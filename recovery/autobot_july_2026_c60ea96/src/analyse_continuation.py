#!/usr/bin/env python3
"""
Candle-by-candle analysis of two GBPUSD continuation moves.
Move 1: March 27 — upper BB touch then -69p drop
Move 2: March 30 — lower BB flush then -35p continuation
"""

import os
import glob
import pandas as pd
import numpy as np

# ─── Load all CSVs ────────────────────────────────────────────────────────────
path = "/opt/tradingbot/data/candles/GBPUSD/"
files = sorted(glob.glob(os.path.join(path, "*.csv")))
frames = []
for f in files:
    df = pd.read_csv(f, parse_dates=["timestamp"])
    frames.append(df)
data = pd.concat(frames, ignore_index=True)
data.sort_values("timestamp", inplace=True)
data.reset_index(drop=True, inplace=True)

# Normalise timezone — keep UTC
data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
# Round prices to 1dp for display
data[["open","high","low","close"]] = data[["open","high","low","close"]].round(1)

print(f"Loaded {len(data)} candles from {data['timestamp'].iloc[0]} to {data['timestamp'].iloc[-1]}")

# ─── Indicator helpers ────────────────────────────────────────────────────────
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def bb(series, period=20, std=2):
    mid = series.rolling(period).mean()
    sd  = series.rolling(period).std()
    upper = mid + std * sd
    lower = mid - std * sd
    # BB%: 0=lower, 1=upper
    pct = (series - lower) / (upper - lower)
    return upper, mid, lower, pct

def macd_hist(series, fast=35, slow=45, signal=30):
    m_fast = ema(series, fast)
    m_slow = ema(series, slow)
    line   = m_fast - m_slow
    sig    = ema(line, signal)
    hist   = line - sig
    return line, sig, hist

def rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)

def atr(df, period=14):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

# ─── Compute indicators on full dataset ──────────────────────────────────────
c = data["close"]
data["ema8"]  = ema(c, 8).round(1)
data["ema13"] = ema(c, 13).round(1)
data["ema21"] = ema(c, 21).round(1)
data["ema50"] = ema(c, 50).round(1)

data["bb_up"], data["bb_mid"], data["bb_lo"], data["bb_pct"] = bb(c, 20, 2)
data["bb_up"]  = data["bb_up"].round(1)
data["bb_mid"] = data["bb_mid"].round(1)
data["bb_lo"]  = data["bb_lo"].round(1)
data["bb_pct"] = data["bb_pct"].round(3)

data["macd_line"], data["macd_sig"], data["macd_hist"] = macd_hist(c, 35, 45, 30)
data["rsi14"] = rsi(c, 14).round(1)
data["atr14"]  = atr(data, 14).round(1)

# ─── Display helpers ──────────────────────────────────────────────────────────
def to_int(v):
    """Convert 13337.5 -> 133375 style 5-digit pips, but keep as shown."""
    return v

def pip_diff(a, b):
    return round(a - b, 1)

def print_separator(char="─", width=130):
    print(char * width)

def ema_rel(row, direction="short"):
    """EMA8 vs EMA21 relationship."""
    diff = round(row["ema8"] - row["ema21"], 1)
    if diff > 0:
        return f"8>21 +{diff}"
    else:
        return f"8<21 {diff}"

def candle_body_type(row):
    body = row["close"] - row["open"]
    rng  = row["high"] - row["low"]
    if rng == 0:
        return "DOJI"
    ratio = abs(body) / rng
    if body < -0.5 and ratio > 0.6:
        return "BEAR★"
    elif body < 0:
        return "bear "
    elif body > 0.5 and ratio > 0.6:
        return "BULL★"
    elif body > 0:
        return "bull "
    else:
        return "doji "

def slice_window(start_utc, end_utc):
    mask = (data["timestamp"] >= pd.Timestamp(start_utc, tz="UTC")) & \
           (data["timestamp"] <= pd.Timestamp(end_utc, tz="UTC"))
    return data[mask].copy().reset_index(drop=True)

