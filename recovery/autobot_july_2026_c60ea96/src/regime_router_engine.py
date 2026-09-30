"""Regime-driven strategy router (Stage 3).

Reads the regime computed once per 5m close by regime_engine.emit() and dispatches
0 or 1 strategy per pair per close, per a fixed MAP. Single classify per close →
the regime_instance_id stamped on the decision matches the one written to
logs/regime_engine.jsonl by emit(), giving the OUTCOME JOIN a clean key.

MAP:
  RANGE_ROTATION                                                   -> BB_REVERSAL  (bidir; band logic picks side)
  STRONG_TREND_UP   / TREND_FORMING_UP   / BREAKOUT_FORMING_UP     -> EMA_PULLBACK LONG
  STRONG_TREND_DOWN / TREND_FORMING_DOWN / BREAKOUT_FORMING_DOWN   -> EMA_PULLBACK SHORT
  COMPRESSION / CHOP / VOLATILITY_EXPANSION                        -> STAND_DOWN

Confidence: NO floor. Dispatch on any arming regime. Confidence is stamped onto
the decision for the learning loop.

Thread model: runs in the regime worker pool (single worker, same as emit). All
exceptions are caught and logged — a router error must never propagate up the
5m-close callback chain.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── Regime → strategy MAP ──────────────────────────────────────────────────
_BIDIR = "BIDIR"
_LONG = "LONG"
_SHORT = "SHORT"

_REGIME_MAP: Dict[str, Dict[str, Optional[str]]] = {
    "RANGE_ROTATION":        {"strategy": "BB_REVERSAL",  "direction": _BIDIR},
    "STRONG_TREND_UP":       {"strategy": "EMA_PULLBACK", "direction": _LONG},
    "TREND_FORMING_UP":      {"strategy": "EMA_PULLBACK", "direction": _LONG},
    "BREAKOUT_FORMING_UP":   {"strategy": "EMA_PULLBACK", "direction": _LONG},
    "STRONG_TREND_DOWN":     {"strategy": "EMA_PULLBACK", "direction": _SHORT},
    "TREND_FORMING_DOWN":    {"strategy": "EMA_PULLBACK", "direction": _SHORT},
    "BREAKOUT_FORMING_DOWN": {"strategy": "EMA_PULLBACK", "direction": _SHORT},
    "COMPRESSION":           {"strategy": None,           "direction": None},
    "CHOP":                  {"strategy": None,           "direction": None},
    "VOLATILITY_EXPANSION":  {"strategy": None,           "direction": None},
}


# Pip-size mirror (matches autobot._BE_PIP_SIZE_FOR_SUMMARY at autobot.py:1582).
# Kept local so the router has no import dependency on autobot's pricing layer.
_PIP_SIZE: Dict[str, float] = {
    "GBPUSD": 1.0, "EURUSD": 1.0, "USDJPY": 1.0, "USDCAD": 1.0, "GBPJPY": 1.0,
}


def _stamp_regime(decision: Any, regime_result: Dict[str, Any],
                  router_direction: str) -> None:
    """Attach the four OUTCOME-JOIN fields to decision.debug."""
    try:
        dbg = dict(getattr(decision, "debug", None) or {})
        dbg["regime_instance_id"]      = regime_result.get("regime_instance_id")
        dbg["regime"]                  = regime_result.get("regime")
        dbg["regime_confidence_final"] = regime_result.get("confidence")
        dbg["router_direction"]        = router_direction
        decision.debug = dbg
    except Exception as exc:
        logger.warning("[ROUTER] regime stamp failed: %s", exc)


def _dispatch_bb_reversal(sym: str, epic: str, df_5m: Any,
                          pip_size: float, mid_price: float) -> Optional[Any]:
    try:
        from bb_reversal import (
            BB_REVERSAL_ENABLED,
            ALLOWED_PAIRS,
            get_instance as _bb_get_instance,
        )
    except Exception as exc:
        logger.warning("[ROUTER] BB_REVERSAL import failed: %s", exc)
        return None
    if not BB_REVERSAL_ENABLED:
        logger.info("[ROUTER] %s BB_REVERSAL disabled at module level "
                    "(BB_REVERSAL_ENABLED=0)", sym)
        return None
    if sym not in ALLOWED_PAIRS:
        logger.info("[ROUTER] %s BB_REVERSAL pair_not_allowed (ALLOWED=%s)",
                    sym, sorted(ALLOWED_PAIRS))
        return None
    try:
        # bb_reversal.get_instance() handles None-vs-missing-attr correctly.
        # Cannot use the hasattr-pattern here: BBReversalStrategy._instance is
        # a class-level None, so hasattr() is True even pre-init.
        return _bb_get_instance().evaluate(
            sym, epic, df_5m, pip_size, float(mid_price),
        )
    except Exception as exc:
        logger.warning("[ROUTER] %s BB_REVERSAL evaluate raised: %s", sym, exc)
        return None


def _dispatch_ema_pullback(sym: str, epic: str, df_5m: Any,
                            pip_size: float, mid_price: float,
                            router_direction: str) -> Optional[Any]:
    try:
        from ema_pullback import EmaPullbackStrategy, EMA_PULLBACK_ENABLED
    except Exception as exc:
        logger.warning("[ROUTER] EMA_PULLBACK import failed: %s", exc)
        return None
    if not EMA_PULLBACK_ENABLED:
        logger.info("[ROUTER] %s EMA_PULLBACK disabled at module level "
                    "(EMA_PULLBACK_ENABLED=0)", sym)
        return None
    # Briefing is optional from the strategy's POV — falls back to None.
    briefing = None
    try:
        import morning_briefing as _mb
        briefing = _mb.get_briefing(sym)
    except Exception:
        briefing = None
    try:
        if not hasattr(EmaPullbackStrategy, "_instance"):
            EmaPullbackStrategy._instance = EmaPullbackStrategy()
        return EmaPullbackStrategy._instance.evaluate(
            sym, epic, df_5m, pip_size, float(mid_price), briefing,
            router_direction=str(router_direction).upper(),
        )
    except Exception as exc:
        logger.warning("[ROUTER] %s EMA_PULLBACK evaluate raised: %s", sym, exc)
        return None


def dispatch(sym: str, payload: Dict[str, Any],
             regime_result: Dict[str, Any]) -> None:
    """Pair-level dispatch on a 5m close.

    `regime_result` is the dict returned by regime_engine.emit() / classify_regime()
    for THIS close. The router shares the same `regime_instance_id` so the
    OUTCOME JOIN can be built downstream.
    """
    sym_u = str(sym).upper()
    regime = str(regime_result.get("regime", "")).upper()
    inst_id = regime_result.get("regime_instance_id")
    conf = regime_result.get("confidence")

    try:
        entry = _REGIME_MAP.get(regime)
        if entry is None:
            logger.warning(
                "[ROUTER] %s regime=%s → UNKNOWN regime (no MAP entry, "
                "treating as STAND_DOWN) iid=%s",
                sym_u, regime, inst_id,
            )
            return

        strategy = entry["strategy"]
        router_direction = entry["direction"] or ""

        # 1) STAND_DOWN.
        if strategy is None:
            logger.info(
                "[ROUTER] %s regime=%s → STAND_DOWN (no dispatch) iid=%s conf=%s",
                sym_u, regime, inst_id,
                f"{float(conf):.4f}" if conf is not None else "N/A",
            )
            return

        # 2) Pull execution context from the 5m-close payload.
        df_5m = payload.get("df_5m") if isinstance(payload, dict) else None
        if df_5m is None or len(df_5m) < 1:
            logger.warning(
                "[ROUTER] %s regime=%s → ABORT (no df_5m on payload) iid=%s",
                sym_u, regime, inst_id,
            )
            return

        try:
            mid_price = float(df_5m["close"].iloc[-1])
        except Exception as exc:
            logger.warning(
                "[ROUTER] %s regime=%s → ABORT (mid_price extract failed: %s) iid=%s",
                sym_u, regime, exc, inst_id,
            )
            return

        # Epic lookup — autobot owns EPIC_MAP.
        epic = ""
        try:
            import autobot
            epic = (getattr(autobot, "EPIC_MAP", {}) or {}).get(sym_u, "")
        except Exception as _em_exc:
            logger.debug("[ROUTER] EPIC_MAP import failed: %s", _em_exc)
        if not epic:
            logger.warning(
                "[ROUTER] %s regime=%s → ABORT (no epic for sym) iid=%s",
                sym_u, regime, inst_id,
            )
            return

        pip_size = float(_PIP_SIZE.get(sym_u, 1.0))

        # 3) Dispatch to the selected strategy.
        if strategy == "BB_REVERSAL":
            decision = _dispatch_bb_reversal(
                sym_u, epic, df_5m, pip_size, mid_price,
            )
        elif strategy == "EMA_PULLBACK":
            decision = _dispatch_ema_pullback(
                sym_u, epic, df_5m, pip_size, mid_price, router_direction,
            )
        else:
            logger.warning(
                "[ROUTER] %s regime=%s → ABORT (unknown strategy %r in MAP) iid=%s",
                sym_u, regime, strategy, inst_id,
            )
            return

        if decision is None:
            return  # Reason already logged in _dispatch_*.

        sig = str(getattr(decision, "signal", "") or "").upper()
        if sig not in ("BUY", "SELL"):
            reason = str(getattr(decision, "reason", "") or "no_signal")
            logger.info(
                "[ROUTER] %s regime=%s → dispatch %s %s → strategy returned "
                "NONE (%s) iid=%s",
                sym_u, regime, strategy, router_direction, reason, inst_id,
            )
            return

        # 4) Stamp regime fields BEFORE execute_trade so the OUTCOME JOIN
        #    can link back to this regime call via decision.debug.
        _stamp_regime(decision, regime_result, router_direction)

        # 5) Optional concurrent-cap pre-check (defence in depth — execute_trade
        #    has its own gates). Logs the precise reason so Monday's debugging
        #    isn't guesswork.
        try:
            from strategy_logic import (
                _strategy_family as _fam,
                _resolve_concurrent_cap as _cap_for,
                _count_open_positions as _cnt_open,
            )
            _sname = _fam(str(getattr(decision, "mode", "") or ""))
            _capn = _cap_for(_sname)
            if _capn is not None:
                _cur = _cnt_open(epic, _sname)
                if _cur >= _capn:
                    logger.info(
                        "[ROUTER] %s regime=%s → dispatch %s %s → execute_trade "
                        "BLOCKED (concurrent_cap %d/%d on %s) iid=%s",
                        sym_u, regime, strategy, router_direction,
                        _cur, _capn, _sname, inst_id,
                    )
                    return
        except Exception as _cap_exc:
            logger.debug(
                "[ROUTER] cap pre-check failed (proceeding): %s", _cap_exc,
            )

        # 6) Fire.
        try:
            from trade_executor import execute_trade, EPIC_STATE
            res = execute_trade(decision, epic)
        except Exception as exc:
            logger.warning(
                "[ROUTER] %s regime=%s → dispatch %s %s → execute_trade "
                "RAISED (%s) iid=%s",
                sym_u, regime, strategy, router_direction, exc, inst_id,
            )
            return

        if not res:
            logger.info(
                "[ROUTER] %s regime=%s → dispatch %s %s → execute_trade "
                "BLOCKED (no fill — cap/dedup/cooldown/order_reject) iid=%s",
                sym_u, regime, strategy, router_direction, inst_id,
            )
            return

        # 7) Persist decision.debug onto EPIC_STATE so _on_trade_close can read
        #    the regime stamp for the outcome push (matches the existing
        #    pattern at autobot.py:2578 / 2768 / 2896 / 3243 / 3574 / 3694 / 3934).
        _deal_id = None
        _pk = None
        try:
            if isinstance(res, dict):
                _deal_id = res.get("dealId") or res.get("deal_id")
                _pk = res.get("_pos_key") or f"{epic}|{str(getattr(decision, 'mode', '') or '').upper()}"
            else:
                _pk = f"{epic}|{str(getattr(decision, 'mode', '') or '').upper()}"
            _es = EPIC_STATE.get(_pk)
            if isinstance(_es, dict):
                _es["decision_debug"] = dict(getattr(decision, "debug", None) or {})
        except Exception as _es_exc:
            logger.debug(
                "[ROUTER] decision_debug persist on EPIC_STATE failed: %s",
                _es_exc,
            )

        # 7b) Signal-log open record — closes the router fire-path gap so
        #     router-dispatched trades are visible to signal_log readers
        #     (the scale-out's log_partial / log_close key off
        #     EPIC_STATE.signal_log_id). Replicates the canonical pattern at
        #     autobot.py:3909-3936. Regime fields ride in via decision.debug
        #     (stamped pre-execute_trade); signal_logger.log_open already
        #     reads regime_instance_id / regime / regime_confidence_final /
        #     router_direction into the open record.
        try:
            import uuid as _uuid
            _sl_id = str(_uuid.uuid4())
            _briefing = None
            try:
                import morning_briefing as _mb
                _briefing = _mb.get_briefing(sym_u)
            except Exception:
                _briefing = None
            _entry_price = None
            try:
                if isinstance(res, dict):
                    _entry_price = res.get("entry_price")
                if _entry_price is None:
                    _entry_price = getattr(decision, "entry", None)
                _entry_price = float(_entry_price) if _entry_price is not None else None
            except Exception:
                _entry_price = None
            if _entry_price is not None:
                import signal_logger as _slogger
                _slogger.log_open(
                    trade_id=_sl_id,
                    epic=epic,
                    decision=decision,
                    briefing=_briefing or {},
                    df_5m=df_5m,
                    entry_price=_entry_price,
                    deal_id=_deal_id,
                )
                _es = EPIC_STATE.get(_pk) if _pk else None
                if isinstance(_es, dict):
                    _es["signal_log_id"] = _sl_id
            else:
                logger.warning(
                    "[ROUTER] %s log_open skipped — no entry_price recoverable "
                    "(res=%s decision.entry=%s)",
                    sym_u, type(res).__name__, getattr(decision, "entry", None),
                )
        except Exception as _sl_exc:
            logger.warning(
                "[ROUTER] %s signal_logger.log_open failed (swallowed): %s",
                sym_u, _sl_exc,
            )

        logger.info(
            "[ROUTER] %s regime=%s → dispatch %s %s → FILLED dealId=%s "
            "regime_instance_id=%s conf=%s",
            sym_u, regime, strategy, router_direction, _deal_id, inst_id,
            f"{float(conf):.4f}" if conf is not None else "N/A",
        )

    except Exception as exc:
        logger.warning(
            "[ROUTER] %s dispatch raised (swallowed): %s", sym_u, exc,
            exc_info=True,
        )
