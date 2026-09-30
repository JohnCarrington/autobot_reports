#!/usr/bin/env python3
"""Unit tests for forensic_logger. Standalone runner — exits 0 on pass.

Tests:
  1. _build_record produces correct schema
  2. Direction normalization (BUY→LONG, SELL→SHORT)
  3. write_forensic_fire creates the log file with the record
  4. ENV flag GBPUSD_FORENSIC_LOGGING_ENABLED=false suppresses write
  5. Multiple writes append correctly without corruption
  6. No .tmp.* files persist after a successful write (atomic cleanup)
  7. Bad input does not raise — returns False instead
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/opt/tradingbot")


def _reload_logger():
    """Re-import forensic_logger so it picks up env var changes."""
    if "forensic_logger" in sys.modules:
        return importlib.reload(sys.modules["forensic_logger"])
    import forensic_logger
    return forensic_logger


def test_build_record_schema():
    fl = _reload_logger()
    rec = fl._build_record(
        strategy="GBPUSD_BB_BOUNCE_L",
        direction="BUY",
        entry_price=13581.55,
        fire_bar_ts="2026-05-04T06:50:00+00:00",
        snapshot_dict={"foo": "bar", "n": 1},
    )
    expected_keys = {
        "timestamp", "fire_bar_ts", "strategy", "direction", "entry_price",
        "snapshot", "outcome", "outcome_pips", "outcome_exit_reason",
        "outcome_close_ts",
    }
    actual = set(rec.keys())
    assert actual == expected_keys, (
        f"schema mismatch: missing={expected_keys - actual} "
        f"extra={actual - expected_keys}"
    )
    assert rec["fire_bar_ts"] == "2026-05-04T06:50:00+00:00"
    assert rec["strategy"] == "GBPUSD_BB_BOUNCE_L"
    assert rec["entry_price"] == 13581.55
    assert rec["snapshot"] == {"foo": "bar", "n": 1}
    assert rec["outcome"] is None
    assert rec["outcome_pips"] is None
    assert rec["outcome_exit_reason"] is None
    assert rec["outcome_close_ts"] is None


def test_direction_normalization():
    fl = _reload_logger()
    assert fl._build_record("X", "BUY", 1.0, "ts", {})["direction"] == "LONG"
    assert fl._build_record("X", "SELL", 1.0, "ts", {})["direction"] == "SHORT"
    assert fl._build_record("X", "LONG", 1.0, "ts", {})["direction"] == "LONG"
    assert fl._build_record("X", "SHORT", 1.0, "ts", {})["direction"] == "SHORT"
    assert fl._build_record("X", "buy", 1.0, "ts", {})["direction"] == "LONG"


def test_write_creates_file(tmp_path):
    log_path = tmp_path / "test_write.jsonl"
    os.environ["GBPUSD_FORENSIC_LOG_PATH"] = str(log_path)
    os.environ["GBPUSD_FORENSIC_LOGGING_ENABLED"] = "true"
    fl = _reload_logger()

    ok = fl.write_forensic_fire(
        strategy="GBPUSD_BB_BOUNCE_L", direction="BUY", entry_price=13581.55,
        fire_bar_ts="2026-05-04T06:50:00+00:00",
        snapshot_dict={"hist": -1.58, "line": -1.03},
    )
    assert ok is True, "write_forensic_fire returned False on success path"
    assert log_path.exists(), "log file not created"

    with open(log_path) as f:
        lines = f.readlines()
    assert len(lines) == 1, f"expected 1 line, got {len(lines)}"
    rec = json.loads(lines[0])
    assert rec["strategy"] == "GBPUSD_BB_BOUNCE_L"
    assert rec["direction"] == "LONG"
    assert rec["entry_price"] == 13581.55
    assert rec["snapshot"]["hist"] == -1.58


def test_env_flag_disables(tmp_path):
    log_path = tmp_path / "test_disabled.jsonl"
    os.environ["GBPUSD_FORENSIC_LOG_PATH"] = str(log_path)
    os.environ["GBPUSD_FORENSIC_LOGGING_ENABLED"] = "false"
    fl = _reload_logger()

    ok = fl.write_forensic_fire(
        strategy="X", direction="LONG", entry_price=1.0,
        fire_bar_ts="ts", snapshot_dict={},
    )
    assert ok is False, "should return False when flag disabled"
    assert not log_path.exists(), "log file should not be created when disabled"

    # And other false-ish values
    for v in ("0", "no", "off", "FALSE"):
        os.environ["GBPUSD_FORENSIC_LOGGING_ENABLED"] = v
        fl = _reload_logger()
        ok = fl.write_forensic_fire("X", "LONG", 1.0, "ts", {})
        assert ok is False, f"value {v!r} should disable"


def test_multiple_writes_append(tmp_path):
    log_path = tmp_path / "test_multi.jsonl"
    os.environ["GBPUSD_FORENSIC_LOG_PATH"] = str(log_path)
    os.environ["GBPUSD_FORENSIC_LOGGING_ENABLED"] = "true"
    fl = _reload_logger()

    for i in range(5):
        ok = fl.write_forensic_fire(
            strategy=f"S{i}", direction="LONG", entry_price=float(i),
            fire_bar_ts=f"2026-05-04T0{i}:00:00+00:00",
            snapshot_dict={"i": i},
        )
        assert ok is True, f"write #{i} failed"

    with open(log_path) as f:
        lines = f.readlines()
    assert len(lines) == 5, f"expected 5 lines, got {len(lines)}"
    for i, line in enumerate(lines):
        rec = json.loads(line)
        assert rec["strategy"] == f"S{i}"
        assert rec["entry_price"] == float(i)
        assert rec["snapshot"]["i"] == i


def test_no_temp_files_left_behind(tmp_path):
    log_path = tmp_path / "test_atomic.jsonl"
    os.environ["GBPUSD_FORENSIC_LOG_PATH"] = str(log_path)
    os.environ["GBPUSD_FORENSIC_LOGGING_ENABLED"] = "true"
    fl = _reload_logger()

    for i in range(3):
        fl.write_forensic_fire("X", "LONG", float(i), "ts", {"i": i})

    tmps = list(tmp_path.glob("*.tmp.*"))
    assert not tmps, f"temp files left behind after success: {tmps}"


def test_never_raises_on_bad_input(tmp_path):
    """Even non-serializable snapshot data must not raise."""
    log_path = tmp_path / "test_bad.jsonl"
    os.environ["GBPUSD_FORENSIC_LOG_PATH"] = str(log_path)
    os.environ["GBPUSD_FORENSIC_LOGGING_ENABLED"] = "true"
    fl = _reload_logger()

    class Unserializable:
        pass

    ok = fl.write_forensic_fire(
        strategy="X", direction="LONG", entry_price=1.0, fire_bar_ts="ts",
        snapshot_dict={"bad": Unserializable()},
    )
    assert ok is False, "should return False on unserializable input"
    # File should not exist (no record was written) or exist but with no
    # corrupt content. Either is acceptable.
    if log_path.exists():
        with open(log_path) as f:
            content = f.read()
        # If anything was written it must be valid JSON-per-line
        for line in content.splitlines():
            line = line.strip()
            if line:
                json.loads(line)  # raises if corrupt


def test_replace_preserves_existing_records_on_failure(tmp_path):
    """If write fails mid-stream, the original log file must be preserved
    intact (no partial overwrite)."""
    log_path = tmp_path / "test_preserve.jsonl"
    os.environ["GBPUSD_FORENSIC_LOG_PATH"] = str(log_path)
    os.environ["GBPUSD_FORENSIC_LOGGING_ENABLED"] = "true"
    fl = _reload_logger()

    # Write 3 good records
    for i in range(3):
        fl.write_forensic_fire("S", "LONG", float(i), f"ts{i}", {"i": i})

    pre = log_path.read_bytes()

    # Attempt a write with bad input — should fail, but must not corrupt
    class Unserializable:
        pass
    fl.write_forensic_fire("S", "LONG", 99.0, "ts99",
                           {"x": Unserializable()})

    post = log_path.read_bytes()
    assert pre == post, "log file changed after failed write — corruption!"

    # Good writes after failure still work
    ok = fl.write_forensic_fire("S", "LONG", 100.0, "ts100", {"i": 100})
    assert ok is True
    with open(log_path) as f:
        lines = f.readlines()
    assert len(lines) == 4


def main():
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and inspect.isfunction(fn)]
    failed: list = []
    print(f"Running {len(tests)} tests for forensic_logger...")
    for name, fn in tests:
        sig = inspect.signature(fn)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as td:
                    fn(Path(td))
            else:
                fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ {name}: {e}")
            failed.append((name, str(e)))
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {name}: unexpected {type(e).__name__}: {e}")
            failed.append((name, f"{type(e).__name__}: {e}"))
    print()
    print(f"{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
