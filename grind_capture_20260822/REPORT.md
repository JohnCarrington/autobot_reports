# Grind Capture — TREND_BANDWALK + TREND_V3 Retune Analysis

**Date:** 2026-08-22
**Host:** AutoBotV1 (`/opt/tradingbot`).
**Investigate-only.** No code, no commits, no restarts.

**Target days (grind tape):**

| date | audit class | dominant close-excursion | notes |
|:---|:---|:---|:---|
| 2026-08-10 | BOUNCE (audit); operator-grind | +44.4 p up over 11.7 h | borderline; regime STRONG only 15 % of session |
| 2026-08-14 | BOUNCE (audit); operator-grind | +68.6 p up over 12.5 h | regime STRONG_TREND_UP held ~9.7 h |
| 2026-06-17 | GRIND_100 | −167.6 p down | Fed decision day |
| 2026-06-18 | GRIND_100 | −129.3 p down | BoE decision day |
| 2026-07-15 | GRIND_100 | +176.1 p up | US_PPI |
| 2026-07-29 | GRIND_DAY (not 100) | +102.1 p up | FOMC |

**Regime-log coverage:** `logs/regime_engine.jsonl` starts 2026-05-22.
The 5 audit GRIND_100 dates before that (01-05, 01-23, 04-07, 04-13,
04-30) cannot be regime-checked and are **excluded from Q1–Q3**.

---

## Q1 — What EMA_PULLBACK already banks on grind days

Reproducer: `q1_ema_pb_grind.py` → `q1_ema_pb_result.json`.

**Method.** Rerun the 5-gate arm walk (session / stack / fan / entry-bar
geometry / regime WIDE) per 5-min bar in the EMA_PB window
(06:00–17:00 UTC). Cross-reference actual fires from `signal_log.jsonl`.

**Limitation (stated up front).** The legacy `_detect` path
(`EMA_PB_PULLBACK_FIX_ENABLED=0`) has **no persistent per-bar decision
log** for downstream gates. I can report the aggregate downstream-kill
count (arms − fires) per day, but **not the per-gate breakdown** the
prompt asks for (news blackout / H1 direction / pullback-shape / ribbon
deferral). This is an infrastructure-observability limitation, not an
analytical dodge. It applies to every EMA_PB fire that entered
`_detect` and was rejected by any gate downstream of the 5 arm-critical
ones.

### 1.1  Arms vs fires vs downstream-kill

| day | arms | fires | downstream-killed | kill rate | banked (p) | capture vs dom_move |
|:---|--:|--:|--:|--:|--:|--:|
| 2026-08-10 | 36 | 2 | 34 |  **94 %** | −10.6 | −23.8 % vs +44.4p |
| 2026-08-14 | 52 | 0 | 52 | **100 %** |   0.0 |   0.0 % vs +68.6p |
| 2026-06-17 | 31 | 2 | 29 |  **94 %** |  −0.2 |  −0.1 % vs −167.6p |
| 2026-06-18 | 36 | 2 | 34 |  **94 %** |  +4.3 |  +3.4 % vs −129.3p |
| 2026-07-15 | 58 | 3 | 55 |  **95 %** | +33.9 | +19.3 % vs +176.1p |
| 2026-07-29 | 18 | 0 | 18 | **100 %** |   0.0 |   0.0 % vs +102.1p |
| **totals** | **231** | **9** | **222** | **96 %** | **+27.4 p** | **~4 % of +688 p offered** |

**Bottom line.** EMA_PULLBACK arms 231 times across 6 grind days; 9
fires reach the tape; total banked +27.4 p against +688 p of directional
dominant close-move offered. **Existing capture is under 4 % of the
grind.** The 96 % downstream kill rate is the actionable number — the
arm side is not the bottleneck.

### 1.2  Actual fires per day (raw signal_log rows)

**2026-08-10** — dom_move +44.4 p up:

