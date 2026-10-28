"""Phase 4 — standalone BB Bounce admission tests.

Exercise the DEPLOYED `_phase2b_block_order()` logic in `/opt/bb_bounce/
open_sb_now.py` under controlled snapshot states. These tests cover:

  * WATCH_AND_WAIT fail-closed on unavailable / stale / malformed snapshot
  * WATCH_AND_WAIT state BLOCK
  * REVERSAL_CONFIRMED BLOCK (BB Bounce is not qualifying reversal)
  * CONTINUATION_CONFIRMED fall-through to Phase 2B
  * Phase 2B v3_state UNKNOWN fail-closed
  * Phase 2B RANGE / NORMAL allow both
  * Phase 2B counter-trend blocked without exhaustion
  * Phase 2B counter-trend allowed with CONFIRMED exhaustion

The test uses the real production module imported from `/opt/bb_bounce/`
with temporary snapshot cache directories so no live production state is
touched. Env flags are set within the test for Phase 4 unified-authority
behaviour.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest


_BBB_SRC = "/opt/bb_bounce"


@pytest.fixture
def temp_cache(tmp_path, monkeypatch):
    """Isolated cache dir pointing session_trend_guard + open_sb_now at a
    scratch directory so test writes don't collide with the live snapshot."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("SESSION_TREND_SNAPSHOT_DIR", str(cache))
    # open_sb_now hard-codes /opt/tradingbot/cache for exhaustion/W&W paths.
    # We monkeypatch the module-level constants instead.
    return cache


@pytest.fixture
def bbb_admission(monkeypatch, temp_cache):
    """Return the deployed `_phase2b_block_order` with cache paths rewired
    to a scratch directory."""
    sys.path.insert(0, _BBB_SRC)
    # Clean imports so monkeypatch takes effect.
    for mod in list(sys.modules):
        if mod in ("open_sb_now", "session_trend_guard"):
            del sys.modules[mod]
    # Minimal env the module needs at import time.
    monkeypatch.setenv("IG_USERNAME", "x")
    monkeypatch.setenv("IG_PASSWORD", "x")
    monkeypatch.setenv("IG_API_KEY", "x")
    import open_sb_now  # type: ignore
    # Rewire file paths to the scratch cache
    monkeypatch.setattr(open_sb_now, "_SESSION_TREND_PATH",
                        str(temp_cache / "session_trend_{sym}.json"), raising=True)
    monkeypatch.setattr(open_sb_now, "_H1_MACD_TIRING_PATH",
                        str(temp_cache / "h1_macd_tiring_{sym}.json"), raising=True)
    monkeypatch.setattr(open_sb_now, "_WATCH_STATE_PATH",
                        str(temp_cache / "nms_watch_state_{sym}.json"), raising=True)
    monkeypatch.setattr(open_sb_now, "_EXHAUSTION_PATH",
                        str(temp_cache / "nms_exhaustion_{sym}.json"), raising=True)
    # Enable deployed flags
    monkeypatch.setenv("NMS_WATCH_AND_WAIT_ENABLED", "1")
    monkeypatch.setenv("NMS_UNIFIED_DIRECTIONAL_AUTHORITY_ENABLED", "1")
    return open_sb_now


def _write(p: Path, body: dict) -> None:
    p.write_text(json.dumps(body))


def _ts(delta_s: int = 0) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delta_s)).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# WATCH_AND_WAIT first-level checks (fail-closed on data problems)
# ─────────────────────────────────────────────────────────────────────────────

def test_watch_unavailable_blocks(bbb_admission, temp_cache):
    # No W&W snapshot file at all → fail-closed BLOCK.
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "BUY")
    assert blocked
    assert reason.startswith("block:watch_snapshot_unavailable")


def test_watch_stale_blocks(bbb_admission, temp_cache):
    # Stale W&W snapshot (> 15 min) → BLOCK.
    _write(temp_cache / "nms_watch_state_GBPUSD.json", {
        "state": "TREND_TRADING",
        "evaluation_ts": _ts(delta_s=-3600),  # 1 hour old
    })
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "SELL")
    assert blocked
    assert reason.startswith("block:watch_snapshot_stale")


def test_watch_malformed_blocks(bbb_admission, temp_cache):
    _write(temp_cache / "nms_watch_state_GBPUSD.json", {
        "state": "WHATEVER", "evaluation_ts": "garbage"
    })
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "BUY")
    assert blocked
    assert "watch_snapshot_malformed" in reason or "watch_and_wait" not in reason


def test_watch_and_wait_state_blocks(bbb_admission, temp_cache):
    _write(temp_cache / "nms_watch_state_GBPUSD.json", {
        "state": "WATCH_AND_WAIT",
        "watched_trend_direction": "UP",
        "evaluation_ts": _ts(),
    })
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "BUY")
    assert blocked
    assert reason.startswith("block:watch_and_wait")


def test_reversal_confirmed_blocks_bb(bbb_admission, temp_cache):
    """Operator ruling: during REVERSAL_CONFIRMED, standalone BB bounce
    is NOT the qualifying reversal oracle (QM_REVERSAL is) and must block."""
    _write(temp_cache / "nms_watch_state_GBPUSD.json", {
        "state": "REVERSAL_CONFIRMED",
        "watched_trend_direction": "UP",
        "reversal_oracle": "QM_REVERSAL",
        "reversal_direction": "DOWN",
        "evaluation_ts": _ts(),
    })
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "SELL")
    assert blocked


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2B rulebook (W&W == TREND_TRADING or CONTINUATION_CONFIRMED)
# ─────────────────────────────────────────────────────────────────────────────

