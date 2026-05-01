from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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
    "odds_tolerance_minutes": 30.0,
    "edge_close_threshold": 0.005,
    "simulate_negative_edge": False,
}


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
    did_edge_close: bool | None
    moved_expected_direction: bool | None
    skip_reason: str | None = None


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
        return max(0.0, min(1.0, 1 - raw_price)), "positive_yes_complemented_from_no"
    return raw_price, "raw_selection"


def detect_signal(edge: HistoricalEdge, config: dict[str, float | bool] | None = None) -> str | None:
    config = {**DEFAULT_BACKTEST_CONFIG, **(config or {})}
    if edge.skip_reason:
        return None
    if abs(edge.net_edge) < float(config["min_abs_edge"]):
        return None
    if edge.confidence_score < float(config["min_confidence_score"]):
        return None
    if edge.match_confidence < float(config["min_match_confidence"]):
        return None
    if edge.liquidity is None or edge.liquidity < float(config["min_liquidity"]):
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
) -> PaperTradeEvaluation:
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
            did_edge_close=None,
            moved_expected_direction=None,
            skip_reason="no_historical_polymarket_price",
        )
    pnl = exit_price - entry_price
    return_on_stake = pnl / entry_price if entry_price > 0 else None
    edge_change = exit_edge - entry_edge if exit_edge is not None else None
    return PaperTradeEvaluation(
        horizon=horizon,
        exit_timestamp=exit_timestamp,
        exit_market_yes_probability=exit_price,
        exit_sportsbook_fair_probability=(exit_price + exit_edge) if exit_edge is not None else None,
        exit_net_edge=exit_edge,
        paper_pnl_per_contract=pnl,
        return_on_stake=return_on_stake,
        edge_change=edge_change,
        did_edge_close=abs(exit_edge) <= edge_close_threshold if exit_edge is not None else None,
        moved_expected_direction=exit_price > entry_price,
    )


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
        return _skipped_edge(market, timestamp, "no_historical_polymarket_price")

    odds = nearest_sportsbook_odds(
        db,
        timestamp,
        market_type=market_type,
        tolerance=timedelta(minutes=float(config["odds_tolerance_minutes"])),
    )
    if not odds:
        return _skipped_edge(market, timestamp, "no_historical_sportsbook_odds")

    probability_result = historical_bookmaker_probabilities(market, market_type, odds)
    if probability_result is None:
        return _skipped_edge(market, timestamp, "no_confident_match")

    bookmaker_probabilities, event_match = probability_result
    probabilities = [book["no_vig_probability"] for book in bookmaker_probabilities]
    weights = [book["weight"] for book in bookmaker_probabilities]
    fair_probability = weighted_consensus_fair_probability(probabilities, weights)
    dispersion = consensus_dispersion(probabilities)

    synthetic_snapshot = _snapshot_from_historical_price(price)
    prediction_inputs = _prediction_probability_inputs(synthetic_snapshot, market, market_type)
    edge = calculate_edge(
        EdgeInputs(
            fair_probability=fair_probability,
            bid_probability=prediction_inputs.bid_probability,
            ask_probability=prediction_inputs.ask_probability,
            last_price=prediction_inputs.last_price,
            liquidity=price.liquidity,
            sportsbook_count=len(bookmaker_probabilities),
            consensus_dispersion=dispersion,
        )
    )
    return HistoricalEdge(
        market=market,
        timestamp=price.timestamp,
        market_yes_probability=edge.market_probability,
        sportsbook_fair_probability=edge.fair_probability,
        net_edge=edge.net_edge,
        gross_edge=edge.gross_edge,
        confidence_score=edge.confidence_score,
        match_confidence=event_match.confidence_score,
        liquidity=price.liquidity,
        display_outcome=prediction_inputs.display_outcome or price.display_outcome,
        bookmaker_probabilities=bookmaker_probabilities,
        matched_event_name=getattr(event_match.event, "event_name", None),
        matched_selection=bookmaker_probabilities[0].get("selection") if bookmaker_probabilities else None,
    )


def nearest_prediction_price(
    db: Session,
    market_id: str,
    timestamp: datetime,
    *,
    tolerance: timedelta,
) -> HistoricalPredictionMarketPriceSnapshot | None:
    target = _ensure_utc(timestamp)
    rows = list(
        db.scalars(
            select(HistoricalPredictionMarketPriceSnapshot)
            .where(HistoricalPredictionMarketPriceSnapshot.market_id == market_id)
            .where(HistoricalPredictionMarketPriceSnapshot.timestamp >= target - tolerance)
            .where(HistoricalPredictionMarketPriceSnapshot.timestamp <= target + tolerance)
        )
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


def persist_signal_results(db: Session, edge: HistoricalEdge, direction: str, config: dict[str, float | bool] | None = None) -> PaperTradeSignal:
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
        },
    )
    db.add(signal)
    db.flush()

    simulate_negative = bool(config["simulate_negative_edge"])
    for horizon, delta in HORIZONS.items():
        if direction == "possible_yes_overpricing" and not simulate_negative:
            db.add(
                SignalBacktestResult(
                    signal_id=signal.id,
                    market_id=edge.market.id,
                    horizon=horizon,
                    skip_reason="negative_edge_no_default_paper_trade",
                    raw_payload={},
                )
            )
            continue

        exit_time = edge.timestamp + delta
        future_price = nearest_prediction_price(
            db,
            edge.market.id,
            exit_time,
            tolerance=timedelta(minutes=float(config["price_tolerance_minutes"])),
        )
        future_edge = reconstruct_historical_edge(db, edge.market, exit_time, config=config) if future_price else None
        evaluation = evaluate_paper_long_yes(
            entry_price=edge.market_yes_probability,
            exit_price=future_price.market_yes_price if future_price else None,
            entry_edge=edge.net_edge,
            exit_edge=future_edge.net_edge if future_edge and not future_edge.skip_reason else None,
            horizon=horizon,
            exit_timestamp=future_price.timestamp if future_price else None,
            edge_close_threshold=float(config["edge_close_threshold"]),
        )
        db.add(_result_from_evaluation(signal, edge.market.id, evaluation))
    return signal


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


def _snapshot_from_historical_price(price: HistoricalPredictionMarketPriceSnapshot) -> Any:
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


def _skipped_edge(market: Market, timestamp: datetime, reason: str) -> HistoricalEdge:
    return HistoricalEdge(
        market=market,
        timestamp=timestamp,
        market_yes_probability=0,
        sportsbook_fair_probability=0,
        net_edge=0,
        gross_edge=0,
        confidence_score=0,
        match_confidence=0,
        liquidity=None,
        display_outcome=None,
        bookmaker_probabilities=[],
        matched_event_name=None,
        matched_selection=None,
        skip_reason=reason,
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
        raw_payload={},
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
