"""Addendum A2 — QM reversal signals overlaid on pivot zones and
measured on actual GBPUSD price action (2026-10-19 → 2026-11-03).

Loads /opt/tradingbot/logs/qm_reversal_signals.jsonl and the production
pivot ASK-bar snapshot /opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json.
For each GBPUSD signal:

  * nearest pivot to level_price (using the correct previous-day ASK bar
    for the signal date's pivots)
  * approach_dir implied by signal.side (BUY = reversing after a push
    DOWN, so approach_dir=DOWN; SELL = reversing after a push UP)
  * entry_feasibility — did a subsequent M5 bar cross entry_price?
  * mae_post_entry_pips, mfe_post_entry_pips
  * outcome_at_horizons — did price move signal.side * X pips within Y
    bars after entry_price was crossed?
  * practical_pnl_after_spread — using a fixed 1.5p GBPUSD spread
    assumption (round-trip cost) and a target == stop distance (1R) and
    2R rules
  * blocked_by_nms_v3 — directly from the signal's reason_codes

Outputs csv/addendum_a2_qm_outcomes.csv.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib

CANDLE_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
SIGNALS     = pathlib.Path("/opt/tradingbot/logs/qm_reversal_signals.jsonl")
PIVOT_CACHE = pathlib.Path("/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json")
OUT_CSV     = pathlib.Path(__file__).parent.parent / "csv" / "addendum_a2_qm_outcomes.csv"

PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")
SPREAD_PIPS = 1.5  # GBPUSD typical round-trip cost per the operator's spec

# Horizons for outcome measurement (post-entry)
HORIZONS_BARS = (6, 12, 24, 48)  # 30 min, 1 h, 2 h, 4 h

def pivots(H, L, C):
    P = (H + L + C) / 3.0
    return {
        "P":  P,
        "R1": 2 * P - L, "S1": 2 * P - H,
        "R2": P + (H - L), "S2": P - (H - L),
        "R3": H + 2 * (P - L), "S3": L - 2 * (H - P),
    }

def pts(x): return x / 10000.0

def load_day_candles(d: dt.date) -> list[dict]:
    rows = []
    f = CANDLE_ROOT / f"{d.isoformat()}.csv"
    if not f.exists(): return rows
    for row in csv.DictReader(f.open()):
        ts_raw = row["timestamp"].replace(" ", "T")
        try:
            ts = dt.datetime.fromisoformat(ts_raw)
        except ValueError:
            continue
        rows.append({
            "ts": ts,
            "o": float(row["open"])/10000.0,
            "h": float(row["high"])/10000.0,
            "l": float(row["low"])/10000.0,
            "c": float(row["close"])/10000.0,
        })
    return rows

def load_pivot_bars():
    """Return dict date_str -> {H, L, C} ASK-side daily OHLC."""
    d = json.loads(PIVOT_CACHE.read_text())
    out = {}
    for row in d["prices"]:
        date_s = row["snapshotTime"].split(" ")[0].replace("/", "-")
        H = pts(row["highPrice"]["ask"])
        L = pts(row["lowPrice"]["ask"])
        C = pts(row["closePrice"]["ask"])
        out[date_s] = (H, L, C)
    return out

def nearest_pivot(piv: dict[str, float], price: float):
    best = min(piv.items(), key=lambda kv: abs(kv[1] - price))
    return best[0], best[1], (price - best[1]) * 10000.0

def main() -> None:
    pivot_bars = load_pivot_bars()
    signals = [json.loads(l) for l in SIGNALS.open() if json.loads(l)["symbol"] == "GBPUSD"]
    print(f"Loaded {len(signals)} GBPUSD QM signals")
    print(f"Loaded {len(pivot_bars)} daily ASK bars for pivot computation")

    # Walk back to find most recent prior trading day
    def prior_date(d: dt.date) -> dt.date | None:
        for back in range(1, 8):
            cand = d - dt.timedelta(days=back)
            if cand.isoformat() in pivot_bars:
                return cand
        return None

    outcomes: list[dict] = []
    for s in signals:
        trig = dt.datetime.fromisoformat(s["trigger_ts"])
        d = trig.date()
        prev = prior_date(d)
        if prev is None:
            continue
        H, L, C = pivot_bars[prev.isoformat()]
        piv = pivots(H, L, C)
        entry = s["entry_price"] / 10000.0  # points -> FX decimal
        stop  = s["stop_price"] / 10000.0
        level = s["level_price"] / 10000.0
        stop_pips = s["stop_distance_pips"]
        nn, nnv, nn_delta = nearest_pivot(piv, level)
        side = s["side"]

        bars = load_day_candles(d)
        if not bars:
            continue
        # Find trigger bar
        trig_idx = None
        for i, b in enumerate(bars):
            if b["ts"] == trig.replace(tzinfo=dt.timezone.utc):
                trig_idx = i
                break
        if trig_idx is None:
            # fallback: first bar >= trig
            for i, b in enumerate(bars):
                if b["ts"] >= trig.replace(tzinfo=dt.timezone.utc):
                    trig_idx = i
                    break
        if trig_idx is None:
            continue

        # Entry feasibility: did a subsequent M5 bar touch entry_price?
        entry_hit_idx = None
        for i in range(trig_idx, min(trig_idx + 48, len(bars))):
            b = bars[i]
            if b["l"] <= entry <= b["h"]:
                entry_hit_idx = i
                break
        entry_feasible = entry_hit_idx is not None

        # If entry hit: measure MAE/MFE and multi-horizon outcomes
        outcome = {
            "ts": s["trigger_ts"],
            "side": side,
            "level_type": s.get("level_type", ""),
            "level_price": f"{level:.5f}",
            "nearest_pivot": nn,
            "nearest_pivot_value": f"{nnv:.5f}",
            "level_minus_nearest_pivot_pips": f"{nn_delta:+.1f}",
            "entry_price": f"{entry:.5f}",
            "stop_price": f"{stop:.5f}",
            "stop_distance_pips": f"{stop_pips:.1f}",
            "entry_feasible": int(entry_feasible),
            "nms_v3_allowed": int(s.get("nms_v3_allowed", False)),
            "blocked_by_nms_v3": int("blocked_by_nms_v3" in s.get("reason_codes", [])),
            "session_phase": s.get("daily_plan", {}).get("session_phase", ""),
            "hour_utc": trig.hour,
            "london_hour": (trig.hour) if trig.month in (11, 12, 1, 2) else (trig.hour + 1),
        }
        if entry_feasible:
            after = bars[entry_hit_idx:]
            if side == "BUY":
                mae = min(b["l"] for b in after) - entry
                mfe = max(b["h"] for b in after) - entry
            else:
                mae = entry - max(b["h"] for b in after)
                mfe = entry - min(b["l"] for b in after)
            outcome["mae_pips"] = f"{mae*10000:+.1f}"
            outcome["mfe_pips"] = f"{mfe*10000:+.1f}"
            # Horizon outcomes
            for h in HORIZONS_BARS:
                j = min(entry_hit_idx + h, len(bars) - 1)
                if side == "BUY":
                    hi = max(b["h"] for b in bars[entry_hit_idx:j + 1])
                    outcome[f"outcome_{h}b_pips"] = f"{(hi - entry) * 10000:+.1f}"
                else:
                    lo = min(b["l"] for b in bars[entry_hit_idx:j + 1])
                    outcome[f"outcome_{h}b_pips"] = f"{(entry - lo) * 10000:+.1f}"
            # Practical outcomes
            # 1R rule: TP = stop_pips, SL = stop_pips. First touch wins. After spread.
            stop_price_val = stop
            tp_1R = entry + (stop_pips / 10000.0) if side == "BUY" else entry - (stop_pips / 10000.0)
            tp_2R = entry + (2 * stop_pips / 10000.0) if side == "BUY" else entry - (2 * stop_pips / 10000.0)
            # Measure which touches first
            hit_sl_1R = None; hit_tp_1R = None; hit_tp_2R = None
            for i, b in enumerate(after):
                if hit_sl_1R is None and ((side == "BUY" and b["l"] <= stop_price_val)
                                          or (side == "SELL" and b["h"] >= stop_price_val)):
                    hit_sl_1R = i
                if hit_tp_1R is None and ((side == "BUY" and b["h"] >= tp_1R)
                                          or (side == "SELL" and b["l"] <= tp_1R)):
                    hit_tp_1R = i
                if hit_tp_2R is None and ((side == "BUY" and b["h"] >= tp_2R)
                                          or (side == "SELL" and b["l"] <= tp_2R)):
                    hit_tp_2R = i
                if hit_sl_1R is not None and hit_tp_1R is not None and hit_tp_2R is not None:
                    break
            # 1R rule net pips: tp_pips - spread vs -stop_pips - spread
            def resolve_1R():
                if hit_tp_1R is not None and (hit_sl_1R is None or hit_tp_1R < hit_sl_1R):
                    return stop_pips - SPREAD_PIPS
                if hit_sl_1R is not None:
                    return -stop_pips - SPREAD_PIPS
                return None  # unresolved in intraday window
            def resolve_2R():
                if hit_tp_2R is not None and (hit_sl_1R is None or hit_tp_2R < hit_sl_1R):
                    return 2 * stop_pips - SPREAD_PIPS
                if hit_sl_1R is not None:
                    return -stop_pips - SPREAD_PIPS
                return None
            r1 = resolve_1R()
            r2 = resolve_2R()
            outcome["net_pips_1R_after_spread"] = f"{r1:+.1f}" if r1 is not None else "UNRESOLVED"
            outcome["net_pips_2R_after_spread"] = f"{r2:+.1f}" if r2 is not None else "UNRESOLVED"
        outcomes.append(outcome)

    print(f"Processed {len(outcomes)} GBPUSD signals")

    # Summary
    from collections import Counter
    print(f"\nEntry feasible: {sum(o.get('entry_feasible', 0) for o in outcomes)} / {len(outcomes)}")
    print(f"Blocked by NMS: {sum(o.get('blocked_by_nms_v3', 0) for o in outcomes)}")
    print(f"By nearest-pivot: {Counter(o['nearest_pivot'] for o in outcomes).most_common()}")
    print(f"By side: {Counter(o['side'] for o in outcomes).most_common()}")

    # 1R outcomes for feasible trades
    r1_vals = [float(o["net_pips_1R_after_spread"]) for o in outcomes
               if o.get("entry_feasible") and o.get("net_pips_1R_after_spread") not in (None, "UNRESOLVED")]
    r2_vals = [float(o["net_pips_2R_after_spread"]) for o in outcomes
               if o.get("entry_feasible") and o.get("net_pips_2R_after_spread") not in (None, "UNRESOLVED")]
    if r1_vals:
        wins_1R = sum(1 for v in r1_vals if v > 0)
        print(f"\n1R resolved: {len(r1_vals)}  wins={wins_1R}  win_rate={100*wins_1R/len(r1_vals):.1f}%  "
              f"total_net_pips={sum(r1_vals):+.1f}  mean={sum(r1_vals)/len(r1_vals):+.1f}p")
    if r2_vals:
        wins_2R = sum(1 for v in r2_vals if v > 0)
        print(f"2R resolved: {len(r2_vals)}  wins={wins_2R}  win_rate={100*wins_2R/len(r2_vals):.1f}%  "
              f"total_net_pips={sum(r2_vals):+.1f}  mean={sum(r2_vals)/len(r2_vals):+.1f}p")

    # Save
    if outcomes:
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        # Find union of keys
        all_keys = []
        for o in outcomes:
            for k in o.keys():
                if k not in all_keys:
                    all_keys.append(k)
        with OUT_CSV.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=all_keys)
            w.writeheader()
            for o in outcomes:
                w.writerow({k: o.get(k, "") for k in all_keys})
        print(f"\nWrote {OUT_CSV}")

if __name__ == "__main__":
    main()
