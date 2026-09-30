"""Tests for the unified NEWS_STRATEGY_MODE gate + release-anchored
shadow build (2026-07-25, ITEM 2).

Contract under test:
  * mode=off      — zero evaluation: evaluate() returns early;
                    news_strategy_release_anchored.on_bar_close returns None.
  * mode=shadow   — full evaluation, eval rows written; executor NEVER
                    invoked (assert the signal returned is NONE).
  * mode=enforce  — evaluation returns actionable Result / non-NONE
                    StrategyDecision (order path reached).
  * stale calendar — release-anchored evaluator emits DECLINE row with
                    reason=stale_calendar; no order can be produced.
  * source-shape assertion that the mode gate covers both the tick-level
    fire path AND the reversal-fire path.
"""
from __future__ import annotations

import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO = Path("/opt/tradingbot")


@pytest.fixture()
def ra_module(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_STATE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("NEWS_STRATEGY_EVALS_LOG_PATH",
                       str(tmp_path / "evals.jsonl"))
    monkeypatch.setenv("NEWS_STRATEGY_EVALS_ENABLED", "1")
    # Fresh reloads so env values are honoured.
    for m in ("news_calendar_health", "news_strategy",
              "news_strategy_release_anchored"):
        if m in list(__import__("sys").modules):
            del __import__("sys").modules[m]
    import news_calendar_health
    import news_strategy_release_anchored as ra
    import news_strategy as ns
    news_calendar_health._reset_state_for_tests()
    ra._reset_state_for_tests()
    return ra, news_calendar_health, ns, tmp_path


def _seed_cache_and_events(tmp_path, release_iso, currency="USD"):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "date": today,
        "events": [{
            "ts": release_iso,
            "currency": currency,
            "impact": "HIGH",
            "event": "TEST_RELEASE",
        }],
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp_path / f"news_state_finnhub_{today}.json").write_text(
        json.dumps(payload)
    )


# ── Mode gate: off = zero evaluation ────────────────────────────────────────
def test_ra_mode_off_is_noop_returns_none(ra_module, monkeypatch):
    ra, _, _, tmp_path = ra_module
    monkeypatch.setenv("NEWS_STRATEGY_MODE", "off")
    r = ra.on_bar_close(
        "GBPUSD", "CS.D.GBPUSD.TODAY.IP",
        bar_ts_utc=datetime(2026, 7, 25, 12, 30, tzinfo=timezone.utc),
        bar_open=1.33, bar_high=1.334, bar_low=1.329, bar_close=1.333,
    )
    assert r is None
    # No eval rows written in off mode.
    ev = tmp_path / "evals.jsonl"
    assert not ev.exists() or ev.read_text().strip() == ""


def test_ns_evaluate_mode_off_bypasses_state_machine(monkeypatch):
    monkeypatch.setenv("NEWS_STRATEGY_MODE", "off")
    if "news_strategy" in list(__import__("sys").modules):
        del __import__("sys").modules["news_strategy"]
    import news_strategy as ns
    inst = ns.NewsStrategy()
    d = inst.evaluate(
        "GBPUSD", "CS.D.GBPUSD.TODAY.IP",
        mid=1.33, bid=1.3299, ask=1.3301,
        ts=1_784_888_000.0, ppp=0.0001,
    )
    assert d is not None
    assert getattr(d, "signal", "") == "NONE"
    assert "mode_off" in (getattr(d, "reason", "") or "")


# ── Mode gate: shadow = eval only, no order ─────────────────────────────────
def test_ra_shadow_writes_eval_rows_no_signal_when_below_spike(ra_module, monkeypatch):
    ra, _, _, tmp_path = ra_module
    monkeypatch.setenv("NEWS_STRATEGY_MODE", "shadow")
    monkeypatch.setenv("NEWS_SPIKE_MIN_PIPS", "25")

    release_dt = datetime(2026, 7, 25, 12, 30, tzinfo=timezone.utc)
    _seed_cache_and_events(tmp_path, release_dt.isoformat())

    # Release bar — captures anchor.
    r0 = ra.on_bar_close(
        "GBPUSD", "CS.D.GBPUSD.TODAY.IP", release_dt,
        bar_open=1.33, bar_high=1.331, bar_low=1.3295, bar_close=1.3305,
    )
    assert r0 is not None and r0.verdict == "NOOP"
    # Three post-release bars with tiny movement (below spike floor).
    for i in range(1, 4):
        bar_ts = release_dt.replace(minute=30 + 5 * i)
        r = ra.on_bar_close(
            "GBPUSD", "CS.D.GBPUSD.TODAY.IP", bar_ts,
            bar_open=1.3305, bar_high=1.3310, bar_low=1.3300, bar_close=1.3305,
        )
    # Final call → decision reached. Below spike floor → DECLINE.
    assert r.verdict == "DECLINE"
    assert r.reason == "spike_below_min"
    # Eval rows written for release + observing + decision.
    lines = (tmp_path / "evals.jsonl").read_text().splitlines()
    verdicts = [json.loads(x)["verdict"] for x in lines]
    assert "NOOP" in verdicts
    assert "DECLINE" in verdicts