| time UTC | strategy | dir | entry | pnl | outcome |
|:---|:---|:---|--:|--:|:---|
| 08:10:01 | EMA_PULLBACK_L | BUY | 13501.20 | **−10.8** | STRUCTURE_EXIT (structure_flip_down) |
| 14:30:02 | EMA_PULLBACK_L | BUY | 13518.60 | **+0.25** | Breakeven stop hit (IG server-side) |

Both LONG (correct direction), but structural-flip exit takes the first
one out at −10p just as the climb continues; second one BE's out just
1 h before the 14:45 peak of the move.

**2026-06-17** — dom_move −167.6 p down (FOMC):

| time UTC | strategy | dir | entry | pnl | outcome |
|:---|:---|:---|--:|--:|:---|
| 14:05:02 | EMA_PULLBACK_S | SELL | 13401.80 | +10.75 | External/manual close |
| 15:10:02 | EMA_PULLBACK_S | SELL | 13388.80 | −10.90 | STRUCTURE_EXIT (structure_flip_up) |

**2026-06-18** — dom_move −129.3 p down (BoE):

| time UTC | strategy | dir | entry | pnl | outcome |
|:---|:---|:---|--:|--:|:---|
| 07:25:02 | EMA_PULLBACK_S | SELL | 13295.30 | +14.95 | TP hit |
| 16:45:03 | EMA_PULLBACK_S | SELL | 13218.40 | −10.60 | STRUCTURE_EXIT (structure_flip_up) |

**2026-07-15** — dom_move +176.1 p up (US_PPI):

| time UTC | strategy | dir | entry | pnl | outcome |
|:---|:---|:---|--:|--:|:---|
| 06:10:01 | EMA_PULLBACK_L | BUY | 13414.80 | −12.70 | STRUCTURE_EXIT (structure_flip_down) |
| 12:10:00 | EMA_PULLBACK_L | BUY | 13405.10 | +30.35 | TP hit |
| 14:35:01 | EMA_PULLBACK_L | BUY | 13447.19 | +16.25 | BE_STOP_POST_SCALEOUT |

07-15 is the only day with meaningfully positive capture (+34 p of
+176 p offered = 19 %) — three fires, one full TP hit.

### 1.3  No-arm holes (contiguous zero-arm hourly windows in 06:00–17:00)

| day | hole span (UTC) | hours | move during hole | comment |
|:---|:---|:---|:---|:---|
| 2026-08-10 | 10:00 – 13:00 | 3 h |  **+0.6 p** | true no-pullback stretch; price sat at 13494 flat |
| 2026-08-14 | — | 0 h | — | arms in every session hour |
| 2026-06-17 | 09:00 – 11:00 | 2 h |  −4.4 p | flat-during-hole |
| 2026-06-17 | 12:00 – 14:00 | 2 h |  −1.3 p | flat-during-hole |
| 2026-06-18 | 12:00 – 15:00 | 3 h | **+29.4 p** | 3-hour counter-trend pullback on a SHORT day — arms blocked (LONG stack not eligible on SHORT tape and vice versa) |
| 2026-07-15 | 08:00 – 09:00 | 1 h | −10.3 p | 1-hour bearish stretch during LONG day; arms correctly stood down |
| 2026-07-29 | 07:00 – 08:00 | 1 h |  +2.8 p | quiet hour |
| 2026-07-29 | 09:00 – 11:00 | 2 h | −13.4 p | 2-hour counter-trend pullback on a LONG day |
| 2026-07-29 | 16:00 – 17:00 | 1 h |  +4.2 p | quiet hour |

**Observation.** No-arm holes are largely legitimate — they're either
flat periods (08-10 10-13 was dead flat) or **counter-trend pullback
stretches** where the EMA stack has genuinely flipped opposite the
grind direction (06-18 12-15 = +29p up-pullback inside a down-grind;
07-29 09-11 = −13p down-pullback inside an up-grind). During these
holes the arm-side gate is doing what it was designed to do.

The **08-10 10:00–13:00 flat hole is the one operator-visible gap** —
the tape sat still, no pullback trigger, and price began its final
climb at 13:25 from ~13494 to 13530.75 at 14:45. That +36 p climb
started AFTER the hole ended, so the arm side would have picked it
up — the missed capture on 08-10 is 100 % downstream-gate driven, not
arm-driven.

