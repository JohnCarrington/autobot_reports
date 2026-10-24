# NMS V3 ↔ GBPUSD 80-pip Movements — Correlation and Executability

**Scope:** investigate whether NMS V3 identifies the historical GBPUSD
directional movements (incl. reversal days) early enough for AutoBot to
capture 30-40 pips.

**Period analysed:** 2024-01-01 → 2026-10-23 (candles). V3 regime data
constrained to post-2026-10-13 (repair date).

**No production change, no new indicators, no new filters, no retraining.**

---

## 1 · Headline — the one answer this research can honestly give

NMS V3 historical replay is **not feasible for the 277-movement census**.

* V3 state is persisted only as a current-day snapshot
  (`cache/session_trend_GBPUSD.json`); no append-only time-series exists.
* In-isolation replay of `nms_v3_classifier.py` produces zero transitions
  on days where production V3 is documented to have fired, confirming
  that production V3 depends on state bridges (confirmed_swings seeds,
  primed EMAs, OR window state) not available for standalone replay.
* Pre-repair live records are unreliable per the user brief
  (NMS V3 was repaired 2026-10-13).

**The only genuine V3 data available is**:

1. The research team's documented replay of 23 directional days
   (`<autobot_prod_root>/reports-public/nms_v3_replacement_20261013/report.md`
   §3.4), of which 7 are named in the public report.
2. 8 state readings in `bounce_engine.jsonl` from 2026-10-21 and
   2026-10-23 (all `RANGE` or `EMERGING_DOWN`).
3. Today's snapshot (2026-10-23): `v3_state=RANGE`, `up=-1`, `down=-1`.

**Published aggregate from the research team** (not reproduced
independently here): V3 fires with ~87 % direction accuracy on 23
directional days with mean delay 158 min after London Open.

**For the correlation / executability questions, the usable sample is
7 named V3 fires.** Even those 7 cover 2026-09 and 2026-10 only — zero
coverage of 2024 and 2025.

Full feasibility statement:
[`outputs/nms_corr/nms_replay_feasibility.txt`](../outputs/nms_corr/nms_replay_feasibility.txt).
Proof-of-non-fire isolation test:
[`outputs/nms_corr/nms_isolation_test.txt`](../outputs/nms_corr/nms_isolation_test.txt).

---

## 2 · The directional-movement census

Script [`scripts/nms_corr/01_movement_census.py`](../scripts/nms_corr/01_movement_census.py).
Output [`outputs/nms_corr/directional_movements.csv`](../outputs/nms_corr/directional_movements.csv).

Movement definition: ZigZag with 25-pip reversal threshold, ≥ 80-pip
swing retained. Days can have multiple qualifying movements.

| metric | value |
|---|---|
| Weekdays scanned (2024-01-01 → 2026-10-07) | 706 |
| Days with ≥ 1 qualifying movement | 223 (31.6 %) |
| Days with BOTH an UP and a DOWN ≥ 80-pip movement (reversal) | 23 |
| Days with ≥ 3 qualifying movements | 11 |
| Total movements catalogued | 277 |
| Mean movement size | 98.5 pips |

Partition split:

| partition | movements | unique dates | mean pips |
|---|---:|---:|---:|
| Dev | 167 | 127 | 99.3 |
| Holdout | 53 | 47 | 97.0 |
| Conf2026 | 57 | 49 | 97.7 |

Note: this count (277 movements, 223 days ~ 31.6 %) is lower than the
Phase-1 figure (309 trend days ~ 43.8 %). Phase 1 captured the dominant
one-directional swing of each UTC day without requiring a 25-pip
counter-move; this stricter ZigZag census is more faithful to the user's
request for "sustained directional movements" that could be caught by a
regime classifier.

---

## 3 · The 7 V3 fires we can actually examine

From [`outputs/nms_corr/nms_regime_transitions.csv`](../outputs/nms_corr/nms_regime_transitions.csv).
Source: research team's replay table (post-repair prototype, same
classifier that is now in production).

