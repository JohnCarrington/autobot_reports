"""Tests for the BB_BOUNCE level-distance entry gate (2026-07-25).

Contract:
  * off      — gate skipped; no verdict stamped, no log line, no block.
  * shadow   — verdict computed + logged as WOULD_BLOCK when BLOCK; decision
               path proceeds (return not None).
  * enforce  — BLOCK returns None; PASS proceeds.
  * fail-open — null dist or null/unknown type → FAIL_OPEN (never blocks).
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest


REPO = Path("/opt/tradingbot")


@pytest.fixture()
def bb_module(monkeypatch):
    """Reload gbpusd_bb_bounce with test-controlled env values."""
    def _reload(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import gbpusd_bb_bounce
        importlib.reload(gbpusd_bb_bounce)
        return gbpusd_bb_bounce
    return _reload


# ── Pure helper: verdict logic ─────────────────────────────────────────────
def test_verdict_pass_when_at_level(bb_module):
    bb = bb_module()
    assert bb._bb_level_gate_verdict(
        3.0, "pdh", 8.0, bb.BB_BOUNCE_LEVEL_GATE_TYPES,
    ) == "PASS"


def test_verdict_block_in_open_space(bb_module):
    bb = bb_module()
    assert bb._bb_level_gate_verdict(
        20.0, "pdl", 8.0, bb.BB_BOUNCE_LEVEL_GATE_TYPES,
    ) == "BLOCK"


def test_verdict_fail_open_on_null_dist(bb_module):
    bb = bb_module()
    assert bb._bb_level_gate_verdict(
        None, "pdh", 8.0, bb.BB_BOUNCE_LEVEL_GATE_TYPES,
    ) == "FAIL_OPEN"


def test_verdict_fail_open_on_null_type(bb_module):
    bb = bb_module()
    assert bb._bb_level_gate_verdict(
        3.0, None, 8.0, bb.BB_BOUNCE_LEVEL_GATE_TYPES,
    ) == "FAIL_OPEN"


def test_verdict_fail_open_on_unknown_type(bb_module):
    bb = bb_module()
    # daily_pivot is not in the accepted set
    assert bb._bb_level_gate_verdict(
        3.0, "daily_pivot", 8.0, bb.BB_BOUNCE_LEVEL_GATE_TYPES,
    ) == "FAIL_OPEN"


def test_verdict_boundary_exactly_at_max(bb_module):
    bb = bb_module()
    # dist == max → PASS (inclusive).
    assert bb._bb_level_gate_verdict(
        8.0, "round_00", 8.0, bb.BB_BOUNCE_LEVEL_GATE_TYPES,
    ) == "PASS"
    assert bb._bb_level_gate_verdict(
        8.01, "round_00", 8.0, bb.BB_BOUNCE_LEVEL_GATE_TYPES,
    ) == "BLOCK"


# ── Mode-loading env behaviour ──────────────────────────────────────────────
def test_default_mode_is_shadow(bb_module):
    # No env set → default shadow.
    import os
    for k in ("BB_BOUNCE_LEVEL_GATE_MODE",):
        os.environ.pop(k, None)
    bb = bb_module()
    assert bb.BB_BOUNCE_LEVEL_GATE_MODE == "shadow"


def test_valid_modes_load(bb_module):
    for m in ("off", "shadow", "enforce"):
        bb = bb_module(BB_BOUNCE_LEVEL_GATE_MODE=m)
        assert bb.BB_BOUNCE_LEVEL_GATE_MODE == m


def test_unknown_mode_falls_back_to_shadow(bb_module):
    bb = bb_module(BB_BOUNCE_LEVEL_GATE_MODE="banana")
    assert bb.BB_BOUNCE_LEVEL_GATE_MODE == "shadow"


def test_types_env_parsed_lowercase(bb_module):
    bb = bb_module(BB_BOUNCE_LEVEL_GATE_TYPES="PDH,PDL,ROUND_00")
    assert bb.BB_BOUNCE_LEVEL_GATE_TYPES == frozenset(
        {"pdh", "pdl", "round_00"}
    )


def test_max_dist_env_parsed(bb_module):
    bb = bb_module(BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS="12.5")
    assert bb.BB_BOUNCE_LEVEL_GATE_MAX_DIST_PIPS == pytest.approx(12.5)


# ── Source-shape: gate wired at fire path AFTER level fields ────────────────
SRC = (REPO / "gbpusd_bb_bounce.py").read_text()


def test_gate_lives_after_level_fields_and_before_decision_build():
    lvl_idx = SRC.index("compute_level_distance_fields")
    gate_idx = SRC.index("Level-distance ENTRY GATE (2026-07-25)")
    build_idx = SRC.index("decision = StrategyDecision(")
    assert lvl_idx < gate_idx < build_idx, (
        "gate must run AFTER level fields populate debug_dict AND BEFORE "
        "the StrategyDecision is built"
    )


def test_off_mode_is_zero_evaluation():
    assert 'if BB_BOUNCE_LEVEL_GATE_MODE != "off":' in SRC


def test_shadow_logs_would_block_but_does_not_return_none():
    assert 'WOULD_BLOCK' in SRC
    # The `return None` inside the gate must be gated by enforce+BLOCK,
    # never by shadow alone.
    m = re.search(
        r'if \(BB_BOUNCE_LEVEL_GATE_MODE == "enforce"\s*\n\s*and _lg_verdict == "BLOCK"\):\s*\n[^\n]*\n\s*return None',
        SRC,
    )
    assert m, "enforce+BLOCK must be the only return None path in the gate"


def test_log_line_format_matches_spec():
    # Format required: [BB-LEVEL-GATE] verdict=X dist=Y type=Z mode=W
    assert '"[BB-LEVEL-GATE] verdict=%s dist=%s type=%s mode=%s "' in SRC


def test_fail_open_survives_enforce_mode():
    # In enforce, FAIL_OPEN is NOT BLOCK — return None gate is verdict=="BLOCK".
    # A regression that returned None on FAIL_OPEN would show up as a broader
    # match on the return-None branch (any verdict). Check the branch condition
    # is strict.
    m = re.search(
        r'if \(BB_BOUNCE_LEVEL_GATE_MODE == "enforce"\s*\n\s*and _lg_verdict == "BLOCK"\):',
        SRC,
    )
    assert m is not None


# ── env layered config ──────────────────────────────────────────────────────
def test_env_layered_declares_shadow_default():
    text = (REPO / "env" / "40-gates.env").read_text()
    assert re.search(r'^BB_BOUNCE_LEVEL_GATE_MODE=shadow\s*$', text, re.M)
