#!/usr/bin/env python3
"""Point-in-time feature engineering for every weekday × decision hour.

For each weekday and each decision hour h ∈ {07, 08, 09, 10, 11, 12, 13} UK
local, we compute a feature vector that strictly uses only information
knowable AT OR BEFORE the final M5 bar closing at ≤ h:00 UK local.

Features (per snapshot):

  Price-action (last k M5 bars up to decision)
    * ret_60_pips, ret_120_pips, ret_240_pips, ret_full_pips   (close − close at look-back)
    * body_mean_3, body_mean_6, body_mean_12                   (|close-open|, pips)
    * directional_streak_count                                 (# of same-sign consecutive bars)
    * directional_streak_pips                                  (net pips in streak)
    * pullback_pips_from_hi, pullback_pips_from_lo              (distance from running peak/trough)

  Session summaries (ASIA 00-07 UK)
    * asia_range_pips, asia_direction (+1/-1/0), asia_body_pct

  Range / position
    * pos_in_day_range                                          (0 at low, 1 at high)
    * dist_to_PDH_pips, dist_to_PDL_pips                        (signed)
    * dist_to_PP_pips, dist_to_R1_pips, dist_to_S1_pips
    * atr14_pips, atr_ratio                                     (today's range so far / atr14)

  Indicators (standard)
    * ema7-ema21, ema13-ema21 (pips, slope sign of each)
    * macd_hist (pips), macd_hist_slope
    * adx14, +DI, -DI, DI_sep
    * bb20_width_pips, bb20_mid, pct_bb_pos                     (close position in BB)
    * close_distance_from_upper_bb_pips, from_lower_bb_pips
    * bb_hug_bars_recent                                        (bars in last 24 within 20% of band)

  Structure (confirmed fractals, n=3)
    * last_2_highs_up (bool), last_2_lows_up, last_2_highs_dn, last_2_lows_dn
    * swings_count_recent (last 24 bars)
    * net_dir_score  (= sum over swings of +1 for HH/HL, -1 for LH/LL)

  Calendar
    * cal_big_today, cal_mid_today, cal_pre_news, cal_post_news (bools)
    * mins_to_next_big_news_today (int or 1440)

  Day-of-week dummies

Targets (per snapshot — labels computed from the full day):
  * trend_day            (bool)
  * trend_dir             (+1 LONG, -1 SHORT, 0 none)
  * remaining_pips_dir    (pips remaining from the decision close to the swing's final peak in the realised dominant direction) — only meaningful on trend days.

Output: one row per (date, hour_uk) with features and labels, written to
`outputs/features.parquet`.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file, _07_uk_in_utc, _uk_offset_hours  # noqa: E402
from baseline_classifiers import _ema, _bb, _macd, _adx, _fractal_swings  # noqa: E402

ROOT = Path("<research_workspace>/outputs")
OUT = ROOT / "features.parquet"

CUTOFF_HOURS = [7, 8, 9, 10, 11, 12]  # UK local

cal_daily = pd.read_csv(ROOT / "calendar_daily.csv")
cal_daily["date"] = cal_daily["date"].astype(str)
cal_events = pd.read_csv(ROOT / "calendar_events.csv")
cal_events["date"] = cal_events["date"].astype(str)
daily_struct = pd.read_csv(ROOT / "daily_structure.csv")
daily_struct["date"] = daily_struct["date"].astype(str)
census = pd.read_csv(ROOT / "census.csv")
census["date"] = census["date"].astype(str)


def _cutoff_utc(date_str: str, uk_hour: int) -> pd.Timestamp:
    d = dt.date.fromisoformat(date_str)
    off = _uk_offset_hours(pd.Timestamp(d, tz="UTC"))
    return pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=uk_hour - off)


def _asia_summary(df: pd.DataFrame, date_str: str) -> dict:
    cutoff = _cutoff_utc(date_str, 7)
    sub = df[df["ts"] < cutoff]
    if sub.empty:
        return {"asia_range_pips": 0, "asia_direction": 0, "asia_body_pct": 0,
                "asia_close": None, "asia_open": None}
    o = float(sub["open"].iloc[0]) / 10000
    c = float(sub["close"].iloc[-1]) / 10000
    h = float(sub["high"].max()) / 10000
    l = float(sub["low"].min()) / 10000
    body = c - o
    rng = max(1e-6, h - l)
    return {
        "asia_range_pips": round((h - l) * 10000, 2),
        "asia_direction": int(np.sign(body)),
        "asia_body_pct": round((body / rng), 3) if rng > 0 else 0.0,
        "asia_close": round(c, 5),
        "asia_open": round(o, 5),
    }


def _price_action(close, open_, high, low, k_bars_list):
    out = {}
    n = len(close)
    for k in k_bars_list:
        if k < n:
            out[f"ret_{k}bars_pips"] = round((close[-1] - close[-k - 1]) * 10000, 2)
        else:
            out[f"ret_{k}bars_pips"] = round((close[-1] - close[0]) * 10000, 2)
    # body means
    bodies = np.abs(close - open_)
    for k in [3, 6, 12]:
        out[f"body_mean_{k}_pips"] = round(np.mean(bodies[-k:]) * 10000, 2) if n >= k else None
    # directional streak
    signs = np.sign(close - open_)
    streak = 0
    for i in range(n - 1, -1, -1):
        if signs[i] == signs[-1] and signs[i] != 0:
            streak += 1
        else:
            break
    streak_pips = (close[-1] - close[-1 - streak]) if streak > 0 and streak + 1 <= n else 0.0
    out["streak_bars"] = int(streak)
    out["streak_pips"] = round(streak_pips * 10000, 2)
    # pullback from running hi/lo on the day so far
    hi_run = high[: n].max()
    lo_run = low[: n].min()
    out["pullback_from_hi_pips"] = round((hi_run - close[-1]) * 10000, 2)
    out["pullback_from_lo_pips"] = round((close[-1] - lo_run) * 10000, 2)
    out["pos_in_day_range"] = round((close[-1] - lo_run) / max(1e-6, hi_run - lo_run), 3)
    return out


def _indicators(open_, high, low, close):
    out = {}
    if len(close) < 25:
        return {}
    e7 = _ema(close, 7)[-1]
    e13 = _ema(close, 13)[-1]
    e21 = _ema(close, 21)[-1]
    out["ema7_minus_21_pips"] = round((e7 - e21) * 10000, 2)
    out["ema13_minus_21_pips"] = round((e13 - e21) * 10000, 2)
    out["ema7_slope_3_pips"] = round((e7 - _ema(close[:-3], 7)[-1]) * 10000, 2) if len(close) > 10 else 0
    out["ema21_slope_6_pips"] = round((e21 - _ema(close[:-6], 21)[-1]) * 10000, 2) if len(close) > 27 else 0
    out["ema_stack_up"] = int(e7 > e13 > e21)
    out["ema_stack_dn"] = int(e7 < e13 < e21)

    _, _, hist = _macd(close)
    out["macd_hist_pips"] = round(hist[-1] * 10000, 2)
    out["macd_hist_slope_pips"] = round((hist[-1] - hist[-3]) * 10000, 2) if len(hist) > 3 else 0.0

    adx, pdi, mdi = _adx(high, low, close, 14)
    out["adx14"] = round(adx[-1], 2) if not np.isnan(adx[-1]) else None
    out["pdi14"] = round(pdi[-1], 2) if not np.isnan(pdi[-1]) else None
    out["mdi14"] = round(mdi[-1], 2) if not np.isnan(mdi[-1]) else None
    out["di_sep"] = round((pdi[-1] - mdi[-1]), 2) if not np.isnan(pdi[-1]) else None

    mid, up, lo = _bb(close, 20, 2.0)
    out["bb_mid_pips"] = round(mid[-1] * 10000, 2) if not np.isnan(mid[-1]) else None
    out["bb_width_pips"] = round((up[-1] - lo[-1]) * 10000, 2) if not np.isnan(up[-1]) else None
    out["dist_upper_bb_pips"] = round((up[-1] - close[-1]) * 10000, 2) if not np.isnan(up[-1]) else None
    out["dist_lower_bb_pips"] = round((close[-1] - lo[-1]) * 10000, 2) if not np.isnan(lo[-1]) else None
    bw = up[-1] - lo[-1] if not np.isnan(up[-1]) else None
    out["pct_bb_pos"] = round((close[-1] - lo[-1]) / bw, 3) if bw and bw > 0 else None
    # BB hug last 24 bars
    k = min(24, len(close))
    hug_u = hug_d = 0
    for i in range(len(close) - k, len(close)):
        if np.isnan(up[i]) or np.isnan(lo[i]):
            continue
        bw_i = up[i] - lo[i]
        if bw_i <= 0:
            continue
        if (up[i] - close[i]) / bw_i <= 0.20:
            hug_u += 1
        if (close[i] - lo[i]) / bw_i <= 0.20:
            hug_d += 1
    out["bb_hug_up_last24"] = hug_u
    out["bb_hug_dn_last24"] = hug_d
    return out


def _structure(high, low, close):
    swings = _fractal_swings(high, low, n=3)
    highs = [(i, p) for i, k, p in swings if k == 'H' and i + 3 <= len(close)]
    lows  = [(i, p) for i, k, p in swings if k == 'L' and i + 3 <= len(close)]
    out = {
        "hh_hl": 0, "lh_ll": 0, "neutral_struct": 0,
        "n_swings_last24": sum(1 for i, _ , _ in swings if i >= len(close) - 24),
    }
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1][1] > highs[-2][1]
        hl = lows [-1][1] > lows [-2][1]
        lh = highs[-1][1] < highs[-2][1]
        ll = lows [-1][1] < lows [-2][1]
        if hh and hl: out["hh_hl"] = 1
        elif lh and ll: out["lh_ll"] = 1
        else: out["neutral_struct"] = 1
    return out


def _calendar(date_str: str, cutoff_utc: pd.Timestamp) -> dict:
    row = cal_daily[cal_daily.date == date_str]
    out = {
        "cal_big_today": 0, "cal_mid_today": 0,
        "cal_pre_news": 0, "cal_post_news": 0,
    }
    if row.empty:
        return out | {"mins_to_next_big_today": 1440}
    r = row.iloc[0]
    out["cal_big_today"]  = int(r.ext_label == "BIG_NEWS")
    out["cal_mid_today"]  = int(r.ext_label == "MID_NEWS")
    out["cal_pre_news"]   = int(r.ext_label == "PRE_NEWS")
    out["cal_post_news"]  = int(r.ext_label == "POST_NEWS")
    # Minutes to next BIG event today
    todays_big = cal_events[(cal_events.date == date_str) & (cal_events.tier == "BIG")]
    if todays_big.empty:
        out["mins_to_next_big_today"] = 1440
    else:
        # Events have no explicit UTC time in the synthetic 2024-25 set; assume
        # NFP/CPI 13:30 UTC, FOMC 19:00 UTC, UK CPI/GDP 07:00 UTC. For 2026
        # authoritative data the event column stores name; we approximate by
        # name-matching the time.
        times = []
        for _, ev in todays_big.iterrows():
            name = str(ev.event or "").upper()
            if "NFP" in name or "PAYROLL" in name:        times.append(13*60+30)
            elif "CPI" in name and "US" in name:          times.append(13*60+30)
            elif "US_PCE" in name or "PCE" in name:       times.append(13*60+30)
            elif "FOMC" in name or "FED" in name:         times.append(19*60+0)
            elif "UK_CPI" in name or ("CPI" in name and ev.get("currency") == "GBP"):
                times.append(7*60+0)
            elif "UK_GDP" in name or ("GDP" in name and ev.get("currency") == "GBP"):
                times.append(7*60+0)
            elif "BOE" in name:                           times.append(12*60+0)
            elif ("UK_" in name and ev.get("currency", "") == "GBP"): times.append(7*60+0)
            else:                                         times.append(13*60+30)
        cutoff_min = cutoff_utc.hour * 60 + cutoff_utc.minute
        future_times = [t for t in times if t > cutoff_min]
        out["mins_to_next_big_today"] = min(future_times) - cutoff_min if future_times else 1440
    return out


def _structure_levels(date_str: str, close: float) -> dict:
    r = daily_struct[daily_struct.date == date_str]
    if r.empty or pd.isna(r.PDH.iloc[0]):
        return {}
    r = r.iloc[0]
    return {
        "dist_PDH_pips": round((r.PDH - close) * 10000, 2) if r.PDH else None,
        "dist_PDL_pips": round((close - r.PDL) * 10000, 2) if r.PDL else None,
        "dist_PP_pips":  round((r.PP - close) * 10000, 2) if r.PP else None,
        "dist_R1_pips":  round((r.R1 - close) * 10000, 2) if r.R1 else None,
        "dist_S1_pips":  round((close - r.S1) * 10000, 2) if r.S1 else None,
        "atr14_pips":    r.atr14_pips if "atr14_pips" in r else None,
        "prev_range_pips": r.prev_range_pips if "prev_range_pips" in r else None,
        "atr_ratio_so_far": None,  # fill below based on realised range to cutoff
    }


def _targets(df_full: pd.DataFrame, cutoff_utc: pd.Timestamp, census_row) -> dict:
    """Compute labels: trend_day flag, direction, remaining_pips in dominant dir."""
    trend_day = bool(census_row.trend_day)
    direction = census_row.direction
    peak_price = census_row.peak_price
    anchor_price = census_row.anchor_price
    pips = census_row.pips

    sub_future = df_full[df_full["ts"] > cutoff_utc]
    sub_so_far = df_full[df_full["ts"] <= cutoff_utc]
    if sub_future.empty or sub_so_far.empty:
        return {"trend_day": int(trend_day), "direction": direction, "pips_target": pips,
                "remaining_pips_in_dir": None,
                "trend_already_developed_pips": None}
    cur_px = float(sub_so_far["close"].iloc[-1]) / 10000
    if direction == "LONG":
        rem = (sub_future["high"].max() / 10000 - cur_px) * 10000
    else:
        rem = (cur_px - sub_future["low"].min() / 10000) * 10000
    # How much of the historical dominant swing is already in the past
    if direction == "LONG":
        best_so_far = (sub_so_far["high"].max() - sub_so_far["low"].min()) / 10000
    else:
        best_so_far = (sub_so_far["high"].max() - sub_so_far["low"].min()) / 10000
    return {
        "trend_day": int(trend_day),
        "direction": direction if trend_day else None,
        "pips_target": round(float(pips), 2),
        "remaining_pips_in_dir": round(float(rem), 2),
        "trend_already_developed_pips": round(best_so_far * 10000, 2),
    }


def features_for_day(path: Path, basis: str) -> list[dict]:
    df = _load_day_file(path, basis)
    if df is None or len(df) < 20:
        return []
    date = df["ts"].iloc[0].date()
    if date.weekday() >= 5:
        return []
    date_str = date.isoformat()
    cen = census[census.date == date_str]
    if cen.empty:
        return []
    cen = cen.iloc[0]

    rows = []
    for h in CUTOFF_HOURS:
        cutoff = _cutoff_utc(date_str, h)
        sub = df[df["ts"] <= cutoff].reset_index(drop=True)
        if len(sub) < 10:
            continue
        c = sub["close"].to_numpy(dtype=float) / 10000
        o = sub["open"].to_numpy(dtype=float) / 10000
        h_ = sub["high"].to_numpy(dtype=float) / 10000
        l = sub["low"].to_numpy(dtype=float) / 10000

        feats = {
            "date": date_str,
            "basis": basis,
            "weekday": date.strftime("%a"),
            "hour_uk": h,
            "cutoff_utc": cutoff.isoformat(),
            "close": round(c[-1], 5),
            "n_bars_so_far": len(sub),
        }
        feats.update(_price_action(c, o, h_, l, [12, 24, 48, len(c) - 1]))
        feats.update(_indicators(o, h_, l, c))
        feats.update(_structure(h_, l, c))
        feats.update(_asia_summary(df, date_str))
        feats.update(_calendar(date_str, cutoff))
        lvl = _structure_levels(date_str, c[-1])
        if lvl.get("atr14_pips"):
            day_range_so_far = (h_.max() - l.min()) * 10000
            lvl["atr_ratio_so_far"] = round(day_range_so_far / lvl["atr14_pips"], 2) \
                if lvl["atr14_pips"] else None
        feats.update(lvl)
        feats.update(_targets(df, cutoff, cen))
        rows.append(feats)
    return rows


def main():
    all_rows = []
    for p in sorted(CANDLES_EXT.glob("*.csv")):
        all_rows.extend(features_for_day(p, "BID"))
    for p in sorted(CANDLES_26.glob("*.csv")):
        all_rows.extend(features_for_day(p, "MID"))
    df = pd.DataFrame(all_rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"Wrote {len(df)} rows, {df.shape[1]} columns → {OUT}")
    print(f"Per hour: {df.hour_uk.value_counts().sort_index().to_dict()}")


if __name__ == "__main__":
    main()
