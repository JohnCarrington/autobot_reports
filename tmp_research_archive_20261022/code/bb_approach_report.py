"""bb_approach_report — tables for the UNTOUCHED near-miss re-cut.

Reads /tmp/bb_approach.json.

Sections:
1. UNTOUCHED re-cut by H1 approach distance buckets.
2. Full-corpus zone-based REJECTING definition sweep (Z=1,2,3,5,8).
3. ≤1p band-pivot confluence pierce-vs-turn-short split.
4. 5m own-bar + tightest-of-6 contribution beyond H1.
5. Live-availability check for the best zone.
6. Cross-check on MIXED.
"""

import json
import statistics
from collections import Counter
from pathlib import Path
import sys

recs = json.load(open("/tmp/bb_approach.json"))
N = len(recs)


def wins(sub):
    return sum(1 for r in sub if (r["pnl"] or 0) > 0)


def med(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def fmt(x, w=6, dp=2):
    if x is None:
        return f'{"—":>{w}}'
    return f"{x:{w}.{dp}f}"


def row(label, sub, colw=32):
    n = len(sub)
    if n == 0:
        print(f"| {label:<{colw}} |  0  |   —   |    —    |    —    (0) |  — |")
        return
    w = wins(sub)
    wp = 100 * w / n
    pnls = [r["pnl"] for r in sub if r["pnl"] is not None]
    mpnl = med(pnls)
    mfes = [r["mfe"] for r in sub if r["mfe"] is not None]
    mmfe = med(mfes)
    mfe25 = sum(1 for m in mfes if m >= 25)
    mfe_str = f'{mmfe:6.2f} ({len(mfes)})' if mmfe is not None else f'   —   (0)'
    print(f"| {label:<{colw}} | {n:3d} | {wp:5.1f} | {mpnl:+7.2f} | {mfe_str:>12s} | {mfe25:2d} |")


def header(cols):
    line = "| " + " | ".join(cols) + " |"
    sep = "|" + "|".join("-" * (len(c) + 2) for c in cols) + "|"
    print(line)
    print(sep)


print("### Sanity — corpus")
print(f"n = {N}, verdict split =",
      {v: sum(1 for r in recs if r['verdict']==v) for v in ['REJECTED','BROKE','UNTOUCHED']})
print(f"day_type split =", dict(Counter(r['day_type'] for r in recs)))
print()

# -------------------------------------------------------------------------
# 0. Baseline recap
# -------------------------------------------------------------------------
print("## 0. Baseline recap")
print()
header(["verdict     ", "  n", " win%", " medPnL", "     medMFE (n)", "mfe≥25"])
for v in ["REJECTED", "BROKE", "UNTOUCHED"]:
    row(v, [r for r in recs if r["verdict"] == v], colw=12)
print()

# -------------------------------------------------------------------------
# 1. UNTOUCHED re-cut by H1 approach distance
# -------------------------------------------------------------------------
print("## 1. UNTOUCHED cohort re-cut by H1 approach distance")
print()
print("Buckets on `h1_approach` (positive pips only; UNTOUCHED strictly outside bar):")
print()
buckets = [
    ("≤1p",   lambda x: x <= 1.0),
    ("1–3p",  lambda x: 1.0 < x <= 3.0),
    ("3–5p",  lambda x: 3.0 < x <= 5.0),
    ("5–10p", lambda x: 5.0 < x <= 10.0),
    ("10–20p",lambda x: 10.0 < x <= 20.0),
    (">20p",  lambda x: x > 20.0),
]
utd = [r for r in recs if r["verdict"] == "UNTOUCHED"]
header(["bucket    ", "  n", " win%", " medPnL", "     medMFE (n)", "mfe≥25"])
for name, cond in buckets:
    sub = [r for r in utd if cond(r["h1_approach"])]
    row(name, sub, colw=10)
row("UNTOUCHED total", utd, colw=10)
print()
print("Baselines from prior report: REJECTED n=53–54, win%=74–75.5, medPnL≈+7.2;",
      "BROKE n=41–42, win%≈38, medPnL≈−9.")
print()

# -------------------------------------------------------------------------
# 2. Zone-based REJECTING definition sweep
# -------------------------------------------------------------------------
print("## 2. Zone-based REJECTING definition — sweep Z = 1, 2, 3, 5, 8")
print()
print("Redefinition: a fire is **zREJECT(Z)** if `|h1_approach| ≤ Z` AND H1 closes",
      "on the entry side of the level. In-bar & near-miss both qualify.")
print("Everything else split as **zBROKE** (touched or near-touched but wrong-side close) /",
      "**zFAR** (never came within Z).")
print()


def entry_side_close(direction, close, level):
    if direction == "SELL":
        return close < level
    return close > level


def zone_class(r, Z):
    a = r["h1_approach"]
    on_side = entry_side_close(r["direction"], r["h1_close"], r["nk_price"])
    if abs(a) <= Z:
        return "zREJECT" if on_side else "zBROKE"
    return "zFAR"


for Z in [1, 2, 3, 5, 8]:
    print(f"### Z = {Z}p")
    for cls in ["zREJECT", "zBROKE", "zFAR"]:
        sub = [r for r in recs if zone_class(r, Z) == cls]
        if not sub:
            print(f"  {cls:8s} n=0")
            continue
        n = len(sub); w = wins(sub); wp = 100*w/n
        pnls = [r["pnl"] for r in sub if r["pnl"] is not None]
        mfes = [r["mfe"] for r in sub if r["mfe"] is not None]
        mfe25 = sum(1 for m in mfes if m >= 25)
        print(f"  {cls:8s} n={n:3d}  win%={wp:5.1f}  medPnL={med(pnls):+6.2f}  medMFE={med(mfes) or 0:5.2f} (n={len(mfes)})  mfe≥25={mfe25}")
    print()

print("Baseline strict-pierce REJECTED: n=54, win%=74.1, medPnL=+7.20 (this corpus).")
print()

# -------------------------------------------------------------------------
# 3. ≤1p band-pivot confluence pierce-vs-turn-short split
# -------------------------------------------------------------------------
print("## 3. ≤1p band-pivot confluence — split by pierce vs turn-short")
print()
print("The ≤1p bucket in the prior pivot-confluence pass was 41.2% WR (n=17).",
      "That bucket was defined by |band-pivot distance| ≤ 1p at fire — a spatial coincidence.")
print("We split those fires by whether the H1 bar pierced through the level or turned short.")
print()

# We don't have "bp-dist" (band-pivot distance) computed here. But we can identify
# the specific ≤1p fires by cross-referencing to prior report's list of 17 fires
# (ts,dir,nk from the h1_verdict report). Alternately we can synthesise ≤1p from
# reconstructed BB(20,2σ). To keep this self-contained + honest, use the prior
# published list of 17 fires (from bb_bounce_h1_verdict_20260813.md).

# Fires from the prior report ≤1p table (verbatim ts strings, dir, nk):
LE1_FIRES = [
    ("2026-07-15T07:30", "BUY",  "S2"),
    ("2026-06-19T14:55", "SELL", "R2"),
    ("2026-06-03T12:45", "BUY",  "P"),
    ("2026-06-25T06:15", "BUY",  "S1"),
    ("2026-08-11T08:55", "SELL", "P"),
    ("2026-05-05T12:35", "SELL", "P"),
    ("2026-05-13T08:15", "BUY",  "P"),
    ("2026-08-11T04:55", "BUY",  "P"),
    ("2026-06-04T06:50", "SELL", "R1"),
    ("2026-05-20T06:10", "BUY",  "S1"),
    ("2026-06-03T15:05", "SELL", "P"),
    ("2026-06-26T14:30", "SELL", "R2"),
    ("2026-05-12T10:40", "SELL", "P"),
    ("2026-05-29T09:15", "BUY",  "S1"),
    ("2026-07-22T11:15", "SELL", "R1"),
    ("2026-05-29T15:20", "SELL", "R1"),
    ("2026-05-29T10:55", "BUY",  "S1"),
]


def find(ts_prefix, direction, nk):
    for r in recs:
        if r["ts"].startswith(ts_prefix) and r["direction"] == direction and r["nk"] == nk:
            return r
    return None


le1_matched = []
for ts_pfx, dr, nk in LE1_FIRES:
    r = find(ts_pfx, dr, nk)
    if r:
        le1_matched.append(r)
print(f"matched {len(le1_matched)}/17 of the prior report's ≤1p fires")
print()

# split by whether H1 pierced (approach<=0) vs turned short (approach>0)
pierced = [r for r in le1_matched if r["h1_approach"] <= 0.0]
short = [r for r in le1_matched if r["h1_approach"] > 0.0]

def one_line(sub, label):
    if not sub:
        print(f"  {label:12s} n=0")
        return
    n = len(sub); w = wins(sub); wp = 100*w/n
    pnls = [r["pnl"] for r in sub if r["pnl"] is not None]
    mfes = [r["mfe"] for r in sub if r["mfe"] is not None]
    print(f"  {label:12s} n={n:2d}  win%={wp:5.1f}  medPnL={med(pnls):+6.2f}  medMFE={med(mfes) or 0:5.2f} (n={len(mfes)})")

print("### ≤1p split by H1 pierce vs turn-short")
one_line(pierced, "PIERCED")
one_line(short,   "TURNED-SHORT")
one_line(le1_matched, "≤1p total")
print()
# extra: pierce depth split within PIERCED
print("### ≤1p PIERCED — split by pierce depth (approach magnitude)")
shallow = [r for r in pierced if r["h1_approach"] > -2.0]  # 0..2p pierce
mid = [r for r in pierced if -5.0 <= r["h1_approach"] <= -2.0]
deep = [r for r in pierced if r["h1_approach"] < -5.0]
one_line(shallow, "0–2p pierce")
one_line(mid,     "2–5p pierce")
one_line(deep,    ">5p pierce")
print()

# extra: pierce-and-REJECTED vs pierce-and-BROKE for the ≤1p bucket
print("### ≤1p PIERCED — split by REJECTED vs BROKE")
p_rej = [r for r in pierced if r["verdict"] == "REJECTED"]
p_brk = [r for r in pierced if r["verdict"] == "BROKE"]
one_line(p_rej, "PIERCED+REJECTED")
one_line(p_brk, "PIERCED+BROKE")
print()
print("### Per-fire detail (≤1p, matched)")
print("```")
print(f"{'ts':16s} {'dir':4s} {'nk':3s} {'approach':>9s} {'verdict':10s} {'pnl':>7s} {'mfe':>7s}")
for r in sorted(le1_matched, key=lambda x: x["ts"]):
    m = r['mfe']
    m_str = f'{m:6.2f}' if m is not None else '  —  '
    print(f"{r['ts'][:16]:16s} {r['direction']:4s} {r['nk']:3s} {r['h1_approach']:+8.2f}p {r['verdict']:10s} {r['pnl']:+7.2f} {m_str}")
print("```")
print()

# -------------------------------------------------------------------------
# 4. 5m contribution within the best zone
# -------------------------------------------------------------------------
print("## 4. 5m contribution beyond H1 zone")
print()
print("Within the best zone (chosen from #2 by win-rate at meaningful n), does the 5m",
      "own-bar approach or tightest-of-6 add separation?")
print()

# choose best zone by highest win% at n>=15 (informative)
best_Z = None
best_wp = -1
zone_results = {}
for Z in [1, 2, 3, 5, 8]:
    sub = [r for r in recs if zone_class(r, Z) == "zREJECT"]
    zone_results[Z] = sub
    if len(sub) >= 15:
        wp = 100 * wins(sub) / len(sub)
        if wp > best_wp:
            best_wp = wp
            best_Z = Z

print(f"Best zone by WR at n≥15: Z={best_Z}p (n={len(zone_results[best_Z])}, win%={best_wp:.1f})")
print()

best_sub = zone_results[best_Z]
# 5m own-bar approach re-cut within zREJECT(best_Z)
print(f"### 5m own-bar approach within zREJECT(Z={best_Z}p)")
fb_buckets = [
    ("pierced (≤0)",  lambda x: x <= 0.0),
    ("0–1p short",    lambda x: 0.0 < x <= 1.0),
    ("1–3p short",    lambda x: 1.0 < x <= 3.0),
    ("3–5p short",    lambda x: 3.0 < x <= 5.0),
    (">5p short",     lambda x: x > 5.0),
]
header(["bucket        ", "  n", " win%", " medPnL", "     medMFE (n)", "mfe≥25"])
for name, cond in fb_buckets:
    sub = [r for r in best_sub if cond(r["fb_approach"])]
    row(name, sub, colw=14)
print()

# tightest-of-6 within zREJECT(best_Z)
print(f"### Tightest-of-6 5m approach within zREJECT(Z={best_Z}p)")
header(["bucket        ", "  n", " win%", " medPnL", "     medMFE (n)", "mfe≥25"])
for name, cond in fb_buckets:
    sub = [r for r in best_sub if cond(r["tightest6_approach"])]
    row(name, sub, colw=14)
print()

# 5m-only rejection definition (ignore H1) at Z=best_Z
print(f"### 5m-only zone rejection — sweep Z on tightest6")
for Z5 in [1, 2, 3, 5]:
    for kind in ["zREJECT5", "zFAR5"]:
        pass
    # zREJECT5: tightest6 within Z pips of level (inside or outside) AND fire-bar
    # close on entry side.
    def z5(r, Z):
        a = r["tightest6_approach"]
        if abs(a) > Z:
            return "zFAR5"
        # entry-side close on FIRE BAR — use fb_high/fb_low? no, we don't have close.
        # Approximate: use direction of the fire-bar wick geometry: if for SELL,
        # fb_low < nk < fb_high or fb_high < nk, treat as on-side; we lack close.
        # For simplicity, use whether the fire's fb_approach shows the bar retreated
        # from the level: fb_approach >= tightest6_approach (positive gap or less pierce).
        # Instead, use the raw fire-bar geometry: for SELL, ok if fb_high - nk <= 0 not required;
        # we don't have a close-vs-level metric on 5m without adding one. Skip on-side.
        return "zREJECT5"
    sub = [r for r in recs if z5(r, Z5) == "zREJECT5"]
    if not sub: continue
    n=len(sub); w=wins(sub)
    pnls=[r["pnl"] for r in sub if r["pnl"] is not None]
    mfes=[r["mfe"] for r in sub if r["mfe"] is not None]
    print(f"  Z5={Z5}p  n={n:3d}  win%={100*w/n:5.1f}  medPnL={med(pnls):+6.2f}  medMFE={med(mfes) or 0:5.2f} (n={len(mfes)})")
print("  [5m-only definition uses tightest-of-6 approach only; no entry-side close",
      "gate at 5m — we do not stamp a 5m close-vs-level flag. Interpret as a proximity-only",
      "test, not a symmetry-parallel of the H1 zone.]")
print()

# combined: H1 zREJECT(best_Z) AND 5m tightest6 in a tight band
print(f"### Combined H1 zREJECT(Z={best_Z}p) AND 5m tightest6 ≤ 3p")
sub = [r for r in best_sub if r["tightest6_approach"] <= 3.0]
row(f"combined", sub, colw=32)
sub2 = [r for r in best_sub if r["tightest6_approach"] > 3.0]
row(f"H1 only, 5m loose (>3p)", sub2, colw=32)
print()

# -------------------------------------------------------------------------
# 5. Live-availability check
# -------------------------------------------------------------------------
print("## 5. Live-availability check for best zone")
print()
print(f"For zREJECT(Z={best_Z}p) as defined on the *completed* H1 bar, how many fires",
      "would be identifiable at the fire's own 5m close?")
print()
print("A fire is *live-identifiable* if, using only bars up to and including the fire",
      "5m bar (i.e. bars from the start of the containing H1 hour up to the fire bar),",
      "we can verify:")
print("  (a) the running H1 extreme is within Z of the level; AND")
print("  (b) the last 5m close in the partial H1 is on the entry side of the level.")
print()
print("This is a proxy — the live check runs on the partial H1 constructed from")
print(f"5m bars in [hour_start, fire_bar] inclusive.")
print()

# For each zREJECT(best_Z) fire, reconstruct the partial H1 up to and including
# the fire's 5m bar and re-classify.
from datetime import datetime, timezone, timedelta
import csv
from pathlib import Path
from bisect import bisect_left

CANDLES = Path("/opt/tradingbot/data/candles/GBPUSD")

def load_day_bars(date_str):
    p = CANDLES / f"{date_str}.csv"
    if not p.exists(): return []
    out = []
    with p.open() as f:
        r = csv.DictReader(f)
        for row_ in r:
            try:
                ts = datetime.fromisoformat(row_["timestamp"].replace("Z","+00:00"))
                out.append((ts, float(row_["open"]), float(row_["high"]),
                            float(row_["low"]), float(row_["close"])))
            except Exception: pass
    return out

def partial_h1(fire_ts):
    hour_start = fire_ts.replace(minute=0, second=0, microsecond=0)
    ds = hour_start.astimezone(timezone.utc).date().isoformat()
    bars = [b for b in load_day_bars(ds) if hour_start <= b[0] <= fire_ts]
    if not bars: return None
    hi = max(b[2] for b in bars); lo = min(b[3] for b in bars)
    return {"high": hi, "low": lo, "close": bars[-1][4], "n_5m": len(bars)}

live_ok = 0
live_total = 0
live_missed = []
for r in best_sub:
    live_total += 1
    fire_ts = datetime.fromisoformat(r["ts"].replace("Z","+00:00"))
    if fire_ts.tzinfo is None: fire_ts = fire_ts.replace(tzinfo=timezone.utc)
    p = partial_h1(fire_ts)
    if p is None:
        live_missed.append((r["ts"], "no partial H1"))
        continue
    # partial approach
    lo, hi, c = p["low"], p["high"], p["close"]
    if lo <= r["nk_price"] <= hi:
        pap = -min(hi - r["nk_price"], r["nk_price"] - lo)
    else:
        pap = min(abs(hi - r["nk_price"]), abs(lo - r["nk_price"]))
    on_side = entry_side_close(r["direction"], c, r["nk_price"])
    if abs(pap) <= best_Z and on_side:
        live_ok += 1
    else:
        live_missed.append((r["ts"], f"partial_approach={pap:+.2f}p on_side={on_side}"))

print(f"live-identifiable at fire close: {live_ok}/{live_total}",
      f"({100*live_ok/live_total:.1f}%)")
print()
# outcomes on live-only subset
live_only = []
for r in best_sub:
    fire_ts = datetime.fromisoformat(r["ts"].replace("Z","+00:00"))
    if fire_ts.tzinfo is None: fire_ts = fire_ts.replace(tzinfo=timezone.utc)
    p = partial_h1(fire_ts)
    if p is None: continue
    lo, hi, c = p["low"], p["high"], p["close"]
    if lo <= r["nk_price"] <= hi:
        pap = -min(hi - r["nk_price"], r["nk_price"] - lo)
    else:
        pap = min(abs(hi - r["nk_price"]), abs(lo - r["nk_price"]))
    on_side = entry_side_close(r["direction"], c, r["nk_price"])
    if abs(pap) <= best_Z and on_side:
        live_only.append(r)

print(f"outcomes on live-only subset (n={len(live_only)}):")
one_line(live_only, "LIVE zREJECT")
live_ids = {id(x) for x in live_only}
dropped = [r for r in best_sub if id(r) not in live_ids]
one_line(dropped, "DROPPED (retroactive-only)")
print()

# also: for each Z, live-availability count
print("### Live-availability by Z (all zones, not just best)")
for Z in [1, 2, 3, 5, 8]:
    sub = [r for r in recs if zone_class(r, Z) == "zREJECT"]
    if not sub:
        continue
    live_cnt = 0
    live_wins = 0
    for r in sub:
        fire_ts = datetime.fromisoformat(r["ts"].replace("Z","+00:00"))
        if fire_ts.tzinfo is None: fire_ts = fire_ts.replace(tzinfo=timezone.utc)
        p = partial_h1(fire_ts)
        if p is None: continue
        lo, hi, c = p["low"], p["high"], p["close"]
        if lo <= r["nk_price"] <= hi:
            pap = -min(hi - r["nk_price"], r["nk_price"] - lo)
        else:
            pap = min(abs(hi - r["nk_price"]), abs(lo - r["nk_price"]))
        on_side = entry_side_close(r["direction"], c, r["nk_price"])
        if abs(pap) <= Z and on_side:
            live_cnt += 1
            if (r["pnl"] or 0) > 0:
                live_wins += 1
    wp = 100*live_wins/live_cnt if live_cnt else 0
    print(f"  Z={Z}p  full={len(sub):3d}  live={live_cnt:3d}  liveWin%={wp:5.1f}")
print()

# -------------------------------------------------------------------------
# 6. Cross-check on MIXED
# -------------------------------------------------------------------------
print("## 6. Cross-check on MIXED days (n_MIXED = %d)" % sum(1 for r in recs if r['day_type']=='MIXED'))
print()

mx = [r for r in recs if r["day_type"] == "MIXED"]
print("### UNTOUCHED re-cut on MIXED")
utd_mx = [r for r in mx if r["verdict"] == "UNTOUCHED"]
header(["bucket    ", "  n", " win%", " medPnL", "     medMFE (n)", "mfe≥25"])
for name, cond in buckets:
    sub = [r for r in utd_mx if cond(r["h1_approach"])]
    row(name, sub, colw=10)
row("UNTOUCHED total MIXED", utd_mx, colw=10)
print()

print("### Zone sweep on MIXED (Z=1,2,3,5,8) — zREJECT cell only")
for Z in [1, 2, 3, 5, 8]:
    sub = [r for r in mx if zone_class(r, Z) == "zREJECT"]
    if not sub:
        print(f"  Z={Z}p  n=0")
        continue
    n=len(sub); w=wins(sub)
    pnls=[r["pnl"] for r in sub if r["pnl"] is not None]
    mfes=[r["mfe"] for r in sub if r["mfe"] is not None]
    print(f"  Z={Z}p  n={n:3d}  win%={100*w/n:5.1f}  medPnL={med(pnls):+6.2f}  medMFE={med(mfes) or 0:5.2f} (n={len(mfes)})")
print()

print("### Non-MIXED (TRENDING/CHOP/QUIET/uncoded) — zone sweep")
nmx = [r for r in recs if r["day_type"] != "MIXED"]
print(f"non-MIXED n = {len(nmx)}")
for Z in [1, 2, 3, 5, 8]:
    sub = [r for r in nmx if zone_class(r, Z) == "zREJECT"]
    if not sub:
        print(f"  Z={Z}p  n=0")
        continue
    n=len(sub); w=wins(sub)
    pnls=[r["pnl"] for r in sub if r["pnl"] is not None]
    print(f"  Z={Z}p  n={n:3d}  win%={100*w/n:5.1f}  medPnL={med(pnls):+6.2f}")