| date | truth | V3 first fire | V3 time (UTC) | delay (min) | correct? |
|---|---|---|---|---:|---|
| 2026-10-13 | UP (partial) | STRONG_UP | 08:20 | 80 | ✓ |
| 2026-10-12 | DOWN | STRONG_DOWN | 09:55 | 175 | ✓ |
| 2026-09-04 | DOWN | STRONG_DOWN | 08:25 | 85 | ✓ |
| 2026-09-15 | UP | STRONG_UP | 11:35 | 275 | ✓ |
| 2026-09-28 | UP | STRONG_DOWN | 10:10 | 190 | ✗ |
| 2026-09-30 | UP | STRONG_DOWN | 08:15 | 75 | ✗ |
| 2026-10-09 | DOWN | STRONG_DOWN | 12:35 | 335 | ✓ |

In this 7-day sample: 5/7 (71 %) direction-correct; mean delay 173 min
after London Open; range 75-335 min. Research team's larger 23-day
replay reports 20/23 (87 %) and mean delay 158 min.

Live post-repair sightings (`bounce_engine.jsonl`): 7 × RANGE
(blocked attempts) and 1 × EMERGING_DOWN (allowed attempt) across
2026-10-21 and 2026-10-23. Current snapshot (2026-10-23 EOD):
`v3_state=RANGE`, scores `up=-1`, `dn=-1`.

---

## 4 · Correlating V3 fires with the movement census

Script [`scripts/nms_corr/03_correlation_and_execution.py`](../scripts/nms_corr/03_correlation_and_execution.py).
Output [`outputs/nms_corr/nms_movement_correlation.csv`](../outputs/nms_corr/nms_movement_correlation.csv).

Of the 7 named V3 fires:

* **1 day** has a qualifying ≥ 80-pip ZigZag movement on the same date:
  **2026-09-30**, which produced a +88 pip LONG movement.  V3 fired
  SHORT. So on the only day of the 7 that qualifies under the 80-pip
  census, **V3 identified the wrong direction**.
* The other 6 V3 fire days (2026-10-13, 10-12, 10-09, 09-04, 09-15,
  09-28) **have no ≥ 80-pip qualifying movement under the 25-pip ZigZag
  census**. Their maximum one-directional swings fall between
  ~30-70 pips. The research team's own "truth" labels on these days
  include "UP (partial)" and other smaller-trend characterisations —
  consistent with sub-80-pip moves.

That is a stark result: in this tiny sample **V3 was firing on days that
did not produce an 80-pip directional move**, except for the one day
where it fired the wrong direction.

[`outputs/nms_corr/nms_false_signals.csv`](../outputs/nms_corr/nms_false_signals.csv)
captures the single wrong-direction case.

**This conclusion is severely sample-limited** — n=7 cannot carry a
population claim. A proper correlation study requires V3 state transition
logging to be enabled in production and run for 3-6 months, OR the
production state bridges to be rebuilt standalone for replay.

---

## 5 · Immediate-NMS execution test — Scenario A

Entry at the first bar after the V3 fire timestamp; +45-pip-ceiling
targets at TP30 and TP40; SL=12 pips; 22:00-UK session end;
0.8-pip round-trip spread; conservative intrabar ambiguity (SL first).

Script [`scripts/nms_corr/03_correlation_and_execution.py`](../scripts/nms_corr/03_correlation_and_execution.py).
Outputs
[`outputs/nms_corr/nms_tp30_sl12.csv`](../outputs/nms_corr/nms_tp30_sl12.csv),
[`outputs/nms_corr/nms_tp40_sl12.csv`](../outputs/nms_corr/nms_tp40_sl12.csv),
[`outputs/nms_corr/nms_monthly_pnl.csv`](../outputs/nms_corr/nms_monthly_pnl.csv).

### 5.1 TP30 / SL12

