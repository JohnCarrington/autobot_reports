"""Addendum M — market reconstruction, count enumeration and outcome tracking.

For each forecast in the evidence register, this script:

  (1) loads completed M5 candles up to the publication timestamp (no look-ahead)
  (2) derives H1 / H4 / D1 bars from the M5 archive
  (3) computes directional structure, consecutive-candle counts, MACD / RSI /
      ATR / Bollinger measurements, and candle-shape features
  (4) enumerates eight candidate exhaustion-count interpretations on each
      timeframe (so Phase 3 can compare against PIA's counts IF they ever
      surface — presently all PIA counts are UNAVAILABLE)
  (5) measures what price did after publication: did the entry fill, did
      the primary / extended target hit, did the stop hit, max favourable
      and adverse excursion, time to each event.

Outputs three CSVs under ../csv/.

No production code is modified. No orders are placed. No network calls.
"""
from __future__ import annotations

import csv
import math
import pathlib
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSV_DIR = ROOT / "csv"
CANDLES_2026 = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")

# ------------------------------------------------------------
# Forecast ledger — what we are able to reconstruct market for
# ------------------------------------------------------------
# Timestamps in UTC. 4 Nov 07:58 UK = 07:58 UTC (BST ended 2026-10-26).
# Others are assumed 07:00 UTC — the Addendum F convention. The assumption
# is flagged explicitly in the register and here.
#
# `thesis_id` collapses operator-identified repeat publications (T1 has two
# calendar dates but one thesis). `repeat_of` is None for the first
# publication of a thesis.
FORECASTS = [
    dict(id="T1a", thesis="T1", date="2026-10-28", pub="2026-10-28T07:00:00+00:00",
         direction="BUY", entry=1.3300, stop=1.3275, tgt1=1.3375, tgt2=1.3400,
         confidence=None, repeat_of=None,
         note="Addendum F ledger. No commentary. Treated as the first publication of the T1 thesis."),
    dict(id="T1b", thesis="T1", date="2026-10-29", pub="2026-10-29T07:00:00+00:00",
         direction="BUY", entry=1.3300, stop=1.3275, tgt1=1.3375, tgt2=1.3400,
         confidence=None, repeat_of="T1a",
         note="Repeat of T1 thesis — not an independent observation."),
    dict(id="T2a", thesis="T2", date="2026-10-30", pub="2026-10-30T07:00:00+00:00",
         direction="BUY", entry=1.3350, stop=1.3325, tgt1=1.3425, tgt2=1.3450,
         confidence=None, repeat_of=None,
         note="First publication of the T2 thesis."),
    dict(id="T2b", thesis="T2", date="2026-11-02", pub="2026-11-02T07:00:00+00:00",
         direction="BUY", entry=1.3350, stop=1.3325, tgt1=1.3425, tgt2=1.3450,
         confidence=None, repeat_of="T2a",
         note="Repeat of T2 thesis — not an independent observation."),
    dict(id="T3",  thesis="T3", date="2026-11-03", pub="2026-11-03T07:00:00+00:00",
         direction="SELL", entry=1.3442, stop=1.3485, tgt1=1.3313, tgt2=None,
         confidence=None, repeat_of=None,
         note="First reversal call after the 4-day BUY run. Presumptive exhaustion read; no commentary preserved."),
    dict(id="T4",  thesis="T4", date="2026-11-04", pub="2026-11-04T07:58:00+00:00",
         direction="BUY", entry=1.3431, stop=1.3381, tgt1=1.3581, tgt2=None,
         confidence=40, repeat_of=None,
         note="Full commentary preserved: PIA states NO exhaustion ('no clear indication that the upward move is coming to an end')."),
    # --- v2 corpus (operator-supplied verbatim 2026-11-17) -------------
    # Candle archive ends 2026-11-06T18:00Z so build_market_row / outcome /
    # count rows return a NO_CANDLE_DATA placeholder for everything from
    # 2026-11-10 onwards. The forecasts are still included so the register
    # and schema of the output CSVs stay consistent with the brief's
    # comparison table (4 / 11 / 13 / 16 / 17 Nov).
    dict(id="T5",  thesis="T5", date="2026-11-10", pub="2026-11-10T08:36:00+00:00",
         direction="SELL", entry=1.3529, stop=1.3572, tgt1=1.3411, tgt2=None,
         confidence=60, repeat_of=None,
         note="DATE PROVISIONAL per operator. Full commentary: 'sell into rallies', 'trend line resistance 13532', 'temporary move higher'. No market reconstruction possible — archive ends 2026-11-06."),
    dict(id="T6",  thesis="T6", date="2026-11-11", pub="2026-11-11T07:25:00+00:00",
         direction="BUY", entry=1.3295, stop=1.3256, tgt1=1.3406, tgt2=None,
         confidence=60, repeat_of=None,
         note="Full commentary. DIRECTION CHANGE SELL→BUY within 1 day of T5. PIA cites 'forming a bottom' + 'weekly pivot at 13295'. No market reconstruction possible."),
    dict(id="T7",  thesis="T7", date="2026-11-13", pub="2026-11-13T07:25:00+00:00",
         direction="SELL", entry=1.3290, stop=1.3329, tgt1=1.3179, tgt2=None,
         confidence=60, repeat_of=None,
         note="Full commentary. DIRECTION CHANGE BUY→SELL within 2 days of T6. PIA explicitly names trigger: 'Previous support level of 13277 broken' — STRUCTURAL break, not exhaustion. No market reconstruction possible."),
    dict(id="T8",  thesis="T8", date="2026-11-16", pub="2026-11-16T07:42:00+00:00",
         direction="SELL", entry=1.3273, stop=1.3311, tgt1=1.3165, tgt2=None,
         confidence=60, repeat_of="T7",
         note="Full commentary. Core Phase 4 observation: 'Although the bears are in control, the stalling negative momentum indicates a turnaround is possible' — exhaustion present + SELL maintained. No market reconstruction possible."),
    dict(id="T9",  thesis="T9", date="2026-11-17", pub="2026-11-17T07:32:00+00:00",
         direction="SELL", entry=1.3245, stop=1.3283, tgt1=1.3138, tgt2=None,
         confidence=60, repeat_of="T7",
         note="Full commentary. Continuation of T7/T8 thesis. 'Bespoke resistance 13245' — entry sits exactly at the stated resistance. No market reconstruction possible."),
]

