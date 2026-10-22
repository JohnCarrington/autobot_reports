"""Generate reports A-F from /tmp/bb_band2outer.json.

Prints plain-text tables to stdout for inclusion in the final report.
"""
from __future__ import annotations
import json
from collections import Counter
from statistics import median
from typing import List, Dict, Any

DATA = json.load(open("/tmp/bb_band2outer.json"))

BUCKETS = [
    ("≤1p",   lambda d: d <= 1),
    ("1–3p",  lambda d: 1 < d <= 3),
    ("3–5p",  lambda d: 3 < d <= 5),
    ("5–8p",  lambda d: 5 < d <= 8),
    ("8–15p", lambda d: 8 < d <= 15),
    (">15p",  lambda d: d > 15),
]


def _cell(sub: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(sub)
    if n == 0:
        return {"n": 0}
    wins = sum(1 for r in sub if r["pnl_pips"] > 0)
    pnl_med = median(r["pnl_pips"] for r in sub)
    pnl_sum = sum(r["pnl_pips"] for r in sub)
    mfes = [r["mfe_pips"] for r in sub if r.get("mfe_pips") is not None]
    mfe_med = median(mfes) if mfes else None
    mfe_ge25 = sum(1 for m in mfes if m >= 25)
    return {
        "n": n,
        "win_rate": 100.0 * wins / n,
        "med_pnl": pnl_med,
        "med_mfe": mfe_med,
        "mfe_n": len(mfes),
        "mfe_ge25": mfe_ge25,
        "sum_pips": pnl_sum,
    }


def _table(rows: List[Dict[str, Any]], distance_key: str, title: str) -> str:
    lines = [f"### {title}",
             "| Bucket   |    n | win%  |  med PnL |  med MFE (n) | MFE≥25 |  sum pips |",
             "|----------|-----:|------:|---------:|-------------:|-------:|----------:|"]
    for label, pred in BUCKETS:
        sub = [r for r in rows if pred(r[distance_key])]
        c = _cell(sub)
        if c["n"] == 0:
            lines.append(f"| {label:<8} |    0 |   —   |    —     |     — (0)    |   0    |     0.00  |")
            continue
        mfe_str = f"{c['med_mfe']:5.2f} ({c['mfe_n']})" if c["med_mfe"] is not None else f"  — ({c['mfe_n']})"
        flag = "  ⚠ (thin)" if c["n"] < 10 else ""
        lines.append(f"| {label:<8} | {c['n']:4d} | {c['win_rate']:5.1f} | {c['med_pnl']:+7.2f}  | {mfe_str:>12} | {c['mfe_ge25']:5d}  | {c['sum_pips']:+8.2f} |{flag}")
    return "\n".join(lines)


def _baseline_cell(rows):
    return _cell(rows)


def print_all():
    total = len(DATA)
    n_upper = sum(1 for r in DATA if r["side"] == "upper")
    n_lower = sum(1 for r in DATA if r["side"] == "lower")
    print("# BB_BOUNCE band-vs-outer-pivot — report tables")
    print(f"n_total: {total}   upper (SELL, vs R): {n_upper}   lower (BUY, vs S): {n_lower}")
    from collections import Counter
    dt = Counter(r.get("day_type") for r in DATA)
    print(f"day_type: {dict(dt)}")
    print()

    base = _cell(DATA)
    print(f"BASELINE (all fires, n={base['n']}): win%={base['win_rate']:.1f}  med_pnl={base['med_pnl']:+.2f}  med_mfe={base['med_mfe']:.2f} (n={base['mfe_n']})  mfe≥25={base['mfe_ge25']}  sum_pips={base['sum_pips']:+.2f}")
    print()

    # ── A ──
    print("## A. Headline — band_to_level_pips (all fires, outer only)")
    print(_table(DATA, "band_to_level_pips", "All fires (n=%d)" % total))
    print()

    # ── B ──
    print("## B. Split by side")
    upper = [r for r in DATA if r["side"] == "upper"]
    lower = [r for r in DATA if r["side"] == "lower"]
    print(_table(upper, "band_to_level_pips", "Upper-band pierces / SELL vs R-levels (n=%d)" % len(upper)))
    print()
    print(_table(lower, "band_to_level_pips", "Lower-band pierces / BUY vs S-levels (n=%d)" % len(lower)))
    print()

    # ── C ──
    print("## C. Which level? — tight buckets by identity")
    for side, label, keys in (("upper", "SELL / R-family (band≤5p)", ["R1","R2","R3"]),
                              ("lower", "BUY / S-family (band≤5p)",  ["S1","S2","S3"])):
        subs = [r for r in DATA if r["side"] == side and r["band_to_level_pips"] <= 5]
        print(f"### {label} — n={len(subs)}")
        print("| Level | n  | win%  | med PnL | med MFE (n) | MFE≥25 | sum pips |")
        print("|:-----:|---:|------:|--------:|------------:|-------:|---------:|")
        for k in keys:
            cell_rows = [r for r in subs if r["nearest_outer_by_band"] == k]
            c = _cell(cell_rows)
            if c["n"] == 0:
                print(f"| {k}    |  0 |   —   |    —    |    — (0)    |   0    |    0.00  |")
                continue
            mfe = f"{c['med_mfe']:5.2f} ({c['mfe_n']})" if c["med_mfe"] is not None else f"  — ({c['mfe_n']})"
            flag = "  ⚠ (thin)" if c["n"] < 10 else ""
            print(f"| {k}    | {c['n']:2d} | {c['win_rate']:5.1f} | {c['med_pnl']:+6.2f} | {mfe:>10} | {c['mfe_ge25']:5d}  | {c['sum_pips']:+7.2f} |{flag}")
        print()

    # ── D ──
    print("## D. Base rates — fraction of fires with band within X of an outer level")
    print("| X (pips) | n_within | share of corpus |")
    print("|---------:|---------:|----------------:|")
    for x in (1, 3, 5, 8):
        n_within = sum(1 for r in DATA if r["band_to_level_pips"] <= x)
        print(f"| ≤{x}       |    {n_within:4d}  |     {100*n_within/total:5.1f}%     |")
    print()

    # ── E ──
    print("## E. Alternatives — the best band bucket vs other framings")
    # E(i) — baseline restated for anchoring
    print(f"### E(i) Baseline (all fires, n={base['n']})")
    print(f"win%={base['win_rate']:.1f}  med_pnl={base['med_pnl']:+.2f}  sum={base['sum_pips']:+.2f}")
    print()
    # E(ii) — entry-to-level buckets over the SAME nearest-outer-by-band
    print("### E(ii) Entry-price-to-level buckets (level = nearest outer at band; same denominator)")
    print(_table(DATA, "entry_to_level_pips", "Entry-to-level (all fires)"))
    print()
    # E(iii) — nearest directional level identity (INCLUDES P) as a categorical
    print("### E(iii) Which directional level is nearest to ENTRY (includes P)")
    print("| Level    |   n | win%  | med PnL | med MFE (n) | sum pips |")
    print("|:--------:|----:|------:|--------:|------------:|---------:|")
    for lvl in ("P","R1","R2","R3","S1","S2","S3"):
        cell_rows = [r for r in DATA if r.get("nearest_dir_full_name") == lvl]
        c = _cell(cell_rows)
        if c["n"] == 0:
            print(f"| {lvl:<4}    |  0  |   —   |    —    |    — (0)    |    0.00  |")
            continue
        mfe = f"{c['med_mfe']:5.2f} ({c['mfe_n']})" if c["med_mfe"] is not None else f"  — ({c['mfe_n']})"
        flag = "  ⚠ (thin)" if c["n"] < 10 else ""
        print(f"| {lvl:<4}    | {c['n']:3d} | {c['win_rate']:5.1f} | {c['med_pnl']:+6.2f} | {mfe:>10} | {c['sum_pips']:+7.2f} |{flag}")
    print()

    # ── F ──
    print("## F. MIXED-day cross-check")
    mixed = [r for r in DATA if r.get("day_type") == "MIXED"]
    print(f"n_MIXED = {len(mixed)}  ({100*len(mixed)/total:.1f}% of corpus)")
    base_m = _cell(mixed)
    if base_m["n"]:
        print(f"MIXED baseline: n={base_m['n']}  win%={base_m['win_rate']:.1f}  med_pnl={base_m['med_pnl']:+.2f}  sum={base_m['sum_pips']:+.2f}")
    print(_table(mixed, "band_to_level_pips", "MIXED — band_to_level buckets"))
    print()
    upper_m = [r for r in mixed if r["side"] == "upper"]
    lower_m = [r for r in mixed if r["side"] == "lower"]
    print(_table(upper_m, "band_to_level_pips", "MIXED / upper (n=%d)" % len(upper_m)))
    print()
    print(_table(lower_m, "band_to_level_pips", "MIXED / lower (n=%d)" % len(lower_m)))
    print()


if __name__ == "__main__":
    print_all()
