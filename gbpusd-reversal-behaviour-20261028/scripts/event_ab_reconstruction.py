"""Reconstruct the two 2026-10-28 GBP/USD reversals.

Event A: ~07:15 UK — price falls into 1.3273-1.3275 area, lower BB
         approached/breached, recovery to ~1.3295.
Event B: ~11:00 UK — repeat test of the same area, recovery to ~1.3290.

For each event, pull M5 bars spanning 30 min before the local low
through 60 min after.  Compute point-in-time indicator values and
report the sequence table.

Data provenance for 2026-10-28:
    /opt/tradingbot/data/candles/GBPUSD/2026-10-28.csv is the live
    MID-of-bid-ask archive.  No BID-side candle file exists for 2026
    on this host (candles_ext ends 2025-12-31).  The brief requests
    BID candles; we flag this limitation in the output.  Phase 2
    tick cache ends 2026-03-31 so cannot help either.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, bollinger, ema, macd, read_mid_m5, rsi


DATE = datetime(2026, 10, 28, tzinfo=timezone.utc)
EVENT_A_WINDOW = (datetime(2026, 10, 28, 6, 45, tzinfo=timezone.utc),
                  datetime(2026, 10, 28, 8, 15, tzinfo=timezone.utc))
EVENT_B_WINDOW = (datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc),
                  datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc))


def _within(bar: Bar, window: tuple[datetime, datetime]) -> bool:
    return window[0] <= bar.ts <= window[1]


def _format_bar(bar: Bar, idx: int, closes: list[float],
                bb_low, bb_mid, bb_up, ema7, ema13, ema21,
                macd_line, macd_sig, macd_hist, rsi_series) -> dict:
    def _r(v, nd=5):
        if v is None:
            return None
        return round(float(v) / 10000.0, nd)   # convert IG points → decimal price

    def _rp(v, nd=2):
        if v is None:
            return None
        return round(float(v), nd)              # keep in points

    return {
        "ts_utc": bar.ts.isoformat(),
        "ts_uk": bar.ts.astimezone(timezone.utc).strftime("%H:%M"),
        "o_pts": _rp(bar.open), "h_pts": _rp(bar.high),
        "l_pts": _rp(bar.low), "c_pts": _rp(bar.close),
        "body_pts": _rp(bar.body),
        "range_pts": _rp(bar.range),
        "upper_wick_pts": _rp(bar.upper_wick),
        "lower_wick_pts": _rp(bar.lower_wick),
        "colour": "green" if bar.is_green else ("red" if bar.is_red else "doji"),
        "bb_low_pts": _rp(bb_low[idx]),
        "bb_mid_pts": _rp(bb_mid[idx]),
        "bb_up_pts": _rp(bb_up[idx]),
        "bb_breach_low": (bb_low[idx] is not None and bar.low <= bb_low[idx]),
        "bb_breach_up": (bb_up[idx] is not None and bar.high >= bb_up[idx]),
        "ema7_pts": _rp(ema7[idx]),
        "ema13_pts": _rp(ema13[idx]),
        "ema21_pts": _rp(ema21[idx]),
        "close_vs_ema7": (
            "above" if (ema7[idx] is not None and bar.close > ema7[idx])
            else "below" if (ema7[idx] is not None and bar.close < ema7[idx])
            else "n/a"
        ),
        "close_vs_ema21": (
            "above" if (ema21[idx] is not None and bar.close > ema21[idx])
            else "below" if (ema21[idx] is not None and bar.close < ema21[idx])
            else "n/a"
        ),
        "macd_line": round(macd_line[idx], 3) if macd_line[idx] is not None else None,
        "macd_sig":  round(macd_sig[idx], 3)  if macd_sig[idx]  is not None else None,
        "macd_hist": round(macd_hist[idx], 3) if macd_hist[idx] is not None else None,
        "rsi":       round(rsi_series[idx], 1) if rsi_series[idx] is not None else None,
    }


def main() -> int:
    bars = read_mid_m5(DATE)
    closes = [b.close for b in bars]
    bb_low, bb_mid, bb_up = bollinger(closes, 20, 2.0)
    ema7 = ema(closes, 7)
    ema13 = ema(closes, 13)
    ema21 = ema(closes, 21)
    macd_line, macd_sig, macd_hist = macd(closes, 12, 26, 9)
    rsi_series = rsi(closes, 14)

    output = {
        "date_utc": DATE.strftime("%Y-%m-%d"),
        "data_source": "candles/GBPUSD/2026-10-28.csv (MID-of-bid-ask)",
        "data_limitation": (
            "BID-side candles are not archived for 2026 on this host. "
            "Phase 2 tick cache ends 2026-03-31. The analysis below uses "
            "the MID candle; for a BID study of a 2026 reversal, a tick "
            "stream for the day would need to be sourced separately. "
            "The mid is bounded by half-spread error of ≤1 pip for "
            "GBPUSD outside news windows."
        ),
        "bb_params": {"period": 20, "stddev": 2.0, "basis": "close"},
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "events": {}
    }

    for name, window in [("A", EVENT_A_WINDOW), ("B", EVENT_B_WINDOW)]:
        rows = []
        local_low_px = float("inf")
        local_low_bar = None
        for idx, b in enumerate(bars):
            if not _within(b, window):
                continue
            row = _format_bar(b, idx, closes, bb_low, bb_mid, bb_up,
                              ema7, ema13, ema21,
                              macd_line, macd_sig, macd_hist, rsi_series)
            rows.append(row)
            if b.low < local_low_px:
                local_low_px = b.low
                local_low_bar = row

        # Reversal-timing diagnostics
        # 1. First strong bullish displacement after the local low
        first_strong_green = None
        first_cross_ema7 = None
        first_cross_ema21 = None
        first_higher_high = None
        prev_high = None
        for row in rows:
            if local_low_bar is None or row["ts_utc"] <= local_low_bar["ts_utc"]:
                continue
            if row["colour"] == "green" and row["body_pts"] > 5.0 \
                    and first_strong_green is None:
                first_strong_green = row["ts_utc"]
            if row["close_vs_ema7"] == "above" and first_cross_ema7 is None:
                first_cross_ema7 = row["ts_utc"]
            if row["close_vs_ema21"] == "above" and first_cross_ema21 is None:
                first_cross_ema21 = row["ts_utc"]
            if prev_high is not None and row["h_pts"] > prev_high \
                    and first_higher_high is None:
                first_higher_high = row["ts_utc"]
            prev_high = row["h_pts"]

        # Extension-attempts: how many red closes within 2 pts of the lowest low
        attempts = 0
        for row in rows:
            if row["colour"] == "red" and abs(row["c_pts"] - local_low_px) < 2.0:
                attempts += 1

        output["events"][name] = {
            "window_utc": [window[0].isoformat(), window[1].isoformat()],
            "local_low_pts": local_low_px,
            "local_low_at_utc": local_low_bar["ts_utc"] if local_low_bar else None,
            "first_strong_green_ge_5pt_body_after_low": first_strong_green,
            "first_close_above_ema7_after_low": first_cross_ema7,
            "first_close_above_ema21_after_low": first_cross_ema21,
            "first_higher_high_after_low": first_higher_high,
            "ext_attempts_red_closes_within_2pts_of_low": attempts,
            "n_bars_in_window": len(rows),
            "bars": rows,
        }

    out_path = HERE.parent / "data" / "event_ab_reconstruction.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    # Concise summary
    for name in ("A", "B"):
        e = output["events"][name]
        print(f"Event {name}: low={e['local_low_pts']} at {e['local_low_at_utc']}")
        print(f"  attempts near low: {e['ext_attempts_red_closes_within_2pts_of_low']}")
        print(f"  first strong green >5pt body: {e['first_strong_green_ge_5pt_body_after_low']}")
        print(f"  first close > EMA7:  {e['first_close_above_ema7_after_low']}")
        print(f"  first close > EMA21: {e['first_close_above_ema21_after_low']}")
        print(f"  first higher-high:   {e['first_higher_high_after_low']}")
        print(f"  bars in window: {e['n_bars_in_window']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
