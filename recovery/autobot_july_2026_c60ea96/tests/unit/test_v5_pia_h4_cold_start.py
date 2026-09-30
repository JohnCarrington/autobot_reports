"""Unit tests for autobot._v5_pia_h4_cold_start.

Covers REST-primary / 5M-aggregation-fallback orchestration for v5_PIA's
H4 cache cold-start. Per docs/pia_shadow_vs_live_investigation_2026-05-13.md
the goal is to ensure _h4_closed[sym] reaches >= 20 bars before the first
PIA briefing so trade_plan_builder.py:114 doesn't STAND_ASIDE on
insufficient_h4_bars.

Mocks: rest_allowance.remaining(), autobot._rest_fetch_df,
TimeframeContext.preload_h4_from_5m_cache. No real IG, no real disk
allowance state.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, List
from unittest import mock

import pandas as pd
import pytest

sys.path.insert(0, "/opt/tradingbot")

import autobot  # noqa: E402


# ───────────────────────────────────────────────────────────── helpers

class _FakeTfCtx:
    """Minimal stand-in for TimeframeContext exposing _h4_closed and the
    preload_h4_from_5m_cache method as a Mock so we can assert call args."""

    def __init__(self, existing_h4: List[Dict[str, Any]] | None = None):
        self._h4_closed: Dict[str, List[Dict[str, Any]]] = {}
        if existing_h4 is not None:
            self._h4_closed["GBPUSD"] = list(existing_h4)
        # Default: aggregation produces 10 H4 bars (typical f6b8599 ceiling).
        self.preload_h4_from_5m_cache = mock.MagicMock(
            return_value={
                "symbol": "GBPUSD",
                "h4_candles_loaded": 10,
                "h4_periods_skipped": 2,
            }
        )


def _h4_bar(bucket_epoch: int, close: float = 1.25) -> Dict[str, Any]:
    return {
        "timeframe":   "H4",
        "timestamp":   "2026-05-12T00:00:00Z",
        "bucket_epoch": int(bucket_epoch),
        "open":  close - 0.001,
        "high":  close + 0.002,
        "low":   close - 0.002,
        "close": close,
    }


def _rest_df(n: int, start_epoch: int = 1747000000) -> pd.DataFrame:
    """Build a standardized H4 REST DataFrame (mirror _standardize_hist_df output)."""
    rows = []
    for i in range(n):
        ts_epoch = start_epoch + i * 14400
        rows.append({
            "timestamp": pd.Timestamp(ts_epoch, unit="s", tz="UTC"),
            "open":  1.2500 + i * 0.0001,
            "high":  1.2520 + i * 0.0001,
            "low":   1.2480 + i * 0.0001,
            "close": 1.2510 + i * 0.0001,
        })
    return pd.DataFrame(rows)


@pytest.fixture
def fake_ig():
    return mock.MagicMock(name="ig")


@pytest.fixture
def patched_rest_allowance():
    """Mock rest_allowance module (lazily-imported inside the helper).
    Default: remaining=7824 (plenty of headroom)."""
    fake_mod = mock.MagicMock()
    fake_mod.remaining.return_value = 7824
    with mock.patch.dict(sys.modules, {"rest_allowance": fake_mod}):
        yield fake_mod


# ───────────────────────────────────────────────────────────── tests

def test_cache_sufficient_skips_rest(fake_ig, patched_rest_allowance):
    """30 existing bars >= threshold (20) → no REST call, no backfill."""
    existing = [_h4_bar(1747000000 + i * 14400) for i in range(30)]
    tf_ctx = _FakeTfCtx(existing_h4=existing)

    with mock.patch.object(autobot, "_rest_fetch_df") as rest_mock:
        metrics = autobot._v5_pia_h4_cold_start(fake_ig, "GBPUSD", "CS.D.GBPUSD.TODAY.IP", tf_ctx)

    rest_mock.assert_not_called()
    tf_ctx.preload_h4_from_5m_cache.assert_not_called()
    assert metrics["skipped"] is True
    assert metrics["rest"] is False
    assert metrics["backfill"] is False
    assert metrics["bars"] == 30


def test_cache_insufficient_rest_success(fake_ig, patched_rest_allowance, tmp_path, monkeypatch):
    """5 existing bars, REST returns 40 fresh → merged cache has >= 20 bars."""
    existing = [_h4_bar(1747000000 + i * 14400) for i in range(5)]
    tf_ctx = _FakeTfCtx(existing_h4=existing)

    # REST returns 40 bars in a non-overlapping range.
    df = _rest_df(40, start_epoch=1747000000 + 5 * 14400)

    with mock.patch.object(autobot, "_rest_fetch_df", return_value=(df, None)) as rest_mock:
        metrics = autobot._v5_pia_h4_cold_start(fake_ig, "GBPUSD", "CS.D.GBPUSD.TODAY.IP", tf_ctx)

    rest_mock.assert_called_once_with(fake_ig, "CS.D.GBPUSD.TODAY.IP", "HOUR_4", 40)
    tf_ctx.preload_h4_from_5m_cache.assert_not_called()  # REST succeeded — no fallback
    assert metrics["rest"] is True
    assert metrics["backfill"] is False
    assert metrics["bars"] >= 20
    # Verify the cache was actually populated.
    assert len(tf_ctx._h4_closed["GBPUSD"]) >= 20


def test_rest_failure_falls_back_to_5m_aggregation(fake_ig, patched_rest_allowance, tmp_path, monkeypatch):
    """REST returns (None, None) → 5M aggregation backfill is invoked."""
    tf_ctx = _FakeTfCtx(existing_h4=[])

    # Need a 5M cache file present for the fallback's read_csv to succeed.
    csv_path = tmp_path / "GBPUSD_candles.csv"
    pd.DataFrame({
        "timestamp": [pd.Timestamp("2026-05-12T00:00:00Z")],
        "open": [1.25], "high": [1.26], "low": [1.24], "close": [1.255],
    }).to_csv(csv_path, index=False)
    monkeypatch.setattr(autobot, "_cache_path", lambda sym: str(csv_path))

    with mock.patch.object(autobot, "_rest_fetch_df", return_value=(None, None)) as rest_mock:
        metrics = autobot._v5_pia_h4_cold_start(fake_ig, "GBPUSD", "CS.D.GBPUSD.TODAY.IP", tf_ctx)

    rest_mock.assert_called_once()
    tf_ctx.preload_h4_from_5m_cache.assert_called_once()
    assert metrics["rest"] is False
    assert metrics["backfill"] is True
    assert metrics["bars"] == 10  # _FakeTfCtx default mock return


def test_rest_exception_falls_back_to_5m_aggregation(fake_ig, patched_rest_allowance, tmp_path, monkeypatch):
    """_rest_fetch_df raises → backfill runs, no crash."""
    tf_ctx = _FakeTfCtx(existing_h4=[])

    csv_path = tmp_path / "GBPUSD_candles.csv"
    pd.DataFrame({
        "timestamp": [pd.Timestamp("2026-05-12T00:00:00Z")],
        "open": [1.25], "high": [1.26], "low": [1.24], "close": [1.255],
    }).to_csv(csv_path, index=False)
    monkeypatch.setattr(autobot, "_cache_path", lambda sym: str(csv_path))

    with mock.patch.object(autobot, "_rest_fetch_df", side_effect=RuntimeError("IG 503")):
        metrics = autobot._v5_pia_h4_cold_start(fake_ig, "GBPUSD", "CS.D.GBPUSD.TODAY.IP", tf_ctx)

    tf_ctx.preload_h4_from_5m_cache.assert_called_once()
    assert metrics["rest"] is False
    assert metrics["backfill"] is True


def test_both_failures_logs_error_no_crash(fake_ig, patched_rest_allowance, tmp_path, monkeypatch, caplog):
    """REST returns (None, None) AND aggregation returns 0 bars → ERROR logged, no exception."""
    tf_ctx = _FakeTfCtx(existing_h4=[])
    # Aggregation reports 0 bars loaded — simulates an empty / corrupt 5M CSV.
    tf_ctx.preload_h4_from_5m_cache = mock.MagicMock(
        return_value={"symbol": "GBPUSD", "h4_candles_loaded": 0, "h4_periods_skipped": 0}
    )

    csv_path = tmp_path / "GBPUSD_candles.csv"
    pd.DataFrame({
        "timestamp": [pd.Timestamp("2026-05-12T00:00:00Z")],
        "open": [1.25], "high": [1.26], "low": [1.24], "close": [1.255],
    }).to_csv(csv_path, index=False)
    monkeypatch.setattr(autobot, "_cache_path", lambda sym: str(csv_path))

    with mock.patch.object(autobot, "_rest_fetch_df", return_value=(None, None)):
        with caplog.at_level(logging.ERROR, logger="AutoBot"):
            metrics = autobot._v5_pia_h4_cold_start(fake_ig, "GBPUSD", "CS.D.GBPUSD.TODAY.IP", tf_ctx)

    # Cache unchanged (empty).
    assert tf_ctx._h4_closed.get("GBPUSD", []) == []
    assert metrics["bars"] == 0
    # ERROR log emitted.
    error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("H4 cold-start FAILED" in m for m in error_msgs)


def test_low_allowance_skips_rest_directly(fake_ig, tmp_path, monkeypatch):
    """rest_allowance.remaining()=150 (<200) → REST not called, backfill runs."""
    tf_ctx = _FakeTfCtx(existing_h4=[])

    fake_mod = mock.MagicMock()
    fake_mod.remaining.return_value = 150
    monkeypatch.setitem(sys.modules, "rest_allowance", fake_mod)

    csv_path = tmp_path / "GBPUSD_candles.csv"
    pd.DataFrame({
        "timestamp": [pd.Timestamp("2026-05-12T00:00:00Z")],
        "open": [1.25], "high": [1.26], "low": [1.24], "close": [1.255],
    }).to_csv(csv_path, index=False)
    monkeypatch.setattr(autobot, "_cache_path", lambda sym: str(csv_path))

    with mock.patch.object(autobot, "_rest_fetch_df") as rest_mock:
        metrics = autobot._v5_pia_h4_cold_start(fake_ig, "GBPUSD", "CS.D.GBPUSD.TODAY.IP", tf_ctx)

    rest_mock.assert_not_called()
    tf_ctx.preload_h4_from_5m_cache.assert_called_once()
    assert metrics["rest"] is False
    assert metrics["backfill"] is True


def test_logging_includes_per_pair_and_cost_summary(fake_ig, patched_rest_allowance, caplog):
    """Per-pair init log line is emitted by the orchestrator wrapper; this
    test exercises the inner helper across 4 pairs in sequence and confirms
    each metrics dict carries the fields the log line interpolates."""
    pairs = [
        ("GBPUSD", "CS.D.GBPUSD.TODAY.IP"),
        ("EURUSD", "CS.D.EURUSD.TODAY.IP"),
        ("USDCAD", "CS.D.USDCAD.TODAY.IP"),
        ("USDJPY", "CS.D.USDJPY.TODAY.IP"),
    ]
    all_metrics: List[Dict[str, Any]] = []

    for sym, epic in pairs:
        tf_ctx = _FakeTfCtx(existing_h4=[])
        df = _rest_df(40, start_epoch=1747000000)
        with mock.patch.object(autobot, "_rest_fetch_df", return_value=(df, None)):
            m = autobot._v5_pia_h4_cold_start(fake_ig, sym, epic, tf_ctx)
        all_metrics.append(m)

    # Each metrics dict carries every key the per-pair log line reads.
    for m in all_metrics:
        for k in ("symbol", "rest", "backfill", "bars", "skipped"):
            assert k in m
        assert m["rest"] is True
        assert m["bars"] >= 20

    # Aggregate cost (what the main() summary line computes).
    rest_pairs = sum(1 for m in all_metrics if m["rest"])
    cost = rest_pairs * autobot._V5_PIA_H4_REQUEST_BARS
    assert cost == 4 * 40 == 160  # spec figure from pre-flight doc
