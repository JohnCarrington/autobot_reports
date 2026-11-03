"""Phase 4 — session bucketing of pivot events.

Reads csv/pivot_events.csv and splits by session window (UTC hour-of-day).

Session windows used (fixed, based on market convention):
  * Asia:                 00:00 - 06:59 UTC
  * London open:          07:00 - 08:59 UTC
  * London morning:       09:00 - 11:59 UTC
  * London/NY overlap:    12:00 - 16:00 UTC
  * Late NY:              16:00 - 22:00 UTC
  * Weekend stub:         22:00 - 23:59 UTC (included for completeness)

For each bucket, report: n events, reach-rate, reject+both rate per pivot.
"""

from __future__ import annotations

import csv
import pathlib
from collections import Counter, defaultdict

CSV_PATH = pathlib.Path(__file__).parent.parent / "csv" / "pivot_events.csv"

PIVOT_NAMES = ("S3", "S2", "S1", "P", "R1", "R2", "R3")

def session_label(ts_iso: str) -> str:
    h = int(ts_iso[11:13])
    if 0 <= h < 7:   return "Asia"
    if 7 <= h < 9:   return "LondonOpen"
    if 9 <= h < 12:  return "LondonMorning"
    if 12 <= h < 16: return "LN_NY_Overlap"
    if 16 <= h < 22: return "LateNY"
    return "WeekendStub"

def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open()))
    print(f"Loaded {len(rows)} events")

    # Bucket by session
    by_session: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_session[session_label(r["bar_ts"])].append(r)

    print(f"\n=== Session volume ===")
    for s, evs in sorted(by_session.items(), key=lambda x: -len(x[1])):
        print(f"  {s:<14} n={len(evs):>5}")

    for session, evs in sorted(by_session.items()):
        print(f"\n=== {session} — n={len(evs)} ===")
        counts   = Counter(e["pivot_name"] for e in evs)
        reach    = defaultdict(lambda: [0, 0])
        reject_n = defaultdict(int)
        brk_n    = defaultdict(int)
        both_n   = defaultdict(int)
        neither_n= defaultdict(int)
        for e in evs:
            p = e["pivot_name"]
            reach[p][1] += 1
            if e["next_pivot_reached"]:
                reach[p][0] += 1
            rj, bk = int(e["reject_flag"]), int(e["breakout_flag"])
            if rj and bk:
                both_n[p] += 1
            elif rj:
                reject_n[p] += 1
            elif bk:
                brk_n[p] += 1
            else:
                neither_n[p] += 1
        print(f"  {'Lvl':4} {'n':>4} {'Reach%':>7} {'Rej%':>7} {'Brk%':>7} {'Both%':>7} {'Neit%':>7}")
        for p in PIVOT_NAMES:
            n = counts.get(p, 0)
            if n == 0:
                continue
            reach_pct = 100 * reach[p][0] / n if n else 0
            rj_pct = 100 * reject_n[p] / n
            bk_pct = 100 * brk_n[p]    / n
            bo_pct = 100 * both_n[p]   / n
            ne_pct = 100 * neither_n[p]/ n
            print(f"  {p:<4} {n:>4} {reach_pct:>6.0f}% {rj_pct:>6.0f}% {bk_pct:>6.0f}% {bo_pct:>6.0f}% {ne_pct:>6.0f}%")

if __name__ == "__main__":
    main()
