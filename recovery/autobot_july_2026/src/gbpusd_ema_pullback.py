"""
gbpusd_ema_pullback.py — GBPUSD EMA pullback continuation strategy.

ENTRY DEFINITION (rebuilt 2026-05-27 — the prior symmetric
"band-touch → ribbon-intersect" geometry was structurally counter-
selective: it fired on snap-back bounces from a fresh band low and
rejected the real retrace-and-continue pullback. This rebuild
inverts the geometry: trail-down → rally up into ribbon → bearish
close back below ema8 = SHORT entry).

  SHORT (LONG is the EXACT mirror — upper-band trail, H1 BULLISH,
  rally DOWN into stack, descent contained below-ema21, entry =
  bullish candle closing back ABOVE ema8):

  H1 CONTEXT — uses indicators.h1_ema_direction (same source as
  gbpusd_trend, reads from the htf_cache H1 series):
    1. h1_ema_direction("GBPUSD")["direction"] == "BEARISH".
    2. H1 fan floor: |H1 ema8 − ema21| >= H1_SEP_MIN_PIPS (default
       2.0p, env GBPUSD_EMA_PULLBACK_H1_SEP_MIN). The indicator's
       own flat cutoff is 0.5p; the 2.0p floor sits above flat for
       a real H1 commit without rejecting today-like setups (07:40
       UTC reference H1 sep ≈ −4.2p to −4.9p — admits with margin).

  ⚠️ NO 5M FAN-WIDTH GATE. A genuine pullback BUNCHES the 5M EMAs by
  nature (rally + retrace compresses the stack). Width is checked
  on H1 only. The 5M side cares about ORDERING.

  5M PULLBACK + ENTRY:
    3. Band-trail context: in last TRAIL_LOOKBACK_BARS, the lowest
       bar low must (a) sit ≥ TRAIL_MIN_AGO_BARS before the entry
       candidate (so price has already pulled OFF the trail-low,
       not still extending it — this is what rejects the "BAD"
       bounce-from-fresh-low geometry) AND (b) be within
       TRAIL_BAND_TOL_PIPS of bbL at that bar (real band-trail,
       not an arbitrary local low).
    4. 5M stack ORDERED (DOWN for SHORT): e8 < e13 < e21 < e50.
       ⚠️ ORDERING ONLY — no fan-width requirement.
    5. Pullback UP into the ribbon: in the LOOKBACK_BARS window,
       some bar had its HIGH >= ema8 at that bar — i.e., price
       did rally up into the EMA stack.
    6. ⚠️ INVALIDATION (Johnny's rule — whole-pullback): every bar
       from the PULLBACK START through the entry bar minus 1 (both
       inclusive) must satisfy bar.LOW ≤ ema21 (SHORT) / bar.HIGH ≥
       ema21 (LONG). ANY bar whose whole body sat above ema21 (for
       SHORT) / below ema21 (for LONG) kills the setup. "If it
       closes above the 21 EMA it isn't a pullback any more" —
       stricter than the symmetric "close past ema21" gate the
       legacy build used.
       PULLBACK START is the bar at which price MOST RECENTLY
       crossed UP into the ribbon: walking backward from B-1, the
       first bar whose HIGH ≥ ema8 (SHORT) / LOW ≤ ema8 (LONG).
       That bar marks the most recent ribbon touch before the
       entry. Earlier ribbon touches — older pullback attempts
       that may have failed independently — are NOT in this
       window; each pullback is its own window, evaluated
       independently. This is what lets today's 07:45 SHORT fire
       cleanly (its pullback start is 07:15 idx 87, with bars
       87‑92 all below ema21) while the prior 06:35-07:00 rally
       (with its 06:45 over‑ema21 ascent bar) is excluded as a
       separate, earlier setup.
    7. ⚠️ ENTRY TRIGGER: the entry bar B is BEARISH (close < open)
       AND its close is BELOW ema8 at B. That close-back-below-ema8
       IS the trigger — not just any bearish bar. (LONG mirror:
       bullish candle closing back ABOVE ema8.)

  Risk geometry — UNCHANGED:
    SL_PIPS            = 20p (broker SL distance at open)
    BROKER_TP_PIPS     = computed at fire time per RUNNER_TARGET_MODE
                         (origin_band → distance from entry to the
                         bbL/bbU at the trail-low/high, clamped to
                         [RUNNER_TP_MIN_PIPS, RUNNER_TP_MAX_PIPS])
    +10p scale-out     = UNIVERSAL in trade_manager — UNTOUCHED.
                         No mode allowlist; this strategy is eligible.
    Time stop          = 240m via BB_PIERCE_RUN_MODES (trade_manager
                         already includes GBPUSD_EMA_PULLBACK_L/S).
    Trail              = none (runner rides BE→broker-TP; TREND-style
                         ratchet trail is only for GBPUSD_TREND_L/S).

  KILL SWITCH — GBPUSD_EMA_PULLBACK_ENABLED default "0".
  (Distinct from legacy ema_pullback.py's EMA_PULLBACK_ENABLED; the
  two modules have independent kill-switches.)
  Slot modes are GBPUSD_EMA_PULLBACK_L / GBPUSD_EMA_PULLBACK_S
  (DISTINCT from GBPUSD_BB_BOUNCE_* — they do not share an open-slot).

  Module-level imports are stdlib + dataclasses only. strategy_logic
  (StrategyDecision), news_calendar, AND indicators (h1_ema_direction)
  are LAZY imports inside _detect/evaluate so mere import of this
  module does NOT pull in live side effects.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_ema_pullback")

LOG_TAG = "EMA_PULLBACK"

MODE_NAME_LONG  = "GBPUSD_EMA_PULLBACK_L"
MODE_NAME_SHORT = "GBPUSD_EMA_PULLBACK_S"

PIP_SIZE = 1.0  # GBPUSD on the IG TODAY epic: 1 raw point = 1 pip


# ─── env helpers ───────────────────────────────────────────────────────────
def _env_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


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


# ─── Configuration ────────────────────────────────────────────────────────
# Master kill-switch. Default OFF.
ENABLED = _env_bool("GBPUSD_EMA_PULLBACK_ENABLED", "0")

# Active session window (UTC, weekdays only).
WIN_START = dtime(_env_int("GBPUSD_EMA_PULLBACK_WIN_START_H", 6), 0)
WIN_END   = dtime(_env_int("GBPUSD_EMA_PULLBACK_WIN_END_H", 17), 0)

# Indicator params.
BB_PERIOD = _env_int("GBPUSD_EMA_PULLBACK_BB_PERIOD", 20)
BB_STD    = _env_float("GBPUSD_EMA_PULLBACK_BB_STD", 2.0)

# Detection lookbacks.
LOOKBACK_BARS         = _env_int("GBPUSD_EMA_PULLBACK_LOOKBACK_BARS", 12)        # pullback evidence (60 min)
COOLDOWN_BARS         = _env_int("GBPUSD_EMA_PULLBACK_COOLDOWN_BARS", 12)        # 60 min between fires
WARMUP_BARS           = _env_int("GBPUSD_EMA_PULLBACK_WARMUP_BARS",   60)
TRAIL_LOOKBACK_BARS   = _env_int("GBPUSD_EMA_PULLBACK_TRAIL_LOOKBACK_BARS", 30)  # ~2.5h for band-trail check
TRAIL_MIN_AGO_BARS    = _env_int("GBPUSD_EMA_PULLBACK_TRAIL_MIN_AGO_BARS", 3)    # trail-extreme must be ≥3 bars old
TRAIL_BAND_TOL_PIPS   = _env_float("GBPUSD_EMA_PULLBACK_TRAIL_BAND_TOL_PIPS", 2.0)  # trail extreme within 2p of band

# ⚠️ NO 5M FAN GATE. A pullback bunches the 5M EMAs by nature; the prior
# 5M fan-width gate was self-defeating against the very geometry this
# strategy targets. Width is checked on H1 only — see below.

# H1 separation floor (in pips). The H1 ema8−ema21 separation must clear
# this absolute floor for the H1 stack to count as a "committed" trend
# read. indicators.h1_ema_direction's own flat threshold is 0.5p; we sit
# above that for a real commit. Today's 07:40 UTC reference has H1
# sep = −4.92p, so 2.0p admits with margin.
H1_SEP_MIN_PIPS       = _env_float("GBPUSD_EMA_PULLBACK_H1_SEP_MIN", 2.0)

# ─── H1 direction veto — M5 OVERRIDE (2026-05-28) ──────────────────────
# H1 ema8/ema21 cross is lagging by design (~3 H1 bars on sharp reversals).
# On 2026-05-28 it blocked 17 LONGs through a 35-pip M5 STRONG_TREND_UP
# rally because H1 ema8 was still anchored to the overnight crash.
#
# This override lets the entry bypass the H1 direction veto when the M5
# evidence is unambiguous (strong trend, not forming; full stack alignment;
# slope positive AND accelerating; directional_bias matches). Every other
# EMA_PULLBACK gate still applies — only the H1 direction veto is bypassed.
# The H1 separation floor (|sep| ≥ H1_SEP_MIN_PIPS) still applies in the
# default path because override is direction-only; if H1 happened to be
# BULLISH but flat, that's still blocked by sep gate as before.
#
# Override is gated by EMA_PULLBACK_H1_OVERRIDE_ENABLED (default ON) so it
# can be killed instantly. The override pulls regime_engine.latest_result
# for the strong-vs-forming discrimination; everything else is computed
# locally from M5 closes (no second race against regime_engine).
H1_OVERRIDE_ENABLED   = _env_bool("EMA_PULLBACK_H1_OVERRIDE_ENABLED", "1")

# Regime tagging (added 2026-06-01) — capture gbpusd_regime_detector's
# fire-time verdict into decision.debug so signal_logger writes it onto
# the trade row. INSTRUMENTATION ONLY: no gating, no behaviour change.
# Mirrors BB_BOUNCE's REGIME_TAG_ENABLED.
REGIME_TAG_ENABLED    = _env_bool("EMA_PULLBACK_REGIME_TAG_ENABLED", "true")

# 5M fan-width gate (added 2026-06-01) — BLOCKS entry when the 5M
# EMA8-EMA50 spread (signed by direction = fan_pips) is below MIN_FAN_PIPS,
# OR the current BB(20,2) width is below the trailing mean over
# SQUEEZE_LOOKBACK_BARS bars (squeeze). Inverts the prior design choice
# documented at _detect() ("No 5M fan-width gate anywhere") — backed by
# 2026-06-01 fills where the three losers (#2/#5/#8) all sat at thin fan
# and/or in squeeze, and the lone winner (#11) cleared both. Default 3.0p
# clears today's winner (4.75p) with margin and blocks today's worst
# loser (1.33p) decisively. Kill-switches via env.
FAN_GATE_ENABLED       = _env_bool("EMA_PULLBACK_FAN_GATE_ENABLED", "true")
MIN_FAN_PIPS           = _env_float("EMA_PULLBACK_MIN_FAN_PIPS", 3.0)
SQUEEZE_LOOKBACK_BARS  = _env_int("EMA_PULLBACK_SQUEEZE_LOOKBACK_BARS", 60)

# ─── Momentum-direction SHADOW gate (added 2026-06-24) ─────────────────
# Proven on n=43 real fills: winners vs losers separate on MOMENTUM
# DIRECTION at entry, not exhaustion magnitude. Three components plus a
# tail-safety; runs ONLY in shadow by default — logs would-block, blocks
# nothing. Promotion is a flag flip (ENFORCE=1), no rebuild.
#   1. RSI(14) 3-bar delta, signed in trade direction > 0
#   2. MACD-hist 3-bar slope, signed in trade direction > 0
#   3. Decisive entry candle: |close - ema8| in pips >= EMA_DECISIVE_MIN_PIPS
#   4. Tail safety: leg_run pips (trail-extreme → entry) <= EMA_LEG_RUN_MAX_PIPS
MOMENTUM_GATE_SHADOW_ENABLED = _env_bool("EMA_PULLBACK_MOMENTUM_GATE_SHADOW", "1")
MOMENTUM_GATE_ENFORCE        = _env_bool("EMA_PULLBACK_MOMENTUM_GATE_ENFORCE", "0")
MOM_RSI_LOOKBACK             = _env_int("EMA_MOM_RSI_LOOKBACK", 3)
MOM_MACD_LOOKBACK            = _env_int("EMA_MOM_MACD_LOOKBACK", 3)
# Indicator periods — Johnny's chart settings (2026-06-25). RSI 14→3,
# MACD (12,26,9)→(35,45,30). RESETS the n=43 calibration (which used
# 12/26/9/14) — re-baseline before promoting ENFORCE.
MOM_RSI_PERIOD               = _env_int("EMA_MOM_RSI_PERIOD", 3)
MOM_MACD_FAST                = _env_int("EMA_MOM_MACD_FAST", 35)
MOM_MACD_SLOW                = _env_int("EMA_MOM_MACD_SLOW", 45)
MOM_MACD_SIGNAL              = _env_int("EMA_MOM_MACD_SIGNAL", 30)
DECISIVE_MIN_PIPS            = _env_float("EMA_DECISIVE_MIN_PIPS", 3.0)
LEG_RUN_MAX_PIPS             = _env_float("EMA_LEG_RUN_MAX_PIPS", 45.0)
MOMENTUM_SHADOW_PATH         = os.getenv(
    "EMA_PULLBACK_MOMENTUM_SHADOW_LOG_PATH",
    "/opt/tradingbot/logs/ema_pullback_momentum_shadow.jsonl",
)

# ─── EMA_PULLBACK velocity gate (2026-06-26, LIVE ENFORCE) ──────────────
# EMA_PULLBACK fires AFTER a bounce starts, so velo at entry is usually
# NEGATIVE in the faded direction (price has already turned). Losers
# cluster in the "uncommitted bounce" band velo_in_faded ∈ [−0.5, 0]:
# n=10, 90% loss, −121.9p (78% of the strategy's total −156p loss).
# Require velo_in_faded <= EMA_PB_VELO_MAX (default −0.5) so we only
# fire when the bounce has visible momentum already. Sign convention
# MIRRORS the shipped BB_BOUNCE velocity guard (commit 3898279):
#   velo_10 = (closes[-1] - closes[-11]) / 10
#   faded_sign = -1 for BUY/L, +1 for SELL/S
#   velo_in_faded = velo_10 * faded_sign  → +ve means rushing into stack
# Stacks ON TOP of the trend gate (both must pass). Fail-open on error.
EMA_PB_VELOCITY_GATE_ENABLED = _env_bool("EMA_PB_VELOCITY_GATE_ENABLED", "1")
EMA_PB_VELO_MAX = _env_float("EMA_PB_VELO_MAX", -0.5)
EMA_PB_VELO_BARS = _env_int("EMA_PB_VELO_BARS", 10)
EMA_PB_VELO_LOG_PATH = os.getenv(
    "EMA_PB_VELO_LOG_PATH",
    "/opt/tradingbot/logs/ema_pb_velocity_gate.jsonl",
)

_ema_pb_velo_log_lock = threading.Lock()


def _ema_pb_velo_log(rec: Dict[str, Any]) -> None:
    """Append one JSON record to the EMA_PULLBACK velocity gate audit log.
    Never raises — log-write failures must not affect the gate verdict."""
    try:
        d = os.path.dirname(EMA_PB_VELO_LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _ema_pb_velo_log_lock:
            with open(EMA_PB_VELO_LOG_PATH, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


# ─── PULLBACK-FIX ENTRY GEOMETRY (2026-06-26, revised) ──────────────────
# Replaces Gate 7's legacy "bullish body + close > ema8" trigger (which
# fired today's 13228.9 extension LONG → -20p SL) with Johnny's confirmed
# pullback definition:
#
#   Step 1  STRONG TREND — regime_engine.latest_result(symbol)
#           .winning_regime == STRONG_TREND_UP (LONG) /
#           STRONG_TREND_DOWN (SHORT). The new H1-MACD classifier
#           (commit 8a6334c) already encodes "steep + building" as
#           STRONG_TREND, so this single read carries the H1 trend
#           context — no separate EMA fan/slope number needed (H1
#           ema fan on GBPUSD is sub-pip; pip-floors would be wrong
#           in any direction).
#           EMA_PB_REGIME_REQUIRE_STRONG=true (default) → strict.
#           EMA_PB_REGIME_REQUIRE_STRONG=false → widens to include
#           TREND_FORMING_UP/DOWN (Johnny tunes if too strict live).
#           Missing/None winning_regime → REJECT (fail-CLOSED).
#   Step 2  STACK ORDERED — reuses the existing is_bull/is_bear check
#           upstream (e8 > e13 > e21 > e50 LONG / reverse SHORT).
#   Step 3  TRIGGER — entry bar WICK crosses INTO the ribbon:
#             LONG : cur_bar.low  <= ema8[i] OR cur_bar.low  <= ema13[i]
#             SHORT: cur_bar.high >= ema8[i] OR cur_bar.high >= ema13[i]
#           Wick-cross counts; body/close need not cross. Else
#           REJECT "no_ribbon_pullback".
#   Step 4  HELD PULLBACK — close stays on the right side of ema21:
#             LONG : cur_bar.close > ema21[i]   else "closed_through_stack"
#             SHORT: cur_bar.close < ema21[i]
#
# Note: the prior commit had a Step 5 BAND GUARD (close < bbU LONG /
# close > bbL SHORT). Removed 2026-06-26 — it wrongly rejected the
# 08:05 UTC textbook pullback recovery candle whose close pierced bbU
# by 0.79p. Johnny's real continuation filter is the 21-EMA close-hold
# (Step 4). The 14:00 UTC extension fire is ALREADY caught structurally
# by Step 3 (wick-into-ribbon) — its low never crossed down into
# ema8/ema13, so Step 3 rejects without needing the band guard.
#
# Kill-switched: EMA_PB_PULLBACK_FIX_ENABLED=0 → Gate 7 behaves
# byte-identical to today (legacy "bullish body + close>ema8").
EMA_PB_PULLBACK_FIX_ENABLED   = _env_bool("EMA_PB_PULLBACK_FIX_ENABLED", "0")
EMA_PB_REGIME_REQUIRE_STRONG  = _env_bool("EMA_PB_REGIME_REQUIRE_STRONG", "1")
_REGIME_MATRIX_ENABLED        = _env_bool("REGIME_MATRIX_ENABLED", "0")
# Armed-machine fire-path regime eligibility gate (2026-07-28).
# WIDE eligibility, applied on top of stack/fan/h1. off | enforce.
EMA_PB_REGIME_GATE_MODE       = os.getenv("EMA_PB_REGIME_GATE_MODE", "enforce")
# 2026-07-28: retire the armed machine, run legacy _detect under the
# WIDE regime gate. Single reversible switch — default "1" forces the
# detect path and short-circuits the armed_machine call regardless of
# EMA_PB_ARMED_MACHINE_ENABLED. Flip to "0" AND flip EMA_PB_ARMED_
# MACHINE_ENABLED=1 to restore the armed-machine path exactly as it
# ran pre-change. The regime gate applies to BOTH paths.
EMA_PB_DETECT_MODE            = _env_bool("EMA_PB_DETECT_MODE", "1")
EMA_PB_PULLBACK_FIX_LOG_PATH  = os.getenv(
    "EMA_PB_PULLBACK_FIX_LOG_PATH",
    "/opt/tradingbot/logs/ema_pb_pullback_fix.jsonl",
)
_ema_pb_pbfix_log_lock = threading.Lock()

# Regime acceptance sets — toggled by EMA_PB_REGIME_REQUIRE_STRONG.
_EMA_PB_LONG_REGIMES_STRICT  = frozenset({"STRONG_TREND_UP"})
_EMA_PB_SHORT_REGIMES_STRICT = frozenset({"STRONG_TREND_DOWN"})
_EMA_PB_LONG_REGIMES_WIDE    = frozenset({"STRONG_TREND_UP",  "TREND_FORMING_UP"})
_EMA_PB_SHORT_REGIMES_WIDE   = frozenset({"STRONG_TREND_DOWN","TREND_FORMING_DOWN"})


def _ema_pb_pbfix_log(rec: Dict[str, Any]) -> None:
    """Append one JSON record to the pullback-fix audit log. Never raises."""
    try:
        d = os.path.dirname(EMA_PB_PULLBACK_FIX_LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _ema_pb_pbfix_log_lock:
            with open(EMA_PB_PULLBACK_FIX_LOG_PATH, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def _ema_pb_read_regime_label(symbol: str) -> Optional[str]:
    """Read winning_regime from regime_engine.latest_result. Returns None
    on any failure (module miss, cache empty, exception). Caller treats
    None as 'no signal' — fail-CLOSED on the regime gate."""
    try:
        import regime_engine as _re
        r = _re.latest_result(symbol) or {}
    except Exception as exc:
        logger.warning(
            "[%s] regime_engine.latest_result failed: %s — pullback-fix fail-closed",
            LOG_TAG, exc,
        )
        return None
    w = r.get("winning_regime")
    return str(w).upper() if w else None

# ─── TREND_ENTRY_GATE (added 2026-06-25, ENFORCE-ON by default) ─────────
# Hard gate: adx_slope >= ADX_SLOPE_MIN AND last same-dir MACD(12,26,9)
# signal-line cross within CROSS_MAX_BARS bars. Validated on 67 real fills
# (ungated −238p → 22 pass +76p). See trend_entry_gate.py for the audit
# trail. Master switch: TREND_ENTRY_GATE_ENABLED. Per-fire log written to
# logs/trend_entry_gate.jsonl on EVERY fire (pass or block) — direction
# field is essential because validation was short-heavy.
#
# EMA_PULLBACK ADX_SLOPE EXEMPTION (2026-06-27). EMA_PULLBACK fires by
# definition on a pullback — and a pullback REDUCES ADX (the trend pauses
# briefly), so leg_a (adx_slope >= 0) structurally rejects valid pullback
# entries. Today's 09:10 BST clean LONG was blocked by exactly this:
# "TREND_GATE block: leg_a:adx_slope=-5.0796<+0.00". The MACD-cross leg_b
# (added by the same commit) still discriminates trend continuation
# correctly. With this exemption, EMA_PULLBACK ignores leg_a but still
# enforces leg_b. STRUCTURE_BREAK keeps BOTH legs unchanged. Kill-
# switchable via TREND_ENTRY_GATE_EMA_PB_EXEMPT (default true → exempt
# EMA_PULLBACK from leg_a; set 0 to restore both-legs enforcement).
TREND_ENTRY_GATE_EMA_PB_EXEMPT = _env_bool(
    "TREND_ENTRY_GATE_EMA_PB_EXEMPT", "1",
)

# Risk geometry.
SL_PIPS              = _env_float("GBPUSD_EMA_PULLBACK_SL_PIPS", 20.0)
# Runner target. "origin_band" (default) computes per-fire; "fixed" uses the
# fallback distance below.
RUNNER_TARGET_MODE   = os.getenv("GBPUSD_EMA_PULLBACK_RUNNER_TARGET", "origin_band").strip().lower()
FIXED_RUNNER_TP_PIPS = _env_float("GBPUSD_EMA_PULLBACK_FIXED_RUNNER_TP_PIPS", 40.0)
RUNNER_TP_MIN_PIPS   = _env_float("GBPUSD_EMA_PULLBACK_RUNNER_TP_MIN_PIPS", 15.0)
RUNNER_TP_MAX_PIPS   = _env_float("GBPUSD_EMA_PULLBACK_RUNNER_TP_MAX_PIPS", 100.0)

# ─── ARMED-STATE ENTRY MACHINE (2026-06-27, kill-switched, default OFF) ──
# A new, independent continuation-only entry path. Modelled on
# BB_BOUNCE's arm-and-wait state pattern (gbpusd_bb_bounce.py:440-454),
# adapted for EMA_PULLBACK geometry:
#
#   Preconditions (ALL required, else no setup; cleared if any drops):
#     • 5M stack ordered: e8>e13>e21>e50 (LONG) or e8<e13<e21<e50
#       (SHORT). Sole trend/direction source (2026-06-28). No fan-
#       width gate — stack fanning is NOT a precondition; fan_pips
#       is computed for telemetry only.
#     • H1 direction matches trade side (BULLISH for LONG / BEARISH
#       for SHORT). Same source as legacy _detect's _h1_direction().
#   ARM:    bar touches/crosses 8 EMA (wick OR body) — bar.low ≤ e8
#           for LONG / bar.high ≥ e8 for SHORT. 13 EMA is irrelevant.
#   DISARM (only):
#           Bar CLOSES beyond 21 EMA — close < e21 for LONG /
#           close > e21 for SHORT. Wicks through 21 do NOT disarm.
#           Also cleared on preconditions lost (fan/regime/H1/side).
#           No time/window expiry — armed persists across bars
#           indefinitely until fire or 21-close disarm.
#   FIRE:   each 5m close while armed, trigger level = e8 + 2p
#           (LONG) / e8 − 2p (SHORT), re-priced from the CURRENT e8
#           every bar (synthesised resting stop — the IG order layer
#           is market-only; no broker pending-order exists). Fires
#           iff the bar TRADED THROUGH the level — i.e. lvl is
#           inside [bar.low, bar.high]. A bar that closes above the
#           level without its low reaching it must NOT fire — the
#           explicit #45 above-band guard.
#
# Default OFF. When enabled, defaults to SHADOW (telemetry only —
# every ARM / DISARM / would-FIRE is logged with full geometry but
# NO call to execute_trade). Promote to live by setting
# EMA_PB_ARMED_MACHINE_SHADOW=0 once the audit log validates.
#
# In-memory only — armed state is held on the strategy singleton and
# does NOT survive process restart. Matches BB_BOUNCE.
EMA_PB_ARMED_MACHINE_ENABLED = _env_bool("EMA_PB_ARMED_MACHINE_ENABLED", "0")
EMA_PB_ARMED_MACHINE_SHADOW  = _env_bool("EMA_PB_ARMED_MACHINE_SHADOW",  "1")
EMA_PB_ARMED_MACHINE_TRIGGER_OFFSET_PIPS = _env_float(
    "EMA_PB_ARMED_MACHINE_TRIGGER_OFFSET_PIPS", 2.0,
)
EMA_PB_ARMED_MACHINE_LOG_PATH = os.getenv(
    "EMA_PB_ARMED_MACHINE_LOG_PATH",
    "/opt/tradingbot/logs/ema_pb_armed_machine.jsonl",
)

# Trend/direction source: 5M stack ordering (e8>e13>e21>e50 for LONG,
# e8<e13<e21<e50 for SHORT). Sole qualifier as of 2026-06-28 — the
# regime classifier no longer gates the armed machine. The regime-set
# constants previously read here were removed in the same commit; the
# legacy _detect path still reads regime via _ema_pb_read_regime_label
# against _EMA_PB_LONG_REGIMES_* sets defined further down.

_ema_pb_armed_log_lock = threading.Lock()


def _ema_pb_armed_log(rec: Dict[str, Any]) -> None:
    """Append one JSON record to the armed-machine audit log.
    Never raises — log-write failures must not affect the machine."""
    try:
        d = os.path.dirname(EMA_PB_ARMED_MACHINE_LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _ema_pb_armed_log_lock:
            with open(EMA_PB_ARMED_MACHINE_LOG_PATH, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


# ─── HTF telemetry snapshot — bounded latency, fail-open ────────────────
# htf_regime.classify() does disk reads + numpy passes over ~800 H1 bars
# and has no internal timeout. Without a wall-time cap, a slow cache read
# (file contention at H1 close, GC pressure, disk stall) on the FIRE path
# would delay `return StrategyDecision(...)` and therefore execute_trade.
#
# The fix: run classify() on a long-lived module-level worker pool and
# wait at most EMA_PB_HTF_TIMEOUT_SEC for the result. On timeout OR any
# exception, return the three telemetry fields as None — IDENTICAL to
# the original fail-open exception path. The in-flight classify keeps
# running on its worker and completes naturally; we discard the future
# and never read it again, so a slow classify cannot raise back into
# the caller.
#
# Containment: executor is module-level (no per-call leak), futures live
# only inside the helper's try/except, all execution paths return one of
# two literal dict shapes. No exception escapes _ema_pb_htf_snapshot.
EMA_PB_HTF_TIMEOUT_SEC = _env_float("EMA_PB_HTF_TIMEOUT_SEC", 0.25)
_ema_pb_htf_executor = None
try:
    from concurrent.futures import ThreadPoolExecutor as _EMAPBHTFPool
    _ema_pb_htf_executor = _EMAPBHTFPool(
        max_workers=2, thread_name_prefix="ema-pb-htf",
    )
except Exception:
    _ema_pb_htf_executor = None  # helper falls through to all-None output


def _ema_pb_htf_snapshot(symbol: str) -> Dict[str, Any]:
    """Fail-open HTF stamp for armed-machine ARM/FIRE telemetry. Calls
    htf_regime.classify(symbol) (same in-process pattern htf_authority.py
    uses — there is no latest_result accessor) on a worker thread with a
    hard wall-time cap (EMA_PB_HTF_TIMEOUT_SEC, default 0.25s).

    NEVER gates / blocks / delays the armed machine — on exception,
    timeout, or empty return, all three fields are None and the caller
    proceeds normally. The timeout itself is contained inside the outer
    try/except; the in-flight classify continues on its worker after a
    timeout and is GC'd when it completes, but no exception or thread
    state ever propagates back to this caller."""
    _null = {
        "htf_h1_state":         None,
        "htf_macd_cross_state": None,
        "htf_alignment":        None,
    }
    if _ema_pb_htf_executor is None:
        return dict(_null)
    try:
        from concurrent.futures import TimeoutError as _FutTimeout
        import htf_regime as _htf
        _fut = _ema_pb_htf_executor.submit(_htf.classify, symbol)
        try:
            r = _fut.result(timeout=EMA_PB_HTF_TIMEOUT_SEC) or {}
        except _FutTimeout:
            # Slow classify — discard the future; the worker finishes on
            # its own. Caller gets null fields, same as the exception path.
            return dict(_null)
        feat = ((r.get("debug") or {}).get("h1_features") or {})
        return {
            "htf_h1_state":         r.get("h1_state"),
            "htf_macd_cross_state": feat.get("macd_cross_state"),
            "htf_alignment":        r.get("alignment"),
        }
    except Exception:
        return dict(_null)


# News blackout (mirror bb_bounce default-ON).
NEWS_BLACKOUT_ENABLED = _env_bool("GBPUSD_EMA_PULLBACK_NEWS_BLACKOUT_ENABLED", "1")
NEWS_PRE_MIN          = _env_int("GBPUSD_EMA_PULLBACK_NEWS_PRE_MIN", 30)
_NEWS_AFFECTING_CCYS  = ("GBP", "USD")


# ─── News blackout helper (lazy news_calendar import) ──────────────────────
def _is_pre_news_blackout(now_utc: datetime) -> Tuple[bool, str]:
    """True iff `now_utc` is within NEWS_PRE_MIN minutes before a High-impact
    GBP/USD event today. Soft on errors — never blocks on calendar failure."""
    if not NEWS_BLACKOUT_ENABLED or NEWS_PRE_MIN <= 0:
        return False, ""
    try:
        import news_calendar  # lazy: avoid module-level live-state imports
        events = news_calendar.get_todays_events(currencies=list(_NEWS_AFFECTING_CCYS))
    except Exception:
        return False, ""
    if not events:
        return False, ""
    pre_seconds = float(NEWS_PRE_MIN) * 60.0
    for ev in events:
        if str(ev.get("impact") or "").strip() != "High":
            continue
        ccy = str(ev.get("currency") or "").upper()
        if ccy not in _NEWS_AFFECTING_CCYS:
            continue
        try:
            h, mi = map(int, str(ev.get("time") or "").split(":"))
        except (ValueError, AttributeError):
            continue
        ev_dt = now_utc.replace(hour=h, minute=mi, second=0, microsecond=0)
        secs_until = (ev_dt - now_utc).total_seconds()
        if 0 < secs_until <= pre_seconds:
            return True, (f"news_blackout_pre: {ccy} {ev.get('event_name','')}"
                          f" @ {ev.get('time')}UTC (in {secs_until/60.0:.1f}m)")
    return False, ""


# ─── Bar dataclass ────────────────────────────────────────────────────────
@dataclass
class Bar:
    """A closed 5m candle. `timestamp` is tz-aware UTC."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float

    @property
    def body_pips(self) -> float:
        return abs(self.close - self.open) / PIP_SIZE


