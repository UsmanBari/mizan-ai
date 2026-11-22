"""External integrations: Telegram Bot API and email (SMTP, e.g. Gmail app password)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


def send_telegram(chat_id: str, text: str) -> bool:
    s = get_settings()
    if not (s.telegram_bot_token and chat_id):
        return False
    r = httpx.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                   json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML",
                         "disable_web_page_preview": True}, timeout=20)
    if r.status_code != 200:
        log.warning("telegram failed: %s %s", r.status_code, r.text[:200])
    return r.status_code == 200


def send_email(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    if not (s.smtp_user and s.smtp_password and to):
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_user, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)
    return True
