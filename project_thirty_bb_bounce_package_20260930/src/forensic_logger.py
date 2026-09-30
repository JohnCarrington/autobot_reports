"""Forensic fire logger — writes complete fire snapshot records to
/opt/tradingbot/logs/forensic_fires.jsonl for the May 19 review.

NOT a strategy gate. NOT consumed by live trading. Sole purpose is data
collection for offline analysis of accumulated fire context.

KNOWN LOST-DATA WINDOW: 21 BRIEFING_EXECUTION records written between
2026-05-05 06:16Z and 2026-05-08 11:10Z carry fire_bar_ts =
"1970-01-01T00:00:00+00:00" — a RangeIndex-as-nanoseconds corruption
fixed by _derive_fire_bar_ts (this module). These records are
unrecoverable; the fire_bar_ts cannot be reconstructed post-hoc and
the JOIN to signal_log fails. Future fires (post-fix) are guarded
against the same bug class. Anyone reading the file after this fix
lands should treat any fire_bar_ts < 2020 as the legacy bug, not a
current data-quality issue.

API:
    write_forensic_fire(strategy, direction, entry_price, fire_bar_ts,
                        snapshot_dict) -> bool

Behavior contract:
- Wrapped in try/except — never raises, even on bad input or disk
  failure. Returns False on suppress/failure, True on success.
- Honors GBPUSD_FORENSIC_LOGGING_ENABLED env (default "true"). When
  false, write is skipped and the function returns False.
- Atomic write: read existing file → append → write to a temp file in
  the same directory → os.replace() (atomic on POSIX). A crash mid-
  write leaves either the prior file untouched or the new file in
  place — never a partial line.

Schema (one JSON object per line):
    {
      "timestamp":             ISO 8601 UTC of write time,
      "fire_bar_ts":           ISO 8601 UTC of the eval bar,
      "strategy":              str (e.g. "GBPUSD_BB_BOUNCE_L"),
      "direction":             "LONG" | "SHORT",
      "entry_price":           float,
      "snapshot":              {forensic_fire_snapshot output},
      "outcome":               null at write time; populated by the
                               hourly forensic-backfill.timer (systemd,
                               OnCalendar=*-*-* *:05:00 UTC) which runs
                               scripts/forensic_outcome_backfill.py and
                               JOINs to signal_log.jsonl on
                               (strategy, fire_bar_ts ↔ timestamp_open
                               floored to the prior 5m bar). Idempotent
                               — re-runs only update records that still
                               lack an outcome. Last successful run
                               timestamp lives at
                               /opt/tradingbot/logs/forensic_backfill_last_run.json
                               (written by the systemd ExecStartPost
                               hook, only on exit-0).
      "outcome_pips":          null at write time except when
                               block_reason is set (see below) —
                               then 0.0 is written immediately.
      "outcome_exit_reason":   null,
      "outcome_close_ts":      null,
      "block_reason":          null | dict (set when a live gate
                               suppressed the fire — see below)
    }

When ``block_reason`` is supplied to ``write_forensic_fire``, the
record represents a fire that was suppressed by a live gate (no
trade was taken). Three fields shift to reflect the suppression:
``outcome_pips`` is set to 0, ``outcome_exit_reason`` carries the
gate label (e.g. ``"macd_extended_momentum_gate_blocked"`` —
read from ``block_reason["rule"]`` with a ``_gate_blocked``
suffix), and ``block_reason`` itself stores the gate's diagnostic
dict so the May 19 review can compare what was blocked vs what
fired. Approved fires (``block_reason=None``) keep the original
schema unchanged; the backfill still owns ``outcome*``.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("AutoBot")

DEFAULT_LOG_PATH = "/opt/tradingbot/logs/forensic_fires.jsonl"
ENV_LOG_PATH = "GBPUSD_FORENSIC_LOG_PATH"
ENV_FLAG = "GBPUSD_FORENSIC_LOGGING_ENABLED"


def _log_path() -> Path:
    """Resolve log path from env (re-read each call so tests can override)."""
    return Path(os.getenv(ENV_LOG_PATH, DEFAULT_LOG_PATH))


def _enabled() -> bool:
    """True iff forensic logging is enabled. Default true."""
    val = os.getenv(ENV_FLAG, "true").strip().lower()
    return val in ("1", "true", "yes", "on")


def _normalize_direction(direction: str) -> str:
    d = (direction or "").upper()
    if d == "BUY":
        return "LONG"
    if d == "SELL":
        return "SHORT"
    return d  # pass-through; caller decides if "LONG"/"SHORT" or other


_PAIR_PREFIXES = ("GBPUSD", "EURUSD", "USDJPY", "USDCAD")


def _infer_pair(strategy: str, pair: Optional[str]) -> Optional[str]:
    if isinstance(pair, str) and pair.strip():
        return pair.strip().upper()
    s = (strategy or "").upper()
    for p in _PAIR_PREFIXES:
        if s.startswith(p):
            return p
    return None


def _build_record(strategy: str, direction: str, entry_price: Optional[float],
                  fire_bar_ts: str, snapshot_dict: Optional[dict],
                  block_reason: Optional[dict] = None,
                  fire_path: Optional[str] = None,
                  pair: Optional[str] = None) -> dict:
    """Build the JSONL record dict with the documented schema.

    When ``block_reason`` is provided, the record represents a
    gate-suppressed fire: ``outcome_pips=0`` and
    ``outcome_exit_reason`` is derived from the gate's ``rule``
    field (e.g. ``"macd_extended_momentum_gate"`` becomes
    ``"macd_extended_momentum_gate_blocked"``). The backfill is
    expected to skip records where ``block_reason`` is not None.

    ``fire_path`` is an optional caller-supplied tag identifying the
    dispatch path within a multi-path strategy (e.g. BRIEFING_EXECUTION's
    ``phase2_sweep_reclaim`` vs ``trend_entry_fallback``). Persisted
    additively so older records and non-tagging callers remain valid.

    ``pair`` is an optional caller-supplied currency-pair tag used to
    look up the Phase 4B cascade label for the top-level
    ``cascade_label_at_fire`` / ``cascade_age_seconds`` fields. When
    omitted, the pair is inferred from a known pair-prefixed strategy
    name (e.g. ``GBPUSD_BB_BOUNCE_L``). Strategies that aren't pair-
    prefixed (e.g. ``BRIEFING_EXECUTION``, ``NEWS_TICK``, ``3CO``) MUST
    pass ``pair`` explicitly or the cascade fields will be null.
    """
    if block_reason is not None:
        rule = (block_reason.get("rule") or "unknown_gate") if isinstance(block_reason, dict) else "unknown_gate"
        outcome_pips: Optional[float] = 0.0
        outcome_exit_reason: Optional[str] = f"{rule}_blocked"
    else:
        outcome_pips = None
        outcome_exit_reason = None
    resolved_pair = _infer_pair(strategy, pair)
    cascade_label: Optional[str] = None
    cascade_age_seconds: Optional[float] = None
    if resolved_pair:
        try:
            from cascade_state import read_latest_cascade
            cascade_label, cascade_age_seconds = read_latest_cascade(resolved_pair)
        except Exception:
            cascade_label, cascade_age_seconds = (None, None)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fire_bar_ts": fire_bar_ts,
        "strategy": strategy,
        "fire_path": fire_path if isinstance(fire_path, str) and fire_path else None,
        "direction": _normalize_direction(direction),
        "entry_price": float(entry_price) if entry_price is not None else None,
        "cascade_label_at_fire": cascade_label,
        "cascade_age_seconds": cascade_age_seconds,
        "snapshot": snapshot_dict if snapshot_dict is not None else {},
        "outcome": None,
        "outcome_pips": outcome_pips,
        "outcome_exit_reason": outcome_exit_reason,
        "outcome_close_ts": None,
        "block_reason": block_reason if isinstance(block_reason, dict) else None,
    }


def _atomic_append_jsonl(log_path: Path, record: dict) -> None:
    """Atomically append a JSONL record to log_path.

    Strategy:
      1. Read existing file bytes (if any).
      2. Write existing + new line to a temp file in the same directory.
      3. fsync the temp file.
      4. os.replace(tmp, log_path) — atomic rename on POSIX.

    A process crash during steps 1-3 leaves log_path untouched. A crash
    between fsync and replace is also safe (replace is atomic; either it
    happened or it didn't). The only risk window is hardware-level
    failure between fsync return and rename completion, which is below
    the protection level of normal append+fsync anyway.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":")) + "\n"

    existing = b""
    if log_path.exists():
        with open(log_path, "rb") as f:
            existing = f.read()

    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=str(log_path.parent),
            prefix=log_path.name + ".tmp.",
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(existing)
            tmp.write(line.encode("utf-8"))
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(str(tmp_path), str(log_path))
        tmp_path = None  # successfully consumed by replace
    finally:
        # If we created a temp file but didn't successfully replace, clean up.
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def write_forensic_fire(
    strategy: str,
    direction: str,
    entry_price: Optional[float],
    fire_bar_ts: str,
    snapshot_dict: Optional[dict],
    block_reason: Optional[dict] = None,
    fire_path: Optional[str] = None,
    pair: Optional[str] = None,
) -> bool:
    """Write a forensic fire record to the JSONL log. NEVER raises.

    ``block_reason`` is an optional dict describing a live gate
    that suppressed this fire (see module docstring). When
    present, the record's outcome fields are pre-set to mark the
    fire as blocked.

    ``fire_path`` is an optional tag identifying the dispatch path
    within a multi-path strategy (persisted to the JSONL).

    ``pair`` is the currency-pair tag used to populate the top-level
    ``cascade_label_at_fire`` / ``cascade_age_seconds`` fields. When
    omitted, the pair is inferred from a pair-prefixed strategy name.

    Returns:
        True  — record successfully written.
        False — disabled by ENV flag, OR any error during write.
                A warning is logged via the AutoBot logger on failure.
    """
    if not _enabled():
        return False
    try:
        record = _build_record(strategy, direction, entry_price,
                               fire_bar_ts, snapshot_dict,
                               block_reason=block_reason,
                               fire_path=fire_path,
                               pair=pair)
        _atomic_append_jsonl(_log_path(), record)
        return True
    except Exception as exc:  # noqa: BLE001 — broad by design, never raise
        try:
            logger.warning(
                "[forensic_logger] write failed for %s %s @ %s: %s",
                strategy, direction, fire_bar_ts, exc,
            )
        except Exception:
            pass
        return False