Checkpoint files:
`q1_ema_pb_grind.py`, `q1_ema_pb_result.json` — this section done.

---

## Q2 — Price TREND_BANDWALK

Reproducer: `q2_bandwalk_v2.py` → `q2_bandwalk_result.json`.

**Method.** Walk every full day in the regime-log window (2026-05-22 →
2026-08-21; 73 processed days). Fire triggers per variant; entry at
next 5m close after trigger; exit stack applied uniformly:

* SL = 12 p from entry
* Ladder-surrogate ratchet: SL → BE at +10 p; +15 p at +30 p favourable;
  +40 p at +60 p; +75 p at +100 p
* Exhaustion: 6 consecutive bars fail to make new favourable extreme
  AND SL is beyond BE → flat at that bar's close
* Hard flat at 20:40 UTC
* One position at a time; re-entry allowed after exit if trigger fires
  again; **no new entries after 18:00 UTC** (need working room)

The ladder-surrogate is a defensible approximation of the live
`level_ladder` state machine. It captures the ratchet-to-BE + tiered
lock-in + exhaustion-hold + flat-at-20:40 spirit without needing to
reproduce the pivot/PDH/PDL rung fetch.

### 2.1  Full-window headline

| variant | trigger-days | trades | total pnl | avg/day | win-days | trade WR |
|:---|--:|--:|--:|--:|--:|--:|
| **persist_2h** (STRONG_TREND held ≥ 2h) | 44 |  98 |  −11.5 p | −0.3 |  13 |  21 % |
| persist_3h (≥ 3h) | 31 |  59 |  −20.4 p | −0.7 |  11 |  24 % |
| **bandwalk_8_10** (operator spec) |  **4** |   4 |  +17.2 p | +4.3 |   2 |  50 % |
| **bandwalk_10_12** (operator spec) |  **0** |   0 |   0.0 p | — |   0 | — |
| bandwalk_6_10 (sensitivity) | 31 |  42 |  −36.4 p | −1.2 |   8 |  19 % |
| bandwalk_5_8  (sensitivity) | 44 |  64 |  **+90.2 p** | +2.1 |  14 |  22 % |

**Operator-specified band-walk K/M parameters (8/10 and 10/12) are
too strict on this tape.** 8/10 triggers on only 4 days across 73 (5 %);
10/12 never triggers. Even on 07-15 — the biggest audit-grind — 8/10
never triggers because BB touches are scattered, not clustered
(18 upper-band touches on 07-15 across 288 bars, but never 8 within
a 50-min window).

Loosening K/M to catch a meaningful set of days requires **5/8** — but
that variant has 22 % trade win-rate and net-positive largely from
tail wins on 07-15 (+107.8 p) and one other day.

### 2.2  Trigger-day overlap between (a) and (b)

| pair | intersection | union |
|:---|--:|--:|
| persist_2h  ∩ bandwalk_8_10  | 3 | 45 |
| persist_2h  ∩ bandwalk_10_12 | 0 | 44 |
| persist_3h  ∩ bandwalk_10_12 | 0 | 31 |
| persist_2h  ∩ bandwalk_6_10  | 26 | 49 |
| persist_2h  ∩ bandwalk_5_8   | 33 | 55 |

The two families overlap heavily at the loose end; at operator-spec
tightness they're essentially disjoint (bandwalk 8/10 fires 4 times
vs persist_2h's 44 — 3 of the 4 are shared).

### 2.3  08-10 flicker test (the operator's eye check)

Does band-walk trigger where persistence doesn't? **Answer: only if K
is loosened below the operator's stated 8/10.**

| variant | 08-10 trigger? | trades | pnl |
|:---|:---:|:---:|:---:|
| persist_2h                    | **no** | — | — |
| persist_3h                    | **no** | — | — |
| **bandwalk_8_10 (spec)**      | **no** | — | — |
| **bandwalk_10_12 (spec)**     | **no** | — | — |
| bandwalk_6_10 (sensitivity)   | **yes** — 17:10 SELL @13511.65 → 20:40 flat @13507.55  | 1 | +4.1 p |
| bandwalk_5_8  (sensitivity)   | **yes** — 17:05 SELL @13510.85 → 20:40 flat @13507.55  | 1 | +3.3 p |

