"""Unit tests for the pre-news positioning bypass (Fix 1) and the
forward news calendar reader (Fix 4).

These tests cover the four interlocking pieces wired up in
feat/v5_pia-pre-news-positioning-data-layer:

- _is_pre_news_window helper (briefing/v5_pia/confidence_scorer.py)
- get_upcoming_events public reader (news_calendar.py)
- d1_h4_bias_disagree gate suspension (briefing/v5_pia/confidence_scorer.py)
- Integration: today's GBPUSD pre-NFP scenario (D1 BEARISH, H4 BULLISH,
  NFP USD HIGH 6h from now) — the gate is bypassed and the scorer
  proceeds rather than short-circuiting.
"""
from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_event(
    *, dt: datetime, currency: str = "USD",
    event_name: str = "Non Farm Payrolls", impact: str = "High",
) -> Dict[str, Any]:
    """Synthesise a calendar event matching the parsed-event shape used
    by news_calendar (date_utc/time/datetime_utc/currency/event_name/impact).
    """
    return {
        "date_utc":     dt.strftime("%Y-%m-%d"),
        "time":         dt.strftime("%H:%M"),
        "datetime_utc": dt.replace(microsecond=0).isoformat(),
        "currency":     currency,
        "event_name":   event_name,
        "impact":       impact,
        "forecast":     "200K",
        "previous":     "150K",
    }


