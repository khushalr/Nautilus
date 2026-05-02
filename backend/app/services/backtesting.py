from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.compute_fair_values import (
    _market_outright_context,
    _outcome_match_score,
    _outright_event_score,
    _prediction_probability_inputs,
    _selected_line_for_market,
)
from app.models import (
    HistoricalPredictionMarketPriceSnapshot,
    HistoricalSportsbookOddsSnapshot,
    Market,
    PaperTradeSignal,
    PredictionMarketSnapshot,
    SignalBacktestResult,
)
from app.services.fair_value import EdgeInputs, calculate_edge, consensus_dispersion, weighted_consensus_fair_probability
from app.services.market_classification import effective_prediction_market_type
from app.services.normalization import EventMatch, normalize_team_name, score_prediction_market_event_match


HORIZONS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}

DEFAULT_BACKTEST_CONFIG: dict[str, float | bool] = {
    "min_abs_edge": 0.015,
    "min_confidence_score": 0.85,
    "min_liquidity": 50000.0,
    "min_match_confidence": 0.85,
    "price_tolerance_minutes": 30.0,
    "odds_tolerance_minutes": 60.0,
    "exit_price_tolerance_minutes": 120.0,
    "edge_close_threshold": 0.005,
    "simulate_negative_edge": False,
    "allow_missing_liquidity": False,
    "allow_missing_future_fair": True,
}

DEFAULT_MEANINGFUL_MOVEMENT = 0.001


@dataclass(frozen=True)
class HistoricalEdge:
    market: Market
    timestamp: datetime
    market_yes_probability: float
    sportsbook_fair_probability: float
    net_edge: float
    gross_edge: float
    confidence_score: float
    match_confidence: float
    liquidity: float | None
    display_outcome: str | None
    bookmaker_probabilities: list[dict[str, Any]]
    matched_event_name: str | None
    matched_selection: str | None
    skip_reason: str | None = None
    raw_prediction_side: str | None = None
    historical_price: float | None = None
    price_token_id: str | None = None
    price_raw_payload: dict[str, Any] = field(default_factory=dict)
    available_sportsbook_event: str | None = None
    available_sportsbook_selection: str | None = None
    match_score_components: dict[str, float | str | None] = field(default_factory=dict)
    liquidity_status: str = "known"
    liquidity_adjusted: bool = True
    exact_skip_detail: str | None = None


@dataclass(frozen=True)
class PaperTradeEvaluation:
    horizon: str
    exit_timestamp: datetime | None
    exit_market_yes_probability: float | None
    exit_sportsbook_fair_probability: float | None
    exit_net_edge: float | None
    paper_pnl_per_contract: float | None
    return_on_stake: float | None
    edge_change: float | None
    signal_direction: str | None = None
    paper_side: str | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    absolute_edge_change: float | None = None
    market_yes_change: float | None = None
    sportsbook_fair_change: float | None = None
    closure_reason: str | None = None
    did_edge_close: bool | None = None
    moved_expected_direction: bool | None = None
    skip_reason: str | None = None
    evaluation_status: str = "evaluated"


def estimate_historical_odds_credits(
    *,
    date_start: datetime,
    date_end: datetime,
    interval_minutes: int,
    markets: list[str],
    regions: str,
) -> int:
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive")
    span_minutes = max(0, (date_end - date_start).total_seconds() / 60)
    timestamps = ceil(span_minutes / interval_minutes) + 1
    region_count = len([region for region in regions.split(",") if region.strip()]) or 1
    market_count = len(markets) or 1
    return timestamps * region_count * market_count


def iter_time_range(date_start: datetime, date_end: datetime, interval_minutes: int) -> list[datetime]:
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive")
    current = _ensure_utc(date_start)
    end = _ensure_utc(date_end)
    values: list[datetime] = []
    while current <= end:
        values.append(current)
        current += timedelta(minutes=interval_minutes)
    return values


def market_yes_price_from_raw(raw_price: float, raw_selection: str, market_type: str, display_outcome: str | None) -> tuple[float, str]:
    should_complement = market_type in {"futures", "awards", "outrights", "h2h", "h2h_game"} and raw_selection.lower() == "no"
    if should_complement and display_outcome:
        return 1 - raw_price, "positive_yes_complemented_from_no"
    return raw_price, "raw_selection"


def detect_signal(edge: HistoricalEdge, config: dict[str, float | bool] | None = None) -> str | None:
    config = {**DEFAULT_BACKTEST_CONFIG, **(config or {})}
    if edge.skip_reason:
        return None
    if not _valid_probability(edge.market_yes_probability) or not _valid_probability(edge.sportsbook_fair_probability):
        return None
    if hasattr(edge, "market") and _is_suspicious_edge(edge):
        return None
    if abs(edge.net_edge) < float(config["min_abs_edge"]):
        return None
    if edge.confidence_score < float(config["min_confidence_score"]):
        return None
    if edge.match_confidence < float(config["min_match_confidence"]):
        return None
    if _is_missing_liquidity(edge.liquidity):
        if not bool(config.get("allow_missing_liquidity", False)):
            return None
    elif edge.liquidity is not None and edge.liquidity < float(config["min_liquidity"]):
        return None
    return "possible_yes_underpricing" if edge.net_edge > 0 else "possible_yes_overpricing"


