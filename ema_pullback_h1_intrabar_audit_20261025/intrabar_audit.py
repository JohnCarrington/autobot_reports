"""M5 intrabar execution audit for 2026-10-23 (read-only).

For each of the 23 setups:
  * Resolve the trigger bar OHLC and the entry level from the replay CSV.
  * Classify whether, under the OWNER'S intended intrabar-detection rule,
    the entry level could have been crossed WITHIN the trigger bar (SELL
    bar.low <= entry; BUY bar.high >= entry). This case is a candidate
    for a one-M5-bar earlier fill under intrabar detection, since the
    current implementation only places the pending stop AFTER the trigger
    bar closes.
  * Record the trigger bar's within-bar OHLC bounds for timing (open ts,
    close ts). The exact intrabar touch moment is UNDETERMINED without
    tick data.
  * For every setup, compute first-touch of the entry level (post-trigger)
    by walking the M5 archive forward.
  * For the six FILLED trades, compute favourable/adverse excursion in
    pips over 5/10/15/20/30-minute windows measured from the simulated
    fill timestamp.

No strategy code is modified. No order placed. No service touched.
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ema_pullback.candle_reader import M5Bar, read_day

ARCHIVE = Path("/opt/tradingbot/data/candles/GBPUSD")
OUT_DIR = Path("/home/autobot/ema_pullback/reports/h1_intrabar_compliance_20261025")
SETUPS_CSV = Path(
    "/home/autobot/ema_pullback/reports/20261025_corrected/"
    "replay_setups_20261025T070353.csv"
)
TARGET_DAY = "2026-10-23"
PIP = 1.0  # GBPUSD 2-dp quote; the archive is in GBPUSD-dp10 scale (per build spec)


@dataclass(frozen=True)
class Setup:
    setup_id: str
    direction: str
    trigger_ts: datetime
    h1_direction: str
    m5_ema8: float
    m5_ema13: float
    m5_ema21: float
    trigger_open: float
    trigger_high: float
    trigger_low: float
    trigger_close: float
    lookback_extreme: float
    entry_level: float
    a_outcome: str
    a_mid_fill_ts: Optional[datetime]
    a_mid_fill_price: Optional[float]
    b_outcome: str
    b_structural_sl: Optional[float]
    b_tp1_price: Optional[float]
    b_final_exit_ts: Optional[datetime]
    b_final_exit_price: Optional[float]
    b_mae_pips: Optional[float]
    b_mfe_pips: Optional[float]


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _opt_dt(s: str) -> Optional[datetime]:
    return _dt(s) if s else None


def _opt_f(s: str) -> Optional[float]:
    return float(s) if s else None


def load_target_day_setups() -> List[Setup]:
    out: List[Setup] = []
    with SETUPS_CSV.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row["trigger_ts"].startswith(TARGET_DAY):
                continue
            out.append(Setup(
                setup_id=row["setup_id"],
                direction=row["direction"],
                trigger_ts=_dt(row["trigger_ts"]),
                h1_direction=row["h1_direction"],
                m5_ema8=float(row["m5_ema8"]),
                m5_ema13=float(row["m5_ema13"]),
                m5_ema21=float(row["m5_ema21"]),
                trigger_open=float(row["trigger_open"]),
                trigger_high=float(row["trigger_high"]),
                trigger_low=float(row["trigger_low"]),
                trigger_close=float(row["trigger_close"]),
                lookback_extreme=float(row["lookback_extreme"]),
                entry_level=float(row["entry_level"]),
                a_outcome=row["a_outcome"],
                a_mid_fill_ts=_opt_dt(row["a_mid_fill_ts"]),
                a_mid_fill_price=_opt_f(row["a_mid_fill_price"]),
                b_outcome=row["b_outcome"],
                b_structural_sl=_opt_f(row["b_structural_sl"]),
                b_tp1_price=_opt_f(row["b_tp1_price"]),
                b_final_exit_ts=_opt_dt(row["b_final_exit_ts"]),
                b_final_exit_price=_opt_f(row["b_final_exit_price"]),
                b_mae_pips=_opt_f(row["b_mae_pips"]),
                b_mfe_pips=_opt_f(row["b_mfe_pips"]),
            ))
    return out


def load_day_bars(day_str: str) -> List[M5Bar]:
    """Load one day's bars tolerant of file errors."""
    d = datetime.fromisoformat(day_str).date()
    return read_day(ARCHIVE, d)


