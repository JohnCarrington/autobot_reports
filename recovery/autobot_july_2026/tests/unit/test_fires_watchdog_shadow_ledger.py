"""Tests for the SHADOW LEDGER extension in scripts/fires_watchdog.py.

These tests never touch the real journal or the real env-history directory.
Everything is injected via temp fixtures and the module-level entry points."""

from __future__ import annotations

import importlib.util
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPT_PATH = Path("/opt/tradingbot/scripts/fires_watchdog.py")


def _load_module(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "fires_watchdog_ledger_ut", str(SCRIPT_PATH)
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Wipe any prior file handlers so tests never accidentally write
    # to /opt/tradingbot/logs/fires_watchdog.log.
    for h in list(logging.getLogger("fires_watchdog").handlers):
        logging.getLogger("fires_watchdog").removeHandler(h)
    return mod


def _write_snapshot(dir_: Path, name: str, body: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    p.write_text(body, encoding="utf-8")
    return p


def _today_utc() -> datetime:
    return datetime(2026, 7, 27, 17, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# _parse_env_file
# ---------------------------------------------------------------------------

def test_parse_env_file_basic(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    p = tmp_path / "sample.env"
    p.write_text(
        "# comment\n\n"
        "FOO=bar\n"
        "BAZ = 'qux'\n"
        'QUUX="ha ha"\n'
        "BOGUS_LINE\n",
        encoding="utf-8",
    )
    d = mod._parse_env_file(p)
    assert d["FOO"] == "bar"
    assert d["BAZ"] == "qux"
    assert d["QUUX"] == "ha ha"
    assert "BOGUS_LINE" not in d


# ---------------------------------------------------------------------------
# _days_in_shadow
# ---------------------------------------------------------------------------

def test_days_in_shadow_exact(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    hist = tmp_path / "env-history"
    _write_snapshot(hist, "env.20260701T120000Z", "OTHER=1\n")
    _write_snapshot(hist, "env.20260710T120000Z", "MY_MODE=shadow\n")
    _write_snapshot(hist, "env.20260720T120000Z", "MY_MODE=shadow\n")
    today = _today_utc()
    days, method = mod._days_in_shadow("MY_MODE", today, hist)
    # today (2026-07-27) - 2026-07-10 = 17 days.
    assert method == "exact"
    assert days == "17"


def test_days_in_shadow_floor_when_not_in_any_snapshot(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    hist = tmp_path / "env-history"
    _write_snapshot(hist, "env.20260705T120000Z", "OTHER=1\n")
    _write_snapshot(hist, "env.20260710T120000Z", "OTHER=2\n")
    today = _today_utc()
    days, method = mod._days_in_shadow("MY_MODE", today, hist)
    # Oldest snapshot 2026-07-05 -> today - that = 22 days, prefixed "≥".
    assert method == "floor"
    assert days.startswith("≥")
    assert days.lstrip("≥").isdigit()
    assert int(days.lstrip("≥")) == 22


def test_days_in_shadow_unknown_when_empty_dir(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    hist = tmp_path / "env-history"
    hist.mkdir()
    today = _today_utc()
    days, method = mod._days_in_shadow("MY_MODE", today, hist)
    assert method == "unknown"
    assert days == "?"


# ---------------------------------------------------------------------------
# _resolve_mode
# ---------------------------------------------------------------------------

def test_resolve_mode_process_wins_when_agreeing(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("FOO_MODE=shadow\n", encoding="utf-8")
    disp, src = mod._resolve_mode("FOO_MODE",
                                  {"FOO_MODE": "shadow"},
                                  [env_path])
    assert disp == "shadow"
    assert src == "process"


def test_resolve_mode_file_when_no_process(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("FOO_MODE=shadow\n", encoding="utf-8")
    disp, src = mod._resolve_mode("FOO_MODE", None, [env_path])
    assert disp == "shadow"
    assert src == "file"


def test_resolve_mode_unset(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=1\n", encoding="utf-8")
    disp, src = mod._resolve_mode("FOO_MODE", {}, [env_path])
    assert disp == "unset"
    assert src == "unset"


def test_resolve_mode_process_file_mismatch_surfaced(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("FOO_MODE=off\n", encoding="utf-8")
    disp, src = mod._resolve_mode("FOO_MODE",
                                  {"FOO_MODE": "shadow"},
                                  [env_path])
    assert src == "process,file-mismatch"
    assert "shadow" in disp and "off" in disp


def test_resolve_mode_none_var_returns_htf_special(monkeypatch):
    mod = _load_module(monkeypatch)
    disp, src = mod._resolve_mode(None, None, [])
    assert src == "special"
    assert "HTF_AUTHORITY_ENFORCE" in disp
    assert "shadow" in disp


# ---------------------------------------------------------------------------
# Evidence collectors
# ---------------------------------------------------------------------------

def test_journal_bb_level_gate_counts_pass_and_would_block(monkeypatch):
    mod = _load_module(monkeypatch)
    text = (
        "[BB-LEVEL-GATE] verdict=PASS dist=1 mode=shadow\n"
        "[BB-LEVEL-GATE] verdict=PASS dist=2 mode=shadow\n"
        "[BB-LEVEL-GATE] verdict=WOULD_BLOCK dist=20 mode=shadow\n"
        "unrelated line\n"
    )
    assert mod._count_journal_bb_level_gate(text) == "PASS=2 WOULD_BLOCK=1"


def test_journal_runner_momentum_counts_hold_and_would_exit(monkeypatch):
    mod = _load_module(monkeypatch)
    text = (
        "[RUNNER-MOMENTUM] deal=X verdict=HOLD\n"
        "[RUNNER-MOMENTUM] deal=Y verdict=WOULD_EXIT\n"
        "[RUNNER-MOMENTUM] deal=Z verdict=WOULD_EXIT\n"
    )
    assert mod._count_journal_runner_momentum(text) == "HOLD=1 WOULD_EXIT=2"


def test_journal_htf_authority_counts_shadow_blocks(monkeypatch):
    mod = _load_module(monkeypatch)
    text = (
        "[HTF-AUTHORITY] PASS GBPUSD BUY X — SHADOW(PASS:LONG_with_TREND_UP)\n"
        "[HTF-AUTHORITY] PASS GBPUSD SELL X — SHADOW(BLOCKED:SHORT_counter_TREND_UP)\n"
        "[HTF-AUTHORITY] PASS EURUSD SELL Y — SHADOW(BLOCKED:SHORT_counter_TREND_UP)\n"
    )
    s = mod._count_journal_htf_authority(text)
    assert "SHADOW(BLOCKED)=2" in s


def test_news_strategy_jsonl_counts(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    p = tmp_path / "news_strategy_evals.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "ARMED"}) + "\n")
        fh.write(json.dumps({"kind": "WOULD_FIRE"}) + "\n")
        fh.write(json.dumps({"kind": "WOULD_FIRE"}) + "\n")
        fh.write(json.dumps({"kind": "SKIP_NO_ACTUALS"}) + "\n")
        fh.write(json.dumps({"kind": "DECLINE"}) + "\n")
    s = mod._count_news_strategy_jsonl(p)
    assert s == "WOULD_FIRE=2 DECLINE=2"


def test_news_momentum_jsonl_counts(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    p = tmp_path / "news_momentum_obs.jsonl"
    p.write_text('{"a":1}\n\n{"a":2}\n', encoding="utf-8")
    assert mod._count_news_momentum_jsonl(p) == "rows=2"


def test_news_strategy_jsonl_missing_file_raises(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    with pytest.raises(FileNotFoundError):
        mod._count_news_strategy_jsonl(tmp_path / "absent.jsonl")


# ---------------------------------------------------------------------------
# _collect_evidence resilience
# ---------------------------------------------------------------------------

def test_collect_evidence_yields_unavailable_on_missing_log(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    monkeypatch.setattr(mod, "NEWS_MOMENTUM_OBS_PATH", tmp_path / "nope.jsonl")
    spec = {"name": "NEWS_MOMENTUM", "mode_env": "NEWS_MOMENTUM_MODE",
            "evidence": "jsonl_news_momentum", "decision_due": "2026-08-10"}
    summary, ok = mod._collect_evidence(spec, _today_utc(), tmp_path,
                                        journal_fetcher=lambda since: "")
    assert not ok
    assert "unavailable" in summary


def test_collect_evidence_wraps_journal_exceptions(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    def _boom(since):
        raise RuntimeError("no_journal")
    spec = {"name": "BB_LEVEL_GATE", "mode_env": "BB_BOUNCE_LEVEL_GATE_MODE",
            "evidence": "journal_bb_level_gate", "decision_due": "2026-07-31"}
    summary, ok = mod._collect_evidence(spec, _today_utc(), tmp_path,
                                        journal_fetcher=_boom)
    assert not ok
    assert "unavailable" in summary and "no_journal" in summary


# ---------------------------------------------------------------------------
# End-to-end: _build_shadow_ledger — overdue sort, formatting, HTF special
# ---------------------------------------------------------------------------

def _fake_journal_fetcher(scripted: dict):
    """Return a fetcher that emits `scripted[since]` or a default. `since`
    is passed through unchanged so tests can key on the exact string if
    they wish, or just accept the default response for every call."""
    default = scripted.get("*", "")
    def fetch(since):
        return scripted.get(since, default)
    return fetch


def test_build_shadow_ledger_sorts_overdue_to_top(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    hist = tmp_path / "env-history"
    _write_snapshot(
        hist, "env.20260710T120000Z",
        "BB_BOUNCE_LEVEL_GATE_MODE=shadow\n"
        "RUNNER_MOMENTUM_CHECK_MODE=shadow\n"
        "NEWS_STRATEGY_MODE=off\n"
        "NEWS_MOMENTUM_MODE=off\n",
    )
    layered = tmp_path / ".env"
    layered.write_text(
        "BB_BOUNCE_LEVEL_GATE_MODE=shadow\n"
        "RUNNER_MOMENTUM_CHECK_MODE=shadow\n"
        "NEWS_STRATEGY_MODE=off\n"
        "NEWS_MOMENTUM_MODE=off\n",
        encoding="utf-8",
    )

    news_strat = tmp_path / "news_strategy_evals.jsonl"
    news_strat.write_text(
        json.dumps({"kind": "WOULD_FIRE"}) + "\n"
        + json.dumps({"kind": "DECLINE"}) + "\n",
        encoding="utf-8",
    )
    news_mom = tmp_path / "news_momentum_obs.jsonl"
    news_mom.write_text('{"a":1}\n{"a":2}\n{"a":3}\n', encoding="utf-8")
    monkeypatch.setattr(mod, "NEWS_STRATEGY_EVALS_PATH", news_strat)
    monkeypatch.setattr(mod, "NEWS_MOMENTUM_OBS_PATH", news_mom)

    journal_text = (
        "[BB-LEVEL-GATE] verdict=PASS dist=1 mode=shadow\n"
        "[BB-LEVEL-GATE] verdict=WOULD_BLOCK dist=20 mode=shadow\n"
        "[RUNNER-MOMENTUM] verdict=HOLD deal=X\n"
        "[HTF-AUTHORITY] PASS GBPUSD SELL X — SHADOW(BLOCKED:foo)\n"
        "[HTF-AUTHORITY] PASS GBPUSD SELL X — SHADOW(BLOCKED:foo)\n"
    )
    lines = mod._build_shadow_ledger(
        _today_utc(),
        env_history_dir=hist,
        layered_paths=[layered],
        process_env=None,
        journal_fetcher=lambda since: journal_text,
    )
    # First line is the header, then entries.
    assert lines[0] == "SHADOW LEDGER"
    body = lines[1:]
    # HTF_AUTHORITY is always overdue → must appear before the other
    # entries (whose decision-due dates in the registry are all in Aug/
    # late-Jul 2026 — every one lands *after* today=2026-07-27 EXCEPT
    # BB_LEVEL_GATE which is 2026-07-31, so it's NOT overdue). Assert:
    #   - HTF_AUTHORITY is first (or at least appears as OVERDUE)
    #   - every OVERDUE entry precedes every non-OVERDUE entry
    seen_non_overdue = False
    for l in body:
        is_over = l.startswith("OVERDUE ")
        if seen_non_overdue:
            assert not is_over, f"non-overdue seen before overdue: {body}"
        else:
            seen_non_overdue = not is_over
    # HTF_AUTHORITY must be OVERDUE.
    htf_line = next(l for l in body if "HTF_AUTHORITY" in l)
    assert htf_line.startswith("OVERDUE ")
    assert "HTF_AUTHORITY_ENFORCE" in htf_line
    # BB_LEVEL_GATE evidence must include PASS/WOULD_BLOCK split.
    bblg = next(l for l in body if "BB_LEVEL_GATE" in l)
    assert "PASS=1 WOULD_BLOCK=1" in bblg


def test_build_shadow_ledger_missing_evidence_source_unavailable(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    hist = tmp_path / "env-history"
    _write_snapshot(hist, "env.20260710T120000Z",
                    "NEWS_MOMENTUM_MODE=shadow\n")
    # Point news_momentum log at a non-existent file, no news_strategy log
    monkeypatch.setattr(mod, "NEWS_STRATEGY_EVALS_PATH",
                        tmp_path / "no_such_strat.jsonl")
    monkeypatch.setattr(mod, "NEWS_MOMENTUM_OBS_PATH",
                        tmp_path / "no_such_mom.jsonl")

    lines = mod._build_shadow_ledger(
        _today_utc(),
        env_history_dir=hist,
        layered_paths=[tmp_path / "does_not_exist.env"],
        process_env=None,
        journal_fetcher=lambda since: "",
    )
    body = "\n".join(lines)
    assert "SHADOW LEDGER" in body
    # Both news mechanisms show "unavailable"
    for name in ("NEWS_STRATEGY", "NEWS_MOMENTUM"):
        row = next(l for l in lines if l.startswith(name)
                   or l.startswith(f"OVERDUE {name}"))
        assert "unavailable" in row


def test_build_shadow_ledger_unset_mode_shown(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    hist = tmp_path / "env-history"
    _write_snapshot(hist, "env.20260710T120000Z", "OTHER=1\n")  # no mode vars
    monkeypatch.setattr(mod, "NEWS_STRATEGY_EVALS_PATH",
                        tmp_path / "absent_strat.jsonl")
    monkeypatch.setattr(mod, "NEWS_MOMENTUM_OBS_PATH",
                        tmp_path / "absent_mom.jsonl")
    lines = mod._build_shadow_ledger(
        _today_utc(),
        env_history_dir=hist,
        layered_paths=[tmp_path / "empty.env"],
        process_env={},
        journal_fetcher=lambda since: "",
    )
    body = "\n".join(lines)
    # All non-HTF mechanisms should render mode as "unset".
    for name in ("BB_LEVEL_GATE", "RUNNER_MOMENTUM",
                 "NEWS_STRATEGY", "NEWS_MOMENTUM"):
        row = next(l for l in lines if name in l)
        assert " unset " in row, row


# ---------------------------------------------------------------------------
# _combine_digest_and_ledger
# ---------------------------------------------------------------------------

def test_combine_ledger_appends_when_within_budget(monkeypatch):
    mod = _load_module(monkeypatch)
    msgs, appended = mod._combine_digest_and_ledger(
        "SILENT TODAY: FOO", ["SHADOW LEDGER", "BB_LEVEL_GATE  shadow 3d ..."]
    )
    assert appended is True
    assert len(msgs) == 1
    assert msgs[0].startswith("SILENT TODAY: FOO")
    assert "SHADOW LEDGER" in msgs[0]


def test_combine_ledger_splits_when_over_budget(monkeypatch):
    mod = _load_module(monkeypatch)
    big_digest = "X" * (mod.TELEGRAM_MAX_CHARS - 10)
    msgs, appended = mod._combine_digest_and_ledger(
        big_digest, ["SHADOW LEDGER", "line1", "line2"]
    )
    assert appended is False
    assert len(msgs) == 2
    assert msgs[0] == big_digest
    assert msgs[1].startswith("SHADOW LEDGER")


def test_combine_ledger_standalone_when_no_digest(monkeypatch):
    mod = _load_module(monkeypatch)
    msgs, appended = mod._combine_digest_and_ledger(
        None, ["SHADOW LEDGER", "line1"]
    )
    assert appended is False
    assert len(msgs) == 1
    assert msgs[0].startswith("SHADOW LEDGER")


# ---------------------------------------------------------------------------
# _run — end-to-end mocked; verifies digest STILL SENDS when evidence
# collection has failures
# ---------------------------------------------------------------------------

def test_run_still_sends_when_ledger_evidence_unavailable(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)

    # Empty signal log → no silent digest.
    sig = tmp_path / "signal_log.jsonl"
    sig.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod, "SIGNAL_LOG", sig)
    monkeypatch.setattr(mod, "LOG_FILE", tmp_path / "logs" / "fires_watchdog.log")

    # env-history with one snapshot but no mode vars.
    hist = tmp_path / "env-history"
    _write_snapshot(hist, "env.20260710T120000Z", "OTHER=1\n")
    monkeypatch.setattr(mod, "ENV_HISTORY_DIR", hist)
    monkeypatch.setattr(mod, "LAYERED_ENV_FILES",
                        [tmp_path / "missing.env"])

    # Point all evidence sources at non-existent files.
    monkeypatch.setattr(mod, "NEWS_STRATEGY_EVALS_PATH",
                        tmp_path / "absent_strat.jsonl")
    monkeypatch.setattr(mod, "NEWS_MOMENTUM_OBS_PATH",
                        tmp_path / "absent_mom.jsonl")

    # No live process env; journal fetcher raises → journal-based rows
    # collapse to unavailable — but overall digest MUST still send.
    monkeypatch.setattr(mod, "_read_service_environ", lambda: None)
    def _boom_fetcher(since):
        raise RuntimeError("journal_gone")
    monkeypatch.setattr(mod, "_run_journal_since", _boom_fetcher)

    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda text, log: sent.append(text))

    assert mod.main() == 0
    assert len(sent) == 1, sent
    assert "SHADOW LEDGER" in sent[0]
    # Every mechanism appears (some with unavailable, some with unset).
    for name in ("BB_LEVEL_GATE", "RUNNER_MOMENTUM",
                 "NEWS_STRATEGY", "NEWS_MOMENTUM", "HTF_AUTHORITY"):
        assert name in sent[0], name


def test_run_sends_ledger_when_journal_and_logs_present(tmp_path, monkeypatch):
    mod = _load_module(monkeypatch)
    sig = tmp_path / "signal_log.jsonl"
    sig.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod, "SIGNAL_LOG", sig)
    monkeypatch.setattr(mod, "LOG_FILE", tmp_path / "logs" / "fires_watchdog.log")

    hist = tmp_path / "env-history"
    _write_snapshot(
        hist, "env.20260710T120000Z",
        "BB_BOUNCE_LEVEL_GATE_MODE=shadow\n"
        "RUNNER_MOMENTUM_CHECK_MODE=shadow\n"
        "NEWS_STRATEGY_MODE=off\n"
        "NEWS_MOMENTUM_MODE=shadow\n",
    )
    monkeypatch.setattr(mod, "ENV_HISTORY_DIR", hist)
    layered = tmp_path / ".env"
    layered.write_text(
        "BB_BOUNCE_LEVEL_GATE_MODE=shadow\n"
        "RUNNER_MOMENTUM_CHECK_MODE=shadow\n"
        "NEWS_STRATEGY_MODE=off\n"
        "NEWS_MOMENTUM_MODE=shadow\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "LAYERED_ENV_FILES", [layered])

    news_strat = tmp_path / "news_strategy_evals.jsonl"
    news_strat.write_text(
        json.dumps({"kind": "WOULD_FIRE"}) + "\n"
        + json.dumps({"kind": "SKIP_NO_ACTUALS"}) + "\n",
        encoding="utf-8",
    )
    news_mom = tmp_path / "news_momentum_obs.jsonl"
    news_mom.write_text('{"a":1}\n', encoding="utf-8")
    monkeypatch.setattr(mod, "NEWS_STRATEGY_EVALS_PATH", news_strat)
    monkeypatch.setattr(mod, "NEWS_MOMENTUM_OBS_PATH", news_mom)

    monkeypatch.setattr(mod, "_read_service_environ", lambda: None)
    def _fetch(since):
        return (
            "[BB-LEVEL-GATE] verdict=PASS dist=1 mode=shadow\n"
            "[BB-LEVEL-GATE] verdict=WOULD_BLOCK dist=20 mode=shadow\n"
            "[RUNNER-MOMENTUM] verdict=HOLD\n"
            "[RUNNER-MOMENTUM] verdict=WOULD_EXIT\n"
            "[HTF-AUTHORITY] PASS X — SHADOW(BLOCKED:foo)\n"
        )
    monkeypatch.setattr(mod, "_run_journal_since", _fetch)

    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda text, log: sent.append(text))

    assert mod.main() == 0
    assert len(sent) == 1
    body = sent[0]
    assert "PASS=1 WOULD_BLOCK=1" in body
    assert "HOLD=1 WOULD_EXIT=1" in body
    assert "SHADOW(BLOCKED)=1" in body
    assert "WOULD_FIRE=1 DECLINE=1" in body
    assert "rows=1" in body
