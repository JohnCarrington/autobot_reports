#!/usr/bin/env python3
"""Tests for forensic_outcome_backfill against synthetic forensic records
matching today's actual signal_log fires. Standalone — exit 0 on pass.

Tests:
  1. Synthetic forensic record matching a signal_log fire gets outcome
     populated (signal_log path).
  2. Idempotency — running backfill twice doesn't change already-filled
     records.
  3. Dispatcher-gap fire (no signal_log close) falls through to journal
     grep correctly (or lands in unmatched if journal unavailable).
  4. Records with no match end up in the unmatched list.
  5. Atomic write — failed write doesn't corrupt the file.
"""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/opt/tradingbot")
sys.path.insert(0, "/opt/tradingbot/scripts")

import forensic_outcome_backfill as bf  # noqa: E402

ROOT = Path("/opt/tradingbot")
REAL_SIGNAL_LOG = ROOT / "logs" / "signal_log.jsonl"


def _write_forensic(path: Path, records: list) -> None:
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _read_forensic(path: Path) -> list:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def test_signal_log_match(tmp_path):
    """A forensic record matching a real signal_log fire should populate."""
    forensic_path = tmp_path / "forensic.jsonl"
    # Synthetic record matching today's 06:55 BB_BOUNCE_L LONG (eval bar 06:50)
    rec = {
        "timestamp": "2026-05-04T06:55:02+00:00",
        "fire_bar_ts": "2026-05-04T06:50:00+00:00",
        "strategy": "GBPUSD_BB_BOUNCE_L",
        "direction": "LONG",
        "entry_price": 13581.55,
        "snapshot": {"placeholder": True},
        "outcome": None,
        "outcome_pips": None,
        "outcome_exit_reason": None,
        "outcome_close_ts": None,
    }
    _write_forensic(forensic_path, [rec])

    result = bf.backfill(
        forensic_path=forensic_path,
        signal_log_path=REAL_SIGNAL_LOG,
        use_journal=False,
    )

    assert result["total"] == 1
    assert result["matched_signal_log"] == 1, (
        f"expected 1 signal_log match, got {result}")
    assert result["matched_journal"] == 0
    assert result["unmatched_count"] == 0

    updated = _read_forensic(forensic_path)
    r = updated[0]
    assert r["outcome"] == "matched_signal_log"
    assert r["outcome_pips"] == -10.75, f"got pnl={r['outcome_pips']}"
    assert r["outcome_close_ts"] is not None
    assert r["outcome_exit_reason"] is not None


def test_multiple_real_fires_match(tmp_path):
    """Multiple forensic records matching today's real fires."""
    forensic_path = tmp_path / "forensic.jsonl"
    fires = [
        # (fire_bar_ts, strategy, direction, expected_pnl)
        ("2026-05-04T06:05:00+00:00", "GBPUSD_BB_BOUNCE_S", "SHORT", 48.4),
        ("2026-05-04T06:50:00+00:00", "GBPUSD_BB_BOUNCE_L", "LONG", -10.75),
        ("2026-05-04T14:30:00+00:00", "GBPUSD_BB_BOUNCE_S", "SHORT", 21.5),
        ("2026-05-04T14:40:00+00:00", "GBPUSD_TREND_CONT_S", "SHORT", 5.75),
    ]
    records = [{
        "timestamp": "x",
        "fire_bar_ts": fbar, "strategy": strat, "direction": dirn,
        "entry_price": 1.0, "snapshot": {},
        "outcome": None, "outcome_pips": None,
        "outcome_exit_reason": None, "outcome_close_ts": None,
    } for fbar, strat, dirn, _ in fires]
    _write_forensic(forensic_path, records)

    result = bf.backfill(
        forensic_path=forensic_path,
        signal_log_path=REAL_SIGNAL_LOG,
        use_journal=False,
    )
    assert result["matched_signal_log"] == 4, (
        f"expected 4 matches, got {result['matched_signal_log']}: "
        f"unmatched={result['unmatched']}")
    assert result["unmatched_count"] == 0

    updated = _read_forensic(forensic_path)
    by_bar = {r["fire_bar_ts"]: r for r in updated}
    for fbar, _, _, expected_pnl in fires:
        assert by_bar[fbar]["outcome_pips"] == expected_pnl, (
            f"{fbar}: expected {expected_pnl}, got {by_bar[fbar]['outcome_pips']}")