def evaluate_paper_long_yes(
    *,
    entry_price: float,
    exit_price: float | None,
    entry_edge: float,
    exit_edge: float | None,
    horizon: str,
    exit_timestamp: datetime | None,
    edge_close_threshold: float = 0.005,
    entry_sportsbook_fair: float | None = None,
    movement_threshold: float = DEFAULT_MEANINGFUL_MOVEMENT,
    signal_direction: str = "positive_edge_long_yes",
    paper_side: str = "YES",
) -> PaperTradeEvaluation:
    normalized_side = paper_side.upper()
    if not _valid_probability(entry_price) or (exit_price is not None and not _valid_probability(exit_price)):
        return PaperTradeEvaluation(
            horizon=horizon,
            exit_timestamp=exit_timestamp,
            exit_market_yes_probability=exit_price,
            exit_sportsbook_fair_probability=None,
            exit_net_edge=exit_edge,
            paper_pnl_per_contract=None,
            return_on_stake=None,
            edge_change=None,
            signal_direction=signal_direction,
            paper_side=normalized_side,
            entry_price=_paper_price(entry_price, normalized_side) if _valid_probability(entry_price) else None,
            exit_price=_paper_price(exit_price, normalized_side) if exit_price is not None and _valid_probability(exit_price) else None,
            absolute_edge_change=None,
            market_yes_change=None,
            sportsbook_fair_change=None,
            closure_reason=None,
            did_edge_close=None,
            moved_expected_direction=None,
            skip_reason="invalid_probability_range",
            evaluation_status="invalid_probability",
        )
    if exit_price is None:
        return PaperTradeEvaluation(
            horizon=horizon,
            exit_timestamp=exit_timestamp,
            exit_market_yes_probability=None,
            exit_sportsbook_fair_probability=None,
            exit_net_edge=exit_edge,
            paper_pnl_per_contract=None,
            return_on_stake=None,
            edge_change=None,
            signal_direction=signal_direction,
            paper_side=normalized_side,
            entry_price=_paper_price(entry_price, normalized_side),
            exit_price=None,
            absolute_edge_change=None,
            market_yes_change=None,
            sportsbook_fair_change=None,
            closure_reason=None,
            did_edge_close=None,
            moved_expected_direction=None,
            skip_reason="missing_future_price",
            evaluation_status="missing_future_price",
        )
    paper_entry_price = _paper_price(entry_price, normalized_side)
    paper_exit_price = _paper_price(exit_price, normalized_side)
    pnl = paper_exit_price - paper_entry_price
    return_on_stake = pnl / paper_entry_price if paper_entry_price > 0 else None
    edge_change = exit_edge - entry_edge if exit_edge is not None else None
    absolute_edge_change = abs(exit_edge) - abs(entry_edge) if exit_edge is not None else None
    exit_fair = (exit_price + exit_edge) if exit_edge is not None else None
    sportsbook_fair_change = (
        exit_fair - entry_sportsbook_fair
        if exit_fair is not None and entry_sportsbook_fair is not None
        else None
    )
    closure_reason = classify_closure_reason(
        entry_market_yes=entry_price,
        entry_sportsbook_fair=entry_sportsbook_fair,
        exit_market_yes=exit_price,
        exit_sportsbook_fair=exit_fair,
        threshold=movement_threshold,
        signal_direction=signal_direction,
    )
    status = "evaluated" if exit_edge is not None else "missing_future_fair"
    return PaperTradeEvaluation(
        horizon=horizon,
        exit_timestamp=exit_timestamp,
        exit_market_yes_probability=exit_price,
        exit_sportsbook_fair_probability=exit_fair,
        exit_net_edge=exit_edge,
        paper_pnl_per_contract=pnl,
        return_on_stake=return_on_stake,
        edge_change=edge_change,
        signal_direction=signal_direction,
        paper_side=normalized_side,
        entry_price=paper_entry_price,
        exit_price=paper_exit_price,
        absolute_edge_change=absolute_edge_change,
        market_yes_change=exit_price - entry_price,
        sportsbook_fair_change=sportsbook_fair_change,
        closure_reason=closure_reason,
        did_edge_close=abs(exit_edge) <= edge_close_threshold if exit_edge is not None else None,
        moved_expected_direction=exit_price < entry_price if normalized_side == "NO" else exit_price > entry_price,
        evaluation_status=status,
    )


