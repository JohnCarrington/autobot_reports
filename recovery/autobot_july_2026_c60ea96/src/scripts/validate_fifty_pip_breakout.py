#!/usr/bin/env python3
"""scripts/validate_fifty_pip_breakout.py — detector validation gate.

Replays the production state machine against the analysis simulator's output
for a random sample of UTC trading days. Pass criterion (from prompt):
    same anchor candle, same direction triggered, same entry price,
    same SL/TP placement, same exit reason — ≤0.1p tolerance on prices,
    exact match on direction / exit_reason.

The fifty_pip_breakout module exits state machine on FIRE; the analysis
simulator continues walking ticks for TP/SL/BE/EOD. So we cross-check:

  - production tick_update fire row (date, side, entry, sl_abs, tp_abs)
        vs analysis CSV (date, side, entry_price, sl_level)
  - production-derived TP price (entry ± 50p) vs analysis-implied
        TP price (when exit_reason == 'tp')

Anchor high/low come from the cached 1H bars parquet (data_layer +
fifty_pip backtest), so we feed the strategy a synthetic 1-bar 5m df
representing the same anchor hour (high=anchor_high, low=anchor_low).
This isolates the test to the state-machine + trigger logic, not the
5m-aggregation correctness (which is a sub-pixel concern at 1-2p spreads).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import fifty_pip_breakout as fpb  # noqa: E402
from scripts.analysis.bb_clean_harness.data_layer import load_ticks  # noqa: E402
from scripts.analysis.fifty_pip.backtest import build_bars_1h  # noqa: E402

PAIR = "USDCAD"
MODE = "FIFTY_PIP_BREAKOUT_USDCAD_V4"
TRADES_CSV = REPO / "data" / "analysis" / "fifty_pip" / "extended" / "trades_USDCAD_V4_10p_BEhold.csv"
TOL = 0.1


def _synthetic_anchor_df(anchor_date: str, anchor_high: float, anchor_low: float
                         ) -> pd.DataFrame:
    """1-bar 5m DataFrame in the anchor window. The state machine aggregates
    over [07:00, 08:00) UTC and takes high.max(), low.min() — a single bar
    in that range with the analysis-cached high/low produces an exact match.
    """
    return pd.DataFrame({
        "time": [pd.Timestamp(f"{anchor_date} 07:30:00", tz="UTC")],
        "open": [(anchor_high + anchor_low) / 2.0],
        "high": [anchor_high],
        "low": [anchor_low],
        "close": [(anchor_high + anchor_low) / 2.0],
    })


def _replay_one_day(date_str: str, expected: pd.Series, ticks_all: pd.DataFrame,
                    bars_1h: pd.DataFrame) -> dict:
    """Return a dict {ok, why, ...} for one day's replay."""
    # Reset module state so this run is independent.
    fpb.reset_state_for_test()

    anchor_ts = pd.Timestamp(f"{date_str} 07:00:00", tz="UTC")
    if anchor_ts not in bars_1h.index:
        return {"ok": False, "why": f"anchor_bar_missing_{date_str}"}
    anchor = bars_1h.loc[anchor_ts]
    anchor_high = float(anchor["high"])
    anchor_low = float(anchor["low"])

    df_5m = _synthetic_anchor_df(date_str, anchor_high, anchor_low)

    day_start = pd.Timestamp(f"{date_str} 08:00:00", tz="UTC")
    day_end = pd.Timestamp(f"{date_str} 22:00:00", tz="UTC")
    sl = ticks_all.loc[(ticks_all.index >= day_start) & (ticks_all.index < day_end)]
    if sl.empty:
        return {"ok": False, "why": f"no_ticks_in_window_{date_str}"}

    fire = None
    for ts_idx, row in sl.iterrows():
        ts_epoch = ts_idx.timestamp()
        fire = fpb.tick_update(
            symbol=PAIR, epic="CS.D.USDCAD.TODAY.IP",
            mid=float(row["mid"]),
            bid=float(row["bid"]),
            ask=float(row["ask"]),
            ts=ts_epoch, ppp=1.0,
            df_5m=df_5m,
            has_open_for_mode_fn=lambda e, m: False,
        )
        if fire is not None:
            break

    if fire is None:
        return {"ok": False, "why": f"production_did_not_fire_{date_str}"}

    # Compare with analysis CSV row.
    exp_side = "BUY" if str(expected["side"]).lower() == "long" else "SELL"
    exp_entry = float(expected["entry_price"])
    exp_sl_level = float(expected["sl_level"])

    issues = []
    if fire["signal"] != exp_side:
        issues.append(f"side mismatch: prod={fire['signal']} csv={exp_side}")
    if abs(fire["entry"] - exp_entry) > TOL:
        issues.append(f"entry mismatch: prod={fire['entry']:.4f} csv={exp_entry:.4f}")
    sl_abs = fire["debug"]["sl_abs_price"]
    if abs(sl_abs - exp_sl_level) > TOL:
        issues.append(f"sl mismatch: prod={sl_abs:.4f} csv={exp_sl_level:.4f}")
    # Anchor match:
    if abs(fire["debug"]["anchor_high"] - float(expected["anchor_high"])) > TOL:
        issues.append(
            f"anchor_high: prod={fire['debug']['anchor_high']:.4f} "
            f"csv={float(expected['anchor_high']):.4f}"
        )
    if abs(fire["debug"]["anchor_low"] - float(expected["anchor_low"])) > TOL:
        issues.append(
            f"anchor_low: prod={fire['debug']['anchor_low']:.4f} "
            f"csv={float(expected['anchor_low']):.4f}"
        )
    # TP implied: entry ± 50.
    if exp_side == "BUY":
        exp_tp_abs = exp_entry + 50.0
    else:
        exp_tp_abs = exp_entry - 50.0
    if abs(fire["debug"]["tp_abs_price"] - exp_tp_abs) > TOL:
        issues.append(
            f"tp mismatch: prod={fire['debug']['tp_abs_price']:.4f} "
            f"implied_csv={exp_tp_abs:.4f}"
        )

    return {
        "ok": len(issues) == 0,
        "why": "; ".join(issues) if issues else "match",
        "date": date_str,
        "side": fire["signal"],
        "prod_entry": fire["entry"],
        "csv_entry": exp_entry,
        "prod_sl_abs": sl_abs,
        "csv_sl_level": exp_sl_level,
        "exit_reason_csv": expected["exit_reason"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="number of sample days")
    ap.add_argument("--seed", type=int, default=20260510)
    args = ap.parse_args()

    print(f"Loading trades from {TRADES_CSV}")
    trades = pd.read_csv(TRADES_CSV)
    trades["date"] = pd.to_datetime(trades["date"])
    fired = trades[trades["fired"] == True].reset_index(drop=True)  # noqa: E712
    n = len(fired)
    print(f"Fired-day rows in CSV: {n}")

    # Even-spaced sample to cover the full date range — same selection
    # pattern used to scope the validation against the analysis output.
    sample_idxs = [int(n * i / args.n) for i in range(args.n)]
    sample = fired.iloc[sample_idxs].copy()
    print(f"Sample days: {[str(d.date()) for d in sample['date']]}")

    print(f"\nLoading ticks for {PAIR}...")
    ticks = load_ticks(PAIR)
    print(f"  ticks: {len(ticks):,} rows  range={ticks.index.min().date()} → {ticks.index.max().date()}")
    print(f"Building 1H bars for anchor lookup...")
    bars_1h = build_bars_1h(PAIR)
    print(f"  H1: {len(bars_1h):,} rows")

    results = []
    for _, row in sample.iterrows():
        d = row["date"].strftime("%Y-%m-%d")
        r = _replay_one_day(d, row, ticks, bars_1h)
        results.append(r)

    ok_n = sum(1 for r in results if r["ok"])
    print(f"\n=== Detector validation gate: {ok_n}/{len(results)} days matched within {TOL}p ===\n")
    for r in results:
        marker = "✓" if r["ok"] else "✗"
        if r["ok"]:
            print(f"  {marker} {r['date']}  side={r['side']:<4} "
                  f"entry={r['prod_entry']:>9.4f} (csv {r['csv_entry']:>9.4f})  "
                  f"sl={r['prod_sl_abs']:>9.4f} (csv {r['csv_sl_level']:>9.4f})  "
                  f"exit_csv={r['exit_reason_csv']}")
        else:
            print(f"  {marker} {r.get('date','?')}  FAIL  {r['why']}")

    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
