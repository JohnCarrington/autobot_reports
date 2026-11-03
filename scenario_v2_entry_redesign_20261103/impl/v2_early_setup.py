"""Scenario V2 — mechanical early-setup derivation.

Takes a V2 scenario row + M5 candles + current clock and returns a
coherent (entry, stop, target, expiry) tuple derived mechanically
from the setup's own invalidation structure — NOT inherited from
V2's breakout stop.

Hard contracts:
  * Pure logic — no file I/O, no network, no broker import.
  * Lookahead-safe — uses only bars whose ts_close is strictly after
    scenario_gen (same guard as the deployed executor).
  * Preserves V2's direction and structural target. Stop is derived
    from the setup type.
  * Three setup types: MOMENTUM_IMPULSE / PULLBACK_REJECTION /
    EARLY_STRUCTURAL. V2's own BREAKOUT (setup_type=BREAKOUT) remains
    the fallback and is handled by the deployed executor unchanged.
  * If V2's structural stop is touched BEFORE the setup entry fires,
    the setup is abandoned (SETUP_INVALIDATED_PRE_ENTRY).

Public API:
    SetupOutcome = {"status": ..., "setup_type": ..., "entry_bar_ts": ...,
                     "sim_entry": ..., "stop": ..., "target": ...,
                     "expiry_bars": ..., "reason": ...}

    derive(scenario_row, candles, now_utc=None, mode="A", **kwargs)
        → SetupOutcome
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import statistics as st
from typing import Any

UTC = dt.timezone.utc


# ---------------------------------------------------------------------
# Defaults — overridable per-call
# ---------------------------------------------------------------------

MOMENTUM_MIN_RANGE_MULT = 1.5          # impulse range ≥ 1.5× 10-bar median
MOMENTUM_MIN_BODY_FRAC = 0.60          # close in top (BUY) / bottom (SELL) 40 % of range
MOMENTUM_STOP_BUFFER_PIPS = 1.0        # 1 p below impulse low (BUY) / above high (SELL)

PULLBACK_MAX_BARS = 6                  # abort if pullback persists > 6 bars
PULLBACK_STOP_BUFFER_PIPS = 2.0

STRUCTURAL_MIN_WINDOW_BARS = 4         # need ≥ 4 post-gen bars to look for 3-bar pivot
STRUCTURAL_STOP_BUFFER_PIPS = 2.0

DEFAULT_EXPIRY_BARS = 24               # 2 h in M5 bars
DEFAULT_LOOKBACK_SECONDS = 2 * 60 * 60 # 2 h — mirrors deployed executor

VALID_MODES = ("A", "B", "C")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _parse(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _primary_direction(row: dict) -> str:
    for o in (row.get("opportunities") or []):
        if isinstance(o, dict):
            d = (o.get("direction") or "").upper()
            if d in ("BUY", "SELL"):
                return d
    tp = (row.get("trade_proposal") or {})
    return (tp.get("direction") or "").upper()


def _tp(row: dict) -> dict:
    tp = row.get("trade_proposal") or {}
    if tp:
        return tp
    for o in (row.get("opportunities") or []):
        if isinstance(o, dict):
            inner = o.get("trade_proposal")
            if inner:
                return inner
    return {}


def _pre_bars(candles: list[dict], gen_dt: dt.datetime, n: int) -> list[dict]:
    """Last `n` completed bars whose ts_close ≤ gen_dt."""
    pre = [c for c in candles if c["ts_close"] <= gen_dt]
    return pre[-n:] if len(pre) >= n else pre


def _post_bars(candles: list[dict], gen_dt: dt.datetime, now: dt.datetime,
                 lookback_s: int) -> list[dict]:
    # Mirror shadow_execution.MAX_FILL_LOOKBACK_SECONDS semantics:
    # ``lookback_s == 0`` means "no cap", in which case the effective
    # not_before is just the scenario's gen_dt.
    if lookback_s <= 0:
        enb = gen_dt
    else:
        floor = now - dt.timedelta(seconds=lookback_s)
        enb = gen_dt if gen_dt > floor else floor
    return [c for c in candles if c["ts_close"] > enb and c["ts_close"] <= now]


def _stop_breach(bar: dict, direction: str, v2_stop: float) -> bool:
    """Did `bar` touch V2's structural stop before an entry fired?"""
    if direction == "BUY":
        return bar["l"] <= v2_stop
    return bar["h"] >= v2_stop


# ---------------------------------------------------------------------
# Public outcome shape
# ---------------------------------------------------------------------

@dataclasses.dataclass
class SetupOutcome:
    status: str                        # "fill" | "wait" | "reject" | "error"
    setup_type: str | None             # e.g. "MOMENTUM_IMPULSE"
    reason: str | None                 # if not fill, why
    entry_bar_ts: str | None           # UTC ISO of fill bar
    sim_entry: float | None            # bar close price (fill)
    stop: float | None                 # mechanical stop
    target: float | None               # V2's target (preserved)
    expiry_bars: int | None            # setup lifetime cap in M5 bars
    direction: str | None              # BUY/SELL
    extras: dict | None = None         # mechanism-specific audit data

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------
# Mechanism A — momentum impulse continuation
# ---------------------------------------------------------------------

