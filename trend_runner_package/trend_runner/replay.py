"""Offline replay driver over the local M5 candle archive.

Feeds bars in strict chronological order. For each M5 close we:
  1. Advance strategy indicators/structure/regime.
  2. Let the exit engine consider closing the live position.
  3. Let the entry engine identify a candidate.
  4. On the *next* bar's open (executable quote), attempt to fill the
     candidate; that fill becomes the entry price.

Pivots are recomputed daily from the previous *completed* FX day
(22:00 UTC -> 22:00 UTC). Days with insufficient coverage produce
``None`` and force any entry attempt on that day to be skipped
(target-behind-entry / pivots-unavailable are separate reject paths).
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .candle_source import CandleArchive, M5Bar
from .ledger import Ledger, Namespace
from .pips import PIP_UNITS, price_to_pips
from .pivots import PivotSet, aggregate_fx_day, compute_pivots, pivot_day_bounds
from .strategy import TrendStrategy, TradeRecord
from .time_utils import UTC, in_entry_window


class ArchivePivotCache:
    """Compute and cache prior-day pivots on demand from the archive."""

    def __init__(self, archive: CandleArchive):
        self.archive = archive
        self.cache: dict[tuple[datetime, datetime], Optional[PivotSet]] = {}

    def get(self, bar_time_utc: datetime) -> Optional[PivotSet]:
        day_start, day_end = pivot_day_bounds(bar_time_utc)
        key = (day_start, day_end)
        if key in self.cache:
            return self.cache[key]
        # Load bars covering the FX day from the archive.
        d0 = day_start.date()
        d1 = day_end.date()
        bars = list(self.archive.iter_m5_bars(d0, d1))
        rows = [(b.ts, b.o, b.h, b.l, b.c) for b in bars if day_start <= b.ts < day_end]
        pivot = None
        agg = aggregate_fx_day(iter(rows), day_start, day_end)
        if agg is not None:
            pivot = compute_pivots(agg)
        self.cache[key] = pivot
        return pivot


def run_replay(start: date, end: date, roots: List[str], symbol: str = "GBPUSD",
               ledger_path: Optional[str] = None,
               min_broker_distance_pips: float = 4.0,
               stake_gbp_per_pip: float = 2.0,
               trace_days: Optional[List[str]] = None,
               ) -> dict:
    archive = CandleArchive(roots, symbol=symbol)
    pivots = ArchivePivotCache(archive)
    ledger = Ledger(ledger_path) if ledger_path else None
    strategy = TrendStrategy(
        pivot_getter=pivots.get,
        ledger=ledger,
        space=Namespace.SIM,
        stake_gbp_per_pip=stake_gbp_per_pip,
        min_broker_distance_pips=min_broker_distance_pips,
    )

    # Peek-ahead: we need the NEXT bar to fill an entry. Iterate with a 1-lookahead.
    bars_iter = archive.iter_m5_bars(start, end)
    bars: List[M5Bar] = list(bars_iter)
    daily_trace: dict[str, list] = defaultdict(list)
    for i, bar in enumerate(bars):
        decision = strategy.on_m5_close(bar)
        trace_row = None
        if trace_days is not None and bar.ts.date().isoformat() in trace_days:
            trace_row = {
                "ts": bar.ts.isoformat(),
                "regime": decision.regime,
                "direction": decision.direction,
                "pause_hint": decision.pause_hint,
                "close": bar.c,
                "high": bar.h,
                "low": bar.l,
            }
        # Attempt to fill any pending entry at the next bar's open.
        if i + 1 < len(bars):
            filled = strategy.on_next_bar_open(bars[i + 1])
            if trace_row is not None and filled is not None:
                trace_row["entry_attempt"] = {
                    "accepted": filled.accepted,
                    "reject_reason": filled.reject_reason,
                    "entry_price": filled.entry_price,
                    "stop_price": filled.stop_price,
                    "risk_pips": filled.risk_pips,
                    "late_entry_pips": filled.late_entry_pips,
                    "reason": filled.candidate.reason,
                    "mode": filled.candidate.mode.value,
                    "direction": filled.candidate.direction.value,
                }
        if trace_row is not None:
            if decision.exit is not None:
                trace_row["exit"] = {
                    "reason": decision.exit.reason.value,
                    "exit_price": decision.exit.exit_price,
                    "detail": decision.exit.detail,
                }
            daily_trace[bar.ts.date().isoformat()].append(trace_row)

    return {
        "trades": [_trade_to_dict(t) for t in strategy.trades],
        "trace": {k: v for k, v in daily_trace.items()},
        "meta": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "bars_replayed": len(bars),
            "symbol": symbol,
        },
    }


def _trade_to_dict(t: TradeRecord) -> dict:
    return {
        "trade_id": t.trade_id,
        "direction": t.direction.value if hasattr(t.direction, "value") else t.direction,
        "entry_time": t.entry_time.isoformat(),
        "entry_price": t.entry_price,
        "stop_price": t.stop_price,
        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "exit_price": t.exit_price,
        "exit_reason": t.exit_reason,
        "net_pips": t.net_pips,
        "regime": t.regime,
        "pivots": t.pivots,
        "stake_gbp_per_pip": t.stake_gbp_per_pip,
    }


def summarise(trades: List[dict]) -> dict:
    if not trades:
        return {"trades": 0}
    closed = [t for t in trades if t.get("net_pips") is not None]
    net = sum(t["net_pips"] for t in closed)
    wins = [t for t in closed if t["net_pips"] > 0]
    losses = [t for t in closed if t["net_pips"] <= 0]
    win_sum = sum(t["net_pips"] for t in wins)
    loss_sum = -sum(t["net_pips"] for t in losses)
    pf = win_sum / loss_sum if loss_sum > 0 else None
    days = {t["entry_time"][:10] for t in closed}
    days_ge_30 = sum(1 for d in days
                     if sum(t["net_pips"] for t in closed if t["entry_time"].startswith(d)) >= 30.0)
    by_exit: dict[str, int] = defaultdict(int)
    for t in closed:
        by_exit[t["exit_reason"] or "UNKNOWN"] += 1
    by_dir_mode: dict[str, int] = defaultdict(int)
    for t in closed:
        by_dir_mode[f"{t['regime']}_{t['direction']}"] += 1
    return {
        "trades": len(closed),
        "net_pips": round(net, 1),
        "win_rate": round(len(wins) / len(closed), 3) if closed else 0.0,
        "avg_pips": round(net / len(closed), 2),
        "profit_factor": round(pf, 2) if pf else None,
        "days_positive_ge_30p": days_ge_30,
        "by_exit_reason": dict(by_exit),
        "by_regime_direction": dict(by_dir_mode),
        "trading_days": len(days),
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Trend Runner offline replay")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--roots", nargs="+", required=True, help="Candle archive roots")
    p.add_argument("--symbol", default="GBPUSD")
    p.add_argument("--ledger", default=None, help="Optional ledger JSONL output path")
    p.add_argument("--out", default=None, help="Optional JSON output path")
    p.add_argument("--trace-day", action="append", default=None, help="One or more YYYY-MM-DD to trace")
    p.add_argument("--stake", type=float, default=2.0)
    p.add_argument("--min-distance-pips", type=float, default=4.0)
    args = p.parse_args(argv)
    result = run_replay(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        roots=args.roots,
        symbol=args.symbol,
        ledger_path=args.ledger,
        stake_gbp_per_pip=args.stake,
        min_broker_distance_pips=args.min_distance_pips,
        trace_days=args.trace_day,
    )
    result["summary"] = summarise(result["trades"])
    body = json.dumps(result, indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            f.write(body)
    else:
        print(body)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
