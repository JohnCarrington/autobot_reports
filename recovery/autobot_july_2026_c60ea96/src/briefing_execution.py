# =========================
# FILE: briefing_execution.py
# =========================
# BRIEFING_EXECUTION strategy — trades directly from briefing trading_plans[0].
#
# On each new briefing: read trading_plans[0] if probability >= 0.50 and
# confidence is MEDIUM or HIGH.  Store entry_zone, stop_loss, targets, and
# invalidation level.
#
# Two-phase entry:
#   Phase 1 (SWEEP_SEEN) — price must touch or exceed the sweep level
#       (top of entry_zone for SELL, bottom for BUY).
#   Phase 2 (ENTRY) — a 5M candle must close back inside the entry_zone
#       from the sweep side (closes below entry_zone[1] for SELL, above
#       entry_zone[0] for BUY).
#
# Monitor invalidation: if a 5M candle closes beyond the invalidation level,
# force close.
#
# Respect exit timing: if the briefing specifies a forced exit time (e.g.
# news_context.avoid_before or "exit before 12:00 UTC" in notes), force
# close at that time.
#
# Enable via BRIEFING_EXECUTION_ENABLED=1.

from __future__ import annotations

import json
import os
import re
import logging
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

from briefing_direction import resolve_briefing_direction

logger = logging.getLogger("AutoBot")

BRIEFING_TREND_ENTRY_MIN_MINUTES = float(os.getenv("BRIEFING_TREND_ENTRY_MIN_MINUTES", "30"))

# Per-arm dedup state persisted across process restarts. The bot is restarted
# multiple times per session as the operator iterates on strategies; without
# disk persistence, in-memory _entered is lost on each restart and the same
# briefing arm can re-fire on every fresh process. This cache survives
# restarts so dedup holds for the lifetime of the briefing arm.
#
# Schema: {"USDJPY": {"briefing_time": "...", "fired_at": epoch_seconds}, ...}
# One key per pair, overwritten on each fresh entry. Tiny, no GC needed.
ENTERED_CACHE_PATH = os.getenv(
    "BRIEFING_EXECUTION_ENTERED_CACHE",
    "/opt/tradingbot/cache/briefing_execution_entered.json",
)


def _load_entered_cache() -> Dict[str, Dict[str, Any]]:
    """Read the dedup cache from disk. Tolerates missing or corrupt file."""
    try:
        with open(ENTERED_CACHE_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        logger.warning("[BRIEFING-EXEC] dedup cache at %s not a dict — ignoring", ENTERED_CACHE_PATH)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("[BRIEFING-EXEC] dedup cache load failed (%s) — treating as empty", e)
    return {}


def _save_entered_cache(data: Dict[str, Dict[str, Any]]) -> None:
    """Atomic write: tmp + rename. Tolerates write failure (logs warning)."""
    try:
        os.makedirs(os.path.dirname(ENTERED_CACHE_PATH), exist_ok=True)
        tmp = ENTERED_CACHE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, ENTERED_CACHE_PATH)
    except Exception as e:
        logger.warning("[BRIEFING-EXEC] dedup cache save failed (%s)", e)


def _plan_id_for(plan: Dict[str, Any]) -> str:
    """Deterministic plan_id from (session, rank): 'London_1', 'NY_2', etc.

    Returns 'unknown_unknown' with a WARNING log on malformed input
    (missing session or non-int rank). Chosen so plan_id never raises and
    downstream observability stays live even if a malformed plan reaches
    the fire emit. The 'unknown_unknown' sentinel is recognisable in logs
    and distinct from any valid (session, rank) composite.
    """
    sess = plan.get("session")
    rk = plan.get("rank")
    if not isinstance(sess, str) or not sess.strip() or not isinstance(rk, int):
        logger.warning(
            "[BRIEFING-EXEC] plan_id derivation: malformed plan "
            "session=%r rank=%r — using 'unknown_unknown'",
            sess, rk,
        )
        return "unknown_unknown"
    return f"{sess}_{rk}"


BRIEFING_EXECUTION_ENABLED = os.getenv(
    "BRIEFING_EXECUTION_ENABLED", "0"
).strip().lower() in ("1", "true", "yes")

BRIEFING_EXECUTION_MODE = "BRIEFING_EXECUTION"

# entry_trigger_v2 enforcement gate. Three modes:
#   off    — ignore entry_trigger_v2 entirely (default)
#   shadow — evaluate on every entry attempt, log, do NOT block
#   live   — evaluate and block entries that fail
# Ships "off" by default; operator flips to "shadow" post-deploy for a 48h
# observation window, then "live" on signal. Unknown values → off.
_TRIGGER_V2_VALID_MODES = ("off", "shadow", "live")
BRIEFING_EXEC_TRIGGER_V2_MODE = (
    os.getenv("BRIEFING_EXEC_TRIGGER_V2_MODE", "off").strip().lower()
)
if BRIEFING_EXEC_TRIGGER_V2_MODE not in _TRIGGER_V2_VALID_MODES:
    logger.warning(
        "[BRIEFING-EXEC] invalid BRIEFING_EXEC_TRIGGER_V2_MODE=%r — falling back to 'off'",
        BRIEFING_EXEC_TRIGGER_V2_MODE,
    )
    BRIEFING_EXEC_TRIGGER_V2_MODE = "off"

# Levels-array entry match. Historically a hard veto (reject entry if no
# qualifying BOUNCE/FADE, HIGH/MEDIUM level within proximity). 21-day audit
# (2026-04-21) showed 10 of 11 blocks resulted in the plan never firing, and
# counterfactual simulation estimated +40-50p net improvement if removed.
# Now default-advisory: the match is computed for Telegram/debug display and
# logged when absent, but does not veto. Set
# BRIEFING_EXEC_LEVELS_ARRAY_GATE_ENABLED=1 to restore the hard gate.
from briefing_liquidity import (
    _match_levels_array as _bl_match_levels_array,
    BRIEFING_LIQUIDITY_LEVELS_PROXIMITY_PIPS as _BE_LEVELS_PROXIMITY_PIPS,
)

_BE_LEVELS_ARRAY_GATE_ENABLED = str(
    os.getenv("BRIEFING_EXEC_LEVELS_ARRAY_GATE_ENABLED", "0")
).strip().lower() in ("1", "true", "yes")


# Deepest-target TP selection. 2026-04-21 retrospective on 54 matched
# BRIEFING_EXECUTION trades showed aggregate +64p improvement when using
# targets[-1] instead of targets[0]; GBPJPY was the single pair where
# targets[-1] was too ambitious (median 36p distance, stop-hunts before TP2).
# Enabled by default; GBPJPY pinned to targets[0] via skip list.
_BE_USE_DEEPEST_TARGET = str(
    os.getenv("BRIEFING_EXEC_USE_DEEPEST_TARGET", "1")
).strip().lower() in ("1", "true", "yes")

_BE_DEEPEST_TARGET_SKIP_PAIRS = frozenset(
    p.strip().upper()
    for p in os.getenv("BRIEFING_EXEC_DEEPEST_TARGET_SKIP_PAIRS", "GBPJPY").split(",")
    if p.strip()
)

# Regime-based TP modulation (Phase 4B classifier magnitude axis).
# When enabled, TRENDING regime → deepest target, RANGE regime → nearest
# target. NEUTRAL / None falls through to existing target-selection
# logic. Default off so the wiring lands observable-only first.
_REGIME_TP_MOD_ENABLED = str(
    os.getenv("REGIME_CLASSIFIER_TP_MODULATION_ENABLED", "0")
).strip().lower() in ("1", "true", "yes")


def _select_tp_target(
    plan: Dict[str, Any],
    symbol: str,
    entry_price: Optional[float] = None,
    direction: Optional[str] = None,
) -> Tuple[Optional[float], int, str]:
    """Pick the TP price from a plan's targets array.

    Returns (target_price, target_index, reason). target_index is the index
    into plan["targets"] used; reason is a short tag for logging.

    Behaviour:
      - targets empty → (None, -1, "no_targets")
      - env BRIEFING_EXEC_USE_DEEPEST_TARGET=0 → targets[0] (legacy)
      - symbol in BRIEFING_EXEC_DEEPEST_TARGET_SKIP_PAIRS → targets[0]
      - entry_price given: among targets still ahead of entry in the trade
        direction, pick the deepest (furthest from entry). If none are
        ahead, fall back to the plan's deepest regardless (TREND_ENTRY's
        "auto-promote" check already vetoes when all targets are past).
      - entry_price not given: return targets[-1].
    """
    raw = plan.get("targets") or []
    targets: List[float] = []
    for t in raw:
        if t is None:
            continue
        try:
            targets.append(float(t))
        except (TypeError, ValueError):
            continue
    if not targets:
        return None, -1, "no_targets"

    sym_u = (symbol or "").upper()

    # Regime-based modulation. TRENDING → deepest, RANGE → nearest,
    # NEUTRAL/None → fall through. Pair-skip list still wins — it
    # represents pair-specific empirical evidence (GBPJPY 36p TP2
    # stop-hunts) that overrides regime intent.
    #
    # Observable-only: when flag=0, log what the live mode WOULD have
    # selected so we can see the modulation behaviour before enabling.
    if sym_u not in _BE_DEEPEST_TARGET_SKIP_PAIRS:
        try:
            from strategy_logic import get_last_regime_label
            _regime = get_last_regime_label(sym_u)
        except Exception:
            _regime = None
        _would = None
        if _regime == "TRENDING":
            _would = (targets[-1], len(targets) - 1, "regime_trending_deepest")
        elif _regime == "RANGE":
            _would = (targets[0], 0, "regime_range_nearest")

        if _would is not None:
            if _REGIME_TP_MOD_ENABLED:
                logger.info(
                    "[REGIME-TP] %s %s → using target %d/%d: %.5f",
                    sym_u, _regime, _would[1] + 1, len(targets), _would[0],
                )
                return _would
            logger.info(
                "[REGIME-TP-OBS] %s %s → would use target %d/%d: %.5f "
                "(flag off, falling through)",
                sym_u, _regime, _would[1] + 1, len(targets), _would[0],
            )
        # NEUTRAL or None: fall through to existing logic below.

    if not _BE_USE_DEEPEST_TARGET:
        return targets[0], 0, "env_disabled"
    if sym_u in _BE_DEEPEST_TARGET_SKIP_PAIRS:
        return targets[0], 0, f"pair_skip:{sym_u}"

    if entry_price is not None and direction is not None:
        ahead = []
        for i, t in enumerate(targets):
            if direction == "BUY" and t > entry_price:
                ahead.append((i, t))
            elif direction == "SELL" and t < entry_price:
                ahead.append((i, t))
        if ahead:
            if direction == "BUY":
                i, t = max(ahead, key=lambda x: x[1])
            else:
                i, t = min(ahead, key=lambda x: x[1])
            return t, i, "deepest_ahead_of_entry"

    return targets[-1], len(targets) - 1, "deepest"


def _parse_sweep_level(
    text: str,
    entry_zone: Tuple[float, float],
) -> Tuple[Optional[float], Optional[str]]:
    """Extract the deeper liquidity level that price must reach before Phase 1 arms.

    Looks for sweep/hunt/wick/break/spike phrases in the plan's entry_trigger
    text and returns the first price that lies OUTSIDE the entry zone (i.e. the
    deeper liquidity level the plan expects price to tag before returning to the
    zone for the actual entry).

    Returns (price, side) where side is 'below' or 'above', or (None, None) if
    no deeper sweep level was referenced (caller should fall back to
    zone-edge arming).

    Examples:
        "Price sweeps below 13250 into 13246-13240 zone..." → (13250.0, 'below')
        "5M sweep of 13390-13400 with long wick rejection..." → (13390.0, 'below')
        "5M close below 13278 with body close in lower 50%..." → (None, None)
          (no sweep/hunt language; 13278 is inside/near the entry zone)
    """
    if not text:
        return None, None
    zone_lo = float(min(entry_zone))
    zone_hi = float(max(entry_zone))

    pattern = (
        r'\b(?:sweep[s]?|hunt[s]?|wick[s]?|spike[s]?|probe[s]?|grab[s]?)\b'
        r'[^.]{0,60}?'
        r'(\d{4,6}(?:\.\d+)?)'
    )
    for m in re.finditer(pattern, text, re.IGNORECASE):
        try:
            price = float(m.group(1))
        except (TypeError, ValueError):
            continue
        if price < zone_lo:
            return price, 'below'
        if price > zone_hi:
            return price, 'above'

    return None, None


# Timeframes recognised by the invalidation parser. Order matters in the
# regex (longer aliases first), but selection on multi-match prefers the
# longest TF (h1 > 15m > 5m) — see _parse_invalidation.
_INV_TF_RANK = {"h1": 3, "15m": 2, "5m": 1}

_INV_TF_NORMALISE = {
    "h1":      "h1",  "1h":       "h1",  "hourly":   "h1",
    "15m":     "15m", "15min":    "15m", "15minute": "15m",
    "5m":      "5m",  "5min":     "5m",  "5minute":  "5m",
}

# Combined pattern: "<tf>? close (back )?(above|below) <price>" — captures
# the timeframe, direction, and price as a single paired clause so we don't
# mismatch a tf from one clause with a price from another.
_INV_PAIRED_RE = re.compile(
    r'(?:(h1|1h|hourly|15-?min(?:ute)?|5-?min(?:ute)?|15m|5m)\s+)?'
    r'close\s*(?:back\s+)?(above|below)\s+(\d{4,6}(?:\.\d+)?)',
    re.IGNORECASE,
)


