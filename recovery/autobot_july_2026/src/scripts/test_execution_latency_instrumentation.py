#!/usr/bin/env python3
"""Standalone tests for execution-latency instrumentation.

Run:
    python3 scripts/test_execution_latency_instrumentation.py

Tests:
  1. signal_logger.log_open accepts and persists new latency fields
  2. signal_logger.log_close accepts and persists new exit-path fields
  3. analysis script renders cleanly against synthetic mixed data
  4. backfill script is idempotent

Exits 0 on pass, 1 on any failure.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, "/opt/tradingbot")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class _FakeDecision:
    symbol: str = "GBPUSD"
    signal: str = "BUY"
    mode: str = "TEST_MODE"
    entry: Optional[float] = 13627.25
    sl: Optional[float] = 8.0
    tp: Optional[float] = 12.0
    reason: str = "test"
    debug: Dict[str, Any] = field(default_factory=dict)
    pip_size: Optional[float] = 1.0


def _reload_signal_logger(log_path: Path):
    """Re-import signal_logger after pointing SIGNAL_LOG_PATH at log_path."""
    os.environ["SIGNAL_LOG_PATH"] = str(log_path)
    if "signal_logger" in sys.modules:
        return importlib.reload(sys.modules["signal_logger"])
    import signal_logger
    return signal_logger


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_log_open_accepts_latency(tmp_path: Path) -> None:
    log_path = tmp_path / "signal_log.jsonl"
    sl = _reload_signal_logger(log_path)
    import pandas as pd
    import execution_latency_metrics as elm

    df = pd.DataFrame()  # empty df is fine — log_open guards against this
    decision = _FakeDecision(debug={"pip_size": 1.0})
    latency = elm.build_fire_latency_record(
        t_decision=1_000_000,
        t_dispatch=1_000_010,
        t_ig_request=1_000_020,
        t_ig_ack=1_000_120,
        t_ig_confirm=1_000_350,
        ls_async_dispatch=0,
    )
    sl.log_open(
        trade_id="test-123",
        epic="CS.D.GBPUSD.TODAY.IP",
        decision=decision,
        briefing={},
        df_5m=df,
        entry_price=13627.25,
        deal_id="DEAL-X",
        latency=latency,
    )
    raw = log_path.read_text(encoding="utf-8").strip()
    assert raw, "log_open wrote nothing"
    rec = json.loads(raw.splitlines()[-1])

    # All fire-latency fields must be present and non-null.
    for k in elm.FIRE_LATENCY_FIELDS:
        assert k in rec, f"missing {k} in open record"
    assert rec["t_decision_epoch_ms"] == 1_000_000
    assert rec["t_ig_confirm_epoch_ms"] == 1_000_350
    assert rec["total_decision_to_confirm_ms"] == 350
    assert rec["dispatch_to_ig_request_ms"] == 10
    assert rec["ack_to_confirm_ms"] == 230
    assert rec["ls_async_dispatch"] == 0


def test_log_close_accepts_latency(tmp_path: Path) -> None:
    log_path = tmp_path / "signal_log.jsonl"
    sl = _reload_signal_logger(log_path)
    import pandas as pd
    import execution_latency_metrics as elm

    df = pd.DataFrame()
    decision = _FakeDecision(debug={"pip_size": 1.0})

    sl.log_open(
        trade_id="test-close-1",
        epic="CS.D.GBPUSD.TODAY.IP",
        decision=decision,
        briefing={},
        df_5m=df,
        entry_price=13627.25,
    )
    exit_latency = elm.build_exit_latency_record(
        t_exit_trigger=2_000_000,
        t_exit_dispatch=2_000_050,
        t_exit_confirm=2_000_900,
        ls_async_dispatch=0,
    )
    sl.log_close(
        trade_id="test-close-1",
        close_price=13620.0,
        pnl_pips=-7.25,
        reason="SL_HIT",
        df_5m=None,
        latency=exit_latency,
    )
    raw = log_path.read_text(encoding="utf-8").strip()
    assert raw
    rec = json.loads(raw.splitlines()[-1])

    for k in elm.EXIT_LATENCY_FIELDS:
        assert k in rec, f"missing {k} in close record"
    assert rec["t_exit_trigger_epoch_ms"] == 2_000_000
    assert rec["t_exit_confirm_epoch_ms"] == 2_000_900
    assert rec["total_trigger_to_confirm_ms"] == 900
    assert rec["trigger_to_dispatch_ms"] == 50
    assert rec["dispatch_to_confirm_ms"] == 850
    # Existing close fields must still be populated.
    assert rec["pnl_pips"] == -7.25
    assert rec["close_reason"] == "SL_HIT"


def test_log_open_omits_latency_keys_when_absent(tmp_path: Path) -> None:
    """Backwards compat: callers that don't pass latency= still work,
    and the open record has no latency keys (so old readers don't see
    a schema change)."""
    log_path = tmp_path / "signal_log.jsonl"
    sl = _reload_signal_logger(log_path)
    import pandas as pd
    import execution_latency_metrics as elm

    df = pd.DataFrame()
    decision = _FakeDecision(debug={"pip_size": 1.0})
    sl.log_open(
        trade_id="test-noLat-1",
        epic="CS.D.GBPUSD.TODAY.IP",
        decision=decision,
        briefing={},
        df_5m=df,
        entry_price=13627.25,
    )
    rec = json.loads(log_path.read_text(encoding="utf-8").strip())
    for k in elm.FIRE_LATENCY_FIELDS:
        assert k not in rec, f"unexpected {k} in open record without latency arg"


def test_analysis_script_renders_mixed(tmp_path: Path) -> None:
    """Synthesise a signal_log with mixed pre/post records and assert
    the analysis script runs cleanly and emits markdown."""
    log_path = tmp_path / "signal_log.jsonl"
    pre_record = {
        "id": "pre-1",
        "timestamp_open": "2026-05-08T07:00:00Z",
        "epic": "CS.D.GBPUSD.TODAY.IP",
        "pair": "GBPUSD",
        "direction": "BUY",
        "strategy": "TEST_PRE",
        "entry": 13627.25,
        "outcome": None,
        "t_decision_epoch_ms": 1_000_000,
        "t_dispatch_epoch_ms": 1_000_010,
        "t_ig_request_epoch_ms": 1_000_020,
        "t_ig_ack_epoch_ms": 1_000_120,
        "t_ig_confirm_epoch_ms": 1_000_350,
        "decision_to_dispatch_ms": 10,
        "dispatch_to_ig_request_ms": 10,
        "ig_request_to_ack_ms": 100,
        "ack_to_confirm_ms": 230,
        "total_decision_to_confirm_ms": 350,
        "ls_async_dispatch": 0,
    }
    post_record = dict(pre_record)
    post_record.update({
        "id": "post-1",
        "timestamp_open": "2026-05-09T13:00:00Z",
        "strategy": "TEST_POST",
        "ls_async_dispatch": 1,
        "total_decision_to_confirm_ms": 50,
        "decision_to_dispatch_ms": 30,
    })
    log_path.write_text(
        json.dumps(pre_record) + "\n" + json.dumps(post_record) + "\n",
        encoding="utf-8",
    )

    script = Path("/opt/tradingbot/"
                   "scripts/execution_latency_analysis.py")
    env = {**os.environ, "PYTHONPATH": "/opt/tradingbot" + ":" + os.environ.get("PYTHONPATH", "")}
    res = subprocess.run(
        [sys.executable, str(script), "--in", str(log_path)],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert res.returncode == 0, f"analysis script exit={res.returncode} stderr={res.stderr}"
    out = res.stdout
    assert "# Execution Latency Analysis" in out
    assert "Fire-path deltas" in out
    assert "TEST_PRE" in out
    assert "TEST_POST" in out
    assert "Pre/Post-refactor split" in out


def test_backfill_idempotent(tmp_path: Path) -> None:
    log_path = tmp_path / "signal_log.jsonl"
    out_path = tmp_path / "signal_log_backfilled.jsonl"
    # A pre-instrumentation record (no latency fields).
    rec = {
        "id": "old-1",
        "timestamp_open": "2026-04-01T08:00:00Z",
        "epic": "CS.D.EURUSD.TODAY.IP",
        "pair": "EURUSD",
        "direction": "SELL",
        "strategy": "OLD_STRAT",
        "entry": 11500.0,
        "outcome": "TP1",
    }
    log_path.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    script = Path("/opt/tradingbot/"
                   "scripts/backfill_execution_latency.py")
    args = [sys.executable, str(script), "--in", str(log_path),
            "--out", str(out_path)]

    env = {**os.environ, "PYTHONPATH": "/opt/tradingbot" + ":" + os.environ.get("PYTHONPATH", "")}
    r1 = subprocess.run(args, capture_output=True, text=True, timeout=30, env=env)
    assert r1.returncode == 0, r1.stderr
    first = out_path.read_text(encoding="utf-8")
    rec1 = json.loads(first.strip().splitlines()[-1])
    assert "t_ig_confirm_epoch_ms" in rec1
    assert "ls_async_dispatch" in rec1
    assert rec1["ls_async_dispatch"] == 0

    # Run again — output must be byte-identical.
    r2 = subprocess.run(args, capture_output=True, text=True, timeout=30, env=env)
    assert r2.returncode == 0, r2.stderr
    second = out_path.read_text(encoding="utf-8")
    assert first == second, "backfill is not idempotent"


def test_backfill_handles_missing_input(tmp_path: Path) -> None:
    log_path = tmp_path / "does_not_exist.jsonl"
    out_path = tmp_path / "out.jsonl"
    script = Path("/opt/tradingbot/"
                   "scripts/backfill_execution_latency.py")
    env = {**os.environ, "PYTHONPATH": "/opt/tradingbot" + ":" + os.environ.get("PYTHONPATH", "")}
    res = subprocess.run(
        [sys.executable, str(script), "--in", str(log_path),
         "--out", str(out_path)],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert res.returncode == 0
    assert out_path.exists()
    body = out_path.read_text(encoding="utf-8")
    assert "input log not found" in body


def test_elm_delta_clamps_negative(tmp_path: Path) -> None:
    import execution_latency_metrics as elm
    deltas = elm.fire_path_deltas(100, 50, 30, 20, 10)
    # All deltas should be clamped to 0, not negative.
    for k, v in deltas.items():
        assert v == 0, f"{k} not clamped: {v}"


def test_elm_handles_none_inputs(tmp_path: Path) -> None:
    import execution_latency_metrics as elm
    deltas = elm.fire_path_deltas(None, None, None, None, None)
    for v in deltas.values():
        assert v is None
    # Also for build_*
    rec = elm.build_fire_latency_record(
        t_decision=None, t_dispatch=None, t_ig_request=None,
        t_ig_ack=None, t_ig_confirm=None,
    )
    assert rec["ls_async_dispatch"] in (0, 1)
    for k in ("t_decision_epoch_ms", "t_dispatch_epoch_ms",
               "t_ig_request_epoch_ms", "t_ig_ack_epoch_ms",
               "t_ig_confirm_epoch_ms"):
        assert rec[k] is None


def test_ls_occupancy_gauge_no_workers_is_silent(tmp_path: Path) -> None:
    """Post-fillin: emit_ls_occupancy_gauge is no longer a stub. With
    no registered workers it must still be a graceful no-op (returns
    None, doesn't raise) — this preserves the test's original contract
    for the empty-registry case. Detailed behavior is covered by
    scripts/test_ls_occupancy_gauge.py."""
    import execution_latency_metrics as elm
    import pair_workers
    pair_workers.shutdown_all()
    assert hasattr(elm, "emit_ls_occupancy_gauge")
    assert elm.emit_ls_occupancy_gauge() is None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and inspect.isfunction(fn)]
    failed: List = []
    print(f"Running {len(tests)} tests for execution_latency_instrumentation...")
    for name, fn in tests:
        sig = inspect.signature(fn)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td))
            else:
                fn()
            print(f"  PASS {name}")
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
            failed.append((name, str(e)))
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {name}: unexpected {type(e).__name__}: {e}")
            failed.append((name, f"{type(e).__name__}: {e}"))
    print()
    print(f"{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
