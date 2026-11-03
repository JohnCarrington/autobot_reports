"""Phase 3 — attach "at touch" features to every pivot event.

Enriches csv/pivot_events.csv with M5 indicators computed up to and including
the touch bar — ZERO look-ahead. Writes csv/pivot_events_features.csv.

Features (all computed from M5 close by default):
  * ema20, ema50, ema20_slope, ema20_minus_ema50 (pips)
  * rsi14 (Wilder), rsi14_minus_rsi14_5bars_ago
  * bb_pos (close - mid) / stddev (20),  bb_width_pips (2 * stddev)
  * atr14 (Wilder, M5)
  * bars_since_last_higher_high, bars_since_last_lower_low (look-back ≤ 100 bars)
  * consecutive_up_candles, consecutive_down_candles
  * approach_velocity_5bar_pips, approach_velocity_15bar_pips
  * prior_tests_today (bars earlier today where |close - pivot_value| <= 5 pips)
  * hour_utc, session (copied/computed)

Warmup comes from the prior trading day's bars so indicators at 00:05 UTC are
usable. For "prior_tests_today" the lookback is reset at UTC midnight of the
event's date.

Basis split: only BID-basis events (2024-2025) are feature-enriched to keep the
downstream statistics basis-clean. The 106 MID events (2026 Jan-Feb) are copied
through without features and flagged `basis=mid, features=None`.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
import pathlib
from collections import defaultdict

CSV_IN  = pathlib.Path(__file__).parent.parent / "csv" / "pivot_events.csv"
CSV_OUT = pathlib.Path(__file__).parent.parent / "csv" / "pivot_events_features.csv"
BID_ROOT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")

PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")

# ---------- utilities --------------------------------------------------------

def load_day(path: pathlib.Path) -> list[dict]:
    """Load one daily M5 CSV. Returns list of dicts with floats in FX decimal."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            ts_raw = row["timestamp"].replace(" ", "T")
            try:
                ts = dt.datetime.fromisoformat(ts_raw)
            except ValueError:
                continue
            try:
                rows.append({
                    "ts": ts,
                    "o": float(row["open"])  / 10000.0,
                    "h": float(row["high"])  / 10000.0,
                    "l": float(row["low"])   / 10000.0,
                    "c": float(row["close"]) / 10000.0,
                })
            except (ValueError, KeyError):
                continue
    return rows

def ema_series(closes: list[float], span: int) -> list[float]:
    if not closes:
        return []
    alpha = 2.0 / (span + 1.0)
    out = [closes[0]]
    for c in closes[1:]:
        out.append(alpha * c + (1.0 - alpha) * out[-1])
    return out

def rsi_wilder(closes: list[float], period: int = 14) -> list[float]:
    """Wilder-smoothed RSI. Returns a list the same length as closes;
    the first `period` entries are approximations (seeded from simple averages)."""
    if len(closes) < period + 1:
        return [float("nan")] * len(closes)
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(0.0,  d) for d in deltas]
    losses = [max(0.0, -d) for d in deltas]
    avg_gain = sum(gains[:period])  / period
    avg_loss = sum(losses[:period]) / period
    out = [float("nan")] * period  # positions 0..period-1 undefined for close-based deltas
    # First RSI corresponds to close index `period`
    rs = (avg_gain / avg_loss) if avg_loss > 0 else float("inf")
    rsi = 100.0 - (100.0 / (1.0 + rs)) if avg_loss > 0 else 100.0
    out.append(rsi)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i])  / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = (avg_gain / avg_loss) if avg_loss > 0 else float("inf")
        out.append(100.0 - (100.0 / (1.0 + rs)) if avg_loss > 0 else 100.0)
    # out length = len(closes)
    return out

def bollinger(closes: list[float], period: int = 20):
    """Return (mid, upper_std, lower_std, stddev) per bar. Non-defined values are nan."""
    n = len(closes)
    mid    = [float("nan")] * n
    stddev = [float("nan")] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        m = sum(window) / period
        v = sum((x - m) ** 2 for x in window) / period
        mid[i] = m
        stddev[i] = math.sqrt(v)
    return mid, stddev

