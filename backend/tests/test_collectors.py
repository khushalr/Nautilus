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
from app.services.collectors.odds_api import (
    OddsApiCollector,
    _expand_with_related_outright_sports,
    _markets_for_sport,
    _odds_values_from_price,
)
from app.services.collectors.polymarket import PolymarketCollector, _quotes_from_market
from app.services.fair_value import american_to_probability, decimal_to_probability
from app.services.market_classification import classify_prediction_market, effective_prediction_market_type
from app.services.odds_quota import parse_quota_headers, redact_api_key, should_send_quota_email, mark_quota_email_sent
from app.services.opportunity_status import opportunity_status_label


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


def test_american_odds_implied_probability_examples() -> None:
    assert american_to_probability(400) == pytest.approx(0.20)
    assert american_to_probability(-150) == pytest.approx(0.60)


def test_decimal_odds_implied_probability_examples() -> None:
    assert decimal_to_probability(5.00) == pytest.approx(0.20)


def test_two_way_no_vig_normalization_example() -> None:
    from app.services.fair_value import remove_vig_two_way

    side_a, side_b = remove_vig_two_way(0.58, 0.48)

    assert side_a == pytest.approx(0.5471698)
    assert side_b == pytest.approx(0.4528302)


def test_opportunity_status_labels() -> None:
    assert opportunity_status_label(0.02) == "Possible YES underpricing"
    assert opportunity_status_label(-0.02) == "Possible YES overpricing"
    assert opportunity_status_label(0.0001) == "Near fair value"


def test_odds_api_quota_header_parsing_and_redaction() -> None:
    quota = parse_quota_headers(
        {
            "x-requests-remaining": "49",
            "x-requests-used": "451",
            "x-requests-last": "2",
        }
    )

    assert quota.remaining == 49
    assert quota.used == 451
    assert quota.last == 2
    assert "secret" not in redact_api_key("https://api.example.test?apiKey=secret&markets=h2h")


def test_odds_api_quota_email_cooldown(tmp_path) -> None:
    state_file = tmp_path / "quota.json"
    now = datetime(2026, 4, 27, 12, tzinfo=UTC)

    assert should_send_quota_email(state_file=str(state_file), cooldown_hours=6, now=now)
    mark_quota_email_sent(state_file=str(state_file), now=now)
    assert not should_send_quota_email(state_file=str(state_file), cooldown_hours=6, now=now)
    assert should_send_quota_email(state_file=str(state_file), cooldown_hours=6, now=now.replace(hour=19))


def test_odds_api_outrights_market_support_uses_sport_metadata() -> None:
    assert _markets_for_sport(["h2h", "outrights"], {"key": "basketball_nba", "has_outrights": True}) == [
        "h2h",
        "outrights",
    ]
    assert _markets_for_sport(["h2h", "outrights"], {"key": "baseball_mlb", "has_outrights": False}) == [
        "h2h"
    ]
    assert _markets_for_sport(
        ["h2h", "outrights"],
        {"key": "basketball_nba_championship_winner", "has_outrights": True},
        outrights_only=True,
    ) == ["outrights"]


def test_odds_api_expands_configured_sports_with_related_outrights() -> None:
    assert _expand_with_related_outright_sports(
        ["basketball_nba"],
        {
            "basketball_nba": {"key": "basketball_nba", "active": True, "has_outrights": False},
            "basketball_nba_championship_winner": {
                "key": "basketball_nba_championship_winner",
                "active": True,
                "has_outrights": True,
            },
            "icehockey_nhl_championship_winner": {
                "key": "icehockey_nhl_championship_winner",
                "active": True,
                "has_outrights": True,
            },
        },
    ) == ["basketball_nba", "basketball_nba_championship_winner"]


def test_decimal_outright_price_is_supported() -> None:
    american, decimal, implied = _odds_values_from_price(11.0)

    assert american is None
    assert decimal == pytest.approx(11.0)
    assert implied == pytest.approx(1 / 11)


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


def test_polymarket_classifies_h2h_and_futures() -> None:
    start_time = datetime(2026, 5, 1, tzinfo=UTC)
    h2h_quotes = _quotes_from_market(
        {
            "id": "pm-h2h",
            "question": "Los Angeles Lakers vs Boston Celtics",
            "category": "NBA",
            "startDate": start_time.isoformat(),
            "outcomes": '["Los Angeles Lakers", "Boston Celtics"]',
            "outcomePrices": '["0.48", "0.52"]',
        },
        "polymarket",
    )
    futures_quotes = _quotes_from_market(
        {
            "id": "pm-futures",
            "question": "Will the Boston Celtics win the 2026 NBA Finals?",
            "category": "NBA",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.25", "0.75"]',
        },
        "polymarket",
    )

    assert {quote.market_type for quote in h2h_quotes} == {"h2h"}
    assert {quote.market_type for quote in futures_quotes} == {"futures"}


def test_market_classification_identifies_awards_and_legacy_binary() -> None:
    assert classify_prediction_market(title="Will Nikola Jokic win the 2025-2026 NBA MVP?") == "awards"

    legacy_market = SimpleNamespace(
        event_name="Will the New York Knicks beat the Boston Celtics?",
        selection="Yes",
        league="NBA",
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        market_type="binary",
        extra={},
    )

    assert effective_prediction_market_type(legacy_market) == "h2h"


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
