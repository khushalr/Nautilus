"""Bounded public WebSocket recorder; no credentials, broker or order submission."""
import argparse
import asyncio
import json
import time
from pathlib import Path
from .book import Book, InvalidBook, decode


async def capture(venue, output, seconds):
    import websockets
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    url = ("wss://ws.kraken.com/v2" if venue == "kraken"
           else "wss://ws-feed.exchange.coinbase.com")
    subscriptions = (
        [{"method": "subscribe", "params": {"channel": c, "symbol": ["BTC/USD"],
          **({"depth": 10} if c == "book" else {})}} for c in ("book", "trade")]
        if venue == "kraken" else
        [{"type": "subscribe", "product_ids": ["BTC-USD"],
          "channels": ["level2_batch", "matches", "heartbeat"]}]
    )
    deadline = time.monotonic() + seconds
    session = 0
    # Exclusive create: do not mix runs or overwrite a historical capture.
    with Path(output).open("x", encoding="utf-8") as sink:
        while time.monotonic() < deadline:
            book = Book(venue)
            session += 1
            try:
                async with websockets.connect(url, open_timeout=10, max_size=16_000_000) as ws:
                    for subscription in subscriptions:
                        await ws.send(json.dumps(subscription))
                    connected = time.monotonic_ns()
                    while time.monotonic() < deadline:
                        raw = await asyncio.wait_for(ws.recv(), timeout=min(5, max(.01, deadline-time.monotonic())))
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8")
                        received = time.time_ns()
                        m = decode(raw)
                        if m.get("type") == "error" or m.get("success") is False:
                            raise InvalidBook("Subscription rejected: " + raw)
                        # Staleness is measured separately from heartbeats/trades.
                        if book.ready and received - book.last_ns > 5_000_000_000:
                            raise InvalidBook("Book stale; reconnect for fresh snapshot")
                        if not book.ready and time.monotonic_ns()-connected > 10_000_000_000:
                            raise InvalidBook("Snapshot timeout")
                        sink.write(json.dumps({"venue": venue, "session": session,
                                   "received_ns": received, "raw": raw}) + "\n")
                        sink.flush()
                        if book.apply(m, received):
                            print(json.dumps(book.features(received)), flush=True)
            except (OSError, asyncio.TimeoutError, InvalidBook, websockets.exceptions.ConnectionClosed) as exc:
                print(f"Session {session} invalidated: {exc}", flush=True)
                # The raw offending record stays in the audit log. Strict replay
                # deliberately rejects it; never silently hide corrupt history.
                await asyncio.sleep(min(1, max(0, deadline-time.monotonic())))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--venue", choices=["kraken", "coinbase"], required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--seconds", type=float, default=60)
    a = p.parse_args()
    asyncio.run(capture(a.venue, a.output, a.seconds))
