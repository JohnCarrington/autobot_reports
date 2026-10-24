#!/usr/bin/env python3
"""Stage 1 — GBPUSD 80-pip session-move census.

Rule (sole qualifying condition):
    movement_in_pips = close_of_(16:55 UK) - open_of_(07:00 UK)
    qualifies iff movement >= +80 (UP) or <= -80 (DOWN)

Integer arithmetic: stored prices have a .1/.5 fractional component, so we
multiply by 10 to shift to integer tenths-of-pip and compare against 800.
No floating-point used anywhere in the qualifying path.

UK clock is the real historical calendar:
    GMT: last Sunday of October 23:00 UTC → last Sunday of March 01:00 UTC
    BST: otherwise
    GMT dates → UTC window 07:00..16:55
    BST dates → UTC window 06:00..15:55

This script ONLY reads timestamp, open and close. It never reads high or
low. (Verified mechanically by 02_verify.py §3.)
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

CANDLES_EXT = Path("<autobot_prod_root>/data/candles_ext_v2/GBPUSD")  # 2024-25 bid
CANDLES_26  = Path("<autobot_prod_root>/data/candles/GBPUSD")           # 2026 mid
OUTDIR = Path("<research_workspace>/outputs")
OUTDIR.mkdir(parents=True, exist_ok=True)

QUALIFY_HUNDREDTHS = 8000  # 80 pips expressed in hundredths-of-pip (sub-pip × 10)
MISSING_FLAG_PCT = 10  # flag if > 10% bars missing


# ─── Calendar helpers ─────────────────────────────────────────────────
def _last_sunday(year: int, month: int) -> dt.date:
    d = dt.date(year, month, 1)
    # advance to last day of month
    nxt = dt.date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
    last = nxt - dt.timedelta(days=1)
    while last.weekday() != 6:
        last -= dt.timedelta(days=1)
    return last


def _is_bst(d: dt.date) -> bool:
    # BST starts last Sun March at 01:00 UTC, ends last Sun Oct at 01:00 UTC.
    # For a *date*, BST applies if the date is on or after the March Sunday and
    # before the October Sunday. (Edge cases on the exact Sundays themselves:
    # we treat 07:00 UK on the DST change date; by 07:00 UK the clock has
    # already settled, so simply using the date boundary is correct.)
    mar = _last_sunday(d.year, 3)
    oct_ = _last_sunday(d.year, 10)
    return mar <= d < oct_


# ─── UK bank holidays (England & Wales) 2024-2026 ─────────────────────
UK_BANK_HOLIDAYS = {
    # 2024
    "2024-01-01",  # New Year's Day
    "2024-03-29",  # Good Friday
    "2024-04-01",  # Easter Monday
    "2024-05-06",  # Early May
    "2024-05-27",  # Spring
    "2024-08-26",  # Summer
    "2024-12-25",  # Christmas Day
    "2024-12-26",  # Boxing Day
    # 2025
    "2025-01-01",
    "2025-04-18",  # Good Friday
    "2025-04-21",
    "2025-05-05",
    "2025-05-26",
    "2025-08-25",
    "2025-12-25",
    "2025-12-26",
    # 2026
    "2026-01-01",
    "2026-04-03",  # Good Friday
    "2026-04-06",
    "2026-05-04",
    "2026-05-25",
    "2026-08-31",
    "2026-12-25",
    "2026-12-28",  # Boxing Day substitute (26 Dec 2026 is Saturday)
}

FESTIVE_FLAGS = set()
for y in (2024, 2025, 2026):
    FESTIVE_FLAGS.add(f"{y}-12-24")  # Christmas Eve
    FESTIVE_FLAGS.add(f"{y}-12-31")  # New Year's Eve
# Christmas Day, Boxing Day, NY Day already in UK_BANK_HOLIDAYS; they'll be
# flagged via bank-holiday flag too.


# ─── Price parsing with integer arithmetic ────────────────────────────
from decimal import Decimal, ROUND_HALF_EVEN

def _price_to_hundredths(price_str: str) -> int:
    """Parse a stored price (prices × 10000, with up to 2dp of sub-pip
    resolution) and return it as an integer in hundredths-of-pip.

    One pip = 100 hundredths. Qualifying threshold: abs(delta) >= 8000.

    Uses Decimal to avoid any float round-tripping. Some CSV values arrive
    as float-serialised strings with ulp noise like '13202.400000000001';
    we quantize to 0.01 using banker's rounding so sub-cent noise is
    discarded without introducing float arithmetic.
    """
    d = Decimal(price_str.strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    # d is now exactly e.g. Decimal('12727.50'); shift by *100 to int.
    scaled = d * Decimal(100)
    # Assert exactness: scaled should be an integer.
    if scaled != scaled.to_integral_value():
        raise ValueError(f"Unexpected scale in {price_str!r} → {scaled}")
    return int(scaled)


# ─── Session-window computation ───────────────────────────────────────
def session_bounds_utc(d: dt.date):
    if _is_bst(d):
        return "BST", "06:00", "15:55", 6, 15  # open hh, close hh (both UTC)
    return "GMT", "07:00", "16:55", 7, 16


def _target_hhmm(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


# ─── Day analysis ─────────────────────────────────────────────────────
def analyse_day(folder: Path, date: dt.date, basis: str):
    uk_clock, utc_open_s, utc_close_s, open_hour, close_hour = session_bounds_utc(date)
    expected_open = _target_hhmm(open_hour, 0)
    expected_close = _target_hhmm(close_hour, 55)

    path = folder / f"{date.isoformat()}.csv"
    if not path.exists():
        return {
            "date": date.isoformat(), "uk_clock": uk_clock,
            "utc_open_time": f"{expected_open}:00",
            "utc_close_time": f"{expected_close}:00",
            "open_price": None, "close_price": None,
            "movement_pips": None, "direction": None,
            "qualifies": "EXCLUDED", "source_folder": folder.name,
            "price_basis": basis, "flags": "",
            "exclusion_reason": "FILE_MISSING",
        }

    # Scan the file ONLY reading timestamp, open, close.
    found_open = None   # (ts, open_str)
    found_close = None  # (ts, close_str)
    bars_in_session_window = 0

    with path.open() as f:
        rdr = csv.reader(f)
        header = next(rdr)
        try:
            idx_ts = header.index("timestamp")
            idx_open = header.index("open")
            idx_close = header.index("close")
        except ValueError:
            return {
                "date": date.isoformat(), "uk_clock": uk_clock,
                "utc_open_time": f"{expected_open}:00",
                "utc_close_time": f"{expected_close}:00",
                "open_price": None, "close_price": None,
                "movement_pips": None, "direction": None,
                "qualifies": "EXCLUDED", "source_folder": folder.name,
                "price_basis": basis, "flags": "",
                "exclusion_reason": "UNEXPECTED_HEADER",
            }
        # IMPORTANT: this is the only place prices are read.
        # We NEVER touch high or low — field positions 2 (high) and 3 (low)
        # are deliberately not consulted.
        assert header[idx_open] == "open" and header[idx_close] == "close"
        for r in rdr:
            if not r:
                continue
            ts = r[idx_ts]
            # ts format: "YYYY-MM-DD HH:MM:SS+00:00" or "YYYY-MM-DDTHH:MM:SS+00:00"
            hhmm = ts[11:16]
            if hhmm == expected_open:
                found_open = (ts, r[idx_open])
            if hhmm == expected_close:
                found_close = (ts, r[idx_close])
            # Count bars inside session window
            try:
                hh = int(hhmm[:2]); mm = int(hhmm[3:5])
                tot = hh * 60 + mm
                open_total = open_hour * 60
                close_total = close_hour * 60 + 55
                if open_total <= tot <= close_total:
                    bars_in_session_window += 1
            except Exception:
                pass

    flags = []
    if date.isoformat() in UK_BANK_HOLIDAYS:
        flags.append("UK_BANK_HOLIDAY")
    if date.isoformat() in FESTIVE_FLAGS:
        flags.append("FESTIVE")
    # Session should have 120 bars (120*5 min = 600 min = 10 hours).
    expected_bars = 120
    pct_missing = (expected_bars - bars_in_session_window) * 100 / expected_bars
    if pct_missing > MISSING_FLAG_PCT:
        flags.append(f"MISSING_{int(pct_missing)}PCT")

    if found_open is None or found_close is None:
        reason = []
        if found_open is None: reason.append("NO_0700_UK_CANDLE")
        if found_close is None: reason.append("NO_1655_UK_CANDLE")
        return {
            "date": date.isoformat(), "uk_clock": uk_clock,
            "utc_open_time": f"{expected_open}:00",
            "utc_close_time": f"{expected_close}:00",
            "open_price": found_open[1] if found_open else None,
            "close_price": found_close[1] if found_close else None,
            "movement_pips": None, "direction": None,
            "qualifies": "EXCLUDED", "source_folder": folder.name,
            "price_basis": basis,
            "flags": ";".join(flags),
            "exclusion_reason": ";".join(reason),
        }

    # Integer arithmetic qualifying path:
    open_h = _price_to_hundredths(found_open[1])
    close_h = _price_to_hundredths(found_close[1])
    movement_h = close_h - open_h  # pure int in hundredths-of-pip
    # Qualifying threshold: 80 pips = 8000 hundredths.
    direction = None
    if movement_h >= QUALIFY_HUNDREDTHS:
        qualifies = "YES"
        direction = "UP"
    elif movement_h <= -QUALIFY_HUNDREDTHS:
        qualifies = "YES"
        direction = "DOWN"
    else:
        qualifies = "NO"
        direction = ""

    return {
        "date": date.isoformat(), "uk_clock": uk_clock,
        "utc_open_time": f"{expected_open}:00",
        "utc_close_time": f"{expected_close}:00",
        "open_price": found_open[1], "close_price": found_close[1],
        "movement_pips": _hundredths_to_display(movement_h),
        "movement_hundredths": movement_h,
        "direction": direction,
        "qualifies": qualifies,
        "source_folder": folder.name,
        "price_basis": basis,
        "flags": ";".join(flags),
        "exclusion_reason": "",
    }


def _hundredths_to_display(h: int) -> str:
    """Render hundredths-of-pip as 'NN.NN' string (whole-pip and 2dp fraction)."""
    sign = "-" if h < 0 else ""
    a = abs(h)
    return f"{sign}{a // 100}.{a % 100:02d}"


# ─── Main driver ──────────────────────────────────────────────────────
def iter_weekdays(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def main():
    start = dt.date(2024, 1, 1)
    # Latest 2026 date present in the corpus
    latest_26 = max(p.stem for p in CANDLES_26.glob("*.csv"))
    end = dt.date.fromisoformat(latest_26)

    rows = []
    for d in iter_weekdays(start, end):
        if d.year <= 2025:
            folder, basis = CANDLES_EXT, "bid"
        else:
            folder, basis = CANDLES_26, "mid"
        r = analyse_day(folder, d, basis)
        rows.append(r)
    print(f"Analysed {len(rows)} weekdays "
          f"({start.isoformat()} → {end.isoformat()})")

    # Daily results (full)
    fields = ["date", "uk_clock", "utc_open_time", "utc_close_time",
              "open_price", "close_price", "movement_pips",
              "movement_hundredths", "direction", "qualifies",
              "source_folder", "price_basis", "flags", "exclusion_reason"]
    with (OUTDIR / "daily_results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            # fill missing keys
            for k in fields:
                r.setdefault(k, "")
            w.writerow({k: r[k] for k in fields})

    # Qualifying only
    quals = [r for r in rows if r["qualifies"] == "YES"]
    with (OUTDIR / "qualifying_days.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in quals:
            for k in fields:
                r.setdefault(k, "")
            w.writerow({k: r[k] for k in fields})

    # Weekly, monthly, yearly counts
    def write_counts(out_name, key_fn):
        agg = {}
        for r in rows:
            k = key_fn(r)
            d = agg.setdefault(k, {"days_analysed": 0, "up_days": 0, "down_days": 0,
                                     "excluded": 0, "qualifying_total": 0})
            if r["qualifies"] == "EXCLUDED":
                d["excluded"] += 1
            else:
                d["days_analysed"] += 1
                if r["qualifies"] == "YES":
                    if r["direction"] == "UP":
                        d["up_days"] += 1
                    elif r["direction"] == "DOWN":
                        d["down_days"] += 1
                    d["qualifying_total"] += 1
        with (OUTDIR / out_name).open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["period", "days_analysed", "up_days", "down_days",
                        "qualifying_total", "excluded"])
            for k in sorted(agg):
                v = agg[k]
                w.writerow([k, v["days_analysed"], v["up_days"], v["down_days"],
                            v["qualifying_total"], v["excluded"]])
        return agg

    def iso_week(r):
        d = dt.date.fromisoformat(r["date"])
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"

    def iso_month(r): return r["date"][:7]

    def iso_year(r): return r["date"][:4]

    agg_w = write_counts("counts_by_week.csv", iso_week)
    agg_m = write_counts("counts_by_month.csv", iso_month)
    agg_y = write_counts("counts_by_year.csv", iso_year)

    # Summary.md
    tot = len(rows)
    excluded = [r for r in rows if r["qualifies"] == "EXCLUDED"]
    analysed = tot - len(excluded)
    up_days = sum(1 for r in rows if r["qualifies"] == "YES" and r["direction"] == "UP")
    dn_days = sum(1 for r in rows if r["qualifies"] == "YES" and r["direction"] == "DOWN")
    qualifying = up_days + dn_days
    pct = (qualifying / analysed * 100) if analysed else 0.0

    # Movement averages (pips, computed from hundredths integer average)
    up_movements_h = [r["movement_hundredths"] for r in rows
                      if r["qualifies"] == "YES" and r["direction"] == "UP"]
    dn_movements_h = [r["movement_hundredths"] for r in rows
                      if r["qualifies"] == "YES" and r["direction"] == "DOWN"]
    avg_up = sum(up_movements_h) / len(up_movements_h) / 100 if up_movements_h else 0.0
    avg_dn = sum(dn_movements_h) / len(dn_movements_h) / 100 if dn_movements_h else 0.0

    # Count flagged
    flagged = [r for r in rows if r["flags"]]
    # Collect exclusions
    excl_detail = [(r["date"], r["exclusion_reason"], r["flags"]) for r in excluded]
    flagged_detail = [(r["date"], r["flags"], r["qualifies"]) for r in flagged]

    with (OUTDIR / "summary.md").open("w") as f:
        f.write("# GBPUSD 80-Pip Session Move — Stage 1 Summary\n\n")
        f.write(f"**Period:** {start.isoformat()} → {end.isoformat()}\n")
        f.write(f"**Session window (UK local):** 07:00 → 17:00 "
                "(open = OPEN of 07:00 UK candle; close = CLOSE of 16:55 UK candle)\n")
        f.write("**UTC window per clock:** GMT dates 07:00-16:55 UTC; "
                "BST dates 06:00-15:55 UTC. UK clock derived from the real "
                "historical BST calendar (BST = last Sun Mar → last Sun Oct).\n\n")
        f.write("## Price basis note\n\n")
        f.write("The price basis changes from BID to MID on 2026-01-01. "
                "No adjustment is applied; movement_pips and movement_hundredths "
                "are raw close-minus-open in each file's native basis.\n\n")
        f.write("## Headline counts\n\n")
        f.write(f"| | n |\n|---|---:|\n")
        f.write(f"| Weekdays scanned | {tot} |\n")
        f.write(f"| Analysed (open and 16:55 close present) | {analysed} |\n")
        f.write(f"| Excluded (missing candle) | {len(excluded)} |\n")
        f.write(f"| Qualifying UP (≥ +80 pips) | {up_days} |\n")
        f.write(f"| Qualifying DOWN (≤ −80 pips) | {dn_days} |\n")
        f.write(f"| Qualifying total | {qualifying} |\n")
        f.write(f"| **% of analysed days that qualify** | **{pct:.1f}%** |\n")
        f.write(f"| Avg movement of UP days | {avg_up:+.1f} pips |\n")
        f.write(f"| Avg movement of DOWN days | {avg_dn:+.1f} pips |\n\n")

        f.write("## Timestamp confirmation\n\n")
        f.write("Candle timestamps are UTC. This was confirmed by matching the "
                "price spike of five known Non-Farm Payrolls releases against "
                "the expected UTC release candle (winter: 13:30 UTC, summer: "
                "12:30 UTC). All five releases produced the largest-range candle "
                "exactly on the expected UTC bar — see `outputs/timestamp_check.txt`.\n\n")

        f.write("## Data coverage\n\n")
        f.write(f"| folder | files visible | basis |\n|---|---:|---|\n")
        f.write(f"| `<autobot_prod_root>/data/candles_ext_v2/GBPUSD/` | "
                f"{len(list(CANDLES_EXT.glob('*.csv')))} | bid |\n")
        f.write(f"| `<autobot_prod_root>/data/candles/GBPUSD/` | "
                f"{len(list(CANDLES_26.glob('*.csv')))} | mid |\n\n")

        f.write("## Flagged days (data still analysed)\n\n")
        if flagged_detail:
            f.write("| date | flags | qualifies |\n|---|---|---|\n")
            for d_, fl, q in flagged_detail:
                f.write(f"| {d_} | {fl} | {q} |\n")
        else:
            f.write("none\n")
        f.write("\n")

        f.write("## Excluded days\n\n")
        if excl_detail:
            f.write("| date | reason | flags |\n|---|---|---|\n")
            for d_, rsn, fl in excl_detail:
                f.write(f"| {d_} | {rsn} | {fl} |\n")
        else:
            f.write("none\n")

        f.write("\n## Known March 2026 gap\n\n")
        f.write("2026-03-02 → 2026-03-20 (15 consecutive weekdays) have no "
                "candle file in `<autobot_prod_root>/data/candles/GBPUSD/`. "
                "These are listed above as EXCLUDED with reason "
                "`FILE_MISSING`.\n\n")

        f.write("## Yearly totals\n\n")
        f.write("| year | days_analysed | up | down | qualifying | excluded |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for y in sorted(agg_y):
            v = agg_y[y]
            f.write(f"| {y} | {v['days_analysed']} | {v['up_days']} | "
                    f"{v['down_days']} | {v['qualifying_total']} | {v['excluded']} |\n")

    # Print to stdout
    print(f"Analysed: {analysed} ({pct:.1f}% qualify)  "
          f"UP: {up_days}  DOWN: {dn_days}  excluded: {len(excluded)}")
    print(f"Avg UP: {avg_up:+.1f}  Avg DOWN: {avg_dn:+.1f}")
    print(f"Flagged: {len(flagged_detail)}  Excluded (listed): {len(excl_detail)}")
    print(f"Outputs → {OUTDIR}")

if __name__ == "__main__":
    main()