def classify_closure_reason(
    *,
    entry_market_yes: float,
    entry_sportsbook_fair: float | None,
    exit_market_yes: float,
    exit_sportsbook_fair: float | None,
    threshold: float = DEFAULT_MEANINGFUL_MOVEMENT,
    signal_direction: str = "positive_edge_long_yes",
) -> str | None:
    if entry_sportsbook_fair is None or exit_sportsbook_fair is None:
        return None
    entry_edge = entry_sportsbook_fair - entry_market_yes
    exit_edge = exit_sportsbook_fair - exit_market_yes
    market_yes_change = exit_market_yes - entry_market_yes
    sportsbook_fair_change = exit_sportsbook_fair - entry_sportsbook_fair
    if abs(exit_edge) > abs(entry_edge) + threshold:
        return "edge_widened"
    if signal_direction == "negative_edge_no_side":
        market_moved = market_yes_change <= -threshold
        fair_moved = sportsbook_fair_change >= threshold
    else:
        market_moved = market_yes_change >= threshold
        fair_moved = sportsbook_fair_change <= -threshold
    if market_moved and fair_moved:
        return "both_moved_toward_each_other"
    if market_moved:
        return "market_moved_expected_direction"
    if fair_moved:
        return "fair_moved_toward_market"
    return "no_meaningful_change"


def _paper_price(market_yes_price: float, paper_side: str) -> float:
    return 1 - market_yes_price if paper_side.upper() == "NO" else market_yes_price


def reconstruct_historical_edge(
    db: Session,
    market: Market,
    timestamp: datetime,
    *,
    config: dict[str, float | bool] | None = None,
) -> HistoricalEdge:
    config = {**DEFAULT_BACKTEST_CONFIG, **(config or {})}
    market_type = effective_prediction_market_type(market)
    price = nearest_prediction_price(
        db,
        market.id,
        timestamp,
        tolerance=timedelta(minutes=float(config["price_tolerance_minutes"])),
    )
    if price is None:
        return _skipped_edge(
            market,
            timestamp,
            "no_historical_polymarket_price",
            exact_skip_detail="No historical Polymarket price was found inside the configured price tolerance.",
        )

    odds = nearest_sportsbook_odds(
        db,
        timestamp,
        market_type=market_type,
        tolerance=timedelta(minutes=float(config["odds_tolerance_minutes"])),
    )
    if not odds:
        return _skipped_edge(
            market,
            timestamp,
            "no_historical_sportsbook_odds",
            price=price,
            allow_missing_liquidity=bool(config.get("allow_missing_liquidity", False)),
            exact_skip_detail="No compatible historical sportsbook odds were found inside the configured odds tolerance.",
        )

    probability_result = historical_bookmaker_probabilities(market, market_type, odds)
    match_debug = historical_match_debug(market, market_type, odds)
    if probability_result is None:
        return _skipped_edge(
            market,
            timestamp,
            "no_confident_match",
            price=price,
            odds=odds,
            match_debug=match_debug,
            allow_missing_liquidity=bool(config.get("allow_missing_liquidity", False)),
            exact_skip_detail="No sportsbook category/selection match reached the conservative confidence threshold.",
        )

    bookmaker_probabilities, event_match = probability_result
    probabilities = [book["no_vig_probability"] for book in bookmaker_probabilities]
    weights = [book["weight"] for book in bookmaker_probabilities]
    fair_probability = weighted_consensus_fair_probability(probabilities, weights)
    if not _valid_probability(fair_probability):
        return _skipped_edge(
            market,
            timestamp,
            "invalid_probability_range",
            price=price,
            odds=odds,
            match_debug=match_debug,
            allow_missing_liquidity=bool(config.get("allow_missing_liquidity", False)),
            exact_skip_detail="Sportsbook fair probability was outside the valid decimal probability range [0, 1].",
        )
    dispersion = consensus_dispersion(probabilities)

    market_probability = historical_market_yes_probability(price, market_type)
    synthetic_snapshot = _snapshot_from_historical_price(price, market_type)
    prediction_inputs = _prediction_probability_inputs(synthetic_snapshot, market, market_type)
    if not _valid_probability(market_probability):
        return _skipped_edge(
            market,
            timestamp,
            "invalid_probability_range",
            price=price,
            odds=odds,
            match_debug=match_debug,
            allow_missing_liquidity=bool(config.get("allow_missing_liquidity", False)),
            exact_skip_detail="Historical Market YES probability was outside the valid decimal probability range [0, 1].",
        )
    provisional_net_edge = fair_probability - market_probability
    suspicious_reason = _suspicious_probability_reason(
        market=market,
        market_type=market_type,
        price=price,
        market_yes_probability=market_probability,
        sportsbook_fair_probability=fair_probability,
        net_edge=provisional_net_edge,
    )
    if suspicious_reason:
        return _skipped_edge(
            market,
            timestamp,
            "suspicious_probability_orientation",
            price=price,
            odds=odds,
            match_debug=match_debug,
            allow_missing_liquidity=bool(config.get("allow_missing_liquidity", False)),
            exact_skip_detail=suspicious_reason,
        )
    liquidity_missing = _is_missing_liquidity(price.liquidity)
    allow_missing_liquidity = bool(config.get("allow_missing_liquidity", False))
    liquidity_status = "unknown" if liquidity_missing and allow_missing_liquidity else ("missing" if liquidity_missing else "known")
    liquidity_adjusted = not (liquidity_missing and allow_missing_liquidity)
    edge_liquidity = (
        float(config["min_liquidity"])
        if liquidity_missing and allow_missing_liquidity
        else price.liquidity
    )
    edge = calculate_edge(
        EdgeInputs(
            fair_probability=fair_probability,
            bid_probability=None,
            ask_probability=None,
            last_price=market_probability,
            liquidity=edge_liquidity,
            sportsbook_count=len(bookmaker_probabilities),
            consensus_dispersion=dispersion,
        )
    )
    return HistoricalEdge(
        market=market,
        timestamp=price.timestamp,
        market_yes_probability=edge.market_probability,
        sportsbook_fair_probability=edge.fair_probability,
        net_edge=edge.fair_probability - edge.market_probability,
        gross_edge=edge.fair_probability - edge.market_probability,
        confidence_score=edge.confidence_score,
        match_confidence=event_match.confidence_score,
        liquidity=price.liquidity,
        display_outcome=prediction_inputs.display_outcome or price.display_outcome,
        bookmaker_probabilities=bookmaker_probabilities,
        matched_event_name=getattr(event_match.event, "event_name", None),
        matched_selection=bookmaker_probabilities[0].get("selection") if bookmaker_probabilities else None,
        raw_prediction_side=price.raw_selection,
        historical_price=price.raw_price,
        price_token_id=price.token_id,
        price_raw_payload=price.raw_payload if isinstance(price.raw_payload, dict) else {},
        available_sportsbook_event=getattr(event_match.event, "event_name", None),
        available_sportsbook_selection=bookmaker_probabilities[0].get("selection") if bookmaker_probabilities else None,
        match_score_components=_event_match_scores(event_match),
        liquidity_status=liquidity_status,
        liquidity_adjusted=liquidity_adjusted,
    )


