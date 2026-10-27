"""
Investigation A: S1/R1 directional filter on BB Bounce.

  1. Replay BB Bounce core 2-candle pierce+rejection signals 2024-01-01 .. 2026-10-26.
  2. Attach daily pivots (prior day HLC → PP/S1-S3/R1-R3), production formula.
  3. Measure outcomes for a grid of (SL, TP) pairs.
  4. Apply the S1/R1 permission rule:
        price > R1 → BLOCK BUY  (allow SELL)
        price < S1 → BLOCK SELL (allow BUY)
        between   → both allowed
     Treat exact boundary as inside range (spec default).
  5. Compute per-config metrics: trades, wins, win rate, PF, net pips, DD,
     prevented wins, prevented losses. Chrono TVT splits.
  6. Emit CSVs for the research report.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data_loader import load_m5
from bb_replay import replay_bb_signals
from outcomes import measure_outcomes
from pivots import daily_hlc, pivots_for_each_day, attach_pivots

OUT = Path("/home/autobot/research/gbpusd_bb_bounce_20261027/data_out")
OUT.mkdir(parents=True, exist_ok=True)

START = date(2024, 1, 1)
END = date(2026, 10, 26)

# Primary outcome pair; sensitivity across the grid stored for reporting.
SL_TP_PAIRS = [
    (12.0, 20.0),  # strategy's production SL + a modest TP
    (12.0, 30.0),  # BB Bounce 2.5R
    (20.0, 20.0),  # 1:1 risk-reward
    (20.0, 30.0),  # 1.5R
    (20.0, 40.0),  # 2R
]
PRIMARY_SL, PRIMARY_TP = 20.0, 30.0  # for headline numbers

TRAIN_END = pd.Timestamp("2025-07-01", tz="UTC")
VAL_END = pd.Timestamp("2026-03-01", tz="UTC")


def split_of(ts: pd.Timestamp) -> str:
    if ts < TRAIN_END: return "TRAIN"
    if ts < VAL_END: return "VAL"
    return "TEST"


def filter_s1r1(row) -> str:
    """Return 'ALLOW' / 'BLOCK' / 'NO_PIVOT' per the S1/R1 rule.

    direction: 'LONG' = BUY, 'SHORT' = SELL
    """
    if pd.isna(row.get("S1")) or pd.isna(row.get("R1")):
        return "NO_PIVOT"
    px = row["fire_bar_close"]
    s1 = row["S1"]; r1 = row["R1"]
    if row["direction"] == "LONG":
        return "BLOCK" if px > r1 else "ALLOW"
    else:  # SHORT
        return "BLOCK" if px < s1 else "ALLOW"


def metrics(trades: pd.DataFrame, pnl_col: str) -> dict:
    if len(trades) == 0:
        return dict(n=0, wins=0, losses=0, ambig=0, win_rate=float("nan"),
                    gross_profit=0.0, gross_loss=0.0, net_pips=0.0,
                    profit_factor=float("nan"), avg_pips=float("nan"),
                    max_dd=float("nan"))
    pnl = trades[pnl_col].values
    oc_col = pnl_col.replace("pnl_pips_", "outcome_")
    wins = (trades[oc_col] == "WIN").sum()
    losses = (trades[oc_col] == "LOSS").sum()
    ambig = (trades[oc_col] == "AMBIG").sum()
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()
    net = pnl.sum()
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    # Max drawdown over chronological equity curve
    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak).min() if len(equity) else 0.0
    return dict(
        n=int(len(trades)),
        wins=int(wins), losses=int(losses), ambig=int(ambig),
        win_rate=float(wins / len(trades)),
        gross_profit=float(gross_profit),
        gross_loss=float(gross_loss),
        net_pips=float(net),
        profit_factor=float(pf),
        avg_pips=float(np.mean(pnl)),
        max_dd=float(dd),
    )


def main():
    print(f"Loading M5 {START}..{END} ...")
    m5 = load_m5(START, END)
    print(f"  M5 bars: {len(m5):,}")

    print("Replaying BB-bounce core 2-candle pattern ...")
    sig = replay_bb_signals(m5)
    sig = sig.drop_duplicates(subset=["fire_time", "direction"]).reset_index(drop=True)
    sig["fire_time"] = pd.to_datetime(sig["fire_time"], utc=True)
    sig["setup_time"] = pd.to_datetime(sig["setup_time"], utc=True)
    print(f"  Signals: {len(sig):,}")

    print("Computing daily pivots ...")
    hlc = daily_hlc(m5)
    pv = pivots_for_each_day(hlc)
    sig = attach_pivots(sig, pv)
    print(f"  Pivots computed: {len(pv):,} dates")

    print("Measuring outcomes across SL/TP grid ...")
    for sl, tp in SL_TP_PAIRS:
        sig = measure_outcomes(sig, m5, sl, tp, max_bars=48)
        print(f"  sl={sl:>5.1f} tp={tp:>5.1f}: {(sig[f'outcome_sl{int(sl)}_tp{int(tp)}']=='WIN').sum()} wins, "
              f"{(sig[f'outcome_sl{int(sl)}_tp{int(tp)}']=='LOSS').sum()} losses")

    sig["s1r1_decision"] = sig.apply(filter_s1r1, axis=1)
    # Half-filter: block SELL below S1 only (the empirically costly leg)
    def filter_sell_below_s1_only(row):
        if pd.isna(row.get("S1")): return "NO_PIVOT"
        if row["direction"] == "SHORT" and row["fire_bar_close"] < row["S1"]:
            return "BLOCK"
        return "ALLOW"
    sig["half_filter_decision"] = sig.apply(filter_sell_below_s1_only, axis=1)
    sig["split"] = sig["fire_time"].apply(split_of)
    sig["day_of_week"] = sig["fire_time"].dt.day_name()
    sig["price_rel_pivots"] = sig.apply(
        lambda r: "ABOVE_R1" if (not pd.isna(r["R1"]) and r["fire_bar_close"] > r["R1"]) else
                   "BELOW_S1" if (not pd.isna(r["S1"]) and r["fire_bar_close"] < r["S1"]) else
                   "INSIDE_S1R1" if not pd.isna(r["S1"]) else "NO_PIVOT",
        axis=1,
    )
    sig.to_csv(OUT / "signals_with_outcomes.csv", index=False)
    print(f"  wrote signals_with_outcomes.csv  ({len(sig):,} rows)")

    # Metrics table
    rows = []
    for sl, tp in SL_TP_PAIRS:
        pnl_col = f"pnl_pips_sl{int(sl)}_tp{int(tp)}"
        for split in ("TRAIN", "VAL", "TEST", "ALL"):
            df = sig if split == "ALL" else sig[sig["split"] == split]
            if len(df) == 0:
                continue
            baseline = df  # Config A
            variant = df[df["s1r1_decision"] != "BLOCK"]  # Config B
            half = df[df["half_filter_decision"] != "BLOCK"]  # Config B'
            m_a = metrics(baseline, pnl_col); m_a["config"] = "A_baseline"
            m_b = metrics(variant, pnl_col); m_b["config"] = "B_s1r1_filter"
            m_h = metrics(half, pnl_col); m_h["config"] = "Bprime_half_filter"
            for m in (m_a, m_b, m_h):
                m["sl"] = sl; m["tp"] = tp; m["split"] = split
                rows.append(m)
    met = pd.DataFrame(rows)
    met.to_csv(OUT / "config_metrics.csv", index=False)
    print(f"  wrote config_metrics.csv  ({len(met):,} rows)")

    # Per-direction × pivot position × split breakdown (primary SL/TP)
    pcol = f"pnl_pips_sl{int(PRIMARY_SL)}_tp{int(PRIMARY_TP)}"
    bd_rows = []
    for split in ("TRAIN", "VAL", "TEST", "ALL"):
        d = sig if split == "ALL" else sig[sig["split"] == split]
        for direction in ("LONG", "SHORT"):
            for rel in ("ABOVE_R1", "INSIDE_S1R1", "BELOW_S1"):
                sub = d[(d["direction"] == direction) & (d["price_rel_pivots"] == rel)]
                m = metrics(sub, pcol)
                m.update(split=split, direction=direction, position=rel)
                bd_rows.append(m)
    bd = pd.DataFrame(bd_rows)
    bd.to_csv(OUT / "direction_position_breakdown.csv", index=False)
    print(f"  wrote direction_position_breakdown.csv")

    print("\n--- summary (sl=20 tp=30, ALL split) ---")
    m_a = metrics(sig, pcol)
    m_b = metrics(sig[sig["s1r1_decision"] != "BLOCK"], pcol)
    print(f"  Config A (baseline): n={m_a['n']}, win_rate={m_a['win_rate']:.1%}, net={m_a['net_pips']:+.1f}p, PF={m_a['profit_factor']:.2f}, DD={m_a['max_dd']:.1f}")
    print(f"  Config B (S1/R1):    n={m_b['n']}, win_rate={m_b['win_rate']:.1%}, net={m_b['net_pips']:+.1f}p, PF={m_b['profit_factor']:.2f}, DD={m_b['max_dd']:.1f}")
    blocked = sig[sig["s1r1_decision"] == "BLOCK"]
    blocked_wins = (blocked[f"outcome_sl{int(PRIMARY_SL)}_tp{int(PRIMARY_TP)}"] == "WIN").sum()
    blocked_losses = (blocked[f"outcome_sl{int(PRIMARY_SL)}_tp{int(PRIMARY_TP)}"] == "LOSS").sum()
    print(f"  Trades prevented by filter: {len(blocked)} ({blocked_wins} would-be wins, {blocked_losses} would-be losses)")

    print("Done.")


if __name__ == "__main__":
    main()
