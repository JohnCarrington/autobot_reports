"""
Read-only audit: enumerate BB pierce events on GBPUSD 5m bars for a single day,
produce 9-bar context (N-3 .. N+6) and pattern classification.

Data source: data/candles/GBPUSD/<date>.csv (raw OHLC, no BB)
BB(20,2) computed on a rolling window over close prices, warmed up from the
prior trading day so the first window bar (07:00 UTC) sees a fully-warm BB.
"""
from __future__ import annotations
import csv
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path
from typing import List, Optional
import math

PIP = 1.0  # GBPUSD: 1 IG point = 1 pip

DATA_DIR = Path("/opt/tradingbot/data/candles/GBPUSD")

def load_day(date: str) -> list:
    p = DATA_DIR / f"{date}.csv"
    rows = []
    with p.open() as f:
        rd = csv.DictReader(f)
        for r in rd:
            rows.append({
                "ts": datetime.fromisoformat(r["timestamp"]).astimezone(timezone.utc),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            })
    rows.sort(key=lambda b: b["ts"])
    # de-dupe by ts (keep last)
    out = []
    last_ts = None
    for b in rows:
        if last_ts is not None and b["ts"] == last_ts:
            out[-1] = b
        else:
            out.append(b)
            last_ts = b["ts"]
    return out

def bb20(closes: list[float]) -> tuple[float, float, float]:
    w = closes[-20:]
    mid = sum(w) / 20.0
    var = sum((c - mid) ** 2 for c in w) / 20.0
    std = var ** 0.5
    return mid - 2 * std, mid, mid + 2 * std

def in_morning(ts: datetime) -> bool:
    t = ts.time()
    return dtime(7, 0) <= t < dtime(12, 0)

def in_afternoon(ts: datetime) -> bool:
    t = ts.time()
    return dtime(12, 0) <= t < dtime(16, 0)

def pos_vs_bb(b: dict, bbu: float, bbl: float) -> str:
    if b["high"] > bbu and b["low"] < bbl:
        return "straddle"
    if b["close"] > bbu or b["high"] > bbu:
        if b["high"] > bbu and b["close"] <= bbu:
            return "wick_above_close_inside"
        if b["close"] > bbu:
            return "above_upper"
    if b["close"] < bbl or b["low"] < bbl:
        if b["low"] < bbl and b["close"] >= bbl:
            return "wick_below_close_inside"
        if b["close"] < bbl:
            return "below_lower"
    return "inside"

def fmt_bar(b: dict) -> str:
    return f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}"

def bar_metrics(b: dict) -> dict:
    rng = b["high"] - b["low"]
    body = abs(b["close"] - b["open"])
    return {"range_p": rng, "body_p": body, "br": (body / rng) if rng > 0 else 0.0}

