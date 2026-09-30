"""
gbpusd_structure_break.py — GBPUSD break-of-structure momentum entry.

Why this exists: 25-day audit (2026-05-13 → 2026-06-15) showed 10/25 trading
days had a clean directional thrust the fleet sat out entirely. EMA_PULLBACK
and GBPUSD_TREND are both pullback-faders by design — they require a settled
5M stack before they fire, so the actual thrust bars (stack mid-flip, sharp
displacement) are structurally unreachable. This module fills that gap by
entering ON the structure flip, not after the dust settles.

ENTRY DEFINITION
================
A FRESH DECISIVE flip of the 5M structure direction, with whipsaw guards:

  Trigger (reuses htf_authority._structure_dir verbatim — same primitive that
  drives STRUCTURE_LEADS in htf_authority.evaluate; we DO NOT reimplement the
  walk):
    1. struct_dir, details = htf_authority._structure_dir(symbol)
    2. struct_dir ∈ {"UP","DOWN"}  (FLAT → stand down)
    3. details["flip_bar_ts"] == current_bar_ts                  ← fresh
    4. |close − prior_swing_extreme| ≥ DECISIVE_PIPS (default 3p) ← decisive

  Regime gate (whipsaw guard — non-negotiable):
    5. regime_engine.latest_result(symbol).winning_regime NOT in
       {RANGE_ROTATION, CHOP, COMPRESSION}.  ⚠️ VOLATILITY_EXPANSION is
       ALLOWED — momentum entries live in vol-expansion; the ADX floor +
       3p decisive break ARE the whipsaw guards there.
    6. ADX(14) ≥ ADX_MIN (default 25).

  ⚠️ Direction comes from the FLIP, never from the regime's directional_bias.
  The whole point is that the regime classifier lags structure; requiring
  bias-agreement would recreate the same lag bug EMA_PULLBACK has with H1.

Risk geometry
=============
  Entry      = bars[-1].close (the flip-bar close).
  Initial SL = |entry − broken_swing_extreme| + 0.5 × ATR(14),
               clamped to [MIN_SL_PIPS, MAX_SL_PIPS].
               (SHORT: above prior_high. LONG: below prior_low.)
  Broker TP  = RUNNER_TP_PIPS (default 80p) — matches gbpusd_trend's
               TREND_BROKER_TP_PIPS. The 80p cap gives the trail room to
               ratchet through all three steps (15/25/40p triggers, locks
               at 7/17/32p) before the broker TP closes the runner.
  Scale-out  = UNIVERSAL +10p / 50% (trade_manager.SCALE_OUT_AT_10P_ENABLED).
               Banks half, moves broker SL to BE. Applies to every mode.
  Trail      = continuous peak-pivot trail (NOT the TREND stepped ratchet).
               Modes are in trade_manager._STRUCTURE_BREAK_TRAIL_MODES, so
               the runner post-scale-out is managed by
               _apply_structure_break_runner_trail. Per-bar rule:
                   proposed_lock_pips = max(0, peak_pnl_pips − OFFSET)
                   new_broker_SL      = entry ± proposed_lock × ppp
               Monotonic upward, floored at BE. peak_pnl_pips is measured
               from the ORIGINAL ENTRY price; the SL is amended off the same
               entry. Default OFFSET = 8p (env STRUCTURE_BREAK_TRAIL_OFFSET
               _PIPS). Continuous from entry — no step triggers; until peak
               ≥ OFFSET the SL stays at BE. Example locks:
                   peak +10p → SL +2p     peak +15p → SL +7p
                   peak +20p → SL +12p    peak +40p → SL +32p
               Decision.use_trailing_stop=False (same as gbpusd_trend); the
               trail is server-side via _amend_broker_sl, not a client-side
               trailing-stop attribute.

Note on the EXIT pattern: STRUCTURE_BREAK briefly piggy-backed on TREND's
stepped 3-step ratchet (2026-06-15) before being given its own continuous
trail same day. EMA_PULLBACK's runner rides BE → broker_TP with no trail —
appropriate for a mean-reversion runner targeting the origin BB band.
STRUCTURE_BREAK enters on a fresh thrust where the natural target is "as
far as the move goes" but a stepped ratchet introduces dead zones between
triggers; the continuous trail tracks every favourable bar so the runner
gives back exactly OFFSET pips at the top, no more.

Note on other trade_manager mode allowlists: this module's modes are
intentionally NOT added to:
  - trade_manager.BB_PIERCE_RUN_MODES   (240m time stop — TREND uses the
                                         default ~120m and the ratchet
                                         captures profit before then;
                                         STRUCTURE_BREAK mirrors that)
  - trade_manager._BB_BOUNCE_TRAIL_MODES (mean-reversion smoothing trail,
                                         not applicable here)
  - trade_executor._PAIR_CONCURRENCY_BYPASS_MODES
  - conviction_gate.TREND_FOLLOWING_MODES / REVERSAL_MODES
EMA_STATE alignment check does NOT apply (correct — EMA_STATE is by
definition mid-flip at the entry bar). Conviction ADX gate floor (20p
default) is BELOW our internal 25p floor, so anything passing our gate
also clears conviction.

KILL SWITCH
===========
STRUCTURE_BREAK_ENABLED default "0". Slot modes GBPUSD_STRUCTURE_BREAK_L /
GBPUSD_STRUCTURE_BREAK_S (DISTINCT from EMA_PULLBACK / BB_BOUNCE / BB_REV_PAT
— never share an open-slot).

Module-level imports are stdlib + dataclasses only. htf_authority,
regime_engine, news_calendar, strategy_logic are LAZY imports inside the
strategy methods so mere import of this module does NOT pull in live state.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_logic import StrategyDecision  # noqa: F401

logger = logging.getLogger("gbpusd_structure_break")

LOG_TAG = "STRUCTURE_BREAK"

MODE_NAME_LONG  = "GBPUSD_STRUCTURE_BREAK_L"
MODE_NAME_SHORT = "GBPUSD_STRUCTURE_BREAK_S"

PIP_SIZE = 1.0  # GBPUSD on the IG TODAY epic: 1 raw point = 1 pip


# ─── env helpers (mirror gbpusd_ema_pullback) ──────────────────────────────
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


# ─── Configuration ─────────────────────────────────────────────────────────
# Master kill-switch. Default OFF.
ENABLED = _env_bool("STRUCTURE_BREAK_ENABLED", "0")

# Active session window (UTC, weekdays only). Mirrors EMA_PULLBACK.
WIN_START = dtime(_env_int("STRUCTURE_BREAK_WIN_START_H", 6), 0)
WIN_END   = dtime(_env_int("STRUCTURE_BREAK_WIN_END_H", 17), 0)

# Trigger params — reuse the htf_authority primitive's lookback by default.
# DECISIVE_PIPS: minimum break size (close vs prior swing extreme) for a
# fresh structure flip to be considered a fire candidate.
#
# 2026-06-16: env-tunable for grind-period calibration. The hard-coded 3.0
# fallback is the byte-identical-to-pre-edit value. Under
# STRUCTURE_BREAK_GRIND_ENABLED=1 the env-supplied value is honoured
# (recommended loosened default 2.5p from 5-day replay; see
# _validate_phaseB_grind_replay.py). Under =0 (default) the threshold is
# pinned to 3.0 regardless of STRUCTURE_BREAK_DECISIVE_PIPS — preserves
# current behaviour until the user opts in via .env.
_GRIND_ENABLED = _env_bool("STRUCTURE_BREAK_GRIND_ENABLED", "0")
_DECISIVE_PIPS_LOOSE = _env_float("STRUCTURE_BREAK_DECISIVE_PIPS", 2.5)
DECISIVE_PIPS_ORIGINAL = 3.0
DECISIVE_PIPS = _DECISIVE_PIPS_LOOSE if _GRIND_ENABLED else DECISIVE_PIPS_ORIGINAL
# 2026-06-28: gate the loosened-only bar-bucket freshness guard (see
# _detect, "Freshness guard for loosened-only entries"). Default OFF —
# the guard is a clock/bar-bucket timing check, not a break or
# displacement check, and with DECISIVE_PIPS=0 it would otherwise apply
# to every sub-3p break. Set to "1" to re-arm.
_LOOSENED_FRESHNESS_GUARD_ENABLED = _env_bool(
    "STRUCTURE_BREAK_LOOSENED_FRESHNESS_GUARD_ENABLED", "0"
)
# Shadow log knob — every eval that reaches the DECISIVE_PIPS gate emits
# one jsonl line for calibration. Default OFF (byte-identical fallback).
_GRIND_SHADOW_ENABLED = _env_bool("STRUCTURE_BREAK_GRIND_SHADOW_ENABLED", "0")
_GRIND_SHADOW_PATH = "/opt/tradingbot/logs/structure_break_grind_shadow.jsonl"

# Regime gate.
# 2026-06-28: emptied — setup was reduced to break-detection + displacement-
# confirm only. 2026-07-07: RESTORED behind kill-switch after 07-07 loss #1
# (SB fired into a range with no regime gate). Set STRUCTURE_BREAK_REGIME_
# FILTER_ENABLED=0 to revert to the empty-set behaviour byte-identically.
# The restored set is intentionally narrower than the pre-06-28 set: only
# the explicit ranging labels (RANGE_ROTATION, CHOP). COMPRESSION is NOT
# in the set — a compressed regime is a coil, and a break out of the coil
# IS the setup. A break strategy must not fire mid-range.
_REGIME_MATRIX_ENABLED = _env_bool("REGIME_MATRIX_ENABLED", "0")
_REGIME_FILTER_ENABLED = _env_bool(
    "STRUCTURE_BREAK_REGIME_FILTER_ENABLED", "1"
)
_RANGE_REGIMES_RESTORED = frozenset({"RANGE_ROTATION", "CHOP"})
RANGE_REGIMES = (_RANGE_REGIMES_RESTORED
                 if _REGIME_FILTER_ENABLED else frozenset())
ADX_MIN = _env_float("STRUCTURE_BREAK_ADX_MIN", 25.0)

# ── Transition-signal filter (2026-06-15) ──────────────────────────────────
# Layered on top of the existing ADX≥25 + regime-block gates above. The
# signature (flip_rate, adx_min, signed disp in flip direction) is ALWAYS
# computed + logged on every flip that reaches the gate stage — the
# enforcing filter is flag-gated separately.
#
# Hypothesis (validated against 25-day GBPUSD regime_engine.jsonl): when the
# regime-family pattern in the trailing 6 bars shows ≥2 UP↔DOWN flips, the
# pattern is ambiguous (real-turn or flicker-chop). What separates them is
# (a) adx_min across the window — real turns sustain ADX≥28, flicker chop
# collapses below; (b) signed displacement in the flip direction — real
# turns show ≥6p of net movement THE RIGHT WAY, chop bounces ±2p.
#
# When flip_rate < FLIP_MIN the filter does NOT apply — common clean-break
# entries (where the regime engine hasn't started oscillating yet) proceed
# on the existing gate stack. The filter only fires to BLOCK flicker chop.
TRANSITION_FILTER_ENABLED = _env_bool("STRUCTURE_BREAK_TRANSITION_FILTER_ENABLED", "0")
TRANSITION_WINDOW_BARS    = _env_int("STRUCTURE_BREAK_TRANSITION_WINDOW_BARS", 6)
TRANSITION_FLIP_MIN       = _env_int("STRUCTURE_BREAK_TRANSITION_FLIP_MIN", 2)
TRANSITION_ADX_WIN_MIN    = _env_float("STRUCTURE_BREAK_TRANSITION_ADX_WIN_MIN", 28.0)
TRANSITION_DISP_MIN_PIPS  = _env_float("STRUCTURE_BREAK_TRANSITION_DISP_MIN_PIPS", 6.0)

# ── Signed-displacement entry confirmation (2026-06-15) ────────────────────
# Standalone gate, INDEPENDENT of the transition filter and the regime
# history. At every fresh-decisive structure flip that reaches the gate
# stage (i.e., after the existing decisive-break + regime-block + ADX-25
# gates), require net 5M price displacement over the trailing
# DISP_CONFIRM_WINDOW_BARS to AGREE with the break direction by at least
# DISP_CONFIRM_MIN_PIPS. Catches the dangerous case where the structure
# primitive registers a flip against the still-running prior leg (a poke,
# not a turn): down-break while net 6-bar price is still UP, or up-break
# while net 6-bar price is still DOWN.
#
# disp_pips is computed directly from bars:
#     disp_pips = (bars[-1].close - bars[-(WINDOW+1)].close) / PIP_SIZE
# No dependency on regime_engine.jsonl — works even if the regime log is
# unavailable. Same primitive the transition filter's signature computes,
# but recomputed locally so this gate stands alone.
#
# Direction-signed rule:
#     DOWN break:  require disp_pips <= -DISP_CONFIRM_MIN_PIPS
#     UP   break:  require disp_pips >= +DISP_CONFIRM_MIN_PIPS
# Default 4.0p — looser than the transition filter's 6.0p (which gates on
# the same disp axis but only when flip_rate>=2). This gate ALWAYS applies.
DISP_CONFIRM_ENABLED      = _env_bool("STRUCTURE_BREAK_DISP_CONFIRM_ENABLED", "0")
DISP_CONFIRM_WINDOW_BARS  = _env_int("STRUCTURE_BREAK_DISP_CONFIRM_WINDOW_BARS", 6)
DISP_CONFIRM_MIN_PIPS     = _env_float("STRUCTURE_BREAK_DISP_CONFIRM_MIN_PIPS", 4.0)

# ── N-bar HOLD SHADOW gate (added 2026-06-24) ──────────────────────────────
# Proven on n=17 real fills: STRUCTURE_BREAK admits false-breaks (price
# pierces the level on bar B, triggers entry, reverts within ~3 bars). 36%
# of losers were clean false-breaks. An N=2 bar-hold requirement (entry
# bar AND prior bar both close beyond the broken level by >= break
# threshold) would have blocked all 4 false-break losers in the sample
# while killing only the 2 smallest winners, net ~+19p across 17 fires.
# N=3 gave no marginal gain over N=2.
#
# Definition (precise — see Phase 0 in commit msg / docs):
#   L_hold = max(bars[-(N+H):-H].high)  for UP
#          = min(bars[-(N+H):-H].low)   for DOWN
#   where N = STRUCT_LEADS_N (the same lookback the live freshness path
#   uses, default 5) and H = STRUCTURE_BREAK_HOLD_BARS (default 2).
#   The window EXCLUDES the bars being checked (bars[-1..-H]) so the
#   check is well-defined; the L_hold level is the structural swing
#   that pre-existed the move.
#   shadow_hold_ok = ALL bars in bars[-H:] close beyond L_hold by >=
#   DECISIVE_PIPS (signed by break direction).
#
# Telemetry-only by default. Promotion to enforce is a flag flip.
# ORTHOGONAL to DISP_CONFIRM (which is close-to-close displacement,
# not level-anchored). Stacks freely.
HOLD_SHADOW_ENABLED = _env_bool("STRUCTURE_BREAK_HOLD_SHADOW", "1")
HOLD_ENFORCE        = _env_bool("STRUCTURE_BREAK_HOLD_ENFORCE", "0")
HOLD_BARS           = _env_int("STRUCTURE_BREAK_HOLD_BARS", 2)
# Hold threshold defaults to DECISIVE_PIPS (matches "by ≥ the break
# threshold" in the spec). Independently tunable during the shadow
# window without touching the live break gate — useful since the
# 14d retrodict suggested the strict 3.0p hold is much tighter than
# the n=17 sample implied (set to 0.0 for "just beyond level").
HOLD_THRESHOLD_PIPS = _env_float("STRUCTURE_BREAK_HOLD_THRESHOLD_PIPS", float(DECISIVE_PIPS))
HOLD_SHADOW_PATH    = os.getenv(
    "STRUCTURE_BREAK_HOLD_SHADOW_LOG_PATH",
    "/opt/tradingbot/logs/sb_hold_shadow.jsonl",
)

# ─── SB velocity gate (2026-06-26, LIVE ENFORCE) ───────────────────────
# Mirror of the BB_BOUNCE velocity guard (commit 3898279), opposite end
# of the same axis. STRUCTURE_BREAK needs HIGH velocity to be a real
# break, not a limp false break that reverts.
# Convention:
#   velo_10 = (closes[-1] - closes[-11]) / 10  → pips/bar
#   trade_sign = +1 for LONG (UP break), -1 for SHORT (DOWN break)
#   velo_in_break = velo_10 * trade_sign  → +ve means momentum in break direction
#   Require velo_in_break >= SB_VELO_MIN (default 1.0) to fire.
# Validated against 24 GBPUSD STRUCTURE_BREAK fills:
#   Winners (n=9): median velo_in_break +1.83p/bar.
#   Losers  (n=15): median +0.84p/bar.
#   AUC 0.748. Block when velo<1.0: −77p → +15.8p, 9L removed vs 2W
#   killed (4.5× ratio). n=24 thin — feature-log for forward tuning.
# Fail-open on compute error.
SB_VELOCITY_GATE_ENABLED = _env_bool("SB_VELOCITY_GATE_ENABLED", "1")
SB_VELO_MIN = _env_float("SB_VELO_MIN", 1.0)
SB_VELO_BARS = _env_int("SB_VELO_BARS", 10)
SB_VELO_LOG_PATH = os.getenv(
    "SB_VELO_LOG_PATH", "/opt/tradingbot/logs/sb_velocity_gate.jsonl",
)

_sb_velo_log_lock = threading.Lock()


def _sb_velo_log(rec: Dict[str, Any]) -> None:
    """Append one JSON record to the SB velocity gate audit log.
    Never raises — log-write failures must not affect the gate verdict."""
    try:
        d = os.path.dirname(SB_VELO_LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _sb_velo_log_lock:
            with open(SB_VELO_LOG_PATH, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


# ─── SB daily-alignment filter audit log (2026-06-30) ───────────────────
# One JSONL row per fire decision the filter inspects (BLOCK + ALLOW).
# Path is env-overridable; never raises into the fire path.
SB_DAILY_FILTER_LOG_PATH = os.getenv(
    "SB_DAILY_FILTER_LOG_PATH",
    "/opt/tradingbot/logs/sb_daily_filter.jsonl",
)
_sb_daily_filter_lock = threading.Lock()


def _sb_daily_filter_log(rec: Dict[str, Any]) -> None:
    """Append one JSON record to the SB daily-alignment filter audit log."""
    try:
        d = os.path.dirname(SB_DAILY_FILTER_LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _sb_daily_filter_lock:
            with open(SB_DAILY_FILTER_LOG_PATH, "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass

# ─── TREND_ENTRY_GATE (added 2026-06-25, ENFORCE-ON by default) ─────────
# Hard gate: adx_slope >= ADX_SLOPE_MIN AND last same-dir MACD(12,26,9)
# signal-line cross within CROSS_MAX_BARS bars. Validated on 67 real fills
# (ungated −238p → 22 pass +76p). Live calc requires full df closes/highs
# /lows (parity verified bit-exact vs the diagnostic on full df; off by
# integer ADX points with only 60 bars warmup, which is why the dispatch
# in autobot.py passes them explicitly). See trend_entry_gate.py.

# Same source the existing regime gate reads — regime_engine.jsonl is the
# file regime_engine.emit() writes to on every 5m close, and where
# regime_engine.latest_result()'s in-memory cache is sourced from. For
# history we tail the file (in-memory cache holds only the latest).
TRANSITION_REGIME_LOG_PATH = os.getenv(
    "STRUCTURE_BREAK_TRANSITION_REGIME_LOG_PATH",
    "/opt/tradingbot/logs/regime_engine.jsonl",
)

# Risk geometry.
ATR_PERIOD          = _env_int("STRUCTURE_BREAK_ATR_PERIOD", 14)
SL_BUFFER_ATR_MULT  = _env_float("STRUCTURE_BREAK_SL_BUFFER_ATR_MULT", 0.5)
MIN_SL_PIPS         = _env_float("STRUCTURE_BREAK_MIN_SL_PIPS", 12.0)
MAX_SL_PIPS         = _env_float("STRUCTURE_BREAK_MAX_SL_PIPS", 30.0)
# Broker TP = "let it run" cap. Default 80p mirrors gbpusd_trend's
# TREND_BROKER_TP_PIPS so the centralised TREND-style trail
# (_apply_trend_runner_trail in trade_manager) has room to ratchet through
# all three steps (15/25/40p triggers) before the broker TP closes the
# runner. The 40p prior default would have closed the runner at the third
# trail step's trigger, defeating the trail.
RUNNER_TP_PIPS      = _env_float("STRUCTURE_BREAK_RUNNER_TP_PIPS", 80.0)

# ── Retest-limit entry (2026-07-07) ────────────────────────────────────────
# Replaces the flip-bar-close (chase) entry with a pending LIMIT at the
# broken level ± a small buffer, expiring after N bars. Motivation: 60d
# retest-vs-runaway study over 549 decisive breaks — 57% RETEST / 41% RUN
# / 3% FAIL at N=5 bars, retests overshoot the level (74% overshoot at N=5,
# median 3.3p past), median time-to-touch = 1 bar; and on the retested
# majority the CHASE entry sits median 8.2p underwater. Enter on the
# level, not on the chase, so:
#   (1) the entry is ~median 4p better (the break_pips itself);
#   (2) the SL — |entry - level| + 0.5*ATR — is naturally tighter, because
#       |limit - level| = BUFFER (default 1p) vs |chase - level| = break_pips
#       (median 4.4p, p75 5.95p);
#   (3) runaways (~41%) are cleanly skipped when the limit expires unfilled.
#
# LIFECYCLE (bot-side monitored — no IG working order; IG's per-pair min-
# distance floor ~12p would reject a level+1p limit at flip time).
#
#   PLACE  — on a fresh decisive break that passes all today's gates,
#            instead of returning a chase decision, register a pending
#            LIMIT at level ± BUFFER on the singleton. Return None
#            (no trade opens this bar).
#   MONITOR — each subsequent 5m evaluate() call: if the just-closed bar's
#            low (LONG) or high (SHORT) touched the limit price, the
#            limit FILLS. Build the StrategyDecision with entry=limit_price
#            and sl_pips recomputed from BUFFER (not the original break_pips),
#            return it.
#   EXPIRE — if EXPIRY_BARS 5m bars elapse without a touch, cancel
#            the pending (no trade). Log EXPIRED — this is exactly the
#            runaway skip.
#   REPLACE — if a fresh decisive break is detected while a pending is
#            still WAITING, replace the pending with the new one (fresh
#            signal supersedes older). Log REPLACED.
#
# The chase decision code path is unchanged and remains the ONLY code
# path when STRUCTURE_BREAK_RETEST_ENTRY_ENABLED=0 (byte-identical kill).
RETEST_ENTRY_ENABLED       = _env_bool("STRUCTURE_BREAK_RETEST_ENTRY_ENABLED", "1")
RETEST_LIMIT_BUFFER_PIPS   = _env_float("STRUCTURE_BREAK_RETEST_LIMIT_BUFFER_PIPS", 1.0)
RETEST_EXPIRY_BARS         = _env_int("STRUCTURE_BREAK_RETEST_EXPIRY_BARS", 3)
_RETEST_LOG_PATH           = "/opt/tradingbot/logs/sb_retest_limit.jsonl"

# Regime-conditional entry-path routing (2026-07-07). CHASE at market on
# genuine STRONG_TREND (hist / struct path). RETEST-limit on TREND_FORMING
# and on RANGE_ROTATION→STRONG_TREND promotions (label_path ==
# "range_break_promote" per 6ccc542). RETEST is the default for any
# uncovered regime SB fires in (BREAKOUT_FORMING_*, COMPRESSION) — the 60d
# retest-vs-runaway study justifies the bias (57% retest / 41% run at N=5);
# if the market runs away without pulling back, the pending simply expires,
# so the retest default is the safer, cleanly-skippable choice on any
# not-yet-classified regime. Only "genuine STRONG_TREND" — the regime that
# empirically follows-through — earns the chase.
#
# Kill-switch semantics (RETEST_ENTRY_ENABLED):
#   =0  → BYTE-IDENTICAL to pre-retest. Every SB fire chases at market,
#         no path gate, no pending, no telemetry.
#   =1  → apply the entry-path gate. Genuine STRONG_TREND chases;
#         everything else places a retest limit.
RETEST_GATE_STRONG_TREND_PROMOTED = _env_bool(
    "STRUCTURE_BREAK_RETEST_GATE_STRONG_TREND_PROMOTED", "1"
)
RETEST_GATE_DEFAULT_PATH = (
    os.getenv("STRUCTURE_BREAK_RETEST_GATE_DEFAULT", "RETEST")
    .strip().upper()
)
if RETEST_GATE_DEFAULT_PATH not in ("CHASE", "RETEST"):
    RETEST_GATE_DEFAULT_PATH = "RETEST"
_ENTRY_PATH_LOG_PATH       = "/opt/tradingbot/logs/sb_entry_path.jsonl"

# Operator-controlled entry-path mode (2026-07-25). Overlays the classifier
# output. Values:
#   current       — no override (byte-identical to prior CHASE-hardcode
#                   behaviour). DEFAULT.
#   prefer_retest — strong-trend promotion no longer forces CHASE; any
#                   would-be CHASE from the classifier is routed through the
#                   existing retest machinery instead.
#   retest_only   — never CHASE; would-be CHASE flips are skipped with
#                   [SB-ENTRY] skipped=no_retest and no pending is placed.
# The kill switch (STRUCTURE_BREAK_RETEST_ENTRY_ENABLED=0) still wins — when
# it is off, the mode override is bypassed and every fire chases.
SB_ENTRY_PATH_MODE = os.getenv("SB_ENTRY_PATH_MODE", "current").strip().lower()
if SB_ENTRY_PATH_MODE not in ("current", "prefer_retest", "retest_only"):
    SB_ENTRY_PATH_MODE = "current"


def _apply_entry_path_mode(entry_path, kill_switch_forced_chase, mode,
                           base_reason):
    """Overlay SB_ENTRY_PATH_MODE on the classifier output.

    Returns (entry_path, mode_skipped_no_retest, entry_reason).

    Kill-switch has priority — when set, the mode is a no-op. Otherwise:
      current       — pass-through
      prefer_retest — CHASE → RETEST
      retest_only   — CHASE → skip (mode_skipped_no_retest=True)
    RETEST inputs are untouched in every mode.
    """
    if kill_switch_forced_chase or entry_path != "CHASE":
        return entry_path, False, base_reason
    if mode == "prefer_retest":
        return "RETEST", False, f"{base_reason}|mode=prefer_retest"
    if mode == "retest_only":
        return "CHASE", True, f"{base_reason}|mode=retest_only:no_retest"
    return entry_path, False, base_reason

# Cooldown and warmup.
COOLDOWN_BARS = _env_int("STRUCTURE_BREAK_COOLDOWN_BARS", 12)   # 60 min
WARMUP_BARS   = _env_int("STRUCTURE_BREAK_WARMUP_BARS", 30)

# News blackout (mirror gbpusd_ema_pullback default-ON).
NEWS_BLACKOUT_ENABLED = _env_bool("STRUCTURE_BREAK_NEWS_BLACKOUT_ENABLED", "1")
NEWS_PRE_MIN          = _env_int("STRUCTURE_BREAK_NEWS_PRE_MIN", 30)
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


# ─── Retest-limit jsonl writer ─────────────────────────────────────────────
def _write_retest_log(rec: Dict[str, Any]) -> None:
    """Append one JSONL row to _RETEST_LOG_PATH. Telemetry only — must
    never raise back into the fire path."""
    try:
        d = os.path.dirname(_RETEST_LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(_RETEST_LOG_PATH, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[%s] retest_log write failed: %s", LOG_TAG, exc)


# ─── Entry-path jsonl writer (2026-07-07) ──────────────────────────────────
def _write_entry_path_log(rec: Dict[str, Any]) -> None:
    """Append one JSONL row to _ENTRY_PATH_LOG_PATH. Telemetry only. Row
    per SB fire capturing entry_path decision + regime + label_path +
    promoted flag so forward fills are auditable by regime bucket."""
    try:
        d = os.path.dirname(_ENTRY_PATH_LOG_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(_ENTRY_PATH_LOG_PATH, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[%s] entry_path_log write failed: %s", LOG_TAG, exc)


# ─── HOLD SHADOW jsonl writer ──────────────────────────────────────────────
def _write_hold_shadow(rec: Dict[str, Any]) -> None:
    """Append one JSONL row to HOLD_SHADOW_PATH. Telemetry-only — must
    never raise back into the fire path. Mirrors the swallow-style used
    by gbpusd_bb_bounce._write_bb_bounce_l_cascade_shadow."""
    try:
        d = os.path.dirname(HOLD_SHADOW_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(HOLD_SHADOW_PATH, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as exc:
        logger.debug("[%s] hold_shadow write failed: %s", LOG_TAG, exc)


# ─── Bar dataclass ─────────────────────────────────────────────────────────
@dataclass
class Bar:
    """A closed 5m candle. `timestamp` is tz-aware UTC."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


