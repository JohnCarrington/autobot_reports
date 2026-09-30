#!/usr/bin/env python3
"""Unit + integration tests for briefing.v5_pia Phase 3 (reader + executor).

Coverage:

  Reader (briefing/v5_pia/reader.py):
    - active_session_for time-of-day boundaries
    - load_v5_briefing missing file → None + log
    - load_v5_briefing unparseable JSON → None + log
    - load_v5_briefing schema-invalid → None + log (Pydantic ValidationError)
    - load_v5_briefing well-formed ARMED → BriefingV5 instance
    - is_briefing_active future / past
    - is_briefing_armed enforces both state + direction

  Executor (briefing/v5_pia/executor.py):
    - PARALLEL_MODE off → silent return None
    - No briefing → None
    - STAND_ASIDE briefing → None + abstain log
    - Expired briefing → None + abstain log
    - confidence < MIN_CONFIDENCE → None + abstain log
    - Already-fired briefing → None
    - MAX_CONCURRENT_LEGS reached → None + abstain log
    - BUY entry zone match → fires StrategyDecision with correct
      direction, sl_pips, tp_pips, mode=BRIEFING_V5
    - SELL entry zone match → fires correctly
    - Outside entry zone → None
    - One fire per briefing — second tick post-fire returns None
    - New briefing-id (re-arm) after a fire → can fire again

Standalone runner — exits 0 on pass.
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, "/opt/tradingbot")


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso_z(dt: datetime) -> str:
    """Match orchestrator's strftime('%Y-%m-%dT%H:%M:%SZ') format."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _armed_payload(
    pair: str = "GBPUSD",
    session: str = "London",
    direction: str = "BUY",
    entry: float = 13560.0,
    stop: float = 13515.0,
    target: float = 13660.0,
    confidence: int = 75,
    confidence_bucket: str = "ARMED",
    state: str = "ARMED",
    valid_until: Optional[datetime] = None,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """A minimal fully-valid BriefingV5-shaped dict for tests."""
    now = generated_at or _now_utc()
    valid_until = valid_until or (now + timedelta(hours=7))
    return {
        "schema_version": "v5_pia",
        "pair": pair,
        "session": session,
        "generated_at_utc": _iso_z(now),
        "valid_until_utc": _iso_z(valid_until),
        "direction": direction,
        "state": state,
        "confidence": confidence,
        "confidence_bucket": confidence_bucket,
        "confidence_breakdown": {},
        "bias_anchor": entry,
        "bias_anchor_label": "H4_EMA20",
        "entry": entry,
        "stop": stop,
        "target": target,
        "rr": 2.22,
        "stop_structural_level": "swing_low",
        "target_structural_level": "swing_high",
        "support_levels": [stop, 13500.0],
        "resistance_levels": [target, 13700.0],
        "rationale": None,
        "stand_aside_reason": None,
        "news_in_window": False,
        "news_event": None,
        "execution": {
            "min_confidence_to_arm": 70,
            "executed": False, "executed_at_utc": None,
            "deal_id": None, "outcome": None,
        },
    }


def _stand_aside_payload(pair: str = "GBPUSD", session: str = "London") -> Dict[str, Any]:
    now = _now_utc()
    return {
        "schema_version": "v5_pia",
        "pair": pair,
        "session": session,
        "generated_at_utc": _iso_z(now),
        "valid_until_utc": _iso_z(now + timedelta(hours=7)),
        "direction": "STAND_ASIDE",
        "state": "STAND_ASIDE",
        "confidence": 0,
        "confidence_bucket": "STAND_ASIDE",
        "confidence_breakdown": {},
        "bias_anchor": None,
        "bias_anchor_label": None,
        "entry": None, "stop": None, "target": None,
        "rr": 0.0,
        "stop_structural_level": None,
        "target_structural_level": None,
        "support_levels": [],
        "resistance_levels": [],
        "rationale": None,
        "stand_aside_reason": "d1_h4_bias_disagree",
        "news_in_window": False,
        "news_event": None,
        "execution": {
            "min_confidence_to_arm": 70,
            "executed": False, "executed_at_utc": None,
            "deal_id": None, "outcome": None,
        },
    }


