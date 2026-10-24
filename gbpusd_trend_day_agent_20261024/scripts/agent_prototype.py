#!/usr/bin/env python3
"""Trend Day Recognition Agent — research prototype.

Takes successive M5 bars (as emitted by candle_builder) for a single trading
day and, at each of the pre-registered decision times (07:00..12:00 UK),
emits a human-readable assessment:

  * trend-day probability (and 1-of-6 trend state)
  * expected direction and direction confidence
  * estimated remaining pips in the dominant direction
  * which features drove the assessment (top-5 SHAP-like contributions
    from gradient boosting)
  * which calendar events are relevant today
  * which structural levels matter

The internal model uses the per-hour GradientBoostingClassifier +
GradientBoostingRegressor fitted in `train_models.py`. The agent itself is a
thin wrapper that applies the models and renders the explanation.

Usage (CLI):

  python3 agent_prototype.py --date 2026-09-04

Reads the day's M5 file from the research corpus, runs the agent through all
decision hours, prints the explanation at each hour.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
from census import CANDLES_26, CANDLES_EXT, _load_day_file  # noqa: E402
from build_features import (  # noqa: E402
    CUTOFF_HOURS, _asia_summary, _calendar, _cutoff_utc, _indicators,
    _price_action, _structure, _structure_levels, _targets, cal_daily,
    cal_events, census, daily_struct,
)

MODELS = Path("<research_workspace>/models")

STATE_FROM_PROB = [
    (0.80, "CONFIRMED_TREND"),
    (0.65, "EMERGING_TREND"),
    (0.50, "PRE_TREND"),
    (0.35, "NEUTRAL"),
    (0.00, "NO_TREND"),
]


def _derive_state(trend_prob: float, direction_prob: float,
                  trend_already_pips: float, remaining_pips: float) -> dict:
    for thr, label in STATE_FROM_PROB:
        if trend_prob >= thr:
            base = label
            break
    direction = "LONG" if direction_prob >= 0.5 else "SHORT"
    direction_strength = max(direction_prob, 1 - direction_prob)
    # Transition descriptors
    descriptor = ""
    if base == "CONFIRMED_TREND" and remaining_pips < 15:
        base = "TREND_EXHAUSTION"
        descriptor = "most of the move is already behind us"
    elif base == "CONFIRMED_TREND" and trend_already_pips > 100 and remaining_pips < 25:
        base = "CONSOLIDATION"
        descriptor = "trend has produced a 100+ pip move and remaining upside is limited"
    return {"state": base, "direction": direction,
            "direction_strength": round(direction_strength, 3),
            "descriptor": descriptor}


def _top_shap(clf, X_row: np.ndarray, features: list[str], n: int = 5) -> list[dict]:
    """Approximate feature contributions by using the GBM's per-tree
    'margin contribution' decomposition. We approximate by looking at how much
    each feature's zero-ablation changes the predicted probability."""
    base = clf.predict_proba(X_row.reshape(1, -1))[0, 1]
    contribs = []
    for i, f in enumerate(features):
        x2 = X_row.copy()
        median_val = 0.0
        x2[i] = median_val
        altered = clf.predict_proba(x2.reshape(1, -1))[0, 1]
        contribs.append((f, base - altered, X_row[i]))
    contribs.sort(key=lambda t: -abs(t[1]))
    return [{"feature": f, "contribution": round(c, 3), "value": round(float(v), 3)}
            for f, c, v in contribs[:n]]


