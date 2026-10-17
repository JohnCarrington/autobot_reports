"""Point-in-time observational-tag computation for V3 GBPUSD entries.

For each V3 signal_log entry, compute:
  TREND EXHAUSTION tags (from signal_log directly):
    - stretch_atr_at_fire
    - price_vs_daily_open
    - day_range_so_far_pips
    - day_net_so_far_pips
    - regime_at_fire + regime_confidence_at_fire
    - atr_vs_20day_avg

  PRICE REJECTION tags (from M5 archive at decision_ts):
    - prev_bar_upper_wick_pips
    - prev_bar_lower_wick_pips
    - prev_bar_body_pips
    - prev_bar_range_pips
    - prev_bar_dominant_wick (UPPER/LOWER/BALANCED)
    - prev_bar_wick_body_ratio (dominant wick / body; floor body at 0.1p)
    - prev_bar_wick_range_pct (dominant wick / range * 100)
    - prev_bar_rejection_against_entry (True iff dominant wick opposes trade direction)

  STRUCTURAL PROXIMITY tags (from FX-day pivots + round-number grids):
    - signed dist_to_P, R1, R2, R3, S1, S2, S3 (abs values + above/below)
    - abs_dist_to_pdh, abs_dist_to_pdl
    - nearest_pivot_name + nearest_pivot_abs_dist_pips
    - nearest_opposing_pivot (above for BUY, below for SELL) + distance
    - abs_dist_to_round_10, round_50, round_100
    - nearest_opposing_round_50 + distance   (operator-highlighted .50 handles)

All features are point-in-time: no bar with ts > decision_ts is read.
TAGS ONLY — no admission/rejection/modification.  Pure observation.
"""
from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, "/opt/tradingbot")
from ig_daily_pivots import compute_classic_floor  # frozen pivot formula

CANDLE_ROOT = Path("/opt/tradingbot/data/candles/GBPUSD")
PIPS_PER_POINT = 1.0  # archive stores price × 10_000; 1 unit = 1 pip

V3_STRATEGIES = {
    "GBPUSD_TREND_V3_L", "GBPUSD_TREND_V3_S",
    "GBPUSD_TREND_V3_UM_L", "GBPUSD_TREND_V3_UM_S",
    "V3_BB_L", "V3_BB_S", "V3_EMA_L", "V3_EMA_S",
    "V3_EMA_PULLBACK_L", "V3_EMA_PULLBACK_S",
}


# ───── Candle loading ─────────────────────────────────────────────────────
def _load_day(d: date) -> List[Dict[str, Any]]:
    p = CANDLE_ROOT / f"{d.isoformat()}.csv"
    if not p.exists():
        return []
    with open(p) as f:
        r = csv.DictReader(f)
        out = []
        for row in r:
            try:
                out.append({
                    "ts": datetime.fromisoformat(row["timestamp"]),
                    "o": float(row["open"]),
                    "h": float(row["high"]),
                    "l": float(row["low"]),
                    "c": float(row["close"]),
                })
            except Exception:
                continue
    return out


def _fx_day_label(ts: datetime) -> date:
    """[D-1 22:00, D 22:00) → label D."""
    if ts.hour >= 22:
        return (ts + timedelta(days=1)).date()
    return ts.date()


def _prior_fx_d1_ohlc(decision_ts: datetime) -> Optional[Tuple[float, float, float]]:
    """Return (H, L, C) of the FX day STRICTLY BEFORE the decision_ts's FX day.
    Builds the bar from M5 archive on [prev_prev 22:00, prev 22:00) UTC.
    Returns None if the window isn't fully available.
    """
    this_fx = _fx_day_label(decision_ts)
    prev_fx = this_fx - timedelta(days=1)
    # Walk back if prev is weekend
    while prev_fx.weekday() >= 5:
        prev_fx = prev_fx - timedelta(days=1)
    start_date = prev_fx - timedelta(days=1)
    bars = _load_day(start_date) + _load_day(prev_fx)
    if not bars:
        return None
    start_ts = datetime(prev_fx.year, prev_fx.month, prev_fx.day,
                        tzinfo=timezone.utc) - timedelta(hours=2)
    end_ts = datetime(prev_fx.year, prev_fx.month, prev_fx.day, 22,
                      tzinfo=timezone.utc)
    window = [b for b in bars if start_ts <= b["ts"] < end_ts]
    if not window:
        return None
    H = max(b["h"] for b in window)
    L = min(b["l"] for b in window)
    C = window[-1]["c"]
    return (H, L, C)


