"""news_strategy_release_anchored.py — release-anchored, shadow-first
evaluator per docs/NEWS_STRATEGY_BUILD_SPEC_2026-07-25.md (2026-07-25).

Design intent:

  * Anchors on calendar HIGH-impact releases (subject to NEWS_MIN_IMPACT).
  * Measures release bar + NEWS_DECISION_CANDLES (default 3) post-release
    bars: spike magnitude, direction, retrace fraction.
  * Fade entry when retrace >= NEWS_FADE_BODY_PCT (default 0.50) of spike;
    continuation variant behind NEWS_CONTINUATION_ENABLED (default 0).
  * SL/TP: NEWS_SL_PIPS / NEWS_TP_PIPS (spec values, ASSUMED).
  * HARD DEPENDENCY: calendar staleness check via news_calendar_health;
    stale → verdict=DECLINE reason=stale_calendar. Structurally incapable
    of firing on stale data.

Mode gate (NEWS_STRATEGY_MODE — governs BOTH this path AND the existing
tick-level spike-reactive path in news_strategy.py):

  off      — dormant. on_bar_close is a no-op that returns None.
  shadow   — full evaluation. Every release produces one eval row per
             decision bar with verdict=WOULD_FIRE|DECLINE + reason. No
             order returned to the caller. Default when mode is `shadow`
             is that autobot never executes.
  enforce  — evaluation + returns a Result dict with a StrategyDecision
             the caller can hand to execute_trade.

Everything is null-safe. This module never raises to its caller.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── Env / config ──────────────────────────────────────────────────────────
def _env(name, default):
    return str(os.getenv(name, default))


def _env_int(name, default):
    try:
        return int(_env(name, str(default)).strip())
    except Exception:
        return int(default)


def _env_float(name, default):
    try:
        return float(_env(name, str(default)).strip())
    except Exception:
        return float(default)


def _mode() -> str:
    m = _env("NEWS_STRATEGY_MODE", "off").strip().lower()
    if m not in ("off", "shadow", "enforce"):
        m = "off"
    return m


def _min_impact() -> str:
    return _env("NEWS_MIN_IMPACT", "HIGH").strip().upper()


def _decision_candles() -> int:
    return max(1, _env_int("NEWS_DECISION_CANDLES", 3))


def _spike_min_pips() -> float:
    return _env_float("NEWS_SPIKE_MIN_PIPS", 25.0)


def _fade_body_pct() -> float:
    return _env_float("NEWS_FADE_BODY_PCT", 0.50)


def _continuation_enabled() -> bool:
    return _env("NEWS_CONTINUATION_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _sl_pips() -> float:
    return _env_float("NEWS_SL_PIPS", 20.0)


def _tp_pips() -> float:
    return _env_float("NEWS_TP_PIPS", 60.0)


_IMPACT_RANK = {"LOW": 1, "MED": 2, "HIGH": 3}
# Pair → set of currencies whose HIGH releases anchor an evaluation for
# the pair. Mirrors news_strategy._AFFECTED_PAIRS shape.
_PAIR_CCYS = {
    "GBPUSD": ("GBP", "USD"),
    "EURUSD": ("EUR", "USD"),
    "USDJPY": ("USD", "JPY"),
    "USDCAD": ("USD", "CAD"),
    "GBPJPY": ("GBP", "JPY"),
}


# ─── State: per-pair release-anchor tracking ───────────────────────────────
@dataclass
class _AnchorState:
    release_key: str
    release_ts: float
    event_name: str
    currency: str
    anchor_price: float
    bars_seen: int = 0
    highs: List[float] = field(default_factory=list)
    lows: List[float] = field(default_factory=list)
    closes: List[float] = field(default_factory=list)
    fired: bool = False


_anchors_by_pair: Dict[str, _AnchorState] = {}


def _reset_state_for_tests() -> None:
    _anchors_by_pair.clear()


def _load_today_events() -> List[Dict[str, Any]]:
    """Read the news_state_finnhub cache for today. Returns [] on any
    failure — the caller handles stale/missing separately via
    news_calendar_health."""
    try:
        import json
        from pathlib import Path
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_dir = Path(os.getenv("NEWS_STATE_CACHE_DIR", "/opt/tradingbot/cache"))
        path = cache_dir / f"news_state_finnhub_{today_str}.json"
        if not path.exists():
            return []
        with path.open("r") as fh:
            data = json.load(fh)
        return list(data.get("events") or [])
    except Exception:
        return []


def _qualifying_release_for_bar(
    pair: str, bar_ts_utc: datetime,
) -> Optional[Dict[str, Any]]:
    """The most recent HIGH (or above) event affecting `pair` whose
    release timestamp falls inside the bar containing bar_ts_utc.

    bar_ts_utc is the bar-OPEN time (the standard convention across the
    codebase); the bar spans [bar_ts, bar_ts + 5min)."""
    ccys = _PAIR_CCYS.get((pair or "").upper())
    if not ccys:
        return None
    min_rank = _IMPACT_RANK.get(_min_impact(), 3)
    bar_start = bar_ts_utc.astimezone(timezone.utc)
    bar_end = bar_start + timedelta(minutes=5)
    for ev in _load_today_events():
        try:
            if _IMPACT_RANK.get(str(ev.get("impact") or "").upper(), 0) < min_rank:
                continue
            if str(ev.get("currency") or "").upper() not in ccys:
                continue
            ts_raw = str(ev.get("ts") or "")
            ts_dt = datetime.fromisoformat(ts_raw)
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=timezone.utc)
            else:
                ts_dt = ts_dt.astimezone(timezone.utc)
            if bar_start <= ts_dt < bar_end:
                return {
                    "event_name": str(ev.get("event") or ""),
                    "currency": str(ev.get("currency") or "").upper(),
                    "release_ts": ts_dt.timestamp(),
                }
        except Exception:
            continue
    return None


def _emit_row(row: Dict[str, Any]) -> None:
    """Write to news_strategy_evals.jsonl via news_strategy._log_eval so we
    share the single eval-log path + gate."""
    try:
        import news_strategy as _ns
        _ns._log_eval(row)
    except Exception:
        pass


def _pip_size_for(pair: str) -> float:
    try:
        from pair_config import get_ppp
        return float(get_ppp(pair))
    except Exception:
        return 0.0001 if not (pair or "").upper().endswith("JPY") else 0.01


def _row(kind, pair, epic, bar_ts, anchor, verdict, reason, extra=None):
    r = {
        "kind": "RELEASE_ANCHORED_" + kind,
        "ts_utc": bar_ts.astimezone(timezone.utc).isoformat(),
        "symbol": pair,
        "epic": epic,
        "mode": _mode(),
        "verdict": verdict,
        "reason": reason,
        "release_key": (anchor.release_key if anchor else None),
        "release_name": (anchor.event_name if anchor else None),
        "release_currency": (anchor.currency if anchor else None),
        "scheduled_time_iso": (
            datetime.fromtimestamp(anchor.release_ts, tz=timezone.utc).isoformat()
            if anchor else None
        ),
        "bars_seen": (anchor.bars_seen if anchor else None),
    }
    if isinstance(extra, dict):
        r.update(extra)
    return r


@dataclass
class Result:
    verdict: str            # WOULD_FIRE | DECLINE | NOOP
    reason: str
    signal: Optional[str] = None    # BUY | SELL when WOULD_FIRE
    entry_price: Optional[float] = None
    sl_pips: Optional[float] = None
    tp_pips: Optional[float] = None
    debug: Dict[str, Any] = field(default_factory=dict)


def on_bar_close(
    pair: str, epic: Optional[str], bar_ts_utc: datetime,
    bar_open: float, bar_high: float, bar_low: float, bar_close: float,
    ppp: Optional[float] = None,
) -> Optional[Result]:
    """Called on every closed 5m bar for every tracked pair.

    Contract:
      * Never raises.
      * Under NEWS_STRATEGY_MODE=off, returns None immediately (no
        evaluation, no eval-log write).
      * Under shadow/enforce with a stale calendar, emits a DECLINE
        eval row with reason=stale_calendar and returns Result(verdict=DECLINE).
      * Under enforce and a valid WOULD_FIRE assessment, returns a
        Result with signal/entry/SL/TP populated; the caller is expected
        to route this into execute_trade.
    """
    try:
        mode = _mode()
        if mode == "off":
            return None
        pair_u = (pair or "").upper()
        if pair_u not in _PAIR_CCYS:
            return None
        if ppp is None or ppp <= 0:
            ppp = _pip_size_for(pair_u)

        # Hard staleness gate — first, before ANY firing consideration.
        try:
            import news_calendar_health as _nch
            if _nch.is_stale():
                _emit_row(_row("STALE", pair_u, epic, bar_ts_utc, None,
                               verdict="DECLINE",
                               reason="stale_calendar",
                               extra={"calendar_age_hours": _nch.age_hours()}))
                return Result(verdict="DECLINE", reason="stale_calendar")
        except Exception:
            # Fail-safe: if the staleness check itself blows up, treat as
            # stale (strategy structurally incapable of firing under
            # uncertainty).
            _emit_row(_row("STALE", pair_u, epic, bar_ts_utc, None,
                           verdict="DECLINE",
                           reason="stale_calendar_check_error"))
            return Result(verdict="DECLINE", reason="stale_calendar_check_error")

        anchor = _anchors_by_pair.get(pair_u)

        # Anchor start: this bar contains a qualifying release.
        ev = _qualifying_release_for_bar(pair_u, bar_ts_utc)
        if ev is not None and (anchor is None or anchor.fired
                               or anchor.bars_seen >= _decision_candles()):
            anchor = _AnchorState(
                release_key=f"{ev['event_name']}|{int(ev['release_ts'])}",
                release_ts=float(ev["release_ts"]),
                event_name=ev["event_name"],
                currency=ev["currency"],
                anchor_price=float(bar_open),
                bars_seen=1,
                highs=[float(bar_high)],
                lows=[float(bar_low)],
                closes=[float(bar_close)],
            )
            _anchors_by_pair[pair_u] = anchor
            _emit_row(_row("ANCHORED", pair_u, epic, bar_ts_utc, anchor,
                           verdict="NOOP", reason="release_bar_captured",
                           extra={"anchor_price": anchor.anchor_price}))
            return Result(verdict="NOOP", reason="release_bar_captured")

        # No anchor active → nothing to do.
        if anchor is None or anchor.fired:
            return None

        # Accumulate post-release bar.
        anchor.bars_seen += 1
        anchor.highs.append(float(bar_high))
        anchor.lows.append(float(bar_low))
        anchor.closes.append(float(bar_close))

        # Not yet at decision boundary → keep accumulating.
        if anchor.bars_seen < _decision_candles() + 1:
            _emit_row(_row("OBSERVING", pair_u, epic, bar_ts_utc, anchor,
                           verdict="NOOP", reason="post_release_observing",
                           extra={"anchor_price": anchor.anchor_price}))
            return Result(verdict="NOOP", reason="post_release_observing")

        # Decision bar reached — compute spike + retrace.
        peak_up = max(anchor.highs) - anchor.anchor_price
        peak_down = anchor.anchor_price - min(anchor.lows)
        if peak_up >= peak_down:
            spike_dir = "UP"
            spike_pips = peak_up / float(ppp)
            spike_extreme_price = max(anchor.highs)
        else:
            spike_dir = "DOWN"
            spike_pips = peak_down / float(ppp)
            spike_extreme_price = min(anchor.lows)

        last_close = anchor.closes[-1]
        if spike_dir == "UP":
            retrace_price = spike_extreme_price - last_close
        else:
            retrace_price = last_close - spike_extreme_price
        spike_price = abs(spike_extreme_price - anchor.anchor_price)
        retrace_frac = (
            0.0 if spike_price <= 0 else max(0.0, retrace_price / spike_price)
        )
        common_extra = {
            "spike_direction": spike_dir,
            "spike_magnitude_pips": round(spike_pips, 3),
            "retrace_fraction": round(retrace_frac, 4),
            "anchor_price": anchor.anchor_price,
            "spike_extreme_price": spike_extreme_price,
            "last_close": last_close,
            "decision_candles": _decision_candles(),
            "params": {
                "NEWS_SPIKE_MIN_PIPS": _spike_min_pips(),
                "NEWS_FADE_BODY_PCT": _fade_body_pct(),
                "NEWS_CONTINUATION_ENABLED": _continuation_enabled(),
                "NEWS_SL_PIPS": _sl_pips(),
                "NEWS_TP_PIPS": _tp_pips(),
            },
        }

        # Below minimum spike → DECLINE.
        if spike_pips < _spike_min_pips():
            anchor.fired = True
            _emit_row(_row("DECISION", pair_u, epic, bar_ts_utc, anchor,
                           verdict="DECLINE", reason="spike_below_min",
                           extra=common_extra))
            return Result(verdict="DECLINE", reason="spike_below_min",
                          debug=common_extra)

        # Fade path — retrace crosses threshold.
        if retrace_frac >= _fade_body_pct():
            signal = "SELL" if spike_dir == "UP" else "BUY"
            _emit_row(_row("DECISION", pair_u, epic, bar_ts_utc, anchor,
                           verdict="WOULD_FIRE",
                           reason="fade_retrace_triggered",
                           extra={**common_extra, "leg": "FADE",
                                  "signal": signal,
                                  "entry_price": last_close,
                                  "sl_pips": _sl_pips(),
                                  "tp_pips": _tp_pips()}))
            anchor.fired = True
            return Result(verdict="WOULD_FIRE",
                          reason="fade_retrace_triggered",
                          signal=signal, entry_price=last_close,
                          sl_pips=_sl_pips(), tp_pips=_tp_pips(),
                          debug={**common_extra, "leg": "FADE"})

        # Continuation path — only if enabled AND no retrace.
        if _continuation_enabled() and retrace_frac < _fade_body_pct():
            signal = "BUY" if spike_dir == "UP" else "SELL"
            _emit_row(_row("DECISION", pair_u, epic, bar_ts_utc, anchor,
                           verdict="WOULD_FIRE",
                           reason="continuation_no_retrace",
                           extra={**common_extra, "leg": "CONTINUATION",
                                  "signal": signal,
                                  "entry_price": last_close,
                                  "sl_pips": _sl_pips(),
                                  "tp_pips": _tp_pips()}))
            anchor.fired = True
            return Result(verdict="WOULD_FIRE",
                          reason="continuation_no_retrace",
                          signal=signal, entry_price=last_close,
                          sl_pips=_sl_pips(), tp_pips=_tp_pips(),
                          debug={**common_extra, "leg": "CONTINUATION"})

        # No setup formed.
        anchor.fired = True
        _emit_row(_row("DECISION", pair_u, epic, bar_ts_utc, anchor,
                       verdict="DECLINE", reason="no_setup",
                       extra=common_extra))
        return Result(verdict="DECLINE", reason="no_setup",
                      debug=common_extra)
    except Exception as exc:
        logger.debug("[NEWS-RA] on_bar_close error (fail-open): %s",
                     exc, exc_info=True)
        return None
