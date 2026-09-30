#!/usr/bin/env python3
"""
replay_engine.py — Simple, correct replay through live evaluate_signals().

For each 5M candle:
  1. WINDOW_SWEEP: check candle high/low vs BB + MACD from dataframe
  2. BRIEFING_EXECUTION: check candle high/low for sweep detection,
     candle close for Phase 2 confirmation
  3. All other strategies: candle close fed through evaluate_signals()
  4. Trade management: subsequent candle OHLC for SL/BE/trail/max-hold

No synthetic ticks. No complex sequencing. Just OHLC candles.

Usage:
    python3 replay_engine.py                      # all pairs, all dates
    python3 replay_engine.py GBPUSD               # single pair
    python3 replay_engine.py GBPUSD 2026-04-10    # single pair + date
"""
import sys, os, json, logging, argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, "/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv("/opt/tradingbot/.env", override=True)
os.chdir("/opt/tradingbot")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
for _m in ("strategy_logic", "trade_manager", "regime_router",
           "briefing_sweep", "briefing_execution", "news_strategy",
           "london_open_pullback", "ema_pullback", "briefing_hunt",
           "briefing_liquidity", "morning_briefing", "indicators"):
    logging.getLogger(_m).setLevel(logging.ERROR)

import pandas as pd
import numpy as np
from indicators import add_indicators, IndicatorsConfig

CANDLE_DIR = Path("/opt/tradingbot/data/candles")
BRIEFING_DIR = Path("/opt/tradingbot/logs")
INDICATOR_CFG = IndicatorsConfig(
    bb_period=20, bb_std=2.0, macd_fast=35, macd_slow=45, macd_signal=30,
)
EPIC_MAP = {
    "GBPUSD": "CS.D.GBPUSD.TODAY.IP", "EURUSD": "CS.D.EURUSD.TODAY.IP",
    "USDJPY": "CS.D.USDJPY.TODAY.IP", "GBPJPY": "CS.D.GBPJPY.TODAY.IP",
    "USDCAD": "CS.D.USDCAD.TODAY.IP",
}
SPREAD = {"GBPUSD": 0.8, "EURUSD": 0.6, "USDJPY": 0.8, "GBPJPY": 1.5, "USDCAD": 1.0}
WARMUP = 50
MAX_HOLD_CANDLES = 24  # 120 min
DEFAULT_SL = 20.0


# ── Briefing loader ──────────────────────────────────────────────────
def load_briefings(pair: str) -> List[Tuple[pd.Timestamp, Dict]]:
    entries = []
    for f in sorted(BRIEFING_DIR.glob(f"briefing_{pair}_*.json")):
        try:
            data = json.loads(f.read_text())
            bt = data.get("briefing_time")
            if not bt:
                continue
            ts = pd.Timestamp(bt)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            entries.append((ts, data))
        except Exception:
            continue
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


# ── Candle loader ────────────────────────────────────────────────────
def load_pair_candles(pair: str, dates: Optional[List[str]] = None) -> pd.DataFrame:
    pair_dir = CANDLE_DIR / pair
    frames = []
    for f in sorted(pair_dir.glob("*.csv")):
        if dates is not None and f.stem not in dates:
            continue
        df = pd.read_csv(f)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return add_indicators(combined, config=INDICATOR_CFG)


