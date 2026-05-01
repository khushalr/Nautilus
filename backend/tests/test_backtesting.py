from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import HistoricalPredictionMarketPriceSnapshot, HistoricalSportsbookOddsSnapshot, Market
from app.api.routes import _aggregate_rows
from app.services.backtesting import (
    detect_signal,
    estimate_historical_odds_credits,
    evaluate_paper_long_yes,
    evaluate_signal_horizons,
    historical_market_yes_probability,
    historical_match_debug,
    market_yes_price_from_raw,
    nearest_prediction_price,
    persist_signal_results,
    reconstruct_historical_edge,
)
from app.jobs.backtest_signals import _verbose_skip_row


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


def test_polymarket_historical_no_token_0996_maps_to_yes_0004() -> None:
    yes_price, orientation = market_yes_price_from_raw(0.996, "No", "futures", "Atlanta Hawks")

    assert yes_price == pytest.approx(0.004)
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
    assert evaluation.skip_reason == "missing_future_price"


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


def test_missing_liquidity_rejected_by_default() -> None:
    edge = _edge(net_edge=0.03, confidence=0.9, match_confidence=0.9, liquidity=None)

    assert detect_signal(edge) is None


def test_missing_liquidity_allowed_in_research_mode() -> None:
    edge = _edge(net_edge=0.03, confidence=0.9, match_confidence=0.9, liquidity=None)

    assert detect_signal(edge, config={"allow_missing_liquidity": True}) == "possible_yes_underpricing"


def test_timestamp_tolerance_matches_nearest_historical_odds(db_session) -> None:
    market = _market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(_price(market.id, timestamp, raw_price=0.40, liquidity=75000))
    db_session.add_all(
        [
            _odds(timestamp + timedelta(minutes=45), "Los Angeles Lakers", 100 / 220, american=120),
            _odds(timestamp + timedelta(minutes=45), "Houston Rockets", 140 / 240, american=-140),
        ]
    )
    db_session.commit()

    narrow = reconstruct_historical_edge(db_session, market, timestamp, config={**_loose_config(), "odds_tolerance_minutes": 30})
    wide = reconstruct_historical_edge(db_session, market, timestamp, config={**_loose_config(), "odds_tolerance_minutes": 60})

    assert narrow.skip_reason == "no_historical_sportsbook_odds"
    assert wide.skip_reason is None


def test_verbose_skip_example_includes_debug_fields(db_session) -> None:
    market = _market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(_price(market.id, timestamp, raw_price=0.40, liquidity=None))
    db_session.commit()
    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    row = _verbose_skip_row(market, timestamp, edge, edge.skip_reason or "unknown")

    assert row["market_title"] == market.event_name
    assert row["market_id"] == market.id
    assert row["raw_historical_polymarket_price"] == pytest.approx(0.40)
    assert row["raw_outcome_side"] == "Yes"
    assert row["derived_market_yes_probability"] == pytest.approx(0)
    assert row["liquidity_status"] == "missing"


def test_historical_futures_outright_matching_reuses_live_context_logic(db_session) -> None:
    market = _futures_market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(_price(market.id, timestamp, raw_price=0.04, liquidity=90000, display_outcome="Tampa Bay Lightning"))
    db_session.add_all(
        [
            _outright_odds(timestamp, "Tampa Bay Lightning", 0.05, american=1900),
            _outright_odds(timestamp, "Dallas Stars", 0.10, american=900),
            _outright_odds(timestamp, "Edmonton Oilers", 0.12, american=733),
        ]
    )
    db_session.commit()

    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())
    debug = historical_match_debug(market, "futures", [_outright_odds(timestamp, "Tampa Bay Lightning", 0.05, american=1900)])

    assert edge.skip_reason is None
    assert edge.matched_event_name == "NHL Championship Winner"
    assert edge.matched_selection == "Tampa Bay Lightning"
    assert debug["available_sportsbook_event"] == "NHL Championship Winner"


