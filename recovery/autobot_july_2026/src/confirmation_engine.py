"""
confirmation_engine.py — TELEMETRY-ONLY confirmation scoring.

For every trade a strategy fires, this module computes and logs a
confirmation record. It scores how confidently the entry is "the move has
started" using three signals proven on 440 realised trades (2026-05-23
precheck):

  - macd_hist_rising      MACD(12,26,9) histogram rising in trade direction
                          at the entry bar's close. +18.9pp separation.
  - struct_break_5        Entry bar's close beyond the 5-bar swing
                          high (LONG) / low (SHORT). +12.2pp separation
                          (high-conviction, rare-TRUE — ~12% of fires).
  - next_bar_continued    The 5m bar AFTER the entry bar closes further
                          in trade direction (vs entry price). +40.5pp
                          separation — single strongest signal.

A composite score = count of {macd_hist_rising, struct_break_5,
next_bar_continued} TRUE (0-3). Per the precheck, this gives a
monotonic WR ladder 28 / 55 / 72 / 81 % across score 0..3.

⚠️ TELEMETRY-ONLY: this module GATES NOTHING. It does not call
close_position, does not amend SL/TP, does not block or delay fires,
does not modify sizing. Read + log only. Calibration data accumulates
on the new strategies' demo telemetry; only after enough data lands
should the score be promoted to a gate or sizing-modulator.

The engine writes TWO records per trade, joined by trade_id:
  Phase 1 (at fire-time): macd_hist_rising, struct_break_5/10/20,
                          macd_line_agree, macd_hist_agree, sub_score_at_entry.
  Phase 2 (next 5m close): next_bar_continued, composite_score.

The trade_id field matches signal_log's trade_id (UUID), so post-run
analysis joins confirmation → signal_log → outcome the same way
regime_engine.jsonl joins to outcomes.

Kill-switch: CONFIRMATION_ENGINE_ENABLED=0 turns the entire module into
no-ops (no compute, no log, no overhead).

Fail-safe: every hook is wrapped in try/except by the caller. The
internal functions also catch exceptions and log warnings rather than
raise. A confirmation-engine failure can NEVER affect a live trade.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("confirmation_engine")

# ─────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────
CONFIRMATION_ENGINE_ENABLED = str(
    os.getenv("CONFIRMATION_ENGINE_ENABLED", "1") or "1"
).strip().lower() in ("1", "true", "yes")

LOG_PATH = os.getenv(
    "CONFIRMATION_ENGINE_LOG_PATH",
    "/opt/tradingbot/logs/confirmation_engine.jsonl",
)

# Structural lookbacks tested in the precheck. 5-bar is the strongest;
# 10/20 logged for ongoing comparison since logging is free.
_STRUCT_LOOKBACKS = (5, 10, 20)

# ─────────────────────────────────────────────────────────────────────
# In-memory pending registry (Phase 1 → Phase 2 join)
# ─────────────────────────────────────────────────────────────────────
# trade_id → {pair, direction, entry, entry_bar_ts, phase1_ts}
# Phase 2 looks up entries here when the next 5m close arrives for the pair.
#
# ⚠️ KNOWN LIMITATION (telemetry-only, acceptable): the registry is
# in-memory only — NOT persisted to disk. A bot restart between Phase 1
# (fire) and Phase 2 (next 5m close, ~0-5 min later) drops the in-flight
# trade from _PENDING. Effect: Phase 1 record was already written to disk;
# Phase 2 record is silently never written. Downstream joiners observe
# the trade as "Phase 1 only — no composite" and can either treat as
# composite=null or exclude. Acceptable because:
#   1) the restart window is small (≤5 min between Phase 1 and Phase 2),
#   2) telemetry-only — no trade decision depends on the composite,
#   3) persisting per-trade state for a 5-min lookup is over-engineering
#      for a telemetry log.
# If a future build promotes the composite to a gate/sizing input, this
# becomes load-bearing and would need disk persistence.
_PENDING: Dict[str, Dict[str, Any]] = {}
_PENDING_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────────
# Pure signal functions
# ─────────────────────────────────────────────────────────────────────
def _macd_hist_rising_at_entry(
    closes: "pd.Series", direction: str,
    fast: int = 12, slow: int = 26, signal: int = 9,
) -> Optional[Dict[str, Any]]:
    """Compute MACD(12,26,9) on closes; return whether the LAST histogram
    value is rising in the trade direction.

    Returns dict with keys:
        macd_hist_rising  bool — hist[-1] > hist[-2] (BUY) / < (SELL)
        macd_hist_agree   bool — hist sign agrees with direction
        macd_line_agree   bool — line > signal (BUY) / < (SELL)
        hist, line, signal floats at the entry bar
    Or None on insufficient data / NaN.
    """
    if closes is None or len(closes) < (slow + signal + 5):
        return None
    try:
        # Use pandas EMA — matches indicators.macd to avoid NaN-seed bug
        # when computing signal EMA on partial MACD-line history.
        s = pd.Series([float(c) for c in closes])
        e_fast = s.ewm(span=fast, adjust=False).mean()
        e_slow = s.ewm(span=slow, adjust=False).mean()
        line = e_fast - e_slow
        sig = line.ewm(span=signal, adjust=False).mean()
        hist = line - sig
        line_v = float(line.iloc[-1])
        sig_v = float(sig.iloc[-1])
        hist_v = float(hist.iloc[-1])
        hist_prev = float(hist.iloc[-2])
    except Exception:
        return None
    if any(np.isnan(x) for x in (line_v, sig_v, hist_v, hist_prev)):
        return None

    line_above_signal = line_v > sig_v
    hist_positive = hist_v > 0
    hist_rising_signed = hist_v > hist_prev  # raw direction (not yet trade-rel)

    if str(direction).upper() == "BUY":
        macd_line_agree = line_above_signal
        macd_hist_agree = hist_positive
        macd_hist_rising = hist_rising_signed
    else:
        macd_line_agree = not line_above_signal
        macd_hist_agree = not hist_positive
        macd_hist_rising = not hist_rising_signed

    return {
        "macd_hist_rising": bool(macd_hist_rising),
        "macd_hist_agree": bool(macd_hist_agree),
        "macd_line_agree": bool(macd_line_agree),
        "hist": round(hist_v, 4),
        "line": round(line_v, 4),
        "signal": round(sig_v, 4),
    }


def _structure_break(
    df_5m: "pd.DataFrame", direction: str, lookback: int,
    entry_close: Optional[float] = None,
) -> Optional[bool]:
    """Closed beyond the N-bar swing high (BUY) / low (SELL).

    The "entry bar" is the LAST closed bar in df_5m. The lookback range
    is the N bars STRICTLY BEFORE the entry bar (exclusive of entry).
    Returns None if not enough bars.
    """
    if df_5m is None or len(df_5m) <= lookback:
        return None
    try:
        # entry bar = last row; prior N bars = rows -lookback-1 .. -1
        if entry_close is None:
            entry_close = float(df_5m["close"].iloc[-1])
        prior = df_5m.iloc[-lookback - 1 : -1]
        if len(prior) < lookback:
            return None
        if str(direction).upper() == "BUY":
            swing_high = float(prior["high"].max())
            return entry_close > swing_high
        else:
            swing_low = float(prior["low"].min())
            return entry_close < swing_low
    except Exception:
        return None


def _next_bar_continued(
    next_bar_close: float, entry_price: float, direction: str,
) -> Optional[bool]:
    """Did the 5m bar after the fire-bar close further in trade direction?"""
    try:
        if str(direction).upper() == "BUY":
            return float(next_bar_close) > float(entry_price)
        return float(next_bar_close) < float(entry_price)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────
# Telemetry writer
# ─────────────────────────────────────────────────────────────────────
_WRITE_LOCK = threading.Lock()


def _write_record(record: Dict[str, Any]) -> None:
    """Append one JSON line to LOG_PATH. Soft-fail — never raise."""
    try:
        d = os.path.dirname(LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _WRITE_LOCK:
            with open(LOG_PATH, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.warning("[confirmation_engine] write failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────
# Phase 1 — at fire time
# ─────────────────────────────────────────────────────────────────────
def record_at_entry(
    trade_id: str,
    pair: str,
    direction: str,
    entry_price: float,
    df_5m: "pd.DataFrame",
    deal_id: Optional[str] = None,
    strategy: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Compute the at-entry signals and write the Phase 1 record.

    Returns the record (for unit tests) or None on disabled / failure.
    Caller MUST wrap in try/except as a belt-and-braces fail-safe.

    df_5m: the recent 5m DataFrame (same one strategies use). LAST row
           is treated as the entry bar.
    """
    if not CONFIRMATION_ENGINE_ENABLED:
        return None
    try:
        # Compute at-entry signals
        macd_dict = None
        try:
            closes = df_5m["close"] if df_5m is not None else None
            macd_dict = _macd_hist_rising_at_entry(closes, direction)
        except Exception as macd_exc:
            logger.debug("[confirmation_engine] macd compute failed: %s", macd_exc)

        struct_results = {}
        entry_close = None
        try:
            entry_close = float(df_5m["close"].iloc[-1]) if df_5m is not None else None
        except Exception:
            pass
        for lb in _STRUCT_LOOKBACKS:
            struct_results[f"struct_break_{lb}"] = _structure_break(
                df_5m, direction, lb, entry_close=entry_close,
            )

        # Sub-score at-entry — count of TRUE among the two at-entry signals
        # we'd actually use as gates: macd_hist_rising + struct_break_5.
        # ⚠️ NULL-vs-ZERO: if EITHER signal is None (couldn't compute —
        # bad/missing df, insufficient bars, etc.), sub_score is set to
        # None and signals_computed_at_entry=false. Score 0 means
        # "evaluated, both FALSE". Score None means "couldn't evaluate."
        # Keeps the calibration dataset clean: data-failures excludable;
        # genuine-low-confidence distinguishable from compute failures.
        macd_val = macd_dict.get("macd_hist_rising") if macd_dict is not None else None
        struct_val = struct_results.get("struct_break_5")
        if macd_val is None or struct_val is None:
            sub_score_at_entry: Optional[int] = None
            signals_computed_at_entry = False
        else:
            sub_score_at_entry = (1 if bool(macd_val) else 0) + (1 if bool(struct_val) else 0)
            signals_computed_at_entry = True

        # Entry-bar timestamp (last row of df_5m), for Phase 2 join.
        entry_bar_ts = None
        try:
            ts_col = "timestamp" if "timestamp" in df_5m.columns else (
                "time" if "time" in df_5m.columns else None
            )
            if ts_col:
                v = df_5m[ts_col].iloc[-1]
                if hasattr(v, "isoformat"):
                    entry_bar_ts = v.isoformat()
                else:
                    entry_bar_ts = str(v)
        except Exception:
            pass

        record = {
            "phase": 1,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "trade_id": str(trade_id),
            "deal_id": deal_id,
            "pair": str(pair).upper(),
            "strategy": strategy,
            "direction": str(direction).upper(),
            "entry_price": float(entry_price) if entry_price is not None else None,
            "entry_bar_ts": entry_bar_ts,
            "macd": macd_dict,  # full dict or None
            **{k: v for k, v in struct_results.items()},
            # sub_score_at_entry: int 0..N when computed, None when compute failed.
            # signals_computed_at_entry distinguishes "evaluated false" from "no data".
            "sub_score_at_entry": sub_score_at_entry,
            "signals_computed_at_entry": signals_computed_at_entry,
        }
        _write_record(record)

        # Register for Phase 2 next-bar evaluation
        with _PENDING_LOCK:
            _PENDING[str(trade_id)] = {
                "pair": str(pair).upper(),
                "direction": str(direction).upper(),
                "entry_price": float(entry_price) if entry_price is not None else None,
                "entry_bar_ts": entry_bar_ts,
                "strategy": strategy,
                "deal_id": deal_id,
                "macd_hist_rising": (macd_dict.get("macd_hist_rising")
                                     if macd_dict else None),
                "struct_break_5": struct_results.get("struct_break_5"),
            }
        return record
    except Exception as exc:
        logger.warning("[confirmation_engine] Phase 1 raised: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────
# Phase 2 — on next 5m close after the entry bar
# ─────────────────────────────────────────────────────────────────────
def evaluate_next_bar_on_close(pair: str, df_5m: "pd.DataFrame") -> int:
    """For every pending trade on this pair whose entry_bar_ts is in the
    SECOND-TO-LAST closed bar of df_5m, evaluate next_bar_continued using
    the LAST closed bar (the just-closed one).

    Returns count of records written. Caller MUST wrap in try/except.
    """
    if not CONFIRMATION_ENGINE_ENABLED:
        return 0
    written = 0
    try:
        if df_5m is None or len(df_5m) < 2:
            return 0
        # The just-closed bar = LAST row; entry-bar of qualifying trades =
        # SECOND-TO-LAST row (timestamp).
        ts_col = "timestamp" if "timestamp" in df_5m.columns else (
            "time" if "time" in df_5m.columns else None
        )
        if ts_col is None:
            return 0
        try:
            prev_ts = df_5m[ts_col].iloc[-2]
            cur_close = float(df_5m["close"].iloc[-1])
        except Exception:
            return 0
        prev_ts_iso = (prev_ts.isoformat() if hasattr(prev_ts, "isoformat")
                       else str(prev_ts))

        pair_u = str(pair).upper()
        # Find pending trades whose entry_bar_ts matches prev_ts
        with _PENDING_LOCK:
            ready = [
                (tid, pend) for tid, pend in _PENDING.items()
                if pend.get("pair") == pair_u and pend.get("entry_bar_ts") == prev_ts_iso
            ]
            for tid, _ in ready:
                _PENDING.pop(tid, None)

        for tid, pend in ready:
            try:
                nb_cont = _next_bar_continued(
                    cur_close, pend.get("entry_price"), pend.get("direction"),
                )
                # ⚠️ NULL-vs-ZERO: composite_score is None unless ALL three
                # signals were computed. Score 0 means "all three evaluated
                # false"; score None means "at least one signal couldn't be
                # computed" (no data, restart-gap loss of pending state, etc.).
                # signals_computed_full distinguishes the two in downstream
                # joins.
                macd_v = pend.get("macd_hist_rising")
                struct_v = pend.get("struct_break_5")
                signals_computed_full = (
                    macd_v is not None and struct_v is not None and nb_cont is not None
                )
                if signals_computed_full:
                    composite_score: Optional[int] = (
                        (1 if bool(macd_v) else 0)
                        + (1 if bool(struct_v) else 0)
                        + (1 if bool(nb_cont) else 0)
                    )
                else:
                    composite_score = None

                record = {
                    "phase": 2,
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "trade_id": tid,
                    "deal_id": pend.get("deal_id"),
                    "pair": pair_u,
                    "strategy": pend.get("strategy"),
                    "direction": pend.get("direction"),
                    "entry_price": pend.get("entry_price"),
                    "entry_bar_ts": pend.get("entry_bar_ts"),
                    "next_bar_close": cur_close,
                    "next_bar_continued": nb_cont,
                    "composite_score": composite_score,
                    "signals_computed_full": signals_computed_full,
                    "composite_components": {
                        "macd_hist_rising": macd_v,
                        "struct_break_5": struct_v,
                        "next_bar_continued": nb_cont,
                    },
                }
                _write_record(record)
                written += 1
            except Exception as inner:
                logger.warning(
                    "[confirmation_engine] Phase 2 inner-loop raised for %s: %s",
                    tid, inner,
                )
        return written
    except Exception as exc:
        logger.warning("[confirmation_engine] Phase 2 raised: %s", exc)
        return 0


# ─────────────────────────────────────────────────────────────────────
# Test/inspection helpers (not used in live path)
# ─────────────────────────────────────────────────────────────────────
def _pending_size() -> int:
    with _PENDING_LOCK:
        return len(_PENDING)


def _reset_pending() -> None:
    """Clear pending registry (for tests/restart)."""
    with _PENDING_LOCK:
        _PENDING.clear()
