#!/usr/bin/env python3
"""Full-corpus offline replay (2024-01-01 -> 2026-09-30).

Emits:
    docs/replay_results/full_corpus_summary.md
    docs/replay_results/by_year_fast_grind_buy_sell.csv
    docs/replay_results/by_exit_reason.csv
    docs/replay_results/trades.jsonl
    docs/replay_results/monthly_pips.csv

Run:
    python3 scripts/run_full_corpus_replay.py \
        --roots /opt/tradingbot/data/candles_ext /opt/tradingbot/data/candles \
        --start 2024-01-01 --end 2026-09-30 \
        --out docs/replay_results
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median

from trend_runner.replay import run_replay


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--roots", nargs="+", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--stake", type=float, default=2.0)
    p.add_argument("--min-distance-pips", type=float, default=4.0)
    args = p.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_replay(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        roots=args.roots,
        stake_gbp_per_pip=args.stake,
        min_broker_distance_pips=args.min_distance_pips,
    )
    trades = result["trades"]

    # trades.jsonl
    with (out_dir / "trades.jsonl").open("w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")

    # By year / mode / direction
    by_year_mode_dir: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for t in trades:
        yr = t["entry_time"][:4]
        by_year_mode_dir[(yr, t["regime"], t["direction"])].append(t)
    with (out_dir / "by_year_fast_grind_buy_sell.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "mode", "direction", "trades", "net_pips", "wins", "losses",
                    "avg_pips", "median_pips", "worst_pips", "best_pips"])
        for (yr, mode, direction), rows in sorted(by_year_mode_dir.items()):
            pips = [r["net_pips"] for r in rows if r["net_pips"] is not None]
            if not pips:
                continue
            w.writerow([yr, mode, direction, len(pips), round(sum(pips), 1),
                        sum(1 for x in pips if x > 0),
                        sum(1 for x in pips if x <= 0),
                        round(sum(pips) / len(pips), 2), round(median(pips), 2),
                        round(min(pips), 1), round(max(pips), 1)])

    # By exit reason
    by_exit: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        if t["net_pips"] is not None:
            by_exit[t["exit_reason"]].append(t["net_pips"])
    with (out_dir / "by_exit_reason.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["exit_reason", "trades", "net_pips", "avg_pips", "median_pips"])
        for reason, pips in sorted(by_exit.items()):
            w.writerow([reason, len(pips), round(sum(pips), 1),
                        round(sum(pips) / len(pips), 2), round(median(pips), 2)])

    # Monthly pips
    monthly: dict[str, float] = defaultdict(float)
    monthly_ct: dict[str, int] = defaultdict(int)
    for t in trades:
        if t["net_pips"] is None:
            continue
        m = t["entry_time"][:7]
        monthly[m] += t["net_pips"]
        monthly_ct[m] += 1
    with (out_dir / "monthly_pips.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "trades", "net_pips"])
        for m in sorted(monthly):
            w.writerow([m, monthly_ct[m], round(monthly[m], 1)])

    # Summary
    def losing_streak(rows):
        streak = worst = 0
        for r in rows:
            if r["net_pips"] is not None and r["net_pips"] <= 0:
                streak += 1
                worst = max(worst, streak)
            else:
                streak = 0
        return worst

    def trade_drawdown(rows):
        eq = 0.0
        peak = 0.0
        dd = 0.0
        for r in rows:
            if r["net_pips"] is None:
                continue
            eq += r["net_pips"]
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        return round(dd, 1)

    closed = [t for t in trades if t["net_pips"] is not None]
    net = sum(t["net_pips"] for t in closed)
    wins = [t for t in closed if t["net_pips"] > 0]
    losses = [t for t in closed if t["net_pips"] <= 0]
    win_sum = sum(t["net_pips"] for t in wins)
    loss_sum = -sum(t["net_pips"] for t in losses)
    pf = round(win_sum / loss_sum, 3) if loss_sum > 0 else None

    trading_days_with_bars = set()
    for t in trades:
        trading_days_with_bars.add(t["entry_time"][:10])
    # Approximate eligible-day count from monthly buckets
    days_ge_30 = 0
    per_day: dict[str, float] = defaultdict(float)
    for t in closed:
        per_day[t["entry_time"][:10]] += t["net_pips"]
    days_ge_30 = sum(1 for d, p in per_day.items() if p >= 30.0)

    summary = {
        "meta": result["meta"],
        "trades": len(closed),
        "net_pips": round(net, 1),
        "win_rate": round(len(wins) / len(closed), 3) if closed else 0.0,
        "avg_pips": round(net / len(closed), 2) if closed else None,
        "median_pips": round(median([t["net_pips"] for t in closed]), 2) if closed else None,
        "profit_factor": pf,
        "losing_streak_max": losing_streak(closed),
        "trade_drawdown_pips": trade_drawdown(closed),
        "days_positive_ge_30p": days_ge_30,
        "trade_days": len(per_day),
        "by_exit_reason_count": {r: len(v) for r, v in by_exit.items()},
        "by_exit_reason_pips": {r: round(sum(v), 1) for r, v in by_exit.items()},
    }
    (out_dir / "full_corpus_summary.md").write_text(_render_summary(summary), encoding="utf-8")
    (out_dir / "full_corpus_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def _render_summary(s: dict) -> str:
    lines = [
        "# Trend Runner full-corpus replay",
        "",
        f"* Corpus: {s['meta']['start']} → {s['meta']['end']}  ({s['meta']['bars_replayed']} M5 bars)",
        f"* Symbol: {s['meta']['symbol']}",
        "",
        "## Overall",
        "",
        f"* Trades: **{s['trades']}**",
        f"* Trade days: {s['trade_days']}",
        f"* Net pips: **{s['net_pips']:+.1f}**",
        f"* Win rate: {s['win_rate']:.1%}",
        f"* Avg pips / trade: {s['avg_pips']}",
        f"* Median pips / trade: {s['median_pips']}",
        f"* Profit factor: {s['profit_factor']}",
        f"* Max losing streak (trades): {s['losing_streak_max']}",
        f"* Trade-level drawdown (pips): {s['trade_drawdown_pips']}",
        f"* Days ≥ +30p net: {s['days_positive_ge_30p']}",
        "",
        "## By exit reason",
        "",
        "| Reason | Count | Net pips |",
        "|---|---:|---:|",
    ]
    for reason in sorted(set(s["by_exit_reason_count"]) | set(s["by_exit_reason_pips"])):
        c = s["by_exit_reason_count"].get(reason, 0)
        p = s["by_exit_reason_pips"].get(reason, 0.0)
        lines.append(f"| {reason} | {c} | {p:+.1f} |")
    lines += [
        "",
        "Segmentation by year × FAST/GRIND × BUY/SELL is in `by_year_fast_grind_buy_sell.csv`.",
        "Monthly net pips in `monthly_pips.csv`.",
        "",
        "## Disclosures",
        "",
        "* Mid-only replay using the M5 candle archive; realistic broker execution",
        "  costs are NOT deducted. The observation runner and future broker path",
        "  will incur spread cost.",
        "* Stop and target ambiguity within a single bar is resolved in favour of the",
        "  protective stop (see `trend_runner/exit.py`). For finer resolution, extend",
        "  the exit engine to read the tick archive where available.",
        "* The 2024-2026 corpus has been inspected previously; treat these results as",
        "  exploratory. No parameter sweep was performed; thresholds are frozen in",
        "  `trend_runner/regime.py` and `trend_runner/entry.py`.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