def test_historical_futures_do_not_match_h2h_games(db_session) -> None:
    market = _futures_market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(_price(market.id, timestamp, raw_price=0.04, liquidity=90000, display_outcome="Tampa Bay Lightning"))
    db_session.add_all(
        [
            _odds(timestamp, "Tampa Bay Lightning", 0.55, american=-120, event_name="Tampa Bay Lightning at Anaheim Ducks"),
            _odds(timestamp, "Anaheim Ducks", 0.50, american=100, event_name="Tampa Bay Lightning at Anaheim Ducks"),
        ]
    )
    db_session.commit()

    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    assert edge.skip_reason == "no_historical_sportsbook_odds"


def test_no_side_historical_price_is_complemented_for_edge_reconstruction(db_session) -> None:
    market = _market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(
        _price(
            market.id,
            timestamp,
            raw_price=0.63,
            market_yes_price=0.37,
            raw_selection="No",
            liquidity=75000,
        )
    )
    db_session.add_all(
        [
            _odds(timestamp, "Los Angeles Lakers", 100 / 220, american=120),
            _odds(timestamp, "Houston Rockets", 140 / 240, american=-140),
        ]
    )
    db_session.commit()

    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    assert edge.skip_reason is None
    assert edge.market_yes_probability == pytest.approx(0.37)
    assert edge.raw_prediction_side == "No"


def test_no_side_historical_price_0996_is_derived_even_if_stored_value_is_wrong(db_session) -> None:
    market = _market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    price = _price(
        market.id,
        timestamp,
        raw_price=0.996,
        market_yes_price=0.996,
        raw_selection="No",
        liquidity=75000,
    )
    db_session.add(price)
    db_session.add_all(
        [
            _odds(timestamp, "Los Angeles Lakers", 100 / 220, american=120),
            _odds(timestamp, "Houston Rockets", 140 / 240, american=-140),
        ]
    )
    db_session.commit()

    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    assert historical_market_yes_probability(price, "h2h_game") == pytest.approx(0.004)
    assert edge.skip_reason is None
    assert edge.market_yes_probability == pytest.approx(0.004)


def test_future_polymarket_price_found_creates_evaluated_result(db_session) -> None:
    market, timestamp = _entry_setup(db_session, entry_price=0.40)
    db_session.add(_price(market.id, timestamp + timedelta(hours=1), raw_price=0.46, liquidity=75000))
    db_session.commit()
    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    signal = persist_signal_results(db_session, edge, "possible_yes_underpricing", config=_loose_config())
    db_session.commit()

    one_hour = next(result for result in signal.results if result.horizon == "1h")
    assert one_hour.paper_pnl_per_contract == pytest.approx(0.06)
    assert one_hour.return_on_stake == pytest.approx(0.15)
    assert one_hour.raw_payload["evaluation_status"] == "missing_future_fair"


def test_future_polymarket_price_missing_marks_missing_future_price(db_session) -> None:
    market, timestamp = _entry_setup(db_session, entry_price=0.40)
    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    evaluations = evaluate_signal_horizons(db_session, edge, "possible_yes_underpricing", config=_loose_config())

    one_hour = next(result for result in evaluations if result.horizon == "1h")
    assert one_hour.paper_pnl_per_contract is None
    assert one_hour.skip_reason == "missing_future_price"
    assert one_hour.evaluation_status == "missing_future_price"


def test_future_fair_missing_still_evaluates_when_enabled(db_session) -> None:
    market, timestamp = _entry_setup(db_session, entry_price=0.40)
    db_session.add(_price(market.id, timestamp + timedelta(hours=1), raw_price=0.44, liquidity=75000))
    db_session.commit()
    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    evaluations = evaluate_signal_horizons(
        db_session,
        edge,
        "possible_yes_underpricing",
        config={**_loose_config(), "allow_missing_future_fair": True},
    )

    one_hour = next(result for result in evaluations if result.horizon == "1h")
    assert one_hour.paper_pnl_per_contract == pytest.approx(0.04)
    assert one_hour.exit_sportsbook_fair_probability is None
    assert one_hour.evaluation_status == "missing_future_fair"