def _derive_fire_bar_ts(df_5m) -> str:
    """Derive ISO 8601 UTC timestamp of the most recent 5m bar from df_5m.

    Defensive against the RangeIndex bug that corrupted 21 BRIEFING_EXECUTION
    forensic records between 2026-05-05 and 2026-05-08: when df_5m had a
    default RangeIndex (rows numbered 0..N-1) and `pd.Timestamp(599)` was
    interpreted as 599 nanoseconds since the Unix epoch, every record got
    fire_bar_ts="1970-01-01T00:00:00.000000599" — silent corruption that
    only surfaced at the May 8 forensic_outcome_backfill JOIN.

    Lookup order:
      1. df_5m["timestamp"] column — the natural shape produced by
         candle_builder/pd.read_csv on the cache CSVs.
      2. df_5m.index[-1] — only if df_5m.index is a DatetimeIndex.
      3. Otherwise raise ValueError. Outer try/except in the caller
         logs WARNING and skips the record rather than writing garbage.

    Final sanity check: year must be ≥ 2020. Any earlier value is
    presumed-bug (RangeIndex-as-ns or similar) and rejected loudly.
    """
    import pandas as _pd
    if df_5m is None or not hasattr(df_5m, "__len__") or len(df_5m) == 0:
        raise ValueError("df_5m empty or unavailable")

    if hasattr(df_5m, "columns") and "timestamp" in df_5m.columns:
        raw = df_5m["timestamp"].iloc[-1]
    elif isinstance(df_5m.index, _pd.DatetimeIndex):
        raw = df_5m.index[-1]
    else:
        raise ValueError(
            f"cannot derive fire_bar_ts: df_5m has no 'timestamp' column "
            f"and index is {type(df_5m.index).__name__}, not DatetimeIndex"
        )

    ts = _pd.Timestamp(raw)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    if ts.year < 2020:
        raise ValueError(
            f"derived fire_bar_ts={ts.isoformat()} is implausible "
            f"(year < 2020) — likely RangeIndex-as-nanoseconds or other "
            f"malformed input; refusing to write a corrupt record"
        )

    return ts.to_pydatetime().isoformat()


