"""news_momentum_observer.py — post-release RESOLUTION observer
(2026-07-26).

Thesis (operator): the tradeable news move is often not the spike but
the RESOLUTION — 30-60 minutes post-release, after the initial reaction
and retrace wash out, the market commits to the real direction. The
first 15 minutes is spread-blown and stop-swept; the resolution is
where a holding move tends to start.

STATUS: observation ONLY. No entry logic, no order path, no executor
wiring. This module is a pure bystander.

Design choice — deferred cache-reader, NOT live-loop entanglement:
  The observer needs bars from release+5m through release+180m. To
  produce zero REST calls and zero latency in any fire path it reads
  the existing rolling 5m candle cache
  (cache/{PAIR}_candles_rolling.csv) that _on_5m_close_log already
  writes for other consumers. It runs on a deferred sweep — a
  throttled hook at the tail of _on_5m_close_log — and only emits
  rows for releases whose (release + NEWS_MOM_OUTCOME_END_MIN) has
  already passed. The live 5m close handler does not wait for it and
  it never calls the executor.

Modes (env NEWS_MOMENTUM_MODE):
  observe — the only implemented mode. Sweep runs; rows written.
  off     — sweep is a no-op; nothing written.
  shadow/enforce — RESERVED. Not implemented in this task. Treated as
                   observe. (Trade spec comes later, from the rows.)

Row schema — one JSONL row per (release_key, pair) into
logs/news_momentum_obs.jsonl. See _row() for the field-by-field shape.
Every failure path is null-safe; exceptions never propagate.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── Env / config ──────────────────────────────────────────────────────────
def _env(name: str, default: str) -> str:
    return str(os.getenv(name, default))


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)).strip())
    except Exception:
        return int(default)


def _mode() -> str:
    m = _env("NEWS_MOMENTUM_MODE", "off").strip().lower()
    if m in ("shadow", "enforce"):
        # RESERVED — not implemented. Treat as observe for now.
        m = "observe"
    if m not in ("off", "observe"):
        m = "off"
    return m


def _min_impact() -> str:
    return _env("NEWS_MIN_IMPACT", "HIGH").strip().upper()


def _range_start_min() -> int:
    return max(0, _env_int("NEWS_MOM_RANGE_START_MIN", 5))


def _range_end_min() -> int:
    return max(_range_start_min() + 1, _env_int("NEWS_MOM_RANGE_END_MIN", 30))


def _obs_start_min() -> int:
    return max(_range_end_min(), _env_int("NEWS_MOM_OBS_START_MIN", 30))


def _obs_end_min() -> int:
    return max(_obs_start_min() + 1, _env_int("NEWS_MOM_OBS_END_MIN", 60))


def _outcome_end_min() -> int:
    return max(_obs_end_min(), _env_int("NEWS_MOM_OUTCOME_END_MIN", 180))


_IMPACT_RANK = {"LOW": 1, "MED": 2, "HIGH": 3}

# Pairs whose bars we observe. Mirrors news_strategy_release_anchored._PAIR_CCYS.
_PAIR_CCYS: Dict[str, Tuple[str, ...]] = {
    "GBPUSD": ("GBP", "USD"),
    "EURUSD": ("EUR", "USD"),
    "USDJPY": ("USD", "JPY"),
    "USDCAD": ("USD", "CAD"),
    "GBPJPY": ("GBP", "JPY"),
}


_OBS_LOG_PATH = Path(_env(
    "NEWS_MOMENTUM_OBS_LOG_PATH",
    "/opt/tradingbot/logs/news_momentum_obs.jsonl",
))
_EVALS_LOG_PATH = Path(_env(
    "NEWS_STRATEGY_EVALS_LOG_PATH",
    "/opt/tradingbot/logs/news_strategy_evals.jsonl",
))
_CACHE_DIR = Path(_env("CACHE_DIR", "/opt/tradingbot/cache"))
_NEWS_CACHE_DIR = Path(_env("NEWS_STATE_CACHE_DIR", "/opt/tradingbot/cache"))

# Sweep throttle: no more than once per this many seconds.
_SWEEP_MIN_INTERVAL_S = float(_env("NEWS_MOMENTUM_SWEEP_MIN_INTERVAL_S", "900"))


# ─── Process-scoped dedup + throttle state ─────────────────────────────────
@dataclass
class _State:
    emitted: set                 # {(release_key, pair)} already written
    bootstrapped: bool
    last_sweep_ts: float


_state = _State(emitted=set(), bootstrapped=False, last_sweep_ts=0.0)


def _reset_state_for_tests() -> None:
    _state.emitted.clear()
    _state.bootstrapped = False
    _state.last_sweep_ts = 0.0


# ─── I/O helpers (all read-only, all null-safe) ────────────────────────────
def _pip_size_for(pair: str) -> float:
    try:
        from pair_config import get_ppp
        return float(get_ppp(pair))
    except Exception:
        return 0.01 if (pair or "").upper().endswith("JPY") else 0.0001


def _load_events_for_day(day: datetime) -> List[Dict[str, Any]]:
    try:
        day_str = day.strftime("%Y-%m-%d")
        path = _NEWS_CACHE_DIR / f"news_state_finnhub_{day_str}.json"
        if not path.exists():
            return []
        with path.open("r") as fh:
            data = json.load(fh)
        return list(data.get("events") or [])
    except Exception:
        return []


def _load_qualifying_releases(now: datetime) -> List[Dict[str, Any]]:
    """Union of today's and yesterday's cached events, filtered to
    ≥ NEWS_MIN_IMPACT. Each returned dict is normalised as
    {release_key, release_ts (float), release_ts_iso, event_name,
    currency, impact}."""
    min_rank = _IMPACT_RANK.get(_min_impact(), 3)
    out: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for day in (now - timedelta(days=1), now):
        for ev in _load_events_for_day(day):
            try:
                impact = str(ev.get("impact") or "").upper()
                if _IMPACT_RANK.get(impact, 0) < min_rank:
                    continue
                ts_raw = str(ev.get("ts") or "")
                ts_dt = datetime.fromisoformat(ts_raw)
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                else:
                    ts_dt = ts_dt.astimezone(timezone.utc)
                event_name = str(ev.get("event") or "")
                currency = str(ev.get("currency") or "").upper()
                release_key = f"{event_name}|{int(ts_dt.timestamp())}"
                if release_key in seen_keys:
                    continue
                seen_keys.add(release_key)
                out.append({
                    "release_key": release_key,
                    "release_ts": ts_dt.timestamp(),
                    "release_ts_iso": ts_dt.isoformat(),
                    "event_name": event_name,
                    "currency": currency,
                    "impact": impact,
                })
            except Exception:
                continue
    return out


def _bars_from_rolling_cache(pair: str) -> List[Tuple[datetime, float, float, float, float]]:
    """Return the pair's rolling 5m bars as [(ts_utc, o, h, l, c), ...].
    Empty list on any parse failure. Read-only; never modifies the file."""
    try:
        import csv
        path = _CACHE_DIR / f"{pair.upper()}_candles_rolling.csv"
        if not path.exists():
            return []
        out: List[Tuple[datetime, float, float, float, float]] = []
        with path.open("r") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    ts_raw = str(row.get("timestamp") or "").strip()
                    if not ts_raw:
                        continue
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    else:
                        ts = ts.astimezone(timezone.utc)
                    o = float(row["open"])
                    h = float(row["high"])
                    lo = float(row["low"])
                    c = float(row["close"])
                    out.append((ts, o, h, lo, c))
                except Exception:
                    continue
        out.sort(key=lambda r: r[0])
        return out
    except Exception:
        return []


def _bootstrap_emitted_from_log() -> None:
    """One-shot: scan the observation log and seed the (release_key, pair)
    dedup set so restarts don't re-emit."""
    if _state.bootstrapped:
        return
    _state.bootstrapped = True
    try:
        if not _OBS_LOG_PATH.exists():
            return
        with _OBS_LOG_PATH.open("r") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    key = obj.get("release_key")
                    pair = obj.get("symbol")
                    if key and pair:
                        _state.emitted.add((str(key), str(pair).upper()))
                except Exception:
                    continue
    except Exception:
        pass


