"""Unit tests for gbpusd_trend (cascade-driven trend strategy, 2026-05-13).

Covers the state machine: stale/missing cascade handling, arming on
consecutive trend emissions at MEDIUM+ confidence, confidence floor
enforcement, label change between emissions resetting count, firing on
the next 5m close in direction, exit on consecutive non-matching
emissions, waiting_for_reset gating re-arming after exit, and
persistence of state to a temp file.

Tests use synthetic regime_shadow.jsonl fixtures via the
REGIME_SHADOW_LOG_PATH env override (cascade_state._shadow_path re-reads
env on every call). State persistence is exercised by pointing
STATE_FILE at a tmp_path before re-importing the module (importlib.reload).
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pytest

sys.path.insert(0, "/opt/tradingbot")

import cascade_state  # noqa: E402


# ────────────────────────────────────────────────── fixture helpers
# NOW is anchored to actual wall-clock UTC so cascade_state's internal
# datetime.now() (which the strategy reads — no now_utc plumbing through
# evaluate_5m_close) sees a consistent reference point with the shadow
# rows we write. Fixed-time mocking would be cleaner but requires a
# freezegun dep that isn't in the repo's pinned set.
NOW = datetime.now(timezone.utc)


def _ts(seconds_before: float) -> str:
    return (NOW - timedelta(seconds=seconds_before)).isoformat()


def _row(ts_iso, sym, stable, confidence=None):
    return {
        "ts": ts_iso,
        "symbol": sym,
        "stable": stable,
        "shadow_label": stable,
        "shadow_confidence": confidence,
    }


def _write_shadow(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _make_bar(ts: datetime, close: float, *, open_=None, high=None, low=None):
    """Build a Bar with sensible OHLC defaults around `close`."""
    from gbpusd_trend import Bar
    o = open_ if open_ is not None else close
    h = high if high is not None else max(o, close) + 0.5
    l = low if low is not None else min(o, close) - 0.5
    return Bar(timestamp=ts, open=o, high=h, low=l, close=close)


@pytest.fixture
def gbpusd_trend_module(tmp_path, monkeypatch):
    """Re-import gbpusd_trend with a fresh STATE_FILE pointing at tmp,
    and a fresh REGIME_SHADOW_LOG_PATH override. Returns (module,
    shadow_writer) where shadow_writer is a callable that overwrites the
    shadow log with the given rows.

    Test isolation (2026-05-13): GBPUSD_FORENSIC_LOG_PATH is redirected
    to tmp_path/forensic_fires.jsonl so test-time fires DO NOT pollute
    the production /opt/tradingbot/logs/forensic_fires.jsonl. Pre-fix,
    test_10/test_12 (and any other test that exercised evaluate_5m_close
    through a FIRE branch) appended real records into the live file —
    38 polluting rows on 2026-05-13 before the fix landed.
    """
    state_path = tmp_path / "gbpusd_trend_state.json"
    shadow_path = tmp_path / "regime_shadow.jsonl"
    forensic_path = tmp_path / "forensic_fires.jsonl"
    monkeypatch.setenv(cascade_state.ENV_SHADOW_PATH, str(shadow_path))
    monkeypatch.setenv("GBPUSD_TREND_ENABLED", "true")
    # Forensic log isolation — forensic_logger._log_path() re-reads env
    # on every call so this redirect works without re-import.
    monkeypatch.setenv("GBPUSD_FORENSIC_LOG_PATH", str(forensic_path))

    # Patch STATE_FILE via a sys.modules reload so the singleton picks
    # up the fresh path on init. Each test gets a clean state file.
    if "gbpusd_trend" in sys.modules:
        del sys.modules["gbpusd_trend"]
    import gbpusd_trend as gt
    monkeypatch.setattr(gt, "STATE_FILE", str(state_path))
    # Re-seed the singleton with the new STATE_FILE.
    gt.GbpUsdTrendStrategy._instance = None
    gt.strategy = gt.GbpUsdTrendStrategy.instance()

    def _shadow_setup(rows):
        _write_shadow(shadow_path, rows)
        return shadow_path

    return gt, _shadow_setup


# ────────────────────────────────────────────────── #1-4: helpers + types
def test_01_module_exposes_constants(gbpusd_trend_module):
    """Smoke: module-level constants are present with the spec values."""
    gt, _ = gbpusd_trend_module
    assert gt.LOG_TAG == "TREND"
    assert gt.MODE_NAME_LONG == "GBPUSD_TREND_L"
    assert gt.MODE_NAME_SHORT == "GBPUSD_TREND_S"
    assert gt.SL_PIPS == 12.0
    assert gt.TREND_INITIAL_SL_PIPS == 12.0
    assert gt.TREND_BROKER_TP_PIPS == 80.0
    assert gt.TREND_TRAIL_STEP_1_TRIGGER_PIPS == 25.0
    assert gt.TREND_TRAIL_STEP_1_LOCK_PIPS == 15.0
    assert gt.TREND_TRAIL_STEP_2_TRIGGER_PIPS == 40.0
    assert gt.TREND_TRAIL_STEP_2_LOCK_PIPS == 25.0
    assert gt.MIN_CONFIDENCE == "MEDIUM"
    assert gt.CONSECUTIVE_THRESHOLD == 2
    assert gt.STALE_CASCADE_SECONDS == 600.0
    # Cascade-flip exit removed 2026-05-13 — EXIT_THRESHOLD must not exist.
    assert not hasattr(gt, "EXIT_THRESHOLD")


def test_02_confidence_meets_helper():
    """The confidence ordering helper used for arming."""
    from cascade_state import confidence_meets
    assert confidence_meets("HIGH", "MEDIUM") is True
    assert confidence_meets("MEDIUM", "MEDIUM") is True
    assert confidence_meets("MED", "MEDIUM") is True       # alias
    assert confidence_meets("LOW", "MEDIUM") is False
    assert confidence_meets(None, "MEDIUM") is False
    assert confidence_meets("BOGUS", "MEDIUM") is False
    assert confidence_meets("HIGH", "HIGH") is True
    assert confidence_meets("MEDIUM", "HIGH") is False


def test_03_initial_state_is_idle(gbpusd_trend_module):
    """Fresh hydrate (no state file) → pair starts idle, no position."""
    gt, _ = gbpusd_trend_module
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "idle"
    assert st["consecutive_trend_count"] == 0
    assert st["position_direction"] is None
    assert st["last_cascade_label"] is None


def test_04_idle_no_fire_with_no_bars(gbpusd_trend_module):
    """Empty bar list → None, no state change."""
    gt, shadow = gbpusd_trend_module
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "HIGH")])
    out = gt.strategy.evaluate_5m_close("GBPUSD", [], False)
    assert out is None


# ─────────────────────────────────────────────── #5-9: arming logic
def test_05_one_med_trend_emission_does_not_arm(gbpusd_trend_module):
    """Threshold=2; one matching emission alone keeps state idle."""
    gt, shadow = gbpusd_trend_module
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "MED")])
    bars = [_make_bar(NOW, 13500.0), _make_bar(NOW, 13501.0)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "idle"
    assert st["consecutive_trend_count"] == 1


def test_06_two_consecutive_med_trend_up_arms_long(gbpusd_trend_module):
    """Two same-direction MED+ emissions → armed_long. Bars are flat so
    the second eval arms (doesn't fire) — fire requires cur > prev."""
    gt, shadow = gbpusd_trend_module
    shadow([_row(_ts(60), "GBPUSD", "TREND_UP", "MED")])
    bars1 = [_make_bar(NOW - timedelta(minutes=10), 13500.0),
             _make_bar(NOW - timedelta(minutes=5), 13500.5)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars1, False)
    # Second emission, fresher timestamp. Flat bars (cur == prev) so
    # arming progresses to armed_long but the bar doesn't fire.
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "HIGH")])
    bars2 = [_make_bar(NOW - timedelta(minutes=5), 13500.5),
             _make_bar(NOW, 13500.5)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars2, False)
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "armed_long"
    assert st["consecutive_trend_count"] >= 2