**Findings:**

1. Persistence fails 08-10 because STRONG_TREND_UP only ever held ≤ 20
   min continuously (44 bars total in the day, but never 24 consecutive).
2. Band-walk at operator-spec 8/10 also fails: BB(20,2) touches on
   08-10 are 19 total, distributed across the day, never clustered
   enough to hit 8/10.
3. Loose band-walk (6/10 or 5/8) TRIGGERS on 08-10 — but only in the
   afternoon post-peak (17:05–17:10), catching the SELL side of the
   pullback from 13530→13507. The operator's "climb" phase
   (03:05–14:45) is not caught by any tested band-walk config.

**Verdict: at operator-specified parameters (8/10 and 10/12), no
variant triggers on 08-10.** The operator's eye may be seeing the
tape differently than K-of-M closes-past-band captures.

### 2.4  Per-target-day performance

| day | dom_move | persist_2h | persist_3h | bandwalk_8_10 | bandwalk_10_12 | bandwalk_6_10 | bandwalk_5_8 |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 2026-08-10 | +44p  | —   | —   | — | — | +4.1 (1) | +3.3 (1) |
| 2026-08-14 | +69p  | +1.0 (3) | +4.9 (3) | — | — | −6.5 (2) | +23.0 (2) |
| 2026-06-17 | −168p | **+40.0 (1)** | — | — | — | 0.0 (1) | 0.0 (1) |
| 2026-06-18 | −129p | +3.0 (4) | +3.0 (3) | — | — | −12.0 (2) | −12.0 (2) |
| 2026-07-15 | +176p | **+63.2 (1)** | +44.5 (1) | — | — | +87.5 (3) | **+95.8 (2)** |
| 2026-07-29 | +102p | 0.0 (1) | — | — | — | +15.0 (1) | +15.0 (1) |
| **totals (target)** | **+688p offered** | **+107.2** | **+52.4** | **0** | **0** | **+88.1** | **+125.1** |
| **totals (non-target = 67 days)** | | **−118.7** | **−72.8** | **+17.2** | **0** | **−124.5** | **−34.9** |
| **full-window (73 days)** | | **−11.5** | **−20.4** | **+17.2** | **0** | **−36.4** | **+90.2** |

**Structural pattern.** On target grind days, persistence-2h catches
+107 p and bandwalk-5/8 catches +125 p. On the 67 non-target days
(false-positive cost), persistence-2h bleeds −118 p while bandwalk-5/8
bleeds only −35 p. Both are net-negative on non-target days — the
false-positive cost is real for every variant that catches meaningful
grind slice.

Checkpoint files:
`q2_bandwalk.py`, `q2_bandwalk_v2.py`, `q2_bandwalk_result.json`.

---

## Q3 — Net-of-overlap dedup vs signal_log

Reproducer: `q3_overlap.py` → `q3_overlap_result.json`.

**Method.** For each variant × day, compare:

* **ctr** — counterfactual PnL from Q2's simulator on that day
* **actual** — pnl_pips summed over signal_log GBPUSD fires on that day
  whose direction matches the counterfactual's direction (double-count
  guard: only same-direction actual fires are subtracted)
* **net-of-overlap** = ctr − actual

If a variant's counterfactual banks +100 p LONG on a day where the
existing book already banked +80 p LONG, the marginal contribution is
+20 p, not +100 p.

### 3.1  Full-window totals

| variant | ctr total | actual same-dir | net-of-overlap | trigger-days |
|:---|--:|--:|--:|--:|
| persist_2h                    |  −11.5 | **+267.2** | **−278.8** | 44 |
| persist_3h                    |  −20.4 | **+340.2** | **−360.6** | 31 |
| bandwalk_8_10 (operator spec) |  +17.2 |   +15.9  |    **+1.3** |  4 |
| bandwalk_10_12 (spec)         |   0.0  |    0.0   |     0.0    |  0 |
| bandwalk_6_10 (sensitivity)   |  −36.4 |  +280.0  |  **−316.4** | 31 |
| bandwalk_5_8 (sensitivity)    |  +90.2 |  +321.4  |  **−231.2** | 44 |

