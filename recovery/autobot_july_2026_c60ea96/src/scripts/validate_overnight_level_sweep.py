#!/usr/bin/env python3
"""
validate_overnight_level_sweep.py — backtest GBPUSD_OVERNIGHT_LEVEL_SWEEP.

For each weekday in the window:
  1. Compute overnight session (22:00 prev-day to 06:45 today).
  2. Identify swing-low levels (up to 5, deduplicated to >=8p apart).
  3. Walk 06:45-10:00 UTC bars; per-level sweep + reversal detection.
  4. On the first qualifying entry: simulate forward to SL/TP/EOD.
  5. Same-bar SL+TP collision resolved as SL (conservative).

LONG-only. SHORT path is bypassed by construction (no SHORT detector,
direction hardcoded "BUY"). A module-load assert refuses to run unless
the strategy module is built with ENABLE_LONG=True and
ENABLE_SHORT=False.

Usage:
    python3 scripts/validate_overnight_level_sweep.py --start 2026-03-30 --end 2026-04-25
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

# Make the strategy module importable when run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbpusd_overnight_level_sweep import (  # noqa: E402
    Bar,
    ENABLE_LONG, ENABLE_SHORT,
    PIERCE_PIPS, MIN_BODY_RATIO, MIN_BAR_RANGE_PIPS,
    MAX_SL_PIPS, MIN_TP_PIPS, CONFIRM_TIMEOUT_MIN,
    LEVEL_MIN_SEPARATION_PIPS, MAX_LEVELS, SL_BUFFER_PIPS,
    WINDOW_START, WINDOW_END,
    PIP_SIZE,
    DEFAULT_CANDLE_ARCHIVE,
    compute_overnight_session,
    _read_csv_bars,
)

# Hard assertion — this validator simulates the LONG-only build. SHORT
# is impossible by construction in `simulate_day`: no SHORT detector,
# `direction` only ever assigned "BUY". This assert rules out running
# against a strategy module built with SHORT enabled.
assert ENABLE_LONG, "validator requires ENABLE_LONG"
assert not ENABLE_SHORT, "validator simulates LONG-only; refuse to run with ENABLE_SHORT"


@dataclass
class DayResult:
    date: str
    weekday: str
    levels: List[float] = field(default_factory=list)
    overnight_high: Optional[float] = None
    status: str = ""              # SKIPPED | NO_SWEEP | SWEPT_NO_CONFIRM | TRADED
    skip_reason: str = ""
    sweep_events: List[str] = field(default_factory=list)
    direction: str = ""           # always "BUY" or ""
    swept_level: Optional[float] = None
    sweep_extreme: Optional[float] = None
    sweep_time: str = ""
    entry_time: str = ""
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    sl_pips: Optional[float] = None
    tp_pips_target: Optional[float] = None
    exit_time: str = ""
    exit_price: Optional[float] = None
    exit_reason: str = ""         # SL | TP | TIMEOUT_EOD | NO_DATA
    pnl_pips: Optional[float] = None
    notes: str = ""

    # Funnel diagnostics.
    any_pierce: bool = False              # any bar < any level (any size)
    any_sweep: bool = False               # any level pierced by >= PIERCE_PIPS
    had_confirm_candidate: bool = False   # post-sweep, bullish, closed back inside
    rejected_sl: bool = False             # candidate failed SL <= MAX_SL_PIPS
    rejected_tp: bool = False             # candidate failed TP >= MIN_TP_PIPS


def daterange(start: date, end_inclusive: date):
    cur = start
    while cur <= end_inclusive:
        yield cur
        cur += timedelta(days=1)


def simulate_day(target_date: date, base: Path) -> DayResult:
    res = DayResult(date=target_date.isoformat(), weekday=target_date.strftime("%a"))
    if target_date.weekday() >= 5:
        res.status = "SKIPPED"
        res.skip_reason = "weekend"
        return res

    today_path = base / f"{target_date.isoformat()}.csv"
    if not today_path.exists():
        res.status = "SKIPPED"
        res.skip_reason = "no_candle_file"
        return res

    overnight_bars, levels, oh = compute_overnight_session(target_date, base)
    if not overnight_bars or oh is None or not levels:
        res.status = "SKIPPED"
        res.skip_reason = "no_overnight_levels"
        return res

    res.levels = levels
    res.overnight_high = oh

    today_bars = _read_csv_bars(today_path)
    win_start = datetime.combine(target_date, WINDOW_START, tzinfo=timezone.utc)
    win_end = datetime.combine(target_date, WINDOW_END, tzinfo=timezone.utc)
    window_bars = [b for b in today_bars if win_start <= b.timestamp < win_end]

    # Funnel: any pierce of any level (any size).
    res.any_pierce = any(
        any(b.low < L for L in levels) for b in window_bars
    )

    @dataclass
    class LS:
        price: float
        phase: str = "WAITING"
        sweep_extreme: Optional[float] = None
        sweep_time: Optional[datetime] = None

    level_states = [LS(price=p) for p in levels]
    direction = ""
    entry_bar: Optional[Bar] = None
    swept_level: Optional[LS] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    sl_pips: Optional[float] = None

    for b in window_bars:
        bar_close = b.timestamp + timedelta(minutes=5)

        # Sweep detection.
        for ls in level_states:
            if ls.phase != "WAITING":
                continue
            if b.low <= ls.price - PIERCE_PIPS * PIP_SIZE:
                ls.phase = "SWEPT"
                ls.sweep_extreme = b.low
                ls.sweep_time = b.timestamp
                res.any_sweep = True
                res.sweep_events.append(
                    f"{b.timestamp.strftime('%H:%M')} L={ls.price:.1f} "
                    f"low={b.low:.1f} (-{ls.price - b.low:.1f}p)"
                )

        # Confirmation. Iterate by sweep_time ascending; tie-break on
        # ascending price (deepest sweep wins).
        swept = [ls for ls in level_states if ls.phase == "SWEPT"]
        swept.sort(key=lambda ls: (ls.sweep_time or bar_close, ls.price))
        for ls in swept:
            if ls.sweep_time is not None and (bar_close - ls.sweep_time) > timedelta(minutes=CONFIRM_TIMEOUT_MIN):
                ls.phase = "DONE_TIMEOUT"
                continue

            cond_after = ls.sweep_time is not None and bar_close > ls.sweep_time
            cond_inside = b.close > ls.price
            cond_dir = b.close > b.open
            if not (cond_after and cond_inside and cond_dir):
                continue

            rng_b = b.high - b.low
            if rng_b <= 0:
                continue
            res.had_confirm_candidate = True

            body = abs(b.close - b.open)
            if (body / rng_b) < MIN_BODY_RATIO:
                continue
            if rng_b < MIN_BAR_RANGE_PIPS * PIP_SIZE:
                continue

            sl_p = ls.sweep_extreme - SL_BUFFER_PIPS * PIP_SIZE
            sl_d = (b.close - sl_p) / PIP_SIZE
            if sl_d <= 0:
                continue
            if sl_d > MAX_SL_PIPS:
                res.rejected_sl = True
                continue

            tp_p: Optional[float] = None
            for lvl in levels:
                if lvl > b.close:
                    tp_p = lvl
                    break
            if tp_p is None:
                tp_p = oh
            if tp_p is None:
                continue
            tp_d = (tp_p - b.close) / PIP_SIZE
            if tp_d < MIN_TP_PIPS:
                res.rejected_tp = True
                continue

            direction = "BUY"
            entry_bar = b
            swept_level = ls
            sl_price = sl_p
            tp_price = tp_p
            sl_pips = sl_d
            break

        if direction:
            break

    if direction == "":
        if not res.any_sweep:
            res.status = "NO_SWEEP"
        else:
            res.status = "SWEPT_NO_CONFIRM"
            reasons = []
            if res.rejected_sl:
                reasons.append("SL>25p")
            if res.rejected_tp:
                reasons.append("TP<8p")
            if reasons:
                res.notes = "rejected: " + ", ".join(reasons)
        return res

    res.status = "TRADED"
    res.direction = direction
    res.swept_level = swept_level.price
    res.sweep_extreme = swept_level.sweep_extreme
    res.sweep_time = swept_level.sweep_time.strftime("%H:%M")
    res.entry_time = entry_bar.timestamp.strftime("%H:%M")
    res.entry_price = entry_bar.close
    res.sl_price = sl_price
    res.tp_price = tp_price
    res.sl_pips = round(sl_pips, 2)
    res.tp_pips_target = round((tp_price - entry_bar.close) / PIP_SIZE, 2)

    # Forward walk for exit (today after entry, then next day).
    after_entry = [b for b in today_bars if b.timestamp > entry_bar.timestamp]
    next_path = base / f"{(target_date + timedelta(days=1)).isoformat()}.csv"
    next_bars = _read_csv_bars(next_path) if next_path.exists() else []
    forward = after_entry + next_bars

    exit_reason = ""
    exit_price: Optional[float] = None
    exit_time_dt: Optional[datetime] = None
    for fb in forward:
        sl_hit = fb.low <= sl_price
        tp_hit = fb.high >= tp_price
        if sl_hit and tp_hit:
            # Conservative: assume SL on tie.
            exit_reason = "SL"
            exit_price = sl_price
            exit_time_dt = fb.timestamp
            break
        if sl_hit:
            exit_reason = "SL"
            exit_price = sl_price
            exit_time_dt = fb.timestamp
            break
        if tp_hit:
            exit_reason = "TP"
            exit_price = tp_price
            exit_time_dt = fb.timestamp
            break

    if exit_reason == "":
        if forward:
            exit_price = forward[-1].close
            exit_time_dt = forward[-1].timestamp
            exit_reason = "TIMEOUT_EOD"
        else:
            exit_price = entry_bar.close
            exit_time_dt = entry_bar.timestamp
            exit_reason = "NO_DATA"

    res.exit_time = exit_time_dt.strftime("%Y-%m-%d %H:%M") if exit_time_dt else ""
    res.exit_price = exit_price
    res.exit_reason = exit_reason
    res.pnl_pips = round((exit_price - entry_bar.close) / PIP_SIZE, 2)
    return res


def print_ledger(results: List[DayResult]) -> None:
    print(
        f"GBPUSD_OVERNIGHT_LEVEL_SWEEP validation (LONG-only) — "
        f"{len(results)} weekdays"
    )
    print(
        "SHORT path is bypassed by construction (no SHORT detector; "
        "direction hardcoded BUY). SHORT entries are impossible.\n"
    )

    # Per-day detail with levels and sweep events.
    print("Per-day detail:")
    for r in results:
        if r.status == "SKIPPED":
            print(f"  {r.date} {r.weekday}: SKIPPED ({r.skip_reason})")
            continue
        lvls = ", ".join(f"{p:.1f}" for p in r.levels)
        print(
            f"  {r.date} {r.weekday}: {len(r.levels)} levels=[{lvls}] "
            f"oh={r.overnight_high:.1f}"
        )
        for e in r.sweep_events:
            print(f"      sweep: {e}")
        if r.status == "TRADED":
            print(
                f"      ENTRY BUY @ {r.entry_price:.1f} swept_lvl={r.swept_level:.1f} | "
                f"SL={r.sl_pips:.1f}p TP={r.tp_pips_target:.1f}p (target {r.tp_price:.1f}) | "
                f"exit {r.exit_time} {r.exit_reason} {r.pnl_pips:+.1f}p"
            )
        elif r.status == "SWEPT_NO_CONFIRM" and r.notes:
            print(f"      no entry: {r.notes}")
    print()

    # Compact ledger.
    hdr = (
        f"{'Date':<11} {'Wd':<4} {'#L':>3} {'OH':>8}  "
        f"{'Status':<18} {'Lvl':>7} {'Sweep':<6} {'Entry':<6} "
        f"{'EntryP':>8} {'SL':>6} {'TPtgt':>6} {'Exit':<13} {'Reason':<10} "
        f"{'PnL':>7}  Notes"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        oh = f"{r.overnight_high:.1f}" if r.overnight_high is not None else "-"
        ep = f"{r.entry_price:.1f}" if r.entry_price is not None else "-"
        slp = f"{r.sl_pips:.1f}" if r.sl_pips is not None else "-"
        tpt = f"{r.tp_pips_target:.1f}" if r.tp_pips_target is not None else "-"
        pnl = f"{r.pnl_pips:+.1f}" if r.pnl_pips is not None else "-"
        lvl = f"{r.swept_level:.1f}" if r.swept_level is not None else "-"
        notes = r.skip_reason or r.notes or ""
        print(
            f"{r.date:<11} {r.weekday:<4} {len(r.levels):>3} {oh:>8}  "
            f"{r.status:<18} {lvl:>7} {(r.sweep_time or '-'):<6} "
            f"{(r.entry_time or '-'):<6} {ep:>8} {slp:>6} {tpt:>6} "
            f"{(r.exit_time or '-'):<13} {(r.exit_reason or '-'):<10} "
            f"{pnl:>7}  {notes}"
        )
    print("-" * len(hdr))

    # Aggregate.
    n_total = len(results)
    armed = [r for r in results if r.levels]
    n_skipped = sum(1 for r in results if r.status == "SKIPPED")
    trades = [r for r in results if r.status == "TRADED" and r.pnl_pips is not None]
    wins = [r for r in trades if r.pnl_pips > 0]
    losses = [r for r in trades if r.pnl_pips <= 0]
    net = sum(r.pnl_pips for r in trades)
    wr = (len(wins) / len(trades) * 100) if trades else 0.0
    avg_w = (sum(r.pnl_pips for r in wins) / len(wins)) if wins else 0.0
    avg_l = (sum(r.pnl_pips for r in losses) / len(losses)) if losses else 0.0
    median_w = 0.0
    if wins:
        sw = sorted(r.pnl_pips for r in wins)
        median_w = (
            sw[len(sw) // 2]
            if len(sw) % 2 == 1
            else (sw[len(sw) // 2 - 1] + sw[len(sw) // 2]) / 2
        )

    print()
    print("Aggregate:")
    print(f"  Days inspected:                 {n_total}")
    print(f"  Days armed (>=1 level):         {len(armed)}")
    print(f"  Days skipped:                   {n_skipped}")
    print(f"  Days TRADED:                    {len(trades)}")
    print(f"  Wins / losses:                  {len(wins)} / {len(losses)}")
    print(f"  Net P&L (pips):                 {net:+.2f}")
    print(f"  Win rate:                       {wr:.1f}%")
    print(f"  Average winner:                 {avg_w:+.2f}p")
    print(f"  Average loser:                  {avg_l:+.2f}p")
    print(f"  Median winner:                  {median_w:+.2f}p")

    # Funnel.
    n_pierce = sum(1 for r in armed if r.any_pierce)
    n_sweep = sum(1 for r in armed if r.any_sweep)
    n_confirm = sum(1 for r in armed if r.had_confirm_candidate)
    n_rej_sl = sum(1 for r in armed if r.rejected_sl)
    n_rej_tp = sum(1 for r in armed if r.rejected_tp)

    print()
    print("Funnel (armed days only):")
    print(f"  Days with any low pierce:                {n_pierce}")
    print(f"  Days with sweep (>= {PIERCE_PIPS:.1f}p):              {n_sweep}")
    print(f"  Days with confirm candidate:             {n_confirm}")
    print(f"  Days with SL > {MAX_SL_PIPS:.0f}p rejection:           {n_rej_sl}")
    print(f"  Days with TP < {MIN_TP_PIPS:.0f}p rejection:            {n_rej_tp}")
    print(f"  Days TRADED:                             {len(trades)}")

    pass_trades = len(trades) >= 5
    pass_wr = wr >= 50
    pass_net = net > 20
    pass_avgw = avg_w >= 12
    decision = "SHIP" if all([pass_trades, pass_wr, pass_net, pass_avgw]) else "HOLD"
    print()
    print("Pass thresholds: trades>=5, WR>=50%, net>+20p, avgWin>=12p")
    print(
        f"  trades>=5: {pass_trades}  WR>=50%: {pass_wr}  "
        f"net>+20p: {pass_net}  avgW>=12p: {pass_avgw}"
    )
    print(f"  Decision: {decision}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--candle-dir", default=str(DEFAULT_CANDLE_ARCHIVE))
    args = p.parse_args()
    base = Path(args.candle_dir)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    results: List[DayResult] = []
    for d in daterange(start, end):
        if d.weekday() >= 5:
            continue
        results.append(simulate_day(d, base))
    print_ledger(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