def test_07_low_confidence_does_not_arm(gbpusd_trend_module):
    """Confidence LOW < MEDIUM → does not count toward arming."""
    gt, shadow = gbpusd_trend_module
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "LOW")])
    bars = [_make_bar(NOW - timedelta(minutes=5), 13500.0),
            _make_bar(NOW, 13501.0)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "idle"
    # Non-matching → consecutive count resets to 0
    assert st["consecutive_trend_count"] == 0


def test_08_label_flip_between_emissions_resets_count(gbpusd_trend_module):
    """TREND_UP then TREND_DOWN at MED+ — count must reset, not arm long."""
    gt, shadow = gbpusd_trend_module
    shadow([_row(_ts(60), "GBPUSD", "TREND_UP", "HIGH")])
    bars1 = [_make_bar(NOW - timedelta(minutes=5), 13500.0),
             _make_bar(NOW - timedelta(minutes=5), 13500.5)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars1, False)
    shadow([_row(_ts(30), "GBPUSD", "TREND_DOWN", "HIGH")])
    bars2 = [_make_bar(NOW - timedelta(minutes=5), 13500.5),
             _make_bar(NOW, 13499.0)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars2, False)
    st = gt.strategy._pair_state("GBPUSD")
    # Started a fresh SHORT streak — count=1, not armed yet
    assert st["arm_state"] == "idle"
    assert st["consecutive_trend_count"] == 1
    assert st["last_cascade_label"] == "TREND_DOWN"


def test_09_two_consecutive_trend_down_arms_short(gbpusd_trend_module):
    """Symmetric: 2 TREND_DOWN MED+ → armed_short. Flat bars so no fire."""
    gt, shadow = gbpusd_trend_module
    shadow([_row(_ts(60), "GBPUSD", "TREND_DOWN", "MEDIUM")])
    bars1 = [_make_bar(NOW - timedelta(minutes=10), 13500.0),
             _make_bar(NOW - timedelta(minutes=5), 13499.5)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars1, False)
    shadow([_row(_ts(30), "GBPUSD", "TREND_DOWN", "HIGH")])
    bars2 = [_make_bar(NOW - timedelta(minutes=5), 13499.5),
             _make_bar(NOW, 13499.5)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars2, False)
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "armed_short"


# ─────────────────────────────────────────────── #10-13: fire logic
def test_10_armed_long_fires_on_up_close(gbpusd_trend_module):
    """Armed long + current_close > prev_close → BUY decision."""
    gt, shadow = gbpusd_trend_module
    # Arm long with two TREND_UP MED+ emissions.
    shadow([_row(_ts(60), "GBPUSD", "TREND_UP", "MED")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=10), 13500.0),
         _make_bar(NOW - timedelta(minutes=5), 13500.5)],
        False,
    )
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "MED")])
    # Now fire on the next 5m close where current > prev.
    bars = [_make_bar(NOW - timedelta(minutes=5), 13500.5),
            _make_bar(NOW, 13502.0)]  # cur > prev
    dec = gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    assert dec is not None
    assert dec.signal == "BUY"
    assert dec.mode == "GBPUSD_TREND_L"
    assert dec.sl == 12.0


