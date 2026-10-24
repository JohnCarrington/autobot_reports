#!/usr/bin/env python3
"""Stage 3 + 5 + 6 + 7 — the 18 TP/SL scenarios.

Rules (identical across all 18 scenarios):
  * Signals come from the Phase-5 trained GBM via the signal audit.
  * A signal fires if  p_trend >= 0.5  AND  dir_confidence >= 0.5.
  * ONE OPEN POSITION AT A TIME.
  * While a position is open, further fires are SUPPRESSED and counted.
  * A trade exits on whichever occurs first:
        TP (fixed pip target in predicted direction)
        SL (fixed pip stop in predicted direction)
        Session end at 22:00 UK
  * Intrabar ambiguity (both TP and SL inside the same M5 candle): we
    report BOTH a conservative (SL first) and an optimistic (TP first)
    bound, and flag the trade so sensitivity can be checked.
  * Primary cost: 0.8 pip round-trip spread. Sensitivity: 0.5 and 1.5.
  * Price basis: 2024-25 BID, 2026 MID. We treat BOTH as "executable at
    close" with the 0.8-pip round-trip cost (standard practice). Because
    there is no ask/bid pair available for either corpus, we DO NOT claim
    tick-perfect execution. Sensitivity analysis on the spread captures the
    assumption uncertainty.

Scenarios: TP ∈ {20,25,30,35,40,45} × SL ∈ {12,15,20} → 18.

Outputs:
  outputs/nextres/executed_trades.csv       — per-trade record for every
                                              (scenario × trade)
  outputs/nextres/tp_sl_scenario_results.csv — one row per
                                              (scenario, partition)
  outputs/nextres/monthly_pnl.csv           — one row per
                                              (scenario, year-month)
  outputs/nextres/suppressed_signals_count.csv — per scenario, how many
                                              fires were suppressed by an
                                              already-open position
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file, _uk_offset_hours  # noqa: E402

ROOT = Path("<research_workspace>/outputs")
OUT = ROOT / "nextres"
OUT.mkdir(parents=True, exist_ok=True)

TPs = [20, 25, 30, 35, 40, 45]
SLs = [12, 15, 20]
SPREAD = 0.8
SPREAD_SENSITIVITY = [0.5, 1.5]

audit = pd.read_csv(OUT / "ai_signal_audit.csv")
audit = audit.sort_values(["date", "hour_uk"]).reset_index(drop=True)

candle_cache: dict[str, pd.DataFrame] = {}
def load(date_str):
    if date_str in candle_cache:
        return candle_cache[date_str]
    for p in CANDLES_EXT.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "BID"); candle_cache[date_str] = df; return df
    for p in CANDLES_26.glob(f"{date_str}.csv"):
        df = _load_day_file(p, "MID"); candle_cache[date_str] = df; return df
    return None


def _uk22_utc(date_str):
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=22 - off)


def _session_of_cutoff(cutoff_utc, date_str):
    off = _uk_offset_hours(pd.Timestamp(dt.date.fromisoformat(date_str), tz="UTC"))
    local_h = (pd.Timestamp(cutoff_utc).hour + off) % 24
    if local_h < 13:
        return "LONDON"
    return "NY"


def simulate_trade(df, entry_ts, entry_price, direction, tp, sl, date_str):
    """Return dict with exit info — conservative (SL-first) ambiguity rule.

    Also returns an 'optimistic_net_pips' as if TP had fired first on any
    ambiguous bar. These two values bracket the true answer.
    """
    end_22 = _uk22_utc(date_str)
    after = df[(df.ts > entry_ts) & (df.ts <= end_22)].reset_index(drop=True)
    if after.empty:
        return None
    tp_px = entry_price + tp/10000 if direction == "LONG" else entry_price - tp/10000
    sl_px = entry_price - sl/10000 if direction == "LONG" else entry_price + sl/10000

    # Walk bars
    status = None; exit_px = None; exit_ts = None; exit_bar_idx = None
    ambiguous = False
    for i, bar in enumerate(after.itertuples()):
        high = float(bar.high)/10000
        low  = float(bar.low)/10000
        if direction == "LONG":
            hit_tp = high >= tp_px
            hit_sl = low <= sl_px
        else:
            hit_tp = low <= tp_px
            hit_sl = high >= sl_px
        if hit_tp and hit_sl:
            # ambiguous — conservative rule: SL first
            status = "SL_ambiguous"; exit_px = sl_px; exit_ts = bar.ts
            ambiguous = True
            exit_bar_idx = i
            break
        if hit_tp:
            status = "TP"; exit_px = tp_px; exit_ts = bar.ts
            exit_bar_idx = i
            break
        if hit_sl:
            status = "SL"; exit_px = sl_px; exit_ts = bar.ts
            exit_bar_idx = i
            break
    if status is None:
        status = "SESSION_END"
        exit_px = float(after.close.iloc[-1])/10000
        exit_ts = after.ts.iloc[-1]
        exit_bar_idx = len(after) - 1

    if direction == "LONG":
        gross = (exit_px - entry_price) * 10000
    else:
        gross = (entry_price - exit_px) * 10000
    net = gross - SPREAD

    # MFE / MAE during the actual holding window
    held = after.iloc[: exit_bar_idx + 1]
    if direction == "LONG":
        mfe = (held.high.max()/10000 - entry_price) * 10000
        mae = (entry_price - held.low.min()/10000) * 10000
    else:
        mfe = (entry_price - held.low.min()/10000) * 10000
        mae = (held.high.max()/10000 - entry_price) * 10000

    # Minutes held
    duration_min = int((exit_ts - entry_ts).total_seconds() / 60)
    return {
        "exit_status": status,
        "exit_ts": exit_ts.isoformat() if hasattr(exit_ts, "isoformat") else str(exit_ts),
        "exit_price": round(exit_px, 5),
        "gross_pips": round(gross, 2),
        "net_pips": round(net, 2),
        "optimistic_net_pips":
            (round(tp - SPREAD, 2) if status == "SL_ambiguous"
             else round(net, 2)),
        "duration_min": duration_min,
        "mfe_during_hold_pips": round(mfe, 2),
        "mae_during_hold_pips": round(mae, 2),
        "ambiguous": ambiguous,
    }


def partition_of(d_str):
    d = dt.date.fromisoformat(d_str)
    if d < dt.date(2025, 7, 1): return "Dev"
    if d < dt.date(2026, 1, 1): return "Holdout"
    return "Conf2026"


all_trades = []
suppressed_rows = []
# For each (TP, SL) scenario, run through the signals in chronological order,
# one open position at a time.
for tp in TPs:
    for sl in SLs:
        scen_name = f"tp{tp}_sl{sl}"
        current_exit_ts = None       # ts at which the open position will have closed
        trades = []
        suppressed = 0
        for _, sig in audit.iterrows():
            if not bool(sig["would_fire_at_0.5"]):
                continue
            sig_ts = pd.Timestamp(sig.signal_ts_utc)
            if current_exit_ts is not None and sig_ts <= current_exit_ts:
                suppressed += 1
                continue
            df = load(sig.date)
            if df is None:
                continue
            res = simulate_trade(df, sig_ts, float(sig.entry_price),
                                  sig.dir_pred, tp, sl, sig.date)
            if res is None:
                continue
            current_exit_ts = pd.Timestamp(res["exit_ts"])
            trade = {
                "scenario": scen_name, "tp_pips": tp, "sl_pips": sl,
                "signal_date": sig.date,
                "signal_hour_uk": int(sig.hour_uk),
                "signal_ts_utc": sig.signal_ts_utc,
                "partition": sig.partition,
                "basis": sig.basis,
                "dir_pred": sig.dir_pred,
                "p_trend": float(sig.p_trend),
                "dir_confidence": float(sig.dir_confidence),
                "true_trend_day": bool(sig.true_trend_day),
                "true_direction":
                    sig.true_direction if pd.notna(sig.true_direction) else None,
                "entry_price": float(sig.entry_price),
                "session": _session_of_cutoff(sig_ts, sig.date),
                **res,
            }
            trades.append(trade)
        all_trades.extend(trades)
        suppressed_rows.append({
            "scenario": scen_name, "tp_pips": tp, "sl_pips": sl,
            "n_trades_executed": len(trades),
            "n_signals_suppressed_by_open_position": suppressed,
        })

df_tr = pd.DataFrame(all_trades)
df_tr.to_csv(OUT / "executed_trades.csv", index=False)
print(f"Wrote {len(df_tr)} executed-trade rows (18 scenarios × ~trades each)")

df_sup = pd.DataFrame(suppressed_rows)
df_sup.to_csv(OUT / "suppressed_signals_count.csv", index=False)

# ─── Scenario summary per partition ──────────────────────────────
rows_sum = []
for scen in sorted(df_tr.scenario.unique()):
    sub_scen = df_tr[df_tr.scenario == scen]
    tp = int(sub_scen.tp_pips.iloc[0]); sl = int(sub_scen.sl_pips.iloc[0])
    for part in ["Dev", "Holdout", "Conf2026", "ALL"]:
        s = sub_scen if part == "ALL" else sub_scen[sub_scen.partition == part]
        if s.empty: continue
        n = len(s)
        wins = s[s.net_pips > 0]
        losses = s[s.net_pips <= 0]
        tp_n = (s.exit_status == "TP").sum()
        sl_n = (s.exit_status.isin(["SL", "SL_ambiguous"])).sum()
        se_n = (s.exit_status == "SESSION_END").sum()
        amb_n = (s.ambiguous).sum()
        gross_win = wins.net_pips.sum() if len(wins) else 0.0
        gross_loss = losses.net_pips.sum() if len(losses) else 0.0
        total_net = s.net_pips.sum()
        total_net_opt = s.optimistic_net_pips.sum()
        pf = -gross_win/gross_loss if gross_loss != 0 else np.inf
        # Equity curve, drawdown
        eq = s.sort_values("signal_ts_utc").net_pips.cumsum()
        dd = (eq - eq.cummax()).min()
        # Monthly avg
        s = s.copy()
        s["ym"] = pd.to_datetime(s["signal_date"]).dt.to_period("M").astype(str)
        monthly_mean = s.groupby("ym").net_pips.sum().mean() if n else 0.0
        rows_sum.append({
            "scenario": scen, "tp_pips": tp, "sl_pips": sl, "partition": part,
            "trades": n, "wins": len(wins), "losses": len(losses),
            "tp_hit": int(tp_n), "sl_hit": int(sl_n), "session_end": int(se_n),
            "ambiguous_trades": int(amb_n),
            "win_rate_%": round(len(wins)/max(1,n)*100, 1),
            "tp_hit_%": round(tp_n/max(1,n)*100, 1),
            "sl_hit_%": round(sl_n/max(1,n)*100, 1),
            "session_end_%": round(se_n/max(1,n)*100, 1),
            "gross_win_pips": round(gross_win, 1),
            "gross_loss_pips": round(gross_loss, 1),
            "spread_cost_pips_total": round(n * SPREAD, 1),
            "total_net_pips": round(total_net, 1),
            "total_net_pips_optimistic": round(total_net_opt, 1),
            "avg_net_per_trade": round(total_net/max(1,n), 2),
            "avg_net_per_month": round(monthly_mean, 1),
            "profit_factor": round(pf, 2) if np.isfinite(pf) else None,
            "max_drawdown_pips": round(dd, 1),
            "avg_duration_min":
                round(s.duration_min.mean(), 1) if n else None,
            "median_duration_min":
                int(s.duration_min.median()) if n else None,
        })
summary = pd.DataFrame(rows_sum)
summary.to_csv(OUT / "tp_sl_scenario_results.csv", index=False)
print(f"Wrote scenario summary: {len(summary)} (scenario, partition) rows")

# Monthly P&L for every scenario × year-month × partition
rows_m = []
df_tr["ym"] = pd.to_datetime(df_tr["signal_date"]).dt.to_period("M").astype(str)
for scen in sorted(df_tr.scenario.unique()):
    sub_scen = df_tr[df_tr.scenario == scen]
    for part in ["Dev", "Holdout", "Conf2026"]:
        s = sub_scen[sub_scen.partition == part]
        if s.empty: continue
        for ym, grp in s.groupby("ym"):
            rows_m.append({
                "scenario": scen, "partition": part, "ym": ym,
                "trades": len(grp),
                "wins": int((grp.net_pips > 0).sum()),
                "net_pips": round(grp.net_pips.sum(), 1),
                "tp_hit": int((grp.exit_status == "TP").sum()),
                "sl_hit": int((grp.exit_status.isin(["SL","SL_ambiguous"])).sum()),
                "session_end": int((grp.exit_status == "SESSION_END").sum()),
            })
monthly = pd.DataFrame(rows_m)
monthly.to_csv(OUT / "monthly_pnl.csv", index=False)
print(f"Wrote monthly PnL: {len(monthly)} rows")

# Sensitivity: spread
sens = []
for s_cost in [SPREAD] + SPREAD_SENSITIVITY:
    for scen in sorted(df_tr.scenario.unique()):
        sub_scen = df_tr[df_tr.scenario == scen]
        for part in ["Dev", "Holdout", "Conf2026", "ALL"]:
            s = sub_scen if part == "ALL" else sub_scen[sub_scen.partition == part]
            if s.empty: continue
            # Re-compute net under alternate spread
            net = s.gross_pips - s_cost
            sens.append({
                "scenario": scen, "partition": part,
                "spread_pips": s_cost,
                "total_net_pips": round(net.sum(), 1),
                "mean_net_per_trade": round(net.mean(), 2),
            })
pd.DataFrame(sens).to_csv(OUT / "spread_sensitivity.csv", index=False)

# Headline printout
print("\n═══ Headline (0.8-pip spread, conservative-ambiguity rule) ═══")
pivot = summary[summary.partition != "ALL"].pivot_table(
    index=["tp_pips", "sl_pips"], columns="partition",
    values="total_net_pips", aggfunc="first")
print(pivot.to_string())
print("\n═══ Avg per-trade net (0.8-pip spread) ═══")
pivot2 = summary[summary.partition != "ALL"].pivot_table(
    index=["tp_pips", "sl_pips"], columns="partition",
    values="avg_net_per_trade", aggfunc="first")
print(pivot2.to_string())
print("\n═══ Win rate % ═══")
pivot3 = summary[summary.partition != "ALL"].pivot_table(
    index=["tp_pips", "sl_pips"], columns="partition",
    values="win_rate_%", aggfunc="first")
print(pivot3.to_string())
print("\n═══ TP-hit % ═══")
pivot4 = summary[summary.partition != "ALL"].pivot_table(
    index=["tp_pips", "sl_pips"], columns="partition",
    values="tp_hit_%", aggfunc="first")
print(pivot4.to_string())