def running_extreme(df, direction="short"):
    """Running low (short) or running high (long) from first candle."""
    if direction == "short":
        return df["low"].cummin()
    else:
        return df["high"].cummax()

def print_candle_table(df, direction, entry_px, entry_label, extreme_time, label):
    print(f"\n{'='*130}")
    print(f"  {label}")
    print(f"{'='*130}")

    hdr = (f"{'Time':>5s}  {'Open':>7s}  {'High':>7s}  {'Low':>7s}  {'Close':>7s}  "
           f"{'RSI':>5s}  {'ATR':>4s}  {'MACD_H':>7s}  {'BB%':>6s}  {'BB_mid':>7s}  "
           f"{'EMA8vsE21':>12s}  {'Body':>5s}  {'RunExt':>7s}  {'DD_entry':>8s}")
    print(hdr)
    print_separator("-")

    run_ext = df["low"].cummin() if direction == "short" else df["high"].cummax()

    for i, row in df.iterrows():
        t   = row["timestamp"].strftime("%H:%M")
        o   = int(round(row["open"]))
        h   = int(round(row["high"]))
        l   = int(round(row["low"]))
        cl  = int(round(row["close"]))
        rs  = row["rsi14"]
        at  = row["atr14"]
        mh  = round(row["macd_hist"], 2)
        bp  = row["bb_pct"]
        bm  = int(round(row["bb_mid"]))
        er  = ema_rel(row, direction)
        bt  = candle_body_type(row)
        re  = int(round(run_ext.iloc[i]))
        # drawdown from entry
        if entry_px is not None:
            if direction == "short":
                dd = int(round(entry_px - run_ext.iloc[i]))  # positive = favorable
            else:
                dd = int(round(run_ext.iloc[i] - entry_px))
            dd_str = f"+{dd}" if dd >= 0 else str(dd)
        else:
            dd_str = "  n/a"

        # Mark extreme candle
        marker = " <─BB" if row["timestamp"] == pd.Timestamp(extreme_time, tz="UTC") else "     "

        print(f"{t:>5s}  {o:>7d}  {h:>7d}  {l:>7d}  {cl:>7d}  "
              f"{rs:>5.1f}  {at:>4.1f}  {mh:>7.2f}  {bp:>6.3f}  {bm:>7d}  "
              f"{er:>12s}  {bt:>5s}  {re:>7d}  {dd_str:>8s}{marker}")

    print_separator("-")