def nearest_prediction_price(
    db: Session,
    market_id: str,
    timestamp: datetime,
    *,
    tolerance: timedelta,
    after: datetime | None = None,
) -> HistoricalPredictionMarketPriceSnapshot | None:
    target = _ensure_utc(timestamp)
    stmt = (
        select(HistoricalPredictionMarketPriceSnapshot)
        .where(HistoricalPredictionMarketPriceSnapshot.market_id == market_id)
        .where(HistoricalPredictionMarketPriceSnapshot.timestamp >= target - tolerance)
        .where(HistoricalPredictionMarketPriceSnapshot.timestamp <= target + tolerance)
    )
    if after is not None:
        stmt = stmt.where(HistoricalPredictionMarketPriceSnapshot.timestamp > _ensure_utc(after))
    rows = list(
        db.scalars(stmt)
    )
    return min(rows, key=lambda row: abs((_ensure_utc(row.timestamp) - target).total_seconds()), default=None)


def nearest_sportsbook_odds(
    db: Session,
    timestamp: datetime,
    *,
    market_type: str,
    tolerance: timedelta,
) -> list[HistoricalSportsbookOddsSnapshot]:
    target = _ensure_utc(timestamp)
    sportsbook_market_types = ("h2h", "moneyline") if market_type in {"h2h", "h2h_game"} else ("outrights",)
    return list(
        db.scalars(
            select(HistoricalSportsbookOddsSnapshot)
            .where(HistoricalSportsbookOddsSnapshot.market_type.in_(sportsbook_market_types))
            .where(HistoricalSportsbookOddsSnapshot.snapshot_timestamp >= target - tolerance)
            .where(HistoricalSportsbookOddsSnapshot.snapshot_timestamp <= target + tolerance)
        )
    )


def historical_bookmaker_probabilities(
    market: Market,
    market_type: str,
    odds: list[HistoricalSportsbookOddsSnapshot],
) -> tuple[list[dict[str, Any]], EventMatch] | None:
    if market_type in {"h2h", "h2h_game"}:
        return _historical_h2h_probabilities(market, odds)
    if market_type in {"futures", "awards"}:
        return _historical_outright_probabilities(market, market_type, odds)
    return None


