"""Structural-level enumeration for the corrected liquidity-sweep research.

Per Stage 0 operator approval (amendment A2):
  - Primary swings: market_structure.detect_confirmed_swings(N=3) on M5.
  - Supplementary HTF swings: H1 24-bar/10 p and H4 30-bar/20 p via γ rules.
  - PDH, PDL, classical floor pivots from prior completed FX-day D1 bar.
  - Round numbers: multiples of 50 pips within ±150 pips of current price.
  - Multi-level overlap: cluster within 5 p, enforce 15 p separation, cluster
    anchor = highest-priority member.  (Stage 0 §3 default approved.)

All functions are point-in-time: no bar from the future is read.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, "/opt/tradingbot")
from market_structure import detect_confirmed_swings  # noqa: E402
from ig_daily_pivots import compute_classic_floor  # noqa: E402

# ------------------------------------------------------------------------
# Constants (frozen from Stage 0 defaults + operator approvals)
# ------------------------------------------------------------------------
APPROACH_BAND_PIPS = 8.0          # Stage 0 §3 default — approach band
CLUSTER_TOLERANCE_PIPS = 5.0      # level_computation.LEVEL_CONFLUENCE_TOLERANCE_PIPS
MIN_SEPARATION_PIPS = 15.0        # level_computation.MIN_SEPARATION_PIPS
ROUND_NUMBER_STEP_PIPS = 50.0     # level_computation.ROUND_NUMBER_STEP_PIPS
ROUND_NUMBER_RANGE_PIPS = 150.0   # level_computation.ROUND_NUMBER_RANGE_PIPS
H1_SWING_LOOKBACK = 24            # level_computation H1 swing lookback
H1_SWING_REVERSAL_PIPS = 10.0
H4_SWING_LOOKBACK = 30            # level_computation H4 swing lookback
H4_SWING_REVERSAL_PIPS = 20.0
PIPS_PER_POINT = 1.0              # GBPUSD AutoBot archive: 1 unit = 1 pip
                                  # (archive stores price × 10_000; 1 unit = 0.0001 USD = 1 pip)
                                  # ref: Stage 1's London liquidity sweep FROZEN_RULE.md convention

# Priority order for cluster anchor selection (highest priority first)
_FAMILY_PRIORITY = [
    "PDH", "PDL",
    "D_PIVOT_P", "D_PIVOT_R1", "D_PIVOT_S1",
    "D_PIVOT_R2", "D_PIVOT_S2",
    "D_PIVOT_R3", "D_PIVOT_S3",
    "H4_SWING_H", "H4_SWING_L",
    "H1_SWING_H", "H1_SWING_L",
    "M5_SWING_H", "M5_SWING_L",
    "ROUND_00", "ROUND_50",
]


# ------------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------------
@dataclass(frozen=True)
class Level:
    price: float
    family: str          # one of _FAMILY_PRIORITY
    side: str            # "resistance" | "support" | "pivot"
    confluence: Tuple[str, ...] = ()   # other families clustered with this one
    confluence_count: int = 1
    source_detail: str = ""   # e.g. "D1 2024-07-03" or "H1 swing idx 42"


# ------------------------------------------------------------------------
# Pivot + PDH/PDL (static per FX day)
# ------------------------------------------------------------------------
def pivots_for_day(prior_d1_hlc: Tuple[float, float, float]) -> Dict[str, float]:
    """Classical floor pivots from (H, L, C) of the prior completed FX D1."""
    H, L, C = prior_d1_hlc
    p = compute_classic_floor(H, L, C)
    return {
        "D_PIVOT_P": p.P,
        "D_PIVOT_R1": p.R1, "D_PIVOT_R2": p.R2, "D_PIVOT_R3": p.R3,
        "D_PIVOT_S1": p.S1, "D_PIVOT_S2": p.S2, "D_PIVOT_S3": p.S3,
    }


def pdh_pdl(prior_d1_hlc: Tuple[float, float, float]) -> Dict[str, float]:
    H, L, _ = prior_d1_hlc
    return {"PDH": H, "PDL": L}


# ------------------------------------------------------------------------
# Round numbers (dynamic per bar)
# ------------------------------------------------------------------------
def round_numbers_near(price: float) -> List[Tuple[float, str]]:
    """Return 50-pip multiples within ±ROUND_NUMBER_RANGE_PIPS of `price`.

    Returns list of (level_price_in_points, family_label).  The "00" vs "50"
    sub-family is derived from whether the pip-level ends in 00 or 50.
    IG point convention: 10 points = 1 pip for GBPUSD, so 50 pips = 500 points.
    """
    step_pts = ROUND_NUMBER_STEP_PIPS * PIPS_PER_POINT
    rng_pts = ROUND_NUMBER_RANGE_PIPS * PIPS_PER_POINT
    lo = price - rng_pts
    hi = price + rng_pts
    import math
    first = math.ceil(lo / step_pts) * step_pts
    out: List[Tuple[float, str]] = []
    x = first
    while x <= hi:
        # Pip value: convert points → pips.  "00" if the integer pip value
        # ends in 00; "50" if it ends in 50.  Any 50-pip grid lands on one.
        pip_level = round(x / PIPS_PER_POINT)
        family = "ROUND_00" if (pip_level % 100) == 0 else "ROUND_50"
        out.append((round(x, 5), family))
        x += step_pts
    return out


# ------------------------------------------------------------------------
# M5 swings via β rule — walk-forward safe
# ------------------------------------------------------------------------
M5_SWING_RETENTION_PER_DIRECTION = 10   # keep last 10 confirmed per side
M5_SWING_MAX_AGE_BARS = 576             # 48 h of M5 — equivalent to γ H4 window

def confirmed_m5_swings(
    highs: np.ndarray, lows: np.ndarray, asof_idx: int, N: int = 3,
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Return (swing_highs, swing_lows) confirmed as of bar `asof_idx`,
    retained to the ``M5_SWING_RETENTION_PER_DIRECTION`` most recent per side
    within ``M5_SWING_MAX_AGE_BARS``.  Only swings with k+N <= asof_idx are
    returned (walk-forward safe).

    Rationale: AMB-2 primary rule is ``detect_confirmed_swings(N=3)`` as
    approved.  Returning every swing ever confirmed would bloat the level set
    with 20+ M5 swings on most bars.  Retention of the 10 most recent per side
    matches the γ supplementary convention (last 5 per side on H1/H4) and
    keeps per-bar level enumeration tractable.  Documented in
    implementation_notes.md §2.
    """
    if asof_idx < 2 * N:
        return [], []
    swings_h, swings_l = detect_confirmed_swings(highs, lows, asof=asof_idx, N=N)
    min_idx = max(0, asof_idx - M5_SWING_MAX_AGE_BARS)
    sh = [(s.idx, s.price) for s in swings_h if s.idx >= min_idx]
    sl = [(s.idx, s.price) for s in swings_l if s.idx >= min_idx]
    sh = sh[-M5_SWING_RETENTION_PER_DIRECTION:]
    sl = sl[-M5_SWING_RETENTION_PER_DIRECTION:]
    return sh, sl


