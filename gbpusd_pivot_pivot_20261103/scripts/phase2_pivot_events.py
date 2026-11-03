"""Phase 2 — extract GBP/USD pivot interaction events over the certified window.

Read-only. Walks /opt/tradingbot/data/candles_ext/GBPUSD/ (BID-side M5 CSVs for
2024-01-01 → 2025-12-31) + /opt/tradingbot/data/candles/GBPUSD/ (MID M5 CSVs for
2026-01-01 → 2026-02-28, flagged `mid_basis=True`).

For every M5 bar, check if any of the 7 daily pivots (P, R1-R3, S1-S3) lies in
[lo, hi]. The first time that happens for a given (date, pivot_name, direction)
is an *event*. Record:
    date, bar_ts, pivot_name, pivot_value, basis (bid|mid),
    approach_dir ("UP" | "DOWN"),               -- sign of 10-bar momentum before touch
    distance_from_prior_pivot (pips),           -- (price_at_touch - value_of_last_other_pivot_touched_today)
    minutes_since_prior_pivot_touch,
    pre_touch_mfe_pips, pre_touch_mae_pips,     -- 30-bar lookback before touch
    outcome_15b_pips,  outcome_30b_pips,  outcome_60b_pips,  outcome_120b_pips,
                                                -- signed excursion from pivot in approach direction after N bars
    next_pivot_reached, bars_to_next_pivot,
    rejection_flag, breakout_flag.              -- fixed-threshold labels, see constants

Writes one row per event to csv/pivot_events.csv.

Pre-defined thresholds (declared BEFORE running):
    APPROACH_LOOKBACK_BARS = 10
    PRE_TOUCH_WINDOW_BARS  = 30
    OUTCOME_HORIZONS_BARS  = (15, 30, 60, 120)
    REJECT_PIPS            = 10  # retrace in approach-reverse direction within reject horizon
    BREAKOUT_PIPS          = 10  # continuation past pivot within breakout horizon
    REJECT_HORIZON_BARS    = 15
    BREAKOUT_HORIZON_BARS  = 15

Deduplication: at most one event per (date_UTC, pivot_name, approach_dir).
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import sys
from collections import defaultdict

ROOT_BID = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
ROOT_MID = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")

OUT_CSV  = pathlib.Path(__file__).parent.parent / "csv" / "pivot_events.csv"

APPROACH_LOOKBACK_BARS = 10
PRE_TOUCH_WINDOW_BARS  = 30
OUTCOME_HORIZONS_BARS  = (15, 30, 60, 120)
REJECT_PIPS            = 10.0
BREAKOUT_PIPS          = 10.0
REJECT_HORIZON_BARS    = 15
BREAKOUT_HORIZON_BARS  = 15

PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")

# ---------- pivot calculation ------------------------------------------------

def compute_pivots(H: float, L: float, C: float) -> dict[str, float]:
    P = (H + L + C) / 3.0
    return {
        "P":  P,
        "R1": 2 * P - L,
        "S1": 2 * P - H,
        "R2": P + (H - L),
        "S2": P - (H - L),
        "R3": H + 2 * (P - L),
        "S3": L - 2 * (H - P),
    }

# ---------- data loading -----------------------------------------------------

def load_day(path: pathlib.Path) -> list[dict]:
    """Load a GBPUSD daily M5 CSV. Prices in archive are IG points (×10000)."""
    rows: list[dict] = []
    with path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            ts_raw = row["timestamp"]
            # Normalise: candles_ext is "2024-01-02T00:00:00+00:00", candles is "2026-01-01 17:00:00+00:00"
            ts_iso = ts_raw.replace(" ", "T")
            try:
                ts = dt.datetime.fromisoformat(ts_iso)
            except ValueError:
                continue
            try:
                o = float(row["open"]) / 10000.0
                h = float(row["high"]) / 10000.0
                l = float(row["low"])  / 10000.0
                c = float(row["close"])/ 10000.0
            except (ValueError, KeyError):
                continue
            rows.append({"ts": ts, "o": o, "h": h, "l": l, "c": c})
    return rows

def day_rollup(bars: list[dict]) -> tuple[float, float, float] | None:
    """Daily H / L / C from a day's M5 bars."""
    if not bars:
        return None
    return (
        max(b["h"] for b in bars),
        min(b["l"] for b in bars),
        bars[-1]["c"],
    )

