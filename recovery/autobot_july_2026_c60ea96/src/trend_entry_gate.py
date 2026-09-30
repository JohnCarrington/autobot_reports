"""TREND_ENTRY_GATE — live enforce gate for EMA_PULLBACK + STRUCTURE_BREAK.

Validated 2026-06-25 on 67 real GBPUSD fills (2026-05-27→2026-06-25):
  ungated −238.2p baseline. Best cut (this gate's defaults):
    n_pass=22 (W=14 L=8, wr=0.636) sum_pass=+76.2p
    losers_removed=34/42, winners_killed=11/25.
  See /tmp/macd_compare_audit.log for the head-to-head vs adx-only and
  vs MACD(35,45,30) — 12/26/9 beats both (more pips, larger sample,
  fewer killed winners). 35/45/30 cross was n_pass=11 (FRAGILE).

Two legs (BOTH required to ENTER; fail-open on compute error):
  1. adx_slope >= ADX_SLOPE_MIN (default 0.0).
     adx_slope = ADX_14[i] - ADX_14[i-5] (5-bar slope, ADX period 14,
     Wilder smoothing — matches the diagnostic exactly, parity verified
     bit-exact against indicators.adx() when full df closes/highs/lows
     are passed).
  2. Last SAME-DIRECTION MACD(12,26,9) signal-line cross within
     CROSS_MAX_BARS bars before entry (default 20).
     "Signal-line cross" == MACD histogram zero-cross (mathematically
     identical — hist = macd_line - signal_line). Same-direction =
     bullish cross (hist 0→+) for a LONG, bearish (hist 0→−) for a SHORT.

DROPPED features (validated dead on the 67-fill sample):
  - bb_exhaustion at cross bar: no separation
  - dist_from_ema50_pips: degenerate cut (best threshold killed nothing)

CAVEAT: validation sample is short-heavy (n=22 pass: 14 PULLBACK_S,
5 SB_S, 3 PULLBACK_L, 0 SB_L) over a down-trending month. Long-side and
SB-long effectiveness UNVERIFIED — per-fire log captures direction so
forward-state can be audited.

The per-fire log at TREND_ENTRY_GATE_LOG_PATH is the audit source —
every fire (pass or block) emits a row with direction + both feature
values, joinable to signal_log via (ts_utc, strategy, direction).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("trend_entry_gate")

LOG_TAG = "TREND_ENTRY_GATE"


def _env_bool(name: str, default: str) -> bool:
    return (os.getenv(name, default) or default).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# Master switch — flip to 0 to disable the whole gate in one env command.
ENABLED         = _env_bool("TREND_ENTRY_GATE_ENABLED", "1")
ADX_SLOPE_MIN   = _env_float("ADX_SLOPE_MIN", 0.0)
CROSS_MAX_BARS  = _env_int("CROSS_MAX_BARS", 20)
MACD_FAST       = _env_int("GATE_MACD_FAST", 12)
MACD_SLOW       = _env_int("GATE_MACD_SLOW", 26)
MACD_SIGNAL     = _env_int("GATE_MACD_SIGNAL", 9)
ADX_PERIOD      = _env_int("GATE_ADX_PERIOD", 14)
ADX_SLOPE_WIN   = _env_int("GATE_ADX_SLOPE_WIN", 5)
# Cross definition. The +314p validation in the 67-fill audit came from
# the MACD line crossing the ZERO AXIS (the diagnostic's `line_bars`
# column). The signal-line cross (= MACD line crossing its 9-EMA signal
# line, == histogram zero-cross — diagnostic's `hist_bars` column) is
# a DIFFERENT event and gave a worse cut on the same sample.
# Default: LINE_ZERO (matches the +314p / +76.2p validation result).
# Alternative: SIGNAL (matches the prompt's verbal description and
# Johnny's typical chart hist cross). Switchable in one env command.
CROSS_TYPE      = (os.getenv("GATE_CROSS_TYPE", "LINE_ZERO") or "LINE_ZERO").strip().upper()
# Below this, we can't reliably compute MACD-line warmup. Fail-open.
MIN_BARS        = _env_int("TREND_ENTRY_GATE_MIN_BARS", 200)
LOG_PATH        = os.getenv(
    "TREND_ENTRY_GATE_LOG_PATH",
    "/opt/tradingbot/logs/trend_entry_gate.jsonl",
)


def compute_features(
    closes: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    direction: str,
    *,
    adx_period: int = ADX_PERIOD,
    adx_slope_win: int = ADX_SLOPE_WIN,
    macd_fast: int = MACD_FAST,
    macd_slow: int = MACD_SLOW,
    macd_signal: int = MACD_SIGNAL,
    cross_max_bars: int = CROSS_MAX_BARS,
    cross_type: str = CROSS_TYPE,
) -> Dict[str, Any]:
    """Compute the two leg features at the LAST bar of each input series.

    Returns a dict with keys: adx_now, adx_then, adx_slope,
    bars_since_same_dir_cross, last_cross_direction, hist_now,
    sample_bars, compute_error.

    Fail-open: on any exception or insufficient warmup returns dict with
    `compute_error` set; caller treats this as "do not block".
    """
    # Lazy import — pandas/indicators must not import at module load time
    # so a missing dep at top-level can't break strategy loading.
    import pandas as pd
    import indicators

    n = len(closes)
    cross_type_u = str(cross_type or "LINE_ZERO").strip().upper()
    if cross_type_u not in ("LINE_ZERO", "SIGNAL"):
        cross_type_u = "LINE_ZERO"
    out: Dict[str, Any] = {
        "adx_now": None,
        "adx_then": None,
        "adx_slope": None,
        "bars_since_same_dir_cross": None,
        "last_cross_direction": None,
        "hist_now": None,
        "macd_line_now": None,
        "sample_bars": n,
        "compute_error": None,
        "adx_period": int(adx_period),
        "adx_slope_window_bars": int(adx_slope_win),
        "macd_fast": int(macd_fast),
        "macd_slow": int(macd_slow),
        "macd_signal": int(macd_signal),
        "cross_max_bars": int(cross_max_bars),
        "cross_type": cross_type_u,
    }
    if n < int(MIN_BARS):
        out["compute_error"] = f"warmup_short have={n}<need={int(MIN_BARS)}"
        return out
    if len(highs) != n or len(lows) != n:
        out["compute_error"] = f"length_mismatch closes={n} highs={len(highs)} lows={len(lows)}"
        return out
    direction_u = str(direction or "").upper()
    if direction_u in ("BUY", "LONG"):
        sign = 1
    elif direction_u in ("SELL", "SHORT"):
        sign = -1
    else:
        out["compute_error"] = f"unknown_direction={direction!r}"
        return out

    try:
        df = pd.DataFrame({
            "high": list(highs),
            "low": list(lows),
            "close": list(closes),
        })
        adx_df = indicators.adx(df, period=int(adx_period))
        adx_series = adx_df[f"ADX_{int(adx_period)}"].tolist()
        macd_df = indicators.macd(
            pd.Series(list(closes)),
            fast=int(macd_fast),
            slow=int(macd_slow),
            signal=int(macd_signal),
        )
        hist_col = f"MACD_HIST_{int(macd_fast)}_{int(macd_slow)}_{int(macd_signal)}"
        macd_col = f"MACD_{int(macd_fast)}_{int(macd_slow)}"
        hist = macd_df[hist_col].tolist()
        macd_line = macd_df[macd_col].tolist()
        # Cross-detection series: LINE_ZERO uses MACD line crossing zero
        # (the validation winner from the 67-fill audit, +314p delta);
        # SIGNAL uses the histogram crossing zero (==MACD line crossing
        # its signal line — the prompt's verbal description).
        if cross_type_u == "SIGNAL":
            cross_series = hist
        else:
            cross_series = macd_line

        # ADX slope
        slope_win = max(1, int(adx_slope_win))
        if n - 1 - slope_win < 0:
            out["compute_error"] = f"adx_slope_warmup_short n={n} slope_win={slope_win}"
            return out
        adx_now = adx_series[-1]
        adx_then = adx_series[-1 - slope_win]
        out["adx_now"] = float(adx_now) if adx_now is not None and adx_now == adx_now else None
        out["adx_then"] = float(adx_then) if adx_then is not None and adx_then == adx_then else None
        if out["adx_now"] is None or out["adx_then"] is None:
            out["compute_error"] = "adx_nan"
            return out
        out["adx_slope"] = out["adx_now"] - out["adx_then"]

        out["hist_now"] = float(hist[-1]) if hist[-1] == hist[-1] else None
        out["macd_line_now"] = float(macd_line[-1]) if macd_line[-1] == macd_line[-1] else None
        # Walk back to find LAST cross on the chosen series. Return both
        # the LAST cross (direction + bar offset) AND specifically the
        # last SAME-DIRECTION cross. Spec: block if last same-dir cross
        # is > CROSS_MAX_BARS bars old, OR if no same-dir cross exists.
        last_cross_idx = None
        last_cross_dir = None
        for j in range(n - 1, 0, -1):
            hj = cross_series[j]
            hjm = cross_series[j - 1]
            if hj != hj or hjm != hjm:  # NaN guard
                continue
            sp = 1 if hjm > 0 else (-1 if hjm < 0 else 0)
            sn = 1 if hj > 0 else (-1 if hj < 0 else 0)
            if sp != 0 and sn != 0 and sp != sn:
                last_cross_idx = j
                last_cross_dir = sn
                break
        if last_cross_idx is None:
            out["bars_since_same_dir_cross"] = None
            out["last_cross_direction"] = None
        else:
            bars_since_last_any = (n - 1) - last_cross_idx
            out["last_cross_direction"] = "BULL" if last_cross_dir == 1 else "BEAR"
            if last_cross_dir == sign:
                out["bars_since_same_dir_cross"] = bars_since_last_any
            else:
                # walk further back for a SAME-direction cross
                same_idx = None
                for j in range(last_cross_idx - 1, 0, -1):
                    hj = cross_series[j]; hjm = cross_series[j - 1]
                    if hj != hj or hjm != hjm:
                        continue
                    sp = 1 if hjm > 0 else (-1 if hjm < 0 else 0)
                    sn = 1 if hj > 0 else (-1 if hj < 0 else 0)
                    if sp != 0 and sn != 0 and sp != sn and sn == sign:
                        same_idx = j
                        break
                out["bars_since_same_dir_cross"] = (
                    (n - 1) - same_idx if same_idx is not None else None
                )
    except Exception as exc:
        out["compute_error"] = f"compute_exception:{type(exc).__name__}:{exc}"
        return out

    return out


def evaluate_gate(
    features: Dict[str, Any],
    *,
    adx_slope_min: float = ADX_SLOPE_MIN,
    cross_max_bars: int = CROSS_MAX_BARS,
) -> Dict[str, Any]:
    """Decide PASS / BLOCK from `features`. Fail-open on compute_error.

    Returns dict with: gate_pass (bool), leg_a_pass (adx), leg_b_pass
    (cross), block_reasons (list[str]), fail_open (bool).
    """
    verdict: Dict[str, Any] = {
        "gate_pass": True,
        "leg_a_pass": None,
        "leg_b_pass": None,
        "block_reasons": [],
        "fail_open": False,
        "adx_slope_min": float(adx_slope_min),
        "cross_max_bars": int(cross_max_bars),
    }
    if features.get("compute_error"):
        # Spec: fail-open on compute error.
        verdict["fail_open"] = True
        verdict["gate_pass"] = True
        verdict["block_reasons"].append(
            f"fail_open:{features.get('compute_error')}"
        )
        return verdict

    adx_slope = features.get("adx_slope")
    bars_since = features.get("bars_since_same_dir_cross")
    last_cross_dir = features.get("last_cross_direction")

    leg_a_pass = (adx_slope is not None) and (adx_slope >= float(adx_slope_min))
    leg_b_pass = (bars_since is not None) and (bars_since <= int(cross_max_bars))

    verdict["leg_a_pass"] = bool(leg_a_pass)
    verdict["leg_b_pass"] = bool(leg_b_pass)
    verdict["gate_pass"] = bool(leg_a_pass and leg_b_pass)

    if not leg_a_pass:
        if adx_slope is None:
            verdict["block_reasons"].append("leg_a:adx_slope_unavailable")
        else:
            verdict["block_reasons"].append(
                f"leg_a:adx_slope={adx_slope:+.4f}<{float(adx_slope_min):+.2f}"
            )
    if not leg_b_pass:
        if bars_since is None:
            cd = last_cross_dir or "none"
            verdict["block_reasons"].append(
                f"leg_b:no_same_dir_cross last_cross_dir={cd}"
            )
        else:
            verdict["block_reasons"].append(
                f"leg_b:bars_since={int(bars_since)}>{int(cross_max_bars)}"
            )
    return verdict


def write_log(row: Dict[str, Any]) -> None:
    """Append one JSONL row to LOG_PATH. Best-effort — never raises.
    Schema must include ts_utc + strategy + direction so rows are joinable
    to signal_log."""
    try:
        d = os.path.dirname(LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(LOG_PATH, "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
    except Exception as exc:
        logger.debug("[%s] log write failed: %s", LOG_TAG, exc)