def classify_touch_timing(s: Setup) -> dict:
    """Describe when under the CURRENT implementation the EMA-8 touch is
    recognised vs when under intrabar detection it would be.

    All timestamps are open-stamped (bar labelled T covers [T, T+5m)).

    Current implementation:
      * Trigger bar closes at trigger_ts + 5m.
      * Service polls the archive on cfg.poll_seconds (default 20s).
      * Trigger is detected on the first poll AFTER the archive writer
        appends the completed bar.
      * Order (pending stop) placed at that moment.

    Owner's intended intrabar scheme:
      * Live price touches EMA-8 at some moment within [trigger_ts,
        trigger_ts + 5m). The exact moment is UNDETERMINED without
        tick data; the window must be reported.
    """
    bar_open = s.trigger_ts
    bar_close = s.trigger_ts + timedelta(minutes=5)
    # The CURRENT implementation can only detect at bar_close + ~1 poll.
    current_detect_from = bar_close
    current_detect_to = bar_close + timedelta(seconds=20)  # one poll
    # Intrabar window for the touch: anywhere in [bar_open, bar_close).
    intrabar_from = bar_open
    intrabar_to = bar_close
    # Minimum implementation-induced delay (intrabar vs current):
    # Worst case touch at bar_open → current detects at bar_close + poll.
    # Best case touch at bar_close - epsilon → current detects at
    # bar_close + poll, so the saved time is just the poll latency.
    max_impl_delay = (current_detect_from - intrabar_from).total_seconds()
    min_impl_delay = 0  # if the touch happened at the close moment
    return {
        "intrabar_touch_window_from": intrabar_from.isoformat(),
        "intrabar_touch_window_to":   intrabar_to.isoformat(),
        "current_recognition_from":   current_detect_from.isoformat(),
        "current_recognition_to":     current_detect_to.isoformat(),
        "max_impl_delay_seconds":     max_impl_delay,
        "min_impl_delay_seconds":     min_impl_delay,
    }


def within_trigger_bar_entry_crossed(s: Setup) -> bool:
    """Return True iff the entry level is between the trigger bar's low
    and high (SELL: low <= entry; BUY: high >= entry). This indicates
    that under intrabar detection the entry stop could have been FILLED
    inside the same trigger bar — the earliest-possible intrabar effect.
    Otherwise the fill timing is driven entirely by subsequent price
    action."""
    if s.direction == "SELL":
        return s.trigger_low <= s.entry_level
    if s.direction == "BUY":
        return s.trigger_high >= s.entry_level
    return False


def first_entry_touch(s: Setup, bars: Sequence[M5Bar]) -> Optional[datetime]:
    """Return the ts of the first bar AT OR AFTER the trigger whose range
    crosses the entry level (SELL: low <= entry; BUY: high >= entry).

    Includes the trigger bar itself (relevant under the owner's intrabar
    scheme). The exact intrabar moment is UNDETERMINED without ticks."""
    for b in bars:
        if b.ts < s.trigger_ts:
            continue
        if s.direction == "SELL" and b.low <= s.entry_level:
            return b.ts
        if s.direction == "BUY" and b.high >= s.entry_level:
            return b.ts
    return None


def first_entry_touch_after_trigger(s: Setup, bars: Sequence[M5Bar]) -> Optional[datetime]:
    """Same as first_entry_touch but STRICTLY AFTER the trigger bar
    (what the current implementation effectively tests, since the
    trigger bar is the one being evaluated at its close)."""
    for b in bars:
        if b.ts <= s.trigger_ts:
            continue
        if s.direction == "SELL" and b.low <= s.entry_level:
            return b.ts
        if s.direction == "BUY" and b.high >= s.entry_level:
            return b.ts
    return None


