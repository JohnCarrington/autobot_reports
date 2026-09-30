"""Engine → Matrix contract coverage (2026-07-09).

The a8148ee wiring in autobot._emit_then_route reads keys off the emit()
return dict that historically only existed on the JSONL row (winning_regime,
regime_label_path, range_break_promoted, range_exit_breakout,
hist_freshness_fail_count). As of 2026-07-09 emit() ADDS those keys to the
return contract — additive only, legacy `regime` + `debug` untouched.

Cases:
    (a) emit() return dict carries all five public keys with values that
        match either result["regime"] (winning_regime) or result["debug"][k]
        (the hoisted keys). Run against a real classify on a synthetic 5m
        DataFrame — no `regime` field, no `winning_regime`, no matrix ever
        works, hence the two-tier check.
    (b) Anti-drift contract check: the key names autobot passes into
        regime_matrix.update() must be a subset of the key names emit()
        writes on its return dict. Extracted from autobot.py source; if
        anyone renames on either side without touching the other, this test
        breaks in CI before it breaks in production.
    (c) Null-alarm fires at REGIME_MATRIX_NULL_ALARM_N consecutive nulls
        and resets on any real label.
    (d) Null-alarm respects env override — a larger N delays the log.
"""
from __future__ import annotations

import ast
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
AUTOBOT_PATH = REPO_ROOT / "autobot.py"


# ─── Helpers ───────────────────────────────────────────────────────────────
def _mk_df(adx: float = 20.0, plus_di: float = 25.0, minus_di: float = 15.0,
           ema_state: str = "BULL_ALIGNED") -> pd.DataFrame:
    return pd.DataFrame([{
        "timestamp": pd.Timestamp("2026-07-09T04:55:00Z"),
        "close": 1.34,
        "EMA_21": 1.34, "EMA_50": 1.34, "EMA_50_SLOPE": 0.0,
        "ADX_14": adx, "PLUS_DI_14": plus_di, "MINUS_DI_14": minus_di,
        "EMA_STACK_STATE": ema_state,
    }])


def _h1_stub(regime: str, directional_bias: str,
             hist: float, slope: float) -> Dict[str, Any]:
    return {
        "regime": regime,
        "directional_bias": directional_bias,
        "hist": hist,
        "hist_slope": slope,
        "macd_line": hist + 0.5, "macd_signal": 0.5,
        "just_crossed": False,
        "reason": f"H1_MACD hist={hist:.3f} slope_2b={slope:.3f} -> {regime}",
        "n_h1_closes": 200,
    }


def _range_stub_off() -> Dict[str, Any]:
    return {
        "enabled": False, "override_active": False, "state": None,
        "signature_met": False, "hyst_count": 0,
        "box_high": None, "box_low": None,
        "exit_breakout": False, "exit_direction": None,
        "er10": None, "adx14": None, "bb_w_pips": None, "atr14_pips": None,
        "body_pips": None, "cross_n": None,
    }


# ─── (a) emit() return carries all five public keys ────────────────────────
def test_emit_return_carries_public_contract_keys(monkeypatch, tmp_path):
    """Contract: emit() returned dict has winning_regime + four hoisted keys."""
    monkeypatch.delitem(sys.modules, "regime_engine", raising=False)
    monkeypatch.setenv("REGIME_DECAY_LADDER_ENABLED", "0")
    import regime_engine as RE  # noqa: E402
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_UP",
                                              "LONG", 2.5, 0.13))
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())
    monkeypatch.setattr(RE, "resolve_briefing_bias", lambda _sym: (None, 0))

    tel = tmp_path / "engine.jsonl"
    result = RE.emit("GBPUSD", _mk_df(), telemetry_path=str(tel))

    # Legacy keys must still be there — additive-only guarantee.
    assert "regime" in result
    assert "debug" in result

    # New public contract — the six keys autobot._emit_then_route reads.
    # h1_decel_streak added 2026-07-09 for the asymmetric-response build.
    for k in ("winning_regime", "regime_label_path",
              "range_break_promoted", "range_exit_breakout",
              "hist_freshness_fail_count", "h1_decel_streak"):
        assert k in result, f"emit() return missing public key {k!r}"

    # Values match their source of truth.
    assert result["winning_regime"] == result["regime"]
    dbg = result["debug"]
    assert result["regime_label_path"] == dbg.get("regime_label_path")
    assert result["range_break_promoted"] == bool(dbg.get("range_break_promoted", False))
    assert result["range_exit_breakout"] == bool(dbg.get("range_exit_breakout", False))
    assert result["hist_freshness_fail_count"] == int(dbg.get("hist_freshness_fail_count") or 0)
    assert result["h1_decel_streak"] == int(dbg.get("h1_decel_streak") or 0)

    # And the winning_regime is a real label — the actual bug we're closing.
    assert isinstance(result["winning_regime"], str) and result["winning_regime"], \
        "winning_regime resolved to None/empty — matrix would still be fail-closed"


