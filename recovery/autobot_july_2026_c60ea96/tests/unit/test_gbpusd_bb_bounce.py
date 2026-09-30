"""
Unit tests for gbpusd_bb_bounce — entry-logic correctness.

Covers:
  - Trigger detection (LONG / SHORT, intra-bar and prev-bar pierce)
  - SL calculation, floor, ceiling
  - TP at BB middle, min-TP rejection
  - Daily fire cap (2 per direction)
  - Re-arm immediately after stop-out (no internal cooldown)
  - News-blackout exemption shape (in-strategy pre-news check)
  - Cross-module integration (pair-dedup bypass, MPP skip, BRIEF_INVALIDATED skip)
"""
from __future__ import annotations

import sys
from datetime import datetime, time as dtime, timedelta, timezone
from typing import List, Tuple

import pytest

sys.path.insert(0, "/opt/tradingbot")

import gbpusd_bb_bounce as bb  # noqa: E402
from gbpusd_bb_bounce import Bar  # noqa: E402


SYMBOL = "GBPUSD"
EPIC = "CS.D.GBPUSD.TODAY.IP"
PIP = 1.0

# v1 BB-pierce-and-recover contract — strategy rewritten to
# BB_PIERCE_RUN 2026-05-02 (commit 3ac8749); these tests predate
# the rewrite and exercise removed daily-cap / sl-floor / pierce-
# recover behaviour.
_OBSOLETE_BB_PIERCE_REWRITE_REASON = (
    "v1 BB-pierce-and-recover contract — strategy rewritten to "
    "BB_PIERCE_RUN 2026-05-02 (commit 3ac8749); test predates rewrite"
)


@pytest.fixture(autouse=True)
def _clean_state(tmp_path, monkeypatch):
    # _STATE_FILE existed under the original BB-pierce-and-recover strategy
    # (commit 556d0c8) and was removed in the BB_PIERCE_RUN rewrite
    # (commit 3ac8749). raising=False keeps the fixture inert against the
    # rewritten module so tests that don't depend on daily-cap state-file
    # behaviour can still run.
    state_file = tmp_path / "bb_bounce_state.json"
    monkeypatch.setattr(bb, "_STATE_FILE", str(state_file), raising=False)
    yield


def _ts(start: datetime, i: int) -> datetime:
    return start + timedelta(minutes=5 * i)