**All variants except bandwalk_8_10 have negative net-of-overlap.** The
existing book is already trading many of the days the variants
counterfactually catch — the new mechanism competes with itself, not
with dead space.

### 3.2  Target-day net-of-overlap

| day | dom_move | best variant → ctr / actual / net |
|:---|:---:|:---|
| 2026-08-10 | +44 p  | bandwalk_6_10 → +4.1 / −25.1 / **+29.2 p** — book bled, new mech would have added value |
| 2026-08-14 | +69 p  | bandwalk_5_8  → +23.0 / +21.4 / **+1.6 p** — book already captured; near breakeven |
| 2026-06-17 | −168 p | **persist_2h** → +40.0 / +7.8 / **+32.1 p** — best margin any variant on any target day |
| 2026-06-18 | −129 p | persist_2h → +3.0 / +52.6 / **−49.6 p** — book already captured heavy; new mech erodes |
| 2026-07-15 | +176 p | bandwalk_5_8 → +95.8 / +105.0 / **−9.2 p** — book already captured full move; marginal ≈ 0 |
| 2026-07-29 | +102 p | bandwalk_5_8 → +15.0 / 0.0 / **+15.0 p** — book banked 0; clean margin |
| **target-day marginal (best per day)** | **+688 p offered** |  **+19.2 p average / day** |

**Winning-trigger-day averages** (marginal per variant, filtered to
days where the counterfactual itself was profitable):

| variant | win days | avg net-of-overlap |
|:---|--:|--:|
| persist_2h                    | 13 |  +4.2 p |
| persist_3h                    | 11 | −21.0 p |
| **bandwalk_8_10 (operator spec)** |  2 | **+22.3 p** |
| bandwalk_6_10                 |  8 |  +1.8 p |
| bandwalk_5_8                  | 14 | +11.0 p |

**Bottom line for Q3.** The mechanism only adds meaningful marginal
value when the existing book undercapturs — 06-17 (FOMC-day short,
book banked only +8 p) and 07-29 (FOMC UP, book 0 p) are the clean
wins. On the days where the book already banked well (07-15 +105 p,
06-18 +53 p), the new mechanism largely double-counts or interferes.

Checkpoint files:
`q3_overlap.py`, `q3_overlap_result.json`.

---

## Q4 — TREND_V3 ER sweep

Reproducer: `q4_tv3_sweep.py` → `q4_tv3_sweep_result.json`.

**Current live config (baseline).** `TREND_V3_ER_MIN=0.5`,
`TREND_V3_ER_BARS=20`.

**Provenance.** ER_MIN=0.5 was set in the initial TREND_V3 commit
`1aa6704 feat(trend_v3): new live daily-spine GBPUSD trend strategy`
(2026-06-30, autobot@localhost). The commit message does not explain
the choice; no `.env` override exists then or now, and no subsequent
commit has touched `TREND_V3_ER_MIN` or `TREND_V3_ER_BARS`. This is a
**default-that-was-never-revisited**, not a value tuned against data.

### 4.1  Sweep summary (all criteria live-config except ER; regime-log window 73 days)

| variant | floor | window | grind days armed | grind arms | non-grind days | non-grind arms |
|:---|--:|--:|--:|--:|--:|--:|
| **baseline** | 0.50 | 20 | **4** (of 6 target) |  **69** |  **23** |  **187** |
| floor_30     | 0.30 | 20 | 5 | 134 | 35 | 611 |
| floor_35     | 0.35 | 20 | 5 | 120 | 34 | 488 |
| floor_40     | 0.40 | 20 | 5 | 102 | 31 | 371 |
| window_40    | 0.50 | 40 | 2 |  46 |  7 |  43 |
| window_60    | 0.50 | 60 | 1 |  45 |  2 |  16 |
| window_80    | 0.50 | 80 | 1 |  24 |  0 |   0 |

