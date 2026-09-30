"""
BriefingHuntStrategy — Enter after briefing-predicted liquidity sweep completes.

Tick-level: monitors price for touch/pierce of briefing liquidity_pools levels.
5M-level: confirms reversal with rejection candle + MACD compression.

BEARISH bias → monitors buy_side levels (sweep up, reverse down → SELL)
BULLISH bias → monitors sell_side levels (sweep down, reverse up → BUY)
NEUTRAL → blocked entirely.

Phase 1 (Tick — Armed): price touches or pierces a liquidity pool level.
Phase 2 (5M — Entry): within 6 candles, rejection candle closes away from
sweep level with body >= 50% of range, MACD histogram compressing or lines
converging in reversal direction. Entry on confirmation candle close.

SL: sweep extreme + 3 pip buffer.
TP: briefing trading_plans target > major_levels > fixed 40p.
Active: 06:45-17:00 BST.
"""

from __future__ import annotations

import logging
import os
import time as _time
from typing import Any, Dict, List, Optional

from strategy_logic import StrategyDecision, _pick_macd_hist

from pair_config import MIN_SL_PIPS as _PAIR_MIN_SL_PIPS

logger = logging.getLogger("AutoBot")

# ---------------------------------------------------------------------------
# ENV-configurable parameters
# ---------------------------------------------------------------------------
BRIEFING_HUNT_ENABLED = str(os.getenv("BRIEFING_HUNT_ENABLED", "1")).strip() in ("1", "true", "yes")
BRIEFING_HUNT_MODE = "BRIEFING_HUNT"

_PAIRS_RAW = os.getenv("BRIEFING_HUNT_PAIRS", "GBPUSD").strip()
ALLOWED_PAIRS = set(p.strip().upper() for p in _PAIRS_RAW.split(",") if p.strip())

# Window: 06:45-17:00 BST
WINDOW_START_BST = (6, 45)
WINDOW_END_BST = (17, 0)

# Phase 2 parameters
CONFIRMATION_WINDOW = int(os.getenv("BRIEFING_HUNT_CONFIRMATION_WINDOW", "6"))
MIN_REJECTION_BODY_PCT = float(os.getenv("BRIEFING_HUNT_MIN_REJECTION_PCT", "0.50"))
SL_BUFFER_PIPS = float(os.getenv("BRIEFING_HUNT_SL_BUFFER", "3"))
DEFAULT_TP_PIPS = float(os.getenv("BRIEFING_HUNT_DEFAULT_TP", "40"))

# MACD convergence threshold
MACD_CONVERGENCE = float(os.getenv("BRIEFING_HUNT_MACD_CONVERGENCE", "1.5"))

# MACD keys
_MACD_FAST = int(float(os.getenv("MACD_FAST", "35") or 35))
_MACD_SLOW = int(float(os.getenv("MACD_SLOW", "45") or 45))
_MACD_SIGNAL = int(float(os.getenv("MACD_SIGNAL", "30") or 30))
_MACD_LINE_KEY = f"MACD_{_MACD_FAST}_{_MACD_SLOW}"
_MACD_SIG_KEY = f"MACD_SIGNAL_{_MACD_FAST}_{_MACD_SLOW}_{_MACD_SIGNAL}"


def _pair_from_epic(epic: str) -> str:
    parts = epic.split(".")
    return parts[2] if len(parts) >= 3 else epic.upper()


def _is_bst(ts) -> bool:
    month = ts.month if hasattr(ts, "month") else 1
    day = ts.day if hasattr(ts, "day") else 1
    return month >= 4 or (month == 3 and day >= 29)


def _to_bst_minutes(ts) -> int:
    utc_h = ts.hour if hasattr(ts, "hour") else 0
    utc_m = ts.minute if hasattr(ts, "minute") else 0
    bst_h = utc_h + (1 if _is_bst(ts) else 0)
    return bst_h * 60 + utc_m


