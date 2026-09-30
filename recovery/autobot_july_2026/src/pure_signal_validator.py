#!/usr/bin/env python3
"""
pure_signal_validator.py — Two-phase signal backtest on GBPUSD 5-min candles.

Phase 1 (Armed): BB pierce (close beyond band) + MACD histogram compressing
over last 3 candles (bars reducing in absolute size).
Phase 2 (Entry): MACD line crosses signal line in reversal direction within
5 candles. Entry on crossover candle close. SL at crossover candle high/low + 3p.

Filters by briefing session bias alignment.
Splits results by London (06:00-12:00 UTC) and NY (12:00-16:00 UTC).
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
from indicators import add_indicators, IndicatorsConfig

CANDLE_DIR = Path("/opt/tradingbot/data/candles/GBPUSD")
BRIEFING_DIR = Path("/opt/tradingbot/logs")
OUTPUT_PATH = Path("/opt/tradingbot/data/signal_validation_results.json")

# Indicator config matching live bot
CFG = IndicatorsConfig(
    bb_period=20, bb_std=2.0,
    macd_fast=35, macd_slow=45, macd_signal=30,
)

# Column names
BB_UPPER = f"BB_UPPER_{CFG.bb_period}_{CFG.bb_std:g}"
BB_LOWER = f"BB_LOWER_{CFG.bb_period}_{CFG.bb_std:g}"
MACD_LINE = f"MACD_{CFG.macd_fast}_{CFG.macd_slow}"
MACD_SIG = f"MACD_SIGNAL_{CFG.macd_fast}_{CFG.macd_slow}_{CFG.macd_signal}"
MACD_HIST = f"MACD_HIST_{CFG.macd_fast}_{CFG.macd_slow}_{CFG.macd_signal}"

# Trade parameters
TARGETS = [20, 30, 40]
SL_BUFFER = 3  # pips beyond crossover candle extreme
ARMED_EXPIRY = 5  # max candles to wait for crossover
LOOKAHEAD = 20  # candles to measure outcome after entry


def load_all_candles() -> pd.DataFrame:
    frames = []
    for f in sorted(CANDLE_DIR.glob("*.csv")):
        df = pd.read_csv(f)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        frames.append(df)
    if not frames:
        print("ERROR: No candle files found")
        sys.exit(1)
    combined = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return add_indicators(combined, config=CFG)


def load_briefing_bias_index() -> list[dict]:
    entries = []
    for f in sorted(BRIEFING_DIR.glob("briefing_GBPUSD_*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        bias = str(data.get("session_bias", "")).upper().strip()
        bt = data.get("briefing_time")
        if not bt or not bias:
            continue
        ts = pd.Timestamp(bt)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        entries.append({"briefing_time": ts, "bias": bias})
    entries.sort(key=lambda e: e["briefing_time"])
    return entries


def get_bias_at(ts: pd.Timestamp, bias_index: list[dict]) -> str | None:
    result = None
    for entry in bias_index:
        if entry["briefing_time"] <= ts:
            result = entry["bias"]
        else:
            break
    return result


def signal_matches_bias(direction: str, bias: str | None) -> bool:
    if bias is None:
        return False
    return (direction == "SHORT" and bias == "BEARISH") or \
           (direction == "LONG" and bias == "BULLISH")


def get_session(hour_utc: int) -> str | None:
    if 6 <= hour_utc < 12:
        return "London"
    if 12 <= hour_utc < 16:
        return "NY"
    return None


def find_two_phase_signals(df: pd.DataFrame, bias_index: list[dict]) -> list[dict]:
    """Scan for Phase 1 (BB pierce + histogram compression) then Phase 2 (MACD crossover)."""
    signals = []
    n = len(df)
    i = 4  # start after warmup

    while i < n:
        close_i = df.at[i, "close"]
        bb_upper = df.at[i, BB_UPPER]
        bb_lower = df.at[i, BB_LOWER]

        if pd.isna(bb_upper) or pd.isna(bb_lower):
            i += 1
            continue

        # Phase 1: BB pierce (close beyond band)
        pierce_upper = close_i > bb_upper
        pierce_lower = close_i < bb_lower
        if not pierce_upper and not pierce_lower:
            i += 1
            continue

        # Phase 1: MACD histogram compressing over last 3 candles
        hists = [abs(df.at[i - k, MACD_HIST]) for k in range(3)]
        if any(pd.isna(h) for h in hists):
            i += 1
            continue
        hist_compressing = hists[2] > hists[1] > hists[0]
        if not hist_compressing:
            i += 1
            continue

        # ARMED — now scan up to ARMED_EXPIRY candles for MACD crossover
        direction = "SHORT" if pierce_upper else "LONG"
        pierce_ts = df.at[i, "timestamp"]
        pierce_idx = i

        crossover_idx = None
        for j in range(i + 1, min(i + 1 + ARMED_EXPIRY, n)):
            cur_m = df.at[j, MACD_LINE]
            cur_s = df.at[j, MACD_SIG]
            prev_m = df.at[j - 1, MACD_LINE]
            prev_s = df.at[j - 1, MACD_SIG]

            if any(pd.isna(v) for v in (cur_m, cur_s, prev_m, prev_s)):
                continue

            if direction == "SHORT":
                crossover = prev_m >= prev_s and cur_m < cur_s
            else:
                crossover = prev_m <= prev_s and cur_m > cur_s

            if crossover:
                crossover_idx = j
                break

        if crossover_idx is None:
            # No crossover — setup expired, advance past the armed window
            i += 1
            continue

        # Phase 2 triggered — entry on crossover candle close
        entry_idx = crossover_idx
        entry_price = df.at[entry_idx, "close"]
        entry_ts = df.at[entry_idx, "timestamp"]
        xo_high = df.at[entry_idx, "high"]
        xo_low = df.at[entry_idx, "low"]

        # SL: crossover candle extreme + buffer
        if direction == "SHORT":
            sl_price = xo_high + SL_BUFFER
            sl_pips = sl_price - entry_price
        else:
            sl_price = xo_low - SL_BUFFER
            sl_pips = entry_price - sl_price

        if sl_pips <= 0:
            sl_pips = SL_BUFFER  # fallback

        # Bias and session
        bias = get_bias_at(entry_ts, bias_index)
        session = get_session(entry_ts.hour)
        bias_aligned = signal_matches_bias(direction, bias)
        candles_to_xo = crossover_idx - pierce_idx

        # Measure outcome
        max_adverse = 0.0
        max_favour = 0.0
        hit_targets = {t: False for t in TARGETS}
        hit_sl = False

        end_idx = min(entry_idx + 1 + LOOKAHEAD, n)
        for k in range(entry_idx + 1, end_idx):
            if direction == "SHORT":
                adverse = df.at[k, "high"] - entry_price
                favour = entry_price - df.at[k, "low"]
            else:
                adverse = entry_price - df.at[k, "low"]
                favour = df.at[k, "high"] - entry_price

            max_adverse = max(max_adverse, adverse)
            max_favour = max(max_favour, favour)

            if adverse >= sl_pips and not hit_sl:
                hit_sl = True
            for t in TARGETS:
                if favour >= t and not hit_targets[t]:
                    hit_targets[t] = True

        # PnL
        if hit_sl and not any(hit_targets.values()):
            pnl = -sl_pips
        elif any(hit_targets.values()):
            pnl = max(t for t in TARGETS if hit_targets[t])
        else:
            final_close = df.at[min(entry_idx + LOOKAHEAD, n - 1), "close"]
            pnl = (entry_price - final_close) if direction == "SHORT" else (final_close - entry_price)

        signals.append({
            "pierce_idx": int(pierce_idx),
            "entry_idx": int(entry_idx),
            "timestamp": str(entry_ts),
            "pierce_timestamp": str(pierce_ts),
            "hour": int(entry_ts.hour),
            "date": str(entry_ts.date()),
            "direction": direction,
            "entry_price": float(entry_price),
            "bb_pierce": "upper" if pierce_upper else "lower",
            "candles_to_crossover": candles_to_xo,
            "sl_pips": round(sl_pips, 2),
            "xo_high": round(xo_high, 2),
            "xo_low": round(xo_low, 2),
            "hit_20p": hit_targets[20],
            "hit_30p": hit_targets[30],
            "hit_40p": hit_targets[40],
            "hit_sl": hit_sl,
            "max_adverse_excursion": round(max_adverse, 2),
            "max_favourable_excursion": round(max_favour, 2),
            "pnl_pips": round(pnl, 2),
            "briefing_bias": bias,
            "bias_aligned": bias_aligned,
            "session": session,
        })

        # Advance past entry to avoid overlapping signals
        i = entry_idx + 1
        continue

    return signals


def print_session_block(label: str, df: pd.DataFrame) -> dict:
    total = len(df)
    if total == 0:
        print(f"\n  {label}: no signals")
        return {"signals": 0}

    shorts = len(df[df["direction"] == "SHORT"])
    longs = len(df[df["direction"] == "LONG"])
    wr_20 = df["hit_20p"].sum() / total * 100
    wr_30 = df["hit_30p"].sum() / total * 100
    wr_40 = df["hit_40p"].sum() / total * 100
    sl_rate = df["hit_sl"].sum() / total * 100
    avg_pnl = df["pnl_pips"].mean()
    avg_mae = df["max_adverse_excursion"].mean()
    avg_mfe = df["max_favourable_excursion"].mean()
    avg_sl = df["sl_pips"].mean()
    avg_xo = df["candles_to_crossover"].mean()

    print(f"\n  {'=' * 62}")
    print(f"  {label}")
    print(f"  {'=' * 62}")
    print(f"  Signals: {total}  (SHORT: {shorts}, LONG: {longs})")
    print(f"  Avg candles to crossover: {avg_xo:.1f}  |  Avg dynamic SL: {avg_sl:.1f}p")
    print()
    print(f"  {'20p target:':<18} {wr_20:>6.1f}%  ({int(df['hit_20p'].sum())}/{total})")
    print(f"  {'30p target:':<18} {wr_30:>6.1f}%  ({int(df['hit_30p'].sum())}/{total})")
    print(f"  {'40p target:':<18} {wr_40:>6.1f}%  ({int(df['hit_40p'].sum())}/{total})")
    print(f"  {'SL hit:':<18} {sl_rate:>6.1f}%  ({int(df['hit_sl'].sum())}/{total})")
    print()
    print(f"  {'Avg pip capture:':<22} {avg_pnl:>+7.2f}")
    print(f"  {'Avg MAE:':<22} {avg_mae:>7.2f}")
    print(f"  {'Avg MFE:':<22} {avg_mfe:>7.2f}")

    if total > 0:
        best = df.loc[df["pnl_pips"].idxmax()]
        worst = df.loc[df["pnl_pips"].idxmin()]
        print(f"  {'Best trade:':<22} {best['pnl_pips']:>+7.2f}p  ({best['timestamp'][:16]})")
        print(f"  {'Worst trade:':<22} {worst['pnl_pips']:>+7.2f}p  ({worst['timestamp'][:16]})")

    hour_stats = df.groupby("hour").agg(
        count=("pnl_pips", "size"),
        win_rate_20=("hit_20p", "mean"),
        avg_pnl=("pnl_pips", "mean"),
        avg_mfe=("max_favourable_excursion", "mean"),
    ).reset_index()
    hour_stats["win_rate_20"] = (hour_stats["win_rate_20"] * 100).round(1)
    hour_stats["avg_pnl"] = hour_stats["avg_pnl"].round(2)
    hour_stats["avg_mfe"] = hour_stats["avg_mfe"].round(2)

    print()
    print(f"  {'Hour':<6} {'Count':>5} {'WR(20p)':>8} {'AvgPnL':>8} {'AvgMFE':>8}")
    print(f"  {'─' * 6} {'─' * 5} {'─' * 8} {'─' * 8} {'─' * 8}")
    for _, row in hour_stats.sort_values("hour").iterrows():
        print(f"  {int(row['hour']):>4}   {int(row['count']):>4}  {row['win_rate_20']:>6.1f}%  {row['avg_pnl']:>+7.2f}  {row['avg_mfe']:>7.2f}")

    return {
        "signals": total,
        "direction_split": {"SHORT": shorts, "LONG": longs},
        "avg_candles_to_crossover": round(avg_xo, 1),
        "avg_dynamic_sl": round(avg_sl, 1),
        "target_hit_rates": {
            "20p": {"rate": round(wr_20, 1), "count": int(df["hit_20p"].sum())},
            "30p": {"rate": round(wr_30, 1), "count": int(df["hit_30p"].sum())},
            "40p": {"rate": round(wr_40, 1), "count": int(df["hit_40p"].sum())},
        },
        "stop_loss_rate": {"rate": round(sl_rate, 1), "count": int(df["hit_sl"].sum())},
        "avg_pnl_pips": round(avg_pnl, 2),
        "avg_mae": round(avg_mae, 2),
        "avg_mfe": round(avg_mfe, 2),
        "hour_breakdown": hour_stats.to_dict(orient="records"),
    }


def analyse_and_report(signals: list[dict]) -> dict:
    all_df = pd.DataFrame(signals)

    if all_df.empty:
        print("No signals found.")
        return {"total_signals": 0}

    total_raw = len(all_df)
    in_session = all_df[all_df["session"].notna()]
    has_bias = in_session[in_session["briefing_bias"].notna()]
    aligned = has_bias[has_bias["bias_aligned"]]
    rejected = has_bias[~has_bias["bias_aligned"]]
    no_bias = in_session[in_session["briefing_bias"].isna()]
    outside = all_df[all_df["session"].isna()]

    london = aligned[aligned["session"] == "London"]
    ny = aligned[aligned["session"] == "NY"]

    print("=" * 70)
    print("  TWO-PHASE SIGNAL VALIDATOR — BB Pierce -> MACD Crossover (GBPUSD)")
    print("=" * 70)
    print(f"  Data range:       {all_df['date'].min()} -> {all_df['date'].max()}")
    print(f"  Phase 1: BB pierce + histogram compressing (3 bars)")
    print(f"  Phase 2: MACD crossover within {ARMED_EXPIRY} candles")
    print(f"  SL: crossover candle extreme + {SL_BUFFER}p buffer")
    print()
    print("  SIGNAL FUNNEL")
    print(f"  {'Raw two-phase signals:':<32} {total_raw:>4}")
    print(f"  {'In London/NY window:':<32} {len(in_session):>4}")
    print(f"  {'  Have briefing bias:':<32} {len(has_bias):>4}")
    print(f"  {'  Bias-aligned (kept):':<32} {len(aligned):>4}")
    print(f"  {'  Bias-rejected (dropped):':<32} {len(rejected):>4}")
    print(f"  {'  No briefing available:':<32} {len(no_bias):>4}")
    print(f"  {'Outside session window:':<32} {len(outside):>4}")

    if len(rejected) > 0:
        rej_pnl = rejected["pnl_pips"].mean()
        rej_wr20 = rejected["hit_20p"].mean() * 100
        rej_sl = rejected["hit_sl"].mean() * 100
        print()
        print(f"  REJECTED (counter-bias) for reference:")
        print(f"    {len(rejected)} signals, WR(20p)={rej_wr20:.1f}%, SL%={rej_sl:.1f}%, AvgPnL={rej_pnl:+.2f}p")

    # Compare old (pierce-only) vs new (two-phase) on all raw signals
    if len(all_df) > 0:
        avg_xo_all = all_df["candles_to_crossover"].mean()
        xo_dist = all_df["candles_to_crossover"].value_counts().sort_index()
        print()
        print(f"  CROSSOVER TIMING (all signals)")
        print(f"  {'Avg candles to crossover:':<32} {avg_xo_all:.1f}")
        for c, count in xo_dist.items():
            print(f"    Candle {c}: {count} signals ({count/len(all_df)*100:.0f}%)")

    london_stats = print_session_block("LONDON SESSION  (06:00-12:00 UTC / 07:00-13:00 BST)", london)
    ny_stats = print_session_block("NEW YORK SESSION  (12:00-16:00 UTC / 13:00-17:00 BST)", ny)

    # Equity curve
    if len(aligned) > 0:
        equity = aligned.groupby("date")["pnl_pips"].sum().cumsum().reset_index()
        equity.columns = ["date", "cumulative_pnl"]
        print(f"\n  {'=' * 62}")
        print(f"  EQUITY CURVE (bias-aligned signals only)")
        print(f"  {'=' * 62}")
        for _, row in equity.iterrows():
            bar_len = int(abs(row["cumulative_pnl"]) / 3)
            bar_char = "+" if row["cumulative_pnl"] >= 0 else "-"
            sign = "+" if row["cumulative_pnl"] >= 0 else ""
            print(f"  {row['date']}  {sign}{row['cumulative_pnl']:>7.1f}p  {bar_char * min(bar_len, 40)}")
    else:
        equity = pd.DataFrame(columns=["date", "cumulative_pnl"])

    print()
    print("=" * 70)

    results = {
        "signal_definition": {
            "phase_1": "BB pierce (close beyond band) + MACD histogram compressing 3 bars",
            "phase_2": f"MACD crossover in reversal direction within {ARMED_EXPIRY} candles",
            "sl": f"Crossover candle extreme + {SL_BUFFER}p buffer",
        },
        "data_range": {"start": all_df["date"].min(), "end": all_df["date"].max()},
        "signal_funnel": {
            "raw_signals": total_raw,
            "in_session_window": len(in_session),
            "have_briefing_bias": len(has_bias),
            "bias_aligned": len(aligned),
            "bias_rejected": len(rejected),
            "no_briefing": len(no_bias),
            "outside_session": len(outside),
        },
        "london": london_stats,
        "ny": ny_stats,
        "rejected_counter_bias": {
            "count": len(rejected),
            "avg_pnl": round(rejected["pnl_pips"].mean(), 2) if len(rejected) > 0 else None,
            "wr_20p": round(rejected["hit_20p"].mean() * 100, 1) if len(rejected) > 0 else None,
        },
        "equity_curve": equity.to_dict(orient="records"),
        "all_signals": signals,
    }
    return results


def main():
    print("Loading GBPUSD candle data...")
    df = load_all_candles()
    print(f"Loaded {len(df)} candles across {df['timestamp'].dt.date.nunique()} days")

    print("Loading briefing bias index...")
    bias_index = load_briefing_bias_index()
    print(f"Loaded {len(bias_index)} briefing bias entries")
    print()

    print("Scanning for two-phase signals...")
    signals = find_two_phase_signals(df, bias_index)

    results = analyse_and_report(signals)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
