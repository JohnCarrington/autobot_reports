"""Tests for the news_strategy per-evaluation telemetry (2026-07-25).

Covers:
  - _snapshot_news_telemetry returns the full spec-field key set for
    every path shape (fire, decline, null calendar).
  - Null calendar data / missing state fields do NOT raise.
  - _log_eval appends one JSON row per call and is a no-op when the
    NEWS_STRATEGY_EVALS_ENABLED gate is off.
  - _emit_eval returns the snapshot and persists it.
  - entry_side_vs_spike mapping is correct for FADE / CONT / REVERSAL.
  - The signal_logger log_open record whitelists news_telemetry.
"""

from __future__ import annotations

import json
import os
import importlib
from collections import deque
from pathlib import Path

import pytest


@pytest.fixture()
def ns_module(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "NEWS_STRATEGY_EVALS_LOG_PATH", str(tmp_path / "evals.jsonl")
    )
    monkeypatch.setenv("NEWS_STRATEGY_EVALS_ENABLED", "1")
    import news_strategy as ns
    importlib.reload(ns)
    return ns


# ── Full-schema fields ─────────────────────────────────────────────────────
SPEC_KEYS = {
    "kind", "ts_utc", "symbol", "epic", "phase", "leg", "signal",
    "decision_reason", "release_key", "release_name", "release_currency",
    "scheduled_time_iso", "seconds_from_release", "since_spike_secs",
    "surprise_direction", "surprise_beat_miss", "surprise_deviation",
    "surprise_actual", "surprise_forecast", "pre_release_range_pips",
    "spike_magnitude_pips", "spike_direction", "entry_side_vs_spike",
    "atr_at_trigger_pips", "atr_at_trigger_source",
}


def test_snapshot_returns_full_spec_schema_on_empty_state(ns_module):
    tele = ns_module._snapshot_news_telemetry(
        symbol="GBPUSD", epic="CS.D.GBPUSD.TODAY.IP",
        st={}, ts=0.0, mid=None, ppp=None, kind="PROBE",
    )
    assert SPEC_KEYS.issubset(set(tele.keys()))
    # All spec fields tolerate empty inputs and yield None (never raise).
    for k in SPEC_KEYS - {"kind", "ts_utc", "symbol", "epic"}:
        assert tele[k] is None, (k, tele[k])


def test_snapshot_null_calendar_state_does_not_raise(ns_module):
    # state with missing release_epoch / event_name / te_result — must not raise
    st = {"phase": "IDLE", "tick_history": deque()}
    tele = ns_module._snapshot_news_telemetry(
        symbol="GBPUSD", epic=None,
        st=st, ts=1_784_888_000.0, mid=1.33, ppp=0.0001,
        kind="ARMED",
    )
    assert tele["kind"] == "ARMED"
    assert tele["release_name"] is None
    assert tele["release_key"] is None
    assert tele["scheduled_time_iso"] is None


def test_snapshot_populates_spike_and_range_fields(ns_module):
    # Build a synthetic tick_history around a fake release + spike.
    ppp = 0.0001
    release = 1_784_888_000.0
    anchor = 1.3300
    # 5 minutes pre-release ticks with a 4p range
    hist = deque()
    for i in range(30):
        t = release - 300 + i * 10  # 30 ticks over 300s
        # walk price ±0.0002 to give a 4p pre-range
        mid = anchor + (0.00005 if i % 2 else -0.00015)
        hist.append((t, mid))
    # 5 minutes post-release ticks that spike UP by 12p
    for i in range(20):
        t = release + i * 15
        mid = anchor + 0.0012  # +12p
        hist.append((t, mid))
    spike_time = release + 60
    spike_extreme = anchor + 0.0018  # +18p
    st = {
        "phase": "NEWS_CONSOLIDATION_TRACKING",
        "tick_history": hist,
        "release_epoch": release,
        "event_name": "US CPI",
        "event_currency": "USD",
        "anchor": anchor,
        "spike_extreme": spike_extreme,
        "spike_time": spike_time,
        "spike_dir": "UP",
        "leg": "FADE",
        "te_result": {
            "direction_hint": "REVERSAL",
            "beat_miss": "BEAT",
            "deviation": 0.03,
            "actual": 3.2, "forecast": 3.1,
        },
    }
    now = release + 400
    tele = ns_module._snapshot_news_telemetry(
        symbol="GBPUSD", epic="CS.D.GBPUSD.TODAY.IP",
        st=st, ts=now, mid=anchor + 0.0005, ppp=ppp,
        kind="FIRE", signal="SELL", decision_reason="news_strategy_fade_sell",
    )
    assert tele["release_name"] == "US CPI"
    assert tele["release_currency"] == "USD"
    assert tele["release_key"] == f"US CPI|{int(release)}"
    assert tele["surprise_direction"] == "REVERSAL"
    assert tele["surprise_beat_miss"] == "BEAT"
    assert tele["surprise_deviation"] == 0.03
    assert tele["spike_direction"] == "UP"
    assert tele["spike_magnitude_pips"] == pytest.approx(18.0, abs=0.01)
    assert tele["seconds_from_release"] == pytest.approx(400.0)
    assert tele["since_spike_secs"] == pytest.approx(now - spike_time)
    assert tele["pre_release_range_pips"] is not None
    assert tele["pre_release_range_pips"] > 0
    assert tele["entry_side_vs_spike"] == "fade"  # FADE leg
    assert tele["atr_at_trigger_pips"] is not None  # 5m proxy filled


