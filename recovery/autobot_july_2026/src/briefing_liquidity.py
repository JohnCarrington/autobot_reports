"""
BriefingLiquidityStrategy — Briefing-gated liquidity sweep with tick-level arming.

Layer 1: Directional bias from morning briefing (direction only, no confidence gate).
Layer 2: Key levels extracted directly from the briefing output (key_levels + liquidity_pools).
Layer 3: Arm-and-confirm trigger at level (WATCHING → ARMED → TRIGGERED).

Replaces BriefingSweepStrategy as the primary trading strategy.
Emits StrategyDecision signals only — does not place trades.
"""

from __future__ import annotations

import enum
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from strategy_logic import StrategyDecision

logger = logging.getLogger("AutoBot")

_SESSION_ENTRIES_PATH = os.path.join(
    os.getenv("CACHE_DIR", "/opt/tradingbot/cache"), "session_entries.json"
)


def _persist_session_entries(entries: Dict[str, int], briefing_times: Dict[str, str]) -> None:
    """Save session entry counters to disk for restart recovery."""
    try:
        import json as _json
        with open(_SESSION_ENTRIES_PATH, "w") as f:
            _json.dump({"entries": entries, "briefing_times": briefing_times}, f)
    except Exception:
        pass


def _load_session_entries() -> tuple:
    """Load persisted session entry counters. Returns (entries_dict, briefing_times_dict)."""
    try:
        import json as _json
        with open(_SESSION_ENTRIES_PATH) as f:
            data = _json.load(f)
        return data.get("entries", {}), data.get("briefing_times", {})
    except Exception:
        return {}, {}


# ---------------------------------------------------------------------------
# ENV-configurable parameters
# ---------------------------------------------------------------------------
BRIEFING_LIQUIDITY_ENABLED = str(os.getenv("BRIEFING_LIQUIDITY_ENABLED", "0")).strip() in ("1", "true", "yes")
# Tolerance in points (e.g. 10 points = 1 pip for GBPUSD).
BRIEFING_LIQUIDITY_ARM_TOLERANCE_PTS = float(os.getenv("BRIEFING_LIQUIDITY_ARM_TOLERANCE_PTS", "1"))
BRIEFING_LIQUIDITY_RESET_AWAY_PIPS = float(os.getenv("BRIEFING_LIQUIDITY_RESET_AWAY_PIPS", "20"))
BRIEFING_LIQUIDITY_ARM_TIMEOUT_CANDLES = int(os.getenv("BRIEFING_LIQUIDITY_ARM_TIMEOUT_CANDLES", "36"))
BRIEFING_LIQUIDITY_SL_BUFFER_PIPS = float(os.getenv("BRIEFING_LIQUIDITY_SL_BUFFER_PIPS", "3"))
# Proximity (pips) used when gating entries against the briefing's levels
# array. Matches BB_REVERSAL's gate — an entry is blocked unless a level in
# briefing["levels"] with matching trade_direction, intent in {BOUNCE,FADE},
# and strength in {HIGH,MEDIUM} sits within this many pips of the entry.
BRIEFING_LIQUIDITY_LEVELS_PROXIMITY_PIPS = float(
    os.getenv("BRIEFING_LIQUIDITY_LEVELS_PROXIMITY_PIPS", "8") or 8.0
)
BRIEFING_LIQUIDITY_MIN_RR = float(os.getenv("BRIEFING_LIQUIDITY_MIN_RR", "1.5"))
BRIEFING_LIQUIDITY_MIN_TP1_PIPS = float(os.getenv("BRIEFING_LIQUIDITY_MIN_TP1_PIPS", "15"))
BRIEFING_LIQUIDITY_COOLDOWN_MINS = int(os.getenv("BRIEFING_LIQUIDITY_COOLDOWN_MINS", "60"))
BRIEFING_LIQUIDITY_BB_PIERCE_ENABLED = str(os.getenv("BRIEFING_LIQUIDITY_BB_PIERCE_ENABLED", "1")).strip() in ("1", "true", "yes")
BRIEFING_LIQUIDITY_BB_PIERCE_MAX_SL_PIPS = float(os.getenv("BRIEFING_LIQUIDITY_BB_PIERCE_MAX_SL_PIPS", "10"))
BRIEFING_LIQUIDITY_BB_PIERCE_MAX_CANDLE_PIPS = float(os.getenv("BRIEFING_LIQUIDITY_BB_PIERCE_MAX_CANDLE_PIPS", "20"))
BRIEFING_LIQUIDITY_BB_PIERCE_MAX_ENTRY_PIPS = float(os.getenv("BRIEFING_LIQUIDITY_BB_PIERCE_MAX_ENTRY_PIPS", "10"))

# Sweep entry quality filters — applied to ALL sweep variants after trigger detection.
# Rejection candle: the candle before entry must close back inside the BB with a
# reversal body of at least BL_MIN_REJECTION_BODY pips, confirming a genuine sweep.
# Wick ratio: the pierce candle's wick beyond the BB must be >= BL_MIN_WICK_RATIO × body,
# filtering out trending moves through the band.
BL_REQUIRE_REJECTION_CANDLE = str(os.getenv("BL_REQUIRE_REJECTION_CANDLE", "0")).strip() in ("1", "true", "yes")
BL_MIN_REJECTION_BODY = float(os.getenv("BL_MIN_REJECTION_BODY", "2.0"))
BL_MIN_WICK_RATIO = float(os.getenv("BL_MIN_WICK_RATIO", "1.5"))
# Session confidence gate — suspend BL/WS when briefing confidence is too low
SESSION_CONFIDENCE_GATE_ENABLED = str(os.getenv("SESSION_CONFIDENCE_GATE_ENABLED", "1")).strip() in ("1", "true", "yes")
SESSION_CONFIDENCE_MIN = float(os.getenv("SESSION_CONFIDENCE_MIN", "0.56"))

# BB width filter for WINDOW_SWEEP — only fire when bands are wide enough for a 30p reversal
SWEEP_MIN_BB_WIDTH_PIPS = float(os.getenv("SWEEP_MIN_BB_WIDTH_PIPS", "22"))

# Bias staleness decay — suspend bias if price moves too far against it since it was set.
BIAS_STALENESS_ENABLED = str(os.getenv("BIAS_STALENESS_ENABLED", "1")).strip() in ("1", "true", "yes")
BIAS_STALENESS_PIPS_DEFAULT = float(os.getenv("BIAS_STALENESS_PIPS_DEFAULT", "25"))
_BIAS_STALENESS_PIPS: Dict[str, float] = {}
for _p in ("USDJPY", "GBPUSD", "EURUSD", "USDCAD", "GBPJPY"):
    _e = os.getenv(f"BIAS_STALENESS_PIPS_{_p}")
    if _e is not None:
        _BIAS_STALENESS_PIPS[_p] = float(_e)
_BIAS_STALENESS_PIPS.setdefault("GBPJPY", 35.0)

BRIEFING_LIQUIDITY_MIN_CONFIDENCE = float(os.getenv("BRIEFING_LIQUIDITY_MIN_CONFIDENCE", "0.60"))
# Per-pair confidence overrides (all-session) — read from env only
_PAIR_MIN_CONFIDENCE: Dict[str, float] = {}
for _p in ("USDJPY", "GBPUSD", "EURUSD", "USDCAD", "GBPJPY"):
    _e = os.getenv(f"{_p}_MIN_CONFIDENCE")
    if _e is not None:
        _PAIR_MIN_CONFIDENCE[_p] = float(_e)
_PAIR_MIN_CONFIDENCE.setdefault("GBPUSD", 0.65)
_PAIR_MIN_CONFIDENCE.setdefault("EURUSD", 0.65)
_PAIR_MIN_CONFIDENCE.setdefault("GBPJPY", 0.65)
# Sweep entry variants: comma-separated list of enabled variant numbers (1-6)
BRIEFING_LIQUIDITY_SWEEP_VARIANTS = set(
    int(v.strip()) for v in os.getenv("BRIEFING_LIQUIDITY_SWEEP_VARIANTS", "1,2,3,4,5,6").split(",") if v.strip()
)
# V3 pair filter — only enable engulfing-at-BB-proximity for these pairs
_SWEEP_V3_PAIRS = set(
    p.strip().upper()
    for p in os.getenv("SWEEP_V3_PAIRS", "GBPUSD,EURUSD").split(",")
    if p.strip()
)
# BB proximity block — only for pairs that need counter-trend protection at band extremes.
# GBPUSD/EURUSD: removed (bias gate + structural levels sufficient).
# USDJPY/USDCAD: kept (these pairs overshoot bands more often).
_BB_PROXIMITY_PAIRS = set(
    p.strip().upper()
    for p in os.getenv("BB_PROXIMITY_PAIRS", "USDJPY,USDCAD").split(",")
    if p.strip()
)
MAX_ENTRIES_PER_SESSION = int(os.getenv("MAX_ENTRIES_PER_SESSION", "3"))
# Per-pair overrides (e.g. USDJPY_MAX_ENTRIES_PER_SESSION=2)
_PAIR_MAX_ENTRIES: Dict[str, int] = {}
for _p in ("USDJPY", "GBPUSD", "EURUSD", "USDCAD", "GBPJPY"):
    _e = os.getenv(f"{_p}_MAX_ENTRIES_PER_SESSION")
    if _e is not None:
        _PAIR_MAX_ENTRIES[_p] = int(_e)
_PAIR_MAX_ENTRIES.setdefault("GBPUSD", 3)
_PAIR_MAX_ENTRIES.setdefault("EURUSD", 3)
_PAIR_MAX_ENTRIES.setdefault("USDJPY", 2)
_PAIR_MAX_ENTRIES.setdefault("USDCAD", 3)
_PAIR_MAX_ENTRIES.setdefault("GBPJPY", 3)
BRIEFING_LIQUIDITY_OPENING_RANGE_ENABLED = str(os.getenv("BRIEFING_LIQUIDITY_OPENING_RANGE_ENABLED", "1")).strip() in ("1", "true", "yes")
BRIEFING_LIQUIDITY_EMA_PULLBACK_ENABLED = str(os.getenv("BRIEFING_LIQUIDITY_EMA_PULLBACK_ENABLED", "1")).strip() in ("1", "true", "yes")

# Tick-level early arm: confluence-based pre-arm when price + BB converge on a briefing level.
BRIEFING_LIQUIDITY_TICK_ARM_ENABLED = str(os.getenv("BRIEFING_LIQUIDITY_TICK_ARM_ENABLED", "0")).strip() in ("1", "true", "yes")
BRIEFING_LIQUIDITY_TICK_ARM_PROXIMITY_PIPS = float(os.getenv("BRIEFING_LIQUIDITY_TICK_ARM_PROXIMITY_PIPS", "15"))
BRIEFING_LIQUIDITY_TICK_ARM_TIMEOUT_SECS = float(os.getenv("BRIEFING_LIQUIDITY_TICK_ARM_TIMEOUT_SECS", "60"))

# Observation mode: log all signals but return NONE instead of live signals.
BRIEFING_LIQUIDITY_OBSERVE = str(os.getenv("BRIEFING_LIQUIDITY_OBSERVE", "1")).strip() in ("1", "true", "yes")

BRIEFING_LIQUIDITY_MODE = "BRIEFING_LIQUIDITY"

# ---------------------------------------------------------------------------
# IG points-per-pip lookup
# IG spread-bet markets quote in "points" not standard pips.
# Points-per-pip: imported from shared pair_config
from pair_config import POINTS_PER_PIP as EPIC_POINTS_PER_PIP, DEFAULT_PPP as _DEFAULT_POINTS_PER_PIP


def _pair_from_epic(epic: str) -> str:
    """Extract pair name from IG epic, e.g. 'CS.D.USDJPY.TODAY.IP' -> 'USDJPY'."""
    parts = epic.split(".")
    return parts[2] if len(parts) >= 3 else epic.upper()


def _max_entries_for_epic(epic: str) -> int:
    """Return the per-session entry limit for an epic."""
    pair = _pair_from_epic(epic)
    return _PAIR_MAX_ENTRIES.get(pair, MAX_ENTRIES_PER_SESSION)


def _get_points_per_pip(epic_or_symbol: str) -> float:
    """Return the IG points-per-pip multiplier for an epic or symbol string."""
    key = epic_or_symbol.upper()
    if key in EPIC_POINTS_PER_PIP:
        return EPIC_POINTS_PER_PIP[key]
    for sym, val in EPIC_POINTS_PER_PIP.items():
        if sym in key:
            return val
    return _DEFAULT_POINTS_PER_PIP


# Levels-array entry gate — parity with bb_reversal._match_levels_array.
# Kept local (BB_REVERSAL left untouched) so the two strategies share the
# same accepted intent/strength/direction contract without cross-import.
_LEVELS_ACCEPTED_INTENTS   = ("BOUNCE", "FADE")
_LEVELS_ACCEPTED_STRENGTHS = ("HIGH", "MEDIUM")


def _pre_event_blackout_blocks(
    briefing: Optional[Dict[str, Any]], now_utc: datetime,
) -> Optional[Dict[str, str]]:
    """Return the {start_utc, end_utc} dict if now_utc is inside the
    briefing's pre_event_blackout window, else None. Fail-open on missing
    or malformed fields.
    """
    if not isinstance(briefing, dict):
        return None
    peb = briefing.get("pre_event_blackout")
    if not isinstance(peb, dict):
        return None
    start = peb.get("start_utc")
    end   = peb.get("end_utc")
    if not start or not end:
        return None
    try:
        sh, sm = (int(x) for x in str(start).split(":"))
        eh, em = (int(x) for x in str(end).split(":"))
    except (ValueError, TypeError):
        return None
    s_mins = sh * 60 + sm
    e_mins = eh * 60 + em
    now_mins = now_utc.hour * 60 + now_utc.minute
    in_window = (
        (s_mins <= now_mins < e_mins) if s_mins <= e_mins
        else (now_mins >= s_mins or now_mins < e_mins)
    )
    return {"start_utc": start, "end_utc": end} if in_window else None


