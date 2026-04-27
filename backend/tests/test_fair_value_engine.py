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
from app.jobs.compute_fair_values import (
    _market_outright_context,
    _outcome_match_score,
    _outright_event_score,
    _sportsbook_outright_context,
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


def test_exact_normalized_event_key_match() -> None:
    start_time = datetime(2026, 5, 1, 23, 0, tzinfo=UTC)
    event_key = normalized_event_key("NBA", ["Boston Celtics", "New York Knicks"], start_time)
    market = SimpleNamespace(
        event_name="Boston Celtics vs New York Knicks",
        selection="Boston Celtics",
        league="NBA",
        start_time=start_time,
        normalized_event_key=event_key,
    )
    event = SimpleNamespace(
        event_name="New York Knicks at Boston Celtics",
        league="NBA",
        home_team="Boston Celtics",
        away_team="New York Knicks",
        start_time=start_time,
        normalized_event_key=event_key,
    )

    match = match_prediction_market_to_sportsbook_events(market, [event])

    assert match is not None
    assert match.match_type == "exact_normalized_event_key"
    assert match.confidence_score >= 0.95


def test_fuzzy_team_title_match_without_exact_key() -> None:
    start_time = datetime(2026, 5, 1, 23, 0, tzinfo=UTC)
    market = SimpleNamespace(
        event_name="Will the Boston Celtics beat the New York Knicks?",
        selection="Yes",
        league="Sports",
        start_time=start_time,
        normalized_event_key="sports:unknown-date:will-the-boston-celtics-beat-the-new-york-knicks",
        extra={"raw_market": {"tags": [{"label": "NBA"}]}},
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
    assert match.match_type == "fuzzy"
    assert match.confidence_score >= 0.80
    assert match.team_score == pytest.approx(1.0)


def test_no_match_for_wrong_team_and_league() -> None:
    start_time = datetime(2026, 5, 1, 23, 0, tzinfo=UTC)
    market = SimpleNamespace(
        event_name="Will the Kansas City Chiefs beat the Denver Broncos?",
        selection="Yes",
        league="NFL",
        start_time=start_time,
        normalized_event_key=normalized_event_key("NFL", ["Kansas City Chiefs", "Denver Broncos"], start_time),
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

    assert match is None


def test_stanley_cup_matches_championship_outright_context() -> None:
    market = SimpleNamespace(
        event_name="Will the Tampa Bay Lightning win the 2026 NHL Stanley Cup?",
        selection="Yes",
        league="sports",
        start_time=None,
        normalized_event_key="sports:unknown-date:stanley-cup",
        extra={},
    )
    event = SimpleNamespace(
        event_name="NHL Championship Winner",
        league="NHL",
        home_team=None,
        away_team=None,
        start_time=None,
        normalized_event_key="nhl:unknown-date:championship",
        extra={"raw_event": {"sport_key": "icehockey_nhl_championship_winner"}},
    )

    assert _market_outright_context(market, "futures") == "championship"
    assert _sportsbook_outright_context(event) == "championship"
    assert _outright_event_score(market, event, "futures") >= 0.70
    assert _outcome_match_score("Tampa Bay Lightning", "Tampa Bay Lightning") == pytest.approx(1.0)


def test_eastern_conference_does_not_match_championship_winner() -> None:
    market = SimpleNamespace(
        event_name="Will the Boston Celtics win the NBA Eastern Conference Finals?",
        selection="Yes",
        league="sports",
        start_time=None,
        normalized_event_key="sports:unknown-date:east",
        extra={},
    )
    event = SimpleNamespace(
        event_name="NBA Championship Winner",
        league="NBA",
        home_team=None,
        away_team=None,
        start_time=None,
        normalized_event_key="nba:unknown-date:championship",
        extra={"raw_event": {"sport_key": "basketball_nba_championship_winner"}},
    )

    assert _market_outright_context(market, "futures") == "eastern_conference"
    assert _sportsbook_outright_context(event) == "championship"
    assert _outright_event_score(market, event, "futures") == pytest.approx(0.0)
