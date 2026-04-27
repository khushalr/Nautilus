from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.models import AlertRule, FairValueSnapshot, Market

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertDeliveryResult:
    ok: bool
    status: str
    error: str | None = None


class AlertDeliveryChannel:
    def send(self, rule: AlertRule, market: Market, fair_value: FairValueSnapshot, market_url: str) -> AlertDeliveryResult:
        raise NotImplementedError


class DiscordWebhookDelivery(AlertDeliveryChannel):
    def send(self, rule: AlertRule, market: Market, fair_value: FairValueSnapshot, market_url: str) -> AlertDeliveryResult:
        if not rule.delivery_target:
            return AlertDeliveryResult(ok=False, status="failed", error="Discord delivery target is empty")

        payload = {
            "username": "Nautilus",
            "embeds": [
                {
                    "title": f"{market.event_name} | {market.selection}",
                    "url": market_url,
                    "description": f"Alert rule: {rule.name}",
                    "color": 3593113,
                    "fields": [
                        {"name": "Market probability", "value": _pct(fair_value.market_probability), "inline": True},
                        {"name": "Fair probability", "value": _pct(fair_value.fair_probability), "inline": True},
                        {"name": "Net edge", "value": _signed_pct(fair_value.net_edge), "inline": True},
                        {"name": "Spread", "value": _pct(fair_value.spread), "inline": True},
                        {"name": "Liquidity", "value": _liquidity(fair_value.liquidity), "inline": True},
                        {"name": "Confidence", "value": _pct(fair_value.confidence_score), "inline": True},
                    ],
                }
            ],
        }

        try:
            response = httpx.post(rule.delivery_target, json=payload, timeout=15)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Discord alert delivery failed for rule %s: %s", rule.id, exc)
            return AlertDeliveryResult(ok=False, status="failed", error=str(exc))

        return AlertDeliveryResult(ok=True, status="sent")


class EmailDelivery(AlertDeliveryChannel):
    def send(self, rule: AlertRule, market: Market, fair_value: FairValueSnapshot, market_url: str) -> AlertDeliveryResult:
        logger.info(
            "Email alert placeholder for %s -> %s: %s",
            rule.name,
            rule.delivery_target,
            market_url,
        )
        return AlertDeliveryResult(ok=False, status="not_implemented", error="Email delivery is a placeholder")


def delivery_channel_for(rule: AlertRule) -> AlertDeliveryChannel:
    if rule.delivery_channel == "email":
        return EmailDelivery()
    return DiscordWebhookDelivery()


def alert_payload(rule: AlertRule, market: Market, fair_value: FairValueSnapshot, market_url: str) -> dict:
    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "market_id": market.id,
        "market_title": market.event_name,
        "selection": market.selection,
        "market_probability": fair_value.market_probability,
        "fair_probability": fair_value.fair_probability,
        "net_edge": fair_value.net_edge,
        "spread": fair_value.spread,
        "liquidity": fair_value.liquidity,
        "confidence": fair_value.confidence_score,
        "market_url": market_url,
    }


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _signed_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.1f}%"


def _liquidity(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.0f}"
