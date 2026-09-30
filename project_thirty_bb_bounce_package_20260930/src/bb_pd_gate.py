"""bb_pd_gate — prior-day range position + classic pivots for BB_BOUNCE.

Pure-function helpers used by gbpusd_bb_bounce.py to compute pd_pct
(entry position within the prior-day range) and classic pivot levels
from the D1 HTF cache. Never raise; on any error return `pd_pct=None`
or `nearest=None` with a populated `reason`. Callers fail OPEN on
missing values.

pd_pct definition (matches bb_bounce_pdrange_direction_20260811.md and
bb_bounce_s_losers_20260811.md audits):

    pd_pct = 100 * (entry - PDL) / (PDH - PDL)

PDH / PDL come from the MOST RECENT COMPLETED D1 bar in
cache/htf/GBPUSD_D1.json whose timestamp is STRICTLY BEFORE the fire's
calendar date. This is a "prior completed bar" definition, not a
"yesterday-only" one:

  - Monday fires   → PDH/PDL are Friday's D1 high/low.
  - Weekend / holiday gap → PDH/PDL are the last completed D1 bar in
    the cache, even if that isn't yesterday's calendar date.
  - If (PDH - PDL) <= 0 → pd_pct = None, reason='degenerate_prior_range'.

Cache source: /opt/tradingbot/cache/htf/GBPUSD_D1.json
(managed by htf_cache.save_candles_to_cache; fresh threshold 24h per
htf_cache.D1_FRESH_THRESHOLD_SECS).

Stale/missing-cache handling (all fail OPEN — reason returned so the
gate log can record it, pd_pct is None so no suppression fires):

  - File missing / corrupt        → reason='cache_missing'
  - Empty candle list             → reason='cache_empty'
  - No candle with date < fire    → reason='no_prior_d1_bar'
  - Degenerate PDH-PDL <= 0       → reason='degenerate_prior_range'
  - Cache file read raises        → reason='cache_read_error:<exc>'

`days_gap` is set to `(fire_date - pd_source_date).days` so the caller
can log when the prior bar is unusually old (weekend/holiday: 3+ days).
"""

from __future__ import annotations

import logging
import os
import threading
import time as _time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("AutoBot")


