"""Compact one-line-per-pierce summary for 2026-04-29."""
from __future__ import annotations
import csv, math
from datetime import datetime, time as dtime, timezone
from pathlib import Path

PIP = 1.0
DATA_DIR = Path("/opt/tradingbot/data/candles/GBPUSD")

def load_day(date):
    rows = []
    with (DATA_DIR / f"{date}.csv").open() as f:
        for r in csv.DictReader(f):
            rows.append({
                "ts": datetime.fromisoformat(r["timestamp"]).astimezone(timezone.utc),
                "open": float(r["open"]),"high": float(r["high"]),
                "low": float(r["low"]),"close": float(r["close"]),
            })
    rows.sort(key=lambda b: b["ts"])
    out = []; last = None
    for b in rows:
        if last and b["ts"] == last: out[-1] = b
        else: out.append(b); last = b["ts"]
    return out

def bb20(closes):
    w = closes[-20:]
    mid = sum(w)/20; std = (sum((c-mid)**2 for c in w)/20)**0.5
    return mid-2*std, mid, mid+2*std

def classify(idx, direction, bars, sign):
    if idx < 3 or idx + 1 >= len(bars): return "NONE"
    Nm3, Nm2, Nm1, N = bars[idx-3], bars[idx-2], bars[idx-1], bars[idx]
    Np1 = bars[idx+1] if idx+1 < len(bars) else None
    Np2 = bars[idx+2] if idx+2 < len(bars) else None
    rev = lambda b: (b["close"]-b["open"])*sign > 0
    if direction == "UPPER":
        if Nm1["high"] >= Nm1["bbu"]-2 and Nm1["close"] <= Nm1["bbu"] and rev(N): return "PATTERN_1A"
        if Np1 and Np2 and Np1["close"] <= Np1["bbu"] and rev(Np2): return "PATTERN_1B"
        if Nm2["high"] < Nm2["bbu"] and (Nm2["bbu"]-Nm2["close"]) <= 5 \
           and Nm1["high"] < Nm1["bbu"] and (Nm1["bbu"]-Nm1["close"]) <= 5 \
           and Nm2["close"] > Nm2["open"] and Nm1["close"] < Nm1["open"] \
           and abs(Nm1["close"]-Nm1["open"]) >= abs(Nm2["close"]-Nm2["open"]) \
           and N["close"] < N["open"]: return "PATTERN_2"
    else:
        if Nm1["low"] <= Nm1["bbl"]+2 and Nm1["close"] >= Nm1["bbl"] and rev(N): return "PATTERN_1A"
        if Np1 and Np2 and Np1["close"] >= Np1["bbl"] and rev(Np2): return "PATTERN_1B"
        if Nm2["low"] > Nm2["bbl"] and (Nm2["close"]-Nm2["bbl"]) <= 5 \
           and Nm1["low"] > Nm1["bbl"] and (Nm1["close"]-Nm1["bbl"]) <= 5 \
           and Nm2["close"] < Nm2["open"] and Nm1["close"] > Nm1["open"] \
           and abs(Nm1["close"]-Nm1["open"]) >= abs(Nm2["close"]-Nm2["open"]) \
           and N["close"] > N["open"]: return "PATTERN_2"
    rngs = [Nm3["high"]-Nm3["low"], Nm2["high"]-Nm2["low"], Nm1["high"]-Nm1["low"]]
    non_exp = rngs[1] <= rngs[0] and rngs[2] <= rngs[1]
    Nrng = N["high"] - N["low"]
    if direction == "UPPER":
        compr = Nm3["close"] <= Nm2["close"] <= Nm1["close"]
        if non_exp and compr and Nrng >= 8 and rev(N): return "PATTERN_3"
    else:
        compr = Nm3["close"] >= Nm2["close"] >= Nm1["close"]
        if non_exp and compr and Nrng >= 8 and rev(N): return "PATTERN_3"
    return "NONE"

def in_window(t):
    if dtime(7,0) <= t.time() < dtime(12,0): return "morning"
    if dtime(12,0) <= t.time() < dtime(16,0): return "afternoon"
    return None

def main():
    target, prior = "2026-04-29", "2026-04-28"
    bars = load_day(prior) + load_day(target)
    closes = [b["close"] for b in bars]
    enriched = []
    for i, b in enumerate(bars):
        if i < 19: bbl=bbm=bbu=math.nan
        else: bbl,bbm,bbu = bb20(closes[:i+1])
        enriched.append({**b,"bbl":bbl,"bbm":bbm,"bbu":bbu})

    # detect pierces (every bar where high>bbu or low<bbl)
    print("idx,ts,window,dir,o,h,l,c,bbl,bbm,bbu,pierce_p,close_back,rng,body,br,first_in_streak,mfe,mae,strength,pattern")
    last_dir, streak = None, False
    for i, b in enumerate(enriched):
        if b["ts"].date().isoformat() != target: continue
        if math.isnan(b["bbu"]): continue
        win = in_window(b["ts"])
        if not win: continue
        upper = b["high"] > b["bbu"]
        lower = b["low"] < b["bbl"]
        for direction in (("UPPER",) if upper else ()) + (("LOWER",) if lower else ()):
            sign = -1 if direction == "UPPER" else +1
            after = enriched[i+1:i+7]
            anchor = b["close"]
            mfe = mae = 0.0
            for ab in after:
                if direction == "UPPER":
                    mfe = max(mfe, anchor - ab["low"])
                    mae = max(mae, ab["high"] - anchor)
                else:
                    mfe = max(mfe, ab["high"] - anchor)
                    mae = max(mae, anchor - ab["low"])
            strength = mfe / max(mae, 1.0)
            pmag = (b["high"] - b["bbu"]) if direction == "UPPER" else (b["bbl"] - b["low"])
            close_back = (b["close"] < b["bbu"]) if direction == "UPPER" else (b["close"] > b["bbl"])
            pat = classify(i, direction, enriched, sign)
            rng = b["high"] - b["low"]
            body = abs(b["close"] - b["open"])
            br = body/rng if rng > 0 else 0
            # first-in-streak detection: prior bar same direction pierce?
            prev_pierce = False
            if i > 0:
                pb = enriched[i-1]
                if not math.isnan(pb["bbu"]):
                    if direction == "UPPER" and pb["high"] > pb["bbu"]: prev_pierce = True
                    if direction == "LOWER" and pb["low"] < pb["bbl"]: prev_pierce = True
            first = "Y" if not prev_pierce else ""
            print(f"{i},{b['ts'].strftime('%H:%M')},{win},{direction},"
                  f"{b['open']:.2f},{b['high']:.2f},{b['low']:.2f},{b['close']:.2f},"
                  f"{b['bbl']:.2f},{b['bbm']:.2f},{b['bbu']:.2f},"
                  f"{pmag:.2f},{close_back},{rng:.1f},{body:.1f},{br:.2f},"
                  f"{first},{mfe:.1f},{mae:.1f},{strength:.2f},{pat}")

main()
