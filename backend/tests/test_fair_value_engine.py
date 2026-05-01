from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.routes import _dedupe_scanner_rows
from app.schemas import OpportunityScannerOut
from app.services.fair_value import (
    EdgeInputs,
    calculate_edge,
    consensus_fair_probability,
    remove_vig_two_way,
    weighted_consensus_fair_probability,
)
from app.jobs.compute_fair_values import (
    _bookmaker_no_vig_probabilities,
    _market_outright_context,
    _outcome_match_score,
    _outright_event_score,
    _prediction_probability_inputs,
    _sportsbook_outright_context,
)
from app.models import Market, SportsbookEvent, SportsbookOddsSnapshot
from app.services.normalization import extract_h2h_market_info, match_prediction_market_to_sportsbook_events, normalized_event_key


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


def test_yes_futures_market_keeps_positive_probability() -> None:
    market = SimpleNamespace(
        event_name="Will the Philadelphia Flyers win the 2026 NHL Stanley Cup?",
        selection="Yes",
    )
    snapshot = SimpleNamespace(bid_probability=0.035, ask_probability=0.045, last_price=0.04)

    inputs = _prediction_probability_inputs(snapshot, market, "futures")

    assert inputs.display_outcome == "Philadelphia Flyers"
    assert inputs.orientation == "raw_selection"
    assert inputs.bid_probability == pytest.approx(0.035)
    assert inputs.ask_probability == pytest.approx(0.045)
    assert inputs.last_price == pytest.approx(0.04)


def test_no_futures_market_complements_to_positive_yes_probability() -> None:
    market = SimpleNamespace(
        event_name="Will the Philadelphia Flyers win the 2026 NHL Stanley Cup?",
        selection="No",
    )
    snapshot = SimpleNamespace(bid_probability=0.955, ask_probability=0.965, last_price=0.964)

    inputs = _prediction_probability_inputs(snapshot, market, "futures")

    assert inputs.display_outcome == "Philadelphia Flyers"
    assert inputs.orientation == "positive_yes_complemented_from_no"
    assert inputs.bid_probability == pytest.approx(0.035)
    assert inputs.ask_probability == pytest.approx(0.045)
    assert inputs.last_price == pytest.approx(0.036)
    assert inputs.raw_last_price == pytest.approx(0.964)


def test_no_h2h_market_complements_to_target_team_yes_probability() -> None:
    market = SimpleNamespace(
        event_name="Will the Los Angeles Lakers beat the Houston Rockets?",
        selection="No",
    )
    snapshot = SimpleNamespace(bid_probability=None, ask_probability=None, last_price=0.58)

    inputs = _prediction_probability_inputs(snapshot, market, "h2h_game")

    assert inputs.display_outcome == "Los Angeles Lakers"
    assert inputs.orientation == "positive_yes_complemented_from_no"
    assert inputs.last_price == pytest.approx(0.42)


def test_futures_edge_uses_positive_market_probability_after_normalization() -> None:
    market = SimpleNamespace(
        event_name="Will the Philadelphia Flyers win the 2026 NHL Stanley Cup?",
        selection="No",
    )
    snapshot = SimpleNamespace(bid_probability=None, ask_probability=None, last_price=0.964)
    inputs = _prediction_probability_inputs(snapshot, market, "futures")

    result = calculate_edge(
        EdgeInputs(
            fair_probability=0.05,
            bid_probability=inputs.bid_probability,
            ask_probability=inputs.ask_probability,
            last_price=inputs.last_price,
            liquidity=1000,
            sportsbook_count=4,
            consensus_dispersion=0.01,
        )
    )

    assert result.market_probability == pytest.approx(0.036)
    assert result.gross_edge == pytest.approx(0.014)


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


def test_h2h_prediction_market_title_parsing() -> None:
    info = extract_h2h_market_info("Will the Los Angeles Lakers beat the Houston Rockets?", "Yes")

    assert info.target_team == "lal"
    assert info.opponent_team == "hou"
    assert set(info.participants) == {"lal", "hou"}


def test_h2h_sportsbook_event_matching() -> None:
    start_time = datetime(2026, 5, 1, 23, 0, tzinfo=UTC)
    market = SimpleNamespace(
        event_name="Will the Los Angeles Lakers beat the Houston Rockets?",
        selection="Yes",
        league="NBA",
        start_time=start_time,
        normalized_event_key="sports:unknown-date:lakers-rockets",
        extra={},
    )
    event = SimpleNamespace(
        event_name="Los Angeles Lakers at Houston Rockets",
        league="NBA",
        home_team="Houston Rockets",
        away_team="Los Angeles Lakers",
        start_time=start_time,
        normalized_event_key=normalized_event_key("NBA", ["Los Angeles Lakers", "Houston Rockets"], start_time),
    )

    match = match_prediction_market_to_sportsbook_events(market, [event], threshold=0.72)

    assert match is not None
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


