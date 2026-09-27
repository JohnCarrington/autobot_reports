#!/usr/bin/env python3
"""BB(20,2) 5-minute upper/lower band reversal census across the full
corpus (2024-01-01 → 2026-09-27, GBPUSD + EURUSD, mid-price).

Corpus locations (mid OHLC, values in file-units = real price × 10 000):
  1. /opt/tradingbot/data/candles_ext/{PAIR}/            2024-01-01 → 2025-12-31
  2. /opt/tradingbot/data/candles/{PAIR}/                2026-01-01 → 2026-09-27
  3. ./data/fill/EURUSD/                                 2026-01-01 → 2026-03-29 (tick-derived)

A "visit" starts on the first 5-min bar where the causal BB(20,2)
condition is met (`mid_high >= upper` for upper; `mid_low <= lower` for
lower) AND no other visit of the same side is already active. It ends
under the chosen boundary rule (default: `mid_close < middle` for an
upper visit, `mid_close > middle` for a lower visit); the sweep runs
four boundary rules for sensitivity.

Within an upper visit we track the running peak of `mid_high` (the
"extreme"), and after the peak, the running minimum of `mid_low`. The
"reversal" is `peak - min_after_peak`. Whenever a new higher high
appears, the reversal counter for that visit resets to zero on the
next bar. First-5/8/10-pip reversal timestamps are the first bar
whose running reversal reaches that threshold. Lower visits invert.

Adverse-before-N flags: BEFORE the visit first reached a K-pip
reversal, did the running peak (upper) exceed the *initial touch
price* by 8/12/15 pips? (For a lower visit, did the running trough
fall below the initial touch by that much?) True = the adverse move
happened first.

Ambiguous flag: the reversal threshold and the adverse threshold both
crossed within the *same 5-min bar*. Since the 5-min OHLC hides
first-touch order, these visits are marked ambiguous and reported
separately; per-tick disambiguation for the 2024-2026 window would
draw on `/mnt/volume_lon1_1778405456698/ticks/` but is not run here
(cost/latency).

Read-only: no orders, no live config, no writes outside this dir.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import math
from collections import defaultdict, OrderedDict
from pathlib import Path
from statistics import median
from typing import Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DATA_ROOT = Path("/opt/tradingbot/data")
CANDLES_EXT = DATA_ROOT / "candles_ext"
CANDLES = DATA_ROOT / "candles"
FILL_ROOT = HERE / "data" / "fill"

PAIRS = ["GBPUSD", "EURUSD"]

BB_PERIOD = 20
BB_STDDEV = 2.0

# Reversal thresholds (pips == 1 file-unit at 4-dp scaling)
REVERSAL_THRESHOLDS = [5, 8, 10]
ADVERSE_THRESHOLDS = [8, 12, 15]

# Boundary rules — sensitivity sweep
BOUNDARY_RULES = [
    ("middle_cross",  {"kind": "middle_cross"}),                 # close crosses back through middle band
    ("band_reentry",  {"kind": "band_reentry"}),                 # close crosses back inside the band (band edge)
    ("bars_since_6",  {"kind": "bars_since_last_touch", "N": 6}),
    ("bars_since_12", {"kind": "bars_since_last_touch", "N": 12}),
]

# --------------------------------------------------------------------------
# Corpus loading
# --------------------------------------------------------------------------

def _read_5m_csv(path: Path) -> List[dict]:
    rows: List[dict] = []
    with open(path) as fh:
        r = csv.DictReader(fh)
        for row in r:
            ts = row.get("timestamp") or row.get("ts") or row.get("time")
            if not ts:
                continue
            try:
                t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                try:
                    t = dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
                except ValueError:
                    continue
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
            try:
                o = float(row["open"]); h = float(row["high"])
                l = float(row["low"]);  c = float(row["close"])
            except (KeyError, ValueError):
                continue
            rows.append({"ts": t, "o": o, "h": h, "l": l, "c": c})
    return rows


def load_pair(pair: str) -> Tuple[List[dict], Dict[str, str]]:
    """Merge every 5m file for a pair. Later fetch overwrites earlier by ts."""
    bars_by_ts: "OrderedDict[dt.datetime, dict]" = OrderedDict()
    sources: Dict[str, str] = {}
    order = [
        ("candles_ext", CANDLES_EXT / pair),
        ("candles",     CANDLES / pair),
        ("fill",        FILL_ROOT / pair),
    ]
    for label, root in order:
        if not root.exists():
            continue
        for f in sorted(root.glob("2024-*.csv")) + \
                 sorted(root.glob("2025-*.csv")) + \
                 sorted(root.glob("2026-*.csv")):
            rows = _read_5m_csv(f)
            for b in rows:
                bars_by_ts[b["ts"]] = b
                sources.setdefault(b["ts"].date().isoformat(), label)
    sorted_bars = [bars_by_ts[k] for k in sorted(bars_by_ts.keys())]
    return sorted_bars, sources


# --------------------------------------------------------------------------
# Bollinger Bands (causal)
# --------------------------------------------------------------------------

def bollinger(closes: List[float],
              period: int = BB_PERIOD,
              k: float = BB_STDDEV) -> List[Optional[Tuple[float, float, float]]]:
    out: List[Optional[Tuple[float, float, float]]] = []
    n = len(closes)
    for i in range(n):
        if i + 1 < period:
            out.append(None)
            continue
        window = closes[i + 1 - period : i + 1]
        mu = sum(window) / period
        var = sum((v - mu) ** 2 for v in window) / period  # population stdev, TA-Lib default
        sd = math.sqrt(var)
        out.append((mu, mu + k * sd, mu - k * sd))
    return out


# --------------------------------------------------------------------------
# Visit detection
# --------------------------------------------------------------------------

def _visit_boundary_hit(rule: dict, side: str,
                        bar: dict, bb: Tuple[float, float, float],
                        bars_since_touch: int) -> bool:
    """Return True if THIS bar terminates the active visit."""
    mid_c = bar["c"]
    mid_hi = bar["h"]
    mid_lo = bar["l"]
    middle, upper, lower = bb
    kind = rule["kind"]
    if kind == "middle_cross":
        if side == "upper":
            return mid_c < middle
        return mid_c > middle
    if kind == "band_reentry":
        if side == "upper":
            return mid_c < upper
        return mid_c > lower
    if kind == "bars_since_last_touch":
        return bars_since_touch >= rule["N"]
    raise ValueError(f"unknown boundary rule kind {kind}")


def detect_and_score_visits(bars: List[dict], bbs, rule: dict) -> List[dict]:
    """Walk the bar stream. For each visit, gather statistics."""
    visits: List[dict] = []
    upper_active: Optional[dict] = None
    lower_active: Optional[dict] = None
    for i, bar in enumerate(bars):
        bb = bbs[i]
        if bb is None:
            continue
        middle, upper, lower = bb
        # Upper visit lifecycle
        upper_touch = bar["h"] >= upper
        lower_touch = bar["l"] <= lower
        # Update running running stats on active visits (from bar entry onward)
        if upper_active is not None:
            _update_upper(upper_active, i, bar)
            upper_active["bars_since_touch"] = 0 if upper_touch else upper_active["bars_since_touch"] + 1
            if _visit_boundary_hit(rule, "upper", bar, bb, upper_active["bars_since_touch"]):
                _finalise_visit(upper_active, i, bar, bb, "upper")
                visits.append(upper_active)
                upper_active = None
        if lower_active is not None:
            _update_lower(lower_active, i, bar)
            lower_active["bars_since_touch"] = 0 if lower_touch else lower_active["bars_since_touch"] + 1
            if _visit_boundary_hit(rule, "lower", bar, bb, lower_active["bars_since_touch"]):
                _finalise_visit(lower_active, i, bar, bb, "lower")
                visits.append(lower_active)
                lower_active = None
        # Visit-start (only after any active-visit updates above)
        if upper_active is None and upper_touch:
            upper_active = _new_visit("upper", i, bar, bb)
        if lower_active is None and lower_touch:
            lower_active = _new_visit("lower", i, bar, bb)
    # Any visits still open at end of corpus → finalise as-is, mark unresolved
    if upper_active is not None:
        upper_active["ended_at_eos"] = True
        _finalise_visit(upper_active, len(bars) - 1, bars[-1], bbs[-1], "upper")
        visits.append(upper_active)
    if lower_active is not None:
        lower_active["ended_at_eos"] = True
        _finalise_visit(lower_active, len(bars) - 1, bars[-1], bbs[-1], "lower")
        visits.append(lower_active)
    return visits


def _new_visit(side: str, i: int, bar: dict, bb) -> dict:
    return {
        "side": side,
        "start_i": i,
        "start_ts": bar["ts"],
        "touch_upper": bb[1],
        "touch_middle": bb[0],
        "touch_lower": bb[2],
        # initial-touch reference price (for adverse-move flag)
        "touch_ref": bar["h"] if side == "upper" else bar["l"],
        "extreme_i": i,
        "extreme_ts": bar["ts"],
        "extreme_price": bar["h"] if side == "upper" else bar["l"],
        # running counter-extreme after the running peak/trough
        "counter_ext_price": bar["h"] if side == "upper" else bar["l"],
        "counter_ext_ts": bar["ts"],
        # bar counts
        "bars_since_touch": 0,
        # per-threshold "first-hit" and "adverse-before" tracking
        "first_hit_ts": {k: None for k in REVERSAL_THRESHOLDS},
        "first_hit_bars": {k: None for k in REVERSAL_THRESHOLDS},
        "adverse_before":  {k: {a: False for a in ADVERSE_THRESHOLDS}
                            for k in REVERSAL_THRESHOLDS},
        # ambiguity: same-bar first-reversal-hit AND adverse crossing
        "ambiguous_first_touch": {k: False for k in REVERSAL_THRESHOLDS},
        # peak / trough
        "adverse_max_delta": 0.0,
        "reversal_max": 0.0,
        # peak-updates counter (used to know when to reset counter-extreme)
        "peak_update_count": 1,
        "ended_at_eos": False,
    }


def _update_upper(v: dict, i: int, bar: dict) -> None:
    """Update peak + reversal tracking on an active upper visit."""
    # Did we make a new peak? If so, reset counter-extreme.
    if bar["h"] > v["extreme_price"]:
        v["extreme_price"] = bar["h"]
        v["extreme_i"] = i
        v["extreme_ts"] = bar["ts"]
        v["peak_update_count"] += 1
        # Reset counter-extreme: start from THIS bar's low
        v["counter_ext_price"] = bar["l"]
        v["counter_ext_ts"] = bar["ts"]
        v["reversal_max"] = max(v["reversal_max"], v["extreme_price"] - v["counter_ext_price"])
        # Adverse update: touch relative to visit-open touch_ref
        adv = v["extreme_price"] - v["touch_ref"]
        if adv > v["adverse_max_delta"]:
            v["adverse_max_delta"] = adv
    else:
        # No new peak: extend trough
        if bar["l"] < v["counter_ext_price"]:
            v["counter_ext_price"] = bar["l"]
            v["counter_ext_ts"] = bar["ts"]
    # Current reversal after any updates
    cur_rev = v["extreme_price"] - v["counter_ext_price"]
    if cur_rev > v["reversal_max"]:
        v["reversal_max"] = cur_rev
    # For each threshold, decide first hit / ambiguous flag / adverse-before
    # Determine what this SAME BAR did to the adverse counter (was there a
    # new-peak-set that pushed adverse forward before or simultaneously
    # with the reversal-threshold hit?)
    same_bar_new_peak = (v["extreme_i"] == i)
    for kk in REVERSAL_THRESHOLDS:
        if v["first_hit_ts"][kk] is None and cur_rev >= kk:
            v["first_hit_ts"][kk] = bar["ts"]
            v["first_hit_bars"][kk] = i - v["start_i"]
            # Adverse-before flags: peak growth over touch_ref BEFORE this bar
            for a in ADVERSE_THRESHOLDS:
                if v["adverse_max_delta"] >= a:
                    v["adverse_before"][kk][a] = True
            if same_bar_new_peak:
                # Both a new peak (adverse extension) and the reversal
                # threshold triggered inside the same 5-min bar — first
                # touch order is not resolvable from 5m OHLC alone.
                v["ambiguous_first_touch"][kk] = True


def _update_lower(v: dict, i: int, bar: dict) -> None:
    """Mirror of _update_upper for a lower visit."""
    if bar["l"] < v["extreme_price"]:
        v["extreme_price"] = bar["l"]
        v["extreme_i"] = i
        v["extreme_ts"] = bar["ts"]
        v["peak_update_count"] += 1
        v["counter_ext_price"] = bar["h"]
        v["counter_ext_ts"] = bar["ts"]
        v["reversal_max"] = max(v["reversal_max"], v["counter_ext_price"] - v["extreme_price"])
        adv = v["touch_ref"] - v["extreme_price"]
        if adv > v["adverse_max_delta"]:
            v["adverse_max_delta"] = adv
    else:
        if bar["h"] > v["counter_ext_price"]:
            v["counter_ext_price"] = bar["h"]
            v["counter_ext_ts"] = bar["ts"]
    cur_rev = v["counter_ext_price"] - v["extreme_price"]
    if cur_rev > v["reversal_max"]:
        v["reversal_max"] = cur_rev
    same_bar_new_trough = (v["extreme_i"] == i)
    for kk in REVERSAL_THRESHOLDS:
        if v["first_hit_ts"][kk] is None and cur_rev >= kk:
            v["first_hit_ts"][kk] = bar["ts"]
            v["first_hit_bars"][kk] = i - v["start_i"]
            for a in ADVERSE_THRESHOLDS:
                if v["adverse_max_delta"] >= a:
                    v["adverse_before"][kk][a] = True
            if same_bar_new_trough:
                v["ambiguous_first_touch"][kk] = True


def _finalise_visit(v: dict, i: int, bar: dict, bb, side: str) -> None:
    v["end_i"] = i
    v["end_ts"] = bar["ts"]
    v["end_close"] = bar["c"]
    v["end_middle"] = bb[0]
    v["duration_bars"] = i - v["start_i"] + 1


# --------------------------------------------------------------------------
# Event CSV
# --------------------------------------------------------------------------

def _visit_row(pair: str, v: dict) -> dict:
    return {
        "pair": pair,
        "side": v["side"],
        "start_ts": v["start_ts"].isoformat(),
        "end_ts": v["end_ts"].isoformat(),
        "duration_bars": v["duration_bars"],
        "peak_updates": v["peak_update_count"],
        "touch_ref_px": round(v["touch_ref"], 4),
        "extreme_ts": v["extreme_ts"].isoformat(),
        "extreme_px": round(v["extreme_price"], 4),
        "counter_ext_ts": v["counter_ext_ts"].isoformat(),
        "counter_ext_px": round(v["counter_ext_price"], 4),
        "reversal_max_pips": round(v["reversal_max"], 2),
        "adverse_max_delta_pips": round(v["adverse_max_delta"], 2),
        "first_5_ts": v["first_hit_ts"][5].isoformat() if v["first_hit_ts"][5] else "",
        "first_5_bars": v["first_hit_bars"][5] if v["first_hit_bars"][5] is not None else "",
        "first_8_ts": v["first_hit_ts"][8].isoformat() if v["first_hit_ts"][8] else "",
        "first_8_bars": v["first_hit_bars"][8] if v["first_hit_bars"][8] is not None else "",
        "first_10_ts": v["first_hit_ts"][10].isoformat() if v["first_hit_ts"][10] else "",
        "first_10_bars": v["first_hit_bars"][10] if v["first_hit_bars"][10] is not None else "",
        # Adverse-before flags (True/False as 1/0)
        **{f"adv_{a}_before_{k}": int(v["adverse_before"][k][a])
           for k in REVERSAL_THRESHOLDS for a in ADVERSE_THRESHOLDS},
        # Ambiguity (first-touch within same 5m bar as adverse extension)
        **{f"ambiguous_{k}": int(v["ambiguous_first_touch"][k])
           for k in REVERSAL_THRESHOLDS},
        "ended_at_eos": int(v["ended_at_eos"]),
    }


# --------------------------------------------------------------------------
# Aggregations
# --------------------------------------------------------------------------

def summarise(visits: List[dict]) -> dict:
    if not visits:
        return {"visits": 0, "reached_5": 0, "reached_8": 0, "reached_10": 0}
    n = len(visits)
    reached = {k: sum(1 for v in visits if v["reversal_max"] >= k) for k in REVERSAL_THRESHOLDS}
    ambiguous = {k: sum(1 for v in visits if v["ambiguous_first_touch"][k]) for k in REVERSAL_THRESHOLDS}
    adverse_first = {}
    for k in REVERSAL_THRESHOLDS:
        for a in ADVERSE_THRESHOLDS:
            adverse_first[f"adv_{a}_before_{k}"] = sum(1 for v in visits
                                                      if v["adverse_before"][k][a])
    return {
        "visits": n,
        **{f"reached_{k}": reached[k] for k in REVERSAL_THRESHOLDS},
        **{f"pct_{k}": reached[k] / n for k in REVERSAL_THRESHOLDS},
        **{f"ambiguous_{k}": ambiguous[k] for k in REVERSAL_THRESHOLDS},
        **adverse_first,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boundary", default="middle_cross",
                    choices=[r[0] for r in BOUNDARY_RULES],
                    help="Primary visit-end boundary; other rules are still swept.")
    args = ap.parse_args()

    # Load corpus
    all_visits_primary: Dict[str, List[dict]] = {}
    corpus_meta: Dict[str, dict] = {}
    for pair in PAIRS:
        bars, sources = load_pair(pair)
        first = bars[0]["ts"].date().isoformat() if bars else None
        last  = bars[-1]["ts"].date().isoformat() if bars else None
        # Detect missing-day gaps
        days = sorted({b["ts"].date().isoformat() for b in bars})
        # In an FX corpus, the natural cadence includes Sunday-evening bars.
        # Report any weekday (Mon-Fri UTC) gaps.
        expected_missing_weekdays = []
        if bars:
            d0 = bars[0]["ts"].date()
            d1 = bars[-1]["ts"].date()
            day = d0
            days_set = set(days)
            while day <= d1:
                if day.weekday() < 5 and day.isoformat() not in days_set:
                    expected_missing_weekdays.append(day.isoformat())
                day += dt.timedelta(days=1)
        corpus_meta[pair] = {
            "bars": len(bars),
            "days_covered": len(days),
            "first_date": first,
            "last_date": last,
            "missing_weekdays": expected_missing_weekdays,
            "source_counts": _summarise_source(sources),
        }
        # Compute BB once (same closes for all boundary rules)
        closes = [b["c"] for b in bars]
        bbs = bollinger(closes)

        # Run each boundary rule
        pair_by_rule = {}
        for name, rule in BOUNDARY_RULES:
            visits = detect_and_score_visits(bars, bbs, rule)
            pair_by_rule[name] = visits
        # Primary = user-selected
        all_visits_primary[pair] = pair_by_rule[args.boundary]
        # Persist per-visit CSV for the primary rule only (event dump)
        _write_events(pair, all_visits_primary[pair])
        # Sensitivity summary
        _write_sensitivity(pair, pair_by_rule)

    # Corpus manifest
    with open(HERE / "corpus_manifest.json", "w") as fh:
        json.dump(corpus_meta, fh, indent=2, default=str)

    # Overall summary + tables
    combined = _emit_report_tables(all_visits_primary, corpus_meta, args.boundary)
    with open(HERE / "summary.json", "w") as fh:
        json.dump(combined, fh, indent=2, default=str)
    print(json.dumps(combined["headline"], indent=2, default=str))


def _summarise_source(sources: Dict[str, str]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for _, label in sources.items():
        counts[label] += 1
    return dict(counts)


def _write_events(pair: str, visits: List[dict]) -> None:
    rows = [_visit_row(pair, v) for v in visits]
    if not rows:
        (HERE / f"events_{pair}.csv").write_text("")
        return
    fields = list(rows[0].keys())
    with open(HERE / f"events_{pair}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_sensitivity(pair: str, pair_by_rule: Dict[str, List[dict]]) -> None:
    rows = []
    for rule_name, visits in pair_by_rule.items():
        for side in ("upper", "lower"):
            sub = [v for v in visits if v["side"] == side]
            s = summarise(sub)
            rows.append({"pair": pair, "rule": rule_name, "side": side, **s})
    fields = list(rows[0].keys()) if rows else ["pair", "rule", "side", "visits"]
    with open(HERE / f"sensitivity_{pair}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _emit_report_tables(visits_by_pair, corpus_meta, boundary):
    # Headline
    headline = {"boundary_rule": boundary,
                "pairs": {}}
    combined = {"headline": headline,
                "by_year": [],
                "by_month": [],
                "by_pair_side": [],
                "by_hour_utc": []}
    for pair, visits in visits_by_pair.items():
        upper = [v for v in visits if v["side"] == "upper"]
        lower = [v for v in visits if v["side"] == "lower"]
        headline["pairs"][pair] = {
            "total_visits": len(visits),
            "days_covered": corpus_meta[pair]["days_covered"],
            "upper": {"visits": len(upper),
                      **{f"reached_{k}": sum(1 for v in upper if v['reversal_max'] >= k)
                         for k in REVERSAL_THRESHOLDS},
                      **{f"pct_{k}": (sum(1 for v in upper if v['reversal_max'] >= k) / len(upper))
                         if upper else 0.0 for k in REVERSAL_THRESHOLDS}},
            "lower": {"visits": len(lower),
                      **{f"reached_{k}": sum(1 for v in lower if v['reversal_max'] >= k)
                         for k in REVERSAL_THRESHOLDS},
                      **{f"pct_{k}": (sum(1 for v in lower if v['reversal_max'] >= k) / len(lower))
                         if lower else 0.0 for k in REVERSAL_THRESHOLDS}},
        }
        # by-year
        by_y: Dict[str, List[dict]] = defaultdict(list)
        for v in visits:
            by_y[str(v["start_ts"].year)].append(v)
        for y, sub in sorted(by_y.items()):
            for side in ("upper", "lower"):
                sub_side = [v for v in sub if v["side"] == side]
                s = summarise(sub_side)
                combined["by_year"].append({"pair": pair, "year": y, "side": side, **s})
        # by-month
        by_m: Dict[str, List[dict]] = defaultdict(list)
        for v in visits:
            by_m[v["start_ts"].strftime("%Y-%m")].append(v)
        for m, sub in sorted(by_m.items()):
            for side in ("upper", "lower"):
                sub_side = [v for v in sub if v["side"] == side]
                s = summarise(sub_side)
                combined["by_month"].append({"pair": pair, "month": m, "side": side, **s})
        # by-hour UTC
        by_h: Dict[int, List[dict]] = defaultdict(list)
        for v in visits:
            by_h[v["start_ts"].hour].append(v)
        for h in range(24):
            sub = by_h.get(h, [])
            for side in ("upper", "lower"):
                sub_side = [v for v in sub if v["side"] == side]
                s = summarise(sub_side)
                combined["by_hour_utc"].append({"pair": pair, "hour_utc": h, "side": side, **s})
        # pair × side split (dedicated table for the report)
        for side in ("upper", "lower"):
            sub_side = [v for v in visits if v["side"] == side]
            s = summarise(sub_side)
            combined["by_pair_side"].append({"pair": pair, "side": side, **s})

    # Write CSVs
    for name, rows in (
        ("by_year", combined["by_year"]),
        ("by_month", combined["by_month"]),
        ("by_pair_side", combined["by_pair_side"]),
        ("by_hour_utc", combined["by_hour_utc"]),
    ):
        if not rows:
            (HERE / f"table_{name}.csv").write_text("")
            continue
        fields: List[str] = list(rows[0].keys())
        seen = set(fields)
        for r in rows[1:]:
            for k in r.keys():
                if k not in seen:
                    fields.append(k); seen.add(k)
        with open(HERE / f"table_{name}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
    return combined


if __name__ == "__main__":
    main()
