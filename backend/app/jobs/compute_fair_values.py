from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import desc, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import FairValueSnapshot, Market, PredictionMarketSnapshot, SportsbookEvent, SportsbookOddsSnapshot
from app.services.fair_value import (
    EdgeInputs,
    calculate_edge,
    consensus_dispersion,
    remove_vig_two_way,
    weighted_consensus_fair_probability,
)
from app.services.normalization import (
    EventMatch,
    match_prediction_market_to_sportsbook_events,
    normalize_team_name,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    assumptions = settings.default_user_model
    computed = 0
    skipped = 0

    with SessionLocal() as db:
        events = list(db.scalars(select(SportsbookEvent)))
        markets = list(db.scalars(select(Market).where(Market.status == "open")))
        for market in markets:
            snapshot = _latest_prediction_snapshot(db, market.id)
            if snapshot is None:
                skipped += 1
                continue

            match = match_prediction_market_to_sportsbook_events(market, events)
            if match is None:
                skipped += 1
                continue

            bookmaker_probabilities = _bookmaker_no_vig_probabilities(db, market, match.event, assumptions)
            if not bookmaker_probabilities:
                skipped += 1
                continue

            probabilities = [book["no_vig_probability"] for book in bookmaker_probabilities]
            weights = [book["weight"] for book in bookmaker_probabilities]
            fair_probability = weighted_consensus_fair_probability(probabilities, weights)
            dispersion = consensus_dispersion(probabilities)
            edge = calculate_edge(
                EdgeInputs(
                    fair_probability=fair_probability,
                    bid_probability=snapshot.bid_probability,
                    ask_probability=snapshot.ask_probability,
                    last_price=snapshot.last_price,
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


def _latest_prediction_snapshot(db, market_id: str) -> PredictionMarketSnapshot | None:
    return db.scalar(
        select(PredictionMarketSnapshot)
        .where(PredictionMarketSnapshot.market_id == market_id)
        .order_by(desc(PredictionMarketSnapshot.observed_at))
        .limit(1)
    )


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
        selected_line = _selected_line_for_market(market, latest_by_selection)
        if selected_line is None or len(latest_by_selection) < 2:
            continue

        selected_key = normalize_team_name(selected_line.selection)
        opposing_probability = sum(
            line.implied_probability
            for key, line in latest_by_selection.items()
            if key != selected_key
        )
        if opposing_probability <= 0:
            continue

        no_vig_probability, no_vig_opposing_probability = remove_vig_two_way(
            selected_line.implied_probability,
            opposing_probability,
        )
        weight = float(weights.get(bookmaker, 1.0)) if isinstance(weights, dict) else 1.0
        probabilities.append(
            {
                "bookmaker": bookmaker,
                "selection": selected_line.selection,
                "weight": weight,
                "original_odds": {
                    "american": selected_line.american_odds,
                    "decimal": selected_line.decimal_odds,
                },
                "implied_probability": selected_line.implied_probability,
                "opposing_implied_probability": opposing_probability,
                "no_vig_probability": no_vig_probability,
                "opposing_no_vig_probability": no_vig_opposing_probability,
                "observed_at": selected_line.observed_at.isoformat(),
            }
        )

    return probabilities


def _latest_lines_by_selection(lines: list[SportsbookOddsSnapshot]) -> dict[str, SportsbookOddsSnapshot]:
    latest_by_selection: dict[str, SportsbookOddsSnapshot] = {}
    for line in lines:
        key = normalize_team_name(line.selection)
        if key not in latest_by_selection:
            latest_by_selection[key] = line
    return latest_by_selection


def _selected_line_for_market(
    market: Market,
    latest_by_selection: dict[str, SportsbookOddsSnapshot],
) -> SportsbookOddsSnapshot | None:
    target_selection = normalize_team_name(market.selection)
    if target_selection in latest_by_selection:
        return latest_by_selection[target_selection]

    event_text = f"{market.event_name} {market.selection}".lower()
    for line in latest_by_selection.values():
        if line.selection.lower() in event_text:
            return line

    if market.selection.lower() in {"yes", "no"} and latest_by_selection:
        return next(iter(latest_by_selection.values()))

    return None


def _build_explanation_json(
    *,
    market: Market,
    prediction_snapshot: PredictionMarketSnapshot,
    event_match: EventMatch,
    bookmaker_probabilities: list[dict[str, Any]],
    fair_probability: float,
    consensus_dispersion_value: float,
    edge,
) -> dict[str, Any]:
    return {
        "selected_bookmakers": [book["bookmaker"] for book in bookmaker_probabilities],
        "bookmakers": bookmaker_probabilities,
        "matched_event": {
            "event_id": getattr(event_match.event, "id", None),
            "event_name": getattr(event_match.event, "event_name", None),
            "normalized_event_key": event_match.normalized_event_key,
            "confidence_score": event_match.confidence_score,
            "league_score": event_match.league_score,
            "team_score": event_match.team_score,
            "date_score": event_match.date_score,
            "fuzzy_score": event_match.fuzzy_score,
        },
        "consensus_fair_probability": fair_probability,
        "consensus_dispersion": consensus_dispersion_value,
        "market_probability": {
            "value": edge.market_probability,
            "source": edge.market_probability_source,
            "bid_probability": prediction_snapshot.bid_probability,
            "ask_probability": prediction_snapshot.ask_probability,
            "last_price": prediction_snapshot.last_price,
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
            "normalized_event_key": market.normalized_event_key,
        },
    }


if __name__ == "__main__":
    main()