# ── Trade simulation ─────────────────────────────────────────────────
@dataclass
class SimTrade:
    pair: str
    mode: str
    direction: str
    entry: float
    sl_pips: float
    entry_ts: pd.Timestamp
    reason: str = ""

    # Runtime
    is_buy: bool = field(init=False)
    current_sl: float = field(init=False)
    be_armed: bool = False
    trail_armed: bool = False
    best_pnl: float = 0.0
    max_run: float = 0.0
    max_dd: float = 0.0
    candles: int = 0
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    exit_ts: Optional[pd.Timestamp] = None

    def __post_init__(self):
        self.is_buy = self.direction == "BUY"
        self.current_sl = (self.entry - self.sl_pips) if self.is_buy else (self.entry + self.sl_pips)

    def tick(self, row) -> bool:
        if self.exit_price is not None:
            return True
        self.candles += 1
        h, l, c = float(row["high"]), float(row["low"]), float(row["close"])

        pnl_best = (h - self.entry) if self.is_buy else (self.entry - l)
        pnl_worst = (l - self.entry) if self.is_buy else (self.entry - h)
        self.max_run = max(self.max_run, pnl_best)
        self.max_dd = min(self.max_dd, pnl_worst)
        self.best_pnl = max(self.best_pnl, pnl_best)

        # SL check
        worst = l if self.is_buy else h
        if (self.is_buy and worst <= self.current_sl) or (not self.is_buy and worst >= self.current_sl):
            self.exit_price = self.current_sl
            self.exit_reason = "TRAIL" if self.trail_armed else ("BE" if self.be_armed else "SL")
            self.exit_ts = row["timestamp"]
            return True

        # Exit management
        if self.mode == "WINDOW_SWEEP":
            # BE + trail arm together at +12p, trail 15p behind peak, floor at breakeven
            if not self.be_armed and self.best_pnl >= 12.0:
                self.be_armed = True
                self.trail_armed = True
            if self.trail_armed:
                floor = max(0.0, self.best_pnl - 15.0)
                new_sl = (self.entry + floor) if self.is_buy else (self.entry - floor)
                self.current_sl = max(self.current_sl, new_sl) if self.is_buy else min(self.current_sl, new_sl)
        else:
            # Other strategies: BE at +12p, lock floor +10p, trail offset 10p
            if not self.be_armed and self.best_pnl >= 12.0:
                self.be_armed = True
                self.trail_armed = True
            if self.trail_armed:
                floor = max(10.0, self.best_pnl - 10.0)
                new_sl = (self.entry + floor) if self.is_buy else (self.entry - floor)
                self.current_sl = max(self.current_sl, new_sl) if self.is_buy else min(self.current_sl, new_sl)

        # Max hold
        if self.candles >= MAX_HOLD_CANDLES:
            self.exit_price = c
            self.exit_reason = "MAX_HOLD"
            self.exit_ts = row["timestamp"]
            return True
        return False

    @property
    def pnl(self):
        return ((self.exit_price - self.entry) if self.is_buy else (self.entry - self.exit_price)) if self.exit_price else 0.0

    @property
    def duration_min(self):
        return self.candles * 5


# ── Strategy state reset ─────────────────────────────────────────────
def reset_strategy_state():
    import strategy_logic as sl
    sl._EDGE_SWEEP_STATE.clear()
    sl._LAST_SWEEP_EXTREME.clear()
    sl._TREND_DURATION_STATE.clear()
    for attr in ("_be_strat", "_bl_strat", "_ws_fired", "_ws_last_close",
                 "_bh_strat", "_lop_strat", "_ep_strat"):
        if hasattr(sl.evaluate_signals, attr):
            try: delattr(sl.evaluate_signals, attr)
            except Exception: pass


