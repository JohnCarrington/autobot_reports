#!/usr/bin/env python3
"""Build opportunity profiles.

For each candidate condition evaluated on every weekday 2024-01-01 →
2026-10-24, compute:
    frequency per month, probability of a subsequent 30p move, 40p move,
    80p move, typical maximum adverse excursion before the favourable
    extension (if direction is predicted; otherwise unsigned MFE/MAE).

Condition entry assumption — a condition is evaluated at a fixed UTC
anchor time per profile; the forecast is then applied by observing M5
candles from the anchor time through 21:00 UTC same day. Direction, if
specified, is a static guess (continuation / fade based on signal).

Output: opportunity_profiles.csv — one row per (condition, direction, year).
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
OUT = HERE / "outputs" / "opportunity_profiles.csv"

MID_2026 = Path("/opt/tradingbot/data/candles/GBPUSD")
BID_LEGACY = Path("/opt/tradingbot/data/candles_ext_v2/GBPUSD")

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

def mfe_mae_from_anchor(day_rows, anchor_hhmm: str, dir_sign: int, end_hhmm="21:00"):
    """From anchor time until end, measure max favourable / max adverse pips.
    dir_sign: +1 BUY, -1 SELL, 0 = unsigned (returns both sides)."""
    if not day_rows: return None
    h0, m0 = int(anchor_hhmm[:2]), int(anchor_hhmm[3:5])
    h1, m1 = int(end_hhmm[:2]), int(end_hhmm[3:5])
    start = day_rows[0][0].replace(hour=h0, minute=m0, second=0, microsecond=0)
    end = day_rows[0][0].replace(hour=h1, minute=m1, second=0, microsecond=0)
    anchor_price = None
    hi = -1e18; lo = 1e18
    for (ts, o, h, l, c) in day_rows:
        if ts < start: continue
        if ts > end: break
        if anchor_price is None: anchor_price = o
        hi = max(hi, h); lo = min(lo, l)
    if anchor_price is None: return None
    up = hi - anchor_price
    dn = anchor_price - lo
    if dir_sign == 0:
        return {"mfe": max(up, dn), "mae": min(up, dn), "up": up, "down": dn, "anchor_price": anchor_price}
    if dir_sign > 0:
        return {"mfe": up, "mae": dn, "anchor_price": anchor_price}
    return {"mfe": dn, "mae": up, "anchor_price": anchor_price}

def main():
    # Load calendar for event-type conditions
    cal_by_date: dict[str, list[dict]] = {}
    with CAL.open() as fp:
        for r in csv.DictReader(fp):
            cal_by_date.setdefault(r["date"], []).append(r)

    # Load day classification
    rows = list(csv.DictReader(DAYS.open()))

    def events_today(date: str):
        return cal_by_date.get(date, [])
    def has_high_event(date: str, country: str = ""):
        for e in events_today(date):
            if e["impact"] == "HIGH" and (not country or e["currency"] == country):
                return True
        return False

    def pre_london_trend(d: dt.date):
        """Signed pips from 00:00 UTC to 06:00 UTC. Returns (sign, pips)."""
        day = load_day(d)
        if not day: return None
        start_tt = day[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
        end_tt = day[0][0].replace(hour=6, minute=0, second=0, microsecond=0)
        anchor_price = None; last_close = None
        for (ts, o, h, l, c) in day:
            if ts < start_tt: continue
            if ts > end_tt: break
            if anchor_price is None: anchor_price = o
            last_close = c
        if anchor_price is None or last_close is None: return None
        return last_close - anchor_price

    # Candidate conditions: (name, filter(date,row) -> optional direction OR 0 for unsigned, anchor_hhmm)
    def filt_major_news_day(d, r):
        return 0 if r["flag_major_news"] == "1" else None
    def filt_pre_news_1d(d, r):
        return 0 if r["flag_pre_news_1d"] == "1" else None
    def filt_post_news_day(d, r):
        return 0 if r["flag_post_news"] == "1" else None
    def filt_no_major_news(d, r):
        return 0 if r["flag_no_major_news"] == "1" else None
    def filt_boe_day(d, r):
        return 0 if re.search(r"UK_BOE|MPC|Bank of England|BoE Interest", r["high_event_names"], re.I) else None
    def filt_fomc_day(d, r):
        return 0 if re.search(r"US_FOMC|FOMC|Fed Interest|Federal Funds", r["high_event_names"], re.I) else None
    def filt_nfp_day(d, r):
        return 0 if re.search(r"Non.?Farm|US_NFP|Nonfarm Pay", r["high_event_names"], re.I) else None
    def filt_us_cpi_day(d, r):
        return 0 if (re.search(r"US_CPI|Core CPI|CPI YoY|CPI MoM", r["high_event_names"], re.I) and int(r["n_high_usd"]) > 0) else None
    def filt_uk_cpi_day(d, r):
        return 0 if (re.search(r"UK_CPI|Inflation Rate", r["high_event_names"], re.I) and int(r["n_high_gbp"]) > 0) else None
    def filt_us_news_pm(date_s, r):
        """Major US news scheduled 13:00-15:00 UTC (NY_AM)."""
        for e in cal_by_date.get(date_s, []):
            if e["impact"] == "HIGH" and e["currency"] == "USD":
                hhmm = e["scheduled_time_utc"]
                if hhmm and hhmm >= "13:00" and hhmm < "15:00":
                    return 0
        return None

    def _pretrend(d):
        if isinstance(d, str):
            d = dt.date.fromisoformat(d)
        return pre_london_trend(d)

    def filt_pretrend_up(d, r):
        s = _pretrend(d)
        if s is None: return None
        return 1 if s > 15 else None  # pre-London up >15p
    def filt_pretrend_down(d, r):
        s = _pretrend(d)
        if s is None: return None
        return -1 if s < -15 else None
    def filt_pretrend_up_strong(d, r):
        s = _pretrend(d)
        if s is None: return None
        return 1 if s > 25 else None
    def filt_pretrend_down_strong(d, r):
        s = _pretrend(d)
        if s is None: return None
        return -1 if s < -25 else None

    # Composite — pre-trend AND no-major-news
    def filt_pretrend_up_nonews(d, r):
        s = _pretrend(d)
        if s is None or r["flag_no_major_news"] != "1": return None
        return 1 if s > 15 else None
    def filt_pretrend_down_nonews(d, r):
        s = _pretrend(d)
        if s is None or r["flag_no_major_news"] != "1": return None
        return -1 if s < -15 else None

    # Pre-US-news afternoon continuation during London (anchor 11:00 UTC)
    def filt_pretrend_up_pre_us_news(date_s, r):
        s = _pretrend(date_s)
        if s is None: return None
        has_pm_us = any(e["impact"] == "HIGH" and e["currency"] == "USD" and e["scheduled_time_utc"] >= "13:00" for e in cal_by_date.get(date_s, []))
        if not has_pm_us: return None
        return 1 if s > 15 else None
    def filt_pretrend_down_pre_us_news(date_s, r):
        s = _pretrend(date_s)
        if s is None: return None
        has_pm_us = any(e["impact"] == "HIGH" and e["currency"] == "USD" and e["scheduled_time_utc"] >= "13:00" for e in cal_by_date.get(date_s, []))
        if not has_pm_us: return None
        return -1 if s < -15 else None

    profiles = [
        # (name, anchor_hhmm, filter_fn)
        ("major_news_day_unsigned",       "06:00", filt_major_news_day),
        ("pre_news_1d_unsigned",          "06:00", filt_pre_news_1d),
        ("post_news_day_unsigned",        "06:00", filt_post_news_day),
        ("no_major_news_unsigned",        "06:00", filt_no_major_news),
        ("boe_day_unsigned",              "06:00", filt_boe_day),
        ("fomc_day_unsigned",             "06:00", filt_fomc_day),
        ("nfp_day_unsigned",              "06:00", filt_nfp_day),
        ("us_cpi_day_unsigned",           "06:00", filt_us_cpi_day),
        ("uk_cpi_day_unsigned",           "06:00", filt_uk_cpi_day),
        ("us_news_pm_unsigned",           "06:00", filt_us_news_pm),
        # Directional (pre-London trend-follow)
        ("pretrend_up_follow_at_07",     "07:00", filt_pretrend_up),
        ("pretrend_down_follow_at_07",   "07:00", filt_pretrend_down),
        ("pretrend_up_strong_follow_07", "07:00", filt_pretrend_up_strong),
        ("pretrend_down_strong_follow_07","07:00", filt_pretrend_down_strong),
        # Composite — pretrend × no-major-news
        ("pretrend_up_nonews_follow_07",  "07:00", filt_pretrend_up_nonews),
        ("pretrend_down_nonews_follow_07","07:00", filt_pretrend_down_nonews),
        # Composite — pretrend × pre-US-news
        ("pretrend_up_preUSnews_follow_07","07:00", filt_pretrend_up_pre_us_news),
        ("pretrend_down_preUSnews_follow_07","07:00", filt_pretrend_down_pre_us_news),
    ]

    all_results = []
    for name, anchor, fn in profiles:
        buckets = defaultdict(lambda: {"n": 0, "p30": 0, "p40": 0, "p80": 0, "mfe_sum": 0.0, "mae_sum": 0.0, "mae_min": 0.0, "mae_max": 0.0})
        for r in rows:
            date = r["date"]
            d = dt.date.fromisoformat(date)
            dir_sign = fn(date, r)
            if dir_sign is None: continue
            day = load_day(d)
            if not day: continue
            res = mfe_mae_from_anchor(day, anchor, dir_sign)
            if res is None: continue
            year = date[:4]
            for bk in (year, "all"):
                b = buckets[bk]
                b["n"] += 1
                mfe = res["mfe"]
                mae = res["mae"]
                if mfe >= 30: b["p30"] += 1
                if mfe >= 40: b["p40"] += 1
                if mfe >= 80: b["p80"] += 1
                b["mfe_sum"] += mfe
                b["mae_sum"] += mae
                b["mae_max"] = max(b["mae_max"], mae)
        # Months spanned per bucket
        for bk, b in buckets.items():
            if bk == "all":
                months_spanned = (dt.date(2026,10,24) - dt.date(2024,1,1)).days / 30.44
            else:
                yr = int(bk)
                months_spanned = 12 if yr < 2026 else 10  # 2026: Jan..Oct
            all_results.append({
                "condition": name,
                "year": bk,
                "n": b["n"],
                "freq_per_month": round(b["n"] / months_spanned, 2) if months_spanned else "",
                "p30p_hit": round(b["p30"] / b["n"] * 100, 1) if b["n"] else "",
                "p40p_hit": round(b["p40"] / b["n"] * 100, 1) if b["n"] else "",
                "p80p_hit": round(b["p80"] / b["n"] * 100, 1) if b["n"] else "",
                "avg_mfe_pips": round(b["mfe_sum"] / b["n"], 1) if b["n"] else "",
                "avg_mae_pips": round(b["mae_sum"] / b["n"], 1) if b["n"] else "",
                "max_mae_pips": round(b["mae_max"], 1),
            })
    with OUT.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(all_results[0].keys()))
        w.writeheader()
        w.writerows(all_results)
    print(f"wrote {len(all_results)} rows -> {OUT}")

    print("\n=== Opportunity profiles (year=all), sorted by p30p ===")
    year_all = [r for r in all_results if r["year"] == "all" and r["n"] and int(r["n"]) >= 20]
    year_all.sort(key=lambda r: -float(r["p30p_hit"]))
    print(f"{'condition':40} {'n':>4} {'f/mo':>5} {'p30%':>5} {'p40%':>5} {'p80%':>5} {'avgMFE':>6} {'avgMAE':>6}")
    for r in year_all:
        print(f"{r['condition']:40} {r['n']:>4} {r['freq_per_month']:>5} {r['p30p_hit']:>5} {r['p40p_hit']:>5} {r['p80p_hit']:>5} {r['avg_mfe_pips']:>6} {r['avg_mae_pips']:>6}")

if __name__ == "__main__":
    main()
