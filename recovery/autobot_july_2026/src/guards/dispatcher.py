"""Shared guard runner — called by strategies before fire."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from guards.base import Guard, GuardContext, GuardResult
from guards.registry import GUARD_REGISTRY

logger = logging.getLogger("AutoBot")

_LOG_PATH = Path(os.getenv("LOG_DIR", "/opt/tradingbot/logs")) / "guards_observed.jsonl"
_LOG_LOCK = threading.Lock()


def _enabled_master() -> bool:
    return str(os.getenv("GUARDS_ENABLED", "1")).strip() in ("1", "true", "yes")


def _observable_only() -> bool:
    return str(os.getenv("GUARDS_OBSERVABLE_ONLY", "1")).strip() in ("1", "true", "yes")


_GUARD_CACHE: dict = {}


def _load_guard(guard_name: str) -> Optional[Guard]:
    if guard_name in _GUARD_CACHE:
        return _GUARD_CACHE[guard_name]

    instance: Optional[Guard] = None
    try:
        if guard_name == "stale_briefing":
            from guards.stale_briefing import StaleBriefingGuard
            instance = StaleBriefingGuard()
        elif guard_name == "news_blackout":
            from guards.news_blackout import NewsBlackoutGuard
            instance = NewsBlackoutGuard()
        elif guard_name == "priced_in":
            from guards.priced_in import PricedInGuard
            instance = PricedInGuard()
        elif guard_name == "opposing_regime":
            from guards.opposing_regime import OpposingRegimeGuard
            instance = OpposingRegimeGuard()
        elif guard_name == "levels_proximity":
            from guards.levels_proximity import LevelsProximityGuard
            instance = LevelsProximityGuard()
    except Exception as exc:
        logger.warning("[guards] failed to load %s: %s", guard_name, exc)
        return None

    _GUARD_CACHE[guard_name] = instance
    return instance


def evaluate_guards(context: GuardContext) -> List[GuardResult]:
    if not _enabled_master():
        return []

    guard_names = GUARD_REGISTRY.get(context.strategy_mode, [])
    results: List[GuardResult] = []
    for name in guard_names:
        guard = _load_guard(name)
        if guard is None:
            continue
        if not guard.is_enabled():
            continue
        try:
            results.append(guard.evaluate(context))
        except Exception as exc:
            logger.warning("[guards] %s.evaluate raised: %s", name, exc, exc_info=True)
    return results


def _log_event(context: GuardContext, results: List[GuardResult],
               would_have_blocked: bool, actually_blocked: bool, trade_fired: bool) -> None:
    blocked = [r for r in results if r.block]
    passed = [r for r in results if not r.block]
    payload = {
        "ts": context.current_time_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbol": context.symbol,
        "strategy_mode": context.strategy_mode,
        "intended_direction": str(context.direction).upper(),
        "intended_entry": context.intended_entry,
        "guards_evaluated": [r.guard_name for r in results],
        "guards_blocked": [r.guard_name for r in blocked],
        "guards_passed":  [r.guard_name for r in passed],
        "block_data": {r.guard_name: r.data for r in blocked},
        "guard_results": {
            r.guard_name: {"block": r.block, "reason": r.reason, "data": r.data}
            for r in results
        },
        "would_have_blocked": would_have_blocked,
        "actually_blocked": actually_blocked,
        "trade_fired": trade_fired,
    }
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK:
            with open(_LOG_PATH, "a") as f:
                f.write(json.dumps(payload, default=str) + "\n")
    except Exception as exc:
        logger.warning("[guards] failed to write %s: %s", _LOG_PATH, exc)


def _build_news_event_window(symbol: str, current_utc: datetime, window_mins: int) -> Tuple[bool, dict]:
    """Return (is_in_active_blackout, nearest_event_dict_or_empty).

    Reads the news_blackout module's window store directly so we can return
    structured event info (name/time/mins-to-event) rather than the prose
    reason string is_news_blackout returns.
    """
    try:
        import news_blackout as nb
    except Exception:
        return False, {}

    in_blackout, _reason = (False, "")
    try:
        in_blackout, _reason = nb.is_news_blackout(current_utc)
    except Exception:
        pass

    nearest: dict = {}
    try:
        windows = getattr(nb, "_windows", {}) or {}
        date_key = current_utc.strftime("%Y-%m-%d")
        times = windows.get(date_key) or []
        now_minutes = current_utc.hour * 60 + current_utc.minute + current_utc.second / 60.0
        best_mins = None
        best_t = None
        for t_str in times:
            try:
                h, m = map(int, str(t_str).split(":"))
            except (ValueError, AttributeError):
                continue
            ev_minutes = h * 60 + m
            delta = ev_minutes - now_minutes
            if delta < -1:
                continue
            if delta > window_mins:
                continue
            if best_mins is None or delta < best_mins:
                best_mins = delta
                best_t = t_str
        if best_t is not None:
            nearest = {
                "event_name": "news",
                "event_time_utc": best_t,
                "mins_to_event": round(float(best_mins), 2),
                "blackout_minutes": int(getattr(nb, "_PRE_MINUTES", 5) or 5),
            }
    except Exception as exc:
        logger.debug("[guards] news event window lookup failed: %s", exc)

    return in_blackout, nearest


def check_trade(
    symbol: str,
    direction: str,
    strategy_mode: str,
    intended_entry: float,
    intended_sl: float,
    intended_tp: float,
    current_mid: float,
    df_5m,
    pip_size: float,
    current_time_utc: Optional[datetime] = None,
    window_mins: int = 30,
) -> Tuple[bool, str]:
    """High-level entry-point used by strategies. Builds context, runs guards,
    returns (block, reason). Returns (False, "") when no guards are registered
    for the strategy or guards are disabled.
    """
    if current_time_utc is None:
        current_time_utc = datetime.now(timezone.utc)
    elif current_time_utc.tzinfo is None:
        current_time_utc = current_time_utc.replace(tzinfo=timezone.utc)

    if not GUARD_REGISTRY.get(strategy_mode):
        return False, ""

    briefing_data = None
    try:
        import morning_briefing
        briefing_data = morning_briefing.get_briefing(symbol)
    except Exception as exc:
        logger.debug("[guards] briefing fetch failed: %s", exc)

    in_blackout, nearest = _build_news_event_window(symbol, current_time_utc, window_mins)

    ctx = GuardContext(
        symbol=symbol,
        direction=direction,
        strategy_mode=strategy_mode,
        intended_entry=float(intended_entry),
        intended_sl=float(intended_sl),
        intended_tp=float(intended_tp),
        current_mid=float(current_mid),
        current_time_utc=current_time_utc,
        df_5m=df_5m,
        briefing_data=briefing_data,
        news_blackout_active=in_blackout,
        news_event_in_window=nearest or None,
        pip_size=float(pip_size or 0.0001),
    )

    results = evaluate_guards(ctx)
    return should_block(ctx, results)


def should_block(context: GuardContext, results: List[GuardResult]) -> Tuple[bool, str]:
    """Return (block, reason). In observable mode block is always False but
    would-block events are still logged. In live mode any blocking guard wins.
    """
    blocking = [r for r in results if r.block]
    would_have = bool(blocking)

    if not blocking:
        if results:
            _log_event(context, results, would_have_blocked=False,
                       actually_blocked=False, trade_fired=True)
        return False, ""

    if _observable_only():
        _log_event(context, results, would_have_blocked=True,
                   actually_blocked=False, trade_fired=True)
        for r in blocking:
            logger.info(
                "[GUARDS] %s/%s WOULD_BLOCK (observable) — %s: %s",
                context.symbol, context.strategy_mode, r.guard_name, r.reason,
            )
        return False, ""

    reasons = "|".join(f"{r.guard_name}:{r.reason}" for r in blocking)
    _log_event(context, results, would_have_blocked=True,
               actually_blocked=True, trade_fired=False)
    for r in blocking:
        logger.warning(
            "[GUARDS] %s/%s BLOCKED — %s: %s",
            context.symbol, context.strategy_mode, r.guard_name, r.reason,
        )
    return True, reasons