def historical_match_debug(
    market: Market,
    market_type: str,
    odds: list[HistoricalSportsbookOddsSnapshot],
) -> dict[str, Any]:
    if not odds:
        return {}
    if market_type in {"h2h", "h2h_game"}:
        by_event = _group_historical_odds_by_event(odds)
        matches = [
            score_prediction_market_event_match(market, _event_proxy(lines[0]))
            for lines in by_event.values()
            if lines
        ]
        matches.sort(key=lambda match: match.confidence_score, reverse=True)
        if not matches:
            return {}
        best = matches[0]
        lines = by_event.get(getattr(best.event, "provider_event_id"), [])
        selected = _selected_line_for_market(market, best.event, _group_latest_by_book_selection(lines).get(lines[0].bookmaker, {}) if lines else {})
        return {
            "available_sportsbook_event": getattr(best.event, "event_name", None),
            "available_sportsbook_selection": selected.selection if selected else None,
            "match_confidence": best.confidence_score,
            "match_score_components": _event_match_scores(best),
        }

    if market_type not in {"futures", "awards"}:
        return {}

    by_event = _group_historical_odds_by_event(odds)
    target = _target_from_market_title(market)
    best: dict[str, Any] = {}
    for event_id, lines in by_event.items():
        if not lines:
            continue
        event = _event_proxy(lines[0])
        event_score = _outright_event_score(market, event, market_type)
        scored_selections = sorted(
            ((line.selection, _outcome_match_score(target or "", line.selection)) for line in lines),
            key=lambda item: item[1],
            reverse=True,
        )
        selection, outcome_score = scored_selections[0] if scored_selections else (None, 0.0)
        confidence = min(1.0, 0.45 * event_score + 0.45 * outcome_score + 0.10)
        if not best or confidence > float(best.get("match_confidence", 0)):
            best = {
                "available_sportsbook_event": getattr(event, "event_name", None),
                "available_sportsbook_selection": selection,
                "match_confidence": confidence,
                "match_score_components": {
                    "event_score": event_score,
                    "outcome_score": outcome_score,
                    "target_outcome": target,
                    "market_type": market_type,
                },
            }
    return best


def persist_signal_results(
    db: Session,
    edge: HistoricalEdge,
    direction: str,
    config: dict[str, float | bool] | None = None,
    evaluations: list[PaperTradeEvaluation] | None = None,
) -> PaperTradeSignal:
    config = {**DEFAULT_BACKTEST_CONFIG, **(config or {})}
    signal = PaperTradeSignal(
        market_id=edge.market.id,
        title=edge.market.event_name,
        market_type=edge.market.market_type,
        league=edge.market.league,
        source=edge.market.source,
        timestamp=edge.timestamp,
        display_outcome=edge.display_outcome,
        direction=direction,
        entry_market_yes_probability=edge.market_yes_probability,
        entry_sportsbook_fair_probability=edge.sportsbook_fair_probability,
        entry_net_edge=edge.net_edge,
        confidence_score=edge.confidence_score,
        match_confidence=edge.match_confidence,
        liquidity=edge.liquidity,
        raw_payload={
            "matched_event": edge.matched_event_name,
            "matched_selection": edge.matched_selection,
            "bookmakers": edge.bookmaker_probabilities,
            "raw_prediction_side": edge.raw_prediction_side,
            "raw_outcome_side": edge.raw_prediction_side,
            "token_id": edge.price_token_id,
            "raw_historical_price": edge.historical_price,
            "historical_price": edge.historical_price,
            "derived_market_yes_probability": edge.market_yes_probability,
            "market_title": edge.market.event_name,
            "external_id": edge.market.external_id,
            "condition_id": _condition_id_from_market(edge.market),
            "liquidity_status": edge.liquidity_status,
            "liquidity_adjusted": edge.liquidity_adjusted,
            "match_score_components": edge.match_score_components,
        },
    )
    db.add(signal)
    db.flush()

    evaluations = evaluations or evaluate_signal_horizons(db, edge, direction, config=config)
    for evaluation in evaluations:
        db.add(_result_from_evaluation(signal, edge.market.id, evaluation))
    return signal


def evaluate_signal_horizons(
    db: Session,
    edge: HistoricalEdge,
    direction: str,
    config: dict[str, float | bool] | None = None,
) -> list[PaperTradeEvaluation]:
    config = {**DEFAULT_BACKTEST_CONFIG, **(config or {})}
    if not _valid_probability(edge.market_yes_probability) or not _valid_probability(edge.sportsbook_fair_probability):
        return [
            PaperTradeEvaluation(
                horizon=horizon,
                exit_timestamp=None,
                exit_market_yes_probability=None,
                exit_sportsbook_fair_probability=None,
                exit_net_edge=None,
                paper_pnl_per_contract=None,
                return_on_stake=None,
                edge_change=None,
                did_edge_close=None,
                moved_expected_direction=None,
                skip_reason="invalid_probability_range",
                evaluation_status="invalid_probability",
            )
            for horizon in HORIZONS
        ]

    simulate_negative = bool(config["simulate_negative_edge"])
    evaluations: list[PaperTradeEvaluation] = []
    for horizon, delta in HORIZONS.items():
        if direction == "possible_yes_overpricing" and not simulate_negative:
            evaluations.append(
                PaperTradeEvaluation(
                    horizon=horizon,
                    exit_timestamp=None,
                    exit_market_yes_probability=None,
                    exit_sportsbook_fair_probability=None,
                    exit_net_edge=None,
                    paper_pnl_per_contract=None,
                    return_on_stake=None,
                    edge_change=None,
                    signal_direction="negative_edge_tracked_only",
                    paper_side=None,
                    entry_price=None,
                    exit_price=None,
                    did_edge_close=None,
                    moved_expected_direction=None,
                    skip_reason="negative_edge_no_long_simulation",
                    evaluation_status="negative_edge_no_long_simulation",
                )
            )
            continue

        exit_time = edge.timestamp + delta
        future_price = nearest_prediction_price(
            db,
            edge.market.id,
            exit_time,
            tolerance=timedelta(minutes=float(config["exit_price_tolerance_minutes"])),
            after=edge.timestamp,
        )
        future_edge = reconstruct_historical_edge(db, edge.market, exit_time, config=config) if future_price else None
        is_negative_simulation = direction == "possible_yes_overpricing"
        evaluation = evaluate_paper_long_yes(
            entry_price=edge.market_yes_probability,
            exit_price=historical_market_yes_probability(future_price, effective_prediction_market_type(edge.market)) if future_price else None,
            entry_edge=edge.net_edge,
            exit_edge=future_edge.net_edge if future_edge and not future_edge.skip_reason else None,
            horizon=horizon,
            exit_timestamp=future_price.timestamp if future_price else None,
            edge_close_threshold=float(config["edge_close_threshold"]),
            entry_sportsbook_fair=edge.sportsbook_fair_probability,
            signal_direction="negative_edge_no_side" if is_negative_simulation else "positive_edge_long_yes",
            paper_side="NO" if is_negative_simulation else "YES",
        )
        evaluations.append(evaluation)
    return evaluations


