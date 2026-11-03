"""Scenario V2 — mechanical early-setup derivation.

Takes a V2 scenario row + M5 candles + current clock and returns a
coherent (entry, stop, target) tuple derived mechanically from the
setup's own invalidation structure — NOT inherited from V2's
breakout stop.

**NO POST-ENTRY TIME-BASED CLOSE.** This module does not and MUST
not emit any time-based expiry for an open position. Once an order
is placed, the broker's attached stop/limit distance governs the
exit entirely. Operator directive 2026-11-03: "a pre-entry setup
may expire or be invalidated before any order is placed, but this
must never close an already-open position". A pre-entry setup
timeout is implemented via the `lookback_seconds` cap on how far
back the derivation looks for a trigger bar — it never closes a
live position.

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
                     "reason": ...}

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

# PRE-ENTRY lookback cap. Bounds how far back the derivation looks for
# a trigger bar. This is a PRE-ENTRY setup timeout: before any order
# is placed. Mirrors the deployed shadow_execution.MAX_FILL_LOOKBACK_SECONDS
# default. NO POST-ENTRY equivalent exists — once a position opens,
# the broker's attached stop/limit distance owns the exit.
DEFAULT_LOOKBACK_SECONDS = 2 * 60 * 60

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
    direction: str | None              # BUY/SELL
    extras: dict | None = None         # mechanism-specific audit data

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------
# Mechanism A — momentum impulse continuation (LATEST-M5-ONLY)
# ---------------------------------------------------------------------
# 2026-11-03 freshness correction: the derivation only ever fires on
# the SINGLE just-closed M5 bar. Earlier bars contribute to context
# (median range, pre-entry stop-breach check) but can never themselves
# trigger an entry retrospectively.
#
# "The just-closed M5 bar" is defined as the bar whose `ts_close` equals
# `now` rounded down to the nearest 5-minute boundary. The sweeper runs
# with RandomizedDelaySec=20s so at wall-clock 10:05:17 the just-closed
# bar is the 10:00-10:05 bar (ts_close = 10:05:00).
#
# If the observer has not published that specific bar yet (common when
# the sweep narrowly beats the observer), the derivation returns WAIT
# with reason `latest_completed_m5_not_available`. It does NOT fall
# back to the previous bar — operator-mandated: "a previous M5 interval"
# is explicitly disallowed. Try again next sweep.


def _latest_m5_boundary(now: dt.datetime) -> dt.datetime:
    """Return ``now`` rounded DOWN to the nearest 5-minute boundary.

    Example: 10:07:30 -> 10:05:00; 10:10:17 -> 10:10:00; 10:10:00 -> 10:10:00.
    """
    anchor = now.replace(second=0, microsecond=0)
    return anchor - dt.timedelta(minutes=anchor.minute % 5)


def _find_just_closed_bar(candles: list[dict],
                            now: dt.datetime) -> dict | None:
    """Return the single bar whose ``ts_close`` equals the latest 5-min
    boundary at or before ``now``. Returns None if that bar is not in
    the candle stream (observer lag / data gap)."""
    boundary = _latest_m5_boundary(now)
    for c in reversed(candles):
        if c["ts_close"] == boundary:
            return c
        if c["ts_close"] < boundary:
            # Stream is behind the expected boundary. The bar we need
            # is not available.
            return None
    return None


def _derive_momentum(gen_dt: dt.datetime, now: dt.datetime,
                       direction: str, v2_stop: float, target: float,
                       candles: list[dict], lookback_s: int) -> SetupOutcome:
    pre = _pre_bars(candles, gen_dt, 10)
    if len(pre) < 10:
        return SetupOutcome("wait", "MOMENTUM_IMPULSE", "insufficient_pre_history",
                             None, None, None, target, direction)
    med_range = st.median((c["h"] - c["l"]) for c in pre)
    if med_range <= 0:
        return SetupOutcome("wait", "MOMENTUM_IMPULSE", "zero_median_range",
                             None, None, None, target, direction)

    # Identify the just-closed M5 bar. If missing, do NOT fire.
    boundary = _latest_m5_boundary(now)
    latest = _find_just_closed_bar(candles, now)
    if latest is None:
        return SetupOutcome("wait", "MOMENTUM_IMPULSE",
                             "latest_completed_m5_not_available",
                             None, None, None, target, direction,
                             extras={"expected_m5_close": boundary.isoformat()})

    # Scenario must have been actionable before this bar closed.
    if latest["ts_close"] <= gen_dt:
        return SetupOutcome("wait", "MOMENTUM_IMPULSE",
                             "latest_bar_closed_before_scenario_actionable",
                             None, None, None, target, direction,
                             extras={"latest_close": latest["ts_close"].isoformat(),
                                     "scen_gen": gen_dt.isoformat()})

    # Defensive: the just-closed bar must sit inside the lookback cap.
    # In normal operation the just-closed bar is seconds old, so this
    # is a no-op. The check protects against pathological time-travel
    # inputs in tests + any future refactor that passes a stale now.
    if lookback_s > 0:
        floor = now - dt.timedelta(seconds=lookback_s)
        if latest["ts_close"] <= floor:
            return SetupOutcome("wait", "MOMENTUM_IMPULSE",
                                 "latest_bar_outside_lookback_cap",
                                 None, None, None, target, direction)

    # Pre-entry V2-stop-breach check — walk EARLIER post-gen bars (not
    # the latest). If any earlier bar touched V2's structural stop before
    # the latest bar formed, the setup is dead on arrival.
    for bar in _post_bars(candles, gen_dt, now, lookback_s):
        if bar["ts_close"] >= latest["ts_close"]:
            break
        if _stop_breach(bar, direction, v2_stop):
            return SetupOutcome("reject", "MOMENTUM_IMPULSE",
                                 "SETUP_INVALIDATED_PRE_ENTRY",
                                 None, None, None, target, direction,
                                 extras={"abort_bar_ts": bar["ts_open"].isoformat()})

    # The latest bar itself must not have breached V2's structural stop.
    if _stop_breach(latest, direction, v2_stop):
        return SetupOutcome("reject", "MOMENTUM_IMPULSE",
                             "SETUP_INVALIDATED_PRE_ENTRY",
                             None, None, None, target, direction,
                             extras={"abort_bar_ts": latest["ts_open"].isoformat()})

    # Apply momentum criteria to the latest bar ONLY.
    rng = latest["h"] - latest["l"]
    if rng <= 0:
        return SetupOutcome("wait", "MOMENTUM_IMPULSE",
                             "latest_bar_zero_range",
                             None, None, None, target, direction)

    if direction == "BUY":
        bullish = latest["c"] > latest["o"]
        above_med = rng >= MOMENTUM_MIN_RANGE_MULT * med_range
        upper_body = (latest["c"] - latest["l"]) / rng >= MOMENTUM_MIN_BODY_FRAC
        if bullish and above_med and upper_body:
            stop = latest["l"] - MOMENTUM_STOP_BUFFER_PIPS
            return SetupOutcome("fill", "MOMENTUM_IMPULSE", None,
                                 latest["ts_open"].isoformat(), latest["c"],
                                 stop, target, direction,
                                 extras={"impulse_range": round(rng, 2),
                                         "median_range_10": round(med_range, 2),
                                         "latest_m5_close": latest["ts_close"].isoformat()})
    else:  # SELL
        bearish = latest["c"] < latest["o"]
        above_med = rng >= MOMENTUM_MIN_RANGE_MULT * med_range
        lower_body = (latest["h"] - latest["c"]) / rng >= MOMENTUM_MIN_BODY_FRAC
        if bearish and above_med and lower_body:
            stop = latest["h"] + MOMENTUM_STOP_BUFFER_PIPS
            return SetupOutcome("fill", "MOMENTUM_IMPULSE", None,
                                 latest["ts_open"].isoformat(), latest["c"],
                                 stop, target, direction,
                                 extras={"impulse_range": round(rng, 2),
                                         "median_range_10": round(med_range, 2),
                                         "latest_m5_close": latest["ts_close"].isoformat()})

    return SetupOutcome("wait", "MOMENTUM_IMPULSE",
                         "latest_bar_did_not_meet_momentum_criteria",
                         None, None, None, target, direction,
                         extras={"latest_m5_close": latest["ts_close"].isoformat(),
                                 "latest_range": round(rng, 2),
                                 "median_range_10": round(med_range, 2)})


# ---------------------------------------------------------------------
# Mechanism B — pullback + rejection
# ---------------------------------------------------------------------

def _derive_pullback(gen_dt: dt.datetime, now: dt.datetime,
                       direction: str, v2_stop: float, target: float,
                       candles: list[dict], lookback_s: int) -> SetupOutcome:
    # Decision price = close of last pre-gen bar.
    pre = [c for c in candles if c["ts_close"] <= gen_dt]
    if not pre:
        return SetupOutcome("wait", "PULLBACK_REJECTION", "no_decision_bar",
                             None, None, None, target, direction)
    decision_price = pre[-1]["c"]
    pullback: list[dict] = []
    for bar in _post_bars(candles, gen_dt, now, lookback_s):
        if _stop_breach(bar, direction, v2_stop):
            return SetupOutcome("reject", "PULLBACK_REJECTION",
                                 "SETUP_INVALIDATED_PRE_ENTRY",
                                 None, None, None, target, direction,
                                 extras={"abort_bar_ts": bar["ts_open"].isoformat()})
        counter = (direction == "BUY" and bar["c"] < decision_price) \
               or (direction == "SELL" and bar["c"] > decision_price)
        indir = (direction == "BUY" and bar["c"] > decision_price) \
             or (direction == "SELL" and bar["c"] < decision_price)
        if counter:
            pullback.append(bar)
            if len(pullback) > PULLBACK_MAX_BARS:
                return SetupOutcome("reject", "PULLBACK_REJECTION",
                                     "pullback_too_long",
                                     None, None, None, target, direction)
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
                                     stop, target, direction,
                                     extras={"pullback_bars": len(pullback)})
    return SetupOutcome("wait", "PULLBACK_REJECTION",
                         "no_pullback_rejection_sequence",
                         None, None, None, target, direction)


# ---------------------------------------------------------------------
# Mechanism C — early structural continuation
# ---------------------------------------------------------------------

def _derive_structural(gen_dt: dt.datetime, now: dt.datetime,
                         direction: str, v2_stop: float, target: float,
                         candles: list[dict], lookback_s: int) -> SetupOutcome:
    post = _post_bars(candles, gen_dt, now, lookback_s)
    if len(post) < STRUCTURAL_MIN_WINDOW_BARS:
        return SetupOutcome("wait", "EARLY_STRUCTURAL", "insufficient_post_bars",
                             None, None, None, target, direction)
    for i in range(len(post) - 2):
        a, b, c_ = post[i], post[i + 1], post[i + 2]
        if _stop_breach(a, direction, v2_stop):
            return SetupOutcome("reject", "EARLY_STRUCTURAL",
                                 "SETUP_INVALIDATED_PRE_ENTRY",
                                 None, None, None, target, direction,
                                 extras={"abort_bar_ts": a["ts_open"].isoformat()})
        if direction == "BUY":
            local_peak = a["h"] >= b["h"]
            local_trough = b["l"] < a["l"] and b["l"] < c_["l"]
            cont_break = c_["c"] > a["h"]
            if local_peak and local_trough and cont_break:
                stop = b["l"] - STRUCTURAL_STOP_BUFFER_PIPS
                return SetupOutcome("fill", "EARLY_STRUCTURAL", None,
                                     c_["ts_open"].isoformat(), c_["c"],
                                     stop, target, direction,
                                     extras={"trough_low": b["l"]})
        else:
            local_trough = a["l"] <= b["l"]
            local_peak = b["h"] > a["h"] and b["h"] > c_["h"]
            cont_break = c_["c"] < a["l"]
            if local_trough and local_peak and cont_break:
                stop = b["h"] + STRUCTURAL_STOP_BUFFER_PIPS
                return SetupOutcome("fill", "EARLY_STRUCTURAL", None,
                                     c_["ts_open"].isoformat(), c_["c"],
                                     stop, target, direction,
                                     extras={"trough_high": b["h"]})
    return SetupOutcome("wait", "EARLY_STRUCTURAL",
                         "no_structural_pivot_pattern",
                         None, None, None, target, direction)


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def derive(scenario_row: dict, candles: list[dict],
             mode: str = "A", now_utc: dt.datetime | None = None,
             lookback_seconds: int = DEFAULT_LOOKBACK_SECONDS) -> SetupOutcome:
    """Derive a coherent (entry, stop, target) setup from the scenario
    row and the M5 bar stream.

    Preserves V2's direction + target. Derives the stop mechanically
    from the setup type. Returns a SetupOutcome; emits no post-entry
    expiry — once an order is placed the broker's attached stop/limit
    distance governs the exit entirely.
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
                             None, None, None, target, direction)
    if target is None or v2_stop is None or gen_dt is None:
        return SetupOutcome("error", None, "missing_proposal_or_gen_ts",
                             None, None, None, target, direction)
    if mode == "A":
        return _derive_momentum(gen_dt, now, direction, v2_stop, target,
                                   candles, lookback_seconds)
    if mode == "B":
        return _derive_pullback(gen_dt, now, direction, v2_stop, target,
                                   candles, lookback_seconds)
    if mode == "C":
        return _derive_structural(gen_dt, now, direction, v2_stop, target,
                                     candles, lookback_seconds)
    # unreachable
    return SetupOutcome("error", None, f"unknown_mode:{mode}",
                         None, None, None, target, direction)


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
    "DEFAULT_LOOKBACK_SECONDS",
]