@pytest.fixture
def now_utc() -> datetime:
    """Fixed reference time so all relative-window tests are deterministic."""
    return datetime(2026, 5, 8, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fake_calendar_module():
    """Build a stand-in news_calendar module exposing get_upcoming_events.

    The factory returns (module, set_events) — set_events lets each test
    install its own event list without restubbing the module.
    """
    container: Dict[str, List[Dict[str, Any]]] = {"events": []}

    def get_upcoming_events(
        hours_ahead: int = 120,
        currencies: List[str] = None,
        impact_min: str = "HIGH",
    ) -> List[Dict[str, Any]]:
        # Emulate the real reader's filter contract: hours_ahead window
        # from "now" (datetime.now(timezone.utc)), currency filter, and
        # impact_min ordering. The fixture passes events with explicit
        # absolute datetimes — to keep the test deterministic we use the
        # event's datetime_utc verbatim and let the test inject events
        # already inside the desired window.
        rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        try:
            min_rank = rank[impact_min.upper()]
        except KeyError:
            min_rank = rank["HIGH"]
        cur = {c.upper() for c in currencies} if currencies else None
        out = []
        for ev in container["events"]:
            ev_imp = rank.get(str(ev.get("impact", "")).upper())
            if ev_imp is None or ev_imp < min_rank:
                continue
            if cur is not None and str(ev.get("currency", "")).upper() not in cur:
                continue
            out.append(dict(ev))
        out.sort(key=lambda r: r["datetime_utc"])
        return out

    mod = types.SimpleNamespace(get_upcoming_events=get_upcoming_events)
    return mod, container


# ─────────────────────────────────────────────────────────────────────────────
# _is_pre_news_window tests
# ─────────────────────────────────────────────────────────────────────────────

class TestIsPreNewsWindow:
    def test_no_events_returns_false(self, now_utc, fake_calendar_module):
        from briefing.v5_pia.confidence_scorer import _is_pre_news_window
        mod, container = fake_calendar_module
        container["events"] = []
        in_window, hours, ev = _is_pre_news_window(
            currencies=["GBP", "USD"], now_utc=now_utc, hours_ahead=48,
            news_calendar_module=mod,
        )
        assert in_window is False
        assert hours is None
        assert ev is None

    def test_event_in_window_returns_true(self, now_utc, fake_calendar_module):
        from briefing.v5_pia.confidence_scorer import _is_pre_news_window
        mod, container = fake_calendar_module
        nfp = _make_event(dt=now_utc + timedelta(hours=6), currency="USD")
        container["events"] = [nfp]
        in_window, hours, ev = _is_pre_news_window(
            currencies=["GBP", "USD"], now_utc=now_utc, hours_ahead=48,
            news_calendar_module=mod,
        )
        assert in_window is True
        # Allow ±0.05h drift from rounding of datetime arithmetic.
        assert hours is not None and 5.5 < hours < 6.5
        assert ev is not None and ev["event_name"] == "Non Farm Payrolls"

    def test_event_past_window_returns_false(self, now_utc, fake_calendar_module):
        """Event is HIGH-impact USD but lands 60 hours from now — outside
        a 48-hour bypass window; the helper must return False.
        """
        from briefing.v5_pia.confidence_scorer import _is_pre_news_window
        mod, container = fake_calendar_module
        # The fake reader doesn't enforce hours_ahead itself, so for this
        # test we filter manually by trimming the events list to events
        # within the requested window — mirrors what the real reader does.
        far = _make_event(dt=now_utc + timedelta(hours=60), currency="USD")

        def reader(hours_ahead, currencies=None, impact_min="HIGH"):
            cutoff = now_utc + timedelta(hours=hours_ahead)
            return [
                e for e in [far]
                if datetime.fromisoformat(e["datetime_utc"]) < cutoff
            ]
        # Substitute a stricter mock for this assertion
        mod.get_upcoming_events = reader  # type: ignore[attr-defined]

        in_window, hours, ev = _is_pre_news_window(
            currencies=["GBP", "USD"], now_utc=now_utc, hours_ahead=48,
            news_calendar_module=mod,
        )
        assert in_window is False
        assert hours is None
        assert ev is None

    def test_currency_filter(self, now_utc, fake_calendar_module):
        """Event is HIGH-impact JPY but the pair's currencies are
        [GBP, USD] — must not trip the bypass.
        """
        from briefing.v5_pia.confidence_scorer import _is_pre_news_window
        mod, container = fake_calendar_module
        boj = _make_event(dt=now_utc + timedelta(hours=10),
                          currency="JPY", event_name="BoJ Rate Decision")
        container["events"] = [boj]
        in_window, _, _ = _is_pre_news_window(
            currencies=["GBP", "USD"], now_utc=now_utc, hours_ahead=48,
            news_calendar_module=mod,
        )
        assert in_window is False
        # Same event WITH JPY in pair currencies → must trigger.
        in_window2, _, ev = _is_pre_news_window(
            currencies=["USD", "JPY"], now_utc=now_utc, hours_ahead=48,
            news_calendar_module=mod,
        )
        assert in_window2 is True
        assert ev["currency"] == "JPY"

    def test_zero_hours_disables(self, now_utc, fake_calendar_module):
        """hours_ahead=0 must short-circuit to (False, None, None) without
        even touching the calendar module — preserves the pre-Fix-1
        baseline when V5_PRE_NEWS_BYPASS_HOURS=0.
        """
        from briefing.v5_pia.confidence_scorer import _is_pre_news_window
        mod, container = fake_calendar_module
        container["events"] = [
            _make_event(dt=now_utc + timedelta(hours=1), currency="USD"),
        ]
        in_window, _, _ = _is_pre_news_window(
            currencies=["GBP", "USD"], now_utc=now_utc, hours_ahead=0,
            news_calendar_module=mod,
        )
        assert in_window is False


# ─────────────────────────────────────────────────────────────────────────────
# news_calendar.get_upcoming_events tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGetUpcomingEvents:
    def _install(self, monkeypatch, events: List[Dict[str, Any]]):
        """Inject parsed events into the news_calendar module-level cache
        and short-circuit _refresh_if_needed so tests are hermetic.
        """
        import news_calendar as nc
        monkeypatch.setattr(nc, "_all_events", list(events), raising=True)
        monkeypatch.setattr(nc, "_cache_date", "2099-12-31", raising=True)
        monkeypatch.setattr(nc, "_fetch_error", False, raising=True)
        monkeypatch.setattr(nc, "_refresh_if_needed", lambda: None, raising=True)
        return nc

    def test_hours_ahead_window(self, monkeypatch):
        nc = self._install(monkeypatch, [])
        now = datetime.now(timezone.utc)
        ev_in  = _make_event(dt=now + timedelta(hours=24), currency="USD")
        ev_out = _make_event(dt=now + timedelta(hours=200), currency="USD")
        ev_past = _make_event(dt=now - timedelta(hours=2), currency="USD")
        monkeypatch.setattr(nc, "_all_events",
                            [ev_in, ev_out, ev_past], raising=True)

        rows = nc.get_upcoming_events(hours_ahead=120, currencies=None,
                                      impact_min="HIGH")
        names = [r["event_name"] for r in rows]
        assert ev_in["event_name"] in names
        # Past and beyond-window events must be excluded.
        assert len(rows) == 1

    def test_currencies_filter(self, monkeypatch):
        nc = self._install(monkeypatch, [])
        now = datetime.now(timezone.utc)
        usd = _make_event(dt=now + timedelta(hours=6), currency="USD",
                          event_name="NFP")
        gbp = _make_event(dt=now + timedelta(hours=10), currency="GBP",
                          event_name="BoE Rate Decision")
        jpy = _make_event(dt=now + timedelta(hours=20), currency="JPY",
                          event_name="BoJ Rate Decision")
        monkeypatch.setattr(nc, "_all_events", [usd, gbp, jpy], raising=True)

        # None = all
        rows_all = nc.get_upcoming_events(hours_ahead=48, currencies=None)
        assert {r["currency"] for r in rows_all} == {"USD", "GBP", "JPY"}

        # ["GBP"] = GBP only
        rows_gbp = nc.get_upcoming_events(hours_ahead=48, currencies=["GBP"])
        assert {r["currency"] for r in rows_gbp} == {"GBP"}

        # ["GBP","USD"] = both
        rows_pair = nc.get_upcoming_events(
            hours_ahead=48, currencies=["GBP", "USD"]
        )
        assert {r["currency"] for r in rows_pair} == {"GBP", "USD"}

    def test_impact_min(self, monkeypatch):
        nc = self._install(monkeypatch, [])
        now = datetime.now(timezone.utc)
        hi  = _make_event(dt=now + timedelta(hours=4), currency="USD",
                         event_name="HI", impact="High")
        med = _make_event(dt=now + timedelta(hours=8), currency="USD",
                         event_name="MED", impact="Medium")
        lo  = _make_event(dt=now + timedelta(hours=12), currency="USD",
                         event_name="LO", impact="Low")
        monkeypatch.setattr(nc, "_all_events", [hi, med, lo], raising=True)

        # HIGH includes only HIGH
        names = [r["event_name"] for r in
                 nc.get_upcoming_events(hours_ahead=24, impact_min="HIGH")]
        assert names == ["HI"]

        # MEDIUM includes MEDIUM + HIGH
        names = sorted(r["event_name"] for r in
                       nc.get_upcoming_events(hours_ahead=24, impact_min="MEDIUM"))
        assert names == ["HI", "MED"]

        # LOW includes all three
        names = sorted(r["event_name"] for r in
                       nc.get_upcoming_events(hours_ahead=24, impact_min="LOW"))
        assert names == ["HI", "LO", "MED"]

    def test_empty_cache_returns_empty(self, monkeypatch):
        nc = self._install(monkeypatch, [])
        rows = nc.get_upcoming_events(hours_ahead=120)
        assert rows == []

    def test_results_are_sorted_ascending(self, monkeypatch):
        nc = self._install(monkeypatch, [])
        now = datetime.now(timezone.utc)
        a = _make_event(dt=now + timedelta(hours=20), currency="USD",
                        event_name="A")
        b = _make_event(dt=now + timedelta(hours=4),  currency="USD",
                        event_name="B")
        c = _make_event(dt=now + timedelta(hours=12), currency="USD",
                        event_name="C")
        monkeypatch.setattr(nc, "_all_events", [a, b, c], raising=True)
        rows = nc.get_upcoming_events(hours_ahead=48)
        assert [r["event_name"] for r in rows] == ["B", "C", "A"]


# ─────────────────────────────────────────────────────────────────────────────
# Hard-gate suspension — integration with _check_hard_gates / score_confidence
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def pre_nfp_market_data():
    """D1 BEARISH (close 13580 < ema 13620), H4 BULLISH (close 13580 > ema 13540).
    The strict d1_h4 gate fails on this configuration in the absence of bypass.
    """
    return {
        "ppp": 0.0001,
        "d1_candles":  [{"o": 13620, "h": 13625, "l": 13570, "c": 13580}],
        "d1_ema_20":   13620.0,
        "h4_candles":  [{"o": 13550, "h": 13585, "l": 13548, "c": 13580}],
        "h4_ema_20":   13540.0,
        "h4_ema_20_5bar_diff_pips": 4.0,
        "atr_h4_pips": 40.0,
        "support_levels":    [13540.0, 13520.0, 13500.0],
        "resistance_levels": [13620.0, 13650.0, 13700.0],
        "h4_swing_lows_recent":  [13540.0, 13520.0],
        "h4_swing_highs_recent": [13620.0, 13650.0],
    }


def _install_calendar(monkeypatch, events):
    """Stub the production news_calendar module so the scorer's bypass
    helper sees these events.
    """
    import news_calendar as nc
    monkeypatch.setattr(nc, "_all_events", list(events), raising=True)
    monkeypatch.setattr(nc, "_cache_date", "2099-12-31", raising=True)
    monkeypatch.setattr(nc, "_fetch_error", False, raising=True)
    monkeypatch.setattr(nc, "_refresh_if_needed", lambda: None, raising=True)


class TestHardGateBypass:
    """Integration tests through the real news_calendar.get_upcoming_events
    path. The reader uses datetime.now(timezone.utc) internally, so events
    are pinned relative to real-world now and the same value is passed
    as the gate's now_utc — keeps the bypass arithmetic consistent.
    """

    def test_disagreement_without_pre_news_still_fails(
        self, monkeypatch, pre_nfp_market_data
    ):
        from briefing.v5_pia.confidence_scorer import _check_hard_gates
        monkeypatch.setenv("V5_PRE_NEWS_BYPASS_HOURS", "48")
        _install_calendar(monkeypatch, [])  # no events
        now = datetime.now(timezone.utc)

        failures, diag = _check_hard_gates(
            pair="GBPUSD", direction="BUY",
            entry=13560.0, stop=13540.0, target=13620.0,
            market_data=pre_nfp_market_data,
            news_calendar=[], now_utc=now,
        )
        # No pre-news events → bypass does NOT apply → original failure stands.
        assert any("d1_h4_bias_disagree" in f for f in failures)
        assert diag["pre_news_bypass"]["applied"] is False
        assert diag["pre_news_bypass"]["d1_h4_disagree"] is True

    def test_disagreement_with_pre_news_bypassed(
        self, monkeypatch, pre_nfp_market_data
    ):
        from briefing.v5_pia.confidence_scorer import _check_hard_gates
        monkeypatch.setenv("V5_PRE_NEWS_BYPASS_HOURS", "48")
        now = datetime.now(timezone.utc)
        nfp = _make_event(dt=now + timedelta(hours=6), currency="USD",
                          event_name="NFP")
        _install_calendar(monkeypatch, [nfp])

        failures, diag = _check_hard_gates(
            pair="GBPUSD", direction="BUY",
            entry=13560.0, stop=13540.0, target=13620.0,
            market_data=pre_nfp_market_data,
            news_calendar=[], now_utc=now,
        )
        assert not any("d1_h4_bias_disagree" in f for f in failures)
        assert diag["pre_news_bypass"]["applied"] is True
        assert diag["pre_news_bypass"]["nearest_event"]["event_name"] == "NFP"

    def test_zero_bypass_hours_disables(
        self, monkeypatch, pre_nfp_market_data
    ):
        from briefing.v5_pia.confidence_scorer import _check_hard_gates
        monkeypatch.setenv("V5_PRE_NEWS_BYPASS_HOURS", "0")
        now = datetime.now(timezone.utc)
        nfp = _make_event(dt=now + timedelta(hours=6), currency="USD",
                          event_name="NFP")
        _install_calendar(monkeypatch, [nfp])

        failures, diag = _check_hard_gates(
            pair="GBPUSD", direction="BUY",
            entry=13560.0, stop=13540.0, target=13620.0,
            market_data=pre_nfp_market_data,
            news_calendar=[], now_utc=now,
        )
        # With bypass disabled, the gate trips even though there's a pre-news event.
        assert any("d1_h4_bias_disagree" in f for f in failures)
        assert diag["pre_news_bypass"]["applied"] is False


class TestScorerIntegration:
    """Full score_confidence path: pre-NFP scenario, bypass active, the
    scorer must NOT short-circuit to displayed=0/STAND_ASIDE on the
    d1_h4 gate. Other failures (if any) may still apply for genuine
    reasons; the assertion is specifically that d1_h4 is not the cause.
    """
    def test_pre_nfp_gbpusd_gate_does_not_shortcircuit(
        self, monkeypatch, pre_nfp_market_data
    ):
        from briefing.v5_pia.confidence_scorer import score_confidence
        monkeypatch.setenv("V5_PRE_NEWS_BYPASS_HOURS", "48")
        now = datetime.now(timezone.utc)
        nfp = _make_event(dt=now + timedelta(hours=6), currency="USD",
                          event_name="NFP")
        _install_calendar(monkeypatch, [nfp])

        # Tighten entry/levels so the entry_too_far_from_levels gate
        # doesn't drown out the d1_h4 assertion. The bypass assertion is
        # specifically about d1_h4 — other gates may still apply for
        # genuine reasons.
        md = dict(pre_nfp_market_data)
        md["support_levels"]    = [13558.0, 13540.0, 13520.0]
        md["resistance_levels"] = [13620.0, 13650.0, 13700.0]

        # Note: news_calendar arg is the entry-window list (today),
        # separate from the upcoming forward window the bypass uses.
        result = score_confidence(
            pair="GBPUSD", direction="BUY",
            entry=13560.0, stop=13540.0, target=13620.0,
            market_data=md,
            news_calendar=[], phase4_structure="NEUTRAL",
            now_utc=now,
        )
        gate_failures = result["hard_gate_failures"]
        assert not any("d1_h4_bias_disagree" in f for f in gate_failures), (
            f"d1_h4 gate should be bypassed; failures={gate_failures}"
        )
        # diagnostics should record the bypass evaluation
        assert result["diagnostics"]["pre_news_bypass"]["applied"] is True