def _historical_h2h_probabilities(
    market: Market,
    odds: list[HistoricalSportsbookOddsSnapshot],
) -> tuple[list[dict[str, Any]], EventMatch] | None:
    by_event = _group_historical_odds_by_event(odds)
    event_matches = [
        score_prediction_market_event_match(market, _event_proxy(lines[0]))
        for lines in by_event.values()
        if lines
    ]
    event_matches.sort(key=lambda match: match.confidence_score, reverse=True)
    if not event_matches or event_matches[0].confidence_score < 0.72:
        return None
    match = event_matches[0]
    selected_lines = by_event[getattr(match.event, "provider_event_id")]
    probabilities = _probabilities_for_historical_lines(market, selected_lines, match)
    return (probabilities, match) if probabilities else None


def _historical_outright_probabilities(
    market: Market,
    market_type: str,
    odds: list[HistoricalSportsbookOddsSnapshot],
) -> tuple[list[dict[str, Any]], EventMatch] | None:
    by_event = _group_historical_odds_by_event(odds)
    target = _target_from_market_title(market)
    if target is None:
        return None
    scored_events: list[tuple[float, str, Any]] = []
    for event_id, lines in by_event.items():
        event = _event_proxy(lines[0])
        event_score = _outright_event_score(market, event, market_type)
        if event_score >= 0.45:
            scored_events.append((event_score, event_id, event))
    scored_events.sort(reverse=True, key=lambda item: item[0])
    for event_score, event_id, event in scored_events:
        probabilities = _outright_probabilities_for_lines(target, by_event[event_id])
        if not probabilities:
            continue
        outcome_score = max(float(book["outcome_match_score"]) for book in probabilities)
        confidence = min(1.0, 0.45 * event_score + 0.45 * outcome_score + 0.10 * min(len(probabilities) / 4, 1))
        if confidence < 0.72:
            continue
        match = EventMatch(
            event=event,
            normalized_event_key=getattr(event, "normalized_event_key", ""),
            confidence_score=confidence,
            league_score=1.0,
            team_score=outcome_score,
            date_score=0.5,
            fuzzy_score=event_score,
            match_type=f"{market_type}_historical_outright",
            reason="matched historical sportsbook outright category and outcome selection",
        )
        return probabilities, match
    return None


def _probabilities_for_historical_lines(
    market: Market,
    lines: list[HistoricalSportsbookOddsSnapshot],
    match: EventMatch,
) -> list[dict[str, Any]]:
    by_book = _group_latest_by_book_selection(lines)
    probabilities: list[dict[str, Any]] = []
    event = match.event
    for bookmaker, selections in by_book.items():
        selected = _selected_line_for_market(market, event, selections)
        if selected is None or len(selections) < 2:
            continue
        total = sum(line.implied_probability for line in selections.values())
        if total <= 0:
            continue
        probabilities.append(
            {
                "bookmaker": bookmaker,
                "selection": selected.selection,
                "weight": 1.0,
                "original_odds": {"american": selected.american_odds, "decimal": selected.decimal_odds},
                "implied_probability": selected.implied_probability,
                "no_vig_probability": selected.implied_probability / total,
                "observed_at": selected.snapshot_timestamp.isoformat(),
            }
        )
    return probabilities


