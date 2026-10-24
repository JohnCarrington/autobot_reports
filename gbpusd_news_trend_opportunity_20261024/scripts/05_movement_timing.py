#!/usr/bin/env python3
"""Movement-start timing analysis.

For Pop A trend days, use the census anchor_time_utc + peak_time_utc.
For Pop B qualifying days, scan M5 chronologically within 06:00..17:00 UTC
and find the largest contiguous one-directional swing — record swing start
and peak time.

Session buckets (UTC):
    PRE_LONDON    < 06:00
    LONDON_AM     06:00 - 11:00
    LONDON_PM     11:00 - 13:00
    NY_AM         13:00 - 16:00
    NY_PM         16:00 - 20:00
    LATE          20:00 +

Outputs:
    news_movement_timing.csv — one row per Pop A or Pop B qualifying day
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent.parent
POPA = HERE / "inputs" / "census.csv"
POPB = HERE / "inputs" / "qualifying_days.csv"
CAL = HERE / "outputs" / "news_calendar.csv"
OUT = HERE / "outputs" / "news_movement_timing.csv"

MID_2026 = Path("/opt/tradingbot/data/candles/GBPUSD")
BID_LEGACY = Path("/opt/tradingbot/data/candles_ext_v2/GBPUSD")

def session_bucket(hhmm: str) -> str:
    if not hhmm: return "UNKNOWN"
    try:
        h, m = int(hhmm[:2]), int(hhmm[3:5])
    except Exception:
        return "UNKNOWN"
    t = h * 60 + m
    if t < 6 * 60: return "PRE_LONDON"
    if t < 11 * 60: return "LONDON_AM"
    if t < 13 * 60: return "LONDON_PM"
    if t < 16 * 60: return "NY_AM"
    if t < 20 * 60: return "NY_PM"
    return "LATE"

def session_from_ts(ts_iso: str) -> str:
    """Pull HH:MM UTC from an ISO ts and bucket."""
    if not ts_iso: return "UNKNOWN"
    try:
        tt = dt.datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        if tt.tzinfo is not None:
            tt = tt.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return session_bucket(tt.strftime("%H:%M"))
    except Exception:
        return "UNKNOWN"

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

def swing_in_window(day_rows, start_hhmm: str, end_hhmm: str):
    """Find the largest one-directional close-to-close swing within window."""
    if not day_rows: return None
    h0, m0 = int(start_hhmm[:2]), int(start_hhmm[3:5])
    h1, m1 = int(end_hhmm[:2]), int(end_hhmm[3:5])
    start_t = day_rows[0][0].replace(hour=h0, minute=m0, second=0, microsecond=0)
    end_t = day_rows[0][0].replace(hour=h1, minute=m1, second=0, microsecond=0)
    in_window = [(ts, o, h, l, c) for (ts, o, h, l, c) in day_rows if start_t <= ts <= end_t]
    if not in_window: return None
    # Find biggest UP swing: argmax(h_i) - argmin(l_j) with i > j (anchor<peak)
    best_up = (0.0, None, None)
    min_l = in_window[0][3]; min_ts = in_window[0][0]
    for (ts, o, h, l, c) in in_window:
        if l < min_l:
            min_l = l; min_ts = ts
        up = h - min_l
        if up > best_up[0]:
            best_up = (up, min_ts, ts)
    # Biggest DOWN swing: argmax(h_i) - argmin(l_j) with j > i
    best_dn = (0.0, None, None)
    max_h = in_window[0][2]; max_ts = in_window[0][0]
    for (ts, o, h, l, c) in in_window:
        if h > max_h:
            max_h = h; max_ts = ts
        dn = max_h - l
        if dn > best_dn[0]:
            best_dn = (dn, max_ts, ts)
    if best_up[0] >= best_dn[0]:
        return ("UP", best_up[0], best_up[1], best_up[2])
    return ("DOWN", best_dn[0], best_dn[1], best_dn[2])

def main():
    # Load calendar — HIGH events keyed by date
    high_by_date: dict[str, list[dict]] = {}
    with CAL.open() as fp:
        for r in csv.DictReader(fp):
            if r["impact"] == "HIGH":
                high_by_date.setdefault(r["date"], []).append(r)

    out = []
    # ---------- Pop A ----------
    with POPA.open() as fp:
        for r in csv.DictReader(fp):
            if r["trend_day"] != "True": continue
            anchor_ts = r.get("anchor_time_utc", "")
            peak_ts = r.get("peak_time_utc", "")
            anchor_sess = session_from_ts(anchor_ts)
            peak_sess = session_from_ts(peak_ts)
            # Nearest HIGH event — time delta between anchor and nearest event
            events_today = high_by_date.get(r["date"], [])
            nearest_hhmm = ""
            nearest_cur = ""
            nearest_event = ""
            if events_today and anchor_ts:
                try:
                    anchor_tt = dt.datetime.fromisoformat(anchor_ts.replace("Z","+00:00")).astimezone(dt.timezone.utc).replace(tzinfo=None)
                    min_abs = None
                    for e in events_today:
                        try:
                            h, m = int(e["scheduled_time_utc"][:2]), int(e["scheduled_time_utc"][3:5])
                            ett = anchor_tt.replace(hour=h, minute=m, second=0, microsecond=0)
                            delta = (anchor_tt - ett).total_seconds() / 60.0  # minutes anchor-after-event
                            if min_abs is None or abs(delta) < abs(min_abs):
                                min_abs = delta
                                nearest_hhmm = e["scheduled_time_utc"]
                                nearest_cur = e["currency"]
                                nearest_event = e["event"][:80]
                        except Exception:
                            continue
                except Exception:
                    min_abs = None
            else:
                min_abs = None
            out.append({
                "population": "A",
                "date": r["date"], "direction": r["direction"],
                "pips": r["pips"],
                "anchor_time_utc": anchor_ts, "peak_time_utc": peak_ts,
                "anchor_session": anchor_sess, "peak_session": peak_sess,
                "nearest_high_event_time": nearest_hhmm,
                "nearest_high_event_currency": nearest_cur,
                "nearest_high_event_name": nearest_event,
                "anchor_minus_event_minutes": "" if min_abs is None else round(min_abs, 1),
                "n_high_events_today": len(events_today),
                "pips_before_07_uk": r.get("pips_before_07_uk", ""),
            })
    # ---------- Pop B ----------
    with POPB.open() as fp:
        for r in csv.DictReader(fp):
            if r["qualifies"] != "YES": continue
            d = dt.date.fromisoformat(r["date"])
            day_rows = load_day(d)
            # Qualifying window: GMT 07:00-16:55 UTC, BST 06:00-15:55 UTC
            is_bst = r["uk_clock"] == "BST"
            start_hhmm = "06:00" if is_bst else "07:00"
            end_hhmm = "15:55" if is_bst else "16:55"
            swing = swing_in_window(day_rows, start_hhmm, end_hhmm) if day_rows else None
            if swing:
                sw_dir, sw_sz, sw_start, sw_peak = swing
                anchor_sess = session_bucket(sw_start.strftime("%H:%M"))
                peak_sess = session_bucket(sw_peak.strftime("%H:%M"))
                anchor_time = sw_start.strftime("%Y-%m-%dT%H:%M:%S")
                peak_time = sw_peak.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                sw_dir, sw_sz, anchor_sess, peak_sess, anchor_time, peak_time = "", 0.0, "UNKNOWN", "UNKNOWN", "", ""
            events_today = high_by_date.get(r["date"], [])
            # Nearest event
            nearest_hhmm = ""; nearest_cur = ""; nearest_event = ""; min_abs = None
            if events_today and swing:
                for e in events_today:
                    try:
                        h, m = int(e["scheduled_time_utc"][:2]), int(e["scheduled_time_utc"][3:5])
                        ett = sw_start.replace(hour=h, minute=m, second=0, microsecond=0)
                        delta = (sw_start - ett).total_seconds() / 60.0
                        if min_abs is None or abs(delta) < abs(min_abs):
                            min_abs = delta
                            nearest_hhmm = e["scheduled_time_utc"]
                            nearest_cur = e["currency"]
                            nearest_event = e["event"][:80]
                    except Exception:
                        continue
            out.append({
                "population": "B",
                "date": r["date"], "direction": r["direction"],
                "pips": r["movement_pips"],
                "anchor_time_utc": anchor_time, "peak_time_utc": peak_time,
                "anchor_session": anchor_sess, "peak_session": peak_sess,
                "nearest_high_event_time": nearest_hhmm,
                "nearest_high_event_currency": nearest_cur,
                "nearest_high_event_name": nearest_event,
                "anchor_minus_event_minutes": "" if min_abs is None else round(min_abs, 1),
                "n_high_events_today": len(events_today),
                "pips_before_07_uk": "",
            })

    cols = ["population","date","direction","pips","anchor_time_utc","peak_time_utc",
            "anchor_session","peak_session","nearest_high_event_time","nearest_high_event_currency",
            "nearest_high_event_name","anchor_minus_event_minutes","n_high_events_today",
            "pips_before_07_uk"]
    with OUT.open("w", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} rows -> {OUT}")

    # Summary
    import collections
    for pop in ("A", "B"):
        subset = [r for r in out if r["population"] == pop]
        print(f"\n=== Pop {pop} anchor-session distribution (n={len(subset)}) ===")
        cnt = collections.Counter(r["anchor_session"] for r in subset)
        for k in ("PRE_LONDON","LONDON_AM","LONDON_PM","NY_AM","NY_PM","LATE","UNKNOWN"):
            v = cnt.get(k, 0)
            print(f"  {k:12} {v:4}  {v/max(len(subset),1)*100:5.1f}%")
        # % with a HIGH event anchor <= 60 min after
        with_news = sum(1 for r in subset if r["anchor_minus_event_minutes"] != "" and -60 <= float(r["anchor_minus_event_minutes"]) <= 120)
        print(f"  anchor within [-60,+120] min of a HIGH event: {with_news}/{len(subset)}  {with_news/max(len(subset),1)*100:.1f}%")

if __name__ == "__main__":
    main()
