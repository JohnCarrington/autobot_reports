"""
Tests for the 2026-04-29 NEWS_STRATEGY rebuild + NEWS_TICK direction fix.

Covers:
- good_for_currency polarity (POSITIVE / INVERSE / unknown-default)
- trade_direction_from_currency_action (base/quote/error)
- event_magnitude lookup (rate / data / default)
- NEWS_STRATEGY state machine: IDLE → ARMED → SPIKE → CONS → ENTRY|TIMEOUT
- Spike detection: range path / directional path / chronological-first
- Consolidation tracking with 30 s exclusion of trailing ticks
- Break detection (UP fade DOWN, DOWN fade UP)
- SL/TP geometry with the 25 p / 50 p caps
- Skip on direction_hint == CONTINUATION
- Skip on no actuals after timeout
- Skip on unknown event direction
- Observable-only mode emits no real signal
- NEWS_TICK direction flips from spike_dir to currency-action
- NEWS_TICK cedes on REVERSAL / no actuals (no chase path)
- NEWS_TICK_LEGACY_STALL_PATH=0 deactivates SPIKE/STALL state handlers
"""
from __future__ import annotations

import importlib
import json
import sys
import time
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Fixtures: stub te_calendar + news_calendar so the strategies don't reach
# the real network or filesystem.
# ---------------------------------------------------------------------------
@pytest.fixture
def stub_te(monkeypatch):
    """Returns a setter; call it with (event_name, te_dict) to seed
    te_calendar.get_actual_for_event's response. Default: returns None."""
    store: Dict[str, Optional[Dict[str, Any]]] = {"result": None}

    def get_actual_for_event(name, currency=None):
        if store["result"] is None:
            return None
        r = dict(store["result"])
        r.setdefault("te_event", name)
        r.setdefault("actual_str", str(r.get("actual", "")))
        r.setdefault("forecast_str", str(r.get("forecast", "")))
        return r

    fake = types.SimpleNamespace(
        get_actual_for_event=get_actual_for_event,
        poll_for_actual=lambda min_interval=0: None,
    )
    monkeypatch.setitem(sys.modules, "te_calendar", fake)

    def set_result(d: Optional[Dict[str, Any]]):
        store["result"] = d

    return set_result


@pytest.fixture
def stub_calendar(monkeypatch):
    """Returns a setter; call it with a list of events to seed
    news_calendar.get_todays_events."""
    store: Dict[str, List[Dict[str, Any]]] = {"events": []}
    fake = types.SimpleNamespace(get_todays_events=lambda: list(store["events"]))
    monkeypatch.setitem(sys.modules, "news_calendar", fake)

    def set_events(events):
        store["events"] = list(events)

    return set_events


@pytest.fixture
def fresh_strategy(monkeypatch, tmp_path):
    """Fresh news_strategy module state; observable-log redirected to tmp."""
    # 2026-07-25 ITEM 2: NEWS_STRATEGY_MODE defaults to `off` (dormant).
    # These state-machine tests were written against pre-mode behaviour;
    # opt them into `enforce` so the state machine progresses as they
    # expect. The mode-gate contract itself is covered by
    # test_news_strategy_mode_gate.py.
    monkeypatch.setenv("NEWS_STRATEGY_MODE", "enforce")
    import news_strategy as ns
    importlib.reload(ns)
    ns._news_state.clear()
    log_path = tmp_path / "news_observed.jsonl"
    monkeypatch.setattr(ns, "_OBSERVED_LOG_PATH", log_path)
    yield ns, log_path
    ns._news_state.clear()


# ---------------------------------------------------------------------------
# good_for_currency
# ---------------------------------------------------------------------------
def test_gfc_positive_event_beat_strengthens(fresh_strategy):
    ns, _ = fresh_strategy
    assert ns.good_for_currency("CPI", "BEAT") == "STRENGTHEN"
    assert ns.good_for_currency("Manufacturing PMI", "BEAT") == "STRENGTHEN"


def test_gfc_positive_event_miss_weakens(fresh_strategy):
    ns, _ = fresh_strategy
    assert ns.good_for_currency("CPI", "MISS") == "WEAKEN"