def _write_briefing_to(tmpdir: Path, payload: Dict[str, Any], when: Optional[datetime] = None) -> Path:
    when = when or _now_utc()
    tmpdir.mkdir(parents=True, exist_ok=True)
    date_str = when.strftime("%Y-%m-%d")
    path = tmpdir / f"briefing_{payload['pair'].upper()}_{date_str}_{payload['session']}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Reload helpers — clean module state per test (env vars affect module-load)
# ─────────────────────────────────────────────────────────────────────────────

def _reload_with_env(env: Dict[str, str]):
    """Reload briefing.v5_pia.config + reader + executor with env vars set."""
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = str(v)
    # Order matters: config first (others import from it), then reader/executor.
    for mod in ("briefing.v5_pia.config",
                "briefing.v5_pia.reader",
                "briefing.v5_pia.executor"):
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])
    from briefing.v5_pia import reader, executor
    return reader, executor


# ─────────────────────────────────────────────────────────────────────────────
# Reader tests
# ─────────────────────────────────────────────────────────────────────────────

def test_active_session_for_pre_london():
    reader, _ = _reload_with_env({})
    dt = datetime(2026, 5, 11, 4, 0, tzinfo=timezone.utc)
    assert reader.active_session_for(dt) == "NY"  # pre-London → falls into NY band by design


def test_active_session_for_london_window():
    reader, _ = _reload_with_env({})
    dt = datetime(2026, 5, 11, 8, 0, tzinfo=timezone.utc)
    assert reader.active_session_for(dt) == "London"


def test_active_session_for_at_ny_open():
    reader, _ = _reload_with_env({})
    dt = datetime(2026, 5, 11, 12, 30, tzinfo=timezone.utc)
    assert reader.active_session_for(dt) == "NY"


def test_active_session_for_late_ny():
    reader, _ = _reload_with_env({})
    dt = datetime(2026, 5, 11, 19, 0, tzinfo=timezone.utc)
    assert reader.active_session_for(dt) == "NY"


def test_load_v5_briefing_missing_file():
    with tempfile.TemporaryDirectory() as td:
        reader, _ = _reload_with_env({})
        b = reader.load_v5_briefing("GBPUSD", "London", briefings_dir=Path(td))
        assert b is None


def test_load_v5_briefing_unparseable_json():
    with tempfile.TemporaryDirectory() as td:
        reader, _ = _reload_with_env({})
        path = Path(td) / f"briefing_GBPUSD_{_now_utc().strftime('%Y-%m-%d')}_London.json"
        path.write_text("{not valid json", encoding="utf-8")
        b = reader.load_v5_briefing("GBPUSD", "London", briefings_dir=Path(td))
        assert b is None


def test_load_v5_briefing_schema_invalid():
    with tempfile.TemporaryDirectory() as td:
        reader, _ = _reload_with_env({})
        bad = _armed_payload()
        bad["confidence"] = 200  # out of range — Pydantic must reject
        _write_briefing_to(Path(td), bad)
        b = reader.load_v5_briefing("GBPUSD", "London", briefings_dir=Path(td))
        assert b is None


def test_load_v5_briefing_well_formed():
    with tempfile.TemporaryDirectory() as td:
        reader, _ = _reload_with_env({})
        _write_briefing_to(Path(td), _armed_payload())
        b = reader.load_v5_briefing("GBPUSD", "London", briefings_dir=Path(td))
        assert b is not None
        assert b.pair == "GBPUSD"
        assert b.direction == "BUY"
        assert b.confidence == 75


def test_is_briefing_active_future():
    reader, _ = _reload_with_env({})
    from briefing.v5_pia.schema import BriefingV5
    payload = _armed_payload(valid_until=_now_utc() + timedelta(hours=2))
    b = BriefingV5(**payload)
    assert reader.is_briefing_active(b) is True


def test_is_briefing_active_past():
    reader, _ = _reload_with_env({})
    from briefing.v5_pia.schema import BriefingV5
    payload = _armed_payload(
        generated_at=_now_utc() - timedelta(hours=10),
        valid_until=_now_utc() - timedelta(hours=2),
    )
    b = BriefingV5(**payload)
    assert reader.is_briefing_active(b) is False


