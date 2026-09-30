#!/usr/bin/env python3
"""
backtest_briefing_tp.py — Compare briefing-level TPs vs fixed TP=30.

Two modes running on same candle data and briefing signals:
  A) Fixed TP=30, SL=20 (current baseline)
  B) Briefing-level TP1/TP2/TP3 with momentum checks and SL progression

Uses real candle data + real briefing JSONs.
Reports pips/day for each mode.
"""

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv()

from briefing_liquidity import BriefingLiquidityStrategy
from trade_manager import select_tp_levels, check_momentum
from indicators import add_indicators

logging.basicConfig(level=logging.WARNING, format="%(message)s")
log = logging.getLogger("bt_tp")
log.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────
PAIR = "GBPUSD"
EPIC = "CS.D.GBPUSD.TODAY.IP"
DATES = [
    "2026-03-23", "2026-03-24", "2026-03-25",
    "2026-03-26", "2026-03-27", "2026-03-30", "2026-03-31",
    "2026-04-01", "2026-04-02", "2026-04-03",
]
PPP = 1.0
WARMUP = 60
SESSION_START_H = 7
SESSION_END_H = 17

# Fixed mode config
FIXED_TP = 30.0
FIXED_SL = 20.0

# Briefing mode
POST_TP1_MAX_RETRACE = 10.0
POST_TP1_BELOW_BUFFER = 5.0
PULLBACK_TRAIL = 20.0

BRIEFING_SCHED = [(0, 0, "Asian"), (6, 30, "London"), (10, 45, "Mid-session"), (13, 0, "NY")]

# ── Monkey-patch datetime.now for strategy ───────────
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


# ── Data types ────────────────────────────────────────────────
@dataclass
class Candle:
    ts: datetime
    o: float
    h: float
    l: float
    c: float

@dataclass
class TradeResult:
    mode: str  # "FIXED" or "BRIEFING"
    date: str
    direction: str
    entry: float
    exit_price: float
    pnl_pips: float
    outcome: str
    tp_phase: str = ""


# ── Helpers ───────────────────────────────────────────────────
def load_candles(date: str) -> List[Candle]:
    for p in [
        Path(f"/opt/tradingbot/cache/test_candles_{PAIR}_{date}.json"),
    ]:
        if p.exists():
            with open(p) as f:
                raw = json.load(f)
            if raw:
                candles = []
                for r in raw:
                    ts = pd.to_datetime(r["timestamp"], utc=True).to_pydatetime()
                    candles.append(Candle(ts=ts, o=float(r["open"]), h=float(r["high"]),
                                         l=float(r["low"]), c=float(r["close"])))
                return candles

    csv_path = Path(f"/opt/tradingbot/data/candles/{PAIR}/{date}.csv")
    if csv_path.exists():
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        candles = []
        for _, r in df.iterrows():
            ts = r["timestamp"].to_pydatetime()
            candles.append(Candle(ts=ts, o=float(r["open"]), h=float(r["high"]),
                                  l=float(r["low"]), c=float(r["close"])))
        return candles
    return []


def get_briefing(date: str, ts: datetime) -> Optional[Dict]:
    best = None
    for h, m, name in BRIEFING_SCHED:
        gt = datetime(ts.year, ts.month, ts.day, h, m, tzinfo=timezone.utc)
        if ts >= gt:
            best = name
    if not best:
        return None
    for d in ["/opt/tradingbot/logs", "/opt/tradingbot/cache/test_briefings"]:
        p = Path(f"{d}/briefing_{PAIR}_{date}_{best}.json")
        if p.exists():
            with open(p) as f:
                return json.load(f)
        # Try without Mid-session hyphen variants
        if best == "Mid-session":
            p2 = Path(f"{d}/briefing_{PAIR}_{date}_Mid-session.json")
            if p2.exists():
                with open(p2) as f:
                    return json.load(f)
    return None


