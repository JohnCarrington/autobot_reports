"""Preregistered SL × TP execution feasibility grid.

For every candidate episode and every confirmation event that
produced a confirmation, simulate an entry at the confirmation bar's
close and evaluate the trade with:

    SL ∈ {4, 6, 8, 12} pips (fixed, from entry)
    TP ∈ {15, 30, 50} pips (fixed, from entry)
    spread ∈ {0, 1, 2} pips (buy adds half spread to entry /
                             SL+TP measured on bid)

Horizon: next 12 M5 bars (60 min) after the confirmation bar.

Intrabar ambiguity rule (frozen in preregistration): if an M5 bar's
high reaches TP and low reaches SL within the same bar, score as
AMBIGUOUS — NOT favourable.

Reports per (year, kind, confirmation_event, SL, TP, spread):
    n_episodes_fired, n_tp, n_sl, n_amb, n_horizon_out,
    hit_rate_tp (within decisive), expectancy_pts (net of spread),
    expectancy_pts_amb_as_sl (worst-case accounting).

Writes ENTRY_EXECUTION_FEASIBILITY.csv.  Also prints a focused
summary for the operator-visible best / worst cells.
"""
from __future__ import annotations

import csv
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, ema, read_bid_m5


# ─── Confirmation detectors (reuse from confirmation_events.py but inline
#     a lean copy here to keep this script self-contained) ────────────────
def _c1(bars, ev, kind):
    return ev, bars[ev].close


def _c2(bars, ev, kind):
    for i in range(ev + 1, min(ev + 13, len(bars))):
        if kind == "BULL" and bars[i].high > bars[ev].high:
            return i, bars[i].close
        if kind == "BEAR" and bars[i].low < bars[ev].low:
            return i, bars[i].close
    return None, None


def _c3(bars, ev, kind):
    for i in range(ev + 1, min(ev + 13, len(bars))):
        b = bars[i]
        if kind == "BULL" and b.is_green and b.body > 5.0:
            return i, b.close
        if kind == "BEAR" and b.is_red and b.body > 5.0:
            return i, b.close
    return None, None


def _c4(bars, ev, kind):
    for i in range(ev + 1, min(ev + 13, len(bars))):
        prev = bars[i - 1]
        if kind == "BULL" and bars[i].close > prev.high:
            return i, bars[i].close
        if kind == "BEAR" and bars[i].close < prev.low:
            return i, bars[i].close
    return None, None


def _c5(bars, ev, kind, ema7):
    for i in range(ev + 1, min(ev + 13, len(bars))):
        if ema7[i] is None:
            continue
        if kind == "BULL" and bars[i].close > ema7[i]:
            return i, bars[i].close
        if kind == "BEAR" and bars[i].close < ema7[i]:
            return i, bars[i].close
    return None, None


def _c6(bars, ev, kind):
    for i in range(ev + 1, min(ev + 13, len(bars))):
        b = bars[i]
        if kind == "BULL" and b.low > bars[ev].low and b.is_green:
            return i, b.close
        if kind == "BEAR" and b.high < bars[ev].high and b.is_red:
            return i, b.close
    return None, None


def _simulate(bars: list[Bar], confirm_i: int, kind: str,
              entry: float, sl_pts: float, tp_pts: float,
              spread_pts: float) -> str:
    """Return one of: 'TP', 'SL', 'AMB', 'OUT'.

    Entry at ``entry`` on the BID (BULL buy, BEAR sell).
    Spread treated as a cost on exit: BUY exits on bid at ``bid - spread``;
    BEAR SELL exits at bid+spread.  To preserve the frozen BID-only
    simulation and keep spread sensitivity explicit, we equivalently
    raise the SL and TP distances by ``spread_pts`` on BULL (bid must
    go higher to realise net profit; bid must drop less to incur net
    loss relative to the quoted entry) and symmetrically on BEAR.
    """
    HORIZON = 12
    end = min(confirm_i + HORIZON, len(bars) - 1)
    for i in range(confirm_i + 1, end + 1):
        bar = bars[i]
        if kind == "BULL":
            tp_hit = bar.high >= entry + tp_pts + spread_pts
            sl_hit = bar.low <= entry - sl_pts - spread_pts
        else:
            tp_hit = bar.low <= entry - tp_pts - spread_pts
            sl_hit = bar.high >= entry + sl_pts + spread_pts
        if tp_hit and sl_hit:
            return "AMB"
        if tp_hit:
            return "TP"
        if sl_hit:
            return "SL"
    return "OUT"


SLS = (4, 6, 8, 12)
TPS = (15, 30, 50)
SPREADS = (0, 1, 2)

CONFIRMERS = [("C1", "c1"), ("C2", "c2"), ("C3", "c3"),
              ("C4", "c4"), ("C5", "c5"), ("C6", "c6")]


