from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.collectors.base import CollectionResult, CollectorAdapter, PersistResult, SportsbookEventRecord, SportsbookLine
from app.services.collectors.persistence import persist_sportsbook_result
from app.services.fair_value import american_to_probability, decimal_to_probability
from app.services.normalization import normalized_event_key

logger = logging.getLogger(__name__)


class OddsApiCollector(CollectorAdapter):
    source_name = "odds_api"

    def __init__(self, settings: Settings | None = None, sports: list[str] | None = None) -> None:
        self.settings = settings or get_settings()
        self.sports = sports or self.settings.sports_to_collect
        self.markets = getattr(self.settings, "sportsbook_markets_to_collect", ["h2h", "outrights"])

    async def collect(self) -> CollectionResult:
        if not self.settings.the_odds_api_key:
            message = "Skipping sportsbook odds collection: THE_ODDS_API_KEY is not configured."
            logger.info(message)
            return CollectionResult(ok=False, message=message)

        events: list[SportsbookEventRecord] = []
        lines: list[SportsbookLine] = []
        failures: list[str] = []

        async with httpx.AsyncClient(base_url=str(self.settings.odds_api_url), timeout=25) as client:
            sport_metadata = await self._sport_metadata(client)
            sports_to_collect = _expand_with_related_outright_sports(self.sports, sport_metadata)
            if sports_to_collect != self.sports:
                logger.info("Expanded sportsbook sports for related outrights: %s", sports_to_collect)
            for sport in sports_to_collect:
                try:
                    sport_events, sport_lines = await self._collect_sport(
                        client,
                        sport,
                        sport_metadata.get(sport),
                        outrights_only=sport not in self.sports,
                    )
                except httpx.HTTPError as exc:
                    logger.warning("The Odds API collection failed for %s: %s", sport, exc)
                    failures.append(f"{sport}: {exc}")
                    continue
                events.extend(sport_events)
                lines.extend(sport_lines)

        ok = bool(events or lines) or not failures
        line_types = Counter(line.market_type for line in lines)
        message = f"Collected {len(events)} sportsbook events and {len(lines)} odds lines"
        if failures and not events and not lines:
            message = f"The Odds API collection failed: {'; '.join(failures)}"

        logger.info("%s from The Odds API", message)
        logger.info("The Odds API sportsbook market types collected: %s", dict(sorted(line_types.items())))
        if "outrights" in self.markets and not line_types.get("outrights"):
            logger.info(
                "No sportsbook futures/awards odds were collected. The Odds API only returns "
                "outrights for selected sports/competitions and may not include them on every plan or region."
            )
        return CollectionResult(ok=ok, message=message, sportsbook_events=events, sportsbook_lines=lines)

    def persist(self, db, result: CollectionResult) -> PersistResult:
        saved = persist_sportsbook_result(db, result)
        logger.info(
            "Saved %s sportsbook events and %s odds snapshots",
            saved.parents_upserted,
            saved.snapshots_saved,
        )
        return saved

    async def _collect_sport(
        self,
        client: httpx.AsyncClient,
        sport: str,
        sport_metadata: dict[str, Any] | None,
        outrights_only: bool = False,
    ) -> tuple[list[SportsbookEventRecord], list[SportsbookLine]]:
        markets = _markets_for_sport(self.markets, sport_metadata, outrights_only=outrights_only)
        if not markets:
            logger.info("Skipping %s odds collection: no supported sportsbook markets configured", sport)
            return [], []

        event_params = {"apiKey": self.settings.the_odds_api_key, "dateFormat": "iso"}
        odds_params = {
            "apiKey": self.settings.the_odds_api_key,
            "regions": "us",
            "markets": ",".join(markets),
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
        event_lookup: dict[str, dict[str, Any]] = {}
        try:
            events_response = await client.get(f"/sports/{sport}/events", params=event_params)
            events_response.raise_for_status()
            event_payload = events_response.json()
            event_lookup = {
                str(event.get("id")): event
                for event in event_payload
                if isinstance(event, dict) and event.get("id") is not None
            } if isinstance(event_payload, list) else {}
        except httpx.HTTPError as exc:
            logger.info("The Odds API events endpoint unavailable for %s; continuing with odds payload only: %s", sport, exc)
        odds_response = await client.get(f"/sports/{sport}/odds", params=odds_params)
        odds_response.raise_for_status()

        odds_payload = odds_response.json()

        event_records: dict[str, SportsbookEventRecord] = {}
        lines: list[SportsbookLine] = []
        for event in odds_payload if isinstance(odds_payload, list) else []:
            if not isinstance(event, dict) or event.get("id") is None:
                continue
            record = _event_record_from_payload(
                provider=self.source_name,
                sport=sport,
                event=event,
                events_endpoint_payload=event_lookup.get(str(event.get("id"))),
            )
            event_records[record.provider_event_id] = record

            for bookmaker in event.get("bookmakers", []):
                if not isinstance(bookmaker, dict):
                    continue
                bookmaker_key = bookmaker.get("key") or bookmaker.get("title") or "unknown"
                for market in bookmaker.get("markets", []):
                    if not isinstance(market, dict) or market.get("key") not in markets:
                        continue
                    sportsbook_market_type = str(market.get("key") or "")
                    for outcome in market.get("outcomes", []):
                        if not isinstance(outcome, dict):
                            continue
                        odds_values = _odds_values_from_price(outcome.get("price"))
                        if odds_values is None:
                            continue
                        american, decimal, implied = odds_values
                        lines.append(
                            SportsbookLine(
                                provider=self.source_name,
                                provider_event_id=record.provider_event_id,
                                event_name=record.event_name,
                                league=record.league,
                                home_team=record.home_team,
                                away_team=record.away_team,
                                normalized_event_key=record.normalized_event_key,
                                start_time=record.start_time,
                                bookmaker=str(bookmaker_key),
                                market_type=sportsbook_market_type,
                                selection=str(outcome.get("name") or ""),
                                american_odds=american,
                                decimal_odds=decimal,
                                implied_probability=implied,
                                raw_payload={
                                    "sport_key": sport,
                                    "event": event,
                                    "bookmaker": bookmaker,
                                    "market": market,
                                    "outcome": outcome,
                                },
                            )
                        )

        for event_id, event in event_lookup.items():
            if event_id not in event_records:
                record = _event_record_from_payload(
                    provider=self.source_name,
                    sport=sport,
                    event=event,
                    events_endpoint_payload=event,
                )
                event_records[record.provider_event_id] = record

        return list(event_records.values()), lines

    async def _sport_metadata(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        try:
            response = await client.get("/sports", params={"apiKey": self.settings.the_odds_api_key})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("Could not load The Odds API sport metadata; requesting configured markets directly: %s", exc)
            return {}
        payload = response.json()
        if not isinstance(payload, list):
            return {}
        return {
            str(sport.get("key")): sport
            for sport in payload
            if isinstance(sport, dict) and sport.get("key")
        }


def _event_record_from_payload(
    *,
    provider: str,
    sport: str,
    event: dict[str, Any],
    events_endpoint_payload: dict[str, Any] | None = None,
) -> SportsbookEventRecord:
    home_team = _as_str(event.get("home_team") or (events_endpoint_payload or {}).get("home_team"))
    away_team = _as_str(event.get("away_team") or (events_endpoint_payload or {}).get("away_team"))
    start_time = _parse_datetime(event.get("commence_time") or (events_endpoint_payload or {}).get("commence_time"))
    league = _as_str(event.get("sport_title") or (events_endpoint_payload or {}).get("sport_title") or sport)
    event_name = f"{away_team} at {home_team}" if home_team and away_team else str(league or event.get("id"))
    event_key = (
        normalized_event_key(league, [home_team or "", away_team or ""], start_time)
        if home_team and away_team
        else normalized_event_key(league, [str(league or sport)], start_time)
    )
    return SportsbookEventRecord(
        provider=provider,
        provider_event_id=str(event.get("id")),
        event_name=event_name,
        league=league,
        home_team=home_team,
        away_team=away_team,
        normalized_event_key=event_key,
        start_time=start_time,
        raw_payload={
            "sport_key": sport,
            "events_endpoint": events_endpoint_payload,
            "odds_endpoint": event,
        },
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _odds_values_from_price(value: object) -> tuple[int | None, float | None, float] | None:
    if value is None:
        return None

    text_value = value.strip() if isinstance(value, str) else None
    if text_value and (text_value.startswith("+") or text_value.startswith("-")):
        american = _as_int(text_value)
        if american is None:
            return None
        return american, _american_to_decimal(american), american_to_probability(american)

    number = _as_float(value)
    if number is None:
        return None

    if number <= -100 or number >= 100:
        american = int(number)
        return american, _american_to_decimal(american), american_to_probability(american)

    if number > 1:
        return None, number, decimal_to_probability(number)

    return None


def _american_to_decimal(odds: int) -> float:
    if odds < 0:
        return 1 + (100 / abs(odds))
    return 1 + (odds / 100)


def _markets_for_sport(
    configured_markets: list[str],
    sport_metadata: dict[str, Any] | None,
    *,
    outrights_only: bool = False,
) -> list[str]:
    requested = [market for market in configured_markets if market in {"h2h", "outrights"}]
    if outrights_only:
        return ["outrights"] if "outrights" in requested else []
    if "outrights" not in requested:
        return requested
    if sport_metadata and sport_metadata.get("has_outrights") is False:
        logger.info(
            "Skipping outrights for %s: The Odds API sport metadata has has_outrights=false",
            sport_metadata.get("key") or sport_metadata.get("title") or "configured sport",
        )
        return [market for market in requested if market != "outrights"]
    return requested


def _expand_with_related_outright_sports(
    configured_sports: list[str],
    sport_metadata: dict[str, dict[str, Any]],
) -> list[str]:
    if not sport_metadata:
        return configured_sports
    expanded = list(configured_sports)
    configured_set = set(configured_sports)
    for configured in configured_sports:
        configured_prefix = configured.rstrip("_")
        for sport_key, metadata in sport_metadata.items():
            if sport_key in configured_set or sport_key in expanded:
                continue
            if not metadata.get("active") or not metadata.get("has_outrights"):
                continue
            if sport_key.startswith(f"{configured_prefix}_"):
                expanded.append(sport_key)
    return expanded