def test_gfc_inverse_unemployment(fresh_strategy):
    ns, _ = fresh_strategy
    # BEAT means more claims → bad → currency weakens.
    assert ns.good_for_currency("Initial Jobless Claims", "BEAT") == "WEAKEN"
    assert ns.good_for_currency("Unemployment Rate", "MISS") == "STRENGTHEN"


def test_gfc_unknown_defaults_positive(fresh_strategy):
    ns, _ = fresh_strategy
    # Unknown event names default to POSITIVE polarity.
    assert ns.good_for_currency("Random Indicator That Doesn't Exist", "BEAT") == "STRENGTHEN"
    assert ns.good_for_currency("Random Indicator That Doesn't Exist", "MISS") == "WEAKEN"


def test_gfc_inline_treated_as_miss(fresh_strategy):
    ns, _ = fresh_strategy
    # Anything not "BEAT" weakens for POSITIVE / strengthens for INVERSE.
    assert ns.good_for_currency("CPI", "IN_LINE") == "WEAKEN"


# ---------------------------------------------------------------------------
# trade_direction_from_currency_action
# ---------------------------------------------------------------------------
def test_trade_dir_base_strengthen(fresh_strategy):
    ns, _ = fresh_strategy
    # CAD strengthens; USDCAD has CAD as quote; USD strengthens vs CAD weakens.
    # Wait: STRENGTHEN means CAD up; pair USDCAD; CAD is quote → SELL USDCAD.
    assert ns.trade_direction_from_currency_action("CAD", "USDCAD", "STRENGTHEN") == "SELL"


def test_trade_dir_quote_weaken(fresh_strategy):
    ns, _ = fresh_strategy
    # USD weakens; pair GBPUSD has USD as quote → SELL=USD strengthens, so
    # weakening USD → BUY GBPUSD.
    assert ns.trade_direction_from_currency_action("USD", "GBPUSD", "WEAKEN") == "BUY"


def test_trade_dir_base_weaken(fresh_strategy):
    ns, _ = fresh_strategy
    # GBP weakens; pair GBPUSD has GBP as base → SELL.
    assert ns.trade_direction_from_currency_action("GBP", "GBPUSD", "WEAKEN") == "SELL"


def test_trade_dir_currency_not_in_pair_raises(fresh_strategy):
    ns, _ = fresh_strategy
    with pytest.raises(ValueError):
        ns.trade_direction_from_currency_action("USD", "GBPJPY", "STRENGTHEN")


# ---------------------------------------------------------------------------
# event_magnitude
# ---------------------------------------------------------------------------
def test_magnitude_rate_decision(fresh_strategy):
    ns, _ = fresh_strategy
    m = ns.event_magnitude("BoC Interest Rate Decision")
    assert m["sl_pips"] == 12 and m["tp_pips"] == 50


def test_magnitude_data_print(fresh_strategy):
    ns, _ = fresh_strategy
    m = ns.event_magnitude("Manufacturing PMI")
    assert m["sl_pips"] == 8 and m["tp_pips"] == 25


def test_magnitude_unknown_default(fresh_strategy):
    ns, _ = fresh_strategy
    m = ns.event_magnitude("Random Indicator")
    assert m["sl_pips"] == 6 and m["tp_pips"] == 20


# ---------------------------------------------------------------------------
# NEWS_STRATEGY state machine
# ---------------------------------------------------------------------------
SYMBOL = "USDCAD"
EPIC = "CS.D.USDCAD.TODAY.IP"
PPP = 1.0


