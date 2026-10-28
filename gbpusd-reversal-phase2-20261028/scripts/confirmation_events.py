"""Preregistered confirmation events C1-C6.

For each candidate episode, find the first qualifying confirmation bar
AFTER the candidate (C1 is the candidate itself).  Record:

* bars_to_confirm (M5 bars from candidate)
* confirm_close
* distance_from_extreme_pts  — on the reversal side (positive = already
  moved against the original run)
* subsequent MFE / MAE at +60 min from the confirmation bar's close
* did_reach_15 / 30 / 50 pts  (from confirmation close in reversal
  direction, before −5 p past the ORIGINAL candidate extreme)

Writes EARLY_CONFIRMATION_RESULTS.csv (one row per episode × event),
and prints a formatted summary of % producing it + medians + reach
rates grouped by (year, kind, outcome_label).
"""
from __future__ import annotations

import csv
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, ema, read_bid_m5


# ─────────────────────────────────────────────────────────────────────
# Confirmation-event detectors
# ─────────────────────────────────────────────────────────────────────
def _c1(bars: list[Bar], ev: int, kind: str) -> tuple[int | None, float | None]:
    """C1 = rejection candle close itself (immediate, distance=0)."""
    return ev, bars[ev].close


def _c2(bars: list[Bar], ev: int, kind: str) -> tuple[int | None, float | None]:
    """C2 = first bar after candidate whose high (BULL) / low (BEAR)
    breaks the candidate's own high (BULL) / low (BEAR)."""
    anchor_high = bars[ev].high
    anchor_low = bars[ev].low
    for i in range(ev + 1, min(ev + 13, len(bars))):
        if kind == "BULL" and bars[i].high > anchor_high:
            return i, bars[i].close
        if kind == "BEAR" and bars[i].low < anchor_low:
            return i, bars[i].close
    return None, None


def _c3(bars: list[Bar], ev: int, kind: str) -> tuple[int | None, float | None]:
    """C3 = first bar with body > 5p on the reversal side."""
    for i in range(ev + 1, min(ev + 13, len(bars))):
        b = bars[i]
        if kind == "BULL" and b.is_green and b.body > 5.0:
            return i, b.close
        if kind == "BEAR" and b.is_red and b.body > 5.0:
            return i, b.close
    return None, None


def _c4(bars: list[Bar], ev: int, kind: str) -> tuple[int | None, float | None]:
    """C4 = first close beyond previous bar's extreme on reversal side."""
    for i in range(ev + 1, min(ev + 13, len(bars))):
        prev = bars[i - 1]
        if kind == "BULL" and bars[i].close > prev.high:
            return i, bars[i].close
        if kind == "BEAR" and bars[i].close < prev.low:
            return i, bars[i].close
    return None, None


def _c5(bars: list[Bar], ev: int, kind: str) -> tuple[int | None, float | None]:
    """C5 = first EMA7 cross on the reversal side (close> EMA7 for BULL)."""
    # EMA7 built from closes up to i inclusive at every i
    closes = [b.close for b in bars]
    e7 = ema(closes, 7)
    for i in range(ev + 1, min(ev + 13, len(bars))):
        if e7[i] is None:
            continue
        if kind == "BULL" and bars[i].close > e7[i]:
            return i, bars[i].close
        if kind == "BEAR" and bars[i].close < e7[i]:
            return i, bars[i].close
    return None, None


def _c6(bars: list[Bar], ev: int, kind: str) -> tuple[int | None, float | None]:
    """C6 = first higher-low (BULL) or lower-high (BEAR) with a reversal-side
    close.  Needs ≥2 bars after the candidate — compare bar[i].low to
    bars[ev].low (strict above) + green close."""
    anchor_low = bars[ev].low
    anchor_high = bars[ev].high
    for i in range(ev + 1, min(ev + 13, len(bars))):
        b = bars[i]
        if kind == "BULL" and b.low > anchor_low and b.is_green:
            return i, b.close
        if kind == "BEAR" and b.high < anchor_high and b.is_red:
            return i, b.close
    return None, None


CONFIRMERS = [("C1", _c1), ("C2", _c2), ("C3", _c3),
              ("C4", _c4), ("C5", _c5), ("C6", _c6)]


