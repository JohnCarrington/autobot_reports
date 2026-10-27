"""
Compute technical features at each level's `live_from` time, and tag
confluence with the Fib / control level price.

Features (all evaluated using ONLY bars completed before `live_from`):
  - Daily pivots from prior UTC day's HLC: P, S1, S2, S3, R1, R2, R3
  - H1 EMA20, EMA50 at the H1 bar closed just before `live_from`
  - H4 EMA20, EMA50 at the H4 bar closed just before `live_from`
  - Prior sessions' high/low (London 07-16 UTC, NY 12-21 UTC, Asia 22-07 UTC)
  - Recent swing extrema at the same TF (last K confirmed swings)

Confluence = feature within ±tol pips of level_price.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=1).mean()


def daily_pivots_from(prior_h: float, prior_l: float, prior_c: float) -> dict:
    """Classic floor pivots."""
    p = (prior_h + prior_l + prior_c) / 3.0
    r1 = 2 * p - prior_l
    s1 = 2 * p - prior_h
    r2 = p + (prior_h - prior_l)
    s2 = p - (prior_h - prior_l)
    r3 = prior_h + 2 * (p - prior_l)
    s3 = prior_l - 2 * (prior_h - p)
    return {"PP": p, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}


def build_daily_hlc(m5: pd.DataFrame) -> pd.DataFrame:
    """Return per-UTC-day H, L, C computed from M5 close."""
    df = m5.copy()
    df["date"] = df["timestamp"].dt.date
    g = df.groupby("date").agg(h=("high", "max"), l=("low", "min"), c=("close", "last"))
    g = g.reset_index()
    return g


def build_h1_emas(h1: pd.DataFrame) -> pd.DataFrame:
    h1 = h1.copy()
    h1["ema20"] = ema(h1["close"], 20)
    h1["ema50"] = ema(h1["close"], 50)
    return h1


def build_h4_emas(h4: pd.DataFrame) -> pd.DataFrame:
    h4 = h4.copy()
    h4["ema20"] = ema(h4["close"], 20)
    h4["ema50"] = ema(h4["close"], 50)
    return h4


def _session_extrema(m5: pd.DataFrame) -> dict:
    """For each UTC date, compute London/NY/Asia session H and L.

    London  07:00..16:00 UTC
    NY      12:00..21:00 UTC
    Asia    22:00..07:00 UTC next-day
    """
    df = m5.copy()
    df["date"] = df["timestamp"].dt.date
    df["hour"] = df["timestamp"].dt.hour
    london = df[(df["hour"] >= 7) & (df["hour"] < 16)].groupby("date").agg(h=("high","max"), l=("low","min"))
    ny = df[(df["hour"] >= 12) & (df["hour"] < 21)].groupby("date").agg(h=("high","max"), l=("low","min"))
    # Asia spans midnight — approximate as [22..07] per UTC date by day of entry: use the "night" (22..24) + next-day (00..07)
    df["asia_day"] = df["timestamp"].dt.date.where(df["hour"] < 22, df["timestamp"].dt.date + pd.Timedelta(days=1))
    asia = df[(df["hour"] >= 22) | (df["hour"] < 7)].groupby("asia_day").agg(h=("high","max"), l=("low","min"))
    return {"LSE": london, "NY": ny, "Asia": asia}


def nearest_feature(level: float, features: dict[str, float]) -> tuple[str, float]:
    """Return (name, pips_from_level) of nearest feature."""
    best_name, best_d = None, None
    for name, v in features.items():
        if v is None or np.isnan(v):
            continue
        d = abs(level - v)
        if best_d is None or d < best_d:
            best_d = d
            best_name = name
    return (best_name or "", float(best_d) if best_d is not None else float("nan"))


def enrich_levels_with_confluence(
    levels: pd.DataFrame,
    m5: pd.DataFrame,
    h1: pd.DataFrame,
    h4: pd.DataFrame,
) -> pd.DataFrame:
    """Add confluence feature columns to the levels DataFrame."""
    daily = build_daily_hlc(m5)
    daily["prev_date"] = daily["date"].shift(1)
    daily["prev_h"] = daily["h"].shift(1)
    daily["prev_l"] = daily["l"].shift(1)
    daily["prev_c"] = daily["c"].shift(1)

    h1e = build_h1_emas(h1)
    h4e = build_h4_emas(h4)

    sess = _session_extrema(m5)

    daily_by_date = daily.set_index("date")
    h1_ts = h1e["timestamp"].values.astype("datetime64[ns]")
    h4_ts = h4e["timestamp"].values.astype("datetime64[ns]")
    h1_ema20 = h1e["ema20"].values
    h1_ema50 = h1e["ema50"].values
    h4_ema20 = h4e["ema20"].values
    h4_ema50 = h4e["ema50"].values

    rows = []
    for _, lv in levels.iterrows():
        lf = pd.Timestamp(lv["live_from"])
        lp = float(lv["level_price"])
        d = lf.date()

        # Prior day pivots: use (d-1) HLC, which = prev_h/prev_l/prev_c of row with date==d
        prev = daily_by_date.loc[d] if d in daily_by_date.index else None
        if prev is None or pd.isna(prev["prev_h"]):
            pivots = {}
        else:
            pivots = daily_pivots_from(prev["prev_h"], prev["prev_l"], prev["prev_c"])

        # H1 EMAs: last H1 bar strictly before lf
        h1_idx = int(np.searchsorted(h1_ts, np.datetime64(lf.to_datetime64()), side="left")) - 1
        if h1_idx >= 0:
            h1_e20 = float(h1_ema20[h1_idx]); h1_e50 = float(h1_ema50[h1_idx])
        else:
            h1_e20 = h1_e50 = float("nan")

        h4_idx = int(np.searchsorted(h4_ts, np.datetime64(lf.to_datetime64()), side="left")) - 1
        if h4_idx >= 0:
            h4_e20 = float(h4_ema20[h4_idx]); h4_e50 = float(h4_ema50[h4_idx])
        else:
            h4_e20 = h4_e50 = float("nan")

        # Prior sessions (relative to the day BEFORE lf's date, so the signals are from completed sessions)
        prev_d = d - pd.Timedelta(days=1).to_pytimedelta()
        def _get(src, key):
            try:
                r = src.loc[prev_d]
                return float(r[key])
            except (KeyError, IndexError):
                return float("nan")
        lse_h = _get(sess["LSE"], "h"); lse_l = _get(sess["LSE"], "l")
        ny_h = _get(sess["NY"], "h"); ny_l = _get(sess["NY"], "l")
        asia_h = _get(sess["Asia"], "h"); asia_l = _get(sess["Asia"], "l")

        features = {
            **{f"pivot_{k}": v for k, v in pivots.items()},
            "h1_ema20": h1_e20, "h1_ema50": h1_e50,
            "h4_ema20": h4_e20, "h4_ema50": h4_e50,
            "prev_LSE_H": lse_h, "prev_LSE_L": lse_l,
            "prev_NY_H": ny_h, "prev_NY_L": ny_l,
            "prev_Asia_H": asia_h, "prev_Asia_L": asia_l,
        }

        row = {k: v for k, v in features.items()}
        # distance to each
        for name, v in features.items():
            row[f"dist_{name}"] = abs(lp - v) if not (v is None or np.isnan(v)) else float("nan")

        # Nearest-feature summary
        nf_name, nf_dist = nearest_feature(lp, features)
        row["nearest_feature"] = nf_name
        row["nearest_feature_dist"] = nf_dist

        # Confluence flags at a few bands
        for band in (3.0, 5.0, 10.0):
            flags = {k: (not np.isnan(row[f"dist_{k}"]) and row[f"dist_{k}"] <= band) for k in features}
            row[f"any_confluence_{int(band)}p"] = any(flags.values())
            row[f"n_confluence_{int(band)}p"] = sum(flags.values())
        rows.append(row)

    feat_df = pd.DataFrame(rows)
    return pd.concat([levels.reset_index(drop=True), feat_df.reset_index(drop=True)], axis=1)