def _bar(ts: datetime, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(timestamp=ts, open=o, high=h, low=l, close=c)


def _baseline_closes(n: int = 19, base: float = 13520.0) -> List[float]:
    """Tight oscillation around `base` so BB lower stays close to it."""
    return [base + ((-1) ** i) * 0.3 for i in range(n)]


def _bb_at(closes: List[float]) -> Tuple[float, float, float]:
    return bb._bb_20_2(closes)


# ---------------------------------------------------------------------------
# Trigger geometry
# ---------------------------------------------------------------------------
@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_trigger_long_intra_bar_pierce_recover():
    """Single-bar pierce: cur.low <= BBL AND cur.close > BBL."""
    bb_lower, bb_upper = 13500.0, 13540.0
    prev = _bar(datetime.now(timezone.utc), 13510.0, 13515.0, 13505.0, 13510.0)
    cur  = _bar(datetime.now(timezone.utc), 13510.0, 13513.0, 13495.0, 13511.0)
    assert bb._detect_pierce_recover([prev, cur], bb_lower, bb_upper) == "BUY"


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_trigger_long_prev_bar_pierce_recover():
    """Prev-bar pierce: prev.low <= BBL AND cur.close > BBL."""
    bb_lower, bb_upper = 13500.0, 13540.0
    prev = _bar(datetime.now(timezone.utc), 13505.0, 13508.0, 13498.0, 13505.0)  # pierces
    cur  = _bar(datetime.now(timezone.utc), 13505.0, 13513.0, 13503.0, 13511.0)  # closes above
    assert bb._detect_pierce_recover([prev, cur], bb_lower, bb_upper) == "BUY"


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_trigger_long_touch_equals_pierce():
    """low == BBL counts as pierce (<=)."""
    bb_lower, bb_upper = 13500.0, 13540.0
    prev = _bar(datetime.now(timezone.utc), 13510.0, 13513.0, 13510.0, 13510.0)
    cur  = _bar(datetime.now(timezone.utc), 13510.0, 13513.0, 13500.0, 13511.0)  # low = BBL exactly
    assert bb._detect_pierce_recover([prev, cur], bb_lower, bb_upper) == "BUY"


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_trigger_long_pierce_no_recover_fails():
    """Cur pierces and closes still below BBL — not a bounce."""
    bb_lower, bb_upper = 13500.0, 13540.0
    prev = _bar(datetime.now(timezone.utc), 13510.0, 13515.0, 13505.0, 13510.0)
    cur  = _bar(datetime.now(timezone.utc), 13510.0, 13510.0, 13495.0, 13498.0)
    assert bb._detect_pierce_recover([prev, cur], bb_lower, bb_upper) is None


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_trigger_long_no_pierce_fails():
    bb_lower, bb_upper = 13500.0, 13540.0
    prev = _bar(datetime.now(timezone.utc), 13510.0, 13515.0, 13505.0, 13512.0)
    cur  = _bar(datetime.now(timezone.utc), 13512.0, 13518.0, 13510.0, 13515.0)
    assert bb._detect_pierce_recover([prev, cur], bb_lower, bb_upper) is None


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_trigger_short_intra_bar_pierce_recover():
    bb_lower, bb_upper = 13500.0, 13540.0
    prev = _bar(datetime.now(timezone.utc), 13530.0, 13535.0, 13525.0, 13530.0)
    cur  = _bar(datetime.now(timezone.utc), 13530.0, 13545.0, 13528.0, 13532.0)
    assert bb._detect_pierce_recover([prev, cur], bb_lower, bb_upper) == "SELL"


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_trigger_short_prev_bar_pierce_recover():
    bb_lower, bb_upper = 13500.0, 13540.0
    prev = _bar(datetime.now(timezone.utc), 13535.0, 13545.0, 13530.0, 13535.0)
    cur  = _bar(datetime.now(timezone.utc), 13535.0, 13540.0, 13530.0, 13534.0)
    assert bb._detect_pierce_recover([prev, cur], bb_lower, bb_upper) == "SELL"


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_trigger_short_pierce_no_recover_fails():
    bb_lower, bb_upper = 13500.0, 13540.0
    prev = _bar(datetime.now(timezone.utc), 13530.0, 13535.0, 13525.0, 13530.0)
    cur  = _bar(datetime.now(timezone.utc), 13530.0, 13545.0, 13530.0, 13542.0)  # close > BBU
    assert bb._detect_pierce_recover([prev, cur], bb_lower, bb_upper) is None


# ---------------------------------------------------------------------------
# evaluate() — full path
# ---------------------------------------------------------------------------
def _build_long_setup(start: datetime,
                       trig_low: float = 13505.0,
                       trig_close: float = 13520.0,
                       ) -> Tuple[List[Bar], List[float], float, float]:
    """Build 20-bar setup with hardcoded prices producing a stable BB.

    Baseline: 18 closes alternating 13520/13540, prev close 13530.
    With trig_close=13520 → BBL ≈ 13510, BBM ≈ 13529.5, BBU ≈ 13549.
    Caller controls (trig_low, trig_close). Returns (bars, closes, BBL, BBM).
    """
    bars: List[Bar] = []
    closes: List[float] = []
    # 18 alternating bars ±10 around 13530.
    for i in range(18):
        c = 13530.0 + ((-1) ** i) * 10.0
        bars.append(_bar(_ts(start, i), c, c + 0.5, c - 0.5, c))
        closes.append(c)
    # Prev bar — sits in mid-band, no pierce.
    prev_close = 13530.0
    bars.append(_bar(_ts(start, 18), 13530.0, 13531.0, 13525.0, prev_close))
    closes.append(prev_close)
    # Trigger bar with caller-specified low and close.
    bars.append(_bar(_ts(start, 19),
                     prev_close,
                     max(trig_close, prev_close) + 0.2,
                     trig_low,
                     trig_close))
    closes.append(trig_close)
    bb_lower, bb_mid, _ = bb._bb_20_2(closes)
    return bars, closes, bb_lower, bb_mid


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_evaluate_long_fires_with_correct_sl_tp():
    """Trigger.low=13505 (5p below BBL ~13510), close=13520 (10p above BBL,
    9.5p below BBM). SL = (13520-13505)+5 = 20p, TP ≈ 9.5p."""
    start = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    bars, closes, bb_lower, bb_mid = _build_long_setup(
        start, trig_low=13505.0, trig_close=13520.0,
    )
    s = bb.GbpUsdBBBounceStrategy()
    dec = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=bars[-1].timestamp,
                     bars=bars, closes_ind=closes)
    assert dec is not None, "expected a decision"
    assert dec.signal == "BUY"
    assert dec.mode == "GBPUSD_BB_BOUNCE_L"
    assert dec.regime == "BB_BOUNCE"
    # SL = (close - low) + buffer = 15 + 5 = 20p.
    assert dec.sl == pytest.approx(20.0, abs=0.01)
    # TP = BBM - close.
    expected_tp = bb_mid - 13520.0
    assert dec.tp == pytest.approx(round(expected_tp, 2), abs=0.01)
    assert dec.use_trailing_stop is False
    assert dec.debug["bb_lower"] == round(bb_lower, 4)
    assert dec.debug["bb_mid"] == round(bb_mid, 4)


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_evaluate_long_sl_floor_at_8p(monkeypatch):
    """Tiny pierce → raw SL would be < 8p; clamps to 8p.

    A real-data setup can't satisfy both `SL_raw < 8` (needs close-low < 3p)
    AND `TP_raw >= 8` (needs BBM-close >= 8p), so we monkeypatch the BB
    to decouple BBL from BBM (BBL=13510, BBM=13525).
    """
    monkeypatch.setattr(bb, "_bb_20_2",
                        lambda closes, period=20, std_mult=2.0:
                            (13510.0, 13525.0, 13540.0))
    start = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    closes = [13520.0] * 20
    prev = _bar(_ts(start, 18), 13520.0, 13521.0, 13519.0, 13520.0)
    # trig.low=13509 (1p below BBL=13510), trig.close=13511 (1p above BBL).
    # SL_raw = (13511 - 13509) + 5 = 7p → clamps to floor 8p.
    # TP = BBM - close = 13525 - 13511 = 14p (well above min).
    trig = _bar(_ts(start, 19), 13520.0, 13511.5, 13509.0, 13511.0)
    bars = [prev, trig]
    s = bb.GbpUsdBBBounceStrategy()
    dec = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=trig.timestamp,
                     bars=bars, closes_ind=closes)
    assert dec is not None
    assert dec.sl == 8.0
    assert dec.tp == pytest.approx(14.0, abs=0.01)


