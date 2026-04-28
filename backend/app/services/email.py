from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import Settings

logger = logging.getLogger(__name__)


def send_email(settings: Settings, *, subject: str, body: str) -> bool:
    if not settings.smtp_host or not settings.alert_email_from or not settings.alert_email_to:
        logger.info("Skipping email notification: SMTP_HOST, ALERT_EMAIL_FROM, or ALERT_EMAIL_TO is not configured.")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.alert_email_from
    message["To"] = settings.alert_email_to
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        logger.warning("Failed to send email notification: %s", exc)
        return False
    return True
