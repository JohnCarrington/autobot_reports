#!/usr/bin/env python3
"""Phase 7 Task 6 — Monthly opportunity ledger.

Per calendar month, report:
  1. Weekdays
  2. True trend days (≥80 pips directional)
  3. Theoretical 45-pip opportunities ≡ trend days (since 80 ≥ 45)
  4. Days the AI first-fired a signal (any direction)
  5. Days the AI first-fired on a true trend day in the correct direction
  6. Days where ≥45 pips remained in TRUE direction after first signal
  7. Days where TP45 reached before SL=25 (based on backtest file)
  8. Net pips realised at SL=25

Distinguishes the maximum historical opportunity from the AI-realisable.
"""
from __future__ import annotations

from pathlib import Path
import datetime as dt
import pandas as pd

ROOT = Path("<research_workspace>/outputs")
P7 = ROOT / "phase7"

census = pd.read_csv(ROOT / "census.csv")
census["date"] = pd.to_datetime(census["date"])
reg = pd.read_csv(P7 / "signal_register.csv")
reg["date"] = pd.to_datetime(reg["date"])
limiter = pd.read_csv(P7 / "why_limiter.csv")
limiter["date"] = pd.to_datetime(limiter["date"])
# Pull the SL=25 trade file (best out-of-sample balance based on tp45_summary)
trades25 = pd.read_csv(P7 / "trades_tp45_sl25.csv")
trades25["date"] = pd.to_datetime(trades25["date"])
trades15 = pd.read_csv(P7 / "trades_tp45_sl15.csv")
trades15["date"] = pd.to_datetime(trades15["date"])


def _mo(d):
    return pd.Timestamp(d).to_period("M").strftime("%Y-%m")


census["ym"] = census["date"].dt.to_period("M")
reg["ym"] = reg["date"].dt.to_period("M")
limiter["ym"] = limiter["date"].dt.to_period("M")
trades25["ym"] = trades25["date"].dt.to_period("M")
trades15["ym"] = trades15["date"].dt.to_period("M")

# Fires-per-day (first fire only)
fires_fp = pd.read_csv(P7 / "fires_first_per_day.csv")
fires_fp["date"] = pd.to_datetime(fires_fp["date"])
fires_fp["ym"] = fires_fp["date"].dt.to_period("M")

rows = []
for ym, cen_sub in census.groupby("ym"):
    weekdays = len(cen_sub)
    trend_days = int(cen_sub.trend_day.sum())
    theoretical_pips = trend_days * 45  # cap at 45 per day
    fires_sub = fires_fp[fires_fp.ym == ym]
    n_fires = len(fires_sub)
    lim_sub = limiter[limiter.ym == ym]
    n_good = int((lim_sub.limiter == "GOOD_FIRE").sum())
    n_fp = int((lim_sub.limiter == "FALSE_POSITIVE").sum())
    n_wrong = int((lim_sub.limiter == "WRONG_DIR").sum())
    n_late = int((lim_sub.limiter == "LATE_FIRE_INSUFFICIENT_REMAIN").sum())

    t25 = trades25[trades25.ym == ym]
    net25 = round(t25.net_pips.sum(), 1) if len(t25) else 0.0
    wins25 = int((t25.net_pips > 0).sum())
    t15 = trades15[trades15.ym == ym]
    net15 = round(t15.net_pips.sum(), 1) if len(t15) else 0.0
    wins15 = int((t15.net_pips > 0).sum())

    rows.append({
        "ym": str(ym),
        "weekdays": weekdays,
        "trend_days": trend_days,
        "max_pips_at_45_per_day": theoretical_pips,
        "n_ai_fires": n_fires,
        "n_good_fires": n_good,
        "n_false_positive": n_fp,
        "n_wrong_dir": n_wrong,
        "n_late_insufficient": n_late,
        "tp45_sl15_trades": len(t15), "tp45_sl15_wins": wins15,
        "tp45_sl15_net_pips": net15,
        "tp45_sl25_trades": len(t25), "tp45_sl25_wins": wins25,
        "tp45_sl25_net_pips": net25,
    })

m_df = pd.DataFrame(rows)
m_df.to_csv(P7 / "monthly_opportunity.csv", index=False)

# Annual aggregates
m_df["year"] = m_df.ym.str[:4]
annual = m_df.groupby("year").agg({
    "weekdays": "sum", "trend_days": "sum",
    "max_pips_at_45_per_day": "sum",
    "n_ai_fires": "sum", "n_good_fires": "sum",
    "n_false_positive": "sum", "n_wrong_dir": "sum",
    "tp45_sl15_trades": "sum", "tp45_sl15_wins": "sum", "tp45_sl15_net_pips": "sum",
    "tp45_sl25_trades": "sum", "tp45_sl25_wins": "sum", "tp45_sl25_net_pips": "sum",
}).reset_index()
annual.to_csv(P7 / "annual_opportunity.csv", index=False)

print("═══ Monthly opportunity ═══")
print(m_df.to_string(index=False))
print("\n═══ Annual ═══")
print(annual.to_string(index=False))

# Totals
tot = annual[["weekdays", "trend_days", "max_pips_at_45_per_day", "n_ai_fires",
              "n_good_fires", "n_false_positive", "n_wrong_dir",
              "tp45_sl15_trades", "tp45_sl15_wins", "tp45_sl15_net_pips",
              "tp45_sl25_trades", "tp45_sl25_wins", "tp45_sl25_net_pips"]].sum()
print("\n═══ Grand totals ═══")
print(tot.to_string())

print(f"\nMax theoretical opportunity (45 pips × trend days): "
      f"{tot['max_pips_at_45_per_day']:.0f} pips")
print(f"AI 'good fire' identification rate: "
      f"{tot['n_good_fires']/tot['trend_days']*100:.1f}% of trend days")
print(f"Net captured @ SL=25: {tot['tp45_sl25_net_pips']:.0f} pips total "
      f"({tot['tp45_sl25_net_pips']/tot['tp45_sl25_trades']:.2f} pips/trade)")
print(f"Net captured @ SL=15: {tot['tp45_sl15_net_pips']:.0f} pips total "
      f"({tot['tp45_sl15_net_pips']/tot['tp45_sl15_trades']:.2f} pips/trade)")
