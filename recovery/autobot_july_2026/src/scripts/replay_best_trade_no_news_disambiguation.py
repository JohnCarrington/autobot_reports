#!/usr/bin/env python3
"""
Clean no-news disambiguation test for the best_trade prompt change.

Constructs a synthetic GBPUSD London package that:
  - has news_events = []
  - no upcoming-news pressure (calibrator, narrative, calendar all empty)
  - structural_state classifies as range-bound, no news_classification
  - inputs naturally suggest a single-thesis "buy support, target up" setup

Patches the five live-state pulls inside _build_user_message
(briefing_calibrator, _get_recent_prediction_accuracy,
briefing_narrative.get_today_narrative_text, structural_state.get_structural_state,
news_calendar.get_todays_events) to return clean values so today's CPI
state cannot bleed into the test.

Expected: best_trade.mode == UNCONDITIONAL on this single-thesis input.
If CONDITIONAL: prompt is over-correcting and needs tightening.

One API call (~$0.20).
"""
import json, os, sys, time, logging, requests
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv("/opt/tradingbot/.env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("noNewsDisambig")

import morning_briefing
from morning_briefing import (
    SYSTEM_PROMPT, ANTHROPIC_URL, ANTHROPIC_MODEL, BRIEFING_MAX_TOKENS,
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OUT = Path("/opt/tradingbot/data/briefings_replay_new_prompt")
OUT.mkdir(parents=True, exist_ok=True)


# Clean synthetic structural state — explicitly range-bound, no news
CLEAN_STRUCTURAL_STATE = {
    "symbol": "GBPUSD",
    "regime": "RANGE",
    "classification_reason": "Range_bound — no high-impact news within ±4h",
    "d1_trend": "BULL",
    "d1_score": 6,
    "h1_alignment": "BULL",
    "intraday_range_pips": 35,
    "news_classification": "NONE",
    "news_events_today": [],
    "news_events_within_4h": [],
}


def _patched_get_today_narrative_text(symbol):
    return ""  # No prior session narrative


def _patched_get_calibration_summary(symbol=None):
    return ""  # No calibration commentary


def _patched_get_recent_prediction_accuracy(sym, lookback_days=14):
    return None  # No accuracy block


def _patched_get_structural_state(sym):
    return CLEAN_STRUCTURAL_STATE


def _patched_get_todays_events(*args, **kwargs):
    return []  # No calendar events at all


def build_single_thesis_pkg():
    """Synthetic input that should make a competent LLM author 1-2 LONG
    London plans of similar shape (primary + backup, NOT branching)."""
    return {
        "symbol": "GBPUSD",
        "current_price": 13585.0,
        "session": "London",
        "briefing_date": "2026-05-12",
        "briefing_time_utc": "2026-05-12T05:30:00Z",
        # Clean H1 candles — slow drift up, no news shock
        "h1_candles": [
            {"time": "2026-05-11 09:00:00+00:00", "open": 13565.0, "high": 13573.0,
             "low": 13562.0, "close": 13571.0},
            {"time": "2026-05-11 10:00:00+00:00", "open": 13571.0, "high": 13580.0,
             "low": 13569.0, "close": 13578.0},
            {"time": "2026-05-11 11:00:00+00:00", "open": 13578.0, "high": 13585.0,
             "low": 13575.0, "close": 13582.0},
            {"time": "2026-05-11 12:00:00+00:00", "open": 13582.0, "high": 13588.0,
             "low": 13579.0, "close": 13586.0},
            {"time": "2026-05-11 13:00:00+00:00", "open": 13586.0, "high": 13591.0,
             "low": 13584.0, "close": 13588.0},
            {"time": "2026-05-11 14:00:00+00:00", "open": 13588.0, "high": 13593.0,
             "low": 13586.0, "close": 13590.0},
            {"time": "2026-05-11 15:00:00+00:00", "open": 13590.0, "high": 13594.0,
             "low": 13587.0, "close": 13589.0},
            {"time": "2026-05-11 16:00:00+00:00", "open": 13589.0, "high": 13592.0,
             "low": 13585.0, "close": 13587.0},
            {"time": "2026-05-12 00:00:00+00:00", "open": 13587.0, "high": 13590.0,
             "low": 13583.0, "close": 13585.0},
            {"time": "2026-05-12 01:00:00+00:00", "open": 13585.0, "high": 13588.0,
             "low": 13582.0, "close": 13585.0},
            {"time": "2026-05-12 02:00:00+00:00", "open": 13585.0, "high": 13587.0,
             "low": 13583.0, "close": 13585.0},
            {"time": "2026-05-12 03:00:00+00:00", "open": 13585.0, "high": 13588.0,
             "low": 13583.0, "close": 13586.0},
            {"time": "2026-05-12 04:00:00+00:00", "open": 13586.0, "high": 13588.0,
             "low": 13583.0, "close": 13585.0},
        ],
        "ema_5m": {"8": 13585.5, "13": 13585.0, "21": 13584.5, "50": 13583.0, "200": 13578.0},
        "ema_h1": {"8": 13586.0, "13": 13584.5, "21": 13582.5, "50": 13580.0, "200": 13568.0},
        "h1_ema_values": {"8": 13586.0, "13": 13584.5, "21": 13582.5, "50": 13580.0},
        "macd_h1_hist": 1.5,
        "h1_momentum_summary": "Slow steady drift higher over last 12h, BULL alignment",
        "ema_alignment": "BULL — EMAs fanned 8>13>21>50, price above all",
        "bb_upper": 13598.0,
        "bb_lower": 13572.0,
        "prev_day_high": 13594.0,
        "prev_day_low": 13578.0,
        "prev_day_close": 13588.0,
        "week_high": 13620.0,
        "week_low": 13560.0,
        "prev_week_high": 13635.0,
        "prev_week_low": 13540.0,
        "price_vs_h1_ema200_pips": 17.0,
        "price_vs_h1_ema50_pips": 5.0,
        "h1_ema_trend": "BULLISH",
        "atr_today_pips": 22.0,
        "atr_20day_avg_pips": 30.0,
        "volatility_regime": "LOW",
        "prev_session_bias": "BULLISH",
        "prev_session_actual_direction": "UP",
        "prev_session_pip_move": 8,
        "usd_proxy_bias": "USD_NEUTRAL",
        "usd_proxy_pips": 1.0,
        "usd_proxy_method": "basket",
        "usd_proxy_contributors": ["EURUSD", "USDJPY", "USDCAD"],
        "usd_proxy_reason": "Mixed; no USD edge",
        "news_events": [],
        "recent_signals": [],
        "recent_accuracy": [],
        "accuracy_last_5": None,
        # Deterministic D1 STATED FACT — moderate-conviction BULL, no headline news
        "d1_direction_detail": {
            "direction": "BULL",
            "confidence": "moderate",
            "score": 6,
            "reason": "BULL moderate (score +6/9)",
            "checks": {
                "ema_stack":           {"verdict": "BULL", "value": {}},
                "ema_fan":             {"verdict": "BULL", "value": {}},
                "ema8_slope":          {"verdict": "BULL", "value": {}},
                "macd_sign":           {"verdict": "BULL", "value": {}},
                "macd_trend":          {"verdict": "NEUTRAL", "value": {}},
                "price_vs_ema50":      {"verdict": "BULL", "value": {}},
                "consec_closes_ema50": {"verdict": "BULL", "value": {}},
                "higher_highs_lows":   {"verdict": "NEUTRAL", "value": {}},
                "close_direction":     {"verdict": "BULL", "value": {}},
            },
            "thresholds": {},
            "cache": {"path": "synthetic", "age_h": 0.0, "stale": False, "n_candles": 56},
        },
    }


def main():
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    # Mock all 5 live-state sources
    patches = [
        patch("morning_briefing.briefing_calibrator.get_calibration_summary",
              side_effect=_patched_get_calibration_summary),
        patch("morning_briefing._get_recent_prediction_accuracy",
              side_effect=_patched_get_recent_prediction_accuracy),
        patch("briefing_narrative.get_today_narrative_text",
              side_effect=_patched_get_today_narrative_text),
        patch("structural_state.get_structural_state",
              side_effect=_patched_get_structural_state),
        patch("news_calendar.get_todays_events",
              side_effect=_patched_get_todays_events),
    ]
    for p in patches:
        p.start()

    try:
        pkg = build_single_thesis_pkg()
        user_msg = morning_briefing._build_user_message("GBPUSD", "London", pkg)

        # Sanity check: confirm the user message has no CPI/inflation contamination
        leak_tokens = ["CPI", "Inflation Rate", "Existing Home Sales",
                       "NFP", "12:30 UTC | USD", "Within ±1h of"]
        leaks = [t for t in leak_tokens if t in user_msg]
        if leaks:
            print(f"WARNING: leak tokens still present in user_msg: {leaks}")
            # Save for inspection
            (OUT / "no_news_test_user_msg_leaked.txt").write_text(user_msg)
            print(f"  full user_msg saved to {OUT}/no_news_test_user_msg_leaked.txt")
        else:
            print("Sanity check: no news-state leakage in user_msg ✓")
            (OUT / "no_news_test_user_msg.txt").write_text(user_msg)
            print(f"  full user_msg ({len(user_msg)} chars) saved to "
                  f"{OUT}/no_news_test_user_msg.txt")

        print()
        print(f"Calling Anthropic API ({ANTHROPIC_MODEL}, max_tokens={BRIEFING_MAX_TOKENS})...")
        t0 = time.time()
        resp = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": BRIEFING_MAX_TOKENS,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            },
            timeout=180,
        )
        resp.raise_for_status()
        body = resp.json()
        text = body["content"][0]["text"].strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()
        briefing = json.loads(text)
        dt = time.time() - t0

        # Save full response
        out_path = OUT / "no_news_test_briefing.json"
        out_path.write_text(json.dumps(briefing, indent=2))

        bt = briefing.get("best_trade") or {}
        mode = bt.get("mode", "(none)")
        plans = briefing.get("trading_plans") or []
        biases = sorted({str(p.get("bias", "?")).upper() for p in plans})
        sessions = sorted({str(p.get("session", "?")) for p in plans})

        print()
        print("=" * 76)
        print(f"  RESULT — best_trade.mode = {mode}  (took {dt:.1f}s)")
        print("=" * 76)
        print(f"  plan_summary    : {briefing.get('plan_summary')}")
        print(f"  daily_bias      : {briefing.get('daily_bias')}")
        print(f"  session_bias    : {briefing.get('session_bias')}")
        print(f"  trading_plans   : {len(plans)} plans | biases={biases} | sessions={sessions}")
        print(f"  best_trade      : {json.dumps(bt, indent=2)}")
        print()
        print(f"  Full response saved to: {out_path}")
        print()

        # Acceptance decision
        if mode == "UNCONDITIONAL":
            print("✓ ACCEPTANCE: prompt correctly produces UNCONDITIONAL on single-thesis no-news input.")
            print("  → Commit cleared.")
        elif mode == "CONDITIONAL":
            print("✗ ACCEPTANCE: prompt produced CONDITIONAL on single-thesis no-news input.")
            print("  → Over-correction confirmed. Tighten prompt before commit.")
            branches = bt.get("conditional_branches") or []
            print(f"  branches authored ({len(branches)}):")
            for i, br in enumerate(branches):
                print(f"    {i+1}. ({br.get('plan_session')},{br.get('plan_rank')}) "
                      f"— {br.get('condition_text')}")
        else:
            print(f"? ACCEPTANCE: best_trade.mode = {mode!r} (neither UNCONDITIONAL nor CONDITIONAL).")
            print("  → Inspect output manually.")

    finally:
        for p in patches:
            p.stop()


if __name__ == "__main__":
    main()
