"""Descriptive analysis of V3 observational tags.

Dev/validation split by chronology.  Dev = 2026-09-07 → 2026-10-02 (first
4 weeks).  Validation = 2026-10-03 → 2026-10-16 (last 2 weeks).

Reports:
  - Baseline: n, win rate, mean pnl, mean MFE, mean MAE per partition.
  - By trend-exhaustion decile.
  - By price-rejection cohort (dominant_wick + against-entry).
  - By structural-proximity bucket.

Caveats stamped on every table:
  - Sample size very small (dev=~40, val=~20).  No threshold optimisation.
  - Pre-pivot-repair; some live decisions used compromised pivots but
    the tags here are computed from the raw candle archive, independent
    of the live cache.
"""
from __future__ import annotations

import json
import sys
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA = Path(__file__).parent.parent / "data" / "v3_entries_tagged.jsonl"
OUT = Path(__file__).parent.parent / "data" / "v3_tag_analysis.md"

DEV_END = "2026-10-03T00:00:00Z"  # before this timestamp = dev
# Validation: 2026-10-03 → 2026-10-17 (end of pre-fix window)


def load() -> List[Dict[str, Any]]:
    with open(DATA) as f:
        return [json.loads(line) for line in f]


def partition(row: Dict[str, Any]) -> str:
    ts = row.get("timestamp_open", "")
    if ts < DEV_END:
        return "DEV"
    return "VAL"


def resolved(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("pnl_pips") is not None]


def _s(xs: List[float]) -> Dict[str, Optional[float]]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0, "mean": None, "median": None, "sd": None}
    mean = sum(xs) / len(xs)
    median = statistics.median(xs)
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return {"n": len(xs), "mean": round(mean, 2), "median": round(median, 2), "sd": round(sd, 2)}


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    rr = resolved(rows)
    if not rr:
        return {"n": 0, "wins": 0, "losses": 0, "wr": None, "mean_pnl": None,
                "mean_mfe": None, "mean_mae": None, "net_pips": 0}
    wins = sum(1 for r in rr if r["pnl_pips"] > 0)
    losses = sum(1 for r in rr if r["pnl_pips"] <= 0)
    pnl = [r["pnl_pips"] for r in rr]
    mfe = [r.get("mfe_pips") for r in rr if r.get("mfe_pips") is not None]
    mae = [r.get("mae_pips") for r in rr if r.get("mae_pips") is not None]
    return {
        "n": len(rr),
        "wins": wins, "losses": losses,
        "wr": round(wins / len(rr) * 100, 1),
        "mean_pnl": round(sum(pnl) / len(pnl), 2),
        "median_pnl": round(statistics.median(pnl), 2),
        "net_pips": round(sum(pnl), 1),
        "mean_mfe": round(sum(mfe) / max(len(mfe), 1), 2) if mfe else None,
        "mean_mae": round(sum(mae) / max(len(mae), 1), 2) if mae else None,
    }


def _row(label: str, s: Dict[str, Any], width=16) -> str:
    if s["n"] == 0:
        return f"| {label:<{width}} | 0 | – | – | – | – | – |"
    return (f"| {label:<{width}} | {s['n']} | {s['wins']}W/{s['losses']}L | "
            f"{s['wr']:.1f}% | {s['mean_pnl']:+.2f} | "
            f"{s['mean_mfe'] if s['mean_mfe'] is not None else '–':>5} | "
            f"{s['mean_mae'] if s['mean_mae'] is not None else '–':>5} |")


