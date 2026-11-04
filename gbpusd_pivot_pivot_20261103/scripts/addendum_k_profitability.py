"""Addendum K — pivot-sequence continuation profitability.

Four sequences, five stop distances, by time-of-day and year.

Entry convention:
  * The first chronological M5 bar that straddles the STARTING pivot
    (low <= pivot <= high) triggers an entry in the direction of the
    next pivot: BUY on R1→R2 / R2→R3; SELL on S1→S2 / S2→S3.
  * Entry price assumed at the pivot value. Round-trip execution cost
    (spread + slippage) of 1.5 pips is subtracted from the final P&L.
    This matches the Addendum G/F convention and is realistic for
    GBP/USD in active-session hours.

Stop convention:
  * 5 / 10 / 15 / 20 / 25 pips from entry (adverse side).

Target convention:
  * Exact value of the next pivot.
  * RR = (target - entry) / (entry - stop), reported per sequence.

Simulation:
  * Walk forward from entry_idx + 1 to end of the day's bars.
  * Same-bar ambiguity: if a single M5 bar simultaneously touches stop
    AND target, mark as AMBIG. Default conservative outcome = SL (does
    NOT count as a win).
  * AMBIG is tick-resolvable where tick data exists; this run uses the
    conservative default. AMBIG counts are reported separately so the
    reader can bound the uplift.

Metrics per (sequence, stop_distance):
  * n entries, win rate, avg win, avg loss, net pips/trade, profit
    factor, max consecutive-trade drawdown, median holding time,
    unresolved, ambiguous.

Breakdowns: time-of-day (4 buckets), year (2024, 2025, 2026 Jan-Feb).

Writes csv/addendum_k_results.csv + csv/addendum_k_trades.csv.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import statistics
from collections import defaultdict

BID_ROOT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
MID_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
TRADES_CSV  = pathlib.Path(__file__).parent.parent / "csv" / "addendum_k_trades.csv"
RESULTS_CSV = pathlib.Path(__file__).parent.parent / "csv" / "addendum_k_results.csv"

STOPS = (5, 10, 15, 20, 25)
SPREAD_PIPS = 1.5  # round-trip execution cost

def load_day(path: pathlib.Path) -> list[dict]:
    if not path.exists(): return []
    out = []
    for row in csv.DictReader(path.open()):
        ts_raw = row["timestamp"].replace(" ", "T")
        try: ts = dt.datetime.fromisoformat(ts_raw)
        except: continue
        out.append({"ts": ts,
                    "o": float(row["open"])/10000.0,
                    "h": float(row["high"])/10000.0,
                    "l": float(row["low"])/10000.0,
                    "c": float(row["close"])/10000.0})
    return out

def pivots(H, L, C):
    P = (H + L + C) / 3.0
    return {"P":P, "R1":2*P-L,"R2":P+(H-L),"R3":H+2*(P-L),
                   "S1":2*P-H,"S2":P-(H-L),"S3":L-2*(H-P)}

def first_touch(bars, level):
    for i, b in enumerate(bars):
        if b["l"] <= level <= b["h"]:
            return i
    return None

def simulate(side, entry, stop, target, bars_after):
    """Walk forward. Return (outcome, hold_bars_or_None, net_pips_or_None).
    outcome in {TP, SL, AMBIG, UNRESOLVED}. Spread subtracted from TP net
    and from SL net (the spread is paid regardless of outcome)."""
    if not bars_after: return "UNRESOLVED", None, None
    for i, b in enumerate(bars_after):
        if side == "BUY":
            hit_sl = b["l"] <= stop
            hit_tp = b["h"] >= target
        else:
            hit_sl = b["h"] >= stop
            hit_tp = b["l"] <= target
        if hit_sl and hit_tp:
            # Conservative — count as SL for net P&L; report AMBIG separately
            net = -abs(entry - stop) * 10000.0 - SPREAD_PIPS
            return "AMBIG", i + 1, net
        if hit_tp:
            net = abs(target - entry) * 10000.0 - SPREAD_PIPS
            return "TP", i + 1, net
        if hit_sl:
            net = -abs(entry - stop) * 10000.0 - SPREAD_PIPS
            return "SL", i + 1, net
    return "UNRESOLVED", None, None

def tod_bucket(h):
    if h < 7:   return "before_07"
    if h < 12:  return "0700_1159"
    if h < 16:  return "1200_1559"
    return "1600_plus"

def main() -> None:
    # Load daily cache (certified)
    daily_cache: dict[dt.date, list[dict]] = {}
    for root in (BID_ROOT, MID_ROOT):
        for f in root.glob("*.csv"):
            try: d = dt.date.fromisoformat(f.stem)
            except: continue
            if d.year == 2026 and d.month > 2: continue
            if d not in daily_cache:
                daily_cache[d] = load_day(f)
    sorted_dates = sorted(daily_cache.keys())
    prior_rollup = {}
    for d in sorted_dates:
        bars = daily_cache[d]
        if bars:
            prior_rollup[d] = (max(b["h"] for b in bars),
                               min(b["l"] for b in bars),
                               bars[-1]["c"])

    SEQUENCES = [
        ("R1", "R2", "BUY",  "ABOVE"),
        ("R2", "R3", "BUY",  "ABOVE"),
        ("S1", "S2", "SELL", "BELOW"),
        ("S2", "S3", "SELL", "BELOW"),
    ]

    trades = []  # per-trade log
    for d in sorted_dates:
        bars = daily_cache[d]
        if not bars: continue
        prior = None
        for back in range(1, 8):
            cand = d - dt.timedelta(days=back)
            if cand in prior_rollup:
                prior = prior_rollup[cand]; break
        if prior is None: continue
        H, L, C = prior
        piv = pivots(H, L, C)
        open_px = bars[0]["o"]
        side_open = "ABOVE" if open_px > piv["P"] else "BELOW" if open_px < piv["P"] else None
        if side_open is None: continue

        for (start, dest, side, needed_open) in SEQUENCES:
            if needed_open != side_open: continue
            t_start = first_touch(bars, piv[start])
            if t_start is None: continue
            entry = piv[start]
            target = piv[dest]
            target_dist_pips = abs(target - entry) * 10000.0
            touch_hour = bars[t_start]["ts"].hour

            for stop_d in STOPS:
                stop = entry - stop_d/10000.0 if side == "BUY" else entry + stop_d/10000.0
                rr = target_dist_pips / stop_d
                bars_after = bars[t_start + 1:]
                outcome, hold, net = simulate(side, entry, stop, target, bars_after)
                trades.append({
                    "date": d.isoformat(),
                    "year": d.year,
                    "sequence": f"{start}->{dest}",
                    "side": side,
                    "touch_hour_utc": touch_hour,
                    "tod_bucket": tod_bucket(touch_hour),
                    "stop_pips": stop_d,
                    "target_pips": f"{target_dist_pips:.1f}",
                    "rr": f"{rr:.2f}",
                    "outcome": outcome,
                    "hold_bars": hold if hold is not None else "",
                    "net_pips": f"{net:+.2f}" if net is not None else "",
                })

    # Write per-trade CSV
    TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(trades[0].keys())
    with TRADES_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(trades)
    print(f"Wrote {len(trades)} trade rows to {TRADES_CSV}")

    def aggregate(subset, label):
        resolved = [t for t in subset if t["outcome"] in ("TP", "SL", "AMBIG")]
        unres   = sum(1 for t in subset if t["outcome"] == "UNRESOLVED")
        ambig   = sum(1 for t in subset if t["outcome"] == "AMBIG")
        wins    = [t for t in resolved if t["outcome"] == "TP"]
        losses  = [t for t in resolved if t["outcome"] in ("SL", "AMBIG")]
        n = len(subset)
        n_res = len(resolved)
        win_rate = 100 * len(wins) / n_res if n_res else float("nan")
        avg_win  = statistics.mean([float(t["net_pips"]) for t in wins]) if wins else float("nan")
        avg_loss = statistics.mean([float(t["net_pips"]) for t in losses]) if losses else float("nan")
        total    = sum(float(t["net_pips"]) for t in resolved) if resolved else 0.0
        mean     = total / n_res if n_res else float("nan")
        win_sum  = sum(float(t["net_pips"]) for t in wins)
        loss_sum = -sum(float(t["net_pips"]) for t in losses) if losses else 0.0
        pf       = (win_sum / loss_sum) if loss_sum > 0 else float("inf")
        holds    = [int(t["hold_bars"]) for t in resolved if t["hold_bars"] != ""]
        med_hold = statistics.median(holds) * 5 if holds else None  # minutes

        # Chronological running-equity drawdown
        series = sorted(resolved, key=lambda t: t["date"])
        equity = 0.0; peak = 0.0; maxdd = 0.0
        for t in series:
            equity += float(t["net_pips"])
            if equity > peak: peak = equity
            dd = peak - equity
            if dd > maxdd: maxdd = dd

        return {
            "label": label,
            "n": n, "n_res": n_res, "unresolved": unres, "ambig": ambig,
            "win_rate_pct": win_rate, "n_wins": len(wins),
            "avg_win_p": avg_win, "avg_loss_p": avg_loss,
            "net_total_p": total, "net_mean_p": mean,
            "profit_factor": pf,
            "max_dd_p": maxdd,
            "median_hold_min": med_hold,
        }

    # Build the big per-sequence, per-stop table
    rows_out = []
    print("\n" + "=" * 100)
    print("MAIN TABLE — by sequence × stop distance (all 676 days)")
    print("=" * 100)
    print(f"  {'Sequence':<10} {'Stop':>4} {'N':>4} {'Res':>4} {'Un':>3} {'Am':>3}  "
          f"{'Win%':>5} {'AvgW':>6} {'AvgL':>6} {'Mean':>6} {'Total':>7} {'PF':>5} {'MaxDD':>6} {'Hold':>5}")
    for (start, dest, side, _) in SEQUENCES:
        for stop_d in STOPS:
            subset = [t for t in trades if t["sequence"] == f"{start}->{dest}" and t["stop_pips"] == stop_d]
            if not subset: continue
            agg = aggregate(subset, f"{start}->{dest} {stop_d}p")
            pf_s = "inf" if agg["profit_factor"] == float("inf") else f"{agg['profit_factor']:.2f}"
            hold_s = f"{agg['median_hold_min']:.0f}m" if agg["median_hold_min"] is not None else "—"
            print(f"  {start+'->'+dest:<10} {stop_d:>3}p {agg['n']:>4} {agg['n_res']:>4} "
                  f"{agg['unresolved']:>3} {agg['ambig']:>3}  "
                  f"{agg['win_rate_pct']:>4.1f} "
                  f"{agg['avg_win_p']:>+6.2f} {agg['avg_loss_p']:>+6.2f} "
                  f"{agg['net_mean_p']:>+6.2f} {agg['net_total_p']:>+7.1f} "
                  f"{pf_s:>5} {agg['max_dd_p']:>5.1f}p {hold_s:>5}")
            rows_out.append({
                "scope": "ALL",
                "sequence": f"{start}->{dest}",
                "stop_pips": stop_d,
                **agg,
            })

    # Time-of-day breakdown
    print("\n" + "=" * 100)
    print("TIME-OF-DAY BREAKDOWN — by sequence × stop × tod_bucket")
    print("=" * 100)
    for (start, dest, side, _) in SEQUENCES:
        print(f"\n{start}->{dest}:")
        print(f"  {'bucket':<12} {'Stop':>4} {'N':>4}  {'Win%':>5} {'Mean':>6} {'Total':>7} {'PF':>5}")
        for b in ("before_07", "0700_1159", "1200_1559", "1600_plus"):
            for stop_d in STOPS:
                sub = [t for t in trades if t["sequence"] == f"{start}->{dest}"
                       and t["stop_pips"] == stop_d and t["tod_bucket"] == b]
                if not sub: continue
                agg = aggregate(sub, f"{start}->{dest} {stop_d}p {b}")
                pf_s = "inf" if agg["profit_factor"] == float("inf") else f"{agg['profit_factor']:.2f}"
                print(f"  {b:<12} {stop_d:>3}p {agg['n']:>4}  {agg['win_rate_pct']:>4.1f} "
                      f"{agg['net_mean_p']:>+6.2f} {agg['net_total_p']:>+7.1f} {pf_s:>5}")
                rows_out.append({"scope": f"TOD:{b}", "sequence": f"{start}->{dest}",
                                 "stop_pips": stop_d, **agg})

    # Year breakdown
    print("\n" + "=" * 100)
    print("YEAR BREAKDOWN — 2024 / 2025 / 2026 Jan-Feb")
    print("=" * 100)
    for year in (2024, 2025, 2026):
        print(f"\nYear {year}:")
        print(f"  {'Sequence':<10} {'Stop':>4} {'N':>4}  {'Win%':>5} {'Mean':>6} {'Total':>7} {'PF':>5}")
        for (start, dest, side, _) in SEQUENCES:
            for stop_d in STOPS:
                sub = [t for t in trades if t["sequence"] == f"{start}->{dest}"
                       and t["stop_pips"] == stop_d and t["year"] == year]
                if not sub: continue
                agg = aggregate(sub, f"{year} {start}->{dest} {stop_d}p")
                pf_s = "inf" if agg["profit_factor"] == float("inf") else f"{agg['profit_factor']:.2f}"
                print(f"  {start+'->'+dest:<10} {stop_d:>3}p {agg['n']:>4}  {agg['win_rate_pct']:>4.1f} "
                      f"{agg['net_mean_p']:>+6.2f} {agg['net_total_p']:>+7.1f} {pf_s:>5}")
                rows_out.append({"scope": f"YEAR:{year}", "sequence": f"{start}->{dest}",
                                 "stop_pips": stop_d, **agg})

    # Write aggregated CSV
    fields = ["scope","sequence","stop_pips","label","n","n_res","unresolved","ambig",
              "win_rate_pct","n_wins","avg_win_p","avg_loss_p","net_total_p","net_mean_p",
              "profit_factor","max_dd_p","median_hold_min"]
    with RESULTS_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows_out:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"\nWrote aggregated results to {RESULTS_CSV}")

if __name__ == "__main__":
    main()
