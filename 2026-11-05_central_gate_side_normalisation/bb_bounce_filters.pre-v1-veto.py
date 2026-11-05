"""bb_bounce_filters.py — Session 4 §3-§5 BB_BOUNCE filter chain.

Three admission filters for the GBPUSD BB_BOUNCE bounce engine, plus the
decision-log writer. Every filter is default-OFF; a filter whose flag is
0 is a byte-identical no-op (TAKEN / "disabled"). The flags are:

  * BB_BOUNCE_CLOSEBACK_ENABLED       — §3 close-back rule
  * BB_BOUNCE_V1_PRESSURE_ENABLED     — §4 USD/GBP pressure signal
  * BB_BOUNCE_DOLLAR_DIRECTION_ENABLED — §5 DXY dollar-direction filter
  * BB_BOUNCE_DECISION_LOG_ENABLED    — §5 bb_bounce_decisions.jsonl

Pipeline order (apply_filters):

    1. close-back  — refuse if the recent pierce has not closed back inside.
    2. V1 pressure — refuse against the implied GBPUSD direction.
    3. dollar dir  — refuse against the DXY-implied direction.

Each refusal names its binding rule; the decision log captures enough
context (time, side, candidate price, close-back state, V1 USD / GBP /
expected direction, dollar filter reading, stale flags, outcome,
refusing rule) to grade refused candidates later.

The module is a self-contained seam. It does NOT import gbpusd_bb_bounce
or trade_executor; integration lives in gbpusd_bb_bounce.py. All file IO
is contained in dedicated helpers so tests can inject fakes.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("AutoBot")

# ── Flag helpers ──────────────────────────────────────────────────────

def _env_bool(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default) or default).strip().lower() in (
        "1", "true", "yes", "on",
    )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def closeback_enabled() -> bool:
    return _env_bool("BB_BOUNCE_CLOSEBACK_ENABLED", "0")


def v1_pressure_enabled() -> bool:
    return _env_bool("BB_BOUNCE_V1_PRESSURE_ENABLED", "0")


def dollar_direction_enabled() -> bool:
    return _env_bool("BB_BOUNCE_DOLLAR_DIRECTION_ENABLED", "0")


def decision_log_enabled() -> bool:
    return _env_bool("BB_BOUNCE_DECISION_LOG_ENABLED", "0")


# ─────────────────────────────────────────────────────────────────────
# §3 — Close-back rule
# ─────────────────────────────────────────────────────────────────────
#
# "Entry allowed only after a 5m bar CLOSES back inside the band
# following a pierce on the trade's side within the last 12 bars.
# BUY: low < lower band, then a later close > lower band. SELL: mirror."
#
# States:
#   * BEFORE_CLOSEBACK — no pierce in window.                   → allow
#   * AFTER_CLOSEBACK  — pierce AND a later bar closed inside.  → allow
#   * NO_CLOSEBACK_YET — pierce but no close-back since pierce. → refuse
#
# `bars` is the strategy's rolling 5m window; `closes_ind` is the
# aligned close series the strategy uses to compute Bollinger bands.
# The candidate bar is the LAST element of each. The lookback runs
# over the 12 bars BEFORE the candidate (so the candidate itself is
# never counted as a pierce).

CLOSEBACK_BEFORE   = "BEFORE_CLOSEBACK"
CLOSEBACK_AFTER    = "AFTER_CLOSEBACK"
CLOSEBACK_PENDING  = "NO_CLOSEBACK_YET"

_DEFAULT_LOOKBACK_BARS = 12
_BB_PERIOD_FOR_LOOKBACK = 20


def _bb_lower_upper(closes: Sequence[float]) -> Tuple[float, float]:
    """Classic BB(20, 2) from a close series. Mirror of
    `gbpusd_bb_bounce._bb_20_2` kept inline so this module has no
    import coupling to the strategy."""
    import statistics
    if len(closes) < _BB_PERIOD_FOR_LOOKBACK:
        raise ValueError("need at least 20 closes")
    window = list(closes[-_BB_PERIOD_FOR_LOOKBACK:])
    mid = sum(window) / float(_BB_PERIOD_FOR_LOOKBACK)
    std = statistics.pstdev(window)
    return mid - 2.0 * std, mid + 2.0 * std


def closeback_state(
    side: str,
    bars: Sequence[Any],
    closes_ind: Sequence[float],
    *,
    lookback_bars: Optional[int] = None,
) -> Dict[str, Any]:
    """Return the close-back state at entry.

    Call this with ``bars`` ending at the LAST CLOSED bar before entry
    — i.e. ``bars[-1]`` is bar N where entry is placed at bar N+1.
    The agreed definition (operator ruling 2026-10-06) counts bar N
    itself as a valid close-back bar: "pierce on bar N-1, close back
    inside on bar N, entry at N+1 = AFTER_CLOSEBACK".

    Shape::

        { "state": BEFORE_CLOSEBACK / AFTER_CLOSEBACK / NO_CLOSEBACK_YET,
          "lookback_bars": int,
          "pierce_idx": Optional[int],  # bar offset back from entry
                                        # (0 = bars[-1] = signal bar N)
          "closeback_idx": Optional[int],
          "reason": str }

    ``side`` accepts BUY / LONG for a long trade and SELL / SHORT for
    short. The function never raises — on insufficient data it returns
    BEFORE_CLOSEBACK with ``reason="insufficient_bars"``; the caller
    treats that as a non-blocking neutral state (same as "no pierce").
    """
    lb = int(lookback_bars or _DEFAULT_LOOKBACK_BARS)
    direction = str(side or "").upper()
    is_long = direction in ("BUY", "LONG")
    is_short = direction in ("SELL", "SHORT")
    if not (is_long or is_short):
        return {
            "state": CLOSEBACK_BEFORE,
            "lookback_bars": lb,
            "pierce_idx": None,
            "closeback_idx": None,
            "reason": "unknown_side",
        }
    # Need enough bars for the BB computation at the oldest pierce
    # candidate position: BB uses the 20 closes ending at that bar.
    need = _BB_PERIOD_FOR_LOOKBACK + lb
    if len(bars) < lb + 1 or len(closes_ind) < need:
        return {
            "state": CLOSEBACK_BEFORE,
            "lookback_bars": lb,
            "pierce_idx": None,
            "closeback_idx": None,
            "reason": "insufficient_bars",
        }

    # Scan the lookback window (the candidate's entry is at bars[0]
    # of the NEXT bar; bars[-1] is the LAST CLOSED bar before entry
    # and is a valid close-back bar — "pierce on bar N-1, close-back
    # inside on bar N, entry at N+1 = AFTER_CLOSEBACK", operator
    # ruling 2026-10-06). Pierce bars are bars[-13 .. -1]; close-back
    # bars are bars[-13 .. -1] too, with the constraint that the
    # close-back offset `k < pierce_idx` (close-back strictly after
    # pierce). BB at each bar is computed from the 20 closes ENDING
    # at that bar.
    pierce_idx: Optional[int] = None
    closeback_idx: Optional[int] = None
    # Iterate from oldest to newest so the first pierce we see is the
    # earliest one in the window; after it we scan forward for a
    # close-back that lands AFTER the pierce.
    for k in range(lb, -1, -1):  # offsets lb, lb-1, ..., 1, 0
        bar = bars[-1 - k]
        # closes_ind up to and including this bar:
        bb_series = closes_ind[:len(closes_ind) - k]
        if len(bb_series) < _BB_PERIOD_FOR_LOOKBACK:
            continue
        try:
            lo, hi = _bb_lower_upper(bb_series)
        except ValueError:
            continue
        low = float(getattr(bar, "low"))
        high = float(getattr(bar, "high"))
        close = float(getattr(bar, "close"))
        if is_long:
            # Pierce: wick poked through the lower band.
            if pierce_idx is None and low < lo:
                pierce_idx = k
                continue
            # Close-back: a later close ends up above the lower band.
            if pierce_idx is not None and k < pierce_idx and close > lo:
                closeback_idx = k
                break
        else:  # SHORT
            if pierce_idx is None and high > hi:
                pierce_idx = k
                continue
            if pierce_idx is not None and k < pierce_idx and close < hi:
                closeback_idx = k
                break

    if pierce_idx is None:
        return {
            "state": CLOSEBACK_BEFORE,
            "lookback_bars": lb,
            "pierce_idx": None,
            "closeback_idx": None,
            "reason": "no_pierce_in_window",
        }
    if closeback_idx is None:
        return {
            "state": CLOSEBACK_PENDING,
            "lookback_bars": lb,
            "pierce_idx": pierce_idx,
            "closeback_idx": None,
            "reason": "pierce_without_closeback",
        }
    return {
        "state": CLOSEBACK_AFTER,
        "lookback_bars": lb,
        "pierce_idx": pierce_idx,
        "closeback_idx": closeback_idx,
        "reason": "pierce_then_closeback",
    }


# ─────────────────────────────────────────────────────────────────────
# §4 — V1 pressure signal
# ─────────────────────────────────────────────────────────────────────
#
# USD = -(EURUSD % change from FX-day open), GBP = +(GBPUSD % change
# from FX-day open). Expected GBPUSD direction = sign(GBP - USD).
# FX-day open is 17:00 America/New_York (DST-aware). Stale pair,
# missing open bar, or an exactly-zero computed value → UNKNOWN.

V1_UNKNOWN = "UNKNOWN"
V1_WITH    = "WITH"
V1_AGAINST = "AGAINST"


_CANDLE_ARCHIVE_ROOT = Path(
    os.getenv("CANDLE_ARCHIVE_ROOT", "/opt/tradingbot/data/candles")
)


_FX_DAY_OPEN_GRACE_HOURS = int(os.getenv("V1_FX_DAY_OPEN_GRACE_HOURS", "4"))


def _read_fx_day_open_bar(
    root: Path,
    pair: str,
    open_utc: datetime,
) -> Optional[Dict[str, float]]:
    """Return the FX-day-open bar for ``pair``.

    Agreed definition (operator ruling 2026-10-06): "from the 17:00 NY
    FX-day open to the last closed bar". The 17:00 NY boundary lands
    on a Sunday for Monday trading days (markets closed until the
    Sunday-evening reopen) and on each prior trading day for Tue–Fri
    fills.

    Resolution order:
      1. Look in ``<root>/<PAIR>/<open_date>.csv`` for the FIRST bar
         whose timestamp is ``>= open_utc`` and ``< open_utc +
         V1_FX_DAY_OPEN_GRACE_HOURS`` (default 4 hours). Covers the
         common Sunday-reopen pattern where the first bar lands at
         ~22:00 UTC rather than exactly 21:00 UTC.
      2. If the open-date file is missing or has no bar in that window,
         walk forward to the next calendar day's file and pick the
         first bar there (still within the grace window).

    Returns ``None`` when neither file produces a bar in the window.
    Uses the SAME CSV reader as the rest of this module (ts/O/H/L/C
    schema; UTC-aware).
    """
    cutoff = open_utc + timedelta(hours=max(1, _FX_DAY_OPEN_GRACE_HOURS))
    for lookahead_days in (0, 1):
        day = (open_utc + timedelta(days=lookahead_days)).strftime("%Y-%m-%d")
        path = root / pair.upper() / f"{day}.csv"
        if not path.exists():
            continue
        try:
            raw_lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for raw in raw_lines:
            if not raw or raw.startswith("timestamp,"):
                continue
            parts = raw.split(",")
            if len(parts) < 5:
                continue
            try:
                ts = datetime.fromisoformat(parts[0])
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < open_utc or ts >= cutoff:
                continue
            try:
                return {
                    "ts": ts,
                    "open":  float(parts[1]),
                    "high":  float(parts[2]),
                    "low":   float(parts[3]),
                    "close": float(parts[4]),
                }
            except ValueError:
                return None
    return None


def _read_bar_at(path: Path, target_utc: datetime) -> Optional[Dict[str, float]]:
    """Return the first bar in ``path`` whose timestamp equals
    ``target_utc`` (UTC-aware). None if the file or row is missing.
    """
    try:
        if not path.exists():
            return None
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw or raw.startswith("timestamp,"):
                continue
            parts = raw.split(",")
            if len(parts) < 5:
                continue
            try:
                ts = datetime.fromisoformat(parts[0])
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts == target_utc:
                try:
                    return {
                        "ts": ts,
                        "open":  float(parts[1]),
                        "high":  float(parts[2]),
                        "low":   float(parts[3]),
                        "close": float(parts[4]),
                    }
                except ValueError:
                    return None
    except Exception:
        return None
    return None


def _read_last_closed_bar(path: Path) -> Optional[Dict[str, float]]:
    try:
        if not path.exists():
            return None
        last = None
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw or raw.startswith("timestamp,"):
                continue
            last = raw
        if last is None:
            return None
        parts = last.split(",")
        if len(parts) < 5:
            return None
        try:
            ts = datetime.fromisoformat(parts[0])
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return {
            "ts": ts,
            "open":  float(parts[1]),
            "high":  float(parts[2]),
            "low":   float(parts[3]),
            "close": float(parts[4]),
        }
    except Exception:
        return None


def _fx_day_start_utc(now_utc: datetime) -> datetime:
    """Reuse daily_loss_stop.fx_day_window so FX-day boundary (17:00 NY
    DST-aware) is one source of truth across the module."""
    import daily_loss_stop as _dls
    start_utc, _end_utc = _dls.fx_day_window(now_utc)
    return start_utc


def _pct_change(open_px: float, close_px: float) -> float:
    if open_px == 0:
        return 0.0
    return (close_px - open_px) / open_px * 100.0


def v1_pressure_signal(
    side: str,
    now_utc: datetime,
    *,
    candle_root: Optional[Path] = None,
    candle_freshness_fn: Optional[Callable[[str, datetime], bool]] = None,
    read_open_bar_fn: Optional[Callable[[str, datetime], Optional[Dict[str, float]]]] = None,
    read_last_closed_bar_fn: Optional[Callable[[str, datetime], Optional[Dict[str, float]]]] = None,
) -> Dict[str, Any]:
    """Compute the V1 pressure signal for GBPUSD.

    Returns:
        { "state": WITH / AGAINST / UNKNOWN,
          "usd_pct": float | None,
          "gbp_pct": float | None,
          "expected_direction": "BUY" | "SELL" | "FLAT" | None,
          "stale_gbpusd": bool,
          "stale_eurusd": bool,
          "reason": str }

    Any of the following forces UNKNOWN:
      * candle_freshness.is_stale(EURUSD or GBPUSD) is True
      * EURUSD % change is EXACTLY zero (per spec)
      * GBPUSD % change is EXACTLY zero
      * FX-day open bar missing for either pair
    """
    direction = str(side or "").upper()
    if direction in ("BUY", "LONG"):
        trade_sign = +1
    elif direction in ("SELL", "SHORT"):
        trade_sign = -1
    else:
        return {
            "state": V1_UNKNOWN,
            "usd_pct": None, "gbp_pct": None,
            "expected_direction": None,
            "stale_gbpusd": False, "stale_eurusd": False,
            "reason": "unknown_side",
        }

    root = Path(candle_root) if candle_root is not None else _CANDLE_ARCHIVE_ROOT

    def _is_stale(pair: str) -> bool:
        if candle_freshness_fn is not None:
            return bool(candle_freshness_fn(pair, now_utc))
        try:
            import candle_freshness as _cf
            return bool(_cf.is_stale(pair, now=now_utc))
        except Exception:
            return True  # treat failure as stale → UNKNOWN

    stale_e = _is_stale("EURUSD")
    stale_g = _is_stale("GBPUSD")
    if stale_e or stale_g:
        return {
            "state": V1_UNKNOWN,
            "usd_pct": None, "gbp_pct": None,
            "expected_direction": None,
            "stale_gbpusd": stale_g, "stale_eurusd": stale_e,
            "reason": "stale",
        }

    open_utc = _fx_day_start_utc(now_utc)
    open_file_date = open_utc.strftime("%Y-%m-%d")
    now_file_date = now_utc.strftime("%Y-%m-%d")

    def _read_open(pair: str) -> Optional[Dict[str, float]]:
        if read_open_bar_fn is not None:
            return read_open_bar_fn(pair, open_utc)
        # Agreed definition (2026-10-06): the FX-day open is the FIRST
        # bar at or after 17:00 NY (within a small grace window). The
        # Sunday-reopen pattern — where the first bar lands at ~22:00
        # UTC rather than exactly 21:00 UTC — is covered without
        # fabricating a value.
        return _read_fx_day_open_bar(root, pair, open_utc)

    def _read_last(pair: str) -> Optional[Dict[str, float]]:
        if read_last_closed_bar_fn is not None:
            return read_last_closed_bar_fn(pair, now_utc)
        return _read_last_closed_bar(
            root / pair.upper() / f"{now_file_date}.csv",
        )

    e_open = _read_open("EURUSD")
    g_open = _read_open("GBPUSD")
    if e_open is None or g_open is None:
        return {
            "state": V1_UNKNOWN,
            "usd_pct": None, "gbp_pct": None,
            "expected_direction": None,
            "stale_gbpusd": stale_g, "stale_eurusd": stale_e,
            "reason": "fx_day_open_missing",
        }

    e_last = _read_last("EURUSD")
    g_last = _read_last("GBPUSD")
    if e_last is None or g_last is None:
        return {
            "state": V1_UNKNOWN,
            "usd_pct": None, "gbp_pct": None,
            "expected_direction": None,
            "stale_gbpusd": stale_g, "stale_eurusd": stale_e,
            "reason": "last_bar_missing",
        }

    eur_pct = _pct_change(e_open["open"], e_last["close"])
    gbp_pct = _pct_change(g_open["open"], g_last["close"])

    # Spec §4: "exactly 0 → UNKNOWN → refuse"
    if eur_pct == 0.0 or gbp_pct == 0.0:
        return {
            "state": V1_UNKNOWN,
            "usd_pct": -eur_pct if eur_pct != 0.0 else 0.0,
            "gbp_pct": gbp_pct,
            "expected_direction": None,
            "stale_gbpusd": stale_g, "stale_eurusd": stale_e,
            "reason": "zero_pct_component",
        }

    usd_pct = -eur_pct
    delta = gbp_pct - usd_pct
    if delta > 0:
        expected = "BUY"
        expected_sign = +1
    elif delta < 0:
        expected = "SELL"
        expected_sign = -1
    else:
        return {
            "state": V1_UNKNOWN,
            "usd_pct": usd_pct, "gbp_pct": gbp_pct,
            "expected_direction": "FLAT",
            "stale_gbpusd": stale_g, "stale_eurusd": stale_e,
            "reason": "flat_delta",
        }

    state = V1_WITH if expected_sign == trade_sign else V1_AGAINST
    return {
        "state": state,
        "usd_pct": usd_pct,
        "gbp_pct": gbp_pct,
        "expected_direction": expected,
        "stale_gbpusd": stale_g, "stale_eurusd": stale_e,
        "reason": "ok",
    }


# ─────────────────────────────────────────────────────────────────────
# §5 — Dollar-direction filter (DXY)
# ─────────────────────────────────────────────────────────────────────
#
# Reuses commit 7394e28's ig_daily_pivots.read_dollar_direction. DXY UP
# → implied GBPUSD DOWN, so SELL is WITH and BUY is AGAINST (and
# conversely for DXY DOWN).

DOLLAR_WITH    = "WITH"
DOLLAR_AGAINST = "AGAINST"
DOLLAR_UNKNOWN = "UNKNOWN"


def dollar_direction_signal(
    side: str,
    now_utc: datetime,
    *,
    read_dollar_direction_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Return WITH / AGAINST / UNKNOWN for the DXY-implied GBPUSD
    direction vs ``side``.

    DXY `UP` → implied GBPUSD DOWN → SELL is WITH, BUY is AGAINST.
    DXY `DOWN` → implied GBPUSD UP → BUY is WITH, SELL is AGAINST.
    DXY `FLAT` or absent surface → UNKNOWN (refuse).
    """
    direction = str(side or "").upper()
    if direction in ("BUY", "LONG"):
        trade_sign = +1
    elif direction in ("SELL", "SHORT"):
        trade_sign = -1
    else:
        return {
            "state": DOLLAR_UNKNOWN,
            "dxy_direction": None,
            "implied_gbpusd_direction": None,
            "reason": "unknown_side",
        }

    trading_date = now_utc.astimezone(timezone.utc).strftime("%Y-%m-%d")
    try:
        if read_dollar_direction_fn is not None:
            block = read_dollar_direction_fn(trading_date)
        else:
            import ig_daily_pivots as _idp
            block = _idp.read_dollar_direction(trading_date)
    except Exception as exc:  # noqa: BLE001 — resilient
        logger.warning("[BB_BOUNCE_DOLLAR] read_dollar_direction raised: %s", exc)
        block = None

    if not block:
        return {
            "state": DOLLAR_UNKNOWN,
            "dxy_direction": None,
            "implied_gbpusd_direction": None,
            "reason": "surface_absent",
        }

    dxy = str(block.get("dxy_direction") or "").upper()
    implied = str(block.get("implied_gbpusd_direction") or "").upper()
    if dxy not in ("UP", "DOWN"):
        return {
            "state": DOLLAR_UNKNOWN,
            "dxy_direction": dxy or None,
            "implied_gbpusd_direction": implied or None,
            "reason": "flat_or_missing_direction",
        }
    implied_sign = +1 if implied == "UP" else -1 if implied == "DOWN" else 0
    if implied_sign == 0:
        return {
            "state": DOLLAR_UNKNOWN,
            "dxy_direction": dxy,
            "implied_gbpusd_direction": implied or None,
            "reason": "implied_missing",
        }
    state = DOLLAR_WITH if implied_sign == trade_sign else DOLLAR_AGAINST
    return {
        "state": state,
        "dxy_direction": dxy,
        "implied_gbpusd_direction": implied,
        "reason": "ok",
    }