def _parse_invalidation(text: str) -> Tuple[Optional[float], Optional[str], str]:
    """Extract (price, direction, timeframe) from invalidation text.

    timeframe ∈ {"5m", "15m", "h1"}; defaults to "5m" when the text doesn't
    name one. When multiple "<tf> close <dir> <price>" clauses match, the
    one with the LONGEST timeframe wins (h1 > 15m > 5m) — invalidating on
    a higher timeframe is the more conservative choice.

    Falls back to the legacy first-number + bias-inference path for texts
    that don't fit the paired shape (e.g. "Reclaim of 13571.6", "break of
    11702 stop"). Fallback always returns timeframe="5m".

    Examples:
        "H1 close above 13615 or failure to sweep 13610 by 09:00 UTC"
            → (13615.0, "above", "h1")
        "Second 5M close below 13571.65 or H1 close below 13570"
            → (13570.0, "below", "h1")   # h1 clause wins on multi-match
        "15M close above 11750 or failure to sweep 11741.7 by 10:00 UTC"
            → (11750.0, "above", "15m")
        "5M close back above 13432 (H1 EMA8) negates …"
            → (13432.0, "above", "5m")
        "Reclaim of 13571.6"
            → (13571.6, None, "5m")  # fallback
    """
    if not text:
        return None, None, "5m"

    # Paired extraction — matches each "<tf>? close (back )?(above|below) <price>"
    # clause as one unit, avoiding tf/price mismatch across "or"-joined clauses.
    best_rank = -1
    best_price: Optional[float] = None
    best_dir: Optional[str] = None
    best_tf: str = "5m"
    for m in _INV_PAIRED_RE.finditer(text):
        raw_tf = (m.group(1) or "").lower().replace("-", "")
        tf = _INV_TF_NORMALISE.get(raw_tf, "5m")
        direction = m.group(2).lower()
        price = float(m.group(3))
        rank = _INV_TF_RANK.get(tf, 1)
        if rank > best_rank:
            best_rank = rank
            best_price = price
            best_dir = direction
            best_tf = tf

    if best_price is not None:
        return best_price, best_dir, best_tf

    # Fallback: no "<tf>? close <dir> <price>" pattern matched. Use first
    # numeric in text + bias-inference (legacy behaviour).
    prices = re.findall(r'\b(\d{4,6}(?:\.\d+)?)\b', text)
    if prices:
        price = float(prices[0])
        low = text.lower()
        if "above" in low:
            return price, "above", "5m"
        if "below" in low:
            return price, "below", "5m"
        return price, None, "5m"

    return None, None, "5m"


def _parse_exit_time(plan: Dict, briefing: Dict) -> Optional[Tuple[int, int]]:
    """Extract forced-exit time (hour, minute) UTC from briefing/plan.

    Priority:
        1. news_context.avoid_before  (explicit array of "HH:MM")
        2. plan notes / plan_summary  (free-text "before HH:MM UTC")
    """
    # 1. news_context.avoid_before
    news_ctx = briefing.get("news_context") or {}
    avoid_before = news_ctx.get("avoid_before", [])
    if avoid_before:
        for t in avoid_before:
            try:
                parts = str(t).split(":")
                return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except Exception:
                continue

    # 2. Free-text in notes / plan_summary
    search_texts = [
        str(plan.get("notes", "") or ""),
        str(briefing.get("plan_summary", "") or ""),
    ]
    for txt in search_texts:
        m = re.search(
            r'(?:before|by)\s+(\d{1,2}):(\d{2})\s*(?:UTC)?',
            txt, re.IGNORECASE,
        )
        if m:
            return (int(m.group(1)), int(m.group(2)))

    return None


# =====================================================================
# entry_trigger_v2 — parsing + evaluation
# =====================================================================
# The briefing schema (morning_briefing._validate_trigger_v2_on_plans)
# already guarantees well-formed v2 conditions before they reach us, but
# the executor repeats enough cheap checks to stay defensive against
# out-of-band plan sources (tests, replay tools, hand-edited briefings).

_TV2_TYPES    = {"release_event", "sweep", "candle_close", "rsi", "consecutive_closes"}
_TV2_SIDES    = {"above", "below"}
_TV2_TFS      = {"5m", "15m", "1h"}
_TV2_RSI_OPS  = {"<", ">", "crosses_up", "crosses_down"}
_TV2_CURR     = {"GBP", "USD", "EUR", "JPY", "CAD"}
_TV2_IMPACTS  = {"HIGH", "MEDIUM"}

# Emit the "no calendar" warning only once per process to avoid log spam.
_tv2_calendar_warn_emitted: bool = False


def _parse_entry_trigger_v2(
    raw: Any, sym: str, plan_label: str,
) -> Optional[List[Dict[str, Any]]]:
    """Parse and normalize a plan's entry_trigger_v2 list.

    Returns a list of normalized condition dicts on success, or None if
    raw is absent/null/malformed. On malformed input logs ERROR and
    returns None — the caller should fall through to legacy gating for
    this plan only.
    """
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) == 0 or len(raw) > 5:
        logger.error(
            "[BRIEFING-EXEC] %s plan=%r entry_trigger_v2 not a 1..5-length list — ignoring",
            sym, plan_label,
        )
        return None

    out: List[Dict[str, Any]] = []
    for idx, c in enumerate(raw):
        if not isinstance(c, dict):
            logger.error(
                "[BRIEFING-EXEC] %s plan=%r entry_trigger_v2[%d] not a dict — dropping all",
                sym, plan_label, idx,
            )
            return None
        ctype = str(c.get("type") or "").strip()
        if ctype not in _TV2_TYPES:
            logger.error(
                "[BRIEFING-EXEC] %s plan=%r entry_trigger_v2[%d] type=%r unknown — dropping all",
                sym, plan_label, idx, ctype,
            )
            return None

        try:
            if ctype == "release_event":
                cond = {
                    "type": "release_event",
                    "event_name": str(c["event_name"]).strip(),
                    "currency":   str(c["currency"]).strip().upper(),
                    "window_minutes_before": int(c["window_minutes_before"]),
                    "window_minutes_after":  int(c["window_minutes_after"]),
                    "impact":     str(c["impact"]).strip().upper(),
                }
                if (cond["currency"] not in _TV2_CURR or
                        cond["impact"] not in _TV2_IMPACTS or
                        not cond["event_name"] or
                        cond["window_minutes_before"] < 0 or
                        cond["window_minutes_after"]  <= 0):
                    raise ValueError("release_event fields out of range")

            elif ctype == "sweep":
                cond = {
                    "type": "sweep",
                    "level": float(c["level"]),
                    "side":  str(c["side"]).strip().lower(),
                    "tolerance_pips": float(c["tolerance_pips"]),
                }
                if cond["side"] not in _TV2_SIDES or cond["tolerance_pips"] < 0:
                    raise ValueError("sweep fields out of range")

            elif ctype == "candle_close":
                cond = {
                    "type": "candle_close",
                    "timeframe": str(c["timeframe"]).strip().lower(),
                    "direction": str(c["direction"]).strip().lower(),
                    "level":     float(c["level"]),
                }
                if cond["timeframe"] not in _TV2_TFS or cond["direction"] not in _TV2_SIDES:
                    raise ValueError("candle_close fields out of range")

            elif ctype == "rsi":
                cond = {
                    "type": "rsi",
                    "timeframe": str(c["timeframe"]).strip().lower(),
                    "operator":  str(c["operator"]).strip(),
                    "value":     float(c["value"]),
                }
                if (cond["timeframe"] not in _TV2_TFS or
                        cond["operator"] not in _TV2_RSI_OPS or
                        not (0.0 <= cond["value"] <= 100.0)):
                    raise ValueError("rsi fields out of range")

            else:  # consecutive_closes
                cond = {
                    "type": "consecutive_closes",
                    "timeframe": str(c["timeframe"]).strip().lower(),
                    "direction": str(c["direction"]).strip().lower(),
                    "level":     float(c["level"]),
                    "count":     int(c["count"]),
                }
                if (cond["timeframe"] not in _TV2_TFS or
                        cond["direction"] not in _TV2_SIDES or
                        cond["count"] < 1):
                    raise ValueError("consecutive_closes fields out of range")
        except (KeyError, TypeError, ValueError) as pe:
            logger.error(
                "[BRIEFING-EXEC] %s plan=%r entry_trigger_v2[%d] (%s) parse error %s: %s",
                sym, plan_label, idx, ctype, type(pe).__name__, pe,
            )
            return None

        out.append(cond)

    return out


def _tv2_resample(df_5m: Any, tf: str) -> Any:
    """Resample a 5m OHLC frame to 15m or 1h. Returns df_5m unchanged for tf=5m."""
    if tf == "5m":
        return df_5m
    try:
        rule = "15min" if tf == "15m" else "1h"
        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        # Expect a DatetimeIndex-like frame; if not, let the except handle it.
        return df_5m.resample(rule).agg(agg).dropna()
    except Exception as e:
        logger.debug("[BRIEFING-EXEC] resample to %s failed: %s", tf, e)
        return None


def _tv2_eval_release_event(
    cond: Dict[str, Any], now_utc: datetime,
) -> Tuple[bool, str]:
    """True when now is within [event - before, event + after] of a matching event."""
    global _tv2_calendar_warn_emitted
    try:
        import news_calendar
    except Exception:
        if not _tv2_calendar_warn_emitted:
            logger.warning("[BRIEFING-EXEC] news_calendar import failed — release_event conditions cannot satisfy")
            _tv2_calendar_warn_emitted = True
        return False, f"release_event({cond['event_name']}): calendar unavailable"

    want_cur = cond["currency"].upper()
    want_imp = cond["impact"].upper()
    needle   = cond["event_name"].strip().lower()

    # Public helper: filters by currency + impact in one call, covering
    # both HIGH and MEDIUM. No module-private reach-through.
    try:
        events = news_calendar.get_events_today(
            currencies=[want_cur], impact=want_imp,
        )
    except Exception:
        events = []

    if not events:
        # Distinguish "cache unavailable" (warn once) from "no matching
        # event today" (return False silently — a legitimate outcome).
        cache_ok = True
        try:
            cache_ok = bool(news_calendar.calendar_available_today())
        except Exception:
            cache_ok = False
        if not cache_ok:
            if not _tv2_calendar_warn_emitted:
                logger.warning(
                    "[BRIEFING-EXEC] news_calendar has no data for today — "
                    "release_event conditions cannot satisfy"
                )
                _tv2_calendar_warn_emitted = True
            return False, f"release_event({cond['event_name']}): no calendar data"
        return False, f"release_event({cond['event_name']}): no matching event today"

    for ev in events:
        if needle not in str(ev.get("event_name", "")).lower():
            continue
        try:
            hh, mm = str(ev["time"]).split(":")
            ev_dt = now_utc.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except Exception:
            continue
        start = ev_dt - timedelta(minutes=cond["window_minutes_before"])
        end   = ev_dt + timedelta(minutes=cond["window_minutes_after"])
        if start <= now_utc <= end:
            return True, ""
        return False, (
            f"release_event({cond['event_name']}): now={now_utc.strftime('%H:%M:%S')} "
            f"outside window [{start.strftime('%H:%M')}, {end.strftime('%H:%M')}]"
        )

    return False, f"release_event({cond['event_name']}): no matching event today"


def _tv2_eval_sweep(
    cond: Dict[str, Any], df_5m: Any, armed_at: float, pip_size: float,
) -> Tuple[bool, str]:
    """True if any bar since arm traded through the level by tolerance_pips."""
    if df_5m is None or not hasattr(df_5m, "__len__") or len(df_5m) == 0:
        return False, f"sweep({cond['level']}): no 5m data"
    tol_price = float(cond["tolerance_pips"]) * float(pip_size or 0.0)
    level = float(cond["level"])
    side = cond["side"]

    try:
        if armed_at and hasattr(df_5m, "index"):
            try:
                # index is pandas DatetimeIndex (tz-aware UTC) in the hot path
                arm_dt = datetime.fromtimestamp(float(armed_at), tz=timezone.utc)
                idx = df_5m.index
                if getattr(idx, "tz", None) is None:
                    # naive index — compare by ts64
                    import pandas as _pd
                    arm_ts = _pd.Timestamp(arm_dt).tz_convert(None) if arm_dt.tzinfo else _pd.Timestamp(arm_dt)
                    sub = df_5m[idx >= arm_ts]
                else:
                    sub = df_5m[idx >= arm_dt]
                if len(sub) == 0:
                    sub = df_5m
            except Exception:
                sub = df_5m
        else:
            sub = df_5m

        if side == "below":
            threshold = level - tol_price
            lo = float(sub["low"].min())
            return (lo <= threshold), (
                f"sweep({level}, below, tol={cond['tolerance_pips']}p): lo={lo:.5f} "
                f"threshold={threshold:.5f}"
            )
        else:
            threshold = level + tol_price
            hi = float(sub["high"].max())
            return (hi >= threshold), (
                f"sweep({level}, above, tol={cond['tolerance_pips']}p): hi={hi:.5f} "
                f"threshold={threshold:.5f}"
            )
    except Exception as e:
        return False, f"sweep({cond['level']}): eval error {type(e).__name__}: {e}"


def _tv2_latest_closed_row(df: Any) -> Optional[Any]:
    """Return the most recent CLOSED bar (iloc[-2] on a live-tailing df).

    The executor's 5m df typically keeps the currently-forming bar at
    iloc[-1]; iloc[-2] is the most recently closed. For a resampled df
    built from closed 5m bars, iloc[-1] may itself still be closing until
    the next TF boundary — iloc[-2] is always safe.
    """
    try:
        if df is None or not hasattr(df, "__len__") or len(df) < 2:
            return None
        return df.iloc[-2]
    except Exception:
        return None


def _tv2_eval_candle_close(cond: Dict[str, Any], df_5m: Any) -> Tuple[bool, str]:
    tf = cond["timeframe"]
    df_tf = _tv2_resample(df_5m, tf)
    row = _tv2_latest_closed_row(df_tf)
    if row is None:
        return False, f"candle_close({tf},{cond['direction']},{cond['level']}): no closed bar"
    try:
        close = float(row["close"])
    except Exception:
        return False, f"candle_close({tf}): close unreadable"
    lvl = float(cond["level"])
    if cond["direction"] == "above":
        return (close > lvl), f"candle_close({tf},above,{lvl}): close={close:.5f}"
    else:
        return (close < lvl), f"candle_close({tf},below,{lvl}): close={close:.5f}"


def _tv2_eval_rsi(cond: Dict[str, Any], df_5m: Any) -> Tuple[bool, str]:
    tf = cond["timeframe"]
    df_tf = _tv2_resample(df_5m, tf)
    if df_tf is None or not hasattr(df_tf, "__len__") or len(df_tf) < 16:
        return False, f"rsi({tf},{cond['operator']},{cond['value']}): insufficient bars"
    try:
        from indicators import rsi as _rsi
    except Exception:
        logger.error("[BRIEFING-EXEC] indicators.rsi import failed — rsi condition cannot satisfy")
        return False, f"rsi({tf}): indicator unavailable"
    try:
        # closed bars only: drop the still-forming last row
        closes = df_tf["close"].iloc[:-1]
        series = _rsi(closes, period=14)
        cur  = float(series.iloc[-1])
        prev = float(series.iloc[-2]) if len(series) >= 2 else cur
    except Exception as e:
        return False, f"rsi({tf}): eval error {type(e).__name__}: {e}"
    val = float(cond["value"])
    op = cond["operator"]
    if op == "<":
        ok = cur < val
    elif op == ">":
        ok = cur > val
    elif op == "crosses_up":
        ok = (prev <= val) and (cur > val)
    else:  # crosses_down
        ok = (prev >= val) and (cur < val)
    return ok, f"rsi({tf},{op},{val}): cur={cur:.2f} prev={prev:.2f}"