def test_11_armed_long_no_fire_on_down_close(gbpusd_trend_module):
    """Armed long but current_close <= prev_close → no fire, stay armed."""
    gt, shadow = gbpusd_trend_module
    shadow([_row(_ts(60), "GBPUSD", "TREND_UP", "MED")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=10), 13500.0),
         _make_bar(NOW - timedelta(minutes=5), 13500.5)],
        False,
    )
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "MED")])
    # Down close — don't fire.
    bars = [_make_bar(NOW - timedelta(minutes=5), 13500.5),
            _make_bar(NOW, 13499.0)]
    dec = gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    assert dec is None
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "armed_long"
    assert st["position_direction"] is None


def test_12_armed_short_fires_on_down_close(gbpusd_trend_module):
    """Mirror: armed short + cur_close < prev_close → SELL."""
    gt, shadow = gbpusd_trend_module
    shadow([_row(_ts(60), "GBPUSD", "TREND_DOWN", "HIGH")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=10), 13500.0),
         _make_bar(NOW - timedelta(minutes=5), 13499.5)],
        False,
    )
    shadow([_row(_ts(30), "GBPUSD", "TREND_DOWN", "HIGH")])
    bars = [_make_bar(NOW - timedelta(minutes=5), 13499.5),
            _make_bar(NOW, 13498.0)]
    dec = gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    assert dec is not None
    assert dec.signal == "SELL"
    assert dec.mode == "GBPUSD_TREND_S"


