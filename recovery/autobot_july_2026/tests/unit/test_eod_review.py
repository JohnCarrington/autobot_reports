"""Tests for scripts/eod_review_metrics.py and eod_review_narrative.py.

Covers: cash-math correctness across TRADE_SIZE eras and scaled/unscaled
fires; empty-day graceful output; missing metrics json → narrative
degrades; email gate; malformed jsonl skipping.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path("/opt/tradingbot")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture
def metrics_mod(monkeypatch, tmp_path):
    """Import eod_review_metrics with LOG_DIR/REPORTS_DIR rerouted into
    a tmp workspace so tests don't touch prod logs/reports."""
    mod = importlib.import_module("eod_review_metrics")
    importlib.reload(mod)  # picks up any monkeypatched paths
    logs = tmp_path / "logs"
    reports = tmp_path / "reports" / "eod"
    logs.mkdir(parents=True)
    reports.mkdir(parents=True)
    monkeypatch.setattr(mod, "LOG_DIR", logs)
    monkeypatch.setattr(mod, "REPORTS_DIR", reports)
    monkeypatch.setattr(mod, "SIGNAL_LOG", logs / "signal_log.jsonl")
    monkeypatch.setattr(mod, "ERROR_LOG", logs / "eod_review.log")
    return mod, logs, reports


@pytest.fixture
def narrative_mod(monkeypatch, tmp_path):
    mod = importlib.import_module("eod_review_narrative")
    importlib.reload(mod)
    logs = tmp_path / "logs"
    reports = tmp_path / "reports" / "eod"
    logs.mkdir(parents=True)
    reports.mkdir(parents=True)
    monkeypatch.setattr(mod, "LOG_DIR", logs)
    monkeypatch.setattr(mod, "REPORTS_DIR", reports)
    monkeypatch.setattr(mod, "SIGNAL_LOG", logs / "signal_log.jsonl")
    monkeypatch.setattr(mod, "JOURNAL_LOG", logs / "daily_journal.jsonl")
    monkeypatch.setattr(mod, "ERROR_LOG", logs / "eod_review.log")
    return mod, logs, reports


def _write_signal_log(path: Path, rows):
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _row(ts_open, strat, pnl_pips=None, total_pnl_pips=None,
         scaled_out=False, partial_bank_pips=None, close_reason=None,
         direction="BUY", entry=1.30, close_price=None, pair="GBPUSD"):
    """Build a minimal signal_log row. Only the fields the scripts read."""
    r = {
        "id": f"test-{ts_open}",
        "deal_id": f"DEAL-{ts_open}",
        "timestamp_open": ts_open,
        "pair": pair,
        "strategy": strat,
        "direction": direction,
        "entry": entry,
    }
    if pnl_pips is not None:
        r["pnl_pips"] = pnl_pips
    if total_pnl_pips is not None:
        r["total_pnl_pips"] = total_pnl_pips
    if scaled_out:
        r["scaled_out"] = True
    if partial_bank_pips is not None:
        r["partial_bank_pips"] = partial_bank_pips
    if close_reason is not None:
        r["close_reason"] = close_reason
        r["timestamp_close"] = ts_open  # marker of closure
    if close_price is not None:
        r["close_price"] = close_price
    return r


# ---------------------------------------------------------------------------
# METRICS: cash math per fire, across TRADE_SIZE eras
# ---------------------------------------------------------------------------