# ─────────────────────────────────────────────────────────────────────
# Reach measurement from the confirmation close
# ─────────────────────────────────────────────────────────────────────
def _reach_from(bars: list[Bar], ev: int, confirm_i: int, kind: str,
                confirm_close: float) -> dict:
    """From confirm bar's close, within +60 min (12 bars), measure MFE/
    MAE and whether price reached +15 / +30 / +50 pts BEFORE breaking
    −5 pts past the ORIGINAL event extreme."""
    HORIZON = 12
    extreme = bars[ev].low if kind == "BULL" else bars[ev].high
    end = min(confirm_i + HORIZON, len(bars) - 1)
    reached_15 = reached_30 = reached_50 = False
    stopped = False
    mfe = mae = 0.0
    for i in range(confirm_i + 1, end + 1):
        bar_hits_15 = bar_hits_30 = bar_hits_50 = bar_stops = False
        if kind == "BULL":
            bar_hits_15 = bars[i].high >= confirm_close + 15.0
            bar_hits_30 = bars[i].high >= confirm_close + 30.0
            bar_hits_50 = bars[i].high >= confirm_close + 50.0
            bar_stops = bars[i].low <= extreme - 5.0
            mfe = max(mfe, bars[i].high - confirm_close)
            mae = max(mae, confirm_close - bars[i].low)
        else:
            bar_hits_15 = bars[i].low <= confirm_close - 15.0
            bar_hits_30 = bars[i].low <= confirm_close - 30.0
            bar_hits_50 = bars[i].low <= confirm_close - 50.0
            bar_stops = bars[i].high >= extreme + 5.0
            mfe = max(mfe, confirm_close - bars[i].low)
            mae = max(mae, bars[i].high - confirm_close)
        if bar_stops and not (bar_hits_15 or bar_hits_30 or bar_hits_50):
            stopped = True
            break
        if bar_stops and (bar_hits_15 or bar_hits_30 or bar_hits_50):
            # intrabar ambiguity on this stop bar — conservative = stopped
            stopped = True
            break
        if bar_hits_50:
            reached_50 = reached_30 = reached_15 = True
            break
        if bar_hits_30:
            reached_30 = reached_15 = True
            # keep looking for 50 only if didn't stop
            continue
        if bar_hits_15:
            reached_15 = True
            continue
    return {
        "mfe_pts": round(mfe, 2),
        "mae_pts": round(mae, 2),
        "reached_15": reached_15,
        "reached_30": reached_30,
        "reached_50": reached_50,
        "stopped": stopped,
    }


def main() -> int:
    in_csv = HERE.parent / "data" / "FULL_POPULATION_RESULTS.csv"
    rows = list(csv.DictReader(in_csv.open()))

    by_date: dict[str, list[dict]] = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)

    out_rows: list[dict] = []
    for date_str in sorted(by_date):
        date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        try:
            bars = read_bid_m5(date)
        except FileNotFoundError:
            continue
        ts_to_idx = {b.ts.isoformat(): i for i, b in enumerate(bars)}
        for r in by_date[date_str]:
            ev = ts_to_idx.get(r["event_ts_utc"])
            if ev is None:
                continue
            extreme = bars[ev].low if r["kind"] == "BULL" else bars[ev].high
            for cname, fn in CONFIRMERS:
                ci, close = fn(bars, ev, r["kind"])
                row = {
                    "year": r["year"], "date": r["date"],
                    "event_ts_utc": r["event_ts_utc"],
                    "kind": r["kind"], "outcome_label": r["outcome_label"],
                    "event": cname,
                    "produced": ci is not None,
                    "bars_to_confirm": (ci - ev) if ci is not None else None,
                    "confirm_close": round(close, 2) if close is not None else None,
                    "distance_from_extreme_pts":
                        (round((close - extreme) if r["kind"] == "BULL"
                               else (extreme - close), 2)
                         if close is not None else None),
                }
                if ci is not None:
                    reach = _reach_from(bars, ev, ci, r["kind"], close)
                    row.update(reach)
                else:
                    for k in ("mfe_pts", "mae_pts", "reached_15",
                              "reached_30", "reached_50", "stopped"):
                        row[k] = None
                out_rows.append(row)

    out_path = HERE.parent / "data" / "EARLY_CONFIRMATION_RESULTS.csv"
    fieldnames = list(out_rows[0].keys())
    with out_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"✓ wrote {out_path} ({len(out_rows)} rows)")

    # Summary — for each (year, kind, outcome_prefix) × event
    print("\n============================================================")
    print("CONFIRMATION EVENTS — produce% / median bars / median dist /"
          " reach_15/30/50 (per episode within confirmation set)")
    print("============================================================")
    for year in ("2024", "2025"):
        for kind in ("BULL", "BEAR"):
            # Across all outcome labels for this year × kind
            for outcome_prefix in ("SUCCESS", "FAIL", "AMBIGUOUS"):
                subset = [r for r in out_rows
                          if r["year"] == year and r["kind"] == kind
                          and r["outcome_label"].startswith(outcome_prefix)]
                n_episodes = len({r["event_ts_utc"] for r in subset})
                print(f"\n--- {year} {kind} {outcome_prefix} (n={n_episodes}) ---")
                for cname, _ in CONFIRMERS:
                    cs = [r for r in subset if r["event"] == cname]
                    produced = [r for r in cs if r["produced"]]
                    pct_prod = round(100.0 * len(produced) / len(cs), 1) if cs else 0.0
                    med_bars = (statistics.median(float(r["bars_to_confirm"]) for r in produced)
                                if produced else None)
                    med_dist = (statistics.median(float(r["distance_from_extreme_pts"]) for r in produced)
                                if produced else None)
                    r15 = sum(1 for r in produced if r["reached_15"] is True)
                    r30 = sum(1 for r in produced if r["reached_30"] is True)
                    r50 = sum(1 for r in produced if r["reached_50"] is True)
                    reach_pct = lambda c: round(100.0 * c / len(produced), 1) if produced else 0.0
                    print(f"  {cname}: prod={pct_prod}%  med_bars={med_bars}  "
                          f"med_dist={med_dist}p  "
                          f"R15={reach_pct(r15)}%  R30={reach_pct(r30)}%  "
                          f"R50={reach_pct(r50)}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
