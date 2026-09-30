#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
sweep_journal.py — Daily CSV trade journal for sweep signals.

One file per calendar day: logs/sweep_journal_YYYY-MM-DD.csv
Append-safe: survives process restarts mid-day (appends to existing file,
rebuilds open-row index on startup).
"""

import csv
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import news_calendar

LOG_DIR = Path("/opt/tradingbot/logs")

COLUMNS = [
    "timestamp", "symbol", "epic", "signal", "mode", "taken", "blocked_reason",
    "entry_price", "sl_pips", "tp_pips", "exit_price", "pnl_pips",
    "close_reason", "sweep_stage", "exhaustion_votes", "exhaustion_count",
    "guards_fired", "fast_reclaim", "london_time", "news_day", "news_events",
    "strong_reversal_bypass", "overshoot_pips", "rejection_pips",
    "trend_age_candles", "sweep_veto_fired", "sweep_veto_reason",
    "ctx_regime", "effective_regime", "h1_bias", "h4_bias", "d1_bias",
    "htf_snapshot", "sweep_quality_json", "pattern",
]


def _fmt(val: Any) -> str:
    """Format a numeric-or-None value for CSV; returns '' for None."""
    if val is None:
        return ""
    try:
        return str(float(val))
    except (TypeError, ValueError):
        return str(val)


class SweepJournal:
    """
    Thread-safe daily CSV journal.

    log_signal() — call after every evaluate_signals BUY/SELL, and for
                   NONE decisions blocked by sweep guards/exhaustion.
    log_close()  — call when a trade closes; patches the open row in-place.
    """

    def __init__(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._date_key: str = ""
        self._csv_path: Optional[Path] = None
        self._rows: list = []
        # "symbol|epic" → FIFO list of row indices for unclosed trades.
        # Using a list per key means overlapping trades on the same pair
        # are matched in open-order: first open gets first close.
        self._open_rows_by_key: Dict[str, list] = {}
        self._ensure_file()

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    def _today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _ensure_file(self) -> None:
        """Roll to a new daily file when the UTC date changes."""
        today = self._today_str()
        if today == self._date_key:
            return

        self._date_key = today
        self._csv_path = LOG_DIR / f"sweep_journal_{today}.csv"
        self._rows = []
        self._open_rows_by_key = {}

        if self._csv_path.exists():
            # Load existing rows and rebuild open-row index for ALL unclosed rows
            try:
                with open(self._csv_path, newline="") as fh:
                    for row in csv.DictReader(fh):
                        self._rows.append(dict(row))
                for idx, row in enumerate(self._rows):
                    if row.get("taken") == "True" and not row.get("exit_price") and not row.get("close_reason"):
                        key = f"{row.get('symbol', '')}|{row.get('epic', '')}|{str(row.get('signal', '')).upper()}"
                        self._open_rows_by_key.setdefault(key, []).append(idx)
            except Exception:
                self._rows = []
                self._open_rows_by_key = {}
                # Recreate with header only
                with open(self._csv_path, "w", newline="") as fh:
                    csv.DictWriter(fh, fieldnames=COLUMNS).writeheader()
        else:
            # Brand-new file — write header so appends are always data-only
            with open(self._csv_path, "w", newline="") as fh:
                csv.DictWriter(fh, fieldnames=COLUMNS).writeheader()

    def _rewrite_file(self) -> None:
        """Full rewrite used after log_close patches a row in-place."""
        with open(self._csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(self._rows)

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------

    def log_signal(
        self,
        decision: Any,
        taken: bool,
        blocked_reason: str = "",
        epic: str = "",
    ) -> None:
        """
        Write one row for a signal event.

        decision    — StrategyDecision (or any object with .symbol, .signal,
                      .mode, .entry, .sl, .tp, .reason, .debug attributes)
        taken       — True if execute_trade confirmed the position opened
        blocked_reason — reason string when taken=False
        epic        — the IG epic string (not on StrategyDecision; caller supplies it)
        """
        with self._lock:
            try:
                self._ensure_file()

                dbg: Dict[str, Any] = getattr(decision, "debug", None) or {}
                reason: str = str(getattr(decision, "reason", "") or "")

                exh: Dict[str, Any] = dbg.get("sweep_exhaustion") or {}
                sweep_stage = dbg.get("sweep_stage")
                exhaustion_votes = exh.get("votes")
                exhaustion_count = exh.get("vote_count")

                guards_fired = (
                    "sweep_arm_rejected" in reason
                    or "sweep_stage2_invalidated" in reason
                    or "sweep_quality_fail" in reason
                    or "sweep_arm_rejected" in blocked_reason
                    or "sweep_stage2_invalidated" in blocked_reason
                    or "sweep_quality_fail" in blocked_reason
                )

                fast_reclaim = bool(
                    dbg.get("fast_reclaim_used")
                    or "fast_reclaim" in reason
                )

                london_time = dbg.get("london_time")
                symbol = str(getattr(decision, "symbol", "") or "")

                veto: Dict[str, Any] = dbg.get("sweep_veto") or {}
                strong_reversal_bypass = dbg.get("strong_reversal_bypass")
                overshoot_pips         = dbg.get("overshoot_pips")
                rejection_pips         = dbg.get("rejection_pips")
                trend_age_candles      = dbg.get("trend_age_candles")
                sweep_veto_fired       = veto.get("fired")
                sweep_veto_reason      = veto.get("reason")

                ctx_regime        = dbg.get("ctx_regime")
                effective_regime  = dbg.get("effective_regime")
                htf_snap: Dict[str, Any] = dbg.get("htf_snapshot") or {}
                h1_bias           = htf_snap.get("h1_bias")
                h4_bias           = htf_snap.get("h4_bias")
                d1_bias           = htf_snap.get("d1_bias")
                htf_snapshot_json = json.dumps(dbg.get("htf_snapshot") or {})

                row: Dict[str, str] = {
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "symbol": symbol,
                    "epic": str(epic),
                    "signal": str(getattr(decision, "signal", "") or ""),
                    "mode": str(getattr(decision, "mode", "") or ""),
                    "taken": str(taken),
                    "blocked_reason": str(blocked_reason),
                    "entry_price": _fmt(getattr(decision, "entry", None)),
                    "sl_pips": _fmt(getattr(decision, "sl", None)),
                    "tp_pips": _fmt(getattr(decision, "tp", None)),
                    "exit_price": "",
                    "pnl_pips": "",
                    "close_reason": "",
                    "sweep_stage": str(sweep_stage) if sweep_stage is not None else "",
                    "exhaustion_votes": str(exhaustion_votes) if exhaustion_votes is not None else "",
                    "exhaustion_count": str(exhaustion_count) if exhaustion_count is not None else "",
                    "guards_fired": str(guards_fired),
                    "fast_reclaim": str(fast_reclaim),
                    "london_time": str(london_time) if london_time is not None else "",
                    "news_day": str(news_calendar.is_news_day()),
                    "news_events": json.dumps(news_calendar.get_todays_events()),
                    "strong_reversal_bypass": str(strong_reversal_bypass) if strong_reversal_bypass is not None else "",
                    "overshoot_pips": _fmt(overshoot_pips),
                    "rejection_pips": _fmt(rejection_pips),
                    "trend_age_candles": str(trend_age_candles) if trend_age_candles is not None else "",
                    "sweep_veto_fired": str(sweep_veto_fired) if sweep_veto_fired is not None else "",
                    "sweep_veto_reason": str(sweep_veto_reason) if sweep_veto_reason is not None else "",
                    "ctx_regime": str(ctx_regime) if ctx_regime is not None else "",
                    "effective_regime": str(effective_regime) if effective_regime is not None else "",
                    "h1_bias": str(h1_bias) if h1_bias is not None else "",
                    "h4_bias": str(h4_bias) if h4_bias is not None else "",
                    "d1_bias": str(d1_bias) if d1_bias is not None else "",
                    "htf_snapshot": htf_snapshot_json,
                    "sweep_quality_json": json.dumps(dbg.get("sweep_quality") or {}),
                    "pattern": str(dbg.get("pattern", "") or ""),
                }

                idx = len(self._rows)
                self._rows.append(row)

                if taken:
                    _sig = str(getattr(decision, "signal", "") or "").upper()
                    key = f"{symbol}|{epic}|{_sig}"
                    self._open_rows_by_key.setdefault(key, []).append(idx)

                # Append only — header was written at file creation
                with open(self._csv_path, "a", newline="") as fh:
                    csv.DictWriter(fh, fieldnames=COLUMNS).writerow(row)

            except Exception:
                pass  # journal must never crash the bot

    def log_close(
        self,
        symbol: str,
        epic: str,
        exit_price: Any,
        pnl_pips: Any,
        close_reason: str,
        direction: str = "",
    ) -> None:
        """
        Find the oldest unclosed row for symbol/epic/direction (FIFO) and fill
        in exit fields. Rewrites the daily file in-place.
        When direction is empty, falls back to any-direction FIFO match.
        """
        with self._lock:
            try:
                self._ensure_file()

                dir_up = str(direction or "").upper()
                if dir_up in ("BUY", "SELL"):
                    key = f"{symbol}|{epic}|{dir_up}"
                    idx_list = self._open_rows_by_key.get(key)
                else:
                    # legacy fallback — pick any open row for this epic
                    idx_list = None
                    for k in list(self._open_rows_by_key.keys()):
                        if k.startswith(f"{symbol}|{epic}|") and self._open_rows_by_key[k]:
                            idx_list = self._open_rows_by_key[k]
                            key = k
                            break
                if not idx_list:
                    return

                # FIFO: close the earliest open trade for this pair
                idx = idx_list.pop(0)
                if not idx_list:
                    del self._open_rows_by_key[key]

                if idx >= len(self._rows):
                    return

                self._rows[idx]["exit_price"] = _fmt(exit_price)
                self._rows[idx]["pnl_pips"] = _fmt(pnl_pips)
                self._rows[idx]["close_reason"] = str(close_reason or "")

                self._rewrite_file()

            except Exception:
                pass  # journal must never crash the bot