# ------------------------------------------------------------
# Candle loading
# ------------------------------------------------------------

@dataclass(frozen=True)
class Candle:
    ts: datetime
    o: float
    h: float
    l: float
    c: float

def load_m5(start: datetime, end: datetime) -> list[Candle]:
    """Read completed M5 bars from the daily CSV archive, inclusive window.

    Prices in archive are stored on a ×10000 scale (13320.00 == 1.33200).
    We divide back to decimal immediately.
    """
    out: list[Candle] = []
    day = start.date()
    last_day = end.date()
    while day <= last_day:
        path = CANDLES_2026 / f"{day.isoformat()}.csv"
        if path.exists():
            with path.open() as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                for row in reader:
                    if not row:
                        continue
                    ts = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                    if ts < start or ts >= end:
                        continue
                    out.append(Candle(ts=ts,
                                      o=float(row[1]) / 10000.0,
                                      h=float(row[2]) / 10000.0,
                                      l=float(row[3]) / 10000.0,
                                      c=float(row[4]) / 10000.0))
        day = day + timedelta(days=1)
    out.sort(key=lambda c: c.ts)
    return out

def resample(m5: list[Candle], bucket_minutes: int) -> list[Candle]:
    """Bucket-align M5 bars into H1 / H4 / D1. Only emit COMPLETE buckets."""
    if not m5:
        return []
    bucket_s = bucket_minutes * 60
    out: list[Candle] = []
    cur_bucket_start: Optional[datetime] = None
    o = h = l = c = 0.0
    bars_in_bucket = 0
    expected_bars = bucket_minutes // 5
    for bar in m5:
        bucket_epoch = (int(bar.ts.timestamp()) // bucket_s) * bucket_s
        bucket_start = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
        if bucket_start != cur_bucket_start:
            if cur_bucket_start is not None and bars_in_bucket == expected_bars:
                out.append(Candle(ts=cur_bucket_start, o=o, h=h, l=l, c=c))
            cur_bucket_start = bucket_start
            o = bar.o
            h = bar.h
            l = bar.l
            c = bar.c
            bars_in_bucket = 1
        else:
            h = max(h, bar.h)
            l = min(l, bar.l)
            c = bar.c
            bars_in_bucket += 1
    if cur_bucket_start is not None and bars_in_bucket == expected_bars:
        out.append(Candle(ts=cur_bucket_start, o=o, h=h, l=l, c=c))
    return out

def resample_d1(m5: list[Candle]) -> list[Candle]:
    """Daily bars UTC-aligned. Emit completed days only (relative to provided m5)."""
    if not m5:
        return []
    by_day: dict[str, list[Candle]] = {}
    for bar in m5:
        by_day.setdefault(bar.ts.date().isoformat(), []).append(bar)
    out: list[Candle] = []
    last_day = m5[-1].ts.date()
    for day_iso, bars in sorted(by_day.items()):
        d = datetime.fromisoformat(day_iso).date()
        if d == last_day:
            # Partial — the publication day. Exclude.
            continue
        bars.sort(key=lambda b: b.ts)
        out.append(Candle(ts=datetime.fromisoformat(day_iso).replace(tzinfo=timezone.utc),
                          o=bars[0].o, h=max(b.h for b in bars),
                          l=min(b.l for b in bars), c=bars[-1].c))
    return out

# ------------------------------------------------------------
# Indicators
# ------------------------------------------------------------

def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(out[-1] + k * (v - out[-1]))
    # pad left with None so index matches input length
    return [None] * (period - 1) + out  # type: ignore

def rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        avg_g = (avg_g * (period - 1) + max(diff, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-diff, 0.0)) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))