def _get_macd_lines(ind: dict) -> tuple:
    m = s = None
    for k in (_MACD_LINE_KEY, "MACD"):
        v = ind.get(k)
        if v is not None:
            try:
                fv = float(v)
                if fv == fv:
                    m = fv; break
            except (TypeError, ValueError):
                pass
    for k in (_MACD_SIG_KEY, "MACD_SIGNAL"):
        v = ind.get(k)
        if v is not None:
            try:
                fv = float(v)
                if fv == fv:
                    s = fv; break
            except (TypeError, ValueError):
                pass
    return m, s


class BriefingHuntStrategy:
    """Enter after briefing-predicted liquidity sweep completes."""

    def __init__(self) -> None:
        # Armed state: {epic: {direction, sweep_level, sweep_extreme, candles_since, date, ...}}
        self._armed: Dict[str, Dict[str, Any]] = {}
        # One entry per session per epic
        self._fired: Dict[str, bool] = {}

    def evaluate(
        self,
        symbol: str,
        epic: str,
        mid_price: float,
        pip_size: float,
        briefing: Optional[Dict[str, Any]],
        is_new_5m: bool,
        rc_all: Optional[list] = None,
    ) -> StrategyDecision:
        sym = str(symbol).upper()

        if sym not in ALLOWED_PAIRS:
            return self._none(sym, "hunt_pair_not_allowed")

        if briefing is None:
            return self._none(sym, "hunt_no_briefing")

        # --- Bias filter (session_bias only) ---
        # Composite session+daily veto removed — daily_bias is the D1 multi-day
        # trend and intentionally allowed to disagree with session_bias.
        bias = str(briefing.get("session_bias", "")).upper()
        if bias not in ("BULLISH", "BEARISH"):
            self._armed.pop(epic, None)
            return self._none(sym, "hunt_no_bias")

        # Direction from bias
        if bias == "BEARISH":
            direction = "SELL"
        else:
            direction = "BUY"

        # --- Time window: 06:45-17:00 BST ---
        import datetime as _dt
        now_utc = _dt.datetime.now(_dt.timezone.utc)
        bst_min = _to_bst_minutes(now_utc)
        window_start = WINDOW_START_BST[0] * 60 + WINDOW_START_BST[1]
        window_end = WINDOW_END_BST[0] * 60 + WINDOW_END_BST[1]

        if bst_min < window_start or bst_min >= window_end:
            return self._none(sym, "hunt_outside_window")

        # One fire per session (reset on bias change)
        day_str = now_utc.strftime("%Y-%m-%d")
        session_key = f"{sym}_{day_str}_{bias}"
        if session_key in self._fired:
            return self._none(sym, "hunt_already_fired")

        # --- Get liquidity pool levels ---
        lp = briefing.get("liquidity_pools") or {}
        if direction == "SELL":
            # BEARISH: sweep buy_side levels (price goes up to grab buy stops, then reverses down)
            sweep_levels = []
            for lv in lp.get("buy_side") or []:
                try: sweep_levels.append(float(lv))
                except (TypeError, ValueError): pass
        else:
            # BULLISH: sweep sell_side levels (price goes down to grab sell stops, then reverses up)
            sweep_levels = []
            for lv in lp.get("sell_side") or []:
                try: sweep_levels.append(float(lv))
                except (TypeError, ValueError): pass

        if not sweep_levels:
            return self._none(sym, "hunt_no_lp_levels")

        # =================================================================
        # PHASE 2: if armed, check for confirmation on 5M close
        # =================================================================
        armed = self._armed.get(epic)
        if armed is not None and armed["direction"] == direction and armed["date"] == day_str:
            if is_new_5m:
                armed["candles_since"] += 1

                if armed["candles_since"] > CONFIRMATION_WINDOW:
                    logger.info(
                        "[BRIEFING-HUNT] %s %s confirmation expired after %d candles — resetting",
                        sym, direction, armed["candles_since"],
                    )
                    self._armed.pop(epic, None)
                    return self._none(sym, "hunt_confirmation_expired")

                if rc_all is not None and len(rc_all) >= 2:
                    current = rc_all[-1]
                    cur_c = current.get("candle") or {}
                    cur_ind = current.get("indicators") or {}

                    try:
                        c_open = float(cur_c["open"])
                        c_high = float(cur_c["high"])
                        c_low = float(cur_c["low"])
                        c_close = float(cur_c["close"])
                    except (KeyError, TypeError, ValueError):
                        return self._none(sym, f"hunt_armed_candle_error_{armed['candles_since']}")

                    c_range = c_high - c_low
                    if c_range <= 0:
                        return self._none(sym, f"hunt_armed_waiting_{armed['candles_since']}")

                    c_body = abs(c_close - c_open)
                    c_body_pct = c_body / c_range

                    # Rejection: body closes away from sweep level
                    is_rejection = False
                    if direction == "SELL" and c_close < c_open and c_body_pct >= MIN_REJECTION_BODY_PCT:
                        # Bearish rejection — closing below open, away from sweep high
                        is_rejection = True
                    elif direction == "BUY" and c_close > c_open and c_body_pct >= MIN_REJECTION_BODY_PCT:
                        # Bullish rejection — closing above open, away from sweep low
                        is_rejection = True

                    if not is_rejection:
                        return self._none(sym, f"hunt_armed_no_rejection_{armed['candles_since']}")

                    # MACD check: histogram compressing OR lines converging
                    macd_ok = False
                    # Histogram compression: last 3 bars reducing
                    if len(rc_all) >= 3:
                        try:
                            h3 = abs(float(_pick_macd_hist((rc_all[-3].get("indicators") or {}))))
                            h2 = abs(float(_pick_macd_hist((rc_all[-2].get("indicators") or {}))))
                            h1 = abs(float(_pick_macd_hist(cur_ind)))
                            if h3 > h2 > h1:
                                macd_ok = True
                        except (TypeError, ValueError):
                            pass

                    # Lines converging fallback
                    if not macd_ok:
                        m_val, s_val = _get_macd_lines(cur_ind)
                        if m_val is not None and s_val is not None:
                            if abs(m_val - s_val) <= MACD_CONVERGENCE:
                                macd_ok = True

                    if not macd_ok:
                        return self._none(sym, f"hunt_armed_no_macd_{armed['candles_since']}")

                    # --- ENTRY ---
                    self._armed.pop(epic, None)
                    self._fired[session_key] = True

                    pair = _pair_from_epic(epic)
                    min_sl = _PAIR_MIN_SL_PIPS.get(pair, 0)
                    buffer = SL_BUFFER_PIPS * pip_size
                    sweep_extreme = armed["sweep_extreme"]

                    if direction == "SELL":
                        sl_price = sweep_extreme + buffer
                        sl_pips = max(abs(sl_price - mid_price) / pip_size, min_sl)
                    else:
                        sl_price = sweep_extreme - buffer
                        sl_pips = max(abs(mid_price - sl_price) / pip_size, min_sl)

                    tp_pips = self._find_tp(direction, mid_price, sl_pips, briefing, pip_size)

                    # Guard: inverted R:R
                    if tp_pips <= sl_pips or tp_pips <= 0 or sl_pips <= 0:
                        sl_pips = max(sl_pips, SL_BUFFER_PIPS)
                        tp_pips = DEFAULT_TP_PIPS

                    logger.info(
                        "[BRIEFING-HUNT-ENTRY] %s %s | sweep_level=%.1f sweep_extreme=%.1f | "
                        "rejection body=%.0f%% candle %d | SL=%.1f TP=%.1f",
                        sym, direction, armed["sweep_level"], sweep_extreme,
                        c_body_pct * 100, armed["candles_since"], sl_pips, tp_pips,
                    )

                    return StrategyDecision(
                        symbol=sym,
                        regime="HUNT",
                        signal=direction,
                        mode=BRIEFING_HUNT_MODE,
                        entry=float(mid_price),
                        sl=float(sl_pips),
                        tp=float(tp_pips),
                        use_trailing_stop=True,
                        reason=f"briefing_hunt_{direction.lower()}",
                        debug={
                            "sweep_level": armed["sweep_level"],
                            "sweep_extreme": sweep_extreme,
                            "candles_to_confirm": armed["candles_since"],
                            "rejection_body_pct": round(c_body_pct, 3),
                            "rejection_high": c_high,
                            "rejection_low": c_low,
                            "sl_pips": round(sl_pips, 2),
                            "tp_pips": round(tp_pips, 2),
                        },
                    )

            return self._none(sym, f"hunt_armed_waiting_{armed.get('candles_since', 0)}")

        # =================================================================
        # PHASE 1 (Tick): check if price touches a liquidity pool level
        # =================================================================
        # Clear stale armed state from a different day/direction
        if armed is not None and (armed.get("date") != day_str or armed.get("direction") != direction):
            self._armed.pop(epic, None)

        # Sort levels: nearest first for the sweep direction
        if direction == "SELL":
            # Buy-side levels above current price — nearest first
            candidates = sorted([lv for lv in sweep_levels if lv >= mid_price - 5 * pip_size])
        else:
            # Sell-side levels below current price — nearest first (descending)
            candidates = sorted([lv for lv in sweep_levels if lv <= mid_price + 5 * pip_size], reverse=True)

        for level in candidates:
            touched = False
            if direction == "SELL" and mid_price >= level:
                touched = True
            elif direction == "BUY" and mid_price <= level:
                touched = True

            if touched:
                self._armed[epic] = {
                    "direction": direction,
                    "sweep_level": level,
                    "sweep_extreme": mid_price,
                    "candles_since": 0,
                    "date": day_str,
                    "armed_ts": _time.time(),
                }
                logger.info(
                    "[BRIEFING-HUNT-ARMED] %s %s | price=%.1f touched LP level=%.1f | "
                    "waiting for reversal confirmation (max %d candles)",
                    sym, direction, mid_price, level, CONFIRMATION_WINDOW,
                )
                return self._none(sym, "hunt_armed")

        return self._none(sym, "hunt_no_level_touch")

    # ------------------------------------------------------------------
    def _find_tp(
        self,
        direction: str,
        entry: float,
        sl_pips: float,
        briefing: Optional[Dict[str, Any]],
        pip_size: float,
    ) -> float:
        """Find TP from trading_plans > major_levels > default."""
        # 1) Try trading_plans target
        plans = briefing.get("trading_plans") or [] if briefing else []
        for plan in plans:
            plan_bias = str(plan.get("bias", "")).upper()
            if (direction == "SELL" and plan_bias == "SHORT") or \
               (direction == "BUY" and plan_bias == "LONG"):
                targets = plan.get("targets") or []
                for t in targets:
                    try:
                        dist = abs(entry - float(t)) / pip_size
                        if dist >= sl_pips:
                            return round(dist, 2)
                    except (TypeError, ValueError):
                        pass

        # 2) Try major_levels
        levels: List[float] = []
        if briefing is not None:
            ml = briefing.get("major_levels") or {}
            kl = briefing.get("key_levels") or {}
            if direction == "SELL":
                for src in (ml.get("support", []), kl.get("support", [])):
                    for p in src:
                        try: levels.append(float(p))
                        except (TypeError, ValueError): pass
                candidates = sorted([lv for lv in levels if lv < entry], reverse=True)
            else:
                for src in (ml.get("resistance", []), kl.get("resistance", [])):
                    for p in src:
                        try: levels.append(float(p))
                        except (TypeError, ValueError): pass
                candidates = sorted([lv for lv in levels if lv > entry])

            for price in candidates:
                dist = abs(entry - price) / pip_size
                if dist >= sl_pips:
                    return round(dist, 2)

        return DEFAULT_TP_PIPS

    # ------------------------------------------------------------------
    def tick_update_sweep_extreme(self, epic: str, mid_price: float) -> None:
        """Update the sweep extreme if price extends further into the sweep."""
        armed = self._armed.get(epic)
        if armed is None:
            return
        if armed["direction"] == "SELL" and mid_price > armed["sweep_extreme"]:
            armed["sweep_extreme"] = mid_price
        elif armed["direction"] == "BUY" and mid_price < armed["sweep_extreme"]:
            armed["sweep_extreme"] = mid_price

    # ------------------------------------------------------------------
    @staticmethod
    def _none(sym: str, reason: str) -> StrategyDecision:
        return StrategyDecision(
            symbol=sym,
            regime="HUNT",
            signal="NONE",
            mode=BRIEFING_HUNT_MODE,
            entry=None,
            sl=None,
            tp=None,
            use_trailing_stop=False,
            reason=reason,
        )
