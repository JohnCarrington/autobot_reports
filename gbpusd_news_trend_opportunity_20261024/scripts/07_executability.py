#!/usr/bin/env python3
"""Executability test.

For a set of directional candidate conditions, simulate a single trade
per qualifying day with:
    anchor_time -> M5 close as entry price
    adjust for spread
    trail chronologically through M5 bars until SL or TP hit, or
    end-of-day timeout at 21:00 UTC

Modes tested:
    TP30 / SL12
    TP40 / SL12
Spread assumption: 0.8 pips (closes aligned with Pop A phase 7).

Within-bar order: if SL and TP both inside bar range, SL wins
(conservative pessimistic assumption).

Outputs:
    execution_feasibility.csv  — one row per (condition, mode, year)
    monthly_opportunity_results.csv — monthly net pips breakdown
    opportunity_trade_log.csv  — individual trades, for audit
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent.parent
CAL = HERE / "outputs" / "news_calendar.csv"
DAYS = HERE / "outputs" / "day_classification.csv"
TRADES = HERE / "outputs" / "opportunity_trade_log.csv"
FEAS = HERE / "outputs" / "execution_feasibility.csv"
MONTHLY = HERE / "outputs" / "monthly_opportunity_results.csv"

MID_2026 = Path("/opt/tradingbot/data/candles/GBPUSD")
BID_LEGACY = Path("/opt/tradingbot/data/candles_ext_v2/GBPUSD")

SPREAD = 0.8

def load_day(d: dt.date):
    for base in (MID_2026, BID_LEGACY):
        p = base / f"{d.isoformat()}.csv"
        if p.exists():
            rows = []
            with p.open() as fp:
                for row in csv.DictReader(fp):
                    ts = row["timestamp"].replace(" ", "T")
                    if "+" in ts:
                        tt = dt.datetime.fromisoformat(ts).astimezone(dt.timezone.utc).replace(tzinfo=None)
                    else:
                        tt = dt.datetime.fromisoformat(ts)
                    try:
                        o = float(row["open"]); h = float(row["high"]); l = float(row["low"]); c = float(row["close"])
                    except Exception:
                        continue
                    rows.append((tt, o, h, l, c))
            return rows
    return None

def simulate(day_rows, anchor_hhmm: str, dir_sign: int, tp: float, sl: float, end_hhmm="21:00"):
    """Return trade dict or None if no entry."""
    if not day_rows or not dir_sign: return None
    h0, m0 = int(anchor_hhmm[:2]), int(anchor_hhmm[3:5])
    h1, m1 = int(end_hhmm[:2]), int(end_hhmm[3:5])
    start = day_rows[0][0].replace(hour=h0, minute=m0, second=0, microsecond=0)
    end = day_rows[0][0].replace(hour=h1, minute=m1, second=0, microsecond=0)
    entry_price = None
    entry_ts = None
    for (ts, o, h, l, c) in day_rows:
        if ts == start:
            entry_price = c + (SPREAD / 2) * dir_sign  # pay half spread entering direction (BUY = pay higher ask)
            entry_ts = ts
            break
    if entry_price is None: return None
    tp_price = entry_price + dir_sign * tp
    sl_price = entry_price - dir_sign * sl
    outcome = "OPEN"
    exit_ts = None
    exit_price = None
    for (ts, o, h, l, c) in day_rows:
        if ts <= start: continue
        if ts > end: break
        # Did bar touch SL or TP?
        if dir_sign > 0:
            hit_sl = l <= sl_price
            hit_tp = h >= tp_price
        else:
            hit_sl = h >= sl_price
            hit_tp = l <= tp_price
        # Conservative: SL first if both
        if hit_sl and hit_tp:
            outcome = "SL"; exit_ts = ts; exit_price = sl_price; break
        if hit_sl:
            outcome = "SL"; exit_ts = ts; exit_price = sl_price; break
        if hit_tp:
            outcome = "TP"; exit_ts = ts; exit_price = tp_price; break
    if outcome == "OPEN":
        # Close at end bar
        last = None
        for (ts, o, h, l, c) in day_rows:
            if start < ts <= end: last = (ts, c)
        if last:
            outcome = "EOD"
            exit_ts = last[0]
            exit_price = last[1] - (SPREAD / 2) * dir_sign  # pay half spread to close
    net = (exit_price - entry_price) * dir_sign if exit_price is not None else 0.0
    return {
        "entry_ts": entry_ts, "entry_price": round(entry_price, 2),
        "exit_ts": exit_ts, "exit_price": round(exit_price, 2) if exit_price is not None else "",
        "outcome": outcome,
        "net_pips": round(net, 1),
        "duration_min": int((exit_ts - entry_ts).total_seconds() / 60.0) if exit_ts else "",
    }

def pre_london_trend(day_rows):
    if not day_rows: return None
    start_tt = day_rows[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
    end_tt = day_rows[0][0].replace(hour=6, minute=0, second=0, microsecond=0)
    anchor_price = None; last_close = None
    for (ts, o, h, l, c) in day_rows:
        if ts < start_tt: continue
        if ts > end_tt: break
        if anchor_price is None: anchor_price = o
        last_close = c
    if anchor_price is None or last_close is None: return None
    return last_close - anchor_price

def main():
    cal_by_date: dict[str, list[dict]] = {}
    with CAL.open() as fp:
        for r in csv.DictReader(fp):
            cal_by_date.setdefault(r["date"], []).append(r)
    rows = list(csv.DictReader(DAYS.open()))

    def has_pm_us(d):
        return any(e["impact"] == "HIGH" and e["currency"] == "USD" and e["scheduled_time_utc"] >= "13:00" for e in cal_by_date.get(d, []))
    def has_am_us(d):
        return any(e["impact"] == "HIGH" and e["currency"] == "USD" and e["scheduled_time_utc"] >= "12:00" and e["scheduled_time_utc"] < "13:00" for e in cal_by_date.get(d, []))
    def has_am_gbp(d):
        return any(e["impact"] == "HIGH" and e["currency"] == "GBP" and e["scheduled_time_utc"] < "11:00" for e in cal_by_date.get(d, []))

    # Candidate rules (name, anchor, direction_fn(row, pretrend_signed_pips) -> {+1,-1,0,None})
    def rule_pretrend_up(r, s):           return 1 if s is not None and s > 15 else None
    def rule_pretrend_down(r, s):         return -1 if s is not None and s < -15 else None
    def rule_pretrend_up_pre_us(r, s):    return 1 if s is not None and s > 15 and has_pm_us(r["date"]) else None
    def rule_pretrend_down_pre_us(r, s):  return -1 if s is not None and s < -15 and has_pm_us(r["date"]) else None
    def rule_pretrend_up_nonews(r, s):    return 1 if s is not None and s > 15 and r["flag_no_major_news"] == "1" else None
    def rule_pretrend_down_nonews(r, s):  return -1 if s is not None and s < -15 and r["flag_no_major_news"] == "1" else None
    def rule_pretrend_up_prenews(r, s):   return 1 if s is not None and s > 15 and r["flag_pre_news_1d"] == "1" else None
    def rule_pretrend_down_prenews(r, s): return -1 if s is not None and s < -15 and r["flag_pre_news_1d"] == "1" else None
    # Strong versions
    def rule_pretrend_up_strong(r, s):    return 1 if s is not None and s > 25 else None
    def rule_pretrend_down_strong(r, s):  return -1 if s is not None and s < -25 else None

    rules = [
        ("pretrend_up_follow",             "07:00", rule_pretrend_up),
        ("pretrend_down_follow",           "07:00", rule_pretrend_down),
        ("pretrend_up_strong_follow",      "07:00", rule_pretrend_up_strong),
        ("pretrend_down_strong_follow",    "07:00", rule_pretrend_down_strong),
        ("pretrend_up_pre_us_news",        "07:00", rule_pretrend_up_pre_us),
        ("pretrend_down_pre_us_news",      "07:00", rule_pretrend_down_pre_us),
        ("pretrend_up_nonews",             "07:00", rule_pretrend_up_nonews),
        ("pretrend_down_nonews",           "07:00", rule_pretrend_down_nonews),
        ("pretrend_up_prenews",            "07:00", rule_pretrend_up_prenews),
        ("pretrend_down_prenews",          "07:00", rule_pretrend_down_prenews),
    ]
    modes = [("TP30_SL12", 30.0, 12.0), ("TP40_SL12", 40.0, 12.0)]

    trade_log = []
    for name, anchor, fn in rules:
        for r in rows:
            d = dt.date.fromisoformat(r["date"])
            day = load_day(d)
            if not day: continue
            s = pre_london_trend(day)
            dir_sign = fn(r, s)
            if not dir_sign: continue
            for mode_name, tp, sl in modes:
                tr = simulate(day, anchor, dir_sign, tp, sl)
                if tr is None: continue
                tr.update({
                    "condition": name,
                    "mode": mode_name,
                    "date": r["date"],
                    "year": r["date"][:4],
                    "direction": "BUY" if dir_sign > 0 else "SELL",
                    "pretrend_pips": round(s or 0.0, 1),
                    "flag_major_news": r["flag_major_news"],
                    "flag_pre_news_1d": r["flag_pre_news_1d"],
                    "flag_no_major_news": r["flag_no_major_news"],
                    "high_event_names": r["high_event_names"][:120],
                })
                trade_log.append(tr)

    # Write trade log
    cols = ["condition","mode","date","year","direction","pretrend_pips",
            "entry_ts","entry_price","exit_ts","exit_price","outcome","net_pips","duration_min",
            "flag_major_news","flag_pre_news_1d","flag_no_major_news","high_event_names"]
    with TRADES.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        for t in trade_log:
            for k in cols: t.setdefault(k, "")
            w.writerow(t)
    print(f"wrote {len(trade_log)} trades -> {TRADES}")

    # Aggregate feasibility
    agg = defaultdict(lambda: {"n": 0, "wins": 0, "losses": 0, "eod": 0,
                                "net_pips": 0.0, "max_dd": 0.0, "running": 0.0,
                                "cum_min": 0.0})
    for t in trade_log:
        bk = (t["condition"], t["mode"], t["year"])
        bk_all = (t["condition"], t["mode"], "all")
        for b in (agg[bk], agg[bk_all]):
            b["n"] += 1
            if t["outcome"] == "TP": b["wins"] += 1
            elif t["outcome"] == "SL": b["losses"] += 1
            else: b["eod"] += 1
            b["net_pips"] += float(t["net_pips"])
            b["running"] += float(t["net_pips"])
            b["cum_min"] = min(b["cum_min"], b["running"])
            b["max_dd"] = max(b["max_dd"], (b["cum_min"] - b["running"]) * -1 if b["running"] > b["cum_min"] else b["max_dd"])

    feas = []
    for (cond, mode, year), b in sorted(agg.items()):
        if year == "all":
            months_spanned = (dt.date(2026,10,24) - dt.date(2024,1,1)).days / 30.44
        else:
            yr = int(year)
            months_spanned = 12 if yr < 2026 else 10
        feas.append({
            "condition": cond, "mode": mode, "year": year,
            "n_trades": b["n"],
            "trades_per_month": round(b["n"] / months_spanned, 2) if months_spanned else "",
            "wins": b["wins"], "losses": b["losses"], "eod": b["eod"],
            "win_rate_pct": round(b["wins"] / b["n"] * 100, 1) if b["n"] else "",
            "net_pips": round(b["net_pips"], 1),
            "net_pips_per_month": round(b["net_pips"] / months_spanned, 1) if months_spanned else "",
            "net_pips_per_trade": round(b["net_pips"] / b["n"], 2) if b["n"] else "",
            "max_dd_from_peak": round(b["running"] - b["cum_min"], 1),
        })
    with FEAS.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(feas[0].keys()))
        w.writeheader()
        w.writerows(feas)
    print(f"wrote {len(feas)} feasibility rows -> {FEAS}")

    print("\n=== Executability — year=all, sorted by net pips/month ===")
    allrows = [r for r in feas if r["year"] == "all" and int(r["n_trades"]) >= 15]
    allrows.sort(key=lambda r: -float(r["net_pips_per_month"]))
    print(f"{'condition':30} {'mode':10} {'n':>4} {'tr/mo':>5} {'win%':>5} {'netPips':>8} {'/mo':>6} {'/tr':>6}")
    for r in allrows:
        print(f"{r['condition']:30} {r['mode']:10} {r['n_trades']:>4} {r['trades_per_month']:>5} "
              f"{r['win_rate_pct']:>5} {r['net_pips']:>8} {r['net_pips_per_month']:>6} {r['net_pips_per_trade']:>6}")

    # Monthly results CSV
    monthly = defaultdict(lambda: defaultdict(float))
    for t in trade_log:
        ym = t["date"][:7]
        monthly[(t["condition"], t["mode"])][ym] += float(t["net_pips"])
    mrows = []
    for (cond, mode), m in monthly.items():
        for ym, net in sorted(m.items()):
            mrows.append({"condition": cond, "mode": mode, "month": ym, "net_pips": round(net, 1)})
    with MONTHLY.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=["condition","mode","month","net_pips"])
        w.writeheader(); w.writerows(mrows)
    print(f"wrote {len(mrows)} monthly rows -> {MONTHLY}")

if __name__ == "__main__":
    main()
