"""
Full-month BB pierce audit, GBPUSD 5m.
- Filters: first_in_streak=True, close_back=True
- Forward window: walk N+1 to EOD-of-pierce-date or until price returns to
  pierce_close, whichever first.
- New columns: MAX_REVERSAL_PIPS, TIME_TO_MAX_PIPS (minutes).
- Retain MFE_6BAR, MAE_6BAR.
"""
from __future__ import annotations
import csv, math, os
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from statistics import median, mean

PIP = 1.0
DATA_DIR = Path("/opt/tradingbot/data/candles/GBPUSD")

WARMUP = ["2026-03-31"]
TARGET_DATES = []
for fn in sorted(os.listdir(DATA_DIR)):
    if not fn.endswith(".csv") or ".tickbuilt" in fn:
        continue
    date = fn[:-4]
    if "2026-04-01" <= date <= "2026-05-01":
        TARGET_DATES.append(date)

def load_day(date):
    p = DATA_DIR / f"{date}.csv"
    if not p.exists(): return []
    rows = []
    with p.open() as f:
        for r in csv.DictReader(f):
            rows.append({
                "ts": datetime.fromisoformat(r["timestamp"]).astimezone(timezone.utc),
                "open": float(r["open"]),"high": float(r["high"]),
                "low": float(r["low"]),"close": float(r["close"]),
                "date": date,
            })
    rows.sort(key=lambda b: b["ts"])
    out = []; last = None
    for b in rows:
        if last and b["ts"] == last: out[-1] = b
        else: out.append(b); last = b["ts"]
    return out

bars = []
for d in WARMUP + TARGET_DATES:
    bars.extend(load_day(d))

def bb20(closes):
    w = closes[-20:]
    mid = sum(w)/20
    std = (sum((c-mid)**2 for c in w)/20) ** 0.5
    return mid-2*std, mid, mid+2*std

closes = [b["close"] for b in bars]
enriched = []
for i, b in enumerate(bars):
    if i < 19:
        bbl=bbm=bbu=math.nan
    else:
        bbl,bbm,bbu = bb20(closes[:i+1])
    enriched.append({**b, "bbl":bbl, "bbm":bbm, "bbu":bbu})

def in_window(t):
    if dtime(7,0) <= t.time() < dtime(12,0): return "morning"
    if dtime(12,0) <= t.time() < dtime(16,0): return "afternoon"
    return None

def classify(idx, direction, bars, sign):
    if idx < 3 or idx + 1 >= len(bars): return "NONE"
    Nm3, Nm2, Nm1, N = bars[idx-3], bars[idx-2], bars[idx-1], bars[idx]
    if any(math.isnan(x[k]) for x in (Nm3,Nm2,Nm1) for k in ("bbu","bbl")):
        return "NONE"
    Np1 = bars[idx+1] if idx+1 < len(bars) else None
    Np2 = bars[idx+2] if idx+2 < len(bars) else None
    rev = lambda b: (b["close"]-b["open"])*sign > 0

    if direction == "UPPER":
        if Nm1["high"] >= Nm1["bbu"]-2 and Nm1["close"] <= Nm1["bbu"] and rev(N): return "PATTERN_1A"
        if Np1 and Np2 and Np1["close"] <= Np1["bbu"] and rev(Np2): return "PATTERN_1B"
        if (Nm2["high"] < Nm2["bbu"] and (Nm2["bbu"]-Nm2["close"]) <= 5
            and Nm1["high"] < Nm1["bbu"] and (Nm1["bbu"]-Nm1["close"]) <= 5
            and Nm2["close"] > Nm2["open"] and Nm1["close"] < Nm1["open"]
            and abs(Nm1["close"]-Nm1["open"]) >= abs(Nm2["close"]-Nm2["open"])
            and N["close"] < N["open"]):
            return "PATTERN_2"
    else:
        if Nm1["low"] <= Nm1["bbl"]+2 and Nm1["close"] >= Nm1["bbl"] and rev(N): return "PATTERN_1A"
        if Np1 and Np2 and Np1["close"] >= Np1["bbl"] and rev(Np2): return "PATTERN_1B"
        if (Nm2["low"] > Nm2["bbl"] and (Nm2["close"]-Nm2["bbl"]) <= 5
            and Nm1["low"] > Nm1["bbl"] and (Nm1["close"]-Nm1["bbl"]) <= 5
            and Nm2["close"] < Nm2["open"] and Nm1["close"] > Nm1["open"]
            and abs(Nm1["close"]-Nm1["open"]) >= abs(Nm2["close"]-Nm2["open"])
            and N["close"] > N["open"]):
            return "PATTERN_2"

    rngs = [Nm3["high"]-Nm3["low"], Nm2["high"]-Nm2["low"], Nm1["high"]-Nm1["low"]]
    non_exp = rngs[1] <= rngs[0] and rngs[2] <= rngs[1]
    Nrng = N["high"] - N["low"]
    if direction == "UPPER":
        if non_exp and (Nm3["close"] <= Nm2["close"] <= Nm1["close"]) and Nrng >= 8 and rev(N):
            return "PATTERN_3"
    else:
        if non_exp and (Nm3["close"] >= Nm2["close"] >= Nm1["close"]) and Nrng >= 8 and rev(N):
            return "PATTERN_3"
    return "NONE"