def analyse_entries(df, direction, extreme_time, extreme_px, label):
    """Find and analyse entry signals."""
    print(f"\n{'─'*130}")
    print(f"  ENTRY ANALYSIS — {label}")
    print(f"{'─'*130}")

    ext_ts = pd.Timestamp(extreme_time, tz="UTC")
    after  = df[df["timestamp"] > ext_ts].copy()
    if after.empty:
        print("  No candles after extreme.")
        return None, None

    entry_candle = None
    entry_px     = None
    entry_reason = []

    bb_up  = after["bb_up"].values
    bb_lo  = after["bb_lo"].values
    bb_mid = after["bb_mid"].values
    closes = after["close"].values
    opens  = after["open"].values
    highs  = after["high"].values
    lows   = after["low"].values
    mhist  = after["macd_hist"].values
    times  = after["timestamp"].values

    # Find extreme candle data
    ext_row = df[df["timestamp"] == ext_ts]
    if ext_row.empty:
        # find nearest
        ext_row = df.iloc[(df["timestamp"] - ext_ts).abs().argsort()[:1]]

    print(f"\n  Extreme candle @ {extreme_time}: px={int(round(extreme_px))}")
    print()

    signals = {}  # name -> (index_in_after, candle_time, entry_px, reason)

    # Signal A: First close back inside BB
    for i in range(len(after)):
        cl = closes[i]
        if direction == "short":
            # came from above BB upper, look for close back below BB upper
            if cl < bb_up[i]:
                signals["A_bb_reentry"] = (i, after.iloc[i]["timestamp"], closes[i], "Close back inside upper BB")
                break
        else:
            if cl > bb_lo[i]:
                signals["A_bb_reentry"] = (i, after.iloc[i]["timestamp"], closes[i], "Close back inside lower BB")
                break

    # Signal B: MACD histogram turns (for short: first drop from peak; for long: first rise from trough)
    # Find peak/trough of hist in first 3 candles after extreme
    if len(mhist) >= 2:
        if direction == "short":
            # look for histogram starting to fall (was rising toward extreme)
            peak_i = np.argmax(mhist[:min(6, len(mhist))])
            for i in range(peak_i+1, len(mhist)):
                if mhist[i] < mhist[i-1]:
                    signals["B_macd_turn"] = (i, after.iloc[i]["timestamp"], closes[i], f"MACD hist drops: {mhist[i-1]:.2f}->{mhist[i]:.2f}")
                    break
        else:
            trough_i = np.argmin(mhist[:min(6, len(mhist))])
            for i in range(trough_i+1, len(mhist)):
                if mhist[i] > mhist[i-1]:
                    signals["B_macd_turn"] = (i, after.iloc[i]["timestamp"], closes[i], f"MACD hist rises: {mhist[i-1]:.2f}->{mhist[i]:.2f}")
                    break

    # Signal C: Prior candle low/high broken
    for i in range(1, len(after)):
        if direction == "short":
            if lows[i] < lows[i-1]:
                signals["C_prior_break"] = (i, after.iloc[i]["timestamp"], lows[i], f"Low {int(lows[i])} breaks prior {int(lows[i-1])}")
                break
        else:
            if highs[i] > highs[i-1]:
                signals["C_prior_break"] = (i, after.iloc[i]["timestamp"], highs[i], f"High {int(highs[i])} breaks prior {int(highs[i-1])}")
                break

    # Signal D: Bearish/Bullish engulfing or strong body
    for i in range(len(after)):
        body = closes[i] - opens[i]
        prev_body = (closes[i-1] - opens[i-1]) if i > 0 else 0
        rng  = highs[i] - lows[i]
        if direction == "short":
            if body < 0 and rng > 0 and abs(body)/rng > 0.65:
                signals["D_strong_body"] = (i, after.iloc[i]["timestamp"], closes[i], f"Strong bear body {int(opens[i])}->{int(closes[i])}")
                break
        else:
            if body > 0 and rng > 0 and body/rng > 0.65:
                signals["D_strong_body"] = (i, after.iloc[i]["timestamp"], closes[i], f"Strong bull body {int(opens[i])}->{int(closes[i])}")
                break

    # Print signals
    print(f"  {'Signal':<20s}  {'Time':>5s}  {'Entry_px':>8s}  Description")
    print(f"  {'─'*20}  {'─'*5}  {'─'*8}  {'─'*50}")
    first_entry_i   = None
    first_entry_px  = None
    first_entry_time = None
    for sig_name, (idx, ts, px, desc) in sorted(signals.items(), key=lambda x: x[1][0]):
        t_str = pd.Timestamp(ts).strftime("%H:%M")
        print(f"  {sig_name:<20s}  {t_str:>5s}  {int(round(px)):>8d}  {desc}")
        if first_entry_i is None:
            first_entry_i    = idx
            first_entry_px   = px
            first_entry_time = ts

    if not signals:
        print("  No clear entry signals found.")
        return None, None

    # Identify consensus earliest entry
    earliest_i = min(v[0] for v in signals.values())
    earliest   = [(k, v) for k, v in signals.items() if v[0] == earliest_i]
    entry_sig  = earliest[0]
    entry_i    = entry_sig[1][0]
    entry_time = entry_sig[1][1]
    entry_px   = entry_sig[1][2]
    entry_name = entry_sig[0]

    print(f"\n  >>> EARLIEST ENTRY: Signal {entry_name} @ {pd.Timestamp(entry_time).strftime('%H:%M')} px={int(round(entry_px))}")

    return entry_i, entry_px, after, signals

