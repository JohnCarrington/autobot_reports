"""
exhaustion_reversal.py — EXHAUSTION_REVERSAL strategy.

BUY-only mean-reversion bounce off lower Bollinger extreme when the daily
trend (EMA50 slope) remains bullish. Designed to catch capitulation lows
inside an uptrend that aren't close to any briefing level and so are missed
by REVERSAL_SWEEP, CONTINUATION_SWEEP and BRIEFING_SWEEP.

Arm conditions on the trigger candle:
  - BB% <= ER_BB_PCT_MAX (default 5)
  - RSI3 <= ER_RSI3_MAX (default 10)
  - EMA50 slope > 0 (trend context still bullish)
  - lower wick > ER_WICK_ATR_MULT * ATR14 (default 0.4)
  - close > BB_LOWER (closed back inside band)

Entry: next candle open. SL: trigger low - ER_SL_BUFFER_PIPS. TP1: BB_MID.
"""
import os
import logging
from typing import Dict
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from strategy_logic import StrategyDecision

import pandas as pd
import numpy as np

logger = logging.getLogger("exhaustion_reversal")

EXHAUSTION_REVERSAL_ENABLED = str(os.getenv("EXHAUSTION_REVERSAL_ENABLED", "1")).strip() in ("1", "true", "yes")
EXHAUSTION_REVERSAL_MODE = "EXHAUSTION_REVERSAL"
ALLOWED_PAIRS = set(
    p.strip().upper()
    for p in os.getenv("EXHAUSTION_REVERSAL_PAIRS", "GBPUSD,EURUSD,USDJPY,USDCAD").split(",")
    if p.strip()
)

BB_PCT_MAX = float(os.getenv("ER_BB_PCT_MAX", "5"))
RSI3_MAX = float(os.getenv("ER_RSI3_MAX", "10"))
WICK_ATR_MULT = float(os.getenv("ER_WICK_ATR_MULT", "0.4"))
SL_BUFFER_PIPS = float(os.getenv("ER_SL_BUFFER", "3"))
COOLDOWN_CANDLES = int(os.getenv("ER_COOLDOWN_CANDLES", "6"))


class ExhaustionReversalStrategy:
    def __init__(self):
        self._armed = {}           # sym -> {trigger_idx, trigger_low, bb_mid, bb_pct, rsi3, atr}
        self._last_entry_idx = {}  # sym -> idx

    def evaluate(self, symbol: str, epic: str, df_in: pd.DataFrame,
                 pip_size: float, mid_price: float, briefing: Dict) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        sym = symbol.upper()

        if df_in is None or len(df_in) < 55:
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
        bb_pct = (closes - bb_lower) / bb_width.replace(0, np.nan) * 100

        # RSI3 (Wilder)
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/3, min_periods=3, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/3, min_periods=3, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi3 = 100 - (100 / (1 + rs))

        # ATR14
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift(1)).abs(),
            (lows - closes.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        ema50 = closes.ewm(span=50, adjust=False).mean()

        idx = len(df_in) - 1

        # Cooldown
        last_entry = self._last_entry_idx.get(sym, -999)
        if idx - last_entry < COOLDOWN_CANDLES:
            return self._none(sym, "exhaustion_reversal_cooldown")

        # --- Armed: fire entry on next candle open (this candle) ---
        state = self._armed.get(sym)
        if state is not None:
            # Entry on the candle immediately after the trigger
            if idx == state["trigger_idx"] + 1:
                entry_price = float(opens.iloc[idx])
                trigger_low = state["trigger_low"]
                sl_pips = max((entry_price - trigger_low) / pip_size + SL_BUFFER_PIPS, 5.0)
                tp_pips = max((state["bb_mid"] - entry_price) / pip_size, sl_pips * 1.0)

                logger.info(
                    f"[EXHAUSTION-REVERSAL] {sym} ENTRY BUY @ {entry_price:.1f} | "
                    f"SL={sl_pips:.1f}p TP1={tp_pips:.1f}p (BB_MID) | "
                    f"trigger_low={trigger_low:.1f} BB%={state['bb_pct']:.1f} RSI3={state['rsi3']:.1f}"
                )

                del self._armed[sym]
                self._last_entry_idx[sym] = idx

                return StrategyDecision(
                    symbol=sym,
                    regime="EXHAUSTION",
                    signal="BUY",
                    mode=EXHAUSTION_REVERSAL_MODE,
                    entry=mid_price,
                    sl=sl_pips,
                    tp=tp_pips,
                    use_trailing_stop=False,
                    reason="exhaustion_reversal_buy",
                    debug={
                        "entry_source": "exhaustion_reversal",
                        "trigger_low": trigger_low,
                        "bb_mid": state["bb_mid"],
                        "bb_pct_at_trigger": state["bb_pct"],
                        "rsi3_at_trigger": state["rsi3"],
                        "atr_at_trigger": state["atr"],
                    },
                )
            else:
                # Missed the window — drop the arm
                del self._armed[sym]

        # --- Arm check on current (closed) candle ---
        cur_bb_pct = float(bb_pct.iloc[idx]) if not pd.isna(bb_pct.iloc[idx]) else 50.0
        cur_rsi3 = float(rsi3.iloc[idx]) if not pd.isna(rsi3.iloc[idx]) else 50.0
        cur_low = float(lows.iloc[idx])
        cur_close = float(closes.iloc[idx])
        cur_open = float(opens.iloc[idx])
        cur_atr = float(atr.iloc[idx]) if not pd.isna(atr.iloc[idx]) else 0.0
        cur_bb_l = float(bb_lower.iloc[idx]) if not pd.isna(bb_lower.iloc[idx]) else None
        cur_bb_mid = float(bb_mid.iloc[idx]) if not pd.isna(bb_mid.iloc[idx]) else None
        cur_ema50 = float(ema50.iloc[idx])
        prev_ema50 = float(ema50.iloc[idx - 3]) if idx >= 3 else cur_ema50

        ema50_slope_pos = cur_ema50 > prev_ema50
        lower_wick = min(cur_open, cur_close) - cur_low
        wick_ok = cur_atr > 0 and lower_wick > WICK_ATR_MULT * cur_atr
        close_inside = cur_bb_l is not None and cur_close > cur_bb_l

        if (cur_bb_pct <= BB_PCT_MAX
                and cur_rsi3 <= RSI3_MAX
                and ema50_slope_pos
                and wick_ok
                and close_inside
                and cur_bb_mid is not None):
            self._armed[sym] = {
                "trigger_idx": idx,
                "trigger_low": cur_low,
                "bb_mid": cur_bb_mid,
                "bb_pct": cur_bb_pct,
                "rsi3": cur_rsi3,
                "atr": cur_atr,
            }
            logger.info(
                f"[EXHAUSTION-REVERSAL] {sym} ARMED BUY | BB%={cur_bb_pct:.1f} "
                f"RSI3={cur_rsi3:.1f} wick={lower_wick:.1f} ATR={cur_atr:.1f} "
                f"EMA50_slope=+ bb_mid={cur_bb_mid:.1f}"
            )
            return self._none(sym, "exhaustion_reversal_armed")

        return self._none(sym, "no_signal")

    @staticmethod
    def _none(sym: str, reason: str) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        return StrategyDecision(
            symbol=sym, regime="DISPATCH", signal="NONE",
            mode=EXHAUSTION_REVERSAL_MODE, entry=None, sl=None, tp=None,
            use_trailing_stop=False, reason=reason,
        )