def _arm_and_pump(ns, strat, stub_calendar, stub_te, *,
                   actuals=None, anchor_price=13690.0,
                   release_in_secs=30, base_ts=None):
    """Helper: stub a CAD HIGH event 30s away; arm via tick at anchor_price.
    Returns the (ts at arming, release_epoch) tuple."""
    if base_ts is None:
        base_ts = time.time()
    # Stub CAD event "release_in_secs" ahead.
    from datetime import datetime, timezone, timedelta
    now_dt = datetime.fromtimestamp(base_ts, tz=timezone.utc)
    ev_dt = now_dt + timedelta(seconds=release_in_secs)
    stub_calendar([{
        "time": ev_dt.strftime("%H:%M"),
        "currency": "CAD",
        "event_name": "BOC Interest Rate Decision",
        "impact": "High",
    }])
    stub_te(actuals)
    arm_ts = base_ts
    decision = strat.evaluate(
        symbol=SYMBOL, epic=EPIC, mid=anchor_price,
        bid=anchor_price - 0.5, ask=anchor_price + 0.5,
        ts=arm_ts, ppp=PPP,
    )
    return arm_ts, ev_dt.timestamp(), decision


def test_strategy_arms_on_high_event_within_5min(fresh_strategy, stub_calendar, stub_te):
    ns, _ = fresh_strategy
    strat = ns.NewsStrategy()
    arm_ts, release_epoch, decision = _arm_and_pump(
        ns, strat, stub_calendar, stub_te, anchor_price=13690.0,
    )
    st = ns._news_state[SYMBOL]
    assert st["phase"] == ns._STATE_ARMED
    assert st["anchor"] == 13690.0
    assert decision.signal == "NONE"
    assert decision.reason == "news_armed"


def test_strategy_skips_when_no_high_event_in_window(fresh_strategy, stub_calendar, stub_te):
    ns, _ = fresh_strategy
    strat = ns.NewsStrategy()
    stub_calendar([])
    stub_te(None)
    decision = strat.evaluate(
        symbol=SYMBOL, epic=EPIC, mid=13690.0, bid=13689.5, ask=13690.5,
        ts=time.time(), ppp=PPP,
    )
    assert decision.signal == "NONE"
    assert decision.reason == "news_no_upcoming_event"
    assert SYMBOL not in ns._news_state or ns._news_state[SYMBOL]["phase"] == ns._STATE_IDLE


def test_strategy_cedes_continuation_to_news_tick(fresh_strategy, stub_calendar, stub_te):
    ns, _ = fresh_strategy
    strat = ns.NewsStrategy()
    arm_ts, release_epoch, _ = _arm_and_pump(
        ns, strat, stub_calendar, stub_te,
        actuals={"direction_hint": "CONTINUATION", "beat_miss": "BEAT",
                 "deviation": 0.10, "actual": 2.50, "forecast": 2.25},
        anchor_price=13690.0,
    )
    # Push tick post-release; should cede on first poll.
    decision = strat.evaluate(
        symbol=SYMBOL, epic=EPIC, mid=13692.0, bid=13691.5, ask=13692.5,
        ts=release_epoch + 5, ppp=PPP,
    )
    assert decision.reason == "news_strategy_ceded_continuation"
    assert ns._news_state[SYMBOL]["phase"] == ns._STATE_IDLE


def test_strategy_skips_when_no_actuals_within_timeout(fresh_strategy, stub_calendar, stub_te):
    ns, _ = fresh_strategy
    strat = ns.NewsStrategy()
    arm_ts, release_epoch, _ = _arm_and_pump(
        ns, strat, stub_calendar, stub_te, actuals=None, anchor_price=13690.0,
    )
    # Push tick past release+timeout — strategy should give up.
    decision = strat.evaluate(
        symbol=SYMBOL, epic=EPIC, mid=13692.0, bid=13691.5, ask=13692.5,
        ts=release_epoch + 100, ppp=PPP,
    )
    assert decision.reason == "news_strategy_no_actuals"
    assert ns._news_state[SYMBOL]["phase"] == ns._STATE_IDLE