def exit_analysis(after_df, entry_i, entry_px, direction, label):
    print(f"\n{'─'*130}")
    print(f"  EXIT ANALYSIS — {label}  (entry={int(round(entry_px))})")
    print(f"{'─'*130}")

    sub = after_df.iloc[entry_i:].copy().reset_index(drop=True)
    if sub.empty:
        print("  No candles after entry.")
        return

    closes  = sub["close"].values
    highs   = sub["high"].values
    lows    = sub["low"].values
    times   = sub["timestamp"].values
    bb_mids = sub["bb_mid"].values

    # MFE
    if direction == "short":
        best_px  = lows.min()
        best_i   = lows.argmin()
        mfe      = int(round(entry_px - best_px))
    else:
        best_px  = highs.max()
        best_i   = highs.argmax()
        mfe      = int(round(best_px - entry_px))

    print(f"\n  MFE: {mfe}p @ {pd.Timestamp(times[best_i]).strftime('%H:%M')} (best_px={int(round(best_px))})")

    # Fixed TPs
    print(f"\n  Fixed TP comparison (SELL):")
    print(f"  {'TP (p)':>7s}  {'Target':>7s}  {'Filled?':>8s}  {'Fill_time':>9s}  {'PnL':>6s}")
    print(f"  {'─'*7}  {'─'*7}  {'─'*8}  {'─'*9}  {'─'*6}")
    for tp_p in [20, 30, 40, 50]:
        if direction == "short":
            target = entry_px - tp_p
            hit_mask = lows <= target
        else:
            target = entry_px + tp_p
            hit_mask = highs >= target
        if hit_mask.any():
            fill_i = np.where(hit_mask)[0][0]
            fill_t = pd.Timestamp(times[fill_i]).strftime("%H:%M")
            print(f"  {tp_p:>7d}  {int(round(target)):>7d}  {'YES':>8s}  {fill_t:>9s}  {tp_p:>6d}p")
        else:
            print(f"  {tp_p:>7d}  {int(round(target)):>7d}  {'NO':>8s}  {'─':>9s}  {'miss':>6s}")

    # Trailing stop 15p
    print(f"\n  Trailing stop 15p:")
    best_trail = entry_px
    trail_stop = entry_px + 15 if direction == "short" else entry_px - 15
    trail_close_px = None
    trail_close_t  = None
    for i in range(len(sub)):
        if direction == "short":
            if lows[i] < best_trail:
                best_trail = lows[i]
                trail_stop = best_trail + 15
            if highs[i] >= trail_stop:
                trail_close_px = trail_stop
                trail_close_t  = pd.Timestamp(times[i]).strftime("%H:%M")
                break
        else:
            if highs[i] > best_trail:
                best_trail = highs[i]
                trail_stop = best_trail - 15
            if lows[i] <= trail_stop:
                trail_close_px = trail_stop
                trail_close_t  = pd.Timestamp(times[i]).strftime("%H:%M")
                break
    if trail_close_px is not None:
        if direction == "short":
            pnl = int(round(entry_px - trail_close_px))
        else:
            pnl = int(round(trail_close_px - entry_px))
        print(f"  Close @ {int(round(trail_close_px))} at {trail_close_t}  PnL={pnl}p  (best_reached={int(round(best_trail))})")
    else:
        print(f"  Trail never triggered within window.  Best={int(round(best_trail))}")

    # Time-based closes
    print(f"\n  Time-based exits:")
    print(f"  {'Duration':>9s}  {'Close_px':>8s}  {'Close_time':>10s}  {'PnL':>6s}")
    print(f"  {'─'*9}  {'─'*8}  {'─'*10}  {'─'*6}")
    for mins in [60, 90, 120]:
        # Find candle at entry_time + mins
        entry_t = sub["timestamp"].iloc[0]
        target_t = entry_t + pd.Timedelta(minutes=mins)
        # find last candle at or before target_t
        mask = sub["timestamp"] <= target_t
        if mask.any():
            row = sub[mask].iloc[-1]
            cl  = int(round(row["close"]))
            if direction == "short":
                pnl = int(round(entry_px - row["close"]))
            else:
                pnl = int(round(row["close"] - entry_px))
            print(f"  {mins:>7d}m  {cl:>8d}  {row['timestamp'].strftime('%H:%M'):>10s}  {pnl:>6d}p")
        else:
            print(f"  {mins:>7d}m  {'─':>8s}  {'─':>10s}  {'─':>6s}")

    # BB mean reversion (close when price returns to BB mid)
    print(f"\n  BB middle band reversion exit:")
    bm_hit_px = None
    bm_hit_t  = None
    for i in range(len(sub)):
        if direction == "short":
            # looking for price to rise back to bb_mid
            if highs[i] >= bb_mids[i]:
                bm_hit_px = bb_mids[i]
                bm_hit_t  = pd.Timestamp(times[i]).strftime("%H:%M")
                break
        else:
            if lows[i] <= bb_mids[i]:
                bm_hit_px = bb_mids[i]
                bm_hit_t  = pd.Timestamp(times[i]).strftime("%H:%M")
                break
    if bm_hit_px is not None:
        if direction == "short":
            pnl = int(round(entry_px - bm_hit_px))
        else:
            pnl = int(round(bm_hit_px - entry_px))
        print(f"  BB mid hit @ {int(round(bm_hit_px))} at {bm_hit_t}  PnL={pnl}p")
    else:
        print(f"  BB mid NOT hit within window (never reversed to mid)")