def test_invalid_probability_above_one_is_skipped(db_session) -> None:
    market = _market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(_price(market.id, timestamp, raw_price=1.016, market_yes_price=1.016, liquidity=75000))
    db_session.add_all(
        [
            _odds(timestamp, "Los Angeles Lakers", 100 / 220, american=120),
            _odds(timestamp, "Houston Rockets", 140 / 240, american=-140),
        ]
    )
    db_session.commit()

    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    assert edge.skip_reason == "invalid_probability_range"
    assert detect_signal(edge, config=_loose_config()) is None


def test_suspicious_negative_99_edge_is_flagged_and_excluded(db_session) -> None:
    market = _futures_market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(
        _price(
            market.id,
            timestamp,
            raw_price=0.996,
            market_yes_price=0.996,
            raw_selection="Yes",
            liquidity=90000,
            display_outcome="Tampa Bay Lightning",
        )
    )
    db_session.add_all(
        [
            _outright_odds(timestamp, "Tampa Bay Lightning", 0.004, american=25000),
            _outright_odds(timestamp, "Dallas Stars", 0.10, american=900),
            _outright_odds(timestamp, "Edmonton Oilers", 0.12, american=733),
        ]
    )
    db_session.commit()

    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    assert edge.skip_reason == "suspicious_probability_orientation"
    assert detect_signal(edge, config=_loose_config()) is None


def test_negative_edge_does_not_simulate_long_yes_by_default(db_session) -> None:
    market, timestamp = _entry_setup(db_session, entry_price=0.80)
    edge = reconstruct_historical_edge(db_session, market, timestamp, config=_loose_config())

    evaluations = evaluate_signal_horizons(db_session, edge, "possible_yes_overpricing", config=_loose_config())

    one_hour = next(result for result in evaluations if result.horizon == "1h")
    assert one_hour.paper_pnl_per_contract is None
    assert one_hour.evaluation_status == "negative_edge_no_long_simulation"


def test_performance_aggregate_counts_total_evaluated_unevaluated_and_invalid() -> None:
    rows = [
        {"signal_id": "a", "paper_pnl_per_contract": 0.02, "did_edge_close": True, "moved_expected_direction": True, "entry_net_edge": 0.03, "return_on_stake": 0.1, "liquidity_adjusted": True, "evaluation_status": "evaluated", "skip_reason": None, "signal_category": "positive_edge_long_yes_simulated"},
        {"signal_id": "b", "paper_pnl_per_contract": None, "did_edge_close": None, "moved_expected_direction": None, "entry_net_edge": 0.03, "return_on_stake": None, "liquidity_adjusted": True, "evaluation_status": "missing_future_price", "skip_reason": "missing_future_price", "signal_category": "unevaluated_missing_future_price"},
        {"signal_id": "c", "paper_pnl_per_contract": None, "did_edge_close": None, "moved_expected_direction": None, "entry_net_edge": None, "return_on_stake": None, "liquidity_adjusted": True, "evaluation_status": "invalid_probability", "skip_reason": "invalid_probability_range", "signal_category": "suspicious_or_invalid"},
        {"signal_id": "d", "paper_pnl_per_contract": None, "did_edge_close": None, "moved_expected_direction": None, "entry_net_edge": -0.03, "return_on_stake": None, "liquidity_adjusted": True, "evaluation_status": "negative_edge_no_long_simulation", "skip_reason": "negative_edge_no_long_simulation", "signal_category": "negative_edge_overpricing_tracked_only"},
    ]

    summary = _aggregate_rows(rows)

    assert summary["total_signals"] == 3
    assert summary["evaluated_signals"] == 1
    assert summary["simulated_long_yes_signals"] == 2
    assert summary["evaluated_long_yes_signals"] == 1
    assert summary["tracked_negative_edge_signals"] == 1
    assert summary["unevaluated_signals"] == 1
    assert summary["suspicious_invalid_signals"] == 1
    assert summary["skipped_invalid_signals"] == 1
    assert summary["average_paper_pnl_per_contract"] == pytest.approx(0.02)


