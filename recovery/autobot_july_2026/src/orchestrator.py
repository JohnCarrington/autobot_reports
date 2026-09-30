#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
orchestrator.py — Sentinel × AutoBot Integration Layer
=======================================================

Sits between the tick feed and both trading systems.
AutoBot provides deterministic rule-based signals.
Sentinel provides regime intelligence, confidence scoring,
and adaptive position sizing.

Neither system is replaced. The orchestrator combines them:

    Tick
     │
     ├─→ AutoBot  (strategy_logic.evaluate_signals)   → deterministic signal
     ├─→ Sentinel (AiBrain.evaluate)                  → confidence + regime
     │
     └─→ Orchestrator decides:
             • Should this trade be taken?   (veto logic)
             • At what size?                 (size_mult)
             • With what SL/TP?              (regime-adjusted distances)
             • Feed outcome back to Sentinel (meta-learning loop)

Environment variables (all optional — sensible defaults provided):
    CONFIDENCE_THRESHOLD   float   Minimum Sentinel confidence to allow a trade  (default 0.52)
    BASE_TRADE_SIZE        float   AutoBot base position size                     (default 1.0)
    MAX_SIZE_MULT          float   Cap on Sentinel's size multiplier              (default 2.0)
    TRADE_ENABLED          bool    Master kill-switch                             (default true)
    OPEN_COOLDOWN_SECONDS  int     Minimum seconds between trades per symbol      (default 30)

Logging:
    All decisions (including vetoed trades) are logged at INFO level so you
    can review the veto rate and tune CONFIDENCE_THRESHOLD accordingly.
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import numpy as np

# ── AutoBot rules engine ──────────────────────────────────────────────
from strategy_logic import evaluate_signals, StrategyDecision

# ── Sentinel AI layer ─────────────────────────────────────────────────
from ai_brain import AiBrain, ai_brain_feedback

# ── Execution & state ─────────────────────────────────────────────────
from trade_manager import TradeManager, execute_trade
from ab_engine import record_trade
from experience_buffer import push_experience
from rollback_manager import monitor as rollback_monitor

# ── Optional Telegram alerts ──────────────────────────────────────────
try:
    from telegram_alerts import send_trade_open_alert, send_trade_close_alert
except ImportError:
    def send_trade_open_alert(*a, **kw): pass
    def send_trade_close_alert(*a, **kw): pass

logger = logging.getLogger("Orchestrator")

# =====================================================================
# CONFIGURATION
# =====================================================================

# Minimum Sentinel confidence required to allow an AutoBot signal through.
# Start conservative — you can lower it as you build trust in Sentinel.
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.52"))

# Master kill-switch
TRADE_ENABLED = os.getenv("TRADE_ENABLED", "true").lower() in ("true", "1", "yes")

# Base position size (AutoBot default)
BASE_TRADE_SIZE = float(os.getenv("BASE_TRADE_SIZE", "1.0"))

# Cap on Sentinel's size multiplier — prevents runaway sizing
MAX_SIZE_MULT = float(os.getenv("MAX_SIZE_MULT", "2.0"))

# Minimum seconds between opening trades on the same symbol
OPEN_COOLDOWN = int(os.getenv("OPEN_COOLDOWN_SECONDS", "30"))

# Pip value (points per pip) — symbol-aware
_PIP_SIZES: dict = {"USDJPY": 1.0, "GBPJPY": 1.0}
_PIP_DEFAULT: float = 0.0001


def _pip(symbol: str) -> float:
    return _PIP_SIZES.get(str(symbol).upper(), _PIP_DEFAULT)

# Regime-adjusted SL/TP distances (pips). AutoBot uses fixed values;
# Sentinel tunes them per regime based on current volatility conditions.
REGIME_DISTANCES = {
    #              SL pips  TP pips  trail pips
    "TREND":    (  40,      80,      15  ),
    "RANGE":    (  25,      40,      10  ),
    "CALM":     (  20,      35,       8  ),
    "VOLATILE": (  50,      80,      20  ),   # rarely trades but safe if it does
    "UNKNOWN":  (  30,      50,      10  ),   # fallback
}

# Decision log file — written alongside sentinel.log for post-trade analysis
DECISION_LOG = Path(os.getenv("DECISION_LOG_PATH", "/opt/tradingbot/decision_log.jsonl"))

# =====================================================================
# INTERNAL STATE
# =====================================================================

