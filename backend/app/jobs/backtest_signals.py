from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select

from app.api.routes import _aggregate_rows
from app.core.db import SessionLocal
from app.models import (
    BacktestSweepResult,
    HistoricalPredictionMarketPriceSnapshot,
    HistoricalSportsbookOddsSnapshot,
    Market,
    PaperTradeSignal,
    SignalBacktestResult,
)
from app.services.backtesting import (
    DEFAULT_BACKTEST_CONFIG,
    detect_signal,
    evaluate_signal_horizons,
    persist_signal_results,
    reconstruct_historical_edge,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


SWEEP_MIN_ABS_EDGES = (0.001, 0.005, 0.01)
SWEEP_MIN_CONFIDENCE_SCORES = (0.60, 0.65, 0.75)
SWEEP_MIN_MATCH_CONFIDENCES = (0.85, 0.90)
SWEEP_SIMULATE_NEGATIVE = (False, True)
SWEEP_CSV_FIELDS = (
    "run_id",
    "min_abs_edge",
    "min_confidence_score",
    "min_match_confidence",
    "simulate_negative_edge",
    "signals_created",
    "evaluated_yes_side",
    "evaluated_no_side",
    "directional_accuracy",
    "average_paper_pnl_per_contract",
    "average_return_on_stake",
    "edge_close_rate",
    "market_driven_close_rate",
    "fair_value_driven_close_rate",
    "suspicious_invalid_count",
)


def main() -> None:
    args = _parse_args()
    config = {
        **DEFAULT_BACKTEST_CONFIG,
        "min_abs_edge": args.min_abs_edge,
        "min_confidence_score": args.min_confidence_score,
        "min_liquidity": args.min_liquidity,
        "min_match_confidence": args.min_match_confidence,
        "simulate_negative_edge": args.simulate_negative_edge,
        "allow_missing_liquidity": args.allow_missing_liquidity,
        "price_tolerance_minutes": args.price_tolerance_minutes,
        "odds_tolerance_minutes": args.odds_tolerance_minutes,
        "exit_price_tolerance_minutes": args.exit_price_tolerance_minutes,
        "allow_missing_future_fair": args.allow_missing_future_fair,
    }
    if args.allow_missing_liquidity:
        logger.warning(
            "Research mode enabled: some historical signals may be evaluated without historical liquidity "
            "and may not represent executable size."
        )
    with SessionLocal() as db:
        if args.debug_market_id:
            _debug_market(db, args.debug_market_id, config)
            return
        if args.sweep_thresholds:
            _run_threshold_sweep(db, args, config)
            return
        if args.clear_existing and not args.dry_run:
            db.execute(delete(SignalBacktestResult))
            db.execute(delete(PaperTradeSignal))
            db.commit()
        elif args.clear_existing and args.dry_run:
            logger.info("Dry run enabled; existing signal rows were not cleared.")
        timestamps = _candidate_timestamps(db, args.market_id, args.limit)
        created = 0
        skips: dict[str, int] = {}
        verbose_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        horizon_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        summary = {
            "total_historical_polymarket_prices_considered": len(timestamps),
            "total_historical_sportsbook_snapshots_considered": _sportsbook_snapshot_count(db),
            "candidate_pairs_created": 0,
            "candidates_passing_timestamp_tolerance": 0,
            "candidates_passing_match_confidence": 0,
            "candidates_passing_liquidity": 0,
            "candidates_passing_edge_threshold": 0,
            "signals_created": 0,
        }
        for market_id, timestamp in timestamps:
            market = db.get(Market, market_id)
            if market is None:
                continue
            summary["candidate_pairs_created"] += 1
            edge = reconstruct_historical_edge(db, market, timestamp, config=config)
            if edge.skip_reason not in {"no_historical_polymarket_price", "no_historical_sportsbook_odds"}:
                summary["candidates_passing_timestamp_tolerance"] += 1
            if edge.match_confidence >= float(config["min_match_confidence"]):
                summary["candidates_passing_match_confidence"] += 1
            if edge.skip_reason:
                skips[edge.skip_reason] = skips.get(edge.skip_reason, 0) + 1
                _record_verbose_example(verbose_examples, edge.skip_reason, market, timestamp, edge)
                continue
            if _passes_liquidity(edge, config):
                summary["candidates_passing_liquidity"] += 1
            if abs(edge.net_edge) >= float(config["min_abs_edge"]):
                summary["candidates_passing_edge_threshold"] += 1
            direction = detect_signal(edge, config=config)
            if direction is None:
                reason = _threshold_skip(edge, config)
                skips[reason] = skips.get(reason, 0) + 1
                _record_verbose_example(verbose_examples, reason, market, timestamp, edge)
                continue
            evaluations = evaluate_signal_horizons(db, edge, direction, config=config)
            _record_horizon_stats(horizon_stats, evaluations)
            if not args.dry_run:
                persist_signal_results(db, edge, direction, config=config, evaluations=evaluations)
            created += 1
        summary["signals_created"] = created
        if not args.dry_run:
            db.commit()
    logger.info("%s %s historical paper-trade signals", "Would create" if args.dry_run else "Created", created)
    logger.info(
        "Backtest summary: %s",
        ", ".join(f"{key}={value}" for key, value in summary.items()),
    )
    if skips:
        logger.info("Backtest skip breakdown: %s", ", ".join(f"{key}={value}" for key, value in sorted(skips.items())))
    if horizon_stats:
        for horizon, stats in sorted(horizon_stats.items()):
            skip_parts = [
                f"{key}={value}"
                for key, value in sorted(stats.items())
                if key.startswith("skip_") and value
            ]
            logger.info(
                "Horizon %s: entry_signals=%s, future_price_found=%s, missing_future_price=%s, "
                "future_sportsbook_fair_found=%s, evaluated=%s, skip_reasons={%s}",
                horizon,
                stats.get("entry_signals", 0),
                stats.get("future_price_found", 0),
                stats.get("missing_future_price", 0),
                stats.get("future_sportsbook_fair_found", 0),
                stats.get("evaluated", 0),
                ", ".join(skip_parts) if skip_parts else "none",
            )
    if args.verbose and verbose_examples:
        for reason, examples in sorted(verbose_examples.items()):
            logger.info("Verbose skip examples for %s:", reason)
            for example in examples:
                logger.info("  %s", example)


def _run_threshold_sweep(db, args, base_config: dict[str, Any]) -> None:
    timestamps = _candidate_timestamps(db, args.market_id, args.limit)
    run_id = str(uuid4())
    rows: list[dict[str, Any]] = []
    logger.info(
        "Running threshold sweep over %s candidate timestamps and %s sportsbook snapshots.",
        len(timestamps),
        _sportsbook_snapshot_count(db),
    )
    for min_abs_edge, min_confidence, min_match_confidence, simulate_negative in product(
        SWEEP_MIN_ABS_EDGES,
        SWEEP_MIN_CONFIDENCE_SCORES,
        SWEEP_MIN_MATCH_CONFIDENCES,
        SWEEP_SIMULATE_NEGATIVE,
    ):
        config = {
            **base_config,
            "min_abs_edge": min_abs_edge,
            "min_confidence_score": min_confidence,
            "min_match_confidence": min_match_confidence,
            "simulate_negative_edge": simulate_negative,
        }
        result = _evaluate_sweep_combination(db, timestamps, config=config)
        row = {
            "run_id": run_id,
            "min_abs_edge": min_abs_edge,
            "min_confidence_score": min_confidence,
            "min_match_confidence": min_match_confidence,
            "simulate_negative_edge": simulate_negative,
            **result,
        }
        rows.append(row)
        logger.info(
            "Sweep edge=%s confidence=%s match=%s simulate_negative=%s: signals=%s yes_eval=%s no_eval=%s "
            "direction=%s avg_pnl=%s avg_return=%s edge_close=%s market_close=%s fair_close=%s suspicious=%s",
            min_abs_edge,
            min_confidence,
            min_match_confidence,
            simulate_negative,
            row["signals_created"],
            row["evaluated_yes_side"],
            row["evaluated_no_side"],
            _format_metric(row["directional_accuracy"]),
            _format_metric(row["average_paper_pnl_per_contract"]),
            _format_metric(row["average_return_on_stake"]),
            _format_metric(row["edge_close_rate"]),
            _format_metric(row["market_driven_close_rate"]),
            _format_metric(row["fair_value_driven_close_rate"]),
            row["suspicious_invalid_count"],
        )
    if args.sweep_output:
        _write_sweep_csv(Path(args.sweep_output), rows)
        logger.info("Wrote threshold sweep CSV to %s", args.sweep_output)
    if not args.dry_run:
        _persist_sweep_rows(db, rows)
        db.commit()
        logger.info("Stored %s threshold sweep rows with run_id=%s", len(rows), run_id)
    else:
        logger.info("Dry run enabled; threshold sweep rows were not stored.")


def _evaluate_sweep_combination(db, timestamps: list[tuple[str, datetime]], *, config: dict[str, Any]) -> dict[str, Any]:
    performance_rows: list[dict[str, Any]] = []
    signal_count = 0
    suspicious_invalid_count = 0
    for index, (market_id, timestamp) in enumerate(timestamps):
        market = db.get(Market, market_id)
        if market is None:
            continue
        edge = reconstruct_historical_edge(db, market, timestamp, config=config)
        if edge.skip_reason:
            if edge.skip_reason in {"suspicious_probability_orientation", "invalid_probability_range"}:
                suspicious_invalid_count += 1
            continue
        direction = detect_signal(edge, config=config)
        if direction is None:
            if _threshold_skip(edge, config) in {"suspicious_probability_orientation", "invalid_probability_range"}:
                suspicious_invalid_count += 1
            continue
        signal_count += 1
        signal_id = f"sweep-{index}"
        evaluations = evaluate_signal_horizons(db, edge, direction, config=config)
        for evaluation in evaluations:
            performance_rows.append(_sweep_performance_row(signal_id, edge, direction, evaluation))
    summary = _aggregate_rows(performance_rows)
    return {
        "signals_created": signal_count,
        "evaluated_yes_side": summary["evaluated_long_yes_signals"],
        "evaluated_no_side": summary["evaluated_negative_edge_signals"],
        "directional_accuracy": summary["directional_accuracy"],
        "average_paper_pnl_per_contract": summary["average_paper_pnl_per_contract"],
        "average_return_on_stake": summary["average_return_on_stake"],
        "edge_close_rate": summary["edge_close_rate"],
        "market_driven_close_rate": summary["market_driven_close_rate"],
        "fair_value_driven_close_rate": summary["fair_value_driven_close_rate"],
        "suspicious_invalid_count": suspicious_invalid_count + summary["suspicious_invalid_signals"],
        "raw_payload": {
            "total_rows": len(performance_rows),
            "evaluated_signals": summary["evaluated_signals"],
            "simulated_long_yes_signals": summary["simulated_long_yes_signals"],
            "simulated_negative_edge_signals": summary["simulated_negative_edge_signals"],
            "tracked_negative_edge_signals": summary["tracked_negative_edge_signals"],
            "edge_widened_rate": summary["edge_widened_rate"],
            "no_meaningful_change_rate": summary["no_meaningful_change_rate"],
        },
    }


def _sweep_performance_row(signal_id: str, edge, direction: str, evaluation) -> dict[str, Any]:
    paper_side = evaluation.paper_side
    category = _sweep_signal_category(direction, evaluation)
    return {
        "signal_id": signal_id,
        "paper_pnl_per_contract": evaluation.paper_pnl_per_contract,
        "did_edge_close": evaluation.did_edge_close,
        "moved_expected_direction": evaluation.moved_expected_direction,
        "entry_net_edge": edge.net_edge,
        "return_on_stake": evaluation.return_on_stake,
        "liquidity_adjusted": edge.liquidity_adjusted,
        "evaluation_status": evaluation.evaluation_status,
        "skip_reason": evaluation.skip_reason,
        "signal_category": category,
        "paper_side": paper_side,
        "closure_reason": evaluation.closure_reason,
        "market_yes_change": evaluation.market_yes_change,
        "sportsbook_fair_change": evaluation.sportsbook_fair_change,
        "edge_change": evaluation.edge_change,
        "absolute_edge_change": evaluation.absolute_edge_change,
    }


def _sweep_signal_category(direction: str, evaluation) -> str:
    if evaluation.evaluation_status in {"suspicious_probability_orientation", "invalid_probability"}:
        return "suspicious_or_invalid"
    if direction == "possible_yes_overpricing":
        if evaluation.paper_side == "NO":
            return "negative_edge_no_side_simulated" if evaluation.paper_pnl_per_contract is not None else "unevaluated_negative_edge_no_side"
        return "negative_edge_overpricing_tracked_only"
    return "positive_edge_long_yes_simulated" if evaluation.paper_pnl_per_contract is not None else "unevaluated_missing_future_price"


def _persist_sweep_rows(db, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        db.add(
            BacktestSweepResult(
                run_id=row["run_id"],
                min_abs_edge=row["min_abs_edge"],
                min_confidence_score=row["min_confidence_score"],
                min_match_confidence=row["min_match_confidence"],
                simulate_negative_edge=row["simulate_negative_edge"],
                signals_created=row["signals_created"],
                evaluated_yes_side=row["evaluated_yes_side"],
                evaluated_no_side=row["evaluated_no_side"],
                directional_accuracy=row["directional_accuracy"],
                average_paper_pnl_per_contract=row["average_paper_pnl_per_contract"],
                average_return_on_stake=row["average_return_on_stake"],
                edge_close_rate=row["edge_close_rate"],
                market_driven_close_rate=row["market_driven_close_rate"],
                fair_value_driven_close_rate=row["fair_value_driven_close_rate"],
                suspicious_invalid_count=row["suspicious_invalid_count"],
                raw_payload=row.get("raw_payload", {}),
            )
        )


def _write_sweep_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SWEEP_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in SWEEP_CSV_FIELDS})