def _derive_momentum(gen_dt: dt.datetime, now: dt.datetime,
                       direction: str, v2_stop: float, target: float,
                       candles: list[dict], lookback_s: int,
                       expiry_bars: int) -> SetupOutcome:
    pre = _pre_bars(candles, gen_dt, 10)
    if len(pre) < 10:
        return SetupOutcome("wait", "MOMENTUM_IMPULSE", "insufficient_pre_history",
                             None, None, None, target, expiry_bars, direction)
    med_range = st.median((c["h"] - c["l"]) for c in pre)
    if med_range <= 0:
        return SetupOutcome("wait", "MOMENTUM_IMPULSE", "zero_median_range",
                             None, None, None, target, expiry_bars, direction)
    for bar in _post_bars(candles, gen_dt, now, lookback_s):
        if _stop_breach(bar, direction, v2_stop):
            return SetupOutcome("reject", "MOMENTUM_IMPULSE",
                                 "SETUP_INVALIDATED_PRE_ENTRY",
                                 None, None, None, target, expiry_bars, direction,
                                 extras={"abort_bar_ts": bar["ts_open"].isoformat()})
        rng = bar["h"] - bar["l"]
        if rng <= 0:
            continue
        if direction == "BUY":
            bullish = bar["c"] > bar["o"]
            above_med = rng >= MOMENTUM_MIN_RANGE_MULT * med_range
            upper_body = (bar["c"] - bar["l"]) / rng >= MOMENTUM_MIN_BODY_FRAC
            if bullish and above_med and upper_body:
                stop = bar["l"] - MOMENTUM_STOP_BUFFER_PIPS
                return SetupOutcome("fill", "MOMENTUM_IMPULSE", None,
                                     bar["ts_open"].isoformat(), bar["c"],
                                     stop, target, expiry_bars, direction,
                                     extras={"impulse_range": round(rng, 2),
                                             "median_range_10": round(med_range, 2)})
        else:  # SELL
            bearish = bar["c"] < bar["o"]
            above_med = rng >= MOMENTUM_MIN_RANGE_MULT * med_range
            lower_body = (bar["h"] - bar["c"]) / rng >= MOMENTUM_MIN_BODY_FRAC
            if bearish and above_med and lower_body:
                stop = bar["h"] + MOMENTUM_STOP_BUFFER_PIPS
                return SetupOutcome("fill", "MOMENTUM_IMPULSE", None,
                                     bar["ts_open"].isoformat(), bar["c"],
                                     stop, target, expiry_bars, direction,
                                     extras={"impulse_range": round(rng, 2),
                                             "median_range_10": round(med_range, 2)})
    return SetupOutcome("wait", "MOMENTUM_IMPULSE",
                         "no_momentum_impulse_within_window",
                         None, None, None, target, expiry_bars, direction)


# ---------------------------------------------------------------------
# Mechanism B — pullback + rejection
# ---------------------------------------------------------------------

def _derive_pullback(gen_dt: dt.datetime, now: dt.datetime,
                       direction: str, v2_stop: float, target: float,
                       candles: list[dict], lookback_s: int,
                       expiry_bars: int) -> SetupOutcome:
    # Decision price = close of last pre-gen bar.
    pre = [c for c in candles if c["ts_close"] <= gen_dt]
    if not pre:
        return SetupOutcome("wait", "PULLBACK_REJECTION", "no_decision_bar",
                             None, None, None, target, expiry_bars, direction)
    decision_price = pre[-1]["c"]
    pullback: list[dict] = []
    for bar in _post_bars(candles, gen_dt, now, lookback_s):
        if _stop_breach(bar, direction, v2_stop):
            return SetupOutcome("reject", "PULLBACK_REJECTION",
                                 "SETUP_INVALIDATED_PRE_ENTRY",
                                 None, None, None, target, expiry_bars, direction,
                                 extras={"abort_bar_ts": bar["ts_open"].isoformat()})
        counter = (direction == "BUY" and bar["c"] < decision_price) \
               or (direction == "SELL" and bar["c"] > decision_price)
        indir = (direction == "BUY" and bar["c"] > decision_price) \
             or (direction == "SELL" and bar["c"] < decision_price)
        if counter:
            pullback.append(bar)
            if len(pullback) > PULLBACK_MAX_BARS:
                return SetupOutcome("reject", "PULLBACK_REJECTION",
                                     "pullback_too_long", None, None, None,
                                     target, expiry_bars, direction)
            continue
        if indir and pullback:
            higher_low = direction == "BUY" and bar["l"] > min(pb["l"] for pb in pullback)
            lower_high = direction == "SELL" and bar["h"] < max(pb["h"] for pb in pullback)
            if higher_low or lower_high:
                if direction == "BUY":
                    stop = min(pb["l"] for pb in pullback) - PULLBACK_STOP_BUFFER_PIPS
                else:
                    stop = max(pb["h"] for pb in pullback) + PULLBACK_STOP_BUFFER_PIPS
                return SetupOutcome("fill", "PULLBACK_REJECTION", None,
                                     bar["ts_open"].isoformat(), bar["c"],
                                     stop, target, expiry_bars, direction,
                                     extras={"pullback_bars": len(pullback)})
    return SetupOutcome("wait", "PULLBACK_REJECTION",
                         "no_pullback_rejection_sequence",
                         None, None, None, target, expiry_bars, direction)


