"""Smoke tests: every playbook can fire a BUY or SELL signal with crafted inputs."""

import os, sys
os.environ["SWEEP_WINDOWS_LONDON"] = "00:00-23:59"  # always in window

import pandas as pd

import strategy_logic as sl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BB_U = 1.3400
BB_L = 1.3300
BB_M = 1.3350
EMA8 = 1.3360
EMA13 = 1.3355
EMA21 = 1.3350

def _ind(bb_u=BB_U, bb_l=BB_L, bb_m=BB_M, ema8=EMA8, ema13=EMA13, ema21=EMA21):
    return {
        "BB_UPPER_20_2": bb_u, "BB_LOWER_20_2": bb_l, "BB_MID_20_2": bb_m,
        "BB_UPPER": bb_u, "BB_LOWER": bb_l, "BB_MID": bb_m,
        "EMA_8": ema8, "EMA_13": ema13, "EMA_21": ema21,
    }

def _candle(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "timestamp": pd.Timestamp.utcnow().timestamp()}

def _rc_entry(o, h, l, c, ind=None):
    return {"candle": _candle(o, h, l, c), "indicators": ind or _ind()}

def _base_snapshot(candle, prev_candle, prev2_candle, indicators=None, prev_indicators=None, prev2_indicators=None, recent_closed=None):
    return {
        "candle": candle,
        "indicators": indicators or _ind(),
        "prev_candle": prev_candle,
        "prev_indicators": prev_indicators or _ind(),
        "prev2_candle": prev2_candle,
        "prev2_indicators": prev2_indicators or _ind(),
        "recent_closed": recent_closed or [],
    }


# ---------------------------------------------------------------------------
# 1. Sweep Pattern 1 — BB pierce + reversal candle → BUY
# ---------------------------------------------------------------------------
def test_sweep_pattern1_buy():
    """Pierce below lower BB + bullish reversal candle → BUY."""
    # Candle that pierced below BB_L
    pierce_candle = _rc_entry(1.3305, 1.3310, 1.3295, 1.3308)  # low 1.3295 < BB_L 1.3300
    # Reversal candle: bullish, close > bb_lower, body >= 50%
    rev_candle = _rc_entry(1.3302, 1.3315, 1.3300, 1.3314)     # bullish, close > BB_L
    # Current open candle (ignored for signal)
    cur_candle = _rc_entry(1.3314, 1.3316, 1.3312, 1.3315)

    rc = [pierce_candle, rev_candle, cur_candle]
    snap = _base_snapshot(
        candle=cur_candle["candle"], prev_candle=rev_candle["candle"], prev2_candle=pierce_candle["candle"],
        recent_closed=rc,
    )
    dec = sl._edge_rejection_engine(
        symbol="GBPUSD", epic="IX.D.POUND.DAILY.IP", mid_price=1.3315,
        snapshot_5m=snap, london_dt=pd.Timestamp("2026-03-20 10:00", tz="Europe/London"),
    )
    assert dec.signal == "BUY", f"Expected BUY, got {dec.signal} reason={dec.reason}"
    assert "pierce" in dec.reason, f"Expected pierce reason, got {dec.reason}"
    print(f"  PASS Pattern 1 BUY: reason={dec.reason}")


# ---------------------------------------------------------------------------
# 2. Sweep Pattern 1 — BB pierce + reversal candle → SELL
# ---------------------------------------------------------------------------
def test_sweep_pattern1_sell():
    """Pierce above upper BB + bearish reversal candle → SELL."""
    pierce_candle = _rc_entry(1.3395, 1.3405, 1.3390, 1.3398)  # high 1.3405 > BB_U 1.3400
    rev_candle = _rc_entry(1.3399, 1.3401, 1.3385, 1.3387)     # bearish, close < BB_U
    cur_candle = _rc_entry(1.3387, 1.3390, 1.3385, 1.3388)

    rc = [pierce_candle, rev_candle, cur_candle]
    snap = _base_snapshot(
        candle=cur_candle["candle"], prev_candle=rev_candle["candle"], prev2_candle=pierce_candle["candle"],
        recent_closed=rc,
    )
    dec = sl._edge_rejection_engine(
        symbol="GBPUSD", epic="IX.D.POUND.DAILY.IP", mid_price=1.3388,
        snapshot_5m=snap, london_dt=pd.Timestamp("2026-03-20 10:00", tz="Europe/London"),
    )
    assert dec.signal == "SELL", f"Expected SELL, got {dec.signal} reason={dec.reason}"
    assert "pierce" in dec.reason, f"Expected pierce reason, got {dec.reason}"
    print(f"  PASS Pattern 1 SELL: reason={dec.reason}")


