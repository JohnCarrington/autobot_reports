#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
briefing_accuracy.py — Measures how often session bias predictions were correct.

For each briefing JSON, finds the 5m candle data covering that session window,
measures the actual price direction, and compares to the predicted session_bias.

Output: /opt/tradingbot/data/briefing_accuracy.jsonl (append-only, one record per session)

Fields per record:
    date            str     YYYY-MM-DD
    session         str     Asian | London | Mid-session | NY
    symbol          str     GBPUSD etc.
    briefing_time   str     ISO-8601 UTC when briefing was generated
    predicted_bias  str     BULLISH | BEARISH | NEUTRAL | LIQUIDITY_HUNT
    bias_confidence float
    session_start   str     ISO-8601 UTC
    session_end     str     ISO-8601 UTC
    open_price      float   first candle open in session window
    close_price     float   last candle close in session window
    pip_move        float   close - open (IG points; equals pips for EUR/GBP pairs)
    actual_direction str    BULLISH | BEARISH | NEUTRAL
    correct         bool    True if predicted_bias matched actual_direction
    candles_used    int     number of 5m candles in session window
    assessable      bool    False if bias was NEUTRAL/LIQUIDITY_HUNT or no candle data

Run daily at 18:00 UTC via cron to capture the full NY session:
    0 18 * * * /opt/tradingbot/venv/bin/python3 /opt/tradingbot/briefing_accuracy.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("briefing_accuracy")

# ── paths ──────────────────────────────────────────────────────────────────────
BASE_DIR        = Path("/opt/tradingbot")
BRIEFINGS_DIR   = Path(os.getenv("BRIEFINGS_DIR",   BASE_DIR / "logs"))
CANDLES_DIR     = Path(os.getenv("CANDLES_DIR",     BASE_DIR / "data" / "candles"))
OUTPUT_PATH     = Path(os.getenv("ACCURACY_OUTPUT", BASE_DIR / "data" / "briefing_accuracy.jsonl"))

# Minimum pip move (IG points) before we call a session directional rather than NEUTRAL.
# EURUSD/GBPUSD: 1 IG point ≈ 1 pip.  USDJPY: 1 pip ≈ 10 IG points.
NEUTRAL_THRESHOLD_POINTS = float(os.getenv("ACCURACY_NEUTRAL_THRESHOLD", "5.0"))

# ── session window definitions (UTC) ──────────────────────────────────────────
# Each session runs from its start time up to (but not including) the next session.
_SESSION_WINDOWS: dict[str, tuple[int, int]] = {
    # session_name: (start_hour_minute_as_hhmm, end_hour_minute_as_hhmm)
    "Asian":       (   0,  630),   # 00:00 – 06:30
    "London":      ( 630, 1045),   # 06:30 – 10:45
    "Mid-session": (1045, 1300),   # 10:45 – 13:00
    "NY":          (1300, 1800),   # 13:00 – 18:00
    "NY_Data":     (1235, 1240),   # 12:35 – 12:40 (partial-refresh slot; no trading window)
}