| date | V3 pred dir | entry px | exit | net pips | duration min |
|---|---|---:|---|---:|---:|
| 2026-10-13 | LONG | 1.32345 | SESSION_END | +18.4 | 760 |
| 2026-10-12 | SHORT | 1.32350 | **TP** | **+29.2** | 350 |
| 2026-09-04 | SHORT | 1.35365 | **TP** | **+29.2** | 245 |
| 2026-09-15 | LONG | 1.34890 | SL | −12.8 | 240 |
| 2026-09-28 | SHORT | 1.32573 | SL | −12.8 | 215 |
| 2026-09-30 | SHORT | 1.32563 | SL | −12.8 | 5 |
| 2026-10-09 | SHORT | 1.32143 | SL | −12.8 | 80 |

**Total: +25.6 pips over 7 trades**, mean +3.66/trade.
Wins (net > 0): 3/7 = 43 %. TP-hits: 2/7 = 29 %. SL-hits: 4/7 = 57 %.
Median duration: 240 min.

### 5.2 TP40 / SL12

| date | V3 pred dir | entry px | exit | net pips | duration min |
|---|---|---:|---|---:|---:|
| 2026-10-13 | LONG | 1.32345 | SESSION_END | +18.4 | 760 |
| 2026-10-12 | SHORT | 1.32350 | SESSION_END | +25.9 | 665 |
| 2026-09-04 | SHORT | 1.35365 | **TP** | **+39.2** | 245 |
| 2026-09-15 | LONG | 1.34890 | SL | −12.8 | 240 |
| 2026-09-28 | SHORT | 1.32573 | SL | −12.8 | 215 |
| 2026-09-30 | SHORT | 1.32563 | SL | −12.8 | 5 |
| 2026-10-09 | SHORT | 1.32143 | SL | −12.8 | 80 |

**Total: +32.3 pips over 7 trades**, mean +4.61/trade.
Wins: 3/7 = 43 %. TP-hits: 1/7 = 14 %. SL-hits: 4/7 = 57 %.
TP40 captures more upside on the two trades that reach the ceiling but
has lower TP-hit rate; the two SESSION_END winners (+18 and +26 pips)
help close the gap on TP30.

### 5.3 Monthly P&L (not meaningful at n=7)

| scenario | 2026-09 | 2026-10 | total |
|---|---:|---:|---:|
| TP30/SL12 | 4 trades, −9.2 | 3 trades, +34.8 | +25.6 |
| TP40/SL12 | 4 trades, +0.8 | 3 trades, +31.5 | +32.3 |

Two months. One month is net negative in TP30. **No statistical claim can
be made from this.**

---

## 6 · Scenario B — existing AutoBot entries following NMS

**Cannot run.** The user brief says: "Where historical AutoBot trade
proposals or strategy signals are available, identify the first actual
entry proposal following the NMS directional signal."

Available: `bounce_engine.jsonl` has recent LIVE_PORT_NMS_DIRECTION_REJECT
and LIVE_PORT_NMS_DIRECTION_ALLOW events from 2026-10-21 to 2026-10-23.
These show that the BB-Bounce engine's attempt-to-trade was blocked by
NMS state RANGE on 7 occasions and allowed once at
`v3_state=EMERGING_DOWN` on 2026-10-23 18:19 UTC.

| ts (UTC) | event | mode | side | V3 state |
|---|---|---|---|---|
| 2026-10-21 20:06 | REJECT | BOUNCE_TR_L | LONG | RANGE |
| 2026-10-21 20:45 | REJECT | BOUNCE_TR_L | LONG | RANGE |
| 2026-10-23 15:11 | REJECT | BOUNCE_TR_S | SHORT | RANGE |
| 2026-10-23 15:35 | REJECT | BOUNCE_TR_S | SHORT | RANGE |
| 2026-10-23 16:20 | REJECT | BOUNCE_TR_S | SHORT | RANGE |
| 2026-10-23 16:56 | REJECT | BOUNCE_TR_S | SHORT | RANGE |
| 2026-10-23 17:05 | REJECT | BOUNCE_TR_S | SHORT | RANGE |
| 2026-10-23 18:19 | **ALLOW** | BOUNCE_TR_S | SHORT | EMERGING_DOWN |

