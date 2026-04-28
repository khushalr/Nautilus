from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping

from app.core.config import Settings
from app.services.email import send_email

logger = logging.getLogger(__name__)

API_KEY_PATTERN = re.compile(r"(?i)(apiKey=)[^&\s]+")


@dataclass(frozen=True)
class OddsApiQuota:
    remaining: int | None = None
    used: int | None = None
    last: int | None = None


def parse_quota_headers(headers: Mapping[str, str]) -> OddsApiQuota:
    normalized = {key.lower(): value for key, value in headers.items()}
    return OddsApiQuota(
        remaining=_parse_int(normalized.get("x-requests-remaining")),
        used=_parse_int(normalized.get("x-requests-used")),
        last=_parse_int(normalized.get("x-requests-last")),
    )


def redact_api_key(value: str) -> str:
    return API_KEY_PATTERN.sub(r"\1REDACTED", value)


def should_send_quota_email(
    *,
    state_file: str,
    cooldown_hours: int,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    path = Path(state_file)
    try:
        payload = json.loads(path.read_text()) if path.exists() else {}
        sent_at = datetime.fromisoformat(str(payload.get("last_sent_at")))
    except Exception:
        return True
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    return now - sent_at >= timedelta(hours=cooldown_hours)


def mark_quota_email_sent(*, state_file: str, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_sent_at": now.isoformat()}))


def notify_quota_issue(
    settings: Settings,
    *,
    subject: str,
    body: str,
    send: Callable[[Settings, str, str], bool] | None = None,
) -> bool:
    if not should_send_quota_email(
        state_file=settings.odds_api_quota_state_file,
        cooldown_hours=settings.odds_api_quota_email_cooldown_hours,
    ):
        logger.info("Skipping Odds API quota email: cooldown window is active.")
        return False

    send_fn = send or _send_email_adapter
    sent = send_fn(settings, subject, body)
    if sent:
        mark_quota_email_sent(state_file=settings.odds_api_quota_state_file)
    return sent


def maybe_notify_low_quota(settings: Settings, quota: OddsApiQuota, *, context: str) -> None:
    if quota.remaining is None:
        return
    logger.info(
        "The Odds API quota for %s: remaining=%s used=%s last=%s",
        context,
        quota.remaining,
        quota.used if quota.used is not None else "unknown",
        quota.last if quota.last is not None else "unknown",
    )
    if quota.remaining <= settings.odds_api_low_quota_threshold:
        notify_quota_issue(
            settings,
            subject="Nautilus Odds API low quota warning",
            body=(
                f"The Odds API reports {quota.remaining} requests remaining for {context}. "
                "Nautilus will keep using the latest stored sportsbook odds if collection is unavailable."
            ),
        )


def notify_quota_failure(settings: Settings, *, reason: str, context: str) -> None:
    notify_quota_issue(
        settings,
        subject="Nautilus Odds API quota/rate-limit warning",
        body=(
            f"Sportsbook odds collection hit a quota/rate-limit condition while requesting {context}.\n\n"
            f"Reason: {redact_api_key(reason)}\n\n"
            "The live loop can continue collecting prediction markets and computing fair values from the latest "
            "stored sportsbook odds."
        ),
    )


def _send_email_adapter(settings: Settings, subject: str, body: str) -> bool:
    return send_email(settings, subject=subject, body=body)


def _parse_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
