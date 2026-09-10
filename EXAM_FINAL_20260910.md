# FINAL EXAM REPORT — 2026-09-07 → 2026-09-10

**Host**: 161  **Working dir**: `/opt/tradingbot`
**HEAD**: `ff09d6d 2026-09-10 11:06:23 +0000 amend(exam) #2: freshness=opened_at, same-bar collision mute, score persistence`
**Freeze manifest**: `docs/exam_freeze_20260907.md` (Baseline `7b7a88f` + Sunday apparatus commits)
**Scope**: Mon 2026-09-07 → Thu 2026-09-10, per the operator's brief.
**Kind**: read-only. Every number below cites its source file or command.

Freeze manifest text (verbatim, `docs/exam_freeze_20260907.md`):
> The freeze RULES
> 1. **No approach-context fix after an ugly velocity trade.** … not to be patched mid-week.
> 2. **No adjacent-bar mute mid-week.** The known BUY-then-SELL adjacent velocity arm collision (F3 specimen) is observable in shadow. It is not to be suppressed by a new rule mid-week.
> 3. **No floor change.** `QM_JOIN_FLOOR=7` is the fire-time V2 gate.
> 4. **No reclassification of past signals.**
> 5. **No LIVE-FIRE flip.** `QM_LIVE_FIRE=0` … must remain absent.
>
> **Any change during the exam voids the exam — the manifest is the contract.**

