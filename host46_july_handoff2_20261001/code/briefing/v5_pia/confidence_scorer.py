"""Deterministic confidence scorer for briefing.v5_pia (Phase 1).

Pure function — no I/O, no global state. The scorer is fed a market_data
dict (already enriched with v5-specific fields by data_package.py) plus a
news list, phase4 structure label, and the candidate trade plan.

Each confluence rule is a top-level function named score_<key> so it can
be unit-tested in isolation. The integrator (score_confidence) calls them
in order, applies hard gates, and returns the breakdown dict.

Bucket vocabulary:
  0-49   STAND_ASIDE
  50-69  WATCH
  70-84  ARMED
  85-100 HIGH_CONVICTION
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Hard-gate magic numbers (kept here, not in config, so the scorer's
# behaviour is fully described by reading this one file).
_HARD_GATE_MIN_RR              = 1.5
_HARD_GATE_MAX_LEVEL_DIST_ATR  = 1.5
_HARD_GATE_NEWS_WINDOW_MIN     =  15   # ±minutes around now_utc
_NEWS_CLEAR_WINDOW_HOURS       =   2

# Pre-news positioning bypass — when a HIGH-impact event for the pair's
# currency bases lands within this forward window, the d1_h4_bias_disagree
# hard gate is suspended (other gates still apply). 0 disables the bypass
# entirely, preserving pre-2026-05-08 behaviour.
_PRE_NEWS_BYPASS_HOURS_DEFAULT = 48


def _pre_news_bypass_hours() -> int:
    """Read V5_PRE_NEWS_BYPASS_HOURS from env at call time so flips don't
    require a process restart in tests. Negative values are clamped to 0.
    """
    try:
        v = int(os.getenv("V5_PRE_NEWS_BYPASS_HOURS", str(_PRE_NEWS_BYPASS_HOURS_DEFAULT)))
    except (TypeError, ValueError):
        return _PRE_NEWS_BYPASS_HOURS_DEFAULT
    return max(0, v)


# Pair → currency bases. Mirrors morning_briefing.SYMBOL_CURRENCIES; kept
# local to avoid importing morning_briefing for a 5-line constant.
_SYMBOL_CURRENCIES_LOCAL: Dict[str, List[str]] = {
    "GBPUSD": ["GBP", "USD"],
    "EURUSD": ["EUR", "USD"],
    "USDJPY": ["USD", "JPY"],
    "USDCAD": ["USD", "CAD"],
    "GBPJPY": ["GBP", "JPY"],
}


def _currencies_for_pair(pair: str) -> List[str]:
    p = (pair or "").upper()
    if p in _SYMBOL_CURRENCIES_LOCAL:
        return list(_SYMBOL_CURRENCIES_LOCAL[p])
    # Fallback: split into 3-letter halves if it looks like a 6-letter pair.
    if len(p) == 6 and p.isalpha():
        return [p[:3], p[3:]]
    return ["USD"]


def _is_pre_news_window(
    currencies: List[str],
    now_utc: datetime,
    hours_ahead: int,
    news_calendar_module=None,
) -> Tuple[bool, Optional[float], Optional[Dict[str, Any]]]:
    """Return (in_window, hours_to_nearest, nearest_event).

    True when at least one HIGH-impact event for any of *currencies* lands
    within *hours_ahead* of *now_utc*. hours_ahead == 0 disables (always
    returns False). Never raises — on calendar errors returns False.

    news_calendar_module: dependency-injection hook for tests. None →
    import the production module.
    """
    if not hours_ahead or hours_ahead <= 0:
        return False, None, None
    try:
        if news_calendar_module is None:
            import news_calendar as news_calendar_module  # type: ignore
        events = news_calendar_module.get_upcoming_events(
            hours_ahead=int(hours_ahead),
            currencies=list(currencies) if currencies else None,
            impact_min="HIGH",
        )
    except Exception as exc:
        logger.warning(f"[v5-scorer] _is_pre_news_window calendar error: {exc}")
        return False, None, None

    if not events:
        return False, None, None

    # The events list is sorted ascending by datetime_utc; the nearest is
    # the first row. Compute hours-to-event from now.
    nearest = events[0]
    try:
        dt_iso = str(nearest.get("datetime_utc") or "")
        ev_dt = datetime.fromisoformat(dt_iso)
        if ev_dt.tzinfo is None:
            ev_dt = ev_dt.replace(tzinfo=timezone.utc)
        delta_hours = (ev_dt - now_utc).total_seconds() / 3600.0
    except Exception:
        delta_hours = None
    return True, (round(delta_hours, 2) if delta_hours is not None else None), nearest

# Bucket boundaries (lower inclusive, upper exclusive).
_BUCKETS: Tuple[Tuple[str, int, int], ...] = (
    ("STAND_ASIDE",     0,  50),
    ("WATCH",          50,  70),
    ("ARMED",          70,  85),
    ("HIGH_CONVICTION", 85, 101),
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ppp(market_data: Dict[str, Any]) -> float:
    """points-per-pip from market_data; defaults to 1.0 (IG spread-bet)."""
    try:
        v = float(market_data.get("ppp", 1.0))
        return v if v > 0 else 1.0
    except (TypeError, ValueError):
        return 1.0


def _last_close(candles: List[Dict[str, Any]]) -> Optional[float]:
    if not candles:
        return None
    last = candles[-1]
    # Tolerate both the v4 short-key shape ("c") and the long-name shape ("close")
    for k in ("c", "close"):
        if k in last:
            try:
                return float(last[k])
            except (TypeError, ValueError):
                return None
    return None


def _bias_aligned(direction: str, value: float, anchor: float) -> bool:
    if direction == "BUY":
        return value > anchor
    if direction == "SELL":
        return value < anchor
    return False


def _bucket_for(score: int) -> str:
    score = max(0, min(100, int(score)))
    for name, lo, hi in _BUCKETS:
        if lo <= score < hi:
            return name
    return "STAND_ASIDE"


# ─────────────────────────────────────────────────────────────────────────────
# Confluence scorers — each pure, returns (points, diagnostic_dict)
# ─────────────────────────────────────────────────────────────────────────────

def score_d1_ema_alignment(
    direction: str, market_data: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    """15pts if D1 close on bias side of D1 20 EMA."""
    d1_close = _last_close(market_data.get("d1_candles") or [])
    d1_ema20 = market_data.get("d1_ema_20")
    if d1_close is None or d1_ema20 is None:
        return 0, {"reason": "missing_inputs", "d1_close": d1_close, "d1_ema_20": d1_ema20}
    aligned = _bias_aligned(direction, d1_close, float(d1_ema20))
    return (15 if aligned else 0), {
        "d1_close": d1_close, "d1_ema_20": float(d1_ema20), "aligned": aligned,
    }


def score_h4_ema_alignment(
    direction: str, market_data: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    """15pts if H4 close on bias side of H4 20 EMA."""
    h4_close = _last_close(market_data.get("h4_candles") or [])
    h4_ema20 = market_data.get("h4_ema_20")
    if h4_close is None or h4_ema20 is None:
        return 0, {"reason": "missing_inputs", "h4_close": h4_close, "h4_ema_20": h4_ema20}
    aligned = _bias_aligned(direction, h4_close, float(h4_ema20))
    return (15 if aligned else 0), {
        "h4_close": h4_close, "h4_ema_20": float(h4_ema20), "aligned": aligned,
    }


def score_h4_ema_slope(
    direction: str, market_data: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    """10pts if H4 EMA20 5-bar diff > 2pip in bias direction.

    market_data["h4_ema_20_5bar_diff_pips"] is precomputed by the v5
    enrichment step (data_package.assemble_v5_data_package). It carries
    the signed pip difference (ema20[t] - ema20[t-5]) / ppp.
    """
    diff = market_data.get("h4_ema_20_5bar_diff_pips")
    if diff is None:
        return 0, {"reason": "missing_input"}
    diff = float(diff)
    threshold = 2.0
    if direction == "BUY":
        ok = diff > threshold
    elif direction == "SELL":
        ok = diff < -threshold
    else:
        ok = False
    return (10 if ok else 0), {"diff_pips": diff, "threshold_pips": threshold, "ok": ok}


def score_h1_momentum(
    direction: str, market_data: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    """10pts if 3+ of last 6 H1 bars closed in bias direction (close vs open)."""
    candles = list(market_data.get("h1_candles") or [])[-6:]
    if len(candles) < 6:
        return 0, {"reason": "insufficient_h1_bars", "have": len(candles)}
    aligned = 0
    for c in candles:
        try:
            o = float(c.get("o", c.get("open")))
            cl = float(c.get("c", c.get("close")))
        except (TypeError, ValueError):
            continue
        if direction == "BUY" and cl > o:
            aligned += 1
        elif direction == "SELL" and cl < o:
            aligned += 1
    return (10 if aligned >= 3 else 0), {"aligned_bars": aligned, "needed": 3}


def score_entry_proximity(
    direction: str, entry: float, market_data: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    """15pts if entry within 0.5×ATR(H4) of nearest level on the side of bias.

    BUY → nearest support_levels entry. SELL → nearest resistance_levels.
    """
    ppp = _ppp(market_data)
    atr_h4_pips = market_data.get("atr_h4_pips")
    if atr_h4_pips is None:
        return 0, {"reason": "missing_atr_h4_pips"}
    levels = market_data.get(
        "support_levels" if direction == "BUY" else "resistance_levels"
    ) or []
    if not levels:
        return 0, {"reason": "no_levels", "side": "support" if direction == "BUY" else "resistance"}

    # Distance in price units; convert to pips for comparison.
    nearest = min(levels, key=lambda lv: abs(float(lv) - entry))
    dist_pips = abs(float(nearest) - entry) / ppp
    threshold_pips = 0.5 * float(atr_h4_pips)
    ok = dist_pips <= threshold_pips
    return (15 if ok else 0), {
        "entry": entry, "nearest_level": float(nearest),
        "distance_pips": round(dist_pips, 2),
        "threshold_pips": round(threshold_pips, 2),
        "ok": ok,
    }


def score_structural_stop(
    direction: str, stop: float, market_data: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    """10pts if stop within 2pip of a structural level.

    Structural levels = swing highs/lows (last 20 H4 bars) plus H4 EMA20.
    For BUY we expect the stop near a swing low (or EMA20 below price);
    for SELL near a swing high (or EMA20 above price). The rule as stated
    is symmetric ("within 2pip of a structural level"), so we measure the
    nearest distance across the appropriate level set.
    """
    ppp = _ppp(market_data)
    h4_ema20 = market_data.get("h4_ema_20")
    swings = (
        list(market_data.get("h4_swing_lows_recent") or [])
        if direction == "BUY"
        else list(market_data.get("h4_swing_highs_recent") or [])
    )
    candidates = list(swings)
    if h4_ema20 is not None:
        candidates.append(float(h4_ema20))
    if not candidates:
        return 0, {"reason": "no_structural_levels"}
    nearest = min(candidates, key=lambda lv: abs(float(lv) - stop))
    dist_pips = abs(float(nearest) - stop) / ppp
    ok = dist_pips <= 2.0
    return (10 if ok else 0), {
        "stop": stop, "nearest_structural_level": float(nearest),
        "distance_pips": round(dist_pips, 2), "threshold_pips": 2.0, "ok": ok,
    }


def score_rr_base(
    direction: str, entry: float, stop: float, target: float
) -> Tuple[int, Dict[str, Any]]:
    """15pts if R:R >= 2.0."""
    rr = _rr(direction, entry, stop, target)
    return (15 if rr is not None and rr >= 2.0 else 0), {
        "rr": rr, "threshold": 2.0,
    }


def score_rr_bonus(
    direction: str, entry: float, stop: float, target: float
) -> Tuple[int, Dict[str, Any]]:
    """5pts if R:R >= 3.0 (additive on top of rr_base)."""
    rr = _rr(direction, entry, stop, target)
    return (5 if rr is not None and rr >= 3.0 else 0), {
        "rr": rr, "threshold": 3.0,
    }


def score_atr_regime(
    market_data: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    """5pts if ATR_PCTL_14 between 30 and 80 (Phase 2 indicator on 5M)."""
    pctl = market_data.get("atr_pctl_14")
    if pctl is None:
        return 0, {"reason": "missing_atr_pctl_14"}
    pctl = float(pctl)
    ok = 30.0 <= pctl <= 80.0
    return (5 if ok else 0), {"atr_pctl_14": pctl, "ok": ok, "band": [30.0, 80.0]}


def score_news_clear(
    entry_time_utc: datetime, news_calendar: List[Dict[str, Any]]
) -> Tuple[int, Dict[str, Any]]:
    """10pts if no red-folder (impact==High) news in [entry_time, entry_time+2h]."""
    upper = entry_time_utc + timedelta(hours=_NEWS_CLEAR_WINDOW_HOURS)
    hits = _news_hits_in_window(news_calendar, entry_time_utc, upper)
    ok = not hits
    return (10 if ok else 0), {
        "window_utc": [entry_time_utc.isoformat(), upper.isoformat()],
        "hits_in_window": hits,
        "ok": ok,
    }


def score_phase4_structure(
    direction: str, phase4_structure: str, market_data: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    """10pts if structure == "TRENDING" AND aligned with direction.

    Aligned means the raw classifier label (TRENDING_BULL / TRENDING_BEAR)
    matches the trade direction. The raw label is passed via
    market_data["phase4_structure_raw"].
    """
    raw = str(market_data.get("phase4_structure_raw") or "").upper()
    structural_trending = phase4_structure == "TRENDING"
    if not structural_trending:
        return 0, {"phase4_structure": phase4_structure, "raw": raw, "trending": False}
    if direction == "BUY" and raw == "TRENDING_BULL":
        return 10, {"phase4_structure": phase4_structure, "raw": raw, "aligned": True}
    if direction == "SELL" and raw == "TRENDING_BEAR":
        return 10, {"phase4_structure": phase4_structure, "raw": raw, "aligned": True}
    return 0, {"phase4_structure": phase4_structure, "raw": raw, "aligned": False}


# ─────────────────────────────────────────────────────────────────────────────
# Hard-gate helpers
# ─────────────────────────────────────────────────────────────────────────────

def _rr(direction: str, entry: float, stop: float, target: float) -> Optional[float]:
    try:
        risk = abs(float(entry) - float(stop))
        reward = abs(float(target) - float(entry))
    except (TypeError, ValueError):
        return None
    if risk <= 0:
        return None
    return round(reward / risk, 3)


def _news_hits_in_window(
    news_calendar: List[Dict[str, Any]],
    start_utc: datetime,
    end_utc: datetime,
) -> List[Dict[str, Any]]:
    """Filter the news_calendar list for HIGH-impact events whose UTC datetime
    falls in [start_utc, end_utc). Events have shape
    {"time": "HH:MM", "currency": ..., "event_name": ..., "impact": "High"}.
    Date is implicitly today UTC (matches the v4 news_calendar.get_todays_events
    contract).
    """
    if not news_calendar:
        return []
    out: List[Dict[str, Any]] = []
    today = start_utc.date() if start_utc.tzinfo else datetime.now(timezone.utc).date()
    for ev in news_calendar:
        try:
            if str(ev.get("impact", "")).strip().lower() != "high":
                continue
            hhmm = str(ev.get("time", ""))
            if ":" not in hhmm:
                continue
            h, m = (int(p) for p in hhmm.split(":")[:2])
            ev_dt = datetime(
                today.year, today.month, today.day, h, m, tzinfo=timezone.utc
            )
        except (TypeError, ValueError):
            continue
        if start_utc <= ev_dt < end_utc:
            out.append({**ev, "_dt_utc": ev_dt.isoformat()})
    return out


def _check_hard_gates(
    pair: str, direction: str, entry: float, stop: float, target: float,
    market_data: Dict[str, Any], news_calendar: List[Dict[str, Any]],
    now_utc: datetime,
) -> Tuple[List[str], Dict[str, Any]]:
    """Evaluate hard gates. Returns (failures, gate_diagnostics).

    The diagnostics dict carries the pre-news bypass evaluation (whether
    it fired, the nearest event, hours_to_news) so the scorer can echo it
    into the confidence_breakdown for downstream observability.
    """
    failures: List[str] = []
    gate_diag: Dict[str, Any] = {}

    # 1. R:R < 1.5
    rr = _rr(direction, entry, stop, target)
    if rr is None or rr < _HARD_GATE_MIN_RR:
        failures.append(f"rr_below_{_HARD_GATE_MIN_RR}: rr={rr}")

    # 2. Entry > 1.5×ATR(H4) from nearest structural level. The "structural
    # levels" set here is the union of support+resistance lists plus
    # h4_ema_20 — i.e. every level the trade plan considers structural.
    atr_h4_pips = market_data.get("atr_h4_pips")
    ppp = _ppp(market_data)
    structural: List[float] = []
    structural.extend(market_data.get("support_levels") or [])
    structural.extend(market_data.get("resistance_levels") or [])
    if market_data.get("h4_ema_20") is not None:
        structural.append(float(market_data["h4_ema_20"]))
    if atr_h4_pips is not None and structural:
        nearest = min(structural, key=lambda lv: abs(float(lv) - entry))
        dist_pips = abs(float(nearest) - entry) / ppp
        threshold = _HARD_GATE_MAX_LEVEL_DIST_ATR * float(atr_h4_pips)
        if dist_pips > threshold:
            failures.append(
                f"entry_too_far_from_levels: dist_pips={dist_pips:.2f} "
                f"threshold_pips={threshold:.2f}"
            )

    # 3. D1 and H4 disagree on bias direction. Compute each anchor's bias
    # absolutely (above EMA = BULLISH, below = BEARISH) then compare.
    #
    # Pre-news bypass: when a HIGH-impact event for the pair's currency
    # bases lands within V5_PRE_NEWS_BYPASS_HOURS of now, this gate is
    # suspended. Pre-NFP positioning days (D1 still aligned with the
    # broader trend, H4 already pulling back into the base) routinely
    # fail the strict d1==h4 check; the bypass restores eligibility for
    # the LLM to make the call rather than short-circuiting to STAND_ASIDE.
    d1_close = _last_close(market_data.get("d1_candles") or [])
    d1_ema20 = market_data.get("d1_ema_20")
    h4_close = _last_close(market_data.get("h4_candles") or [])
    h4_ema20 = market_data.get("h4_ema_20")
    d1_h4_disagree = False
    if all(x is not None for x in (d1_close, d1_ema20, h4_close, h4_ema20)):
        d1_bull = float(d1_close) > float(d1_ema20)
        h4_bull = float(h4_close) > float(h4_ema20)
        d1_h4_disagree = (d1_bull != h4_bull)

    bypass_hours = _pre_news_bypass_hours()
    pair_currencies = _currencies_for_pair(pair)
    in_pre_news, hours_to_news, nearest_event = (False, None, None)
    if d1_h4_disagree and bypass_hours > 0:
        in_pre_news, hours_to_news, nearest_event = _is_pre_news_window(
            currencies=pair_currencies,
            now_utc=now_utc,
            hours_ahead=bypass_hours,
        )

    bypass_applied = bool(d1_h4_disagree and in_pre_news)
    gate_diag["pre_news_bypass"] = {
        "applied":         bypass_applied,
        "hours_to_news":   hours_to_news,
        "currencies":      pair_currencies,
        "nearest_event":   nearest_event,
        "bypass_hours_env": bypass_hours,
        "d1_h4_disagree":  d1_h4_disagree,
    }

    if d1_h4_disagree and not bypass_applied:
        # Recompute booleans purely for the failure message — same values
        # as above, kept local so the message reads naturally.
        d1_bull = float(d1_close) > float(d1_ema20)  # type: ignore[arg-type]
        h4_bull = float(h4_close) > float(h4_ema20)  # type: ignore[arg-type]
        failures.append(
            f"d1_h4_bias_disagree: d1_bull={d1_bull} h4_bull={h4_bull}"
        )

    # Loud single-line gate-evaluation log. Operators scrolling journalctl
    # need to see WHY a bypass fired (or didn't).
    gate_outcome = (
        "BYPASSED" if bypass_applied
        else ("FAILED" if d1_h4_disagree else "PASSED")
    )
    logger.info(
        "[v5-scorer] %s d1_h4_disagree=%s pre_news_bypass=%s hours_to_news=%s "
        "currencies=%s -> %s",
        (pair or "").upper(), d1_h4_disagree, bypass_applied,
        hours_to_news, pair_currencies, gate_outcome,
    )

    # 4. Red-folder news during the entry window itself (±15min around now).
    near_window_lo = now_utc - timedelta(minutes=_HARD_GATE_NEWS_WINDOW_MIN)
    near_window_hi = now_utc + timedelta(minutes=_HARD_GATE_NEWS_WINDOW_MIN)
    in_entry = _news_hits_in_window(news_calendar, near_window_lo, near_window_hi)
    if in_entry:
        names = [str(e.get("event_name", "?")) for e in in_entry]
        failures.append(f"red_news_in_entry_window: {names}")

    return failures, gate_diag


# ─────────────────────────────────────────────────────────────────────────────
# Public integrator
# ─────────────────────────────────────────────────────────────────────────────

def score_confidence(
    pair: str,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    market_data: Dict[str, Any],
    news_calendar: List[Dict[str, Any]],
    phase4_structure: str,
    now_utc: datetime,
) -> Dict[str, Any]:
    """Score a candidate trade plan deterministically.

    Returns a confidence_breakdown dict — see module docstring for the
    bucket vocabulary. On hard-gate failure the dict is fully populated
    with the failures and a zero score.
    """
    if direction not in ("BUY", "SELL"):
        # Caller should have routed this to STAND_ASIDE before scoring,
        # but guard anyway. Returns an honest zero rather than crashing.
        return {
            "schema_version": "v5_pia.scorer.v1",
            "awards": {}, "diagnostics": {},
            "total": 0, "capped": 0, "displayed": 0,
            "hard_gate_failures": [f"invalid_direction:{direction}"],
            "bucket": "STAND_ASIDE",
        }

    # Hard gates run first. Any failure short-circuits to zero.
    hard_failures, gate_diag = _check_hard_gates(
        pair, direction, entry, stop, target, market_data, news_calendar, now_utc,
    )

    awards: Dict[str, int] = {}
    # Seed diagnostics with the pre-news bypass evaluation — this is a
    # free-form dict by schema design (BriefingV5.confidence_breakdown is
    # Dict[str, Any]); adding a key is non-breaking. See PR for schema
    # decision rationale (no top-level regime field needed).
    diagnostics: Dict[str, Any] = {
        "pre_news_bypass": gate_diag.get("pre_news_bypass"),
    }

    # Run every scorer regardless of hard-gate result so the diagnostics
    # are populated for every fire — useful for shadow-logging when a
    # hard gate trips. The capped/displayed values are still zeroed below.
    pts, diag = score_d1_ema_alignment(direction, market_data)
    awards["d1_ema_alignment"], diagnostics["d1_ema_alignment"] = pts, diag

    pts, diag = score_h4_ema_alignment(direction, market_data)
    awards["h4_ema_alignment"], diagnostics["h4_ema_alignment"] = pts, diag

    pts, diag = score_h4_ema_slope(direction, market_data)
    awards["h4_ema_slope"], diagnostics["h4_ema_slope"] = pts, diag

    pts, diag = score_h1_momentum(direction, market_data)
    awards["h1_momentum"], diagnostics["h1_momentum"] = pts, diag

    pts, diag = score_entry_proximity(direction, entry, market_data)
    awards["entry_proximity"], diagnostics["entry_proximity"] = pts, diag

    pts, diag = score_structural_stop(direction, stop, market_data)
    awards["structural_stop"], diagnostics["structural_stop"] = pts, diag

    pts, diag = score_rr_base(direction, entry, stop, target)
    awards["rr_base"], diagnostics["rr_base"] = pts, diag

    pts, diag = score_rr_bonus(direction, entry, stop, target)
    awards["rr_bonus"], diagnostics["rr_bonus"] = pts, diag

    pts, diag = score_atr_regime(market_data)
    awards["atr_regime"], diagnostics["atr_regime"] = pts, diag

    pts, diag = score_news_clear(now_utc, news_calendar)
    awards["news_clear"], diagnostics["news_clear"] = pts, diag

    pts, diag = score_phase4_structure(direction, phase4_structure, market_data)
    awards["phase4_structure"], diagnostics["phase4_structure"] = pts, diag

    total = int(sum(awards.values()))
    capped = min(total, 100)
    if hard_failures:
        displayed = 0
        bucket = "STAND_ASIDE"
    else:
        displayed = capped
        bucket = _bucket_for(displayed)

    return {
        "schema_version":      "v5_pia.scorer.v1",
        "awards":              awards,
        "diagnostics":         diagnostics,
        "total":               total,
        "capped":              capped,
        "displayed":           displayed,
        "hard_gate_failures":  hard_failures,
        "bucket":              bucket,
    }
