from __future__ import annotations

import argparse
import logging
from datetime import datetime

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.models import HistoricalPredictionMarketPriceSnapshot, Market, PaperTradeSignal, SignalBacktestResult
from app.services.backtesting import DEFAULT_BACKTEST_CONFIG, detect_signal, persist_signal_results, reconstruct_historical_edge

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    args = _parse_args()
    config = {
        **DEFAULT_BACKTEST_CONFIG,
        "min_abs_edge": args.min_abs_edge,
        "min_confidence_score": args.min_confidence_score,
        "min_liquidity": args.min_liquidity,
        "min_match_confidence": args.min_match_confidence,
        "simulate_negative_edge": args.simulate_negative_edge,
    }
    with SessionLocal() as db:
        if args.clear_existing:
            db.execute(delete(SignalBacktestResult))
            db.execute(delete(PaperTradeSignal))
            db.commit()
        timestamps = _candidate_timestamps(db, args.market_id, args.limit)
        created = 0
        skips: dict[str, int] = {}
        for market_id, timestamp in timestamps:
            market = db.get(Market, market_id)
            if market is None:
                continue
            edge = reconstruct_historical_edge(db, market, timestamp, config=config)
            if edge.skip_reason:
                skips[edge.skip_reason] = skips.get(edge.skip_reason, 0) + 1
                continue
            direction = detect_signal(edge, config=config)
            if direction is None:
                reason = _threshold_skip(edge, config)
                skips[reason] = skips.get(reason, 0) + 1
                continue
            persist_signal_results(db, edge, direction, config=config)
            created += 1
        db.commit()
    logger.info("Created %s historical paper-trade signals", created)
    if skips:
        logger.info("Backtest skip breakdown: %s", ", ".join(f"{key}={value}" for key, value in sorted(skips.items())))


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
    if edge.liquidity is None or edge.liquidity < float(config["min_liquidity"]):
        return "insufficient_liquidity"
    if edge.confidence_score < float(config["min_confidence_score"]):
        return "confidence_below_threshold"
    if edge.match_confidence < float(config["min_match_confidence"]):
        return "confidence_below_threshold"
    if abs(edge.net_edge) < float(config["min_abs_edge"]):
        return "edge_below_threshold"
    return "timestamp_out_of_range"


def _parse_args():
    parser = argparse.ArgumentParser(description="Run historical signal paper-trade simulations.")
    parser.add_argument("--market-id")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--min-abs-edge", type=float, default=0.015)
    parser.add_argument("--min-confidence-score", type=float, default=0.85)
    parser.add_argument("--min-liquidity", type=float, default=50000)
    parser.add_argument("--min-match-confidence", type=float, default=0.85)
    parser.add_argument("--simulate-negative-edge", action="store_true")
    parser.add_argument("--clear-existing", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
