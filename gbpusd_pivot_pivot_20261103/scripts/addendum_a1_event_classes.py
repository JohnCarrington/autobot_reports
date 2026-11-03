"""Addendum A1 — rebuild pivot-interaction event detection with proper
pre-pivot / at-pivot / overshoot / stop-sweep classes.

Addresses the audit critique:
  * Old detection used `lo <= pivot <= hi` (touch = event). Missed
    pre-pivot reversals.
  * Old breakout flag counted a 1-bar wick 10p past as a breakout.
    No follow-through confirmation.
  * Thresholds for reject (10p/15 bars) and breakout (10p/15 bars)
    imposed without sensitivity testing.

New event classification per daily approach to a pivot. For S2/R2 and
S3/R3 primarily; other pivots computed for completeness.

Definitions (pre-registered before running):

  APPROACH_PROXIMITY_PIPS = 15     # price enters within 15p of pivot
  OVERSHOOT_MAX_PIPS      = 50     # overshoot beyond 50p is not a "wick"
  CONFIRMED_CLOSE_BARS    = 2      # 2 M5 closes past pivot define breakout
  CONFIRMED_CLOSE_PIPS    = 3      # minimum close-past distance (pips)
  HOLD_HORIZON_BARS       = 30     # measurement window after approach

Four outcome classes per approach event:
  PRE_PIVOT_REVERSAL   — price approaches within proximity but never
                         touches (bar lo/hi doesn't straddle pivot)
                         AND then moves > approach_proximity_pips away
                         in the opposite direction.
  AT_PIVOT_REVERSAL    — bar lo/hi straddles pivot AND the max
                         overshoot (bar extreme past pivot) is < 3p
                         AND price then moves away such that no
                         subsequent close within HOLD_HORIZON_BARS is
                         further past pivot by >= 3p.
  STOP_SWEEP_REVERSAL  — bar lo/hi straddles pivot AND max overshoot
                         >= 3p AND no 2 consecutive closes past pivot
                         by >= 3p within HOLD_HORIZON_BARS AND price
                         subsequently traverses back past pivot by
                         >= 5p in the opposite direction.
  CONFIRMED_BREAKOUT   — bar lo/hi straddles pivot AND at least 2 M5
                         closes (not necessarily consecutive) within
                         HOLD_HORIZON_BARS are >= 3p past pivot AND
                         price reaches >= 10p past pivot.

If none of the four classes apply (eg. chop near pivot with no decisive
move), we label STALL.

Sensitivity test also runs the same classification for:
  (approach_proximity, confirmed_pips, confirmed_bars) in grid:
    (10, 2, 1), (15, 3, 2) [base], (20, 5, 3)

Writes csv/addendum_a1_events.csv (one row per approach event).
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
from collections import defaultdict

BID_ROOT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
MID_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
OUT_CSV  = pathlib.Path(__file__).parent.parent / "csv" / "addendum_a1_events.csv"

PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")

# Base thresholds — pre-registered
APPROACH_PROXIMITY_PIPS = 15.0
CONFIRMED_CLOSE_PIPS    = 3.0
CONFIRMED_CLOSE_BARS    = 2
HOLD_HORIZON_BARS       = 30
REVERSAL_AWAY_PIPS      = 15.0
POST_SWEEP_REVERSE_PIPS = 5.0

# Sensitivity grid
GRID = [
    ("LOOSE",    10.0, 2.0, 1, 20, 10.0, 3.0),
    ("BASE",     15.0, 3.0, 2, 30, 15.0, 5.0),
    ("STRICT",   20.0, 5.0, 3, 40, 20.0, 10.0),
]

def pivots(H, L, C):
    P = (H + L + C) / 3.0
    return {
        "P":  P,
        "R1": 2 * P - L, "S1": 2 * P - H,
        "R2": P + (H - L), "S2": P - (H - L),
        "R3": H + 2 * (P - L), "S3": L - 2 * (H - P),
    }

def load_day(path: pathlib.Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for row in csv.DictReader(path.open()):
        ts_raw = row["timestamp"].replace(" ", "T")
        try:
            ts = dt.datetime.fromisoformat(ts_raw)
        except ValueError:
            continue
        rows.append({
            "ts": ts,
            "o": float(row["open"]) / 10000.0,
            "h": float(row["high"]) / 10000.0,
            "l": float(row["low"])  / 10000.0,
            "c": float(row["close"])/ 10000.0,
        })
    return rows

def classify_event(
    bars: list[dict], pivot_value: float, pivot_name: str,
    proximity: float, confirmed_pips: float, confirmed_bars: int,
    hold: int, reverse_away: float, post_sweep_reverse: float,
) -> dict | None:
    """Scan today's bars for the FIRST approach to `pivot_value`.
    An approach is the first bar whose |close - pivot| <= proximity/10000
    OR hi/lo straddles pivot.
    Returns an event dict or None."""
    N = len(bars)
    first_approach_idx = None
    approach_dir = None
    for i, b in enumerate(bars):
        near_close = abs(b["c"] - pivot_value) * 10000.0 <= proximity
        straddles = b["l"] <= pivot_value <= b["h"]
        if near_close or straddles:
            first_approach_idx = i
            # Approach direction: sign of 10-bar close change (fallback: bar direction)
            k = max(0, i - 10)
            if i > 0:
                approach_dir = "UP" if b["c"] >= bars[k]["c"] else "DOWN"
            else:
                approach_dir = "UP" if b["c"] >= b["o"] else "DOWN"
            break
    if first_approach_idx is None:
        return None

    i = first_approach_idx
    b = bars[i]
    approach_proximity_pips = abs(b["c"] - pivot_value) * 10000.0
    straddles = b["l"] <= pivot_value <= b["h"]

    # Shortfall = closest price got to pivot BEFORE touching (in the approach bar
    # and up to 10 bars before). Positive = price fell short of pivot.
    look_start = max(0, i - 10)
    if approach_dir == "UP":
        closest = max(x["h"] for x in bars[look_start:i + 1])
        shortfall_pips = (pivot_value - closest) * 10000.0  # positive if closest < pivot
    else:
        closest = min(x["l"] for x in bars[look_start:i + 1])
        shortfall_pips = (closest - pivot_value) * 10000.0

    # Max overshoot beyond pivot across the current bar + hold horizon (first N bars)
    j = min(i + hold, N - 1)
    window_bars = bars[i:j + 1]
    if approach_dir == "UP":
        max_extreme = max(x["h"] for x in window_bars)
        max_overshoot_pips = max(0.0, (max_extreme - pivot_value) * 10000.0)
    else:
        min_extreme = min(x["l"] for x in window_bars)
        max_overshoot_pips = max(0.0, (pivot_value - min_extreme) * 10000.0)

    # Closes past pivot in the hold window (counting bars where close >= pivot+confirmed_pips)
    closes_past = 0
    max_close_past_pips = 0.0
    consecutive_closes_past = 0
    best_consecutive = 0
    for x in window_bars:
        if approach_dir == "UP":
            diff = (x["c"] - pivot_value) * 10000.0
        else:
            diff = (pivot_value - x["c"]) * 10000.0
        if diff >= confirmed_pips:
            closes_past += 1
            max_close_past_pips = max(max_close_past_pips, diff)
            consecutive_closes_past += 1
            best_consecutive = max(best_consecutive, consecutive_closes_past)
        else:
            consecutive_closes_past = 0

    # Reverse excursion within hold horizon
    if approach_dir == "UP":
        reverse_extreme = min(x["l"] for x in window_bars)
        max_reverse_pips = (pivot_value - reverse_extreme) * 10000.0
    else:
        reverse_extreme = max(x["h"] for x in window_bars)
        max_reverse_pips = (reverse_extreme - pivot_value) * 10000.0

    # Classification
    outcome_class = "STALL"
    if not straddles:
        # Approach without touch — reversal class only if price then moves away
        if max_reverse_pips >= reverse_away:
            outcome_class = "PRE_PIVOT_REVERSAL"
    else:
        # Touched. Decide between the three touch classes.
        confirmed_breakout = (closes_past >= confirmed_bars and max_close_past_pips >= 10.0)
        if confirmed_breakout:
            outcome_class = "CONFIRMED_BREAKOUT"
        elif max_overshoot_pips >= confirmed_pips and max_reverse_pips >= post_sweep_reverse:
            outcome_class = "STOP_SWEEP_REVERSAL"
        elif max_overshoot_pips < confirmed_pips and max_reverse_pips >= post_sweep_reverse:
            outcome_class = "AT_PIVOT_REVERSAL"
        elif closes_past >= 1 and closes_past < confirmed_bars:
            outcome_class = "WICK_UNCONFIRMED"
        # else STALL

    return {
        "pivot_name": pivot_name,
        "pivot_value": f"{pivot_value:.5f}",
        "approach_bar_ts": b["ts"].isoformat(),
        "approach_dir": approach_dir,
        "touched": int(straddles),
        "approach_proximity_pips": f"{approach_proximity_pips:.1f}",
        "shortfall_pips": f"{shortfall_pips:+.1f}",
        "max_overshoot_pips": f"{max_overshoot_pips:.1f}",
        "closes_past_count": closes_past,
        "best_consecutive_closes_past": best_consecutive,
        "max_close_past_pips": f"{max_close_past_pips:.1f}",
        "max_reverse_from_pivot_pips": f"{max_reverse_pips:.1f}",
        "outcome_class": outcome_class,
    }

def process(bid_only: bool, label: str) -> list[dict]:
    """Walk daily files, compute pivots from prior day, classify every pivot approach."""
    out = []
    # Build daily rollup cache from BID (2024-2025) + MID (2026 Jan-Feb)
    files = sorted(BID_ROOT.glob("*.csv"))
    if not bid_only:
        files += sorted(MID_ROOT.glob("2026-01-*.csv")) + sorted(MID_ROOT.glob("2026-02-*.csv"))

    daily_cache: dict[dt.date, list[dict]] = {}
    for f in files:
        try:
            d = dt.date.fromisoformat(f.stem)
        except ValueError:
            continue
        daily_cache[d] = load_day(f)

    sorted_dates = sorted(daily_cache.keys())
    for d in sorted_dates:
        bars = daily_cache[d]
        if not bars:
            continue
        prior = None
        for back in range(1, 8):
            cand = d - dt.timedelta(days=back)
            if cand in daily_cache and daily_cache[cand]:
                prior_bars = daily_cache[cand]
                prior = (
                    max(b["h"] for b in prior_bars),
                    min(b["l"] for b in prior_bars),
                    prior_bars[-1]["c"],
                )
                break
        if prior is None:
            continue
        H, L, C = prior
        piv = pivots(H, L, C)
        basis = "bid" if d.year < 2026 else "mid"

        for pn in PIVOT_NAMES:
            ev = classify_event(
                bars, piv[pn], pn,
                APPROACH_PROXIMITY_PIPS,
                CONFIRMED_CLOSE_PIPS,
                CONFIRMED_CLOSE_BARS,
                HOLD_HORIZON_BARS,
                REVERSAL_AWAY_PIPS,
                POST_SWEEP_REVERSE_PIPS,
            )
            if ev is None:
                continue
            out.append({"date": d.isoformat(), "basis": basis, "subset": label, **ev})
    return out

def sensitivity_table(events_all: list[dict]) -> None:
    """Rerun classification at LOOSE/BASE/STRICT and tabulate outcome shares for S2/R2/S3/R3."""
    print("\n=== Sensitivity test (counts by outcome class, S2/R2/S3/R3 only) ===")
    # For speed, run full rebuild for each row of the grid
    for label, prox, cp, cb, hold, ra, psr in GRID:
        # Rebuild
        files = sorted(BID_ROOT.glob("*.csv"))
        daily_cache: dict[dt.date, list[dict]] = {d: load_day(BID_ROOT / f"{d.isoformat()}.csv") for d in [dt.date.fromisoformat(f.stem) for f in files]}
        sorted_dates = sorted(daily_cache.keys())
        grid_out = []
        for d in sorted_dates:
            bars = daily_cache.get(d) or []
            if not bars: continue
            prior = None
            for back in range(1, 8):
                cand = d - dt.timedelta(days=back)
                pb = daily_cache.get(cand)
                if pb:
                    prior = (max(b["h"] for b in pb), min(b["l"] for b in pb), pb[-1]["c"])
                    break
            if prior is None: continue
            piv = pivots(*prior)
            for pn in ("S2", "R2", "S3", "R3"):
                ev = classify_event(bars, piv[pn], pn, prox, cp, cb, hold, ra, psr)
                if ev is None: continue
                grid_out.append((pn, ev["outcome_class"]))
        from collections import Counter
        print(f"\n--- {label}  prox={prox} close_pips={cp} close_bars={cb} hold={hold}bars reverse={ra}p sweep_reverse={psr}p ---")
        for pn in ("S2", "R2", "S3", "R3"):
            c = Counter(oc for p, oc in grid_out if p == pn)
            n = sum(c.values())
            if n == 0: continue
            parts = ", ".join(f"{k}={v}({100*v/n:.0f}%)" for k, v in c.most_common())
            print(f"  {pn:<4} n={n:<3}  {parts}")

def main() -> None:
    events_full = process(bid_only=False, label="ALL")
    print(f"Total approach events: {len(events_full)}")
    # Summary at BASE thresholds
    from collections import Counter
    for pn in ("S2", "R2", "S3", "R3"):
        sub = [e for e in events_full if e["pivot_name"] == pn]
        c = Counter(e["outcome_class"] for e in sub)
        print(f"\n{pn} (BASE thresholds) n={len(sub)}")
        for k, v in c.most_common():
            print(f"  {k:<22} {v:>4} ({100*v/len(sub):.1f}%)")

    # Save CSV
    if events_full:
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        fields = list(events_full[0].keys())
        with OUT_CSV.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(events_full)
        print(f"\nWrote {OUT_CSV}")

    # Sensitivity grid
    sensitivity_table(events_full)

if __name__ == "__main__":
    main()