def test_evaluate_long_sl_ceiling_rejects_above_25p():
    """Huge wick → SL > 25p; reject."""
    start = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    # trig_close=13520 BBL≈13510 OK, trig_low=13495 → SL_raw = 25+5 = 30p > 25 → reject.
    bars, closes, _, _ = _build_long_setup(
        start, trig_low=13495.0, trig_close=13520.0,
    )
    s = bb.GbpUsdBBBounceStrategy()
    dec = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=bars[-1].timestamp,
                     bars=bars, closes_ind=closes)
    assert dec is None


def test_evaluate_long_tp_floor_rejects_below_8p():
    """Trigger close just below BBM (<8p away) → TP < 8p; reject."""
    start = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    # First find BBM with default trigger, then place close BBM-3.
    _, _, _, bbm0 = _build_long_setup(start, trig_low=13505.0, trig_close=13520.0)
    bars, closes, _, _ = _build_long_setup(
        start, trig_low=13505.0, trig_close=bbm0 - 3.0,
    )
    s = bb.GbpUsdBBBounceStrategy()
    dec = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=bars[-1].timestamp,
                     bars=bars, closes_ind=closes)
    assert dec is None


def _build_short_setup(start: datetime,
                        trig_high: float = 13555.0,
                        trig_close: float = 13540.0,
                        ) -> Tuple[List[Bar], List[float], float, float]:
    """Mirror of _build_long_setup. Baseline produces BBU ≈ 13549, BBM ≈ 13530.
    Caller controls (trig_high, trig_close)."""
    bars: List[Bar] = []
    closes: List[float] = []
    for i in range(18):
        c = 13530.0 + ((-1) ** i) * 10.0
        bars.append(_bar(_ts(start, i), c, c + 0.5, c - 0.5, c))
        closes.append(c)
    prev_close = 13530.0
    bars.append(_bar(_ts(start, 18), 13530.0, 13535.0, 13530.0, prev_close))
    closes.append(prev_close)
    bars.append(_bar(_ts(start, 19),
                     prev_close,
                     trig_high,
                     min(trig_close, prev_close) - 0.2,
                     trig_close))
    closes.append(trig_close)
    _, bb_mid, bb_upper = bb._bb_20_2(closes)
    return bars, closes, bb_upper, bb_mid


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_evaluate_short_fires():
    """trig_high=13555 (6p above BBU≈13549), close=13540 (9p below BBU,
    10p above BBM≈13530 → TP=10p)."""
    start = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    bars, closes, bb_upper, bb_mid = _build_short_setup(
        start, trig_high=13555.0, trig_close=13540.0,
    )
    s = bb.GbpUsdBBBounceStrategy()
    dec = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=bars[-1].timestamp,
                     bars=bars, closes_ind=closes)
    assert dec is not None
    assert dec.signal == "SELL"
    assert dec.mode == "GBPUSD_BB_BOUNCE_S"
    # SL = (high - close) + 5 = 15 + 5 = 20p.
    assert dec.sl == pytest.approx(20.0, abs=0.01)
    # TP = close - BBM.
    assert dec.tp == pytest.approx(round(13540.0 - bb_mid, 2), abs=0.01)


