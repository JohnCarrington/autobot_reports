#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
briefing_emailer.py — Send morning briefing as plain-text email via SendGrid Web API.

Configuration via env vars:
    EMAIL_FROM        sender address
    EMAIL_TO          recipient address (comma-separated for multiple)
    SENDGRID_API_KEY  SendGrid API key (Bearer token)

send_briefing_email(session, date) is the only public function.
It never raises — logs a warning on any failure.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

import read_briefing

logger = logging.getLogger("AutoBot")

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

def _cfg(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _is_configured() -> bool:
    """Return True if minimum required env vars are set."""
    return bool(
        _cfg("EMAIL_FROM")
        and _cfg("EMAIL_TO")
        and _cfg("SENDGRID_API_KEY")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def send_briefing_email(session: str, date: Optional[str] = None) -> None:
    """
    Format and send the morning briefing email for the given session and date.

    Parameters
    ----------
    session : "Asian", "London", or "NY"
    date    : "YYYY-MM-DD". Defaults to today UTC.

    Never raises — logs a warning on any failure.
    """
    logger.info(f"[briefing_emailer] send_briefing_email called — session={session} date={date}")

    if not _is_configured():
        logger.warning(
            "[briefing_emailer] SendGrid env vars not configured — skipping email. "
            "Set EMAIL_FROM / EMAIL_TO / SENDGRID_API_KEY in .env to enable."
        )
        return

    # Defense in depth: even if a briefing somehow generated on a
    # weekend (e.g. a future code path bypassed the scheduler gates),
    # never email — markets are closed and the body would be stale.
    from morning_briefing import _is_fx_market_closed
    if _is_fx_market_closed():
        logger.info("[briefing_emailer] Weekend market closure — email skipped")
        return

    logger.info("[briefing_emailer] _is_configured() passed")

    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        dt_label = datetime.strptime(date, "%Y-%m-%d").strftime("%a %d %b %Y")
    except Exception:
        dt_label = date

    subject = f"FX Morning Briefing — {session} {dt_label}"

    try:
        body = read_briefing.format_briefings(session=session, date=date)
    except Exception as exc:
        logger.warning(f"[briefing_emailer] Failed to format briefing body: {exc}")
        return

    if body:
        logger.info(f"[briefing_emailer] Email body populated ({len(body)} chars)")
    else:
        logger.warning("[briefing_emailer] Email body is empty")

    _send(subject=subject, body=body)


def _send(subject: str, body: str) -> None:
    """Post to SendGrid Web API. Logs warning on any error, never raises."""
    from_addr = _cfg("EMAIL_FROM")
    to_raw    = _cfg("EMAIL_TO")
    to_addrs  = [a.strip() for a in to_raw.split(",") if a.strip()]
    api_key   = _cfg("SENDGRID_API_KEY")

    payload = {
        "personalizations": [
            {"to": [{"email": addr} for addr in to_addrs]}
        ],
        "from":    {"email": from_addr},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }

    try:
        resp = requests.post(
            SENDGRID_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=30,
        )

        logger.info(
            f"[briefing_emailer] SendGrid response: status={resp.status_code} "
            f"body={resp.text[:500] if resp.text else '(empty)'}"
        )

        if resp.status_code == 401:
            logger.warning(
                "[briefing_emailer] SendGrid authentication failed (401) — "
                "check SENDGRID_API_KEY"
            )
        elif resp.status_code == 403:
            logger.warning(
                "[briefing_emailer] SendGrid permission denied (403) — "
                "check sender verification and API key scopes"
            )
        elif resp.status_code >= 400:
            logger.warning(
                f"[briefing_emailer] SendGrid API error {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        else:
            logger.info(
                f"[briefing_emailer] Sent '{subject}' → {to_addrs} "
                f"(status {resp.status_code})"
            )

    except requests.exceptions.Timeout:
        logger.warning("[briefing_emailer] SendGrid request timed out after 30s")
    except requests.exceptions.ConnectionError as exc:
        logger.warning(f"[briefing_emailer] SendGrid connection error: {exc}")
    except Exception as exc:
        logger.warning(f"[briefing_emailer] Unexpected error sending briefing: {exc}")
