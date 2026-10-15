"""trend_coverage.py — HTF-aligned-bar census.

Measures the UPPER BOUND of Trend V3 / EMA Pullback entry opportunities
across the historical corpus by counting 5m bars where:

  * D1 close direction (prior-D1 close vs prior-prior-D1 close) is UP or DOWN
  * H4 close direction (prior-H4 close vs prior-prior-H4 close) is same as D1
  * H1 close direction is same as D1

This is NOT a Trend V3 fire simulation (which requires the full ADX /
MACD / ATR / ribbon-gate pipeline and session_trend state). It is the
TRIAGE question: "on how many bars COULD a trend strategy have fired?"
Follow-up: run gbpusd_trend_v3.strategy.evaluate against each
aligned-bar window with the enriched df_5m produced by the production
indicator pipeline — a substantially larger harness, scheduled as a
follow-up per the spec.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROD = "/opt/tradingbot"
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)

from autobot_v3_build.opening_map import _load_day_bars

OUT_DIR = Path(__file__).resolve().parent / "replay_out"
OUT_DIR.mkdir(exist_ok=True)


def _d1_series(pair: str, from_date, to_date) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    d = from_date
    while d <= to_date:
        bars = _load_day_bars(pair, d.isoformat())
        if bars:
            out.append({
                "date": d.isoformat(),
                "open": bars[0]["open"],
                "high": max(b["high"] for b in bars),
                "low":  min(b["low"] for b in bars),
                "close": bars[-1]["close"],
            })
        d = d + timedelta(days=1)
    return out


def _direction(delta: float) -> str:
    if delta > 0: return "UP"
    if delta < 0: return "DOWN"
    return "FLAT"


def run_census(pair: str = "GBPUSD",
                 from_date=None, to_date=None) -> Dict[str, Any]:
    from datetime import date as _date
    if from_date is None:
        from_date = _date(2024, 1, 2)
    if to_date is None:
        to_date = _date(2026, 9, 27)

    d1 = _d1_series(pair, from_date, to_date)
    # Build a per-date D1 direction map (prior-close vs prior-prior-close)
    d1_dir_by_date: Dict[str, str] = {}
    for i in range(2, len(d1)):
        day = d1[i]["date"]
        d1_dir_by_date[day] = _direction(d1[i-1]["close"] - d1[i-2]["close"])

    # Iterate 5m bars day-by-day
    counts = Counter()
    aligned_days: Dict[str, int] = defaultdict(int)
    hourly_hist = Counter()
    for i, day in enumerate(d1):
        if i < 2:
            continue
        bars = _load_day_bars(pair, day["date"])
        if not bars:
            continue
        d1_dir = d1_dir_by_date.get(day["date"]) or "FLAT"
        for b in bars:
            counts["total_bars"] += 1
            # Rolling H4 / H1 directions = close vs 48/12 bars ago
            # Approximate using the day's running close series — simplification
            # just for the upper bound.
            # We'll compute H1 direction as (close - close 12 bars ago)
            # and H4 as (close - close 48 bars ago). If insufficient
            # history, treat as FLAT (not aligned).
            # NOTE: this is a simplification. The faithful HTF path reads
            # H1/H4 cached candles; the production entry condition reads
            # htf_regime.classify(symbol). This upper-bound census is
            # bounded above by that signal.
            pass  # we'll handle below

        # Build the rolling H1 (12 bars = 60 min) and H4 (48 bars = 240 min)
        for idx, b in enumerate(bars):
            if idx < 48:
                continue
            h1_dir = _direction(bars[idx]["close"] - bars[idx-12]["close"])
            h4_dir = _direction(bars[idx]["close"] - bars[idx-48]["close"])
            if h1_dir == h4_dir == d1_dir and h1_dir in ("UP", "DOWN"):
                counts["aligned_bars"] += 1
                aligned_days[day["date"]] += 1
                hourly_hist[b["ts"].hour] += 1
            if h1_dir == h4_dir and h1_dir in ("UP", "DOWN") and d1_dir == "FLAT":
                counts["h1h4_aligned_d1_flat"] += 1
            if h1_dir in ("UP","DOWN") or h4_dir in ("UP","DOWN"):
                counts["any_dir_bar"] += 1

    total = max(counts["total_bars"], 1)
    aligned = counts.get("aligned_bars", 0)
    summary = {
        "pair": pair,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "n_days": len(d1),
        "total_bars": counts["total_bars"],
        "aligned_bars": aligned,
        "aligned_fraction": round(aligned / total, 4),
        "h1h4_aligned_d1_flat": counts.get("h1h4_aligned_d1_flat", 0),
        "aligned_days": len(aligned_days),
        "aligned_bars_median_per_day_aligned": sorted(aligned_days.values())[len(aligned_days)//2] if aligned_days else 0,
        "aligned_bars_by_hour": dict(hourly_hist),
    }
    (OUT_DIR / "trend_coverage.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    s = run_census()
    print(json.dumps(s, indent=2))
