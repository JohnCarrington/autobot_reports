"""13:00 / 15:00 bucket clustering analysis.

Analysis-only. Consumes:
  /tmp/bb_level_events.json   (from bb_level_coincidence.py)
  /opt/tradingbot/data/candles/GBPUSD/YYYY-MM-DD.csv   (raw 5m)
  /opt/tradingbot/cache/news_state_finnhub_*.json      (calendar)

No pivot/BB math re-implemented.
"""
from __future__ import annotations
import csv
import glob
import json
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta, time
from statistics import median

sys.path.insert(0, "/opt/tradingbot")

EVENTS_JSON = "/tmp/bb_level_events.json"
CANDLE_DIR = "/opt/tradingbot/data/candles/GBPUSD"
NEWS_GLOB = "/opt/tradingbot/cache/news_state_finnhub_*.json"

# Windows the operator flagged
W13_START = time(12, 45)
W13_END = time(13, 15)   # half-open [start, end)
W15_START = time(14, 45)
W15_END = time(15, 15)

SESSION_START = time(7, 0)
SESSION_END = time(20, 55)  # inclusive to last 5m bar 20:55

LONDON_START = time(8, 0)
LONDON_END = time(11, 0)   # net over 08:00..10:55


def load_events():
    d = json.load(open(EVENTS_JSON))
    for e in d["events"]:
        e["ts_dt"] = datetime.fromisoformat(e["ts"])
    return d["events"], d.get("bar_counts", {}), d.get("day_ranges", {})


def load_all_news():
    all_ev = {}
    for f in glob.glob(NEWS_GLOB):
        try:
            d = json.load(open(f))
            for ev in d.get("events", []):
                k = (ev.get("ts"), ev.get("event"), ev.get("currency"))
                all_ev[k] = ev
        except Exception:
            continue
    out = []
    for ev in all_ev.values():
        try:
            ts = datetime.fromisoformat(ev["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            out.append({
                "ts": ts,
                "date": ts.date().isoformat(),
                "impact": str(ev.get("impact", "")).upper(),
                "currency": str(ev.get("currency", "")).upper(),
                "event": str(ev.get("event", "")),
            })
        except Exception:
            continue
    out.sort(key=lambda r: r["ts"])
    return out