def classify(pierce_idx: int, direction: str, bars_with_bb: list, target_dir_sign: int) -> str:
    """direction='UPPER' or 'LOWER'; target_dir_sign = -1 for upper-pierce reversal (down), +1 for lower."""
    if pierce_idx < 3 or pierce_idx + 1 >= len(bars_with_bb):
        return "NONE"
    Nm3 = bars_with_bb[pierce_idx - 3]
    Nm2 = bars_with_bb[pierce_idx - 2]
    Nm1 = bars_with_bb[pierce_idx - 1]
    N = bars_with_bb[pierce_idx]
    Np1 = bars_with_bb[pierce_idx + 1] if pierce_idx + 1 < len(bars_with_bb) else None
    Np2 = bars_with_bb[pierce_idx + 2] if pierce_idx + 2 < len(bars_with_bb) else None

    # PATTERN_1 (pierce + reclaim + confirm)
    # Branch A: N-1 wicks/closes near extreme, N-1 closes back inside, N closes in reversal
    # Branch B: N pierces, N+1 closes back inside, N+2 closes in reversal direction
    # Reversal-direction close means signed bar move (close - open) has sign target_dir_sign
    def reversal_close(bar):
        return (bar["close"] - bar["open"]) * target_dir_sign > 0

    if direction == "UPPER":
        # Branch A
        if (Nm1["high"] >= Nm1["bbu"] - 2.0
            and Nm1["close"] <= Nm1["bbu"]
            and reversal_close(N)):
            return "PATTERN_1A"
        # Branch B
        if Np1 is not None and Np2 is not None:
            if Np1["close"] <= Np1["bbu"] and reversal_close(Np2):
                return "PATTERN_1B"
    else:
        if (Nm1["low"] <= Nm1["bbl"] + 2.0
            and Nm1["close"] >= Nm1["bbl"]
            and reversal_close(N)):
            return "PATTERN_1A"
        if Np1 is not None and Np2 is not None:
            if Np1["close"] >= Np1["bbl"] and reversal_close(Np2):
                return "PATTERN_1B"

    # PATTERN_2 (two engulfing + confirm)
    # N-2 and N-1 inside BB within 5p of extreme; N-2 directional in trend dir; N-1 engulfing opposite; N continues N-1
    def near_extreme(bar, kind):
        if kind == "UPPER":
            return bar["high"] < bar["bbu"] and (bar["bbu"] - bar["close"]) <= 5.0
        return bar["low"] > bar["bbl"] and (bar["close"] - bar["bbl"]) <= 5.0

    if direction == "UPPER":
        if (near_extreme(Nm2, "UPPER") and near_extreme(Nm1, "UPPER")
            and Nm2["close"] > Nm2["open"]   # green (trend dir)
            and Nm1["close"] < Nm1["open"]   # red (engulfing opposite)
            and abs(Nm1["close"] - Nm1["open"]) >= abs(Nm2["close"] - Nm2["open"])
            and N["close"] < N["open"]):
            return "PATTERN_2"
    else:
        if (near_extreme(Nm2, "LOWER") and near_extreme(Nm1, "LOWER")
            and Nm2["close"] < Nm2["open"]
            and Nm1["close"] > Nm1["open"]
            and abs(Nm1["close"] - Nm1["open"]) >= abs(Nm2["close"] - Nm2["open"])
            and N["close"] > N["open"]):
            return "PATTERN_2"

    # PATTERN_3 (arc + breakout)
    # N-3, N-2, N-1 form arc with non-expanding range AND closes compressing toward extreme
    # N is breakout: range >= 8p AND close in reversal direction
    rngs = [(Nm3["high"] - Nm3["low"]),
            (Nm2["high"] - Nm2["low"]),
            (Nm1["high"] - Nm1["low"])]
    non_expanding = rngs[1] <= rngs[0] and rngs[2] <= rngs[1]
    N_range = N["high"] - N["low"]
    if direction == "UPPER":
        compressing = (Nm3["close"] <= Nm2["close"] <= Nm1["close"])  # closes drifting up toward upper
        if non_expanding and compressing and N_range >= 8.0 and reversal_close(N):
            return "PATTERN_3"
    else:
        compressing = (Nm3["close"] >= Nm2["close"] >= Nm1["close"])  # closes drifting down toward lower
        if non_expanding and compressing and N_range >= 8.0 and reversal_close(N):
            return "PATTERN_3"

    return "NONE"

