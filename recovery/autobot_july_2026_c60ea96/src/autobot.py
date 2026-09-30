#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
autobot.py — Multi-FX AutoBot (systemd) — cache-first preload + Lightstreamer ticks + tick-built 5m candles

PRE-CHECK (House rules / Continual Errors / Contracts):
- #83: load .env before env-dependent imports
- #97: warmup within IG limits; don't demand more than available
- #104/#24: no price normalization; keep IG prices native points
- #106: StrategyDecision.sl/tp are pip distances; executor converts pips→points
- #96: open_sb_now is golden; executor uses it
- #20/#21/#100/#101: avoid aggressive REST loops; respect block file; throttle REST calls
- CONTRACT: DATAFLOW MUST NOT DRIFT — TimeframeContext.on_5m_close(...) must run on 5m close and snapshot must be passed into strategy

REQUIRED BEHAVIOR (your words, implemented):
- Arm indicators immediately (≥50 CLOSED 5m candles per epic)
- No top-up/merge (replace-only)
- Allowance-safe across rapid restarts (do NOT REST just because cache is stale if it already has ≥50)
- Prefer cheap preload (CFD 5m fetch) and only fall back to MINUTE→5m aggregation if needed
- Trade/stream using TODAY epics
- Write closed candles to cache while running

PATCHES INCLUDED (per latest pre-prod feedback):
- ✅ TimeframeContext integration fixed + mandatory (hard stop if missing) — no contract drift
- ✅ NaN/inf hardening in _safe_float
- ✅ Preload prefers cheap 5m fetch first (MINUTE_5) with robust shape handling; falls back to MINUTE aggregation
- ✅ Expanded allowance detection (best-effort) to handle empty exception strings
- ✅ Startup banner logs cache last timestamp + age (per symbol)
"""

import math
import os
import re
import signal as _signal_mod
import time
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv

# ------------------------------------------------------------
# #83: LOAD ENV BEFORE IMPORTING ENV-DEPENDENT MODULES
# override=True (2026-05-27): python-dotenv correctly strips trailing
# inline `# comment` text on KEY=value lines; systemd's EnvironmentFile
# parser does NOT. With override=True, python-dotenv's clean parse
# OVERWRITES systemd's polluted environ values on startup, immunising
# the bot against any inline-comment pollution in .env (root cause of
# the 2026-05-27 GBPUSD_TREND_SELF_DISPATCH=1 silently-OFF incident).
# ------------------------------------------------------------
load_dotenv(override=True)

# ------------------------------------------------------------
# Logging config
# ------------------------------------------------------------

def _configure_logging() -> None:
    level_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=fmt)
    else:
        root.setLevel(level)
        for h in root.handlers:
            try:
                h.setLevel(level)
            except Exception:
                pass

    logging.getLogger("AutoBot").setLevel(level)

    # Redact secret substrings (Telegram bot token, SendGrid key, Anthropic
    # key, IG API key) before any handler emits them. Must run AFTER root
    # handlers exist so the filter can attach to them; a future DEBUG toggle
    # on urllib3/httpx cannot re-introduce the leak.
    from log_redaction import install_default as _install_secret_redaction
    _install_secret_redaction(root)


_configure_logging()
logger = logging.getLogger("AutoBot")

# ------------------------------------------------------------
# Imports that rely on env (after load_dotenv)
# ------------------------------------------------------------
from ig_auth import get_ig_session  # noqa: E402
from streamer_ls import start_streaming  # noqa: E402
from close_sb_now import get_open_positions  # noqa: E402

from trade_executor import (  # noqa: E402
    execute_trade,
    close_position,
    close_all_positions_for_epic,
    has_active_trade,  # authoritative — True if ANY position active for epic
    has_active_trade_for_mode,
    get_all_positions_for_epic,
    register_trade_close_callback,
    reconcile_open_positions,
    EPIC_STATE,
    _pos_key,
    _epic_from_pos_key,
    _pair_from_epic,
)
from trade_manager import trade_manager, register_bb_range_scalp  # noqa: E402

from telegram_alerts import send_status_update, send_telegram_message  # noqa: E402

from filesystem_paths import (  # noqa: E402
    ensure_output_directories,
    verify_output_directories_writable,
)

import candle_builder  # noqa: E402
import candle_archive  # noqa: E402,F401  (side-effect: registers 5m-close → data/candles/{PAIR}/{DATE}.csv)
from sweep_journal import SweepJournal  # noqa: E402
from diagnostics_logger import DiagnosticsLogger  # noqa: E402
from news_blackout import load_news_windows, is_news_blackout, CLOSE_ON_BLACKOUT  # noqa: E402
import news_tick_strategy  # noqa: E402
import news_calendar  # noqa: E402
import fifty_pip_breakout  # noqa: E402,F401  (startup-time import sanity; symbols loaded lazily in tick block)

# NEWS_STRATEGY singleton — cached to avoid per-tick reconstruction.
# The strategy's state lives in news_strategy._news_state (module-level
# dict), so reusing one NewsStrategy instance is functionally equivalent
# to the prior per-tick `NewsStrategy()` construction in
# strategy_logic.evaluate_signals — just cheaper.
_NEWS_STRATEGY_SINGLETON = None


def _get_news_strategy_singleton():
    global _NEWS_STRATEGY_SINGLETON
    if _NEWS_STRATEGY_SINGLETON is None:
        from news_strategy import NewsStrategy
        _NEWS_STRATEGY_SINGLETON = NewsStrategy()
    return _NEWS_STRATEGY_SINGLETON

import morning_briefing  # noqa: E402
from briefing_tracker import BriefingTracker  # noqa: E402
import signal_logger  # noqa: E402
import regime_matrix  # noqa: E402  (Phase 2 dispatch gate; no-op when REGIME_MATRIX_ENABLED=0)

# ------------------------------------------------------------
# TimeframeContext (CONTRACT: MUST NOT DRIFT)
# ------------------------------------------------------------
try:
    from timeframe_context import TimeframeContext
except Exception as e:
    logger.error(f"❌ TimeframeContext import failed (DATAFLOW MUST NOT DRIFT): {e}")
    raise

try:
    import htf_cache as _htf_cache
except Exception as e:
    logger.warning(f"htf_cache import failed (HTF caching disabled): {e}")
    _htf_cache = None  # type: ignore[assignment]


# ============================================================
# CONFIG
# ============================================================

BOT_ID = os.getenv("BOT_ID", "unknown")

COOLDOWN_SECONDS = int(float(os.getenv("COOLDOWN_SECONDS", "60")))
# Same-direction re-entry on a pair is blocked for this long after a stop-out.
# Same-direction post-SL cooldown. Default 30 min (was 2 h before 2026-04-30).
# Rationale: 2 h was overprotective and blocked legitimate setup re-prints in
# the same direction within the same session. 60 s is too short — see
# USDJPY 2026-04-15 08:21 SL → 09:03 SL revenge cluster. 30 min is a
# compromise: cools the immediate revenge response without freezing the
# strategy out of a same-day re-arm. Env-overridable via
# COOLDOWN_SECONDS_AFTER_SL.
COOLDOWN_SECONDS_AFTER_SL = int(float(os.getenv("COOLDOWN_SECONDS_AFTER_SL", "1800")))

LAST_SL_BLOCK_PATH = (
    os.getenv("LAST_SL_BLOCK_PATH", "/opt/tradingbot/last_sl_block.json").strip()
)
HEARTBEAT_SECONDS = int(float(os.getenv("HEARTBEAT_SECONDS", "30")))

POSITIONS_SYNC_SECONDS = int(float(os.getenv("POSITIONS_SYNC_SECONDS", "15")))
POSITIONS_SYNC_MIN_GAP = max(5, POSITIONS_SYNC_SECONDS)
# Per-epic position limit removed — multiple strategies can hold simultaneous
# positions on the same epic.  Duplicate-mode blocking is handled in execute_trade.

# LS-thread refactor (2026-05-08): per-pair-worker async dispatch.
# When 1 (default), L1 ticks and 5m closes are routed through pair_workers,
# REST sweeps run on the rest_sweeps daemon, and Telegram sends are async.
# When 0, the synchronous LS-thread path is restored as a rollback escape
# hatch. Read once at module load — restart required to flip.
_LS_ASYNC_DISPATCH = (os.getenv("LS_ASYNC_DISPATCH", "1") or "1").strip() != "0"

STRATEGY_LOG_EVERY_TICK = (os.getenv("STRATEGY_LOG_EVERY_TICK", "0") or "0").strip() == "1"

NY_CLOSE_ENABLED = (os.getenv("NY_CLOSE_ENABLED", "1") or "1").strip() == "1"
NY_CLOSE_HHMM = (os.getenv("NY_CLOSE_HHMM", "16:55") or "16:55").strip()
NY_CLOSE_WINDOW_MINUTES = int(float(os.getenv("NY_CLOSE_WINDOW_MINUTES", "10")))

SOFTWARE_BE_ENABLED = (os.getenv("SOFTWARE_BE_ENABLED", "1") or "1").strip() == "1"
SOFTWARE_BE_TRIGGER_PIPS = float(os.getenv("SOFTWARE_BE_TRIGGER_PIPS", "12"))
SOFTWARE_BE_OFFSET_PIPS = float(os.getenv("SOFTWARE_BE_OFFSET_PIPS", "1"))

# 2026-06-15: when True, signal_log persists the IG broker-confirmed fill
# level (captured by trade_executor.fetch_deal_by_deal_reference into
# EPIC_STATE[pk]["entry_price"]) as the `entry` field, tagged
# entry_price_source="ig_fill". When False (or no fill available, or
# the fill is >5p from decision), persists the strategy's M5 decision
# price tagged entry_price_source="decision_fallback". The source field
# is written in BOTH modes so the corpus is self-describing across the
# semantic change. See signal_logger.log_open docstring.
ENTRY_FILL_READBACK_ENABLED = (
    os.getenv("ENTRY_FILL_READBACK_ENABLED", "true") or "true"
).strip().lower() in ("1", "true", "yes", "on")
# Modes whose positions are exempt from the software BE-amend.
# BB_REVERSAL: TP1 is 15-20p, +12p BE-amend caps winners at +1p (entry+offset)
# and strips the edge — let IG TP/SL run untouched.
# GBPUSD_TREND_L/S: own 2-step software trail (25p→entry+15p,
# 40p→entry+25p) — generic +12p BE-amend would override the trail floor
# and disable the structural design. See gbpusd_trend.update_trailing_stop.
_SKIP_BE_AMEND_MODES = {"BB_REVERSAL", "GBPUSD_TREND_L", "GBPUSD_TREND_S"}

NEWS_BLACKOUT_MIN_PROFIT_TO_KEEP_PIPS = float(os.getenv("NEWS_BLACKOUT_MIN_PROFIT_TO_KEEP_PIPS", "10"))

# Global pre-news position-close kill switch (2026-05-23). When False, the
# 5-min pre-HIGH-event force-close block below is skipped entirely: positions
# ride through news on their own broker SL/TP/scale-out. Default OFF — the
# block's +10p keep-threshold collides exactly with the universal +10p
# scale-out trigger, strangling winners at +8-9p (1-2p shy of scale-out)
# instead of letting them bank. The strategy-level _is_pre_news_blackout
# (in gbpusd_bb_bounce, ema_pullback, etc.) is a SEPARATE mechanism — it
# blocks NEW entries near news and is untouched by this flag.
PRE_NEWS_CLOSE_ENABLED = (os.getenv("PRE_NEWS_CLOSE_ENABLED", "0") or "0").strip() == "1"

# ── BRIEFING_EXECUTION simple-exits (2026-04-21) ──────────────────────
# Default behaviour: BE positions ride to SL / TP / PRE_NEWS_CLOSE / EOD
# only. Every other early-exit mechanism is env-gated off for BE mode.
# Flip any _ENABLED=1 to restore the legacy mechanism.
_BE_TIME_EXIT_ENABLED = (os.getenv("BRIEFING_EXEC_TIME_EXIT_ENABLED", "0") or "0").strip() == "1"
_BE_INVALIDATION_ENABLED = (os.getenv("BRIEFING_EXEC_INVALIDATION_ENABLED", "0") or "0").strip() == "1"
_BE_SKIP_NY_CLOSE = (os.getenv("BRIEFING_EXEC_SKIP_NY_CLOSE", "1") or "1").strip() == "1"
_BE_SOFTWARE_BE_AMEND_ENABLED = (os.getenv("BRIEFING_EXEC_SOFTWARE_BE_AMEND_ENABLED", "0") or "0").strip() == "1"
_BE_EOD_CLOSE_ENABLED = (os.getenv("BRIEFING_EXEC_EOD_CLOSE_ENABLED", "1") or "1").strip() == "1"
_BE_EOD_CLOSE_UTC = (os.getenv("BRIEFING_EXEC_EOD_CLOSE_UTC", "21:00") or "21:00").strip()

# Phase 2 — NY plan evaluation at 12:30 UTC. The single morning briefing
# emits NY plans gated by london_condition; this dispatcher builds the
# London 06:45-12:25 UTC summary from data/candles/<sym>/<today>.csv and
# calls BriefingExecutionStrategy.evaluate_ny_plans() once per (pair, day).
_BE_NY_EVAL_ENABLED = (os.getenv("BRIEFING_EXEC_NY_EVAL_ENABLED", "1") or "1").strip() == "1"
_BE_NY_EVAL_UTC = (os.getenv("BRIEFING_EXEC_NY_EVAL_UTC", "12:30") or "12:30").strip()
# Per-pair last-fired date so a restart between 12:30 and tomorrow can run
# the eval retroactively (Persistent=true semantics) while still gating to
# once per day.
_BE_NY_EVAL_STATE: Dict[str, str] = {}


def _is_briefing_exec_mode(mode: Any) -> bool:
    """True if mode belongs to the EOD-close sweep set — prefix match.

    NAMING NOTE (2026-05-13): the function name is historical — it
    matched only briefing-execution variants until GBPUSD_TREND was
    added. The semantics are now "mode whose positions the EOD 21:00
    UTC close machinery sweeps", which is a superset. A future rename
    to `_is_eod_swept_mode` would clarify intent without changing
    behaviour. Until then: every consumer (EOD close at :1591, BE skip
    at :1879 (note: also gated by _SKIP_BE_AMEND_MODES which already
    contains GBPUSD_TREND_*), NY-close skip at :2410) treats the matched
    mode like a briefing fire for those concerns.

    Members:
      BRIEFING_EXECUTION  — v4 / v5_pia briefings (single + multi-slot)
      BRIEFING_PIA_FIRST  — PIA_FIRST system (2026-05-13)
      GBPUSD_TREND        — cascade-trend strategy needs EOD close to
                            catch positions still open at 21:00 UTC
                            (broker TP at +80p, software trail otherwise)
    """
    m = str(mode or "").strip().upper()
    _EOD_CLOSE_PREFIXES = ("BRIEFING_EXECUTION", "BRIEFING_PIA_FIRST", "GBPUSD_TREND")
    return any(m.startswith(p) for p in _EOD_CLOSE_PREFIXES)


CACHE_DIR = os.getenv("CACHE_DIR", "/opt/tradingbot/cache").strip() or "/opt/tradingbot/cache"

SESSION_TZ = (os.getenv("SESSION_TZ", "Europe/London") or "Europe/London").strip()

# Indicator arming requirement (EMA stable)
MIN_CACHE_CANDLES = int(float(os.getenv("MIN_CACHE_CANDLES", "50") or 50))

# Cache freshness budget (only used for visibility / optional strict mode)
MAX_CACHE_AGE_HOURS = float(os.getenv("MAX_CACHE_AGE_HOURS", "6") or 6)

# Compatibility shim: PRELOAD_MAX_AGE_MIN overrides MAX_CACHE_AGE_HOURS if present
if os.getenv("PRELOAD_MAX_AGE_MIN") is not None:
    try:
        MAX_CACHE_AGE_HOURS = float(os.getenv("PRELOAD_MAX_AGE_MIN")) / 60.0
    except Exception:
        pass

# Target number of CLOSED 5m candles we want in cache/builder.
# Floor 10, ceiling 2000 (well above the 576-bar ATR_PCTL_14 warmup that
# drives the Phase 4B shadow classifier; default 600 matches the rolling
# cache that already keeps a continuous, indicator-enriched 600-bar
# history on disk).
PRELOAD_TARGET_5M_BARS = int(float(os.getenv("PRELOAD_TARGET_5M_BARS", "600") or 600))
PRELOAD_TARGET_5M_BARS = max(10, min(2000, PRELOAD_TARGET_5M_BARS))

# Allowance-safe rule: if cache has >= MIN_CACHE_CANDLES, arm immediately even if stale
ALLOW_STALE_CACHE_FOR_ARMING = (os.getenv("ALLOW_STALE_CACHE_FOR_ARMING", "1") or "1").strip() == "1"

# Prefer cheap preload (CFD 5m fetch) first, then fall back to MINUTE aggregation
PREFER_CHEAP_5M_PRELOAD = (os.getenv("PREFER_CHEAP_5M_PRELOAD", "1") or "1").strip() == "1"

# Cheap 5m fetch points (CFD MINUTE_5). Default: 60 (gives some buffer for closed buckets)
CHEAP_5M_POINTS = int(float(os.getenv("CHEAP_5M_POINTS", "60") or 60))

# Fallback: Number of MINUTE bars to request so we can build 5m candles.
# Conservative default: target*7 (runs only when cache missing/short).
try:
    _default_1m_points = int(PRELOAD_TARGET_5M_BARS) * 7
except Exception:
    _default_1m_points = 350
PRELOAD_REST_1M_POINTS = int(float(os.getenv("PRELOAD_REST_1M_POINTS", str(_default_1m_points)) or _default_1m_points))

REST_PRELOAD_ENABLED = (os.getenv("REST_PRELOAD_ENABLED", "1") or "1").strip() == "1"
ALLOW_STALE_CACHE_IF_REST_BLOCKED = (os.getenv("ALLOW_STALE_CACHE_IF_REST_BLOCKED", "1") or "1").strip() == "1"

REST_PRELOAD_MIN_GAP_SECS = float(os.getenv("REST_PRELOAD_MIN_GAP_SECS", "1.0") or 1.0)
REST_PRELOAD_BLOCK_SECS = int(float(os.getenv("REST_PRELOAD_BLOCK_SECS", "1800") or 1800))
REST_PRELOAD_BLOCK_PATH = os.getenv("REST_PRELOAD_BLOCK_PATH", "/opt/tradingbot/rest_preload_block.json")

# 5M REST gap-fill (2026-05-24): mirrors the proven H1/D1 gap-fill path
# at _rest_preload_symbol's HTF block. When the rolling cache is loaded
# but its last bar is more than REST_5M_GAPFILL_GRACE_SECS behind wall-
# clock, fetch the missing 5M bars from REST and merge before seeding
# the buffer. Closes the Thursday-style stale-seed bug at the source
# (paired with candle_builder's contiguity guard as the unconditional
# backstop). Set REST_5M_GAPFILL_ENABLED=0 to revert to legacy fresh→use
# / stale→replace behaviour.
REST_5M_GAPFILL_ENABLED = (os.getenv("REST_5M_GAPFILL_ENABLED", "1") or "1").strip().lower() in ("1", "true", "yes")
# Grace = how stale the cache may be before we trigger gap-fill. 360s =
# 1 bar (300s) + 60s slack. Below this, cache is effectively at-tail and
# no REST call is needed.
REST_5M_GAPFILL_GRACE_SECS = float(os.getenv("REST_5M_GAPFILL_GRACE_SECS", "360") or 360.0)
# Ceiling on the points requested in a single gap-fill call. Cold-start
# weekend recovery could theoretically ask for thousands; clamp at
# PRELOAD_TARGET_5M_BARS (the buffer size) — anything older is uselessly
# trimmed by the buffer cap.
REST_5M_GAPFILL_MAX_POINTS = int(float(os.getenv("REST_5M_GAPFILL_MAX_POINTS", "600") or 600))

# Internal-gap REST backfill (2026-06-15). The existing 5M gap-fill above
# only triggers when the *tail* of the rolling cache is stale. If a prior
# restart straddled a 5M candle close, the cache will have an INTERNAL
# hole (e.g. today's 12:35 UTC bar). On the next restart the contiguity
# guard truncates the buffer to the post-gap tail, blinding the fleet for
# ~2h of warmup. This block extends the preload path: scan the loaded
# rolling-cache df for any Δt > GRACE between consecutive rows, REST-fill
# each gap window, then merge. Mirrors the tail-age gap-fill block (same
# concat → drop_duplicates(keep='last') → sort → tail pattern). Paired
# with candle_builder's persist-side gap guard (same env flag) so a single
# bad restart can't poison every future restart. Default OFF.
STRUCTURE_BUFFER_GAPFILL_ENABLED = (
    os.getenv("STRUCTURE_BUFFER_GAPFILL_ENABLED", "0") or "0"
).strip().lower() in ("1", "true", "yes")
# Gap threshold (secs) — anything Δt > this is treated as a hole.
# Default 360s = one 5M bar (300s) + 60s slack, matching the contiguity
# guard's own threshold so the two stay aligned.
STRUCTURE_BUFFER_GAPFILL_MAX_GAP_SECS = float(
    os.getenv("STRUCTURE_BUFFER_GAPFILL_MAX_GAP_SECS", "360") or 360.0
)
# Cap on TOTAL points fetched across all internal gaps in one preload.
# Allowance protection — a many-hour gap blows past PRELOAD_TARGET_5M_BARS
# and isn't usable anyway.
STRUCTURE_BUFFER_GAPFILL_MAX_POINTS = int(
    float(os.getenv("STRUCTURE_BUFFER_GAPFILL_MAX_POINTS", "600") or 600)
)
# Skip attempting backfill across the FX-closed weekend window
# (Fri 21:00 UTC → Sun 22:00 UTC, approx). IG returns no bars and the
# attempt would burn allowance points to no purpose. Set =0 to attempt
# anyway (e.g. for testing or out-of-band session models).
STRUCTURE_BUFFER_GAPFILL_SKIP_WEEKEND = (
    os.getenv("STRUCTURE_BUFFER_GAPFILL_SKIP_WEEKEND", "1") or "1"
).strip().lower() in ("1", "true", "yes")

LAST_TRADE_TIMES_PATH = (
    os.getenv("LAST_TRADE_TIMES_PATH", "/opt/tradingbot/last_trade_times.json").strip()
    or "/opt/tradingbot/last_trade_times.json"
)

ONE_ENTRY_PER_BUCKET = (os.getenv("ONE_ENTRY_PER_BUCKET", "1") or "1").strip() == "1"

# 3CO (Three Consecutive Opens) and GBPUSD_TREND_CONTINUATION strategies
# deleted 2026-05-13. Replaced by GBPUSD_TREND (gbpusd_trend.py) which
# uses the Phase 4B cascade as the directional truth — no early-session
# pattern, no H1 EMA stack gate, no freshness window. See
# docs/executor_gate_kill_list_2026-05-12.md.

# Ongoing cache writes on each 5m close (since candle_builder has no persistence)
WRITE_CACHE_FROM_5M_CLOSE = (os.getenv("WRITE_CACHE_FROM_5M_CLOSE", "1") or "1").strip() == "1"

# Optional DF check logs (helps diagnose UNKNOWN/NaNs without spamming)
DFCHECK_ON_5M_CLOSE = (os.getenv("DFCHECK_ON_5M_CLOSE", "0") or "0").strip() == "1"

# Warn-once flags
_WARNED_PRELOAD_INJECT_FAIL = set()


# ============================================================
# EPIC MAPPING
# ============================================================

# TRADING/STREAMING epics — TODAY

def _load_epic_mapping() -> Dict[str, str]:
    raw = (os.getenv("EPICS_JSON") or "").strip()
    if raw:
        try:
            m = json.loads(raw)
            if isinstance(m, dict) and m:
                return {str(k).upper(): str(v) for k, v in m.items()}
        except Exception:
            pass

    symbol = (os.getenv("SYMBOL") or "EURUSD").strip().upper()
    epic = (os.getenv("EPIC") or f"CS.D.{symbol}.TODAY.IP").strip()
    return {symbol: epic}


EPIC_MAP = _load_epic_mapping()

# CFD epics for PRELOAD only
CFD_EPIC_MAP: Dict[str, str] = {}
raw_cfd = (os.getenv("CFD_EPICS_JSON") or "").strip()
if raw_cfd:
    try:
        tmp = json.loads(raw_cfd)
        if isinstance(tmp, dict):
            CFD_EPIC_MAP = {str(k).upper(): str(v) for k, v in tmp.items()}
    except Exception:
        CFD_EPIC_MAP = {}


# ============================================================
# Session gating
# ============================================================

def _parse_hhmm(hhmm: str) -> Tuple[int, int]:
    try:
        hh, mm = hhmm.split(":")
        return int(hh), int(mm)
    except Exception:
        return 16, 55


def _session_now() -> Optional[datetime]:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(SESSION_TZ))
    except Exception:
        return None


# ============================================================
# 3CO inline evaluation REMOVED 2026-05-13 (strategy deleted in favour
# of GBPUSD_TREND cascade-driven entries — see gbpusd_trend.py and
# docs/executor_gate_kill_list_2026-05-12.md).
# ============================================================
# ============================================================
# Utilities
# ============================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_weekend_utc() -> bool:
    return _utc_now().weekday() >= 5


def _source_brake_adx_at_bar(
    symbol: str,
    current_bar_ts: datetime,
) -> Tuple[Optional[float], Optional[str]]:
    """Source the ADX scalar for guards.trend_stretch_brake, once per bar.

    Called from each strategy's 5m-close dispatch AFTER regime_matrix.
    wait_for_bar() has returned — that Event is set inside the regime-
    engine pool worker's finally block (autobot._emit_then_route), so by
    the time this helper runs, regime_engine.latest_result(symbol) has
    been populated for this bar.

    Reads ONLY two fields off the result dict:
        "ADX"        — the scalar we pass to the brake
        "timestamp"  — used ONLY for staleness rejection
    Never reads the regime label, directional_bias, confidence, or any
    other classifier state — the brake must not couple to the
    classifier's judgement.

    Staleness gate: TREND_STRETCH_BRAKE_ADX_MAX_STALE_BARS 5m bars
    (default 1 → 300s). When the result's own timestamp is older than
    the driver's current bar by more than the tolerance, the sourced
    value is dropped and adx_source is set to "stale_failsafe" so the
    brake still fails safe (BLOCK via
    blocked_adx_unavailable_failsafe) but the reason stays
    distinguishable in telemetry from a genuinely missing ADX.

    Returns (adx_at_bar, adx_source) where adx_source ∈
    {"regime_engine", "stale_failsafe", None}. On any error, returns
    (None, None) — the brake will then fail safe (BLOCK), matching the
    pre-change behaviour on missing input.
    """
    try:
        import regime_engine as _re
        _re_result = _re.latest_result(symbol)
    except Exception:
        return None, None
    if not isinstance(_re_result, dict):
        return None, None

    _adx_raw = _re_result.get("ADX")
    if _adx_raw is None:
        return None, None
    try:
        adx_at_bar: Optional[float] = float(_adx_raw)
    except (TypeError, ValueError):
        return None, None

    # Parse the result's own timestamp for the staleness check.
    _re_ts_raw = _re_result.get("timestamp")
    _re_ts_utc: Optional[datetime] = None
    if _re_ts_raw:
        try:
            _t = datetime.fromisoformat(
                str(_re_ts_raw).replace("Z", "+00:00")
            )
            if _t.tzinfo is None:
                _t = _t.replace(tzinfo=timezone.utc)
            _re_ts_utc = _t.astimezone(timezone.utc)
        except Exception:
            _re_ts_utc = None

    # Staleness gate — env read at call time, flippable without restart.
    try:
        _stale_bars = int(os.getenv("TREND_STRETCH_BRAKE_ADX_MAX_STALE_BARS", "1") or 1)
    except (TypeError, ValueError):
        _stale_bars = 1
    _stale_max_s = float(_stale_bars) * 5.0 * 60.0

    if _re_ts_utc is None:
        return None, "stale_failsafe"  # timestamp missing → cannot verify
    try:
        _age_s = (current_bar_ts - _re_ts_utc).total_seconds()
    except Exception:
        return None, "stale_failsafe"
    if _age_s > _stale_max_s:
        return None, "stale_failsafe"

    return adx_at_bar, "regime_engine"


def _read_rest_block() -> Optional[dict]:
    try:
        if not os.path.exists(REST_PRELOAD_BLOCK_PATH):
            return None
        with open(REST_PRELOAD_BLOCK_PATH, "r") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return None


def _write_rest_block(until_epoch: int, reason: str) -> None:
    try:
        os.makedirs(os.path.dirname(REST_PRELOAD_BLOCK_PATH), exist_ok=True)
        with open(REST_PRELOAD_BLOCK_PATH, "w") as f:
            json.dump({"until": int(until_epoch), "reason": str(reason)}, f)
    except Exception:
        pass


def _rest_blocked_now() -> bool:
    b = _read_rest_block()
    if not b:
        return False
    try:
        until = int(b.get("until", 0))
        return time.time() < until
    except Exception:
        return False


def _cache_path(symbol: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{symbol.upper()}_candles.csv")


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    """Convert to float, rejecting NaN/inf."""
    try:
        if v is None:
            return default
        x = float(v)
        if x != x:
            return default
        if x == float("inf") or x == float("-inf"):
            return default
        return x
    except Exception:
        return default


def _resolve_entry_price_and_source(
    pos_key: str, decision: Any, decision_entry: float
) -> Tuple[float, str]:
    """Resolve entry price + source for signal_log persistence.

    Prefers the IG broker-confirmed fill that trade_executor stored in
    EPIC_STATE[pos_key]["entry_price"] (via fetch_deal_by_deal_reference)
    over the strategy's M5-decision price. Falls back to the decision
    price if any of:
      - ENTRY_FILL_READBACK_ENABLED is False
      - state lacks a valid finite positive fill
      - the fill is suspiciously far (>5p) from decision — a fill that
        far off is more likely a state-corruption / pos_key mismatch
        than a real slip; emit WARNING and use decision instead

    Returns (entry_price, source) where source is "ig_fill" or
    "decision_fallback". The source travels into signal_log as
    entry_price_source so every row is self-describing across the
    2026-06-15 semantic change.
    """
    try:
        dec = float(decision_entry)
    except Exception:
        return float(decision_entry or 0.0), "decision_fallback"
    if not ENTRY_FILL_READBACK_ENABLED:
        return dec, "decision_fallback"
    try:
        st = EPIC_STATE.get(pos_key) or {}
        st_entry = st.get("entry_price")
        if st_entry is None:
            return dec, "decision_fallback"
        st_entry_f = float(st_entry)
        if not math.isfinite(st_entry_f) or st_entry_f <= 0:
            return dec, "decision_fallback"
        ps_raw = getattr(decision, "pip_size", None)
        ps = float(ps_raw) if ps_raw and float(ps_raw) > 0 else 1.0
        diff_pips = abs(st_entry_f - dec) / ps
        if diff_pips > 5.0:
            logger.warning(
                "[ENTRY-FILL] %s: IG fill %.5f differs from decision %.5f "
                "by %.2fp (>5p) — using decision price",
                pos_key, st_entry_f, dec, diff_pips,
            )
            return dec, "decision_fallback"
        return st_entry_f, "ig_fill"
    except Exception:
        return dec, "decision_fallback"


def _bucket_5m(ts_numeric: float) -> int:
    try:
        return int(float(ts_numeric)) // 300
    except Exception:
        return int(time.time()) // 300


def _cooldown_ready(last_trade_ts: Optional[float]) -> Tuple[bool, float]:
    if not last_trade_ts:
        return True, 0.0
    elapsed = time.time() - float(last_trade_ts)
    remaining = max(0.0, float(COOLDOWN_SECONDS) - elapsed)
    return remaining <= 0.0, remaining


def _cooldown_key(symbol: str, epic: str) -> str:
    return f"{(symbol or '').upper()}|{str(epic or '').strip()}"


def _read_last_trade_times() -> Dict[str, float]:
    try:
        if not os.path.exists(LAST_TRADE_TIMES_PATH):
            return {}
        with open(LAST_TRADE_TIMES_PATH, "r") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, float] = {}
        for k, v in raw.items():
            try:
                out[str(k)] = float(v)
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _save_last_trade_times(times: Dict[str, float]) -> None:
    try:
        os.makedirs(os.path.dirname(LAST_TRADE_TIMES_PATH), exist_ok=True)
        with open(LAST_TRADE_TIMES_PATH, "w") as f:
            json.dump(times, f)
    except Exception:
        pass


def _sl_block_key(symbol: str, epic: str, direction: str) -> str:
    return f"{(symbol or '').upper()}|{str(epic or '').strip()}|{(direction or '').upper()}"


def _read_sl_blocks() -> Dict[str, float]:
    try:
        if not os.path.exists(LAST_SL_BLOCK_PATH):
            return {}
        with open(LAST_SL_BLOCK_PATH, "r") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, float] = {}
        for k, v in raw.items():
            try:
                out[str(k)] = float(v)
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _save_sl_blocks(blocks: Dict[str, float]) -> None:
    try:
        os.makedirs(os.path.dirname(LAST_SL_BLOCK_PATH), exist_ok=True)
        with open(LAST_SL_BLOCK_PATH, "w") as f:
            json.dump(blocks, f)
    except Exception:
        pass


_SL_BLOCKS: Dict[str, float] = _read_sl_blocks()


def _sl_block_remaining(symbol: str, epic: str, direction: str) -> float:
    until = _SL_BLOCKS.get(_sl_block_key(symbol, epic, direction))
    if not until:
        return 0.0
    return max(0.0, float(until) - time.time())


def _set_sl_block(symbol: str, epic: str, direction: str, seconds: float) -> None:
    key = _sl_block_key(symbol, epic, direction)
    _SL_BLOCKS[key] = time.time() + max(0.0, float(seconds))
    _save_sl_blocks(_SL_BLOCKS)


def _extract_bollinger_bands_from_df(df) -> Tuple[Optional[float], Optional[float]]:
    """Extract upper/lower Bollinger from last df row (native IG units)."""
    if df is None or len(df) == 0:
        return None, None
    try:
        last = df.iloc[-1]
    except Exception:
        return None, None

    def _get_any(keys):
        for k in keys:
            try:
                v = last.get(k) if hasattr(last, "get") else None
            except Exception:
                v = None
            v2 = _safe_float(v, None)
            if v2 is not None:
                return v2
        return None

    upper = _get_any(["BB_UPPER_20_2", "BB_UPPER", "bb_upper", "bb_upper_20_2", "BB_U"])
    lower = _get_any(["BB_LOWER_20_2", "BB_LOWER", "bb_lower", "bb_lower_20_2", "BB_L"])
    return upper, lower


def _extract_macd_hist_pair_from_df(df) -> Tuple[Optional[float], Optional[float]]:
    """Extract current/previous MACD histogram values from df, if present."""
    from pair_config import pick_macd_hist_pair
    return pick_macd_hist_pair(df)


# ============================================================
# Cache helpers
# ============================================================

def _max_cache_age_seconds() -> float:
    """Cache freshness budget in seconds (for visibility / optional strict mode)."""
    try:
        max_age_sec = float(MAX_CACHE_AGE_HOURS) * 3600.0
    except Exception:
        max_age_sec = 6 * 3600.0

    if _is_weekend_utc():
        weekend_min = os.getenv("PRELOAD_WEEKEND_MAX_AGE_MIN")
        if weekend_min is not None:
            try:
                max_age_sec = float(weekend_min) * 60.0
            except Exception:
                pass
        else:
            max_age_sec = max(max_age_sec, 72 * 3600.0)

    return float(max(60.0, max_age_sec))


def _standardize_cache_df(df):
    try:
        import pandas as pd

        if df is None or len(df) == 0:
            return None

        cols = [c.strip().lower() for c in df.columns]
        m = {df.columns[i]: cols[i] for i in range(len(cols))}
        df = df.rename(columns=m)

        if "time" in df.columns and "timestamp" not in df.columns:
            df = df.rename(columns={"time": "timestamp"})

        if "timestamp" not in df.columns:
            return None

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp"])

        for c in ("open", "high", "low", "close"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df[["timestamp", "open", "high", "low", "close"]]
    except Exception:
        return None


def _cache_state_from_df(df_5m) -> Tuple[str, Optional[str], Optional[float]]:
    try:
        import pandas as pd

        if df_5m is None or not isinstance(df_5m, pd.DataFrame) or df_5m.empty:
            return "EMPTY", None, None

        if "timestamp" not in df_5m.columns:
            return "ERROR", None, None

        last_ts = pd.to_datetime(df_5m["timestamp"].iloc[-1], errors="coerce", utc=True)
        if pd.isna(last_ts):
            return "ERROR", None, None

        # Age is measured from the bar's CLOSE (open + 5min), not its OPEN.
        # Cache rows are stamped with the bar's OPEN time, so a bar that
        # JUST closed has wall_clock − open == 300s — which previously
        # consumed 83% of the 360s gap-fill budget on a perfectly healthy
        # cache. Measuring from CLOSE gives the freshly-closed bar age=0,
        # so the gate only fires when at least one full bar has been
        # missed. (2026-05-27 fix; was the root cause of REST gap-fills
        # firing on every restart in the second half of the 5M window.)
        last_close = last_ts + pd.Timedelta(minutes=5)
        age_sec = (_utc_now() - last_close.to_pydatetime()).total_seconds()
        # Clamp negative ages (the bar hasn't "closed" yet by wall-clock —
        # e.g. when the cache has been polluted by a future-stamped row;
        # the future-row guard in _standardize_hist_df now blocks new
        # ingest, but existing cache rows can still be future). Treat
        # negative age as FRESH for the gap-fill gate.
        if age_sec < 0:
            age_sec = 0.0
        budget = _max_cache_age_seconds()

        state = "FRESH" if float(age_sec) <= float(budget) else "STALE"
        return state, last_ts.isoformat(), float(age_sec)
    except Exception:
        return "ERROR", None, None


def _read_cache_df(symbol: str):
    path = _cache_path(symbol)
    try:
        if not os.path.exists(path):
            return None, "MISSING", None, None
        import pandas as pd

        df = pd.read_csv(path)
        df = _standardize_cache_df(df)
        if df is None or df.empty:
            return None, "EMPTY", None, None

        state, last_ts_iso, age_sec = _cache_state_from_df(df)
        return df, state, last_ts_iso, age_sec
    except Exception:
        return None, "ERROR", None, None


def _rolling_cache_path_local(symbol: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol.upper()}_candles_rolling.csv")


def _read_rolling_cache_df(symbol: str, min_rows: int = 600):
    """Read /opt/tradingbot/cache/<SYMBOL>_candles_rolling.csv, the
    continuous indicator-enriched buffer maintained by
    candle_builder._persist_rolling_cache. Returned df is OHLC-standardised
    (timestamp/open/high/low/close, indicator columns dropped) and ready
    for build_candles. Returns (df, state, last_ts_iso, age_sec) on
    success, or (None, reason, None, None) if absent / too short / stale
    beyond the cache budget."""
    path = _rolling_cache_path_local(symbol)
    try:
        if not os.path.exists(path):
            return None, "MISSING", None, None
        import pandas as pd

        df = pd.read_csv(path)
        df = _standardize_cache_df(df)
        if df is None or df.empty:
            return None, "EMPTY", None, None
        if len(df) < int(min_rows):
            state, last_ts_iso, age_sec = _cache_state_from_df(df)
            return None, f"TOO_SHORT_{len(df)}", last_ts_iso, age_sec

        state, last_ts_iso, age_sec = _cache_state_from_df(df)
        return df, state, last_ts_iso, age_sec
    except Exception:
        return None, "ERROR", None, None


def _write_cache_df(symbol: str, df_5m) -> None:
    try:
        if df_5m is None or len(df_5m) == 0:
            return
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = _cache_path(symbol)

        df_5m = _standardize_cache_df(df_5m)
        if df_5m is None or df_5m.empty:
            return

        df_5m = df_5m.tail(int(PRELOAD_TARGET_5M_BARS)).reset_index(drop=True)
        df_5m.to_csv(path, index=False)
        logger.info(f"[CACHE/REST] [{symbol}] wrote {len(df_5m)} rows → {path}")
    except Exception as e:
        logger.warning(f"[CACHE/REST] [{symbol}] write failed: {e}")


def _write_cache_from_close_payload(symbol: str, df_closed_5m) -> None:
    if not WRITE_CACHE_FROM_5M_CLOSE:
        return
    try:
        import pandas as pd

        if df_closed_5m is None or not hasattr(df_closed_5m, "columns") or len(df_closed_5m) == 0:
            return

        d = df_closed_5m.copy()

        if "timestamp" not in d.columns and "time" in d.columns:
            d = d.rename(columns={"time": "timestamp"})

        if "timestamp" not in d.columns:
            return

        d["timestamp"] = pd.to_datetime(d["timestamp"], errors="coerce", utc=True)
        d = d.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        for c in ("open", "high", "low", "close"):
            if c not in d.columns:
                return
            d[c] = pd.to_numeric(d[c], errors="coerce")

        d = d.dropna(subset=["open", "high", "low", "close"])
        if d.empty:
            return

        d = d.tail(int(PRELOAD_TARGET_5M_BARS)).reset_index(drop=True)

        base = ["timestamp", "open", "high", "low", "close"]
        rest = [c for c in d.columns if c not in base]
        d = d[base + rest]

        path = _cache_path(symbol)
        os.makedirs(CACHE_DIR, exist_ok=True)
        d.to_csv(path, index=False)

    except Exception as e:
        logger.warning(f"[CACHE/CLOSE] [{symbol}] write failed: {e}")


# ============================================================
# REST preload (CFD-only, cache-first, replace-only)
# ============================================================

_LAST_REST_CALL_TS = 0.0


def _pick_preload_epic(symbol: str) -> Optional[str]:
    sym = str(symbol).upper()
    cfd = CFD_EPIC_MAP.get(sym)
    if cfd:
        return str(cfd)

    logger.error(f"[PRELOAD/{sym}] ❌ Missing CFD epic in CFD_EPICS_JSON; cannot REST preload for this symbol.")
    return None


def _best_effort_extract_error_code(err: Exception, hist: Any = None) -> str:
    try:
        s = str(err) or ""
        if s:
            return s
    except Exception:
        pass

    for attr in ("errorCode", "error_code", "code"):
        try:
            v = getattr(err, attr, None)
            if v:
                return str(v)
        except Exception:
            pass

    try:
        if isinstance(hist, dict):
            for k in ("errorCode", "error_code", "code", "error"):
                if k in hist and hist.get(k):
                    return str(hist.get(k))
            if "error" in hist and isinstance(hist.get("error"), dict):
                nested = hist.get("error")
                for k in ("errorCode", "code"):
                    if nested.get(k):
                        return str(nested.get(k))
    except Exception:
        pass

    return ""


def _is_allowance_error(code_or_msg: str) -> bool:
    s = (code_or_msg or "").lower()
    needles = [
        "exceeded-account-historical-data-allowance",
        "error.public-api.exceeded-account-historical-data-allowance",
        "historical-data-allowance",
    ]
    return any(n in s for n in needles)


def _normalize_hist_to_df(hist: Any) -> Any:
    if isinstance(hist, tuple) and len(hist) == 2:
        hist = hist[1]

    if hasattr(hist, "copy") and hasattr(hist, "columns"):
        try:
            return hist.copy()
        except Exception:
            return hist

    if isinstance(hist, dict):
        prices = hist.get("prices")
        if prices is None:
            prices = hist.get("data")
        if prices is None:
            prices = []

        # If prices is a DataFrame (from trading_ig format_prices), extract OHLC
        if hasattr(prices, "columns") and hasattr(prices, "iterrows"):
            try:
                import pandas as pd
                df = prices.copy()

                # trading_ig format_prices returns MultiIndex columns:
                # ('bid', 'Open'), ('bid', 'High'), etc. or ('last', 'Open'), etc.
                # Flatten to simple columns, preferring bid > last > ask
                if isinstance(df.columns, pd.MultiIndex):
                    # Flatten MultiIndex: pick preferred price type
                    level0 = df.columns.get_level_values(0).unique().tolist()
                    preferred = None
                    for pref in ("bid", "last", "ask"):
                        if pref in level0:
                            preferred = pref
                            break
                    if preferred:
                        sub = df[preferred].copy()
                        sub.columns = [c.lower() for c in sub.columns]
                    else:
                        # Take first level
                        sub = df[level0[0]].copy()
                        sub.columns = [c.lower() for c in sub.columns]
                else:
                    sub = df.copy()
                    sub.columns = [c.lower() for c in sub.columns]

                # Index is DateTime — convert to timestamp column
                sub = sub.reset_index()
                ts_col = sub.columns[0]  # First column after reset is the old index
                sub = sub.rename(columns={ts_col: "timestamp"})

                # IG REST returns timestamps via trading_ig.format_prices,
                # which parses the `snapshotTime` field (account-local
                # time — Europe/London for this account) with
                # `pd.to_datetime(..., format=DATE_FORMATS[ver])` — leaving
                # the DatetimeIndex TZ-NAIVE. Without explicit localization,
                # downstream `pd.to_datetime(..., utc=True)` in
                # _standardize_hist_df treats naive timestamps as already-UTC,
                # shifting BST-labeled bars ~1h into the future (the 2026-05-27
                # rolling-cache pollution root cause). Localize to
                # Europe/London first then convert to UTC so DST (BST/GMT)
                # is handled correctly by pandas/zoneinfo.
                try:
                    _ts = pd.to_datetime(sub["timestamp"], errors="coerce")
                    if getattr(_ts.dt, "tz", None) is None:
                        _ts = _ts.dt.tz_localize(
                            "Europe/London",
                            ambiguous="infer",
                            nonexistent="shift_forward",
                        )
                    sub["timestamp"] = _ts.dt.tz_convert("UTC")
                except Exception:
                    # If localization fails (e.g. ambiguous DST that can't
                    # be inferred), leave the column as-is and let the
                    # downstream future-row guard reject any bad rows.
                    pass

                needed = {"timestamp", "open", "high", "low", "close"}
                if needed.issubset(set(sub.columns)):
                    return sub[["timestamp", "open", "high", "low", "close"]]
            except Exception:
                return None

        if isinstance(prices, list) and prices:
            try:
                import pandas as pd

                rows = []
                for p in prices:
                    if not isinstance(p, dict):
                        continue
                    ts = p.get("snapshotTimeUTC") or p.get("snapshotTime") or p.get("timestamp") or p.get("time")

                    def _mid(x, fallback_key):
                        if isinstance(x, dict):
                            return x.get("mid")
                        return p.get(fallback_key)

                    o = _mid(p.get("openPrice"), "open")
                    h = _mid(p.get("highPrice"), "high")
                    l = _mid(p.get("lowPrice"), "low")
                    c = _mid(p.get("closePrice"), "close")

                    if c is None:
                        continue
                    rows.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c})

                if rows:
                    out_df = pd.DataFrame(rows)
                    # Same TZ handling as the DataFrame branch above. If IG
                    # returned `snapshotTimeUTC` (preferred at line above),
                    # pd.to_datetime will pick up the timezone from the
                    # string. If it fell back to `snapshotTime` (Europe/London
                    # local, TZ-naive), localize first to avoid the
                    # naive-as-UTC shift bug.
                    try:
                        _ts = pd.to_datetime(out_df["timestamp"], errors="coerce")
                        if getattr(_ts.dt, "tz", None) is None:
                            _ts = _ts.dt.tz_localize(
                                "Europe/London",
                                ambiguous="infer",
                                nonexistent="shift_forward",
                            )
                        out_df["timestamp"] = _ts.dt.tz_convert("UTC")
                    except Exception:
                        pass
                    return out_df
            except Exception:
                return None

    return None


def _minute_df_to_5m(df_minute):
    import pandas as pd

    if df_minute is None or not isinstance(df_minute, pd.DataFrame) or df_minute.empty:
        return None

    df = df_minute.copy()

    if "timestamp" not in df.columns and "time" in df.columns:
        df = df.rename(columns={"time": "timestamp"})
    if "timestamp" not in df.columns:
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"])
    if df.empty:
        return None

    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            return None
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return None

    df = df.sort_values("timestamp").reset_index(drop=True)

    ts_epoch = (df["timestamp"].astype("int64") // 10**9).astype("int64")
    bucket_epoch = (ts_epoch // 300) * 300
    df["bucket_epoch"] = bucket_epoch

    g = df.groupby("bucket_epoch", sort=True)
    out = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(g["bucket_epoch"].first(), unit="s", utc=True),
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
        }
    ).reset_index(drop=True)

    out = out.sort_values("timestamp").reset_index(drop=True)
    return out[["timestamp", "open", "high", "low", "close"]]


def _standardize_hist_df(df):
    try:
        import pandas as pd

        if df is None or len(df) == 0:
            return None

        if "timestamp" not in df.columns and "time" in df.columns:
            df = df.rename(columns={"time": "timestamp"})

        if "timestamp" not in df.columns:
            return None

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp"])
        for c in ("open", "high", "low", "close"):
            if c not in df.columns:
                return None
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)

        # Future-row guard (2026-05-27 defense-in-depth). Every REST fetch
        # routes through here, so this is the chokepoint that prevents
        # future-dated rows from poisoning the rolling cache regardless of
        # which parse branch produced them. _normalize_hist_to_df's TZ-fix
        # should already prevent this; the guard surfaces any regression
        # loudly rather than silently corrupting downstream consumers.
        _now_utc = pd.Timestamp.now(tz="UTC")
        _future_mask = df["timestamp"] > _now_utc
        if bool(_future_mask.any()):
            _n_future = int(_future_mask.sum())
            _latest_future = df.loc[_future_mask, "timestamp"].max()
            logger.error(
                f"[REST-PARSE] REJECTED {_n_future} future-dated row(s) from "
                f"REST response (latest future ts={_latest_future.isoformat()}, "
                f"now={_now_utc.isoformat()}) — possible TZ misinterpretation; "
                f"check _normalize_hist_to_df parsing path"
            )
            df = df.loc[~_future_mask].reset_index(drop=True)
            if df.empty:
                return None

        return df[["timestamp", "open", "high", "low", "close"]]
    except Exception:
        return None


def _rest_fetch_df(ig, epic: str, resolution: str, num_points: Optional[int] = None) -> Any:
    # Every historical-price fetch (5M/1M preload, HTF gap-fill, any other
    # caller that routes through this helper) is charged against the shared
    # weekly allowance. Unknown-depth fetches are charged a conservative 10.
    try:
        import rest_allowance
        _charge = int(num_points) if num_points is not None else 10
        if not rest_allowance.consume(_charge):
            st = rest_allowance.get_state()
            logger.warning(
                f"[REST-ALLOWANCE] {epic} {resolution}x{_charge} skipped — weekly budget exhausted "
                f"({st['points_used']}/{st['points_budget']}, week_start={st['week_start']})"
            )
            return None, None
    except Exception as _re:
        logger.warning(f"[REST-ALLOWANCE] budget check failed ({_re}); proceeding without gate")
        _charge = 0

    hist = None
    try:
        fn_np = getattr(ig, "fetch_historical_prices_by_epic_and_num_points", None)
        if callable(fn_np) and num_points is not None:
            hist = fn_np(epic, resolution, int(num_points))
        else:
            fn = getattr(ig, "fetch_historical_prices_by_epic", None)
            if callable(fn):
                hist = fn(epic=epic, resolution=resolution)
            else:
                if _charge:
                    try:
                        import rest_allowance
                        rest_allowance.refund(_charge)
                    except Exception:
                        pass
                raise RuntimeError("IGService missing historical fetch methods")
    except Exception:
        # Points stay consumed — IG counted the attempt on their side.
        raise

    # IG returns its authoritative allowance figure on every historical-prices
    # response. Two hosts share IG account REDACTED_IG_ACCT's 10k weekly pool but neither
    # can see the other's spend, so we capture IG's own number here on every
    # fetch. Observation-only: does not feed consume()/remaining() — the local
    # counter continues to gate. Defensive: any parse failure is swallowed
    # rather than allowed to break the fetch.
    try:
        _al = None
        if isinstance(hist, dict):
            _al = hist.get("allowance")
            if _al is None:
                _md = hist.get("metadata")
                if isinstance(_md, dict):
                    _al = _md.get("allowance")
        if isinstance(_al, dict):
            _ig_rem = _al.get("remainingAllowance")
            _ig_tot = _al.get("totalAllowance")
            _ig_exp = _al.get("allowanceExpiry")
            logger.info(
                f"[REST-ALLOWANCE-IG] {epic} {resolution} "
                f"ig_allowance_remaining={_ig_rem} ig_allowance_total={_ig_tot} "
                f"ig_allowance_expiry_s={_ig_exp}"
            )
            try:
                import rest_allowance
                rest_allowance.persist_ig_allowance(_ig_rem, _ig_tot, _ig_exp)
            except Exception:
                pass
    except Exception:
        pass

    df = _normalize_hist_to_df(hist)
    if df is None:
        return None, hist

    df = _standardize_hist_df(df)
    return df, hist


# ────────────────────────────────────────────────────────────────────────────
# v5_PIA H4 cold-start orchestration
# Wires IG REST historical-prices fetch as the primary path for H4 backfill,
# with f6b8599's 5M aggregation as the fallback. Spec & rationale:
#   docs/pia_shadow_vs_live_investigation_2026-05-13.md
#   docs/ig_allowance_preflight_2026-05-13.md
# ────────────────────────────────────────────────────────────────────────────
_V5_PIA_H4_SUFFICIENT_BARS = 20  # EMA20 requires 20 bars; skip REST if we already have >=
_V5_PIA_H4_REQUEST_BARS    = 40  # spec window (trade_plan_builder _LEVEL_LOOKBACK_BARS)
_V5_PIA_H4_LOW_ALLOWANCE   = 200  # below this we skip REST to preserve budget headroom


def _v5_pia_h4_rest_to_candles(df) -> list:
    """Convert a standardized H4 REST DataFrame to the candle-dict shape
    used by TimeframeContext._h4_closed (mirror of preload_h4_from_5m_cache
    row format). Returns [] on empty/invalid input."""
    if df is None or len(df) == 0:
        return []
    try:
        import pandas as _pd
    except Exception:
        return []
    out: list = []
    for _, row in df.iterrows():
        try:
            ts_raw = row["timestamp"]
            ts = _pd.Timestamp(ts_raw)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            ts_epoch = int(ts.timestamp())
            bucket_epoch = (ts_epoch // 14400) * 14400
            out.append({
                "timeframe":   "H4",
                "timestamp":   ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "bucket_epoch": int(bucket_epoch),
                "open":  float(row["open"]),
                "high":  float(row["high"]),
                "low":   float(row["low"]),
                "close": float(row["close"]),
            })
        except Exception:
            continue
    return out


def _v5_pia_h4_cold_start(ig, sym: str, epic: str, tf_ctx) -> dict:
    """Per-pair H4 cold-start with REST-primary, 5M-aggregation fallback.

    Order of operations:
      1. If _h4_closed[sym] already has >= 20 bars, no-op (cache sufficient).
      2. If rest_allowance.remaining() < 200, skip REST and fall through to
         5M aggregation only.
      3. Else call _rest_fetch_df(ig, epic, "HOUR_4", 40). On success, merge
         the returned bars with the existing _h4_closed[sym] list, deduped
         by bucket_epoch, sorted, capped at 40 bars.
      4. On REST failure (None / exception / empty), fall back to
         preload_h4_from_5m_cache (f6b8599). The 5M aggregator is consumed
         unmodified — this function does not refactor it.
      5. If both fail, log ERROR and leave cache untouched. Never raise.

    Returns a metrics dict for the cost-summary log line.
    """
    metrics = {
        "symbol":   sym,
        "rest":     False,   # did REST succeed and contribute bars?
        "backfill": False,   # did 5M aggregation run?
        "bars":     0,       # bars in _h4_closed[sym] after this call
        "skipped":  False,   # cache was already sufficient
    }

    try:
        existing = list(getattr(tf_ctx, "_h4_closed", {}).get(sym.upper(), []))
    except Exception:
        existing = []

    if len(existing) >= _V5_PIA_H4_SUFFICIENT_BARS:
        metrics["bars"] = len(existing)
        metrics["skipped"] = True
        return metrics

    # ── Early-warning low-allowance gate ────────────────────────────────
    rest_attempted = False
    rest_df = None
    try:
        import rest_allowance as _ra
        _remaining = int(_ra.remaining())
    except Exception:
        _remaining = -1

    if 0 <= _remaining < _V5_PIA_H4_LOW_ALLOWANCE:
        logger.warning(
            f"[V5_PIA] H4 cold-start: allowance <{_V5_PIA_H4_LOW_ALLOWANCE} "
            f"({_remaining} left) — skipping REST for {sym}, falling back to 5M aggregation"
        )
    else:
        # ── REST primary path ───────────────────────────────────────────
        rest_attempted = True
        try:
            rest_df, _hist = _rest_fetch_df(ig, epic, "HOUR_4", _V5_PIA_H4_REQUEST_BARS)
        except Exception as _rex:
            logger.warning(
                f"[V5_PIA] H4 cold-start REST failed for {sym}: "
                f"{type(_rex).__name__}: {_rex} — falling back to 5M aggregation"
            )
            rest_df = None

    if rest_attempted and rest_df is not None and len(rest_df) > 0:
        # Merge fetched bars with existing cache, dedupe by bucket_epoch,
        # sort chronologically, cap at 40 bars.
        try:
            fetched = _v5_pia_h4_rest_to_candles(rest_df)
            merged_by_epoch: Dict[int, Dict[str, Any]] = {}
            for c in existing:
                be = c.get("bucket_epoch")
                if isinstance(be, int):
                    merged_by_epoch[be] = c
            for c in fetched:
                be = c.get("bucket_epoch")
                if isinstance(be, int):
                    merged_by_epoch[be] = c  # REST wins on overlap
            merged = sorted(merged_by_epoch.values(), key=lambda c: c["bucket_epoch"])
            merged = merged[-_V5_PIA_H4_REQUEST_BARS:]
            tf_ctx._h4_closed[sym.upper()] = merged
            metrics["rest"] = True
            metrics["bars"] = len(merged)
            return metrics
        except Exception as _me:
            logger.warning(
                f"[V5_PIA] H4 cold-start merge failed for {sym}: "
                f"{type(_me).__name__}: {_me} — falling back to 5M aggregation"
            )
            # fall through to 5M aggregation
    elif rest_attempted:
        logger.warning(
            f"[V5_PIA] H4 cold-start REST returned no data for {sym} "
            "— falling back to 5M aggregation"
        )

    # ── 5M aggregation fallback (f6b8599 unmodified) ────────────────────
    try:
        import pandas as _pd
        _h4_path = _cache_path(sym)
        _h4_df = None
        if os.path.exists(_h4_path):
            _h4_df = _pd.read_csv(_h4_path)
        if _h4_df is not None and len(_h4_df) > 0:
            summary = tf_ctx.preload_h4_from_5m_cache(sym.upper(), epic, _h4_df)
            loaded = int(summary.get("h4_candles_loaded", 0))
            metrics["backfill"] = True
            metrics["bars"] = loaded
            if loaded == 0:
                logger.error(
                    f"[V5_PIA] H4 cold-start FAILED for {sym}: no REST data and "
                    "no 5M backfill — PIA will abstain on insufficient_h4_bars"
                )
            return metrics
    except Exception as _be:
        logger.warning(
            f"[V5_PIA] H4 cold-start 5M aggregation raised for {sym}: "
            f"{type(_be).__name__}: {_be}"
        )

    # Both paths exhausted with no bars loaded.
    logger.error(
        f"[V5_PIA] H4 cold-start FAILED for {sym}: no REST data and "
        "no 5M backfill — PIA will abstain on insufficient_h4_bars"
    )
    return metrics


def _scan_internal_gaps(df, ts_col: str = "timestamp", threshold_secs: float = 360.0):
    """Return a list of (prev_ts, next_ts, gap_secs) tuples for every
    pair of adjacent rows in df whose time delta exceeds threshold_secs.

    df is expected to have a sortable timestamp column. Empty df, single
    row, or any unexpected error → empty list. The function is read-only.
    """
    try:
        if df is None or len(df) < 2:
            return []
        import pandas as _pd
        col = ts_col if ts_col in df.columns else ("time" if "time" in df.columns else None)
        if col is None:
            return []
        ts = _pd.to_datetime(df[col], utc=True, errors="coerce").dropna().sort_values().reset_index(drop=True)
        if len(ts) < 2:
            return []
        deltas = ts.diff().dt.total_seconds()
        gaps = []
        for i in range(1, len(ts)):
            d = float(deltas.iloc[i]) if not _pd.isna(deltas.iloc[i]) else 0.0
            if d > float(threshold_secs):
                gaps.append((ts.iloc[i - 1].to_pydatetime(), ts.iloc[i].to_pydatetime(), d))
        return gaps
    except Exception:
        return []


def _is_fx_session_closed(ts) -> bool:
    """Coarse check: is `ts` (tz-aware UTC) inside the FX-closed weekend
    window for this broker? Returns True for: Saturday all day, Fri >= 21
    UTC, and Sun < 20 UTC. Observed broker behaviour on IG demo: bars stop
    at Fri ~20:55 UTC and resume at Sun ~20:00 UTC (rolling-spot CFD)."""
    try:
        wd = ts.weekday()  # Mon=0 .. Sun=6
        if wd == 5:
            return True
        if wd == 4 and ts.hour >= 21:
            return True
        if wd == 6 and ts.hour < 20:
            return True
        return False
    except Exception:
        return False


def _is_weekend_gap(prev_ts, next_ts) -> bool:
    """Return True if the gap (prev_ts → next_ts) is session/weekend-closed.

    Two conditions, either is sufficient:
      1. Gap is large (>=6h) — no real intraday gap is 6h+; spans a
         broker-closed window by definition. Catches the multi-day
         weekend even when the boundary bars sit just before/after the
         closed-window clock thresholds.
      2. Either endpoint sits in the FX-closed window. Catches
         single-bar session-edge gaps (e.g. EURUSD Sun 20:00→20:10)."""
    try:
        gap_secs = (next_ts - prev_ts).total_seconds()
        if gap_secs >= 6 * 3600:
            return True
        return _is_fx_session_closed(prev_ts) or _is_fx_session_closed(next_ts)
    except Exception:
        return False


def _rest_preload_symbol(ig, symbol: str, today_epic: str):
    global _LAST_REST_CALL_TS

    # Phase 4B preload-from-rolling-cache. The rolling buffer
    # (_candles_rolling.csv) is the continuous 600-bar history maintained
    # by candle_builder._persist_rolling_cache and is the only on-disk
    # source long enough to satisfy the strictest shadow-classifier
    # warmup (ATR_PCTL_14 = 576 bars). Prefer it over the 50-row live
    # cache and over REST. Note the symmetric "_candles_deep.csv" file
    # exists but was last refreshed by build_deep_cache.py on 2026-03-19
    # and would inject ~41 days of stale history — not used here.
    rolling_df, rolling_state, rolling_last_ts, rolling_age_sec = _read_rolling_cache_df(
        symbol, min_rows=int(PRELOAD_TARGET_5M_BARS)
    )

    # ── 5M REST gap-fill (2026-05-24) ─────────────────────────────────
    # If the rolling cache is loaded but its last bar is more than the
    # grace window behind wall-clock, fetch the missing 5M bars from REST
    # and merge before seeding. Mirrors the H1/D1 gap-fill path at the
    # HTF preload block (see autobot.py:5031-5072). On allowance error,
    # set the REST block flag and fall through to the existing FRESH /
    # STALE logic — candle_builder's contiguity guard then truncates the
    # stale-seed buffer when the first live close lands on the other side
    # of the gap. Kill-switch: REST_5M_GAPFILL_ENABLED=0.
    if (
        REST_5M_GAPFILL_ENABLED
        and rolling_df is not None
        and rolling_age_sec is not None
        and float(rolling_age_sec) > float(REST_5M_GAPFILL_GRACE_SECS)
        and not _rest_blocked_now()
        and REST_PRELOAD_ENABLED
    ):
        _gf_epic = _pick_preload_epic(symbol)
        if _gf_epic:
            _points_needed = max(
                5,
                int(float(rolling_age_sec) / 300.0) + 5,
            )
            _points_needed = min(_points_needed, int(REST_5M_GAPFILL_MAX_POINTS))
            try:
                _now_t = time.time()
                if _now_t - _LAST_REST_CALL_TS < REST_PRELOAD_MIN_GAP_SECS:
                    time.sleep(max(0.0, REST_PRELOAD_MIN_GAP_SECS - (_now_t - _LAST_REST_CALL_TS)))
                _LAST_REST_CALL_TS = time.time()
                logger.info(
                    f"[PRELOAD/{symbol}] 5M REST gap-fill: age={float(rolling_age_sec):.0f}s "
                    f"last_ts={rolling_last_ts} requesting {_points_needed}x MINUTE_5 via epic={_gf_epic}"
                )
                _gf_df, _gf_raw = _rest_fetch_df(ig, _gf_epic, "MINUTE_5", _points_needed)
                if _gf_df is not None and len(_gf_df) > 0:
                    # Merge: concat cached + fresh, dedupe by time
                    # (fresh wins on conflict — implemented by keep="last"
                    # since fresh rows are appended after cached). The
                    # time column name varies — _read_rolling_cache_df
                    # returns "timestamp", _rest_fetch_df returns
                    # "timestamp" too; normalise both before merge.
                    import pandas as _pd
                    _ts_col_cached = "timestamp" if "timestamp" in rolling_df.columns else "time"
                    _ts_col_fresh = "timestamp" if "timestamp" in _gf_df.columns else "time"
                    _cached_n = rolling_df.rename(columns={_ts_col_cached: "timestamp"}).copy()
                    _fresh_n = _gf_df.rename(columns={_ts_col_fresh: "timestamp"}).copy()
                    _cached_n["timestamp"] = _pd.to_datetime(_cached_n["timestamp"], utc=True, errors="coerce")
                    _fresh_n["timestamp"] = _pd.to_datetime(_fresh_n["timestamp"], utc=True, errors="coerce")
                    _merged = _pd.concat([_cached_n, _fresh_n], ignore_index=True)
                    _merged = _merged.dropna(subset=["timestamp"])
                    _merged = _merged.drop_duplicates(subset=["timestamp"], keep="last")
                    _merged = _merged.sort_values("timestamp").reset_index(drop=True)
                    _merged = _merged.tail(int(PRELOAD_TARGET_5M_BARS)).reset_index(drop=True)
                    _new_last_ts = _merged["timestamp"].iloc[-1] if len(_merged) else None
                    logger.info(
                        f"[PRELOAD/{symbol}] 5M gap-fill OK: fetched={len(_gf_df)} "
                        f"merged_rows={len(_merged)} new_last_ts={_new_last_ts}"
                    )
                    _write_cache_df(symbol, _merged)
                    return _merged, "CACHE_ROLLING+REST_GAPFILL"
                else:
                    logger.warning(
                        f"[PRELOAD/{symbol}] 5M gap-fill returned empty df — falling through"
                    )
            except Exception as _gf_err:
                _code = _best_effort_extract_error_code(_gf_err)
                if _is_allowance_error(_code):
                    _until = int(time.time() + REST_PRELOAD_BLOCK_SECS)
                    _write_rest_block(_until, "5m-gapfill-allowance")
                    logger.warning(
                        f"[PRELOAD/{symbol}] 5M gap-fill blocked by allowance; "
                        f"REST disabled for {REST_PRELOAD_BLOCK_SECS}s — "
                        f"falling back to stale cache (contiguity guard will truncate)"
                    )
                else:
                    logger.warning(
                        f"[PRELOAD/{symbol}] 5M gap-fill failed: {_gf_err} — falling through"
                    )

    # ── 5M REST internal-gap backfill (2026-06-15) ───────────────────
    # The tail-age block above repairs a stale-tail cache. This block
    # repairs INTERNAL holes (a prior restart that straddled a 5M close
    # leaves the bar missing from the rolling cache). Each gap window is
    # fetched from IG REST MINUTE_5, merged via the same dedupe-by-ts
    # pattern, and the patched buffer replaces rolling_df so the FRESH
    # path below returns the contiguous buffer. Flag: default OFF via
    # STRUCTURE_BUFFER_GAPFILL_ENABLED.
    if (
        STRUCTURE_BUFFER_GAPFILL_ENABLED
        and rolling_df is not None
        and not _rest_blocked_now()
        and REST_PRELOAD_ENABLED
    ):
        try:
            _ts_col_now = "timestamp" if "timestamp" in rolling_df.columns else "time"
            _gaps = _scan_internal_gaps(
                rolling_df,
                ts_col=_ts_col_now,
                threshold_secs=STRUCTURE_BUFFER_GAPFILL_MAX_GAP_SECS,
            )
            if _gaps:
                # Filter out weekend / session-closed windows (no broker
                # data → fetch would burn allowance and return empty).
                _real_gaps = []
                for _prev_ts, _next_ts, _gsec in _gaps:
                    if STRUCTURE_BUFFER_GAPFILL_SKIP_WEEKEND and _is_weekend_gap(_prev_ts, _next_ts):
                        logger.info(
                            f"[PRELOAD/{symbol}] internal-gap skip (weekend): "
                            f"{_prev_ts.isoformat()} → {_next_ts.isoformat()} ({_gsec:.0f}s)"
                        )
                        continue
                    _real_gaps.append((_prev_ts, _next_ts, _gsec))
                if _real_gaps:
                    _bf_epic = _pick_preload_epic(symbol)
                    if _bf_epic:
                        # IG's by_num_points endpoint returns the LAST N
                        # bars from now backwards. To reach the OLDEST
                        # gap we need enough points to cover (now → oldest
                        # gap prev_ts). Width-of-gap is irrelevant —
                        # what matters is how far back we must fetch.
                        _now_utc = _utc_now()
                        _oldest_prev = min(g[0] for g in _real_gaps)
                        try:
                            _secs_back = max(0.0, (_now_utc - _oldest_prev).total_seconds())
                        except Exception:
                            _secs_back = 0.0
                        _points_needed = int(_secs_back / 300.0) + 5
                        _points_needed = max(5, _points_needed)
                        _points_needed = min(_points_needed, int(STRUCTURE_BUFFER_GAPFILL_MAX_POINTS))
                        _oldest_gap_age_bars = int(_secs_back / 300.0)
                        _total_gap_secs = sum(g[2] for g in _real_gaps)
                        logger.info(
                            f"[PRELOAD/{symbol}] internal-gap backfill: {len(_real_gaps)} gap(s) "
                            f"total_width={_total_gap_secs:.0f}s, requesting {_points_needed}x MINUTE_5 "
                            f"via epic={_bf_epic} (reach_back≈{_oldest_gap_age_bars} bars)"
                        )
                        try:
                            _now_t = time.time()
                            if _now_t - _LAST_REST_CALL_TS < REST_PRELOAD_MIN_GAP_SECS:
                                time.sleep(max(0.0, REST_PRELOAD_MIN_GAP_SECS - (_now_t - _LAST_REST_CALL_TS)))
                            _LAST_REST_CALL_TS = time.time()
                            _bf_df, _bf_raw = _rest_fetch_df(ig, _bf_epic, "MINUTE_5", _points_needed)
                            if _bf_df is not None and len(_bf_df) > 0:
                                import pandas as _pd
                                _ts_col_cached = "timestamp" if "timestamp" in rolling_df.columns else "time"
                                _ts_col_fresh = "timestamp" if "timestamp" in _bf_df.columns else "time"
                                _cached_n = rolling_df.rename(columns={_ts_col_cached: "timestamp"}).copy()
                                _fresh_n = _bf_df.rename(columns={_ts_col_fresh: "timestamp"}).copy()
                                _cached_n["timestamp"] = _pd.to_datetime(_cached_n["timestamp"], utc=True, errors="coerce")
                                _fresh_n["timestamp"] = _pd.to_datetime(_fresh_n["timestamp"], utc=True, errors="coerce")
                                _merged = _pd.concat([_cached_n, _fresh_n], ignore_index=True)
                                _merged = _merged.dropna(subset=["timestamp"])
                                _merged = _merged.drop_duplicates(subset=["timestamp"], keep="last")
                                _merged = _merged.sort_values("timestamp").reset_index(drop=True)
                                _merged = _merged.tail(int(PRELOAD_TARGET_5M_BARS)).reset_index(drop=True)
                                # Re-scan after merge: confirm remaining gaps
                                _post_gaps = _scan_internal_gaps(
                                    _merged, ts_col="timestamp",
                                    threshold_secs=STRUCTURE_BUFFER_GAPFILL_MAX_GAP_SECS,
                                )
                                # Filter out weekend ones from the post count for clarity
                                _post_real = [
                                    g for g in _post_gaps
                                    if not (STRUCTURE_BUFFER_GAPFILL_SKIP_WEEKEND and _is_weekend_gap(g[0], g[1]))
                                ]
                                logger.info(
                                    f"[PRELOAD/{symbol}] internal-gap backfill OK: fetched={len(_bf_df)} "
                                    f"pre_gaps={len(_real_gaps)} post_gaps={len(_post_real)} "
                                    f"merged_rows={len(_merged)}"
                                )
                                rolling_df = _merged
                                # Update tail-age metadata so the FRESH gate stays consistent
                                try:
                                    _last_ts = _merged["timestamp"].iloc[-1]
                                    rolling_last_ts = _last_ts.isoformat() if hasattr(_last_ts, "isoformat") else str(_last_ts)
                                    _last_close = _last_ts + _pd.Timedelta(minutes=5)
                                    rolling_age_sec = max(0.0, (_utc_now() - _last_close.to_pydatetime()).total_seconds())
                                    rolling_state = "FRESH" if float(rolling_age_sec) <= float(_max_cache_age_seconds()) else "STALE"
                                except Exception:
                                    pass
                                # Persist the patched buffer so the next
                                # restart sees the repaired cache.
                                _write_cache_df(symbol, _merged)
                            else:
                                logger.warning(
                                    f"[PRELOAD/{symbol}] internal-gap backfill returned empty df — "
                                    f"falling through (contiguity guard will truncate)"
                                )
                        except Exception as _bf_err:
                            _code = _best_effort_extract_error_code(_bf_err)
                            if _is_allowance_error(_code):
                                _until = int(time.time() + REST_PRELOAD_BLOCK_SECS)
                                _write_rest_block(_until, "5m-internalgap-allowance")
                                logger.warning(
                                    f"[PRELOAD/{symbol}] internal-gap backfill blocked by allowance; "
                                    f"REST disabled for {REST_PRELOAD_BLOCK_SECS}s — "
                                    f"falling back to existing path (contiguity guard will truncate)"
                                )
                            else:
                                logger.warning(
                                    f"[PRELOAD/{symbol}] internal-gap backfill failed: {_bf_err} — falling through"
                                )
        except Exception as _scan_err:
            logger.warning(
                f"[PRELOAD/{symbol}] internal-gap scan failed: {_scan_err} — falling through"
            )

    if rolling_df is not None and rolling_state in ("FRESH",) and ALLOW_STALE_CACHE_FOR_ARMING:
        try:
            rolling_df2 = rolling_df.tail(int(PRELOAD_TARGET_5M_BARS)).reset_index(drop=True)
        except Exception:
            rolling_df2 = rolling_df
        logger.info(
            f"[PRELOAD/{symbol}] using rolling cache: rows={len(rolling_df2)} "
            f"state={rolling_state} last_ts={rolling_last_ts}"
        )
        return rolling_df2, f"CACHE_ROLLING,{rolling_state}"

    cache_df, cache_state, cache_last_ts, cache_age_sec = _read_cache_df(symbol)
    cache_rows = int(len(cache_df)) if cache_df is not None else 0

    if cache_df is not None and cache_rows >= int(MIN_CACHE_CANDLES) and ALLOW_STALE_CACHE_FOR_ARMING:
        try:
            cache_df2 = cache_df.tail(int(PRELOAD_TARGET_5M_BARS)).reset_index(drop=True)
        except Exception:
            cache_df2 = cache_df
        src = "CACHE,ARM" if cache_state == "FRESH" else "CACHE,STALE_ARM"
        return cache_df2, src

    if cache_df is not None and cache_rows >= int(MIN_CACHE_CANDLES) and str(cache_state) == "FRESH":
        try:
            cache_df2 = cache_df.tail(int(PRELOAD_TARGET_5M_BARS)).reset_index(drop=True)
        except Exception:
            cache_df2 = cache_df
        return cache_df2, f"CACHE,{cache_state}"

    if _rest_blocked_now() or not REST_PRELOAD_ENABLED:
        if cache_df is not None and ALLOW_STALE_CACHE_IF_REST_BLOCKED:
            return cache_df, f"CACHE,{cache_state}"
        return None, "TICKS,STALE"

    preload_epic = _pick_preload_epic(symbol)
    if not preload_epic:
        if cache_df is not None and ALLOW_STALE_CACHE_IF_REST_BLOCKED:
            return cache_df, f"CACHE,{cache_state}"
        return None, "TICKS,STALE"

    now = time.time()
    if now - _LAST_REST_CALL_TS < REST_PRELOAD_MIN_GAP_SECS:
        time.sleep(max(0.0, REST_PRELOAD_MIN_GAP_SECS - (now - _LAST_REST_CALL_TS)))
    _LAST_REST_CALL_TS = time.time()

    try:
        if PREFER_CHEAP_5M_PRELOAD:
            n5 = int(max(int(MIN_CACHE_CANDLES), int(CHEAP_5M_POINTS)))
            logger.info(
                f"[PRELOAD/{symbol}] REST(CFD) cheap 5m fetch: {n5}x MINUTE_5 via epic={preload_epic} "
                f"(cache rows={cache_rows} state={cache_state} last_ts={cache_last_ts})"
            )
            df_5m, raw = _rest_fetch_df(ig, preload_epic, "MINUTE_5", n5)
            if df_5m is not None and len(df_5m) > 0:
                df_5m = df_5m.tail(int(PRELOAD_TARGET_5M_BARS)).reset_index(drop=True)
                have_5m = int(len(df_5m))
                if have_5m >= int(MIN_CACHE_CANDLES):
                    _write_cache_df(symbol, df_5m)
                    return df_5m, "REST(CFD,5M)"

        num_points_1m = int(max(50, PRELOAD_REST_1M_POINTS))
        logger.info(
            f"[PRELOAD/{symbol}] REST(CFD) minute fallback: {num_points_1m}x MINUTE via epic={preload_epic} "
            f"to build {PRELOAD_TARGET_5M_BARS}x 5m candles (cache rows={cache_rows} state={cache_state} last_ts={cache_last_ts})"
        )

        df_min, raw = _rest_fetch_df(ig, preload_epic, "MINUTE", num_points_1m)
        if df_min is None or df_min.empty:
            raise RuntimeError("REST preload returned empty/invalid minute df")

        df_5m = _minute_df_to_5m(df_min)
        if df_5m is None or df_5m.empty:
            raise RuntimeError("Failed to aggregate minute->5m candles")

        df_5m = df_5m.tail(int(PRELOAD_TARGET_5M_BARS)).reset_index(drop=True)
        have_5m = int(len(df_5m))

        if have_5m < int(MIN_CACHE_CANDLES):
            raise RuntimeError(f"REST(CFD) produced only {have_5m}x 5m candles (< MIN_CACHE_CANDLES={MIN_CACHE_CANDLES})")

        _write_cache_df(symbol, df_5m)
        return df_5m, "REST(CFD,1M_AGG)"

    except Exception as e:
        code = _best_effort_extract_error_code(e)
        if _is_allowance_error(code):
            until = int(time.time() + REST_PRELOAD_BLOCK_SECS)
            _write_rest_block(until, "error.public-api.exceeded-account-historical-data-allowance")
            logger.warning(
                f"[PRELOAD/{symbol}] REST blocked by allowance; disabling REST preloads for {REST_PRELOAD_BLOCK_SECS}s (until {until})."
            )
        else:
            logger.warning(f"[PRELOAD/{symbol}] REST preload failed: {e}")

        if cache_df is not None and ALLOW_STALE_CACHE_IF_REST_BLOCKED:
            return cache_df, f"CACHE,{cache_state}"
        return None, "TICKS,STALE"


# ============================================================
# Strategy wiring
# ============================================================

def _load_strategy_module():
    import importlib
    return importlib.import_module("strategy_logic")


def _call_strategy_compat(
    fn: Callable,
    symbol: str,
    epic: str,
    bid: float,
    ask: float,
    mid: float,
    df: Any,
    has_open_position: bool,
    htf_snapshot: Any,
    extra_kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    import inspect

    kwargs: Dict[str, Any] = {
        "symbol": symbol,
        "epic": epic,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "mid_price": mid,
        "df": df,
        "has_open_position": has_open_position,
        "htf_snapshot": htf_snapshot,
    }
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    sig = inspect.signature(fn)
    params = sig.parameters

    for p in params.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            return fn(**kwargs)

    filtered = {k: v for k, v in kwargs.items() if k in params}
    return fn(**filtered)


# ============================================================
# NY close + software BE (informational only)
# ============================================================

def _ny_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return None


@dataclass
class NYCloseState:
    last_done_date_by_epic: Dict[str, str]


# ── BRIEFING_EXECUTION EOD close state ────────────────────────────────
# Tracks the UTC date on which the once-per-day EOD sweep last fired, so
# the helper self-gates and only runs once per calendar day even though
# it's called every tick. On first call after startup, if the EOD time
# has already passed for today, record today's date so we DO NOT fire
# retroactively — wait for tomorrow's scheduled time. Simple dict (no
# dataclass) because this is process-lifetime state, not persisted.
_BE_EOD_CLOSE_STATE: Dict[str, Any] = {
    "last_fired_date": None,   # str "YYYY-MM-DD" of last fire, or None
    "startup_checked": False,  # set True after first tick-time eval
}
# LS-thread refactor (2026-05-08): per the safety audit (§1), this
# once-per-day flag is mutated from per-pair workers and needs a small
# lock so two workers can't both pass the "first fire today" check.
_BE_EOD_LOCK: threading.Lock = threading.Lock()

def _apply_briefing_exec_eod_close(utc_now: datetime) -> None:
    """Once-per-day sweep: close all BRIEFING_EXECUTION positions at EOD.

    Env-gated via BRIEFING_EXEC_EOD_CLOSE_ENABLED (default 1). Time via
    BRIEFING_EXEC_EOD_CLOSE_UTC (default "21:00"). Called every tick; the
    function itself handles date-bookkeeping so it only closes once per
    UTC day.

    Startup behaviour: if the bot restarts after the EOD time on a given
    day, we skip that day's close (do NOT fire retroactively) and wait
    for tomorrow. Any BE position still open at restart simply carries
    forward to the next EOD — the broker SL/TP remains the only exit
    until then.
    """
    if not _BE_EOD_CLOSE_ENABLED:
        return
    try:
        eod_hh, eod_mm = _parse_hhmm(_BE_EOD_CLOSE_UTC)
    except Exception:
        logger.warning(
            "[BRIEFING-EXEC] invalid BRIEFING_EXEC_EOD_CLOSE_UTC=%r — EOD close disabled",
            _BE_EOD_CLOSE_UTC,
        )
        return

    today_utc = utc_now.strftime("%Y-%m-%d")
    eod_today = utc_now.replace(hour=eod_hh, minute=eod_mm, second=0, microsecond=0)
    past_eod = utc_now >= eod_today

    # One-time startup check + once-per-day fire are read-modify-write on
    # _BE_EOD_CLOSE_STATE; under per-pair workers, two pairs can race here
    # so the flag-check + flag-set is wrapped in _BE_EOD_LOCK.
    with _BE_EOD_LOCK:
        if not _BE_EOD_CLOSE_STATE["startup_checked"]:
            _BE_EOD_CLOSE_STATE["startup_checked"] = True
            if past_eod:
                _BE_EOD_CLOSE_STATE["last_fired_date"] = today_utc
                logger.info(
                    "[BRIEFING-EXEC] EOD-CLOSE startup: current UTC %s >= %02d:%02d — "
                    "skipping today's EOD close (will fire tomorrow at %02d:%02d UTC)",
                    utc_now.strftime("%H:%M"), eod_hh, eod_mm, eod_hh, eod_mm,
                )
                return

        if _BE_EOD_CLOSE_STATE["last_fired_date"] == today_utc:
            return
        if not past_eod:
            return

        # Atomically mark today as fired so no concurrent worker re-enters.
        _BE_EOD_CLOSE_STATE["last_fired_date"] = today_utc

    # Fire: iterate every active BE position across all epics.
    closed_count = 0
    # Snapshot EPIC_STATE under its lock so a concurrent worker cannot
    # mutate it during the EOD close iteration.
    from trade_executor import EPIC_STATE_LOCK as _EPIC_STATE_LOCK_BE
    with _EPIC_STATE_LOCK_BE:
        _be_eod_items = list(EPIC_STATE.items())
    for _pk, _st in _be_eod_items:
        if not _st.get("active"):
            continue
        _mode = str(_st.get("mode") or "").upper()
        if not _is_briefing_exec_mode(_mode):
            continue
        _epic_e = str(_st.get("epic") or _pk.split("|")[0])
        _pair_e = next((s for s, e in EPIC_MAP.items() if e == _epic_e), _epic_e)
        _entry_e = _st.get("entry_price")
        _last_mid_e = _st.get("last_mid") or _st.get("exit_price") or _entry_e
        _dir_e = str(_st.get("direction") or "").upper()
        _pip_sz_e = _st.get("pip_size") or 0.0001
        _pnl_e = None
        if _entry_e is not None and _last_mid_e is not None:
            try:
                if _dir_e == "BUY":
                    _pnl_e = round((float(_last_mid_e) - float(_entry_e)) / _pip_sz_e, 1)
                elif _dir_e == "SELL":
                    _pnl_e = round((float(_entry_e) - float(_last_mid_e)) / _pip_sz_e, 1)
            except Exception:
                pass
        logger.info(
            "[BRIEFING-EXEC] EOD-CLOSE epic=%s mode=%s entry=%s close=%s realised_pnl=%sp",
            _epic_e, _mode, _entry_e, _last_mid_e,
            f"{_pnl_e:+.1f}" if _pnl_e is not None else "n/a",
        )
        try:
            close_position(pos_key=_pk, reason="EOD_CLOSE", exit_hint_price=_last_mid_e)
            closed_count += 1
            try:
                send_telegram_message(
                    f"🌙 <b>BRIEFING_EXEC EOD close:</b> {_pair_e} {_dir_e} "
                    f"closed at {utc_now.strftime('%H:%M')} UTC "
                    f"(pnl={_pnl_e:+.1f}p)" if _pnl_e is not None else
                    f"🌙 <b>BRIEFING_EXEC EOD close:</b> {_pair_e} {_dir_e} "
                    f"closed at {utc_now.strftime('%H:%M')} UTC"
                )
            except Exception:
                pass
        except Exception as _eod_e:
            logger.error(
                "[BRIEFING-EXEC] EOD-CLOSE failed for %s: %s", _pk, _eod_e,
                exc_info=True,
            )
    if closed_count:
        logger.info(
            "[BRIEFING-EXEC] EOD-CLOSE sweep complete: closed %d position(s) at %s UTC",
            closed_count, utc_now.strftime("%H:%M"),
        )


def _build_london_summary(symbol: str, today_utc: str) -> Optional[Any]:
    """Read /opt/tradingbot/data/candles/<sym>/<today>.csv and return a
    LondonSummary for the 06:45-12:25 UTC window. Returns None when the
    file is missing or the window is empty (e.g. weekend, missing data).
    """
    from briefing_execution import LondonSummary, Bar
    from pathlib import Path as _Path
    import csv as _csv

    candle_path = _Path("/opt/tradingbot/data/candles") / symbol.upper() / f"{today_utc}.csv"
    if not candle_path.exists():
        logger.warning(
            "[BRIEFING-EXEC] NY-EVAL %s: candle file %s not found — skipping",
            symbol, candle_path,
        )
        return None

    win_start = f"{today_utc}T06:45:00"
    win_end   = f"{today_utc}T12:25:00"
    bars: List[Bar] = []
    try:
        with candle_path.open() as fh:
            reader = _csv.DictReader(fh)
            for row in reader:
                ts_raw = (row.get("timestamp") or "").strip()
                if not ts_raw:
                    continue
                # Compare lexically — ISO8601 timestamps sort correctly
                cmp_ts = ts_raw[:19]  # strip tz suffix for comparison
                if cmp_ts < win_start or cmp_ts > win_end:
                    continue
                try:
                    bars.append(Bar(
                        timestamp=datetime.fromisoformat(ts_raw.replace("Z", "+00:00")),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                    ))
                except (KeyError, TypeError, ValueError) as exc:
                    logger.debug(
                        "[BRIEFING-EXEC] NY-EVAL %s skipping bad row %r: %s",
                        symbol, row, exc,
                    )
                    continue
    except Exception as exc:
        logger.warning(
            "[BRIEFING-EXEC] NY-EVAL %s: failed to read %s: %s",
            symbol, candle_path, exc,
        )
        return None

    if not bars:
        logger.warning(
            "[BRIEFING-EXEC] NY-EVAL %s: no bars in 06:45-12:25 UTC window of %s",
            symbol, candle_path,
        )
        return None

    bars.sort(key=lambda b: b.timestamp)
    high = max(b.high for b in bars)
    low  = min(b.low  for b in bars)
    pip_size = _BE_PIP_SIZE_FOR_SUMMARY.get(symbol.upper(), 1.0)
    return LondonSummary(
        symbol=symbol.upper(),
        date_utc=datetime.strptime(today_utc, "%Y-%m-%d").date(),
        open_price=bars[0].open,
        close_price=bars[-1].close,
        high=high,
        low=low,
        range_pips=(high - low) / pip_size,
        bars_06_45_to_12_25=bars,
    )


# IG FX feeds are 1 point == 1 pip across the configured pairs; using a
# constant of 1.0 matches the pair_config.POINTS_PER_PIP convention used
# by morning_briefing for pip distance calculations.
_BE_PIP_SIZE_FOR_SUMMARY: Dict[str, float] = {
    "GBPUSD": 1.0, "EURUSD": 1.0, "USDJPY": 1.0, "USDCAD": 1.0, "GBPJPY": 1.0,
}


def _apply_briefing_exec_ny_evaluation(symbol: str, utc_now: datetime) -> None:
    """Once-per-(pair, UTC-day) NY plan evaluation at 12:30 UTC.

    Self-gates: returns immediately when (a) the feature is disabled, (b)
    we haven't yet reached the configured time today, or (c) we already
    fired for *symbol* today. Restart-safe — runs retroactively if the bot
    came back up after 12:30.
    """
    if not _BE_NY_EVAL_ENABLED:
        return
    try:
        eval_h, eval_m = _parse_hhmm(_BE_NY_EVAL_UTC)
    except Exception:
        logger.warning(
            "[BRIEFING-EXEC] invalid BRIEFING_EXEC_NY_EVAL_UTC=%r — NY eval disabled",
            _BE_NY_EVAL_UTC,
        )
        return
    today_utc = utc_now.strftime("%Y-%m-%d")
    eval_today = utc_now.replace(hour=eval_h, minute=eval_m, second=0, microsecond=0)
    if utc_now < eval_today:
        return
    sym_u = symbol.upper()
    if _BE_NY_EVAL_STATE.get(sym_u) == today_utc:
        return

    # Mark first so we don't retry on every tick if the path raises
    _BE_NY_EVAL_STATE[sym_u] = today_utc

    summary = _build_london_summary(sym_u, today_utc)
    if summary is None:
        logger.info(
            "[BRIEFING-EXEC] NY-EVAL %s: London summary unavailable — "
            "evaluator skipped for %s",
            sym_u, today_utc,
        )
        return

    try:
        from strategy_logic import evaluate_signals as _es_ref
        _be_strat = getattr(_es_ref, "_be_strat", None)
        if _be_strat is None:
            from briefing_execution import BriefingExecutionStrategy
            _es_ref._be_strat = BriefingExecutionStrategy()
            _be_strat = _es_ref._be_strat
        pip_size = _BE_PIP_SIZE_FOR_SUMMARY.get(sym_u, 1.0)
        _be_strat.evaluate_ny_plans(sym_u, summary, pip_size=pip_size)
    except Exception as exc:
        logger.error(
            "[BRIEFING-EXEC] NY-EVAL %s: evaluator raised %s",
            sym_u, exc, exc_info=True,
        )



def _should_close_for_ny_end(ny_state: NYCloseState, epic: str) -> bool:
    if not NY_CLOSE_ENABLED:
        return False
    ny = _ny_now()
    if ny is None:
        return False

    hh, mm = _parse_hhmm(NY_CLOSE_HHMM)
    start = ny.replace(hour=hh, minute=mm, second=0, microsecond=0)
    end = start + timedelta(minutes=NY_CLOSE_WINDOW_MINUTES)
    if not (start <= ny < end):
        return False

    today_key = ny.date().isoformat()
    if ny_state.last_done_date_by_epic.get(epic) == today_key:
        return False

    ny_state.last_done_date_by_epic[epic] = today_key
    return True


def _get_imminent_high_news_event(minutes: int = 5):
    """Return the first HIGH-impact news event starting within *minutes*, or None."""
    now = datetime.now(timezone.utc)
    for ev in news_calendar.get_todays_events():
        try:
            t_str = ev.get("time", "")
            hh, mm = int(t_str.split(":")[0]), int(t_str.split(":")[1])
            ev_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            diff = (ev_dt - now).total_seconds()
            if 0 <= diff <= minutes * 60:
                return ev
        except Exception:
            continue
    return None


def _apply_software_break_even(epic: str, mid: float, bid: float = None, ask: float = None) -> None:
    """Move stop to breakeven once profit exceeds trigger threshold.

    Iterates all active positions for this epic and applies BE to each
    independently.
    """
    if not SOFTWARE_BE_ENABLED:
        return
    if not has_active_trade(epic):
        return

    from trade_executor import _state_for_epic, _pair_from_epic, _ppp_for_pair

    for _be_pk, _be_st in get_all_positions_for_epic(epic):
        try:
            _apply_be_for_position(_be_pk, _be_st, epic, mid, bid, ask)
        except Exception as exc:
            logger.warning("[%s] BE amend failed for %s: %s", epic, _be_pk, exc)


def _apply_be_for_position(pk, st, epic, mid, bid, ask):
    from trade_executor import _pair_from_epic, _ppp_for_pair

    entry = st.get("entry_price")
    direction = str(st.get("direction") or "").upper()
    deal_id = st.get("dealId") or st.get("deal_id")

    if entry is None or not direction or not deal_id:
        return
    if st.get("_be_applied"):
        return

    pair = _pair_from_epic(epic)
    ppp = _ppp_for_pair(pair)

    trigger_pts = SOFTWARE_BE_TRIGGER_PIPS * ppp

    live_spread_pts = 0.0
    if bid is not None and ask is not None:
        try:
            live_spread_pts = float(ask) - float(bid)
        except (TypeError, ValueError):
            live_spread_pts = 0.0
    offset_pts = max(SOFTWARE_BE_OFFSET_PIPS * ppp, live_spread_pts * 0.75)

    entry = float(entry)
    if direction == "BUY":
        profit_pts = mid - entry
        new_stop = entry + offset_pts
    elif direction == "SELL":
        profit_pts = entry - mid
        new_stop = entry - offset_pts
    else:
        return

    if profit_pts < trigger_pts:
        return

    # Mode exemption: skip BE-amend for modes in _SKIP_BE_AMEND_MODES or for
    # BRIEFING_EXECUTION when BRIEFING_EXEC_SOFTWARE_BE_AMEND_ENABLED=0 (the
    # default — BE rides to SL / TP / EOD without broker-side SL modification).
    # Log once per position (gated by _be_skip_logged) so first eligible
    # tick produces operator visibility, then stays silent.
    trade_mode = str(st.get("mode") or "").strip().upper()
    # Phase 3 collision guard 5.5: profile-managed trades own BE. The
    # profile-side scale-out (_scale_out_50pct) installs the broker BE
    # inside trade_manager under the same primitive; running software-BE
    # here would race the profile's BE amend on the tick immediately
    # after profile scale. Skip when profile_id ∈ _PROFILE_MANAGED.
    _profile_id_sbe = str(st.get("profile_id") or "").upper()
    _sbe_profile_managed = _profile_id_sbe in ("STRONG", "FORMING")
    _be_exempt = (
        trade_mode in _SKIP_BE_AMEND_MODES
        or (_is_briefing_exec_mode(trade_mode) and not _BE_SOFTWARE_BE_AMEND_ENABLED)
        or _sbe_profile_managed
    )
    if _be_exempt:
        if not st.get("_be_skip_logged"):
            profit_pips = round(profit_pts / ppp, 1)
            _reason = (
                "BRIEFING_EXEC_SOFTWARE_BE_AMEND_ENABLED=0"
                if _is_briefing_exec_mode(trade_mode) and trade_mode not in _SKIP_BE_AMEND_MODES
                else "_SKIP_BE_AMEND_MODES"
            )
            logger.info(
                "[%s] BE-amend skipped for mode=%s: profit=%.1fp >= trigger=%.1fp "
                "(%s — IG TP/SL preserved)",
                pair, trade_mode, profit_pips, SOFTWARE_BE_TRIGGER_PIPS, _reason,
            )
            st["_be_skip_logged"] = True
        return

    tp_pips = st.get("tp")
    if tp_pips is not None and float(tp_pips) > 0:
        if direction == "BUY":
            current_limit = round(entry + float(tp_pips) * ppp, 1)
        else:
            current_limit = round(entry - float(tp_pips) * ppp, 1)
    else:
        current_limit = None

    ig, _h, _a = get_ig_session()
    ig.update_open_position(
        limit_level=current_limit,
        stop_level=round(new_stop, 1),
        deal_id=deal_id,
    )
    st["_be_applied"] = True
    profit_pips = round(profit_pts / ppp, 1)
    offset_pips = round(offset_pts / ppp, 1)
    spread_pips = round(live_spread_pts / ppp, 1)
    logger.info(
        "[%s] BE amended: profit=%.1f pips (trigger=%.1f), "
        "stop moved to %.1f (entry %+.1f pips), limit preserved at %s "
        "[spread=%.1f, offset=%.1f (min=%.1f)]",
        pair, profit_pips, SOFTWARE_BE_TRIGGER_PIPS,
        new_stop, offset_pips,
        current_limit,
        spread_pips, offset_pips, SOFTWARE_BE_OFFSET_PIPS,
    )


# _apply_gbpusd_trend_trailing_stop removed 2026-05-23 — superseded by the
# centralised trend-style runner trail in trade_manager._apply_trend_runner_trail.
# The new trail engages for modes in _TREND_RUNNER_STYLE_MODES after scale-out
# has fired; one trail mechanism for the whole fleet, no per-strategy trailing.


# ============================================================
# FIFTY_PIP_BREAKOUT — time-based BE-hold at 22:00 UTC of fire day.
# Distinct from _apply_software_break_even (which is profit-triggered);
# V4's BE-hold transitions when wall-clock crosses 22:00 UTC regardless
# of position P&L. Called every tick from the per-pair handler.
# ============================================================
def _apply_fifty_pip_eod_be_hold(epic: str, ts: float) -> None:
    """Bridge fifty_pip_breakout.apply_eod_be_hold to the broker SL amend API."""
    try:
        from fifty_pip_breakout import apply_eod_be_hold as _fpb_eod
    except Exception:
        return

    def _get_open_position_for_mode(epic_arg: str, mode: str):
        from trade_executor import EPIC_STATE_LOCK as _LOCK
        pk = _pos_key(epic_arg, mode)
        with _LOCK:
            st = EPIC_STATE.get(pk)
            if not st or not st.get("active"):
                return None
            return {
                "deal_id": st.get("dealId") or st.get("deal_id"),
                "entry_price": st.get("entry_price"),
                "direction": st.get("direction"),
                "limit_price": st.get("limit_price"),
            }

    def _amend_stop(deal_id, new_stop_price, limit_price):
        try:
            ig, _h, _a = get_ig_session()
            kwargs = {"stop_level": round(float(new_stop_price), 1),
                      "deal_id": str(deal_id)}
            if limit_price is not None:
                kwargs["limit_level"] = round(float(limit_price), 1)
            ig.update_open_position(**kwargs)
            return True
        except Exception as exc:
            logger.warning("[FIFTY_PIP] amend_stop failed deal=%s: %s",
                           deal_id, exc)
            return False

    try:
        _fpb_eod(
            epic=epic, ts=float(ts),
            get_open_position_for_mode_fn=_get_open_position_for_mode,
            amend_stop_fn=_amend_stop,
        )
    except Exception as exc:
        logger.warning("[FIFTY_PIP] apply_eod_be_hold raised: %s", exc)


# ============================================================
# TimeframeContext integration (DATAFLOW MUST NOT DRIFT)
# ============================================================

_TF_CTX: Optional[TimeframeContext] = None
_TF_LAST_SNAPSHOT_BY_SYMBOL: Dict[str, Any] = {}

# Router (Step 3 wiring, 2026-05-30). Holds the per-symbol previous-bar
# structure classification so router.route()'s CHoCH lookback has the
# correct prior_structure. Populated/consumed only when the router hook
# block runs (ROUTER_DISPATCH_ENABLED=1); dormant otherwise.
_ROUTER_PRIOR_STRUCTURE_BY_SYMBOL: Dict[str, Optional[str]] = {}


def _router_dispatch_enabled() -> bool:
    """Shared gate for the router hook + the four structure-strategy
    self-dispatch sites. When True, the router drives those strategies and
    the legacy self-dispatch sites skip execute_trade."""
    return str(os.getenv("ROUTER_DISPATCH_ENABLED", "0")).strip().lower() in (
        "1", "true", "yes", "on"
    )

_journal: Optional[SweepJournal] = None
_diag_logger: Optional[DiagnosticsLogger] = None


def _init_timeframe_context_or_die() -> None:
    global _TF_CTX
    try:
        _TF_CTX = TimeframeContext()
    except Exception as e:
        logger.error(f"❌ TimeframeContext init failed (DATAFLOW MUST NOT DRIFT): {e}")
        raise


def _on_5m_close_tf(payload: Dict[str, Any]) -> None:
    global _TF_CTX, _TF_LAST_SNAPSHOT_BY_SYMBOL
    if _TF_CTX is None:
        raise RuntimeError("TimeframeContext is not initialized")

    try:
        sym = str(payload.get("symbol") or "").upper()
        epic = str(payload.get("epic") or "")
        if not sym or not epic:
            return

        snap = _TF_CTX.on_5m_close(sym, epic, payload)
        _TF_LAST_SNAPSHOT_BY_SYMBOL[sym] = snap

        # Persist HTF candles to disk on H1/D1 close
        if _htf_cache is not None:
            try:
                events = (snap.get("debug") or {}).get("event") or {}
                if events.get("h1_closed"):
                    _htf_cache.save_candles_to_cache(
                        sym, "H1", _TF_CTX.get_closed_candles(sym, "H1")
                    )
                if events.get("d1_closed"):
                    _htf_cache.save_candles_to_cache(
                        sym, "D1", _TF_CTX.get_closed_candles(sym, "D1")
                    )
            except Exception as _cache_e:
                logger.debug(f"[HTF-CACHE] {sym}: cache write error (non-fatal): {_cache_e}")
    except Exception as e:
        logger.error(f"❌ TimeframeContext.on_5m_close failed (DATAFLOW MUST NOT DRIFT): {e}", exc_info=True)
        raise


# ============================================================
# Candle-close logging callback (LOG + cache write + TFCTX)
# ============================================================

def _on_5m_close_log(payload: Dict[str, Any]) -> None:
    _on_5m_close_tf(payload)

    try:
        sym = payload.get("symbol")
        epic = payload.get("epic")
        c = payload.get("candle") or {}
        ts = c.get("timestamp")
        o = c.get("open")
        h = c.get("high")
        l = c.get("low")
        cl = c.get("close")

        df = None
        rows = None
        try:
            df = payload.get("candles_5m_closed_df")
            rows = int(len(df)) if df is not None else None
        except Exception:
            rows = None

        logger.info(f"[5M CLOSE] {sym} epic={epic} ts={ts} O={o} H={h} L={l} C={cl} closed_rows={rows}")

        # Candle-lag alerting: ts is bar-open time; bar closes ts+5min.
        try:
            from candle_lag_monitor import check_candle_lag
            check_candle_lag(sym, ts)
        except Exception:
            pass

        # NEWS_STRATEGY release-anchored evaluator (2026-07-25, ITEM 2).
        # Dormant when NEWS_STRATEGY_MODE=off (module returns None early);
        # in shadow: writes eval rows only, no execute_trade call;
        # in enforce: returns a Result the operator wires into the
        # executor (a follow-up commit adds that wiring — the evaluator
        # itself is safe under all three modes).
        try:
            import news_strategy_release_anchored as _ns_ra
            from datetime import datetime as _dt, timezone as _tz
            _bar_ts = ts
            if isinstance(_bar_ts, str):
                _bar_ts = _dt.fromisoformat(_bar_ts.replace("Z", "+00:00"))
            if _bar_ts is not None and o is not None and h is not None \
                    and l is not None and cl is not None:
                _ns_ra.on_bar_close(
                    pair=sym, epic=epic, bar_ts_utc=_bar_ts,
                    bar_open=float(o), bar_high=float(h),
                    bar_low=float(l), bar_close=float(cl),
                )
        except Exception:
            logger.debug("[NEWS-RA] on_bar_close dispatch failed",
                          exc_info=True)

        if sym and df is not None:
            _write_cache_from_close_payload(str(sym).upper(), df)

        # NEWS_MOMENTUM observation-only sweep (2026-07-26). Deferred
        # cache-reader — reads cache/{PAIR}_candles_rolling.csv only,
        # never touches any fire path, throttled to 15 min inside the
        # module. When NEWS_MOMENTUM_MODE=off this is a no-op returning 0.
        try:
            import news_momentum_observer as _ns_mom
            _ns_mom.sweep()
        except Exception:
            logger.debug("[NEWS-MOM] sweep dispatch failed", exc_info=True)

        if DFCHECK_ON_5M_CLOSE and sym and df is not None:
            try:
                import pandas as pd

                d = df.copy()
                if "timestamp" not in d.columns and "time" in d.columns:
                    d = d.rename(columns={"time": "timestamp"})
                if "timestamp" in d.columns:
                    d["timestamp"] = pd.to_datetime(d["timestamp"], errors="coerce", utc=True)
                    d = d.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
                cols = list(d.columns)
                logger.info(f"[DFCHECK] {sym} rows={len(d)} cols(n)={len(cols)} sample_cols={cols[:15]}")

                for col in ("EMA_50", "MACD_HIST_35_45_30", "BB_UPPER_20_2", "BB_LOWER_20_2"):
                    if col in d.columns:
                        nn = int(pd.to_numeric(d[col], errors="coerce").notna().sum())
                        last = d[col].iloc[-1]
                        logger.info(f"[DFCHECK] {sym} {col} non_nan={nn}/{len(d)} last={last}")
                    else:
                        logger.info(f"[DFCHECK] {sym} MISSING {col}")
            except Exception:
                pass

    except Exception:
        return


# ============================================================
# AutoBot Core
# ============================================================

class AutoBot:
    def __init__(self, epic_map: Dict[str, str]):
        self.epic_map = epic_map
        self.last_trade_ts_by_key: Dict[str, float] = _read_last_trade_times()

        self._last_positions_sync_ts: float = 0.0
        self._sync_miss_counts: Dict[str, int] = {}   # epic → consecutive confirmed-missing rounds
        self._open_position_counts: Dict[str, int] = {}  # epic → number of open deals on broker
        self._tick_last_seen_ts: Dict[str, float] = {}
        self._ny_state = NYCloseState(last_done_date_by_epic={})
        self._last_strategy_bucket: Dict[str, int] = {}
        self._last_entry_attempt_bucket_by_key: Dict[str, int] = {}
        self._last_seen_5m_bucket: Dict[str, int] = {}

        # Per-symbol tick-state cache, populated at top of _on_ls_tick.
        # Consumed by post-rebuild 5M close-callback dispatch sites that
        # need access to the most recent tick context (e.g. structure_break
        # dispatch under STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED, 2026-06-16).
        self._latest_tick_state: Dict[str, Dict[str, Any]] = {}

        self._bucket_open_state_by_key: Dict[str, Dict[str, float]] = {}

        self._strategy_mod = _load_strategy_module()
        self._evaluate_signals = getattr(self._strategy_mod, "evaluate_signals", None)
        if not callable(self._evaluate_signals):
            raise RuntimeError("strategy_logic.evaluate_signals is missing or not callable")

    def _log_strategy_once_per_bucket(self, symbol: str, ts_numeric: float, regime: Any, signal: Any, reason: str, mid: float) -> None:
        bucket = int(float(ts_numeric)) // 300
        last_bucket = self._last_strategy_bucket.get(symbol)
        if last_bucket == bucket:
            return
        self._last_strategy_bucket[symbol] = bucket
        logger.info(f"[STRATEGY] {symbol} regime={regime} signal={signal} mid={mid:.6f} reason={reason}")

    def _entry_attempt_allowed_this_bucket(self, symbol: str, epic: str, bucket: int) -> bool:
        if not ONE_ENTRY_PER_BUCKET:
            return True
        key = _cooldown_key(symbol, epic)
        last = self._last_entry_attempt_bucket_by_key.get(key)
        if last == bucket:
            return False
        # Do NOT consume the bucket here — only mark it after a successful trade
        return True

    def _mark_bucket_used(self, symbol: str, epic: str, bucket: int) -> None:
        key = _cooldown_key(symbol, epic)
        self._last_entry_attempt_bucket_by_key[key] = bucket

    def _get_last_trade_ts(self, symbol: str, epic: str) -> Optional[float]:
        key = _cooldown_key(symbol, epic)
        ts = self.last_trade_ts_by_key.get(key)
        if ts is not None:
            try:
                return float(ts)
            except Exception:
                return None
        return None

    def _set_last_trade_ts(self, symbol: str, epic: str, ts: float) -> None:
        key = _cooldown_key(symbol, epic)
        try:
            self.last_trade_ts_by_key[key] = float(ts)
        except Exception:
            self.last_trade_ts_by_key[key] = time.time()
        _save_last_trade_times(self.last_trade_ts_by_key)

    def _get_or_set_bucket_open(self, symbol: str, epic: str, ts: float, mid: float) -> Optional[float]:
        try:
            t = float(ts)
            if not (t and t > 0):
                t = time.time()
        except Exception:
            t = time.time()

        bucket = int(t) // 300
        key = _cooldown_key(symbol, epic)

        st = self._bucket_open_state_by_key.get(key)
        if not isinstance(st, dict):
            st = {}
            self._bucket_open_state_by_key[key] = st

        last_bucket = int(st.get("bucket", -1)) if "bucket" in st else -1
        if last_bucket != bucket:
            st["bucket"] = float(bucket)
            st["open_mid"] = float(mid)
            return float(mid)

        om = st.get("open_mid")
        try:
            if om is None:
                st["open_mid"] = float(mid)
                return float(mid)
            return float(om)
        except Exception:
            st["open_mid"] = float(mid)
            return float(mid)

    def run_positions_sync(self) -> None:
        """SYNC sweep: reconcile broker open positions with EPIC_STATE.

        Extracted (2026-05-08) from `_on_ls_tick` so it can run on its own
        cadence (rest_sweeps daemon thread) instead of piggybacking the LS
        thread. Body is unchanged from the inline version.
        """
        try:
            SYNC_MISS_THRESHOLD = 3  # require 3 consecutive confirmed misses (~45s at 15s gap)
            positions = get_open_positions()

            if positions is None:
                logger.warning("⚠️ Positions sync: API returned None (network/auth error); skipping this round.")
                return

            # Build set of IG deal_ids and epic counts
            ig_deal_ids = set()
            _epic_counts: Dict[str, int] = {}
            for p in positions:
                if not isinstance(p, dict):
                    continue
                market = p.get("market") or {}
                pos_d = p.get("position") or {}
                ep = market.get("epic")
                did = pos_d.get("dealId")
                if ep:
                    ep_str = str(ep)
                    _epic_counts[ep_str] = _epic_counts.get(ep_str, 0) + 1
                if did:
                    ig_deal_ids.add(str(did))
            self._open_position_counts = _epic_counts

            # Check each locally-tracked position against IG by deal_id
            checked_pks: set = set()
            for _sym, _ep in self.epic_map.items():
                ep_s = str(_ep)
                active_pos = get_all_positions_for_epic(ep_s)
                if not active_pos:
                    # Clean up stale miss counts for this epic
                    for k in list(self._sync_miss_counts.keys()):
                        if k.startswith(ep_s + "|"):
                            self._sync_miss_counts.pop(k, None)
                    continue
                for pk, _pos_st in active_pos:
                    checked_pks.add(pk)
                    did = str(_pos_st.get("dealId") or _pos_st.get("deal_id") or "")
                    if did and did in ig_deal_ids:
                        self._sync_miss_counts.pop(pk, None)
                    elif did:
                        misses = self._sync_miss_counts.get(pk, 0) + 1
                        self._sync_miss_counts[pk] = misses
                        if misses < SYNC_MISS_THRESHOLD:
                            logger.warning(
                                f"⚠️ {_ep} dealId={did} not in IG positions ({misses}/{SYNC_MISS_THRESHOLD} misses); waiting."
                            )
                        else:
                            logger.warning(f"🧹 IG has no position for {_ep} dealId={did} ({misses} checks); SYNC closing.")
                            try:
                                _sync_exit = _pos_st.get("last_mid") or _pos_st.get("exit_price")
                                close_position(pos_key=pk, reason="SYNC_NO_POSITION", exit_hint_price=_sync_exit)
                            except Exception as e:
                                logger.error(f"❌ SYNC close_position failed for {pk}: {e}", exc_info=True)
                            self._sync_miss_counts.pop(pk, None)

            # Global sweep: catch any active pos_key whose epic was not in
            # epic_map (or was missed above). Matches the user request to
            # scan *all* pos_key variants for a vanished dealId, so that an
            # orphaned signal_log entry still gets its close emitted.
            from trade_executor import (
                EPIC_STATE as _EPIC_STATE_ALL,
                EPIC_STATE_LOCK as _EPIC_STATE_LOCK_ALL,
            )
            # Snapshot under lock so a pair-worker's mid-tick write
            # cannot mutate EPIC_STATE during this iteration.
            with _EPIC_STATE_LOCK_ALL:
                _orphan_items = list(_EPIC_STATE_ALL.items())
            for pk, _pos_st in _orphan_items:
                if pk in checked_pks:
                    continue
                if not (_pos_st.get("active") or _pos_st.get("pending_open")):
                    continue
                did = str(_pos_st.get("dealId") or _pos_st.get("deal_id") or "")
                if not did:
                    continue
                if did in ig_deal_ids:
                    self._sync_miss_counts.pop(pk, None)
                    continue
                misses = self._sync_miss_counts.get(pk, 0) + 1
                self._sync_miss_counts[pk] = misses
                if misses < SYNC_MISS_THRESHOLD:
                    logger.warning(
                        f"⚠️ orphan pk={pk} dealId={did} not in IG positions "
                        f"({misses}/{SYNC_MISS_THRESHOLD} misses); waiting."
                    )
                else:
                    logger.warning(
                        f"🧹 IG has no position for orphan pk={pk} dealId={did} "
                        f"({misses} checks); SYNC closing."
                    )
                    try:
                        _sync_exit = _pos_st.get("last_mid") or _pos_st.get("exit_price")
                        close_position(pos_key=pk, reason="SYNC_NO_POSITION_ORPHAN", exit_hint_price=_sync_exit)
                    except Exception as e:
                        logger.error(f"❌ SYNC orphan close failed for {pk}: {e}", exc_info=True)
                    self._sync_miss_counts.pop(pk, None)
        except Exception:
            logger.warning("[POSITIONS-SYNC] sweep raised — see traceback", exc_info=True)

    def _on_ls_tick(self, symbol: str, epic: str, bid: float, ask: float, mid: float, ts: float, uts: Any, umicro: Any):
        self._tick_last_seen_ts[str(symbol).upper()] = time.time()
        # Module-level mirror for trade_executor's hybrid RACE_CAUGHT guard
        # (2026-05-28). Decoupled from this instance so the executor can
        # read tick-age without importing autobot. Heartbeat/watchdog
        # stores above retained as the authoritative instance state.
        # Lazy import to match the existing candle_lag_monitor usage style
        # in this file (no top-level import).
        try:
            import candle_lag_monitor as _clm_tick
            _clm_tick.record_tick(symbol)
        except Exception:
            pass
        # LSController watchdog stamp. The factory's wrapped callback in
        # streamer_ls.start_streaming originally did this, but under
        # LS_ASYNC_DISPATCH=1 the pair-worker dispatches ticks by calling
        # this method directly, bypassing that wrapper. Without this stamp
        # the watchdog reads a stale per-symbol last_tick and trips
        # spuriously every MAX_TICK_AGE_SECS on a healthy feed.
        try:
            _ls_ctrl = getattr(self, "ls_controller", None)
            if _ls_ctrl is not None:
                _ls_ctrl.record_tick(symbol)
        except Exception:
            pass

        bid_f = _safe_float(bid, None)
        ask_f = _safe_float(ask, None)
        mid_f = _safe_float(mid, None)

        if mid_f is None and bid_f is not None and ask_f is not None:
            mid_f = (bid_f + ask_f) / 2.0
        if bid_f is None or ask_f is None or mid_f is None:
            return

        sym_u = str(symbol).upper()
        epic_s = str(epic)

        # Snapshot the latest tick state per symbol so post-rebuild 5M close
        # callbacks (e.g. structure_break dispatch under
        # STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED) can reuse the most recent
        # epic+tick context without re-deriving from a building bar.
        self._latest_tick_state[sym_u] = {"epic": epic_s, "ts": float(ts)}

        try:
            candle_builder.set_symbol_epic(sym_u, epic_s)
        except Exception:
            pass

        # Candle aggregation was moved to native_5m_source (CHART:{epic}:5MINUTE
        # subscription wired in main()). Ticks here still drive NEWS_TICK
        # spike detection; candle_builder no longer receives tick updates.
        # See docs/data_integrity.md + branch migrate/native-5m-candle-feed.

        # Positions SYNC sweep — moved to rest_sweeps daemon thread when
        # LS_ASYNC_DISPATCH=1 (default). The inline path is preserved for
        # rollback (LS_ASYNC_DISPATCH=0). See run_positions_sync().
        if not _LS_ASYNC_DISPATCH:
            now = time.time()
            if now - self._last_positions_sync_ts >= POSITIONS_SYNC_MIN_GAP:
                self._last_positions_sync_ts = now
                self.run_positions_sync()

        had_open_position = bool(has_active_trade(epic_s))

        try:
            df = candle_builder.get_df(sym_u)
        except Exception:
            df = None

        upper_band, lower_band = _extract_bollinger_bands_from_df(df)
        macd_hist, prev_macd_hist = _extract_macd_hist_pair_from_df(df)

        try:
            _sweep_extreme = None
            try:
                _sweep_extreme = self._strategy_mod.get_last_sweep_extreme(sym_u, epic_s)
            except Exception:
                pass
            trade_manager.monitor_positions(
                epic_s,
                mid_f,
                bid=bid_f,
                ask=ask_f,
                upper_band=upper_band,
                lower_band=lower_band,
                macd_hist=macd_hist,
                prev_macd_hist=prev_macd_hist,
                sweep_extreme=_sweep_extreme,
                # df_5m is consumed only by the BB_REVERSAL TRENDING branch
                # in trade_manager._monitor_briefing_tp (extracts candle bodies +
                # recent highs/lows for check_momentum). Other monitor branches
                # ignore this kwarg, so no other strategy is affected.
                df_5m=df,
            )
        except TypeError:
            try:
                trade_manager.monitor_positions(epic_s, mid_f)
            except Exception:
                # 2026-06-17: was silent `pass` — surfaced as a 59-min
                # monitor stall on DIAAAAXR5CNSZA6 because tracebacks were
                # swallowed. Log + continue (same control flow).
                logger.exception(
                    "[MONITOR] monitor_positions (legacy 2-arg retry) raised "
                    "epic=%s mid=%s", epic_s, mid_f,
                )
        except Exception:
            logger.exception(
                "[MONITOR] monitor_positions raised epic=%s mid=%s",
                epic_s, mid_f,
            )

        has_open_position = bool(has_active_trade(epic_s))

        # Fix 3: If monitor_positions just closed a trade this tick, set cooldown and
        # skip strategy evaluation to prevent same-tick close+reopen.
        if had_open_position and not has_open_position:
            self._set_last_trade_ts(sym_u, epic_s, time.time())
            logger.info(f"[{sym_u}/{epic_s}] Trade closed by monitor this tick — cooldown set, skipping signal eval.")
            return

        # BRIEFING_EXECUTION EOD close (21:00 UTC by default) runs before
        # NY_CLOSE so BE positions exit under EOD_CLOSE reason rather than
        # NY_CLOSE. Self-gates per UTC day so repeat ticks are cheap.
        try:
            _apply_briefing_exec_eod_close(datetime.now(timezone.utc))
        except Exception as _eod_exc:
            logger.debug("[BRIEFING-EXEC] EOD helper error: %s", _eod_exc)

        # Phase 2 — NY plan evaluation at 12:30 UTC. Self-gates per
        # (pair, day) so repeat ticks are cheap; runs retroactively if
        # the bot was down at 12:30.
        try:
            _apply_briefing_exec_ny_evaluation(sym_u, datetime.now(timezone.utc))
        except Exception as _ny_eval_exc:
            logger.debug("[BRIEFING-EXEC] NY-EVAL helper error: %s", _ny_eval_exc)

        if has_open_position and _should_close_for_ny_end(self._ny_state, epic_s):
            # BRIEFING_EXECUTION skip: when BRIEFING_EXEC_SKIP_NY_CLOSE=1, BE
            # positions are excluded from NY_CLOSE and ride to SL / TP / EOD
            # only. Other modes still close here. Iterate per-position and
            # close only non-BE modes.
            _ny_closed_any = False
            for _ny_pk, _ny_st in get_all_positions_for_epic(epic_s):
                _ny_mode = str(_ny_st.get("mode") or "").upper()
                if _BE_SKIP_NY_CLOSE and _is_briefing_exec_mode(_ny_mode):
                    logger.info(
                        f"[{sym_u}/{epic_s}] [BRIEFING-EXEC] skipped NY_CLOSE for mode={_ny_mode} "
                        f"(env BRIEFING_EXEC_SKIP_NY_CLOSE=1; will be handled by EOD close)"
                    )
                    continue
                try:
                    close_position(pos_key=_ny_pk, reason="NY_CLOSE", exit_hint_price=mid_f)
                    _ny_closed_any = True
                except Exception as e:
                    logger.error(f"[{sym_u}/{epic_s}] ❌ NY close failed for {_ny_pk}: {e}", exc_info=True)
            if _ny_closed_any:
                logger.info(f"[{sym_u}/{epic_s}] 🕔 NY close window → closed non-BE positions.")
                return

        # Early 5M-boundary compute so monitoring block below can reference it
        # (proper value recomputed later near line 1960 for the strategy path).
        try:
            _bem_current_bucket = _bucket_5m(ts)
            _bem_prev_bucket = self._last_seen_5m_bucket.get(epic_s)
            _is_new_5m = (_bem_prev_bucket is None or _bem_prev_bucket != _bem_current_bucket)
        except Exception:
            _is_new_5m = False

        # -- BRIEFING_EXECUTION monitoring: invalidation + timed exit ----------
        if has_open_position:
            try:
                from briefing_execution import BRIEFING_EXECUTION_ENABLED as _BE_MON_ENABLED, BRIEFING_EXECUTION_MODE as _BE_MODE
                if _BE_MON_ENABLED and has_active_trade_for_mode(epic_s, _BE_MODE):
                    from strategy_logic import evaluate_signals as _es_ref
                    if hasattr(_es_ref, "_be_strat"):
                        _be_strat = _es_ref._be_strat
                        # Time-based forced exit (every tick)
                        if _be_strat.has_entered(sym_u) and _be_strat.should_time_exit(sym_u):
                            if not _BE_TIME_EXIT_ENABLED:
                                _be_pk_s = _pos_key(epic_s, _BE_MODE)
                                _be_st_s = EPIC_STATE.get(_be_pk_s) or {}
                                if not _be_st_s.get("_be_time_exit_skip_logged"):
                                    logger.info(
                                        f"[{sym_u}/{epic_s}] [BRIEFING-EXEC] skipped TIME_EXIT (env disabled)"
                                    )
                                    _be_st_s["_be_time_exit_skip_logged"] = True
                            else:
                                _be_pk = _pos_key(epic_s, _BE_MODE)
                                logger.info(f"[{sym_u}/{epic_s}] BRIEFING_EXEC TIME EXIT — force closing.")
                                try:
                                    close_position(pos_key=_be_pk, reason="BRIEFING_EXEC_TIME_EXIT", exit_hint_price=mid_f)
                                    send_telegram_message(
                                        f"⏰ <b>BRIEFING_EXEC time exit:</b> {sym_u} closed at scheduled exit time"
                                    )
                                except Exception as _be_te:
                                    logger.error(f"[{sym_u}/{epic_s}] BRIEFING_EXEC time exit failed: {_be_te}")
                                return
                        # Invalidation check (5M close only)
                        if _is_new_5m and _be_strat.has_entered(sym_u):
                            _be_candle_close = mid_f
                            if df is not None and len(df) > 0:
                                try:
                                    _be_candle_close = float(df.iloc[-1]["close"])
                                except Exception:
                                    pass
                            if _be_strat.should_invalidation_close(sym_u, _be_candle_close):
                                if not _BE_INVALIDATION_ENABLED:
                                    logger.info(
                                        f"[{sym_u}/{epic_s}] [BRIEFING-EXEC] skipped INVALIDATION "
                                        f"(env disabled, 5M close {_be_candle_close:.1f} beyond level)"
                                    )
                                else:
                                    _be_pk = _pos_key(epic_s, _BE_MODE)
                                    logger.info(f"[{sym_u}/{epic_s}] BRIEFING_EXEC INVALIDATION — force closing.")
                                    try:
                                        close_position(pos_key=_be_pk, reason="BRIEFING_EXEC_INVALIDATION", exit_hint_price=mid_f)
                                        send_telegram_message(
                                            f"🚫 <b>BRIEFING_EXEC invalidation:</b> {sym_u} closed — "
                                            f"5M candle closed beyond invalidation level"
                                        )
                                    except Exception as _be_ie:
                                        logger.error(f"[{sym_u}/{epic_s}] BRIEFING_EXEC invalidation close failed: {_be_ie}")
                                    return
            except ImportError:
                pass
            except Exception as _be_mon_exc:
                try:
                    from exception_monitor import record_exception
                    record_exception("BRIEFING-EXEC-MON", _be_mon_exc)
                except Exception:
                    pass
                logger.debug("[BRIEFING-EXEC-MON] error: %s", _be_mon_exc)

        # -- Pre-news position close: give the news strategy priority ----------
        # Gated by PRE_NEWS_CLOSE_ENABLED (2026-05-23, default OFF). When the
        # flag is False, the entire block — _get_imminent_high_news_event()
        # call, the per-position loop, the close_position(PRE_NEWS_CLOSE) call
        # — is skipped. Positions ride through news on their own broker SL/TP/
        # scale-out. The strategy-level _is_pre_news_blackout (entry-block)
        # is a separate, untouched mechanism.
        if PRE_NEWS_CLOSE_ENABLED and has_open_position:
            _imminent_ev = _get_imminent_high_news_event(minutes=5)
            if _imminent_ev is not None:
                _ev_name = _imminent_ev.get("event_name", "?")
                for _pn_pk, _pn_st in get_all_positions_for_epic(epic_s):
                    _dir = str(_pn_st.get("direction") or "").upper() or "?"
                    _entry_p = _pn_st.get("entry_price")
                    _pip_sz = _pn_st.get("pip_size") or 0.0001
                    _pnl = None
                    if _entry_p is not None:
                        try:
                            if _dir == "BUY":
                                _pnl = round((mid_f - float(_entry_p)) / _pip_sz, 1)
                            elif _dir == "SELL":
                                _pnl = round((float(_entry_p) - mid_f) / _pip_sz, 1)
                        except Exception:
                            pass

                    if _pnl is not None and _pnl >= NEWS_BLACKOUT_MIN_PROFIT_TO_KEEP_PIPS:
                        logger.info(
                            f"[{sym_u}/{epic_s}] ✅ Pre-news KEEP: {_dir} at {_pnl:+.1f} pips "
                            f"≥ {NEWS_BLACKOUT_MIN_PROFIT_TO_KEEP_PIPS} threshold — "
                            f"holding through '{_ev_name}'."
                        )
                    else:
                        logger.info(
                            f"[{sym_u}/{epic_s}] ⚠️ Pre-news close: HIGH event "
                            f"'{_ev_name}' imminent — closing position."
                        )
                        try:
                            close_position(pos_key=_pn_pk, reason="PRE_NEWS_CLOSE", exit_hint_price=mid_f)
                            _pnl_s = f"{_pnl:+.1f} pips" if _pnl is not None else "n/a"
                            send_telegram_message(
                                f"⚠️ <b>Pre-news close:</b> {sym_u} {_dir} closed before "
                                f"<b>{_ev_name}</b> release\n"
                                f"PnL: {_pnl_s} | Reason: PRE_NEWS_CLOSE"
                            )
                        except Exception as _pne:
                            logger.error(
                                f"[{sym_u}/{epic_s}] ❌ PRE_NEWS_CLOSE failed: {_pne}",
                                exc_info=True,
                            )
                return

        # Use system UTC clock for blackout — IG tick timestamps may be BST during summer
        _in_blackout, _blackout_reason = is_news_blackout(datetime.now(timezone.utc))

        # --- Tick-based news strategy: runs DURING blackout (exempt) ---
        # Always feed ticks so the state machine can arm/track even with
        # an open position.  Only execute the entry when no position exists.
        try:
            from pair_config import get_ppp
            _news_tick_ppp = get_ppp(sym_u)
            _news_tick_result = news_tick_strategy.tick_update(
                symbol=sym_u, mid=mid_f, bid=bid_f, ask=ask_f,
                ts=ts, ppp=_news_tick_ppp,
                is_blackout=_in_blackout, blackout_reason=_blackout_reason,
            )
            if _news_tick_result is not None and not has_open_position:
                try:
                    import candle_lag_monitor as _clm
                    if _clm.is_stale(sym_u):
                        _stale_lag_s = _clm.stale_lag(sym_u) or 0.0
                        logger.warning(
                            f"[{sym_u}/{epic_s}] ⛔ ENTRY BLOCKED — stale data "
                            f"({_stale_lag_s:.1f}s) on {sym_u} (NEWS_TICK)"
                        )
                        try:
                            send_telegram_message(
                                f"⛔ <b>Entry blocked — stale data</b>\n"
                                f"Pair: <code>{sym_u}</code>\n"
                                f"Lag: <b>{_stale_lag_s:.1f}s</b>\n"
                                f"Strategy: NEWS_TICK {_news_tick_result['signal']}"
                            )
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
                from strategy_logic import StrategyDecision
                # Pin regime classifier state at decision-construction
                # time so signal_log carries it with zero log-open
                # staleness. Cache populated by
                # strategy_logic._get_candle_regime each 5m close.
                _nt_debug = dict(_news_tick_result.get("debug", {}) or {})
                try:
                    from strategy_logic import get_latest_regime_state as _gls
                    _rs = _gls(sym_u)
                    if isinstance(_rs, dict):
                        _nt_debug["regime_state"] = _rs
                except Exception:
                    pass
                _nt_dec = StrategyDecision(
                    symbol=sym_u, regime="NEWS_TICK",
                    signal=_news_tick_result["signal"],
                    mode="NEWS_TICK",
                    entry=_news_tick_result["entry"],
                    sl=_news_tick_result["sl"],
                    tp=_news_tick_result["tp"],
                    use_trailing_stop=False,
                    reason=_news_tick_result["reason"],
                    debug=_nt_debug,
                )
                logger.info(
                    f"[{sym_u}/{epic_s}] ⚡ NEWS TICK ENTRY: "
                    f"{_news_tick_result['signal']} @ {_news_tick_result['entry']:.1f} "
                    f"SL={_news_tick_result['sl']:.1f} TP={_news_tick_result['tp']:.1f} "
                    f"reason={_news_tick_result['reason']}"
                )
                try:
                    _nt_trade_result = execute_trade(_nt_dec, epic_s)
                except Exception as _nt_exc:
                    logger.error(f"[{sym_u}/{epic_s}] ❌ News tick execute failed: {_nt_exc}")
                    _nt_trade_result = None
                if _journal is not None and has_active_trade(epic_s):
                    try:
                        _journal.log_signal(_nt_dec, taken=True, epic=epic_s)
                    except Exception:
                        pass
                # signal_log persistence — without this, NEWS_TICK trades
                # never reach signal_log.jsonl (the main-dispatch log_open at
                # autobot.py:3506 sits below the early `return` here).
                if isinstance(_nt_trade_result, dict) and has_active_trade_for_mode(epic_s, "NEWS_TICK"):
                    try:
                        _nt_pk = _pos_key(epic_s, "NEWS_TICK")
                        _nt_sl_id = str(uuid.uuid4())
                        _nt_briefing = morning_briefing.get_briefing(sym_u) or {}
                        _nt_entry = float(getattr(_nt_dec, "entry", None) or _news_tick_result["entry"])
                        _nt_entry, _nt_entry_source = _resolve_entry_price_and_source(_nt_pk, _nt_dec, _nt_entry)
                        _nt_deal_id = (
                            _nt_trade_result.get("dealId")
                            or _nt_trade_result.get("deal_id")
                            or (EPIC_STATE.get(_nt_pk) or {}).get("dealId")
                        )
                        signal_logger.log_open(
                            trade_id=_nt_sl_id,
                            epic=epic_s,
                            decision=_nt_dec,
                            briefing=_nt_briefing,
                            df_5m=df,
                            entry_price=_nt_entry,
                            deal_id=_nt_deal_id,
                            latency=(EPIC_STATE.get(_nt_pk) or {}).get("fire_latency"),
                            entry_price_source=_nt_entry_source,
                        )
                        _nt_st = EPIC_STATE.get(_nt_pk)
                        if _nt_st is not None:
                            _nt_st["signal_log_id"] = _nt_sl_id
                            _nt_st["decision_debug"] = dict(getattr(_nt_dec, "debug", None) or {})
                    except Exception as _nt_sl_exc:
                        logger.warning("[NEWS-TICK] signal_log.log_open failed: %s", _nt_sl_exc)

                    # Forensic fire snapshot — cross-pair coverage for the
                    # May 23 regime-coupling review. Strategy string is
                    # written as "NEWS_TICK" explicitly (not decision.mode)
                    # to keep the signal_log ⋈ forensic_fires JOIN key
                    # stable across pair-portable strategies.
                    try:
                        from forensic_logger import capture_fire_from_df as _nt_ff
                        _nt_pip = float(getattr(_nt_dec, "pip_size", None) or 1.0)
                        _nt_ff(
                            sym=sym_u,
                            strategy="NEWS_TICK",
                            direction=str(getattr(_nt_dec, "signal", "") or ""),
                            entry_price=_nt_entry,
                            df_5m=df,
                            pip_size=_nt_pip,
                            fire_path="news_tick_post_open",
                        )
                    except Exception as _nt_ff_exc:
                        logger.warning("[NEWS-TICK] forensic capture failed: %s", _nt_ff_exc)

                # Slippage-reject gate. Compare strategy-intended entry to
                # the actual IG fill (from EPIC_STATE.entry_price, populated
                # by execute_trade on ACCEPTED). If abs(slippage) exceeds
                # the threshold, close the position immediately. The
                # signal_log row was already written above, so the standard
                # close-callback chain will patch outcome=SLIPPAGE_REJECT
                # on it. Per 30-day analysis, the median slippage is 1.4p
                # and the threshold of 10p catches the two extreme outliers
                # (USDCAD 04-14 +20.65p and GBPJPY 04-14 -15.80p) without
                # rejecting moderate fills.
                if isinstance(_nt_trade_result, dict) and has_active_trade_for_mode(epic_s, "NEWS_TICK"):
                    try:
                        _nt_pk = _pos_key(epic_s, "NEWS_TICK")
                        _nt_st = EPIC_STATE.get(_nt_pk) or {}
                        _nt_actual = _nt_st.get("entry_price")
                        _nt_intended = getattr(_nt_dec, "entry", None)
                        _nt_max_slip = float(os.getenv("NEWS_TICK_MAX_SLIPPAGE_PIPS", "10"))
                        if (_nt_actual is not None and _nt_intended is not None
                                and _nt_max_slip > 0):
                            _nt_slip = abs(float(_nt_actual) - float(_nt_intended))
                            if _nt_slip > _nt_max_slip:
                                logger.warning(
                                    "[NEWS-TICK] %s slippage %.2fp exceeds max %.2fp — "
                                    "closing position. intended=%.5f actual=%.5f",
                                    sym_u, _nt_slip, _nt_max_slip,
                                    float(_nt_intended), float(_nt_actual),
                                )
                                try:
                                    close_position(
                                        pos_key=_nt_pk,
                                        reason="SLIPPAGE_REJECT",
                                        exit_hint_price=float(_nt_actual),
                                    )
                                except Exception as _nt_close_exc:
                                    logger.error(
                                        "[NEWS-TICK] slippage-reject close failed for %s: %s",
                                        _nt_pk, _nt_close_exc,
                                    )
                                try:
                                    send_telegram_message(
                                        f"🚫 <b>NEWS_TICK slippage reject</b>\n"
                                        f"Pair: <code>{sym_u}</code> "
                                        f"{_news_tick_result.get('signal','?')}\n"
                                        f"Intended: <code>{float(_nt_intended):.5f}</code>\n"
                                        f"Actual:   <code>{float(_nt_actual):.5f}</code>\n"
                                        f"Slippage: <b>{_nt_slip:.2f}p</b> (max {_nt_max_slip:.0f}p)"
                                    )
                                except Exception:
                                    pass
                    except Exception as _nt_slip_exc:
                        logger.warning("[NEWS-TICK] slippage check failed: %s", _nt_slip_exc)
                return
            elif _news_tick_result is not None and has_open_position:
                logger.info(
                    f"[{sym_u}/{epic_s}] ⚡ News tick signal {_news_tick_result['signal']} "
                    f"suppressed — position already open"
                )
        except Exception as _ntse:
            logger.debug(f"[{sym_u}] news_tick_strategy error: {_ntse}")

        # --- NEWS_STRATEGY: runs DURING blackout (exempt). -----------------
        # State machine always progresses (pre-arm at 30 min, spike
        # detection on candle close) so pre-event arming keeps working;
        # the strategy internally suppresses BUY/SELL emission unless
        # is_blackout=True.  Hoisted out of strategy_logic.evaluate_signals
        # because that dispatcher is reached via the main strategy path
        # at line ~2596, which sits downstream of the blackout `return`
        # at line ~2545 — the one strategy designed to trade during news
        # releases would otherwise be the only one silenced by them.
        try:
            from news_strategy import NEWS_STRATEGY_ENABLED as _NEWS_STRAT_ENABLED
            # Per-mode guard (was: not has_open_position). NEWS_TICK fires
            # tick-level on the same release and opens a position 1-2 bars
            # before NEWS_STRATEGY can evaluate the post-spike candles —
            # the global guard then silenced NEWS_STRATEGY for the entire
            # NEWS_TICK trade lifetime, costing 29 of 30 firings in the
            # 2026-04-29 30d audit. Switch to per-mode so only an existing
            # NEWS_STRATEGY-tagged position blocks re-entry; concurrent
            # NEWS_TICK trades are fine.
            # 2026-05-28: news_strategy now emits two leg-tagged modes
            # (NEWS_STRATEGY_FADE / NEWS_STRATEGY_CONT). Block on EITHER leg
            # being open on this pair. Legacy "NEWS_STRATEGY" key retained
            # for any in-flight pre-2026-05-28 state that might still exist.
            if _NEWS_STRAT_ENABLED and not (
                has_active_trade_for_mode(epic_s, "NEWS_STRATEGY_FADE")
                or has_active_trade_for_mode(epic_s, "NEWS_STRATEGY_CONT")
                or has_active_trade_for_mode(epic_s, "NEWS_STRATEGY")
            ):
                _ns_inst = _get_news_strategy_singleton()
                from pair_config import get_ppp as _ns_get_ppp
                _ns_pip = float(_ns_get_ppp(sym_u))
                # 2026-04-29 rebuild: NEWS_STRATEGY is now tick-level.
                # New signature mirrors news_tick_strategy.tick_update —
                # mid/bid/ask/ts/ppp instead of df/mid_price/pip_size.
                # Candle-shape evaluation is removed.
                _ns_decision = _ns_inst.evaluate(
                    symbol=sym_u,
                    epic=epic_s,
                    mid=mid_f,
                    bid=bid_f,
                    ask=ask_f,
                    ts=ts,
                    ppp=_ns_pip,
                    is_blackout=_in_blackout,
                    blackout_reason=_blackout_reason,
                )
                _ns_sig = str(getattr(_ns_decision, "signal", "") or "").upper()
                if _ns_sig in ("BUY", "SELL"):
                    # News release window — suppress NEWS_STRATEGY_FADE only;
                    # NEWS_STRATEGY_CONT (the +34.6p winning leg) bypasses.
                    # Block-entries-only; news_strategy's state machine has
                    # already logged WOULD_FIRE/FIRE upstream — we only skip
                    # execute_trade.
                    _ns_mode_for_window = str(
                        getattr(_ns_decision, "mode", "") or ""
                    ).upper()
                    if _ns_mode_for_window == "NEWS_STRATEGY_FADE":
                        try:
                            # Log-only staleness alert (ITEM 1c, 2026-07-25).
                            # Behaviour of the release-window gate is unchanged.
                            import news_calendar_health as _nch
                            _nch.warn_once_if_stale("news_strategy_release_window")
                        except Exception:
                            pass
                        try:
                            from news_release_window import is_in_release_window
                            _nrw_blocked, _nrw_reason = is_in_release_window(
                                datetime.now(timezone.utc)
                            )
                            if _nrw_blocked:
                                logger.info(
                                    "[NEWS_WINDOW_BLOCK] strategy=NEWS_STRATEGY_FADE "
                                    "%s %s reason=%s",
                                    sym_u, _ns_sig, _nrw_reason,
                                )
                                return
                        except Exception as _nrw_exc:
                            logger.debug(
                                f"[{sym_u}] news_release_window check error: {_nrw_exc}"
                            )
                    try:
                        import candle_lag_monitor as _clm
                        if _clm.is_stale(sym_u):
                            _stale_lag_s = _clm.stale_lag(sym_u) or 0.0
                            logger.warning(
                                f"[{sym_u}/{epic_s}] ⛔ ENTRY BLOCKED — stale data "
                                f"({_stale_lag_s:.1f}s) on {sym_u} (NEWS_STRATEGY)"
                            )
                            try:
                                send_telegram_message(
                                    f"⛔ <b>Entry blocked — stale data</b>\n"
                                    f"Pair: <code>{sym_u}</code>\n"
                                    f"Lag: <b>{_stale_lag_s:.1f}s</b>\n"
                                    f"Strategy: NEWS_STRATEGY {_ns_sig}"
                                )
                            except Exception:
                                pass
                            return
                    except Exception:
                        pass
                    logger.info(
                        f"[{sym_u}/{epic_s}] 📰 NEWS STRATEGY ENTRY: "
                        f"{_ns_sig} @ {float(mid_f):.1f} "
                        f"SL={getattr(_ns_decision, 'sl', None)} "
                        f"TP={getattr(_ns_decision, 'tp', None)} "
                        f"reason={getattr(_ns_decision, 'reason', None)}"
                    )
                    try:
                        _ns_trade_result = execute_trade(_ns_decision, epic_s)
                    except Exception as _ns_exc:
                        logger.error(
                            f"[{sym_u}/{epic_s}] ❌ News strategy execute failed: {_ns_exc}"
                        )
                        _ns_trade_result = None
                    if _journal is not None and has_active_trade(epic_s):
                        try:
                            _journal.log_signal(_ns_decision, taken=True, epic=epic_s)
                        except Exception:
                            pass
                    # signal_log persistence — without this, NEWS_STRATEGY
                    # trades never reach signal_log.jsonl (mirror of the
                    # NEWS_TICK fix above; same early-return constraint).
                    # 2026-05-28: mode is now leg-tagged (NEWS_STRATEGY_FADE /
                    # NEWS_STRATEGY_CONT) — read it from the decision so the
                    # EPIC_STATE key matches what trade_executor stored.
                    # Fallback to "NEWS_STRATEGY" preserves behaviour for any
                    # future code path emitting the legacy mode string.
                    _ns_mode = str(getattr(_ns_decision, "mode", "") or "NEWS_STRATEGY")
                    if isinstance(_ns_trade_result, dict) and has_active_trade_for_mode(epic_s, _ns_mode):
                        try:
                            _ns_pk = _pos_key(epic_s, _ns_mode)
                            _ns_sl_id = str(uuid.uuid4())
                            _ns_briefing = morning_briefing.get_briefing(sym_u) or {}
                            _ns_entry = float(getattr(_ns_decision, "entry", None) or mid_f)
                            _ns_entry, _ns_entry_source = _resolve_entry_price_and_source(_ns_pk, _ns_decision, _ns_entry)
                            _ns_deal_id = (
                                _ns_trade_result.get("dealId")
                                or _ns_trade_result.get("deal_id")
                                or (EPIC_STATE.get(_ns_pk) or {}).get("dealId")
                            )
                            signal_logger.log_open(
                                trade_id=_ns_sl_id,
                                epic=epic_s,
                                decision=_ns_decision,
                                briefing=_ns_briefing,
                                df_5m=df,
                                entry_price=_ns_entry,
                                deal_id=_ns_deal_id,
                                latency=(EPIC_STATE.get(_ns_pk) or {}).get("fire_latency"),
                                entry_price_source=_ns_entry_source,
                            )
                            _ns_st = EPIC_STATE.get(_ns_pk)
                            if _ns_st is not None:
                                _ns_st["signal_log_id"] = _ns_sl_id
                                _ns_st["decision_debug"] = dict(getattr(_ns_decision, "debug", None) or {})
                        except Exception as _ns_sl_exc:
                            logger.warning("[NEWS-STRATEGY] signal_log.log_open failed: %s", _ns_sl_exc)

                        # Forensic fire snapshot. Note the strategy override:
                        # decision.mode for this path is "NEWS" (per
                        # news_strategy.py:353), but signal_log records this
                        # strategy as "NEWS_STRATEGY" — we write the same
                        # name here to keep the JOIN key consistent.
                        try:
                            from forensic_logger import capture_fire_from_df as _ns_ff
                            _ns_pip = float(getattr(_ns_decision, "pip_size", None) or 1.0)
                            _ns_ff(
                                sym=sym_u,
                                strategy="NEWS_STRATEGY",
                                direction=str(getattr(_ns_decision, "signal", "") or ""),
                                entry_price=_ns_entry,
                                df_5m=df,
                                pip_size=_ns_pip,
                                fire_path="news_strategy_post_open",
                            )
                        except Exception as _ns_ff_exc:
                            logger.warning("[NEWS-STRATEGY] forensic capture failed: %s", _ns_ff_exc)
                    return
        except Exception as _nse:
            logger.debug(f"[{sym_u}] news_strategy error: {_nse}")

        # --- FIFTY_PIP_BREAKOUT: anchor-candle 50p strategy (Prompt-1 USDCAD V4) ---
        # Tick-driven entry. Strategy module owns the 08:00-anchor read,
        # virtual order monitoring, and 22:00-UTC BE-hold transition (the
        # latter via _apply_fifty_pip_eod_be_hold below). Universal blackouts
        # honoured via _in_blackout gate; CLOSE_ON_BLACKOUT path below
        # handles forced exit of an open V4 position during news windows.
        try:
            from fifty_pip_breakout import (
                tick_update as _fpb_tick,
                FIFTY_PIP_BREAKOUT_ENABLED as _FPB_ENABLED,
                ALLOWED_PAIRS as _FPB_PAIRS,
            )
            if _FPB_ENABLED and sym_u in _FPB_PAIRS:
                from pair_config import get_ppp as _fpb_get_ppp
                _fpb_result = _fpb_tick(
                    symbol=sym_u, epic=epic_s,
                    mid=mid_f, bid=bid_f, ask=ask_f,
                    ts=ts, ppp=float(_fpb_get_ppp(sym_u)),
                    df_5m=df,
                    has_open_for_mode_fn=lambda e, m: has_active_trade_for_mode(e, m),
                )
                if _fpb_result is not None and not _in_blackout:
                    _fpb_mode = str(_fpb_result["mode"])
                    if not has_active_trade_for_mode(epic_s, _fpb_mode):
                        try:
                            import candle_lag_monitor as _clm_fpb
                            if _clm_fpb.is_stale(sym_u):
                                _stale_lag_s = _clm_fpb.stale_lag(sym_u) or 0.0
                                logger.warning(
                                    f"[{sym_u}/{epic_s}] ⛔ ENTRY BLOCKED — stale data "
                                    f"({_stale_lag_s:.1f}s) on {sym_u} ({_fpb_mode})"
                                )
                                return
                        except Exception:
                            pass

                        from strategy_logic import StrategyDecision
                        _fpb_debug = dict(_fpb_result.get("debug", {}) or {})
                        try:
                            from strategy_logic import get_latest_regime_state as _gls
                            _rs = _gls(sym_u)
                            if isinstance(_rs, dict):
                                _fpb_debug["regime_state"] = _rs
                        except Exception:
                            pass
                        _fpb_dec = StrategyDecision(
                            symbol=sym_u, regime="FIFTY_PIP_BREAKOUT",
                            signal=_fpb_result["signal"],
                            mode=_fpb_mode,
                            entry=_fpb_result["entry"],
                            sl=_fpb_result["sl"],
                            tp=_fpb_result["tp"],
                            use_trailing_stop=False,
                            reason=_fpb_result["reason"],
                            debug=_fpb_debug,
                        )
                        logger.info(
                            f"[{sym_u}/{epic_s}] 🎯 FIFTY_PIP_BREAKOUT ENTRY: "
                            f"{_fpb_result['signal']} @ {_fpb_result['entry']:.2f} "
                            f"SL={_fpb_result['sl']:.1f}p TP={_fpb_result['tp']:.1f}p "
                            f"mode={_fpb_mode} reason={_fpb_result['reason']}"
                        )
                        try:
                            _fpb_trade_result = execute_trade(_fpb_dec, epic_s)
                        except Exception as _fpb_exc:
                            logger.error(
                                f"[{sym_u}/{epic_s}] ❌ Fifty-pip execute failed: {_fpb_exc}"
                            )
                            _fpb_trade_result = None
                        if _journal is not None and has_active_trade(epic_s):
                            try:
                                _journal.log_signal(_fpb_dec, taken=True, epic=epic_s)
                            except Exception:
                                pass
                        # signal_log persistence
                        if isinstance(_fpb_trade_result, dict) and has_active_trade_for_mode(epic_s, _fpb_mode):
                            try:
                                _fpb_pk = _pos_key(epic_s, _fpb_mode)
                                _fpb_sl_id = str(uuid.uuid4())
                                _fpb_briefing = morning_briefing.get_briefing(sym_u) or {}
                                _fpb_entry = float(
                                    getattr(_fpb_dec, "entry", None) or _fpb_result["entry"]
                                )
                                _fpb_entry, _fpb_entry_source = _resolve_entry_price_and_source(_fpb_pk, _fpb_dec, _fpb_entry)
                                _fpb_deal_id = (
                                    _fpb_trade_result.get("dealId")
                                    or _fpb_trade_result.get("deal_id")
                                    or (EPIC_STATE.get(_fpb_pk) or {}).get("dealId")
                                )
                                signal_logger.log_open(
                                    trade_id=_fpb_sl_id,
                                    epic=epic_s,
                                    decision=_fpb_dec,
                                    briefing=_fpb_briefing,
                                    df_5m=df,
                                    entry_price=_fpb_entry,
                                    deal_id=_fpb_deal_id,
                                    latency=(EPIC_STATE.get(_fpb_pk) or {}).get("fire_latency"),
                                    entry_price_source=_fpb_entry_source,
                                )
                                _fpb_st = EPIC_STATE.get(_fpb_pk)
                                if _fpb_st is not None:
                                    _fpb_st["signal_log_id"] = _fpb_sl_id
                                    _fpb_st["decision_debug"] = dict(getattr(_fpb_dec, "debug", None) or {})
                            except Exception as _fpb_sl_exc:
                                logger.warning(
                                    "[FIFTY_PIP] signal_log.log_open failed: %s",
                                    _fpb_sl_exc,
                                )
                            # Forensic fire snapshot for cross-strategy review.
                            try:
                                from forensic_logger import capture_fire_from_df as _fpb_ff
                                _fpb_pip = float(getattr(_fpb_dec, "pip_size", None) or 1.0)
                                _fpb_ff(
                                    sym=sym_u,
                                    strategy=_fpb_mode,
                                    direction=str(getattr(_fpb_dec, "signal", "") or ""),
                                    entry_price=_fpb_entry,
                                    df_5m=df,
                                    pip_size=_fpb_pip,
                                    fire_path="fifty_pip_post_open",
                                )
                            except Exception as _fpb_ff_exc:
                                logger.warning(
                                    "[FIFTY_PIP] forensic capture failed: %s",
                                    _fpb_ff_exc,
                                )
                        return
                elif _fpb_result is not None and _in_blackout:
                    logger.info(
                        f"[{sym_u}/{epic_s}] 🎯 FIFTY_PIP fire suppressed "
                        f"(news blackout: {_blackout_reason})"
                    )
        except Exception as _fpb_exc:
            logger.debug(f"[{sym_u}] fifty_pip_breakout error: {_fpb_exc}")

        # News blackout — fresh-entry gate stripped 2026-04-30 per
        # dispatcher-decoupling. Close path retained: when CLOSE_ON_BLACKOUT
        # is set, an open position is force-closed at the start of a
        # blackout window (preserves the manage-existing-positions logic).
        # Strategies are responsible for their own event-awareness on entry.
        if _in_blackout and CLOSE_ON_BLACKOUT and has_open_position:
            logger.info(
                f"[{sym_u}/{epic_s}] 📰 News blackout: {_blackout_reason}"
                f" — closing open position (CLOSE_ON_BLACKOUT)."
            )
            try:
                close_all_positions_for_epic(epic=epic_s, reason="NEWS_BLACKOUT_CLOSE", exit_hint_price=mid_f)
            except Exception as _boe:
                logger.error(
                    f"[{sym_u}/{epic_s}] ❌ NEWS_BLACKOUT_CLOSE failed: {_boe}",
                    exc_info=True,
                )
            return

        if has_open_position:
            try:
                # Software BE-amend: move stop to entry+offset once profit ≥
                # SOFTWARE_BE_TRIGGER_PIPS. Iterates per-position via
                # _apply_be_for_position; modes in _SKIP_BE_AMEND_MODES are
                # exempt (BB_REVERSAL: TP1 is 15-20p, +12p BE-amend caps
                # winners at +1p and strips the edge; GBPUSD_TREND_*: owns
                # its own 2-step software trail).
                _apply_software_break_even(epic_s, mid_f, bid=bid_f, ask=ask_f)
            except Exception:
                pass
            # GBPUSD_TREND per-tick trail call removed 2026-05-23 — the
            # centralised trend-style trail in trade_manager runs from the
            # 5m _monitor_profit_protection cadence and uses broker SL
            # amends keyed on the peak MFE tracked in meta["best_pnl_pips"].
            # FIFTY_PIP V4 time-based BE-hold: at 22:00 UTC of the fire
            # day, regardless of P&L, move SL → entry for any open V4
            # position on this epic. Idempotent per (mode, position).
            try:
                _apply_fifty_pip_eod_be_hold(epic_s, ts)
            except Exception:
                pass

        current_bucket_open = self._get_or_set_bucket_open(sym_u, epic_s, ts, mid_f)

        htf_snapshot = _TF_LAST_SNAPSHOT_BY_SYMBOL.get(sym_u)

        # Detect 5M boundary change — sweep strategies only run on new 5M closes
        _current_bucket = _bucket_5m(ts)
        _prev_bucket = self._last_seen_5m_bucket.get(epic_s)
        _is_new_5m = (_prev_bucket is None or _prev_bucket != _current_bucket)
        if _is_new_5m:
            self._last_seen_5m_bucket[epic_s] = _current_bucket

            # Phase 4 — staleness handling. On every closed 5m bar, ask
            # the briefing-execution strategy whether to drop the active
            # plan because expires_at has passed or because this bar's
            # close is beyond the plan's invalidation level. Wicks are
            # ignored. Already-entered plans are skipped inside the
            # method.
            #
            # Multi-timeframe fanout: a 5m close at :00 is also an H1 close
            # (and trivially a 15m close); at :15/:30/:45 it's also a 15m
            # close. The 5m bar's close PRICE equals the H1/15m close at
            # those boundaries (it's the last tick of the higher-tf bar),
            # so we reuse it. The evaluator silently no-ops when the plan's
            # invalidation_timeframe doesn't match the dispatched timeframe.
            #   _current_bucket % 12 == 0  →  hh:00 (H1 boundary)
            #   _current_bucket %  3 == 0  →  :15/:30/:45/:00 (15m boundary)
            if df is not None and len(df) > 0:
                try:
                    from strategy_logic import evaluate_signals as _es_ref_p4
                    _be_strat_p4 = getattr(_es_ref_p4, "_be_strat", None)
                    if _be_strat_p4 is not None:
                        _bar_close = float(df["close"].iloc[-1])
                        _now_utc = datetime.now(timezone.utc)
                        _pip_size = _BE_PIP_SIZE_FOR_SUMMARY.get(sym_u, 1.0)
                        _tfs: List[str] = ["5m"]
                        if _current_bucket % 3 == 0:
                            _tfs.append("15m")
                        if _current_bucket % 12 == 0:
                            _tfs.append("h1")
                        for _tf in _tfs:
                            _be_strat_p4.on_bar_close(
                                symbol=sym_u,
                                bar_close=_bar_close,
                                timeframe=_tf,
                                now_utc=_now_utc,
                                pip_size=_pip_size,
                            )
                except Exception as _phase4_exc:
                    logger.error(
                        "[BRIEFING-EXEC] on_bar_close failed: %s",
                        _phase4_exc, exc_info=True,
                    )

        extra = {
            "update_time": uts,
            "update_micro": umicro,
            "ts": ts,
            "current_bucket_open": current_bucket_open,
            "is_new_5m_close": _is_new_5m,
        }

        try:
            decision = _call_strategy_compat(
                self._evaluate_signals,
                symbol=sym_u,
                epic=epic_s,
                bid=bid_f,
                ask=ask_f,
                mid=mid_f,
                df=df,
                has_open_position=has_open_position,
                htf_snapshot=htf_snapshot,
                extra_kwargs=extra,
            )
        except Exception as e:
            logger.error(f"[{sym_u}] ❌ Strategy error: {e}", exc_info=True)
            return

        # --- Diagnostic snapshot (read-only tap, non-blocking) ---
        if _diag_logger is not None:
            try:
                _diag_logger.maybe_log(sym_u, mid_f, df, htf_snapshot, decision)
            except Exception:
                pass

        # ─── GBPUSD dual BB-reversal strategies (2026-04-25) ─────────────
        # Two independent strategies on GBPUSD — REV_L (high-frequency
        # lower-band pierce-and-reverse) and BIG_REV (low-frequency
        # extended pierce + strong reversal). Both fire on new 5m closes
        # only. Each owns its own mode tag and its own internal day cap.
        # Per-mode pyramiding is enforced by has_active_trade_for_mode in
        # the existing dispatch path; we call execute_trade directly for
        # these strategies the same way NEWS_TICK / NEWS_STRATEGY do.
        if sym_u == "GBPUSD" and _is_new_5m and df is not None and len(df) >= 21:
            try:
                from gbpusd_bb_reversal_long import strategy as _bb_rev_l_strat, ENABLED as _BB_REV_L_ENABLED
                from gbpusd_bb_reversal_long import bb_20_2 as _bb_calc, Bar as _RBar
                from gbpusd_big_rev import strategy as _big_rev_strat, ENABLED as _BIG_REV_ENABLED, Bar as _BBar
                # Tick `ts` is an epoch float in this handler. Both
                # strategies expect a tz-aware datetime — convert.
                _ts_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                _closes_n = [float(c) for c in df["close"].tolist()]
                if len(_closes_n) >= 20:
                    _bbl_n, _bbm_n, _bbu_n = _bb_calc(_closes_n)
                    _last_n = min(6, len(df))
                    # candle_builder.get_df uses "time" as the column name
                    # for the bar timestamp; fall back to "timestamp" if a
                    # caller ever swaps source.
                    _ts_col = "time" if "time" in df.columns else "timestamp"
                    def _row_ts(_r):
                        v = _r[_ts_col]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    _recent = [
                        _RBar(
                            timestamp=_row_ts(df.iloc[-_last_n + j]),
                            open=float(df.iloc[-_last_n + j]["open"]),
                            high=float(df.iloc[-_last_n + j]["high"]),
                            low=float(df.iloc[-_last_n + j]["low"]),
                            close=float(df.iloc[-_last_n + j]["close"]),
                        )
                        for j in range(_last_n)
                    ]

                    # REV_L (bidirectional 2026-04-28: LONG + SHORT)
                    # Router self-dispatch gate (Step 4, 2026-05-30): when
                    # ROUTER_DISPATCH_ENABLED=1 the router's RANGE chain is
                    # the sole BB_REV_L dispatch path. The strategy mutates
                    # `_trades_today` on each fire (gbpusd_bb_reversal_long.py:677);
                    # leaving this evaluate running would double-count fires
                    # against the per-day cap. Note: the surrounding wrapper
                    # also hosts BIG_REV — that one stays independent (not
                    # under the router), so we gate the inner if rather than
                    # the outer wrapper.
                    if _BB_REV_L_ENABLED and not _router_dispatch_enabled():
                        try:
                            _rev_l_dec = _bb_rev_l_strat.evaluate(
                                symbol=sym_u, epic=epic_s,
                                mid_price=mid_f, pip_size=1.0,
                                ts=_ts_dt, bars=_recent,
                                bb_upper=_bbu_n, bb_lower=_bbl_n, bb_mid=_bbm_n,
                                has_open_long=has_active_trade_for_mode(epic_s, "GBPUSD_BB_REV_L"),
                                has_open_short=has_active_trade_for_mode(epic_s, "GBPUSD_BB_REV_L_S"),
                            )
                        except Exception as _re:
                            logger.error("[BB_REV_L] evaluate failed: %s", _re, exc_info=True)
                            _rev_l_dec = None
                        if _rev_l_dec is not None:
                            execute_trade(_rev_l_dec, epic_s)

                    # BIG_REV — needs BB at bar N-1 close as well
                    if _BIG_REV_ENABLED and len(_closes_n) >= 21:
                        _closes_nm1 = _closes_n[:-1]
                        _bbl_nm1, _bbm_nm1, _bbu_nm1 = _bb_calc(_closes_nm1)
                        _big_recent = [
                            _BBar(
                                timestamp=b.timestamp,
                                open=b.open, high=b.high, low=b.low, close=b.close,
                            )
                            for b in _recent
                        ]
                        try:
                            _big_dec = _big_rev_strat.evaluate(
                                symbol=sym_u, epic=epic_s, ts=_ts_dt, bars=_big_recent,
                                bb_upper_n=_bbu_n, bb_lower_n=_bbl_n, bb_mid_n=_bbm_n,
                                bb_upper_nm1=_bbu_nm1, bb_lower_nm1=_bbl_nm1,
                                pip_size=1.0,
                                has_open_position=has_active_trade_for_mode(epic_s, "GBPUSD_BIG_REV"),
                            )
                        except Exception as _bre:
                            logger.error("[BIG_REV] evaluate failed: %s", _bre, exc_info=True)
                            _big_dec = None
                        if _big_dec is not None:
                            execute_trade(_big_dec, epic_s)
            except Exception as _dual_e:
                logger.error("[BB_REV_L/BIG_REV] dispatch wrapper failed: %s", _dual_e, exc_info=True)

        # ─── GBPUSD_TREND (cascade-driven, 2026-05-13) ────────────────────
        # Replaces GBPUSD_TREND_CONTINUATION and the 3CO H1-stack gate
        # (both deleted 2026-05-13). 2026-05-23 rewire: now keys off H1
        # EMA-stack vote (indicators.h1_ema_direction) for context +
        # 9-gate proven entry (5 trend_detection.is_clean_trend H1 gates
        # + H1 freshness + 5m 2-bar continuation + 5m momentum-close +
        # per-H1-bucket dedup). SL = 20p, broker TP = 80p, 3-step trail
        # via trade_manager._apply_trend_runner_trail (centralised, only
        # engages after +10p scale-out for modes in _TREND_RUNNER_STYLE_MODES).
        # BRIEFING_INVALIDATED-exempt.
        #
        # Direct-dispatch wrapper (mirrors BB_BOUNCE pattern). The
        # strategy is intentionally exempted from this gate:
        #   - cross-mode pair concurrency   (_PAIR_CONCURRENCY_BYPASS_MODES)
        #
        # Composes two flags (Step 3 wiring, 2026-05-30):
        #   * ROUTER_DISPATCH_ENABLED=1 → entire wrapper SKIPPED (router hook
        #     below is the sole evaluate path; same shape as BB_BOUNCE/
        #     EMA_PULLBACK wrappers). The strategy's per-H1-bucket dedup at
        #     gbpusd_trend.py:387 means a same-bar second evaluate returns
        #     None, so leaving the legacy evaluate running would silence the
        #     router for GBPUSD_TREND.
        #   * GBPUSD_TREND_SELF_DISPATCH (inside the wrapper) — only consulted
        #     when router is OFF; preserves the existing dormancy mechanism.
        # Truth table for execute_trade firing (when GT_ENABLED + setup):
        #   ROUTER=0, SELF_DISPATCH=1  → wrapper runs, execute_trade fires    (legacy on)
        #   ROUTER=0, SELF_DISPATCH=0  → wrapper runs, execute_trade SKIPPED  (legacy dormant)
        #   ROUTER=1, SELF_DISPATCH=*  → wrapper skipped; router drives       (router on)
        #
        # Strategy retired 2026-06-18: redundant with EMA_PULLBACK, broken
        # wire (every fire died at the distance guard), net-negative on
        # replay. GBPUSD_TREND_ENABLED defaults OFF — the wrapper short-
        # circuits before importing gbpusd_trend so nothing evaluates and
        # no log noise. Flip GBPUSD_TREND_ENABLED=1 to revert call-time
        # (no restart). Strategy module + tests intentionally kept; this
        # is a flag-gated retire, not a rip-out.
        if (
            sym_u == "GBPUSD"
            and _is_new_5m
            and df is not None
            and len(df) >= 21
            and not _router_dispatch_enabled()
            and os.getenv("GBPUSD_TREND_ENABLED", "0").strip().lower() in ("1", "true", "yes")
        ):
            try:
                from gbpusd_trend import (
                    strategy as _gt_strat,
                    ENABLED as _GT_ENABLED,
                    MODE_NAME_LONG as _GT_MODE_L,
                    MODE_NAME_SHORT as _GT_MODE_S,
                    Bar as _GTBar,
                )
                if _GT_ENABLED:
                    # ── GBPUSD_TREND self-dispatch gate (Stage 2, 2026-05-22) ──
                    # GBPUSD_TREND_SELF_DISPATCH=0 evaluates but does NOT call
                    # execute_trade — strategy goes dormant. Default "1"
                    # preserves legacy self-dispatch; flip the env var to revert.
                    # Only consulted when ROUTER_DISPATCH_ENABLED=0 (see outer if).
                    _GT_SELF_DISPATCH = os.getenv(
                        "GBPUSD_TREND_SELF_DISPATCH", "1"
                    ).strip().lower() in ("1", "true", "yes")
                    _ts_col_gt = "time" if "time" in df.columns else "timestamp"

                    def _row_ts_gt(_r):
                        v = _r[_ts_col_gt]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    _last_gt = min(60, len(df))
                    _gt_bars = [
                        _GTBar(
                            timestamp=_row_ts_gt(df.iloc[-_last_gt + j]),
                            open=float(df.iloc[-_last_gt + j]["open"]),
                            high=float(df.iloc[-_last_gt + j]["high"]),
                            low=float(df.iloc[-_last_gt + j]["low"]),
                            close=float(df.iloc[-_last_gt + j]["close"]),
                        )
                        for j in range(_last_gt)
                    ]
                    _has_pos_gt = bool(
                        has_active_trade_for_mode(epic_s, _GT_MODE_L)
                        or has_active_trade_for_mode(epic_s, _GT_MODE_S)
                    )
                    try:
                        _gt_dec = _gt_strat.evaluate_5m_close(
                            pair=sym_u, bars=_gt_bars,
                            has_active_position=_has_pos_gt,
                        )
                    except Exception as _gte:
                        logger.error("[TREND] evaluate failed: %s", _gte, exc_info=True)
                        _gt_dec = None
                    if _gt_dec is not None and not _GT_SELF_DISPATCH:
                        logger.info(
                            "[TREND] %s self-dispatch gated off "
                            "(GBPUSD_TREND_SELF_DISPATCH=0) — decision "
                            "evaluated, execute_trade SKIPPED", sym_u,
                        )
                    elif _gt_dec is not None:
                        _gt_trade_result = execute_trade(_gt_dec, epic_s)
                        # signal_log persistence + mark_position_opened
                        # so the strategy state machine knows the trade
                        # is live (drives the cascade-flip exit path).
                        if isinstance(_gt_trade_result, dict) and (
                            has_active_trade_for_mode(epic_s, _GT_MODE_L)
                            or has_active_trade_for_mode(epic_s, _GT_MODE_S)
                        ):
                            # Forensic fire snapshot — self-capture, mirrors the
                            # NEWS_TICK pattern at :2640 and gbpusd_bb_bounce's
                            # own self-capture. Telemetry-only; the trade is
                            # already filled, so any failure here logs WARNING
                            # and continues. Strategy string comes from
                            # decision.mode (GBPUSD_TREND_L/_S) so the JOIN key
                            # matches the allowlist at :4015 and signal_log.
                            try:
                                from forensic_logger import capture_fire_from_df as _gt_ff
                                _gt_ff(
                                    sym=sym_u,
                                    strategy=str(getattr(_gt_dec, "mode", "") or ""),
                                    direction=str(getattr(_gt_dec, "signal", "") or ""),
                                    entry_price=float(getattr(_gt_dec, "entry", None) or 0.0),
                                    df_5m=df,
                                    pip_size=float(getattr(_gt_dec, "pip_size", None) or 1.0),
                                    fire_path="gbpusd_trend_post_open",
                                )
                            except Exception as _gt_ff_exc:
                                logger.warning("[TREND] forensic capture failed: %s", _gt_ff_exc)
                            try:
                                _gt_mode = (_GT_MODE_L
                                            if str(getattr(_gt_dec, "signal", "")).upper() == "BUY"
                                            else _GT_MODE_S)
                                _gt_pk = _pos_key(epic_s, _gt_mode)
                                _gt_sl_id = str(uuid.uuid4())
                                _gt_briefing = morning_briefing.get_briefing(sym_u) or {}
                                _gt_entry = float(getattr(_gt_dec, "entry", None) or 0.0)
                                _gt_entry, _gt_entry_source = _resolve_entry_price_and_source(_gt_pk, _gt_dec, _gt_entry)
                                _gt_deal_id = (
                                    _gt_trade_result.get("dealId")
                                    or _gt_trade_result.get("deal_id")
                                    or (EPIC_STATE.get(_gt_pk) or {}).get("dealId")
                                )
                                signal_logger.log_open(
                                    trade_id=_gt_sl_id,
                                    epic=epic_s,
                                    decision=_gt_dec,
                                    briefing=_gt_briefing,
                                    df_5m=df,
                                    entry_price=_gt_entry,
                                    deal_id=_gt_deal_id,
                                    latency=(EPIC_STATE.get(_gt_pk) or {}).get("fire_latency"),
                                    entry_price_source=_gt_entry_source,
                                )
                                _gt_st = EPIC_STATE.get(_gt_pk)
                                if _gt_st is not None:
                                    _gt_st["signal_log_id"] = _gt_sl_id
                                    _gt_st["decision_debug"] = dict(getattr(_gt_dec, "debug", None) or {})
                            except Exception as _gt_sl_exc:
                                logger.warning(
                                    "[TREND] signal_log.log_open failed: %s",
                                    _gt_sl_exc,
                                )
                            # Tell the strategy state machine the trade
                            # is now open — drives the cascade-flip exit
                            # path on subsequent 5m closes.
                            try:
                                _gt_signal = str(getattr(_gt_dec, "signal", "")).upper()
                                _gt_strat.mark_position_opened(
                                    pair=sym_u,
                                    direction=_gt_signal,
                                    entry_price=float(getattr(_gt_dec, "entry", 0.0) or 0.0),
                                )
                            except Exception as _gt_mark_exc:
                                logger.warning(
                                    "[TREND] mark_position_opened failed: %s",
                                    _gt_mark_exc,
                                )
            except Exception as _gt_outer:
                logger.error("[TREND] dispatch wrapper failed: %s", _gt_outer, exc_info=True)

        # ─── GBPUSD_OVERNIGHT_LEVEL_SWEEP (2026-04-28: bidirectional) ─────
        # London-open sweep + reversal of any significant overnight swing
        # low (LONG) or high (SHORT). Reads its overnight session from
        # data/candles/GBPUSD/<date>.csv via candle_archive's 5m-close
        # callback. LONG and SHORT fire independently; each side caps at
        # one trade per day.
        if sym_u == "GBPUSD" and _is_new_5m and df is not None and len(df) >= 6:
            try:
                from gbpusd_overnight_level_sweep import (
                    strategy as _ov_strat,
                    ENABLED as _OV_ENABLED,
                    Bar as _OBar,
                )
                if _OV_ENABLED:
                    _ts_dt_ov = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _ts_col_ov = "time" if "time" in df.columns else "timestamp"
                    _last_ov = min(6, len(df))
                    def _row_ts_ov(_r):
                        v = _r[_ts_col_ov]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    _ov_bars = [
                        _OBar(
                            timestamp=_row_ts_ov(df.iloc[-_last_ov + j]),
                            open=float(df.iloc[-_last_ov + j]["open"]),
                            high=float(df.iloc[-_last_ov + j]["high"]),
                            low=float(df.iloc[-_last_ov + j]["low"]),
                            close=float(df.iloc[-_last_ov + j]["close"]),
                        )
                        for j in range(_last_ov)
                    ]
                    try:
                        _ov_dec = _ov_strat.evaluate(
                            symbol=sym_u, epic=epic_s,
                            ts=_ts_dt_ov, bars=_ov_bars,
                            pip_size=1.0,
                            has_open_long=has_active_trade_for_mode(
                                epic_s, "GBPUSD_OVERNIGHT_LEVEL_SWEEP"
                            ),
                            has_open_short=has_active_trade_for_mode(
                                epic_s, "GBPUSD_OVERNIGHT_LEVEL_SWEEP_S"
                            ),
                        )
                    except Exception as _ove:
                        logger.error("[OVERNIGHT_SWEEP] evaluate failed: %s", _ove, exc_info=True)
                        _ov_dec = None
                    if _ov_dec is not None:
                        execute_trade(_ov_dec, epic_s)
            except Exception as _ov_disp:
                logger.error("[OVERNIGHT_SWEEP] dispatch wrapper failed: %s", _ov_disp, exc_info=True)

        # ─── GBPUSD_BB_PREMIRROR_L (2026-04-25) ───────────────────────────
        # Pattern B (pre-pierce mirror) at the lower BB. Mean-reversion
        # grinder, LONG-only. The detector needs BB(20,2) at bar N's
        # close (closes[:-1]) and BB(20,2) at bar N+1's close (closes).
        if sym_u == "GBPUSD" and _is_new_5m and df is not None and len(df) >= 21:
            try:
                from gbpusd_bb_premirror_long import (
                    strategy as _pm_strat,
                    ENABLED as _PM_ENABLED,
                    Bar as _PMBar,
                )
                from gbpusd_bb_reversal_long import bb_20_2 as _bb_calc_pm
                if _PM_ENABLED:
                    _ts_dt_pm = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _closes_pm = [float(c) for c in df["close"].tolist()]
                    if len(_closes_pm) >= 21:
                        # BB(20,2) computed at bar N close (closes[:-1]) and bar N+1 close (closes).
                        _bbl_n,    _, _bbu_n    = _bb_calc_pm(_closes_pm[:-1])
                        _bbl_np1,  _, _bbu_np1  = _bb_calc_pm(_closes_pm)
                        _ts_col_pm = "time" if "time" in df.columns else "timestamp"
                        def _row_ts_pm(_r):
                            v = _r[_ts_col_pm]
                            return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                        _last_pm = min(6, len(df))
                        _pm_bars = [
                            _PMBar(
                                timestamp=_row_ts_pm(df.iloc[-_last_pm + j]),
                                open=float(df.iloc[-_last_pm + j]["open"]),
                                high=float(df.iloc[-_last_pm + j]["high"]),
                                low=float(df.iloc[-_last_pm + j]["low"]),
                                close=float(df.iloc[-_last_pm + j]["close"]),
                            )
                            for j in range(_last_pm)
                        ]
                        try:
                            _pm_dec = _pm_strat.evaluate(
                                symbol=sym_u, epic=epic_s,
                                ts=_ts_dt_pm, bars=_pm_bars,
                                pip_size=1.0,
                                bb_lower_at_n_close=_bbl_n,
                                bb_upper_at_n_close=_bbu_n,
                                bb_lower_at_np1_close=_bbl_np1,
                                bb_upper_at_np1_close=_bbu_np1,
                                has_open_long=has_active_trade_for_mode(
                                    epic_s, "GBPUSD_BB_PREMIRROR_L"
                                ),
                                has_open_short=has_active_trade_for_mode(
                                    epic_s, "GBPUSD_BB_PREMIRROR_L_S"
                                ),
                            )
                        except Exception as _pme:
                            logger.error("[BB_PREMIRROR_L] evaluate failed: %s", _pme, exc_info=True)
                            _pm_dec = None
                        if _pm_dec is not None:
                            execute_trade(_pm_dec, epic_s)
            except Exception as _pm_disp:
                logger.error("[BB_PREMIRROR_L] dispatch wrapper failed: %s", _pm_disp, exc_info=True)

        # ─── GBPUSD_NY_CONTINUATION_L (2026-04-25) ────────────────────────
        # Sixth (and last) node in the GBPUSD net. Catches NY momentum
        # continuation of directional London sessions. Reads the London
        # session from data/candles/GBPUSD/<date>.csv at first NY-window
        # tick; no BB indicator dependency. The strategy's own _in_window
        # check (12:30-15:30 UTC) is authoritative — we just dispatch on
        # every is_new_5m for GBPUSD and let it filter.
        if sym_u == "GBPUSD" and _is_new_5m and df is not None and len(df) >= 6:
            try:
                from gbpusd_ny_continuation_long import (
                    strategy as _ny_strat,
                    ENABLED as _NY_ENABLED,
                    Bar as _NYBar,
                )
                if _NY_ENABLED:
                    _ts_dt_ny = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _ts_col_ny = "time" if "time" in df.columns else "timestamp"
                    _last_ny = min(6, len(df))
                    def _row_ts_ny(_r):
                        v = _r[_ts_col_ny]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    _ny_bars = [
                        _NYBar(
                            timestamp=_row_ts_ny(df.iloc[-_last_ny + j]),
                            open=float(df.iloc[-_last_ny + j]["open"]),
                            high=float(df.iloc[-_last_ny + j]["high"]),
                            low=float(df.iloc[-_last_ny + j]["low"]),
                            close=float(df.iloc[-_last_ny + j]["close"]),
                        )
                        for j in range(_last_ny)
                    ]
                    try:
                        _ny_dec = _ny_strat.evaluate(
                            symbol=sym_u, epic=epic_s,
                            ts=_ts_dt_ny, bars=_ny_bars,
                            pip_size=1.0,
                            has_open_long=has_active_trade_for_mode(
                                epic_s, "GBPUSD_NY_CONTINUATION_L"
                            ),
                            has_open_short=has_active_trade_for_mode(
                                epic_s, "GBPUSD_NY_CONTINUATION_L_S"
                            ),
                        )
                    except Exception as _nye:
                        logger.error("[NY_CONTINUATION_L] evaluate failed: %s", _nye, exc_info=True)
                        _ny_dec = None
                    if _ny_dec is not None:
                        execute_trade(_ny_dec, epic_s)
            except Exception as _ny_disp:
                logger.error("[NY_CONTINUATION_L] dispatch wrapper failed: %s", _ny_disp, exc_info=True)

        # ─── GBPUSD_BB_BOUNCE / BB_PIERCE_RUN (rewritten 2026-05-02) ──────
        # Two-candle pierce + rejection on GBPUSD 5m. SL=12p hard,
        # TP_cap=80p with multi-tier trail, time stop 240m. Window
        # 06:00-17:00 UTC, BB_width>=8p, pierce>=1p, open-inside-band on
        # N-1, rejection direction on N. 30-min pre-news blackout for
        # GBP/USD high-impact events (in-strategy check).
        #
        # Direct-dispatch wrapper (bypasses the main strategy_logic path).
        # The strategy is intentionally exempted from the following,
        # either by traversing this wrapper instead of the main path, by
        # being in a bypass allowlist, or by being explicitly omitted here:
        #   - cross-mode pair_concurrency_check     (_PAIR_CONCURRENCY_BYPASS_MODES)
        #   - briefing thesis invalidation          (trade_manager allowlist)
        #   - sentinel scoring                      (only on main-path)
        # Per-direction slot enforcement (1 LONG + 1 SHORT max) comes from
        # the has_open_long / has_open_short args below.
        #
        # Router self-dispatch gate (Step 3, 2026-05-30). When
        # ROUTER_DISPATCH_ENABLED=1, the entire wrapper is skipped — the
        # router hook below is the sole dispatch path for BB_BOUNCE. Skipping
        # the WHOLE wrapper (not just execute_trade) is intentional: the
        # strategy's `_last_eval_bar` bar-dedup means a same-bar second
        # evaluate() call returns None, so leaving evaluate() running here
        # would silence the router's own adapter call. With router=0 the
        # wrapper runs unchanged (existing behaviour).
        #
        # 2026-06-29: under BB_BOUNCE_CLOSE_DISPATCH_ENABLED=1 (default)
        # the tick-driven dispatch below is short-circuited and the eval
        # runs from a post-rebuild 5M close callback instead (see
        # _on_5m_close_bb_bounce + main() registration). Setting the env
        # to 0 restores byte-identical legacy tick-driven dispatch.
        # Mirror of the structure_break migration (2026-06-16).
        _bb_close_dispatch_active = (
            (os.getenv("BB_BOUNCE_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1"
        )
        if (
            sym_u == "GBPUSD"
            and _is_new_5m
            and df is not None
            and len(df) >= 21
            and not _router_dispatch_enabled()
            and not _bb_close_dispatch_active
        ):
            try:
                from gbpusd_bb_bounce import (
                    strategy as _bbb_strat,
                    ENABLED as _BBB_ENABLED,
                    MODE_NAME_LONG as _BBB_MODE_L,
                    MODE_NAME_SHORT as _BBB_MODE_S,
                    Bar as _BBBBar,
                )
                if _BBB_ENABLED:
                    _ts_dt_bbb = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _ts_col_bbb = "time" if "time" in df.columns else "timestamp"
                    def _row_ts_bbb(_r):
                        v = _r[_ts_col_bbb]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    _last_bbb = min(60, len(df))
                    _bbb_bars = [
                        _BBBBar(
                            timestamp=_row_ts_bbb(df.iloc[-_last_bbb + j]),
                            open=float(df.iloc[-_last_bbb + j]["open"]),
                            high=float(df.iloc[-_last_bbb + j]["high"]),
                            low=float(df.iloc[-_last_bbb + j]["low"]),
                            close=float(df.iloc[-_last_bbb + j]["close"]),
                        )
                        for j in range(_last_bbb)
                    ]
                    _bbb_closes = [float(c) for c in df["close"].tolist()]
                    try:
                        _bbb_dec = _bbb_strat.evaluate(
                            symbol=sym_u, epic=epic_s,
                            ts=_ts_dt_bbb, bars=_bbb_bars,
                            closes_ind=_bbb_closes,
                            has_open_long=has_active_trade_for_mode(epic_s, _BBB_MODE_L),
                            has_open_short=has_active_trade_for_mode(epic_s, _BBB_MODE_S),
                        )
                    except Exception as _bbbe:
                        logger.error("[BB_BOUNCE] evaluate failed: %s", _bbbe, exc_info=True)
                        _bbb_dec = None
                    # Regime entry filter REMOVED for BB_PIERCE_RUN (2026-05-02).
                    # The strategy's own gate set is the authority; no upstream
                    # classifier can suppress a fire. If the regime classifier
                    # is later wired to gate other fade-class strategies, a
                    # mode-bypass for GBPUSD_BB_BOUNCE_L/_S must be added there.

                    # Guards (2026-05-02 wireup) — observable-only by default.
                    # Closes the dead-registration gap: GUARD_REGISTRY has had
                    # GBPUSD_BB_BOUNCE → [news_blackout, priced_in,
                    # levels_proximity] since commit df151ff but no code
                    # invoked check_trade for it. Mirrors the 3CO call site at
                    # autobot.py:3547-3569. strategy_mode = "GBPUSD_BB_BOUNCE"
                    # (no L/S suffix) to match the registry key. Direction +
                    # SL/TP prices derived from the StrategyDecision; entry
                    # uses decision.entry (the rejection-bar close), not mid_f,
                    # because the decision was already built and emits an
                    # entry-price intent.
                    if _bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED:
                        # GUARDS observable-mode gated off under matrix per
                        # Phase 2 spec §D. news_release_window.py continues to
                        # enforce entry-time blackout inside each strategy.
                        try:
                            from guards import check_trade as _bbb_guards_check
                            _bbb_dir = str(getattr(_bbb_dec, "signal", "")).upper()
                            _bbb_entry_px = float(
                                getattr(_bbb_dec, "entry", mid_f) or mid_f
                            )
                            _bbb_sl_pips_g = float(getattr(_bbb_dec, "sl", 0) or 0)
                            _bbb_tp_pips_g = float(getattr(_bbb_dec, "tp", 0) or 0)
                            if _bbb_dir == "SELL":
                                _bbb_sl_px = _bbb_entry_px + _bbb_sl_pips_g
                                _bbb_tp_px = _bbb_entry_px - _bbb_tp_pips_g
                            else:
                                _bbb_sl_px = _bbb_entry_px - _bbb_sl_pips_g
                                _bbb_tp_px = _bbb_entry_px + _bbb_tp_pips_g
                            _bbb_g_blocked, _bbb_g_reason = _bbb_guards_check(
                                symbol=sym_u,
                                direction=_bbb_dir,
                                strategy_mode="GBPUSD_BB_BOUNCE",
                                intended_entry=_bbb_entry_px,
                                intended_sl=_bbb_sl_px,
                                intended_tp=_bbb_tp_px,
                                current_mid=float(mid_f),
                                df_5m=df,
                                pip_size=1.0,
                            )
                            if _bbb_g_blocked:
                                logger.info(
                                    "[BB_BOUNCE] %s %s blocked by guards: %s",
                                    sym_u, _bbb_dir, _bbb_g_reason,
                                )
                                _bbb_dec = None
                        except Exception as _bbb_g_exc:
                            logger.warning(
                                "[BB_BOUNCE] guard eval raised: %s",
                                _bbb_g_exc, exc_info=True,
                            )

                    if _bbb_dec is not None:
                        _bbb_trade_result = execute_trade(_bbb_dec, epic_s)
                        # Back-annotation (telemetry only). When
                        # execute_trade returns None, the strategy's own
                        # forensic_fires row at gbpusd_bb_bounce.py:780-788
                        # is left without an outcome — a reader can't tell
                        # whether HTF_AUTHORITY blocked it, CONVICTION_GATE
                        # blocked it, RACE_CAUGHT tripped, etc. Append a
                        # sibling row joinable on (strategy, fire_bar_ts).
                        # Zero trading-path effect — the trade was already
                        # dropped at this point.
                        if _bbb_trade_result is None:
                            try:
                                from trade_executor import (
                                    consume_last_block_info as _bbb_consume_blk,
                                )
                                _bbb_blk = _bbb_consume_blk()
                                if _bbb_blk:
                                    from forensic_logger import (
                                        write_forensic_fire as _bbb_ff_write,
                                    )
                                    _bbb_ann_mode = (
                                        _BBB_MODE_L
                                        if str(getattr(_bbb_dec, "signal", "")).upper() == "BUY"
                                        else _BBB_MODE_S
                                    )
                                    _bbb_ann_fbts = (
                                        _bbb_bars[-1].timestamp.isoformat()
                                        if _bbb_bars else ""
                                    )
                                    _bbb_ann_dir = str(getattr(_bbb_dec, "signal", "")) or ""
                                    _bbb_ann_entry = float(
                                        getattr(_bbb_dec, "entry", None) or 0.0
                                    )
                                    _bbb_ann_reason = {
                                        "rule": _bbb_blk.get("stage", "unknown"),
                                        "stage": _bbb_blk.get("stage", "unknown"),
                                        "reason": _bbb_blk.get("reason", ""),
                                        "block_stage": _bbb_blk.get("stage", "unknown"),
                                        "block_reason": _bbb_blk.get("reason", ""),
                                        "annotation": True,
                                        "block_ts_ms": _bbb_blk.get("ts_ms"),
                                    }
                                    _bbb_ff_write(
                                        strategy=_bbb_ann_mode,
                                        direction=_bbb_ann_dir,
                                        entry_price=_bbb_ann_entry,
                                        fire_bar_ts=_bbb_ann_fbts,
                                        snapshot_dict={},
                                        block_reason=_bbb_ann_reason,
                                        pair="GBPUSD",
                                    )
                            except Exception as _bbb_ann_exc:  # noqa: BLE001
                                logger.debug(
                                    "[BB_BOUNCE] block annotation write failed: %s",
                                    _bbb_ann_exc,
                                )
                        # signal_log persistence — without this, BB_BOUNCE
                        # trades never reach signal_log.jsonl (the main-
                        # dispatch log_open at autobot.py:3857 is below this
                        # block and is unreachable from the direct dispatch
                        # path). Same pattern as the NEWS_TICK fix
                        # (commit 72a6f9a, 2026-04).
                        if isinstance(_bbb_trade_result, dict) and (
                            has_active_trade_for_mode(epic_s, _BBB_MODE_L)
                            or has_active_trade_for_mode(epic_s, _BBB_MODE_S)
                        ):
                            try:
                                _bbb_mode = (_BBB_MODE_L
                                             if str(getattr(_bbb_dec, "signal", "")).upper() == "BUY"
                                             else _BBB_MODE_S)
                                _bbb_pk = _pos_key(epic_s, _bbb_mode)
                                _bbb_sl_id = str(uuid.uuid4())
                                _bbb_briefing = morning_briefing.get_briefing(sym_u) or {}
                                _bbb_entry = float(getattr(_bbb_dec, "entry", None) or 0.0)
                                _bbb_entry, _bbb_entry_source = _resolve_entry_price_and_source(_bbb_pk, _bbb_dec, _bbb_entry)
                                _bbb_deal_id = (
                                    _bbb_trade_result.get("dealId")
                                    or _bbb_trade_result.get("deal_id")
                                    or (EPIC_STATE.get(_bbb_pk) or {}).get("dealId")
                                )
                                signal_logger.log_open(
                                    trade_id=_bbb_sl_id,
                                    epic=epic_s,
                                    decision=_bbb_dec,
                                    briefing=_bbb_briefing,
                                    df_5m=df,
                                    entry_price=_bbb_entry,
                                    deal_id=_bbb_deal_id,
                                    latency=(EPIC_STATE.get(_bbb_pk) or {}).get("fire_latency"),
                                    entry_price_source=_bbb_entry_source,
                                )
                                _bbb_st = EPIC_STATE.get(_bbb_pk)
                                if _bbb_st is not None:
                                    _bbb_st["signal_log_id"] = _bbb_sl_id
                                    _bbb_st["decision_debug"] = dict(getattr(_bbb_dec, "debug", None) or {})
                            except Exception as _bbb_sl_exc:
                                logger.warning("[BB_BOUNCE] signal_log.log_open failed: %s", _bbb_sl_exc)

                            # Multi-tier briefing-TP registration — mirrors
                            # autobot.py:3833-3849 main-dispatch path. The
                            # BB_BOUNCE direct-dispatch wrapper bypasses
                            # that block, so we replicate it here so
                            # trade_manager._monitor_briefing_tp drives the
                            # TP1/TP2/TP3 progression on this position.
                            try:
                                _bbb_dbg_tp = getattr(_bbb_dec, "debug", None) or {}
                                _bbb_confirmed_entry = (
                                    _bbb_trade_result.get("entry_price")
                                    or (EPIC_STATE.get(_bbb_pk) or {}).get("entry_price")
                                )
                                _bbb_tp_entry = float(_bbb_confirmed_entry or _bbb_entry)
                                _bbb_signal = str(getattr(_bbb_dec, "signal", "")).upper()
                                if _bbb_dbg_tp.get("range_scalp"):
                                    # RANGE_ROTATION single-exit scalp: register
                                    # for regime-exit monitoring INSTEAD of the
                                    # tier machine. Broker LIMIT (opposite band)
                                    # is the real exit.
                                    register_bb_range_scalp(
                                        epic=_bbb_pk,
                                        entry_price=_bbb_tp_entry,
                                        direction=_bbb_signal,
                                        opposite_band_price=float(
                                            _bbb_dbg_tp.get("range_scalp_opp_band") or 0.0
                                        ),
                                        pair=sym_u,
                                    )
                                elif _bbb_dbg_tp.get("tp_plan") and _bbb_dbg_tp.get("briefing_levels") is not None:
                                    trade_manager.setup_briefing_tp(
                                        epic=_bbb_pk,
                                        entry_price=_bbb_tp_entry,
                                        direction=_bbb_signal,
                                        briefing_levels=_bbb_dbg_tp["briefing_levels"],
                                        pair=sym_u,
                                    )
                            except Exception as _bbb_tp_err:
                                logger.error(
                                    "[BB_BOUNCE] tier/scalp register failed: %s",
                                    _bbb_tp_err,
                                )
            except Exception as _bbb_disp:
                logger.error("[BB_BOUNCE] dispatch wrapper failed: %s", _bbb_disp, exc_info=True)

        # ─── GBPUSD_BB_REV_PAT (V-shaped + Arc reversal — 2026-05-04) ─────
        # Two BB-reversal patterns under one strategy module
        # (gbpusd_bb_reversal_patterns.py). Designed to catch reversals
        # that BB_PIERCE_RUN's pierce+rejection pattern misses:
        #   - V-SHAPED: 2-bar (touch + opposite-direction reversal candle).
        #   - ARC:      3-7 bar hugging arc + opposite-direction reversal.
        # Co-fire suppression with BB_PIERCE_RUN is enforced inside the
        # strategy via _bb_pierce_run_active (reads bb_bounce armed
        # setups + recent bb_bounce open positions). SL/TP/news/regime/
        # window all mirror BB_PIERCE_RUN.
        #
        # Direct-dispatch wrapper, mirroring BB_BOUNCE. signal_log.log_open
        # called manually below to close the dispatcher gap. setup_briefing_tp
        # registered identically so trade_manager._monitor_briefing_tp
        # drives the multi-tier TP1/TP2/TP3 progression.
        #
        # Router self-dispatch gate (Step 4, 2026-05-30). The strategy has
        # `_last_eval_bar` bar-dedup at gbpusd_bb_reversal_patterns.py:484-487;
        # a same-bar second evaluate() from the router would early-return
        # None. Skip the WHOLE wrapper when router is on — same pattern as
        # BB_BOUNCE / EMA_PULLBACK. With router=0 the wrapper runs unchanged.
        #
        # 2026-06-29: under BB_REV_PAT_CLOSE_DISPATCH_ENABLED=1 (default)
        # the tick-driven dispatch below is short-circuited and the eval
        # runs from a post-rebuild 5M close callback instead (see
        # _on_5m_close_bb_rev_pat + main() registration). Setting the env
        # to 0 restores byte-identical legacy tick-driven dispatch.
        # Mirror of bb_bounce (cac2eb3+3672512) and ema_pullback (f69d971).
        # The strategy's own `_last_eval_bar` per-epic dedup is the
        # belt-and-braces; the early-skip below is the primary guarantee.
        _bb_rev_pat_close_dispatch_active = (
            (os.getenv("BB_REV_PAT_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1"
        )
        if (
            sym_u == "GBPUSD"
            and _is_new_5m
            and df is not None
            and len(df) >= 21
            and not _router_dispatch_enabled()
            and not _bb_rev_pat_close_dispatch_active
        ):
            try:
                from gbpusd_bb_reversal_patterns import (
                    strategy as _brp_strat,
                    ENABLED as _BRP_ENABLED,
                    MODE_NAME_LONG as _BRP_MODE_L,
                    MODE_NAME_SHORT as _BRP_MODE_S,
                    Bar as _BRPBar,
                )
                if _BRP_ENABLED:
                    _ts_dt_brp = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _ts_col_brp = "time" if "time" in df.columns else "timestamp"
                    def _row_ts_brp(_r):
                        v = _r[_ts_col_brp]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    _last_brp = min(60, len(df))
                    _brp_bars = [
                        _BRPBar(
                            timestamp=_row_ts_brp(df.iloc[-_last_brp + j]),
                            open=float(df.iloc[-_last_brp + j]["open"]),
                            high=float(df.iloc[-_last_brp + j]["high"]),
                            low=float(df.iloc[-_last_brp + j]["low"]),
                            close=float(df.iloc[-_last_brp + j]["close"]),
                        )
                        for j in range(_last_brp)
                    ]
                    _brp_closes = [float(c) for c in df["close"].tolist()]
                    try:
                        _brp_dec = _brp_strat.evaluate(
                            symbol=sym_u, epic=epic_s,
                            ts=_ts_dt_brp, bars=_brp_bars,
                            closes_ind=_brp_closes,
                            has_open_long=has_active_trade_for_mode(epic_s, _BRP_MODE_L),
                            has_open_short=has_active_trade_for_mode(epic_s, _BRP_MODE_S),
                        )
                    except Exception as _brpe:
                        logger.error("[BB_REV_PAT] evaluate failed: %s", _brpe, exc_info=True)
                        _brp_dec = None

                    if _brp_dec is not None:
                        _brp_trade_result = execute_trade(_brp_dec, epic_s)
                        if isinstance(_brp_trade_result, dict) and (
                            has_active_trade_for_mode(epic_s, _BRP_MODE_L)
                            or has_active_trade_for_mode(epic_s, _BRP_MODE_S)
                        ):
                            try:
                                _brp_mode = (_BRP_MODE_L
                                             if str(getattr(_brp_dec, "signal", "")).upper() == "BUY"
                                             else _BRP_MODE_S)
                                _brp_pk = _pos_key(epic_s, _brp_mode)
                                _brp_sl_id = str(uuid.uuid4())
                                _brp_briefing = morning_briefing.get_briefing(sym_u) or {}
                                _brp_entry = float(getattr(_brp_dec, "entry", None) or 0.0)
                                _brp_entry, _brp_entry_source = _resolve_entry_price_and_source(_brp_pk, _brp_dec, _brp_entry)
                                _brp_deal_id = (
                                    _brp_trade_result.get("dealId")
                                    or _brp_trade_result.get("deal_id")
                                    or (EPIC_STATE.get(_brp_pk) or {}).get("dealId")
                                )
                                signal_logger.log_open(
                                    trade_id=_brp_sl_id,
                                    epic=epic_s,
                                    decision=_brp_dec,
                                    briefing=_brp_briefing,
                                    df_5m=df,
                                    entry_price=_brp_entry,
                                    deal_id=_brp_deal_id,
                                    latency=(EPIC_STATE.get(_brp_pk) or {}).get("fire_latency"),
                                    entry_price_source=_brp_entry_source,
                                )
                                _brp_st = EPIC_STATE.get(_brp_pk)
                                if _brp_st is not None:
                                    _brp_st["signal_log_id"] = _brp_sl_id
                                    _brp_st["decision_debug"] = dict(getattr(_brp_dec, "debug", None) or {})
                            except Exception as _brp_sl_exc:
                                logger.warning("[BB_REV_PAT] signal_log.log_open failed: %s", _brp_sl_exc)

                            try:
                                _brp_dbg_tp = getattr(_brp_dec, "debug", None) or {}
                                if _brp_dbg_tp.get("tp_plan") and _brp_dbg_tp.get("briefing_levels") is not None:
                                    _brp_confirmed_entry = (
                                        _brp_trade_result.get("entry_price")
                                        or (EPIC_STATE.get(_brp_pk) or {}).get("entry_price")
                                    )
                                    _brp_tp_entry = float(_brp_confirmed_entry or _brp_entry)
                                    _brp_signal = str(getattr(_brp_dec, "signal", "")).upper()
                                    trade_manager.setup_briefing_tp(
                                        epic=_brp_pk,
                                        entry_price=_brp_tp_entry,
                                        direction=_brp_signal,
                                        briefing_levels=_brp_dbg_tp["briefing_levels"],
                                        pair=sym_u,
                                    )
                            except Exception as _brp_tp_err:
                                logger.error(
                                    "[BB_REV_PAT] setup_briefing_tp failed: %s",
                                    _brp_tp_err,
                                )
            except Exception as _brp_disp:
                logger.error("[BB_REV_PAT] dispatch wrapper failed: %s", _brp_disp, exc_info=True)

        # ─── GBPUSD_EMA_PULLBACK (continuation pullback — 2026-05-26) ─────
        # Geometric pullback continuation in the trend direction:
        # BB-band touch → pullback into ema8..ema21 ribbon → fire with the
        # trend on a qualifying pierce bar gated by three filters (MACD
        # 3-bar signed slope, pullback last-2 body, fan ema8-ema50).
        # Module: gbpusd_ema_pullback.py — mirrors BB_REV_PAT dispatch
        # structure. Slot enforcement via has_active_trade_for_mode on
        # GBPUSD_EMA_PULLBACK_L/_S (DISTINCT slots from BB_BOUNCE / BB_REV_PAT).
        # ENABLED defaults OFF — controlled by env EMA_PULLBACK_ENABLED.
        #
        # Router self-dispatch gate (Step 3, 2026-05-30). Same shape as the
        # BB_BOUNCE wrapper above — entire block skipped when router is on.
        # ema_pullback.evaluate bumps `_last_fire_ts_by_epic` on a successful
        # fire (gbpusd_ema_pullback.py:773); a same-bar second call from the
        # router adapter would hit the cooldown and return None, so leaving
        # the legacy evaluate() in place would silence the router for this
        # strategy. With router=0 the wrapper runs unchanged.
        #
        # 2026-06-29: under EMA_PULLBACK_CLOSE_DISPATCH_ENABLED=1 (default)
        # the tick-driven dispatch below is short-circuited and the eval
        # runs from a post-rebuild 5M close callback instead (see
        # _on_5m_close_ema_pullback + main() registration). Setting the env
        # to 0 restores byte-identical legacy tick-driven dispatch.
        # Mirror of the bb_bounce migration (commit cac2eb3 + 3672512).
        # The arm-state machine (self._armed_machine) lives on a singleton
        # strategy instance, so legacy and callback dispatch share the
        # same dict — but only one path may run per bar or the machine
        # double-arms/disarms. The early-skip below + registration in
        # main() enforce exactly-one-path-per-bar.
        _ema_close_dispatch_active = (
            (os.getenv("EMA_PULLBACK_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1"
        )
        if (
            sym_u == "GBPUSD"
            and _is_new_5m
            and df is not None
            and len(df) >= 21
            and not _router_dispatch_enabled()
            and not _ema_close_dispatch_active
        ):
            try:
                from gbpusd_ema_pullback import (
                    strategy as _ep_strat,
                    ENABLED as _EP_ENABLED,
                    MODE_NAME_LONG as _EP_MODE_L,
                    MODE_NAME_SHORT as _EP_MODE_S,
                    Bar as _EPBar,
                )
                if _EP_ENABLED:
                    _ts_dt_ep = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _ts_col_ep = "time" if "time" in df.columns else "timestamp"
                    def _row_ts_ep(_r):
                        v = _r[_ts_col_ep]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    _last_ep = min(60, len(df))
                    _ep_bars = [
                        _EPBar(
                            timestamp=_row_ts_ep(df.iloc[-_last_ep + j]),
                            open=float(df.iloc[-_last_ep + j]["open"]),
                            high=float(df.iloc[-_last_ep + j]["high"]),
                            low=float(df.iloc[-_last_ep + j]["low"]),
                            close=float(df.iloc[-_last_ep + j]["close"]),
                        )
                        for j in range(_last_ep)
                    ]
                    _ep_closes = [float(c) for c in df["close"].tolist()]
                    # Full df highs/lows for TREND_ENTRY_GATE ADX-slope leg
                    # (added 2026-06-25). With only the last 60 _ep_bars,
                    # ADX-slope sign flips at the seed-bias level on real
                    # fills — must use full df warmup for parity.
                    _ep_highs = [float(h) for h in df["high"].tolist()]
                    _ep_lows = [float(l) for l in df["low"].tolist()]
                    try:
                        _ep_dec = _ep_strat.evaluate(
                            symbol=sym_u, epic=epic_s,
                            ts=_ts_dt_ep, bars=_ep_bars,
                            closes_ind=_ep_closes,
                            highs_ind=_ep_highs,
                            lows_ind=_ep_lows,
                            has_open_long=has_active_trade_for_mode(epic_s, _EP_MODE_L),
                            has_open_short=has_active_trade_for_mode(epic_s, _EP_MODE_S),
                        )
                    except Exception as _epe:
                        logger.error("[EMA_PULLBACK] evaluate failed: %s", _epe, exc_info=True)
                        _ep_dec = None

                    if _ep_dec is not None:
                        _ep_trade_result = execute_trade(_ep_dec, epic_s)
                        if isinstance(_ep_trade_result, dict) and (
                            has_active_trade_for_mode(epic_s, _EP_MODE_L)
                            or has_active_trade_for_mode(epic_s, _EP_MODE_S)
                        ):
                            try:
                                _ep_mode = (_EP_MODE_L
                                            if str(getattr(_ep_dec, "signal", "")).upper() == "BUY"
                                            else _EP_MODE_S)
                                _ep_pk = _pos_key(epic_s, _ep_mode)
                                _ep_sl_id = str(uuid.uuid4())
                                _ep_briefing = morning_briefing.get_briefing(sym_u) or {}
                                _ep_entry = float(getattr(_ep_dec, "entry", None) or 0.0)
                                _ep_entry, _ep_entry_source = _resolve_entry_price_and_source(_ep_pk, _ep_dec, _ep_entry)
                                _ep_deal_id = (
                                    _ep_trade_result.get("dealId")
                                    or _ep_trade_result.get("deal_id")
                                    or (EPIC_STATE.get(_ep_pk) or {}).get("dealId")
                                )
                                signal_logger.log_open(
                                    trade_id=_ep_sl_id,
                                    epic=epic_s,
                                    decision=_ep_dec,
                                    briefing=_ep_briefing,
                                    df_5m=df,
                                    entry_price=_ep_entry,
                                    deal_id=_ep_deal_id,
                                    latency=(EPIC_STATE.get(_ep_pk) or {}).get("fire_latency"),
                                    entry_price_source=_ep_entry_source,
                                )
                                _ep_st = EPIC_STATE.get(_ep_pk)
                                if _ep_st is not None:
                                    _ep_st["signal_log_id"] = _ep_sl_id
                                    _ep_st["decision_debug"] = dict(getattr(_ep_dec, "debug", None) or {})
                            except Exception as _ep_sl_exc:
                                logger.warning("[EMA_PULLBACK] signal_log.log_open failed: %s", _ep_sl_exc)

                            # Exhaustion telemetry — capture-only, gates
                            # nothing. Default OFF; only fires when
                            # EMA_PULLBACK_EXHAUSTION_TELEMETRY_ENABLED=1.
                            try:
                                import ema_pullback_exhaustion as _ep_exh
                                if _ep_exh.is_enabled():
                                    from pair_config import get_ppp as _ep_exh_ppp
                                    _ep_exh.log_fire(
                                        trade_id=_ep_sl_id,
                                        deal_id=_ep_deal_id,
                                        epic=epic_s,
                                        symbol=sym_u,
                                        direction=str(getattr(_ep_dec, "signal", "") or ""),
                                        fire_ts_utc=_ts_dt_ep,
                                        df_5m=df,
                                        pip_size=_ep_exh_ppp(epic_s),
                                        decision_debug=getattr(_ep_dec, "debug", None) or {},
                                    )
                            except Exception as _ep_exh_exc:
                                logger.debug(
                                    "[EMA_PULLBACK] exhaustion telemetry failed: %s",
                                    _ep_exh_exc,
                                )

                            try:
                                _ep_dbg_tp = getattr(_ep_dec, "debug", None) or {}
                                if _ep_dbg_tp.get("tp_plan") and _ep_dbg_tp.get("briefing_levels") is not None:
                                    _ep_confirmed_entry = (
                                        _ep_trade_result.get("entry_price")
                                        or (EPIC_STATE.get(_ep_pk) or {}).get("entry_price")
                                    )
                                    _ep_tp_entry = float(_ep_confirmed_entry or _ep_entry)
                                    _ep_signal = str(getattr(_ep_dec, "signal", "")).upper()
                                    trade_manager.setup_briefing_tp(
                                        epic=_ep_pk,
                                        entry_price=_ep_tp_entry,
                                        direction=_ep_signal,
                                        briefing_levels=_ep_dbg_tp["briefing_levels"],
                                        pair=sym_u,
                                    )
                            except Exception as _ep_tp_err:
                                logger.error(
                                    "[EMA_PULLBACK] setup_briefing_tp failed: %s",
                                    _ep_tp_err,
                                )
            except Exception as _ep_disp:
                logger.error("[EMA_PULLBACK] dispatch wrapper failed: %s", _ep_disp, exc_info=True)

        # ─── GBPUSD_STRUCTURE_BREAK (break-of-structure momentum, 2026-06-15) ─
        # Momentum entry that fires ON a fresh decisive 5M structure flip
        # (htf_authority._structure_dir primitive). Closes the gap the
        # pullback-faders (EMA_PULLBACK, TREND) can't reach: thrust bars
        # where the 5M EMA stack is still mid-flip. Distinct slots
        # GBPUSD_STRUCTURE_BREAK_L/_S. ENABLED defaults OFF — flag
        # STRUCTURE_BREAK_ENABLED. Same dispatch shape as EMA_PULLBACK;
        # router skip rule mirrored.
        #
        # 2026-06-16: under STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED=1 (default)
        # the tick-driven dispatch below is short-circuited and the eval
        # runs from a post-rebuild 5M close callback instead (see
        # _on_5m_close_structure_break + main() registration). Setting the
        # env to 0 restores byte-identical legacy tick-driven dispatch.
        _sb_close_dispatch_active = (
            (os.getenv("STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1"
        )
        if (
            sym_u == "GBPUSD"
            and _is_new_5m
            and df is not None
            and len(df) >= 30
            and not _router_dispatch_enabled()
            and not _sb_close_dispatch_active
        ):
            try:
                from gbpusd_structure_break import (
                    strategy as _sb_strat,
                    ENABLED as _SB_ENABLED,
                    MODE_NAME_LONG as _SB_MODE_L,
                    MODE_NAME_SHORT as _SB_MODE_S,
                    Bar as _SBBar,
                )
                if _SB_ENABLED:
                    _ts_dt_sb = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _ts_col_sb = "time" if "time" in df.columns else "timestamp"
                    def _row_ts_sb(_r):
                        v = _r[_ts_col_sb]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    _last_sb = min(60, len(df))
                    _sb_bars = [
                        _SBBar(
                            timestamp=_row_ts_sb(df.iloc[-_last_sb + j]),
                            open=float(df.iloc[-_last_sb + j]["open"]),
                            high=float(df.iloc[-_last_sb + j]["high"]),
                            low=float(df.iloc[-_last_sb + j]["low"]),
                            close=float(df.iloc[-_last_sb + j]["close"]),
                        )
                        for j in range(_last_sb)
                    ]
                    # Full df closes/highs/lows for TREND_ENTRY_GATE
                    # (added 2026-06-25). 60-bar warmup is too short for
                    # clean ADX-slope parity vs the diagnostic.
                    _sb_closes = [float(c) for c in df["close"].tolist()]
                    _sb_highs = [float(h) for h in df["high"].tolist()]
                    _sb_lows = [float(l) for l in df["low"].tolist()]
                    try:
                        _sb_dec = _sb_strat.evaluate(
                            symbol=sym_u, epic=epic_s,
                            ts=_ts_dt_sb, bars=_sb_bars,
                            has_open_long=has_active_trade_for_mode(epic_s, _SB_MODE_L),
                            has_open_short=has_active_trade_for_mode(epic_s, _SB_MODE_S),
                            closes_ind=_sb_closes,
                            highs_ind=_sb_highs,
                            lows_ind=_sb_lows,
                        )
                    except Exception as _sbe:
                        logger.error("[STRUCTURE_BREAK] evaluate failed: %s", _sbe, exc_info=True)
                        _sb_dec = None

                    if _sb_dec is not None:
                        _sb_trade_result = execute_trade(_sb_dec, epic_s)
                        if isinstance(_sb_trade_result, dict) and (
                            has_active_trade_for_mode(epic_s, _SB_MODE_L)
                            or has_active_trade_for_mode(epic_s, _SB_MODE_S)
                        ):
                            try:
                                _sb_mode = (_SB_MODE_L
                                            if str(getattr(_sb_dec, "signal", "")).upper() == "BUY"
                                            else _SB_MODE_S)
                                _sb_pk = _pos_key(epic_s, _sb_mode)
                                _sb_sl_id = str(uuid.uuid4())
                                _sb_briefing = morning_briefing.get_briefing(sym_u) or {}
                                _sb_entry = float(getattr(_sb_dec, "entry", None) or 0.0)
                                _sb_entry, _sb_entry_source = _resolve_entry_price_and_source(_sb_pk, _sb_dec, _sb_entry)
                                _sb_deal_id = (
                                    _sb_trade_result.get("dealId")
                                    or _sb_trade_result.get("deal_id")
                                    or (EPIC_STATE.get(_sb_pk) or {}).get("dealId")
                                )
                                signal_logger.log_open(
                                    trade_id=_sb_sl_id,
                                    epic=epic_s,
                                    decision=_sb_dec,
                                    briefing=_sb_briefing,
                                    df_5m=df,
                                    entry_price=_sb_entry,
                                    deal_id=_sb_deal_id,
                                    latency=(EPIC_STATE.get(_sb_pk) or {}).get("fire_latency"),
                                    entry_price_source=_sb_entry_source,
                                )
                                _sb_st = EPIC_STATE.get(_sb_pk)
                                if _sb_st is not None:
                                    _sb_st["signal_log_id"] = _sb_sl_id
                                    _sb_st["decision_debug"] = dict(getattr(_sb_dec, "debug", None) or {})
                            except Exception as _sb_sl_exc:
                                logger.warning("[STRUCTURE_BREAK] signal_log.log_open failed: %s", _sb_sl_exc)
            except Exception as _sb_disp:
                logger.error("[STRUCTURE_BREAK] dispatch wrapper failed: %s", _sb_disp, exc_info=True)

        # ─── ROUTER hook (Step 3 wiring, 2026-05-30) ──────────────────────
        # Single dispatch path for the structure-driven strategies (BB_BOUNCE,
        # EMA_PULLBACK, GBPUSD_TREND, BB_REVERSAL family). Gated behind
        # ROUTER_DISPATCH_ENABLED (default 0). When 0 the hook is dormant and
        # the legacy per-strategy self-dispatch sites above remain the live
        # path — bot behaviour is unchanged. When 1 the router is the SOLE
        # dispatch source for the gated strategies, and the per-strategy
        # self-dispatch sites above skip execute_trade. The router's decision
        # flows through the EXISTING execute_trade — so conviction gate +
        # structure-exit + RACE_CAUGHT + post-SL block + briefing logic all
        # continue to apply to router-dispatched trades unchanged.
        if (
            sym_u == "GBPUSD"
            and _is_new_5m
            and df is not None
            and len(df) >= 21
            and _router_dispatch_enabled()
        ):
            try:
                import router as _router_mod
                import numpy as _r_np
                import pandas as _r_pd
                _r_h1 = []
                if _TF_CTX is not None:
                    try:
                        _r_h1 = _TF_CTX.get_closed_candles(sym_u, "H1") or []
                    except Exception:
                        _r_h1 = []
                # Need at least 30 H1 bars for structure/regime to compute
                # anything meaningful — Layer 1 needs swings (≥6 bars), Layer 2
                # needs ema50 slope over 5 bars + BB width over 40 bars.
                if len(_r_h1) >= 30:
                    _r_h1_highs = _r_np.array(
                        [float(c["high"]) for c in _r_h1], dtype=_r_np.float64
                    )
                    _r_h1_lows = _r_np.array(
                        [float(c["low"]) for c in _r_h1], dtype=_r_np.float64
                    )
                    _r_h1_closes = _r_np.array(
                        [float(c["close"]) for c in _r_h1], dtype=_r_np.float64
                    )
                    _r_h1_close_series = _r_pd.Series(_r_h1_closes)
                    _r_ema20_series = _r_h1_close_series.ewm(span=20, adjust=False).mean()
                    _r_ema50_series = _r_h1_close_series.ewm(span=50, adjust=False).mean()
                    _r_ema200_series = _r_h1_close_series.ewm(span=200, adjust=False).mean()
                    _r_ema20_h1 = float(_r_ema20_series.iloc[-1])
                    _r_ema50_h1 = float(_r_ema50_series.iloc[-1])
                    _r_ema200_h1 = float(_r_ema200_series.iloc[-1])
                    _r_ema50_series_arr = _r_ema50_series.to_numpy(dtype=_r_np.float64)
                    _r_ts_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _r_prior_struct = _ROUTER_PRIOR_STRUCTURE_BY_SYMBOL.get(sym_u)
                    _r_has_long_any = (
                        has_active_trade_for_mode(epic_s, "GBPUSD_EMA_PULLBACK_L")
                        or has_active_trade_for_mode(epic_s, "GBPUSD_BB_BOUNCE_L")
                        or has_active_trade_for_mode(epic_s, "GBPUSD_TREND_L")
                    )
                    _r_has_short_any = (
                        has_active_trade_for_mode(epic_s, "GBPUSD_EMA_PULLBACK_S")
                        or has_active_trade_for_mode(epic_s, "GBPUSD_BB_BOUNCE_S")
                        or has_active_trade_for_mode(epic_s, "GBPUSD_TREND_S")
                    )
                    _r_result = _router_mod.route(
                        symbol=sym_u, epic=epic_s, ts=_r_ts_dt, df_5m=df,
                        h1_highs=_r_h1_highs, h1_lows=_r_h1_lows, h1_closes=_r_h1_closes,
                        ema20_h1=_r_ema20_h1, ema50_h1=_r_ema50_h1, ema200_h1=_r_ema200_h1,
                        ema50_series_h1=_r_ema50_series_arr,
                        prior_structure=_r_prior_struct,
                        has_open_long=_r_has_long_any,
                        has_open_short=_r_has_short_any,
                    )
                    # Update prior_structure for next bar's CHoCH
                    _ROUTER_PRIOR_STRUCTURE_BY_SYMBOL[sym_u] = _r_result.get("structure")
                    _r_decision = _r_result.get("decision")
                    _r_reason = _r_result.get("reason") or "no_reason"
                    _r_regime = _r_result.get("regime") or "?"
                    _r_selector = _r_result.get("selector") or "?"
                    _r_iid = _r_result.get("regime_instance_id")
                    if _r_decision is not None:
                        logger.info(
                            "[ROUTER] %s 5M close → regime=%s selector=%s "
                            "decision=%s/%s instance=%s",
                            sym_u, _r_regime, _r_selector,
                            str(getattr(_r_decision, "regime", "?")),
                            str(getattr(_r_decision, "signal", "?")),
                            (_r_iid or "")[:8],
                        )
                        try:
                            _r_trade_result = execute_trade(_r_decision, epic_s)
                        except Exception as _r_te:
                            logger.error("[ROUTER] execute_trade crashed: %s", _r_te, exc_info=True)
                            _r_trade_result = None
                        # Forensic capture is owned by each strategy's existing
                        # forensic hooks — the router does not duplicate them.
                        # signal_log persistence is likewise owned downstream
                        # (mark_position_opened path), matching the live wiring
                        # for these strategies prior to router introduction.
                    else:
                        logger.debug(
                            "[ROUTER] %s 5M close no-trade: regime=%s selector=%s reason=%s",
                            sym_u, _r_regime, _r_selector, _r_reason,
                        )
                else:
                    logger.debug(
                        "[ROUTER] %s 5M close skipped: H1 history insufficient (%d bars)",
                        sym_u, len(_r_h1),
                    )
            except Exception as _r_exc:
                logger.error("[ROUTER] hook failed: %s", _r_exc, exc_info=True)

        # ─── GBPUSD_RAW_REVERSAL (2026-04-28, replaced by BB_BOUNCE) ──────
        # Replacement bidirectional reversal strategy for GBPUSD. Three
        # geometric setups (BB pierce+recover, engulfing+hold, curve+rejection)
        # gated by four context filters (body slope, RSI lift, MACD decay,
        # level proximity). Self-contained session counter (max 3 entries
        # per direction in the 06:00-21:00 UTC window). Bypasses the per-pair
        # 120s cooldown and the post-SL block by mode. Disabled by default
        # after 2026-04-30 — kept loaded for one release in case of rollback.
        if sym_u == "GBPUSD" and _is_new_5m and df is not None and len(df) >= 21:
            try:
                from gbpusd_raw_reversal import (
                    strategy as _rr_strat,
                    ENABLED as _RR_ENABLED,
                    MODE_NAME_LONG as _RR_MODE_L,
                    MODE_NAME_SHORT as _RR_MODE_S,
                    Bar as _RRBar,
                )
                if _RR_ENABLED:
                    _ts_dt_rr = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _ts_col_rr = "time" if "time" in df.columns else "timestamp"
                    def _row_ts_rr(_r):
                        v = _r[_ts_col_rr]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    # Hand the strategy enough history for level/morning-extreme
                    # extraction (06:00 UTC onward) and indicator computation.
                    _last_rr = min(60, len(df))
                    _rr_bars = [
                        _RRBar(
                            timestamp=_row_ts_rr(df.iloc[-_last_rr + j]),
                            open=float(df.iloc[-_last_rr + j]["open"]),
                            high=float(df.iloc[-_last_rr + j]["high"]),
                            low=float(df.iloc[-_last_rr + j]["low"]),
                            close=float(df.iloc[-_last_rr + j]["close"]),
                        )
                        for j in range(_last_rr)
                    ]
                    _rr_closes = [float(c) for c in df["close"].tolist()]
                    _rr_briefing = None
                    try:
                        import morning_briefing as _mb_rr
                        _rr_briefing = _mb_rr.get_briefing(sym_u)
                    except Exception:
                        _rr_briefing = None
                    try:
                        _rr_dec = _rr_strat.evaluate(
                            symbol=sym_u, epic=epic_s,
                            ts=_ts_dt_rr, bars=_rr_bars,
                            closes_ind=_rr_closes,
                            briefing=_rr_briefing,
                            pip_size=1.0,
                            has_open_long=has_active_trade_for_mode(epic_s, _RR_MODE_L),
                            has_open_short=has_active_trade_for_mode(epic_s, _RR_MODE_S),
                        )
                    except Exception as _rre:
                        logger.error("[RAW_REVERSAL] evaluate failed: %s", _rre, exc_info=True)
                        _rr_dec = None
                    if _rr_dec is not None:
                        execute_trade(_rr_dec, epic_s)
            except Exception as _rr_disp:
                logger.error("[RAW_REVERSAL] dispatch wrapper failed: %s", _rr_disp, exc_info=True)

        # ─── GBPUSD_CONFIRMATION_FALLBACK (NEW — 2026-06-28) ─────────────
        # Self-dispatching CHOP-bucket sweep / reclaim / M5-confirm sequencer.
        # Mirrors BB_BOUNCE / RAW_REVERSAL idiom. Gated by:
        #   not _router_dispatch_enabled()  — router is dormant (env=0); this
        #                                      strategy lives in the self-
        #                                      dispatch lane.
        #   _CF_ENABLED                     — CONFIRMATION_FALLBACK_ENABLED
        #                                      (default "0"). When OFF the
        #                                      strategy is never evaluated.
        # Inside the strategy, CONFIRMATION_FALLBACK_SHADOW (default "1") is
        # a second gate: when ON, evaluate() runs the full sequencer,
        # writes logs/confirmation_fallback.jsonl, and returns None — so
        # execute_trade is never reached. Live trading requires ENABLED=1
        # AND SHADOW=0.
        #
        # 2026-06-29: under CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED=1
        # (default) the tick-driven dispatch below is short-circuited and
        # the eval runs from a post-rebuild 5M close callback instead
        # (see _on_5m_close_confirmation_fallback + main() registration).
        # The callback ALSO fixes the half-wired post-decision pipeline:
        # the legacy block below only calls execute_trade, missing
        # signal_log.log_open / setup_briefing_tp / EPIC_STATE writes.
        # The callback adds all three so live fires reach signal_log.jsonl.
        # Setting the env to 0 restores byte-identical legacy tick-driven
        # dispatch (with the original broken pipeline). Mirror of the
        # bb_bounce / ema_pullback / bb_rev_pat migrations earlier today.
        # The CONFIRMATION_FALLBACK_ENABLED enable flag is UNTOUCHED by
        # this migration — both paths still check _CF_ENABLED before
        # evaluate(); the strategy stays OFF until that flag is flipped.
        _cf_close_dispatch_active = (
            (os.getenv("CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1"
        )
        if (
            sym_u == "GBPUSD"
            and _is_new_5m
            and df is not None
            and len(df) >= 30
            and not _router_dispatch_enabled()
            and not _cf_close_dispatch_active
        ):
            try:
                from gbpusd_confirmation_fallback import (
                    strategy as _cf_strat,
                    ENABLED as _CF_ENABLED,
                    MODE_NAME_LONG as _CF_MODE_L,
                    MODE_NAME_SHORT as _CF_MODE_S,
                    Bar as _CFBar,
                )
                if _CF_ENABLED:
                    _ts_dt_cf = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    _ts_col_cf = "time" if "time" in df.columns else "timestamp"
                    def _row_ts_cf(_r):
                        v = _r[_ts_col_cf]
                        return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
                    _last_cf = min(60, len(df))
                    _cf_bars = [
                        _CFBar(
                            timestamp=_row_ts_cf(df.iloc[-_last_cf + j]),
                            open=float(df.iloc[-_last_cf + j]["open"]),
                            high=float(df.iloc[-_last_cf + j]["high"]),
                            low=float(df.iloc[-_last_cf + j]["low"]),
                            close=float(df.iloc[-_last_cf + j]["close"]),
                        )
                        for j in range(_last_cf)
                    ]
                    try:
                        _cf_dec = _cf_strat.evaluate(
                            symbol=sym_u, epic=epic_s,
                            ts=_ts_dt_cf, bars=_cf_bars,
                            has_open_long=has_active_trade_for_mode(epic_s, _CF_MODE_L),
                            has_open_short=has_active_trade_for_mode(epic_s, _CF_MODE_S),
                        )
                    except Exception as _cfe:
                        logger.error("[CONFIRMATION_FALLBACK] evaluate failed: %s", _cfe, exc_info=True)
                        _cf_dec = None
                    if _cf_dec is not None:
                        execute_trade(_cf_dec, epic_s)
            except Exception as _cf_disp:
                logger.error("[CONFIRMATION_FALLBACK] dispatch wrapper failed: %s", _cf_disp, exc_info=True)

        signal = getattr(decision, "signal", None)
        regime = getattr(decision, "regime", None)
        reason = getattr(decision, "reason", "") or ""

        if STRATEGY_LOG_EVERY_TICK:
            logger.debug(f"[STRATEGY] {sym_u} regime={regime} signal={signal} mid={mid_f:.6f} reason={reason}")
        else:
            self._log_strategy_once_per_bucket(sym_u, ts, regime, signal, reason, mid_f)

        # Log sweep signals blocked by strategy guards / exhaustion filter
        if signal not in ("BUY", "SELL"):
            _blocked_sweep = (
                "sweep_arm_rejected" in reason
                or "sweep_stage2_invalidated" in reason
                or "sweep_exhaustion" in reason
                or "sweep_quality_fail" in reason
            )
            if _blocked_sweep and _journal is not None:
                logger.warning(f"[{sym_u}/{epic_s}] [SWEEP-BLOCKED] {reason}")
                try:
                    _journal.log_signal(decision, taken=False, blocked_reason=reason, epic=epic_s)
                except Exception:
                    pass

            # 3CO fallback removed 2026-05-13 (strategy deleted —
            # replaced by GBPUSD_TREND cascade-driven entry above).
            return

        _mode = getattr(decision, "mode", "") or ""
        session_reason = "gate_stripped"

        bucket = _bucket_5m(ts)

        # Briefing avoid_before fresh-entry gate removed 2026-04-30 per
        # dispatcher-decoupling. Each strategy that wants to fade away
        # from briefing-named events handles that internally; the
        # dispatcher no longer enforces a blanket window.

        try:
            trade_result = execute_trade(decision, epic_s)
        except Exception as e:
            logger.error(f"[{sym_u}/{epic_s}] ❌ execute_trade crashed: {e}", exc_info=True)
            return

        # Build pos_key for metadata storage
        _opened_mode = str(getattr(decision, "mode", None) or "DEFAULT").strip().upper()
        _opened_pk = _pos_key(epic_s, _opened_mode)

        # Require BOTH a successful trade_result dict AND an active position.
        # has_active_trade_for_mode alone is ambiguous — it's True whenever
        # ANY position for this mode exists, including one already open
        # before this call. execute_trade returns None when it blocks a
        # re-entry against an already-active pos_key, which used to slip
        # past the "opened" check and emit a phantom signal_log row with
        # no matching IG trade (the CONTINUATION_SWEEP bookkeeping gap).
        opened = (
            isinstance(trade_result, dict)
            and bool(has_active_trade_for_mode(epic_s, _opened_mode))
        )
        if not opened:
            logger.warning(f"[{sym_u}/{epic_s}] ❌ Trade NOT opened for signal={signal} mode={_opened_mode} (executor returned {type(trade_result).__name__}). Bucket NOT consumed — retry allowed.")
            if _journal is not None:
                try:
                    _journal.log_signal(decision, taken=False, blocked_reason="execute_failed_or_not_opened", epic=epic_s)
                except Exception:
                    pass
            return

        # Trade opened successfully — now consume the 5-minute bucket
        self._mark_bucket_used(sym_u, epic_s, bucket)

        entry_val = _safe_float(getattr(decision, "entry", None), mid_f) or mid_f
        sl_val = getattr(decision, "sl", None)
        tp_val = getattr(decision, "tp", None)

        # Set up briefing-level TP management if decision carries a tp_plan
        _dbg_tp = getattr(decision, "debug", None) or {}
        if _dbg_tp.get("tp_plan") and _dbg_tp.get("briefing_levels") is not None:
            try:
                _confirmed_entry = (
                    trade_result.get("entry_price") if isinstance(trade_result, dict) else None
                )
                _tp_entry = float(_confirmed_entry or entry_val)
                trade_manager.setup_briefing_tp(
                    epic=_opened_pk,
                    entry_price=_tp_entry,
                    direction=signal,
                    briefing_levels=_dbg_tp["briefing_levels"],
                    pair=sym_u,
                    bb_reversal_mode=_dbg_tp.get("bb_reversal_mode"),
                )
            except Exception as _tp_err:
                logger.error(f"[{sym_u}/{epic_s}] setup_briefing_tp failed: {_tp_err}")

        logger.info(
            f"[{sym_u}/{epic_s}] 🚀 {signal} entry={float(entry_val):.5f} SL={sl_val} TP={tp_val} mode={_opened_mode} | {reason} | {session_reason} | bucket_open={current_bucket_open}"
        )

        if _journal is not None:
            try:
                _confirmed_fill = (
                    trade_result.get("entry_price") if isinstance(trade_result, dict) else None
                )
                if _confirmed_fill is not None:
                    decision.entry = _confirmed_fill
                _journal.log_signal(decision, taken=True, epic=epic_s)
            except Exception:
                pass

        # Stash briefing metadata in EPIC_STATE for retrieval at close
        try:
            _dbg = getattr(decision, "debug", None) or {}
            _briefing = morning_briefing.get_briefing(sym_u) or {}
            _epic_st = EPIC_STATE.get(_opened_pk)
            if _epic_st is not None:
                _epic_st["briefing_meta"] = {
                    "briefing_confirmed": _dbg.get("briefing_confirmed", False),
                    "briefing_level": _dbg.get("briefing_level"),
                    "plan_label": _dbg.get("briefing_plan_label", ""),
                    "briefing_bias": _briefing.get("daily_bias", ""),
                    "briefing_confidence": _briefing.get("bias_confidence", 0),
                    "session_expectation": _briefing.get("session_expectation", ""),
                }
        except Exception:
            pass

        # Signal outcome logger — record full open context
        try:
            _sl_id = str(uuid.uuid4())
            _sl_briefing = morning_briefing.get_briefing(sym_u) or {}
            _sl_entry = float(getattr(decision, "entry", None) or entry_val)
            _sl_entry, _sl_entry_source = _resolve_entry_price_and_source(_opened_pk, decision, _sl_entry)
            _sl_deal_id = (
                trade_result.get("dealId")
                or trade_result.get("deal_id")
                or (EPIC_STATE.get(_opened_pk) or {}).get("dealId")
            ) if isinstance(trade_result, dict) else (
                (EPIC_STATE.get(_opened_pk) or {}).get("dealId")
            )
            signal_logger.log_open(
                trade_id=_sl_id,
                epic=epic_s,
                decision=decision,
                briefing=_sl_briefing,
                df_5m=df,
                entry_price=_sl_entry,
                deal_id=_sl_deal_id,
                latency=(EPIC_STATE.get(_opened_pk) or {}).get("fire_latency"),
                entry_price_source=_sl_entry_source,
            )
            _sl_st = EPIC_STATE.get(_opened_pk)
            if _sl_st is not None:
                _sl_st["signal_log_id"] = _sl_id
                _sl_st["decision_debug"] = dict(getattr(decision, "debug", None) or {})
        except Exception as _sl_open_exc:
            # T1-4 (2026-05-24): never swallow silently. The broker
            # position is already open at this point; if log_open or its
            # prep (briefing fetch, float convert, EPIC_STATE lookup,
            # deal-id resolution) raises, the trade lives in IG with NO
            # signal_log row and previously NO log line at all — an
            # invisible fire. Logging this as a WARNING with exc_info
            # makes the failure observable. Behaviour unchanged: the
            # trade stays open and downstream management continues.
            logger.warning(
                "[SIGNAL_LOG] log_open or its prep raised for opened "
                "position (epic=%s pk=%s): %s",
                epic_s, _opened_pk, _sl_open_exc, exc_info=True,
            )

        # Forensic fire snapshot — main-dispatcher path. Strategies that
        # already self-capture (BB_PIERCE_RUN via gbpusd_bb_bounce.py,
        # GBPUSD_TREND via the self-dispatch wrapper above at :3267 (NEWS_TICK
        # pattern), BB_REV_PAT, BRIEFING_EXECUTION) are excluded so
        # forensic_fires.jsonl never gets duplicate records.
        try:
            _ff_mode = str(getattr(decision, "mode", "") or "").strip().upper()
            # FOOT-GUN: any new strategy that adds its OWN forensic emit
            # site (e.g. the gbpusd_bb_bounce.py:1147 pattern) MUST also be
            # added to this allowlist — otherwise this dispatcher path
            # captures a second time and forensic_fires.jsonl gets silent
            # duplicates that won't surface until a review fire-count
            # reconciliation discovers the mismatch. Strategy onboarding
            # checklist should reference this site.
            _ff_already_captured_modes = {
                "GBPUSD_BB_BOUNCE_L", "GBPUSD_BB_BOUNCE_S",
                "GBPUSD_TREND_L", "GBPUSD_TREND_S",
                "GBPUSD_BB_REV_PAT_L", "GBPUSD_BB_REV_PAT_S",
                "BRIEFING_EXECUTION",
            }
            if _ff_mode and _ff_mode not in _ff_already_captured_modes:
                # Best-effort coverage for any other strategy that flows
                # through the main dispatcher (e.g. future additions).
                # Skipping silently if mode is empty/unknown.
                pass
        except Exception as _ff_md_exc:
            logger.warning("[forensic] main-dispatcher capture failed: %s", _ff_md_exc)

        self._set_last_trade_ts(sym_u, epic_s, time.time())
        logger.info(f"[{sym_u}/{epic_s}] ⏳ Cooldown reset ({COOLDOWN_SECONDS}s)")

    def _on_5m_close_structure_break(self, payload: Dict[str, Any]) -> None:
        """Post-rebuild 5M close dispatch for GBPUSD_STRUCTURE_BREAK.

        Replaces the tick-driven dispatch at the _on_ls_tick `_is_new_5m`
        path under STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED=1. Runs from the
        candle_builder 5M close-callback chain AFTER regime_engine and
        htf_regime have rebuilt, so bars[-1] is always the just-closed
        bar regardless of whether the close was "tick-won" or
        "rebuild-won". Gated separately from the legacy block so the two
        paths never both dispatch on the same bar (the legacy block
        early-skips when this callback is registered).
        """
        try:
            if (os.getenv("STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() != "1":
                return
            sym_u = str(payload.get("symbol") or "").upper()
            if sym_u != "GBPUSD":
                return
            df = payload.get("df_5m")
            if df is None or len(df) < 30:
                return
            if _router_dispatch_enabled():
                return
            tick_state = self._latest_tick_state.get(sym_u)
            if not tick_state or not tick_state.get("epic"):
                logger.info("STRUCT_BREAK_DISPATCH:skip no_tick_state symbol=%s", sym_u)
                return
            epic_s = str(tick_state["epic"])
            from gbpusd_structure_break import (
                strategy as _sb_strat,
                ENABLED as _SB_ENABLED,
                MODE_NAME_LONG as _SB_MODE_L,
                MODE_NAME_SHORT as _SB_MODE_S,
                Bar as _SBBar,
            )
            if not _SB_ENABLED:
                return
            # Ordering fix (2026-07-09): synchronise with the engine pool
            # worker for THIS bar so permits() reads post-transition state.
            regime_matrix.wait_for_bar(sym_u, payload.get("bucket_epoch"))
            if not regime_matrix.permits(sym_u, _SB_MODE_L) and not regime_matrix.permits(sym_u, _SB_MODE_S):
                regime_matrix.log_suppression(sym_u, "GBPUSD_STRUCTURE_BREAK")
                return
            # Derive ts from the just-closed bar timestamp (the close-callback
            # payload carries it as `candle.timestamp` / `bucket_epoch`).
            _bucket_epoch = payload.get("bucket_epoch")
            if _bucket_epoch is not None:
                _ts_dt_sb = datetime.fromtimestamp(float(_bucket_epoch), tz=timezone.utc)
            else:
                _candle = payload.get("candle") or {}
                _cts = _candle.get("timestamp")
                if isinstance(_cts, datetime):
                    _ts_dt_sb = _cts if _cts.tzinfo else _cts.replace(tzinfo=timezone.utc)
                else:
                    _ts_dt_sb = datetime.now(timezone.utc)
            _ts_col_sb = "time" if "time" in df.columns else "timestamp"
            def _row_ts_sb(_r):
                v = _r[_ts_col_sb]
                return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
            _last_sb = min(60, len(df))
            _sb_bars = [
                _SBBar(
                    timestamp=_row_ts_sb(df.iloc[-_last_sb + j]),
                    open=float(df.iloc[-_last_sb + j]["open"]),
                    high=float(df.iloc[-_last_sb + j]["high"]),
                    low=float(df.iloc[-_last_sb + j]["low"]),
                    close=float(df.iloc[-_last_sb + j]["close"]),
                )
                for j in range(_last_sb)
            ]
            # Full df closes/highs/lows for TREND_ENTRY_GATE
            # (added 2026-06-25). See legacy dispatch above for rationale.
            _sb_closes = [float(c) for c in df["close"].tolist()]
            _sb_highs = [float(h) for h in df["high"].tolist()]
            _sb_lows = [float(l) for l in df["low"].tolist()]
            # Single per-bar ADX source for the VWAP-stretch brake
            # (2026-07-22). Called AFTER wait_for_bar() so
            # regime_engine.latest_result() is fresh for this bar. Same
            # sourced (adx, source) tuple is fed to every dispatch path
            # via the strategy's evaluate() kwargs — one call, one
            # value, no per-strategy re-source.
            _sb_brake_adx, _sb_brake_adx_src = _source_brake_adx_at_bar(sym_u, _ts_dt_sb)
            try:
                _sb_dec = _sb_strat.evaluate(
                    symbol=sym_u, epic=epic_s,
                    ts=_ts_dt_sb, bars=_sb_bars,
                    has_open_long=has_active_trade_for_mode(epic_s, _SB_MODE_L),
                    has_open_short=has_active_trade_for_mode(epic_s, _SB_MODE_S),
                    closes_ind=_sb_closes,
                    highs_ind=_sb_highs,
                    lows_ind=_sb_lows,
                    brake_adx_at_bar=_sb_brake_adx,
                    brake_adx_source=_sb_brake_adx_src,
                )
            except Exception as _sbe:
                logger.error("[STRUCTURE_BREAK] evaluate failed (close-cb): %s", _sbe, exc_info=True)
                _sb_dec = None

            if _sb_dec is not None:
                _sb_trade_result = execute_trade(_sb_dec, epic_s)
                if isinstance(_sb_trade_result, dict) and (
                    has_active_trade_for_mode(epic_s, _SB_MODE_L)
                    or has_active_trade_for_mode(epic_s, _SB_MODE_S)
                ):
                    try:
                        _sb_mode = (_SB_MODE_L
                                    if str(getattr(_sb_dec, "signal", "")).upper() == "BUY"
                                    else _SB_MODE_S)
                        _sb_pk = _pos_key(epic_s, _sb_mode)
                        _sb_sl_id = str(uuid.uuid4())
                        _sb_briefing = morning_briefing.get_briefing(sym_u) or {}
                        _sb_entry = float(getattr(_sb_dec, "entry", None) or 0.0)
                        _sb_entry, _sb_entry_source = _resolve_entry_price_and_source(_sb_pk, _sb_dec, _sb_entry)
                        _sb_deal_id = (
                            _sb_trade_result.get("dealId")
                            or _sb_trade_result.get("deal_id")
                            or (EPIC_STATE.get(_sb_pk) or {}).get("dealId")
                        )
                        signal_logger.log_open(
                            trade_id=_sb_sl_id,
                            epic=epic_s,
                            decision=_sb_dec,
                            briefing=_sb_briefing,
                            df_5m=df,
                            entry_price=_sb_entry,
                            deal_id=_sb_deal_id,
                            latency=(EPIC_STATE.get(_sb_pk) or {}).get("fire_latency"),
                            entry_price_source=_sb_entry_source,
                        )
                        _sb_st = EPIC_STATE.get(_sb_pk)
                        if _sb_st is not None:
                            _sb_st["signal_log_id"] = _sb_sl_id
                            _sb_st["decision_debug"] = dict(getattr(_sb_dec, "debug", None) or {})
                    except Exception as _sb_sl_exc:
                        logger.warning("[STRUCTURE_BREAK] signal_log.log_open failed (close-cb): %s", _sb_sl_exc)
        except Exception as _sb_disp:
            logger.error("[STRUCTURE_BREAK] close-cb dispatch wrapper failed: %s", _sb_disp, exc_info=True)

    def _on_5m_close_bb_bounce(self, payload: Dict[str, Any]) -> None:
        """Post-rebuild 5M close dispatch for GBPUSD_BB_BOUNCE.

        Replaces the tick-driven dispatch at the _on_ls_tick `_is_new_5m`
        path under BB_BOUNCE_CLOSE_DISPATCH_ENABLED=1. Runs from the
        candle_builder 5M close-callback chain AFTER regime_engine and
        htf_regime have rebuilt, so bars[-1] is always the just-closed
        bar regardless of whether the close was "tick-won" or
        "rebuild-won". Gated separately from the legacy block so the two
        paths never both dispatch on the same bar (the legacy block
        early-skips when this callback is registered). Mirror of
        _on_5m_close_structure_break (2026-06-16) — fixes the same race
        for BB_BOUNCE.
        """
        try:
            if (os.getenv("BB_BOUNCE_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() != "1":
                return
            sym_u = str(payload.get("symbol") or "").upper()
            if sym_u != "GBPUSD":
                return
            df = payload.get("df_5m")
            if df is None or len(df) < 21:
                return
            if _router_dispatch_enabled():
                return
            tick_state = self._latest_tick_state.get(sym_u)
            if not tick_state or not tick_state.get("epic"):
                logger.info("BB_BOUNCE_DISPATCH:skip no_tick_state symbol=%s", sym_u)
                return
            epic_s = str(tick_state["epic"])
            from gbpusd_bb_bounce import (
                strategy as _bbb_strat,
                ENABLED as _BBB_ENABLED,
                MODE_NAME_LONG as _BBB_MODE_L,
                MODE_NAME_SHORT as _BBB_MODE_S,
                Bar as _BBBBar,
            )
            if not _BBB_ENABLED:
                return
            # Ordering fix (2026-07-09): synchronise with the engine pool
            # worker for THIS bar so permits() reads post-transition state.
            regime_matrix.wait_for_bar(sym_u, payload.get("bucket_epoch"))
            if not regime_matrix.permits(sym_u, _BBB_MODE_L) and not regime_matrix.permits(sym_u, _BBB_MODE_S):
                regime_matrix.log_suppression(sym_u, "GBPUSD_BB_BOUNCE")
                return
            # Derive ts from the just-closed bar's CLOSE instant — bar OPEN
            # (bucket_epoch / candle.timestamp) plus the 5M bar duration
            # (300s). The strategy uses `ts` for `_in_window(ts)` (06:00-17:00
            # UTC trading window) and `is_in_release_window(ts)` (news
            # blackout); the tick path fed the wall-clock at the FIRST tick of
            # the new bucket (≈ bar close + delta), so we mirror that instant
            # here. Without the +300, the 05:55-open bar (closes 06:00) would
            # be skipped and the 16:55-open bar (closes 17:00) would be
            # evaluated — both inverse to the tick path. STRUCTURE_BREAK uses
            # bucket_epoch without the +300 because it has no _in_window check;
            # BB_BOUNCE has one, so we need bar-close parity here.
            _bucket_epoch = payload.get("bucket_epoch")
            if _bucket_epoch is not None:
                _ts_dt_bbb = datetime.fromtimestamp(float(_bucket_epoch) + 300.0, tz=timezone.utc)
            else:
                _candle = payload.get("candle") or {}
                _cts = _candle.get("timestamp")
                if isinstance(_cts, datetime):
                    _cts_aware = _cts if _cts.tzinfo else _cts.replace(tzinfo=timezone.utc)
                    _ts_dt_bbb = _cts_aware + timedelta(seconds=300)
                else:
                    # datetime.now(UTC) at this point is already ≈ bar close
                    # instant (CONS_END="1" arrives near minute :00), so no
                    # +300 offset here — keeps the fallback semantically right.
                    _ts_dt_bbb = datetime.now(timezone.utc)
            _ts_col_bbb = "time" if "time" in df.columns else "timestamp"
            def _row_ts_bbb(_r):
                v = _r[_ts_col_bbb]
                return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
            _last_bbb = min(60, len(df))
            _bbb_bars = [
                _BBBBar(
                    timestamp=_row_ts_bbb(df.iloc[-_last_bbb + j]),
                    open=float(df.iloc[-_last_bbb + j]["open"]),
                    high=float(df.iloc[-_last_bbb + j]["high"]),
                    low=float(df.iloc[-_last_bbb + j]["low"]),
                    close=float(df.iloc[-_last_bbb + j]["close"]),
                )
                for j in range(_last_bbb)
            ]
            _bbb_closes = [float(c) for c in df["close"].tolist()]
            try:
                _bbb_dec = _bbb_strat.evaluate(
                    symbol=sym_u, epic=epic_s,
                    ts=_ts_dt_bbb, bars=_bbb_bars,
                    closes_ind=_bbb_closes,
                    has_open_long=has_active_trade_for_mode(epic_s, _BBB_MODE_L),
                    has_open_short=has_active_trade_for_mode(epic_s, _BBB_MODE_S),
                )
            except Exception as _bbbe:
                logger.error("[BB_BOUNCE] evaluate failed (close-cb): %s", _bbbe, exc_info=True)
                _bbb_dec = None

            # Guards (mirrors tick-path autobot.py:4102-4138). current_mid is
            # the just-closed bar's close — the most recent confirmed price
            # at this dispatch point. Same semantics as the tick-path mid_f
            # for the levels_proximity / news_blackout / priced_in checks.
            _mid_for_guards = float(df["close"].iloc[-1])
            if _bbb_dec is not None and not regime_matrix.REGIME_MATRIX_ENABLED:
                # GUARDS observable-mode gated off under matrix per §D.
                try:
                    from guards import check_trade as _bbb_guards_check
                    _bbb_dir = str(getattr(_bbb_dec, "signal", "")).upper()
                    _bbb_entry_px = float(
                        getattr(_bbb_dec, "entry", _mid_for_guards) or _mid_for_guards
                    )
                    _bbb_sl_pips_g = float(getattr(_bbb_dec, "sl", 0) or 0)
                    _bbb_tp_pips_g = float(getattr(_bbb_dec, "tp", 0) or 0)
                    if _bbb_dir == "SELL":
                        _bbb_sl_px = _bbb_entry_px + _bbb_sl_pips_g
                        _bbb_tp_px = _bbb_entry_px - _bbb_tp_pips_g
                    else:
                        _bbb_sl_px = _bbb_entry_px - _bbb_sl_pips_g
                        _bbb_tp_px = _bbb_entry_px + _bbb_tp_pips_g
                    _bbb_g_blocked, _bbb_g_reason = _bbb_guards_check(
                        symbol=sym_u,
                        direction=_bbb_dir,
                        strategy_mode="GBPUSD_BB_BOUNCE",
                        intended_entry=_bbb_entry_px,
                        intended_sl=_bbb_sl_px,
                        intended_tp=_bbb_tp_px,
                        current_mid=_mid_for_guards,
                        df_5m=df,
                        pip_size=1.0,
                    )
                    if _bbb_g_blocked:
                        logger.info(
                            "[BB_BOUNCE] %s %s blocked by guards (close-cb): %s",
                            sym_u, _bbb_dir, _bbb_g_reason,
                        )
                        _bbb_dec = None
                except Exception as _bbb_g_exc:
                    logger.warning(
                        "[BB_BOUNCE] guard eval raised (close-cb): %s",
                        _bbb_g_exc, exc_info=True,
                    )

            if _bbb_dec is not None:
                _bbb_trade_result = execute_trade(_bbb_dec, epic_s)
                # Back-annotation (telemetry only) — mirrors tick-path
                # autobot.py:4151-4196. When execute_trade returns None,
                # capture the block stage/reason against the strategy's
                # forensic_fires row for forensic joining.
                if _bbb_trade_result is None:
                    try:
                        from trade_executor import (
                            consume_last_block_info as _bbb_consume_blk,
                        )
                        _bbb_blk = _bbb_consume_blk()
                        if _bbb_blk:
                            from forensic_logger import (
                                write_forensic_fire as _bbb_ff_write,
                            )
                            _bbb_ann_mode = (
                                _BBB_MODE_L
                                if str(getattr(_bbb_dec, "signal", "")).upper() == "BUY"
                                else _BBB_MODE_S
                            )
                            _bbb_ann_fbts = (
                                _bbb_bars[-1].timestamp.isoformat()
                                if _bbb_bars else ""
                            )
                            _bbb_ann_dir = str(getattr(_bbb_dec, "signal", "")) or ""
                            _bbb_ann_entry = float(
                                getattr(_bbb_dec, "entry", None) or 0.0
                            )
                            _bbb_ann_reason = {
                                "rule": _bbb_blk.get("stage", "unknown"),
                                "stage": _bbb_blk.get("stage", "unknown"),
                                "reason": _bbb_blk.get("reason", ""),
                                "block_stage": _bbb_blk.get("stage", "unknown"),
                                "block_reason": _bbb_blk.get("reason", ""),
                                "annotation": True,
                                "block_ts_ms": _bbb_blk.get("ts_ms"),
                            }
                            _bbb_ff_write(
                                strategy=_bbb_ann_mode,
                                direction=_bbb_ann_dir,
                                entry_price=_bbb_ann_entry,
                                fire_bar_ts=_bbb_ann_fbts,
                                snapshot_dict={},
                                block_reason=_bbb_ann_reason,
                                pair="GBPUSD",
                            )
                    except Exception as _bbb_ann_exc:  # noqa: BLE001
                        logger.debug(
                            "[BB_BOUNCE] block annotation write failed (close-cb): %s",
                            _bbb_ann_exc,
                        )
                # signal_log persistence — mirrors tick-path autobot.py:4203-4237.
                if isinstance(_bbb_trade_result, dict) and (
                    has_active_trade_for_mode(epic_s, _BBB_MODE_L)
                    or has_active_trade_for_mode(epic_s, _BBB_MODE_S)
                ):
                    try:
                        _bbb_mode = (_BBB_MODE_L
                                     if str(getattr(_bbb_dec, "signal", "")).upper() == "BUY"
                                     else _BBB_MODE_S)
                        _bbb_pk = _pos_key(epic_s, _bbb_mode)
                        _bbb_sl_id = str(uuid.uuid4())
                        _bbb_briefing = morning_briefing.get_briefing(sym_u) or {}
                        _bbb_entry = float(getattr(_bbb_dec, "entry", None) or 0.0)
                        _bbb_entry, _bbb_entry_source = _resolve_entry_price_and_source(_bbb_pk, _bbb_dec, _bbb_entry)
                        _bbb_deal_id = (
                            _bbb_trade_result.get("dealId")
                            or _bbb_trade_result.get("deal_id")
                            or (EPIC_STATE.get(_bbb_pk) or {}).get("dealId")
                        )
                        signal_logger.log_open(
                            trade_id=_bbb_sl_id,
                            epic=epic_s,
                            decision=_bbb_dec,
                            briefing=_bbb_briefing,
                            df_5m=df,
                            entry_price=_bbb_entry,
                            deal_id=_bbb_deal_id,
                            latency=(EPIC_STATE.get(_bbb_pk) or {}).get("fire_latency"),
                            entry_price_source=_bbb_entry_source,
                        )
                        _bbb_st = EPIC_STATE.get(_bbb_pk)
                        if _bbb_st is not None:
                            _bbb_st["signal_log_id"] = _bbb_sl_id
                            _bbb_st["decision_debug"] = dict(getattr(_bbb_dec, "debug", None) or {})
                    except Exception as _bbb_sl_exc:
                        logger.warning("[BB_BOUNCE] signal_log.log_open failed (close-cb): %s", _bbb_sl_exc)

                    # Multi-tier briefing-TP registration — mirrors tick-path
                    # autobot.py:4245-4265. RANGE_ROTATION single-exit scalp
                    # takes the register_bb_range_scalp path instead.
                    try:
                        _bbb_dbg_tp = getattr(_bbb_dec, "debug", None) or {}
                        _bbb_confirmed_entry = (
                            _bbb_trade_result.get("entry_price")
                            or (EPIC_STATE.get(_bbb_pk) or {}).get("entry_price")
                        )
                        _bbb_tp_entry = float(_bbb_confirmed_entry or _bbb_entry)
                        _bbb_signal = str(getattr(_bbb_dec, "signal", "")).upper()
                        if _bbb_dbg_tp.get("range_scalp"):
                            register_bb_range_scalp(
                                epic=_bbb_pk,
                                entry_price=_bbb_tp_entry,
                                direction=_bbb_signal,
                                opposite_band_price=float(
                                    _bbb_dbg_tp.get("range_scalp_opp_band") or 0.0
                                ),
                                pair=sym_u,
                            )
                        elif _bbb_dbg_tp.get("tp_plan") and _bbb_dbg_tp.get("briefing_levels") is not None:
                            trade_manager.setup_briefing_tp(
                                epic=_bbb_pk,
                                entry_price=_bbb_tp_entry,
                                direction=_bbb_signal,
                                briefing_levels=_bbb_dbg_tp["briefing_levels"],
                                pair=sym_u,
                            )
                    except Exception as _bbb_tp_err:
                        logger.error(
                            "[BB_BOUNCE] tier/scalp register failed (close-cb): %s",
                            _bbb_tp_err,
                        )
        except Exception as _bbb_disp:
            logger.error("[BB_BOUNCE] close-cb dispatch wrapper failed: %s", _bbb_disp, exc_info=True)

    def _on_5m_close_ema_pullback(self, payload: Dict[str, Any]) -> None:
        """Post-rebuild 5M close dispatch for GBPUSD_EMA_PULLBACK.

        Replaces the tick-driven dispatch at the _on_ls_tick `_is_new_5m`
        path under EMA_PULLBACK_CLOSE_DISPATCH_ENABLED=1. Runs from the
        candle_builder 5M close-callback chain AFTER regime_engine and
        htf_regime have rebuilt, so bars[-1] is always the just-closed
        bar regardless of whether the close was "tick-won" or
        "rebuild-won". Gated separately from the legacy block so the two
        paths never both dispatch on the same bar (the legacy block
        early-skips when this callback is registered). Mirror of
        _on_5m_close_bb_bounce (2026-06-29) — fixes the same race for
        EMA_PULLBACK.

        EMA_PULLBACK-specific notes vs. BB_BOUNCE:
          • The strategy maintains an in-memory armed-state machine on
            self._armed_machine[epic] (gbpusd_ema_pullback.py:705). The
            module-level `strategy` is a singleton (line 2148), so the
            tick path and this callback both call methods on the SAME
            instance — the arm dict is shared, not duplicated. The
            early-skip in the legacy block guarantees exactly ONE
            evaluate() per bar, so the machine arm/disarm transitions
            mutate exactly once per bar (under the callback, against
            the FRESH bars[-1] — which is the whole point of the fix).
          • The HTF telemetry snapshot (_ema_pb_htf_snapshot at
            gbpusd_ema_pullback.py:477) is called from inside
            _armed_machine_step on ARM and FIRE. It is module-level
            and uses a long-lived ThreadPoolExecutor with a 0.25s
            wall-time cap; the executor and cap are unaffected by
            dispatch source. The snapshot remains log-only and never
            gates the decision.
          • evaluate() takes highs_ind / lows_ind (full df warmup) in
            addition to closes_ind — TREND_ENTRY_GATE ADX-slope
            requires the full series, not just the last 60 bars
            (added 2026-06-25). Preserved here identically.
          • Post-decision pipeline differs from BB_BOUNCE: no
            guards.check_trade call (EMA_PULLBACK does not use the
            guards registry); no block-annotation forensic write; one
            extra step — exhaustion telemetry capture between
            signal_log.log_open and setup_briefing_tp.
        """
        try:
            if (os.getenv("EMA_PULLBACK_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() != "1":
                return
            sym_u = str(payload.get("symbol") or "").upper()
            if sym_u != "GBPUSD":
                return
            df = payload.get("df_5m")
            if df is None or len(df) < 21:
                return
            if _router_dispatch_enabled():
                return
            tick_state = self._latest_tick_state.get(sym_u)
            if not tick_state or not tick_state.get("epic"):
                logger.info("EMA_PULLBACK_DISPATCH:skip no_tick_state symbol=%s", sym_u)
                return
            epic_s = str(tick_state["epic"])
            from gbpusd_ema_pullback import (
                strategy as _ep_strat,
                ENABLED as _EP_ENABLED,
                MODE_NAME_LONG as _EP_MODE_L,
                MODE_NAME_SHORT as _EP_MODE_S,
                Bar as _EPBar,
            )
            # The module-level ENABLED is the legacy _detect path gate. The
            # armed machine has its own enable env (EMA_PB_ARMED_MACHINE_
            # ENABLED) and evaluate() runs when EITHER is on (strategy
            # line 1581). Mirror that here so the callback fires whenever
            # evaluate() would have fired on the tick path. If both gates
            # are off, evaluate() will early-return None anyway, but we
            # spare the work.
            try:
                from gbpusd_ema_pullback import EMA_PB_ARMED_MACHINE_ENABLED as _EP_ARM_ENABLED
            except Exception:
                _EP_ARM_ENABLED = False
            if not (_EP_ENABLED or _EP_ARM_ENABLED):
                return
            # Ordering fix (2026-07-09): synchronise with the engine pool
            # worker for THIS bar so permits() reads post-transition state.
            regime_matrix.wait_for_bar(sym_u, payload.get("bucket_epoch"))
            if not regime_matrix.permits(sym_u, _EP_MODE_L) and not regime_matrix.permits(sym_u, _EP_MODE_S):
                regime_matrix.log_suppression(sym_u, "GBPUSD_EMA_PULLBACK")
                return
            # Derive ts from the just-closed bar's CLOSE instant — bar OPEN
            # (bucket_epoch / candle.timestamp) plus the 5M bar duration
            # (300s). The strategy uses `ts` for `_in_window(ts)` (06:00-17:00
            # UTC trading window, line 1587), `_is_pre_news_blackout(ts)`
            # (line 1663), `is_in_release_window(ts)` (line 1673), and
            # `_cooldown_ok(epic, ts)` (line 1620). The tick path fed the
            # wall-clock at the FIRST tick of the new bucket (≈ bar close +
            # delta), so we mirror that instant here. Same +300 boundary fix
            # as bb_bounce (commit 3672512).
            _bucket_epoch = payload.get("bucket_epoch")
            if _bucket_epoch is not None:
                _ts_dt_ep = datetime.fromtimestamp(float(_bucket_epoch) + 300.0, tz=timezone.utc)
            else:
                _candle = payload.get("candle") or {}
                _cts = _candle.get("timestamp")
                if isinstance(_cts, datetime):
                    _cts_aware = _cts if _cts.tzinfo else _cts.replace(tzinfo=timezone.utc)
                    _ts_dt_ep = _cts_aware + timedelta(seconds=300)
                else:
                    # datetime.now(UTC) at this point is already ≈ bar close
                    # instant (CONS_END="1" arrives near minute :00), so no
                    # +300 offset here — keeps the fallback semantically right.
                    _ts_dt_ep = datetime.now(timezone.utc)
            _ts_col_ep = "time" if "time" in df.columns else "timestamp"
            def _row_ts_ep(_r):
                v = _r[_ts_col_ep]
                return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
            _last_ep = min(60, len(df))
            _ep_bars = [
                _EPBar(
                    timestamp=_row_ts_ep(df.iloc[-_last_ep + j]),
                    open=float(df.iloc[-_last_ep + j]["open"]),
                    high=float(df.iloc[-_last_ep + j]["high"]),
                    low=float(df.iloc[-_last_ep + j]["low"]),
                    close=float(df.iloc[-_last_ep + j]["close"]),
                )
                for j in range(_last_ep)
            ]
            _ep_closes = [float(c) for c in df["close"].tolist()]
            # Full df highs/lows for TREND_ENTRY_GATE ADX-slope leg
            # (added 2026-06-25). With only the last 60 _ep_bars,
            # ADX-slope sign flips at the seed-bias level on real
            # fills — must use full df warmup for parity.
            _ep_highs = [float(h) for h in df["high"].tolist()]
            _ep_lows = [float(l) for l in df["low"].tolist()]
            # Single per-bar ADX source for the VWAP-stretch brake
            # (2026-07-22). Called AFTER wait_for_bar() so
            # regime_engine.latest_result() is fresh for this bar. Same
            # sourced (adx, source) tuple is fed to every dispatch path
            # via the strategy's evaluate() kwargs — one call, one
            # value, no per-strategy re-source.
            _ep_brake_adx, _ep_brake_adx_src = _source_brake_adx_at_bar(sym_u, _ts_dt_ep)
            try:
                _ep_dec = _ep_strat.evaluate(
                    symbol=sym_u, epic=epic_s,
                    ts=_ts_dt_ep, bars=_ep_bars,
                    closes_ind=_ep_closes,
                    highs_ind=_ep_highs,
                    lows_ind=_ep_lows,
                    has_open_long=has_active_trade_for_mode(epic_s, _EP_MODE_L),
                    has_open_short=has_active_trade_for_mode(epic_s, _EP_MODE_S),
                    brake_adx_at_bar=_ep_brake_adx,
                    brake_adx_source=_ep_brake_adx_src,
                )
            except Exception as _epe:
                logger.error("[EMA_PULLBACK] evaluate failed (close-cb): %s", _epe, exc_info=True)
                _ep_dec = None

            if _ep_dec is not None:
                _ep_trade_result = execute_trade(_ep_dec, epic_s)
                # signal_log persistence — mirrors tick-path autobot.py:4480-4514.
                if isinstance(_ep_trade_result, dict) and (
                    has_active_trade_for_mode(epic_s, _EP_MODE_L)
                    or has_active_trade_for_mode(epic_s, _EP_MODE_S)
                ):
                    try:
                        _ep_mode = (_EP_MODE_L
                                    if str(getattr(_ep_dec, "signal", "")).upper() == "BUY"
                                    else _EP_MODE_S)
                        _ep_pk = _pos_key(epic_s, _ep_mode)
                        _ep_sl_id = str(uuid.uuid4())
                        _ep_briefing = morning_briefing.get_briefing(sym_u) or {}
                        _ep_entry = float(getattr(_ep_dec, "entry", None) or 0.0)
                        _ep_entry, _ep_entry_source = _resolve_entry_price_and_source(_ep_pk, _ep_dec, _ep_entry)
                        _ep_deal_id = (
                            _ep_trade_result.get("dealId")
                            or _ep_trade_result.get("deal_id")
                            or (EPIC_STATE.get(_ep_pk) or {}).get("dealId")
                        )
                        signal_logger.log_open(
                            trade_id=_ep_sl_id,
                            epic=epic_s,
                            decision=_ep_dec,
                            briefing=_ep_briefing,
                            df_5m=df,
                            entry_price=_ep_entry,
                            deal_id=_ep_deal_id,
                            latency=(EPIC_STATE.get(_ep_pk) or {}).get("fire_latency"),
                            entry_price_source=_ep_entry_source,
                        )
                        _ep_st = EPIC_STATE.get(_ep_pk)
                        if _ep_st is not None:
                            _ep_st["signal_log_id"] = _ep_sl_id
                            _ep_st["decision_debug"] = dict(getattr(_ep_dec, "debug", None) or {})
                    except Exception as _ep_sl_exc:
                        logger.warning("[EMA_PULLBACK] signal_log.log_open failed (close-cb): %s", _ep_sl_exc)

                    # Exhaustion telemetry — capture-only, gates nothing.
                    # Default OFF; only fires when
                    # EMA_PULLBACK_EXHAUSTION_TELEMETRY_ENABLED=1. Mirrors
                    # tick-path autobot.py:4519-4538.
                    try:
                        import ema_pullback_exhaustion as _ep_exh
                        if _ep_exh.is_enabled():
                            from pair_config import get_ppp as _ep_exh_ppp
                            _ep_exh.log_fire(
                                trade_id=_ep_sl_id,
                                deal_id=_ep_deal_id,
                                epic=epic_s,
                                symbol=sym_u,
                                direction=str(getattr(_ep_dec, "signal", "") or ""),
                                fire_ts_utc=_ts_dt_ep,
                                df_5m=df,
                                pip_size=_ep_exh_ppp(epic_s),
                                decision_debug=getattr(_ep_dec, "debug", None) or {},
                            )
                    except Exception as _ep_exh_exc:
                        logger.debug(
                            "[EMA_PULLBACK] exhaustion telemetry failed (close-cb): %s",
                            _ep_exh_exc,
                        )

                    # Multi-tier briefing-TP registration — mirrors tick-path
                    # autobot.py:4540-4560.
                    try:
                        _ep_dbg_tp = getattr(_ep_dec, "debug", None) or {}
                        if _ep_dbg_tp.get("tp_plan") and _ep_dbg_tp.get("briefing_levels") is not None:
                            _ep_confirmed_entry = (
                                _ep_trade_result.get("entry_price")
                                or (EPIC_STATE.get(_ep_pk) or {}).get("entry_price")
                            )
                            _ep_tp_entry = float(_ep_confirmed_entry or _ep_entry)
                            _ep_signal = str(getattr(_ep_dec, "signal", "")).upper()
                            trade_manager.setup_briefing_tp(
                                epic=_ep_pk,
                                entry_price=_ep_tp_entry,
                                direction=_ep_signal,
                                briefing_levels=_ep_dbg_tp["briefing_levels"],
                                pair=sym_u,
                            )
                    except Exception as _ep_tp_err:
                        logger.error(
                            "[EMA_PULLBACK] setup_briefing_tp failed (close-cb): %s",
                            _ep_tp_err,
                        )
        except Exception as _ep_disp:
            logger.error("[EMA_PULLBACK] close-cb dispatch wrapper failed: %s", _ep_disp, exc_info=True)

    def _on_5m_close_bb_rev_pat(self, payload: Dict[str, Any]) -> None:
        """Post-rebuild 5M close dispatch for GBPUSD_BB_REV_PAT (V+Arc).

        Replaces the tick-driven dispatch at the _on_ls_tick `_is_new_5m`
        path under BB_REV_PAT_CLOSE_DISPATCH_ENABLED=1. Runs from the
        candle_builder 5M close-callback chain AFTER regime_engine and
        htf_regime have rebuilt, so bars[-1] is always the just-closed
        bar regardless of whether the close was "tick-won" or
        "rebuild-won". Gated separately from the legacy block so the two
        paths never both dispatch on the same bar (the legacy block
        early-skips when this callback is registered). Mirror of
        _on_5m_close_bb_bounce (2026-06-29) — fixes the same race for
        BB_REV_PAT.

        BB_REV_PAT-specific notes:
          • The strategy is stateless beyond a per-epic `_last_eval_bar`
            dedup (gbpusd_bb_reversal_patterns.py:442, 484-487) — same
            bar timestamp on a second `evaluate()` returns None. The
            early-skip is the primary one-path-per-bar guarantee; the
            dedup is belt-and-braces in case of any future call-graph
            change.
          • The strategy gates on `_in_window(ts)` (06:00-17:00 UTC,
            line 473) and `_is_pre_news_blackout(ts)` (line 543), so the
            +300s bar-CLOSE ts is required to match the tick path's
            wall-clock-at-first-tick semantics — identical reasoning to
            the bb_bounce 3672512 fix.
          • Post-decision pipeline: execute_trade → signal_log.log_open
            → setup_briefing_tp. No guards.check_trade and no
            block-annotation (BB_REV_PAT does not use guards on the
            tick path; preserved as-is).
        """
        try:
            if (os.getenv("BB_REV_PAT_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() != "1":
                return
            sym_u = str(payload.get("symbol") or "").upper()
            if sym_u != "GBPUSD":
                return
            df = payload.get("df_5m")
            if df is None or len(df) < 21:
                return
            if _router_dispatch_enabled():
                return
            tick_state = self._latest_tick_state.get(sym_u)
            if not tick_state or not tick_state.get("epic"):
                logger.info("BB_REV_PAT_DISPATCH:skip no_tick_state symbol=%s", sym_u)
                return
            epic_s = str(tick_state["epic"])
            from gbpusd_bb_reversal_patterns import (
                strategy as _brp_strat,
                ENABLED as _BRP_ENABLED,
                MODE_NAME_LONG as _BRP_MODE_L,
                MODE_NAME_SHORT as _BRP_MODE_S,
                Bar as _BRPBar,
            )
            if not _BRP_ENABLED:
                return
            # Ordering fix (2026-07-09): synchronise with the engine pool
            # worker for THIS bar so permits() reads post-transition state.
            regime_matrix.wait_for_bar(sym_u, payload.get("bucket_epoch"))
            if not regime_matrix.permits(sym_u, _BRP_MODE_L) and not regime_matrix.permits(sym_u, _BRP_MODE_S):
                regime_matrix.log_suppression(sym_u, "GBPUSD_BB_REV_PAT")
                return
            # Derive ts from the just-closed bar's CLOSE instant — bar OPEN
            # (bucket_epoch / candle.timestamp) plus the 5M bar duration
            # (300s). The strategy uses `ts` for `_in_window(ts)` (06:00-
            # 17:00 UTC) and `_is_pre_news_blackout(ts)`. Same +300
            # boundary fix as bb_bounce (3672512) and ema_pullback
            # (f69d971).
            _bucket_epoch = payload.get("bucket_epoch")
            if _bucket_epoch is not None:
                _ts_dt_brp = datetime.fromtimestamp(float(_bucket_epoch) + 300.0, tz=timezone.utc)
            else:
                _candle = payload.get("candle") or {}
                _cts = _candle.get("timestamp")
                if isinstance(_cts, datetime):
                    _cts_aware = _cts if _cts.tzinfo else _cts.replace(tzinfo=timezone.utc)
                    _ts_dt_brp = _cts_aware + timedelta(seconds=300)
                else:
                    # datetime.now(UTC) at this point is already ≈ bar
                    # close instant (CONS_END="1" arrives near minute :00),
                    # so no +300 offset here.
                    _ts_dt_brp = datetime.now(timezone.utc)
            _ts_col_brp = "time" if "time" in df.columns else "timestamp"
            def _row_ts_brp(_r):
                v = _r[_ts_col_brp]
                return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
            _last_brp = min(60, len(df))
            _brp_bars = [
                _BRPBar(
                    timestamp=_row_ts_brp(df.iloc[-_last_brp + j]),
                    open=float(df.iloc[-_last_brp + j]["open"]),
                    high=float(df.iloc[-_last_brp + j]["high"]),
                    low=float(df.iloc[-_last_brp + j]["low"]),
                    close=float(df.iloc[-_last_brp + j]["close"]),
                )
                for j in range(_last_brp)
            ]
            _brp_closes = [float(c) for c in df["close"].tolist()]
            try:
                _brp_dec = _brp_strat.evaluate(
                    symbol=sym_u, epic=epic_s,
                    ts=_ts_dt_brp, bars=_brp_bars,
                    closes_ind=_brp_closes,
                    has_open_long=has_active_trade_for_mode(epic_s, _BRP_MODE_L),
                    has_open_short=has_active_trade_for_mode(epic_s, _BRP_MODE_S),
                )
            except Exception as _brpe:
                logger.error("[BB_REV_PAT] evaluate failed (close-cb): %s", _brpe, exc_info=True)
                _brp_dec = None

            if _brp_dec is not None:
                _brp_trade_result = execute_trade(_brp_dec, epic_s)
                # signal_log persistence — mirrors tick-path autobot.py:4348-4382.
                if isinstance(_brp_trade_result, dict) and (
                    has_active_trade_for_mode(epic_s, _BRP_MODE_L)
                    or has_active_trade_for_mode(epic_s, _BRP_MODE_S)
                ):
                    try:
                        _brp_mode = (_BRP_MODE_L
                                     if str(getattr(_brp_dec, "signal", "")).upper() == "BUY"
                                     else _BRP_MODE_S)
                        _brp_pk = _pos_key(epic_s, _brp_mode)
                        _brp_sl_id = str(uuid.uuid4())
                        _brp_briefing = morning_briefing.get_briefing(sym_u) or {}
                        _brp_entry = float(getattr(_brp_dec, "entry", None) or 0.0)
                        _brp_entry, _brp_entry_source = _resolve_entry_price_and_source(_brp_pk, _brp_dec, _brp_entry)
                        _brp_deal_id = (
                            _brp_trade_result.get("dealId")
                            or _brp_trade_result.get("deal_id")
                            or (EPIC_STATE.get(_brp_pk) or {}).get("dealId")
                        )
                        signal_logger.log_open(
                            trade_id=_brp_sl_id,
                            epic=epic_s,
                            decision=_brp_dec,
                            briefing=_brp_briefing,
                            df_5m=df,
                            entry_price=_brp_entry,
                            deal_id=_brp_deal_id,
                            latency=(EPIC_STATE.get(_brp_pk) or {}).get("fire_latency"),
                            entry_price_source=_brp_entry_source,
                        )
                        _brp_st = EPIC_STATE.get(_brp_pk)
                        if _brp_st is not None:
                            _brp_st["signal_log_id"] = _brp_sl_id
                            _brp_st["decision_debug"] = dict(getattr(_brp_dec, "debug", None) or {})
                    except Exception as _brp_sl_exc:
                        logger.warning("[BB_REV_PAT] signal_log.log_open failed (close-cb): %s", _brp_sl_exc)

                    # Multi-tier briefing-TP registration — mirrors tick-path
                    # autobot.py:4384-4404.
                    try:
                        _brp_dbg_tp = getattr(_brp_dec, "debug", None) or {}
                        if _brp_dbg_tp.get("tp_plan") and _brp_dbg_tp.get("briefing_levels") is not None:
                            _brp_confirmed_entry = (
                                _brp_trade_result.get("entry_price")
                                or (EPIC_STATE.get(_brp_pk) or {}).get("entry_price")
                            )
                            _brp_tp_entry = float(_brp_confirmed_entry or _brp_entry)
                            _brp_signal = str(getattr(_brp_dec, "signal", "")).upper()
                            trade_manager.setup_briefing_tp(
                                epic=_brp_pk,
                                entry_price=_brp_tp_entry,
                                direction=_brp_signal,
                                briefing_levels=_brp_dbg_tp["briefing_levels"],
                                pair=sym_u,
                            )
                    except Exception as _brp_tp_err:
                        logger.error(
                            "[BB_REV_PAT] setup_briefing_tp failed (close-cb): %s",
                            _brp_tp_err,
                        )
        except Exception as _brp_disp:
            logger.error("[BB_REV_PAT] close-cb dispatch wrapper failed: %s", _brp_disp, exc_info=True)

    def _on_5m_close_confirmation_fallback(self, payload: Dict[str, Any]) -> None:
        """Post-rebuild 5M close dispatch for GBPUSD_CONFIRMATION_FALLBACK.

        Replaces the tick-driven dispatch at the _on_ls_tick `_is_new_5m`
        path under CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED=1. Runs
        from the candle_builder 5M close-callback chain AFTER
        regime_engine and htf_regime have rebuilt, so bars[-1] is always
        the just-closed bar. Mirror of _on_5m_close_bb_rev_pat
        (2026-06-29) — fixes the same race for CONFIRMATION_FALLBACK.

        ALSO completes the post-decision pipeline. The legacy tick block
        only called execute_trade and missed signal_log.log_open /
        setup_briefing_tp / EPIC_STATE writes — so live fires never
        appeared in signal_log.jsonl. This callback writes all three,
        matching bb_rev_pat / bb_bounce.

        CONFIRMATION_FALLBACK-specific notes:
          • Stateful sequencer. The strategy maintains
            self._armed[epic] (sweep→reclaim→confirm phase + level/
            extreme/timestamps) across up to SEQUENCE_MAX_BARS=6 bars,
            plus self._last_eval_bar (per-bar dedup) and
            self._last_fire_bar (cooldown) — all on the singleton
            (gbpusd_confirmation_fallback.py:298, 669). The legacy
            tick path and this callback resolve to the same singleton
            and therefore the same _armed dict. The early-skip below
            is the primary one-path-per-bar guarantee; the strategy's
            own _last_eval_bar dedup at line 425-428 is belt-and-
            braces.
          • Gates on _in_window(ts) (06:00-17:00 UTC, line 414) and
            _news_blackout(ts) (line 446), so the +300s bar-CLOSE ts
            is required to match the tick path's wall-clock-at-first-
            tick semantics — same +300 fix as bb_bounce 3672512.
          • The CONFIRMATION_FALLBACK_ENABLED flag is honored INSIDE
            this callback (lazy import + `if not _CF_ENABLED: return`)
            identical to the legacy block. With the enable flag at its
            current value (unset/0), this callback is a no-op even
            when registered — the migration prepares the strategy
            without flipping it on.
          • SL floor (MIN_SL_PIPS=12.0) is enforced INSIDE
            evaluate() at gbpusd_confirmation_fallback.py:571
            (`sl_pips = max(MIN_SL_PIPS, min(MAX_SL_PIPS, raw_sl_pips))`)
            — applies regardless of dispatch path; this callback
            does not bypass it.
          • Post-decision pipeline now MATCHES bb_rev_pat:
            execute_trade → signal_log.log_open → EPIC_STATE writes
            → setup_briefing_tp (conditional on debug["tp_plan"] +
            briefing_levels, harmless when CF doesn't carry those).
            No guards.check_trade, no block-annotation (CF doesn't
            use those — preserved absence).
        """
        try:
            if (os.getenv("CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() != "1":
                return
            sym_u = str(payload.get("symbol") or "").upper()
            if sym_u != "GBPUSD":
                return
            df = payload.get("df_5m")
            if df is None or len(df) < 30:
                return
            if _router_dispatch_enabled():
                return
            tick_state = self._latest_tick_state.get(sym_u)
            if not tick_state or not tick_state.get("epic"):
                logger.info("CONFIRMATION_FALLBACK_DISPATCH:skip no_tick_state symbol=%s", sym_u)
                return
            epic_s = str(tick_state["epic"])
            from gbpusd_confirmation_fallback import (
                strategy as _cf_strat,
                ENABLED as _CF_ENABLED,
                MODE_NAME_LONG as _CF_MODE_L,
                MODE_NAME_SHORT as _CF_MODE_S,
                Bar as _CFBar,
            )
            if not _CF_ENABLED:
                return
            # Ordering fix (2026-07-09): synchronise with the engine pool
            # worker for THIS bar so permits() reads post-transition state.
            regime_matrix.wait_for_bar(sym_u, payload.get("bucket_epoch"))
            if not regime_matrix.permits(sym_u, _CF_MODE_L) and not regime_matrix.permits(sym_u, _CF_MODE_S):
                regime_matrix.log_suppression(sym_u, "GBPUSD_CONFIRMATION_FALLBACK")
                return
            # Derive ts from the just-closed bar's CLOSE instant — bar OPEN
            # (bucket_epoch / candle.timestamp) plus 5M bar duration
            # (300s). Strategy uses ts for _in_window and _news_blackout.
            # Same +300 boundary fix as bb_bounce (3672512).
            _bucket_epoch = payload.get("bucket_epoch")
            if _bucket_epoch is not None:
                _ts_dt_cf = datetime.fromtimestamp(float(_bucket_epoch) + 300.0, tz=timezone.utc)
            else:
                _candle = payload.get("candle") or {}
                _cts = _candle.get("timestamp")
                if isinstance(_cts, datetime):
                    _cts_aware = _cts if _cts.tzinfo else _cts.replace(tzinfo=timezone.utc)
                    _ts_dt_cf = _cts_aware + timedelta(seconds=300)
                else:
                    _ts_dt_cf = datetime.now(timezone.utc)
            _ts_col_cf = "time" if "time" in df.columns else "timestamp"
            def _row_ts_cf(_r):
                v = _r[_ts_col_cf]
                return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
            _last_cf = min(60, len(df))
            _cf_bars = [
                _CFBar(
                    timestamp=_row_ts_cf(df.iloc[-_last_cf + j]),
                    open=float(df.iloc[-_last_cf + j]["open"]),
                    high=float(df.iloc[-_last_cf + j]["high"]),
                    low=float(df.iloc[-_last_cf + j]["low"]),
                    close=float(df.iloc[-_last_cf + j]["close"]),
                )
                for j in range(_last_cf)
            ]
            try:
                _cf_dec = _cf_strat.evaluate(
                    symbol=sym_u, epic=epic_s,
                    ts=_ts_dt_cf, bars=_cf_bars,
                    has_open_long=has_active_trade_for_mode(epic_s, _CF_MODE_L),
                    has_open_short=has_active_trade_for_mode(epic_s, _CF_MODE_S),
                )
            except Exception as _cfe:
                logger.error("[CONFIRMATION_FALLBACK] evaluate failed (close-cb): %s", _cfe, exc_info=True)
                _cf_dec = None

            if _cf_dec is not None:
                _cf_trade_result = execute_trade(_cf_dec, epic_s)
                # signal_log persistence — NEW in the callback (the legacy
                # tick block omitted this; live CF fires never appeared in
                # signal_log.jsonl). Mirror of bb_rev_pat's pipeline.
                if isinstance(_cf_trade_result, dict) and (
                    has_active_trade_for_mode(epic_s, _CF_MODE_L)
                    or has_active_trade_for_mode(epic_s, _CF_MODE_S)
                ):
                    try:
                        _cf_mode = (_CF_MODE_L
                                    if str(getattr(_cf_dec, "signal", "")).upper() == "BUY"
                                    else _CF_MODE_S)
                        _cf_pk = _pos_key(epic_s, _cf_mode)
                        _cf_sl_id = str(uuid.uuid4())
                        _cf_briefing = morning_briefing.get_briefing(sym_u) or {}
                        _cf_entry = float(getattr(_cf_dec, "entry", None) or 0.0)
                        _cf_entry, _cf_entry_source = _resolve_entry_price_and_source(_cf_pk, _cf_dec, _cf_entry)
                        _cf_deal_id = (
                            _cf_trade_result.get("dealId")
                            or _cf_trade_result.get("deal_id")
                            or (EPIC_STATE.get(_cf_pk) or {}).get("dealId")
                        )
                        signal_logger.log_open(
                            trade_id=_cf_sl_id,
                            epic=epic_s,
                            decision=_cf_dec,
                            briefing=_cf_briefing,
                            df_5m=df,
                            entry_price=_cf_entry,
                            deal_id=_cf_deal_id,
                            latency=(EPIC_STATE.get(_cf_pk) or {}).get("fire_latency"),
                            entry_price_source=_cf_entry_source,
                        )
                        _cf_st = EPIC_STATE.get(_cf_pk)
                        if _cf_st is not None:
                            _cf_st["signal_log_id"] = _cf_sl_id
                            _cf_st["decision_debug"] = dict(getattr(_cf_dec, "debug", None) or {})
                    except Exception as _cf_sl_exc:
                        logger.warning("[CONFIRMATION_FALLBACK] signal_log.log_open failed (close-cb): %s", _cf_sl_exc)

                    # Multi-tier briefing-TP registration — NEW in the
                    # callback. Harmless if the CF decision's debug dict
                    # doesn't carry tp_plan / briefing_levels (current
                    # behavior — see gbpusd_confirmation_fallback.py:630-
                    # 647 debug-dict shape); future-proof if the strategy
                    # later adds those keys.
                    try:
                        _cf_dbg_tp = getattr(_cf_dec, "debug", None) or {}
                        if _cf_dbg_tp.get("tp_plan") and _cf_dbg_tp.get("briefing_levels") is not None:
                            _cf_confirmed_entry = (
                                _cf_trade_result.get("entry_price")
                                or (EPIC_STATE.get(_cf_pk) or {}).get("entry_price")
                            )
                            _cf_tp_entry = float(_cf_confirmed_entry or _cf_entry)
                            _cf_signal = str(getattr(_cf_dec, "signal", "")).upper()
                            trade_manager.setup_briefing_tp(
                                epic=_cf_pk,
                                entry_price=_cf_tp_entry,
                                direction=_cf_signal,
                                briefing_levels=_cf_dbg_tp["briefing_levels"],
                                pair=sym_u,
                            )
                    except Exception as _cf_tp_err:
                        logger.error(
                            "[CONFIRMATION_FALLBACK] setup_briefing_tp failed (close-cb): %s",
                            _cf_tp_err,
                        )
        except Exception as _cf_disp:
            logger.error("[CONFIRMATION_FALLBACK] close-cb dispatch wrapper failed: %s", _cf_disp, exc_info=True)

    def _on_5m_close_trend_v3(self, payload: Dict[str, Any]) -> None:
        """5M close dispatch for GBPUSD_TREND_V3 (live, daily-spine trend).

        Runs AFTER regime_engine / htf_regime / structure_break / bb_bounce /
        ema_pullback / bb_rev_pat in the callback chain so:
          - regime_engine.latest_result(\"GBPUSD\") has just been refreshed
          - bars[-1] reflects the just-closed bar
          - TimeframeContext._d1_closed has been updated by _on_5m_close_tf

        Independent module — touches no other strategy state. Honors the
        TREND_V3_ENABLED env flag inside the strategy's evaluate(); when
        disabled this callback is a near-no-op (monitor_exits also early-
        exits). Two-step:
          1) monitor_exits() — close any TREND_V3 position whose exit fires
          2) evaluate() — fire a new entry when all gates hold
        """
        try:
            sym_u = str(payload.get("symbol") or "").upper()
            if sym_u != "GBPUSD":
                return
            df = payload.get("df_5m")
            if df is None or len(df) < 30:
                return
            tick_state = self._latest_tick_state.get(sym_u)
            if not tick_state or not tick_state.get("epic"):
                return
            epic_s = str(tick_state["epic"])
            from gbpusd_trend_v3 import (
                strategy as _tv3_strat,
                ENABLED as _TV3_ENABLED,
                MODE_NAME_LONG as _TV3_MODE_L,
                MODE_NAME_SHORT as _TV3_MODE_S,
                Bar as _TV3Bar,
                monitor_exits as _tv3_monitor_exits,
                on_open as _tv3_on_open,
            )
            if not _TV3_ENABLED:
                return
            # Ordering fix (2026-07-09): synchronise with the engine pool
            # worker for THIS bar so permits() reads post-transition state.
            regime_matrix.wait_for_bar(sym_u, payload.get("bucket_epoch"))
            if not regime_matrix.permits(sym_u, _TV3_MODE_L) and not regime_matrix.permits(sym_u, _TV3_MODE_S):
                regime_matrix.log_suppression(sym_u, "GBPUSD_TREND_V3")
                return

            _bucket_epoch = payload.get("bucket_epoch")
            if _bucket_epoch is not None:
                _ts_dt = datetime.fromtimestamp(float(_bucket_epoch) + 300.0, tz=timezone.utc)
            else:
                _candle = payload.get("candle") or {}
                _cts = _candle.get("timestamp")
                if isinstance(_cts, datetime):
                    _cts_aware = _cts if _cts.tzinfo else _cts.replace(tzinfo=timezone.utc)
                    _ts_dt = _cts_aware + timedelta(seconds=300)
                else:
                    _ts_dt = datetime.now(timezone.utc)
            _ts_col = "time" if "time" in df.columns else "timestamp"

            def _row_ts(_r):
                v = _r[_ts_col]
                return v.to_pydatetime() if hasattr(v, "to_pydatetime") else v

            _last_n = min(60, len(df))
            _bars = [
                _TV3Bar(
                    timestamp=_row_ts(df.iloc[-_last_n + j]),
                    open=float(df.iloc[-_last_n + j]["open"]),
                    high=float(df.iloc[-_last_n + j]["high"]),
                    low=float(df.iloc[-_last_n + j]["low"]),
                    close=float(df.iloc[-_last_n + j]["close"]),
                )
                for j in range(_last_n)
            ]
            _closes = [float(c) for c in df["close"].tolist()]

            # (1) Exit machine first
            try:
                _tv3_monitor_exits(symbol=sym_u, epic=epic_s, ts=_ts_dt,
                                   bars=_bars, closes_ind=_closes, df_5m=df)
            except Exception as _mx_exc:
                logger.warning("[TREND_V3] monitor_exits raised: %s", _mx_exc)

            # (2) Entry evaluate
            try:
                _dec = _tv3_strat.evaluate(
                    symbol=sym_u, epic=epic_s,
                    ts=_ts_dt, bars=_bars,
                    closes_ind=_closes,
                    df_5m=df,
                    has_open_long=has_active_trade_for_mode(epic_s, _TV3_MODE_L),
                    has_open_short=has_active_trade_for_mode(epic_s, _TV3_MODE_S),
                )
            except Exception as _ev_exc:
                logger.error("[TREND_V3] evaluate failed: %s", _ev_exc, exc_info=True)
                _dec = None
            if _dec is None:
                return

            _mid = float(df["close"].iloc[-1])
            _guards_gated = regime_matrix.REGIME_MATRIX_ENABLED
            try:
                if _guards_gated:
                    raise ImportError("guards observable gated off under matrix (§D)")
                from guards import check_trade as _g_check
                _dir = str(getattr(_dec, "signal", "")).upper()
                _entry = float(getattr(_dec, "entry", _mid) or _mid)
                _sl_p = float(getattr(_dec, "sl", 0) or 0)
                _tp_p = float(getattr(_dec, "tp", 0) or 0)
                if _dir == "SELL":
                    _sl_px = _entry + _sl_p
                    _tp_px = _entry - _tp_p
                else:
                    _sl_px = _entry - _sl_p
                    _tp_px = _entry + _tp_p
                _blk, _why = _g_check(
                    symbol=sym_u, direction=_dir, strategy_mode="GBPUSD_TREND_V3",
                    intended_entry=_entry, intended_sl=_sl_px, intended_tp=_tp_px,
                    current_mid=_mid, df_5m=df, pip_size=1.0,
                )
                if _blk:
                    logger.info("[TREND_V3] %s blocked by guards: %s", _dir, _why)
                    return
            except Exception as _g_exc:
                logger.warning("[TREND_V3] guard eval raised: %s", _g_exc, exc_info=True)

            _result = execute_trade(_dec, epic_s)
            if not isinstance(_result, dict):
                return
            _mode = _TV3_MODE_L if str(getattr(_dec, "signal", "")).upper() == "BUY" else _TV3_MODE_S
            _pk = _pos_key(epic_s, _mode)
            _confirmed_entry = (
                _result.get("entry_price")
                or (EPIC_STATE.get(_pk) or {}).get("entry_price")
                or _entry
            )
            # Register the open-position state for the exit machine
            try:
                _tv3_on_open(epic=epic_s, pos_key=_pk,
                             decision_debug=getattr(_dec, "debug", None) or {},
                             confirmed_entry=float(_confirmed_entry),
                             bar_ts=_bars[-1].timestamp)
            except Exception as _oo_exc:
                logger.warning("[TREND_V3] on_open raised: %s", _oo_exc)

            # signal_log persistence — mirrors BB_BOUNCE path
            try:
                _sl_id = str(uuid.uuid4())
                _br = morning_briefing.get_briefing(sym_u) or {}
                signal_logger.log_open(
                    trade_id=_sl_id,
                    epic=epic_s,
                    decision=_dec,
                    briefing=_br,
                    df_5m=df,
                    entry_price=float(_confirmed_entry),
                    deal_id=(_result.get("dealId") or _result.get("deal_id")
                             or (EPIC_STATE.get(_pk) or {}).get("dealId")),
                    latency=(EPIC_STATE.get(_pk) or {}).get("fire_latency"),
                    entry_price_source="trade_executor.confirmed",
                )
                _st = EPIC_STATE.get(_pk)
                if _st is not None:
                    _st["signal_log_id"] = _sl_id
                    _st["decision_debug"] = dict(getattr(_dec, "debug", None) or {})
            except Exception as _sl_exc:
                logger.warning("[TREND_V3] signal_log.log_open failed: %s", _sl_exc)
        except Exception as _tv3_disp:
            logger.error("[TREND_V3] close-cb dispatch wrapper failed: %s", _tv3_disp, exc_info=True)

    def _heartbeat_loop(self, stop_evt: threading.Event):
        while not stop_evt.is_set():
            parts = []
            now = time.time()
            for sym in sorted(self.epic_map.keys()):
                age = int(now - self._tick_last_seen_ts.get(sym, now))
                parts.append(f"{sym}:{age}s")

            cd_parts = []
            for sym, ep in self.epic_map.items():
                last_ts = self._get_last_trade_ts(sym, ep)
                ready, remaining = _cooldown_ready(last_ts)
                cd_parts.append(f"{sym}:{'READY' if ready else f'{remaining:.0f}s'}")

            logger.info(f"💓 AutoBot running — tick age: {' | '.join(parts)} | Cooldown: {' | '.join(cd_parts)}")
            time.sleep(max(5, HEARTBEAT_SECONDS))


# ============================================================
# Main
# ============================================================

def _recover_mode_map_from_journal(epic_map: Dict[str, str]) -> Dict[str, str]:
    """
    Read today's sweep journal CSV and return a mapping of epic → mode for
    positions that were opened today and have not yet been closed.

    Used by startup reconciliation to restore the correct strategy mode so
    that trade_manager applies the right trail logic (sweep vs trend-follow).
    """
    import csv
    from datetime import date

    today = date.today().isoformat()
    journal_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "logs",
        f"sweep_journal_{today}.csv",
    )

    mode_map: Dict[str, str] = {}

    if not os.path.exists(journal_path):
        return mode_map

    known_epics = set(str(e) for e in epic_map.values())

    try:
        with open(journal_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                epic = str(row.get("epic") or "").strip()
                if not epic or epic not in known_epics:
                    continue
                taken = str(row.get("taken") or "").strip().lower()
                if taken != "true":
                    continue
                # A row represents an open position if exit_price and
                # close_reason are both blank.
                exit_price = str(row.get("exit_price") or "").strip()
                close_reason = str(row.get("close_reason") or "").strip()
                if exit_price or close_reason:
                    # This trade was closed — remove any prior open entry.
                    mode_map.pop(epic, None)
                    continue
                mode = str(row.get("mode") or "").strip()
                if mode:
                    mode_map[epic] = mode
    except Exception as e:
        logger.warning(f"[RECONCILE] Could not read journal for mode recovery: {e}")

    return mode_map


def _log_cache_banner() -> None:
    for symbol in sorted(EPIC_MAP.keys()):
        df, state, last_ts_iso, age_sec = _read_cache_df(symbol)
        rows = int(len(df)) if df is not None else 0
        if last_ts_iso and age_sec is not None:
            age_min = age_sec / 60.0
            logger.info(f"[CACHE-AGE] {symbol} rows={rows} last_ts={last_ts_iso} age={age_min:.1f}m state={state}")
        else:
            logger.info(f"[CACHE-AGE] {symbol} rows={rows} last_ts=None age=None state={state}")


# ============================================================
# Graceful shutdown
# ============================================================

_SHUTDOWN_REQUESTED = threading.Event()
_SHUTDOWN_TIMEOUT_SECS = int(float(os.getenv("SHUTDOWN_TIMEOUT_SECS", "30") or 30))

# When true, the shutdown handler closes every tracked open position before
# disconnecting Lightstreamer. Default OFF — flip only once IG's weekend
# position-retention behaviour is confirmed externally.
CLOSE_POSITIONS_ON_SHUTDOWN = (os.getenv("CLOSE_POSITIONS_ON_SHUTDOWN", "0") or "0").strip() == "1"
_SHUTDOWN_CLOSE_TIMEOUT_SECS = int(float(os.getenv("SHUTDOWN_CLOSE_TIMEOUT_SECS", "20") or 20))


def _install_shutdown_signal_handlers() -> None:
    """Register SIGTERM/SIGINT handlers that request orderly shutdown via
    _SHUTDOWN_REQUESTED. The main loop polls this event; cleanup runs in the
    finally block of main(). Signal handlers stay minimal — set the event,
    return. All real work happens in _run_graceful_shutdown under the
    watchdog timer."""
    def _handler(signum, _frame):
        try:
            name = _signal_mod.Signals(signum).name
        except Exception:
            name = f"signal#{signum}"
        if _SHUTDOWN_REQUESTED.is_set():
            logger.info(f"[SHUTDOWN] {name} received again — already shutting down")
            return
        logger.info(
            f"[SHUTDOWN] initiated at {datetime.now(timezone.utc).isoformat()} "
            f"(signal={name})"
        )
        _SHUTDOWN_REQUESTED.set()

    for _sig in (_signal_mod.SIGTERM, _signal_mod.SIGINT):
        try:
            _signal_mod.signal(_sig, _handler)
        except (ValueError, OSError) as _sig_err:
            logger.warning(f"[SHUTDOWN] could not install handler for {_sig!r}: {_sig_err}")


def _shutdown_close_positions(epic_map: Dict[str, str], *, timeout_secs: int) -> None:
    """Close every tracked open position via the existing executor path.
    Continues on per-position failure and stops when *timeout_secs* elapses —
    does not block the rest of shutdown. Gated by CLOSE_POSITIONS_ON_SHUTDOWN."""
    logger.info(
        f"[SHUTDOWN] CLOSE_POSITIONS_ON_SHUTDOWN=1 — closing tracked positions "
        f"(timeout={timeout_secs}s)"
    )
    deadline = time.monotonic() + float(timeout_secs)
    closed = 0
    errors = 0
    skipped = 0
    for _pair, _epic in (epic_map or {}).items():
        if time.monotonic() >= deadline:
            logger.warning("[SHUTDOWN] close deadline reached — remaining pairs skipped")
            break
        try:
            positions = get_all_positions_for_epic(str(_epic))
        except Exception as e:
            logger.warning(f"[SHUTDOWN] {_pair}/{_epic}: get_all_positions_for_epic failed: {e}")
            errors += 1
            continue
        if not positions:
            continue
        for _pk, _st in positions:
            if time.monotonic() >= deadline:
                skipped += 1
                continue
            _dealid = _st.get("dealId") or _st.get("deal_id") or "?"
            try:
                ok = close_position(pos_key=_pk, reason="WEEKEND_SHUTDOWN")
                # close_position returns True on success, None/False on failure.
                # PnL is logged separately by the on_trade_close callback.
                if ok:
                    logger.info(f"[SHUTDOWN] closed {_pair} dealId={_dealid}")
                    closed += 1
                else:
                    logger.warning(f"[SHUTDOWN] close returned falsy for {_pair} dealId={_dealid}")
                    errors += 1
            except Exception as e:
                logger.error(f"[SHUTDOWN] close failed {_pair} dealId={_dealid}: {e}")
                errors += 1
    logger.info(
        f"[SHUTDOWN] position-close summary: closed={closed} errors={errors} "
        f"skipped_on_timeout={skipped}"
    )


def _run_graceful_shutdown(controller, stop_evt, *, timeout_secs: int = _SHUTDOWN_TIMEOUT_SECS) -> None:
    """Orderly shutdown bounded by *timeout_secs*:
      1. Halt heartbeat + stop-event-gated loops.
      2. If CLOSE_POSITIONS_ON_SHUTDOWN=1 — close every tracked position
         (bounded by SHUTDOWN_CLOSE_TIMEOUT_SECS). Default OFF.
      3. Unsubscribe Lightstreamer + disconnect.
      4. Touch persistent state (rest_allowance) to confirm on-disk freshness.
      5. Log summary and return.

    Warm cache / candle archive / briefing tracker / sweep journal all write
    synchronously per event — no in-memory buffers to flush. If cleanup
    exceeds *timeout_secs*, a watchdog thread force-exits with [SHUTDOWN]
    timeout logged.
    """
    start_monotonic = time.monotonic()

    def _force_exit():
        logger.error(f"[SHUTDOWN] timeout after {timeout_secs}s — force exit")
        try:
            logging.shutdown()
        except Exception:
            pass
        os._exit(1)

    watchdog = threading.Timer(timeout_secs, _force_exit)
    watchdog.daemon = True
    watchdog.start()

    try:
        try:
            stop_evt.set()
        except Exception:
            pass

        if CLOSE_POSITIONS_ON_SHUTDOWN:
            try:
                _shutdown_close_positions(EPIC_MAP, timeout_secs=_SHUTDOWN_CLOSE_TIMEOUT_SECS)
            except Exception as e:
                logger.error(f"[SHUTDOWN] position-close phase raised: {e}", exc_info=True)

        if controller is not None:
            try:
                controller.stop()
                logger.info("[SHUTDOWN] Lightstreamer unsubscribed + disconnected")
            except Exception as e:
                logger.warning(f"[SHUTDOWN] LS stop failed: {e}")

        # LS-thread refactor: stop pair-workers + REST sweep daemon. Order
        # matters — LS is unsubscribed first so no new ticks arrive, then
        # the pair-workers drain in-flight queues, then the sweep daemon.
        try:
            import pair_workers
            pair_workers.stop_depth_gauge()
            pair_workers.shutdown_all(timeout=5.0)
        except Exception as e:
            logger.warning(f"[SHUTDOWN] pair_workers shutdown failed: {e}")
        try:
            import rest_sweeps
            rest_sweeps.stop_rest_sweep_daemon(timeout=5.0)
        except Exception as e:
            logger.warning(f"[SHUTDOWN] rest_sweeps shutdown failed: {e}")

        try:
            import rest_allowance as _ra
            _ra.reset_if_new_week()
            _st = _ra.get_state()
            logger.info(
                f"[SHUTDOWN] rest_allowance persisted: used={_st['points_used']} "
                f"budget={_st['points_budget']} remaining={_st['remaining']} "
                f"week_start={_st['week_start']}"
            )
        except Exception as e:
            logger.warning(f"[SHUTDOWN] rest_allowance touch failed: {e}")

        logger.info(
            "[SHUTDOWN] persistent writers (warm cache, candle archive, briefing tracker, "
            "sweep journal) write synchronously per event — no in-memory buffer to flush"
        )

        elapsed = time.monotonic() - start_monotonic
        watchdog.cancel()
        logger.info(f"[SHUTDOWN] complete in {elapsed:.2f}s — exiting 0")
    except Exception as e:
        logger.error(f"[SHUTDOWN] cleanup raised: {e}", exc_info=True)
        watchdog.cancel()


def main():
    if not CFD_EPIC_MAP:
        logger.error("❌ CFD_EPICS_JSON is not set. This bot requires CFD epics for REST preload.")
        raise SystemExit(2)

    # Filesystem preflight: create output dirs (correct ownership when we
    # can) and probe each one with a sentinel write. A permissions miss
    # here would cost us a trading session — fail loud at boot instead.
    ensure_output_directories()
    verify_output_directories_writable()

    _init_timeframe_context_or_die()

    # 2026-07-01: Fix module-identity split. This process runs as
    # `python autobot.py`, so this module is sys.modules['__main__'] and
    # its live `_TF_CTX` (just bound above) lives here. Strategy consumers
    # do `import autobot`, which was returning a SEPARATE sys.modules['autobot']
    # object where main() never ran and `_TF_CTX` was permanently None —
    # silently disabling the SB daily-filter and TREND_V3's daily-direction
    # spine (trend_v3.jsonl was 217/217 rows `err: tf_ctx_none`). Aliasing
    # both names to the same live module object routes all consumers to the
    # initialized `_TF_CTX`. Must come AFTER _init_timeframe_context_or_die
    # (so `_TF_CTX` is bound) and BEFORE any 5m-close callback registration.
    import sys as _sys
    _sys.modules["autobot"] = _sys.modules[__name__]

    ig, headers, account_id = get_ig_session()

    logger.info(f"===== 🔄 AUTOBOT STARTUP ({BOT_ID}) =====")
    logger.info("EPIC MAPPING (TRADING / TODAY):")
    for s, e in EPIC_MAP.items():
        logger.info(f"  {s} → {e}")

    logger.info("CFD EPIC MAPPING (PRELOAD ONLY):")
    for s, e in CFD_EPIC_MAP.items():
        logger.info(f"  {s} → {e}")

    _log_cache_banner()

    for s, e in EPIC_MAP.items():
        try:
            candle_builder.set_symbol_epic(s, e)
        except Exception:
            pass

    try:
        candle_builder.register_5m_close_callback(_on_5m_close_log)
    except Exception:
        try:
            candle_builder.set_on_5m_close_callback(_on_5m_close_log)
        except Exception:
            pass

    # Briefing invalidation check on every 5M close (all strategies).
    # Dispatched to a single-worker background thread so slow JSON/disk work
    # cannot stall the 5M close callback chain (candle-lag source).
    try:
        from trade_manager import check_briefing_invalidation
        from concurrent.futures import ThreadPoolExecutor
        _briefing_inv_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="briefing-inv")

        def _deferred_briefing_invalidation(payload):
            try:
                _briefing_inv_pool.submit(check_briefing_invalidation, payload)
            except Exception as _sub_err:
                logger.warning("[AUTOBOT] briefing invalidation submit failed: %s", _sub_err)

        candle_builder.register_5m_close_callback(_deferred_briefing_invalidation)
        logger.info("[AUTOBOT] Registered deferred briefing invalidation 5M callback")
    except Exception as _inv_reg_err:
        logger.warning("[AUTOBOT] Could not register invalidation callback: %s", _inv_reg_err)

    # 2026-07-27: universal exhaustion-gated runner momentum check.
    # Fires ONCE per 5M close per pair, iterates scaled-out runners across
    # all strategies (skips TREND_V3 — owns its own enforced path). Mode
    # via env RUNNER_MOMENTUM_CHECK_MODE = off|shadow|enforce (default
    # shadow — closes NOTHING, logs [RUNNER-MOMENTUM] verdicts only).
    # Registered here (not deferred) so it runs synchronously in the
    # close chain, consistent with TREND_V3's monitor_exits ordering.
    # Any exception is trapped inside check_universal_runner_momentum
    # itself (outer guard) — the callback never raises into the chain.
    try:
        from trade_manager import check_universal_runner_momentum
        candle_builder.register_5m_close_callback(check_universal_runner_momentum)
        logger.info(
            "[AUTOBOT] Registered universal runner-momentum 5M callback "
            "(RUNNER_MOMENTUM_CHECK_MODE=%s)",
            os.getenv("RUNNER_MOMENTUM_CHECK_MODE", "shadow"),
        )
    except Exception as _rm_reg_err:
        logger.warning(
            "[AUTOBOT] Could not register runner-momentum callback: %s",
            _rm_reg_err,
        )

    # Regime engine — scored regime classification on every 5M close.
    # Stage 3: emit() writes one telemetry line to logs/regime_engine.jsonl AND
    # returns the classification dict. When REGIME_ROUTER_ENGINE_ENABLED=1 the
    # same result is passed to regime_router_engine.dispatch() (ONE classify per
    # close → telemetry + router share one regime_instance_id, the OUTCOME-JOIN
    # key).
    # Dispatched to its OWN dedicated single-worker thread (a separate pool from
    # briefing-inv) so a slow regime emit can neither stall the 5M close callback
    # chain (candle-lag source) nor block invalidation work.
    try:
        import regime_engine
        import regime_router_engine
        from concurrent.futures import ThreadPoolExecutor
        _regime_engine_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="regime-engine")

        def _emit_then_route(sym, df_tail, payload, bucket_epoch):
            # try/finally guarantees the per-bar Event is set even if emit or
            # update raises — otherwise strategy wait_for_bar() would time out
            # every bar and drift to stale reads. Set it AFTER matrix.update()
            # on the happy path so strategies unblock on fresh state, not
            # pre-update state.
            result = None
            try:
                try:
                    result = regime_engine.emit(sym, df_tail)
                except Exception as _emit_exc:
                    logger.warning("[REGIME-ENGINE] emit raised for %s: %s", sym, _emit_exc)
                    return
                # Phase 2 regime matrix update — hysteresis + fast lane.
                # No-op when REGIME_MATRIX_ENABLED=0.
                try:
                    regime_matrix.update(
                        sym,
                        (result or {}).get("winning_regime"),
                        range_break_promoted=bool((result or {}).get("range_break_promoted", False)),
                        range_exit_breakout=bool((result or {}).get("range_exit_breakout", False)),
                        regime_label_path=(result or {}).get("regime_label_path"),
                        hist_freshness_fail_count=int((result or {}).get("hist_freshness_fail_count") or 0),
                        h1_decel_streak=int((result or {}).get("h1_decel_streak") or 0),
                    )
                except Exception as _mtx_exc:
                    logger.warning("[REGIME-MATRIX] update raised for %s: %s", sym, _mtx_exc)
                if str(os.getenv("REGIME_ROUTER_ENGINE_ENABLED", "0")).strip().lower() not in ("1", "true", "yes"):
                    return
                try:
                    regime_router_engine.dispatch(sym, payload, result)
                except Exception as _disp_exc:
                    logger.warning("[ROUTER] dispatch raised for %s (swallowed at callback): %s", sym, _disp_exc)
            finally:
                # Ordering fix (2026-07-09): unblock any strategy callback
                # waiting on wait_for_bar() for this (sym, bucket) — happy
                # path AND every error path. Never raises.
                try:
                    regime_matrix.mark_bar_processed(sym, bucket_epoch)
                except Exception:
                    pass

        def _on_5m_close_regime_engine(payload):
            sym = None
            bucket_epoch = None
            try:
                sym = payload.get("symbol")
                bucket_epoch = payload.get("bucket_epoch")
                df = payload.get("df_5m")
                if df is None or len(df) < 1:
                    logger.debug("[REGIME-ENGINE] %s: no df_5m on 5M close — skip", sym)
                    # No emit will run for this bar — unblock strategy waiters
                    # immediately so they don't sit on the 2s timeout for a bar
                    # that will never get an update.
                    regime_matrix.mark_bar_processed(sym, bucket_epoch)
                    return
                _regime_engine_pool.submit(_emit_then_route, sym, df.tail(30), payload, bucket_epoch)
            except Exception as _re_err:
                logger.warning("[REGIME-ENGINE] 5M close emit submit failed: %s", _re_err)
                # Submit failed → the pool worker will never run → unblock
                # strategy waiters here to avoid a fleet-wide 2s stall.
                try:
                    regime_matrix.mark_bar_processed(sym, bucket_epoch)
                except Exception:
                    pass

        candle_builder.register_5m_close_callback(_on_5m_close_regime_engine)
        logger.info("[AUTOBOT] Registered regime-engine 5M close callback (router_enabled=%s)",
                    os.getenv("REGIME_ROUTER_ENGINE_ENABLED", "0"))
    except Exception as _re_reg_err:
        logger.warning("[AUTOBOT] Could not register regime-engine callback: %s", _re_reg_err)

    # ── HTF regime layer (telemetry-only, kill-switch HTF_REGIME_ENABLED) ──
    # Higher-timeframe (H1/D1/W1) regime classifier sitting ABOVE the 5M
    # regime engine. Purely additive: reads from htf_cache, emits one JSONL
    # row per 5M close per active symbol. Does NOT gate, NOT route, NOT touch
    # strategies. Wrapped to swallow all exceptions at callback level so it
    # cannot disturb the close-callback chain.
    try:
        import htf_regime as _htf_regime
        from concurrent.futures import ThreadPoolExecutor as _HTFPool
        _htf_regime_pool = _HTFPool(max_workers=1, thread_name_prefix="htf-regime")

        def _emit_htf_regime(sym, bar_ts):
            try:
                _htf_regime.emit(sym, bar_ts)
            except Exception as _htf_exc:
                logger.warning("[HTF-REGIME] emit raised for %s: %s", sym, _htf_exc)

        def _on_5m_close_htf_regime(payload):
            try:
                sym = payload.get("symbol")
                if not sym:
                    return
                bar_ts = None
                df = payload.get("df_5m")
                if df is not None and len(df) >= 1:
                    try:
                        last = df.iloc[-1]
                        bar_ts = str(last.get("timestamp") or "") or None
                    except Exception:
                        bar_ts = None
                _htf_regime_pool.submit(_emit_htf_regime, sym, bar_ts)
            except Exception as _htf_reg_err:
                logger.warning("[HTF-REGIME] 5M close submit failed: %s", _htf_reg_err)

        candle_builder.register_5m_close_callback(_on_5m_close_htf_regime)
        logger.info(_htf_regime.startup_banner())
        try:
            import htf_authority as _htf_authority
            logger.info(_htf_authority.startup_banner())
        except Exception as _hauth_banner_exc:
            logger.warning("[AUTOBOT] htf_authority banner failed: %s",
                           _hauth_banner_exc)
        logger.info("[AUTOBOT] Registered HTF-regime 5M close callback (enabled=%s)",
                    os.getenv("HTF_REGIME_ENABLED", "0"))
    except Exception as _htf_reg_exc:
        logger.warning("[AUTOBOT] Could not register HTF-regime callback: %s",
                       _htf_reg_exc)

    # ── Confirmation-engine Phase-2 hook (telemetry-only, 2026-05-23) ──
    # On every 5m close, evaluate next_bar_continued for pending trades
    # that fired on the prior bar. ⚠️ FAIL-SAFE: wrapped at both the
    # callback and registration level — cannot raise into the close-
    # callback chain. The engine itself is GATES-NOTHING (no close calls,
    # no SL amends, no sizing) — read + log only.
    try:
        import confirmation_engine as _conf_eng

        def _on_5m_close_confirmation_phase2(payload):
            try:
                sym = payload.get("symbol")
                df = payload.get("df_5m")
                if sym is None or df is None or len(df) < 2:
                    return
                _conf_eng.evaluate_next_bar_on_close(sym, df)
            except Exception as _ce_err:
                logger.warning(
                    "[CONFIRMATION-ENGINE] Phase-2 callback raised "
                    "(swallowed; trade path unaffected): %s",
                    _ce_err,
                )

        candle_builder.register_5m_close_callback(_on_5m_close_confirmation_phase2)
        logger.info(
            "[AUTOBOT] Registered confirmation-engine Phase-2 5M close callback "
            "(enabled=%s)", os.getenv("CONFIRMATION_ENGINE_ENABLED", "1"),
        )
    except Exception as _ce_reg_err:
        logger.warning(
            "[AUTOBOT] Could not register confirmation-engine callback: %s",
            _ce_reg_err,
        )

    # regime_tree_shadow registration removed 2026-07-08 under Phase 2
    # deletion pass. Was shadow-only (write-only Sentinel feedstock);
    # DRIVES NOTHING at any flag value. Env REGIME_TREE_SHADOW_ENABLED
    # deleted from code. Module regime_tree_shadow.py remains on disk
    # for potential future revival but no longer wired.
    # Recon phase2_recon_2026-07-08.md Q1.6.

    # Startup Telegram notification is sent ONCE at the bottom of startup
    # (around autobot.py:5583, the "🚀 AutoBot startup complete" message
    # that includes pairs, briefings, and REST budget). The earlier
    # "AutoBot online" status check-in here was redundant — it fired
    # ~5s before the detailed message and resulted in two startup
    # Telegrams per restart. Removed 2026-05-27.
    bot = AutoBot(EPIC_MAP)

    # ── Structure-break post-rebuild 5M close dispatch (2026-06-16) ──
    # Register AFTER regime_engine (line ~5285) and htf_regime (line ~5325)
    # so bars[-1] reflects the just-closed bar. Gated by
    # STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED (default 1 = active here, with
    # the legacy tick-driven block early-skipping). Setting the env to 0
    # NOT registers this callback AND restores the legacy block — exactly
    # one dispatch path runs per bar.
    try:
        if (os.getenv("STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1":
            candle_builder.register_5m_close_callback(bot._on_5m_close_structure_break)
            logger.info(
                "[AUTOBOT] Registered structure_break 5M close callback "
                "(STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)"
            )
        else:
            logger.info(
                "[AUTOBOT] structure_break close-dispatch DISABLED "
                "(STRUCTURE_BREAK_CLOSE_DISPATCH_ENABLED=0, legacy tick path active)"
            )
    except Exception as _sb_cb_exc:
        logger.warning("[AUTOBOT] structure_break close-callback registration failed: %s", _sb_cb_exc)

    # ── BB_BOUNCE post-rebuild 5M close dispatch (2026-06-29) ──
    # Mirror of structure_break (2026-06-16). Registered AFTER regime_engine
    # and htf_regime so bars[-1] reflects the just-closed bar. Gated by
    # BB_BOUNCE_CLOSE_DISPATCH_ENABLED (default 1 = active here, with
    # the legacy tick-driven block early-skipping). Setting the env to 0
    # NOT registers this callback AND restores the legacy block — exactly
    # one dispatch path runs per bar.
    try:
        if (os.getenv("BB_BOUNCE_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1":
            candle_builder.register_5m_close_callback(bot._on_5m_close_bb_bounce)
            logger.info(
                "[AUTOBOT] Registered bb_bounce 5M close callback "
                "(BB_BOUNCE_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)"
            )
        else:
            logger.info(
                "[AUTOBOT] bb_bounce close-dispatch DISABLED "
                "(BB_BOUNCE_CLOSE_DISPATCH_ENABLED=0, legacy tick path active)"
            )
    except Exception as _bbb_cb_exc:
        logger.warning("[AUTOBOT] bb_bounce close-callback registration failed: %s", _bbb_cb_exc)

    # ── EMA_PULLBACK post-rebuild 5M close dispatch (2026-06-29) ──
    # Mirror of bb_bounce (commit cac2eb3 + 3672512). Registered AFTER
    # regime_engine and htf_regime so bars[-1] reflects the just-closed
    # bar and htf state is fresh by the time the armed-machine's HTF
    # telemetry snapshot fires. Gated by EMA_PULLBACK_CLOSE_DISPATCH_
    # ENABLED (default 1 = active here, with the legacy tick-driven
    # block early-skipping). Setting the env to 0 NOT registers this
    # callback AND restores the legacy block — exactly one dispatch
    # path runs per bar so the strategy's in-memory arm-state machine
    # (self._armed_machine) mutates exactly once per close.
    try:
        if (os.getenv("EMA_PULLBACK_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1":
            candle_builder.register_5m_close_callback(bot._on_5m_close_ema_pullback)
            logger.info(
                "[AUTOBOT] Registered ema_pullback 5M close callback "
                "(EMA_PULLBACK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)"
            )
        else:
            logger.info(
                "[AUTOBOT] ema_pullback close-dispatch DISABLED "
                "(EMA_PULLBACK_CLOSE_DISPATCH_ENABLED=0, legacy tick path active)"
            )
    except Exception as _ep_cb_exc:
        logger.warning("[AUTOBOT] ema_pullback close-callback registration failed: %s", _ep_cb_exc)

    # ── BB_REV_PAT (V+Arc) post-rebuild 5M close dispatch (2026-06-29) ──
    # Mirror of bb_bounce / ema_pullback. Registered AFTER regime_engine
    # and htf_regime so bars[-1] reflects the just-closed bar. Gated by
    # BB_REV_PAT_CLOSE_DISPATCH_ENABLED (default 1 = active here, with
    # the legacy tick-driven block early-skipping). Setting the env to 0
    # NOT registers this callback AND restores the legacy block — exactly
    # one dispatch path runs per bar. The strategy's own per-epic
    # `_last_eval_bar` dedup (gbpusd_bb_reversal_patterns.py:484-487)
    # is belt-and-braces in case both paths ever ran on the same bar.
    try:
        if (os.getenv("BB_REV_PAT_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1":
            candle_builder.register_5m_close_callback(bot._on_5m_close_bb_rev_pat)
            logger.info(
                "[AUTOBOT] Registered bb_rev_pat 5M close callback "
                "(BB_REV_PAT_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)"
            )
        else:
            logger.info(
                "[AUTOBOT] bb_rev_pat close-dispatch DISABLED "
                "(BB_REV_PAT_CLOSE_DISPATCH_ENABLED=0, legacy tick path active)"
            )
    except Exception as _brp_cb_exc:
        logger.warning("[AUTOBOT] bb_rev_pat close-callback registration failed: %s", _brp_cb_exc)

    # ── CONFIRMATION_FALLBACK post-rebuild 5M close dispatch (2026-06-29) ──
    # Mirror of bb_bounce / ema_pullback / bb_rev_pat. Registered AFTER
    # regime_engine and htf_regime so bars[-1] reflects the just-closed
    # bar AND the regime self-gate inside the strategy sees fresh state.
    # Gated by CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED (default 1 =
    # active here, with the legacy tick-driven block early-skipping).
    # Setting the env to 0 NOT registers this callback AND restores the
    # legacy block (with its half-wired pipeline) — exactly one dispatch
    # path runs per bar. The strategy's per-epic _armed sequencer state +
    # _last_eval_bar dedup share one singleton instance across paths;
    # the early-skip is the primary one-path-per-bar guarantee. The
    # strategy's CONFIRMATION_FALLBACK_ENABLED gate is honored INSIDE
    # the callback, so registering it while the enable flag is 0 (or
    # unset) is a no-op evaluate-wise — the migration prepares the
    # strategy without flipping it on.
    try:
        if (os.getenv("CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED", "1") or "1").strip() == "1":
            candle_builder.register_5m_close_callback(bot._on_5m_close_confirmation_fallback)
            logger.info(
                "[AUTOBOT] Registered confirmation_fallback 5M close callback "
                "(CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED=1, post-rebuild dispatch)"
            )
        else:
            logger.info(
                "[AUTOBOT] confirmation_fallback close-dispatch DISABLED "
                "(CONFIRMATION_FALLBACK_CLOSE_DISPATCH_ENABLED=0, legacy tick path active)"
            )
    except Exception as _cf_cb_exc:
        logger.warning("[AUTOBOT] confirmation_fallback close-callback registration failed: %s", _cf_cb_exc)

    # ── TREND_V3 5M close dispatch (2026-06-30) ─────────────────────────
    # New daily-spine trend strategy. Independent module — touches no other
    # strategy state. Registered AFTER regime_engine / htf_regime / BB_BOUNCE
    # so latest_result + bars[-1] + D1 list are all current at dispatch time.
    # The TREND_V3_ENABLED env flag is honored INSIDE the callback (lazy
    # import on the strategy's ENABLED constant), so registering it while
    # the flag is 0 is a no-op evaluate-wise.
    try:
        candle_builder.register_5m_close_callback(bot._on_5m_close_trend_v3)
        try:
            import gbpusd_trend_v3 as _tv3_mod
            logger.info(_tv3_mod.startup_banner())
        except Exception:
            pass
        logger.info(
            "[AUTOBOT] Registered TREND_V3 5M close callback (TREND_V3_ENABLED=%s)",
            os.getenv("TREND_V3_ENABLED", "0"),
        )
    except Exception as _tv3_cb_exc:
        logger.warning("[AUTOBOT] TREND_V3 close-callback registration failed: %s", _tv3_cb_exc)

    # ── BB_PIERCE_RECORDER — passive, zero trading impact ─────────────
    # Registered LAST so its 5M close callback runs AFTER every
    # strategy dispatch on the same bar. The recorder self-registers
    # on import (bb_pierce_recorder.start() at module bottom), so the
    # import statement here IS the wire-up. Wrapped so an import
    # failure never touches the trading loop. Kill-switch env:
    # BB_PIERCE_RECORDER_ENABLED (default 1).
    try:
        import bb_pierce_recorder as _bb_pierce_recorder  # noqa: F401
        logger.info(
            "[AUTOBOT] bb_pierce_recorder imported (ENABLED=%s)",
            os.getenv("BB_PIERCE_RECORDER_ENABLED", "1"),
        )
    except Exception as _bbpr_exc:
        logger.warning(
            "[AUTOBOT] bb_pierce_recorder import failed (recorder off, "
            "trading unaffected): %s",
            _bbpr_exc,
        )

    # (Removed 2026-04-30: rehydrate_session_entry_counts call site —
    # session-cap counter superseded by per-strategy concurrent cap, which
    # reads live position state from trade_executor.EPIC_STATE on each
    # dispatch and needs no rehydration on restart.)

    # Start exception monitor reporter — hourly Telegram alerts if any
    # strategy catch fired, daily summary at 00:00 UTC.
    try:
        import exception_monitor as _exmon
        _exmon.start()
        logger.info("[AUTOBOT] exception_monitor reporter started")
    except Exception as _exmon_exc:
        logger.warning("[AUTOBOT] exception_monitor start failed: %s", _exmon_exc)

    # Start signal-log integrity checker — daily 00:05 UTC reconcile of
    # orphaned open entries against IG transaction history.
    try:
        import signal_log_integrity as _sli
        _sli.start()
        logger.info("[AUTOBOT] signal_log_integrity scheduler started")
    except Exception as _sli_exc:
        logger.warning("[AUTOBOT] signal_log_integrity start failed: %s", _sli_exc)

    # Start briefing-outcome evaluator — runs on THIS machine where
    # briefings (/opt/tradingbot/logs) and enriched candles
    # (/opt/tradingbot/data/candles) actually live. The sentinel_api
    # copy on droplet 2 can't see either, which is why outcome tracking
    # silently stopped after the briefing path moved to logs/ and the
    # droplet→droplet briefing sync broke.
    def _briefing_outcome_loop():
        import briefing_outcome_tracker as _bot
        from pathlib import Path as _P
        backfill_dir = _P("/opt/tradingbot/logs")
        try:
            n = _bot.backfill_from_briefings(backfill_dir)
            if n:
                logger.info("[AUTOBOT] briefing outcome backfill: %d new outcomes", n)
        except Exception as e:
            logger.warning("[AUTOBOT] briefing outcome backfill failed: %s", e)
        while True:
            try:
                written = _bot.evaluate_completed_sessions()
                if written:
                    logger.info("[AUTOBOT] briefing outcome eval: %d new outcomes", written)
            except Exception as e:
                logger.warning("[AUTOBOT] briefing outcome eval tick failed: %s", e)
            time.sleep(300)  # 5 min cadence — matches session-end + 5-min buffer
    try:
        threading.Thread(target=_briefing_outcome_loop, name="briefing_outcome_loop", daemon=True).start()
        logger.info("[AUTOBOT] briefing_outcome evaluator started")
    except Exception as _boe_exc:
        logger.warning("[AUTOBOT] briefing_outcome evaluator start failed: %s", _boe_exc)

    global _journal, _diag_logger, _LAST_REST_CALL_TS
    _journal = SweepJournal()
    logger.info("📓 SweepJournal initialised.")
    _diag_logger = DiagnosticsLogger()
    logger.info("🔬 DiagnosticsLogger initialised.")

    load_news_windows()

    _briefing_tracker = BriefingTracker()

    def _on_trade_close(pos_key_or_epic: str, exit_price: Any, pnl_pips: Any, close_reason: str,
                         deal_id: Optional[str] = None) -> None:
        # pos_key_or_epic is now "{epic}|{mode}" from close_trade callback.
        # deal_id (added 2026-04-23) lets strategy state matchers disambiguate
        # legs that re-use the same un-suffixed pos_key over a session.
        if "|" in pos_key_or_epic:
            epic = _epic_from_pos_key(pos_key_or_epic)
            pk = pos_key_or_epic
        else:
            epic = pos_key_or_epic
            pk = pos_key_or_epic

        # Canonical epic→pair (handles both CS.D.<PAIR>.TODAY.IP and .CFD.IP).
        # The prior reverse-lookup against EPIC_MAP silently fell through to
        # the raw epic string when the .env switched to CFD epics, nulling
        # MAE/MFE on every close because candle_builder.get_df keys on pair.
        sym = _pair_from_epic(epic)
        try:
            _direction = str((EPIC_STATE.get(pk) or {}).get("direction", "") or "").upper()
            _journal.log_close(sym, epic, exit_price, pnl_pips, close_reason, direction=_direction)
        except Exception:
            pass

        # Signal outcome logger — patch open record with close outcome
        try:
            _sl_id = (EPIC_STATE.get(pk) or {}).get("signal_log_id")
            if _sl_id:
                # Pull exit-path latency captured by trade_executor.close_trade.
                # close_trade resets state on success, but the callback fires
                # before _reset_trade_state runs, so exit_latency is still
                # readable here.  If absent (legacy path / non-close_trade
                # exit), latency stays None and the close record simply
                # lacks those fields — readers must treat missing as null.
                _exit_latency = (EPIC_STATE.get(pk) or {}).get("exit_latency")
                signal_logger.log_close(
                    trade_id=_sl_id,
                    close_price=exit_price,
                    pnl_pips=pnl_pips,
                    reason=close_reason,
                    df_5m=candle_builder.get_df(sym),
                    latency=_exit_latency,
                )
        except Exception:
            pass

        # Push completed trade to Sentinel for model updates
        try:
            from sentinel_client import push_trade_outcome
            _es = EPIC_STATE.get(pk) or {}
            _dbg = _es.get("decision_debug") or {}
            _bm = _es.get("briefing_meta") or {}
            _utc_h = datetime.now(timezone.utc).hour
            _sess = (
                "Asian" if (_utc_h >= 22 or _utc_h < 6)
                else "London" if _utc_h < 12
                else "New York" if _utc_h < 17
                else "London"
            )
            # Scale-out OUTCOME JOIN integrity: when the +10p / 50% scale
            # fired, EPIC_STATE carries partial_bank_pips. The runner's
            # close PnL here represents the runner only — combine with the
            # banked partial so per-regime expectancy sees the full trade.
            _partial_bank = _es.get("partial_bank_pips")
            _runner_pnl = float(pnl_pips) if pnl_pips is not None else 0.0
            _total_pnl = _runner_pnl + (float(_partial_bank) if _partial_bank is not None else 0.0)
            _outcome_dict = {
                "id": _es.get("signal_log_id", ""),
                "source": "live",
                "epic": epic,
                "pair": sym,
                "direction": str(_es.get("direction", "")).upper(),
                "strategy": str(_es.get("mode", "")).upper(),
                "session": _bm.get("session_expectation") or _sess,
                # pnl_pips is the COMBINED total for sentinel/learning
                # (matches what total_pnl_pips will be in signal_log).
                "pnl_pips": round(_total_pnl, 2),
                # Diagnostic split (null when not scaled).
                "runner_pnl_pips":   round(_runner_pnl, 2) if _partial_bank is not None else None,
                "partial_bank_pips": round(float(_partial_bank), 2) if _partial_bank is not None else None,
                "scaled_out":        bool(_es.get("scaled_out")),
                "close_reason": close_reason,
                "bb_width_pips": _dbg.get("bb_width_pips") or _dbg.get("bb_width"),
                "atr_pips": _dbg.get("atr_pips") or _dbg.get("atr"),
                "bias_confidence": _bm.get("briefing_confidence"),
                "session_bias": _bm.get("session_expectation"),
                "daily_bias": _bm.get("briefing_bias"),
                # Regime router OUTCOME-JOIN — links this close back to the
                # regime_engine.jsonl line that drove the open.
                "regime_instance_id": _dbg.get("regime_instance_id"),
                "regime_at_fire":     _dbg.get("regime"),
                "router_direction":   _dbg.get("router_direction"),
            }
            try:
                from briefing_narrative import get_today_narrative
                _outcome_dict["session_narrative"] = get_today_narrative(sym)
            except Exception:
                pass
            _pushed = push_trade_outcome(_outcome_dict)
            logger.debug("[SENTINEL] outcome push %s: %s pnl=%.1f",
                         "ok" if _pushed else "FAILED", epic,
                         float(pnl_pips or 0))
        except Exception as _so_exc:
            logger.debug("[SENTINEL] outcome push error: %s", _so_exc)

        # Record briefing outcome from stashed metadata
        try:
            epic_st = EPIC_STATE.get(pk) or {}
            meta = epic_st.get("briefing_meta") or {}
            if meta:
                _briefing_tracker.record_trade_outcome(
                    symbol=sym,
                    session=meta.get("session_expectation", ""),
                    date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    trade_result={
                        "direction": epic_st.get("direction", ""),
                        "briefing_confirmed": meta.get("briefing_confirmed", False),
                        "briefing_bias": meta.get("briefing_bias", ""),
                        "briefing_confidence": meta.get("briefing_confidence", 0),
                        "session_expectation": meta.get("session_expectation", ""),
                        "plan_label": meta.get("plan_label", ""),
                        "pnl_pips": pnl_pips,
                        "close_reason": close_reason,
                    },
                )
        except Exception as e:
            logger.warning(f"[{sym}/{epic}] briefing_tracker.record failed: {e}")

        # Reset normal cooldown on every close. On SL hits, additionally set a
        # per-direction post-SL block so the bot cannot revenge-trade the same
        # losing setup. Opposite direction is unblocked (a flip is a fresh thesis).
        try:
            bot._set_last_trade_ts(sym, epic, time.time())
            _is_sl_close = bool(
                close_reason and (
                    close_reason.upper() == "SL_HIT"
                    or "SL" in close_reason.upper()
                )
            )
            if _is_sl_close and _direction in ("BUY", "SELL"):
                _set_sl_block(sym, epic, _direction, COOLDOWN_SECONDS_AFTER_SL)
                logger.info(
                    f"[{sym}/{epic}] 🛑 Post-SL block set: {_direction} blocked for "
                    f"{COOLDOWN_SECONDS_AFTER_SL/60.0:.1f} min (reason={close_reason})"
                )
            else:
                logger.info(f"[{sym}/{epic}] Cooldown reset on trade close ({COOLDOWN_SECONDS}s) reason={close_reason}")
        except Exception as e:
            logger.error(f"[{sym}/{epic}] Failed to reset cooldown on close: {e}")

    register_trade_close_callback(_on_trade_close)

    # BB_REVERSAL v4: state-machine hooks. The trade-open callback promotes
    # a PendingProposal to a committed leg (the state-gate fix — stops the
    # DAILY_DOUBLE dormancy bug from recurring). The close callback handles
    # SL re-arm of the tighter filter and final leg accounting.
    try:
        from bb_reversal import (
            on_bb_reversal_trade_opened as _bbr_opened_cb,
            on_bb_reversal_trade_close as _bbr_close_cb,
            get_instance as _bbr_get,
        )
        from trade_executor import register_trade_open_callback
        _bbr_get()  # ensure singleton constructed at startup (loads state, migrates legacy files)
        register_trade_open_callback(_bbr_opened_cb)
        register_trade_close_callback(_bbr_close_cb)
        logger.info("[AUTOBOT] Registered BB_REVERSAL v4 open + close callbacks")
    except Exception as _bbr_reg_err:
        logger.warning("[AUTOBOT] Could not register BB_REVERSAL v4 hooks: %s", _bbr_reg_err)

    # GBPUSD_TREND: hook the broker close-callback so the strategy state
    # machine knows when its position closes (SL hit, cascade-flip self-
    # close, manual close, etc.) and transitions to waiting_for_reset.
    try:
        from gbpusd_trend import mark_position_closed as _gt_mark_closed

        def _gt_close_cb(pos_key, exit_price, pnl_pips, close_reason):
            try:
                # pos_key is "{epic}|{mode}". We only care about
                # GBPUSD_TREND_L / GBPUSD_TREND_S positions.
                if "|" not in pos_key:
                    return
                mode = pos_key.split("|", 1)[1].strip().upper()
                if mode not in ("GBPUSD_TREND_L", "GBPUSD_TREND_S"):
                    return
                _gt_mark_closed(
                    pair="GBPUSD", reason=close_reason or "broker_close",
                    exit_price=exit_price,
                )
            except Exception as _cb_exc:
                logger.warning(
                    "[TREND] close callback failed for %s: %s",
                    pos_key, _cb_exc,
                )

        register_trade_close_callback(_gt_close_cb)
        logger.info("[AUTOBOT] Registered GBPUSD_TREND close callback")
    except Exception as _gt_cb_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD_TREND close callback: %s",
                       _gt_cb_err)

    # GBPUSD dual BB-reversal strategies (REV_L + BIG_REV) — registration log.
    try:
        import gbpusd_bb_reversal_long as _gbrl
        import gbpusd_big_rev as _gbig
        logger.info(
            "[AUTOBOT] Registered GBPUSD_BB_REV_L  | enabled=%s bidirectional "
            "(LONG mode=%s A_LOW=%s, SHORT mode=%s A=%s) "
            "max_trades/day=%d max_sl=%.0fp window=%s-%s",
            _gbrl.ENABLED,
            _gbrl.MODE_NAME, _gbrl.PATTERN_A_LOW_ENABLED,
            _gbrl.MODE_NAME_SHORT, _gbrl.PATTERN_A_SHORT_ENABLED,
            _gbrl.MAX_TRADES_PER_DAY, _gbrl.MAX_SL_PIPS,
            _gbrl.WIN_START.strftime("%H:%M"), _gbrl.WIN_END.strftime("%H:%M"),
        )
        logger.info(
            "[AUTOBOT] Registered GBPUSD_BIG_REV   | enabled=%s body_n>=%.2f "
            "bb_width>=%.0fp range>=%.0fp windows=L%s-%s NY%s-%s",
            _gbig.ENABLED, _gbig.BAR_N_BODY_RATIO,
            _gbig.MIN_BB_WIDTH_PIPS, _gbig.MIN_REVERSAL_RANGE_PIPS,
            _gbig.W_LONDON_START.strftime("%H:%M"), _gbig.W_LONDON_END.strftime("%H:%M"),
            _gbig.W_NY_START.strftime("%H:%M"), _gbig.W_NY_END.strftime("%H:%M"),
        )
    except Exception as _dual_reg_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD dual BB strategies: %s",
                       _dual_reg_err)

    # GBPUSD_OVERNIGHT_LEVEL_SWEEP — registration log.
    try:
        import gbpusd_overnight_level_sweep as _gols
        logger.info(
            "[AUTOBOT] Registered GBPUSD_OVERNIGHT_LEVEL_SWEEP | enabled=%s bidirectional "
            "(LONG mode=%s on=%s, SHORT mode=%s on=%s) "
            "pierce=%.1fp body>=%.2f range>=%.0fp max_sl=%.0fp min_tp=%.0fp "
            "max_levels=%d sep>=%.0fp window=%s-%s",
            _gols.ENABLED,
            _gols.MODE_NAME, _gols.ENABLE_LONG,
            _gols.MODE_NAME_SHORT, _gols.ENABLE_SHORT,
            _gols.PIERCE_PIPS, _gols.MIN_BODY_RATIO, _gols.MIN_BAR_RANGE_PIPS,
            _gols.MAX_SL_PIPS, _gols.MIN_TP_PIPS,
            _gols.MAX_LEVELS, _gols.LEVEL_MIN_SEPARATION_PIPS,
            _gols.WINDOW_START.strftime("%H:%M"), _gols.WINDOW_END.strftime("%H:%M"),
        )
    except Exception as _ov_reg_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD_OVERNIGHT_LEVEL_SWEEP: %s",
                       _ov_reg_err)

    # GBPUSD_BB_PREMIRROR_L — registration log.
    try:
        import gbpusd_bb_premirror_long as _gpml
        logger.info(
            "[AUTOBOT] Registered GBPUSD_BB_PREMIRROR_L | enabled=%s bidirectional "
            "(LONG mode=%s, SHORT mode=%s) "
            "max_per_day=%d body_n>=%.2f mirror_body>=%.2f*N "
            "band_proximity<=%dp mirror_tol=%dp max_sl=%dp "
            "window=%s-%s",
            _gpml.ENABLED,
            _gpml.MODE_NAME, _gpml.MODE_NAME_SHORT,
            _gpml.MAX_TRADES_PER_DAY, _gpml.BAR_N_BODY_RATIO,
            _gpml.BAR_NP1_BODY_RATIO_OF_N,
            int(_gpml.BAND_PROXIMITY_PIPS), int(_gpml.MIRROR_TOLERANCE_PIPS),
            int(_gpml.MAX_SL_PIPS),
            _gpml.WIN_START.strftime("%H:%M"), _gpml.WIN_END.strftime("%H:%M"),
        )
    except Exception as _pm_reg_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD_BB_PREMIRROR_L: %s",
                       _pm_reg_err)

    # GBPUSD_NY_CONTINUATION_L — registration log.
    try:
        import gbpusd_ny_continuation_long as _gnyc
        logger.info(
            "[AUTOBOT] Registered GBPUSD_NY_CONTINUATION_L | enabled=%s bidirectional "
            "(LONG mode=%s, SHORT mode=%s) "
            "min_london_range=%dp directional_frac=%.2f pullback_frac=%.2f "
            "tp_extension=%.2f max_sl=%dp window=%s-%s",
            _gnyc.ENABLED,
            _gnyc.MODE_NAME, _gnyc.MODE_NAME_SHORT,
            int(_gnyc.LONDON_MIN_RANGE_PIPS),
            _gnyc.LONDON_DIRECTIONAL_FRAC, _gnyc.PULLBACK_FRAC,
            _gnyc.TP_EXTENSION_FRAC, int(_gnyc.MAX_SL_PIPS),
            _gnyc.WIN_START.strftime("%H:%M"), _gnyc.WIN_END.strftime("%H:%M"),
        )
    except Exception as _ny_reg_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD_NY_CONTINUATION_L: %s",
                       _ny_reg_err)

    # GBPUSD_TREND (H1-LEADS + MACD confirm + dip-resume, rebuilt 2026-05-28)
    # — registration log. PART-2 rebuild removed Gates 7-8 (5m pierce +
    # momentum-close-third) and the MOMENTUM_CLOSE_RANGE_FRAC constant
    # that came with them; PART-1 removed FRESHNESS_MAX_H1_BARS. This log
    # references only attributes that exist in the rebuilt module so the
    # registration no longer raises AttributeError. New gates exposed:
    # MACD_CONFIRM_ENABLED (light H1 MACD line/signal agreement),
    # DIP_MAX_BARS (5m dip-window size). TREND_MIN_DIRECTIONAL and
    # TREND_FAST_CONTEXT_ENABLED are still used inside _update_h1_streak's
    # is_clean_trend call for the Gate-6 fluke-filter streak label.
    try:
        import gbpusd_trend as _gt_reg
        logger.info(
            "[AUTOBOT] Registered GBPUSD_TREND (H1-LEADS + MACD confirm + dip-resume) | "
            "enabled=%s (LONG mode=%s, SHORT mode=%s) "
            "h1_strength_floor=%.2f freshness_H1_min=%d "
            "macd_confirm=%s dip_max_bars=%d min_directional=%d "
            "sl=%.0fp tp=%.0fp fast_context=%s state_file=%s",
            _gt_reg.ENABLED,
            _gt_reg.MODE_NAME_LONG, _gt_reg.MODE_NAME_SHORT,
            _gt_reg.H1_STRENGTH_FLOOR,
            _gt_reg.FRESHNESS_MIN_H1_BARS,
            _gt_reg.MACD_CONFIRM_ENABLED,
            _gt_reg.DIP_MAX_BARS,
            _gt_reg.TREND_MIN_DIRECTIONAL,
            _gt_reg.SL_PIPS, _gt_reg.TREND_BROKER_TP_PIPS,
            _gt_reg.TREND_FAST_CONTEXT_ENABLED,
            _gt_reg.STATE_FILE,
        )
    except Exception as _gt_reg_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD_TREND: %s",
                       _gt_reg_err)

    # GBPUSD_BB_BOUNCE — registration log.
    try:
        import gbpusd_bb_bounce as _gbb
        from trade_manager import BB_PIERCE_RUN_TIME_STOP_MINUTES as _bbb_tsm
        logger.info(
            "[AUTOBOT] Registered GBPUSD_BB_BOUNCE (BB_PIERCE_RUN) | "
            "enabled=%s bidirectional (LONG mode=%s, SHORT mode=%s) "
            "pierce>=%.1fp sl=%.0fp tp1_fallback=%.0fp "
            "rej_window=%db time_stop=%.0fm (via REGIME_MAX_HOLD) window=%s-%s "
            "h1_counter_strength=%.2f<=s<%.2f",
            _gbb.ENABLED,
            _gbb.MODE_NAME_LONG, _gbb.MODE_NAME_SHORT,
            _gbb.PIERCE_THRESH_PIPS,
            _gbb.SL_PIPS, _gbb.TP1_FALLBACK_PIPS,
            _gbb.REJECTION_WINDOW_BARS, _bbb_tsm,
            _gbb.WIN_START.strftime("%H:%M"), _gbb.WIN_END.strftime("%H:%M"),
            _gbb.H1_COUNTER_STRENGTH_FLOOR, _gbb.H1_COUNTER_STRENGTH_CEILING,
        )
    except Exception as _gbb_reg_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD_BB_BOUNCE: %s",
                       _gbb_reg_err)

    # GBPUSD_BB_REV_PAT (V + Arc) — registration log.
    try:
        import gbpusd_bb_reversal_patterns as _brp_mod
        logger.info(
            "[AUTOBOT] Registered GBPUSD_BB_REV_PAT (V+Arc) | enabled=%s "
            "V=%s Arc=%s (modes L=%s S=%s) "
            "V_min_body=%.0fp V_bb_width>=%.0fp "
            "Arc_bars=%d-%d Arc_hug<=%.0fp Arc_min_rev_body=%.0fp "
            "sl=%.0fp broker_tp=%.0fp news_blackout=%s regime_filter=%s "
            "co_fire_window=%db window=%s-%s",
            _brp_mod.ENABLED, _brp_mod.V_ENABLED, _brp_mod.ARC_ENABLED,
            _brp_mod.MODE_NAME_LONG, _brp_mod.MODE_NAME_SHORT,
            _brp_mod.V_MIN_BODY_PIPS, _brp_mod.V_BB_WIDTH_FLOOR_PIPS,
            _brp_mod.ARC_MIN_BARS, _brp_mod.ARC_MAX_BARS,
            _brp_mod.ARC_HUG_PIPS, _brp_mod.ARC_MIN_REVERSAL_BODY_PIPS,
            _brp_mod.SL_PIPS, _brp_mod.BROKER_TP_PIPS,
            _brp_mod.NEWS_BLACKOUT_ENABLED, _brp_mod.REGIME_FILTER_ENABLED,
            _brp_mod.CO_FIRE_WINDOW_BARS,
            _brp_mod.WIN_START.strftime("%H:%M"),
            _brp_mod.WIN_END.strftime("%H:%M"),
        )
    except Exception as _brp_reg_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD_BB_REV_PAT: %s",
                       _brp_reg_err)

    # GBPUSD_EMA_PULLBACK (continuation pullback — rebuilt 2026-05-27)
    # — registration log. The prior three-filter design's attributes
    # (MACD_SLOPE_KILL, PULLBACK_BODY_MAX, FAN_MIN, FAN_MAX) were
    # removed in the rebuild — the new gate stack is H1 direction +
    # fan floor + trail-band context + 5M-ordering + bearish-close-
    # below-ema8 + whole-pullback ema21-containment. This log now
    # reports the live attributes the rebuilt strategy exposes, so
    # the registration no longer throws AttributeError.
    # Independent kill-switch GBPUSD_EMA_PULLBACK_ENABLED (does NOT
    # collide with legacy ema_pullback.py's EMA_PULLBACK_ENABLED).
    try:
        import gbpusd_ema_pullback as _gep_mod
        logger.info(
            "[AUTOBOT] Registered GBPUSD_EMA_PULLBACK (whole-pullback gate 6) | "
            "enabled=%s (LONG mode=%s, SHORT mode=%s) "
            "h1_sep_floor=%.2fp trail_lookback=%db trail_min_ago=%db "
            "trail_band_tol=%.2fp pullback_lookback=%db cooldown=%db "
            "sl=%.0fp runner_target=%s runner_tp=[%.1fp,%.1fp] "
            "news_blackout=%s window=%s-%s",
            _gep_mod.ENABLED,
            _gep_mod.MODE_NAME_LONG, _gep_mod.MODE_NAME_SHORT,
            _gep_mod.H1_SEP_MIN_PIPS,
            _gep_mod.TRAIL_LOOKBACK_BARS, _gep_mod.TRAIL_MIN_AGO_BARS,
            _gep_mod.TRAIL_BAND_TOL_PIPS,
            _gep_mod.LOOKBACK_BARS, _gep_mod.COOLDOWN_BARS,
            _gep_mod.SL_PIPS, _gep_mod.RUNNER_TARGET_MODE,
            _gep_mod.RUNNER_TP_MIN_PIPS, _gep_mod.RUNNER_TP_MAX_PIPS,
            _gep_mod.NEWS_BLACKOUT_ENABLED,
            _gep_mod.WIN_START.strftime("%H:%M"),
            _gep_mod.WIN_END.strftime("%H:%M"),
        )
    except Exception as _gep_reg_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD_EMA_PULLBACK: %s",
                       _gep_reg_err)

    # Prewarm gbpusd_regime_detector from the candle archive. Without
    # this, the detector's 140-bar baseline takes ~11.7h of live ticks
    # to fill after every restart — every regime gate decision during
    # that window silently falls through as NEUTRAL/LOW. With prewarm
    # the gate is functional from the first 5m close after boot.
    try:
        from gbpusd_regime_detector import prewarm_buffer as _regime_prewarm
        _regime_prewarm("GBPUSD")
    except Exception as _regime_pw_err:
        logger.warning("[AUTOBOT] regime detector prewarm failed: %s",
                       _regime_pw_err)

    # EMA_PULLBACK — registration log + amendments visibility (news
    # blackout, regime gate). Strategy is dispatched from
    # strategy_logic.evaluate_signals → main _on_signal path → executes
    # via execute_trade and logs to signal_log.jsonl via the shared
    # log_open call site (NOT a direct-dispatch wrapper).
    try:
        import ema_pullback as _ep_mod
        logger.info(
            "[AUTOBOT] Registered EMA_PULLBACK | enabled=%s "
            "min_fan_pips=GBPUSD:%.1fp/EURUSD:%.1fp/USDJPY:%.1fp/USDCAD:%.1fp "
            "bb_lookback=%db sl_buffer=%.1fp default_tp=%.0fp "
            "news_blackout=%s pre_min=%dm regime_gate=%s "
            "(GBPUSD only, blocks on RANGE) "
            "session=07-17 BST (London 07-12, NY 12-17)",
            _ep_mod.EMA_PULLBACK_ENABLED,
            _ep_mod._min_fan_for_pair("GBPUSD"),
            _ep_mod._min_fan_for_pair("EURUSD"),
            _ep_mod._min_fan_for_pair("USDJPY"),
            _ep_mod._min_fan_for_pair("USDCAD"),
            _ep_mod.BB_LOOKBACK_BARS,
            _ep_mod.SL_BUFFER_PIPS, _ep_mod.DEFAULT_TP_PIPS,
            _ep_mod.NEWS_BLACKOUT_ENABLED, _ep_mod.NEWS_PRE_MIN,
            _ep_mod.REGIME_FILTER_ENABLED,
        )
    except Exception as _ep_reg_err:
        logger.warning("[AUTOBOT] Could not register EMA_PULLBACK: %s",
                       _ep_reg_err)

    # GBPUSD_RAW_REVERSAL — registration log (kept for rollback visibility).
    try:
        import gbpusd_raw_reversal as _grr
        logger.info(
            "[AUTOBOT] Registered GBPUSD_RAW_REVERSAL | enabled=%s bidirectional "
            "(LONG mode=%s, SHORT mode=%s) "
            "setups=A,B,C max_per_dir/session=%d sl=[%.0fp..%.0fp] tp=%.0fp "
            "window=%s-%s",
            _grr.ENABLED,
            _grr.MODE_NAME_LONG, _grr.MODE_NAME_SHORT,
            _grr.MAX_ENTRIES_PER_DIRECTION,
            _grr.SL_FLOOR_PIPS, _grr.SL_CEILING_PIPS, _grr.TP_PIPS,
            _grr.WIN_START.strftime("%H:%M"), _grr.WIN_END.strftime("%H:%M"),
        )
    except Exception as _rr_reg_err:
        logger.warning("[AUTOBOT] Could not register GBPUSD_RAW_REVERSAL: %s",
                       _rr_reg_err)

    # BB_REVERSAL ALLOWED_PAIRS — surface the active pair list at startup so
    # operator can confirm GBPUSD is no longer in scope (replaced by
    # GBPUSD_RAW_REVERSAL on 2026-04-28).
    try:
        import bb_reversal as _bbr_pairs_log
        logger.info(
            "[AUTOBOT] BB_REVERSAL ALLOWED_PAIRS=%s",
            sorted(_bbr_pairs_log.ALLOWED_PAIRS) or "[]",
        )
    except Exception:
        pass

    # EXHAUSTION_REVERSAL ALLOWED_PAIRS — same rationale.
    try:
        import exhaustion_reversal as _exr_pairs_log
        logger.info(
            "[AUTOBOT] EXHAUSTION_REVERSAL enabled=%s ALLOWED_PAIRS=%s",
            _exr_pairs_log.EXHAUSTION_REVERSAL_ENABLED,
            sorted(_exr_pairs_log.ALLOWED_PAIRS) or "[]",
        )
    except Exception:
        pass

    # RSI_EXTREME_FADE / MACD_EXTREME_FADE — full-search portfolio pilot.
    # Default ON per the deployable-subset plan. Per-mode env disable via
    # <MODE_NAME>_ENABLED=0; module-wide via RSI_EXTREME_FADE_ENABLED=0 /
    # MACD_EXTREME_FADE_ENABLED=0.
    try:
        import rsi_extreme_fade as _ref_log
        for _cfg in _ref_log.configs_summary():
            logger.info(
                "[AUTOBOT] Registered %s | enabled=%s pair=%s dir=%s "
                "RSI(%d)%s%.4f SL=%.1fp TP=%.1fp",
                _cfg["mode_name"],
                _cfg["enabled"] and _ref_log.RSI_EXTREME_FADE_ENABLED,
                _cfg["pair"], _cfg["direction"],
                _cfg["rsi_period"], _cfg["op"], _cfg["threshold"],
                _cfg["sl_pips"], _cfg["tp_pips"],
            )
        logger.info(
            "[AUTOBOT] RSI_EXTREME_FADE module enabled=%s ALLOWED_PAIRS=%s",
            _ref_log.RSI_EXTREME_FADE_ENABLED,
            sorted(_ref_log.ALLOWED_PAIRS) or "[]",
        )
    except Exception as _ref_log_err:
        logger.warning("[AUTOBOT] Could not register RSI_EXTREME_FADE: %s",
                       _ref_log_err)

    try:
        import macd_extreme_fade as _mef_log
        for _cfg in _mef_log.configs_summary():
            logger.info(
                "[AUTOBOT] Registered %s | enabled=%s pair=%s dir=%s "
                "MACD(%d,%d,sig=%d)%s%.4f SL=%.1fp TP=%.1fp",
                _cfg["mode_name"],
                _cfg["enabled"] and _mef_log.MACD_EXTREME_FADE_ENABLED,
                _cfg["pair"], _cfg["direction"],
                _cfg["fast"], _cfg["slow"], _cfg["signal"],
                _cfg["op"], _cfg["threshold"],
                _cfg["sl_pips"], _cfg["tp_pips"],
            )
        logger.info(
            "[AUTOBOT] MACD_EXTREME_FADE module enabled=%s ALLOWED_PAIRS=%s",
            _mef_log.MACD_EXTREME_FADE_ENABLED,
            sorted(_mef_log.ALLOWED_PAIRS) or "[]",
        )
    except Exception as _mef_log_err:
        logger.warning("[AUTOBOT] Could not register MACD_EXTREME_FADE: %s",
                       _mef_log_err)

    # BB_PATTERN2_FADE — Phase-6 strict/loose pilot. Per-mode env disable via
    # <MODE_NAME>_ENABLED=0; module-wide via BB_PATTERN2_FADE_ENABLED=0.
    try:
        import bb_pattern2_fade as _bbp2_log
        for _cfg in _bbp2_log.configs_summary():
            logger.info(
                "[AUTOBOT] Registered %s | enabled=%s pair=%s variant=%s "
                "SL=%.1fp TP=%.1fp horizon=%d wick:body>=%.2f iso=%db",
                _cfg["mode_name"],
                _cfg["enabled"] and _bbp2_log.BB_PATTERN2_FADE_ENABLED,
                _cfg["pair"], _cfg["variant"],
                _cfg["sl_pips"], _cfg["tp_pips"], _cfg["horizon_bars"],
                _cfg["wick_ratio"], _cfg["isolation_window"],
            )
        logger.info(
            "[AUTOBOT] BB_PATTERN2_FADE module enabled=%s ALLOWED_PAIRS=%s",
            _bbp2_log.BB_PATTERN2_FADE_ENABLED,
            sorted(_bbp2_log.ALLOWED_PAIRS) or "[]",
        )
    except Exception as _bbp2_log_err:
        logger.warning("[AUTOBOT] Could not register BB_PATTERN2_FADE: %s",
                       _bbp2_log_err)

    # Pair-concurrency caps — log the per-pair configuration at startup so the
    # operator can confirm what's enforced this session. Empty / 0 means
    # unlimited on that dimension.
    try:
        from trade_executor import _env_int_safe as _cap_env_int
        _cap_summary = []
        for _p in ("GBPUSD", "EURUSD", "USDJPY", "USDCAD", "GBPJPY"):
            _mt = _cap_env_int(f"{_p}_MAX_CONCURRENT")
            _md = _cap_env_int(f"{_p}_MAX_PER_DIRECTION")
            if _mt <= 0 and _md <= 0:
                _cap_summary.append(f"{_p}=unlimited")
            else:
                _t = f"{_mt}" if _mt > 0 else "∞"
                _d = f"{_md}/dir" if _md > 0 else "∞/dir"
                _cap_summary.append(f"{_p}={_t} max ({_d})")
        logger.info("[CONCURRENCY-CAP] %s", ", ".join(_cap_summary))
    except Exception as _cap_log_err:
        logger.warning("[CONCURRENCY-CAP] startup log failed: %s", _cap_log_err)

    # BRIEFING_EXECUTION pessimistic commit: the _entered slot is locked only
    # on broker ACCEPTED. The decision-emit path no longer writes _entered,
    # so a dispatch reject (pyramiding guard, session gate, cooldown, etc.)
    # or broker REJECT leaves the slot unlocked and re-armable.
    try:
        from briefing_execution import BRIEFING_EXECUTION_MODE as _BE_MODE_CB
        from trade_executor import (
            register_trade_open_callback as _register_open_cb_be,
            EPIC_STATE as _EPIC_STATE_BE,
            _pair_from_epic as _pair_from_epic_be,
        )

        def _briefing_exec_opened_cb(pos_key: str, decision: Any) -> None:
            _mode = str(getattr(decision, "mode", "") or "").strip().upper()
            if _mode != _BE_MODE_CB:
                return
            try:
                from strategy_logic import evaluate_signals as _es_ref
                _be_strat = getattr(_es_ref, "_be_strat", None)
                if _be_strat is None:
                    logger.warning(
                        "[BRIEFING-EXEC] broker-confirm callback fired but "
                        "_be_strat singleton not yet constructed (pos_key=%s)",
                        pos_key,
                    )
                    return
                _sym_cb = str(getattr(decision, "symbol", "") or "").upper()
                if not _sym_cb:
                    try:
                        _sym_cb = _pair_from_epic_be(pos_key.split("|", 1)[0]).upper()
                    except Exception:
                        _sym_cb = ""
                _st_cb = _EPIC_STATE_BE.get(pos_key) or {}
                _deal_id_cb = (
                    _st_cb.get("dealId") or _st_cb.get("deal_id") or None
                )
                _brief_time_cb = _be_strat._briefing_id.get(_sym_cb, "")
                # Step 2A — plan_id rides on decision.debug; pass it
                # through to the strategy so the on-disk dedup record
                # learns which plan fired (entered_by_plan). Behaviour
                # stays pair-scoped; plan_id is observability + forward
                # compat for Commit 2B.
                _dbg_cb = getattr(decision, "debug", None) or {}
                _plan_id_cb = _dbg_cb.get("plan_id")
                _be_strat.on_broker_confirmed(
                    _sym_cb,
                    briefing_time=_brief_time_cb,
                    deal_id=_deal_id_cb,
                    plan_id=_plan_id_cb,
                )
            except Exception as _be_cb_err:
                logger.error(
                    "[BRIEFING-EXEC] broker-confirm callback failed "
                    "pos_key=%s: %s — slot may remain unlocked; next tick will "
                    "re-evaluate (broker position is real).",
                    pos_key, _be_cb_err,
                )

        _register_open_cb_be(_briefing_exec_opened_cb)
        logger.info("[AUTOBOT] Registered BRIEFING_EXECUTION broker-confirm callback")
    except Exception as _be_reg_err:
        logger.warning(
            "[AUTOBOT] Could not register BRIEFING_EXECUTION broker-confirm callback: %s",
            _be_reg_err,
        )

    preload_summary = []
    for _idx, (symbol, today_epic) in enumerate(EPIC_MAP.items()):
        if _idx > 0:
            time.sleep(0.5)  # stagger REST preload across pairs to avoid burst
        df, src = _rest_preload_symbol(ig, symbol=symbol, today_epic=today_epic)
        if df is not None:
            injected = False
            try:
                candle_builder.build_candles(symbol, df.rename(columns={"timestamp": "time"}))
                injected = True
            except Exception:
                try:
                    candle_builder.build_candles(symbol, df)
                    injected = True
                except Exception:
                    injected = False

            if not injected:
                key = str(symbol).upper()
                if key not in _WARNED_PRELOAD_INJECT_FAIL:
                    _WARNED_PRELOAD_INJECT_FAIL.add(key)
                    logger.warning(f"[PRELOAD-INJECT] [{symbol}] ❌ candle_builder.build_candles failed; will fallback to tick-build.")

            try:
                df_check = candle_builder.get_df(str(symbol).upper())
                rows = int(len(df_check)) if df_check is not None else 0
                logger.info(f"[PRELOAD-INJECT] [{symbol}] builder_rows={rows} src={src}")
            except Exception:
                logger.warning(f"[PRELOAD-INJECT] [{symbol}] unable to verify builder rows (get_df failed).")

            preload_summary.append(f"{symbol}:{len(df)}({src})")
        else:
            preload_summary.append(f"{symbol}:0({src})")

    logger.info("[PRELOAD] " + " ".join(preload_summary))
    logger.info(f"[CACHE] WRITE_CACHE_FROM_5M_CLOSE={'1' if WRITE_CACHE_FROM_5M_CLOSE else '0'} dir={CACHE_DIR}")

    # ------------------------------------------------------------------
    # HTF preload — cache-first: load persisted H1/D1 candles from JSON
    # cache, fall back to 5M replay only on cold start or stale cache.
    # ------------------------------------------------------------------
    import pandas as _htf_pd
    _htf_cache_restored: Dict[str, set] = {}  # symbol -> set of TFs restored from HTF cache

    # Phase 1: Try HTF JSON cache (fast path — avoids 5M replay entirely)
    if _htf_cache is not None:
        _htf_cache._ensure_cache_dir()
        for _htf_sym, _htf_epic in EPIC_MAP.items():
            _htf_cache_restored.setdefault(_htf_sym.upper(), set())
            for _tf in ("H1", "D1"):
                try:
                    _action, _cached_candles, _last_epoch = _htf_cache.startup_load_or_flag(
                        _htf_sym.upper(), _tf,
                    )
                    if _action == "fresh" and _cached_candles:
                        _n = _TF_CTX.inject_htf_candles(_htf_sym.upper(), _tf, _cached_candles)
                        _htf_cache_restored[_htf_sym.upper()].add(_tf)
                        logger.info(
                            f"[HTF-PRELOAD] {_htf_sym}/{_tf}: restored {_n} candles from HTF cache (fresh)"
                        )
                    elif _action == "gap_fill" and _cached_candles:
                        # Try to gap-fill from IG API, fall back to stale cache
                        _gap_filled = False
                        if not _rest_blocked_now() and REST_PRELOAD_ENABLED:
                            _gf_epic = _pick_preload_epic(_htf_sym)
                            if _gf_epic:
                                _ig_res = "HOUR" if _tf == "H1" else "DAY"
                                # Estimate points needed: seconds since last candle / bucket size + buffer
                                _bucket_secs = 3600 if _tf == "H1" else 86400
                                _age_secs = _htf_cache.last_candle_age_secs(_cached_candles) or 0
                                _points_needed = max(5, int(_age_secs / _bucket_secs) + 5)
                                try:
                                    _now_t = time.time()
                                    if _now_t - _LAST_REST_CALL_TS < REST_PRELOAD_MIN_GAP_SECS:
                                        time.sleep(max(0.0, REST_PRELOAD_MIN_GAP_SECS - (_now_t - _LAST_REST_CALL_TS)))
                                    _LAST_REST_CALL_TS = time.time()
                                    _gf_df, _gf_raw = _rest_fetch_df(ig, _gf_epic, _ig_res, _points_needed)
                                    if _gf_df is not None and len(_gf_df) > 0:
                                        _fresh_candles = _htf_cache.normalize_ig_hist_to_candles(_tf, _gf_df)
                                        _merged = _htf_cache.merge_candles(_cached_candles, _fresh_candles)
                                        _n = _TF_CTX.inject_htf_candles(_htf_sym.upper(), _tf, _merged)
                                        _htf_cache.save_candles_to_cache(_htf_sym.upper(), _tf, _merged)
                                        _htf_cache_restored[_htf_sym.upper()].add(_tf)
                                        _gap_filled = True
                                        logger.info(
                                            f"[HTF-PRELOAD] {_htf_sym}/{_tf}: gap-filled {len(_fresh_candles)} candles "
                                            f"from API, merged to {_n} total"
                                        )
                                except Exception as _gf_err:
                                    _code = _best_effort_extract_error_code(_gf_err)
                                    if _is_allowance_error(_code):
                                        _until = int(time.time() + REST_PRELOAD_BLOCK_SECS)
                                        _write_rest_block(_until, "htf-gap-fill-allowance")
                                    logger.warning(
                                        f"[HTF-CACHE] {_htf_sym}/{_tf}: gap-fill API failed ({_gf_err}), using stale cache"
                                    )
                        if not _gap_filled:
                            _n = _TF_CTX.inject_htf_candles(_htf_sym.upper(), _tf, _cached_candles)
                            _htf_cache_restored[_htf_sym.upper()].add(_tf)
                            logger.info(
                                f"[HTF-PRELOAD] {_htf_sym}/{_tf}: restored {_n} candles from HTF cache (stale, no gap-fill)"
                            )
                except Exception as _hce:
                    logger.warning(f"[HTF-CACHE] {_htf_sym}/{_tf}: cache restore failed: {_hce}")

    # Phase 2: 5M replay for symbols/TFs NOT fully restored from HTF cache
    _v5_pia_cold_start_metrics: List[Dict[str, Any]] = []
    for _htf_sym, _htf_epic in EPIC_MAP.items():
        _restored_tfs = _htf_cache_restored.get(_htf_sym.upper(), set())
        # If H1 and D1 came from the HTF JSON cache, the all-TF 5M replay is
        # skipped — but H4 isn't in that JSON cache, so we still need an
        # H4-only replay here. Otherwise v5_pia STAND_ASIDEs all pairs with
        # `insufficient_h4_bars` until ~5 live H4 closes accumulate (~20h).
        if "H1" in _restored_tfs and "D1" in _restored_tfs:
            logger.info(
                f"[V5_PIA] {_htf_sym}: H1+D1 restored from HTF cache — running H4 cold-start (REST primary)"
            )
            _h4_metrics = _v5_pia_h4_cold_start(ig, _htf_sym, _htf_epic, _TF_CTX)
            _v5_pia_cold_start_metrics.append(_h4_metrics)
            logger.info(
                f"[V5_PIA] H4 cache initialized for {_htf_sym}: {_h4_metrics['bars']} bars "
                f"(source: REST={'Y' if _h4_metrics['rest'] else 'N'}, "
                f"backfill={'Y' if _h4_metrics['backfill'] else 'N'})"
            )
            # Still need to seed snapshot for bias computation
            _h1_candles = _TF_CTX.get_closed_candles(_htf_sym.upper(), "H1")
            if _h1_candles:
                _last_c = _h1_candles[-1]
                _last_ts = _htf_pd.Timestamp(str(_last_c["timestamp"]))
                if _last_ts.tzinfo is None:
                    _last_ts = _last_ts.tz_localize("UTC")
                _TF_LAST_SNAPSHOT_BY_SYMBOL[_htf_sym.upper()] = _TF_CTX.on_5m_close(
                    _htf_sym.upper(), _htf_epic,
                    {
                        "timeframe": "5m",
                        "symbol": _htf_sym.upper(),
                        "epic": _htf_epic,
                        "candle": {
                            "timestamp": _last_ts,
                            "open": float(_last_c["open"]),
                            "high": float(_last_c["high"]),
                            "low": float(_last_c["low"]),
                            "close": float(_last_c["close"]),
                        },
                        "bucket_epoch": int(_last_ts.timestamp()) // 300 * 300,
                    },
                )
            continue

        try:
            # Prefer deep cache (built by build_deep_cache.py) for fuller HTF history
            _htf_path = _cache_path(_htf_sym)
            _deep_path = _htf_path.replace("_candles.csv", "_candles_deep.csv")
            _htf_df = None
            _htf_src = "standard"
            if os.path.exists(_deep_path):
                try:
                    _htf_df = _htf_pd.read_csv(_deep_path)
                    if _htf_df is not None and len(_htf_df) > 0:
                        _htf_src = f"deep({len(_htf_df)} bars)"
                    else:
                        _htf_df = None
                except Exception:
                    _htf_df = None
            if _htf_df is None and os.path.exists(_htf_path):
                try:
                    _htf_df = _htf_pd.read_csv(_htf_path)
                    if _htf_df is not None and len(_htf_df) > 0:
                        _htf_src = f"standard({len(_htf_df)} bars)"
                    else:
                        _htf_df = None
                except Exception:
                    _htf_df = None
            if _htf_df is None or len(_htf_df) == 0:
                logger.info(f"[HTF-PRELOAD] {_htf_sym}: no cache file — HTF context starts empty")
                continue

            _htf_summary = _TF_CTX.preload_from_5m_cache(_htf_sym, _htf_epic, _htf_df)

            # Seed the snapshot so first tick eval has HTF data — call on_5m_close
            # with the last cached candle to trigger bias computation.
            _ts_col = "timestamp" if "timestamp" in _htf_df.columns else "time"
            _last_row = _htf_df.iloc[-1]
            _last_ts = _htf_pd.Timestamp(str(_last_row[_ts_col]))
            if _last_ts.tzinfo is None:
                _last_ts = _last_ts.tz_localize("UTC")
            _TF_LAST_SNAPSHOT_BY_SYMBOL[_htf_sym.upper()] = _TF_CTX.on_5m_close(
                _htf_sym.upper(), _htf_epic,
                {
                    "timeframe": "5m",
                    "symbol": _htf_sym.upper(),
                    "epic": _htf_epic,
                    "candle": {
                        "timestamp": _last_ts,
                        "open": float(_last_row["open"]),
                        "high": float(_last_row["high"]),
                        "low": float(_last_row["low"]),
                        "close": float(_last_row["close"]),
                    },
                    "bucket_epoch": int(_last_ts.timestamp()) // 300 * 300,
                },
            )
            logger.info(
                f"[HTF-PRELOAD] {_htf_sym}: H1={_htf_summary['h1_candles']} H4={_htf_summary['h4_candles']} "
                f"D1={_htf_summary['d1_candles']} | bias: h1={_htf_summary.get('h1_bias','?')} "
                f"h4={_htf_summary.get('h4_bias','?')} d1={_htf_summary.get('d1_bias','?')} | src={_htf_src}"
            )

            # Save freshly-built H1+D1 candles to HTF cache for next restart
            if _htf_cache is not None:
                try:
                    _htf_cache.save_candles_to_cache(
                        _htf_sym.upper(), "H1",
                        _TF_CTX.get_closed_candles(_htf_sym.upper(), "H1"),
                    )
                    _htf_cache.save_candles_to_cache(
                        _htf_sym.upper(), "D1",
                        _TF_CTX.get_closed_candles(_htf_sym.upper(), "D1"),
                    )
                except Exception:
                    pass
        except Exception as _htf_e:
            logger.warning(f"[HTF-PRELOAD] {_htf_sym}: failed: {type(_htf_e).__name__}: {_htf_e}")

    # v5_PIA cold-start cost summary (1 line, after all pairs processed).
    try:
        _rest_pairs = sum(1 for m in _v5_pia_cold_start_metrics if m.get("rest"))
        _cost = _rest_pairs * _V5_PIA_H4_REQUEST_BARS
        import rest_allowance as _ra_sum
        _remaining_now = int(_ra_sum.remaining())
        logger.info(
            f"[V5_PIA] cold-start REST cost: {_cost} points, remaining: {_remaining_now}"
        )
    except Exception as _cs_e:
        logger.warning(f"[V5_PIA] cold-start cost-summary failed: {type(_cs_e).__name__}: {_cs_e}")

    # ------------------------------------------------------------------
    # D1 cache preload — load pre-built D1 candles directly (no 5M aggregation)
    # Only for symbols where D1 was NOT already restored from HTF cache.
    # ------------------------------------------------------------------
    for _htf_sym, _htf_epic in EPIC_MAP.items():
        _restored_tfs = _htf_cache_restored.get(_htf_sym.upper(), set())
        if "D1" in _restored_tfs:
            continue  # Already restored from HTF cache
        _d1_path = _cache_path(_htf_sym).replace("_candles.csv", "_candles_d1.csv")
        if os.path.exists(_d1_path):
            try:
                _d1_df = _htf_pd.read_csv(_d1_path)
                if _d1_df is not None and len(_d1_df) > 0:
                    _d1_summary = _TF_CTX.preload_from_d1_cache(_htf_sym, _htf_epic, _d1_df)
                    logger.info(
                        f"[HTF-PRELOAD] {_htf_sym}: D1={_d1_summary['d1_candles']} candles from d1 cache "
                        f"| bias={_d1_summary['d1_bias']}"
                    )
                    # Save to HTF cache for next restart
                    if _htf_cache is not None:
                        try:
                            _htf_cache.save_candles_to_cache(
                                _htf_sym.upper(), "D1",
                                _TF_CTX.get_closed_candles(_htf_sym.upper(), "D1"),
                            )
                        except Exception:
                            pass
            except Exception as _d1_e:
                logger.warning(f"[HTF-PRELOAD] {_htf_sym}: D1 cache load failed: {_d1_e}")

    news_calendar.prefetch()
    morning_briefing.start(tf_ctx=_TF_CTX, builder=candle_builder)

    # ------------------------------------------------------------------
    # Startup reconciliation — must run before tick loop starts.
    # Polls IG for any positions that survived a bot restart and restores
    # local TRADE_STATE_BY_EPIC so trade_manager protects them immediately.
    # ------------------------------------------------------------------
    try:
        _mode_map = _recover_mode_map_from_journal(EPIC_MAP)
        if _mode_map:
            logger.info(f"[RECONCILE] Mode hints from journal: {_mode_map}")
        _reconciled, _seen = reconcile_open_positions(EPIC_MAP, mode_map=_mode_map)
        if _reconciled > 0:
            logger.warning(
                f"[RECONCILE] ⚠️ {_reconciled} open IG position(s) restored into local state. "
                f"Trade manager will protect them immediately."
            )
            # Restore persisted profit management state for surviving trades.
            # NOTE: do NOT `from trade_executor import EPIC_STATE` here — that
            # makes EPIC_STATE a local of main() for the whole function and
            # shadows the module-level import, leaving _on_trade_close
            # (defined earlier in main) with an unbound EPIC_STATE reference
            # if this branch never runs. Use the module-level import instead.
            try:
                from trade_manager import restore_profit_state_for_active_trades
                _active = {ep for ep, st in EPIC_STATE.items() if st.get("active")}
                restore_profit_state_for_active_trades(_active)
            except Exception as _rpe:
                logger.warning(f"[RECONCILE] Profit state restore failed: {_rpe}")
        elif _seen > 0:
            # IG returned positions for our epics but the gates (own-deals,
            # already-tracked, foreign) dropped them all. Emit a loud line
            # so a silent-drop surfaces here, not after lost trades.
            logger.warning(
                f"[RECONCILE] ⚠️ {_seen} open IG position(s) matched our epics "
                f"but none were restored. Check per-deal RECONCILE WARN/DEBUG "
                f"lines above (own-deals gate, foreign deals, already tracked)."
            )
        else:
            logger.info("[RECONCILE] No orphaned positions — starting clean.")
    except Exception as _rec_err:
        logger.error(f"[RECONCILE] ❌ Startup reconciliation failed: {_rec_err}", exc_info=True)

    # ── Trades API launch (in-process, OPT-IN) ────────────────────────────
    # Default: do NOT bind 8080 in-process. The standalone
    # `trades-api.service` (deploy/trades-api.service) owns that port so
    # the dashboard stays live when the trading engine is off (weekends,
    # maintenance). Set TRADES_API_INPROCESS_ENABLED=1 only to re-bundle
    # the legacy in-process Flask daemon-thread (e.g. for a single-process
    # debug run where you don't want to manage two systemd units).
    if str(os.getenv("TRADES_API_INPROCESS_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on"):
        from trades_api import start_trades_api
        start_trades_api(port=8080)
        logger.info("[STARTUP] Trades API in-process (TRADES_API_INPROCESS_ENABLED=1) — binds 0.0.0.0:8080")
    else:
        logger.info("[STARTUP] Trades API NOT started in-process — owned by standalone trades-api.service "
                    "(set TRADES_API_INPROCESS_ENABLED=1 to re-bundle)")

    logger.info("===== ✅ STARTUP COMPLETE =====")

    try:
        _utc_now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        _pairs_str = ", ".join(sorted(EPIC_MAP.keys())) or "(none)"
        _sessions = getattr(morning_briefing, "SESSIONS", []) or []
        _briefing_str = " | ".join(
            f"{_sname} {_sh:02d}:{_sm:02d}" for _sh, _sm, _sname in _sessions
        ) or "(none)"
        try:
            import rest_allowance
            _ra = rest_allowance.get_state()
            _budget_line = (
                f"\n<b>REST budget:</b> {_ra['points_used']}/{_ra['points_budget']} used, "
                f"{_ra['remaining']} remaining (counter since {_ra['week_start']}; IG resets nightly)"
            )
        except Exception:
            _budget_line = ""
        _startup_msg = (
            f"🚀 <b>AutoBot startup complete</b> <code>[{BOT_ID}]</code>\n"
            f"<b>Time:</b> {_utc_now_str}\n"
            f"<b>Pairs:</b> {_pairs_str}\n"
            f"<b>Briefings (UTC):</b> {_briefing_str}"
            f"{_budget_line}"
        )
        send_telegram_message(_startup_msg)
    except Exception as _startup_tg_err:
        logger.warning(f"[AUTOBOT] startup Telegram notification failed: {_startup_tg_err}")

    logger.info("📡 Starting Lightstreamer …")

    stop_evt = threading.Event()
    hb_thread = threading.Thread(target=bot._heartbeat_loop, args=(stop_evt,), daemon=True)
    hb_thread.start()

    # LS-thread refactor (2026-05-08): per-pair-worker async dispatch.
    # Pre-create workers for every tracked pair so the LS callback path
    # never has to allocate-on-the-hot-path. Configure default tick + 5m
    # callbacks via the module-level registry.
    if _LS_ASYNC_DISPATCH:
        try:
            import pair_workers
            import native_5m_source as _ns_mod
            pair_workers.configure_default_callbacks(
                tick_callback=bot._on_ls_tick,
                five_min_callback=_ns_mod._emit_native_close,
            )
            for _sym in EPIC_MAP.keys():
                pair_workers.get_or_create_worker(_sym)
            pair_workers.start_depth_gauge()
            logger.info(
                f"[LS-WORKER] {len(EPIC_MAP)} per-pair workers started "
                f"(LS_ASYNC_DISPATCH=1)"
            )
        except Exception as _pw_exc:
            logger.error(
                f"[LS-WORKER] startup failed: {_pw_exc}",
                exc_info=True,
            )

    # LS-thread refactor (2026-05-08): start the REST sweep daemon.
    # When LS_ASYNC_DISPATCH=1 (default) it owns the SYNC + external-close
    # cadences that previously fired inline from `_on_ls_tick`.
    try:
        import rest_sweeps
        rest_sweeps.start_rest_sweep_daemon(
            sync_sweep_fn=bot.run_positions_sync,
            external_close_sweep_fn=trade_manager.run_external_close_sweep,
        )
    except Exception as _rs_exc:
        logger.warning(
            f"[REST-SWEEP] daemon start failed: {_rs_exc}",
            exc_info=True,
        )

    controller = start_streaming(EPIC_MAP, bot._on_ls_tick)
    bot.ls_controller = controller
    logger.info("✔ Lightstreamer active.")

    # Seed candle_builder's rolling buffer from the on-disk cache so
    # indicator windows are warm when the first native 5m bar arrives.
    # Absence of a cache file is non-fatal (first few bars will have
    # NaN indicators until the windows fill; existing strategy warmup
    # guards handle that).
    try:
        import native_5m_source
        _seed_counts = native_5m_source.seed_builder_from_cache(EPIC_MAP)
        logger.info(f"[native-5m] cold-start seed counts: {_seed_counts}")
    except Exception as _seed_exc:
        logger.warning(f"[native-5m] cache seed failed: {_seed_exc}", exc_info=True)

    # Subscribe to CHART:{epic}:5MINUTE on the same LS client used for
    # ticks. This is the canonical source of closed 5m bars post-migration
    # (branch migrate/native-5m-candle-feed, 2026-04-23). The tick
    # subscription from start_streaming() is preserved for NEWS_TICK.
    #
    # 2026-05-28 self-healing port: register the 5m feed as a FACTORY
    # (not a Subscription object via controller.add_subscription) so
    # the LSController can rebuild it against a fresh client during a
    # self-healing recovery. The factory closure captures EPIC_MAP and
    # the default on_close_payload (`_emit_native_close`) — which keeps
    # the existing candle_builder callback chain intact across rebuilds.
    try:
        _native_factory = native_5m_source.make_native_5m_factory(EPIC_MAP)
        controller.register_factory(
            name="native_5m",
            factory=_native_factory,
            watch_symbols=None,  # 5m closes are NOT a tick liveness signal
        )
        logger.info(
            "✔ Native 5m factory registered (CHART:{epic}:5MINUTE — "
            "survives self-healing recovery)."
        )
    except Exception as _sub_exc:
        # Hard-fail: without the native subscription there is no source of
        # closed bars, which silently disables every candle-gated strategy.
        # Crash early is better than silent no-trading.
        logger.error(f"[native-5m] subscription FAILED: {_sub_exc}", exc_info=True)
        raise

    # Start the stale-tick watchdog now that every factory is registered.
    # See streamer_ls.LSController._watchdog_loop. Market-hours-gated,
    # Sunday-reopen-probe-guarded, single-in-flight recovery thread.
    try:
        controller.start_watchdog()
    except Exception as _wd_exc:
        logger.error(
            "[LS-WATCHDOG] failed to start (continuing without "
            "self-healing): %s", _wd_exc, exc_info=True,
        )

    _install_shutdown_signal_handlers()

    try:
        while not _SHUTDOWN_REQUESTED.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        # Fallback path if signal handler registration failed; handler normally wins.
        _SHUTDOWN_REQUESTED.set()
    finally:
        _run_graceful_shutdown(controller, stop_evt)


if __name__ == "__main__":
    # Fatal auth exit: FatalAuthError leaks straight through main() from
    # get_ig_session(). Translate it to the distinct exit code the unit
    # file's RestartPreventExitStatus is pinned to, so systemd keeps the
    # service DOWN until an operator has resolved the IG suspension.
    import sys as _sys
    try:
        from ig_auth import FATAL_AUTH_EXIT_CODE as _FATAL_AUTH_EXIT_CODE
        from ig_auth import FatalAuthError as _FatalAuthError
    except Exception:
        _FATAL_AUTH_EXIT_CODE = 78
        _FatalAuthError = None
    try:
        main()
    except (*(( _FatalAuthError,) if _FatalAuthError else ()),) as _fatal_exc:
        logger.critical(
            "[BOOT] fatal auth exit: %s (errorCode=%s attempts=%s) — exiting %d",
            _fatal_exc, getattr(_fatal_exc, "error_code", "?"),
            getattr(_fatal_exc, "attempts", "?"), _FATAL_AUTH_EXIT_CODE,
        )
        _sys.exit(_FATAL_AUTH_EXIT_CODE)
