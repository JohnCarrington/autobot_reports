"""Baseline comparison — "ordinary" GBPUSD 5m extremes NOT in a bounce event.

Picks random 5m bars from the same archive, excludes bars inside any
bounce event's (start_ts, end_ts), uses the bar's high or low as the
"extreme" (randomised), computes level distances the same way, and
reports distribution. Provides the control group for "levels are
dense everywhere" vs "levels concentrate on bounce extremes".
"""
from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import sys, importlib.util
_h = importlib.util.spec_from_file_location("lh", Path(__file__).parent / "level_distance_harness.py")
lh = importlib.util.module_from_spec(_h); _h.loader.exec_module(lh)  # type: ignore

ROOT = Path("/opt/tradingbot")
EVENTS_CSV = ROOT / "reports-public" / "2026-09-27_bb_reversal_census" / "events_GBPUSD.csv"
OUT_DIR = Path(__file__).resolve().parent
SAMPLE_SIZE = 2000
SEED = 20261015


def _parse_ts(s: str):
    return lh._parse_ts(s)


def _event_intervals() -> List[Tuple[datetime, datetime]]:
    out: List[Tuple[datetime, datetime]] = []
    with EVENTS_CSV.open() as fh:
        r = csv.DictReader(fh)
        for row in r:
            s = _parse_ts(row.get("start_ts") or "")
            e = _parse_ts(row.get("end_ts") or "")
            if s and e:
                out.append((s, e))
    return out


def _in_any_event(ts: datetime, intervals: List[Tuple[datetime, datetime]]) -> bool:
    # linear scan — intervals aren't guaranteed sorted, but ~11k is tolerable
    for s, e in intervals:
        if s <= ts <= e:
            return True
    return False


def main() -> None:
    intervals = _event_intervals()
    all_days = sorted({p.name.replace(".csv", "")
                       for d in lh.CANDLES_DIRS for p in d.glob("*.csv")})
    rng = random.Random(SEED)
    rng.shuffle(all_days)
    sample: List[Dict[str, Any]] = []
    for day in all_days:
        bars = lh._load_day(day)
        if not bars:
            continue
        # Pick random bars not in any event; use random high/low
        rng.shuffle(bars)
        for b in bars:
            if _in_any_event(b["ts"], intervals):
                continue
            side = rng.choice(("high", "low"))
            sample.append({"ts": b["ts"], "px": b[side], "side": side})
            if len(sample) >= SAMPLE_SIZE:
                break
        if len(sample) >= SAMPLE_SIZE:
            break

    counts = {k: 0 for k in lh.K_PIPS}
    cluster_ge2 = {k: 0 for k in lh.K_PIPS}
    cluster_ge3 = {k: 0 for k in lh.K_PIPS}
    per_type_cnt: Dict[str, Dict[float, int]] = {
        lt: {k: 0 for k in lh.K_PIPS} for lt in lh.NONTRIVIAL_LEVEL_TYPES
    }
    for s in sample:
        levels = lh.build_levels(s["ts"], s["px"])
        hits_within = {k: 0 for k in lh.K_PIPS}
        for lt in lh.NONTRIVIAL_LEVEL_TYPES:
            lv = levels.get(lt)
            if lv is None:
                continue
            d = abs(s["px"] - lv)
            for k in lh.K_PIPS:
                if d <= k:
                    hits_within[k] += 1
                    per_type_cnt[lt][k] += 1
        for k in lh.K_PIPS:
            if hits_within[k] >= 1:
                counts[k] += 1
            if hits_within[k] >= 2:
                cluster_ge2[k] += 1
            if hits_within[k] >= 3:
                cluster_ge3[k] += 1

    n = len(sample)
    summary = {
        "n_sample": n,
        "proportion_any_level_within_k": {f"{k}p": round(counts[k]/n, 4) for k in lh.K_PIPS},
        "proportion_cluster_ge2_within_k": {f"{k}p": round(cluster_ge2[k]/n, 4) for k in lh.K_PIPS},
        "proportion_cluster_ge3_within_k": {f"{k}p": round(cluster_ge3[k]/n, 4) for k in lh.K_PIPS},
        "proportion_within_k_per_type": {
            lt: {f"{k}p": round(per_type_cnt[lt][k]/n, 4) for k in lh.K_PIPS}
            for lt in lh.NONTRIVIAL_LEVEL_TYPES
        },
    }
    (OUT_DIR / "ordinary_baseline.json").write_text(json.dumps(summary, indent=2))
    print(f"sample n={n}")
    for k in lh.K_PIPS:
        print(f"  within {k}p: any={counts[k]/n*100:.1f}%  >=2={cluster_ge2[k]/n*100:.1f}%  >=3={cluster_ge3[k]/n*100:.1f}%")


if __name__ == "__main__":
    main()