def test_emit_winning_regime_tracks_conf_floor_demotion(monkeypatch, tmp_path):
    """When the conf floor demotes result["regime"] to CHOP inside emit(),
    winning_regime on the return dict must reflect the POST-demotion label,
    not the pre-floor label. Otherwise the matrix would see the pre-floor
    trend regime while the JSONL row (and downstream readers) see CHOP.
    """
    monkeypatch.delitem(sys.modules, "regime_engine", raising=False)
    monkeypatch.setenv("REGIME_DECAY_LADDER_ENABLED", "1")
    monkeypatch.setenv("REGIME_DECAY_CONF_FACTOR", "0.85")
    monkeypatch.setenv("REGIME_CONF_FLOOR", "0.20")
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_HYST_N", "3")
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_ADX_MAX", "25")
    monkeypatch.setenv("REGIME_HIST_FRESHNESS_DI_SIG_MAX", "3")
    import regime_engine as RE  # noqa: E402
    RE._HIST_FRESHNESS_STATE_BY_SYM.clear()
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_DOWN",
                                              "SHORT", -2.5, -0.13))
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())
    monkeypatch.setattr(RE, "resolve_briefing_bias", lambda _sym: (None, 0))

    tel = tmp_path / "engine.jsonl"
    df = _mk_df(adx=20.0, plus_di=25.0, minus_di=15.0)
    # Ten contradicting bars — enough to walk both decay rungs to CHOP.
    result = None
    for _ in range(10):
        result = RE.emit("GBPUSD", df, telemetry_path=str(tel))
    assert result is not None
    assert result["regime"] == "CHOP"
    assert result["winning_regime"] == "CHOP", \
        "winning_regime must reflect post-floor demotion, not pre-floor label"


# ─── (b) Anti-drift contract — the two modules speak the same vocabulary ──
def test_autobot_call_site_keys_are_subset_of_emit_return_keys(monkeypatch, tmp_path):
    """Extract the keys autobot._emit_then_route reads off `result`, then
    check every one of them is present in emit()'s return dict.

    If someone renames a key on either side without updating the other, this
    test breaks in CI — a durable fix for the class of bug a8148ee introduced.
    """
    src = AUTOBOT_PATH.read_text()
    tree = ast.parse(src)
    keys_read: set[str] = set()
    # Look for the specific call chain (result or {}).get("<key>")` inside
    # any function; each such Call literal captures a key autobot expects on
    # the return dict.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get"):
            continue
        # func.value should be a BoolOp `(result or {})`
        val = func.value
        if not (isinstance(val, ast.BoolOp) and isinstance(val.op, ast.Or)):
            continue
        names = [n.id for n in val.values if isinstance(n, ast.Name)]
        if "result" not in names:
            continue
        if node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            keys_read.add(node.args[0].value)

    # Minimum expected — the six keys _emit_then_route reads today.
    required = {"winning_regime", "range_break_promoted", "range_exit_breakout",
                "regime_label_path", "hist_freshness_fail_count",
                "h1_decel_streak"}
    missing_from_call_site = required - keys_read
    assert not missing_from_call_site, (
        f"autobot.py no longer reads these keys off `result` — did the "
        f"_emit_then_route dispatch hook get renamed or removed? "
        f"missing={missing_from_call_site}"
    )

    # Now confirm emit() actually writes every key autobot reads.
    monkeypatch.delitem(sys.modules, "regime_engine", raising=False)
    monkeypatch.setenv("REGIME_DECAY_LADDER_ENABLED", "0")
    import regime_engine as RE  # noqa: E402
    monkeypatch.setattr(RE, "_classify_macd_h1",
                        lambda _sym: _h1_stub("STRONG_TREND_UP",
                                              "LONG", 2.5, 0.13))
    monkeypatch.setattr(RE, "_run_range_detector",
                        lambda _sym, _feat, _adx: _range_stub_off())
    monkeypatch.setattr(RE, "resolve_briefing_bias", lambda _sym: (None, 0))

    tel = tmp_path / "engine.jsonl"
    result = RE.emit("GBPUSD", _mk_df(), telemetry_path=str(tel))

    missing_on_return = required - set(result.keys())
    assert not missing_on_return, (
        f"emit() return dict is missing keys autobot reads — contract regression. "
        f"missing={missing_on_return}. Add them to the additive block before "
        f"`return result` in regime_engine.emit()."
    )


