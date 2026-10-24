#!/usr/bin/env python3
"""Build a unified daily news-impact table for the full corpus.

For 2026 we use the authoritative day_type_census file. For 2024-2025 we
construct a synthetic calendar from recurring high-impact events:

  * US NFP          — first Friday of every month, 13:30 UTC
  * US CPI          — ~mid-month, 13:30 UTC
  * US PPI          — ~mid-month after CPI
  * US FOMC         — 8 scheduled meetings per year (hardcoded)
  * US PCE          — late-month (28-31), 13:30 UTC
  * US ISM Manu PMI — 1st business day of month, 15:00 UTC
  * US ISM Svcs PMI — 3rd business day of month, 15:00 UTC
  * US Retail Sales — ~15-17th, 13:30 UTC
  * UK CPI          — 3rd Wed of month, 07:00 UTC
  * UK Retail Sales — 3rd Fri of month, 07:00 UTC
  * UK GDP          — 2nd Fri of each month (monthly), 07:00 UTC
  * UK PMI flash    — 23rd of month, 09:30 UTC
  * UK Jobs         — mid-month Tuesday, 07:00 UTC
  * BoE meetings    — ~8/year (hardcoded)
  * ECB meetings    — ~8/year (hardcoded) — minor for GBPUSD but marked

The output day-level label uses tiers:
  * BIG   — Tier 1 scheduled: NFP, FOMC, CPI (US/UK), BoE, GDP (UK), PCE
  * MED   — Tier 2: ISM, retail sales, PPI, jobs, PMI flash
  * none  — no major scheduled event

Also records PRE (day before BIG) and POST (day after BIG).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path("<research_workspace>/outputs")
TB_CENSUS = Path(
    "<autobot_prod_root>/reports-public/day_type_calendar_census_20260919/day_type_census.csv"
)

# ─────────────────────────────────────────────────────────────────────
# Hardcoded 2024-2025 FOMC & BoE meeting dates (publicly known).
# Verified against FOMC and BoE calendars.
# ─────────────────────────────────────────────────────────────────────
FOMC_DATES = {
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026 (schedule provided by Fed as of 2026-10)
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
}
BOE_DATES = {
    # 2024
    "2024-02-01", "2024-03-21", "2024-05-09", "2024-06-20",
    "2024-08-01", "2024-09-19", "2024-11-07", "2024-12-19",
    # 2025
    "2025-02-06", "2025-03-20", "2025-05-08", "2025-06-19",
    "2025-08-07", "2025-09-18", "2025-11-06", "2025-12-18",
    # 2026
    "2026-02-05", "2026-03-19", "2026-05-07", "2026-06-18",
    "2026-08-06", "2026-09-17", "2026-11-05", "2026-12-17",
}


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> dt.date:
    """Return the nth occurrence (1-based) of a given weekday in a month."""
    d = dt.date(year, month, 1)
    first_offset = (weekday - d.weekday()) % 7
    d = d + dt.timedelta(days=first_offset + 7 * (n - 1))
    if d.month != month:
        return None
    return d


def _business_days_in_month_from_start(year: int, month: int, nth: int) -> dt.date:
    """nth business day of the month."""
    d = dt.date(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == nth:
                return d
        d += dt.timedelta(days=1)
        if d.month != month:
            return None


def synthetic_events(start: dt.date, end: dt.date):
    """Yield (date_iso, event_name, tier) for a known-event schedule."""
    d = start.replace(day=1)
    while d <= end:
        y, m = d.year, d.month

        # US NFP — first Friday
        nfp = _nth_weekday_of_month(y, m, 4, 1)  # Fri = 4
        if nfp and start <= nfp <= end:
            yield nfp.isoformat(), "US_NFP", "BIG"

        # US CPI — 2nd Tuesday or 2nd Wednesday, use 2nd Wednesday as proxy
        cpi = _nth_weekday_of_month(y, m, 2, 2)  # Wed = 2
        if cpi and start <= cpi <= end:
            yield cpi.isoformat(), "US_CPI", "BIG"

        # US PPI — 2nd Thursday
        ppi = _nth_weekday_of_month(y, m, 3, 2)
        if ppi and start <= ppi <= end:
            yield ppi.isoformat(), "US_PPI", "MED"

        # US Retail Sales — around 15-17th, use 3rd Thu
        rs = _nth_weekday_of_month(y, m, 3, 3)
        if rs and start <= rs <= end:
            yield rs.isoformat(), "US_RETAIL_SALES", "MED"

        # US PCE — last business day of month
        last_bd = dt.date(y, m, 28)
        while last_bd.month == m:
            if last_bd.weekday() < 5:
                pce = last_bd
            last_bd += dt.timedelta(days=1)
        pce = pce if 'pce' in dir() else None
        if pce and start <= pce <= end:
            yield pce.isoformat(), "US_PCE", "BIG"

        # US ISM Manufacturing — 1st business day
        ism_m = _business_days_in_month_from_start(y, m, 1)
        if ism_m and start <= ism_m <= end:
            yield ism_m.isoformat(), "US_ISM_MANU", "MED"
        # ISM Services — 3rd business day
        ism_s = _business_days_in_month_from_start(y, m, 3)
        if ism_s and start <= ism_s <= end:
            yield ism_s.isoformat(), "US_ISM_SERVICES", "MED"

        # UK CPI — 3rd Wednesday
        uk_cpi = _nth_weekday_of_month(y, m, 2, 3)
        if uk_cpi and start <= uk_cpi <= end:
            yield uk_cpi.isoformat(), "UK_CPI", "BIG"

        # UK Retail Sales — 3rd Friday
        uk_rs = _nth_weekday_of_month(y, m, 4, 3)
        if uk_rs and start <= uk_rs <= end:
            yield uk_rs.isoformat(), "UK_RETAIL_SALES", "MED"

        # UK monthly GDP — 2nd Friday
        uk_gdp = _nth_weekday_of_month(y, m, 4, 2)
        if uk_gdp and start <= uk_gdp <= end:
            yield uk_gdp.isoformat(), "UK_GDP_M", "MED"

        # UK Jobs — 2nd Tuesday
        uk_jobs = _nth_weekday_of_month(y, m, 1, 2)
        if uk_jobs and start <= uk_jobs <= end:
            yield uk_jobs.isoformat(), "UK_JOBS", "MED"

        # UK PMI flash — 23rd (if business day) else next bd
        pmi_date = dt.date(y, m, 23)
        while pmi_date.weekday() >= 5 and pmi_date.month == m:
            pmi_date += dt.timedelta(days=1)
        if pmi_date.month == m and start <= pmi_date <= end:
            yield pmi_date.isoformat(), "UK_PMI_FLASH", "MED"

        # FOMC
        for d_iso in FOMC_DATES:
            dd = dt.date.fromisoformat(d_iso)
            if dd.year == y and dd.month == m and start <= dd <= end:
                yield d_iso, "US_FOMC", "BIG"

        # BoE
        for d_iso in BOE_DATES:
            dd = dt.date.fromisoformat(d_iso)
            if dd.year == y and dd.month == m and start <= dd <= end:
                yield d_iso, "UK_BOE", "BIG"

        # Next month
        if m == 12:
            d = dt.date(y + 1, 1, 1)
        else:
            d = dt.date(y, m + 1, 1)


def load_2026_from_census() -> pd.DataFrame:
    """Expand the day_type_census into (date, event, tier) rows.

    The census stores events as JSON in the big_today_json / middle_today_json
    columns. We parse them and emit one row per (date, event_name).
    """
    df = pd.read_csv(TB_CENSUS)
    rows = []
    for _, r in df.iterrows():
        d = r["date"]
        for col, tier in [
            ("big_today_json", "BIG"),
            ("middle_today_json", "MED"),
        ]:
            raw = r.get(col, "[]")
            if pd.isna(raw) or not raw:
                continue
            try:
                events = json.loads(raw)
            except Exception:
                events = []
            for ev in events:
                rows.append({
                    "date": d,
                    "event": ev.get("event", "unknown"),
                    "currency": ev.get("currency", ""),
                    "tier": tier,
                    "source": "finnhub_2026",
                })
    return pd.DataFrame(rows)


def main():
    rows = []
    synth_start = dt.date(2024, 1, 1)
    synth_end = dt.date(2025, 12, 31)
    for d, name, tier in synthetic_events(synth_start, synth_end):
        rows.append({
            "date": d, "event": name, "currency":
                ("USD" if name.startswith("US_") else "GBP"
                 if name.startswith("UK_") else ""),
            "tier": tier, "source": "synthetic_2024_2025",
        })
    synth = pd.DataFrame(rows)

    cal_2026 = load_2026_from_census()

    cal = pd.concat([synth, cal_2026], ignore_index=True)
    cal = cal.drop_duplicates(subset=["date", "event", "currency"]).sort_values(["date", "tier"])
    cal.to_csv(ROOT / "calendar_events.csv", index=False)

    # Daily label: BIG > MED > NORMAL. Also compute PRE/POST relative to BIG.
    daily = cal.groupby("date").agg(
        n_events=("event", "count"),
        has_big=("tier", lambda s: (s == "BIG").any()),
        has_med=("tier", lambda s: (s == "MED").any()),
        currencies=("currency", lambda s: ",".join(sorted(set(s.dropna())))),
        tier_mix=("tier", lambda s: ",".join(sorted(set(s)))),
    ).reset_index()
    daily["label"] = "NORMAL"
    daily.loc[daily.has_med, "label"] = "MID_NEWS"
    daily.loc[daily.has_big, "label"] = "BIG_NEWS"

    # Add PRE / POST
    all_dates = pd.date_range("2024-01-01", "2026-10-07", freq="D")
    frame = pd.DataFrame({"date": [d.date().isoformat() for d in all_dates]})
    frame = frame.merge(daily, on="date", how="left")
    frame["label"] = frame["label"].fillna("NORMAL")
    big_mask = frame["label"] == "BIG_NEWS"
    frame["pre_big"] = big_mask.shift(-1).fillna(False)
    frame["post_big"] = big_mask.shift(1).fillna(False)
    # Compose extended label
    def ext(r):
        if r.label == "BIG_NEWS":   return "BIG_NEWS"
        if r.label == "MID_NEWS":   return "MID_NEWS"
        if r.pre_big:               return "PRE_NEWS"
        if r.post_big:              return "POST_NEWS"
        return "NORMAL"
    frame["ext_label"] = frame.apply(ext, axis=1)
    frame.to_csv(ROOT / "calendar_daily.csv", index=False)

    print(f"Events: {len(cal)}")
    print(f"Daily rows: {len(frame)}")
    print(frame.ext_label.value_counts())


if __name__ == "__main__":
    main()
