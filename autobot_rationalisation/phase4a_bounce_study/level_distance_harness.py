"""Phase 4A — bounce-event / level-proximity study.

READ-ONLY research. Operator-authorised scope:

  Using the ORIGINAL historical GBPUSD bounce events in
  /opt/tradingbot/reports-public/2026-09-27_bb_reversal_census/
  events_GBPUSD.csv, measure the distance from every turning point
  (`extreme_px` at `extreme_ts`) to every significant structural
  level AutoBot could have known at that time.

Level universe (reused verbatim from production implementations):

  * PIVOT / R1 / R2 / R3 / S1 / S2 / S3 — floor-pivot formulas as in
    bb_pd_gate.compute_pivots_only (level_snapshot_v6.py:482-528) +
    qm_liquidity_level_mapper._pivots_from_prior (:173-187).
  * PDH / PDL — the SAME prior-D1 anchor (level_snapshot_v6 §3).
  * NEAREST_00 / NEAREST_50 — nearest 100p / 50p-offset grid
    (level_snapshot_v6._build_nearest_entries :700-765 semantics).
  * SWING_H / SWING_L — rolling max/min of last 48 5m bars (4h),
    exactly qm_liquidity_level_mapper._swing_hl default (:199-204).
  * RANGE_H / RANGE_L — intraday H/L up to extreme_ts
    (qm_liquidity_level_mapper build_map :293-296).
  * LN_H / LN_L — London session (07:00–16:00 UTC) H/L up to ts,
    qm_liquidity_level_mapper._session_hl (:206-220).
  * NY_H / NY_L — NY session (13:00–22:00 UTC) H/L up to ts, same.
  * BB_U / BB_L — Bollinger(20, 2.0) on 5m closes up to ts,
    qm_liquidity_level_mapper._bollinger (:189-197). Reported for
    completeness; distance ≈ 0 by construction (bounce events are
    BB touches).

This harness does NOT construct any new level primitive — it
restates the formulas already written in production.

Writes:
  * autobot_rationalisation/phase4a_bounce_study/per_event_levels.jsonl
  * autobot_rationalisation/phase4a_bounce_study/summary.json
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path("/opt/tradingbot")
EVENTS_CSV = ROOT / "reports-public" / "2026-09-27_bb_reversal_census" / "events_GBPUSD.csv"
CANDLES_DIRS = [ROOT / "data" / "candles_ext" / "GBPUSD",
                ROOT / "data" / "candles" / "GBPUSD"]
OUT_DIR = Path(__file__).resolve().parent
PAIR = "GBPUSD"

# Session windows (UTC) per qm_liquidity_level_mapper:
LN_START, LN_END = 7, 16
NY_START, NY_END = 13, 22
SWING_LOOKBACK = 48    # 4h in 5m bars
BB_N = 20              # Bollinger period
BB_K = 2.0             # Bollinger stddev multiplier
# Nearest-00 / nearest-50 grid step. 1 pip = 1.0 at IG scale (×10000).
STEP_00 = 100.0
STEP_50 = 50.0

LEVEL_TYPES = (
    "PIVOT", "R1", "R2", "R3", "S1", "S2", "S3",
    "PDH", "PDL",
    "NEAREST_00", "NEAREST_50",
    "SWING_H", "SWING_L",
    "RANGE_H", "RANGE_L",
    "LN_H", "LN_L", "NY_H", "NY_L",
    "BB_U", "BB_L",
)
# "Non-trivial" level set: exclude BB_U/BB_L because the bounce event
# IS a BB touch (distance ≈ 0 by construction) — including them in the
# proximity analysis would be a self-reference.
NONTRIVIAL_LEVEL_TYPES = tuple(t for t in LEVEL_TYPES if t not in ("BB_U", "BB_L"))

# Within-K thresholds (pips) for the proportion matrix.
K_PIPS = (2.0, 5.0, 10.0, 15.0)


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# ── 5m archive loader ────────────────────────────────────────────────

_BARS_BY_DATE: Dict[str, List[Dict[str, Any]]] = {}


def _load_day(date_iso: str) -> List[Dict[str, Any]]:
    if date_iso in _BARS_BY_DATE:
        return _BARS_BY_DATE[date_iso]
    out: List[Dict[str, Any]] = []
    for d in CANDLES_DIRS:
        fp = d / f"{date_iso}.csv"
        if not fp.exists():
            continue
        with fp.open() as fh:
            r = csv.DictReader(fh)
            for row in r:
                try:
                    ts = _parse_ts(row["timestamp"])
                    if ts is None:
                        continue
                    out.append({
                        "ts": ts,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                    })
                except Exception:
                    continue
        if out:
            break  # prefer earliest matching source
    out.sort(key=lambda b: b["ts"])
    _BARS_BY_DATE[date_iso] = out
    return out


def _bars_up_to(start_day: datetime, end_ts: datetime, lookback_days: int) -> List[Dict[str, Any]]:
    """Return bars from `start_day - lookback_days` up to (<=) end_ts."""
    out: List[Dict[str, Any]] = []
    base = start_day.date()
    for offset in range(lookback_days, -1, -1):
        d = (base - timedelta(days=offset)).isoformat()
        for b in _load_day(d):
            if b["ts"] <= end_ts:
                out.append(b)
    return out


# ── D1 aggregation from 5m ───────────────────────────────────────────

_D1_CACHE: Dict[str, Dict[str, float]] = {}  # UTC date -> OHLC


def _d1_for(date_iso: str) -> Optional[Dict[str, float]]:
    if date_iso in _D1_CACHE:
        return _D1_CACHE[date_iso]
    bars = _load_day(date_iso)
    if not bars:
        _D1_CACHE[date_iso] = None  # type: ignore[assignment]
        return None
    agg = {
        "open":  bars[0]["open"],
        "high":  max(b["high"] for b in bars),
        "low":   min(b["low"] for b in bars),
        "close": bars[-1]["close"],
    }
    _D1_CACHE[date_iso] = agg
    return agg


def _prior_d1(for_date: datetime.date) -> Optional[Dict[str, float]]:
    # Walk back up to 5 days to skip weekends / holidays
    for offset in range(1, 6):
        d = (for_date - timedelta(days=offset)).isoformat()
        d1 = _d1_for(d)
        if d1 is not None:
            return {**d1, "date": d}
    return None


# ── Pivot formulas (identical to _pivots_from_prior) ─────────────────

def _pivots(prior: Dict[str, float]) -> Dict[str, float]:
    h, l, c = prior["high"], prior["low"], prior["close"]
    pp = (h + l + c) / 3.0
    return {
        "PIVOT": pp,
        "R1": 2 * pp - l,
        "R2": pp + (h - l),
        "R3": h + 2 * (pp - l),
        "S1": 2 * pp - h,
        "S2": pp - (h - l),
        "S3": l - 2 * (h - pp),
    }


def _nearest_00(ref: float) -> float:
    return round(ref / STEP_00) * STEP_00


def _nearest_50(ref: float) -> float:
    """Nearest 50-pip multiple that is NOT a 100-pip multiple."""
    # Candidate: nearest 50-grid point
    nearest = round(ref / STEP_50) * STEP_50
    if abs(nearest - round(nearest / STEP_00) * STEP_00) < 1e-9:
        # Picked a 100p point. Shift to adjacent 50p offset.
        up = nearest + STEP_50
        down = nearest - STEP_50
        return up if abs(up - ref) <= abs(down - ref) else down
    return nearest


def _session_hl(bars: List[Dict[str, Any]], start_h: int, end_h: int) -> Tuple[Optional[float], Optional[float]]:
    hi = lo = None
    for b in bars:
        h = b["ts"].hour
        if start_h <= h < end_h:
            if hi is None or b["high"] > hi:
                hi = b["high"]
            if lo is None or b["low"] < lo:
                lo = b["low"]
    return hi, lo


def _bollinger(closes: List[float]) -> Optional[Tuple[float, float, float]]:
    if len(closes) < BB_N:
        return None
    w = closes[-BB_N:]
    mid = sum(w) / BB_N
    var = sum((c - mid) ** 2 for c in w) / BB_N
    sd = math.sqrt(var)
    return mid, mid + BB_K * sd, mid - BB_K * sd


# ── Level map builder for a single event ─────────────────────────────

def build_levels(extreme_ts: datetime, extreme_px: float) -> Dict[str, Optional[float]]:
    today = extreme_ts.date()
    bars_today = [b for b in _load_day(today.isoformat()) if b["ts"] <= extreme_ts]
    # 48-bar lookback for swings; load a few prior days to be safe
    lookback = _bars_up_to(extreme_ts, extreme_ts, lookback_days=1)
    # Make sure we have enough for Bollinger / swing — allow 2 days back
    if len(lookback) < max(BB_N, SWING_LOOKBACK):
        lookback = _bars_up_to(extreme_ts, extreme_ts, lookback_days=3)

    out: Dict[str, Optional[float]] = {}
    # Pivots + PDH/PDL
    prior = _prior_d1(today)
    if prior is not None:
        pivots = _pivots(prior)
        for k, v in pivots.items():
            out[k] = v
        out["PDH"] = prior["high"]
        out["PDL"] = prior["low"]
    else:
        for k in ("PIVOT", "R1", "R2", "R3", "S1", "S2", "S3", "PDH", "PDL"):
            out[k] = None

    out["NEAREST_00"] = _nearest_00(extreme_px)
    out["NEAREST_50"] = _nearest_50(extreme_px)

    # Swing H/L over last SWING_LOOKBACK bars (regardless of day boundary)
    sw_bars = lookback[-SWING_LOOKBACK:] if len(lookback) >= SWING_LOOKBACK else lookback
    if sw_bars:
        out["SWING_H"] = max(b["high"] for b in sw_bars)
        out["SWING_L"] = min(b["low"] for b in sw_bars)
    else:
        out["SWING_H"] = out["SWING_L"] = None

    # RANGE_H/L — today's intraday H/L up to extreme_ts
    if bars_today:
        out["RANGE_H"] = max(b["high"] for b in bars_today)
        out["RANGE_L"] = min(b["low"] for b in bars_today)
    else:
        out["RANGE_H"] = out["RANGE_L"] = None

    # Session H/L
    ln_h, ln_l = _session_hl(bars_today, LN_START, LN_END)
    ny_h, ny_l = _session_hl(bars_today, NY_START, NY_END)
    out["LN_H"], out["LN_L"] = ln_h, ln_l
    out["NY_H"], out["NY_L"] = ny_h, ny_l

    # Bollinger on 5m closes
    closes = [b["close"] for b in lookback]
    bb = _bollinger(closes)
    if bb is not None:
        _, bu, bl = bb
        out["BB_U"], out["BB_L"] = bu, bl
    else:
        out["BB_U"] = out["BB_L"] = None

    return out


# ── Event iteration ──────────────────────────────────────────────────

def _load_events() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with EVENTS_CSV.open() as fh:
        r = csv.DictReader(fh)
        for row in r:
            try:
                row["_extreme_ts"] = _parse_ts(row["extreme_ts"])
                row["_extreme_px"] = float(row["extreme_px"]) if row.get("extreme_px") else None
                row["_touch_ref_px"] = float(row["touch_ref_px"]) if row.get("touch_ref_px") else None
                row["_rev_max_pips"] = float(row["reversal_max_pips"]) if row.get("reversal_max_pips") else 0.0
                row["_adv_max_pips"] = float(row["adverse_max_delta_pips"]) if row.get("adverse_max_delta_pips") else 0.0
            except Exception:
                continue
            if row["_extreme_ts"] is None or row["_extreme_px"] is None:
                continue
            rows.append(row)
    return rows


def _outcome_label(row: Dict[str, Any]) -> str:
    """Three-way label used across the study:
       REVERSED_10: first_10_ts present and NOT ambiguous_10 (clean 10p reversal
                   with no 8p adverse before)
       REVERSED_5: first_5_ts present, not ambiguous_5, but not REVERSED_10
       FAILED:    extreme reached 'reversal_max_pips' < 5 OR
                  ambiguous_5 (adverse 8p+ moved before 5p reversal)
    """
    def _f(k): return float(row.get(k, 0) or 0)
    first_10 = row.get("first_10_ts") or ""
    amb_10 = int(row.get("ambiguous_10", 0) or 0)
    first_5 = row.get("first_5_ts") or ""
    amb_5 = int(row.get("ambiguous_5", 0) or 0)
    if first_10 and not amb_10:
        return "REVERSED_10"
    if first_5 and not amb_5:
        return "REVERSED_5"
    return "FAILED"


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    events = _load_events()
    out_path = OUT_DIR / "per_event_levels.jsonl"
    summary_path = OUT_DIR / "summary.json"

    # proportion-within-K counters, per outcome bucket × level_type × K
    cnt_hits: Dict[Tuple[str, str, float], int] = defaultdict(int)
    cnt_events: Dict[str, int] = defaultdict(int)
    cnt_any: Dict[Tuple[str, float], int] = defaultdict(int)  # any non-trivial level within K
    cnt_cluster: Dict[Tuple[str, float, int], int] = defaultdict(int)  # outcome, K, cluster size >= N

    # Reversal success rate per cluster size (within 5p of extreme — the median window)
    cluster_outcomes_5p: Dict[int, Counter] = defaultdict(Counter)
    cluster_outcomes_2p: Dict[int, Counter] = defaultdict(Counter)

    # per-event JSONL for audit
    with out_path.open("w") as fh:
        for row in events:
            ts = row["_extreme_ts"]
            px = row["_extreme_px"]
            levels = build_levels(ts, px)
            outcome = _outcome_label(row)
            cnt_events[outcome] += 1
            cnt_events["ALL"] += 1

            per_type_dist: Dict[str, Optional[float]] = {}
            min_abs_dist: Dict[float, Optional[float]] = {k: None for k in K_PIPS}
            # count-by-k across non-trivial
            levels_within = {k: 0 for k in K_PIPS}
            # list the levels within 5p for cluster recording
            levels_within_5p: List[str] = []
            levels_within_2p: List[str] = []
            for lt in LEVEL_TYPES:
                lv = levels.get(lt)
                if lv is None:
                    per_type_dist[lt] = None
                    continue
                d = abs(px - lv)
                per_type_dist[lt] = round(d, 2)
                if lt in NONTRIVIAL_LEVEL_TYPES:
                    for k in K_PIPS:
                        if d <= k:
                            levels_within[k] += 1
                            cnt_hits[(outcome, lt, k)] += 1
                            cnt_hits[("ALL", lt, k)] += 1
                    if d <= 5.0:
                        levels_within_5p.append(lt)
                    if d <= 2.0:
                        levels_within_2p.append(lt)
            for k in K_PIPS:
                if levels_within[k] >= 1:
                    cnt_any[(outcome, k)] += 1
                    cnt_any[("ALL", k)] += 1
                # cluster: ≥2 levels within K
                if levels_within[k] >= 2:
                    cnt_cluster[(outcome, k, 2)] += 1
                    cnt_cluster[("ALL", k, 2)] += 1
                if levels_within[k] >= 3:
                    cnt_cluster[(outcome, k, 3)] += 1
                    cnt_cluster[("ALL", k, 3)] += 1

            cluster_outcomes_5p[len(levels_within_5p)][outcome] += 1
            cluster_outcomes_2p[len(levels_within_2p)][outcome] += 1

            fh.write(json.dumps({
                "pair": row.get("pair"),
                "side": row.get("side"),
                "extreme_ts": row.get("extreme_ts"),
                "extreme_px": px,
                "touch_ref_px": row.get("_touch_ref_px"),
                "rev_max_pips": row.get("_rev_max_pips"),
                "adv_max_pips": row.get("_adv_max_pips"),
                "outcome": outcome,
                "per_type_distance_pips": per_type_dist,
                "levels_within_2p": levels_within_2p,
                "levels_within_5p": levels_within_5p,
            }) + "\n")

    summary = {
        "n_events_total": cnt_events["ALL"],
        "n_events_by_outcome": {k: v for k, v in cnt_events.items() if k != "ALL"},
        "proportion_within_k_per_type_overall": {},
        "proportion_within_k_per_type_by_outcome": {},
        "proportion_any_level_within_k": {},
        "proportion_cluster_ge2_within_k": {},
        "proportion_cluster_ge3_within_k": {},
        "cluster_size_vs_outcome_at_5p": {},
        "cluster_size_vs_outcome_at_2p": {},
    }
    for lt in NONTRIVIAL_LEVEL_TYPES:
        summary["proportion_within_k_per_type_overall"][lt] = {
            f"{k}p": round(cnt_hits[("ALL", lt, k)] / max(cnt_events["ALL"], 1), 4)
            for k in K_PIPS
        }
        for outcome in ("REVERSED_10", "REVERSED_5", "FAILED"):
            summary["proportion_within_k_per_type_by_outcome"].setdefault(outcome, {})[lt] = {
                f"{k}p": round(cnt_hits[(outcome, lt, k)] / max(cnt_events[outcome], 1), 4)
                for k in K_PIPS
            }
    for k in K_PIPS:
        summary["proportion_any_level_within_k"][f"{k}p"] = {
            "ALL": round(cnt_any[("ALL", k)] / max(cnt_events["ALL"], 1), 4),
            "REVERSED_10": round(cnt_any[("REVERSED_10", k)] / max(cnt_events["REVERSED_10"], 1), 4),
            "REVERSED_5": round(cnt_any[("REVERSED_5", k)] / max(cnt_events["REVERSED_5"], 1), 4),
            "FAILED": round(cnt_any[("FAILED", k)] / max(cnt_events["FAILED"], 1), 4),
        }
        summary["proportion_cluster_ge2_within_k"][f"{k}p"] = {
            "ALL": round(cnt_cluster[("ALL", k, 2)] / max(cnt_events["ALL"], 1), 4),
            "REVERSED_10": round(cnt_cluster[("REVERSED_10", k, 2)] / max(cnt_events["REVERSED_10"], 1), 4),
            "REVERSED_5": round(cnt_cluster[("REVERSED_5", k, 2)] / max(cnt_events["REVERSED_5"], 1), 4),
            "FAILED": round(cnt_cluster[("FAILED", k, 2)] / max(cnt_events["FAILED"], 1), 4),
        }
        summary["proportion_cluster_ge3_within_k"][f"{k}p"] = {
            "ALL": round(cnt_cluster[("ALL", k, 3)] / max(cnt_events["ALL"], 1), 4),
            "REVERSED_10": round(cnt_cluster[("REVERSED_10", k, 3)] / max(cnt_events["REVERSED_10"], 1), 4),
            "REVERSED_5": round(cnt_cluster[("REVERSED_5", k, 3)] / max(cnt_events["REVERSED_5"], 1), 4),
            "FAILED": round(cnt_cluster[("FAILED", k, 3)] / max(cnt_events["FAILED"], 1), 4),
        }
    for size, oc in sorted(cluster_outcomes_5p.items()):
        total = sum(oc.values())
        summary["cluster_size_vs_outcome_at_5p"][size] = {
            "n": total,
            "REVERSED_10_pct": round(oc.get("REVERSED_10", 0) / max(total, 1) * 100, 1),
            "REVERSED_5_pct": round(oc.get("REVERSED_5", 0) / max(total, 1) * 100, 1),
            "FAILED_pct": round(oc.get("FAILED", 0) / max(total, 1) * 100, 1),
        }
    for size, oc in sorted(cluster_outcomes_2p.items()):
        total = sum(oc.values())
        summary["cluster_size_vs_outcome_at_2p"][size] = {
            "n": total,
            "REVERSED_10_pct": round(oc.get("REVERSED_10", 0) / max(total, 1) * 100, 1),
            "REVERSED_5_pct": round(oc.get("REVERSED_5", 0) / max(total, 1) * 100, 1),
            "FAILED_pct": round(oc.get("FAILED", 0) / max(total, 1) * 100, 1),
        }

    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"events: {cnt_events['ALL']} (REVERSED_10 {cnt_events['REVERSED_10']}, "
          f"REVERSED_5 {cnt_events['REVERSED_5']}, FAILED {cnt_events['FAILED']})")
    print(f"wrote: {out_path.name}, {summary_path.name}")


if __name__ == "__main__":
    main()
