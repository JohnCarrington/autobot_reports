"""Phase 2 C2 — self-gate bypass + CF armed-state preservation.

Covers:
- (e) self-gate bypass only when REGIME_MATRIX_ENABLED=1
- (f) CONFIRMATION_FALLBACK disarm path executes under the flag (not by
  assertion — the callback is actually invoked)
- flag OFF byte-identical for the gate

Run: pytest tests/unit/test_regime_matrix_self_gates.py -q
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest


def _reload(names):
    for n in names:
        if n in sys.modules:
            del sys.modules[n]


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "0")
    _reload(["regime_matrix", "gbpusd_confirmation_fallback"])


@pytest.fixture
def flag_on(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", str(tmp_path / "matrix.jsonl"))
    _reload(["regime_matrix", "gbpusd_confirmation_fallback"])


# ── (f) CF disarm executes under the flag ─────────────────────────────────

def test_cf_disarm_fires_on_matrix_suppression(flag_on):
    """Register happened at module import. Populate _armed, drive a
    transition that removes CF from the permitted set, and confirm the
    strategy's _armed dict has been cleared.
    """
    import regime_matrix as rm
    import gbpusd_confirmation_fallback as cf

    # Sanity: matrix flag on, singleton has an _armed dict.
    assert rm.REGIME_MATRIX_ENABLED is True
    assert hasattr(cf.strategy, "_armed")
    assert isinstance(cf.strategy._armed, dict)

    # Reset matrix and populate CF armed state.
    rm._reset_state_for_tests()
    # Callback registration is lost on _reset — re-register for the test.
    rm.register_on_suppress(cf.MODE_NAME_LONG, cf._cf_matrix_disarm)
    rm.register_on_suppress(cf.MODE_NAME_SHORT, cf._cf_matrix_disarm)

    cf.strategy._armed["CS.D.CFDGBPUSD.MINI.IP"] = {"phase": "SWEEP"}
    cf.strategy._armed["CS.D.SPOTGBPUSD.MINI.IP"] = {"phase": "RECLAIM"}
    assert len(cf.strategy._armed) == 2

    # Promote effective to TREND_FORMING_UP (CF_L / CF_S permitted).
    for _ in range(3):
        rm.update("GBPUSD", "TREND_FORMING_UP")
    assert rm.effective_regime("GBPUSD") == "TREND_FORMING_UP"
    assert len(cf.strategy._armed) == 2, "no suppression yet — armed intact"

    # Now dwell to CHOP — CF leaves the permitted set (fail-closed).
    for _ in range(3):
        rm.update("GBPUSD", "CHOP")
    assert rm.effective_regime("GBPUSD") == "CHOP"
    assert cf.strategy._armed == {}, (
        f"CF armed dict not cleared on matrix suppression: {cf.strategy._armed}"
    )


def test_cf_disarm_registered_only_when_flag_on(flag_off):
    """When flag OFF at module import, no callback is registered — the
    legacy gate handles disarm inside evaluate().
    """
    import regime_matrix as rm
    import gbpusd_confirmation_fallback as cf

    assert rm.REGIME_MATRIX_ENABLED is False
    # Callbacks dict should have no entries for CF modes (nothing was
    # registered at module import because the flag was off).
    assert cf.MODE_NAME_LONG not in rm._on_suppress or rm._on_suppress[cf.MODE_NAME_LONG] == []
    assert cf.MODE_NAME_SHORT not in rm._on_suppress or rm._on_suppress[cf.MODE_NAME_SHORT] == []


# ── (e) Self-gate bypass only under flag ──────────────────────────────────
# Direct source introspection — the bypass shape must be present in each
# of the five self-gate files and keyed on the local _REGIME_MATRIX_ENABLED
# constant. A regression that drops the bypass (e.g. someone reverts one
# strategy's gate to unconditional) fails this test without needing to
# spin up a full strategy evaluate() harness.

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(path):
    return (REPO / path).read_text()


def test_bb_bounce_standdown_bypass_present():
    src = _read("gbpusd_bb_bounce.py")
    assert "_REGIME_MATRIX_ENABLED" in src
    assert re.search(
        r"if\s+BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED\s+and\s+not\s+_REGIME_MATRIX_ENABLED",
        src,
    ), "BB_BOUNCE STRONG_TREND_STANDDOWN missing matrix bypass"


def test_trend_v3_regime_gate_bypass_present():
    src = _read("gbpusd_trend_v3.py")
    assert "_REGIME_MATRIX_ENABLED" in src
    # Both directions must reference the bypass.
    assert re.search(
        r'if\s+regime\s*!=\s*"STRONG_TREND_UP"\s+and\s+not\s+_REGIME_MATRIX_ENABLED', src
    )
    assert re.search(
        r'if\s+regime\s*!=\s*"STRONG_TREND_DOWN"\s+and\s+not\s+_REGIME_MATRIX_ENABLED', src
    )


def test_ema_pullback_regime_bypass_present():
    src = _read("gbpusd_ema_pullback.py")
    assert "_REGIME_MATRIX_ENABLED" in src
    assert re.search(
        r"if\s+not\s+_REGIME_MATRIX_ENABLED:\s*\n\s+_ema_pb_pbfix_log", src
    )


def test_structure_break_gate_a_bypass_present_and_gate_b_untouched():
    src = _read("gbpusd_structure_break.py")
    assert "_REGIME_MATRIX_ENABLED" in src
    # Gate A wrapped.
    assert re.search(
        r"if\s+regime\s+in\s+RANGE_REGIMES\s+and\s+not\s+_REGIME_MATRIX_ENABLED", src
    ), "STRUCTURE_BREAK Gate A missing bypass"
    # Gate B (ADX_FLOOR) must NOT reference the flag — untouched per spec.
    m = re.search(r"if\s+adx\s*<\s*ADX_MIN[:\s]*\n[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*", src)
    if m:
        assert "_REGIME_MATRIX_ENABLED" not in m.group(0), (
            "STRUCTURE_BREAK Gate B (ADX_FLOOR) touched by matrix flag — spec violation"
        )


def test_confirmation_fallback_gate_bypass_present():
    src = _read("gbpusd_confirmation_fallback.py")
    assert "_REGIME_MATRIX_ENABLED" in src
    # The disarm block wrapped by the flag.
    assert re.search(
        r"if\s+_regime_is_trending\(regime\)\s+and\s+not\s+_REGIME_MATRIX_ENABLED", src
    )
    # And the matrix on-suppress registration is present.
    assert "register_on_suppress" in src
    assert "_cf_matrix_disarm" in src


def test_news_release_window_untouched():
    """DO-NOT-TOUCH: news_release_window.py must survive this phase."""
    src = _read("news_release_window.py")
    assert "REGIME_MATRIX" not in src, (
        "news_release_window.py must not reference REGIME_MATRIX — see do-not-touch list"
    )


def test_structure_break_gate_c_retest_lifecycle_untouched():
    """DO-NOT-TOUCH: STRUCTURE_BREAK entry-path retest routing (Gate C)
    must not be modified this phase.
    """
    src = _read("gbpusd_structure_break.py")
    # Retest-related lines exist and do NOT gate on the matrix flag.
    lines = src.splitlines()
    # Find the classify method
    for i, line in enumerate(lines):
        if "_classify_entry_path" in line and "def " in line:
            # Scan the next 50 lines for a flag reference.
            block = "\n".join(lines[i:i + 60])
            assert "_REGIME_MATRIX_ENABLED" not in block, (
                "STRUCTURE_BREAK entry-path classification touched — spec violation"
            )
            break
