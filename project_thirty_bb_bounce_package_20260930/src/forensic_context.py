"""forensic_context.py — context helpers for forensic_fire_snapshot.

Diagnostic-only. Each helper resolves a single piece of contextual data
(HTF candles, briefing levels, session, news) and is wrapped in
try/except so it NEVER raises. Failure modes return safe sentinels
(``None`` / empty dict / all-``None`` tuple) so the caller can pass the
result straight into ``indicators.forensic_fire_snapshot`` and let the
snapshot's per-axis ``_safe`` wrappers handle missing inputs.

Phase 2f wiring: called from each of the 4 strategies' forensic-capture
blocks (gbpusd_trend_continuation, gbpusd_bb_bounce,
gbpusd_bb_reversal_patterns, briefing_execution). Lifts data plumbing
out of those strategies and centralises it here so future schema drift
(e.g. additional briefing fields, news shape changes) lands in one
place.

Soft-fail invariant: every public function returns even if the caller's
process is mid-shutdown, the cache is corrupt, or upstream modules are
unimportable. Exceptions surface only as a single WARNING log line via
the AutoBot logger, never via raise.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AutoBot")

# Session boundaries in UTC. Single-canonical source — used by
# session_state_now and any future caller that needs the same map.
# Asian rolls overnight (22:00 → 08:00); London/NY are intra-day.
# Overlap windows resolve by priority: NY > London > Asian (matches
# trader convention — the "active" session is the most recently opened
# liquidity window).
_SESSIONS = (
    # (name, start_h, end_h)  — `end_h` is exclusive; if end < start the
    # window wraps midnight UTC (used for Asian).
    ("NY",     12, 21),   # 12:00–21:00 UTC
    ("London",  7, 16),   # 07:00–16:00 UTC
    ("Asian",  22,  8),   # 22:00–08:00 UTC (wraps)
)


def _safe_warn(msg: str, *args: Any) -> None:
    """Internal: warning-log without raising even if logger is misconfigured."""
    try:
        logger.warning(msg, *args)
    except Exception:
        pass


# ─── HTF series ───────────────────────────────────────────────────────────
def load_htf_series(
    sym: str,
) -> Tuple[Any, Any, Any, Any, Any, Any]:
    """Return ``(closes_h1, highs_h1, lows_h1, closes_h4, highs_h4, lows_h4)``
    as ``pd.Series`` from cached H1 candles, with H4 resampled from H1.

    Reads ``htf_cache.load_cached_candles(sym, "H1")``. H4 is resampled
    with ``origin='start_day'`` so bars align to 00:00 / 04:00 / 08:00 /
    12:00 / 16:00 / 20:00 UTC — matching IG charts.

    Returns a 6-tuple of ``None`` on any failure (missing cache,
    corrupt data, missing pandas, anything).
    """
    none_tuple: Tuple[Any, Any, Any, Any, Any, Any] = (
        None, None, None, None, None, None,
    )
    try:
        import pandas as pd
        from htf_cache import load_cached_candles

        cached = load_cached_candles(sym, "H1")
        if not cached:
            return none_tuple
        candles = cached.get("candles") or []
        if not candles:
            return none_tuple

        # Build a tz-aware UTC DataFrame from the candle list.
        ts_index = pd.DatetimeIndex(
            [pd.Timestamp(c["timestamp"]) for c in candles]
        )
        if getattr(ts_index, "tz", None) is None:
            ts_index = ts_index.tz_localize("UTC")
        else:
            ts_index = ts_index.tz_convert("UTC")
        df_h1 = pd.DataFrame({
            "open":  [float(c["open"])  for c in candles],
            "high":  [float(c["high"])  for c in candles],
            "low":   [float(c["low"])   for c in candles],
            "close": [float(c["close"]) for c in candles],
        }, index=ts_index)

        closes_h1 = df_h1["close"].reset_index(drop=True)
        highs_h1  = df_h1["high"].reset_index(drop=True)
        lows_h1   = df_h1["low"].reset_index(drop=True)

        # Resample to H4 aligned to 00:00 UTC daily boundaries.
        # origin='start_day' makes bars start at 00:00 of each day,
        # producing 04h buckets at 00, 04, 08, 12, 16, 20 UTC.
        try:
            df_h4 = df_h1.resample("4H", origin="start_day").agg({
                "open":  "first",
                "high":  "max",
                "low":   "min",
                "close": "last",
            }).dropna(how="any")
            closes_h4 = df_h4["close"].reset_index(drop=True)
            highs_h4  = df_h4["high"].reset_index(drop=True)
            lows_h4   = df_h4["low"].reset_index(drop=True)
        except Exception as exc:
            _safe_warn(
                "[forensic_context] H4 resample failed for %s: %s", sym, exc,
            )
            closes_h4 = highs_h4 = lows_h4 = None

        return (closes_h1, highs_h1, lows_h1, closes_h4, highs_h4, lows_h4)
    except Exception as exc:  # noqa: BLE001 — never raise
        _safe_warn("[forensic_context] load_htf_series(%s) failed: %s", sym, exc)
        return none_tuple


# ─── Briefing levels ──────────────────────────────────────────────────────
def briefing_levels_for_sym(sym: str) -> Optional[List[Dict[str, Any]]]:
    """Return the briefing-level pool for ``sym`` as a list of dicts:
    ``{price, level_type, source, major}``. Built from
    ``key_levels`` / ``major_levels`` / ``liquidity_pools`` of the active
    in-memory briefing — same shape that
    ``trade_manager.select_tp_levels`` consumes (and that the GBPUSD
    BB strategies already build inline). Returns ``None`` on failure or
    when no briefing is active.
    """
    try:
        from morning_briefing import get_briefing
        brief = get_briefing(sym)
        if not brief:
            return None
        levels: List[Dict[str, Any]] = []
        for src in ("key_levels", "major_levels"):
            d = brief.get(src) or {}
            major = (src == "major_levels")
            for v in (d.get("resistance") or []):
                if v is None:
                    continue
                try:
                    levels.append({
                        "price": float(v), "level_type": "resistance",
                        "source": src, "major": major,
                    })
                except (TypeError, ValueError):
                    continue
            for v in (d.get("support") or []):
                if v is None:
                    continue
                try:
                    levels.append({
                        "price": float(v), "level_type": "support",
                        "source": src, "major": major,
                    })
                except (TypeError, ValueError):
                    continue
        lp = brief.get("liquidity_pools") or {}
        for v in (lp.get("buy_side") or []):
            if v is None:
                continue
            try:
                levels.append({
                    "price": float(v), "level_type": "resistance",
                    "source": "liquidity_pools", "major": False,
                })
            except (TypeError, ValueError):
                continue
        for v in (lp.get("sell_side") or []):
            if v is None:
                continue
            try:
                levels.append({
                    "price": float(v), "level_type": "support",
                    "source": "liquidity_pools", "major": False,
                })
            except (TypeError, ValueError):
                continue
        return levels if levels else None
    except Exception as exc:  # noqa: BLE001 — never raise
        _safe_warn(
            "[forensic_context] briefing_levels_for_sym(%s) failed: %s",
            sym, exc,
        )
        return None


# ─── Session state ────────────────────────────────────────────────────────
def _session_for(now_utc: datetime) -> Optional[Tuple[str, int, int]]:
    """Return (name, start_h, end_h) of the active session at now_utc, or
    None if outside all defined windows. Iterates _SESSIONS in priority
    order (NY > London > Asian) so overlaps resolve to the latest-opened
    session."""
    h = now_utc.hour
    for name, start_h, end_h in _SESSIONS:
        if start_h < end_h:
            if start_h <= h < end_h:
                return (name, start_h, end_h)
        else:
            # Wraps midnight: in-window if h >= start OR h < end.
            if h >= start_h or h < end_h:
                return (name, start_h, end_h)
    return None


def session_state_now(now_utc: Optional[datetime] = None) -> Dict[str, Any]:
    """Return ``{name, minutes_since_open, minutes_until_close}`` for the
    currently-active UTC session.

    Boundaries hardcoded in ``_SESSIONS`` (Asian wraps midnight).
    Overlapping windows resolve to NY > London > Asian (most recently
    opened wins). Returns ``{}`` on any failure or if outside all windows.
    """
    try:
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        else:
            now_utc = now_utc.astimezone(timezone.utc)

        sess = _session_for(now_utc)
        if sess is None:
            return {}
        name, start_h, end_h = sess

        # Resolve concrete open/close timestamps anchored to today (or
        # yesterday for the Asian-overnight case).
        today = now_utc.replace(minute=0, second=0, microsecond=0, hour=0)
        if start_h < end_h:
            open_dt = today + timedelta(hours=start_h)
            close_dt = today + timedelta(hours=end_h)
        else:
            # Wraps: if current hour is before end_h, the session opened
            # YESTERDAY at start_h and closes TODAY at end_h. Else it
            # opened TODAY at start_h and closes TOMORROW at end_h.
            if now_utc.hour < end_h:
                open_dt = today + timedelta(hours=start_h - 24)
                close_dt = today + timedelta(hours=end_h)
            else:
                open_dt = today + timedelta(hours=start_h)
                close_dt = today + timedelta(hours=end_h + 24)

        mins_since = int((now_utc - open_dt).total_seconds() // 60)
        mins_until = int((close_dt - now_utc).total_seconds() // 60)
        return {
            "name": name,
            "minutes_since_open": max(0, mins_since),
            "minutes_until_close": max(0, mins_until),
        }
    except Exception as exc:  # noqa: BLE001 — never raise
        _safe_warn("[forensic_context] session_state_now failed: %s", exc)
        return {}


# ─── News state ───────────────────────────────────────────────────────────
def news_state_now(
    currencies: List[str],
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return ``{minutes_since_event, minutes_until_event, last_event,
    next_event}`` for high-impact events on the supplied currencies.

    Reads ``news_calendar.get_todays_events(currencies)`` (today UTC,
    high-impact filtered upstream). For each event, parses the ``HH:MM``
    time field, anchors it to today UTC, and computes the nearest past
    + nearest future. Past/future fields are ``None`` if no event in
    that direction. Returns ``{}`` on any failure.
    """
    try:
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        else:
            now_utc = now_utc.astimezone(timezone.utc)

        from news_calendar import get_todays_events
        events = get_todays_events(currencies=list(currencies)) or []
        if not events:
            return {}

        anchored: List[Tuple[datetime, Dict[str, Any]]] = []
        today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        for ev in events:
            t_str = str(ev.get("time") or "")
            try:
                hh, mm = map(int, t_str.split(":"))
            except (ValueError, AttributeError):
                continue
            ev_dt = today + timedelta(hours=hh, minutes=mm)
            anchored.append((ev_dt, ev))

        if not anchored:
            return {}

        past = [(dt, ev) for dt, ev in anchored if dt <= now_utc]
        future = [(dt, ev) for dt, ev in anchored if dt > now_utc]

        last_dt, last_ev = max(past, key=lambda t: t[0]) if past else (None, None)
        next_dt, next_ev = min(future, key=lambda t: t[0]) if future else (None, None)

        return {
            "minutes_since_event": (
                int((now_utc - last_dt).total_seconds() // 60)
                if last_dt is not None else None
            ),
            "minutes_until_event": (
                int((next_dt - now_utc).total_seconds() // 60)
                if next_dt is not None else None
            ),
            "last_event": last_ev,
            "next_event": next_ev,
        }
    except Exception as exc:  # noqa: BLE001 — never raise
        _safe_warn("[forensic_context] news_state_now failed: %s", exc)
        return {}