def test_is_briefing_armed_requires_both():
    reader, _ = _reload_with_env({})
    from briefing.v5_pia.schema import BriefingV5
    armed = BriefingV5(**_armed_payload())
    assert reader.is_briefing_armed(armed) is True
    sa = BriefingV5(**_stand_aside_payload())
    assert reader.is_briefing_armed(sa) is False


# ─────────────────────────────────────────────────────────────────────────────
# Executor tests
# ─────────────────────────────────────────────────────────────────────────────

def _patch_briefings_dir(executor_mod, tmpdir: Path) -> None:
    """Point the reader the executor uses at our tmp dir."""
    import briefing.v5_pia.config as cfg
    import briefing.v5_pia.reader as reader
    cfg.BRIEFINGS_DIR = tmpdir
    reader.BRIEFINGS_DIR = tmpdir


def _stub_count_open_legs(executor_mod, n: int) -> None:
    """Patch _count_open_briefing_legs to return n (avoid dragging in
    trade_executor.EPIC_STATE)."""
    executor_mod._count_open_briefing_legs = lambda: n


def test_executor_parallel_mode_off_returns_none():
    with tempfile.TemporaryDirectory() as td:
        reader, executor_mod = _reload_with_env({"BRIEFING_V5_PARALLEL_MODE": "0"})
        _patch_briefings_dir(executor_mod, Path(td))
        _write_briefing_to(Path(td), _armed_payload(entry=13560))
        ex = executor_mod.BriefingV5Executor()
        decision = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                    mid_price=13560.0, pip_size=1.0)
        assert decision is None


def test_executor_no_briefing_returns_none():
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({"BRIEFING_V5_PARALLEL_MODE": "1"})
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)
        ex = executor_mod.BriefingV5Executor()
        decision = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                    mid_price=13560.0, pip_size=1.0)
        assert decision is None


def test_executor_stand_aside_returns_none():
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({"BRIEFING_V5_PARALLEL_MODE": "1"})
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)
        _write_briefing_to(Path(td), _stand_aside_payload())
        ex = executor_mod.BriefingV5Executor()
        decision = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                    mid_price=13560.0, pip_size=1.0)
        assert decision is None


def test_executor_expired_briefing_returns_none():
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({"BRIEFING_V5_PARALLEL_MODE": "1"})
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)
        _write_briefing_to(Path(td), _armed_payload(
            generated_at=_now_utc() - timedelta(hours=10),
            valid_until=_now_utc() - timedelta(hours=2),
        ))
        ex = executor_mod.BriefingV5Executor()
        decision = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                    mid_price=13560.0, pip_size=1.0)
        assert decision is None


def test_executor_low_confidence_returns_none():
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({
            "BRIEFING_V5_PARALLEL_MODE": "1",
            "BRIEFING_EXECUTION_MIN_CONFIDENCE": "70",
        })
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)
        # confidence=65 with bucket=WATCH (50<=conf<70 keeps Pydantic happy)
        _write_briefing_to(Path(td), _armed_payload(
            confidence=65, confidence_bucket="WATCH",
        ))
        ex = executor_mod.BriefingV5Executor()
        decision = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                    mid_price=13560.0, pip_size=1.0)
        assert decision is None


def test_executor_max_concurrent_legs_returns_none():
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({
            "BRIEFING_V5_PARALLEL_MODE": "1",
            "BRIEFING_MAX_CONCURRENT_LEGS": "2",
        })
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 2)  # at cap
        _write_briefing_to(Path(td), _armed_payload(entry=13560))
        ex = executor_mod.BriefingV5Executor()
        decision = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                    mid_price=13560.0, pip_size=1.0)
        assert decision is None


_FIXED_LONDON_NOW = datetime(2026, 5, 11, 8, 0, tzinfo=timezone.utc)