# ── Main replay ──────────────────────────────────────────────────────
def replay_pair(pair: str, dates: Optional[List[str]] = None) -> List[SimTrade]:
    from strategy_logic import evaluate_signals

    epic = EPIC_MAP.get(pair, f"CS.D.{pair}.TODAY.IP")
    spread = SPREAD.get(pair, 1.0)

    full_df = load_pair_candles(pair, dates)
    if full_df.empty:
        print(f"  [{pair}] No candle data.")
        return []

    briefing_index = load_briefings(pair)

    # Monkey-patch briefing access
    import morning_briefing
    _briefing_now = {}
    _orig_get = morning_briefing.get_briefing
    morning_briefing.get_briefing = lambda sym=None: _briefing_now.get(str(sym or "").upper())

    trades: List[SimTrade] = []
    open_trades: Dict[str, SimTrade] = {}
    last_bucket = None
    last_date = None

    for i in range(WARMUP, len(full_df)):
        row = full_df.iloc[i]
        ts = row["timestamp"]
        day_str = ts.strftime('%Y-%m-%d')
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])

        # Day boundary — reset strategy state
        if day_str != last_date:
            reset_strategy_state()
            last_date = day_str
            last_bucket = None

        # 5M bucket detection
        bucket = int(ts.timestamp()) // 300
        is_new_5m = (last_bucket is None or last_bucket != bucket)
        last_bucket = bucket

        # Manage open trades — tick with full OHLC
        for mode in list(open_trades):
            if open_trades[mode].tick(row):
                trades.append(open_trades.pop(mode))

        if not is_new_5m:
            continue

        # Set briefing
        briefing = get_briefing_at(ts, briefing_index)
        _briefing_now[pair] = briefing

        # ── BRIEFING_EXECUTION: pre-arm sweep using candle high/low ──
        # This is the only special handling needed. We check if the
        # candle's wick touched the entry zone boundary, then let
        # evaluate_signals() handle Phase 2 at the close price.
        if hasattr(evaluate_signals, "_be_strat"):
            be = evaluate_signals._be_strat
            if briefing and isinstance(briefing, dict):
                be.on_briefing(pair, briefing)
            plan = be._plans.get(pair)
            if plan and not be._entered.get(pair) and not be._sweep_seen.get(pair):
                zone_lo = min(plan["entry_zone"])
                zone_hi = max(plan["entry_zone"])
                if plan["direction"] == "SELL" and high >= zone_hi:
                    be._sweep_seen[pair] = True
                elif plan["direction"] == "BUY" and low <= zone_lo:
                    be._sweep_seen[pair] = True

        # Build rolling df — no lookahead
        start = max(0, i - 59)
        df_window = full_df.iloc[start:i + 1].copy().reset_index(drop=True)

        # Call evaluate_signals at candle close
        bid = close - spread / 2
        ask = close + spread / 2
        try:
            dec = evaluate_signals(
                symbol=pair, epic=epic, bid=bid, ask=ask,
                df=df_window, is_new_5m_close=True,
                ts=ts.timestamp(), has_open_position=bool(open_trades),
            )
        except Exception:
            continue

        sig = getattr(dec, "signal", "NONE")
        if sig not in ("BUY", "SELL"):
            continue

        mode = getattr(dec, "mode", "UNKNOWN") or "UNKNOWN"
        entry = getattr(dec, "entry", None)
        sl = getattr(dec, "sl", None) or DEFAULT_SL
        reason = getattr(dec, "reason", "") or ""

        if entry is None or mode in open_trades:
            continue

        open_trades[mode] = SimTrade(
            pair=pair, mode=mode, direction=sig,
            entry=float(entry), sl_pips=float(sl),
            entry_ts=ts, reason=reason,
        )

    # Close remaining
    for mode in list(open_trades):
        t = open_trades[mode]
        last = full_df.iloc[-1]
        t.exit_price = float(last["close"])
        t.exit_reason = "EOD"
        t.exit_ts = last["timestamp"]
        trades.append(t)

    morning_briefing.get_briefing = _orig_get
    return trades