def atr_wilder(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    n = len(closes)
    if n < 2:
        return [float("nan")] * n
    trs: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    atr = [float("nan")] * n
    if n >= period:
        atr[period - 1] = sum(trs[:period]) / period
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + trs[i]) / period
    return atr

# ---------- event enrichment -------------------------------------------------

def enrich_day(day_date: dt.date, prev_date: dt.date | None,
               day_bars: list[dict], prev_bars: list[dict],
               events_today: list[dict]) -> list[dict]:
    """Return feature-enriched event dicts for one day."""
    # Stitch prev-day warmup + today
    warmup = prev_bars[-200:] if prev_bars else []
    combined = warmup + day_bars
    if not combined:
        return []
    closes = [b["c"] for b in combined]
    highs  = [b["h"] for b in combined]
    lows   = [b["l"] for b in combined]

    ema20_s = ema_series(closes, 20)
    ema50_s = ema_series(closes, 50)
    rsi_s   = rsi_wilder(closes, 14)
    bb_mid, bb_sd = bollinger(closes, 20)
    atr_s = atr_wilder(highs, lows, closes, 14)

    # Today's bars start at index `start_today` in the combined array.
    start_today = len(warmup)

    enriched: list[dict] = []
    for e in events_today:
        bar_ts = dt.datetime.fromisoformat(e["bar_ts"])
        # Find today's bar index whose ts matches.
        today_idx = None
        for j, b in enumerate(day_bars):
            if b["ts"] == bar_ts:
                today_idx = j
                break
        if today_idx is None:
            continue
        i = start_today + today_idx  # index into combined / indicator arrays

        # Features
        ema20_now = ema20_s[i]
        ema50_now = ema50_s[i]
        ema20_slope_pips = (ema20_s[i] - ema20_s[max(0, i - 10)]) * 10000.0 if i >= 10 else 0.0
        ema20_minus_ema50_pips = (ema20_now - ema50_now) * 10000.0

        rsi_now = rsi_s[i] if not math.isnan(rsi_s[i]) else 50.0
        rsi_prev = rsi_s[max(0, i - 5)] if not math.isnan(rsi_s[max(0, i - 5)]) else 50.0
        rsi_slope_5bar = rsi_now - rsi_prev

        if not math.isnan(bb_mid[i]) and not math.isnan(bb_sd[i]) and bb_sd[i] > 0:
            bb_pos = (closes[i] - bb_mid[i]) / bb_sd[i]
            bb_width_pips = 2.0 * bb_sd[i] * 10000.0
        else:
            bb_pos = 0.0
            bb_width_pips = 0.0

        atr_now_pips = atr_s[i] * 10000.0 if not math.isnan(atr_s[i]) else 0.0

        # Approach velocity
        approach_5  = (closes[i] - closes[max(0, i - 5)])  * 10000.0
        approach_15 = (closes[i] - closes[max(0, i - 15)]) * 10000.0

        # Consecutive up/down candles ending at i
        cu = cd = 0
        for j in range(i, -1, -1):
            if combined[j]["c"] > combined[j]["o"]:
                if cd:
                    break
                cu += 1
            elif combined[j]["c"] < combined[j]["o"]:
                if cu:
                    break
                cd += 1
            else:
                break

        # Bars since last higher-high / lower-low (look-back ≤ 100 bars)
        lb = min(100, i)
        max_high = combined[i]["h"]
        bars_since_hh = 0
        for j in range(i - 1, max(-1, i - lb - 1), -1):
            if combined[j]["h"] > max_high:
                break
            bars_since_hh += 1
        min_low = combined[i]["l"]
        bars_since_ll = 0
        for j in range(i - 1, max(-1, i - lb - 1), -1):
            if combined[j]["l"] < min_low:
                break
            bars_since_ll += 1

        # Prior tests today (before this bar, within 5 pips of pivot_value)
        pivot_value = float(e["pivot_value"])
        prior_tests_today = 0
        for j in range(today_idx):
            if abs(day_bars[j]["c"] - pivot_value) <= 0.0005:  # 5 pips
                prior_tests_today += 1

        hour_utc = bar_ts.hour
        session = (
            "Asia"          if 0 <= hour_utc < 7  else
            "LondonOpen"    if 7 <= hour_utc < 9  else
            "LondonMorning" if 9 <= hour_utc < 12 else
            "LN_NY_Overlap" if 12 <= hour_utc < 16 else
            "LateNY"        if 16 <= hour_utc < 22 else
            "WeekendStub"
        )

        enriched.append({
            **e,
            "ema20_minus_ema50_pips":   f"{ema20_minus_ema50_pips:+.1f}",
            "ema20_slope_pips_per10b":  f"{ema20_slope_pips:+.2f}",
            "rsi14":                    f"{rsi_now:.1f}",
            "rsi14_slope_5bar":         f"{rsi_slope_5bar:+.1f}",
            "bb_pos_std":               f"{bb_pos:+.2f}",
            "bb_width_pips":            f"{bb_width_pips:.1f}",
            "atr14_pips":               f"{atr_now_pips:.1f}",
            "consecutive_up_candles":   cu,
            "consecutive_down_candles": cd,
            "bars_since_higher_high":   bars_since_hh,
            "bars_since_lower_low":     bars_since_ll,
            "approach_velocity_5bar_pips":  f"{approach_5:+.1f}",
            "approach_velocity_15bar_pips": f"{approach_15:+.1f}",
            "prior_tests_today":        prior_tests_today,
            "hour_utc":                 hour_utc,
            "session":                  session,
        })
    return enriched