# ---------- event detection --------------------------------------------------

def extract_events(day_date: dt.date, bars: list[dict],
                   pivots: dict[str, float], basis: str) -> list[dict]:
    """Walk `bars` (sorted by ts). For each pivot, find the first bar where
    lo <= pivot <= hi. Compute all required fields."""
    if not bars:
        return []

    # Index bars for post-touch excursion lookups
    N = len(bars)
    events: list[dict] = []
    seen_keys: set[tuple] = set()

    def post_touch_outcome(idx: int, pivot_value: float, approach_dir: str, horizon: int) -> float:
        """Return signed excursion from pivot in approach direction at idx+horizon."""
        j = min(idx + horizon, N - 1)
        if approach_dir == "UP":
            # upward approach: positive if price *continues* above pivot_value
            extreme = max(b["h"] for b in bars[idx + 1 : j + 1]) if j > idx else bars[idx]["h"]
            return (extreme - pivot_value) * 10000.0
        else:
            extreme = min(b["l"] for b in bars[idx + 1 : j + 1]) if j > idx else bars[idx]["l"]
            return (pivot_value - extreme) * 10000.0

    def post_touch_reverse(idx: int, pivot_value: float, approach_dir: str, horizon: int) -> float:
        """Return max retrace *against* approach direction within horizon."""
        j = min(idx + horizon, N - 1)
        if approach_dir == "UP":
            extreme = min(b["l"] for b in bars[idx + 1 : j + 1]) if j > idx else bars[idx]["l"]
            return (pivot_value - extreme) * 10000.0
        else:
            extreme = max(b["h"] for b in bars[idx + 1 : j + 1]) if j > idx else bars[idx]["h"]
            return (extreme - pivot_value) * 10000.0

    for pivot_name in PIVOT_NAMES:
        pivot_value = pivots[pivot_name]
        for i, b in enumerate(bars):
            if not (b["l"] <= pivot_value <= b["h"]):
                continue
            # First touch for this pivot today.
            # Approach direction from 10-bar lookback close delta.
            k = max(0, i - APPROACH_LOOKBACK_BARS)
            if i == 0:
                approach_dir = "UP" if b["c"] >= b["o"] else "DOWN"
            else:
                approach_dir = "UP" if b["c"] >= bars[k]["c"] else "DOWN"

            key = (day_date, pivot_name, approach_dir)
            if key in seen_keys:
                break
            seen_keys.add(key)

            # Pre-touch window (lookback)
            win_start = max(0, i - PRE_TOUCH_WINDOW_BARS)
            pre = bars[win_start:i + 1]
            if pre:
                pre_hi = max(x["h"] for x in pre)
                pre_lo = min(x["l"] for x in pre)
                if approach_dir == "UP":
                    pre_mfe = (pre_hi - pre[0]["o"]) * 10000.0
                    pre_mae = (pre[0]["o"] - pre_lo) * 10000.0
                else:
                    pre_mfe = (pre[0]["o"] - pre_lo) * 10000.0
                    pre_mae = (pre_hi - pre[0]["o"]) * 10000.0
            else:
                pre_mfe = pre_mae = 0.0

            # Outcomes at each horizon
            outcomes = {h: post_touch_outcome(i, pivot_value, approach_dir, h)
                        for h in OUTCOME_HORIZONS_BARS}

            # Reject / breakout labels (both are independent flags on fixed thresholds)
            rev_rh = post_touch_reverse(i, pivot_value, approach_dir, REJECT_HORIZON_BARS)
            fwd_bh = post_touch_outcome(i, pivot_value, approach_dir, BREAKOUT_HORIZON_BARS)
            reject_flag   = int(rev_rh >= REJECT_PIPS)
            breakout_flag = int(fwd_bh >= BREAKOUT_PIPS)

            # Next-pivot-reached: find the first other pivot touched after this one
            next_pivot_reached = ""
            bars_to_next_pivot = ""
            for j in range(i + 1, N):
                for other in PIVOT_NAMES:
                    if other == pivot_name:
                        continue
                    pv = pivots[other]
                    if bars[j]["l"] <= pv <= bars[j]["h"]:
                        next_pivot_reached = other
                        bars_to_next_pivot = str(j - i)
                        break
                if next_pivot_reached:
                    break

            events.append({
                "date": day_date.isoformat(),
                "bar_ts": b["ts"].isoformat(),
                "bar_idx": i,
                "pivot_name": pivot_name,
                "pivot_value": f"{pivot_value:.5f}",
                "basis": basis,
                "approach_dir": approach_dir,
                "prior_pivot_name": "",                 # filled in after sorting
                "minutes_since_prior_pivot": "",
                "distance_from_prior_pivot_pips": "",
                "pre_touch_mfe_pips": f"{pre_mfe:+.1f}",
                "pre_touch_mae_pips": f"{pre_mae:+.1f}",
                "outcome_15b_pips": f"{outcomes[15]:+.1f}",
                "outcome_30b_pips": f"{outcomes[30]:+.1f}",
                "outcome_60b_pips": f"{outcomes[60]:+.1f}",
                "outcome_120b_pips": f"{outcomes[120]:+.1f}",
                "next_pivot_reached": next_pivot_reached,
                "bars_to_next_pivot": bars_to_next_pivot,
                "reject_flag": reject_flag,
                "breakout_flag": breakout_flag,
            })
            break  # first touch only per (pivot, direction)

    # Sort events chronologically (bar_idx ascending) and backfill prior-pivot fields
    events.sort(key=lambda e: e["bar_idx"])
    prev_idx: int | None = None
    prev_name: str | None = None
    prev_value: float | None = None
    for e in events:
        if prev_idx is not None:
            e["prior_pivot_name"] = prev_name or ""
            e["minutes_since_prior_pivot"] = str((e["bar_idx"] - prev_idx) * 5)
            e["distance_from_prior_pivot_pips"] = (
                f'{(float(e["pivot_value"]) - float(prev_value)) * 10000.0:+.1f}'
            )
        prev_idx = e["bar_idx"]
        prev_name = e["pivot_name"]
        prev_value = float(e["pivot_value"])

    for e in events:
        del e["bar_idx"]

    return events