def forward_measure(idx, direction, bars):
    """Track max favourable excursion bar-by-bar from N+1 to EOD-of-pierce-day.
    Stop early when a bar's CLOSE returns to (or beyond) pierce_close — i.e.
    a bar finishes back at break-even. MFE_6BAR / MAE_6BAR are computed over
    the literal first 6 bars, ignoring the early-stop, for short-term context.
    """
    pierce = bars[idx]
    pclose = pierce["close"]
    pdate = pierce["date"]
    # 6-bar window — independent of early-stop
    mfe_6 = 0.0; mae_6 = 0.0
    for k in range(1, 7):
        if idx + k >= len(bars): break
        b = bars[idx + k]
        if b["date"] != pdate: break
        if direction == "UPPER":
            mfe_6 = max(mfe_6, pclose - b["low"])
            mae_6 = max(mae_6, b["high"] - pclose)
        else:
            mfe_6 = max(mfe_6, b["high"] - pclose)
            mae_6 = max(mae_6, pclose - b["low"])
    # Full-day max with close-based BE stop
    max_rev = 0.0; t2max = 0
    j = idx + 1
    bar_count = 0
    while j < len(bars):
        b = bars[j]
        if b["date"] != pdate:
            break
        bar_count += 1
        if direction == "UPPER":
            cand = pclose - b["low"]
        else:
            cand = b["high"] - pclose
        if cand > max_rev:
            max_rev = cand
            t2max = bar_count * 5  # minutes from pierce close
        # Close-based "return to pierce_close": bar finished back at BE
        if direction == "UPPER":
            if b["close"] >= pclose:
                break
        else:
            if b["close"] <= pclose:
                break
        j += 1
    return max_rev, t2max, mfe_6, mae_6

pierces = []
for i, b in enumerate(enriched):
    if b["date"] not in TARGET_DATES: continue
    if math.isnan(b["bbu"]): continue
    win = in_window(b["ts"])
    if not win: continue
    upper = b["high"] > b["bbu"]
    lower = b["low"] < b["bbl"]
    for direction in (("UPPER",) if upper else ()) + (("LOWER",) if lower else ()):
        # close_back filter
        if direction == "UPPER" and b["close"] >= b["bbu"]: continue
        if direction == "LOWER" and b["close"] <= b["bbl"]: continue
        # first_in_streak filter — prior bar must NOT have been a same-direction pierce
        if i > 0:
            pb = enriched[i-1]
            if not math.isnan(pb["bbu"]):
                if direction == "UPPER" and pb["high"] > pb["bbu"]: continue
                if direction == "LOWER" and pb["low"] < pb["bbl"]: continue
        max_rev, t2max, mfe6, mae6 = forward_measure(i, direction, enriched)
        sign = -1 if direction == "UPPER" else +1
        pat = classify(i, direction, enriched, sign)
        pmag = (b["high"] - b["bbu"]) if direction == "UPPER" else (b["bbl"] - b["low"])
        rng = b["high"] - b["low"]
        body = abs(b["close"] - b["open"])
        br = body/rng if rng > 0 else 0
        pierces.append({
            "date": b["date"], "ts": b["ts"].strftime("%H:%M"),
            "window": win, "dir": direction,
            "o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"],
            "bbl": b["bbl"], "bbm": b["bbm"], "bbu": b["bbu"],
            "pierce_p": pmag, "rng": rng, "body": body, "br": br,
            "pattern": pat,
            "max_rev": max_rev, "t2max": t2max,
            "mfe6": mfe6, "mae6": mae6,
        })

