"""Thin v5-internal HTTP wrapper around Anthropic /v1/messages.

Reuses ANTHROPIC_API_KEY + ANTHROPIC_URL from morning_briefing — does NOT
introduce a new SDK or instantiate a separate client. The morning_briefing
v4 code path keeps using its inline requests.post block; this helper
exists so the rationale writer can make a different call (different
prompt, model, temperature, max_tokens) without copy-pasting auth/URL.

No retries. The caller decides whether to retry — Phase-2 spec is "no
retries on rationale-write failure, fail loud, return None."
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from morning_briefing import ANTHROPIC_API_KEY, ANTHROPIC_URL

logger = logging.getLogger(__name__)


def call_messages(
    *,
    system: str,
    user: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int = 60,
) -> Optional[str]:
    """Single Anthropic /v1/messages POST. Returns the response text or
    None on any failure (HTTP error, timeout, parse error, missing API
    key). Logs the failure in detail; does not raise.

    The response shape we care about is body["content"][0]["text"] —
    same shape morning_briefing._call_anthropic_once parses.
    """
    if not ANTHROPIC_API_KEY:
        logger.error(
            "[v5_pia.anthropic_client] ANTHROPIC_API_KEY not set — "
            "cannot call /v1/messages"
        )
        return None

    payload = {
        "model":       model,
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "system":      system,
        "messages":    [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }

    try:
        resp = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        text = body["content"][0]["text"]
    except requests.exceptions.HTTPError as exc:
        try:
            err_body = exc.response.text[:1000]
        except Exception:
            err_body = "(could not read response body)"
        logger.error(
            "[v5_pia.anthropic_client] HTTP error: %s | response_body=%s",
            exc, err_body,
        )
        return None
    except requests.exceptions.Timeout:
        logger.error(
            "[v5_pia.anthropic_client] /v1/messages timed out after %ds", timeout,
        )
        return None
    except (KeyError, IndexError, ValueError) as exc:
        # JSON parse error or unexpected shape.
        logger.error("[v5_pia.anthropic_client] response parse failed: %s", exc)
        return None
    except Exception as exc:
        logger.error("[v5_pia.anthropic_client] unexpected error: %s", exc, exc_info=True)
        return None

    return str(text).strip() if text is not None else None
