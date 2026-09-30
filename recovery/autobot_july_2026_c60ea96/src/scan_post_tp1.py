#!/usr/bin/env python3
"""
scan_post_tp1.py — For each V1/V3 sweep that hit TP1 in the 7-day replay,
trace what price did AFTER TP1 was reached.

Shows: did it reach TP2/TP3, max continuation beyond TP1, time to reversal.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv()

from briefing_liquidity import BriefingLiquidityStrategy

DATES = [
    "2026-03-23",
    "2026-03-24",
    "2026-03-25",
    "2026-03-26",
    "2026-03-27",
    "2026-03-30",
    "2026-03-31",
]
SYMBOL = "GBPUSD"
EPIC = "CS.D.GBPUSD.TODAY.IP"
PPP = 1.0
WARMUP = 60
COOLDOWN_MINS = 60
SESSION_START = 7
SESSION_END = 17

BRIEFING_SESSIONS = [
    (0, 0, "Asian"),
    (6, 30, "London"),
    (10, 45, "Mid-session"),
    (13, 0, "NY"),
]

# Monkey-patch datetime for simulated time
import briefing_liquidity as _bl_mod
_real_datetime = datetime

class _SimDatetime(datetime):
    _sim_now = None
    @classmethod
    def now(cls, tz=None):
        if cls._sim_now is not None and tz is not None:
            return cls._sim_now
        return _real_datetime.now(tz)

_bl_mod.datetime = _SimDatetime


def load_candles(date):
    path = Path(f"/opt/tradingbot/cache/test_candles_GBPUSD_{date}.json")
    if not path.exists():
        return pd.DataFrame()
    with open(path) as f:
        data = json.load(f)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def get_briefing_for_time(date, ts):
    best_session = None
    for h, m, session_name in BRIEFING_SESSIONS:
        gen_time = datetime(ts.year, ts.month, ts.day, h, m, tzinfo=timezone.utc)
        if ts >= gen_time:
            best_session = session_name
    if best_session is None:
        return None
    path = Path(f"/opt/tradingbot/logs/briefing_GBPUSD_{date}_{best_session}.json")
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def main():
    print("=" * 130)
    print("  POST-TP1 CONTINUATION ANALYSIS — GBPUSD V1/V3 sweeps that hit TP1")
    print("  Traces price from TP1 candle to session end (17:00 UTC)")
    print("=" * 130)
    print()

    results = []

    for date in DATES:
        df = load_candles(date)
        if df.empty or len(df) < WARMUP + 10:
            continue

        strat = BriefingLiquidityStrategy()
        open_trade = None
        last_signal_time = None

        for i in range(WARMUP, len(df)):
            ts = df["timestamp"].iloc[i]
            if not isinstance(ts, datetime):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            _SimDatetime._sim_now = ts

            h = ts.hour
            candle_high = float(df["high"].iloc[i])
            candle_low = float(df["low"].iloc[i])
            candle_close = float(df["close"].iloc[i])

            # Check open trade for TP1 hit
            if open_trade and not open_trade.get("closed"):
                hit_tp1 = False
                if open_trade["direction"] == "BUY" and candle_high >= open_trade["tp1_price"]:
                    hit_tp1 = True
                elif open_trade["direction"] == "SELL" and candle_low <= open_trade["tp1_price"]:
                    hit_tp1 = True

                if hit_tp1:
                    open_trade["tp1_hit_candle"] = i
                    open_trade["tp1_hit_time"] = ts.strftime("%H:%M")
                    open_trade["closed"] = True

                # Check SL
                if not open_trade.get("closed"):
                    if open_trade["direction"] == "BUY" and candle_low <= open_trade["sl_price"]:
                        open_trade["closed"] = True
                        open_trade["outcome"] = "SL"
                    elif open_trade["direction"] == "SELL" and candle_high >= open_trade["sl_price"]:
                        open_trade["closed"] = True
                        open_trade["outcome"] = "SL"

                # Session end
                if not open_trade.get("closed") and h >= SESSION_END:
                    open_trade["closed"] = True
                    open_trade["outcome"] = "17:00"

            if h < SESSION_START or h >= SESSION_END:
                continue
            if open_trade and not open_trade.get("closed"):
                continue
            if last_signal_time and (ts - last_signal_time) < timedelta(minutes=COOLDOWN_MINS):
                continue

            briefing = get_briefing_for_time(date, ts)
            if not briefing:
                continue

            df_slice = df.iloc[max(0, i - WARMUP + 1):i + 1].copy()
            try:
                dec = strat.evaluate(SYMBOL, EPIC, df_slice, PPP, candle_close, briefing)
            except Exception:
                continue

            sig = str(dec.signal or "").upper()
            if sig not in ("BUY", "SELL"):
                continue

            entry_source = dec.debug.get("entry_source", "")
            if entry_source not in ("sweep_v1", "sweep_v3"):
                # Still record non-V1/V3 to consume cooldown
                last_signal_time = ts
                open_trade = {"closed": True}
                continue

            entry = float(dec.entry or candle_close)
            sl_pips = float(dec.sl or 10)
            tp1_pips = float(dec.tp or 15)
            tp2_pips = float(dec.debug.get("tp2_pips") or 0)
            tp2_price = float(dec.debug.get("tp2_price") or 0)
            tp3_pips = float(dec.debug.get("tp3_pips") or 0)
            tp3_price = float(dec.debug.get("tp3_price") or 0)

            if sig == "BUY":
                sl_price = entry - sl_pips * PPP
                tp1_price = entry + tp1_pips * PPP
            else:
                sl_price = entry + sl_pips * PPP
                tp1_price = entry - tp1_pips * PPP

            open_trade = {
                "date": date,
                "entry_time": ts.strftime("%H:%M"),
                "direction": sig,
                "entry": entry,
                "sl_price": sl_price,
                "sl_pips": sl_pips,
                "tp1_price": tp1_price,
                "tp1_pips": tp1_pips,
                "tp2_pips": tp2_pips,
                "tp2_price": tp2_price,
                "tp3_pips": tp3_pips,
                "tp3_price": tp3_price,
                "source": entry_source,
                "closed": False,
                "tp1_hit_candle": None,
                "tp1_hit_time": None,
                "outcome": None,
            }
            last_signal_time = ts

        # Now for any trade that hit TP1, trace post-TP1 price action
        if open_trade and open_trade.get("tp1_hit_candle") is not None:
            t = open_trade
            tp1_i = t["tp1_hit_candle"]
            direction = t["direction"]
            entry = t["entry"]
            tp1_price = t["tp1_price"]
            tp2_price = t["tp2_price"]
            tp3_price = t["tp3_price"]

            max_continuation_pips = 0
            max_continuation_time = None
            reached_tp2 = False
            reached_tp2_time = None
            reached_tp3 = False
            reached_tp3_time = None
            reversal_candle = None

            # Scan from TP1 candle to end of data or 17:00
            for j in range(tp1_i, len(df)):
                ts_j = df["timestamp"].iloc[j]
                if not isinstance(ts_j, datetime):
                    ts_j = ts_j.to_pydatetime()
                if ts_j.tzinfo is None:
                    ts_j = ts_j.replace(tzinfo=timezone.utc)
                if ts_j.hour >= SESSION_END:
                    break

                h_j = float(df["high"].iloc[j])
                l_j = float(df["low"].iloc[j])

                if direction == "SELL":
                    # Continuation = price going lower
                    best_this_candle = (tp1_price - l_j) / PPP
                    if best_this_candle > max_continuation_pips:
                        max_continuation_pips = best_this_candle
                        max_continuation_time = ts_j.strftime("%H:%M")
                    if tp2_price > 0 and l_j <= tp2_price and not reached_tp2:
                        reached_tp2 = True
                        reached_tp2_time = ts_j.strftime("%H:%M")
                    if tp3_price > 0 and l_j <= tp3_price and not reached_tp3:
                        reached_tp3 = True
                        reached_tp3_time = ts_j.strftime("%H:%M")
                else:
                    # Continuation = price going higher
                    best_this_candle = (h_j - tp1_price) / PPP
                    if best_this_candle > max_continuation_pips:
                        max_continuation_pips = best_this_candle
                        max_continuation_time = ts_j.strftime("%H:%M")
                    if tp2_price > 0 and h_j >= tp2_price and not reached_tp2:
                        reached_tp2 = True
                        reached_tp2_time = ts_j.strftime("%H:%M")
                    if tp3_price > 0 and h_j >= tp3_price and not reached_tp3:
                        reached_tp3 = True
                        reached_tp3_time = ts_j.strftime("%H:%M")

            # Time from TP1 to max continuation
            tp1_ts = datetime.strptime(f"{t['date']} {t['tp1_hit_time']}", "%Y-%m-%d %H:%M")
            if max_continuation_time:
                max_ts = datetime.strptime(f"{t['date']} {max_continuation_time}", "%Y-%m-%d %H:%M")
                duration_mins = int((max_ts - tp1_ts).total_seconds() / 60)
            else:
                duration_mins = 0

            results.append({
                **t,
                "max_continuation_pips": max_continuation_pips,
                "max_continuation_time": max_continuation_time,
                "duration_mins": duration_mins,
                "reached_tp2": reached_tp2,
                "reached_tp2_time": reached_tp2_time,
                "reached_tp3": reached_tp3,
                "reached_tp3_time": reached_tp3_time,
            })

    # === Output ===
    print(f"  {'Date':>12} {'Entry':>6} {'Src':>9} {'Dir':>5} {'TP1':>6} {'TP2':>6} {'TP3':>6} "
          f"{'TP1@':>6} {'MaxCont':>8} {'MaxAt':>6} {'Dur':>6} {'→TP2':>5} {'→TP3':>5}")
    print("-" * 130)

    for r in results:
        tp2_str = f"{r['tp2_pips']:.1f}" if r['tp2_pips'] > 0 else "  —"
        tp3_str = f"{r['tp3_pips']:.1f}" if r['tp3_pips'] > 0 else "  —"
        tp2_hit = f"{'✓':>4} {r['reached_tp2_time']}" if r['reached_tp2'] else "  ✗"
        tp3_hit = f"{'✓':>4} {r['reached_tp3_time']}" if r['reached_tp3'] else "  ✗"
        dur_str = f"{r['duration_mins']}m"

        print(f"  {r['date']:>12} {r['entry_time']:>6} {r['source']:>9} {r['direction']:>5} "
              f"{r['tp1_pips']:>6.1f} {tp2_str:>6} {tp3_str:>6} "
              f"{r['tp1_hit_time']:>6} {r['max_continuation_pips']:>+8.1f} {r['max_continuation_time'] or '—':>6} "
              f"{dur_str:>6} {tp2_hit:>10} {tp3_hit:>10}")

    print()
    print("=" * 130)
    print("  SUMMARY")
    print("=" * 130)
    n = len(results)
    if n == 0:
        print("  No TP1 hits found.")
        return

    tp2_count = sum(1 for r in results if r["reached_tp2"])
    tp3_count = sum(1 for r in results if r["reached_tp3"])
    avg_cont = np.mean([r["max_continuation_pips"] for r in results])
    avg_dur = np.mean([r["duration_mins"] for r in results])
    max_cont = max(r["max_continuation_pips"] for r in results)
    min_cont = min(r["max_continuation_pips"] for r in results)

    with_tp2 = [r for r in results if r["tp2_pips"] > 0]
    tp2_possible = len(with_tp2)
    tp2_reached = sum(1 for r in with_tp2 if r["reached_tp2"])

    print(f"  TP1 hits analysed:         {n}")
    print(f"  Reached TP2:               {tp2_reached}/{tp2_possible} ({tp2_reached/tp2_possible*100:.0f}% of trades with TP2)")
    print(f"  Reached TP3:               {tp3_count}/{n}")
    print(f"  Avg continuation past TP1: {avg_cont:+.1f} pips")
    print(f"  Max continuation:          {max_cont:+.1f} pips")
    print(f"  Min continuation:          {min_cont:+.1f} pips")
    print(f"  Avg time to max:           {avg_dur:.0f} minutes")
    print()

    # What-if: extra pips if held to TP2 vs closed at TP1
    print("  WHAT-IF: 50% at TP1, 50% held to TP2 (or BE if TP2 not reached)")
    total_tp1_only = sum(r["tp1_pips"] for r in results)
    total_partial = 0
    for r in results:
        tp1_half = r["tp1_pips"] * 0.5
        if r["reached_tp2"] and r["tp2_pips"] > 0:
            tp2_half = r["tp2_pips"] * 0.5
        else:
            tp2_half = 0  # BE on the remainder
        total_partial += tp1_half + tp2_half

    print(f"  100% at TP1:               {total_tp1_only:+.1f} pips")
    print(f"  50/50 partial close:       {total_partial:+.1f} pips")
    print(f"  Difference:                {total_partial - total_tp1_only:+.1f} pips")
    print("=" * 130)


if __name__ == "__main__":
    main()
