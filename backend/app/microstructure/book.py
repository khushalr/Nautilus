"""Venue-specific L2 reconstruction; Decimal preserves Kraken CRC precision."""
from decimal import Decimal
import json
import zlib


class InvalidBook(ValueError):
    """Discard state and obtain a fresh snapshot before generating features."""


def decode(raw):
    return json.loads(raw, parse_float=Decimal)


class Book:
    def __init__(self, venue, depth=10):
        if venue not in {"kraken", "coinbase"} or depth not in {10, 25, 100, 500, 1000}:
            raise ValueError("Unsupported venue/depth")
        self.venue, self.depth = venue, depth
        self.reset()

    def reset(self):
        self.bids, self.asks = {}, {}
        self.ready = False
        self.last_ns = None
        self.previous = None

    @staticmethod
    def _put(side, price, size):
        p, q = Decimal(str(price)), Decimal(str(size))
        if not p.is_finite() or not q.is_finite() or p <= 0 or q < 0:
            raise InvalidBook("Invalid price or quantity")
        if q == 0:
            side.pop(p, None)
        else:
            # Replacing the key preserves the latest wire decimal representation.
            side.pop(p, None)
            side[p] = q

    def checksum(self):
        def digits(value):
            return format(value, "f").replace(".", "").lstrip("0")
        parts = []
        for side, reverse in ((self.asks, False), (self.bids, True)):
            for p in sorted(side, reverse=reverse)[:10]:
                parts.extend((digits(p), digits(side[p])))
        return zlib.crc32("".join(parts).encode()) & 0xffffffff

    def apply(self, message, received_ns):
        """Process in arrival order; neither selected L2 feed has contiguous sequence IDs.

        Kraken validates CRC on every book event. Coinbase Exchange level2_batch
        relies on ordered transport; it has no book checksum or sequence field.
        A disconnect, malformed update, or stale stream requires a new snapshot.
        """
        try:
            return self._apply(message, received_ns)
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            self.reset()
            raise InvalidBook(str(exc)) from exc

    def _apply(self, m, received_ns):
        if not isinstance(received_ns, int) or received_ns < 0:
            raise InvalidBook("Invalid receive timestamp")
        if self.last_ns is not None and received_ns < self.last_ns:
            raise InvalidBook("Receive timestamps moved backwards")
        if self.venue == "kraken":
            if m.get("channel") != "book":
                return False
            if m.get("type") not in {"snapshot", "update"} or len(m["data"]) != 1:
                raise InvalidBook("Unexpected book message")
            d = m["data"][0]
            if d["symbol"] != "BTC/USD":
                raise InvalidBook("Wrong symbol")
            snapshot = m["type"] == "snapshot"
            if snapshot:
                self.reset()
            elif not self.ready:
                raise InvalidBook("Update before snapshot")
            for name in ("bids", "asks"):
                side = getattr(self, name)
                for row in d.get(name, []):
                    self._put(side, row["price"], row["qty"])
                for price in sorted(side, reverse=name == "bids")[self.depth:]:
                    del side[price]
            if self.checksum() != int(d["checksum"]):
                raise InvalidBook("Kraken checksum mismatch")
        else:
            if m.get("type") not in {"snapshot", "l2update"}:
                return False
            if m["product_id"] != "BTC-USD":
                raise InvalidBook("Wrong product")
            snapshot = m["type"] == "snapshot"
            if snapshot:
                self.reset()
                for name in ("bids", "asks"):
                    for p, q in m[name]:
                        self._put(getattr(self, name), p, q)
            else:
                if not self.ready:
                    raise InvalidBook("Update before snapshot")
                for side, p, q in m["changes"]:
                    if side not in {"buy", "sell"}:
                        raise InvalidBook("Unknown side")
                    self._put(self.bids if side == "buy" else self.asks, p, q)
            # Coinbase needs the full snapshot: pruning would lose levels that
            # later become best without another update to those levels.
        if not self.bids or not self.asks or max(self.bids) >= min(self.asks):
            raise InvalidBook("Empty, locked or crossed book")
        self.ready, self.last_ns = True, received_ns
        return True

    def features(self, now_ns, max_age_ns=5_000_000_000):
        if (not self.ready or self.last_ns is None or now_ns < self.last_ns
                or now_ns - self.last_ns > max_age_ns):
            raise InvalidBook("Unavailable or stale book")
        b, a = max(self.bids), min(self.asks)
        qb, qa = self.bids[b], self.asks[a]
        bd = sum(self.bids[p] for p in sorted(self.bids, reverse=True)[:self.depth])
        ad = sum(self.asks[p] for p in sorted(self.asks)[:self.depth])
        ofi = Decimal(0)
        if self.previous is not None:
            pb, pa, pqb, pqa = self.previous
            ofi = (qb if b >= pb else 0) - (pqb if b <= pb else 0)
            ofi -= (qa if a <= pa else 0) - (pqa if a >= pa else 0)
        self.previous = b, a, qb, qa
        return {k: str(v) for k, v in {
            "bid": b, "ask": a, "mid": (a+b)/2, "spread": a-b,
            "bid_depth": bd, "ask_depth": ad, "imbalance": (bd-ad)/(bd+ad),
            "microprice": (a*qb+b*qa)/(qb+qa), "ofi": ofi,
        }.items()}