def capture_fire_from_df(
    sym: str,
    strategy: str,
    direction: str,
    entry_price: float,
    df_5m,
    pip_size: float,
    fire_path: str = "default",
    block_reason: Optional[dict] = None,
) -> None:
    """One-shot forensic capture from a 5m DataFrame. Never raises.

    Builds a multi-axis snapshot via indicators.forensic_fire_snapshot
    (5m + HTF + briefing levels + session + news state) and appends a
    single forensic_fires.jsonl record. Soft-fails to a single WARNING
    log line tagged with `sym` + `fire_path` so post-mortems can pinpoint
    the emit site without reading a traceback.

    Caller must pass `strategy` exactly as it should appear in the JSONL
    record. JOIN convention is signal_log.strategy = forensic.strategy,
    so callers use the same string they pass to signal_logger.log_open
    (e.g. "NEWS_TICK", "NEWS_STRATEGY", "3CO", "GBPUSD_BB_BOUNCE_L").
    """
    try:
        import pandas as _ff_pd
        from indicators import forensic_fire_snapshot as _ff_snapshot_fn
        from forensic_context import (
            load_htf_series as _ff_load_htf,
            briefing_levels_for_sym as _ff_briefing_levels,
            session_state_now as _ff_session_state,
            news_state_now as _ff_news_state,
        )

        if df_5m is None or not hasattr(df_5m, "__len__") or len(df_5m) == 0:
            raise ValueError("df_5m empty or unavailable")

        closes_5m = _ff_pd.Series(df_5m["close"].astype(float).tolist())
        highs_5m = _ff_pd.Series(df_5m["high"].astype(float).tolist())
        lows_5m = _ff_pd.Series(df_5m["low"].astype(float).tolist())

        # Defensive: rejects RangeIndex-as-nanoseconds malformed dfs
        # loudly rather than writing a silent epoch-1970 record. See
        # _derive_fire_bar_ts docstring for the bug-class context.
        fire_bar_ts = _derive_fire_bar_ts(df_5m)

        if direction == "BUY":
            norm_dir = "LONG"
        elif direction == "SELL":
            norm_dir = "SHORT"
        else:
            norm_dir = direction

        sym_u = (sym or "").upper()
        if len(sym_u) >= 6:
            ccys = list(dict.fromkeys([sym_u[:3], sym_u[3:6]]))
        else:
            ccys = []

        (_h1c, _h1h, _h1l, _h4c, _h4h, _h4l) = _ff_load_htf(sym_u)
        snap = _ff_snapshot_fn(
            closes_5m=closes_5m, highs_5m=highs_5m, lows_5m=lows_5m,
            closes_h1=_h1c, highs_h1=_h1h, lows_h1=_h1l,
            closes_h4=_h4c, highs_h4=_h4h, lows_h4=_h4l,
            briefing_levels=_ff_briefing_levels(sym_u),
            session_state=_ff_session_state(),
            news_state=_ff_news_state(ccys),
            pip_size=pip_size,
        )
        write_forensic_fire(
            strategy=strategy,
            direction=norm_dir,
            entry_price=float(entry_price),
            fire_bar_ts=fire_bar_ts,
            snapshot_dict=snap,
            block_reason=block_reason,
            fire_path=fire_path,
            pair=sym_u,
        )
    except Exception as exc:  # noqa: BLE001 — never raise from this helper
        try:
            logger.warning(
                "[forensic_logger] %s capture_fire_from_df failed (%s): %s",
                sym, fire_path, exc,
            )
        except Exception:
            pass
