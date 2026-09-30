"""Tests for morning_briefing._is_fx_market_closed and the
scheduler-tuple change that adds NY at 12:30 UTC.

The gate's semantics: FX is closed Saturday all day + Sunday before
21:00 UTC (FX reopens Sunday 22:00 UTC; the 21:00 cutoff gives a
1-hour pre-open buffer).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import morning_briefing as mb


# ────────────────────────────────────────────────────────────────────────
# _is_fx_market_closed truth table
# ────────────────────────────────────────────────────────────────────────

# Use 2026-05-09 (Saturday) and 2026-05-10 (Sunday) as anchor days.
# 2026-05-08 = Friday, 2026-05-11 = Monday.

@pytest.mark.parametrize("when, closed", [
    # Saturday — closed all day
    (datetime(2026, 5, 9,  0,  0, tzinfo=timezone.utc), True),
    (datetime(2026, 5, 9, 12,  0, tzinfo=timezone.utc), True),
    (datetime(2026, 5, 9, 23, 59, tzinfo=timezone.utc), True),
    # Sunday before 21:00 UTC — closed
    (datetime(2026, 5, 10, 0,  0, tzinfo=timezone.utc), True),
    (datetime(2026, 5, 10, 12, 30, tzinfo=timezone.utc), True),
    (datetime(2026, 5, 10, 20, 59, tzinfo=timezone.utc), True),
    # Sunday 21:00 onward — open (1-hour pre-reopen buffer ends)
    (datetime(2026, 5, 10, 21, 0,  tzinfo=timezone.utc), False),
    (datetime(2026, 5, 10, 22, 0,  tzinfo=timezone.utc), False),
    (datetime(2026, 5, 10, 23, 59, tzinfo=timezone.utc), False),
    # Monday — open
    (datetime(2026, 5, 11, 0,  0,  tzinfo=timezone.utc), False),
    (datetime(2026, 5, 11, 5,  30, tzinfo=timezone.utc), False),
    (datetime(2026, 5, 11, 12, 30, tzinfo=timezone.utc), False),
    # Friday late — open
    (datetime(2026, 5, 8, 23, 59, tzinfo=timezone.utc), False),
])
def test_fx_market_closed_truth_table(when, closed):
    assert mb._is_fx_market_closed(when) is closed


def test_fx_market_closed_uses_now_when_no_arg(monkeypatch):
    """No-arg form delegates to datetime.now(timezone.utc)."""
    fake = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)  # Saturday

    class _DT:
        @staticmethod
        def now(tz=None):
            return fake

    monkeypatch.setattr(mb, "datetime", _DT)
    assert mb._is_fx_market_closed() is True


# ────────────────────────────────────────────────────────────────────────
# Scheduled fires must respect the gate
# ────────────────────────────────────────────────────────────────────────

def test_friday_london_open_briefing_fires():
    """Friday 05:30 UTC — London should fire."""
    fri_0530 = datetime(2026, 5, 8, 5, 30, tzinfo=timezone.utc)
    assert mb._is_fx_market_closed(fri_0530) is False


def test_friday_ny_briefing_fires():
    """Friday 12:30 UTC — NY should fire (newly added entry)."""
    fri_1230 = datetime(2026, 5, 8, 12, 30, tzinfo=timezone.utc)
    assert mb._is_fx_market_closed(fri_1230) is False


def test_saturday_london_briefing_blocked():
    """Saturday 05:30 UTC — gate must block London."""
    sat_0530 = datetime(2026, 5, 9, 5, 30, tzinfo=timezone.utc)
    assert mb._is_fx_market_closed(sat_0530) is True


def test_sunday_ny_briefing_blocked():
    """Sunday 12:30 UTC — gate must block NY."""
    sun_1230 = datetime(2026, 5, 10, 12, 30, tzinfo=timezone.utc)
    assert mb._is_fx_market_closed(sun_1230) is True


def test_monday_both_briefings_fire():
    """Monday 05:30 + 12:30 UTC — both must fire."""
    mon_0530 = datetime(2026, 5, 11, 5, 30, tzinfo=timezone.utc)
    mon_1230 = datetime(2026, 5, 11, 12, 30, tzinfo=timezone.utc)
    assert mb._is_fx_market_closed(mon_0530) is False
    assert mb._is_fx_market_closed(mon_1230) is False


# ────────────────────────────────────────────────────────────────────────
# NY scheduler tuples
# ────────────────────────────────────────────────────────────────────────

def test_sessions_include_london_and_ny():
    """v4 scheduler tuples must include London 05:30 + NY 12:30."""
    assert (5, 30, "London") in mb._SESSIONS_GMT
    assert (12, 30, "NY") in mb._SESSIONS_GMT
    assert (5, 30, "London") in mb._SESSIONS_BST
    assert (12, 30, "NY") in mb._SESSIONS_BST


def test_v5_sessions_include_london_and_ny():
    """v5 schedule unchanged — London 05:30 + NY 12:30."""
    assert (5, 30, "London") in mb._SESSIONS_V5
    assert (12, 30, "NY") in mb._SESSIONS_V5


# ────────────────────────────────────────────────────────────────────────
# Email gate (defense in depth)
# ────────────────────────────────────────────────────────────────────────

def test_email_gate_skips_on_weekend(monkeypatch):
    """briefing_emailer.send_briefing_email returns early when the
    weekend helper says markets are closed."""
    import briefing_emailer

    monkeypatch.setattr(briefing_emailer, "_is_configured", lambda: True)
    monkeypatch.setattr(mb, "_is_fx_market_closed", lambda now=None: True)

    sent = []
    monkeypatch.setattr(briefing_emailer, "_send",
                        lambda subject, body: sent.append((subject, body)))
    monkeypatch.setattr("read_briefing.format_briefings",
                        lambda session=None, date=None: "body")

    briefing_emailer.send_briefing_email("London", date="2026-05-09")
    assert sent == []


def test_email_gate_lets_weekday_through(monkeypatch):
    """Sanity check: weekday email path is not blocked by the gate."""
    import briefing_emailer

    monkeypatch.setattr(briefing_emailer, "_is_configured", lambda: True)
    monkeypatch.setattr(mb, "_is_fx_market_closed", lambda now=None: False)

    sent = []
    monkeypatch.setattr(briefing_emailer, "_send",
                        lambda subject, body: sent.append((subject, body)))
    monkeypatch.setattr("read_briefing.format_briefings",
                        lambda session=None, date=None: "body")

    briefing_emailer.send_briefing_email("NY", date="2026-05-08")
    assert len(sent) == 1
    assert sent[0][0] == "FX Morning Briefing — NY Fri 08 May 2026"
