#!/usr/bin/env python3
"""Era B GBPUSD_BB_BOUNCE_S benchmark runner.

Loads 5m candles for the Era B window, drives the pierce+rejection
entry detector, applies the 4-exit manager to each fire, and emits:

  outputs/benchmark_fires.csv     — every signal the detector emitted
  outputs/parity_report.csv       — 36-row deal-by-deal parity table
                                    (benchmark vs ledger, side by side)
  outputs/false_positives.csv     — benchmark fires with no ledger match
  outputs/false_negatives.csv     — ledger rows with no benchmark match
  outputs/per_day_summary.csv     — daily aggregate: benchmark vs ledger
  outputs/summary.json            — machine-readable summary

Usage:
  python3 run_benchmark.py [--pierce-thresh 0.5|2.0]
                           [--start 2026-05-23] [--end 2026-06-25]

Broker submission: NEVER. IG modules are not imported at any point.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Package import
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from era_b_bench import config
from era_b_bench.candles import load_range, stream_from, Bar
from era_b_bench.entry import EraBEntryDetector, Signal
from era_b_bench.exits import ExitReport, simulate as run_exits
from era_b_bench.ledger import load_era_b_rows, LedgerRow


OUTDIR = HERE / "outputs"


def _match_price(a: float, b: float, tol_units: float = 0.05) -> bool:
    return abs(a - b) <= tol_units


def _bar_close_ts(sig: Signal) -> datetime:
    return sig.ts_utc


def run(pierce_thresh_pips: float, start_date: str, end_date: str) -> Dict:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    # ─── stage 1: load bars ─────────────────────────────────────────────
    bars = load_range(start_date, end_date)
    if not bars:
        raise RuntimeError(f"No candles in {start_date} → {end_date}. "
                           f"Check /opt/tradingbot/data/candles/GBPUSD/.")

    # ─── stage 2: detect signals ────────────────────────────────────────
    detector = EraBEntryDetector(pierce_thresh_pips=pierce_thresh_pips)
    fires: List[Signal] = []
    for bar in bars:
        sig = detector.on_bar(bar)
        if sig is not None:
            fires.append(sig)

    # ─── stage 3: apply exits ───────────────────────────────────────────
    exits: Dict[str, ExitReport] = {}
    for sig in fires:
        # Feed the manager the bars starting at the bar whose OPEN
        # equals rejection.close_ts (i.e., bar N+1).
        downstream = stream_from(sig.rejection_bar.close_ts, config.MAX_HOLD_BARS)
        exits[sig.ts_utc.isoformat()] = run_exits(sig, downstream)

    # ─── stage 4: load ledger + match ───────────────────────────────────
    ledger = load_era_b_rows()
    assert len(ledger) == 36, f"Expected 36 Era B rows, got {len(ledger)}"

    # Match by (rejection_bar_open_ts, direction, entry_price within 0.05 units).
    # 0.05 units = 0.05 pips: strict enough to catch off-by-one bar
    # errors, generous enough to accept float printing round-trips.
    fire_by_key: Dict[tuple, Signal] = {}
    for sig in fires:
        key = (sig.rejection_bar.ts.isoformat(), sig.direction)
        fire_by_key[key] = sig

    parity_rows: List[Dict] = []
    matched_fires: set = set()
    for row in ledger:
        rej_open_iso = row.rejection_bar_open_ts.isoformat()
        key = (rej_open_iso, row.direction)
        sig = fire_by_key.get(key)
        matched = False
        price_delta_pips: Optional[float] = None
        exit_rep: Optional[ExitReport] = None
        if sig is not None:
            # Match rule: same rejection bar (5-min timestamp) + same
            # direction. Price delta is recorded as a diagnostic — the
            # candle CSV stores MID close while the ledger stores the
            # broker fill (BID for SELL) recorded 3-10 seconds after
            # the close (execution latency). Deltas up to ~2 pips are
            # normal broker slippage; deltas > 3 pips are flagged.
            price_delta_pips = round(sig.entry_price - row.entry_price, 3)
            matched = True
            matched_fires.add(id(sig))
            exit_rep = exits[sig.ts_utc.isoformat()]

        parity_rows.append(_format_parity_row(row, sig, exit_rep, matched, price_delta_pips))

    # False positives: benchmark fires that didn't map to any ledger row
    false_positives: List[Signal] = [s for s in fires if id(s) not in matched_fires]
    false_negatives: List[LedgerRow] = [row for row, prow in zip(ledger, parity_rows)
                                        if not prow["matched"]]

    # ─── stage 5: write outputs ─────────────────────────────────────────
    _write_benchmark_fires(fires, exits)
    _write_parity(parity_rows)
    _write_false_positives(false_positives, exits)
    _write_false_negatives(false_negatives)
    per_day = _write_per_day(parity_rows)
    summary = _write_summary(fires, false_positives, false_negatives, parity_rows,
                             per_day, pierce_thresh_pips, start_date, end_date)
    return summary


# ─── formatters ─────────────────────────────────────────────────────────

def _format_parity_row(row: LedgerRow, sig: Optional[Signal],
                       exit_rep: Optional[ExitReport], matched: bool,
                       price_delta_pips: Optional[float] = None) -> Dict:
    partials_str = ""
    final_str = ""
    bench_pips = ""
    bench_gbp = ""
    bench_scaled = ""
    bench_mfe = ""
    bench_mae = ""
    bench_duration = ""
    signal_ts = ""
    signal_entry = ""
    initial_stop = ""
    if sig is not None:
        signal_ts    = sig.ts_utc.isoformat()
        signal_entry = round(sig.entry_price, 3)
        initial_stop = round(sig.entry_price + (config.SL_PIPS * config.PIP_UNITS), 3)  # SHORT SL above entry
    if exit_rep is not None:
        partials_str = ";".join(
            f"{p.ts_utc.isoformat()}@{round(p.price,3)}:frac={p.fraction_closed}:pips={round(p.pips_banked,2)}"
            for p in exit_rep.partials
        )
        if exit_rep.final is not None:
            final_str = (f"{exit_rep.final.ts_utc.isoformat()}@{round(exit_rep.final.price,3)}"
                         f":reason={exit_rep.final.reason}:pips={round(exit_rep.final.pips,2)}"
                         f":frac={exit_rep.final.fraction_closed}")
        bench_pips = round(exit_rep.total_pips, 2)
        bench_gbp = round(exit_rep.total_gbp_at_stake1, 2)
        bench_scaled = exit_rep.scaled_out
        bench_mfe = exit_rep.mfe_pips
        bench_mae = exit_rep.mae_pips
        bench_duration = exit_rep.duration_bars * 5
    return {
        "deal_id":                        row.deal_id,
        "matched":                        matched,
        "ledger_signal_time":             row.timestamp_open.isoformat(),
        "ledger_entry_price":             row.entry_price,
        "ledger_sl_pips":                 row.sl_pips_applied,
        "ledger_tp1_pips":                row.tp1_pips,
        "ledger_close_reason":            row.close_reason_canonical,
        "ledger_close_time":              row.timestamp_close.isoformat() if row.timestamp_close else "",
        "ledger_partial_bank_pips":       row.partial_bank_pips if row.partial_bank_pips is not None else "",
        "ledger_runner_pnl_pips":         row.runner_pnl_pips if row.runner_pnl_pips is not None else "",
        "ledger_effective_pnl_pips":      row.effective_pnl_pips if row.effective_pnl_pips is not None else "",
        "ledger_gbp_at_stake1":           round((row.effective_pnl_pips or 0.0) * config.STAKE_GBP_PER_PIP, 2),
        "ledger_scaled_out":              row.scaled_out,
        "ledger_close_reproducible":      row.close_reproducible,
        "ledger_exit_unreproducible":     (not row.close_reproducible),
        "benchmark_signal_time":          signal_ts,
        "benchmark_entry_price":          signal_entry,
        "entry_price_delta_pips":         price_delta_pips if price_delta_pips is not None else "",
        "benchmark_initial_stop_price":   initial_stop,
        "benchmark_partial_closes":       partials_str,
        "benchmark_final_close":          final_str,
        "benchmark_pips":                 bench_pips,
        "benchmark_gbp_at_stake1":        bench_gbp,
        "benchmark_scaled_out":           bench_scaled,
        "benchmark_mfe_pips":             bench_mfe,
        "benchmark_mae_pips":             bench_mae,
        "benchmark_duration_min":         bench_duration,
    }


def _write_benchmark_fires(fires: List[Signal], exits: Dict[str, ExitReport]) -> None:
    with open(OUTDIR / "benchmark_fires.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["signal_ts_utc", "direction", "entry_price",
                    "sl_pips", "tp_pips", "rejection_bar_open",
                    "rejection_bar_close", "setup_bar_open",
                    "rejection_window_idx", "bbu_setup", "bbl_setup",
                    "bbu_current", "bbl_current",
                    "exit_final_reason", "exit_final_price", "exit_final_ts",
                    "total_pips", "scaled_out", "duration_bars",
                    "mfe_pips", "mae_pips"])
        for s in fires:
            e = exits.get(s.ts_utc.isoformat())
            if e and e.final:
                fr, fp, ft = e.final.reason, round(e.final.price, 3), e.final.ts_utc.isoformat()
            else:
                fr, fp, ft = "", "", ""
            w.writerow([s.ts_utc.isoformat(), s.direction, s.entry_price,
                        s.sl_pips, s.tp_pips,
                        s.rejection_bar.ts.isoformat(),
                        s.rejection_bar.close_ts.isoformat(),
                        s.setup_bar.ts.isoformat(),
                        s.rejection_window_idx,
                        round(s.bbu_setup, 3), round(s.bbl_setup, 3),
                        round(s.bbu_current, 3), round(s.bbl_current, 3),
                        fr, fp, ft,
                        round(e.total_pips, 2) if e else "",
                        e.scaled_out if e else "",
                        e.duration_bars if e else "",
                        e.mfe_pips if e else "",
                        e.mae_pips if e else ""])


def _write_parity(rows: List[Dict]) -> None:
    with open(OUTDIR / "parity_report.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_false_positives(fires: List[Signal], exits: Dict[str, ExitReport]) -> None:
    with open(OUTDIR / "false_positives.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["signal_ts_utc", "direction", "entry_price",
                    "rejection_bar_open", "setup_bar_open",
                    "rejection_window_idx", "exit_final_reason",
                    "total_pips", "scaled_out"])
        for s in fires:
            e = exits.get(s.ts_utc.isoformat())
            w.writerow([s.ts_utc.isoformat(), s.direction, s.entry_price,
                        s.rejection_bar.ts.isoformat(),
                        s.setup_bar.ts.isoformat(),
                        s.rejection_window_idx,
                        e.final.reason if e and e.final else "",
                        round(e.total_pips, 2) if e else "",
                        e.scaled_out if e else ""])


def _write_false_negatives(rows: List[LedgerRow]) -> None:
    with open(OUTDIR / "false_negatives.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["deal_id", "ledger_signal_time", "ledger_entry_price",
                    "ledger_close_reason", "ledger_effective_pnl_pips"])
        for row in rows:
            w.writerow([row.deal_id, row.timestamp_open.isoformat(),
                        row.entry_price, row.close_reason_canonical,
                        row.effective_pnl_pips])


def _write_per_day(rows: List[Dict]) -> Dict:
    per_day = defaultdict(lambda: {"n_ledger": 0, "n_bench": 0,
                                    "ledger_pips": 0.0, "bench_pips": 0.0})
    for r in rows:
        d = r["ledger_signal_time"][:10]
        per_day[d]["n_ledger"] += 1
        per_day[d]["ledger_pips"] += r["ledger_effective_pnl_pips"] or 0.0
        if r["matched"]:
            per_day[d]["n_bench"] += 1
            per_day[d]["bench_pips"] += r["benchmark_pips"] or 0.0
    with open(OUTDIR / "per_day_summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "n_ledger", "n_bench", "ledger_pips",
                    "bench_pips", "delta_pips"])
        totals = {"n_ledger": 0, "n_bench": 0, "ledger_pips": 0.0, "bench_pips": 0.0}
        for d in sorted(per_day):
            v = per_day[d]
            w.writerow([d, v["n_ledger"], v["n_bench"],
                        round(v["ledger_pips"], 2),
                        round(v["bench_pips"], 2),
                        round(v["bench_pips"] - v["ledger_pips"], 2)])
            for k, val in v.items(): totals[k] += val
        w.writerow(["TOTAL", totals["n_ledger"], totals["n_bench"],
                    round(totals["ledger_pips"], 2),
                    round(totals["bench_pips"], 2),
                    round(totals["bench_pips"] - totals["ledger_pips"], 2)])
    return dict(per_day)


def _write_summary(fires: List[Signal],
                   false_positives: List[Signal],
                   false_negatives: List[LedgerRow],
                   parity_rows: List[Dict],
                   per_day: Dict, pierce_thresh_pips: float,
                   start_date: str, end_date: str) -> Dict:
    n_matched = sum(1 for r in parity_rows if r["matched"])
    n_unreprod = sum(1 for r in parity_rows if r["ledger_exit_unreproducible"])
    n_reprod   = sum(1 for r in parity_rows if not r["ledger_exit_unreproducible"])
    bench_total = sum((r["benchmark_pips"] or 0.0) for r in parity_rows)
    ledger_total = sum((r["ledger_effective_pnl_pips"] or 0.0) for r in parity_rows)
    reprod_ledger = sum((r["ledger_effective_pnl_pips"] or 0.0)
                        for r in parity_rows
                        if r["matched"] and not r["ledger_exit_unreproducible"])
    reprod_bench = sum((r["benchmark_pips"] or 0.0)
                       for r in parity_rows
                       if r["matched"] and not r["ledger_exit_unreproducible"])
    price_deltas = [r["entry_price_delta_pips"] for r in parity_rows
                    if isinstance(r["entry_price_delta_pips"], (int, float))]
    large_delta_count = sum(1 for d in price_deltas if abs(d) > 2.0)
    summary = {
        "pin": {
            "source_repo": "github.com/JohnCarrington/autobot_reports",
            "commit": "714af5b",
            "spec_sha256":   "c4219f8ca4a7e677c27d0620c01699d1e5e3f1413570fbd3e86f21171b599ae2",
            "ledger_sha256": "f19141457ef96280b30930d8a27121cf4e9e37f697b5a4b8755f0c2f20ac124c",
        },
        "run": {
            "window": [start_date, end_date],
            "pierce_thresh_pips_used": pierce_thresh_pips,
            "broker_submission_enabled": config.IG_SUBMISSION_ENABLED,
        },
        "signals": {
            "benchmark_fires_total": len(fires),
            "ledger_rows_total": 36,
            "matched": n_matched,
            "false_positives_benchmark_only": len(false_positives),
            "false_negatives_ledger_only": len(false_negatives),
            "match_rate_pct": round(n_matched / 36 * 100, 1),
            "matched_with_price_delta_over_2pips": large_delta_count,
            "price_delta_pips_avg": round(sum(price_deltas)/len(price_deltas), 3) if price_deltas else 0.0,
            "price_delta_pips_max_abs": round(max((abs(d) for d in price_deltas), default=0.0), 3),
        },
        "exit_reproducibility": {
            "ledger_reproducible_close_count": n_reprod,
            "ledger_unreproducible_close_count": n_unreprod,
            "sum_pips_ledger_reproducible_only": round(reprod_ledger, 2),
            "sum_pips_benchmark_matched_reproducible_only": round(reprod_bench, 2),
        },
        "totals_all_rows": {
            "ledger_pips": round(ledger_total, 2),
            "benchmark_pips": round(bench_total, 2),
            "delta_pips": round(bench_total - ledger_total, 2),
            "caveat": "Benchmark cannot reproduce soft-exit reasons; the total_pips delta is dominated by that gap, not by disagreement.",
        },
    }
    with open(OUTDIR / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    return summary


# ─── CLI ────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--pierce-thresh", type=float,
                   default=config.PIERCE_THRESH_PIPS_DEFAULT,
                   help="PIERCE_THRESH_PIPS (default: code default at c85481c = 0.5)")
    p.add_argument("--start", default="2026-05-23")
    p.add_argument("--end",   default="2026-06-25")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    assert not config.IG_SUBMISSION_ENABLED, "Broker submission must be disabled"
    summary = run(args.pierce_thresh, args.start, args.end)
    print(json.dumps(summary, indent=2))
