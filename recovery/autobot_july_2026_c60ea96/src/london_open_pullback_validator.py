#!/usr/bin/env python3
"""
london_open_pullback_validator.py — Backtest the London open EMA pullback pattern.

Scans GBPUSD 5-min candles for:
1. Opening thrust: >= 10p combined move in first 30 min after 07:00 BST
2. EMA pullback: price within 2 pips of EMA 8 or 13 within 6 candles
3. Rejection candle: closes in thrust direction, body >= 40% of range

Entry on rejection close. SL at rejection extreme + 3p. Targets: 20/30/40p.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
from indicators import add_indicators, IndicatorsConfig, ema

CANDLE_DIR = Path("/opt/tradingbot/data/candles/GBPUSD")
OUTPUT_PATH = Path("/opt/tradingbot/data/london_pullback_validation_results.json")

CFG = IndicatorsConfig(bb_period=20, bb_std=2.0, macd_fast=35, macd_slow=45, macd_signal=30)

MIN_THRUST_PIPS = 10
THRUST_WINDOW_MIN = 30  # minutes after London open
EMA_TOLERANCE = 2  # pips
PULLBACK_CANDLES = 6
MIN_BODY_PCT = 0.40
SL_BUFFER = 3
TARGETS = [20, 30, 40]
LOOKAHEAD = 20


def load_candles() -> pd.DataFrame:
    frames = []
    for f in sorted(CANDLE_DIR.glob("*.csv")):
        df = pd.read_csv(f)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        frames.append(df)
    if not frames:
        print("ERROR: No candle files"); sys.exit(1)
    combined = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    enriched = add_indicators(combined, config=CFG)
    # Add EMA 8 and 13
    close = pd.to_numeric(enriched["close"], errors="coerce").astype(float)
    for p in (8, 13):
        col = f"EMA_{p}"
        if col not in enriched.columns:
            enriched[col] = ema(close, p)
    return enriched


def is_bst(ts) -> bool:
    return ts.month >= 4 or (ts.month == 3 and ts.day >= 29)


def to_bst_minutes(ts) -> int:
    bst_h = ts.hour + (1 if is_bst(ts) else 0)
    return bst_h * 60 + ts.minute


def find_patterns(df: pd.DataFrame) -> list[dict]:
    signals = []
    n = len(df)
    dates = sorted(df["timestamp"].dt.date.unique())

    for d in dates:
        day_mask = df["timestamp"].dt.date == d
        day_indices = df.index[day_mask].tolist()
        if len(day_indices) < 15:
            continue

        # Find London open time
        month = d.month
        day_num = d.day
        london_utc_h = 6 if (month >= 4 or (month == 3 and day_num >= 29)) else 7

        # Get candles from London open onward
        london_start = pd.Timestamp(d, tz="utc").replace(hour=london_utc_h, minute=0)
        london_mask = (df["timestamp"] >= london_start) & day_mask
        london_indices = df.index[london_mask].tolist()

        if len(london_indices) < THRUST_WINDOW_MIN // 5 + PULLBACK_CANDLES:
            continue

        # Phase 1: detect thrust in first 30 minutes (6 candles)
        thrust_end = min(len(london_indices), THRUST_WINDOW_MIN // 5)
        thrust_indices = london_indices[:thrust_end]

        first_open = df.at[thrust_indices[0], "open"]

        # Try each candle as thrust endpoint (at least 2 candles)
        best_thrust = None
        for t_end in range(1, len(thrust_indices)):
            t_close = df.at[thrust_indices[t_end], "close"]
            move = t_close - first_open
            move_pips = abs(move)
            if move_pips >= MIN_THRUST_PIPS:
                direction = "BUY" if move > 0 else "SELL"
                if best_thrust is None or move_pips > best_thrust["pips"]:
                    best_thrust = {
                        "direction": direction,
                        "pips": move_pips,
                        "end_idx": thrust_indices[t_end],
                        "end_pos": t_end,
                    }

        if best_thrust is None:
            continue

        # Phase 2: scan next PULLBACK_CANDLES for EMA touch + rejection
        search_start = best_thrust["end_pos"] + 1
        search_end = min(search_start + PULLBACK_CANDLES, len(london_indices))

        for p in range(search_start, search_end):
            idx = london_indices[p]
            if idx >= n - LOOKAHEAD:
                continue

            close_p = df.at[idx, "close"]
            high_p = df.at[idx, "high"]
            low_p = df.at[idx, "low"]
            open_p = df.at[idx, "open"]
            ema8 = df.at[idx, "EMA_8"] if "EMA_8" in df.columns else None
            ema13 = df.at[idx, "EMA_13"] if "EMA_13" in df.columns else None

            if pd.isna(ema8) and pd.isna(ema13):
                continue

            # Check pullback to EMA
            near_ema = False
            ema_name = None
            ema_val = None

            if best_thrust["direction"] == "BUY":
                if ema8 is not None and not pd.isna(ema8) and low_p <= ema8 + EMA_TOLERANCE:
                    near_ema = True; ema_name = "EMA_8"; ema_val = ema8
                elif ema13 is not None and not pd.isna(ema13) and low_p <= ema13 + EMA_TOLERANCE:
                    near_ema = True; ema_name = "EMA_13"; ema_val = ema13
            else:
                if ema8 is not None and not pd.isna(ema8) and high_p >= ema8 - EMA_TOLERANCE:
                    near_ema = True; ema_name = "EMA_8"; ema_val = ema8
                elif ema13 is not None and not pd.isna(ema13) and high_p >= ema13 - EMA_TOLERANCE:
                    near_ema = True; ema_name = "EMA_13"; ema_val = ema13

            if not near_ema:
                continue

            # Check rejection candle
            c_range = high_p - low_p
            if c_range <= 0:
                continue
            c_body = abs(close_p - open_p)
            c_body_pct = c_body / c_range

            is_rejection = False
            if best_thrust["direction"] == "BUY" and close_p > open_p and c_body_pct >= MIN_BODY_PCT:
                is_rejection = True
            elif best_thrust["direction"] == "SELL" and close_p < open_p and c_body_pct >= MIN_BODY_PCT:
                is_rejection = True

            if not is_rejection:
                continue

            # ENTRY found — measure outcome
            entry_price = close_p
            entry_ts = df.at[idx, "timestamp"]
            direction = best_thrust["direction"]

            if direction == "BUY":
                sl_pips = entry_price - low_p + SL_BUFFER
            else:
                sl_pips = high_p - entry_price + SL_BUFFER

            if sl_pips <= 0:
                sl_pips = SL_BUFFER

            max_adverse = 0.0
            max_favour = 0.0
            hit_targets = {t: False for t in TARGETS}
            hit_sl = False

            for k in range(idx + 1, min(idx + 1 + LOOKAHEAD, n)):
                if direction == "BUY":
                    adverse = entry_price - df.at[k, "low"]
                    favour = df.at[k, "high"] - entry_price
                else:
                    adverse = df.at[k, "high"] - entry_price
                    favour = entry_price - df.at[k, "low"]

                max_adverse = max(max_adverse, adverse)
                max_favour = max(max_favour, favour)

                if adverse >= sl_pips and not hit_sl:
                    hit_sl = True
                for t in TARGETS:
                    if favour >= t and not hit_targets[t]:
                        hit_targets[t] = True

            if hit_sl and not any(hit_targets.values()):
                pnl = -sl_pips
            elif any(hit_targets.values()):
                pnl = max(t for t in TARGETS if hit_targets[t])
            else:
                final = df.at[min(idx + LOOKAHEAD, n - 1), "close"]
                pnl = (final - entry_price) if direction == "BUY" else (entry_price - final)

            signals.append({
                "date": str(d),
                "timestamp": str(entry_ts),
                "hour": int(entry_ts.hour),
                "direction": direction,
                "thrust_pips": round(best_thrust["pips"], 1),
                "ema_touched": ema_name,
                "ema_value": round(ema_val, 2),
                "body_pct": round(c_body_pct, 3),
                "candles_to_pullback": p - best_thrust["end_pos"],
                "entry_price": round(entry_price, 2),
                "sl_pips": round(sl_pips, 2),
                "hit_20p": hit_targets[20],
                "hit_30p": hit_targets[30],
                "hit_40p": hit_targets[40],
                "hit_sl": hit_sl,
                "max_adverse_excursion": round(max_adverse, 2),
                "max_favourable_excursion": round(max_favour, 2),
                "pnl_pips": round(pnl, 2),
            })
            break  # One pattern per day

    return signals


def main():
    print("Loading GBPUSD candle data...")
    df = load_candles()
    print(f"Loaded {len(df)} candles across {df['timestamp'].dt.date.nunique()} days")
    print()

    print("Scanning for London open pullback patterns...")
    signals = find_patterns(df)

    if not signals:
        print("No patterns found.")
        return

    sdf = pd.DataFrame(signals)
    total = len(sdf)
    days_total = df["timestamp"].dt.date.nunique()

    wr_20 = sdf["hit_20p"].sum() / total * 100
    wr_30 = sdf["hit_30p"].sum() / total * 100
    wr_40 = sdf["hit_40p"].sum() / total * 100
    sl_rate = sdf["hit_sl"].sum() / total * 100
    avg_pnl = sdf["pnl_pips"].mean()
    avg_mae = sdf["max_adverse_excursion"].mean()
    avg_mfe = sdf["max_favourable_excursion"].mean()
    avg_sl = sdf["sl_pips"].mean()
    avg_thrust = sdf["thrust_pips"].mean()

    print("=" * 65)
    print("  LONDON OPEN PULLBACK VALIDATOR — GBPUSD 5M")
    print("=" * 65)
    print(f"  Data:   {sdf['date'].min()} -> {sdf['date'].max()}")
    print(f"  Pattern frequency: {total}/{days_total} days ({total/days_total*100:.0f}%)")
    print()
    print("  PATTERN STATS")
    print(f"  {'Avg thrust size:':<24} {avg_thrust:>7.1f}p")
    print(f"  {'Avg dynamic SL:':<24} {avg_sl:>7.1f}p")
    print(f"  {'Avg candles to PB:':<24} {sdf['candles_to_pullback'].mean():>7.1f}")

    # EMA breakdown
    ema_counts = sdf["ema_touched"].value_counts()
    for ema_name, count in ema_counts.items():
        print(f"  {'  ' + ema_name + ' touches:':<24} {count:>5}")

    print()
    print("  RESULTS")
    print(f"  {'20p target:':<18} {wr_20:>6.1f}%  ({int(sdf['hit_20p'].sum())}/{total})")
    print(f"  {'30p target:':<18} {wr_30:>6.1f}%  ({int(sdf['hit_30p'].sum())}/{total})")
    print(f"  {'40p target:':<18} {wr_40:>6.1f}%  ({int(sdf['hit_40p'].sum())}/{total})")
    print(f"  {'SL hit:':<18} {sl_rate:>6.1f}%  ({int(sdf['hit_sl'].sum())}/{total})")
    print()
    print(f"  {'Avg pip capture:':<22} {avg_pnl:>+7.2f}")
    print(f"  {'Avg MAE:':<22} {avg_mae:>7.2f}")
    print(f"  {'Avg MFE:':<22} {avg_mfe:>7.2f}")

    if total > 0:
        best = sdf.loc[sdf["pnl_pips"].idxmax()]
        worst = sdf.loc[sdf["pnl_pips"].idxmin()]
        print(f"  {'Best:':<22} {best['pnl_pips']:>+7.2f}p  ({best['date']})")
        print(f"  {'Worst:':<22} {worst['pnl_pips']:>+7.2f}p  ({worst['date']})")

    # Direction breakdown
    for d in ("BUY", "SELL"):
        subset = sdf[sdf["direction"] == d]
        if len(subset) > 0:
            print(f"\n  {d}: {len(subset)} signals, "
                  f"WR(20p)={subset['hit_20p'].mean()*100:.1f}%, "
                  f"AvgPnL={subset['pnl_pips'].mean():+.2f}p")

    # Per-trade detail
    print()
    print(f"  {'Date':<12} {'Dir':<5} {'Thrust':>7} {'EMA':>6} {'Body%':>6} {'SL':>5} {'PnL':>7} {'Result'}")
    print(f"  {'─'*12} {'─'*5} {'─'*7} {'─'*6} {'─'*6} {'─'*5} {'─'*7} {'─'*8}")
    for _, row in sdf.iterrows():
        result = "SL" if row["hit_sl"] and not row["hit_20p"] else (
            "TP40" if row["hit_40p"] else "TP30" if row["hit_30p"] else "TP20" if row["hit_20p"] else "EXP")
        print(f"  {row['date']:<12} {row['direction']:<5} {row['thrust_pips']:>6.1f}p "
              f"{row['ema_touched'][-1:]:>5} {row['body_pct']*100:>5.0f}% "
              f"{row['sl_pips']:>4.0f}p {row['pnl_pips']:>+6.1f}p  {result}")

    print("=" * 65)

    # Save
    results = {
        "pattern_frequency": f"{total}/{days_total}",
        "total_signals": total,
        "avg_thrust_pips": round(avg_thrust, 1),
        "avg_sl_pips": round(avg_sl, 1),
        "target_hit_rates": {
            "20p": round(wr_20, 1),
            "30p": round(wr_30, 1),
            "40p": round(wr_40, 1),
        },
        "sl_rate": round(sl_rate, 1),
        "avg_pnl": round(avg_pnl, 2),
        "avg_mae": round(avg_mae, 2),
        "avg_mfe": round(avg_mfe, 2),
        "signals": signals,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
