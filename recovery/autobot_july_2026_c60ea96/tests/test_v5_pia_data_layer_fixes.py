"""Tests for v5_pia data-layer fixes 2 + 3.

Fix 2: H4 truncation lifted from 20 → 40 bars in the v5 path.
Fix 3: rationale_writer._market_data_summary no longer drops v4-computed
       fields (audit Gap D), and forward-news section is rendered.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pandas as pd
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2: 40-bar H4 reaches the data_package
# ─────────────────────────────────────────────────────────────────────────────

def _h4_dataframe(n_bars: int) -> pd.DataFrame:
    base = pd.Timestamp("2026-05-01T00:00:00Z")
    rows = []
    for i in range(n_bars):
        ts = base + pd.Timedelta(hours=4 * i)
        # Smooth synthetic walk so swing detection still finds pivots.
        c = 13500.0 + (i * 1.5) + ((-1) ** i) * 8.0
        rows.append({
            "timestamp": ts,
            "open":  c - 2.0,
            "high":  c + 5.0,
            "low":   c - 5.0,
            "close": c,
        })
    return pd.DataFrame(rows)


class TestH4DepthFix:
    def test_offline_path_passes_at_least_40_h4_bars(self):
        """assemble_v5_data_package_offline must keep at least 40 H4 bars
        when the caller hands them in (the prior runtime path silently
        truncated trade_plan_builder's lookback to 20 via [-20:] slice).
        The offline harness has always passed whatever fits inside its
        max_n cap; this test pins the minimum to 40 going forward.
        """
        from briefing.v5_pia.data_package import assemble_v5_data_package_offline

        df_h4 = _h4_dataframe(40)
        # Stub D1/H1/5M with minimal frames — the test only asserts H4.
        df_d1 = _h4_dataframe(5).rename(columns=str)
        df_h1 = _h4_dataframe(5).rename(columns=str)
        df_5m = _h4_dataframe(5).rename(columns=str)
        now = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)

        pkg = assemble_v5_data_package_offline(
            "GBPUSD", "London", now,
            df_5m=df_5m, df_h1=df_h1, df_h4=df_h4, df_d1=df_d1,
        )
        assert len(pkg["h4_candles"]) >= 40, (
            f"v5 offline path should expose ≥40 H4 bars, got {len(pkg['h4_candles'])}"
        )

    def test_runtime_widening_uses_tf_ctx(self, monkeypatch):
        """The runtime path (_widen_h4_for_v5) should widen the v4 [-20:]
        slice to 40 by re-pulling from morning_briefing._TF_CTX.
        """
        from briefing.v5_pia import data_package as dp

        # Build a fake TimeframeContext with a 60-bar H4 list.
        bars = [
            {"open": 13500.0 + i, "high": 13510.0 + i,
             "low":  13490.0 + i, "close": 13505.0 + i}
            for i in range(60)
        ]

        class _FakeTFCtx:
            def __init__(self):
                self._h4_closed = {"GBPUSD": list(bars)}

        # _fmt_candles in production maps long-name keys to short keys.
        def _fmt_candles(cs):
            return [{"o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"]}
                    for c in cs]

        import morning_briefing as mb
        monkeypatch.setattr(mb, "_TF_CTX", _FakeTFCtx(), raising=False)
        monkeypatch.setattr(mb, "_fmt_candles", _fmt_candles, raising=False)

        # Seed base with the v4 short slice (last 20).
        base = {"h4_candles": _fmt_candles(bars[-20:])}
        dp._widen_h4_for_v5(base, "GBPUSD")
        assert len(base["h4_candles"]) == 40
        # Oldest of the wider slice is the 21st-from-newest bar.
        assert base["h4_candles"][0]["o"] == bars[-40]["open"]


# ─────────────────────────────────────────────────────────────────────────────
# Fix 3: _market_data_summary preserves dropped v4 fields
# ─────────────────────────────────────────────────────────────────────────────

class TestMarketDataSummary:
    def _make_md(self) -> Dict[str, Any]:
        """Build a market_data dict carrying every v4-computed field the
        audit listed as silently dropped, plus the v5 enrichment scalars.
        """
        return {
            # v5 scalars
            "ppp": 0.0001,
            "current_price": 13550.5,
            "d1_ema_20": 13520.0,
            "h4_ema_20": 13540.0,
            "atr_pctl_14": 55.0,
            "atr_h4_pips": 38.5,
            "phase4_structure": "TRENDING",
            "ema_stack_state": "BULL_STACK",

            # v4-computed structure (audit Gap D)
            "prev_day_high":  13615.0,
            "prev_day_low":   13502.0,
            "prev_day_close": 13580.0,
            "week_high":      13700.0,
            "week_low":       13455.0,
            "prev_week_high": 13720.0,
            "prev_week_low":  13420.0,
            "htf_bias":       {"d1": "BEARISH", "h4": "BULLISH", "h1": "BULLISH"},
            "usd_proxy_bias": "USD_NEUTRAL",
            "prev_session_actual_direction": "DOWN",
            "prev_session_pip_move": -22.5,
            "news_events": [
                {"time": "12:30", "currency": "USD",
                 "event_name": "Non Farm Payrolls", "impact": "High"},
            ],

            # candle arrays
            "h4_candles": [
                {"o": 13500 + i, "h": 13510 + i, "l": 13490 + i, "c": 13505 + i}
                for i in range(40)
            ],
            "d1_candles": [
                {"o": 13400 + i*5, "h": 13420 + i*5, "l": 13380 + i*5, "c": 13410 + i*5}
                for i in range(20)
            ],
            "h1_candles": [
                {"o": 13500 + i, "h": 13510 + i, "l": 13490 + i, "c": 13505 + i}
                for i in range(20)
            ],
        }

    def test_dropped_fields_now_present(self):
        from briefing.v5_pia.rationale_writer import _market_data_summary

        md = self._make_md()
        out = _market_data_summary(md)

        # Every previously-dropped field must be present (and not None
        # since we provided values).
        for k in (
            "prev_day_high", "prev_day_low", "prev_day_close",
            "week_high", "week_low", "prev_week_high", "prev_week_low",
            "htf_bias", "usd_proxy_bias",
            "prev_session_actual_direction", "prev_session_pip_move",
            "news_events",
        ):
            assert k in out, f"field {k!r} missing from _market_data_summary"
            assert out[k] is not None, f"field {k!r} should preserve value, got None"

        # H4 + D1 OHLC tables present and non-empty
        assert "h4_ohlc_table" in out
        assert "d1_ohlc_table" in out
        assert out["h4_bars_count"] == 40
        assert out["d1_bars_count"] == 20
        assert "/" in out["h4_ohlc_table"]  # compact OHLC format

    def test_existing_v5_scalars_still_present(self):
        from briefing.v5_pia.rationale_writer import _market_data_summary

        md = self._make_md()
        out = _market_data_summary(md)
        for k in (
            "current_price", "d1_ema_20", "h4_ema_20", "h4_close",
            "h1_recent_pip_move_6h", "atr_pctl_14", "atr_h4_pips",
            "phase4_structure", "ema_stack_state",
        ):
            assert k in out


# ─────────────────────────────────────────────────────────────────────────────
# Fix 4 prompt-side: forward calendar section is rendered
# ─────────────────────────────────────────────────────────────────────────────

class TestUpcomingEventsSection:
    def test_section_appended_when_events_present(self):
        from briefing.v5_pia.rationale_writer import (
            _format_upcoming_events_section,
        )
        now = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
        events = [
            {
                "datetime_utc": (now + timedelta(hours=6)).isoformat(),
                "currency": "USD",
                "event_name": "Non Farm Payrolls",
            },
            {
                "datetime_utc": (now + timedelta(hours=60)).isoformat(),
                "currency": "GBP",
                "event_name": "Average Earnings",
            },
        ]
        out = _format_upcoming_events_section(events, now)
        assert "Upcoming high-impact events (next 5 days):" in out
        assert "USD: Non Farm Payrolls" in out
        assert "GBP: Average Earnings" in out
        # Relative-time hint
        assert "today, in 6h" in out
        # Day-name format for non-today/tomorrow
        assert "in 60h" in out

    def test_empty_section_returns_empty_string(self):
        from briefing.v5_pia.rationale_writer import (
            _format_upcoming_events_section,
        )
        now = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
        assert _format_upcoming_events_section([], now) == ""


class TestBuildUserMessageIntegration:
    def _briefing(self):
        from briefing.v5_pia.schema import BriefingV5
        return BriefingV5(
            schema_version="v5_pia",
            pair="GBPUSD",
            session="London",
            generated_at_utc="2026-05-08T05:30:00Z",
            valid_until_utc="2026-05-08T12:30:00Z",
            direction="BUY",
            state="ARMED",
            confidence=72,
            confidence_bucket="ARMED",
            confidence_breakdown={"hard_gate_failures": []},
            bias_anchor=13540.0,
            bias_anchor_label="H4_EMA20",
            entry=13540.0,
            stop=13510.0,
            target=13620.0,
            rr=2.67,
            stop_structural_level="swing_low",
            target_structural_level="swing_high",
            support_levels=[13500.0, 13480.0],
            resistance_levels=[13620.0, 13650.0],
            rationale=None,
            stand_aside_reason=None,
            news_in_window=False,
            news_event=None,
        )

    def test_user_message_contains_upcoming_section_when_events_present(self):
        from briefing.v5_pia.rationale_writer import build_user_message
        now = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
        md = {
            "ppp": 0.0001,
            "current_price": 13550.5,
            "h4_candles": [
                {"o": 13500, "h": 13510, "l": 13490, "c": 13505}
            ],
            "h1_candles": [],
            "d1_candles": [],
            "upcoming_events": [
                {
                    "datetime_utc": (now + timedelta(hours=6)).isoformat(),
                    "currency": "USD",
                    "event_name": "NFP",
                }
            ],
        }
        msg = build_user_message(self._briefing(), md, now_utc=now)
        # JSON block first, then the upcoming-events section.
        json_part, _, upcoming_part = msg.partition("\n\nUpcoming")
        # JSON portion still parses
        payload = json.loads(json_part)
        assert payload["pair"] == "GBPUSD"
        # Section header present
        assert "high-impact events" in upcoming_part
        assert "USD: NFP" in upcoming_part

    def test_user_message_no_section_when_events_absent(self):
        from briefing.v5_pia.rationale_writer import build_user_message
        now = datetime(2026, 5, 8, 10, 0, tzinfo=timezone.utc)
        md = {"upcoming_events": [], "ppp": 0.0001,
              "h4_candles": [], "h1_candles": [], "d1_candles": []}
        msg = build_user_message(self._briefing(), md, now_utc=now)
        # No trailing "Upcoming" section header.
        assert "Upcoming high-impact events" not in msg