def bars_for(date_iso):
    path = f"{CANDLE_DIR}/{date_iso}.csv"
    if not os.path.exists(path):
        return []
    by_ts = {}
    with open(path, newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            try:
                ts = datetime.fromisoformat(row["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                by_ts[ts] = (ts, float(row["open"]), float(row["high"]),
                             float(row["low"]), float(row["close"]))
            except Exception:
                continue
    return sorted(by_ts.values(), key=lambda b: b[0])


def bars_before(date_iso, n_days=45):
    """Load prior candle files going back up to n_days calendar days.
    Concatenate in chronological order. Needed for H1 EMA200 warmup."""
    out = []
    d0 = datetime.fromisoformat(date_iso).date()
    loaded_days = []
    for back in range(1, n_days + 1):
        p = (d0 - timedelta(days=back)).isoformat()
        if os.path.exists(f"{CANDLE_DIR}/{p}.csv"):
            loaded_days.append(p)
    loaded_days.sort()  # chronological
    for p in loaded_days:
        out.extend(bars_for(p))
    return out


def london_stats(bars):
    """Return dict: open, close, high, low, net, range, efficiency."""
    sel = [b for b in bars if LONDON_START <= b[0].timetz().replace(tzinfo=None) < LONDON_END]
    if not sel:
        return None
    op = sel[0][1]
    cl = sel[-1][4]
    hi = max(b[2] for b in sel)
    lo = min(b[3] for b in sel)
    net = round(cl - op, 2)
    rng = round(hi - lo, 2)
    eff = round(abs(net) / rng, 3) if rng else 0.0
    return dict(open=op, close=cl, high=hi, low=lo, net=net, range=rng, efficiency=eff)


def bucket_key(ts):
    m = (ts.minute // 15) * 15
    return f"{ts.hour:02d}:{m:02d}"


def all_buckets():
    keys = []
    for h in range(7, 21):
        for m in (0, 15, 30, 45):
            if h == 20 and m > 45:
                continue
            keys.append(f"{h:02d}:{m:02d}")
    return keys


def in_session(ts):
    t = ts.timetz().replace(tzinfo=None)
    return SESSION_START <= t <= SESSION_END


def in_window(ts, start, end):
    t = ts.timetz().replace(tzinfo=None)
    return start <= t < end


def bb_series(closes):
    """Rolling BB(20,2) — width in pips per bar (index >= 19)."""
    import math
    n = len(closes)
    widths = [None] * n
    for i in range(19, n):
        window = closes[i - 19:i + 1]
        mid = sum(window) / 20
        var = sum((x - mid) ** 2 for x in window) / 20
        sd = math.sqrt(var)
        widths[i] = 4.0 * sd  # (up - lo) = 2*2*sd = 4*sd
    return widths


def find_bb_width_at(bars, ts, warmup_closes):
    """Return BB width in pips at bar with timestamp==ts, and day-median BB
    width for session bars 07:00..20:55."""
    closes_all = [b[4] for b in bars]
    combined = list(warmup_closes) + closes_all
    off = len(warmup_closes)
    widths = bb_series(combined)
    idx = None
    for i, b in enumerate(bars):
        if b[0] == ts:
            idx = i
            break
    if idx is None:
        return None, None
    at = widths[off + idx]
    sess_widths = [widths[off + i] for i, b in enumerate(bars)
                   if widths[off + i] is not None and in_session(b[0])]
    med = median(sess_widths) if sess_widths else None
    return at, med


def regime_proxy_h1(bars_prev_and_today, ts):
    """Very coarse regime proxy from H1 rollup up to `ts`:
      - Compute H1 closes from 5m
      - EMA20, EMA50, EMA200 on H1 close
      - ADX proxy via 14-bar Wilder using H1 highs/lows/closes
      - Label:
          STRONG_TREND_UP:   close > ema20 > ema50 > ema200 AND ADX >= 25
          STRONG_TREND_DOWN: close < ema20 < ema50 < ema200 AND ADX >= 25
          TREND_FORMING_UP:  close > ema20 > ema50 (adx < 25 or ema200 not aligned)
          TREND_FORMING_DOWN: close < ema20 < ema50 (adx < 25 or ema200 not aligned)
          RANGE:             |close-ema50| < 0.25 * atr14  AND ADX < 20
          CHOP:              otherwise
    Note: PROXY — not the production regime engine label. Reported as such.
    """
    h1 = {}
    for b in bars_prev_and_today:
        if b[0] > ts:
            break
        key = b[0].replace(minute=0, second=0, microsecond=0)
        rec = h1.get(key)
        if rec is None:
            h1[key] = [b[1], b[2], b[3], b[4]]  # o,h,l,c
        else:
            rec[1] = max(rec[1], b[2])
            rec[2] = min(rec[2], b[3])
            rec[3] = b[4]
    if len(h1) < 20:
        return "insufficient_h1"
    keys = sorted(h1.keys())
    ohlc = [h1[k] for k in keys]
    closes = [r[3] for r in ohlc]
    highs = [r[1] for r in ohlc]
    lows = [r[2] for r in ohlc]

    def ema(vals, n):
        if len(vals) < n:
            return None
        k = 2 / (n + 1)
        e = sum(vals[:n]) / n
        for v in vals[n:]:
            e = v * k + e * (1 - k)
        return e

    e20 = ema(closes, 20)
    e50 = ema(closes, 50) if len(closes) >= 50 else None
    e200 = ema(closes, 200) if len(closes) >= 200 else None
    if e20 is None or e50 is None:
        return "insufficient_h1"

    # ADX 14 (Wilder)
    def adx14(highs, lows, closes, n=14):
        if len(closes) < n + 1:
            return None
        tr = []
        pdm = []
        ndm = []
        for i in range(1, len(closes)):
            hh = highs[i]
            ll = lows[i]
            prev_c = closes[i - 1]
            tr.append(max(hh - ll, abs(hh - prev_c), abs(ll - prev_c)))
            up = highs[i] - highs[i - 1]
            dn = lows[i - 1] - lows[i]
            pdm.append(up if (up > dn and up > 0) else 0.0)
            ndm.append(dn if (dn > up and dn > 0) else 0.0)
        atr = sum(tr[:n]) / n
        pdi_s = sum(pdm[:n]) / n
        ndi_s = sum(ndm[:n]) / n
        dxs = []
        for i in range(n, len(tr)):
            atr = (atr * (n - 1) + tr[i]) / n
            pdi_s = (pdi_s * (n - 1) + pdm[i]) / n
            ndi_s = (ndi_s * (n - 1) + ndm[i]) / n
            if atr <= 0:
                continue
            pdi = 100 * pdi_s / atr
            ndi = 100 * ndi_s / atr
            dx = 100 * abs(pdi - ndi) / max(1e-9, (pdi + ndi))
            dxs.append(dx)
        if len(dxs) < n:
            return None
        adx = sum(dxs[:n]) / n
        for v in dxs[n:]:
            adx = (adx * (n - 1) + v) / n
        return adx, atr

    r = adx14(highs, lows, closes)
    if r is None:
        return "insufficient_h1"
    adx, atr = r
    c = closes[-1]
    aligned_up = (c > e20 > e50) and (e200 is None or e50 > e200)
    aligned_dn = (c < e20 < e50) and (e200 is None or e50 < e200)
    strong = adx >= 25.0
    if aligned_up and strong and e200 is not None:
        return "STRONG_TREND_UP"
    if aligned_dn and strong and e200 is not None:
        return "STRONG_TREND_DOWN"
    if aligned_up:
        return "TREND_FORMING_UP"
    if aligned_dn:
        return "TREND_FORMING_DOWN"
    if adx < 20.0 and atr > 0 and abs(c - e50) < 0.25 * atr:
        return "RANGE"
    return "CHOP"


# ---------------- MAIN ----------------

def main():
    events, bar_counts, day_ranges = load_events()
    news = load_all_news()

    # ---------- Task 1: 15-min bucket histogram ----------
    buckets = all_buckets()
    hist_all = {cohort: {k: 0 for k in buckets} for cohort in ("OUTER", "P")}
    hist_turn = {cohort: {k: 0 for k in buckets} for cohort in ("OUTER", "P")}
    for e in events:
        if e["kind"] != "COINC":   # only COINC (near band); LEVEL/BAND separate
            continue
        ts = e["ts_dt"]
        if not in_session(ts):
            continue
        cohort = e["cohort"]
        bk = bucket_key(ts)
        hist_all[cohort][bk] += 1
        if e["turn15"]:
            hist_turn[cohort][bk] += 1

    print("=" * 78)
    print("TASK 1 — 15-MIN BUCKET HISTOGRAM (event kind = COINC, session 07:00–20:55)")
    print("Corpus: 2026-03-23 to 2026-08-14")
    print("=" * 78)
    for cohort in ("OUTER", "P"):
        print(f"\n{cohort} cohort — counts (n) and turn15 rate (t15/n)")
        print(f"{'bucket':>7} | {'n':>4}  {'t15':>4}  rate")
        for k in buckets:
            n = hist_all[cohort][k]
            t = hist_turn[cohort][k]
            r = f"{t/n:.2f}" if n else "  —"
            mark = ""
            if k in ("12:45", "13:00", "13:15"):
                mark = "  <-- 13:00 window"
            if k in ("14:45", "15:00", "15:15"):
                mark = "  <-- 15:00 window"
            print(f"  {k}  | {n:4d}  {t:4d}  {r}{mark}")

    # Baseline (mean/median across all buckets 07:00..20:55)
    for cohort in ("OUTER", "P"):
        ns = [hist_all[cohort][k] for k in buckets]
        ts_ = [hist_turn[cohort][k] for k in buckets]
        print(f"\n{cohort} baseline: n median={median(ns):.1f}  mean={sum(ns)/len(ns):.2f}  "
              f"turn15 median={median(ts_):.1f}  mean={sum(ts_)/len(ts_):.2f}")

    # ---------- Bounce-day sets ----------
    bounce_days_13 = defaultdict(list)   # date -> [events]
    bounce_days_15 = defaultdict(list)
    for e in events:
        if e["kind"] != "COINC":
            continue
        if e["cohort"] != "OUTER":
            continue
        if not e["turn15"]:
            continue
        ts = e["ts_dt"]
        t = ts.timetz().replace(tzinfo=None)
        if W13_START <= t < W13_END:
            bounce_days_13[e["date"]].append(e)
        if W15_START <= t < W15_END:
            bounce_days_15[e["date"]].append(e)

    all_bounce_days = sorted(set(list(bounce_days_13) + list(bounce_days_15)))
    both_days = sorted(set(bounce_days_13) & set(bounce_days_15))
    print()
    print("=" * 78)
    print(f"BOUNCE-DAY SETS  (COINC OUTER, turn15=True)")
    print(f"  13:00-window days (n={len(bounce_days_13)}): {sorted(bounce_days_13)}")
    print(f"  15:00-window days (n={len(bounce_days_15)}): {sorted(bounce_days_15)}")
    print(f"  overlap (both):   (n={len(both_days)}): {both_days}")
    print("=" * 78)

    # ---------- Task 2: characterise bounce days ----------
    def char_day(date_iso, ev):
        bars = bars_for(date_iso)
        # get prior-day closes as warmup for BB
        d0 = datetime.fromisoformat(date_iso).date()
        prev = None
        for back in (1, 2, 3, 4, 5):
            p = (d0 - timedelta(days=back)).isoformat()
            if os.path.exists(f"{CANDLE_DIR}/{p}.csv"):
                prev = p
                break
        warmup = []
        prev_bars_full = []
        if prev:
            prev_bars_full = bars_for(prev)
            warmup = [b[4] for b in prev_bars_full][-20:]
        # deeper history for regime H1 EMA200
        prev_bars_deep = bars_before(date_iso, n_days=45)
        bb_at, bb_med = find_bb_width_at(bars, ev["ts_dt"], warmup) if bars else (None, None)
        lond = london_stats(bars) if bars else None
        # news on this day
        day_ev = [n for n in news if n["date"] == date_iso]
        highs_gbp_usd = [n for n in day_ev if n["impact"] == "HIGH" and n["currency"] in ("GBP", "USD")]
        # tier: BIG if >=1 HIGH GBP/USD, MIDDLE if 0 HIGH but any MED GBP/USD, none otherwise
        meds = [n for n in day_ev if n["impact"] == "MED" and n["currency"] in ("GBP", "USD")]
        if highs_gbp_usd:
            tier = "BIG"
        elif meds:
            tier = "MIDDLE"
        elif day_ev:
            tier = "SMALL"
        else:
            tier = "NONE_or_UNAVAIL"
        # note about cache coverage
        has_cache = os.path.exists(f"/opt/tradingbot/cache/news_state_finnhub_{date_iso}.json")
        # subtype (crude): if today has HIGH => BIG; else look ahead/behind 1 day
        d0d = datetime.fromisoformat(date_iso).date()
        def has_high(delta):
            dd = (d0d + timedelta(days=delta)).isoformat()
            highs = [n for n in news if n["date"] == dd and n["impact"] == "HIGH"
                     and n["currency"] in ("GBP", "USD")]
            return bool(highs)
        subtype = "NORMAL"
        if tier == "BIG":
            subtype = "BIG"
        elif tier == "MIDDLE":
            subtype = "MIDDLE"
        else:
            if has_high(1):
                subtype = "PRE_BIG"
            elif has_high(-1):
                subtype = "POST_BIG"
        # release-relation for this bounce
        rel_flag = "no-release"
        release_detail = ""
        target_ts = ev["ts_dt"]
        # any HIGH-impact release within [target-30min, target] on same day?
        # ON minute: exact same minute; POST_30: within 30m prior (release before bounce)
        recent_high = [n for n in highs_gbp_usd if 0 <= (target_ts - n["ts"]).total_seconds() <= 30 * 60]
        if recent_high:
            if any(n["ts"] == target_ts for n in recent_high):
                rel_flag = "ON-release-minute"
            elif any((target_ts - n["ts"]).total_seconds() <= 30 * 60
                     and (target_ts - n["ts"]).total_seconds() > 0 for n in recent_high):
                rel_flag = "POST-release-<=30m"
            release_detail = ";".join(f"{n['ts'].strftime('%H:%M')}={n['event']}" for n in recent_high)
        # regime proxy: use ~30d of prior H1 bars for EMA200
        regime = regime_proxy_h1(prev_bars_deep + bars, ev["ts_dt"])
        # direction vs London
        dir_vs_london = "n/a"
        if lond:
            london_dir = "UP" if lond["net"] > 0 else ("DOWN" if lond["net"] < 0 else "FLAT")
            bounce_side_after = "DOWN" if ev["side"] == "SELL" else "UP"
            if london_dir == "FLAT":
                dir_vs_london = "flat-london"
            elif london_dir == bounce_side_after:
                dir_vs_london = "CONTINUATION"
            else:
                dir_vs_london = "FADE"

        return dict(
            date=date_iso,
            time=ev["ts_dt"].strftime("%H:%M"),
            level=ev["level_name"],
            side=ev["side"],
            level_price=round(ev["level_price"], 2),
            tier=tier,
            subtype=subtype,
            highs_on_day=len(highs_gbp_usd),
            meds_on_day=len(meds),
            release_relation=rel_flag,
            release_detail=release_detail,
            london_net=lond["net"] if lond else None,
            london_range=lond["range"] if lond else None,
            london_eff=lond["efficiency"] if lond else None,
            regime=regime,
            bb_at=round(bb_at, 2) if bb_at else None,
            bb_med=round(bb_med, 2) if bb_med else None,
            bb_ratio=round(bb_at / bb_med, 2) if (bb_at and bb_med) else None,
            dir_vs_london=dir_vs_london,
            news_cache=("yes" if has_cache else "no"),
        )

    print()
    print("=" * 78)
    print("TASK 2 — BOUNCE-DAY CHARACTERISATION (per-bounce rows)")
    print("=" * 78)
    header = ["date", "T", "lvl", "side", "tier", "subtype", "reln",
              "L_net", "L_rng", "L_eff", "regime", "BB@", "BBmed", "R",
              "dir/L", "cache"]
    print("|" + "|".join(f" {h:^7} " for h in header) + "|")
    print("|" + "|".join("---------" for _ in header) + "|")

    all_bounce_rows_13 = []
    for d in sorted(bounce_days_13):
        for ev in bounce_days_13[d]:
            row = char_day(d, ev)
            row["window"] = "13:00"
            all_bounce_rows_13.append(row)

    all_bounce_rows_15 = []
    for d in sorted(bounce_days_15):
        for ev in bounce_days_15[d]:
            row = char_day(d, ev)
            row["window"] = "15:00"
            all_bounce_rows_15.append(row)

    def fmt_row(r):
        return "|" + "|".join(f" {str(v):^7} " for v in [
            r["date"], r["time"], r["level"], r["side"],
            r["tier"], r["subtype"], r["release_relation"],
            r["london_net"], r["london_range"], r["london_eff"],
            r["regime"], r["bb_at"], r["bb_med"], r["bb_ratio"],
            r["dir_vs_london"], r["news_cache"],
        ]) + "|"

    print("\n---- 13:00 window bounces ----")
    for r in all_bounce_rows_13:
        print(fmt_row(r))
    print("\n---- 15:00 window bounces ----")
    for r in all_bounce_rows_15:
        print(fmt_row(r))

    # release detail expanded
    print()
    print("---- release detail for bounces with ON/POST-release ----")
    for r in all_bounce_rows_13 + all_bounce_rows_15:
        if r["release_relation"] != "no-release":
            print(f"  {r['date']} {r['time']} ({r['window']}) {r['release_relation']} : {r['release_detail']}")

    # ---------- Task 3: non-bounce days characterisation ----------
    # define universe = all dates with bar data in event JSON
    all_dates = sorted(set(e["date"] for e in events))
    bounce_dates = set(list(bounce_days_13) + list(bounce_days_15))
    non_bounce = [d for d in all_dates if d not in bounce_dates]

    def summarise_group(dates, label):
        n = len(dates)
        # tier distribution using same tier logic
        tier_c = Counter()
        subtype_c = Counter()
        reg_c = Counter()
        lond_eff = []
        lond_range = []
        us_1230 = 0
        us_1400_1500 = 0
        cache_hits = 0
        for d in dates:
            has_cache = os.path.exists(f"/opt/tradingbot/cache/news_state_finnhub_{d}.json")
            cache_hits += (1 if has_cache else 0)
            day_ev = [n for n in news if n["date"] == d]
            highs = [n for n in day_ev if n["impact"] == "HIGH"
                     and n["currency"] in ("GBP", "USD")]
            meds = [n for n in day_ev if n["impact"] == "MED"
                    and n["currency"] in ("GBP", "USD")]
            if highs:
                tier = "BIG"
            elif meds:
                tier = "MIDDLE"
            elif day_ev:
                tier = "SMALL"
            else:
                tier = "NONE_or_UNAVAIL"
            tier_c[tier] += 1
            d0 = datetime.fromisoformat(d).date()
            def hh(delta):
                dd = (d0 + timedelta(days=delta)).isoformat()
                return any(n["date"] == dd and n["impact"] == "HIGH"
                           and n["currency"] in ("GBP", "USD") for n in news)
            if tier == "BIG":
                sub = "BIG"
            elif tier == "MIDDLE":
                sub = "MIDDLE"
            elif hh(1):
                sub = "PRE_BIG"
            elif hh(-1):
                sub = "POST_BIG"
            else:
                sub = "NORMAL"
            subtype_c[sub] += 1

            # US releases at 12:30 UTC (any impact)
            if any(n["ts"].hour == 12 and n["ts"].minute == 30
                   and n["currency"] == "USD" for n in day_ev):
                us_1230 += 1
            # US releases in 14:00..15:00 UTC
            if any(n["currency"] == "USD" and
                   ((n["ts"].hour == 14) or (n["ts"].hour == 15 and n["ts"].minute == 0))
                   for n in day_ev):
                us_1400_1500 += 1

            # London stats
            bars = bars_for(d)
            if bars:
                st = london_stats(bars)
                if st:
                    lond_eff.append(st["efficiency"])
                    lond_range.append(st["range"])
        return dict(
            n=n,
            tier=dict(tier_c),
            subtype=dict(subtype_c),
            london_eff_median=(round(median(lond_eff), 3) if lond_eff else None),
            london_range_median=(round(median(lond_range), 2) if lond_range else None),
            us_1230_days=us_1230,
            us_1400_1500_days=us_1400_1500,
            cache_hits=cache_hits,
        )

    grp_b13 = summarise_group(sorted(bounce_days_13), "bounce_13")
    grp_b15 = summarise_group(sorted(bounce_days_15), "bounce_15")
    grp_all_b = summarise_group(sorted(bounce_dates), "bounce_any")
    grp_nb = summarise_group(non_bounce, "non_bounce")

    print()
    print("=" * 78)
    print("TASK 3 — DAY-GROUP COMPARISON")
    print("=" * 78)
    for name, g in [("bounce 13:00 only-set", grp_b13),
                    ("bounce 15:00 only-set", grp_b15),
                    ("bounce ANY window", grp_all_b),
                    ("NON-bounce", grp_nb)]:
        print(f"\n[{name}]  n_days={g['n']}   news-cache-days={g['cache_hits']}/{g['n']}")
        print(f"  tier      {g['tier']}")
        print(f"  subtype   {g['subtype']}")
        print(f"  london_eff median={g['london_eff_median']}   london_range median={g['london_range_median']}")
        print(f"  US 12:30 releases:            {g['us_1230_days']}/{g['n']} days")
        print(f"  US 14:00–15:00 releases:      {g['us_1400_1500_days']}/{g['n']} days")

    # ---------- Task 4: news-slot hypothesis ----------
    print()
    print("=" * 78)
    print("TASK 4 — NEWS-SLOT HYPOTHESIS")
    print("=" * 78)
    def had_us_release(date_iso, hh_start, hh_end):
        """True if any USD release with ts hour in [hh_start,hh_end) (any impact) on that date."""
        for n in news:
            if n["date"] != date_iso:
                continue
            if n["currency"] != "USD":
                continue
            t = n["ts"].time()
            if time(hh_start[0], hh_start[1]) <= t < time(hh_end[0], hh_end[1]):
                return True
        return False
    def had_us_release_high(date_iso, hh_start, hh_end):
        for n in news:
            if n["date"] != date_iso:
                continue
            if n["currency"] != "USD":
                continue
            if n["impact"] != "HIGH":
                continue
            t = n["ts"].time()
            if time(hh_start[0], hh_start[1]) <= t < time(hh_end[0], hh_end[1]):
                return True
        return False

    # For the 13:00 window
    b13_cache = [d for d in bounce_days_13
                 if os.path.exists(f"/opt/tradingbot/cache/news_state_finnhub_{d}.json")]
    b13_1230 = [d for d in b13_cache if had_us_release(d, (12, 30), (12, 31))]
    b13_1230_high = [d for d in b13_cache if had_us_release_high(d, (12, 30), (12, 31))]
    b15_cache = [d for d in bounce_days_15
                 if os.path.exists(f"/opt/tradingbot/cache/news_state_finnhub_{d}.json")]
    b15_1400_1500 = [d for d in b15_cache
                     if had_us_release(d, (14, 0), (15, 1))]
    b15_1400_1500_high = [d for d in b15_cache
                          if had_us_release_high(d, (14, 0), (15, 1))]
    print(f"\n13:00 bounces with news cache: {len(b13_cache)}/{len(bounce_days_13)} "
          f"(pre-2026-06-06 have no cache coverage)")
    print(f"  had US 12:30 release (any impact): {len(b13_1230)}/{len(b13_cache)}  "
          f"({sorted(b13_1230)})")
    print(f"  had US 12:30 HIGH release:        {len(b13_1230_high)}/{len(b13_cache)}  "
          f"({sorted(b13_1230_high)})")
    print(f"\n15:00 bounces with news cache: {len(b15_cache)}/{len(bounce_days_15)}")
    print(f"  had US 14:00–15:00 release (any): {len(b15_1400_1500)}/{len(b15_cache)}  "
          f"({sorted(b15_1400_1500)})")
    print(f"  had US 14:00–15:00 HIGH release:  {len(b15_1400_1500_high)}/{len(b15_cache)}  "
          f"({sorted(b15_1400_1500_high)})")

    # For controls: how often do all-cache-days have those releases?
    all_cache_dates = [d for d in all_dates
                      if os.path.exists(f"/opt/tradingbot/cache/news_state_finnhub_{d}.json")]
    ctrl_1230 = sum(1 for d in all_cache_dates if had_us_release(d, (12, 30), (12, 31)))
    ctrl_1230_h = sum(1 for d in all_cache_dates if had_us_release_high(d, (12, 30), (12, 31)))
    ctrl_1415 = sum(1 for d in all_cache_dates if had_us_release(d, (14, 0), (15, 1)))
    ctrl_1415_h = sum(1 for d in all_cache_dates if had_us_release_high(d, (14, 0), (15, 1)))
    print(f"\nBASELINE (all cache-days, n={len(all_cache_dates)}):")
    print(f"  US 12:30 any release:    {ctrl_1230}/{len(all_cache_dates)} = "
          f"{ctrl_1230/len(all_cache_dates):.2f}")
    print(f"  US 12:30 HIGH release:   {ctrl_1230_h}/{len(all_cache_dates)} = "
          f"{ctrl_1230_h/len(all_cache_dates):.2f}")
    print(f"  US 14:00–15:00 any:      {ctrl_1415}/{len(all_cache_dates)} = "
          f"{ctrl_1415/len(all_cache_dates):.2f}")
    print(f"  US 14:00–15:00 HIGH:     {ctrl_1415_h}/{len(all_cache_dates)} = "
          f"{ctrl_1415_h/len(all_cache_dates):.2f}")

    # ---------- Task 5: three raw example days ----------
    print()
    print("=" * 78)
    print("TASK 5 — RAW EXAMPLE DAYS")
    print("=" * 78)

    def raw_example(date_iso, window_label, ev):
        print(f"\n---- {date_iso} — {window_label} bounce ----")
        print(f"  event: {ev['ts_dt'].strftime('%H:%M')} COINC OUTER {ev['level_name']}={ev['level_price']:.2f} "
              f"side={ev['side']}  MFE={ev['fwd_mfe_p']}p  MAE={ev['fwd_mae_p']}p  "
              f"turn10={ev['turn10']} turn15={ev['turn15']} turn25={ev['turn25']}  "
              f"closed_beyond={ev['close_beyond']}")
        # calendar
        day_ev = [n for n in news if n["date"] == date_iso]
        has_cache = os.path.exists(f"/opt/tradingbot/cache/news_state_finnhub_{date_iso}.json")
        print(f"  news-cache={'YES' if has_cache else 'NO (pre-2026-06-06)'}")
        for n in sorted(day_ev, key=lambda x: x["ts"]):
            print(f"    {n['ts'].strftime('%H:%M')} {n['currency']} {n['impact']:>4} — {n['event']}")
        # regime
        prev_bars_deep = bars_before(date_iso, n_days=45)
        bars = bars_for(date_iso)
        regime = regime_proxy_h1(prev_bars_deep + bars, ev["ts_dt"])
        print(f"  regime-proxy (H1 EMA20/50/200 + ADX14) at bounce: {regime}")
        # bars around bounce (-3..+3 = 6 bars)
        idx = None
        for i, b in enumerate(bars):
            if b[0] == ev["ts_dt"]:
                idx = i
                break
        if idx is not None:
            print(f"  5m bars around bounce (idx-3 .. idx+6):")
            for j in range(max(0, idx - 3), min(len(bars), idx + 7)):
                b = bars[j]
                marker = " *EV*" if j == idx else "     "
                print(f"    {b[0].strftime('%H:%M')} O {b[1]:.2f}  H {b[2]:.2f}  L {b[3]:.2f}  C {b[4]:.2f}{marker}")
        # BB width context
        warm = [b[4] for b in prev_bars_deep][-20:] if prev_bars_deep else []
        bb_at, bb_med = find_bb_width_at(bars, ev["ts_dt"], warm)
        print(f"  BB width at bounce = {bb_at:.2f}p  day-median = {bb_med:.2f}p  "
              f"ratio={bb_at/bb_med:.2f}" if (bb_at and bb_med) else "")

    # pick examples: prefer days with news cache (so calendar shows)
    ex_13 = None
    ex_15 = None
    ex_both = None
    # prefer days with news cache
    for d in sorted(bounce_days_13):
        if d in bounce_days_15:
            if os.path.exists(f"/opt/tradingbot/cache/news_state_finnhub_{d}.json"):
                ex_both = (d, bounce_days_13[d][0], bounce_days_15[d][0])
                break
    if ex_both is None:
        for d in both_days:
            ex_both = (d, bounce_days_13[d][0], bounce_days_15[d][0])
            break
    for d in sorted(bounce_days_13):
        if d in bounce_days_15:
            continue
        if os.path.exists(f"/opt/tradingbot/cache/news_state_finnhub_{d}.json"):
            ex_13 = (d, bounce_days_13[d][0])
            break
    if ex_13 is None:
        for d in sorted(bounce_days_13):
            if d in bounce_days_15:
                continue
            ex_13 = (d, bounce_days_13[d][0])
            break
    for d in sorted(bounce_days_15):
        if d in bounce_days_13:
            continue
        if os.path.exists(f"/opt/tradingbot/cache/news_state_finnhub_{d}.json"):
            ex_15 = (d, bounce_days_15[d][0])
            break
    if ex_15 is None:
        for d in sorted(bounce_days_15):
            if d in bounce_days_13:
                continue
            ex_15 = (d, bounce_days_15[d][0])
            break

    if ex_13:
        raw_example(ex_13[0], "13:00", ex_13[1])
    if ex_15:
        raw_example(ex_15[0], "15:00", ex_15[1])
    if ex_both:
        print(f"\n---- {ex_both[0]} — 13:00 AND 15:00 bounce ----")
        raw_example(ex_both[0], "13:00", ex_both[1])
        raw_example(ex_both[0], "15:00", ex_both[2])

    print("\n[DONE]")


if __name__ == "__main__":
    main()
