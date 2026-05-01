from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import FairValueSnapshot, Market, PredictionMarketSnapshot, SportsbookEvent, SportsbookOddsSnapshot
from app.services.fair_value import (
    EdgeInputs,
    calculate_edge,
    consensus_dispersion,
    weighted_consensus_fair_probability,
)
from app.services.market_classification import effective_prediction_market_type
from app.services.normalization import (
    EventMatch,
    extract_h2h_market_info,
    infer_market_league,
    match_prediction_market_to_sportsbook_events,
    normalize_team_name,
    possible_event_matches,
    slugify,
    team_mention_position,
    team_mention_score,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BookmakerProbabilityResult:
    bookmaker_probabilities: list[dict[str, Any]]
    event_match: EventMatch | None = None
    skip_reason: str | None = None
    skip_detail: str = ""


@dataclass(frozen=True)
class OutrightMatchDebug:
    market_title: str
    target_outcome: str | None
    market_context: str | None
    sportsbook_event: str | None
    sportsbook_selection: str | None
    confidence_score: float
    reason: str


@dataclass(frozen=True)
class PredictionProbabilityInputs:
    bid_probability: float | None
    ask_probability: float | None
    last_price: float | None
    raw_bid_probability: float | None
    raw_ask_probability: float | None
    raw_last_price: float | None
    orientation: str
    display_outcome: str | None


@dataclass(frozen=True)
class OutrightSnapshotIndex:
    grouped_by_event_book: dict[tuple[str, str], list[SportsbookOddsSnapshot]]
    event_by_id: dict[str, SportsbookEvent]


def possible_outright_matches(
    market: Market,
    snapshots: list[SportsbookOddsSnapshot],
    *,
    market_type: str | None = None,
    limit: int = 3,
) -> list[OutrightMatchDebug]:
    effective_market_type = market_type or effective_prediction_market_type(market)
    target = _target_outcome_from_market(market)
    context = _market_outright_context(market, effective_market_type)
    if effective_market_type not in {"futures", "awards"}:
        return [
            OutrightMatchDebug(
                market_title=market.event_name,
                target_outcome=target,
                market_context=context,
                sportsbook_event=None,
                sportsbook_selection=None,
                confidence_score=0.0,
                reason=f"not a futures/awards market: {effective_market_type}",
            )
        ]
    if target is None or context is None:
        return [
            OutrightMatchDebug(
                market_title=market.event_name,
                target_outcome=target,
                market_context=context,
                sportsbook_event=None,
                sportsbook_selection=None,
                confidence_score=0.0,
                reason="could not extract target outcome or market context",
            )
        ]

    by_event_book: dict[tuple[str, str], list[SportsbookOddsSnapshot]] = defaultdict(list)
    event_scores: dict[str, float] = {}
    for snapshot in snapshots:
        if snapshot.market_type != "outrights" or snapshot.event is None:
            continue
        event_score = _outright_event_score(market, snapshot.event, effective_market_type)
        if event_score <= 0:
            continue
        by_event_book[(snapshot.event_id, snapshot.bookmaker)].append(snapshot)
        event_scores[snapshot.event_id] = max(event_scores.get(snapshot.event_id, 0.0), event_score)

    candidates: list[OutrightMatchDebug] = []
    event_seen: set[tuple[str, str]] = set()
    for (event_id, _bookmaker), lines in by_event_book.items():
        latest_by_selection = _latest_lines_by_selection(lines)
        selection_key, outcome_score = _selected_outright_key(target, latest_by_selection)
        event = lines[0].event
        if event is None:
            continue
        if selection_key is None:
            best_selection = _best_outright_selection_name(target, latest_by_selection)
            key = (event_id, best_selection or "")
            if key in event_seen:
                continue
            event_seen.add(key)
            candidates.append(
                OutrightMatchDebug(
                    market_title=market.event_name,
                    target_outcome=target,
                    market_context=context,
                    sportsbook_event=event.event_name,
                    sportsbook_selection=best_selection,
                    confidence_score=min(0.69, 0.5 * event_scores[event_id] + 0.5 * outcome_score),
                    reason=f"category matched but no confident outcome selection; outcome_score={outcome_score:.3f}",
                )
            )
            continue

        selected_line = latest_by_selection[selection_key]
        confidence = min(1.0, 0.5 * event_scores[event_id] + 0.5 * outcome_score)
        key = (event_id, selected_line.selection)
        if key in event_seen:
            continue
        event_seen.add(key)
        candidates.append(
            OutrightMatchDebug(
                market_title=market.event_name,
                target_outcome=target,
                market_context=context,
                sportsbook_event=event.event_name,
                sportsbook_selection=selected_line.selection,
                confidence_score=confidence,
                reason="matched sportsbook outright category and outcome selection",
            )
        )

    if not candidates:
        return [
            OutrightMatchDebug(
                market_title=market.event_name,
                target_outcome=target,
                market_context=context,
                sportsbook_event=None,
                sportsbook_selection=None,
                confidence_score=0.0,
                reason="no compatible sportsbook outright category found",
            )
        ]
    candidates.sort(key=lambda candidate: candidate.confidence_score, reverse=True)
    return candidates[:limit]


def main() -> None:
    settings = get_settings()
    assumptions = settings.default_user_model
    computed = 0
    skipped = 0
    skip_reasons: Counter[str] = Counter()
    market_type_counts: Counter[str] = Counter()
    outright_stats: Counter[str] = Counter()
    h2h_stats: Counter[str] = Counter()

    with SessionLocal() as db:
        h2h_events = _events_with_market_type(db, {"h2h", "moneyline"})
        h2h_stats["h2h_sportsbook_events_collected"] = len(h2h_events)
        outright_index = _build_outright_snapshot_index(_latest_outright_snapshots(db))
        events_by_key: dict[str, list[SportsbookEvent]] = defaultdict(list)
        for event in h2h_events:
            events_by_key[event.normalized_event_key].append(event)

        markets = list(db.scalars(select(Market).where(Market.status == "open")))
        for market in markets:
            effective_market_type = effective_prediction_market_type(market)
            market_type_counts[effective_market_type] += 1
            if market.market_type != effective_market_type:
                market.market_type = effective_market_type
            if effective_market_type not in {"h2h_game", "futures", "awards"}:
                _log_skip(
                    skip_reasons,
                    market,
                    "unsupported_market_type",
                    f"market_type={effective_market_type}",
                )
                skipped += 1
                continue

            snapshot = _latest_prediction_snapshot(db, market.id)
            if snapshot is None:
                _log_skip(skip_reasons, market, "no_prediction_snapshot_exists")
                skipped += 1
                continue

            probability_result = _bookmaker_probabilities_for_market_type(
                db=db,
                market=market,
                market_type=effective_market_type,
                events=h2h_events,
                events_by_key=events_by_key,
                assumptions=assumptions,
                stats=outright_stats,
                h2h_stats=h2h_stats,
                outright_index=outright_index,
            )
            if probability_result.skip_reason:
                _log_skip(
                    skip_reasons,
                    market,
                    probability_result.skip_reason,
                    probability_result.skip_detail,
                )
                skipped += 1
                continue
            if probability_result.event_match is None or not probability_result.bookmaker_probabilities:
                _log_skip(skip_reasons, market, "no_bookmaker_probabilities", f"market_type={effective_market_type}")
                skipped += 1
                continue

            match = probability_result.event_match
            bookmaker_probabilities = probability_result.bookmaker_probabilities

            probabilities = [book["no_vig_probability"] for book in bookmaker_probabilities]
            weights = [book["weight"] for book in bookmaker_probabilities]
            fair_probability = weighted_consensus_fair_probability(probabilities, weights)
            dispersion = consensus_dispersion(probabilities)
            prediction_inputs = _prediction_probability_inputs(snapshot, market, effective_market_type)
            edge = calculate_edge(
                EdgeInputs(
                    fair_probability=fair_probability,
                    bid_probability=prediction_inputs.bid_probability,
                    ask_probability=prediction_inputs.ask_probability,
                    last_price=prediction_inputs.last_price,
                    liquidity=snapshot.liquidity,
                    sportsbook_count=len(bookmaker_probabilities),
                    consensus_dispersion=dispersion,
                    min_liquidity=float(assumptions.get("min_liquidity", 500)),
                    spread_penalty_multiplier=float(assumptions.get("spread_penalty_multiplier", 0.5)),
                    liquidity_penalty_multiplier=float(assumptions.get("liquidity_penalty_multiplier", 0.02)),
                )
            )
            explanation_json = _build_explanation_json(
                market=market,
                prediction_snapshot=snapshot,
                event_match=match,
                bookmaker_probabilities=bookmaker_probabilities,
                fair_probability=fair_probability,
                consensus_dispersion_value=dispersion,
                prediction_inputs=prediction_inputs,
                edge=edge,
            )
            db.add(
                FairValueSnapshot(
                    market_id=market.id,
                    fair_probability=edge.fair_probability,
                    market_probability=edge.market_probability,
                    gross_edge=edge.gross_edge,
                    net_edge=edge.net_edge,
                    spread=edge.spread,
                    liquidity=snapshot.liquidity,
                    confidence_score=edge.confidence_score,
                    sportsbook_consensus=explanation_json,
                    assumptions=assumptions,
                    explanation_json=explanation_json,
                    explanation=(
                        "Fair probability is a weighted no-vig sportsbook consensus. "
                        "Net edge subtracts spread and liquidity penalties from fair minus market probability."
                    ),
                )
            )
            computed += 1
        db.commit()

    logger.info("Computed %s fair values; skipped %s markets", computed, skipped)
    logger.info("Prediction markets checked by market_type: %s", dict(sorted(market_type_counts.items())))
    if h2h_stats:
        logger.info("H2H matching stats: %s", dict(sorted(h2h_stats.items())))
    if outright_stats:
        logger.info("Futures/awards matching stats: %s", dict(sorted(outright_stats.items())))
    if skip_reasons:
        logger.info(
            "Skip breakdown: %s",
            ", ".join(f"{reason}={count}" for reason, count in sorted(skip_reasons.items())),
        )


def _log_skip(skip_reasons: Counter[str], market: Market, reason: str, detail: str = "") -> None:
    skip_reasons[reason] += 1
    logger.info(
        "Skipped market %s (%s / %s): %s%s",
        market.id,
        market.source,
        market.event_name,
        reason,
        f" [{detail}]" if detail else "",
    )


def _populate_inferred_market_fields(market: Market, match: EventMatch) -> None:
    if match.confidence_score < 0.80:
        return
    if _market_key_needs_inference(market.normalized_event_key):
        market.normalized_event_key = match.normalized_event_key
    if not market.league or infer_market_league(market) in {"sports", "sport", "unknown-league"}:
        event_league = getattr(match.event, "league", None)
        if event_league:
            market.league = event_league


def _market_key_needs_inference(key: str | None) -> bool:
    if not key:
        return True
    return (
        key.startswith("sports:")
        or "unknown-date" in key
        or "unknown-participants" in key
    )


def _latest_prediction_snapshot(db, market_id: str) -> PredictionMarketSnapshot | None:
    return db.scalar(
        select(PredictionMarketSnapshot)
        .where(PredictionMarketSnapshot.market_id == market_id)
        .order_by(desc(PredictionMarketSnapshot.observed_at))
        .limit(1)
    )


def _sportsbook_odds_exist(db, event_id: str) -> bool:
    return (
        db.scalar(
            select(SportsbookOddsSnapshot.id)
            .where(SportsbookOddsSnapshot.event_id == event_id)
            .where(SportsbookOddsSnapshot.market_type.in_(("h2h", "moneyline")))
            .limit(1)
        )
        is not None
    )


def _events_with_market_type(db, market_types: set[str]) -> list[SportsbookEvent]:
    return list(
        db.scalars(
            select(SportsbookEvent)
            .join(SportsbookOddsSnapshot)
            .where(SportsbookOddsSnapshot.market_type.in_(market_types))
            .distinct()
        )
    )


def _latest_outright_snapshots(db) -> list[SportsbookOddsSnapshot]:
    return list(
        db.scalars(
            select(SportsbookOddsSnapshot)
            .where(SportsbookOddsSnapshot.market_type == "outrights")
            .options(selectinload(SportsbookOddsSnapshot.event))
            .order_by(desc(SportsbookOddsSnapshot.observed_at))
            .limit(8000)
        )
    )


def _build_outright_snapshot_index(snapshots: list[SportsbookOddsSnapshot]) -> OutrightSnapshotIndex:
    grouped: dict[tuple[str, str], list[SportsbookOddsSnapshot]] = defaultdict(list)
    event_by_id: dict[str, SportsbookEvent] = {}
    for snapshot in snapshots:
        if snapshot.event is None:
            continue
        grouped[(snapshot.event_id, snapshot.bookmaker)].append(snapshot)
        event_by_id[snapshot.event_id] = snapshot.event
    return OutrightSnapshotIndex(grouped_by_event_book=dict(grouped), event_by_id=event_by_id)


def _bookmaker_probabilities_for_market_type(
    *,
    db,
    market: Market,
    market_type: str,
    events: list[SportsbookEvent],
    events_by_key: dict[str, list[SportsbookEvent]],
    assumptions: dict[str, Any],
    stats: Counter[str] | None = None,
    h2h_stats: Counter[str] | None = None,
    outright_index: OutrightSnapshotIndex | None = None,
) -> BookmakerProbabilityResult:
    if market_type in {"h2h", "h2h_game"}:
        return _h2h_bookmaker_probabilities(
            db=db,
            market=market,
            events=events,
            events_by_key=events_by_key,
            assumptions=assumptions,
            stats=h2h_stats,
        )
    if market_type in {"futures", "awards"}:
        return _outright_bookmaker_probabilities(
            db=db,
            market=market,
            market_type=market_type,
            assumptions=assumptions,
            stats=stats,
            snapshot_index=outright_index,
        )
    return BookmakerProbabilityResult(
        bookmaker_probabilities=[],
        skip_reason="unsupported_market_type",
        skip_detail=f"market_type={market_type}",
    )


def _h2h_bookmaker_probabilities(
    *,
    db,
    market: Market,
    events: list[SportsbookEvent],
    events_by_key: dict[str, list[SportsbookEvent]],
    assumptions: dict[str, Any],
    stats: Counter[str] | None = None,
) -> BookmakerProbabilityResult:
    if stats is not None:
        stats["h2h_prediction_markets_found"] += 1
    if not events:
        return BookmakerProbabilityResult(
            bookmaker_probabilities=[],
            skip_reason="no_matching_sportsbook_event",
            skip_detail="no h2h/moneyline sportsbook events are available",
        )

    match = match_prediction_market_to_sportsbook_events(market, events, threshold=0.72)
    if match is None:
        scored = possible_event_matches(market, events, limit=1)
        best = scored[0] if scored else None
        if best and best.date_score == 0.0:
            reason = "start_time_too_far"
        elif best and best.team_score < 0.58:
            reason = "ambiguous_team_match"
        elif best and best.confidence_score > 0:
            reason = "low_match_confidence"
        else:
            reason = "no_matching_sportsbook_event"
        return BookmakerProbabilityResult(
            bookmaker_probabilities=[],
            skip_reason=reason,
            skip_detail=f"market_key={market.normalized_event_key or '<missing>'}",
        )
    if stats is not None:
        stats["h2h_matches_found"] += 1

    if market.normalized_event_key not in events_by_key and match.match_type != "exact_normalized_event_key":
        logger.info(
            "Matched market %s via fuzzy fallback: event=%s confidence=%.3f key=%s",
            market.id,
            getattr(match.event, "event_name", ""),
            match.confidence_score,
            match.normalized_event_key,
        )
    _populate_inferred_market_fields(market, match)

    if not _sportsbook_odds_exist(db, match.event.id):
        return BookmakerProbabilityResult(
            bookmaker_probabilities=[],
            event_match=match,
            skip_reason="no_h2h_odds",
            skip_detail=f"event_id={match.event.id}",
        )

    probabilities = _bookmaker_no_vig_probabilities(db, market, match.event, assumptions)
    if not probabilities:
        return BookmakerProbabilityResult(
            bookmaker_probabilities=[],
            event_match=match,
            skip_reason="ambiguous_team_match",
            skip_detail=f"event_id={match.event.id} event={match.event.event_name}",
        )
    if stats is not None:
        stats["h2h_fair_values_computed"] += 1
    return BookmakerProbabilityResult(bookmaker_probabilities=probabilities, event_match=match)


def _bookmaker_no_vig_probabilities(
    db,
    market: Market,
    event: SportsbookEvent,
    assumptions: dict[str, Any],
) -> list[dict[str, Any]]:
    excluded = {str(bookmaker) for bookmaker in assumptions.get("excluded_bookmakers", [])}
    weights = assumptions.get("bookmaker_weights", {})
    snapshots = list(
        db.scalars(
            select(SportsbookOddsSnapshot)
            .where(SportsbookOddsSnapshot.event_id == event.id)
            .where(SportsbookOddsSnapshot.market_type.in_(("h2h", "moneyline")))
            .order_by(desc(SportsbookOddsSnapshot.observed_at))
            .limit(500)
        )
    )
    by_book: dict[str, list[SportsbookOddsSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        if snapshot.bookmaker not in excluded:
            by_book[snapshot.bookmaker].append(snapshot)

    probabilities: list[dict[str, Any]] = []
    for bookmaker, book_lines in by_book.items():
        latest_by_selection = _latest_lines_by_selection(book_lines)
        selected_line = _selected_line_for_market(market, event, latest_by_selection)
        if selected_line is None or len(latest_by_selection) < 2:
            continue

        total_probability = sum(line.implied_probability for line in latest_by_selection.values())
        if total_probability <= 0:
            continue
        no_vig_probability = selected_line.implied_probability / total_probability
        no_vig_by_selection = {
            line.selection: line.implied_probability / total_probability
            for line in latest_by_selection.values()
        }
        opposing_probability = total_probability - selected_line.implied_probability
        no_vig_opposing_probability = 1 - no_vig_probability
        h2h_info = _h2h_info_for_match(market, event)
        weight = float(weights.get(bookmaker, 1.0)) if isinstance(weights, dict) else 1.0
        probabilities.append(
            {
                "bookmaker": bookmaker,
                "selection": selected_line.selection,
                "target_outcome": selected_line.selection,
                "opponent": h2h_info.get("opponent"),
                "weight": weight,
                "original_odds": {
                    "american": selected_line.american_odds,
                    "decimal": selected_line.decimal_odds,
                },
                "implied_probability": selected_line.implied_probability,
                "opposing_implied_probability": opposing_probability,
                "all_no_vig_probabilities": no_vig_by_selection,
                "h2h_market_total_implied_probability": total_probability,
                "no_vig_probability": no_vig_probability,
                "opposing_no_vig_probability": no_vig_opposing_probability,
                "observed_at": selected_line.observed_at.isoformat(),
            }
        )

    return probabilities


def _prediction_probability_inputs(
    snapshot: PredictionMarketSnapshot,
    market: Market,
    market_type: str,
) -> PredictionProbabilityInputs:
    display_outcome = _target_outcome_from_market(market)
    raw_selection = market.selection.lower().strip()
    should_complement = market_type in {"futures", "awards", "h2h", "h2h_game"} and raw_selection == "no" and display_outcome is not None

    if should_complement:
        bid = _complement_probability(snapshot.ask_probability)
        ask = _complement_probability(snapshot.bid_probability)
        last = _complement_probability(snapshot.last_price)
        orientation = "positive_yes_complemented_from_no"
    else:
        bid = snapshot.bid_probability
        ask = snapshot.ask_probability
        last = snapshot.last_price
        orientation = "raw_selection"

    return PredictionProbabilityInputs(
        bid_probability=bid,
        ask_probability=ask,
        last_price=last,
        raw_bid_probability=snapshot.bid_probability,
        raw_ask_probability=snapshot.ask_probability,
        raw_last_price=snapshot.last_price,
        orientation=orientation,
        display_outcome=display_outcome,
    )


def _complement_probability(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, 1 - value))


def _outright_bookmaker_probabilities(
    *,
    db,
    market: Market,
    market_type: str,
    assumptions: dict[str, Any],
    stats: Counter[str] | None = None,
    snapshot_index: OutrightSnapshotIndex | None = None,
) -> BookmakerProbabilityResult:
    if stats is not None:
        stats["futures_awards_markets_checked"] += 1
    excluded = {str(bookmaker) for bookmaker in assumptions.get("excluded_bookmakers", [])}
    weights = assumptions.get("bookmaker_weights", {})
    snapshot_index = snapshot_index or _build_outright_snapshot_index(_latest_outright_snapshots(db))
    if not snapshot_index.grouped_by_event_book:
        return BookmakerProbabilityResult(
            bookmaker_probabilities=[],
            skip_reason="no_sportsbook_outrights_odds_exist",
            skip_detail=(
                "The Odds API returned no outrights odds. Outrights are only available for selected "
                "sports/competitions and may not be included for the configured plan/regions."
            ),
        )

    target = _target_outcome_from_market(market)
    context = _market_outright_context(market, market_type)
    if target is None:
        return BookmakerProbabilityResult(
            bookmaker_probabilities=[],
            skip_reason="outright_outcome_could_not_be_identified",
            skip_detail=f"title={market.event_name} selection={market.selection}",
        )

    event_scores: dict[str, float] = {}
    for event_id, event in snapshot_index.event_by_id.items():
        event_score = _outright_event_score(market, event, market_type)
        if event_score < 0.45:
            continue
        event_scores[event_id] = event_score

    if stats is not None and event_scores:
        stats["futures_awards_with_matching_sportsbook_category"] += 1

    probabilities_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    best_outcome_scores: dict[str, float] = defaultdict(float)
    for (event_id, bookmaker), book_lines in snapshot_index.grouped_by_event_book.items():
        if event_id not in event_scores or bookmaker in excluded:
            continue
        latest_by_selection = _latest_lines_by_selection(book_lines)
        selection_key, outcome_score = _selected_outright_key(target, latest_by_selection)
        if selection_key is None or outcome_score < 0.86:
            continue
        total_probability = sum(line.implied_probability for line in latest_by_selection.values())
        if total_probability <= 0:
            continue
        selected_line = latest_by_selection[selection_key]
        selected_no_vig_probability = selected_line.implied_probability / total_probability
        weight = float(weights.get(bookmaker, 1.0)) if isinstance(weights, dict) else 1.0
        probabilities_by_event[event_id].append(
            {
                "bookmaker": bookmaker,
                "selection": selected_line.selection,
                "target_outcome": target,
                "weight": weight,
                "original_odds": {
                    "american": selected_line.american_odds,
                    "decimal": selected_line.decimal_odds,
                },
                "implied_probability": selected_line.implied_probability,
                "outright_market_total_implied_probability": total_probability,
                "no_vig_probability": selected_no_vig_probability,
                "selected_outcome_no_vig_probability": selected_no_vig_probability,
                "raw_prediction_market_selection": market.selection,
                "is_inverse_no_selection": False,
                "outcome_match_score": outcome_score,
                "observed_at": selected_line.observed_at.isoformat(),
            }
        )
        best_outcome_scores[event_id] = max(best_outcome_scores[event_id], outcome_score)

    if not probabilities_by_event:
        return BookmakerProbabilityResult(
            bookmaker_probabilities=[],
            skip_reason="no_confident_outright_match",
            skip_detail=f"target_outcome={target}",
        )
    if stats is not None:
        stats["futures_awards_with_matching_outcome_selection"] += 1

    best_event_id, bookmaker_probabilities = max(
        probabilities_by_event.items(),
        key=lambda item: (len(item[1]), event_scores.get(item[0], 0.0), best_outcome_scores.get(item[0], 0.0)),
    )
    event = snapshot_index.event_by_id[best_event_id]
    match_confidence = min(
        1.0,
        (0.45 * event_scores.get(best_event_id, 0.0))
        + (0.45 * best_outcome_scores.get(best_event_id, 0.0))
        + (0.10 * min(len(bookmaker_probabilities) / 4, 1.0)),
    )
    if match_confidence < 0.72:
        return BookmakerProbabilityResult(
            bookmaker_probabilities=[],
            skip_reason="no_confident_outright_match",
            skip_detail=(
                f"target_outcome={target} best_event={event.event_name} "
                f"confidence={match_confidence:.3f}"
            ),
        )

    match = EventMatch(
        event=event,
        normalized_event_key=event.normalized_event_key,
        confidence_score=match_confidence,
        league_score=_league_similarity(infer_market_league(market), event.league),
        team_score=best_outcome_scores.get(best_event_id, 0.0),
        date_score=0.5,
        fuzzy_score=event_scores.get(best_event_id, 0.0),
        match_type=f"{market_type}_outright",
        reason=f"matched {context or market_type} prediction outcome to sportsbook outrights outcome",
        inferred_market_normalized_event_key=event.normalized_event_key,
    )
    if stats is not None:
        stats["futures_awards_fair_values_computed"] += 1
    return BookmakerProbabilityResult(bookmaker_probabilities=bookmaker_probabilities, event_match=match)


def _latest_lines_by_selection(lines: list[SportsbookOddsSnapshot]) -> dict[str, SportsbookOddsSnapshot]:
    latest_by_selection: dict[str, SportsbookOddsSnapshot] = {}
    for line in lines:
        key = normalize_team_name(line.selection)
        if key not in latest_by_selection:
            latest_by_selection[key] = line
    return latest_by_selection


def _selected_line_for_market(
    market: Market,
    event: SportsbookEvent,
    latest_by_selection: dict[str, SportsbookOddsSnapshot],
) -> SportsbookOddsSnapshot | None:
    target_outcome = _target_outcome_from_market(market)
    if target_outcome:
        target_mentions = _strong_line_mentions(target_outcome, latest_by_selection, threshold=0.78)
        if len(target_mentions) == 1:
            return target_mentions[0]
        target_key = normalize_team_name(target_outcome)
        if target_key in latest_by_selection:
            return latest_by_selection[target_key]

    target_selection = normalize_team_name(market.selection)
    if market.selection.lower().strip() not in {"yes", "no"} and target_selection in latest_by_selection:
        return latest_by_selection[target_selection]

    selection_lower = market.selection.lower().strip()
    proposition_key = _proposition_selection_key(market, latest_by_selection)
    if proposition_key and selection_lower == "yes":
        return latest_by_selection.get(proposition_key)
    if proposition_key and selection_lower == "no":
        opposing_keys = [key for key in latest_by_selection if key != proposition_key]
        if len(opposing_keys) == 1:
            return latest_by_selection[opposing_keys[0]]

    selection_mentions = _strong_line_mentions(market.selection, latest_by_selection, threshold=0.78)
    if len(selection_mentions) == 1:
        return selection_mentions[0]

    market_mentions = _strong_line_mentions(market.event_name, latest_by_selection, threshold=0.90)
    if len(market_mentions) == 1:
        return market_mentions[0]

    event_teams = {normalize_team_name(team) for team in (event.home_team, event.away_team) if team}
    if event_teams:
        event_market_mentions = [
            line
            for line in market_mentions
            if normalize_team_name(line.selection) in event_teams
        ]
        if len(event_market_mentions) == 1:
            return event_market_mentions[0]

    return None


def _proposition_selection_key(
    market: Market,
    latest_by_selection: dict[str, SportsbookOddsSnapshot],
) -> str | None:
    title = market.event_name
    title_slug = f"-{_slug_text(title)}-"
    positive_moneyline_terms = (
        "-win-",
        "-wins-",
        "-beat-",
        "-beats-",
        "-defeat-",
        "-defeats-",
        "-advance-",
        "-advances-",
    )
    if not any(term in title_slug for term in positive_moneyline_terms):
        return None

    positioned_lines: list[tuple[int, str]] = []
    for key, line in latest_by_selection.items():
        if team_mention_score(title, line.selection) < 0.78:
            continue
        position = team_mention_position(title, line.selection)
        if position is not None:
            positioned_lines.append((position, key))

    if not positioned_lines:
        return None
    positioned_lines.sort(key=lambda item: item[0])
    return positioned_lines[0][1]


def _strong_line_mentions(
    text: str,
    latest_by_selection: dict[str, SportsbookOddsSnapshot],
    *,
    threshold: float,
) -> list[SportsbookOddsSnapshot]:
    return [
        line
        for line in latest_by_selection.values()
        if team_mention_score(text, line.selection) >= threshold
    ]


def _slug_text(value: str) -> str:
    return "-".join(part for part in normalize_team_name(value).split("-") if part)


def _target_outcome_from_market(market: Market) -> str | None:
    selection = market.selection.strip()
    if selection and selection.lower() not in {"yes", "no"}:
        return selection

    title = market.event_name.strip()
    lower_title = title.lower()
    for delimiter in (" beat ", " beats ", " defeat ", " defeats ", " win ", " make ", " reach "):
        marker = f"will "
        if lower_title.startswith(marker) and delimiter in lower_title:
            start = len(marker)
            end = lower_title.find(delimiter, start)
            candidate = title[start:end].strip(" ?")
            candidate = _strip_leading_article(candidate)
            if candidate:
                return candidate

    return None


def _h2h_info_for_match(market: Market, event: SportsbookEvent) -> dict[str, str | None]:
    info = extract_h2h_market_info(market.event_name, market.selection)
    target = info.target_team
    opponent = info.opponent_team
    event_teams = [
        team
        for team in (event.home_team, event.away_team)
        if team
    ]
    if target:
        target = next(
            (team for team in event_teams if normalize_team_name(team) == target),
            target,
        )
        opponent = next(
            (team for team in event_teams if normalize_team_name(team) != normalize_team_name(target)),
            opponent,
        )
    return {"target_team": target, "opponent": opponent}


def _selected_outright_key(
    target: str,
    latest_by_selection: dict[str, SportsbookOddsSnapshot],
) -> tuple[str | None, float]:
    scored = [
        (key, _outcome_match_score(target, line.selection))
        for key, line in latest_by_selection.items()
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    if not scored:
        return None, 0.0
    best_key, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0
    if best_score < 0.86:
        return None, best_score
    if second_score >= 0.84 and best_score - second_score < 0.05:
        return None, best_score
    return best_key, best_score


def _best_outright_selection_name(
    target: str,
    latest_by_selection: dict[str, SportsbookOddsSnapshot],
) -> str | None:
    if not latest_by_selection:
        return None
    return max(
        latest_by_selection.values(),
        key=lambda line: _outcome_match_score(target, line.selection),
    ).selection


def _outcome_match_score(target: str, sportsbook_selection: str) -> float:
    target_team = normalize_team_name(target)
    selection_team = normalize_team_name(sportsbook_selection)
    if target_team == selection_team:
        return 1.0

    target_slug = slugify(_strip_leading_article(target))
    selection_slug = slugify(_strip_leading_article(sportsbook_selection))
    if target_slug == selection_slug:
        return 0.98
    if target_slug and selection_slug and (target_slug in selection_slug or selection_slug in target_slug):
        return 0.90
    return SequenceMatcher(None, target_slug, selection_slug).ratio()


def _outright_event_score(market: Market, event: SportsbookEvent, market_type: str) -> float:
    market_league = infer_market_league(market)
    league_score = _league_similarity(market_league, event.league)
    if market_league not in {"", "sports", "sport", "unknown-league"} and league_score < 0.55:
        return 0.0
    title = market.event_name.lower()
    market_context = _market_outright_context(market, market_type)
    event_context = _sportsbook_outright_context(event)
    if market_context is None or event_context is None:
        return 0.0
    if not _outright_contexts_compatible(market_context, event_context):
        return 0.0

    event_text = " ".join(
        str(value or "").lower()
        for value in (
            event.event_name,
            event.league,
            (event.extra or {}).get("raw_event", {}).get("sport_key") if isinstance(event.extra, dict) else "",
        )
    )
    event_title_score = SequenceMatcher(None, slugify(title), slugify(event_text)).ratio()
    keyword_score = 1.0
    return max(
        0.35 * league_score + 0.35 * keyword_score + 0.30 * event_title_score,
        league_score * 0.70 if keyword_score >= 0.5 else 0.0,
    )


def _market_outright_context(market: Market, market_type: str) -> str | None:
    title_slug = slugify(market.event_name)
    if market_type == "awards":
        return _award_context(title_slug)
    if "stanley-cup" in title_slug:
        return "championship"
    if "nba-finals" in title_slug or "nba-championship" in title_slug:
        return "championship"
    if "world-cup" in title_slug:
        return "world_cup"
    if "super-bowl" in title_slug:
        return "championship"
    if "eastern-conference-finals" in title_slug or "eastern-conference" in title_slug:
        return "eastern_conference"
    if "western-conference-finals" in title_slug or "western-conference" in title_slug:
        return "western_conference"
    if "division" in title_slug:
        return "division"
    if "championship" in title_slug or "finals" in title_slug:
        return "championship"
    return None


def _sportsbook_outright_context(event: SportsbookEvent) -> str | None:
    text = " ".join(
        str(value or "")
        for value in (
            event.event_name,
            event.league,
            (event.extra or {}).get("raw_event", {}).get("sport_key") if isinstance(event.extra, dict) else "",
        )
    )
    text_slug = slugify(text)
    if "world-cup" in text_slug or "fifa" in text_slug:
        return "world_cup"
    if "eastern-conference" in text_slug or "east-conference" in text_slug:
        return "eastern_conference"
    if "western-conference" in text_slug or "west-conference" in text_slug:
        return "western_conference"
    if "division" in text_slug:
        return "division"
    award = _award_context(text_slug)
    if award:
        return award
    if "championship-winner" in text_slug or "championship" in text_slug or "winner" in text_slug:
        return "championship"
    return None


def _award_context(text_slug: str) -> str | None:
    if "rookie-of-the-year" in text_slug or "rookie" in text_slug:
        return "rookie_of_the_year"
    if "defensive-player-of-the-year" in text_slug or "defensive" in text_slug:
        return "defensive_player_of_the_year"
    if "coach-of-the-year" in text_slug or "coach" in text_slug:
        return "coach_of_the_year"
    if "cy-young" in text_slug:
        return "cy_young"
    if "mvp" in text_slug or "most-valuable-player" in text_slug:
        return "mvp"
    return None


def _outright_contexts_compatible(market_context: str, event_context: str) -> bool:
    if market_context == event_context:
        return True
    if market_context == "world_cup" and event_context == "championship":
        return False
    if market_context in {"eastern_conference", "western_conference", "division"}:
        return False
    return False


def _league_similarity(left: str | None, right: str | None) -> float:
    left_slug = slugify(str(left or ""))
    right_slug = slugify(str(right or ""))
    if not left_slug or not right_slug:
        return 0.35
    if left_slug == right_slug:
        return 1.0
    if left_slug in right_slug or right_slug in left_slug:
        return 0.80
    return SequenceMatcher(None, left_slug, right_slug).ratio()


def _strip_leading_article(value: str) -> str:
    stripped = value.strip()
    return stripped[4:].strip() if stripped.lower().startswith("the ") else stripped


def _build_explanation_json(
    *,
    market: Market,
    prediction_snapshot: PredictionMarketSnapshot,
    event_match: EventMatch,
    bookmaker_probabilities: list[dict[str, Any]],
    fair_probability: float,
    consensus_dispersion_value: float,
    prediction_inputs: PredictionProbabilityInputs,
    edge,
) -> dict[str, Any]:
    h2h_info = _h2h_info_for_match(market, event_match.event) if getattr(event_match.event, "home_team", None) or getattr(event_match.event, "away_team", None) else {}
    return {
        "selected_bookmakers": [book["bookmaker"] for book in bookmaker_probabilities],
        "bookmakers": bookmaker_probabilities,
        "matched_event": {
            "event_id": getattr(event_match.event, "id", None),
            "event_name": getattr(event_match.event, "event_name", None),
            "home_team": getattr(event_match.event, "home_team", None),
            "away_team": getattr(event_match.event, "away_team", None),
            "target_team": h2h_info.get("target_team"),
            "opponent": h2h_info.get("opponent"),
            "normalized_event_key": event_match.normalized_event_key,
            "confidence_score": event_match.confidence_score,
            "league_score": event_match.league_score,
            "team_score": event_match.team_score,
            "date_score": event_match.date_score,
            "fuzzy_score": event_match.fuzzy_score,
            "match_type": event_match.match_type,
            "reason": event_match.reason,
            "inferred_market_normalized_event_key": event_match.inferred_market_normalized_event_key,
        },
        "consensus_fair_probability": fair_probability,
        "consensus_dispersion": consensus_dispersion_value,
        "market_probability": {
            "value": edge.market_probability,
            "source": edge.market_probability_source,
            "orientation": prediction_inputs.orientation,
            "display_outcome": prediction_inputs.display_outcome,
            "bid_probability": prediction_inputs.bid_probability,
            "ask_probability": prediction_inputs.ask_probability,
            "last_price": prediction_inputs.last_price,
            "raw_bid_probability": prediction_inputs.raw_bid_probability,
            "raw_ask_probability": prediction_inputs.raw_ask_probability,
            "raw_last_price": prediction_inputs.raw_last_price,
        },
        "gross_edge": edge.gross_edge,
        "penalties": {
            "spread": edge.spread,
            "spread_penalty": edge.spread_penalty,
            "liquidity": prediction_snapshot.liquidity,
            "liquidity_penalty": edge.liquidity_penalty,
        },
        "net_edge": edge.net_edge,
        "confidence_score": edge.confidence_score,
        "market": {
            "market_id": market.id,
            "event_name": market.event_name,
            "selection": market.selection,
            "raw_selection": market.selection,
            "display_outcome": prediction_inputs.display_outcome,
            "normalized_event_key": market.normalized_event_key,
        },
    }


if __name__ == "__main__":
    main()
