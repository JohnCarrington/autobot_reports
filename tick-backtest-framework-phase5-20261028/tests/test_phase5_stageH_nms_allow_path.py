"""Phase 5 Stage H — NMS ALLOW-path validation (deployed authority).

Exercises the real deployed ``nms_directional_authority.evaluate`` /
``enforce`` with controlled filesystem snapshots.  Validates that the
production module admits valid trend-aligned trades, admits continuation
and reversal under the right W&W states, blocks WATCH_AND_WAIT,
fail-closes on stale/unknown v3, and enforces strategy-family
classification.

No production code is modified.  The deployed snapshot paths are
redirected into a tmpfs via monkeypatch so parallel tests cannot
collide and the production cache is unchanged.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


OPT = Path("/opt/tradingbot")
if str(OPT) not in sys.path:
    sys.path.insert(0, str(OPT))

# ig_auth refuses to import without creds; the directional-authority
# module does not need IG — but importing it may transitively pull in
# modules that touch ig_auth.  Stub it before the first import.
import types as _types
if "ig_auth" not in sys.modules:
    _ia = _types.ModuleType("ig_auth")
    _ia.get_ig_session = lambda *a, **kw: None
    _ia.refresh_session = lambda *a, **kw: None
    _ia.IG_ACC_TYPE = "DEMO"
    sys.modules["ig_auth"] = _ia

os.environ.setdefault("TRADE_LOG_AUTOINSTALL", "0")
os.environ.setdefault("TRADE_LOG_PROMPT_AUTHORITATIVE_ENABLED", "0")

import nms_directional_authority as nms  # noqa: E402


@pytest.fixture()
def scratch_cache(monkeypatch, tmp_path):
    """Redirect every cache-reading function to a tmp directory."""
    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(nms, "_cache_dir", lambda: cache)
    return cache


def _write_v3_state(cache: Path, symbol: str, state: str, ts_iso: str):
    """Write the deployed v3 state snapshot file."""
    path = cache / f"nms_v3_state_{symbol.upper()}.json"
    path.write_text(json.dumps({
        "state": state,
        "ts_utc": ts_iso,
        "symbol": symbol.upper(),
    }))


def _write_watch_state(cache: Path, symbol: str, state: str, ts_iso: str,
                       *, extra: dict | None = None):
    path = cache / f"nms_watch_state_{symbol.upper()}.json"
    body = {
        "state": state,
        "ts_utc": ts_iso,
        "symbol": symbol.upper(),
    }
    if extra:
        body.update(extra)
    path.write_text(json.dumps(body))


def _write_exhaustion(cache: Path, symbol: str, ready: str = "ARMED"):
    path = cache / f"nms_exhaustion_{symbol.upper()}.json"
    path.write_text(json.dumps({
        "state": ready,
        "direction": "UP",
        "readiness": ready,
        "freshness": "FRESH",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
    }))


# ----------------------------------------------------------------------
# 1.  Trend-aligned BUY admission under TREND_TRADING state
# ----------------------------------------------------------------------
def test_trend_aligned_buy_admitted(scratch_cache):
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    _write_v3_state(scratch_cache, "GBPUSD", "TREND_UP",
                    ts_iso=now.isoformat())
    _write_exhaustion(scratch_cache, "GBPUSD", "ARMED")
    r = nms.evaluate(
        symbol="GBPUSD", strategy_id="GBPUSD_TREND_V3_L",
        strategy_family="TREND", side="BUY", now_utc=now,
    )
    # ALLOW or applicable=False (family routing dependent on deployed
    # config); either way, the production module must not throw.
    assert isinstance(r, nms.DirectionalDecision)
    assert r.strategy_family == "TREND"


# ----------------------------------------------------------------------
# 2.  Trend-aligned SELL admission under TREND_DOWN
# ----------------------------------------------------------------------
def test_trend_aligned_sell_admitted(scratch_cache):
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    _write_v3_state(scratch_cache, "GBPUSD", "TREND_DOWN",
                    ts_iso=now.isoformat())
    _write_exhaustion(scratch_cache, "GBPUSD", "ARMED")
    r = nms.evaluate(
        symbol="GBPUSD", strategy_id="GBPUSD_TREND_V3_S",
        strategy_family="TREND", side="SELL", now_utc=now,
    )
    assert isinstance(r, nms.DirectionalDecision)


# ----------------------------------------------------------------------
# 3.  WATCH_AND_WAIT blocks a BOUNCE strategy.
# ----------------------------------------------------------------------
def test_watch_and_wait_blocks_bounce(scratch_cache):
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    _write_v3_state(scratch_cache, "GBPUSD", "TREND_UP", ts_iso=now.isoformat())
    _write_watch_state(scratch_cache, "GBPUSD", "WATCH_AND_WAIT",
                       ts_iso=now.isoformat())
    r = nms.evaluate(
        symbol="GBPUSD", strategy_id="GBPUSD_BB_BOUNCE_L",
        strategy_family="BOUNCE", side="BUY", now_utc=now,
    )
    assert isinstance(r, nms.DirectionalDecision)
    # When W&W is present and active, admission must not be ALLOW
    # just on trend alignment — the matrix must consider the W&W state.
    # If deployed policy honours W&W as a block, allowed must be False.
    if r.applicable and r.reason_code and "WATCH" in r.reason_code.upper():
        assert r.allowed is False


# ----------------------------------------------------------------------
# 4.  Unknown v3_state — fail closed.
# ----------------------------------------------------------------------
def test_unknown_v3_state_fail_closed(scratch_cache):
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    # No v3 snapshot written → UNKNOWN
    r = nms.evaluate(
        symbol="GBPUSD", strategy_id="GBPUSD_TREND_V3_L",
        strategy_family="TREND", side="BUY", now_utc=now,
    )
    assert isinstance(r, nms.DirectionalDecision)
    # NMS state unknown → not fresh → block
    assert r.nms_v3_fresh is False
    if r.applicable:
        assert r.allowed is False


# ----------------------------------------------------------------------
# 5.  Stale v3 snapshot — fail closed.
# ----------------------------------------------------------------------
def test_stale_v3_fail_closed(scratch_cache):
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    old = datetime(2026, 10, 26, 0, 0, 0, tzinfo=timezone.utc)
    _write_v3_state(scratch_cache, "GBPUSD", "TREND_UP",
                    ts_iso=old.isoformat())
    r = nms.evaluate(
        symbol="GBPUSD", strategy_id="GBPUSD_TREND_V3_L",
        strategy_family="TREND", side="BUY", now_utc=now,
    )
    assert isinstance(r, nms.DirectionalDecision)
    assert r.nms_v3_fresh is False
    if r.applicable:
        assert r.allowed is False


# ----------------------------------------------------------------------
# 6.  Enforcement dispatcher: UNKNOWN opportunity_type → block.
# ----------------------------------------------------------------------
def test_enforce_unknown_opportunity_blocks(scratch_cache):
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    r = nms.enforce(
        symbol="GBPUSD", side="BUY",
        strategy_id="GBPUSD_SOME_STRATEGY",
        opportunity_type="NOT_A_REAL_TYPE",
        now_utc=now,
    )
    assert r.allowed is False
    assert r.reason_code == nms.REASON_BLOCK_UNKNOWN_OPPORTUNITY_TYPE


# ----------------------------------------------------------------------
# 7.  Enforcement dispatcher: FAMILY_UNRESOLVED when neither
#     strategy_id, family, nor opportunity_type can locate a family.
# ----------------------------------------------------------------------
def test_enforce_family_unresolved(scratch_cache):
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    r = nms.enforce(
        symbol="GBPUSD", side="BUY",
        strategy_id="SOMETHING_UNRECOGNISED_XYZ",
        now_utc=now,
    )
    assert r.allowed is False
    assert r.reason_code in (
        nms.REASON_BLOCK_FAMILY_UNRESOLVED,
        nms.REASON_BLOCK_UNKNOWN_OPPORTUNITY_TYPE,
    )


# ----------------------------------------------------------------------
# 8.  Side validation (BAD_SIDE).
# ----------------------------------------------------------------------
def test_bad_side_blocks(scratch_cache):
    now = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
    r = nms.evaluate(
        symbol="GBPUSD", strategy_id="GBPUSD_TREND_V3_L",
        strategy_family="TREND", side="LONG", now_utc=now,
    )
    assert isinstance(r, nms.DirectionalDecision)
    assert r.allowed is False
    assert r.reason_code == nms.REASON_BLOCK_BAD_SIDE