def macd(closes: list[float]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (macd_line, signal, histogram) at the last bar using 12/26/9."""
    if len(closes) < 35:
        return None, None, None
    e12 = ema(closes, 12)
    e26 = ema(closes, 26)
    macd_line = [a - b if (a is not None and b is not None) else None
                 for a, b in zip(e12, e26)]
    non_null = [v for v in macd_line if v is not None]
    sig = ema(non_null, 9)
    return (macd_line[-1],
            sig[-1] if sig else None,
            (macd_line[-1] - sig[-1]) if (sig and sig[-1] is not None and macd_line[-1] is not None) else None)

def atr(bars: list[Candle], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i].h, bars[i].l, bars[i - 1].c
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    # Wilder's smoothing
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a

def bollinger(closes: list[float], period: int = 20, mult: float = 2.0):
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    sd = math.sqrt(var)
    return mean, mean + mult * sd, mean - mult * sd

# ------------------------------------------------------------
# Count candidates (Phase 3)
# ------------------------------------------------------------

def consecutive_direction(bars: list[Candle]) -> tuple[int, str]:
    """Longest tail-run of same-signed bodies (close > open = UP, else DOWN)."""
    if not bars:
        return 0, "NONE"
    direction = "UP" if bars[-1].c > bars[-1].o else ("DOWN" if bars[-1].c < bars[-1].o else "FLAT")
    if direction == "FLAT":
        return 0, "FLAT"
    n = 0
    for b in reversed(bars):
        d = "UP" if b.c > b.o else ("DOWN" if b.c < b.o else "FLAT")
        if d != direction:
            break
        n += 1
    return n, direction

def consecutive_higher_closes(bars: list[Candle]) -> int:
    if len(bars) < 2:
        return 0
    n = 0
    for i in range(len(bars) - 1, 0, -1):
        if bars[i].c > bars[i - 1].c:
            n += 1
        else:
            break
    return n

def consecutive_lower_closes(bars: list[Candle]) -> int:
    if len(bars) < 2:
        return 0
    n = 0
    for i in range(len(bars) - 1, 0, -1):
        if bars[i].c < bars[i - 1].c:
            n += 1
        else:
            break
    return n

def consecutive_new_highs(bars: list[Candle]) -> int:
    if len(bars) < 2:
        return 0
    n = 0
    for i in range(len(bars) - 1, 0, -1):
        if bars[i].h > bars[i - 1].h:
            n += 1
        else:
            break
    return n

def consecutive_new_lows(bars: list[Candle]) -> int:
    if len(bars) < 2:
        return 0
    n = 0
    for i in range(len(bars) - 1, 0, -1):
        if bars[i].l < bars[i - 1].l:
            n += 1
        else:
            break
    return n

def td_setup_count(bars: list[Candle]) -> tuple[int, str]:
    """TD Sequential 'setup' count ending at the last bar.

    Buy setup: count of consecutive bars whose close < close[-4].
    Sell setup: count of consecutive bars whose close > close[-4].
    Capped at 9 per the published algorithm (we report the raw count
    so a value of 10+ can appear — Phase 3 will discuss).
    """
    if len(bars) < 5:
        return 0, "NONE"
    last = bars[-1]
    # Which side is the current bar on?
    four_back = bars[-5]
    if last.c < four_back.c:
        side = "BUY_SETUP"  # price-is-down → TD counts down for a prospective BUY signal
        cmp = lambda a, b: a < b
    elif last.c > four_back.c:
        side = "SELL_SETUP"
        cmp = lambda a, b: a > b
    else:
        return 0, "NONE"
    n = 0
    for i in range(len(bars) - 1, 3, -1):
        if cmp(bars[i].c, bars[i - 4].c):
            n += 1
        else:
            break
    return n, side

def completed_swings(bars: list[Candle], threshold_pips: float = 15.0) -> int:
    """Confirmed zig-zag swings in the series using a tail-reversal
    threshold (pips, GBPUSD 1p = 0.0001). Returns the total swing count
    confirmed before the final bar."""
    if len(bars) < 3:
        return 0
    tol = threshold_pips / 10000.0
    swings = 0
    hi = lo = bars[0].c
    hi_t = lo_t = bars[0].ts
    direction = 0  # 0 unknown, 1 up, -1 down
    for b in bars[1:]:
        if direction >= 0 and b.h > hi:
            hi = b.h
            hi_t = b.ts
        if direction <= 0 and b.l < lo:
            lo = b.l
            lo_t = b.ts
        if direction != -1 and (hi - b.l) >= tol and hi_t < b.ts:
            # UP swing confirmed
            swings += 1
            direction = -1
            lo = b.l
            lo_t = b.ts
        elif direction != 1 and (b.h - lo) >= tol and lo_t < b.ts:
            swings += 1
            direction = 1
            hi = b.h
            hi_t = b.ts
    return swings

# ------------------------------------------------------------
# Market-condition row builder
# ------------------------------------------------------------

STALENESS_LIMIT_MIN = 30.0  # last bar must be within 30 minutes of publication

def build_market_row(f: dict) -> dict:
    pub = datetime.fromisoformat(f["pub"])
    # Load 30 days of M5 preceding publication — enough for D1(20), H4(20), H1(50).
    m5 = load_m5(pub - timedelta(days=30), pub)
    if not m5:
        return dict(id=f["id"], date=f["date"], pub_utc=f["pub"], note="NO CANDLE DATA")
    # Staleness gate: candle archive ends 2026-11-06T18:00Z. Any publication
    # whose last preceding M5 bar is >STALENESS_LIMIT_MIN minutes before
    # the publication means we don't have usable publication-time state.
    stale_min = (pub - m5[-1].ts).total_seconds() / 60.0
    if stale_min > STALENESS_LIMIT_MIN:
        return dict(id=f["id"], date=f["date"], pub_utc=f["pub"], direction=f["direction"],
                    note=f"NO_CANDLE_DATA (last bar {m5[-1].ts.isoformat()}, {stale_min/1440:.1f}d stale)")
    h1 = resample(m5, 60)
    h4 = resample(m5, 240)
    d1 = resample_d1(m5)

    def block(bars: list[Candle], label: str) -> dict:
        if not bars:
            return {f"{label}_n_bars": 0}
        closes = [b.c for b in bars]
        last = bars[-1]
        macd_line, sig, hist = macd(closes)
        r = rsi(closes)
        a = atr(bars)
        bb_mid, bb_up, bb_lo = bollinger(closes)
        ema20_pad = ema(closes, 20)
        ema50_pad = ema(closes, 50)
        ema20 = ema20_pad[-1] if ema20_pad else None
        ema50 = ema50_pad[-1] if ema50_pad else None
        # Directional structure: higher-highs / higher-lows over last 5 bars
        tail = bars[-5:]
        hhs = sum(1 for i in range(1, len(tail)) if tail[i].h > tail[i - 1].h)
        lls = sum(1 for i in range(1, len(tail)) if tail[i].l < tail[i - 1].l)
        return {
            f"{label}_n_bars": len(bars),
            f"{label}_last_close": round(last.c, 5),
            f"{label}_last_body_pips": round((last.c - last.o) * 10000, 2),
            f"{label}_last_upper_wick_pips": round((last.h - max(last.o, last.c)) * 10000, 2),
            f"{label}_last_lower_wick_pips": round((min(last.o, last.c) - last.l) * 10000, 2),
            f"{label}_rsi14": round(r, 2) if r is not None else None,
            f"{label}_macd_line_pips": round(macd_line * 10000, 2) if macd_line is not None else None,
            f"{label}_macd_signal_pips": round(sig * 10000, 2) if sig is not None else None,
            f"{label}_macd_hist_pips": round(hist * 10000, 2) if hist is not None else None,
            f"{label}_atr14_pips": round(a * 10000, 2) if a is not None else None,
            f"{label}_bb20_mid": round(bb_mid, 5) if bb_mid is not None else None,
            f"{label}_bb20_width_pips": round((bb_up - bb_lo) * 10000, 2) if (bb_up is not None and bb_lo is not None) else None,
            f"{label}_close_vs_bbmid_pips": round((last.c - bb_mid) * 10000, 2) if bb_mid is not None else None,
            f"{label}_ema20": round(ema20, 5) if ema20 is not None else None,
            f"{label}_close_vs_ema20_pips": round((last.c - ema20) * 10000, 2) if ema20 is not None else None,
            f"{label}_ema50": round(ema50, 5) if ema50 is not None else None,
            f"{label}_close_vs_ema50_pips": round((last.c - ema50) * 10000, 2) if ema50 is not None else None,
            f"{label}_hh_last5": hhs,
            f"{label}_ll_last5": lls,
        }

    row = dict(
        id=f["id"], date=f["date"], pub_utc=f["pub"], direction=f["direction"],
        thesis=f["thesis"], repeat_of=(f["repeat_of"] or ""),
        m5_bars_loaded=len(m5),
    )
    row.update(block(h1, "H1"))
    row.update(block(h4, "H4"))
    row.update(block(d1, "D1"))

    # Spot (last completed M5 close)
    last_m5 = m5[-1]
    row["spot_at_publish"] = round(last_m5.c, 5)
    row["pub_minus_lastbar_minutes"] = round((pub - last_m5.ts).total_seconds() / 60.0, 1)

    # Distance from entry / stop / target at publication
    row["entry_distance_pips"] = round((last_m5.c - f["entry"]) * 10000, 2)
    row["stop_distance_pips"] = round((f["entry"] - f["stop"]) * 10000, 2) * (1 if f["direction"] == "BUY" else -1)
    row["target1_distance_pips"] = round((f["tgt1"] - f["entry"]) * 10000, 2)
    row["target2_distance_pips"] = round((f["tgt2"] - f["entry"]) * 10000, 2) if f["tgt2"] else None
    # Realised RR
    stop_abs = abs(f["entry"] - f["stop"])
    tgt_abs = abs(f["tgt1"] - f["entry"])
    row["rr_primary"] = round(tgt_abs / stop_abs, 2) if stop_abs > 0 else None
    return row

# ------------------------------------------------------------
# Count-candidate row builder (Phase 3)
# ------------------------------------------------------------

def build_count_row(f: dict) -> dict:
    pub = datetime.fromisoformat(f["pub"])
    m5 = load_m5(pub - timedelta(days=30), pub)
    if not m5:
        return dict(id=f["id"], date=f["date"], pub_utc=f["pub"], note="NO CANDLE DATA")
    stale_min = (pub - m5[-1].ts).total_seconds() / 60.0
    if stale_min > STALENESS_LIMIT_MIN:
        return dict(id=f["id"], date=f["date"], pub_utc=f["pub"], direction=f["direction"],
                    note=f"NO_CANDLE_DATA ({stale_min/1440:.1f}d stale)")
    h1 = resample(m5, 60)
    h4 = resample(m5, 240)
    d1 = resample_d1(m5)

    out = dict(
        id=f["id"], date=f["date"], pub_utc=f["pub"], direction=f["direction"],
        pia_published_count="UNAVAILABLE",
        pia_published_timeframe="UNAVAILABLE",
    )
    for label, bars in [("H1", h1), ("H4", h4), ("D1", d1)]:
        if not bars:
            continue
        cd_n, cd_dir = consecutive_direction(bars)
        td_n, td_side = td_setup_count(bars)
        out[f"{label}_consec_direction_n"] = cd_n
        out[f"{label}_consec_direction_side"] = cd_dir
        out[f"{label}_consec_higher_closes"] = consecutive_higher_closes(bars)
        out[f"{label}_consec_lower_closes"] = consecutive_lower_closes(bars)
        out[f"{label}_consec_new_highs"] = consecutive_new_highs(bars)
        out[f"{label}_consec_new_lows"] = consecutive_new_lows(bars)
        out[f"{label}_td_setup_count"] = td_n
        out[f"{label}_td_setup_side"] = td_side
        out[f"{label}_completed_swings_15p"] = completed_swings(bars, 15.0)
        out[f"{label}_completed_swings_30p"] = completed_swings(bars, 30.0)
    return out

# ------------------------------------------------------------
# Outcome row builder (Phase 6)
# ------------------------------------------------------------

def build_outcome_row(f: dict, horizon_days: int = 10) -> dict:
    pub = datetime.fromisoformat(f["pub"])
    m5 = load_m5(pub, pub + timedelta(days=horizon_days))
    out = dict(
        id=f["id"], date=f["date"], pub_utc=f["pub"], direction=f["direction"],
        horizon_days=horizon_days,
    )
    if not m5:
        out["note"] = "NO POST-PUBLICATION CANDLES"
        return out
    # If every post-publication bar is literally before the publication
    # timestamp (archive ended before publication), bail out — this
    # happens for T5-T9 where the archive ends 2026-11-06.
    if m5[0].ts < pub:
        out["note"] = f"NO_POST_PUBLICATION_CANDLES (archive ends {m5[-1].ts.isoformat()})"
        return out

    entry = f["entry"]
    stop = f["stop"]
    tgt1 = f["tgt1"]
    tgt2 = f["tgt2"]
    is_buy = f["direction"] == "BUY"

    out["bars_post_pub"] = len(m5)
    out["observation_window_end_utc"] = m5[-1].ts.isoformat()

    # Entry fill: for BUY limit, needs a bar whose low <= entry. For SELL limit,
    # needs a bar whose high >= entry.
    entry_fill_ts: Optional[datetime] = None
    for b in m5:
        if is_buy and b.l <= entry:
            entry_fill_ts = b.ts
            break
        if not is_buy and b.h >= entry:
            entry_fill_ts = b.ts
            break
    out["entry_filled"] = entry_fill_ts is not None
    out["entry_fill_utc"] = entry_fill_ts.isoformat() if entry_fill_ts else ""
    out["minutes_to_entry_fill"] = round((entry_fill_ts - pub).total_seconds() / 60.0, 1) if entry_fill_ts else None

    # After fill (or publication, if never filled), track outcome.
    post_fill = [b for b in m5 if b.ts >= (entry_fill_ts or pub)]

    # Max favourable / adverse from entry level in the published direction.
    def mfe_mae(bars: list[Candle]) -> tuple[float, float]:
        mfe = 0.0
        mae = 0.0
        for b in bars:
            if is_buy:
                mfe = max(mfe, (b.h - entry) * 10000)
                mae = min(mae, (b.l - entry) * 10000)
            else:
                mfe = max(mfe, (entry - b.l) * 10000)
                mae = min(mae, (entry - b.h) * 10000)
        return mfe, mae

    mfe, mae = mfe_mae(post_fill)
    out["mfe_from_entry_pips"] = round(mfe, 2)
    out["mae_from_entry_pips"] = round(mae, 2)

    # Target / stop hit tracking — only valid if entry filled.
    def hit_ts(bars: list[Candle], predicate) -> Optional[datetime]:
        for b in bars:
            if predicate(b):
                return b.ts
        return None

    if entry_fill_ts is not None:
        if is_buy:
            tp1_ts = hit_ts(post_fill, lambda b: b.h >= tgt1)
            tp2_ts = hit_ts(post_fill, lambda b: b.h >= tgt2) if tgt2 else None
            sl_ts = hit_ts(post_fill, lambda b: b.l <= stop)
        else:
            tp1_ts = hit_ts(post_fill, lambda b: b.l <= tgt1)
            tp2_ts = hit_ts(post_fill, lambda b: b.l <= tgt2) if tgt2 else None
            sl_ts = hit_ts(post_fill, lambda b: b.h >= stop)
        out["tp1_hit"] = tp1_ts is not None
        out["tp1_hit_utc"] = tp1_ts.isoformat() if tp1_ts else ""
        out["tp2_hit"] = tp2_ts is not None if tgt2 else None
        out["tp2_hit_utc"] = tp2_ts.isoformat() if tp2_ts else ""
        out["stop_hit"] = sl_ts is not None
        out["stop_hit_utc"] = sl_ts.isoformat() if sl_ts else ""
        # First-to-hit (TP1 vs stop)
        if tp1_ts and sl_ts:
            out["first_event"] = "TP1" if tp1_ts < sl_ts else "STOP"
        elif tp1_ts:
            out["first_event"] = "TP1"
        elif sl_ts:
            out["first_event"] = "STOP"
        else:
            out["first_event"] = "NEITHER"
    else:
        for k in ("tp1_hit", "tp2_hit", "stop_hit"):
            out[k] = None
        out["first_event"] = "ENTRY_NEVER_FILLED"

    # Correction-anticipated outcome: did price move AGAINST the published
    # direction first (the "temporary correction" of Phase 4)?  Measured as
    # the first excursion of >=10 pips in the counter direction before any
    # >=10 pip move in the forecast direction.
    threshold_pips = 10.0 / 10000.0
    correction_ts: Optional[datetime] = None
    continuation_ts: Optional[datetime] = None
    ref = m5[0].o if m5 else entry  # from the very first post-pub bar
    for b in m5:
        if is_buy:
            if b.l <= ref - threshold_pips and correction_ts is None:
                correction_ts = b.ts
            if b.h >= ref + threshold_pips and continuation_ts is None:
                continuation_ts = b.ts
        else:
            if b.h >= ref + threshold_pips and correction_ts is None:
                correction_ts = b.ts
            if b.l <= ref - threshold_pips and continuation_ts is None:
                continuation_ts = b.ts
        if correction_ts and continuation_ts:
            break
    out["correction_first"] = (correction_ts is not None
                               and (continuation_ts is None or correction_ts < continuation_ts))
    out["correction_first_utc"] = correction_ts.isoformat() if correction_ts else ""
    out["continuation_first_utc"] = continuation_ts.isoformat() if continuation_ts else ""
    return out

# ------------------------------------------------------------
# Writers
# ------------------------------------------------------------

def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                keys.append(k)
                seen.add(k)
    with path.open("w") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def main() -> None:
    market_rows = [build_market_row(f) for f in FORECASTS]
    count_rows = [build_count_row(f) for f in FORECASTS]
    outcome_rows = [build_outcome_row(f) for f in FORECASTS]

    write_csv(CSV_DIR / "PIA_EXHAUSTION_MARKET_RECONSTRUCTION.csv", market_rows)
    write_csv(CSV_DIR / "PIA_EXHAUSTION_COUNT_COMPARISON.csv", count_rows)
    write_csv(CSV_DIR / "PIA_EXHAUSTION_OUTCOMES.csv", outcome_rows)

    print(f"Wrote {len(market_rows)} market rows, {len(count_rows)} count rows, {len(outcome_rows)} outcome rows.")

if __name__ == "__main__":
    main()