# ─── Indicators ────────────────────────────────────────────────────────────
def _atr(bars: Sequence[Bar], period: int = 14) -> Optional[float]:
    """Wilder ATR over the last `period` bars. Returns ATR in PRICE units
    (not pips). None when there are not enough bars."""
    n = len(bars)
    if n < period + 1:
        return None
    # True range for each bar against its prior close.
    trs: List[float] = []
    for i in range(1, n):
        h = bars[i].high
        l = bars[i].low
        pc = bars[i - 1].close
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    # Wilder smoothing: seed with simple mean of first `period`, then EMA.
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return float(atr)


# ─── Detection internals ───────────────────────────────────────────────────
@dataclass
class _Evidence:
    direction: str          # "LONG" or "SHORT"
    flip_bar_ts: str        # the bar this flip occurred on (matches current)
    prior_swing: float      # broken extreme: prior_high (UP) or prior_low (DOWN)
    close_at_flip: float    # close that broke it
    break_pips: float       # |close − prior_swing| in pips
    atr_price: float        # ATR(14) in price units
    regime: str             # winning_regime at fire time (tag only)
    adx: float              # ADX(14) at fire time
    sl_pips: float          # initial SL in pips (post-buffer + clamp)
    sl_components: Dict[str, float]   # break/buffer/raw/clamped for telemetry
    # Transition signature (2026-06-15). Always populated when the regime-
    # history JSONL has enough emissions; None when insufficient. When
    # populated, contains: window_bars, fams, flip_rate, adx_min, adx_mean,
    # disp_pips, bars_with_adx, history_emissions.
    transition_sig: Optional[Dict[str, Any]] = None
    # Would the transition filter have blocked this entry (independent of
    # whether the filter flag was enabled)? Records the chop verdict so the
    # signal_log row carries both the live decision AND the would-be one.
    transition_would_block: bool = False
    transition_block_reason: str = ""
    # Signed-displacement entry confirmation (2026-06-15). Independent of
    # the transition filter — computed directly from bar closes over the
    # trailing DISP_CONFIRM_WINDOW_BARS. Always populated when enough bars
    # are present; None on warmup. would_block_disp captures the agreement
    # verdict regardless of whether the disp_confirm flag was enabled.
    disp_confirm_pips: Optional[float] = None
    disp_confirm_window_bars: int = 0
    disp_confirm_would_block: bool = False
    disp_confirm_block_reason: str = ""
    # regime_engine label_path at fire time. Distinguishes a genuine
    # STRONG_TREND ("hist" / "struct") from a range-break promotion
    # ("range_break_promote"). Read directly off latest_result — value
    # depends on regime_engine ≥ 6ccc542 (range-break promoter). Empty
    # string when unavailable (no emit yet / lookup exception). Consumed
    # by the entry-path gate to decide CHASE vs RETEST.
    regime_label_path: str = ""


