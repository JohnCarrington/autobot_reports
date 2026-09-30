#!/usr/bin/env python3
"""
sequence_trade_validator.py — Tests sweep-then-reversal sequences against candle data.

Uses stored briefing JSONs with session_expectation=LIQUIDITY_HUNT and matching
scenario labels. Validates whether the predicted sweep happened, whether the
reversal followed, and measures pip capture.
"""

import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
from indicators import add_indicators, IndicatorsConfig

CANDLE_DIR = Path("/opt/tradingbot/data/candles")
BRIEFING_DIR = Path("/opt/tradingbot/logs")
OUTPUT_PATH = Path("/opt/tradingbot/data/sequence_validation_results.json")

CFG = IndicatorsConfig(
    bb_period=20, bb_std=2.0,
    macd_fast=35, macd_slow=45, macd_signal=30,
)
BB_UPPER = f"BB_UPPER_{CFG.bb_period}_{CFG.bb_std:g}"
BB_LOWER = f"BB_LOWER_{CFG.bb_period}_{CFG.bb_std:g}"

# Session time windows (UTC hours, inclusive start, exclusive end)
SESSION_WINDOWS = {
    "Asian":       (0, 7),
    "London":      (7, 12),
    "London_Open": (7, 10),
    "Mid-session": (10, 14),
    "NY":          (12, 17),
    "NY_Mid":      (14, 17),
}


def load_candles(symbol: str) -> pd.DataFrame:
    """Load all candle data for a symbol and add indicators."""
    sym_dir = CANDLE_DIR / symbol
    frames = []
    for f in sorted(sym_dir.glob("*.csv")):
        df = pd.read_csv(f)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return add_indicators(combined, config=CFG)


