"""Independent reversal-candidate detector.

Pre-registered definition (no look-ahead):

A **bullish reversal CANDIDATE** at the close of bar `b` occurs when:
    1. The dominant movement over the preceding 12 bars (60 min) is DOWN,
       quantified as closes[b] - closes[b-12] <= -20 pips.
    2. The current bar's LOW is within 2 pips of the lowest LOW in the
       preceding 60 bars (5 h) excluding the current bar.
    3. At least 20 pips separate the lowest high of the past 12 bars
       from the current low (= the "run depth").
    4. The current bar closed inside the previous 24-bar range (did not
       set a decisive new low on the close).

A **bearish reversal CANDIDATE** is the mirror.

All thresholds are frozen in this file.  No downstream analysis is
allowed to tune them.

The detector returns the full candidate population; outcome labelling
is performed separately in ``classify_outcomes.py``.
"""
from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, read_bid_m5


# ─────────────────────────────────────────────────────────────────────
# Pre-registered thresholds (frozen 2026-10-28; do not tune downstream)
# ─────────────────────────────────────────────────────────────────────
RUN_WINDOW_BARS = 12            # 60 min of M5
LOOKBACK_WINDOW_BARS = 60       # 5 h of M5
RUN_MOVE_PIPS = 20.0
TEST_TOLERANCE_PIPS = 2.0
MIN_RUN_DEPTH_PIPS = 20.0
CLOSE_INSIDE_WINDOW_BARS = 24   # close must sit inside the past-24-bar range

# Session restriction — detection only during London+NY hours
# (brief says "sustained directional movement" implies active market)
SESSION_START_UTC_HOUR = 6      # ~ London open
SESSION_END_UTC_HOUR = 20       # ~ NY late


@dataclass(frozen=True)
class Candidate:
    date: str
    event_ts_utc: str
    kind: str                  # 'BULL' or 'BEAR'
    bar_open: float
    bar_high: float
    bar_low: float
    bar_close: float
    extreme_pts: float          # the low (BULL) or high (BEAR) touched
    run_move_pips: float        # negative for down-runs that produce BULL candidates
    run_depth_pips: float
    bars_since_prev_test: int   # None-marker = -1 for 'no prior test in lookback'


def _is_in_session(bar: Bar) -> bool:
    return SESSION_START_UTC_HOUR <= bar.ts.hour < SESSION_END_UTC_HOUR


def detect_in_day(bars: list[Bar], date_str: str) -> list[Candidate]:
    """Detect candidates on a single day's bars.  Uses only data up to
    and including the inspected bar — no look-ahead."""
    cands: list[Candidate] = []
    for i, b in enumerate(bars):
        if not _is_in_session(b):
            continue
        if i < max(RUN_WINDOW_BARS, LOOKBACK_WINDOW_BARS):
            continue
        window = bars[i - RUN_WINDOW_BARS:i + 1]      # include current
        lookback = bars[i - LOOKBACK_WINDOW_BARS:i]   # exclude current
        run_move = b.close - window[0].close           # points == pips for FX
        high_in_run = max(x.high for x in window)
        low_in_run = min(x.low for x in window)
        lookback_low = min(x.low for x in lookback)
        lookback_high = max(x.high for x in lookback)
        range_in_window = bars[i - CLOSE_INSIDE_WINDOW_BARS:i]
        inside_low = min(x.low for x in range_in_window)
        inside_high = max(x.high for x in range_in_window)

        # BULL candidate ------------------------------------------------
        if run_move <= -RUN_MOVE_PIPS \
                and b.low <= lookback_low + TEST_TOLERANCE_PIPS \
                and (high_in_run - b.low) >= MIN_RUN_DEPTH_PIPS \
                and b.close > inside_low:
            # Count prior tests of the same low area within lookback
            prior_tests = sum(
                1 for x in lookback
                if x.low <= lookback_low + TEST_TOLERANCE_PIPS
            )
            # bars_since_prev_test = index gap to the most recent prior test
            bars_since = -1
            for off, x in enumerate(reversed(lookback)):
                if x.low <= lookback_low + TEST_TOLERANCE_PIPS:
                    bars_since = off
                    break
            cands.append(Candidate(
                date=date_str, event_ts_utc=b.ts.isoformat(), kind="BULL",
                bar_open=b.open, bar_high=b.high, bar_low=b.low,
                bar_close=b.close, extreme_pts=lookback_low,
                run_move_pips=round(run_move, 2),
                run_depth_pips=round(high_in_run - b.low, 2),
                bars_since_prev_test=bars_since,
            ))
            continue  # one candidate per bar

        # BEAR candidate (mirror) --------------------------------------
        if run_move >= RUN_MOVE_PIPS \
                and b.high >= lookback_high - TEST_TOLERANCE_PIPS \
                and (b.high - low_in_run) >= MIN_RUN_DEPTH_PIPS \
                and b.close < inside_high:
            prior_tests = sum(
                1 for x in lookback
                if x.high >= lookback_high - TEST_TOLERANCE_PIPS
            )
            bars_since = -1
            for off, x in enumerate(reversed(lookback)):
                if x.high >= lookback_high - TEST_TOLERANCE_PIPS:
                    bars_since = off
                    break
            cands.append(Candidate(
                date=date_str, event_ts_utc=b.ts.isoformat(), kind="BEAR",
                bar_open=b.open, bar_high=b.high, bar_low=b.low,
                bar_close=b.close, extreme_pts=lookback_high,
                run_move_pips=round(run_move, 2),
                run_depth_pips=round(b.high - low_in_run, 2),
                bars_since_prev_test=bars_since,
            ))

    return cands


def main() -> int:
    # Scan the full BID archive (2024-2025).
    archive = Path("/opt/tradingbot/data/candles_ext/GBPUSD")
    files = sorted(archive.glob("*.csv"))
    all_cands: list[Candidate] = []
    for p in files:
        try:
            date = datetime.strptime(p.stem, "%Y-%m-%d")
            bars = read_bid_m5(date.replace(tzinfo=timezone.utc))
        except Exception:
            continue
        cands = detect_in_day(bars, p.stem)
        all_cands.extend(cands)

    out_csv = HERE.parent / "data" / "reversal_candidates.csv"
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(Candidate.__dataclass_fields__.keys()))
        w.writeheader()
        for c in all_cands:
            w.writerow(asdict(c))

    print(f"Scanned {len(files)} days (2024-2025 BID archive).")
    print(f"Candidates found: {len(all_cands)}")
    from collections import Counter
    kinds = Counter(c.kind for c in all_cands)
    print(f"  BULL: {kinds['BULL']}")
    print(f"  BEAR: {kinds['BEAR']}")
    print(f"Written to: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
