#!/usr/bin/env python3
"""Phase 7 Task 2 — Fixed TP (+45) / Fixed SL backtest for every signal.

For every (date, hour, basis) in the signal register, if the model fires
(p_trend >= trend_thr, dir_conf >= dir_thr), simulate:

    Entry at the M5 close at the cutoff.
    TP: +45 pips in predicted direction.
    SL: stops from {12, 15, 20, 25, 30} pips.
    Hold until 21:00 UK (end-of-window) if neither triggers.

Intrabar ambiguity: if both TP and SL are inside the same M5 candle, we
check order via 1-minute candles if available; else classify as AMBIGUOUS
and conservatively assume SL triggered first (worst case). Our source is
5-minute only — ambiguity is handled by the pessimistic rule.

Costs: 0.8 pip round-trip spread.

Output: outputs/phase7/trades_tp45_sl{N}.csv for each stop, plus a summary
`outputs/phase7/tp45_summary.csv`.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file, _uk_offset_hours  # noqa

ROOT = Path("<research_workspace>/outputs")
P7 = ROOT / "phase7"; P7.mkdir(exist_ok=True)

reg = pd.read_csv(P7 / "signal_register.csv")
reg["date"] = reg["date"].astype(str)

STOPS = [12, 15, 20, 25, 30]
TP_PIPS = 45.0
SPREAD = 0.8  # round-trip cost in pips
TRND_THR = 0.5
DIR_THR = 0.5

# Preload candle lookup
candle_cache: dict[str, pd.DataFrame] = {}
def load_m5(date_str: str) -> pd.DataFrame | None:
    if date_str in candle_cache:
        return candle_cache[date_str]
    for p in CANDLES_EXT.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "BID"); candle_cache[date_str] = df; return df
    for p in CANDLES_26.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "MID"); candle_cache[date_str] = df; return df
    return None


def _window_end_utc(date_str: str) -> pd.Timestamp:
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=21 - off)


def simulate_trade(row, sl_pips: float) -> dict:
    """Resolve a single trade from M5 bars starting after cutoff."""
    date = row.date
    dir_pred = row.dir_pred
    entry_px = float(row.close_at_cutoff)
    tp_px = entry_px + TP_PIPS/10000  if dir_pred == "LONG" else entry_px - TP_PIPS/10000
    sl_px = entry_px - sl_pips/10000  if dir_pred == "LONG" else entry_px + sl_pips/10000

    df_m5 = load_m5(date)
    if df_m5 is None:
        return {"status": "no_data"}
    cutoff = pd.Timestamp(row.cutoff_utc)
    end = _window_end_utc(date)
    after = df_m5[(df_m5.ts > cutoff) & (df_m5.ts <= end)].reset_index(drop=True)
    if after.empty:
        return {"status": "no_bars"}
    status = None; exit_px = None; exit_ts = None; bars_held = 0
    for _, bar in after.iterrows():
        bars_held += 1
        high = float(bar.high)/10000
        low  = float(bar.low)/10000
        if dir_pred == "LONG":
            hit_tp = high >= tp_px
            hit_sl = low <= sl_px
        else:
            hit_tp = low <= tp_px
            hit_sl = high >= sl_px
        if hit_tp and hit_sl:
            # ambiguous — pessimistic: SL first
            status = "SL_AMBIGUOUS"; exit_px = sl_px; exit_ts = bar.ts; break
        if hit_tp:
            status = "TP"; exit_px = tp_px; exit_ts = bar.ts; break
        if hit_sl:
            status = "SL"; exit_px = sl_px; exit_ts = bar.ts; break
    if status is None:
        status = "EOW"; exit_px = float(after.close.iloc[-1])/10000; exit_ts = after.ts.iloc[-1]

    if dir_pred == "LONG":
        gross_pips = (exit_px - entry_px) * 10000
    else:
        gross_pips = (entry_px - exit_px) * 10000
    net_pips = gross_pips - SPREAD

    return {
        "exit_status": status,
        "exit_px": round(exit_px, 5),
        "exit_ts": exit_ts.isoformat() if exit_ts is not None else None,
        "bars_held": bars_held,
        "gross_pips": round(gross_pips, 2),
        "net_pips": round(net_pips, 2),
    }

def one_entry_per_day(sub: pd.DataFrame) -> pd.DataFrame:
    """Keep only the FIRST fire per date (earliest hour cutoff)."""
    fires = sub[(sub.p_trend >= TRND_THR) & (sub.dir_confidence >= DIR_THR)].copy()
    first = fires.sort_values(["date", "hour_uk"]).groupby("date").first().reset_index()
    return first

# Build the fire set once (same across stops)
fires_first = one_entry_per_day(reg)
fires_first.to_csv(P7 / "fires_first_per_day.csv", index=False)
print(f"First-fire-per-day signals: {len(fires_first)} "
      f"(partitions: {fires_first.partition.value_counts().to_dict()})")

summary_rows = []
for sl in STOPS:
    results = []
    for _, r in fires_first.iterrows():
        res = simulate_trade(r, sl)
        row = {**r.to_dict(), **res, "sl_pips": sl, "tp_pips": TP_PIPS}
        results.append(row)
    rdf = pd.DataFrame(results)
    rdf.to_csv(P7 / f"trades_tp45_sl{sl}.csv", index=False)
    # per-partition summary
    for part in ["Dev", "Holdout", "Conf2026"]:
        sub = rdf[rdf.partition == part]
        if sub.empty: continue
        wins = sub[sub.net_pips > 0]
        losses = sub[sub.net_pips <= 0]
        n = len(sub)
        total_net = sub.net_pips.sum()
        wr = len(wins)/n*100
        avg_win = wins.net_pips.mean() if len(wins) else 0
        avg_loss = losses.net_pips.mean() if len(losses) else 0
        pf = -wins.net_pips.sum()/losses.net_pips.sum() if len(losses) and losses.net_pips.sum() != 0 else np.inf
        expectancy = sub.net_pips.mean()
        # Equity curve, drawdown
        eq = sub.net_pips.cumsum()
        dd = (eq - eq.cummax()).min()
        tp_pct = (sub.exit_status == "TP").mean()*100
        sl_pct = (sub.exit_status.isin(["SL", "SL_AMBIGUOUS"])).mean()*100
        eow_pct = (sub.exit_status == "EOW").mean()*100
        amb_pct = (sub.exit_status == "SL_AMBIGUOUS").mean()*100

        summary_rows.append({
            "partition": part, "sl_pips": sl, "n_trades": n,
            "wins": len(wins), "losses": len(losses),
            "win_rate_%": round(wr, 1),
            "avg_win_net": round(avg_win, 1),
            "avg_loss_net": round(avg_loss, 1),
            "expectancy_net_pips": round(expectancy, 2),
            "total_net_pips": round(total_net, 1),
            "profit_factor": round(pf, 2) if np.isfinite(pf) else None,
            "max_drawdown_pips": round(dd, 1),
            "tp_pct_%": round(tp_pct, 1),
            "sl_pct_%": round(sl_pct, 1),
            "eow_pct_%": round(eow_pct, 1),
            "ambiguous_pct_%": round(amb_pct, 1),
        })

sum_df = pd.DataFrame(summary_rows)
sum_df.to_csv(P7 / "tp45_summary.csv", index=False)

print("\n═══ TP=45 pips, varying SL (first-fire-per-day, cost 0.8 pip) ═══")
print(sum_df.pivot_table(index="sl_pips", columns="partition",
                         values=["n_trades", "win_rate_%", "expectancy_net_pips",
                                 "total_net_pips", "profit_factor", "tp_pct_%", "sl_pct_%"],
                         aggfunc="first").to_string())