# ─── (c) Matrix null-alarm fires at N and resets on real label ─────────────
@pytest.fixture
def matrix_alarm(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_NULL_ALARM_N", "5")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH",
                       str(tmp_path / "matrix_alarm.jsonl"))
    monkeypatch.delitem(sys.modules, "regime_matrix", raising=False)
    import regime_matrix
    regime_matrix._reset_state_for_tests()
    return regime_matrix


def test_null_alarm_fires_at_floor(matrix_alarm, caplog):
    m = matrix_alarm
    caplog.set_level(logging.ERROR, logger="regime_matrix")
    # First four nulls — silent.
    for _ in range(4):
        m.update("GBPUSD", None)
    assert not any("consecutive null labels" in r.getMessage()
                   for r in caplog.records), \
        "alarm fired before crossing floor"
    # Fifth null — alarm fires.
    m.update("GBPUSD", None)
    alarms = [r for r in caplog.records
              if "consecutive null labels" in r.getMessage()]
    assert len(alarms) == 1, f"expected exactly one alarm at N=5, got {len(alarms)}"
    assert alarms[0].levelno == logging.ERROR
    assert "GBPUSD" in alarms[0].getMessage()
    assert "5" in alarms[0].getMessage()


def test_null_alarm_resets_on_real_label(matrix_alarm, caplog):
    m = matrix_alarm
    caplog.set_level(logging.ERROR, logger="regime_matrix")
    # Trip the alarm.
    for _ in range(5):
        m.update("GBPUSD", None)
    assert any("consecutive null labels" in r.getMessage()
               for r in caplog.records)
    caplog.clear()
    # A real label arrives — streak resets.
    m.update("GBPUSD", "CHOP")
    # Now four more nulls should NOT re-trip.
    for _ in range(4):
        m.update("GBPUSD", None)
    assert not any("consecutive null labels" in r.getMessage()
                   for r in caplog.records), \
        "alarm re-fired before streak re-crossed floor after reset"


def test_null_alarm_re_fires_every_n_bars_while_stuck(matrix_alarm, caplog):
    """Fires ONCE per N-multiple crossing while raw stays null — a stuck
    contract regression should scream repeatedly, not just once."""
    m = matrix_alarm
    caplog.set_level(logging.ERROR, logger="regime_matrix")
    for _ in range(15):
        m.update("GBPUSD", None)
    alarms = [r for r in caplog.records
              if "consecutive null labels" in r.getMessage()]
    # Streak crosses 5, 10, 15 → three alarms.
    assert len(alarms) == 3, f"expected 3 alarms at 5/10/15, got {len(alarms)}"


def test_null_alarm_is_per_symbol(matrix_alarm, caplog):
    m = matrix_alarm
    caplog.set_level(logging.ERROR, logger="regime_matrix")
    # GBPUSD accrues 4 nulls, EURUSD accrues 5.
    for _ in range(4):
        m.update("GBPUSD", None)
    for _ in range(5):
        m.update("EURUSD", None)
    alarms = [r for r in caplog.records
              if "consecutive null labels" in r.getMessage()]
    assert len(alarms) == 1, f"expected one alarm (EURUSD), got {len(alarms)}"
    assert "EURUSD" in alarms[0].getMessage()


def test_null_alarm_no_op_when_matrix_disabled(monkeypatch, tmp_path, caplog):
    """Flag OFF: update() is a no-op — no alarm, no state."""
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "0")
    monkeypatch.setenv("REGIME_MATRIX_NULL_ALARM_N", "5")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH",
                       str(tmp_path / "matrix_alarm_off.jsonl"))
    monkeypatch.delitem(sys.modules, "regime_matrix", raising=False)
    import regime_matrix
    regime_matrix._reset_state_for_tests()
    caplog.set_level(logging.ERROR, logger="regime_matrix")
    for _ in range(10):
        regime_matrix.update("GBPUSD", None)
    assert not any("consecutive null labels" in r.getMessage()
                   for r in caplog.records)


# ─── (d) Env override changes the floor ────────────────────────────────────
def test_null_alarm_respects_env_override(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_NULL_ALARM_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH",
                       str(tmp_path / "matrix_alarm_override.jsonl"))
    monkeypatch.delitem(sys.modules, "regime_matrix", raising=False)
    import regime_matrix
    regime_matrix._reset_state_for_tests()
    caplog.set_level(logging.ERROR, logger="regime_matrix")
    for _ in range(2):
        regime_matrix.update("GBPUSD", None)
    assert not any("consecutive null labels" in r.getMessage()
                   for r in caplog.records)
    regime_matrix.update("GBPUSD", None)
    alarms = [r for r in caplog.records
              if "consecutive null labels" in r.getMessage()]
    assert len(alarms) == 1, f"expected alarm at overridden N=3, got {len(alarms)}"
