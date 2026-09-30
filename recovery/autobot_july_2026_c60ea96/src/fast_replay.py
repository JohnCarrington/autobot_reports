#!/usr/bin/env python3
"""
fast_replay.py — Lightweight replay that calls strategy evaluate() directly.

Bypasses AutoBot, candle_builder, trade_manager, and all orchestration.
Pre-computes indicators once, then iterates candles calling each strategy's
evaluate() with the rolling DataFrame.  SL/TP checked against real tick data.

Runs a full day in ~5-10 seconds.

Usage:
    python3 fast_replay.py GBPUSD 2026-03-27
    python3 fast_replay.py GBPUSD                # all available dates
"""
import sys, os, json, logging, argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")

from dotenv import load_dotenv
load_dotenv("/opt/tradingbot/.env", override=True)

# Replay clock — patched into strategy modules that use datetime.now()
import time as _time_mod
import datetime as _dt_mod
_replay_epoch = [0.0]
_orig_time = _time_mod.time
_time_mod.time = lambda: _replay_epoch[0] if _replay_epoch[0] > 0 else _orig_time()
_time_mod.sleep = lambda s: None

def _replay_now(tz=None):
    if _replay_epoch[0] > 0:
        return _dt_mod.datetime.fromtimestamp(_replay_epoch[0], tz=tz or _dt_mod.timezone.utc)
    return _dt_mod.datetime.now(tz)

# Block external HTTP
import requests as _req
_FakeResp = type("R", (), {
    "status_code": 200, "text": "[]", "ok": True,
    "json": lambda self: [], "raise_for_status": lambda self: None,
    "content": b"[]", "headers": {},
})
_req.post = lambda *a, **kw: _FakeResp()
_req.get = lambda *a, **kw: _FakeResp()

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

import pandas as pd
import numpy as np
from indicators import add_indicators, IndicatorsConfig

CANDLE_DIR = Path("/opt/tradingbot/data/candles")
TICK_DIR = Path("/opt/tradingbot/data/ticks")
BRIEFING_DIR = Path("/opt/tradingbot/logs")
CFG = IndicatorsConfig(bb_period=20, bb_std=2.0, macd_fast=35, macd_slow=45, macd_signal=30)
EPIC_MAP = {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP", "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP", "GBPJPY": "CS.D.GBPJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}
SPREAD = {"GBPUSD": 0.8, "EURUSD": 0.6, "USDJPY": 0.8, "GBPJPY": 1.5, "USDCAD": 1.0}
WARMUP = 50
MAX_HOLD_CANDLES = 24
PIP_SIZE = 1.0

# ── SimTrade ────────────────────────────────────────────────────────
@dataclass
class SimTrade:
    pair: str
    mode: str
    direction: str
    entry: float
    sl_pips: float
    tp_pips: float
    entry_ts: pd.Timestamp
    reason: str = ""
    is_buy: bool = field(init=False)
    current_sl: float = field(init=False)
    be_armed: bool = False
    trail_armed: bool = False
    best_pnl: float = 0.0
    candles: int = 0
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    exit_ts: Optional[pd.Timestamp] = None

    def __post_init__(self):
        self.is_buy = self.direction == "BUY"
        self.current_sl = (self.entry - self.sl_pips) if self.is_buy else (self.entry + self.sl_pips)

    def check_tick(self, mid: float, ts) -> bool:
        """Check SL/TP at a tick price. Returns True if trade closed."""
        if self.exit_price is not None:
            return True
        pnl = (mid - self.entry) if self.is_buy else (self.entry - mid)
        self.best_pnl = max(self.best_pnl, pnl)
        # BE + trail at +12p
        if not self.trail_armed and self.best_pnl >= 12.0:
            self.trail_armed = True
            self.be_armed = True
        if self.trail_armed:
            floor = max(10.0, self.best_pnl - 10.0)
            new_sl = (self.entry + floor) if self.is_buy else (self.entry - floor)
            self.current_sl = max(self.current_sl, new_sl) if self.is_buy else min(self.current_sl, new_sl)
        # SL check
        if (self.is_buy and mid <= self.current_sl) or (not self.is_buy and mid >= self.current_sl):
            self.exit_price = self.current_sl
            self.exit_reason = "TRAIL" if self.trail_armed else "SL"
            self.exit_ts = ts
            return True
        # TP check
        tp_price = (self.entry + self.tp_pips) if self.is_buy else (self.entry - self.tp_pips)
        if (self.is_buy and mid >= tp_price) or (not self.is_buy and mid <= tp_price):
            self.exit_price = tp_price
            self.exit_reason = "TP"
            self.exit_ts = ts
            return True
        return False

    def check_candle(self, row) -> bool:
        """Check SL/TP on candle OHLC. Returns True if trade closed."""
        if self.exit_price is not None:
            return True
        self.candles += 1
        h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
        # Check extremes
        if self.is_buy:
            self.check_tick(l, row["timestamp"])
            if self.exit_price is None:
                self.check_tick(h, row["timestamp"])
        else:
            self.check_tick(h, row["timestamp"])
            if self.exit_price is None:
                self.check_tick(l, row["timestamp"])
        # Max hold
        if self.exit_price is None and self.candles >= MAX_HOLD_CANDLES:
            self.exit_price = c
            self.exit_reason = "MAX_HOLD"
            self.exit_ts = row["timestamp"]
            return True
        return self.exit_price is not None

    @property
    def pnl(self):
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry) if self.is_buy else (self.entry - self.exit_price)

    @property
    def duration_min(self):
        return self.candles * 5