def load_qualifying_briefings() -> list[dict]:
    """Find all LIQUIDITY_HUNT briefings with sweep/liquidity scenarios."""
    results = []
    for f in sorted(BRIEFING_DIR.glob("briefing_*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue

        if data.get("session_expectation") != "LIQUIDITY_HUNT":
            continue

        scenarios = data.get("scenarios", [])
        sweep_scenario = None
        for s in scenarios:
            if re.search(r"sweep|liquidity", s.get("label", ""), re.I):
                sweep_scenario = s
                break
        if not sweep_scenario:
            continue

        # Extract sweep level: use liquidity_pools aligned with bias direction
        bias = str(data.get("session_bias", "")).upper()
        liq = data.get("liquidity_pools", {})
        plans = data.get("trading_plans", [])

        # Determine sweep level and reversal target
        if bias in ("BEARISH", "SHORT"):
            # Expect sweep of buy-side liquidity, then drop
            sweep_pool = liq.get("buy_side", [])
            sweep_direction = "UP"  # price sweeps up first
        elif bias in ("BULLISH", "LONG"):
            # Expect sweep of sell-side liquidity, then rise
            sweep_pool = liq.get("sell_side", [])
            sweep_direction = "DOWN"  # price sweeps down first
        else:
            # Neutral/unknown — try to infer from scenario
            if any(w in sweep_scenario.get("label", "").lower() for w in ["sell", "short", "bearish"]):
                sweep_pool = liq.get("buy_side", [])
                sweep_direction = "UP"
            else:
                sweep_pool = liq.get("sell_side", [])
                sweep_direction = "DOWN"

        if not sweep_pool:
            continue

        # Nearest sweep level (first in pool is typically nearest from briefing)
        # Use the scenario target as reversal target
        reversal_target = sweep_scenario.get("target")
        if reversal_target is None:
            continue

        # Try to get sweep level from scenario trigger text (first number)
        trigger_nums = re.findall(r"\d{4,5}\.?\d*", sweep_scenario.get("trigger", ""))
        if trigger_nums:
            sweep_level = float(trigger_nums[0])
        else:
            # Fallback: nearest liquidity pool level
            sweep_level = float(sweep_pool[-1]) if sweep_direction == "UP" else float(sweep_pool[-1])

        # Get plan targets for comparison
        plan_targets = []
        for p in plans:
            if re.search(r"sweep|liquidity", p.get("label", ""), re.I):
                plan_targets = p.get("targets", [])
                break

        # Parse date and session from filename
        fname = f.name
        m = re.match(r"briefing_(\w+)_(\d{4}-\d{2}-\d{2})_(.+)\.json", fname)
        if not m:
            continue

        results.append({
            "file": fname,
            "symbol": m.group(1),
            "date": m.group(2),
            "session": m.group(3),
            "bias": bias,
            "sweep_direction": sweep_direction,
            "sweep_level": float(sweep_level),
            "reversal_target": float(reversal_target),
            "plan_targets": [float(t) for t in plan_targets],
            "scenario_probability": sweep_scenario.get("probability"),
            "bb_upper": data.get("bb_upper"),
            "bb_lower": data.get("bb_lower"),
        })

    return results


def get_session_candles(df: pd.DataFrame, date_str: str, session: str) -> pd.DataFrame:
    """Filter candles for a specific date and session window."""
    date = pd.Timestamp(date_str, tz="utc")
    window = SESSION_WINDOWS.get(session)
    if window is None:
        # Unknown session — use full day
        mask = df["timestamp"].dt.date == date.date()
        return df[mask].copy()

    start_h, end_h = window
    start = date.replace(hour=start_h, minute=0, second=0)
    end = date.replace(hour=end_h, minute=0, second=0)
    mask = (df["timestamp"] >= start) & (df["timestamp"] < end)
    return df[mask].copy()


def evaluate_sequence(candles: pd.DataFrame, briefing: dict) -> dict:
    """Evaluate a single sweep-then-reversal sequence against candle data."""
    if candles.empty or len(candles) < 5:
        return {"status": "no_data"}

    sweep_level = briefing["sweep_level"]
    reversal_target = briefing["reversal_target"]
    sweep_dir = briefing["sweep_direction"]
    bb_upper_val = briefing.get("bb_upper")
    bb_lower_val = briefing.get("bb_lower")

    # Track: did price reach sweep level?
    sweep_hit = False
    sweep_idx = None
    sweep_price = None
    first_bb_touch_idx = None

    for i in range(len(candles)):
        row = candles.iloc[i]

        # Track first BB touch
        if first_bb_touch_idx is None:
            candle_bb_upper = row.get(BB_UPPER)
            candle_bb_lower = row.get(BB_LOWER)
            if not pd.isna(candle_bb_upper) and not pd.isna(candle_bb_lower):
                if sweep_dir == "UP" and row["high"] >= candle_bb_upper:
                    first_bb_touch_idx = i
                elif sweep_dir == "DOWN" and row["low"] <= candle_bb_lower:
                    first_bb_touch_idx = i

        # Check sweep hit
        if not sweep_hit:
            if sweep_dir == "UP" and row["high"] >= sweep_level:
                sweep_hit = True
                sweep_idx = i
                sweep_price = row["high"]
            elif sweep_dir == "DOWN" and row["low"] <= sweep_level:
                sweep_hit = True
                sweep_idx = i
                sweep_price = row["low"]

    # Measure reversal after sweep
    reversal_hit = False
    reversal_pips = 0.0
    max_reversal_excursion = 0.0
    sweep_to_reversal_candles = None

    if sweep_hit and sweep_idx is not None:
        post_sweep = candles.iloc[sweep_idx:]
        for j in range(len(post_sweep)):
            row = post_sweep.iloc[j]
            if sweep_dir == "UP":
                # After upward sweep, expect reversal DOWN
                excursion = sweep_price - row["low"]
                target_distance = sweep_price - reversal_target
            else:
                # After downward sweep, expect reversal UP
                excursion = row["high"] - sweep_price
                target_distance = reversal_target - sweep_price

            max_reversal_excursion = max(max_reversal_excursion, excursion)

            if target_distance > 0 and excursion >= target_distance:
                reversal_hit = True
                sweep_to_reversal_candles = j
                reversal_pips = target_distance
                break

        if not reversal_hit:
            reversal_pips = max_reversal_excursion

    # Measure BB touch entry vs sweep entry comparison
    bb_entry_pips = 0.0
    if first_bb_touch_idx is not None and sweep_hit:
        bb_row = candles.iloc[first_bb_touch_idx]
        if sweep_dir == "UP":
            bb_entry_price = bb_row["high"]
            # Measure from BB touch to best reversal point after sweep
            post_bb = candles.iloc[first_bb_touch_idx:]
            bb_best = 0.0
            for _, r in post_bb.iterrows():
                bb_best = max(bb_best, bb_entry_price - r["low"])
            bb_entry_pips = bb_best
        else:
            bb_entry_price = bb_row["low"]
            post_bb = candles.iloc[first_bb_touch_idx:]
            bb_best = 0.0
            for _, r in post_bb.iterrows():
                bb_best = max(bb_best, r["high"] - bb_entry_price)
            bb_entry_pips = bb_best

    sweep_entry_pips = max_reversal_excursion if sweep_hit else 0.0

    return {
        "status": "evaluated",
        "sweep_hit": sweep_hit,
        "sweep_candle_index": int(sweep_idx) if sweep_idx is not None else None,
        "reversal_hit": reversal_hit,
        "reversal_pips": round(reversal_pips, 2),
        "max_reversal_excursion": round(max_reversal_excursion, 2),
        "sweep_to_reversal_candles": sweep_to_reversal_candles,
        "bb_touch_found": first_bb_touch_idx is not None,
        "bb_entry_capture_pips": round(bb_entry_pips, 2),
        "sweep_entry_capture_pips": round(sweep_entry_pips, 2),
    }


def main():
    print("Loading qualifying briefings...")
    briefings = load_qualifying_briefings()
    print(f"Found {len(briefings)} LIQUIDITY_HUNT briefings with sweep scenarios")

    # Load candle data per symbol (cache)
    symbols = sorted(set(b["symbol"] for b in briefings))
    print(f"Loading candle data for: {', '.join(symbols)}")
    candle_cache = {}
    for sym in symbols:
        candle_cache[sym] = load_candles(sym)
        print(f"  {sym}: {len(candle_cache[sym])} candles")
    print()

    # Evaluate each briefing
    results_list = []
    for b in briefings:
        sym = b["symbol"]
        df = candle_cache.get(sym)
        if df is None or df.empty:
            continue
        session_candles = get_session_candles(df, b["date"], b["session"])
        outcome = evaluate_sequence(session_candles, b)
        results_list.append({**b, **outcome})

    evaluated = [r for r in results_list if r["status"] == "evaluated"]
    no_data = [r for r in results_list if r["status"] == "no_data"]

    if not evaluated:
        print("No briefings could be evaluated against candle data.")
        return

    df = pd.DataFrame(evaluated)

    # Overall stats
    total = len(df)
    sweep_count = df["sweep_hit"].sum()
    sweep_rate = sweep_count / total * 100

    sweep_df = df[df["sweep_hit"]]
    reversal_count = sweep_df["reversal_hit"].sum() if len(sweep_df) > 0 else 0
    reversal_rate = reversal_count / len(sweep_df) * 100 if len(sweep_df) > 0 else 0
    full_sequence_rate = reversal_count / total * 100

    avg_reversal_pips = sweep_df["reversal_pips"].mean() if len(sweep_df) > 0 else 0
    avg_mre = sweep_df["max_reversal_excursion"].mean() if len(sweep_df) > 0 else 0

    # BB vs sweep entry comparison
    both_entries = df[(df["sweep_hit"]) & (df["bb_touch_found"])]
    avg_bb_capture = both_entries["bb_entry_capture_pips"].mean() if len(both_entries) > 0 else 0
    avg_sweep_capture = both_entries["sweep_entry_capture_pips"].mean() if len(both_entries) > 0 else 0

    # Pair breakdown
    pair_stats = df.groupby("symbol").agg(
        count=("sweep_hit", "size"),
        sweep_rate=("sweep_hit", "mean"),
        reversal_rate_all=("reversal_hit", "mean"),
        avg_rev_pips=("reversal_pips", "mean"),
        avg_mre=("max_reversal_excursion", "mean"),
    ).reset_index()
    pair_stats["sweep_rate"] = (pair_stats["sweep_rate"] * 100).round(1)
    pair_stats["reversal_rate_all"] = (pair_stats["reversal_rate_all"] * 100).round(1)
    pair_stats["avg_rev_pips"] = pair_stats["avg_rev_pips"].round(1)
    pair_stats["avg_mre"] = pair_stats["avg_mre"].round(1)

    # Session breakdown
    session_stats = df.groupby("session").agg(
        count=("sweep_hit", "size"),
        sweep_rate=("sweep_hit", "mean"),
        reversal_rate_all=("reversal_hit", "mean"),
        avg_rev_pips=("reversal_pips", "mean"),
    ).reset_index()
    session_stats["sweep_rate"] = (session_stats["sweep_rate"] * 100).round(1)
    session_stats["reversal_rate_all"] = (session_stats["reversal_rate_all"] * 100).round(1)
    session_stats["avg_rev_pips"] = session_stats["avg_rev_pips"].round(1)

    # Print report
    print("=" * 70)
    print("  SEQUENCE TRADE VALIDATOR — Sweep-Then-Reversal Analysis")
    print("=" * 70)
    print(f"  Briefings evaluated:   {total}  (skipped {len(no_data)} with no candle data)")
    print(f"  Date range:            {df['date'].min()} → {df['date'].max()}")
    print()
    print("  SEQUENCE COMPLETION RATES")
    print(f"  {'Sweep hit rate:':<30} {sweep_rate:>6.1f}%  ({sweep_count}/{total})")
    print(f"  {'Reversal after sweep:':<30} {reversal_rate:>6.1f}%  ({reversal_count}/{int(sweep_count)})")
    print(f"  {'Full sequence (sweep+rev):':<30} {full_sequence_rate:>6.1f}%  ({reversal_count}/{total})")
    print()
    print("  PIP CAPTURE (sweep trades only)")
    print(f"  {'Avg reversal pips:':<30} {avg_reversal_pips:>7.1f}")
    print(f"  {'Avg max reversal excursion:':<30} {avg_mre:>7.1f}")
    if len(both_entries) > 0:
        print()
        print("  ENTRY COMPARISON (BB touch vs sweep completion)")
        print(f"  {'Avg capture from BB touch:':<30} {avg_bb_capture:>7.1f}p")
        print(f"  {'Avg capture from sweep point:':<30} {avg_sweep_capture:>7.1f}p")
        diff = avg_bb_capture - avg_sweep_capture
        better = "BB touch" if diff > 0 else "Sweep completion"
        print(f"  {'Edge:':<30} {better} by {abs(diff):.1f}p")
    print()
    print("  PAIR BREAKDOWN")
    print(f"  {'Pair':<10} {'Count':>5} {'Sweep%':>8} {'Rev%':>8} {'AvgPips':>8} {'AvgMRE':>8}")
    print(f"  {'─' * 10} {'─' * 5} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 8}")
    for _, row in pair_stats.sort_values("avg_mre", ascending=False).iterrows():
        print(f"  {row['symbol']:<10} {int(row['count']):>4}  {row['sweep_rate']:>6.1f}%  {row['reversal_rate_all']:>6.1f}%  {row['avg_rev_pips']:>7.1f}  {row['avg_mre']:>7.1f}")
    print()
    print("  SESSION BREAKDOWN")
    print(f"  {'Session':<14} {'Count':>5} {'Sweep%':>8} {'Rev%':>8} {'AvgPips':>8}")
    print(f"  {'─' * 14} {'─' * 5} {'─' * 8} {'─' * 8} {'─' * 8}")
    for _, row in session_stats.sort_values("reversal_rate_all", ascending=False).iterrows():
        print(f"  {row['session']:<14} {int(row['count']):>4}  {row['sweep_rate']:>6.1f}%  {row['reversal_rate_all']:>6.1f}%  {row['avg_rev_pips']:>7.1f}")
    print("=" * 70)

    # Save results
    output = {
        "total_briefings_evaluated": total,
        "skipped_no_data": len(no_data),
        "date_range": {"start": df["date"].min(), "end": df["date"].max()},
        "sequence_rates": {
            "sweep_hit_rate": round(sweep_rate, 1),
            "reversal_after_sweep_rate": round(reversal_rate, 1),
            "full_sequence_rate": round(full_sequence_rate, 1),
            "sweep_count": int(sweep_count),
            "reversal_count": int(reversal_count),
        },
        "pip_capture": {
            "avg_reversal_pips": round(avg_reversal_pips, 1),
            "avg_max_reversal_excursion": round(avg_mre, 1),
        },
        "entry_comparison": {
            "avg_bb_touch_capture": round(avg_bb_capture, 1),
            "avg_sweep_entry_capture": round(avg_sweep_capture, 1),
            "better_entry": "bb_touch" if avg_bb_capture > avg_sweep_capture else "sweep_completion",
            "edge_pips": round(abs(avg_bb_capture - avg_sweep_capture), 1),
            "sample_size": len(both_entries),
        },
        "pair_breakdown": pair_stats.to_dict(orient="records"),
        "session_breakdown": session_stats.to_dict(orient="records"),
        "all_evaluations": evaluated,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
