#!/usr/bin/env python3
"""
validate_bb_premirror_long.py — backtest GBPUSD_BB_PREMIRROR_L over a
window of weekdays, reading 5m candles from data/candles/GBPUSD/<date>.csv.

Per-day flow:
  - Load bars; iterate forward in time.
  - For each bar in the trading window with at least 21 prior closes,
    evaluate the (N, N+1) pair using BB(20,2):
      bb_lower_at_n_close   = BB on closes ending at bar N
      bb_upper_at_np1_close = BB on closes ending at bar N+1
  - On detector match: simulate entry at bar N+1's close, walk forward
    bar-by-bar to SL or TP. Same-bar SL+TP collision resolved as SL.
  - Resume scanning after exit; cap at MAX_TRADES_PER_DAY.

Funnel: counts bar-pairs dropped at each detector gate. The validator
re-implements the detector with explicit per-gate counters rather than
calling the pure detector — this is the only way to attribute drops.

Usage:
    python3 scripts/validate_bb_premirror_long.py --start 2026-03-30 --end 2026-04-25
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbpusd_bb_premirror_long import (  # noqa: E402
    Bar,
    PIP_SIZE,
    BAR_N_BODY_RATIO,
    BAR_NP1_BODY_RATIO_OF_N,
    BAND_PROXIMITY_PIPS,
    MIRROR_TOLERANCE_PIPS,
    SL_BUFFER_PIPS,
    MAX_SL_PIPS,
    MAX_TRADES_PER_DAY,
    WIN_START, WIN_END,
)

DEFAULT_CANDLE_ARCHIVE = Path("/opt/tradingbot/data/candles/GBPUSD")


# ─── BB(20,2) — same formula as gbpusd_bb_reversal_long.bb_20_2 ─────────
def bb_20_2(closes: List[float]) -> Tuple[float, float, float]:
    """Return (lower, mid, upper) for the last 20 closes."""
    if len(closes) < 20:
        raise ValueError("need at least 20 closes for BB(20,2)")
    window = list(closes[-20:])
    mid = sum(window) / 20.0
    var = sum((c - mid) ** 2 for c in window) / 20.0
    std = var ** 0.5
    return mid - 2 * std, mid, mid + 2 * std


def _read_csv_bars(path: Path) -> List[Bar]:
    bars: List[Bar] = []
    if not path.exists():
        return bars
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                ts_s = (row.get("timestamp") or row.get("time") or "").strip()
                if not ts_s:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)
                try:
                    bars.append(Bar(
                        timestamp=ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                    ))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return bars
    bars.sort(key=lambda b: b.timestamp)
    return bars


@dataclass
class Funnel:
    """Counts bar-pairs that pass each gate sequentially."""
    pairs_evaluated: int = 0
    bearish_n: int = 0
    no_pierce: int = 0
    body_ratio_n: int = 0
    band_proximity: int = 0
    bullish_np1: int = 0
    mirror_body_ratio: int = 0
    mirror_tolerance: int = 0
    sl_in_range: int = 0
    tp_positive: int = 0
    fired: int = 0


@dataclass
class TradeRecord:
    entry_time: str
    entry_price: float
    sl_pips: float
    tp_pips: float
    bb_width_at_entry: float
    sl_price: float
    tp_price: float
    bar_n_low: float
    exit_time: str
    exit_price: float
    exit_reason: str
    pnl_pips: float


def daterange(start: date, end_inclusive: date):
    cur = start
    while cur <= end_inclusive:
        yield cur
        cur += timedelta(days=1)


def simulate(
    days: List[date],
    base: Path,
) -> Tuple[List[TradeRecord], Funnel, List[Bar]]:
    """Walk all bars across `days` (chronological), running the detector
    on each (N, N+1) pair where N+1 is in the trading window. Returns the
    trade ledger, funnel counts, and the merged bar list (for diagnostics).
    """
    # Read all bars across the window plus the day after the end (for
    # post-window forward walk on late-window entries).
    all_bars: List[Bar] = []
    seen_ts = set()
    for d in days + [days[-1] + timedelta(days=1)] if days else []:
        path = base / f"{d.isoformat()}.csv"
        for b in _read_csv_bars(path):
            if b.timestamp not in seen_ts:
                all_bars.append(b)
                seen_ts.add(b.timestamp)
    all_bars.sort(key=lambda b: b.timestamp)

    funnel = Funnel()
    trades: List[TradeRecord] = []
    if len(all_bars) < 21:
        return trades, funnel, all_bars

    closes = [b.close for b in all_bars]
    trades_today: dict = {}
    open_until_ts: Optional[datetime] = None  # block scans while a trade is open

    for i in range(20, len(all_bars)):
        bNp1 = all_bars[i]
        # Need bar N+1 in the trading window on a weekday.
        if bNp1.timestamp.weekday() >= 5:
            continue
        if not (WIN_START <= bNp1.timestamp.time() < WIN_END):
            continue
        # Trading-day cap.
        date_key = bNp1.timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d")
        if trades_today.get(date_key, 0) >= MAX_TRADES_PER_DAY:
            continue
        # Block re-evaluation while a trade is open (we exit at SL or TP
        # in the forward walk; until then we don't issue another entry).
        if open_until_ts is not None and bNp1.timestamp <= open_until_ts:
            continue

        bN = all_bars[i - 1]

        # BB(20,2) at bar N's close: closes ending at bar N (index i-1
        # inclusive, so closes[i-20:i] which is the 20 closes up to and
        # including bar N).
        bb_lower_at_n, _, _ = bb_20_2(closes[i - 20:i])
        # BB(20,2) at bar N+1's close: closes[i-19:i+1].
        bb_lower_np1, bb_mid_np1, bb_upper_np1 = bb_20_2(closes[i - 19:i + 1])

        funnel.pairs_evaluated += 1

        if not bN.is_bearish:
            continue
        funnel.bearish_n += 1

        if bN.low <= bb_lower_at_n:
            continue
        funnel.no_pierce += 1

        if bN.body_ratio < BAR_N_BODY_RATIO:
            continue
        funnel.body_ratio_n += 1

        close_to_band = bN.close - bb_lower_at_n
        if close_to_band < 0 or close_to_band > BAND_PROXIMITY_PIPS * PIP_SIZE:
            continue
        funnel.band_proximity += 1

        if not bNp1.is_bullish:
            continue
        funnel.bullish_np1 += 1

        bN_body_abs = abs(bN.body)
        if bN_body_abs <= 0:
            continue
        if abs(bNp1.body) < BAR_NP1_BODY_RATIO_OF_N * bN_body_abs:
            continue
        funnel.mirror_body_ratio += 1

        if bNp1.close < bN.open - MIRROR_TOLERANCE_PIPS * PIP_SIZE:
            continue
        funnel.mirror_tolerance += 1

        # Geometry / risk.
        entry = bNp1.close
        sl_price = bN.low - SL_BUFFER_PIPS * PIP_SIZE
        sl_pips = (entry - sl_price) / PIP_SIZE
        if sl_pips <= 0 or sl_pips > MAX_SL_PIPS:
            continue
        funnel.sl_in_range += 1

        tp_price = bb_upper_np1
        tp_pips = (tp_price - entry) / PIP_SIZE
        if tp_pips <= 0:
            continue
        funnel.tp_positive += 1

        # Fire entry. Forward walk for exit.
        funnel.fired += 1
        bb_width_at_entry = bb_upper_np1 - bb_lower_np1

        exit_reason = ""
        exit_price = entry
        exit_time_dt = bNp1.timestamp
        for fb in all_bars[i + 1:]:
            sl_hit = fb.low <= sl_price
            tp_hit = fb.high >= tp_price
            if sl_hit and tp_hit:
                exit_reason = "SL"  # conservative: SL on tie
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
            # Ran out of bars — mark as TIMEOUT_EOD using the last bar's close.
            last_b = all_bars[-1]
            exit_price = last_b.close
            exit_time_dt = last_b.timestamp
            exit_reason = "TIMEOUT_EOD"

        pnl = (exit_price - entry) / PIP_SIZE
        trades.append(TradeRecord(
            entry_time=bNp1.timestamp.strftime("%Y-%m-%d %H:%M"),
            entry_price=entry,
            sl_pips=round(sl_pips, 2),
            tp_pips=round(tp_pips, 2),
            bb_width_at_entry=round(bb_width_at_entry, 2),
            sl_price=sl_price,
            tp_price=tp_price,
            bar_n_low=bN.low,
            exit_time=exit_time_dt.strftime("%Y-%m-%d %H:%M"),
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl_pips=round(pnl, 2),
        ))
        trades_today[date_key] = trades_today.get(date_key, 0) + 1
        open_until_ts = exit_time_dt

    return trades, funnel, all_bars


def print_report(trades: List[TradeRecord], funnel: Funnel, days: List[date]) -> None:
    print(
        f"GBPUSD_BB_PREMIRROR_L validation (LONG-only) — "
        f"{len(days)} weekday(s) {days[0].isoformat()} → {days[-1].isoformat()}\n"
    )
    print("Per-trade ledger:")
    hdr = (
        f"{'Entry':<17} {'EntryP':>8} {'SL':>6} {'TP':>6} {'BBw':>6}  "
        f"{'Exit':<17} {'Reason':<10} {'PnL':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for t in trades:
        print(
            f"{t.entry_time:<17} {t.entry_price:>8.1f} {t.sl_pips:>6.1f} "
            f"{t.tp_pips:>6.1f} {t.bb_width_at_entry:>6.1f}  "
            f"{t.exit_time:<17} {t.exit_reason:<10} {t.pnl_pips:>+7.2f}"
        )
    print("-" * len(hdr))

    # Funnel.
    print()
    print("Funnel (sequential gates — each line is a subset of the line above):")
    print(f"  Pairs evaluated (window x days):    {funnel.pairs_evaluated}")
    print(f"  bar N bearish:                      {funnel.bearish_n}")
    print(f"  + no-pierce (low > BB_lower_at_N):  {funnel.no_pierce}")
    print(f"  + body_ratio_N >= {BAR_N_BODY_RATIO:.2f}:           {funnel.body_ratio_n}")
    print(f"  + band proximity <= {BAND_PROXIMITY_PIPS:.0f}p:           {funnel.band_proximity}")
    print(f"  + bar N+1 bullish:                  {funnel.bullish_np1}")
    print(f"  + mirror body >= {BAR_NP1_BODY_RATIO_OF_N:.2f} * bN:     {funnel.mirror_body_ratio}")
    print(f"  + mirror close >= bN.open - {MIRROR_TOLERANCE_PIPS:.0f}p:   {funnel.mirror_tolerance}")
    print(f"  + SL <= {MAX_SL_PIPS:.0f}p:                       {funnel.sl_in_range}")
    print(f"  + TP > 0:                           {funnel.tp_positive}")
    print(f"  + fired (and respected day cap):    {funnel.fired}")

    # Aggregate.
    n_total = funnel.fired
    wins = [t for t in trades if t.pnl_pips > 0]
    losses = [t for t in trades if t.pnl_pips <= 0]
    net = sum(t.pnl_pips for t in trades)
    wr = (len(wins) / n_total * 100) if n_total else 0.0
    avg_w = (sum(t.pnl_pips for t in wins) / len(wins)) if wins else 0.0
    avg_l = (sum(t.pnl_pips for t in losses) / len(losses)) if losses else 0.0
    median_w = 0.0
    if wins:
        sw = sorted(t.pnl_pips for t in wins)
        median_w = (
            sw[len(sw) // 2]
            if len(sw) % 2 == 1
            else (sw[len(sw) // 2 - 1] + sw[len(sw) // 2]) / 2
        )

    print()
    print("Aggregate:")
    print(f"  Days inspected:                 {len(days)}")
    print(f"  Trades:                         {n_total}")
    print(f"  Wins / losses:                  {len(wins)} / {len(losses)}")
    print(f"  Net P&L (pips):                 {net:+.2f}")
    print(f"  Win rate:                       {wr:.1f}%")
    print(f"  Average winner:                 {avg_w:+.2f}p")
    print(f"  Average loser:                  {avg_l:+.2f}p")
    print(f"  Median winner:                  {median_w:+.2f}p")

    pass_trades = n_total >= 5
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
    days = [d for d in daterange(start, end) if d.weekday() < 5]
    trades, funnel, _ = simulate(days, base)
    print_report(trades, funnel, days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
