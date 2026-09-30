"""
reversal_sweep.py — REVERSAL_SWEEP strategy.

Two arm paths:
  1. Close-outside: close pushes BB% beyond RS_BB_LOWER/UPPER (defaults 0/100)
     with MACD histogram confirming exhaustion and RSI gate
     (<RS_RSI_OVERSOLD for BUY, >RS_RSI_OVERBOUGHT for SELL).
  2. Wick-sweep: candle wick pierces the band but close returns inside, with
     RSI beyond RS_WICK_RSI_OVERSOLD/OVERBOUGHT. Catches failed-breakout sweeps
     that close-based BB% would miss.
ATR stability (<1.5p over 3 candles) applies to path 1; cooldown applies to both.  Arms once on first touch — subsequent candles still
in the extreme update the extreme price but do NOT reset candles_since.
Entry on 2nd candle after touch closing back inside the band.

SL: touch extreme + 3p buffer.  TP1: +20p, TP2: +40p, trail 20p.
"""
import os
import logging
from typing import Dict, Any, Optional
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from strategy_logic import StrategyDecision

import pandas as pd
import numpy as np

logger = logging.getLogger("reversal_sweep")

REVERSAL_SWEEP_ENABLED = str(os.getenv("REVERSAL_SWEEP_ENABLED", "0")).strip() in ("1", "true", "yes")
REVERSAL_SWEEP_MODE = "REVERSAL_SWEEP"
ALLOWED_PAIRS = set(p.strip().upper() for p in os.getenv("REVERSAL_SWEEP_PAIRS", "GBPUSD").split(",") if p.strip())

# Tunable thresholds
BB_LOWER_THRESHOLD = float(os.getenv("RS_BB_LOWER", "0"))       # BB% below this = lower extreme
BB_UPPER_THRESHOLD = float(os.getenv("RS_BB_UPPER", "100"))     # BB% above this = upper extreme
ATR_EXPANSION_MAX = float(os.getenv("RS_ATR_EXPANSION_MAX", "1.5"))  # max ATR change over 3 candles
RSI_OVERSOLD = float(os.getenv("RS_RSI_OVERSOLD", "40"))        # RSI must be below this for BUY
RSI_OVERBOUGHT = float(os.getenv("RS_RSI_OVERBOUGHT", "60"))    # RSI must be above this for SELL
RSI_WICK_OVERSOLD = float(os.getenv("RS_WICK_RSI_OVERSOLD", "40"))
RSI_WICK_OVERBOUGHT = float(os.getenv("RS_WICK_RSI_OVERBOUGHT", "60"))
COOLDOWN_CANDLES = int(os.getenv("RS_COOLDOWN_CANDLES", "2"))    # min candles between entries (2 x 5min = 10min)
SL_BUFFER_PIPS = float(os.getenv("RS_SL_BUFFER", "3"))
TP1_PIPS = float(os.getenv("RS_TP1", "20"))
TP2_PIPS = float(os.getenv("RS_TP2", "40"))


