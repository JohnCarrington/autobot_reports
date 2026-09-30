"""
guards/trend_stretch_brake.py — direction-aware VWAP-stretch EXHAUSTION BRAKE
for CONTINUATION strategies (STRUCTURE_BREAK, EMA_PULLBACK).

Why this exists
================
2026-06-30 daily review: 3 of 4 losers were continuation shorts sold ≥13p
below VWAP into the day's V-bottom (L2 SB_S vwap_dist=-13.73p pnl=-10.90p,
L3 SB_S -21.29p pnl=-11.65p, L4 EMA_PB_S -15.53p pnl=-15.80p). A
direction-aware stretch brake catches the V-bottom shorts while sparing
every winner — IF the carve-out is right. The carve-out is the whole point.

Gate (2026-06-30 swap: ER replaces CHOP-regime)
===============================================
The original brake gated on `regime == CHOP` (laggy proxy from
regime_classifier_v2). 2026-06-30 audit showed Kaufman ER computed at
fire time separates today's brake-relevant fires better and on the actual
SNAP-BACK signature:

    L2 (08:40 SB_S, -13.73p VWAP)  ER(10) = 0.699  LOST  → ER ≤ 0.70 BLOCK
    L3 (12:25 SB_S, -21.29p)       ER(10) = 0.012  LOST  → ER ≤ 0.70 BLOCK
    L4 (12:25 EMA_PB_S, -15.53p)   ER(10) = 0.012  LOST  → ER ≤ 0.70 BLOCK
    14:55 SB_L (+28.04p VWAP)      ER(10) = 0.885  WON   → ER > 0.70 SPARED

LOW ER = price thrashing, no net progress → snap-back likely → BRAKE FIRES.
HIGH ER = price moving efficiently → real trend → BRAKE STAYS OUT.

Because the V-pump that produced the 14:55 SB_L winner was high-ER, the
ER gate spares it automatically — the previous "long-side-OFF" hack
(TREND_STRETCH_LONG_ENABLED=0) is no longer needed. The brake now runs
SYMMETRIC on both sides.

The gate has NO dependency on regime_engine. ER comes from
gbpusd_trend_v3._kaufman_er (the same Kaufman implementation TREND_V3
already uses live — one ER implementation per fleet, lazy-imported the
same way SB reuses gbpusd_trend_v3.prior_daily_direction).

Scope (mode-allowlist)
======================
Applies ONLY to:
    GBPUSD_STRUCTURE_BREAK_L / GBPUSD_STRUCTURE_BREAK_S
    GBPUSD_EMA_PULLBACK_L    / GBPUSD_EMA_PULLBACK_S

EXEMPT — never touched (these strategies FADE stretch by design and
provably won on 2026-06-30 with-stretch fires; not in the allowlist):
    GBPUSD_BB_BOUNCE_L / S
    GBPUSD_CONFIRMATION_FALLBACK_L / S
    BB_REV_PAT / any other fade / mean-reversion strategy.

Rule (direction-matched, symmetric)
===================================
SHORT side:
    BLOCK when vwap_distance_pips ≤ -TREND_STRETCH_SHORT_PIPS
              AND ER(ER_BARS) ≤ TREND_STRETCH_ER_MAX.
LONG side:
    BLOCK when vwap_distance_pips ≥ +TREND_STRETCH_LONG_PIPS
              AND ER(ER_BARS) ≤ TREND_STRETCH_ER_MAX.

Direction-matched ALWAYS: only blocks stretch IN the fire direction.
A continuation fire AGAINST the stretch is never blocked.

Env (read at call time — flippable without restart)
====================================================
TREND_STRETCH_BRAKE_ENABLED    "1"     master on/off
TREND_STRETCH_ER_MAX           "0.70"  block iff ER ≤ this
TREND_STRETCH_ER_BARS          "10"    Kaufman ER lookback (closes)
TREND_STRETCH_SHORT_PIPS       "15"    short threshold (positive number;
                                       compared against -value)
TREND_STRETCH_LONG_PIPS        "15"    long threshold (symmetric default)
TREND_STRETCH_LONG_ENABLED     "1"     long-side kill-switch override.
                                       The ER gate spares efficient longs
                                       automatically; set to "0" only as
                                       a manual kill-switch for the long
                                       side.
TREND_STRETCH_BRAKE_ADX_FLOOR  "25.0"  ADX floor for the snap-back rule
                                       (2026-07-22). When the ER+VWAP
                                       block condition holds, the brake
                                       only BLOCKS if ADX < floor. When
                                       ADX >= floor the move is genuinely
                                       directional and the snap-back
                                       assumption fails — brake PASSES.
                                       If ADX is not supplied (None), the
                                       brake fails safe by BLOCKING as
                                       before. Symmetric to short + long.

TREND_STRETCH_BRAKE_ADX_MAX_STALE_BARS "1"  Staleness tolerance for the
                                       sourced ADX (2026-07-22). Read by
                                       the DRIVER (each strategy's
                                       evaluate() sources ADX from
                                       regime_engine.latest_result and
                                       reads this env at sourcing time).
                                       If the regime result's own
                                       "timestamp" is older than the
                                       driver's current bar by more than
                                       this many 5m bars, the driver
                                       drops the sourced value to None
                                       and marks adx_source as
                                       "stale_failsafe" so the brake
                                       still fails safe (BLOCK) but the
                                       reason is distinguishable in
                                       telemetry from a genuinely
                                       missing ADX.

Stacking
========
ADDITIVE to all other gates (SB daily-filter, transition filter, velocity
gate, conviction gate, slot enforcement). Any gate can block independently;
this one only adds new blocks for the low-ER stretched continuation pattern.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

logger = logging.getLogger("trend_stretch_brake")

# Greppable tag — matches the format the user asked for:
#     [STRETCH_BRAKE] BLOCK — {strategy} {dir} @ vwap_dist={x}p ER={er} ...
LOG_TAG = "STRETCH_BRAKE"

# Mode allowlist — CONTINUATION ONLY. Fade strategies are NOT in this set
# and therefore physically cannot be caught by this brake. The allowlist
# is the safety mechanism: if a caller passes a fade-strategy mode, the
# brake returns None unconditionally.
ALLOWED_MODES = frozenset({
    "GBPUSD_STRUCTURE_BREAK_L",
    "GBPUSD_STRUCTURE_BREAK_S",
    "GBPUSD_EMA_PULLBACK_L",
    "GBPUSD_EMA_PULLBACK_S",
})

_LOG_PATH = Path("/opt/tradingbot/logs/trend_stretch_brake.jsonl")


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
    fleet, same lazy-import pattern SB already uses for
    gbpusd_trend_v3.prior_daily_direction. Returns None on infra failure
    / not enough bars; caller treats None as FAIL-OPEN.
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


def _today_vwap_distance_pips(
    bars: Sequence[Any],
    last_price: float,
    pip_size: float,
    now_utc: datetime,
) -> Optional[float]:
    """Distance from today's session-VWAP in pips (+ = price above VWAP).

    Mirrors signal_logger._vwap_distance_pips for the no-volume case
    (Bar dataclasses don't carry volume; candle_builder.get_df_raw
    columns are [time, open, high, low, close]). VWAP = mean of typical
    price (H+L+C)/3 across all of today's UTC-date closed bars. Same
    fallback path signal_logger uses — so the brake's vwap_dist is
    directly comparable to signal_log rows.
    """
    if not bars:
        return None
    try:
        today = now_utc.astimezone(timezone.utc).date()
        typicals = []
        for b in bars:
            ts = getattr(b, "timestamp", None)
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts.astimezone(timezone.utc).date() != today:
                continue
            h = float(b.high); l = float(b.low); c = float(b.close)
            typicals.append((h + l + c) / 3.0)
        if not typicals:
            return None
        vwap = sum(typicals) / float(len(typicals))
        return round((float(last_price) - vwap) / float(pip_size), 2)
    except Exception as exc:
        logger.warning("[%s] vwap compute raised: %s", LOG_TAG, exc)
        return None


def _write_log_row(row: Dict[str, Any]) -> None:
    """Append one JSON line to logs/trend_stretch_brake.jsonl. Never raises."""
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
    adx_at_decision: Optional[float] = None,
    adx_source: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Direction-aware VWAP-stretch brake.

    Returns (block, reason, record). When block=True the caller must
    suppress the fire (return None from evaluate). When block=False the
    record is still useful for callsite telemetry (debug bag).

    Fail-open everywhere: missing ER / unavailable VWAP / out-of-scope
    mode all return block=False. The brake adds NEW blocks for one
    specific pattern (low-ER stretched continuation); it never blocks
    anything the existing pipeline already would have fired.
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
        "vwap_distance_pips": None,
        "er": None,
        "er_bars": None,
        "er_max": None,
        "verdict": "ALLOW",
        "reason": "",
        "threshold_hit": None,
        "short_threshold_pips": None,
        "long_threshold_pips": None,
        "long_side_enabled": None,
        "brake_enabled": None,
        # ADX floor (2026-07-22). Populated on every BLOCK/PASS decision
        # taken by the ER+VWAP rule below. Fields stay None when the
        # rule wasn't reached (e.g. out-of-scope mode, brake disabled).
        "adx_at_decision": (float(adx_at_decision)
                            if adx_at_decision is not None else None),
        "adx_floor": None,
        "adx_source": (str(adx_source) if adx_source else None),
        "adx_gate_verdict": None,
    }

    # Master flag (read at call time).
    brake_enabled = _env_bool("TREND_STRETCH_BRAKE_ENABLED", "1")
    rec["brake_enabled"] = bool(brake_enabled)
    if not brake_enabled:
        rec["reason"] = "brake_disabled"
        return False, "", rec

    # Mode allowlist — fade strategies (BB_BOUNCE, CONFIRMATION_FALLBACK,
    # BB_REV_PAT, etc.) are NOT in this set and silently pass through.
    if mode not in ALLOWED_MODES:
        rec["reason"] = "out_of_scope_mode"
        return False, "", rec

    # Thresholds (read at call time so they're flippable mid-session).
    er_max = _env_float("TREND_STRETCH_ER_MAX", 0.70)
    er_bars = _env_int("TREND_STRETCH_ER_BARS", 10)
    short_thr = _env_float("TREND_STRETCH_SHORT_PIPS", 15.0)
    long_thr = _env_float("TREND_STRETCH_LONG_PIPS", 15.0)
    long_side_enabled = _env_bool("TREND_STRETCH_LONG_ENABLED", "1")
    adx_floor = _env_float("TREND_STRETCH_BRAKE_ADX_FLOOR", 25.0)
    rec["er_max"] = er_max
    rec["er_bars"] = er_bars
    rec["short_threshold_pips"] = short_thr
    rec["long_threshold_pips"] = long_thr
    rec["long_side_enabled"] = bool(long_side_enabled)
    rec["adx_floor"] = adx_floor

    # VWAP distance — the stretch precondition. Computed FIRST because if
    # the fire isn't stretched in the fire direction, neither gate matters
    # and we save the ER compute.
    vwap_dist = _today_vwap_distance_pips(bars, last_price, pip_size, ts_utc)
    rec["vwap_distance_pips"] = vwap_dist
    if vwap_dist is None:
        rec["reason"] = "vwap_unavailable"
        return False, "", rec

    # Kaufman ER — the snap-back-likelihood gate. Low ER = thrash
    # (snap-back likely → block). High ER = efficient (trend → spare).
    er = _compute_er(bars, er_bars)
    rec["er"] = er
    if er is None:
        rec["reason"] = "er_unavailable"
        return False, "", rec

    direction_u = str(direction).upper()

    # SHORT side — direction-matched: only blocks a short when price is
    # stretched DOWN (vwap_dist <= -short_thr) AND ER is low (thrash).
    if direction_u == "SHORT":
        if vwap_dist <= -float(short_thr) and er <= float(er_max):
            # ER+VWAP rule fired. ADX floor decides block vs pass
            # (2026-07-22). None ADX → fail safe (BLOCK as before).
            gate_verdict, gate_block = _apply_adx_floor(
                adx_at_decision, adx_floor
            )
            rec["adx_gate_verdict"] = gate_verdict
            rec["threshold_hit"] = "short"
            if gate_block:
                rec["verdict"] = "BLOCK"
                rec["reason"] = (
                    f"short_stretched_down_lowER vwap_dist={vwap_dist:+.2f}p "
                    f"<= -{short_thr:.2f}p AND ER({er_bars})={er:.3f} <= {er_max:.2f} "
                    f"(thrash-stretch, snapback-likely) "
                    f"[adx_gate={gate_verdict} adx={_fmt_adx(adx_at_decision)} "
                    f"floor={adx_floor:.2f}]"
                )
                _emit_block(rec)
                return True, rec["reason"], rec
            # ADX high — spare the fire.
            rec["reason"] = (
                f"short_stretched_lowER_but_high_adx vwap_dist={vwap_dist:+.2f}p "
                f"ER({er_bars})={er:.3f} adx={_fmt_adx(adx_at_decision)} "
                f">= floor={adx_floor:.2f} (trend, snapback unlikely)"
            )
            _emit_allow(rec)
            return False, "", rec
        # Not blocked (ER+VWAP rule did not fire) — explain why for telemetry.
        if vwap_dist > -float(short_thr):
            rec["reason"] = (
                f"short_not_stretched vwap_dist={vwap_dist:+.2f}p > -{short_thr:.2f}p"
            )
        else:
            rec["reason"] = (
                f"short_stretched_but_efficient ER({er_bars})={er:.3f} > {er_max:.2f}"
            )
        return False, "", rec

    # LONG side — direction-matched: only blocks a long when price is
    # stretched UP (vwap_dist >= +long_thr) AND ER is low (thrash).
    # The kill-switch override defaults ON; flip TREND_STRETCH_LONG_ENABLED=0
    # to disable the long side entirely without disabling the brake.
    if direction_u == "LONG":
        if not long_side_enabled:
            rec["reason"] = "long_side_killswitch_off"
            return False, "", rec
        if vwap_dist >= float(long_thr) and er <= float(er_max):
            # ER+VWAP rule fired. Same ADX floor as SHORT (2026-07-22).
            gate_verdict, gate_block = _apply_adx_floor(
                adx_at_decision, adx_floor
            )
            rec["adx_gate_verdict"] = gate_verdict
            rec["threshold_hit"] = "long"
            if gate_block:
                rec["verdict"] = "BLOCK"
                rec["reason"] = (
                    f"long_stretched_up_lowER vwap_dist={vwap_dist:+.2f}p "
                    f">= +{long_thr:.2f}p AND ER({er_bars})={er:.3f} <= {er_max:.2f} "
                    f"(thrash-stretch, snapback-likely) "
                    f"[adx_gate={gate_verdict} adx={_fmt_adx(adx_at_decision)} "
                    f"floor={adx_floor:.2f}]"
                )
                _emit_block(rec)
                return True, rec["reason"], rec
            rec["reason"] = (
                f"long_stretched_lowER_but_high_adx vwap_dist={vwap_dist:+.2f}p "
                f"ER({er_bars})={er:.3f} adx={_fmt_adx(adx_at_decision)} "
                f">= floor={adx_floor:.2f} (trend, snapback unlikely)"
            )
            _emit_allow(rec)
            return False, "", rec
        if vwap_dist < float(long_thr):
            rec["reason"] = (
                f"long_not_stretched vwap_dist={vwap_dist:+.2f}p < +{long_thr:.2f}p"
            )
        else:
            rec["reason"] = (
                f"long_stretched_but_efficient ER({er_bars})={er:.3f} > {er_max:.2f}"
            )
        return False, "", rec

    rec["reason"] = f"unknown_direction:{direction}"
    return False, "", rec


def _apply_adx_floor(
    adx: Optional[float], floor: float,
) -> Tuple[str, bool]:
    """Return (adx_gate_verdict, block_flag) for the ADX floor gate.

    Called only from inside the ER+VWAP block branches (SHORT / LONG).
    Fail-safe: adx=None → block as before (this is the corpus we've been
    catching all along; a missing scalar must never silently open the
    gate). adx>=floor → pass (genuine trend, snap-back unlikely).
    adx<floor → block (thrashy stretch — original brake target).
    """
    if adx is None:
        return "blocked_adx_unavailable_failsafe", True
    try:
        adx_f = float(adx)
    except (TypeError, ValueError):
        return "blocked_adx_unavailable_failsafe", True
    if adx_f >= float(floor):
        return "passed_high_adx", False
    return "blocked_low_adx", True


def _fmt_adx(adx: Optional[float]) -> str:
    """Compact adx formatter used in reason strings."""
    if adx is None:
        return "null"
    try:
        return f"{float(adx):.2f}"
    except (TypeError, ValueError):
        return "null"


def _emit_block(rec: Dict[str, Any]) -> None:
    """Greppable single-line block log + JSONL row. Never raises."""
    try:
        logger.info(
            "[%s] BLOCK — %s %s @ vwap_dist=%+.2fp ER(%s)=%.3f<=%.2f "
            "(thrash-stretch, snapback-likely) thr_hit=%s "
            "adx_gate=%s adx=%s floor=%s",
            LOG_TAG, rec.get("strategy"), rec.get("direction"),
            float(rec.get("vwap_distance_pips") or 0.0),
            rec.get("er_bars"), float(rec.get("er") or 0.0),
            float(rec.get("er_max") or 0.0), rec.get("threshold_hit"),
            rec.get("adx_gate_verdict"),
            _fmt_adx(rec.get("adx_at_decision")),
            rec.get("adx_floor"),
        )
    except Exception:
        # Logging itself failing must never interfere with the brake's
        # block decision.
        pass
    _write_log_row(rec)


def _emit_allow(rec: Dict[str, Any]) -> None:
    """Greppable single-line ALLOW log + JSONL row for the ADX-floor pass
    path (2026-07-22). Only fires when the ER+VWAP rule matched but the
    ADX floor spared the fire — that's the interesting case we want in
    the corpus for validation. Non-matching passes (not stretched, or
    stretched-but-efficient) continue to skip the jsonl to keep it lean.
    """
    try:
        logger.info(
            "[%s] PASS — %s %s @ vwap_dist=%+.2fp ER(%s)=%.3f<=%.2f "
            "(ADX floor spared) thr_hit=%s "
            "adx_gate=%s adx=%s floor=%s",
            LOG_TAG, rec.get("strategy"), rec.get("direction"),
            float(rec.get("vwap_distance_pips") or 0.0),
            rec.get("er_bars"), float(rec.get("er") or 0.0),
            float(rec.get("er_max") or 0.0), rec.get("threshold_hit"),
            rec.get("adx_gate_verdict"),
            _fmt_adx(rec.get("adx_at_decision")),
            rec.get("adx_floor"),
        )
    except Exception:
        pass
    _write_log_row(rec)


__all__ = ["evaluate", "ALLOWED_MODES"]