def _fade_gate_blocks(
    briefing: Optional[Dict[str, Any]], direction: str,
) -> Optional[str]:
    """Return the sweep_direction if the fade_after_sweep gate blocks this
    entry (trade direction matches expected sweep direction), else None.
    Fail-open when fade_after_sweep != True or sweep_direction not BUY/SELL.
    """
    if not isinstance(briefing, dict):
        return None
    if briefing.get("fade_after_sweep") is not True:
        return None
    sd = str(briefing.get("sweep_direction", "")).upper()
    if sd not in ("BUY", "SELL"):
        return None
    return sd if str(direction).upper() == sd else None


def _match_levels_array(
    briefing: Optional[Dict[str, Any]],
    entry_price: float,
    signal_direction: str,
    ppp: float,
    max_pips: float,
) -> Optional[Dict[str, Any]]:
    """Find the nearest briefing["levels"] entry that gates this entry.

    Requirements (all must hold):
      - entry.trade_direction == signal_direction (BUY or SELL)
      - entry.intent in {BOUNCE, FADE}
      - entry.strength in {HIGH, MEDIUM}
      - |entry.price - entry_price| / ppp <= max_pips

    Returns the matched entry with an added `dist_pips` field, or None when
    no gate-qualifying level is within range / the levels array is
    missing/empty / briefing is None. Callers fail-closed on None.
    """
    if briefing is None:
        return None
    arr = briefing.get("levels")
    if not isinstance(arr, list) or not arr:
        return None

    want_dir = str(signal_direction).upper()
    best: Optional[Dict[str, Any]] = None
    best_dist = float("inf")
    for lv in arr:
        if not isinstance(lv, dict):
            continue
        if str(lv.get("trade_direction", "")).upper() != want_dir:
            continue
        if str(lv.get("intent", "")).upper() not in _LEVELS_ACCEPTED_INTENTS:
            continue
        if str(lv.get("strength", "")).upper() not in _LEVELS_ACCEPTED_STRENGTHS:
            continue
        try:
            price = float(lv["price"])
        except (TypeError, ValueError, KeyError):
            continue
        dist_pips = abs(price - entry_price) / ppp
        if dist_pips <= max_pips and dist_pips < best_dist:
            best = {**lv, "dist_pips": dist_pips}
            best_dist = dist_pips
    return best


# ---------------------------------------------------------------------------
# Telegram helper
# ---------------------------------------------------------------------------

_TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
_TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def _send_telegram(text: str) -> None:
    """Send a Telegram notification via the shared telegram_alerts helper so
    the per-host ALERT_HOST_LABEL prefix and retry logic apply."""
    if not _TELEGRAM_TOKEN or not _TELEGRAM_CHAT_ID:
        return
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(text, parse_mode="HTML")
    except Exception as exc:
        logger.warning("[BRIEFING-LIQ] Telegram send failed: %s", exc)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class TriggerState(enum.Enum):
    WATCHING = "WATCHING"    # default — waiting for price to touch level
    ARMED = "ARMED"          # level touched, awaiting confirming candle close
    CONSUMED = "CONSUMED"    # triggered and consumed — terminal state


@dataclass
class LiquidityLevel:
    price: float
    level_type: str          # "support" or "resistance"
    source: str              # e.g. "briefing_resistance", "briefing_liquidity_buy"
    major: bool = False      # True for major_levels (prev day H/L, round numbers, major pivots)


@dataclass
class TriggerSlot:
    """Per-epic, per-level arm-and-confirm state machine."""
    level: LiquidityLevel
    state: TriggerState = TriggerState.WATCHING
    direction: Optional[str] = None
    armed_at_candle: Optional[int] = None   # candle index when armed (for timeout)
    level_price: float = 0.0                # exact price for arming/confirming
    consumed: bool = False


class EarlyArmPhase(enum.Enum):
    IDLE = "IDLE"                # Not near any level
    APPROACHING = "APPROACHING"  # Price + BB converging on level
    ARMED = "ARMED"              # Pierce detected, watching for reversal


@dataclass
class EarlyArmSlot:
    """Per-epic, per-level tick-level early arm state machine."""
    level: LiquidityLevel
    phase: EarlyArmPhase = EarlyArmPhase.IDLE
    direction: Optional[str] = None          # "BUY" or "SELL"
    approaching_since: Optional[float] = None  # epoch when APPROACHING started
    pierce_price: Optional[float] = None     # extreme price during pierce
    pierce_tick_ts: Optional[float] = None   # timestamp of first pierce tick


# ---------------------------------------------------------------------------
# Main strategy class
# ---------------------------------------------------------------------------