# ---------------------------------------------------------------------------
# Daily fire cap (2 per direction)
# ---------------------------------------------------------------------------
@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_daily_cap_blocks_third_long():
    s = bb.GbpUsdBBBounceStrategy()
    sess = "2026-04-30"
    s._counts[sess] = {"BUY": 2, "SELL": 0}
    assert s._can_enter(sess, "BUY") is False
    assert s._can_enter(sess, "SELL") is True
    s._counts[sess] = {"BUY": 1, "SELL": 0}
    assert s._can_enter(sess, "BUY") is True


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_daily_cap_resets_at_06_utc():
    s = bb.GbpUsdBBBounceStrategy()
    early = datetime(2026, 4, 30, 5, 30, tzinfo=timezone.utc)  # before 06:00
    after = datetime(2026, 4, 30, 6, 30, tzinfo=timezone.utc)
    assert s._session_date(early) == "2026-04-29"
    assert s._session_date(after) == "2026-04-30"


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_daily_cap_blocks_evaluate_after_2_long_entries():
    """Live integration: pre-load counter and verify a third LONG fails."""
    start = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    bars, closes, _, _ = _build_long_setup(
        start, trig_low=13505.0, trig_close=13520.0,
    )
    s = bb.GbpUsdBBBounceStrategy()
    sess = s._session_date(bars[-1].timestamp)
    s._counts[sess] = {"BUY": 2, "SELL": 0}
    dec = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=bars[-1].timestamp,
                     bars=bars, closes_ind=closes)
    assert dec is None


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_short_cap_independent_of_long_cap():
    s = bb.GbpUsdBBBounceStrategy()
    sess = "2026-04-30"
    s._counts[sess] = {"BUY": 2, "SELL": 0}
    # SHORT must still be allowed — the cap is per-direction.
    assert s._can_enter(sess, "SELL") is True


# ---------------------------------------------------------------------------
# Re-arm after stop-out (no internal cooldown)
# ---------------------------------------------------------------------------
@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_re_arm_after_stop_out_immediate():
    """Strategy itself imposes no time-based cooldown. A subsequent fresh
    trigger on a *new* bar after a stop-out must evaluate normally; only
    the daily cap applies."""
    s = bb.GbpUsdBBBounceStrategy()
    sess = "2026-04-30"
    # Simulate one entry has fired and been stopped out.
    s._record_entry(sess, "BUY")
    assert s._counts[sess]["BUY"] == 1
    # Counter still allows another entry today (cap = 2).
    assert s._can_enter(sess, "BUY") is True
    # Strategy file must NOT implement its own cooldown state machine —
    # there is no autobot-side cooldown gate either (stripped 2026-05-22).
    # The word "cooldown" only appears in module-level docstring comments.
    src = open("/opt/tradingbot/gbpusd_bb_bounce.py").read()
    # No cooldown timer fields, no last-trade timestamp tracking.
    assert "_last_trade_ts" not in src
    assert "cooldown_until" not in src.lower()
    assert "time.time()" not in src  # no wall-clock cooldown checks