# Per-symbol cooldown tracker (persisted to disk to survive restarts)
_LAST_OPEN: dict = {}
_COOLDOWN_FILE = Path("/opt/tradingbot/cache/cooldown_state.json")


def _load_cooldown_state() -> None:
    """Restore unexpired cooldowns from disk on startup."""
    global _LAST_OPEN
    try:
        if not _COOLDOWN_FILE.exists():
            return
        data = json.loads(_COOLDOWN_FILE.read_text())
        now = datetime.now(timezone.utc)
        for sym, iso_ts in data.items():
            try:
                ts = datetime.fromisoformat(iso_ts)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if (now - ts).total_seconds() < OPEN_COOLDOWN:
                    _LAST_OPEN[sym] = ts
            except Exception:
                continue
        if _LAST_OPEN:
            logger.info(
                f"[cooldown] Restored {len(_LAST_OPEN)} active cooldown(s) from disk: "
                f"{list(_LAST_OPEN.keys())}"
            )
    except Exception as exc:
        logger.warning(f"[cooldown] Failed to load cooldown state: {exc}")


def _save_cooldown_state() -> None:
    """Persist current cooldowns to disk."""
    try:
        data = {sym: ts.isoformat() for sym, ts in _LAST_OPEN.items()}
        _COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COOLDOWN_FILE.write_text(json.dumps(data))
    except Exception as exc:
        logger.warning(f"[cooldown] Failed to save cooldown state: {exc}")


# Load cooldowns on module import
_load_cooldown_state()

# Per-symbol trade managers (injected or auto-created)
_MANAGERS: dict = {}

# Single AiBrain instance shared across all symbols
_brain = AiBrain()

# Track which A/B model slot each symbol is using (round-robin A/B)
_AB_SLOT: dict = {}


# =====================================================================
# DECISION RECORD
# =====================================================================

@dataclass
class OrchestratorDecision:
    """
    Full record of every tick evaluation — both allowed trades and vetoes.
    Written to decision_log.jsonl so you can analyse veto rate and tune
    CONFIDENCE_THRESHOLD post-hoc.
    """
    timestamp:          str
    symbol:             str
    mid:                float

    # AutoBot output
    ab_signal:          str
    ab_regime:          str
    ab_mode:            str
    ab_entry:           Optional[float]
    ab_sl:              Optional[float]
    ab_tp:              Optional[float]
    ab_reason:          str

    # Sentinel output
    sentinel_signal:    str
    sentinel_confidence: float
    sentinel_size_mult: float
    sentinel_regime_now:    str
    sentinel_regime_future: str

    # Orchestrator decision
    action:             str          # TRADE / VETO / COOLDOWN / DISABLED / NO_SIGNAL
    veto_reason:        str
    final_size:         float
    final_sl:           Optional[float]
    final_tp:           Optional[float]
    final_sl_pips:      Optional[int]
    final_tp_pips:      Optional[int]

    # Outcome (filled in after close)
    deal_id:            Optional[str] = None
    realised_pnl:       Optional[float] = None
    close_reason:       Optional[str] = None


# =====================================================================
# HELPERS
# =====================================================================

def _get_manager(epic: str) -> TradeManager:
    if epic not in _MANAGERS:
        _MANAGERS[epic] = TradeManager()
    return _MANAGERS[epic]


def _on_cooldown(symbol: str, now: datetime) -> bool:
    last = _LAST_OPEN.get(symbol)
    if not last:
        return False
    return (now - last).total_seconds() < OPEN_COOLDOWN


NEWS_BLACKOUT_PRE_MINUTES = int(os.getenv("NEWS_BLACKOUT_PRE_MINUTES", "5"))
NEWS_BLACKOUT_POST_MINUTES = int(os.getenv("NEWS_BLACKOUT_POST_MINUTES", "5"))


def _check_news_blackout(symbol: str, now: datetime):
    """
    Check live news calendar for HIGH impact events affecting this symbol's
    currencies.  Returns (True, reason) if blocked, (False, "") otherwise.
    """
    try:
        import news_calendar
    except ImportError:
        return False, ""

    # Extract currencies from symbol (e.g. "GBPUSD" → ["GBP", "USD"])
    sym = str(symbol).upper().replace("/", "").replace("_", "")
    currencies = []
    if len(sym) >= 6:
        currencies = [sym[:3], sym[3:6]]
    if not currencies:
        return False, ""

    events = news_calendar.get_todays_events(currencies)
    if not events:
        return False, ""

    now_minutes = now.hour * 60 + now.minute + now.second / 60.0
    for ev in events:
        try:
            h, m = map(int, str(ev.get("time", "")).split(":"))
        except (ValueError, AttributeError):
            continue
        event_minutes = h * 60 + m
        if (event_minutes - NEWS_BLACKOUT_PRE_MINUTES) <= now_minutes <= (event_minutes + NEWS_BLACKOUT_POST_MINUTES):
            reason = (
                f"News blackout: {ev.get('currency','')} {ev.get('event_name','?')} "
                f"at {ev.get('time','')} UTC (±{NEWS_BLACKOUT_PRE_MINUTES}/{NEWS_BLACKOUT_POST_MINUTES}min)"
            )
            return True, reason

    return False, ""


