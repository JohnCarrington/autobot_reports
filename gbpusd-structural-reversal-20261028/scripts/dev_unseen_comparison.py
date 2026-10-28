"""Side-by-side dev (2024) vs unseen (2025) comparison on the frozen
feasibility grid.  Writes YEAR_BY_YEAR_VALIDATION.csv and prints a
compact summary.
"""
from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"


def _wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _f(x):
    try:
        return float(x) if x != "" else None
    except Exception:
        return None


def _as_int(x):
    try:
        return int(x)
    except Exception:
        return 0


def main():
    feas = list(csv.DictReader((DATA / "ENTRY_FEASIBILITY.csv").open()))
    print(f"Loaded {len(feas)} rows.")

    # Build a per-(family, cf, sl, tp, spread) × year lookup
    by_cell: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for r in feas:
        key = (r["level_family"], r["cf_event"],
               int(r["sl_pts"]), int(r["tp_pts"]), int(r["spread_pts"]))
        by_cell[key][r["year"]] = r

    # Response distribution comparison
    resp = list(csv.DictReader((DATA / "STRUCTURAL_RESPONSE_CLASSIFICATION.csv").open()))
    print("\n### Response share by family × year (TYPE_1 / TYPE_2 / TYPE_3 / TYPE_4 %)")
    print(f"{'family':15} {'year':>4} {'n':>6} {'TYPE_1':>8} {'TYPE_2':>8} {'TYPE_3':>8} {'TYPE_4':>8}")
    for fam in ("PREV_DAY", "PREV_SESSION", "SWING", "DEFENDED", "PIVOT", "ROUND"):
        for yr in ("2024", "2025"):
            sub = [r for r in resp if r["level_family"] == fam and r["year"] == yr]
            n = len(sub)
            if n == 0:
                continue
            c1 = sum(1 for r in sub if r["type_label"] == "TYPE_1_DIRECT_REJECT")
            c2 = sum(1 for r in sub if r["type_label"] == "TYPE_2_SWEEP_RECLAIM")
            c3 = sum(1 for r in sub if r["type_label"] == "TYPE_3_ACCEPTED_BREAKOUT")
            c4 = sum(1 for r in sub if r["repeated_test_flag"].lower() in ("true", "1"))
            print(f"{fam:15} {yr:>4} {n:>6} {100*c1/n:8.1f} {100*c2/n:8.1f} {100*c3/n:8.1f} {100*c4/n:8.1f}")

    # 2024 best cells applied to 2025 — the key validation
    print("\n### Best 2024 cells (n≥100, 1p spread) applied unseen on 2025")
    cells_2024 = [c for c in feas if c["year"] == "2024" and c["spread_pts"] == "1"
                  and int(c["n_fired"]) >= 100 and c["expectancy_pts_amb_as_sl"] not in ("", None)]
    cells_2024.sort(key=lambda r: _f(r["expectancy_pts_amb_as_sl"]) or 0.0, reverse=True)
    header = f"{'family':14} {'cf':24} {'SL':>3} {'TP':>3}"
    header += f" {'n24':>5} {'exp24':>7} {'n25':>5} {'exp25':>7} {'Δ':>7}"
    print(header)
    rows_out = []
    inversions = 0
    for r24 in cells_2024[:25]:
        key = (r24["level_family"], r24["cf_event"],
               int(r24["sl_pts"]), int(r24["tp_pts"]), int(r24["spread_pts"]))
        r25 = by_cell[key].get("2025")
        exp24 = _f(r24["expectancy_pts_amb_as_sl"]) or 0.0
        exp25 = _f(r25["expectancy_pts_amb_as_sl"]) if r25 else None
        delta = (exp25 - exp24) if exp25 is not None else None
        inv = "←INV" if exp25 is not None and exp24 > 0 and exp25 < 0 else "    "
        if exp25 is not None and exp24 > 0 and exp25 < 0:
            inversions += 1
        print(f"{r24['level_family']:14} {r24['cf_event']:24} "
              f"{r24['sl_pts']:>3} {r24['tp_pts']:>3} "
              f"{r24['n_fired']:>5} {exp24:>7.2f} "
              f"{r25['n_fired'] if r25 else '':>5} "
              f"{exp25 if exp25 is not None else '':>7} "
              f"{delta if delta is not None else '':>7} {inv}")
        rows_out.append({
            "family": r24["level_family"], "cf_event": r24["cf_event"],
            "sl_pts": r24["sl_pts"], "tp_pts": r24["tp_pts"], "spread_pts": r24["spread_pts"],
            "n_2024": r24["n_fired"],
            "hit_2024": r24["hit_rate_decisive"],
            "exp_amb_sl_2024": exp24,
            "n_2025": r25["n_fired"] if r25 else "",
            "hit_2025": r25["hit_rate_decisive"] if r25 else "",
            "exp_amb_sl_2025": exp25 if exp25 is not None else "",
            "delta_pp": delta if delta is not None else "",
            "verdict": "INVERTED" if (exp25 is not None and exp24 > 0 and exp25 < 0)
                       else ("DEGRADED" if (exp25 is not None and exp25 < exp24 - 0.3)
                             else ("IMPROVED" if (exp25 is not None and exp25 > exp24 + 0.3)
                                   else "STABLE")),
        })
    print(f"\n### {inversions} of top 25 cells inverted sign dev→unseen")

    # Full dev×unseen for all cells with n_2024 ≥ 50 AND n_2025 ≥ 50
    all_rows = []
    for key, byy in by_cell.items():
        if "2024" not in byy or "2025" not in byy:
            continue
        r24 = byy["2024"]; r25 = byy["2025"]
        n24 = int(r24["n_fired"]); n25 = int(r25["n_fired"])
        if n24 < 50 or n25 < 50:
            continue
        all_rows.append({
            "family": key[0], "cf_event": key[1],
            "sl_pts": key[2], "tp_pts": key[3], "spread_pts": key[4],
            "n_2024": n24, "n_2025": n25,
            "hit_2024": r24["hit_rate_decisive"], "hit_2025": r25["hit_rate_decisive"],
            "exp_amb_sl_2024": r24["expectancy_pts_amb_as_sl"],
            "exp_amb_sl_2025": r25["expectancy_pts_amb_as_sl"],
            "exp_dec_2024": r24["expectancy_pts_decisive"],
            "exp_dec_2025": r25["expectancy_pts_decisive"],
        })

    out = DATA / "YEAR_BY_YEAR_VALIDATION.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"\n✓ YEAR_BY_YEAR_VALIDATION.csv written ({len(all_rows)} cells)")

    # Count cells positive-both-years
    both_positive = 0
    both_rows = []
    for row in all_rows:
        e24 = _f(row["exp_amb_sl_2024"]) or 0.0
        e25 = _f(row["exp_amb_sl_2025"]) or 0.0
        if e24 > 0 and e25 > 0:
            both_positive += 1
            both_rows.append(row)
    print(f"\n### Cells with BOTH years' expectancy > 0 (amb-as-SL, 1p spread): {both_positive}")
    both_rows.sort(key=lambda r: min(_f(r["exp_amb_sl_2024"]), _f(r["exp_amb_sl_2025"])),
                   reverse=True)
    print(f"{'family':14} {'cf':24} {'SL':>3} {'TP':>3} {'sp':>3} "
          f"{'n24':>5} {'n25':>5} {'exp24':>7} {'exp25':>7}")
    for r in both_rows[:20]:
        print(f"{r['family']:14} {r['cf_event']:24} {r['sl_pts']:>3} {r['tp_pts']:>3} "
              f"{r['spread_pts']:>3} {r['n_2024']:>5} {r['n_2025']:>5} "
              f"{_f(r['exp_amb_sl_2024']):>7.2f} {_f(r['exp_amb_sl_2025']):>7.2f}")


if __name__ == "__main__":
    main()