# ---------------------------------------------------------------------------
# 3. Sweep Pattern 2 — Curve top → SELL
# ---------------------------------------------------------------------------
def test_sweep_pattern2_curve_top_sell():
    """3+ candles hug upper BB + bearish reversal that closes below prior low → SELL."""
    pip = 1.0  # GBPUSD pip_size
    hug_buffer = 8.0 * pip  # 8 pips

    # 4 candles hugging upper BB (high within 8 pips of BB_U)
    hug_ind = _ind()
    hug1 = _rc_entry(1.3392, 1.3398, 1.3390, 1.3395, hug_ind)  # high=1.3398, BB_U=1.3400, diff=2 pip
    hug2 = _rc_entry(1.3393, 1.3397, 1.3391, 1.3394, hug_ind)
    hug3 = _rc_entry(1.3394, 1.3399, 1.3392, 1.3396, hug_ind)
    hug4 = _rc_entry(1.3395, 1.3398, 1.3393, 1.3395, hug_ind)  # prior candle (rc_all[-3])

    # Reversal candle (rc_all[-2]): bearish, body >= 50%, close < prior low, close < BB_U
    # Prior candle low = 1.3393, so close must be < 1.3393
    rev_candle = _rc_entry(1.3396, 1.3397, 1.3385, 1.3386, hug_ind)  # body=10, range=12, 83%

    # Current open candle (rc_all[-1])
    cur_candle = _rc_entry(1.3386, 1.3388, 1.3384, 1.3387, hug_ind)

    rc = [hug1, hug2, hug3, hug4, rev_candle, cur_candle]
    snap = _base_snapshot(
        candle=cur_candle["candle"], prev_candle=rev_candle["candle"], prev2_candle=hug4["candle"],
        recent_closed=rc,
    )
    dec = sl._edge_rejection_engine(
        symbol="GBPUSD", epic="IX.D.POUND.DAILY.IP", mid_price=1.3387,
        snapshot_5m=snap, london_dt=pd.Timestamp("2026-03-20 10:00", tz="Europe/London"),
    )
    assert dec.signal == "SELL", f"Expected SELL, got {dec.signal} reason={dec.reason} debug={dec.debug}"
    assert dec.reason == "sweep_curve_top_sell", f"Expected sweep_curve_top_sell, got {dec.reason}"
    print(f"  PASS Pattern 2 Curve Top SELL: reason={dec.reason}")


# ---------------------------------------------------------------------------
# 4. Sweep Pattern 2 — Curve bottom → BUY
# ---------------------------------------------------------------------------
def test_sweep_pattern2_curve_bottom_buy():
    """3+ candles hug lower BB + bullish reversal that closes above prior high → BUY."""
    hug_ind = _ind()
    # 4 candles hugging lower BB (low within 8 pips of BB_L=1.3300)
    hug1 = _rc_entry(1.3308, 1.3310, 1.3302, 1.3305, hug_ind)
    hug2 = _rc_entry(1.3307, 1.3309, 1.3303, 1.3306, hug_ind)
    hug3 = _rc_entry(1.3306, 1.3308, 1.3301, 1.3304, hug_ind)
    hug4 = _rc_entry(1.3305, 1.3307, 1.3302, 1.3304, hug_ind)  # prior candle, high=1.3307

    # Reversal: bullish, close > prior high (1.3307), close > BB_L, body >= 50%
    rev_candle = _rc_entry(1.3304, 1.3315, 1.3303, 1.3314, hug_ind)  # body=10, range=12

    cur_candle = _rc_entry(1.3314, 1.3316, 1.3312, 1.3315, hug_ind)

    rc = [hug1, hug2, hug3, hug4, rev_candle, cur_candle]
    snap = _base_snapshot(
        candle=cur_candle["candle"], prev_candle=rev_candle["candle"], prev2_candle=hug4["candle"],
        recent_closed=rc,
    )
    dec = sl._edge_rejection_engine(
        symbol="GBPUSD", epic="IX.D.POUND.DAILY.IP", mid_price=1.3315,
        snapshot_5m=snap, london_dt=pd.Timestamp("2026-03-20 10:00", tz="Europe/London"),
    )
    assert dec.signal == "BUY", f"Expected BUY, got {dec.signal} reason={dec.reason} debug={dec.debug}"
    assert dec.reason == "sweep_curve_bottom_buy", f"Expected sweep_curve_bottom_buy, got {dec.reason}"
    print(f"  PASS Pattern 2 Curve Bottom BUY: reason={dec.reason}")


