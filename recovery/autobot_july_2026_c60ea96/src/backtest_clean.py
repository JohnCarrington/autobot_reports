#!/usr/bin/env python3
"""
backtest_clean.py — Ground truth backtest from scratch.

No reuse of existing replay code. Clean implementation:
- Real OHLC candles from cached JSON
- Actual briefing_liquidity.py evaluate() on each candle close
- Fill at NEXT candle open (realistic)
- SL/TP checked against real high/low (SL wins if both hit same candle)
- Post-TP1 continuation with 10-pip retrace from peak
- 17:00 UTC session close at candle close price
"""

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv()

from briefing_liquidity import BriefingLiquidityStrategy

logging.basicConfig(level=logging.WARNING, format="%(message)s")
log = logging.getLogger("clean")
log.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────
PAIRS = {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP",
    "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}
DATES = [
    "2026-03-23", "2026-03-24", "2026-03-25",
    "2026-03-26", "2026-03-27", "2026-03-30", "2026-03-31",
    "2026-04-01", "2026-04-02", "2026-04-03",
]
PPP = 1.0
WARMUP = 60
SESSION_START_H = 7
SESSION_END_H = 17
COOLDOWN = timedelta(minutes=60)
POST_TP1_MAX_RETRACE = 10.0
POST_TP1_BELOW_BUFFER = 5.0

BRIEFING_SCHED = [(0, 0, "Asian"), (6, 30, "London"), (10, 45, "Mid-session"), (13, 0, "NY")]


# ── Monkey-patch datetime.now for strategy session gate ───────────
import briefing_liquidity as _bl_mod
_real_dt = datetime


class _SimDt(datetime):
    _now = None

    @classmethod
    def now(cls, tz=None):
        if cls._now is not None and tz is not None:
            return cls._now
        return _real_dt.now(tz)


_bl_mod.datetime = _SimDt


# ── Data types ────────────────────────────────────────────────────
@dataclass
class Candle:
    ts: datetime
    o: float
    h: float
    l: float
    c: float


@dataclass
class OpenTrade:
    pair: str
    date: str
    signal_time: str      # when signal fired
    fill_time: str        # when filled (next candle open)
    direction: str
    entry: float          # fill price (next candle open)
    signal_entry: float   # strategy's suggested entry
    sl_price: float
    tp1_price: float
    sl_pips: float
    tp1_pips: float
    source: str
    bias: str
    # post-TP1 state
    tp1_hit: bool = False
    post_tp1_peak: float = 0.0
    # result
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: Optional[str] = None
    pnl_pips: Optional[float] = None


# ── Helpers ───────────────────────────────────────────────────────
def load_candles(pair: str, date: str) -> List[Candle]:
    # Try cache/test_candles JSON first
    p = Path(f"/opt/tradingbot/cache/test_candles_{pair}_{date}.json")
    if p.exists():
        with open(p) as f:
            raw = json.load(f)
        if raw:
            candles = []
            for r in raw:
                ts = pd.to_datetime(r["timestamp"], utc=True)
                if hasattr(ts, "to_pydatetime"):
                    ts = ts.to_pydatetime()
                candles.append(Candle(
                    ts=ts,
                    o=float(r["open"]), h=float(r["high"]),
                    l=float(r["low"]), c=float(r["close"]),
                ))
            return candles

    # Fall back to data/candles/{pair}/{date}.csv
    csv_path = Path(f"/opt/tradingbot/data/candles/{pair}/{date}.csv")
    if csv_path.exists():
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        candles = []
        for _, r in df.iterrows():
            ts = r["timestamp"]
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            candles.append(Candle(
                ts=ts,
                o=float(r["open"]), h=float(r["high"]),
                l=float(r["low"]), c=float(r["close"]),
            ))
        return candles

    return []


def verify_candles(candles: List[Candle], pair: str, date: str) -> bool:
    """Verify 5M spacing and print sample."""
    if len(candles) < 10:
        return False
    gaps = []
    for i in range(1, min(20, len(candles))):
        gap = (candles[i].ts - candles[i - 1].ts).total_seconds()
        gaps.append(gap)
    median_gap = sorted(gaps)[len(gaps) // 2]
    if abs(median_gap - 300) > 30:
        log.warning("  %s %s: median gap %.0fs (expected 300s) — skipping", pair, date, median_gap)
        return False
    return True


def get_briefing(pair: str, date: str, ts: datetime) -> Optional[Dict]:
    best = None
    for h, m, name in BRIEFING_SCHED:
        gt = datetime(ts.year, ts.month, ts.day, h, m, tzinfo=timezone.utc)
        if ts >= gt:
            best = name
    if not best:
        return None
    p = Path(f"/opt/tradingbot/logs/briefing_{pair}_{date}_{best}.json")
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def build_df(candles: List[Candle], end_idx: int) -> pd.DataFrame:
    """Build DataFrame from candle list up to end_idx (inclusive)."""
    start = max(0, end_idx - WARMUP + 1)
    rows = []
    for c in candles[start:end_idx + 1]:
        rows.append({
            "timestamp": c.ts, "open": c.o, "high": c.h, "low": c.l, "close": c.c,
        })
    return pd.DataFrame(rows)


def pnl(direction: str, entry: float, price: float) -> float:
    return (price - entry) / PPP if direction == "BUY" else (entry - price) / PPP


# ── Trade simulation ─────────────────────────────────────────────
def check_trade(trade: OpenTrade, candle: Candle) -> Optional[str]:
    """Check a single candle against an open trade. Returns outcome or None."""
    is_buy = trade.direction == "BUY"

    if not trade.tp1_hit:
        # ── Phase 1: watching for SL or TP1 ──
        sl_hit = (candle.l <= trade.sl_price) if is_buy else (candle.h >= trade.sl_price)
        tp_hit = (candle.h >= trade.tp1_price) if is_buy else (candle.l <= trade.tp1_price)

        if sl_hit and tp_hit:
            # Both in same candle — SL wins (conservative)
            trade.exit_price = trade.sl_price
            trade.pnl_pips = -trade.sl_pips
            return "SL"
        if sl_hit:
            trade.exit_price = trade.sl_price
            trade.pnl_pips = -trade.sl_pips
            return "SL"
        if tp_hit:
            # TP1 reached — enter post-TP1 continuation
            trade.tp1_hit = True
            if is_buy:
                trade.post_tp1_peak = max((candle.h - trade.entry) / PPP, trade.tp1_pips)
            else:
                trade.post_tp1_peak = max((trade.entry - candle.l) / PPP, trade.tp1_pips)
            return None  # hold — continuation watch

    else:
        # ── Phase 2: post-TP1 continuation ──
        if is_buy:
            candle_best = (candle.h - trade.entry) / PPP
            candle_worst = (candle.l - trade.entry) / PPP
        else:
            candle_best = (trade.entry - candle.l) / PPP
            candle_worst = (trade.entry - candle.h) / PPP

        peak = max(trade.post_tp1_peak, candle_best)
        trade.post_tp1_peak = peak

        # Exit 1: price drops below TP1 minus buffer
        if candle_worst < trade.tp1_pips - POST_TP1_BELOW_BUFFER:
            trade.exit_price = trade.tp1_price
            trade.pnl_pips = trade.tp1_pips
            return "TP1"

        # Exit 2: retrace from peak exceeds max (simulate intra-candle catch)
        retrace = peak - candle_worst
        if retrace >= POST_TP1_MAX_RETRACE:
            exit_pips = max(peak - POST_TP1_MAX_RETRACE, trade.tp1_pips)
            trade.pnl_pips = exit_pips
            if is_buy:
                trade.exit_price = trade.entry + exit_pips * PPP
            else:
                trade.exit_price = trade.entry - exit_pips * PPP
            return "TP1+RET"

    return None


# ── Day replay ────────────────────────────────────────────────────
def replay_day(pair: str, epic: str, date: str) -> List[OpenTrade]:
    candles = load_candles(pair, date)
    if not candles or not verify_candles(candles, pair, date):
        return []

    strat = BriefingLiquidityStrategy()
    completed: List[OpenTrade] = []
    trade: Optional[OpenTrade] = None
    pending_signal: Optional[Dict] = None  # signal waiting for next-candle fill
    last_signal_ts: Optional[datetime] = None

    for i in range(WARMUP, len(candles)):
        c = candles[i]
        _SimDt._now = c.ts
        h = c.ts.hour

        # ── Step 1: Fill pending signal at this candle's open ──
        if pending_signal is not None:
            ps = pending_signal
            pending_signal = None

            fill_price = c.o
            direction = ps["direction"]

            # Recalculate SL/TP from fill price (not signal entry)
            if direction == "BUY":
                sl_price = fill_price - ps["sl_pips"] * PPP
                tp1_price = fill_price + ps["tp1_pips"] * PPP
            else:
                sl_price = fill_price + ps["sl_pips"] * PPP
                tp1_price = fill_price - ps["tp1_pips"] * PPP

            trade = OpenTrade(
                pair=pair, date=date, signal_time=ps["time"], fill_time=c.ts.strftime("%H:%M"),
                direction=direction, entry=fill_price, signal_entry=ps["signal_entry"],
                sl_price=sl_price, tp1_price=tp1_price,
                sl_pips=ps["sl_pips"], tp1_pips=ps["tp1_pips"],
                source=ps["source"], bias=ps["bias"],
            )

        # ── Step 2: Manage open trade ──
        if trade is not None:
            if h >= SESSION_END_H:
                p = pnl(trade.direction, trade.entry, c.c)
                if trade.tp1_hit:
                    trade.pnl_pips = max(p, trade.tp1_pips)
                    trade.outcome = "TP1+17:00"
                else:
                    trade.pnl_pips = p
                    trade.outcome = "17:00"
                trade.exit_time = c.ts.strftime("%H:%M")
                trade.exit_price = c.c
                completed.append(trade)
                trade = None
            else:
                result = check_trade(trade, c)
                if result:
                    trade.exit_time = c.ts.strftime("%H:%M")
                    trade.outcome = result
                    completed.append(trade)
                    trade = None

        # ── Step 3: Evaluate strategy for new signal ──
        if h < SESSION_START_H or h >= SESSION_END_H:
            continue
        if trade is not None or pending_signal is not None:
            continue
        if last_signal_ts and (c.ts - last_signal_ts) < COOLDOWN:
            continue

        briefing = get_briefing(pair, date, c.ts)
        if not briefing:
            continue

        df = build_df(candles, i)
        try:
            dec = strat.evaluate(pair, epic, df, PPP, c.c, briefing)
        except Exception:
            continue

        sig = str(dec.signal or "").upper()
        if sig not in ("BUY", "SELL"):
            continue

        src = dec.debug.get("entry_source", "?")
        last_signal_ts = c.ts

        # Queue signal for next-candle fill
        pending_signal = {
            "time": c.ts.strftime("%H:%M"),
            "direction": sig,
            "signal_entry": float(dec.entry or c.c),
            "sl_pips": float(dec.sl or 10),
            "tp1_pips": float(dec.tp or 15),
            "source": src,
            "bias": dec.debug.get("bias", "?"),
        }

    # Close remaining
    if trade is not None:
        lc = candles[-1]
        p = pnl(trade.direction, trade.entry, lc.c)
        if trade.tp1_hit:
            trade.pnl_pips = max(p, trade.tp1_pips)
            trade.outcome = "TP1+EOD"
        else:
            trade.pnl_pips = p
            trade.outcome = "EOD"
        trade.exit_time = "EOD"
        trade.exit_price = lc.c
        completed.append(trade)

    return completed


# ── Main ──────────────────────────────────────────────────────────
def main():
    # ── Data verification ──
    print("=" * 110)
    print("  CLEAN BACKTEST — Ground Truth")
    print("  Fill at next candle open | SL wins if ambiguous | Post-TP1 10p retrace | 17:00 close")
    print("=" * 110)
    print()

    # Print sample candles
    sample_candles = load_candles("GBPUSD", "2026-03-27")
    if sample_candles:
        print("  Sample candles (GBPUSD 2026-03-27):")
        for c in sample_candles[80:85]:
            print(f"    {c.ts.strftime('%H:%M')}  O={c.o:.1f}  H={c.h:.1f}  L={c.l:.1f}  C={c.c:.1f}")
        gaps = [(sample_candles[i + 1].ts - sample_candles[i].ts).total_seconds()
                for i in range(len(sample_candles) - 1)]
        print(f"    Candle interval: {sorted(gaps)[len(gaps) // 2]:.0f}s (median)")
        print()

    # ── Replay ──
    all_trades: List[OpenTrade] = []
    pair_stats: Dict[str, Dict] = {}
    day_totals: Dict[str, float] = {}

    for pair, epic in PAIRS.items():
        pair_trades = []
        for date in DATES:
            trades = replay_day(pair, epic, date)
            if not trades:
                continue

            # ── Per-day output ──
            day_pnl = sum(t.pnl_pips or 0 for t in trades)
            day_key = f"{date}"
            day_totals[day_key] = day_totals.get(day_key, 0) + day_pnl

            # Get briefing bias
            sample_ts = datetime(int(date[:4]), int(date[5:7]), int(date[8:10]),
                                 8, 0, tzinfo=timezone.utc)
            br = get_briefing(pair, date, sample_ts)
            bias_str = ""
            if br:
                sb = str(br.get("session_bias", "")).upper()
                conf = br.get("bias_confidence", "?")
                bias_str = f"{sb} ({conf})"

            print(f"  {date} {pair}")
            if bias_str:
                print(f"    Briefing: {bias_str}")

            for t in trades:
                slip = t.entry - t.signal_entry
                slip_str = f" (slip {slip:+.1f})" if abs(slip) > 0.1 else ""
                print(f"    {t.signal_time} → fill {t.fill_time} {t.direction} @ {t.entry:.1f}{slip_str} | "
                      f"SL {t.sl_price:.1f} ({t.sl_pips:.0f}p) | TP1 {t.tp1_price:.1f} ({t.tp1_pips:.0f}p) | "
                      f"[{t.source}]")
                if t.tp1_hit:
                    print(f"      → TP1 HIT | post-TP1 peak: +{t.post_tp1_peak:.1f}p | "
                          f"exit {t.exit_time}: {t.outcome} {t.pnl_pips:+.1f} pips")
                else:
                    print(f"      → exit {t.exit_time}: {t.outcome} {t.pnl_pips:+.1f} pips")

            print(f"    Day total: {day_pnl:+.1f} pips")
            print()

            pair_trades.extend(trades)

        # Pair summary
        total = sum(t.pnl_pips or 0 for t in pair_trades)
        wins = sum(1 for t in pair_trades if (t.pnl_pips or 0) > 0)
        wr = wins / len(pair_trades) * 100 if pair_trades else 0
        active_days = len(set(t.pair + t.fill_time[:5] for t in pair_trades))  # rough
        pair_stats[pair] = {"trades": len(pair_trades), "wins": wins, "wr": wr, "pnl": total}
        all_trades.extend(pair_trades)

    # ── Summary tables ──
    print("=" * 110)
    print("  PER-PAIR SUMMARY")
    print("=" * 110)
    print(f"  {'Pair':>8} {'Trades':>7} {'Wins':>5} {'WR':>5} {'Total P&L':>10} {'Avg/day':>8}")
    print(f"  {'-'*50}")
    grand_pnl = 0
    grand_trades = 0
    grand_wins = 0
    for pair in PAIRS:
        s = pair_stats.get(pair, {"trades": 0, "wins": 0, "wr": 0, "pnl": 0})
        active = max(1, len(set(t.date for t in all_trades if t.pair == pair)))
        avg = s["pnl"] / active if active > 0 else 0
        print(f"  {pair:>8} {s['trades']:>7} {s['wins']:>5} {s['wr']:>4.0f}% {s['pnl']:>+10.1f} {avg:>+8.1f}")
        grand_pnl += s["pnl"]
        grand_trades += s["trades"]
        grand_wins += s["wins"]

    print(f"  {'-'*50}")
    gwr = grand_wins / grand_trades * 100 if grand_trades else 0
    print(f"  {'TOTAL':>8} {grand_trades:>7} {grand_wins:>5} {gwr:>4.0f}% {grand_pnl:>+10.1f}")

    # ── Per-source breakdown ──
    print(f"\n  PER-SOURCE:")
    sources = {}
    for t in all_trades:
        s = t.source
        if s not in sources:
            sources[s] = {"n": 0, "w": 0, "pnl": 0}
        sources[s]["n"] += 1
        sources[s]["pnl"] += t.pnl_pips or 0
        if (t.pnl_pips or 0) > 0:
            sources[s]["w"] += 1
    for s in sorted(sources):
        v = sources[s]
        wr = v["w"] / v["n"] * 100 if v["n"] else 0
        print(f"    {s:>18}: {v['n']:>3} trades | {v['pnl']:>+8.1f} pips | WR {wr:.0f}%")

    # ── Per-day cross-pair total ──
    print(f"\n  PER-DAY CROSS-PAIR TOTAL:")
    active_days = 0
    for date in DATES:
        dt = [t for t in all_trades if t.date == date]
        if not dt:
            continue
        active_days += 1
        dp = sum(t.pnl_pips or 0 for t in dt)
        pairs_active = set(t.pair for t in dt)
        print(f"    {date}: {dp:>+8.1f} pips ({len(dt)} trades, {', '.join(sorted(pairs_active))})")

    daily_avg = grand_pnl / active_days if active_days > 0 else 0

    # ── Grand total ──
    print(f"\n{'='*110}")
    print(f"  GRAND TOTAL")
    print(f"{'='*110}")
    print(f"  Trades:        {grand_trades}")
    print(f"  Win rate:      {gwr:.0f}% ({grand_wins}W / {grand_trades - grand_wins}L)")
    print(f"  Total P&L:     {grand_pnl:+.1f} pips")
    print(f"  Active days:   {active_days}")
    print(f"  Avg pips/day:  {daily_avg:+.1f} (target: 100)")
    print(f"  Gap:           {100 - daily_avg:.1f} pips/day")
    print(f"  @ £1/pip:      £{grand_pnl:+.2f} total | £{daily_avg:+.2f}/day")
    print(f"  @ £10/pip:     £{grand_pnl * 10:+.2f} total | £{daily_avg * 10:+.2f}/day")
    print(f"{'='*110}")


if __name__ == "__main__":
    main()