def extract_briefing_levels(briefing: Optional[Dict]) -> List[Dict]:
    """Extract all levels from a briefing JSON into the format select_tp_levels expects."""
    if not briefing:
        return []
    levels = []
    for src_key in ["key_levels", "major_levels"]:
        d = briefing.get(src_key, {})
        is_major = (src_key == "major_levels")
        for v in d.get("resistance", []):
            if v is not None:
                levels.append({"price": float(v), "level_type": "resistance",
                              "source": src_key, "major": is_major})
        for v in d.get("support", []):
            if v is not None:
                levels.append({"price": float(v), "level_type": "support",
                              "source": src_key, "major": is_major})
    lp = briefing.get("liquidity_pools", {})
    for v in lp.get("buy_side", []):
        if v is not None:
            levels.append({"price": float(v), "level_type": "resistance",
                          "source": "liquidity_buy", "major": False})
    for v in lp.get("sell_side", []):
        if v is not None:
            levels.append({"price": float(v), "level_type": "support",
                          "source": "liquidity_sell", "major": False})
    return levels


def build_df(candles: List[Candle], end_idx: int) -> pd.DataFrame:
    start = max(0, end_idx - WARMUP + 1)
    rows = [{"timestamp": c.ts, "open": c.o, "high": c.h, "low": c.l, "close": c.c}
            for c in candles[start:end_idx + 1]]
    return pd.DataFrame(rows)


def pnl(direction: str, entry: float, price: float) -> float:
    return (price - entry) / PPP if direction == "BUY" else (entry - price) / PPP


# ── Simulate fixed TP mode ────────────────────────────────────
def sim_fixed(direction: str, entry: float, candles: List[Candle], start_idx: int, date: str) -> TradeResult:
    """Simulate a trade with fixed TP=30, SL=20."""
    is_buy = direction == "BUY"
    sl_price = entry - FIXED_SL * PPP if is_buy else entry + FIXED_SL * PPP
    tp_price = entry + FIXED_TP * PPP if is_buy else entry - FIXED_TP * PPP

    for i in range(start_idx, len(candles)):
        c = candles[i]
        # Session close
        if c.ts.hour >= SESSION_END_H:
            p = pnl(direction, entry, c.c)
            return TradeResult("FIXED", date, direction, entry, c.c, p, "SESSION_CLOSE")

        sl_hit = (c.l <= sl_price) if is_buy else (c.h >= sl_price)
        tp_hit = (c.h >= tp_price) if is_buy else (c.l <= tp_price)

        if sl_hit and tp_hit:
            return TradeResult("FIXED", date, direction, entry, sl_price, -FIXED_SL, "SL")
        if sl_hit:
            return TradeResult("FIXED", date, direction, entry, sl_price, -FIXED_SL, "SL")
        if tp_hit:
            return TradeResult("FIXED", date, direction, entry, tp_price, FIXED_TP, "TP")

    p = pnl(direction, entry, candles[-1].c)
    return TradeResult("FIXED", date, direction, entry, candles[-1].c, p, "EOD")


# ── Simulate briefing TP mode ────────────────────────────────
def _compute_indicators(candles: List[Candle], end_idx: int) -> Optional[pd.DataFrame]:
    """Build DataFrame with real MACD indicators for momentum checks."""
    start = max(0, end_idx - WARMUP + 1)
    rows = [{"timestamp": c.ts, "open": c.o, "high": c.h, "low": c.l, "close": c.c}
            for c in candles[start:end_idx + 1]]
    df = pd.DataFrame(rows)
    if len(df) < 45:  # Need enough bars for MACD (35/45)
        return None
    try:
        df = add_indicators(df)
    except Exception:
        return None
    return df


def _get_macd_hist(df: Optional[pd.DataFrame]) -> Tuple[float, float]:
    """Extract current and previous MACD histogram from indicator DF."""
    if df is None or len(df) < 2:
        return 0.0, 0.0
    # Find MACD hist column
    hist_cols = [c for c in df.columns if "MACD_HIST" in c]
    if not hist_cols:
        return 0.0, 0.0
    col = hist_cols[0]
    curr = df[col].iloc[-1]
    prev = df[col].iloc[-2]
    if pd.isna(curr) or pd.isna(prev):
        return 0.0, 0.0
    return float(curr), float(prev)


