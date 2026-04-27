from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.models import Market, PredictionMarketSnapshot, SportsbookEvent, SportsbookOddsSnapshot
from app.services.collectors.base import CollectionResult, PredictionMarketQuote, SportsbookEventRecord, SportsbookLine
from app.services.collectors.odds_api import OddsApiCollector
from app.services.collectors.polymarket import PolymarketCollector, _quotes_from_market
from app.services.fair_value import american_to_probability, decimal_to_probability


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with SessionLocal() as session:
        yield session


def test_odds_conversion() -> None:
    assert american_to_probability(-150) == pytest.approx(0.6)
    assert american_to_probability(200) == pytest.approx(1 / 3)
    assert decimal_to_probability(2.5) == pytest.approx(0.4)


def test_polymarket_duplicate_market_upsert_inserts_new_snapshots(db_session) -> None:
    collector = PolymarketCollector()
    quote = _prediction_quote(event_name="Lakers vs Celtics", last_price=0.58)
    updated_quote = _prediction_quote(event_name="Los Angeles Lakers vs Boston Celtics", last_price=0.61)

    first_save = collector.persist(db_session, CollectionResult(ok=True, message="ok", prediction_markets=[quote]))
    second_save = collector.persist(db_session, CollectionResult(ok=True, message="ok", prediction_markets=[updated_quote]))

    assert first_save.snapshots_saved == 1
    assert second_save.snapshots_saved == 1
    assert db_session.scalar(select(func.count()).select_from(Market)) == 1
    assert db_session.scalar(select(func.count()).select_from(PredictionMarketSnapshot)) == 2

    market = db_session.scalar(select(Market))
    latest_snapshot = db_session.scalars(
        select(PredictionMarketSnapshot).order_by(PredictionMarketSnapshot.observed_at.desc())
    ).first()
    assert market is not None
    assert latest_snapshot is not None
    assert market.event_name == "Los Angeles Lakers vs Boston Celtics"
    assert latest_snapshot.bid_probability is None
    assert latest_snapshot.ask_probability is None
    assert latest_snapshot.last_price == pytest.approx(0.61)


def test_sportsbook_event_upsert_inserts_new_snapshots(db_session) -> None:
    collector = OddsApiCollector(
        settings=SimpleNamespace(
            the_odds_api_key="test-key",
            odds_api_url="https://example.test",
            sports_to_collect=["basketball_nba"],
        )
    )
    result = CollectionResult(
        ok=True,
        message="ok",
        sportsbook_events=[
            SportsbookEventRecord(
                provider="odds_api",
                provider_event_id="evt-1",
                event_name="Knicks at Celtics",
                league="NBA",
                home_team="Boston Celtics",
                away_team="New York Knicks",
                normalized_event_key="nba:2026-05-01:bos-vs-nyk",
                start_time=datetime(2026, 5, 1, tzinfo=UTC),
                raw_payload={"id": "evt-1"},
            )
        ],
        sportsbook_lines=[
            SportsbookLine(
                provider="odds_api",
                provider_event_id="evt-1",
                event_name="Knicks at Celtics",
                league="NBA",
                home_team="Boston Celtics",
                away_team="New York Knicks",
                normalized_event_key="nba:2026-05-01:bos-vs-nyk",
                start_time=datetime(2026, 5, 1, tzinfo=UTC),
                bookmaker="draftkings",
                market_type="moneyline",
                selection="Boston Celtics",
                american_odds=-125,
                decimal_odds=1.8,
                implied_probability=american_to_probability(-125),
                raw_payload={"outcome": {"name": "Boston Celtics", "price": -125}},
            )
        ],
    )

    collector.persist(db_session, result)
    collector.persist(db_session, result)

    assert db_session.scalar(select(func.count()).select_from(SportsbookEvent)) == 1
    assert db_session.scalar(select(func.count()).select_from(SportsbookOddsSnapshot)) == 2
    snapshot = db_session.scalar(select(SportsbookOddsSnapshot))
    assert snapshot is not None
    assert snapshot.raw_payload["outcome"]["price"] == -125


def test_polymarket_outcome_price_becomes_last_price_without_bid_ask() -> None:
    quotes = _quotes_from_market(
        {
            "id": "pm-1",
            "question": "Will the Boston Celtics win?",
            "category": "NBA",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.42", "0.58"]',
            "liquidity": "1200",
            "volume": "9000",
        },
        "polymarket",
    )

    assert len(quotes) == 2
    assert quotes[0].bid_probability is None
    assert quotes[0].ask_probability is None
    assert quotes[0].last_price == pytest.approx(0.42)
    assert quotes[0].midpoint_probability == pytest.approx(0.42)


def test_odds_api_missing_key_fails_gracefully() -> None:
    collector = OddsApiCollector(
        settings=SimpleNamespace(
            the_odds_api_key=None,
            odds_api_url="https://example.test",
            sports_to_collect=["americanfootball_nfl"],
        )
    )

    result = asyncio.run(collector.collect())

    assert result.ok is False
    assert "THE_ODDS_API_KEY" in result.message
    assert result.sportsbook_events == []
    assert result.sportsbook_lines == []


def _prediction_quote(event_name: str, last_price: float) -> PredictionMarketQuote:
    return PredictionMarketQuote(
        source="polymarket",
        external_id="market-1:yes",
        event_name=event_name,
        league="NBA",
        market_type="binary",
        selection="Yes",
        normalized_event_key="nba:2026-05-01:bos-vs-lal",
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        bid_probability=None,
        ask_probability=None,
        last_price=last_price,
        midpoint_probability=last_price,
        spread=None,
        liquidity=1500,
        volume=10000,
        market_url="https://polymarket.com/event/example",
        raw_payload={"id": "market-1", "last_price": last_price},
    )