def _join_spike_from_eval(release_key: str, pair: str) -> Dict[str, Any]:
    """Look through the release-anchored eval log for a DECISION row on
    (release_key, pair) and return {spike_direction, spike_magnitude_pips,
    spike_source}. Empty dict when no join is available (null-safe)."""
    try:
        if not _EVALS_LOG_PATH.exists():
            return {}
        candidates: List[Dict[str, Any]] = []
        with _EVALS_LOG_PATH.open("r") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                kind = str(obj.get("kind") or "")
                if not kind.startswith("RELEASE_ANCHORED_"):
                    continue
                if str(obj.get("release_key") or "") != release_key:
                    continue
                if str(obj.get("symbol") or "").upper() != pair.upper():
                    continue
                candidates.append(obj)
        if not candidates:
            return {}
        # Prefer a DECISION-kind row (has the resolved spike fields).
        pref = [c for c in candidates if str(c.get("kind")) == "RELEASE_ANCHORED_DECISION"]
        row = (pref or candidates)[-1]
        return {
            "spike_direction": row.get("spike_direction"),
            "spike_magnitude_pips": row.get("spike_magnitude_pips"),
            "spike_source": "news_strategy_release_anchored_eval",
        }
    except Exception:
        return {}


def _emit_row(row: Dict[str, Any]) -> None:
    try:
        _OBS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _OBS_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


