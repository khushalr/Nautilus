from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import HistoricalPredictionMarketPriceSnapshot, HistoricalSportsbookOddsSnapshot, Market
from app.services.backtesting import (
    detect_signal,
    estimate_historical_odds_credits,
    evaluate_paper_long_yes,
    market_yes_price_from_raw,
    nearest_prediction_price,
    reconstruct_historical_edge,
)


def test_historical_timestamp_matching(db_session) -> None:
    market = _market()
    db_session.add(market)
    db_session.flush()
    target = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(
        _price(market.id, target + timedelta(minutes=12), raw_price=0.42)
    )
    db_session.commit()

    matched = nearest_prediction_price(db_session, market.id, target, tolerance=timedelta(minutes=15))

    assert matched is not None
    assert matched.market_yes_price == pytest.approx(0.42)


def test_historical_odds_no_vig_reconstruction(db_session) -> None:
    market = _market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(_price(market.id, timestamp, raw_price=0.40, liquidity=75000))
    db_session.add_all(
        [
            _odds(timestamp, "Los Angeles Lakers", 100 / 220, american=120),
            _odds(timestamp, "Houston Rockets", 140 / 240, american=-140),
        ]
    )
    db_session.commit()

    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    total = (100 / 220) + (140 / 240)
    assert edge.skip_reason is None
    assert edge.sportsbook_fair_probability == pytest.approx((100 / 220) / total)
    assert edge.market_yes_probability == pytest.approx(0.40)


def test_polymarket_historical_yes_orientation() -> None:
    yes_price, orientation = market_yes_price_from_raw(0.37, "Yes", "futures", "Boston Celtics")

    assert yes_price == pytest.approx(0.37)
    assert orientation == "raw_selection"


def test_polymarket_historical_no_orientation_complements_to_yes() -> None:
    yes_price, orientation = market_yes_price_from_raw(0.63, "No", "futures", "Boston Celtics")

    assert yes_price == pytest.approx(0.37)
    assert orientation == "positive_yes_complemented_from_no"


def test_positive_edge_signal_detection() -> None:
    edge = _edge(net_edge=0.03, confidence=0.9, match_confidence=0.9, liquidity=80000)

    assert detect_signal(edge) == "possible_yes_underpricing"


def test_negative_edge_signal_detection_without_default_short_simulation() -> None:
    edge = _edge(net_edge=-0.03, confidence=0.9, match_confidence=0.9, liquidity=80000)
    evaluation = evaluate_paper_long_yes(
        entry_price=0.5,
        exit_price=None,
        entry_edge=edge.net_edge,
        exit_edge=None,
        horizon="1h",
        exit_timestamp=None,
    )

    assert detect_signal(edge) == "possible_yes_overpricing"
    assert evaluation.skip_reason == "no_historical_polymarket_price"


def test_paper_long_yes_pnl_and_return_on_stake() -> None:
    evaluation = evaluate_paper_long_yes(
        entry_price=0.40,
        exit_price=0.46,
        entry_edge=0.05,
        exit_edge=0.01,
        horizon="1h",
        exit_timestamp=datetime(2026, 1, 1, 13, tzinfo=UTC),
    )

    assert evaluation.paper_pnl_per_contract == pytest.approx(0.06)
    assert evaluation.return_on_stake == pytest.approx(0.15)


def test_edge_close_and_directional_accuracy_calculation() -> None:
    evaluation = evaluate_paper_long_yes(
        entry_price=0.40,
        exit_price=0.46,
        entry_edge=0.05,
        exit_edge=0.004,
        horizon="1h",
        exit_timestamp=datetime(2026, 1, 1, 13, tzinfo=UTC),
    )

    assert evaluation.did_edge_close is True
    assert evaluation.moved_expected_direction is True


def test_missing_historical_polymarket_price_skip(db_session) -> None:
    market = _market()
    db_session.add(market)
    db_session.commit()

    edge = reconstruct_historical_edge(db_session, market, datetime(2026, 1, 1, 12, tzinfo=UTC), config=_loose_config())

    assert edge.skip_reason == "no_historical_polymarket_price"


def test_missing_historical_sportsbook_odds_skip(db_session) -> None:
    market = _market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(_price(market.id, timestamp, raw_price=0.4, liquidity=75000))
    db_session.commit()

    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    assert edge.skip_reason == "no_historical_sportsbook_odds"


def test_quota_cost_estimation_and_yes_guard_inputs() -> None:
    estimate = estimate_historical_odds_credits(
        date_start=datetime(2026, 1, 1, tzinfo=UTC),
        date_end=datetime(2026, 1, 1, 3, tzinfo=UTC),
        interval_minutes=60,
        markets=["h2h"],
        regions="us,us2",
    )

    assert estimate == 8


def _market() -> Market:
    return Market(
        source="polymarket",
        external_id="pm-h2h:yes",
        event_name="Will the Los Angeles Lakers beat the Houston Rockets?",
        league="NBA",
        market_type="h2h_game",
        selection="Yes",
        normalized_event_key="nba:2026-01-01:hou-vs-lal",
        start_time=datetime(2026, 1, 1, 13, tzinfo=UTC),
        status="open",
        extra={},
    )


def _price(market_id: str, timestamp: datetime, raw_price: float, liquidity: float = 100000) -> HistoricalPredictionMarketPriceSnapshot:
    return HistoricalPredictionMarketPriceSnapshot(
        market_id=market_id,
        source="polymarket",
        token_id="token-yes",
        raw_selection="Yes",
        display_outcome="Los Angeles Lakers",
        raw_price=raw_price,
        market_yes_price=raw_price,
        orientation="raw_selection",
        liquidity=liquidity,
        volume=1000,
        timestamp=timestamp,
        raw_payload={},
    )


def _odds(timestamp: datetime, selection: str, implied: float, american: int) -> HistoricalSportsbookOddsSnapshot:
    return HistoricalSportsbookOddsSnapshot(
        provider="odds_api",
        provider_event_id="evt-1",
        event_name="Los Angeles Lakers at Houston Rockets",
        league="NBA",
        home_team="Houston Rockets",
        away_team="Los Angeles Lakers",
        normalized_event_key="nba:2026-01-01:hou-vs-lal",
        start_time=datetime(2026, 1, 1, 13, tzinfo=UTC),
        bookmaker="draftkings",
        market_type="h2h",
        selection=selection,
        american_odds=american,
        decimal_odds=None,
        implied_probability=implied,
        snapshot_timestamp=timestamp,
        raw_payload={},
    )


def _loose_config() -> dict[str, float | bool]:
    return {
        "price_tolerance_minutes": 30,
        "odds_tolerance_minutes": 30,
        "min_abs_edge": 0.01,
        "min_confidence_score": 0.1,
        "min_liquidity": 0,
        "min_match_confidence": 0.1,
    }


def _edge(net_edge: float, confidence: float, match_confidence: float, liquidity: float):
    return type(
        "Edge",
        (),
        {
            "skip_reason": None,
            "net_edge": net_edge,
            "confidence_score": confidence,
            "match_confidence": match_confidence,
            "liquidity": liquidity,
        },
    )()
