#!/usr/bin/env python3
"""Observation-only pierce + rejection-close candidate detector.

Emits one CSV row per candidate signal — no orders, no state changes,
no IG import. Deployment target: Project Thirty droplet (or any host
that can stream 5m GBPUSD candles).

Detection rules (spec_pins/gbpusd_bb_bounce_s_implementation_spec_20260929.md §2):
  - Bar N-1 (setup): high ≥ BBU(N-1) + PIERCE_THRESH_PIPS AND open ≤ BBU(N-1)
  - Bar N (rejection, within 3 bars of setup):
      body ≥ MIN_REJECTION_BODY_PIPS
      close < open (bearish, SHORT candidate)
      close ≤ BBU(current) + REJECTION_TOLERANCE_PIPS
  - Emit at rejection-bar CLOSE

Every candidate is written to `candidates_log.csv` with the OHLC of
both bars, BB values, pierce depth, rejection body, and both timestamps.
Downstream analysis can compare candidates against later fills / other
strategy signals to test the detector's precision and recall on
Project Thirty's live data.

Broker submission: not implemented. No IG SDK is imported. This module
cannot open a position by construction.

Usage as a library (recommended — the caller supplies the candle stream):

    from observer import Detector
    det = Detector(log_path="/var/log/project30/bb_pierce_candidates.csv",
                   pierce_thresh_pips=0.5)
    for candle in your_5m_stream(...):    # any object with .ts/.o/.h/.l/.c
        det.on_bar(candle)
    # candidates are appended to log_path as they fire.

Usage as a one-shot replay against a CSV of 5m candles:

    python3 observer.py --candles data/candles/GBPUSD/2026-05-27.csv \
                        --out /tmp/candidates.csv \
                        --pierce-thresh 0.5

The detector is stateful per instance. In a live loop, keep one
Detector alive across bars; do NOT construct a new one per bar.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── constants (baked in — no env dependency for a portable observer) ───

BB_LEN                        = 20
BB_STD                        = 2.0
PIERCE_THRESH_PIPS_DEFAULT    = 0.5   # matches the Era B code default; env override allowed
MIN_REJECTION_BODY_PIPS       = 1.5
REJECTION_TOLERANCE_PIPS      = 1.0
REJECTION_WINDOW_BARS         = 3
PIP_UNITS                     = 1.0   # data/candles/GBPUSD/*.csv scale: 1 pip = 1 CSV unit

# session filter — match Era B strategy
WIN_START_HOUR = 6
WIN_END_HOUR   = 17


# ─── data classes ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class Candle:
    ts:    datetime   # bar OPEN time, UTC
    open:  float
    high:  float
    low:   float
    close: float

    @property
    def close_ts(self) -> datetime:
        return self.ts + timedelta(minutes=5)


@dataclass
class _Armed:
    setup_ts:  datetime
    setup_bar: Candle
    bbu_setup: float
    bbl_setup: float


# ─── BB(20, 2.0) with population variance ───────────────────────────────

def _bb_20_2(closes: List[float]):
    if len(closes) < BB_LEN:
        return None
    window = closes[-BB_LEN:]
    mean = sum(window) / BB_LEN
    var  = sum((x - mean) ** 2 for x in window) / BB_LEN
    sd   = math.sqrt(var)
    return (mean - BB_STD * sd, mean, mean + BB_STD * sd)


# ─── the observer ───────────────────────────────────────────────────────

CSV_HEADER = [
    "candidate_ts_utc",         # rejection bar CLOSE time (= entry ts of a live strategy)
    "direction",                # "SELL" (SHORT only in this observer)
    "entry_price_mid",          # rejection bar close price (mid)
    "setup_bar_open_utc",
    "setup_bar_open", "setup_bar_high", "setup_bar_low", "setup_bar_close",
    "rejection_bar_open_utc",
    "rejection_bar_open", "rejection_bar_high", "rejection_bar_low", "rejection_bar_close",
    "bbu_setup", "bbl_setup", "bbm_setup",
    "bbu_current", "bbl_current", "bbm_current",
    "pierce_depth_pips",        # (setup_bar.high - bbu_setup) / pip
    "rejection_body_pips",      # |close - open|
    "back_inside_margin_pips",  # (bbu_current + tolerance) - rejection_bar.close, positive means "inside"
    "rejection_window_idx",     # 1..3 (which bar in the window paired)
    "pierce_thresh_used",
    "in_session",               # True if rejection bar open is in WIN_START..WIN_END UTC
]


class Detector:
    """Bar-by-bar pierce + rejection-close observer.

    Not a trader. `on_bar(candle)` returns a dict describing the
    candidate (or None) and, if `log_path` is set, appends the row to
    the CSV. The log file is opened in append mode and flushed after
    every write so a crash cannot lose more than one line.
    """

    def __init__(self,
                 log_path: Optional[str] = None,
                 pierce_thresh_pips: float = PIERCE_THRESH_PIPS_DEFAULT,
                 session_filter: bool = True):
        self.log_path            = log_path
        self.pierce_thresh_pips  = float(pierce_thresh_pips)
        self.session_filter      = bool(session_filter)
        self._closes:      List[float] = []
        self._bars:        List[Candle] = []
        self._armed:       List[_Armed] = []
        self._log_writer               = None
        self._log_file                 = None
        if log_path:
            self._open_log(log_path)

    # ─── log lifecycle ──────────────────────────────────────────────

    def _open_log(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        new = not p.exists() or p.stat().st_size == 0
        self._log_file = open(p, "a", newline="")
        self._log_writer = csv.DictWriter(self._log_file, fieldnames=CSV_HEADER)
        if new:
            self._log_writer.writeheader()
            self._log_file.flush()

    def close(self) -> None:
        if self._log_file:
            self._log_file.flush()
            self._log_file.close()
            self._log_file = None
            self._log_writer = None

    def __enter__(self): return self
    def __exit__(self, *a):
        self.close()
        return False

    # ─── helpers ────────────────────────────────────────────────────

    def _in_session(self, ts: datetime) -> bool:
        if ts.weekday() >= 5:
            return False
        return WIN_START_HOUR <= ts.hour < WIN_END_HOUR

    def _age_bars(self, arm: _Armed, cur: Candle) -> float:
        return (cur.ts - arm.setup_ts).total_seconds() / 300.0

    # ─── main entry point ──────────────────────────────────────────

    def on_bar(self, candle: Candle) -> Optional[Dict[str, Any]]:
        """Process one 5m bar. Returns the candidate dict if a
        rejection-close candidate fires on this bar, else None.
        Emits to CSV if configured. Never raises on a bad bar — bad
        input is silently dropped (bench-safe)."""
        try:
            self._bars.append(candle)
            self._closes.append(candle.close)
            keep = BB_LEN + REJECTION_WINDOW_BARS + 2
            if len(self._bars) > keep:
                self._bars   = self._bars[-keep:]
                self._closes = self._closes[-keep:]

            # BB at current bar
            cur_bb = _bb_20_2(self._closes)
            if cur_bb is None:
                return None
            bbl_cur, bbm_cur, bbu_cur = cur_bb

            # Expire armed setups older than the window
            self._armed = [a for a in self._armed
                           if self._age_bars(a, candle) <= float(REJECTION_WINDOW_BARS) + 1e-3]

            # Arm from bar N-1 (the just-previous bar)
            if len(self._bars) >= 2:
                prev = self._bars[-2]
                setup_closes = self._closes[:-1]
                setup_bb = _bb_20_2(setup_closes)
                if setup_bb is not None:
                    bbl_prev, _bbm_prev, bbu_prev = setup_bb
                    thresh_price = self.pierce_thresh_pips * PIP_UNITS
                    short_pierce = (prev.high - bbu_prev) >= thresh_price
                    long_pierce  = (bbl_prev - prev.low)  >= thresh_price
                    if short_pierce and not long_pierce and prev.open <= bbu_prev:
                        if not any(a.setup_ts == prev.ts for a in self._armed):
                            self._armed.append(_Armed(
                                setup_ts=prev.ts, setup_bar=prev,
                                bbu_setup=bbu_prev, bbl_setup=bbl_prev,
                            ))

            # Rejection candidate: bearish body ≥ min, close ≤ BBU_cur + tol
            body = abs(candle.close - candle.open)
            bearish = candle.close < candle.open
            tol_price = REJECTION_TOLERANCE_PIPS * PIP_UNITS
            back_inside_margin = (bbu_cur + tol_price) - candle.close
            body_ok = body >= MIN_REJECTION_BODY_PIPS * PIP_UNITS
            close_ok = candle.close <= bbu_cur + tol_price
            if not (bearish and body_ok and close_ok and self._armed):
                return None

            # Fire on the OLDEST armed setup (matches spec §2.5)
            fired = max(self._armed, key=lambda a: self._age_bars(a, candle))
            window_idx = max(1, int(round(self._age_bars(fired, candle))))
            self._armed = []  # consume all SHORT setups on fire

            in_session = self._in_session(candle.ts)
            # Emit even if out-of-session (observation-only) — flag it.

            row = {
                "candidate_ts_utc":       candle.close_ts.isoformat(),
                "direction":              "SELL",
                "entry_price_mid":        candle.close,
                "setup_bar_open_utc":     fired.setup_bar.ts.isoformat(),
                "setup_bar_open":         fired.setup_bar.open,
                "setup_bar_high":         fired.setup_bar.high,
                "setup_bar_low":          fired.setup_bar.low,
                "setup_bar_close":        fired.setup_bar.close,
                "rejection_bar_open_utc": candle.ts.isoformat(),
                "rejection_bar_open":     candle.open,
                "rejection_bar_high":     candle.high,
                "rejection_bar_low":      candle.low,
                "rejection_bar_close":    candle.close,
                "bbu_setup":              round(fired.bbu_setup, 5),
                "bbl_setup":              round(fired.bbl_setup, 5),
                "bbm_setup":              round((fired.bbu_setup + fired.bbl_setup) / 2, 5),
                "bbu_current":            round(bbu_cur, 5),
                "bbl_current":            round(bbl_cur, 5),
                "bbm_current":            round(bbm_cur, 5),
                "pierce_depth_pips":      round((fired.setup_bar.high - fired.bbu_setup) / PIP_UNITS, 3),
                "rejection_body_pips":    round(body / PIP_UNITS, 3),
                "back_inside_margin_pips": round(back_inside_margin / PIP_UNITS, 3),
                "rejection_window_idx":   window_idx,
                "pierce_thresh_used":     self.pierce_thresh_pips,
                "in_session":             in_session,
            }
            if self._log_writer is not None and (in_session or not self.session_filter):
                # session_filter=True logs only in-session; downstream
                # analysis for a "faithful to Era B" comparison wants
                # in-session candidates.
                self._log_writer.writerow(row)
                self._log_file.flush()
            return row
        except Exception:
            # Fail-safe: never raise. Observation-only must never affect
            # the caller's stream.
            return None


# ─── one-shot replay CLI ────────────────────────────────────────────────

def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace(" ", "T").replace("Z", "+00:00"))


def _iter_candles_from_csv(path: str):
    with open(path) as f:
        for r in csv.DictReader(f):
            yield Candle(
                ts    = _parse_ts(r["timestamp"]),
                open  = float(r["open"]),
                high  = float(r["high"]),
                low   = float(r["low"]),
                close = float(r["close"]),
            )


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candles", required=True, help="CSV with timestamp,open,high,low,close")
    ap.add_argument("--out",     required=True, help="Path to write candidates_log.csv")
    ap.add_argument("--pierce-thresh", type=float, default=PIERCE_THRESH_PIPS_DEFAULT)
    ap.add_argument("--all-sessions", action="store_true",
                    help="Log candidates outside 06-17 UTC too")
    args = ap.parse_args()

    n = 0
    with Detector(log_path=args.out,
                  pierce_thresh_pips=args.pierce_thresh,
                  session_filter=not args.all_sessions) as det:
        for c in _iter_candles_from_csv(args.candles):
            if det.on_bar(c) is not None:
                n += 1
    print(f"wrote {n} candidates to {args.out}")


if __name__ == "__main__":
    _cli()
