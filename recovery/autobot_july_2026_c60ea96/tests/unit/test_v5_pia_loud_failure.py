"""Test that briefing.v5_pia.orchestrator.generate_v5_for_session
escalates per-pair failures to ERROR + Telegram + re-raise.

Pre-2026-05-06 it logged WARNING and swallowed; the NY 12:30 fire
that day silently lost all 4 pairs to a permission error.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from briefing.v5_pia import orchestrator


def test_per_pair_failure_logs_error_alerts_and_reraises(caplog):
    sent = []

    def fake_send(msg, parse_mode=None):
        sent.append((msg, parse_mode))

    def fail(*args, **kwargs):
        raise PermissionError("simulated write denied")

    with patch("telegram_alerts.send_telegram_message", side_effect=fake_send), \
         patch.object(orchestrator, "generate_briefing_v5", side_effect=fail):
        with caplog.at_level(logging.ERROR, logger="briefing.v5_pia.orchestrator"):
            with pytest.raises(PermissionError):
                orchestrator.generate_v5_for_session("London", pairs=["GBPUSD"])

    assert len(sent) == 1
    msg, parse_mode = sent[0]
    assert parse_mode == "HTML"
    assert "GBPUSD" in msg
    assert "London" in msg
    assert "PermissionError" in msg
    assert "v5_pia write FAILED" in msg
    assert "FAILED" in caplog.text
    assert "PermissionError" in caplog.text


def test_telegram_failure_does_not_swallow_original_exception(caplog):
    """If telegram itself is broken we still want the ERROR log and
    we still re-raise the original exception — the operator finds
    out via journalctl even when the alert path is down."""

    def fail(*args, **kwargs):
        raise PermissionError("simulated write denied")

    with patch("telegram_alerts.send_telegram_message", side_effect=RuntimeError("tg down")), \
         patch.object(orchestrator, "generate_briefing_v5", side_effect=fail):
        with caplog.at_level(logging.ERROR, logger="briefing.v5_pia.orchestrator"):
            with pytest.raises(PermissionError):
                orchestrator.generate_v5_for_session("NY", pairs=["EURUSD"])

    assert "telegram alert failed" in caplog.text