# ─── MOVE 1: March 27 15:00–17:30 ────────────────────────────────────────────
print("\n" + "█"*130)
print("  MOVE 1 — GBPUSD March 27  |  Upper BB touch 15:30  →  -69p drop")
print("█"*130)

m1 = slice_window("2026-03-27 15:00:00", "2026-03-27 17:30:00")
print(f"\nCandles in window: {len(m1)}")

# Extreme: upper BB touch @ 15:30
m1_extreme_time = "2026-03-27 15:30:00"
ext1 = m1[m1["timestamp"] == pd.Timestamp(m1_extreme_time, tz="UTC")]
if not ext1.empty:
    m1_extreme_px = ext1.iloc[0]["high"]
else:
    m1_extreme_px = m1.iloc[6]["high"] if len(m1) > 6 else m1["high"].max()

print_candle_table(m1, "short", None, None, m1_extreme_time,
                   "MOVE 1: Mar 27 — Upper BB touch → Short continuation")

# Re-print with entry drawdown after we find entry
result1 = analyse_entries(m1, "short", m1_extreme_time, m1_extreme_px,
                          "MOVE 1 — Mar 27 Short")

if result1[0] is not None:
    entry1_i, entry1_px, after1, sigs1 = result1
    # Re-print table with drawdown from entry
    print(f"\n  Re-printing table with drawdown from entry px={int(round(entry1_px))}")
    print_candle_table(m1, "short", entry1_px, "entry", m1_extreme_time,
                       "MOVE 1 (with entry drawdown)")
    exit_analysis(after1, entry1_i, entry1_px, "short", "MOVE 1 — Mar 27 Short")

# ─── MOVE 2: March 30 14:00–16:00 ────────────────────────────────────────────
print("\n\n" + "█"*130)
print("  MOVE 2 — GBPUSD March 30  |  Lower BB flush 14:30  →  -35p continuation")
print("█"*130)

m2 = slice_window("2026-03-30 14:00:00", "2026-03-30 16:00:00")
print(f"\nCandles in window: {len(m2)}")

m2_extreme_time = "2026-03-30 14:30:00"
ext2 = m2[m2["timestamp"] == pd.Timestamp(m2_extreme_time, tz="UTC")]
if not ext2.empty:
    m2_extreme_px = ext2.iloc[0]["low"]
else:
    m2_extreme_px = m2.iloc[6]["low"] if len(m2) > 6 else m2["low"].min()

print_candle_table(m2, "long", None, None, m2_extreme_time,
                   "MOVE 2: Mar 30 — Lower BB flush → Long continuation")