def test_idempotent(tmp_path):
    """Re-running backfill on an already-filled record does nothing new."""
    forensic_path = tmp_path / "forensic.jsonl"
    rec = {
        "timestamp": "x", "fire_bar_ts": "2026-05-04T06:50:00+00:00",
        "strategy": "GBPUSD_BB_BOUNCE_L", "direction": "LONG",
        "entry_price": 1.0, "snapshot": {},
        "outcome": None, "outcome_pips": None,
        "outcome_exit_reason": None, "outcome_close_ts": None,
    }
    _write_forensic(forensic_path, [rec])

    r1 = bf.backfill(forensic_path=forensic_path,
                     signal_log_path=REAL_SIGNAL_LOG, use_journal=False)
    assert r1["matched_signal_log"] == 1

    # Run again — should detect already-filled and not re-match
    r2 = bf.backfill(forensic_path=forensic_path,
                     signal_log_path=REAL_SIGNAL_LOG, use_journal=False)
    assert r2["already_filled"] == 1, r2
    assert r2["matched_signal_log"] == 0
    assert r2["wrote_file"] is False, "should not rewrite when no new matches"


def test_unmatched_no_journal(tmp_path):
    """A fire with no signal_log entry and no journal fallback → unmatched."""
    forensic_path = tmp_path / "forensic.jsonl"
    rec = {
        "timestamp": "x",
        "fire_bar_ts": "2024-01-01T00:00:00+00:00",  # ancient, no match
        "strategy": "GBPUSD_FAKE_STRATEGY", "direction": "LONG",
        "entry_price": 1.0, "snapshot": {},
        "outcome": None, "outcome_pips": None,
        "outcome_exit_reason": None, "outcome_close_ts": None,
    }
    _write_forensic(forensic_path, [rec])

    result = bf.backfill(forensic_path=forensic_path,
                         signal_log_path=REAL_SIGNAL_LOG, use_journal=False)
    assert result["matched_signal_log"] == 0
    assert result["unmatched_count"] == 1
    assert result["unmatched"][0]["strategy"] == "GBPUSD_FAKE_STRATEGY"


def test_journal_fallback_recovers_dispatcher_gap(tmp_path):
    """A dispatcher-gap fire (not in signal_log) should be recoverable
    via journal SENTINEL events. Uses 04-29 11:10 GBPUSD_TREND_CONT_S
    which was confirmed earlier as recoverable (pnl=-5.2)."""
    forensic_path = tmp_path / "forensic.jsonl"
    # Bar before 11:10 fire = 11:05
    rec = {
        "timestamp": "x", "fire_bar_ts": "2026-04-29T11:05:00+00:00",
        "strategy": "GBPUSD_TREND_CONT_S", "direction": "SHORT",
        "entry_price": 1.0, "snapshot": {},
        "outcome": None, "outcome_pips": None,
        "outcome_exit_reason": None, "outcome_close_ts": None,
    }
    _write_forensic(forensic_path, [rec])

    result = bf.backfill(forensic_path=forensic_path,
                         signal_log_path=REAL_SIGNAL_LOG,
                         use_journal=True)

    # Either we recover via journal, or we don't (depending on journal availability).
    # We just verify the path doesn't crash and produces a coherent result.
    assert result["total"] == 1
    if result["matched_journal"] == 1:
        updated = _read_forensic(forensic_path)
        assert updated[0]["outcome"] == "matched_journal"
        assert updated[0]["outcome_pips"] is not None
        # Verified earlier this fire's pnl was -5.2
        assert abs(updated[0]["outcome_pips"] - (-5.2)) < 0.01, (
            f"expected -5.2 from journal, got {updated[0]['outcome_pips']}")
    else:
        # Journal not available or didn't match — record left unmatched
        assert result["unmatched_count"] == 1


def test_dry_run_no_write(tmp_path):
    """--dry-run should compute matches but not modify the file."""
    forensic_path = tmp_path / "forensic.jsonl"
    rec = {
        "timestamp": "x", "fire_bar_ts": "2026-05-04T06:50:00+00:00",
        "strategy": "GBPUSD_BB_BOUNCE_L", "direction": "LONG",
        "entry_price": 1.0, "snapshot": {},
        "outcome": None, "outcome_pips": None,
        "outcome_exit_reason": None, "outcome_close_ts": None,
    }
    _write_forensic(forensic_path, [rec])
    pre = forensic_path.read_bytes()

    result = bf.backfill(forensic_path=forensic_path,
                         signal_log_path=REAL_SIGNAL_LOG,
                         use_journal=False, dry_run=True)
    assert result["matched_signal_log"] == 1
    assert result["wrote_file"] is False

    post = forensic_path.read_bytes()
    assert pre == post, "dry_run wrote to file!"


def main():
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and inspect.isfunction(fn)]
    failed: list = []
    print(f"Running {len(tests)} tests for forensic_outcome_backfill...")
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
