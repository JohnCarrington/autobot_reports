"""Addendum J — pivot-sequence tradeability under adverse movement.

Three tests on the 676-day certified dataset (same as Addenda H and I):

TEST 1 — continuation sequences R1→R2, R2→R3 (ABOVE days); S1→S2,
S2→S3 (BELOW days). For each day qualifying (first M5 bar touching
the starting pivot), check whether the destination is touched BEFORE
price moves adversely by {5, 10, 15, 20, 25} pips from the starting
pivot.

TEST 2 — central-pivot reclaim. For ABOVE days with an S1/S2 touch
followed by a completed M5 close ABOVE P, use that reclaim-close bar
as the starting point. Adverse reference is the reclaim bar's CLOSE.
Destination is R2. Mirror for BELOW days (R1/R2 touch + close below P;
destination S2).

TEST 3 — time-of-day. Bucket the qualifying event's UTC hour:
  * before 07:00 UTC
  * 07:00-11:59
  * 12:00-15:59
  * 16:00+

For each test + threshold:
  * Count destination-reached-before-adverse (clean win on sequence).
  * Count adverse-reached-first (sequence invalidated).
  * Count destination-NEVER-reached (same-day end before destination).
  * Count AMBIGUOUS (same M5 bar crosses both destination AND adverse
    threshold; without tick data we cannot order them).

M5 definition: adverse = price moves below (BUY context) or above
(SELL context) the reference by the threshold. Reference depends on
test — starting pivot for Test 1, reclaim close for Test 2.

No HTF filters, no EMAs, no exhaustion, no classifier. No trade sim —
this is a path-geometry audit only.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import statistics
from collections import defaultdict

BID_ROOT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
MID_ROOT = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")
OUT_CSV = pathlib.Path(__file__).parent.parent / "csv" / "addendum_j_results.csv"

THRESHOLDS = (5, 10, 15, 20, 25)

def load_day(path: pathlib.Path) -> list[dict]:
    if not path.exists(): return []
    out = []
    for row in csv.DictReader(path.open()):
        ts_raw = row["timestamp"].replace(" ", "T")
        try: ts = dt.datetime.fromisoformat(ts_raw)
        except: continue
        out.append({"ts": ts,
                    "o": float(row["open"])/10000.0,
                    "h": float(row["high"])/10000.0,
                    "l": float(row["low"])/10000.0,
                    "c": float(row["close"])/10000.0})
    return out

def pivots(H, L, C):
    P = (H + L + C) / 3.0
    return {
        "P":  P,
        "R1": 2*P - L, "S1": 2*P - H,
        "R2": P + (H-L), "S2": P - (H-L),
        "R3": H + 2*(P - L), "S3": L - 2*(H - P),
    }

def first_touch(bars, level, start=0):
    for i in range(start, len(bars)):
        if bars[i]["l"] <= level <= bars[i]["h"]:
            return i
    return None

def first_close_above(bars, level, start=0):
    for i in range(start, len(bars)):
        if bars[i]["c"] > level:
            return i
    return None

def first_close_below(bars, level, start=0):
    for i in range(start, len(bars)):
        if bars[i]["c"] < level:
            return i
    return None

def sequence_outcome_above(bars, start_idx, reference, destination, threshold_pips):
    """For a BUY-direction sequence (destination ABOVE reference): starting at
    bar index `start_idx`, scan forward. Return one of:
      DEST_FIRST: destination touched before adverse
      ADV_FIRST:  adverse threshold hit before destination
      AMBIG:      same M5 bar crosses both
      NEVER:      neither reached by EOD

    Also return minutes-to-destination (bars × 5) and MAE pips to destination
    (if reached).
    """
    adv_level = reference - threshold_pips / 10000.0
    n = len(bars)
    min_low = reference  # track min since start for MAE
    for j in range(start_idx, n):
        b = bars[j]
        bar_adv = b["l"] <= adv_level
        bar_dest = b["h"] >= destination
        min_low = min(min_low, b["l"])
        if bar_adv and bar_dest:
            # Same M5 bar — ambiguous
            return ("AMBIG", (j - start_idx) * 5, (reference - min_low) * 10000.0)
        if bar_dest:
            return ("DEST_FIRST", (j - start_idx) * 5, (reference - min_low) * 10000.0)
        if bar_adv:
            return ("ADV_FIRST", None, (reference - min_low) * 10000.0)
    return ("NEVER", None, (reference - min_low) * 10000.0)

def sequence_outcome_below(bars, start_idx, reference, destination, threshold_pips):
    """For a SELL-direction sequence (destination BELOW reference). Adverse is
    price rising above reference by threshold."""
    adv_level = reference + threshold_pips / 10000.0
    n = len(bars)
    max_high = reference
    for j in range(start_idx, n):
        b = bars[j]
        bar_adv = b["h"] >= adv_level
        bar_dest = b["l"] <= destination
        max_high = max(max_high, b["h"])
        if bar_adv and bar_dest:
            return ("AMBIG", (j - start_idx) * 5, (max_high - reference) * 10000.0)
        if bar_dest:
            return ("DEST_FIRST", (j - start_idx) * 5, (max_high - reference) * 10000.0)
        if bar_adv:
            return ("ADV_FIRST", None, (max_high - reference) * 10000.0)
    return ("NEVER", None, (max_high - reference) * 10000.0)

def tod_bucket(utc_hour: int) -> str:
    if utc_hour < 7: return "before_07"
    if utc_hour < 12: return "0700_1159"
    if utc_hour < 16: return "1200_1559"
    return "1600_plus"

def main() -> None:
    # Load daily cache
    daily_cache: dict[dt.date, list[dict]] = {}
    for root in (BID_ROOT, MID_ROOT):
        for f in root.glob("*.csv"):
            try: d = dt.date.fromisoformat(f.stem)
            except: continue
            if d.year == 2026 and d.month > 2: continue
            if d not in daily_cache:
                daily_cache[d] = load_day(f)
    sorted_dates = sorted(daily_cache.keys())
    prior_rollup = {}
    for d in sorted_dates:
        bars = daily_cache[d]
        if bars:
            prior_rollup[d] = (max(b["h"] for b in bars),
                               min(b["l"] for b in bars),
                               bars[-1]["c"])

    # Aggregate records
    above_days, below_days = [], []
    for d in sorted_dates:
        bars = daily_cache[d]
        if not bars: continue
        prior = None
        for back in range(1, 8):
            cand = d - dt.timedelta(days=back)
            if cand in prior_rollup:
                prior = prior_rollup[cand]; break
        if prior is None: continue
        H, L, C = prior
        piv = pivots(H, L, C)
        open_px = bars[0]["o"]
        if open_px > piv["P"]: side = "ABOVE"
        elif open_px < piv["P"]: side = "BELOW"
        else: continue
        rec = {"date": d, "bars": bars, "piv": piv}
        if side == "ABOVE": above_days.append(rec)
        else: below_days.append(rec)

    # ---------- TEST 1 ----------
    SEQS_ABOVE = (("R1", "R2"), ("R2", "R3"))
    SEQS_BELOW = (("S1", "S2"), ("S2", "S3"))

    def run_continuation(days_group, seqs, side):
        """Returns: for each (start, dest) and each threshold, counts and median time."""
        results = {}  # (start, dest, threshold) -> counter dict
        for (start, dest) in seqs:
            # Collect qualifying days: those touching `start`
            quals = []
            for d in days_group:
                bars = d["bars"]; piv = d["piv"]
                start_price = piv[start]; dest_price = piv[dest]
                # First touch of starting pivot
                t_start = first_touch(bars, start_price)
                if t_start is None: continue
                quals.append((d, t_start, start_price, dest_price, bars[t_start]["ts"]))

            for th in THRESHOLDS:
                c = {"DEST_FIRST": 0, "ADV_FIRST": 0, "AMBIG": 0, "NEVER": 0,
                     "times_to_dest": [], "mae_on_dest": []}
                for (d, t_start, start_price, dest_price, ts) in quals:
                    bars = d["bars"]
                    if side == "ABOVE":
                        outc, tmin, mae = sequence_outcome_above(bars, t_start,
                                                                   start_price, dest_price, th)
                    else:
                        outc, tmin, mae = sequence_outcome_below(bars, t_start,
                                                                   start_price, dest_price, th)
                    c[outc] += 1
                    if outc == "DEST_FIRST":
                        c["times_to_dest"].append(tmin)
                        c["mae_on_dest"].append(mae)
                results[(start, dest, th)] = {"qual": len(quals), **c}
            # Also store the quals for ToD breakdown
            results[(start, dest, "quals")] = quals
        return results

    res_above = run_continuation(above_days, SEQS_ABOVE, "ABOVE")
    res_below = run_continuation(below_days, SEQS_BELOW, "BELOW")

    # ---------- Reporting Test 1 ----------
    out_rows = []
    def print_test1(side, results, seqs):
        print(f"\n{'='*80}")
        print(f"TEST 1 — CONTINUATION — DAYS OPENING {side}")
        print(f"{'='*80}")
        for (start, dest) in seqs:
            quals_n = results[(start, dest, THRESHOLDS[0])]["qual"]
            print(f"\n{start} → {dest}  (N qualifying = {quals_n})")
            print(f"  {'thresh':>7}  {'DEST':>6} {'ADV':>6} {'AMBIG':>6} {'NEVER':>6}  "
                  f"{'DEST%':>6}  {'median_min':>10}  {'med_MAE':>8}")
            for th in THRESHOLDS:
                r = results[(start, dest, th)]
                n = r["qual"]; dn = r["DEST_FIRST"]; an = r["ADV_FIRST"]; am = r["AMBIG"]; nv = r["NEVER"]
                pct = 100 * dn / max(n, 1)
                mt = statistics.median(r["times_to_dest"]) if r["times_to_dest"] else float("nan")
                mm = statistics.median(r["mae_on_dest"]) if r["mae_on_dest"] else float("nan")
                print(f"  {th:>5}p   {dn:>6} {an:>6} {am:>6} {nv:>6}  {pct:>5.1f}%  {mt:>10.1f}  {mm:>7.1f}p")
                out_rows.append({"test": "T1", "side": side, "sequence": f"{start}->{dest}",
                                 "threshold_pips": th, "qualifying": n,
                                 "DEST_FIRST": dn, "ADV_FIRST": an, "AMBIG": am, "NEVER": nv,
                                 "pct_dest_first": f"{pct:.1f}%",
                                 "median_min_to_dest": f"{mt:.1f}" if mt==mt else "",
                                 "median_mae_at_dest_pips": f"{mm:.1f}" if mm==mm else ""})

    print_test1("ABOVE", res_above, SEQS_ABOVE)
    print_test1("BELOW", res_below, SEQS_BELOW)

    # ---------- TEST 2 — reclaim ----------
    print(f"\n{'='*80}")
    print("TEST 2 — CENTRAL-PIVOT RECLAIM")
    print(f"{'='*80}")

    def run_reclaim(days_group, side, pullback_pivots, destination_pivot):
        reclaim_quals = []
        for d in days_group:
            bars = d["bars"]; piv = d["piv"]
            first_pb = None
            for pb in pullback_pivots:
                t = first_touch(bars, piv[pb])
                if t is not None:
                    if first_pb is None or t < first_pb[0]:
                        first_pb = (t, pb)
            if first_pb is None: continue
            if side == "ABOVE":
                reclaim_idx = first_close_above(bars, piv["P"], start=first_pb[0] + 1)
            else:
                reclaim_idx = first_close_below(bars, piv["P"], start=first_pb[0] + 1)
            if reclaim_idx is None: continue
            reclaim_close = bars[reclaim_idx]["c"]
            reclaim_quals.append((d, reclaim_idx, reclaim_close, piv[destination_pivot], bars[reclaim_idx]["ts"]))
        return reclaim_quals

    # ABOVE
    ab_quals = run_reclaim(above_days, "ABOVE", ("S1", "S2"), "R2")
    print(f"\nABOVE — S1/S2 touch then M5 close > P.  N qualifying = {len(ab_quals)}")
    print(f"  {'thresh':>7}  {'DEST':>6} {'ADV':>6} {'AMBIG':>6} {'NEVER':>6}  {'DEST%':>6}  "
          f"{'median_min':>10}  {'med_MAE':>8}")
    for th in THRESHOLDS:
        c = {"DEST_FIRST": 0, "ADV_FIRST": 0, "AMBIG": 0, "NEVER": 0, "tm": [], "mae": []}
        for (d, idx, ref, dest, ts) in ab_quals:
            outc, tmin, mae = sequence_outcome_above(d["bars"], idx, ref, dest, th)
            c[outc] += 1
            if outc == "DEST_FIRST": c["tm"].append(tmin); c["mae"].append(mae)
        n = len(ab_quals); dn = c["DEST_FIRST"]; pct = 100 * dn / max(n, 1)
        mt = statistics.median(c["tm"]) if c["tm"] else float("nan")
        mm = statistics.median(c["mae"]) if c["mae"] else float("nan")
        print(f"  {th:>5}p   {dn:>6} {c['ADV_FIRST']:>6} {c['AMBIG']:>6} {c['NEVER']:>6}  {pct:>5.1f}%  {mt:>10.1f}  {mm:>7.1f}p")
        out_rows.append({"test": "T2", "side": "ABOVE", "sequence": "S1/S2+Preclaim->R2",
                         "threshold_pips": th, "qualifying": n,
                         "DEST_FIRST": dn, "ADV_FIRST": c["ADV_FIRST"], "AMBIG": c["AMBIG"], "NEVER": c["NEVER"],
                         "pct_dest_first": f"{pct:.1f}%",
                         "median_min_to_dest": f"{mt:.1f}" if mt==mt else "",
                         "median_mae_at_dest_pips": f"{mm:.1f}" if mm==mm else ""})

    # BELOW
    be_quals = run_reclaim(below_days, "BELOW", ("R1", "R2"), "S2")
    print(f"\nBELOW — R1/R2 touch then M5 close < P.  N qualifying = {len(be_quals)}")
    print(f"  {'thresh':>7}  {'DEST':>6} {'ADV':>6} {'AMBIG':>6} {'NEVER':>6}  {'DEST%':>6}  "
          f"{'median_min':>10}  {'med_MAE':>8}")
    for th in THRESHOLDS:
        c = {"DEST_FIRST": 0, "ADV_FIRST": 0, "AMBIG": 0, "NEVER": 0, "tm": [], "mae": []}
        for (d, idx, ref, dest, ts) in be_quals:
            outc, tmin, mae = sequence_outcome_below(d["bars"], idx, ref, dest, th)
            c[outc] += 1
            if outc == "DEST_FIRST": c["tm"].append(tmin); c["mae"].append(mae)
        n = len(be_quals); dn = c["DEST_FIRST"]; pct = 100 * dn / max(n, 1)
        mt = statistics.median(c["tm"]) if c["tm"] else float("nan")
        mm = statistics.median(c["mae"]) if c["mae"] else float("nan")
        print(f"  {th:>5}p   {dn:>6} {c['ADV_FIRST']:>6} {c['AMBIG']:>6} {c['NEVER']:>6}  {pct:>5.1f}%  {mt:>10.1f}  {mm:>7.1f}p")
        out_rows.append({"test": "T2", "side": "BELOW", "sequence": "R1/R2+Preclaim->S2",
                         "threshold_pips": th, "qualifying": n,
                         "DEST_FIRST": dn, "ADV_FIRST": c["ADV_FIRST"], "AMBIG": c["AMBIG"], "NEVER": c["NEVER"],
                         "pct_dest_first": f"{pct:.1f}%",
                         "median_min_to_dest": f"{mt:.1f}" if mt==mt else "",
                         "median_mae_at_dest_pips": f"{mm:.1f}" if mm==mm else ""})

    # ---------- No-reclaim comparison ----------
    print(f"\n{'='*80}")
    print("No-reclaim comparison (Addendum I denominator resolution)")
    print(f"{'='*80}")
    # ABOVE: days touching S1/S2 but NO P close reclaim before EOD
    for side, days_group, pullbacks, dest_name, dest_direction in (
        ("ABOVE", above_days, ("S1", "S2"), "R2", "UP"),
        ("BELOW", below_days, ("R1", "R2"), "S2", "DOWN"),
    ):
        touched = []
        no_reclaim = []
        for d in days_group:
            bars = d["bars"]; piv = d["piv"]
            first_pb = None
            for pb in pullbacks:
                t = first_touch(bars, piv[pb])
                if t is not None:
                    if first_pb is None or t < first_pb:
                        first_pb = t
            if first_pb is None: continue
            touched.append(d)
            if dest_direction == "UP":
                rec_idx = first_close_above(bars, piv["P"], start=first_pb + 1)
            else:
                rec_idx = first_close_below(bars, piv["P"], start=first_pb + 1)
            if rec_idx is None: no_reclaim.append(d)
        # of no_reclaim: did they reach the destination?
        reached = 0
        for d in no_reclaim:
            t_dest = first_touch(d["bars"], d["piv"][dest_name])
            if t_dest is not None:
                reached += 1
        pct = 100 * reached / max(len(no_reclaim), 1)
        print(f"  {side} — touched pullback = {len(touched)}  |  no-reclaim = {len(no_reclaim)}  |  "
              f"of no-reclaim, reached {dest_name}: {reached} ({pct:.1f}%)")

    # ---------- TEST 3 — time-of-day ----------
    print(f"\n{'='*80}")
    print("TEST 3 — TIME-OF-DAY BREAKDOWN (qualifying event UTC hour)")
    print(f"{'='*80}")

    def tod_run_continuation(days_group, start, dest, side):
        """Return dict bucket -> (n_qual, {th: (dest_first, pct)})."""
        buckets = defaultdict(lambda: {"quals": 0,
                                        **{th: {"DEST_FIRST": 0, "ADV_FIRST": 0, "AMBIG": 0, "NEVER": 0, "tm": []}
                                           for th in THRESHOLDS}})
        for d in days_group:
            bars = d["bars"]; piv = d["piv"]
            t_start = first_touch(bars, piv[start])
            if t_start is None: continue
            bucket = tod_bucket(bars[t_start]["ts"].hour)
            buckets[bucket]["quals"] += 1
            start_price = piv[start]; dest_price = piv[dest]
            for th in THRESHOLDS:
                if side == "ABOVE":
                    outc, tmin, _ = sequence_outcome_above(bars, t_start, start_price, dest_price, th)
                else:
                    outc, tmin, _ = sequence_outcome_below(bars, t_start, start_price, dest_price, th)
                buckets[bucket][th][outc] += 1
                if outc == "DEST_FIRST": buckets[bucket][th]["tm"].append(tmin)
        return buckets

    for (start, dest), side, days_group in (
        (("R1", "R2"), "ABOVE", above_days),
        (("R2", "R3"), "ABOVE", above_days),
        (("S1", "S2"), "BELOW", below_days),
        (("S2", "S3"), "BELOW", below_days),
    ):
        buckets = tod_run_continuation(days_group, start, dest, side)
        print(f"\n{start} → {dest}  ({side}):")
        print(f"  {'bucket':<12} {'N':>5}  " + " ".join(f"{str(th)+'p':>9}" for th in THRESHOLDS))
        for b in ("before_07", "0700_1159", "1200_1559", "1600_plus"):
            row = buckets[b]
            n = row["quals"]
            cells = []
            for th in THRESHOLDS:
                r = row[th]; dn = r["DEST_FIRST"]
                pct = 100*dn/max(n,1)
                cells.append(f"{dn}/{n} {pct:4.1f}%")
            print(f"  {b:<12} {n:>5}  " + " ".join(f"{c:>9}" for c in cells))
            for th in THRESHOLDS:
                r = row[th]
                out_rows.append({"test": "T3", "side": side, "sequence": f"{start}->{dest}",
                                 "threshold_pips": th, "qualifying": n,
                                 "DEST_FIRST": r["DEST_FIRST"], "ADV_FIRST": r["ADV_FIRST"],
                                 "AMBIG": r["AMBIG"], "NEVER": r["NEVER"],
                                 "pct_dest_first": f"{100*r['DEST_FIRST']/max(n,1):.1f}%",
                                 "tod_bucket": b})

    # Save CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    keys = set()
    for r in out_rows: keys.update(r.keys())
    fields = ["test","side","sequence","threshold_pips","tod_bucket","qualifying",
              "DEST_FIRST","ADV_FIRST","AMBIG","NEVER","pct_dest_first",
              "median_min_to_dest","median_mae_at_dest_pips"]
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out_rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"\nWrote {len(out_rows)} rows to {OUT_CSV}")

if __name__ == "__main__":
    main()
