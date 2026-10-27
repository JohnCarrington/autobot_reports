"""
Pre-London reversal zone forecasters.

Each forecaster produces, for a given UTC date D and a cutoff time
`as_of_london_6am = 06:00 Europe/London` (= 05:00 UTC during BST, 06:00 UTC
during GMT), a (BUY zone, SELL zone) pair OR None if evidence is
insufficient.

Zones are produced from information COMPLETED strictly before `as_of`. The
walk-forward evaluator uses only M5 bars after `as_of` to measure outcomes.

Models implemented:
  M1  Pivots       — BUY zone = S1 ± 5p,  SELL zone = R1 ± 5p
  M2  Swings       — BUY zone = most recent confirmed H1 swing LOW below
                     spot (within 10..100 p) ± 5p; mirror for SELL.
  M3  Prev-day HL  — BUY zone = yesterday's low ± 5p, SELL = yesterday's high ± 5p
  M4  Baseline     — BUY zone = spot − ATR20 × 0.5 ± 5p (ATR20 of daily H-L
                     over the trailing 20 UTC-days as of yesterday).

Returned schema (one row per forecast per model):
  prediction_time, model, date, direction, zone_lo, zone_hi, zone_mid,
  spot_at_prediction, distance_pips_from_spot, rationale, confidence,
  rank, validity_bars
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from swings import detect_swings


def london_6am_to_utc(d: date) -> pd.Timestamp:
    """Return the UTC timestamp of 06:00 London on date d, honoring BST.
    GMT→BST transition: last Sunday of March 01:00 UTC.
    BST→GMT transition: last Sunday of October 01:00 UTC.
    This is sufficient; the archive's UTC timestamps are the source of truth
    regardless of UK time."""
    uk_offset = _uk_offset_hours(d)
    hour_utc = 6 - uk_offset
    return pd.Timestamp(f"{d.isoformat()} {hour_utc:02d}:00", tz="UTC")


def _uk_offset_hours(d: date) -> int:
    """Return +0 for GMT, +1 for BST."""
    y = d.year
    # Last Sunday of March
    march_last = date(y, 3, 31)
    while march_last.weekday() != 6: march_last -= timedelta(days=1)
    # Last Sunday of October
    oct_last = date(y, 10, 31)
    while oct_last.weekday() != 6: oct_last -= timedelta(days=1)
    return 1 if march_last <= d < oct_last else 0


def _spot_at(m5: pd.DataFrame, as_of: pd.Timestamp) -> Optional[float]:
    """Last M5 close strictly before `as_of`."""
    idx = int(np.searchsorted(m5["timestamp"].values, as_of.to_datetime64(), side="left")) - 1
    if idx < 0: return None
    return float(m5.at[idx, "close"])


def _pivots_for_date(m5: pd.DataFrame, d: date, _dates_cache=None) -> Optional[dict]:
    """Pivots computed from day D-1's HLC."""
    if _dates_cache is None:
        return None
    for lookback_days in range(1, 5):
        pday = d - timedelta(days=lookback_days)
        rows = _dates_cache.get(pday)
        if rows is None: continue
        H, L, C = rows
        P = (H + L + C) / 3.0
        return dict(
            PP=P, S1=2*P-H, S2=P-(H-L), S3=L-2*(H-P),
            R1=2*P-L, R2=P+(H-L), R3=H+2*(P-L),
            prev_h=H, prev_l=L, prev_c=C, prev_date=pday,
        )
    return None


def build_daily_hlc_cache(m5: pd.DataFrame) -> dict:
    """One-time daily H/L/C cache: {date -> (H, L, C)}."""
    df = m5.copy()
    df["date"] = df["timestamp"].dt.date
    g = df.groupby("date").agg(h=("high","max"), l=("low","min"), c=("close","last"))
    return {d: (r["h"], r["l"], r["c"]) for d, r in g.iterrows()}


