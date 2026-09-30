"""runner_momentum — pure helpers for the exhaustion-gated momentum check.

Extracted from gbpusd_trend_v3.py on 2026-07-27 (M1-alignment logic +
MACD_HIST reader). Same primitives now feed BOTH:
  - gbpusd_trend_v3.monitor_exits — byte-identical wrappers keep the
    proven per-strategy behaviour untouched.
  - trade_manager.check_universal_runner_momentum — new universal
    shadow/enforce path (RUNNER_MOMENTUM_CHECK_MODE) for scaled-out
    runners across ALL strategies.

Byte-identical contract vs the previous inline blocks in
gbpusd_trend_v3.py (_m1_aligned, _macd_hist_last_and_contracting).
See tests/unit/test_runner_momentum.py for the parity harness.

Observable-only helpers — no side effects, no logging, no env reads.
The caller decides shadow vs enforce and owns close_position().
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple


def m1_aligned(direction: str, macd_hist: Optional[float]) -> Optional[bool]:
    """M1 = sign(MACD-hist) aligned with trade direction.

    Returns True/False, or None if undecidable (macd_hist is None / NaN /
    non-numeric, or direction is not one of the recognised tokens).
    Zero counts as NOT aligned (no directional push) — matches TREND_V3.

    Accepted direction tokens (case-sensitive, mirroring TREND_V3's
    original _m1_aligned): "LONG", "SHORT". For universal callers that
    speak "BUY"/"SELL", also accepts those as synonyms.
    """
    if macd_hist is None:
        return None
    try:
        h = float(macd_hist)
    except (TypeError, ValueError):
        return None
    if direction in ("LONG", "BUY"):
        return h > 0.0
    if direction in ("SHORT", "SELL"):
        return h < 0.0
    return None


def macd_hist_last_and_contracting(
    df_5m: Any,
    col: str = "MACD_HIST_35_45_30",
) -> Tuple[Optional[float], Optional[bool]]:
    """Read MACD histogram from the enriched 5m frame.

    Returns (last, contracting_bool). contracting = |hist[-1]| < |hist[-2]|.
    Any missing/NaN/exception path returns (None, None) — matches TREND_V3.
    """
    try:
        if df_5m is None or col not in df_5m.columns or len(df_5m) < 2:
            return None, None
        last = float(df_5m[col].iloc[-1])
        prev = float(df_5m[col].iloc[-2])
        if math.isnan(last) or math.isnan(prev):
            return None, None
        return last, (abs(last) < abs(prev))
    except Exception:
        return None, None


def evaluate_runner_verdict(
    direction: str,
    macd_hist_last: Optional[float],
) -> Dict[str, Any]:
    """Universal shadow/enforce entry point. Returns a verdict dict.

    Semantics:
      aligned (LONG hist>0 / SHORT hist<0)  -> HOLD
      against (LONG hist<=0 / SHORT hist>=0) -> WOULD_EXIT
      undecidable (hist None/NaN, unknown dir) -> HOLD (fail-safe)

    Verdict dict keys:
      verdict:    "HOLD" | "WOULD_EXIT"
      aligned:    True | False | None
      macd_hist:  float | None
      direction:  the direction passed in (upper-cased for the log)
      reason:     short human-readable string for the log
    """
    aligned = m1_aligned(direction, macd_hist_last)
    dir_up = str(direction).upper() if direction is not None else ""
    if aligned is True:
        verdict = "HOLD"
        reason = f"m1_aligned dir={dir_up} hist={macd_hist_last}"
    elif aligned is False:
        verdict = "WOULD_EXIT"
        reason = f"m1_flipped dir={dir_up} hist={macd_hist_last}"
    else:
        verdict = "HOLD"
        reason = f"m1_undecidable dir={dir_up} hist={macd_hist_last}"
    return {
        "verdict":   verdict,
        "aligned":   aligned,
        "macd_hist": macd_hist_last,
        "direction": dir_up,
        "reason":    reason,
    }
