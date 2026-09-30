"""
session_impulse_breakout.py — SESSION_IMPULSE_BREAKOUT strategy.

Catches single-bar impulse breakouts where the EMA stack flips direction
within 1-2 candles and price closes outside the Bollinger band with BB
width expanding. Active only during London (06:00-11:00 UTC) and NY
(12:00-17:00 UTC) sessions.

Arm conditions on trigger candle close:
  - BB% crosses above 100 (BUY) or below 0 (SELL)
  - EMA8/13/21 stack flipped direction within the last 2 candles
    (prior stack was bearish/mixed for BUY, bullish/mixed for SELL)
  - BB width > SIB_WIDTH_MULT × its 10-bar average
  - MACD_HIST delta > 0 (BUY) or < 0 (SELL)

Entry: next candle open. SL: trigger low (BUY) / trigger high (SELL) + buffer.
TP1: BB midline. TP2: 2× distance from entry to BB midline.
"""
import os
import logging
from typing import Dict
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from strategy_logic import StrategyDecision

import pandas as pd
import numpy as np

logger = logging.getLogger("session_impulse_breakout")

SESSION_IMPULSE_BREAKOUT_ENABLED = str(os.getenv("SESSION_IMPULSE_BREAKOUT_ENABLED", "1")).strip() in ("1", "true", "yes")
SESSION_IMPULSE_BREAKOUT_MODE = "SESSION_IMPULSE_BREAKOUT"
ALLOWED_PAIRS = set(
    p.strip().upper()
    for p in os.getenv("SESSION_IMPULSE_BREAKOUT_PAIRS", "GBPUSD,EURUSD,USDJPY,USDCAD").split(",")
    if p.strip()
)

WIDTH_MULT = float(os.getenv("SIB_WIDTH_MULT", "1.2"))
STACK_FLIP_LOOKBACK = int(os.getenv("SIB_STACK_FLIP_LOOKBACK", "2"))
SL_BUFFER_PIPS = float(os.getenv("SIB_SL_BUFFER", "2"))
COOLDOWN_CANDLES = int(os.getenv("SIB_COOLDOWN_CANDLES", "6"))

# Session windows (UTC). Hour-minute tuples, inclusive start / exclusive end.
LONDON_START = (6, 0)
LONDON_END = (11, 0)
NY_START = (12, 0)
NY_END = (17, 0)


def _in_session(ts: pd.Timestamp) -> bool:
    if ts is None:
        return False
    try:
        t = ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")
    except Exception:
        t = ts
    hm = (t.hour, t.minute)
    return (LONDON_START <= hm < LONDON_END) or (NY_START <= hm < NY_END)


def _stack_sign(e8: float, e13: float, e21: float) -> int:
    """+1 bullish (8>13>21), -1 bearish (8<13<21), 0 mixed."""
    if e8 > e13 > e21:
        return 1
    if e8 < e13 < e21:
        return -1
    return 0