**Grind-arm-to-non-grind-arm ratio (higher = more selective):**

| variant | ratio | interpretation |
|:---|--:|:---|
| baseline    | 69/187 = **0.37** | 3 false-positive arms per grind arm |
| floor_30    | 134/611 = 0.22 | 4.5 FP per grind arm — worse |
| floor_35    | 120/488 = 0.25 | 4.1 FP per grind arm — worse |
| floor_40    | 102/371 = 0.28 | 3.6 FP per grind arm — slightly worse |
| **window_40** | 46/43 = **1.07** | **≈ 1:1 — 3× cleaner** |
| **window_60** | 45/16 = **2.81** | **2.8:1 — best selectivity** |
| window_80   | 24/0 = ∞ | 0 false-arms but only 1 grind day + 24 arms |

Lowering the floor adds grind arms but adds MORE non-grind arms per
unit; the ratio degrades. **Widening the window is the selective
lever** — window_60 catches only 07-15 among the grinds but has an
FP ratio 8× better than the baseline.

### 4.2  First-arm timing per target grind day

| day | dom_end | dom_move | baseline | floor_30 | floor_35 | floor_40 | window_40 | window_60 | window_80 |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 2026-06-17 | 19:35 | −168 p | — | — | — | — | — | — | — |
| 2026-06-18 | 19:20 | −129 p | 08:10 | **08:00** | 08:00 | 08:05 | 09:30 | — | — |
| 2026-07-15 | 18:15 | +176 p | 13:05 | **08:55** | 13:05 | 13:05 | 14:30 | 14:55 | 16:25 |
| 2026-07-29 | 19:15 | +102 p | 13:05 | **11:05** | 12:50 | 13:05 | — | — | — |
| 2026-08-10 | 14:45 | +44 p  | 17:35 (post-peak) | **09:05** (pre-peak +36 p to go) | 09:05 | 17:15 (post-peak) | — | — | — |
| 2026-08-14 | 14:25 | +69 p  | — | 18:05 (post-peak) | 18:05 | 18:05 | — | — | — |

**Key observations.**

1. **06-17 stays dead** at every variant — the spine (prior UP) vs
   actual GRIND-DOWN mismatch blocks all arms across all ER
   configurations. Only the intraday-flip machinery can rescue this
   day; no ER tune changes it.
2. **Floor_30 is the only variant that catches 08-10 pre-peak**
   (09:05, +36 p of the +44 p climb still to go). Baseline and
   floor_40 only fire at 17:15–17:35, deep in the post-peak retrace.
3. **08-14 baseline stayed silent** on this walk (spine=DOWN mismatch);
   the actual live 08:05 fire came via the intraday-flip that this
   walk does not model. Under floor_30/35/40 the arm still fires only
   at 18:05 — late.
4. **07-15 with floor_30 arms at 08:55** — hours before the baseline's
   13:05 first-arm; window_60/80 arm even later than baseline.

### 4.3  Top-5 non-grind days by false-arm count

**baseline** (top 5): 07-02 (31 arms, NFP-day), 07-06 (28, ISM_SVC),
06-05 (25, NFP), 07-30 (18, BoE+US_GDP), 06-22 (11).

**floor_30** (top 5): 07-02 (54), 07-30 (49), 06-05 (47), 07-06 (42),
06-22 (31). Same days but +80 % arms each on average.

**window_60** (top): 07-02 (16-ish), 07-30 (0 — silenced), 06-05
(silenced). Wider windows are event-day-selective — they arm on 07-02
(NFP) which had the sharpest impulse but silence the choppier
event-days.

### 4.4  Structural vs parametric conclusion

The prompt asked: "is the ER floor's ~90 % failure rate on grind bars
parametric or structural?" The sweep says **it is structural at
short windows and parametric at long windows.**

* At `window=20` (current), lowering floor from 0.5 → 0.3 adds arms
  but doesn't dramatically change WHERE they arm — the operator-grind
  08-10 borderline case gets a *timing* rescue (09:05 vs 17:35) but
  the ratio worsens.
