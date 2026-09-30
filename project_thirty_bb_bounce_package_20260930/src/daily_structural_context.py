#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_structural_context.py — M5 consumer surface + readiness authority.

Single validated surface for strategies that require the daily-fixed
structural level family (PIVOT, PDH, PDL, R1/R2/R3, S1/S2/S3).

Layers on top of the accepted chain:

  M0-M3   4b354f4  H4 persistence + reconstruction
  fa18a90 fa18a90  authoritative previous-completed-D1 selector
  783eb0e 783eb0e  5D/20D weekend-fragment guard
  M4      4bf3e55  persisted daily structural snapshot (dark-wired)
  M4_CLOSURE ed294b7 combined weekend boot + allowance proof

M5 does NOT introduce a new persistence format, a new prior-D1 selector,
or a new pivot formula. It reads the M4 snapshot via
:func:`daily_snapshot.load_snapshot_if_valid` and wraps it in a
consumer-facing readiness contract so context-required strategies can
fail closed on missing/stale/corrupt/wrong-identity snapshots.

Feature flag — ``DAILY_STRUCTURAL_CONTEXT_ENABLED`` (default ``"0"``):

  When OFF: :func:`is_enabled` returns False; :func:`require` returns
  a "pass-through" readiness (ok=True, no context) — every migrated
  strategy behaves byte-identical to the pre-M5 chain, still routing
  through ``bb_pd_gate.compute_pd_pct`` / ``compute_pivots_only``.

  When ON: :func:`require` calls
  :func:`daily_snapshot.load_snapshot_if_valid` for the given
  ``symbol`` + ``trading_date`` + ``epic``; an invalid load returns
  ok=False with an explicit reason code and the strategy MUST abstain.

Trading-date discipline (§9 of the M5 ruling): callers pass their
existing ``fire_ts.astimezone(timezone.utc).date()`` — production
strategies already use wall-clock UTC everywhere. M5 does NOT redesign
trading-date semantics. The Sunday 22:00-24:00 UTC seam remains
handled by the existing weekday + entry-hours strategy gates; if
those gates fail to block, the M5 readiness gate will also block
(load_snapshot_if_valid on a Sunday returns None with
schema_version_mismatch/trading_date_mismatch/snapshot_missing
because M4 refuses to create a Sunday snapshot).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("AutoBot")

_FLAG_ENV_VAR = "DAILY_STRUCTURAL_CONTEXT_ENABLED"

