#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
diagnostics_logger.py — Read-only verbose diagnostic logger.

Fires at most once every 5 minutes per symbol, during London trading hours
(07:00–16:00), and appends a human-readable block to logs/diagnostics.log.

This module is a passive observer only.  It does not call any strategy
functions, does not mutate any state, and cannot affect trade execution.
All values are read from objects that the main evaluation loop has already
computed before calling maybe_log().
"""

import json
import logging
import threading
from datetime import time as dtime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

LOG_DIR = Path("/opt/tradingbot/logs")
LOG_FILE = LOG_DIR / "diagnostics.log"

_LONDON_TZ = "Europe/London"
_WINDOW_START = dtime(7, 0)
_WINDOW_END = dtime(16, 0)
_INTERVAL_SECONDS = 300  # 5 minutes

# Symbols whose pip size is 0.01 (JPY pairs)
_JPY_SYMBOLS = frozenset({"USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "CHFJPY"})


def _pip_size(symbol: str) -> float:
    return 0.01 if str(symbol).upper() in _JPY_SYMBOLS else 0.0001


def _fmt(v: Any, dp: int = 5) -> str:
    """Format a float to dp decimal places, or '—' for None/NaN."""
    if v is None:
        return "—"
    try:
        f = float(v)
        if f != f:  # NaN check
            return "—"
        return f"{f:.{dp}f}"
    except Exception:
        return str(v)


def _fmt_pips(v: Any) -> str:
    """Format a signed pip distance, or '—'."""
    if v is None:
        return "—"
    try:
        return f"{float(v):+.1f} pips"
    except Exception:
        return "—"


def _df_last(df: pd.DataFrame, col: str) -> Optional[float]:
    """Safely read the last value of a column from a DataFrame."""
    try:
        if col not in df.columns:
            return None
        v = df[col].iloc[-1]
        f = float(v)
        return None if f != f else f  # drop NaN
    except Exception:
        return None


class DiagnosticsLogger:
    """
    Thread-safe, rate-limited diagnostic snapshot logger.

    Usage (from the main evaluation loop):
        _diag_logger.maybe_log(symbol, mid_price, df, htf_snapshot, decision)
    """

    def __init__(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # symbol → float epoch of last log write
        self._last_logged: Dict[str, float] = {}
        self._logger = self._build_logger()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_logger() -> logging.Logger:
        log = logging.getLogger("diagnostics_file")
        log.setLevel(logging.DEBUG)
        if not log.handlers:
            fh = logging.FileHandler(str(LOG_FILE), mode="a", encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(message)s"))
            log.addHandler(fh)
            log.propagate = False  # don't bubble into root / console
        return log

    @staticmethod
    def _london_now() -> pd.Timestamp:
        return pd.Timestamp.now(tz=_LONDON_TZ)

    @staticmethod
    def _in_window(now: pd.Timestamp) -> bool:
        t = now.time()
        return _WINDOW_START <= t < _WINDOW_END

    def _is_due(self, symbol: str, now_epoch: float) -> bool:
        return (now_epoch - self._last_logged.get(symbol, 0.0)) >= _INTERVAL_SECONDS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def maybe_log(
        self,
        symbol: str,
        mid_price: float,
        df: Optional[pd.DataFrame],
        htf_snapshot: Optional[Dict[str, Any]],
        decision: Any,
    ) -> None:
        """
        Called on every tick.  Writes a diagnostic block only when:
          - London time is between 07:00 and 16:00, and
          - At least 5 minutes have elapsed since the last write for this symbol.
        """
        now = self._london_now()
        if not self._in_window(now):
            return

        now_epoch = now.timestamp()
        with self._lock:
            if not self._is_due(symbol, now_epoch):
                return
            self._last_logged[symbol] = now_epoch

        # Build and write outside the lock so we don't hold it during I/O.
        try:
            block = self._build_block(symbol, mid_price, df, htf_snapshot, decision, now)
            self._logger.info(block)
        except Exception as exc:  # journal must never crash the bot
            try:
                self._logger.info(f"\n[DIAG-ERROR] {symbol} @ {now}: {exc}\n")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Block builder
    # ------------------------------------------------------------------

    def _build_block(
        self,
        symbol: str,
        mid_price: float,
        df: Optional[pd.DataFrame],
        htf_snapshot: Optional[Dict[str, Any]],
        decision: Any,
        now: pd.Timestamp,
    ) -> str:
        sym = str(symbol).upper()
        dbg: Dict[str, Any] = getattr(decision, "debug", None) or {}
        htf: Dict[str, Any] = htf_snapshot or {}
        # _attach_htf_debug() stores a compact copy on dec.debug["htf_snapshot"];
        # use that as a fallback when htf_snapshot is None or a key is absent.
        htf_compact: Dict[str, Any] = dbg.get("htf_snapshot") or {}

        # ---- Regime ------------------------------------------------
        ctx_regime       = dbg.get("ctx_regime") or "—"
        effective_regime = (
            dbg.get("effective_regime")
            or dbg.get("regime_ctx")
            or "—"
        )

        # ---- HTF biases --------------------------------------------
        # h4_bias may not yet be populated by timeframe_context.py;
        # show whatever is present and fall back to '—' gracefully.
        h1_bias = htf.get("h1_bias") or htf_compact.get("h1_bias") or "—"
        h4_bias = htf.get("h4_bias") or htf_compact.get("h4_bias") or "—"
        d1_bias = htf.get("d1_bias") or htf_compact.get("d1_bias") or "—"

        htf_json = json.dumps(
            {
                "h1_bias":         htf.get("h1_bias"),
                "h4_bias":         htf.get("h4_bias"),
                "d1_bias":         htf.get("d1_bias"),
                "h1_ema8":         htf.get("h1_ema8"),
                "h1_ema21":        htf.get("h1_ema21"),
                "h1_price":        htf.get("h1_price"),
                "h1_anchor_ready": htf.get("h1_anchor_ready"),
                "h1_anchor_buy_ok":  htf.get("h1_anchor_buy_ok"),
                "h1_anchor_sell_ok": htf.get("h1_anchor_sell_ok"),
            },
            default=str,
        )

        # ---- Market context ----------------------------------------
        ctx_location     = dbg.get("ctx_location") or "—"
        ctx_vol          = dbg.get("ctx_volatility_state") or "—"
        ctx_veto_rr      = dbg.get("ctx_veto_rr")
        ctx_veto_rr_rsn  = dbg.get("ctx_veto_rr_reason") or "ok"
        ctx_veto_ema     = dbg.get("ctx_veto_ema")
        ctx_veto_ema_rsn = dbg.get("ctx_veto_ema_reason") or "ok"
        ctx_debug_inner: Dict[str, Any] = dbg.get("ctx_debug") or {}
        mkt_ctx_json = json.dumps(ctx_debug_inner, default=str) if ctx_debug_inner else "{}"

        # ---- 5m EMAs -----------------------------------------------
        ema_8 = ema_13 = ema_21 = ema_50 = None
        dist_ema21 = None
        ps = _pip_size(sym)

        if isinstance(df, pd.DataFrame) and not df.empty:
            ema_8  = _df_last(df, "EMA_8")
            ema_13 = _df_last(df, "EMA_13")
            ema_21 = _df_last(df, "EMA_21")
            ema_50 = _df_last(df, "EMA_50")
            if ema_21 is not None:
                try:
                    dist_ema21 = (float(mid_price) - ema_21) / ps
                except Exception:
                    pass

        # ---- Decision summary (non-intrusive) ----------------------
        dec_signal = str(getattr(decision, "signal", "") or "NONE")
        dec_reason = str(getattr(decision, "reason", "") or "")
        dec_mode   = str(getattr(decision, "mode", "") or "")

        sep = "=" * 72
        return (
            f"\n{sep}\n"
            f"DIAG  {sym:<8}  {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"{sep}\n"
            f"  mid_price          : {_fmt(mid_price)}\n"
            f"  signal / mode      : {dec_signal} / {dec_mode}\n"
            f"  reason             : {dec_reason}\n"
            f"\n"
            f"  REGIME\n"
            f"  ctx_regime         : {ctx_regime}\n"
            f"  effective_regime   : {effective_regime}\n"
            f"\n"
            f"  HTF BIASES\n"
            f"  h1_bias            : {h1_bias}\n"
            f"  h4_bias            : {h4_bias}\n"
            f"  d1_bias            : {d1_bias}\n"
            f"  htf_snapshot       : {htf_json}\n"
            f"\n"
            f"  MARKET CONTEXT\n"
            f"  ctx_location       : {ctx_location}\n"
            f"  ctx_volatility     : {ctx_vol}\n"
            f"  veto_rr            : {ctx_veto_rr}  ({ctx_veto_rr_rsn})\n"
            f"  veto_ema           : {ctx_veto_ema}  ({ctx_veto_ema_rsn})\n"
            f"  ctx_debug          : {mkt_ctx_json}\n"
            f"\n"
            f"  5M EMAs\n"
            f"  EMA_8              : {_fmt(ema_8)}\n"
            f"  EMA_13             : {_fmt(ema_13)}\n"
            f"  EMA_21             : {_fmt(ema_21)}\n"
            f"  EMA_50             : {_fmt(ema_50)}\n"
            f"  dist_from_ema21    : {_fmt_pips(dist_ema21)}\n"
            f"{sep}\n"
        )
