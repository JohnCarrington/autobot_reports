"""Independent day-classification. Fixed zigzag."""
import csv, os, glob, json
from collections import Counter

CANDLES = "/opt/tradingbot/data/candles/GBPUSD"
REV_PIPS = 15.0
RUN_MIN  = 40.0
GRIND_RANGE_MIN = 60.0
GRIND_NET_FRAC  = 0.70
GRIND100 = 100.0

def load_day(path):
    rows = []
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                rows.append((row["timestamp"], float(row["open"]), float(row["high"]),
                             float(row["low"]), float(row["close"])))
            except Exception:
                continue
    return rows

def find_runs(rows):
    """Returns list of runs (dicts) — legs whose |mag| ≥ 40p."""
    if len(rows) < 2:
        return []
    closes = [r[4] for r in rows]
    pivots = [(0, closes[0])]        # (bar_idx, close)
    max_i, max_c = 0, closes[0]
    min_i, min_c = 0, closes[0]
    direction = 0                     # 0=undetermined, +1=up leg, -1=down leg

    for i in range(1, len(closes)):
        c = closes[i]
        if direction == 0:
            if c > max_c:
                max_i, max_c = i, c
            if c < min_c:
                min_i, min_c = i, c
            # first-pivot commit
            if max_c - c >= REV_PIPS:
                pivots.append((max_i, max_c))
                direction = -1
                min_i, min_c = i, c
            elif c - min_c >= REV_PIPS:
                pivots.append((min_i, min_c))
                direction = +1
                max_i, max_c = i, c
        elif direction == +1:
            if c > max_c:
                max_i, max_c = i, c
            if max_c - c >= REV_PIPS:
                pivots.append((max_i, max_c))
                direction = -1
                min_i, min_c = i, c
        else:  # direction == -1
            if c < min_c:
                min_i, min_c = i, c
            if c - min_c >= REV_PIPS:
                pivots.append((min_i, min_c))
                direction = +1
                max_i, max_c = i, c
    # tail pivot: final running extreme
    if direction == +1:
        tail = (max_i, max_c)
    elif direction == -1:
        tail = (min_i, min_c)
    else:
        # no confirmed direction; take further extreme from open as tail
        # audit's "final running extreme" — if never flipped, both are open-tracked
        if abs(max_c - closes[0]) >= abs(min_c - closes[0]):
            tail = (max_i, max_c)
        else:
            tail = (min_i, min_c)
    if pivots[-1] != tail:
        pivots.append(tail)

    runs = []
    for a, b in zip(pivots, pivots[1:]):
        i0, c0 = a
        i1, c1 = b
        mag = abs(c1 - c0)
        if mag >= RUN_MIN:
            runs.append(dict(
                start_bar=i0, end_bar=i1,
                start_close=c0, end_close=c1,
                start_ts=rows[i0][0], end_ts=rows[i1][0],
                direction=(+1 if c1 > c0 else -1),
                magnitude=mag,
            ))
    return runs

def classify_day(rows):
    if not rows:
        return None
    closes = [r[4] for r in rows]
    highs  = [r[2] for r in rows]
    lows   = [r[3] for r in rows]
    n = len(rows)
    day_range = max(highs) - min(lows)
    day_net   = closes[-1] - closes[0]
    runs      = find_runs(rows)
    n_runs    = len(runs)
    is_grind  = day_range >= GRIND_RANGE_MIN and abs(day_net) >= GRIND_NET_FRAC * day_range
    grind100  = is_grind and abs(day_net) >= GRIND100
    if is_grind:
        cls = "GRIND_DAY"
    elif n_runs == 0:
        cls = "QUIET_DAY"
    elif n_runs >= 3:
        cls = "MULTI_DAY"
    else:
        cls = "BOUNCE_DAY"
    return dict(n_rows=n, range=day_range, net=day_net, n_runs=n_runs,
                is_grind=is_grind, grind100=grind100, cls=cls,
                first_ts=rows[0][0], last_ts=rows[-1][0],
                runs=runs)

if __name__ == "__main__":
    files = sorted(glob.glob(f"{CANDLES}/*.csv"))
    days = {}
    for f in files:
        date = os.path.basename(f).replace(".csv","")
        rows = load_day(f)
        if not rows:
            continue
        summ = classify_day(rows)
        summ["full_day"] = summ["n_rows"] >= 200
        days[date] = summ

    n_all = len(days)
    full = {d:v for d,v in days.items() if v["full_day"]}
    n_full = len(full)
    print(f"[C0] all-day CSVs classified: {n_all}, full days (>=200 rows): {n_full}")

    cls_ct = Counter([v["cls"] for v in full.values()])
    print(f"[C0] full-day day-class histogram (mine):")
    for k in ("BOUNCE_DAY","GRIND_DAY","QUIET_DAY","MULTI_DAY"):
        print(f"     {k:12s} {cls_ct.get(k,0):3d}  {cls_ct.get(k,0)/n_full*100:5.1f}%")

    grind100 = [(d,v) for d,v in full.items() if v["grind100"]]
    print(f"[C0] GRIND_100 days (mine): n={len(grind100)}")
    for d,v in sorted(grind100):
        print(f"     {d}  net={v['net']:+7.1f} range={v['range']:6.1f} runs={v['n_runs']}")

    run_hist = Counter([v["n_runs"] for v in full.values()])
    print(f"[C0] runs-per-day histogram (mine):")
    for k in sorted(run_hist):
        print(f"     runs={k:2d}  n={run_hist[k]:3d}")

    # persist
    dump = {}
    for d,v in days.items():
        dump[d] = dict(
            n_rows=v["n_rows"], range=v["range"], net=v["net"], n_runs=v["n_runs"],
            is_grind=v["is_grind"], grind100=v["grind100"], cls=v["cls"],
            full_day=v["full_day"], first_ts=v["first_ts"], last_ts=v["last_ts"],
            runs=v["runs"],
        )
    json.dump(dump, open("/tmp/tier3_days_class.json","w"), indent=1, default=str)