def _recent_h1_swings(m5: pd.DataFrame, as_of: pd.Timestamp,
                     threshold_pips: float = 20.0, lookback_days: int = 20) -> pd.DataFrame:
    """H1 swings CONFIRMED strictly before `as_of`, limited to the last N days.
    m5['timestamp'] must already be tz-aware datetime64[ns, UTC]."""
    start = as_of - pd.Timedelta(days=lookback_days)
    ts_arr = m5["timestamp"].values
    i0 = int(np.searchsorted(ts_arr, np.datetime64(start.to_datetime64())))
    i1 = int(np.searchsorted(ts_arr, np.datetime64(as_of.to_datetime64()), side="left"))
    if i1 - i0 < 25: return pd.DataFrame()
    m5_sub = m5.iloc[i0:i1]
    idx = m5_sub.set_index("timestamp")
    h1 = idx.resample("1h", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
    ).dropna().reset_index()
    if len(h1) < 25: return pd.DataFrame()
    sw = detect_swings(h1, threshold_pips)
    if len(sw) == 0: return sw
    return sw[sw["conf_time"] < as_of].reset_index(drop=True)


def _daily_atr(m5: pd.DataFrame, as_of: pd.Timestamp, n_days: int = 20,
               _dates_cache=None) -> Optional[float]:
    """Mean of daily (H-L) over the trailing N completed UTC days (excluding today)."""
    if _dates_cache is None: return None
    today = as_of.date()
    prior = sorted(d for d in _dates_cache.keys() if d < today)
    if len(prior) < 5: return None
    tail_dates = prior[-n_days:]
    ranges = [_dates_cache[d][0] - _dates_cache[d][1] for d in tail_dates]
    return float(sum(ranges) / len(ranges))


ZONE_HALF_WIDTH_PIPS = 5.0


def _mkzone(mid: float, direction: str, rationale: str, rank: str = "primary",
            confidence: float = 0.5, half: float = ZONE_HALF_WIDTH_PIPS,
            validity_bars: int = 288) -> dict:
    return dict(
        direction=direction,
        zone_lo=mid - half, zone_hi=mid + half, zone_mid=mid,
        rationale=rationale, rank=rank, confidence=confidence,
        validity_bars=validity_bars,
    )


def forecast_m1_pivots(m5, as_of, spot, d, cache=None):
    pv = _pivots_for_date(m5, d, cache)
    if pv is None: return []
    out = [{**_mkzone(pv["S1"], "BUY", f"S1 @ {pv['S1']:.2f} from prev {pv['prev_date']} HLC")},
           {**_mkzone(pv["R1"], "SELL", f"R1 @ {pv['R1']:.2f} from prev {pv['prev_date']} HLC")}]
    for z in out:
        z["distance_pips_from_spot"] = abs(z["zone_mid"] - spot)
    return out


def forecast_m2_swings(m5, as_of, spot, d, cache=None):
    sw = _recent_h1_swings(m5, as_of, threshold_pips=20.0, lookback_days=20)
    if len(sw) == 0: return []
    # Candidate buy zones: swing LOW extrema (end of DOWN swings) below spot and within 10-100p
    lows = sw[sw["direction"] == "DOWN"]["end_price"]
    highs = sw[sw["direction"] == "UP"]["end_price"]
    out = []
    for lp in sorted(lows, key=lambda x: abs(x - spot)):
        d_pips = spot - lp
        if 10 <= d_pips <= 100:
            out.append({**_mkzone(lp, "BUY", f"H1 swing LOW @ {lp:.2f} ({d_pips:.0f}p below spot)"),
                        "distance_pips_from_spot": d_pips})
            break
    for hp in sorted(highs, key=lambda x: abs(x - spot)):
        d_pips = hp - spot
        if 10 <= d_pips <= 100:
            out.append({**_mkzone(hp, "SELL", f"H1 swing HIGH @ {hp:.2f} ({d_pips:.0f}p above spot)"),
                        "distance_pips_from_spot": d_pips})
            break
    return out