def sim_briefing(direction: str, entry: float, briefing_levels: List[Dict],
                 candles: List[Candle], start_idx: int, date: str) -> TradeResult:
    """Simulate a trade with briefing-level TP1/TP2/TP3, momentum checks, SL progression."""
    tp = select_tp_levels(entry, direction, briefing_levels, PAIR)
    is_buy = direction == "BUY"

    sl_price = entry - tp["sl_pips"] * PPP if is_buy else entry + tp["sl_pips"] * PPP
    phase = "OPEN"
    swing_extreme = entry

    for i in range(start_idx, len(candles)):
        c = candles[i]

        # Session close
        if c.ts.hour >= SESSION_END_H:
            p = pnl(direction, entry, c.c)
            return TradeResult("BRIEFING", date, direction, entry, c.c, p, "SESSION_CLOSE", phase)

        # Update swing extreme
        if is_buy:
            swing_extreme = max(swing_extreme, c.h)
        else:
            swing_extreme = min(swing_extreme, c.l)

        # SL check
        sl_hit = (c.l <= sl_price) if is_buy else (c.h >= sl_price)
        if sl_hit:
            p = pnl(direction, entry, sl_price)
            return TradeResult("BRIEFING", date, direction, entry, sl_price, p, f"SL_{phase}", phase)

        # TP3 check (always close)
        tp3_hit = (c.h >= tp["tp3"]) if is_buy else (c.l <= tp["tp3"])
        if tp3_hit and phase in ("OPEN", "TP1", "TP2"):
            p = pnl(direction, entry, tp["tp3"])
            return TradeResult("BRIEFING", date, direction, entry, tp["tp3"], p, "TP3", "TP3")

        # Pullback trail (between levels after TP1)
        if phase in ("TP1", "TP2"):
            if is_buy:
                pullback = (swing_extreme - c.l) / PPP
            else:
                pullback = (c.h - swing_extreme) / PPP
            if pullback >= PULLBACK_TRAIL:
                exit_p = swing_extreme - PULLBACK_TRAIL * PPP if is_buy else swing_extreme + PULLBACK_TRAIL * PPP
                p = pnl(direction, entry, exit_p)
                return TradeResult("BRIEFING", date, direction, entry, exit_p, p, f"PULLBACK_{phase}", phase)

        # Momentum helper
        def _momentum_check(idx: int) -> str:
            bodies = []
            for j in range(max(start_idx, idx-2), idx+1):
                bodies.append((candles[j].o, candles[j].c))
            highs = [candles[max(start_idx, idx-1)].h, candles[idx].h]
            lows = [candles[max(start_idx, idx-1)].l, candles[idx].l]
            # Real MACD indicators
            ind_df = _compute_indicators(candles, idx)
            macd_curr, macd_prev = _get_macd_hist(ind_df)
            return check_momentum(direction, macd_curr, macd_prev, bodies, highs, lows)

        # TP2 check
        tp2_hit = (c.h >= tp["tp2"]) if is_buy else (c.l <= tp["tp2"])
        if tp2_hit and phase == "TP1":
            mom = _momentum_check(i)
            if mom == "HOLD":
                phase = "TP2"
                sl_price = tp["tp1"]  # SL → TP1
                swing_extreme = c.h if is_buy else c.l
                continue
            else:
                p = pnl(direction, entry, tp["tp2"])
                return TradeResult("BRIEFING", date, direction, entry, tp["tp2"], p, "TP2_CLOSE", "TP2")

        # TP1 check
        tp1_hit = (c.h >= tp["tp1"]) if is_buy else (c.l <= tp["tp1"])
        if tp1_hit and phase == "OPEN":
            mom = _momentum_check(i)
            if mom == "HOLD":
                phase = "TP1"
                sl_price = entry  # breakeven
                swing_extreme = c.h if is_buy else c.l
                continue
            else:
                p = pnl(direction, entry, tp["tp1"])
                return TradeResult("BRIEFING", date, direction, entry, tp["tp1"], p, "TP1_CLOSE", "TP1")

    p = pnl(direction, entry, candles[-1].c)
    return TradeResult("BRIEFING", date, direction, entry, candles[-1].c, p, "EOD", phase)