def test_strategy_spike_detected_and_dir_locked_to_first_extreme(
    fresh_strategy, stub_calendar, stub_te,
):
    """Anchor at 13690. After release: tick rises to 13696 (5p above
    anchor — locks spike_dir UP), then drops to 13680 (10p below — would
    be DOWN if locking by current). spike_dir must remain UP."""
    ns, _ = fresh_strategy
    strat = ns.NewsStrategy()
    arm_ts, release_epoch, _ = _arm_and_pump(
        ns, strat, stub_calendar, stub_te,
        actuals={"direction_hint": "REVERSAL", "beat_miss": "IN_LINE",
                 "deviation": 0.0, "actual": 2.25, "forecast": 2.25},
        anchor_price=13690.0,
    )
    # First post-release extreme is UP at 13695.5 (5.5p > 5p lock).
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13695.5,
                   bid=13695.0, ask=13696.0, ts=release_epoch + 5, ppp=PPP)
    # Then big DOWN move so range exceeds 15p threshold.
    decision = strat.evaluate(
        symbol=SYMBOL, epic=EPIC, mid=13680.0,
        bid=13679.5, ask=13680.5, ts=release_epoch + 30, ppp=PPP,
    )
    st = ns._news_state[SYMBOL]
    # We expect SPIKE → CONS transition on this same call (actuals are
    # IN_LINE, te poll gate passes through). Phase should be CONS now.
    assert st["phase"] in (ns._STATE_SPIKE, ns._STATE_CONS)
    assert st["spike_dir"] == "UP"  # locked to chronological-first


def test_strategy_spike_dir_down_when_first_extreme_below(
    fresh_strategy, stub_calendar, stub_te,
):
    ns, _ = fresh_strategy
    strat = ns.NewsStrategy()
    arm_ts, release_epoch, _ = _arm_and_pump(
        ns, strat, stub_calendar, stub_te,
        actuals={"direction_hint": "REVERSAL", "beat_miss": "IN_LINE",
                 "deviation": 0.0},
        anchor_price=13690.0,
    )
    # First post-release extreme DOWN at 13684.5 (5.5p below).
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13684.5,
                   bid=13684.0, ask=13685.0, ts=release_epoch + 5, ppp=PPP)
    # Then big UP move so range threshold fires.
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13702.0,
                   bid=13701.5, ask=13702.5, ts=release_epoch + 30, ppp=PPP)
    st = ns._news_state[SYMBOL]
    assert st["spike_dir"] == "DOWN"


def test_consolidation_break_fires_fade_short_after_up_spike(
    fresh_strategy, stub_calendar, stub_te,
):
    """UP spike to 13710, then consolidation; cons_low forms at 13700;
    next tick 13698 breaks cons_low - 1.5p → WOULD_FIRE SELL (observable)."""
    ns, log_path = fresh_strategy
    strat = ns.NewsStrategy()
    arm_ts, release_epoch, _ = _arm_and_pump(
        ns, strat, stub_calendar, stub_te,
        actuals={"direction_hint": "REVERSAL", "beat_miss": "IN_LINE",
                 "deviation": 0.0, "actual": 2.25, "forecast": 2.25},
        anchor_price=13690.0,
    )
    # Step 1: cross 5p UP threshold (locks spike_dir).
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13696.0,
                   bid=13695.5, ask=13696.5, ts=release_epoch + 10, ppp=PPP)
    # Step 2: hit spike high 13710 (10p above anchor → directional spike fires).
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13710.0,
                   bid=13709.5, ask=13710.5, ts=release_epoch + 30, ppp=PPP)
    st = ns._news_state[SYMBOL]
    assert st["spike_dir"] == "UP"
    # Step 3: consolidation forms — push several ticks at 13700 well past
    # 30s cons-window exclusion.
    for offset in range(45, 90, 5):
        strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13700.0,
                       bid=13699.5, ask=13700.5,
                       ts=release_epoch + offset, ppp=PPP)
    # Step 4: tick well after the 30s exclusion window with a clean
    # break below cons_low - 1.5p.
    decision = strat.evaluate(
        symbol=SYMBOL, epic=EPIC, mid=13697.0,
        bid=13696.5, ask=13697.5,
        ts=release_epoch + 130, ppp=PPP,
    )
    rows = []
    if log_path.exists():
        rows = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    fires = [r for r in rows if r.get("kind") == "WOULD_FIRE"]
    assert fires, f"expected WOULD_FIRE row; rows={rows}"
    assert fires[0]["signal"] == "SELL"
    # Observable-only mode: decision is NONE.
    assert decision.signal == "NONE"
    assert decision.reason == "news_strategy_observable_only"


