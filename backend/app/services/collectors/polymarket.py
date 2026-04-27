from __future__ import annotations

import logging
import json
from datetime import datetime
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.collectors.base import CollectionResult, CollectorAdapter, PersistResult, PredictionMarketQuote
from app.services.collectors.persistence import persist_prediction_market_quotes
from app.services.fair_value import calculate_market_midpoint
from app.services.normalization import normalized_event_key_from_name, slugify

logger = logging.getLogger(__name__)


class PolymarketCollector(CollectorAdapter):
    source_name = "polymarket"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def collect(self) -> CollectionResult:
        try:
            async with httpx.AsyncClient(base_url=str(self.settings.polymarket_api_url), timeout=20) as client:
                response = await client.get(
                    "/markets",
                    params={
                        "active": "true",
                        "closed": "false",
                        "archived": "false",
                        "limit": 250,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Polymarket collection failed: %s", exc)
            return CollectionResult(ok=False, message=f"Polymarket collection failed: {exc}")

        payload = response.json()
        raw_markets = payload if isinstance(payload, list) else payload.get("data", payload.get("markets", []))
        quotes: list[PredictionMarketQuote] = []
        for item in raw_markets:
            if not isinstance(item, dict):
                continue
            if not _is_sports_market(item):
                continue
            quotes.extend(_quotes_from_market(item, self.source_name))

        logger.info("Collected %s Polymarket markets", len(quotes))
        return CollectionResult(ok=True, message=f"Collected {len(quotes)} Polymarket markets", prediction_markets=quotes)

    def persist(self, db, result: CollectionResult) -> PersistResult:
        saved = persist_prediction_market_quotes(db, result.prediction_markets)
        logger.info(
            "Saved %s Polymarket market records and %s prediction snapshots",
            saved.parents_upserted,
            saved.snapshots_saved,
        )
        return saved


def _quotes_from_market(item: dict[str, Any], source_name: str) -> list[PredictionMarketQuote]:
    event_name = str(
        item.get("question")
        or item.get("title")
        or item.get("market_slug")
        or item.get("slug")
        or "Unknown event"
    )
    base_external_id = str(
        item.get("condition_id")
        or item.get("conditionId")
        or item.get("id")
        or item.get("market_slug")
        or item.get("slug")
        or event_name
    )
    league = _category(item)
    start_time = _parse_datetime(item.get("startDate") or item.get("start_date") or item.get("gameStartTime"))
    outcomes = _list_from_jsonish(item.get("outcomes")) or [item.get("outcome") or item.get("selection") or "Yes"]
    outcome_prices = _list_from_jsonish(
        item.get("outcomePrices")
        or item.get("outcome_prices")
        or item.get("prices")
    )
    quotes: list[PredictionMarketQuote] = []

    for index, outcome in enumerate(outcomes):
        selection = str(outcome)
        bid = _as_probability(_first_present(item, ("best_bid", "bestBid", "bid")))
        ask = _as_probability(_first_present(item, ("best_ask", "bestAsk", "ask")))
        if len(outcomes) > 1 and index > 0 and not _has_outcome_level_quotes(item):
            bid = None
            ask = None

        outcome_price = outcome_prices[index] if index < len(outcome_prices) else None
        last_price = _as_probability(
            outcome_price
            if outcome_price is not None
            else _first_present(item, ("last_trade_price", "lastPrice", "last_price", "price"))
        )
        try:
            midpoint = calculate_market_midpoint(bid, ask, last_price)
        except ValueError:
            continue

        spread = abs(ask - bid) if bid is not None and ask is not None else None
        quotes.append(
            PredictionMarketQuote(
                source=source_name,
                external_id=f"{base_external_id}:{slugify(selection)}",
                event_name=event_name,
                league=league,
                market_type=str(item.get("market_type") or item.get("marketType") or "binary"),
                selection=selection,
                normalized_event_key=normalized_event_key_from_name(league, event_name, start_time),
                start_time=start_time,
                bid_probability=bid,
                ask_probability=ask,
                last_price=last_price,
                midpoint_probability=midpoint,
                spread=spread,
                liquidity=_as_float(item.get("liquidity") or item.get("liquidityNum") or item.get("liquidity_num")),
                volume=_as_float(item.get("volume") or item.get("volumeNum") or item.get("volume_num")),
                market_url=item.get("market_url") or item.get("url"),
                raw_payload={"market": item, "outcome": selection, "outcome_index": index},
            )
        )
    return quotes


def _is_sports_market(item: dict[str, Any]) -> bool:
    text_bits = [
        str(item.get("category") or ""),
        str(item.get("question") or ""),
        str(item.get("title") or ""),
        str(item.get("description") or ""),
        json.dumps(item.get("tags", ""), default=str),
    ]
    haystack = " ".join(text_bits).lower()
    sports_terms = {
        "sports",
        "nfl",
        "nba",
        "mlb",
        "nhl",
        "soccer",
        "football",
        "basketball",
        "baseball",
        "hockey",
        "ufc",
        "tennis",
        "golf",
        "fifa",
        "premier league",
    }
    return any(term in haystack for term in sports_terms)


def _category(item: dict[str, Any]) -> str | None:
    category = item.get("category")
    if isinstance(category, str) and category:
        return category
    tags = item.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict) and tag.get("label"):
                label = str(tag["label"])
                if label.lower() != "sports":
                    return label
            if isinstance(tag, str) and tag.lower() != "sports":
                return tag
    return "sports"


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _list_from_jsonish(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _first_present(item: dict[str, Any], keys: tuple[str, ...]) -> object:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def _has_outcome_level_quotes(item: dict[str, Any]) -> bool:
    return any(key in item for key in ("outcomeBids", "outcomeAsks", "outcome_bids", "outcome_asks"))


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_probability(value: object) -> float | None:
    number = _as_float(value)
    if number is None:
        return None
    if number > 1:
        number = number / 100
    return max(0.0, min(1.0, number))