class ReversalSweepStrategy:
    """BB extreme reversal — enter on 2nd candle after touch confirms reversal."""

    def __init__(self):
        # Per-symbol state: tracks the BB extreme touch
        self._armed = {}  # symbol -> {touch_idx, extreme_price, direction, candles_since}
        self._last_entry_idx = {}  # symbol -> candle index of last entry (for cooldown)

    def evaluate(self, symbol: str, epic: str, df_in: pd.DataFrame,
                 pip_size: float, mid_price: float, briefing: Dict) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        sym = symbol.upper()

        if df_in is None or len(df_in) < 25:
            return self._none(sym, "insufficient_data")

        closes = df_in["close"].astype(float)
        highs = df_in["high"].astype(float)
        lows = df_in["low"].astype(float)

        # Compute indicators from the close series
        bb_mid = closes.rolling(20).mean()
        bb_std = closes.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = bb_upper - bb_lower
        bb_pct = (closes - bb_lower) / bb_width.replace(0, np.nan) * 100

        # MACD histogram (35/45/30)
        ema_fast = closes.ewm(span=35, adjust=False).mean()
        ema_slow = closes.ewm(span=45, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        macd_signal = macd_line.ewm(span=30, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        # ATR
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift(1)).abs(),
            (lows - closes.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        # RSI (14-period Wilder smoothing)
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        # Current candle values
        idx = len(df_in) - 1
        cur_bb_pct = float(bb_pct.iloc[idx]) if not pd.isna(bb_pct.iloc[idx]) else 50.0
        cur_macd_h = float(macd_hist.iloc[idx]) if not pd.isna(macd_hist.iloc[idx]) else 0.0
        cur_atr = float(atr.iloc[idx]) if not pd.isna(atr.iloc[idx]) else 10.0
        cur_rsi = float(rsi.iloc[idx]) if not pd.isna(rsi.iloc[idx]) else 50.0
        atr_3ago = float(atr.iloc[idx - 3]) if idx >= 3 and not pd.isna(atr.iloc[idx - 3]) else cur_atr
        atr_change = cur_atr - atr_3ago
        cur_close = float(closes.iloc[idx])

        state = self._armed.get(sym)

        # --- COOLDOWN CHECK ---
        last_entry = self._last_entry_idx.get(sym, -999)
        if idx - last_entry < COOLDOWN_CANDLES:
            return self._none(sym, "reversal_sweep_cooldown")

        # --- CHECK FOR NEW BB EXTREME TOUCH ---
        is_lower_extreme = cur_bb_pct < BB_LOWER_THRESHOLD
        is_upper_extreme = cur_bb_pct > BB_UPPER_THRESHOLD

        if is_lower_extreme or is_upper_extreme:
            direction = "BUY" if is_lower_extreme else "SELL"

            # Already armed in the same direction — update extreme price but
            # do NOT reset candles_since (fixes re-arming bug).
            if state and state["direction"] == direction:
                new_extreme = float(lows.iloc[idx]) if is_lower_extreme else float(highs.iloc[idx])
                if (direction == "BUY" and new_extreme < state["extreme_price"]) or \
                   (direction == "SELL" and new_extreme > state["extreme_price"]):
                    state["extreme_price"] = new_extreme
                # Fall through to entry check below (don't return early)
            else:
                # RSI filter: must be in oversold/overbought territory
                rsi_ok = (is_lower_extreme and cur_rsi < RSI_OVERSOLD) or \
                         (is_upper_extreme and cur_rsi > RSI_OVERBOUGHT)
                if not rsi_ok:
                    if state:
                        del self._armed[sym]
                    return self._none(sym, f"reversal_sweep_rsi_rejected_{cur_rsi:.1f}")

                # MACD filter: histogram must confirm exhaustion
                # Lower BB touch → MACD histogram should be negative (selling exhaustion)
                # Upper BB touch → MACD histogram should be positive (buying exhaustion)
                macd_aligned = (is_lower_extreme and cur_macd_h < 0) or \
                               (is_upper_extreme and cur_macd_h > 0)

                # ATR filter: volatility should be stable, not accelerating
                atr_stable = atr_change < ATR_EXPANSION_MAX

                if macd_aligned and atr_stable:
                    extreme_price = float(lows.iloc[idx]) if is_lower_extreme else float(highs.iloc[idx])
                    self._armed[sym] = {
                        "touch_idx": idx,
                        "extreme_price": extreme_price,
                        "direction": direction,
                        "candles_since": 0,
                        "bb_pct_at_touch": cur_bb_pct,
                        "macd_at_touch": cur_macd_h,
                        "atr_at_touch": cur_atr,
                        "atr_change": atr_change,
                    }
                    logger.info(
                        f"[REVERSAL-SWEEP] {sym} ARMED {direction} | BB%={cur_bb_pct:.1f} RSI={cur_rsi:.1f} "
                        f"MACD_H={cur_macd_h:.3f} ATR={cur_atr:.1f} ATRchg={atr_change:+.2f}"
                    )
                    return self._none(sym, f"reversal_sweep_armed_{direction.lower()}")

        # --- WICK-SWEEP ARM PATH (wick pierced band, close back inside) ---
        # Runs only if no state was just created by the close-outside path above.
        if self._armed.get(sym) is None:
            cur_high = float(highs.iloc[idx])
            cur_low = float(lows.iloc[idx])
            cur_bb_u = float(bb_upper.iloc[idx]) if not pd.isna(bb_upper.iloc[idx]) else None
            cur_bb_l = float(bb_lower.iloc[idx]) if not pd.isna(bb_lower.iloc[idx]) else None

            wick_upper = (cur_bb_u is not None
                          and cur_high > cur_bb_u
                          and cur_close < cur_bb_u
                          and cur_rsi > RSI_WICK_OVERBOUGHT)
            wick_lower = (cur_bb_l is not None
                          and cur_low < cur_bb_l
                          and cur_close > cur_bb_l
                          and cur_rsi < RSI_WICK_OVERSOLD)

            if wick_upper or wick_lower:
                direction = "SELL" if wick_upper else "BUY"
                extreme_price = cur_high if wick_upper else cur_low
                self._armed[sym] = {
                    "touch_idx": idx,
                    "extreme_price": extreme_price,
                    "direction": direction,
                    "candles_since": 0,
                    "bb_pct_at_touch": cur_bb_pct,
                    "macd_at_touch": cur_macd_h,
                    "atr_at_touch": cur_atr,
                    "atr_change": atr_change,
                    "arm_path": "wick_sweep",
                }
                logger.info(
                    f"[REVERSAL-SWEEP] {sym} ARMED {direction} via WICK_SWEEP | "
                    f"BB%={cur_bb_pct:.1f} RSI={cur_rsi:.1f} MACD_H={cur_macd_h:.3f} "
                    f"extreme={extreme_price:.1f}"
                )
                return self._none(sym, f"reversal_sweep_wick_armed_{direction.lower()}")

        # --- CHECK ARMED STATE FOR ENTRY ---
        if state is not None:
            state["candles_since"] += 1
            candles_since = state["candles_since"]
            direction = state["direction"]
            extreme_price = state["extreme_price"]

            # Update extreme price if price extends further
            if direction == "BUY":
                new_low = float(lows.iloc[idx])
                if new_low < extreme_price:
                    state["extreme_price"] = new_low
                    extreme_price = new_low
            else:
                new_high = float(highs.iloc[idx])
                if new_high > extreme_price:
                    state["extreme_price"] = new_high
                    extreme_price = new_high

            # Expire if too many candles pass (>6 = 30 min)
            if candles_since > 6:
                logger.debug(f"[REVERSAL-SWEEP] {sym} expired after {candles_since} candles")
                del self._armed[sym]
                return self._none(sym, "reversal_sweep_expired")

            # Entry on 2nd candle: must close back inside the BB
            if candles_since >= 2:
                back_inside = (direction == "BUY" and cur_bb_pct > 0) or \
                              (direction == "SELL" and cur_bb_pct < 100)

                if back_inside:
                    # Compute SL from the extreme + buffer
                    if direction == "BUY":
                        sl_pips = (cur_close - extreme_price) + SL_BUFFER_PIPS
                    else:
                        sl_pips = (extreme_price - cur_close) + SL_BUFFER_PIPS

                    sl_pips = max(sl_pips, 5.0)  # minimum 5p SL

                    logger.info(
                        f"[REVERSAL-SWEEP] {sym} ENTRY {direction} @ {cur_close:.1f} | "
                        f"SL={sl_pips:.1f}p TP1={TP1_PIPS}p TP2={TP2_PIPS}p | "
                        f"extreme={extreme_price:.1f} BB%={cur_bb_pct:.1f}"
                    )

                    del self._armed[sym]
                    self._last_entry_idx[sym] = idx  # cooldown
                    return StrategyDecision(
                        symbol=sym,
                        regime="SWEEP",
                        signal=direction,
                        mode=REVERSAL_SWEEP_MODE,
                        entry=mid_price,
                        sl=sl_pips,
                        tp=TP1_PIPS,
                        use_trailing_stop=False,
                        reason=f"reversal_sweep_{direction.lower()}",
                        debug={
                            "entry_source": "reversal_sweep",
                            "bb_pct_at_touch": state["bb_pct_at_touch"],
                            "macd_at_touch": state["macd_at_touch"],
                            "atr_at_touch": state["atr_at_touch"],
                            "atr_change": state["atr_change"],
                            "extreme_price": extreme_price,
                            "candles_to_entry": candles_since,
                            "tp2_pips": TP2_PIPS,
                        },
                    )

        return self._none(sym, "no_signal")

    @staticmethod
    def _none(sym: str, reason: str) -> "StrategyDecision":
        from strategy_logic import StrategyDecision
        return StrategyDecision(
            symbol=sym, regime="DISPATCH", signal="NONE",
            mode=REVERSAL_SWEEP_MODE, entry=None, sl=None, tp=None,
            use_trailing_stop=False, reason=reason,
        )
