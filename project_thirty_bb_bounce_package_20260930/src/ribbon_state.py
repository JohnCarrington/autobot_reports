"""ribbon_state.py — EMA-ribbon regime-state classifier (2026-08-05).

Calibrated against 934 certified regime bars (report 2026-08-05):
STRONG_TREND spread_norm IQR 1.51-2.74 vs RANGE 0.29-1.10; cross_count
median 0 (STRONG) vs 3 (RANGE). Thresholds env-tunable so the operator
can retune without a code push.

Public surface:
  classify(closes, highs, lows) -> RibbonState
      Returns a RibbonState enum (UNKNOWN / FANNED_UP / FANNED_DOWN /
      BRAIDED / TRANSITIONAL) plus the three metric values used for the
      decision (spread_norm, cross_count_12, pitch50_norm) via the
      RibbonReading namedtuple.

  ENABLED (bool): master switch. Reads RIBBON_GATE_ENABLED (default OFF).

Deliberately dumb: no state, no lookback beyond what the caller supplies.
Fail-safe: returns UNKNOWN when there are fewer than 60 bars or when any
arithmetic step raises. Callers treat UNKNOWN as "no opinion" — never
gate on it.

Precedence (must not be reordered without recalibration):
  1. FANNED_UP / FANNED_DOWN  — tested first so a clearly-fanned bar
     is never swept into TRANSITIONAL by a stale-cross artefact.
  2. BRAIDED                  — only if FANNED does not hold.
  3. TRANSITIONAL             — everything else (e.g. fanned-spread
     with flat pitch, or half-braided half-fanned).
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger("AutoBot")


def _env_bool(name: str, default: str) -> bool:
    return (os.getenv(name) or default).strip() == "1"


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or "").strip() or default)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except Exception:
        return int(default)


ENABLED = _env_bool("RIBBON_GATE_ENABLED", "0")

# Thresholds — defaults per operator spec (2026-08-05 calibration).
FANNED_SPREAD_MIN = _env_float("RIBBON_FANNED_SPREAD_MIN", 1.2)
FANNED_CROSS_MAX  = _env_int("RIBBON_FANNED_CROSS_MAX", 1)
PITCH_MIN         = _env_float("RIBBON_PITCH_MIN", 0.3)
BRAIDED_SPREAD_MAX = _env_float("RIBBON_BRAIDED_SPREAD_MAX", 0.8)
BRAIDED_CROSS_MIN  = _env_int("RIBBON_BRAIDED_CROSS_MIN", 3)

MIN_BARS_REQUIRED = 60  # ATR14 warm-up + trailing 12-bar cross window.


class RibbonState(str, Enum):
    UNKNOWN = "UNKNOWN"
    FANNED_UP = "FANNED_UP"
    FANNED_DOWN = "FANNED_DOWN"
    BRAIDED = "BRAIDED"
    TRANSITIONAL = "TRANSITIONAL"


@dataclass(frozen=True)
class RibbonReading:
    state: RibbonState
    spread_norm: Optional[float]
    cross_count_12: Optional[int]
    pitch50_norm: Optional[float]


# ── Velocity/exhaustion (2026-08-08) ────────────────────────────────────────
# Fourth entry-gate term. Same input surface as classify() (closes/highs/lows
# in pips) — the consumer already has these to hand at the ribbon-gate seam.

class VelocityState(str, Enum):
    OK = "OK"                # metrics computed; caller applies the gate
    DEAD_TAPE = "DEAD_TAPE"  # vel_12 below floor — no move to join or fade
    UNKNOWN = "UNKNOWN"      # <20-bar seed or arithmetic failure — caller abstains


@dataclass(frozen=True)
class VelocityReading:
    state: VelocityState
    vel_3: Optional[float]        # pips/bar over the last 3 completed bars
    vel_12: Optional[float]       # pips/bar over the last 12 completed bars
    accel: Optional[float]        # vel_3 / vel_12 — >1 accelerating, <1 decelerating
    atr_mult: Optional[float]     # vel_3 / (ATR14 / 5). See VELOCITY_ATR_DIV comment.
    dir_of_move: int              # sign(close[-1] − close[-13]) — +1 up, -1 down, 0 flat


def _ewm(values: Sequence[float], span: int) -> List[float]:
    """pandas.Series.ewm(span=span, adjust=False).mean() equivalent."""
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    out: List[float] = [float(values[0])]
    for x in values[1:]:
        out.append(alpha * float(x) + (1.0 - alpha) * out[-1])
    return out


def band_width(
    closes: Sequence[float],
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
    pip_size: float = 1.0,
) -> Optional[Tuple[float, Optional[float]]]:
    """Bollinger-band width (BB(20,2)) and its ATR14 normalization.

    Added 2026-08-06 for the condition-aware BB_BOUNCE exit profile
    (calibration report of same date). Raw pip width is the decision
    ruler; width_norm is logging-only per operator direction.

    Args:
        closes: trailing 5m close series (>=40 bars required — 20-bar BB
            plus a comfortable ATR14 seed).
        highs, lows: optional trailing high/low series aligned with
            closes. When either is None, ATR normalization is skipped
            and width_norm returns None (width_pips still computed).
        pip_size: divisor to convert raw price differences to pips
            (1.0 for series already stored in ×10000 raw units;
            0.0001 for decimal-scaled series).

    Returns:
        (width_pips, width_norm) tuple, or None if fewer than 40 closes
        are supplied (insufficient seed).
    """
    n = len(closes)
    if n < 40:
        return None
    try:
        window = [float(c) for c in closes[-20:]]
        sma = sum(window) / 20.0
        var = sum((c - sma) ** 2 for c in window) / 20.0  # population variance
        sd = math.sqrt(var)
        raw_width = 4.0 * sd  # (SMA + 2*sd) - (SMA - 2*sd)
        ps = float(pip_size) if pip_size and float(pip_size) > 0 else 1.0
        width_pips = raw_width / ps

        width_norm: Optional[float] = None
        if highs is not None and lows is not None and len(highs) == n and len(lows) == n:
            atr_raw = _atr14_wilder(highs, lows, closes)
            if atr_raw is not None and atr_raw > 0:
                width_norm = width_pips / (atr_raw / ps)
        return width_pips, width_norm
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("[BAND-WIDTH] band_width raised (fail-safe None): %s", exc)
        return None


def _atr14_wilder(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> Optional[float]:
    """Wilder ATR14 on the trailing sequence — matches pandas .ewm(alpha=1/14,
    adjust=False).mean() applied to the True Range series."""
    n = len(closes)
    if n < 15 or len(highs) != n or len(lows) != n:
        return None
    trs: List[float] = []
    for i in range(1, n):
        h = float(highs[i]); l = float(lows[i]); pc = float(closes[i - 1])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    alpha = 1.0 / 14.0
    atr = trs[0]
    for tr in trs[1:]:
        atr = alpha * tr + (1.0 - alpha) * atr
    return atr


def _cross_count_12(
    ema8: Sequence[float],
    ema13: Sequence[float],
    ema21: Sequence[float],
) -> Optional[int]:
    """Pairwise order-changes among EMA8/13/21 over the trailing 12 bars.

    Braided ribbons flip pair-order constantly; fanned ribbons keep the
    same sign of (a-b) bar after bar. We count changes over the last 12
    bar-to-bar transitions (i.e. bars t-11..t vs t-12..t-1).
    """
    n = len(ema8)
    if n < 13 or len(ema13) != n or len(ema21) != n:
        return None
    start = n - 12
    count = 0
    for i in range(start, n):
        prev_ab = ema8[i - 1] - ema13[i - 1]
        prev_ac = ema8[i - 1] - ema21[i - 1]
        prev_bc = ema13[i - 1] - ema21[i - 1]
        cur_ab = ema8[i] - ema13[i]
        cur_ac = ema8[i] - ema21[i]
        cur_bc = ema13[i] - ema21[i]
        for a, b in ((prev_ab, cur_ab), (prev_ac, cur_ac), (prev_bc, cur_bc)):
            if (a > 0) != (b > 0):
                count += 1
    return count


def classify(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
) -> RibbonReading:
    """Classify the current ribbon state on the trailing 5m series.

    Requires >= 60 bars; returns UNKNOWN otherwise. All arithmetic errors
    also short-circuit to UNKNOWN — callers must never gate on UNKNOWN.
    """
    try:
        n = len(closes)
        if n < MIN_BARS_REQUIRED or len(highs) != n or len(lows) != n:
            return RibbonReading(RibbonState.UNKNOWN, None, None, None)

        ema8 = _ewm(closes, 8)
        ema13 = _ewm(closes, 13)
        ema21 = _ewm(closes, 21)
        ema50 = _ewm(closes, 50)

        atr14 = _atr14_wilder(highs, lows, closes)
        if atr14 is None or atr14 <= 0.0:
            return RibbonReading(RibbonState.UNKNOWN, None, None, None)

        # spread_norm = (max - min) of EMA8/13/21/50 at t / ATR14
        emas_t = (ema8[-1], ema13[-1], ema21[-1], ema50[-1])
        spread = max(emas_t) - min(emas_t)
        spread_norm = spread / atr14

        cross_count = _cross_count_12(ema8, ema13, ema21)
        if cross_count is None:
            return RibbonReading(RibbonState.UNKNOWN, None, None, None)

        # pitch50_norm = (EMA50[t] - EMA50[t-7]) / ATR14
        if len(ema50) < 8:
            return RibbonReading(RibbonState.UNKNOWN, spread_norm, cross_count, None)
        pitch50 = ema50[-1] - ema50[-8]
        pitch50_norm = pitch50 / atr14

        if any(math.isnan(v) or math.isinf(v)
               for v in (spread_norm, pitch50_norm)):
            return RibbonReading(RibbonState.UNKNOWN, None, None, None)

        # Precedence: FANNED first, then BRAIDED, else TRANSITIONAL.
        # FANNED_UP: spread >= min AND cross_count <= max AND pitch >= min.
        # FANNED_DOWN: same, pitch <= -min. BRAIDED: spread <= max OR
        # cross_count >= min (either signal is enough — braided is a
        # weak-alignment claim, so a low-spread flat-cross bar counts).
        if (spread_norm >= FANNED_SPREAD_MIN
                and cross_count <= FANNED_CROSS_MAX
                and pitch50_norm >= PITCH_MIN):
            state = RibbonState.FANNED_UP
        elif (spread_norm >= FANNED_SPREAD_MIN
                and cross_count <= FANNED_CROSS_MAX
                and pitch50_norm <= -PITCH_MIN):
            state = RibbonState.FANNED_DOWN
        elif (spread_norm <= BRAIDED_SPREAD_MAX
                or cross_count >= BRAIDED_CROSS_MIN):
            state = RibbonState.BRAIDED
        else:
            state = RibbonState.TRANSITIONAL

        return RibbonReading(state, spread_norm, cross_count, pitch50_norm)
    except Exception as exc:  # noqa: BLE001 — fail-safe by contract
        logger.warning("[RIBBON-GATE] classify raised (fail-safe UNKNOWN): %s", exc)
        return RibbonReading(RibbonState.UNKNOWN, None, None, None)


# Velocity-gate env — defaults keep the gate DORMANT in code; enabling
# in .env is what activates it. VELOCITY_MIN_VEL12 in pips/bar; anything
# below is DEAD_TAPE regardless of accel.
VELOCITY_MIN_VEL12 = _env_float("VELOCITY_MIN_VEL12", 0.15)


def velocity_state(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
) -> VelocityReading:
    """Fourth-gate velocity/exhaustion reading. Read-only on completed bars.

    Formulas (from bars STRICTLY BEFORE the event bar — caller is expected
    to pass its own completed-bar series; this fn does NOT drop the last
    bar itself):
        vel_3   = |close[-1] − close[-4]|  / 3    (pips/bar)
        vel_12  = |close[-1] − close[-13]| / 12   (pips/bar)
        accel   = vel_3 / vel_12
        atr_mult= vel_3 / (ATR14 / 5)             (per-bar ATR-equivalent
                  normalisation. This matches the 2026-08-08 calibration
                  pass — see /tmp unit check exhibit_A/exhibit_B for the
                  reproduced arithmetic.)
        dir_of_move = sign(close[-1] − close[-13])

    Returns state=UNKNOWN on <20-bar seed or arithmetic error, DEAD_TAPE
    when vel_12 < VELOCITY_MIN_VEL12 (default 0.15 p/bar), else OK.
    Caller decides how to act on OK; DEAD_TAPE and UNKNOWN mean abstain.
    """
    try:
        n = len(closes)
        if n < 20 or len(highs) != n or len(lows) != n:
            return VelocityReading(VelocityState.UNKNOWN, None, None, None, None, 0)
        c_m1  = float(closes[-1])
        c_m4  = float(closes[-4])
        c_m13 = float(closes[-13])
        vel_3  = abs(c_m1 - c_m4)  / 3.0
        vel_12 = abs(c_m1 - c_m13) / 12.0
        dir_of_move = 1 if (c_m1 - c_m13) > 0 else (-1 if (c_m1 - c_m13) < 0 else 0)
        if vel_12 < VELOCITY_MIN_VEL12:
            return VelocityReading(VelocityState.DEAD_TAPE, vel_3, vel_12,
                                   None, None, dir_of_move)
        accel = vel_3 / vel_12
        atr14 = _atr14_wilder(highs, lows, closes)
        if atr14 is None or atr14 <= 0.0:
            return VelocityReading(VelocityState.UNKNOWN, vel_3, vel_12,
                                   accel, None, dir_of_move)
        atr_mult = vel_3 / (atr14 / 5.0)
        return VelocityReading(VelocityState.OK, vel_3, vel_12, accel,
                               atr_mult, dir_of_move)
    except Exception as exc:  # noqa: BLE001 — fail-safe by contract
        logger.warning("[VELOCITY-GATE] velocity_state raised (fail-safe UNKNOWN): %s", exc)
        return VelocityReading(VelocityState.UNKNOWN, None, None, None, None, 0)


# --------------------------------------------------------------------------
# Deferral store (in-memory, per-strategy). Consumers create their own
# instance so state is not shared across strategies. "Dumb" per spec:
# levels + direction + setup_ts + age only. No stored verdicts. The
# release check reads current-bar data only.
# --------------------------------------------------------------------------

RIBBON_CONFIRM_EXPIRY_BARS = _env_int("RIBBON_CONFIRM_EXPIRY_BARS", 4)


@dataclass
class RibbonDeferredSetup:
    direction: str          # "LONG" or "SHORT"
    setup_ts: object        # datetime of the setup bar (opaque; string-formatted for logs)
    setup_high: float       # setup bar high
    setup_low: float        # setup bar low
    stop_side_price: float  # SL price the fire would have used (LONG: setup_low; SHORT: setup_high)
    age_bars: int = 0       # incremented on each subsequent completed 5m close


class RibbonDeferralStore:
    """Per-strategy in-memory dict of pending TRANSITIONAL setups.

    Key: (epic, direction). One deferred setup per (epic, direction);
    a new deferral overwrites any prior. No persistence — restart clears.
    """

    def __init__(self, strategy_tag: str) -> None:
        self._tag = strategy_tag
        self._store: dict = {}

    def arm(self, epic: str, setup: RibbonDeferredSetup) -> None:
        self._store[(epic, setup.direction)] = setup

    def get(self, epic: str, direction: str) -> Optional[RibbonDeferredSetup]:
        return self._store.get((epic, direction))

    def get_all_for_epic(self, epic: str) -> List[RibbonDeferredSetup]:
        return [v for (e, _d), v in self._store.items() if e == epic]

    def drop(self, epic: str, direction: str) -> None:
        self._store.pop((epic, direction), None)

    def bump_ages(self, epic: str) -> None:
        for (e, _d), v in list(self._store.items()):
            if e == epic:
                v.age_bars += 1
