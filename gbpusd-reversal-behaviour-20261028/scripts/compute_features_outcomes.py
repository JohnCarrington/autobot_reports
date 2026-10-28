"""Compute point-in-time features + measured outcomes + entry feasibility.

For each of the 20 selected events, this script writes:

    reversal_event_features.csv   — characteristics computed from bars
                                     at or before the event (no look-ahead).
    reversal_outcomes.csv         — MFE / MAE over +30 and +60 min and
                                     final outcome category.
    entry_feasibility.csv         — the earliest observable confirmation
                                     point for each candidate; SL survival;
                                     time to +15/+30/+50 pips.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Bar, bollinger, ema, macd, read_bid_m5, rsi


ROUND_LEVEL_INCREMENT_PTS = 50.0  # 00 / 50 psychological levels (50 pts = half-cent)
STRUCT_PROXIMITY_PTS = 10.0        # "near" a level if within 10 points


# ─────────────────────────────────────────────────────────────────────
# Feature extraction (uses bars[0 .. event_idx] only)
# ─────────────────────────────────────────────────────────────────────
def _features(bars: list[Bar], event_idx: int, kind: str,
              session_bars: list[Bar], prev_day: list[Bar] | None) -> dict:
    b = bars[event_idx]
    closes = [x.close for x in bars[:event_idx + 1]]
    bb_low, bb_mid, bb_up = bollinger(closes, 20, 2.0)
    _, _, hist = macd(closes, 12, 26, 9)
    rsi_series = rsi(closes, 14)
    ema7 = ema(closes, 7)
    ema13 = ema(closes, 13)
    ema21 = ema(closes, 21)

    # A. Failed-continuation — attempts to extend beyond the previous extreme
    look = bars[max(0, event_idx - 60):event_idx]  # 5h lookback (excl. event)
    if kind == "BULL":
        prior_low = min(x.low for x in look) if look else b.low
        # extensions = bars among last 24 that made a new low vs the lookback low
        exts = [x for x in bars[max(0, event_idx - 24):event_idx]
                if x.low < prior_low]
        extend_distance = (prior_low - b.low) if b.low < prior_low else 0.0
    else:
        prior_high = max(x.high for x in look) if look else b.high
        exts = [x for x in bars[max(0, event_idx - 24):event_idx]
                if x.high > prior_high]
        extend_distance = (b.high - prior_high) if b.high > prior_high else 0.0

    # B. Repeated tests — count prior bars within 2 pts of the extreme
    tol = 2.0
    if kind == "BULL":
        tests = [x for x in look if x.low <= prior_low + tol]
    else:
        tests = [x for x in look if x.high >= prior_high - tol]
    # Time since the most recent prior test
    if tests:
        bars_since_prev_test = event_idx - bars.index(tests[-1])
    else:
        bars_since_prev_test = -1

    # C. Momentum exhaustion
    bb_width = (bb_up[event_idx] - bb_low[event_idx]) \
        if (bb_up[event_idx] is not None and bb_low[event_idx] is not None) else None
    bb_breach = (bb_low[event_idx] is not None and b.low <= bb_low[event_idx]) if kind == "BULL" \
        else (bb_up[event_idx] is not None and b.high >= bb_up[event_idx])
    # MACD contraction over last 3 bars
    macd_contraction = None
    if event_idx >= 3 and hist[event_idx] is not None and hist[event_idx - 3] is not None:
        if kind == "BULL":
            macd_contraction = (hist[event_idx] - hist[event_idx - 3]) > 0  # histogram rising from a low
        else:
            macd_contraction = (hist[event_idx] - hist[event_idx - 3]) < 0

    # D. Momentum transfer — body + wick contrast between the extreme bar
    #    and its immediate predecessors.  "Strong" countertrend if the
    #    event bar itself closed in the opposite direction of the run.
    strong_countertrend_bar = (b.is_green if kind == "BULL" else b.is_red) and b.body > 5.0
    lower_wick_ratio = (b.lower_wick / b.range) if b.range > 0 else 0.0
    upper_wick_ratio = (b.upper_wick / b.range) if b.range > 0 else 0.0
    long_tail = (lower_wick_ratio if kind == "BULL" else upper_wick_ratio) > 0.5

    # Body contraction — average body of last 3 bars vs prior 3
    def _avg_body(seq):
        return sum(x.body for x in seq) / max(1, len(seq))
    last3 = bars[event_idx - 2:event_idx + 1]
    prior3 = bars[event_idx - 5:event_idx - 2] if event_idx >= 5 else []
    body_contraction = (_avg_body(last3) < _avg_body(prior3)) if prior3 else None

    # E. Structural location
    # 00/50 round-level proximity (points scale means 50 pts = .0050 price)
    if kind == "BULL":
        base_px = b.low
    else:
        base_px = b.high
    nearest_round = round(base_px / ROUND_LEVEL_INCREMENT_PTS) * ROUND_LEVEL_INCREMENT_PTS
    near_round = abs(base_px - nearest_round) <= STRUCT_PROXIMITY_PTS
    # Session HL from the current session only (bars from 06:00 onwards same day)
    session_high = max((x.high for x in session_bars if x.ts < b.ts), default=None)
    session_low = min((x.low for x in session_bars if x.ts < b.ts), default=None)
    near_session_extreme = False
    if kind == "BULL" and session_low is not None:
        near_session_extreme = abs(b.low - session_low) <= STRUCT_PROXIMITY_PTS
    elif kind == "BEAR" and session_high is not None:
        near_session_extreme = abs(b.high - session_high) <= STRUCT_PROXIMITY_PTS
    # Previous-day HL
    pd_high = max((x.high for x in prev_day), default=None) if prev_day else None
    pd_low = min((x.low for x in prev_day), default=None) if prev_day else None
    near_prev_day_extreme = False
    if kind == "BULL" and pd_low is not None:
        near_prev_day_extreme = abs(b.low - pd_low) <= STRUCT_PROXIMITY_PTS
    elif kind == "BEAR" and pd_high is not None:
        near_prev_day_extreme = abs(b.high - pd_high) <= STRUCT_PROXIMITY_PTS

    return {
        # Failed continuation
        "A_extend_distance_pts": round(extend_distance, 2),
        "A_n_extension_bars": len(exts),
        # Repeated tests
        "B_n_prior_tests_in_5h": len(tests),
        "B_bars_since_prev_test": bars_since_prev_test,
        # Momentum exhaustion
        "C_bb_width_pts": round(bb_width, 2) if bb_width else None,
        "C_bb_breach_at_event": bool(bb_breach),
        "C_macd_hist": round(hist[event_idx], 3) if hist[event_idx] is not None else None,
        "C_macd_hist_contracting_3b": macd_contraction,
        "C_rsi_at_event": round(rsi_series[event_idx], 1) if rsi_series[event_idx] is not None else None,
        "C_body_contracting_3b_vs_prev3": body_contraction,
        # Momentum transfer
        "D_strong_countertrend_bar": strong_countertrend_bar,
        "D_long_tail": long_tail,
        "D_lower_wick_ratio": round(lower_wick_ratio, 2),
        "D_upper_wick_ratio": round(upper_wick_ratio, 2),
        "D_ema7_rising": None if event_idx < 2 or ema7[event_idx] is None or ema7[event_idx - 2] is None
            else ((ema7[event_idx] > ema7[event_idx - 2]) if kind == "BULL"
                  else (ema7[event_idx] < ema7[event_idx - 2])),
        # Structural
        "E_near_00_or_50_level": near_round,
        "E_round_level_pts": nearest_round,
        "E_near_session_extreme": near_session_extreme,
        "E_near_prev_day_extreme": near_prev_day_extreme,
    }


# ─────────────────────────────────────────────────────────────────────
# Outcome measurement
# ─────────────────────────────────────────────────────────────────────
def _outcomes(bars: list[Bar], event_idx: int, kind: str) -> dict:
    extreme = bars[event_idx].low if kind == "BULL" else bars[event_idx].high
    event_close = bars[event_idx].close
    out = {}
    for horizon_min, horizon_bars in [(30, 6), (60, 12)]:
        end = min(event_idx + horizon_bars, len(bars) - 1)
        window = bars[event_idx + 1:end + 1]
        if not window:
            continue
        if kind == "BULL":
            mfe = max(x.high for x in window) - event_close
            mae = event_close - min(x.low for x in window)
            broke_extreme = min(x.low for x in window) < extreme
        else:
            mfe = event_close - min(x.low for x in window)
            mae = max(x.high for x in window) - event_close
            broke_extreme = max(x.high for x in window) > extreme
        out[f"mfe_{horizon_min}min_pts"] = round(mfe, 2)
        out[f"mae_{horizon_min}min_pts"] = round(mae, 2)
        out[f"broke_extreme_within_{horizon_min}min"] = bool(broke_extreme)
    return out


# ─────────────────────────────────────────────────────────────────────
# Entry feasibility — the earliest observable confirmation
# ─────────────────────────────────────────────────────────────────────
def _entry_feasibility(bars: list[Bar], event_idx: int, kind: str) -> dict:
    """The earliest EMA7 cross after the event is the proxy for the
    'first observable confirmation'.  We report the price at that bar
    (treated as the executable entry) and measure MFE/MAE and SL
    survival from that bar."""
    closes = [x.close for x in bars[:min(event_idx + 60, len(bars))]]
    ema7 = ema(closes, 7)
    entry_bar_idx = None
    for i in range(event_idx + 1, min(event_idx + 12, len(bars))):
        if ema7[i] is None:
            continue
        if kind == "BULL" and bars[i].close > ema7[i]:
            entry_bar_idx = i
            break
        if kind == "BEAR" and bars[i].close < ema7[i]:
            entry_bar_idx = i
            break
    if entry_bar_idx is None:
        return {"feasible": False, "reason": "no_ema7_cross_within_60min"}
    entry_bar = bars[entry_bar_idx]
    entry_price = entry_bar.close
    extreme = bars[event_idx].low if kind == "BULL" else bars[event_idx].high

    # Horizons from the ENTRY bar
    out = {
        "feasible": True,
        "entry_bar_ts_utc": entry_bar.ts.isoformat(),
        "entry_price_pts": entry_price,
        "distance_from_extreme_pts": round(abs(entry_price - extreme), 2),
    }
    # Time to +15/+30/+50
    for target in [15, 30, 50]:
        hit = None
        for j in range(entry_bar_idx + 1, min(entry_bar_idx + 24, len(bars))):
            if kind == "BULL" and bars[j].high >= entry_price + target:
                hit = (bars[j].ts - entry_bar.ts).total_seconds() / 60.0
                break
            if kind == "BEAR" and bars[j].low <= entry_price - target:
                hit = (bars[j].ts - entry_bar.ts).total_seconds() / 60.0
                break
        out[f"min_to_{target}pts"] = hit  # minutes

    # SL survival over 60 min from entry
    for sl in [4, 6, 8, 12]:
        survived = True
        for j in range(entry_bar_idx + 1, min(entry_bar_idx + 12, len(bars))):
            if kind == "BULL" and bars[j].low <= entry_price - sl:
                survived = False
                break
            if kind == "BEAR" and bars[j].high >= entry_price + sl:
                survived = False
                break
        out[f"sl_{sl}pt_survives_60min"] = survived
    return out


def main() -> int:
    sample_path = HERE.parent / "data" / "reversal_event_population.csv"
    sample = list(csv.DictReader(sample_path.open()))

    features_rows = []
    outcomes_rows = []
    feasibility_rows = []

    # Add today's two events (A and B) to the output, even though they
    # weren't in the sample selection — the brief asks for a detailed
    # Oct 28 case study.
    today_events = [
        {"date": "2026-10-28", "event_ts_utc": "2026-10-28T07:15:00+00:00",
         "kind": "BULL", "outcome_label": "ANALYSIS_CASE_STUDY_A"},
        {"date": "2026-10-28", "event_ts_utc": "2026-10-28T11:00:00+00:00",
         "kind": "BULL", "outcome_label": "ANALYSIS_CASE_STUDY_B"},
    ]
    all_events = sample + today_events

    for row in all_events:
        date = datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        try:
            bars = read_bid_m5(date)
        except FileNotFoundError:
            # 2026 — fall back to MID candles (today) for the case study
            from common import read_mid_m5
            bars = read_mid_m5(date)
        prev_date = date - timedelta(days=1)
        try:
            prev_bars = read_bid_m5(prev_date)
        except FileNotFoundError:
            try:
                from common import read_mid_m5
                prev_bars = read_mid_m5(prev_date)
            except FileNotFoundError:
                prev_bars = []
        ts_to_idx = {b.ts.isoformat(): i for i, b in enumerate(bars)}
        idx = ts_to_idx.get(row["event_ts_utc"])
        if idx is None:
            continue
        kind = row["kind"]

        # Session bars = same day up to the event
        session_bars = [b for b in bars[:idx] if b.ts.hour >= 6]

        feats = _features(bars, idx, kind, session_bars, prev_bars)
        features_rows.append({
            **{k: row[k] for k in ("date", "event_ts_utc", "kind", "outcome_label")},
            **feats,
        })
        if "CASE_STUDY" not in row["outcome_label"]:
            outcomes = _outcomes(bars, idx, kind)
            outcomes_rows.append({
                **{k: row[k] for k in ("date", "event_ts_utc", "kind", "outcome_label")},
                **outcomes,
            })
        feas = _entry_feasibility(bars, idx, kind)
        feasibility_rows.append({
            **{k: row[k] for k in ("date", "event_ts_utc", "kind", "outcome_label")},
            **feas,
        })

    for name, rows in [
        ("reversal_event_features.csv", features_rows),
        ("reversal_outcomes.csv", outcomes_rows),
        ("entry_feasibility.csv", feasibility_rows),
    ]:
        out = HERE.parent / "data" / name
        if not rows:
            continue
        # Collect union of all keys so rows with sparse fields don't fail
        all_keys: list[str] = []
        seen: set[str] = set()
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    all_keys.append(k)
                    seen.add(k)
        with out.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=all_keys)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in all_keys})
        print(f"✓ wrote {name} ({len(rows)} rows)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