def _regime_sl_tp(regime: str, direction: str, mid: float, symbol: str = ""):
    """
    Returns (sl, tp, sl_pips, tp_pips) adjusted for the current regime.
    Wider in volatile/trend conditions, tighter in calm/range.
    """
    sl_pips, tp_pips, _ = REGIME_DISTANCES.get(regime, REGIME_DISTANCES["UNKNOWN"])
    pip = _pip(symbol)
    sl_dist = sl_pips * pip
    tp_dist = tp_pips * pip

    if direction == "BUY":
        return mid - sl_dist, mid + tp_dist, sl_pips, tp_pips
    else:
        return mid + sl_dist, mid - tp_dist, sl_pips, tp_pips


def _clamp_size(raw_mult: float) -> float:
    """Clamp size multiplier to [0.25, MAX_SIZE_MULT]."""
    return round(max(0.25, min(MAX_SIZE_MULT, raw_mult)), 2)


def _log_decision(decision: OrchestratorDecision):
    """Append decision record to JSONL log for post-trade analysis."""
    try:
        DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DECISION_LOG.open("a") as f:
            f.write(json.dumps(decision.__dict__) + "\n")
    except Exception as e:
        logger.debug(f"Decision log write failed: {e}")


def _ab_slot(symbol: str) -> str:
    """Round-robin A/B slot assignment per symbol."""
    if symbol not in _AB_SLOT:
        _AB_SLOT[symbol] = "A" if len(_AB_SLOT) % 2 == 0 else "B"
    return _AB_SLOT[symbol]


# =====================================================================
# CORE ORCHESTRATION FUNCTION
# =====================================================================