def forecast_m3_prev_hl(m5, as_of, spot, d, cache=None):
    pv = _pivots_for_date(m5, d, cache)
    if pv is None: return []
    out = [{**_mkzone(pv["prev_l"], "BUY", f"Prev day ({pv['prev_date']}) LOW @ {pv['prev_l']:.2f}")},
           {**_mkzone(pv["prev_h"], "SELL", f"Prev day ({pv['prev_date']}) HIGH @ {pv['prev_h']:.2f}")}]
    for z in out:
        z["distance_pips_from_spot"] = abs(z["zone_mid"] - spot)
    return out


def forecast_m4_baseline(m5, as_of, spot, d, cache=None):
    atr = _daily_atr(m5, as_of, n_days=20, _dates_cache=cache)
    if atr is None: return []
    half_range = atr * 0.5
    out = [{**_mkzone(spot - half_range, "BUY", f"Spot − 0.5×ATR20 ({atr:.1f}p)"),
            "distance_pips_from_spot": half_range},
           {**_mkzone(spot + half_range, "SELL", f"Spot + 0.5×ATR20 ({atr:.1f}p)"),
            "distance_pips_from_spot": half_range}]
    return out


MODELS = {
    "M1_pivots": forecast_m1_pivots,
    "M2_swings": forecast_m2_swings,
    "M3_prev_hl": forecast_m3_prev_hl,
    "M4_baseline": forecast_m4_baseline,
}


def forecast_all_models(m5: pd.DataFrame, d: date, cache: Optional[dict] = None) -> list[dict]:
    """Run every model at as_of = 06:00 London on date d. Returns rows."""
    as_of = london_6am_to_utc(d)
    spot = _spot_at(m5, as_of)
    if spot is None: return []
    rows = []
    for name, fn in MODELS.items():
        for z in fn(m5, as_of, spot, d, cache):
            rows.append({
                "model": name, "prediction_time": as_of, "date": d,
                "spot_at_prediction": spot,
                **z,
            })
    return rows


def evaluate_zone(m5: pd.DataFrame, zone: dict, max_bars: int = 288) -> dict:
    """For a predicted zone, walk M5 forward from prediction_time and measure outcomes.

    Returns:
      approached (bool), approach_time, approach_price, approach_bars,
      bounce_pips_from_zone (max favorable move from the touch, direction-adjusted),
      drawdown_through_zone (how far price went THROUGH the zone before any bounce),
      hits_15 / hits_20 / hits_30 / hits_50 (bool)
    """
    as_of = pd.Timestamp(zone["prediction_time"]).to_datetime64()
    lo = zone["zone_lo"]; hi = zone["zone_hi"]
    direction = zone["direction"]  # BUY = expect price to bounce UP from zone
    ts = m5["timestamp"].values.astype("datetime64[ns]")
    highs = m5["high"].values; lows = m5["low"].values; closes = m5["close"].values
    start = int(np.searchsorted(ts, as_of, side="right"))
    end = min(start + max_bars, len(ts))
    # First touch: bar whose [low, high] intersects [lo, hi]
    j = -1
    for k in range(start, end):
        if lows[k] <= hi and highs[k] >= lo:
            j = k; break
    if j < 0:
        return dict(approached=False, approach_time=None, approach_price=None,
                    approach_bars=-1, max_bounce=0.0, max_through=0.0,
                    hits_15=False, hits_20=False, hits_30=False, hits_50=False)
    # Reference price = ZONE_MID for a limit at the center
    entry_px = zone["zone_mid"]
    sub_h = highs[j:end]; sub_l = lows[j:end]
    if direction == "BUY":
        bounce = sub_h - entry_px   # upward from zone
        through = entry_px - sub_l  # downward beyond zone
    else:
        bounce = entry_px - sub_l   # downward from zone
        through = sub_h - entry_px  # upward beyond zone
    max_bounce = float(bounce.max())
    max_through = float(through.max())
    return dict(
        approached=True,
        approach_time=pd.Timestamp(ts[j]),
        approach_price=float(closes[j]),
        approach_bars=j - start,
        max_bounce=max_bounce,
        max_through=max_through,
        hits_15=max_bounce >= 15.0,
        hits_20=max_bounce >= 20.0,
        hits_30=max_bounce >= 30.0,
        hits_50=max_bounce >= 50.0,
    )