def test_executor_buy_entry_zone_match_fires():
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({
            "BRIEFING_V5_PARALLEL_MODE": "1",
            "BRIEFING_EXECUTION_MIN_CONFIDENCE": "70",
            "V5_EXECUTOR_ENTRY_TOL_PIPS": "2.0",
        })
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)
        _write_briefing_to(
            Path(td),
            _armed_payload(
                direction="BUY", entry=13560, stop=13515, target=13660,
                confidence=75, generated_at=_FIXED_LONDON_NOW,
            ),
            when=_FIXED_LONDON_NOW,
        )
        ex = executor_mod.BriefingV5Executor()
        decision = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                    mid_price=13560.5, pip_size=1.0,
                                    now_utc=_FIXED_LONDON_NOW)
        assert decision is not None
        assert decision.signal == "BUY"
        assert decision.mode == "BRIEFING_V5"
        assert abs(decision.sl - 45.0) < 0.01
        assert abs(decision.tp - 100.0) < 0.01
        assert decision.debug.get("v5_briefing_entry") == 13560
        assert decision.debug.get("v5_confidence") == 75


def test_executor_sell_entry_zone_match_fires():
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({
            "BRIEFING_V5_PARALLEL_MODE": "1",
            "BRIEFING_EXECUTION_MIN_CONFIDENCE": "70",
            "V5_EXECUTOR_ENTRY_TOL_PIPS": "2.0",
        })
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)
        _write_briefing_to(
            Path(td),
            _armed_payload(
                direction="SELL", entry=13620, stop=13660, target=13540,
                confidence=80, generated_at=_FIXED_LONDON_NOW,
            ),
            when=_FIXED_LONDON_NOW,
        )
        ex = executor_mod.BriefingV5Executor()
        decision = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                    mid_price=13619.0, pip_size=1.0,
                                    now_utc=_FIXED_LONDON_NOW)
        assert decision is not None
        assert decision.signal == "SELL"
        assert decision.mode == "BRIEFING_V5"
        assert abs(decision.sl - 40.0) < 0.01
        assert abs(decision.tp - 80.0) < 0.01


def test_executor_outside_entry_zone_returns_none():
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({
            "BRIEFING_V5_PARALLEL_MODE": "1",
            "V5_EXECUTOR_ENTRY_TOL_PIPS": "2.0",
        })
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)
        _write_briefing_to(
            Path(td),
            _armed_payload(entry=13560, generated_at=_FIXED_LONDON_NOW),
            when=_FIXED_LONDON_NOW,
        )
        ex = executor_mod.BriefingV5Executor()
        decision = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                    mid_price=13565.0, pip_size=1.0,
                                    now_utc=_FIXED_LONDON_NOW)
        assert decision is None


def test_executor_one_fire_per_briefing_dedup():
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({
            "BRIEFING_V5_PARALLEL_MODE": "1",
            "V5_EXECUTOR_ENTRY_TOL_PIPS": "2.0",
        })
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)
        _write_briefing_to(
            Path(td),
            _armed_payload(entry=13560, generated_at=_FIXED_LONDON_NOW),
            when=_FIXED_LONDON_NOW,
        )
        ex = executor_mod.BriefingV5Executor()
        d1 = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                              mid_price=13560.0, pip_size=1.0,
                              now_utc=_FIXED_LONDON_NOW)
        assert d1 is not None
        d2 = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                              mid_price=13560.0, pip_size=1.0,
                              now_utc=_FIXED_LONDON_NOW)
        assert d2 is None


