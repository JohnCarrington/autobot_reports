#!/usr/bin/env python3
"""Correlate news-day flags with Pop A (trend day) and Pop B (session trend).

Produces one CSV per population:
    population_a_news_correlation.csv
    population_b_news_correlation.csv

Each row is a condition (news flag or specific HIGH event name) and
records: n_cond, n_cond_pos, p_pos_cond, p_pos_base, lift, 95% CI,
split by {all, 2024, 2025, 2026}. CI via normal approximation.
"""
from __future__ import annotations

import csv
import math
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
IN = HERE / "outputs" / "day_classification.csv"
OUT_A = HERE / "outputs" / "population_a_news_correlation.csv"
OUT_B = HERE / "outputs" / "population_b_news_correlation.csv"

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    halfw = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - halfw), min(1.0, centre + halfw))

def rows_for_year(rows, y):
    if y == "all":
        return rows
    return [r for r in rows if r["year"] == y]

def compute(rows, cond_fn, outcome_key):
    cond = [r for r in rows if cond_fn(r)]
    other = [r for r in rows if not cond_fn(r)]
    n_cond = len(cond)
    n_other = len(other)
    k_cond = sum(1 for r in cond if r[outcome_key] == "1")
    k_other = sum(1 for r in other if r[outcome_key] == "1")
    n_total = n_cond + n_other
    k_total = k_cond + k_other
    p_cond = k_cond / n_cond if n_cond else float("nan")
    p_base = k_total / n_total if n_total else float("nan")
    p_other = k_other / n_other if n_other else float("nan")
    lift = p_cond / p_base if p_base else float("nan")
    ci_lo, ci_hi = wilson_ci(k_cond, n_cond)
    return {
        "n_cond": n_cond, "k_cond": k_cond,
        "p_cond": p_cond, "p_base": p_base, "p_other": p_other,
        "lift": lift,
        "p_cond_ci_lo": ci_lo, "p_cond_ci_hi": ci_hi,
    }

def main():
    rows = list(csv.DictReader(IN.open()))
    # Pop A outcome: trend day
    # Pop B outcome: 80p session move
    for pop, outcome_key, out_path in [
        ("A", "pop_a_trend_day", OUT_A),
        ("B", "pop_b_qualifies", OUT_B),
    ]:
        # restrict to analysed days for Pop A (pop_a_in_set == 1 ensures census coverage)
        if pop == "A":
            scope = [r for r in rows if r["pop_a_in_set"] == "1"]
        else:
            scope = rows
        conditions = [
            ("major_news_day",   lambda r: r["flag_major_news"] == "1"),
            ("pre_news_1d",      lambda r: r["flag_pre_news_1d"] == "1"),
            ("pre_news_2d",      lambda r: r["flag_pre_news_2d"] == "1"),
            ("post_news_day",    lambda r: r["flag_post_news"] == "1"),
            ("no_major_news",    lambda r: r["flag_no_major_news"] == "1"),
            ("major_news_USD",   lambda r: int(r["n_high_usd"]) > 0),
            ("major_news_GBP",   lambda r: int(r["n_high_gbp"]) > 0),
            ("major_news_both",  lambda r: int(r["n_high_usd"]) > 0 and int(r["n_high_gbp"]) > 0),
            ("dual_session_news",lambda r: r["dual_session_high"] == "1"),
            # Release-window conditions
            ("release_LONDON_AM", lambda r: "LONDON_AM" in r["release_windows"]),
            ("release_LONDON_PM", lambda r: "LONDON_PM" in r["release_windows"]),
            ("release_NY_AM",     lambda r: "NY_AM" in r["release_windows"]),
            ("release_NY_PM",     lambda r: "NY_PM" in r["release_windows"]),
            # Specific HIGH events (regex over high_event_names)
            ("event_NFP",         lambda r: bool(re.search(r"Non.?Farm|US_NFP|Nonfarm Pay", r["high_event_names"], re.I))),
            ("event_FOMC",        lambda r: bool(re.search(r"FOMC|Fed Interest Rate|US_FOMC|Federal Funds", r["high_event_names"], re.I))),
            ("event_US_CPI",      lambda r: bool(re.search(r"US_CPI|Core CPI|CPI YoY|CPI MoM", r["high_event_names"], re.I)) and int(r["n_high_usd"]) > 0),
            ("event_UK_CPI",      lambda r: bool(re.search(r"UK_CPI|Inflation Rate", r["high_event_names"], re.I)) and int(r["n_high_gbp"]) > 0),
            ("event_BOE",         lambda r: bool(re.search(r"UK_BOE|BoE Interest|MPC|Bank of England", r["high_event_names"], re.I))),
            ("event_UK_GDP",      lambda r: bool(re.search(r"UK_GDP|GDP YoY|GDP MoM|GDP Growth", r["high_event_names"], re.I)) and int(r["n_high_gbp"]) > 0),
            ("event_UK_JOBS",     lambda r: bool(re.search(r"Employment|Claimant|Unemployment Rate|Earnings|UK_JOBS", r["high_event_names"], re.I)) and int(r["n_high_gbp"]) > 0),
        ]

        out = []
        for year in ("all", "2024", "2025", "2026"):
            subset = rows_for_year(scope, year)
            n_year = len(subset)
            k_year = sum(1 for r in subset if r[outcome_key] == "1")
            p_base_year = k_year / n_year if n_year else float("nan")
            for cname, cfn in conditions:
                st = compute(subset, cfn, outcome_key)
                out.append({
                    "year": year,
                    "condition": cname,
                    "n_total": n_year,
                    "n_cond": st["n_cond"],
                    "k_cond": st["k_cond"],
                    "p_cond": f"{st['p_cond']:.4f}" if not math.isnan(st["p_cond"]) else "",
                    "p_base": f"{p_base_year:.4f}",
                    "p_other": f"{st['p_other']:.4f}" if not math.isnan(st["p_other"]) else "",
                    "lift_vs_base": f"{st['lift']:.3f}" if not math.isnan(st["lift"]) else "",
                    "p_cond_ci_lo": f"{st['p_cond_ci_lo']:.4f}" if not math.isnan(st["p_cond_ci_lo"]) else "",
                    "p_cond_ci_hi": f"{st['p_cond_ci_hi']:.4f}" if not math.isnan(st["p_cond_ci_hi"]) else "",
                })
        with out_path.open("w", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
        print(f"wrote {len(out)} rows -> {out_path}")
        # Print the biggest-lift conditions for quick scan
        top = sorted(
            [r for r in out if r["year"] == "all" and r["lift_vs_base"] and r["n_cond"] >= 10],
            key=lambda r: float(r["lift_vs_base"]),
            reverse=True,
        )[:10]
        print(f"=== Pop {pop} top lift (year=all, n_cond>=10) ===")
        for r in top:
            print(f"  {r['condition']:22} n_cond={r['n_cond']:3} k_cond={r['k_cond']:3} "
                  f"p_cond={r['p_cond']} base={r['p_base']} lift={r['lift_vs_base']}")

if __name__ == "__main__":
    main()
