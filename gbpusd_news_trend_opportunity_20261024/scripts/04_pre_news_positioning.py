#!/usr/bin/env python3
"""Pre-news positioning study.

For every HIGH-impact USD or GBP event in the research calendar,
compute GBPUSD directional travel on the preceding trading days, in the
pre-release hours of the release-day London session, and the first-hour
reaction after the release. Then classify each event as:

    PRE_RUN_INTO_NEWS       — >=30p drift T-1/T-release-London in one dir
    PRE_RUN_REVERSED        — pre-run then opposite direction >=20p at release
    PRE_RUN_CONTINUED       — pre-run then same direction >=20p at release
    NO_MATERIAL_PRE_RUN     — pre-run <30p
    DATA_GAP                — missing candles for required windows

Outputs:
    pre_news_positioning.csv  — one row per HIGH event
    forecast_direction_analysis.csv — placeholder (forecast data unavailable)
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent.parent
CAL = HERE / "outputs" / "news_calendar.csv"
POPA = HERE / "inputs" / "census.csv"
OUT1 = HERE / "outputs" / "pre_news_positioning.csv"
OUT2 = HERE / "outputs" / "forecast_direction_analysis.csv"

MID_2026 = Path("/opt/tradingbot/data/candles/GBPUSD")        # 2026 mid
BID_LEGACY = Path("/opt/tradingbot/data/candles_ext_v2/GBPUSD")  # 2024-25 bid

def candle_path(d: dt.date) -> Optional[Path]:
    p1 = MID_2026 / f"{d.isoformat()}.csv"
    if p1.exists(): return p1
    p2 = BID_LEGACY / f"{d.isoformat()}.csv"
    if p2.exists(): return p2
    return None

def load_day(d: dt.date):
    p = candle_path(d)
    if p is None: return None
    rows = []
    with p.open() as fp:
        r = csv.DictReader(fp)
        for row in r:
            ts = row["timestamp"].replace(" ", "T")
            # normalise to UTC naive dt
            if "+" in ts:
                tt = dt.datetime.fromisoformat(ts).astimezone(dt.timezone.utc).replace(tzinfo=None)
            else:
                tt = dt.datetime.fromisoformat(ts)
            try:
                o = float(row["open"]); h = float(row["high"])
                l = float(row["low"]); c = float(row["close"])
            except Exception:
                continue
            rows.append((tt, o, h, l, c))
    return rows if rows else None

def _pips(price_delta: float) -> float:
    """CSV prices are already in pips with 2-decimal sub-pip precision
    (e.g. 12730.90 — matching Pop B qualifying rule where 1 pip = 1 unit).
    Delta is therefore the pip movement directly."""
    return price_delta

def price_at(day_rows, t_hhmm: str, how="close") -> Optional[float]:
    """Closest-at-or-before bar with timestamp HH:MM UTC on that day."""
    if not day_rows: return None
    h, m = int(t_hhmm[:2]), int(t_hhmm[3:5])
    target = day_rows[0][0].replace(hour=h, minute=m, second=0, microsecond=0)
    best = None
    for (ts, o, _, _, c) in day_rows:
        if ts > target: break
        best = (ts, o, c)
    if best is None: return None
    return best[2] if how == "close" else best[1]

def mfe(day_rows, from_hhmm: str, to_hhmm: str) -> dict:
    """Max favourable up/down over window; returns anchor price, up_pips, down_pips."""
    if not day_rows: return {}
    h0, m0 = int(from_hhmm[:2]), int(from_hhmm[3:5])
    h1, m1 = int(to_hhmm[:2]), int(to_hhmm[3:5])
    anchor_ts = day_rows[0][0].replace(hour=h0, minute=m0, second=0, microsecond=0)
    end_ts = day_rows[0][0].replace(hour=h1, minute=m1, second=0, microsecond=0)
    anchor_open = None
    hi = -1e18; lo = 1e18
    for (ts, o, h, l, c) in day_rows:
        if ts < anchor_ts: continue
        if ts > end_ts: break
        if anchor_open is None: anchor_open = o
        hi = max(hi, h); lo = min(lo, l)
    if anchor_open is None: return {}
    return {
        "anchor_open": anchor_open,
        "window_high": hi, "window_low": lo,
        "up_pips": _pips(hi - anchor_open),
        "down_pips": _pips(anchor_open - lo),
    }

def net_move_pips(day_rows, from_hhmm: str, to_hhmm: str) -> Optional[float]:
    if not day_rows: return None
    h0, m0 = int(from_hhmm[:2]), int(from_hhmm[3:5])
    h1, m1 = int(to_hhmm[:2]), int(to_hhmm[3:5])
    a_ts = day_rows[0][0].replace(hour=h0, minute=m0, second=0, microsecond=0)
    b_ts = day_rows[0][0].replace(hour=h1, minute=m1, second=0, microsecond=0)
    a_open = None; b_close = None
    for (ts, o, h, l, c) in day_rows:
        if ts == a_ts: a_open = o
        if ts == b_ts: b_close = c
    if a_open is None or b_close is None: return None
    return _pips(b_close - a_open)

def prev_trading_day(d: dt.date, n: int = 1) -> dt.date:
    out = d
    k = 0
    while k < n:
        out -= dt.timedelta(days=1)
        if out.weekday() < 5:
            k += 1
    return out

def main():
    # Load calendar — HIGH USD + GBP only
    events = []
    with CAL.open() as fp:
        for r in csv.DictReader(fp):
            if r["impact"] != "HIGH": continue
            if r["currency"] not in ("USD", "GBP"): continue
            if not r["scheduled_time_utc"]: continue
            events.append(r)
    print(f"HIGH events: {len(events)}")

    # ---------- Pre-news positioning per event ----------
    out = []
    for e in events:
        d = dt.date.fromisoformat(e["date"])
        hhmm = e["scheduled_time_utc"]
        # Only use events during (or around) weekday trading hours
        if d.weekday() >= 5: continue

        # T-1 full-day move
        try:
            tm1 = prev_trading_day(d, 1)
            tm2 = prev_trading_day(d, 2)
        except Exception:
            continue
        rows_tm1 = load_day(tm1)
        rows_tm2 = load_day(tm2)
        rows_t   = load_day(d)
        if rows_tm1 is None or rows_t is None:
            out.append({
                "date": e["date"], "scheduled_time_utc": hhmm, "currency": e["currency"],
                "event": e["event"], "source": e["source"],
                "classification": "DATA_GAP",
            })
            continue

        # T-1 London AM window move 06:00 → 11:00 UTC
        tm1_london_am = net_move_pips(rows_tm1, "06:00", "11:00") or 0.0
        # T-1 full day move (anchor 06:00 → close 21:00)
        tm1_full = net_move_pips(rows_tm1, "06:00", "21:00") or 0.0
        # T-2 full day move
        tm2_full = (net_move_pips(rows_tm2, "06:00", "21:00") if rows_tm2 else 0.0) or 0.0

        # T-day pre-release move: 06:00 UTC → event-time
        t_pre = net_move_pips(rows_t, "06:00", hhmm) or 0.0
        # T-day first hour after release
        try:
            h, m = int(hhmm[:2]), int(hhmm[3:5])
            end_h = h + 1
            end_hhmm = f"{end_h:02d}:{m:02d}"
            t_post = net_move_pips(rows_t, hhmm, end_hhmm) or 0.0
        except Exception:
            t_post = 0.0

        # Determine positioning: use combined T-1 London AM + T-day pre-release
        pre_run = tm1_london_am + t_pre
        pre_sign = 1 if pre_run > 0 else (-1 if pre_run < 0 else 0)
        post_sign = 1 if t_post > 0 else (-1 if t_post < 0 else 0)

        if abs(pre_run) < 30:
            cls = "NO_MATERIAL_PRE_RUN"
        elif abs(t_post) < 20:
            cls = "PRE_RUN_FADE_AT_RELEASE"
        elif pre_sign == post_sign:
            cls = "PRE_RUN_CONTINUED"
        else:
            cls = "PRE_RUN_REVERSED"

        out.append({
            "date": e["date"], "scheduled_time_utc": hhmm, "currency": e["currency"],
            "event": e["event"], "source": e["source"],
            "tm2_full_day_pips": round(tm2_full, 1),
            "tm1_full_day_pips": round(tm1_full, 1),
            "tm1_london_am_pips": round(tm1_london_am, 1),
            "t_pre_release_pips": round(t_pre, 1),
            "pre_run_combined_pips": round(pre_run, 1),
            "t_post_release_1h_pips": round(t_post, 1),
            "classification": cls,
        })

    cols = ["date","scheduled_time_utc","currency","event","source",
            "tm2_full_day_pips","tm1_full_day_pips","tm1_london_am_pips",
            "t_pre_release_pips","pre_run_combined_pips","t_post_release_1h_pips",
            "classification"]
    with OUT1.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        for r in out:
            # fill missing keys with ""
            for k in cols:
                r.setdefault(k, "")
            w.writerow(r)
    print(f"wrote {len(out)} event rows -> {OUT1}")

    # Summary
    import collections
    cnt = collections.Counter(r["classification"] for r in out)
    total = len(out)
    print("\nClassification distribution:")
    for k, v in cnt.most_common():
        print(f"  {k:28} {v:4}  {v/total*100:5.1f}%")

    # By event-family
    def family(ev: str) -> str:
        s = ev.lower()
        if "nfp" in s or "non.farm" in s or "nonfarm" in s: return "NFP"
        if "fomc" in s or "fed interest" in s or "federal funds" in s: return "FOMC"
        if "boe" in s or "mpc" in s or "bank of england" in s: return "BOE"
        if "cpi" in s or "inflation rate" in s: return "CPI"
        if "gdp" in s: return "GDP"
        if "employ" in s or "claimant" in s or "jobs" in s or "unemployment" in s or "earnings" in s: return "JOBS"
        if "retail" in s: return "RETAIL"
        if "pmi" in s or "ism" in s: return "PMI"
        return "OTHER"

    print("\nBy family × classification (year=all):")
    fam_counts = {}
    for r in out:
        f = family(r["event"])
        fam_counts.setdefault(f, collections.Counter())[r["classification"]] += 1
    for f, c in sorted(fam_counts.items(), key=lambda kv: -sum(kv[1].values())):
        total_f = sum(c.values())
        pre_run = c.get("PRE_RUN_CONTINUED", 0) + c.get("PRE_RUN_REVERSED", 0) + c.get("PRE_RUN_FADE_AT_RELEASE", 0)
        print(f"  {f:8} n={total_f:3} with_pre_run={pre_run:3} ({pre_run/total_f*100:4.1f}%) "
              f"cont={c.get('PRE_RUN_CONTINUED',0):3} rev={c.get('PRE_RUN_REVERSED',0):3} fade={c.get('PRE_RUN_FADE_AT_RELEASE',0):3} gap={c.get('DATA_GAP',0):3}")

    # ---------- Placeholder forecast analysis — data unavailable ----------
    with OUT2.open("w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["event_family","year","forecast_available","n_events","note"])
        w.writerow(["ALL","2024","no","-","Finnhub cache absent for 2024; synthetic template has no forecast; historical forecast integrity cannot be guaranteed retroactively"])
        w.writerow(["ALL","2025","no","-","Same as 2024 — no point-in-time forecast cache"])
        w.writerow(["ALL","2026","no","-","Finnhub local cache strips forecast/estimate/actual/prev before persistence"])
    print(f"wrote forecast placeholder -> {OUT2}")

if __name__ == "__main__":
    main()