def on_tick(symbol: str,
            df1:  pd.DataFrame,
            df5:  pd.DataFrame,
            df1h: pd.DataFrame,
            mid:  float,
            epic: str,
            bid:  float = 0.0,
            ask:  float = 0.0,
            htf_snapshot: Optional[dict] = None) -> Optional[OrchestratorDecision]:
    """
    Called on every tick for a symbol. Runs both AutoBot and Sentinel,
    combines their outputs, and executes if conditions are met.

    Args:
        symbol : e.g. "EURUSD"
        df1    : 1-minute candle DataFrame
        df5    : 5-minute candle DataFrame
        df1h   : 1-hour candle DataFrame
        mid    : current mid price
        epic   : IG epic string for order placement

    Returns:
        OrchestratorDecision — the full decision record for this tick,
        or None if data was insufficient to evaluate.
    """
    now = datetime.now(timezone.utc)
    manager = _get_manager(epic)
    has_active = epic in manager.active_trades

    # Include pending-open orders in the duplicate-trade gate so the race
    # window between signal submission and IG confirmation cannot spawn a
    # second order for the same epic.
    has_pending = False
    try:
        from trade_executor import TRADE_STATE_BY_EPIC as _TSBE
        _pending_st = _TSBE.get(epic)
        if isinstance(_pending_st, dict) and _pending_st.get("pending_open"):
            has_pending = True
    except Exception:
        pass

    # ── Tick-level position monitoring (trailing stops, partial exits) ──
    if has_active:
        manager.monitor_positions(epic, mid)
        # Check if monitor_positions just closed the trade
        if epic not in manager.active_trades:
            _on_trade_closed(symbol, epic, mid, "monitor")
        return None

    if has_pending:
        return None

    # ── Minimum data guard ────────────────────────────────────────────
    if df5 is None or len(df5) < 30:
        return None

    # =================================================================
    # 1. AutoBot — deterministic rules engine
    # =================================================================
    ab: StrategyDecision = evaluate_signals(
        symbol=symbol,
        epic=epic,
        bid=bid,
        ask=ask,
        htf_snapshot=htf_snapshot,
        df=df5,
    )

    # =================================================================
    # 2. Sentinel — AI confidence + regime layer
    # =================================================================
    sentinel = _brain.evaluate(
        symbol=symbol,
        df1=df1,
        df5=df5,
        df1h=df1h,
        mid=mid,
        has_open_position=has_active,
    )

    # =================================================================
    # 3. Build the base decision record
    # =================================================================
    rec = OrchestratorDecision(
        timestamp            = now.isoformat(),
        symbol               = symbol,
        mid                  = mid,
        ab_signal            = ab.signal,
        ab_regime            = ab.regime,
        ab_mode              = ab.mode,
        ab_entry             = ab.entry,
        ab_sl                = ab.sl,
        ab_tp                = ab.tp,
        ab_reason            = ab.reason,
        sentinel_signal      = sentinel.signal,
        sentinel_confidence  = sentinel.confidence,
        sentinel_size_mult   = sentinel.size_mult,
        sentinel_regime_now  = sentinel.regime_now,
        sentinel_regime_future = sentinel.regime_future,
        action               = "NO_SIGNAL",
        veto_reason          = "",
        final_size           = BASE_TRADE_SIZE,
        final_sl             = None,
        final_tp             = None,
        final_sl_pips        = None,
        final_tp_pips        = None,
    )

    # =================================================================
    # 4. Gate 1 — AutoBot must have a signal
    # =================================================================
    if ab.signal == "NONE":
        _log_decision(rec)
        return rec

    # =================================================================
    # 5. Gate 2 — Regime agreement check
    #
    # AutoBot's strategies are regime-specific. If Sentinel's regime
    # reading contradicts what AutoBot assumed, suppress the trade.
    #
    # Mapping of AutoBot modes to compatible Sentinel regimes:
    #   RANGE mode    → Sentinel should agree it's RANGE or CALM
    #   TREND mode    → Sentinel should agree it's TREND
    #   BREAKOUT mode → Sentinel should agree it's CALM or TREND
    # =================================================================
    regime = sentinel.regime_now
    compatible = _regime_compatible(ab.mode, regime)

    if not compatible:
        rec.action = "VETO"
        rec.veto_reason = (
            f"Regime mismatch: AutoBot mode={ab.mode} "
            f"vs Sentinel regime={regime}"
        )
        logger.info(
            f"[{symbol}] VETO — {rec.veto_reason} "
            f"(conf={sentinel.confidence:.3f})"
        )
        _log_decision(rec)
        return rec

    # =================================================================
    # 6. Gate 3 — Sentinel confidence threshold
    # =================================================================
    if sentinel.confidence < CONFIDENCE_THRESHOLD:
        rec.action = "VETO"
        rec.veto_reason = (
            f"Low confidence: {sentinel.confidence:.3f} < "
            f"threshold {CONFIDENCE_THRESHOLD:.3f}"
        )
        logger.info(f"[{symbol}] VETO — {rec.veto_reason}")
        _log_decision(rec)
        return rec

    # =================================================================
    # 7. Gate 4 — Signal direction agreement
    #
    # Both systems must agree on direction. If AutoBot says BUY but
    # Sentinel says SELL, something is ambiguous — skip the trade.
    # If Sentinel says NONE but confidence is above threshold, we
    # defer to AutoBot (Sentinel is abstaining, not contradicting).
    # =================================================================
    if sentinel.signal != "NONE" and sentinel.signal != ab.signal:
        rec.action = "VETO"
        rec.veto_reason = (
            f"Direction conflict: AutoBot={ab.signal} "
            f"vs Sentinel={sentinel.signal}"
        )
        logger.info(f"[{symbol}] VETO — {rec.veto_reason}")
        _log_decision(rec)
        return rec

    # =================================================================
    # 8. Gate 5 — Cooldown and kill-switch
    # =================================================================
    if not TRADE_ENABLED:
        rec.action = "DISABLED"
        rec.veto_reason = "TRADE_ENABLED=false"
        _log_decision(rec)
        return rec

    if _on_cooldown(symbol, now):
        rec.action = "COOLDOWN"
        rec.veto_reason = f"Cooldown active ({OPEN_COOLDOWN}s)"
        _log_decision(rec)
        return rec

    # =================================================================
    # 8b. Gate 6 — News calendar blackout (HIGH impact events ±5 min)
    # =================================================================
    try:
        blocked, news_reason = _check_news_blackout(symbol, now)
        if blocked:
            rec.action = "VETO"
            rec.veto_reason = news_reason
            logger.info(f"[{symbol}] VETO — {news_reason}")
            _log_decision(rec)
            return rec
    except Exception as _news_exc:
        logger.debug(f"[{symbol}] News blackout check error: {_news_exc}")

    # =================================================================
    # 9. All gates passed — compute final order parameters
    # =================================================================

    direction = ab.signal

    # Regime-adjusted SL/TP (overrides AutoBot's fixed pip distances)
    sl, tp, sl_pips, tp_pips = _regime_sl_tp(regime, direction, mid, symbol)

    # Sentinel-scaled position size
    raw_mult   = sentinel.size_mult
    final_size = round(BASE_TRADE_SIZE * _clamp_size(raw_mult), 2)

    rec.action       = "TRADE"
    rec.final_size   = final_size
    rec.final_sl     = sl
    rec.final_tp     = tp
    rec.final_sl_pips = sl_pips
    rec.final_tp_pips = tp_pips

    logger.info(
        f"[{symbol}] TRADE — {direction} @ {mid:.5f} | "
        f"SL={sl:.5f} ({sl_pips}pip) TP={tp:.5f} ({tp_pips}pip) | "
        f"size={final_size} (mult={raw_mult:.2f}) | "
        f"conf={sentinel.confidence:.3f} regime={regime} | "
        f"ab_mode={ab.mode} ab_reason={ab.reason}"
    )

    # =================================================================
    # 10. Execute
    # =================================================================
    try:
        # Patch the AutoBot decision with regime-adjusted values so
        # execute_trade uses the orchestrator's SL/TP (in pips) and entry.
        # Use correct bid/ask price: BUY fills at ask, SELL fills at bid.
        # Fall back to mid only if bid/ask are unavailable.
        if direction == "BUY" and ask > 0:
            ab.entry = ask
        elif direction == "SELL" and bid > 0:
            ab.entry = bid
        else:
            ab.entry = mid
        ab.sl    = sl_pips
        ab.tp    = tp_pips
        ab.size  = final_size

        # execute_trade handles open_sb_now, deal confirmation, state
        # recording (TRADE_STATE_BY_EPIC), and send_trade_open_alert.
        result = execute_trade(ab, epic)

        deal_id = None
        if result and isinstance(result, dict):
            deal_id = result.get("dealId") or result.get("dealReference")

        _LAST_OPEN[symbol] = now
        _save_cooldown_state()
        rec.deal_id = deal_id

        # Record to A/B engine (provisional — updated on close)
        record_trade(_ab_slot(symbol), 0.0)

    except Exception as e:
        logger.error(f"[{symbol}] Execution error: {e}")
        rec.action = "VETO"
        rec.veto_reason = f"Execution error: {e}"

    _log_decision(rec)
    return rec