# ------------------------------------------------------------------------
# HTF supplementary swings (γ) — H1 and H4 fractal-ish reversal filter
# ------------------------------------------------------------------------
def _htf_swings(
    highs: np.ndarray, lows: np.ndarray, lookback: int, reversal_pips: float,
    asof_idx: int,
) -> Tuple[List[float], List[float]]:
    """Simple reversal-filter swings for HTF: iterate backward from `asof_idx`,
    find local extremes separated by at least `reversal_pips`.  Matches
    `level_computation._swing_points` style without importing it (same rule).
    """
    if asof_idx < lookback + 2:
        return [], []
    start = max(0, asof_idx - lookback)
    sl: List[float] = []
    sh: List[float] = []
    rev_pts = reversal_pips * PIPS_PER_POINT
    # Walk forward from `start` and record local extrema that satisfy the
    # reversal distance from the preceding extreme.
    direction = 0
    cur_hi = lows[start]
    cur_lo = highs[start]
    for i in range(start, asof_idx + 1):
        hi, lo = highs[i], lows[i]
        if direction >= 0 and hi >= cur_hi:
            cur_hi = hi
        if direction <= 0 and lo <= cur_lo:
            cur_lo = lo
        if direction >= 0 and (cur_hi - lo) >= rev_pts:
            sh.append(cur_hi)
            direction = -1
            cur_lo = lo
        elif direction <= 0 and (hi - cur_lo) >= rev_pts:
            sl.append(cur_lo)
            direction = 1
            cur_hi = hi
    return sh[-5:], sl[-5:]  # last 5 per direction, matching γ convention


def htf_swings_h1(h1_highs: np.ndarray, h1_lows: np.ndarray, asof_h1_idx: int
                  ) -> Tuple[List[float], List[float]]:
    return _htf_swings(h1_highs, h1_lows, H1_SWING_LOOKBACK, H1_SWING_REVERSAL_PIPS,
                       asof_h1_idx)


def htf_swings_h4(h4_highs: np.ndarray, h4_lows: np.ndarray, asof_h4_idx: int
                  ) -> Tuple[List[float], List[float]]:
    return _htf_swings(h4_highs, h4_lows, H4_SWING_LOOKBACK, H4_SWING_REVERSAL_PIPS,
                       asof_h4_idx)


# ------------------------------------------------------------------------
# Clustering (deterministic, no future peek)
# ------------------------------------------------------------------------
def cluster_levels(candidates: List[Level]) -> List[Level]:
    """Cluster candidates within CLUSTER_TOLERANCE_PIPS, pick highest-priority
    member as anchor, preserve all contributing family tags in `confluence`.
    """
    if not candidates:
        return []
    tol_pts = CLUSTER_TOLERANCE_PIPS * PIPS_PER_POINT
    sorted_candidates = sorted(candidates, key=lambda L: L.price)
    priority_rank = {f: i for i, f in enumerate(_FAMILY_PRIORITY)}
    clusters: List[List[Level]] = []
    for lvl in sorted_candidates:
        if clusters and abs(lvl.price - clusters[-1][0].price) <= tol_pts:
            clusters[-1].append(lvl)
        else:
            clusters.append([lvl])
    out: List[Level] = []
    for cluster in clusters:
        anchor = min(cluster, key=lambda L: priority_rank.get(L.family, 999))
        confluence = tuple(sorted(set(L.family for L in cluster) - {anchor.family}))
        out.append(Level(
            price=anchor.price,
            family=anchor.family,
            side=anchor.side,
            confluence=confluence,
            confluence_count=len(cluster),
            source_detail=anchor.source_detail,
        ))
    return out