# ─── Indicators ────────────────────────────────────────────────────────────
def _ema(values: Sequence[float], n: int) -> List[float]:
    """EMA seeded with the first close. Same recipe as the rest of the codebase."""
    if not values:
        return []
    a = 2.0 / (n + 1.0)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(a * float(v) + (1.0 - a) * out[-1])
    return out


def _rsi_wilder(values: Sequence[float], period: int = 14) -> List[float]:
    """Wilder-RMA RSI mirroring indicators.rsi (Wilder smoothing α=1/N,
    adjust=False, seeded at the first delta). Returns a series of the
    same length as `values`; index 0 is NaN-like (set to 50.0 as a
    neutral sentinel — never referenced for entries since we need at
    least `period + MOM_RSI_LOOKBACK` warmup)."""
    n = len(values)
    if n < 2:
        return [50.0] * n
    alpha = 1.0 / float(period)
    out: List[float] = [50.0]  # placeholder for index 0 (no delta yet)
    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, n):
        d = float(values[i]) - float(values[i - 1])
        gain = d if d > 0 else 0.0
        loss = -d if d < 0 else 0.0
        if i == 1:
            avg_gain = gain
            avg_loss = loss
        else:
            avg_gain = alpha * gain + (1.0 - alpha) * avg_gain
            avg_loss = alpha * loss + (1.0 - alpha) * avg_loss
        if avg_gain < 1e-12 and avg_loss < 1e-12:
            out.append(50.0)
        elif avg_loss < 1e-12:
            out.append(100.0)
        elif avg_gain < 1e-12:
            out.append(0.0)
        else:
            rs = avg_gain / avg_loss
            out.append(100.0 - (100.0 / (1.0 + rs)))
    return out


