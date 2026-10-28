"""Phase 4 — reconciliation output regression.

Smoke tests on the ledger + match summary produced by
`phase4_reconcile_trades.py`. These guard the fundamental counts and
the match-grade distribution so future runs can detect accidental
regressions in the extraction / matching pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def ledger():
    p = DATA / "trade_ledger.json"
    if not p.exists():
        pytest.skip(f"missing {p.name} — run phase4_reconcile_trades.py first")
    return json.loads(p.read_text())


@pytest.fixture
def summary():
    p = DATA / "trade_match_summary.json"
    if not p.exists():
        pytest.skip(f"missing {p.name}")
    return json.loads(p.read_text())["summary"]


def test_ledger_covers_expected_opens(summary):
    assert summary["ig_total_opens"] >= 300, summary["ig_total_opens"]
    assert summary["ledger_size"] == summary["ig_total_opens"]


def test_fully_reconciled_rate_above_70pc(summary):
    grades = summary["match_grades"]
    total = sum(grades.values())
    assert total > 0
    pct = 100.0 * grades.get("FULLY_RECONCILED", 0) / total
    assert pct > 70.0, f"FULLY_RECONCILED {pct:.1f}% below 70% threshold"


def test_pre_log_coverage_bucket_is_populated(summary):
    """Pre-2026-10-07 trades predate unified_trades.jsonl — they MUST
    land in PRE_LOG_COVERAGE, not UNATTRIBUTED."""
    assert "PRE_LOG_COVERAGE" in summary["match_grades"]


def test_source_system_distribution_includes_all_known_hosts(summary):
    srcs = set(summary["by_source_system"])
    assert "autobot" in srcs
    assert "bb_bounce_standalone" in srcs
    # EMA Pullback had some flow in the window
    assert "ema_pullback_standalone" in srcs


def test_ledger_entries_are_well_formed(ledger):
    for did, t in ledger.items():
        assert did.startswith("DI"), did
        assert "ig_open_date_utc" in t
        assert "ig_direction" in t
        assert "match_grade" in t
        assert t["source_system"] in {
            "autobot", "bb_bounce_standalone", "ema_pullback_standalone",
            "sibling_host_h144", "unknown_or_manual",
        }, (did, t["source_system"])


def test_sibling_host_or_pre_log_captures_all_unattributed(summary):
    """Everything we can't attribute to this host's internal logs should
    be bucketed into PRE_LOG_COVERAGE, UNATTRIBUTED_SIBLING_LIKELY,
    MANUAL_UI_INTERVENTION, or SIBLING_HOST — never raw UNATTRIBUTED."""
    assert "UNATTRIBUTED" not in summary["match_grades"], summary["match_grades"]
