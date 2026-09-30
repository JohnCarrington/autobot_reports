#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
briefing_outcome_tracker.py — Track briefing prediction outcomes.

On each new briefing:
  Store structured prediction data (session_expectation, trading_plans[0]
  entry_zone, targets, stop, probability, confidence, liquidity_pools).

After each session closes:
  Compare actual 5m candle data against predictions and record:
    sweep_happened        bool    Did price reach a predicted liquidity level?
    sweep_level_accuracy  float   Distance (pips) between predicted and actual sweep level
    reversal_followed     bool    Did price reverse after the sweep?
    reversal_depth        float   How far (pips) the reversal went
    time_to_sweep         float   Minutes from session start to sweep

Output: /opt/tradingbot/data/briefing_outcomes.jsonl  (append-only)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("briefing_outcome_tracker")

# ── paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/opt/tradingbot")
CANDLES_DIR = Path(os.getenv("CANDLES_DIR", BASE_DIR / "data" / "candles"))
OUTCOMES_PATH = Path(
    os.getenv("BRIEFING_OUTCOMES_PATH", BASE_DIR / "data" / "briefing_outcomes.jsonl")
)

# ── session windows (UTC hhmm) ────────────────────────────────────────────────
_SESSION_WINDOWS: dict[str, tuple[int, int]] = {
    "Asian":       (   0,  630),
    "London":      ( 630,  800),
    "London_Open": ( 800, 1045),
    "Mid-session": (1045, 1300),
    "NY":          (1300, 1500),
    "NY_Data":     (1235, 1240),  # partial-refresh slot; no trading window
    "NY_Mid":      (1500, 1800),
}

# Pip divisor — USDJPY/GBPJPY use 100, others use 10000.
# IG quotes in "points" where 1 point ≈ 1 pip for EUR/GBP pairs.
# We keep everything in IG points (same as pips for most pairs).

_write_lock = threading.Lock()

# In-memory pending predictions keyed by (symbol, date, session)
_pending: Dict[tuple, dict] = {}
_pending_lock = threading.Lock()


# ── helpers ───────────────────────────────────────────────────────────────────