def test_13_has_active_position_blocks_new_fire(gbpusd_trend_module):
    """has_active_position=True → strategy never returns a decision."""
    gt, shadow = gbpusd_trend_module
    # Arm long.
    shadow([_row(_ts(60), "GBPUSD", "TREND_UP", "MED")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=10), 13500.0),
         _make_bar(NOW - timedelta(minutes=5), 13500.5)],
        False,
    )
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "MED")])
    bars = [_make_bar(NOW - timedelta(minutes=5), 13500.5),
            _make_bar(NOW, 13502.0)]
    dec = gt.strategy.evaluate_5m_close("GBPUSD", bars, has_active_position=True)
    assert dec is None


# ─────────────────────────────────────────────── #14: open-position 5m close is a no-op
def test_14_open_position_5m_close_no_state_mutation(gbpusd_trend_module):
    """2026-05-13: cascade-flip exit removed. With a position open, the
    5m-close path is now a no-op — no exit_counter ticks, no state
    mutation. Exits are entirely broker-side (SL/TP) + software trail
    on ticks + EOD 21:00 UTC sweep.
    """
    gt, shadow = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13502.0)
    pre = dict(gt.strategy._pair_state("GBPUSD"))
    # Two consecutive TREND_DOWN emissions — pre-2026-05-13 this would
    # have requested close. Now: nothing happens.
    shadow([_row(_ts(60), "GBPUSD", "TREND_DOWN", "HIGH")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=10), 13502.0),
         _make_bar(NOW - timedelta(minutes=5), 13502.0)],
        has_active_position=True,
    )
    shadow([_row(_ts(30), "GBPUSD", "TREND_DOWN", "HIGH")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=5), 13502.0),
         _make_bar(NOW, 13501.0)],
        has_active_position=True,
    )
    post = dict(gt.strategy._pair_state("GBPUSD"))
    assert post["position_direction"] == pre["position_direction"] == "LONG"
    assert post["trail_step"] == 0
    assert "exit_counter" not in post  # field removed entirely


