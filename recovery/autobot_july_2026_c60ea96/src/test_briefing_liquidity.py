#!/usr/bin/env python3
"""
test_briefing_liquidity.py — Replay backtest for BriefingLiquidityStrategy.

Generates a London briefing for GBPUSD 2026-03-25 by calling the Anthropic
API with real D1/H1/5M candle data from that date, then replays 5M candles
through the arm-and-confirm state machine.

All candle fetches and the briefing are cached to disk on first successful
run. Subsequent runs load from cache and never hit the IG or Anthropic APIs.
Use --refresh to force fresh fetches.

Usage: python test_briefing_liquidity.py [--refresh]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

os.environ["BRIEFING_LIQUIDITY_OBSERVE"] = "0"
os.environ["BRIEFING_LIQUIDITY_ENABLED"] = "1"

import logging
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
load_dotenv()

import pandas as pd

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("AutoBot")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ig_auth import get_ig_session
from autobot import _normalize_hist_to_df
from briefing_liquidity import (
    BriefingLiquidityStrategy,
    LiquidityLevel,
    TriggerState,
)
from strategy_logic import StrategyDecision

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EPIC = "CS.D.GBPUSD.TODAY.IP"
SYMBOL = "GBPUSD"
PIP_SIZE = 0.0001

SESSION_START = datetime(2026, 3, 25, 6, 0, tzinfo=timezone.utc)
SESSION_END = datetime(2026, 3, 25, 18, 0, tzinfo=timezone.utc)

# Cache directory
CACHE_DIR = "/opt/tradingbot/cache"
CACHE_PREFIX = f"test_candles_{SYMBOL}_2026-03-25"
BRIEFING_CACHE = f"/opt/tradingbot/logs/briefing_{SYMBOL}_2026-03-25_London_REPLAY.json"

# Anthropic API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-5"

# Reuse morning_briefing prompt constants
SYSTEM_PROMPT = (
    "You are a professional FX market analyst with deep expertise in technical analysis, "
    "price action, liquidity theory, and session dynamics. "
    "You analyse markets top-down: Daily structure first, then H4, then H1, then 5M execution frame. "
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
    "bias_reasoning": "specific explanation referencing actual price levels and structure",
    "session_expectation": "TREND|LIQUIDITY_HUNT|RANGE",
    "expectation_reasoning": "specific explanation referencing session dynamics",
    "key_levels": {
        "resistance": ["float", "float"],
        "support": ["float", "float"]
    },
    "liquidity_pools": {
        "buy_side": ["float"],
        "sell_side": ["float"]
    },
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
            "rank": "int (1=highest probability)",
            "label": "string",
            "probability": "0.0-1.0",
            "confidence": "HIGH|MEDIUM|LOW",
            "bias": "LONG|SHORT",
            "entry_trigger": "string",
            "entry_zone": ["float", "float"],
            "stop_loss": "float",
            "targets": ["float", "float"],
            "risk_reward": "float",
            "invalidation": "string",
            "notes": "string"
        }
    ],
    "plan_summary": "string",
    "news_risk": "HIGH|MEDIUM|LOW|NONE",
    "news_events": [],
    "signal_filter": {
        "allow_buys": "true|false",
        "allow_sells": "true|false",
        "notes": "string"
    }
}


# ---------------------------------------------------------------------------
# IG data fetching
# ---------------------------------------------------------------------------

def fetch_candles_by_date_range(ig, epic: str, resolution: str,
                                start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """Fetch historical candles from IG REST API for a specific date range."""
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    print(f"  Fetching {resolution} for {epic}  {start_str} -> {end_str} ...")
    hist = ig.fetch_historical_prices_by_epic_and_date_range(
        epic, resolution, start_str, end_str
    )
    df = _normalize_hist_to_df(hist)
    if df is None or df.empty:
        print(f"  ERROR: No data returned for {resolution} date range")
        sys.exit(1)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    print(f"  Got {len(df)} candles: {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]}")
    return df


def _cache_path(label: str) -> str:
    """Return the cache file path for a given candle label (e.g. '5m', 'd1')."""
    return os.path.join(CACHE_DIR, f"{CACHE_PREFIX}_{label}.json")


def _save_df_cache(df: pd.DataFrame, label: str) -> None:
    """Save a DataFrame to JSON cache."""
    path = _cache_path(label)
    records = []
    for _, row in df.iterrows():
        rec = {
            "timestamp": str(row["timestamp"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        records.append(rec)
    with open(path, "w") as f:
        json.dump(records, f)
    print(f"  Cached {len(records)} candles -> {path}")


def _load_df_cache(label: str) -> pd.DataFrame | None:
    """Load a DataFrame from JSON cache, or return None if missing."""
    path = _cache_path(label)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        records = json.load(f)
    if not records:
        return None
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    print(f"  Loaded {len(df)} candles from cache: {path}")
    return df


def fetch_or_cache(ig, epic: str, resolution: str,
                   start_dt: datetime, end_dt: datetime,
                   label: str, refresh: bool) -> pd.DataFrame:
    """Load candles from cache, or fetch from IG and cache the result."""
    if not refresh:
        cached = _load_df_cache(label)
        if cached is not None and len(cached) > 0:
            return cached
    if ig is None:
        print(f"  ERROR: No cache for '{label}' and IG session not available")
        sys.exit(1)
    df = fetch_candles_by_date_range(ig, epic, resolution, start_dt, end_dt)
    _save_df_cache(df, label)
    return df


def fmt_candles(df: pd.DataFrame) -> list[dict]:
    """Format DataFrame candles for the briefing prompt (same as morning_briefing._fmt_candles)."""
    out = []
    for _, row in df.iterrows():
        ts = row["timestamp"]
        if hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        out.append({
            "t": str(ts),
            "o": round(float(row["open"]), 5),
            "h": round(float(row["high"]), 5),
            "l": round(float(row["low"]), 5),
            "c": round(float(row["close"]), 5),
        })
    return out


# ---------------------------------------------------------------------------
# Briefing generation via Anthropic API
# ---------------------------------------------------------------------------

def generate_briefing(
    symbol: str,
    session: str,
    current_price: float,
    briefing_date: str,
    briefing_time_utc: str,
    d1_candles: list[dict],
    h1_candles: list[dict],
    h4_candles: list[dict],
) -> dict:
    """Call Anthropic API to generate a fresh briefing for a historical date."""
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    # Compute H1 momentum summary from candle data
    h1_momentum = "insufficient data"
    if h1_candles and len(h1_candles) >= 2:
        tail = h1_candles[-6:] if len(h1_candles) >= 6 else h1_candles
        closes = [c["c"] for c in tail]
        consec = 0
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] > closes[i - 1]:
                if consec <= 0 and consec != 0:
                    break
                consec += 1
            elif closes[i] < closes[i - 1]:
                if consec >= 0 and consec != 0:
                    break
                consec -= 1
            else:
                break
        total = round(closes[-1] - closes[0], 1)
        direction = "higher" if consec > 0 else "lower" if consec < 0 else "flat"
        trend = "short-term uptrend" if consec > 0 else "short-term downtrend" if consec < 0 else "no clear trend"
        h1_momentum = (
            f"{abs(consec)} consecutive {direction} closes out of last {len(closes)} H1 candles, "
            f"{'+' if total > 0 else ''}{total} points over {len(closes)} hours, {trend}"
        )

    pkg = {
        "symbol": symbol,
        "current_price": current_price,
        "session": session,
        "briefing_date": briefing_date,
        "briefing_time_utc": briefing_time_utc,
        "d1_candles": d1_candles,
        "h4_candles": h4_candles,
        "h1_candles": h1_candles,
        "ema_5m": {},
        "ema_h1": {},
        "htf_bias": {"h1": "NEUTRAL", "h4": "NEUTRAL", "d1": "NEUTRAL"},
        "macd_h1_hist": None,
        "rsi_5m": None,
        "h1_momentum_summary": h1_momentum,
        "ema_alignment": "no H1 EMA data available",
        "news_events": [],
        "recent_signals": [],
    }

    print(f"  H1 momentum: {h1_momentum}")

    user_message = (
        f"Produce a pre-session briefing for {symbol} at the {session} open.\n\n"
        f"Current price: {current_price}\n"
        f"Today's date: {briefing_date} UTC\n"
        f"Current UTC time: {briefing_time_utc}\n\n"
        f"=== MARKET DATA ===\n"
        f"{json.dumps(pkg, indent=2, default=str)}\n\n"
        f"=== ANALYSIS INSTRUCTIONS ===\n"
        f"1. DAILY STRUCTURE: Identify the dominant multi-day trend, key swing highs/lows, "
        f"where price has come from and where it is going. Is price in a pullback, "
        f"continuation, or at a major level?\n\n"
        f"2. H4 CONTEXT: What is the intermediate trend? Where are the H4 liquidity pools "
        f"(equal highs/lows, swing points where stops cluster)? Is there a compression or expansion phase?\n\n"
        f"3. H1 STRUCTURE (CRITICAL): The most recent 6 H1 candles are the most important "
        f"signal for session direction. Give them MORE weight than the broader D1 structure "
        f"when assessing session_bias. Look at: consecutive higher/lower closes, total pip "
        f"movement, EMA alignment. See the h1_momentum_summary and ema_alignment fields "
        f"in the data for a pre-computed read.\n\n"
        f"4. SESSION BIAS: What is the most likely direction for THIS {session} session "
        f"based on the recent H1 structure and momentum? This can differ from daily_bias. "
        f"A range-bound daily structure with clear H1 downtrend heading into London = "
        f"session_bias BEARISH even if daily_bias is NEUTRAL. Be decisive — if H1 momentum "
        f"is clearly directional, session_bias should reflect that.\n\n"
        f"5. SESSION EXPECTATION: Given the session opening ({session}), what typically happens? "
        f"Asian: accumulation/range. London: breakout or liquidity hunt then reversal. "
        f"NY: continuation or reversal of London move. "
        f"Which is most likely today given the structure?\n\n"
        f"6. KEY LEVELS: Identify the most important levels only — not every swing. "
        f"Focus on: recent swing highs/lows with clustered stops, round numbers, "
        f"previous session highs/lows, EMA confluences.\n\n"
        f"7. NO-TRADE ZONES: Identify price ranges where the risk/reward is poor — "
        f"mid-range locations, areas of chop, between major levels with no clear edge.\n\n"
        f"8. LIQUIDITY POOLS: Identify where buy-side and sell-side liquidity is resting — "
        f"above equal highs, below equal lows, above/below obvious swing points. "
        f"Be specific about price levels.\n\n"
        f"9. SCENARIOS: Produce 2-3 specific scenarios with realistic probabilities. "
        f"Each scenario needs a specific trigger (not vague), a target level, and a clear invalidation.\n\n"
        f"10. NEWS RISK: Assess impact of today's news events on this pair specifically.\n\n"
        f"11. SIGNAL FILTER: Based on your analysis, should the bot be buying, selling, or both today?\n\n"
        f"12. TRADING PLANS: Produce 2-3 ranked trading plans in order of probability highest first. "
        f"Each plan must have:\n"
        f"- A specific entry trigger (not vague — e.g. '5M close above 13380 with RSI > 60')\n"
        f"- A specific entry zone (price range to enter)\n"
        f"- A hard stop loss level\n"
        f"- Two targets (T1 partial, T2 runner)\n"
        f"- Risk/reward ratio\n"
        f"- A clear invalidation condition\n"
        f"- Confidence level: HIGH (>65% probability), MEDIUM (45-65%), LOW (<45%)\n"
        f"Plans must be ranked — rank 1 is your highest conviction idea for this session.\n"
        f"Probabilities are independent scenarios and do not need to sum to 100%.\n"
        f"Include a one-sentence plan_summary of your single best trade idea.\n\n"
        f"=== REQUIRED JSON RESPONSE ===\n"
        f"{json.dumps(RESPONSE_SCHEMA, indent=2)}\n\n"
        f"Rules:\n"
        f"- daily_bias must be BULLISH, BEARISH, or NEUTRAL (multi-day trend)\n"
        f"- session_bias must be BULLISH, BEARISH, or NEUTRAL (THIS session's likely direction based on H1 momentum)\n"
        f"- session_bias can differ from daily_bias — a NEUTRAL daily range with clear H1 downtrend = session_bias BEARISH\n"
        f"- signal_filter.allow_buys must be false when session_bias is BEARISH\n"
        f"- signal_filter.allow_sells must be false when session_bias is BULLISH\n"
        f"- signal_filter.allow_buys and allow_sells must both be true when session_bias is NEUTRAL\n"
        f"- briefing_time must be the current UTC time in ISO8601 format\n"
        f"- bias_reasoning and expectation_reasoning must be specific — reference actual price levels\n"
        f"- trading_plans must be ranked 1 to N, rank 1 = highest probability\n"
        f"- entry_trigger must be specific and actionable\n"
        f"- Return valid JSON only — no prose, no markdown fences"
    )

    print(f"\n  Calling Anthropic API ({ANTHROPIC_MODEL}) ...")
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=120,
    )

    if resp.status_code != 200:
        print(f"  ERROR: API returned {resp.status_code}: {resp.text[:500]}")
        sys.exit(1)

    body = resp.json()
    text = body["content"][0]["text"].strip()

    # Strip accidental markdown fencing
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    briefing = json.loads(text)

    # Sanity-check required keys
    required = {"symbol", "daily_bias", "signal_filter"}
    missing = required - set(briefing.keys())
    if missing:
        print(f"  ERROR: Response missing keys {missing}")
        print(f"  Raw: {text[:500]}")
        sys.exit(1)

    print(f"  Briefing generated OK")
    return briefing


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_levels(levels: list[LiquidityLevel]) -> None:
    print("\n" + "=" * 80)
    print("BRIEFING-DERIVED LIQUIDITY LEVELS")
    print("=" * 80)
    print(f"{'Price':>12}  {'Type':>12}  {'Source':<25}")
    print("-" * 80)
    for lv in sorted(levels, key=lambda x: x.price, reverse=True):
        print(f"{lv.price:>12.1f}  {lv.level_type:>12}  {lv.source:<25}")
    print("=" * 80 + "\n")


def print_trigger_states(strategy: BriefingLiquidityStrategy, epic: str) -> None:
    slots = strategy._triggers.get(epic, {})
    candle_idx = strategy._candle_index.get(epic, 0)
    for lvl_price, slot in sorted(slots.items(), reverse=True):
        if slot.state != TriggerState.WATCHING and not slot.consumed:
            armed_age = f" armed_for={candle_idx - slot.armed_at_candle}" if slot.armed_at_candle is not None else ""
            print(f"    [{slot.state.value:>10}] level={lvl_price:.1f} ({slot.level.source}) dir={slot.direction}{armed_age}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Replay backtest for BriefingLiquidityStrategy")
    parser.add_argument("--refresh", action="store_true",
                        help="Force fresh fetch from IG/Anthropic APIs (ignore cache)")
    args = parser.parse_args()
    refresh = args.refresh

    print("=" * 80)
    print("BRIEFING LIQUIDITY STRATEGY — REPLAY BACKTEST")
    print(f"Symbol: {SYMBOL}  Epic: {EPIC}")
    print(f"Date: 2026-03-25  Session: London 06:00-18:00 UTC")
    print(f"Cache: {'REFRESH (forced)' if refresh else 'enabled'}")
    print("=" * 80)

    # ------------------------------------------------------------------
    # 1. Load candle data (from cache or IG API)
    # ------------------------------------------------------------------
    # Check if all caches exist so we can skip IG login entirely
    all_cached = (not refresh
                  and all(os.path.exists(_cache_path(l))
                          for l in ("d1", "h1", "h4", "5m"))
                  and os.path.exists(BRIEFING_CACHE))

    if all_cached:
        print("\n--- Loading all candle data from cache (no IG API needed) ---")
        ig = None
    else:
        print("\n--- Connecting to IG API ---")
        ig, headers, account_id = get_ig_session()
        print(f"  Connected. Account: {account_id}")

    print("\n--- Candle data for briefing context ---")

    d1_start = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc)
    d1_end = datetime(2026, 3, 25, 6, 0, tzinfo=timezone.utc)
    df_d1 = fetch_or_cache(ig, EPIC, "DAY", d1_start, d1_end, "d1", refresh)

    h1_start = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    h1_end = datetime(2026, 3, 25, 6, 0, tzinfo=timezone.utc)
    df_h1 = fetch_or_cache(ig, EPIC, "HOUR", h1_start, h1_end, "h1", refresh)

    h4_start = datetime(2026, 3, 18, 0, 0, tzinfo=timezone.utc)
    h4_end = datetime(2026, 3, 25, 6, 0, tzinfo=timezone.utc)
    try:
        df_h4 = fetch_or_cache(ig, EPIC, "HOUR_4", h4_start, h4_end, "h4", refresh)
    except Exception:
        print("  H4 resolution not available, using H1 data as fallback")
        df_h4 = fetch_or_cache(ig, EPIC, "HOUR", h4_start, h4_end, "h4", refresh)

    print("\n--- 5M data (extended for simulation) ---")
    sim_start = datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc)
    sim_end = datetime(2026, 3, 26, 23, 59, tzinfo=timezone.utc)
    df_5m_all = fetch_or_cache(ig, EPIC, "MINUTE_5", sim_start, sim_end, "5m", refresh)

    # ------------------------------------------------------------------
    # 2. Load or generate briefing
    # ------------------------------------------------------------------
    df_session = df_5m_all[
        (df_5m_all["timestamp"] >= SESSION_START) &
        (df_5m_all["timestamp"] <= SESSION_END)
    ].reset_index(drop=True)

    if df_session.empty:
        print(f"\nERROR: No 5M candles in session window")
        sys.exit(1)

    open_price = float(df_session.iloc[0]["open"])
    print(f"\n  Session open price: {open_price:.1f}")

    out_path = BRIEFING_CACHE
    if not refresh and os.path.exists(out_path):
        print(f"\n--- Loading briefing from cache: {out_path} ---")
        with open(out_path) as f:
            briefing = json.load(f)
    else:
        print("\n--- Generating fresh briefing via Anthropic API ---")
        briefing = generate_briefing(
            symbol=SYMBOL,
            session="London",
            current_price=open_price,
            briefing_date="2026-03-25",
            briefing_time_utc="2026-03-25T07:00:00Z",
            d1_candles=fmt_candles(df_d1),
            h1_candles=fmt_candles(df_h1),
            h4_candles=fmt_candles(df_h4),
        )
        with open(out_path, "w") as f:
            json.dump(briefing, f, indent=2, default=str)
        print(f"  Saved to: {out_path}")

    # ------------------------------------------------------------------
    # 3. Report briefing output
    # ------------------------------------------------------------------
    daily_bias = briefing.get("daily_bias", "?")
    session_bias = briefing.get("session_bias", "?")
    conf = briefing.get("bias_confidence", "?")
    kl = briefing.get("key_levels", {})
    lp = briefing.get("liquidity_pools", {})

    print(f"\n--- BRIEFING RESULT ---")
    print(f"  Daily bias:   {daily_bias} (confidence={conf})")
    print(f"  Session bias: {session_bias}")
    print(f"  Session expectation: {briefing.get('session_expectation', '?')}")
    print(f"  Bias reasoning: {briefing.get('bias_reasoning', '?')[:120]}...")
    print(f"  key_levels.resistance: {kl.get('resistance', [])}")
    print(f"  key_levels.support:    {kl.get('support', [])}")
    print(f"  liquidity_pools.buy:   {lp.get('buy_side', [])}")
    print(f"  liquidity_pools.sell:  {lp.get('sell_side', [])}")
    print(f"  Plan summary: {briefing.get('plan_summary', '?')[:120]}")

    # The strategy uses session_bias as primary, daily_bias as confirmation.
    # Determine effective bias matching _get_bias() logic for test display.
    effective_bias = None
    if session_bias in ("BULLISH", "BEARISH"):
        if daily_bias in ("BULLISH", "BEARISH") and daily_bias != session_bias:
            effective_bias = None  # conflict
        else:
            effective_bias = session_bias
    elif daily_bias in ("BULLISH", "BEARISH"):
        effective_bias = daily_bias
    original_bias = effective_bias
    if effective_bias not in ("BULLISH", "BEARISH"):
        print(f"\n  No tradeable bias — overriding session_bias to BEARISH for replay test")
        briefing["session_bias"] = "BEARISH"
        briefing["daily_bias"] = "BEARISH"
        effective_bias = "BEARISH"
    else:
        print(f"\n  Strategy will use effective bias={effective_bias} (no override needed)")

    # ------------------------------------------------------------------
    # 4. Initialize strategy and extract levels
    # ------------------------------------------------------------------
    strategy = BriefingLiquidityStrategy()
    df_pre = df_5m_all[df_5m_all["timestamp"] < SESSION_START].reset_index(drop=True)
    warmup_df = df_pre if len(df_pre) > 0 else df_session.iloc[:1]

    strategy.evaluate(
        symbol=SYMBOL, epic=EPIC, df_5m=warmup_df,
        pip_size=PIP_SIZE, mid_price=open_price, briefing=briefing,
    )
    levels = strategy._levels.get(EPIC, [])
    print_levels(levels)

    if not levels:
        print("ERROR: No levels extracted from briefing")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 5. Replay
    # ------------------------------------------------------------------
    print("=" * 80)
    print("REPLAY — Stepping through 5M candles")
    sig_dir = "SELL" if effective_bias == "BEARISH" else "BUY"
    print(f"  Effective bias: {effective_bias} -> all signals will be {sig_dir}")
    print("=" * 80)

    signals_fired = []

    for i in range(len(df_session)):
        row = df_session.iloc[i]
        candle_time = row["timestamp"]
        c_o = float(row["open"])
        c_h = float(row["high"])
        c_l = float(row["low"])
        c_c = float(row["close"])

        df_rolling = pd.concat([df_pre, df_session.iloc[:i + 1]], ignore_index=True)

        decision = strategy.evaluate(
            symbol=SYMBOL, epic=EPIC, df_5m=df_rolling,
            pip_size=PIP_SIZE, mid_price=c_c, briefing=briefing,
        )

        ts_str = candle_time.strftime("%H:%M")
        bar = f"  {ts_str}  O={c_o:.1f} H={c_h:.1f} L={c_l:.1f} C={c_c:.1f}"

        slots = strategy._triggers.get(EPIC, {})
        active_slots = [(p, s) for p, s in slots.items()
                        if s.state != TriggerState.WATCHING and not s.consumed]

        if decision.signal != "NONE":
            dbg = decision.debug
            print(f"\n{'*' * 80}")
            print(f"  >>> SIGNAL: {decision.signal} at {ts_str} UTC <<<")
            print(bar)
            print(f"  Entry: {decision.entry:.1f}")
            print(f"  Level: {dbg.get('level_price')} ({dbg.get('level_source')})")
            print(f"  SL:  {decision.sl:.1f} pips @ {dbg.get('sl_price', '?')} ({dbg.get('sl_source', '?')})")
            tp_plan = dbg.get("tp_plan", [])
            for i, t in enumerate(tp_plan, 1):
                print(f"  TP{i}: {t['pips']:.1f} pips @ {t['price']} ({t['source']})")
            print(f"{'*' * 80}\n")
            signals_fired.append((candle_time, decision))
        elif active_slots:
            print(bar)
            print_trigger_states(strategy, EPIC)
        else:
            print(bar)

    # ------------------------------------------------------------------
    # 6. Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("REPLAY SUMMARY")
    print("=" * 80)
    print(f"\n  API daily_bias: {daily_bias}  session_bias: {session_bias}  (confidence={conf})")
    if original_bias != effective_bias:
        print(f"  Override: session_bias -> {effective_bias} (for replay testing)")
    print(f"  Cooldown: {60} minutes between signals")
    print(f"  Key levels: {len(kl.get('resistance', []))} resistance, {len(kl.get('support', []))} support")
    print(f"  Liquidity pools: {len(lp.get('buy_side', []))} buy-side, {len(lp.get('sell_side', []))} sell-side")

    slots = strategy._triggers.get(EPIC, {})
    consumed = [(p, s) for p, s in slots.items() if s.consumed]
    still_touched = [(p, s) for p, s in slots.items()
                     if s.state == TriggerState.ARMED and not s.consumed]
    watching = [(p, s) for p, s in slots.items()
                if s.state == TriggerState.WATCHING and not s.consumed]

    print(f"\n  Level summary:")
    print(f"    Triggered (consumed): {len(consumed)}")
    for p, s in consumed:
        print(f"      {p:.1f} ({s.level.source}) -> {s.direction}")
    print(f"    Still armed:          {len(still_touched)}")
    print(f"    Never reached:        {len(watching)}")

    if signals_fired:
        print(f"\n  Total signals fired: {len(signals_fired)}")
        for ts, dec in signals_fired:
            dbg = dec.debug
            tp_plan = dbg.get("tp_plan", [])
            tp_str = " | ".join(f"TP{i+1}={t['pips']:.1f}@{t['price']}" for i, t in enumerate(tp_plan))
            print(f"    {ts.strftime('%H:%M')} UTC  {dec.signal} @ {dec.entry:.1f}"
                  f"  SL={dec.sl:.1f}@{dbg.get('sl_price', '?')}"
                  f"  level={dbg.get('level_price')} ({dbg.get('level_source')})"
                  f"  {tp_str}")
    else:
        print("\n  No signals fired.")

    print(f"\n  Briefing saved: {out_path}")

    # ------------------------------------------------------------------
    # 7. Trade outcome simulation
    # ------------------------------------------------------------------
    simulate_trade_outcomes(signals_fired, df_5m_all)

    print("\n" + "=" * 80)
    print("Done.")


# ---------------------------------------------------------------------------
# Trade outcome simulation
# ---------------------------------------------------------------------------

def simulate_trade_outcomes(
    signals_fired: list[tuple[datetime, StrategyDecision]],
    df_all: pd.DataFrame,
) -> None:
    """Step through 5m candles after each signal with trade manager logic.

    Exit conditions (checked in order each candle):
    1. SL hit (hard stop)
    2. TP1 hit (take profit)
    3. Profit protection trail exit:
       - Arm at LOCK_TRIGGER pips profit, floor = LOCK_FLOOR pips
       - Trail: best_pnl - TRAIL_OFFSET (never below LOCK_FLOOR)
       - Close when cur_pnl drops below dynamic floor

    No session-close cutoff — trades run until resolved or data runs out.
    Tracks max favourable excursion (MFE) to show how close price got to TP1.
    """
    PPP = 1  # points per pip — all IG spread-bet pairs are 1:1

    # Trade manager profit protection parameters (matching trade_manager.py)
    LOCK_TRIGGER = 20.0   # pips — arm profit lock
    LOCK_FLOOR = 10.0     # pips — minimum locked floor
    TRAIL_OFFSET = 10.0   # pips — trail offset from best

    if not signals_fired:
        print("\n  No signals to simulate.")
        return

    print("\n" + "=" * 80)
    print("TRADE OUTCOME SIMULATION  (trade manager: arm@20pip, trail offset=10, floor=10)")
    print("=" * 80)

    results = []

    for sig_time, dec in signals_fired:
        direction = dec.signal
        entry = dec.entry
        dbg = dec.debug
        tp_plan = dbg.get("tp_plan", [])

        # Absolute prices from debug
        sl_price = dbg.get("sl_price")
        tp1_price = tp_plan[0]["price"] if tp_plan else None

        # Fallback if debug prices missing
        if sl_price is None:
            sl_price = entry + dec.sl * PPP if direction == "SELL" else entry - dec.sl * PPP
        if tp1_price is None:
            tp1_price = entry - dec.tp * PPP if direction == "SELL" else entry + dec.tp * PPP

        # Get all candles from signal time onwards
        future = df_all[df_all["timestamp"] >= sig_time].reset_index(drop=True)

        outcome = None
        close_price = None
        close_time = None
        points_pnl = 0.0

        # Trade manager state
        best_pnl_pips = 0.0
        lock_armed = False
        best_price = entry  # best price in trade direction

        for _, row in future.iterrows():
            c_h = float(row["high"])
            c_l = float(row["low"])
            c_c = float(row["close"])
            c_ts = row["timestamp"]

            if direction == "SELL":
                best_price = min(best_price, c_l)
                # Check SL first (worst case within candle)
                if c_h >= sl_price:
                    outcome = "SL"
                    close_price = sl_price
                    close_time = c_ts
                    points_pnl = entry - sl_price
                    break
                # Check TP1
                if c_l <= tp1_price:
                    outcome = "TP1"
                    close_price = tp1_price
                    close_time = c_ts
                    points_pnl = entry - tp1_price
                    break
                # Trade manager: use candle close as proxy for tick-level pnl
                cur_pnl_pips = (entry - c_c) / PPP
                best_pnl_pips = max(best_pnl_pips, (entry - c_l) / PPP)
            else:
                best_price = max(best_price, c_h)
                # Check SL first
                if c_l <= sl_price:
                    outcome = "SL"
                    close_price = sl_price
                    close_time = c_ts
                    points_pnl = sl_price - entry
                    break
                # Check TP1
                if c_h >= tp1_price:
                    outcome = "TP1"
                    close_price = tp1_price
                    close_time = c_ts
                    points_pnl = tp1_price - entry
                    break
                # Trade manager: use candle close as proxy
                cur_pnl_pips = (c_c - entry) / PPP
                best_pnl_pips = max(best_pnl_pips, (c_h - entry) / PPP)

            # Profit protection logic
            if not lock_armed and best_pnl_pips >= LOCK_TRIGGER:
                lock_armed = True

            if lock_armed:
                dynamic_floor = max(LOCK_FLOOR, best_pnl_pips - TRAIL_OFFSET)
                if cur_pnl_pips < dynamic_floor:
                    outcome = "TRAIL"
                    close_price = c_c
                    close_time = c_ts
                    points_pnl = (entry - c_c) if direction == "SELL" else (c_c - entry)
                    break

        if outcome is None:
            last = future.iloc[-1]
            outcome = "STILL_OPEN"
            close_price = float(last["close"])
            close_time = last["timestamp"]
            points_pnl = (entry - close_price) if direction == "SELL" else (close_price - entry)

        # MFE: how far price moved in the trade direction
        mfe_points = abs(entry - best_price)
        mfe_pips = mfe_points / PPP
        # Distance from best price to TP1
        tp1_dist_from_best = abs(best_price - tp1_price)

        pip_pnl = points_pnl / PPP
        results.append((sig_time, direction, entry, sl_price, tp1_price,
                         outcome, close_price, close_time, points_pnl, pip_pnl))

        # Print per-trade details
        tp_plan_str = " → ".join(
            f"TP{i+1} {t['price']} ({t['source']})" for i, t in enumerate(tp_plan)
        )
        close_ts = close_time.strftime("%Y-%m-%d %H:%M") if close_time is not None else "?"
        trail_info = ""
        if outcome == "TRAIL":
            trail_info = f"  (lock armed, best={best_pnl_pips:.1f} floor={max(LOCK_FLOOR, best_pnl_pips - TRAIL_OFFSET):.1f})"
        print(f"\n  Trade {len(results)}:")
        print(f"    Entry time:  {sig_time.strftime('%H:%M')} UTC")
        print(f"    Direction:   {direction}")
        print(f"    Entry price: {entry:.1f}")
        print(f"    Level:       {dbg.get('level_price')} ({dbg.get('level_source')})")
        print(f"    SL:          {sl_price:.1f} ({dbg.get('sl_source', '?')})")
        print(f"    TP plan:     {tp_plan_str}")
        print(f"    Outcome:     {outcome}{trail_info} at {close_ts}")
        print(f"    Close price: {close_price:.1f}")
        print(f"    Points P&L:  {points_pnl:+.1f}")
        print(f"    Pip P&L:     {pip_pnl:+.1f}")
        print(f"    MFE:         {mfe_points:+.1f} pts ({mfe_pips:+.1f} pips) — best {best_price:.1f}"
              f", needed {tp1_dist_from_best:.1f} pts more for TP1")

    # Final summary
    total_points = sum(r[8] for r in results)
    total_pips = sum(r[9] for r in results)
    wins = sum(1 for r in results if r[8] > 0)
    losses = sum(1 for r in results if r[8] < 0)
    flat = sum(1 for r in results if r[8] == 0)

    print("\n" + "-" * 80)
    print("  SIMULATION SUMMARY  (trade manager: arm@20pip, trail offset=10, floor=10)")
    print("-" * 80)
    print(f"  Trades:       {len(results)}  (W:{wins} L:{losses} F:{flat})")
    print(f"  Total points: {total_points:+.1f}")
    print(f"  Total pips:   {total_pips:+.1f}")
    print(f"  @ £1/pip:     £{total_pips * 1:+.2f}")
    print(f"  @ £10/pip:    £{total_pips * 10:+.2f}")
    print("-" * 80)


if __name__ == "__main__":
    main()