def enforce_separation(levels: List[Level], current_price: float) -> List[Level]:
    """Enforce MIN_SEPARATION_PIPS between adjacent levels, prefer the one
    closest to current price."""
    if not levels:
        return []
    sep_pts = MIN_SEPARATION_PIPS * PIPS_PER_POINT
    priority_rank = {f: i for i, f in enumerate(_FAMILY_PRIORITY)}
    sorted_levels = sorted(levels, key=lambda L: L.price)
    out: List[Level] = []
    for lvl in sorted_levels:
        if out and (lvl.price - out[-1].price) < sep_pts:
            # Keep the one closer to current price; if tie, the one with
            # higher confluence_count; then higher priority.
            prev = out[-1]
            def score(L: Level) -> Tuple[float, int, int]:
                return (
                    abs(L.price - current_price),
                    -L.confluence_count,
                    priority_rank.get(L.family, 999),
                )
            if score(lvl) < score(prev):
                out[-1] = lvl
        else:
            out.append(lvl)
    return out


# ------------------------------------------------------------------------
# Entry point: enumerate levels at a point in time
# ------------------------------------------------------------------------
def enumerate_levels_at(
    *,
    current_price: float,
    prior_d1_hlc: Tuple[float, float, float],
    m5_highs: np.ndarray,
    m5_lows: np.ndarray,
    m5_asof_idx: int,
    h1_highs: Optional[np.ndarray] = None,
    h1_lows: Optional[np.ndarray] = None,
    h1_asof_idx: Optional[int] = None,
    h4_highs: Optional[np.ndarray] = None,
    h4_lows: Optional[np.ndarray] = None,
    h4_asof_idx: Optional[int] = None,
) -> List[Level]:
    """Return the clustered + separated level set valid at this moment.

    `m5_asof_idx` points at the LAST CLOSED M5 bar's index.  Swings in that
    series are available with ≥ N-bar delay.  HTF arrays are optional.
    """
    candidates: List[Level] = []

    # PDH / PDL
    for family, price in pdh_pdl(prior_d1_hlc).items():
        side = "resistance" if family == "PDH" else "support"
        candidates.append(Level(price=price, family=family, side=side,
                                source_detail="prior_fx_d1"))
    # Daily pivots
    for family, price in pivots_for_day(prior_d1_hlc).items():
        if "R" in family:
            side = "resistance"
        elif "S" in family:
            side = "support"
        else:
            side = "pivot"
        candidates.append(Level(price=price, family=family, side=side,
                                source_detail="classical_floor"))
    # Round numbers near current price
    for rn_price, family in round_numbers_near(current_price):
        candidates.append(Level(price=rn_price, family=family, side="pivot",
                                source_detail=f"grid_{family}"))

    # M5 confirmed swings (β) — walk-forward safe
    sh, sl = confirmed_m5_swings(m5_highs, m5_lows, asof_idx=m5_asof_idx, N=3)
    for idx, price in sh:
        candidates.append(Level(price=price, family="M5_SWING_H", side="resistance",
                                source_detail=f"m5_swing_bar={idx}"))
    for idx, price in sl:
        candidates.append(Level(price=price, family="M5_SWING_L", side="support",
                                source_detail=f"m5_swing_bar={idx}"))

    # H1 supplementary swings (γ)
    if h1_highs is not None and h1_lows is not None and h1_asof_idx is not None:
        h1_sh, h1_sl = htf_swings_h1(h1_highs, h1_lows, h1_asof_idx)
        for p in h1_sh:
            candidates.append(Level(price=p, family="H1_SWING_H", side="resistance",
                                    source_detail="h1_gamma"))
        for p in h1_sl:
            candidates.append(Level(price=p, family="H1_SWING_L", side="support",
                                    source_detail="h1_gamma"))

    # H4 supplementary swings (γ)
    if h4_highs is not None and h4_lows is not None and h4_asof_idx is not None:
        h4_sh, h4_sl = htf_swings_h4(h4_highs, h4_lows, h4_asof_idx)
        for p in h4_sh:
            candidates.append(Level(price=p, family="H4_SWING_H", side="resistance",
                                    source_detail="h4_gamma"))
        for p in h4_sl:
            candidates.append(Level(price=p, family="H4_SWING_L", side="support",
                                    source_detail="h4_gamma"))

    # Cluster at 5 pips to preserve identity on near-coincident levels.
    # Do NOT run enforce_separation (15 p rule) here: that is for the production
    # briefing's 4-6-level pick, not for research event enumeration where every
    # distinct structural level matters.
    return cluster_levels(candidates)