# ─── Phase computation ─────────────────────────────────────────────────────
def _bars_between(
    bars: Iterable[Tuple[datetime, float, float, float, float]],
    start: datetime, end: datetime,
) -> List[Tuple[datetime, float, float, float, float]]:
    """Half-open [start, end). Bar timestamp is bar-OPEN time."""
    return [b for b in bars if start <= b[0] < end]


def _compute_observation(
    pair: str, release: Dict[str, Any],
    bars: List[Tuple[datetime, float, float, float, float]],
    ppp: float, calendar_age_hours: Optional[float],
) -> Dict[str, Any]:
    """Build the full observation row for one (release, pair). Never
    raises — every field derived from bars is defensively wrapped."""
    release_ts = float(release["release_ts"])
    release_dt = datetime.fromtimestamp(release_ts, tz=timezone.utc)

    range_start = release_dt + timedelta(minutes=_range_start_min())
    range_end = release_dt + timedelta(minutes=_range_end_min())
    obs_start = release_dt + timedelta(minutes=_obs_start_min())
    obs_end = release_dt + timedelta(minutes=_obs_end_min())
    outcome_end = release_dt + timedelta(minutes=_outcome_end_min())

    # PHASE A — settling range from bars in [range_start, range_end).
    range_bars = _bars_between(bars, range_start, range_end)
    if range_bars:
        range_high = max(b[2] for b in range_bars)
        range_low = min(b[3] for b in range_bars)
        range_width_pips = (range_high - range_low) / ppp if ppp > 0 else None
    else:
        range_high = None
        range_low = None
        range_width_pips = None

    # PHASE B — resolution watch in [obs_start, obs_end): first 5m bar
    # whose CLOSE is beyond the settling range.
    resolution: Dict[str, Any] = {
        "resolution_ts_utc": None,
        "resolution_minutes_from_release": None,
        "resolution_side": None,
        "resolution_break_close": None,
        "resolution_bar_body_pips": None,
        "resolution_bar_range_pips": None,
    }
    obs_bars = _bars_between(bars, obs_start, obs_end)
    if range_high is not None and range_low is not None:
        for (ts, o, h, lo, c) in obs_bars:
            side = None
            if c > range_high:
                side = "UP"
            elif c < range_low:
                side = "DOWN"
            if side is None:
                continue
            body_pips = abs(c - o) / ppp if ppp > 0 else None
            rng_pips = (h - lo) / ppp if ppp > 0 else None
            resolution.update({
                "resolution_ts_utc": ts.isoformat(),
                "resolution_minutes_from_release": int(
                    (ts - release_dt).total_seconds() // 60
                ),
                "resolution_side": side,
                "resolution_break_close": c,
                "resolution_bar_body_pips": (
                    round(body_pips, 3) if body_pips is not None else None
                ),
                "resolution_bar_range_pips": (
                    round(rng_pips, 3) if rng_pips is not None else None
                ),
            })
            break

    # Spike-join (nullable).
    spike = _join_spike_from_eval(release["release_key"], pair)
    spike_direction = spike.get("spike_direction")
    spike_magnitude_pips = spike.get("spike_magnitude_pips")
    spike_source = spike.get("spike_source")

    # Agreement classification.
    if resolution["resolution_side"] is None:
        agreement = None
    elif spike_direction not in ("UP", "DOWN"):
        agreement = "no_spike"
    elif resolution["resolution_side"] == spike_direction:
        agreement = "continuation"
    else:
        agreement = "reversal"

    # PHASE C — outcome window. Starts at resolution close if we have one,
    # else at obs_end. Ends at outcome_end. Excursions measured in the
    # break direction (or, if no break, in each direction against the
    # resolution start close for reporting completeness — null when we
    # have neither anchor).
    verdict = "observed" if resolution["resolution_side"] else "no_resolution"
    mfe_pips: Optional[float] = None
    mae_pips: Optional[float] = None
    if resolution["resolution_side"]:
        # Start where the break happened. Resolution ts is the break bar
        # OPEN; measure excursion from resolution_break_close (bar close).
        break_ts = datetime.fromisoformat(
            str(resolution["resolution_ts_utc"])
        )
        # Bars strictly AFTER the break bar, up to outcome_end.
        outcome_bars = [b for b in bars
                        if b[0] > break_ts and b[0] < outcome_end]
        if outcome_bars and ppp > 0:
            base = float(resolution["resolution_break_close"])
            if resolution["resolution_side"] == "UP":
                mfe = max((b[2] for b in outcome_bars), default=base) - base
                mae = base - min((b[3] for b in outcome_bars), default=base)
            else:
                mfe = base - min((b[3] for b in outcome_bars), default=base)
                mae = max((b[2] for b in outcome_bars), default=base) - base
            mfe_pips = round(max(0.0, mfe / ppp), 3)
            mae_pips = round(max(0.0, mae / ppp), 3)

    row = {
        "kind": "NEWS_MOMENTUM_OBS",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "mode": _mode(),
        # Release identity — joins to RA eval row on release_key.
        "release_key": release["release_key"],
        "release_name": release.get("event_name"),
        "release_currency": release.get("currency"),
        "release_impact": release.get("impact"),
        "release_ts_iso": release.get("release_ts_iso"),
        "symbol": pair.upper(),
        # Calendar freshness snapshot.
        "calendar_age_hours_at_obs": (
            round(calendar_age_hours, 3)
            if calendar_age_hours is not None else None
        ),
        # PHASE A window + result.
        "range_start_min": _range_start_min(),
        "range_end_min": _range_end_min(),
        "range_high": range_high,
        "range_low": range_low,
        "range_width_pips": (
            round(range_width_pips, 3) if range_width_pips is not None else None
        ),
        # Spike (joined, nullable).
        "spike_direction": spike_direction,
        "spike_magnitude_pips": spike_magnitude_pips,
        "spike_source": spike_source,
        # PHASE B window + result.
        "obs_start_min": _obs_start_min(),
        "obs_end_min": _obs_end_min(),
        **resolution,
        "agreement_with_spike": agreement,
        # PHASE C outcome.
        "outcome_end_min": _outcome_end_min(),
        "mfe_pips": mfe_pips,
        "mae_pips": mae_pips,
        # Overall verdict — "observed" (had a resolution) | "no_resolution".
        "verdict": verdict,
    }
    return row