# ---------- main driver ------------------------------------------------------

def main() -> None:
    files = sorted(ROOT_BID.glob("*.csv")) + sorted(ROOT_MID.glob("2026-01-*.csv")) + sorted(ROOT_MID.glob("2026-02-*.csv"))
    print(f"Files to process: {len(files)}")

    all_events: list[dict] = []
    skipped: list[str] = []

    # Previous-day rollup cache (needs the DAY BEFORE each file)
    prior_rollups: dict[dt.date, tuple[float, float, float]] = {}

    # First pass: build daily rollups so we can look up d-1 for each d
    daily_cache: dict[dt.date, list[dict]] = {}
    for f in files:
        try:
            d = dt.date.fromisoformat(f.stem)
        except ValueError:
            continue
        bars = load_day(f)
        if bars:
            daily_cache[d] = bars
            rl = day_rollup(bars)
            if rl is not None:
                prior_rollups[d] = rl
    print(f"Days with usable bars: {len(daily_cache)}")

    # Second pass: event detection
    sorted_dates = sorted(daily_cache.keys())
    for d in sorted_dates:
        bars = daily_cache[d]
        # Find prior trading day (walk back up to 7 days to accommodate weekends/holidays)
        prior = None
        prior_date = None
        for back in range(1, 8):
            cand = d - dt.timedelta(days=back)
            if cand in prior_rollups:
                prior = prior_rollups[cand]
                prior_date = cand
                break
        if prior is None:
            skipped.append(f"{d.isoformat()} (no prior rollup)")
            continue
        H, L, C = prior
        pivots = compute_pivots(H, L, C)
        basis = "bid" if d.year < 2026 else "mid"
        events = extract_events(d, bars, pivots, basis)
        all_events.extend(events)

    print(f"Days skipped: {len(skipped)}  Events found: {len(all_events)}")
    if skipped[:5]:
        print(f"  first 5 skipped: {skipped[:5]}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    if all_events:
        fields = list(all_events[0].keys())
        with OUT_CSV.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(all_events)
        print(f"Wrote {len(all_events)} events to {OUT_CSV}")
    else:
        print("No events to write")

if __name__ == "__main__":
    main()
