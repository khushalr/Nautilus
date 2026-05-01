from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import HistoricalPredictionMarketPriceSnapshot, Market
from app.services.backtesting import market_yes_price_from_raw
from app.services.market_classification import effective_prediction_market_type

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    args = _parse_args()
    saved = asyncio.run(_collect(args))
    logger.info("Stored %s historical Polymarket price snapshots", saved)


async def _collect(args) -> int:
    settings = get_settings()
    with SessionLocal() as db:
        markets = _markets_to_collect(db, args.market_id, args.limit)
    saved = 0
    async with httpx.AsyncClient(base_url=str(settings.polymarket_clob_api_url), timeout=30) as client:
        for market in markets:
            token_id = _token_id_for_market(market)
            if not token_id:
                logger.info("Skipping %s: no Polymarket token id found in raw metadata", market.id)
                continue
            prices = await _fetch_prices(
                client,
                token_id=token_id,
                start=_parse_datetime_arg(args.date_start),
                end=_parse_datetime_arg(args.date_end),
                fidelity=args.fidelity_minutes,
            )
            if not prices:
                logger.info("No historical Polymarket prices returned for %s token=%s", market.id, token_id)
                continue
            saved += _persist_prices(market.id, token_id, market, prices)
    return saved


async def _fetch_prices(
    client: httpx.AsyncClient,
    *,
    token_id: str,
    start: datetime,
    end: datetime,
    fidelity: int,
) -> list[dict[str, Any]]:
    params = {
        "market": token_id,
        "startTs": int(start.timestamp()),
        "endTs": int(end.timestamp()),
        "fidelity": fidelity,
    }
    response = await client.get("/prices-history", params=params)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("Polymarket price history request failed for token=%s: %s", token_id, exc)
        return []
    payload = response.json()
    history = payload.get("history") if isinstance(payload, dict) else payload
    return history if isinstance(history, list) else []


def _persist_prices(market_id: str, token_id: str, market: Market, prices: list[dict[str, Any]]) -> int:
    market_type = effective_prediction_market_type(market)
    raw_selection = market.selection
    display_outcome = _display_outcome(market)
    records: list[HistoricalPredictionMarketPriceSnapshot] = []
    for item in prices:
        parsed = _parse_price_item(item)
        if parsed is None:
            continue
        timestamp, raw_price = parsed
        market_yes_price, orientation = market_yes_price_from_raw(raw_price, raw_selection, market_type, display_outcome)
        records.append(
            HistoricalPredictionMarketPriceSnapshot(
                market_id=market_id,
                source=market.source,
                token_id=token_id,
                raw_selection=raw_selection,
                display_outcome=display_outcome,
                raw_price=raw_price,
                market_yes_price=market_yes_price,
                orientation=orientation,
                liquidity=None,
                volume=None,
                timestamp=timestamp,
                raw_payload=item,
            )
        )
    if not records:
        return 0
    with SessionLocal() as db:
        for record in records:
            exists = db.scalar(
                select(HistoricalPredictionMarketPriceSnapshot.id)
                .where(HistoricalPredictionMarketPriceSnapshot.market_id == record.market_id)
                .where(HistoricalPredictionMarketPriceSnapshot.token_id == record.token_id)
                .where(HistoricalPredictionMarketPriceSnapshot.timestamp == record.timestamp)
                .limit(1)
            )
            if exists is None:
                db.add(record)
        db.commit()
    return len(records)


def _markets_to_collect(db, market_id: str | None, limit: int) -> list[Market]:
    stmt = select(Market).where(Market.source == "polymarket").limit(limit)
    if market_id:
        stmt = stmt.where(Market.id == market_id)
    return list(db.scalars(stmt))


def _token_id_for_market(market: Market) -> str | None:
    raw = market.extra.get("raw_market") if isinstance(market.extra, dict) else None
    payload = raw.get("market") if isinstance(raw, dict) and isinstance(raw.get("market"), dict) else raw
    if not isinstance(payload, dict):
        return None
    outcome_index = int(raw.get("outcome_index", 0)) if isinstance(raw, dict) else 0
    for key in ("clobTokenIds", "clob_token_ids", "tokenIds", "token_ids"):
        values = _jsonish_list(payload.get(key))
        if outcome_index < len(values):
            return str(values[outcome_index])
    value = payload.get("token_id") or payload.get("tokenId")
    return str(value) if value else None


def _jsonish_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _parse_price_item(item: object) -> tuple[datetime, float] | None:
    if not isinstance(item, dict):
        return None
    timestamp_value = item.get("t") or item.get("timestamp")
    price_value = item.get("p") or item.get("price")
    try:
        timestamp = datetime.fromtimestamp(float(timestamp_value), tz=UTC)
        price = float(price_value)
    except (TypeError, ValueError, OSError):
        return None
    return timestamp, max(0.0, min(1.0, price))


def _display_outcome(market: Market) -> str | None:
    if market.selection.lower() not in {"yes", "no"}:
        return market.selection
    title = market.event_name
    lower = title.lower()
    for delimiter in (" beat ", " beats ", " defeat ", " defeats ", " win ", " make ", " reach "):
        if lower.startswith("will ") and delimiter in lower:
            return title[len("will "): lower.find(delimiter, len("will "))].strip(" ?") or None
    return None


def _parse_datetime_arg(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_args():
    parser = argparse.ArgumentParser(description="Collect historical Polymarket YES/NO token prices.")
    parser.add_argument("--market-id")
    parser.add_argument("--date-start", required=True)
    parser.add_argument("--date-end", required=True)
    parser.add_argument("--fidelity-minutes", type=int, default=60)
    parser.add_argument("--limit", type=int, default=25)
    return parser.parse_args()


if __name__ == "__main__":
    main()