def _session_bounds(date_str: str, session: str) -> tuple[datetime, datetime] | None:
    """Return (session_start_utc, session_end_utc) for a given date + session name."""
    window = _SESSION_WINDOWS.get(session)
    if window is None:
        return None
    date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_hm, end_hm = window
    start = date + timedelta(hours=start_hm // 100, minutes=start_hm % 100)
    end   = date + timedelta(hours=end_hm   // 100, minutes=end_hm   % 100)
    return start, end


def _load_candles(symbol: str, date_str: str) -> Optional[pd.DataFrame]:
    """Load the daily 5m archive CSV for symbol/date. Returns None if unavailable."""
    path = CANDLES_DIR / symbol.upper() / f"{date_str}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return df if not df.empty else None
    except Exception as e:
        logger.warning(f"Failed to load candles {path}: {e}")
        return None


def _actual_direction(pip_move: float) -> str:
    if pip_move > NEUTRAL_THRESHOLD_POINTS:
        return "BULLISH"
    if pip_move < -NEUTRAL_THRESHOLD_POINTS:
        return "BEARISH"
    return "NEUTRAL"


def _already_recorded(date: str, session: str, symbol: str) -> bool:
    """Check if this (date, session, symbol) triple already exists in the output file."""
    if not OUTPUT_PATH.exists():
        return False
    try:
        with OUTPUT_PATH.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("date") == date and rec.get("session") == session and rec.get("symbol") == symbol:
                        return True
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return False


# ── core analysis ─────────────────────────────────────────────────────────────

def analyse_briefing(path: Path) -> Optional[dict]:
    """
    Analyse one briefing JSON file.
    Returns a result dict, or None if analysis cannot be performed.
    """
    try:
        with path.open() as fh:
            briefing = json.load(fh)
    except Exception as e:
        logger.warning(f"Cannot parse {path.name}: {e}")
        return None

    symbol          = briefing.get("symbol", "").upper()
    session         = briefing.get("session", "")
    briefing_time   = briefing.get("briefing_time", "")
    session_bias    = briefing.get("session_bias", "NEUTRAL")
    bias_confidence = float(briefing.get("bias_confidence") or 0.0)

    if not symbol or not session:
        return None

    # Derive date from briefing_time or filename
    date_str: str | None = None
    if briefing_time:
        try:
            date_str = briefing_time[:10]
        except Exception:
            pass
    if not date_str:
        # fallback: parse from filename  briefing_GBPUSD_2026-03-30_London.json
        stem = path.stem  # briefing_GBPUSD_2026-03-30_London
        parts = stem.split("_")
        for p in parts:
            if len(p) == 10 and p[4] == "-" and p[7] == "-":
                date_str = p
                break
    if not date_str:
        return None

    if _already_recorded(date_str, session, symbol):
        logger.debug(f"Already recorded: {date_str} {session} {symbol} — skipping")
        return None

    bounds = _session_bounds(date_str, session)
    if bounds is None:
        return None
    session_start, session_end = bounds

    # Load candle data for this symbol/date
    df = _load_candles(symbol, date_str)

    # For NY session (ends 18:00) we may also need next day if data is split;
    # but since daily files use UTC date of the candle timestamp, same-day file suffices.
    if df is None:
        logger.info(f"No candle data for {symbol} {date_str} — recording as unassessable")
        return {
            "date":             date_str,
            "session":          session,
            "symbol":           symbol,
            "briefing_time":    briefing_time,
            "predicted_bias":   session_bias,
            "bias_confidence":  bias_confidence,
            "session_start":    session_start.isoformat(),
            "session_end":      session_end.isoformat(),
            "open_price":       None,
            "close_price":      None,
            "pip_move":         None,
            "actual_direction": None,
            "correct":          None,
            "candles_used":     0,
            "assessable":       False,
        }

    # Filter candles within session window
    mask = (df["timestamp"] >= session_start) & (df["timestamp"] < session_end)
    session_df = df[mask]

    if session_df.empty:
        logger.info(f"No candles in session window {symbol} {date_str} {session}")
        return {
            "date":             date_str,
            "session":          session,
            "symbol":           symbol,
            "briefing_time":    briefing_time,
            "predicted_bias":   session_bias,
            "bias_confidence":  bias_confidence,
            "session_start":    session_start.isoformat(),
            "session_end":      session_end.isoformat(),
            "open_price":       None,
            "close_price":      None,
            "pip_move":         None,
            "actual_direction": None,
            "correct":          None,
            "candles_used":     0,
            "assessable":       False,
        }

    open_price  = float(session_df.iloc[0]["open"])
    close_price = float(session_df.iloc[-1]["close"])
    pip_move    = round(close_price - open_price, 5)
    actual_dir  = _actual_direction(pip_move)
    candles_used = len(session_df)

    # Only assessable if bias is directional (not NEUTRAL or LIQUIDITY_HUNT)
    assessable = session_bias in ("BULLISH", "BEARISH")
    correct: bool | None = None
    if assessable:
        correct = (session_bias == actual_dir)

    return {
        "date":             date_str,
        "session":          session,
        "symbol":           symbol,
        "briefing_time":    briefing_time,
        "predicted_bias":   session_bias,
        "bias_confidence":  bias_confidence,
        "session_start":    session_start.isoformat(),
        "session_end":      session_end.isoformat(),
        "open_price":       open_price,
        "close_price":      close_price,
        "pip_move":         pip_move,
        "actual_direction": actual_dir,
        "correct":          correct,
        "candles_used":     candles_used,
        "assessable":       assessable,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def run(target_date: str | None = None) -> None:
    """
    Process briefing JSONs from BRIEFINGS_DIR.
    If target_date (YYYY-MM-DD) is given, only process that date.
    Otherwise processes all available briefings.
    """
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    briefing_files = sorted(BRIEFINGS_DIR.glob("briefing_*.json"))
    if not briefing_files:
        logger.warning(f"No briefing files found in {BRIEFINGS_DIR}")
        return

    if target_date:
        briefing_files = [f for f in briefing_files if target_date in f.name]
        logger.info(f"Processing {len(briefing_files)} briefings for {target_date}")
    else:
        logger.info(f"Processing {len(briefing_files)} briefing files")

    written = 0
    skipped = 0
    no_data = 0

    with OUTPUT_PATH.open("a") as out:
        for path in briefing_files:
            result = analyse_briefing(path)
            if result is None:
                skipped += 1
                continue
            if result["candles_used"] == 0:
                no_data += 1
            out.write(json.dumps(result) + "\n")
            written += 1
            status = "✓" if result.get("correct") else ("✗" if result.get("correct") is False else "—")
            logger.info(
                f"[{status}] {result['date']} {result['session']:12s} {result['symbol']} "
                f"predicted={result['predicted_bias']:12s} actual={result.get('actual_direction') or 'N/A':8s} "
                f"move={result.get('pip_move') or 0:+.1f}pts candles={result['candles_used']}"
            )

    logger.info(f"Done — written={written} skipped={skipped} no_candle_data={no_data}")

    # Print a quick accuracy summary
    _print_summary()


def _print_summary() -> None:
    if not OUTPUT_PATH.exists():
        return
    records = []
    with OUTPUT_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    assessable = [r for r in records if r.get("assessable")]
    if not assessable:
        logger.info("No assessable records yet (all biases were NEUTRAL/LIQUIDITY_HUNT or no candle data)")
        return

    correct = [r for r in assessable if r.get("correct") is True]
    accuracy = len(correct) / len(assessable) * 100

    logger.info(
        f"=== Accuracy summary: {len(correct)}/{len(assessable)} correct ({accuracy:.1f}%) "
        f"across {len(set(r['symbol'] for r in assessable))} symbols ==="
    )

    # Per-symbol breakdown
    for sym in sorted(set(r["symbol"] for r in assessable)):
        sym_recs = [r for r in assessable if r["symbol"] == sym]
        sym_correct = [r for r in sym_recs if r.get("correct") is True]
        logger.info(
            f"  {sym}: {len(sym_correct)}/{len(sym_recs)} ({len(sym_correct)/len(sym_recs)*100:.1f}%)"
        )


if __name__ == "__main__":
    # Optional: pass a date as argv[1] to limit processing
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(target_date=date_arg)