def _format_metric(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _candidate_timestamps(db, market_id: str | None, limit: int) -> list[tuple[str, datetime]]:
    stmt = (
        select(HistoricalPredictionMarketPriceSnapshot.market_id, HistoricalPredictionMarketPriceSnapshot.timestamp)
        .order_by(HistoricalPredictionMarketPriceSnapshot.timestamp.asc())
        .limit(limit)
    )
    if market_id:
        stmt = stmt.where(HistoricalPredictionMarketPriceSnapshot.market_id == market_id)
    return [(str(row[0]), row[1]) for row in db.execute(stmt).all()]


def _threshold_skip(edge, config: dict) -> str:
    if not _probability_in_range(edge.market_yes_probability) or not _probability_in_range(edge.sportsbook_fair_probability):
        return "invalid_probability_range"
    if abs(edge.net_edge) > 0.50:
        return "suspicious_probability_orientation"
    if not _passes_liquidity(edge, config):
        return "insufficient_liquidity"
    if edge.confidence_score < float(config["min_confidence_score"]):
        return "confidence_below_threshold"
    if edge.match_confidence < float(config["min_match_confidence"]):
        return "confidence_below_threshold"
    if abs(edge.net_edge) < float(config["min_abs_edge"]):
        return "edge_below_threshold"
    return "timestamp_out_of_range"


def _passes_liquidity(edge, config: dict) -> bool:
    if edge.liquidity is None or edge.liquidity <= 0:
        return bool(config.get("allow_missing_liquidity", False))
    return edge.liquidity >= float(config["min_liquidity"])


def _sportsbook_snapshot_count(db) -> int:
    return int(db.scalar(select(func.count()).select_from(HistoricalSportsbookOddsSnapshot)) or 0)


def _record_horizon_stats(horizon_stats: dict[str, dict[str, int]], evaluations) -> None:
    for evaluation in evaluations:
        stats = horizon_stats[evaluation.horizon]
        stats["entry_signals"] += 1
        if evaluation.evaluation_status in {"negative_edge_no_long_simulation", "invalid_probability"}:
            stats[f"skip_{evaluation.skip_reason or evaluation.evaluation_status}"] += 1
            continue
        if evaluation.exit_market_yes_probability is None:
            stats["missing_future_price"] += 1
        else:
            stats["future_price_found"] += 1
        if evaluation.exit_sportsbook_fair_probability is not None:
            stats["future_sportsbook_fair_found"] += 1
        if evaluation.paper_pnl_per_contract is not None:
            stats["evaluated"] += 1
        else:
            stats[f"skip_{evaluation.skip_reason or evaluation.evaluation_status}"] += 1


def _probability_in_range(value: float | None) -> bool:
    return value is not None and 0 <= value <= 1


def _record_verbose_example(
    examples: dict[str, list[dict[str, Any]]],
    reason: str,
    market: Market,
    timestamp: datetime,
    edge,
    *,
    limit: int = 3,
) -> None:
    if len(examples[reason]) >= limit:
        return
    examples[reason].append(_verbose_skip_row(market, timestamp, edge, reason))


def _verbose_skip_row(market: Market, timestamp: datetime, edge, reason: str) -> dict[str, Any]:
    liquidity = getattr(edge, "liquidity", None)
    return {
        "market_title": market.event_name,
        "market_id": str(market.id),
        "external_id": market.external_id,
        "timestamp": timestamp.isoformat(),
        "market_type": market.market_type,
        "league": market.league,
        "display_outcome": getattr(edge, "display_outcome", None),
        "token_id": _edge_price_payload(edge).get("token_id"),
        "raw_outcome_side": getattr(edge, "raw_prediction_side", None),
        "raw_historical_polymarket_price": getattr(edge, "historical_price", None),
        "derived_market_yes_probability": getattr(edge, "market_yes_probability", None),
        "sportsbook_fair_probability": getattr(edge, "sportsbook_fair_probability", None),
        "net_edge": getattr(edge, "net_edge", None),
        "available_sportsbook_event_or_category": getattr(edge, "available_sportsbook_event", None),
        "available_sportsbook_selection": getattr(edge, "available_sportsbook_selection", None),
        "match_confidence": getattr(edge, "match_confidence", None),
        "match_score_components": getattr(edge, "match_score_components", {}),
        "liquidity_value": liquidity,
        "liquidity_status": getattr(edge, "liquidity_status", "missing" if liquidity is None or liquidity <= 0 else "known"),
        "exact_reason_for_skip": getattr(edge, "exact_skip_detail", None) or reason,
    }


def _edge_price_payload(edge) -> dict[str, Any]:
    raw_payload = getattr(edge, "price_raw_payload", None)
    return raw_payload if isinstance(raw_payload, dict) else {}


def _debug_market(db, market_id: str, config: dict[str, Any]) -> None:
    market = db.get(Market, market_id)
    if market is None:
        logger.info("No market found for %s", market_id)
        return
    logger.info("Debug market: title=%s id=%s external_id=%s type=%s league=%s", market.event_name, market.id, market.external_id, market.market_type, market.league)
    prices = list(
        db.scalars(
            select(HistoricalPredictionMarketPriceSnapshot)
            .where(HistoricalPredictionMarketPriceSnapshot.market_id == market_id)
            .order_by(HistoricalPredictionMarketPriceSnapshot.timestamp.asc())
            .limit(10)
        )
    )
    for price in prices:
        edge = reconstruct_historical_edge(db, market, price.timestamp, config=config)
        logger.info(
            "Historical price: ts=%s token_id=%s raw_side=%s raw_price=%s derived_yes=%s sportsbook_fair=%s edge=%s status=%s reason=%s",
            price.timestamp.isoformat(),
            price.token_id,
            price.raw_selection,
            price.raw_price,
            price.market_yes_price,
            edge.sportsbook_fair_probability,
            edge.net_edge,
            edge.skip_reason or "ok",
            edge.exact_skip_detail,
        )


def _parse_args():
    parser = argparse.ArgumentParser(description="Run historical signal paper-trade simulations.")
    parser.add_argument("--market-id")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--min-abs-edge", type=float, default=0.015)
    parser.add_argument("--min-confidence-score", type=float, default=0.85)
    parser.add_argument("--min-liquidity", type=float, default=50000)
    parser.add_argument("--min-match-confidence", type=float, default=0.85)
    parser.add_argument("--price-tolerance-minutes", type=float, default=30)
    parser.add_argument("--odds-tolerance-minutes", type=float, default=60)
    parser.add_argument(
        "--exit-price-tolerance-minutes",
        type=float,
        default=120,
        help="Nearest future Polymarket YES price tolerance for horizon exits. Historical price collection must extend past each horizon.",
    )
    parser.add_argument("--allow-missing-future-fair", action="store_true", default=True)
    parser.add_argument("--simulate-negative-edge", action="store_true")
    parser.add_argument("--allow-missing-liquidity", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--debug-market-id", help="Print historical token orientation and edge reconstruction for one market, then exit.")
    parser.add_argument("--clear-existing", action="store_true")
    parser.add_argument("--sweep-thresholds", action="store_true", help="Evaluate a fixed grid of research thresholds without replacing signal rows.")
    parser.add_argument("--sweep-output", help="Optional CSV path for threshold sweep results.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