# ---------------------------------------------------------------------
# Mechanism C — early structural continuation
# ---------------------------------------------------------------------

def _derive_structural(gen_dt: dt.datetime, now: dt.datetime,
                         direction: str, v2_stop: float, target: float,
                         candles: list[dict], lookback_s: int,
                         expiry_bars: int) -> SetupOutcome:
    post = _post_bars(candles, gen_dt, now, lookback_s)
    if len(post) < STRUCTURAL_MIN_WINDOW_BARS:
        return SetupOutcome("wait", "EARLY_STRUCTURAL", "insufficient_post_bars",
                             None, None, None, target, expiry_bars, direction)
    for i in range(len(post) - 2):
        a, b, c_ = post[i], post[i + 1], post[i + 2]
        if _stop_breach(a, direction, v2_stop):
            return SetupOutcome("reject", "EARLY_STRUCTURAL",
                                 "SETUP_INVALIDATED_PRE_ENTRY",
                                 None, None, None, target, expiry_bars, direction,
                                 extras={"abort_bar_ts": a["ts_open"].isoformat()})
        if direction == "BUY":
            local_peak = a["h"] >= b["h"]
            local_trough = b["l"] < a["l"] and b["l"] < c_["l"]
            cont_break = c_["c"] > a["h"]
            if local_peak and local_trough and cont_break:
                stop = b["l"] - STRUCTURAL_STOP_BUFFER_PIPS
                return SetupOutcome("fill", "EARLY_STRUCTURAL", None,
                                     c_["ts_open"].isoformat(), c_["c"],
                                     stop, target, expiry_bars, direction,
                                     extras={"trough_low": b["l"]})
        else:
            local_trough = a["l"] <= b["l"]
            local_peak = b["h"] > a["h"] and b["h"] > c_["h"]
            cont_break = c_["c"] < a["l"]
            if local_trough and local_peak and cont_break:
                stop = b["h"] + STRUCTURAL_STOP_BUFFER_PIPS
                return SetupOutcome("fill", "EARLY_STRUCTURAL", None,
                                     c_["ts_open"].isoformat(), c_["c"],
                                     stop, target, expiry_bars, direction,
                                     extras={"trough_high": b["h"]})
    return SetupOutcome("wait", "EARLY_STRUCTURAL",
                         "no_structural_pivot_pattern",
                         None, None, None, target, expiry_bars, direction)


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def derive(scenario_row: dict, candles: list[dict],
             mode: str = "A", now_utc: dt.datetime | None = None,
             lookback_seconds: int = DEFAULT_LOOKBACK_SECONDS,
             expiry_bars: int = DEFAULT_EXPIRY_BARS) -> SetupOutcome:
    """Derive a coherent (entry, stop, target, expiry) setup from the
    scenario row and the M5 bar stream.

    Preserves V2's direction + target. Derives the stop mechanically
    from the setup type.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}; got {mode!r}")
    now = now_utc or dt.datetime.now(UTC)
    direction = _primary_direction(scenario_row)
    tp = _tp(scenario_row)
    target = tp.get("target_price")
    v2_stop = tp.get("stop_price")
    scen_gen_at = scenario_row.get("generated_at_utc") \
                   or scenario_row.get("revised_at_utc") or ""
    gen_dt = _parse(scen_gen_at)
    if direction not in ("BUY", "SELL"):
        return SetupOutcome("error", None, "no_direction",
                             None, None, None, target, expiry_bars, direction)
    if target is None or v2_stop is None or gen_dt is None:
        return SetupOutcome("error", None, "missing_proposal_or_gen_ts",
                             None, None, None, target, expiry_bars, direction)
    if mode == "A":
        return _derive_momentum(gen_dt, now, direction, v2_stop, target,
                                   candles, lookback_seconds, expiry_bars)
    if mode == "B":
        return _derive_pullback(gen_dt, now, direction, v2_stop, target,
                                   candles, lookback_seconds, expiry_bars)
    if mode == "C":
        return _derive_structural(gen_dt, now, direction, v2_stop, target,
                                     candles, lookback_seconds, expiry_bars)
    # unreachable
    return SetupOutcome("error", None, f"unknown_mode:{mode}",
                         None, None, None, target, expiry_bars, direction)


__all__ = [
    "SetupOutcome",
    "derive",
    "VALID_MODES",
    "MOMENTUM_MIN_RANGE_MULT",
    "MOMENTUM_MIN_BODY_FRAC",
    "MOMENTUM_STOP_BUFFER_PIPS",
    "PULLBACK_MAX_BARS",
    "PULLBACK_STOP_BUFFER_PIPS",
    "STRUCTURAL_STOP_BUFFER_PIPS",
    "DEFAULT_EXPIRY_BARS",
    "DEFAULT_LOOKBACK_SECONDS",
]