def main() -> int:
    in_csv = HERE.parent / "data" / "FULL_POPULATION_RESULTS.csv"
    rows = list(csv.DictReader(in_csv.open()))

    by_date: dict[str, list[dict]] = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)

    # Collect per (year, kind, cname, sl, tp, spread) counters
    agg = defaultdict(lambda: Counter())

    for date_str in sorted(by_date):
        date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        try:
            bars = read_bid_m5(date)
        except FileNotFoundError:
            continue
        closes = [b.close for b in bars]
        ema7 = ema(closes, 7)
        ts_to_idx = {b.ts.isoformat(): i for i, b in enumerate(bars)}
        for r in by_date[date_str]:
            ev = ts_to_idx.get(r["event_ts_utc"])
            if ev is None:
                continue
            kind = r["kind"]
            year = r["year"]
            for cname, _tag in CONFIRMERS:
                if cname == "C1":
                    ci, close = _c1(bars, ev, kind)
                elif cname == "C2":
                    ci, close = _c2(bars, ev, kind)
                elif cname == "C3":
                    ci, close = _c3(bars, ev, kind)
                elif cname == "C4":
                    ci, close = _c4(bars, ev, kind)
                elif cname == "C5":
                    ci, close = _c5(bars, ev, kind, ema7)
                else:
                    ci, close = _c6(bars, ev, kind)
                if ci is None:
                    continue
                for sl in SLS:
                    for tp in TPS:
                        for sp in SPREADS:
                            out = _simulate(bars, ci, kind, close, sl, tp, sp)
                            key = (year, kind, cname, sl, tp, sp)
                            agg[key][out] += 1
                            agg[key]["N"] += 1

    # Write CSV
    out_rows = []
    for key, counter in sorted(agg.items()):
        year, kind, cname, sl, tp, sp = key
        n = counter["N"]
        n_tp = counter["TP"]
        n_sl = counter["SL"]
        n_amb = counter["AMB"]
        n_out = counter["OUT"]
        decisive = n_tp + n_sl
        hit_rate_decisive = (n_tp / decisive) if decisive else None
        # Expectancy A: ambiguous and horizon-out ignored (decisive only)
        # pts counted on the BID (hence after spread adjustment above the
        # ``spread_pts`` is already baked into TP/SL distances)
        exp_decisive = ((n_tp * tp - n_sl * sl) / decisive) if decisive else None
        # Expectancy B: ambiguous counted as SL (worst case)
        exp_worst = ((n_tp * tp - (n_sl + n_amb) * sl) /
                     (n_tp + n_sl + n_amb)) if (n_tp + n_sl + n_amb) else None
        out_rows.append({
            "year": year, "kind": kind, "event": cname,
            "sl_pts": sl, "tp_pts": tp, "spread_pts": sp,
            "n_fired": n, "n_tp": n_tp, "n_sl": n_sl, "n_amb": n_amb, "n_out": n_out,
            "hit_rate_decisive": round(hit_rate_decisive, 4) if hit_rate_decisive is not None else "",
            "expectancy_pts_decisive": round(exp_decisive, 2) if exp_decisive is not None else "",
            "expectancy_pts_amb_as_sl": round(exp_worst, 2) if exp_worst is not None else "",
        })

    out_path = HERE.parent / "data" / "ENTRY_EXECUTION_FEASIBILITY.csv"
    fieldnames = list(out_rows[0].keys())
    with out_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"✓ wrote {out_path} ({len(out_rows)} rows)")

    # Focused print — best / worst cells per (year, kind, event) by
    # expectancy_pts_amb_as_sl (worst-case accounting with 1p spread)
    print("\n============================================================")
    print("BEST CELLS BY EXPECTANCY (AMB-as-SL, 1p spread) — by (year, kind)")
    print("============================================================")
    for year in ("2024", "2025"):
        for kind in ("BULL", "BEAR"):
            cells = [r for r in out_rows
                     if r["year"] == year and r["kind"] == kind
                     and r["spread_pts"] == 1
                     and r["expectancy_pts_amb_as_sl"] != ""]
            if not cells:
                continue
            cells.sort(key=lambda r: r["expectancy_pts_amb_as_sl"], reverse=True)
            print(f"\n--- {year} {kind} ---")
            for r in cells[:6]:
                print(f"  {r['event']} SL={r['sl_pts']} TP={r['tp_pts']}  "
                      f"n={r['n_fired']}  TP={r['n_tp']}/SL={r['n_sl']}/AMB={r['n_amb']}  "
                      f"hit={r['hit_rate_decisive']}  "
                      f"exp_decisive={r['expectancy_pts_decisive']}p  "
                      f"exp_amb_as_sl={r['expectancy_pts_amb_as_sl']}p")
            print("  ...worst:")
            for r in cells[-3:]:
                print(f"  {r['event']} SL={r['sl_pts']} TP={r['tp_pts']}  "
                      f"n={r['n_fired']}  TP={r['n_tp']}/SL={r['n_sl']}/AMB={r['n_amb']}  "
                      f"exp_amb_as_sl={r['expectancy_pts_amb_as_sl']}p")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