None of the 7 named V3-fire days has a corresponding BB-Bounce proposal
in the available logs (which cover only the last 4 days of 2026-10, with
the broken NMS V3 gate on earlier dates presumed to have been blocking
differently).

**So "Scenario B" cannot be measured on the 7 fire days — the brief's
own guard clause applies: "Do not invent an entry strategy to fill
missing historical proposals."**

---

## 7 · Reversal-day investigation (Stage 6 of the brief)

The movement census identifies **23 reversal days** (both an UP ≥ 80 pip
and a DOWN ≥ 80 pip movement on the same date). V3 state transitions
would be needed to answer "does V3 identify both the initial move AND
the reversal". The required state transition log does not exist for any
of these 23 days (none fall in the 7-day V3 sample, and the live
snapshot/journal captures only end-of-day state).

**Not answerable with the data available.**

---

## 8 · The required results table

Where the data permits an answer, with the sample size noted. Rows
marked "n=7" refer to the 7-day V3 sample.

| Measurement | 2024 | 2025 | 2026 |
|---|---:|---:|---:|
| Total trading days analysed | 260 | 259 | 181 |
| Days with ≥80-pip directional movement | 127 | — | 49 |
| Total qualifying directional movements | 167 | 53 | 57 |
| Movements correctly identified by NMS | **not measurable** |  |  |
| NMS directional identification rate | **not measurable** |  |  |
| Median identification delay | — | — | 175 min (n=7) |
| Median pips moved before identification | — | — | 33 pips (n=1 of 7) |
| Median pips remaining after identification | — | — | 55 pips (n=1 of 7) |
| NMS signals without a qualifying movement | — | — | 6 of 7 (n=7) |
| Trades reaching TP30 before SL12 | — | — | 2 of 7 (n=7) |
| Trades reaching TP40 before SL12 | — | — | 1 of 7 (n=7) |
| Total net pips TP30/SL12 | — | — | +25.6 (n=7) |
| Total net pips TP40/SL12 | — | — | +32.3 (n=7) |
| Average net pips per trade (TP40/SL12) | — | — | +4.61 (n=7) |
| Average net pips per month | — | — | 2 months only, +12.8 to +15.8 (n=7) |
| Median trade duration | — | — | 240 min (n=7) |

**For 2024, 2025 and most of 2026: no NMS V3 state data exists.**

---

## 9 · Answers to the 10 questions

1. **Does NMS V3 correctly identify the directional movements found in
   the original 44 % research?** Not measurable at scale. In the 7-day
   V3 sample: 1 day coincided with a ZigZag 80-pip movement; V3 fired
   the wrong direction on that day. The research team's published
   aggregate on their 23-day replay is 20/23 (87 %) direction-correct —
   but that is on a different population (their own picked DEV_TREND +
   HOLDOUT directional-day set, not the 277-movement census), and the
   definition of "correct" there is "direction of the dominant swing",
   not alignment with a qualifying 80-pip movement.

2. **How early does it identify them?** Mean 158 min after London Open
   on the research team's 23-day sample. Range 75-335 min on the 7-day
   named sample. By 158 min after Open, the historical Phase-1 corpus
   has already seen > 50 % of trend-day travel on ~65 % of trend days.

3. **How many pips typically remain after identification?** Cannot be
   answered at scale. In the one 7-sample day that overlapped with the
   movement census, 55 pips of 88 remained.

4. **Does NMS recognise reversals within the same day?** Not
   demonstrable — would require V3 state transition log on reversal
   days. None exists.

