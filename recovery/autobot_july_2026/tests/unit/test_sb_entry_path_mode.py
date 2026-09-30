"""Tests for the SB_ENTRY_PATH_MODE operator gate (2026-07-25).

The gate overlays the classifier output in gbpusd_structure_break.evaluate:
  current       — no-op (byte-identical to prior CHASE-hardcode behaviour)
  prefer_retest — would-be CHASE routed via retest machinery
  retest_only   — would-be CHASE skipped with [SB-ENTRY] skipped=no_retest

The kill switch (STRUCTURE_BREAK_RETEST_ENTRY_ENABLED=0) has priority over
the mode; when off, mode is a no-op.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path


REPO = Path("/opt/tradingbot")
SB_SRC = (REPO / "gbpusd_structure_break.py").read_text()


# ── Env constant loading ───────────────────────────────────────────────────
def _reload_with_mode(monkeypatch, mode_val):
    if mode_val is None:
        monkeypatch.delenv("SB_ENTRY_PATH_MODE", raising=False)
    else:
        monkeypatch.setenv("SB_ENTRY_PATH_MODE", mode_val)
    import gbpusd_structure_break as sb
    importlib.reload(sb)
    return sb


def test_default_mode_is_current(monkeypatch):
    sb = _reload_with_mode(monkeypatch, None)
    assert sb.SB_ENTRY_PATH_MODE == "current"


def test_valid_modes_load(monkeypatch):
    for m in ("current", "prefer_retest", "retest_only"):
        sb = _reload_with_mode(monkeypatch, m)
        assert sb.SB_ENTRY_PATH_MODE == m


def test_unknown_mode_falls_back_to_current(monkeypatch):
    sb = _reload_with_mode(monkeypatch, "banana")
    assert sb.SB_ENTRY_PATH_MODE == "current"


def test_mode_matches_case_insensitive_upper(monkeypatch):
    sb = _reload_with_mode(monkeypatch, "PREFER_RETEST")
    assert sb.SB_ENTRY_PATH_MODE == "prefer_retest"


# ── Source-shape assertions on evaluate()'s mode overlay ───────────────────
def test_universal_sb_entry_log_line_present():
    # A single [SB-ENTRY] log formatter that fires on every path with the
    # spec keys mode= path_taken= promoted= regime=.
    assert '"[SB-ENTRY] mode=%s path_taken=%s promoted=%s regime=%s%s"' in SB_SRC


def test_skip_no_retest_marker_present():
    assert 'skipped=no_retest' in SB_SRC


def test_retest_only_skip_short_circuits_with_return_none():
    assert re.search(
        r'if\s+_mode_skipped_no_retest:\s*\n\s+return\s+None', SB_SRC
    ), "retest_only skip must short-circuit with return None"


# ── Pure helper: _apply_entry_path_mode — the byte-identity guarantee ──────
def test_mode_current_pure_helper_is_no_op(monkeypatch):
    sb = _reload_with_mode(monkeypatch, "current")
    # Fixed inputs — every classifier output must survive untouched.
    for path in ("CHASE", "RETEST"):
        for kill in (False, True):
            out_path, skipped, reason = sb._apply_entry_path_mode(
                entry_path=path,
                kill_switch_forced_chase=kill,
                mode="current",
                base_reason="probe_reason",
            )
            assert out_path == path, (path, kill, out_path)
            assert skipped is False, (path, kill, skipped)
            assert reason == "probe_reason", (path, kill, reason)


def test_mode_prefer_retest_routes_chase_to_retest(monkeypatch):
    sb = _reload_with_mode(monkeypatch, "prefer_retest")
    out_path, skipped, reason = sb._apply_entry_path_mode(
        entry_path="CHASE",
        kill_switch_forced_chase=False,
        mode="prefer_retest",
        base_reason="genuine_strong_trend",
    )
    assert out_path == "RETEST"
    assert skipped is False
    assert "mode=prefer_retest" in reason
    # RETEST inputs untouched.
    out_path, skipped, reason = sb._apply_entry_path_mode(
        entry_path="RETEST",
        kill_switch_forced_chase=False,
        mode="prefer_retest",
        base_reason="trend_forming",
    )
    assert (out_path, skipped, reason) == ("RETEST", False, "trend_forming")


def test_mode_retest_only_skips_chase(monkeypatch):
    sb = _reload_with_mode(monkeypatch, "retest_only")
    out_path, skipped, reason = sb._apply_entry_path_mode(
        entry_path="CHASE",
        kill_switch_forced_chase=False,
        mode="retest_only",
        base_reason="genuine_strong_trend",
    )
    assert skipped is True
    assert "mode=retest_only:no_retest" in reason
    # RETEST inputs untouched even in retest_only.
    out_path, skipped, reason = sb._apply_entry_path_mode(
        entry_path="RETEST",
        kill_switch_forced_chase=False,
        mode="retest_only",
        base_reason="trend_forming",
    )
    assert (out_path, skipped, reason) == ("RETEST", False, "trend_forming")


def test_kill_switch_beats_every_mode(monkeypatch):
    sb = _reload_with_mode(monkeypatch, "retest_only")
    # Even in retest_only, kill-switch=True → mode is no-op.
    for mode in ("current", "prefer_retest", "retest_only"):
        out_path, skipped, reason = sb._apply_entry_path_mode(
            entry_path="CHASE",
            kill_switch_forced_chase=True,
            mode=mode,
            base_reason="kill_switch_off",
        )
        assert (out_path, skipped, reason) == ("CHASE", False, "kill_switch_off")


def test_kill_switch_precedence_guard_present_in_evaluate():
    # Callsite must still pre-compute _kill_switch_forced_chase and pass it in.
    assert "_kill_switch_forced_chase = (not RETEST_ENTRY_ENABLED)" in SB_SRC
    assert "kill_switch_forced_chase=_kill_switch_forced_chase" in SB_SRC


# ── Env-file placement (STEP 2) ────────────────────────────────────────────
def test_default_env_line_committed_to_40_gates():
    env_path = REPO / "env" / "40-gates.env"
    assert env_path.exists(), "env/40-gates.env missing"
    text = env_path.read_text()
    assert re.search(r'^SB_ENTRY_PATH_MODE=current\s*$', text, re.M), (
        "env/40-gates.env must declare SB_ENTRY_PATH_MODE=current"
    )