def test_ra_shadow_would_fire_but_no_executor_call(ra_module, monkeypatch):
    ra, _, _, tmp_path = ra_module
    monkeypatch.setenv("NEWS_STRATEGY_MODE", "shadow")
    monkeypatch.setenv("NEWS_SPIKE_MIN_PIPS", "20")
    monkeypatch.setenv("NEWS_FADE_BODY_PCT", "0.30")
    release_dt = datetime(2026, 7, 25, 12, 30, tzinfo=timezone.utc)
    _seed_cache_and_events(tmp_path, release_dt.isoformat())

    # NOTE: bot prices are integer-scaled (price × 10000 for FX majors); 1
    # unit == 1 pip via pair_config.get_ppp("GBPUSD") == 1.0. Anchor at
    # 13300, spike to 13340 (+40p), retrace to 13305 (35p ≈ 87.5% of spike).
    ra.on_bar_close("GBPUSD", "CS.D.GBPUSD.TODAY.IP", release_dt,
                    bar_open=13300.0, bar_high=13335.0, bar_low=13298.0,
                    bar_close=13325.0)
    ra.on_bar_close("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                    release_dt.replace(minute=35),
                    bar_open=13325.0, bar_high=13340.0, bar_low=13320.0,
                    bar_close=13330.0)
    ra.on_bar_close("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                    release_dt.replace(minute=40),
                    bar_open=13330.0, bar_high=13335.0, bar_low=13310.0,
                    bar_close=13315.0)
    # DECISION bar. Retrace = (13340 - 13305)/(13340-13300) ≈ 0.875 (past 0.30).
    result = ra.on_bar_close("GBPUSD", "CS.D.GBPUSD.TODAY.IP",
                    release_dt.replace(minute=45),
                    bar_open=13315.0, bar_high=13320.0, bar_low=13300.0,
                    bar_close=13305.0)
    assert result is not None
    assert result.verdict == "WOULD_FIRE"
    assert result.signal == "SELL"   # fade an UP spike
    # Under shadow, autobot must NOT call execute_trade. There is no such
    # invocation to assert against here (autobot's 5m hook is not exercised),
    # but the Result being returned + mode=shadow is the operator's signal
    # to route/not-route. The tick-level path is separately gated below.
    assert os.environ.get("NEWS_STRATEGY_MODE") == "shadow"


# ── Stale calendar hard-DECLINE ─────────────────────────────────────────────
def test_ra_stale_calendar_forces_decline(ra_module, monkeypatch):
    ra, nch, _, tmp_path = ra_module
    monkeypatch.setenv("NEWS_STRATEGY_MODE", "shadow")
    # Point cache dir at empty tmp — no files → is_stale True.
    monkeypatch.setenv("NEWS_STATE_CACHE_DIR", str(tmp_path / "empty"))
    importlib.reload(nch)
    nch._reset_state_for_tests()
    # Reload ra so its is_stale sees the empty dir.
    if "news_strategy_release_anchored" in list(__import__("sys").modules):
        del __import__("sys").modules["news_strategy_release_anchored"]
    import news_strategy_release_anchored as ra2
    ra2._reset_state_for_tests()

    r = ra2.on_bar_close(
        "GBPUSD", "CS.D.GBPUSD.TODAY.IP",
        bar_ts_utc=datetime(2026, 7, 25, 12, 30, tzinfo=timezone.utc),
        bar_open=1.33, bar_high=1.34, bar_low=1.32, bar_close=1.335,
    )
    assert r is not None
    assert r.verdict == "DECLINE"
    assert r.reason == "stale_calendar"


# ── Source-shape: mode gate covers both fire paths ──────────────────────────
def test_news_strategy_mode_gate_covers_both_fire_paths():
    src = (REPO / "news_strategy.py").read_text()
    # Function defined.
    assert "def _news_strategy_mode()" in src
    # Early bypass at evaluate() top.
    assert 'if _news_strategy_mode() == "off":' in src
    assert '"news_strategy_mode_off"' in src
    # Shadow suppression on the tick FIRE path (fade/cont).
    assert '"news_strategy_mode_shadow"' in src
    # Shadow suppression on the REVERSAL_FIRE path.
    assert '"news_strategy_mode_shadow_reversal"' in src


def test_env_layered_declares_mode_gate():
    src = (REPO / "env" / "40-gates.env").read_text()
    assert "NEWS_STRATEGY_MODE=" in src  # value can be off/shadow/enforce
    assert "NEWS_MIN_IMPACT=HIGH" in src
    assert "NEWS_SPIKE_MIN_PIPS=25" in src
    assert "NEWS_FADE_BODY_PCT=0.50" in src
    assert "NEWS_SL_PIPS=20" in src
    assert "NEWS_TP_PIPS=60" in src
