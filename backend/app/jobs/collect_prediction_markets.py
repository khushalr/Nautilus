from __future__ import annotations

import asyncio
import logging
from collections import Counter

from app.core.db import SessionLocal
from app.services.collectors.kalshi import KalshiCollector
from app.services.collectors.polymarket import PolymarketCollector

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    collectors = [PolymarketCollector(), KalshiCollector()]
    results = []
    for collector in collectors:
        result = await collector.collect()
        results.append((collector, result))
        _log_collection_debug(collector.source_name, result.prediction_markets)

    with SessionLocal() as db:
        total_snapshots = 0
        for collector, result in results:
            if not result.prediction_markets:
                continue
            saved = collector.persist(db, result)
            total_snapshots += saved.snapshots_saved
    logger.info("Stored %s prediction-market snapshots", total_snapshots)


def _log_collection_debug(source: str, markets: list) -> None:
    if not markets:
        logger.info("%s collection debug: no prediction markets collected", source)
        return
    by_type = Counter(market.market_type for market in markets)
    by_league = Counter(market.league or "unknown" for market in markets)
    missing_start_time = sum(1 for market in markets if market.start_time is None)
    skipped_samples = [
        market.event_name
        for market in markets
        if market.market_type in {"futures", "awards"}
    ][:5]
    logger.info("%s markets by market_type: %s", source, dict(sorted(by_type.items())))
    logger.info("%s markets by league: %s", source, dict(by_league.most_common(12)))
    logger.info("%s markets missing start_time: %s", source, missing_start_time)
    if skipped_samples:
        logger.info("%s sample skipped futures/awards: %s", source, skipped_samples)


if __name__ == "__main__":
    asyncio.run(main())