# ── Reporting ────────────────────────────────────────────────────────
def print_results(all_trades: List[SimTrade]):
    if not all_trades:
        print("\n  No trades generated.")
        return

    trades = sorted(all_trades, key=lambda t: t.entry_ts)
    dates = sorted(set(t.entry_ts.strftime('%Y-%m-%d') for t in trades))

    print(f"\n{'=' * 130}")
    print(f"  REPLAY ENGINE — {', '.join(sorted(set(t.pair for t in trades)))}")
    print(f"  {dates[0]} → {dates[-1]}  ({len(dates)} trading days)  {len(trades)} trades")
    print(f"{'=' * 130}")

    # Strategy summary
    by_mode = {}
    for t in trades:
        by_mode.setdefault(t.mode, []).append(t)

    print(f"\n  {'Strategy':<22} {'N':>4} {'W':>3} {'L':>3} {'WR%':>6} {'AvgPnL':>8} {'Total':>9} {'Best':>7} {'Worst':>7} {'AvgHold':>8}")
    print(f"  {'─'*22} {'─'*4} {'─'*3} {'─'*3} {'─'*6} {'─'*8} {'─'*9} {'─'*7} {'─'*7} {'─'*8}")

    grand_pnl = grand_n = grand_w = 0
    for mode in sorted(by_mode):
        mt = by_mode[mode]
        n = len(mt)
        pnls = [t.pnl for t in mt]
        w = sum(1 for p in pnls if p > 0)
        l = sum(1 for p in pnls if p < 0)
        print(f"  {mode:<22} {n:>4} {w:>3} {l:>3} {w/n*100:>5.1f}% {sum(pnls)/n:>+8.1f} "
              f"{sum(pnls):>+9.1f} {max(pnls):>+7.1f} {min(pnls):>+7.1f} "
              f"{sum(t.duration_min for t in mt)/n:>7.0f}m")
        grand_pnl += sum(pnls); grand_n += n; grand_w += w

    print(f"  {'─'*22} {'─'*4} {'─'*3} {'─'*3} {'─'*6} {'─'*8} {'─'*9}")
    print(f"  {'TOTAL':<22} {grand_n:>4} {grand_w:>3} {grand_n-grand_w:>3} "
          f"{grand_w/grand_n*100:>5.1f}% {grand_pnl/grand_n:>+8.1f} {grand_pnl:>+9.1f}")

    exits = {}
    for t in trades:
        exits[t.exit_reason] = exits.get(t.exit_reason, 0) + 1
    print(f"\n  Exits: {', '.join(f'{r}={c}' for r, c in sorted(exits.items()))}")

    # Trade log
    print(f"\n{'=' * 130}")
    print(f"  TRADE LOG")
    print(f"{'=' * 130}")
    print(f"  {'#':<4} {'Date':>10} {'UTC':>5} {'Strategy':<22} {'Dir':>4} {'Entry':>9} {'Exit':>9} "
          f"{'PnL':>7} {'Reason':<10} {'Hold':>5} {'Peak':>6} {'DD':>6}")
    print(f"  {'─'*4} {'─'*10} {'─'*5} {'─'*22} {'─'*4} {'─'*9} {'─'*9} "
          f"{'─'*7} {'─'*10} {'─'*5} {'─'*6} {'─'*6}")

    for i, t in enumerate(trades, 1):
        print(f"  {i:<4} {t.entry_ts.strftime('%Y-%m-%d'):>10} {t.entry_ts.strftime('%H:%M'):>5} "
              f"{t.mode:<22} {t.direction:>4} {t.entry:>9.2f} {t.exit_price:>9.2f} "
              f"{t.pnl:>+7.1f} {t.exit_reason:<10} {t.duration_min:>4}m "
              f"{t.max_run:>+6.1f} {t.max_dd:>+6.1f}")

    # Equity curve
    print(f"\n{'=' * 130}")
    print(f"  EQUITY CURVE")
    print(f"{'=' * 130}")
    daily = {}
    for t in trades:
        d = t.entry_ts.strftime('%Y-%m-%d')
        daily.setdefault(d, []).append(t.pnl)
    cum = 0.0
    for d in sorted(daily):
        day_pnl = sum(daily[d])
        cum += day_pnl
        n = len(daily[d])
        bar = ("█" if cum >= 0 else "░") * min(int(abs(cum) / 3), 50)
        print(f"  {d}  {n:>2} trades  day={day_pnl:>+7.1f}p  cum={cum:>+8.1f}p  {bar}")
    print()


def main():
    parser = argparse.ArgumentParser(description="AutoBot Replay Engine")
    parser.add_argument("pair", nargs="?", default=None)
    parser.add_argument("date", nargs="?", default=None)
    args = parser.parse_args()

    pairs = [args.pair.upper()] if args.pair else sorted(EPIC_MAP.keys())
    dates = None
    if args.date:
        all_csvs = sorted((CANDLE_DIR / pairs[0]).glob("*.csv"))
        dates = [f.stem for f in all_csvs if f.stem <= args.date]

    all_trades = []
    for pair in pairs:
        if not (CANDLE_DIR / pair).exists():
            continue
        print(f"  Replaying {pair}...")
        t = replay_pair(pair, dates)
        all_trades.extend(t)
        print(f"  [{pair}] {len(t)} trades")

    print_results(all_trades)


if __name__ == "__main__":
    main()
