#!/usr/bin/env python3
"""Classify every weekday 2024-01-01 → 2026-10-24 as A..E news flags
and join against Pop A (census) and Pop B (qualifying_days).

Day-level flags (not mutually exclusive):
  A — major-news day (>=1 HIGH-impact USD or GBP event on this date)
  B — pre-news day     (next trading day has A)
  C — two-day pre-news (two trading days ahead has A)
  D — post-news day    (prev trading day was A)
  E — no-major-news    (not A, not B, not D)

Also records:
  n_events, n_high, n_high_usd, n_high_gbp
  release_window: {PRE_LONDON, LONDON_AM, LONDON_PM, NY_AM, NY_PM, OVERNIGHT}
  dual_session_high: multiple HIGH events across different sessions

Note on "major event" definition — HIGH impact (Finnhub rating) OR
one of the deterministic template events whose template impact is HIGH.
A deliberately conservative definition: HIGH-impact only.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CAL = HERE / "outputs" / "news_calendar.csv"
POPA = HERE / "inputs" / "census.csv"
POPB = HERE / "inputs" / "qualifying_days.csv"
OUT = HERE / "outputs" / "day_classification.csv"

def classify_time(hhmm: str) -> str:
    """Group a UTC HH:MM time into a session window."""
    if not hhmm or ":" not in hhmm:
        return "UNKNOWN"
    h, m = (int(x) for x in hhmm.split(":")[:2])
    tm = h * 60 + m
    # UK/UTC: London 07:00-11:00 UTC AM, 11:00-16:00 UTC PM. BST shifts -1h.
    # Simple grouping aligned with trading sessions (UTC):
    if tm < 6 * 60: return "OVERNIGHT"           # <06:00
    if tm < 11 * 60: return "LONDON_AM"           # 06:00-11:00
    if tm < 13 * 60: return "LONDON_PM"           # 11:00-13:00
    if tm < 16 * 60: return "NY_AM"               # 13:00-16:00
    if tm < 20 * 60: return "NY_PM"               # 16:00-20:00
    return "LATE"

def main():
    # Load calendar
    cal_by_date: dict[str, list[dict]] = {}
    with CAL.open() as fp:
        for r in csv.DictReader(fp):
            cal_by_date.setdefault(r["date"], []).append(r)

    # Load Pop A census — base for weekdays
    popa = {}
    with POPA.open() as fp:
        for r in csv.DictReader(fp):
            popa[r["date"]] = r
    # Load Pop B
    popb = {}
    with POPB.open() as fp:
        for r in csv.DictReader(fp):
            popb[r["date"]] = r

    # Enumerate weekdays Jan-01-2024 through Oct-24-2026
    start = dt.date(2024, 1, 1)
    end = dt.date(2026, 10, 24)
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += dt.timedelta(days=1)

    def is_major(date: str) -> bool:
        for e in cal_by_date.get(date, []):
            if e.get("impact") == "HIGH":
                return True
        return False

    # Previous / next trading day
    def prev_td(i: int) -> str | None:
        return days[i-1] if i > 0 else None
    def next_td(i: int) -> str | None:
        return days[i+1] if i < len(days) - 1 else None
    def plus2_td(i: int) -> str | None:
        return days[i+2] if i < len(days) - 2 else None

    out = []
    for i, date in enumerate(days):
        A = is_major(date)
        B = is_major(next_td(i) or "")
        C = is_major(plus2_td(i) or "")
        D = is_major(prev_td(i) or "")
        E = not (A or B or D)
        events = cal_by_date.get(date, [])
        n_events = len(events)
        n_high = sum(1 for e in events if e.get("impact") == "HIGH")
        n_high_usd = sum(1 for e in events if e.get("impact") == "HIGH" and e["currency"] == "USD")
        n_high_gbp = sum(1 for e in events if e.get("impact") == "HIGH" and e["currency"] == "GBP")
        high_events = [e for e in events if e.get("impact") == "HIGH"]
        high_names = ";".join(sorted({e["event"] for e in high_events}))[:200]
        windows = sorted({classify_time(e["scheduled_time_utc"]) for e in high_events})
        dual_session = len(windows) > 1 and "UNKNOWN" not in windows
        src = events[0]["source"] if events else ""

        pa = popa.get(date, {})
        pb = popb.get(date, {})
        out.append({
            "date": date,
            "weekday": dt.date.fromisoformat(date).strftime("%a"),
            "year": date[:4],
            # News flags
            "flag_major_news": int(A),
            "flag_pre_news_1d": int(B),
            "flag_pre_news_2d": int(C),
            "flag_post_news": int(D),
            "flag_no_major_news": int(E),
            "n_events": n_events,
            "n_high": n_high,
            "n_high_usd": n_high_usd,
            "n_high_gbp": n_high_gbp,
            "high_event_names": high_names,
            "release_windows": ",".join(windows),
            "dual_session_high": int(dual_session),
            "calendar_source": src,
            # Pop A fields
            "pop_a_in_set": int(bool(pa)),
            "pop_a_trend_day": int(pa.get("trend_day", "False") == "True"),
            "pop_a_direction": pa.get("direction", ""),
            "pop_a_pips": pa.get("pips", ""),
            "pop_a_anchor_time_utc": pa.get("anchor_time_utc", ""),
            "pop_a_peak_time_utc": pa.get("peak_time_utc", ""),
            "pop_a_pips_before_07_uk": pa.get("pips_before_07_uk", ""),
            "pop_a_consolidation": pa.get("consolidation", ""),
            # Pop B fields
            "pop_b_qualifies": int(pb.get("qualifies", "NO") == "YES"),
            "pop_b_direction": pb.get("direction", ""),
            "pop_b_movement_pips": pb.get("movement_pips", ""),
        })

    with OUT.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} day rows -> {OUT}")
    # Quick summary
    import collections
    tot = len(out)
    def pct(n): return f"{n/tot*100:.1f}%"
    print(f"total weekdays: {tot}")
    print(f"flag_major_news:    {sum(r['flag_major_news'] for r in out)} ({pct(sum(r['flag_major_news'] for r in out))})")
    print(f"flag_pre_news_1d:   {sum(r['flag_pre_news_1d'] for r in out)} ({pct(sum(r['flag_pre_news_1d'] for r in out))})")
    print(f"flag_post_news:     {sum(r['flag_post_news'] for r in out)} ({pct(sum(r['flag_post_news'] for r in out))})")
    print(f"flag_no_major_news: {sum(r['flag_no_major_news'] for r in out)} ({pct(sum(r['flag_no_major_news'] for r in out))})")
    print(f"pop_a_trend_day:    {sum(r['pop_a_trend_day'] for r in out)} ({pct(sum(r['pop_a_trend_day'] for r in out))})")
    print(f"pop_b_qualifies:    {sum(r['pop_b_qualifies'] for r in out)}")

if __name__ == "__main__":
    main()
