#!/usr/bin/env python3
"""Emit per-reference-day traces required by section 7 of the brief.

For each named day we write:
    docs/reference_traces/<YYYY-MM-DD>.md   — narrative summary
    docs/reference_traces/<YYYY-MM-DD>.jsonl — one line per M5 bar

The trace records: bar time, regime, direction, close/high/low,
pause_hint, any entry candidate & fill attempt, any exit event.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from trend_runner.candle_source import CandleArchive
from trend_runner.ledger import Namespace
from trend_runner.replay import ArchivePivotCache
from trend_runner.strategy import TrendStrategy


UTC = timezone.utc


REFERENCE_DAYS = [
    ("2026-09-23", "Sustained DOWN trend on GBPUSD."),
    ("2026-09-25", "Slow UP staircase followed by loss of progress."),
    ("2026-09-30", "Strong UP breakout toward R3."),
    ("2026-09-24", "Chop day — expected no valid trend/no trade."),
    ("2026-09-29", "Range/chop with intraday reversal."),
]


def trace_day(day: date, roots: list[str], out_dir: Path) -> dict:
    archive = CandleArchive(roots)
    pivots = ArchivePivotCache(archive)
    strategy = TrendStrategy(pivot_getter=pivots.get,
                             space=Namespace.SIM,
                             min_broker_distance_pips=4.0)
    # Warm from the previous week so structure/indicator seeds mature.
    bars = list(archive.iter_m5_bars(day - timedelta(days=7), day))
    trace_rows = []
    fills = []
    exits = []
    for i, b in enumerate(bars):
        dec = strategy.on_m5_close(b)
        row = {
            "ts": b.ts.isoformat(),
            "regime": dec.regime,
            "direction": dec.direction,
            "pause_hint": dec.pause_hint,
            "o": b.o, "h": b.h, "l": b.l, "c": b.c,
        }
        if dec.exit is not None:
            row["exit"] = {
                "reason": dec.exit.reason.value,
                "exit_price": dec.exit.exit_price,
                "detail": dec.exit.detail,
            }
            exits.append({"ts": b.ts.isoformat(), **row["exit"]})
        if i + 1 < len(bars):
            filled = strategy.on_next_bar_open(bars[i + 1])
            if filled is not None:
                row["entry_attempt"] = {
                    "accepted": filled.accepted,
                    "reject_reason": filled.reject_reason,
                    "entry_price": filled.entry_price,
                    "stop_price": filled.stop_price,
                    "risk_pips": filled.risk_pips,
                    "late_entry_pips": filled.late_entry_pips,
                    "mode": filled.candidate.mode.value,
                    "direction": filled.candidate.direction.value,
                    "reason": filled.candidate.reason,
                }
                if filled.accepted:
                    fills.append({"ts": (filled.entry_time or b.ts).isoformat(),
                                  **row["entry_attempt"]})
        if b.ts.date() == day:
            trace_rows.append(row)

    trace_path = out_dir / f"{day.isoformat()}.jsonl"
    with trace_path.open("w") as f:
        for r in trace_rows:
            f.write(json.dumps(r) + "\n")

    trades = [t for t in strategy.trades if t.entry_time.date() == day]
    return {
        "day": day.isoformat(),
        "fills": fills,
        "exits": exits,
        "trades": [
            {
                "direction": t.direction.value,
                "regime": t.regime,
                "entry_time": t.entry_time.isoformat(),
                "entry_price": t.entry_price,
                "stop_price": t.stop_price,
                "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                "exit_price": t.exit_price,
                "exit_reason": t.exit_reason,
                "net_pips": t.net_pips,
            }
            for t in trades
        ],
        "regimes_at_london_hours": {
            r["ts"][:16]: r["regime"] for r in trace_rows
            if 6 <= datetime.fromisoformat(r["ts"]).hour <= 16
            and datetime.fromisoformat(r["ts"]).minute in (0, 30)
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--roots", nargs="+", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for iso, note in REFERENCE_DAYS:
        day = date.fromisoformat(iso)
        rec = trace_day(day, args.roots, out_dir)
        rec["note"] = note
        summary.append(rec)
        (out_dir / f"{iso}.md").write_text(_render_day(rec, note), encoding="utf-8")
    (out_dir / "index.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def _render_day(rec: dict, note: str) -> str:
    lines = [
        f"# {rec['day']} – reference trace",
        "",
        f"*Note:* {note}",
        "",
        f"* Fills accepted: {len([f for f in rec['fills'] if f['accepted']])}",
        f"* Fill attempts (accepted+rejected): {len(rec['fills'])}",
        f"* Exit events: {len(rec['exits'])}",
        f"* Trades on day: {len(rec['trades'])}",
        "",
        "## London hour regimes (half-hourly snapshot)",
        "",
        "| Time (UTC) | Regime |",
        "|---|---|",
    ]
    for ts, reg in sorted(rec["regimes_at_london_hours"].items()):
        lines.append(f"| {ts} | {reg} |")
    if rec["trades"]:
        lines += [
            "",
            "## Trades",
            "",
            "| Entry | Dir | Mode | Entry | Stop | Exit | Reason | Net pips |",
            "|---|---|---|---:|---:|---:|---|---:|",
        ]
        for t in rec["trades"]:
            lines.append(f"| {t['entry_time']} | {t['direction']} | {t['regime']} "
                         f"| {t['entry_price']:.2f} | {t['stop_price']:.2f} "
                         f"| {t['exit_price'] if t['exit_price'] else '-'} "
                         f"| {t['exit_reason']} | {t['net_pips']:+.1f} |")
    else:
        lines += [
            "",
            "## Trades",
            "",
            "*No trade taken on this day.* See per-bar trace `%s.jsonl` for reasons "
            "(regime, pause_hint, entry_attempt reject reasons)." % rec["day"],
        ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
