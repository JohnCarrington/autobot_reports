"""
news_followthrough_observer.py — passive post-news follow-through observer.

Attached to news_strategy's state machine. On every ARMED news event (any
outcome — fired, timed out, skipped), keeps a passive observer alive for
NEWS_FOLLOWTHROUGH_OBS_WINDOW_MIN (default 90) minutes past release,
sampling on 5m closes. Writes JSONL rows to logs/news_followthrough.jsonl
tracking four phases plus a final row per event:

  IMPULSE        — first ~10 min: max move from anchor, direction, magnitude.
  CONSOLIDATION  — post-impulse digest: rolling range of last N bars vs
                   impulse magnitude, plus start_ts / range / duration_bars.
  BREAK          — first 5m close beyond the consolidation envelope.
  FOLLOW_THROUGH — MFE in break direction after break, plus end-of-window price.
  NONE           — window elapsed with no consolidation formed or no break.

Zero live-path effect: every entry point is wrapped fail-open; any error is
logged at DEBUG and swallowed. Reads only, never mutates news_strategy state.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("AutoBot")

# ---------------------------------------------------------------------------
# ENV — all sane defaults, all env-tunable.
# ---------------------------------------------------------------------------
ENABLED = str(os.getenv("NEWS_FOLLOWTHROUGH_OBS_ENABLED", "1")).strip().lower() in (
    "1", "true", "yes", "on",
)
WINDOW_MIN = float(os.getenv("NEWS_FOLLOWTHROUGH_OBS_WINDOW_MIN", "90"))
# Impulse phase = first N seconds after release; max |mid - anchor| across the
# window becomes the impulse magnitude.
IMPULSE_WINDOW_SEC = float(os.getenv("NEWS_FOLLOWTHROUGH_OBS_IMPULSE_SEC", "600"))
# Consolidation candidate = rolling window of N closed 5m bars whose total
# high-low range is <= CONS_RATIO * impulse_magnitude (both in pips).
CONS_MIN_BARS = int(os.getenv("NEWS_FOLLOWTHROUGH_OBS_CONS_MIN_BARS", "3"))
CONS_MAX_RANGE_RATIO = float(os.getenv("NEWS_FOLLOWTHROUGH_OBS_CONS_RANGE_RATIO", "0.6"))
# Floor: if impulse was tiny (<= this many pips), don't try to fit a
# consolidation — the ratio test becomes noisy. Log phase=NONE instead.
IMPULSE_MIN_PIPS = float(os.getenv("NEWS_FOLLOWTHROUGH_OBS_IMPULSE_MIN_PIPS", "3.0"))
# Break confirmation buffer in pips beyond the consolidation envelope.
BREAK_BUFFER_PIPS = float(os.getenv("NEWS_FOLLOWTHROUGH_OBS_BREAK_BUFFER_PIPS", "0.0"))

_LOG_PATH = Path("/opt/tradingbot/logs/news_followthrough.jsonl")
_BAR_SECS = 300  # 5-minute bar

# ---------------------------------------------------------------------------
# State — per (symbol, release_epoch) observation record.
# ---------------------------------------------------------------------------
_observations: Dict[str, "_Observation"] = {}
_lock = threading.Lock()


class _Observation:
    __slots__ = (
        "key", "symbol", "release_ts", "anchor", "event_name", "currency",
        "beat_miss", "deviation", "strategy_outcome", "pipsize",
        "daily_bias_direction",
        "cur_bucket", "cur_bar_open", "cur_bar_high", "cur_bar_low", "cur_bar_close",
        "bars",
        "impulse_dir", "impulse_mag_pips", "impulse_extreme_price",
        "impulse_extreme_ts", "impulse_done",
        "cons_start_ts", "cons_end_ts", "cons_low", "cons_high",
        "cons_range_pips", "cons_duration_bars", "cons_formed",
        "break_ts", "break_dir", "break_min_after_release", "break_price",
        "ft_mfe_pips", "ft_mfe_ts", "ft_end_price",
        "phase", "closed", "window_end_ts",
        "interim_rows_emitted",
    )

    def __init__(self, key: str, symbol: str, release_ts: float, anchor: float,
                 event_name: str, currency: str, beat_miss: Optional[str],
                 deviation: Optional[float], strategy_outcome: str,
                 pipsize: float, daily_bias_direction: Optional[str]) -> None:
        self.key = key
        self.symbol = symbol
        self.release_ts = float(release_ts)
        self.anchor = float(anchor)
        self.event_name = event_name or ""
        self.currency = currency or ""
        self.beat_miss = beat_miss
        self.deviation = deviation
        self.strategy_outcome = strategy_outcome
        self.pipsize = float(pipsize)
        self.daily_bias_direction = daily_bias_direction  # BULL/BEAR/NEUTRAL/None

        # Rolling 5m bar aggregator.
        self.cur_bucket: Optional[int] = None
        self.cur_bar_open: Optional[float] = None
        self.cur_bar_high: Optional[float] = None
        self.cur_bar_low: Optional[float] = None
        self.cur_bar_close: Optional[float] = None
        self.bars: List[Dict[str, Any]] = []

        # Phase 1 — impulse.
        self.impulse_dir: Optional[str] = None
        self.impulse_mag_pips: float = 0.0  # signed: + = UP, - = DOWN
        self.impulse_extreme_price: Optional[float] = None
        self.impulse_extreme_ts: Optional[float] = None
        self.impulse_done: bool = False

        # Phase 2 — consolidation.
        self.cons_start_ts: Optional[float] = None
        self.cons_end_ts: Optional[float] = None
        self.cons_low: Optional[float] = None
        self.cons_high: Optional[float] = None
        self.cons_range_pips: Optional[float] = None
        self.cons_duration_bars: int = 0
        self.cons_formed: bool = False

        # Phase 3 — break.
        self.break_ts: Optional[float] = None
        self.break_dir: Optional[str] = None
        self.break_min_after_release: Optional[float] = None
        self.break_price: Optional[float] = None

        # Phase 4 — follow-through.
        self.ft_mfe_pips: float = 0.0
        self.ft_mfe_ts: Optional[float] = None
        self.ft_end_price: Optional[float] = None

        self.phase: str = "IMPULSE"
        self.closed: bool = False
        self.window_end_ts: float = self.release_ts + WINDOW_MIN * 60.0
        self.interim_rows_emitted: set = set()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _daily_bias(symbol: str) -> Optional[str]:
    """Best-effort — returns BULL/BEAR/NEUTRAL or None. Never raises."""
    try:
        from d1_direction import compute_d1_direction_from_cache
        out = compute_d1_direction_from_cache(symbol)
        if isinstance(out, dict):
            d = out.get("direction")
            if isinstance(d, str):
                return d
    except Exception:
        logger.debug("[NEWS-FT-OBS] daily bias lookup failed", exc_info=True)
    return None


def _write_row(row: Dict[str, Any]) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = dict(row)
        row.setdefault("ts", _now_iso())
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        logger.debug("[NEWS-FT-OBS] write_row failed", exc_info=True)


def _agree_flag(direction_a: Optional[str], direction_b: Optional[str]) -> Optional[bool]:
    """True if both are the same non-empty direction; False if both non-empty
    and different; None if either is missing / neutral."""
    if not direction_a or not direction_b:
        return None
    a = direction_a.upper()
    b = direction_b.upper()
    if a in ("NEUTRAL", "FLAT", "NONE") or b in ("NEUTRAL", "FLAT", "NONE"):
        return None
    # Normalise BULL/BEAR (bias) vs UP/DOWN (price move) vs BUY/SELL.
    _up = {"UP", "BULL", "BULLISH", "BUY"}
    _dn = {"DOWN", "BEAR", "BEARISH", "SELL"}
    a_up = a in _up
    b_up = b in _up
    a_dn = a in _dn
    b_dn = b in _dn
    if not (a_up or a_dn) or not (b_up or b_dn):
        return None
    return (a_up and b_up) or (a_dn and b_dn)


def _make_key(symbol: str, release_ts: float) -> str:
    return f"{str(symbol).upper()}:{int(release_ts)}"


# ---------------------------------------------------------------------------
# Public entry points (all fail-open).
# ---------------------------------------------------------------------------
def notify_armed(symbol: str, release_ts: float, anchor: float,
                 event_name: str, currency: str,
                 beat_miss: Optional[str], deviation: Optional[float],
                 strategy_outcome: str, pipsize: float) -> None:
    """Open a new observation record (or update outcome if it already exists).

    Called on IDLE→ARMED to seed the observer. Safe to call multiple times
    for the same event — later calls only refresh strategy_outcome / actuals
    fields as they become known.
    """
    if not ENABLED:
        return
    try:
        with _lock:
            key = _make_key(symbol, release_ts)
            obs = _observations.get(key)
            if obs is None:
                obs = _Observation(
                    key=key,
                    symbol=str(symbol).upper(),
                    release_ts=float(release_ts),
                    anchor=float(anchor),
                    event_name=event_name,
                    currency=currency,
                    beat_miss=beat_miss,
                    deviation=deviation,
                    strategy_outcome=strategy_outcome,
                    pipsize=float(pipsize),
                    daily_bias_direction=_daily_bias(str(symbol).upper()),
                )
                _observations[key] = obs
                _write_row({
                    "kind": "OBS_OPEN",
                    "symbol": obs.symbol,
                    "release_ts": obs.release_ts,
                    "event_name": obs.event_name,
                    "currency": obs.currency,
                    "anchor": obs.anchor,
                    "beat_miss": obs.beat_miss,
                    "deviation": obs.deviation,
                    "strategy_outcome": obs.strategy_outcome,
                    "daily_bias_direction": obs.daily_bias_direction,
                    "window_end_ts": obs.window_end_ts,
                    "window_min": WINDOW_MIN,
                })
            else:
                # Refresh known-later fields.
                if beat_miss is not None:
                    obs.beat_miss = beat_miss
                if deviation is not None:
                    obs.deviation = deviation
                if strategy_outcome:
                    obs.strategy_outcome = strategy_outcome
    except Exception:
        logger.debug("[NEWS-FT-OBS] notify_armed failed", exc_info=True)


def notify_outcome(symbol: str, release_ts: float, outcome: str,
                   extra: Optional[Dict[str, Any]] = None) -> None:
    """Update strategy_outcome for an existing observation (e.g., ARMED_TIMEOUT,
    SPIKE_DETECTED, WOULD_FIRE, FIRE). Observer keeps running past this."""
    if not ENABLED:
        return
    try:
        with _lock:
            key = _make_key(symbol, release_ts)
            obs = _observations.get(key)
            if obs is None:
                return
            obs.strategy_outcome = outcome
            row = {
                "kind": "OBS_STRATEGY_OUTCOME",
                "symbol": obs.symbol,
                "release_ts": obs.release_ts,
                "outcome": outcome,
            }
            if extra:
                row["extra"] = extra
            _write_row(row)
    except Exception:
        logger.debug("[NEWS-FT-OBS] notify_outcome failed", exc_info=True)


def on_tick(symbol: str, ts: float, mid: float, pipsize: float) -> None:
    """Push a tick to every open observation for this symbol.

    Called at the top of news_strategy.evaluate() for every tick. Ticks
    before release_ts are ignored; ticks after window_end_ts trigger finalise.
    """
    if not ENABLED:
        return
    try:
        sym = str(symbol).upper()
        with _lock:
            keys = [k for k in _observations if k.startswith(sym + ":")]
            for key in keys:
                obs = _observations[key]
                if obs.closed:
                    continue
                try:
                    _process_tick(obs, float(ts), float(mid))
                except Exception:
                    logger.debug("[NEWS-FT-OBS] process_tick failed", exc_info=True)
                if ts >= obs.window_end_ts and not obs.closed:
                    _finalise(obs, float(ts), float(mid))
            # Drop closed observations from the map.
            for key in list(_observations):
                if _observations[key].closed:
                    _observations.pop(key, None)
    except Exception:
        logger.debug("[NEWS-FT-OBS] on_tick failed", exc_info=True)


# ---------------------------------------------------------------------------
# Internals.
# ---------------------------------------------------------------------------
def _process_tick(obs: _Observation, ts: float, mid: float) -> None:
    if ts < obs.release_ts:
        return

    since_release = ts - obs.release_ts
    ps = obs.pipsize if obs.pipsize > 0 else 0.0001

    # Phase 1 — impulse magnitude (unsigned max abs move from anchor).
    if not obs.impulse_done:
        move_price = mid - obs.anchor
        move_pips = move_price / ps
        if abs(move_pips) > abs(obs.impulse_mag_pips):
            obs.impulse_mag_pips = move_pips
            obs.impulse_extreme_price = mid
            obs.impulse_extreme_ts = ts
        if since_release >= IMPULSE_WINDOW_SEC:
            if obs.impulse_mag_pips > 0:
                obs.impulse_dir = "UP"
            elif obs.impulse_mag_pips < 0:
                obs.impulse_dir = "DOWN"
            else:
                obs.impulse_dir = "FLAT"
            obs.impulse_done = True
            obs.phase = "CONSOLIDATION"
            _emit_interim(obs, "IMPULSE_DONE")

    # 5-minute bar aggregation (post-release only).
    bucket = int(ts // _BAR_SECS)
    if obs.cur_bucket is None:
        obs.cur_bucket = bucket
        obs.cur_bar_open = mid
        obs.cur_bar_high = mid
        obs.cur_bar_low = mid
        obs.cur_bar_close = mid
    elif bucket > obs.cur_bucket:
        closed_bar = {
            "bucket": obs.cur_bucket,
            "close_ts": (obs.cur_bucket + 1) * _BAR_SECS,
            "open": obs.cur_bar_open,
            "high": obs.cur_bar_high,
            "low": obs.cur_bar_low,
            "close": obs.cur_bar_close,
        }
        obs.bars.append(closed_bar)
        obs.cur_bucket = bucket
        obs.cur_bar_open = mid
        obs.cur_bar_high = mid
        obs.cur_bar_low = mid
        obs.cur_bar_close = mid
        _on_bar_close(obs, closed_bar)
    else:
        if mid > (obs.cur_bar_high or mid):
            obs.cur_bar_high = mid
        if mid < (obs.cur_bar_low or mid):
            obs.cur_bar_low = mid
        obs.cur_bar_close = mid

    # Follow-through MFE tracking — cheap, on every tick after break.
    if obs.break_dir is not None and obs.break_price is not None:
        if obs.break_dir == "UP":
            mfe = (mid - obs.break_price) / ps
        else:
            mfe = (obs.break_price - mid) / ps
        if mfe > obs.ft_mfe_pips:
            obs.ft_mfe_pips = mfe
            obs.ft_mfe_ts = ts


def _on_bar_close(obs: _Observation, bar: Dict[str, Any]) -> None:
    """Evaluate consolidation / break phase transitions on each closed 5m bar."""
    if not obs.impulse_done:
        return  # too early — impulse phase still running
    ps = obs.pipsize if obs.pipsize > 0 else 0.0001
    impulse_mag = abs(obs.impulse_mag_pips)

    if impulse_mag < IMPULSE_MIN_PIPS:
        # Tiny impulse — don't chase a consolidation fit; log nothing extra
        # and let the finalise path record phase=NONE at window end.
        return

    # Consolidation candidate: last CONS_MIN_BARS closed bars post-impulse,
    # excluding any bars that overlapped the impulse window itself.
    impulse_end_ts = obs.release_ts + IMPULSE_WINDOW_SEC
    post_impulse_bars = [b for b in obs.bars if b["close_ts"] > impulse_end_ts]

    if not obs.cons_formed:
        if len(post_impulse_bars) < CONS_MIN_BARS:
            return
        window = post_impulse_bars[-CONS_MIN_BARS:]
        hi = max(b["high"] for b in window)
        lo = min(b["low"] for b in window)
        rng_pips = (hi - lo) / ps
        max_allowed = CONS_MAX_RANGE_RATIO * impulse_mag
        if rng_pips <= max_allowed:
            obs.cons_formed = True
            obs.cons_start_ts = window[0]["close_ts"] - _BAR_SECS  # bar open of first
            obs.cons_low = lo
            obs.cons_high = hi
            obs.cons_range_pips = rng_pips
            obs.cons_duration_bars = len(window)
            obs.phase = "BREAK_WATCH"
            _emit_interim(obs, "CONSOLIDATION_FORMED")
        return

    # Consolidation exists — extend envelope with the just-closed bar until
    # a break occurs, then record the break.
    if obs.break_ts is None:
        # Update envelope with this new bar if it's still contained (extends
        # duration); otherwise it's the break.
        buf = BREAK_BUFFER_PIPS * ps
        close = bar["close"]
        broke_up = close > (obs.cons_high or 0.0) + buf
        broke_dn = close < (obs.cons_low or 0.0) - buf
        if broke_up or broke_dn:
            obs.break_ts = bar["close_ts"]
            obs.break_dir = "UP" if broke_up else "DOWN"
            obs.break_price = close
            obs.break_min_after_release = (bar["close_ts"] - obs.release_ts) / 60.0
            # Initialise FT tracking from the break bar itself.
            obs.ft_mfe_pips = 0.0
            obs.ft_end_price = close
            obs.phase = "FOLLOW_THROUGH"
            _emit_interim(obs, "BREAK")
        else:
            # Bar contained — extend envelope high/low; duration grows.
            if close < (obs.cons_low or close):
                obs.cons_low = bar["low"]
            if close > (obs.cons_high or close):
                obs.cons_high = bar["high"]
            # Recompute low/high across the extended window to be safe.
            obs.cons_low = min(obs.cons_low or bar["low"], bar["low"])
            obs.cons_high = max(obs.cons_high or bar["high"], bar["high"])
            obs.cons_range_pips = ((obs.cons_high or 0.0) - (obs.cons_low or 0.0)) / ps
            obs.cons_duration_bars += 1


def _emit_interim(obs: _Observation, kind: str) -> None:
    if kind in obs.interim_rows_emitted:
        return
    obs.interim_rows_emitted.add(kind)
    row = _snapshot_row(obs, kind=f"PHASE_{kind}")
    _write_row(row)


def _snapshot_row(obs: _Observation, *, kind: str,
                  final: bool = False) -> Dict[str, Any]:
    impulse_dir = obs.impulse_dir
    break_dir = obs.break_dir
    return {
        "kind": kind,
        "symbol": obs.symbol,
        "release_ts": obs.release_ts,
        "event_name": obs.event_name,
        "currency": obs.currency,
        "anchor": obs.anchor,
        "beat_miss": obs.beat_miss,
        "deviation": obs.deviation,
        "strategy_outcome": obs.strategy_outcome,
        "impulse": {
            "dir": impulse_dir,
            "mag_pips": round(abs(obs.impulse_mag_pips), 3),
            "signed_pips": round(obs.impulse_mag_pips, 3),
            "extreme_price": obs.impulse_extreme_price,
            "extreme_ts": obs.impulse_extreme_ts,
            "done": obs.impulse_done,
        },
        "consolidation": {
            "formed": obs.cons_formed,
            "start_ts": obs.cons_start_ts,
            "low": obs.cons_low,
            "high": obs.cons_high,
            "range_pips": (round(obs.cons_range_pips, 3)
                           if obs.cons_range_pips is not None else None),
            "duration_bars": obs.cons_duration_bars,
        },
        "break": {
            "ts": obs.break_ts,
            "dir": break_dir,
            "price": obs.break_price,
            "min_after_release": (round(obs.break_min_after_release, 2)
                                  if obs.break_min_after_release is not None else None),
            "agree_with_impulse": _agree_flag(break_dir, impulse_dir),
            "agree_with_daily_bias": _agree_flag(break_dir, obs.daily_bias_direction),
        },
        "follow_through": {
            "mfe_pips": round(obs.ft_mfe_pips, 3),
            "mfe_ts": obs.ft_mfe_ts,
            "end_price": obs.ft_end_price,
        },
        "daily_bias_direction": obs.daily_bias_direction,
        "phase_at_row": obs.phase,
        "final": final,
    }


def _finalise(obs: _Observation, ts: float, mid: float) -> None:
    obs.ft_end_price = mid
    # Determine terminal phase label for the final row.
    if not obs.cons_formed:
        obs.phase = "NONE_NO_CONSOLIDATION"
    elif obs.break_ts is None:
        obs.phase = "NONE_NO_BREAK"
    else:
        obs.phase = "FOLLOW_THROUGH_DONE"
    row = _snapshot_row(obs, kind="OBS_FINAL", final=True)
    _write_row(row)
    obs.closed = True


# ---------------------------------------------------------------------------
# Test / diagnostic helper — not called from live path.
# ---------------------------------------------------------------------------
def _active_keys() -> List[str]:
    with _lock:
        return list(_observations.keys())