# ─────────────────────────────────────────────── #17-18: lifecycle
def test_17_waiting_for_reset_blocks_immediate_rearm(gbpusd_trend_module):
    """After mark_position_closed, state is waiting_for_reset and the
    same-direction trend does NOT immediately rearm."""
    gt, shadow = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13502.0)
    # Manually transition the last_cascade_label to TREND_UP so the
    # reset rule has prior state to compare against.
    st = gt.strategy._pair_state("GBPUSD")
    st["last_cascade_label"] = "TREND_UP"
    gt.strategy.mark_position_closed("GBPUSD", reason="test")
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "waiting_for_reset"

    # Same direction cascade — must NOT arm.
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "HIGH")])
    bars = [_make_bar(NOW - timedelta(minutes=5), 13502.0),
            _make_bar(NOW, 13503.0)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "waiting_for_reset"
    assert st["consecutive_trend_count"] == 0


def test_18_neutral_cascade_clears_waiting_for_reset(gbpusd_trend_module):
    """waiting_for_reset → NEUTRAL emission → idle (re-arm allowed)."""
    gt, shadow = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13502.0)
    st = gt.strategy._pair_state("GBPUSD")
    st["last_cascade_label"] = "TREND_UP"
    gt.strategy.mark_position_closed("GBPUSD", reason="test")
    shadow([_row(_ts(30), "GBPUSD", "NEUTRAL", "LOW")])
    bars = [_make_bar(NOW - timedelta(minutes=5), 13502.0),
            _make_bar(NOW, 13502.5)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "idle"
    assert st["consecutive_trend_count"] == 0


# ─────────────────────────────────────────────── #19: stale cascade
def test_19_stale_cascade_does_not_arm(gbpusd_trend_module):
    """Cascade age > STALE_CASCADE_SECONDS (600s) → strategy SKIPS arming.
    State stays idle, consecutive_trend_count stays 0.

    This is the canary test for the user's spec: "no signal is no
    action, never degrade to 'arm anyway' on missing data."
    """
    gt, shadow = gbpusd_trend_module
    # Emission 900s ago — stale.
    shadow([_row(_ts(900), "GBPUSD", "TREND_UP", "HIGH")])
    bars = [_make_bar(NOW - timedelta(minutes=5), 13500.0),
            _make_bar(NOW, 13501.0)]
    gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "idle"
    assert st["consecutive_trend_count"] == 0


# ─────────────────────────────────────────────── #20: missing cascade
def test_20_missing_cascade_does_not_arm_or_raise(gbpusd_trend_module):
    """Cascade reader returns None → SKIPS arming, no exception."""
    gt, shadow = gbpusd_trend_module
    # Empty shadow file → reader returns (None, None, None).
    shadow([])
    bars = [_make_bar(NOW - timedelta(minutes=5), 13500.0),
            _make_bar(NOW, 13501.0)]
    out = gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    assert out is None
    st = gt.strategy._pair_state("GBPUSD")
    assert st["arm_state"] == "idle"
    assert st["consecutive_trend_count"] == 0


# ─────────────────────────────────────────────── #21: persistence
def test_21_state_persists_to_file_on_transition(gbpusd_trend_module):
    """Arm-state transition → STATE_FILE on disk reflects the change."""
    gt, shadow = gbpusd_trend_module
    state_path = Path(gt.STATE_FILE)
    # Two TREND_UP emissions → armed_long.
    shadow([_row(_ts(60), "GBPUSD", "TREND_UP", "MED")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=10), 13500.0),
         _make_bar(NOW - timedelta(minutes=5), 13500.5)],
        False,
    )
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "MED")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=5), 13500.5),
         _make_bar(NOW, 13500.5)],  # equal — no fire, just arm
        False,
    )
    # Force a persist by going through a position-opened transition.
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13501.0)
    assert state_path.exists()
    with state_path.open("r") as fh:
        data = json.load(fh)
    assert "GBPUSD" in data
    assert data["GBPUSD"]["position_direction"] == "LONG"
    assert data["GBPUSD"]["entry_price"] == 13501.0


# ───────────────────────────────────────── #22-30: trailing stop (2026-05-13)
def test_22_trail_step_1_arms_at_25p_mfe(gbpusd_trend_module):
    """LONG position, peak MFE reaches 25p → returns step-1 amend."""
    gt, _ = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13500.0)
    # 13525 = +25p MFE for LONG (PIP_SIZE=1.0).
    amend = gt.strategy.update_trailing_stop("GBPUSD", current_price=13525.0)
    assert amend is not None
    assert amend["step"] == 1
    assert amend["lock_pips"] == 15.0
    # entry + 15p = 13515
    assert amend["new_sl_price"] == 13515.0
    # Peak MFE must be recorded.
    st = gt.strategy._pair_state("GBPUSD")
    assert st["peak_mfe_pips"] >= 25.0
    # Trail not yet committed — caller does that after broker amend.
    assert st["trail_step"] == 0


def test_23_trail_step_1_no_arm_at_24p_mfe(gbpusd_trend_module):
    """Peak MFE 24p (below trigger) → no amend, trail_step stays 0."""
    gt, _ = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13500.0)
    amend = gt.strategy.update_trailing_stop("GBPUSD", current_price=13524.0)
    assert amend is None
    st = gt.strategy._pair_state("GBPUSD")
    assert st["trail_step"] == 0
    assert st["peak_mfe_pips"] == 24.0