def test_consolidation_timeout_resets_to_idle(fresh_strategy, stub_calendar, stub_te):
    ns, log_path = fresh_strategy
    strat = ns.NewsStrategy()
    arm_ts, release_epoch, _ = _arm_and_pump(
        ns, strat, stub_calendar, stub_te,
        actuals={"direction_hint": "REVERSAL", "beat_miss": "IN_LINE",
                 "deviation": 0.0},
        anchor_price=13690.0,
    )
    # Force into SPIKE+CONS via a clean directional spike.
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13696.0,
                   bid=13695.5, ask=13696.5, ts=release_epoch + 10, ppp=PPP)
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13710.0,
                   bid=13709.5, ask=13710.5, ts=release_epoch + 30, ppp=PPP)
    st = ns._news_state[SYMBOL]
    assert st["phase"] == ns._STATE_CONS
    spike_time = st["spike_time"]
    # Push a tick past the 60-min consolidation timeout.
    decision = strat.evaluate(
        symbol=SYMBOL, epic=EPIC, mid=13705.0,
        bid=13704.5, ask=13705.5,
        ts=spike_time + ns.NEWS_CONSOLIDATION_TIMEOUT_SECS + 1, ppp=PPP,
    )
    assert decision.reason == "news_strategy_cons_timeout"
    assert ns._news_state[SYMBOL]["phase"] == ns._STATE_IDLE


def test_compute_fade_entry_sl_anchored_to_cons_high_for_up_fade(fresh_strategy):
    """UP spike: spike_extreme=13700.65 (threshold-crossing tick), but
    the true peak captured during CONS is 13710.55. SL must anchor to
    cons_high+5p, not spike_extreme+5p. TP must mirror cons_high past
    anchor, not spike_extreme past anchor — symmetric water-mark
    anchoring."""
    ns, _ = fresh_strategy
    e = ns._compute_fade_entry(
        spike_dir="UP", spike_extreme=13700.65,
        cons_high_at_entry=13710.55, cons_low_at_entry=13700.65,
        mid_price=13698.95, anchor=13690.25, ppp=1.0,
        event_name="BoC Interest Rate Decision",
    )
    assert e is not None
    assert e["signal"] == "SELL"
    # SL = cons_high + 5p.
    assert e["sl_price"] == pytest.approx(13715.55)
    assert e["sl_pips"] == pytest.approx(16.6, abs=0.01)
    # TP = anchor - (cons_high - anchor) = mirror past anchor.
    # spike_size to water mark = |13710.55 - 13690.25| = 20.3p.
    # TP target = 13690.25 - 20.3 = 13669.95.
    # Distance from 13698.95 entry = 29.0p (under 50p cap).
    assert e["tp_pips"] == pytest.approx(29.0, abs=0.01)
    assert e["tp_price"] == pytest.approx(13669.95, abs=0.01)
    assert e["tp_capped"] is False


def test_compute_fade_entry_sl_anchored_to_cons_low_for_down_fade(fresh_strategy):
    ns, _ = fresh_strategy
    # DOWN spike: spike_extreme=13680 (threshold), cons_low captured the
    # true trough at 13670.
    e = ns._compute_fade_entry(
        spike_dir="DOWN", spike_extreme=13680.0,
        cons_high_at_entry=13680.0, cons_low_at_entry=13670.0,
        mid_price=13682.0, anchor=13690.0, ppp=1.0,
        event_name="Manufacturing PMI",
    )
    assert e is not None
    assert e["signal"] == "BUY"
    # SL = cons_low - 5p = 13665.0
    assert e["sl_price"] == pytest.approx(13665.0)
    assert e["sl_pips"] == pytest.approx(17.0)
    # TP = anchor + (anchor - cons_low) = mirror water mark past anchor.
    # spike_size to water mark = |13670 - 13690| = 20p.
    # TP target = 13690 + 20 = 13710. Distance from 13682 entry = 28p.
    assert e["tp_pips"] == pytest.approx(28.0)
    assert e["tp_price"] == pytest.approx(13710.0)


