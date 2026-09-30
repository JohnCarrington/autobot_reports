"""
BriefingSweepStrategy – Briefing-level rejection + confirmation entry.

Entry logic (all 4 conditions required):
1. Price within BRIEFING_LEVEL_TOLERANCE_PIPS of a briefing key level / liquidity pool
   - Resistance / buy_side level  -> SELL setup
   - Support  / sell_side level   -> BUY setup
2. Rejection candle (rc_all[-3]): pierces/touches the briefing level AND has
   strong body against the sweep direction (body >= 50% of range)
3. Confirmation candle (rc_all[-2]): closes beyond rejection candle's low/high
4. MACD histogram confirms direction (declining for SELL, rising for BUY)

SL: above rejection high (SELL) or below rejection low (BUY) + buffer
TP: next briefing key level in trade direction, or default
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from strategy_logic import (
    BRIEFING_LEVEL_TOLERANCE_PIPS,
    StrategyDecision,
    _pick_macd_hist,
)

# Per-pair minimum SL floors: imported from shared pair_config
from pair_config import MIN_SL_PIPS as _PAIR_MIN_SL_PIPS

logger = logging.getLogger("AutoBot")

# ---------------------------------------------------------------------------
# ENV-configurable parameters
# ---------------------------------------------------------------------------
BRIEFING_SWEEP_ENABLED = str(os.getenv("BRIEFING_SWEEP_ENABLED", "0")).strip() in ("1", "true", "yes")
BRIEFING_SWEEP_SL_BUFFER_PIPS = float(os.getenv("BRIEFING_SWEEP_SL_BUFFER_PIPS", "3"))
BRIEFING_SWEEP_DEFAULT_TP_PIPS = float(os.getenv("BRIEFING_SWEEP_DEFAULT_TP_PIPS", "50"))
# Session gate: block pre-London noise entries before 07:00 UTC.
BRIEFING_SWEEP_MIN_HOUR_UTC = int(os.getenv("BRIEFING_SWEEP_MIN_HOUR_UTC", "7"))
# BB proximity block — only for pairs that need counter-trend protection.
_BB_PROXIMITY_PAIRS_SWEEP = set(
    p.strip().upper()
    for p in os.getenv("BB_PROXIMITY_PAIRS", "USDJPY,USDCAD").split(",")
    if p.strip()
)

BRIEFING_SWEEP_MODE = "BRIEFING_SWEEP"

MAX_ENTRIES_PER_SESSION_SWEEP = int(os.getenv("MAX_ENTRIES_PER_SESSION", "3"))
_PAIR_MAX_ENTRIES_SWEEP: Dict[str, int] = {}
for _p in ("USDJPY", "GBPUSD", "EURUSD", "USDCAD", "GBPJPY"):
    _e = os.getenv(f"{_p}_MAX_ENTRIES_PER_SESSION")
    if _e is not None:
        _PAIR_MAX_ENTRIES_SWEEP[_p] = int(_e)
_PAIR_MAX_ENTRIES_SWEEP.setdefault("GBPUSD", 3)
_PAIR_MAX_ENTRIES_SWEEP.setdefault("EURUSD", 3)
_PAIR_MAX_ENTRIES_SWEEP.setdefault("USDJPY", 2)
_PAIR_MAX_ENTRIES_SWEEP.setdefault("USDCAD", 3)
_PAIR_MAX_ENTRIES_SWEEP.setdefault("GBPJPY", 3)

# ---------------------------------------------------------------------------
# Disk persistence for sweep session entry counters (survives restarts)
# ---------------------------------------------------------------------------
_SWEEP_SESSION_ENTRIES_PATH = os.path.join(
    os.getenv("CACHE_DIR", "/opt/tradingbot/cache"), "sweep_session_entries.json"
)


def _persist_sweep_entries(entries: Dict[str, int], biases: Dict[str, str]) -> None:
    try:
        import json as _json
        with open(_SWEEP_SESSION_ENTRIES_PATH, "w") as f:
            _json.dump({"entries": entries, "biases": biases}, f)
    except Exception:
        pass


def _load_sweep_entries() -> tuple:
    try:
        import json as _json
        with open(_SWEEP_SESSION_ENTRIES_PATH) as f:
            data = _json.load(f)
        return data.get("entries", {}), data.get("biases", {})
    except Exception:
        return {}, {}


def _pair_from_epic(epic: str) -> str:
    parts = epic.split(".")
    return parts[2] if len(parts) >= 3 else epic.upper()


class BriefingSweepStrategy:
    """Briefing-level rejection -> confirmation entry."""

    def __init__(self) -> None:
        _saved_entries, _saved_biases = _load_sweep_entries()
        self._session_entries: Dict[str, int] = _saved_entries
        self._last_session_bias: Dict[str, str] = _saved_biases

    def _check_session_reset(self, epic: str, session_bias: str) -> None:
        """Reset entry counter when the session bias changes (new briefing session)."""
        prev = self._last_session_bias.get(epic)
        if prev != session_bias:
            self._session_entries[epic] = 0
            self._last_session_bias[epic] = session_bias
            _persist_sweep_entries(self._session_entries, self._last_session_bias)

    def evaluate(
        self,
        symbol: str,
        epic: str,
        df: Any,
        pip_size: float,
        mid_price: float,
        briefing: Optional[Dict[str, Any]],
    ) -> StrategyDecision:
        sym = str(symbol).upper()

        if briefing is None:
            return self._none(sym, "no_briefing_sweep")

        # --- Session gate: block pre-London noise entries before 07:00 UTC ---
        now_utc = datetime.now(timezone.utc)
        min_hour = BRIEFING_SWEEP_MIN_HOUR_UTC
        if now_utc.hour < min_hour:
            logger.info(
                "[BRIEFING-SWEEP] %s blocked — morning session (before %02d:00 UTC)",
                sym, min_hour,
            )
            return self._none(sym, "briefing_sweep_morning_blocked")

        # --- Bias filter (session_bias only; plan.bias overrides below) ---
        # Composite session+daily veto removed — daily_bias is the D1 multi-day
        # trend and intentionally allowed to disagree with session_bias.
        _session = str(briefing.get("session_bias", "")).upper()

        # Track session changes and reset entry counter
        self._check_session_reset(epic, _session)

        _bias = _session if _session in ("BULLISH", "BEARISH") else "NONE"

        # Rank-1 plan.bias takes precedence over session_bias.
        # LONG → BULLISH (BUY-only), SHORT → BEARISH (SELL-only). Falls back
        # to session_bias when plan has no directional bias.
        _allow_both = False
        _plans = briefing.get("trading_plans") or []
        _plan_bias = ""
        if isinstance(_plans, list) and _plans:
            _plan_bias = str((_plans[0] or {}).get("bias", "") or "").upper()
        if _plan_bias == "LONG":
            if _bias != "BULLISH":
                logger.info(
                    "[BRIEFING-SWEEP] %s plan.bias=LONG overrides session_bias %s",
                    sym, _bias,
                )
            _bias = "BULLISH"
        elif _plan_bias == "SHORT":
            if _bias != "BEARISH":
                logger.info(
                    "[BRIEFING-SWEEP] %s plan.bias=SHORT overrides session_bias %s",
                    sym, _bias,
                )
            _bias = "BEARISH"
        elif _bias == "NONE":
            if _plans:
                _allow_both = True
                logger.info(
                    "[BRIEFING-SWEEP] %s NEUTRAL bias — allowing both BUY/SELL (rank-1 plan present, no plan.bias)",
                    sym,
                )
            else:
                return self._none(sym, "briefing_sweep_no_bias")

        # --- Collect levels with direction tags ---
        sell_levels: List[float] = []  # resistance / buy_side -> SELL
        buy_levels: List[float] = []   # support / sell_side -> BUY

        kl = briefing.get("key_levels") or {}
        for lv in kl.get("resistance") or []:
            try:
                sell_levels.append(float(lv))
            except (TypeError, ValueError):
                pass
        for lv in kl.get("support") or []:
            try:
                buy_levels.append(float(lv))
            except (TypeError, ValueError):
                pass

        ml = briefing.get("major_levels") or {}
        for lv in ml.get("resistance") or []:
            try:
                sell_levels.append(float(lv))
            except (TypeError, ValueError):
                pass
        for lv in ml.get("support") or []:
            try:
                buy_levels.append(float(lv))
            except (TypeError, ValueError):
                pass

        lp = briefing.get("liquidity_pools") or {}
        for lv in lp.get("buy_side") or []:
            try:
                sell_levels.append(float(lv))
            except (TypeError, ValueError):
                pass
        for lv in lp.get("sell_side") or []:
            try:
                buy_levels.append(float(lv))
            except (TypeError, ValueError):
                pass

        if not sell_levels and not buy_levels:
            return self._none(sym, "briefing_sweep_no_levels")

        # --- Need rc_all with at least 4 entries ([-3] through [-1] + one earlier) ---
        rc_all: list = []
        if isinstance(df, list):
            rc_all = df
        elif hasattr(df, "iterrows"):
            return self._none(sym, "briefing_sweep_need_rc_all")

        if len(rc_all) < 4:
            return self._none(sym, "briefing_sweep_insufficient_candles")

        # --- Trend override: block counter-trend entries when last 6 closed 5M
        # candles show strictly higher highs + higher lows (uptrend) or lower
        # highs + lower lows (downtrend). Use last 6 CLOSED candles (skip the
        # in-progress one at [-1]).
        if len(rc_all) >= 7:
            try:
                recent6 = [rc_all[i].get("candle") or {} for i in range(-7, -1)]
                highs = [float(c["high"]) for c in recent6]
                lows  = [float(c["low"])  for c in recent6]
                uptrend   = all(highs[i] > highs[i-1] for i in range(1, 6)) and \
                            all(lows[i]  > lows[i-1]  for i in range(1, 6))
                downtrend = all(highs[i] < highs[i-1] for i in range(1, 6)) and \
                            all(lows[i]  < lows[i-1]  for i in range(1, 6))
                if _bias == "BEARISH" and uptrend:
                    logger.info(
                        "[BRIEFING-SWEEP] %s BEARISH bias blocked — 6 consecutive 5M "
                        "higher-highs-and-higher-lows uptrend", sym,
                    )
                    return self._none(sym, "briefing_sweep_trend_override_up")
                if _bias == "BULLISH" and downtrend:
                    logger.info(
                        "[BRIEFING-SWEEP] %s BULLISH bias blocked — 6 consecutive 5M "
                        "lower-highs-and-lower-lows downtrend", sym,
                    )
                    return self._none(sym, "briefing_sweep_trend_override_down")
            except (KeyError, TypeError, ValueError):
                pass

        rejection_candle = rc_all[-3]
        confirmation_candle = rc_all[-2]

        rj_c = rejection_candle.get("candle") or {}
        cf_c = confirmation_candle.get("candle") or {}

        try:
            rj_open = float(rj_c["open"])
            rj_high = float(rj_c["high"])
            rj_low = float(rj_c["low"])
            rj_close = float(rj_c["close"])
            cf_close = float(cf_c["close"])
        except (KeyError, TypeError, ValueError):
            return self._none(sym, "briefing_sweep_candle_parse_error")

        rj_range = rj_high - rj_low
        if rj_range <= 0:
            return self._none(sym, "briefing_sweep_zero_range")

        rj_body = abs(rj_close - rj_open)
        rj_body_pct = rj_body / rj_range

        tol = BRIEFING_LEVEL_TOLERANCE_PIPS * pip_size

        # --- MACD histogram ---
        cf_hist = _pick_macd_hist(confirmation_candle.get("indicators") or {})
        rj_hist = _pick_macd_hist(rejection_candle.get("indicators") or {})

        all_levels = sorted(set(sell_levels + buy_levels))

        # --- Try SELL setup (resistance levels) ---
        sell_result = None
        if _bias == "BEARISH" or _allow_both:  # SELL when bias is BEARISH or NEUTRAL-with-plan
            sell_result = self._check_setup(
                direction="SELL",
                levels=sell_levels,
                all_levels_sorted=all_levels,
                rj_open=rj_open,
                rj_close=rj_close,
                rj_high=rj_high,
                rj_low=rj_low,
                rj_body_pct=rj_body_pct,
                cf_close=cf_close,
                cf_hist=cf_hist,
                rj_hist=rj_hist,
                mid_price=mid_price,
                pip_size=pip_size,
                tol=tol,
                sym=sym,
                epic=epic,
                rc_all=rc_all,
                briefing=briefing,
            )
        if sell_result is not None:
            return sell_result

        # --- Try BUY setup (support levels) ---
        buy_result = None
        if _bias == "BULLISH" or _allow_both:  # BUY when bias is BULLISH or NEUTRAL-with-plan
            buy_result = self._check_setup(
                direction="BUY",
                levels=buy_levels,
                all_levels_sorted=all_levels,
                rj_open=rj_open,
                rj_close=rj_close,
                rj_high=rj_high,
                rj_low=rj_low,
                rj_body_pct=rj_body_pct,
                cf_close=cf_close,
                cf_hist=cf_hist,
                rj_hist=rj_hist,
                mid_price=mid_price,
                pip_size=pip_size,
                tol=tol,
                sym=sym,
                epic=epic,
                rc_all=rc_all,
                briefing=briefing,
            )
        if buy_result is not None:
            return buy_result

        return self._none(sym, "briefing_sweep_no_match")

    # ------------------------------------------------------------------
    def _check_setup(
        self,
        direction: str,
        levels: List[float],
        all_levels_sorted: List[float],
        rj_open: float,
        rj_close: float,
        rj_high: float,
        rj_low: float,
        rj_body_pct: float,
        cf_close: float,
        cf_hist: Optional[float],
        rj_hist: Optional[float],
        mid_price: float,
        pip_size: float,
        tol: float,
        sym: str,
        epic: str,
        rc_all: Optional[list] = None,
        briefing: Optional[Dict[str, Any]] = None,
    ) -> Optional[StrategyDecision]:
        """Check one direction. Returns StrategyDecision if all 4 conditions met, else None."""

        # 1) Find nearest level within tolerance of the rejection candle's extreme
        matched_level: Optional[float] = None
        best_dist = float("inf")
        for lv in levels:
            if direction == "SELL":
                dist = abs(rj_high - lv)
            else:
                dist = abs(rj_low - lv)
            if dist <= tol and dist < best_dist:
                best_dist = dist
                matched_level = lv

        if matched_level is None:
            return None

        # 2) Rejection candle: pierces/touches the level AND has strong body
        if rj_body_pct < 0.50:
            return None

        if direction == "SELL":
            # Bearish rejection: close < open, high pierced/touched level
            if rj_close >= rj_open:
                return None
            if rj_high < matched_level - tol:
                return None
        else:
            # Bullish rejection: close > open, low pierced/touched level
            if rj_close <= rj_open:
                return None
            if rj_low > matched_level + tol:
                return None

        # 3) Confirmation candle: closes beyond rejection candle's extreme
        if direction == "SELL":
            if cf_close >= rj_low:
                return None
        else:
            if cf_close <= rj_high:
                return None

        # 4) MACD histogram — direction-aware momentum check
        if cf_hist is None or rj_hist is None:
            return None
        if direction == "SELL":
            # Block if histogram is positive and expanding (bullish momentum building)
            if cf_hist > 0 and cf_hist > rj_hist:
                return None
            # Allow if: positive but shrinking, OR turned negative
        else:
            # Block if histogram is negative and expanding (bearish momentum building)
            if cf_hist < 0 and cf_hist < rj_hist:
                return None
            # Allow if: negative but shrinking, OR turned positive

        # --- Level proximity filter: price must be within 15 pips of a level ---
        if levels:
            nearest_level_dist = min(abs(mid_price - lv) / pip_size for lv in levels)
        else:
            nearest_level_dist = float("inf")
        if nearest_level_dist > 15:
            logger.info(
                "[BRIEFING-SWEEP] %s %s blocked — no briefing level within 15 pips of entry",
                sym, direction,
            )
            return self._none(sym, "briefing_sweep_no_level_proximity")

        # --- All 4 conditions met — compute SL / TP ---
        buffer = BRIEFING_SWEEP_SL_BUFFER_PIPS * pip_size
        pair = _pair_from_epic(epic)
        min_sl = _PAIR_MIN_SL_PIPS.get(pair, 0)

        if direction == "SELL":
            # SL anchored to nearest resistance level above entry
            above = [lv for lv in levels if lv >= mid_price]
            if above:
                sl_price = min(above) + buffer
            else:
                sl_price = rj_high + buffer  # fallback to rejection candle
            sl_pips = max(abs(sl_price - mid_price) / pip_size, min_sl)
            tp_pips = self._find_tp_plan("SELL", mid_price, sl_pips, briefing, pip_size)
            reason = "briefing_sweep_sell"
        else:
            # SL anchored to nearest support level below entry
            below = [lv for lv in levels if lv <= mid_price]
            if below:
                sl_price = max(below) - buffer
            else:
                sl_price = rj_low - buffer  # fallback to rejection candle
            sl_pips = max(abs(mid_price - sl_price) / pip_size, min_sl)
            tp_pips = self._find_tp_plan("BUY", mid_price, sl_pips, briefing, pip_size)
            reason = "briefing_sweep_buy"

        # Guard: if briefing-level TP is smaller than SL (inverted R:R),
        # fall back to default TP.
        if tp_pips <= sl_pips or tp_pips <= 0 or sl_pips <= 0:
            logger.warning(
                "[BRIEFING-SWEEP] %s %s | inverted/zero R:R (SL=%.1f TP=%.1f) — "
                "falling back to default TP",
                reason, sym, sl_pips, tp_pips,
            )
            sl_pips = max(sl_pips, BRIEFING_SWEEP_SL_BUFFER_PIPS)
            tp_pips = BRIEFING_SWEEP_DEFAULT_TP_PIPS

        debug = {
            "matched_level": matched_level,
            "rj_high": rj_high,
            "rj_low": rj_low,
            "rj_body_pct": round(rj_body_pct, 3),
            "cf_close": cf_close,
            "macd_hist_cf": cf_hist,
            "macd_hist_rj": rj_hist,
            "sl_pips": round(sl_pips, 2),
            "tp_pips": round(tp_pips, 2),
        }

        # --- BB proximity block (pair-specific: USDJPY/USDCAD only by default) ---
        pair = _pair_from_epic(epic)
        if pair in _BB_PROXIMITY_PAIRS_SWEEP and rc_all is not None and len(rc_all) >= 22:
            try:
                _sw_closes = [float((c.get("candle") or c).get("close") or (c.get("candle") or c).get("c", 0)) for c in rc_all[-22:]]
                _sw_sma = np.mean(_sw_closes[-20:])
                _sw_std = np.std(_sw_closes[-20:], ddof=1)
                _sw_bb_upper = _sw_sma + 2 * _sw_std
                _sw_bb_lower = _sw_sma - 2 * _sw_std
                _sw_proximity = 15 * pip_size
                if (direction == "SELL" and (mid_price - _sw_bb_lower) <= _sw_proximity) or \
                   (direction == "BUY" and (_sw_bb_upper - mid_price) <= _sw_proximity):
                    logger.info(
                        "[BRIEFING-SWEEP] %s %s BLOCKED near opposing BB "
                        "(price=%.1f upper=%.1f lower=%.1f)",
                        sym, direction, mid_price, _sw_bb_upper, _sw_bb_lower,
                    )
                    return self._none(sym, "briefing_sweep_bb_proximity")
            except Exception:
                pass

        logger.info(
            "[BRIEFING-SWEEP] %s %s | level=%.1f | SL=%.1f TP=%.1f",
            reason, sym, matched_level, sl_pips, tp_pips,
        )

        try:
            from guards import check_trade as _guards_check
            _tp_price_g = mid_price - tp_pips * pip_size if direction == "SELL" \
                else mid_price + tp_pips * pip_size
            _g_blocked, _g_reason = _guards_check(
                symbol=sym,
                direction=direction,
                strategy_mode="BRIEFING_SWEEP",
                intended_entry=float(mid_price),
                intended_sl=float(sl_price),
                intended_tp=float(_tp_price_g),
                current_mid=float(mid_price),
                df_5m=rc_all,
                pip_size=pip_size,
            )
            if _g_blocked:
                logger.info("[BRIEFING-SWEEP] %s %s blocked by guards: %s",
                            sym, direction, _g_reason)
                return self._none(sym, "briefing_sweep_guard_blocked")
        except Exception as _g_exc:
            logger.warning("[BRIEFING-SWEEP] guard eval raised: %s",
                           _g_exc, exc_info=True)

        # --- Session entry limit ---
        max_ent = _PAIR_MAX_ENTRIES_SWEEP.get(pair, MAX_ENTRIES_PER_SESSION_SWEEP)
        cur_ent = self._session_entries.get(epic, 0)
        if cur_ent >= max_ent:
            logger.info(
                "[BRIEFING-SWEEP] %s session entry limit reached (%d/%d) — no further entries this session",
                pair, cur_ent, max_ent,
            )
            return self._none(sym, "briefing_sweep_session_limit")
        self._session_entries[epic] = cur_ent + 1
        _persist_sweep_entries(self._session_entries, self._last_session_bias)

        return StrategyDecision(
            symbol=sym,
            regime="SWEEP",
            signal=direction,
            mode=BRIEFING_SWEEP_MODE,
            entry=float(mid_price),
            sl=float(sl_pips),
            tp=float(tp_pips),
            use_trailing_stop=True,
            reason=reason,
            debug=debug,
        )

    # ------------------------------------------------------------------
    def _find_tp_plan(
        self,
        direction: str,
        entry: float,
        sl_pips: float,
        briefing: Optional[Dict[str, Any]],
        pip_size: float,
    ) -> float:
        """Find next briefing level in trade direction as TP (pip distance).

        SELL: support / sell-side levels below entry.
        BUY:  resistance / buy-side levels above entry.
        Fallback: BRIEFING_SWEEP_DEFAULT_TP_PIPS (50).
        """
        levels: List[float] = []
        if briefing is not None:
            kl = briefing.get("key_levels") or {}
            ml = briefing.get("major_levels") or {}
            lp = briefing.get("liquidity_pools") or {}
            if direction == "SELL":
                for src in (kl.get("support", []), ml.get("support", []), lp.get("sell_side", [])):
                    for p in src:
                        try:
                            levels.append(float(p))
                        except (TypeError, ValueError):
                            pass
            else:
                for src in (kl.get("resistance", []), ml.get("resistance", []), lp.get("buy_side", [])):
                    for p in src:
                        try:
                            levels.append(float(p))
                        except (TypeError, ValueError):
                            pass

        if direction == "SELL":
            candidates = sorted([lv for lv in levels if lv < entry], reverse=True)
        else:
            candidates = sorted([lv for lv in levels if lv > entry])

        for price in candidates:
            dist_pips = abs(entry - price) / pip_size
            if dist_pips >= sl_pips:
                return round(dist_pips, 2)

        return BRIEFING_SWEEP_DEFAULT_TP_PIPS

    # ------------------------------------------------------------------
    @staticmethod
    def _none(sym: str, reason: str) -> StrategyDecision:
        return StrategyDecision(
            symbol=sym,
            regime="SWEEP",
            signal="NONE",
            mode=BRIEFING_SWEEP_MODE,
            entry=None,
            sl=None,
            tp=None,
            use_trailing_stop=False,
            reason=reason,
        )
