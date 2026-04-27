from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.fair_value import (
    EdgeInputs,
    calculate_edge,
    consensus_fair_probability,
    remove_vig_two_way,
    weighted_consensus_fair_probability,
)
from app.services.normalization import match_prediction_market_to_sportsbook_events, normalized_event_key


def test_no_vig_calculation() -> None:
    side_a, side_b = remove_vig_two_way(0.55, 0.55)

    assert side_a == pytest.approx(0.5)
    assert side_b == pytest.approx(0.5)


def test_weighted_consensus() -> None:
    assert consensus_fair_probability([0.48, 0.52]) == pytest.approx(0.5)
    assert weighted_consensus_fair_probability([0.50, 0.60], [1.0, 3.0]) == pytest.approx(0.575)


def test_edge_calculation_uses_midpoint_and_penalties() -> None:
    result = calculate_edge(
        EdgeInputs(
            fair_probability=0.56,
            bid_probability=0.50,
            ask_probability=0.54,
            last_price=0.53,
            liquidity=1000,
            sportsbook_count=4,
            consensus_dispersion=0.01,
            min_liquidity=500,
            spread_penalty_multiplier=0.5,
            liquidity_penalty_multiplier=0.02,
        )
    )

    assert result.market_probability == pytest.approx(0.52)
    assert result.market_probability_source == "midpoint"
    assert result.spread == pytest.approx(0.04)
    assert result.gross_edge == pytest.approx(0.04)
    assert result.spread_penalty == pytest.approx(0.02)
    assert result.liquidity_penalty == pytest.approx(0.0)
    assert result.net_edge == pytest.approx(0.02)


def test_missing_liquidity_applies_max_penalty() -> None:
    result = calculate_edge(
        EdgeInputs(
            fair_probability=0.60,
            bid_probability=0.50,
            ask_probability=0.52,
            last_price=None,
            liquidity=None,
            sportsbook_count=2,
            consensus_dispersion=0.0,
        )
    )

    assert result.liquidity_penalty == pytest.approx(0.10)
    assert result.net_edge == pytest.approx(0.60 - 0.51 - 0.01 - 0.10)


def test_missing_bid_ask_uses_last_price() -> None:
    result = calculate_edge(
        EdgeInputs(
            fair_probability=0.57,
            bid_probability=None,
            ask_probability=None,
            last_price=0.52,
            liquidity=900,
            sportsbook_count=3,
            consensus_dispersion=0.02,
        )
    )

    assert result.market_probability == pytest.approx(0.52)
    assert result.market_probability_source == "last_price"
    assert result.spread is None
    assert result.gross_edge == pytest.approx(0.05)


def test_prediction_market_matches_sportsbook_event_with_confidence() -> None:
    start_time = datetime(2026, 5, 1, tzinfo=UTC)
    market = SimpleNamespace(
        event_name="Will the Boston Celtics win?",
        selection="Yes",
        league="NBA",
        start_time=start_time,
        normalized_event_key=normalized_event_key("NBA", ["Boston Celtics"], start_time),
    )
    event = SimpleNamespace(
        event_name="New York Knicks at Boston Celtics",
        league="NBA",
        home_team="Boston Celtics",
        away_team="New York Knicks",
        start_time=start_time,
        normalized_event_key=normalized_event_key("NBA", ["Boston Celtics", "New York Knicks"], start_time),
    )

    match = match_prediction_market_to_sportsbook_events(market, [event])

    assert match is not None
    assert match.confidence_score >= 0.58
    assert match.team_score >= 0.7