# ---------------------------------------------------------------------------
# 5. EMA Pullback / Trend Follow — BUY
# ---------------------------------------------------------------------------
def test_trend_follow_buy():
    """EMA stack bullish + prev candle touches EMA8 + current confirms → BUY."""
    ema8, ema13, ema21 = 1.3360, 1.3355, 1.3350  # bullish stack

    prev_ind = _ind(ema8=ema8, ema13=ema13, ema21=ema21)
    cur_ind = _ind(ema8=ema8, ema13=ema13, ema21=ema21)

    # Previous candle: low touches EMA8 (1.3360)
    prev_candle = _candle(1.3365, 1.3370, 1.3358, 1.3362)  # low 1.3358 <= ema8
    # Current candle: close > open, close > ema8, body >= 50%
    cur_candle = _candle(1.3362, 1.3380, 1.3360, 1.3378)   # body=16, range=20, 80%
    prev2_candle = _candle(1.3360, 1.3366, 1.3355, 1.3363)

    snap = _base_snapshot(
        candle=cur_candle, prev_candle=prev_candle, prev2_candle=prev2_candle,
        indicators=cur_ind, prev_indicators=prev_ind,
    )
    dec = sl._ema_pullback_playbook("GBPUSD", "IX.D.POUND.DAILY.IP", 1.3378, snap, "UP", 1.0)
    assert dec.signal == "BUY", f"Expected BUY, got {dec.signal} reason={dec.reason} debug={dec.debug}"
    assert "ema_pullback_buy" in dec.reason, f"Expected ema_pullback_buy, got {dec.reason}"
    print(f"  PASS Trend Follow BUY: reason={dec.reason}")


# ---------------------------------------------------------------------------
# 6. EMA Pullback / Trend Follow — SELL
# ---------------------------------------------------------------------------
def test_trend_follow_sell():
    """EMA stack bearish + prev candle touches EMA8 + current confirms → SELL."""
    ema8, ema13, ema21 = 1.3340, 1.3345, 1.3350  # bearish stack

    prev_ind = _ind(ema8=ema8, ema13=ema13, ema21=ema21)
    cur_ind = _ind(ema8=ema8, ema13=ema13, ema21=ema21)

    # Previous candle: high touches EMA8 (1.3340)
    prev_candle = _candle(1.3335, 1.3342, 1.3330, 1.3336)  # high 1.3342 >= ema8
    # Current candle: close < open, close < ema8, body >= 50%
    cur_candle = _candle(1.3338, 1.3340, 1.3320, 1.3322)   # body=16, range=20
    prev2_candle = _candle(1.3340, 1.3345, 1.3335, 1.3338)

    snap = _base_snapshot(
        candle=cur_candle, prev_candle=prev_candle, prev2_candle=prev2_candle,
        indicators=cur_ind, prev_indicators=prev_ind,
    )
    dec = sl._ema_pullback_playbook("GBPUSD", "IX.D.POUND.DAILY.IP", 1.3322, snap, "DOWN", 1.0)
    assert dec.signal == "SELL", f"Expected SELL, got {dec.signal} reason={dec.reason} debug={dec.debug}"
    assert "ema_pullback_sell" in dec.reason, f"Expected ema_pullback_sell, got {dec.reason}"
    print(f"  PASS Trend Follow SELL: reason={dec.reason}")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        ("Sweep Pattern 1 BUY",         test_sweep_pattern1_buy),
        ("Sweep Pattern 1 SELL",         test_sweep_pattern1_sell),
        ("Sweep Pattern 2 Curve SELL",   test_sweep_pattern2_curve_top_sell),
        ("Sweep Pattern 2 Curve BUY",    test_sweep_pattern2_curve_bottom_buy),
        ("Trend Follow BUY",             test_trend_follow_buy),
        ("Trend Follow SELL",            test_trend_follow_sell),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL {name}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed:
        sys.exit(1)
    else:
        print("All playbooks fire correctly!")