def test_entry_side_vs_spike_mapping(ns_module):
    assert ns_module._entry_side_vs_spike("FADE") == "fade"
    assert ns_module._entry_side_vs_spike("CONTINUATION") == "follow"
    assert ns_module._entry_side_vs_spike("REVERSAL") == "fade"
    assert ns_module._entry_side_vs_spike(None) is None
    assert ns_module._entry_side_vs_spike("UNKNOWN") is None


def test_log_eval_writes_one_json_row(tmp_path, ns_module):
    row = {"kind": "PROBE", "symbol": "GBPUSD"}
    ns_module._log_eval(row)
    ns_module._log_eval(dict(row, kind="PROBE2"))
    lines = Path(ns_module._EVALS_LOG_PATH).read_text().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(x) for x in lines]
    assert parsed[0]["kind"] == "PROBE"
    assert parsed[1]["kind"] == "PROBE2"


def test_log_eval_noop_when_gate_off(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "NEWS_STRATEGY_EVALS_LOG_PATH", str(tmp_path / "evals_off.jsonl")
    )
    monkeypatch.setenv("NEWS_STRATEGY_EVALS_ENABLED", "0")
    import news_strategy as ns
    importlib.reload(ns)
    ns._log_eval({"kind": "SHOULD_NOT_WRITE"})
    assert not (tmp_path / "evals_off.jsonl").exists()


def test_emit_eval_returns_snapshot_and_persists(ns_module):
    st = {
        "phase": "ARMED",
        "release_epoch": 1_784_888_000.0,
        "event_name": "BoE Rate Decision",
        "event_currency": "GBP",
        "tick_history": deque(),
    }
    tele = ns_module._emit_eval(
        "GBPUSD", "CS.D.GBPUSD.TODAY.IP", st,
        ts=1_784_887_800.0, mid=1.33, ppp=0.0001,
        kind="ARMED", decision_reason="news_armed",
    )
    assert tele is not None
    assert tele["kind"] == "ARMED"
    assert tele["release_name"] == "BoE Rate Decision"
    persisted = Path(ns_module._EVALS_LOG_PATH).read_text().splitlines()
    assert len(persisted) == 1
    assert json.loads(persisted[0])["release_name"] == "BoE Rate Decision"


def test_emit_eval_survives_broken_state(ns_module):
    # A dict-shaped st but with rogue types on every field — must still return
    # a dict and not raise.
    st = {
        "phase": object(), "release_epoch": "not-a-number",
        "event_name": 42, "tick_history": ["not-a-tuple"],
        "spike_extreme": "x", "anchor": None,
    }
    tele = ns_module._emit_eval(
        "GBPUSD", None, st, ts=0.0, mid=None, ppp=None, kind="ROGUE"
    )
    assert tele is not None
    assert tele["kind"] == "ROGUE"


# ── Signal-logger whitelist wiring ─────────────────────────────────────────
def test_signal_logger_whitelists_news_telemetry_key():
    src = Path("/opt/tradingbot/signal_logger.py").read_text()
    assert (
        '"news_telemetry":              dbg.get("news_telemetry") '
        'if isinstance(dbg, dict) else None' in src
    ), "signal_logger must add news_telemetry to log_open record"


# ── Fire-path stamp: news_strategy attaches news_telemetry to decision.debug
def test_fire_path_attaches_telemetry_to_common_debug(ns_module):
    src = Path("/opt/tradingbot/news_strategy.py").read_text()
    assert 'common_debug["news_telemetry"] = _news_tele_fire' in src
    assert 'rw_debug["news_telemetry"] = _rw_news_tele' in src


# ── Decline paths write an eval row (source assertion) ─────────────────────
def test_decline_paths_emit_eval_rows(ns_module):
    src = Path("/opt/tradingbot/news_strategy.py").read_text()
    for kind in ("SKIP_NO_ACTUALS", "SKIP_ARMED_TIMEOUT",
                 "SKIP_NO_ACTUALS_AT_SPIKE", "CONS_TIMEOUT",
                 "SKIP_SL_TOO_WIDE", "REVERSAL_WATCH_EXPIRED",
                 "REVERSAL_WOULD_FIRE_EARLY",
                 "REVERSAL_WOULD_FIRE_POSITION_OPEN",
                 "ARMED", "SPIKE_DETECTED"):
        assert f'kind="{kind}"' in src, f"missing _emit_eval kind={kind}"


def test_env_layered_declares_evals_config():
    src = Path("/opt/tradingbot/env/10-infrastructure.env").read_text()
    assert "NEWS_STRATEGY_EVALS_ENABLED=1" in src
    assert "NEWS_STRATEGY_EVALS_LOG_PATH=" in src