# ── Day replay using strategy signals ────────────────────────
def replay_day(date: str) -> Tuple[List[TradeResult], List[TradeResult]]:
    candles = load_candles(date)
    if not candles or len(candles) < WARMUP + 10:
        return [], []

    strat = BriefingLiquidityStrategy()
    fixed_results = []
    briefing_results = []
    cooldown_until: Optional[datetime] = None
    pending_signal = None

    for i in range(WARMUP, len(candles)):
        c = candles[i]
        _SimDt._now = c.ts
        h = c.ts.hour

        # Fill pending signal at this candle's open
        if pending_signal is not None:
            ps = pending_signal
            pending_signal = None
            fill_price = c.o
            direction = ps["direction"]
            briefing_levels = ps["levels"]

            fr = sim_fixed(direction, fill_price, candles, i, date)
            br = sim_briefing(direction, fill_price, briefing_levels, candles, i, date)
            fixed_results.append(fr)
            briefing_results.append(br)

        # Only look for new signals during session
        if h < SESSION_START_H or h >= SESSION_END_H:
            continue
        if pending_signal is not None:
            continue
        if cooldown_until and c.ts < cooldown_until:
            continue

        # Build DF and evaluate strategy
        df = build_df(candles, i)
        if len(df) < 20:
            continue

        briefing = get_briefing(date, c.ts)
        if not briefing:
            continue

        try:
            dec = strat.evaluate(PAIR, EPIC, df, PPP, c.c, briefing)
        except Exception:
            continue

        sig = str(dec.signal or "").upper()
        if sig not in ("BUY", "SELL"):
            continue

        # Queue for next-candle fill
        cooldown_until = c.ts + timedelta(minutes=60)
        pending_signal = {
            "direction": sig,
            "levels": extract_briefing_levels(briefing),
        }

    return fixed_results, briefing_results


# ── Main ─────────────────────────────────────────────────────
def main():
    all_fixed = []
    all_briefing = []

    print("="*80)
    print("BACKTEST: Briefing-Level TPs vs Fixed TP=30")
    print(f"Pair: {PAIR}  |  Dates: {DATES[0]} → {DATES[-1]}")
    print("="*80)

    for date in DATES:
        fixed, briefing = replay_day(date)
        all_fixed.extend(fixed)
        all_briefing.extend(briefing)

        f_pips = sum(r.pnl_pips for r in fixed) if fixed else 0
        b_pips = sum(r.pnl_pips for r in briefing) if briefing else 0
        print(f"  {date}: signals={len(fixed):>2}  "
              f"Fixed={f_pips:>+7.1f}p  Briefing={b_pips:>+7.1f}p  "
              f"diff={b_pips - f_pips:>+6.1f}p")

    print(f"\n{'─'*80}")
    print("TOTALS")
    print(f"{'─'*80}")

    f_total = sum(r.pnl_pips for r in all_fixed)
    b_total = sum(r.pnl_pips for r in all_briefing)
    n_days = len([d for d in DATES if any(r.date == d for r in all_fixed)])
    n_trades = len(all_fixed)

    print(f"  Trades: {n_trades}")
    print(f"  Trading days: {n_days}")
    print(f"  Fixed TP=30:       {f_total:>+8.1f} pips total  ({f_total/max(n_days,1):>+6.1f} pips/day)")
    print(f"  Briefing-level TP: {b_total:>+8.1f} pips total  ({b_total/max(n_days,1):>+6.1f} pips/day)")
    print(f"  Difference:        {b_total - f_total:>+8.1f} pips ({'+' if b_total > f_total else ''}{(b_total-f_total)/max(n_days,1):.1f} pips/day)")
    print()

    # Outcome breakdown
    for label, results in [("FIXED", all_fixed), ("BRIEFING", all_briefing)]:
        outcomes = {}
        for r in results:
            outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
        print(f"  {label} outcomes: {dict(sorted(outcomes.items()))}")

    # Win rate
    for label, results in [("FIXED", all_fixed), ("BRIEFING", all_briefing)]:
        wins = sum(1 for r in results if r.pnl_pips > 0)
        total = len(results)
        wr = wins / total * 100 if total else 0
        avg_win = np.mean([r.pnl_pips for r in results if r.pnl_pips > 0]) if wins else 0
        losses = [r.pnl_pips for r in results if r.pnl_pips <= 0]
        avg_loss = np.mean(losses) if losses else 0
        print(f"  {label}: WR={wr:.0f}% ({wins}/{total})  avg_win={avg_win:+.1f}  avg_loss={avg_loss:+.1f}")

    print()
    if b_total > f_total:
        print(f"✅ Briefing-level TPs outperform fixed TP=30 by {b_total - f_total:+.1f} pips")
    else:
        print(f"⚠️  Fixed TP=30 outperforms briefing-level TPs by {f_total - b_total:+.1f} pips")

    return b_total, f_total


if __name__ == "__main__":
    main()
