"""Era B pierce + rejection-close entry detector for GBPUSD_BB_BOUNCE_S.

Implements spec §2 verbatim:
  - Bar N-1 setup:  high >= BBU(N-1) + PIERCE_THRESH_PIPS  AND  open <= BBU(N-1)
    (with mirror LONG side — this benchmark implements SHORT only)
  - Rejection candle at bar N, N+1, or N+2 (REJECTION_WINDOW_BARS = 3):
      body |close-open| >= MIN_REJECTION_BODY_PIPS
      close < open (bearish body, SHORT)
      close <= BBU(current) + REJECTION_TOLERANCE_PIPS
      (uses the CURRENT bar's BBU, not the setup-bar's stale BBU)
  - Entry: MARKET SELL at cur.close on the rejection bar

No orchestrator gates, no cascade-disagree, no regime consult, no
counter-H1, no news blackout, no velocity guard, no ARM_AND_WAIT.
Those gates were live in Era B but their algorithms are not fully
specified — they are flagged in config.UNKNOWNS and expected to be the
source of the benchmark's false-positive fires vs the ledger.

IG order submission is not imported here. The detector emits Signal
objects; the runner decides what to do with them.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from . import config
from .candles import Bar


# ─── data classes ───────────────────────────────────────────────────────

@dataclass
class ArmedSetup:
    setup_ts:  datetime   # bar OPEN time of setup bar N-1
    direction: str        # "LONG" | "SHORT"
    bbl_setup: float      # BBL frozen at setup bar close
    bbu_setup: float      # BBU frozen at setup bar close
    setup_bar: Bar


@dataclass
class Signal:
    ts_utc:              datetime   # rejection bar CLOSE time (= entry ts)
    direction:           str        # "SELL" | "BUY"
    entry_price:         float
    sl_pips:             float
    tp_pips:             float
    setup_bar:           Bar
    rejection_bar:       Bar
    rejection_window_idx: int       # 1..REJECTION_WINDOW_BARS (which bar caught it)
    bbu_setup:           float
    bbl_setup:           float
    bbu_current:         float
    bbl_current:         float
    strategy:            str = "GBPUSD_BB_BOUNCE_S"
    size:                float = 1.0


# ─── indicators ─────────────────────────────────────────────────────────

def bb_20_2(closes: List[float], length: int = config.BB_LEN,
            std_mult: float = config.BB_STD) -> Optional[tuple]:
    """Return (bbl, bbm, bbu) for the last bar in closes. None if
    closes has fewer than `length` samples."""
    if len(closes) < length:
        return None
    window = closes[-length:]
    mean = sum(window) / length
    # sample std (N-1) matches numpy default ddof=1; but the actual
    # code uses statistics.pstdev-equivalent (population std). Both
    # give values within a fraction of a pip on GBPUSD 5m. Use pstdev
    # to match the reference implementation more closely.
    var = sum((x - mean) ** 2 for x in window) / length
    sd = math.sqrt(var)
    return (mean - std_mult * sd, mean, mean + std_mult * sd)


# ─── setup + rejection tests ────────────────────────────────────────────

def detect_pierce_setup(prev: Bar, bbl_prev: float, bbu_prev: float,
                        pierce_thresh_pips: float) -> Optional[str]:
    """SHORT setup only (LONG mirror not needed for BB_BOUNCE_S).
    Returns 'SHORT' if the bar is a pierce setup, else None.

    Spec §2.3:
      SHORT setup: prev.high >= bbu_prev + PIERCE_THRESH_PIPS
                    AND prev.open <= bbu_prev
                    AND NOT both-band pierce (excluded here as a matter
                        of course — a bar that pierces BOTH sides is a
                        squeeze-hug, not a clean pierce).
    """
    thresh_price = pierce_thresh_pips * config.PIP_UNITS
    long_pierce  = (bbl_prev - prev.low)  >= thresh_price
    short_pierce = (prev.high - bbu_prev) >= thresh_price
    if long_pierce and short_pierce:
        return None
    if not short_pierce:
        return None
    if prev.open > bbu_prev:
        return None
    return "SHORT"


def is_rejection(cur: Bar, direction: str,
                 bbu_current: float, bbl_current: float) -> bool:
    """Spec §2.4:
      SHORT rejection: body >= MIN_REJECTION_BODY_PIPS
                       AND close < open (bearish)
                       AND close <= bbu_current + REJECTION_TOLERANCE_PIPS

      LONG mirror (not exercised in this benchmark).
    """
    body = abs(cur.close - cur.open)
    if body < config.MIN_REJECTION_BODY_PIPS * config.PIP_UNITS:
        return False
    tol_price = config.REJECTION_TOLERANCE_PIPS * config.PIP_UNITS
    if direction == "SHORT":
        return cur.close < cur.open and cur.close <= bbu_current + tol_price
    return cur.close > cur.open and cur.close >= bbl_current - tol_price


# ─── detector ───────────────────────────────────────────────────────────

class EraBEntryDetector:
    """Bar-by-bar detector. Feed candles via .on_bar(); collect Signal
    objects from .signals(). Stateful per instance."""

    def __init__(self, pierce_thresh_pips: float = config.PIERCE_THRESH_PIPS_DEFAULT):
        self.pierce_thresh_pips = pierce_thresh_pips
        self._closes: List[float] = []
        self._armed: List[ArmedSetup] = []
        self._bars_seen: List[Bar] = []       # sliding buffer of BB_LEN+2 bars
        self._signals: List[Signal] = []

    # ------------------------------------------------------------------

    def _in_window(self, ts: datetime) -> bool:
        if ts.weekday() >= 5:
            return False
        t = ts.time()
        return config.WIN_START <= t < config.WIN_END

    def _age_bars(self, s: ArmedSetup, now_bar: Bar) -> float:
        # 5m-aligned bar timestamps; age is (now_open - setup_open) / 5min.
        return (now_bar.ts - s.setup_ts).total_seconds() / 300.0

    def on_bar(self, cur: Bar) -> Optional[Signal]:
        """Consume one 5m bar (bar N, with bar N-1 already ingested).
        Returns a Signal if a fire happens on this bar, else None.
        """
        self._closes.append(cur.close)
        self._bars_seen.append(cur)
        # Trim buffers to what we need
        keep = config.BB_LEN + 5
        if len(self._closes) > keep:
            self._closes = self._closes[-keep:]
            self._bars_seen = self._bars_seen[-keep:]

        # 1) BB at current bar
        cur_bb = bb_20_2(self._closes)
        if cur_bb is None:
            return None
        bbl_cur, bbm_cur, bbu_cur = cur_bb

        # 2) Expire armed setups older than REJECTION_WINDOW_BARS
        self._armed = [s for s in self._armed
                       if self._age_bars(s, cur) <= float(config.REJECTION_WINDOW_BARS) + 1e-3]

        # 3) Try setup detection on bar N-1 (the second-to-last bar in buffer).
        #    On the very next call (bar N) this new setup is checked as a
        #    same-bar rejection — matches the spec (bar N can fire when
        #    N-1 was the setup AND N is the rejection).
        if len(self._bars_seen) >= 2:
            prev_bar = self._bars_seen[-2]
            # BB at the setup bar (i.e., at its close, which needs BB_LEN closes
            # ending at prev_bar.close). Use the closes list minus the current bar.
            setup_closes = self._closes[:-1]
            setup_bb = bb_20_2(setup_closes)
            if setup_bb is not None:
                bbl_prev, _bbm_prev, bbu_prev = setup_bb
                sig_dir = detect_pierce_setup(prev_bar, bbl_prev, bbu_prev,
                                              self.pierce_thresh_pips)
                if sig_dir == "SHORT":
                    # Dedup: don't arm the same setup twice
                    if not any(s.setup_ts == prev_bar.ts and s.direction == "SHORT"
                               for s in self._armed):
                        self._armed.append(ArmedSetup(
                            setup_ts=prev_bar.ts,
                            direction="SHORT",
                            bbl_setup=bbl_prev,
                            bbu_setup=bbu_prev,
                            setup_bar=prev_bar,
                        ))

        # 4) Test cur bar as a rejection for each armed SHORT setup.
        #    Order by oldest first — matches spec §2.5 which selects
        #    max(_age_bars) (oldest).
        short_matches = [s for s in self._armed
                         if s.direction == "SHORT"
                         and is_rejection(cur, "SHORT", bbu_cur, bbl_cur)]
        if not short_matches:
            return None

        fired = max(short_matches, key=lambda s: self._age_bars(s, cur))
        # Session filter: entry ts = bar close = cur.close_ts. But the
        # actual code checks self._in_window(cur.timestamp) i.e. the bar
        # OPEN time. Match that.
        if not self._in_window(cur.ts):
            # Not a fire; leave armed setups in place for the next in-window bar.
            return None

        # 5) Fire — consume all SHORT setups (spec §2.5 note on consuming
        #    all setups of the firing direction).
        self._armed = [s for s in self._armed if s.direction != "SHORT"]

        window_idx = int(round(self._age_bars(fired, cur)))
        if window_idx < 1:
            window_idx = 1

        sig = Signal(
            ts_utc               = cur.close_ts,
            direction            = "SELL",
            entry_price          = cur.close,
            sl_pips              = config.SL_PIPS,
            tp_pips              = config.BROKER_TP_PIPS,
            setup_bar            = fired.setup_bar,
            rejection_bar        = cur,
            rejection_window_idx = window_idx,
            bbu_setup            = fired.bbu_setup,
            bbl_setup            = fired.bbl_setup,
            bbu_current          = bbu_cur,
            bbl_current          = bbl_cur,
        )
        self._signals.append(sig)
        return sig

    def signals(self) -> List[Signal]:
        return list(self._signals)