* At `window=40+`, the ER numerator (net over window) and denominator
  (sum of abs-diff) both grow with a sustained trend, so ER rides
  higher even at slow pace. window_60 armed at 07-15 without shape
  tuning — this is the **structural fix** the analysis suggests.

But window_60 also loses 3 of 4 baseline grind days (06-18, 07-29,
08-10 lost). The selective gain comes at cost of narrow coverage.

Checkpoint files:
`q4_tv3_sweep.py`, `q4_tv3_sweep_result.json`.

---

## Q5 — Verdict summary (side-by-side, no recommendation)

Three routes to grind capture, priced on the same 73-day regime-log
window (2026-05-22 → 2026-08-21). All figures pips of GBPUSD move,
signed (positive = win to the operator).

### 5.1  Status quo (Q1's existing capture)

| | value |
|:---|:---|
| Mechanism | EMA_PULLBACK legacy `_detect` path + level_ladder exits |
| Grind days (6 target) — dominant close-move offered | +688 p |
| Grind days — actual EMA_PB banked (from signal_log) | **+27.4 p** |
| Capture rate on grind tape | **~ 4 %** |
| Arm side | 231 arms across 6 days (adequate) |
| Downstream kill rate | 96 % (34-58 arms per day → 0-3 fires per day) |
| No-arm holes | mostly legitimate (flat periods + counter-pullback stretches); one operator-visible hole on 08-10 10:00-13:00 (3 h, +0.6 p) |
| Bottleneck | **downstream gates** — not arm side |

### 5.2  TREND_BANDWALK — best variant

Best operator-spec: **bandwalk_8_10** (K=8-of-M=10 closes past outer BB).
Best sensitivity variant: **bandwalk_5_8**.

| metric | bandwalk_8_10 (spec) | bandwalk_5_8 (sens) | persist_2h |
|:---|:---|:---|:---|
| Trigger days (of 73) | **4** | 44 | 44 |
| Total counterfactual PnL | +17.2 | +90.2 | −11.5 |
| Total net-of-overlap (Q3) | **+1.3** | −231.2 | −278.8 |
| Winning-trigger-day count | 2 | 14 | 13 |
| Avg net-of-overlap per winning day | **+22.3** | +11.0 | +4.2 |
| Trigger on 08-10 | **no** | yes (17:05 SELL, +3.3) | no |
| Trigger on 08-14 | no | yes (07:10 BUY, +23.0 excl. reversal) | yes (08:35 BUY, +25 EXHAUSTION) |
| Trigger on 06-17 | no | 0.0 (immediate SL) | **+40.0** |
| Trigger on 07-15 | no | +95.8 | +63.2 |

**Best case:** bandwalk_8_10 has a positive net-of-overlap
(+1.3 p total, +22/win-day) but only fires on 4 days out of 73 in the
window. It is not a mechanism for the operator's stated grind
concern — it doesn't fire on 08-10 or 08-14. Loosening K/M catches
more days but adds false-positive cost that erases the gain.

**Persist_2h** delivers +32.1 net-of-overlap on 06-17 (best single-day
margin any variant produced) but bleeds heavily across non-target days.

### 5.3  TREND_V3 retuned — best variant

| metric | baseline (live) | floor_30 | floor_40 | window_60 |
|:---|:---:|:---:|:---:|:---:|
| ER floor | 0.50 | 0.30 | 0.40 | 0.50 |
| ER window | 20 | 20 | 20 | 60 |
| Grind days armed (of 6 target) | 4 | 5 | 5 | 1 |
| Grind arms | 69 | 134 | 102 | 45 |
| Non-grind arms | 187 | 611 | 371 | 16 |
| Grind:non-grind ratio | **0.37** | 0.22 | 0.28 | **2.81** |
| 08-10 first arm | 17:35 post-peak | **09:05 pre-peak** | 17:15 post-peak | none |
| 07-15 first arm | 13:05 in-move | **08:55 early** | 13:05 | 16:25 late |