class BriefingLiquidityStrategy:
    """Briefing-gated liquidity sweep strategy (two-candle trigger)."""

    def __init__(self) -> None:
        self._levels: Dict[str, List[LiquidityLevel]] = {}
        self._triggers: Dict[str, Dict[float, TriggerSlot]] = {}
        self._last_briefing_time: Dict[str, str] = {}
        self._last_signal_time: Dict[str, datetime] = {}
        self._candle_index: Dict[str, int] = {}  # per-epic candle counter for timeout
        # Separate cooldown for sweep variants (V1-V4) so level triggers don't block sweeps
        self._last_sweep_time: Dict[str, datetime] = {}
        # GBPUSD: one sweep per session per direction — tracks {"BUY", "SELL"} per epic
        self._sweep_dirs_fired: Dict[str, set] = {}
        # Opening range: one-shot flag per session + dedicated candle counter
        self._or_fired: Dict[str, bool] = {}
        self._briefing_candle_count: Dict[str, int] = {}
        self._current_briefing: Dict[str, Optional[Dict[str, Any]]] = {}
        # EMA pullback: arm/confirm state + one-shot flag + session high/low tracker
        self._pb_armed: Dict[str, Optional[Dict[str, Any]]] = {}
        self._pb_fired: Dict[str, bool] = {}
        self._session_high: Dict[str, float] = {}
        self._session_low: Dict[str, float] = {}
        # Tick-level early arm state: Dict[epic, Dict[level_price, EarlyArmSlot]]
        self._early_arm: Dict[str, Dict[float, EarlyArmSlot]] = {}
        # Cached BB values per epic (updated on each 5M close, read on every tick)
        self._bb_cache: Dict[str, tuple] = {}  # epic -> (upper, lower, sma)
        # Bias staleness: track mid_price and bias when first observed per symbol
        self._bias_anchor: Dict[str, Dict[str, Any]] = {}  # sym -> {bias, mid, suspended}
        # Restore session entry counters from disk if the briefing session hasn't changed
        _saved_entries, _saved_bt = _load_session_entries()
        self._session_entries: Dict[str, int] = {}
        self._saved_briefing_times: Dict[str, str] = _saved_bt
        for _ep, _cnt in _saved_entries.items():
            if _saved_bt.get(_ep) and _saved_bt.get(_ep) == self._last_briefing_time.get(_ep, _saved_bt.get(_ep)):
                self._session_entries[_ep] = int(_cnt)
                logger.info(f"[BRIEFING-LIQ] Restored session entry count for {_ep}: {_cnt}")
        # Restore briefing times so _ensure_levels doesn't think a new briefing
        # fired on first evaluate() call, which would reset counters to 0.
        self._last_briefing_time = dict(_saved_bt)

    # ------------------------------------------------------------------
    # Layer 1 — Directional Bias
    # ------------------------------------------------------------------

    @staticmethod
    def _get_bias(briefing: Optional[Dict[str, Any]]) -> str:
        """Return 'LONG', 'SHORT', or 'NONE' from briefing.

        Reads session_bias only. Composite veto against daily_bias was removed
        — daily_bias is the D1 multi-day trend and intentionally allowed to
        disagree with session_bias (e.g. fade-the-uptrend session bias on a
        BULLISH D1). Confidence gate below still applies.
        """
        if briefing is None:
            return "NONE"
        # Confidence gate: reject low-conviction bias
        try:
            confidence = float(briefing.get("bias_confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        _sym = str(briefing.get("symbol", "")).upper()
        min_conf = _PAIR_MIN_CONFIDENCE.get(_sym, BRIEFING_LIQUIDITY_MIN_CONFIDENCE)
        if confidence < min_conf:
            logger.info(
                "[BRIEFING-LIQ] %s bias confidence %.2f < min %.2f — treating as NEUTRAL",
                _sym, confidence, min_conf,
            )
            return "NONE"

        session = str(briefing.get("session_bias", "")).upper()
        if session == "BULLISH":
            return "LONG"
        if session == "BEARISH":
            return "SHORT"
        return "NONE"

    # ------------------------------------------------------------------
    # Layer 2 — Extract levels from briefing output
    # ------------------------------------------------------------------

    @staticmethod
    def _levels_from_briefing(
        briefing: Dict[str, Any],
        epic: str,
        current_price: float,
    ) -> List[LiquidityLevel]:
        """
        Extract key levels directly from the briefing dict.

        Sources (in priority order):
        - briefing["key_levels"]["resistance"] -> resistance levels
        - briefing["key_levels"]["support"]    -> support levels
        - briefing["liquidity_pools"]["buy_side"]  -> resistance (buy-side liquidity sits above price)
        - briefing["liquidity_pools"]["sell_side"] -> support (sell-side liquidity sits below price)
        """
        levels: List[LiquidityLevel] = []
        seen: set = set()

        # Track which prices are major levels for TP prioritisation
        major_prices: set = set()

        _level_tolerance = 20 * _get_points_per_pip(epic)  # 20 pips in IG points

        def _add(price_raw, level_type: str, source: str, major: bool = False) -> None:
            try:
                price = float(price_raw)
            except (TypeError, ValueError):
                return
            if price <= 0:
                return
            # Reject levels on the wrong side of current price
            if level_type == "resistance" and price < current_price - _level_tolerance:
                logger.debug(
                    "[BRIEFING-LIQ] %s rejected %s resistance=%.1f below price=%.1f - %.1f",
                    epic, source, price, current_price, _level_tolerance,
                )
                return
            if level_type == "support" and price > current_price + _level_tolerance:
                logger.debug(
                    "[BRIEFING-LIQ] %s rejected %s support=%.1f above price=%.1f + %.1f",
                    epic, source, price, current_price, _level_tolerance,
                )
                return
            rounded = round(price, 5)
            if rounded in seen:
                # If this price already exists but is now flagged major, upgrade it
                if major and rounded not in major_prices:
                    major_prices.add(rounded)
                    for lv in levels:
                        if round(lv.price, 5) == rounded:
                            lv.major = True
                            break
                return
            seen.add(rounded)
            if major:
                major_prices.add(rounded)
            levels.append(LiquidityLevel(
                price=price,
                level_type=level_type,
                source=source,
                major=major,
            ))

        # BB levels first — highest priority structural levels for TP targeting
        _bb_upper = briefing.get("bb_upper")
        if _bb_upper is not None:
            _add(_bb_upper, "resistance", "briefing_bb_upper", major=True)
        _bb_lower = briefing.get("bb_lower")
        if _bb_lower is not None:
            _add(_bb_lower, "support", "briefing_bb_lower", major=True)

        # major_levels next — so they are in the list and flagged
        major_lvls = briefing.get("major_levels") or {}
        for price in (major_lvls.get("resistance") or []):
            _add(price, "resistance", "briefing_major_resistance", major=True)
        for price in (major_lvls.get("support") or []):
            _add(price, "support", "briefing_major_support", major=True)

        # key_levels.resistance / support
        key_levels = briefing.get("key_levels") or {}
        for price in (key_levels.get("resistance") or []):
            _add(price, "resistance", "briefing_resistance")
        for price in (key_levels.get("support") or []):
            _add(price, "support", "briefing_support")

        # liquidity_pools.buy_side / sell_side
        # Buy-side liquidity = clusters of buy stops ABOVE price (above highs) → acts
        # as resistance; price sweeps up to grab them then reverses → SELL setup.
        # Sell-side liquidity = clusters of sell stops BELOW price (below lows) → acts
        # as support; price sweeps down to grab them then reverses → BUY setup.
        liq_pools = briefing.get("liquidity_pools") or {}
        for price in (liq_pools.get("buy_side") or []):
            _add(price, "resistance", "briefing_liq_buyside")
        for price in (liq_pools.get("sell_side") or []):
            _add(price, "support", "briefing_liq_sellside")

        n_major = sum(1 for lv in levels if lv.major)
        logger.info(
            "[BRIEFING-LIQ] %s extracted %d levels (%d major) from briefing: %s",
            epic,
            len(levels),
            n_major,
            [(round(lv.price, 5), lv.level_type, lv.source, "MAJOR" if lv.major else "") for lv in levels],
        )
        return levels

    # ------------------------------------------------------------------
    # Layer 2b — Ensure levels + build trigger slots
    # ------------------------------------------------------------------

    def _ensure_levels(
        self,
        epic: str,
        briefing: Optional[Dict[str, Any]],
        current_price: float,
        bias: str,
    ) -> List[LiquidityLevel]:
        """Extract levels from briefing if it changed, otherwise return cached."""
        briefing_time = ""
        if briefing:
            briefing_time = str(briefing.get("briefing_time", ""))

        if briefing_time and briefing_time != self._last_briefing_time.get(epic):
            # --- Bias flip detection ---
            bias_changed = False
            try:
                bias_changed = bool(briefing.get("bias_change"))
            except Exception:
                pass
            if bias_changed:
                pair = _pair_from_epic(epic)
                prev_bias = "N/A"
                prev_b = self._current_briefing.get(epic)
                if prev_b:
                    prev_bias = str(prev_b.get("session_bias", "N/A")).upper()
                new_bias = str(briefing.get("session_bias", "N/A")).upper()
                logger.warning(
                    "[BRIEFING-LIQ] %s bias flipped %s\u2192%s \u2014 existing trades preserved, new entries use new bias",
                    pair, prev_bias, new_bias,
                )

            levels = self._levels_from_briefing(briefing, epic, current_price)
            self._levels[epic] = levels
            self._last_briefing_time[epic] = briefing_time
            bias_dir = "SELL" if bias == "SHORT" else "BUY" if bias == "LONG" else None
            self._triggers[epic] = {
                lv.price: TriggerSlot(
                    level=lv,
                    direction=bias_dir or ("BUY" if lv.level_type == "support" else "SELL"),
                    level_price=lv.price,
                )
                for lv in levels
            }
            # Tick-level early arm slots
            self._early_arm[epic] = {
                lv.price: EarlyArmSlot(
                    level=lv,
                    direction="BUY" if lv.level_type == "support" else "SELL",
                )
                for lv in levels
            }
            self._candle_index[epic] = 0
            self._or_fired[epic] = False
            self._sweep_dirs_fired[epic] = set()
            self._briefing_candle_count[epic] = 0
            # Only reset session entry counter on non-flip briefings;
            # on flip, preserve the count so we don't over-trade.
            if not bias_changed:
                self._session_entries[epic] = 0
            _persist_session_entries(self._session_entries, self._last_briefing_time)
            self._current_briefing[epic] = briefing
            self._pb_armed[epic] = None
            self._pb_fired[epic] = False
            # Session high/low only resets on London briefing — established trend
            # must be measured from the London open, not from mid-session updates.
            if self._is_london_briefing(briefing):
                self._session_high[epic] = current_price
                self._session_low[epic] = current_price
            logger.info(
                "[BRIEFING-LIQ] %s reset %d trigger slots (bias=%s, dir=%s%s)",
                epic, len(levels), bias, bias_dir,
                ", BIAS_FLIP" if bias_changed else "",
            )

        return self._levels.get(epic, [])

    # ------------------------------------------------------------------
    # Layer 3 — Arm-and-Confirm Trigger
    # ------------------------------------------------------------------

    def _advance_state_machines(
        self,
        epic: str,
        candle: Dict[str, float],
        current_price: float,
    ) -> Optional[TriggerSlot]:
        """
        Advance all arm-and-confirm state machines for one epic.
        Returns the first TriggerSlot that reaches TRIGGERED state, or None.

        WATCHING → ARMED:     candle wick touches the exact level price (±1 pt tolerance)
        ARMED    → TRIGGERED: subsequent candle closes in the confirming direction
        ARMED    → WATCHING:  timeout (36 candles) or 20-pip breakout reset
        """
        slots = self._triggers.get(epic, {})
        ppp = _get_points_per_pip(epic)
        reset_away = BRIEFING_LIQUIDITY_RESET_AWAY_PIPS * ppp
        tolerance = BRIEFING_LIQUIDITY_ARM_TOLERANCE_PTS  # in points, compared directly to prices
        timeout = BRIEFING_LIQUIDITY_ARM_TIMEOUT_CANDLES

        candle_idx = self._candle_index.get(epic, 0)
        self._candle_index[epic] = candle_idx + 1

        c_high = float(candle.get("high", 0))
        c_low = float(candle.get("low", 0))
        c_close = float(candle.get("close", 0))

        triggered_slot: Optional[TriggerSlot] = None

        for lvl_price, slot in list(slots.items()):
            lv = slot.level

            if slot.consumed:
                continue

            # --- ARMED state: check confirmation, timeout, or breakout reset ---
            if slot.state == TriggerState.ARMED:
                candles_armed = candle_idx - (slot.armed_at_candle or 0)

                # Timeout: 36 candles (3 hours of 5M) with no confirming close
                if candles_armed > timeout:
                    logger.info(
                        "[BRIEFING-LIQ] %s level=%.5f %s ARMED->WATCHING (timeout after %d candles)",
                        epic, lv.price, lv.source, candles_armed,
                    )
                    self._reset_slot(slot)
                    continue

                # Breakout reset: price 20 pips beyond level in wrong direction
                if slot.direction == "SELL" and c_high > slot.level_price + reset_away:
                    logger.info(
                        "[BRIEFING-LIQ] %s level=%.5f %s ARMED->WATCHING (breakout high=%.5f, %.1f pips above level)",
                        epic, lv.price, lv.source, c_high, (c_high - slot.level_price) / ppp,
                    )
                    self._reset_slot(slot)
                    continue
                elif slot.direction == "BUY" and c_low < slot.level_price - reset_away:
                    logger.info(
                        "[BRIEFING-LIQ] %s level=%.5f %s ARMED->WATCHING (breakout low=%.5f, %.1f pips below level)",
                        epic, lv.price, lv.source, c_low, (slot.level_price - c_low) / ppp,
                    )
                    self._reset_slot(slot)
                    continue

                # Confirmation: candle closes in the confirming direction
                if slot.direction == "SELL" and c_close < slot.level_price:
                    logger.info(
                        "[BRIEFING-LIQ] %s level=%.5f %s ARMED->TRIGGERED (SELL) close=%.5f < level=%.5f",
                        epic, lv.price, lv.source, c_close, slot.level_price,
                    )
                    triggered_slot = slot
                    slot.state = TriggerState.CONSUMED
                    slot.consumed = True
                    break
                elif slot.direction == "BUY" and c_close > slot.level_price:
                    logger.info(
                        "[BRIEFING-LIQ] %s level=%.5f %s ARMED->TRIGGERED (BUY) close=%.5f > level=%.5f",
                        epic, lv.price, lv.source, c_close, slot.level_price,
                    )
                    triggered_slot = slot
                    slot.state = TriggerState.CONSUMED
                    slot.consumed = True
                    break

                continue

            # --- WATCHING state: check if candle touches exact level price ---
            if slot.state == TriggerState.WATCHING:
                armed = False
                # Resistance / SELL: high reaches or exceeds level price
                if slot.direction == "SELL":
                    if c_high >= slot.level_price - tolerance:
                        armed = True
                # Support / BUY: low reaches or dips below level price
                elif slot.direction == "BUY":
                    if c_low <= slot.level_price + tolerance:
                        armed = True

                if armed:
                    slot.state = TriggerState.ARMED
                    slot.armed_at_candle = candle_idx
                    logger.info(
                        "[BRIEFING-LIQ] %s level=%.5f %s WATCHING->ARMED dir=%s h=%.5f l=%.5f c=%.5f",
                        epic, lv.price, lv.source, slot.direction, c_high, c_low, c_close,
                    )

        return triggered_slot

    @staticmethod
    def _reset_slot(slot: TriggerSlot) -> None:
        """Reset a slot back to WATCHING state."""
        slot.state = TriggerState.WATCHING
        slot.armed_at_candle = None

    # ------------------------------------------------------------------
    # Bias filter
    # ------------------------------------------------------------------

    @staticmethod
    def _bias_allows(bias: str, slot: TriggerSlot) -> bool:
        """LONG bias -> only BUY.  SHORT bias -> only SELL.  NONE -> no trades."""
        if bias == "NONE":
            return False
        if bias == "LONG":
            return slot.direction == "BUY"
        if bias == "SHORT":
            return slot.direction == "SELL"
        return False

    # ------------------------------------------------------------------
    # BB cache (updated once per 5M close, read on every tick)
    # ------------------------------------------------------------------

    def _update_bb_cache(self, epic: str, df_5m: pd.DataFrame) -> None:
        """Cache BB upper/lower/sma from latest 5M close prices for tick-level use."""
        if df_5m is None or len(df_5m) < 22:
            return
        closes = df_5m["close"].astype(float)
        sma = closes.rolling(20).mean()
        std = closes.rolling(20).std()
        self._bb_cache[epic] = (
            float((sma + 2 * std).iloc[-1]),
            float((sma - 2 * std).iloc[-1]),
            float(sma.iloc[-1]),
        )

    # ------------------------------------------------------------------
    # Tick-level early arm — confluence-based pre-arm state machine
    # ------------------------------------------------------------------

    def tick_check_early_arm(
        self,
        symbol: str,
        epic: str,
        mid_price: float,
        bid: float,
        ask: float,
        tick_ts: float,
        df_5m: Optional[pd.DataFrame],
        briefing: Optional[Dict[str, Any]],
    ) -> Optional[StrategyDecision]:
        """Tick-level confluence pre-arm: price + BB converging on a briefing level.

        Runs on every tick (outside the 5M gate). Returns a StrategyDecision
        if a sweep-and-reverse is detected at tick resolution.
        """
        if not BRIEFING_LIQUIDITY_TICK_ARM_ENABLED:
            return None

        sym = symbol.upper()
        from datetime import datetime as _dt
        utc_hour = _dt.utcfromtimestamp(tick_ts).hour if tick_ts else _dt.utcnow().hour
        if not (7 <= utc_hour < 17):
            return None

        if epic not in self._early_arm or epic not in self._bb_cache:
            return None

        bb_upper, bb_lower, _ = self._bb_cache[epic]
        ppp = _get_points_per_pip(epic)
        proximity = BRIEFING_LIQUIDITY_TICK_ARM_PROXIMITY_PIPS * ppp
        timeout = BRIEFING_LIQUIDITY_TICK_ARM_TIMEOUT_SECS
        pair = _pair_from_epic(epic)

        bias = self._get_bias(briefing) if briefing else "NONE"

        for lv_price, slot in self._early_arm[epic].items():
            price_dist = abs(mid_price - slot.level.price)
            # BB band relevant to level type
            if slot.level.level_type == "resistance":
                bb_dist = abs(bb_upper - slot.level.price)
                bb_label = "upper"
            else:
                bb_dist = abs(bb_lower - slot.level.price)
                bb_label = "lower"

            # ── IDLE ──────────────────────────────────────────
            if slot.phase == EarlyArmPhase.IDLE:
                if price_dist <= proximity and bb_dist <= proximity:
                    slot.phase = EarlyArmPhase.APPROACHING
                    slot.approaching_since = tick_ts
                    logger.info(
                        "[BRIEFING-LIQ-TICK] %s Sweep setup approaching — "
                        "price %.1fp from level %.1f, BB %s %.1fp from level",
                        sym, price_dist / ppp, slot.level.price,
                        bb_label, bb_dist / ppp,
                    )
                continue

            # ── APPROACHING ───────────────────────────────────
            if slot.phase == EarlyArmPhase.APPROACHING:
                # Reset if moved far away (2x proximity hysteresis)
                if price_dist > proximity * 2:
                    slot.phase = EarlyArmPhase.IDLE
                    slot.approaching_since = None
                    logger.debug(
                        "[BRIEFING-LIQ-TICK] %s Setup dissolved — price moved away from level %.1f",
                        sym, slot.level.price,
                    )
                    continue

                # Check for pierce: price crosses through the level
                pierced = False
                if slot.direction == "SELL" and mid_price > slot.level.price:
                    pierced = True
                elif slot.direction == "BUY" and mid_price < slot.level.price:
                    pierced = True

                if pierced:
                    slot.phase = EarlyArmPhase.ARMED
                    slot.pierce_price = mid_price
                    slot.pierce_tick_ts = tick_ts
                    logger.info(
                        "[BRIEFING-LIQ-TICK] %s Pierce detected — price %.1f crossed level %.1f, tracking extreme",
                        sym, mid_price, slot.level.price,
                    )
                continue

            # ── ARMED ─────────────────────────────────────────
            if slot.phase == EarlyArmPhase.ARMED:
                # Track pierce extreme
                if slot.direction == "SELL":
                    slot.pierce_price = max(slot.pierce_price, mid_price)
                else:
                    slot.pierce_price = min(slot.pierce_price, mid_price)

                # Timeout: pierced for too long = breakout, not sweep
                if tick_ts - slot.pierce_tick_ts > timeout:
                    logger.info(
                        "[BRIEFING-LIQ-TICK] %s Pierce timeout — level %.1f held for %.0fs, resetting",
                        sym, slot.level.price, timeout,
                    )
                    slot.phase = EarlyArmPhase.IDLE
                    slot.pierce_price = None
                    slot.pierce_tick_ts = None
                    slot.approaching_since = None
                    continue

                # Check for reversal: price crosses back through level
                reversed_back = False
                if slot.direction == "SELL" and mid_price < slot.level.price:
                    reversed_back = True
                elif slot.direction == "BUY" and mid_price > slot.level.price:
                    reversed_back = True

                if not reversed_back:
                    continue

                # ── FIRE ──────────────────────────────────────
                direction = slot.direction
                entry_price = mid_price
                pierce_extreme = slot.pierce_price

                # Reset slot immediately
                slot.phase = EarlyArmPhase.IDLE
                slot.pierce_price = None
                slot.pierce_tick_ts = None
                slot.approaching_since = None

                # --- signal_filter gate (fail-open on missing briefing) ---
                if briefing is not None:
                    _sf = briefing.get("signal_filter") or {}
                    if direction == "BUY" and _sf.get("allow_buys") is False:
                        logger.info(
                            "[BRIEFING-LIQ-TICK] %s SIGNAL_FILTER blocked BUY — allow_buys=false",
                            sym,
                        )
                        continue
                    if direction == "SELL" and _sf.get("allow_sells") is False:
                        logger.info(
                            "[BRIEFING-LIQ-TICK] %s SIGNAL_FILTER blocked SELL — allow_sells=false",
                            sym,
                        )
                        continue

                # --- pre_event_blackout gate (fail-open on missing field) ---
                _tick_now = (
                    datetime.fromtimestamp(tick_ts, tz=timezone.utc)
                    if tick_ts else datetime.now(timezone.utc)
                )
                _peb = _pre_event_blackout_blocks(briefing, _tick_now)
                if _peb:
                    logger.info(
                        "[BRIEFING-LIQ-TICK] PRE_EVENT_BLACKOUT blocked %s %s — blackout %s→%s UTC",
                        sym, direction, _peb["start_utc"], _peb["end_utc"],
                    )
                    continue

                # --- Levels-array gate (fail-closed, same contract as BB_REVERSAL) ---
                _lv_match = _match_levels_array(
                    briefing, slot.level.price, direction, ppp,
                    BRIEFING_LIQUIDITY_LEVELS_PROXIMITY_PIPS,
                )
                if _lv_match is None:
                    logger.info(
                        "[BRIEFING-LIQ-TICK] PIERCE-REJECT %s %s reason=no_levels_match_within_%.1fp "
                        "entry=%.1f (required: trade_direction=%s, intent in {BOUNCE,FADE}, "
                        "strength in {HIGH,MEDIUM})",
                        sym, direction, BRIEFING_LIQUIDITY_LEVELS_PROXIMITY_PIPS,
                        slot.level.price, direction,
                    )
                    continue

                # --- fade_after_sweep gate (fail-open) ---
                _fade_sd = _fade_gate_blocks(briefing, direction)
                if _fade_sd:
                    logger.info(
                        "[BRIEFING-LIQ-TICK] FADE_GATE blocked %s %s — briefing expects sweep %s, fade only",
                        sym, direction, _fade_sd,
                    )
                    continue

                logger.info(
                    "[BRIEFING-LIQ-TICK] PIERCE-MATCH %s %s entry=%.1f level_price=%.1f "
                    "type=%s intent=%s strength=%s dist=%.2fp",
                    sym, direction, slot.level.price, _lv_match["price"],
                    _lv_match.get("type"), _lv_match.get("intent"),
                    _lv_match.get("strength"), _lv_match["dist_pips"],
                )

                # --- Guards (same as V1-V4) ---

                # Bias check (NY session exemption matches V1/V3)
                _ny_session = 13 <= utc_hour < 17
                if not _ny_session:
                    if bias == "NONE":
                        logger.debug("[BRIEFING-LIQ-TICK] %s tick-arm blocked: no bias", sym)
                        continue
                    if (direction == "SELL" and bias != "SHORT") or (direction == "BUY" and bias != "LONG"):
                        logger.debug("[BRIEFING-LIQ-TICK] %s tick-arm blocked: bias=%s dir=%s", sym, bias, direction)
                        continue

                # Sweep cooldown
                now = datetime.fromtimestamp(tick_ts, tz=timezone.utc) if tick_ts else datetime.now(timezone.utc)
                last_sweep = self._last_sweep_time.get(epic)
                if last_sweep:
                    elapsed = (now - last_sweep).total_seconds()
                    if elapsed < BRIEFING_LIQUIDITY_COOLDOWN_MINS * 60:
                        logger.debug("[BRIEFING-LIQ-TICK] %s tick-arm blocked: sweep cooldown (%ds)", sym, int(elapsed))
                        continue

                # Per-direction gate for non-GBPUSD/GBPJPY
                if pair not in ("GBPUSD", "GBPJPY"):
                    if direction in self._sweep_dirs_fired.get(epic, set()):
                        logger.debug("[BRIEFING-LIQ-TICK] %s tick-arm blocked: %s already fired", sym, direction)
                        continue

                # SL: pierce extreme + buffer (matching V1 pattern)
                if pair in ("GBPUSD", "GBPJPY"):
                    sl_buffer = 5 * ppp
                else:
                    sl_buffer = BRIEFING_LIQUIDITY_SL_BUFFER_PIPS * ppp

                if direction == "SELL":
                    sl_price = pierce_extreme + sl_buffer
                    sl_pips = (sl_price - entry_price) / ppp
                else:
                    sl_price = pierce_extreme - sl_buffer
                    sl_pips = (entry_price - sl_price) / ppp

                if sl_pips <= 0:
                    logger.debug("[BRIEFING-LIQ-TICK] %s tick-arm bad SL: %.1f", sym, sl_pips)
                    continue

                # Cap SL (non-GBPUSD/GBPJPY)
                if pair not in ("GBPUSD", "GBPJPY") and sl_pips > BRIEFING_LIQUIDITY_BB_PIERCE_MAX_SL_PIPS:
                    sl_pips = BRIEFING_LIQUIDITY_BB_PIERCE_MAX_SL_PIPS
                    if direction == "SELL":
                        sl_price = entry_price + sl_pips * ppp
                    else:
                        sl_price = entry_price - sl_pips * ppp

                # Min SL floor
                from pair_config import MIN_SL_PIPS as _min_sl_map
                _min_sl = _min_sl_map.get(pair, 0)
                if sl_pips < _min_sl:
                    sl_pips = _min_sl
                    if direction == "SELL":
                        sl_price = entry_price + sl_pips * ppp
                    else:
                        sl_price = entry_price - sl_pips * ppp

                # TP plan
                levels = self._levels.get(epic, [])
                tp_plan = self._find_tp_plan(
                    direction, entry_price, sl_pips, levels, ppp, briefing,
                )
                tp1 = tp_plan[0]

                entry_label = "tick_arm_upper" if slot.level.level_type == "resistance" else "tick_arm_lower"

                tp_summary = " | ".join(
                    f"TP{i+1}={t['pips']:.1f} ({t['source']})"
                    for i, t in enumerate(tp_plan)
                )
                logger.info(
                    "[BRIEFING-LIQ-TICK] %s %s @ %.1f (%s) | level=%.1f pierce=%.1f | "
                    "bias=%s | SL=%.1f | %s%s",
                    sym, direction, entry_price, entry_label,
                    slot.level.price, pierce_extreme,
                    bias, sl_pips, tp_summary,
                    " [OBSERVE-ONLY]" if BRIEFING_LIQUIDITY_OBSERVE else "",
                )

                if BRIEFING_LIQUIDITY_OBSERVE:
                    return self._none(sym, f"briefing_liq_observe_tick_arm_{direction.lower()}")

                # Session entry limit
                max_ent = _max_entries_for_epic(epic)
                cur_ent = self._session_entries.get(epic, 0)
                if cur_ent >= max_ent:
                    logger.info(
                        "[BRIEFING-LIQ-TICK] %s session entry limit reached (%d/%d)",
                        pair, cur_ent, max_ent,
                    )
                    return self._none(sym, "briefing_liq_session_limit")
                self._session_entries[epic] = cur_ent + 1
                _persist_session_entries(self._session_entries, self._last_briefing_time)

                # Record cooldown
                self._last_sweep_time[epic] = now
                if pair in ("GBPUSD", "GBPJPY"):
                    self._sweep_dirs_fired.setdefault(epic, set()).add(direction)

                # GBPUSD/GBPJPY V1/V3-style: hold to TP1, no trail
                _gbp_hold_to_tp1 = pair in ("GBPUSD", "GBPJPY")

                debug = {
                    "bias": bias,
                    "level_price": round(slot.level.price, 1),
                    "trigger_source": entry_label,
                    "entry_source": entry_label,
                    "pierce_extreme": round(pierce_extreme, 1),
                    "sl_pips": round(sl_pips, 2),
                    "sl_price": round(sl_price, 1),
                    "sl_source": entry_label,
                    "tp_plan": tp_plan,
                    "tp1_pips": tp1["pips"],
                    "tp1_price": tp1["price"],
                    "tp1_source": tp1["source"],
                    "total_levels": len(levels),
                    "tick_arm": True,
                    "briefing_level": _lv_match,
                }

                return StrategyDecision(
                    symbol=sym,
                    regime="SWEEP",
                    signal=direction,
                    mode=BRIEFING_LIQUIDITY_MODE,
                    entry=float(entry_price),
                    sl=float(sl_pips),
                    tp=float(tp1["pips"]),
                    use_trailing_stop=not _gbp_hold_to_tp1,
                    reason=f"briefing_liq_{direction.lower()}",
                    debug=debug,
                )

        return None

    # ------------------------------------------------------------------
    # Layer 4 — Bollinger Band Sweep Trigger
    # ------------------------------------------------------------------

    def _check_sweep_entry(
        self,
        epic: str,
        df_5m: pd.DataFrame,
        bias: str,
        ppp: float,
        levels: List[LiquidityLevel],
        utc_hour: int = 12,
    ) -> Optional[Dict[str, Any]]:
        """Detect sweep entry across 4 variants (stateless lookback).

        V1: Classic BB pierce (N-2) → rejection (N-1) → confirm (N)
        V2: Single candle BB pierce with wick rejection (N-1) → confirm (N)
        V3: Engulfing at BB proximity (no pierce) (N-1) → confirm (N)
        V4: Strong engulfing at major briefing level (N-1) → confirm (N)

        Session-based V1/V3 bias gating:
        - London (07:00-11:00 UTC): bias + MACD required (all pairs).
        - NY (13:00-17:00 UTC): BB position only, no bias/MACD (all pairs).
        - Gap (11:00-13:00 UTC): bias + MACD required (conservative).
        V2/V4: bias + MACD filters (all pairs, all sessions).
        """
        if df_5m is None or len(df_5m) < 22:
            return None

        closes = df_5m["close"].astype(float)
        highs = df_5m["high"].astype(float)
        lows = df_5m["low"].astype(float)
        opens = df_5m["open"].astype(float)

        sma = closes.rolling(20).mean()
        std = closes.rolling(20).std()
        upper = sma + 2 * std
        lower = sma - 2 * std

        n = df_5m.iloc[-1]
        n_close, n_high, n_low, n_open = float(n["close"]), float(n["high"]), float(n["low"]), float(n["open"])
        n1 = df_5m.iloc[-2]
        n1_close, n1_high, n1_low, n1_open = float(n1["close"]), float(n1["high"]), float(n1["low"]), float(n1["open"])

        upper_n1 = float(upper.iloc[-2])
        lower_n1 = float(lower.iloc[-2])

        # MACD histogram — used by V2/V4 and non-GBPUSD V1/V3
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal_line
        macd_n = float(hist.iloc[-1])
        macd_prev = float(hist.iloc[-2]) if len(hist) >= 2 else 0.0

        def _macd_ok(direction: str) -> bool:
            if direction == "SELL":
                return macd_n < 0 or (macd_prev >= 0 and macd_n < 0)
            return macd_n > 0 or (macd_prev <= 0 and macd_n > 0)

        def _bias_ok(direction: str) -> bool:
            return (direction == "SELL" and bias == "SHORT") or (direction == "BUY" and bias == "LONG")

        def _sl_price(direction: str) -> float:
            last3_highs = highs.iloc[-3:].values
            last3_lows = lows.iloc[-3:].values
            sl_buffer = BRIEFING_LIQUIDITY_SL_BUFFER_PIPS * ppp
            if direction == "SELL":
                return float(max(last3_highs)) + sl_buffer
            return float(min(last3_lows)) - sl_buffer

        # All sweep variants require bias alignment + MACD confirmation.
        # No session or pair exceptions — same strict gating as BRIEFING_SWEEP.

        # --- Variant 1: Classic BB pierce + rejection + confirm ---
        if 1 in BRIEFING_LIQUIDITY_SWEEP_VARIANTS and len(df_5m) >= 23:
            n2 = df_5m.iloc[-3]
            n2_close = float(n2["close"])
            n2_open = float(n2["open"])
            upper_n2 = float(upper.iloc[-3])
            lower_n2 = float(lower.iloc[-3])
            _n1_body = abs(n1_close - n1_open)

            # Upper pierce → SELL (bias must allow)
            if n2_close > upper_n2 and n1_close <= upper_n1 and n_close < n1_low:
                direction = "SELL"
                if _bias_ok(direction) and _macd_ok(direction):
                    sl = _sl_price(direction)
                    logger.info(
                        "[BRIEFING-LIQ-V1] %s SELL pierce=%.1f reject=%.1f confirm=%.1f upper=%.1f",
                        epic, n2_close, n1_close, n_close, upper_n2,
                    )
                    return {"direction": "SELL", "entry": n_close, "sl_price": sl,
                            "source": "sweep_v1_upper", "variant": 1}

            # Lower pierce → BUY (bias must allow)
            if n2_close < lower_n2 and n1_close >= lower_n1 and n_close > n1_high:
                direction = "BUY"
                if _bias_ok(direction) and _macd_ok(direction):
                    sl = _sl_price(direction)
                    logger.info(
                        "[BRIEFING-LIQ-V1] %s BUY pierce=%.1f reject=%.1f confirm=%.1f lower=%.1f",
                        epic, n2_close, n1_close, n_close, lower_n2,
                    )
                    return {"direction": "BUY", "entry": n_close, "sl_price": sl,
                            "source": "sweep_v1_lower", "variant": 1}
                    return {"direction": "BUY", "entry": n_close, "sl_price": sl,
                            "source": "sweep_v1_lower", "variant": 1}

        # --- Variant 2: Single candle pierce with wick rejection + confirm ---
        if 2 in BRIEFING_LIQUIDITY_SWEEP_VARIANTS:
            n1_range = n1_high - n1_low
            if n1_range > 0:
                if n1_close > upper_n1:
                    lower_wick_ratio = (n1_close - n1_low) / n1_range
                    if lower_wick_ratio >= 0.25 and n_close < n1_low:
                        direction = "SELL"
                        if _bias_ok(direction) and _macd_ok(direction):
                            sl = _sl_price(direction)
                            logger.info(
                                "[BRIEFING-LIQ-V2] %s SELL wick_reject=%.0f%% close=%.1f > upper=%.1f confirm=%.1f",
                                epic, lower_wick_ratio * 100, n1_close, upper_n1, n_close,
                            )
                            return {"direction": "SELL", "entry": n_close, "sl_price": sl,
                                    "source": "sweep_v2_upper", "variant": 2}

                if n1_close < lower_n1:
                    upper_wick_ratio = (n1_high - n1_close) / n1_range
                    if upper_wick_ratio >= 0.25 and n_close > n1_high:
                        direction = "BUY"
                        if _bias_ok(direction) and _macd_ok(direction):
                            sl = _sl_price(direction)
                            logger.info(
                                "[BRIEFING-LIQ-V2] %s BUY wick_reject=%.0f%% close=%.1f < lower=%.1f confirm=%.1f",
                                epic, upper_wick_ratio * 100, n1_close, lower_n1, n_close,
                            )
                            return {"direction": "BUY", "entry": n_close, "sl_price": sl,
                                    "source": "sweep_v2_lower", "variant": 2}

        # --- Variant 3: Engulfing at BB proximity (no pierce) ---
        _pair = _pair_from_epic(epic)
        if 3 in BRIEFING_LIQUIDITY_SWEEP_VARIANTS and _pair in _SWEEP_V3_PAIRS:
            bb_prox = 15 * ppp
            n1_range = n1_high - n1_low
            n1_body = abs(n1_close - n1_open)
            n1_body_ratio = n1_body / n1_range if n1_range > 0 else 0

            if len(df_5m) >= 23:
                n2 = df_5m.iloc[-3]
                n2_close, n2_high, n2_low, n2_open = float(n2["close"]), float(n2["high"]), float(n2["low"]), float(n2["open"])

                # Near upper BB, bearish engulfing → SELL (bias must allow)
                dist_to_upper = upper_n1 - n1_high
                if 0 <= dist_to_upper <= bb_prox:
                    if n1_close < n1_open and n1_close < n2_low and n1_body_ratio >= 0.60:
                        if n_close < n1_low:
                            direction = "SELL"
                            if _bias_ok(direction) and _macd_ok(direction):
                                sl = _sl_price(direction)
                                logger.info(
                                    "[BRIEFING-LIQ-V3] %s SELL engulf@BB prox=%.1f body=%.0f%% confirm=%.1f SL=%.1f",
                                    epic, dist_to_upper / ppp, n1_body_ratio * 100, n_close, sl,
                                )
                                return {"direction": "SELL", "entry": n_close, "sl_price": sl,
                                        "source": "sweep_v3_upper", "variant": 3}

                # Near lower BB, bullish engulfing → BUY (bias must allow)
                dist_to_lower = n1_low - lower_n1
                if 0 <= dist_to_lower <= bb_prox:
                    if n1_close > n1_open and n1_close > n2_high and n1_body_ratio >= 0.60:
                        if n_close > n1_high:
                            direction = "BUY"
                            if _bias_ok(direction) and _macd_ok(direction):
                                sl = _sl_price(direction)
                                logger.info(
                                    "[BRIEFING-LIQ-V3] %s BUY engulf@BB prox=%.1f body=%.0f%% confirm=%.1f SL=%.1f",
                                    epic, dist_to_lower / ppp, n1_body_ratio * 100, n_close, sl,
                                )
                                return {"direction": "BUY", "entry": n_close, "sl_price": sl,
                                        "source": "sweep_v3_lower", "variant": 3}

        # --- Variant 4: Strong engulfing at major briefing level ---
        if 4 in BRIEFING_LIQUIDITY_SWEEP_VARIANTS and levels:
            major_prox = 10 * ppp  # within 10 pips of major level
            n1_range = n1_high - n1_low
            n1_body = abs(n1_close - n1_open)
            n1_body_ratio = n1_body / n1_range if n1_range > 0 else 0

            if len(df_5m) >= 23:
                n2 = df_5m.iloc[-3]
                n2_close, n2_open = float(n2["close"]), float(n2["open"])
                n2_body_top = max(n2_close, n2_open)
                n2_body_bot = min(n2_close, n2_open)
                n1_body_top = max(n1_close, n1_open)
                n1_body_bot = min(n1_close, n1_open)

                for lv in levels:
                    if not lv.major:
                        continue
                    dist = abs(n1_close - lv.price)
                    if dist > major_prox:
                        continue

                    # Body engulfs previous candle body, body >= 50% of range
                    body_engulfs = n1_body_top > n2_body_top and n1_body_bot < n2_body_bot
                    if not body_engulfs or n1_body_ratio < 0.50:
                        continue

                    # Bearish engulfing at resistance → SELL
                    if n1_close < n1_open and lv.level_type == "resistance":
                        if n_close < n1_low:
                            direction = "SELL"
                            if _bias_ok(direction) and _macd_ok(direction):
                                sl = _sl_price(direction)
                                logger.info(
                                    "[BRIEFING-LIQ-V4] %s SELL engulf@level %.1f dist=%.1f pips body=%.0f%% confirm=%.1f",
                                    epic, lv.price, dist / ppp, n1_body_ratio * 100, n_close,
                                )
                                return {"direction": "SELL", "entry": n_close, "sl_price": sl,
                                        "source": f"sweep_v4_{lv.source}@{lv.price:.1f}", "variant": 4}

                    # Bullish engulfing at support → BUY
                    if n1_close > n1_open and lv.level_type == "support":
                        if n_close > n1_high:
                            direction = "BUY"
                            if _bias_ok(direction) and _macd_ok(direction):
                                sl = _sl_price(direction)
                                logger.info(
                                    "[BRIEFING-LIQ-V4] %s BUY engulf@level %.1f dist=%.1f pips body=%.0f%% confirm=%.1f",
                                    epic, lv.price, dist / ppp, n1_body_ratio * 100, n_close,
                                )
                                return {"direction": "BUY", "entry": n_close, "sl_price": sl,
                                        "source": f"sweep_v4_{lv.source}@{lv.price:.1f}", "variant": 4}

        # --- Variant 5: Wick Rejection (wick probes beyond BB, close inside, next candle confirms) ---
        if 5 in BRIEFING_LIQUIDITY_SWEEP_VARIANTS and len(df_5m) >= 22:
            _v5_wick_min_pips = 2  # wick must exceed BB by at least 2 pips

            # Upper wick → SELL
            _v5_wick_above = (n1_high - upper_n1) / ppp
            if _v5_wick_above >= _v5_wick_min_pips and n1_close <= upper_n1:
                # N-1 wicked above BB but closed inside. N confirms by closing below N-1 open.
                _v5_body_ratio = abs(n_close - n_open) / (n_high - n_low) if (n_high - n_low) > 0 else 0
                if n_close < n1_open and _v5_body_ratio >= 0.40:
                    direction = "SELL"
                    sl = n1_high + BRIEFING_LIQUIDITY_SL_BUFFER_PIPS * ppp
                    logger.info(
                        "[BRIEFING-LIQ-V5] %s SELL wick=%.1fp above BB close_inside=%.1f confirm=%.1f body_ratio=%.0f%%",
                        epic, _v5_wick_above, n1_close, n_close, _v5_body_ratio * 100,
                    )
                    return {"direction": "SELL", "entry": n_close, "sl_price": sl,
                            "source": "sweep_v5_upper", "variant": 5}

            # Lower wick → BUY
            _v5_wick_below = (lower_n1 - n1_low) / ppp
            if _v5_wick_below >= _v5_wick_min_pips and n1_close >= lower_n1:
                _v5_body_ratio = abs(n_close - n_open) / (n_high - n_low) if (n_high - n_low) > 0 else 0
                if n_close > n1_open and _v5_body_ratio >= 0.40:
                    direction = "BUY"
                    sl = n1_low - BRIEFING_LIQUIDITY_SL_BUFFER_PIPS * ppp
                    logger.info(
                        "[BRIEFING-LIQ-V5] %s BUY wick=%.1fp below BB close_inside=%.1f confirm=%.1f body_ratio=%.0f%%",
                        epic, _v5_wick_below, n1_close, n_close, _v5_body_ratio * 100,
                    )
                    return {"direction": "BUY", "entry": n_close, "sl_price": sl,
                            "source": "sweep_v5_lower", "variant": 5}

        # --- Variant 6: Extended Pierce Reversal (pierce + 1-3 candles beyond, then rejection + confirm) ---
        if 6 in BRIEFING_LIQUIDITY_SWEEP_VARIANTS and len(df_5m) >= 25:
            _v6_max_extend = 3  # max candles beyond BB before rejection

            # Check upper: look back for a pierce followed by extended candles beyond, then rejection
            for _v6_back in range(3, min(6, len(df_5m))):
                _v6_pierce_idx = -_v6_back - 1
                if abs(_v6_pierce_idx) > len(df_5m):
                    break
                _v6_pc = df_5m.iloc[_v6_pierce_idx]
                _v6_upper = float(upper.iloc[_v6_pierce_idx]) if abs(_v6_pierce_idx) <= len(upper) else 0
                _v6_lower = float(lower.iloc[_v6_pierce_idx]) if abs(_v6_pierce_idx) <= len(lower) else 0

                # Upper pierce: check if candle closed above BB
                if float(_v6_pc["close"]) > _v6_upper and _v6_upper > 0:
                    # Check that intermediate candles also closed beyond
                    _v6_all_beyond = True
                    for _v6_k in range(_v6_pierce_idx + 1, -2):
                        _v6_ic = df_5m.iloc[_v6_k]
                        _v6_iu = float(upper.iloc[_v6_k])
                        if float(_v6_ic["close"]) <= _v6_iu:
                            _v6_all_beyond = False
                            break
                    if not _v6_all_beyond:
                        continue

                    # N-1 is the rejection: must close back inside BB
                    if n1_close <= upper_n1:
                        # N is the confirm: must close below N-1 low
                        if n_close < n1_low:
                            direction = "SELL"
                            sl = max(float(_v6_pc["high"]), n1_high) + BRIEFING_LIQUIDITY_SL_BUFFER_PIPS * ppp
                            _v6_extend = _v6_back - 2  # candles spent beyond
                            logger.info(
                                "[BRIEFING-LIQ-V6] %s SELL extended_pierce (%d candles beyond) reject=%.1f confirm=%.1f",
                                epic, _v6_extend, n1_close, n_close,
                            )
                            return {"direction": "SELL", "entry": n_close, "sl_price": sl,
                                    "source": "sweep_v6_upper", "variant": 6}
                    break  # only check first valid pierce lookback

                # Lower pierce
                if float(_v6_pc["close"]) < _v6_lower and _v6_lower > 0:
                    _v6_all_beyond = True
                    for _v6_k in range(_v6_pierce_idx + 1, -2):
                        _v6_ic = df_5m.iloc[_v6_k]
                        _v6_il = float(lower.iloc[_v6_k])
                        if float(_v6_ic["close"]) >= _v6_il:
                            _v6_all_beyond = False
                            break
                    if not _v6_all_beyond:
                        continue

                    if n1_close >= lower_n1:
                        if n_close > n1_high:
                            direction = "BUY"
                            sl = min(float(_v6_pc["low"]), n1_low) - BRIEFING_LIQUIDITY_SL_BUFFER_PIPS * ppp
                            _v6_extend = _v6_back - 2
                            logger.info(
                                "[BRIEFING-LIQ-V6] %s BUY extended_pierce (%d candles beyond) reject=%.1f confirm=%.1f",
                                epic, _v6_extend, n1_close, n_close,
                            )
                            return {"direction": "BUY", "entry": n_close, "sl_price": sl,
                                    "source": "sweep_v6_lower", "variant": 6}
                    break

        return None

    # ------------------------------------------------------------------
    # Layer 5 — Opening Range Breakdown/Breakout
    # ------------------------------------------------------------------

    @staticmethod
    def _is_london_briefing(briefing: Optional[Dict[str, Any]]) -> bool:
        """Return True if this briefing is from the London session.

        Checks briefing["session"] for "London", falling back to
        briefing_time between 06:00-07:30 UTC.
        """
        if briefing is None:
            return False

        session = str(briefing.get("session") or "").strip()
        if "london" in session.lower():
            return True

        # Fallback: parse briefing_time and check 06:00-07:30 UTC window
        bt = briefing.get("briefing_time") or briefing.get("briefing_time_utc") or ""
        if bt:
            try:
                from datetime import datetime as _dt
                for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
                    try:
                        parsed = _dt.strptime(str(bt), fmt)
                        break
                    except ValueError:
                        continue
                else:
                    return False
                hour, minute = parsed.hour, parsed.minute
                total_mins = hour * 60 + minute
                # 06:00 (360) to 07:30 (450) UTC
                if 360 <= total_mins <= 450:
                    return True
            except Exception:
                pass

        return False

    def _check_opening_range(
        self,
        epic: str,
        df_5m: pd.DataFrame,
        bias: str,
        candle: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        """Detect opening range breakdown (SELL) or breakout (BUY).

        Fires within the first 3 candles after briefing active when price is
        near a BB extreme or beyond the BB midline, the candle confirms
        direction with close vs EMA_8, EMAs are stacked, and MACD agrees.
        One signal per session.
        """
        if not BRIEFING_LIQUIDITY_OPENING_RANGE_ENABLED:
            return None

        # Only fire on London session briefing
        if not self._is_london_briefing(self._current_briefing.get(epic)):
            return None

        if self._or_fired.get(epic):
            return None

        # Must be within candles 1-3 after briefing load.
        # Skip candle 0 — it may have started before the briefing loaded.
        bc = self._briefing_candle_count.get(epic, 0)
        if bc < 1 or bc > 3:
            return None

        if df_5m is None or len(df_5m) < 26:
            return None

        ppp = _get_points_per_pip(epic)
        closes = df_5m["close"].astype(float)

        # Bollinger Bands (20-period, 2σ) + midline
        sma20 = closes.rolling(20).mean()
        std20 = closes.rolling(20).std()
        upper_bb = float((sma20 + 2 * std20).iloc[-1])
        lower_bb = float((sma20 - 2 * std20).iloc[-1])
        bb_mid = float(sma20.iloc[-1])

        # EMAs (8, 13, 21)
        ema8 = float(closes.ewm(span=8, adjust=False).mean().iloc[-1])
        ema13 = float(closes.ewm(span=13, adjust=False).mean().iloc[-1])
        ema21 = float(closes.ewm(span=21, adjust=False).mean().iloc[-1])

        # MACD histogram (12, 26, 9)
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = float((macd_line - signal_line).iloc[-1])

        c_open = candle["open"]
        c_close = candle["close"]
        c_high = candle["high"]
        c_low = candle["low"]

        near_upper = (upper_bb - c_close) <= 15 * ppp
        near_lower = (c_close - lower_bb) <= 15 * ppp
        bearish_candle = c_close < c_open
        bullish_candle = c_close > c_open
        emas_bearish = ema8 < ema13 < ema21
        emas_bullish = ema8 > ema13 > ema21

        direction = None

        # SELL setup (opening range breakdown)
        if bias == "SHORT":
            price_zone = near_upper or c_close < bb_mid
            ema_confirm = c_close < ema8
            if price_zone and bearish_candle and ema_confirm and emas_bearish and macd_hist < 0:
                direction = "SELL"

        # BUY setup (opening range breakout)
        if bias == "LONG" and direction is None:
            price_zone = near_lower or c_close > bb_mid
            ema_confirm = c_close > ema8
            if price_zone and bullish_candle and ema_confirm and emas_bullish and macd_hist > 0:
                direction = "BUY"

        if direction is None:
            return None

        # SL: entry candle high + buffer (SELL) or low - buffer (BUY)
        sl_buffer_points = BRIEFING_LIQUIDITY_SL_BUFFER_PIPS * ppp
        if direction == "SELL":
            sl_price = c_high + sl_buffer_points
        else:
            sl_price = c_low - sl_buffer_points

        label = "breakdown" if direction == "SELL" else "breakout"
        logger.info(
            "[BRIEFING-LIQ-OR] %s %s opening range %s | close=%.5f open=%.5f "
            "ema8=%.5f ema13=%.5f ema21=%.5f macd_hist=%.6f "
            "bb_upper=%.5f bb_mid=%.5f bb_lower=%.5f candle=%d/3",
            epic, direction, label,
            c_close, c_open, ema8, ema13, ema21, macd_hist,
            upper_bb, bb_mid, lower_bb, bc,
        )

        return {
            "direction": direction,
            "entry": c_close,
            "sl_price": sl_price,
            "source": f"opening_range_{label}",
        }

    # ------------------------------------------------------------------
    # Layer 6 — Intraday EMA Pullback (afternoon continuation)
    # ------------------------------------------------------------------

    def _check_ema_pullback(
        self,
        epic: str,
        df_5m: pd.DataFrame,
        bias: str,
        candle: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        """Detect EMA_8 pullback-and-rejection in an established trend.

        Two-candle pattern:
          Arm:     candle high touches/crosses EMA_8 (SELL) or low touches EMA_8 (BUY)
          Confirm: next candle closes back below EMA_8 (SELL) or above EMA_8 (BUY)

        Requires:
          - EMA stack with EMA_50 (4-EMA alignment)
          - 20+ pips of established trend from session extreme
          - MACD histogram in trade direction and expanding
          - Not within first 3 London candles (opening range territory)
        """
        if not BRIEFING_LIQUIDITY_EMA_PULLBACK_ENABLED:
            return None

        if self._pb_fired.get(epic):
            return None

        # Skip first 3 candles of London briefing (opening range territory)
        bc = self._briefing_candle_count.get(epic, 0)
        if bc <= 3 and self._is_london_briefing(self._current_briefing.get(epic)):
            self._pb_armed[epic] = None
            return None

        if df_5m is None or len(df_5m) < 50:
            return None

        ppp = _get_points_per_pip(epic)
        closes = df_5m["close"].astype(float)
        highs = df_5m["high"].astype(float)
        lows = df_5m["low"].astype(float)

        # EMAs (8, 13, 21, 50)
        ema8 = float(closes.ewm(span=8, adjust=False).mean().iloc[-1])
        ema13 = float(closes.ewm(span=13, adjust=False).mean().iloc[-1])
        ema21 = float(closes.ewm(span=21, adjust=False).mean().iloc[-1])
        ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])

        # MACD histogram (12, 26, 9) — current and previous for expansion check
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal_line
        macd_hist = float(hist.iloc[-1])
        prev_macd_hist = float(hist.iloc[-2]) if len(hist) >= 2 else 0.0

        c_high = candle["high"]
        c_low = candle["low"]
        c_close = candle["close"]

        # Update session high/low tracking
        s_high = self._session_high.get(epic, c_high)
        s_low = self._session_low.get(epic, c_low)
        s_high = max(s_high, c_high)
        s_low = min(s_low, c_low)
        self._session_high[epic] = s_high
        self._session_low[epic] = s_low

        # --- Check for confirm on a previously armed pullback ---
        armed = self._pb_armed.get(epic)
        if armed is not None:
            confirmed = False
            if armed["direction"] == "SELL" and c_close < ema8:
                confirmed = True
            elif armed["direction"] == "BUY" and c_close > ema8:
                confirmed = True

            if confirmed:
                direction = armed["direction"]
                sl_buffer_points = BRIEFING_LIQUIDITY_SL_BUFFER_PIPS * ppp
                if direction == "SELL":
                    sl_price = c_high + sl_buffer_points
                else:
                    sl_price = c_low - sl_buffer_points

                logger.info(
                    "[BRIEFING-LIQ-PB] %s %s EMA pullback confirmed | close=%.5f ema8=%.5f "
                    "ema13=%.5f ema21=%.5f ema50=%.5f macd=%.6f session_range=%.1f pips",
                    epic, direction, c_close, ema8, ema13, ema21, ema50, macd_hist,
                    (s_high - s_low) / ppp,
                )
                self._pb_armed[epic] = None
                return {
                    "direction": direction,
                    "entry": c_close,
                    "sl_price": sl_price,
                    "source": "ema_pullback",
                }

            # Confirm didn't happen — disarm (one-candle window)
            self._pb_armed[epic] = None

        # --- Check for new pullback arm on current candle ---

        # EMA stack check
        if bias == "SHORT":
            if not (ema8 < ema13 < ema21 < ema50):
                return None
        elif bias == "LONG":
            if not (ema8 > ema13 > ema21 > ema50):
                return None
        else:
            return None

        # Trend established: 20+ pips from session extreme
        if bias == "SHORT":
            trend_move = (s_high - c_close) / ppp
        else:
            trend_move = (c_close - s_low) / ppp

        if trend_move < 20:
            return None
        if trend_move > 60:
            return None

        # MACD in trade direction and expanding (not flattening)
        if bias == "SHORT":
            if macd_hist >= 0:
                return None
            if abs(macd_hist) <= abs(prev_macd_hist):
                return None  # flattening
        else:
            if macd_hist <= 0:
                return None
            if abs(macd_hist) <= abs(prev_macd_hist):
                return None  # flattening

        # Pullback touch: candle wick reaches EMA_8
        if bias == "SHORT" and c_high >= ema8:
            self._pb_armed[epic] = {"direction": "SELL"}
            logger.debug(
                "[BRIEFING-LIQ-PB] %s SELL pullback armed: high=%.5f >= ema8=%.5f "
                "trend=%.1f pips macd=%.6f",
                epic, c_high, ema8, trend_move, macd_hist,
            )
        elif bias == "LONG" and c_low <= ema8:
            self._pb_armed[epic] = {"direction": "BUY"}
            logger.debug(
                "[BRIEFING-LIQ-PB] %s BUY pullback armed: low=%.5f <= ema8=%.5f "
                "trend=%.1f pips macd=%.6f",
                epic, c_low, ema8, trend_move, macd_hist,
            )

        return None

    # ------------------------------------------------------------------
    # Main evaluate entry point
    # ------------------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        epic: str,
        df_5m: pd.DataFrame,
        pip_size: float,
        mid_price: float,
        briefing: Optional[Dict[str, Any]],
        d1_candles: Optional[List[Dict[str, Any]]] = None,
        h1_candles: Optional[List[Dict[str, Any]]] = None,
        snapshot_5m: Optional[Dict[str, Any]] = None,
    ) -> StrategyDecision:
        """
        Evaluate all layers and return a StrategyDecision.

        Called on every new 5M candle close.
        d1_candles / h1_candles / snapshot_5m are accepted for backward
        compatibility but ignored — levels come from the briefing.
        """
        sym = str(symbol).upper()

        # --- Session window gate: 07:00-17:00 UTC always (London open) ---
        # Briefing fires at 05:30/06:30 to arm levels, but no trades until 07:00
        # when London liquidity is real. Previously 06:00 during BST — 06:xx was 25% WR.
        now_utc = datetime.now(timezone.utc)
        _session_start_hour = 7
        if not (_session_start_hour <= now_utc.hour < 17):
            return self._none(sym, "briefing_liq_outside_session")

        # --- Determine UTC hour from candle timestamp (backtest-safe) ---
        _utc_hour = now_utc.hour
        if df_5m is not None and len(df_5m) >= 1 and "timestamp" in df_5m.columns:
            _last_ts = df_5m["timestamp"].iloc[-1]
            if hasattr(_last_ts, "hour"):
                _utc_hour = _last_ts.hour
            elif hasattr(_last_ts, "to_pydatetime"):
                _utc_hour = _last_ts.to_pydatetime().hour
        _is_ny_session = 13 <= _utc_hour < 17

        # --- Session confidence gate: suspend when London briefing confidence too low ---
        # Only gate on the FIRST briefing of the day (London) — not mid-session/NY updates.
        # Latch the London confidence per epic per day.
        if SESSION_CONFIDENCE_GATE_ENABLED and briefing is not None:
            _bc = briefing.get("bias_confidence")
            try:
                _bc = float(_bc) if _bc is not None else 1.0
            except (ValueError, TypeError):
                _bc = 1.0

            _gate_key = f"_conf_gate_{epic}"
            _gate_day_key = f"_conf_gate_day_{epic}"
            _today = str(briefing.get("briefing_time", ""))[:10]

            # Latch on first briefing of the day only
            if _today and _today != getattr(self, _gate_day_key, ""):
                setattr(self, _gate_day_key, _today)
                _is_low = _bc < SESSION_CONFIDENCE_MIN
                setattr(self, _gate_key, _is_low)
                if _is_low:
                    logger.warning(
                        "[BRIEFING-LIQ] %s ⚠️ Low confidence session: %.2f < %.2f — "
                        "BL/WS entries suspended for today",
                        sym, _bc, SESSION_CONFIDENCE_MIN,
                    )
                    try:
                        from telegram_alerts import send_telegram_message
                        send_telegram_message(
                            f"⚠️ <b>Low confidence session</b> — {sym} confidence "
                            f"<b>{_bc:.2f}</b> (min: {SESSION_CONFIDENCE_MIN:.2f})\n"
                            f"BL/WS entries suspended for this session."
                        )
                    except Exception:
                        pass

            if getattr(self, _gate_key, False):
                return self._none(sym, f"session_confidence_gate_{_bc:.2f}")

        # --- Layer 1: Bias ---
        bias = self._get_bias(briefing)

        # --- Bias staleness decay ---
        if BIAS_STALENESS_ENABLED and bias in ("LONG", "SHORT"):
            _bt = str(briefing.get("briefing_time", "")) if briefing else ""
            anchor = self._bias_anchor.get(sym)
            if anchor is None or anchor["bias"] != bias or anchor.get("bt") != _bt:
                # New bias, bias changed, or new briefing fired — reset anchor
                self._bias_anchor[sym] = {"bias": bias, "mid": mid_price, "suspended": False, "bt": _bt}
            elif not anchor["suspended"]:
                stale_threshold = _BIAS_STALENESS_PIPS.get(sym, BIAS_STALENESS_PIPS_DEFAULT)
                displacement = mid_price - anchor["mid"]
                # Check if price moved against the bias direction
                against = (bias == "LONG" and displacement < -stale_threshold) or \
                          (bias == "SHORT" and displacement > stale_threshold)
                if against:
                    anchor["suspended"] = True
                    logger.warning(
                        "[BRIEFING-LIQ] %s bias %s SUSPENDED — price displaced %.1fp "
                        "from anchor %.1f (threshold %.0fp)",
                        sym, bias, abs(displacement), anchor["mid"], stale_threshold,
                    )
                    try:
                        from telegram_alerts import send_telegram_message
                        send_telegram_message(
                            f"\u26a0\ufe0f {sym} bias {bias} auto-suspended: "
                            f"price moved {abs(displacement):.1f}p against bias "
                            f"(threshold {stale_threshold:.0f}p). "
                            f"Treating as NEUTRAL until next briefing.",
                        )
                    except Exception:
                        pass
            if self._bias_anchor.get(sym, {}).get("suspended"):
                bias = "NONE"

        if bias == "NONE" and not _is_ny_session:
            logger.debug("[BRIEFING-LIQ] %s bias=NONE -- no trades (London/gap session)", sym)
            return self._none(sym, "briefing_liq_no_bias")
        if bias == "NONE" and _is_ny_session:
            logger.info("[BRIEFING-LIQ] %s bias=NONE but NY session — V1/V3 sweeps allowed", sym)

        # --- Layer 2: Ensure levels from briefing ---
        levels = self._ensure_levels(epic, briefing, mid_price, bias)
        if not levels and not _is_ny_session:
            return self._none(sym, "briefing_liq_no_levels")

        # --- Get latest closed candle ---
        if df_5m is None or len(df_5m) < 1:
            return self._none(sym, "briefing_liq_no_candles")

        last_row = df_5m.iloc[-1]
        candle = {
            "open": float(last_row["open"]),
            "high": float(last_row["high"]),
            "low": float(last_row["low"]),
            "close": float(last_row["close"]),
        }

        # --- Increment briefing candle counter (for opening range window) ---
        self._briefing_candle_count[epic] = self._briefing_candle_count.get(epic, 0) + 1

        # --- Candle timestamp for cooldown check ---
        candle_time: Optional[datetime] = None
        if "timestamp" in last_row.index:
            ts = last_row["timestamp"]
            if hasattr(ts, "timestamp"):
                candle_time = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                if candle_time.tzinfo is None:
                    candle_time = candle_time.replace(tzinfo=timezone.utc)

        # --- Layer 3: Advance state machines ---
        triggered = self._advance_state_machines(epic, candle, mid_price)

        # --- Update BB cache for tick-level early arm ---
        self._update_bb_cache(epic, df_5m)

        # --- Layer 4: Sweep entry trigger (V1-V4, runs alongside level triggers) ---
        bb_trigger = None
        if BRIEFING_LIQUIDITY_BB_PIERCE_ENABLED:
            bb_trigger = self._check_sweep_entry(epic, df_5m, bias, ppp=_get_points_per_pip(epic), levels=levels, utc_hour=_utc_hour)

        # --- Sweep quality gate: rejection candle + wick ratio ---
        if bb_trigger is not None and BL_REQUIRE_REJECTION_CANDLE and len(df_5m) >= 3:
            _ppp = _get_points_per_pip(epic)
            _n1 = df_5m.iloc[-2]
            _n1_o, _n1_c = float(_n1["open"]), float(_n1["close"])
            _n1_h, _n1_l = float(_n1["high"]), float(_n1["low"])
            _n1_body = abs(_n1_c - _n1_o) / _ppp
            _direction = bb_trigger["direction"]

            # Check 1: Rejection candle body must be at least BL_MIN_REJECTION_BODY pips
            # in the reversal direction
            _reversal_body = False
            if _direction == "BUY" and _n1_c > _n1_o and _n1_body >= BL_MIN_REJECTION_BODY:
                _reversal_body = True
            elif _direction == "SELL" and _n1_c < _n1_o and _n1_body >= BL_MIN_REJECTION_BODY:
                _reversal_body = True

            # Check 2: Pierce candle wick beyond BB must be >= BL_MIN_WICK_RATIO × body
            _wick_ok = True
            if BL_MIN_WICK_RATIO > 0 and len(df_5m) >= 3:
                _pc = df_5m.iloc[-3] if bb_trigger.get("variant") == 1 else _n1
                _pc_o, _pc_c = float(_pc["open"]), float(_pc["close"])
                _pc_h, _pc_l = float(_pc["high"]), float(_pc["low"])
                _pc_body = abs(_pc_c - _pc_o)
                if _pc_body > 0:
                    if _direction == "BUY":
                        _wick = _pc_o - _pc_l if _pc_c > _pc_o else _pc_c - _pc_l
                        _wick = max(0, _wick)
                    else:
                        _wick = _pc_h - _pc_o if _pc_c < _pc_o else _pc_h - _pc_c
                        _wick = max(0, _wick)
                    _wick_ok = (_wick / _pc_body) >= BL_MIN_WICK_RATIO
                # Zero-body candle: doji — wick check is automatically ok

            if not _reversal_body:
                logger.info(
                    "[BRIEFING-LIQ] %s sweep %s blocked: rejection body %.1fp < %.1fp min",
                    _pair_from_epic(epic), _direction, _n1_body, BL_MIN_REJECTION_BODY,
                )
                bb_trigger = None
            elif not _wick_ok:
                logger.info(
                    "[BRIEFING-LIQ] %s sweep %s blocked: wick ratio below %.1fx min",
                    _pair_from_epic(epic), _direction, BL_MIN_WICK_RATIO,
                )
                bb_trigger = None

        # --- BB width filter: only allow sweeps when bands are wide enough ---
        if bb_trigger is not None and SWEEP_MIN_BB_WIDTH_PIPS > 0 and len(df_5m) >= 20:
            _sw_closes = df_5m["close"].astype(float)
            _sw_sma = float(_sw_closes.rolling(20).mean().iloc[-1])
            _sw_std = float(_sw_closes.rolling(20).std().iloc[-1])
            _sw_bbw = (4 * _sw_std) / _get_points_per_pip(epic)
            if _sw_bbw < SWEEP_MIN_BB_WIDTH_PIPS:
                logger.info(
                    "[BRIEFING-LIQ] %s sweep BLOCKED: BB width %.1fp < %.1fp minimum",
                    sym, _sw_bbw, SWEEP_MIN_BB_WIDTH_PIPS,
                )
                bb_trigger = None

        # --- Layer 5: Opening range breakdown/breakout ---
        or_trigger = self._check_opening_range(epic, df_5m, bias, candle)

        # --- Layer 6: EMA pullback (afternoon continuation) ---
        pb_trigger = self._check_ema_pullback(epic, df_5m, bias, candle)

        # --- Bias filter for level trigger ---
        if triggered is not None and not self._bias_allows(bias, triggered):
            logger.info(
                "[BRIEFING-LIQ] %s BLOCKED by bias=%s direction=%s level_type=%s",
                sym, bias, triggered.direction, triggered.level.level_type,
            )
            triggered = None

        # --- GBPUSD trigger_close: re-enabled (core entry type) ---

        # --- BB proximity block (pair-specific: USDJPY/USDCAD only by default) ---
        if sym in _BB_PROXIMITY_PAIRS and (triggered is not None or or_trigger is not None or pb_trigger is not None) and df_5m is not None and len(df_5m) >= 22:
            _bb_closes = df_5m["close"].astype(float)
            _bb_sma = _bb_closes.rolling(20).mean()
            _bb_std = _bb_closes.rolling(20).std()
            _bb_upper = float((_bb_sma + 2 * _bb_std).iloc[-1])
            _bb_lower = float((_bb_sma - 2 * _bb_std).iloc[-1])
            _bb_ppp = _get_points_per_pip(epic)
            _bb_proximity = 15 * _bb_ppp

            if triggered is not None:
                _t_dir = triggered.direction
                if (_t_dir == "SELL" and (mid_price - _bb_lower) <= _bb_proximity) or \
                   (_t_dir == "BUY" and (_bb_upper - mid_price) <= _bb_proximity):
                    logger.info(
                        "[BRIEFING-LIQ] %s %s BLOCKED near opposing BB (price=%.5f upper=%.5f lower=%.5f)",
                        sym, _t_dir, mid_price, _bb_upper, _bb_lower,
                    )
                    triggered = None

            if or_trigger is not None:
                _or_dir = or_trigger["direction"]
                if (_or_dir == "SELL" and (mid_price - _bb_lower) <= _bb_proximity) or \
                   (_or_dir == "BUY" and (_bb_upper - mid_price) <= _bb_proximity):
                    logger.info(
                        "[BRIEFING-LIQ-OR] %s %s BLOCKED near opposing BB",
                        sym, _or_dir,
                    )
                    or_trigger = None

            if pb_trigger is not None:
                _pb_dir = pb_trigger["direction"]
                if (_pb_dir == "SELL" and (mid_price - _bb_lower) <= _bb_proximity) or \
                   (_pb_dir == "BUY" and (_bb_upper - mid_price) <= _bb_proximity):
                    logger.info(
                        "[BRIEFING-LIQ-PB] %s %s BLOCKED near opposing BB",
                        sym, _pb_dir,
                    )
                    pb_trigger = None

        if triggered is None and bb_trigger is None and or_trigger is None and pb_trigger is None:
            return self._none(sym, "briefing_liq_no_trigger")

        # --- Cooldown: separate for sweep variants vs level/OR/PB triggers ---
        now = candle_time or datetime.now(timezone.utc)
        _cd = timedelta(minutes=BRIEFING_LIQUIDITY_COOLDOWN_MINS)

        # Level/OR/PB cooldown (shared)
        last_sig = self._last_signal_time.get(epic)
        _level_on_cd = last_sig and (now - last_sig) < _cd
        if _level_on_cd and triggered is not None:
            triggered = None
        if _level_on_cd and or_trigger is not None:
            or_trigger = None
        if _level_on_cd and pb_trigger is not None:
            pb_trigger = None

        # Sweep cooldown (independent) — 60-min cooldown, timer + per-direction gate for others
        last_sweep = self._last_sweep_time.get(epic)
        _sweep_on_cd = last_sweep and (now - last_sweep) < _cd
        if _sweep_on_cd and bb_trigger is not None:
            logger.debug("[BRIEFING-LIQ] %s sweep cooldown active", epic)
            bb_trigger = None

        # Non-GBPUSD: per-direction gate on top of cooldown
        if bb_trigger is not None and _pair_from_epic(epic) not in ("GBPUSD", "GBPJPY"):
            _bb_v = bb_trigger.get("variant", 0)
            if _bb_v in (1, 3):
                _fired = self._sweep_dirs_fired.get(epic, set())
                if bb_trigger["direction"] in _fired:
                    logger.info(
                        "[BRIEFING-LIQ] %s sweep %s already fired this session",
                        epic, bb_trigger["direction"],
                    )
                    bb_trigger = None

        if triggered is None and bb_trigger is None and or_trigger is None and pb_trigger is None:
            return self._none(sym, "briefing_liq_cooldown")

        # --- Resolve trigger source (level trigger takes priority) ---
        ppp = _get_points_per_pip(epic)
        sl_buffer_points = BRIEFING_LIQUIDITY_SL_BUFFER_PIPS * ppp

        if triggered is not None:
            direction = triggered.direction
            lv = triggered.level
            entry_price = float(candle["close"])
            if direction == "SELL":
                sl_price = lv.price + sl_buffer_points
            else:
                sl_price = lv.price - sl_buffer_points
            trigger_source = f"{lv.level_type}/{lv.source}"
            trigger_level_price = lv.price
            entry_label = "trigger_close"
        elif bb_trigger is not None:
            direction = bb_trigger["direction"]
            entry_price = float(bb_trigger["entry"])
            pierce_extreme = float(bb_trigger["sl_price"])
            _bb_variant = bb_trigger.get("variant", 0)
            _bb_is_gbpusd = _pair_from_epic(epic) in ("GBPUSD", "GBPJPY")
            if _bb_is_gbpusd and _bb_variant in (1, 3):
                # GBPUSD/GBPJPY V1/V3: SL already set to sweep candle extreme + 5 pips
                sl_price = pierce_extreme
            elif direction == "SELL":
                sl_price = pierce_extreme + sl_buffer_points
                max_sl = entry_price + BRIEFING_LIQUIDITY_BB_PIERCE_MAX_SL_PIPS * ppp
                if sl_price > max_sl:
                    logger.info(
                        "[BRIEFING-LIQ] %s BB pierce SL capped: %.1f -> %.1f (max %d pips)",
                        epic, sl_price, max_sl, BRIEFING_LIQUIDITY_BB_PIERCE_MAX_SL_PIPS,
                    )
                    sl_price = max_sl
            else:
                sl_price = pierce_extreme - sl_buffer_points
                max_sl = entry_price - BRIEFING_LIQUIDITY_BB_PIERCE_MAX_SL_PIPS * ppp
                if sl_price < max_sl:
                    logger.info(
                        "[BRIEFING-LIQ] %s BB pierce SL capped: %.1f -> %.1f (max %d pips)",
                        epic, sl_price, max_sl, BRIEFING_LIQUIDITY_BB_PIERCE_MAX_SL_PIPS,
                    )
                    sl_price = max_sl
            trigger_source = bb_trigger["source"]
            trigger_level_price = pierce_extreme
            entry_label = f"sweep_v{_bb_variant}"
        elif or_trigger is not None:
            direction = or_trigger["direction"]
            entry_price = float(or_trigger["entry"])
            sl_price = float(or_trigger["sl_price"])
            trigger_source = or_trigger["source"]
            trigger_level_price = entry_price
            entry_label = "opening_range"
        else:
            direction = pb_trigger["direction"]
            entry_price = float(pb_trigger["entry"])
            sl_price = float(pb_trigger["sl_price"])
            trigger_source = pb_trigger["source"]
            trigger_level_price = entry_price
            entry_label = "ema_pullback"

        # --- signal_filter gate (fail-open on missing briefing) ---
        if briefing is not None:
            _sf = briefing.get("signal_filter") or {}
            if direction == "BUY" and _sf.get("allow_buys") is False:
                logger.info(
                    "[BRIEFING-LIQ] %s SIGNAL_FILTER blocked BUY — allow_buys=false",
                    sym,
                )
                return self._none(sym, "briefing_liq_signal_filter_allow_buys_false")
            if direction == "SELL" and _sf.get("allow_sells") is False:
                logger.info(
                    "[BRIEFING-LIQ] %s SIGNAL_FILTER blocked SELL — allow_sells=false",
                    sym,
                )
                return self._none(sym, "briefing_liq_signal_filter_allow_sells_false")

        # --- pre_event_blackout gate (fail-open on missing field) ---
        _peb = _pre_event_blackout_blocks(briefing, now)
        if _peb:
            logger.info(
                "[BRIEFING-LIQ] PRE_EVENT_BLACKOUT blocked %s %s — blackout %s→%s UTC",
                sym, direction, _peb["start_utc"], _peb["end_utc"],
            )
            return self._none(sym, f"briefing_liq_pre_event_blackout_{direction.lower()}")

        # --- Levels-array gate (fail-closed, same contract as BB_REVERSAL) ---
        # Runs before the OR/PB one-shot flags so a rejected candidate does not
        # consume the trigger slot for this session.
        _lv_match = _match_levels_array(
            briefing, trigger_level_price, direction, ppp,
            BRIEFING_LIQUIDITY_LEVELS_PROXIMITY_PIPS,
        )
        if _lv_match is None:
            logger.info(
                "[BRIEFING-LIQ] PIERCE-REJECT %s %s reason=no_levels_match_within_%.1fp "
                "entry=%.1f source=%s (required: trade_direction=%s, intent in {BOUNCE,FADE}, "
                "strength in {HIGH,MEDIUM})",
                sym, direction, BRIEFING_LIQUIDITY_LEVELS_PROXIMITY_PIPS,
                trigger_level_price, entry_label, direction,
            )
            return self._none(sym, f"briefing_liq_no_levels_match_{direction.lower()}")
        logger.info(
            "[BRIEFING-LIQ] PIERCE-MATCH %s %s entry=%.1f source=%s level_price=%.1f "
            "type=%s intent=%s strength=%s dist=%.2fp",
            sym, direction, trigger_level_price, entry_label,
            _lv_match["price"], _lv_match.get("type"), _lv_match.get("intent"),
            _lv_match.get("strength"), _lv_match["dist_pips"],
        )

        # --- fade_after_sweep gate (fail-open) ---
        _fade_sd = _fade_gate_blocks(briefing, direction)
        if _fade_sd:
            logger.info(
                "[BRIEFING-LIQ] FADE_GATE blocked %s %s — briefing expects sweep %s, fade only",
                sym, direction, _fade_sd,
            )
            return self._none(sym, f"briefing_liq_fade_gate_{direction.lower()}")

        # One-shot flags: set only after the gate passes so rejected OR/PB
        # candidates can retry on later bars in the same session.
        if or_trigger is not None and entry_label == "opening_range":
            self._or_fired[epic] = True
        elif entry_label == "ema_pullback":
            self._pb_fired[epic] = True

        if direction == "SELL":
            sl_pips = (sl_price - entry_price) / ppp
        else:
            sl_pips = (entry_price - sl_price) / ppp

        if sl_pips <= 0:
            logger.warning(
                "[BRIEFING-LIQ] %s %s | zero SL (%.1f) -- skipping",
                sym, direction, sl_pips,
            )
            return self._none(sym, "briefing_liq_bad_rr")

        # --- Enforce per-pair minimum SL floor (before TP plan so R:R is correct) ---
        from pair_config import MIN_SL_PIPS as _min_sl_map
        _pair = _pair_from_epic(epic)
        _min_sl = _min_sl_map.get(_pair, 0)
        if sl_pips < _min_sl:
            logger.info(
                "[BRIEFING-LIQ] %s %s SL %.1f below pair min %.1f — widening",
                sym, direction, sl_pips, _min_sl,
            )
            sl_pips = _min_sl
            if direction == "SELL":
                sl_price = entry_price + sl_pips * ppp
            else:
                sl_price = entry_price - sl_pips * ppp

        # --- Multi-level TP plan from briefing levels ---
        tp_plan = self._find_tp_plan(
            direction, entry_price, sl_pips, levels, ppp, briefing,
        )
        tp1 = tp_plan[0]
        tp2 = tp_plan[1] if len(tp_plan) > 1 else None
        tp3 = tp_plan[2] if len(tp_plan) > 2 else None

        debug = {
            "bias": bias,
            "level_price": round(trigger_level_price, 5),
            "trigger_source": trigger_source,
            "entry_source": entry_label,
            "armed_at_candle": triggered.armed_at_candle if triggered else None,
            "sl_pips": round(sl_pips, 2),
            "sl_price": round(sl_price, 1),
            "sl_source": entry_label,
            "tp_plan": tp_plan,
            "tp1_pips": tp1["pips"],
            "tp1_price": tp1["price"],
            "tp1_source": tp1["source"],
            "tp2_pips": tp2["pips"] if tp2 else None,
            "tp2_price": tp2["price"] if tp2 else None,
            "tp2_source": tp2["source"] if tp2 else None,
            "tp3_pips": tp3["pips"] if tp3 else None,
            "tp3_price": tp3["price"] if tp3 else None,
            "tp3_source": tp3["source"] if tp3 else None,
            "total_levels": len(levels),
            "briefing_level": _lv_match,
        }

        tp_summary = " | ".join(
            f"TP{i+1}={t['pips']:.1f} ({t['source']})"
            for i, t in enumerate(tp_plan)
        )
        logger.info(
            "[BRIEFING-LIQ] %s %s @ %.5f (%s) | trigger=%.5f (%s) | bias=%s | SL=%.1f | %s%s",
            sym, direction, entry_price,
            entry_label,
            trigger_level_price, trigger_source,
            bias, sl_pips, tp_summary,
            " [OBSERVE-ONLY]" if BRIEFING_LIQUIDITY_OBSERVE else "",
        )

        if BRIEFING_LIQUIDITY_OBSERVE:
            return self._none(sym, f"briefing_liq_observe_{direction.lower()}")

        # --- Session entry limit ---
        max_ent = _max_entries_for_epic(epic)
        cur_ent = self._session_entries.get(epic, 0)
        if cur_ent >= max_ent:
            logger.info(
                "[BRIEFING-LIQ] %s session entry limit reached (%d/%d) — no further entries this session",
                _pair_from_epic(epic), cur_ent, max_ent,
            )
            return self._none(sym, "briefing_liq_session_limit")
        self._session_entries[epic] = cur_ent + 1
        _persist_session_entries(self._session_entries, self._last_briefing_time)

        # Record cooldown on the correct tracker
        if entry_label.startswith("sweep_v"):
            self._last_sweep_time[epic] = now
            if _pair_from_epic(epic) in ("GBPUSD", "GBPJPY"):
                self._sweep_dirs_fired.setdefault(epic, set()).add(direction)
        else:
            self._last_signal_time[epic] = now
        # GBPUSD/GBPJPY: hold to TP1, no trail — SL or TP1 only
        # Applies to V1/V3 sweeps AND trigger_close (TP1 is a real briefing level)
        _gbp_hold_to_tp1 = (
            _pair_from_epic(epic) in ("GBPUSD", "GBPJPY")
            and (
                entry_label == "trigger_close"
                or (entry_label.startswith("sweep_v")
                    and any(entry_label.startswith(f"sweep_v{v}") for v in (1, 3)))
            )
        )
        return StrategyDecision(
            symbol=sym,
            regime="SWEEP",
            signal=direction,
            mode=BRIEFING_LIQUIDITY_MODE,
            entry=float(entry_price),
            sl=float(sl_pips),
            tp=float(tp1["pips"]),
            use_trailing_stop=not _gbp_hold_to_tp1,
            reason=f"briefing_liq_{direction.lower()}",
            debug=debug,
        )

    # ------------------------------------------------------------------
    # TP helper — multi-level TP plan from briefing levels
    # ------------------------------------------------------------------

    @staticmethod
    def _find_tp_plan(
        direction: str,
        entry: float,
        sl_pips: float,
        levels: List[LiquidityLevel],
        ppp: float,
        briefing: Optional[Dict[str, Any]] = None,
    ) -> list[dict]:
        """Find up to 3 TP levels from briefing levels in trade direction.

        SELL: support levels below entry, nearest first.
        BUY: resistance levels above entry, nearest first.

        Returns list of dicts: [{pips, price, source}, ...] (1-3 items).
        Falls back to session extreme (lowest support / highest resistance),
        then SL * 4.0 if no qualifying level meets 1.5R.

        If the briefing provides session_low_estimate (SELL) or
        session_high_estimate (BUY) beyond existing TP levels, it is
        appended as TP3.
        """
        min_rr = BRIEFING_LIQUIDITY_MIN_RR
        min_tp1 = BRIEFING_LIQUIDITY_MIN_TP1_PIPS

        if direction == "SELL":
            candidates = sorted(
                [lv for lv in levels if lv.price < entry],
                key=lambda lv: lv.price,
                reverse=True,  # nearest first
            )
        else:
            candidates = sorted(
                [lv for lv in levels if lv.price > entry],
                key=lambda lv: lv.price,  # nearest first
            )

        # --- TP1: prefer nearest major level meeting R:R + min distance,
        #     else nearest any level meeting both criteria ---
        plan: list[dict] = []
        tp1_found_at = None  # index into candidates where TP1 was found

        # First pass: nearest major level that meets R:R and min distance
        for i, lv in enumerate(candidates):
            if not lv.major:
                continue
            dist_pips = abs(entry - lv.price) / ppp
            if dist_pips >= sl_pips * min_rr and dist_pips >= min_tp1:
                plan.append({
                    "pips": round(dist_pips, 2),
                    "price": round(lv.price, 1),
                    "source": f"{lv.source}@{round(lv.price, 1)}",
                })
                tp1_found_at = i
                break

        # Second pass: fall back to nearest any level meeting R:R and min distance
        if not plan:
            for i, lv in enumerate(candidates):
                dist_pips = abs(entry - lv.price) / ppp
                if dist_pips >= sl_pips * min_rr and dist_pips >= min_tp1:
                    plan.append({
                        "pips": round(dist_pips, 2),
                        "price": round(lv.price, 1),
                        "source": f"{lv.source}@{round(lv.price, 1)}",
                    })
                    tp1_found_at = i
                    break

        # Fallback TP1 if no level meets the R:R threshold
        # 1) Try session extreme from briefing levels (lowest support for SELL,
        #    highest resistance for BUY) — structurally meaningful target.
        # 2) If that still doesn't meet 1.5R, use SL × 4.0 as final fallback.
        if not plan:
            extreme_price = None
            if direction == "SELL":
                support_levels = [lv for lv in levels if lv.level_type == "support" and lv.price < entry]
                if support_levels:
                    extreme_price = min(lv.price for lv in support_levels)
            else:
                resist_levels = [lv for lv in levels if lv.level_type == "resistance" and lv.price > entry]
                if resist_levels:
                    extreme_price = max(lv.price for lv in resist_levels)

            if extreme_price is not None:
                extreme_pips = abs(entry - extreme_price) / ppp
                if extreme_pips >= sl_pips * min_rr and extreme_pips >= min_tp1:
                    plan.append({
                        "pips": round(extreme_pips, 2),
                        "price": round(extreme_price, 1),
                        "source": f"fallback_session_extreme@{round(extreme_price, 1)}",
                    })

            # Final fallback: SL × 4.0 (at least min_tp1)
            if not plan:
                fallback_pips = max(round(sl_pips * 4.0, 2), min_tp1)
                if direction == "SELL":
                    fallback_price = round(entry - fallback_pips * ppp, 1)
                else:
                    fallback_price = round(entry + fallback_pips * ppp, 1)
                plan.append({
                    "pips": fallback_pips,
                    "price": fallback_price,
                    "source": "fallback_sl_x4.0",
                })

        # --- TP2/TP3: next levels beyond TP1, no R:R minimum ---
        remaining = candidates[tp1_found_at + 1:] if tp1_found_at is not None else candidates
        for lv in remaining:
            dist_pips = abs(entry - lv.price) / ppp
            # Must be further than the last TP in the plan
            if dist_pips <= plan[-1]["pips"]:
                continue
            # Skip levels too close to the previous TP (< 3 pips apart)
            if abs(dist_pips - plan[-1]["pips"]) < 3:
                continue
            plan.append({
                "pips": round(dist_pips, 2),
                "price": round(lv.price, 1),
                "source": f"{lv.source}@{round(lv.price, 1)}",
            })
            if len(plan) >= 3:
                break

        # --- Session H/L estimate as additional TP3 ---
        # If briefing provides session_low_estimate (SELL) or session_high_estimate
        # (BUY) beyond the furthest TP, use it as TP3.
        if len(plan) < 3 and briefing is not None:
            est = None
            if direction == "SELL":
                raw = briefing.get("session_low_estimate")
                if raw is not None:
                    est = float(raw)
            else:
                raw = briefing.get("session_high_estimate")
                if raw is not None:
                    est = float(raw)

            if est is not None:
                est_pips = abs(entry - est) / ppp
                # Must be in the right direction and further than the last TP
                in_direction = (direction == "SELL" and est < entry) or (direction == "BUY" and est > entry)
                further = est_pips > plan[-1]["pips"] if plan else True
                not_too_close = abs(est_pips - plan[-1]["pips"]) >= 3 if plan else True
                if in_direction and further and not_too_close:
                    plan.append({
                        "pips": round(est_pips, 2),
                        "price": round(est, 1),
                        "source": f"session_{'low' if direction == 'SELL' else 'high'}_estimate",
                    })

        return plan

    # ------------------------------------------------------------------
    @staticmethod
    def _none(sym: str, reason: str) -> StrategyDecision:
        return StrategyDecision(
            symbol=sym,
            regime="SWEEP",
            signal="NONE",
            mode=BRIEFING_LIQUIDITY_MODE,
            entry=None,
            sl=None,
            tp=None,
            use_trailing_stop=False,
            reason=reason,
        )