def main() -> None:
    events = list(csv.DictReader(CSV_IN.open()))
    print(f"Loaded {len(events)} events")

    # Only enrich BID-basis events (2024-2025). Pass MID events through unchanged.
    bid_events = [e for e in events if e["basis"] == "bid"]
    mid_events = [e for e in events if e["basis"] == "mid"]
    print(f"BID events to enrich: {len(bid_events)}   MID events passed through: {len(mid_events)}")

    # Group events by date
    by_date = defaultdict(list)
    for e in bid_events:
        by_date[e["date"]].append(e)

    enriched_all: list[dict] = []
    skipped = 0
    for date_s in sorted(by_date.keys()):
        d = dt.date.fromisoformat(date_s)
        day_bars = load_day(BID_ROOT / f"{date_s}.csv")
        # prior trading day (walk back ≤ 7 days)
        prev_bars: list[dict] = []
        prev_date = None
        for back in range(1, 8):
            cand_date = d - dt.timedelta(days=back)
            prev_bars = load_day(BID_ROOT / f"{cand_date.isoformat()}.csv")
            if prev_bars:
                prev_date = cand_date
                break
        if not day_bars:
            skipped += len(by_date[date_s])
            continue
        enriched_all.extend(enrich_day(d, prev_date, day_bars, prev_bars, by_date[date_s]))

    # Append MID events (features left blank)
    feature_cols = [
        "ema20_minus_ema50_pips", "ema20_slope_pips_per10b",
        "rsi14", "rsi14_slope_5bar",
        "bb_pos_std", "bb_width_pips", "atr14_pips",
        "consecutive_up_candles", "consecutive_down_candles",
        "bars_since_higher_high", "bars_since_lower_low",
        "approach_velocity_5bar_pips", "approach_velocity_15bar_pips",
        "prior_tests_today", "hour_utc", "session",
    ]
    for e in mid_events:
        enriched_all.append({**e, **{k: "" for k in feature_cols}})

    print(f"Enriched: {len(enriched_all)}  skipped (missing day file): {skipped}")

    if enriched_all:
        all_keys = list(enriched_all[0].keys())
        with CSV_OUT.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=all_keys)
            w.writeheader()
            w.writerows(enriched_all)
        print(f"Wrote {CSV_OUT}")

if __name__ == "__main__":
    main()
