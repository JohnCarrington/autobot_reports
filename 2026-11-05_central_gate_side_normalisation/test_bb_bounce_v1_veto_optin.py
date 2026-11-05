"""V1-pressure veto is now opt-in (2026-11-05).

The v1-pressure signal remains computed and logged into the decision
row whenever ``BB_BOUNCE_V1_PRESSURE_ENABLED=1`` (so operators retain
AGAINST / WITH / UNKNOWN telemetry), but it only sets
``refusing_rule`` and flips ``outcome=REFUSED`` when the new
``BB_BOUNCE_V1_PRESSURE_VETO_ENABLED=1`` flag is explicitly on.

Rationale: audit 2026-11-05 showed 23/29 recent v1_pressure_against
blocks were uniquely-v1 (the unified NMS directional authority would
have admitted them), and the 4 blocked candidates with recoverable
tick outcomes were net +40 p at TP20/SL20 (3 wins / 1 loss). The
unified authority now governs direction × v3 state × exhaustion ×
WATCH_AND_WAIT. v1-pressure's role as a hard veto is redundant.

These tests pin:
  (1) default — veto flag off → v1=AGAINST does NOT refuse; the
      decision row still contains the full v1 state;
  (2) opt-in — veto flag on → legacy behaviour byte-identical;
  (3) close-back and dollar-direction vetoes unchanged in both modes;
  (4) v1_pressure_unknown is downgraded on the same flag.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import bb_bounce_filters as bbf  # noqa: E402


# ─── Injection helpers — bypass real file IO ──────────────────────────


def _stub_closeback(state="BEFORE_CLOSEBACK"):
    def _fn(**kw):
        return {"state": state, "reason": "test"}
    return _fn


def _stub_v1(state):
    def _fn(**kw):
        return {
            "state": state,
            "usd_pct": 0.1, "gbp_pct": -0.1,
            "expected_direction": "SELL" if state == bbf.V1_AGAINST else "BUY",
            "stale_gbpusd": False, "stale_eurusd": False,
            "reason": "test",
        }
    return _fn


def _stub_dd(state):
    def _fn(**kw):
        return {"state": state, "reason": "test"}
    return _fn


def _bars_closes(n=3):
    bar = {"ts": datetime(2026, 11, 5, tzinfo=timezone.utc),
           "open": 1.3, "high": 1.3, "low": 1.3, "close": 1.3}
    return ([bar] * n, [1.3] * n)


# ─── Flag helper ──────────────────────────────────────────────────────


@pytest.fixture
def filter_flags(monkeypatch):
    """Default: closeback + v1 computation + dollar-direction all ON;
    v1 veto OFF (the new 2026-11-05 default). Override per test."""
    monkeypatch.setenv("BB_BOUNCE_CLOSEBACK_ENABLED", "1")
    monkeypatch.setenv("BB_BOUNCE_V1_PRESSURE_ENABLED", "1")
    monkeypatch.setenv("BB_BOUNCE_V1_PRESSURE_VETO_ENABLED", "0")
    monkeypatch.setenv("BB_BOUNCE_DOLLAR_DIRECTION_ENABLED", "0")
    yield monkeypatch


def _apply(side: str, cb="AFTER_CLOSEBACK", v1="AGAINST", dd="WITH"):
    bars, closes = _bars_closes()
    return bbf.apply_filters(
        side=side,
        ts_utc=datetime(2026, 11, 5, 11, 20, tzinfo=timezone.utc),
        candidate_price=1.3460,
        bars=bars, closes_ind=closes,
        closeback_fn=_stub_closeback(cb),
        v1_pressure_fn=_stub_v1(v1),
        dollar_direction_fn=_stub_dd(dd),
        write_fn=lambda row: None,
    )


# ─── (1) Default (veto OFF) — v1=AGAINST no longer refuses ────────────


def test_v1_against_does_not_refuse_by_default(filter_flags):
    r = _apply("BUY", cb="AFTER_CLOSEBACK", v1=bbf.V1_AGAINST, dd="WITH")
    assert r["outcome"] == bbf.OUTCOME_TAKEN, (
        f"v1 AGAINST should no longer veto by default. row={r}"
    )
    assert r["refusing_rule"] is None, (
        f"refusing_rule must be None; got {r['refusing_rule']!r}"
    )
    # Telemetry preserved — the v1 state is still in the row.
    assert r["v1_pressure"]["state"] == bbf.V1_AGAINST
    assert r["flags"]["v1_pressure"] is True
    assert r["flags"]["v1_pressure_veto"] is False


def test_v1_unknown_does_not_refuse_by_default(filter_flags):
    r = _apply("SELL", cb="AFTER_CLOSEBACK", v1=bbf.V1_UNKNOWN, dd="WITH")
    assert r["outcome"] == bbf.OUTCOME_TAKEN
    assert r["refusing_rule"] is None
    assert r["v1_pressure"]["state"] == bbf.V1_UNKNOWN


# ─── (2) Opt-in (veto ON) — byte-identical legacy ─────────────────────


def test_v1_against_refuses_when_veto_opt_in(filter_flags):
    filter_flags.setenv("BB_BOUNCE_V1_PRESSURE_VETO_ENABLED", "1")
    r = _apply("BUY", cb="AFTER_CLOSEBACK", v1=bbf.V1_AGAINST, dd="WITH")
    assert r["outcome"] == bbf.OUTCOME_REFUSED
    assert r["refusing_rule"] == "v1_pressure_against"
    assert r["flags"]["v1_pressure_veto"] is True


def test_v1_unknown_refuses_when_veto_opt_in(filter_flags):
    filter_flags.setenv("BB_BOUNCE_V1_PRESSURE_VETO_ENABLED", "1")
    r = _apply("SELL", cb="AFTER_CLOSEBACK", v1=bbf.V1_UNKNOWN, dd="WITH")
    assert r["outcome"] == bbf.OUTCOME_REFUSED
    assert r["refusing_rule"] == "v1_pressure_unknown"


# ─── (3) Close-back + dollar-direction vetoes untouched ───────────────


def test_closeback_still_vetoes_when_v1_veto_off(filter_flags):
    r = _apply("BUY", cb="NO_CLOSEBACK_YET", v1=bbf.V1_AGAINST, dd="WITH")
    assert r["outcome"] == bbf.OUTCOME_REFUSED
    assert r["refusing_rule"] == "close_back_no_closeback_yet"


def test_dollar_direction_still_vetoes_when_v1_veto_off(filter_flags):
    filter_flags.setenv("BB_BOUNCE_DOLLAR_DIRECTION_ENABLED", "1")
    r = _apply("BUY", cb="AFTER_CLOSEBACK", v1=bbf.V1_WITH,
               dd=bbf.DOLLAR_AGAINST)
    assert r["outcome"] == bbf.OUTCOME_REFUSED
    assert r["refusing_rule"] == "dollar_direction_against"


# ─── (4) v1 computation flag off → no computation, no veto ────────────


def test_v1_computation_off_is_silent(filter_flags):
    """When BB_BOUNCE_V1_PRESSURE_ENABLED=0 the filter does not compute
    OR veto, regardless of the veto flag (legacy semantics)."""
    filter_flags.setenv("BB_BOUNCE_V1_PRESSURE_ENABLED", "0")
    filter_flags.setenv("BB_BOUNCE_V1_PRESSURE_VETO_ENABLED", "1")
    r = _apply("BUY", cb="AFTER_CLOSEBACK", v1=bbf.V1_AGAINST, dd="WITH")
    assert r["outcome"] == bbf.OUTCOME_TAKEN
    assert r["refusing_rule"] is None
    assert r["flags"]["v1_pressure"] is False
    assert r["flags"]["v1_pressure_veto"] is True


# ─── (5) Historical Nov-5 11:10 UTC replay ────────────────────────────


def test_nov5_1120_buy_no_longer_vetoed_by_v1(filter_flags):
    """The operator-cited case: Nov 5 11:20 UTC BUY blocked with
    v1_pressure_against. Post-patch default must not refuse."""
    # (The exact bar details don't matter — this test pins the
    # vocabulary + outcome of the specific stub.)
    r = _apply("BUY", cb="BEFORE_CLOSEBACK", v1=bbf.V1_AGAINST, dd="WITH")
    # closeback is BEFORE on this bar — so closeback still blocks it.
    # The important thing is the refusing_rule, if any, is NOT v1.
    # (If closeback is pending, close-back rule wins; v1 is now never
    #  the reason given BB_BOUNCE_V1_PRESSURE_VETO_ENABLED=0.)
    assert r["refusing_rule"] != "v1_pressure_against"
    assert r["refusing_rule"] != "v1_pressure_unknown"


def test_decision_row_schema_has_new_flag(filter_flags):
    r = _apply("BUY")
    assert "v1_pressure_veto" in r["flags"]
    # Backward compatibility — existing keys preserved
    assert "closeback" in r["flags"]
    assert "v1_pressure" in r["flags"]
    assert "dollar_direction" in r["flags"]
