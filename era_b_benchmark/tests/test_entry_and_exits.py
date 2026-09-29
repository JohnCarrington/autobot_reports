"""Unit tests for era_b_bench.entry and era_b_bench.exits.

Run: python3 -m pytest tests/ -v
Or:  python3 tests/test_entry_and_exits.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Package path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from era_b_bench import config
from era_b_bench.candles import Bar
from era_b_bench.entry import (
    EraBEntryDetector, Signal, bb_20_2, detect_pierce_setup, is_rejection,
)
from era_b_bench.exits import simulate as run_exits


def _bar(hh, mm, o, h, l, c) -> Bar:
    ts = datetime(2026, 5, 29, hh, mm, tzinfo=timezone.utc)
    return Bar(ts=ts, open=o, high=h, low=l, close=c)


# ─── entry: unit checks ─────────────────────────────────────────────────

def test_bb_20_2_needs_20_samples():
    assert bb_20_2([1.0] * 19) is None
    r = bb_20_2([1.0] * 20)
    assert r is not None
    bbl, bbm, bbu = r
    assert bbl == bbm == bbu == 1.0

def test_bb_20_2_matches_hand_calc():
    closes = [10.0] * 19 + [12.0]
    r = bb_20_2(closes)
    assert r is not None
    _bbl, bbm, _bbu = r
    assert round(bbm, 2) == 10.10   # (19 * 10 + 12) / 20 = 10.1

def test_pierce_setup_short_when_wick_pokes_above_bbu():
    prev = _bar(6, 55, 100.0, 103.0, 99.0, 100.5)  # high 103, open 100
    # BBU at prev = 100.5, PIERCE_THRESH_PIPS = 2.0
    # short_pierce = 103 - 100.5 = 2.5 >= 2.0 → pierce
    # open (100) <= BBU (100.5) → passes
    assert detect_pierce_setup(prev, 98.0, 100.5, 2.0) == "SHORT"

def test_pierce_setup_rejects_open_above_bbu():
    prev = _bar(6, 55, 101.0, 103.0, 99.0, 100.5)  # open above BBU
    assert detect_pierce_setup(prev, 98.0, 100.5, 2.0) is None

def test_pierce_setup_below_threshold():
    prev = _bar(6, 55, 100.0, 101.0, 99.0, 100.5)   # only 0.5 above BBU
    assert detect_pierce_setup(prev, 98.0, 100.5, 2.0) is None
    # but with threshold 0.5 → SHORT
    assert detect_pierce_setup(prev, 98.0, 100.5, 0.5) == "SHORT"

def test_rejection_short_needs_body_and_close_inside():
    cur = _bar(7, 0, 100.0, 101.0, 98.0, 98.5)   # bearish body 1.5, close < open
    # BBU_current = 99.0, tolerance 1.0 → close (98.5) <= 99+1 → OK
    assert is_rejection(cur, "SHORT", 99.0, 90.0) is True

def test_rejection_short_fails_on_doji_body():
    cur = _bar(7, 0, 100.0, 101.0, 98.0, 99.0)   # body 1.0 < 1.5
    assert is_rejection(cur, "SHORT", 99.0, 90.0) is False

def test_rejection_short_fails_when_close_above_bbu_plus_tol():
    cur = _bar(7, 0, 100.0, 101.0, 98.0, 99.5)   # bearish, but close > BBU+tol
    # BBU=95, tol=1 → close 99.5 > 96 → fail
    assert is_rejection(cur, "SHORT", 95.0, 90.0) is False


# ─── exits: unit checks ─────────────────────────────────────────────────

def _make_signal(entry: float) -> Signal:
    ts = datetime(2026, 5, 29, 7, 5, tzinfo=timezone.utc)
    setup = _bar(6, 55, 100, 105, 99, 100)
    rejection = _bar(7, 0, 103, 104, 100, 100)
    return Signal(
        ts_utc=ts, direction="SELL", entry_price=entry,
        sl_pips=20.0, tp_pips=100.0,
        setup_bar=setup, rejection_bar=rejection, rejection_window_idx=1,
        bbu_setup=101.0, bbl_setup=99.0,
        bbu_current=101.0, bbl_current=99.0,
    )

def _mk(ofs_min, o, h, l, c) -> Bar:
    ts = datetime(2026, 5, 29, 7, 5, tzinfo=timezone.utc) + timedelta(minutes=ofs_min)
    return Bar(ts=ts, open=o, high=h, low=l, close=c)


def test_exits_sl_hit_first_bar():
    sig = _make_signal(entry=100.0)     # SL = 120, TP = 0, SO = 90
    downstream = [_mk(0, 100.0, 121.0, 99.5, 120.5)]
    r = run_exits(sig, downstream)
    assert r.final.reason == "SL_HIT"
    assert round(r.total_pips, 2) == -20.0

def test_exits_scale_out_then_be():
    sig = _make_signal(entry=100.0)     # SL=120, SO=90, BE=100
    downstream = [
        _mk(0, 100.0, 100.5, 89.5, 91.0),   # low 89.5 < SO=90 → scale-out; high 100.5 >= BE=100 → BE same bar
    ]
    r = run_exits(sig, downstream)
    assert r.scaled_out is True
    assert r.final.reason == "SCALE_OUT_BE"
    # partial: +10p on 0.5, runner 0.5 * 0 = 0 → total = 5.0
    assert round(r.total_pips, 2) == 5.0

def test_exits_scale_out_then_tp():
    sig = _make_signal(entry=100.0)     # SL=120, TP=0, SO=90, BE=100
    downstream = [
        _mk(0, 100.0, 100.1, 88.0, 89.0),   # scale-out at 90 (low=88<90); BE not hit (bar_high 100.1 >= BE=100!)
        # Actually 100.1 >= 100 → BE hit same bar as scale-out.
        # For a cleaner test:
    ]
    downstream = [
        _mk(0, 100.0, 99.9, 88.0, 89.0),    # scale-out; no BE (high < 100)
        _mk(5, 89.0, 89.5, -0.5, 0.0),      # low = -0.5 <= TP=0 → runner TP hit
    ]
    r = run_exits(sig, downstream)
    assert r.scaled_out is True
    assert r.final.reason == "SCALE_OUT_TP"
    # partial: +10p on 0.5 = +5p; runner: +100p on 0.5 = +50p → total = 55
    assert round(r.total_pips, 2) == 55.0

def test_exits_max_hold_no_scale():
    sig = _make_signal(entry=100.0)
    # 48 bars of drift, no SL/TP/scale-out, final close at 99.5 → +0.5p
    downstream = [_mk(i*5, 100.0, 100.5, 99.5, 99.5) for i in range(48)]
    r = run_exits(sig, downstream)
    assert r.final.reason == "REGIME_MAX_HOLD"
    assert round(r.total_pips, 2) == 0.5

def test_broker_submission_disabled():
    assert config.IG_SUBMISSION_ENABLED is False


# ─── run smoke ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    ns = {name: val for name, val in globals().items() if callable(val) and name.startswith("test_")}
    fail = 0
    for name, fn in ns.items():
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as exc:
            fail += 1
            print(f"  FAIL  {name} :: {exc}")
        except Exception as exc:
            fail += 1
            print(f"  ERR   {name} :: {type(exc).__name__}: {exc}")
    print(f"\n{len(ns) - fail}/{len(ns)} passed" + (f", {fail} failed" if fail else ""))
    sys.exit(1 if fail else 0)
