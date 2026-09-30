#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
morning_briefing.py — Scheduled pre-session FX briefing via Anthropic API.

Runs at 00:00 UTC (Asian open), then London/London_Open/Mid-session/NY/NY_Mid
sessions that auto-adjust for BST (last Sun Mar – last Sun Oct): GMT schedule
uses 05:45/08:00/10:45/13:00/15:00 UTC; BST uses 04:45/07:00/09:45/12:00/14:00.
Assembles multi-timeframe market data per symbol, calls claude-sonnet-4-5,
and stores a structured JSON briefing that acts as a directional gate in
strategy_logic.py (fail-closed: no briefing → trades blocked).

Public API
----------
start(tf_ctx, builder)
    Start the background scheduler. Call from sentinel.main() after
    news_calendar.prefetch().

update_htf_snapshot(symbol, snapshot)
    Keep HTF snapshots current. Call from sentinel._on_5m_close().

get_briefing(symbol) -> dict | None
    Return the most recent in-memory briefing for a symbol, or None.
"""

from __future__ import annotations

import calendar
import csv
import json
import logging
import re
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

import news_calendar
import briefing_emailer
import briefing_calibrator

logger = logging.getLogger("AutoBot")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str   = "claude-sonnet-4-5"
ANTHROPIC_URL: str     = "https://api.anthropic.com/v1/messages"
API_TIMEOUT: int       = 180  # seconds — full briefings at high max_tokens can exceed 60s under backend load
ANTHROPIC_TEMPERATURE: float = float(os.getenv("BRIEFING_TEMPERATURE", "0.3"))
# 2026-04-30: bumped from 6000 after EURUSD/London hit the cap on every
# attempt under heavy ECB news_risk content, leaving the briefing missing
# all session. Sized to comfortably hold the longest observed payload (~17 KB).
BRIEFING_MAX_TOKENS: int = int(os.getenv("BRIEFING_MAX_TOKENS", "12000") or 12000)

# Set BRIEFING_SCHEDULER_ENABLED=0 to skip the briefing scheduler on this machine.
# Useful when multiple instances share the same codebase but only one should fire.
BRIEFING_SCHEDULER_ENABLED: bool = (os.getenv("BRIEFING_SCHEDULER_ENABLED", "1") or "1").strip() == "1"

TELEGRAM_TOKEN:   str = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

LOG_DIR = Path(os.getenv("LOG_DIR", "/opt/tradingbot/logs"))

# 2026-04-28: London briefing fires at 05:30 UTC year-round — must complete
# before the 05:45 UTC premarket health check and the 06:00 UTC trading
# window open. Both tuples are interpreted as UTC by the scheduler, so
# they're identical (no longer following the BST/GMT split that
# anchored to 08:00 London local). The "London" name is preserved
# because strategies and the outcome tracker key off this string.
#
# 2026-05-06: NY briefing added at 12:30 UTC. Mirrors the v5_pia NY fire
# and lands ~57 min before the 14:30 BST NYSE cash open (or 30 min before
# under the worst-case 30-min retry budget). Both fires share the same
# pipeline — _run_briefing → _finalise_briefing → SendGrid email.
_SESSIONS_GMT: List[tuple] = [(5, 30, "London"), (12, 30, "NY")]
_SESSIONS_BST: List[tuple] = [(5, 30, "London"), (12, 30, "NY")]

# All session labels that may appear on disk as
# briefing_{SYMBOL}_{DATE}_{SESSION}.json. Broader than _SESSIONS_GMT/_BST,
# which only control when the scheduler fires the morning briefing — the
# disk loader needs every label that could exist (re-briefings emitted by
# briefing_execution and other code paths). Mirror of read_briefing.SESSIONS
# (commit 7ace531). Chronological order; _load_latest_briefing_for_today
# iterates reversed() so newer sessions win.
_BRIEFING_DISK_SESSIONS: List[str] = [
    "Asian",
    "London",
    "London_Open",
    "Mid-session",
    "NY",
    "NY_Data",
    "NY_Mid",
]


def _last_sunday(year: int, month: int) -> int:
    """Day-of-month of the last Sunday in the given month."""
    last_day = calendar.monthrange(year, month)[1]
    dow = datetime(year, month, last_day).weekday()  # Mon=0 … Sun=6
    return last_day - (dow + 1) % 7


def _is_bst(dt_utc: datetime) -> bool:
    """True if *dt_utc* (UTC) falls inside UK BST (UTC+1).

    BST runs from the last Sunday of March at 01:00 UTC
    to the last Sunday of October at 01:00 UTC.
    """
    y = dt_utc.year
    start = datetime(y, 3, _last_sunday(y, 3), 1, 0, tzinfo=timezone.utc)
    end   = datetime(y, 10, _last_sunday(y, 10), 1, 0, tzinfo=timezone.utc)
    return start <= dt_utc < end


def _get_sessions(now: datetime | None = None) -> List[tuple]:
    """Return the correct session schedule based on current BST/GMT status."""
    if now is None:
        now = datetime.now(timezone.utc)
    return _SESSIONS_BST if _is_bst(now) else _SESSIONS_GMT


def _is_fx_market_closed(now_utc: datetime | None = None) -> bool:
    """True when FX is closed: Saturday all day + Sunday before 21:00 UTC.

    FX reopens at the Sunday 22:00 UTC roll. The 21:00 cutoff gives a
    1-hour pre-open buffer so anything scheduled in the final hour can
    still fire if we ever add a Sunday-evening pre-Asian briefing.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    return now_utc.weekday() == 5 or (now_utc.weekday() == 6 and now_utc.hour < 21)


SESSIONS: List[tuple] = _get_sessions()

# Briefing trigger window — fire within this many minutes of scheduled time
SESSION_WINDOW_MINUTES: int = 5

# Currencies tracked per symbol for news filtering
SYMBOL_CURRENCIES: Dict[str, List[str]] = {
    "GBPUSD": ["GBP", "USD"],
    "EURUSD": ["EUR", "USD"],
    "USDJPY": ["USD", "JPY"],
    "USDCAD": ["USD", "CAD"],
    "GBPJPY": ["GBP", "JPY"],
}

# Fallback symbol list for the scheduler (supplemented by _ACTIVE_SYMBOLS at runtime).
# Narrow via BRIEFING_SYMBOLS env (comma-separated). On the 161 box this is the
# streamed-pairs set (GBPUSD,EURUSD); USDJPY/USDCAD briefing+execution were
# consolidated on the FXi (144) box.
_BRIEFING_SYMBOLS_ENV = (os.getenv("BRIEFING_SYMBOLS", "") or "").strip()
if _BRIEFING_SYMBOLS_ENV:
    DEFAULT_SYMBOLS: List[str] = [
        s.strip().upper() for s in _BRIEFING_SYMBOLS_ENV.split(",") if s.strip()
    ]
else:
    DEFAULT_SYMBOLS: List[str] = ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]

# Points-per-pip: imported from shared pair_config
from pair_config import POINTS_PER_PIP as _POINTS_PER_PIP

# MACD params — read from env to stay consistent with rest of bot
_MACD_FAST   = int(float(os.getenv("MACD_FAST",   "35") or 35))
_MACD_SLOW   = int(float(os.getenv("MACD_SLOW",   "45") or 45))
_MACD_SIGNAL = int(float(os.getenv("MACD_SIGNAL", "30") or 30))

SYSTEM_PROMPT = (
    "You are a professional FX market analyst with deep expertise in technical analysis, "
    "price action, liquidity theory, and session dynamics. "
    "You analyse markets top-down: Daily structure sets the dominant bias, then H4 confirms, "
    "then H1 refines timing, then 5M provides execution context. D1 always dominates. "
    "You understand liquidity pools, stop hunts, institutional order flow, and session-specific behaviour "
    "(Asian accumulation, London breakout/reversal, NY continuation/reversal). "
    "You identify key levels not just as price numbers but as liquidity zones where stops cluster "
    "and institutional orders are likely resting. "
    "You think probabilistically — you always consider multiple scenarios and assign realistic probabilities. "
    "You produce a structured JSON briefing only — no prose, no markdown. "
    "Your analysis must be specific and actionable, not generic."
)

RESPONSE_SCHEMA = {
    "symbol": "string",
    "session": "string",
    "briefing_time": "ISO8601 UTC string",
    "daily_bias": "BULLISH|BEARISH|NEUTRAL",
    "session_bias": "BULLISH|BEARISH|NEUTRAL (most likely direction for THIS session based on recent H1 momentum)",
    "bias_confidence": "0.0-1.0",
    "bias_change": "true|false — true if this session_bias differs from previous session's session_bias",
    "bias_reasoning": "specific explanation referencing actual price levels and structure",
    "session_expectation": "TREND|LIQUIDITY_HUNT|RANGE",
    "expectation_reasoning": "specific explanation referencing session dynamics",
    "regime": "SWEEP|TREND|NEWS",
    "regime_confidence": "0.0-1.0",
    "regime_reasoning": "one sentence explaining why this regime applies",
    "structure": "TRENDING|RANGE|NEUTRAL",
    "structure_confidence": "0.0-1.0",
    "structure_reasoning": "one sentence explaining why this structure applies",
    "bb_upper": "float — H1 Bollinger Band upper value (copy from data package)",
    "bb_lower": "float — H1 Bollinger Band lower value (copy from data package)",
    "key_levels": {
        "resistance": ["float x6-8 — all significant resistance levels, nearest first"],
        "support": ["float x6-8 — all significant support levels, nearest first"]
    },
    "major_levels": {
        "resistance": ["float — bb_upper MUST be first, then prev day high, round numbers, major pivots"],
        "support": ["float — bb_lower MUST be first, then prev day low, round numbers, major pivots"]
    },
    "session_high_estimate": "float — your best estimate of where the session high will print",
    "session_low_estimate": "float — your best estimate of where the session low will print",
    "liquidity_pools": {
        "buy_side": ["float"],
        "sell_side": ["float"]
    },
    "levels": [
        {
            "rank":            "int 1..6 — 1 is the most significant level for today; ranks must be unique and contiguous",
            "price":           "float — exact price",
            "type":            "RESISTANCE|SUPPORT|PIVOT",
            "role":            "primary|secondary|extension",
            "confluence":      ["PREV_DAY_HIGH|PREV_DAY_LOW|PREV_DAY_CLOSE|WEEK_HIGH|WEEK_LOW|PREV_WEEK_HIGH|PREV_WEEK_LOW|ASIAN_HIGH|ASIAN_LOW|SWING_HIGH|SWING_LOW|BB_UPPER|BB_LOWER|EMA_50|EMA_200|ROUND_NUMBER|DAILY_PIVOT|VWAP"],
            "justification":   "string (<= 30 words) — why this level matters today",
            "intent":           "BOUNCE|FADE|BREAK",
            "trade_direction":  "BUY|SELL|NONE",
            "strength":         "HIGH|MEDIUM|LOW"
        }
    ],
    "no_trade_zones": [["float", "float"]],
    "scenarios": [
        {
            "label": "string",
            "probability": "0.0-1.0",
            "trigger": "string",
            "target": "float",
            "invalidation": "string"
        }
    ],
    "trading_plans": [
        {
            "rank": "int (1=highest probability within its session)",
            "session": "London | NY — London plans active 06:45-12:30 UTC; NY plans gated by london_condition and active 12:30-21:00 UTC",
            "label": "string (e.g. Bearish continuation, Liquidity sweep then sell)",
            "raw_probability": "0.0-1.0 — your judgement of the setup's geometric merit BEFORE bias adjustment (set this; the bot then computes probability)",
            "probability": "0.0-1.0 — placeholder; the bot overwrites with raw_probability × bias multiplier",
            "confidence": "HIGH|MEDIUM|LOW",
            "bias": "LONG|SHORT",
            "entry_trigger": "string (specific price action required to enter)",
            "entry_trigger_v2": "list[object] — structured conditions, see vocabulary in prompt",
            "entry_zone": ["float", "float"],
            "stop_loss": "float",
            "targets": ["float", "float"],
            "risk_reward": "float",
            "invalidation": "string (what cancels this plan)",
            "london_condition": "null for London plans; for NY plans an object {type, level, [tolerance_pips], description} where type ∈ {close_above, close_below, ranged, swept_then_reversed, held_at}",
            "expires_at": "'12:30Z' (London-session-tied) | 'end_of_day' (active until 21:00 UTC) | ISO8601 UTC timestamp (explicit)",
            "notes": "string (session context, timing, confluences)"
        }
    ],
    "narrative_summary": "string (1-2 sentences: plain English summary of your directional reasoning for this session)",
    "plan_summary": "string (one sentence: the single highest-conviction trade idea for this session)",
    "news_risk": "HIGH|MEDIUM|LOW|NONE",
    "news_events": [],
    "news_context": {
        "has_high_impact": "true|false",
        "events": [{"time": "HH:MM UTC", "name": "string", "currency": "USD|GBP|EUR|JPY|CAD", "forecast": "string"}],
        "avoid_before": ["HH:MM UTC — REQUIRED whenever a high-impact release or instructed forced-exit applies. Include 30 min pre-release cutoffs AND any explicit exit-by/close-by/out-by times mentioned in news context (e.g. 'exit by 12:15 UTC' → '12:15')"],
        "most_affected_pairs": ["pairs most affected by today's events"],
        "note": "string — summary of how today's calendar affects this pair"
    },
    "signal_filter": {
        "allow_buys": "true|false  (false when session_bias is BEARISH)",
        "allow_sells": "true|false  (false when session_bias is BULLISH)",
        "notes": "string"
    },
    "sweep_direction": "BUY|SELL|NONE — which side the liquidity sweep is expected on this session",
    "fade_after_sweep": "true|false — true if the primary play is to enter after the sweep exhausts; false for trend continuation",
    "pre_event_blackout": {
        "start_utc": "HH:MM — 15 min before the next HIGH impact release (null if no HIGH impact event today)",
        "end_utc":   "HH:MM —  5 min after that release (null if no HIGH impact event today)"
    },
    "session_stage_intent": {
        "london": "SWEEP|TREND|RANGE|UNKNOWN — what London session is expected to do",
        "ny":     "SWEEP|TREND|RANGE|CONTINUATION|REVERSAL|UNKNOWN — what NY session is expected to do"
    },
    "best_trade": {
        "_doc": "Optional. Structured pointer to the primary trade for today. "
                "Translation of the plan_summary prose into a machine-readable "
                "selection over trading_plans. May be null when plan_summary is "
                "ambiguous or no clean primary direction exists; in that case "
                "set best_trade_omission_reason instead.",
        "mode": "UNCONDITIONAL|CONDITIONAL",
        "plan_rank":    "int — required when mode=UNCONDITIONAL; null when mode=CONDITIONAL. "
                        "References the rank of the matching trading_plans entry within its session.",
        "plan_session": "London|NY — required when mode=UNCONDITIONAL; null when mode=CONDITIONAL. "
                        "Disambiguates plan_rank since rank is unique only within a session.",
        "conditional_branches": [
            {
                "_doc": "Required when mode=CONDITIONAL. Each branch references one trading_plan.",
                "condition_text": "string — natural-language description of when this branch applies "
                                  "(e.g. 'BoE hawkish', 'London breaks above 13526.9')",
                "plan_rank":    "int — rank of the matching trading_plans entry",
                "plan_session": "London|NY — disambiguates plan_rank"
            }
        ],
        "reasoning": "string (1 sentence) — your justification for this selection. "
                     "Distinct from plan_summary: plan_summary is the human prose summary, "
                     "best_trade.reasoning explains why this structured pointer is the right one."
    },
    "best_trade_omission_reason": "string|null — optional. When best_trade is null, "
                                  "a single sentence explaining why no clean primary "
                                  "direction was selected (e.g. 'plan_summary describes "
                                  "wait-and-see posture before BoE')."
}

# ─────────────────────────────────────────────────────────────────────────────
# Module state — injected via start()
# ─────────────────────────────────────────────────────────────────────────────

_TF_CTX    = None   # TimeframeContext instance
_BUILDER   = None   # CandleBuilder5M instance

_LOCK                            = threading.Lock()
_BRIEFING_LOCK                   = threading.Lock()   # guards _BRIEFED_SESSIONS check-and-mark
_BRIEFINGS:      Dict[str, Any]  = {}   # symbol → latest briefing dict
_HTF_SNAPSHOTS:  Dict[str, Any]  = {}   # symbol → latest HTF snapshot dict
_ACTIVE_SYMBOLS: set             = set()

# (symbol, session) → reason why the last _refresh_symbol call returned None.
# Populated at each failure path inside _refresh_symbol / _assemble_data_package
# so _run_briefing_once can surface the real cause in alerts/results rather
# than the historical "API timeout or parse error" catch-all.
_LAST_REFRESH_SKIP_REASON: Dict[Any, str] = {}

# (symbol, session) → specific Anthropic-side failure class recorded by
# _call_anthropic_once when the HTTP call or JSON parse fails. Distinguishes
# HTTP status + body (e.g. 400 credit-balance), timeout, and parse error so
# _refresh_symbol can propagate the real reason instead of the historical
# "timeout or parse error" catch-all. Popped in _refresh_symbol after use.
_LAST_ANTHROPIC_FAILURE_REASON: Dict[Any, str] = {}

# Scheduler tracking — keyed by "SESSION_DATE" so stale entries are naturally inert
_BRIEFED_SESSIONS: Dict[str, str] = {}

# v5 (briefing.v5_pia) parallel scheduler. Independent dedup map so the v5
# fire decisions cannot collide with v4. v5-specific session list:
#   London 05:30 UTC  (parallel to v4 — same trigger, separate output JSON)
#   NY     12:30 UTC  (new fire — v4 packs NY plans inside the London JSON)
# Phase 1 deliberate: see briefing/v5_pia/PHASE1_README.md.
_SESSIONS_V5: List[tuple] = [(5, 30, "London"), (12, 30, "NY")]
_BRIEFED_SESSIONS_V5: Dict[str, str] = {}
_BRIEFING_V5_LOCK = threading.Lock()

# PIA_FIRST (pia_first_briefing.py) parallel scheduler. Independent dedup
# map so the new producer's fire decisions cannot collide with v4 or v5.
# Single daily fire at 05:30 UTC — one LLM call per pair, one plan per pair.
# Gated by PIA_FIRST_ENABLED env flag — disabled on current droplet,
# enabled on the AutoBot-PIA droplet (2026-05-13).
_SESSIONS_PIA_FIRST: List[tuple] = [(5, 30, "London")]
_BRIEFED_SESSIONS_PIA_FIRST: Dict[str, str] = {}
_BRIEFING_PIA_FIRST_LOCK = threading.Lock()

_stop_event = threading.Event()

# ── OS-level file lock for scheduler mutual exclusion ──
import fcntl

_SCHEDULER_LOCK_PATH = os.path.join(
    os.getenv("CACHE_DIR", "/opt/tradingbot/cache"), "briefing_scheduler.lock"
)
_scheduler_lock_file = None