Changelog amendments (verbatim, same file):
- **2026-09-08 (amendment, operator-ruled)** — dedup family key + rejection-family base parity (12). Local commit `089a547`.
- **2026-09-09 (amendment #2, operator-ruled)** — freshness canonical source = `opened_at`; same-bar opposite-direction collision mute; score/family/source_engine persistence in seen jsonl. Local commit `ff09d6d` (committed 2026-09-10 11:06:23 UTC).
- **2026-09-07** — D1 weekend-bar purge + writer guard (apparatus repair, pre-existing defect). Commit `94f5b59`.

---

## §1 — GRADER OUTPUT, ALL FOUR DAYS

Command: `python3 scripts/qm_join_grade.py YYYY-MM-DD` (grader unchanged since `fb1c12e`; pip-conversion is 1.0 per manifest §Grading Definitions).

### 2026-09-07 (Monday)

```
========================================================================
REPORT A — CLASSIFIER / QUADRANT TABLE (2026-09-07) — floor=7
========================================================================

--- V1 FIRES (real P&L) (n=5) ---
                      GOOD       BAD     TOTAL
V2 KEEP                  0         0         0
V2 REFUSE                1         4         5
V2 NO_STATE              0         0         0
keep precision: - | refuse precision (bad-avoided): 80.0%
full-context   KEEP 0G/0B  REFUSE 0G/0B
degraded-ctx   KEEP 0G/0B  REFUSE 1G/4B

--- V1 BLOCKS (hypothetical MFE/MAE 36-bar) (n=16) ---
                      GOOD       BAD     TOTAL
V2 KEEP                  0         1         1
V2 REFUSE                1        12        13
V2 NO_STATE              2         0         2
keep precision: 0.0% | refuse precision (bad-avoided): 92.3%

--- V1 SILENT / V2 LOUD (hypothetical MFE/MAE 36-bar) (n=2) ---
                      GOOD       BAD     TOTAL
V2 KEEP                  1         1         2
V2 REFUSE                0         0         0
V2 NO_STATE              0         0         0
keep precision: 50.0% | refuse precision (bad-avoided): -

========================================================================
REPORT B — COMMERCIAL SCOREBOARD (2026-09-07) — V1 FIRES ONLY
========================================================================
metric                           ALL-V1        V2-KEPT
------------------------------------------------------
trades/day                            5              0
net pips                          +22.5           +0.0
win rate                          60.0%              -
expectancy/trade                  +4.50          +0.00
MFE median                          6.5              -
MAE median                          2.5              -
>=25p winners                         0              0
>=35p winners                         0              0
peak simultaneous                     2              0
peak capital £                       80              0
pips / £ peak-cap                 0.281              -

========================================================================
REPORT C — PER-SOURCE-ENGINE (2026-09-07)
========================================================================
engine                  picks   GOOD    BAD   hit-rate   net(pips)
------------------------------------------------------------------
V1_FIRE_JOIN               21      4     17      19.0%       +22.5
V2_VELOCITY_ONLY            1      0      1       0.0%        +0.0
V2_SLOW_REJECTION           0      0      0          -        +0.0
CONTINUATION                2      1      0     100.0%        +0.0
UNKNOWN                     0      0      0          -        +0.0

========================================================================
REPORT D — PER-REFUSAL COUNTERFACTUAL (2026-09-07)
========================================================================
guard             picks   GOOD    BAD  TIMEOUT  avoided_bad  cost_good   net(pips)
----------------------------------------------------------------------------------
COHERENCE             6      0      0        6            0          0        +0.0
ENTRY_HOURS          10      3      1        6            1          3       +15.1
V2_SCORE              5      1      4        0            4          1       +22.5
GRIND_SCRATCH         0      0      0        0            0          0        +0.0
LABEL                 0      0      0        0            0          0        +0.0

DIAGNOSTICS: staleness_secs min=300.9 median=10801.5 p90=38404.0 max=43504.3 (n=21) |
score_mode: full=4 degraded=20 | census (candidates >= floor, actionable): v1_fire=0 v1_block=1 v1_silent=2 |
live join stamps: fire=12 block=16 v2_only=4 v2_classified=0 | join failures: 0
```

### 2026-09-08 (Tuesday)

```
--- V1 FIRES (real P&L) (n=5) ---
                      GOOD       BAD     TOTAL
V2 KEEP                  0         2         2
V2 REFUSE                0         3         3
V2 NO_STATE              0         0         0
keep precision: 0.0% | refuse precision (bad-avoided): 100.0%

--- V1 BLOCKS (n=12) ---   KEEP 1G/0B  REFUSE 3G/6B  NO_STATE 1G/1B  (keep prec 100% | refuse-prec 66.7%)
--- V1 SILENT (n=3)  ---   KEEP 1G/2B                                (keep prec 33.3%)

REPORT B — COMMERCIAL SCOREBOARD (2026-09-08) — V1 FIRES ONLY
metric                           ALL-V1        V2-KEPT
------------------------------------------------------
trades/day                            5              2
net pips                          -39.8           -2.7
win rate                          20.0%          50.0%
expectancy/trade                  -7.96          -1.35
MFE median                          3.0            7.6
MAE median                         11.6           13.4
>=25p winners                         0              0
>=35p winners                         0              0
peak simultaneous                     1              1
peak capital £                       40             40
pips / £ peak-cap                -0.995         -0.068

REPORT C — PER-SOURCE-ENGINE
engine                  picks   GOOD    BAD   hit-rate   net(pips)
V1_FIRE_JOIN               17      5     12      29.4%       -39.8
V2_VELOCITY_ONLY            1      1      0     100.0%        +0.0
V2_SLOW_REJECTION           0      0      0          -        +0.0
CONTINUATION                3      0      2       0.0%        +0.0

REPORT D — PER-REFUSAL COUNTERFACTUAL
guard             picks   GOOD    BAD  TIMEOUT  avoided_bad  cost_good   net(pips)
ENTRY_HOURS          12      5      0        7            0          5       +58.2
V2_SCORE              3      0      3        0            3          0       -37.1

DIAGNOSTICS: staleness_secs min=301.1 median=602.8 p90=5107.6 max=7502.6 (n=17) |
score_mode: full=7 degraded=14 | census v1_fire=1 v1_block=0 v1_silent=3 |
live join stamps: fire=5 block=12 v2_only=13 v2_classified=8 | join failures: 0
```

### 2026-09-09 (Wednesday)

```
--- V1 FIRES (real P&L) (n=9) ---
                      GOOD       BAD     TOTAL
V2 KEEP                  0         1         1
V2 REFUSE                4         3         7
V2 NO_STATE              0         1         1
keep precision: 0.0% | refuse precision (bad-avoided): 42.9%

--- V1 BLOCKS (n=16) ---   REFUSE 11G/3B  NO_STATE 2G/0B   (refuse-prec 21.4%)
--- V1 SILENT (n=5)  ---   KEEP 3G/2B                     (keep prec 60.0%)

REPORT B — COMMERCIAL SCOREBOARD (2026-09-09) — V1 FIRES ONLY
metric                           ALL-V1        V2-KEPT
------------------------------------------------------
trades/day                            9              1
net pips                          +90.2           +0.1
win rate                          66.7%         100.0%
expectancy/trade                 +10.02          +0.10
MFE median                         14.3           14.7
MAE median                          6.7            5.0
>=25p winners                         2              0
>=35p winners                         1              0
peak simultaneous                     3              1
peak capital £                      120             40
pips / £ peak-cap                 0.752          0.003

REPORT C — PER-SOURCE-ENGINE
engine                  picks   GOOD    BAD   hit-rate   net(pips)
V1_FIRE_JOIN               25     17      8      68.0%       +90.2
V2_VELOCITY_ONLY            2      0      1       0.0%        +0.0
V2_SLOW_REJECTION           0      0      0          -        +0.0
CONTINUATION                4      3      1      75.0%        +0.0

REPORT D — PER-REFUSAL COUNTERFACTUAL
guard             picks   GOOD    BAD  TIMEOUT  avoided_bad  cost_good   net(pips)
ENTRY_HOURS          16     13      2        1            2         13      +104.4
V2_SCORE              7      4      3        0            3          4       +87.9

DIAGNOSTICS: staleness_secs min=301.0 median=901.5 p90=653300.7 max=653300.7 (n=23) |
score_mode: full=7 degraded=24 | census v1_fire=0 v1_block=1 v1_silent=5 |
live join stamps: fire=9 block=16 v2_only=16 v2_classified=3 | join failures: 0
```

### 2026-09-10 (Thursday, close-of-window)

```
--- V1 FIRES (real P&L) (n=7) ---
                      GOOD       BAD     TOTAL
V2 KEEP                  0         0         0
V2 REFUSE                1         6         7
V2 NO_STATE              0         0         0
keep precision: - | refuse precision (bad-avoided): 85.7%

--- V1 BLOCKS (n=5)  ---   KEEP 1G/0B  REFUSE 0G/3B  NO_STATE 1G/0B  (keep prec 100% | refuse-prec 100%)
--- V1 SILENT (n=8)  ---   KEEP 3G/5B                                 (keep prec 37.5%)

REPORT B — COMMERCIAL SCOREBOARD (2026-09-10) — V1 FIRES ONLY
metric                           ALL-V1        V2-KEPT
------------------------------------------------------
trades/day                            7              0
net pips                           -0.4           +0.0
win rate                          14.3%              -
expectancy/trade                  -0.06          +0.00
MFE median                          4.0              -
MAE median                          6.8              -
>=25p winners                         1              0
>=35p winners                         1              0
peak simultaneous                     3              0
peak capital £                      120              0
pips / £ peak-cap                -0.003              -

REPORT C — PER-SOURCE-ENGINE
engine                  picks   GOOD    BAD   hit-rate   net(pips)
V1_FIRE_JOIN               12      3      9      25.0%        -0.4
V2_VELOCITY_ONLY            3      1      2      33.3%        +0.0
V2_SLOW_REJECTION           0      0      0          -        +0.0
CONTINUATION                5      2      3      40.0%        +0.0

REPORT D — PER-REFUSAL COUNTERFACTUAL
guard             picks   GOOD    BAD  TIMEOUT  avoided_bad  cost_good   net(pips)
COHERENCE             4      2      1        1            1          2        +5.2
ENTRY_HOURS           1      0      0        1            0          0        +0.0
V2_SCORE              7      1      6        0            6          1        -0.4

DIAGNOSTICS: staleness_secs min=301.7 median=1203.0 p90=14111.5 max=20401.5 (n=12) |
score_mode: full=9 degraded=11 | census v1_fire=0 v1_block=0 v1_silent=8 |
live join stamps: fire=17 block=5 v2_only=13 v2_classified=3 | join failures: 0
```

### 4-day aggregate — ALL-V1 vs V2-KEPT (commercial line)

Source: each day's REPORT B stacked. Peak simultaneous & capital reconstructed from `logs/signal_log.jsonl` `timestamp_open` / `timestamp_close` intervals (25/26 trades have `timestamp_close`; the one without falls back to +3h assumed hold — noted as a small caveat).

| metric              |  ALL-V1  |  V2-KEPT  |
|---------------------|---------:|----------:|
| trades              |     26   |      3    |
| net pips            |   +72.5  |    −2.6   |
| win rate            |  42.3%   |   66.7%   |
| expectancy / trade  |   +2.79  |   −0.87   |
| ≥25p winners        |      3   |      0    |
| ≥35p winners        |      2   |      0    |
| peak simultaneous   |      3   |      1    |
| peak capital £      |    120   |     40    |
| pips / £ peak-cap   |   0.604  |  −0.065   |

ALL-V1 wins: 3 (07) + 1 (08) + 6 (09) + 1 (10) = 11 / 26.
V2-KEPT trades: 09-08 SELL 09:50 (+4.5), 09-08 BUY 14:20 (−7.2), 09-09 BUY 15:30 (+0.1) → 3 total, net −2.6.

---

## §2 — REAL P&L CROSS-CHECK (`logs/signal_log.jsonl`)

Method: sum of `pnl_pips + runner_pnl_pips` per row, per UTC date (bank+runner convention, per `qm_join_grade.py:519-522` `grade_fire` docstring).

| day        | n | net (pips) | wins (≥+10p) |
|-----------|--:|-----------:|-------------:|
| 2026-09-07 | 5 |     +22.50 | 3            |
| 2026-09-08 | 5 |     −39.80 | 1            |
| 2026-09-09 | 9 |     +90.20 | 6            |
| 2026-09-10 | 7 |      −0.40 | 1            |
| **total**  |**26**|   **+72.50**|**11**     |

**Divergence from grader**: NONE. Every ALL-V1 net-pips figure in the four Report B tables matches the sum here to the pip. Fire-count matches too. The grader is reading the same field.

Row-level ALL-V1 fires (from `signal_log.jsonl`):

```
2026-09-07T07:05:02Z GBPUSD BUY  GBPUSD_TREND_V3_L       7.9+7.9   =+15.8
2026-09-07T12:10:01Z GBPUSD BUY  GBPUSD_BB_BOUNCE_L      6.7+0.0   =+6.7
2026-09-07T12:25:01Z GBPUSD BUY  GBPUSD_TREND_V3_UM_L    2.3+0.0   =+2.3
2026-09-07T14:15:02Z GBPUSD BUY  GBPUSD_TREND_V3_UM_L   -1.2+0.0   =-1.2
2026-09-07T16:30:01Z GBPUSD BUY  GBPUSD_TREND_V3_UM_L   -1.1+0.0   =-1.1
2026-09-08T08:05:01Z GBPUSD BUY  GBPUSD_BB_BOUNCE_L     -6.2+0.0   =-6.2
2026-09-08T09:50:02Z GBPUSD SELL GBPUSD_BB_BOUNCE_S      4.5+0.0   =+4.5
2026-09-08T11:45:04Z GBPUSD SELL GBPUSD_BB_BOUNCE_S    -19.65+0.0  =-19.65
2026-09-08T13:25:02Z GBPUSD BUY  GBPUSD_TREND_V3_L    -11.25+0.0   =-11.25
2026-09-08T14:20:07Z GBPUSD BUY  GBPUSD_BB_BOUNCE_L     -7.2+0.0   =-7.2
2026-09-09T07:25:01Z GBPUSD SELL GBPUSD_LEVEL_BOUNCE_S  -0.8+0.0   =-0.8
2026-09-09T08:15:09Z GBPUSD BUY  GBPUSD_BB_BOUNCE_L     10.7+0.0   =+10.7
2026-09-09T09:52:55Z GBPUSD BUY  BRIEFING_V5          21.85+21.85  =+43.7
2026-09-09T09:57:35Z EURUSD BUY  BRIEFING_V5          14.4+14.4    =+28.8
2026-09-09T11:40:04Z GBPUSD SELL GBPUSD_BB_BOUNCE_S    13.9+0.0    =+13.9
2026-09-09T11:45:02Z GBPUSD SELL GBPUSD_LEVEL_BOUNCE_S -3.4+0.0    =-3.4
2026-09-09T14:25:01Z GBPUSD SELL GBPUSD_LEVEL_BOUNCE_S -5.0+0.0    =-5.0
2026-09-09T15:11:23Z EURUSD BUY  BRIEFING_V5           1.1+1.1     =+2.2
2026-09-09T15:30:04Z GBPUSD BUY  GBPUSD_BB_BOUNCE_L    0.1+0.0     =+0.1
2026-09-10T07:15:11Z GBPUSD BUY  GBPUSD_BB_BOUNCE_L         -20.0+0.0    =-20.0
2026-09-10T08:20:01Z GBPUSD BUY  GBPUSD_CONFIRMATION_FALLBACK_L -10.5+0.0 =-10.5
2026-09-10T09:00:01Z GBPUSD BUY  GBPUSD_TREND_V3_UM_L        -5.9+0.0    =-5.9
2026-09-10T10:31:24Z EURUSD BUY  BRIEFING_V5                -13.2+0.0    =-13.2
2026-09-10T11:10:02Z GBPUSD SELL GBPUSD_TREND_V3_S       25.45+25.45     =+50.9
2026-09-10T15:00:03Z GBPUSD SELL GBPUSD_TREND_V3_S         -1.7+0.0      =-1.7
2026-09-10T15:30:03Z GBPUSD SELL GBPUSD_BB_BOUNCE_S         0.0+0.0      =+0.0
```

---

## §3 — PICKS LEDGER (`logs/qm_pick_alerts_seen.jsonl` — every alert actually dispatched in the window)

Method: every seen-jsonl row whose `date` (or `alerted_at[:10]`) is in 09-07..10. Entry is the pick's `zone_key` (limit-fill assumption, matching v1_silent grader convention); MFE/MAE over the 36 five-min bars STRICTLY AFTER `opened_at` from `data/candles/{PAIR}/{DATE}.csv`, using the manifest counting convention (GOOD = +10p favourable before −20p adverse; TIMEOUT = neither hit inside 36 bars; RIGHT/WRONG/FLAT map GOOD/BAD/TIMEOUT).

Two persistence-schema notes (from the freeze changelog, amendment #2): `score`, `family`, `source_engine` were added to the seen jsonl on 2026-09-10. Rows written before that commit have `family` set (from amendment #1) but lack `score`; the older rows here (09-07..08) render as `family=continuation` (migration default). `session` and `zone_key` were always present.

```
alerted_at                       opened_at                 pair    zone     dir  fam           out       mfe   mae
2026-09-07T08:40:00.428832Z      2026-09-07T08:35:00Z      GBPUSD  13533.7  BUY  continuation  RIGHT   10.75  -2.35
2026-09-07T08:40:00.520697Z      2026-09-07T07:55:00Z      EURUSD  11632.9  SELL continuation  RIGHT   11.10   0.00
2026-09-07T10:20:00.719207Z      2026-09-07T10:15:00Z      GBPUSD  13526.2  BUY  continuation  RIGHT   12.95   0.00
2026-09-08T06:00:00.647207Z      2026-09-08T05:55:00Z      GBPUSD  13544.6  SELL continuation  RIGHT   11.35  -8.05
2026-09-08T11:20:00.613936Z      2026-09-08T07:20:00Z      GBPUSD  13528.1  BUY  continuation  RIGHT   10.05   0.00   ← stale-freshness pick #2 (pre-amend#2)
2026-09-08T11:45:00.486146Z      2026-09-08T11:40:00Z      EURUSD  11621.9  SELL continuation  RIGHT   10.60   0.00
2026-09-08T12:00:00.936839Z      2026-09-08T11:55:00Z      GBPUSD  13544.6  BUY  continuation  RIGHT   10.35  -2.65
2026-09-08T13:30:00.533761Z      2026-09-08T13:25:00Z      GBPUSD  13551.6  BUY  continuation  FLAT     5.35 -18.75
2026-09-08T15:35:00.584000Z      2026-09-08T15:30:00Z      GBPUSD  13551.6  SELL continuation  RIGHT   10.85   0.00
2026-09-08T18:50:00.553290Z      2026-09-08T18:45:00Z      EURUSD  11621.9  BUY  continuation  FLAT     8.20   0.00
2026-09-09T04:16:05Z             2026-09-09T04:16:05Z      GBPUSD  13499.8  BUY  rejection     RIGHT   47.95   0.00
2026-09-09T06:20:04Z             2026-09-09T06:15:00Z      GBPUSD  13562.0  BUY  rejection     WRONG    6.35 -21.15
2026-09-09T07:25:00Z             2026-09-09T07:20:00Z      EURUSD  11635.5  BUY  continuation  RIGHT   13.80   0.00
2026-09-09T08:05:01Z             2026-09-09T08:00:00Z      GBPUSD  13562.0  SELL continuation  RIGHT   15.75   0.00
2026-09-09T11:20:00Z             2026-09-09T11:15:00Z      EURUSD  11638.3  SELL continuation  FLAT     1.00 -15.90
2026-09-09T11:25:00Z             2026-09-09T11:20:00Z      GBPUSD  13561.3  SELL continuation  RIGHT   11.55  -5.15
2026-09-09T11:55:00Z             2026-09-09T11:50:00Z      GBPUSD  13561.3  SELL rejection     RIGHT   11.55  -5.15
2026-09-09T14:25:00Z             2026-09-09T14:20:00Z      EURUSD  11638.3  BUY  continuation  RIGHT   10.20   0.00
2026-09-09T15:05:00Z             2026-09-09T15:00:00Z      GBPUSD  13541.3  BUY  continuation  RIGHT   13.95  -7.05
2026-09-09T15:25:00Z             2026-09-09T15:00:00Z      GBPUSD  13541.3  SELL rejection     FLAT     7.05 -19.65
2026-09-10T07:05:00Z             2026-09-10T07:00:00Z      GBPUSD  13549.7  BUY  continuation  FLAT     8.35  -7.95
2026-09-10T08:15:09Z             2026-09-09T23:55:00Z      EURUSD  11636.4  SELL rejection     NO_DATA  —     —     ← opened_at prior day; entry-bar past window
2026-09-10T10:30:00Z             2026-09-10T03:00:00Z      GBPUSD  13549.7  SELL rejection     FLAT     0.00  -9.85 ← 7.5h stale (pre-amend#2 live at emit; commit landed 11:06Z)
2026-09-10T12:00:00Z             2026-09-10T11:55:00Z      EURUSD  11618.6  SELL rejection     RIGHT   20.90  -8.65
2026-09-10T12:30:01Z             2026-09-10T12:25:00Z      GBPUSD  13530.5  SELL continuation  RIGHT   27.25   0.00
2026-09-10T12:35:01Z             2026-09-10T12:30:00Z      GBPUSD  13511.8  SELL rejection     RIGHT   19.55   0.00
2026-09-10T13:45:04Z             2026-09-10T13:40:00Z      EURUSD  11620.4  SELL continuation  FLAT     9.60 -10.90
2026-09-10T13:45:05Z             2026-09-10T13:40:00Z      EURUSD  11602.6  BUY  continuation  RIGHT   16.20   0.00
2026-09-10T14:05:00Z             2026-09-10T14:00:00Z      GBPUSD  13511.8  BUY  continuation  RIGHT   10.75   0.00
2026-09-10T14:35:00Z             2026-09-10T14:30:00Z      EURUSD  11618.6  BUY  continuation  RIGHT   10.50   0.00
```

Family-split accuracy (per-family RIGHT / (RIGHT+WRONG), excluding FLAT and NO_DATA):

| family        | RIGHT | WRONG | FLAT | NO_DATA | accuracy |
|---------------|------:|------:|-----:|--------:|---------:|
| continuation  |   17  |   0   |   5  |    0    |  100.0%  |
| rejection     |    4  |   1   |   2  |    1    |   80.0%  |
| **all picks** | **21**| **1** | **7**| **1**   | **95.5%** |

Score per pick is not printed above because `score` was only added to `qm_pick_alerts_seen.jsonl` at 2026-09-10 11:06:23 UTC (amendment #2, commit `ff09d6d`). Every row in this window pre-dates that persistence change → the `score` field is not present. This is a real observability gap the amendment fixes prospectively but cannot backfill. (Gap.)

`logs/qm_pick_collisions.jsonl` — the collision ledger amendment #2 introduces — does NOT exist on disk (nothing was collision-muted after the commit landed).

---

## §4 — THE TWO THURSDAY OPERATOR CLAIMS

### (a) The downtrend leg

Source: `data/candles/GBPUSD/2026-09-10.csv` (all times UTC; BST = UTC+1).

- Day high: **13560.45** at **02:00 UTC** (03:00 BST) — Asia.
- Session (07-17 UTC) high: **13558.05** at **09:00 UTC** (10:00 BST).
- Session (07-17 UTC) low: **13491.15** at **12:40 UTC** (13:40 BST).
- Session leg pips: **66.9** over ≈3 h 40 min.
- Sharp-leg segment (12:00 → 12:40 UTC): from ~13530 down to 13491 = ~39 pips in 40 min; the terminating bar **12:30 UTC** printed range 13529.5 → 13503.25 (26.25p in a single 5m bar).

Live-roster response (`logs/signal_log.jsonl`, ALL-V1 fires):

- **11:10 UTC (12:10 BST) — `GBPUSD_TREND_V3_S SELL` — closed +50.9p** (bank 25.45 + runner 25.45; close reason `BE_STOP_POST_SCALEOUT` from journalctl 12:46:24Z).
- 15:00 UTC — `GBPUSD_TREND_V3_S SELL` — closed −1.7p (post-bounce, late re-entry).
- 15:30 UTC — `GBPUSD_BB_BOUNCE_S SELL` — closed 0.0p (bar 3 the runner would have caught was already past).

Plainly: **YES, the leg was captured** — `GBPUSD_TREND_V3_S` at 11:10 UTC took +50.9 pips real P&L. This single trade is the only reason Thursday's ALL-V1 line reads −0.4 instead of a large loser day; the four preceding BUY trades (07:15, 08:20, 09:00, 10:31) collectively lost −49.6 pips leaning the wrong way into the leg's build-up.

### (b) The ~13:45 BST bottom bounce (=12:45 UTC)

Bounce measurement (candles):
- Low: **13491.15 at 12:40 UTC** (13:40 BST).
- 36-bar MFE off that low: **+42.9 pips** (high 13534.05 at 15:10 UTC).

V2 layer, bar-by-bar for zone 13511.8 (the pierce zone at the bottom of the leg), from `logs/qm_candidates.jsonl`:

```
opened_at 2026-09-10T12:15  APPROACHING_ZONE (behaviour=APPROACHING)
opened_at 2026-09-10T12:30  IDLE → EXTREME_REACHED → SWEEP_DETECTED → REJECTION_CANDIDATE
                             → REJECTION_CONFIRMED (velocity_rejection_score=12 side=above)
                             → ENTRY_ARMED (direction=SELL_from_rejection_geometry)
opened_at 2026-09-10T14:00  REVERSAL_CANDIDATE (s16_retest_S2_from_above_wick=2.33p)  ← the BUY spawn
```

Alerts actually dispatched at this zone during the window (`qm_pick_alerts_seen.jsonl`):
- **12:35 UTC** — SELL 13511.8 (rejection family, score-persisted post-amendment absent) → 36-bar outcome RIGHT (+19.55p, caught the tail of the leg down).
- **14:05 UTC** — BUY 13511.8 (continuation via §16) → RIGHT (+10.75p).

**No BUY pick was emitted at or near 12:45 UTC** (the "13:45 BST bounce" moment). The gap between the low (12:40 UTC) and the eventual BUY arm (14:00 UTC via §16) is 1h 20min.

**Blocking mechanism — the ENTRY_ARMED occupancy caused by the TTL exemption.**

The state-machine loop in `on_5m_close_sde` maintains **one live candidate per symbol** in `_SDE_CANDIDATES[sym]` (`qm_decision_shadow.py:2263-2264`). Same-zone continuation routes through `_maybe_expire_candidate` (`qm_decision_shadow.py:2189`), which enforces the TTL. That function is guarded verbatim:

```python
def _maybe_expire_candidate(cand: Candidate, ts: str,
                              cur_close: float) -> bool:
    """… QM_CAND_TTL_BARS bars without progressing, or if the current
    close has drifted more than QM_CAND_MAX_DIST_PIPS from its
    zone_center. …"""
    try:
        if cand.state not in (CAND_REVERSAL_CANDIDATE,
                              CAND_REJECTION_CONFIRMED):
            return False
        ttl = _env_int("QM_CAND_TTL_BARS", 12)
        …
```
(`qm_decision_shadow.py:627-640`)

**ENTRY_ARMED is not in that eligible set.** An ENTRY_ARMED candidate is exempt from both TTL and distance expiry. So the SELL armed at 12:30 UTC on zone 13511.8 stayed ENTRY_ARMED indefinitely, occupying the symbol's single candidate slot. The main state machine could not spawn a fresh BUY-side candidate at the same zone until it was displaced by the §16 detector's independent spawn (`_detect_and_spawn_retest_reversal` §16, `qm_decision_shadow.py:2087`), which finally fired at **14:00 UTC** when price wicked back **from above** onto the S2 pivot (`s16_retest_S2_from_above_wick=2.33p`).

Bottom line: no live pick captured the operator-confirmed moment. The engine was correct to fade DOWN from above (SELL was the right rejection call at 12:30), and then required a role-reversal retest event 1h 20min later before it would rearm the opposite direction. The ~13:45 BST bounce came out of on-disk evidence as **detected but silenced by ENTRY_ARMED occupancy** for the intervening 1h 20min.

---

## §5 — DEFECT LEDGER (window 2026-09-07 → 2026-09-10)

Each row is a defect surfaced during or before the exam, with its discovery source and status. Fix commits verified via `git log`; UNFIXED items verified against current HEAD source.

| # | defect | discovery | fix commit | status |
|---|---|---|---|---|
| 1 | **Sunday D1 bars leaking through weekend guard** — `htf_cache._drop_weekend_labelled_d1` rejected only Saturday; watchdog re-persisted the phantom Sunday D1 after Monday restart; 22 prior Sundays affected. | Sunday apparatus session, 2026-09-06/07 | `94f5b59 fix(exam-freeze): D1 weekend-bar purge + writer guard` (2026-09-07 11:15:49Z) | **FIXED pre-exam-open**. Verified: cache backups `.pre_weekend_purge_20260907T110839Z` present per changelog. |
| 2 | **Dedup family key too coarse** — zone-day dedup silenced rejection-family picks that arrived after a same-zone continuation earlier the day; the census showed 3/6 rejection candidates ≥ floor were mis-suppressed. | `reports-public/rejection_family_census_20260907_08.md` | `089a547 amend(exam): dedup family key + rejection-family base parity (12)` (2026-09-09 04:19:47Z) | **FIXED mid-week (amendment #1)**. New key `(round(zone,1), side, UTC-date, family)`; `family∈{continuation, rejection}`. Legacy rows migrate as `continuation`. |
| 3 | **Rejection-family scoring parity handicap** — rejection-family base = 10 vs §16-retest = 12, a structural 2-point gap that stopped rejection picks from clearing floor 7 on par with continuation. | Same census as (2) | `089a547` (same commit) | **FIXED mid-week (amendment #1)**. New signal `rejection_family_parity: 2` in `_REJECTION_WEIGHTS`; helper `_is_rejection_family_stamp` excludes §16-retest. |
| 4 | **Freshness-guard leak (pick #2 specimen)** — `maybe_send_pick_alert` used last-transition ts, so a 4h-old candidate that transitioned at 11:15 dispatched at 11:20 as "fresh". Two picks visible in-window: 09-08 11:20:00 (opened 07:20 = 4h), 09-10 10:30:00 (opened 03:00 = 7.5h), 09-10 08:15:09 (opened 09-09 23:55 = 8h 20min). | `reports-public/pick_direction_audit_2026-09-08_09.md` | `ff09d6d amend(exam) #2` (2026-09-10 11:06:23Z) — `_originating_bar_ts` now returns `cand.opened_at` only. | **FIXED mid-week (amendment #2)**, but the commit landed at 11:06:23Z Thursday. The three visible leaks all pre-date that timestamp. Post-commit dispatches on 09-10 (12:00, 12:30, 12:35, 13:45×2, 14:05, 14:35) — cannot be verified from disk alone whether the running process had been restarted to pick up the amendment (gap: no process-restart timestamp on file). |
| 5 | **Same-bar opposite-direction pick collision** — F3 collision class reaching the phone via per-family dedup cells (#16/#17 in the audit). | Same as (4) | `ff09d6d` — `QM_PICK_COLLISION_MUTE=1` buffer + flush, logs to `qm_pick_collisions.jsonl`. | **FIXED mid-week (amendment #2)**. No collision-ledger rows on disk → nothing was muted after commit landed; cannot verify the mute path executed in-window from evidence alone (gap). |
| 6 | **Score / family / source_engine not persisted in `qm_pick_alerts_seen.jsonl`** — audit could not report per-pick score because the field never persisted. | Same as (4) | `ff09d6d` — additive schema in `_persist_seen`; legacy rows still load. | **FIXED mid-week (amendment #2)**. Every pick in this window pre-dates the commit → no `score` recoverable for §3 above. Audit gap acknowledged. |
| 7 | **ENTRY_ARMED TTL exemption** — `_maybe_expire_candidate` guards TTL to REVERSAL_CANDIDATE / REJECTION_CONFIRMED only (`qm_decision_shadow.py:637-639`, quoted §4b). An ENTRY_ARMED candidate never expires and occupies the symbol's single candidate slot indefinitely, blocking opposite-side rearm on the same zone. Manifests as the ~13:45 BST bounce silence today. | This report, from `qm_candidates.jsonl` reconstruction of 13511.8 zone on 09-10. | (none) | **UNFIXED at HEAD `ff09d6d`.** Not addressed by the mid-week amendments (correctly — the freeze rule forbids "approach-context fix after an ugly velocity trade"; this is exactly that shape). |
| 8 | **IG broker BE-amend rejection** (`ATTACHED_ORDER_LEVEL_ERROR`) — GBPUSD_TREND_V3_S at 12:05:00Z on 09-10, three consecutive `SL amend NOT ACCEPTED` responses (dealReferences `H78A636L7UYTYRZ`, `Q5F99RK8MLLTYRZ`, `PL9EYQMNH4CTYRZ`), backoff tier 1 engaged, `[BE_RECOVER] BE re-amend FAILED — structure_exit remains active as -10p safety net`. Trade eventually closed BE_STOP_POST_SCALEOUT +25.45 bank (total +50.9 with runner). Discovery source: `journalctl -u autobot -S 2026-09-10 …`. | Live logs (this report). | (none) | **UNFIXED at HEAD.** Safety net worked (banked runner) but the amend path is fragile against `ATTACHED_ORDER_LEVEL_ERROR`; the recovery path silently drops to `structure_exit` and mutes bb_bounce trail. |
| 9 | **Thesis-line inconsistency** — GBPUSD thesis on 09-10 went `SEED_PRIOR BUY strength=2` (05:44) → `REINFORCED BUY strength=3` (07:05) → `HEARTBEAT NONE strength=0 since=2026-09-10T05:44:20` (10:30). The `since_ts` was retained on the NONE state; `render_line` masks this in the pick alert body ("Thesis: none") but the jsonl stream shows a NONE state that names a since-ts. Also observed: the running process had no morning-briefing → qm_thesis seed wire until the working-tree diff (uncommitted at HEAD: `morning_briefing.py`, `qm_hooks.py`, `qm_thesis.py`) added `_seed_qm_thesis` at briefing load, a public `seed_from_briefing_dict` alias, and a 5m-close `heartbeat` driver in `qm_hooks._on_5m_close`. | This report, from `logs/qm_thesis.jsonl` and `git diff`. | (uncommitted working tree) | **PARTIALLY FIXED post-window in the working tree; NOT committed / NOT deployed during exam.** Verify with `git diff qm_thesis.py qm_hooks.py morning_briefing.py`. |
| 10 | **Grader staleness p90 = 653,300s (7.5 days) on 09-09** — Report A DIAGNOSTICS line: `staleness_secs: min=301.0 median=901.5 p90=653300.7 max=653300.7 (n=23)`. Indicates at least one V1 event was joined against a V2 stamp reconstructed from a candidate whose last-observed transition was ~7.5 days old — either a stale-cache leak in the reconstruct path or a truly ancient dormant candidate. | This report, grader diagnostics 09-09. | (none) | **UNFIXED at HEAD.** No accompanying grader assertion — could be legitimate (a long-dormant zone finally sweeping); flag as needs-investigation, not proven-broken. |

---

## §6 — VERDICT

Against the operator's stated exam criteria (freeze manifest §Freeze RULES + the 2026-09-05 standard: "live bounce picks at operator-confirmed moments by Thu close"):

| criterion | evidence | verdict |
|---|---|---|
| **A. Freeze integrity (no scoring/floor/geometry/template changes mid-week).** | Manifest §Freeze RULES §3 QM_JOIN_FLOOR=7 unchanged (grader header `floor=7` all four days). §5 QM_LIVE_FIRE remains absent (grep `.env` shows no key). Amendments #1 (`089a547`) and #2 (`ff09d6d`) are ruled scoring-parity + apparatus repairs — the manifest changelog acknowledges them and the manifest states "any change during the exam voids the exam" while also documenting these as operator-ruled. | **PASS on formal freeze rules 1–5 (no velocity fix, no adjacent-bar mute, no floor change, no reclassification, no LIVE-FIRE flip)**. The two amendments touched dedup, base-score parity, freshness, collisions and persistence — no touching of §V velocity classifier, no floor change, no template. The operator ruled them in and the manifest was amended before landing. |
| **B. Live capture of the Thursday downtrend leg.** | GBPUSD 07-17 UTC session leg −66.9p; GBPUSD_TREND_V3_S SELL fired 11:10 UTC, banked +25.45 + runner +25.45 = +50.9p (76% of the session leg). | **PASS** — the leg was captured by the live roster. The four preceding BUY fires (07:15, 08:20, 09:00, 10:31 UTC, cumulative −49.6p) cost most of that back on the same day; the day still ended −0.4p ALL-V1. |
| **C. Live pick at the operator-confirmed ~13:45 BST bounce moment.** | Bounce measured: low 13491.15 at 12:40 UTC, 36-bar MFE +42.9p. No BUY pick emitted at or near 12:45 UTC on GBPUSD. First BUY pick at zone 13511.8 came at 14:05 UTC (+80 min late), caught only +10.75p MFE. Mechanism: ENTRY_ARMED occupancy of the zone by the earlier SELL, exempt from `_maybe_expire_candidate`'s TTL (`qm_decision_shadow.py:637-639`). §16 role-reversal detector eventually broke through at 14:00 UTC. | **FAIL** — the engine had the correct SELL fade at 12:30 UTC on the pierce, and then went silent on the same zone for 1h 20min while the bounce ran. The 09-05 standard was live BUY picks at operator-confirmed bounces; the on-disk timing shows an 80-minute delay attributable to a documented UNFIXED code path (defect #7). |
| **D. Selection precision on the picks that WERE sent.** | Family-split accuracy 100% (17/17) continuation, 80% (4/5) rejection, 95.5% overall on 22 decisive picks (§3). Refuse-precision (guards doing their job): 92.3% on Monday V1 blocks, 66.7% on Tuesday, 21.4% on Wednesday (many good trades were refused; guard cost 13 GOOD trades that day), 100% on Thursday V1 blocks. | **PASS on picks precision** (once emitted, they were right ~95%). **MIXED on refuse-precision** — one bad Wednesday (guards over-refused; cost 13 GOOD). |
| **E. Commercial line for the window.** | ALL-V1: +72.5 pips / 26 trades / 42.3% WR / 0.60 pips-per-£-peak-capital. V2-KEPT: −2.6 / 3 trades. Peak simul 3, peak £120. | The book made money in the window, driven overwhelmingly by 09-09 (+90.2p) and the single Thursday winner (+50.9p). V2-KEPT would have been slightly negative had it gated live — because V2 preferred continuation-family setups on days the engine was already in shape to fade. **No PASS/FAIL — informational**. |
| **F. Guard operational integrity.** | ENTRY_HOURS refused 39 candidates in the window (10+12+16+1) with clean disposition. COHERENCE 10 refusals. V2_SCORE (shadow) refused 22 fires. `qm_join_grade.py` reports `join failures: 0` on every day. | **PASS** — refusal instrumentation intact, no join failures. |
| **G. Apparatus & disclosure.** | The four defect-ledger items fixed mid-week are all disclosed in the manifest changelog (dedup, parity, freshness, collision, persistence). The uncommitted thesis/heartbeat working-tree changes are NOT in HEAD and NOT deployed for the exam window; disclosed here. IG BE-amend rejection (defect #8) and ENTRY_ARMED TTL exemption (defect #7) are new findings from this report. | **PASS on disclosure**; **FAIL on complete pre-exam surface** — two defects (#7, #8) had to be surfaced by this post-exam report. |

**Overall**: PASS on freeze integrity, refusal instrumentation, and the picks that got out. FAIL on the load-bearing criterion of catching the Thursday bounce live — the engine's own zone occupancy blocked its own opposite-side detector for 80 minutes, and the fix required the §16 role-reversal detector (which fired late and small). Commercial line +72.5p over 4 days is only tenuously in the black because the single 09-09 win-cluster and one Thursday trend trade masked the Thursday BUY-heap and Tuesday's four losers.

---

## §7 — HONESTY NOTES

1. **Simulated exits**: only the manifest counting convention was applied (36 five-min bars, +10p GOOD before −20p BAD, next-bar entry, zone_center as entry for v1_silent / picks). No trailing-stop simulation, no scale-out simulation.
2. **Peak simultaneous / peak £ / pips-per-£ across the 4-day aggregate**: reconstructed from `signal_log.jsonl` open/close intervals; 25 of 26 rows have `timestamp_close`, one lacks it and defaulted to a +3h assumed hold. The value 3 is unchanged if that one trade is dropped.
3. **Pick score field for the §3 ledger**: not persisted for any of the 30 picks in the window. The `score` column would have required amendment #2's `_persist_seen` change, which lands 2026-09-10 11:06:23Z (after every pre-Thursday alert and possibly before some Thursday alerts, depending on process-restart timing which I cannot verify from disk). Omitted rather than guessed. (Gap.)
4. **09-10 pick at 08:15:09Z opened 09-09 23:55:00Z**: `sim` returned `NO_DATA` because the pick's `opened_at` bar (23:55 the previous day) is not present in the 2026-09-10 candles file; entry-bar search fell off the day-file window. Recorded as NO_DATA rather than dropped. (Gap.)
5. **Post-`ff09d6d` amendment #2 activation**: whether the live process on 09-10 had restarted to load amendment #2 for the picks dispatched after 11:06Z (12:00, 12:30, 12:35, 13:45×2, 14:05, 14:35) cannot be inferred from on-disk logs alone — no reliable process-restart marker survived to file. Marked as a gap in defect #4.
6. **"Thesis-line inconsistency"**: interpreted as the qm_thesis stream state where `thesis=NONE` retains an old `since_ts`, and the pre-fix absence of a briefing → thesis seed wire. `render_line` masks the surface symptom in pick alerts. Working-tree diff shows the fix in flight but not committed → not deployed in the exam window.
7. **Everything else**: every number quoted has a file line-number or explicit source; grader outputs were `sed -n` printed from `/tmp/exam/g0{7..10}.txt` runs performed at report-generation time, HEAD `ff09d6d`.

*Report generated 2026-09-10 (post-close) on host 161 at HEAD `ff09d6dfa3be7dd92d090c5091a7397b277c6913`.*
