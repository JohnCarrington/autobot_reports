#!/usr/bin/env python3
"""
validate_ny_continuation_long.py — backtest GBPUSD_NY_CONTINUATION_L over
a window of weekdays.

For each weekday:
  1. Read 5m bars from data/candles/GBPUSD/<date>.csv.
  2. Build London session (06:45-12:25 UTC) and classify.
  3. If directional up: walk NY bars (12:30-15:30 UTC) through the
     state machine.
  4. If entered: walk forward to SL or TP (today + next day for late
     entries). Same-bar SL+TP collision = SL.
  5. Record per-day outcome.

Per-day ledger covers every weekday — directional or not, pullback or
not, traded or not — so the funnel is reconstructable from the table.

Usage:
    python3 scripts/validate_ny_continuation_long.py --start 2026-03-30 --end 2026-04-25
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbpusd_ny_continuation_long import (  # noqa: E402
    Bar,
    LondonClassification,
    PIP_SIZE,
    LONDON_START, LONDON_END,
    WIN_START, WIN_END,
    LONDON_MIN_RANGE_PIPS,
    LONDON_DIRECTIONAL_FRAC,
    PULLBACK_FRAC,
    RECOVERY_PIPS,
    MIN_BODY_RATIO,
    MIN_BAR_RANGE_PIPS,
    MAX_SL_PIPS,
    TP_EXTENSION_FRAC,
    PULLBACK_TIMEOUT_UTC,
    CONFIRMATION_TIMEOUT_MIN,
    SL_BUFFER_PIPS,
    DEFAULT_CANDLE_ARCHIVE,
    classify_london_session,
    load_london_session_bars,
    _read_csv_bars,
)


@dataclass
class DayResult:
    date: str
    weekday: str
    london_class: str = ""        # DIRECTIONAL_UP | NOT_DIRECTIONAL | NO_DATA | WEEKEND
    london_reason: str = ""       # disqualification reason if not directional
    london_open: Optional[float] = None
    london_high: Optional[float] = None
    london_low: Optional[float] = None
    london_close: Optional[float] = None
    london_range_pips: Optional[float] = None

    pullback_time: str = ""
    pullback_low: Optional[float] = None
    confirmed: bool = False
    rejected_sl_too_large: bool = False

    direction: str = ""           # always "BUY" or ""
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

    status: str = ""              # SKIPPED | NOT_DIRECTIONAL | NO_PULLBACK | SWEPT_NO_CONFIRM | TRADED


def daterange(start: date, end_inclusive: date):
    cur = start
    while cur <= end_inclusive:
        yield cur
        cur += timedelta(days=1)


def simulate_day(target_date: date, base: Path) -> DayResult:
    res = DayResult(date=target_date.isoformat(), weekday=target_date.strftime("%a"))
    if target_date.weekday() >= 5:
        res.london_class = "WEEKEND"
        res.status = "SKIPPED"
        return res

    today_bars = _read_csv_bars(base / f"{target_date.isoformat()}.csv")
    if not today_bars:
        res.london_class = "NO_DATA"
        res.status = "SKIPPED"
        return res

    london_bars = load_london_session_bars(target_date, base)
    cls = classify_london_session(london_bars)
    if cls is None:
        res.london_class = "NO_DATA"
        res.status = "SKIPPED"
        return res
    res.london_open = cls.london_open
    res.london_high = cls.london_high
    res.london_low = cls.london_low
    res.london_close = cls.london_close
    res.london_range_pips = round(cls.london_range_pips, 2)
    if not cls.is_directional_up:
        res.london_class = "NOT_DIRECTIONAL"
        res.london_reason = cls.reason
        res.status = "NOT_DIRECTIONAL"
        return res
    res.london_class = "DIRECTIONAL_UP"

    # Walk NY window for pullback then confirmation.
    win_start_dt = datetime.combine(target_date, WIN_START, tzinfo=timezone.utc)
    win_end_dt = datetime.combine(target_date, WIN_END, tzinfo=timezone.utc)
    pullback_timeout_dt = datetime.combine(
        target_date, PULLBACK_TIMEOUT_UTC, tzinfo=timezone.utc,
    )
    window_bars = [b for b in today_bars if win_start_dt <= b.timestamp < win_end_dt]

    london_range = cls.london_high - cls.london_low
    pullback_threshold = cls.london_close - PULLBACK_FRAC * london_range
    tp_price = cls.london_high + TP_EXTENSION_FRAC * london_range

    phase = "ARMED"
    pullback_low: Optional[float] = None
    pullback_time: Optional[datetime] = None
    entry_bar: Optional[Bar] = None
    sl_price: Optional[float] = None
    sl_pips: Optional[float] = None

    for b in window_bars:
        bar_close = b.timestamp + timedelta(minutes=5)

        if phase == "ARMED":
            if b.timestamp >= pullback_timeout_dt:
                phase = "DONE_TIMEOUT_NO_PULLBACK"
                break
            if b.low <= pullback_threshold:
                phase = "PULLED_BACK"
                pullback_low = b.low
                pullback_time = b.timestamp
                res.pullback_time = b.timestamp.strftime("%H:%M")
                res.pullback_low = b.low
            continue

        # PULLED_BACK
        assert pullback_time is not None and pullback_low is not None
        if (bar_close - pullback_time) > timedelta(minutes=CONFIRMATION_TIMEOUT_MIN):
            phase = "DONE_CONFIRM_TIMEOUT"
            break

        cond_after = bar_close > pullback_time
        cond_recover = b.close >= pullback_low + RECOVERY_PIPS * PIP_SIZE
        cond_dir = b.close > b.open
        if not (cond_after and cond_recover and cond_dir):
            continue
        rng_b = b.high - b.low
        if rng_b <= 0:
            continue
        body = abs(b.close - b.open)
        if (body / rng_b) < MIN_BODY_RATIO:
            continue
        if rng_b < MIN_BAR_RANGE_PIPS * PIP_SIZE:
            continue
        res.confirmed = True

        sl_p = pullback_low - SL_BUFFER_PIPS * PIP_SIZE
        sl_d = (b.close - sl_p) / PIP_SIZE
        if sl_d <= 0:
            continue
        if sl_d > MAX_SL_PIPS:
            res.rejected_sl_too_large = True
            continue

        entry_bar = b
        sl_price = sl_p
        sl_pips = sl_d
        phase = "ENTERED"
        break

    if phase != "ENTERED":
        if pullback_time is None:
            res.status = "NO_PULLBACK"
        elif not res.confirmed:
            res.status = "PULLBACK_NO_CONFIRM"
        else:
            res.status = "PULLBACK_NO_CONFIRM"  # confirmed bar(s) but rejected by SL gate
            if res.rejected_sl_too_large:
                res.status = "SL_TOO_WIDE"
        return res

    res.status = "TRADED"
    res.direction = "BUY"
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


def print_report(results: List[DayResult]) -> None:
    print(
        f"GBPUSD_NY_CONTINUATION_L validation (LONG-only) — "
        f"{len(results)} weekdays\n"
    )
    print("Per-day ledger:")
    hdr = (
        f"{'Date':<11} {'Wd':<4} {'Class':<16} {'LRng':>5} {'PB':<6} "
        f"{'PBLo':>8} {'Status':<22} {'Entry':<6} {'EntryP':>8} "
        f"{'SL':>5} {'TPtgt':>5} {'Exit':<13} {'Reason':<10} {'PnL':>7}  Notes"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        lr = f"{r.london_range_pips:.1f}" if r.london_range_pips is not None else "-"
        pbl = f"{r.pullback_low:.1f}" if r.pullback_low is not None else "-"
        ep = f"{r.entry_price:.1f}" if r.entry_price is not None else "-"
        slp = f"{r.sl_pips:.1f}" if r.sl_pips is not None else "-"
        tpt = f"{r.tp_pips_target:.1f}" if r.tp_pips_target is not None else "-"
        pnl = f"{r.pnl_pips:+.1f}" if r.pnl_pips is not None else "-"
        notes = r.london_reason or ""
        print(
            f"{r.date:<11} {r.weekday:<4} {r.london_class:<16} {lr:>5} "
            f"{(r.pullback_time or '-'):<6} {pbl:>8} {r.status:<22} "
            f"{(r.entry_time or '-'):<6} {ep:>8} {slp:>5} {tpt:>5} "
            f"{(r.exit_time or '-'):<13} {(r.exit_reason or '-'):<10} "
            f"{pnl:>7}  {notes}"
        )
    print("-" * len(hdr))

    # Funnel.
    n_total = len(results)
    n_skipped = sum(1 for r in results if r.status == "SKIPPED")
    inspected = [r for r in results if r.status != "SKIPPED"]
    n_inspected = len(inspected)
    n_range_pass = sum(
        1 for r in inspected
        if r.london_range_pips is not None and r.london_range_pips >= LONDON_MIN_RANGE_PIPS
    )
    n_directional = sum(1 for r in inspected if r.london_class == "DIRECTIONAL_UP")
    n_pullback = sum(1 for r in inspected if r.pullback_time)
    n_confirmed = sum(1 for r in inspected if r.confirmed)
    n_sl_rej = sum(1 for r in inspected if r.rejected_sl_too_large)
    trades = [r for r in inspected if r.status == "TRADED"]

    print()
    print("Funnel:")
    print(f"  All weekdays:                              {n_total}")
    print(f"  Inspected (data present):                  {n_inspected}")
    print(f"  London range >= {LONDON_MIN_RANGE_PIPS:.0f}p:                 {n_range_pass}")
    print(f"  + close in upper {int(LONDON_DIRECTIONAL_FRAC*100)}% AND net up: {n_directional}")
    print(f"  + had pullback (>= {int(PULLBACK_FRAC*100)}% retracement): {n_pullback}")
    print(f"  + had qualifying confirmation:             {n_confirmed}")
    print(f"  + (of confirmed) SL > {MAX_SL_PIPS:.0f}p rejection:    {n_sl_rej}")
    print(f"  Days TRADED:                               {len(trades)}")

    # Aggregate.
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
    print(f"  Days TRADED:                    {len(trades)}")
    print(f"  Wins / losses:                  {len(wins)} / {len(losses)}")
    print(f"  Net P&L (pips):                 {net:+.2f}")
    print(f"  Win rate:                       {wr:.1f}%")
    print(f"  Average winner:                 {avg_w:+.2f}p")
    print(f"  Average loser:                  {avg_l:+.2f}p")
    print(f"  Median winner:                  {median_w:+.2f}p")

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
    print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