# =====================================================================
# TRADE CLOSE FEEDBACK
# =====================================================================

def on_trade_closed(symbol: str,
                    epic: str,
                    exit_mid: float,
                    entry_mid: float,
                    direction: str,
                    size: float,
                    reason: str = "unknown"):
    """
    Call this when a trade closes (from TradeManager.monitor_positions,
    TP hit, SL hit, or manual close).

    Feeds the realised P&L back into:
        • Sentinel meta-learning loop
        • A/B engine result tracking
        • Experience buffer for NMC training
    """
    pip_pnl = (
        (exit_mid - entry_mid) / _pip(symbol) if direction == "BUY"
        else (entry_mid - exit_mid) / _pip(symbol)
    )
    currency_pnl = pip_pnl * size

    logger.info(
        f"[{symbol}] CLOSED — {direction} exit={exit_mid:.5f} "
        f"pnl={pip_pnl:+.1f}pip ({currency_pnl:+.2f}) reason={reason}"
    )

    # 1. Feed back into Sentinel's meta-learning
    try:
        ai_brain_feedback(action=direction, realised_pnl=currency_pnl)
    except Exception as e:
        logger.debug(f"ai_brain_feedback error: {e}")

    # 2. Update A/B engine with real P&L
    try:
        record_trade(_ab_slot(symbol), currency_pnl)
    except Exception as e:
        logger.debug(f"record_trade error: {e}")

    # 3. Push to experience buffer for future NMC training
    try:
        action_idx = 0 if direction == "BUY" else 1
        push_experience(
            features=np.zeros(64),   # placeholder — real features stored by ai_brain
            action=action_idx,
            reward=currency_pnl,
        )
    except Exception as e:
        logger.debug(f"push_experience error: {e}")

    send_trade_close_alert(
        epic,
        direction,
        size=size,
        level=exit_mid,
        reason=reason,
    )


