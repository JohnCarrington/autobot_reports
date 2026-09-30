"""pia_first_executor — fires the daily PIA_FIRST briefing as a market trade.

Standalone executor (not the v5_pia executor — schema mismatch). Reads today's
briefing for a pair from /opt/tradingbot/briefings/pia_first/<DATE>/<PAIR>.json,
and on the first tick after the briefing exists fires a MARKET order with the
broker-side SL/TP set at briefing.stop / briefing.target prices.

Mode tags:
  - BRIEFING_PIA_FIRST_L  (LONG → BUY)
  - BRIEFING_PIA_FIRST_S  (SHORT → SELL)

Both share the "BRIEFING_PIA_FIRST" prefix so the EOD-close machinery in
autobot._is_briefing_exec_mode picks them up automatically once that
predicate is extended.

No mid-trade management. The position rides to one of: broker SL, broker TP,
or 21:00 UTC EOD close. Behaviour-consistent with v5_pia's design.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────────────────────────────────────

PIA_FIRST_ENABLED = (os.getenv("PIA_FIRST_ENABLED", "0") or "0").strip() == "1"

MIN_CONFIDENCE_PIA_FIRST = int(
    float(os.getenv("MIN_CONFIDENCE_PIA_FIRST", "60") or 60)
)

PIA_FIRST_STATE_FILE = Path(
    os.getenv("PIA_FIRST_STATE_FILE", "/opt/tradingbot/cache/pia_first_state.json")
)

_BRIEFINGS_BASE = Path("/opt/tradingbot/briefings/pia_first")

# Mode tag prefix — the EOD-close matcher (autobot._is_briefing_exec_mode)
# checks for this prefix. Kept as a module constant so tests can assert it.
MODE_TAG_PREFIX = "BRIEFING_PIA_FIRST"


# ─────────────────────────────────────────────────────────────────────────────
# State (fired-today dedup) — persisted to disk so a mid-day restart cannot
# double-fire the same briefing.
# ─────────────────────────────────────────────────────────────────────────────

_STATE_LOCK = threading.Lock()


def _load_state() -> Dict[str, Any]:
    """Read the dedup state from disk. Missing/malformed file → empty dict."""
    if not PIA_FIRST_STATE_FILE.exists():
        return {}
    try:
        with PIA_FIRST_STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[pia_first_exec] state read failed: %s — starting fresh", exc)
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    """Atomic write via .tmp + replace. Inherits writer ownership (autobot
    user when called from the live loop)."""
    try:
        PIA_FIRST_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PIA_FIRST_STATE_FILE.with_suffix(PIA_FIRST_STATE_FILE.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f, sort_keys=True)
        os.replace(str(tmp), str(PIA_FIRST_STATE_FILE))
    except OSError as exc:
        logger.warning("[pia_first_exec] state write failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Briefing loader
# ─────────────────────────────────────────────────────────────────────────────

def _today_str(now_utc: Optional[datetime] = None) -> str:
    when = now_utc or datetime.now(tz=timezone.utc)
    return when.strftime("%Y-%m-%d")


def _briefing_path(pair: str, date_str: str) -> Path:
    return _BRIEFINGS_BASE / date_str / f"{pair.upper()}.json"


def _load_briefing(pair: str, date_str: str) -> Optional[Dict[str, Any]]:
    """Read today's briefing for `pair`. Returns None when the file does not
    exist or fails to parse — the executor abstains silently in either case
    (the producer would have logged + alerted on its end)."""
    path = _briefing_path(pair, date_str)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[pia_first_exec] %s briefing unreadable: %s", pair, exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Fire gate
# ─────────────────────────────────────────────────────────────────────────────

def _should_fire(
    briefing: Dict[str, Any],
) -> tuple[bool, Optional[str]]:
    """Apply the gate sequence. Returns (ok, abstain_reason_or_None)."""
    direction = str(briefing.get("direction") or "").upper()
    if direction not in ("LONG", "SHORT"):
        return False, f"bad_direction={direction!r}"

    try:
        confidence = int(briefing.get("confidence"))
    except (TypeError, ValueError):
        return False, "confidence_not_int"

    if confidence < MIN_CONFIDENCE_PIA_FIRST:
        return False, f"low_conf {confidence}<{MIN_CONFIDENCE_PIA_FIRST}"

    return True, None


def _mode_tag(direction: str) -> str:
    """Map LONG → BRIEFING_PIA_FIRST_L, SHORT → BRIEFING_PIA_FIRST_S."""
    return f"{MODE_TAG_PREFIX}_L" if direction.upper() == "LONG" else f"{MODE_TAG_PREFIX}_S"


def _signal_from_direction(direction: str) -> str:
    return "BUY" if direction.upper() == "LONG" else "SELL"


# ─────────────────────────────────────────────────────────────────────────────
# Decision builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_decision(
    *,
    pair: str,
    briefing: Dict[str, Any],
    mid_price: float,
    pip_size: float,
):
    """Construct a StrategyDecision with SL/TP expressed as pip distances
    from the current market price. Mirrors briefing.v5_pia.executor._build_decision
    so signal_logger and trade_executor see a familiar shape."""
    from strategy_logic import StrategyDecision

    direction = str(briefing["direction"]).upper()
    entry = float(briefing["entry"])
    stop = float(briefing["stop"])
    target = float(briefing["target"])
    signal = _signal_from_direction(direction)

    if signal == "BUY":
        sl_pips = (mid_price - stop) / pip_size
        tp_pips = (target - mid_price) / pip_size
    else:  # SELL
        sl_pips = (stop - mid_price) / pip_size
        tp_pips = (mid_price - target) / pip_size

    sl_pips = max(0.0, float(sl_pips))
    tp_pips = max(0.0, float(tp_pips))

    debug: Dict[str, Any] = {
        "pip_size":                 pip_size,
        "pia_first_pair":           pair,
        "pia_first_date":           briefing.get("date"),
        "pia_first_session":        briefing.get("session"),
        "pia_first_generated_at":   briefing.get("generated_at_utc"),
        "pia_first_valid_until":    briefing.get("valid_until_utc"),
        "pia_first_confidence":     briefing.get("confidence"),
        "pia_first_briefing_entry": entry,
        "pia_first_briefing_stop":  stop,
        "pia_first_briefing_target": target,
        "pia_first_rr":             briefing.get("rr"),
    }

    return StrategyDecision(
        symbol=pair.upper(),
        regime="BRIEFING_PIA_FIRST",
        signal=signal,
        mode=_mode_tag(direction),
        entry=mid_price,
        sl=sl_pips,
        tp=tp_pips,
        use_trailing_stop=False,
        reason=(
            f"PIA_FIRST {direction} mid={mid_price:g} entry={entry:g} "
            f"conf={briefing.get('confidence')}% rr={briefing.get('rr')}"
        ),
        debug=debug,
        pip_size=pip_size,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Per-tick entry point
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_tick(
    pair: str,
    epic: str,
    mid_price: float,
    pip_size: float,
    now_utc: Optional[datetime] = None,
    df_5m: Any = None,
):
    """Per-tick gate. Returns a StrategyDecision on fire, else None.

    Gate order:
      1. PIA_FIRST_ENABLED off → silent
      2. No briefing file for today → debug log
      3. confidence < MIN_CONFIDENCE_PIA_FIRST → info log (once)
      4. Already fired today for this pair → debug log
      5. Direction unknown → warn
      → fire (MARKET order — the briefing entry field is informational)
    """
    if not PIA_FIRST_ENABLED:
        return None

    pair_u = pair.upper()
    when = now_utc or datetime.now(tz=timezone.utc)
    date_str = _today_str(when)

    briefing = _load_briefing(pair_u, date_str)
    if briefing is None:
        logger.debug("[pia_first_exec] %s no briefing for %s", pair_u, date_str)
        return None

    ok, reason = _should_fire(briefing)
    if not ok:
        logger.info("[pia_first_exec] %s abstain: %s", pair_u, reason)
        return None

    # Dedup: once per (pair, date)
    with _STATE_LOCK:
        state = _load_state()
        fired_today = state.get(pair_u)
        if fired_today == date_str:
            logger.debug("[pia_first_exec] %s already fired today", pair_u)
            return None

    decision = _build_decision(
        pair=pair_u,
        briefing=briefing,
        mid_price=float(mid_price),
        pip_size=float(pip_size or 1.0),
    )

    # Mark fired BEFORE returning so a concurrent re-tick can't double-fire.
    with _STATE_LOCK:
        state = _load_state()
        state[pair_u] = date_str
        _save_state(state)

    logger.info(
        "[pia_first_exec] %s FIRE %s mode=%s mid=%.5f stop=%s target=%s "
        "sl_pips=%.1f tp_pips=%.1f conf=%s",
        pair_u, decision.signal, decision.mode, mid_price,
        briefing.get("stop"), briefing.get("target"),
        decision.sl, decision.tp, briefing.get("confidence"),
    )

    # Forensic capture — soft-fail. The forensic_logger writer is mode-tag
    # agnostic per prior audit; using the same mode tag keeps signal_log
    # joinable to forensic_fires.jsonl.
    try:
        from forensic_logger import capture_fire_from_df
        capture_fire_from_df(
            sym=pair_u,
            strategy=decision.mode,
            direction=decision.signal,
            entry_price=float(mid_price),
            df_5m=df_5m,
            pip_size=float(pip_size or 1.0),
            fire_path=f"pia_first/{date_str}",
        )
    except Exception as exc:
        logger.warning(
            "[pia_first_exec] %s forensic capture failed: %s: %s",
            pair_u, type(exc).__name__, exc,
        )

    return decision


# ─────────────────────────────────────────────────────────────────────────────
# Bulk pending-briefing scan — utility for catch-up runs / cron tests
# ─────────────────────────────────────────────────────────────────────────────

def process_pending_briefings(now_utc: Optional[datetime] = None) -> int:
    """List today's briefing files, log which would fire vs skip. Returns the
    fire-eligible count. Does NOT place orders — actual fires only happen via
    evaluate_tick in the live tick loop. Useful for cron-mode smoke tests.
    """
    if not PIA_FIRST_ENABLED:
        return 0
    when = now_utc or datetime.now(tz=timezone.utc)
    date_str = _today_str(when)
    day_dir = _BRIEFINGS_BASE / date_str
    if not day_dir.exists():
        return 0
    count = 0
    for path in sorted(day_dir.glob("*.json")):
        if path.name.endswith("_INVALID.json"):
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                briefing = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        ok, reason = _should_fire(briefing)
        pair = briefing.get("pair") or path.stem
        if ok:
            count += 1
            logger.info("[pia_first_exec] PENDING %s would fire", pair)
        else:
            logger.info("[pia_first_exec] PENDING %s skip: %s", pair, reason)
    return count


def register_callbacks() -> None:
    """Hook reserved for future broker-confirm wiring. Currently a no-op:
    state tracking happens inside evaluate_tick at the moment of decision,
    not on broker confirmation — which matches the v5_pia executor's
    "mark fired before returning" semantics."""
    logger.debug("[pia_first_exec] register_callbacks: no-op in v1")