def test_metrics_cash_math_size_1(metrics_mod, monkeypatch):
    """With TRADE_SIZE=1, cash on unscaled = pips × 1; scaled = total × 0.5."""
    mod, logs, _ = metrics_mod
    monkeypatch.setenv("TRADE_SIZE", "1")
    rows = [
        # Size-1 era unscaled fires: cash == pnl_pips × 1
        _row("2026-05-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
        _row("2026-05-01T10:00:00Z", "BB_L", pnl_pips=-5.0,
             total_pnl_pips=-5.0, close_reason="SL hit"),
        # Size-1 era scaled fire: cash == total × (1/2) = 8 × 0.5 = 4.0
        _row("2026-05-01T11:00:00Z", "BB_S", pnl_pips=-2.0,
             total_pnl_pips=8.0, scaled_out=True, partial_bank_pips=10.0,
             close_reason="TRAIL_STOP"),
    ]
    _write_signal_log(logs / "signal_log.jsonl", rows)

    m = mod.build_metrics(date(2026, 5, 1))
    assert m["totals"]["fills"] == 3
    # 2026-07-29: pips are now size-weighted so pips × TRADE_SIZE == cash.
    # Scaled fire (total=8): 1-unit-equivalent pips = 8/2 = 4.
    # Total: 10 - 5 + 4 = 9. cash: 10 - 5 + 4 = 9 (TRADE_SIZE=1). ratio 1.0.
    assert m["totals"]["net_pips"] == pytest.approx(9.0)
    assert m["totals"]["net_cash_gbp"] == pytest.approx(9.0)
    assert m["scale_out_count"] == 1
    assert m["runner_exit_reasons"] == {"TRAIL_STOP": 1}


def test_metrics_cash_math_size_2(metrics_mod, monkeypatch):
    """With TRADE_SIZE=2, unscaled cash doubles; scaled cash == total × 1."""
    mod, logs, _ = metrics_mod
    monkeypatch.setenv("TRADE_SIZE", "2")
    rows = [
        _row("2026-07-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
        _row("2026-07-01T10:00:00Z", "BB_L", pnl_pips=-5.0,
             total_pnl_pips=-5.0, close_reason="SL hit"),
        _row("2026-07-01T11:00:00Z", "BB_S", pnl_pips=-2.0,
             total_pnl_pips=8.0, scaled_out=True, partial_bank_pips=10.0,
             close_reason="BE_STOP_POST_SCALEOUT"),
    ]
    _write_signal_log(logs / "signal_log.jsonl", rows)

    m = mod.build_metrics(date(2026, 7, 1))
    # 2026-07-29: size-weighted pips reconcile with cash at ×TRADE_SIZE.
    # Scaled fire (total=8): 1-unit-equivalent pips = 8/2 = 4.
    # Total: 10 - 5 + 4 = 9. cash: 10*2 + (-5)*2 + 8*(2/2) = 18. ratio 2.0.
    assert m["totals"]["net_pips"] == pytest.approx(9.0)
    assert m["totals"]["net_cash_gbp"] == pytest.approx(18.0)
    assert m["totals"]["net_cash_gbp"] == pytest.approx(
        m["totals"]["net_pips"] * 2.0
    )
    assert m["runner_exit_reasons"] == {"BE_STOP_POST_SCALEOUT": 1}


def test_metrics_mixed_era_rows(metrics_mod, monkeypatch):
    """Corpus mixes size-1 and size-2 era rows in a single day (edge case
    if TRADE_SIZE was changed mid-day). Current TRADE_SIZE applies
    uniformly — this is the known convention (see daily_journal.py:373).
    """
    mod, logs, _ = metrics_mod
    monkeypatch.setenv("TRADE_SIZE", "2")
    # Both rows same day; whatever their historical fill size, cash
    # here reflects the *current* TRADE_SIZE. That's intentional.
    rows = [
        _row("2026-07-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
        _row("2026-07-01T10:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
    ]
    _write_signal_log(logs / "signal_log.jsonl", rows)
    m = mod.build_metrics(date(2026, 7, 1))
    # 20p × TRADE_SIZE 2 = £40
    assert m["totals"]["net_cash_gbp"] == pytest.approx(40.0)


def test_metrics_empty_day_writes_no_fills(metrics_mod, monkeypatch, capsys):
    mod, logs, reports = metrics_mod
    monkeypatch.setenv("TRADE_SIZE", "2")
    _write_signal_log(logs / "signal_log.jsonl", [
        _row("2026-05-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
    ])
    # Target a *different* date — no rows.
    rc = mod.main(["--date", "2026-05-02"])
    assert rc == 0
    md = (reports / "metrics_2026-05-02.md").read_text()
    assert "No fills on this date." in md
    js = json.loads((reports / "metrics_2026-05-02.json").read_text())
    assert js["totals"]["fills"] == 0


def test_metrics_malformed_jsonl_skipped_not_fatal(metrics_mod, monkeypatch):
    mod, logs, _ = metrics_mod
    monkeypatch.setenv("TRADE_SIZE", "2")
    path = logs / "signal_log.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_row("2026-07-01T09:00:00Z", "BB_L",
                                 pnl_pips=10.0, total_pnl_pips=10.0,
                                 close_reason="TP hit")) + "\n")
        fh.write("{this is not valid json\n")
        fh.write("\n")  # blank line
        fh.write(json.dumps(_row("2026-07-01T11:00:00Z", "BB_L",
                                 pnl_pips=5.0, total_pnl_pips=5.0,
                                 close_reason="TP hit")) + "\n")
    m = mod.build_metrics(date(2026, 7, 1))
    assert m["totals"]["fills"] == 2
    assert m["totals"]["net_pips"] == pytest.approx(15.0)


def test_metrics_open_positions_detected(metrics_mod, monkeypatch):
    mod, logs, _ = metrics_mod
    monkeypatch.setenv("TRADE_SIZE", "2")
    rows = [
        _row("2026-07-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
        # Open: no close_reason, no pnl fields, no close timestamp.
        _row("2026-07-01T15:00:00Z", "BB_S", direction="SELL"),
    ]
    _write_signal_log(logs / "signal_log.jsonl", rows)
    m = mod.build_metrics(date(2026, 7, 1))
    assert len(m["open_positions"]) == 1
    assert m["open_positions"][0]["strategy"] == "BB_S"


def test_metrics_missing_new_telemetry_columns_ok(metrics_mod, monkeypatch):
    """Rows from earlier eras lack many of the newer fields (session_adx,
    regime_at_fire, close_reason, etc.). Metrics must not crash on
    their absence and must still count realised pnl when pnl_pips is
    the only close-marker present (older rows didn't always set
    close_reason)."""
    mod, logs, _ = metrics_mod
    monkeypatch.setenv("TRADE_SIZE", "2")
    minimal_closed = {
        "id": "old-row",
        "timestamp_open": "2026-03-30T06:25:07Z",
        "pair": "GBPUSD",
        "strategy": "BRIEFING_SWEEP",
        "pnl_pips": 19.0,  # realised — the only close marker on this era
    }
    minimal_open = {
        "id": "old-open",
        "timestamp_open": "2026-03-30T07:00:00Z",
        "pair": "GBPUSD",
        "strategy": "BRIEFING_SWEEP",
        # No pnl_pips, no close_reason — genuinely open.
    }
    _write_signal_log(logs / "signal_log.jsonl",
                      [minimal_closed, minimal_open])
    m = mod.build_metrics(date(2026, 3, 30))
    assert m["totals"]["fills"] == 2
    assert m["totals"]["net_pips"] == pytest.approx(19.0)
    assert m["totals"]["net_cash_gbp"] == pytest.approx(38.0)
    assert len(m["open_positions"]) == 1


def test_metrics_top_level_exception_exits_zero(metrics_mod, monkeypatch):
    """Any uncaught exception inside main() must be swallowed to exit 0."""
    mod, logs, _ = metrics_mod

    def _blow_up(_day):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(mod, "build_metrics", _blow_up)
    rc = mod.main([])
    assert rc == 0
    assert (logs / "eod_review.log").exists()


# ---------------------------------------------------------------------------
# NARRATIVE: degradation, email gate, missing json, malformed inputs
# ---------------------------------------------------------------------------

def test_narrative_missing_metrics_still_writes_and_sends(
    narrative_mod, monkeypatch
):
    """No metrics json on disk → narrative still writes, still attempts
    email (respecting the gate)."""
    mod, logs, reports = narrative_mod
    monkeypatch.setenv("EOD_REVIEW_EMAIL_ENABLED", "1")
    _write_signal_log(logs / "signal_log.jsonl", [
        _row("2026-07-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
    ])

    sent = {"count": 0, "subject": None, "body": None}

    def _fake_send(subject, body):
        sent["count"] += 1
        sent["subject"] = subject
        sent["body"] = body
        return (True, "status=202")

    monkeypatch.setattr(mod, "_send_review_email", _fake_send)

    rc = mod.main(["--date", "2026-07-01"])
    assert rc == 0
    md = (reports / "review_2026-07-01.md").read_text()
    assert "Metrics unavailable" in md
    assert "BB_L" in md  # per-trade narrative still populated
    assert sent["count"] == 1
    assert sent["subject"] == "AutoBot EOD Review — 2026-07-01"


def test_narrative_gate_flag_off_does_not_send(narrative_mod, monkeypatch):
    mod, logs, reports = narrative_mod
    monkeypatch.setenv("EOD_REVIEW_EMAIL_ENABLED", "0")
    _write_signal_log(logs / "signal_log.jsonl", [
        _row("2026-07-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
    ])

    sent = {"count": 0}

    def _fake_send(subject, body):
        sent["count"] += 1
        return (True, "status=202")

    monkeypatch.setattr(mod, "_send_review_email", _fake_send)

    rc = mod.main(["--date", "2026-07-01"])
    assert rc == 0
    assert sent["count"] == 0
    # But the MD is still written.
    assert (reports / "review_2026-07-01.md").exists()


def test_narrative_gate_flag_defaults_to_on(narrative_mod, monkeypatch):
    """Task-specified default: EOD_REVIEW_EMAIL_ENABLED unset → send."""
    mod, logs, reports = narrative_mod
    monkeypatch.delenv("EOD_REVIEW_EMAIL_ENABLED", raising=False)
    _write_signal_log(logs / "signal_log.jsonl", [
        _row("2026-07-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
    ])
    sent = {"count": 0}

    def _fake_send(subject, body):
        sent["count"] += 1
        return (True, "status=202")

    monkeypatch.setattr(mod, "_send_review_email", _fake_send)
    rc = mod.main(["--date", "2026-07-01"])
    assert rc == 0
    assert sent["count"] == 1


def test_narrative_empty_day_produces_no_fires_output(
    narrative_mod, monkeypatch
):
    mod, logs, reports = narrative_mod
    monkeypatch.setenv("EOD_REVIEW_EMAIL_ENABLED", "0")
    (logs / "signal_log.jsonl").write_text("")
    rc = mod.main(["--date", "2026-07-02"])
    assert rc == 0
    md = (reports / "review_2026-07-02.md").read_text()
    assert "No fires today." in md


def test_narrative_send_failure_still_writes(narrative_mod, monkeypatch):
    mod, logs, reports = narrative_mod
    monkeypatch.setenv("EOD_REVIEW_EMAIL_ENABLED", "1")
    _write_signal_log(logs / "signal_log.jsonl", [
        _row("2026-07-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
    ])

    def _fake_send(subject, body):
        return (False, "SendGrid 401: unauthorised")

    monkeypatch.setattr(mod, "_send_review_email", _fake_send)
    rc = mod.main(["--date", "2026-07-01"])
    assert rc == 0
    assert (reports / "review_2026-07-01.md").exists()


def test_narrative_metrics_read_when_present(narrative_mod, monkeypatch):
    mod, logs, reports = narrative_mod
    monkeypatch.setenv("EOD_REVIEW_EMAIL_ENABLED", "0")
    _write_signal_log(logs / "signal_log.jsonl", [
        _row("2026-07-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
    ])
    # Write a fake metrics json for the same date; narrative should
    # pick it up.
    metrics_json = {
        "date": "2026-07-01",
        "generated_at_utc": "2026-07-01T22:05:00+00:00",
        "trade_size_used": 2.0,
        "totals": {"fills": 1, "wins": 1, "losses": 0, "scratches": 0,
                   "net_pips": 10.0, "net_cash_gbp": 20.0},
        "per_strategy": {"BB_L": {"fills": 1, "wins": 1, "losses": 0,
                                  "scratches": 0, "net_pips": 10.0,
                                  "net_cash_gbp": 20.0}},
        "scale_out_count": 0,
        "runner_exit_reasons": {},
        "open_positions": [],
        "rows_read": 1,
    }
    (reports / "metrics_2026-07-01.json").write_text(json.dumps(metrics_json))
    rc = mod.main(["--date", "2026-07-01"])
    assert rc == 0
    md = (reports / "review_2026-07-01.md").read_text()
    assert "1 fills" in md
    assert "£+20.00" in md
    assert "Metrics unavailable" not in md


def test_narrative_malformed_jsonl_skipped_not_fatal(
    narrative_mod, monkeypatch
):
    mod, logs, reports = narrative_mod
    monkeypatch.setenv("EOD_REVIEW_EMAIL_ENABLED", "0")
    path = logs / "signal_log.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write("{corrupt line\n")
        fh.write(json.dumps(_row("2026-07-01T09:00:00Z", "BB_L",
                                 pnl_pips=10.0, total_pnl_pips=10.0,
                                 close_reason="TP hit")) + "\n")
    rc = mod.main(["--date", "2026-07-01"])
    assert rc == 0
    md = (reports / "review_2026-07-01.md").read_text()
    assert "BB_L" in md


def test_narrative_top_level_exception_exits_zero(narrative_mod, monkeypatch):
    mod, logs, _ = narrative_mod

    def _blow_up(_day):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(mod, "_rows_for_day", _blow_up)
    # _rows_for_day is caught inside main's inner try/except so does
    # NOT reach top-level. Force top-level by breaking write instead:
    def _bad_build(*a, **k):
        raise RuntimeError("top-level failure")

    monkeypatch.setattr(mod, "_build_narrative", _bad_build)
    rc = mod.main([])
    assert rc == 0
    assert (mod.LOG_DIR / "eod_review.log").exists()


def test_narrative_gate_counts_missing_files_are_zero(
    narrative_mod, monkeypatch
):
    """None of the GATE_LOGS files exist in the test tmp dir → all
    counts should read 0 without raising."""
    mod, logs, reports = narrative_mod
    monkeypatch.setenv("EOD_REVIEW_EMAIL_ENABLED", "0")
    _write_signal_log(logs / "signal_log.jsonl", [])
    rc = mod.main(["--date", "2026-07-01"])
    assert rc == 0
    md = (reports / "review_2026-07-01.md").read_text()
    assert "All monitored gates recorded 0 events for the day." in md


def test_narrative_reads_journal_entry(narrative_mod, monkeypatch):
    mod, logs, reports = narrative_mod
    monkeypatch.setenv("EOD_REVIEW_EMAIL_ENABLED", "0")
    _write_signal_log(logs / "signal_log.jsonl", [
        _row("2026-07-01T09:00:00Z", "BB_L", pnl_pips=10.0,
             total_pnl_pips=10.0, close_reason="TP hit"),
    ])
    (logs / "daily_journal.jsonl").write_text(
        json.dumps({"date": "2026-07-01", "day_type": "trend",
                    "flags": [{"code": "trend_day"}, {"code": "clean_run"}],
                    "suggestions": []}) + "\n"
    )
    rc = mod.main(["--date", "2026-07-01"])
    assert rc == 0
    md = (reports / "review_2026-07-01.md").read_text()
    assert "2 flag(s)" in md