def test_executor_new_briefing_re_arms_after_fire():
    """Different briefing-id (e.g. NY session, or next day) → new fire allowed."""
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({
            "BRIEFING_V5_PARALLEL_MODE": "1",
            "V5_EXECUTOR_ENTRY_TOL_PIPS": "2.0",
        })
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)

        london_now = datetime(2026, 5, 11, 8, 0, tzinfo=timezone.utc)
        london = _armed_payload(
            session="London", entry=13560,
            generated_at=datetime(2026, 5, 11, 5, 30, tzinfo=timezone.utc),
        )
        _write_briefing_to(Path(td), london, when=london_now)

        ex = executor_mod.BriefingV5Executor()
        d1 = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                              mid_price=13560.0, pip_size=1.0,
                              now_utc=london_now)
        assert d1 is not None
        # Same briefing — no re-fire
        d_dup = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                 mid_price=13560.0, pip_size=1.0,
                                 now_utc=london_now)
        assert d_dup is None

        # Now write the NY briefing for the same day. Different
        # session → different briefing-id → re-arm.
        ny_when = datetime(2026, 5, 11, 12, 30, tzinfo=timezone.utc)
        ny = _armed_payload(
            session="NY", entry=13620, stop=13580, target=13700,
            generated_at=ny_when,
        )
        _write_briefing_to(Path(td), ny, when=ny_when)
        ny_now = datetime(2026, 5, 11, 13, 0, tzinfo=timezone.utc)
        d2 = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                              mid_price=13620.0, pip_size=1.0,
                              now_utc=ny_now)
        assert d2 is not None
        assert d2.debug.get("v5_session") == "NY"


def test_executor_strategy_mode_value():
    """Anchor on the canonical mode name so signal_log JOIN to forensic
    works."""
    _, executor_mod = _reload_with_env({})
    assert executor_mod.STRATEGY_MODE == "BRIEFING_V5"


# ─────────────────────────────────────────────────────────────────────────────
# Integration test: synthetic briefing + simulated price + log the path
# ─────────────────────────────────────────────────────────────────────────────

def test_integration_synthetic_briefing_to_decision():
    """End-to-end: write a briefing, drive ticks across the entry zone,
    confirm exactly one fire with the right metadata."""
    with tempfile.TemporaryDirectory() as td:
        _, executor_mod = _reload_with_env({
            "BRIEFING_V5_PARALLEL_MODE": "1",
            "BRIEFING_EXECUTION_MIN_CONFIDENCE": "70",
            "V5_EXECUTOR_ENTRY_TOL_PIPS": "2.0",
            "BRIEFING_MAX_CONCURRENT_LEGS": "2",
        })
        _patch_briefings_dir(executor_mod, Path(td))
        _stub_count_open_legs(executor_mod, 0)

        _write_briefing_to(
            Path(td),
            _armed_payload(
                direction="BUY",
                entry=13560.0, stop=13515.0, target=13689.0,
                confidence=75, confidence_bucket="ARMED",
                generated_at=_FIXED_LONDON_NOW,
            ),
            when=_FIXED_LONDON_NOW,
        )
        ex = executor_mod.BriefingV5Executor()

        # Drive a sequence of ticks: well-above, approaching, in-zone, post-fire
        ticks = [
            (13580.0, None),    # 20 pips above — too far
            (13564.0, None),    # 4 pips above — outside 2-pip tolerance
            (13561.5, "fire"),  # 1.5 pips above — inside tolerance
            (13559.5, None),    # in zone but already fired
            (13540.0, None),    # 20 pips below — already fired
        ]

        fired_count = 0
        last_decision = None
        for mid, expect in ticks:
            d = ex.evaluate_tick("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                                 mid_price=mid, pip_size=1.0,
                                 now_utc=_FIXED_LONDON_NOW)
            if d is not None:
                fired_count += 1
                last_decision = d
            if expect == "fire":
                assert d is not None, f"expected fire at mid={mid}, got None"
            else:
                assert d is None, f"expected no fire at mid={mid}, got {d}"

        assert fired_count == 1, f"expected exactly 1 fire, got {fired_count}"
        assert last_decision.mode == "BRIEFING_V5"
        assert last_decision.signal == "BUY"
        assert last_decision.entry == 13561.5  # used the actual mid at fire time
        assert abs(last_decision.sl - 45.0) < 0.01
        assert abs(last_decision.tp - 129.0) < 0.01
        # debug carries the briefing fingerprint for downstream JOIN
        assert "v5_briefing_id" in last_decision.debug
        assert "v5_generated_at_utc" in last_decision.debug


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def main():
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and inspect.isfunction(fn)]
    failed = []
    print(f"Running {len(tests)} v5 phase-3 tests...")
    t0 = time.time()
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failed.append((name, e))
    dt = time.time() - t0
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed in {dt:.2f}s")
    if failed:
        for name, e in failed:
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
