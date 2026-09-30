"""Unit tests for regime_matrix (Phase 2).

Covers: matrix lookup, fail-closed on unknown, dwell absorbs sub-N flicker,
fast-lane bypass, on-suppress callbacks, anti-drift dispatch-site
introspection, byte-identical flag-off behaviour.

Run: pytest tests/unit/test_regime_matrix.py -q
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOBOT_PATH = REPO_ROOT / "autobot.py"


# ── Fixture: reload regime_matrix under a fresh env each test ──────────────

@pytest.fixture
def matrix_on(monkeypatch):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
    monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", "/tmp/test_regime_matrix.jsonl")
    if "regime_matrix" in sys.modules:
        del sys.modules["regime_matrix"]
    import regime_matrix
    regime_matrix._reset_state_for_tests()
    return regime_matrix


@pytest.fixture
def matrix_off(monkeypatch):
    monkeypatch.setenv("REGIME_MATRIX_ENABLED", "0")
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", "/tmp/test_regime_matrix_off.jsonl")
    if "regime_matrix" in sys.modules:
        del sys.modules["regime_matrix"]
    import regime_matrix
    regime_matrix._reset_state_for_tests()
    return regime_matrix


# ── (a) Matrix lookup — fail-closed on unknown ────────────────────────────

def test_matrix_permits_range_rotation(matrix_on):
    m = matrix_on
    # Prime dwell to promote RANGE_ROTATION
    for _ in range(3):
        m.update("GBPUSD", "RANGE_ROTATION")
    assert m.effective_regime("GBPUSD") == "RANGE_ROTATION"
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_L") is True
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_S") is True
    assert m.permits("GBPUSD", "GBPUSD_TREND_V3_L") is False


def test_matrix_permits_strong_trend_up(matrix_on):
    """STRONG_TREND_UP permits the LONG trend suite. As of the 2026-07-09
    amendment BB_BOUNCE_L AND BB_BOUNCE_S are also permitted here — the
    strategy is table-permitted in every trend regime; only opposite-
    direction TREND modes are blocked.
    """
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "STRONG_TREND_UP")
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"
    for mode in ("GBPUSD_EMA_PULLBACK_L", "GBPUSD_TREND_V3_L",
                 "GBPUSD_STRUCTURE_BREAK_L", "GBPUSD_CONFIRMATION_FALLBACK_L",
                 "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S"):
        assert m.permits("GBPUSD", mode) is True, mode
    # Opposite-direction trend modes remain blocked.
    for mode in ("GBPUSD_EMA_PULLBACK_S", "GBPUSD_TREND_V3_S"):
        assert m.permits("GBPUSD", mode) is False, mode


def test_matrix_fail_closed_on_chop(matrix_on):
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "CHOP")
    assert m.effective_regime("GBPUSD") == "CHOP"
    # Every mode blocked in CHOP.
    for mode in ("GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
                 "GBPUSD_TREND_V3_L", "GBPUSD_EMA_PULLBACK_L",
                 "GBPUSD_STRUCTURE_BREAK_L", "GBPUSD_CONFIRMATION_FALLBACK_L"):
        assert m.permits("GBPUSD", mode) is False, mode


def test_matrix_fail_closed_on_unrecognised(matrix_on):
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "MYSTERY_LABEL")
    assert m.effective_regime("GBPUSD") == "MYSTERY_LABEL"
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_L") is False


def test_matrix_fail_closed_before_first_update(matrix_on):
    m = matrix_on
    # No update() calls yet — effective is None → empty permitted set.
    assert m.effective_regime("GBPUSD") is None
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_L") is False


# ── (b) Dwell absorbs sub-N flicker ───────────────────────────────────────

def test_dwell_absorbs_single_bar_flicker(matrix_on):
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "STRONG_TREND_UP")
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"
    # One CHOP bar should NOT flip the effective state.
    m.update("GBPUSD", "CHOP")
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"
    # Return to trend confirms nothing changed.
    m.update("GBPUSD", "STRONG_TREND_UP")
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"


def test_dwell_absorbs_alternating_flicker(matrix_on):
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "STRONG_TREND_UP")
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"
    # Alternating STRONG/CHOP/STRONG/CHOP — dwell never accumulates.
    for raw in ("CHOP", "STRONG_TREND_UP", "CHOP", "STRONG_TREND_UP", "CHOP"):
        m.update("GBPUSD", raw)
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"


def test_dwell_promotes_after_n_consecutive(matrix_on):
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "STRONG_TREND_UP")
    # 3 consecutive CHOP bars should now promote CHOP.
    m.update("GBPUSD", "CHOP")
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"  # after 1 bar
    m.update("GBPUSD", "CHOP")
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"  # after 2 bars
    m.update("GBPUSD", "CHOP")
    assert m.effective_regime("GBPUSD") == "CHOP"  # 3 consecutive


# ── (c) Fast lane bypasses dwell ──────────────────────────────────────────

def test_fast_lane_promotes_immediately(matrix_on):
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "RANGE_ROTATION")
    assert m.effective_regime("GBPUSD") == "RANGE_ROTATION"
    # Simulate range-break promotion — engine emits STRONG_TREND_UP with
    # BOTH range_break_promoted and range_exit_breakout set. Should
    # transition immediately without waiting for dwell.
    m.update(
        "GBPUSD", "STRONG_TREND_UP",
        range_break_promoted=True, range_exit_breakout=True,
        regime_label_path="range_break_promote",
    )
    assert m.effective_regime("GBPUSD") == "STRONG_TREND_UP"


def test_fast_lane_requires_both_signals(matrix_on):
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "RANGE_ROTATION")
    # Only one of the two signals — must not fast-lane.
    m.update("GBPUSD", "STRONG_TREND_UP", range_break_promoted=True,
             range_exit_breakout=False)
    assert m.effective_regime("GBPUSD") == "RANGE_ROTATION"


# ── (d) Dispatch suppression — anti-drift + logging ───────────────────────

def test_log_suppression_no_op_when_off(matrix_off, tmp_path, monkeypatch):
    log = tmp_path / "matrix_off.jsonl"
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", str(log))
    if "regime_matrix" in sys.modules:
        del sys.modules["regime_matrix"]
    import regime_matrix
    regime_matrix._reset_state_for_tests()
    # permits() returns True unconditionally when flag off.
    assert regime_matrix.permits("GBPUSD", "MYSTERY") is True
    regime_matrix.log_suppression("GBPUSD", "GBPUSD_BB_BOUNCE")
    # No file written.
    assert not log.exists()


def test_anti_drift_all_dispatch_sites_have_permits_call():
    """Every `_on_5m_close_<strategy>` method on AutoBot must contain a
    `regime_matrix.permits(...)` call — a new strategy added without the
    hook must fail this test.
    """
    src = AUTOBOT_PATH.read_text()
    tree = ast.parse(src)
    autobot_cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AutoBot":
            autobot_cls = node
            break
    assert autobot_cls is not None, "AutoBot class not found in autobot.py"

    callback_methods = [
        item for item in autobot_cls.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name.startswith("_on_5m_close_")
    ]
    assert len(callback_methods) >= 6, (
        f"Expected ≥6 _on_5m_close_* strategy callbacks on AutoBot; "
        f"found {len(callback_methods)}: {[m.name for m in callback_methods]}"
    )
    for method in callback_methods:
        method_src = ast.unparse(method)
        assert "regime_matrix.permits" in method_src, (
            f"{method.name} missing regime_matrix.permits(...) call — "
            f"dispatch hook drift"
        )


# ── (e) On-suppress callback fires on transition ──────────────────────────

def test_on_suppress_fires_when_mode_leaves_permitted_set(matrix_on):
    m = matrix_on
    fired = []
    m.register_on_suppress("GBPUSD_CONFIRMATION_FALLBACK_L", lambda sym: fired.append(sym))
    # Promote STRONG_TREND_UP — CF_L is permitted.
    for _ in range(3):
        m.update("GBPUSD", "STRONG_TREND_UP")
    assert not fired, "callback fired before mode left permitted set"
    # Now dwell to CHOP — CF_L leaves permitted set.
    for _ in range(3):
        m.update("GBPUSD", "CHOP")
    assert fired == ["GBPUSD"], f"callback not fired on transition: {fired}"


def test_on_suppress_does_not_fire_when_still_permitted(matrix_on):
    m = matrix_on
    fired = []
    m.register_on_suppress("GBPUSD_EMA_PULLBACK_L", lambda sym: fired.append(sym))
    for _ in range(3):
        m.update("GBPUSD", "TREND_FORMING_UP")
    # Transition to STRONG_TREND_UP — EMA_PULLBACK_L still permitted.
    for _ in range(3):
        m.update("GBPUSD", "STRONG_TREND_UP")
    assert fired == [], "callback fired despite mode remaining permitted"


# ── 2026-07-09 amendment: BB_BOUNCE ungated except CHOP/UNKNOWN ───────────
# SUPERSEDES the b237921 "exhausted-trend BB_BOUNCE fade window" and the
# 4ee95a9 decel-disjunct extension that lived here between 2026-07-08 and
# 2026-07-09. The prior tests asserted:
#   * exhaust_streak / raw_divergence flip permits(BB) True in trend
#   * healthy trend keeps permits(BB) False
#   * fade-knob=0 restores base table
# Operator design (2026-07-09) replaced all of that with an unconditional
# permitted entry for BB_BOUNCE_L/S in every trend regime AND
# RANGE_ROTATION. The tests below are the direct replacements of the
# superseded cases — each docstring names the case it replaces and the
# commit that introduced it, so the git blame keeps history readable.

def _prime_trend(m, label="STRONG_TREND_UP"):
    for _ in range(3):
        m.update("GBPUSD", label)
    assert m.effective_regime("GBPUSD") == label


def test_bb_bounce_permitted_in_all_four_trend_regimes(matrix_on):
    """Replaces test_healthy_trend_bb_bounce_not_permitted (b237921):
    prior test asserted healthy trend blocks BB fires; the new table
    permits BB in every trend regime regardless of exhaustion.
    """
    m = matrix_on
    for label in ("TREND_FORMING_UP", "TREND_FORMING_DOWN",
                  "STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        m._reset_state_for_tests()
        _prime_trend(m, label)
        # Healthy — streak 0, no divergence, no decel.
        m.update("GBPUSD", label, hist_freshness_fail_count=0,
                 h1_decel_streak=0)
        assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_L") is True, label
        assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_S") is True, label
        # Same-direction trend modes remain permitted alongside.
        if "UP" in label:
            assert m.permits("GBPUSD", "GBPUSD_EMA_PULLBACK_L") is True, label
        else:
            assert m.permits("GBPUSD", "GBPUSD_EMA_PULLBACK_S") is True, label


def test_bb_bounce_permitted_in_range_rotation(matrix_on):
    """RANGE_ROTATION still permits BB_BOUNCE_L/S (was already true under
    the base table; retained here for the ungated-except-CHOP invariant).
    """
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "RANGE_ROTATION")
    assert m.effective_regime("GBPUSD") == "RANGE_ROTATION"
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_L") is True
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_S") is True
    # Trend modes remain not permitted in RANGE_ROTATION.
    assert m.permits("GBPUSD", "GBPUSD_TREND_V3_L") is False


def test_bb_bounce_blocked_in_chop_and_unknown(matrix_on):
    """CHOP and unknown labels remain the ONLY gates on BB_BOUNCE. Replaces
    the CHOP branch of test_chop_unchanged_by_amendment (b237921) — same
    assertion, motivation now inverted (CHOP is the entire gate, not one
    exception to a permissive trend rule).
    """
    m = matrix_on
    for _ in range(3):
        m.update("GBPUSD", "CHOP", hist_freshness_fail_count=99,
                 h1_decel_streak=99)
    assert m.effective_regime("GBPUSD") == "CHOP"
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_L") is False
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_S") is False
    # Trend modes also blocked in CHOP — the empty permitted set is total.
    assert m.permits("GBPUSD", "GBPUSD_EMA_PULLBACK_L") is False
    assert m.permits("GBPUSD", "GBPUSD_TREND_V3_L") is False

    # Unknown label — never listed in MATRIX. Fail-closed for every mode.
    m._reset_state_for_tests()
    for _ in range(3):
        m.update("GBPUSD", "MYSTERY_LABEL", hist_freshness_fail_count=99,
                 h1_decel_streak=99)
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_L") is False
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_S") is False


def test_exhausted_flag_has_no_effect_on_any_permitted_set(matrix_on):
    """Replaces the b237921 tests
      test_exhaust_streak_permits_bb_bounce_in_trend,
      test_exhaust_raw_divergence_permits_bb_bounce_without_streak,
      test_exhaust_window_closes_when_streak_resets_and_raw_reagrees
    which asserted the exhausted flag flips permits(BB) True in trend
    regimes and False when the window closes. Now permits() reads only
    effective_regime; the flag flipping True or False must NOT change
    the permitted set in any regime.
    """
    m = matrix_on
    scenarios = [
        # (label, streak, decel_streak) — exhausted flag toggles True/False
        # across these; permits(BB) must be identical for the same label.
        ("STRONG_TREND_UP",   0, 0),
        ("STRONG_TREND_UP",   9, 0),
        ("STRONG_TREND_UP",   0, 9),
        ("TREND_FORMING_DOWN",0, 0),
        ("TREND_FORMING_DOWN",9, 9),
        ("RANGE_ROTATION",    0, 0),
        ("RANGE_ROTATION",    9, 9),
    ]
    # Group scenarios by label; assert permits(BB) is identical across
    # streak/decel choices for that label.
    from collections import defaultdict
    by_label: dict = defaultdict(list)
    for label, streak, decel in scenarios:
        m._reset_state_for_tests()
        for _ in range(3):
            m.update("GBPUSD", label,
                     hist_freshness_fail_count=streak,
                     h1_decel_streak=decel)
        for mode in ("GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
                     "GBPUSD_EMA_PULLBACK_L", "GBPUSD_EMA_PULLBACK_S",
                     "GBPUSD_TREND_V3_L", "GBPUSD_TREND_V3_S"):
            by_label[(label, mode)].append(m.permits("GBPUSD", mode))
    for (label, mode), results in by_label.items():
        assert len(set(results)) == 1, (
            f"permits({label!r}, {mode!r}) varies with exhaustion inputs "
            f"— should be constant. saw={results}"
        )


def test_fade_knob_now_has_no_effect_on_permits(monkeypatch):
    """Replaces test_fade_knob_off_restores_prior_table (b237921) — the
    knob previously toggled exhausted() as an escape hatch. Both settings
    must now produce identical permits() results because permits()
    no longer reads the exhausted flag.
    """
    def _permits_snapshot(fade_flag_value: str) -> dict:
        monkeypatch.setenv("REGIME_MATRIX_ENABLED", "1")
        monkeypatch.setenv("REGIME_MATRIX_DWELL_N", "3")
        monkeypatch.setenv("REGIME_MATRIX_EXHAUSTED_FADE_ENABLED", fade_flag_value)
        monkeypatch.setenv("REGIME_MATRIX_LOG_PATH",
                           f"/tmp/test_matrix_fade_{fade_flag_value}.jsonl")
        if "regime_matrix" in sys.modules:
            del sys.modules["regime_matrix"]
        import regime_matrix as m  # noqa
        m._reset_state_for_tests()
        for _ in range(3):
            m.update("GBPUSD", "STRONG_TREND_UP",
                     hist_freshness_fail_count=5, h1_decel_streak=5)
        return {
            mode: m.permits("GBPUSD", mode)
            for mode in ("GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
                         "GBPUSD_EMA_PULLBACK_L", "GBPUSD_TREND_V3_L")
        }
    on  = _permits_snapshot("1")
    off = _permits_snapshot("0")
    assert on == off, (
        "REGIME_MATRIX_EXHAUSTED_FADE_ENABLED should have no effect on "
        f"permits() — knob leaks: on={on} off={off}"
    )
    # And in that regime BB_BOUNCE is table-permitted regardless.
    assert on["GBPUSD_BB_BOUNCE_L"] is True
    assert on["GBPUSD_BB_BOUNCE_S"] is True


def test_flag_off_byte_identical_ignores_new_kwarg():
    """Flag OFF: update() is a no-op, permits() returns True unconditionally.
    Neither hist_freshness_fail_count nor h1_decel_streak must alter this.
    """
    if "regime_matrix" in sys.modules:
        del sys.modules["regime_matrix"]
    os.environ["REGIME_MATRIX_ENABLED"] = "0"
    import regime_matrix as m
    m._reset_state_for_tests()
    m.update("GBPUSD", "STRONG_TREND_UP", hist_freshness_fail_count=999,
             h1_decel_streak=999)
    assert m.permits("GBPUSD", "GBPUSD_BB_BOUNCE_L") is True
    assert m.effective_regime("GBPUSD") is None
    # cleanup for other tests
    os.environ.pop("REGIME_MATRIX_ENABLED", None)


# ── Telemetry retention: exhaustion still logged, still on jsonl ─────────
def test_exhaustion_telemetry_still_logged_though_gates_nothing(matrix_on,
                                                                monkeypatch,
                                                                tmp_path):
    """Even though permits() ignores exhausted / exhaust_streak /
    exhaust_decel_streak, they must still land in the jsonl rows so
    calibration downstream keeps joining on them.
    """
    log_path = tmp_path / "matrix_tel.jsonl"
    monkeypatch.setenv("REGIME_MATRIX_LOG_PATH", str(log_path))
    if "regime_matrix" in sys.modules:
        del sys.modules["regime_matrix"]
    import regime_matrix as m
    m._reset_state_for_tests()
    for _ in range(3):
        m.update("GBPUSD", "STRONG_TREND_UP",
                 hist_freshness_fail_count=7, h1_decel_streak=4)
    import json as _json
    rows = [_json.loads(l) for l in log_path.read_text().splitlines() if l]
    assert rows, "no matrix telemetry rows written"
    last = rows[-1]
    assert last["exhausted"] is True
    assert last["exhaust_streak"] == 7
    assert last["exhaust_decel_streak"] == 4
