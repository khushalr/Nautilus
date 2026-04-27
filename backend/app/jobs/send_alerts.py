from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AlertDelivery, AlertRule, FairValueSnapshot, Market
from app.services.alerts import alert_payload, delivery_channel_for

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    cooldown = timedelta(minutes=settings.alert_cooldown_minutes)
    public_app_url = settings.public_app_url.rstrip("/")

    with SessionLocal() as db:
        rules = list(db.scalars(select(AlertRule).where(AlertRule.is_active.is_(True))))
        opportunities = _latest_opportunities(db)
        sent = 0
        skipped = 0
        failed = 0

        for rule in rules:
            for market, fair_value in opportunities:
                if not _matches_rule(rule, market, fair_value):
                    continue
                if _recent_duplicate_exists(db, rule.id, market.id, cooldown):
                    skipped += 1
                    continue

                market_url = f"{public_app_url}/markets/{market.id}"
                payload = alert_payload(rule, market, fair_value, market_url)
                result = delivery_channel_for(rule).send(rule, market, fair_value, market_url)
                db.add(
                    AlertDelivery(
                        alert_rule_id=rule.id,
                        market_id=market.id,
                        fair_value_snapshot_id=fair_value.id,
                        delivery_channel=rule.delivery_channel,
                        delivery_target=rule.delivery_target,
                        status=result.status,
                        error=result.error,
                        payload=payload,
                    )
                )
                if result.ok:
                    sent += 1
                    logger.info("Sent alert %s for market %s", rule.name, market.event_name)
                else:
                    failed += 1
                    logger.warning("Alert %s for market %s was not sent: %s", rule.name, market.event_name, result.error)

        db.commit()

    logger.info("Alert job complete: sent=%s skipped_recent=%s failed=%s", sent, skipped, failed)


def _latest_opportunities(db) -> list[tuple[Market, FairValueSnapshot]]:
    ranked = (
        select(
            FairValueSnapshot.id.label("id"),
            func.row_number()
            .over(partition_by=FairValueSnapshot.market_id, order_by=FairValueSnapshot.observed_at.desc())
            .label("rank"),
        )
        .subquery()
    )
    stmt = (
        select(Market, FairValueSnapshot)
        .join(FairValueSnapshot, FairValueSnapshot.market_id == Market.id)
        .join(ranked, ranked.c.id == FairValueSnapshot.id)
        .where(ranked.c.rank == 1)
        .order_by(desc(FairValueSnapshot.net_edge))
    )
    return list(db.execute(stmt).all())


def _matches_rule(rule: AlertRule, market: Market, fair_value: FairValueSnapshot) -> bool:
    if fair_value.net_edge < rule.min_net_edge:
        return False
    if rule.max_spread is not None and (fair_value.spread is None or fair_value.spread > rule.max_spread):
        return False
    if rule.min_liquidity is not None and (fair_value.liquidity is None or fair_value.liquidity < rule.min_liquidity):
        return False
    if rule.league and market.league != rule.league:
        return False
    if rule.source and market.source != rule.source:
        return False
    return True


def _recent_duplicate_exists(db, rule_id: str, market_id: str, cooldown: timedelta) -> bool:
    cutoff = datetime.now(UTC) - cooldown
    existing = db.scalar(
        select(AlertDelivery.id)
        .where(
            AlertDelivery.alert_rule_id == rule_id,
            AlertDelivery.market_id == market_id,
            AlertDelivery.status == "sent",
            AlertDelivery.sent_at >= cutoff,
        )
        .limit(1)
    )
    return existing is not None


if __name__ == "__main__":
    main()