def run_agent_for_day(date_str: str):
    # locate file
    for path in (list(CANDLES_EXT.glob("*.csv")) + list(CANDLES_26.glob("*.csv"))):
        if date_str in path.name:
            # determine basis
            basis = "BID" if "candles_ext" in str(path) else "MID"
            df = _load_day_file(path, basis)
            break
    else:
        print(f"No data for {date_str}")
        return

    if df is None:
        print(f"Could not load {date_str}")
        return

    # Load the Dev-trained feature list — same construction as train_models.py
    df_full = pd.read_parquet(
        "<research_workspace>/outputs/features.parquet")
    df_full["is_mon"] = (df_full.weekday == "Mon").astype(int)
    df_full["is_tue"] = (df_full.weekday == "Tue").astype(int)
    df_full["is_wed"] = (df_full.weekday == "Wed").astype(int)
    df_full["is_thu"] = (df_full.weekday == "Thu").astype(int)
    df_full["is_fri"] = (df_full.weekday == "Fri").astype(int)
    EXCLUDE = {"date", "basis", "weekday", "hour_uk", "cutoff_utc", "close",
               "partition", "direction", "trend_day", "pips_target",
               "remaining_pips_in_dir", "trend_already_developed_pips",
               "asia_close", "asia_open"}
    features = [c for c in df_full.columns if c not in EXCLUDE]

    cen = census[census.date == date_str]
    if cen.empty:
        print(f"No census record for {date_str}")
        return
    cen_row = cen.iloc[0]

    print("=" * 72)
    print(f"GBPUSD Trend Day Recognition Agent — {date_str}")
    print(f"Basis: {basis}; weekday: {dt.date.fromisoformat(date_str).strftime('%A')}")
    print(f"Actual outcome: trend_day={cen_row.trend_day} "
          f"direction={cen_row.direction} magnitude={cen_row.pips} pips, "
          f"from {cen_row.anchor_time_utc[11:16]} → {cen_row.peak_time_utc[11:16]} UTC")
    print("=" * 72)

    # Build per-hour features by replicating build_features logic for one day
    for h in CUTOFF_HOURS:
        cutoff = _cutoff_utc(date_str, h)
        sub = df[df["ts"] <= cutoff].reset_index(drop=True)
        if len(sub) < 10:
            continue
        o = sub["open"].to_numpy(dtype=float) / 10000
        c = sub["close"].to_numpy(dtype=float) / 10000
        h_ = sub["high"].to_numpy(dtype=float) / 10000
        l = sub["low"].to_numpy(dtype=float) / 10000
        feats = {}
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
        # Day-of-week dummies
        wd = dt.date.fromisoformat(date_str).strftime("%a")
        for d_ in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
            feats[f"is_{d_.lower()}"] = int(wd == d_)
        # Fill features into a vector in the right order
        X_row = np.zeros(len(features), dtype=float)
        for i, name in enumerate(features):
            v = feats.get(name, 0.0)
            X_row[i] = 0.0 if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)

        clf = joblib.load(MODELS / f"trend_gbm_h{h:02d}.joblib")
        dir_clf = joblib.load(MODELS / f"dir_gbm_h{h:02d}.joblib")
        reg = joblib.load(MODELS / f"rem_gbr_h{h:02d}.joblib")

        trend_prob = float(clf.predict_proba(X_row.reshape(1, -1))[0, 1])
        dir_prob   = float(dir_clf.predict_proba(X_row.reshape(1, -1))[0, 1])  # P(LONG)
        rem_pips_pred = float(reg.predict(X_row.reshape(1, -1))[0])

        # Compute trend_already_pips (what the labelled run would give)
        trend_already_pips = feats.get("ret_full_pips") or 0.0
        state_info = _derive_state(trend_prob, dir_prob, abs(trend_already_pips), rem_pips_pred)

        # Explanation
        top5 = _top_shap(clf, X_row, features, n=5)

        # News context
        cal_row = cal_daily[cal_daily.date == date_str]
        news_label = cal_row.ext_label.iloc[0] if not cal_row.empty else "NORMAL"
        todays_evs = cal_events[cal_events.date == date_str]
        news_list = ", ".join(f"{r.event}({r.tier})" for _, r in todays_evs.iterrows()) \
                    or "none"

        # Structural levels
        sr = daily_struct[daily_struct.date == date_str]
        if not sr.empty:
            sr = sr.iloc[0]
            lvl_line = (f"PDH={sr.PDH:.5f}  PDL={sr.PDL:.5f}  PP={sr.PP:.5f}  "
                        f"R1={sr.R1:.5f}  S1={sr.S1:.5f}  ATR14={sr.atr14_pips:.1f}p")
        else:
            lvl_line = "no prior-day structure available"

        print(f"\n── {h:02d}:00 UK ───────────────────────────────────────")
        print(f"  P(trend day)        = {trend_prob:.2f}   state={state_info['state']}  "
              f"{state_info['descriptor']}")
        print(f"  Expected direction  = {state_info['direction']}  "
              f"(P(LONG)={dir_prob:.2f}  confidence={state_info['direction_strength']:.2f})")
        print(f"  Est. remaining pips = {rem_pips_pred:.0f}   (so-far-dir pips≈{trend_already_pips:.0f})")
        print(f"  News day label      = {news_label}   events today: {news_list}")
        print(f"  Structure           = {lvl_line}")
        print(f"  Top evidence:")
        for t in top5:
            print(f"      • {t['feature']}  value={t['value']}  Δp={t['contribution']:+.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="ISO date e.g. 2026-09-04")
    args = ap.parse_args()
    run_agent_for_day(args.date)


if __name__ == "__main__":
    main()