_REASON_M5_OFF                = "m5_off"
_REASON_LOAD_ERROR            = "load_error"
_REASON_BAD_TRADING_DATE      = "bad_trading_date"


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    """M5 consumer-side authority. Default OFF."""
    v = (os.getenv(_FLAG_ENV_VAR, "0") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DailyStructuralContext:
    """Immutable snapshot of the daily-fixed structural level set for
    one symbol on one trading date. Every level in ``levels`` was
    computed from the SAME source D1 bar identified by
    ``source_d1_timestamp`` (M4's single-source-of-truth invariant).
    """
    epic:                  Optional[str]
    symbol:                str
    trading_date:          date
    previous_trading_date: date
    source_d1_timestamp:   str            # ISO-8601 UTC
    levels:                Dict[str, float]
    calculated_at:         str            # ISO-8601 UTC — telemetry only

    def level(self, name: str) -> float:
        """Convenience accessor with a stable KeyError message."""
        try:
            return self.levels[name]
        except KeyError:
            raise KeyError(
                f"level {name!r} not present in daily structural context "
                f"for {self.symbol} on {self.trading_date}"
            )


@dataclass(frozen=True)
class DailyContextReadiness:
    """Return value from :func:`require`.

    ``ok`` is True when either:
      - M5 is disabled (pass-through — the strategy proceeds through
        its legacy code path)
      - M5 is enabled AND ``context`` is a valid, non-stale, non-corrupt
        daily structural context.

    ``ok`` is False when M5 is enabled and the M4 snapshot loader
    reported any invalidation. ``reason`` mirrors the M4 loader's
    reason code (schema_version_mismatch, trading_date_mismatch,
    epic_mismatch, symbol_mismatch, mixed_source_level:{K},
    non_finite_level:{K}, missing_level:{K}, snapshot_missing,
    snapshot_read_error:{cls}, previous_trading_date_source_mismatch,
    …) so migrated strategies can emit distinct telemetry lines
    per failure class.

    ``context`` is populated only when ``ok`` is True AND M5 is
    enabled. When M5 is disabled, ``context`` is None and the strategy
    is expected to use its existing bb_pd_gate calls.
    """
    ok:      bool
    reason:  str
    context: Optional[DailyStructuralContext] = None


# ---------------------------------------------------------------------------
# Coercion helper — accepts date / datetime / ISO string
# ---------------------------------------------------------------------------

def _coerce_trading_date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        vv = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return vv.astimezone(timezone.utc).date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return datetime.strptime(v[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get(
    symbol:       str,
    trading_date: Any,
    epic:         Optional[str] = None,
) -> DailyContextReadiness:
    """Load a validated daily structural context, independent of the
    feature flag. Callers that want strict-load semantics (e.g. a
    diagnostic shadow surface) can use this; the M5 gate uses
    :func:`require` which respects the flag.
    """
    td = _coerce_trading_date(trading_date)
    if td is None:
        return DailyContextReadiness(ok=False, reason=_REASON_BAD_TRADING_DATE)
    try:
        import daily_snapshot as _ds
    except Exception as exc:  # pragma: no cover — defensive
        return DailyContextReadiness(
            ok=False, reason=f"{_REASON_LOAD_ERROR}:{exc.__class__.__name__}",
        )
    snap, reason = _ds.load_snapshot_if_valid(symbol, td, epic=epic)
    if snap is None:
        return DailyContextReadiness(ok=False, reason=reason)
    try:
        ctx = DailyStructuralContext(
            epic                  = snap.get("epic"),
            symbol                = str(snap.get("symbol") or symbol).upper(),
            trading_date          = _coerce_trading_date(snap["trading_date"]) or td,
            previous_trading_date = _coerce_trading_date(snap["previous_trading_date"]) or td,
            source_d1_timestamp   = str(snap["source_d1_timestamp"]),
            levels                = {k: float(v) for k, v in
                                     (snap.get("levels") or {}).items()},
            calculated_at         = str(snap.get("calculated_at") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return DailyContextReadiness(
            ok=False, reason=f"{_REASON_LOAD_ERROR}:{exc.__class__.__name__}",
        )
    return DailyContextReadiness(ok=True, reason="ok", context=ctx)


def require(
    symbol:       str,
    trading_date: Any,
    epic:         Optional[str] = None,
) -> DailyContextReadiness:
    """M5 readiness gate for context-required strategies.

    - When ``DAILY_STRUCTURAL_CONTEXT_ENABLED`` is OFF (default),
      returns ``DailyContextReadiness(ok=True, reason="m5_off",
      context=None)`` — the caller proceeds through its legacy code
      path and behaviour is byte-identical to the pre-M5 chain.
    - When the flag is ON, delegates to :func:`get` and returns its
      readiness. The caller MUST abstain when ``ok is False``.

    Never raises. Any unexpected exception is caught and returned as
    ``ok=False, reason="load_error:<ExcClass>"`` so a migrated
    strategy that trusts this gate never crashes on unexpected M5
    internals.
    """
    if not is_enabled():
        return DailyContextReadiness(ok=True, reason=_REASON_M5_OFF)
    try:
        return get(symbol, trading_date, epic=epic)
    except Exception as exc:  # pragma: no cover — defensive
        return DailyContextReadiness(
            ok=False, reason=f"{_REASON_LOAD_ERROR}:{exc.__class__.__name__}",
        )


__all__ = [
    "is_enabled",
    "get",
    "require",
    "DailyStructuralContext",
    "DailyContextReadiness",
]