def test_compute_fade_entry_rejects_when_cons_water_mark_too_far(fresh_strategy):
    """Entry at 13670, cons_high at 13710 → SL = 13715, distance = 45p
    above the 25p cap → reject."""
    ns, _ = fresh_strategy
    e = ns._compute_fade_entry(
        spike_dir="UP", spike_extreme=13700.0,
        cons_high_at_entry=13710.0, cons_low_at_entry=13700.0,
        mid_price=13670.0, anchor=13690.0, ppp=1.0,
        event_name="BoC Interest Rate Decision",
    )
    assert e is None


def test_compute_fade_entry_caps_tp_at_max_when_spike_huge(fresh_strategy):
    """cons_high 60p past anchor → mirror TP would be 60p past anchor
    too, distance from entry > 50p → clamp to 50p."""
    ns, _ = fresh_strategy
    e = ns._compute_fade_entry(
        spike_dir="UP", spike_extreme=13750.0,
        cons_high_at_entry=13750.0, cons_low_at_entry=13735.0,
        mid_price=13735.0, anchor=13690.0, ppp=1.0,
        event_name="BoC Interest Rate Decision",
    )
    assert e is not None
    # cons_high = 60p past anchor; mirror TP target = anchor - 60 = 13630;
    # distance from 13735 entry = 105p > 50p cap → clamp.
    assert e["tp_pips"] == pytest.approx(50.0)
    assert e["tp_capped"] is True


def test_continuation_magnitude_lookup(fresh_strategy):
    ns, _ = fresh_strategy
    assert ns.continuation_magnitude("BoC Interest Rate Decision") == {
        "sl_pips": 12, "tp_pips": 50,
    }
    assert ns.continuation_magnitude("Random Indicator") == {
        "sl_pips": 6, "tp_pips": 20,
    }


def test_fade_caps_default(fresh_strategy):
    ns, _ = fresh_strategy
    caps = ns.fade_caps("BoC Interest Rate Decision")
    assert caps["max_sl_pips"] == ns.NEWS_FADE_MAX_SL_PIPS
    assert caps["max_tp_pips"] == ns.NEWS_FADE_MAX_TP_PIPS


def test_event_magnitude_alias_routes_to_continuation(fresh_strategy):
    """Backward-compat: event_magnitude is now an alias for
    continuation_magnitude. EVENT_MAGNITUDE module-level points to
    CONTINUATION_MAGNITUDE."""
    ns, _ = fresh_strategy
    assert ns.event_magnitude("CPI") == ns.continuation_magnitude("CPI")
    assert ns.EVENT_MAGNITUDE is ns.CONTINUATION_MAGNITUDE


def test_observable_only_returns_none_signal_and_logs(
    fresh_strategy, stub_calendar, stub_te,
):
    ns, log_path = fresh_strategy
    assert ns.NEWS_OBSERVABLE_ONLY is True
    strat = ns.NewsStrategy()
    arm_ts, release_epoch, _ = _arm_and_pump(
        ns, strat, stub_calendar, stub_te,
        actuals={"direction_hint": "REVERSAL", "beat_miss": "IN_LINE",
                 "deviation": 0.0},
        anchor_price=13690.0,
    )
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13696.0,
                   bid=13695.5, ask=13696.5, ts=release_epoch + 10, ppp=PPP)
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13710.0,
                   bid=13709.5, ask=13710.5, ts=release_epoch + 30, ppp=PPP)
    for offset in range(45, 90, 5):
        strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13700.0,
                       bid=13699.5, ask=13700.5,
                       ts=release_epoch + offset, ppp=PPP)
    decision = strat.evaluate(
        symbol=SYMBOL, epic=EPIC, mid=13697.0,
        bid=13696.5, ask=13697.5,
        ts=release_epoch + 130, ppp=PPP,
    )
    assert decision.signal == "NONE"
    rows = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    fires = [r for r in rows if r.get("kind") == "WOULD_FIRE"]
    assert len(fires) == 1