class SessionImpulseBreakoutStrategy:
    def __init__(self):
        self._armed = {}           # sym -> arm state
        self._last_entry_idx = {}  # sym -> idx

    def evaluate(self, symbol: str, epic: str, df_in: pd.DataFrame,
                 pip_size: float, mid_price: float, briefing: Dict) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        sym = symbol.upper()

        if df_in is None or len(df_in) < 25:
            return self._none(sym, "insufficient_data")

        closes = df_in["close"].astype(float)
        highs = df_in["high"].astype(float)
        lows = df_in["low"].astype(float)
        opens = df_in["open"].astype(float)

        # Indicators
        bb_mid = closes.rolling(20).mean()
        bb_std = closes.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = bb_upper - bb_lower
        bb_width_avg10 = bb_width.rolling(10).mean()
        bb_pct = (closes - bb_lower) / bb_width.replace(0, np.nan) * 100

        ema8 = closes.ewm(span=8, adjust=False).mean()
        ema13 = closes.ewm(span=13, adjust=False).mean()
        ema21 = closes.ewm(span=21, adjust=False).mean()

        # MACD histogram (35/45/30) and its delta
        macd_line = closes.ewm(span=35, adjust=False).mean() - closes.ewm(span=45, adjust=False).mean()
        macd_signal = macd_line.ewm(span=30, adjust=False).mean()
        macd_hist = macd_line - macd_signal
        macd_hist_delta = macd_hist.diff()

        idx = len(df_in) - 1

        # Session filter. Prefer df timestamp if present & parseable, else
        # fall back to current UTC wall-clock (tick-driven evaluation).
        ts_latest = None
        try:
            ts_col = df_in["timestamp"] if "timestamp" in df_in.columns else None
            if ts_col is not None:
                ts_latest = pd.to_datetime(ts_col.iloc[idx], utc=True, errors="coerce")
                if pd.isna(ts_latest):
                    ts_latest = None
        except Exception:
            ts_latest = None
        if ts_latest is None:
            from datetime import datetime as _dt, timezone as _tz
            ts_latest = pd.Timestamp(_dt.now(_tz.utc))
        if not _in_session(ts_latest):
            return self._none(sym, "out_of_session")

        # Cooldown
        last_entry = self._last_entry_idx.get(sym, -999)
        if idx - last_entry < COOLDOWN_CANDLES:
            return self._none(sym, "sib_cooldown")

        # --- Armed → fire entry on next candle open ---
        state = self._armed.get(sym)
        if state is not None:
            if idx == state["trigger_idx"] + 1:
                direction = state["direction"]
                entry_price = float(opens.iloc[idx])
                bb_mid_trig = state["bb_mid"]

                if direction == "BUY":
                    sl_price = state["trigger_low"] - SL_BUFFER_PIPS * pip_size
                    sl_pips = max((entry_price - sl_price) / pip_size, 5.0)
                    tp1_pips = max((bb_mid_trig - entry_price) / pip_size, sl_pips)
                else:
                    sl_price = state["trigger_high"] + SL_BUFFER_PIPS * pip_size
                    sl_pips = max((sl_price - entry_price) / pip_size, 5.0)
                    tp1_pips = max((entry_price - bb_mid_trig) / pip_size, sl_pips)

                tp2_pips = tp1_pips * 2.0

                logger.info(
                    f"[SESSION-IMPULSE-BREAKOUT] {sym} ENTRY {direction} @ {entry_price:.1f} | "
                    f"SL={sl_pips:.1f}p TP1={tp1_pips:.1f}p TP2={tp2_pips:.1f}p | "
                    f"trigger BB%={state['bb_pct']:.1f} width_ratio={state['width_ratio']:.2f}"
                )

                del self._armed[sym]
                self._last_entry_idx[sym] = idx

                return StrategyDecision(
                    symbol=sym,
                    regime="BREAKOUT",
                    signal=direction,
                    mode=SESSION_IMPULSE_BREAKOUT_MODE,
                    entry=mid_price,
                    sl=sl_pips,
                    tp=tp1_pips,
                    use_trailing_stop=False,
                    reason=f"session_impulse_breakout_{direction.lower()}",
                    debug={
                        "entry_source": "session_impulse_breakout",
                        "bb_pct_at_trigger": state["bb_pct"],
                        "width_ratio": state["width_ratio"],
                        "macd_hist_delta": state["macd_hist_delta"],
                        "bb_mid_at_trigger": bb_mid_trig,
                        "tp1_source": "bb_mid",
                        "tp2_pips": tp2_pips,
                    },
                )
            else:
                # Missed the entry window
                del self._armed[sym]

        # --- Arm check on current (closed) candle ---
        cur_bb_pct = float(bb_pct.iloc[idx]) if not pd.isna(bb_pct.iloc[idx]) else 50.0
        cur_width = float(bb_width.iloc[idx]) if not pd.isna(bb_width.iloc[idx]) else None
        cur_width_avg = float(bb_width_avg10.iloc[idx]) if not pd.isna(bb_width_avg10.iloc[idx]) else None
        cur_macd_hd = float(macd_hist_delta.iloc[idx]) if not pd.isna(macd_hist_delta.iloc[idx]) else 0.0
        cur_bb_mid = float(bb_mid.iloc[idx]) if not pd.isna(bb_mid.iloc[idx]) else None
        cur_high = float(highs.iloc[idx])
        cur_low = float(lows.iloc[idx])

        if cur_width is None or cur_width_avg is None or cur_bb_mid is None or cur_width_avg <= 0:
            return self._none(sym, "no_signal")

        width_ratio = cur_width / cur_width_avg
        width_expanding = width_ratio > WIDTH_MULT

        # Stack flip check — current sign vs any of the prior STACK_FLIP_LOOKBACK candles
        cur_sign = _stack_sign(float(ema8.iloc[idx]), float(ema13.iloc[idx]), float(ema21.iloc[idx]))
        flipped_from_bearish = False
        flipped_from_bullish = False
        for k in range(1, STACK_FLIP_LOOKBACK + 1):
            j = idx - k
            if j < 0:
                break
            prev_sign = _stack_sign(float(ema8.iloc[j]), float(ema13.iloc[j]), float(ema21.iloc[j]))
            if cur_sign == 1 and prev_sign <= 0 and prev_sign != 1:
                flipped_from_bearish = True
            if cur_sign == -1 and prev_sign >= 0 and prev_sign != -1:
                flipped_from_bullish = True

        buy_ok = (cur_bb_pct > 100
                  and cur_sign == 1
                  and flipped_from_bearish
                  and width_expanding
                  and cur_macd_hd > 0)
        sell_ok = (cur_bb_pct < 0
                   and cur_sign == -1
                   and flipped_from_bullish
                   and width_expanding
                   and cur_macd_hd < 0)

        if buy_ok or sell_ok:
            direction = "BUY" if buy_ok else "SELL"
            self._armed[sym] = {
                "trigger_idx": idx,
                "direction": direction,
                "trigger_low": cur_low,
                "trigger_high": cur_high,
                "bb_mid": cur_bb_mid,
                "bb_pct": cur_bb_pct,
                "width_ratio": width_ratio,
                "macd_hist_delta": cur_macd_hd,
            }
            logger.info(
                f"[SESSION-IMPULSE-BREAKOUT] {sym} ARMED {direction} | "
                f"BB%={cur_bb_pct:.1f} width_ratio={width_ratio:.2f} "
                f"MACD_HD={cur_macd_hd:+.3f} stack_flipped_within={STACK_FLIP_LOOKBACK}"
            )
            return self._none(sym, f"sib_armed_{direction.lower()}")

        return self._none(sym, "no_signal")

    @staticmethod
    def _none(sym: str, reason: str) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        return StrategyDecision(
            symbol=sym, regime="DISPATCH", signal="NONE",
            mode=SESSION_IMPULSE_BREAKOUT_MODE, entry=None, sl=None, tp=None,
            use_trailing_stop=False, reason=reason,
        )
