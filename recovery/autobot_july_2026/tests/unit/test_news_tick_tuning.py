"""
Regression tests for NEWS_TICK tuning — 2026-04-23 changes.

Change 2: NEWS_TICK_SPIKE_MIN_PIPS default 15 → 8.
Change 3: _expire_at uses new NEWS_TICK_ARMED_RELEASE_WINDOW_SECS (300s)
          instead of the 120s NEWS_TICK_SPIKE_WINDOW_SECS.
Change 4: per-event SL/TP routing via _is_tight_tp_event classifier.

The 2026-04-23 GBP PMI event was the motivating case:
  - peak diff from anchor: 14.8p at 08:31:50 (missed 15p threshold by 0.2p)
  - later peak: 15.3p at ~08:35 (missed because _expire_at=08:32:00)
Both issues addressed: 8p threshold + 300s window.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Change 2 — spike threshold
# ---------------------------------------------------------------------------

def test_default_threshold_is_8_pips():
    """Module default must be 8, not 15."""
    import importlib
    import news_tick_strategy
    # If env override is set, the module's runtime constant may differ.
    # Check the literal default in the os.getenv call.
    import inspect
    src = inspect.getsource(news_tick_strategy)
    assert 'NEWS_TICK_SPIKE_MIN_PIPS", os.getenv("NEWS_SPIKE_MIN_PIPS", "8")' in src, (
        "module-level default for NEWS_TICK_SPIKE_MIN_PIPS must be '8'"
    )


def test_env_override_is_8_pips():
    """`.env` file contains NEWS_TICK_SPIKE_MIN_PIPS=8."""
    with open("/opt/tradingbot/.env") as f:
        env_text = f.read()
    assert "NEWS_TICK_SPIKE_MIN_PIPS=8" in env_text
    assert "NEWS_TICK_SPIKE_MIN_PIPS=15" not in env_text


def test_threshold_catches_gbp_pmi_14p_move_with_new_default(monkeypatch):
    """At the GBP PMI peak of 14.8p above anchor, the 8p threshold
    fires; the old 15p threshold did not."""
    # Force threshold to 8 (module may have loaded with env override)
    import news_tick_strategy
    monkeypatch.setattr(news_tick_strategy, "NEWS_TICK_SPIKE_MIN_PIPS", 8.0)
    diff_pips = 14.8  # today's GBP PMI peak
    assert abs(diff_pips) >= news_tick_strategy.NEWS_TICK_SPIKE_MIN_PIPS
    # And 15p would have rejected it:
    assert abs(diff_pips) < 15.0


# ---------------------------------------------------------------------------
# Change 3 — ARMED/PREFLIGHT expire window
# ---------------------------------------------------------------------------

def test_armed_release_window_default_is_300():
    """New constant NEWS_TICK_ARMED_RELEASE_WINDOW_SECS default = 300."""
    import news_tick_strategy
    assert hasattr(news_tick_strategy, "NEWS_TICK_ARMED_RELEASE_WINDOW_SECS")
    import inspect
    src = inspect.getsource(news_tick_strategy)
    assert 'NEWS_TICK_ARMED_RELEASE_WINDOW_SECS", "300"' in src, (
        "NEWS_TICK_ARMED_RELEASE_WINDOW_SECS default must be '300'"
    )


def test_spike_window_unchanged_at_120():
    """NEWS_TICK_SPIKE_WINDOW_SECS still defaults to 120 (narrow
    scope: only _expire_at was widened)."""
    import news_tick_strategy
    import inspect
    src = inspect.getsource(news_tick_strategy)
    assert 'NEWS_TICK_SPIKE_WINDOW_SECS", "120"' in src, (
        "NEWS_TICK_SPIKE_WINDOW_SECS must remain '120'"
    )


def test_expire_at_uses_armed_window_not_spike_window():
    """Both _expire_at sites must use ARMED_RELEASE_WINDOW, not SPIKE_WINDOW."""
    import inspect
    import news_tick_strategy
    src = inspect.getsource(news_tick_strategy.tick_update)
    # Count usages: the 2 _expire_at calcs must reference ARMED_RELEASE_WINDOW
    armed_usages = src.count("NEWS_TICK_ARMED_RELEASE_WINDOW_SECS")
    assert armed_usages == 2, (
        f"expected 2 ARMED_RELEASE_WINDOW refs in tick_update (both _expire_at), got {armed_usages}"
    )
    # The _expire_at calcs should NOT reference the old 120s SPIKE_WINDOW:
    assert "_expire_at = max(st.get(\"release_epoch\", 0) + NEWS_TICK_SPIKE_WINDOW_SECS" not in src, (
        "_expire_at must no longer use NEWS_TICK_SPIKE_WINDOW_SECS"
    )


# ---------------------------------------------------------------------------
# Change 4 — TIGHT_TP event classifier
# ---------------------------------------------------------------------------

_TIGHT_TITLES = [
    "S&P Global Manufacturing PMI Flash",
    "ISM Manufacturing PMI",
    "UoM Consumer Sentiment",
    "CB Consumer Confidence",
    "Michigan Consumer Sentiment",
    "Industrial Production m/m",
]
_WIDE_TITLES = [
    "CPI y/y",
    "Non-Farm Employment Change",
    "FOMC Statement",
    "ECB Interest Rate Decision",
    "Retail Sales m/m",
]


@pytest.mark.parametrize("title", _TIGHT_TITLES)
def test_tight_classifier_matches_known_titles(title):
    import news_tick_strategy
    assert news_tick_strategy._is_tight_tp_event([title]) is True, (
        f"title {title!r} must classify as TIGHT"
    )


@pytest.mark.parametrize("title", _WIDE_TITLES)
def test_wide_classifier_rejects_non_matching_titles(title):
    import news_tick_strategy
    assert news_tick_strategy._is_tight_tp_event([title]) is False, (
        f"title {title!r} must classify as WIDE"
    )


def test_classifier_empty_list_defaults_wide():
    import news_tick_strategy
    assert news_tick_strategy._is_tight_tp_event([]) is False
    assert news_tick_strategy._is_tight_tp_event(None) is False


def test_classifier_multi_title_any_match_wins():
    import news_tick_strategy
    # PMI + CPI — any tight keyword triggers
    titles = ["CPI y/y", "S&P Global Composite PMI Flash"]
    assert news_tick_strategy._is_tight_tp_event(titles) is True


def test_classifier_skips_empty_title_entries():
    import news_tick_strategy
    assert news_tick_strategy._is_tight_tp_event(["", None, "CPI y/y"]) is False


# ---------------------------------------------------------------------------
# Change 4 — _build_entry SL/TP routing
# ---------------------------------------------------------------------------

def test_build_entry_tight_buy_tp_from_anchor():
    """TIGHT BUY: TP = anchor + 20p. SL = entry - 6p.
    Entry chosen so anchor-TP distance > MIN_TIGHT_TP_PIPS, guarding
    against the widening guard kicking in for this scenario."""
    import news_tick_strategy
    anchor = 13487.0
    entry = 13490.0  # price moved +3p from anchor → tp_pips=17 (safely above guard)
    ppp = 1.0
    r = news_tick_strategy._build_entry(
        signal="BUY", entry_price=entry, spike_dir="UP",
        anchor=anchor, extreme=entry, ppp=ppp,
        reason_tag="preflight",
        event_titles=["S&P Global Manufacturing PMI Flash"],
        sl_override=10.0,   # TIGHT must override this
    )
    # TP anchored at anchor + 20
    assert r["tp_price"] == pytest.approx(anchor + 20.0), f"TP price={r['tp_price']}"
    # SL 6p below entry
    assert r["sl_price"] == pytest.approx(entry - 6.0), f"SL price={r['sl_price']}"
    assert r["sl"] == 6.0
    # tp_pips is distance from entry to tp_price
    assert r["tp"] == pytest.approx(17.0), f"tp_pips={r['tp']} (expected 17 = 13507-13490)"
    assert r["debug"]["tight_tp"] is True


def test_build_entry_tight_sell_tp_from_anchor():
    """TIGHT SELL: TP = anchor - 20p. SL = entry + 6p."""
    import news_tick_strategy
    anchor = 13487.0
    entry = 13480.0  # price moved -7p from anchor
    ppp = 1.0
    r = news_tick_strategy._build_entry(
        signal="SELL", entry_price=entry, spike_dir="DOWN",
        anchor=anchor, extreme=entry, ppp=ppp,
        reason_tag="spike_fallback",
        event_titles=["ISM Manufacturing PMI"],
    )
    assert r["tp_price"] == pytest.approx(anchor - 20.0)
    assert r["sl_price"] == pytest.approx(entry + 6.0)
    assert r["sl"] == 6.0
    assert r["tp"] == pytest.approx(13.0), f"tp_pips={r['tp']} (expected 13 = 13480-13467)"
    assert r["debug"]["tight_tp"] is True


def test_build_entry_wide_default_formula():
    """WIDE (non-TIGHT title): spike-proportional SL+TP."""
    import news_tick_strategy
    anchor = 13487.0
    entry = 13510.0  # spike_pips = 23
    extreme = 13510.0
    ppp = 1.0
    r = news_tick_strategy._build_entry(
        signal="BUY", entry_price=entry, spike_dir="UP",
        anchor=anchor, extreme=extreme, ppp=ppp,
        reason_tag="spike_fallback",
        event_titles=["Non-Farm Employment Change"],
    )
    # SL = max(15, min(25, spike*0.5)) = max(15, min(25, 11.5)) = 15
    assert r["sl"] == pytest.approx(15.0)
    # TP = max(30, min(120, spike*1.5)) = max(30, min(120, 34.5)) = 34.5
    assert r["tp"] == pytest.approx(34.5)
    assert r["debug"]["tight_tp"] is False


def test_build_entry_wide_with_sl_override():
    """WIDE + sl_override (PREFLIGHT path): override SL, keep spike-
    proportional TP."""
    import news_tick_strategy
    anchor = 13487.0
    entry = 13490.0
    extreme = 13492.0
    ppp = 1.0
    r = news_tick_strategy._build_entry(
        signal="BUY", entry_price=entry, spike_dir="UP",
        anchor=anchor, extreme=extreme, ppp=ppp,
        reason_tag="preflight",
        event_titles=["Non-Farm Employment Change"],
        sl_override=10.0,
    )
    assert r["sl"] == 10.0
    assert r["debug"]["tight_tp"] is False


def test_build_entry_empty_titles_defaults_wide():
    import news_tick_strategy
    r = news_tick_strategy._build_entry(
        signal="BUY", entry_price=13500.0, spike_dir="UP",
        anchor=13487.0, extreme=13500.0, ppp=1.0,
        reason_tag="spike_fallback",
        event_titles=[],
    )
    assert r["debug"]["tight_tp"] is False
    # SL/TP follow WIDE formula
    assert r["sl"] >= 15.0 and r["sl"] <= 25.0


def test_build_entry_none_titles_defaults_wide():
    import news_tick_strategy
    r = news_tick_strategy._build_entry(
        signal="BUY", entry_price=13500.0, spike_dir="UP",
        anchor=13487.0, extreme=13500.0, ppp=1.0,
        reason_tag="spike_fallback",
        event_titles=None,
    )
    assert r["debug"]["tight_tp"] is False


def test_tight_applied_to_all_five_fire_paths():
    """Every reason_tag that NEWS_TICK uses at _build_entry must honor
    TIGHT classification. Simulate each reason_tag and assert TIGHT
    output shape (6p SL, anchor-based TP)."""
    import news_tick_strategy
    anchor = 13487.0
    entry = 13495.0
    for reason in ("preflight", "spike_fallback", "te_continuation",
                    "continuation", "reversal"):
        r = news_tick_strategy._build_entry(
            signal="BUY", entry_price=entry, spike_dir="UP",
            anchor=anchor, extreme=entry, ppp=1.0,
            reason_tag=reason,
            event_titles=["Composite PMI Flash"],
        )
        assert r["debug"]["tight_tp"] is True, f"reason={reason} failed TIGHT routing"
        assert r["sl"] == 6.0, f"reason={reason} SL should be 6p, got {r['sl']}"
        assert r["tp_price"] == pytest.approx(anchor + 20.0), (
            f"reason={reason} TP should be anchor+20, got {r['tp_price']}"
        )


def test_tight_tp_distance_reflects_entry_offset_from_anchor():
    """tp_pips (distance reported) varies with how far entry drifted
    from anchor before fire, bounded below by MIN_TIGHT_TP_PIPS."""
    import news_tick_strategy
    anchor = 13487.0
    # Entry close to anchor
    r1 = news_tick_strategy._build_entry(
        signal="BUY", entry_price=13490.0, spike_dir="UP",
        anchor=anchor, extreme=13490.0, ppp=1.0,
        reason_tag="preflight",
        event_titles=["Services PMI"],
    )
    assert r1["tp"] == pytest.approx(17.0)  # 13507 - 13490

    # Entry further from anchor — still above MIN_TIGHT_TP_PIPS (8)
    # (entry 13499 → 13507-13499=8.0 — exactly at floor, no widening)
    r2 = news_tick_strategy._build_entry(
        signal="BUY", entry_price=13499.0, spike_dir="UP",
        anchor=anchor, extreme=13499.0, ppp=1.0,
        reason_tag="preflight",
        event_titles=["Services PMI"],
    )
    assert r2["tp"] == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# Late-entry guard: TIGHT_TP widens to MIN_TIGHT_TP_PIPS when anchor-based
# TP would be too close to entry (price drifted in spike direction)
# ---------------------------------------------------------------------------

def test_tight_buy_late_entry_widens_tp_to_minimum(caplog):
    """BUY + price already drifted 18p up from anchor 13487 → entry 13505.
    Anchor-TP would be 13507, only 2p from entry. Guard widens TP to 8p
    from entry (= 13513)."""
    import logging
    import news_tick_strategy
    anchor = 13487.0
    entry = 13505.0   # drifted 18p in BUY direction
    ppp = 1.0
    with caplog.at_level(logging.INFO, logger="AutoBot"):
        r = news_tick_strategy._build_entry(
            signal="BUY", entry_price=entry, spike_dir="UP",
            anchor=anchor, extreme=entry, ppp=ppp,
            reason_tag="spike_fallback",
            event_titles=["S&P Global Manufacturing PMI Flash"],
            symbol="GBPUSD",
        )
    assert r["tp"] == pytest.approx(8.0), (
        f"expected tp widened to 8p minimum; got {r['tp']}"
    )
    assert r["tp_price"] == pytest.approx(entry + 8.0), (
        f"tp_price should be entry+8p; got {r['tp_price']}"
    )
    assert r["sl"] == 6.0  # SL unchanged
    assert r["debug"]["tight_tp"] is True
    # Guard-widen log line fired
    widen_logs = [rec for rec in caplog.records
                  if "late entry: anchor-TP would be" in rec.getMessage()]
    assert len(widen_logs) == 1, (
        f"expected 1 late-entry widening log, got {len(widen_logs)}"
    )
    msg = widen_logs[0].getMessage()
    assert "GBPUSD" in msg
    assert "2.0p" in msg  # original tp_pips before widening
    assert "8.0p" in msg  # floor


def test_tight_sell_late_entry_widens_tp_to_minimum():
    """SELL + price already dropped 16p → entry 13471. Anchor-TP (13467)
    would be 4p from entry. Guard widens to 8p (tp_price=13463)."""
    import news_tick_strategy
    anchor = 13487.0
    entry = 13471.0   # dropped 16p
    ppp = 1.0
    r = news_tick_strategy._build_entry(
        signal="SELL", entry_price=entry, spike_dir="DOWN",
        anchor=anchor, extreme=entry, ppp=ppp,
        reason_tag="te_continuation",
        event_titles=["ISM Manufacturing PMI"],
        symbol="EURUSD",
    )
    assert r["tp"] == pytest.approx(8.0)
    assert r["tp_price"] == pytest.approx(entry - 8.0)
    assert r["sl"] == 6.0
    assert r["sl_price"] == pytest.approx(entry + 6.0)  # SELL: SL above entry
    assert r["debug"]["tight_tp"] is True


def test_tight_normal_entry_does_not_trigger_guard():
    """Regression: normal TIGHT fire (entry close to anchor) keeps the
    anchor-based TP and does NOT trigger the widening guard."""
    import news_tick_strategy
    anchor = 13487.0
    entry = 13490.0   # drifted only 3p — anchor-TP (13507) is 17p away
    ppp = 1.0
    r = news_tick_strategy._build_entry(
        signal="BUY", entry_price=entry, spike_dir="UP",
        anchor=anchor, extreme=entry, ppp=ppp,
        reason_tag="preflight",
        event_titles=["Services PMI"],
        symbol="GBPUSD",
    )
    # tp_pips = 17p, well above 8p floor; guard does NOT fire
    assert r["tp"] == pytest.approx(17.0)
    assert r["tp_price"] == pytest.approx(anchor + 20.0)  # still anchor-based