def test_30s_exclusion_does_not_fire_on_just_set_low(fresh_strategy, stub_calendar, stub_te):
    """The 30s exclusion forbids the cons_low_so_far from being seeded
    by a tick younger than 30s. With NO older valid ticks in the
    consolidation window, the strategy should report cons_warmup and
    not fire — even if the just-set low + 1.5p break would otherwise
    qualify."""
    ns, log_path = fresh_strategy
    strat = ns.NewsStrategy()
    arm_ts, release_epoch, _ = _arm_and_pump(
        ns, strat, stub_calendar, stub_te,
        actuals={"direction_hint": "REVERSAL", "beat_miss": "IN_LINE",
                 "deviation": 0.0},
        anchor_price=13690.0,
    )
    # Bring spike_dir up via 5p crossing, then hit spike high.
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13696.0,
                   bid=13695.5, ask=13696.5, ts=release_epoch + 10, ppp=PPP)
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13710.0,
                   bid=13709.5, ask=13710.5, ts=release_epoch + 30, ppp=PPP)
    # Push a single LOW tick at 13700 just before the break attempt — no
    # ticks between spike (+30) and offset +65 means no eligible older
    # tick is available when the break attempt runs.
    strat.evaluate(symbol=SYMBOL, epic=EPIC, mid=13700.0,
                   bid=13699.5, ask=13700.5, ts=release_epoch + 65, ppp=PPP)
    # Break attempt 5s later — eligible window = (spike_ts=+30, +70-30=+40].
    # No ticks pushed in (+30, +40] → cons_extremes returns (None, None) →
    # warmup, no fire.
    decision = strat.evaluate(
        symbol=SYMBOL, epic=EPIC, mid=13698.0,
        bid=13697.5, ask=13698.5, ts=release_epoch + 70, ppp=PPP,
    )
    rows = []
    if log_path.exists():
        rows = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    fires = [r for r in rows if r.get("kind") == "WOULD_FIRE"]
    assert not fires, f"30s-exclusion violated; rows={rows}"
    assert decision.reason == "news_strategy_cons_warmup"


# ---------------------------------------------------------------------------
# NEWS_TICK direction logic + cede behaviour
# ---------------------------------------------------------------------------
@pytest.fixture
def fresh_news_tick(monkeypatch, tmp_path, stub_calendar, stub_te):
    """Reload news_tick_strategy AFTER stub_calendar / stub_te have
    placed their stubs in sys.modules — news_tick_strategy.py does a
    top-level `import te_calendar`, so the binding is captured at load
    time and won't pick up later monkeypatches of sys.modules without
    a reload."""
    import news_tick_strategy as nt
    importlib.reload(nt)
    nt._state.clear()
    nt._processed_news_events.clear()
    monkeypatch.setattr(nt, "_persist_state", lambda: None)
    monkeypatch.setattr(nt, "_pre_entry_gate", lambda *a, **kw: (None, None))
    monkeypatch.setattr(nt, "_handle_pre_entry_block", lambda *a, **kw: None)
    monkeypatch.setattr(nt, "_send_telegram", lambda *a, **kw: None)
    yield nt
    nt._state.clear()


def _arm_news_tick(nt, stub_calendar, stub_te, *, anchor_price=13690.0):
    base_ts = time.time()
    from datetime import datetime, timezone, timedelta
    ev_dt = datetime.fromtimestamp(base_ts, tz=timezone.utc) + timedelta(seconds=30)
    stub_calendar([{
        "time": ev_dt.strftime("%H:%M"),
        "currency": "CAD",
        "event_name": "BoC Interest Rate Decision",
        "impact": "High",
    }])
    stub_te(None)
    nt.tick_update(symbol="USDCAD", mid=anchor_price,
                    bid=anchor_price - 0.5, ask=anchor_price + 0.5,
                    ts=base_ts, ppp=1.0,
                    is_blackout=True, blackout_reason="news@13:45UTC")
    return base_ts, ev_dt.timestamp()


