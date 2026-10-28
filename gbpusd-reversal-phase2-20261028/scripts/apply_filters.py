"""Apply the preregistered filters B1-B6 to FULL_POPULATION_RESULTS.

Writes YEAR_BY_YEAR_VALIDATION.csv and prints a formatted summary.
Also computes 95% Wilson CIs on success rates.
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score CI for success rate k/n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _rate(rows: list[dict], kind: str) -> dict:
    """Compute success/fail/ambiguous/opportunity rate for a (filtered) subset."""
    by = {"SUCCESS": 0, "FAIL": 0, "AMBIGUOUS": 0}
    for r in rows:
        if r["kind"] != kind:
            continue
        lbl = r["outcome_label"]
        if lbl == f"SUCCESS_{kind}":
            by["SUCCESS"] += 1
        elif lbl == f"FAIL_{kind}":
            by["FAIL"] += 1
        else:
            by["AMBIGUOUS"] += 1
    total = sum(by.values())
    decisive = by["SUCCESS"] + by["FAIL"]
    s_rate_all = (by["SUCCESS"] / total) if total else 0.0
    s_rate_decisive = (by["SUCCESS"] / decisive) if decisive else 0.0
    lo_all, hi_all = _wilson_ci(by["SUCCESS"], total)
    lo_dec, hi_dec = _wilson_ci(by["SUCCESS"], decisive)
    return {
        "n_total": total,
        "n_success": by["SUCCESS"],
        "n_fail": by["FAIL"],
        "n_ambig": by["AMBIGUOUS"],
        "success_pct_all": round(100.0 * s_rate_all, 2),
        "success_pct_all_ci95": f"[{lo_all*100:.1f},{hi_all*100:.1f}]",
        "success_pct_decisive": round(100.0 * s_rate_decisive, 2),
        "success_pct_decisive_ci95": f"[{lo_dec*100:.1f},{hi_dec*100:.1f}]",
    }


def _as_float(v) -> float | None:
    try:
        f = float(v)
        if math.isnan(f):
            return None
        return f
    except Exception:
        return None


def _filter_B1_BULL(r: dict) -> bool:
    bbw = _as_float(r.get("bb_width_pts"))
    rsi = _as_float(r.get("rsi"))
    return (r["kind"] == "BULL"
            and r.get("bb_breach_low") in ("True", True)
            and bbw is not None and bbw >= 40.0
            and rsi is not None and rsi <= 23.0)


def _filter_B2_BULL(r: dict) -> bool:
    bbw = _as_float(r.get("bb_width_pts"))
    return (r["kind"] == "BULL"
            and r.get("bb_breach_low") in ("True", True)
            and bbw is not None and bbw >= 40.0)


def _filter_B3_BULL(r: dict) -> bool:
    rsi = _as_float(r.get("rsi"))
    return (r["kind"] == "BULL" and rsi is not None and rsi <= 23.0)


def _filter_B4_BULL(r: dict) -> bool:
    return (r["kind"] == "BULL" and r.get("bb_breach_low") in ("True", True))


def _filter_B5_BEAR(r: dict) -> bool:
    bbw = _as_float(r.get("bb_width_pts"))
    rsi = _as_float(r.get("rsi"))
    return (r["kind"] == "BEAR"
            and r.get("bb_breach_up") in ("True", True)
            and bbw is not None and bbw >= 40.0
            and rsi is not None and rsi >= 77.0)


def _filter_B6_BEAR(r: dict) -> bool:
    bbw = _as_float(r.get("bb_width_pts"))
    rsi = _as_float(r.get("rsi"))
    return (r["kind"] == "BEAR"
            and bbw is not None and bbw >= 40.0
            and rsi is not None and rsi >= 77.0)


FILTERS = [
    ("B1_BULL", _filter_B1_BULL, "BULL"),
    ("B2_BULL", _filter_B2_BULL, "BULL"),
    ("B3_BULL", _filter_B3_BULL, "BULL"),
    ("B4_BULL", _filter_B4_BULL, "BULL"),
    ("B5_BEAR", _filter_B5_BEAR, "BEAR"),
    ("B6_BEAR", _filter_B6_BEAR, "BEAR"),
]


def _trading_weeks(rows: list[dict]) -> float:
    """Approximate number of unique ISO weeks spanned by the rows."""
    import datetime as _dt
    dates = sorted({r["date"] for r in rows})
    if not dates:
        return 0.0
    weeks = set()
    for d in dates:
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        weeks.add(_dt.date(y, m, dd).isocalendar()[:2])
    return float(len(weeks))


def main() -> int:
    in_csv = HERE.parent / "data" / "FULL_POPULATION_RESULTS.csv"
    rows = list(csv.DictReader(in_csv.open()))

    # Baseline per (year, kind)
    print("\n============================================================")
    print("BASELINE (unfiltered) — 2024 vs 2025 × BULL vs BEAR")
    print("============================================================")
    by_year = {y: [r for r in rows if r["year"] == y] for y in ("2024", "2025")}
    for year in ("2024", "2025"):
        weeks = _trading_weeks(by_year[year])
        for kind in ("BULL", "BEAR"):
            stats = _rate(by_year[year], kind)
            opp_per_week = round(stats["n_total"] / weeks, 2) if weeks else 0
            print(f"{year}  {kind}  n={stats['n_total']}  "
                  f"success_decisive={stats['success_pct_decisive']}% "
                  f"CI95 {stats['success_pct_decisive_ci95']}  "
                  f"opps/wk={opp_per_week}")

    # Each preregistered filter × year
    results_csv_rows = []
    print("\n============================================================")
    print("PREREGISTERED FILTERS — B1-B4 (BULL) and B5-B6 (BEAR)")
    print("============================================================")
    for fname, fn, kind in FILTERS:
        print(f"\n--- {fname} ---")
        for year in ("2024", "2025"):
            subset = [r for r in by_year[year] if fn(r)]
            stats = _rate(subset, kind)
            base = _rate(by_year[year], kind)
            # Opportunity frequency
            weeks = _trading_weeks(by_year[year])
            opp_per_week = round(stats["n_total"] / weeks, 2) if weeks else 0
            # Absolute improvement vs baseline (decisive)
            delta_decisive = round(
                stats["success_pct_decisive"] - base["success_pct_decisive"], 2
            )
            print(f"  {year}: n_fired={stats['n_total']}  "
                  f"successes={stats['n_success']}/{stats['n_success']+stats['n_fail']}  "
                  f"rate_decisive={stats['success_pct_decisive']}% "
                  f"{stats['success_pct_decisive_ci95']}  "
                  f"(baseline {base['success_pct_decisive']}%, "
                  f"delta {'+' if delta_decisive >= 0 else ''}{delta_decisive} pp, "
                  f"opps/wk {opp_per_week})")
            results_csv_rows.append({
                "filter": fname,
                "kind": kind,
                "year": year,
                "n_fired": stats["n_total"],
                "n_success": stats["n_success"],
                "n_fail": stats["n_fail"],
                "n_ambiguous": stats["n_ambig"],
                "success_pct_all": stats["success_pct_all"],
                "success_pct_all_ci95": stats["success_pct_all_ci95"],
                "success_pct_decisive": stats["success_pct_decisive"],
                "success_pct_decisive_ci95": stats["success_pct_decisive_ci95"],
                "baseline_success_pct_decisive": base["success_pct_decisive"],
                "delta_vs_baseline_pp": delta_decisive,
                "opps_per_week": opp_per_week,
                "weeks_in_year": weeks,
            })

    # Baseline rows in the CSV too
    for year in ("2024", "2025"):
        weeks = _trading_weeks(by_year[year])
        for kind in ("BULL", "BEAR"):
            stats = _rate(by_year[year], kind)
            results_csv_rows.append({
                "filter": "BASELINE",
                "kind": kind,
                "year": year,
                "n_fired": stats["n_total"],
                "n_success": stats["n_success"],
                "n_fail": stats["n_fail"],
                "n_ambiguous": stats["n_ambig"],
                "success_pct_all": stats["success_pct_all"],
                "success_pct_all_ci95": stats["success_pct_all_ci95"],
                "success_pct_decisive": stats["success_pct_decisive"],
                "success_pct_decisive_ci95": stats["success_pct_decisive_ci95"],
                "baseline_success_pct_decisive": stats["success_pct_decisive"],
                "delta_vs_baseline_pp": 0.0,
                "opps_per_week": round(stats["n_total"] / weeks, 2) if weeks else 0,
                "weeks_in_year": weeks,
            })

    out = HERE.parent / "data" / "YEAR_BY_YEAR_VALIDATION.csv"
    fieldnames = list(results_csv_rows[0].keys())
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for row in results_csv_rows:
            w.writerow(row)
    print(f"\n✓ YEAR_BY_YEAR_VALIDATION.csv written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