def _outright_probabilities_for_lines(target: str, lines: list[HistoricalSportsbookOddsSnapshot]) -> list[dict[str, Any]]:
    by_book = _group_latest_by_book_selection(lines)
    probabilities: list[dict[str, Any]] = []
    for bookmaker, selections in by_book.items():
        scored = sorted(
            ((key, line, _outcome_match_score(target, line.selection)) for key, line in selections.items()),
            key=lambda item: item[2],
            reverse=True,
        )
        if not scored or scored[0][2] < 0.86:
            continue
        selected = scored[0][1]
        total = sum(line.implied_probability for line in selections.values())
        if total <= 0:
            continue
        probabilities.append(
            {
                "bookmaker": bookmaker,
                "selection": selected.selection,
                "target_outcome": target,
                "weight": 1.0,
                "original_odds": {"american": selected.american_odds, "decimal": selected.decimal_odds},
                "implied_probability": selected.implied_probability,
                "no_vig_probability": selected.implied_probability / total,
                "outcome_match_score": scored[0][2],
                "observed_at": selected.snapshot_timestamp.isoformat(),
            }
        )
    return probabilities


def _group_historical_odds_by_event(
    odds: list[HistoricalSportsbookOddsSnapshot],
) -> dict[str, list[HistoricalSportsbookOddsSnapshot]]:
    grouped: dict[str, list[HistoricalSportsbookOddsSnapshot]] = defaultdict(list)
    for line in odds:
        grouped[line.provider_event_id].append(line)
    return grouped


def _group_latest_by_book_selection(
    lines: list[HistoricalSportsbookOddsSnapshot],
) -> dict[str, dict[str, HistoricalSportsbookOddsSnapshot]]:
    grouped: dict[str, dict[str, HistoricalSportsbookOddsSnapshot]] = defaultdict(dict)
    for line in sorted(lines, key=lambda item: item.snapshot_timestamp, reverse=True):
        key = normalize_team_name(line.selection)
        grouped[line.bookmaker].setdefault(key, line)
    return grouped


def _event_proxy(line: HistoricalSportsbookOddsSnapshot) -> Any:
    return type(
        "HistoricalSportsbookEventProxy",
        (),
        {
            "id": line.provider_event_id,
            "provider_event_id": line.provider_event_id,
            "event_name": line.event_name,
            "league": line.league,
            "home_team": line.home_team,
            "away_team": line.away_team,
            "normalized_event_key": line.normalized_event_key,
            "start_time": line.start_time,
            "extra": {"raw_event": line.raw_payload.get("event", {}) if isinstance(line.raw_payload, dict) else {}},
        },
    )()


def historical_market_yes_probability(price: HistoricalPredictionMarketPriceSnapshot, market_type: str) -> float:
    display_outcome = price.display_outcome or ""
    derived, _ = market_yes_price_from_raw(price.raw_price, price.raw_selection, market_type, display_outcome)
    return derived


def _snapshot_from_historical_price(price: HistoricalPredictionMarketPriceSnapshot, market_type: str) -> Any:
    return PredictionMarketSnapshot(
        market_id=price.market_id,
        source=price.source,
        bid_probability=None,
        ask_probability=None,
        last_price=price.raw_price,
        midpoint_probability=price.raw_price,
        spread=None,
        liquidity=price.liquidity,
        volume=price.volume,
        raw_payload=price.raw_payload,
        observed_at=price.timestamp,
    )


def _target_from_market_title(market: Market) -> str | None:
    selection = market.selection.strip()
    if selection and selection.lower() not in {"yes", "no"}:
        return selection
    title = market.event_name.strip()
    lower = title.lower()
    for delimiter in (" beat ", " beats ", " defeat ", " defeats ", " win ", " make ", " reach "):
        if lower.startswith("will ") and delimiter in lower:
            start = len("will ")
            end = lower.find(delimiter, start)
            return title[start:end].strip(" ?") or None
    return None


def _skipped_edge(
    market: Market,
    timestamp: datetime,
    reason: str,
    *,
    price: HistoricalPredictionMarketPriceSnapshot | None = None,
    odds: list[HistoricalSportsbookOddsSnapshot] | None = None,
    match_debug: dict[str, Any] | None = None,
    allow_missing_liquidity: bool = False,
    exact_skip_detail: str | None = None,
) -> HistoricalEdge:
    odds = odds or []
    first_odds = odds[0] if odds else None
    match_debug = match_debug or {}
    return HistoricalEdge(
        market=market,
        timestamp=timestamp,
        market_yes_probability=0,
        sportsbook_fair_probability=0,
        net_edge=0,
        gross_edge=0,
        confidence_score=0,
        match_confidence=float(match_debug.get("match_confidence", 0) or 0),
        liquidity=price.liquidity if price else None,
        display_outcome=price.display_outcome if price else None,
        bookmaker_probabilities=[],
        matched_event_name=None,
        matched_selection=None,
        skip_reason=reason,
        raw_prediction_side=price.raw_selection if price else None,
        historical_price=price.raw_price if price else None,
        price_token_id=price.token_id if price else None,
        price_raw_payload=price.raw_payload if price and isinstance(price.raw_payload, dict) else {},
        available_sportsbook_event=match_debug.get("available_sportsbook_event") or (first_odds.event_name if first_odds else None),
        available_sportsbook_selection=match_debug.get("available_sportsbook_selection") or (first_odds.selection if first_odds else None),
        match_score_components=match_debug.get("match_score_components", {}),
        liquidity_status=(
            "unknown"
            if price and _is_missing_liquidity(price.liquidity) and allow_missing_liquidity
            else ("missing" if price and _is_missing_liquidity(price.liquidity) else ("known" if price else "unknown"))
        ),
        liquidity_adjusted=not (bool(price and _is_missing_liquidity(price.liquidity)) and allow_missing_liquidity),
        exact_skip_detail=exact_skip_detail,
    )