# ─── Pending retest-limit state (bot-side monitored limit) ────────────────
@dataclass
class _PendingRetest:
    """A live LIMIT that was queued at PLACE and waits for a subsequent bar
    to touch it (fill), or to age out (expire). One per epic; the strategy
    singleton owns the dict.
    """
    epic: str
    direction: str          # "LONG" | "SHORT"
    direction_signal: str   # "BUY" | "SELL"
    mode: str               # MODE_NAME_LONG | MODE_NAME_SHORT
    level: float            # broken swing extreme (prior_high for LONG, prior_low for SHORT)
    limit_price: float      # level ± BUFFER (fill trigger)
    buffer_pips: float      # BUFFER used at placement
    # Snapshot from the flip bar — used to build the retest StrategyDecision on fill.
    close_at_flip: float
    break_pips_at_flip: float
    atr_price: float        # ATR at placement — reused for SL recompute at fill
    regime: str
    adx: float
    flip_bar_ts: str
    placed_ts: datetime     # the flip-bar ts (tz-aware UTC)
    expiry_ts: datetime     # placed_ts + EXPIRY_BARS * 5m
    # Debug carry-over so the fill decision keeps parity with what the
    # chase path would have written to signal_log at the flip bar.
    debug_carry: Dict[str, Any]
    sl_components_place: Dict[str, float]
    # regime label_path at PLACE time — carried onto FILLED/EXPIRED rows so
    # the retest-vs-runaway forward view can bucket outcomes by "promoted
    # STRONG_TREND" vs "TREND_FORMING" vs "default".
    regime_label_path: str = ""


# ─── Level-telemetry helpers (2026-07-24, OBSERVABLE-ONLY) ─────────────────
# Wraps the shared level_telemetry.compute_level_distance_fields with the
# STRUCTURE_BREAK-specific PDH/PDL derivation. Never blocks a fire — every
# path returns {} on any failure and logs at DEBUG only.

def _sb_compute_level_telemetry(
    entry_px: Optional[float],
    closes: Optional[Sequence[float]],
    highs: Optional[Sequence[float]],
    lows: Optional[Sequence[float]],
) -> Dict[str, Any]:
    """Return the six level-distance fields for STRUCTURE_BREAK.

    Sources PDH/PDL from indicators._ff_swing over the widest 5m series
    available (closes/highs/lows arg, falling back to
    candle_builder.get_df('GBPUSD')). In-process only — no REST, no HTF
    load, no briefing/session/news. Returns {} on any failure.
    """
    try:
        from level_telemetry import compute_level_distance_fields as _lvl_fn
        dpdh: Optional[float] = None
        dpdl: Optional[float] = None
        try:
            import indicators as _ind
            import pandas as _pd
            _c = list(closes) if closes else None
            _h = list(highs) if highs else None
            _l = list(lows) if lows else None
            if not _c or len(_c) < 287:
                try:
                    import candle_builder as _cb
                    _df = _cb.get_df("GBPUSD")
                    if _df is not None and len(_df) >= 287:
                        _c = [float(x) for x in _df["close"].tolist()]
                        _h = [float(x) for x in _df["high"].tolist()]
                        _l = [float(x) for x in _df["low"].tolist()]
                except Exception:
                    pass
            if _c and _h and _l and len(_c) >= 287:
                _swing = _ind._ff_swing(
                    _pd.Series(_c), _pd.Series(_h), _pd.Series(_l), PIP_SIZE,
                )
                if isinstance(_swing, dict):
                    dpdh = _swing.get("distance_from_pdh_pips")
                    dpdl = _swing.get("distance_from_pdl_pips")
        except Exception as _swing_exc:  # noqa: BLE001
            logger.debug("[%s] _sb PDH/PDL derive failed: %s",
                         LOG_TAG, _swing_exc)
        thr = _env_float("LEVEL_TELEMETRY_AT_LEVEL_PIPS", 5.0)
        return _lvl_fn(
            entry_price=entry_px,
            distance_from_pdh_pips=dpdh,
            distance_from_pdl_pips=dpdl,
            threshold_pips=thr,
        )
    except Exception as _exc:  # noqa: BLE001 — never block a fire
        logger.debug("[%s] level-distance telemetry failed: %s", LOG_TAG, _exc)
        return {}


def _sb_normalize_flip_bar_ts(x: Any) -> Optional[str]:
    """Return flip_bar_ts as a UTC ISO string.

    Live path (b) produces cur_ts_iso from
    `bars[-1].timestamp.astimezone(timezone.utc).isoformat()` — already UTC
    ISO. Path (a) may pass through primitive-supplied strings whose format
    isn't guaranteed. Normalize defensively; fall back to str(x) if parse
    fails so nothing regresses.
    """
    if x is None:
        return None
    try:
        if isinstance(x, datetime):
            d = x if x.tzinfo else x.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc).isoformat()
        s = str(x)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return str(x) if x is not None else None