def _wnw_trend_trading(temp_cache):
    _write(temp_cache / "nms_watch_state_GBPUSD.json", {
        "state": "TREND_TRADING",
        "evaluation_ts": _ts(),
    })


def test_phase2b_v3_unknown_fails_closed(bbb_admission, temp_cache):
    _wnw_trend_trading(temp_cache)
    # No session_trend snapshot → UNKNOWN → BLOCK.
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "BUY")
    assert blocked
    assert "block" in reason


def test_phase2b_range_allows_both_directions(bbb_admission, temp_cache):
    _wnw_trend_trading(temp_cache)
    _write(temp_cache / "session_trend_GBPUSD.json", {
        "v3_state": "RANGE", "data_fresh": True, "evaluation_ts": _ts(),
    })
    for d in ("BUY", "SELL"):
        blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", d)
        assert not blocked, reason


def test_phase2b_with_trend_allows(bbb_admission, temp_cache):
    _wnw_trend_trading(temp_cache)
    _write(temp_cache / "session_trend_GBPUSD.json", {
        "v3_state": "STRONG_UP", "data_fresh": True, "evaluation_ts": _ts(),
    })
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "BUY")
    assert not blocked, reason


def test_phase2b_counter_trend_without_exhaustion_blocks(bbb_admission, temp_cache):
    _wnw_trend_trading(temp_cache)
    _write(temp_cache / "session_trend_GBPUSD.json", {
        "v3_state": "STRONG_UP", "data_fresh": True, "evaluation_ts": _ts(),
    })
    # No exhaustion snapshot → BLOCK counter-trend SELL vs STRONG_UP.
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "SELL")
    assert blocked


def test_phase2b_counter_trend_with_matching_exhaustion_allows(bbb_admission, temp_cache):
    _wnw_trend_trading(temp_cache)
    _write(temp_cache / "session_trend_GBPUSD.json", {
        "v3_state": "STRONG_UP", "data_fresh": True, "evaluation_ts": _ts(),
    })
    _write(temp_cache / "nms_exhaustion_GBPUSD.json", {
        "exhaustion_state": "EXHAUSTION_CONFIRMED",
        "exhaustion_direction": "BUYING_EXHAUSTION",
        "readiness": "READY",
        "freshness": "FRESH",
        "evaluation_ts": _ts(),
    })
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "SELL")
    assert not blocked, reason


def test_phase2b_counter_trend_with_wrong_direction_exhaustion_blocks(bbb_admission, temp_cache):
    _wnw_trend_trading(temp_cache)
    _write(temp_cache / "session_trend_GBPUSD.json", {
        "v3_state": "STRONG_UP", "data_fresh": True, "evaluation_ts": _ts(),
    })
    # Exhaustion exists but in the WRONG direction for a counter-trend SELL.
    _write(temp_cache / "nms_exhaustion_GBPUSD.json", {
        "exhaustion_state": "EXHAUSTION_CONFIRMED",
        "exhaustion_direction": "SELLING_EXHAUSTION",
        "readiness": "READY",
        "freshness": "FRESH",
        "evaluation_ts": _ts(),
    })
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "SELL")
    assert blocked


def test_phase2b_counter_trend_with_stale_exhaustion_blocks(bbb_admission, temp_cache):
    _wnw_trend_trading(temp_cache)
    _write(temp_cache / "session_trend_GBPUSD.json", {
        "v3_state": "STRONG_DOWN", "data_fresh": True, "evaluation_ts": _ts(),
    })
    _write(temp_cache / "nms_exhaustion_GBPUSD.json", {
        "exhaustion_state": "EXHAUSTION_CONFIRMED",
        "exhaustion_direction": "SELLING_EXHAUSTION",
        "readiness": "READY",
        "freshness": "FRESH",
        "evaluation_ts": _ts(delta_s=-3600),  # stale
    })
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "BUY")
    assert blocked


def test_continuation_confirmed_falls_through_phase2b(bbb_admission, temp_cache):
    """CONTINUATION_CONFIRMED is a valid W&W pass-through state — admission
    then re-evaluates Phase 2B rules."""
    _write(temp_cache / "nms_watch_state_GBPUSD.json", {
        "state": "CONTINUATION_CONFIRMED",
        "watched_trend_direction": "UP",
        "evaluation_ts": _ts(),
    })
    _write(temp_cache / "session_trend_GBPUSD.json", {
        "v3_state": "STRONG_UP", "data_fresh": True, "evaluation_ts": _ts(),
    })
    # Should allow BUY (with-trend) under CONTINUATION_CONFIRMED.
    blocked, reason = bbb_admission._phase2b_block_order("GBPUSD", "BUY")
    assert not blocked, reason


# ─────────────────────────────────────────────────────────────────────────────
# No deployed state is written: this test MUST not touch /opt/tradingbot/cache
# ─────────────────────────────────────────────────────────────────────────────

def test_no_production_cache_writes(bbb_admission, temp_cache):
    prod_cache = Path("/opt/tradingbot/cache")
    pre = {p.name for p in prod_cache.glob("*.json") if p.is_file()} if prod_cache.exists() else set()
    bbb_admission._phase2b_block_order("GBPUSD", "BUY")
    post = {p.name for p in prod_cache.glob("*.json") if p.is_file()} if prod_cache.exists() else set()
    assert pre == post