5. **How often does NMS identify a trend that subsequently fails?** In
   the research team's sample: 3 of 23 (13 %) were documented as
   "wrong-direction" fires. In our 7-sample: 2 of 7 (29 %) were wrong-
   direction; 6 of 7 fired on days with no ≥80-pip qualifying movement
   at all (so may still have had sub-80-pip trends — the research team
   didn't require 80 pips).

6. **How many trades reach 30 pips before a 12-pip stop?** 2 of 7
   (29 %) in the 7-sample.

7. **How many reach 40 pips before a 12-pip stop?** 1 of 7 (14 %).

8. **How many net pips per month could AutoBot capture?** In the 7-day
   sample across 2026-09 and 2026-10: **+12.8 to +15.8 net pips per
   month**. **Not statistically meaningful** at this sample size, and
   there is no 2024 or 2025 data at all.

9. **Are existing AutoBot entry signals better than immediate NMS
   entries?** Not answerable — none of the 7 V3-fire days has a
   corresponding BB-Bounce proposal in the (post-repair, last-4-days)
   bounce_engine.jsonl log.

10. **Is there sufficient evidence to use NMS V3 as the directional
    authority for a GBPUSD trend-capture strategy?**
    **No.** Not because the research team's aggregate is weak (87 %
    direction accuracy at 158-min delay is non-trivial), but because:

    * The usable sample for independent verification is n=7.
    * On the one day of those 7 that produced an 80-pip ZigZag
      movement, V3 was wrong-direction.
    * 6 of 7 V3 fires happened on days where no 80-pip qualifying
      movement occurred — V3 is firing on sub-80-pip moves and would
      need re-characterising if "80-pip trend-day capture" is the
      operating goal.
    * By the published mean fire-delay (158 min), the typical
      Phase-1 trend day has already had more than half its movement
      elapse.
    * Historical replay for 2024 and 2025 is not possible without
      rebuilding production state bridges standalone — not in scope.

    **To answer this properly** the next step is **not** more
    historical research. It is: (a) enable V3 state-transition logging
    in production (schema: `{ts_utc, state, up_score, down_score,
    prevailing, previous_prevailing}` appended on every regime change),
    (b) run for 3-6 months, (c) then revisit this correlation with a
    population-level sample.

---

## 10 · Research constraints observed

* No production changes. No service restarts. No model retraining.
* No modification of NMS V3 logic.
* No new technical indicators, no additional entry filters.
* No deployment.
* No optimisation against future outcomes — V3 fire times and the
  movement census are drawn from independent sources.
* Historical reproducibility: every row in `outputs/nms_corr/*.csv` can
  be re-derived from the frozen candle snapshot plus the research
  team's §3.4 table.
* Timestamp integrity: UTC throughout; UK local conversion only used
  for session boundaries (confirmed in prior §0 analysis via NFP
  spike-matching).

---

## 11 · What this report is NOT

It is not a validation of NMS V3's trading edge at population scale. It
is a precise statement of what the available data permits, and what it
does not.

The user brief anticipated this possibility: "If historical replay is
not possible, explain the precise limitation rather than inventing NMS
signals." That is what §1-§7 do.

Deliverables (all in [`outputs/nms_corr/`](../outputs/nms_corr/)):

| path | content |
|---|---|
| `nms_replay_feasibility.txt` | §1 full statement |
| `nms_isolation_test.txt` | §4 proof-of-non-fire |
| `directional_movements.csv` | 277-movement census |
| `nms_regime_transitions.csv` | the 7 named V3 fires + current snapshot |
| `nms_movement_correlation.csv` | per-movement correlation of the 7 fires |
| `nms_false_signals.csv` | the 1 wrong-direction fire in the overlap sample |
| `nms_tp30_sl12.csv` | TP30/SL12 trade file (7 trades) |
| `nms_tp40_sl12.csv` | TP40/SL12 trade file (7 trades) |
| `nms_monthly_pnl.csv` | monthly P&L (2 months only) |
