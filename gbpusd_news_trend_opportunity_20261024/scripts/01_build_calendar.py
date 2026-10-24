#!/usr/bin/env python3
"""Build the research news calendar for Jan 2024 → Oct 2026.

Data sources (ordered by preference per date):

1. **Finnhub daily cache (REAL)** — /opt/tradingbot/cache/news_state_finnhub_*.json
   Covers 2026-01-01 → 2026-10-24 (248 days). Each event carries:
       ts (UTC), currency, impact {HIGH|MED|LOW}, event name.
   The cache was written at the time of the trading day — this is
   point-in-time economic calendar data with real impact ratings.
   Finnhub does NOT populate forecast / actual / previous values in the
   locally cached state; so this field is empty for every event.

2. **Templated 2024-2025 (SYNTHETIC)** — hardcoded FOMC/BoE/ECB dates
   plus deterministic recurrence patterns (NFP 1st Friday, CPI mid-month).
   This covers 2024-2025 because no raw Finnhub cache exists for that
   range. Flagged `source='template_2024_2025'`. Forecast/actual/prev
   are NEVER populated for these entries. Use for occurrence detection
   only — not for surprise / forecast analysis.

The emitted file `news_calendar.csv` records:
    date, scheduled_time_utc, currency, event, impact, source,
    forecast, previous, actual, has_forecast
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "outputs" / "news_calendar.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

FINNHUB_DIR = Path("/opt/tradingbot/cache")

# ---------------------------------------------------------------------
# Hardcoded, publicly-verified Fed/BoE calendar dates (2024-2025)
# ---------------------------------------------------------------------
FOMC_2024_2025 = [
    ("2024-01-31", "19:00"), ("2024-03-20", "18:00"), ("2024-05-01", "18:00"),
    ("2024-06-12", "18:00"), ("2024-07-31", "18:00"), ("2024-09-18", "18:00"),
    ("2024-11-07", "19:00"), ("2024-12-18", "19:00"),
    ("2025-01-29", "19:00"), ("2025-03-19", "18:00"), ("2025-05-07", "18:00"),
    ("2025-06-18", "18:00"), ("2025-07-30", "18:00"), ("2025-09-17", "18:00"),
    ("2025-10-29", "18:00"), ("2025-12-10", "19:00"),
]
BOE_2024_2025 = [
    ("2024-02-01", "12:00"), ("2024-03-21", "12:00"), ("2024-05-09", "11:00"),
    ("2024-06-20", "11:00"), ("2024-08-01", "11:00"), ("2024-09-19", "11:00"),
    ("2024-11-07", "12:00"), ("2024-12-19", "12:00"),
    ("2025-02-06", "12:00"), ("2025-03-20", "12:00"), ("2025-05-08", "11:00"),
    ("2025-06-19", "11:00"), ("2025-08-07", "11:00"), ("2025-09-18", "11:00"),
    ("2025-11-06", "12:00"), ("2025-12-18", "12:00"),
]

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def weekday(d: dt.date) -> int:
    return d.weekday()  # 0=Mon

def first_friday(y: int, m: int) -> dt.date:
    d = dt.date(y, m, 1)
    while d.weekday() != 4:
        d += dt.timedelta(days=1)
    return d

def nth_weekday(y: int, m: int, weekday_idx: int, n: int) -> dt.date:
    d = dt.date(y, m, 1)
    while d.weekday() != weekday_idx:
        d += dt.timedelta(days=1)
    return d + dt.timedelta(days=7 * (n - 1))

def is_last_business_day(d: dt.date) -> bool:
    nd = d + dt.timedelta(days=1)
    while nd.weekday() >= 5:
        nd += dt.timedelta(days=1)
    return nd.month != d.month

def nth_business_day(y: int, m: int, n: int) -> dt.date:
    d = dt.date(y, m, 1)
    cnt = 0
    while cnt < n:
        if d.weekday() < 5:
            cnt += 1
            if cnt == n:
                return d
        d += dt.timedelta(days=1)
    return d  # unreachable

# ---------------------------------------------------------------------
# 1) Load real Finnhub events (2026)
# ---------------------------------------------------------------------
def load_finnhub() -> list[dict]:
    rows = []
    for fp in sorted(FINNHUB_DIR.glob("news_state_finnhub_*.json")):
        try:
            d = json.loads(fp.read_text())
        except Exception:
            continue
        date = d.get("date", "")
        for e in d.get("events", []):
            cur = (e.get("currency") or "").upper()
            if cur not in ("USD", "GBP"):
                continue
            ts = e.get("ts", "")
            # Parse UTC time from ISO ts
            try:
                tt = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                scheduled_time = tt.strftime("%H:%M")
            except Exception:
                scheduled_time = ""
            event = (e.get("event") or "").strip()
            impact = (e.get("impact") or "").upper()
            rows.append({
                "date": date,
                "scheduled_time_utc": scheduled_time,
                "currency": cur,
                "event": event,
                "impact": impact,
                "source": "finnhub_cache_pit",
                "forecast": "",
                "previous": "",
                "actual": "",
                "has_forecast": "0",
            })
    return rows

# ---------------------------------------------------------------------
# 2) Build synthetic 2024-2025 template
# ---------------------------------------------------------------------
def build_template_2024_2025() -> list[dict]:
    rows = []
    def add(d, hhmm, cur, event, impact, source="template_2024_2025"):
        rows.append({
            "date": d.isoformat(),
            "scheduled_time_utc": hhmm,
            "currency": cur,
            "event": event,
            "impact": impact,
            "source": source,
            "forecast": "",
            "previous": "",
            "actual": "",
            "has_forecast": "0",
        })
    for y in (2024, 2025):
        for m in range(1, 13):
            # NFP — first Friday 13:30 UTC (DST-naïve)
            add(first_friday(y, m), "13:30", "USD", "US_NFP", "HIGH")
            # US CPI — ~2nd Wed 13:30 UTC
            add(nth_weekday(y, m, 2, 2), "13:30", "USD", "US_CPI", "HIGH")
            # US PPI — ~3rd Wed 13:30 UTC
            add(nth_weekday(y, m, 2, 3), "13:30", "USD", "US_PPI", "MED")
            # US Retail Sales — ~15th
            try:
                rs = dt.date(y, m, 15)
                while rs.weekday() >= 5:
                    rs += dt.timedelta(days=1)
                add(rs, "13:30", "USD", "US_RETAIL_SALES", "MED")
            except Exception:
                pass
            # ISM Manu — 1st business day 15:00
            add(nth_business_day(y, m, 1), "15:00", "USD", "US_ISM_MANU", "MED")
            # ISM Svcs — 3rd business day 15:00
            add(nth_business_day(y, m, 3), "15:00", "USD", "US_ISM_SVCS", "MED")
            # UK CPI — 3rd Wed 07:00 UTC (approx; real time 06:00 UTC in summer)
            add(nth_weekday(y, m, 2, 3), "06:00", "GBP", "UK_CPI", "HIGH")
            # UK GDP monthly — 2nd Fri 06:00 UTC
            add(nth_weekday(y, m, 4, 2), "06:00", "GBP", "UK_GDP_MONTHLY", "HIGH")
            # UK Retail Sales — 3rd Fri
            add(nth_weekday(y, m, 4, 3), "06:00", "GBP", "UK_RETAIL_SALES", "MED")
            # UK Jobs — mid-month Tue
            try:
                jd = dt.date(y, m, 14)
                while jd.weekday() != 1:
                    jd += dt.timedelta(days=1)
                add(jd, "06:00", "GBP", "UK_JOBS", "MED")
            except Exception:
                pass
    for d, hh in FOMC_2024_2025:
        add(dt.date.fromisoformat(d), hh, "USD", "US_FOMC", "HIGH")
    for d, hh in BOE_2024_2025:
        add(dt.date.fromisoformat(d), hh, "GBP", "UK_BOE", "HIGH")
    return rows

# ---------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------
def main():
    fh_rows = load_finnhub()
    tpl_rows = build_template_2024_2025()
    # Dedup: finnhub takes precedence for its date range
    fh_dates = {r["date"] for r in fh_rows}
    tpl_rows = [r for r in tpl_rows if r["date"] not in fh_dates]
    rows = tpl_rows + fh_rows
    rows.sort(key=lambda r: (r["date"], r["scheduled_time_utc"]))
    with OUT.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=[
            "date", "scheduled_time_utc", "currency", "event",
            "impact", "source", "forecast", "previous", "actual",
            "has_forecast",
        ])
        w.writeheader()
        w.writerows(rows)
    # Summary
    import collections
    by_src = collections.Counter(r["source"] for r in rows)
    by_impact = collections.Counter(r["impact"] for r in rows)
    by_year = collections.Counter(r["date"][:4] for r in rows)
    print(f"wrote {len(rows)} events -> {OUT}")
    print("by source:", dict(by_src))
    print("by impact:", dict(by_impact))
    print("by year:", dict(by_year))

if __name__ == "__main__":
    main()