def test_24_trail_step_2_arms_at_40p_mfe(gbpusd_trend_module):
    """From step-1 state, peak MFE reaches 40p → step-2 amend at entry+25p."""
    gt, _ = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13500.0)
    # First trigger step 1 and commit.
    amend1 = gt.strategy.update_trailing_stop("GBPUSD", current_price=13525.0)
    assert amend1 is not None
    gt.strategy.commit_trail_step("GBPUSD",
                                   step=amend1["step"], lock_pips=amend1["lock_pips"])
    # Now push MFE to +40p.
    amend2 = gt.strategy.update_trailing_stop("GBPUSD", current_price=13540.0)
    assert amend2 is not None
    assert amend2["step"] == 2
    assert amend2["lock_pips"] == 25.0
    assert amend2["new_sl_price"] == 13525.0   # entry + 25p
    st = gt.strategy._pair_state("GBPUSD")
    assert st["peak_mfe_pips"] >= 40.0


def test_25_trail_no_regression(gbpusd_trend_module):
    """Peak MFE 30p then retraces to 20p → trail_step stays 1, no
    second amend (the original step-1 amend is the only one)."""
    gt, _ = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13500.0)
    amend1 = gt.strategy.update_trailing_stop("GBPUSD", current_price=13530.0)
    assert amend1 is not None
    gt.strategy.commit_trail_step("GBPUSD",
                                   step=amend1["step"], lock_pips=amend1["lock_pips"])
    # Retrace to +20p — below step-1 trigger but step is already armed.
    amend2 = gt.strategy.update_trailing_stop("GBPUSD", current_price=13520.0)
    assert amend2 is None
    st = gt.strategy._pair_state("GBPUSD")
    assert st["trail_step"] == 1
    assert st["peak_mfe_pips"] >= 30.0           # peak only grows
    assert st["current_broker_sl_pips"] == 15.0  # locked at entry+15p


def test_26_initial_sl_unchanged_below_trigger(gbpusd_trend_module):
    """MFE 10p → no amend, trail_step=0, current_broker_sl_pips=None."""
    gt, _ = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13500.0)
    amend = gt.strategy.update_trailing_stop("GBPUSD", current_price=13510.0)
    assert amend is None
    st = gt.strategy._pair_state("GBPUSD")
    assert st["trail_step"] == 0
    assert st["current_broker_sl_pips"] is None
    assert st["peak_mfe_pips"] == 10.0


def test_27_fire_with_tp_80_and_sl_12(gbpusd_trend_module):
    """Arming + firing emits a StrategyDecision with sl=12 tp=80."""
    gt, shadow = gbpusd_trend_module
    shadow([_row(_ts(60), "GBPUSD", "TREND_UP", "MED")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=10), 13500.0),
         _make_bar(NOW - timedelta(minutes=5), 13500.5)],
        False,
    )
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "MED")])
    bars = [_make_bar(NOW - timedelta(minutes=5), 13500.5),
            _make_bar(NOW, 13502.0)]   # cur > prev → fire
    dec = gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    assert dec is not None
    assert dec.signal == "BUY"
    assert dec.sl == 12.0
    assert dec.tp == 80.0                     # 2026-05-13: broker TP
    # tp=0.0 (cascade-flip exit semantics) must be GONE.
    assert dec.tp != 0.0
    # debug carries the new lifecycle tag and tp_pips=80.
    assert dec.debug["tp_pips"] == 80.0
    assert dec.debug["strategy_lifecycle"] == "cascade_trend_v2_trail"


