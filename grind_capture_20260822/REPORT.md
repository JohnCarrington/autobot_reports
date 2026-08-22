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

