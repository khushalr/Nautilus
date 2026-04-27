from __future__ import annotations

from sqlalchemy import select

from app.models import Market, PredictionMarketSnapshot, SportsbookEvent, SportsbookOddsSnapshot
from app.services.collectors.base import CollectionResult, PersistResult, PredictionMarketQuote, SportsbookEventRecord


def persist_prediction_market_quotes(db, quotes: list[PredictionMarketQuote]) -> PersistResult:
    market_ids_seen: set[str] = set()
    snapshots_saved = 0

    for quote in quotes:
        market = db.scalar(
            select(Market).where(Market.source == quote.source, Market.external_id == quote.external_id)
        )
        if market is None:
            market = Market(
                source=quote.source,
                external_id=quote.external_id,
                event_name=quote.event_name,
                league=quote.league,
                market_type=quote.market_type,
                selection=quote.selection,
                normalized_event_key=quote.normalized_event_key,
                start_time=quote.start_time,
                status="open",
                market_url=quote.market_url,
                extra={"raw_market": quote.raw_payload},
            )
            db.add(market)
            db.flush()
        else:
            market.event_name = quote.event_name
            market.league = quote.league
            market.market_type = quote.market_type
            market.selection = quote.selection
            market.normalized_event_key = quote.normalized_event_key
            market.start_time = quote.start_time
            market.status = "open"
            market.market_url = quote.market_url
            market.extra = {"raw_market": quote.raw_payload}

        market_ids_seen.add(market.id)
        db.add(
            PredictionMarketSnapshot(
                market_id=market.id,
                source=quote.source,
                bid_probability=quote.bid_probability,
                ask_probability=quote.ask_probability,
                last_price=quote.last_price,
                midpoint_probability=quote.midpoint_probability,
                spread=quote.spread,
                liquidity=quote.liquidity,
                volume=quote.volume,
                raw_payload=quote.raw_payload,
            )
        )
        snapshots_saved += 1

    db.commit()
    return PersistResult(
        records_saved=snapshots_saved,
        snapshots_saved=snapshots_saved,
        parents_upserted=len(market_ids_seen),
    )


def persist_sportsbook_result(db, result: CollectionResult) -> PersistResult:
    events_by_key: dict[tuple[str, str], SportsbookEvent] = {}
    parents_upserted = 0
    snapshots_saved = 0

    for record in result.sportsbook_events:
        event = _upsert_sportsbook_event(db, record)
        events_by_key[(record.provider, record.provider_event_id)] = event
        parents_upserted += 1

    for line in result.sportsbook_lines:
        event_key = (line.provider, line.provider_event_id)
        event = events_by_key.get(event_key)
        if event is None:
            event = _upsert_sportsbook_event(
                db,
                SportsbookEventRecord(
                    provider=line.provider,
                    provider_event_id=line.provider_event_id,
                    event_name=line.event_name,
                    league=line.league,
                    home_team=line.home_team,
                    away_team=line.away_team,
                    normalized_event_key=line.normalized_event_key,
                    start_time=line.start_time,
                    raw_payload=line.raw_payload.get("event", {}),
                ),
            )
            events_by_key[event_key] = event
            parents_upserted += 1

        db.add(
            SportsbookOddsSnapshot(
                event_id=event.id,
                bookmaker=line.bookmaker,
                market_type=line.market_type,
                selection=line.selection,
                american_odds=line.american_odds,
                decimal_odds=line.decimal_odds,
                implied_probability=line.implied_probability,
                raw_payload=line.raw_payload,
            )
        )
        snapshots_saved += 1

    db.commit()
    return PersistResult(
        records_saved=parents_upserted + snapshots_saved,
        snapshots_saved=snapshots_saved,
        parents_upserted=parents_upserted,
    )


def _upsert_sportsbook_event(db, record: SportsbookEventRecord) -> SportsbookEvent:
    event = db.scalar(
        select(SportsbookEvent).where(
            SportsbookEvent.provider == record.provider,
            SportsbookEvent.provider_event_id == record.provider_event_id,
        )
    )
    if event is None:
        event = SportsbookEvent(
            provider=record.provider,
            provider_event_id=record.provider_event_id,
            event_name=record.event_name,
            league=record.league,
            home_team=record.home_team,
            away_team=record.away_team,
            normalized_event_key=record.normalized_event_key,
            start_time=record.start_time,
            extra={"raw_event": record.raw_payload},
        )
        db.add(event)
        db.flush()
        return event

    event.event_name = record.event_name
    event.league = record.league
    event.home_team = record.home_team
    event.away_team = record.away_team
    event.normalized_event_key = record.normalized_event_key
    event.start_time = record.start_time
    event.extra = {"raw_event": record.raw_payload}
    return event