# ─────────────────────────────────────────────────────────────────────
# Pipeline + decision log
# ─────────────────────────────────────────────────────────────────────

_DEFAULT_DECISION_LOG = Path(
    os.getenv("BB_BOUNCE_DECISION_LOG_PATH", "/opt/tradingbot/logs/bb_bounce_decisions.jsonl")
)


def _write_decision_row(row: Dict[str, Any], *, path: Optional[Path] = None) -> None:
    """Append ``row`` as one JSON line to the decision log. Silent on
    IO error — logging must never block an evaluate() call."""
    if not decision_log_enabled():
        return
    target = Path(path) if path is not None else _DEFAULT_DECISION_LOG
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001 — resilient
        logger.warning("[BB_BOUNCE_DECISION_LOG] write failed: %s", exc)


OUTCOME_TAKEN   = "TAKEN"
OUTCOME_REFUSED = "REFUSED"


def apply_filters(
    *,
    side: str,
    ts_utc: datetime,
    candidate_price: float,
    bars: Sequence[Any],
    closes_ind: Sequence[float],
    log_path: Optional[Path] = None,
    zone_info: Optional[Dict[str, Any]] = None,
    # Injection hooks for tests:
    closeback_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    v1_pressure_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    dollar_direction_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    write_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Run close-back → V1 pressure → dollar-direction, in that order.

    Each filter is a byte-identical no-op when its flag is OFF. The
    first filter that refuses wins; the remaining filters are still
    computed for the decision log so the operator sees why the trade
    would have been refused by downstream filters too — this makes
    "would-also-have-refused" grading possible from the log alone.

    Returns a record identical to the one written to the log:

      { "ts_utc": "...", "side": "BUY|SELL", "candidate_price": float,
        "close_back": {...}, "v1_pressure": {...},
        "dollar_direction": {...}, "outcome": TAKEN|REFUSED,
        "refusing_rule": None | "close_back_no_closeback_yet" |
                         "v1_pressure_against" | "v1_pressure_unknown" |
                         "dollar_direction_against" | "dollar_direction_unknown",
        "flags": {"closeback": bool, "v1_pressure": bool,
                  "dollar_direction": bool} }
    """
    cb = (closeback_fn or closeback_state)(
        side=side, bars=bars, closes_ind=closes_ind,
    )
    v1 = (v1_pressure_fn or v1_pressure_signal)(
        side=side, now_utc=ts_utc,
    )
    dd = (dollar_direction_fn or dollar_direction_signal)(
        side=side, now_utc=ts_utc,
    )

    cb_on = closeback_enabled()
    v1_on = v1_pressure_enabled()
    dd_on = dollar_direction_enabled()

    refusing_rule: Optional[str] = None
    if cb_on and cb.get("state") == CLOSEBACK_PENDING:
        refusing_rule = "close_back_no_closeback_yet"
    elif v1_on and v1.get("state") == V1_UNKNOWN:
        refusing_rule = "v1_pressure_unknown"
    elif v1_on and v1.get("state") == V1_AGAINST:
        refusing_rule = "v1_pressure_against"
    elif dd_on and dd.get("state") == DOLLAR_UNKNOWN:
        refusing_rule = "dollar_direction_unknown"
    elif dd_on and dd.get("state") == DOLLAR_AGAINST:
        refusing_rule = "dollar_direction_against"

    outcome = OUTCOME_REFUSED if refusing_rule else OUTCOME_TAKEN
    row = {
        "ts_utc": ts_utc.astimezone(timezone.utc).isoformat()
                   if ts_utc.tzinfo else ts_utc.replace(tzinfo=timezone.utc).isoformat(),
        "side": str(side or "").upper(),
        "candidate_price": float(candidate_price),
        "close_back": cb,
        "v1_pressure": v1,
        "dollar_direction": dd,
        "outcome": outcome,
        "refusing_rule": refusing_rule,
        "flags": {
            "closeback": cb_on,
            "v1_pressure": v1_on,
            "dollar_direction": dd_on,
        },
        # Build-2 Phase 4: zone context attached verbatim when the view
        # is enabled; absent (view_status="ABSENT") when VIEW_ENABLED=0.
        "zone_info": zone_info or {
            "view_status": "ABSENT",
            "in_zone": False,
            "zone": None,
            "zones_above_count": 0,
            "zones_below_count": 0,
            "band_confluent": False,
        },
    }
    if write_fn is not None:
        try:
            write_fn(row)
        except Exception as exc:  # noqa: BLE001 — tests inject raisers
            logger.warning("[BB_BOUNCE_DECISION_LOG] inject-write failed: %s", exc)
    else:
        _write_decision_row(row, path=log_path)
    return row


# ─── test seams ───────────────────────────────────────────────────────

def _reset_decision_log_path_for_tests(path: Path) -> None:
    """Rebind the default decision-log path. Tests only."""
    global _DEFAULT_DECISION_LOG
    _DEFAULT_DECISION_LOG = Path(path)
