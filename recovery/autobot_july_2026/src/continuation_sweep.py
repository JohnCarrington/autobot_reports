"""
continuation_sweep.py — CONTINUATION_SWEEP strategy.

Fires when price touches a BB extreme (BB% < -5 or > 105) but MACD histogram
is AGAINST the touch direction (positive at lower BB = trend still driving)
and ATR is expanding (> +0.5p over 3 candles). Entry on 1st candle making a
new extreme beyond the touch.

SL: touch opposite extreme + 3p buffer.  TP: +20p fixed, time stop 60min.
"""
import os
import logging
from typing import Dict, Any, Optional
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from strategy_logic import StrategyDecision

import pandas as pd
import numpy as np

logger = logging.getLogger("continuation_sweep")

CONTINUATION_SWEEP_ENABLED = str(os.getenv("CONTINUATION_SWEEP_ENABLED", "0")).strip() in ("1", "true", "yes")
CONTINUATION_SWEEP_MODE = "CONTINUATION_SWEEP"
ALLOWED_PAIRS = set(p.strip().upper() for p in os.getenv("CONTINUATION_SWEEP_PAIRS", "GBPUSD").split(",") if p.strip())

# Tunable thresholds
BB_LOWER_THRESHOLD = float(os.getenv("CS_BB_LOWER", "-5"))
BB_UPPER_THRESHOLD = float(os.getenv("CS_BB_UPPER", "105"))
ATR_EXPANSION_MIN = float(os.getenv("CS_ATR_EXPANSION_MIN", "0.5"))
SL_BUFFER_PIPS = float(os.getenv("CS_SL_BUFFER", "3"))
TP_PIPS = float(os.getenv("CS_TP", "20"))