# ─── Public entry points ───────────────────────────────────────────────────
def observe_release(
    release: Dict[str, Any], pair: str, now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Compute and emit ONE observation row for (release, pair). Returns
    the emitted row or None (never raises). Used directly by tests and by
    sweep()."""
    try:
        if _mode() == "off":
            return None
        pair_u = (pair or "").upper()
        if pair_u not in _PAIR_CCYS:
            return None
        now = now or datetime.now(timezone.utc)
        # Staleness gate — no row when stale, only a debug log.
        try:
            import news_calendar_health as _nch
            if _nch.is_stale():
                logger.debug(
                    "[NEWS-MOM] skip release=%s pair=%s stale_calendar age=%s",
                    release.get("release_key"), pair_u,
                    _nch.age_hours(),
                )
                return None
            calendar_age_hours = _nch.age_hours()
        except Exception:
            logger.debug(
                "[NEWS-MOM] stale-check failed for release=%s pair=%s "
                "(bystander; skipping)",
                release.get("release_key"), pair_u, exc_info=True,
            )
            return None

        # Outcome window must have fully elapsed.
        release_dt = datetime.fromtimestamp(
            float(release["release_ts"]), tz=timezone.utc
        )
        if now < release_dt + timedelta(minutes=_outcome_end_min()):
            return None

        # Currency filter — release currency must be one of the pair's ccys.
        ccys = _PAIR_CCYS.get(pair_u)
        if not ccys or (release.get("currency") or "").upper() not in ccys:
            return None

        _bootstrap_emitted_from_log()
        key = (release["release_key"], pair_u)
        if key in _state.emitted:
            return None

        ppp = _pip_size_for(pair_u)
        bars = _bars_from_rolling_cache(pair_u)
        row = _compute_observation(
            pair_u, release, bars, ppp, calendar_age_hours,
        )
        _emit_row(row)
        _state.emitted.add(key)
        return row
    except Exception:
        logger.debug("[NEWS-MOM] observe_release swallowed", exc_info=True)
        return None


def sweep(now: Optional[datetime] = None,
          throttle_override: bool = False) -> int:
    """Scan today's + yesterday's qualifying releases and, for each that
    has fully elapsed its outcome window and hasn't been recorded yet,
    emit one observation row per affected traded pair. Returns the count
    of rows emitted this call. Never raises.

    Throttled to _SWEEP_MIN_INTERVAL_S (default 900 s = 15 min) between
    calls per process; tests may override."""
    try:
        if _mode() == "off":
            return 0
        now_ts = time.time()
        if not throttle_override and (
            now_ts - _state.last_sweep_ts < _SWEEP_MIN_INTERVAL_S
        ):
            return 0
        _state.last_sweep_ts = now_ts

        now = now or datetime.now(timezone.utc)
        emitted = 0
        for release in _load_qualifying_releases(now):
            ccy = (release.get("currency") or "").upper()
            for pair, ccys in _PAIR_CCYS.items():
                if ccy not in ccys:
                    continue
                row = observe_release(release, pair, now=now)
                if row is not None:
                    emitted += 1
        return emitted
    except Exception:
        logger.debug("[NEWS-MOM] sweep swallowed", exc_info=True)
        return 0