def _macd_hist(values: Sequence[float],
               fast: int = 12, slow: int = 26, signal: int = 9
               ) -> List[float]:
    """MACD histogram mirroring indicators.macd: macd_line = EMA(fast) -
    EMA(slow), signal_line = EMA(macd_line, signal), hist = macd_line -
    signal_line. Uses the same EWM (adjust=False, seeded at first value)
    recipe as `_ema` above and indicators.macd at slow=26."""
    if not values:
        return []
    ema_fast = _ema(values, fast)
    ema_slow = _ema(values, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    return [m - s for m, s in zip(macd_line, signal_line)]


def _write_momentum_shadow(rec: Dict[str, Any]) -> None:
    """Append one JSONL row to MOMENTUM_SHADOW_PATH. Telemetry-only —
    must never raise back into the fire path. Mirrors the swallow-style
    used by gbpusd_bb_bounce._write_bb_bounce_l_cascade_shadow."""
    try:
        d = os.path.dirname(MOMENTUM_SHADOW_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(MOMENTUM_SHADOW_PATH, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[%s] momentum_shadow write failed: %s", LOG_TAG, exc)


def _bb_at(closes: Sequence[float], idx: int,
           period: int = BB_PERIOD, k: float = BB_STD
           ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Bollinger Bands (lower, mid, upper) at index `idx`. None for warmup."""
    if idx + 1 < period:
        return None, None, None
    window = closes[idx - period + 1 : idx + 1]
    m = sum(window) / period
    var = sum((c - m) ** 2 for c in window) / period
    s = math.sqrt(var)
    return m - k * s, m, m + k * s


# ─── Detection internals ───────────────────────────────────────────────────
@dataclass
class _Evidence:
    direction: str                       # "LONG" or "SHORT"
    fan_pips: float                      # |ema8-ema50| in pips — gated by MIN_FAN_PIPS when FAN_GATE_ENABLED
    bb_width_pips: float                 # current BB(20,2) width in pips
    bb_squeeze: bool                     # True iff current width < mean width over SQUEEZE_LOOKBACK_BARS
    h1_direction: str                    # H1 EMA direction ("BULLISH" / "BEARISH")
    h1_separation_pips: float            # signed H1 ema8-ema21 separation (|..| ≥ H1_SEP_MIN_PIPS)
    pullback_start_offset_bars: int      # bars ago the pullback started (most recent ribbon touch)
    pullback_peak_offset_bars: int       # bars ago the pullback peak (max H SHORT / min L LONG) sat — reporting only
    pullback_peak_price: float           # the pullback peak's high (SHORT) / low (LONG)
    trail_extreme_offset_bars: int       # bars ago the trail-low (SHORT) / trail-high (LONG) sat
    trail_extreme_price: float           # the trail-extreme price itself
    trail_band_proximity_pips: float     # trail extreme − bbL (SHORT) / bbU − trail (LONG) at trail bar
    entry_bar_body_pips: float           # |close - open| at entry bar
    runner_tp_pips: float                # computed broker-TP distance
    ema8: float
    ema13: float
    ema21: float
    ema50: float
    bb_lower: float
    bb_mid: float
    bb_upper: float


# ─── Strategy class ───────────────────────────────────────────────────────
class GbpUsdEmaPullbackStrategy:
    """Singleton. Stateless across days — slot enforcement is provided by
    the autobot wiring via has_open_long / has_open_short."""

    _instance: Optional["GbpUsdEmaPullbackStrategy"] = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_fire_ts_by_epic: Dict[str, datetime] = {}
        # Previous EMA50 slope per pair — used by the H1 M5-override to
        # require slope acceleration (current slope steeper than prior).
        # Snapshotted at end of each _detect() call.
        self._prev_ema50_slope_by_pair: Dict[str, float] = {}
        # Armed-state entry machine (2026-06-27). Per-epic single-slot
        # dict carrying the current armed setup, or None when not armed.
        # Independent of the legacy _detect path (which is untouched).
        # Cleared on disarm (close past 21 EMA / preconditions lost) or
        # fire. Held in memory ONLY — does NOT survive restart, matching
        # BB_BOUNCE (gbpusd_bb_bounce.py:440-454).
        self._armed_machine: Dict[str, Optional[Dict[str, Any]]] = {}

    @classmethod
    def instance(cls) -> "GbpUsdEmaPullbackStrategy":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _in_window(self, ts_utc: datetime) -> bool:
        ts = ts_utc.astimezone(timezone.utc)
        if ts.weekday() >= 5:
            return False
        t = ts.time()
        return WIN_START <= t < WIN_END

    def _cooldown_ok(self, epic: str, ts: datetime) -> bool:
        last = self._last_fire_ts_by_epic.get(epic)
        if last is None:
            return True
        elapsed_min = (ts - last).total_seconds() / 60.0
        return elapsed_min >= COOLDOWN_BARS * 5.0

    # ── H1 direction (lazy import; required gate) ──────────────────────
    @staticmethod
    def _h1_direction() -> Optional[Dict[str, Any]]:
        """Wrapper around indicators.h1_ema_direction(GBPUSD). Same source
        gbpusd_trend uses. Returns dict or None."""
        try:
            import indicators
            return indicators.h1_ema_direction("GBPUSD", pip_size=PIP_SIZE)
        except Exception as exc:
            logger.warning("[%s] h1_ema_direction failed: %s", LOG_TAG, exc)
            return None

    # ── ARMED-STATE ENTRY MACHINE step (2026-06-27) ────────────────────
    def _armed_machine_step(self,
                            epic: str,
                            ts: datetime,
                            bars: Sequence[Bar],
                            closes_ind: Sequence[float],
                            symbol: str,
                            has_open_long: bool,
                            has_open_short: bool,
                            brake_adx_at_bar: Optional[float] = None,
                            brake_adx_source: Optional[str] = None,
                            ) -> Optional["StrategyDecision"]:
        """Advance the armed-state entry machine for `epic` on the just-
        closed 5m bar. Returns a StrategyDecision ONLY when the machine
        is ENABLED, shadow is OFF, fire conditions are met, and the
        same-side position slot is free. Returns None in every other
        case — including ALL shadow-mode would-fires (those are logged
        only, never produce a decision).

        Preconditions (ALL required — any drop disarms):
          • 5M stack ORDERED: e8>e13>e21>e50 → trend_side=LONG, or
            e8<e13<e21<e50 → trend_side=SHORT. Neither ordering →
            no setup. Stack ordering is the SOLE trend/direction
            qualifier (2026-06-28). Stack fanning ≥ MIN_FAN_PIPS
            IS a precondition when FAN_GATE_ENABLED (2026-07-20 —
            22-fill audit: F=2.5 lifts net +26.55p, blocks 3 of 6
            STRUCTURE_EXIT flip losses).
          • H1 direction = BULLISH for LONG / BEARISH for SHORT.
            Same H1 source as _detect().

        Transitions:
          ARM    — preconditions hold AND bar touches/crosses 8 EMA
                   (wick OR body): bar.low ≤ e8 (LONG) / bar.high ≥ e8
                   (SHORT). 13 EMA is irrelevant.
          DISARM — bar CLOSES beyond 21 EMA (close < e21 LONG /
                   close > e21 SHORT). Wicks through 21 do NOT
                   disarm. Or preconditions lost (stack no longer
                   ordered in armed direction / stack flips / H1
                   flips). No time/window expiry.
          FIRE   — while armed, the just-closed bar TRADED THROUGH
                   the resting-stop level lvl = e8 ± 2p (re-priced
                   from the CURRENT e8 every bar). I.e. lvl is
                   inside [bar.low, bar.high]. A bar closing above
                   lvl with low > lvl does NOT fire — the explicit
                   #45 above-band guard.

        State held on self._armed_machine[epic] (in-memory only):
          {"side": "LONG"|"SHORT", "armed_ts": datetime,
           "armed_e8": float, "armed_e21": float,
           "armed_h1_dir": str, "armed_fan_pips": float,
           "bars_since_arm": int}
          or None when not armed.

        Does NOT survive process restart (matches BB_BOUNCE arm-wait).
        """
        if not bars or not closes_ind:
            return None
        cur_bar = bars[-1]
        n = len(closes_ind)
        if n < max(50, WARMUP_BARS):
            return None

        # EMAs at the just-closed bar.
        e8s  = _ema(closes_ind, 8)
        e13s = _ema(closes_ind, 13)
        e21s = _ema(closes_ind, 21)
        e50s = _ema(closes_ind, 50)
        i = n - 1
        e8, e13, e21, e50 = e8s[i], e13s[i], e21s[i], e50s[i]

        # ── 5M stack ordering is the SOLE trend + direction source
        #    (2026-06-28). The regime classifier no longer gates the
        #    armed machine. Stack fanning ≥ MIN_FAN_PIPS IS a
        #    precondition when FAN_GATE_ENABLED (2026-07-20 — 22-fill
        #    audit: F=2.5 lifts net +26.55p, blocks 3 of 6
        #    STRUCTURE_EXIT flip losses). The EMAs continue to drive
        #    arm (touch e8), disarm (close past e21), and fire
        #    (level e8 ± 2p).
        is_bull = (e8 > e13 > e21 > e50)
        is_bear = (e8 < e13 < e21 < e50)
        if is_bull:
            trend_side: Optional[str] = "LONG"
        elif is_bear:
            trend_side = "SHORT"
        else:
            trend_side = None

        # Fan pips — side-signed EMA8-EMA50 spread. Feeds the fan_ok
        # precondition below when FAN_GATE_ENABLED. Sign convention
        # matches the legacy _detect path: positive when stack is in
        # trend direction.
        if trend_side == "LONG":
            fan_pips = (e8 - e50) / PIP_SIZE
        elif trend_side == "SHORT":
            fan_pips = (e50 - e8) / PIP_SIZE
        else:
            fan_pips = 0.0

        # H1 direction (lazy, shared with legacy). RETAINED as a
        # precondition — see preconditions_ok below.
        h1 = self._h1_direction() or {}
        h1_dir = str(h1.get("direction") or "").upper() if h1 else ""
        h1_ok = (
            (trend_side == "LONG"  and h1_dir == "BULLISH") or
            (trend_side == "SHORT" and h1_dir == "BEARISH")
        )

        fan_ok = (not FAN_GATE_ENABLED) or (fan_pips >= float(MIN_FAN_PIPS))

        preconditions_ok = (
            trend_side is not None and h1_ok and fan_ok
        )

        current = self._armed_machine.get(epic)

        # ── Currently armed: check side-flip / preconditions-lost first,
        #    then 21-EMA close disarm, then trigger. ───────────────────
        if current is not None:
            armed_side = current["side"]

            if (trend_side != armed_side) or (not preconditions_ok):
                if (trend_side == armed_side) and h1_ok and (not fan_ok):
                    _disarm_reason = (
                        f"fan_too_narrow fan={fan_pips:.2f}p<"
                        f"{float(MIN_FAN_PIPS):.2f}p"
                    )
                else:
                    _disarm_reason = "preconditions_lost"
                _ema_pb_armed_log({
                    "ts": cur_bar.timestamp.isoformat(),
                    "epic": epic,
                    "transition": "DISARM",
                    "reason": _disarm_reason,
                    "side": armed_side,
                    "trend_side_now": trend_side,
                    "fan_pips": round(fan_pips, 2),
                    "min_fan_pips": float(MIN_FAN_PIPS),
                    "fan_ok": bool(fan_ok),
                    "h1_dir": h1_dir,
                    "h1_ok": h1_ok,
                    "ema8":  round(e8,  5),
                    "ema13": round(e13, 5),
                    "ema21": round(e21, 5),
                    "ema50": round(e50, 5),
                    "bar_open":  cur_bar.open,
                    "bar_high":  cur_bar.high,
                    "bar_low":   cur_bar.low,
                    "bar_close": cur_bar.close,
                    "bars_since_arm": int(current.get("bars_since_arm", 0)),
                    "shadow_mode": bool(EMA_PB_ARMED_MACHINE_SHADOW),
                })
                self._armed_machine[epic] = None
                current = None
            else:
                close_disarm = (
                    (armed_side == "LONG"  and cur_bar.close < e21) or
                    (armed_side == "SHORT" and cur_bar.close > e21)
                )
                if close_disarm:
                    _ema_pb_armed_log({
                        "ts": cur_bar.timestamp.isoformat(),
                        "epic": epic,
                        "transition": "DISARM",
                        "reason": "close_past_ema21",
                        "side": armed_side,
                        "ema8":  round(e8,  5),
                        "ema13": round(e13, 5),
                        "ema21": round(e21, 5),
                        "ema50": round(e50, 5),
                        "bar_open":  cur_bar.open,
                        "bar_high":  cur_bar.high,
                        "bar_low":   cur_bar.low,
                        "bar_close": cur_bar.close,
                        "bars_since_arm": int(current.get("bars_since_arm", 0)),
                        "shadow_mode": bool(EMA_PB_ARMED_MACHINE_SHADOW),
                    })
                    self._armed_machine[epic] = None
                    current = None

        # ── Still armed? Evaluate the resting-stop trigger. ────────────
        if current is not None:
            armed_side = current["side"]
            offset_price = float(EMA_PB_ARMED_MACHINE_TRIGGER_OFFSET_PIPS) * PIP_SIZE
            if armed_side == "LONG":
                lvl = e8 + offset_price
            else:
                lvl = e8 - offset_price
            # TRADED THROUGH lvl: lvl is inside [bar.low, bar.high].
            # NOT "close above lvl" — close-only with low > lvl must
            # NOT fire (the #45 above-band guard).
            traded_through = (cur_bar.low <= lvl <= cur_bar.high)

            current["bars_since_arm"] = int(current.get("bars_since_arm", 0)) + 1

            if traded_through:
                slot_taken = (
                    (armed_side == "LONG"  and has_open_long) or
                    (armed_side == "SHORT" and has_open_short)
                )
                shadow = bool(EMA_PB_ARMED_MACHINE_SHADOW)
                would_fire_live = (not shadow) and (not slot_taken)
                # Per spec, the setup must remain armed until a 21-EMA-close
                # disarm (or preconditions lost). The armed slot is cleared
                # ONLY when a live trade decision is actually returned.
                # Shadow would-fires and slot-blocked would-fires log the
                # FIRE telemetry but leave the arm in place, so the next
                # through-trade on a later bar fires again. Each distinct
                # through-trade emits its own FIRE record (the gate is on
                # `traded_through` for the current bar, so a flat hover at
                # the level only fires once per bar; re-entry on a fresh
                # bar re-fires).
                armed_retained = (shadow or slot_taken)
                _htf_fire = _ema_pb_htf_snapshot(symbol)
                _ema_pb_armed_log({
                    "ts": cur_bar.timestamp.isoformat(),
                    "epic": epic,
                    "transition": "FIRE",
                    "side": armed_side,
                    "trigger_level": round(lvl, 5),
                    "trigger_offset_pips": float(
                        EMA_PB_ARMED_MACHINE_TRIGGER_OFFSET_PIPS
                    ),
                    "synth_entry_px": round(lvl, 5),
                    "ema8":  round(e8,  5),
                    "ema13": round(e13, 5),
                    "ema21": round(e21, 5),
                    "ema50": round(e50, 5),
                    "fan_pips": round(fan_pips, 2),
                    "min_fan_pips": float(MIN_FAN_PIPS),
                    "h1_dir": h1_dir,
                    "htf_h1_state":         _htf_fire["htf_h1_state"],
                    "htf_macd_cross_state": _htf_fire["htf_macd_cross_state"],
                    "htf_alignment":        _htf_fire["htf_alignment"],
                    "bar_open":  cur_bar.open,
                    "bar_high":  cur_bar.high,
                    "bar_low":   cur_bar.low,
                    "bar_close": cur_bar.close,
                    "bars_since_arm": int(current["bars_since_arm"]),
                    "armed_ts": current["armed_ts"].isoformat(),
                    "slot_taken": bool(slot_taken),
                    "shadow_mode": shadow,
                    "would_fire_live": would_fire_live,
                    "armed_retained": bool(armed_retained),
                })

                if armed_retained:
                    # Do NOT clear self._armed_machine[epic] — the spec is
                    # arm-until-21-close. Return None and let the next bar
                    # advance state normally.
                    return None

                # Live fire — build a decision that mirrors the legacy
                # construction. Exit stack INHERITED from execute_trade:
                #   • UNIVERSAL +8p / 50% scale-out + BE amend is mode-
                #     agnostic (trade_manager.py:2849-2857, _scale_out_50pct).
                #   • 240m time stop applies via BB_PIERCE_RUN_MODES
                #     (trade_manager.py:213-223 — GBPUSD_EMA_PULLBACK_L/S
                #     is in this set).
                #   • RUNNER TRAIL: trend stepped trail. Since 2026-06-27
                #     (commit 340e370) GBPUSD_EMA_PULLBACK_L/S is enrolled
                #     in _TREND_RUNNER_STYLE_MODES (trade_manager.py:437-451),
                #     so the runner inherits the same stepped ratchet as
                #     GBPUSD_TREND: triggers at peak MFE +15/+25/+40 pips,
                #     locking SL at +7/+17/+32 (trigger − 8p offset), floored
                #     at BE and monotonic upward.
                # Clear the armed slot now (live fire about to happen).
                self._armed_machine[epic] = None
                try:
                    from strategy_logic import StrategyDecision
                except Exception as exc:
                    logger.error("[%s] StrategyDecision import failed: %s",
                                 LOG_TAG, exc)
                    return None
                direction_signal = "BUY" if armed_side == "LONG" else "SELL"
                mode = MODE_NAME_LONG if armed_side == "LONG" else MODE_NAME_SHORT

                # ── REGIME ELIGIBILITY GATE (armed-machine fire path) ────
                # Layered ON TOP of the stack/fan/h1 preconditions as an
                # ADDITIONAL live precondition (2026-07-28, restoring
                # Johnny's 06-28 design intent, commit 67994bb). Reuses
                # _EMA_PB_LONG/SHORT_REGIMES_WIDE frozensets and the
                # _ema_pb_read_regime_label accessor — the SAME
                # regime_engine.latest_result → winning_regime read that
                # BB_BOUNCE, TREND_V3, and signal_logger consume, so a
                # single committed label decides the fleet.
                # Fail-OPEN on missing/null label: the classifier has
                # documented hiccup modes and must never silence the
                # armed machine on its own.
                if EMA_PB_REGIME_GATE_MODE == "enforce":
                    _reg_gate_label = _ema_pb_read_regime_label(symbol)
                    if _reg_gate_label is None:
                        logger.info(
                            "[EMA-PB-REGIME-GATE] verdict=PASS regime=NULL "
                            "dir=%s reason=failopen mode=enforce",
                            armed_side,
                        )
                    else:
                        if armed_side == "LONG":
                            _reg_gate_ok = (
                                _reg_gate_label in _EMA_PB_LONG_REGIMES_WIDE
                            )
                        else:
                            _reg_gate_ok = (
                                _reg_gate_label in _EMA_PB_SHORT_REGIMES_WIDE
                            )
                        if _reg_gate_ok:
                            logger.info(
                                "[EMA-PB-REGIME-GATE] verdict=PASS "
                                "regime=%s dir=%s mode=enforce",
                                _reg_gate_label, armed_side,
                            )
                        else:
                            logger.info(
                                "[EMA-PB-REGIME-GATE] verdict=BLOCK "
                                "regime=%s dir=%s mode=enforce",
                                _reg_gate_label, armed_side,
                            )
                            return None

                # ── VWAP-STRETCH BRAKE (armed-machine fire path) ─────────
                # Apply the same direction-aware brake the legacy _detect
                # path uses. CHOP-only, mode-allowlist (GBPUSD_EMA_PULLBACK
                # _L/S only). Fail-open everywhere. The armed-machine
                # fires off `lvl` (the e8 trigger price), not the bar
                # close — use that as the comparison price so vwap_dist
                # matches what the actual order will fill against.
                _brake_rec_armed: Dict[str, Any] = {"called": False}
                try:
                    from guards.trend_stretch_brake import evaluate as _stretch_brake
                    _blocked_a, _brake_reason_a, _brake_rec_armed = _stretch_brake(
                        strategy="EMA_PULLBACK_ARMED",
                        mode=mode,
                        direction=armed_side,
                        bars=bars,
                        last_price=float(lvl),
                        pip_size=PIP_SIZE,
                        symbol=symbol,
                        ts_utc=ts,
                        adx_at_decision=brake_adx_at_bar,
                        adx_source=brake_adx_source,
                    )
                    if _blocked_a:
                        logger.info(
                            "[%s] %s %s ARMED STRETCH_BRAKE block: %s",
                            LOG_TAG, symbol, armed_side, _brake_reason_a,
                        )
                        # Armed slot already cleared above (line 988) —
                        # the brake catches the fire that would have
                        # happened; the arm-state is not retained.
                        return None
                except Exception as _brake_exc_a:
                    logger.warning(
                        "[%s] armed stretch_brake raised (fail-open): %s",
                        LOG_TAG, _brake_exc_a,
                    )
                    _brake_rec_armed = {
                        "fail_open": True,
                        "compute_error": str(_brake_exc_a),
                    }

                # ── RANGE GATE (armed-machine fire path) ───────────────
                # Suppress armed EMA_PULLBACK fires inside a range
                # (wide bands + low ER). Direction-agnostic, mode
                # allowlist (GBPUSD_EMA_PULLBACK_L/S). Fail-open.
                _range_rec_armed: Dict[str, Any] = {"called": False}
                try:
                    from guards.range_gate import evaluate as _range_gate
                    _r_blocked_a, _r_reason_a, _range_rec_armed = _range_gate(
                        strategy="EMA_PULLBACK_ARMED",
                        mode=mode,
                        direction=armed_side,
                        bars=bars,
                        last_price=float(lvl),
                        pip_size=PIP_SIZE,
                        symbol=symbol,
                        ts_utc=ts,
                    )
                    if _r_blocked_a:
                        logger.info(
                            "[%s] %s %s ARMED RANGE_GATE suppress: %s",
                            LOG_TAG, symbol, armed_side, _r_reason_a,
                        )
                        return None
                except Exception as _range_exc_a:
                    logger.warning(
                        "[%s] armed range_gate raised (fail-open): %s",
                        LOG_TAG, _range_exc_a,
                    )
                    _range_rec_armed = {
                        "fail_open": True,
                        "compute_error": str(_range_exc_a),
                    }

                debug = {
                    "pattern": "EMA_PULLBACK_ARMED",
                    "direction": armed_side,
                    "armed_ts": current["armed_ts"].isoformat(),
                    "bars_since_arm": int(current["bars_since_arm"]),
                    "trigger_level": round(lvl, 5),
                    "trigger_offset_pips": float(
                        EMA_PB_ARMED_MACHINE_TRIGGER_OFFSET_PIPS
                    ),
                    "ema8":  round(e8,  5),
                    "ema13": round(e13, 5),
                    "ema21": round(e21, 5),
                    "ema50": round(e50, 5),
                    "fan_pips": round(fan_pips, 2),
                    "min_fan_pips": float(MIN_FAN_PIPS),
                    "h1_direction": h1_dir,
                    "htf_h1_state":         _htf_fire["htf_h1_state"],
                    "htf_macd_cross_state": _htf_fire["htf_macd_cross_state"],
                    "htf_alignment":        _htf_fire["htf_alignment"],
                    "shadow_mode": False,
                    "bar_open":  cur_bar.open,
                    "bar_high":  cur_bar.high,
                    "bar_low":   cur_bar.low,
                    "bar_close": cur_bar.close,
                    "trend_stretch_brake": (
                        dict(_brake_rec_armed)
                        if isinstance(_brake_rec_armed, dict) else None
                    ),
                    "range_gate": (
                        dict(_range_rec_armed)
                        if isinstance(_range_rec_armed, dict) else None
                    ),
                }
                reason = (
                    f"ema_pullback_armed_{direction_signal.lower()} "
                    f"stack=ORDERED h1={h1_dir} "
                    f"trigger_lvl={lvl:.5f} "
                    f"(e8{('+' if armed_side == 'LONG' else '-')}"
                    f"{float(EMA_PB_ARMED_MACHINE_TRIGGER_OFFSET_PIPS):.1f}p) "
                    f"fan={fan_pips:.2f}p "
                    f"SL={float(SL_PIPS):.0f}p TP={float(FIXED_RUNNER_TP_PIPS):.0f}p"
                )
                return StrategyDecision(
                    symbol="GBPUSD",
                    regime="EMA_PULLBACK",
                    signal=direction_signal,
                    mode=mode,
                    entry=float(lvl),
                    sl=round(float(SL_PIPS), 2),
                    tp=round(float(FIXED_RUNNER_TP_PIPS), 2),
                    use_trailing_stop=False,
                    reason=reason,
                    debug=debug,
                    pip_size=PIP_SIZE,
                )

        # ── Not currently armed. Arm if preconditions hold AND bar
        #    touches/crosses e8 (wick OR body). ──────────────────────
        if self._armed_machine.get(epic) is None and preconditions_ok:
            # Never arm when same-side slot is already taken.
            slot_taken_at_arm = (
                (trend_side == "LONG"  and has_open_long) or
                (trend_side == "SHORT" and has_open_short)
            )
            if not slot_taken_at_arm:
                if trend_side == "LONG":
                    touch = (cur_bar.low <= e8)
                else:
                    touch = (cur_bar.high >= e8)
                if touch:
                    self._armed_machine[epic] = {
                        "side": trend_side,
                        "armed_ts": cur_bar.timestamp,
                        "armed_e8": float(e8),
                        "armed_e21": float(e21),
                        "armed_h1_dir": h1_dir,
                        "armed_fan_pips": float(fan_pips),
                        "bars_since_arm": 0,
                    }
                    _htf_arm = _ema_pb_htf_snapshot(symbol)
                    _ema_pb_armed_log({
                        "ts": cur_bar.timestamp.isoformat(),
                        "epic": epic,
                        "transition": "ARM",
                        "side": trend_side,
                        "ema8":  round(e8,  5),
                        "ema13": round(e13, 5),
                        "ema21": round(e21, 5),
                        "ema50": round(e50, 5),
                        "fan_pips": round(fan_pips, 2),
                        "min_fan_pips": float(MIN_FAN_PIPS),
                        "h1_dir": h1_dir,
                        "htf_h1_state":         _htf_arm["htf_h1_state"],
                        "htf_macd_cross_state": _htf_arm["htf_macd_cross_state"],
                        "htf_alignment":        _htf_arm["htf_alignment"],
                        "bar_open":  cur_bar.open,
                        "bar_high":  cur_bar.high,
                        "bar_low":   cur_bar.low,
                        "bar_close": cur_bar.close,
                        "shadow_mode": bool(EMA_PB_ARMED_MACHINE_SHADOW),
                    })

        return None

    def _detect(self,
                bars: Sequence[Bar],
                closes_ind: Sequence[float],
                symbol: str = "GBPUSD",
                ) -> Tuple[Optional[_Evidence], str]:
        """Pure detection — returns (evidence, reject_reason). See the
        module docstring for the gate definition. Order is cheap-to-
        expensive so the common no-fire path short-circuits before
        we hit the H1 cache:

          (a) 5M stack ORDERED              — gate 4 (cheapest)
          (b) Entry-bar geometry            — gate 7 (bearish + close<ema8)
          (c) Pullback START (most recent
              high≥ema8 walking back from
              B-1)                          — gate 5
          (d) Whole-pullback invalidation
              walk [start, B-1] inclusive   — gate 6 (Johnny rule)
          (e) Band-trail context            — gate 3
          (f) H1 direction + fan floor      — gates 1, 2 (lazy, last)

        ⚠️ No 5M fan-width gate anywhere. A pullback bunches the 5M
        EMAs by nature; width is checked on H1 only (gate 2)."""
        n_closes = len(closes_ind)
        if n_closes < max(BB_PERIOD + 5, WARMUP_BARS, TRAIL_LOOKBACK_BARS + 5, 30):
            return None, "warmup"
        if len(bars) < TRAIL_MIN_AGO_BARS + 2:
            return None, "no_bars"

        i = n_closes - 1  # absolute index of the entry candidate (bar B)

        # EMA series across full close history.
        e8  = _ema(closes_ind, 8)
        e13 = _ema(closes_ind, 13)
        e21 = _ema(closes_ind, 21)
        e50 = _ema(closes_ind, 50)

        cur_bar = bars[-1]

        # Gate 1: 5M stack ORDERED + direction. NO fan-width check —
        # a real pullback compresses the stack, so width on the 5M is
        # an anti-signal here.
        is_bull = (e8[i] > e13[i] > e21[i] > e50[i])
        is_bear = (e8[i] < e13[i] < e21[i] < e50[i])
        if not (is_bull or is_bear):
            return None, "stack_not_ordered"
        direction = "LONG" if is_bull else "SHORT"

        # 5M EMA8-EMA50 spread (signed by direction). Was reporting-only;
        # now feeds the FAN_GATE below when FAN_GATE_ENABLED.
        fan_p = (e8[i] - e50[i]) / PIP_SIZE if is_bull else (e50[i] - e8[i]) / PIP_SIZE

        # ── 5M fan-width gate (BLOCKING, added 2026-06-01) ──────────────
        # Inverts the prior "no 5M fan-width gate" stance. Justification
        # — 2026-06-01 fills: losers #2 (fan=4.80p, squeeze), #5 (2.41p),
        # #8 (1.33p, squeeze) all sat at thin fan and/or in squeeze;
        # winner #11 (4.75p, no squeeze) cleared both. Default 3.0p clears
        # #11 with margin and blocks #5/#8 outright; co-condition on
        # BB squeeze catches #2's slightly-above-threshold fan.
        #
        # Squeeze rule mirrors signal_logger._bb_squeeze: current BB(20,2)
        # width < mean BB width over the trailing SQUEEZE_LOOKBACK_BARS
        # bars. Defensive: if BB width can't be computed (warmup), squeeze
        # is False (gate stays permissive on the squeeze axis).
        bb_lo_now, _, bb_up_now = _bb_at(closes_ind, i)
        bb_width_now_pips: float = 0.0
        bb_squeeze_now: bool = False
        if bb_lo_now is not None and bb_up_now is not None:
            bb_width_now_pips = float(bb_up_now - bb_lo_now) / PIP_SIZE
            lookback = max(1, min(int(SQUEEZE_LOOKBACK_BARS), i + 1 - BB_PERIOD + 1))
            widths_pips: List[float] = []
            for k in range(lookback):
                idx_k = i - k
                if idx_k < BB_PERIOD - 1:
                    break
                bbl_k, _, bbu_k = _bb_at(closes_ind, idx_k)
                if bbl_k is None or bbu_k is None:
                    continue
                widths_pips.append(float(bbu_k - bbl_k) / PIP_SIZE)
            if widths_pips:
                mean_w = sum(widths_pips) / len(widths_pips)
                if mean_w > 0:
                    bb_squeeze_now = bb_width_now_pips < mean_w

        if FAN_GATE_ENABLED:
            if fan_p < float(MIN_FAN_PIPS):
                return None, (f"fan_too_narrow fan={fan_p:.2f}p<"
                              f"{float(MIN_FAN_PIPS):.2f}p")
            if bb_squeeze_now:
                return None, (f"bb_squeeze width={bb_width_now_pips:.2f}p"
                              f"<mean over {SQUEEZE_LOOKBACK_BARS}b")

        # ── Gate 7 — entry bar geometry ─────────────────────────────────
        # When EMA_PB_PULLBACK_FIX_ENABLED=0: the LEGACY trigger
        # (bullish/bearish body + close past ema8). Byte-identical to today.
        # When EMA_PB_PULLBACK_FIX_ENABLED=1: Johnny's pullback-fix
        # geometry — wick-into-ribbon trigger + close-stays-the-right-side-
        # of-ema21 (continuation rejection) + BB band guard + regime gate +
        # H1 steepness (fan AND slope). The legacy "body + close>ema8"
        # also stays as a baseline trigger underneath the new gates: a
        # pullback recovery still requires a bullish close above ema8 (LONG)
        # / bearish close below ema8 (SHORT). The new gates add the
        # missing "this candle IS the pullback, not the extension" tests.
        entry_body = cur_bar.close - cur_bar.open
        if not EMA_PB_PULLBACK_FIX_ENABLED:
            # LEGACY PATH — byte-identical to pre-2026-06-26 behaviour.
            if is_bear:
                if entry_body >= 0:
                    return None, "entry_bar_not_bearish"
                if cur_bar.close >= e8[i]:
                    return None, "entry_close_not_below_ema8"
            else:
                if entry_body <= 0:
                    return None, "entry_bar_not_bullish"
                if cur_bar.close <= e8[i]:
                    return None, "entry_close_not_above_ema8"
        else:
            # PULLBACK-FIX PATH (2026-06-26, revised). Order is
            # cheap-to-expensive. Step labels mirror the spec.
            #
            # Step 1 — STRONG TREND via regime classifier. The H1-MACD
            # classifier (commit 8a6334c) encodes "steep + building" as
            # STRONG_TREND, so this single label carries the trend-context
            # requirement. No EMA fan/slope pip number anywhere on this
            # path — H1 EMA fan on GBPUSD is sub-pip and unsuited to a
            # pip floor. Fail-CLOSED on missing/unknown regime.
            _reg = _ema_pb_read_regime_label(symbol)
            if EMA_PB_REGIME_REQUIRE_STRONG:
                _long_ok  = _reg in _EMA_PB_LONG_REGIMES_STRICT
                _short_ok = _reg in _EMA_PB_SHORT_REGIMES_STRICT
                _mode     = "strict"
            else:
                _long_ok  = _reg in _EMA_PB_LONG_REGIMES_WIDE
                _short_ok = _reg in _EMA_PB_SHORT_REGIMES_WIDE
                _mode     = "wide"
            # Under the matrix (REGIME_MATRIX_ENABLED=1) the effective_regime
            # decides enablement; this local strict-STRONG check is bypassed.
            if (is_bull and not _long_ok) or (is_bear and not _short_ok):
                if not _REGIME_MATRIX_ENABLED:
                    _ema_pb_pbfix_log({
                        "ts": cur_bar.timestamp.isoformat(),
                        "verdict": "REJECT",
                        "reason": "regime_not_strong_trend",
                        "direction": ("LONG" if is_bull else "SHORT"),
                        "winning_regime": _reg,
                        "regime_mode": _mode,
                    })
                    return None, f"regime_not_strong_trend regime={_reg} mode={_mode}"

            # Step 2 — STACK ORDERED: already enforced upstream by the
            # is_bull / is_bear gate ("stack_not_ordered" return). Nothing
            # extra here; recorded for symmetry with the spec.

            # Step 3 — TRIGGER: entry bar WICK crosses INTO the ribbon.
            #   LONG : cur_bar.low  <= ema8[i] OR cur_bar.low  <= ema13[i]
            #   SHORT: cur_bar.high >= ema8[i] OR cur_bar.high >= ema13[i]
            if is_bull:
                _wick_into_ribbon = (cur_bar.low <= e8[i]) or (cur_bar.low <= e13[i])
            else:
                _wick_into_ribbon = (cur_bar.high >= e8[i]) or (cur_bar.high >= e13[i])
            if not _wick_into_ribbon:
                _ema_pb_pbfix_log({
                    "ts": cur_bar.timestamp.isoformat(),
                    "verdict": "REJECT", "reason": "no_ribbon_pullback",
                    "direction": ("LONG" if is_bull else "SHORT"),
                    "low": cur_bar.low, "high": cur_bar.high,
                    "ema8": e8[i], "ema13": e13[i],
                })
                return None, (f"no_ribbon_pullback "
                              f"low={cur_bar.low:.2f} high={cur_bar.high:.2f} "
                              f"ema8={e8[i]:.2f} ema13={e13[i]:.2f}")

            # Step 4 — HELD PULLBACK: close stays on the right side of ema21.
            #   LONG : cur_bar.close > ema21[i]
            #   SHORT: cur_bar.close < ema21[i]
            if is_bull and cur_bar.close <= e21[i]:
                _ema_pb_pbfix_log({
                    "ts": cur_bar.timestamp.isoformat(),
                    "verdict": "REJECT", "reason": "closed_through_stack",
                    "direction": "LONG",
                    "close": cur_bar.close, "ema21": e21[i],
                })
                return None, (f"closed_through_stack close={cur_bar.close:.2f}"
                              f"<=ema21={e21[i]:.2f}")
            if is_bear and cur_bar.close >= e21[i]:
                _ema_pb_pbfix_log({
                    "ts": cur_bar.timestamp.isoformat(),
                    "verdict": "REJECT", "reason": "closed_through_stack",
                    "direction": "SHORT",
                    "close": cur_bar.close, "ema21": e21[i],
                })
                return None, (f"closed_through_stack close={cur_bar.close:.2f}"
                              f">=ema21={e21[i]:.2f}")

            # (Step 5 BAND GUARD removed 2026-06-26 — see env-block comment
            # above. Continuation filter is the 21-EMA close-hold in Step 4.)

            # Body/recovery sanity (preserved from legacy): bullish bar
            # closing above ema8 for LONG, bearish bar closing below ema8
            # for SHORT. The pullback fire IS a recovery candle.
            if is_bear:
                if entry_body >= 0:
                    return None, "entry_bar_not_bearish"
                if cur_bar.close >= e8[i]:
                    return None, "entry_close_not_below_ema8"
            else:
                if entry_body <= 0:
                    return None, "entry_bar_not_bullish"
                if cur_bar.close <= e8[i]:
                    return None, "entry_close_not_above_ema8"
            _ema_pb_pbfix_log({
                "ts": cur_bar.timestamp.isoformat(),
                "verdict": "PASS",
                "direction": ("LONG" if is_bull else "SHORT"),
                "close": cur_bar.close, "open": cur_bar.open,
                "low": cur_bar.low, "high": cur_bar.high,
                "ema8": e8[i], "ema13": e13[i], "ema21": e21[i],
                "bbU": float(bb_up_now) if bb_up_now is not None else None,
                "bbL": float(bb_lo_now) if bb_lo_now is not None else None,
                "winning_regime": _reg,
                "regime_mode": _mode,
            })

        # Gate 5: Pullback START — walking back from B-1 (the bar
        # before entry), find the most recent bar whose HIGH ≥ ema8
        # (SHORT) / LOW ≤ ema8 (LONG). That bar marks the most recent
        # time price touched up into / down into the ribbon before
        # the entry. Earlier ribbon touches belong to separate
        # pullback attempts (potentially older, potentially already
        # failed) and are NOT in this window.
        #
        # If no such bar exists in the LOOKBACK_BARS window, no
        # pullback happened and the setup doesn't qualify.
        n_pb_back = min(LOOKBACK_BARS, len(bars) - 1)
        pullback_start_abs: Optional[int] = None
        for k in range(1, n_pb_back + 1):
            abs_k = i - k
            if abs_k < 0:
                break
            local_k = len(bars) - 1 - k
            if local_k < 0:
                break
            bar_k = bars[local_k]
            if is_bear:
                if bar_k.high >= e8[abs_k]:
                    pullback_start_abs = abs_k
                    break
            else:
                if bar_k.low <= e8[abs_k]:
                    pullback_start_abs = abs_k
                    break
        if pullback_start_abs is None:
            return None, "no_pullback_into_ribbon"

        # Gate 6: Whole-pullback INVALIDATION + peak tracking.
        # Every bar from pullback_start through B-1 (both inclusive)
        # must satisfy bar.LOW ≤ ema21 (SHORT) / bar.HIGH ≥ ema21
        # (LONG). One bar fully clearing ema21 → setup DEAD.
        # ascent leg is NOT exempt — Johnny's rule: "if it closes
        # above the 21 EMA it isn't a pullback any more."
        # Peak (most extreme excursion within the window) is tracked
        # for reporting only — not used for invalidation.
        pullback_peak_abs = pullback_start_abs
        _start_bar = bars[len(bars) - 1 - (i - pullback_start_abs)]
        pullback_peak_price = (_start_bar.high if is_bear
                               else _start_bar.low)
        for abs_k in range(pullback_start_abs, i):
            local_k = len(bars) - 1 - (i - abs_k)
            if local_k < 0 or local_k >= len(bars):
                continue
            bar_k = bars[local_k]
            if is_bear:
                if bar_k.low > e21[abs_k]:
                    return None, (f"pullback_low_above_ema21 "
                                  f"bar@i-{i-abs_k}.low={bar_k.low:.2f}"
                                  f">ema21={e21[abs_k]:.2f}")
                if bar_k.high > pullback_peak_price:
                    pullback_peak_price = bar_k.high
                    pullback_peak_abs = abs_k
            else:
                if bar_k.high < e21[abs_k]:
                    return None, (f"pullback_high_below_ema21 "
                                  f"bar@i-{i-abs_k}.high={bar_k.high:.2f}"
                                  f"<ema21={e21[abs_k]:.2f}")
                if bar_k.low < pullback_peak_price:
                    pullback_peak_price = bar_k.low
                    pullback_peak_abs = abs_k

        # Gate 3 (band-trailing context): in last TRAIL_LOOKBACK_BARS
        # before the entry, the lowest bar low (SHORT) must (a) be within
        # TRAIL_BAND_TOL_PIPS of bbL at that bar AND (b) sit at least
        # TRAIL_MIN_AGO_BARS bars before the entry. (LONG mirror: highest
        # bar high vs bbU.) (b) is what rejects the snap-back-from-fresh-
        # extreme geometry — if the lowest low IS the last few bars, we
        # do not have a "trailed-then-pulled-back" context, we have a
        # "still-extending" one.
        n_trail_back = min(TRAIL_LOOKBACK_BARS, len(bars) - 1)
        trail_extreme_abs: Optional[int] = None
        trail_extreme_price: float = float("inf") if is_bear else float("-inf")
        for k in range(1, n_trail_back + 1):
            abs_k = i - k
            if abs_k < 0:
                break
            local_k = len(bars) - 1 - k
            if local_k < 0:
                break
            bar_k = bars[local_k]
            if is_bear:
                if bar_k.low < trail_extreme_price:
                    trail_extreme_price = bar_k.low
                    trail_extreme_abs = abs_k
            else:
                if bar_k.high > trail_extreme_price:
                    trail_extreme_price = bar_k.high
                    trail_extreme_abs = abs_k
        if trail_extreme_abs is None:
            return None, "no_trail_extreme_in_window"

        trail_ago = i - trail_extreme_abs
        if trail_ago < TRAIL_MIN_AGO_BARS:
            return None, (f"trail_extreme_too_recent "
                          f"ago={trail_ago}b<{TRAIL_MIN_AGO_BARS}b")

        # Band proximity at the trail-extreme bar.
        bbL_t, _bbM_t, bbU_t = _bb_at(closes_ind, trail_extreme_abs)
        if bbL_t is None or bbU_t is None:
            return None, "trail_bb_unavailable"
        if is_bear:
            band_proximity = trail_extreme_price - bbL_t  # +ve = above band, -ve = pierced below
        else:
            band_proximity = bbU_t - trail_extreme_price
        if band_proximity > TRAIL_BAND_TOL_PIPS:
            return None, (f"trail_extreme_not_near_band "
                          f"proximity={band_proximity:.2f}p>{TRAIL_BAND_TOL_PIPS:.2f}p")

        # Gate H1 (direction + fan). Lazy import — only invoked once all
        # 5M gates have passed. Required, not soft.
        #   - direction must match the 5M side (BEARISH for SHORT,
        #     BULLISH for LONG).
        #   - |ema8 − ema21| in pips must clear H1_SEP_MIN_PIPS (default
        #     2.0p). The function's own flat threshold is 0.5p; we sit
        #     above that floor for a real H1 commit.
        h1 = self._h1_direction()
        if h1 is None or "direction" not in h1:
            return None, "h1_unavailable"
        h1_dir = str(h1.get("direction") or "").upper()
        h1_sep_pips = float(h1.get("separation_pips") or 0.0)

        # ── M5 OVERRIDE on the H1 direction veto (2026-05-28) ───────────
        # Compute it BEFORE the direction-mismatch return so we can bypass
        # the veto when the M5 evidence is unambiguous. The override does
        # NOT bypass the H1 sep-floor below; only the direction match.
        # Conditions (ALL must hold; otherwise default H1 veto applies):
        #   1. regime_engine.latest_result winning_regime == STRONG_TREND_UP
        #      for LONG (STRONG_TREND_DOWN for SHORT). TREND_FORMING_* does
        #      NOT qualify — must be the strong regime.
        #   2. EMA_STACK ordered AND aligned in trade direction (already
        #      enforced by `is_bull`/`is_bear` upstream, but re-asserted via
        #      regime_engine's EMA_STACK_STATE for consistency).
        #   3. EMA50 slope same sign as direction AND accelerating
        #      (|current slope| > |prior slope| with matching sign).
        #   4. directional_bias matches (LONG for is_bull / SHORT for is_bear).
        # Slope source: regime_engine's published EMA_50_SLOPE (the same
        # value the investigation used). Falls back to None when the
        # regime cache is empty — override won't fire in that case.
        override_fires = False
        _cur_slope: Optional[float] = None
        _prev_slope = self._prev_ema50_slope_by_pair.get(str(symbol).upper())
        if H1_OVERRIDE_ENABLED and (
            (is_bull and h1_dir != "BULLISH") or
            (is_bear and h1_dir != "BEARISH")
        ):
            try:
                import regime_engine as _re
                _rg = _re.latest_result(symbol)
            except Exception:
                _rg = None
            if _rg is not None:
                _winning = str(_rg.get("winning_regime") or "").upper()
                _dbias = str(_rg.get("directional_bias") or "").upper()
                _stack = str(_rg.get("EMA_state") or "").upper()
                _ff = _rg.get("full_features") or {}
                _rg_slope = _ff.get("EMA_50_SLOPE")
                if _rg_slope is not None:
                    try:
                        _cur_slope = float(_rg_slope)
                    except (TypeError, ValueError):
                        _cur_slope = None
                _want_regime = "STRONG_TREND_UP" if is_bull else "STRONG_TREND_DOWN"
                _want_stack = "BULL_ALIGNED" if is_bull else "BEAR_ALIGNED"
                _want_bias = "LONG" if is_bull else "SHORT"
                _slope_sign_ok = (
                    _cur_slope is not None
                    and ((_cur_slope > 0) if is_bull else (_cur_slope < 0))
                )
                _accel_ok = (
                    _cur_slope is not None
                    and _prev_slope is not None
                    and (
                        (is_bull and _cur_slope > _prev_slope) or
                        (is_bear and _cur_slope < _prev_slope)
                    )
                )
                if (
                    _winning == _want_regime
                    and _dbias == _want_bias
                    and _stack == _want_stack
                    and _slope_sign_ok
                    and _accel_ok
                ):
                    override_fires = True
                    logger.info(
                        "[H1_OVERRIDE] pair=%s dir=%s regime=%s stack=%s "
                        "ema50_slope=%.4f (prev=%.4f accel=%s) h1_was=%s "
                        "— H1 veto bypassed",
                        symbol, ("LONG" if is_bull else "SHORT"),
                        _winning, _stack, _cur_slope,
                        (_prev_slope if _prev_slope is not None else float("nan")),
                        _accel_ok, h1_dir,
                    )
        # Snapshot slope for next cycle's acceleration check (every call,
        # regardless of override outcome, so the comparator stays current).
        # Only update if we actually have a fresh regime slope; otherwise
        # leave the prior snapshot in place.
        if _cur_slope is not None:
            self._prev_ema50_slope_by_pair[str(symbol).upper()] = _cur_slope

        if not override_fires:
            if is_bear and h1_dir != "BEARISH":
                return None, f"h1_not_bearish h1={h1_dir}"
            if is_bull and h1_dir != "BULLISH":
                return None, f"h1_not_bullish h1={h1_dir}"
        if abs(h1_sep_pips) < H1_SEP_MIN_PIPS:
            return None, (f"h1_sep_too_small |sep|={abs(h1_sep_pips):.2f}p<"
                          f"{H1_SEP_MIN_PIPS:.2f}p")

        # ── Runner-TP geometry (UNCHANGED computation). Use the trail-
        # extreme's band price as the origin-band reference (replaces the
        # old band_touch_price). ──────────────────────────────────────
        entry_px = float(cur_bar.close)
        if RUNNER_TARGET_MODE == "fixed":
            runner_tp_pips = float(FIXED_RUNNER_TP_PIPS)
        else:
            if is_bull:
                raw = (float(bbU_t) - entry_px) / PIP_SIZE
            else:
                raw = (entry_px - float(bbL_t)) / PIP_SIZE
            runner_tp_pips = max(RUNNER_TP_MIN_PIPS,
                                 min(RUNNER_TP_MAX_PIPS, raw))

        # Current-bar BB for reporting.
        bb_lo, bb_mid, bb_up = _bb_at(closes_ind, i)
        if bb_lo is None or bb_mid is None or bb_up is None:
            return None, "bb_unavailable"

        ev = _Evidence(
            direction=direction,
            fan_pips=round(fan_p, 2),
            bb_width_pips=round(bb_width_now_pips, 2),
            bb_squeeze=bool(bb_squeeze_now),
            h1_direction=h1_dir,
            h1_separation_pips=round(float(h1.get("separation_pips") or 0.0), 2),
            pullback_start_offset_bars=(i - pullback_start_abs),
            pullback_peak_offset_bars=(i - pullback_peak_abs),
            pullback_peak_price=float(pullback_peak_price),
            trail_extreme_offset_bars=trail_ago,
            trail_extreme_price=float(trail_extreme_price),
            trail_band_proximity_pips=round(band_proximity, 2),
            entry_bar_body_pips=round(abs(entry_body) / PIP_SIZE, 2),
            runner_tp_pips=round(runner_tp_pips, 2),
            ema8=e8[i], ema13=e13[i], ema21=e21[i], ema50=e50[i],
            bb_lower=bb_lo, bb_mid=bb_mid, bb_upper=bb_up,
        )
        return ev, ""

    def evaluate(self,
                 symbol: str,
                 epic: str,
                 ts: datetime,
                 bars: Sequence[Bar],
                 closes_ind: Sequence[float],
                 has_open_long: bool = False,
                 has_open_short: bool = False,
                 highs_ind: Optional[Sequence[float]] = None,
                 lows_ind: Optional[Sequence[float]] = None,
                 brake_adx_at_bar: Optional[float] = None,
                 brake_adx_source: Optional[str] = None,
                 ) -> Optional["StrategyDecision"]:
        """Called on each new 5m close for GBPUSD. Returns a
        StrategyDecision when the setup + all three filters pass."""
        # 2026-06-28: split the master gate so the legacy _detect path and
        # the armed-state machine can be toggled independently. evaluate()
        # proceeds when EITHER path is enabled; the legacy block has its own
        # ENABLED-only guard below (just before _detect is called).
        if (not ENABLED and not EMA_PB_ARMED_MACHINE_ENABLED) or str(symbol).upper() != "GBPUSD":
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        if not self._in_window(ts):
            return None

        # ── VWAP-stretch brake ADX + source (sourced upstream) ───────────
        # 2026-07-22: sourced ONCE per bar in autobot._source_brake_adx_
        # at_bar and passed in via kwargs. No latest_result() call happens
        # here. Callers that don't supply the kwargs (legacy tick-driven,
        # router self-dispatch) leave both None → the brake's ADX-floor
        # gate takes the blocked_adx_unavailable_failsafe path → BLOCK.
        # Local aliases keep the downstream code below unchanged.
        _brake_adx_at_bar: Optional[float] = brake_adx_at_bar
        _brake_adx_source: Optional[str] = brake_adx_source

        # ── ARMED-STATE ENTRY MACHINE (2026-06-27) ──────────────────────
        # Default OFF. When enabled, advances state on every in-session
        # 5m close: ARM on 8-EMA touch (preconditions); DISARM on close
        # past 21-EMA or preconditions lost; FIRE on a bar that traded
        # THROUGH e8±2p. Legacy _detect path BELOW is UNTOUCHED — when
        # EMA_PB_ARMED_MACHINE_ENABLED=0 the call returns None
        # immediately and the legacy fire path is byte-identical to
        # pre-2026-06-27 behaviour. In shadow mode (the on-by-default
        # mode when the machine is enabled) the call NEVER returns a
        # decision — every transition is logged to
        # logs/ema_pb_armed_machine.jsonl and we fall through to legacy.
        # Only when ENABLED=1 AND SHADOW=0 can the machine return a
        # decision; cooldown is checked AFTER (shared with legacy) so
        # a machine fire still respects the same per-epic interval.
        # 2026-07-28: EMA_PB_DETECT_MODE=1 (default) retires the armed
        # machine — the step is not called, telemetry stops, and the
        # legacy _detect path (with WIDE regime gate) is the sole entry
        # route. Flip DETECT_MODE=0 to fall back to the pre-2026-07-28
        # armed-machine behaviour (still gated by EMA_PB_ARMED_MACHINE_
        # ENABLED).
        armed_machine_decision: Optional["StrategyDecision"] = None
        if EMA_PB_ARMED_MACHINE_ENABLED and not EMA_PB_DETECT_MODE:
            try:
                armed_machine_decision = self._armed_machine_step(
                    epic=epic, ts=ts, bars=bars, closes_ind=closes_ind,
                    symbol=symbol,
                    has_open_long=has_open_long,
                    has_open_short=has_open_short,
                    brake_adx_at_bar=_brake_adx_at_bar,
                    brake_adx_source=_brake_adx_source,
                )
            except Exception as _amm_exc:
                logger.warning(
                    "[%s] armed_machine_step raised: %s — fail-open, "
                    "legacy path continues",
                    LOG_TAG, _amm_exc,
                )

        if not self._cooldown_ok(epic, ts):
            return None

        # The machine's decision (live mode only) short-circuits the
        # legacy detect+gates for this bar. Stamp cooldown so the
        # machine respects the same inter-fire interval as legacy.
        if armed_machine_decision is not None:
            self._last_fire_ts_by_epic[epic] = ts
            logger.info(
                "[%s] %s ARMED_MACHINE fire %s @ %.5f | SL=%.0fp TP=%.1fp | %s",
                LOG_TAG, symbol,
                armed_machine_decision.signal,
                float(armed_machine_decision.entry),
                float(armed_machine_decision.sl),
                float(armed_machine_decision.tp),
                armed_machine_decision.reason,
            )
            return armed_machine_decision

        # Legacy _detect path — only runs when the legacy strategy is
        # enabled. When ENABLED=0 and the armed machine did not fire on
        # this bar, return None so legacy fires never reach dispatch.
        if not ENABLED:
            return None

        ev, reject = self._detect(bars, closes_ind, symbol=symbol)
        if ev is None:
            if reject:
                logger.debug("[%s] %s skip: %s", LOG_TAG, symbol, reject)
            return None

        direction_signal = "BUY" if ev.direction == "LONG" else "SELL"
        mode = MODE_NAME_LONG if ev.direction == "LONG" else MODE_NAME_SHORT

        # ── REGIME ELIGIBILITY GATE (legacy detect fire path) ──────────
        # Layered ON TOP of the existing gate stack as an ADDITIONAL live
        # precondition (2026-07-28, armed-machine retirement — detect-
        # and-fire runs under the SAME WIDE regime gate the armed path
        # used, per operator spec). Reuses _EMA_PB_LONG/SHORT_REGIMES_
        # WIDE frozensets and _ema_pb_read_regime_label — the SAME
        # regime_engine.latest_result → winning_regime read the armed-
        # machine gate, BB_BOUNCE, TREND_V3, and signal_logger consume.
        # Fail-OPEN on missing/null label so a classifier hiccup never
        # silences the strategy. Placed before slot/news/momentum/
        # trend-gate stack so a blocking regime skips the expensive
        # downstream work.
        if EMA_PB_REGIME_GATE_MODE == "enforce":
            _reg_gate_label = _ema_pb_read_regime_label(symbol)
            if _reg_gate_label is None:
                logger.info(
                    "[EMA-PB-REGIME-GATE] verdict=PASS regime=NULL "
                    "dir=%s path=detect reason=failopen mode=enforce",
                    ev.direction,
                )
            else:
                if ev.direction == "LONG":
                    _reg_gate_ok = (
                        _reg_gate_label in _EMA_PB_LONG_REGIMES_WIDE
                    )
                else:
                    _reg_gate_ok = (
                        _reg_gate_label in _EMA_PB_SHORT_REGIMES_WIDE
                    )
                if _reg_gate_ok:
                    logger.info(
                        "[EMA-PB-REGIME-GATE] verdict=PASS regime=%s "
                        "dir=%s path=detect mode=enforce",
                        _reg_gate_label, ev.direction,
                    )
                else:
                    logger.info(
                        "[EMA-PB-REGIME-GATE] verdict=BLOCK regime=%s "
                        "dir=%s path=detect mode=enforce",
                        _reg_gate_label, ev.direction,
                    )
                    return None

        # Slot enforcement.
        if direction_signal == "BUY" and has_open_long:
            logger.debug("[%s] %s LONG fire suppressed: slot taken", LOG_TAG, symbol)
            return None
        if direction_signal == "SELL" and has_open_short:
            logger.debug("[%s] %s SHORT fire suppressed: slot taken", LOG_TAG, symbol)
            return None

        # News blackout.
        is_black, why = _is_pre_news_blackout(ts)
        if is_black:
            logger.info("[%s] %s %s fire suppressed: %s",
                        LOG_TAG, symbol, ev.direction, why)
            return None

        # News release window — symmetric [-PRE,+POST] gate on HIGH GBP/USD.
        # Complements the strictly-pre-event helper above; block-entries-only.
        try:
            # Log-only staleness alert (ITEM 1c, 2026-07-25). Behaviour
            # unchanged; consumer already fails OPEN on missing cache.
            import news_calendar_health as _nch
            _nch.warn_once_if_stale("gbpusd_ema_pullback")
        except Exception:
            pass
        try:
            from news_release_window import is_in_release_window
            _nrw_blocked, _nrw_reason = is_in_release_window(ts)
            if _nrw_blocked:
                logger.info(
                    "[NEWS_WINDOW_BLOCK] strategy=GBPUSD_EMA_PULLBACK %s %s reason=%s",
                    symbol, ev.direction, _nrw_reason,
                )
                return None
        except Exception:
            pass  # fail-open on suppressor error

        # ── Momentum-direction SHADOW gate (added 2026-06-24) ──────────
        # Computes 4 components from the same closes_ind / evidence the
        # geometry gates used. Default SHADOW=on, ENFORCE=off: logs the
        # would-block verdict, blocks nothing. Flipping ENFORCE=1 turns
        # this into a real gate — no rebuild required.
        entry_px = float(bars[-1].close)
        shadow_rec: Optional[Dict[str, Any]] = None
        shadow_would_fire: Optional[bool] = None
        shadow_block_reasons: List[str] = []
        if MOMENTUM_GATE_SHADOW_ENABLED or MOMENTUM_GATE_ENFORCE:
            try:
                i = len(closes_ind) - 1
                rsi_lb = max(1, int(MOM_RSI_LOOKBACK))
                macd_lb = max(1, int(MOM_MACD_LOOKBACK))
                rsi_p = max(2, int(MOM_RSI_PERIOD))
                macd_fast = max(2, int(MOM_MACD_FAST))
                macd_slow = max(macd_fast + 1, int(MOM_MACD_SLOW))
                macd_sig = max(1, int(MOM_MACD_SIGNAL))
                need = max(rsi_p + rsi_lb + 1, macd_slow + macd_sig + macd_lb + 1)
                if i + 1 < need:
                    shadow_rec = {"shadow_warmup_skip": True, "have": i + 1, "need": need}
                else:
                    rsi_series = _rsi_wilder(closes_ind, rsi_p)
                    hist_series = _macd_hist(closes_ind, macd_fast, macd_slow, macd_sig)
                    rsi_now = float(rsi_series[i])
                    rsi_then = float(rsi_series[i - rsi_lb])
                    hist_now = float(hist_series[i])
                    hist_then = float(hist_series[i - macd_lb])
                    rsi_delta_raw = rsi_now - rsi_then
                    macd_slope_raw = hist_now - hist_then
                    sign = 1.0 if ev.direction == "LONG" else -1.0
                    rsi_delta_in_dir = sign * rsi_delta_raw
                    macd_slope_in_dir = sign * macd_slope_raw
                    # Decisive entry candle: close past ema8 in pips (signed
                    # in direction; gate 7 already guarantees the correct
                    # side, so this is just an absolute-magnitude check).
                    dist_e8_pips_raw = (entry_px - float(ev.ema8)) / PIP_SIZE
                    dist_e8_pips_in_dir = sign * dist_e8_pips_raw
                    # leg_run: trail-extreme (band-low SHORT / band-high
                    # LONG, gate-3-validated) to entry, in pips. Always
                    # positive by gate-3 geometry but use abs() defensively.
                    leg_run_pips = abs(entry_px - float(ev.trail_extreme_price)) / PIP_SIZE

                    shadow_momentum_ok = (rsi_delta_in_dir > 0.0) and (macd_slope_in_dir > 0.0)
                    shadow_decisive_ok = (dist_e8_pips_in_dir >= float(DECISIVE_MIN_PIPS))
                    shadow_leg_ok = (leg_run_pips <= float(LEG_RUN_MAX_PIPS))
                    shadow_would_fire = bool(
                        shadow_momentum_ok and shadow_decisive_ok and shadow_leg_ok
                    )
                    if not shadow_momentum_ok:
                        if rsi_delta_in_dir <= 0.0:
                            shadow_block_reasons.append(
                                f"rsi_delta_in_dir={rsi_delta_in_dir:+.3f}<=0"
                            )
                        if macd_slope_in_dir <= 0.0:
                            shadow_block_reasons.append(
                                f"macd_slope_in_dir={macd_slope_in_dir:+.5f}<=0"
                            )
                    if not shadow_decisive_ok:
                        shadow_block_reasons.append(
                            f"dist_e8={dist_e8_pips_in_dir:+.2f}p<{float(DECISIVE_MIN_PIPS):.2f}p"
                        )
                    if not shadow_leg_ok:
                        shadow_block_reasons.append(
                            f"leg_run={leg_run_pips:.2f}p>{float(LEG_RUN_MAX_PIPS):.2f}p"
                        )

                    shadow_rec = {
                        "shadow_would_fire": shadow_would_fire,
                        "shadow_momentum_ok": shadow_momentum_ok,
                        "shadow_decisive_ok": shadow_decisive_ok,
                        "shadow_leg_ok": shadow_leg_ok,
                        "rsi_now": round(rsi_now, 3),
                        "rsi_then": round(rsi_then, 3),
                        "rsi_delta_raw": round(rsi_delta_raw, 3),
                        "rsi_delta_in_dir": round(rsi_delta_in_dir, 3),
                        "rsi_lookback_bars": rsi_lb,
                        "rsi_period": rsi_p,
                        "macd_hist_now": round(hist_now, 5),
                        "macd_hist_then": round(hist_then, 5),
                        "macd_slope_raw": round(macd_slope_raw, 5),
                        "macd_slope_in_dir": round(macd_slope_in_dir, 5),
                        "macd_lookback_bars": macd_lb,
                        "macd_fast": macd_fast,
                        "macd_slow": macd_slow,
                        "macd_signal": macd_sig,
                        "dist_e8_pips_in_dir": round(dist_e8_pips_in_dir, 2),
                        "decisive_min_pips": float(DECISIVE_MIN_PIPS),
                        "leg_run_pips": round(leg_run_pips, 2),
                        "leg_run_max_pips": float(LEG_RUN_MAX_PIPS),
                        "shadow_block_reasons": list(shadow_block_reasons),
                        "shadow_enforce": bool(MOMENTUM_GATE_ENFORCE),
                    }
            except Exception as _shadow_exc:
                logger.warning(
                    "[%s] momentum_shadow compute failed: %s", LOG_TAG, _shadow_exc,
                )
                shadow_rec = {"shadow_compute_error": str(_shadow_exc)}

        # Enforce path: when ENFORCE=1 AND shadow verdict is False, block
        # the entry before the decision is built. Default ENFORCE=0 means
        # we never reach the block branch — the trade fires as today.
        # Defensive: an unresolved verdict (warmup / compute error) does
        # NOT block — fail-open. Promotion-time policy can tighten this.
        if MOMENTUM_GATE_ENFORCE and shadow_would_fire is False:
            logger.info(
                "[%s] %s %s ENFORCE block: %s",
                LOG_TAG, symbol, ev.direction,
                ", ".join(shadow_block_reasons) or "shadow_false",
            )
            # Still emit the shadow row so we can audit what got blocked.
            if MOMENTUM_GATE_SHADOW_ENABLED:
                _write_momentum_shadow({
                    "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "pair": "GBPUSD",
                    "epic": epic,
                    "direction": ev.direction,
                    "entry_px": round(entry_px, 5),
                    "fired_live": False,
                    "enforced_block": True,
                    "trail_extreme_price": float(ev.trail_extreme_price),
                    "ema8": round(float(ev.ema8), 5),
                    "h1_direction": ev.h1_direction,
                    **(shadow_rec or {}),
                })
            return None

        # ── TREND_ENTRY_GATE (LIVE enforce, added 2026-06-25) ───────────
        # Two-leg hard gate. Highs/lows fall back to extracting from bars
        # if the dispatch hasn't been extended (back-compat shim) — the
        # gate will warmup_skip + fail-open if the resulting series is
        # too short for clean MACD warmup (default min 200 bars).
        trend_gate_rec: Optional[Dict[str, Any]] = None
        try:
            import trend_entry_gate as _teg
            if _teg.ENABLED:
                if highs_ind is None or lows_ind is None:
                    _highs_in = [float(b.high) for b in bars]
                    _lows_in = [float(b.low) for b in bars]
                else:
                    _highs_in = list(highs_ind)
                    _lows_in = list(lows_ind)
                _features = _teg.compute_features(
                    closes=list(closes_ind),
                    highs=_highs_in,
                    lows=_lows_in,
                    direction=ev.direction,
                )
                _verdict = _teg.evaluate_gate(_features)
                trend_gate_rec = {
                    "enabled": True,
                    "gate_pass": bool(_verdict["gate_pass"]),
                    "leg_a_pass": _verdict["leg_a_pass"],
                    "leg_b_pass": _verdict["leg_b_pass"],
                    "fail_open": bool(_verdict["fail_open"]),
                    "block_reasons": list(_verdict["block_reasons"]),
                    "adx_slope": _features.get("adx_slope"),
                    "adx_now": _features.get("adx_now"),
                    "adx_then": _features.get("adx_then"),
                    "bars_since_same_dir_cross": _features.get(
                        "bars_since_same_dir_cross"
                    ),
                    "last_cross_direction": _features.get("last_cross_direction"),
                    "hist_now": _features.get("hist_now"),
                    "macd_line_now": _features.get("macd_line_now"),
                    "sample_bars": _features.get("sample_bars"),
                    "compute_error": _features.get("compute_error"),
                    "adx_slope_min": _verdict["adx_slope_min"],
                    "cross_max_bars": _verdict["cross_max_bars"],
                    "cross_type": _features.get("cross_type"),
                    "adx_period": _features.get("adx_period"),
                    "adx_slope_window_bars": _features.get("adx_slope_window_bars"),
                    "macd_fast": _features.get("macd_fast"),
                    "macd_slow": _features.get("macd_slow"),
                    "macd_signal": _features.get("macd_signal"),
                }
                _teg.write_log({
                    "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "pair": "GBPUSD",
                    "epic": epic,
                    "strategy": "EMA_PULLBACK",
                    "direction": ev.direction,
                    "entry_px": round(entry_px, 5),
                    "fired_live": bool(_verdict["gate_pass"]),
                    "enforced_block": (
                        not _verdict["gate_pass"] and not _verdict["fail_open"]
                    ),
                    **trend_gate_rec,
                })
                if not _verdict["gate_pass"] and not _verdict["fail_open"]:
                    # EMA_PULLBACK ADX_SLOPE EXEMPTION (2026-06-27).
                    # When the ONLY failing leg is leg_a (adx_slope) and
                    # the exemption flag is on, allow through with a
                    # logged note. A pullback by definition reduces ADX,
                    # so leg_a structurally rejects valid pullbacks.
                    # leg_b (MACD cross) still discriminates trend
                    # continuation and is enforced. trend_entry_gate.py
                    # itself is unchanged → STRUCTURE_BREAK keeps both
                    # legs.
                    _leg_a_only = (
                        TREND_ENTRY_GATE_EMA_PB_EXEMPT
                        and _verdict.get("leg_a_pass") is False
                        and _verdict.get("leg_b_pass") is True
                    )
                    if _leg_a_only:
                        logger.info(
                            "[%s] %s %s TREND_GATE leg_a EXEMPT "
                            "(EMA_PULLBACK pullback-context): %s — fire proceeds",
                            LOG_TAG, symbol, ev.direction,
                            ", ".join(_verdict["block_reasons"]) or "blocked",
                        )
                        # Stamp the exemption decision into the gate record
                        # so signal_log shows it was a leg_a exemption,
                        # not a pass.
                        if isinstance(trend_gate_rec, dict):
                            trend_gate_rec["leg_a_exempt_fired"] = True
                    else:
                        logger.info(
                            "[%s] %s %s TREND_GATE block: %s",
                            LOG_TAG, symbol, ev.direction,
                            ", ".join(_verdict["block_reasons"]) or "blocked",
                        )
                        return None
            else:
                trend_gate_rec = {"enabled": False}
        except Exception as _teg_exc:
            # Fail-open on any unexpected error (mirrors gate spec).
            logger.warning(
                "[%s] trend_entry_gate failed (fail-open): %s",
                LOG_TAG, _teg_exc,
            )
            trend_gate_rec = {
                "enabled": True,
                "fail_open": True,
                "compute_error": f"outer_exception:{type(_teg_exc).__name__}:{_teg_exc}",
            }

        # ── EMA_PULLBACK velocity gate (2026-06-26, LIVE ENFORCE) ───────
        # Block when velo_in_faded > EMA_PB_VELO_MAX — i.e., the bounce
        # hasn't committed yet. Stacks ON TOP of the trend gate.
        ema_pb_velo_rec: Optional[Dict[str, Any]] = None
        if EMA_PB_VELOCITY_GATE_ENABLED:
            try:
                if len(closes_ind) >= EMA_PB_VELO_BARS + 1:
                    _vc = float(closes_ind[-1])
                    _vp = float(closes_ind[-1 - EMA_PB_VELO_BARS])
                    _velo_10 = (_vc - _vp) / float(EMA_PB_VELO_BARS) / float(PIP_SIZE)
                    # MIRROR of BB_BOUNCE convention: faded_sign = -1 for
                    # BUY (L), +1 for SELL (S). velo_in_faded > 0 ⇔
                    # price rushing into the stack.
                    _faded_sign = -1.0 if ev.direction == "LONG" else 1.0
                    _velo_in_faded = _velo_10 * _faded_sign
                    _verdict = (
                        "PASS" if _velo_in_faded <= EMA_PB_VELO_MAX else "BLOCK"
                    )
                    ema_pb_velo_rec = {
                        "enabled": True,
                        "velo_10": round(_velo_10, 4),
                        "velo_in_faded": round(_velo_in_faded, 4),
                        "threshold_max": EMA_PB_VELO_MAX,
                        "bars": EMA_PB_VELO_BARS,
                        "verdict": _verdict,
                    }
                    _ema_pb_velo_log({
                        "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "pair": "GBPUSD",
                        "epic": epic,
                        "strategy": "GBPUSD_EMA_PULLBACK",
                        "direction": ev.direction,
                        "entry_px": round(entry_px, 5),
                        "fired_live": (_verdict == "PASS"),
                        "enforced_block": (_verdict == "BLOCK"),
                        "trend_gate_pass": (
                            trend_gate_rec.get("gate_pass")
                            if trend_gate_rec else None
                        ),
                        **ema_pb_velo_rec,
                    })
                    if _verdict == "BLOCK":
                        logger.info(
                            "[EMA_PB_VELO_BLOCK] %s %s velo_10=%+.3fp/bar "
                            "velo_in_faded=%+.3fp/bar thr_max=%.3f "
                            "(bounce not committed)",
                            symbol, ev.direction, _velo_10, _velo_in_faded,
                            EMA_PB_VELO_MAX,
                        )
                        return None
                else:
                    ema_pb_velo_rec = {
                        "enabled": True,
                        "verdict": "INSUFFICIENT_BARS",
                        "have_closes": len(closes_ind),
                        "need_closes": EMA_PB_VELO_BARS + 1,
                    }
                    _ema_pb_velo_log({
                        "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "pair": "GBPUSD",
                        "epic": epic,
                        "strategy": "GBPUSD_EMA_PULLBACK",
                        "direction": ev.direction,
                        **ema_pb_velo_rec,
                    })
            except Exception as _velo_exc:
                logger.warning(
                    "[EMA_PB_VELO_ERROR] %s %s velocity gate compute failed: "
                    "%s — fail-open, fire proceeds",
                    symbol, ev.direction, _velo_exc,
                )
                ema_pb_velo_rec = {
                    "enabled": True,
                    "fail_open": True,
                    "compute_error": f"{type(_velo_exc).__name__}:{_velo_exc}",
                }
        else:
            ema_pb_velo_rec = {"enabled": False}

        # ── VWAP-STRETCH EXHAUSTION BRAKE (2026-06-30, LIVE) ────────────
        # Direction-aware brake on continuation strategies. Short side
        # default-on (validated 2026-06-30 V-bottom losers: L4 EMA_PB_S
        # at vwap_dist=-15.53p pnl=-15.80p). Long side default-off.
        # CHOP-only. Read flags at call time. Fail-open everywhere.
        # ADDITIVE to every other gate above — both can block.
        _brake_rec: Dict[str, Any] = {"called": False}
        try:
            from guards.trend_stretch_brake import evaluate as _stretch_brake
            _blocked, _brake_reason, _brake_rec = _stretch_brake(
                strategy="EMA_PULLBACK",
                mode=mode,
                direction=ev.direction,
                bars=bars,
                last_price=float(bars[-1].close),
                pip_size=PIP_SIZE,
                symbol=symbol,
                ts_utc=ts,
                adx_at_decision=_brake_adx_at_bar,
                adx_source=_brake_adx_source,
            )
            if _blocked:
                logger.info(
                    "[%s] %s %s STRETCH_BRAKE block: %s",
                    LOG_TAG, symbol, ev.direction, _brake_reason,
                )
                return None
        except Exception as _brake_exc:
            logger.warning(
                "[%s] stretch_brake raised (fail-open): %s",
                LOG_TAG, _brake_exc,
            )
            _brake_rec = {"fail_open": True, "compute_error": str(_brake_exc)}

        # ── RANGE GATE (legacy fire path) ──────────────────────────────
        # Suppress legacy EMA_PULLBACK fires inside a range (wide bands
        # + low ER). Direction-agnostic, mode allowlist
        # (GBPUSD_EMA_PULLBACK_L/S). Fail-open. ADDITIVE to every gate
        # above — any can independently block.
        _range_rec: Dict[str, Any] = {"called": False}
        try:
            from guards.range_gate import evaluate as _range_gate
            _r_blocked, _r_reason, _range_rec = _range_gate(
                strategy="EMA_PULLBACK",
                mode=mode,
                direction=ev.direction,
                bars=bars,
                last_price=float(bars[-1].close),
                pip_size=PIP_SIZE,
                symbol=symbol,
                ts_utc=ts,
            )
            if _r_blocked:
                logger.info(
                    "[%s] %s %s RANGE_GATE suppress: %s",
                    LOG_TAG, symbol, ev.direction, _r_reason,
                )
                return None
        except Exception as _range_exc:
            logger.warning(
                "[%s] range_gate raised (fail-open): %s",
                LOG_TAG, _range_exc,
            )
            _range_rec = {"fail_open": True, "compute_error": str(_range_exc)}

        # Build the decision.
        sl_pips = float(SL_PIPS)
        tp_pips = float(ev.runner_tp_pips)

        reason = (
            f"ema_pullback_{direction_signal.lower()} "
            f"h1={ev.h1_direction}(sep={ev.h1_separation_pips:+.2f}p) "
            f"stack_ordered fan_report={ev.fan_pips:.2f}p "
            f"pullback_start={ev.pullback_start_offset_bars}b_ago "
            f"pullback_peak={ev.pullback_peak_offset_bars}b_ago@{ev.pullback_peak_price:.2f} "
            f"trail_extreme={ev.trail_extreme_offset_bars}b_ago@{ev.trail_extreme_price:.2f}"
            f"(prox={ev.trail_band_proximity_pips:+.2f}p) "
            f"entry_body={ev.entry_bar_body_pips:.2f}p "
            f"runner_target_mode={RUNNER_TARGET_MODE} "
            f"SL={sl_pips:.0f}p TP={tp_pips:.1f}p"
        )

        debug: Dict[str, Any] = {
            "pattern": "EMA_PULLBACK",
            "direction": ev.direction,
            "fan_pips_report_only": ev.fan_pips,   # legacy key — retained
            "fan_width_pips_at_fire": ev.fan_pips, # gated key — written to signal_log
            "fan_min_threshold_pips": float(MIN_FAN_PIPS),
            "fan_gate_enabled": bool(FAN_GATE_ENABLED),
            "bb_width_pips_at_fire": ev.bb_width_pips,
            "bb_squeeze_at_fire": ev.bb_squeeze,
            "bb_squeeze_lookback_bars": int(SQUEEZE_LOOKBACK_BARS),
            "h1_direction": ev.h1_direction,
            "h1_separation_pips": ev.h1_separation_pips,
            "h1_sep_min_threshold": H1_SEP_MIN_PIPS,
            "pullback_start_offset_bars": ev.pullback_start_offset_bars,
            "pullback_peak_offset_bars": ev.pullback_peak_offset_bars,
            "pullback_peak_price": ev.pullback_peak_price,
            "trail_extreme_offset_bars": ev.trail_extreme_offset_bars,
            "trail_extreme_price": ev.trail_extreme_price,
            "trail_band_proximity_pips": ev.trail_band_proximity_pips,
            "trail_band_tol_threshold": TRAIL_BAND_TOL_PIPS,
            "trail_min_ago_threshold": TRAIL_MIN_AGO_BARS,
            "trail_lookback_bars": TRAIL_LOOKBACK_BARS,
            "pullback_lookback_bars": LOOKBACK_BARS,
            "entry_bar_body_pips": ev.entry_bar_body_pips,
            "runner_target_mode": RUNNER_TARGET_MODE,
            "runner_tp_pips": ev.runner_tp_pips,
            "ema8": round(ev.ema8, 4),
            "ema13": round(ev.ema13, 4),
            "ema21": round(ev.ema21, 4),
            "ema50": round(ev.ema50, 4),
            "bb_lower": round(ev.bb_lower, 4),
            "bb_mid": round(ev.bb_mid, 4),
            "bb_upper": round(ev.bb_upper, 4),
        }

        # Momentum-direction SHADOW gate fields (added 2026-06-24). Keys
        # match the schema written to logs/ema_pullback_momentum_shadow
        # so the per-fire jsonl can be joined to the signal_log row by
        # trade_id later.
        if shadow_rec is not None:
            debug["momentum_shadow"] = dict(shadow_rec)
            debug["momentum_shadow_enabled"] = bool(MOMENTUM_GATE_SHADOW_ENABLED)
            debug["momentum_shadow_enforce"] = bool(MOMENTUM_GATE_ENFORCE)

        # TREND_ENTRY_GATE fields (added 2026-06-25). Mirrors the per-fire
        # row written to logs/trend_entry_gate.jsonl so signal_log carries
        # the gate verdict alongside the trade_id.
        if trend_gate_rec is not None:
            debug["trend_entry_gate"] = dict(trend_gate_rec)

        # EMA_PB velocity gate fields (added 2026-06-26). Mirrors the
        # per-fire row written to logs/ema_pb_velocity_gate.jsonl.
        if ema_pb_velo_rec is not None:
            debug["ema_pb_velocity_gate"] = dict(ema_pb_velo_rec)

        # VWAP-stretch brake telemetry (2026-06-30). Always-on debug stamp
        # for ALLOW fires so the signal_log row carries vwap_dist + regime
        # + threshold state. BLOCK fires returned None above and are only
        # captured in logs/trend_stretch_brake.jsonl.
        try:
            if isinstance(_brake_rec, dict):
                debug["trend_stretch_brake"] = dict(_brake_rec)
        except Exception:
            pass

        # Range-gate telemetry (2026-06-30). Always-on debug stamp for
        # ALLOW fires. SUPPRESS fires returned None above and are only
        # captured in logs/range_gate.jsonl.
        try:
            if isinstance(_range_rec, dict):
                debug["range_gate"] = dict(_range_rec)
        except Exception:
            pass

        # Regime tagging (no gating) — capture gbpusd_regime_detector's
        # verdict at fire time so signal_logger writes it onto the row.
        # log=False so we don't double-stamp logs/gbpusd_regime.jsonl
        # (BB_BOUNCE already calls classify_regime with log=True). Best-
        # effort — failure here MUST NOT block a fire.
        if REGIME_TAG_ENABLED:
            try:
                from gbpusd_regime_detector import classify_regime as _crg
                _rg = _crg(list(bars), symbol="GBPUSD", log=False)
                debug.update({
                    "regime": _rg.regime,
                    "regime_confidence_final": _rg.confidence,
                    "regime_signals": dict(_rg.signal_breakdown),
                    "regime_source": "gbpusd_regime_detector",
                    "regime_classified_at_bar_ts": (
                        _rg.timestamp.isoformat()
                        if _rg.timestamp is not None else None
                    ),
                })
            except Exception as _tag_exc:
                logger.warning(
                    "[%s] regime_tag capture failed: %s", LOG_TAG, _tag_exc,
                )

        # Lazy import — keep module-level imports free of live side effects.
        try:
            from strategy_logic import StrategyDecision
        except Exception as exc:
            logger.error("[%s] StrategyDecision import failed: %s", LOG_TAG, exc)
            return None

        decision = StrategyDecision(
            symbol="GBPUSD",
            regime="EMA_PULLBACK",
            signal=direction_signal,
            mode=mode,
            entry=entry_px,
            sl=round(sl_pips, 2),
            tp=round(tp_pips, 2),
            use_trailing_stop=False,
            reason=reason,
            debug=debug,
            pip_size=PIP_SIZE,
        )

        # Record fire time for cooldown bookkeeping. We do this AFTER
        # building the decision so any downstream raises don't poison
        # the cooldown.
        self._last_fire_ts_by_epic[epic] = ts

        # Emit the live-fire shadow row (telemetry only — never raises).
        if MOMENTUM_GATE_SHADOW_ENABLED and shadow_rec is not None:
            _write_momentum_shadow({
                "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pair": "GBPUSD",
                "epic": epic,
                "direction": ev.direction,
                "entry_px": round(entry_px, 5),
                "fired_live": True,
                "enforced_block": False,
                "trail_extreme_price": float(ev.trail_extreme_price),
                "ema8": round(float(ev.ema8), 5),
                "h1_direction": ev.h1_direction,
                **shadow_rec,
            })

        logger.info(
            "[%s] %s %s ENTRY @ %.5f | SL=%.0fp TP=%.1fp | shadow_fire=%s | %s",
            LOG_TAG, ev.direction, direction_signal,
            entry_px, sl_pips, tp_pips,
            (shadow_would_fire if shadow_would_fire is not None else "n/a"),
            reason,
        )
        return decision


# Module-level singleton + dispatch helper (mirrors gbpusd_bb_bounce).
strategy = GbpUsdEmaPullbackStrategy.instance()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)
