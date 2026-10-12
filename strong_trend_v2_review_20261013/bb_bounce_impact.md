# BB-Bounce impact — chronological trade decisions under v2

The BB-Bounce guard (`session_trend_guard.py`) blocks a trade when
the proposed direction opposes an established STRONG trend. On any
day where `session_trend.prevailing` ∈ {UP, DOWN}:

- **UP established** → BUYs allowed, **SELLs blocked**.
- **DOWN established** → **BUYs blocked**, SELLs allowed.
- UNKNOWN / RANGE → no restriction.

The guard is read-only; it reads a JSON snapshot and never calls
IG. The flag `BB_BOUNCE_SESSION_TREND_GUARD_ENABLED` gates all
blocking; stale/missing/corrupt snapshots never block.

---

## 2026-10-12 — trigger case (archive-driven replay)

Known 8 pinned trade entries from the historical journal, with
the guard decision at each entry time:

| Entry | Side | Prevailing at entry | v1 (`403922e`) | **v2 (`f90ffd2`)** | Protection recovered |
|---|---|---|---|---|---|
| 08:10:11 | SELL | UNKNOWN | allow | allow | n/a |
| 09:35:12 | BUY  | UNKNOWN | allow | allow | n/a (DOWN not yet established) |
| 10:20:18 | BUY  | DOWN (since 09:50) | allow | **block** | ✓ |
| 11:18:06 | BUY  | DOWN (since 09:50) | allow | **block** | ✓ |
| 12:20:14 | SELL | DOWN (since 09:50) | allow | allow | n/a (aligned) |
| 14:10:14 | BUY  | DOWN (since 09:50) | allow | **block** | ✓ |
| 15:25:22 | SELL | DOWN (since 09:50) | allow | allow | n/a (aligned) |
| 16:10:24 | BUY  | DOWN (since 09:50) | block | **block** | ✓ (unchanged) |

**v2 blocks all 4 historical losing BUYs.** v1 only blocked the
final one (16:10) because its DOWN establishment arrived too late.

Pinned regression test:
`tests/data_continuity/test_phase8_oct12_regression.py` (passes
under v2; previously set to expect only 1 block under v1).

---

## 34-day guard-impact summary (hypothetical)

The live BB-Bounce archive doesn't contain entry events for every
day in the window, so the table below is derived from the ST
`prevailing` state at the common BB-Bounce entry hours (09:00,
10:00, 11:00, 12:00, 13:00, 14:00 UTC). For each hour × side ×
day, we check whether the guard would block.

The intent is to characterise:
- Days where BUY blocks apply (DOWN established)
- Days where SELL blocks apply (UP established)
- Days where no restriction applies

For a day marked `truth=UP` the guard applying `SELL block` is
correct (aligned direction trades, counter blocked). For `truth=
RANGE` or `NORMAL`, any block is an **unnecessary restriction**.

| Day truth | ST=DOWN days (BUY blocked) | ST=UP days (SELL blocked) | ST=RANGE/UNKNOWN (no block) |
|---|---|---|---|
| DOWN (12 days) | 8 | 0 | 4 |
| UP (6 days)   | 0 | 3 | 3 |
| NORMAL (7)    | 1 | 1 | 5 |
| RANGE (9)     | 2 | 0 | 7 |

**Unnecessary restrictions on non-trend days: 4** (1 NORMAL→DOWN
+ 1 NORMAL→UP + 2 RANGE→DOWN). These are the 4 FPs documented in
the README.

---

## Note on "within-day wrong-direction fires"

2 UP-truth days fire DOWN first then release before EOD:

- **2026-09-18:** DOWN established 10:45 UTC, released to UNKNOWN
  before close. During the window ~10:45 → release moment, aligned
  BUYs are blocked. If a BUY entry fell in that window on a true-UP
  day, it was wrongly rejected.
- **2026-10-02:** DOWN established 12:10 UTC, final state RANGE
  (so release did fire). Same cost model.

Historical BB-Bounce fires on these two days were not available in
my local archive, so direct trade impact can't be computed.
Operator could overlay from the live journal.

---

## Guard flag + deployment

```
# .env
BB_BOUNCE_SESSION_TREND_GUARD_ENABLED=1
SESSION_TREND_GUARD_MAX_AGE_SECS=600
# Optional overrides (all default-sensible):
# SESSION_TREND_MIN_STRUCTURE_RUN=3
# SESSION_TREND_MIN_STRUCTURE_ASYMMETRY=2
# SESSION_TREND_MIN_PULLBACK_CONTINUES=1
# SESSION_TREND_MAX_RANGE_REVERSALS=2
# SESSION_TREND_CLOSE_POS_DOWN_CEILING=0.35
# SESSION_TREND_CLOSE_POS_UP_FLOOR=0.65
# SESSION_TREND_DISP_DIRECTION_SANITY_PIPS=10
# SESSION_TREND_PERSISTENCE_BARS=2
```

Deployment steps (operator action — **not taken by this change**):

1. Merge AutoBot dev branch `feat/nms-data-continuity-stages1-3-20261012`.
2. Merge BB-Bounce dev branch `feat/nms-session-trend-guard-20261013`.
3. Set the env flags above in each host's `.env`.
4. Restart `autobot-start.service` (AutoBot host) and `bb-bounce.service`
   (BB-Bounce host).
5. Monitor snapshot file at `data/session_trend_GBPUSD.json`.