def main():
    target = "2026-04-29"
    prior = "2026-04-28"
    bars = load_day(prior) + load_day(target)
    print(f"# loaded {len(bars)} bars across {prior}+{target}")
    # Compute BB at each bar using its own close + 19 prior closes
    closes = [b["close"] for b in bars]
    enriched = []
    for i, b in enumerate(bars):
        if i < 19:
            bbl = bbm = bbu = math.nan
        else:
            bbl, bbm, bbu = bb20(closes[: i + 1])
        enriched.append({**b, "bbl": bbl, "bbm": bbm, "bbu": bbu})

    pierces = []
    for i, b in enumerate(enriched):
        if b["ts"].date().isoformat() != target:
            continue
        if math.isnan(b["bbu"]):
            continue
        morning = in_morning(b["ts"])
        afternoon = in_afternoon(b["ts"])
        if not (morning or afternoon):
            continue
        upper = b["high"] > b["bbu"]
        lower = b["low"] < b["bbl"]
        if upper:
            pierces.append((i, "UPPER", "morning" if morning else "afternoon"))
        if lower:
            pierces.append((i, "LOWER", "morning" if morning else "afternoon"))

    print(f"# detected {len(pierces)} pierce-bars in 07:00-16:00 UTC on {target}")
    print()

    for k, (idx, direction, win) in enumerate(pierces):
        N = enriched[idx]
        # context: N-3..N-1, N, N+1..N+6
        before = enriched[max(0, idx - 3):idx]
        after = enriched[idx + 1: min(len(enriched), idx + 7)]
        # MFE/MAE in reversal direction
        sign = -1 if direction == "UPPER" else +1  # reversal direction relative to N close
        anchor = N["close"]
        mfe = 0.0  # max favourable in reversal dir (positive pips)
        mae = 0.0  # max adverse — i.e. continuation in pierce direction
        for ab in after:
            move_high = (ab["high"] - anchor) * sign  # for UPPER pierce, sign=-1 → continuation up = adverse
            move_low = (ab["low"] - anchor) * sign
            # Favourable excursion: best move in reversal direction
            if direction == "UPPER":
                # reversal direction = down → favourable = anchor - low
                mfe = max(mfe, anchor - ab["low"])
                mae = max(mae, ab["high"] - anchor)
            else:
                mfe = max(mfe, ab["high"] - anchor)
                mae = max(mae, anchor - ab["low"])

        rev_strength = mfe / max(mae, 1.0)
        # Pierce magnitude
        if direction == "UPPER":
            pmag = N["high"] - N["bbu"]
            close_back_inside = N["close"] < N["bbu"]
        else:
            pmag = N["bbl"] - N["low"]
            close_back_inside = N["close"] > N["bbl"]
        target_dir_sign = -1 if direction == "UPPER" else +1
        pat = classify(idx, direction, enriched, target_dir_sign)

        print(f"=== PIERCE {k+1}/{len(pierces)} === {N['ts'].strftime('%Y-%m-%d %H:%M')}  {direction}_PIERCE  window={win}")
        print(f"    BB: lower={N['bbl']:.2f} mid={N['bbm']:.2f} upper={N['bbu']:.2f}")
        print(f"    pierce_magnitude={pmag:.2f}p  close_back_inside={close_back_inside}  pattern={pat}")
        print(f"    MFE(reversal)={mfe:.1f}p  MAE(continuation)={mae:.1f}p  strength={rev_strength:.2f}")
        # 3 before
        for j, bb in enumerate(before):
            m = bar_metrics(bb)
            print(f"    N-{3-j}: {bb['ts'].strftime('%H:%M')} {fmt_bar(bb)} rng={m['range_p']:.1f} body={m['body_p']:.1f} br={m['br']:.2f} pos={pos_vs_bb(bb, bb['bbu'], bb['bbl'])} BBu={bb['bbu']:.2f} BBl={bb['bbl']:.2f}")
        # pierce
        m = bar_metrics(N)
        print(f"    N  : {N['ts'].strftime('%H:%M')} {fmt_bar(N)} rng={m['range_p']:.1f} body={m['body_p']:.1f} br={m['br']:.2f} pos={pos_vs_bb(N, N['bbu'], N['bbl'])}")
        # 6 after
        cum = 0.0
        for j, bb in enumerate(after):
            m = bar_metrics(bb)
            # cumulative move in reversal direction = (anchor - close)*sign for UPPER; (close - anchor) for LOWER
            if direction == "UPPER":
                disp = anchor - bb["close"]
            else:
                disp = bb["close"] - anchor
            print(f"    N+{j+1}: {bb['ts'].strftime('%H:%M')} {fmt_bar(bb)} rng={m['range_p']:.1f} body={m['body_p']:.1f} br={m['br']:.2f} pos={pos_vs_bb(bb, bb['bbu'], bb['bbl'])} disp_from_N_close={disp:+.1f}p")
        print()

if __name__ == "__main__":
    main()