def excursion_from_fill(s: Setup, bars: Sequence[M5Bar], horizon_minutes: int) -> Tuple[Optional[float], Optional[float]]:
    """Return (MFE_pips, MAE_pips) for a filled trade over the next
    `horizon_minutes` after the simulated fill timestamp. MFE/MAE are
    measured against the simulated fill price in direction units; SELL
    MFE is max distance BELOW fill, BUY MFE is max distance ABOVE.
    Returns (None, None) if the trade is not filled or horizon exceeds
    the day's archive."""
    if s.a_mid_fill_ts is None or s.a_mid_fill_price is None:
        return (None, None)
    fill_ts = s.a_mid_fill_ts
    end_ts = fill_ts + timedelta(minutes=horizon_minutes)
    fp = s.a_mid_fill_price
    best_fav = 0.0
    best_adv = 0.0
    saw_any = False
    for b in bars:
        if b.ts < fill_ts:
            continue
        if b.ts >= end_ts:
            break
        saw_any = True
        if s.direction == "SELL":
            fav = fp - b.low
            adv = b.high - fp
        else:  # BUY
            fav = b.high - fp
            adv = fp - b.low
        if fav > best_fav:
            best_fav = fav
        if adv > best_adv:
            best_adv = adv
    if not saw_any:
        return (None, None)
    return (round(best_fav / PIP, 2), round(best_adv / PIP, 2))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    setups = load_target_day_setups()
    # Need bars up to 1 hour after the last setup to compute excursions.
    day_bars = load_day_bars(TARGET_DAY)
    # Also load the next day in case fills roll into Mon (no bars Sat/Sun in GBPUSD archive here).
    next_day = (datetime.fromisoformat(TARGET_DAY).date() + timedelta(days=1)).isoformat()
    next_bars: List[M5Bar] = []
    try:
        next_bars = load_day_bars(next_day)
    except Exception:
        pass
    all_bars = sorted(day_bars + next_bars, key=lambda b: b.ts)

    reconstruction_path = OUT_DIR / "FRIDAY_SETUP_RECONSTRUCTION.csv"
    fieldnames = [
        "setup_id", "direction", "trigger_ts",
        "h1_direction",
        "intrabar_touch_window_from",
        "intrabar_touch_window_to",
        "current_recognition_from",
        "current_recognition_to",
        "max_impl_delay_seconds",
        "within_trigger_bar_entry_crossed",
        "trigger_bar_low", "trigger_bar_high",
        "entry_level",
        "first_entry_touch_including_trigger",
        "first_entry_touch_after_trigger",
        "a_outcome",
        "replay_fill_ts",
        "replay_fill_price",
        "fill_delay_minutes_from_trigger_open",
        "fill_delay_minutes_from_trigger_close",
        "fill_delay_bars",
        "mfe_5m_pips", "mae_5m_pips",
        "mfe_10m_pips", "mae_10m_pips",
        "mfe_15m_pips", "mae_15m_pips",
        "mfe_20m_pips", "mae_20m_pips",
        "mfe_30m_pips", "mae_30m_pips",
        "delay_root_cause",
    ]
    with reconstruction_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for s in setups:
            touch = classify_touch_timing(s)
            crossed_in_trigger = within_trigger_bar_entry_crossed(s)
            fe_incl = first_entry_touch(s, all_bars)
            fe_after = first_entry_touch_after_trigger(s, all_bars)
            fill_ts = s.a_mid_fill_ts
            mfe5, mae5 = excursion_from_fill(s, all_bars, 5)
            mfe10, mae10 = excursion_from_fill(s, all_bars, 10)
            mfe15, mae15 = excursion_from_fill(s, all_bars, 15)
            mfe20, mae20 = excursion_from_fill(s, all_bars, 20)
            mfe30, mae30 = excursion_from_fill(s, all_bars, 30)

            delay_bars = None
            delay_from_open = None
            delay_from_close = None
            if fill_ts is not None:
                delay_from_open = (fill_ts - s.trigger_ts).total_seconds() / 60.0
                delay_from_close = (fill_ts - (s.trigger_ts + timedelta(minutes=5))).total_seconds() / 60.0
                delay_bars = int(delay_from_close // 5)
            # Delay root cause classifier (filled only):
            cause = ""
            if fill_ts is None:
                cause = "cancelled_before_fill"
            else:
                # Minimum delay the current implementation imposes: between the
                # intrabar touch moment and the FIRST completed-bar fill
                # check — i.e. 1 bar (5 min) worst case + poll latency.
                # If the entry level is crossed WITHIN the trigger bar, the
                # current implementation CANNOT fill until trigger_ts + 10m
                # (the trigger bar is the one being evaluated, and the fill
                # check runs on the NEXT completed bar).
                # If NOT crossed within trigger bar, delay beyond 5 min is
                # pure price action (price didn't reach entry).
                if crossed_in_trigger:
                    cause = ("implementation_delay_at_least_5m: entry level was "
                             "crossed WITHIN the trigger bar but fill check only "
                             "runs on the NEXT completed M5 bar")
                else:
                    # Price did not reach entry inside the trigger bar.
                    # Fill delay beyond ~5 min is price-driven.
                    if delay_from_close is not None and delay_from_close <= 5.0:
                        cause = "price_reached_entry_on_first_bar_after_trigger_close"
                    else:
                        extra = max(0.0, delay_from_close - 5.0)
                        cause = (f"price_action_delay: entry not reached inside "
                                 f"trigger bar; additional {extra:.0f} min wait for "
                                 f"price to touch entry")

            w.writerow({
                "setup_id": s.setup_id,
                "direction": s.direction,
                "trigger_ts": s.trigger_ts.isoformat(),
                "h1_direction": s.h1_direction,
                "intrabar_touch_window_from": touch["intrabar_touch_window_from"],
                "intrabar_touch_window_to":   touch["intrabar_touch_window_to"],
                "current_recognition_from":   touch["current_recognition_from"],
                "current_recognition_to":     touch["current_recognition_to"],
                "max_impl_delay_seconds":     touch["max_impl_delay_seconds"],
                "within_trigger_bar_entry_crossed": crossed_in_trigger,
                "trigger_bar_low": s.trigger_low,
                "trigger_bar_high": s.trigger_high,
                "entry_level": s.entry_level,
                "first_entry_touch_including_trigger": fe_incl.isoformat() if fe_incl else "",
                "first_entry_touch_after_trigger": fe_after.isoformat() if fe_after else "",
                "a_outcome": s.a_outcome,
                "replay_fill_ts": fill_ts.isoformat() if fill_ts else "",
                "replay_fill_price": s.a_mid_fill_price if s.a_mid_fill_price is not None else "",
                "fill_delay_minutes_from_trigger_open": f"{delay_from_open:.1f}" if delay_from_open is not None else "",
                "fill_delay_minutes_from_trigger_close": f"{delay_from_close:.1f}" if delay_from_close is not None else "",
                "fill_delay_bars": delay_bars if delay_bars is not None else "",
                "mfe_5m_pips": mfe5 if mfe5 is not None else "",
                "mae_5m_pips": mae5 if mae5 is not None else "",
                "mfe_10m_pips": mfe10 if mfe10 is not None else "",
                "mae_10m_pips": mae10 if mae10 is not None else "",
                "mfe_15m_pips": mfe15 if mfe15 is not None else "",
                "mae_15m_pips": mae15 if mae15 is not None else "",
                "mfe_20m_pips": mfe20 if mfe20 is not None else "",
                "mae_20m_pips": mae20 if mae20 is not None else "",
                "mfe_30m_pips": mfe30 if mfe30 is not None else "",
                "mae_30m_pips": mae30 if mae30 is not None else "",
                "delay_root_cause": cause,
            })

    # Also produce a plain-text per-fill forensic analysis for the six
    # filled trades, matching the brief's §8 columns.
    with (OUT_DIR / "SIX_FILL_INTRABAR_FORENSIC.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "trigger_ts", "direction",
            "trigger_bar_low", "trigger_bar_high",
            "entry_level",
            "within_trigger_bar_entry_crossed",
            "intrabar_touch_window_from", "intrabar_touch_window_to",
            "earliest_possible_intrabar_fill_bar",
            "current_fill_bar", "current_fill_price",
            "fill_delay_from_trigger_open_min",
            "fill_delay_from_trigger_close_min",
            "fill_delay_bars_after_close",
            "a_outcome", "b_outcome",
            "b_mae_pips", "b_mfe_pips",
            "mfe_15m", "mae_15m", "mfe_30m", "mae_30m",
            "delay_root_cause",
        ])
        for s in setups:
            if s.a_mid_fill_ts is None:
                continue
            fe_incl = first_entry_touch(s, all_bars)
            touch = classify_touch_timing(s)
            crossed_in_trigger = within_trigger_bar_entry_crossed(s)
            mfe15, mae15 = excursion_from_fill(s, all_bars, 15)
            mfe30, mae30 = excursion_from_fill(s, all_bars, 30)
            delay_from_open = (s.a_mid_fill_ts - s.trigger_ts).total_seconds() / 60.0
            delay_from_close = (s.a_mid_fill_ts - (s.trigger_ts + timedelta(minutes=5))).total_seconds() / 60.0
            delay_bars = int(delay_from_close // 5)
            if crossed_in_trigger:
                cause = "intrabar_fill_possible: entry crossed within trigger bar; current impl waits 1 more bar"
            else:
                extra = max(0.0, delay_from_close - 5.0)
                cause = f"price_action_delay: {extra:.0f}m waiting for price to touch entry"
            w.writerow([
                s.trigger_ts.isoformat(), s.direction,
                s.trigger_low, s.trigger_high,
                s.entry_level, crossed_in_trigger,
                touch["intrabar_touch_window_from"], touch["intrabar_touch_window_to"],
                fe_incl.isoformat() if fe_incl else "",
                s.a_mid_fill_ts.isoformat(), s.a_mid_fill_price,
                f"{delay_from_open:.1f}", f"{delay_from_close:.1f}", delay_bars,
                s.a_outcome, s.b_outcome,
                s.b_mae_pips if s.b_mae_pips is not None else "",
                s.b_mfe_pips if s.b_mfe_pips is not None else "",
                mfe15 if mfe15 is not None else "",
                mae15 if mae15 is not None else "",
                mfe30 if mfe30 is not None else "",
                mae30 if mae30 is not None else "",
                cause,
            ])

    print(f"wrote {reconstruction_path}")
    print(f"wrote {OUT_DIR / 'SIX_FILL_INTRABAR_FORENSIC.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
