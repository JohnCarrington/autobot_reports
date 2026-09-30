"""
LondonOpenPullbackStrategy — EMA pullback entry after London open thrust.

Two-phase detection active only 07:00-10:00 BST, GBPUSD initially.

Phase 1 (Armed): Opening thrust detected — one or more candles in first
30 minutes after 07:00 BST with combined move >= 10 pips in one direction.

Phase 2 (Entry): Price pulls back to within 2 pips of the 8 or 13 EMA,
then a candle closes back in the thrust direction with body >= 40% of range
(rejection candle). Entry on the close of the rejection candle.

SL: rejection candle extreme + 3 pip buffer.
TP: briefing levels if available, otherwise fixed 30p.

Bias alignment required: BUY only if BULLISH, SELL only if BEARISH.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from strategy_logic import StrategyDecision

from pair_config import MIN_SL_PIPS as _PAIR_MIN_SL_PIPS

logger = logging.getLogger("AutoBot")

# ---------------------------------------------------------------------------
# ENV-configurable parameters
# ---------------------------------------------------------------------------
LONDON_PULLBACK_ENABLED = str(os.getenv("LONDON_PULLBACK_ENABLED", "0")).strip() in ("1", "true", "yes")
LONDON_PULLBACK_MODE = "LONDON_PULLBACK"

# Window: 07:00-10:00 BST
PULLBACK_WINDOW_START_BST = (7, 0)   # (hour, minute)
PULLBACK_WINDOW_END_BST = (10, 0)

# Phase 1: minimum and maximum thrust size in pips
MIN_THRUST_PIPS = float(os.getenv("LONDON_PULLBACK_MIN_THRUST", "10"))
MAX_THRUST_PIPS = float(os.getenv("LONDON_PULLBACK_MAX_THRUST_PIPS", "20"))
# Thrust detection window: first N candles after 07:00 BST
THRUST_CANDLES = int(os.getenv("LONDON_PULLBACK_THRUST_CANDLES", "6"))

# Phase 2: EMA pullback tolerance
EMA_PULLBACK_PIPS = float(os.getenv("LONDON_PULLBACK_EMA_TOLERANCE", "2"))
# Max candles to wait for pullback after thrust
PULLBACK_WINDOW_CANDLES = int(os.getenv("LONDON_PULLBACK_WINDOW_CANDLES", "6"))
# Min body percentage for rejection candle
MIN_REJECTION_BODY_PCT = float(os.getenv("LONDON_PULLBACK_MIN_REJECTION", "0.40"))

# SL/TP
SL_BUFFER_PIPS = float(os.getenv("LONDON_PULLBACK_SL_BUFFER", "3"))
DEFAULT_TP_PIPS = float(os.getenv("LONDON_PULLBACK_DEFAULT_TP", "30"))

# Pairs
_PAIRS_RAW = os.getenv("LONDON_PULLBACK_PAIRS", "GBPUSD").strip()
ALLOWED_PAIRS = set(p.strip().upper() for p in _PAIRS_RAW.split(",") if p.strip())


def _pair_from_epic(epic: str) -> str:
    parts = epic.split(".")
    return parts[2] if len(parts) >= 3 else epic.upper()


def _is_bst(ts) -> bool:
    """Rough BST check: April-October, or late March."""
    month = ts.month if hasattr(ts, "month") else 1
    day = ts.day if hasattr(ts, "day") else 1
    return month >= 4 or (month == 3 and day >= 29)


def _to_bst_minutes(ts) -> int:
    """Convert timestamp to BST minutes since midnight."""
    utc_h = ts.hour if hasattr(ts, "hour") else 0
    utc_m = ts.minute if hasattr(ts, "minute") else 0
    bst_h = utc_h + (1 if _is_bst(ts) else 0)
    return bst_h * 60 + utc_m


class LondonOpenPullbackStrategy:
    """EMA pullback entry after London open thrust."""

    def __init__(self) -> None:
        # Armed state per epic
        # {epic: {direction, thrust_end_idx, thrust_pips, candles_since, date}}
        self._armed: Dict[str, Dict[str, Any]] = {}
        # One trade per day per epic
        self._fired: Dict[str, bool] = {}

    def evaluate(
        self,
        symbol: str,
        epic: str,
        df_in,  # pandas DataFrame with indicators
        pip_size: float,
        mid_price: float,
        briefing: Optional[Dict[str, Any]],
    ) -> StrategyDecision:
        sym = str(symbol).upper()

        if sym not in ALLOWED_PAIRS:
            return self._none(sym, "pullback_pair_not_allowed")

        if briefing is None:
            return self._none(sym, "pullback_no_briefing")

        if df_in is None or len(df_in) < 20:
            return self._none(sym, "pullback_insufficient_data")

        # --- Bias filter (session_bias only) ---
        # Composite session+daily veto removed — daily_bias is the D1 multi-day
        # trend and intentionally allowed to disagree with session_bias.
        bias = str(briefing.get("session_bias", "")).upper()
        if bias not in ("BULLISH", "BEARISH"):
            self._armed.pop(epic, None)
            return self._none(sym, "pullback_no_bias")

        direction = "BUY" if bias == "BULLISH" else "SELL"

        # --- Time window check: 07:00-10:00 BST ---
        last_row = df_in.iloc[-1]
        ts = last_row.get("timestamp")
        if ts is None:
            return self._none(sym, "pullback_no_timestamp")

        bst_min = _to_bst_minutes(ts)
        window_start = PULLBACK_WINDOW_START_BST[0] * 60 + PULLBACK_WINDOW_START_BST[1]
        window_end = PULLBACK_WINDOW_END_BST[0] * 60 + PULLBACK_WINDOW_END_BST[1]

        if bst_min < window_start or bst_min >= window_end:
            return self._none(sym, "pullback_outside_window")

        # One trade per day
        day_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        fire_key = f"{sym}_{day_str}"
        if fire_key in self._fired:
            return self._none(sym, "pullback_already_fired_today")

        # =================================================================
        # PHASE 2: if armed, check for EMA pullback + rejection
        # =================================================================
        armed = self._armed.get(epic)
        if armed is not None and armed["direction"] == direction and armed["date"] == day_str:
            armed["candles_since"] += 1

            if armed["candles_since"] > PULLBACK_WINDOW_CANDLES:
                logger.info(
                    "[LONDON-PULLBACK] %s %s pullback window expired after %d candles",
                    sym, direction, armed["candles_since"],
                )
                self._armed.pop(epic, None)
                return self._none(sym, "pullback_window_expired")

            close = float(last_row.get("close", 0))
            high = float(last_row.get("high", 0))
            low = float(last_row.get("low", 0))
            open_ = float(last_row.get("open", 0))

            # Get EMA 8 and 13
            ema8 = ema13 = None
            if "EMA_8" in last_row.index:
                v = last_row["EMA_8"]
                if v is not None and v == v:
                    ema8 = float(v)
            if "EMA_13" in last_row.index:
                v = last_row["EMA_13"]
                if v is not None and v == v:
                    ema13 = float(v)

            if ema8 is None and ema13 is None:
                return self._none(sym, "pullback_no_ema")

            # Check pullback to EMA: price within tolerance of EMA 8 or 13
            tol = EMA_PULLBACK_PIPS * pip_size
            near_ema = False
            ema_touched = None

            if direction == "BUY":
                # Pullback down to EMA — low touches EMA
                if ema8 is not None and low <= ema8 + tol:
                    near_ema = True
                    ema_touched = ("EMA_8", ema8)
                elif ema13 is not None and low <= ema13 + tol:
                    near_ema = True
                    ema_touched = ("EMA_13", ema13)
            else:
                # Pullback up to EMA — high touches EMA
                if ema8 is not None and high >= ema8 - tol:
                    near_ema = True
                    ema_touched = ("EMA_8", ema8)
                elif ema13 is not None and high >= ema13 - tol:
                    near_ema = True
                    ema_touched = ("EMA_13", ema13)

            if not near_ema:
                return self._none(sym, f"pullback_waiting_{armed['candles_since']}")

            # Check rejection: body in thrust direction, body >= 40% of range
            c_range = high - low
            if c_range <= 0:
                return self._none(sym, "pullback_zero_range")

            c_body = abs(close - open_)
            c_body_pct = c_body / c_range

            is_rejection = False
            if direction == "BUY" and close > open_ and c_body_pct >= MIN_REJECTION_BODY_PCT:
                is_rejection = True
            elif direction == "SELL" and close < open_ and c_body_pct >= MIN_REJECTION_BODY_PCT:
                is_rejection = True

            if not is_rejection:
                return self._none(sym, f"pullback_ema_touch_no_rejection_{armed['candles_since']}")

            # --- ENTRY ---
            self._armed.pop(epic, None)
            self._fired[fire_key] = True

            pair = _pair_from_epic(epic)
            min_sl = _PAIR_MIN_SL_PIPS.get(pair, 0)
            buffer = SL_BUFFER_PIPS * pip_size

            if direction == "BUY":
                sl_price = low - buffer
                sl_pips = max(abs(mid_price - sl_price) / pip_size, min_sl)
            else:
                sl_price = high + buffer
                sl_pips = max(abs(sl_price - mid_price) / pip_size, min_sl)

            tp_pips = self._find_tp(direction, mid_price, sl_pips, briefing, pip_size)

            logger.info(
                "[LONDON-PULLBACK] %s %s ENTRY | thrust=%.1fp | %s=%.1f | "
                "rejection body=%.0f%% | SL=%.1f TP=%.1f",
                sym, direction, armed["thrust_pips"],
                ema_touched[0], ema_touched[1],
                c_body_pct * 100, sl_pips, tp_pips,
            )

            return StrategyDecision(
                symbol=sym,
                regime="PULLBACK",
                signal=direction,
                mode=LONDON_PULLBACK_MODE,
                entry=float(mid_price),
                sl=float(sl_pips),
                tp=float(tp_pips),
                use_trailing_stop=True,
                reason=f"london_pullback_{direction.lower()}",
                debug={
                    "thrust_pips": armed["thrust_pips"],
                    "ema_touched": ema_touched[0],
                    "ema_value": ema_touched[1],
                    "rejection_body_pct": round(c_body_pct, 3),
                    "rejection_high": high,
                    "rejection_low": low,
                    "candles_to_pullback": armed["candles_since"],
                    "sl_pips": round(sl_pips, 2),
                    "tp_pips": round(tp_pips, 2),
                },
            )

        # =================================================================
        # PHASE 1: detect opening thrust
        # =================================================================
        # Only arm in first 30 minutes after window start (07:00-07:30 BST)
        thrust_end_bst = window_start + 30
        if bst_min >= thrust_end_bst:
            return self._none(sym, "pullback_past_thrust_window")

        # Already armed for today? Don't re-arm
        if armed is not None and armed.get("date") == day_str:
            return self._none(sym, "pullback_already_armed")

        # Look at recent candles within the thrust window
        # Find candles since window start
        thrust_candles = []
        for idx in range(max(0, len(df_in) - THRUST_CANDLES), len(df_in)):
            row = df_in.iloc[idx]
            row_ts = row.get("timestamp")
            if row_ts is not None:
                row_bst = _to_bst_minutes(row_ts)
                if row_bst >= window_start:
                    thrust_candles.append(row)

        if len(thrust_candles) < 2:
            return self._none(sym, "pullback_thrust_building")

        # Calculate combined move
        first_open = float(thrust_candles[0].get("open", 0))
        last_close = float(thrust_candles[-1].get("close", 0))
        move = last_close - first_open
        move_pips = abs(move) / pip_size

        if move_pips < MIN_THRUST_PIPS:
            return self._none(sym, f"pullback_thrust_too_small_{move_pips:.1f}p")

        if move_pips > MAX_THRUST_PIPS:
            logger.info(
                "[LONDON-PULLBACK] %s thrust %.1fp exceeds max %.1fp — overextended, blocking",
                sym, move_pips, MAX_THRUST_PIPS,
            )
            return self._none(sym, f"pullback_thrust_overextended_{move_pips:.1f}p")

        # Determine thrust direction
        thrust_dir = "BUY" if move > 0 else "SELL"

        # Must match bias
        if thrust_dir != direction:
            return self._none(sym, "pullback_thrust_against_bias")

        # ARM
        self._armed[epic] = {
            "direction": thrust_dir,
            "thrust_pips": round(move_pips, 1),
            "candles_since": 0,
            "date": day_str,
        }
        logger.info(
            "[LONDON-PULLBACK] %s %s ARMED — thrust %.1fp over %d candles, "
            "waiting for EMA pullback + rejection",
            sym, thrust_dir, move_pips, len(thrust_candles),
        )
        return self._none(sym, "pullback_armed")

    # ------------------------------------------------------------------
    def _find_tp(
        self,
        direction: str,
        entry: float,
        sl_pips: float,
        briefing: Optional[Dict[str, Any]],
        pip_size: float,
    ) -> float:
        """Find TP from briefing levels, fallback to default."""
        levels: List[float] = []
        if briefing is not None:
            kl = briefing.get("key_levels") or {}
            ml = briefing.get("major_levels") or {}
            lp = briefing.get("liquidity_pools") or {}
            if direction == "SELL":
                for src in (kl.get("support", []), ml.get("support", []), lp.get("sell_side", [])):
                    for p in src:
                        try: levels.append(float(p))
                        except (TypeError, ValueError): pass
            else:
                for src in (kl.get("resistance", []), ml.get("resistance", []), lp.get("buy_side", [])):
                    for p in src:
                        try: levels.append(float(p))
                        except (TypeError, ValueError): pass

        if direction == "SELL":
            candidates = sorted([lv for lv in levels if lv < entry], reverse=True)
        else:
            candidates = sorted([lv for lv in levels if lv > entry])

        for price in candidates:
            dist_pips = abs(entry - price) / pip_size
            if dist_pips >= sl_pips:
                return round(dist_pips, 2)

        return DEFAULT_TP_PIPS

    # ------------------------------------------------------------------
    @staticmethod
    def _none(sym: str, reason: str) -> StrategyDecision:
        return StrategyDecision(
            symbol=sym,
            regime="PULLBACK",
            signal="NONE",
            mode=LONDON_PULLBACK_MODE,
            entry=None,
            sl=None,
            tp=None,
            use_trailing_stop=False,
            reason=reason,
        )
