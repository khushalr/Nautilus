from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.core.config import Settings, get_settings
from app.services.collectors.base import CollectionResult, CollectorAdapter, PersistResult, PredictionMarketQuote
from app.services.collectors.persistence import persist_prediction_market_quotes
from app.services.fair_value import calculate_market_midpoint
from app.services.market_classification import classify_prediction_market, market_priority
from app.services.normalization import normalized_event_key_from_name

logger = logging.getLogger(__name__)


class KalshiCollector(CollectorAdapter):
    source_name = "kalshi"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def collect(self) -> CollectionResult:
        headers = {}
        if self.settings.kalshi_api_key:
            headers["Authorization"] = f"Bearer {self.settings.kalshi_api_key}"
        try:
            async with httpx.AsyncClient(base_url=str(self.settings.kalshi_api_url), timeout=20) as client:
                response = await client.get(
                    "/markets",
                    headers=headers,
                    params={"status": "open", "limit": 200},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            if not self.settings.kalshi_api_key:
                message = (
                    "Skipping Kalshi collection: public /markets endpoint is unavailable "
                    f"or requires authentication ({exc})."
                )
                logger.info(message)
                return CollectionResult(ok=False, message=message)
            logger.warning("Kalshi collection failed: %s", exc)
            return CollectionResult(ok=False, message=f"Kalshi collection failed: {exc}")

        payload = response.json()
        raw_markets = payload.get("markets", []) if isinstance(payload, dict) else []
        quotes: list[PredictionMarketQuote] = []
        for item in raw_markets:
            if not isinstance(item, dict) or not _is_sports_market(item):
                continue
            event_name = str(item.get("title") or item.get("subtitle") or item.get("ticker") or "Unknown event")
            bid = _cent_probability(item.get("yes_bid"))
            ask = _cent_probability(item.get("yes_ask"))
            last = _cent_probability(item.get("last_price"))
            start_time = _parse_datetime(
                item.get("close_time")
                or item.get("expiration_time")
                or item.get("expected_expiration_time")
                or item.get("open_time")
            )
            league = item.get("category")
            market_type = classify_prediction_market(
                title=event_name,
                selection="Yes",
                league=league,
                start_time=start_time,
                raw_payload=item,
            )
            try:
                midpoint = calculate_market_midpoint(bid, ask, last)
            except ValueError:
                continue
            spread = abs(ask - bid) if bid is not None and ask is not None else None
            quotes.append(
                PredictionMarketQuote(
                    source=self.source_name,
                    external_id=str(item.get("ticker") or event_name),
                    event_name=event_name,
                    league=league,
                    market_type=market_type,
                    selection="Yes",
                    normalized_event_key=normalized_event_key_from_name(league, event_name, start_time),
                    start_time=start_time,
                    bid_probability=bid,
                    ask_probability=ask,
                    last_price=last,
                    midpoint_probability=midpoint,
                    spread=spread,
                    liquidity=_as_float(item.get("liquidity")),
                    volume=_as_float(item.get("volume")),
                    market_url=item.get("url"),
                    raw_payload=item,
                )
            )
        quotes.sort(key=lambda quote: market_priority(quote.market_type, quote.start_time))

        logger.info("Collected %s Kalshi markets", len(quotes))
        return CollectionResult(ok=True, message=f"Collected {len(quotes)} Kalshi markets", prediction_markets=quotes)

    def persist(self, db, result: CollectionResult) -> PersistResult:
        saved = persist_prediction_market_quotes(db, result.prediction_markets)
        logger.info(
            "Saved %s Kalshi market records and %s prediction snapshots",
            saved.parents_upserted,
            saved.snapshots_saved,
        )
        return saved


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _cent_probability(value: object) -> float | None:
    number = _as_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number / 100))


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_sports_market(item: dict) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "subtitle", "category", "event_ticker", "series_ticker", "ticker")
    ).lower()
    return any(
        term in text
        for term in (
            "sports",
            "nfl",
            "nba",
            "mlb",
            "nhl",
            "football",
            "basketball",
            "baseball",
            "hockey",
            "soccer",
        )
    )
