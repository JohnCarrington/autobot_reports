#!/usr/bin/env python3
"""
sweep_level_validator.py — BB pierce + liquidity pool level confluence backtest.

Only counts BB pierces that occur within 8 pips of a briefing liquidity_pools
level (buy_side for SELL, sell_side for BUY). Compares against unfiltered
BB pierce results to measure improvement from level confluence.
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
OUTPUT_PATH = Path("/opt/tradingbot/data/sweep_level_validation_results.json")

CFG = IndicatorsConfig(
    bb_period=20, bb_std=2.0,
    macd_fast=35, macd_slow=45, macd_signal=30,
)

BB_UPPER = f"BB_UPPER_{CFG.bb_period}_{CFG.bb_std:g}"
BB_LOWER = f"BB_LOWER_{CFG.bb_period}_{CFG.bb_std:g}"
MACD_HIST = f"MACD_HIST_{CFG.macd_fast}_{CFG.macd_slow}_{CFG.macd_signal}"

TARGETS = [20, 30, 40]
STOP_LOSS = 12
LOOKAHEAD = 20
LEVEL_TOLERANCE = 8  # pips


def load_all_candles() -> pd.DataFrame:
    frames = []
    for f in sorted(CANDLE_DIR.glob("*.csv")):
        df = pd.read_csv(f)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        frames.append(df)
    if not frames:
        print("ERROR: No candle files found"); sys.exit(1)
    combined = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return add_indicators(combined, config=CFG)


def load_briefing_index() -> list[dict]:
    """Load all GBPUSD briefings with liquidity_pools and bias, sorted by time."""
    entries = []
    for f in sorted(BRIEFING_DIR.glob("briefing_GBPUSD_*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        bt = data.get("briefing_time")
        if not bt:
            continue
        ts = pd.Timestamp(bt)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")

        lp = data.get("liquidity_pools") or {}
        bias = str(data.get("session_bias", "")).upper().strip()
        entries.append({
            "briefing_time": ts,
            "bias": bias,
            "buy_side": [float(v) for v in (lp.get("buy_side") or []) if v is not None],
            "sell_side": [float(v) for v in (lp.get("sell_side") or []) if v is not None],
        })
    entries.sort(key=lambda e: e["briefing_time"])
    return entries


def get_briefing_at(ts: pd.Timestamp, index: list[dict]) -> dict | None:
    result = None
    for entry in index:
        if entry["briefing_time"] <= ts:
            result = entry
        else:
            break
    return result


def get_session(hour_utc: int) -> str | None:
    if 6 <= hour_utc < 12:
        return "London"
    if 12 <= hour_utc < 16:
        return "NY"
    return None


def find_signals(df: pd.DataFrame, briefing_index: list[dict]) -> tuple[list[dict], list[dict]]:
    """Find all BB pierce signals. Return (lp_filtered, all_unfiltered)."""
    all_signals = []
    lp_signals = []
    n = len(df)

    for i in range(4, n - LOOKAHEAD):
        close_i = df.at[i, "close"]
        high_i = df.at[i, "high"]
        low_i = df.at[i, "low"]
        bb_upper = df.at[i, BB_UPPER]
        bb_lower = df.at[i, BB_LOWER]

        if pd.isna(bb_upper) or pd.isna(bb_lower):
            continue

        pierce_upper = close_i > bb_upper
        pierce_lower = close_i < bb_lower
        if not pierce_upper and not pierce_lower:
            continue

        # MACD histogram compressing
        hists = [abs(df.at[i - k, MACD_HIST]) for k in range(3)]
        if any(pd.isna(h) for h in hists):
            continue
        if not (hists[2] > hists[1] > hists[0]):
            continue

        direction = "SHORT" if pierce_upper else "LONG"
        ts = df.at[i, "timestamp"]
        entry_price = close_i
        session = get_session(ts.hour)

        # Look up briefing
        briefing = get_briefing_at(ts, briefing_index)
        bias = briefing["bias"] if briefing else None
        bias_aligned = (direction == "SHORT" and bias == "BEARISH") or \
                       (direction == "LONG" and bias == "BULLISH")

        # Check liquidity pool proximity
        lp_match = False
        lp_level = None
        if briefing:
            if direction == "SHORT":
                pool = briefing.get("buy_side", [])
                pierce_extreme = high_i
            else:
                pool = briefing.get("sell_side", [])
                pierce_extreme = low_i
            for lv in pool:
                if abs(pierce_extreme - lv) <= LEVEL_TOLERANCE:
                    lp_match = True
                    lp_level = lv
                    break

        # Measure outcome
        max_adverse = 0.0
        max_favour = 0.0
        hit_targets = {t: False for t in TARGETS}
        hit_sl = False

        for j in range(i + 1, min(i + 1 + LOOKAHEAD, n)):
            if direction == "SHORT":
                adverse = df.at[j, "high"] - entry_price
                favour = entry_price - df.at[j, "low"]
            else:
                adverse = entry_price - df.at[j, "low"]
                favour = df.at[j, "high"] - entry_price

            max_adverse = max(max_adverse, adverse)
            max_favour = max(max_favour, favour)

            if adverse >= STOP_LOSS and not hit_sl:
                hit_sl = True
            for t in TARGETS:
                if favour >= t and not hit_targets[t]:
                    hit_targets[t] = True

        if hit_sl and not any(hit_targets.values()):
            pnl = -STOP_LOSS
        elif any(hit_targets.values()):
            pnl = max(t for t in TARGETS if hit_targets[t])
        else:
            final_close = df.at[min(i + LOOKAHEAD, n - 1), "close"]
            pnl = (entry_price - final_close) if direction == "SHORT" else (final_close - entry_price)

        sig = {
            "index": int(i),
            "timestamp": str(ts),
            "hour": int(ts.hour),
            "date": str(ts.date()),
            "direction": direction,
            "entry_price": float(entry_price),
            "pierce_extreme": float(high_i if pierce_upper else low_i),
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
            "lp_match": lp_match,
            "lp_level": lp_level,
        }

        all_signals.append(sig)
        if lp_match:
            lp_signals.append(sig)

    return lp_signals, all_signals


def compute_stats(df: pd.DataFrame, label: str) -> dict:
    total = len(df)
    if total == 0:
        return {"signals": 0, "label": label}

    wr_20 = df["hit_20p"].sum() / total * 100
    wr_30 = df["hit_30p"].sum() / total * 100
    wr_40 = df["hit_40p"].sum() / total * 100
    sl_rate = df["hit_sl"].sum() / total * 100
    avg_pnl = df["pnl_pips"].mean()
    avg_mae = df["max_adverse_excursion"].mean()
    avg_mfe = df["max_favourable_excursion"].mean()

    return {
        "label": label,
        "signals": total,
        "wr_20p": round(wr_20, 1),
        "wr_30p": round(wr_30, 1),
        "wr_40p": round(wr_40, 1),
        "sl_rate": round(sl_rate, 1),
        "avg_pnl": round(avg_pnl, 2),
        "avg_mae": round(avg_mae, 2),
        "avg_mfe": round(avg_mfe, 2),
    }


def print_comparison(unfiltered: dict, filtered: dict):
    """Print side-by-side comparison."""
    print(f"\n  {'Metric':<22} {'All BB Pierce':>14} {'LP Confluence':>14} {'Delta':>10}")
    print(f"  {'─' * 22} {'─' * 14} {'─' * 14} {'─' * 10}")
    for key, label in [
        ("signals", "Signals"),
        ("wr_20p", "WR 20p (%)"),
        ("wr_30p", "WR 30p (%)"),
        ("wr_40p", "WR 40p (%)"),
        ("sl_rate", "SL hit (%)"),
        ("avg_pnl", "Avg PnL (p)"),
        ("avg_mae", "Avg MAE (p)"),
        ("avg_mfe", "Avg MFE (p)"),
    ]:
        v1 = unfiltered.get(key, 0)
        v2 = filtered.get(key, 0)
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            delta = v2 - v1
            sign = "+" if delta > 0 else ""
            print(f"  {label:<22} {v1:>14} {v2:>14} {sign}{delta:>9.1f}")
        else:
            print(f"  {label:<22} {v1:>14} {v2:>14}")


def print_block(label: str, df: pd.DataFrame):
    """Print detailed stats for a subset."""
    total = len(df)
    if total == 0:
        print(f"\n  {label}: no signals")
        return

    shorts = len(df[df["direction"] == "SHORT"])
    longs = len(df[df["direction"] == "LONG"])
    stats = compute_stats(df, label)

    print(f"\n  {'=' * 62}")
    print(f"  {label}")
    print(f"  {'=' * 62}")
    print(f"  Signals: {total}  (SHORT: {shorts}, LONG: {longs})")
    print(f"  {'20p WR:':<18} {stats['wr_20p']:>6.1f}%")
    print(f"  {'30p WR:':<18} {stats['wr_30p']:>6.1f}%")
    print(f"  {'40p WR:':<18} {stats['wr_40p']:>6.1f}%")
    print(f"  {'SL hit:':<18} {stats['sl_rate']:>6.1f}%")
    print(f"  {'Avg PnL:':<18} {stats['avg_pnl']:>+7.2f}p")
    print(f"  {'Avg MAE:':<18} {stats['avg_mae']:>7.2f}p")
    print(f"  {'Avg MFE:':<18} {stats['avg_mfe']:>7.2f}p")

    if total > 0:
        best = df.loc[df["pnl_pips"].idxmax()]
        worst = df.loc[df["pnl_pips"].idxmin()]
        print(f"  {'Best:':<18} {best['pnl_pips']:>+7.2f}p  ({best['timestamp'][:16]})")
        print(f"  {'Worst:':<18} {worst['pnl_pips']:>+7.2f}p  ({worst['timestamp'][:16]})")

    # Hour breakdown
    hour_stats = df.groupby("hour").agg(
        count=("pnl_pips", "size"),
        wr_20=("hit_20p", "mean"),
        avg_pnl=("pnl_pips", "mean"),
    ).reset_index()
    hour_stats["wr_20"] = (hour_stats["wr_20"] * 100).round(1)
    hour_stats["avg_pnl"] = hour_stats["avg_pnl"].round(2)

    print(f"\n  {'Hour':<6} {'Count':>5} {'WR(20p)':>8} {'AvgPnL':>8}")
    print(f"  {'─' * 6} {'─' * 5} {'─' * 8} {'─' * 8}")
    for _, row in hour_stats.sort_values("hour").iterrows():
        print(f"  {int(row['hour']):>4}   {int(row['count']):>4}  {row['wr_20']:>6.1f}%  {row['avg_pnl']:>+7.2f}")


def main():
    print("Loading GBPUSD candle data...")
    df = load_all_candles()
    print(f"Loaded {len(df)} candles across {df['timestamp'].dt.date.nunique()} days")

    print("Loading briefing index...")
    briefing_index = load_briefing_index()
    print(f"Loaded {len(briefing_index)} briefings")
    print()

    print("Scanning signals...")
    lp_signals, all_signals = find_signals(df, briefing_index)
    print(f"Found {len(all_signals)} total BB pierce signals, {len(lp_signals)} near LP levels")

    all_df = pd.DataFrame(all_signals)
    lp_df = pd.DataFrame(lp_signals)

    # Overall comparison
    print("\n" + "=" * 70)
    print("  SWEEP LEVEL VALIDATOR — LP Confluence vs Unfiltered (GBPUSD)")
    print("=" * 70)
    print(f"  Data: {all_df['date'].min()} -> {all_df['date'].max()}")
    print(f"  LP tolerance: {LEVEL_TOLERANCE} pips")

    all_stats = compute_stats(all_df, "All BB Pierce")
    lp_stats = compute_stats(lp_df, "LP Confluence")
    print_comparison(all_stats, lp_stats)

    # Bias-aligned subsets
    if not all_df.empty:
        all_aligned = all_df[all_df["bias_aligned"]]
        lp_aligned = lp_df[lp_df["bias_aligned"]] if not lp_df.empty else pd.DataFrame()

        print(f"\n  BIAS-ALIGNED ONLY")
        all_ba_stats = compute_stats(all_aligned, "All + Bias")
        lp_ba_stats = compute_stats(lp_aligned, "LP + Bias")
        print_comparison(all_ba_stats, lp_ba_stats)

    # Session breakdowns for LP-filtered signals
    if not lp_df.empty:
        london = lp_df[lp_df["session"] == "London"]
        ny = lp_df[lp_df["session"] == "NY"]
        print_block("LP CONFLUENCE — LONDON (06:00-12:00 UTC)", london)
        print_block("LP CONFLUENCE — NEW YORK (12:00-16:00 UTC)", ny)

        # Bias-aligned LP by session
        lp_ba = lp_df[lp_df["bias_aligned"]]
        if not lp_ba.empty:
            london_ba = lp_ba[lp_ba["session"] == "London"]
            ny_ba = lp_ba[lp_ba["session"] == "NY"]
            print_block("LP + BIAS-ALIGNED — LONDON", london_ba)
            print_block("LP + BIAS-ALIGNED — NEW YORK", ny_ba)

    print("\n" + "=" * 70)

    # Save results
    results = {
        "data_range": {"start": all_df["date"].min() if not all_df.empty else None,
                       "end": all_df["date"].max() if not all_df.empty else None},
        "lp_tolerance_pips": LEVEL_TOLERANCE,
        "unfiltered": all_stats,
        "lp_confluence": lp_stats,
        "bias_aligned_unfiltered": compute_stats(all_aligned, "All+Bias") if not all_df.empty else {},
        "bias_aligned_lp": compute_stats(lp_aligned, "LP+Bias") if not lp_df.empty else {},
        "all_signals": all_signals,
        "lp_signals": lp_signals,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