@pytest.mark.skip(reason=_OBSOLETE_BB_PIERCE_REWRITE_REASON)
def test_dedup_eval_per_bar():
    """Same bar timestamp evaluated twice must not double-fire (or even
    re-evaluate). Different bar timestamp does evaluate."""
    start = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    bars, closes, _, _ = _build_long_setup(
        start, trig_low=13505.0, trig_close=13520.0,
    )
    s = bb.GbpUsdBBBounceStrategy()
    dec1 = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=bars[-1].timestamp,
                      bars=bars, closes_ind=closes)
    assert dec1 is not None
    # Second call with same bar — dedup'd.
    dec2 = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=bars[-1].timestamp,
                      bars=bars, closes_ind=closes)
    assert dec2 is None


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
def test_outside_window_returns_none():
    """22:00 UTC is past WIN_END (21:00). Strategy must reject."""
    start = datetime(2026, 4, 28, 22, 0, tzinfo=timezone.utc)
    bars, closes, _, _ = _build_long_setup(start, trig_low=13505.0, trig_close=13520.0)
    s = bb.GbpUsdBBBounceStrategy()
    dec = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=bars[-1].timestamp,
                     bars=bars, closes_ind=closes)
    assert dec is None


def test_weekend_returns_none():
    """Saturday — no trading."""
    start = datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc)  # Saturday
    assert start.weekday() == 5
    bars, closes, _, _ = _build_long_setup(start, trig_low=13505.0, trig_close=13520.0)
    s = bb.GbpUsdBBBounceStrategy()
    dec = s.evaluate(symbol="GBPUSD", epic=EPIC, ts=bars[-1].timestamp,
                     bars=bars, closes_ind=closes)
    assert dec is None


def test_non_gbpusd_returns_none():
    start = datetime(2026, 4, 28, 9, 0, tzinfo=timezone.utc)
    bars, closes, _, _ = _build_long_setup(start, trig_low=13505.0, trig_close=13520.0)
    s = bb.GbpUsdBBBounceStrategy()
    dec = s.evaluate(symbol="EURUSD", epic="CS.D.EURUSD.TODAY.IP",
                     ts=bars[-1].timestamp, bars=bars, closes_ind=closes)
    assert dec is None


# ---------------------------------------------------------------------------
# Integration — autobot / trade_executor / trade_manager wiring
# ---------------------------------------------------------------------------
def test_cooldown_bypass_mechanism_stripped():
    """Regression guard: the per-pair cooldown gate and its
    _COOLDOWN_BYPASS_MODES allowlist were stripped from autobot.py
    (V1 strip-out step 3j, 2026-05-22). Nothing should re-introduce the
    symbol — there is no cooldown left to bypass. Dispatch-block
    presence is covered separately by test_autobot_dispatch_block_present."""
    src = open("/opt/tradingbot/autobot.py").read()
    assert "_COOLDOWN_BYPASS_MODES" not in src


def test_pair_dedup_bypass_includes_bb_bounce():
    src = open("/opt/tradingbot/trade_executor.py").read()
    assert "_PAIR_DEDUP_BYPASS_MODES" in src
    assert "GBPUSD_BB_BOUNCE_L" in src
    assert "GBPUSD_BB_BOUNCE_S" in src


def test_brief_invalidated_skip_includes_bb_bounce():
    src = open("/opt/tradingbot/trade_manager.py").read()
    idx = src.find('"BRIEFING_EXECUTION", "BB_REVERSAL", "NEWS_TICK", "NEWS_STRATEGY"')
    assert idx >= 0
    block = src[idx:idx + 1200]
    assert "GBPUSD_BB_BOUNCE_L" in block
    assert "GBPUSD_BB_BOUNCE_S" in block


def test_autobot_dispatch_block_present():
    src = open("/opt/tradingbot/autobot.py").read()
    assert "from gbpusd_bb_bounce import" in src
    assert "GBPUSD_BB_BOUNCE" in src


def test_env_disables_raw_reversal_enables_bb_bounce():
    env = open("/opt/tradingbot/.env").read()
    assert "GBPUSD_RAW_REVERSAL_ENABLED=0" in env
    assert "GBPUSD_BB_BOUNCE_ENABLED=1" in env
