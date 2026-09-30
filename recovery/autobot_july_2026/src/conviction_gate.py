"""conviction_gate.py — pre-fire conviction gating, called from trade_executor.execute_trade.

Five toggleable sub-gates, each with its own env var. All fail-open: if the
required signal is unavailable, the gate passes (never block on missing data).

Sub-gates:
  1. ADX trending threshold        (CONVICTION_ADX_GATE_ENABLED=1, CONVICTION_ADX_MIN=20)
  2. DI alignment                  (CONVICTION_DI_GATE_ENABLED=1)
  3. Regime confidence threshold   (CONVICTION_CONF_GATE_ENABLED=1, CONVICTION_CONF_MIN=0.50)
  4. EMA_state strictness          (CONVICTION_EMA_GATE_ENABLED=1)
       For trend strategies, EMA_state must be BULL_ALIGNED (LONG) or BEAR_ALIGNED (SHORT) —
       MIXED is rejected. Pure mean-reversion strategies bypass via TREND_FOLLOWING_MODES.
  5. Confirmation sub-score        (CONVICTION_CONF_SCORE_GATE_ENABLED=0 default — see note)
       Reads sub_score_at_entry from the most recent confirmation_engine.jsonl entry.
       Default OFF: confirmation engine fires post-entry, so synchronous reads are racy.

Master switch: CONVICTION_GATE_ENABLED=1 (default ON; set to 0 to disable all sub-gates).

Returns: (passed: bool, reason: str, details: dict)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger("AutoBot")

# ─────────────────────────────────────────────────────────────
# Configuration (env-driven, evaluated at gate-call time so .env edits
# take effect without restarting; safe because the cost is one os.getenv
# per fire which is negligible vs the rest of execute_trade).
# ─────────────────────────────────────────────────────────────
def _env_bool(name: str, default: str = "1") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default

def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


TREND_GUARD_SHADOW_PATH = os.getenv(
    "TREND_GUARD_SHADOW_LOG_PATH", "/opt/tradingbot/logs/trend_guard_shadow.jsonl"
)


def _load_recent_adx(symbol: str, want: int) -> list:
    """Tail regime_engine.jsonl and return up to `want` recent ADX values for
    `symbol`, MOST-RECENT FIRST. Returns [] on any failure — caller treats as
    "history unavailable, do not override" (fail-closed for the override; the
    block still applies on level alone). Safe against partial trailing line and
    interleaved symbols (GBPUSD/EURUSD).
    """
    path = "/opt/tradingbot/logs/regime_engine.jsonl"
    try:
        if not os.path.exists(path):
            return []
        size = os.path.getsize(path)
        # 64KB tail covers ~25-50 rows per symbol — well above any sane lookback.
        read_bytes = min(size, 65536)
        with open(path, "rb") as f:
            f.seek(size - read_bytes)
            tail = f.read().decode("utf-8", errors="ignore")
        sym_u = str(symbol).upper()
        out: list = []
        for line in reversed(tail.splitlines()):
            ln = line.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:
                continue
            if str(d.get("symbol") or "").upper() != sym_u:
                continue
            adx = d.get("ADX")
            if adx is None:
                continue
            try:
                out.append(float(adx))
            except (TypeError, ValueError):
                continue
            if len(out) >= want:
                break
        return out
    except Exception:
        return []


def _slope_override(adx_now: Optional[float], prior_adxs: list,
                    lookback: int, slope_delta: float):
    """Return (override_block: bool, adx_lookback: Optional[float], slope: Optional[float]).

    override_block=True when ADX has FALLEN by at least slope_delta over the
    last `lookback` bars — i.e. the trend is rolling over, so the fade should
    be allowed despite the high level. prior_adxs[0] should be the CURRENT bar
    (we double-check it matches adx_now, but the comparator uses prior_adxs[lookback]).
    """
    if adx_now is None or lookback < 1 or not prior_adxs:
        return False, None, None
    if len(prior_adxs) <= lookback:
        return False, None, None
    adx_lookback = prior_adxs[lookback]
    slope = adx_now - adx_lookback
    return (slope < -slope_delta), adx_lookback, slope


def _write_trend_guard_shadow(rec: Dict[str, object]) -> None:
    """Append one JSONL row to TREND_GUARD_SHADOW_PATH. Swallowing writer —
    telemetry-only, must never raise back into the guard path."""
    try:
        d = os.path.dirname(TREND_GUARD_SHADOW_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(TREND_GUARD_SHADOW_PATH, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[conviction_gate] trend_guard_shadow write failed: %s", exc)

# Modes for which trend-following filters apply. Pure mean-reversion modes
# (e.g. BB-pierce reversals) are filtered separately or bypass entirely.
TREND_FOLLOWING_MODES = {
    "GBPUSD_TREND_L", "GBPUSD_TREND_S",
    "GBPUSD_EMA_PULLBACK_L", "GBPUSD_EMA_PULLBACK_S",
}

# Modes that are reversal/mean-reversion — EMA_STATE gate should NOT
# require BULL/BEAR_ALIGNED because reversal trades by definition
# fight the prevailing trend. Still subject to ADX/DI/confidence gates.
REVERSAL_MODES = {
    "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
    "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S",
    "GBPUSD_RAW_REVERSAL_L", "GBPUSD_RAW_REVERSAL_S",
    "BB_REVERSAL",
}

# Per-mode exemption set for REV_TREND_GUARD. Listed modes remain in
# REVERSAL_MODES (so EMA_state bypass still applies), but the reversal-
# trend guard returns pass-through for them — the level/slope verdict
# is still computed and written to trend_guard_shadow.jsonl with
# exempt=true so the forensic record of what WOULD have blocked is
# preserved. Default: BB_BOUNCE freed (Johnny's directive 2026-06-25).
def _rev_trend_guard_exempt_modes() -> set:
    raw = os.getenv(
        "REV_TREND_GUARD_EXEMPT_MODES",
        "GBPUSD_BB_BOUNCE_L,GBPUSD_BB_BOUNCE_S",
    )
    return {m.strip().upper() for m in raw.split(",") if m.strip()}


def _pair_from_mode(mode: str) -> Optional[str]:
    """Extract pair from strategy mode (e.g. 'GBPUSD_BB_BOUNCE_S' → 'GBPUSD')."""
    if not mode:
        return None
    parts = mode.split("_")
    if parts and len(parts[0]) == 6 and parts[0].isalpha():
        return parts[0].upper()
    return None


def _load_latest_confirmation(symbol: str, max_age_secs: float = 120.0) -> Optional[dict]:
    """Tail confirmation_engine.jsonl for the most recent entry for `symbol`.

    Returns None if no entry within max_age_secs (i.e. the confirmation engine
    hasn't scored anything recently — fail-open). Reading tail is acceptable
    here; the file is small (<10MB typical) and JSONL parsing is cheap. We do
    this synchronously because the confirmation engine writes from a separate
    5m-close callback path; reading the persisted state is the cleanest cross-
    process handoff."""
    path = "/opt/tradingbot/logs/confirmation_engine.jsonl"
    try:
        if not os.path.exists(path):
            return None
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            # Read last 16KB which should contain plenty of recent entries
            f.seek(max(0, size - 16384))
            tail = f.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        # Walk backwards to find the latest entry for `symbol`
        sym_u = str(symbol).upper()
        now = datetime.now(timezone.utc)
        for line in reversed(lines):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if str(d.get("pair", "")).upper() != sym_u:
                continue
            ts_raw = d.get("ts_utc") or d.get("timestamp")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            age = (now - ts).total_seconds()
            if age > max_age_secs:
                return None  # too stale to count
            return d
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Sub-gate implementations
# ─────────────────────────────────────────────────────────────
def _gate_adx(regime: dict) -> Tuple[bool, str, dict]:
    enabled = _env_bool("CONVICTION_ADX_GATE_ENABLED", "1")
    threshold = _env_float("CONVICTION_ADX_MIN", 20.0)
    if not enabled:
        return True, "ADX_gate_disabled", {"enabled": False}
    adx = regime.get("ADX")
    if adx is None:
        return True, "ADX_unavailable_fail_open", {"adx": None, "threshold": threshold}
    try:
        adx_f = float(adx)
    except (TypeError, ValueError):
        return True, "ADX_unparseable_fail_open", {"adx": adx, "threshold": threshold}
    passed = adx_f >= threshold
    return passed, ("ADX_pass" if passed else f"ADX_below_threshold:{adx_f:.1f}<{threshold:.1f}"), {
        "adx": adx_f, "threshold": threshold,
    }


def _gate_di_alignment(regime: dict, direction: str) -> Tuple[bool, str, dict]:
    """For SHORT: require −DI > +DI. For LONG: require +DI > −DI.
    Captures the DMI internals contradicting the EMA-based direction.

    NOTE: Default OFF — replay 2026-05-29 (16-trade sample, 7-day window)
    showed this gate is net-negative: it blocked 7 winners vs 3 losers
    (−44.8p net). Re-evaluate once we have ≥3 months of regime coverage."""
    enabled = _env_bool("CONVICTION_DI_GATE_ENABLED", "0")
    if not enabled:
        return True, "DI_gate_disabled", {"enabled": False}
    plus_di = regime.get("plus_di")
    minus_di = regime.get("minus_di")
    if plus_di is None or minus_di is None:
        return True, "DI_unavailable_fail_open", {"plus_di": plus_di, "minus_di": minus_di}
    try:
        p = float(plus_di); m = float(minus_di)
    except (TypeError, ValueError):
        return True, "DI_unparseable_fail_open", {"plus_di": plus_di, "minus_di": minus_di}
    direction_u = str(direction).upper()
    if direction_u in ("BUY", "LONG", "L"):
        passed = p > m
        reason = ("DI_pass:+DI>-DI" if passed else f"DI_misaligned_for_LONG:+{p:.1f}<-{m:.1f}")
    elif direction_u in ("SELL", "SHORT", "S"):
        passed = m > p
        reason = ("DI_pass:-DI>+DI" if passed else f"DI_misaligned_for_SHORT:-{m:.1f}<+{p:.1f}")
    else:
        return True, "DI_unknown_direction_fail_open", {"direction": direction}
    return passed, reason, {"plus_di": p, "minus_di": m, "direction": direction_u}


def _gate_confidence(regime: dict) -> Tuple[bool, str, dict]:
    """NOTE: Default OFF — replay 2026-05-29 (16-trade sample) showed net
    −8.1p (only 2 trades blocked, 1 win, 1 loss; the blocked winner was
    larger than the blocked loser). Re-evaluate on more data."""
    enabled = _env_bool("CONVICTION_CONF_GATE_ENABLED", "0")
    threshold = _env_float("CONVICTION_CONF_MIN", 0.50)
    if not enabled:
        return True, "conf_gate_disabled", {"enabled": False}
    conf = regime.get("confidence_final")
    if conf is None:
        return True, "conf_unavailable_fail_open", {"conf": None, "threshold": threshold}
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return True, "conf_unparseable_fail_open", {"conf": conf, "threshold": threshold}
    passed = c >= threshold
    return passed, ("conf_pass" if passed else f"conf_below_threshold:{c:.2f}<{threshold:.2f}"), {
        "conf": c, "threshold": threshold,
    }


def _gate_reversal_trend(regime: dict, mode: str, direction: str) -> Tuple[bool, str, dict]:
    """Directional guard for REVERSAL_MODES — block fades against a strong
    aligned trend.

    Scope: applies ONLY to modes in REVERSAL_MODES (BB_BOUNCE_L/_S, BB_REV_PAT
    _L/_S, RAW_REVERSAL_L/_S, BB_REVERSAL). Trend-following / unknown modes
    pass through unchanged.

    Block rule (only fires when ALL three conditions hold):
        LONG  blocked iff winning_regime == STRONG_TREND_DOWN
                          AND ADX >= ADX_MIN (default 25)
                          AND EMA_state    == BEAR_ALIGNED
        SHORT blocked iff winning_regime == STRONG_TREND_UP
                          AND ADX >= ADX_MIN
                          AND EMA_state    == BULL_ALIGNED

    Targeted: TREND_FORMING_*, BEAR_PARTIAL/BULL_PARTIAL/MIXED, COMPRESSION,
    RANGE_ROTATION, VOLATILITY_EXPANSION, sub-threshold ADX all PASS through.
    The premise is "don't fade a strongly-aligned trend"; mild / forming /
    rangy conditions are exactly where reversal modes earn their keep, so
    they're untouched.

    ALWAYS computes the would_block verdict and logs it at INFO regardless of
    flag state — telemetry accumulates so we can audit the gate's impact
    before / after flipping the flag. Enforcement is flag-gated:
        STRUCTURE_REVERSAL_TREND_GUARD_ENABLED   (default 0)
        STRUCTURE_REVERSAL_TREND_GUARD_ADX_MIN   (default 25.0)

    Pre-validation against signal_log (06-01 to 06-15) at the defaults:
      - 0/7 with-trend reversal fires blocked   (surgical, as required)
      - 15/30 counter-trend reversal fires blocked
      - Of 9 counter-trend GBPUSD LONGs: 6 blocked (incl. the 06-05 TP1
        winner — a real cost the user has acknowledged), 3 slipped because
        their regime was TREND_FORMING_DOWN / VOLATILITY_EXPANSION rather
        than STRONG_TREND_DOWN, by spec."""
    enabled = _env_bool("STRUCTURE_REVERSAL_TREND_GUARD_ENABLED", "0")
    adx_min = _env_float("STRUCTURE_REVERSAL_TREND_GUARD_ADX_MIN", 25.0)
    mode_u = str(mode).upper()
    direction_u = str(direction).upper()
    is_long  = direction_u in ("BUY", "LONG", "L")
    is_short = direction_u in ("SELL", "SHORT", "S")
    is_reversal = mode_u in REVERSAL_MODES

    details: Dict[str, object] = {
        "enabled": enabled, "adx_min_threshold": adx_min,
        "mode": mode_u, "direction": direction_u, "is_reversal": is_reversal,
    }

    if not is_reversal:
        # Out of scope — pass through silently (no log noise on every fire).
        return True, "reversal_trend_guard_not_reversal_mode", details

    winning   = str(regime.get("winning_regime") or "").upper()
    ema_state = str(regime.get("EMA_state") or "").upper()
    adx_raw   = regime.get("ADX")
    try:
        adx_f = float(adx_raw) if adx_raw is not None else None
    except (TypeError, ValueError):
        adx_f = None

    details.update({"winning_regime": winning, "ema_state": ema_state, "adx": adx_f})

    would_block = False
    block_reason = ""
    adx_ok = (adx_f is not None) and (adx_f >= adx_min)
    if is_long and winning == "STRONG_TREND_DOWN" and ema_state == "BEAR_ALIGNED" and adx_ok:
        would_block = True
        block_reason = (f"reversal_trend_guard LONG_into_STRONG_TREND_DOWN "
                        f"ADX={adx_f:.1f}>={adx_min:.1f} EMA=BEAR_ALIGNED mode={mode_u}")
    elif is_short and winning == "STRONG_TREND_UP" and ema_state == "BULL_ALIGNED" and adx_ok:
        would_block = True
        block_reason = (f"reversal_trend_guard SHORT_into_STRONG_TREND_UP "
                        f"ADX={adx_f:.1f}>={adx_min:.1f} EMA=BULL_ALIGNED mode={mode_u}")

    details["would_block"] = would_block
    # Preserve the level-only verdict for shadow telemetry and reasoning.
    level_only_block = would_block
    level_only_reason = block_reason

    # Per-mode exempt list (2026-06-25). Computed early so it can be
    # stamped on telemetry; the actual pass-through return happens AFTER
    # the shadow row is written so forensic_fires / trend_guard_shadow
    # still record what WOULD have blocked under the rule.
    is_exempt = mode_u in _rev_trend_guard_exempt_modes()
    details["exempt"] = is_exempt

    # ── ADX-slope override (2026-06-16) ───────────────────────────────────
    # The level-only rule blocks even when ADX is high BECAUSE OF a leg that
    # has already topped — exactly the dying-trend case the fade wants. The
    # slope override allows the block to be vetoed when ADX has actually
    # fallen by at least SLOPE_DELTA over the last LOOKBACK bars. Gated by
    # STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED so the legacy level-only
    # behaviour is byte-identically reproducible by setting it to 0.
    slope_enabled = _env_bool("STRUCTURE_REVERSAL_TREND_GUARD_SLOPE_ENABLED", "1")
    slope_lookback = _env_int("TREND_GUARD_ADX_LOOKBACK", 1)
    slope_delta = _env_float("TREND_GUARD_ADX_SLOPE_DELTA", 0.5)
    pair = _pair_from_mode(mode) or "?"

    prior_adxs: list = []
    slope_override_fired = False
    adx_lookback_val: Optional[float] = None
    adx_slope: Optional[float] = None
    if level_only_block:
        prior_adxs = _load_recent_adx(pair, slope_lookback + 1)
        slope_override_fired, adx_lookback_val, adx_slope = _slope_override(
            adx_f, prior_adxs, slope_lookback, slope_delta
        )

    slope_block = level_only_block and not slope_override_fired
    active_block = slope_block if slope_enabled else level_only_block

    details.update({
        "level_only_block": level_only_block,
        "slope_enabled": slope_enabled,
        "slope_lookback_bars": slope_lookback,
        "slope_delta_threshold": slope_delta,
        "adx_lookback": adx_lookback_val,
        "adx_slope": adx_slope,
        "slope_override_fired": slope_override_fired,
        "slope_block": slope_block,
        "active_block": active_block,
    })

    # Always log the verdict so the gate's impact accumulates regardless of
    # flag state — mirrors the disp_confirm / transition_filter telemetry
    # pattern in gbpusd_structure_break.
    logger.info(
        "[CONVICTION] REVERSAL_TREND_GUARD %s %s %s regime=%s adx=%s "
        "adx_lb%d=%s slope=%s ema=%s level_block=%s slope_block=%s "
        "active_block=%s slope_enabled=%s flag_enabled=%s",
        pair, direction_u, mode_u,
        winning or "?",
        (f"{adx_f:.2f}" if adx_f is not None else "None"),
        slope_lookback,
        (f"{adx_lookback_val:.2f}" if adx_lookback_val is not None else "None"),
        (f"{adx_slope:+.2f}" if adx_slope is not None else "None"),
        ema_state or "?",
        level_only_block, slope_block, active_block,
        slope_enabled, enabled,
    )

    # Shadow log: always-on telemetry so old-vs-new divergence is measurable
    # regardless of which rule is active. Separate kill-switch.
    if _env_bool("TREND_GUARD_SHADOW_ENABLED", "1"):
        _write_trend_guard_shadow({
            "ts": datetime.now(timezone.utc).isoformat(),
            "pair": pair, "side": direction_u, "mode": mode_u,
            "winning_regime": winning, "ema_state": ema_state,
            "adx_now": adx_f,
            "adx_lookback": adx_lookback_val,
            "adx_lookback_bars": slope_lookback,
            "adx_slope": adx_slope,
            "slope_delta_threshold": slope_delta,
            "level_only_decision": "BLOCK" if level_only_block else "PASS",
            "slope_decision": "BLOCK" if slope_block else "PASS",
            "active_decision": "BLOCK" if active_block else "PASS",
            "final_decision": (
                "EXEMPT" if (is_exempt and active_block and enabled)
                else ("BLOCK" if (active_block and enabled) else "PASS")
            ),
            "exempt": is_exempt,
            "slope_enabled": slope_enabled,
            "guard_flag_enabled": enabled,
            "adx_min_threshold": adx_min,
        })

    # Per-mode exempt bypass: shadow telemetry already captured the
    # would-block; return PASS so the live fire isn't strangled.
    if is_exempt and enabled and active_block:
        logger.info(
            "[BB_FREED] REVERSAL_TREND_GUARD bypassed mode=%s regime=%s adx=%s "
            "level_block=%s slope_block=%s — exempt",
            mode_u, winning or "?",
            (f"{adx_f:.2f}" if adx_f is not None else "None"),
            level_only_block, slope_block,
        )
        return True, "reversal_trend_guard_mode_exempt", details

    if not enabled:
        return True, "reversal_trend_guard_disabled_log_only", details
    if active_block:
        # Preserve the original level-only reason text when slope is OFF or
        # didn't override; annotate when slope let it through (block flips OFF
        # before reaching here, so this branch never hits in that case).
        return False, level_only_reason, details
    if level_only_block and slope_override_fired and slope_enabled:
        return True, (
            f"reversal_trend_guard_slope_override "
            f"adx_now={adx_f:.2f} adx_lb{slope_lookback}={adx_lookback_val:.2f} "
            f"slope={adx_slope:+.2f}<-{slope_delta:.2f}"
        ), details
    return True, "reversal_trend_guard_pass", details


def _gate_ema_state(regime: dict, mode: str, direction: str) -> Tuple[bool, str, dict]:
    """For trend-following strategies: require EMA_state == BULL_ALIGNED (LONG)
    or BEAR_ALIGNED (SHORT). Reversal strategies bypass (they don't trade with
    EMA stack)."""
    enabled = _env_bool("CONVICTION_EMA_GATE_ENABLED", "1")
    if not enabled:
        return True, "EMA_gate_disabled", {"enabled": False}
    mode_u = str(mode).upper()
    if mode_u in REVERSAL_MODES:
        return True, "EMA_gate_bypass_reversal_mode", {"mode": mode_u}
    if mode_u not in TREND_FOLLOWING_MODES:
        # Unknown mode — fail-open to preserve existing behaviour for strategies
        # not yet classified here.
        return True, "EMA_gate_mode_not_classified_fail_open", {"mode": mode_u}
    ema_state = str(regime.get("EMA_state", "")).upper()
    if not ema_state:
        return True, "EMA_state_unavailable_fail_open", {"EMA_state": None}
    direction_u = str(direction).upper()
    if direction_u in ("BUY", "LONG", "L"):
        passed = ema_state == "BULL_ALIGNED"
        reason = ("EMA_pass:BULL_ALIGNED" if passed else f"EMA_misaligned_for_LONG:{ema_state}")
    elif direction_u in ("SELL", "SHORT", "S"):
        passed = ema_state == "BEAR_ALIGNED"
        reason = ("EMA_pass:BEAR_ALIGNED" if passed else f"EMA_misaligned_for_SHORT:{ema_state}")
    else:
        return True, "EMA_gate_unknown_direction_fail_open", {"direction": direction}
    return passed, reason, {"EMA_state": ema_state, "direction": direction_u, "mode": mode_u}


def _gate_confirmation_score(symbol: str) -> Tuple[bool, str, dict]:
    """Synchronous read of confirmation_engine.jsonl tail for sub_score_at_entry.
    Default OFF because the confirmation engine fires post-entry asynchronously;
    a synchronous gate here can be racy if the prior fire is stale."""
    enabled = _env_bool("CONVICTION_CONF_SCORE_GATE_ENABLED", "0")
    threshold = _env_float("CONVICTION_CONF_SCORE_MIN", 2.0)
    if not enabled:
        return True, "conf_score_gate_disabled", {"enabled": False}
    rec = _load_latest_confirmation(symbol, max_age_secs=120.0)
    if rec is None:
        return True, "conf_score_unavailable_fail_open", {"threshold": threshold}
    score = rec.get("sub_score_at_entry") or rec.get("composite_score")
    if score is None:
        return True, "conf_score_field_missing_fail_open", {"threshold": threshold}
    try:
        s = float(score)
    except (TypeError, ValueError):
        return True, "conf_score_unparseable_fail_open", {"score": score, "threshold": threshold}
    passed = s >= threshold
    return passed, ("conf_score_pass" if passed else f"conf_score_below:{s:.1f}<{threshold:.1f}"), {
        "score": s, "threshold": threshold,
    }


# ─────────────────────────────────────────────────────────────
# Piece 2 — Regime direction filter
#
# Honest map (per the prior audit):
#   STRONG_TREND_UP   → block SHORTs, allow LONGs
#   STRONG_TREND_DOWN → block LONGs,  allow SHORTs
#   RANGE_ROTATION    → allow reversal strategies; pass trend strategies through
#   TREND_FORMING_*   → stand down (anti-predictive per the audit)
#   COMPRESSION       → stand down
#   CHOP              → stand down
#   anything else / unknown → stand down
#
# Toggle: REGIME_DIRECTION_GATE_ENABLED (default per replay verdict).
# ─────────────────────────────────────────────────────────────
def evaluate_direction(symbol: str, direction: str, mode: str) -> Tuple[bool, str, dict]:
    """Block trades whose direction is inconsistent with the regime's honest map.

    NOTE: Default OFF per replay (2026-05-29, 16-trade sample, 7-day window).
    The TREND_FORMING_* stand-down piece is clearly value-add (-26.4p across
    8 trades — all losers). The STRONG_TREND_* counter-direction blocks are
    net-negative in this small sample (2 SHORTs in STRONG_TREND_UP were
    contrarian winners totalling +27.6p; gate would have blocked them).
    Whole gate nets -4.1p. Re-evaluate with ≥3 months of regime coverage."""
    enabled = _env_bool("REGIME_DIRECTION_GATE_ENABLED", "0")
    details: Dict[str, dict] = {"enabled": enabled}
    if not enabled:
        return True, "regime_direction_disabled", details

    try:
        import regime_engine as _re
        regime = _re.latest_result(symbol) or {}
    except Exception as exc:
        return True, "regime_fetch_failed_fail_open", {"error": str(exc)}
    if not regime:
        return True, "no_regime_yet_fail_open", {"symbol": symbol}

    winning = str(regime.get("winning_regime", "")).upper()
    direction_u = str(direction).upper()
    is_long = direction_u in ("BUY", "LONG", "L")
    is_short = direction_u in ("SELL", "SHORT", "S")
    mode_u = str(mode).upper()
    is_reversal = mode_u in REVERSAL_MODES
    details.update({"winning_regime": winning, "direction": direction_u, "mode": mode_u,
                    "is_reversal": is_reversal})

    if winning == "STRONG_TREND_UP":
        if is_short:
            return False, "BLOCKED:SHORT_in_STRONG_TREND_UP", details
        return True, "PASS:LONG_in_STRONG_TREND_UP", details
    if winning == "STRONG_TREND_DOWN":
        if is_long:
            return False, "BLOCKED:LONG_in_STRONG_TREND_DOWN", details
        return True, "PASS:SHORT_in_STRONG_TREND_DOWN", details
    if winning == "RANGE_ROTATION":
        # Reversal strategies are allowed; trend strategies pass through (they
        # have their own with-trend logic that wouldn't have fired in a range).
        return True, "PASS:RANGE_ROTATION", details
    # TREND_FORMING_*, COMPRESSION, CHOP, UNKNOWN, BREAKOUT_*: stand down
    return False, f"BLOCKED:stand_down_regime:{winning}", details


# ─────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────
def evaluate(symbol: str, direction: str, mode: str) -> Tuple[bool, str, dict]:
    """Evaluate all enabled sub-gates. Returns (passed, reason, details).

    A False from ANY sub-gate blocks the trade. Missing data fails open
    on a per-sub-gate basis (each sub-gate decides individually whether
    its specific signal is required).
    """
    master = _env_bool("CONVICTION_GATE_ENABLED", "1")
    details: Dict[str, dict] = {"master_enabled": master}
    if not master:
        return True, "master_disabled", details

    # Late import to avoid circular import on module load
    try:
        import regime_engine as _re
        regime = _re.latest_result(symbol) or {}
    except Exception as exc:
        # Regime unavailable at all — fail open (don't block on infra failure)
        logger.debug("[CONVICTION] regime fetch failed: %s — fail open", exc)
        return True, "regime_fetch_failed_fail_open", {"error": str(exc)}

    if not regime:
        return True, "no_regime_yet_fail_open", {"symbol": symbol}

    sub_results = []
    for name, fn in [
        ("ADX",       lambda: _gate_adx(regime)),
        ("DI",        lambda: _gate_di_alignment(regime, direction)),
        ("CONF",      lambda: _gate_confidence(regime)),
        ("EMA_STATE", lambda: _gate_ema_state(regime, mode, direction)),
        # Reversal-mode directional guard (2026-06-15). Logs would_block
        # verdict on every reversal-mode fire regardless of flag state;
        # enforces only when STRUCTURE_REVERSAL_TREND_GUARD_ENABLED=1.
        ("REV_TREND_GUARD", lambda: _gate_reversal_trend(regime, mode, direction)),
        ("CONF_SCORE", lambda: _gate_confirmation_score(symbol)),
    ]:
        try:
            passed, reason, d = fn()
        except Exception as exc:
            # Any sub-gate that errors → fail open
            passed, reason, d = True, f"{name}_exception_fail_open:{exc}", {"error": str(exc)}
        details[name] = {"passed": passed, "reason": reason, **d}
        sub_results.append((name, passed, reason))

    # ADX-gate instrumentation (2026-07-24, OBSERVATION ONLY). Emits one
    # INFO line per evaluation on both PASS and BLOCK paths. The gate
    # decision, threshold, ordering, and the sub-gate itself are unchanged.
    # Motivation: 07-24 06:20 BB_BOUNCE fire blocked at ADX 19.37, but
    # three 07-22 fires apparently passed at ADX < 20 with no journal
    # evidence of the specific sub-gate verdict. This line makes that
    # question answerable next time. Wrapped so telemetry can never
    # break the gate.
    try:
        _adx_det = details.get("ADX") or {}
        _adx_passed = bool(_adx_det.get("passed"))
        _adx_val = _adx_det.get("adx")
        _adx_floor = _adx_det.get("threshold")
        _adx_reason = _adx_det.get("reason")
        # Source: single call chain — feat.get("adx") in regime_engine._telemetry_record
        # (:1697), cached at _LATEST_RESULT_BY_SYM[SYMBOL] (:1895), read
        # in trade_executor.execute_trade via _cg.evaluate → this function's
        # regime = regime_engine.latest_result(symbol) (:616), then
        # _gate_adx(regime) reads regime.get("ADX") (:226).
        logger.info(
            "[CONVICTION-ADX] pair=%s strategy=%s adx=%s "
            "source=regime_engine.latest_result.ADX floor=%s verdict=%s reason=%s",
            symbol, mode,
            (f"{float(_adx_val):.2f}" if _adx_val is not None else "None"),
            (f"{float(_adx_floor):.2f}" if _adx_floor is not None else "None"),
            ("PASS" if _adx_passed else "BLOCK"),
            _adx_reason,
        )
    except Exception:  # noqa: BLE001
        logger.debug("[CONVICTION-ADX] telemetry emit raised — swallowed", exc_info=True)

    blocked_by = [name for name, p, _ in sub_results if not p]
    if blocked_by:
        reasons = ";".join(f"{n}:{r}" for n, p, r in sub_results if not p)
        return False, f"BLOCKED_BY:{','.join(blocked_by)}|{reasons}", details

    return True, "PASS", details
