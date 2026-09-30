"""
guards/range_gate.py — RANGE GATE: suppress trend-family fires inside a range.

Why this exists
================
2026-06-30 midday (11:35–13:20) was a textbook range: bb_w(20,2) plateau
at 22–24p with Kaufman ER(10) 0.01–0.35. The V-bottom floor held and
ripped up. L3 SB_S (bb_w=23.4, ER10=0.012) and L4 EMA_PB_S (bb_w=23.4,
ER10=0.012) sold INTO that floor — false breakouts that reverted (-27p
combined).

This gate is the MIRROR of the BB_BOUNCE STRONG_TREND stand-down
(55cea3b): instead of suppressing fade fires when a STRONG trend is
running, it suppresses TREND fires when a RANGE is running. Opposite
direction, same shape (regime-based suppression at the fire point).

Range detector (BOTH must hold)
================================
    bb_w_pips ≥ RANGE_GATE_BBW_MIN   (wide bands)
    ER(N)     ≤ RANGE_GATE_ER_MAX    (low efficiency)

Wide bands + low ER = oscillating with amplitude = RANGE. Tight bands +
low ER = CHOP (NOT a range — the bb_w floor's job, not ours). The gate
must NOT fire there.

Validated on 2026-06-30
    12:25 SB_S   bb_w 23.4  ER10 0.012  →  SUPPRESS (range — saves -11.65p)
    12:25 EMA_PB_S bb_w 23.4 ER10 0.012  →  SUPPRESS (saves -15.80p)
    10:45 BB_BOUNCE / 11:30 BB_BOUNCE     →  EXEMPT (fade strategy)
    14:55 SB_L   bb_w ~38–45 ER10 high   →  ALLOWED (real trend, not range)
    Chop squeeze bb_w 5.7–6p             →  ALLOWED (not range — bb_w < 15)

Scope (mode-allowlist for SUPPRESSION)
======================================
Applies ONLY to the TREND family (mirror of how the stretch brake
allowlists continuation strategies, but here the list is broader and
includes TREND_V3):
    GBPUSD_STRUCTURE_BREAK_L / GBPUSD_STRUCTURE_BREAK_S
    GBPUSD_EMA_PULLBACK_L    / GBPUSD_EMA_PULLBACK_S
    GBPUSD_TREND_V3_L        / GBPUSD_TREND_V3_S

EXEMPT — never suppressed (these strategies trade ranges by design):
    GBPUSD_BB_BOUNCE_L / S
    GBPUSD_CONFIRMATION_FALLBACK_L / S
    BB_REV_PAT / any other fade / mean-reversion strategy.

Direction-agnostic: in a range a break either way is a false breakout,
so the gate ignores LONG/SHORT and blocks if mode is in the allowlist.

Inputs
======
bb_w  — Bollinger Band(20,2) width in pips, computed at call time from
        bars[-20:] closes. Period mirrors signal_logger._bb_width_pips
        and gbpusd_ema_pullback (both use BB(20,2)).
ER    — Kaufman efficiency ratio, reused from gbpusd_trend_v3._kaufman_er
        (same ER implementation as the stretch brake). Lookback is
        RANGE_GATE_ER_BARS (default 10, the sharp read; ER20 carries
        residual trend leg and mis-reads).

Env (read at call time — flippable without restart)
====================================================
RANGE_GATE_ENABLED    "1"     master on/off
RANGE_GATE_BBW_MIN    "15"    pips — wide-band threshold (range/chop split)
RANGE_GATE_ER_MAX     "0.35"  block iff ER ≤ this (low ER = not-trend)
RANGE_GATE_ER_BARS    "10"    Kaufman ER lookback (closes)

Stacking
========
ADDITIVE to every other gate. Stacks with the SB daily-filter, the
trend stretch brake, transition / velocity / conviction / slot gates.
Each gate can independently block. Overlaps with the stretch brake on
the L3/L4 V-bottom shorts (both would block) — that is fine; they are
complementary (brake catches stretched fires; range gate catches all
trend fires in a range, including non-stretched ones). Each gate logs
to its own jsonl so there is no double-logging.

Fail-open everywhere: missing bb_w / ER / out-of-scope mode all return
block=False. The gate ADDS new blocks for a specific pattern; it never
blocks anything the existing pipeline already would have fired.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

logger = logging.getLogger("range_gate")

# Greppable tag — matches the format the user asked for:
#     [RANGE_GATE] SUPPRESS — {strategy} {dir} @ bb_w={x}p ER={er} ...
LOG_TAG = "RANGE_GATE"

# Mode allowlist — TREND FAMILY ONLY. Fade strategies are NOT in this
# set and therefore physically cannot be suppressed. The allowlist is
# the safety mechanism: if a caller passes a fade-strategy mode, the
# gate returns block=False unconditionally.
ALLOWED_MODES = frozenset({
    "GBPUSD_STRUCTURE_BREAK_L",
    "GBPUSD_STRUCTURE_BREAK_S",
    "GBPUSD_EMA_PULLBACK_L",
    "GBPUSD_EMA_PULLBACK_S",
    "GBPUSD_TREND_V3_L",
    "GBPUSD_TREND_V3_S",
})

_LOG_PATH = Path("/opt/tradingbot/logs/range_gate.jsonl")

# BB(20,2) — matches signal_logger._bb_width_pips and the BB period
# already used by EMA_PULLBACK's squeeze rule.
_BB_PERIOD = 20
_BB_STD = 2.0


def _env_bool(name: str, default: str) -> bool:
    return (os.getenv(name, default) or default).strip().lower() in (
        "1", "true", "yes", "on",
    )


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default)) or default))
    except (TypeError, ValueError):
        return int(default)


def _compute_er(bars: Sequence[Any], n: int) -> Optional[float]:
    """Kaufman efficiency ratio over the last n closes of `bars`.

    Reuses gbpusd_trend_v3._kaufman_er — one ER implementation for the
    fleet, same lazy-import pattern the stretch brake uses. Returns None
    on infra failure / not enough bars; caller treats None as FAIL-OPEN.
    """
    try:
        from gbpusd_trend_v3 import _kaufman_er
    except Exception as exc:
        logger.warning("[%s] _kaufman_er import raised: %s", LOG_TAG, exc)
        return None
    try:
        if not bars or len(bars) < n + 1:
            return None
        closes = [float(b.close) for b in bars[-(n + 1):]]
        return _kaufman_er(closes, n)
    except Exception as exc:
        logger.warning("[%s] _kaufman_er compute raised: %s", LOG_TAG, exc)
        return None


def _bb_width_pips(
    bars: Sequence[Any],
    pip_size: float,
    period: int = _BB_PERIOD,
    std_mult: float = _BB_STD,
) -> Optional[float]:
    """Bollinger Band(period, std_mult) width in pips from bars[-period:] closes.

    Mirrors signal_logger._bb_width_pips (BB(20,2)) and the BB period
    EMA_PULLBACK uses for its squeeze rule. Returns None on missing /
    short / non-finite data — caller treats None as FAIL-OPEN.
    """
    try:
        if not bars or len(bars) < period:
            return None
        closes = [float(b.close) for b in bars[-period:]]
        if len(closes) < period or any(not math.isfinite(c) for c in closes):
            return None
        mean = sum(closes) / float(period)
        var = sum((c - mean) ** 2 for c in closes) / float(period)
        stdev = math.sqrt(var)
        upper = mean + std_mult * stdev
        lower = mean - std_mult * stdev
        if not (math.isfinite(upper) and math.isfinite(lower)):
            return None
        if pip_size <= 0:
            return None
        return round((upper - lower) / float(pip_size), 2)
    except Exception as exc:
        logger.warning("[%s] bb_width compute raised: %s", LOG_TAG, exc)
        return None


def _write_log_row(row: Dict[str, Any]) -> None:
    """Append one JSON line to logs/range_gate.jsonl. Never raises."""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as exc:
        logger.warning("[%s] log write raised: %s", LOG_TAG, exc)


def evaluate(
    *,
    strategy: str,
    mode: str,
    direction: str,
    bars: Sequence[Any],
    last_price: float,
    pip_size: float,
    symbol: str = "GBPUSD",
    ts_utc: Optional[datetime] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Range-gate evaluation.

    Returns (block, reason, record). When block=True the caller must
    suppress the fire (return None from evaluate). When block=False the
    record is still useful for callsite telemetry (debug bag).

    Range detected iff BOTH:
        bb_w_pips ≥ RANGE_GATE_BBW_MIN   (wide bands)
        ER(N)     ≤ RANGE_GATE_ER_MAX    (low efficiency)

    Direction-agnostic suppression for modes in ALLOWED_MODES.
    """
    if ts_utc is None:
        ts_utc = datetime.now(timezone.utc)
    elif ts_utc.tzinfo is None:
        ts_utc = ts_utc.replace(tzinfo=timezone.utc)
    else:
        ts_utc = ts_utc.astimezone(timezone.utc)

    rec: Dict[str, Any] = {
        "ts_utc": ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategy": strategy,
        "mode": mode,
        "direction": direction,
        "symbol": str(symbol).upper(),
        "price": float(last_price) if last_price is not None else None,
        "bb_w_pips": None,
        "bb_period": _BB_PERIOD,
        "bb_std": _BB_STD,
        "er": None,
        "er_bars": None,
        "bbw_min": None,
        "er_max": None,
        "verdict": "ALLOW",
        "reason": "",
        "gate_enabled": None,
    }

    # Master flag (read at call time).
    gate_enabled = _env_bool("RANGE_GATE_ENABLED", "1")
    rec["gate_enabled"] = bool(gate_enabled)
    if not gate_enabled:
        rec["reason"] = "gate_disabled"
        return False, "", rec

    # Mode allowlist — fade strategies (BB_BOUNCE, CONFIRMATION_FALLBACK,
    # BB_REV_PAT, etc.) are NOT in this set and silently pass through.
    if mode not in ALLOWED_MODES:
        rec["reason"] = "out_of_scope_mode"
        return False, "", rec

    # Thresholds (read at call time so they're flippable mid-session).
    bbw_min = _env_float("RANGE_GATE_BBW_MIN", 15.0)
    er_max = _env_float("RANGE_GATE_ER_MAX", 0.35)
    er_bars = _env_int("RANGE_GATE_ER_BARS", 10)
    rec["bbw_min"] = bbw_min
    rec["er_max"] = er_max
    rec["er_bars"] = er_bars

    # bb_w(20,2) in pips. Wide-band precondition.
    bb_w = _bb_width_pips(bars, pip_size)
    rec["bb_w_pips"] = bb_w
    if bb_w is None:
        rec["reason"] = "bb_width_unavailable"
        return False, "", rec

    # Kaufman ER — low-efficiency precondition.
    er = _compute_er(bars, er_bars)
    rec["er"] = er
    if er is None:
        rec["reason"] = "er_unavailable"
        return False, "", rec

    wide_bands = bb_w >= float(bbw_min)
    low_er = er <= float(er_max)

    if wide_bands and low_er:
        rec["verdict"] = "SUPPRESS"
        rec["reason"] = (
            f"ranging bb_w={bb_w:.2f}p>={bbw_min:.2f}p AND "
            f"ER({er_bars})={er:.3f}<={er_max:.2f} "
            f"(wide bands + low ER, trend fire suppressed)"
        )
        _emit_suppress(rec)
        return True, rec["reason"], rec

    if not wide_bands:
        rec["reason"] = (
            f"not_range bb_w={bb_w:.2f}p<{bbw_min:.2f}p "
            f"(tight bands — chop or trend, not range)"
        )
    else:
        rec["reason"] = (
            f"not_range ER({er_bars})={er:.3f}>{er_max:.2f} "
            f"(efficient — trend, not range)"
        )
    return False, "", rec


def _emit_suppress(rec: Dict[str, Any]) -> None:
    """Greppable single-line suppress log + JSONL row. Never raises."""
    try:
        logger.info(
            "[%s] SUPPRESS — %s %s @ bb_w=%.2fp ER(%s)=%.3f<=%.2f "
            "(ranging: wide bands + low ER, trend fire suppressed) "
            "bbw_min=%.2fp price=%s",
            LOG_TAG, rec.get("strategy"), rec.get("direction"),
            float(rec.get("bb_w_pips") or 0.0),
            rec.get("er_bars"), float(rec.get("er") or 0.0),
            float(rec.get("er_max") or 0.0),
            float(rec.get("bbw_min") or 0.0),
            rec.get("price"),
        )
    except Exception:
        # Logging itself failing must never interfere with the gate's
        # block decision.
        pass
    _write_log_row(rec)


__all__ = ["evaluate", "ALLOWED_MODES"]