def test_28_position_close_resets_trail_state(gbpusd_trend_module):
    """mark_position_closed → trail_step=0, peak_mfe_pips=0,
    current_broker_sl_pips=None, arm_state=waiting_for_reset."""
    gt, _ = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "BUY", entry_price=13500.0)
    # Push trail to step 1.
    amend = gt.strategy.update_trailing_stop("GBPUSD", current_price=13525.0)
    gt.strategy.commit_trail_step("GBPUSD",
                                   step=amend["step"], lock_pips=amend["lock_pips"])
    st = gt.strategy._pair_state("GBPUSD")
    assert st["trail_step"] == 1
    gt.strategy.mark_position_closed("GBPUSD", reason="broker_sl_hit",
                                     exit_price=13515.0)
    st = gt.strategy._pair_state("GBPUSD")
    assert st["trail_step"] == 0
    assert st["peak_mfe_pips"] == 0.0
    assert st["current_broker_sl_pips"] is None
    assert st["arm_state"] == "waiting_for_reset"


def test_29_short_direction_trail_step_1(gbpusd_trend_module):
    """SHORT position, favourable MFE 25p (price 25p BELOW entry) →
    step-1 amend at entry-15p."""
    gt, _ = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "SELL", entry_price=13500.0)
    # 13475 = +25p MFE for SHORT.
    amend = gt.strategy.update_trailing_stop("GBPUSD", current_price=13475.0)
    assert amend is not None
    assert amend["step"] == 1
    assert amend["lock_pips"] == 15.0
    assert amend["new_sl_price"] == 13485.0   # entry - 15p
    gt.strategy.commit_trail_step("GBPUSD",
                                   step=amend["step"], lock_pips=amend["lock_pips"])
    st = gt.strategy._pair_state("GBPUSD")
    # current_broker_sl_pips is signed: SHORT locks at -lock.
    assert st["current_broker_sl_pips"] == -15.0


def test_30_short_direction_trail_step_2(gbpusd_trend_module):
    """SHORT from step-1 → MFE 40p → step-2 amend at entry-25p."""
    gt, _ = gbpusd_trend_module
    gt.strategy.mark_position_opened("GBPUSD", "SELL", entry_price=13500.0)
    amend1 = gt.strategy.update_trailing_stop("GBPUSD", current_price=13475.0)
    gt.strategy.commit_trail_step("GBPUSD",
                                   step=amend1["step"], lock_pips=amend1["lock_pips"])
    # Push to +40p MFE.
    amend2 = gt.strategy.update_trailing_stop("GBPUSD", current_price=13460.0)
    assert amend2 is not None
    assert amend2["step"] == 2
    assert amend2["new_sl_price"] == 13475.0   # entry - 25p


# ───────────────────────────────────────── #31: forensic-log isolation
def test_31_test_fixture_does_not_pollute_production_forensic_log(
    gbpusd_trend_module, tmp_path,
):
    """The fixture redirects GBPUSD_FORENSIC_LOG_PATH to a tmp file.
    Firing the strategy must NOT touch the production log."""
    gt, shadow = gbpusd_trend_module
    PROD_LOG = Path("/opt/tradingbot/logs/forensic_fires.jsonl")
    pre_mtime = PROD_LOG.stat().st_mtime if PROD_LOG.exists() else None
    pre_len = sum(1 for _ in PROD_LOG.open()) if PROD_LOG.exists() else 0

    # Arm + fire.
    shadow([_row(_ts(60), "GBPUSD", "TREND_UP", "MED")])
    gt.strategy.evaluate_5m_close(
        "GBPUSD",
        [_make_bar(NOW - timedelta(minutes=10), 13500.0),
         _make_bar(NOW - timedelta(minutes=5), 13500.5)],
        False,
    )
    shadow([_row(_ts(30), "GBPUSD", "TREND_UP", "MED")])
    bars = [_make_bar(NOW - timedelta(minutes=5), 13500.5),
            _make_bar(NOW, 13502.0)]
    dec = gt.strategy.evaluate_5m_close("GBPUSD", bars, False)
    assert dec is not None  # fire happened

    if PROD_LOG.exists():
        post_mtime = PROD_LOG.stat().st_mtime
        post_len = sum(1 for _ in PROD_LOG.open())
        assert post_mtime == pre_mtime, "production forensic log mtime changed"
        assert post_len == pre_len, "production forensic log line count changed"
