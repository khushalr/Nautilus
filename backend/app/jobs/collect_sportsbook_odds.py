from __future__ import annotations

import asyncio
import logging

from app.core.db import SessionLocal
from app.services.collectors.odds_api import OddsApiCollector

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    collector = OddsApiCollector()
    result = await collector.collect()
    with SessionLocal() as db:
        saved = collector.persist(db, result)
    logger.info("Stored %s sportsbook odds snapshots", saved.snapshots_saved)


if __name__ == "__main__":
    asyncio.run(main())