def _session_bounds(date_str: str, session: str) -> Optional[tuple[datetime, datetime]]:
    window = _SESSION_WINDOWS.get(session)
    if window is None:
        return None
    date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    s_hm, e_hm = window
    start = date + timedelta(hours=s_hm // 100, minutes=s_hm % 100)
    end = date + timedelta(hours=e_hm // 100, minutes=e_hm % 100)
    return start, end


def _load_candles(symbol: str, date_str: str) -> Optional[pd.DataFrame]:
    path = CANDLES_DIR / symbol.upper() / f"{date_str}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return df if not df.empty else None
    except Exception as e:
        logger.warning("Failed to load candles %s: %s", path, e)
        return None


def _already_recorded(date: str, session: str, symbol: str) -> bool:
    if not OUTCOMES_PATH.exists():
        return False
    try:
        with OUTCOMES_PATH.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if (rec.get("date") == date
                            and rec.get("session") == session
                            and rec.get("symbol") == symbol):
                        return True
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return False


def _pip_distance(a: float, b: float) -> float:
    return round(abs(a - b), 1)


# ── public API ────────────────────────────────────────────────────────────────

def store_prediction(briefing: dict) -> None:
    """Called when a new briefing is generated. Extracts and caches prediction data."""
    symbol = briefing.get("symbol", "").upper()
    session = briefing.get("session", "")
    bt = briefing.get("briefing_time", "")
    if not symbol or not session or not bt:
        return

    date_str = bt[:10]

    plans = briefing.get("trading_plans") or []
    plan0 = plans[0] if plans else {}

    prediction = {
        "symbol": symbol,
        "session": session,
        "date": date_str,
        "briefing_time": bt,
        "session_expectation": briefing.get("session_expectation"),
        "session_bias": briefing.get("session_bias"),
        "bias_confidence": briefing.get("bias_confidence"),
        "liquidity_pools": briefing.get("liquidity_pools"),
        # trading_plans[0] fields
        "plan_label": plan0.get("label"),
        "plan_probability": plan0.get("probability"),
        "plan_confidence": plan0.get("confidence"),
        "plan_bias": plan0.get("bias"),
        "plan_entry_zone": plan0.get("entry_zone"),
        "plan_stop_loss": plan0.get("stop_loss"),
        "plan_targets": plan0.get("targets"),
        # scenario tracking
        "session_high_estimate": briefing.get("session_high_estimate"),
        "session_low_estimate": briefing.get("session_low_estimate"),
        # Regime tracking
        "regime": briefing.get("regime"),
        "regime_confidence": briefing.get("regime_confidence"),
        "structure": briefing.get("structure"),
        "structure_confidence": briefing.get("structure_confidence"),
    }

    key = (symbol, date_str, session)
    with _pending_lock:
        _pending[key] = prediction

    logger.info(
        "[outcome_tracker] Stored prediction %s %s %s expectation=%s plan=%s",
        symbol, date_str, session,
        prediction["session_expectation"],
        prediction["plan_label"],
    )


def evaluate_completed_sessions() -> int:
    """
    Evaluate all pending predictions whose session window has closed.
    Returns the number of outcomes written.
    """
    now = datetime.now(timezone.utc)
    written = 0

    with _pending_lock:
        keys = list(_pending.keys())

    for key in keys:
        symbol, date_str, session = key

        bounds = _session_bounds(date_str, session)
        if bounds is None:
            with _pending_lock:
                _pending.pop(key, None)
            continue

        _, session_end = bounds
        # Wait 5 minutes after session end for final candle to settle
        if now < session_end + timedelta(minutes=5):
            continue

        with _pending_lock:
            prediction = _pending.pop(key, None)
        if prediction is None:
            continue

        if _already_recorded(date_str, session, symbol):
            logger.debug("Already recorded %s %s %s — skipping", date_str, session, symbol)
            continue

        outcome = _evaluate_one(prediction, bounds)
        if outcome is not None:
            _write_outcome(outcome)
            written += 1

    return written


def backfill_from_briefings(briefings_dir: Path) -> int:
    """
    Scan briefing JSON files on disk and evaluate any that haven't been recorded yet.
    Useful for bootstrapping the outcomes file from historical briefings.
    """
    written = 0
    for path in sorted(briefings_dir.glob("briefing_*.json")):
        try:
            with path.open() as fh:
                briefing = json.load(fh)
        except Exception:
            continue

        symbol = briefing.get("symbol", "").upper()
        session = briefing.get("session", "")
        bt = briefing.get("briefing_time", "")
        if not symbol or not session or not bt:
            continue

        date_str = bt[:10]
        if _already_recorded(date_str, session, symbol):
            continue

        bounds = _session_bounds(date_str, session)
        if bounds is None:
            continue

        _, session_end = bounds
        now = datetime.now(timezone.utc)
        if now < session_end + timedelta(minutes=5):
            continue

        # Build prediction from briefing
        store_prediction(briefing)
        key = (symbol, date_str, session)
        with _pending_lock:
            prediction = _pending.pop(key, None)
        if prediction is None:
            continue

        outcome = _evaluate_one(prediction, bounds)
        if outcome is not None:
            _write_outcome(outcome)
            written += 1

    logger.info("[outcome_tracker] Backfill wrote %d outcomes", written)
    return written


# ── evaluation engine ─────────────────────────────────────────────────────────

def _evaluate_one(
    prediction: dict,
    bounds: tuple[datetime, datetime],
) -> Optional[dict]:
    """Evaluate a single prediction against candle data."""
    symbol = prediction["symbol"]
    date_str = prediction["date"]
    session = prediction["session"]
    session_start, session_end = bounds

    df = _load_candles(symbol, date_str)
    if df is None:
        return None

    mask = (df["timestamp"] >= session_start) & (df["timestamp"] < session_end)
    sdf = df[mask]
    if sdf.empty or len(sdf) < 3:
        return None

    session_open = float(sdf.iloc[0]["open"])
    session_close = float(sdf.iloc[-1]["close"])
    session_high = float(sdf["high"].max())
    session_low = float(sdf["low"].min())

    # ── Sweep detection ───────────────────────────────────────────────────
    liq = prediction.get("liquidity_pools") or {}
    buy_side = liq.get("buy_side") or []   # upside liquidity levels
    sell_side = liq.get("sell_side") or []  # downside liquidity levels

    plan_bias = (prediction.get("plan_bias") or "").upper()

    # Determine which side to check for sweep based on session expectation
    # LIQUIDITY_HUNT: check the side the briefing expects price to sweep
    # For SHORT bias: expect price to sweep buy_side (upside) then reverse down
    # For LONG bias: expect price to sweep sell_side (downside) then reverse up
    sweep_happened = False
    sweep_level_accuracy = None
    reversal_followed = False
    reversal_depth = 0.0
    time_to_sweep = None
    swept_level = None

    # Check buy-side sweeps (price went up and took out buy-side liquidity)
    best_buy_sweep = _check_sweep(sdf, buy_side, "buy_side", session_start)
    # Check sell-side sweeps (price went down and took out sell-side liquidity)
    best_sell_sweep = _check_sweep(sdf, sell_side, "sell_side", session_start)

    # Pick the sweep that matches the prediction's expected direction
    if prediction.get("session_expectation") == "LIQUIDITY_HUNT":
        if plan_bias == "SHORT" and best_buy_sweep:
            sweep_result = best_buy_sweep
        elif plan_bias == "LONG" and best_sell_sweep:
            sweep_result = best_sell_sweep
        elif best_buy_sweep or best_sell_sweep:
            # Either side swept — take whichever happened
            sweep_result = best_buy_sweep or best_sell_sweep
        else:
            sweep_result = None
    else:
        # For TREND/RANGE, check if any liquidity was swept
        sweep_result = best_buy_sweep or best_sell_sweep

    if sweep_result:
        sweep_happened = True
        swept_level = sweep_result["level"]
        sweep_level_accuracy = sweep_result["accuracy"]
        time_to_sweep = sweep_result["time_minutes"]

        # ── Reversal detection after sweep ────────────────────────────────
        sweep_idx = sweep_result["candle_idx"]
        if sweep_idx < len(sdf) - 1:
            post_sweep = sdf.iloc[sweep_idx + 1:]
            if not post_sweep.empty:
                if sweep_result["side"] == "buy_side":
                    # Swept upside → reversal is price moving down
                    sweep_price = float(sdf.iloc[sweep_idx]["high"])
                    post_low = float(post_sweep["low"].min())
                    depth = sweep_price - post_low
                    if depth > 5.0:  # at least 5 points of reversal
                        reversal_followed = True
                        reversal_depth = round(depth, 1)
                else:
                    # Swept downside → reversal is price moving up
                    sweep_price = float(sdf.iloc[sweep_idx]["low"])
                    post_high = float(post_sweep["high"].max())
                    depth = post_high - sweep_price
                    if depth > 5.0:
                        reversal_followed = True
                        reversal_depth = round(depth, 1)

    # ── Plan target accuracy ──────────────────────────────────────────────
    # A target counts as HIT only when:
    #   (a) the session high/low actually reached it, AND
    #   (b) the target is on the correct side of entry for the plan bias.
    # Condition (b) catches plans whose targets were placed in the wrong
    # direction — e.g. a LONG plan with TP1 below entry. Before this guard
    # those plans scored tp1_hit=True trivially because session_high almost
    # always exceeds a target set below entry.
    # If the plan has no directional bias, fall back to the prior plain
    # price-reached semantics.
    targets = prediction.get("plan_targets") or []
    tp1_hit = False
    tp2_hit = False

    # Determine a representative entry price from the plan's entry_zone.
    zone = prediction.get("plan_entry_zone") or []
    try:
        entry_price = (float(zone[0]) + float(zone[-1])) / 2.0 if len(zone) >= 1 else None
    except Exception:
        entry_price = None

    def _correct_side(tp: float) -> bool:
        """True if `tp` sits on the expected side of entry for the plan bias,
        or we lack the info to judge (in which case fall back to True)."""
        if entry_price is None or plan_bias not in ("LONG", "SHORT"):
            return True
        try:
            tp_f = float(tp)
        except Exception:
            return False
        if plan_bias == "LONG":
            return tp_f > entry_price
        return tp_f < entry_price  # SHORT

    if targets and plan_bias:
        if plan_bias == "SHORT":
            if len(targets) >= 1 and session_low <= targets[0] and _correct_side(targets[0]):
                tp1_hit = True
            if len(targets) >= 2 and session_low <= targets[1] and _correct_side(targets[1]):
                tp2_hit = True
        elif plan_bias == "LONG":
            if len(targets) >= 1 and session_high >= targets[0] and _correct_side(targets[0]):
                tp1_hit = True
            if len(targets) >= 2 and session_high >= targets[1] and _correct_side(targets[1]):
                tp2_hit = True
    elif targets:
        # No directional bias — preserve legacy "price reached level" semantics.
        if len(targets) >= 1 and (session_low <= targets[0] <= session_high):
            tp1_hit = True
        if len(targets) >= 2 and (session_low <= targets[1] <= session_high):
            tp2_hit = True

    # ── Session range estimate accuracy ───────────────────────────────────
    high_est = prediction.get("session_high_estimate")
    low_est = prediction.get("session_low_estimate")
    high_estimate_error = round(abs(session_high - high_est), 1) if high_est else None
    low_estimate_error = round(abs(session_low - low_est), 1) if low_est else None

    # ── Bias correctness ──────────────────────────────────────────────────
    pip_move = session_close - session_open
    if pip_move > 5.0:
        actual_direction = "BULLISH"
    elif pip_move < -5.0:
        actual_direction = "BEARISH"
    else:
        actual_direction = "NEUTRAL"

    session_bias = (prediction.get("session_bias") or "").upper()
    bias_correct = (
        session_bias == actual_direction
        if session_bias in ("BULLISH", "BEARISH")
        else None
    )

    # ── Regime accuracy ─────────────────────────────────────────────────
    predicted_regime = (prediction.get("regime") or "").upper()
    # Derive actual regime from price action:
    # NEWS: handled by briefing (kept as-is), TREND: large directional move,
    # SWEEP: price swept extremes then reversed
    session_range = session_high - session_low if session_high and session_low else 0
    _regime_correct = None
    if predicted_regime in ("SWEEP", "TREND", "NEWS"):
        if predicted_regime == "TREND":
            _regime_correct = pip_move > session_range * 0.4  # strong directional = trend
        elif predicted_regime == "SWEEP":
            _regime_correct = pip_move <= session_range * 0.4  # range-bound / reversal
        elif predicted_regime == "NEWS":
            _regime_correct = True  # NEWS regime correctness based on calendar, always valid

    # ── Day of week (0=Mon..6=Sun) ────────────────────────────────────────
    try:
        dow = datetime.strptime(date_str, "%Y-%m-%d").weekday()
    except Exception:
        dow = None

    return {
        "date": date_str,
        "session": session,
        "symbol": symbol,
        "briefing_time": prediction.get("briefing_time"),
        "day_of_week": dow,
        # Prediction snapshot
        "session_expectation": prediction.get("session_expectation"),
        "session_bias": session_bias,
        "bias_confidence": prediction.get("bias_confidence"),
        "plan_label": prediction.get("plan_label"),
        "plan_probability": prediction.get("plan_probability"),
        "plan_confidence": prediction.get("plan_confidence"),
        "plan_bias": plan_bias,
        "plan_entry_zone": prediction.get("plan_entry_zone"),
        "plan_stop_loss": prediction.get("plan_stop_loss"),
        "plan_targets": prediction.get("plan_targets"),
        # Actual session data
        "session_open": session_open,
        "session_close": session_close,
        "session_high": session_high,
        "session_low": session_low,
        "pip_move": round(pip_move, 1),
        "actual_direction": actual_direction,
        "bias_correct": bias_correct,
        # Sweep metrics
        "sweep_happened": sweep_happened,
        "sweep_level_accuracy": sweep_level_accuracy,
        "swept_level": swept_level,
        "reversal_followed": reversal_followed,
        "reversal_depth": reversal_depth,
        "time_to_sweep": time_to_sweep,
        # Target accuracy
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        # Range estimates
        "high_estimate_error": high_estimate_error,
        "low_estimate_error": low_estimate_error,
        # Regime
        "regime": predicted_regime or None,
        "regime_confidence": prediction.get("regime_confidence"),
        "regime_correct": _regime_correct,
    }


def _check_sweep(
    sdf: pd.DataFrame,
    levels: list,
    side: str,
    session_start: datetime,
) -> Optional[dict]:
    """
    Check if any candle in the session swept a liquidity level.
    Returns info about the closest/first sweep, or None.
    """
    if not levels:
        return None

    best = None
    for i, row in sdf.iterrows():
        candle_high = float(row["high"])
        candle_low = float(row["low"])
        candle_ts = row["timestamp"]

        for level in levels:
            if level is None:
                continue
            level = float(level)

            swept = False
            accuracy = 0.0

            if side == "buy_side":
                # Buy-side liquidity is above price — swept when high >= level
                if candle_high >= level:
                    swept = True
                    accuracy = round(abs(candle_high - level), 1)
            else:
                # Sell-side liquidity is below price — swept when low <= level
                if candle_low <= level:
                    swept = True
                    accuracy = round(abs(candle_low - level), 1)

            if swept:
                elapsed = (candle_ts - session_start).total_seconds() / 60.0
                result = {
                    "level": level,
                    "accuracy": accuracy,
                    "time_minutes": round(elapsed, 1),
                    "candle_idx": sdf.index.get_loc(i) if i in sdf.index else 0,
                    "side": side,
                }
                if best is None:
                    best = result
                elif elapsed < best["time_minutes"]:
                    best = result

    return best


def _write_outcome(outcome: dict) -> None:
    OUTCOMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with OUTCOMES_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(outcome) + "\n")
    logger.info(
        "[outcome_tracker] Recorded %s %s %s sweep=%s reversal=%s tp1=%s",
        outcome["symbol"], outcome["date"], outcome["session"],
        outcome["sweep_happened"], outcome["reversal_followed"],
        outcome["tp1_hit"],
    )


# ── statistics for /briefing-accuracy endpoint ────────────────────────────────

def load_all_outcomes() -> List[dict]:
    """Load all outcome records from disk."""
    if not OUTCOMES_PATH.exists():
        return []
    records = []
    with OUTCOMES_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def compute_accuracy_stats() -> dict:
    """
    Compute accuracy statistics grouped by session, pair, confidence, day of week.
    Returns a dict suitable for JSON response.
    """
    records = load_all_outcomes()
    if not records:
        return {"total_outcomes": 0, "by_session": {}, "by_pair": {},
                "by_confidence": {}, "by_day_of_week": {}, "overall": {}}

    total = len(records)

    def _bucket_stats(recs: List[dict]) -> dict:
        n = len(recs)
        if n == 0:
            return {"n": 0}

        sweeps = [r for r in recs if r.get("sweep_happened")]
        reversals = [r for r in recs if r.get("reversal_followed")]
        bias_assessable = [r for r in recs if r.get("bias_correct") is not None]
        bias_correct = [r for r in bias_assessable if r.get("bias_correct")]
        regime_assessable = [r for r in recs if r.get("regime_correct") is not None]
        regime_correct = [r for r in regime_assessable if r.get("regime_correct")]
        tp1_hits = [r for r in recs if r.get("tp1_hit")]
        tp2_hits = [r for r in recs if r.get("tp2_hit")]

        sweep_accuracies = [
            r["sweep_level_accuracy"] for r in sweeps
            if r.get("sweep_level_accuracy") is not None
        ]
        reversal_depths = [
            r["reversal_depth"] for r in reversals
            if r.get("reversal_depth") is not None
        ]
        sweep_times = [
            r["time_to_sweep"] for r in sweeps
            if r.get("time_to_sweep") is not None
        ]

        return {
            "n": n,
            "sweep_rate": round(len(sweeps) / n * 100, 1),
            "reversal_rate": round(len(reversals) / n * 100, 1) if sweeps else 0,
            "reversal_after_sweep_rate": (
                round(len(reversals) / len(sweeps) * 100, 1) if sweeps else None
            ),
            "bias_accuracy": (
                round(len(bias_correct) / len(bias_assessable) * 100, 1)
                if bias_assessable else None
            ),
            "regime_accuracy": (
                round(len(regime_correct) / len(regime_assessable) * 100, 1)
                if regime_assessable else None
            ),
            "tp1_hit_rate": round(len(tp1_hits) / n * 100, 1),
            "tp2_hit_rate": round(len(tp2_hits) / n * 100, 1),
            "avg_sweep_accuracy_pips": (
                round(sum(sweep_accuracies) / len(sweep_accuracies), 1)
                if sweep_accuracies else None
            ),
            "avg_reversal_depth_pips": (
                round(sum(reversal_depths) / len(reversal_depths), 1)
                if reversal_depths else None
            ),
            "avg_time_to_sweep_min": (
                round(sum(sweep_times) / len(sweep_times), 1)
                if sweep_times else None
            ),
        }

    overall = _bucket_stats(records)

    # Group by session
    by_session: Dict[str, dict] = {}
    sessions = sorted(set(r.get("session", "") for r in records))
    for s in sessions:
        if s:
            by_session[s] = _bucket_stats([r for r in records if r.get("session") == s])

    # Group by pair
    by_pair: Dict[str, dict] = {}
    symbols = sorted(set(r.get("symbol", "") for r in records))
    for sym in symbols:
        if sym:
            by_pair[sym] = _bucket_stats([r for r in records if r.get("symbol") == sym])

    # Group by plan confidence
    by_confidence: Dict[str, dict] = {}
    for conf in ("HIGH", "MEDIUM", "LOW"):
        recs = [r for r in records if (r.get("plan_confidence") or "").upper() == conf]
        if recs:
            by_confidence[conf] = _bucket_stats(recs)

    # Group by day of week
    _day_names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday"}
    by_dow: Dict[str, dict] = {}
    for dow_num, name in _day_names.items():
        recs = [r for r in records if r.get("day_of_week") == dow_num]
        if recs:
            by_dow[name] = _bucket_stats(recs)

    # Group by regime
    by_regime: Dict[str, dict] = {}
    for regime in ("SWEEP", "TREND", "NEWS"):
        recs = [r for r in records if (r.get("regime") or "").upper() == regime]
        if recs:
            by_regime[regime] = _bucket_stats(recs)

    return {
        "total_outcomes": total,
        "overall": overall,
        "by_session": by_session,
        "by_pair": by_pair,
        "by_confidence": by_confidence,
        "by_day_of_week": by_dow,
        "by_regime": by_regime,
    }