def _acquire_scheduler_lock() -> bool:
    """Try to acquire an exclusive OS-level flock. Returns True if we own it."""
    global _scheduler_lock_file
    try:
        _scheduler_lock_file = open(_SCHEDULER_LOCK_PATH, "w")
        fcntl.flock(_scheduler_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _scheduler_lock_file.write(str(os.getpid()))
        _scheduler_lock_file.flush()
        logger.info("[morning_briefing] Acquired scheduler lock (PID %d)", os.getpid())
        return True
    except IOError:
        logger.warning(
            "[morning_briefing] Scheduler lock held by another process — not starting duplicate"
        )
        if _scheduler_lock_file:
            _scheduler_lock_file.close()
            _scheduler_lock_file = None
        return False


def _release_scheduler_lock() -> None:
    """Release the OS-level flock."""
    global _scheduler_lock_file
    if _scheduler_lock_file:
        try:
            fcntl.flock(_scheduler_lock_file, fcntl.LOCK_UN)
            _scheduler_lock_file.close()
            logger.info("[morning_briefing] Released scheduler lock (PID %d)", os.getpid())
        except Exception:
            pass
        _scheduler_lock_file = None


import atexit
atexit.register(_release_scheduler_lock)


# ── Per-session disk lock (prevents duplicate briefings across restarts) ──

_CACHE_DIR = Path(os.getenv("CACHE_DIR", "/opt/tradingbot/cache"))


def _session_lock_path(session: str, date: str) -> Path:
    """Return path for the atomic session lock file."""
    return _CACHE_DIR / f"briefing_fired_{session}_{date}.lock"


def _try_claim_session(session: str, date: str) -> bool:
    """Atomically claim a briefing session via O_CREAT|O_EXCL lock file.

    Returns True if this call created the lock (caller should fire).
    Returns False if the lock already exists (briefing already fired/firing).
    """
    lp = _session_lock_path(session, date)
    lp.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        logger.info("[morning_briefing] Claimed session lock: %s", lp.name)
        return True
    except FileExistsError:
        logger.info("[morning_briefing] Session lock exists: %s — already fired", lp.name)
        return False


def _cleanup_old_session_locks(today: str) -> None:
    """Remove session lock files from previous days."""
    for lf in _CACHE_DIR.glob("briefing_fired_*.lock"):
        if today not in lf.name:
            try:
                lf.unlink()
            except OSError:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Small utilities
# ─────────────────────────────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_today() -> str:
    return _utc_now().strftime("%Y-%m-%d")


def _ewm(series: pd.Series, period: int) -> pd.Series:
    """EWM with adjust=False, min_periods=1 — suitable for small sample sizes."""
    return series.ewm(span=period, adjust=False, min_periods=1).mean()

# ─────────────────────────────────────────────────────────────────────────────
# Data assembly helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_candles(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Serialise TF_CTX candle dicts for the prompt payload."""
    out = []
    for c in candles:
        try:
            ts = c.get("time", "")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            out.append({
                "t": str(ts),
                "o": round(float(c["open"]),  5),
                "h": round(float(c["high"]),  5),
                "l": round(float(c["low"]),   5),
                "c": round(float(c["close"]), 5),
            })
        except Exception:
            pass
    return out


def _emas_from_closes(closes: List[float], periods=(8, 13, 21, 50, 200)) -> Dict[str, float]:
    """Compute EMA stack from a list of closes. Returns only periods with enough data."""
    if not closes:
        return {}
    s = pd.Series(closes, dtype="float64")
    out: Dict[str, float] = {}
    for p in periods:
        if len(s) >= max(3, p // 4):   # loose threshold — briefing context, not bias calc
            v = float(_ewm(s, p).iloc[-1])
            if pd.notna(v):
                out[str(p)] = round(v, 5)
    return out


def _h1_momentum_summary(h1_candles: List[Dict[str, Any]], n: int = 6) -> str:
    """Produce a plain-English summary of the last N H1 candles' momentum."""
    if not h1_candles or len(h1_candles) < 2:
        return "insufficient H1 data"
    tail = h1_candles[-n:] if len(h1_candles) >= n else h1_candles
    closes = []
    for c in tail:
        try:
            closes.append(float(c["close"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(closes) < 2:
        return "insufficient H1 close data"

    # Count consecutive higher/lower closes from most recent backward
    consec_dir = 0  # positive = higher, negative = lower
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            if consec_dir <= 0 and consec_dir != 0:
                break
            consec_dir += 1
        elif closes[i] < closes[i - 1]:
            if consec_dir >= 0 and consec_dir != 0:
                break
            consec_dir -= 1
        else:
            break

    total_move = round(closes[-1] - closes[0], 1)
    hours = len(closes)
    abs_consec = abs(consec_dir)

    if consec_dir > 0:
        direction = "higher"
        trend = "short-term uptrend"
    elif consec_dir < 0:
        direction = "lower"
        trend = "short-term downtrend"
    else:
        direction = "flat"
        trend = "no clear trend"

    return (
        f"{abs_consec} consecutive {direction} closes out of last {hours} H1 candles, "
        f"{'+' if total_move > 0 else ''}{total_move} points over {hours} hours, "
        f"{trend}"
    )


def _ema_alignment_summary(
    current_price: float,
    ema_h1: Dict[str, float],
) -> str:
    """Produce a plain-English EMA alignment summary for H1."""
    if not ema_h1:
        return "no H1 EMA data available"
    periods = sorted(ema_h1.keys(), key=lambda k: int(k))
    above = [p for p in periods if current_price > ema_h1[p]]
    below = [p for p in periods if current_price < ema_h1[p]]

    if len(below) == len(periods) and len(periods) >= 3:
        return f"price below all H1 EMAs ({'/'.join(periods)}) — bearish alignment"
    if len(above) == len(periods) and len(periods) >= 3:
        return f"price above all H1 EMAs ({'/'.join(periods)}) — bullish alignment"
    if above and below:
        return (
            f"price above EMA {'/'.join(above)} but below EMA {'/'.join(below)} — mixed alignment"
        )
    return "EMA data inconclusive"


def _macd_hist_from_closes(closes: List[float]) -> Optional[float]:
    """Compute MACD histogram from closes using bot's configured params."""
    min_needed = max(_MACD_FAST, _MACD_SLOW) + _MACD_SIGNAL
    if len(closes) < min_needed // 2:   # allow partial warmup
        return None
    try:
        s = pd.Series(closes, dtype="float64")
        fast_ema   = _ewm(s, _MACD_FAST)
        slow_ema   = _ewm(s, _MACD_SLOW)
        macd_line  = fast_ema - slow_ema
        signal_line = _ewm(macd_line, _MACD_SIGNAL)
        hist = float((macd_line - signal_line).iloc[-1])
        return round(hist, 6) if pd.notna(hist) else None
    except Exception:
        return None


def _read_recent_signals(symbol: str, n: int = 3) -> List[Dict[str, str]]:
    """Read last n BUY/SELL entries for symbol from today's sweep journal CSV."""
    path = LOG_DIR / f"sweep_journal_{_utc_today()}.csv"
    if not path.exists():
        return []
    try:
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))
        sym_rows = [
            r for r in rows
            if r.get("symbol", "").upper() == symbol
            and r.get("signal", "").upper() in ("BUY", "SELL")
        ]
        out = []
        for r in sym_rows[-n:]:
            out.append({
                "direction":    r.get("signal", ""),
                "taken":        r.get("taken", ""),
                "pnl_pips":     r.get("pnl_pips", ""),
                "close_reason": r.get("close_reason", ""),
            })
        return out
    except Exception as exc:
        logger.debug(f"[morning_briefing] sweep journal read error for {symbol}: {exc}")
        return []


def _assemble_data_package(symbol: str, session: str) -> Optional[Dict[str, Any]]:
    """
    Build the full data package for a symbol/session API call.
    Returns None if critical data is missing (signals skip, not crash).
    On skip, records the precise reason in _LAST_REFRESH_SKIP_REASON so the
    caller surfaces it instead of the historical catch-all alert text.
    """
    sym = symbol.upper()
    if _BUILDER is None or _TF_CTX is None:
        logger.warning("[morning_briefing] start() not yet called — cannot assemble package")
        _LAST_REFRESH_SKIP_REASON[(sym, session)] = "start() not yet called (BUILDER/TF_CTX unset)"
        return None

    # ── 5M data ───────────────────────────────────────────────────────────────
    try:
        df_5m = _BUILDER.get_df(sym)
    except Exception as exc:
        logger.warning(f"[morning_briefing] {sym}: get_df failed: {exc}")
        _LAST_REFRESH_SKIP_REASON[(sym, session)] = f"5M get_df raised: {type(exc).__name__}: {str(exc)[:80]}"
        return None

    if df_5m is None or not isinstance(df_5m, pd.DataFrame) or len(df_5m) < 3:
        _bars = len(df_5m) if isinstance(df_5m, pd.DataFrame) else 0
        logger.warning(f"[morning_briefing] {sym}: insufficient 5M data ({_bars} bars) — skipping")
        _LAST_REFRESH_SKIP_REASON[(sym, session)] = f"insufficient 5M data ({_bars} bars; pair likely not streamed on this box)"
        return None

    current_price: float = round(float(df_5m["close"].iloc[-1]), 5)

    # 5M EMAs from cached indicator columns
    ema_5m: Dict[str, float] = {}
    for p in (8, 13, 21, 50, 200):
        col = f"EMA_{p}"
        if col in df_5m.columns:
            v = df_5m[col].iloc[-1]
            if pd.notna(v):
                ema_5m[str(p)] = round(float(v), 5)

    # 5M RSI — column named RSI_{period} by indicators.py
    rsi_5m: Optional[float] = None
    for col in ("RSI_3", "RSI_14", "RSI"):
        if col in df_5m.columns:
            v = df_5m[col].iloc[-1]
            if pd.notna(v):
                rsi_5m = round(float(v), 2)
                break

    # ── HTF candle lists from TimeframeContext ─────────────────────────────────
    h1_candles  = list(_TF_CTX._h1_closed.get(sym, []))[-20:]
    h4_candles  = list(_TF_CTX._h4_closed.get(sym, []))[-20:]
    d1_candles  = list(_TF_CTX._d1_closed.get(sym, []))[-20:]

    # H1 indicator values computed locally from H1 closes
    h1_closes = [float(c["close"]) for c in h1_candles if "close" in c]
    ema_h1    = _emas_from_closes(h1_closes)
    macd_h1_hist = _macd_hist_from_closes(h1_closes)

    # BB(20,2) from H1 closes — primary entry levels for BRIEFING_LIQUIDITY
    bb_upper = None
    bb_lower = None
    if len(h1_closes) >= 20:
        _bb_window = h1_closes[-20:]
        _bb_sma = sum(_bb_window) / 20.0
        _bb_var = sum((x - _bb_sma) ** 2 for x in _bb_window) / 20.0
        _bb_std = _bb_var ** 0.5
        bb_upper = round(_bb_sma + 2 * _bb_std, 5)
        bb_lower = round(_bb_sma - 2 * _bb_std, 5)

    # Pre-computed summaries for the prompt
    h1_momentum = _h1_momentum_summary(h1_candles)
    ema_alignment = _ema_alignment_summary(current_price, ema_h1)

    # ── Previous day / week structure from D1 candles ─────────────────────────
    prev_day_high = prev_day_low = prev_day_close = None
    week_high = week_low = prev_week_high = prev_week_low = None
    if len(d1_candles) >= 2:
        prev = d1_candles[-2]
        prev_day_high  = round(float(prev.get("high", 0)), 5)
        prev_day_low   = round(float(prev.get("low", 0)), 5)
        prev_day_close = round(float(prev.get("close", 0)), 5)
    # Current week = last 5 D1 candles (Mon-Fri), prev week = 5 before that
    if len(d1_candles) >= 5:
        this_week = d1_candles[-5:]
        week_high = round(max(float(c.get("high", 0)) for c in this_week), 5)
        week_low  = round(min(float(c.get("low", 0)) for c in this_week), 5)
    if len(d1_candles) >= 10:
        last_week = d1_candles[-10:-5]
        prev_week_high = round(max(float(c.get("high", 0)) for c in last_week), 5)
        prev_week_low  = round(min(float(c.get("low", 0)) for c in last_week), 5)

    # ── Price relative to key H1 EMAs ─────────────────────────────────────────
    _ppp = _POINTS_PER_PIP.get(sym, 1.0)
    price_vs_h1_ema200 = None
    price_vs_h1_ema50 = None
    h1_ema_trend = "NEUTRAL"
    ema200_val = ema_h1.get("200")
    ema50_val = ema_h1.get("50")
    if ema200_val is not None:
        price_vs_h1_ema200 = round((current_price - float(ema200_val)) / _ppp, 1)
    if ema50_val is not None:
        price_vs_h1_ema50 = round((current_price - float(ema50_val)) / _ppp, 1)
    if ema50_val is not None and ema200_val is not None:
        ema_diff_pips = (float(ema50_val) - float(ema200_val)) / _ppp
        if ema_diff_pips > 5:
            h1_ema_trend = "BULLISH"
        elif ema_diff_pips < -5:
            h1_ema_trend = "BEARISH"

    # ── Volatility context from D1 candles ────────────────────────────────────
    atr_today_pips = None
    atr_20day_avg_pips = None
    volatility_regime = "NORMAL"
    if d1_candles:
        today_d1 = d1_candles[-1]
        atr_today_pips = round((float(today_d1.get("high", 0)) - float(today_d1.get("low", 0))) / _ppp, 1)
    if len(d1_candles) >= 20:
        daily_ranges = [(float(c.get("high", 0)) - float(c.get("low", 0))) / _ppp for c in d1_candles[-20:]]
        atr_20day_avg_pips = round(sum(daily_ranges) / len(daily_ranges), 1)
        if atr_today_pips and atr_20day_avg_pips > 0:
            ratio = atr_today_pips / atr_20day_avg_pips
            if ratio > 1.2:
                volatility_regime = "HIGH"
            elif ratio < 0.8:
                volatility_regime = "LOW"

    # ── Recent briefing accuracy feedback ─────────────────────────────────────
    recent_accuracy = []
    accuracy_pct = None
    try:
        _acc_path = Path("/opt/tradingbot/data/briefing_accuracy.jsonl")
        if _acc_path.exists():
            import json as _json
            all_entries = []
            with open(_acc_path) as _af:
                for line in _af:
                    line = line.strip()
                    if line:
                        try:
                            entry = _json.loads(line)
                            if str(entry.get("symbol", "")).upper() == sym:
                                all_entries.append(entry)
                        except Exception:
                            pass
            recent_accuracy = all_entries[-5:]
            assessable = [e for e in recent_accuracy if e.get("correct") is not None]
            if assessable:
                accuracy_pct = round(sum(1 for e in assessable if e["correct"]) / len(assessable) * 100, 0)
    except Exception:
        pass

    # ── HTF bias from last snapshot ────────────────────────────────────────────
    snap = _HTF_SNAPSHOTS.get(sym, {})
    htf_bias = {
        "h1": snap.get("h1_bias", "NEUTRAL"),
        "h4": snap.get("h4_bias", "NEUTRAL"),
        "d1": snap.get("d1_bias", "NEUTRAL"),
    }

    # ── News events ────────────────────────────────────────────────────────────
    currencies  = SYMBOL_CURRENCIES.get(sym, ["USD"])
    news_events = news_calendar.get_todays_events(currencies)

    # ── Recent sweep signals ───────────────────────────────────────────────────
    recent_signals = _read_recent_signals(sym, n=3)

    _now = datetime.now(timezone.utc)

    # ── Previous session bias for bias_change detection ────────────────────────
    prev_session_bias = None
    try:
        prev_briefing = _BRIEFINGS.get(sym)
        if prev_briefing:
            prev_session_bias = str(prev_briefing.get("session_bias", "")).upper() or None
    except Exception:
        pass

    # ── USD strength proxy via a multi-pair basket ────────────────────────
    # Bug 2 of docs/briefing_producer_audit_2026-05-11.md: the USDJPY-only
    # proxy produced identical values for GBPUSD and EURUSD (both pulled
    # from the same source) and was contaminated by JPY-specific moves.
    # The basket excludes the pair being briefed and normalises each
    # contributor by its own typical H1 range. Narrative input only —
    # daily_bias is bound deterministically (see Bug 1 fix).
    usd_proxy_bias: Optional[str] = None
    usd_proxy_pips: Optional[float] = None
    usd_proxy_method: Optional[str] = None
    usd_proxy_contributors: List[str] = []
    usd_proxy_reason: Optional[str] = None
    if _TF_CTX is not None:
        try:
            from usd_strength import compute_usd_strength
            _buffers = {
                p: list(_TF_CTX._h1_closed.get(p, []))
                for p in ("USDJPY", "USDCAD", "USDCHF", "EURUSD",
                         "GBPUSD", "AUDUSD", "NZDUSD")
            }
            _usd = compute_usd_strength(sym, _buffers, lookback_bars=6)
            usd_proxy_bias        = _usd["usd_proxy_bias"]
            usd_proxy_pips        = _usd["usd_proxy_pips"]
            usd_proxy_method      = _usd["method"]
            usd_proxy_contributors = list(_usd["contributing_pairs"])
            usd_proxy_reason      = _usd["reason"]
        except Exception as _us_exc:
            logger.warning(
                "[morning_briefing] %s/%s: usd_strength failed (%s) — "
                "prompt will omit the USD proxy block",
                sym, session, _us_exc,
            )

    # ── Deterministic D1 direction (single source of truth for daily_bias) ───
    # Loaded from HTF cache so it is identical to what d1_veto sees, and to
    # sidestep the cold-start gap on _TF_CTX._d1_closed after a restart.
    # Bug 1 of docs/briefing_producer_audit_2026-05-11.md.
    d1_direction_detail: Optional[Dict[str, Any]] = None
    try:
        from d1_direction import compute_d1_direction_from_cache
        d1_direction_detail = compute_d1_direction_from_cache(sym)
    except Exception as _dd_exc:
        logger.warning(
            "[morning_briefing] %s/%s: compute_d1_direction failed (%s) — "
            "daily_bias will fall through to LLM value as before",
            sym, session, _dd_exc,
        )

    # ── Previous session actual direction & move ──────────────────────────────
    prev_session_actual_direction = None
    prev_session_pip_move = None
    try:
        if prev_briefing and _BUILDER is not None:
            _prev_df = _BUILDER.get_df(sym)
            if _prev_df is not None and len(_prev_df) >= 20:
                # Previous session = last 12 candles worth of 5M data (1 hour)
                # Use a simpler heuristic: direction of last 12 candles before this briefing
                _tail = _prev_df.tail(12)
                _p_open = float(_tail.iloc[0]["open"])
                _p_close = float(_tail.iloc[-1]["close"])
                _p_move = (_p_close - _p_open) / _ppp
                prev_session_pip_move = round(_p_move, 1)
                if _p_move > 3:
                    prev_session_actual_direction = "UP"
                elif _p_move < -3:
                    prev_session_actual_direction = "DOWN"
                else:
                    prev_session_actual_direction = "FLAT"
    except Exception:
        pass

    return {
        "symbol":            sym,
        "current_price":     current_price,
        "session":           session,
        "briefing_date":     _now.strftime("%Y-%m-%d"),
        "briefing_time_utc": _now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "d1_candles":        _fmt_candles(d1_candles),
        "h4_candles":        _fmt_candles(h4_candles),
        "h1_candles":        _fmt_candles(h1_candles),
        "ema_5m":            ema_5m,
        "ema_h1":            ema_h1,
        "h1_ema_values":     {k: v for k, v in ema_h1.items() if k in ("8", "13", "21", "50")},
        "htf_bias":          htf_bias,
        "macd_h1_hist":      macd_h1_hist,
        "rsi_5m":            rsi_5m,
        "h1_momentum_summary": h1_momentum,
        "ema_alignment":     ema_alignment,
        "bb_upper":          bb_upper,
        "bb_lower":          bb_lower,
        "news_events":       news_events,
        "recent_signals":    recent_signals,
        # Enhancement 1 — Previous day/week structure
        "prev_day_high":     prev_day_high,
        "prev_day_low":      prev_day_low,
        "prev_day_close":    prev_day_close,
        "week_high":         week_high,
        "week_low":          week_low,
        "prev_week_high":    prev_week_high,
        "prev_week_low":     prev_week_low,
        # Enhancement 2 — Price vs key EMAs
        "price_vs_h1_ema200_pips": price_vs_h1_ema200,
        "price_vs_h1_ema50_pips":  price_vs_h1_ema50,
        "h1_ema_trend":      h1_ema_trend,
        # Enhancement 3 — Volatility context
        "atr_today_pips":    atr_today_pips,
        "atr_20day_avg_pips": atr_20day_avg_pips,
        "volatility_regime": volatility_regime,
        # Enhancement 4 — Recent accuracy
        "recent_accuracy":   recent_accuracy,
        "accuracy_last_5":   accuracy_pct,
        # Enhancement 5 — Previous session bias for flip detection
        "prev_session_bias": prev_session_bias,
        # Enhancement 6 — USD proxy via multi-pair basket (Bug 2 fix)
        "usd_proxy_bias":         usd_proxy_bias,
        "usd_proxy_pips":         usd_proxy_pips,
        "usd_proxy_method":       usd_proxy_method,
        "usd_proxy_contributors": usd_proxy_contributors,
        "usd_proxy_reason":       usd_proxy_reason,
        # Enhancement 7 — Previous session actual performance
        "prev_session_actual_direction": prev_session_actual_direction,
        "prev_session_pip_move": prev_session_pip_move,
        # Bug 1 fix — deterministic D1 direction (overrides LLM daily_bias)
        "d1_direction_detail": d1_direction_detail,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Anthropic API call
# ─────────────────────────────────────────────────────────────────────────────

def _derive_session_bias_from_h1(data_package: Dict[str, Any]) -> Optional[str]:
    """Derive session_bias from H1 candle momentum when the model omits it.

    Uses last 6 H1 candles: net positive → BULLISH, net negative → BEARISH,
    flat → None (caller should fall back to daily_bias).
    """
    try:
        h1_candles = data_package.get("h1_candles") or []
        if not h1_candles:
            return None
        tail = h1_candles[-6:] if len(h1_candles) >= 6 else h1_candles
        closes = []
        for c in tail:
            if isinstance(c, dict) and "close" in c:
                closes.append(float(c["close"]))
            elif isinstance(c, dict) and "c" in c:
                closes.append(float(c["c"]))
        if len(closes) < 2:
            return None
        ppp = _POINTS_PER_PIP.get(str(data_package.get("symbol", "")).upper(), 1.0)
        move_pips = (closes[-1] - closes[0]) / ppp
        if move_pips > 3:
            return "BULLISH"
        elif move_pips < -3:
            return "BEARISH"
        return None
    except Exception:
        return None


def calculate_session_bias(data_package: Dict[str, Any]) -> str:
    """Calculate session_bias from market data — no API involvement.

    BEARISH if ANY TWO of:
      1. H1 price below H1 EMA 200
      2. H1 EMA 8 < EMA 21 < EMA 50
      3. Yesterday closed lower than it opened
      4. Price below last week's midpoint

    BULLISH if ANY TWO of the mirror conditions.

    NEUTRAL only if exactly 2 bearish and 2 bullish cancel out.
    """
    sym = str(data_package.get("symbol", "")).upper()

    # --- Extract H1 EMA values ---
    ema_h1 = data_package.get("ema_h1") or {}
    ema8  = ema_h1.get("8")
    ema21 = ema_h1.get("21")
    ema50 = ema_h1.get("50")
    ema200 = ema_h1.get("200")
    current_price = data_package.get("current_price")

    # --- Extract D1 candles for yesterday ---
    d1_candles = data_package.get("d1_candles") or []
    yesterday_open = None
    yesterday_close = None
    if len(d1_candles) >= 2:
        prev = d1_candles[-2]
        if isinstance(prev, dict):
            yesterday_open  = prev.get("o") or prev.get("open")
            yesterday_close = prev.get("c") or prev.get("close")
        if yesterday_open is not None:
            yesterday_open = float(yesterday_open)
        if yesterday_close is not None:
            yesterday_close = float(yesterday_close)

    # --- Last week's midpoint ---
    pw_high = data_package.get("prev_week_high")
    pw_low  = data_package.get("prev_week_low")
    week_mid = None
    if pw_high is not None and pw_low is not None:
        week_mid = (float(pw_high) + float(pw_low)) / 2.0

    # --- Score each signal ---
    bullish = 0
    bearish = 0

    # Signal 1: Price vs H1 EMA 200
    if current_price is not None and ema200 is not None:
        if float(current_price) > float(ema200):
            bullish += 1
        elif float(current_price) < float(ema200):
            bearish += 1

    # Signal 2: EMA fan alignment (8 vs 21 vs 50)
    if ema8 is not None and ema21 is not None and ema50 is not None:
        e8, e21, e50 = float(ema8), float(ema21), float(ema50)
        if e8 > e21 > e50:
            bullish += 1
        elif e8 < e21 < e50:
            bearish += 1

    # Signal 3: Yesterday's close vs open
    if yesterday_open is not None and yesterday_close is not None:
        if yesterday_close > yesterday_open:
            bullish += 1
        elif yesterday_close < yesterday_open:
            bearish += 1

    # Signal 4: Price vs last week's midpoint
    if current_price is not None and week_mid is not None:
        if float(current_price) > week_mid:
            bullish += 1
        elif float(current_price) < week_mid:
            bearish += 1

    logger.info(
        "[morning_briefing] %s calculated_bias: bullish=%d bearish=%d "
        "(ema200=%s, fan=%s/%s/%s, yday_o=%s yday_c=%s, week_mid=%s, price=%s)",
        sym, bullish, bearish,
        ema200, ema8, ema21, ema50,
        yesterday_open, yesterday_close, week_mid, current_price,
    )

    if bullish >= 2 and bearish >= 2:
        return "NEUTRAL"
    if bearish >= 2:
        return "BEARISH"
    if bullish >= 2:
        return "BULLISH"
    # Fewer than 2 in either direction (e.g. 1-1, 1-0, 0-0) — insufficient conviction
    return "NEUTRAL"


def _calc_bias_confidence(data_package: Dict[str, Any]) -> float:
    """Return a confidence score (0.0–1.0) for the calculated session_bias.

    Counts how many of the 4 market-data signals agree with the winning direction.
    """
    sym = str(data_package.get("symbol", "")).upper()
    ema_h1 = data_package.get("ema_h1") or {}
    current_price = data_package.get("current_price")
    d1_candles = data_package.get("d1_candles") or []
    pw_high = data_package.get("prev_week_high")
    pw_low = data_package.get("prev_week_low")

    directional = 0  # count of signals that agree with majority direction
    total = 0

    ema200 = ema_h1.get("200")
    ema8 = ema_h1.get("8")
    ema21 = ema_h1.get("21")
    ema50 = ema_h1.get("50")

    if current_price is not None and ema200 is not None:
        total += 1
    if ema8 is not None and ema21 is not None and ema50 is not None:
        e8, e21, e50 = float(ema8), float(ema21), float(ema50)
        if e8 > e21 > e50 or e8 < e21 < e50:
            total += 1
    if len(d1_candles) >= 2:
        prev = d1_candles[-2]
        yo = prev.get("o") or prev.get("open")
        yc = prev.get("c") or prev.get("close")
        if yo is not None and yc is not None and float(yo) != float(yc):
            total += 1
    if pw_high is not None and pw_low is not None and current_price is not None:
        wm = (float(pw_high) + float(pw_low)) / 2.0
        if float(current_price) != wm:
            total += 1

    # Re-run the bias calc to get bull/bear counts
    bias = calculate_session_bias(data_package)
    # Reconstruct counts from the bias result
    # 4 aligned → 0.85, 3 → 0.75, 2 → 0.68
    bullish = bearish = 0
    if current_price is not None and ema200 is not None:
        if float(current_price) > float(ema200):
            bullish += 1
        elif float(current_price) < float(ema200):
            bearish += 1
    if ema8 is not None and ema21 is not None and ema50 is not None:
        e8, e21, e50 = float(ema8), float(ema21), float(ema50)
        if e8 > e21 > e50:
            bullish += 1
        elif e8 < e21 < e50:
            bearish += 1
    if len(d1_candles) >= 2:
        prev = d1_candles[-2]
        yo = prev.get("o") or prev.get("open")
        yc = prev.get("c") or prev.get("close")
        if yo is not None and yc is not None:
            if float(yc) > float(yo):
                bullish += 1
            elif float(yc) < float(yo):
                bearish += 1
    if pw_high is not None and pw_low is not None and current_price is not None:
        wm = (float(pw_high) + float(pw_low)) / 2.0
        if float(current_price) > wm:
            bullish += 1
        elif float(current_price) < wm:
            bearish += 1

    dominant = max(bullish, bearish)
    if dominant >= 4:
        return 0.85
    if dominant >= 3:
        return 0.75
    if dominant >= 2:
        return 0.68
    return 0.50


def _slim_data_package(pkg: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of pkg with candle lists trimmed to 10 bars for retry."""
    slimmed = dict(pkg)
    for key in ("d1_candles", "h4_candles", "h1_candles"):
        if key in slimmed and isinstance(slimmed[key], list):
            slimmed[key] = slimmed[key][-10:]
    return slimmed


def _build_calendar_section(sym: str, pkg: Dict[str, Any]) -> str:
    """Build the TODAY'S ECONOMIC CALENDAR section for the briefing prompt."""
    try:
        # Fetch ALL high-impact events (all currencies) for full context
        all_events = news_calendar.get_todays_events(
            currencies=["USD", "GBP", "EUR", "JPY", "CAD"]
        )
        if not all_events:
            return ""

        lines = ["=== TODAY'S ECONOMIC CALENDAR ===\n"]
        for e in sorted(all_events, key=lambda x: x.get("time", "")):
            t = e.get("time", "??:??")
            # Convert UTC to BST (UTC+1 during summer)
            try:
                h, m = int(t.split(":")[0]), int(t.split(":")[1])
                bst_h = (h + 1) % 24
                bst_str = f"{bst_h:02d}:{m:02d} BST"
            except Exception:
                bst_str = f"{t} UTC"
            name = e.get("event_name", "?")
            ccy = e.get("currency", "?")
            forecast = e.get("forecast", "")
            previous = e.get("previous", "")
            fc_str = f"forecast={forecast}" if forecast else "no forecast"
            pv_str = f"previous={previous}" if previous else ""
            lines.append(f"  {bst_str} ({t} UTC) | {ccy} | {name} | {fc_str} {pv_str}".rstrip())

        # Pair-specific relevance
        pair_ccys = SYMBOL_CURRENCIES.get(sym, ["USD"])
        relevant = [e for e in all_events if e.get("currency", "") in pair_ccys]

        lines.append("")
        lines.append("Consider how these events affect your analysis:")
        lines.append("- Should entries be avoided before major releases?")
        lines.append("- Will the release likely reset directional bias for affected pairs?")
        lines.append("- Are current technical levels still valid post-release or will they be superseded?")
        lines.append(f"- Which events directly affect {sym}? (currencies: {', '.join(pair_ccys)})")
        if relevant:
            lines.append(f"- {len(relevant)} event(s) directly affect {sym} — include avoid_before times in news_context")
        lines.append("")
        lines.append("You MUST populate the news_context field in your response with:")
        lines.append("- has_high_impact: true if any event affects this pair")
        lines.append("- events: list of events with time, name, currency, forecast")
        lines.append("- avoid_before: REQUIRED list of 'HH:MM' UTC cutoffs. Include (a) 30-min pre-release blackouts for each high-impact event affecting this pair, AND (b) any explicit forced-exit instruction in the calendar (e.g. 'exit by 12:15 UTC', 'close before 14:00', 'out by 13:30 UTC' → emit '12:15', '14:00', '13:30'). Never leave empty when such an instruction exists.")
        lines.append("- most_affected_pairs: which pairs are most affected by today's calendar")
        lines.append("- note: one-sentence summary of calendar impact on this pair")
        lines.append("\n")

        return "\n".join(lines)
    except Exception as exc:
        logger.debug(f"[morning_briefing] calendar section build error: {exc}")
        return ""


_AVOID_BEFORE_PATTERNS = [
    re.compile(
        r'\b(?:exit|close|out|flat(?:ten)?|stop\s+trading|no\s+trades?|avoid)\b'
        r'[^.\n]{0,40}?'
        r'\b(?:by|before|prior\s+to|ahead\s+of|until)\b'
        r'\s*(\d{1,2}):(\d{2})\s*(?:UTC|GMT|BST)?',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:by|before|prior\s+to|ahead\s+of)\b'
        r'\s*(\d{1,2}):(\d{2})\s*(?:UTC|GMT|BST)?'
        r'[^.\n]{0,40}?'
        r'\b(?:exit|close|flat|out|no\s+trades?)\b',
        re.IGNORECASE,
    ),
]


def _scan_avoid_before_times(text: str) -> List[str]:
    """Extract HH:MM cutoffs from free-text exit/close/out instructions."""
    if not text:
        return []
    found: List[str] = []
    for pat in _AVOID_BEFORE_PATTERNS:
        for m in pat.finditer(text):
            try:
                groups = m.groups()
                hh = int(groups[-2]); mm = int(groups[-1])
            except (TypeError, ValueError, IndexError):
                continue
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                found.append(f"{hh:02d}:{mm:02d}")
    return found


def _signal_filter_notes(
    allow_buys: bool,
    allow_sells: bool,
    d1_detail: Optional[Dict[str, Any]] = None,
    session_bias: Optional[str] = None,
) -> str:
    """Render the deterministic signal_filter.notes line.

    Bug 3 of docs/briefing_producer_audit_2026-05-11.md: the old code left
    `notes` LLM-authored while overwriting the booleans twice, so the
    label and the text could disagree. This template binds the text to
    the same source of truth as the booleans (d1_direction_detail from
    Bug 1) so they cannot diverge.

    Bug 1 completion: when LLM session_bias disagrees with the
    authoritative deterministic daily_bias, surface that in the note so
    operators can see why the filter overrode the narrative bias.
    """
    score = (d1_detail or {}).get("score")
    confidence = (d1_detail or {}).get("confidence")
    reason = (d1_detail or {}).get("reason") or ""
    direction = (d1_detail or {}).get("direction") or "NEUTRAL"
    sb = (session_bias or "").upper()

    has_score = isinstance(score, int) and confidence in ("strong", "moderate", "neutral")

    def _override_clause() -> str:
        if direction == "BULL" and sb == "BEARISH":
            return f" LLM session_bias was {sb} but daily structure is authoritative."
        if direction == "BEAR" and sb == "BULLISH":
            return f" LLM session_bias was {sb} but daily structure is authoritative."
        return ""

    if allow_buys and allow_sells:
        if reason in ("insufficient_d1_history", "stale_d1_cache",
                      "cache_missing", "cache_read_error"):
            return (
                f"Both directions allowed. D1 direction unavailable "
                f"({reason}); no directional veto applied."
            )
        if has_score and direction == "NEUTRAL":
            return (
                f"Both directions allowed. D1 trend is NEUTRAL "
                f"(score {score:+d}/9); no directional veto applied."
            )
        return "Both directions allowed. D1 trend is NEUTRAL or no veto applied."

    if allow_buys and not allow_sells:
        if has_score and direction in ("BULL", "BEAR"):
            return (
                f"Buys only. D1 direction is {direction} ({confidence} confidence, "
                f"score {score:+d}/9).{_override_clause()}"
            ).strip()
        return "Buys only."

    if allow_sells and not allow_buys:
        if has_score and direction in ("BULL", "BEAR"):
            return (
                f"Sells only. D1 direction is {direction} ({confidence} confidence, "
                f"score {score:+d}/9).{_override_clause()}"
            ).strip()
        return "Sells only."

    return "No directional trades allowed. D1 direction insufficient or filter manually disabled."


def _apply_avoid_before_fallback(briefing: Dict[str, Any]) -> None:
    """Populate news_context.avoid_before from free-text when the model omitted it.

    Scans news_context.note, news_context.events[].name/forecast, and news_events
    free text for patterns like 'exit by 12:15', 'close before 14:00 UTC'. Mutates
    the briefing dict in place. No-op when avoid_before already has entries.
    """
    if not isinstance(briefing, dict):
        return
    nc = briefing.get("news_context")
    if not isinstance(nc, dict):
        nc = {}
        briefing["news_context"] = nc

    existing = nc.get("avoid_before") or []
    if existing:
        return

    chunks: List[str] = []
    for key in ("note", "summary", "commentary"):
        v = nc.get(key)
        if isinstance(v, str):
            chunks.append(v)
    for ev in (nc.get("events") or []):
        if isinstance(ev, dict):
            for k in ("name", "forecast", "note", "instruction"):
                v = ev.get(k)
                if isinstance(v, str):
                    chunks.append(v)
        elif isinstance(ev, str):
            chunks.append(ev)
    ne = briefing.get("news_events")
    if isinstance(ne, list):
        for ev in ne:
            if isinstance(ev, dict):
                for v in ev.values():
                    if isinstance(v, str):
                        chunks.append(v)
            elif isinstance(ev, str):
                chunks.append(ev)
    elif isinstance(ne, str):
        chunks.append(ne)

    times: List[str] = []
    seen = set()
    for txt in chunks:
        for t in _scan_avoid_before_times(txt):
            if t not in seen:
                seen.add(t)
                times.append(t)

    if times:
        nc["avoid_before"] = times
        try:
            logger.info(
                "[morning_briefing] avoid_before fallback populated %s from free text",
                times,
            )
        except Exception:
            pass


def _get_recent_prediction_accuracy(
    symbol: str, lookback_days: int = 14
) -> Optional[Dict[str, Any]]:
    """Read briefing_outcomes.jsonl and return per-pair accuracy stats for the
    last N days. Returns None if fewer than 5 records exist for the symbol.

    Returns dict with: total, with_call, correct, accuracy_pct,
    by_session (dict of session -> {n, correct, win_pct}),
    avg_conf_correct, avg_conf_wrong.
    """
    path = Path("/opt/tradingbot/data/briefing_outcomes.jsonl")
    if not path.exists():
        return None

    sym = str(symbol).upper()
    cutoff = (datetime.now(timezone.utc).date()
              - pd.Timedelta(days=lookback_days)).isoformat()

    records: List[Dict[str, Any]] = []
    try:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if str(rec.get("symbol", "")).upper() != sym:
                    continue
                if str(rec.get("date", "")) < cutoff:
                    continue
                records.append(rec)
    except Exception:
        return None

    if len(records) < 5:
        return None

    directional = [r for r in records
                   if str(r.get("session_bias", "")).upper() in ("BULLISH", "BEARISH")
                   and r.get("bias_correct") is not None]

    correct_recs = [r for r in directional if r.get("bias_correct") is True]
    wrong_recs   = [r for r in directional if r.get("bias_correct") is False]

    by_session: Dict[str, Dict[str, Any]] = {}
    for r in directional:
        s = str(r.get("session", "?"))
        bs = by_session.setdefault(s, {"n": 0, "correct": 0})
        bs["n"] += 1
        if r.get("bias_correct"):
            bs["correct"] += 1
    for s in by_session:
        n = by_session[s]["n"]
        by_session[s]["win_pct"] = round(by_session[s]["correct"] / n * 100, 1) if n else None

    def _avg_conf(recs: List[Dict[str, Any]]) -> Optional[float]:
        vals = [float(r["bias_confidence"]) for r in recs
                if isinstance(r.get("bias_confidence"), (int, float))]
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "total": len(records),
        "with_call": len(directional),
        "correct": len(correct_recs),
        "accuracy_pct": (round(len(correct_recs) / len(directional) * 100, 1)
                         if directional else None),
        "by_session": by_session,
        "avg_conf_correct": _avg_conf(correct_recs),
        "avg_conf_wrong":   _avg_conf(wrong_recs),
    }


def _format_recent_accuracy_block(symbol: str, stats: Dict[str, Any]) -> str:
    sessions_str = ", ".join(
        f"{s} {d['correct']}/{d['n']} ({d['win_pct']}%)"
        for s, d in sorted(stats["by_session"].items())
    ) or "—"

    parts = [
        f"\n=== RECENT PREDICTION ACCURACY ({symbol}, last 14 days) ===",
        f"Total briefings: {stats['total']}",
        f"Non-NEUTRAL calls: {stats['with_call']} "
        f"({round(stats['with_call']/stats['total']*100, 1)}%)",
    ]
    if stats["accuracy_pct"] is not None:
        parts.append(
            f"Directional accuracy on non-NEUTRAL: "
            f"{stats['correct']}/{stats['with_call']} = {stats['accuracy_pct']}%"
        )
    if stats["avg_conf_correct"] is not None:
        parts.append(f"Avg confidence on correct: {stats['avg_conf_correct']}")
    if stats["avg_conf_wrong"] is not None:
        parts.append(f"Avg confidence on wrong: {stats['avg_conf_wrong']}")
    parts.append(f"By session: {sessions_str}")

    if (stats["avg_conf_correct"] is not None
            and stats["avg_conf_wrong"] is not None
            and stats["avg_conf_wrong"] > stats["avg_conf_correct"]):
        parts.append(
            "NOTE: confidence has been miscalibrated recently — "
            "your wrong calls have carried higher confidence than your "
            "correct ones. When you issue a directional call, ground "
            "bias_confidence in the strength of the underlying evidence "
            "(D1 alignment, USD proxy, structural breaks) rather than "
            "confidence-as-feeling."
        )
    return "\n".join(parts) + "\n\n"


def _build_user_message(
    sym: str,
    session: str,
    pkg: Dict[str, Any],
    validation_feedback: Optional[str] = None,
) -> str:
    # Inject calibration summary so the model can self-correct
    _cal_block = ""
    try:
        _cal = briefing_calibrator.get_calibration_summary(symbol=sym)
        if _cal:
            _cal_block = (
                f"\n=== PAST BRIEFING CALIBRATION ===\n{_cal}\n"
                f"Use this to adjust your confidence levels and bias accuracy.\n\n"
            )
    except Exception:
        pass

    # Inject recent prediction accuracy from briefing_outcomes.jsonl —
    # complements the trade-CSV-based calibration above with the broader
    # prediction-vs-actual record (all briefings, not just traded ones).
    _pred_acc_block = ""
    try:
        _stats = _get_recent_prediction_accuracy(sym, lookback_days=14)
        if _stats is not None:
            _pred_acc_block = _format_recent_accuracy_block(sym, _stats)
    except Exception:
        pass

    _narrative_block = ""
    try:
        from briefing_narrative import get_today_narrative_text
        _nt = get_today_narrative_text(sym)
        if _nt:
            _narrative_block = (
                f"\n=== TODAY'S SESSION HISTORY FOR {sym} ===\n{_nt}\n"
                f"You have context on how today has unfolded. Maintain directional continuity "
                f"unless you see clear structural evidence of a change. If you are flipping from "
                f"the previous session bias, explain specifically what structural level has broken.\n\n"
            )
    except Exception:
        pass

    _feedback_block = ""
    if validation_feedback:
        _feedback_block = (
            f"\n=== VALIDATION RETRY ===\n"
            f"Your previous output failed validation. Please regenerate with these "
            f"specific issues fixed:\n{validation_feedback}\n"
            f"Return the full briefing JSON again with the issues resolved.\n\n"
        )

    # Bug 1 fix — deterministic D1 direction injected as STATED FACT.
    # The LLM cannot author daily_bias; it must mirror this value.
    # Override applied in _refresh_symbol after the LLM returns.
    _d1_dir_block = ""
    _d1_dir = pkg.get("d1_direction_detail") if isinstance(pkg, dict) else None
    if _d1_dir and _d1_dir.get("direction") and _d1_dir.get("reason") != "insufficient_d1_history":
        try:
            _checks_summary = ", ".join(
                f"{name}={info['verdict']}"
                for name, info in (_d1_dir.get("checks") or {}).items()
            )
            _d1_dir_block = (
                "=== D1 DIRECTION (deterministic — STATED FACT) ===\n"
                f"D1 direction is {_d1_dir['direction']} "
                f"({_d1_dir['confidence']} confidence, "
                f"score {_d1_dir['score']:+d}/9).\n"
                f"Check breakdown: {_checks_summary}.\n"
                f"You MUST use this direction in the daily_bias field "
                f"(BULL→BULLISH, BEAR→BEARISH, NEUTRAL→NEUTRAL). "
                f"Your narrative may discuss nuance but cannot contradict it.\n\n"
            )
        except Exception:
            _d1_dir_block = ""

    # Phase 6 — deterministic structural state (news + HTF) computed
    # bot-side and provided as authoritative input. The model uses this
    # rather than re-deriving from raw candles. Falls back gracefully
    # on any error so a structural_state bug never kills the briefing.
    _state_block = ""
    try:
        from structural_state import get_structural_state
        _state = get_structural_state(sym)
        _state_block = (
            "=== STRUCTURAL STATE (computed deterministically — use as factual "
            "input, not commentary) ===\n"
            + json.dumps(_state, indent=2, default=str)
            + "\n\n"
        )
    except Exception as _ss_exc:
        logger.warning(
            "[morning_briefing] %s/%s: structural_state failed (%s) — "
            "briefing continues without state block",
            sym, session, _ss_exc, exc_info=True,
        )

    return (
        _feedback_block
        +
        f"Produce a pre-session briefing for {sym} at the {session} open.\n\n"
        f"Current price: {pkg.get('current_price')}\n"
        f"Today's date: {pkg.get('briefing_date')} UTC\n"
        f"Current UTC time: {pkg.get('briefing_time_utc')}\n\n"
        + _d1_dir_block
        + _state_block +
        f"=== MARKET DATA ===\n"
        f"{json.dumps(pkg, indent=2, default=str)}\n\n"
        f"{_cal_block}"
        f"{_pred_acc_block}"
        f"{_narrative_block}"
        f"=== STRUCTURAL CONTEXT ===\n"
        f"Previous day: high={pkg.get('prev_day_high')} low={pkg.get('prev_day_low')} close={pkg.get('prev_day_close')}\n"
        f"This week: high={pkg.get('week_high')} low={pkg.get('week_low')}\n"
        f"Last week: high={pkg.get('prev_week_high')} low={pkg.get('prev_week_low')}\n"
        f"Price vs H1 EMA200: {pkg.get('price_vs_h1_ema200_pips')} pips | "
        f"vs H1 EMA50: {pkg.get('price_vs_h1_ema50_pips')} pips | "
        f"H1 EMA trend: {pkg.get('h1_ema_trend')}\n"
        f"Volatility: today ATR={pkg.get('atr_today_pips')} pips, "
        f"20-day avg={pkg.get('atr_20day_avg_pips')} pips, regime={pkg.get('volatility_regime')}\n"
        f"Previous session bias: {pkg.get('prev_session_bias', 'N/A')}\n"
        f"Previous session actual: {pkg.get('prev_session_actual_direction', 'N/A')} "
        f"({pkg.get('prev_session_pip_move', 'N/A')} pips)\n\n"
        +
        # USD proxy block — basket-weighted (Bug 2 fix). The pair being
        # briefed is excluded from its own basket. Daily directional bias
        # is owned by compute_d1_direction (Bug 1) and cannot be overridden
        # by this proxy.
        (
            f"=== USD STRENGTH PROXY (basket — {pkg.get('usd_proxy_method')}) ===\n"
            f"Basket: {', '.join(pkg.get('usd_proxy_contributors') or [])}\n"
            f"USD strength: {pkg.get('usd_proxy_pips', 0):+.1f} (normalised pips)"
            f" → {pkg.get('usd_proxy_bias', 'N/A')}\n"
            f"Computation: {pkg.get('usd_proxy_reason', '')}\n"
            f"USD strength is one input among many. Directional bias is determined "
            f"deterministically from D1 structure (see daily_bias field) and "
            f"cannot be overridden by USD proxy alone. Use this signal to flavour "
            f"the narrative (e.g. distinguish a session driven by USD-wide moves "
            f"from one driven by {sym}-specific catalysts) but not to flip bias.\n"
            + (
                f"WARNING: only {len(pkg.get('usd_proxy_contributors') or [])} pair(s) "
                f"available — basket is degraded; weight accordingly.\n"
                if pkg.get("usd_proxy_method") == "degraded_single"
                else ""
            )
            + "\n"
            if pkg.get("usd_proxy_bias") is not None
            else ""
        )
        +
        (
            f"=== RECENT ACCURACY FEEDBACK ===\n"
            f"Your recent accuracy for {sym}: {pkg.get('accuracy_last_5', 'N/A')}% correct out of last 5 assessable sessions.\n"
            f"Recent results: {json.dumps(pkg.get('recent_accuracy', []), default=str)}\n"
            + (
                f"WARNING: Your recent accuracy for {sym} is only {pkg.get('accuracy_last_5')}%. "
                f"You have been systematically wrong. Consider reversing your typical bias "
                f"assessment for this pair. If your instinct says BULLISH, seriously consider "
                f"whether the evidence actually points BEARISH, and vice versa.\n\n"
                if pkg.get("accuracy_last_5") is not None and pkg["accuracy_last_5"] < 60
                else f"Review where you went wrong and adjust your bias assessment accordingly.\n\n"
            )
            if pkg.get("recent_accuracy")
            else ""
        )
        +
        _build_calendar_section(sym, pkg)
        +
        f"=== ANALYSIS INSTRUCTIONS ===\n"
        f"0. STRUCTURAL STATE: The STRUCTURAL STATE block above is computed and "
        f"authoritative. It tells you the day's news context (today / yesterday / "
        f"tomorrow + classification), D1 trend, position, ATR state, H4 trend, and "
        f"weekly position. Treat these as facts about today — do not re-derive them "
        f"from raw candles or argue with them. Use them as inputs to your reasoning "
        f"about plans, bias, and probabilities.\n\n"
        f"1. DAILY STRUCTURE: D1 trend / position / ATR state come from the state "
        f"block. Beyond that, identify the specific swing highs/lows that frame "
        f"today and which structural levels (prev_day, week, prev_week) are most "
        f"relevant given the state.\n\n"
        f"2. H4 CONTEXT: H4 trend comes from the state block. Identify the H4 "
        f"liquidity pools (equal highs/lows, swing points where stops cluster) and "
        f"any compression / expansion patterns the state classification doesn't "
        f"capture.\n\n"
        f"3. H1 STRUCTURE: The most recent 6 H1 candles refine timing within the "
        f"trend established by the state block. Look at consecutive higher/lower "
        f"closes, total pip movement, EMA alignment. See h1_momentum_summary and "
        f"ema_alignment in the data.\n\n"
        f"4. SESSION BIAS: Form your own session_bias informed by the structural "
        f"state above (D1 trend, weekly position, news classification) AND the "
        f"intraday data below (H1 momentum, USD proxy, previous session result). "
        f"Return NEUTRAL when the inputs conflict or you lack conviction — do not "
        f"force a direction.\n"
        f"BIAS STABILITY: If the previous session bias was directional and price "
        f"has not broken a major structural level, maintain the same bias rather "
        f"than flipping. Only reverse on a clear structural break.\n"
        f"CONFIDENCE CALIBRATION:\n"
        f"  0.75+ = high conviction, structural state + intraday agree, strong setup\n"
        f"  0.65-0.75 = moderate conviction, some conflicting signals\n"
        f"  0.55-0.65 = low conviction, mixed conditions — consider NEUTRAL instead\n"
        f"  below 0.55 = return NEUTRAL with confidence 0.50\n\n"
        f"5. REGIME CLASSIFICATION: Classify the current market regime as one of:\n"
        f"   NEWS — if any HIGH impact news event is scheduled within 4 hours of this session\n"
        f"   TREND — if EMAs are fanned out (8 > 13 > 21 or 8 < 13 < 21) AND MACD is expanding "
        f"directionally AND session_expectation is TREND\n"
        f"   SWEEP — all other conditions (NEUTRAL, LIQUIDITY_HUNT, RANGE, mixed signals)\n"
        f"   Set regime_confidence (0.0-1.0) and regime_reasoning (one sentence).\n\n"
        f"6. SESSION EXPECTATION: Given the session opening ({session}), what typically happens? "
        f"Asian: accumulation/range. London: breakout or liquidity hunt then reversal. "
        f"NY: continuation or reversal of London move. "
        f"Which is most likely today given the structure?\n\n"
        f"7. RANKED LEVELS (`levels` array — primary output):\n"
        f"List ONLY the 4-6 most significant price levels for today, ranked by importance. "
        f"Do not list secondary or noise levels. Each level must have real confluence and a "
        f"specific justification. Adjacent ranks must be at least 15 pips apart in price — if "
        f"two candidate levels are closer than 15p, pick the more significant one and drop the "
        f"other. Each entry must have:\n"
        f"  - rank:           int 1..6, unique and contiguous (1, 2, 3, ... no gaps). rank 1 is "
        f"the single most significant level for today.\n"
        f"  - price:          exact level price (float).\n"
        f"  - type:           RESISTANCE (above price), SUPPORT (below price), or PIVOT "
        f"(price is currently at/around the level).\n"
        f"  - role:           primary (a level you expect price to interact with today), "
        f"secondary (matters if primary breaks), extension (longer-term target / overshoot zone).\n"
        f"  - confluence:     non-empty list of tags from this vocabulary: "
        f"PREV_DAY_HIGH, PREV_DAY_LOW, PREV_DAY_CLOSE, WEEK_HIGH, WEEK_LOW, "
        f"PREV_WEEK_HIGH, PREV_WEEK_LOW, ASIAN_HIGH, ASIAN_LOW, SWING_HIGH, SWING_LOW, "
        f"BB_UPPER, BB_LOWER, EMA_50, EMA_200, ROUND_NUMBER, DAILY_PIVOT, VWAP. "
        f"At least one tag; prefer multiple when truly present.\n"
        f"  - justification:  ≤30 words explaining concretely why this level matters today "
        f"(e.g. \"Prev day high + weekly pivot + 1.27 round number, untested since Tuesday\"). "
        f"Do NOT use generic phrases like \"key resistance\" or \"important level\".\n"
        f"  - intent:         BOUNCE (expect reaction/reversal off it), FADE (expect rejection "
        f"on a retest — often a sweep), BREAK (expect price to break through it as a trigger).\n"
        f"  - trade_direction: BUY, SELL, or NONE. Must match session_bias and signal_filter.\n"
        f"  - strength:       HIGH (multiple strong confluences + major structural level), "
        f"MEDIUM (one strong confluence), LOW (minor confluence).\n"
        f"BB_LOWER entries always have trade_direction=BUY and intent=BOUNCE; BB_UPPER entries "
        f"always have trade_direction=SELL and intent=FADE. These are non-negotiable.\n"
        f"Ranking guidance: rank 1 is the level most likely to drive today's price action, "
        f"based on D1/H4 structure, untested liquidity pools, and session-specific dynamics. "
        f"Sort the array by rank ascending.\n\n"
        f"7b. MAJOR LEVELS (legacy fields — kept for backwards compatibility):\n"
        f"Copy bb_upper and bb_lower from the data package into the top-level bb_upper / "
        f"bb_lower fields exactly as provided. The legacy key_levels / major_levels / "
        f"liquidity_pools fields will be derived automatically from your ranked `levels` "
        f"array — you do NOT need to populate them yourself, but you MAY include short "
        f"resistance/support arrays in key_levels and major_levels if you wish; they will be "
        f"overwritten by the derivation step if so. The ranked `levels` array is the source "
        f"of truth.\n\n"
        f"7c. SESSION HIGH/LOW ESTIMATES: Based on current structure, volatility, and session type, "
        f"provide your best estimate of where the session high and session low will print. "
        f"These should be specific price levels, not ranges.\n\n"
        f"8. NO-TRADE ZONES: Identify price ranges where the risk/reward is poor — "
        f"mid-range locations, areas of chop, between major levels with no clear edge. "
        f"Format as `[[low, high], ...]`.\n\n"
        f"9. LIQUIDITY POOLS: Identify where buy-side and sell-side liquidity is resting — "
        f"above equal highs, below equal lows, above/below obvious swing points. "
        f"Be specific about price levels.\n\n"
        f"10. SCENARIOS: Produce 2-3 specific scenarios with realistic probabilities. "
        f"Each scenario needs a specific trigger (not vague), a target level, and a clear invalidation.\n\n"
        f"11. NEWS RISK & CONTEXT: news_context.classification, today's events list, "
        f"and the affects_pair flag are in the structural state block — use those as the "
        f"factual record. Set news_risk (HIGH/MEDIUM/LOW/NONE) and populate the "
        f"news_context output, including avoid_before times (30 min before each "
        f"high-impact release affecting {sym}), most_affected_pairs, and a note. "
        f"If any news instruction requires exiting positions before a specific time "
        f"(e.g. 'exit by 12:15 UTC', 'close before 14:00 UTC'), you MUST output that "
        f"time in news_context.avoid_before as 'HH:MM' (UTC). avoid_before is the "
        f"structured field the bot's news gate reads — never leave it empty when a "
        f"forced-exit time exists.\n\n"
        f"12. SIGNAL FILTER: Based on your analysis, should the bot be buying, selling, or both today?\n\n"
        f"13. TRADING PLANS — TWO SESSIONS: Produce 2-3 LONDON plans and 2-3 NY plans. "
        f"Plans must be ranked within their own session (rank 1 = highest probability for "
        f"that session). Total plans 4-6. Probabilities are independent scenarios and do not "
        f"need to sum to 100%.\n\n"
        f"PROBABILITY FIELDS (Phase 3 — bot applies a bias adjustment):\n"
        f"- raw_probability: your judgement of the setup's GEOMETRIC merit alone — how good is "
        f"this trade plan in isolation, ignoring directional bias. Range 0.0-1.0.\n"
        f"- probability: set to the same value as raw_probability initially. The bot will "
        f"overwrite it with raw_probability × bias_multiplier(direction, session_bias, "
        f"bias_confidence) at briefing-receipt time.\n\n"
        f"Each plan must have:\n"
        f"- session: \"London\" or \"NY\"\n"
        f"- A specific entry trigger (not vague — e.g. '5M close above 13380 with RSI > 60')\n"
        f"- A specific entry zone (price range to enter)\n"
        f"- A hard stop loss level\n"
        f"- Two targets (T1 partial, T2 runner)\n"
        f"- Risk/reward ratio\n"
        f"- A clear invalidation condition\n"
        f"- Confidence level: HIGH (raw_probability > 0.65), MEDIUM (0.45-0.65), LOW (< 0.45). "
        f"Use raw_probability for the boundary, not the post-adjustment probability.\n"
        f"- expires_at: '12:30Z' (London plans), 'end_of_day' (NY/HTF plans), or an explicit "
        f"ISO 8601 UTC timestamp.\n\n"
        f"LONDON plans (active 06:45-12:30 UTC):\n"
        f"- session: \"London\"\n"
        f"- london_condition: null  (no gate — fire when entry trigger hits)\n\n"
        f"NY plans (active 12:30-21:00 UTC, ONLY if their london_condition is satisfied by "
        f"what London actually did):\n"
        f"- session: \"NY\"\n"
        f"- london_condition: {{type, level, [tolerance_pips], description}}\n\n"
        f"  Condition types:\n"
        f"  - close_above: NY plan arms only if London 5m close at 12:30 UTC > level. "
        f"Example: {{\"type\": \"close_above\", \"level\": 13530, "
        f"\"description\": \"London closes above yesterday's high\"}}\n"
        f"  - close_below: NY plan arms only if London 5m close at 12:30 UTC < level. "
        f"Example: {{\"type\": \"close_below\", \"level\": 13450, "
        f"\"description\": \"London closes below the Asian low\"}}\n"
        f"  - ranged: NY plan arms only if London high AND low both within tolerance_pips of "
        f"level. Example: {{\"type\": \"ranged\", \"level\": 13490, \"tolerance_pips\": 20, "
        f"\"description\": \"London ranges within 20p of the daily pivot\"}}\n"
        f"  - swept_then_reversed: NY plan arms only if London ran past level by ≥2p then "
        f"closed back through it. Example: {{\"type\": \"swept_then_reversed\", "
        f"\"level\": 13530, \"description\": \"London sweeps yesterday's high then closes "
        f"back below\"}}\n"
        f"  - held_at: NY plan arms only if London tested level (within tolerance_pips) ≥2 "
        f"times without closing through. Example: {{\"type\": \"held_at\", \"level\": 13500, "
        f"\"tolerance_pips\": 8, \"description\": \"London tests 13500 multiple times without "
        f"breaking\"}}\n\n"
        f"  Required fields per type:\n"
        f"    close_above / close_below: level (tolerance_pips not used)\n"
        f"    ranged / held_at:           level + tolerance_pips\n"
        f"    swept_then_reversed:        level (tolerance defaults to 2 pips)\n"
        f"  description ≤ 25 words, always required.\n\n"
        f"NY plan set design: choose conditions that cover the realistic range of London "
        f"outcomes. If London's three most likely outcomes are 'breaks above 13530', 'fades "
        f"back to 13480', or 'ranges around 13510', your three NY plans should target those "
        f"three scenarios. Don't invent NY plans for unlikely scenarios just to fill 3 slots "
        f"— 2 NY plans is fine if only 2 outcomes are plausible.\n\n"
        f"Include a one-sentence plan_summary of your single best trade idea.\n\n"
        f"14. SESSION STRUCTURE FIELDS (Phase 2 — machine-consumed):\n"
        f"   - sweep_direction: BUY, SELL, or NONE. Which side's liquidity is more likely "
        f"to be hunted this session? BUY = buy-side liquidity above (expect a SELL sweep "
        f"that spikes highs then reverses down). SELL = sell-side liquidity below (expect a "
        f"BUY sweep that spikes lows then reverses up). NONE only when no clear sweep setup.\n"
        f"   - fade_after_sweep: true when the primary trade is to fade the sweep after it "
        f"exhausts (mean-reversion play). false when the primary trade is trend continuation "
        f"in the session_bias direction without waiting for a sweep.\n"
        f"   - pre_event_blackout: derive from news_events[]. If ANY HIGH impact event is "
        f"scheduled today for a currency in this pair, set start_utc to 15 minutes BEFORE "
        f"the release time and end_utc to 5 minutes AFTER. Format: 'HH:MM' (UTC). If "
        f"multiple HIGH impact events, cover the nearest one; if none, return "
        f"{{'start_utc': null, 'end_utc': null}}.\n"
        f"   - session_stage_intent: based on D1/H4 structure and your session_expectation, "
        f"classify what EACH session is expected to do today:\n"
        f"       london: SWEEP (hunt liquidity then reverse), TREND (directional move in "
        f"session_bias direction), RANGE (chop between known levels), UNKNOWN.\n"
        f"       ny: SWEEP, TREND, RANGE, CONTINUATION (extend London move), "
        f"REVERSAL (reverse London move), UNKNOWN.\n"
        f"   These fields are NOT yet wired into entry logic — populate them accurately so "
        f"the bot can start using them in the next phase.\n\n"
        f"=== REQUIRED JSON RESPONSE ===\n"
        f"{json.dumps(RESPONSE_SCHEMA, indent=2)}\n\n"
        f"Rules:\n"
        f"- daily_bias must be BULLISH, BEARISH, or NEUTRAL (multi-day trend)\n"
        f"- session_bias MUST be included in your response (required field)\n"
        f"- session_bias should be BULLISH, BEARISH, or NEUTRAL — return NEUTRAL when D1 and H1 conflict or no clear edge\n"
        f"- session_bias can differ from daily_bias — but D1 structure is the dominant signal\n"
        f"- bias_confidence: 0.75+ high conviction, 0.65-0.75 moderate, 0.55-0.65 low, below 0.55 return NEUTRAL\n"
        f"- bias_reasoning MUST reference specific data: USDJPY direction, EMA alignment, prev session result, ATR regime\n"
        f"- signal_filter.allow_buys must be false when session_bias is BEARISH\n"
        f"- signal_filter.allow_sells must be false when session_bias is BULLISH\n"
        f"- signal_filter.allow_buys and allow_sells must both be true when session_bias is NEUTRAL\n"
        f"- briefing_time must be the current UTC time in ISO8601 format\n"
        f"- bias_reasoning and expectation_reasoning must be specific — reference actual price levels\n"
        f"- If you are changing direction from the previous session's bias (prev_session_bias in the data), "
        f"set bias_change=true and explain why in bias_reasoning. "
        f"Be conservative about changing direction mid-session — require strong evidence "
        f"such as a significant structural break or news catalyst\n"
        f"- If volatility_regime is HIGH, consider wider targets and note increased risk in plan notes\n"
        f"- regime must be SWEEP, TREND, or NEWS\n"
        f"- regime_confidence must be between 0.0 and 1.0\n"
        f"- structure describes how the market is currently moving, independent of direction:\n"
        f"    TRENDING: sustained directional movement with clear momentum "
        f"(the direction itself is carried by bias, not here)\n"
        f"    RANGE: oscillation between defined levels with no clear directional conviction\n"
        f"    NEUTRAL: structure is unclear or in transition between regimes\n"
        f"  structure is separate from bias (directional lean) and from regime "
        f"(session character SWEEP/TREND/NEWS). A session can legitimately be "
        f"bias=BULLISH, structure=RANGE, regime=SWEEP — meaning 'we lean long, "
        f"the market is ranging, the session is liquidity-sweep-driven'.\n"
        f"- structure must be TRENDING, RANGE, or NEUTRAL\n"
        f"- structure_confidence must be between 0.0 and 1.0\n"
        f"- levels: 4 to 6 entries. Ranks must be unique and contiguous starting at 1. "
        f"Adjacent ranks must differ by ≥15 pips in price. Each entry must have a non-empty "
        f"confluence list and a justification ≤30 words. Sort by rank ascending.\n"
        f"- trading_plans: 2-3 London plans + 2-3 NY plans, total 4-6.\n"
        f"- Each plan has session ∈ {{\"London\", \"NY\"}}. Within each session ranks must be "
        f"unique starting at 1.\n"
        f"- Each plan MUST include raw_probability ∈ [0.0, 1.0] (geometric merit only, "
        f"ignoring bias). probability is a placeholder of the same value; the bot overwrites "
        f"probability with raw_probability × bias_multiplier.\n"
        f"- London plans: london_condition MUST be null.\n"
        f"- NY plans: london_condition MUST be a non-null object with valid type, level, "
        f"description (≤25 words), and tolerance_pips when type ∈ {{ranged, held_at}}.\n"
        f"- trading_plans[].expires_at is REQUIRED on every plan. Use '12:30Z' for "
        f"London-session-only plans, 'end_of_day' for plans valid until 21:00 UTC, or an "
        f"explicit ISO 8601 UTC timestamp.\n"
        f"- entry_trigger must be specific and actionable\n"
        f"- entry_trigger_v2: list of condition objects. ALL conditions must be\n"
        f"  satisfied for the executor to enter. Choose the conditions that match\n"
        f"  the plan's thesis — minimum 1, maximum 5.\n"
        f"\n"
        f"  Supported condition types:\n"
        f"\n"
        f"  {{\"type\": \"release_event\",\n"
        f"   \"event_name\": str,          // substring match against economic calendar\n"
        f"   \"currency\": \"GBP\"|\"USD\"|\"EUR\"|\"JPY\"|\"CAD\",\n"
        f"   \"window_minutes_before\": int,   // 0 = no pre-release entry\n"
        f"   \"window_minutes_after\": int,    // minutes after release the window is open\n"
        f"   \"impact\": \"HIGH\"|\"MEDIUM\"}}\n"
        f"\n"
        f"  {{\"type\": \"sweep\",\n"
        f"   \"level\": float,\n"
        f"   \"side\": \"above\"|\"below\",\n"
        f"   \"tolerance_pips\": float}}    // price must trade through level by this amount\n"
        f"\n"
        f"  {{\"type\": \"candle_close\",\n"
        f"   \"timeframe\": \"5m\"|\"15m\"|\"1h\",\n"
        f"   \"direction\": \"above\"|\"below\",\n"
        f"   \"level\": float}}             // most recent CLOSED candle on timeframe\n"
        f"\n"
        f"  {{\"type\": \"rsi\",\n"
        f"   \"timeframe\": \"5m\"|\"15m\"|\"1h\",\n"
        f"   \"operator\": \"<\"|\">\"|\"crosses_up\"|\"crosses_down\",\n"
        f"   \"value\": float}}\n"
        f"\n"
        f"  {{\"type\": \"consecutive_closes\",\n"
        f"   \"timeframe\": \"5m\",\n"
        f"   \"direction\": \"above\"|\"below\",\n"
        f"   \"level\": float,\n"
        f"   \"count\": int}}               // N consecutive closed candles\n"
        f"- best_trade: structured pointer that translates your plan_summary "
        f"prose into a machine-readable selection over your trading_plans output.\n"
        f"  • Default to CONDITIONAL when your trading_plans cover mutually-exclusive "
        f"scenarios that cannot all play out today. Use UNCONDITIONAL only when one "
        f"plan is clearly dominant and the others are unlikely fallbacks (e.g. a "
        f"strong-conviction continuation day with no impending news, no major level "
        f"untested, no session-split thesis).\n"
        f"  • A day is multi-scenario when ANY of these hold: price can sweep one "
        f"key level OR test another (not both); London is expected to behave one way "
        f"and NY differently; a scheduled news release will resolve direction one of "
        f"two ways; pre-event drift and post-event continuation are both plausible. "
        f"In any of those cases, your plan_summary SHOULD be written as if/else prose "
        f"and best_trade.mode SHOULD be CONDITIONAL with one branch per scenario.\n"
        f"  • Concrete examples of CONDITIONAL-worthy plan_summary phrasings:\n"
        f"      'Either price sweeps Asian low 13580 and bounces back (LONG branch) "
        f"or it tests equal highs 13630 and fades (SHORT branch).'\n"
        f"      'London is expected to range; NY breaks out post-CPI in the "
        f"data-driven direction — bullish above 13610 or bearish below 13570.'\n"
        f"      'Pre-CPI drift to sell-side liquidity 13580 then either bounces to "
        f"13610 (LONG) or breaks down to 13544 (SHORT) depending on data outcome.'\n"
        f"  • Counter-trend intraday plans WITHIN a strong daily_bias are legitimate "
        f"and your plan_summary should reflect them. A BULL daily that expects a "
        f"morning sweep below support before resuming higher is a CONDITIONAL day, "
        f"not a UNCONDITIONAL LONG day — author a SHORT branch for the sweep and a "
        f"LONG branch for the resumption. Do not collapse the day to a single-thesis "
        f"summary just because daily_bias is directional; the LLM gate on direction "
        f"happens downstream, not in best_trade.\n"
        f"  • Soft heuristic: if you have authored 4+ trading_plans across multiple "
        f"sessions OR across multiple directions, the day is almost certainly "
        f"multi-scenario — default to CONDITIONAL unless one plan's raw_probability "
        f"exceeds every other plan by at least 0.20 (clear dominance).\n"
        f"  • If plan_summary commits to ONE trade with no if/else logic (e.g. "
        f"'Primary setup: sell on break below 13455 targeting 13420'): emit "
        f"best_trade with mode=UNCONDITIONAL, plan_rank and plan_session pointing "
        f"to the matching trading_plans entry, conditional_branches=null.\n"
        f"  • If plan_summary has if/else logic: emit best_trade with mode=CONDITIONAL, "
        f"plan_rank and plan_session both null, conditional_branches as a list of "
        f"{{condition_text, plan_rank, plan_session}} objects each pointing to one "
        f"trading_plans entry. condition_text is natural language (e.g. 'London "
        f"sweeps below 13580 by 5+ pips then reclaims', 'CPI prints above 3.7% YoY'). "
        f"conditional_branches typically has 2-3 entries; more than 4 is unusual.\n"
        f"  • Each plan_rank+plan_session pair MUST exactly match a trading_plans "
        f"entry that you emitted. plan_rank alone is not unique (rank=1 exists for "
        f"both London and NY).\n"
        f"  • reasoning: ONE sentence explaining why this structured pointer is the "
        f"right one. This is NOT a copy of plan_summary — plan_summary is the prose "
        f"summary for human readers, best_trade.reasoning justifies the structured "
        f"selection (e.g. 'rank-1 London plan has the strongest pre-event conviction "
        f"and clear invalidation', or 'BoE outcome bifurcates the day cleanly into "
        f"two pre-defined plans').\n"
        f"  • If plan_summary is genuinely ambiguous, describes a wait-and-see "
        f"posture, or doesn't map to any trading_plans entry: set best_trade=null "
        f"and OPTIONALLY set best_trade_omission_reason to a single sentence "
        f"explaining why (e.g. 'plan_summary describes wait-and-see posture before "
        f"BoE'). Better null than a mistranslation.\n"
        f"- Return valid JSON only — no prose, no markdown fences"
    )


def _populate_legacy_levels(briefing: Dict[str, Any], levels: list) -> None:
    """Derive the legacy key_levels / major_levels / liquidity_pools / no_trade_zones
    fields from the new ranked levels[] array. Phase 1 backwards compatibility:
    consumers (BB_REVERSAL TP placement, NEWS_TICK proximity matching) keep
    reading the legacy shape unchanged.

    Mutates *briefing* in place. bb_upper / bb_lower top-level fields are left
    untouched — they're computed Python-side and the model copies them through.
    """
    if not levels:
        # Don't clobber whatever the model returned (or what was already there)
        # if the new array is empty for some reason.
        return

    bb_upper = briefing.get("bb_upper")
    bb_lower = briefing.get("bb_lower")

    res = sorted(
        (lv for lv in levels if lv["type"] == "RESISTANCE"),
        key=lambda lv: lv["rank"],
    )
    sup = sorted(
        (lv for lv in levels if lv["type"] == "SUPPORT"),
        key=lambda lv: lv["rank"],
    )

    res_prices = [lv["price"] for lv in res]
    sup_prices = [lv["price"] for lv in sup]

    # key_levels: every resistance/support price, ordered by rank (best first).
    briefing["key_levels"] = {
        "resistance": list(res_prices),
        "support":    list(sup_prices),
    }

    # major_levels: top 3 of each side, with bb_upper/bb_lower prepended when
    # available (matches the historical ordering rule).
    major_res = list(res_prices[:3])
    major_sup = list(sup_prices[:3])
    if isinstance(bb_upper, (int, float)) and bb_upper not in major_res:
        major_res.insert(0, float(bb_upper))
    if isinstance(bb_lower, (int, float)) and bb_lower not in major_sup:
        major_sup.insert(0, float(bb_lower))
    briefing["major_levels"] = {
        "resistance": major_res,
        "support":    major_sup,
    }

    # liquidity_pools: derived by trade_direction. Buy-side = resistance levels
    # with FADE intent (sweep targets above) ∪ levels priced as resistance.
    # Sell-side = support levels with FADE intent (sweep targets below).
    # Conservative derivation: every resistance is buy-side liquidity, every
    # support is sell-side. Existing consumers treat this as a flat price list.
    briefing["liquidity_pools"] = {
        "buy_side":  list(res_prices),
        "sell_side": list(sup_prices),
    }


_LEVEL_TYPES      = {"RESISTANCE", "SUPPORT", "PIVOT"}
_LEVEL_ROLES      = {"primary", "secondary", "extension"}
_LEVEL_INTENTS    = {"BOUNCE", "FADE", "BREAK"}
_LEVEL_DIRECTIONS = {"BUY", "SELL", "NONE"}
_LEVEL_STRENGTHS  = {"HIGH", "MEDIUM", "LOW"}
_LEVEL_REQUIRED   = ("rank", "price", "type", "role", "confluence",
                     "justification", "intent", "trade_direction", "strength")
_LEVEL_CONFLUENCE_VOCAB = {
    "PREV_DAY_HIGH", "PREV_DAY_LOW", "PREV_DAY_CLOSE",
    "WEEK_HIGH", "WEEK_LOW", "PREV_WEEK_HIGH", "PREV_WEEK_LOW",
    "ASIAN_HIGH", "ASIAN_LOW",
    "SWING_HIGH", "SWING_LOW",
    "BB_UPPER", "BB_LOWER",
    "EMA_50", "EMA_200",
    "ROUND_NUMBER", "DAILY_PIVOT", "VWAP",
}

_LEVELS_MIN_COUNT          = 4
_LEVELS_MAX_COUNT          = 6
_LEVELS_MIN_SEPARATION_PIP = 15.0
_LEVELS_MAX_JUSTIFICATION_WORDS = 30


def _validate_levels(levels: list, symbol: str) -> tuple:
    """Validate the redesigned `levels` array (Phase 1 schema).

    Returns ``(cleaned_list, errors)``. When ``errors`` is non-empty the
    caller should retry the briefing once with explicit feedback. When empty,
    ``cleaned_list`` is ready to ship.

    Constraints enforced:
      - 4 ≤ len ≤ 6
      - rank ∈ {1..N}, unique and contiguous (1..N with no gaps)
      - sorted by rank ascending (output is sorted)
      - adjacent (by rank) ranks ≥ 15 pips apart in price
      - confluence non-empty, all tags from the vocabulary
      - justification present and ≤ 30 words
      - BB_LOWER ⇒ trade_direction=BUY/intent=BOUNCE (force-fixed)
      - BB_UPPER ⇒ trade_direction=SELL/intent=FADE (force-fixed)
    """
    errors: list = []

    if not isinstance(levels, list):
        msg = (f"levels field is {type(levels).__name__}, expected list "
               f"of {_LEVELS_MIN_COUNT}-{_LEVELS_MAX_COUNT} entries")
        logger.warning("[morning_briefing] %s: %s", symbol, msg)
        return [], [msg]

    ppp = _POINTS_PER_PIP.get(str(symbol).upper(), 1.0) or 1.0

    cleaned: list = []
    for idx, entry in enumerate(levels):
        if not isinstance(entry, dict):
            errors.append(f"levels[{idx}] is not an object")
            continue

        missing = [k for k in _LEVEL_REQUIRED if k not in entry]
        if missing:
            errors.append(f"levels[{idx}] missing required fields {missing}")
            continue

        try:
            rank = int(entry["rank"])
        except (TypeError, ValueError):
            errors.append(f"levels[{idx}] rank={entry.get('rank')!r} not an integer")
            continue
        if rank < 1 or rank > _LEVELS_MAX_COUNT:
            errors.append(f"levels[{idx}] rank={rank} out of range 1..{_LEVELS_MAX_COUNT}")
            continue

        try:
            price = float(entry["price"])
        except (TypeError, ValueError):
            errors.append(f"levels[{idx}] price={entry.get('price')!r} not numeric")
            continue

        ltype = str(entry.get("type", "")).upper()
        if ltype not in _LEVEL_TYPES:
            errors.append(f"levels[{idx}] type={entry.get('type')!r} not in {sorted(_LEVEL_TYPES)}")
            continue

        role = str(entry.get("role", "")).lower()
        if role not in _LEVEL_ROLES:
            errors.append(f"levels[{idx}] role={entry.get('role')!r} not in {sorted(_LEVEL_ROLES)}")
            continue

        intent = str(entry.get("intent", "")).upper()
        if intent not in _LEVEL_INTENTS:
            errors.append(f"levels[{idx}] intent={entry.get('intent')!r} not in {sorted(_LEVEL_INTENTS)}")
            continue

        direction = str(entry.get("trade_direction", "")).upper()
        if direction not in _LEVEL_DIRECTIONS:
            errors.append(f"levels[{idx}] trade_direction={entry.get('trade_direction')!r} "
                          f"not in {sorted(_LEVEL_DIRECTIONS)}")
            continue

        strength = str(entry.get("strength", "")).upper()
        if strength not in _LEVEL_STRENGTHS:
            errors.append(f"levels[{idx}] strength={entry.get('strength')!r} "
                          f"not in {sorted(_LEVEL_STRENGTHS)}")
            continue

        confluence = entry.get("confluence")
        if not isinstance(confluence, list) or not confluence:
            errors.append(f"levels[{idx}] confluence must be a non-empty list")
            continue
        confluence = [str(c).upper() for c in confluence if c is not None and str(c).strip()]
        if not confluence:
            errors.append(f"levels[{idx}] confluence has no valid tags")
            continue
        unknown_tags = [t for t in confluence if t not in _LEVEL_CONFLUENCE_VOCAB]
        if unknown_tags:
            errors.append(
                f"levels[{idx}] confluence has tags outside vocabulary: {unknown_tags} "
                f"(allowed: {sorted(_LEVEL_CONFLUENCE_VOCAB)})"
            )
            continue

        justification = str(entry.get("justification", "") or "").strip()
        if not justification:
            errors.append(f"levels[{idx}] justification is required")
            continue
        word_count = len(justification.split())
        if word_count > _LEVELS_MAX_JUSTIFICATION_WORDS:
            errors.append(
                f"levels[{idx}] justification has {word_count} words "
                f"(max {_LEVELS_MAX_JUSTIFICATION_WORDS})"
            )
            continue

        cleaned.append({
            "rank":            rank,
            "price":           price,
            "type":            ltype,
            "role":            role,
            "confluence":      confluence,
            "justification":   justification,
            "intent":          intent,
            "trade_direction": direction,
            "strength":        strength,
        })

    # Force BB_UPPER/BB_LOWER direction/intent before the structural checks
    for lv in cleaned:
        conf = lv.get("confluence") or []
        if "BB_LOWER" in conf:
            if lv.get("trade_direction") != "BUY" or lv.get("intent") != "BOUNCE":
                logger.info(
                    "[BRIEFING-FIX] %s BB_LOWER forced BUY/BOUNCE (was %s/%s)",
                    symbol, lv.get("trade_direction"), lv.get("intent"),
                )
                lv["trade_direction"] = "BUY"
                lv["intent"] = "BOUNCE"
        if "BB_UPPER" in conf:
            if lv.get("trade_direction") != "SELL" or lv.get("intent") != "FADE":
                logger.info(
                    "[BRIEFING-FIX] %s BB_UPPER forced SELL/FADE (was %s/%s)",
                    symbol, lv.get("trade_direction"), lv.get("intent"),
                )
                lv["trade_direction"] = "SELL"
                lv["intent"] = "FADE"

    # Count check (only if individual entries didn't already fail)
    if not (_LEVELS_MIN_COUNT <= len(cleaned) <= _LEVELS_MAX_COUNT):
        errors.append(
            f"levels has {len(cleaned)} valid entries; "
            f"need {_LEVELS_MIN_COUNT}-{_LEVELS_MAX_COUNT}"
        )

    # Sort by rank ascending — checks below assume sorted order
    cleaned.sort(key=lambda lv: lv["rank"])

    if cleaned:
        ranks = [lv["rank"] for lv in cleaned]
        expected = list(range(1, len(cleaned) + 1))
        if ranks != expected:
            errors.append(
                f"ranks must be unique and contiguous 1..{len(cleaned)}; got {ranks}"
            )

        for i in range(len(cleaned) - 1):
            sep = abs(cleaned[i]["price"] - cleaned[i + 1]["price"]) / ppp
            if sep < _LEVELS_MIN_SEPARATION_PIP:
                errors.append(
                    f"rank {cleaned[i]['rank']} ({cleaned[i]['price']:g}) and rank "
                    f"{cleaned[i + 1]['rank']} ({cleaned[i + 1]['price']:g}) are only "
                    f"{sep:.1f} pips apart (min {_LEVELS_MIN_SEPARATION_PIP:g})"
                )

    if errors:
        for err in errors:
            logger.warning("[morning_briefing] %s: levels validation: %s", symbol, err)

    return cleaned, errors


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 briefing fields — validation only, no strategy wiring yet.
# ─────────────────────────────────────────────────────────────────────────────
_PHASE2_SWEEP_DIRECTIONS = {"BUY", "SELL", "NONE"}
_PHASE2_LONDON_STAGES    = {"SWEEP", "TREND", "RANGE", "UNKNOWN"}
_PHASE2_NY_STAGES        = {"SWEEP", "TREND", "RANGE", "CONTINUATION", "REVERSAL", "UNKNOWN"}


def _valid_hhmm(s: Any) -> bool:
    """True iff s is a 'HH:MM' string in 00:00..23:59."""
    if not isinstance(s, str):
        return False
    parts = s.split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


# ─────────────────────────────────────────────────────────────────────────────
# best_trade validation (Phase A — feat/briefing-best-trade)
# ─────────────────────────────────────────────────────────────────────────────

# In-memory dedup for the per-pair-per-day Telegram WARNING. Keys are
# "{symbol}|{YYYY-MM-DD}|best_trade". Reset on process restart so the first
# malformed briefing post-restart re-fires the warning — intentional, gives
# post-restart visibility rather than silent state carryover.
_BEST_TRADE_TELEGRAM_DEDUP: Dict[str, bool] = {}

_BEST_TRADE_FAILURE_DIR = "/opt/tradingbot/cache/briefing_schema_failures"
_VALID_BEST_TRADE_MODES = {"UNCONDITIONAL", "CONDITIONAL"}
_VALID_BEST_TRADE_SESSIONS = {"London", "NY"}


def _send_best_trade_telegram_once_per_day(symbol: str, reason: str) -> None:
    """First occurrence per (pair, UTC date) fires Telegram; subsequent
    occurrences in the same UTC day silent. State is in-memory only —
    process restart resets the dedup."""
    from datetime import datetime as _dt, timezone as _tz
    today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    key = f"{symbol}|{today}|best_trade"
    if _BEST_TRADE_TELEGRAM_DEDUP.get(key):
        return
    _BEST_TRADE_TELEGRAM_DEDUP[key] = True
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(
            f"⚠️ briefing best_trade validation failed pair={symbol} — "
            f"{reason} (deduped, first occurrence today only)"
        )
    except Exception:
        pass


def _persist_best_trade_failure(
    symbol: str, session: str, raw_best_trade: Any, reason: str,
) -> None:
    """Write the malformed best_trade payload to disk for offline review.
    One file per (pair, session, UTC date); overwrite on multiple
    failures."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
        target_dir = os.path.join(_BEST_TRADE_FAILURE_DIR, today)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(
            target_dir, f"{symbol}_{session}_best_trade.json"
        )
        with open(target, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "symbol": symbol,
                    "session": session,
                    "reason": reason,
                    "raw_best_trade": raw_best_trade,
                    "saved_at_utc": _dt.now(_tz.utc).isoformat(),
                },
                f, indent=2, default=str,
            )
    except Exception as exc:
        logger.debug(
            "[morning_briefing] best_trade failure persist skipped: %s", exc,
        )


def _build_plan_index(briefing: Dict[str, Any]) -> set:
    """Return a set of (plan_session, plan_rank) tuples representing the
    valid plan references in this briefing. Used to validate best_trade
    references."""
    out = set()
    for p in (briefing.get("trading_plans") or []):
        if not isinstance(p, dict):
            continue
        sess = p.get("session")
        rk = p.get("rank")
        if isinstance(sess, str) and isinstance(rk, int):
            out.add((sess, rk))
    return out


def _validate_best_trade(briefing: Dict[str, Any], symbol: str, session: str) -> None:
    """Validate best_trade in place. On any structural error: log WARNING,
    persist raw payload, fire Telegram (deduped), set best_trade=None.
    The rest of the briefing is unaffected.

    best_trade=None on entry is valid (no validation, no warning).
    best_trade_omission_reason is independent — checked only for type.
    """
    raw = briefing.get("best_trade")

    # Optional adjacent field — sanity-check shape only.
    omit_reason = briefing.get("best_trade_omission_reason")
    if omit_reason is not None and not isinstance(omit_reason, str):
        logger.warning(
            "[morning_briefing] %s/%s best_trade_omission_reason not a string "
            "(got %s) — clearing",
            symbol, session, type(omit_reason).__name__,
        )
        briefing["best_trade_omission_reason"] = None

    if raw is None:
        # null is a valid emission; nothing to validate.
        return

    def _fail(reason: str) -> None:
        logger.warning(
            "[morning_briefing] %s/%s best_trade malformed: %s — clearing",
            symbol, session, reason,
        )
        _persist_best_trade_failure(symbol, session, raw, reason)
        briefing["best_trade"] = None
        _send_best_trade_telegram_once_per_day(
            symbol, f"{session}: {reason}",
        )

    if not isinstance(raw, dict):
        _fail(f"not an object (got {type(raw).__name__})")
        return

    mode = raw.get("mode")
    if mode not in _VALID_BEST_TRADE_MODES:
        _fail(f"mode={mode!r} not in {sorted(_VALID_BEST_TRADE_MODES)}")
        return

    reasoning = raw.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        _fail("reasoning missing or empty")
        return

    plan_index = _build_plan_index(briefing)

    if mode == "UNCONDITIONAL":
        rk = raw.get("plan_rank")
        sess = raw.get("plan_session")
        if not isinstance(rk, int):
            _fail(f"UNCONDITIONAL plan_rank must be int, got {type(rk).__name__}")
            return
        if sess not in _VALID_BEST_TRADE_SESSIONS:
            _fail(f"UNCONDITIONAL plan_session={sess!r} not in {sorted(_VALID_BEST_TRADE_SESSIONS)}")
            return
        if (sess, rk) not in plan_index:
            _fail(
                f"UNCONDITIONAL points to (session={sess}, rank={rk}) which is "
                f"not in trading_plans (have {sorted(plan_index)})"
            )
            return
        # Branches must be absent / null / empty for UNCONDITIONAL.
        branches = raw.get("conditional_branches")
        if branches not in (None, [], ()):
            _fail("UNCONDITIONAL must not carry conditional_branches")
            return
        return  # valid

    # mode == "CONDITIONAL"
    if raw.get("plan_rank") is not None or raw.get("plan_session") is not None:
        _fail("CONDITIONAL must have plan_rank=null and plan_session=null at top level")
        return
    branches = raw.get("conditional_branches")
    if not isinstance(branches, list) or len(branches) < 2:
        _fail(
            f"CONDITIONAL conditional_branches must be a list of >=2 items "
            f"(got {type(branches).__name__})"
        )
        return
    for i, b in enumerate(branches):
        if not isinstance(b, dict):
            _fail(f"CONDITIONAL branch[{i}] not an object")
            return
        ct = b.get("condition_text")
        if not isinstance(ct, str) or not ct.strip():
            _fail(f"CONDITIONAL branch[{i}] condition_text missing/empty")
            return
        rk = b.get("plan_rank")
        sess = b.get("plan_session")
        if not isinstance(rk, int):
            _fail(f"CONDITIONAL branch[{i}] plan_rank not int")
            return
        if sess not in _VALID_BEST_TRADE_SESSIONS:
            _fail(
                f"CONDITIONAL branch[{i}] plan_session={sess!r} invalid"
            )
            return
        if (sess, rk) not in plan_index:
            _fail(
                f"CONDITIONAL branch[{i}] points to (session={sess}, rank={rk}) "
                f"not in trading_plans (have {sorted(plan_index)})"
            )
            return
    # all branches valid
    return


def _validate_phase2_fields(briefing: Dict[str, Any], symbol: str) -> None:
    """Warn on missing/malformed Phase 2 fields; normalize in place; never raise.

    - sweep_direction: must be BUY/SELL/NONE (case-insensitive) → upper-cased
    - fade_after_sweep: must be bool → coerced from truthy/JSON-ish values
    - pre_event_blackout: must be {'start_utc': 'HH:MM'|null, 'end_utc': 'HH:MM'|null}
    - session_stage_intent: must be {'london': <enum>, 'ny': <enum>}
    """
    # sweep_direction
    sd = briefing.get("sweep_direction")
    if sd is None:
        logger.warning("[morning_briefing] %s: sweep_direction missing", symbol)
    else:
        sd_u = str(sd).upper()
        if sd_u not in _PHASE2_SWEEP_DIRECTIONS:
            logger.warning(
                "[morning_briefing] %s: sweep_direction=%r invalid — expected one of %s; normalizing to NONE",
                symbol, sd, sorted(_PHASE2_SWEEP_DIRECTIONS),
            )
            briefing["sweep_direction"] = "NONE"
        else:
            briefing["sweep_direction"] = sd_u

    # fade_after_sweep — booleans in raw JSON come through as bool; tolerate
    # "true"/"false" strings from sloppy model output.
    fas = briefing.get("fade_after_sweep")
    if fas is None:
        logger.warning("[morning_briefing] %s: fade_after_sweep missing", symbol)
    elif isinstance(fas, bool):
        pass
    elif isinstance(fas, str) and fas.strip().lower() in ("true", "false"):
        briefing["fade_after_sweep"] = fas.strip().lower() == "true"
    else:
        logger.warning(
            "[morning_briefing] %s: fade_after_sweep=%r not a bool — setting to false",
            symbol, fas,
        )
        briefing["fade_after_sweep"] = False

    # pre_event_blackout — dict with start_utc / end_utc (each HH:MM or null)
    peb = briefing.get("pre_event_blackout")
    if peb is None:
        logger.warning("[morning_briefing] %s: pre_event_blackout missing", symbol)
    elif not isinstance(peb, dict):
        logger.warning(
            "[morning_briefing] %s: pre_event_blackout is %s, expected dict — clearing",
            symbol, type(peb).__name__,
        )
        briefing["pre_event_blackout"] = {"start_utc": None, "end_utc": None}
    else:
        s_utc = peb.get("start_utc")
        e_utc = peb.get("end_utc")
        bad = False
        if s_utc is not None and not _valid_hhmm(s_utc):
            logger.warning(
                "[morning_briefing] %s: pre_event_blackout.start_utc=%r invalid HH:MM",
                symbol, s_utc,
            )
            bad = True
        if e_utc is not None and not _valid_hhmm(e_utc):
            logger.warning(
                "[morning_briefing] %s: pre_event_blackout.end_utc=%r invalid HH:MM",
                symbol, e_utc,
            )
            bad = True
        # Require both-or-neither; a partial blackout is meaningless.
        if (s_utc is None) != (e_utc is None):
            logger.warning(
                "[morning_briefing] %s: pre_event_blackout has only one of start_utc/end_utc set — clearing",
                symbol,
            )
            bad = True
        if bad:
            briefing["pre_event_blackout"] = {"start_utc": None, "end_utc": None}

    # session_stage_intent — dict with london + ny enums
    ssi = briefing.get("session_stage_intent")
    if ssi is None:
        logger.warning("[morning_briefing] %s: session_stage_intent missing", symbol)
    elif not isinstance(ssi, dict):
        logger.warning(
            "[morning_briefing] %s: session_stage_intent is %s, expected dict — clearing",
            symbol, type(ssi).__name__,
        )
        briefing["session_stage_intent"] = {"london": "UNKNOWN", "ny": "UNKNOWN"}
    else:
        london = str(ssi.get("london", "")).upper()
        ny     = str(ssi.get("ny", "")).upper()
        if london not in _PHASE2_LONDON_STAGES:
            logger.warning(
                "[morning_briefing] %s: session_stage_intent.london=%r invalid — expected one of %s; normalizing to UNKNOWN",
                symbol, ssi.get("london"), sorted(_PHASE2_LONDON_STAGES),
            )
            london = "UNKNOWN"
        if ny not in _PHASE2_NY_STAGES:
            logger.warning(
                "[morning_briefing] %s: session_stage_intent.ny=%r invalid — expected one of %s; normalizing to UNKNOWN",
                symbol, ssi.get("ny"), sorted(_PHASE2_NY_STAGES),
            )
            ny = "UNKNOWN"
        briefing["session_stage_intent"] = {"london": london, "ny": ny}


# ─────────────────────────────────────────────────────────────────────────────
# entry_trigger_v2 — structured-condition vocabulary validator
# ─────────────────────────────────────────────────────────────────────────────
_TRIGGER_V2_TYPES = {
    "release_event", "sweep", "candle_close", "rsi", "consecutive_closes",
}
_TRIGGER_V2_CURRENCIES = {"GBP", "USD", "EUR", "JPY", "CAD"}
_TRIGGER_V2_IMPACTS    = {"HIGH", "MEDIUM"}
_TRIGGER_V2_SIDES      = {"above", "below"}
_TRIGGER_V2_TFS        = {"5m", "15m", "1h"}
_TRIGGER_V2_CC_TFS     = {"5m"}  # consecutive_closes is 5m-only per spec
_TRIGGER_V2_RSI_OPS    = {"<", ">", "crosses_up", "crosses_down"}
_TRIGGER_V2_MAX        = 5


def _trigger_v2_error(cond: Any, idx: int, field: str, detail: str) -> str:
    ctype = "?"
    if isinstance(cond, dict):
        ctype = str(cond.get("type") or "?")
    return f"cond[{idx}] type={ctype} {field}: {detail}"


def _validate_single_trigger_v2(cond: Any, idx: int) -> Optional[str]:
    """Return None if the condition is valid; else a human-readable error string."""
    if not isinstance(cond, dict):
        return f"cond[{idx}]: not a dict (got {type(cond).__name__})"
    ctype = str(cond.get("type") or "").strip()
    if ctype not in _TRIGGER_V2_TYPES:
        return _trigger_v2_error(cond, idx, "type",
                                 f"unknown (expected one of {sorted(_TRIGGER_V2_TYPES)})")

    if ctype == "release_event":
        ev = cond.get("event_name")
        if not isinstance(ev, str) or not ev.strip():
            return _trigger_v2_error(cond, idx, "event_name", "missing or empty")
        cur = str(cond.get("currency") or "").upper()
        if cur not in _TRIGGER_V2_CURRENCIES:
            return _trigger_v2_error(cond, idx, "currency",
                                     f"invalid {cur!r} (expected one of {sorted(_TRIGGER_V2_CURRENCIES)})")
        for k in ("window_minutes_before", "window_minutes_after"):
            v = cond.get(k)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 720:
                return _trigger_v2_error(cond, idx, k, f"expected int in [0,720], got {v!r}")
        imp = str(cond.get("impact") or "").upper()
        if imp not in _TRIGGER_V2_IMPACTS:
            return _trigger_v2_error(cond, idx, "impact",
                                     f"invalid {imp!r} (expected one of {sorted(_TRIGGER_V2_IMPACTS)})")
        return None

    if ctype == "sweep":
        lv = cond.get("level")
        if not isinstance(lv, (int, float)) or isinstance(lv, bool):
            return _trigger_v2_error(cond, idx, "level", f"expected float, got {lv!r}")
        side = str(cond.get("side") or "").lower()
        if side not in _TRIGGER_V2_SIDES:
            return _trigger_v2_error(cond, idx, "side",
                                     f"invalid {side!r} (expected one of {sorted(_TRIGGER_V2_SIDES)})")
        tol = cond.get("tolerance_pips")
        if not isinstance(tol, (int, float)) or isinstance(tol, bool) or tol < 0 or tol > 100:
            return _trigger_v2_error(cond, idx, "tolerance_pips",
                                     f"expected float in [0,100], got {tol!r}")
        return None

    if ctype == "candle_close":
        tf = str(cond.get("timeframe") or "").lower()
        if tf not in _TRIGGER_V2_TFS:
            return _trigger_v2_error(cond, idx, "timeframe",
                                     f"invalid {tf!r} (expected one of {sorted(_TRIGGER_V2_TFS)})")
        direction = str(cond.get("direction") or "").lower()
        if direction not in _TRIGGER_V2_SIDES:
            return _trigger_v2_error(cond, idx, "direction",
                                     f"invalid {direction!r} (expected one of {sorted(_TRIGGER_V2_SIDES)})")
        lv = cond.get("level")
        if not isinstance(lv, (int, float)) or isinstance(lv, bool):
            return _trigger_v2_error(cond, idx, "level", f"expected float, got {lv!r}")
        return None

    if ctype == "rsi":
        tf = str(cond.get("timeframe") or "").lower()
        if tf not in _TRIGGER_V2_TFS:
            return _trigger_v2_error(cond, idx, "timeframe",
                                     f"invalid {tf!r} (expected one of {sorted(_TRIGGER_V2_TFS)})")
        op = str(cond.get("operator") or "")
        if op not in _TRIGGER_V2_RSI_OPS:
            return _trigger_v2_error(cond, idx, "operator",
                                     f"invalid {op!r} (expected one of {sorted(_TRIGGER_V2_RSI_OPS)})")
        v = cond.get("value")
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or v > 100:
            return _trigger_v2_error(cond, idx, "value", f"expected float in [0,100], got {v!r}")
        return None

    if ctype == "consecutive_closes":
        tf = str(cond.get("timeframe") or "").lower()
        if tf not in _TRIGGER_V2_CC_TFS:
            return _trigger_v2_error(cond, idx, "timeframe",
                                     f"invalid {tf!r} (expected one of {sorted(_TRIGGER_V2_CC_TFS)})")
        direction = str(cond.get("direction") or "").lower()
        if direction not in _TRIGGER_V2_SIDES:
            return _trigger_v2_error(cond, idx, "direction",
                                     f"invalid {direction!r} (expected one of {sorted(_TRIGGER_V2_SIDES)})")
        lv = cond.get("level")
        if not isinstance(lv, (int, float)) or isinstance(lv, bool):
            return _trigger_v2_error(cond, idx, "level", f"expected float, got {lv!r}")
        cnt = cond.get("count")
        if not isinstance(cnt, int) or isinstance(cnt, bool) or cnt < 1 or cnt > 20:
            return _trigger_v2_error(cond, idx, "count", f"expected int in [1,20], got {cnt!r}")
        return None

    return _trigger_v2_error(cond, idx, "type", f"unhandled {ctype!r}")


def _validate_trigger_v2_on_plans(briefing: Dict[str, Any], symbol: str) -> None:
    """Per-plan schema validation for entry_trigger_v2.

    Failure for one plan does NOT suppress v2 on other plans, and never
    blocks the briefing from publishing. Legacy entry_trigger prose is not
    touched. On failure, the offending plan's entry_trigger_v2 is set to
    None and a Telegram alert is emitted once per failing plan.
    """
    plans = briefing.get("trading_plans")
    if not isinstance(plans, list):
        return  # no plans, nothing to validate

    for p_idx, plan in enumerate(plans):
        if not isinstance(plan, dict):
            continue
        if "entry_trigger_v2" not in plan:
            continue  # absent is fine — executor falls back to legacy

        conds = plan.get("entry_trigger_v2")
        if conds is None:
            continue  # explicit null treated as absent

        label = str(plan.get("label") or f"plan#{p_idx}")
        fail_detail: Optional[str] = None

        if not isinstance(conds, list):
            fail_detail = f"entry_trigger_v2 is {type(conds).__name__}, expected list"
        elif len(conds) == 0:
            fail_detail = "entry_trigger_v2 is empty list (expected >= 1 condition)"
        elif len(conds) > _TRIGGER_V2_MAX:
            fail_detail = f"entry_trigger_v2 has {len(conds)} conditions (max {_TRIGGER_V2_MAX})"
        else:
            for c_idx, cond in enumerate(conds):
                err = _validate_single_trigger_v2(cond, c_idx)
                if err is not None:
                    fail_detail = err
                    break

        if fail_detail is not None:
            logger.error(
                "[morning_briefing] %s plan=%r entry_trigger_v2 validation failed: %s",
                symbol, label, fail_detail,
            )
            plan["entry_trigger_v2"] = None
            try:
                from telegram_alerts import send_telegram_message
                send_telegram_message(
                    f"⚠️ briefing trigger_v2 validation failed pair={symbol} "
                    f"plan={label} — executor falling back to legacy gating"
                )
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — trading_plans session split + london_condition validation
# ─────────────────────────────────────────────────────────────────────────────

_PLAN_SESSIONS               = {"London", "NY"}
_LONDON_CONDITION_TYPES      = {
    "close_above", "close_below", "ranged", "swept_then_reversed", "held_at",
}
_LONDON_CONDITION_NEEDS_TOL  = {"ranged", "held_at"}
_LONDON_CONDITION_MAX_DESC_W = 25
_PLANS_PER_SESSION_MIN       = 2
_PLANS_PER_SESSION_MAX       = 3
_PLANS_TOTAL_MIN             = 4
_PLANS_TOTAL_MAX             = 6


def _validate_london_condition(cond: Any, plan_idx: int) -> List[str]:
    """Return a list of error strings for one NY plan's london_condition."""
    errs: List[str] = []
    if not isinstance(cond, dict):
        return [f"plan[{plan_idx}] NY plans require london_condition object, got {type(cond).__name__}"]

    ctype = str(cond.get("type") or "").strip()
    if ctype not in _LONDON_CONDITION_TYPES:
        errs.append(
            f"plan[{plan_idx}] london_condition.type={ctype!r} not in "
            f"{sorted(_LONDON_CONDITION_TYPES)}"
        )
        return errs

    lvl = cond.get("level")
    if not isinstance(lvl, (int, float)) or isinstance(lvl, bool):
        errs.append(f"plan[{plan_idx}] london_condition.level must be a number, got {lvl!r}")

    if ctype in _LONDON_CONDITION_NEEDS_TOL:
        tol = cond.get("tolerance_pips")
        if not isinstance(tol, (int, float)) or isinstance(tol, bool) or tol <= 0:
            errs.append(
                f"plan[{plan_idx}] london_condition.tolerance_pips must be a positive number "
                f"for type={ctype!r}, got {tol!r}"
            )

    desc = str(cond.get("description") or "").strip()
    if not desc:
        errs.append(f"plan[{plan_idx}] london_condition.description is required")
    else:
        wc = len(desc.split())
        if wc > _LONDON_CONDITION_MAX_DESC_W:
            errs.append(
                f"plan[{plan_idx}] london_condition.description has {wc} words "
                f"(max {_LONDON_CONDITION_MAX_DESC_W})"
            )
    return errs


def _validate_plans(briefing: Dict[str, Any], symbol: str) -> List[str]:
    """Validate the Phase 2 trading_plans structure: 2-3 London + 2-3 NY,
    each carrying a `session` field, NY plans carrying a valid
    london_condition. Mutates the plan dicts in place to normalize session
    capitalization. Returns a list of human-readable errors (empty = OK).
    """
    plans = briefing.get("trading_plans")
    errs: List[str] = []
    if not isinstance(plans, list) or not plans:
        errs.append("trading_plans is empty/missing")
        return errs

    london_count = 0
    ny_count = 0
    london_ranks: List[int] = []
    ny_ranks: List[int] = []

    for idx, plan in enumerate(plans):
        if not isinstance(plan, dict):
            errs.append(f"plan[{idx}] is not an object")
            continue

        sess_raw = str(plan.get("session") or "").strip()
        sess = sess_raw.capitalize() if sess_raw.lower() != "ny" else "NY"
        if sess not in _PLAN_SESSIONS:
            errs.append(
                f"plan[{idx}] session={sess_raw!r} not in {sorted(_PLAN_SESSIONS)}"
            )
            continue
        plan["session"] = sess

        try:
            rank = int(plan.get("rank"))
        except (TypeError, ValueError):
            errs.append(f"plan[{idx}] rank={plan.get('rank')!r} not an integer")
            continue

        cond = plan.get("london_condition", None)
        if sess == "London":
            london_count += 1
            london_ranks.append(rank)
            if cond is not None:
                errs.append(
                    f"plan[{idx}] London plan must have london_condition=null, "
                    f"got {type(cond).__name__}"
                )
        else:  # NY
            ny_count += 1
            ny_ranks.append(rank)
            errs.extend(_validate_london_condition(cond, idx))

        # Phase 3 — raw_probability + probability presence/range
        for fld in ("raw_probability", "probability"):
            v = plan.get(fld)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errs.append(
                    f"plan[{idx}] {fld}={v!r} must be a number in [0.0, 1.0]"
                )
                continue
            fv = float(v)
            if not (0.0 <= fv <= 1.0):
                errs.append(
                    f"plan[{idx}] {fld}={fv:g} out of range [0.0, 1.0]"
                )

    if not (_PLANS_PER_SESSION_MIN <= london_count <= _PLANS_PER_SESSION_MAX):
        errs.append(
            f"London plan count is {london_count}; need "
            f"{_PLANS_PER_SESSION_MIN}-{_PLANS_PER_SESSION_MAX}"
        )
    if not (_PLANS_PER_SESSION_MIN <= ny_count <= _PLANS_PER_SESSION_MAX):
        errs.append(
            f"NY plan count is {ny_count}; need "
            f"{_PLANS_PER_SESSION_MIN}-{_PLANS_PER_SESSION_MAX}"
        )
    total = london_count + ny_count
    if not (_PLANS_TOTAL_MIN <= total <= _PLANS_TOTAL_MAX):
        errs.append(
            f"total plan count is {total}; need {_PLANS_TOTAL_MIN}-{_PLANS_TOTAL_MAX}"
        )

    for label, ranks in (("London", london_ranks), ("NY", ny_ranks)):
        if ranks:
            sr = sorted(ranks)
            expected = list(range(1, len(sr) + 1))
            if sr != expected:
                errs.append(
                    f"{label} plan ranks must be unique and contiguous starting at 1; got {sr}"
                )

    if errs:
        for e in errs:
            logger.warning("[morning_briefing] %s: plans validation: %s", symbol, e)

    return errs


def _call_anthropic(data_package: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call the Anthropic API; retry once on levels-validation failure with
    explicit feedback fed back to the model. Returns None on any failure —
    callers keep existing briefing and fail open.
    """
    if not ANTHROPIC_API_KEY:
        logger.warning(
            "[morning_briefing] ANTHROPIC_API_KEY not set — briefing skipped. "
            "Add ANTHROPIC_API_KEY to .env to enable briefings."
        )
        return None

    # Defense-in-depth: scheduler/catch-up gates above should already
    # block weekend fires, but keep this as the last line of defense
    # before we pay for an Anthropic call.
    if _is_fx_market_closed():
        logger.info("[morning_briefing] Weekend market closure — briefing skipped")
        return None

    sym     = data_package.get("symbol", "")
    session = data_package.get("session", "")

    feedback: Optional[str] = None
    for validation_attempt in (1, 2):
        briefing, level_errors = _call_anthropic_once(data_package, feedback)
        if briefing is None:
            return None
        if not level_errors:
            return briefing
        if validation_attempt == 1:
            feedback = "\n".join(f"  - {e}" for e in level_errors)
            logger.warning(
                "[morning_briefing] %s/%s: levels validation failed (%d issues); "
                "retrying once with feedback",
                sym, session, len(level_errors),
            )
            continue
        logger.error(
            "[morning_briefing] %s/%s: levels validation failed after retry — "
            "no briefing for this session. Issues: %s",
            sym, session, "; ".join(level_errors),
        )
        return None
    return None


def _call_anthropic_once(
    data_package: Dict[str, Any],
    validation_feedback: Optional[str] = None,
) -> tuple:
    """One end-to-end briefing attempt: HTTP + parse + level validation.

    Returns ``(briefing_dict_or_None, level_errors_list)``:
      - ``(None, [])``         — hard failure (HTTP/parse). Do not retry.
      - ``(briefing, [])``     — success.
      - ``(briefing, errors)`` — parsed but levels validation failed; the
                                 caller may regenerate with feedback.
    """
    sym     = data_package.get("symbol", "")
    session = data_package.get("session", "")

    for attempt in (1, 2):
        pkg          = data_package if attempt == 1 else _slim_data_package(data_package)
        user_message = _build_user_message(sym, session, pkg, validation_feedback)

        # ── HTTP call (up to 2 tries on timeout) ──────────────────────────
        max_timeout_tries = 3
        resp = None
        for t_try in range(1, max_timeout_tries + 1):
            try:
                logger.info(
                    f"[morning_briefing] {sym}/{session}: API request "
                    f"attempt {t_try} of {max_timeout_tries}"
                )
                resp = requests.post(
                    ANTHROPIC_URL,
                    headers={
                        "x-api-key":         ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type":      "application/json",
                    },
                    json={
                        "model":       ANTHROPIC_MODEL,
                        "max_tokens":  BRIEFING_MAX_TOKENS,
                        "temperature": ANTHROPIC_TEMPERATURE,
                        "system":      SYSTEM_PROMPT,
                        "messages":    [{"role": "user", "content": user_message}],
                    },
                    timeout=API_TIMEOUT,
                )
                resp.raise_for_status()
                break  # success
            except requests.exceptions.Timeout:
                logger.warning(
                    f"[morning_briefing] {sym}/{session}: API request timed out "
                    f"after {API_TIMEOUT}s (attempt {t_try} of {max_timeout_tries})"
                )
                if t_try < max_timeout_tries:
                    logger.info(
                        f"[morning_briefing] {sym}/{session}: waiting 10s before retry…"
                    )
                    time.sleep(10)
                    continue
                _LAST_ANTHROPIC_FAILURE_REASON[(sym, session)] = (
                    f"timeout after {API_TIMEOUT}s "
                    f"({max_timeout_tries} tries)"
                )
                return None, []
            except requests.exceptions.HTTPError as exc:
                try:
                    error_body = exc.response.text[:2000]
                except Exception:
                    error_body = "(could not read response body)"
                try:
                    _status = exc.response.status_code
                except Exception:
                    _status = "?"
                logger.error(
                    f"[morning_briefing] {sym}/{session}: API HTTP {_status}: {exc} | "
                    f"response_body={error_body}"
                )
                _LAST_ANTHROPIC_FAILURE_REASON[(sym, session)] = (
                    f"HTTP {_status}: {error_body[:200]}"
                )
                return None, []
            except Exception as exc:
                logger.warning(
                    f"[morning_briefing] {sym}/{session}: API request failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                _LAST_ANTHROPIC_FAILURE_REASON[(sym, session)] = (
                    f"{type(exc).__name__}: {str(exc)[:200]}"
                )
                return None, []

        # ── Parse response ───────────────────────────────────────────────────
        text = ""
        stop_reason = None
        output_tokens = None
        try:
            body = resp.json()
            stop_reason = body.get("stop_reason")
            output_tokens = (body.get("usage") or {}).get("output_tokens")
            text = body["content"][0]["text"].strip()

            if output_tokens and output_tokens > 0.85 * BRIEFING_MAX_TOKENS:
                logger.warning(
                    f"[BRIEFING] {sym} response at {len(text)} chars / "
                    f"{output_tokens} output_tokens (cap {BRIEFING_MAX_TOKENS}) — "
                    f"consider further bump if approaching limit"
                )

            # Strip accidental markdown fencing
            if text.startswith("```"):
                lines = text.split("\n")
                text  = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                ).strip()

            briefing = json.loads(text)

            # --- Derive session_bias from H1 momentum if missing/null ---
            if not briefing.get("session_bias"):
                _derived = _derive_session_bias_from_h1(data_package)
                if _derived:
                    briefing["session_bias"] = _derived
                    logger.warning(
                        "[morning_briefing] %s session_bias missing from response "
                        "— derived %s from H1 momentum",
                        sym, _derived,
                    )
                elif str(briefing.get("daily_bias", "")).upper() in ("BULLISH", "BEARISH"):
                    briefing["session_bias"] = briefing["daily_bias"]
                    logger.warning(
                        "[morning_briefing] %s session_bias missing, H1 flat "
                        "— falling back to daily_bias %s",
                        sym, briefing["daily_bias"],
                    )

            # Default regime if missing
            if not briefing.get("regime") or str(briefing.get("regime", "")).upper() not in ("SWEEP", "TREND", "NEWS"):
                briefing["regime"] = "SWEEP"
                briefing.setdefault("regime_confidence", 0.5)
                briefing.setdefault("regime_reasoning", "default — no regime returned by API")

            # Default structure if missing (4D). Separate from `regime`
            # (session character) — this is the market-structure axis the
            # candle classifier's shadow path compares against. Vocabulary
            # chosen to be non-directional so it doesn't overlap with bias.
            if not briefing.get("structure") or str(briefing.get("structure", "")).upper() not in ("TRENDING", "RANGE", "NEUTRAL"):
                briefing["structure"] = "NEUTRAL"
                briefing.setdefault("structure_confidence", 0.5)
                briefing.setdefault("structure_reasoning", "defaulted due to AI omission or invalid value")

            # Update regime router
            try:
                import regime_router
                regime_router.update_regime(sym, briefing)
            except Exception as _rr_err:
                logger.debug("[morning_briefing] regime_router update failed: %s", _rr_err)

            # Sanity-check required keys
            required = {"symbol", "daily_bias", "session_bias", "signal_filter"}
            missing  = required - set(briefing.keys())
            if missing:
                raise ValueError(f"response missing keys {missing}")

            # Validate & clean the structured levels array FIRST — signal_filter
            # is now derived from the levels array, so it must be validated before
            # the flags are computed.
            levels, level_errors = _validate_levels(briefing.get("levels") or [], sym)
            briefing["levels"] = levels
            # Derive legacy fields from the new ranked levels[] array so existing
            # consumers (BB_REVERSAL TP placement, NEWS_TICK proximity matching)
            # keep working without modification. Phase 1 backwards compatibility.
            _populate_legacy_levels(briefing, levels)

            # Phase 2 structured fields — warn/normalize in place, never crash.
            _validate_phase2_fields(briefing, sym)

            # entry_trigger_v2 — structured trigger vocabulary on each plan.
            # Per-plan validation: a bad plan has its v2 cleared to None
            # (legacy prose still ships) and a Telegram alert is emitted;
            # good plans on the same briefing keep their v2 intact.
            _validate_trigger_v2_on_plans(briefing, sym)

            # Phase 2 — trading_plans session split + london_condition.
            # Errors are aggregated with level_errors; the wrapper retries
            # the whole briefing once with explicit feedback if any errors
            # are present.
            plan_errors = _validate_plans(briefing, sym)
            level_errors = list(level_errors) + list(plan_errors)

            # signal_filter: driven by the directions actually present in levels.
            # Rule: allow_X=true if any level has trade_direction=X. Only set
            # allow_X=false when there are zero X-direction levels AND session_bias
            # is strongly opposed (directional and opposite to X).
            sf              = briefing.get("signal_filter") or {}
            _model_allow_b  = sf.get("allow_buys")
            _model_allow_s  = sf.get("allow_sells")
            session         = str(briefing.get("session_bias", "")).upper()

            _buy_count  = sum(1 for lv in levels if lv.get("trade_direction") == "BUY")
            _sell_count = sum(1 for lv in levels if lv.get("trade_direction") == "SELL")
            has_buy_levels  = _buy_count  > 0
            has_sell_levels = _sell_count > 0

            allow_buys  = True
            allow_sells = True
            if not has_buy_levels  and session == "BEARISH":
                allow_buys  = False
            if not has_sell_levels and session == "BULLISH":
                allow_sells = False

            # Warn if the model's returned signal_filter contradicts the levels array.
            if _model_allow_s is False and has_sell_levels:
                logger.warning(
                    "[morning_briefing] %s: model returned allow_sells=false but "
                    "levels array contains %d SELL entries — overriding to true",
                    sym, _sell_count,
                )
            if _model_allow_b is False and has_buy_levels:
                logger.warning(
                    "[morning_briefing] %s: model returned allow_buys=false but "
                    "levels array contains %d BUY entries — overriding to true",
                    sym, _buy_count,
                )

            sf["allow_buys"]  = allow_buys
            sf["allow_sells"] = allow_sells
            briefing["signal_filter"] = sf

            return briefing, level_errors

        except (json.JSONDecodeError, ValueError) as exc:
            _trunc_tag = " [TRUNCATED]" if stop_reason == "max_tokens" else ""
            _diag = (
                f"len={len(text)} stop_reason={stop_reason!r} "
                f"output_tokens={output_tokens}{_trunc_tag}"
            )
            if attempt == 1:
                logger.warning(
                    f"[morning_briefing] {sym}/{session}: parse failed on attempt 1 "
                    f"({exc}) — retrying with slimmed data package (10 candles per TF)\n"
                    f"  diagnostics: {_diag}\n"
                    f"  first 300 chars: {text[:300]}\n"
                    f"  last 200 chars : {text[-200:]}"
                )
                continue
            logger.warning(
                f"[morning_briefing] {sym}/{session}: parse failed on attempt 2 "
                f"({exc}) — giving up\n"
                f"  diagnostics: {_diag}\n"
                f"  first 300 chars: {text[:300]}\n"
                f"  last 200 chars : {text[-200:]}"
            )
            _LAST_ANTHROPIC_FAILURE_REASON[(sym, session)] = (
                f"parse error: {type(exc).__name__}: {str(exc)[:200]}"
            )
            return None, []
        except Exception as exc:
            logger.warning(
                f"[morning_briefing] {sym}/{session}: response parse error: "
                f"{type(exc).__name__}: {exc}"
            )
            _LAST_ANTHROPIC_FAILURE_REASON[(sym, session)] = (
                f"parse error: {type(exc).__name__}: {str(exc)[:200]}"
            )
            return None, []

    return None, []

# ─────────────────────────────────────────────────────────────────────────────
# File persistence
# ─────────────────────────────────────────────────────────────────────────────

def _briefing_path(symbol: str, date: str, session: str) -> Path:
    return LOG_DIR / f"briefing_{symbol}_{date}_{session}.json"


def _save_briefing(symbol: str, session: str, briefing: Dict[str, Any]) -> None:
    today = _utc_today()
    path  = _briefing_path(symbol, today, session)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(briefing, indent=2, default=str))
        logger.debug(f"[morning_briefing] saved {path.name}")
    except Exception as exc:
        logger.warning(f"[morning_briefing] {symbol}/{session}: save failed: {exc}")


def _load_latest_briefing_for_today(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Return the most recent on-disk briefing for symbol on today's UTC date.
    Checks sessions in reverse chronological order
    (NY_Mid → NY_Data → NY → Mid-session → London_Open → London → Asian).
    """
    today = _utc_today()
    for session in reversed(_BRIEFING_DISK_SESSIONS):
        path = _briefing_path(symbol, today, session)
        if path.exists():
            try:
                briefing = json.loads(path.read_text())
                logger.info(
                    f"[morning_briefing] {symbol}: loaded {session} briefing from disk "
                    f"(bias={briefing.get('daily_bias','?')})"
                )
                return briefing
            except Exception as exc:
                logger.warning(f"[morning_briefing] {symbol}: failed to load {path.name}: {exc}")
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Briefing refresh for one symbol
# ─────────────────────────────────────────────────────────────────────────────

def _refresh_symbol(symbol: str, session: str) -> Optional[Dict[str, Any]]:
    """Assemble data, call API, store and persist briefing for one symbol.

    Returns the briefing dict on success, or None on failure. On failure,
    records the real reason in _LAST_REFRESH_SKIP_REASON so the caller can
    propagate it into alerts instead of falling back to "API timeout or
    parse error" (which previously masked a 14-day data-availability skip).
    """
    sym = symbol.upper()
    logger.info(f"[morning_briefing] {sym}/{session}: assembling data package")

    package = _assemble_data_package(sym, session)
    if package is None:
        # Warning already logged inside _assemble_data_package; reason recorded there too.
        _LAST_REFRESH_SKIP_REASON.setdefault((sym, session), "data unavailable (see log)")
        return None

    logger.info(f"[morning_briefing] {sym}/{session}: calling Anthropic API")
    briefing = _call_anthropic(package)

    if briefing is None:
        real_reason = _LAST_ANTHROPIC_FAILURE_REASON.pop(
            (sym, session), None
        ) or "unknown (see log for upstream warning)"
        logger.error(
            f"[morning_briefing] {sym}/{session}: Anthropic call failed — "
            f"{real_reason} — no briefing available, trades will be blocked"
        )
        _LAST_REFRESH_SKIP_REASON[(sym, session)] = (
            f"Anthropic call failed: {real_reason}"
        )
        return None

    # --- API session_bias and bias_confidence are authoritative ---
    session_bias_raw = str(briefing.get("session_bias", "")).upper()
    # Store calculated values for audit only — never override API fields
    briefing["calc_bias_confidence"] = _calc_bias_confidence(package)

    # Bug 1 fix — deterministic daily_bias override.
    # daily_bias is computed by compute_d1_direction (single source of truth
    # for the briefing producer AND d1_veto). The LLM's value is replaced
    # whenever the deterministic result is available; the LLM-authored value
    # is retained as `daily_bias_llm` for audit.
    _d1_detail = (package or {}).get("d1_direction_detail")
    _llm_daily_bias = str(briefing.get("daily_bias", "NEUTRAL")).upper()
    briefing["daily_bias_llm"] = _llm_daily_bias
    if _d1_detail and _d1_detail.get("reason") != "insufficient_d1_history":
        try:
            from d1_direction import map_direction_to_daily_bias
            _det_bias = map_direction_to_daily_bias(_d1_detail.get("direction", "NEUTRAL"))
            briefing["daily_bias"] = _det_bias
            briefing["d1_direction_detail"] = _d1_detail
            if _det_bias != _llm_daily_bias:
                logger.warning(
                    "[morning_briefing] %s/%s: daily_bias overridden — "
                    "LLM=%s deterministic=%s score=%+d/9 reason=%s",
                    sym, session, _llm_daily_bias, _det_bias,
                    _d1_detail.get("score", 0), _d1_detail.get("reason", "?"),
                )

            # Narrative-vs-bias contradiction detector. If the LLM still
            # discusses the opposite direction (legacy template residue),
            # surface it so the operator can see the mismatch.
            _narr = (
                str(briefing.get("bias_reasoning", "") or "")
                + " "
                + str(briefing.get("expectation_reasoning", "") or "")
            ).lower()
            _contradicts = False
            if _det_bias == "BULLISH" and ("bearish" in _narr or "short bias" in _narr):
                _contradicts = True
            elif _det_bias == "BEARISH" and ("bullish" in _narr or "long bias" in _narr):
                _contradicts = True
            if _contradicts:
                logger.warning(
                    "[morning_briefing] %s/%s: narrative contradicts deterministic "
                    "daily_bias=%s — text mentions opposite direction",
                    sym, session, _det_bias,
                )
                briefing["daily_bias_narrative_contradiction"] = True
        except Exception as _ov_exc:
            logger.warning(
                "[morning_briefing] %s/%s: daily_bias override failed (%s) — "
                "retaining LLM value",
                sym, session, _ov_exc,
            )
    else:
        briefing["d1_direction_detail"] = _d1_detail

    # Bug 1 completion (commit b8c05de + this commit): daily_bias is the
    # deterministic 9-check D1 direction and is authoritative for the
    # directional filter. The previous "conflict → NEUTRAL" collapse
    # discarded directional signal whenever the LLM's session_bias disagreed
    # with the 9-check; in 30-day replay that wiped out ~50% of usable
    # directional gates. session_bias (LLM) remains in the briefing for
    # narrative purposes (entry zones, plan triggers); it no longer
    # influences signal_filter.
    daily_bias = str(briefing.get("daily_bias", "NEUTRAL")).upper()
    if daily_bias == "BULLISH":
        eff_bias = "BULLISH"
    elif daily_bias == "BEARISH":
        eff_bias = "BEARISH"
    else:
        eff_bias = "NEUTRAL"

    sf = briefing.get("signal_filter") or {}
    if eff_bias == "BULLISH":
        sf["allow_buys"]  = True
        sf["allow_sells"] = False
    elif eff_bias == "BEARISH":
        sf["allow_buys"]  = False
        sf["allow_sells"] = True
    else:
        sf["allow_buys"]  = True
        sf["allow_sells"] = True
    # Bug 3 fix — signal_filter.notes is now deterministic, templated from
    # the booleans + d1_direction_detail. LLM-authored notes are discarded
    # so the displayed label and the supporting text cannot contradict.
    sf["notes"] = _signal_filter_notes(
        allow_buys=sf["allow_buys"],
        allow_sells=sf["allow_sells"],
        d1_detail=_d1_detail,
        session_bias=session_bias_raw,
    )
    briefing["signal_filter"] = sf

    logger.info(
        f"[morning_briefing] {sym}/{session}: session_bias={session_bias_raw} "
        f"daily_bias={daily_bias} "
        f"allow_buys={sf.get('allow_buys')} allow_sells={sf.get('allow_sells')} "
        f"confidence={briefing.get('bias_confidence','?')} "
        f"news_risk={briefing.get('news_risk','?')}"
    )

    _apply_avoid_before_fallback(briefing)

    # best_trade structural validation (Phase A — feat/briefing-best-trade).
    # Failure clears the field, persists raw payload to disk, fires Telegram
    # WARNING (deduped per pair-day). Existing pipeline unaffected.
    _validate_best_trade(briefing, sym, session)

    with _LOCK:
        _BRIEFINGS[sym] = briefing

    _save_briefing(sym, session, briefing)

    # Store prediction for outcome tracking
    try:
        import briefing_outcome_tracker
        briefing_outcome_tracker.store_prediction(briefing)
    except Exception:
        pass

    # Capture training data (input features + output briefing)
    try:
        import briefing_training_collector
        _prompt_hash = briefing_training_collector._prompt_version_hash(
            RESPONSE_SCHEMA, SYSTEM_PROMPT,
        )
        briefing_training_collector.store_training_record(
            data_package=package,
            briefing=briefing,
            model=ANTHROPIC_MODEL,
            prompt_hash=_prompt_hash,
        )
    except Exception as _tc_err:
        logger.warning("[morning_briefing] training collector error: %s", _tc_err)

    # Log to session narrative for cross-session continuity
    try:
        from briefing_narrative import log_session
        log_session(
            pair=sym,
            session=session,
            bias=str(briefing.get("session_bias", "")),
            confidence=briefing.get("bias_confidence", 0),
            reasoning_summary=str(briefing.get("narrative_summary", "") or briefing.get("bias_reasoning", "")[:150]),
            key_levels=briefing.get("key_levels"),
        )
    except Exception:
        pass

    # Register dynamic blackout windows from news_context.avoid_before
    try:
        from news_blackout import register_window
        nc = briefing.get("news_context") or {}
        avoid_times = nc.get("avoid_before") or []
        if avoid_times:
            today = _utc_today()
            for t_str in avoid_times:
                # Accept "HH:MM" format — strip any trailing text
                clean = str(t_str).strip()[:5]
                if len(clean) == 5 and ":" in clean:
                    register_window(today, clean)
    except Exception as exc:
        logger.debug(f"[morning_briefing] avoid_before registration error: {exc}")

    return briefing


def _send_telegram(text: str) -> None:
    """Send a Telegram message via the shared telegram_alerts helper so the
    per-host ALERT_HOST_LABEL prefix and retry logic apply."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("[morning_briefing] TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set — skipping Telegram summary")
        return
    try:
        from telegram_alerts import send_telegram_message
        send_telegram_message(text, parse_mode="HTML")
    except Exception as exc:
        logger.warning(f"[morning_briefing] Telegram send failed: {exc}")


def _send_briefing_summary_telegram(session: str, results: Dict[str, Dict[str, Any]]) -> None:
    """Send a Telegram summary of briefing results for a session."""
    now = _utc_now()
    date_str = now.strftime("%d %b")
    # Use the active schedule so the time matches what actually fired
    stime = ""
    for hh, mm, name in _get_sessions(now):
        if name == session:
            stime = f"{hh:02d}:{mm:02d}"
            break
    lines = [f"\U0001f4cb FX Briefing \u2014 {session} ({stime} UTC) {date_str}"]

    failed_symbols = []
    for sym in sorted(results):
        info = results[sym]
        if info.get("success"):
            briefing = info.get("briefing", {})
            session_bias = briefing.get("session_bias", "NEUTRAL")
            daily_bias = briefing.get("daily_bias", "NEUTRAL")
            confidence = briefing.get("bias_confidence", "?")
            regime = briefing.get("regime", "N/A")
            regime_conf = briefing.get("regime_confidence", "?")
            lines.append(
                f"\u2705 {sym} \u2014 Session: {session_bias} (conf {confidence}) "
                f"| D1: {daily_bias} | {regime}"
            )
            narrative = briefing.get("narrative_summary", "")
            if narrative:
                lines.append(f"   {narrative}")
            _levels = briefing.get("levels") or []
            if isinstance(_levels, list) and _levels:
                _hi  = sum(1 for lv in _levels if isinstance(lv, dict) and str(lv.get("strength", "")).upper() == "HIGH")
                _med = sum(1 for lv in _levels if isinstance(lv, dict) and str(lv.get("strength", "")).upper() == "MEDIUM")
                _lo  = sum(1 for lv in _levels if isinstance(lv, dict) and str(lv.get("strength", "")).upper() == "LOW")
                lines.append(
                    f"   \U0001f4d0 {sym}: {len(_levels)} levels parsed "
                    f"({_hi} HIGH, {_med} MEDIUM, {_lo} LOW)"
                )
            # Phase 2 fields (sweep / fade / per-session stage intent)
            _ssi = briefing.get("session_stage_intent") or {}
            _sweep = str(briefing.get("sweep_direction") or "?")
            _fade = briefing.get("fade_after_sweep")
            _fade_s = "true" if _fade is True else ("false" if _fade is False else "?")
            _london = str(_ssi.get("london") or "?") if isinstance(_ssi, dict) else "?"
            _ny = str(_ssi.get("ny") or "?") if isinstance(_ssi, dict) else "?"
            lines.append(
                f"   \U0001f50d Sweep: {_sweep} | Fade: {_fade_s} | London: {_london} | NY: {_ny}"
            )
        else:
            error = info.get("error", "Unknown error")
            lines.append(f"\u274c {sym} \u2014 Failed ({error})")
            failed_symbols.append(sym)

    if failed_symbols:
        lines.append(f"\u26a0\ufe0f No trades will fire on failed pairs until briefing succeeds")

    _send_telegram("\n".join(lines))


BRIEFING_RETRY_DELAYS_MINUTES = [5, 10, 15]  # exponential-ish backoff


# ─────────────────────────────────────────────────────────────────────────────
# NY_Data — lightweight partial refresh (news context only, no full briefing)
# ─────────────────────────────────────────────────────────────────────────────

def _collect_recent_releases() -> List[Dict[str, Any]]:
    """Collect today's high-impact events whose release time is within the last
    ~30 minutes, enriched with Finnhub/TE actuals when available."""
    out: List[Dict[str, Any]] = []
    try:
        events = news_calendar.get_todays_events() or []
    except Exception:
        return out
    now = _utc_now()
    for ev in events:
        if (ev.get("impact") or "").lower() != "high":
            continue
        try:
            hh, mm = map(int, str(ev.get("time", "")).split(":"))
        except Exception:
            continue
        ev_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        mins_since = (now - ev_dt).total_seconds() / 60.0
        if -5 <= mins_since <= 45:
            entry = {
                "time":     ev.get("time"),
                "currency": ev.get("currency"),
                "event":    ev.get("event_name"),
                "forecast": ev.get("forecast"),
                "mins_since_release": round(mins_since, 1),
            }
            try:
                import te_calendar
                actual = te_calendar.get_actual_for_event(
                    str(ev.get("event_name", "")),
                    currency=str(ev.get("currency", "")),
                )
                if actual:
                    entry["actual"]       = actual.get("actual_str")
                    entry["deviation"]    = actual.get("deviation")
                    entry["beat_miss"]    = actual.get("beat_miss")
                    entry["direction_hint"] = actual.get("direction_hint")
            except Exception:
                pass
            out.append(entry)
    return out


def _refresh_news_context(symbol: str, session: str) -> Optional[Dict[str, Any]]:
    """NY_Data partial refresh — short focused Anthropic call updating only
    news_risk, news_context.has_high_impact, and signal_filter.allow_buys/allow_sells
    on the existing cached NY briefing. Fail-open: returns None on error and
    leaves the cached briefing unchanged.
    """
    sym = symbol.upper()
    with _LOCK:
        cached = _BRIEFINGS.get(sym)
    if cached is None:
        logger.warning("[morning_briefing] NY_Data %s: no cached briefing to update — skipping", sym)
        return None

    if not ANTHROPIC_API_KEY:
        logger.warning("[morning_briefing] NY_Data %s: ANTHROPIC_API_KEY missing — skipping", sym)
        return None

    releases = _collect_recent_releases()

    prompt = (
        f"Pair: {sym}\n"
        f"Recent high-impact releases (within ~30 min of {session}):\n"
        f"{json.dumps(releases, default=str)}\n\n"
        "Given these actual data releases vs forecasts, update the post-release news "
        f"picture for {sym}. Consider whether the releases argue for blocking BUY or "
        "SELL entries over the remainder of the session, and the residual news risk. "
        "Respond with ONLY this JSON (no prose, no markdown):\n"
        '{"news_risk": "HIGH|MEDIUM|LOW|NONE", '
        '"news_context": {"has_high_impact": true|false}, '
        '"signal_filter": {"allow_buys": true|false, "allow_sells": true|false}}'
    )

    try:
        resp = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      ANTHROPIC_MODEL,
                "max_tokens": 256,
                "system":     "You are a forex news-context analyzer. Respond with only the requested JSON.",
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"].strip()
        if text.startswith("```"):
            text = "\n".join(
                ln for ln in text.split("\n") if not ln.strip().startswith("```")
            ).strip()
        update = json.loads(text)
    except Exception as exc:
        logger.warning(
            "[morning_briefing] NY_Data %s: API call failed (%s) — cached NY briefing unchanged",
            sym, exc,
        )
        return None

    # Merge updates into the cached briefing (copy to avoid mutating concurrently)
    new_briefing = dict(cached)
    try:
        if "news_risk" in update:
            new_briefing["news_risk"] = update["news_risk"]
        _nc_in = update.get("news_context") or {}
        if isinstance(_nc_in, dict) and "has_high_impact" in _nc_in:
            nc = dict(new_briefing.get("news_context") or {})
            nc["has_high_impact"] = _nc_in["has_high_impact"]
            new_briefing["news_context"] = nc
        _sf_in = update.get("signal_filter") or {}
        if isinstance(_sf_in, dict):
            sf = dict(new_briefing.get("signal_filter") or {})
            if "allow_buys" in _sf_in:
                sf["allow_buys"] = _sf_in["allow_buys"]
            if "allow_sells" in _sf_in:
                sf["allow_sells"] = _sf_in["allow_sells"]
            new_briefing["signal_filter"] = sf
    except Exception as exc:
        logger.warning("[morning_briefing] NY_Data %s: merge failed (%s) — cached NY briefing unchanged", sym, exc)
        return None

    new_briefing["last_refresh_session"] = session
    new_briefing["last_refresh_ts"]      = datetime.now(timezone.utc).isoformat()

    with _LOCK:
        _BRIEFINGS[sym] = new_briefing
    # Overwrite the NY file on disk (not a new NY_Data file) so downstream
    # readers pick up the refreshed news context automatically.
    _save_briefing(sym, "NY", new_briefing)

    sf = new_briefing.get("signal_filter") or {}
    logger.info(
        "[morning_briefing] NY_Data %s: refreshed news_risk=%s allow_buys=%s allow_sells=%s releases=%d",
        sym, new_briefing.get("news_risk"),
        sf.get("allow_buys"), sf.get("allow_sells"), len(releases),
    )
    return new_briefing


def _run_news_context_refresh(symbols: List[str]) -> None:
    """NY_Data entry point — single-shot per symbol, fail-open, no retry/finalise."""
    for sym in symbols:
        result = None
        try:
            result = _refresh_news_context(sym, "NY_Data")
        except Exception as exc:
            logger.warning("[morning_briefing] NY_Data %s: unhandled error: %s", sym, exc, exc_info=True)
        if result is not None:
            try:
                sf = result.get("signal_filter") or {}
                _send_telegram(
                    f"⚡ NY_Data refresh — {sym} news_risk: {result.get('news_risk','?')} "
                    f"| buys: {sf.get('allow_buys')} | sells: {sf.get('allow_sells')}"
                )
            except Exception as exc:
                logger.debug("[morning_briefing] NY_Data %s: Telegram error: %s", sym, exc)


def _run_briefing_once(session: str, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Single pass over symbols — returns per-symbol results dict."""
    results: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        try:
            briefing = _refresh_symbol(sym, session)
            if briefing and briefing.get("daily_bias"):
                results[sym] = {"success": True, "briefing": briefing}
            else:
                reason = _LAST_REFRESH_SKIP_REASON.pop((sym, session), None) or (
                    "API response missing daily_bias" if briefing else
                    "_refresh_symbol returned None (no reason recorded; see log for upstream warning)"
                )
                results[sym] = {"success": False, "error": reason}
        except Exception as exc:
            logger.warning(
                f"[morning_briefing] {sym}/{session}: unhandled error: {exc}",
                exc_info=True,
            )
            results[sym] = {"success": False, "error": str(exc)[:80]}
    return results


def _finalise_briefing(session: str, results: Dict[str, Dict[str, Any]]) -> None:
    """Send email + Telegram summary; alert on remaining failures."""
    still_failed = [s for s, r in results.items() if not r.get("success")]
    if still_failed:
        per_pair = ", ".join(
            f"{s} ({results[s].get('error') or 'unknown reason'})"
            for s in still_failed
        )
        alert = (
            f"⚠️ BRIEFING FAILED — all retries exhausted, strategies disabled "
            f"for {session}. Failed pairs: {per_pair}"
        )
        logger.error("[morning_briefing] %s", alert)
        try:
            _send_telegram(alert)
        except Exception as exc:
            logger.warning(f"[morning_briefing] {session}: telegram alert error: {exc}")

    try:
        briefing_emailer.send_briefing_email(session=session)
    except Exception as exc:
        logger.warning(f"[morning_briefing] {session}: emailer error: {exc}")

    try:
        _send_briefing_summary_telegram(session, results)
    except Exception as exc:
        logger.warning(f"[morning_briefing] {session}: Telegram summary error: {exc}")


def _retry_worker(session: str, initial_results: Dict[str, Dict[str, Any]]) -> None:
    """Background retry loop — does not block the scheduler."""
    results = dict(initial_results)
    for attempt_idx, delay_min in enumerate(BRIEFING_RETRY_DELAYS_MINUTES, start=1):
        failed = [s for s, r in results.items() if not r.get("success")]
        if not failed:
            break
        logger.warning(
            "[morning_briefing] %s: %d pair(s) failed (%s) — waiting %d min "
            "before retry %d/%d (background thread)",
            session, len(failed), ",".join(failed), delay_min,
            attempt_idx, len(BRIEFING_RETRY_DELAYS_MINUTES),
        )
        time.sleep(delay_min * 60)
        logger.info(
            "[morning_briefing] %s: retry %d/%d starting for %s (background)",
            session, attempt_idx, len(BRIEFING_RETRY_DELAYS_MINUTES), failed,
        )
        retry_results = _run_briefing_once(session, failed)
        results.update(retry_results)

    _finalise_briefing(session, results)


def _run_briefing(session: str) -> None:
    """Run briefing refresh for all active symbols. First pass runs inline;
    retries run in a background thread so subsequent scheduled sessions
    continue to fire on time.
    """
    today = _utc_now().strftime("%Y-%m-%d")
    if not _try_claim_session(session, today):
        logger.info("[morning_briefing] %s briefing already claimed — skipping duplicate", session)
        return
    symbols = sorted(_ACTIVE_SYMBOLS) if _ACTIVE_SYMBOLS else DEFAULT_SYMBOLS
    logger.info(
        f"[morning_briefing] {session} briefing starting for {symbols}"
    )

    # NY_Data: lightweight partial refresh — single-shot, fail-open, no retry
    # or finalise pipeline (the cached NY briefing remains authoritative if the
    # refresh fails). Do not confuse this with the full NY briefing.
    if session == "NY_Data":
        _run_news_context_refresh(symbols)
        return

    results = _run_briefing_once(session, symbols)

    failed = [s for s, r in results.items() if not r.get("success")]
    if failed:
        t = threading.Thread(
            target=_retry_worker,
            args=(session, results),
            name=f"briefing-retry-{session}",
            daemon=True,
        )
        t.start()
        logger.info(
            "[morning_briefing] %s: %d pair(s) failed first pass — backoff "
            "retries handed off to thread %s, scheduler continues",
            session, len(failed), t.name,
        )
    else:
        _finalise_briefing(session, results)

# ─────────────────────────────────────────────────────────────────────────────
# Background scheduler
# ─────────────────────────────────────────────────────────────────────────────

def _scheduler_loop() -> None:
    """
    Check every 60s whether a session briefing is due.
    Fires within the first SESSION_WINDOW_MINUTES minutes of the scheduled hour.
    """
    logger.info("[morning_briefing] Scheduler thread started")

    while not _stop_event.is_set():
        try:
            now   = _utc_now()
            today = now.strftime("%Y-%m-%d")

            # Skip the entire tick on weekends — covers v4 and v5 fire
            # paths below in a single check. FX closed Sat all day +
            # Sun before 21:00 UTC; nothing in the active schedule
            # falls in the Sunday 21:00-23:59 window today.
            if _is_fx_market_closed(now):
                _stop_event.wait(60)
                continue

            active_sessions = _get_sessions(now)

            # Log active scheduler thread count every iteration for diagnostics.
            # Match the scheduler's exact thread name only — substring match used
            # to false-positive on transient catch-up workers (MorningBriefingCatchup*)
            # which legitimately stay alive for the duration of multi-symbol API calls.
            sched_threads = [t for t in threading.enumerate() if t.name == "MorningBriefing"]
            sched_count = len(sched_threads)
            logger.debug(
                f"[morning_briefing] Scheduler tick {now.strftime('%H:%M:%S')} UTC — "
                f"{sched_count} scheduler thread(s) active: {[t.name for t in sched_threads]}"
            )
            if sched_count > 1:
                logger.warning(
                    f"[morning_briefing] DUPLICATE SCHEDULER DETECTED: {sched_count} threads active: "
                    f"{[t.name for t in sched_threads]} — only one should exist"
                )

            for session_hour, session_minute, session_name in active_sessions:
                # Check if we're within SESSION_WINDOW_MINUTES of the scheduled time
                sched_mins = session_hour * 60 + session_minute
                now_mins = now.hour * 60 + now.minute
                elapsed = now_mins - sched_mins
                if elapsed < 0 or elapsed >= SESSION_WINDOW_MINUTES:
                    continue

                session_key = f"{session_name}_{today}"
                with _BRIEFING_LOCK:
                    if session_key in _BRIEFED_SESSIONS:
                        continue
                    # Belt-and-suspenders: check disk files too (guards against
                    # cross-process duplicates or stale in-memory state)
                    if any(_briefing_path(s, today, session_name).exists() for s in DEFAULT_SYMBOLS):
                        logger.info(
                            f"[morning_briefing] {session_key} already has disk files — "
                            f"marking done without re-running"
                        )
                        _BRIEFED_SESSIONS[session_key] = today
                        continue
                    # Mark before running so a slow API call doesn't trigger a second run
                    _BRIEFED_SESSIONS[session_key] = today
                logger.info(
                    f"[morning_briefing] Firing {session_name} briefing "
                    f"(elapsed={elapsed}m, threads={sched_count})"
                )
                try:
                    _run_briefing(session_name)
                except Exception as exc:
                    logger.warning(
                        f"[morning_briefing] {session_name} briefing run failed: {exc}",
                        exc_info=True,
                    )

            # ── v5 (briefing.v5_pia) parallel fires ──────────────────────────
            # Runs alongside v4 — separate dedup map, separate output dir.
            # Disable via BRIEFING_V5_ENABLED=0.
            try:
                from briefing.v5_pia.config import BRIEFING_V5_ENABLED as _V5_ENABLED
            except Exception:
                _V5_ENABLED = False
            if _V5_ENABLED:
                for s_hour, s_min, s_name in _SESSIONS_V5:
                    sched_mins_v5 = s_hour * 60 + s_min
                    elapsed_v5 = now_mins - sched_mins_v5
                    if elapsed_v5 < 0 or elapsed_v5 >= SESSION_WINDOW_MINUTES:
                        continue
                    v5_key = f"v5:{s_name}_{today}"
                    with _BRIEFING_V5_LOCK:
                        if v5_key in _BRIEFED_SESSIONS_V5:
                            continue
                        _BRIEFED_SESSIONS_V5[v5_key] = today
                    logger.info(
                        f"[morning_briefing.v5] Firing {s_name} v5 briefing "
                        f"(elapsed={elapsed_v5}m)"
                    )
                    try:
                        from briefing.v5_pia.orchestrator import generate_v5_for_session
                        generate_v5_for_session(s_name)
                    except Exception as exc:
                        logger.warning(
                            f"[morning_briefing.v5] {s_name} v5 fire failed: {exc}",
                            exc_info=True,
                        )

            # ── PIA_FIRST (pia_first_briefing.py) parallel fires ─────────
            # Single daily fire at 05:30 UTC. Disabled by default on this
            # droplet; flipped on by the AutoBot-PIA droplet's .env.
            _pia_first_enabled = (
                (os.getenv("PIA_FIRST_ENABLED", "0") or "0").strip() == "1"
            )
            if _pia_first_enabled:
                for s_hour, s_min, s_name in _SESSIONS_PIA_FIRST:
                    sched_mins_pf = s_hour * 60 + s_min
                    elapsed_pf = now_mins - sched_mins_pf
                    if elapsed_pf < 0 or elapsed_pf >= SESSION_WINDOW_MINUTES:
                        continue
                    pf_key = f"pia_first:{s_name}_{today}"
                    with _BRIEFING_PIA_FIRST_LOCK:
                        if pf_key in _BRIEFED_SESSIONS_PIA_FIRST:
                            continue
                        _BRIEFED_SESSIONS_PIA_FIRST[pf_key] = today
                    logger.info(
                        f"[morning_briefing.pia_first] Firing {s_name} "
                        f"PIA_FIRST briefing (elapsed={elapsed_pf}m)"
                    )
                    try:
                        from pia_first_briefing import generate_pia_first_for_session
                        generate_pia_first_for_session()
                    except Exception as exc:
                        logger.warning(
                            f"[morning_briefing.pia_first] {s_name} fire failed: {exc}",
                            exc_info=True,
                        )
            else:
                # Log-once-per-process so the operator can see the system is
                # wired but inactive. The scheduler loop ticks every 60s; we
                # only want a single info line at first iteration.
                if not getattr(_scheduler_loop, "_pia_first_disabled_logged", False):
                    logger.info("[pia_first] disabled by env flag")
                    _scheduler_loop._pia_first_disabled_logged = True  # type: ignore[attr-defined]

        except Exception as exc:
            logger.warning(f"[morning_briefing] scheduler loop error: {exc}")

        _stop_event.wait(60)

    _release_scheduler_lock()
    logger.info("[morning_briefing] Scheduler thread stopped")

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def update_htf_snapshot(symbol: str, snapshot: Dict[str, Any]) -> None:
    """
    Keep the HTF snapshot store current.
    Call from sentinel._on_5m_close() after each snapshot update.
    """
    if not snapshot:
        return
    sym = str(symbol).upper()
    _HTF_SNAPSHOTS[sym] = snapshot
    _ACTIVE_SYMBOLS.add(sym)


def get_briefing(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Return the current in-memory briefing for a symbol, or None if unavailable.
    Thread-safe read — no lock needed for dict lookup.
    """
    return _BRIEFINGS.get(str(symbol).upper())


def start(tf_ctx: Any, builder: Any) -> None:
    """
    Initialise the module and start the background scheduler.

    Parameters
    ----------
    tf_ctx  : TimeframeContext instance from sentinel._TF_CTX
    builder : CandleBuilder5M instance from candle_builder.get_builder()
    """
    global _TF_CTX, _BUILDER, SESSIONS

    _TF_CTX  = tf_ctx
    _BUILDER = builder

    if not BRIEFING_SCHEDULER_ENABLED:
        logger.info("[morning_briefing] BRIEFING_SCHEDULER_ENABLED=0 — scheduler disabled on this instance")
        return

    if not _acquire_scheduler_lock():
        return

    # Refresh module-level SESSIONS for current BST/GMT state
    SESSIONS = _get_sessions()
    tz_mode = "BST" if _is_bst(_utc_now()) else "GMT"

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Clean up stale session locks and pre-mark today's from existing lock files
    today = _utc_now().strftime("%Y-%m-%d")
    _cleanup_old_session_locks(today)
    for _sh, _sm, _sname in SESSIONS:
        _skey = f"{_sname}_{today}"
        if _session_lock_path(_sname, today).exists():
            _BRIEFED_SESSIONS[_skey] = today
            logger.info("[morning_briefing] Pre-marked %s from existing session lock", _skey)

    if not ANTHROPIC_API_KEY:
        logger.warning(
            "[morning_briefing] ANTHROPIC_API_KEY not set. Briefings will be skipped "
            "and the bias gate will block all trades (fail-closed). "
            "Set ANTHROPIC_API_KEY in .env to enable."
        )

    # Load any briefings already written to disk today (bot restart mid-day)
    # AND mark completed sessions in _BRIEFED_SESSIONS so the scheduler
    # doesn't re-fire a briefing that already ran before the restart.
    today = _utc_now().strftime("%Y-%m-%d")
    for sym in DEFAULT_SYMBOLS:
        existing = _load_latest_briefing_for_today(sym)
        if existing is not None:
            _apply_avoid_before_fallback(existing)
            with _LOCK:
                _BRIEFINGS[sym] = existing
    for _sh, _sm, _sname in SESSIONS:
        _skey = f"{_sname}_{today}"
        if _skey not in _BRIEFED_SESSIONS:
            if any(_briefing_path(s, today, _sname).exists() for s in DEFAULT_SYMBOLS):
                _BRIEFED_SESSIONS[_skey] = today
                logger.info(f"[morning_briefing] Pre-marked {_skey} from existing disk files")

    # Stale-lock recovery: per-pair. If a session lock exists for today but a
    # given pair's briefing file is missing/empty, retry that pair-session
    # directly (bypasses the 5-min window gate). Handles the case where the
    # scheduler exhausted retries but a subsequent attempt could succeed (e.g.
    # after a network blip or API_TIMEOUT bump).
    _now = _utc_now()
    for _sh, _sm, _sname in SESSIONS:
        _lock_path = _session_lock_path(_sname, today)
        if not _lock_path.exists():
            continue
        _scheduled = _now.replace(hour=_sh, minute=_sm, second=0, microsecond=0)
        _age_hours = (_now - _scheduled).total_seconds() / 3600.0
        for _sym in DEFAULT_SYMBOLS:
            _bpath = _briefing_path(_sym, today, _sname)
            _missing = not _bpath.exists() or _bpath.stat().st_size == 0
            if not _missing:
                continue
            if _age_hours > 4.0:
                logger.info(
                    "[BRIEFING-RECOVERY] %s %s skipped — session scheduled "
                    "%.1fh ago, too stale to retry",
                    _sym, _sname, _age_hours,
                )
                continue
            logger.warning(
                "[BRIEFING-RECOVERY] %s %s lock exists but file missing — "
                "clearing lock and retrying",
                _sym, _sname,
            )
            try:
                _lock_path.unlink()
            except OSError:
                pass
            _BRIEFED_SESSIONS.pop(f"{_sname}_{today}", None)
            try:
                _recovered = _refresh_symbol(_sym, _sname)
                if _recovered is not None:
                    logger.info(
                        "[BRIEFING-RECOVERY] %s %s retry succeeded", _sym, _sname,
                    )
                else:
                    logger.warning(
                        "[BRIEFING-RECOVERY] %s %s retry failed — trades will "
                        "remain blocked until next scheduled session",
                        _sym, _sname,
                    )
            except Exception as _rec_err:
                logger.warning(
                    "[BRIEFING-RECOVERY] %s %s retry raised: %s",
                    _sym, _sname, _rec_err,
                )
            # Re-claim the lock so the scheduler doesn't re-fire the whole session.
            try:
                _try_claim_session(_sname, today)
            except Exception:
                pass

    # Start scheduler thread
    t = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
        name="MorningBriefing",
    )
    t.start()

    session_str = ", ".join(f"{h:02d}:{m:02d} ({s})" for h, m, s in SESSIONS)
    logger.info(
        f"[morning_briefing] {tz_mode} active — "
        + " | ".join(f"{s} briefing at {h:02d}:{m:02d} UTC" for h, m, s in SESSIONS)
    )
    logger.info(
        f"[morning_briefing] Started — timezone: {tz_mode} — sessions (UTC): {session_str}"
    )

    # Catch-up: if a session briefing hasn't fired yet and we're past its time, fire now.
    # Rapid-restart guard: if any briefing for today was written in the last 30
    # minutes, skip the entire catch-up block — operational deploy/restart cycles
    # shouldn't reflexively refresh trading thesis state on top of a fresh fire.
    try:
        now = _utc_now()
        today = now.strftime("%Y-%m-%d")

        # Weekend gate: a deploy on Saturday or Sunday-before-21:00 UTC
        # must not trigger any catch-up fire — markets are closed.
        if _is_fx_market_closed(now):
            logger.info("[morning_briefing] Catch-up: weekend market closure — skipping all sessions")
            return

        _CATCHUP_RECENT_FIRE_GUARD_MINS = 30
        _recent_age_mins: Optional[float] = None
        try:
            for _p in LOG_DIR.glob(f"briefing_*_{today}_*.json"):
                try:
                    _age_m = (now.timestamp() - _p.stat().st_mtime) / 60.0
                except OSError:
                    continue
                if _recent_age_mins is None or _age_m < _recent_age_mins:
                    _recent_age_mins = _age_m
        except Exception:
            pass
        if _recent_age_mins is not None and _recent_age_mins < _CATCHUP_RECENT_FIRE_GUARD_MINS:
            logger.info(
                "[morning_briefing] Catch-up: skipping all sessions — most recent "
                "briefing fired %.1fm ago (< %dm rapid-restart guard)",
                _recent_age_mins, _CATCHUP_RECENT_FIRE_GUARD_MINS,
            )
            return

        now_mins = now.hour * 60 + now.minute

        # Catch-up windows are derived from the active session schedule.
        # Sessions removed from SESSIONS on 2026-04-28 (London_Open,
        # Mid-session, NY_Mid) had their catch-up blocks deleted on
        # 2026-05-06 — they were vestigial and fired surprise emails on
        # every restart inside the legacy windows.
        _london_mins = next((h * 60 + m for h, m, s in SESSIONS if s == "London"), 390)

        # Check London catch-up (scheduled time – 12:00 UTC)
        london_key = f"London_{today}"
        with _BRIEFING_LOCK:
            london_already_done = london_key in _BRIEFED_SESSIONS
        if _london_mins <= now_mins < 720 and not london_already_done:
            any_exists = any(
                _briefing_path(sym, today, "London").exists()
                for sym in DEFAULT_SYMBOLS
            )
            if not any_exists:
                with _BRIEFING_LOCK:
                    if london_key in _BRIEFED_SESSIONS:
                        logger.info("[morning_briefing] Catch-up: London already claimed by scheduler, skipping")
                    else:
                        _BRIEFED_SESSIONS[london_key] = today
                        logger.info("[morning_briefing] Catch-up: London briefing missing, firing now")
                        threading.Thread(
                            target=_run_briefing,
                            args=("London",),
                            daemon=True,
                            name="MorningBriefingCatchup",
                        ).start()
            else:
                logger.info("[morning_briefing] Catch-up: London briefing files exist on disk, skipping")
    except Exception as exc:
        logger.warning(f"[morning_briefing] Catch-up check failed: {exc}")