class ContinuationSweepStrategy:
    """BB extreme continuation — enter when trend punches through the band."""

    def __init__(self):
        self._armed = {}  # symbol -> {touch_idx, touch_high, touch_low, direction, candles_since}

    def evaluate(self, symbol: str, epic: str, df_in: pd.DataFrame,
                 pip_size: float, mid_price: float, briefing: Dict) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        sym = symbol.upper()

        if df_in is None or len(df_in) < 25:
            return self._none(sym, "insufficient_data")

        closes = df_in["close"].astype(float)
        highs = df_in["high"].astype(float)
        lows = df_in["low"].astype(float)

        # Compute indicators
        bb_mid = closes.rolling(20).mean()
        bb_std = closes.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = bb_upper - bb_lower
        bb_pct = (closes - bb_lower) / bb_width.replace(0, np.nan) * 100

        ema_fast = closes.ewm(span=35, adjust=False).mean()
        ema_slow = closes.ewm(span=45, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        macd_signal = macd_line.ewm(span=30, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        tr = pd.concat([
            highs - lows,
            (highs - closes.shift(1)).abs(),
            (lows - closes.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        idx = len(df_in) - 1
        cur_bb_pct = float(bb_pct.iloc[idx]) if not pd.isna(bb_pct.iloc[idx]) else 50.0
        cur_macd_h = float(macd_hist.iloc[idx]) if not pd.isna(macd_hist.iloc[idx]) else 0.0
        cur_atr = float(atr.iloc[idx]) if not pd.isna(atr.iloc[idx]) else 10.0
        atr_3ago = float(atr.iloc[idx - 3]) if idx >= 3 and not pd.isna(atr.iloc[idx - 3]) else cur_atr
        atr_change = cur_atr - atr_3ago
        cur_close = float(closes.iloc[idx])
        cur_low = float(lows.iloc[idx])
        cur_high = float(highs.iloc[idx])

        state = self._armed.get(sym)

        # --- CHECK FOR NEW BB EXTREME TOUCH ---
        is_lower_extreme = cur_bb_pct < BB_LOWER_THRESHOLD
        is_upper_extreme = cur_bb_pct > BB_UPPER_THRESHOLD

        if is_lower_extreme or is_upper_extreme:
            # Continuation: MACD histogram is AGAINST the touch direction
            # Lower BB touch with positive MACD → trend still driving down (histogram hasn't caught up)
            # Upper BB touch with negative MACD → trend still driving up
            macd_against = (is_lower_extreme and cur_macd_h > 0) or \
                           (is_upper_extreme and cur_macd_h < 0)

            # ATR must be expanding — volatility accelerating
            atr_expanding = atr_change > ATR_EXPANSION_MIN

            if macd_against and atr_expanding:
                # Direction is WITH the trend (SELL for lower BB, BUY for upper BB)
                direction = "SELL" if is_lower_extreme else "BUY"
                self._armed[sym] = {
                    "touch_idx": idx,
                    "touch_low": cur_low,
                    "touch_high": cur_high,
                    "direction": direction,
                    "candles_since": 0,
                    "bb_pct_at_touch": cur_bb_pct,
                    "macd_at_touch": cur_macd_h,
                    "atr_at_touch": cur_atr,
                    "atr_change": atr_change,
                }
                logger.info(
                    f"[CONTINUATION-SWEEP] {sym} ARMED {direction} | BB%={cur_bb_pct:.1f} "
                    f"MACD_H={cur_macd_h:+.3f} ATR={cur_atr:.1f} ATRchg={atr_change:+.2f}"
                )
                return self._none(sym, f"continuation_sweep_armed_{direction.lower()}")

        # --- CHECK ARMED STATE FOR ENTRY ---
        if state is not None:
            state["candles_since"] += 1
            candles_since = state["candles_since"]
            direction = state["direction"]

            # Expire if too many candles (>4 = 20 min)
            if candles_since > 4:
                logger.debug(f"[CONTINUATION-SWEEP] {sym} expired after {candles_since} candles")
                del self._armed[sym]
                return self._none(sym, "continuation_sweep_expired")

            # Entry on 1st candle making a new extreme beyond the touch
            new_extreme = False
            if direction == "SELL" and cur_low < state["touch_low"]:
                new_extreme = True
            elif direction == "BUY" and cur_high > state["touch_high"]:
                new_extreme = True

            if new_extreme:
                session_bias = str((briefing or {}).get("session_bias", "")).upper()
                if direction == "SELL" and session_bias == "BULLISH":
                    logger.info(
                        f"[CONTINUATION-SWEEP] {sym} ENTRY SELL blocked — session_bias=BULLISH opposes signal"
                    )
                    del self._armed[sym]
                    return self._none(sym, "continuation_sweep_blocked_bias")
                if direction == "BUY" and session_bias == "BEARISH":
                    logger.info(
                        f"[CONTINUATION-SWEEP] {sym} ENTRY BUY blocked — session_bias=BEARISH opposes signal"
                    )
                    del self._armed[sym]
                    return self._none(sym, "continuation_sweep_blocked_bias")

                # SL: opposite side of the touch candle + buffer
                if direction == "SELL":
                    sl_price = state["touch_high"]
                    sl_pips = (sl_price - cur_close) + SL_BUFFER_PIPS
                else:
                    sl_price = state["touch_low"]
                    sl_pips = (cur_close - sl_price) + SL_BUFFER_PIPS

                sl_pips = max(sl_pips, 8.0)  # minimum 8p SL for continuation trades

                logger.info(
                    f"[CONTINUATION-SWEEP] {sym} ENTRY {direction} @ {cur_close:.1f} | "
                    f"SL={sl_pips:.1f}p TP={TP_PIPS}p | "
                    f"BB%={cur_bb_pct:.1f} new_extreme confirmed"
                )

                del self._armed[sym]
                return StrategyDecision(
                    symbol=sym,
                    regime="SWEEP",
                    signal=direction,
                    mode=CONTINUATION_SWEEP_MODE,
                    entry=mid_price,
                    sl=sl_pips,
                    tp=TP_PIPS,
                    use_trailing_stop=False,
                    reason=f"continuation_sweep_{direction.lower()}",
                    debug={
                        "entry_source": "continuation_sweep",
                        "bb_pct_at_touch": state["bb_pct_at_touch"],
                        "macd_at_touch": state["macd_at_touch"],
                        "atr_at_touch": state["atr_at_touch"],
                        "atr_change": state["atr_change"],
                        "touch_high": state["touch_high"],
                        "touch_low": state["touch_low"],
                        "candles_to_entry": candles_since,
                        "time_stop_minutes": 60,
                    },
                )

        return self._none(sym, "no_signal")

    @staticmethod
    def _none(sym: str, reason: str) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        return StrategyDecision(
            symbol=sym, regime="DISPATCH", signal="NONE",
            mode=CONTINUATION_SWEEP_MODE, entry=None, sl=None, tp=None,
            use_trailing_stop=False, reason=reason,
        )