# ── Data loading ────────────────────────────────────────────────────
def load_candles(pair, dates=None):
    frames = []
    for f in sorted((CANDLE_DIR / pair).glob("*.csv")):
        if dates and f.stem not in dates:
            continue
        df = pd.read_csv(f)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return add_indicators(combined, config=CFG)


def load_briefings(pair):
    entries = []
    for f in sorted(BRIEFING_DIR.glob(f"briefing_{pair}_*.json")):
        try:
            data = json.loads(f.read_text())
            bt = data.get("briefing_time")
            if bt:
                ts = pd.Timestamp(bt)
                ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
                entries.append((ts, data))
        except Exception:
            pass
    entries.sort(key=lambda x: x[0])
    return entries


def get_briefing_at(candle_ts, briefing_index):
    result = None
    for bts, bdata in briefing_index:
        if bts <= candle_ts:
            result = bdata
        else:
            break
    return result


def load_tick_data(pair, target_date):
    """Load real tick data for a single date. Returns numpy arrays or None."""
    tick_file = TICK_DIR / f"{pair}_ticks_2026.csv"
    if not tick_file.exists():
        return None
    _jpy = {"USDJPY", "GBPJPY", "EURJPY", "AUDJPY"}
    scale = 100 if pair.upper() in _jpy else 10000
    date_str = str(target_date)[:10]
    next_str = str(pd.Timestamp(target_date) + pd.Timedelta(days=1))[:10]
    # Read only relevant lines using binary search
    import os as _os
    fpath = str(tick_file)
    fsize = _os.path.getsize(fpath)
    with open(fpath, "r") as fh:
        header = fh.readline()
    from true_replay import _bsearch_file_offset
    off_start = _bsearch_file_offset(fpath, date_str, fsize)
    off_end = _bsearch_file_offset(fpath, next_str, fsize)
    with open(fpath, "r") as fh:
        fh.seek(off_start)
        if off_start > 0:
            fh.readline()
        lines = []
        while True:
            line = fh.readline()
            if not line or line[:10] >= next_str:
                break
            lines.append(line)
    if not lines:
        return None
    from io import StringIO
    df = pd.read_csv(StringIO(header + "".join(lines)), parse_dates=["timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return {
        "ts": df["timestamp"].values,
        "epochs": df["timestamp"].values.astype(np.int64) / 1e9,
        "mids": df["mid"].values * scale,
        "count": len(df),
    }


# ── Main replay ────────────────────────────────────────────────────
def replay_pair(pair, target_date):
    from reversal_sweep import ReversalSweepStrategy, REVERSAL_SWEEP_ENABLED, ALLOWED_PAIRS as RS_PAIRS
    from continuation_sweep import ContinuationSweepStrategy, CONTINUATION_SWEEP_ENABLED
    from ema_pullback import EmaPullbackStrategy

    epic = EPIC_MAP.get(pair, f"CS.D.{pair}.TODAY.IP")
    spread = SPREAD.get(pair, 1.0)

    # Load all candles up to target date
    all_csvs = sorted(f.stem for f in (CANDLE_DIR / pair).glob("*.csv"))
    dates_to_load = [d for d in all_csvs if d <= target_date]
    full_df = load_candles(pair, dates_to_load)
    if full_df.empty:
        return []

    # Find target date start
    target_start = next(
        (i for i in range(len(full_df)) if full_df.iloc[i]["timestamp"].strftime("%Y-%m-%d") == target_date),
        None,
    )
    if target_start is None:
        return []

    briefing_index = load_briefings(pair)
    tick_data = load_tick_data(pair, target_date)

    # Instantiate strategies
    rs = ReversalSweepStrategy()
    cs = ContinuationSweepStrategy()
    ep = EmaPullbackStrategy()

    strategies = []
    if REVERSAL_SWEEP_ENABLED and pair.upper() in RS_PAIRS:
        strategies.append(("REVERSAL_SWEEP", rs))
    if CONTINUATION_SWEEP_ENABLED:
        strategies.append(("CONTINUATION_SWEEP", cs))
    strategies.append(("EMA_PULLBACK", ep))

    trades: List[SimTrade] = []
    open_trades: Dict[str, SimTrade] = {}

    # Warmup: run strategies on prior-day candles (no trades recorded)
    for i in range(WARMUP, target_start):
        row = full_df.iloc[i]
        ts = row["timestamp"]
        _replay_epoch[0] = ts.timestamp()
        close = float(row["close"])
        mid = close
        briefing = get_briefing_at(ts, briefing_index)
        df_window = full_df.iloc[max(0, i - 59):i + 1].copy().reset_index(drop=True)
        if len(df_window) < 25:
            continue
        for name, strat in strategies:
            try:
                strat.evaluate(pair, epic, df_window, PIP_SIZE, mid, briefing or {})
            except Exception:
                pass

    # Reset strategy internal state after warmup so cooldowns don't carry over
    rs._armed.clear()
    rs._last_entry_idx.clear()
    if hasattr(cs, '_armed'):
        cs._armed.clear()
    if hasattr(cs, '_last_entry_idx'):
        cs._last_entry_idx.clear()

    # Replay target date
    for i in range(target_start, len(full_df)):
        row = full_df.iloc[i]
        ts = row["timestamp"]
        _replay_epoch[0] = ts.timestamp()
        close = float(row["close"])
        mid = close
        briefing = get_briefing_at(ts, briefing_index)

        # Check open trades against tick data for this candle
        if tick_data is not None and open_trades:
            ts_dt64 = ts.to_datetime64()
            end_dt64 = (ts + pd.Timedelta(minutes=5)).to_datetime64()
            i_lo = np.searchsorted(tick_data["ts"], ts_dt64, side="left")
            i_hi = np.searchsorted(tick_data["ts"], end_dt64, side="left")
            if i_hi > i_lo:
                # Subsample ~50 ticks
                n = i_hi - i_lo
                step = max(1, n // 50)
                for j in range(i_lo, i_hi, step):
                    tick_mid = tick_data["mids"][j]
                    tick_ts = pd.Timestamp(tick_data["ts"][j])
                    for mode in list(open_trades):
                        if open_trades[mode].check_tick(tick_mid, tick_ts):
                            trades.append(open_trades.pop(mode))

        # Check open trades against candle OHLC (fallback / max hold)
        for mode in list(open_trades):
            if open_trades[mode].check_candle(row):
                trades.append(open_trades.pop(mode))

        # Evaluate strategies at candle close
        df_window = full_df.iloc[max(0, i - 59):i + 1].copy().reset_index(drop=True)
        if len(df_window) < 25:
            continue

        for name, strat in strategies:
            if name in open_trades:
                continue
            try:
                dec = strat.evaluate(pair, epic, df_window, PIP_SIZE, mid, briefing or {})
            except Exception:
                continue
            sig = getattr(dec, "signal", "NONE")
            if sig not in ("BUY", "SELL"):
                continue
            mode = getattr(dec, "mode", name) or name
            if mode in open_trades:
                continue
            entry = getattr(dec, "entry", None) or mid
            sl = getattr(dec, "sl", None) or 20.0
            tp = getattr(dec, "tp", None) or 30.0
            open_trades[mode] = SimTrade(
                pair=pair, mode=mode, direction=sig,
                entry=float(entry), sl_pips=float(sl), tp_pips=float(tp),
                entry_ts=ts, reason=getattr(dec, "reason", ""),
            )

    # Close remaining
    for mode in list(open_trades):
        t = open_trades[mode]
        last = full_df.iloc[-1]
        t.exit_price = float(last["close"])
        t.exit_reason = "EOD"
        t.exit_ts = last["timestamp"]
        trades.append(t)

    return sorted(trades, key=lambda t: t.entry_ts)


# ── Reporting ───────────────────────────────────────────────────────
def print_results(all_trades, pair, target_date):
    if not all_trades:
        print(f"\n  No trades on {target_date}.")
        return

    print(f"\n{'=' * 120}")
    print(f"  FAST REPLAY — {pair} — {target_date} — {len(all_trades)} trades")
    print(f"{'=' * 120}")

    by_mode = {}
    for t in all_trades:
        by_mode.setdefault(t.mode, []).append(t)

    print(f"\n  {'Strategy':<22} {'N':>4} {'W':>3} {'L':>3} {'WR%':>6} {'AvgPnL':>8} {'Total':>9} {'Best':>7} {'Worst':>7}")
    print(f"  {'─'*22} {'─'*4} {'─'*3} {'─'*3} {'─'*6} {'─'*8} {'─'*9} {'─'*7} {'─'*7}")

    grand_pnl = grand_n = grand_w = 0
    for mode in sorted(by_mode):
        mt = by_mode[mode]
        n = len(mt)
        pnls = [t.pnl for t in mt]
        w = sum(1 for p in pnls if p > 0)
        l = sum(1 for p in pnls if p < 0)
        print(f"  {mode:<22} {n:>4} {w:>3} {l:>3} {w/n*100:>5.1f}% {sum(pnls)/n:>+8.1f} "
              f"{sum(pnls):>+9.1f} {max(pnls):>+7.1f} {min(pnls):>+7.1f}")
        grand_pnl += sum(pnls); grand_n += n; grand_w += w

    print(f"  {'─'*22} {'─'*4} {'─'*3} {'─'*3} {'─'*6} {'─'*8} {'─'*9}")
    print(f"  {'TOTAL':<22} {grand_n:>4} {grand_w:>3} {grand_n-grand_w:>3} "
          f"{grand_w/grand_n*100:>5.1f}% {grand_pnl/grand_n:>+8.1f} {grand_pnl:>+9.1f}")

    print(f"\n  {'#':<3} {'UTC':>5} {'Strategy':<22} {'Dir':>4} {'Entry':>9} {'Exit':>9} "
          f"{'PnL':>7} {'Reason':<10} {'Hold':>5} {'Peak':>6}")
    print(f"  {'─'*3} {'─'*5} {'─'*22} {'─'*4} {'─'*9} {'─'*9} "
          f"{'─'*7} {'─'*10} {'─'*5} {'─'*6}")
    for i, t in enumerate(all_trades, 1):
        print(f"  {i:<3} {t.entry_ts.strftime('%H:%M'):>5} {t.mode:<22} {t.direction:>4} "
              f"{t.entry:>9.2f} {t.exit_price:>9.2f} {t.pnl:>+7.1f} "
              f"{t.exit_reason:<10} {t.duration_min:>4}m {t.best_pnl:>+6.1f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Fast Replay")
    parser.add_argument("pair", default="GBPUSD")
    parser.add_argument("date", nargs="?", default=None)
    args = parser.parse_args()

    pair = args.pair.upper()
    if args.date:
        dates = [args.date]
    else:
        dates = sorted(f.stem for f in (CANDLE_DIR / pair).glob("*.csv"))

    for d in dates:
        trades = replay_pair(pair, d)
        print_results(trades, pair, d)


if __name__ == "__main__":
    main()
