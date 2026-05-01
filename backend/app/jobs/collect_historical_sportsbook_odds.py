from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import HistoricalSportsbookOddsSnapshot
from app.services.backtesting import estimate_historical_odds_credits, iter_time_range
from app.services.collectors.odds_api import _event_record_from_payload, _odds_values_from_price
from app.services.odds_quota import maybe_notify_low_quota, notify_quota_failure, parse_quota_headers, redact_api_key

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    date_start = _parse_datetime_arg(args.date_start)
    date_end = _parse_datetime_arg(args.date_end)
    markets = [args.market]
    estimate = estimate_historical_odds_credits(
        date_start=date_start,
        date_end=date_end,
        interval_minutes=args.interval_minutes,
        markets=markets,
        regions=args.regions,
    )
    logger.info("Estimated historical Odds API credit cost: %s", estimate)
    if estimate > 24 and not args.yes:
        raise SystemExit("Refusing larger historical collection without --yes. Reduce the date range or pass --yes.")
    if not settings.the_odds_api_key:
        raise SystemExit("THE_ODDS_API_KEY is not configured.")

    saved = asyncio.run(_collect(args, settings, date_start, date_end))
    logger.info("Stored %s historical sportsbook odds snapshots", saved)


async def _collect(args, settings, date_start: datetime, date_end: datetime) -> int:
    saved = 0
    async with httpx.AsyncClient(base_url=str(settings.odds_api_url), timeout=30) as client:
        for timestamp in iter_time_range(date_start, date_end, args.interval_minutes):
            params = {
                "apiKey": settings.the_odds_api_key,
                "regions": args.regions,
                "markets": args.market,
                "oddsFormat": "american",
                "dateFormat": "iso",
                "date": timestamp.isoformat().replace("+00:00", "Z"),
            }
            if args.bookmakers:
                params["bookmakers"] = args.bookmakers
            response = await client.get(f"/historical/sports/{args.sport}/odds", params=params)
            maybe_notify_low_quota(settings, parse_quota_headers(response.headers), context=f"historical {args.sport}/{args.market}")
            if response.status_code == 429 or "OUT_OF_USAGE_CREDITS" in response.text[:1000]:
                notify_quota_failure(settings, reason=f"status={response.status_code} body={response.text[:500]}", context="historical sportsbook odds")
                logger.warning("Historical Odds API quota/rate limit: %s", redact_api_key(response.text[:500]))
                break
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("Historical Odds API request failed: %s", redact_api_key(str(exc)))
                continue
            payload = response.json()
            snapshot_timestamp = _payload_timestamp(payload) or timestamp
            events = payload.get("data") if isinstance(payload, dict) else payload
            saved += _persist_payload(args.sport, args.market, snapshot_timestamp, events if isinstance(events, list) else [])
    return saved


def _persist_payload(sport: str, market_type: str, snapshot_timestamp: datetime, events: list[dict[str, Any]]) -> int:
    records: list[HistoricalSportsbookOddsSnapshot] = []
    for event in events:
        if not isinstance(event, dict) or event.get("id") is None:
            continue
        record = _event_record_from_payload(provider="odds_api", sport=sport, event=event, events_endpoint_payload=None)
        for bookmaker in event.get("bookmakers", []):
            if not isinstance(bookmaker, dict):
                continue
            bookmaker_key = str(bookmaker.get("key") or bookmaker.get("title") or "unknown")
            for market in bookmaker.get("markets", []):
                if not isinstance(market, dict) or market.get("key") != market_type:
                    continue
                for outcome in market.get("outcomes", []):
                    if not isinstance(outcome, dict):
                        continue
                    odds_values = _odds_values_from_price(outcome.get("price"))
                    if odds_values is None:
                        continue
                    american, decimal, implied = odds_values
                    records.append(
                        HistoricalSportsbookOddsSnapshot(
                            provider="odds_api",
                            provider_event_id=record.provider_event_id,
                            event_name=record.event_name,
                            league=record.league,
                            home_team=record.home_team,
                            away_team=record.away_team,
                            normalized_event_key=record.normalized_event_key,
                            start_time=record.start_time,
                            bookmaker=bookmaker_key,
                            market_type=market_type,
                            selection=str(outcome.get("name") or ""),
                            american_odds=american,
                            decimal_odds=decimal,
                            implied_probability=implied,
                            snapshot_timestamp=snapshot_timestamp,
                            raw_payload={"sport_key": sport, "event": event, "bookmaker": bookmaker, "market": market, "outcome": outcome},
                        )
                    )
    if not records:
        return 0
    with SessionLocal() as db:
        for record in records:
            db.add(record)
        db.commit()
    return len(records)


def _payload_timestamp(payload: object) -> datetime | None:
    if not isinstance(payload, dict):
        return None
    for key in ("timestamp", "date"):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
    return None


def _parse_datetime_arg(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_args():
    parser = argparse.ArgumentParser(description="Collect historical sportsbook odds snapshots from The Odds API.")
    parser.add_argument("--sport", required=True)
    parser.add_argument("--market", required=True, choices=["h2h", "outrights"])
    parser.add_argument("--date-start", required=True)
    parser.add_argument("--date-end", required=True)
    parser.add_argument("--interval-minutes", type=int, default=60)
    parser.add_argument("--regions", default="us")
    parser.add_argument("--bookmakers")
    parser.add_argument("--yes", action="store_true", help="Confirm historical Odds API credit usage.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
