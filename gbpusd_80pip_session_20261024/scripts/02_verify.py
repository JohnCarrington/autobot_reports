#!/usr/bin/env python3
"""Stage 1 — Independent verification.

Shares no code with 01_main_analysis.py. Instead of importing anything, it
re-derives the qualifying answer directly from the raw CSV rows and compares
to the main script's claims.

Verification steps:
    1. Recalculate 10 qualifying + 10 non-qualifying days, including two
       boundary cases (|movement| within 5 pips of 80).
    2. Walk every UK clock-change weekend in the dataset and confirm the
       UTC open/close windows the main analysis used.
    3. Mechanically scan the main-analysis source for high/low reads inside
       the qualifying path.
    4. Confirm weekly / monthly / yearly aggregates agree with
       daily_results.csv.

Output: full narrative to stdout; verification result log to
outputs/verification.txt.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path("<research_workspace>")
OUT = ROOT / "outputs"

DAILY = OUT / "daily_results.csv"
WEEKLY = OUT / "counts_by_week.csv"
MONTHLY = OUT / "counts_by_month.csv"
YEARLY = OUT / "counts_by_year.csv"
QUAL = OUT / "qualifying_days.csv"

CANDLES_EXT = Path("<autobot_prod_root>/data/candles_ext_v2/GBPUSD")
CANDLES_26  = Path("<autobot_prod_root>/data/candles/GBPUSD")

MAIN_SOURCE = ROOT / "01_main_analysis.py"


# ─────── Independent per-day recomputation ──────────────────────────
def _is_bst(d: dt.date) -> bool:
    # last Sunday of March / October
    def last_sun(y, m):
        day = 31
        while True:
            try:
                dte = dt.date(y, m, day)
                if dte.weekday() == 6:
                    return dte
                day -= 1
            except ValueError:
                day -= 1
    return last_sun(d.year, 3) <= d < last_sun(d.year, 10)


def _recompute(date: dt.date):
    """Return (open_price_str, close_price_str, movement_whole_pips_str,
    qualifies_YES_NO_EXCLUDED, direction) by scanning raw CSV."""
    folder = CANDLES_EXT if date.year <= 2025 else CANDLES_26
    is_bst = _is_bst(date)
    exp_open = "06:00" if is_bst else "07:00"
    exp_close = "15:55" if is_bst else "16:55"
    path = folder / f"{date.isoformat()}.csv"
    if not path.exists():
        return (None, None, None, "EXCLUDED", "", "FILE_MISSING")
    open_val = close_val = None
    with path.open() as f:
        for i, line in enumerate(f):
            if i == 0:
                continue  # skip header
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            ts, o, h, l, c = parts[0], parts[1], parts[2], parts[3], parts[4]
            hhmm = ts[11:16]
            if hhmm == exp_open:
                open_val = o
            if hhmm == exp_close:
                close_val = c
    if open_val is None or close_val is None:
        return (open_val, close_val, None, "EXCLUDED", "",
                "NO_0700_UK_CANDLE" if open_val is None else "NO_1655_UK_CANDLE")
    # Independent integer arithmetic. We write a from-scratch 2dp-sub-pip
    # tokeniser without using Decimal (just to be fully different from the
    # main script).
    def to_hundredths(s: str) -> int:
        s = s.strip()
        sign = 1
        if s.startswith("-"):
            sign = -1; s = s[1:]
        if "." in s:
            whole, frac = s.split(".", 1)
        else:
            whole, frac = s, ""
        whole_i = int(whole) if whole else 0
        if len(frac) == 0:
            h = 0
        elif len(frac) == 1:
            h = int(frac) * 10
        else:
            # Deal with float-ulp noise: trailing zeros/99…
            # Take first 2 digits; sanity-check remainder.
            d2 = frac[:2]
            tail = frac[2:]
            h = int(d2)
            if tail:
                # tail should be all zeros, all 9s with a terminating pattern,
                # or small junk. Treat as a rounding error → add +1 to h if
                # tail starts with digit >=5 and current hundredths-digit is
                # 9 or less. To stay simple, use banker-ish rule:
                tail_int = int(tail)
                tail_width = len(tail)
                # If tail represents >= 0.5 of the next hundredth, bump up.
                threshold = 5 * (10 ** (tail_width - 1))
                if tail_int >= threshold:
                    h += 1
        return sign * (whole_i * 100 + h)
    o_h = to_hundredths(open_val)
    c_h = to_hundredths(close_val)
    delta_h = c_h - o_h
    if delta_h >= 8000:
        qualifies = "YES"; direction = "UP"
    elif delta_h <= -8000:
        qualifies = "YES"; direction = "DOWN"
    else:
        qualifies = "NO"; direction = ""
    whole = delta_h // 100 if delta_h >= 0 else -((-delta_h) // 100)
    frac = abs(delta_h) % 100
    disp = f"{'-' if delta_h < 0 else ''}{abs(whole)}.{frac:02d}"
    return (open_val, close_val, disp, qualifies, direction, "")


def _load_daily():
    rows = []
    with DAILY.open() as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rows.append(r)
    return rows


def main():
    log_lines = []
    def log(s=""):
        print(s)
        log_lines.append(s)

    daily = _load_daily()
    by_date = {r["date"]: r for r in daily}

    log("STAGE 1 VERIFICATION")
    log("=" * 72)

    # ─── §1. Spot-check 10 qualifying + 10 non-qualifying, incl. boundary ─
    log("\n§1 — Spot-check qualifying / non-qualifying days")
    log("    (independent re-computation vs daily_results.csv)\n")

    # Pick 5 UP, 5 DOWN, plus 10 near-boundary (|movement| between 60 and 95
    # pips but not qualifying, OR qualifying with just over 80 pips).
    ups = [r for r in daily if r["qualifies"] == "YES" and r["direction"] == "UP"]
    dns = [r for r in daily if r["qualifies"] == "YES" and r["direction"] == "DOWN"]
    nqs = [r for r in daily if r["qualifies"] == "NO"]

    # 5 UP (first 5 chronologically)
    sample_up = ups[:5]
    # 5 DOWN
    sample_dn = dns[:5]
    # 2 near-boundary: closest-to-80 qualifying days (lowest absolute movement >=80)
    near_qual = sorted(
        [r for r in daily if r["qualifies"] == "YES"],
        key=lambda r: abs(int(r["movement_hundredths"])),
    )[:2]
    # 8 non-qualifying — including 2 near-miss, 2 small-move, 4 random
    near_miss = sorted(nqs, key=lambda r: -abs(int(r["movement_hundredths"])))[:2]
    small = sorted(nqs, key=lambda r: abs(int(r["movement_hundredths"])))[:2]
    mid_nq = nqs[100:104] if len(nqs) >= 104 else nqs[:4]

    sample = (sample_up + sample_dn + near_qual + near_miss + small + mid_nq)
    # Dedupe
    seen = set(); unique = []
    for r in sample:
        if r["date"] not in seen:
            unique.append(r); seen.add(r["date"])
    sample = unique[:24]

    mismatches = 0
    for r in sample:
        d = dt.date.fromisoformat(r["date"])
        ov, cv, mv, q, dr, excl = _recompute(d)
        main_q = r["qualifies"]; main_dir = r["direction"]; main_mv = r["movement_pips"]
        main_ov = r["open_price"]; main_cv = r["close_price"]
        ok = (q == main_q and dr == main_dir and mv == main_mv
              and ov == main_ov and cv == main_cv)
        tag = "✓" if ok else "✗ MISMATCH"
        log(f"  {r['date']}  main=[{main_q:<8}  {main_dir:<4}  "
            f"mv={main_mv:>8}  open={main_ov}  close={main_cv}]  "
            f"| recomputed=[{q:<8}  {dr:<4}  mv={mv}]  →  {tag}")
        if not ok:
            mismatches += 1
    if mismatches == 0:
        log(f"\n  ✓ All {len(sample)} spot-checks agree with main analysis.")
    else:
        log(f"\n  ✗ {mismatches} spot-check(s) disagree with main analysis!")

    # ─── §2. UK clock-change weekends ─────────────────────────────────
    log("\n§2 — UK clock-change weekend verification")
    log("    Confirming utc_open_time / utc_close_time for dates "
        "either side of every DST transition.\n")
    changes = []
    for y in (2024, 2025, 2026):
        # last Sunday March = BST start
        day = 31
        while True:
            try:
                dte = dt.date(y, 3, day)
                if dte.weekday() == 6:
                    changes.append(("BST_start", dte)); break
                day -= 1
            except ValueError:
                day -= 1
        day = 31
        while True:
            try:
                dte = dt.date(y, 10, day)
                if dte.weekday() == 6:
                    changes.append(("GMT_start", dte)); break
                day -= 1
            except ValueError:
                day -= 1
    for kind, sunday in changes:
        # Friday before, Monday after
        fri = sunday - dt.timedelta(days=2)
        mon = sunday + dt.timedelta(days=1)
        for date, label in [(fri, "pre"), (mon, "post")]:
            key = date.isoformat()
            if key not in by_date:
                log(f"  {kind}  {date}({label}): NOT IN DAILY  — abort check")
                continue
            r = by_date[key]
            expected_clock = "GMT" if (
                (kind == "BST_start" and label == "pre") or
                (kind == "GMT_start" and label == "post")
            ) else "BST"
            exp_open = "07:00:00" if expected_clock == "GMT" else "06:00:00"
            exp_close = "16:55:00" if expected_clock == "GMT" else "15:55:00"
            ok = (r["uk_clock"] == expected_clock and
                  r["utc_open_time"] == exp_open and
                  r["utc_close_time"] == exp_close)
            tag = "✓" if ok else "✗"
            log(f"  {kind} {sunday} — {date} ({label}): expect "
                f"{expected_clock} {exp_open}-{exp_close}  "
                f"got {r['uk_clock']} {r['utc_open_time']}-{r['utc_close_time']}  {tag}")

    # ─── §3. Mechanically confirm main script never reads high/low ───
    log("\n§3 — Mechanical check: main-script qualifying path reads only ts/open/close")
    src = MAIN_SOURCE.read_text()
    # Locate the qualifying path. It's `def analyse_day(...)` body plus the
    # `_price_to_hundredths` function. We scan both for any mention of
    # `high` or `low` as a column/token read.
    def _find_block(name):
        # Return the body of def `name`() up to the next `def ` at col 0.
        pat = re.compile(rf"^def {name}\(", re.M)
        m = pat.search(src)
        if not m: return ""
        start = m.start()
        # find next top-level def
        m2 = re.search(r"^def ", src[start+1:], re.M)
        end = start + 1 + m2.start() if m2 else len(src)
        return src[start:end]
    block_analyse = _find_block("analyse_day")
    block_price = _find_block("_price_to_hundredths")
    # Look for forbidden tokens.
    forbidden = ["r[2]", "r[3]", "idx_high", "idx_low", 'high"', "low\"",
                 "'high'", "'low'", "high_val", "low_val", "high =", "low ="]
    forbidden_hits = []
    for tok in forbidden:
        if tok in block_analyse or tok in block_price:
            forbidden_hits.append(tok)
    if not forbidden_hits:
        log("  ✓ No high/low read-expression found in analyse_day() or "
            "_price_to_hundredths()")
    else:
        log(f"  ✗ Forbidden tokens found: {forbidden_hits}")
    # The analyse_day block does walk every row and count "bars_in_session_window"
    # for the missing-bars flag — this does not read high/low either.
    assert "idx_high" not in block_analyse

    # ─── §4. Aggregate consistency ────────────────────────────────────
    log("\n§4 — Aggregate consistency check (weekly / monthly / yearly)")
    def read_counts(path):
        out = {}
        with path.open() as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                out[r["period"]] = {k: int(r[k]) for k in r if k != "period"}
        return out

    weekly = read_counts(WEEKLY)
    monthly = read_counts(MONTHLY)
    yearly = read_counts(YEARLY)

    # Recompute aggregates from daily
    def iso_week(d_iso):
        d = dt.date.fromisoformat(d_iso)
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    def iso_month(d_iso): return d_iso[:7]
    def iso_year(d_iso): return d_iso[:4]

    recomputed = {"w": {}, "m": {}, "y": {}}
    for key, lvl in [(iso_week, "w"), (iso_month, "m"), (iso_year, "y")]:
        for r in daily:
            k = key(r["date"])
            d = recomputed[lvl].setdefault(k, {"days_analysed": 0, "up_days": 0,
                                                 "down_days": 0,
                                                 "qualifying_total": 0,
                                                 "excluded": 0})
            if r["qualifies"] == "EXCLUDED":
                d["excluded"] += 1
            else:
                d["days_analysed"] += 1
                if r["qualifies"] == "YES":
                    if r["direction"] == "UP": d["up_days"] += 1
                    if r["direction"] == "DOWN": d["down_days"] += 1
                    d["qualifying_total"] += 1

    def compare_level(name, csv_rows, recomp):
        mism = 0
        for k, v_csv in csv_rows.items():
            v_rec = recomp.get(k)
            if v_rec is None:
                log(f"  {name} {k}: present in CSV, not in daily — ✗"); mism += 1; continue
            for col, exp in v_rec.items():
                got = v_csv.get(col)
                if got != exp:
                    log(f"  {name} {k}.{col}: CSV={got}  daily={exp}  ✗"); mism += 1
        for k in recomp:
            if k not in csv_rows:
                log(f"  {name} {k}: present in daily, missing from CSV ✗"); mism += 1
        if mism == 0:
            log(f"  ✓ {name}: all {len(recomp)} periods match the daily totals")
        return mism

    mw = compare_level("weekly", weekly, recomputed["w"])
    mm = compare_level("monthly", monthly, recomputed["m"])
    my = compare_level("yearly", yearly, recomputed["y"])

    # Also check: counts_by_year grand totals = daily counts
    tot_daily = {"analysed": 0, "up": 0, "down": 0, "qual": 0, "excl": 0}
    for r in daily:
        if r["qualifies"] == "EXCLUDED":
            tot_daily["excl"] += 1
        else:
            tot_daily["analysed"] += 1
            if r["qualifies"] == "YES":
                if r["direction"] == "UP": tot_daily["up"] += 1
                if r["direction"] == "DOWN": tot_daily["down"] += 1
                tot_daily["qual"] += 1
    tot_yearly = {k: 0 for k in ("analysed", "up", "down", "qual", "excl")}
    for y, v in yearly.items():
        tot_yearly["analysed"] += v["days_analysed"]
        tot_yearly["up"] += v["up_days"]
        tot_yearly["down"] += v["down_days"]
        tot_yearly["qual"] += v["qualifying_total"]
        tot_yearly["excl"] += v["excluded"]
    log(f"\n  Grand totals from daily:  {tot_daily}")
    log(f"  Grand totals from yearly: {tot_yearly}")
    if tot_daily == tot_yearly:
        log("  ✓ Grand totals agree.")
    else:
        log("  ✗ Grand totals disagree.")

    # Also qualifying_days.csv must equal daily rows where qualifies==YES
    with QUAL.open() as f:
        qual_count = sum(1 for _ in csv.DictReader(f))
    main_qual = sum(1 for r in daily if r["qualifies"] == "YES")
    if qual_count == main_qual:
        log(f"  ✓ qualifying_days.csv has {qual_count} rows == "
            f"daily qualifying count")
    else:
        log(f"  ✗ qualifying_days.csv has {qual_count} rows, daily has "
            f"{main_qual}")

    log("\n" + "=" * 72)
    all_ok = (mismatches == 0 and not forbidden_hits
              and mw == 0 and mm == 0 and my == 0
              and tot_daily == tot_yearly and qual_count == main_qual)
    log("VERIFICATION PASS" if all_ok else "VERIFICATION FAILED")

    (OUT / "verification.txt").write_text("\n".join(log_lines) + "\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