# CSV output to file
csv_path = "/tmp/audit_full_month.csv"
with open(csv_path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date","ts","window","dir","o","h","l","c","bbl","bbm","bbu",
                "pierce_p","rng","body","br","pattern",
                "max_rev_p","t2max_min","mfe_6bar","mae_6bar"])
    for p in pierces:
        w.writerow([p["date"], p["ts"], p["window"], p["dir"],
                    f"{p['o']:.2f}", f"{p['h']:.2f}", f"{p['l']:.2f}", f"{p['c']:.2f}",
                    f"{p['bbl']:.2f}", f"{p['bbm']:.2f}", f"{p['bbu']:.2f}",
                    f"{p['pierce_p']:.2f}", f"{p['rng']:.1f}", f"{p['body']:.1f}", f"{p['br']:.2f}",
                    p["pattern"], f"{p['max_rev']:.1f}", p["t2max"],
                    f"{p['mfe6']:.1f}", f"{p['mae6']:.1f}"])

print(f"# total qualified pierces: {len(pierces)}  (written to {csv_path})")
print()

# Per-day count
from collections import Counter
by_day = Counter(p["date"] for p in pierces)
print("# pierces per day:")
for d in TARGET_DATES:
    print(f"#   {d}  {by_day[d]}")
print()

# Per-pattern summary
patterns = ["PATTERN_1A","PATTERN_1B","PATTERN_2","PATTERN_3","NONE"]
print("# === PER-PATTERN SUMMARY ===")
header = ["pattern","n","morn","aft","mr_med","mr_mean","≥20p","≥30p","≥50p","≥75p","≥100p","t2m_med","t2m_mean"]
print("  ".join(f"{h:>10}" for h in header))
for pat in patterns:
    rows = [p for p in pierces if p["pattern"] == pat]
    if not rows:
        print("  ".join(f"{v:>10}" for v in [pat,0,0,0,"-","-",0,0,0,0,0,"-","-"]))
        continue
    mrs = [r["max_rev"] for r in rows]
    t2ms = [r["t2max"] for r in rows if r["max_rev"] > 0]
    morn = sum(1 for r in rows if r["window"]=="morning")
    aft = sum(1 for r in rows if r["window"]=="afternoon")
    vals = [
        pat, len(rows), morn, aft,
        f"{median(mrs):.1f}", f"{mean(mrs):.1f}",
        sum(1 for r in mrs if r>=20),
        sum(1 for r in mrs if r>=30),
        sum(1 for r in mrs if r>=50),
        sum(1 for r in mrs if r>=75),
        sum(1 for r in mrs if r>=100),
        f"{median(t2ms):.0f}" if t2ms else "-",
        f"{mean(t2ms):.1f}" if t2ms else "-",
    ]
    print("  ".join(f"{v:>10}" for v in vals))

# Per-pattern × per-window breakdown of MAX_REVERSAL_PIPS
print()
print("# === MAX_REVERSAL_PIPS DECOMPOSED BY WINDOW ===")
print("  ".join(f"{h:>14}" for h in ["pattern","window","n","mr_med","mr_mean","≥20p","≥30p","≥50p","≥75p","≥100p"]))
for pat in patterns:
    for win in ("morning","afternoon"):
        rows = [p for p in pierces if p["pattern"]==pat and p["window"]==win]
        if not rows:
            print("  ".join(f"{v:>14}" for v in [pat, win, 0, "-", "-", 0,0,0,0,0]))
            continue
        mrs = [r["max_rev"] for r in rows]
        vals = [pat, win, len(rows),
                f"{median(mrs):.1f}", f"{mean(mrs):.1f}",
                sum(1 for r in mrs if r>=20),
                sum(1 for r in mrs if r>=30),
                sum(1 for r in mrs if r>=50),
                sum(1 for r in mrs if r>=75),
                sum(1 for r in mrs if r>=100)]
        print("  ".join(f"{v:>14}" for v in vals))