def test_news_tick_continuation_uses_currency_action_direction(
    fresh_news_tick, stub_calendar, stub_te, monkeypatch,
):
    """CAD BEAT on rate decision: CAD strengthens → SELL USDCAD,
    regardless of which way price moved first."""
    nt = fresh_news_tick
    monkeypatch.setattr(nt, "NEWS_OBSERVABLE_ONLY", False)
    base_ts, release_epoch = _arm_news_tick(nt, stub_calendar, stub_te,
                                              anchor_price=13690.0)
    # Push price UP first (would have given BUY under the old spike_dir
    # logic) but actuals say CAD BEAT → CAD strengthens → SELL.
    nt.tick_update(symbol="USDCAD", mid=13695.0, bid=13694.5, ask=13695.5,
                    ts=release_epoch + 1, ppp=1.0,
                    is_blackout=True, blackout_reason="news@13:45UTC")
    # Now seed actuals BEAT and trigger PREFLIGHT poll.
    stub_te({"direction_hint": "CONTINUATION", "beat_miss": "BEAT",
             "deviation": 0.10, "actual": 2.50, "forecast": 2.25,
             "te_event": "BoC Interest Rate Decision"})
    res = nt.tick_update(symbol="USDCAD", mid=13696.0,
                          bid=13695.5, ask=13696.5,
                          ts=release_epoch + 6, ppp=1.0,
                          is_blackout=True, blackout_reason="news@13:45UTC")
    assert res is not None
    assert res["signal"] == "SELL"


def test_news_tick_cedes_on_inline(fresh_news_tick, stub_calendar, stub_te):
    nt = fresh_news_tick
    base_ts, release_epoch = _arm_news_tick(nt, stub_calendar, stub_te)
    stub_te({"direction_hint": "REVERSAL", "beat_miss": "IN_LINE",
             "deviation": 0.0, "actual": 2.25, "forecast": 2.25,
             "te_event": "BoC Interest Rate Decision"})
    res = nt.tick_update(symbol="USDCAD", mid=13692.0, bid=13691.5, ask=13692.5,
                          ts=release_epoch + 6, ppp=1.0,
                          is_blackout=True, blackout_reason="news@13:45UTC")
    assert res is None
    # State must reset to IDLE — we ceded.
    assert nt._state["USDCAD"]["phase"] == nt._IDLE


def test_news_tick_cedes_when_no_actuals_and_legacy_off(
    fresh_news_tick, stub_calendar, stub_te,
):
    nt = fresh_news_tick
    assert nt.NEWS_TICK_LEGACY_STALL_PATH is False
    base_ts, release_epoch = _arm_news_tick(nt, stub_calendar, stub_te)
    stub_te(None)
    # Even a 20p move under default config must not fire (no chase path).
    res = nt.tick_update(symbol="USDCAD", mid=13710.0, bid=13709.5, ask=13710.5,
                          ts=release_epoch + 30, ppp=1.0,
                          is_blackout=True, blackout_reason="news@13:45UTC")
    assert res is None
    # Phase is PREFLIGHT awaiting actuals or IDLE post-cede; not a fire.
    phase = nt._state["USDCAD"]["phase"]
    assert phase in (nt._PREFLIGHT, nt._IDLE)


def test_news_tick_legacy_stall_path_disabled_blocks_spike_state(
    fresh_news_tick, stub_calendar, stub_te,
):
    """If state somehow lands in SPIKE under default config (legacy=0),
    next tick must reset to IDLE without firing."""
    nt = fresh_news_tick
    nt._state["USDCAD"] = {
        "phase": nt._SPIKE,
        "spike_dir": "UP",
        "spike_extreme": 13710.0,
        "spike_time": time.time() - 10,
        "anchor": 13690.0, "anchor_time": time.time() - 60,
        "no_new_extreme_count": 12,
        "release_epoch": time.time() - 5,
        "event_currency": "CAD", "event_titles": ["BoC Interest Rate Decision"],
        "armed_time": time.time() - 60,
        "te_result": None,
    }
    res = nt.tick_update(symbol="USDCAD", mid=13708.0, bid=13707.5, ask=13708.5,
                          ts=time.time(), ppp=1.0,
                          is_blackout=True, blackout_reason="")
    assert res is None
    assert nt._state["USDCAD"]["phase"] == nt._IDLE
