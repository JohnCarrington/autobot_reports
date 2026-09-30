"""htf_authority.py — HTF authority gate (TREND/RANGE + direction).

Kill-switch: HTF_AUTHORITY_ENABLED (default OFF). When OFF, evaluate() returns
PASS for every call — pure no-op, no behaviour change.

When ON, classifies the market as TREND or RANGE using htf_regime's H1/D1/W1
read PLUS a net-progress check over the last HTF_AUTH_H1_WINDOW H1 bars
(efficiency ratio = |net| / Σ|Δclose|), then gates entries:

  RANGE  → mean-reversion only. Strategies in REVERSAL_MODES pass for both
           directions; everything else is blocked. HTF direction is IGNORED.

  TREND  → direction authority = sign of H1 EMA8 vs EMA21, CONFIRMED by D1
           ema_slope sign OR W1 closes-tail slope sign. Counter-trend entries
           are blocked regardless of strategy class. If H1 sign disagrees with
           both D1 and W1 slope, direction is NONE and the gate fails open
           (logs the indeterminate state for review).

A directional drift inside an "htf_regime says RANGE" day still counts as a
TREND if |net| over the H1 window clears HTF_AUTH_DRIFT_PIPS_MIN AND the
efficiency ratio clears HTF_AUTH_EFF_RATIO_MIN — this catches choppy-but-
directional sessions (e.g. 2026-06-03: htf_regime h1_state=RANGE 63% of the
day yet net −25.7p with W1=DOWN).

Telemetry: every call appends one row to logs/htf_authority.jsonl with the
TREND/RANGE call, HTF direction, allow/block decision, reason, and the 5m
label it overrode — so the call earns a scoreable record.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Env-tunable thresholds — read at call time so .env edits take immediate
# effect without a process restart.
# ─────────────────────────────────────────────────────────────────────────────
def _env_bool(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


TELEMETRY_PATH = os.getenv("HTF_AUTHORITY_LOG_PATH", "/opt/tradingbot/logs/htf_authority.jsonl")
BB_BLOCK_SHADOW_PATH = os.getenv(
    "BB_BLOCK_SHADOW_LOG_PATH", "/opt/tradingbot/logs/bb_block_shadow.jsonl"
)


# Mirrors conviction_gate.REVERSAL_MODES — mean-reversion strategies that are
# allowed under a RANGE call. Importing from conviction_gate would create a
# circular dependency at gate-evaluation time, so duplicated here intentionally.
REVERSAL_MODES = frozenset({
    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
    "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S",
    "GBPUSD_RAW_REVERSAL_L", "GBPUSD_RAW_REVERSAL_S",
    "BB_REVERSAL",
})


# structure_break is a continuation-breakout strategy. A decisive 5M break
# while HTF reads RANGE is the range→trend transition — its best setup —
# but it isn't a "reversal" so RANGE_no_continuation otherwise vetoes it.
# Membership here unlocks the scoped RANGE-branch exempt below; gated at
# evaluate() time by STRUCTURE_BREAK_HTF_RANGE_EXEMPT_ENABLED so reverting
# is one .env flip without a restart.
STRUCTURE_BREAK_MODES = frozenset({
    "GBPUSD_STRUCTURE_BREAK_L", "GBPUSD_STRUCTURE_BREAK_S",
})


# GBPUSD_EMA_PULLBACK trusts its own H1 EMA8/21 separation (>=2.0p, with the
# 0.5p h1_ema_direction floor in the strategy itself). Membership here makes
# the strategy authoritative on direction — HTF_AUTHORITY PASSes regardless
# of the call (RANGE *or* opposite-trend) when EMA_PULLBACK_HTF_EXEMPT_ENABLED=1.
# Default OFF preserves the current HTF_AUTHORITY gating; one .env flip
# reverts without a restart.
EMA_PULLBACK_MODES = frozenset({
    "GBPUSD_EMA_PULLBACK_L", "GBPUSD_EMA_PULLBACK_S",
})


# NEWS_STRATEGY arms on Finnhub HIGH-impact releases and trades the spike
# either as FADE (counter to the spike, after a consolidation break) or
# CONT (with the spike direction). The economic surprise itself is the
# catalyst — HTF momentum should not veto a news fire:
#   • FADE is counter-trend by design (it fades the spike), so an HTF
#     read aligned with the spike will always block it.
#   • CONT may also fire counter-HTF when the surprise breaks the prior
#     regime (e.g. a BEAT pushes EURUSD UP while H1 reads TREND_DOWN).
# 2026-06-14 → 2026-06-28 audit: 3 of 13 real news fires vanished at the
# HTF_AUTHORITY gate (EURUSD Core PCE FADE 2026-06-25 12:31:55 is the
# canonical case — observed.jsonl FIRE row present, no signal_log row,
# trade_executor.py:1083-1095 returned None on
# BLOCKED:SHORT_counter_TREND_UP). Membership here makes news the
# authority on direction. Default ON (this is the bug fix); flip
# HTF_AUTH_NEWS_EXEMPT_ENABLED=0 in .env to revert without a restart.
NEWS_STRATEGY_MODES = frozenset({
    "NEWS_STRATEGY", "NEWS_STRATEGY_FADE", "NEWS_STRATEGY_CONT",
})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _linreg_slope(values: List[float]) -> Optional[float]:
    """Plain linear-regression slope (per-step). None when degenerate."""
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return None
    return num / den


def _efficiency_ratio(closes: List[float]) -> Tuple[float, float, float, float]:
    """Return (net_signed, |net|, path, efficiency) on a list of closes.

    efficiency = |net| / Σ|Δclose|. 0 = pure chop, 1 = pure trend.
    net_signed retains direction (closes[-1] - closes[0]) so the caller can
    log the signed drift alongside the magnitude used for the override test.
    """
    if not closes or len(closes) < 2:
        return 0.0, 0.0, 0.0, 0.0
    net_signed = closes[-1] - closes[0]
    net_abs = abs(net_signed)
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    if path <= 0:
        return net_signed, net_abs, 0.0, 0.0
    return net_signed, net_abs, path, net_abs / path


def _load_recent_h1_closes(symbol: str, n: int) -> List[float]:
    """Load the last `n` H1 closes from the htf cache. Empty list on failure."""
    try:
        from trend_detection import load_h1_candles_from_cache
    except Exception:
        return []
    try:
        candles = load_h1_candles_from_cache(symbol) or []
    except Exception:
        return []
    if not candles:
        return []
    try:
        closes = [float(c["close"]) for c in candles[-n:]]
        return closes
    except (KeyError, TypeError, ValueError):
        return []


def _h1_ema_sign(h1_features: Dict[str, Any], flat_pips: float, pip_size: float) -> str:
    """UP / DOWN / FLAT from H1 EMA8 vs EMA21 separation."""
    e8 = h1_features.get("ema8")
    e21 = h1_features.get("ema21")
    if e8 is None or e21 is None:
        return "FLAT"
    try:
        sep_pips = (float(e8) - float(e21)) / max(float(pip_size), 1e-9)
    except (TypeError, ValueError):
        return "FLAT"
    if abs(sep_pips) < flat_pips:
        return "FLAT"
    return "UP" if sep_pips > 0 else "DOWN"


def _slope_sign(slope: Optional[float], flat_eps: float = 1e-9) -> str:
    if slope is None:
        return "FLAT"
    if slope > flat_eps:
        return "UP"
    if slope < -flat_eps:
        return "DOWN"
    return "FLAT"


def _w1_slope_sign(w1_features: Dict[str, Any]) -> str:
    closes = w1_features.get("closes_tail") or []
    if len(closes) < 3:
        return "FLAT"
    try:
        slope = _linreg_slope([float(x) for x in closes])
    except (TypeError, ValueError):
        return "FLAT"
    return _slope_sign(slope)


def _structure_dir(symbol: str) -> Tuple[str, Dict[str, Any]]:
    """5M structure direction from the most-recent close-break.

    Mirrors structure_exit's primitive (structure_exit.py:111-124) on the
    candle_builder 5M closed-bar buffer:
        flip_up   = close > max(prior N highs)
        flip_down = close < min(prior N lows)

    Walks the closed-bar series backwards from the most recent bar; returns
    the side of the FIRST flip encountered ("UP"/"DOWN"). FLAT when no flip
    is found in the available history — that's the indeterminate read that
    falls through to the existing D1/W1-confirm authority logic.

    Params (env, defaults):
        STRUCT_LEADS_N              = 5    (prior-bar window; matches
                                            STRUCTURE_EXIT_LOOKBACK_BARS default)
        STRUCT_LEADS_MIN_BREAK_PIPS = 0.0  (decisiveness floor; the close must
                                            exceed the prior extreme by this
                                            many pips. 0 reproduces structure_
                                            exit's bare > / <)
    """
    out: Dict[str, Any] = {
        "n_bars_seen": 0, "lookback": 0, "min_break_pips": 0.0,
        "flip_bar_ts": None, "prior_high": None, "prior_low": None,
        "close_at_flip": None,
    }
    try:
        import candle_builder
        df = candle_builder.get_df_raw(symbol)
    except Exception as exc:
        out["err"] = f"candle_builder_unavailable:{exc}"
        return "FLAT", out
    if df is None or len(df) == 0:
        out["err"] = "no_5m_bars"
        return "FLAT", out
    lookback = _env_int("STRUCT_LEADS_N", 5)
    min_break_pips = _env_float("STRUCT_LEADS_MIN_BREAK_PIPS", 0.0)
    out["lookback"] = lookback
    out["min_break_pips"] = min_break_pips
    n = len(df)
    out["n_bars_seen"] = n
    if n < lookback + 1:
        out["err"] = "insufficient_5m_bars"
        return "FLAT", out

    try:
        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        closes = df["close"].astype(float).values
        ts = (df["timestamp"].astype(str).values
              if "timestamp" in df.columns else [None] * n)
    except Exception as exc:
        out["err"] = f"df_columns_error:{exc}"
        return "FLAT", out

    # Walk backwards from the most recent CLOSED bar: the first flip we hit is
    # the most-recent one, and the structure direction "holds until an opposite
    # flip" — which is exactly what scan-backward-first-hit returns.
    for i in range(n - 1, lookback - 1, -1):
        prior_h = float(highs[i - lookback:i].max())
        prior_l = float(lows[i - lookback:i].min())
        c = float(closes[i])
        if c > prior_h + min_break_pips:
            out["flip_bar_ts"] = ts[i]
            out["prior_high"] = round(prior_h, 5)
            out["close_at_flip"] = round(c, 5)
            return "UP", out
        if c < prior_l - min_break_pips:
            out["flip_bar_ts"] = ts[i]
            out["prior_low"] = round(prior_l, 5)
            out["close_at_flip"] = round(c, 5)
            return "DOWN", out
    out["err"] = "no_flip_in_history"
    return "FLAT", out


def _exemption_check(symbol: str, direction: str) -> Tuple[bool, Dict[str, Any]]:
    """Exhaustion exemption for a counter-structure fade.

    Computes — on the candle_builder 5M closed-bar buffer — the same RSI(14)
    + MACD(12,26,9) hist + prior-swing-divergence signature that the 2026-06-06
    9-fire forensic validated:

        bearish_div (for SELL): setup_high > prior_swing_high
                                AND setup_RSI < prior_swing_RSI
        bullish_div (for BUY):  setup_low  < prior_swing_low
                                AND setup_RSI > prior_swing_RSI

    Prior-swing window: bars [n-31, n-16) relative to the last closed bar —
    i.e. the [-30, -15] window used in the forensic, where the swing extreme
    is the max-high (SELL) or min-low (BUY) over those 15 bars.

    Returns (allow, details). `allow` is True when divergence == Y AND
    |MACD hist| >= HTF_AUTH_STRUCT_EXEMPT_HIST_MIN.

    Pure read — never raises. Errors short-circuit to (False, {"err": ...}).
    """
    out: Dict[str, Any] = {
        "rsi": None, "rsi_div": "N", "hist": None,
        "prior_swing_px": None, "prior_swing_rsi": None,
        "setup_extreme": None, "n_bars": 0, "lookback": 30, "half": 15,
        "hist_min": _env_float("HTF_AUTH_STRUCT_EXEMPT_HIST_MIN", 0.5),
        "err": None,
    }
    direction_u = str(direction or "").upper()
    is_short = direction_u in ("SELL", "SHORT", "S")
    is_long = direction_u in ("BUY", "LONG", "L")
    if not (is_short or is_long):
        out["err"] = "unknown_direction"
        return False, out

    try:
        import candle_builder
        df = candle_builder.get_df_raw(symbol)
    except Exception as exc:
        out["err"] = f"candle_builder_unavailable:{exc}"
        return False, out
    if df is None:
        out["err"] = "no_5m_df"
        return False, out
    n = len(df)
    out["n_bars"] = n
    # Need: ≥35 bars for MACD/RSI warmup AND ≥31 bars for the swing window.
    if n < 35:
        out["err"] = "insufficient_5m_bars"
        return False, out

    try:
        from indicators import rsi as _rsi, macd as _macd
        closes = df["close"].astype(float)
        r = _rsi(closes, 14)
        md = _macd(closes, 12, 26, 9)
        hist = md.iloc[:, 2]
    except Exception as exc:
        out["err"] = f"indicator_error:{exc}"
        return False, out

    # Setup bar = last closed bar in the buffer.
    try:
        rsi_now = float(r.iloc[-1])
        hist_now = float(hist.iloc[-1])
    except Exception as exc:
        out["err"] = f"tail_value_error:{exc}"
        return False, out
    out["rsi"] = round(rsi_now, 2)
    out["hist"] = round(hist_now, 3)

    # Prior-swing window [n-31, n-16) — 15 bars centred ~22 bars before setup.
    lo = n - 1 - out["lookback"]
    hi = n - 1 - out["half"]
    if lo < 0 or hi <= lo:
        out["err"] = "swing_window_degenerate"
        return False, out

    try:
        if is_short:
            seg_h = df["high"].iloc[lo:hi].astype(float).values
            j_off = int(seg_h.argmax())
            prior_px = float(seg_h[j_off])
            prior_rsi = float(r.iloc[lo + j_off])
            setup_extreme = float(df["high"].iloc[-1])
            out["prior_swing_px"] = round(prior_px, 5)
            out["prior_swing_rsi"] = round(prior_rsi, 2)
            out["setup_extreme"] = round(setup_extreme, 5)
            if setup_extreme > prior_px and rsi_now < prior_rsi:
                out["rsi_div"] = "Y"
        else:  # is_long
            seg_l = df["low"].iloc[lo:hi].astype(float).values
            j_off = int(seg_l.argmin())
            prior_px = float(seg_l[j_off])
            prior_rsi = float(r.iloc[lo + j_off])
            setup_extreme = float(df["low"].iloc[-1])
            out["prior_swing_px"] = round(prior_px, 5)
            out["prior_swing_rsi"] = round(prior_rsi, 2)
            out["setup_extreme"] = round(setup_extreme, 5)
            if setup_extreme < prior_px and rsi_now > prior_rsi:
                out["rsi_div"] = "Y"
    except Exception as exc:
        out["err"] = f"swing_compute_error:{exc}"
        return False, out

    allow = (out["rsi_div"] == "Y") and (abs(hist_now) >= out["hist_min"])
    return allow, out


# ─────────────────────────────────────────────────────────────────────────────
# Core classification — TREND/RANGE call + committed direction.
# ─────────────────────────────────────────────────────────────────────────────
def _classify_market(symbol: str) -> Dict[str, Any]:
    """Return a dict describing the authority's view of the market.

    Output keys (always present):
        call                  — "TREND" | "RANGE"
        direction             — "UP" | "DOWN" | "NONE" (NONE only in TREND when
                                H1 sign disagrees with both D1 and W1 slope)
        why                   — short reason string
        htf_h1_state          — htf_regime's h1_state
        htf_d1_state          — htf_regime's d1_state
        htf_w1_state          — htf_regime's w1_state
        htf_alignment         — htf_regime's alignment
        h1_ema_sign           — UP / DOWN / FLAT
        d1_slope_sign         — UP / DOWN / FLAT
        w1_slope_sign         — UP / DOWN / FLAT
        eff_window_bars       — H1 bars used for the net-progress check
        eff_net_pips          — |net move| over the window, in pips
        eff_ratio             — |net| / Σ|Δclose|
        drift_override_fired  — bool, True if RANGE was overridden to TREND
        pip_size              — pip_size used
        error                 — set if classify failed (call falls back to RANGE)
    """
    out: Dict[str, Any] = {
        "call": "RANGE", "direction": "NONE", "why": "",
        "htf_h1_state": None, "htf_d1_state": None, "htf_w1_state": None,
        "htf_alignment": None,
        "h1_ema_sign": "FLAT", "d1_slope_sign": "FLAT", "w1_slope_sign": "FLAT",
        "eff_window_bars": 0, "eff_net_pips": 0.0, "eff_net_pips_signed": 0.0,
        "eff_ratio": 0.0,
        "drift_override_fired": False, "pip_size": 1.0,
        "structure_dir": "FLAT", "structure_n": 0,
        "structure_min_break_pips": 0.0, "structure_flip_bar_ts": None,
        "structure_lead_enabled": False, "structure_lead_fired": False,
    }
    try:
        import htf_regime as _htf
        htf = _htf.classify(symbol) or {}
    except Exception as exc:
        out["error"] = f"htf_classify_failed: {exc}"
        out["why"] = "htf_unavailable_fallback_RANGE"
        return out

    debug = htf.get("debug") or {}
    h1_features = debug.get("h1_features") or {}
    d1_features = debug.get("d1_features") or {}
    w1_features = debug.get("w1_features") or {}
    pip_size = float(debug.get("pip_size") or 1.0)
    out["pip_size"] = pip_size
    out["htf_h1_state"] = htf.get("h1_state")
    out["htf_d1_state"] = htf.get("d1_state")
    out["htf_w1_state"] = htf.get("w1_state")
    out["htf_alignment"] = htf.get("alignment")

    # Direction inputs.
    flat_pips = _env_float("HTF_AUTH_H1_FLAT_PIPS", 0.5)
    h1_sign = _h1_ema_sign(h1_features, flat_pips, pip_size)
    d1_slope = d1_features.get("ema_slope")
    d1_sign = _slope_sign(d1_slope)
    w1_sign = _w1_slope_sign(w1_features)
    out["h1_ema_sign"] = h1_sign
    out["d1_slope_sign"] = d1_sign
    out["w1_slope_sign"] = w1_sign

    # Net-progress check over the H1 window.
    window = _env_int("HTF_AUTH_H1_WINDOW", 24)
    drift_pips_min = _env_float("HTF_AUTH_DRIFT_PIPS_MIN", 15.0)
    eff_ratio_min = _env_float("HTF_AUTH_EFF_RATIO_MIN", 0.08)
    closes = _load_recent_h1_closes(symbol, window)
    if closes:
        net_signed_raw, net_abs_raw, _path, eff = _efficiency_ratio(closes)
        net_pips_signed = net_signed_raw / max(pip_size, 1e-9)
        net_pips = net_abs_raw / max(pip_size, 1e-9)
        out["eff_window_bars"] = len(closes)
        out["eff_net_pips"] = round(net_pips, 2)
        out["eff_net_pips_signed"] = round(net_pips_signed, 2)
        out["eff_ratio"] = round(eff, 4)
    else:
        net_pips = 0.0
        net_pips_signed = 0.0
        eff = 0.0

    # ── TREND vs RANGE call ────────────────────────────────────────────────
    h1_state = (htf.get("h1_state") or "").upper()
    # htf_regime label set (per htf_regime.py state constants):
    #   TRENDING_UP / TRENDING_DOWN / RANGE / COMPRESSION / EXPANSION / EXHAUSTION
    trend_states = {"TRENDING_UP", "TRENDING_DOWN", "EXPANSION", "EXHAUSTION"}
    range_states = {"RANGE", "COMPRESSION"}

    if h1_state in trend_states:
        call = "TREND"
        why_bits = [f"htf_h1={h1_state}"]
    elif h1_state in range_states:
        # Net-progress override: choppy-but-directional drift still reads TREND.
        if net_pips >= drift_pips_min and eff >= eff_ratio_min:
            call = "TREND"
            out["drift_override_fired"] = True
            why_bits = [
                f"htf_h1={h1_state} OVERRIDDEN_by_drift",
                f"net={net_pips_signed:+.1f}p (|net|>={drift_pips_min})",
                f"eff={eff:.3f}>={eff_ratio_min}",
            ]
        else:
            call = "RANGE"
            why_bits = [
                f"htf_h1={h1_state}",
                f"net={net_pips_signed:+.1f}p", f"eff={eff:.3f}",
            ]
    else:
        # Unknown / missing state — be conservative, call RANGE.
        call = "RANGE"
        why_bits = [f"htf_h1={h1_state or 'UNKNOWN'}_fallback_RANGE"]
    out["call"] = call

    # ── Direction authority (only meaningful in TREND) ─────────────────────
    if call == "TREND":
        # H1 sign confirmed by D1 OR W1 slope sign agreeing.
        candidates = {s for s in (d1_sign, w1_sign) if s in ("UP", "DOWN")}
        if h1_sign in ("UP", "DOWN") and h1_sign in candidates:
            out["direction"] = h1_sign
            confirmers = [t for t, s in (("D1", d1_sign), ("W1", w1_sign)) if s == h1_sign]
            why_bits.append(f"H1={h1_sign} confirmed_by={'+'.join(confirmers)}")
        elif h1_sign == "FLAT":
            out["direction"] = "NONE"
            why_bits.append("H1=FLAT_no_direction")
        else:
            # H1 has a sign but neither D1 nor W1 confirms — indeterminate.
            out["direction"] = "NONE"
            why_bits.append(f"H1={h1_sign} unconfirmed (D1={d1_sign},W1={w1_sign})")
    else:
        out["direction"] = "NONE"  # RANGE: direction is ignored anyway

    # ── STRUCTURE-LEADS override (flag-gated, post-classification) ────────
    # Mirrors structure_exit's 5M close-break primitive: the side of the most-
    # recent flip (flip_up / flip_down vs prior-N high/low) becomes the
    # authority. Forces call=TREND and direction=structure_dir, regardless of
    # D1/W1 confirmation OR the prior RANGE/TREND call. Counter-trend entries
    # against the most-recent flip are blocked at the evaluate() layer.
    # FLAT (no flip in history) falls through to the existing direction logic.
    struct_lead_enabled = _env_bool("HTF_AUTH_STRUCTURE_LEADS_ENABLED", "0")
    range_standdown_enabled = _env_bool("HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED", "0")
    structure_dir, struct_details = _structure_dir(symbol)
    out["structure_dir"] = structure_dir
    out["structure_n"] = struct_details.get("lookback", 0)
    out["structure_min_break_pips"] = struct_details.get("min_break_pips", 0.0)
    out["structure_flip_bar_ts"] = struct_details.get("flip_bar_ts")
    out["structure_lead_enabled"] = struct_lead_enabled
    out["structure_lead_range_standdown_enabled"] = range_standdown_enabled
    out["structure_lead_range_standdown_fired"] = False
    # RANGE carve-out: when the HTF call (post-drift-override) is RANGE, the
    # structure-leads override would convert a mean-reversion day into a fake
    # TREND and block reversal entries. Flag-gated; default OFF preserves the
    # current "structure-always-wins" behaviour.
    _standdown_in_range = (
        range_standdown_enabled
        and out["call"] == "RANGE"
        and structure_dir in ("UP", "DOWN")
    )
    if struct_lead_enabled and structure_dir in ("UP", "DOWN") and not _standdown_in_range:
        prior_call = out["call"]
        prior_dir = out["direction"]
        out["call"] = "TREND"
        out["direction"] = structure_dir
        out["structure_lead_fired"] = True
        why_bits.append(
            f"STRUCTURE_LEADS:{structure_dir} "
            f"flip_bar={struct_details.get('flip_bar_ts')} "
            f"N={struct_details.get('lookback')} "
            f"override(call:{prior_call}->TREND,dir:{prior_dir}->{structure_dir})"
        )
    elif struct_lead_enabled and _standdown_in_range:
        out["structure_lead_range_standdown_fired"] = True
        why_bits.append(
            f"STRUCTURE_LEADS_STANDDOWN:RANGE "
            f"(structure={structure_dir} not applied; call stays RANGE)"
        )

    # ── ADX-floor RANGE→TREND override (2026-06-18) ────────────────
    # The htf_regime classifier is momentum-blind — it consults H1 EMA
    # ordering + slope + MACD but never ADX. On fresh impulses the H1
    # EMA stack lags and the classifier falls through to RANGE at
    # htf_regime.py:478, even when the 5M regime engine reports
    # STRONG_TREND_* with ADX above floor. This override consults the
    # 5M regime engine's ADX and promotes RANGE→TREND when momentum
    # clearly disagrees with the H1 read. Gate is EXACTLY
    # out["call"] == "RANGE" — never touches a TREND call.
    # Direction: structure_dir (preferred — same primitive
    # STRUCTURE_LEADS uses) or regime_engine.directional_bias; aborts
    # cleanly when neither resolves.
    adx_floor = _env_float("HTF_AUTH_ADX_TREND_FLOOR", 25.0)
    adx_override_enabled = _env_bool("HTF_AUTH_ADX_OVERRIDE_ENABLED", "0")
    out["adx_override_fired"] = False
    if adx_override_enabled and out["call"] == "RANGE":
        try:
            import regime_engine as _re
            _rg = _re.latest_result(symbol) or {}
            _adx_now = _rg.get("ADX")
            _bias = str(_rg.get("directional_bias") or "").upper()
        except Exception:
            _adx_now = None
            _bias = ""
        if _adx_now is not None and float(_adx_now) >= adx_floor:
            new_dir = None
            if structure_dir in ("UP", "DOWN"):
                new_dir = structure_dir
            elif _bias == "LONG":
                new_dir = "UP"
            elif _bias == "SHORT":
                new_dir = "DOWN"
            if new_dir is not None:
                prior_call = out["call"]
                out["call"] = "TREND"
                out["direction"] = new_dir
                out["adx_override_fired"] = True
                out["adx_override_value"] = float(_adx_now)
                out["adx_override_floor"] = float(adx_floor)
                out["adx_override_direction_source"] = (
                    "structure_dir" if structure_dir in ("UP", "DOWN")
                    else "regime_engine_bias"
                )
                why_bits.append(
                    f"ADX_OVERRIDE adx={float(_adx_now):.1f}>="
                    f"floor={adx_floor:.1f} (call:{prior_call}->TREND "
                    f"dir->{new_dir} via {out['adx_override_direction_source']})"
                )

    out["why"] = "; ".join(why_bits)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry — one row per evaluate() call.
# ─────────────────────────────────────────────────────────────────────────────
def _write_log(rec: Dict[str, Any]) -> None:
    try:
        d = os.path.dirname(TELEMETRY_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(TELEMETRY_PATH, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[htf_authority] telemetry write failed: %s", exc)


def _fetch_5m_label(symbol: str) -> Optional[str]:
    """Best-effort pull of the latest 5m regime_engine label, for log-only
    comparison against the HTF call. Never raises."""
    try:
        import regime_engine as _re
        r = _re.latest_result(symbol) or {}
        return r.get("winning_regime")
    except Exception:
        return None


def _fetch_5m_close(symbol: str) -> Optional[float]:
    """Best-effort latest 5m close (used as a proxy signal price in the
    BB-block shadow log). Never raises; returns None when unavailable."""
    try:
        import regime_engine as _re
        r = _re.latest_result(symbol) or {}
        feats = r.get("full_features") or {}
        c = feats.get("close")
        return float(c) if c is not None else None
    except Exception:
        return None


def _write_bb_block_shadow(rec: Dict[str, Any]) -> None:
    """Append one JSONL row to BB_BLOCK_SHADOW_PATH. Swallowing writer —
    telemetry-only, must never raise back into the gate path."""
    try:
        d = os.path.dirname(BB_BLOCK_SHADOW_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(BB_BLOCK_SHADOW_PATH, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[htf_authority] bb_block_shadow write failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def evaluate(symbol: str, direction: str, mode: str) -> Tuple[bool, str, Dict[str, Any]]:
    """Evaluate the HTF-authority gate.

    Returns (allow, reason, details).

    Behaviour by flag:
        HTF_AUTHORITY_ENABLED=1  → classify, decide, log (enforced=True), return
                                    the decision (may BLOCK).
        HTF_AUTHORITY_ENABLED=0  → classify, log (enforced=False) with the
                                    decision the gate WOULD have made, then
                                    return PASS unconditionally. Logging-only
                                    mirror of the live path so we can score
                                    the call before flipping the switch on.

    Fail-open invariant: when the flag is OFF, no exception path returns BLOCK.
    The classify+log block is wrapped so any failure (htf_regime unavailable,
    candle cache gap, disk write error, anything) still returns PASS. Even when
    ON, infrastructure errors in trade_executor's outer try/except keep that
    same fail-open posture at the call site.

    Block conditions (only enforced when ENABLED=1):
        call=RANGE AND mode NOT IN REVERSAL_MODES                     → BLOCK
        call=TREND AND direction is counter to authority direction    → BLOCK
    All other combinations PASS. Indeterminate direction (NONE) fails open.
    """
    enabled = _env_bool("HTF_AUTHORITY_ENABLED", "0")
    sym = str(symbol or "").upper()
    dir_u = str(direction or "").upper()
    mode_u = str(mode or "").upper()
    is_long = dir_u in ("BUY", "LONG", "L")
    is_short = dir_u in ("SELL", "SHORT", "S")
    is_reversal = mode_u in REVERSAL_MODES

    try:
        classification = _classify_market(sym)
        call = classification["call"]
        authority_dir = classification["direction"]
        why = classification["why"]
        overridden_5m_label = _fetch_5m_label(sym)

        # The decision the gate WOULD make — computed regardless of `enabled`,
        # so the OFF-mode log row carries the same call/reason as the ON path.
        would_pass = True
        would_reason = ""

        if call == "RANGE":
            if is_reversal:
                would_pass, would_reason = True, f"PASS:RANGE_reversal_allowed:{mode_u}"
            elif (mode_u in STRUCTURE_BREAK_MODES
                  and _env_bool("STRUCTURE_BREAK_HTF_RANGE_EXEMPT_ENABLED", "0")
                  and ((is_long and classification.get("structure_dir") == "UP")
                       or (is_short and classification.get("structure_dir") == "DOWN"))):
                # Scoped RANGE-branch carve-out for structure_break (2026-06-17).
                # The break direction governs: when the firing mode is a
                # structure_break breakout AND the most-recent N-bar flip aligns
                # with the trade side, the RANGE_no_continuation veto is lifted.
                # Counter-break direction (e.g. SELL with structure_dir=UP) and
                # structure_dir=FLAT both still BLOCK at the else branch below.
                # All non-RANGE branches and structure_break's own gates
                # (decisive-pips, ADX floor, ATR, regime) are unchanged.
                would_pass = True
                would_reason = (
                    f"PASS:RANGE_STRUCTURE_BREAK_EXEMPT:{mode_u}:"
                    f"dir={dir_u}:struct={classification.get('structure_dir')}"
                )
                logger.info(
                    "[HTF-AUTHORITY] STRUCT_BREAK exempt FIRED: %s %s "
                    "call=RANGE→exempt structure_dir=%s — "
                    "RANGE_no_continuation suppressed",
                    mode_u, dir_u, classification.get("structure_dir"),
                )
            else:
                would_pass, would_reason = False, f"BLOCKED:RANGE_no_continuation:{mode_u}"
        else:  # TREND
            if authority_dir == "UP":
                if is_short:
                    would_pass, would_reason = False, "BLOCKED:SHORT_counter_TREND_UP"
                else:
                    would_pass, would_reason = True, "PASS:LONG_with_TREND_UP"
            elif authority_dir == "DOWN":
                if is_long:
                    would_pass, would_reason = False, "BLOCKED:LONG_counter_TREND_DOWN"
                else:
                    would_pass, would_reason = True, "PASS:SHORT_with_TREND_DOWN"
            else:
                would_pass, would_reason = True, "PASS:TREND_direction_indeterminate"

        # ── BB-reversal TREND-branch confirmation-only carve-out ──────────
        # When BB_BOUNCE_TREND_CONFIRMED_ONLY=1 and the firing mode is a
        # reversal (REVERSAL_MODES), the TREND-branch counter-direction
        # block is kept ONLY if all 3 HTF frames (h1_state / d1_state /
        # w1_state) agree with authority_dir. On a non-confirmed block
        # (<3 frames) the carve-out flips would_pass→True with reason
        # TREND_reversal_unconfirmed; the n/3 frame count is in the
        # reason string and an info-level log records the prior block
        # reason + which frames agreed. Default OFF preserves the
        # current TREND counter-trend behaviour. Symmetric in spirit to
        # the RANGE-branch is_reversal PASS above.
        # Frame-alignment definition (matches 2026-06-22 audit, Defn B —
        # uses the adjudicated d1/w1 trend labels, not raw slope signs):
        #   h1_state == f"TRENDING_{authority_dir}"
        #   d1_state == authority_dir      (bare UP/DOWN)
        #   w1_state == authority_dir      (bare UP/DOWN)
        # Scope: REVERSAL_MODES only — continuation strategies still
        # block counter-trend; EMA_PULLBACK exemption (below) and the
        # RANGE branch (above) are byte-unchanged.
        if (call == "TREND"
                and is_reversal
                and not would_pass
                and authority_dir in ("UP", "DOWN")
                and _env_bool("BB_BOUNCE_TREND_CONFIRMED_ONLY", "0")):
            h1_state_val = (classification.get("htf_h1_state") or "").upper()
            d1_state_val = (classification.get("htf_d1_state") or "").upper()
            w1_state_val = (classification.get("htf_w1_state") or "").upper()
            h1_ok = h1_state_val == f"TRENDING_{authority_dir}"
            d1_ok = d1_state_val == authority_dir
            w1_ok = w1_state_val == authority_dir
            frames = int(h1_ok) + int(d1_ok) + int(w1_ok)
            if frames < 3:
                prior_decision = "BLOCK"
                prior_reason = would_reason
                would_pass = True
                would_reason = (
                    f"PASS:TREND_reversal_unconfirmed:{mode_u}:"
                    f"frames={frames}/3"
                )
                agreed = []
                if h1_ok:
                    agreed.append("h1_state")
                if d1_ok:
                    agreed.append("d1_state")
                if w1_ok:
                    agreed.append("w1_state")
                logger.info(
                    "[HTF-AUTHORITY] TREND_CONFIRMED_ONLY carve-out "
                    "FIRED: %s %s call=TREND authority=%s prior=%s(%s) "
                    "frames_agreed=%s",
                    mode_u, dir_u, authority_dir, prior_decision,
                    prior_reason,
                    ",".join(agreed) if agreed else "none",
                )

        # ── EMA_PULLBACK exemption (covers both RANGE and counter-TREND) ──
        # Mirrors STRUCTURE_BREAK_HTF_RANGE_EXEMPT shape (frozenset + env flag
        # + would_pass override + logger.info emit) but applied as a late
        # override AFTER the RANGE/TREND decision tree completes — so the
        # tree itself stays byte-identical and the BB_BOUNCE / STRUCTURE_BREAK
        # paths are untouched. When EMA_PULLBACK_HTF_EXEMPT_ENABLED=1 and the
        # firing mode is GBPUSD_EMA_PULLBACK_L/S, the strategy's own H1
        # EMA8/21 read (≥2.0p separation, 0.5p h1_ema_direction floor) is
        # authoritative on direction. classification fields (h1_state, call,
        # why, etc.) are preserved in details unchanged.
        if (mode_u in EMA_PULLBACK_MODES
                and _env_bool("EMA_PULLBACK_HTF_EXEMPT_ENABLED", "0")):
            prior_decision = "PASS" if would_pass else "BLOCK"
            prior_reason = would_reason
            would_pass = True
            would_reason = (
                f"PASS:HTF_EXEMPT:EMA_PULLBACK:{mode_u}:"
                f"dir={dir_u}:call={call}"
            )
            logger.info(
                "[HTF-AUTHORITY] EMA_PULLBACK exempt FIRED: %s %s "
                "call=%s prior=%s(%s) — strategy H1 read governs",
                mode_u, dir_u, call, prior_decision, prior_reason,
            )

        # ── NEWS_STRATEGY exemption (covers both RANGE and counter-TREND) ─
        # Mirrors the EMA_PULLBACK shape (frozenset + env flag + would_pass
        # override + logger.info emit) applied as a late override AFTER the
        # RANGE/TREND decision tree completes — the tree itself stays
        # byte-identical and every other strategy's gating is untouched.
        # When HTF_AUTH_NEWS_EXEMPT_ENABLED=1 (default ON — bug fix per
        # 2026-06-28 audit) and the firing mode is NEWS_STRATEGY_FADE /
        # NEWS_STRATEGY_CONT / NEWS_STRATEGY, the economic-surprise
        # catalyst is authoritative; the HTF call is logged in details
        # but does not veto.
        if (mode_u in NEWS_STRATEGY_MODES
                and _env_bool("HTF_AUTH_NEWS_EXEMPT_ENABLED", "1")):
            prior_decision = "PASS" if would_pass else "BLOCK"
            prior_reason = would_reason
            would_pass = True
            would_reason = (
                f"PASS:HTF_EXEMPT:NEWS_STRATEGY:{mode_u}:"
                f"dir={dir_u}:call={call}"
            )
            logger.info(
                "[HTF-AUTHORITY] NEWS_STRATEGY exempt FIRED: %s %s "
                "call=%s prior=%s(%s) — news catalyst governs",
                mode_u, dir_u, call, prior_decision, prior_reason,
            )

        # ── Exhaustion exemption (counter-structure block rescue) ─────────
        # Evaluated on every counter-structure block whether the exemption
        # flag is on or off — so live telemetry accumulates the div/hist
        # readings on every blocked fade. Only fires (flips would_pass→True)
        # when HTF_AUTH_STRUCT_EXEMPT_ENABLED=1 AND the rule passes. Bound to
        # the structure-leads override specifically: doesn't rescue blocks
        # that came from the legacy D1/W1-confirm direction.
        exempt_details: Dict[str, Any] = {
            "evaluated": False, "enabled": False, "fired": False,
            "div": "N", "rsi": None, "hist": None, "hist_min": None,
            "prior_swing_px": None, "prior_swing_rsi": None,
            "setup_extreme": None, "n_bars": 0, "err": None,
        }
        if (not would_pass
                and classification.get("structure_lead_fired")
                and (is_short or is_long)):
            exempt_enabled = _env_bool("HTF_AUTH_STRUCT_EXEMPT_ENABLED", "0")
            allow, edet = _exemption_check(sym, dir_u)
            exempt_details.update({
                "evaluated": True,
                "enabled": exempt_enabled,
                "div": edet.get("rsi_div", "N"),
                "rsi": edet.get("rsi"),
                "hist": edet.get("hist"),
                "hist_min": edet.get("hist_min"),
                "prior_swing_px": edet.get("prior_swing_px"),
                "prior_swing_rsi": edet.get("prior_swing_rsi"),
                "setup_extreme": edet.get("setup_extreme"),
                "n_bars": edet.get("n_bars", 0),
                "err": edet.get("err"),
            })
            if exempt_enabled and allow:
                exempt_details["fired"] = True
                would_pass = True
                hist_val = edet.get("hist")
                hist_min_val = edet.get("hist_min", 0.5)
                would_reason = (
                    f"PASS:STRUCT_EXEMPT:div=Y,|hist|="
                    f"{abs(hist_val) if hist_val is not None else 0:.2f}"
                    f">={hist_min_val:.2f}"
                )

        details: Dict[str, Any] = {
            "enabled": enabled,
            "enforced": enabled,  # explicit: did this decision actually gate the fire?
            "symbol": sym, "direction": dir_u, "mode": mode_u,
            "is_reversal": is_reversal,
            "call": call,
            "authority_direction": authority_dir,
            "why": why,
            "would_decision": "PASS" if would_pass else "BLOCK",
            "would_reason": would_reason,
            "overridden_5m_regime": overridden_5m_label,
            "h1_state": classification["htf_h1_state"],
            "d1_state": classification["htf_d1_state"],
            "w1_state": classification["htf_w1_state"],
            "alignment": classification["htf_alignment"],
            "h1_ema_sign": classification["h1_ema_sign"],
            "d1_slope_sign": classification["d1_slope_sign"],
            "w1_slope_sign": classification["w1_slope_sign"],
            "eff_window_bars": classification["eff_window_bars"],
            "eff_net_pips": classification["eff_net_pips"],
            "eff_net_pips_signed": classification["eff_net_pips_signed"],
            "eff_ratio": classification["eff_ratio"],
            "drift_override_fired": classification["drift_override_fired"],
            # ADX-floor RANGE→TREND override fields (f4216cf, 2026-06-18).
            # .get() so the early-return path at _classify_market line 409
            # (htf_regime unavailable) doesn't KeyError — those rows just
            # carry None/False and the boolean field is still present.
            "adx_override_fired": classification.get("adx_override_fired", False),
            "adx_override_value": classification.get("adx_override_value"),
            "adx_override_floor": classification.get("adx_override_floor"),
            "adx_override_direction_source": classification.get("adx_override_direction_source"),
            "structure_dir": classification["structure_dir"],
            "structure_n": classification["structure_n"],
            "structure_min_break_pips": classification["structure_min_break_pips"],
            "structure_flip_bar_ts": classification["structure_flip_bar_ts"],
            "structure_lead_enabled": classification["structure_lead_enabled"],
            "structure_lead_fired": classification["structure_lead_fired"],
            "exempt_evaluated": exempt_details["evaluated"],
            "exempt_enabled": exempt_details["enabled"],
            "exempt_fired": exempt_details["fired"],
            "exempt_div": exempt_details["div"],
            "exempt_rsi": exempt_details["rsi"],
            "exempt_hist": exempt_details["hist"],
            "exempt_hist_min": exempt_details["hist_min"],
            "exempt_prior_swing_px": exempt_details["prior_swing_px"],
            "exempt_prior_swing_rsi": exempt_details["prior_swing_rsi"],
            "exempt_setup_extreme": exempt_details["setup_extreme"],
            "exempt_n_bars": exempt_details["n_bars"],
            "exempt_err": exempt_details["err"],
        }
        if "error" in classification:
            details["error"] = classification["error"]

        # ── News-state passive logger (PURE TELEMETRY, no gating) ─────────
        # Only run when NEWS_STATE_LOGGING_ENABLED=1. Failure mode: any
        # exception inside news_state_snapshot() returns a dict with
        # news_state="UNKNOWN" — never raises. Nothing in this function,
        # _classify_market(), the exemption logic, or trade_executor reads
        # any news_* field back — this is write-only into the telemetry row.
        if _env_bool("NEWS_STATE_LOGGING_ENABLED", "0"):
            try:
                import news_state as _ns
                details.update(_ns.news_state_snapshot())
            except Exception as _ns_exc:
                # belt-and-braces — _ns.news_state_snapshot itself shouldn't
                # raise, but if even the import fails we still don't fault.
                details["news_state"] = "UNKNOWN"
                details["news_state_source"] = f"unknown_import_{type(_ns_exc).__name__}"

        # Final returned decision: enforce only when ENABLED. When OFF, the
        # gate is observational — log what we WOULD have done, return PASS.
        if enabled:
            ret_pass, ret_reason = would_pass, would_reason
        else:
            ret_pass = True
            ret_reason = f"SHADOW({would_reason})"  # marks as observational

        rec = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": "PASS" if ret_pass else "BLOCK",
            "reason": ret_reason,
            **details,
        }
        _write_log(rec)

        # ── BB-reversal block shadow log (PURE TELEMETRY, no gating) ──────
        # Records every enforced counter-trend block of a BB-reversal-family
        # mode so the ±target outcome can be scored later from candles. Gate
        # behind BB_BLOCK_SHADOW_ENABLED (default 1). Failures swallowed.
        if (enabled and is_reversal and not ret_pass
                and "counter_TREND" in (ret_reason or "")
                and _env_bool("BB_BLOCK_SHADOW_ENABLED", "1")):
            try:
                _write_bb_block_shadow({
                    "ts": rec["timestamp"],
                    "symbol": sym,
                    "mode": mode_u,
                    "direction": dir_u,
                    "signal_price": _fetch_5m_close(sym),
                    "htf_h1_call": classification["htf_h1_state"],
                    "call": call,
                    "authority_direction": authority_dir,
                    "net_pips_signed": classification["eff_net_pips_signed"],
                    "eff_ratio": classification["eff_ratio"],
                    "drift_override_fired": classification["drift_override_fired"],
                    "structure_lead_fired": classification["structure_lead_fired"],
                    "exempt_evaluated": exempt_details["evaluated"],
                    "exempt_fired": exempt_details["fired"],
                    "thresh_drift_pips_min": _env_float("HTF_AUTH_DRIFT_PIPS_MIN", 15.0),
                    "thresh_eff_ratio_min": _env_float("HTF_AUTH_EFF_RATIO_MIN", 0.08),
                    "reason": ret_reason,
                })
            except Exception as _bbs_exc:
                logger.debug("[htf_authority] bb_block_shadow build failed: %s", _bbs_exc)

        return ret_pass, ret_reason, details

    except Exception as exc:
        # Fail-open: never let a classify/log fault block a fire, ever — this
        # is the contract for both ON and OFF paths. Best-effort log of the
        # error itself; that write is also wrapped (_write_log swallows).
        err_details: Dict[str, Any] = {
            "enabled": enabled,
            "enforced": enabled,
            "symbol": sym, "direction": dir_u, "mode": mode_u,
            "is_reversal": is_reversal,
            "error": f"{type(exc).__name__}: {exc}",
        }
        try:
            _write_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "decision": "PASS",
                "reason": "htf_authority_exception_fail_open",
                **err_details,
            })
        except Exception:
            pass
        return True, "htf_authority_exception_fail_open", err_details


def startup_banner() -> str:
    enabled = _env_bool("HTF_AUTHORITY_ENABLED", "0")
    struct_leads = _env_bool("HTF_AUTH_STRUCTURE_LEADS_ENABLED", "0")
    struct_exempt = _env_bool("HTF_AUTH_STRUCT_EXEMPT_ENABLED", "0")
    range_standdown = _env_bool("HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED", "0")
    sb_range_exempt = _env_bool("STRUCTURE_BREAK_HTF_RANGE_EXEMPT_ENABLED", "0")
    ema_pullback_exempt = _env_bool("EMA_PULLBACK_HTF_EXEMPT_ENABLED", "0")
    return (
        f"[HTF-AUTHORITY] enabled={enabled} "
        f"STRUCTURE_LEADS={struct_leads} "
        f"STRUCT_RANGE_STANDDOWN={range_standdown} "
        f"STRUCT_N={_env_int('STRUCT_LEADS_N', 5)} "
        f"STRUCT_MIN_BREAK={_env_float('STRUCT_LEADS_MIN_BREAK_PIPS', 0.0)}p "
        f"STRUCT_EXEMPT={struct_exempt} "
        f"SB_RANGE_EXEMPT={sb_range_exempt} "
        f"EMA_PULLBACK_EXEMPT={ema_pullback_exempt} "
        f"HIST_MIN={_env_float('HTF_AUTH_STRUCT_EXEMPT_HIST_MIN', 0.5)} "
        f"H1_WINDOW={_env_int('HTF_AUTH_H1_WINDOW', 24)} "
        f"DRIFT_MIN={_env_float('HTF_AUTH_DRIFT_PIPS_MIN', 15.0)}p "
        f"EFF_MIN={_env_float('HTF_AUTH_EFF_RATIO_MIN', 0.08)} "
        f"H1_FLAT={_env_float('HTF_AUTH_H1_FLAT_PIPS', 0.5)}p "
        f"log={TELEMETRY_PATH}"
    )