**Trade-off.**
* **floor_30**: catches 08-10 pre-peak but almost doubles non-grind
  false-arm count (611 vs 187). Ratio degrades from 0.37 → 0.22.
* **window_60**: excellent selectivity (2.81 ratio) but covers only
  1 of 6 target grind days (07-15). Loses everything else.
* Neither route dominates — floor and window represent orthogonal
  trade-offs (coverage vs precision).

**Baseline (live) is Pareto-reasonable given the trade-off surface:**
0.37 grind-to-noise ratio, 4 of 6 target days armed. No sweep variant
strictly dominates it on both axes.

### 5.4  Consolidated Q1-Q5 side-by-side

Pips on target 6 grind days (dominant move: 688 p total offered):

| route | mechanism | grind days armed / 6 | grind arms / 231 | grind pnl banked | non-grind cost (p) | net-of-overlap on target |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **Status quo** | EMA_PB legacy + ladder | 6 arm; 4 fire | 231 arms → 9 fires | **+27.4 p** | (already deducted) | baseline |
| BANDWALK 8/10 (spec) | new module, priority TBD | 0 of 6 target | 0 grind arm total on target | 0 | +17 p total window | **0 (never fires on target)** |
| BANDWALK 5/8 (sens) | new module | 5 of 6 (all but 06-17) | 8 target arms | +125.1 | −34.9 p non-target | +2.9 p net-of-overlap on 08-10; −80 p on target overall (crowds existing book) |
| persist_2h | new module | 4 of 6 target | 10 target arms | +107.2 | −118.7 p non-target | +32.1 on 06-17; −60 on target overall |
| TV3 floor_30 (retune) | existing strategy | 5 of 6 target | 134 grind arms | ~ +100 to +150 p if all-fires-priced (uninstrumented — my sweep does arms not fills) | 611 non-grind arms | — (not priced end-to-end; requires re-run of ladder exit stack) |
| TV3 window_60 (retune) | existing strategy | 1 of 6 target (07-15) | 45 grind arms | +45 arm approx | 16 non-grind arms | narrow but clean |

### 5.5  Load-bearing caveats

* **Q2/Q3 PnL uses a ladder-surrogate**, not the live `level_ladder`
  state machine (which reads pivots + PDH/PDL rungs). Absolute pnl
  numbers should be treated as directional, not point estimates. A
  ~ ±20 % swing in per-trade pnl is plausible depending on the actual
  ladder-rung sequence on each day.
* **06-17 (Fed decision, GRIND_100 DOWN) is impossible for TV3 or
  bandwalk to catch** without intraday flip or spine-override —
  prior daily UP + tape DOWN. No ER retune fixes this.
* **All Q4 sweep numbers count ARMS, not fills.** The end-to-end pnl of a
  retuned TV3 would require running the ladder exit stack over each
  arm — not done here.
* **Q1's downstream-kill attribution is aggregate**, not per-gate.
  The 96 % downstream kill rate is real but which specific gates
  (news blackout, H1 direction, pullback-shape, ribbon deferral,
  cooldown) are responsible is unknowable from the current
  observability.
* **Regime engine data is 78 days** (starts 2026-05-22). The pre-May
  audit GRIND_100 days (01-05, 01-23, 04-07, 04-13, 04-30) are
  excluded from every Q here.
* **Thin cells everywhere** — only 6 target grind days, only 4 days
  where bandwalk_8_10 triggers, 1 winning trigger day for
  bandwalk_10_12 (zero). No single number in this report survives
  n<10 caution.

The operator has the numbers. The build decision follows the numbers,
not this report.

---

## Artefacts

Under `/opt/tradingbot/reports-public/grind_capture_20260822/`:

* `q1_ema_pb_grind.py` + `q1_ema_pb_result.json`
* `q2_bandwalk.py`, `q2_bandwalk_v2.py`, `q2_bandwalk_result.json`
* `q3_overlap.py` + `q3_overlap_result.json`
* `q4_tv3_sweep.py` + `q4_tv3_sweep_result.json`
* This report: `REPORT.md`




