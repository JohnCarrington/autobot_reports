"""Unit tests for the BB_BOUNCE cascade-disagree gate (wired 2026-05-12).

Covers:
  - cascade_state.cascade_disagrees logic (agree/disagree/neutral/missing/stale)
  - BB_BOUNCE_CASCADE_GATE_ENABLED env-flag override
  - Forensic record carries cascade_label_at_fire + cascade_age_seconds
  - Counterfactual: Tuesday 2026-05-12 BB_BOUNCE_L fires replayed against the
    real regime_shadow.jsonl historical rows for those bars

Tests use synthetic regime_shadow.jsonl fixtures via the REGIME_SHADOW_LOG_PATH
env override (cascade_state._shadow_path re-reads env on every call) — except
test_counterfactual_tuesday_2026_05_12 which reads the live log.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pytest

sys.path.insert(0, "/opt/tradingbot")

import cascade_state  # noqa: E402
import forensic_logger  # noqa: E402


# ────────────────────────────────────────────────────────── fixture helpers

def _row(ts_iso: str, sym: str, stable):
    return {
        "ts": ts_iso,
        "symbol": sym,
        "stable": stable,
        "shadow_label": None,
        "shadow_confidence": None,
    }


def _write_shadow(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


@pytest.fixture
def shadow_log(tmp_path, monkeypatch):
    """Return a callable that writes synthetic shadow rows + activates the
    env override. Each call replaces the previous file content.
    """
    path = tmp_path / "regime_shadow.jsonl"
    monkeypatch.setenv(cascade_state.ENV_SHADOW_PATH, str(path))

    def _setup(rows):
        _write_shadow(path, rows)
        return path

    return _setup


# ───────────────────────────────────────────────── direct gate-helper tests

NOW = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)


def _ts(seconds_before: float) -> str:
    return (NOW - timedelta(seconds=seconds_before)).isoformat()


def test_case1_trend_down_short_allows(shadow_log):
    # cascade=TREND_DOWN + direction=SHORT → allow
    shadow_log([_row(_ts(30), "GBPUSD", "TREND_DOWN")])
    disagree, label, age = cascade_state.cascade_disagrees("SELL", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label == "TREND_DOWN"
    assert age is not None and age < 60


def test_case2_trend_down_long_blocks(shadow_log):
    # cascade=TREND_DOWN + direction=LONG → block
    shadow_log([_row(_ts(30), "GBPUSD", "TREND_DOWN")])
    disagree, label, age = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    assert disagree is True
    assert label == "TREND_DOWN"


def test_case3_trend_up_long_allows(shadow_log):
    shadow_log([_row(_ts(30), "GBPUSD", "TREND_UP")])
    disagree, label, _ = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label == "TREND_UP"


def test_case4_trend_up_short_blocks(shadow_log):
    shadow_log([_row(_ts(30), "GBPUSD", "TREND_UP")])
    disagree, label, _ = cascade_state.cascade_disagrees("SELL", "GBPUSD", now_utc=NOW)
    assert disagree is True
    assert label == "TREND_UP"


def test_case5_neutral_long_allows(shadow_log):
    shadow_log([_row(_ts(30), "GBPUSD", "NEUTRAL")])
    disagree, label, _ = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label == "NEUTRAL"


def test_case6_neutral_short_allows(shadow_log):
    shadow_log([_row(_ts(30), "GBPUSD", "NEUTRAL")])
    disagree, label, _ = cascade_state.cascade_disagrees("SELL", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label == "NEUTRAL"


def test_case7_range_long_allows(shadow_log):
    shadow_log([_row(_ts(30), "GBPUSD", "RANGE")])
    disagree, label, _ = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label == "RANGE"


def test_case8_range_short_allows(shadow_log):
    shadow_log([_row(_ts(30), "GBPUSD", "RANGE")])
    disagree, label, _ = cascade_state.cascade_disagrees("SELL", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label == "RANGE"


def test_case9_missing_pair_allows(shadow_log):
    # No record for GBPUSD at all → allow
    shadow_log([_row(_ts(30), "EURUSD", "TREND_DOWN")])
    disagree, label, age = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label is None
    assert age is None


def test_case9b_empty_file_allows(tmp_path, monkeypatch):
    p = tmp_path / "regime_shadow.jsonl"
    p.write_text("")
    monkeypatch.setenv(cascade_state.ENV_SHADOW_PATH, str(p))
    disagree, label, age = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label is None
    assert age is None


def test_case10_gate_disabled_never_blocks(monkeypatch):
    # When BB_BOUNCE_CASCADE_GATE_ENABLED=0, gbpusd_bb_bounce.evaluate
    # does NOT consult cascade_disagrees for blocking. We can't easily
    # invoke the strategy end-to-end (heavy deps), so we assert the
    # module-level flag is honoured: importing the module after setting
    # the env disables the gate at load time. The flag is read in
    # gbpusd_bb_bounce at module import.
    monkeypatch.setenv("BB_BOUNCE_CASCADE_GATE_ENABLED", "0")
    # Force reload so the new env value takes effect.
    import importlib
    import gbpusd_bb_bounce as bb
    importlib.reload(bb)
    assert bb.CASCADE_DISAGREE_GATE_ENABLED is False
    # And re-enable for downstream tests.
    monkeypatch.setenv("BB_BOUNCE_CASCADE_GATE_ENABLED", "1")
    importlib.reload(bb)
    assert bb.CASCADE_DISAGREE_GATE_ENABLED is True


def test_case12_stale_cascade_allows(shadow_log):
    # Age > 600s → treated as missing for gate purposes (still surfaced).
    shadow_log([_row(_ts(900), "GBPUSD", "TREND_DOWN")])
    disagree, label, age = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label == "TREND_DOWN"
    assert age is not None and age > 600


def test_most_recent_row_wins(shadow_log):
    # Older TREND_UP, newer TREND_DOWN — gate should use the newest.
    shadow_log([
        _row(_ts(200), "GBPUSD", "TREND_UP"),
        _row(_ts(30), "GBPUSD", "TREND_DOWN"),
    ])
    disagree, label, _ = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    assert disagree is True
    assert label == "TREND_DOWN"


def test_pair_isolation(shadow_log):
    # Newer USDJPY row must NOT shadow the older GBPUSD row for GBPUSD lookups.
    shadow_log([
        _row(_ts(60), "GBPUSD", "TREND_UP"),
        _row(_ts(10), "USDJPY", "TREND_DOWN"),
    ])
    disagree, label, _ = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    assert disagree is False
    assert label == "TREND_UP"


def test_malformed_lines_skipped(tmp_path, monkeypatch):
    p = tmp_path / "regime_shadow.jsonl"
    text = (
        '{"ts": "' + _ts(45) + '", "symbol": "GBPUSD", "stable": "TREND_DOWN"}\n'
        "not-json garbage line\n"
        '{"ts": "' + _ts(10) + '", "symbol": "GBPUSD", "stable":\n'  # truncated
    )
    p.write_text(text)
    monkeypatch.setenv(cascade_state.ENV_SHADOW_PATH, str(p))
    disagree, label, _ = cascade_state.cascade_disagrees("BUY", "GBPUSD", now_utc=NOW)
    # Truncated line is skipped, garbage line is skipped, first good row wins.
    assert disagree is True
    assert label == "TREND_DOWN"


# ────────────────────────────────────────────── forensic-record cascade fields

def test_forensic_record_carries_cascade_for_gbpusd(shadow_log):
    shadow_log([_row(_ts(30), "GBPUSD", "TREND_DOWN")])
    rec = forensic_logger._build_record(
        strategy="GBPUSD_BB_BOUNCE_L",
        direction="BUY",
        entry_price=1.3300,
        fire_bar_ts=NOW.isoformat(),
        snapshot_dict={"foo": "bar"},
    )
    assert rec["cascade_label_at_fire"] == "TREND_DOWN"
    assert isinstance(rec["cascade_age_seconds"], float)


def test_forensic_record_infers_pair_for_non_pair_prefix_via_param(shadow_log):
    # BRIEFING_EXECUTION isn't pair-prefixed → must pass pair= explicitly.
    shadow_log([_row(_ts(30), "EURUSD", "TREND_UP")])
    rec = forensic_logger._build_record(
        strategy="BRIEFING_EXECUTION",
        direction="BUY",
        entry_price=1.0900,
        fire_bar_ts=NOW.isoformat(),
        snapshot_dict={},
        pair="EURUSD",
    )
    assert rec["cascade_label_at_fire"] == "TREND_UP"


def test_forensic_record_null_when_pair_unknown(shadow_log):
    shadow_log([_row(_ts(30), "GBPUSD", "TREND_DOWN")])
    rec = forensic_logger._build_record(
        strategy="NEWS_TICK",  # not pair-prefixed, no pair= supplied
        direction="SELL",
        entry_price=1.2500,
        fire_bar_ts=NOW.isoformat(),
        snapshot_dict={},
    )
    assert rec["cascade_label_at_fire"] is None
    assert rec["cascade_age_seconds"] is None


# ──────────────────────────────────────────── counterfactual: Tuesday replay

LIVE_SHADOW = Path("/opt/tradingbot/logs/regime_shadow.jsonl")

# Per docs/cascade_accuracy_join_2026-05-12.md §4.1, only 2 of the 3 Tuesday
# BB_BOUNCE_L fires landed in the cascade-FALSE bucket:
#   06:35:03 → cascade TREND_DOWN → BLOCKED
#   11:10:20 → cascade NEUTRAL    → ALLOWED (audit row reads NEUTRAL/-9.95)
#   12:30:05 → cascade TREND_DOWN → BLOCKED
# The task framing claimed "all 3" but the audit data shows 2 — we assert
# the truthful outcomes, not the framing.
TUESDAY_FIRES = [
    ("2026-05-12T06:35:03+00:00", "TREND_DOWN", True),
    ("2026-05-12T11:10:20+00:00", "NEUTRAL",    False),
    ("2026-05-12T12:30:05+00:00", "TREND_DOWN", True),
]


@pytest.mark.skipif(
    not LIVE_SHADOW.exists(),
    reason="live regime_shadow.jsonl not present (skipped in detached envs)",
)
def test_counterfactual_tuesday_2026_05_12():
    # Read the live file and dump only the rows up to each fire ts into a
    # synthetic copy, then call cascade_disagrees with now_utc = fire_ts.
    # This insulates against re-running the test after later rows arrive.
    all_rows = []
    with LIVE_SHADOW.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                all_rows.append(json.loads(line))
            except Exception:
                continue
    assert all_rows, "live shadow log is unexpectedly empty"

    results = []
    for fire_ts_iso, expected_label, expected_block in TUESDAY_FIRES:
        fire_dt = datetime.fromisoformat(fire_ts_iso)
        # Build a synthetic file containing only rows up to fire_dt.
        relevant = [
            r for r in all_rows
            if (r.get("symbol") or "").upper() == "GBPUSD"
            and (r.get("ts") or "") <= fire_ts_iso
        ]
        assert relevant, f"no GBPUSD rows before {fire_ts_iso}"
        # Use a tmp file
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8",
        ) as tf:
            for r in relevant:
                tf.write(json.dumps(r) + "\n")
            tmp_path = tf.name
        try:
            os.environ[cascade_state.ENV_SHADOW_PATH] = tmp_path
            disagree, label, age = cascade_state.cascade_disagrees(
                "BUY", "GBPUSD", now_utc=fire_dt,
            )
            results.append((fire_ts_iso, label, disagree))
            assert label == expected_label, (
                f"{fire_ts_iso}: expected cascade={expected_label}, got {label}"
            )
            assert disagree is expected_block, (
                f"{fire_ts_iso}: expected block={expected_block}, got {disagree}"
            )
        finally:
            os.environ.pop(cascade_state.ENV_SHADOW_PATH, None)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # Visible summary for review.
    print("\nCounterfactual replay (live regime_shadow.jsonl):")
    for ts_iso, lbl, blocked in results:
        print(f"  {ts_iso} cascade={lbl} blocked={blocked}")