def test_h2h_no_vig_normalizes_all_moneyline_outcomes(db_session) -> None:
    event = SportsbookEvent(
        provider="odds_api",
        provider_event_id="evt-h2h",
        event_name="Los Angeles Lakers at Houston Rockets",
        league="NBA",
        home_team="Houston Rockets",
        away_team="Los Angeles Lakers",
        normalized_event_key="nba:2026-05-01:hou-vs-lal",
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        extra={},
    )
    market = Market(
        source="polymarket",
        external_id="pm-h2h:yes",
        event_name="Will the Los Angeles Lakers beat the Houston Rockets?",
        league="NBA",
        market_type="h2h_game",
        selection="Yes",
        normalized_event_key="nba:2026-05-01:hou-vs-lal",
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        status="open",
        extra={},
    )
    db_session.add_all([event, market])
    db_session.flush()
    db_session.add_all(
        [
            SportsbookOddsSnapshot(
                event_id=event.id,
                bookmaker="draftkings",
                market_type="h2h",
                selection="Los Angeles Lakers",
                american_odds=120,
                decimal_odds=2.2,
                implied_probability=100 / 220,
                raw_payload={},
            ),
            SportsbookOddsSnapshot(
                event_id=event.id,
                bookmaker="draftkings",
                market_type="h2h",
                selection="Houston Rockets",
                american_odds=-140,
                decimal_odds=1.714,
                implied_probability=140 / 240,
                raw_payload={},
            ),
        ]
    )
    db_session.flush()

    probabilities = _bookmaker_no_vig_probabilities(db_session, market, event, {"excluded_bookmakers": [], "bookmaker_weights": {}})

    assert len(probabilities) == 1
    total = (100 / 220) + (140 / 240)
    assert probabilities[0]["no_vig_probability"] == pytest.approx((100 / 220) / total)
    assert probabilities[0]["all_no_vig_probabilities"]["Los Angeles Lakers"] == pytest.approx((100 / 220) / total)


def test_futures_are_not_matched_to_h2h_games() -> None:
    market = SimpleNamespace(
        event_name="Will the Tampa Bay Lightning win the 2026 NHL Stanley Cup?",
        selection="Yes",
        league="NHL",
        start_time=None,
        normalized_event_key="nhl:unknown-date:tbl-stanley-cup",
        market_type="futures",
        extra={},
    )
    event = SimpleNamespace(
        event_name="Tampa Bay Lightning at Boston Bruins",
        league="NHL",
        home_team="Boston Bruins",
        away_team="Tampa Bay Lightning",
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        normalized_event_key="nhl:2026-05-01:bos-bruins-vs-tbl",
        extra={},
    )

    assert _outright_event_score(market, event, "futures") == pytest.approx(0.0)


def test_h2h_games_are_not_matched_to_outrights() -> None:
    market = SimpleNamespace(
        event_name="Will the Los Angeles Lakers beat the Houston Rockets?",
        selection="Yes",
        league="NBA",
        start_time=datetime(2026, 5, 1, tzinfo=UTC),
        normalized_event_key="nba:2026-05-01:hou-vs-lal",
        market_type="h2h_game",
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

    assert _outright_event_score(market, event, "h2h_game") == pytest.approx(0.0)


def test_duplicate_yes_no_opportunities_are_deduped_in_scanner() -> None:
    now = datetime(2026, 5, 1, tzinfo=UTC)
    rows = [
        OpportunityScannerOut(
            market_id="yes",
            title="Will the Philadelphia Flyers win the 2026 NHL Stanley Cup?",
            source="polymarket",
            external_id="pm:yes",
            league="NHL",
            market_type="futures",
            outcome="Philadelphia Flyers",
            display_outcome="Philadelphia Flyers",
            start_time=None,
            status="open",
            market_url=None,
            market_probability=0.04,
            fair_probability=0.05,
            gross_edge=0.01,
            net_edge=0.01,
            spread=None,
            liquidity=1000,
            confidence_score=0.8,
            matched_sportsbook_category="NHL Championship Winner",
            matched_selection="Philadelphia Flyers",
            match_confidence=0.9,
            sportsbooks_used=["draftkings"],
            last_updated=now,
        ),
        OpportunityScannerOut(
            market_id="no",
            title="Will the Philadelphia Flyers win the 2026 NHL Stanley Cup?",
            source="polymarket",
            external_id="pm:no",
            league="NHL",
            market_type="futures",
            outcome="Philadelphia Flyers",
            display_outcome="Philadelphia Flyers",
            start_time=None,
            status="open",
            market_url=None,
            market_probability=0.04,
            fair_probability=0.05,
            gross_edge=0.01,
            net_edge=0.009,
            spread=None,
            liquidity=1000,
            confidence_score=0.8,
            matched_sportsbook_category="NHL Championship Winner",
            matched_selection="Philadelphia Flyers",
            match_confidence=0.9,
            sportsbooks_used=["draftkings"],
            last_updated=now,
        ),
    ]

    deduped = _dedupe_scanner_rows(rows)

    assert len(deduped) == 1
    assert deduped[0].market_id == "yes"


@pytest.mark.parametrize(
    ("text", "league"),
    [
        ("Will the Boston Celtics win the NBA Finals?", "nba"),
        ("Will the Tampa Bay Lightning win the NHL Stanley Cup?", "nhl"),
        ("Will the Kansas City Chiefs win the Super Bowl?", "nfl"),
        ("Will the Los Angeles Dodgers win the World Series?", "mlb"),
    ],
)
def test_league_inference_for_major_us_sports(text: str, league: str) -> None:
    from app.services.normalization import infer_league_from_text

    assert infer_league_from_text(text) == league


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