# ─── D1-STALE-ANCHOR Telegram escalation (task 5) ─────────────────────
# The [D1-STALE-ANCHOR] warning was firing 239 times on 2026-08-21 with
# no operator-visible signal. Below promotes it to a Telegram once per
# hour per symbol (dedup) so a genuine miss is unmissable but the log
# spam doesn't paper over anything. Off via env for tests / replays.
_STALE_TG_DEDUP: Dict[str, float] = {}
_STALE_TG_LOCK = threading.Lock()
_STALE_TG_DEDUP_SECS = float(os.getenv("D1_STALE_ANCHOR_TG_DEDUP_SECS", "3600"))
_STALE_TG_ENABLED = str(os.getenv("D1_STALE_ANCHOR_TG_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")


def _maybe_send_stale_telegram(msg: str, symbol: str) -> None:
    """Send Telegram for a [D1-STALE-ANCHOR] event, dedup 1/hour/symbol.

    Fail-open: any error in the alert path is swallowed. Never raises.
    """
    if not _STALE_TG_ENABLED:
        return
    now = _time.time()
    with _STALE_TG_LOCK:
        last = _STALE_TG_DEDUP.get(symbol, 0.0)
        if now - last < _STALE_TG_DEDUP_SECS:
            return
        _STALE_TG_DEDUP[symbol] = now
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(msg)
    except Exception as exc:
        logger.warning(f"[D1-STALE-ANCHOR] telegram send failed for {symbol}: {exc}")


def _reset_stale_dedup_for_tests() -> None:
    """Clear the per-symbol dedup. Test-only."""
    with _STALE_TG_LOCK:
        _STALE_TG_DEDUP.clear()


def _iso_to_dt(z: Any) -> Optional[datetime]:
    if z is None:
        return None
    try:
        s = str(z).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def is_prior_d1_stale(fire_ts: Optional[datetime],
                      symbol: str = "GBPUSD") -> Tuple[bool, Dict[str, Any]]:
    """Public staleness check used by strategies that must refuse to fire
    when the pivot anchor is older than the Mon/Fri anchor rule allows.

    Returns (is_stale, ctx) where ctx contains:
      - reason:            'stale' | 'no_prior_d1_bar' | 'cache_missing' | ...
      - prior_d1_date:     ISO date string of the selected prior bar (if any)
      - fire_date:         ISO date string of the fire's UTC date
      - gap_days:          days between prior bar and fire date
      - expected_gap_days: expected max gap (3 on Mondays, else 1)
      - monday_anchor:     'friday' | 'sunday' env value

    is_stale=True when gap_days > expected_gap_days OR when no prior D1
    bar is available at all (cache_missing / cache_empty / no_prior_d1_bar).
    is_stale=False otherwise.

    Fail-closed for staleness detection: callers that treat True as
    "refuse to fire" get the correct answer even if the cache is unreadable.
    """
    ctx: Dict[str, Any] = {
        "reason": None, "prior_d1_date": None, "fire_date": None,
        "gap_days": None, "expected_gap_days": None, "monday_anchor": None,
    }
    if fire_ts is None:
        ctx["reason"] = "missing_fire_ts"
        return True, ctx

    fts = fire_ts if fire_ts.tzinfo else fire_ts.replace(tzinfo=timezone.utc)
    fire_date = fts.astimezone(timezone.utc).date()
    ctx["fire_date"] = fire_date.isoformat()

    prior, _cache_age, reason = _select_prior_d1(fts, symbol)
    ctx["monday_anchor"] = (os.getenv("PIVOT_MONDAY_ANCHOR", "friday") or "friday").strip().lower()
    if prior is None:
        ctx["reason"] = reason or "no_prior_d1_bar"
        return True, ctx

    p_dt = _iso_to_dt(prior.get("timestamp"))
    if p_dt is None:
        ctx["reason"] = "prior_bar_no_timestamp"
        return True, ctx
    p_date = p_dt.astimezone(timezone.utc).date()
    ctx["prior_d1_date"] = p_date.isoformat()

    expected_gap = 3 if fire_date.weekday() == 0 else 1
    actual_gap = (fire_date - p_date).days
    ctx["expected_gap_days"] = expected_gap
    ctx["gap_days"] = actual_gap
    if actual_gap > expected_gap:
        ctx["reason"] = "stale"
        return True, ctx
    ctx["reason"] = "ok"
    return False, ctx


def compute_pd_pct(entry_price: Optional[float],
                   fire_ts: Optional[datetime],
                   symbol: str = "GBPUSD") -> Dict[str, Any]:
    """Return {pd_pct, pdh, pdl, pd_source_ts, cache_age_secs, days_gap, reason}.

    Fails OPEN: any error → pd_pct=None + populated reason.
    """
    out: Dict[str, Any] = {
        "pd_pct": None, "pdh": None, "pdl": None,
        "pd_source_ts": None, "cache_age_secs": None,
        "days_gap": None, "reason": None,
    }
    if entry_price is None or fire_ts is None:
        out["reason"] = "missing_inputs"
        return out
    try:
        ep = float(entry_price)
    except (TypeError, ValueError):
        out["reason"] = "bad_entry_price"
        return out
    fts = fire_ts
    if fts.tzinfo is None:
        fts = fts.replace(tzinfo=timezone.utc)
    fire_date = fts.astimezone(timezone.utc).date()

    try:
        from htf_cache import (
            load_cached_candles,
            last_candle_age_secs,
            select_prior_completed_d1,
        )
    except Exception as exc:
        out["reason"] = f"htf_cache_import_error:{exc}"
        return out

    # cache_age_secs is populated eagerly (even on failure) so callers
    # can gate on staleness independent of whether a valid prior exists.
    try:
        data = load_cached_candles(symbol, "D1")
        if data is not None:
            candles = data.get("candles") or []
            if candles:
                try:
                    out["cache_age_secs"] = last_candle_age_secs(candles)
                except Exception:
                    out["cache_age_secs"] = None
    except Exception:
        # Non-fatal — the selector below handles cache errors explicitly.
        pass

    # Route through the authoritative selector so pd_pct and pivot-family
    # outputs cannot disagree about which bar is "yesterday". This closes
    # the Defect 1 divergence — this function used to walk the D1 cache
    # itself without the weekday guard, contradicting the invariant the
    # _select_prior_d1 docstring already claimed.
    prior, sel_reason = select_prior_completed_d1(symbol, fire_date)
    if prior is None:
        out["reason"] = sel_reason
        return out

    try:
        pdh = float(prior["high"])
        pdl = float(prior["low"])
    except (KeyError, TypeError, ValueError) as exc:
        out["reason"] = f"prior_bar_malformed:{exc}"
        return out

    if pdh - pdl <= 0.0:
        out["pdh"] = pdh
        out["pdl"] = pdl
        out["pd_source_ts"] = prior.get("timestamp")
        out["reason"] = "degenerate_prior_range"
        return out

    pd_pct = 100.0 * (ep - pdl) / (pdh - pdl)
    out["pd_pct"] = float(pd_pct)
    out["pdh"] = pdh
    out["pdl"] = pdl
    out["pd_source_ts"] = prior.get("timestamp")
    p_dt = _iso_to_dt(prior.get("timestamp"))
    if p_dt is not None:
        out["days_gap"] = (fire_date - p_dt.astimezone(timezone.utc).date()).days
    return out


def _select_prior_d1(fire_ts: datetime, symbol: str = "GBPUSD"):
    """Shared prior-D1 selection. Returns (candle_dict, cache_age_secs, reason)
    or (None, None, reason).

    Delegates the selection itself to the authoritative
    ``htf_cache.select_prior_completed_d1`` helper so every consumer
    (pd_pct, PDH/PDL, PIVOT, R/S, level_computation PREV_DAY_*) shares
    identical previous-day identity — the invariant this wrapper's
    docstring used to CLAIM but the code did not enforce (compute_pd_pct
    walked the cache independently without the weekday guard).

    Anchor rule (2026-09-07 tightening — exam-freeze apparatus repair):
    unconditionally skip Saturday- and Sunday-labelled bars in the walk.
    The anchor is the most recent FULL WEEKDAY bar strictly before the
    fire date. This is a defence-in-depth backstop for the writer-side
    weekend guard in htf_cache._drop_weekend_labelled_d1: even if a Sat/Sun
    row leaks into the cache in future, the pivot levels cannot shear.
    The weekday filter now lives on the authoritative selector so all
    call sites inherit it.

    The prior PIVOT_MONDAY_ANCHOR env switch is deprecated and no longer
    consulted — Sunday-anchored Monday pivots produced the 2026-09-06
    phantom R1/R2 that motivated the freeze; the option is removed to
    eliminate any path that could re-enable that behaviour.

    This wrapper adds two concerns on top of the pure selector:
      * cache_age_secs — surfaced to gate strategies on staleness.
      * [PIVOT-ANCHOR] / [D1-STALE-ANCHOR] logging + Telegram escalation.
    Both are journal-facing side effects, not part of the selection rule.
    """
    fts = fire_ts
    if fts.tzinfo is None:
        fts = fts.replace(tzinfo=timezone.utc)
    fire_date = fts.astimezone(timezone.utc).date()

    try:
        from htf_cache import (
            load_cached_candles,
            last_candle_age_secs,
            select_prior_completed_d1,
        )
    except Exception as exc:
        return None, None, f"htf_cache_import_error:{exc}"

    # Compute cache_age separately so callers can still gate on staleness
    # even when no valid prior is found (the message differs but the age
    # signal is useful).
    try:
        data = load_cached_candles(symbol, "D1")
        if data is None:
            return None, None, "cache_missing"
        candles = data.get("candles") or []
        if not candles:
            return None, None, "cache_empty"
        try:
            cache_age = last_candle_age_secs(candles)
        except Exception:
            cache_age = None
    except Exception as exc:
        return None, None, f"cache_read_error:{exc}"

    prior, reason = select_prior_completed_d1(symbol, fire_date)
    if prior is None:
        return None, cache_age, reason

    p_dt = _iso_to_dt(prior.get("timestamp"))
    if p_dt is not None:
        p_date = p_dt.astimezone(timezone.utc).date()
        logger.info(
            f"[PIVOT-ANCHOR] {symbol}: date={p_date.isoformat()} "
            f"weekday={p_date.strftime('%a')} fire_date={fire_date.isoformat()}"
        )
        expected_gap = 3 if fire_date.weekday() == 0 else 1
        actual_gap = (fire_date - p_date).days
        if actual_gap > expected_gap:
            _warn_line = (
                f"[D1-STALE-ANCHOR] {symbol}: prior_d1_date={p_date.isoformat()} "
                f"fire_date={fire_date.isoformat()} gap_days={actual_gap} "
                f"expected_gap_days={expected_gap}"
            )
            logger.warning(_warn_line)
            # Escalate to Telegram — 1 alert / hour / symbol so the log
            # spam (239× on 2026-08-21) doesn't hide a real miss.
            _maybe_send_stale_telegram(_warn_line, symbol)

    return prior, cache_age, None


def compute_pivot_nearest(entry_price: Optional[float],
                          fire_ts: Optional[datetime],
                          direction: Optional[str],
                          symbol: str = "GBPUSD") -> Dict[str, Any]:
    """Return classic pivots + directionally-relevant nearest level.

    Pivots computed from the prior completed D1 bar (same selection as
    compute_pd_pct — cache/htf/GBPUSD_D1.json, most recent D1 whose UTC date
    is strictly before the fire's calendar date; Monday → Friday's;
    weekend/holiday gap → last completed bar). Formula (classic floor):

        P  = (H + L + C) / 3
        R1 = 2*P - L        S1 = 2*P - H
        R2 = P + (H - L)    S2 = P - (H - L)
        R3 = H + 2*(P - L)  S3 = L - 2*(H - P)

    Directionally-relevant family: SELL fires resistance-family {P,R1,R2,R3};
    BUY fires support-family {P,S1,S2,S3}. Reported fields:

      - pivots: {"P","R1","R2","R3","S1","S2","S3"}  (all values or None)
      - nearest: identity of the nearest directionally-relevant level
                 (min |level - entry| in the family), None on failure
      - nearest_price
      - nearest_dist_pips: signed = (level - entry) * 10000  (level above → +)
      - is_outer: True if nearest is not P, False if P, None on failure
      - outer_min_dist_pips: |dist| in pips to the nearest OUTER level of
        the same family (R-family for SELL, S-family for BUY). Enables the
        "central-only" gate: is_outer=False AND outer_min_dist_pips > cap.
      - pd_source_ts, cache_age_secs, days_gap, reason

    Fails OPEN: any error → nearest=None + populated reason. Callers must
    treat nearest=None as "no gate action".
    """
    out: Dict[str, Any] = {
        "pivots": None,
        "nearest": None, "nearest_price": None, "nearest_dist_pips": None,
        "is_outer": None, "outer_min_dist_pips": None,
        "pd_source_ts": None, "cache_age_secs": None, "days_gap": None,
        "reason": None,
    }
    if entry_price is None or fire_ts is None or direction is None:
        out["reason"] = "missing_inputs"
        return out
    try:
        ep = float(entry_price)
    except (TypeError, ValueError):
        out["reason"] = "bad_entry_price"
        return out
    dir_norm = str(direction).upper()
    if dir_norm not in ("BUY", "SELL"):
        out["reason"] = f"bad_direction:{direction}"
        return out

    fts = fire_ts if fire_ts.tzinfo else fire_ts.replace(tzinfo=timezone.utc)
    fire_date = fts.astimezone(timezone.utc).date()

    prior, cache_age, reason = _select_prior_d1(fts, symbol)
    out["cache_age_secs"] = cache_age
    if prior is None:
        out["reason"] = reason
        return out

    try:
        h = float(prior["high"])
        l = float(prior["low"])
        c = float(prior["close"])
    except (KeyError, TypeError, ValueError) as exc:
        out["reason"] = f"prior_bar_malformed:{exc}"
        return out
    if h - l <= 0.0:
        out["reason"] = "degenerate_prior_range"
        out["pd_source_ts"] = prior.get("timestamp")
        return out

    pp = (h + l + c) / 3.0
    pivots = {
        "P":  pp,
        "R1": 2 * pp - l,
        "S1": 2 * pp - h,
        "R2": pp + (h - l),
        "S2": pp - (h - l),
        "R3": h + 2 * (pp - l),
        "S3": l - 2 * (h - pp),
    }
    out["pivots"] = pivots
    out["pd_source_ts"] = prior.get("timestamp")
    p_dt = _iso_to_dt(prior.get("timestamp"))
    if p_dt is not None:
        out["days_gap"] = (fire_date - p_dt.astimezone(timezone.utc).date()).days

    # Directionally-relevant family
    if dir_norm == "SELL":
        family = ("P", "R1", "R2", "R3")
        outer  = ("R1", "R2", "R3")
    else:
        family = ("P", "S1", "S2", "S3")
        outer  = ("S1", "S2", "S3")

    # Nearest in the family (min |level - entry|). Pip scale for GBPUSD-style
    # cache prices: cache stores price * 10000, so pips = |level - entry|.
    fam_items = [(k, pivots[k]) for k in family]
    nk, nv = min(fam_items, key=lambda kv: abs(kv[1] - ep))
    out["nearest"] = nk
    out["nearest_price"] = nv
    out["nearest_dist_pips"] = nv - ep
    out["is_outer"] = (nk != "P")

    outer_items = [(k, pivots[k]) for k in outer]
    ok, ov = min(outer_items, key=lambda kv: abs(kv[1] - ep))
    out["outer_min_dist_pips"] = abs(ov - ep)
    return out


def compute_pivots_only(fire_ts: Optional[datetime],
                        symbol: str = "GBPUSD") -> Dict[str, Any]:
    """Direction-agnostic pivot read for PIVOT_BREAK's coil test.

    Same D1 selection as compute_pivot_nearest (via _select_prior_d1) —
    reusing the shared selector guarantees PIVOT_BREAK, the PD gates and
    the pivot telemetry cannot disagree about which D1 bar is "yesterday".
    Formulas are not duplicated; this wrapper computes the same classic
    floor pivots and returns only the pivots dict + provenance.

    Returns:
      {"pivots": {"P","R1","R2","R3","S1","S2","S3"}, "pd_source_ts",
       "cache_age_secs", "days_gap", "reason"}

    Failure: `pivots` is None and `reason` is populated when the D1 cache
    is missing/stale or the prior bar is degenerate. PIVOT_BREAK MUST treat
    pivots=None as "do not evaluate" — without P there is no coil test
    and no scale/runner targets, and the strategy cannot fail open.
    """
    out: Dict[str, Any] = {
        "pivots": None,
        "pd_source_ts": None,
        "cache_age_secs": None,
        "days_gap": None,
        "reason": None,
    }
    if fire_ts is None:
        out["reason"] = "missing_fire_ts"
        return out
    fts = fire_ts if fire_ts.tzinfo else fire_ts.replace(tzinfo=timezone.utc)
    fire_date = fts.astimezone(timezone.utc).date()

    prior, cache_age, reason = _select_prior_d1(fts, symbol)
    out["cache_age_secs"] = cache_age
    if prior is None:
        out["reason"] = reason
        return out
    try:
        h = float(prior["high"])
        l = float(prior["low"])
        c = float(prior["close"])
    except (KeyError, TypeError, ValueError) as exc:
        out["reason"] = f"prior_bar_malformed:{exc}"
        return out
    if h - l <= 0.0:
        out["reason"] = "degenerate_prior_range"
        out["pd_source_ts"] = prior.get("timestamp")
        return out

    pp = (h + l + c) / 3.0
    out["pivots"] = {
        "P":  pp,
        "R1": 2 * pp - l,
        "S1": 2 * pp - h,
        "R2": pp + (h - l),
        "S2": pp - (h - l),
        "R3": h + 2 * (pp - l),
        "S3": l - 2 * (h - pp),
    }
    out["pd_source_ts"] = prior.get("timestamp")
    p_dt = _iso_to_dt(prior.get("timestamp"))
    if p_dt is not None:
        out["days_gap"] = (fire_date - p_dt.astimezone(timezone.utc).date()).days
    return out