def test_quota_cost_estimation_and_yes_guard_inputs() -> None:
    estimate = estimate_historical_odds_credits(
        date_start=datetime(2026, 1, 1, tzinfo=UTC),
        date_end=datetime(2026, 1, 1, 3, tzinfo=UTC),
        interval_minutes=60,
        markets=["h2h"],
        regions="us,us2",
    )

    assert estimate == 8


def _entry_setup(db_session, entry_price: float) -> tuple[Market, datetime]:
    market = _market()
    timestamp = datetime(2026, 1, 1, 12, tzinfo=UTC)
    db_session.add(market)
    db_session.flush()
    db_session.add(_price(market.id, timestamp, raw_price=entry_price, liquidity=75000))
    db_session.add_all(
        [
            _odds(timestamp, "Los Angeles Lakers", 100 / 220, american=120),
            _odds(timestamp, "Houston Rockets", 140 / 240, american=-140),
        ]
    )
    db_session.commit()
    return market, timestamp


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


def _futures_market() -> Market:
    return Market(
        source="polymarket",
        external_id="pm-nhl-futures:yes",
        event_name="Will the Tampa Bay Lightning win the 2026 NHL Stanley Cup?",
        league="NHL",
        market_type="futures",
        selection="Yes",
        normalized_event_key="nhl:stanley-cup-winner:2026:tampa-bay-lightning",
        start_time=None,
        status="open",
        extra={},
    )


def _price(
    market_id: str,
    timestamp: datetime,
    raw_price: float,
    liquidity: float | None = 100000,
    *,
    market_yes_price: float | None = None,
    raw_selection: str = "Yes",
    display_outcome: str = "Los Angeles Lakers",
) -> HistoricalPredictionMarketPriceSnapshot:
    return HistoricalPredictionMarketPriceSnapshot(
        market_id=market_id,
        source="polymarket",
        token_id="token-yes",
        raw_selection=raw_selection,
        display_outcome=display_outcome,
        raw_price=raw_price,
        market_yes_price=market_yes_price if market_yes_price is not None else raw_price,
        orientation="raw_selection" if raw_selection == "Yes" else "positive_yes_complemented_from_no",
        liquidity=liquidity,
        volume=1000,
        timestamp=timestamp,
        raw_payload={
            "token_id": "token-yes",
            "raw_outcome_side": raw_selection,
            "raw_price": raw_price,
            "derived_market_yes_probability": market_yes_price if market_yes_price is not None else raw_price,
            "market_title": "test market",
        },
    )


def _odds(
    timestamp: datetime,
    selection: str,
    implied: float,
    american: int,
    *,
    event_name: str = "Los Angeles Lakers at Houston Rockets",
) -> HistoricalSportsbookOddsSnapshot:
    return HistoricalSportsbookOddsSnapshot(
        provider="odds_api",
        provider_event_id="evt-1",
        event_name=event_name,
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


def _outright_odds(timestamp: datetime, selection: str, implied: float, american: int) -> HistoricalSportsbookOddsSnapshot:
    return HistoricalSportsbookOddsSnapshot(
        provider="odds_api",
        provider_event_id="nhl-outright-1",
        event_name="NHL Championship Winner",
        league="NHL",
        home_team=None,
        away_team=None,
        normalized_event_key="nhl:championship-winner:2026",
        start_time=None,
        bookmaker="draftkings",
        market_type="outrights",
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
        "exit_price_tolerance_minutes": 120,
        "min_abs_edge": 0.01,
        "min_confidence_score": 0.1,
        "min_liquidity": 0,
        "min_match_confidence": 0.1,
        "allow_missing_liquidity": False,
    }


def _edge(net_edge: float, confidence: float, match_confidence: float, liquidity: float | None):
    return type(
        "Edge",
        (),
        {
            "skip_reason": None,
            "net_edge": net_edge,
            "confidence_score": confidence,
            "match_confidence": match_confidence,
            "liquidity": liquidity,
            "market_yes_probability": 0.4,
            "sportsbook_fair_probability": 0.43,
        },
    )()