def _on_trade_closed(symbol: str, epic: str, mid: float, reason: str):
    """Internal hook called when monitor_positions closes a trade."""
    manager = _get_manager(epic)
    # Position has already been cleared by monitor_positions
    # Retrieve entry from the last log entry if available
    on_trade_closed(
        symbol=symbol,
        epic=epic,
        exit_mid=mid,
        entry_mid=mid,      # best effort — TradeManager already logged the real entry
        direction="BUY",    # direction was already handled internally
        size=BASE_TRADE_SIZE,
        reason=reason,
    )


# =====================================================================
# REGIME COMPATIBILITY MATRIX
# =====================================================================

def _regime_compatible(ab_mode: str, sentinel_regime: str) -> bool:
    """
    Returns True if AutoBot's strategy mode is compatible with
    the regime Sentinel has detected.

    Conservative by design — when in doubt, veto.
    """
    COMPAT = {
        "LIQUIDITY_SWEEP":  {"CALM", "RANGE", "UNKNOWN"},
        "BRIEFING_LIQUIDITY": {"CALM", "RANGE", "UNKNOWN"},
        "DISPATCH":         {"TREND", "RANGE", "CALM", "UNKNOWN"},
        "-":                {"TREND", "RANGE", "CALM"},  # unknown mode — allow non-volatile
    }
    allowed = COMPAT.get(ab_mode, set())

    # Always block VOLATILE regardless of mode
    if sentinel_regime == "VOLATILE":
        return False

    if sentinel_regime == "UNKNOWN":
        logger.debug(
            f"[regime_compat] Sentinel regime=UNKNOWN — applying UNKNOWN rules for mode={ab_mode}"
        )

    return sentinel_regime in allowed


# =====================================================================
# SAFETY MONITOR
# =====================================================================

def run_safety_checks():
    """
    Periodic safety checks — call this from your main loop every 60s.
    Runs genome rollback monitor and A/B evaluation.
    """
    try:
        ok, msg = rollback_monitor()
        if not ok:
            logger.warning(f"[Safety] Rollback triggered: {msg}")
        else:
            logger.debug(f"[Safety] Rollback monitor: {msg}")
    except Exception as e:
        logger.debug(f"[Safety] rollback_monitor error: {e}")


# =====================================================================
# VETO ANALYTICS  (call periodically to tune CONFIDENCE_THRESHOLD)
# =====================================================================

def veto_analytics(last_n: int = 500) -> dict:
    """
    Reads the last N entries from decision_log.jsonl and returns
    a summary to help tune CONFIDENCE_THRESHOLD.

    Returns dict with:
        total, trades, vetoes, veto_rate,
        veto_breakdown (reason → count),
        avg_confidence_vetoed, avg_confidence_traded
    """
    if not DECISION_LOG.exists():
        return {"error": "No decision log found"}

    entries = []
    try:
        with DECISION_LOG.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
    except Exception as e:
        return {"error": str(e)}

    entries = entries[-last_n:]
    total   = len(entries)
    trades  = [e for e in entries if e.get("action") == "TRADE"]
    vetoes  = [e for e in entries if e.get("action") == "VETO"]

    veto_breakdown: dict = {}
    for v in vetoes:
        reason = v.get("veto_reason", "unknown")
        # Bucket by reason type for readability
        if "Regime mismatch" in reason:
            key = "regime_mismatch"
        elif "Low confidence" in reason:
            key = "low_confidence"
        elif "Direction conflict" in reason:
            key = "direction_conflict"
        else:
            key = "other"
        veto_breakdown[key] = veto_breakdown.get(key, 0) + 1

    conf_vetoed  = [v.get("sentinel_confidence", 0) for v in vetoes  if v.get("ab_signal") != "NONE"]
    conf_traded  = [t.get("sentinel_confidence", 0) for t in trades]

    return {
        "total":                total,
        "trades":               len(trades),
        "vetoes":               len(vetoes),
        "veto_rate":            round(len(vetoes) / max(1, len(vetoes) + len(trades)), 3),
        "veto_breakdown":       veto_breakdown,
        "avg_confidence_vetoed": round(sum(conf_vetoed) / max(1, len(conf_vetoed)), 3),
        "avg_confidence_traded": round(sum(conf_traded) / max(1, len(conf_traded)), 3),
        "current_threshold":    CONFIDENCE_THRESHOLD,
    }