def _result_from_evaluation(signal: PaperTradeSignal, market_id: str, evaluation: PaperTradeEvaluation) -> SignalBacktestResult:
    return SignalBacktestResult(
        signal_id=signal.id,
        market_id=market_id,
        horizon=evaluation.horizon,
        exit_timestamp=evaluation.exit_timestamp,
        exit_market_yes_probability=evaluation.exit_market_yes_probability,
        exit_sportsbook_fair_probability=evaluation.exit_sportsbook_fair_probability,
        exit_net_edge=evaluation.exit_net_edge,
        paper_pnl_per_contract=evaluation.paper_pnl_per_contract,
        return_on_stake=evaluation.return_on_stake,
        edge_change=evaluation.edge_change,
        did_edge_close=evaluation.did_edge_close,
        moved_expected_direction=evaluation.moved_expected_direction,
        skip_reason=evaluation.skip_reason,
        raw_payload={
            "liquidity_status": signal.raw_payload.get("liquidity_status") if isinstance(signal.raw_payload, dict) else None,
            "liquidity_adjusted": signal.raw_payload.get("liquidity_adjusted") if isinstance(signal.raw_payload, dict) else None,
            "evaluation_status": evaluation.evaluation_status,
            "signal_direction": evaluation.signal_direction,
            "paper_side": evaluation.paper_side,
            "entry_price": evaluation.entry_price,
            "exit_price": evaluation.exit_price,
            "market_yes_change": evaluation.market_yes_change,
            "sportsbook_fair_change": evaluation.sportsbook_fair_change,
            "absolute_edge_change": evaluation.absolute_edge_change,
            "closure_reason": evaluation.closure_reason,
        },
    )


def _event_match_scores(match: EventMatch) -> dict[str, float | str | None]:
    return {
        "league_score": match.league_score,
        "team_score": match.team_score,
        "date_score": match.date_score,
        "fuzzy_score": match.fuzzy_score,
        "match_type": match.match_type,
        "reason": match.reason,
    }


def _is_missing_liquidity(value: float | None) -> bool:
    return value is None or value <= 0


def _valid_probability(value: float | None) -> bool:
    return value is not None and 0 <= value <= 1


def _is_suspicious_edge(edge: HistoricalEdge) -> bool:
    return bool(
        _suspicious_probability_reason(
            market=edge.market,
            market_type=effective_prediction_market_type(edge.market),
            price=None,
            market_yes_probability=edge.market_yes_probability,
            sportsbook_fair_probability=edge.sportsbook_fair_probability,
            net_edge=edge.net_edge,
            raw_selection=edge.raw_prediction_side,
            raw_price=edge.historical_price,
        )
    )


def _suspicious_probability_reason(
    *,
    market: Market,
    market_type: str,
    price: HistoricalPredictionMarketPriceSnapshot | None,
    market_yes_probability: float,
    sportsbook_fair_probability: float,
    net_edge: float,
    raw_selection: str | None = None,
    raw_price: float | None = None,
) -> str | None:
    raw_selection = raw_selection or (price.raw_selection if price else None)
    raw_price = raw_price if raw_price is not None else (price.raw_price if price else None)
    if abs(net_edge) > 0.50:
        return "Net edge magnitude exceeded 50%, which usually indicates stale data or YES/NO orientation mismatch."
    if market_type in {"futures", "awards", "outrights"} and market_yes_probability > 0.95:
        title = market.event_name.lower()
        championship_text = any(term in title for term in ("finals", "stanley cup", "world cup", "championship", "win the"))
        raw_no_leak = (raw_selection or "").lower() == "no" and raw_price is not None and raw_price > 0.95
        if championship_text or raw_no_leak:
            return "Futures/awards Market YES probability is above 95% for a likely longshot-style market."
    if not _valid_probability(sportsbook_fair_probability):
        return "Sportsbook fair probability was outside [0, 1]."
    return None


def _condition_id_from_market(market: Market) -> str | None:
    raw = market.extra.get("raw_market") if isinstance(market.extra, dict) else None
    payload = raw.get("market") if isinstance(raw, dict) and isinstance(raw.get("market"), dict) else raw
    if isinstance(payload, dict):
        value = payload.get("condition_id") or payload.get("conditionId")
        return str(value) if value else None
    return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