# ───── Price-rejection features ───────────────────────────────────────────
def _prev_completed_m5(decision_ts: datetime) -> Optional[Dict[str, Any]]:
    """Return the most recent completed M5 bar strictly before decision_ts.
    A bar at ts T is 'completed' at T + 5 min.  decision_ts must be past T+5min.
    """
    # Load this day and previous day (overnight boundary)
    d = decision_ts.date()
    bars = _load_day(d - timedelta(days=1)) + _load_day(d)
    if not bars:
        return None
    # A bar at ts=T completes at T+5min
    cutoff = decision_ts
    completed = [b for b in bars if b["ts"] + timedelta(minutes=5) <= cutoff]
    return completed[-1] if completed else None


def _rejection_features(prev_bar: Dict[str, Any], entry_dir: str) -> Dict[str, Any]:
    h, l, o, c = prev_bar["h"], prev_bar["l"], prev_bar["o"], prev_bar["c"]
    body_top = max(o, c)
    body_bot = min(o, c)
    upper_wick = (h - body_top) / PIPS_PER_POINT
    lower_wick = (body_bot - l) / PIPS_PER_POINT
    body = abs(c - o) / PIPS_PER_POINT
    rng = (h - l) / PIPS_PER_POINT

    if rng <= 0:
        dominant = "BALANCED"
        wick_body_ratio = None
        wick_range_pct = None
    elif upper_wick > lower_wick * 1.5:
        dominant = "UPPER"
    elif lower_wick > upper_wick * 1.5:
        dominant = "LOWER"
    else:
        dominant = "BALANCED"

    dominant_wick = upper_wick if dominant == "UPPER" else (lower_wick if dominant == "LOWER" else max(upper_wick, lower_wick))
    body_floor = max(body, 0.1)
    wick_body_ratio = dominant_wick / body_floor if rng > 0 else None
    wick_range_pct = dominant_wick / rng * 100 if rng > 0 else None

    # Against-entry test:
    # BUY against = UPPER-wick rejection (sellers rejected higher prices)
    # SELL against = LOWER-wick rejection
    rejection_against = (
        (entry_dir == "BUY" and dominant == "UPPER") or
        (entry_dir == "SELL" and dominant == "LOWER")
    )

    return {
        "prev_bar_ts": prev_bar["ts"].isoformat(),
        "prev_bar_upper_wick_pips": round(upper_wick, 2),
        "prev_bar_lower_wick_pips": round(lower_wick, 2),
        "prev_bar_body_pips": round(body, 2),
        "prev_bar_range_pips": round(rng, 2),
        "prev_bar_dominant_wick": dominant,
        "prev_bar_wick_body_ratio": round(wick_body_ratio, 2) if wick_body_ratio is not None else None,
        "prev_bar_wick_range_pct": round(wick_range_pct, 1) if wick_range_pct is not None else None,
        "prev_bar_rejection_against_entry": rejection_against,
    }