def bucketed(rows: List[Dict[str, Any]], field: str, buckets: List[float]
             ) -> Dict[str, List[Dict[str, Any]]]:
    """Partition `rows` by `field` into buckets defined by edges."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for i in range(len(buckets) + 1):
        if i == 0:
            label = f"<{buckets[0]}"
        elif i == len(buckets):
            label = f"≥{buckets[-1]}"
        else:
            label = f"{buckets[i-1]}–{buckets[i]}"
        out[label] = []
    for r in rows:
        v = r.get(field)
        if v is None:
            continue
        for i, edge in enumerate(buckets):
            if v < edge:
                lbl = f"<{buckets[0]}" if i == 0 else f"{buckets[i-1]}–{buckets[i]}"
                out[lbl].append(r)
                break
        else:
            out[f"≥{buckets[-1]}"].append(r)
    return out


def section_header(lines: List[str], title: str) -> None:
    lines.append("")
    lines.append(f"## {title}")
    lines.append("")


def table_header(lines: List[str], first_col: str) -> None:
    lines.append(f"| {first_col:<16} | n | W/L | WR | mean pnl p | MFE p | MAE p |")
    lines.append("|---|---:|---|---:|---:|---:|---:|")


def write() -> int:
    rows = load()
    print(f"loaded {len(rows)} entries")

    dev = [r for r in rows if partition(r) == "DEV"]
    val = [r for r in rows if partition(r) == "VAL"]
    print(f"DEV: {len(dev)}  VAL: {len(val)}")

    L: List[str] = []
    L.append("# V3 Observational Tags — Historical Evaluation")
    L.append("")
    L.append(f"Generated: {datetime.utcnow().isoformat()}Z")
    L.append("")
    L.append("Window: 2026-09-07 → 2026-10-16 (6 weeks of pre-fix live data).")
    L.append("")
    L.append(f"- DEV partition: 2026-09-07 → 2026-10-02 ({len(resolved(dev))} resolved).")
    L.append(f"- VAL partition: 2026-10-03 → 2026-10-16 ({len(resolved(val))} resolved).")
    L.append("")
    L.append("**All features computed point-in-time from the frozen 5-minute candle "
             "archive.  Pre-pivot-repair live decisions may have used compromised "
             "pivot values; the tags here are derived independently and reflect the "
             "correct FX-day pivots.**")
    L.append("")
    L.append("**No thresholds optimised against this sample.  All splits below are "
             "preregistered or evenly-spaced buckets.**")

    section_header(L, "Baseline")
    table_header(L, "partition")
    L.append(_row("DEV", summarise(dev)))
    L.append(_row("VAL", summarise(val)))
    L.append(_row("ALL", summarise(rows)))

    # ───── TREND EXHAUSTION ─────
    section_header(L, "A. Trend exhaustion — by stretch_atr_at_fire")
    L.append("Buckets: <1, 1-2, 2-3, ≥3 ATRs of stretch.")
    L.append("")
    table_header(L, "stretch_atr")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        bk = bucketed(part, "stretch_atr_at_fire", [1.0, 2.0, 3.0])
        for b, items in bk.items():
            L.append(_row(f"  {b}", summarise(items)))

    section_header(L, "A. Trend exhaustion — by price_vs_daily_open")
    L.append("Buckets: <25, 25-50, 50-75, ≥75 pips above/below daily open.")
    L.append("")
    table_header(L, "px_vs_open")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        # Convert to absolute
        for r in part:
            v = r.get("price_vs_daily_open")
            r["_abs_px_vs_open"] = abs(v) if v is not None else None
        bk = bucketed(part, "_abs_px_vs_open", [25, 50, 75])
        for b, items in bk.items():
            L.append(_row(f"  {b}", summarise(items)))

    section_header(L, "A. Trend exhaustion — by regime_at_fire")
    L.append("")
    table_header(L, "regime")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        regimes: Dict[str, List[Dict[str, Any]]] = {}
        for r in part:
            k = r.get("regime_at_fire") or "UNKNOWN"
            regimes.setdefault(k, []).append(r)
        for reg in sorted(regimes.keys()):
            L.append(_row(f"  {reg[:14]}", summarise(regimes[reg])))

    # ───── PRICE REJECTION ─────
    section_header(L, "B. Price rejection — by prev_bar_dominant_wick")
    L.append("Dominant wick side on the *immediately-prior completed M5 bar*.  "
             "'Against entry' = UPPER wick for a BUY or LOWER wick for a SELL.")
    L.append("")
    table_header(L, "dominant")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        side_groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in part:
            k = r.get("prev_bar_dominant_wick") or "N/A"
            side_groups.setdefault(k, []).append(r)
        for s in ("UPPER", "LOWER", "BALANCED", "N/A"):
            if s in side_groups:
                L.append(_row(f"  {s}", summarise(side_groups[s])))

    section_header(L, "B. Price rejection — against-entry flag")
    L.append("")
    table_header(L, "against_entry")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        groups = {True: [], False: []}
        for r in part:
            v = r.get("prev_bar_rejection_against_entry")
            if v is not None:
                groups[bool(v)].append(r)
        L.append(_row(f"  AGAINST (True)", summarise(groups[True])))
        L.append(_row(f"  not against", summarise(groups[False])))

    section_header(L, "B. Price rejection — by wick/body ratio")
    L.append("Dominant wick / body (body floor 0.1 p).  Buckets: <2, 2-4, 4-10, ≥10.")
    L.append("")
    table_header(L, "wick/body")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        bk = bucketed(part, "prev_bar_wick_body_ratio", [2, 4, 10])
        for b, items in bk.items():
            L.append(_row(f"  {b}", summarise(items)))

    # ───── STRUCTURAL PROXIMITY ─────
    section_header(L, "C. Structural proximity — nearest OPPOSING pivot")
    L.append("Opposing = pivot above entry for BUY, below for SELL.  Buckets in pips.")
    L.append("")
    table_header(L, "dist_opp_pivot")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        bk = bucketed(part, "nearest_opposing_pivot_abs_dist_pips", [5, 15, 30])
        for b, items in bk.items():
            L.append(_row(f"  {b}", summarise(items)))

    section_header(L, "C. Structural proximity — nearest OPPOSING round-50 handle")
    L.append("Includes .00 handles implicitly (every .00 is also a .50 grid line).  "
             "Buckets in pips.")
    L.append("")
    table_header(L, "dist_opp_r50")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        bk = bucketed(part, "abs_dist_to_opposing_round_50_pips", [5, 15, 30])
        for b, items in bk.items():
            L.append(_row(f"  {b}", summarise(items)))

    section_header(L, "C. Structural proximity — distance to PDH or PDL (nearest)")
    L.append("Buckets in pips.")
    L.append("")
    table_header(L, "dist_pdhpdl")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        for r in part:
            h = r.get("abs_dist_to_pdh_pips")
            l_ = r.get("abs_dist_to_pdl_pips")
            if h is not None and l_ is not None:
                r["_min_pdhpdl"] = min(h, l_)
            elif h is not None:
                r["_min_pdhpdl"] = h
            elif l_ is not None:
                r["_min_pdhpdl"] = l_
            else:
                r["_min_pdhpdl"] = None
        bk = bucketed(part, "_min_pdhpdl", [10, 25, 50])
        for b, items in bk.items():
            L.append(_row(f"  {b}", summarise(items)))

    # ───── COMBINED FLAGS ─────
    section_header(L, "D. Combined-flag spotlight (not optimised; preregistered split)")
    L.append("A trade is 'FLAGGED' if ANY of the following is true at decision time:")
    L.append("  - stretch_atr_at_fire ≥ 2.0, OR")
    L.append("  - abs(price_vs_daily_open) ≥ 60 p, OR")
    L.append("  - prev_bar_rejection_against_entry = True AND prev_bar_wick_range_pct ≥ 50, OR")
    L.append("  - nearest_opposing_pivot_abs_dist_pips < 5, OR")
    L.append("  - abs_dist_to_opposing_round_50_pips < 5")
    L.append("")
    L.append("All thresholds are round numbers chosen from the research spec, not fitted.")
    L.append("")
    table_header(L, "cohort")
    for part_name, part in [("DEV", dev), ("VAL", val)]:
        L.append(f"| **{part_name}** |  |  |  |  |  |  |")
        flagged, clean = [], []
        for r in part:
            if r.get("pnl_pips") is None:
                continue
            flags = []
            if (r.get("stretch_atr_at_fire") or 0) >= 2.0:
                flags.append("stretch")
            if abs(r.get("price_vs_daily_open") or 0) >= 60:
                flags.append("daynet")
            if (r.get("prev_bar_rejection_against_entry") is True and
                (r.get("prev_bar_wick_range_pct") or 0) >= 50):
                flags.append("rejection")
            if (r.get("nearest_opposing_pivot_abs_dist_pips") or 999) < 5:
                flags.append("pivot_near")
            if (r.get("abs_dist_to_opposing_round_50_pips") or 999) < 5:
                flags.append("r50_near")
            if flags:
                flagged.append(r)
            else:
                clean.append(r)
        L.append(_row(f"  flagged", summarise(flagged)))
        L.append(_row(f"  clean", summarise(clean)))

    with open(OUT, "w") as f:
        f.write("\n".join(L))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(write())
