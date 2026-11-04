"""Addendum B1 — real QM graded-candidate outcomes.

46 fully-graded ENTRY_ARMED GBPUSD candidates with stop_first/target_first
flags, mae/mfe pips, STRUCT-derived target and 20-bar horizon.

Enrich each row with:
  * Side (inferred: entry > stop → BUY, entry < stop → SELL)
  * Nearest daily pivot at entry time (prior-day ASK D1 bar from
    /opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json or rolled from candle data)
  * Distance to nearest pivot in pips + volatility-adjusted "in zone" flag
  * Session (UTC hour → London / NY / Asia bucket; Oct-Nov 2026 is UK GMT)
  * ATR at open (from adjacent M5 candles)
  * Distance-to-next-pivot in signal direction
  * Realised net pips after 1.5p round-trip spread using the
    recorded hypothetical_stop and hypothetical_target (STRUCT).

Writes csv/addendum_b1_qm_graded.csv.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib

GRADED  = pathlib.Path("/home/autobot/reports-wt/gbpusd-pivot-pivot-20261103/gbpusd_pivot_pivot_20261103/data/qm_candidates_graded_all.jsonl")
CANDLES = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
PIVOT_CACHE = pathlib.Path("/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json")
OUT     = pathlib.Path(__file__).parent.parent / "csv" / "addendum_b1_qm_graded.csv"

SPREAD_PIPS = 1.5
PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")

def pivots(H, L, C):
    P = (H + L + C) / 3.0
    return {
        "P":  P,
        "R1": 2 * P - L, "S1": 2 * P - H,
        "R2": P + (H - L), "S2": P - (H - L),
        "R3": H + 2 * (P - L), "S3": L - 2 * (H - P),
    }

def pts(x): return x / 10000.0

def load_day(d: dt.date) -> list[dict]:
    f = CANDLES / f"{d.isoformat()}.csv"
    if not f.exists(): return []
    out = []
    for row in csv.DictReader(f.open()):
        ts_raw = row["timestamp"].replace(" ", "T")
        try: ts = dt.datetime.fromisoformat(ts_raw)
        except: continue
        out.append({
            "ts": ts,
            "o": float(row["open"]) / 10000.0,
            "h": float(row["high"]) / 10000.0,
            "l": float(row["low"])  / 10000.0,
            "c": float(row["close"])/ 10000.0,
        })
    return out

def day_rollup(bars: list[dict]):
    if not bars: return None
    return max(b["h"] for b in bars), min(b["l"] for b in bars), bars[-1]["c"]

def pivot_bars_from_cache():
    """Load production ASK D1 bars (30 trailing days)."""
    if not PIVOT_CACHE.exists(): return {}
    d = json.loads(PIVOT_CACHE.read_text())
    out = {}
    for row in d.get("prices", []):
        date_s = row["snapshotTime"].split(" ")[0].replace("/", "-")
        H = pts(row["highPrice"]["ask"])
        L = pts(row["lowPrice"]["ask"])
        C = pts(row["closePrice"]["ask"])
        out[date_s] = (H, L, C)
    return out

def atr14_at(bars: list[dict], idx: int) -> float:
    if idx < 14: return 0.0
    trs = []
    for j in range(idx - 13, idx + 1):
        tr = max(bars[j]["h"] - bars[j]["l"],
                 abs(bars[j]["h"] - bars[j - 1]["c"]) if j > 0 else bars[j]["h"] - bars[j]["l"],
                 abs(bars[j]["l"] - bars[j - 1]["c"]) if j > 0 else bars[j]["h"] - bars[j]["l"])
        trs.append(tr)
    return (sum(trs) / len(trs)) * 10000.0  # pips

def session_label(hour_utc: int) -> str:
    # Oct-Nov 2026 UK = GMT (UTC = UK local)
    if 0 <= hour_utc < 7:   return "Asia"
    if 7 <= hour_utc < 9:   return "LondonOpen"
    if 9 <= hour_utc < 12:  return "LondonMorning"
    if 12 <= hour_utc < 16: return "LN_NY_Overlap"
    if 16 <= hour_utc < 22: return "LateNY"
    return "Off"

def london_local_hour(utc_hour: int) -> int:
    return utc_hour  # GMT in Nov

def main() -> None:
    rows_raw = []
    for l in GRADED.open():
        try: rows_raw.append(json.loads(l))
        except: pass
    # Dedup
    seen = set(); uniq = []
    for r in rows_raw:
        key = (r.get('symbol'), r.get('opened_at'), r.get('zone_center'), r.get('state'))
        if key in seen: continue
        seen.add(key); uniq.append(r)
    gb = [r for r in uniq if r.get('symbol') == 'GBPUSD'
          and isinstance(r.get('outcome'), dict)
          and 'drawdown_20bar_pips' in r.get('outcome', {})]
    print(f"GBPUSD fully-graded ENTRY_ARMED candidates: {len(gb)}")

    pivot_cache = pivot_bars_from_cache()
    print(f"Pivot cache ASK days: {len(pivot_cache)}")

    # Build daily candle roll-up cache for pivot inputs on dates older than cache
    candle_rollup_cache = {}

    def get_prior_bar(d: dt.date):
        """Return (H, L, C) ASK rollup of prior trading day. Fallback to candle rollup (MID)."""
        for back in range(1, 8):
            cand = d - dt.timedelta(days=back)
            key = cand.isoformat()
            if key in pivot_cache:
                return pivot_cache[key], "ASK"
            if key in candle_rollup_cache:
                return candle_rollup_cache[key], "MID"
            # Try load it
            bars = load_day(cand)
            if bars:
                rl = day_rollup(bars)
                candle_rollup_cache[key] = rl
                return rl, "MID"
        return None, None

    enriched = []
    for r in gb:
        opened = dt.datetime.fromisoformat(r["opened_at"])
        d = opened.date()
        prior, basis = get_prior_bar(d)
        if prior is None:
            continue
        H, L, C = prior
        piv = pivots(H, L, C)

        entry  = r["hypothetical_entry"]  / 10000.0
        stop   = r["hypothetical_stop"]   / 10000.0
        target = r["hypothetical_target"] / 10000.0
        side = "BUY" if entry > stop else "SELL"
        stop_pips   = abs(entry - stop) * 10000.0
        target_pips = abs(entry - target) * 10000.0
        rr = target_pips / stop_pips if stop_pips > 0 else 0.0

        # Nearest pivot to the entry price (not the zone_center — entry is what we trade)
        nearest_name, nearest_val = min(piv.items(), key=lambda kv: abs(kv[1] - entry))
        dist_pips_signed = (entry - nearest_val) * 10000.0
        dist_pips_abs    = abs(dist_pips_signed)

        # Distance to NEXT pivot in signal direction
        piv_sorted = sorted(piv.items(), key=lambda kv: kv[1])
        if side == "BUY":
            above = [pv for _, pv in piv_sorted if pv > entry]
            next_pv = above[0] if above else None
        else:
            below = [pv for _, pv in piv_sorted if pv < entry]
            next_pv = below[-1] if below else None
        dist_next_pips = abs(entry - next_pv) * 10000.0 if next_pv is not None else 0.0

        # ATR at open (load day candles + find bar)
        bars = load_day(d)
        atr_pips = 0.0
        if bars:
            # find bar index
            idx = None
            for i, b in enumerate(bars):
                if b["ts"].replace(tzinfo=dt.timezone.utc) == opened.replace(tzinfo=dt.timezone.utc):
                    idx = i; break
            if idx is None:
                for i, b in enumerate(bars):
                    if b["ts"] >= opened:
                        idx = i; break
            if idx is not None and idx >= 14:
                atr_pips = atr14_at(bars, idx)

        hour = opened.hour
        sess = session_label(hour)

        # Realised outcome from graded record
        o = r["outcome"]
        stop_first   = bool(o.get("stop_first"))
        target_first = bool(o.get("target_first"))
        mae_pips = o.get("mae_pips", 0.0)
        mfe_pips = o.get("mfe_pips", 0.0)

        # Resolved P&L after spread
        if target_first:
            net = target_pips - SPREAD_PIPS
        elif stop_first:
            net = -stop_pips - SPREAD_PIPS
        else:
            # Neither hit within 20-bar horizon — unresolved; approximate by close vs entry
            # The grader doesn't give an explicit "close price" so we use MFE/MAE signs.
            # Simplest fair handling: mark as UNRESOLVED.
            net = None

        enriched.append({
            "opened_at": r["opened_at"],
            "side": side,
            "entry": f"{entry:.5f}",
            "stop": f"{stop:.5f}",
            "target": f"{target:.5f}",
            "stop_pips": f"{stop_pips:.1f}",
            "target_pips": f"{target_pips:.1f}",
            "rr_struct": f"{rr:.2f}",
            "basis_of_pivots": basis,
            "nearest_pivot_name": nearest_name,
            "nearest_pivot_value": f"{nearest_val:.5f}",
            "nearest_pivot_dist_pips_abs": f"{dist_pips_abs:.1f}",
            "nearest_pivot_dist_pips_signed": f"{dist_pips_signed:+.1f}",
            "dist_to_next_pivot_pips": f"{dist_next_pips:.1f}",
            "atr14_m5_pips_at_open": f"{atr_pips:.1f}",
            "session": sess,
            "hour_utc": hour,
            "zone_center": r.get("zone_center"),
            "zone_class": r.get("zone_class"),
            "zone_weight": r.get("zone_weight"),
            "zone_width_pips": r.get("zone_width_pips"),
            "confidence_score": r.get("confidence_score"),
            "stop_first": int(stop_first),
            "target_first": int(target_first),
            "mae_pips": f"{mae_pips:+.1f}",
            "mfe_pips": f"{mfe_pips:+.1f}",
            "net_pips_after_spread": "UNRESOLVED" if net is None else f"{net:+.1f}",
            "state": r.get("state"),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = list(enriched[0].keys()) if enriched else []
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(enriched)
    print(f"Wrote {len(enriched)} enriched rows to {OUT}")

    # Headline summary
    from collections import Counter
    resolved = [r for r in enriched if r["net_pips_after_spread"] != "UNRESOLVED"]
    wins = [r for r in resolved if float(r["net_pips_after_spread"]) > 0]
    print(f"\nResolved trades: {len(resolved)}")
    print(f"Wins: {len(wins)} ({100*len(wins)/max(len(resolved),1):.1f}%)")
    print(f"Total net: {sum(float(r['net_pips_after_spread']) for r in resolved):+.1f} pips")
    print(f"Mean net:  {sum(float(r['net_pips_after_spread']) for r in resolved)/max(len(resolved),1):+.2f} pips/trade")
    print(f"\nSessions: {Counter(r['session'] for r in enriched).most_common()}")
    print(f"Sides:    {Counter(r['side'] for r in enriched).most_common()}")
    print(f"Pivots:   {Counter(r['nearest_pivot_name'] for r in enriched).most_common()}")

if __name__ == "__main__":
    main()