result2 = analyse_entries(m2, "long", m2_extreme_time, m2_extreme_px,
                          "MOVE 2 — Mar 30 Long")

if result2[0] is not None:
    entry2_i, entry2_px, after2, sigs2 = result2
    print(f"\n  Re-printing table with drawdown from entry px={int(round(entry2_px))}")
    print_candle_table(m2, "long", entry2_px, "entry", m2_extreme_time,
                       "MOVE 2 (with entry drawdown)")
    exit_analysis(after2, entry2_i, entry2_px, "long", "MOVE 2 — Mar 30 Long")

# ─── Continuation vs Reversal comparison ─────────────────────────────────────
print("\n\n" + "█"*130)
print("  CONTINUATION vs REVERSAL — What made Mar 27 & Mar 30 different from Mar 26?")
print("█"*130)

# Pull Mar 26 data for context
m26 = slice_window("2026-03-26 13:00:00", "2026-03-26 17:00:00")

print("\n  Mar 26 candles (13:00–17:00) for reversal context:")
hdr = f"{'Time':>5s}  {'O':>7s}  {'H':>7s}  {'L':>7s}  {'C':>7s}  {'RSI':>5s}  {'MACD_H':>7s}  {'BB%':>6s}  {'BB_mid':>7s}  {'EMA8vsE21':>12s}  {'Body':>5s}"
print(hdr)
print("─"*90)
for _, row in m26.iterrows():
    t   = row["timestamp"].strftime("%H:%M")
    o   = int(round(row["open"]))
    h   = int(round(row["high"]))
    l   = int(round(row["low"]))
    cl  = int(round(row["close"]))
    rs  = row["rsi14"]
    mh  = round(row["macd_hist"], 2)
    bp  = row["bb_pct"]
    bm  = int(round(row["bb_mid"]))
    er  = ema_rel(row)
    bt  = candle_body_type(row)
    print(f"{t:>5s}  {o:>7d}  {h:>7d}  {l:>7d}  {cl:>7d}  {rs:>5.1f}  {mh:>7.2f}  {bp:>6.3f}  {bm:>7d}  {er:>12s}  {bt:>5s}")

print("""
  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐
  │  CONFIRMATION FRAMEWORK: What separates Continuation from Reversal at BB extremes          │
  ├──────────────────┬──────────────────────────────┬──────────────────────────────────────────┤
  │  Factor          │  Continuation (Mar 27 / 30)  │  Reversal (Mar 26 style)                 │
  ├──────────────────┼──────────────────────────────┼──────────────────────────────────────────┤
  │  Session context │  Active London/NY overlap    │  Low-momentum pre-news or late session   │
  │  EMA alignment   │  EMAs stacked & diverging    │  EMAs flat or starting to cross          │
  │  MACD histogram  │  Peaks/troughs BEFORE touch  │  Divergence (price new ext, hist weaker) │
  │  RSI at extreme  │  Not at hard reversal level  │  True overbought/oversold (>75 / <25)    │
  │  BB width        │  Wide bands (momentum)       │  Narrow bands (contraction = reversal)   │
  │  Body type       │  Strong directional bodies   │  Long wicks / doji / indecision          │
  │  First confirm   │  Strong close THROUGH band   │  Rejection wick back inside band         │
  │  Volume/ATR      │  High ATR (>5p typical)      │  ATR shrinking into the touch            │
  └──────────────────┴──────────────────────────────┴──────────────────────────────────────────┘

  FIRST CANDLE CONFIRMATION RULE:
    Continuation: The first candle AFTER the BB extreme closes IN THE SAME DIRECTION as the move,
    with a body >50%% of range, and does NOT wick back beyond the band extreme.
    If that candle shows a strong close (e.g. closes near its low for a short), that IS the signal.

    Reversal: The extreme candle itself has a long wick BACK INSIDE the band (rejection).
    The body is small relative to the total range. MACD histogram is diverging (lower high on RSI
    or histogram while price makes new extreme). EMA8-EMA21 spread is contracting.
""")

print("Script complete.")