# ─── Strategy class ────────────────────────────────────────────────────────
class GbpUsdStructureBreakStrategy:
    """Singleton. Stateless across days — slot enforcement is provided by
    the autobot wiring via has_open_long / has_open_short."""

    _instance: Optional["GbpUsdStructureBreakStrategy"] = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_fire_ts_by_epic: Dict[str, datetime] = {}
        # Pending retest-limit orders keyed by epic. One per epic —
        # a fresh break during a WAITING pending REPLACES it. Cleared
        # on FILL, EXPIRE, or REPLACE. See _PendingRetest for state.
        self._pending_retest_by_epic: Dict[str, "_PendingRetest"] = {}

    @classmethod
    def instance(cls) -> "GbpUsdStructureBreakStrategy":
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

    # ── Structure direction (lazy import) ──────────────────────────────────
    @staticmethod
    def _structure_dir(symbol: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Wrapper around htf_authority._structure_dir(symbol). Returns
        (direction, details) or None on infrastructure failure."""
        try:
            import htf_authority
            return htf_authority._structure_dir(symbol)
        except Exception as exc:
            logger.warning("[%s] _structure_dir lookup failed: %s", LOG_TAG, exc)
            return None

    # ── Regime/ADX history (transition signature) ─────────────────────────
    # Same source as `_regime_and_adx` below — `regime_engine.latest_result`
    # only exposes the latest emission, so for the trailing window we tail
    # the JSONL the engine writes to on every 5m close. Reads the trailing
    # ~256KB of the file (≈ 1-2 days of GBPUSD entries), filters for the
    # requested symbol, and returns the last `n` entries by timestamp order.
    @staticmethod
    def _regime_history(symbol: str, n: int,
                        path: str = TRANSITION_REGIME_LOG_PATH,
                        ) -> List[Dict[str, Any]]:
        """Return the last `n` regime emissions for `symbol`, oldest first.
        Empty list on any I/O / parse failure (caller treats that as
        'history unavailable' — never blocks)."""
        try:
            size = os.path.getsize(path)
            # Read at most the trailing 256KB. At ~1KB/line the file averages
            # ~256 entries per slice — plenty for a 6-bar window even with
            # multi-symbol noise. Increase if symbol density gets sparser.
            read_bytes = min(size, 262144)
            with open(path, "rb") as fh:
                fh.seek(size - read_bytes)
                tail = fh.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.warning("[%s] regime_history tail failed (%s): %s",
                           LOG_TAG, path, exc)
            return []
        sym_u = str(symbol).upper()
        # Drop the first (likely-partial) line.
        lines = tail.splitlines()[1:]
        out: List[Dict[str, Any]] = []
        for line in lines:
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if str(d.get("symbol") or "").upper() != sym_u:
                continue
            out.append({
                "timestamp": d.get("timestamp"),
                "regime": str(d.get("winning_regime") or "").upper(),
                "adx": d.get("ADX"),
            })
        # Sort by timestamp (ISO-8601 sorts lexicographically).
        out.sort(key=lambda r: str(r.get("timestamp") or ""))
        return out[-n:] if len(out) > n else out

    @staticmethod
    def _classify_regime_family(regime: str) -> str:
        """UP / DOWN / OTHER. Mirrors the 25-day audit's family classification."""
        if regime in ("STRONG_TREND_UP", "TREND_FORMING_UP", "BREAKOUT_FORMING_UP"):
            return "U"
        if regime in ("STRONG_TREND_DOWN", "TREND_FORMING_DOWN", "BREAKOUT_FORMING_DOWN"):
            return "D"
        return "O"

    @classmethod
    def _compute_transition_signature(cls, symbol: str,
                                      bars: Sequence[Bar],
                                      window: int,
                                      ) -> Optional[Dict[str, Any]]:
        """Compute flip_rate / adx_min / adx_mean / disp_pips over the
        trailing `window` bars (closes from `bars`; regime + ADX from the
        JSONL history). Returns the signature dict, or None when history
        is insufficient (caller treats that as 'signature unavailable' —
        signal not computable, filter does not apply)."""
        if window <= 0:
            return None
        if len(bars) < window + 1:
            return None
        # We need `window` regime emissions to compute (window - 1) family
        # transitions plus adx_min/mean. Read window+2 to give ourselves
        # margin for any alignment drift between bar boundaries and emit
        # timestamps.
        hist = cls._regime_history(symbol, window + 2)
        if len(hist) < window:
            return None
        recent = hist[-window:]
        fams = [cls._classify_regime_family(r["regime"]) for r in recent]
        flips = 0
        for i in range(1, len(fams)):
            a, b = fams[i - 1], fams[i]
            if (a == "U" and b == "D") or (a == "D" and b == "U"):
                flips += 1
        adxs: List[float] = []
        for r in recent:
            v = r.get("adx")
            if v is None:
                continue
            try:
                adxs.append(float(v))
            except (TypeError, ValueError):
                continue
        adx_min = min(adxs) if adxs else None
        adx_mean = (sum(adxs) / len(adxs)) if adxs else None
        # Displacement: close at current bar minus close `window` bars ago,
        # in pips. Signed.
        try:
            first_close = float(bars[-(window + 1)].close)
            last_close = float(bars[-1].close)
            disp_pips = (last_close - first_close) / PIP_SIZE
        except Exception:
            disp_pips = None
        return {
            "window_bars": window,
            "fams": "".join(fams),
            "flip_rate": int(flips),
            "adx_min": adx_min,
            "adx_mean": adx_mean,
            "disp_pips": disp_pips,
            "bars_with_adx": len(adxs),
            "history_emissions": len(recent),
        }

    # ── Regime + ADX read (lazy import) ────────────────────────────────────
    @staticmethod
    def _regime_and_adx(symbol: str) -> Tuple[Optional[str], Optional[float]]:
        """Latest in-memory regime_engine result. Same source EMA_PULLBACK's
        M5-override uses. Returns (regime, adx) or (None, None)."""
        try:
            import regime_engine
            rg = regime_engine.latest_result(symbol)
        except Exception as exc:
            logger.warning("[%s] regime_engine.latest_result failed: %s", LOG_TAG, exc)
            return None, None
        if not rg:
            return None, None
        reg = rg.get("winning_regime")
        adx = rg.get("ADX")
        try:
            adx_f = float(adx) if adx is not None else None
        except (TypeError, ValueError):
            adx_f = None
        return (str(reg).upper() if reg else None), adx_f

    @staticmethod
    def _regime_label_path(symbol: str) -> str:
        """label_path from the latest regime_engine emit. Empty string when
        unavailable. Values (regime_engine 6ccc542+): "hist" | "struct" |
        "range" | "range_break_promote". Only "range_break_promote" flags
        a promoted STRONG_TREND (RANGE_ROTATION→STRONG_TREND). Read live
        so a mid-fire regime override is picked up."""
        try:
            import regime_engine
            rg = regime_engine.latest_result(symbol)
        except Exception as exc:
            logger.warning("[%s] regime_engine.latest_result (label_path) "
                           "failed: %s", LOG_TAG, exc)
            return ""
        if not rg:
            return ""
        lp = rg.get("regime_label_path")
        return str(lp) if lp else ""

    def _detect(self,
                bars: Sequence[Bar],
                symbol: str = "GBPUSD",
                ) -> Tuple[Optional[_Evidence], str]:
        """Pure detection. Returns (evidence, reject_reason). Order:
          (a) Warmup / ATR availability
          (b) Structure-dir fresh + decisive       (cheap)
          (c) Regime ∉ RANGE/CHOP/COMPRESSION
          (d) ADX ≥ ADX_MIN
        """
        n = len(bars)
        if n < WARMUP_BARS:
            return None, f"warmup n={n}<{WARMUP_BARS}"

        atr_px = _atr(bars, ATR_PERIOD)
        if atr_px is None or atr_px <= 0:
            return None, "atr_unavailable"

        sd = self._structure_dir(symbol)
        if sd is None:
            return None, "structure_dir_unavailable"
        struct_dir, details = sd
        if struct_dir not in ("UP", "DOWN"):
            return None, f"structure_dir={struct_dir}"

        flip_bar_ts = details.get("flip_bar_ts")
        # Freshness check. htf_authority._structure_dir reads ts via
        # df["timestamp"], but candle_builder.get_df_raw exposes the column
        # as "time" — so in the live process flip_bar_ts is ALWAYS None
        # (confirmed against /opt/tradingbot/logs/htf_authority.jsonl, every
        # row has "structure_flip_bar_ts": null). Two paths:
        #   (a) ts-match path  — used when the primitive HAS a ts (offline
        #       replays whose df carries a "timestamp" column).
        #   (b) bars-replicate path — when flip_bar_ts is None, replicate the
        #       primitive's single-bar break check on bars[] directly: the
        #       current bar IS a fresh flip iff its close breaks the prior-N
        #       high/low in struct_dir. Mirrors htf_authority._structure_dir
        #       lines 225-238 for the i=last-bar case. STRUCT_N+min_break
        #       defaults match the primitive's env defaults (5, 0.0p).
        is_fresh: Optional[bool] = None
        fresh_path = "none"
        cur_ts_iso = bars[-1].timestamp.astimezone(timezone.utc).isoformat()
        if flip_bar_ts:
            # (a) — primitive supplied a timestamp; do the original string match.
            fresh_path = "ts_match"
            cur_ts_keys = {
                cur_ts_iso,
                cur_ts_iso.replace("+00:00", "Z"),
                cur_ts_iso[:19],
                cur_ts_iso[:19] + "+00:00",
                bars[-1].timestamp.replace(tzinfo=None).isoformat(),
                bars[-1].timestamp.replace(tzinfo=None).isoformat(sep=" "),
            }
            flip_ts_s = str(flip_bar_ts)
            flip_ts_19 = flip_ts_s.replace("T", " ")[:19]
            cur_ts_19  = cur_ts_iso.replace("T", " ")[:19]
            is_fresh = (flip_ts_s in cur_ts_keys) or (flip_ts_19 == cur_ts_19)
            if not is_fresh:
                return None, f"not_fresh flip_bar={flip_ts_s} cur={cur_ts_iso}"
        else:
            # (b) — fallback: live candle_builder df has no "timestamp" column,
            # primitive populated flip_bar_ts=None. Apply the primitive's break
            # check locally against the current bar.
            fresh_path = "bars_replicate"
            struct_n = _env_int("STRUCT_LEADS_N", 5)
            struct_min_break = _env_float("STRUCT_LEADS_MIN_BREAK_PIPS", 0.0)
            if len(bars) < struct_n + 1:
                return None, f"not_fresh insufficient_bars n={len(bars)}<{struct_n + 1}"
            window = bars[-(struct_n + 1):-1]   # the N bars BEFORE current
            prior_high = max(float(b.high) for b in window)
            prior_low  = min(float(b.low)  for b in window)
            cur_close  = float(bars[-1].close)
            break_pad  = float(struct_min_break) * PIP_SIZE
            if struct_dir == "DOWN":
                is_fresh = cur_close < (prior_low - break_pad)
                if not is_fresh:
                    return None, (
                        f"not_fresh fallback dir=DOWN "
                        f"cur_close={cur_close:.5f}>=prior_low={prior_low:.5f}"
                        f"(N={struct_n} pad={break_pad:.2f})"
                    )
                # Backfill details so downstream code (break_pips / SL geometry)
                # has the same inputs it would have had with a populated ts.
                details = dict(details)
                details["prior_low"] = prior_low
                details["close_at_flip"] = cur_close
            else:  # UP (struct_dir already validated as UP/DOWN upstream)
                is_fresh = cur_close > (prior_high + break_pad)
                if not is_fresh:
                    return None, (
                        f"not_fresh fallback dir=UP "
                        f"cur_close={cur_close:.5f}<=prior_high={prior_high:.5f}"
                        f"(N={struct_n} pad={break_pad:.2f})"
                    )
                details = dict(details)
                details["prior_high"] = prior_high
                details["close_at_flip"] = cur_close
            # Synthesise a flip_bar_ts so downstream telemetry still has it.
            # Mirror path (a)'s flip_ts_s so the evidence builder at the bottom
            # (flip_bar_ts=flip_ts_s) has a value — without this the bars-
            # replicate path raises UnboundLocalError on every fire candidate.
            flip_bar_ts = cur_ts_iso
            flip_ts_s = cur_ts_iso

        close_at_flip = float(details.get("close_at_flip") or bars[-1].close)
        if struct_dir == "UP":
            prior_swing = details.get("prior_high")
            if prior_swing is None:
                return None, "missing_prior_high"
            break_px = close_at_flip - float(prior_swing)
        else:
            prior_swing = details.get("prior_low")
            if prior_swing is None:
                return None, "missing_prior_low"
            break_px = float(prior_swing) - close_at_flip
        break_pips = break_px / PIP_SIZE
        # ── Freshness guard for loosened-only entries (2026-06-16) ─────
        # When STRUCTURE_BREAK_GRIND_ENABLED=1 has lowered DECISIVE_PIPS
        # below 3.0, any entry whose break_pips is BETWEEN the loosened
        # threshold and the original 3.0p must also verify that the
        # current bar timestamp matches the EXPECTED just-closed 5M
        # bucket (floor(now, 5min)). Loosened-only entries are exactly
        # the population introduced by the relaxation, so this stale-
        # bar reject prevents the gate from accepting a fire computed
        # against a building bar in any future race window. Entries
        # that pass at the original 3.0 threshold are unchanged.
        # Flag-gated. When _LOOSENED_FRESHNESS_GUARD_ENABLED is False
        # (default), _is_loosened_only is forced False so the bar-bucket
        # timing check below and its reject at line ~812 are inert. The
        # code stays present for telemetry/re-arm. Break-detection (660-
        # 737) and displacement-confirm (886-933) are unaffected.
        _is_loosened_only = (
            _LOOSENED_FRESHNESS_GUARD_ENABLED
            and break_pips < DECISIVE_PIPS_ORIGINAL
            and break_pips >= DECISIVE_PIPS
        )
        _freshness_pass = True  # vacuously True for original-threshold fires
        if _is_loosened_only:
            try:
                _dispatch_now = datetime.now(timezone.utc)
                _expected_bucket_epoch = (
                    int(_dispatch_now.timestamp()) // 300 * 300
                )
                _bar_ts = bars[-1].timestamp.astimezone(timezone.utc)
                _bar_bucket_epoch = int(_bar_ts.timestamp())
                _freshness_pass = (_bar_bucket_epoch == _expected_bucket_epoch)
            except Exception:
                _freshness_pass = False
            if not _freshness_pass:
                logger.info(
                    "STRUCT_BREAK_FRESHNESS_GUARD:reject bar_ts=%s "
                    "expected_bucket_epoch=%s break_pips=%.2f",
                    bars[-1].timestamp.isoformat() if bars else "?",
                    _expected_bucket_epoch, break_pips,
                )
        # ── Shadow log (every eval reaching the gate) ──────────────────
        _decision_original = (
            "fire" if break_pips >= DECISIVE_PIPS_ORIGINAL
            else f"skip:break_below_decisive_{break_pips:.2f}p"
        )
        _decision_loosened = (
            "fire" if break_pips >= DECISIVE_PIPS
            else f"skip:break_below_decisive_{break_pips:.2f}p"
        )
        if _GRIND_SHADOW_ENABLED:
            try:
                _shadow_row = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "symbol": str(symbol).upper(),
                    "bar_ts": bars[-1].timestamp.astimezone(timezone.utc).isoformat() if bars else None,
                    "struct_dir": struct_dir,
                    "break_pips": float(break_pips),
                    "decision_original": _decision_original,
                    "decision_loosened": _decision_loosened,
                    "would_pass_freshness_guard": bool(_freshness_pass),
                    "fresh_path": fresh_path,
                    "decisive_orig": DECISIVE_PIPS_ORIGINAL,
                    "decisive_loose": DECISIVE_PIPS,
                }
                with open(_GRIND_SHADOW_PATH, "a") as _fh:
                    _fh.write(json.dumps(_shadow_row) + "\n")
            except Exception as _shadow_exc:
                logger.warning("[%s] grind shadow-log failed: %s",
                               LOG_TAG, _shadow_exc)

        # Block any loosened-only entry that failed the freshness guard.
        if _is_loosened_only and not _freshness_pass:
            return None, (f"break_below_decisive_freshness_guard "
                          f"break_pips={break_pips:.2f}p loose={DECISIVE_PIPS:.2f}p")

        if break_pips < DECISIVE_PIPS:
            return None, (f"break_below_decisive {break_pips:.2f}p<"
                          f"{DECISIVE_PIPS:.2f}p")

        # Regime gate (whipsaw guard).
        # Gate A only: RANGE/CHOP fail. Bypassed under REGIME_MATRIX_ENABLED
        # (matrix owns enablement). Gate B (ADX floor) and Gate C (retest
        # routing) are setup mechanics and remain enforced regardless of
        # the matrix flag.
        regime, adx = self._regime_and_adx(symbol)
        if regime is None:
            return None, "regime_unavailable"
        if regime in RANGE_REGIMES and not _REGIME_MATRIX_ENABLED:
            logger.info(
                "[%s] regime_filter_block sym=%s dir=%s regime=%s "
                "range_set=%s adx=%s (2026-07-07 restoration; "
                "STRUCTURE_BREAK_REGIME_FILTER_ENABLED=0 to disable)",
                LOG_TAG, symbol, struct_dir, regime,
                sorted(RANGE_REGIMES),
                (f"{adx:.1f}" if adx is not None else "?"),
            )
            return None, f"regime_blocks={regime}"
        if adx is None:
            return None, "adx_unavailable"
        if adx < ADX_MIN:
            logger.info(
                "[%s] adx_floor_block sym=%s dir=%s adx=%.2f<%.2f "
                "(STRUCTURE_BREAK_ADX_MIN env to tune)",
                LOG_TAG, symbol, struct_dir, adx, ADX_MIN,
            )
            return None, f"adx_below_floor adx={adx:.1f}<{ADX_MIN:.1f}"

        # ── Transition-signature compute + filter (always log; block iff
        #    flag-enabled AND flip_rate triggers AND ADX/disp fail). ─────
        sig = self._compute_transition_signature(symbol, bars, TRANSITION_WINDOW_BARS)
        flip_direction = "DOWN" if struct_dir == "DOWN" else "UP"
        would_block = False
        block_reason = ""
        sig_status = "computed" if sig is not None else "unavailable"
        if sig is not None and sig["flip_rate"] is not None \
                and sig["flip_rate"] >= TRANSITION_FLIP_MIN:
            # Filter applies. Both axes must pass.
            adx_ok = (sig["adx_min"] is not None
                      and sig["adx_min"] >= TRANSITION_ADX_WIN_MIN)
            if flip_direction == "DOWN":
                disp_ok = (sig["disp_pips"] is not None
                           and sig["disp_pips"] <= -float(TRANSITION_DISP_MIN_PIPS))
            else:
                disp_ok = (sig["disp_pips"] is not None
                           and sig["disp_pips"] >= float(TRANSITION_DISP_MIN_PIPS))
            if not (adx_ok and disp_ok):
                would_block = True
                _adx_min_s = (f"{sig['adx_min']:.2f}"
                              if sig['adx_min'] is not None else "?")
                _disp_s = (f"{sig['disp_pips']:+.2f}p"
                           if sig['disp_pips'] is not None else "?")
                block_reason = (
                    f"transition_chop flip={sig['flip_rate']} "
                    f"fams={sig['fams']} adx_min={_adx_min_s} "
                    f"(need>={TRANSITION_ADX_WIN_MIN:.1f}) "
                    f"disp={_disp_s} "
                    f"(need {'<=-' if flip_direction == 'DOWN' else '>=+'}"
                    f"{TRANSITION_DISP_MIN_PIPS:.1f}p) "
                    f"dir={flip_direction}"
                )
        # Always log telemetry — accumulating record regardless of flag.
        if sig is not None:
            logger.info(
                "[%s] %s TRANSITION_SIG dir=%s flip=%d fams=%s "
                "adx_min=%s adx_mean=%s disp=%s "
                "would_block=%s filter_enabled=%s",
                LOG_TAG, symbol, flip_direction, sig["flip_rate"], sig["fams"],
                (f"{sig['adx_min']:.2f}" if sig['adx_min'] is not None else "None"),
                (f"{sig['adx_mean']:.2f}" if sig['adx_mean'] is not None else "None"),
                (f"{sig['disp_pips']:+.2f}p" if sig['disp_pips'] is not None else "None"),
                would_block, TRANSITION_FILTER_ENABLED,
            )
        else:
            logger.info(
                "[%s] %s TRANSITION_SIG dir=%s status=unavailable "
                "filter_enabled=%s",
                LOG_TAG, symbol, flip_direction, TRANSITION_FILTER_ENABLED,
            )
        # Enforcing branch — only blocks when flag is on AND would_block.
        if TRANSITION_FILTER_ENABLED and would_block:
            return None, block_reason

        # ── Signed-displacement entry confirmation (2026-06-15) ─────────
        # Stand-alone gate: every flip must show net price displacement in
        # the break direction over the trailing DISP_CONFIRM_WINDOW_BARS.
        # disp computed directly from bars (no regime-history dependency).
        # Stacks INDEPENDENTLY with the transition filter above — both
        # always log; either can block when its own flag is enabled.
        disp_W = int(DISP_CONFIRM_WINDOW_BARS)
        disp_confirm_pips: Optional[float] = None
        would_block_disp = False
        disp_block_reason = ""
        if disp_W > 0 and len(bars) >= disp_W + 1:
            try:
                disp_confirm_pips = (
                    float(bars[-1].close) - float(bars[-(disp_W + 1)].close)
                ) / PIP_SIZE
            except Exception:
                disp_confirm_pips = None
        if disp_confirm_pips is not None:
            if flip_direction == "DOWN":
                disp_agree_ok = disp_confirm_pips <= -float(DISP_CONFIRM_MIN_PIPS)
                _need_s = f"<=-{DISP_CONFIRM_MIN_PIPS:.1f}p"
            else:
                disp_agree_ok = disp_confirm_pips >=  float(DISP_CONFIRM_MIN_PIPS)
                _need_s = f">=+{DISP_CONFIRM_MIN_PIPS:.1f}p"
            if not disp_agree_ok:
                would_block_disp = True
                disp_block_reason = (
                    f"disp_disagree disp={disp_confirm_pips:+.2f}p "
                    f"(need {_need_s}) dir={flip_direction} "
                    f"window={disp_W}b"
                )
        # Always log telemetry — accumulating record regardless of flag.
        if disp_confirm_pips is not None:
            logger.info(
                "[%s] %s DISP_CONFIRM dir=%s disp=%+.2fp window=%db "
                "would_block_disp=%s confirm_enabled=%s",
                LOG_TAG, symbol, flip_direction, disp_confirm_pips, disp_W,
                would_block_disp, DISP_CONFIRM_ENABLED,
            )
        else:
            logger.info(
                "[%s] %s DISP_CONFIRM dir=%s status=unavailable window=%db "
                "confirm_enabled=%s",
                LOG_TAG, symbol, flip_direction, disp_W, DISP_CONFIRM_ENABLED,
            )
        # Enforcing branch — only blocks when flag is on AND would_block_disp.
        if DISP_CONFIRM_ENABLED and would_block_disp:
            return None, disp_block_reason

        # Risk geometry. SL = break distance + 0.5*ATR (in price units),
        # then clamp to [MIN_SL_PIPS, MAX_SL_PIPS].
        atr_pips = atr_px / PIP_SIZE
        # The flip happened against a swing extreme; entry is at the flip
        # bar's close, which has already moved `break_pips` BEYOND that
        # swing. Place SL at swing + atr_buffer (away from entry), i.e.
        # SL distance from entry = break_pips + SL_BUFFER_ATR_MULT*atr_pips.
        raw_sl_pips = break_pips + SL_BUFFER_ATR_MULT * atr_pips
        sl_pips = max(MIN_SL_PIPS, min(MAX_SL_PIPS, raw_sl_pips))

        direction = "SHORT" if struct_dir == "DOWN" else "LONG"
        ev = _Evidence(
            direction=direction,
            flip_bar_ts=flip_ts_s,
            prior_swing=float(prior_swing),
            close_at_flip=close_at_flip,
            break_pips=break_pips,
            atr_price=atr_px,
            regime=regime,
            adx=adx,
            sl_pips=sl_pips,
            sl_components={
                "break_pips": round(break_pips, 3),
                "atr_pips": round(atr_pips, 3),
                "buffer_pips": round(SL_BUFFER_ATR_MULT * atr_pips, 3),
                "raw_sl_pips": round(raw_sl_pips, 3),
                "clamped_sl_pips": round(sl_pips, 3),
                "min_sl_pips": MIN_SL_PIPS,
                "max_sl_pips": MAX_SL_PIPS,
            },
            transition_sig=sig,
            transition_would_block=would_block,
            transition_block_reason=block_reason,
            disp_confirm_pips=disp_confirm_pips,
            disp_confirm_window_bars=disp_W,
            disp_confirm_would_block=would_block_disp,
            disp_confirm_block_reason=disp_block_reason,
            regime_label_path=self._regime_label_path(symbol),
        )
        return ev, "ok"

    # ── Retest-limit lifecycle helpers ─────────────────────────────────────
    # A pending LIMIT is placed on a fresh decisive break instead of firing
    # at the flip-bar close. On each subsequent evaluate() call the last-
    # closed bar is checked for a fill (bar.low touches LIMIT for LONG,
    # bar.high touches LIMIT for SHORT). If age exceeds EXPIRY_BARS, the
    # pending is cancelled. All events go to _RETEST_LOG_PATH.

    def _classify_entry_path(self, ev: "_Evidence") -> Tuple[str, bool, str]:
        """Return (entry_path, promoted, reason).

          entry_path : "CHASE" | "RETEST"
          promoted   : True iff regime is a range_break_promote STRONG_TREND
                       (label_path == "range_break_promote").
          reason     : short greppable tag used in the telemetry row.

        Gate:
          - Genuine STRONG_TREND_{UP,DOWN} (label_path != range_break_promote)
              → CHASE (trend-aligned break, don't wait for a pullback).
          - TREND_FORMING_{UP,DOWN}
              → RETEST (forming trend — more likely to pull back to the level).
          - Promoted STRONG_TREND (label_path == "range_break_promote", any
            direction) → RETEST (structurally a range-edge breakout, treat as
            a forming break).
          - Any other regime SB fires in post-37b0054 (BREAKOUT_FORMING_*,
            COMPRESSION, …) → RETEST_GATE_DEFAULT_PATH (default RETEST — see
            the module-level rationale above).

        Never blocks; never raises. On missing regime it defers to the
        default path so a data-availability hiccup does not silently switch
        entry semantics.
        """
        regime = str(ev.regime or "").upper()
        label_path = str(ev.regime_label_path or "").strip()
        promoted = (label_path == "range_break_promote")
        strong_trend = regime in ("STRONG_TREND_UP", "STRONG_TREND_DOWN")
        trend_forming = regime in ("TREND_FORMING_UP", "TREND_FORMING_DOWN")

        if strong_trend and not promoted:
            return "CHASE", False, "genuine_strong_trend"
        if strong_trend and promoted:
            if RETEST_GATE_STRONG_TREND_PROMOTED:
                return "RETEST", True, "promoted_strong_trend_range_edge"
            return "CHASE", True, "promoted_strong_trend_gate_off"
        if trend_forming:
            return "RETEST", False, "trend_forming"
        if not regime:
            return RETEST_GATE_DEFAULT_PATH, False, "regime_unavailable"
        return RETEST_GATE_DEFAULT_PATH, False, f"default_for_{regime.lower()}"

    def _retest_limit_price(self, direction: str, level: float) -> float:
        """LONG limit sits 1p ABOVE the broken level (price falls to it).
        SHORT limit sits 1p BELOW the broken level (price rises to it)."""
        buf = float(RETEST_LIMIT_BUFFER_PIPS) * PIP_SIZE
        return float(level) + buf if direction == "LONG" else float(level) - buf

    def _retest_touched(self, pending: "_PendingRetest", last_bar: Bar) -> bool:
        """Did the just-closed 5m bar's low/high cross the LIMIT price?"""
        if pending.direction == "LONG":
            return float(last_bar.low) <= float(pending.limit_price)
        return float(last_bar.high) >= float(pending.limit_price)

    def _retest_expired(self, pending: "_PendingRetest", ts_utc: datetime) -> bool:
        return ts_utc >= pending.expiry_ts

    def _bars_waited(self, pending: "_PendingRetest", ts_utc: datetime) -> int:
        """Whole 5m bars elapsed since PLACE (0 on the placement bar)."""
        secs = (ts_utc - pending.placed_ts).total_seconds()
        return max(0, int(round(secs / 300.0)))

    def _place_pending_retest(self, epic: str, ev: "_Evidence", ts_utc: datetime,
                              debug_carry: Dict[str, Any]) -> None:
        """Store (or REPLACE) a pending retest limit for the epic and log."""
        direction_signal = "BUY" if ev.direction == "LONG" else "SELL"
        mode = MODE_NAME_LONG if ev.direction == "LONG" else MODE_NAME_SHORT
        limit_price = self._retest_limit_price(ev.direction, ev.prior_swing)
        # placed_ts = flip-bar close ts; expiry = flip-bar + EXPIRY_BARS 5m bars.
        # The NEXT evaluate() call (t+5m) is bars_waited=1.
        expiry_ts = ts_utc + timedelta(minutes=5 * int(RETEST_EXPIRY_BARS))
        prior = self._pending_retest_by_epic.get(epic)
        pending = _PendingRetest(
            epic=epic,
            direction=ev.direction,
            direction_signal=direction_signal,
            mode=mode,
            level=float(ev.prior_swing),
            limit_price=float(limit_price),
            buffer_pips=float(RETEST_LIMIT_BUFFER_PIPS),
            close_at_flip=float(ev.close_at_flip),
            break_pips_at_flip=float(ev.break_pips),
            atr_price=float(ev.atr_price),
            regime=str(ev.regime),
            adx=float(ev.adx),
            flip_bar_ts=str(ev.flip_bar_ts),
            placed_ts=ts_utc,
            expiry_ts=expiry_ts,
            debug_carry=dict(debug_carry or {}),
            sl_components_place=dict(ev.sl_components or {}),
            regime_label_path=str(ev.regime_label_path or ""),
        )
        self._pending_retest_by_epic[epic] = pending
        event = "REPLACED" if prior is not None else "PLACED"
        logger.info(
            "[%s] %s %s retest_limit %s level=%.5f limit=%.5f buffer=%.2fp "
            "placed_bar=%s expiry_bar=%s (in %d bars) close_at_flip=%.5f "
            "break_at_flip=%.2fp",
            LOG_TAG, epic, ev.direction, event,
            pending.level, pending.limit_price, pending.buffer_pips,
            pending.placed_ts.isoformat(), pending.expiry_ts.isoformat(),
            int(RETEST_EXPIRY_BARS),
            pending.close_at_flip, pending.break_pips_at_flip,
        )
        _write_retest_log({
            "event": event,
            "ts": ts_utc.isoformat(),
            "epic": epic,
            "direction": ev.direction,
            "level": pending.level,
            "limit_price": pending.limit_price,
            "buffer_pips": pending.buffer_pips,
            "placed_ts": pending.placed_ts.isoformat(),
            "expiry_ts": pending.expiry_ts.isoformat(),
            "expiry_bars": int(RETEST_EXPIRY_BARS),
            "close_at_flip": pending.close_at_flip,
            "break_at_flip_pips": pending.break_pips_at_flip,
            "atr_price_at_flip": pending.atr_price,
            "regime_at_flip": pending.regime,
            "regime_label_path_at_flip": pending.regime_label_path,
            "promoted_at_flip": (pending.regime_label_path == "range_break_promote"),
            "adx_at_flip": pending.adx,
            "flip_bar_ts": pending.flip_bar_ts,
            "prior_pending_level": (prior.level if prior else None),
            "prior_pending_direction": (prior.direction if prior else None),
        })

    def _expire_pending_retest(self, epic: str, pending: "_PendingRetest",
                               ts_utc: datetime) -> None:
        logger.info(
            "[%s] %s %s retest_limit EXPIRED level=%.5f limit=%.5f "
            "waited=%d bars (runaway, no fill)",
            LOG_TAG, epic, pending.direction,
            pending.level, pending.limit_price,
            self._bars_waited(pending, ts_utc),
        )
        _write_retest_log({
            "event": "EXPIRED",
            "ts": ts_utc.isoformat(),
            "epic": epic,
            "direction": pending.direction,
            "level": pending.level,
            "limit_price": pending.limit_price,
            "buffer_pips": pending.buffer_pips,
            "placed_ts": pending.placed_ts.isoformat(),
            "expiry_ts": pending.expiry_ts.isoformat(),
            "bars_waited": self._bars_waited(pending, ts_utc),
            "close_at_flip": pending.close_at_flip,
            "break_at_flip_pips": pending.break_pips_at_flip,
            "regime_at_flip": pending.regime,
            "regime_label_path_at_flip": pending.regime_label_path,
            "promoted_at_flip": (pending.regime_label_path == "range_break_promote"),
        })

    def _build_retest_fill_decision(self, pending: "_PendingRetest",
                                    ts_utc: datetime) -> Optional["StrategyDecision"]:
        """Build the StrategyDecision when the pending fills. Entry = the
        LIMIT price. SL is recomputed from the retest geometry, NOT the
        original flip-bar break_pips, so the trade opens with a naturally
        tighter stop (|entry - level| = BUFFER instead of break_pips_at_flip).
        """
        atr_pips_fill = float(pending.atr_price) / PIP_SIZE
        break_pips_fill = float(pending.buffer_pips)  # |entry - level|
        raw_sl_pips_fill = break_pips_fill + SL_BUFFER_ATR_MULT * atr_pips_fill
        sl_pips_fill = max(MIN_SL_PIPS, min(MAX_SL_PIPS, raw_sl_pips_fill))
        tp_pips = float(RUNNER_TP_PIPS)
        entry_px = float(pending.limit_price)
        bars_waited = self._bars_waited(pending, ts_utc)

        reason = (
            f"structure_break_{pending.direction_signal.lower()} "
            f"entry=retest_limit "
            f"flip={pending.direction} break_at_flip={pending.break_pips_at_flip:.2f}p "
            f"level={pending.level:.5f} limit={entry_px:.5f} "
            f"buffer={pending.buffer_pips:.2f}p bars_waited={bars_waited} "
            f"atr={atr_pips_fill:.2f}p regime={pending.regime} adx={pending.adx:.1f} "
            f"SL={sl_pips_fill:.1f}p TP={tp_pips:.1f}p"
        )

        debug: Dict[str, Any] = dict(pending.debug_carry or {})
        debug.update({
            "entry_mode": "retest_limit",
            "retest_limit_price": entry_px,
            "retest_buffer_pips": pending.buffer_pips,
            "retest_bars_waited": bars_waited,
            "retest_placed_ts": pending.placed_ts.isoformat(),
            "retest_expiry_ts": pending.expiry_ts.isoformat(),
            "retest_expiry_bars": int(RETEST_EXPIRY_BARS),
            "chase_would_have_been_entry": pending.close_at_flip,
            "chase_would_have_been_break_pips": pending.break_pips_at_flip,
            "sl_components": {
                "break_pips": round(break_pips_fill, 3),   # = buffer, at the fill
                "atr_pips": round(atr_pips_fill, 3),
                "buffer_pips": round(SL_BUFFER_ATR_MULT * atr_pips_fill, 3),
                "raw_sl_pips": round(raw_sl_pips_fill, 3),
                "clamped_sl_pips": round(sl_pips_fill, 3),
                "min_sl_pips": MIN_SL_PIPS,
                "max_sl_pips": MAX_SL_PIPS,
            },
            "sl_components_at_place": pending.sl_components_place,
        })

        # ── Break-level + level-distance stamps at RETEST FILL (2026-07-24)
        # Flip-bar break-level fields come from `pending` (the flip-time
        # snapshot). Level-distance fields are RECOMPUTED here at the fill
        # bar using entry_px = pending.limit_price — the retest fills at a
        # different bar than the flip, so "distance at entry" is only
        # honest against the current 5m frame from candle_builder (evaluate()
        # does not receive closes_ind/highs_ind/lows_ind on this branch).
        # Any failure is DEBUG-logged and never blocks the fill.
        try:
            debug["prior_swing"] = float(pending.level)
            debug["close_at_flip"] = float(pending.close_at_flip)
            debug["sb_break_pips"] = round(float(pending.break_pips_at_flip), 3)
            debug["sb_atr_pips"] = round(float(pending.atr_price) / PIP_SIZE, 3)
            debug["sb_entry_path"] = "RETEST"
            debug["flip_bar_ts"] = _sb_normalize_flip_bar_ts(pending.flip_bar_ts)
        except Exception as _sb_stamp_exc:  # noqa: BLE001
            logger.debug("[%s] sb break-level stamp (retest) failed: %s",
                         LOG_TAG, _sb_stamp_exc)
        try:
            _sb_lvl = _sb_compute_level_telemetry(
                entry_px=float(entry_px),
                closes=None,
                highs=None,
                lows=None,
            )
            if _sb_lvl:
                debug.update(_sb_lvl)
        except Exception as _sb_lvl_exc:  # noqa: BLE001
            logger.debug("[%s] sb level-distance stamp (retest) failed: %s",
                         LOG_TAG, _sb_lvl_exc)

        try:
            from strategy_logic import StrategyDecision
        except Exception as exc:
            logger.error("[%s] StrategyDecision import failed on retest fill: %s",
                         LOG_TAG, exc)
            return None

        decision = StrategyDecision(
            symbol="GBPUSD",
            regime="STRUCTURE_BREAK",
            signal=pending.direction_signal,
            mode=pending.mode,
            entry=entry_px,
            sl=round(sl_pips_fill, 2),
            tp=round(tp_pips, 2),
            use_trailing_stop=False,
            reason=reason,
            debug=debug,
            pip_size=PIP_SIZE,
        )

        logger.info(
            "[%s] %s %s retest_limit FILLED entry=%.5f bars_waited=%d "
            "SL=%.1fp (vs chase SL≈%.1fp) TP=%.1fp level=%.5f",
            LOG_TAG, pending.epic, pending.direction,
            entry_px, bars_waited, sl_pips_fill,
            max(MIN_SL_PIPS, min(MAX_SL_PIPS,
                pending.break_pips_at_flip + SL_BUFFER_ATR_MULT * atr_pips_fill)),
            tp_pips, pending.level,
        )
        _write_retest_log({
            "event": "FILLED",
            "ts": ts_utc.isoformat(),
            "epic": pending.epic,
            "direction": pending.direction,
            "level": pending.level,
            "limit_price": entry_px,
            "buffer_pips": pending.buffer_pips,
            "placed_ts": pending.placed_ts.isoformat(),
            "bars_waited": bars_waited,
            "regime_at_flip": pending.regime,
            "regime_label_path_at_flip": pending.regime_label_path,
            "promoted_at_flip": (pending.regime_label_path == "range_break_promote"),
            "sl_pips_fill": round(sl_pips_fill, 2),
            "sl_pips_chase_would_have_been": round(
                max(MIN_SL_PIPS, min(MAX_SL_PIPS,
                    pending.break_pips_at_flip + SL_BUFFER_ATR_MULT * atr_pips_fill)), 2),
            "tp_pips": round(tp_pips, 2),
            "atr_pips_at_place": round(atr_pips_fill, 3),
            "close_at_flip": pending.close_at_flip,
            "break_at_flip_pips": pending.break_pips_at_flip,
            "chase_entry_would_have_been": pending.close_at_flip,
            "entry_improvement_pips": round(
                pending.close_at_flip - entry_px if pending.direction == "LONG"
                else entry_px - pending.close_at_flip, 2),
        })
        return decision

    def evaluate(self,
                 symbol: str,
                 epic: str,
                 ts: datetime,
                 bars: Sequence[Bar],
                 has_open_long: bool = False,
                 has_open_short: bool = False,
                 closes_ind: Optional[Sequence[float]] = None,
                 highs_ind: Optional[Sequence[float]] = None,
                 lows_ind: Optional[Sequence[float]] = None,
                 brake_adx_at_bar: Optional[float] = None,
                 brake_adx_source: Optional[str] = None,
                 ) -> Optional["StrategyDecision"]:
        """Called on each new 5m close for GBPUSD. Returns a
        StrategyDecision on a fresh decisive flip in a non-range regime."""
        if not ENABLED or str(symbol).upper() != "GBPUSD":
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

        # ── Pending retest-limit lifecycle (2026-07-07) ───────────────────
        # Runs BEFORE cooldown and detection so a queued limit gets checked
        # regardless of new-fire cooldown. A FILL returns immediately with
        # the retest decision; an EXPIRE clears the pending and falls
        # through so this bar may still start a fresh break. WAITING falls
        # through so a fresh break can REPLACE the pending.
        if RETEST_ENTRY_ENABLED:
            pending = self._pending_retest_by_epic.get(epic)
            if pending is not None:
                if bars and self._retest_touched(pending, bars[-1]):
                    fill_decision = self._build_retest_fill_decision(pending, ts)
                    # Clear pending regardless of decision build outcome so
                    # a rejected build does not leave a stuck limit.
                    self._pending_retest_by_epic.pop(epic, None)
                    if fill_decision is not None:
                        # Cooldown starts on actual trade OPEN (fill),
                        # matching the byte-identical-off behaviour.
                        self._last_fire_ts_by_epic[epic] = ts
                    return fill_decision
                if self._retest_expired(pending, ts):
                    self._expire_pending_retest(epic, pending, ts)
                    self._pending_retest_by_epic.pop(epic, None)
                    # Fall through — this bar may start a fresh break.

        if not self._cooldown_ok(epic, ts):
            return None

        ev, reject = self._detect(bars, symbol=symbol)
        if ev is None:
            if reject and reject != "ok":
                logger.debug("[%s] %s skip: %s", LOG_TAG, symbol, reject)
            return None

        direction_signal = "BUY" if ev.direction == "LONG" else "SELL"
        mode = MODE_NAME_LONG if ev.direction == "LONG" else MODE_NAME_SHORT

        # ── Pair-wide slot enforcement (2026-06-15) ────────────────────────
        # ONE STRUCTURE_BREAK position per epic at a time, regardless of
        # direction. Prevents the same-direction-commit hazard where, after
        # the 60-min cooldown clears while a runner is still open, an
        # opposite-direction structure flip would otherwise open the other
        # slot and commit the bot to BOTH legs of the move simultaneously
        # (incoherent for a "ride the new leg" strategy; runners commonly
        # stay open >60 min under the 80p broker TP + continuous trail).
        # Same-direction is also blocked here (subsumes the prior per-slot
        # check). After close, the existing cooldown governs re-entry.
        # Slots are STRUCTURE_BREAK-only (the autobot dispatch passes
        # has_active_trade_for_mode(MODE_NAME_L/_S)) — does NOT block on
        # EMA_PULLBACK / BB_BOUNCE / etc.
        if has_open_long or has_open_short:
            open_side = "LONG" if has_open_long else "SHORT"
            logger.debug(
                "[%s] %s %s fire suppressed: STRUCTURE_BREAK %s already open "
                "(pair-wide slot — opposite direction blocked until close)",
                LOG_TAG, symbol, ev.direction, open_side,
            )
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
            from news_release_window import is_in_release_window
            _nrw_blocked, _nrw_reason = is_in_release_window(ts)
            if _nrw_blocked:
                logger.info(
                    "[NEWS_WINDOW_BLOCK] strategy=GBPUSD_STRUCTURE_BREAK %s %s reason=%s",
                    symbol, ev.direction, _nrw_reason,
                )
                return None
        except Exception:
            pass  # fail-open on suppressor error

        # ── N-bar HOLD SHADOW gate (added 2026-06-24) ──────────────────
        # Compute shadow_hold_ok: do the last HOLD_BARS bars (default 2)
        # ALL close beyond the structural swing that pre-existed them by
        # >= DECISIVE_PIPS? L_hold uses the same N as the live freshness
        # path (STRUCT_LEADS_N, default 5), windowed to EXCLUDE bars
        # being checked. Telemetry-only by default; ENFORCE=1 promotes
        # to a real gate without rebuild.
        shadow_rec: Optional[Dict[str, Any]] = None
        shadow_hold_ok: Optional[bool] = None
        if HOLD_SHADOW_ENABLED or HOLD_ENFORCE:
            try:
                hold_n_for_level = _env_int("STRUCT_LEADS_N", 5)
                hold_h = max(1, int(HOLD_BARS))
                need_bars = hold_n_for_level + hold_h
                if len(bars) < need_bars:
                    shadow_rec = {
                        "shadow_warmup_skip": True,
                        "have_bars": len(bars),
                        "need_bars": need_bars,
                    }
                else:
                    # Level window EXCLUDES the hold_h bars being checked.
                    # Examples (default N=5, H=2): bars[-7:-2] → 5 bars,
                    # immediately before bars[-2..-1] which are checked.
                    level_window = bars[-(hold_n_for_level + hold_h):-hold_h]
                    if ev.direction == "LONG":  # UP break
                        L_hold = max(float(b.high) for b in level_window)
                        threshold_px = float(HOLD_THRESHOLD_PIPS) * PIP_SIZE
                        per_bar = []
                        for k in range(1, hold_h + 1):
                            c = float(bars[-k].close)
                            beyond_px = c - L_hold
                            beyond_pips = beyond_px / PIP_SIZE
                            held = (beyond_px >= threshold_px)
                            per_bar.append({
                                "offset": -k,
                                "close": round(c, 5),
                                "beyond_pips": round(beyond_pips, 3),
                                "held": bool(held),
                            })
                        all_held = all(b["held"] for b in per_bar)
                    else:  # SHORT / DOWN break
                        L_hold = min(float(b.low) for b in level_window)
                        threshold_px = float(HOLD_THRESHOLD_PIPS) * PIP_SIZE
                        per_bar = []
                        for k in range(1, hold_h + 1):
                            c = float(bars[-k].close)
                            beyond_px = L_hold - c
                            beyond_pips = beyond_px / PIP_SIZE
                            held = (beyond_px >= threshold_px)
                            per_bar.append({
                                "offset": -k,
                                "close": round(c, 5),
                                "beyond_pips": round(beyond_pips, 3),
                                "held": bool(held),
                            })
                        all_held = all(b["held"] for b in per_bar)
                    shadow_hold_ok = bool(all_held)
                    block_reasons: List[str] = []
                    if not shadow_hold_ok:
                        for b in per_bar:
                            if not b["held"]:
                                block_reasons.append(
                                    f"bar[{b['offset']}].close beyond={b['beyond_pips']:+.2f}p"
                                    f"<{float(HOLD_THRESHOLD_PIPS):.2f}p"
                                )
                    shadow_rec = {
                        "shadow_hold_ok": shadow_hold_ok,
                        "hold_bars": hold_h,
                        "struct_n_for_level": hold_n_for_level,
                        "L_hold": round(L_hold, 5),
                        "threshold_pips": float(HOLD_THRESHOLD_PIPS),
                        "decisive_break_pips": float(DECISIVE_PIPS),
                        "per_bar": per_bar,
                        "block_reasons": block_reasons,
                        "shadow_enforce": bool(HOLD_ENFORCE),
                        "level_window_start_offset": -(hold_n_for_level + hold_h),
                        "level_window_end_offset": -hold_h,
                    }
            except Exception as _shadow_exc:
                logger.warning(
                    "[%s] hold_shadow compute failed: %s", LOG_TAG, _shadow_exc,
                )
                shadow_rec = {"shadow_compute_error": str(_shadow_exc)}

        # Enforce path: when ENFORCE=1 AND verdict is False, block the
        # entry before the decision is built. Default ENFORCE=0 means
        # we never reach the block branch — trade fires as today.
        # Fail-open on unresolved verdict (warmup / compute error).
        if HOLD_ENFORCE and shadow_hold_ok is False:
            logger.info(
                "[%s] %s %s HOLD_ENFORCE block: %s",
                LOG_TAG, symbol, ev.direction,
                ", ".join(shadow_rec.get("block_reasons") or []) or "hold_false",
            )
            if HOLD_SHADOW_ENABLED:
                _write_hold_shadow({
                    "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "pair": "GBPUSD",
                    "epic": epic,
                    "direction": ev.direction,
                    "entry_px": round(float(bars[-1].close), 5),
                    "fired_live": False,
                    "enforced_block": True,
                    "prior_swing": float(ev.prior_swing),
                    "break_pips_live": round(float(ev.break_pips), 3),
                    "flip_bar_ts": ev.flip_bar_ts,
                    **(shadow_rec or {}),
                })
            return None

        # ── TREND_ENTRY_GATE (LIVE enforce, added 2026-06-25) ───────────
        # Two-leg hard gate. Falls back to extracting from `bars` if the
        # full df closes/highs/lows weren't passed (back-compat shim).
        # gate.compute_features warmup_skips → fail-open when bars < 200,
        # so legacy short-bar dispatches don't trigger spurious blocks.
        trend_gate_rec: Optional[Dict[str, Any]] = None
        try:
            import trend_entry_gate as _teg
            if _teg.ENABLED:
                if closes_ind is None:
                    _closes_in = [float(b.close) for b in bars]
                else:
                    _closes_in = list(closes_ind)
                if highs_ind is None or lows_ind is None:
                    _highs_in = [float(b.high) for b in bars]
                    _lows_in = [float(b.low) for b in bars]
                else:
                    _highs_in = list(highs_ind)
                    _lows_in = list(lows_ind)
                _features = _teg.compute_features(
                    closes=_closes_in,
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
                    "strategy": "STRUCTURE_BREAK",
                    "direction": ev.direction,
                    "entry_px": round(float(bars[-1].close), 5),
                    "fired_live": bool(_verdict["gate_pass"]),
                    "enforced_block": (
                        not _verdict["gate_pass"] and not _verdict["fail_open"]
                    ),
                    **trend_gate_rec,
                })
                if not _verdict["gate_pass"] and not _verdict["fail_open"]:
                    logger.info(
                        "[%s] %s %s TREND_GATE block: %s",
                        LOG_TAG, symbol, ev.direction,
                        ", ".join(_verdict["block_reasons"]) or "blocked",
                    )
                    return None
            else:
                trend_gate_rec = {"enabled": False}
        except Exception as _teg_exc:
            logger.warning(
                "[%s] trend_entry_gate failed (fail-open): %s",
                LOG_TAG, _teg_exc,
            )
            trend_gate_rec = {
                "enabled": True,
                "fail_open": True,
                "compute_error": f"outer_exception:{type(_teg_exc).__name__}:{_teg_exc}",
            }

        # ── SB velocity gate (2026-06-26, LIVE ENFORCE) ─────────────────
        # Mirror of the BB_BOUNCE velocity guard. STRUCTURE_BREAK needs
        # real momentum in the break direction; low velocity = false break
        # that reverts. Stacks ON TOP of the trend gate (both must pass).
        # Sits after trend gate so the audit log can answer: "of fires
        # the trend gate passed, how many does velocity then catch?"
        sb_velo_rec: Optional[Dict[str, Any]] = None
        if SB_VELOCITY_GATE_ENABLED:
            try:
                # Prefer closes_ind when provided; fall back to bars.
                if closes_ind is not None and len(closes_ind) >= SB_VELO_BARS + 1:
                    _vc = float(closes_ind[-1])
                    _vp = float(closes_ind[-1 - SB_VELO_BARS])
                    _have = len(closes_ind)
                elif len(bars) >= SB_VELO_BARS + 1:
                    _vc = float(bars[-1].close)
                    _vp = float(bars[-1 - SB_VELO_BARS].close)
                    _have = len(bars)
                else:
                    _vc = _vp = None
                    _have = max(
                        len(closes_ind) if closes_ind is not None else 0,
                        len(bars),
                    )
                if _vc is not None and _vp is not None:
                    _velo_10 = (_vc - _vp) / float(SB_VELO_BARS) / float(PIP_SIZE)
                    _trade_sign = 1.0 if ev.direction == "LONG" else -1.0
                    _velo_in_break = _velo_10 * _trade_sign
                    _verdict = "PASS" if _velo_in_break >= SB_VELO_MIN else "BLOCK"
                    sb_velo_rec = {
                        "enabled": True,
                        "velo_10": round(_velo_10, 4),
                        "velo_in_break": round(_velo_in_break, 4),
                        "threshold": SB_VELO_MIN,
                        "bars": SB_VELO_BARS,
                        "verdict": _verdict,
                    }
                    _sb_velo_log({
                        "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "pair": "GBPUSD",
                        "epic": epic,
                        "strategy": "STRUCTURE_BREAK",
                        "direction": ev.direction,
                        "entry_px": round(float(bars[-1].close), 5),
                        "fired_live": (_verdict == "PASS"),
                        "enforced_block": (_verdict == "BLOCK"),
                        "trend_gate_pass": (
                            trend_gate_rec.get("gate_pass") if trend_gate_rec else None
                        ),
                        "shadow_hold_ok": shadow_hold_ok,
                        **sb_velo_rec,
                    })
                    if _verdict == "BLOCK":
                        logger.info(
                            "[SB_VELO_BLOCK] %s %s velo_10=%+.3fp/bar "
                            "velo_in_break=%+.3fp/bar thr=%.3f",
                            symbol, ev.direction, _velo_10, _velo_in_break,
                            SB_VELO_MIN,
                        )
                        return None
                else:
                    sb_velo_rec = {
                        "enabled": True,
                        "verdict": "INSUFFICIENT_BARS",
                        "have_bars": _have,
                        "need_bars": SB_VELO_BARS + 1,
                    }
                    _sb_velo_log({
                        "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "pair": "GBPUSD",
                        "epic": epic,
                        "strategy": "STRUCTURE_BREAK",
                        "direction": ev.direction,
                        **sb_velo_rec,
                    })
            except Exception as _velo_exc:
                logger.warning(
                    "[SB_VELO_ERROR] %s %s velocity gate compute failed: "
                    "%s — fail-open, fire proceeds",
                    symbol, ev.direction, _velo_exc,
                )
                sb_velo_rec = {
                    "enabled": True,
                    "fail_open": True,
                    "compute_error": f"{type(_velo_exc).__name__}:{_velo_exc}",
                }
        else:
            sb_velo_rec = {"enabled": False}

        # ── DAILY-ALIGNMENT FILTER (2026-06-30, LIVE ENFORCE) ───────────
        # Measured finding (30-fire SB directional audit): against-daily
        # SB fires booked −80p of the −92.65p total (57% of fires, 86% of
        # losses); with-daily was near-breakeven. Sign-stable both halves.
        # Filter blocks SB fires whose direction opposes the prior COMPLETED
        # daily candle's direction. Reuses gbpusd_trend_v3.prior_daily_direction
        # — same no-lookahead source the live TREND_V3 strategy uses
        # (reads only TF_CTX._d1_closed via get_closed_candles("GBPUSD","D1")[-1],
        # sign of close-open). ONE daily-direction source for the fleet.
        #
        # FLAT daily (prior day close ≈ open) → ALLOW (no directional signal
        #   to filter on; blocking on non-signal would be more conservative
        #   than the audit supports).
        # daily unavailable (TF_CTX warmup / D1 list empty / exception)
        #   → ALLOW (fail-open; do not gate on missing data).
        #
        # Flag: STRUCTURE_BREAK_DAILY_FILTER_ENABLED. Code default "1" (live —
        # user is testing the audit finding on real fills). Read at CALL-TIME
        # so it can be flipped off mid-session without restart.
        #
        # Touches direction only — SB break-detection, displacement-confirm,
        # SL/TP, scale-out, the regime gate, trail (already off), trend gate,
        # velocity gate are ALL unchanged. Every BLOCK and every ALLOW logs
        # greppably + JSONL so the live test is watchable.
        _daily_filter_on = (
            (os.getenv("STRUCTURE_BREAK_DAILY_FILTER_ENABLED", "1") or "1")
            .strip().lower() in ("1", "true", "yes", "on")
        )
        if _daily_filter_on:
            try:
                from gbpusd_trend_v3 import prior_daily_direction as _pdd
                _daily_dir, _daily_dbg = _pdd(symbol)
            except Exception as _pdd_exc:
                logger.warning(
                    "[SB_DAILY_FILTER] daily-direction lookup raised "
                    "(fail-open, fire proceeds): %s", _pdd_exc,
                )
                _daily_dir, _daily_dbg = None, {"err": f"exc:{_pdd_exc}"}

            _aligned = (
                (ev.direction == "LONG"  and _daily_dir == "UP")
                or (ev.direction == "SHORT" and _daily_dir == "DOWN")
            )
            _is_against = (
                (ev.direction == "LONG"  and _daily_dir == "DOWN")
                or (ev.direction == "SHORT" and _daily_dir == "UP")
            )

            _filter_row = {
                "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pair": "GBPUSD",
                "epic": epic,
                "strategy": "STRUCTURE_BREAK",
                "sb_direction": ev.direction,
                "daily_dir": _daily_dir,
                "daily_open": (_daily_dbg or {}).get("d1_open"),
                "daily_close": (_daily_dbg or {}).get("d1_close"),
                "daily_ts": (_daily_dbg or {}).get("d1_ts"),
                # 2026-07-01: propagate err/n_d1/source so any future null-fail
                # is visible in this row instead of only in trend_v3.jsonl. The
                # prior module-identity bug hid as clean daily_unavailable ALLOWs
                # because these debug fields weren't surfaced here.
                "daily_err": (_daily_dbg or {}).get("err"),
                "daily_n_d1": (_daily_dbg or {}).get("n_d1"),
                "daily_source": (_daily_dbg or {}).get("source"),
                "break_level": float(ev.prior_swing),
                "close_at_flip": float(ev.close_at_flip),
                "break_pips": round(float(ev.break_pips), 3),
                "filter_enabled": True,
            }

            if _is_against:
                _filter_row["verdict"] = "BLOCK"
                _filter_row["reason"] = "against_daily"
                logger.info(
                    "[SB_DAILY_FILTER] BLOCK — SB %s blocked, daily=%s "
                    "(against-daily fire suppressed) break_level=%.2f "
                    "close_at_flip=%.2f break=%.2fp",
                    ev.direction, _daily_dir,
                    float(ev.prior_swing), float(ev.close_at_flip),
                    float(ev.break_pips),
                )
                _sb_daily_filter_log(_filter_row)
                return None

            # ALLOW path: with-daily OR FLAT OR unavailable (fail-open).
            if _aligned:
                _filter_row["verdict"] = "ALLOW"
                _filter_row["reason"] = "with_daily"
                logger.info(
                    "[SB_DAILY_FILTER] ALLOW — SB %s with daily=%s "
                    "break_level=%.2f close_at_flip=%.2f break=%.2fp",
                    ev.direction, _daily_dir,
                    float(ev.prior_swing), float(ev.close_at_flip),
                    float(ev.break_pips),
                )
            elif _daily_dir == "FLAT":
                _filter_row["verdict"] = "ALLOW"
                _filter_row["reason"] = "daily_flat"
                logger.info(
                    "[SB_DAILY_FILTER] ALLOW — SB %s with daily=FLAT "
                    "(no directional signal to filter on)",
                    ev.direction,
                )
            else:
                # daily_dir is None (unavailable) → fail-open ALLOW.
                _filter_row["verdict"] = "ALLOW"
                _filter_row["reason"] = "daily_unavailable"
                logger.info(
                    "[SB_DAILY_FILTER] ALLOW — SB %s daily=unavailable "
                    "(fail-open; daily_dbg=%s)",
                    ev.direction, _daily_dbg,
                )
            _sb_daily_filter_log(_filter_row)
        # else: flag off → no log row, no gate; SB fires as before.

        # ── VWAP-STRETCH EXHAUSTION BRAKE (2026-06-30, LIVE) ────────────
        # Direction-aware brake on continuation strategies. Short side
        # default-on (validated 2026-06-30: L2/L3/L4 V-bottom shorts).
        # Long side default-off (preserves 14:55 SB_L +28p winner).
        # CHOP-only. Read flags at call time. Fail-open everywhere.
        # ADDITIVE to the SB daily-filter above — both can block; this
        # one only adds new blocks for the V-bottom continuation pattern.
        try:
            from guards.trend_stretch_brake import evaluate as _stretch_brake
            _mode_for_brake = mode  # GBPUSD_STRUCTURE_BREAK_L/S
            _blocked, _brake_reason, _brake_rec = _stretch_brake(
                strategy="STRUCTURE_BREAK",
                mode=_mode_for_brake,
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

        # ── RANGE GATE (2026-06-30, LIVE) ──────────────────────────────
        # Suppress trend-family fires when the market is ranging
        # (wide bands + low ER). Mirror of the BB_BOUNCE STRONG_TREND
        # stand-down, opposite direction. Direction-agnostic for
        # TREND family (SB/EMA_PB/TREND_V3). Fade strategies are EXEMPT
        # via the gate's mode-allowlist. Read flags at call time.
        # Fail-open. ADDITIVE to the SB daily-filter + stretch brake
        # above — any can block independently.
        _range_rec: Dict[str, Any] = {"called": False}
        try:
            from guards.range_gate import evaluate as _range_gate
            _mode_for_range = mode  # GBPUSD_STRUCTURE_BREAK_L/S
            _r_blocked, _r_reason, _range_rec = _range_gate(
                strategy="STRUCTURE_BREAK",
                mode=_mode_for_range,
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

        entry_px = float(bars[-1].close)
        sl_pips = float(ev.sl_pips)
        tp_pips = float(RUNNER_TP_PIPS)

        reason = (
            f"structure_break_{direction_signal.lower()} "
            f"flip={ev.direction} break={ev.break_pips:.2f}p "
            f"prior_swing={ev.prior_swing:.2f} close_at_flip={ev.close_at_flip:.2f} "
            f"atr={ev.atr_price/PIP_SIZE:.2f}p regime={ev.regime} adx={ev.adx:.1f} "
            f"SL={sl_pips:.1f}p TP={tp_pips:.1f}p"
        )

        debug: Dict[str, Any] = {
            "pattern": "STRUCTURE_BREAK",
            "direction": ev.direction,
            "flip_bar_ts": ev.flip_bar_ts,
            "prior_swing": ev.prior_swing,
            "close_at_flip": ev.close_at_flip,
            "break_pips": round(ev.break_pips, 3),
            "decisive_threshold_pips": DECISIVE_PIPS,
            "atr_period": ATR_PERIOD,
            "atr_pips": round(ev.atr_price / PIP_SIZE, 3),
            "sl_buffer_atr_mult": SL_BUFFER_ATR_MULT,
            "sl_components": ev.sl_components,
            "regime_at_fire": ev.regime,
            "adx_at_fire": round(ev.adx, 2),
            "adx_min_threshold": ADX_MIN,
            "range_regimes_blocked": sorted(RANGE_REGIMES),
            "runner_tp_pips": RUNNER_TP_PIPS,
            "transition_filter_enabled": TRANSITION_FILTER_ENABLED,
            "transition_window_bars": TRANSITION_WINDOW_BARS,
            "transition_flip_min": TRANSITION_FLIP_MIN,
            "transition_adx_win_min": TRANSITION_ADX_WIN_MIN,
            "transition_disp_min_pips": TRANSITION_DISP_MIN_PIPS,
            "transition_sig": ev.transition_sig,
            "transition_would_block": ev.transition_would_block,
            "transition_block_reason": ev.transition_block_reason,
            "disp_confirm_enabled": DISP_CONFIRM_ENABLED,
            "disp_confirm_window_bars": ev.disp_confirm_window_bars,
            "disp_confirm_min_pips": DISP_CONFIRM_MIN_PIPS,
            "disp_confirm_pips": ev.disp_confirm_pips,
            "disp_confirm_would_block": ev.disp_confirm_would_block,
            "disp_confirm_block_reason": ev.disp_confirm_block_reason,
        }

        # N-bar HOLD SHADOW fields (added 2026-06-24). Schema mirrors the
        # per-fire row written to logs/sb_hold_shadow.jsonl so the two
        # sources can be cross-referenced by trade_id later.
        if shadow_rec is not None:
            debug["hold_shadow"] = dict(shadow_rec)
            debug["hold_shadow_enabled"] = bool(HOLD_SHADOW_ENABLED)
            debug["hold_shadow_enforce"] = bool(HOLD_ENFORCE)

        # TREND_ENTRY_GATE fields (added 2026-06-25). Mirrors the per-fire
        # row written to logs/trend_entry_gate.jsonl.
        if trend_gate_rec is not None:
            debug["trend_entry_gate"] = dict(trend_gate_rec)

        # SB velocity gate fields (added 2026-06-26). Mirrors the per-fire
        # row written to logs/sb_velocity_gate.jsonl.
        if sb_velo_rec is not None:
            debug["sb_velocity_gate"] = dict(sb_velo_rec)

        # VWAP-stretch brake telemetry (2026-06-30). Always-on debug stamp
        # for ALLOW fires so the signal_log row carries vwap_dist + regime
        # + threshold state as evaluated by the brake. BLOCK fires never
        # reach this branch (we returned None above); they are captured
        # only in logs/trend_stretch_brake.jsonl.
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

        # ── Entry-path regime gate (2026-07-07) ───────────────────────────
        # Route between CHASE-at-market (genuine STRONG_TREND) and
        # RETEST-limit (TREND_FORMING or promoted STRONG_TREND). See
        # _classify_entry_path for the full table. Always classify + log
        # so both branches (and the kill-switch off case) are auditable.
        entry_path, promoted, entry_reason = self._classify_entry_path(ev)
        _kill_switch_forced_chase = (not RETEST_ENTRY_ENABLED)
        if _kill_switch_forced_chase:
            # Kill-switch OFF → force CHASE regardless of gate. Byte-identical
            # to pre-retest fire path for every regime.
            entry_path = "CHASE"
            entry_reason = "kill_switch_off"
        # Mode overlay: prefer_retest re-routes would-be CHASE through the
        # existing retest machinery; retest_only skips the fire outright.
        # Kill-switch has priority — when off, mode is a no-op.
        entry_path, _mode_skipped_no_retest, entry_reason = _apply_entry_path_mode(
            entry_path=entry_path,
            kill_switch_forced_chase=_kill_switch_forced_chase,
            mode=SB_ENTRY_PATH_MODE,
            base_reason=entry_reason,
        )
        # Universal decision log — fires on every path (CHASE, RETEST, skip).
        logger.info(
            "[SB-ENTRY] mode=%s path_taken=%s promoted=%s regime=%s%s",
            SB_ENTRY_PATH_MODE,
            ("SKIPPED" if _mode_skipped_no_retest else entry_path),
            promoted, (ev.regime or "?"),
            (" skipped=no_retest" if _mode_skipped_no_retest else ""),
        )
        if _mode_skipped_no_retest:
            return None
        debug["entry_path_gate"] = {
            "entry_path": entry_path,
            "regime_at_fire": ev.regime,
            "regime_label_path": ev.regime_label_path,
            "promoted": bool(promoted),
            "reason": entry_reason,
            "retest_entry_enabled": bool(RETEST_ENTRY_ENABLED),
            "retest_gate_default": RETEST_GATE_DEFAULT_PATH,
            "retest_gate_strong_trend_promoted": bool(
                RETEST_GATE_STRONG_TREND_PROMOTED
            ),
        }

        # ── Break-level + level-distance stamps (2026-07-24, OBSERVE-ONLY) ──
        # Persist raw flip-bar values (prior_swing / close_at_flip already on
        # debug from the base build; add SB-namespaced break_pips, atr_pips,
        # entry_path so signal_logger can whitelist without colliding with
        # existing atr_pips / entry_path readers). Level fields come from the
        # shared level_telemetry function; PDH/PDL sourced from the wide 5m
        # frame in-process (no REST). Both stamps are best-effort — any
        # failure logs at DEBUG and the CHASE build below proceeds unchanged.
        try:
            debug["sb_break_pips"] = round(float(ev.break_pips), 3)
            debug["sb_atr_pips"] = round(float(ev.atr_price) / PIP_SIZE, 3)
            debug["sb_entry_path"] = str(entry_path)
            debug["flip_bar_ts"] = _sb_normalize_flip_bar_ts(ev.flip_bar_ts)
        except Exception as _sb_stamp_exc:  # noqa: BLE001
            logger.debug("[%s] sb break-level stamp failed: %s",
                         LOG_TAG, _sb_stamp_exc)
        try:
            _sb_lvl = _sb_compute_level_telemetry(
                entry_px=float(bars[-1].close),
                closes=closes_ind,
                highs=highs_ind,
                lows=lows_ind,
            )
            if _sb_lvl:
                debug.update(_sb_lvl)
        except Exception as _sb_lvl_exc:  # noqa: BLE001
            logger.debug("[%s] sb level-distance stamp failed: %s",
                         LOG_TAG, _sb_lvl_exc)

        _entry_path_row = {
            "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pair": "GBPUSD",
            "epic": epic,
            "direction": ev.direction,
            "close_at_flip": round(float(ev.close_at_flip), 5),
            "prior_swing": round(float(ev.prior_swing), 5),
            "break_pips": round(float(ev.break_pips), 3),
            "flip_bar_ts": ev.flip_bar_ts,
            "regime_at_fire": ev.regime,
            "regime_label_path": ev.regime_label_path,
            "adx_at_fire": round(float(ev.adx), 2),
            "entry_path": entry_path,
            "promoted": bool(promoted),
            "reason": entry_reason,
            "retest_entry_enabled": bool(RETEST_ENTRY_ENABLED),
            "retest_limit_buffer_pips": float(RETEST_LIMIT_BUFFER_PIPS),
            "retest_expiry_bars": int(RETEST_EXPIRY_BARS),
        }
        _write_entry_path_log(_entry_path_row)
        logger.info(
            "[%s] %s %s entry_path=%s regime=%s label_path=%s promoted=%s "
            "reason=%s (kill_switch=%s)",
            LOG_TAG, epic, ev.direction, entry_path, ev.regime,
            (ev.regime_label_path or "?"), promoted, entry_reason,
            ("off" if _kill_switch_forced_chase else "on"),
        )

        # ── RETEST branch ─────────────────────────────────────────────────
        # PLACE a pending LIMIT at level ± BUFFER, emit the per-flip-bar
        # hold_shadow row with fired_live=False + deferred_to_retest_limit=True,
        # and return None. The pending fills on a subsequent bar (via the
        # lifecycle block at the top of evaluate()) or expires unfilled
        # (runaway cleanly skipped).
        if entry_path == "RETEST":
            self._place_pending_retest(epic, ev, ts, debug_carry=debug)
            if HOLD_SHADOW_ENABLED and shadow_rec is not None:
                _write_hold_shadow({
                    "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "pair": "GBPUSD",
                    "epic": epic,
                    "direction": ev.direction,
                    "entry_px": round(float(ev.close_at_flip), 5),
                    "fired_live": False,
                    "enforced_block": False,
                    "prior_swing": float(ev.prior_swing),
                    "break_pips_live": round(float(ev.break_pips), 3),
                    "flip_bar_ts": ev.flip_bar_ts,
                    "deferred_to_retest_limit": True,
                    "entry_path": entry_path,
                    "regime_at_fire": ev.regime,
                    "regime_label_path": ev.regime_label_path,
                    "promoted": bool(promoted),
                    **shadow_rec,
                })
            return None

        # CHASE branch — fall through to the market-order decision build
        # below. entry_path == "CHASE" (genuine STRONG_TREND, or kill-switch
        # forced off, or the promoted-gate override).

        # Lazy import — keep module-level imports free of live side effects.
        try:
            from strategy_logic import StrategyDecision
        except Exception as exc:
            logger.error("[%s] StrategyDecision import failed: %s", LOG_TAG, exc)
            return None

        decision = StrategyDecision(
            symbol="GBPUSD",
            regime="STRUCTURE_BREAK",
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

        # Record fire time for cooldown bookkeeping AFTER building decision.
        self._last_fire_ts_by_epic[epic] = ts

        # Emit the live-fire HOLD shadow row (telemetry only — never raises).
        if HOLD_SHADOW_ENABLED and shadow_rec is not None:
            _write_hold_shadow({
                "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pair": "GBPUSD",
                "epic": epic,
                "direction": ev.direction,
                "entry_px": round(entry_px, 5),
                "fired_live": True,
                "enforced_block": False,
                "prior_swing": float(ev.prior_swing),
                "break_pips_live": round(float(ev.break_pips), 3),
                "flip_bar_ts": ev.flip_bar_ts,
                "entry_path": entry_path,
                "regime_at_fire": ev.regime,
                "regime_label_path": ev.regime_label_path,
                "promoted": bool(promoted),
                **shadow_rec,
            })

        logger.info(
            "[%s] %s %s ENTRY @ %.5f | entry_path=%s regime=%s label_path=%s "
            "promoted=%s | SL=%.1fp TP=%.1fp | shadow_hold=%s | %s",
            LOG_TAG, ev.direction, direction_signal,
            entry_px, entry_path, ev.regime,
            (ev.regime_label_path or "?"), promoted,
            sl_pips, tp_pips,
            (shadow_hold_ok if shadow_hold_ok is not None else "n/a"),
            reason,
        )
        return decision


# Module-level singleton + dispatch helper (mirrors gbpusd_ema_pullback).
strategy = GbpUsdStructureBreakStrategy.instance()


def evaluate(*args, **kwargs):
    return strategy.evaluate(*args, **kwargs)