def _tv2_eval_consecutive_closes(cond: Dict[str, Any], df_5m: Any) -> Tuple[bool, str]:
    tf = cond["timeframe"]
    df_tf = _tv2_resample(df_5m, tf)
    if df_tf is None or not hasattr(df_tf, "__len__"):
        return False, f"consecutive_closes({tf}): no data"
    need = int(cond["count"])
    try:
        # drop the still-forming last bar, then grab the last `need` closed bars
        closed = df_tf.iloc[:-1]
        if len(closed) < need:
            return False, f"consecutive_closes({tf},{need}): only {len(closed)} closed bars"
        closes = [float(x) for x in closed["close"].iloc[-need:].tolist()]
    except Exception as e:
        return False, f"consecutive_closes({tf}): eval error {type(e).__name__}: {e}"
    lvl = float(cond["level"])
    if cond["direction"] == "above":
        ok = all(c > lvl for c in closes)
    else:
        ok = all(c < lvl for c in closes)
    return ok, f"consecutive_closes({tf},{cond['direction']},{lvl},{need}): closes={closes}"


def _all_triggers_satisfied(
    plan: Dict[str, Any], sym: str, now_utc: datetime,
    price_context: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """Evaluate ALL parsed entry_trigger_v2 conditions for `plan`.

    Returns (ok, failed_descriptions). Caller decides whether to block
    (MODE=live), log-only (MODE=shadow), or skip (MODE=off — never call).
    """
    parsed = plan.get("_triggers_parsed") or []
    if not parsed:
        return True, []  # treat absent v2 as vacuously satisfied

    df_5m = price_context.get("df_5m")
    armed_at = float(price_context.get("armed_at") or 0.0)
    pip_size = float(price_context.get("pip_size") or 0.0)

    failed: List[str] = []
    for cond in parsed:
        ctype = cond["type"]
        if ctype == "release_event":
            ok, detail = _tv2_eval_release_event(cond, now_utc)
        elif ctype == "sweep":
            ok, detail = _tv2_eval_sweep(cond, df_5m, armed_at, pip_size)
        elif ctype == "candle_close":
            ok, detail = _tv2_eval_candle_close(cond, df_5m)
        elif ctype == "rsi":
            ok, detail = _tv2_eval_rsi(cond, df_5m)
        elif ctype == "consecutive_closes":
            ok, detail = _tv2_eval_consecutive_closes(cond, df_5m)
        else:
            ok, detail = False, f"unknown condition type {ctype!r}"
        if not ok:
            failed.append(detail or ctype)
    return (len(failed) == 0), failed


# =====================================================================
# Phase 2 — London/NY split + conditional NY plan evaluation
# =====================================================================

@dataclass
class Bar:
    """One 5m candle. Times are UTC."""
    timestamp: datetime
    open:  float
    high:  float
    low:   float
    close: float


@dataclass
class LondonSummary:
    """Summary of London session price action 06:45-12:25 UTC, used at
    12:30 UTC to evaluate NY plans' london_condition gates.
    """
    symbol:     str
    date_utc:   date
    open_price: float
    close_price: float
    high:       float
    low:        float
    range_pips: float
    bars_06_45_to_12_25: List[Bar] = field(default_factory=list)


def _evaluate_london_condition(
    condition: Dict[str, Any],
    summary:   LondonSummary,
    pip_size:  float,
) -> Tuple[bool, str]:
    """Evaluate a NY plan's london_condition against the actual London
    session summary. Returns ``(passed, reason)``.

    pip_size is in price units (e.g. 0.0001 for EURUSD, 0.01 for USDJPY) —
    used to convert tolerance_pips into price tolerance. For IG-scaled
    feeds where 1 point == 1 pip, callers can pass pip_size=1.0.
    """
    if not isinstance(condition, dict):
        return False, f"condition not an object ({type(condition).__name__})"
    ctype = str(condition.get("type") or "").strip()
    try:
        level = float(condition["level"])
    except (KeyError, TypeError, ValueError):
        return False, f"condition.level missing or non-numeric"
    tol_pips = float(condition.get("tolerance_pips") or 0.0)
    tol_price = tol_pips * pip_size

    close_p = summary.close_price
    high_p  = summary.high
    low_p   = summary.low

    if ctype == "close_above":
        ok = close_p > level
        return ok, f"close_above level={level:g} close={close_p:g}"
    if ctype == "close_below":
        ok = close_p < level
        return ok, f"close_below level={level:g} close={close_p:g}"
    if ctype == "ranged":
        ok = (abs(high_p - level) <= tol_price
              and abs(low_p  - level) <= tol_price)
        return ok, (
            f"ranged level={level:g} ±{tol_pips:g}p "
            f"high={high_p:g} low={low_p:g}"
        )
    if ctype == "swept_then_reversed":
        # Spec: 2-pip default if no tolerance supplied.
        sweep_tol_pips = tol_pips if tol_pips > 0 else 2.0
        sweep_tol_price = sweep_tol_pips * pip_size
        bars = summary.bars_06_45_to_12_25 or []
        max_excursion = max((b.high for b in bars), default=high_p)
        min_excursion = min((b.low  for b in bars), default=low_p)
        sweep_above = (max_excursion > level + sweep_tol_price
                       and close_p < level)
        sweep_below = (min_excursion < level - sweep_tol_price
                       and close_p > level)
        ok = sweep_above or sweep_below
        side = "above" if sweep_above else ("below" if sweep_below else "none")
        return ok, (
            f"swept_then_reversed level={level:g} side={side} "
            f"max_ex={max_excursion:g} min_ex={min_excursion:g} close={close_p:g}"
        )
    if ctype == "held_at":
        bars = summary.bars_06_45_to_12_25 or []
        touches = sum(
            1 for b in bars
            if abs(b.high - level) <= tol_price
            or abs(b.low  - level) <= tol_price
        )
        broke = (close_p > level + tol_price) or (close_p < level - tol_price)
        ok = touches >= 2 and not broke
        return ok, (
            f"held_at level={level:g} ±{tol_pips:g}p touches={touches} "
            f"broke={broke} close={close_p:g}"
        )
    return False, f"unknown condition type {ctype!r}"


# ── Per-pair plan-state persistence (survives restart 06:30..12:30 UTC) ──

_PLANS_CACHE_DIR = Path(os.getenv("CACHE_DIR", "/opt/tradingbot/cache"))


def _plans_cache_path(symbol: str) -> Path:
    return _PLANS_CACHE_DIR / f"briefing_plans_{symbol.upper()}.json"


def _today_utc_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _briefing_time_is_today(briefing_time: str) -> bool:
    """True if briefing_time's UTC date matches today's UTC date."""
    if not briefing_time:
        return False
    try:
        bt = briefing_time.replace("Z", "+00:00")
        dt = datetime.fromisoformat(bt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d") == _today_utc_date_str()
    except Exception:
        return False


# =====================================================================
# Phase 3 — bias-as-probability-adjustment
# =====================================================================
# The briefing model produces raw_probability per plan (geometric merit
# only); the bot computes probability = raw_probability × multiplier
# based on whether the plan direction agrees with session_bias and how
# confident the model is in that bias.
#
# Multipliers were chosen so a high-confidence agreeing plan gets a
# meaningful but not dominant boost (×1.10), while a high-confidence
# opposing plan is materially down-weighted (×0.80) without forcing
# probability under typical execution thresholds. NEUTRAL bias is a
# no-op (×1.00). The output is clamped to [0.05, 0.95] to avoid edge
# cases at execution-gate boundaries.

_BIAS_CONFIDENCE_HIGH_THRESHOLD = 0.65
_BIAS_PROB_CLAMP_LO = 0.05
_BIAS_PROB_CLAMP_HI = 0.95


def _plan_side(plan: Dict[str, Any]) -> Optional[str]:
    """Return 'BUY' or 'SELL' from plan.direction or plan.bias, else None."""
    val = str(plan.get("direction") or plan.get("bias") or "").upper()
    if val in ("BUY", "LONG"):
        return "BUY"
    if val in ("SELL", "SHORT"):
        return "SELL"
    return None


def _bias_multiplier(
    plan_direction: str,
    bias: str,
    bias_confidence: float,
) -> float:
    """Probability multiplier for a plan based on its directional
    alignment with the briefing's session_bias.

    plan_direction: "BUY" | "SELL" | "LONG" | "SHORT" (case-insensitive)
    bias:           "BULLISH" | "BEARISH" | "NEUTRAL" (case-insensitive)
    bias_confidence: 0.0-1.0 — used to pick high vs low band

    Returns 1.0 when bias is NEUTRAL or when direction can't be
    classified. Otherwise:
      - aligned + conf >= 0.65 → 1.10
      - aligned + conf <  0.65 → 1.05
      - opposed + conf <  0.65 → 0.90
      - opposed + conf >= 0.65 → 0.80
    """
    bias_u = (bias or "").upper()
    if bias_u == "NEUTRAL":
        return 1.00

    d = (plan_direction or "").upper()
    is_long  = d in ("BUY",  "LONG")
    is_short = d in ("SELL", "SHORT")
    if not (is_long or is_short):
        return 1.00

    bias_long  = bias_u == "BULLISH"
    bias_short = bias_u == "BEARISH"
    if not (bias_long or bias_short):
        # Unknown bias label — be conservative and don't adjust.
        return 1.00

    matches = (is_long and bias_long) or (is_short and bias_short)
    high_conf = float(bias_confidence or 0.0) >= _BIAS_CONFIDENCE_HIGH_THRESHOLD

    if matches:
        return 1.10 if high_conf else 1.05
    return 0.80 if high_conf else 0.90


def apply_bias_adjustment(briefing: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Mutate ``briefing.trading_plans`` in place: set ``probability =
    clamp(raw_probability × _bias_multiplier(plan.bias, session_bias,
    bias_confidence), [0.05, 0.95])``. ``raw_probability`` is preserved
    as audit; ``_bias_multiplier`` is added per-plan for diagnostics.

    Returns a list of per-plan adjustment records used for log lines:
    ``[{"label": str, "raw": float, "adjusted": float, "mult": float}, ...]``.

    Backwards-compat: a plan missing ``raw_probability`` has its current
    ``probability`` lifted into ``raw_probability`` first; subsequent
    re-applications are idempotent.
    """
    summary: List[Dict[str, Any]] = []
    bias = str(briefing.get("session_bias") or "NEUTRAL")
    try:
        conf = float(briefing.get("bias_confidence", 0.5) or 0.5)
    except (TypeError, ValueError):
        conf = 0.5

    plans = briefing.get("trading_plans")
    if not isinstance(plans, list):
        return summary

    for plan in plans:
        if not isinstance(plan, dict):
            continue
        raw = plan.get("raw_probability")
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            # Backwards compat: hoist current probability into raw
            try:
                raw = float(plan.get("probability", 0.0) or 0.0)
            except (TypeError, ValueError):
                raw = 0.0
            plan["raw_probability"] = raw
        raw_f = float(raw)

        direction = plan.get("bias", "")  # plan.bias is "LONG"/"SHORT"
        mult = _bias_multiplier(direction, bias, conf)
        adjusted = raw_f * mult
        adjusted = max(_BIAS_PROB_CLAMP_LO, min(_BIAS_PROB_CLAMP_HI, adjusted))
        plan["probability"]      = round(adjusted, 3)
        plan["_bias_multiplier"] = mult

        summary.append({
            "label":    str(plan.get("label") or "?"),
            "raw":      round(raw_f, 3),
            "adjusted": round(adjusted, 3),
            "mult":     mult,
        })
    return summary


# =====================================================================
# Phase 4 — plan staleness handling
# =====================================================================
# Two checks drop a plan from the active set BEFORE entry:
#   1. expires_at  — wall-clock deadline ("12:30Z" / "end_of_day" /
#      ISO8601). Checked on every evaluate_tick().
#   2. invalidation — bar CLOSE beyond the plan's invalidation level
#      in the wrong direction. Checked on each is_new_5m via
#      on_bar_close().
# Already-entered plans are not affected by either check — once the
# trade is open, the executor (not the briefing strategy) manages it.

from datetime import time as dt_time


def _plan_expired(plan: Dict[str, Any], now_utc: datetime) -> bool:
    """True iff the plan's ``expires_at`` deadline has passed.

    Accepted forms:
      - 'end_of_day'            → 21:00 UTC today
      - 'HH:MM' or 'HH:MMZ'     → wall-clock today UTC (e.g. '12:30Z', '17:45Z')
      - Full ISO-8601 datetime  → trailing Z or +00:00 offset
    """
    raw = plan.get("expires_at")
    if not raw:
        return False
    raw = str(raw).strip()

    if raw == "end_of_day":
        eod = datetime.combine(now_utc.date(), dt_time(21, 0), tzinfo=timezone.utc)
        return now_utc >= eod

    # HH:MM[Z] — wall-clock time-of-day, today UTC.
    hhmm = raw[:-1] if raw.endswith("Z") else raw
    try:
        t = datetime.strptime(hhmm, "%H:%M").time()
        deadline = datetime.combine(now_utc.date(), t, tzinfo=timezone.utc)
        return now_utc >= deadline
    except ValueError:
        pass

    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        logger.warning(
            "[BRIEFING-EXEC] %r: unparseable expires_at — treating as never-expiring",
            raw,
        )
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return now_utc >= ts


_INVALIDATION_TOLERANCE_PIPS = float(
    os.getenv("BRIEFING_INVALIDATION_TOLERANCE_PIPS", "5") or "5"
)


def _bar_invalidates_plan(
    plan: Dict[str, Any],
    bar_close: float,
    timeframe: str = "5m",
    pip_size: float = 1.0,
) -> bool:
    """True iff this bar's CLOSE is beyond the plan's invalidation level
    by more than the tolerance buffer, in the wrong direction.

    timeframe is the bar's own timeframe ("5m"/"15m"/"h1"). The plan's
    ``invalidation_timeframe`` (default "5m") gates which closes apply:
    a plan with invalidation_timeframe="h1" is untouched by 5m or 15m
    closes — only an actual H1-bar close can invalidate it.

    A pip tolerance buffer (BRIEFING_INVALIDATION_TOLERANCE_PIPS, default
    5) is added to the comparison: SHORT plans only invalidate when the
    close exceeds level + tolerance; LONG plans when close drops below
    level - tolerance. Single-pip overshoots from market noise are
    ignored.

    Active plans (built by on_briefing) carry ``invalidation_price`` +
    ``direction`` (BUY/SELL). Raw briefing plans may carry numeric
    ``invalidation`` + ``bias`` (LONG/SHORT). Both shapes are accepted.
    Wicks are ignored — strict close-beyond-tolerance comparison only.
    """
    plan_tf = str(plan.get("invalidation_timeframe") or "5m").lower()
    if plan_tf != timeframe:
        return False

    inv = plan.get("invalidation_price")
    if inv is None:
        inv = plan.get("invalidation")
    if inv is None:
        return False
    try:
        inv = float(inv)
    except (TypeError, ValueError):
        return False

    direction = (plan.get("direction") or plan.get("bias") or "").upper()
    is_long  = direction in ("LONG", "BUY")
    is_short = direction in ("SHORT", "SELL")

    tolerance = _INVALIDATION_TOLERANCE_PIPS * pip_size

    if is_long:
        return bar_close < (inv - tolerance)
    if is_short:
        return bar_close > (inv + tolerance)
    return False


_CONVICTION_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _lookup_plan_by_ref(
    briefing: Dict[str, Any],
    plan_session: Any,
    plan_rank: Any,
) -> Optional[Dict[str, Any]]:
    """Return the trading_plans entry matching (plan_session, plan_rank),
    or None when the pair doesn't resolve. Mirrors the (session, rank) key
    that morning_briefing._build_plan_index uses to validate best_trade."""
    if not isinstance(plan_session, str) or not isinstance(plan_rank, int):
        return None
    for p in (briefing.get("trading_plans") or []):
        if not isinstance(p, dict):
            continue
        if p.get("session") == plan_session and p.get("rank") == plan_rank:
            return p
    return None


def _resolve_active_plans(briefing: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resolve the list of active plans from briefing.best_trade.

    Returns a possibly-empty list. Caller falls back to "all London plans"
    when this returns [].

    UNCONDITIONAL → singleton list containing the named plan (or [] if
        the (plan_session, plan_rank) reference doesn't resolve).
    CONDITIONAL   → list of ALL branch-referenced plans (deduped by
        (session, rank); expired branches dropped with DEBUG log).
    null / absent → [].

    The `expires_at` gate (signoff decision 5) skips any branch whose
    plan has already expired by the time the briefing is consumed. This
    avoids arming a plan that check_expires_at would immediately drop.
    """
    bt = briefing.get("best_trade")
    if not isinstance(bt, dict):
        return []

    mode = bt.get("mode")
    now_utc = datetime.now(timezone.utc)

    if mode == "UNCONDITIONAL":
        p = _lookup_plan_by_ref(briefing, bt.get("plan_session"), bt.get("plan_rank"))
        if p is None:
            return []
        if _plan_expired(p, now_utc):
            logger.debug(
                "[BRIEFING-EXEC] resolver: UNCONDITIONAL plan already expired "
                "(session=%s rank=%s expires_at=%s) — returning []",
                p.get("session"), p.get("rank"), p.get("expires_at"),
            )
            return []
        return [p]

    if mode == "CONDITIONAL":
        branches = bt.get("conditional_branches") or []
        if not isinstance(branches, list):
            return []
        out: List[Dict[str, Any]] = []
        seen_keys: set = set()
        for br in branches:
            if not isinstance(br, dict):
                continue
            plan = _lookup_plan_by_ref(briefing, br.get("plan_session"), br.get("plan_rank"))
            if plan is None:
                continue
            if _plan_expired(plan, now_utc):
                logger.debug(
                    "[BRIEFING-EXEC] resolver: CONDITIONAL branch plan expired "
                    "(session=%s rank=%s expires_at=%s) — skipped",
                    plan.get("session"), plan.get("rank"), plan.get("expires_at"),
                )
                continue
            key = (plan.get("session"), plan.get("rank"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(plan)
        return out

    return []


# ─── Forensic fire snapshot helper (Phase 2e — diagnostic only) ──────────
# Module-level helper called once per fire from each of the two emit
# sites in evaluate_tick (TREND_ENTRY, PHASE2). Captures a multi-axis
# 5m snapshot at fire-confirmed time and appends a record to
# logs/forensic_fires.jsonl for the May 19 review.
#
# Wrapped in try/except internally so the helper never raises — a fire
# path that calls it is safe even on snapshot/IO/import failure.
#
# strategy=mode writes "BRIEFING_EXECUTION" (the single name; this
# strategy has no directional variants in signal_log). direction is
# normalized to LONG/SHORT here for explicitness; the forensic logger
# normalizes too. fire_bar_ts uses df_5m.index[-1] — tz-aware UTC in the
# hot path; naive indexes get localized.
#
# Phase 2f will add HTF (H1/H4), briefing levels, session, and news
# state plumbed from the autobot main loop.
def _emit_forensic_fire(
    sym: str,
    mode: str,
    direction: str,
    entry_price: float,
    df_5m: Any,
    pip_size: float,
    fire_path: str,
) -> None:
    """Emit one forensic fire record. Thin wrapper around
    forensic_logger.capture_fire_from_df (the canonical helper used by
    NEWS_TICK / NEWS_STRATEGY / 3CO too). Kept as a local name so existing
    callers in this module need no change."""
    from forensic_logger import capture_fire_from_df as _ff_capture
    _ff_capture(
        sym=sym,
        strategy=mode,
        direction=direction,
        entry_price=entry_price,
        df_5m=df_5m,
        pip_size=pip_size,
        fire_path=fire_path,
    )


class BriefingExecutionStrategy:
    """Trades directly from the highest-ranked briefing trading plan."""

    def __init__(self) -> None:
        # Step 2B — multi-slot: symbol → ordered list of active plan dicts
        # (was Dict[str, Dict[str, Any]] in 2A). Each plan dict carries its
        # own per-plan latches: _sweep_seen, _armed_at, _trend_closes,
        # _dormant. The four sibling instance dicts (_sweep_seen, _armed_at,
        # _trend_closes, plus the un-used _dormant) are gone in favour of
        # field-on-plan storage. State and plan travel together; disk
        # persistence comes for free via _save_plans_state's existing dump.
        self._plans: Dict[str, List[Dict[str, Any]]] = {}
        # Step 2B — per-session lockout: symbol → {session: True} once a
        # plan in that session fires and broker confirms. Session-scoped,
        # not plan-scoped, because the operational gate is "the pair already
        # has a same-session position open" (the bot doesn't double-up
        # within a session). Per-pair pair-concurrency cap in
        # trade_executor.py:773 still gates cross-session second fires
        # until BRIEFING_EXECUTION joins _PAIR_CONCURRENCY_BYPASS_MODES —
        # see commit body for the dependency note.
        self._entered: Dict[str, Dict[str, bool]] = {}
        # symbol → briefing_time string (detect new briefings)
        self._briefing_id: Dict[str, str] = {}

        # ── Phase 2 — London/NY split state ──────────────────────────────
        # All London plans (raw briefing dicts, ranked) for audit/persistence
        self._london_plans:  Dict[str, List[Dict[str, Any]]] = {}
        # NY plans queued, evaluated at 12:30 UTC against LondonSummary
        self._ny_pending:    Dict[str, List[Dict[str, Any]]] = {}
        # NY plans whose london_condition was satisfied (post-12:30 eval)
        self._ny_armed:      Dict[str, List[Dict[str, Any]]] = {}
        # NY plans whose london_condition was NOT satisfied; each entry is
        # {"plan": {...}, "reason": str}
        self._ny_discarded:  Dict[str, List[Dict[str, Any]]] = {}
        # Track that today's NY evaluation has already run (per symbol).
        # Key: "YYYY-MM-DD", set when evaluate_ny_plans() runs.
        self._ny_eval_date:  Dict[str, str] = {}

        # ── Phase 4 — staleness handling ──────────────────────────────────
        # Plans dropped before entry, audited for diagnostics. Records are
        # {"plan": <active-plan dict>, "reason": str}.
        self._invalidated_plans: Dict[str, List[Dict[str, Any]]] = {}

        # ── Skip-log dedupe sets — emit each (sym, session, plan_id, reason)
        # skip line at INFO at most once per process. Without this, the
        # per-session lockout and _dormant `continue` paths would flood
        # INFO on every tick for already-fired or dormant plans.
        self._skip_log_seen: set[tuple] = set()

        # Hydrate any same-day persisted state (survives restarts between
        # the 06:30 briefing and the 12:30 NY evaluation).
        try:
            self._hydrate_plans_state_from_disk()
        except Exception as exc:
            logger.warning("[BRIEFING-EXEC] plan-state hydration failed: %s", exc)

    # ------------------------------------------------------------------
    # Step 2B — multi-slot internal helpers
    # ------------------------------------------------------------------

    def _is_entered(self, sym: str, session: str) -> bool:
        """Per-session lockout check. Returns True iff a plan in *session*
        on *sym* has fired and the broker has confirmed."""
        return bool(self._entered.get(sym, {}).get(session, False))

    def _mark_entered(self, sym: str, session: str) -> None:
        """Per-session lockout set. Idempotent."""
        self._entered.setdefault(sym, {})[session] = True

    def _per_plan_init(self, plan: Dict[str, Any]) -> None:
        """Stamp per-plan latches on a freshly-armed plan dict. Idempotent
        — re-arming the same plan resets the latches cleanly."""
        plan["_sweep_seen"] = False
        plan["_armed_at"] = _time.time()
        plan["_trend_closes"] = 0
        plan["_dormant"] = False

    def _drop_plan(
        self, sym: str, plan: Dict[str, Any], reason: str,
    ) -> None:
        """Remove a single plan from self._plans[sym] (the list), audit
        it under _invalidated_plans, persist. Replaces the pre-2B
        _drop_active_plan which popped the whole pair slot."""
        plans = self._plans.get(sym) or []
        try:
            plans.remove(plan)
        except ValueError:
            # Plan already removed by a concurrent path; defensively log
            # and continue rather than crash. on_bar_close + check_expires_at
            # can both fire on a tick that ends in re-arming.
            logger.debug(
                "[BRIEFING-EXEC] %s _drop_plan: plan %r not in list",
                sym, plan.get("label", "?"),
            )
            return
        record = {"plan": plan, "reason": reason}
        self._invalidated_plans.setdefault(sym, []).append(record)
        self._save_plans_state(sym)

    def _build_active_from_plan(
        self, sym: str, plan: Dict[str, Any], briefing: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Validate a raw briefing plan and build the active-dict shape
        used by evaluate_tick / on_bar_close. Returns None when the plan
        is missing required fields or has an unrecognised bias, logging
        a WARNING that names the plan so multi-plan briefings can
        partially fail without taking down the rest of the arming."""
        plan_label = str(plan.get("label", "") or "?")
        entry_zone = plan.get("entry_zone")
        stop_loss  = plan.get("stop_loss")
        targets    = plan.get("targets", [])

        if not entry_zone or len(entry_zone) < 2:
            logger.warning(
                "[BRIEFING-EXEC] %s plan %r missing entry_zone — skip",
                sym, plan_label,
            )
            return None
        if stop_loss is None:
            logger.warning(
                "[BRIEFING-EXEC] %s plan %r missing stop_loss — skip",
                sym, plan_label,
            )
            return None
        if not targets or len(targets) < 1:
            logger.warning(
                "[BRIEFING-EXEC] %s plan %r missing targets — skip",
                sym, plan_label,
            )
            return None

        bias = str(plan.get("bias", "") or "").upper()
        if bias == "LONG":
            direction = "BUY"
        elif bias == "SHORT":
            direction = "SELL"
        else:
            logger.warning(
                "[BRIEFING-EXEC] %s plan %r bias %r not LONG/SHORT — skip",
                sym, plan_label, bias,
            )
            return None

        inv_price, inv_direction, inv_timeframe = _parse_invalidation(
            str(plan.get("invalidation", "") or ""),
        )
        if inv_price is not None:
            logger.info(
                "[BRIEFING-EXEC] %s plan %r invalidation: %.5f %s on %s "
                "close (tolerance %.1fp)",
                sym, plan_label, inv_price, (inv_direction or "?"),
                inv_timeframe, _INVALIDATION_TOLERANCE_PIPS,
            )
        sweep_price, sweep_side = _parse_sweep_level(
            str(plan.get("entry_trigger", "") or ""),
            (float(entry_zone[0]), float(entry_zone[1])),
        )
        exit_time = _parse_exit_time(plan, briefing)

        _tv2_parsed = _parse_entry_trigger_v2(
            plan.get("entry_trigger_v2"), sym, plan_label,
        )

        prob = float(plan.get("probability", 0) or 0)
        conf = str(plan.get("confidence", "") or "").upper()

        active: Dict[str, Any] = {
            "label":            plan.get("label", ""),
            "direction":        direction,
            "entry_zone":       [float(entry_zone[0]), float(entry_zone[1])],
            "stop_loss":        float(stop_loss),
            "targets":          [float(t) for t in targets[:2]],
            "invalidation_price":     inv_price,
            "invalidation_direction": inv_direction,
            "invalidation_timeframe": inv_timeframe,
            "sweep_level_price":      sweep_price,
            "sweep_level_side":       sweep_side,
            "exit_time_utc":          exit_time,
            "probability":      prob,
            "confidence":       conf,
            "_triggers_parsed": _tv2_parsed,
            # Phase 4 — staleness fields
            "expires_at": plan.get("expires_at"),
            "session":    str(plan.get("session") or "London"),
            "bias":       bias,
            "rank":       plan.get("rank"),
            # Step 2A — deterministic plan_id; downstream stamps
            # decision.debug["plan_id"] from this field.
            "plan_id":    _plan_id_for(plan),
        }
        self._per_plan_init(active)
        return active

    # ------------------------------------------------------------------
    # Briefing ingestion
    # ------------------------------------------------------------------

    def on_briefing(self, symbol: str, briefing: Dict[str, Any]) -> None:
        """Called when a new/updated briefing is detected."""
        if not BRIEFING_EXECUTION_ENABLED:
            return
        sym = symbol.upper()
        briefing_time = str(briefing.get("briefing_time", ""))

        # Same briefing — no-op
        if self._briefing_id.get(sym) == briefing_time and briefing_time:
            return

        self._briefing_id[sym] = briefing_time
        # Step 2B — per-session _entered shape; plan-scoped latches now
        # live on the plan dict, so just clearing _plans[sym] drops them.
        self._entered[sym] = {}
        self._plans.pop(sym, None)

        # Cross-restart dedup: if a previous process already fired for this
        # exact briefing_time, hydrate _entered with the per-session flags
        # from disk so we don't re-fire the same arm. New briefing_time →
        # no record match → fires once.
        try:
            cache = _load_entered_cache()
            rec = cache.get(sym)
            if rec and str(rec.get("briefing_time", "")) == briefing_time and briefing_time:
                ebs = rec.get("entered_by_session")
                if isinstance(ebs, dict) and ebs:
                    self._entered[sym] = {
                        str(k): bool(v) for k, v in ebs.items()
                    }
                else:
                    # Backwards-compat: 2A caches carry only
                    # `entered_by_plan` keyed by "<session>_<rank>". Derive
                    # the session set from the keys.
                    ebp = rec.get("entered_by_plan") or {}
                    derived: Dict[str, bool] = {}
                    if isinstance(ebp, dict):
                        for k, v in ebp.items():
                            if not bool(v):
                                continue
                            sess = str(k).split("_", 1)[0] if "_" in str(k) else None
                            if sess:
                                derived[sess] = True
                    self._entered[sym] = derived
                logger.info(
                    "[BRIEFING-EXEC] %s arm already fired in prior process "
                    "(briefing_time=%s, fired_at=%s, sessions=%s) — dedup loaded from disk",
                    sym, briefing_time,
                    datetime.fromtimestamp(float(rec.get("fired_at", 0)), tz=timezone.utc).isoformat()
                    if rec.get("fired_at") else "?",
                    sorted(self._entered.get(sym, {}).keys()),
                )
        except Exception as _e:
            logger.debug("[BRIEFING-EXEC] %s dedup-load skipped: %s", sym, _e)

        plans = briefing.get("trading_plans")
        if not plans or not isinstance(plans, list) or len(plans) == 0:
            logger.info("[BRIEFING-EXEC] %s no trading_plans in briefing", sym)
            return

        # ── Phase 3: bias adjusts plan probabilities ────────────────────
        # Done before the session split so both London and NY plans carry
        # the bot-computed `probability` field once they reach storage.
        # raw_probability is preserved for audit; _bias_multiplier is
        # added per plan.
        adj_summary = apply_bias_adjustment(briefing)
        if adj_summary:
            session_bias = str(briefing.get("session_bias") or "NEUTRAL")
            try:
                conf = float(briefing.get("bias_confidence", 0.5) or 0.5)
            except (TypeError, ValueError):
                conf = 0.5
            adj_str = ", ".join(
                f"{r['label']!r} raw={r['raw']:.3f} → {r['adjusted']:.3f} (×{r['mult']:.2f})"
                for r in adj_summary
            )
            logger.info(
                "[BRIEFING-EXEC] %s bias=%s conf=%.2f | %d plan(s) adjusted: %s",
                sym, session_bias, conf, len(adj_summary), adj_str,
            )

        # ── HARD direction gate (composite veto, corrected) ─────────────
        # Reads briefing["daily_bias"] (deterministic 9-check) +
        # session_bias. Daily wins on disagreement; daily_bias=NEUTRAL
        # stands the entire briefing down (+34.5p abstention edge).
        decision = resolve_briefing_direction(briefing)
        logger.info(
            "[BRIEFING-EXEC] %s direction-gate: %s dir=%s class=%s — %s",
            sym, decision["action"], decision.get("direction") or "-",
            decision["class"], decision["reason"],
        )
        if decision["action"] == "STAND_DOWN":
            self._save_plans_state(sym)
            return
        _allowed_side = decision["direction"]  # "BUY" or "SELL"
        _kept: List[Dict[str, Any]] = []
        _dropped: List[str] = []
        for _p in plans:
            if not isinstance(_p, dict):
                continue
            _side = _plan_side(_p)
            if _side is None:
                _dropped.append(f"{_p.get('label','?')}(no-dir)")
                continue
            if _side != _allowed_side:
                _dropped.append(f"{_p.get('label','?')}({_side}!={_allowed_side})")
                continue
            _kept.append(_p)
        if _dropped:
            logger.info(
                "[BRIEFING-EXEC] %s direction-gate dropped %d plan(s): %s",
                sym, len(_dropped), ", ".join(_dropped),
            )
        if not _kept:
            logger.info(
                "[BRIEFING-EXEC] %s no plans pass direction gate (allowed=%s) — no arming",
                sym, _allowed_side,
            )
            self._save_plans_state(sym)
            return
        plans = _kept
        briefing["trading_plans"] = _kept

        # ── Phase 2: split by session ───────────────────────────────────
        # London plans become candidate active plans (highest-ranked wins,
        # matching the legacy single-active-plan invariant). NY plans are
        # queued in _ny_pending and evaluated at 12:30 UTC against the
        # actual London session via evaluate_ny_plans().
        # Plans without a `session` field (legacy briefings) are treated
        # as London — preserves existing behaviour during migration.
        london_plans: List[Dict[str, Any]] = []
        ny_plans:     List[Dict[str, Any]] = []
        for p in plans:
            if not isinstance(p, dict):
                continue
            sess = str(p.get("session") or "London").strip()
            if sess.upper() == "NY":
                ny_plans.append(p)
            else:
                london_plans.append(p)

        # Reset Phase 2 state for the new briefing
        self._london_plans[sym] = london_plans
        self._ny_pending[sym]   = ny_plans
        self._ny_armed[sym]     = []
        self._ny_discarded[sym] = []
        self._ny_eval_date.pop(sym, None)

        if not london_plans:
            logger.info(
                "[BRIEFING-EXEC] %s briefing has no London plans (NY-only=%d) "
                "— no active plan until 12:30 UTC NY evaluation",
                sym, len(ny_plans),
            )
            self._save_plans_state(sym)
            return

        # Sort by rank ascending; rank 1 is the head of the fallback list
        london_plans.sort(key=lambda p: int(p.get("rank") or 999))

        # Step 2B — multi-slot arming. best_trade.UNCONDITIONAL still arms
        # exactly one plan; best_trade.CONDITIONAL arms ALL referenced
        # branches; unresolvable best_trade falls back to all London plans
        # (rank-ascending), letting late-day price action select the winner
        # by trigger rather than by single-plan pick. Each arming pass
        # builds active dicts via _build_active_from_plan, which stamps
        # per-plan latches via _per_plan_init.
        resolved_plans = _resolve_active_plans(briefing)
        if resolved_plans:
            arming_source = "best_trade.{}".format(
                (briefing.get("best_trade") or {}).get("mode")
            )
            source_plans = resolved_plans
        else:
            arming_source = "fallback (no resolvable best_trade)"
            source_plans = list(london_plans)

        active_list: List[Dict[str, Any]] = []
        for raw in source_plans:
            active = self._build_active_from_plan(sym, raw, briefing)
            if active is None:
                continue
            active_list.append(active)

        if not active_list:
            logger.warning(
                "[BRIEFING-EXEC] %s no valid plans after arming (source=%s) — "
                "no active plan",
                sym, arming_source,
            )
            self._save_plans_state(sym)
            return

        self._plans[sym] = active_list
        plans_summary = ", ".join(
            "{sess}_{rk}({bias})".format(
                sess=a.get("session"), rk=a.get("rank"),
                bias=a.get("bias"),
            )
            for a in active_list
        )
        logger.info(
            "[BRIEFING-EXEC] %s ARMED %d plan(s) via %s: %s | ny_pending=%d",
            sym, len(active_list), arming_source, plans_summary,
            len(self._ny_pending.get(sym, [])),
        )
        for a in active_list:
            logger.info(
                "[BRIEFING-EXEC] %s   plan_id=%s label=%s dir=%s "
                "zone=[%.5f, %.5f] SL=%.5f TP=%s inv=%s@%s sweep=%s@%s "
                "exit=%s expires_at=%s",
                sym, a.get("plan_id"), a.get("label"), a.get("direction"),
                a["entry_zone"][0], a["entry_zone"][1], a["stop_loss"],
                a.get("targets"),
                a.get("invalidation_direction") or "?",
                f"{a['invalidation_price']:.5f}" if a.get("invalidation_price") is not None else "n/a",
                a.get("sweep_level_side") or "zone-edge",
                f"{a['sweep_level_price']:.5f}" if a.get("sweep_level_price") is not None else "n/a",
                a.get("exit_time_utc"),
                a.get("expires_at"),
            )
        self._save_plans_state(sym)

    # ------------------------------------------------------------------
    # Phase 2 — NY plan evaluation at 12:30 UTC
    # ------------------------------------------------------------------

    def evaluate_ny_plans(
        self,
        symbol: str,
        london_summary: LondonSummary,
        pip_size: float = 1.0,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:  # noqa: D401
        if not BRIEFING_EXECUTION_ENABLED:
            return ([], [])
        """Evaluate all queued NY plans for *symbol* against the actual
        London summary and APPEND all qualifying NY plans to the active
        list (Step 2B multi-slot behaviour). Persists + notifies.

        Each pending NY plan's ``london_condition`` is checked. Plans
        that pass go into ``_ny_armed[sym]`` (audit) and are promoted to
        ``_plans[sym]`` via :py:meth:`_promote_to_active` (append, not
        replace — late London plans coexist per signoff decision 4
        modified). Plans that fail go into ``_ny_discarded[sym]`` with
        the failure reason and are NOT promoted.

        Returns ``(armed_plans, discarded_records)`` where each
        discarded record is ``{"plan": <raw briefing plan>, "reason":
        str}``. Idempotent per UTC date — a second call on the same day
        logs and returns the prior result.

        Note: London plans with ``expires_at='12:30Z'`` are NOT dropped
        by this function; they get dropped by the next
        :py:meth:`check_expires_at` call inside ``evaluate_tick``, which
        runs every tick and gates plan iteration. Between this call and
        the next tick, ``_plans[sym]`` may transiently hold expired
        London plans alongside the promoted NY plans — they're sorted
        out on the next iteration before any plan gets a fire chance.

        ``pip_size`` is in price units (1.0 for IG-scaled FX feeds, where
        1 point == 1 pip).
        """
        sym = symbol.upper()
        date_str = london_summary.date_utc.strftime("%Y-%m-%d")
        if self._ny_eval_date.get(sym) == date_str:
            logger.info(
                "[BRIEFING-EXEC] %s NY evaluation already ran today (%s) — skipping",
                sym, date_str,
            )
            return list(self._ny_armed.get(sym, [])), list(self._ny_discarded.get(sym, []))

        pending = list(self._ny_pending.get(sym) or [])
        if not pending:
            logger.info(
                "[BRIEFING-EXEC] %s no NY plans pending evaluation (date=%s)",
                sym, date_str,
            )
            self._ny_eval_date[sym] = date_str
            self._save_plans_state(sym)
            return [], []

        logger.info(
            "[BRIEFING-EXEC] NY plan evaluation for %s | london open=%g close=%g "
            "high=%g low=%g range=%.1fp pending=%d",
            sym, london_summary.open_price, london_summary.close_price,
            london_summary.high, london_summary.low, london_summary.range_pips,
            len(pending),
        )

        armed:     List[Dict[str, Any]] = []
        discarded: List[Dict[str, Any]] = []
        for plan in pending:
            label = str(plan.get("label") or "?")
            cond = plan.get("london_condition")
            if not isinstance(cond, dict):
                discarded.append({"plan": plan, "reason": "london_condition missing"})
                logger.info(
                    "[BRIEFING-EXEC]   Plan %r: no london_condition — DISCARDED",
                    label,
                )
                continue
            ok, reason = _evaluate_london_condition(cond, london_summary, pip_size)
            if ok:
                armed.append(plan)
                logger.info(
                    "[BRIEFING-EXEC]   Plan %r: %s — ARMED",
                    label, reason,
                )
            else:
                discarded.append({"plan": plan, "reason": reason})
                logger.info(
                    "[BRIEFING-EXEC]   Plan %r: %s — DISCARDED",
                    label, reason,
                )

        self._ny_armed[sym]     = armed
        self._ny_discarded[sym] = discarded
        self._ny_pending[sym]   = []
        self._ny_eval_date[sym] = date_str

        # Step 2B — promote ALL surviving NY plans into the active list,
        # appending alongside any London plans still armed. London plans
        # are NOT auto-locked at 12:30 (signoff decision 4 modified);
        # _entered tracks fires, not clock boundaries.
        if armed:
            armed.sort(key=lambda p: int(p.get("rank") or 999))
            for ny_plan in armed:
                self._promote_to_active(sym, ny_plan)

        # Telegram summary
        try:
            from telegram_alerts import send_telegram_message
            send_telegram_message(
                f"NY plans armed for {sym}: {len(armed)}/{len(pending)}. "
                f"Armed: {', '.join(p.get('label') or '?' for p in armed) or '(none)'}. "
                f"Discarded: {', '.join(d['plan'].get('label') or '?' for d in discarded) or '(none)'}."
            )
        except Exception as exc:
            logger.debug("[BRIEFING-EXEC] %s Telegram notify failed: %s", sym, exc)

        self._save_plans_state(sym)
        return armed, discarded

    def _promote_to_active(self, sym: str, plan: Dict[str, Any]) -> None:
        """Build a normalized active plan dict from *plan* and APPEND it
        to ``self._plans[sym]`` (Step 2B multi-slot behaviour). Used by
        evaluate_ny_plans() to add surviving NY plans alongside any
        still-armed London plans rather than replacing them.

        Per signoff decision 4 (modified): does NOT auto-lock the London
        session. ``_entered[sym][session]`` is fire-triggered only.
        """
        # Delegates field-shape building to _build_active_from_plan so the
        # NY promote path stays in lockstep with on_briefing arming. We
        # pass an empty briefing because the NY-promotion path has no
        # news_context-anchored exit_time; _parse_exit_time tolerates {}.
        active = self._build_active_from_plan(sym, plan, {})
        if active is None:
            return
        # Default session label for NY-promoted plans when the source
        # plan dict didn't carry one — keeps audit logs unambiguous.
        if not active.get("session"):
            active["session"] = "NY"
        self._plans.setdefault(sym, []).append(active)
        logger.info(
            "[BRIEFING-EXEC] %s NY ARMED plan: %s | plan_id=%s session=%s "
            "dir=%s zone=[%.5f, %.5f] SL=%.5f TP=%s",
            sym, active["label"], active.get("plan_id"), active.get("session"),
            active["direction"],
            active["entry_zone"][0], active["entry_zone"][1],
            active["stop_loss"], active["targets"],
        )

    # ------------------------------------------------------------------
    # Phase 4 — staleness handling (expires_at + invalidation-on-close)
    # ------------------------------------------------------------------

    def _drop_active_plan(self, sym: str, reason: str) -> None:
        """Legacy shim — Step 2B multi-slot uses :py:meth:`_drop_plan`
        with a specific plan argument. Retained as a no-op alias so any
        external caller (none today inside this module) doesn't silently
        break; logs a warning so accidental usage is visible."""
        logger.warning(
            "[BRIEFING-EXEC] %s _drop_active_plan called (legacy single-plan "
            "API) — Step 2B no-op. reason=%s",
            sym, reason,
        )

    def check_expires_at(
        self,
        symbol: str,
        now_utc: Optional[datetime] = None,
    ) -> bool:
        """Drop any active plan whose ``expires_at`` has passed. Returns
        True iff at least one drop happened. Plans whose session has
        already fired (per-session lockout) are left alone — once the
        trade is open the executor manages it.
        """
        sym = symbol.upper()
        plans = list(self._plans.get(sym) or [])
        if not plans:
            return False
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        dropped_any = False
        for plan in plans:
            if self._is_entered(sym, str(plan.get("session") or "")):
                continue
            if not _plan_expired(plan, now_utc):
                continue
            logger.info(
                "[BRIEFING-EXEC] %s plan %r (plan_id=%s) expired at %s — dropping",
                sym, plan.get("label", "?"), plan.get("plan_id"),
                plan.get("expires_at"),
            )
            self._drop_plan(sym, plan, f"expired:{plan.get('expires_at')}")
            dropped_any = True
        return dropped_any

    def on_bar_close(
        self,
        symbol: str,
        bar_close: float,
        timeframe: str = "5m",
        now_utc: Optional[datetime] = None,
        pip_size: float = 1.0,
    ) -> None:
        if not BRIEFING_EXECUTION_ENABLED:
            return
        """Per-pair bar-close hook (5m / 15m / h1). For each armed plan
        on the symbol, drops it when:
          (a) the plan's ``expires_at`` has passed (5m only), OR
          (b) this bar's CLOSE is beyond the plan's invalidation level
              by more than the tolerance buffer, AND the bar's timeframe
              matches the plan's ``invalidation_timeframe`` (default 5m).

        Plans whose session has already fired (per-session lockout) are
        skipped. Wicks are ignored.
        """
        sym = symbol.upper()
        # Copy the list — _drop_plan mutates self._plans[sym] in place.
        plans = list(self._plans.get(sym) or [])
        if not plans:
            return

        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        for plan in plans:
            if self._is_entered(sym, str(plan.get("session") or "")):
                continue

            # Expiry first — gives the more specific log line when both
            # apply. Only run on 5m to avoid duplicate "expired" logs at
            # h1 boundaries (which always coincide with 5m).
            if timeframe == "5m" and _plan_expired(plan, now_utc):
                logger.info(
                    "[BRIEFING-EXEC] %s plan %r (plan_id=%s) expired at %s "
                    "— dropping",
                    sym, plan.get("label", "?"), plan.get("plan_id"),
                    plan.get("expires_at"),
                )
                self._drop_plan(sym, plan, f"expired:{plan.get('expires_at')}")
                continue

            if _bar_invalidates_plan(plan, bar_close, timeframe=timeframe, pip_size=pip_size):
                inv = plan.get("invalidation_price")
                if inv is None:
                    inv = plan.get("invalidation")
                try:
                    inv_f = float(inv) if inv is not None else 0.0
                except (TypeError, ValueError):
                    inv_f = 0.0
                plan_tf = str(plan.get("invalidation_timeframe") or "5m")
                direction = (plan.get("direction") or plan.get("bias") or "?").upper()
                logger.info(
                    "[BRIEFING-EXEC] %s plan %r (plan_id=%s) invalidated — "
                    "%s bar close %.5f beyond invalidation %.5f "
                    "(tolerance %.1fp, direction %s). Dropping plan.",
                    sym, plan.get("label", "?"), plan.get("plan_id"),
                    plan_tf, bar_close, inv_f,
                    _INVALIDATION_TOLERANCE_PIPS, direction,
                )
                self._drop_plan(sym, plan, f"invalidated@{bar_close:g}")
                continue

    # ------------------------------------------------------------------
    # Tick evaluation — entry detection
    # ------------------------------------------------------------------

    def evaluate_tick(
        self,
        symbol: str,
        epic: str,
        mid_price: float,
        pip_size: float,
        briefing: Optional[Dict[str, Any]],
        is_new_5m: bool = False,
        candle_close: Optional[float] = None,
        df_5m: Any = None,
    ) -> Optional[Any]:
        """Two-phase entry: sweep detection on every tick, entry on 5M close.

        Step 2B multi-slot: iterates plans rank-ascending; first plan to
        satisfy fires and returns. Plans whose session has already fired
        (per-session lockout) and plans marked _dormant are skipped.
        """
        if not BRIEFING_EXECUTION_ENABLED:
            return None
        from strategy_logic import StrategyDecision

        sym = symbol.upper()

        # Ingest briefing on first sight / update
        if briefing and isinstance(briefing, dict):
            self.on_briefing(sym, briefing)

        # Phase 4: drop any expired plans up front. Cheap no-op when
        # nothing is armed.
        self.check_expires_at(sym)

        plans = list(self._plans.get(sym) or [])
        # Rank-ascending iteration with deterministic cross-session
        # tie-break (London=0 before NY=1, then plan_id lexicographic).
        # Same-tick first-to-satisfy fires; remaining plans are skipped
        # on this tick. Per-session lockout prevents same-session
        # double-fire (signoff decision 1 + 7).
        plans.sort(key=lambda p: (
            int(p.get("rank") or 999),
            0 if str(p.get("session") or "").lower() == "london" else 1,
            str(p.get("plan_id") or ""),
        ))

        for plan in plans:
            session = str(plan.get("session") or "")
            if self._is_entered(sym, session):
                _skip_key = (sym, session, plan.get("plan_id"), "session_locked")
                if _skip_key not in self._skip_log_seen:
                    self._skip_log_seen.add(_skip_key)
                    logger.info(
                        "[BRIEFING-EXEC] %s plan_id=%s strategy=BRIEFING_EXECUTION "
                        "skipped — session=%s already fired (per-session lockout)",
                        sym, plan.get("plan_id"), session,
                    )
                continue
            if plan.get("_dormant"):
                _skip_key = (sym, session, plan.get("plan_id"), "dormant")
                if _skip_key not in self._skip_log_seen:
                    self._skip_log_seen.add(_skip_key)
                    logger.info(
                        "[BRIEFING-EXEC] %s plan_id=%s strategy=BRIEFING_EXECUTION "
                        "skipped — plan marked _dormant (Step 2C london_condition false)",
                        sym, plan.get("plan_id"),
                    )
                continue

            zone_lo = min(plan["entry_zone"])
            zone_hi = max(plan["entry_zone"])
            direction = plan["direction"]

            # ── Phase 1: Detect sweep (every tick) ────────────────────────
            if not plan.get("_sweep_seen"):
                sweep_price = plan.get("sweep_level_price")
                sweep_side = plan.get("sweep_level_side")

                if sweep_price is not None and sweep_side in ("below", "above"):
                    if sweep_side == "below" and mid_price <= sweep_price:
                        plan["_sweep_seen"] = True
                        logger.info(
                            "[BRIEFING-EXEC] %s SWEEP SEEN (plan_id=%s): mid %.5f <= "
                            "sweep_level %.5f — waiting for 5M close",
                            sym, plan.get("plan_id"), mid_price, sweep_price,
                        )
                    elif sweep_side == "above" and mid_price >= sweep_price:
                        plan["_sweep_seen"] = True
                        logger.info(
                            "[BRIEFING-EXEC] %s SWEEP SEEN (plan_id=%s): mid %.5f >= "
                            "sweep_level %.5f — waiting for 5M close",
                            sym, plan.get("plan_id"), mid_price, sweep_price,
                        )
                else:
                    if direction == "SELL":
                        if mid_price >= zone_hi:
                            plan["_sweep_seen"] = True
                            logger.info(
                                "[BRIEFING-EXEC] %s SWEEP SEEN (plan_id=%s): mid %.5f "
                                ">= zone_hi %.5f (zone-edge fallback) — waiting for "
                                "5M close confirmation",
                                sym, plan.get("plan_id"), mid_price, zone_hi,
                            )
                    else:
                        if mid_price <= zone_lo:
                            plan["_sweep_seen"] = True
                            logger.info(
                                "[BRIEFING-EXEC] %s SWEEP SEEN (plan_id=%s): mid %.5f "
                                "<= zone_lo %.5f (zone-edge fallback) — waiting for "
                                "5M close confirmation",
                                sym, plan.get("plan_id"), mid_price, zone_lo,
                            )

                # ── TREND_ENTRY fallback ──────────────────────────────────
                if not plan.get("_sweep_seen") and is_new_5m:
                    close_price_tc = candle_close if candle_close is not None else mid_price
                    through_zone = (
                        (direction == "SELL" and close_price_tc < zone_lo) or
                        (direction == "BUY"  and close_price_tc > zone_hi)
                    )
                    if through_zone:
                        plan["_trend_closes"] = int(plan.get("_trend_closes", 0)) + 1
                    else:
                        plan["_trend_closes"] = 0

                    armed_at = float(plan.get("_armed_at") or 0.0)
                    elapsed_min = (_time.time() - armed_at) / 60.0 if armed_at else 0.0

                    if (
                        int(plan.get("_trend_closes", 0)) >= 2
                        and elapsed_min >= BRIEFING_TREND_ENTRY_MIN_MINUTES
                    ):
                        inv_price_tc = plan.get("invalidation_price")
                        if inv_price_tc is None:
                            logger.info(
                                "[BRIEFING-EXEC] %s TREND_ENTRY conditions met but no "
                                "invalidation price — skipping (plan_id=%s)",
                                sym, plan.get("plan_id"),
                            )
                            continue

                        entry_price = close_price_tc

                        if direction == "BUY":
                            drift_past_zone = (entry_price - zone_hi) / pip_size
                        else:
                            drift_past_zone = (zone_lo - entry_price) / pip_size
                        if drift_past_zone > 10.0:
                            logger.info(
                                "[BRIEFING-EXEC] %s TREND_ENTRY vetoed — entry %.5f is "
                                "%.1fp past zone (cap 10p). plan_id=%s plan=%s",
                                sym, entry_price, drift_past_zone,
                                plan.get("plan_id"), plan["label"],
                            )
                            continue

                        targets = plan.get("targets") or []
                        tp_price, tp_idx, tp_reason = _select_tp_target(
                            plan, sym, entry_price=entry_price, direction=direction,
                        )
                        ahead = False
                        if tp_price is not None:
                            if direction == "BUY" and tp_price > entry_price:
                                ahead = True
                            elif direction == "SELL" and tp_price < entry_price:
                                ahead = True
                        if tp_price is None or not ahead:
                            logger.info(
                                "[BRIEFING-EXEC] %s TREND_ENTRY vetoed — no target ahead "
                                "of entry %.5f (targets=%s). plan_id=%s plan=%s",
                                sym, entry_price, targets,
                                plan.get("plan_id"), plan["label"],
                            )
                            continue
                        tp1_price = tp_price
                        _plan_tgt_count = len(plan.get("targets") or [])

                        if direction == "BUY":
                            sl_pips = abs(entry_price - inv_price_tc) / pip_size
                            tp_pips = abs(tp_price - entry_price) / pip_size
                        else:
                            sl_pips = abs(inv_price_tc - entry_price) / pip_size
                            tp_pips = abs(entry_price - tp_price) / pip_size

                        if tp_reason in ("deepest", "deepest_ahead_of_entry"):
                            logger.info(
                                "[BRIEFING-EXEC] %s TREND_ENTRY TP selection: using deepest target "
                                "plan_tp_count=%d tp_idx=%d target_price=%.5f target_pips=%.1f",
                                sym, _plan_tgt_count, tp_idx, tp_price, tp_pips,
                            )
                        else:
                            logger.info(
                                "[BRIEFING-EXEC] %s TREND_ENTRY TP selection: using targets[0] "
                                "reason=%s target_price=%.5f target_pips=%.1f",
                                sym, tp_reason, tp_price, tp_pips,
                            )

                        sl_pips = max(sl_pips, 3.0)
                        tp_pips = max(tp_pips, 5.0)

                        _lv_match_te = _bl_match_levels_array(
                            briefing, entry_price, direction, pip_size,
                            _BE_LEVELS_PROXIMITY_PIPS,
                        )
                        if _lv_match_te is None:
                            if _BE_LEVELS_ARRAY_GATE_ENABLED:
                                logger.info(
                                    "[BRIEFING-EXEC] %s TREND_ENTRY vetoed — no "
                                    "levels_match_within_%.1fp. plan_id=%s plan=%s",
                                    sym, _BE_LEVELS_PROXIMITY_PIPS,
                                    plan.get("plan_id"), plan["label"],
                                )
                                continue
                            logger.info(
                                "[BRIEFING-EXEC] %s TREND_ENTRY levels_match=false "
                                "(advisory; gate disabled, proceeding). proximity=%.1fp "
                                "direction=%s plan_id=%s plan=%s",
                                sym, _BE_LEVELS_PROXIMITY_PIPS, direction,
                                plan.get("plan_id"), plan["label"],
                            )

                        if self._trigger_v2_gate(
                            plan, sym, "trend_entry",
                            {"df_5m": df_5m, "pip_size": pip_size,
                             "armed_at": float(plan.get("_armed_at") or 0.0)},
                        ):
                            continue

                        debug_tc: Dict[str, Any] = {
                            "strategy": BRIEFING_EXECUTION_MODE,
                            "entry_mode": "TREND_ENTRY",
                            "fire_path": "trend_entry_fallback",
                            "briefing_level": _lv_match_te,
                            "plan_label": plan["label"],
                            "plan_id": plan.get("plan_id") or _plan_id_for(plan),
                            "entry_zone": plan["entry_zone"],
                            "stop_loss_price": float(inv_price_tc),
                            "tp1_price": tp1_price,
                            "invalidation_price": plan.get("invalidation_price"),
                            "invalidation_direction": plan.get("invalidation_direction"),
                            "exit_time_utc": plan.get("exit_time_utc"),
                            "probability": plan["probability"],
                            "confidence": plan["confidence"],
                            "trend_closes": int(plan.get("_trend_closes", 0)),
                            "minutes_since_arm": round(elapsed_min, 1),
                        }

                        logger.info(
                            "[BRIEFING-EXEC] %s TREND_ENTRY %s @ %.5f | 2 consecutive 5M "
                            "closes through zone (%.1fmin since arm) | SL=%.1fp (inv=%.5f) "
                            "TP=%.1fp | plan_id=%s plan=%s",
                            sym, direction, entry_price, elapsed_min,
                            sl_pips, inv_price_tc, tp_pips,
                            plan.get("plan_id"), plan["label"],
                        )

                        try:
                            from guards import check_trade as _guards_check
                            _tp_price_g = entry_price - tp_pips * pip_size if direction == "SELL" \
                                else entry_price + tp_pips * pip_size
                            _g_blocked, _g_reason = _guards_check(
                                symbol=sym,
                                direction=direction,
                                strategy_mode="BRIEFING_EXECUTION",
                                intended_entry=entry_price,
                                intended_sl=float(inv_price_tc),
                                intended_tp=_tp_price_g,
                                current_mid=mid_price,
                                df_5m=df_5m,
                                pip_size=pip_size,
                            )
                            if _g_blocked:
                                logger.info(
                                    "[BRIEFING-EXEC] %s TREND_ENTRY blocked by guards: %s "
                                    "(plan_id=%s)",
                                    sym, _g_reason, plan.get("plan_id"),
                                )
                                continue
                        except Exception as _g_exc:
                            logger.warning(
                                "[BRIEFING-EXEC] guard eval raised (TREND_ENTRY, plan_id=%s): %s",
                                plan.get("plan_id"), _g_exc, exc_info=True,
                            )

                        debug_tc["plan_class"] = "continuation"

                        _emit_forensic_fire(
                            sym=sym,
                            mode=BRIEFING_EXECUTION_MODE,
                            direction=direction,
                            entry_price=entry_price,
                            df_5m=df_5m,
                            pip_size=pip_size,
                            fire_path="trend_entry_fallback",
                        )

                        try:
                            from strategy_logic import get_latest_regime_state as _gls
                            _rs = _gls(sym)
                            if isinstance(_rs, dict):
                                debug_tc["regime_state"] = _rs
                        except Exception:
                            pass

                        return StrategyDecision(
                            symbol=sym,
                            regime="BRIEFING_EXEC",
                            signal=direction,
                            mode=BRIEFING_EXECUTION_MODE,
                            entry=entry_price,
                            sl=round(sl_pips, 1),
                            tp=round(tp_pips, 1),
                            use_trailing_stop=False,
                            reason=f"briefing_trend_entry: {plan['label']}",
                            debug=debug_tc,
                        )

                # Sweep not seen and TREND_ENTRY did not fire — try next plan.
                continue

            # ── Phase 2: 5M close confirmation (only on candle close) ─────
            if not is_new_5m:
                continue

            close_price = candle_close if candle_close is not None else mid_price

            sweep_price_ph2 = plan.get("sweep_level_price")
            sweep_side_ph2 = plan.get("sweep_level_side")

            if sweep_price_ph2 is not None and sweep_side_ph2 in ("below", "above"):
                if direction == "SELL":
                    confirmed = close_price < float(sweep_price_ph2)
                else:
                    confirmed = close_price > float(sweep_price_ph2)
            else:
                confirmed = zone_lo <= close_price <= zone_hi

            if not confirmed:
                logger.info(
                    "[BRIEFING-EXEC] %s plan_id=%s strategy=BRIEFING_EXECUTION "
                    "skipped — phase2 5m close=%.5f did not confirm "
                    "(direction=%s sweep=%s zone=%.5f-%.5f)",
                    sym, plan.get("plan_id"), close_price, direction,
                    sweep_price_ph2, zone_lo, zone_hi,
                )
                continue

            _lv_match_p2 = _bl_match_levels_array(
                briefing, close_price, direction, pip_size,
                _BE_LEVELS_PROXIMITY_PIPS,
            )
            if _lv_match_p2 is None:
                if _BE_LEVELS_ARRAY_GATE_ENABLED:
                    logger.info(
                        "[BRIEFING-EXEC] %s ENTRY vetoed — no levels_match_within_%.1fp "
                        "(direction=%s). plan_id=%s plan=%s",
                        sym, _BE_LEVELS_PROXIMITY_PIPS, direction,
                        plan.get("plan_id"), plan["label"],
                    )
                    continue
                logger.info(
                    "[BRIEFING-EXEC] %s ENTRY levels_match=false (advisory; gate "
                    "disabled, proceeding). proximity=%.1fp direction=%s plan_id=%s "
                    "plan=%s",
                    sym, _BE_LEVELS_PROXIMITY_PIPS, direction,
                    plan.get("plan_id"), plan["label"],
                )

            if self._trigger_v2_gate(
                plan, sym, "phase2",
                {"df_5m": df_5m, "pip_size": pip_size,
                 "armed_at": float(plan.get("_armed_at") or 0.0)},
            ):
                continue

            entry_price = close_price
            sl_price = plan["stop_loss"]
            tp_price, tp_idx, tp_reason = _select_tp_target(
                plan, sym, entry_price=entry_price, direction=direction,
            )
            if tp_price is None:
                logger.info(
                    "[BRIEFING-EXEC] %s ENTRY vetoed — plan has no targets "
                    "(plan_id=%s)",
                    sym, plan.get("plan_id"),
                )
                continue
            tp1_price = tp_price
            tp2_price = plan["targets"][1] if len(plan["targets"]) > 1 else None
            _plan_tgt_count = len(plan.get("targets") or [])

            if direction == "BUY":
                sl_pips = abs(entry_price - sl_price) / pip_size
                tp_pips = abs(tp_price - entry_price) / pip_size
            else:
                sl_pips = abs(sl_price - entry_price) / pip_size
                tp_pips = abs(entry_price - tp_price) / pip_size

            if tp_reason in ("deepest", "deepest_ahead_of_entry"):
                logger.info(
                    "[BRIEFING-EXEC] %s TP selection: using deepest target "
                    "plan_tp_count=%d tp_idx=%d target_price=%.5f target_pips=%.1f",
                    sym, _plan_tgt_count, tp_idx, tp_price, tp_pips,
                )
            else:
                logger.info(
                    "[BRIEFING-EXEC] %s TP selection: using targets[0] reason=%s "
                    "target_price=%.5f target_pips=%.1f",
                    sym, tp_reason, tp_price, tp_pips,
                )

            sl_pips = max(sl_pips, 3.0)
            tp_pips = max(tp_pips, 5.0)

            debug: Dict[str, Any] = {
                "strategy": BRIEFING_EXECUTION_MODE,
                "fire_path": "phase2_sweep_reclaim",
                "briefing_level": _lv_match_p2,
                "plan_label": plan["label"],
                "plan_id": plan.get("plan_id") or _plan_id_for(plan),
                "entry_zone": plan["entry_zone"],
                "stop_loss_price": sl_price,
                "tp1_price": tp1_price,
                "tp2_price": tp2_price,
                "invalidation_price": plan.get("invalidation_price"),
                "invalidation_direction": plan.get("invalidation_direction"),
                "exit_time_utc": plan.get("exit_time_utc"),
                "probability": plan["probability"],
                "confidence": plan["confidence"],
            }

            logger.info(
                "[BRIEFING-EXEC] %s ENTRY %s @ %.5f (5M close confirmed) | "
                "SL=%.1f pips TP=%.1f pips | plan_id=%s plan=%s",
                sym, direction, entry_price, sl_pips, tp_pips,
                plan.get("plan_id"), plan["label"],
            )

            try:
                from guards import check_trade as _guards_check
                _g_blocked, _g_reason = _guards_check(
                    symbol=sym,
                    direction=direction,
                    strategy_mode="BRIEFING_EXECUTION",
                    intended_entry=entry_price,
                    intended_sl=sl_price,
                    intended_tp=tp_price,
                    current_mid=mid_price,
                    df_5m=df_5m,
                    pip_size=pip_size,
                )
                if _g_blocked:
                    logger.info(
                        "[BRIEFING-EXEC] %s ENTRY blocked by guards: %s "
                        "(plan_id=%s)",
                        sym, _g_reason, plan.get("plan_id"),
                    )
                    continue
            except Exception as _g_exc:
                logger.warning(
                    "[BRIEFING-EXEC] guard eval raised (ENTRY, plan_id=%s): %s",
                    plan.get("plan_id"), _g_exc, exc_info=True,
                )

            try:
                from regime_filter import infer_plan_class
                debug["plan_class"] = infer_plan_class(plan.get("label"))
            except Exception:
                debug["plan_class"] = "unknown"

            _emit_forensic_fire(
                sym=sym,
                mode=BRIEFING_EXECUTION_MODE,
                direction=direction,
                entry_price=entry_price,
                df_5m=df_5m,
                pip_size=pip_size,
                fire_path="phase2_sweep_reclaim",
            )

            try:
                from strategy_logic import get_latest_regime_state as _gls
                _rs = _gls(sym)
                if isinstance(_rs, dict):
                    debug["regime_state"] = _rs
            except Exception:
                pass

            return StrategyDecision(
                symbol=sym,
                regime="BRIEFING_EXEC",
                signal=direction,
                mode=BRIEFING_EXECUTION_MODE,
                entry=entry_price,
                sl=round(sl_pips, 1),
                tp=round(tp_pips, 1),
                use_trailing_stop=False,
                reason=f"briefing_execution_plan: {plan['label']}",
                debug=debug,
            )

        return None

    # ------------------------------------------------------------------
    # Position monitoring — invalidation + timed exit
    # ------------------------------------------------------------------

    def get_active_plan(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Return the currently-entered active plan for a symbol (used by
        autobot for post-entry monitoring). When no plan has entered,
        falls back to the highest-ranked plan still armed — preserves the
        legacy callable contract for any read site that wants "the plan."
        """
        sym = symbol.upper()
        plans = self._plans.get(sym) or []
        if not plans:
            return None
        for p in plans:
            if p.get("_entered"):
                return p
        return min(plans, key=lambda p: int(p.get("rank") or 999))

    def has_entered(self, symbol: str) -> bool:
        """Whether ANY plan-session has entered for this pair under the
        current briefing arm. Pair-level aggregation: True iff at least
        one session in ``_entered[sym]`` is locked."""
        return any(self._entered.get(symbol.upper(), {}).values())

    def _trigger_v2_gate(
        self,
        plan: Dict[str, Any],
        sym: str,
        entry_mode: str,
        price_context: Dict[str, Any],
    ) -> bool:
        """Evaluate entry_trigger_v2 per BRIEFING_EXEC_TRIGGER_V2_MODE.

        Returns True if the caller should block the entry; False otherwise.
        Handles off/shadow/live dispatch + logging here so the call sites
        stay minimal.
        """
        if BRIEFING_EXEC_TRIGGER_V2_MODE == "off":
            return False
        if not plan.get("_triggers_parsed"):
            # absent/malformed v2 → legacy gating for this plan only
            return False

        now_utc = datetime.now(timezone.utc)
        ok, failed = _all_triggers_satisfied(plan, sym, now_utc, price_context)
        bt = self._briefing_id.get(sym, "?")

        if BRIEFING_EXEC_TRIGGER_V2_MODE == "shadow":
            logger.info(
                "[BRIEFING-EXEC-SHADOW] %s would_block=%s failed=%s "
                "briefing_time=%s entry_mode=%s",
                sym, (not ok), failed, bt, entry_mode,
            )
            return False  # never block in shadow

        # live
        if not ok:
            logger.info(
                "[BRIEFING-EXEC] %s %s BLOCKED trigger_v2 plan_id=%s "
                "briefing_time=%s entry_mode=%s reason=%s",
                sym, plan.get("direction"), plan.get("plan_id") or _plan_id_for(plan),
                bt, entry_mode, failed,
            )
            return True
        logger.info(
            "[BRIEFING-EXEC] %s entry_trigger_v2 satisfied (entry_mode=%s)",
            sym, entry_mode,
        )
        return False

    def on_broker_confirmed(
        self,
        sym: str,
        briefing_time: Optional[str] = None,
        deal_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> None:
        """Pessimistic commit: mark the firing plan's session entered only
        after the broker has ACCEPTED the order. Idempotent — a second
        call for the same (sym, session) is a no-op aside from a debug
        log.

        Step 2B — splits plan_id ("<session>_<rank>") to recover the
        session and sets ``_entered[sym][session] = True`` rather than the
        legacy pair-level latch. Also marks the matching plan dict with
        ``_entered=True`` so post-entry helpers (should_invalidation_close,
        should_time_exit) can find the fired plan.

        When plan_id is missing (legacy callsite), falls back to "lock
        every armed plan's session" — conservative, preserves the prior
        behaviour where any fire locked the pair.
        """
        s = sym.upper()
        expected_bt = self._briefing_id.get(s, "")
        if briefing_time and expected_bt and str(briefing_time) != expected_bt:
            logger.info(
                "[BRIEFING-EXEC] %s on_broker_confirmed briefing_time mismatch "
                "(callback=%s, current=%s) — proceeding with current briefing",
                s, briefing_time, expected_bt,
            )

        # Derive session from plan_id: "<session>_<rank>". When unknown,
        # we cannot key the per-session lockout precisely; fall back to
        # locking every armed session on the pair.
        session: Optional[str] = None
        if plan_id and "_" in str(plan_id):
            session = str(plan_id).split("_", 1)[0]
        if plan_id:
            logger.info(
                "[BRIEFING-EXEC] %s fill confirmed plan_id=%s session=%s dealId=%s",
                s, plan_id, session or "?", deal_id or "?",
            )

        # Find the plan dict matching plan_id (if any) and mark it
        # _entered so monitor helpers consult the right plan.
        plans = self._plans.get(s) or []
        matched_plan: Optional[Dict[str, Any]] = None
        if plan_id:
            for p in plans:
                if p.get("plan_id") == plan_id:
                    matched_plan = p
                    break

        if session:
            if self._is_entered(s, session):
                logger.debug(
                    "[BRIEFING-EXEC] %s on_broker_confirmed — session %s already "
                    "locked (deal_id=%s, plan_id=%s); idempotent no-op",
                    s, session, deal_id or "?", plan_id or "-",
                )
                return
            self._mark_entered(s, session)
            if matched_plan is not None:
                matched_plan["_entered"] = True
            self._persist_entered(s, plan_id=plan_id, session=session)
            logger.info(
                "[BRIEFING-EXEC] %s session %s locked on broker confirmation "
                "(deal_id=%s, plan_id=%s, briefing_time=%s)",
                s, session, deal_id or "?", plan_id or "-", expected_bt or "?",
            )
            return

        # plan_id absent/unparseable — legacy lockdown: every armed
        # session gets locked. Same conservative behaviour as the prior
        # pair-scoped latch.
        if not plans:
            logger.warning(
                "[BRIEFING-EXEC] %s on_broker_confirmed with no plan_id and "
                "no armed plans — nothing to lock (deal_id=%s)",
                s, deal_id or "?",
            )
            return
        locked_any = False
        for p in plans:
            sess_p = str(p.get("session") or "")
            if not sess_p or self._is_entered(s, sess_p):
                continue
            self._mark_entered(s, sess_p)
            p["_entered"] = True
            locked_any = True
        if locked_any:
            self._persist_entered(s, plan_id=plan_id, session=None)
            logger.info(
                "[BRIEFING-EXEC] %s sessions %s locked on broker confirmation "
                "(legacy no-plan_id fallback, deal_id=%s, briefing_time=%s)",
                s, sorted(self._entered.get(s, {}).keys()),
                deal_id or "?", expected_bt or "?",
            )

    def _persist_entered(
        self,
        symbol: str,
        plan_id: Optional[str] = None,
        session: Optional[str] = None,
    ) -> None:
        """Write the dedup record for `symbol` to disk so it survives
        restart.

        Schema (Step 2B):
        - ``briefing_time``, ``fired_at`` — unchanged.
        - ``entered_by_plan`` — additive dict (kept from 2A) of plan_id → True.
        - ``entered_by_session`` — NEW dict of session → True; what 2B
          on_briefing rehydration reads. Old readers ignore it; new
          readers gracefully derive from ``entered_by_plan`` when the new
          field is absent.
        """
        sym = symbol.upper()
        briefing_time = self._briefing_id.get(sym, "")
        if not briefing_time:
            return  # nothing to dedup against
        try:
            cache = _load_entered_cache()
            rec = cache.get(sym)
            # Fresh briefing => start a clean record. Same briefing =>
            # preserve existing dicts so multiple fires accumulate.
            if not isinstance(rec, dict) or str(rec.get("briefing_time", "")) != briefing_time:
                rec = {"briefing_time": briefing_time, "fired_at": _time.time()}
            else:
                rec["fired_at"] = _time.time()
            if plan_id:
                ebp = rec.get("entered_by_plan")
                if not isinstance(ebp, dict):
                    ebp = {}
                ebp[plan_id] = True
                rec["entered_by_plan"] = ebp
            # Mirror in-memory _entered into the on-disk dict. When the
            # caller passes ``session`` we know exactly what flipped;
            # when it doesn't (legacy no-plan_id fallback), we dump all
            # currently-locked sessions.
            ebs = rec.get("entered_by_session")
            if not isinstance(ebs, dict):
                ebs = {}
            if session:
                ebs[session] = True
            else:
                for k, v in (self._entered.get(sym) or {}).items():
                    if bool(v):
                        ebs[k] = True
            rec["entered_by_session"] = ebs
            cache[sym] = rec
            _save_entered_cache(cache)
        except Exception as e:
            logger.warning("[BRIEFING-EXEC] %s _persist_entered failed: %s", sym, e)

    # ------------------------------------------------------------------
    # Phase 2 — per-pair plan-state persistence
    # ------------------------------------------------------------------

    def _save_plans_state(self, symbol: str) -> None:
        """Atomic write of the per-pair plan state to
        /opt/tradingbot/cache/briefing_plans_<SYMBOL>.json. Tolerates
        write failures with a warning.

        Step 2B writes the new field ``active_plans`` (plural, list).
        Each plan dict carries its own latches (_sweep_seen, _armed_at,
        _trend_closes, _dormant, _entered) so the list-only schema is
        round-trip complete — no sibling state dicts to persist.
        """
        sym = symbol.upper()
        path = _plans_cache_path(sym)
        payload = {
            "symbol":            sym,
            "briefing_time":     self._briefing_id.get(sym, ""),
            "saved_at":          datetime.now(timezone.utc).isoformat(),
            "active_plans":      list(self._plans.get(sym) or []),
            "london_plans":      self._london_plans.get(sym, []),
            "ny_pending":        self._ny_pending.get(sym, []),
            "ny_armed":          self._ny_armed.get(sym, []),
            "ny_discarded":      self._ny_discarded.get(sym, []),
            "ny_eval_date":      self._ny_eval_date.get(sym, ""),
            "invalidated_plans": self._invalidated_plans.get(sym, []),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, default=str))
            os.replace(tmp, path)
        except Exception as exc:
            logger.warning("[BRIEFING-EXEC] %s _save_plans_state failed: %s", sym, exc)

    @staticmethod
    def _find_briefing_for_plan(
        sym: str, briefing_time: str,
    ) -> Optional[Dict[str, Any]]:
        """Locate the briefing JSON whose `briefing_time` matches and return
        its parsed dict. Returns None if no match (file missing, parse
        error, or no matching briefing_time)."""
        if not briefing_time:
            return None
        # briefing_time is ISO8601, e.g. "2026-05-01T05:32:15Z" → date 2026-05-01.
        try:
            date_str = briefing_time.split("T")[0]
        except Exception:
            return None
        log_dir = Path(os.getenv("LOG_DIR", "/opt/tradingbot/logs"))
        for path in sorted(log_dir.glob(f"briefing_{sym}_{date_str}_*.json")):
            try:
                b = json.loads(path.read_text())
            except Exception:
                continue
            if str(b.get("briefing_time") or "") == briefing_time:
                return b
        return None

    def _backfill_invalidation_timeframe(
        self, sym: str, plan: Dict[str, Any], briefing_time: str,
    ) -> None:
        """Look up the originating briefing JSON, find the matching plan
        by label, re-parse its `invalidation` text, and set the plan dict's
        `invalidation_timeframe`. On any failure, default to "5m" with a
        WARNING log line so the gap is visible.
        """
        label = str(plan.get("label") or "")
        briefing = self._find_briefing_for_plan(sym, briefing_time)
        if briefing is None:
            logger.warning(
                "[BRIEFING-EXEC] %s could not locate briefing JSON for "
                "label=%r briefing_time=%s — defaulting "
                "invalidation_timeframe='5m'",
                sym, label, briefing_time,
            )
            plan["invalidation_timeframe"] = "5m"
            return
        for orig in (briefing.get("trading_plans") or []):
            if not isinstance(orig, dict):
                continue
            if str(orig.get("label") or "") == label:
                inv_text = str(orig.get("invalidation") or "")
                _, _, tf = _parse_invalidation(inv_text)
                plan["invalidation_timeframe"] = tf
                logger.info(
                    "[BRIEFING-EXEC] %s backfilled invalidation_timeframe=%s "
                    "for plan %r (text=%r)",
                    sym, tf, label, inv_text[:80],
                )
                return
        logger.warning(
            "[BRIEFING-EXEC] %s no briefing plan matched label=%r — "
            "defaulting invalidation_timeframe='5m'",
            sym, label,
        )
        plan["invalidation_timeframe"] = "5m"

    def _hydrate_plans_state_from_disk(self) -> None:
        """On startup, restore any same-day persisted plan state from
        /opt/tradingbot/cache/briefing_plans_*.json. Stale entries
        (briefing_time not today) are ignored — we'll wait for the next
        fresh briefing instead.
        """
        if not _PLANS_CACHE_DIR.exists():
            return
        for path in _PLANS_CACHE_DIR.glob("briefing_plans_*.json"):
            try:
                payload = json.loads(path.read_text())
            except Exception as exc:
                logger.warning("[BRIEFING-EXEC] hydrate skipped %s: %s", path.name, exc)
                continue
            sym = str(payload.get("symbol") or "").upper()
            briefing_time = str(payload.get("briefing_time") or "")
            if not sym or not _briefing_time_is_today(briefing_time):
                continue

            self._briefing_id[sym]  = briefing_time

            # Step 2B — prefer the new ``active_plans`` (list) field; fall
            # back to wrapping a singleton ``active_plan`` from a pre-2B
            # cache. Caches written by 2B no longer carry the old field.
            ap_list = payload.get("active_plans")
            ap_singleton = payload.get("active_plan")
            active_list: List[Dict[str, Any]] = []
            if isinstance(ap_list, list):
                for p in ap_list:
                    if isinstance(p, dict):
                        active_list.append(p)
            elif isinstance(ap_singleton, dict):
                active_list = [ap_singleton]

            hydrated: List[Dict[str, Any]] = []
            for p in active_list:
                if p.get("invalidation_timeframe") is None:
                    self._backfill_invalidation_timeframe(sym, p, briefing_time)
                # Pre-2B caches persisted active-plan dicts without `rank`.
                # Without rank, _plan_id_for warns and stamps
                # "unknown_unknown" — leaving an identity-less plan in
                # _plans[sym] that subsequent log lines treat as a phantom
                # duplicate. Re-derive rank from the originating briefing
                # JSON by label match (same mechanism as
                # _backfill_invalidation_timeframe). If recovery fails the
                # plan has no source of truth — hard-drop rather than
                # promote.
                if not isinstance(p.get("rank"), int):
                    label = str(p.get("label") or "")
                    briefing = self._find_briefing_for_plan(sym, briefing_time)
                    recovered = False
                    if briefing is not None:
                        for orig in (briefing.get("trading_plans") or []):
                            if not isinstance(orig, dict):
                                continue
                            if str(orig.get("label") or "") == label:
                                rk = orig.get("rank")
                                sess = orig.get("session")
                                if isinstance(rk, int):
                                    p["rank"] = rk
                                if isinstance(sess, str) and sess.strip():
                                    p["session"] = sess
                                recovered = isinstance(p.get("rank"), int)
                                break
                    if not recovered:
                        logger.warning(
                            "[BRIEFING-EXEC] %s hydrate: dropping pre-schema plan "
                            "label=%r — rank not recoverable from briefing JSON "
                            "(briefing_time=%s)",
                            sym, label, briefing_time,
                        )
                        continue
                # Backfill plan_id (pre-2A caches) and per-plan latches
                # (pre-2B caches lack _sweep_seen etc.). _per_plan_init
                # is destructive on _sweep_seen / _armed_at / _trend_closes,
                # so only call when the plan does not already carry them.
                if not p.get("plan_id"):
                    p["plan_id"] = _plan_id_for(p)
                if "_armed_at" not in p:
                    self._per_plan_init(p)
                hydrated.append(p)

            active_list = hydrated
            self._plans[sym]             = active_list
            self._london_plans[sym]      = list(payload.get("london_plans") or [])
            self._ny_pending[sym]        = list(payload.get("ny_pending") or [])
            self._ny_armed[sym]          = list(payload.get("ny_armed") or [])
            self._ny_discarded[sym]      = list(payload.get("ny_discarded") or [])
            self._invalidated_plans[sym] = list(payload.get("invalidated_plans") or [])
            ned = str(payload.get("ny_eval_date") or "")
            if ned:
                self._ny_eval_date[sym] = ned

            logger.info(
                "[BRIEFING-EXEC] %s plan state hydrated from %s — "
                "active=%d london=%d ny_pending=%d ny_armed=%d ny_discarded=%d "
                "invalidated=%d",
                sym, path.name,
                len(active_list),
                len(self._london_plans[sym]),
                len(self._ny_pending[sym]),
                len(self._ny_armed[sym]),
                len(self._ny_discarded[sym]),
                len(self._invalidated_plans[sym]),
            )

    def _entered_plan(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Return the plan dict that fired (carries ``_entered=True``).
        Used by post-entry monitor helpers. Returns None when no plan is
        marked entered (e.g. legacy callers before 2B, or no fire yet)."""
        sym = symbol.upper()
        for p in self._plans.get(sym) or []:
            if p.get("_entered"):
                return p
        return None

    def should_invalidation_close(
        self, symbol: str, candle_close: float,
    ) -> bool:
        """Check 5M candle close against the entered plan's invalidation
        level. Returns True if the position should be force-closed.

        Consults the plan whose session has fired (``_entered=True`` on
        the plan dict) so multi-plan briefings monitor the right level.
        """
        plan = self._entered_plan(symbol)
        if plan is None:
            return False

        inv_price = plan.get("invalidation_price")
        inv_dir = plan.get("invalidation_direction")
        if inv_price is None or inv_dir is None:
            return False

        if inv_dir == "above" and candle_close > inv_price:
            logger.info(
                "[BRIEFING-EXEC] %s INVALIDATION (plan_id=%s): 5M close %.5f > %.5f "
                "— force close",
                symbol.upper(), plan.get("plan_id"), candle_close, inv_price,
            )
            return True
        if inv_dir == "below" and candle_close < inv_price:
            logger.info(
                "[BRIEFING-EXEC] %s INVALIDATION (plan_id=%s): 5M close %.5f < %.5f "
                "— force close",
                symbol.upper(), plan.get("plan_id"), candle_close, inv_price,
            )
            return True

        return False

    def should_time_exit(self, symbol: str) -> bool:
        """Check if the current UTC time has reached the entered plan's
        forced exit time. Consults the fired plan (``_entered=True``)."""
        plan = self._entered_plan(symbol)
        if plan is None:
            return False

        exit_time = plan.get("exit_time_utc")
        if exit_time is None:
            return False

        now = datetime.now(timezone.utc)
        exit_h, exit_m = exit_time
        if now.hour > exit_h or (now.hour == exit_h and now.minute >= exit_m):
            logger.info(
                "[BRIEFING-EXEC] %s TIME EXIT (plan_id=%s): UTC %02d:%02d >= "
                "%02d:%02d — force close",
                symbol.upper(), plan.get("plan_id"),
                now.hour, now.minute, exit_h, exit_m,
            )
            return True

        return False