# ───── Structural proximity features ──────────────────────────────────────
def _structural_features(entry: float, decision_ts: datetime, entry_dir: str
                         ) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    prior = _prior_fx_d1_ohlc(decision_ts)
    pivots: Dict[str, float] = {}
    if prior:
        H, L, C = prior
        p = compute_classic_floor(H, L, C)
        pivots = {"P": p.P, "R1": p.R1, "R2": p.R2, "R3": p.R3,
                  "S1": p.S1, "S2": p.S2, "S3": p.S3}
        out["prior_fx_d1_H"] = round(H, 2)
        out["prior_fx_d1_L"] = round(L, 2)
        out["prior_fx_d1_C"] = round(C, 2)
        for name, px in pivots.items():
            d_pips = (px - entry) / PIPS_PER_POINT
            out[f"signed_dist_to_{name}_pips"] = round(d_pips, 2)
        out["abs_dist_to_pdh_pips"] = round(abs(H - entry) / PIPS_PER_POINT, 2)
        out["abs_dist_to_pdl_pips"] = round(abs(L - entry) / PIPS_PER_POINT, 2)
    else:
        out["prior_fx_d1_H"] = None
        out["prior_fx_d1_L"] = None
        out["prior_fx_d1_C"] = None

    # Nearest pivot by absolute distance
    if pivots:
        pivots_full = dict(pivots)
        if prior:
            pivots_full["PDH"] = prior[0]
            pivots_full["PDL"] = prior[1]
        name_min = min(pivots_full, key=lambda k: abs(pivots_full[k] - entry))
        out["nearest_pivot_name"] = name_min
        out["nearest_pivot_abs_dist_pips"] = round(abs(pivots_full[name_min] - entry) / PIPS_PER_POINT, 2)
        # Nearest opposing (above for BUY, below for SELL)
        if entry_dir == "BUY":
            opposing = {k: v for k, v in pivots_full.items() if v > entry}
        else:
            opposing = {k: v for k, v in pivots_full.items() if v < entry}
        if opposing:
            opp_name = min(opposing, key=lambda k: abs(opposing[k] - entry))
            out["nearest_opposing_pivot_name"] = opp_name
            out["nearest_opposing_pivot_abs_dist_pips"] = round(abs(opposing[opp_name] - entry) / PIPS_PER_POINT, 2)
        else:
            out["nearest_opposing_pivot_name"] = None
            out["nearest_opposing_pivot_abs_dist_pips"] = None

    # Round grids (10 / 50 / 100 pip)
    for step in (10, 50, 100):
        step_units = step * PIPS_PER_POINT
        nearest = round(entry / step_units) * step_units
        out[f"abs_dist_to_round_{step}_pips"] = round(abs(entry - nearest) / PIPS_PER_POINT, 2)
        # Opposing
        if entry_dir == "BUY":
            # Opposing = above
            above = (int(entry // step_units) + 1) * step_units
            if above <= entry:
                above += step_units
            out[f"abs_dist_to_opposing_round_{step}_pips"] = round((above - entry) / PIPS_PER_POINT, 2)
        else:
            below = int(entry // step_units) * step_units
            if below >= entry:
                below -= step_units
            out[f"abs_dist_to_opposing_round_{step}_pips"] = round((entry - below) / PIPS_PER_POINT, 2)

    return out


# ───── Main pipeline ──────────────────────────────────────────────────────
def process_entries(signal_log: Path, out_path: Path) -> int:
    rows_out: List[Dict[str, Any]] = []
    skipped_no_bar = 0
    with open(signal_log) as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            if j.get("pair") != "GBPUSD":
                continue
            if j.get("strategy") not in V3_STRATEGIES:
                continue
            ts_open = j.get("timestamp_open")
            if not ts_open:
                continue
            # Parse decision timestamp
            decision_ts = datetime.fromisoformat(ts_open.replace("Z", "+00:00"))

            # Base signal-log fields
            row = {
                "id": j.get("id"),
                "deal_id": j.get("deal_id"),
                "timestamp_open": ts_open,
                "timestamp_close": j.get("timestamp_close"),
                "strategy": j.get("strategy"),
                "direction": j.get("direction"),
                "entry": j.get("entry"),
                "sl": j.get("sl"),
                "sl_pips": j.get("sl_pips"),
                "tp1_pips": j.get("tp1_pips"),
                "regime_at_fire": j.get("regime_at_fire"),
                "regime_confidence_at_fire": j.get("regime_confidence_at_fire"),
                "stretch_atr_at_fire": j.get("stretch_atr_at_fire"),
                "atr_at_fire": j.get("atr_at_fire"),
                "atr_vs_20day_avg": j.get("atr_vs_20day_avg"),
                "price_vs_daily_open": j.get("price_vs_daily_open"),
                "day_range_so_far_pips": j.get("day_range_so_far_pips"),
                "day_net_so_far_pips": j.get("day_net_so_far_pips"),
                "session_name": j.get("session_name"),
                "entry_candle_pattern": j.get("entry_candle_pattern"),
                "entry_candle_body_pct": j.get("entry_candle_body_pct"),
                "entry_candle_wick_ratio": j.get("entry_candle_wick_ratio"),
                "mfe_pips": j.get("mfe_pips"),
                "mae_pips": j.get("mae_pips"),
                "pnl_pips": j.get("pnl_pips"),
                "close_price": j.get("close_price"),
                "close_type": (j.get("close_type") or "")[:60],
                "close_reason": (j.get("close_reason") or "")[:60],
                "duration_minutes": j.get("duration_minutes"),
            }
            # Previous completed M5 bar
            prev_bar = _prev_completed_m5(decision_ts)
            if prev_bar is None:
                row["prev_bar_available"] = False
                skipped_no_bar += 1
            else:
                row["prev_bar_available"] = True
                row.update(_rejection_features(prev_bar, j.get("direction", "BUY")))
            # Structural proximity
            if j.get("entry") is not None:
                row.update(_structural_features(float(j["entry"]), decision_ts,
                                                 j.get("direction", "BUY")))
            rows_out.append(row)

    # Write JSONL
    with open(out_path, "w") as f:
        for r in rows_out:
            f.write(json.dumps(r, default=str) + "\n")
    return len(rows_out)


if __name__ == "__main__":
    sl = Path("/opt/tradingbot/logs/signal_log.jsonl")
    out = Path(__file__).parent.parent / "data" / "v3_entries_tagged.jsonl"
    out.parent.mkdir(exist_ok=True)
    n = process_entries(sl, out)
    print(f"wrote {out}  ({n} rows)")
