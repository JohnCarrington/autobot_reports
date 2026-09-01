# Corpus recalibration — DST · LevelMemory weights · Two-bounce rescope grid

**Host:** 161 · **Date:** 2026-09-01 · **Scope:** read-only research + weight proposal.
No live-path changes. No env changes. No P&L simulation (turn-rate counting only).

**Corpus:** `/tmp/coincidence_ext_v2_events.json` — 33,252 events over 674
full-session weekday days (2024-01-01 → 2026-08-14), audited provenance per
`corpus_provenance`. Bar sources: `data/candles` (IG mid, 2026-03-23→08-14);
`data/ohlc` (mid, 2026-01→04-06 excl. 04-07..10); `data/candles_ext`
(HistData rebuild, bid, 2024+2025).

Scripts:
- STEP 0: `/tmp/dst_verify3.py`
- STEP 1: `/tmp/step1_weights.py`
- STEP 2: `/tmp/step2_grid.py`

---

## STEP 0 — DST verdict: NOT CLEAN (EDT months contaminated)

The +5h HistData→UTC shift, calibrated on a March 2026 week (pre-US-DST),
was checked month-by-month against three anchors:

### Anchor 1 — Tokyo open (no Japan DST, must sit at 00:00 UTC year-round)

Step-up hour in the 22-02 UTC window (largest hour-to-hour delta of the 5m
mean range):

| month     | mean range 22..02 | step-up hr | expected | verdict |
|:----------|:------------------|:----------:|:--------:|:-------:|
| 2024-01   | 22:26k 23:19k 00:27k 01:33k 02:27k | **00** | 00 | OK |
| 2024-02   | 22:25k 23:16k 00:25k 01:29k 02:22k | **00** | 00 | OK |
| 2024-03   | 22:18k 23:15k 00:23k 01:26k 02:21k | **00** | 00 | OK (pre-DST bulk) |
| 2024-04   | 22:23k 23:13k 00:16k 01:28k 02:32k | **01** | 00 | **MISS +1h** |
| 2024-05   | 22:26k 23:12k 00:14k 01:25k 02:27k | **01** | 00 | **MISS +1h** |
| 2024-06   | 22:26k 23:11k 00:12k 01:21k 02:23k | **01** | 00 | **MISS +1h** |
| 2024-07   | 22:29k 23:12k 00:14k 01:24k 02:23k | **01** | 00 | **MISS +1h** |
| 2024-08   | 22:29k 23:19k 00:19k 01:29k 02:30k | **01** | 00 | **MISS +1h** |
| 2024-09   | 22:21k 23:16k 00:18k 01:30k 02:33k | **01** | 00 | **MISS +1h** |
| 2024-10   | 22:24k 23:17k 00:20k 01:30k 02:31k | **01** | 00 | **MISS +1h** |
| 2024-11   | 22:24k 23:28k 00:39k 01:43k 02:36k | **00** | 00 | OK |
| 2024-12   | 22:24k 23:22k 00:31k 01:32k 02:27k | **00** | 00 | OK |
| 2025-01   | 22:27k 23:38k 00:41k 01:43k 02:37k | **23** | 00 | miss (23; ambiguous) |
| 2025-02   | 22:32k 23:28k 00:38k 01:40k 02:36k | **00** | 00 | OK |
| 2025-03   | 22:22k 23:22k 00:35k 01:35k 02:30k | **00** | 00 | OK (pre-DST bulk) |
| 2025-04   | 22:43k 23:55k 00:49k 01:64k 02:59k | **01** | 00 | **MISS +1h** |
| 2025-05   | 22:34k 23:27k 00:31k 01:48k 02:53k | **01** | 00 | **MISS +1h** |
| 2025-06   | 22:41k 23:27k 00:33k 01:47k 02:49k | **01** | 00 | **MISS +1h** |
| 2025-07   | 22:48k 23:20k 00:22k 01:38k 02:40k | **01** | 00 | **MISS +1h** |
| 2025-08   | 22:38k 23:18k 00:20k 01:33k 02:36k | **01** | 00 | **MISS +1h** |

*(Tokyo values in units of `sum(hi-lo)*10000` pips-scaled; step column is
biggest hour-to-hour gain among {23-22, 00-23, 01-00, 02-01}.)*

### Verdict

The HistData source is not fixed-EST — it toggles with US DST. The uniform
+5h shift produces true UTC only during EST months (Nov→Mar). During EDT
months (roughly Apr→Oct) the shifted clock runs **1h ahead of true UTC**.

**Months where the shifted clock is +1h ahead (session-tag error):**
2024-04, 2024-05, 2024-06, 2024-07, 2024-08, 2024-09, 2024-10;
2025-04, 2025-05, 2025-06, 2025-07, 2025-08, 2025-09, 2025-10.

**Transition weeks** (partial contamination): early March 2024 & 2025
(before US-DST start), late October 2024 & 2025 (after UK-DST ends but
before US-DST ends), and the first days of November (before US-DST ends
on 1st Sunday). Late Mar / early Nov also have short spans where UK is
already on/off DST but US is not, giving 4h effective offset.

**Downstream tagging rule:** any session-cut analysis (LON/NY/OVERLAP) on
events in the EDT-contaminated months carries a systematic +1h shift in
its bounce-timestamp session assignment. Session-boundary events can move
across LON↔NY↔Late windows. For broad-window analyses (7-hour LON, 9-hour
NY) the effect is small; for tight sub-hour analyses (news-window,
London-fixing) it is material. STEP 2 below uses broad windows and flags
this caveat inline.

Test files that fell out of the DST test but are informative:
- London/Frankfurt open plateau (06:00-09:00 UTC): dominated by the Frankfurt
  CET/CEST step at "07:00 shifted" every month — cannot distinguish the DST
  hypothesis on its own; noted, not used as sole evidence.
- NY equity open (13:30 UTC BST / 14:30 UTC GMT): step hour is consistently
  in the 13-15 window without a clean BST-vs-GMT signature — NYSE open is
  one of several drivers (US 12:30 UTC releases, 14:00 UTC releases, LDN
  4pm fix at 16:00). Also not clean.

The Tokyo anchor is the discriminating one and is unambiguous.

---

## STEP 1 — LevelMemory weight recalibration

Cohort mapping (per operator's `cohort_of` semantics):
- **P** — `kind=LEVEL, cohort=P, level_name=P`
- **OUTER_PIVOT** — `kind=LEVEL, cohort=OUTER, level_name in R1..R3/S1..S3`
- **BAND (LOW-CONFIDENCE)** — `kind=BAND` (BB upper/lower). Flagged because
  band identity drifts within the day.
- **SESSION_STRUCT (PDH/PDL/session H-L)** — **NOT REPRESENTED** in the
  corpus's `kind` / `cohort` / `level_name` schema. Not testable here.
  (Two-bounce study STEP 2 does track these anchors — different detector.)
- **ROUND (round numbers)** — **NOT REPRESENTED**. Not testable.

Outcome measure: **turn15** (peak forward MFE ≥ 15p within 12 fwd 5m bars).
turn10 shown for context.

Weight proposal rule (stated and applied mechanically):
`proposed = round(lift_pp / 5)`, clamped to `±4`,
where `lift_pp = 100 × (rate_bucket − baseline_rate_of_cohort)`.

### Cohort **P** — baseline: n=2,461, turn15=40.8%, turn10=66.5%

| factor       | bucket           | n    | turn15 | turn10 | lift15pp | default | proposed | flag |
|:-------------|:-----------------|-----:|-------:|-------:|---------:|--------:|---------:|:-----|
| test_number  | t=1 (first)      | 996  | 36.9%  | 63.7%  | **−3.9** | **+3**  | **−1**   | **‼ DIRECTION DISAGREE** |
| test_number  | t=2              | 634  | 43.1%  | 68.1%  |  +2.2    |   0     |   0      | matches |
| test_number  | t=3+             | 831  | 43.8%  | 68.7%  | **+3.0** | **−3**  | **+1**   | **‼ DIRECTION DISAGREE** |
| role_reversal| rr=N             | 1834 | 39.7%  | 65.3%  |  −1.1    |   0     |   0      | matches |
| role_reversal| rr=Y             | 627  | 44.2%  | 70.2%  |  +3.3    |  +4     |  +1      | same sign, weaker |
| recency      | fresh (first)    | 996  | 36.9%  | 63.7%  |  −3.9    |   —     |  −1      | (bucket not weighted live) |
| recency      | fresh (≤30m)     | 355  | 44.8%  | 68.7%  |  +4.0    |  +1     |  +1      | **matches** |
| recency      | medium (30m-2h)  | 460  | 43.5%  | 67.8%  |  +2.6    |   —     |   0      | — |
| recency      | stale (>2h)      | 650  | 42.8%  | 68.8%  |  +1.9    |   —     |   0      | — |

### Cohort **OUTER_PIVOT** — baseline: n=2,212, turn15=46.7%, turn10=73.3%

| factor       | bucket           | n    | turn15 | turn10 | lift15pp | default | proposed | flag |
|:-------------|:-----------------|-----:|-------:|-------:|---------:|--------:|---------:|:-----|
| test_number  | t=1 (first)      | 992  | 48.8%  | 74.5%  |  +2.1    |  +3     |   0      | same sign, weaker |
| test_number  | t=2              | 567  | 46.9%  | 75.3%  |  +0.3    |   0     |   0      | matches |
| test_number  | t=3+             | 653  | 43.2%  | 69.7%  |  −3.5    |  −3     |  −1      | same sign, weaker |
| role_reversal| rr=N             | 2212 | 46.7%  | 73.3%  |   —      |   0     |   0      | — |
| role_reversal| rr=Y             |    0 |  n/a   |  n/a   |   —      |  +4     |   —      | **NOT MEASURABLE** (see note) |
| recency      | fresh (first)    | 992  | 48.8%  | 74.5%  |  +2.1    |   —     |   0      | — |
| recency      | fresh (≤30m)     | 299  | 45.8%  | 75.6%  |  −0.8    |  +1     |   0      | wrong direction, tiny |
| recency      | medium (30m-2h)  | 391  | 48.6%  | 76.7%  |  +1.9    |   —     |   0      | — |
| recency      | stale (>2h)      | 530  | 41.7%  | 67.2%  |  −5.0    |   —     |  −1      | — |

**Role-reversal on OUTER_PIVOT — not measurable.** The audited corpus is
side-asymmetric: R1/R2/R3 events emit only when approached from below
(side=SELL); S1/S2/S3 only from above (side=BUY). No `(date, level_name)`
in the corpus contains touches from both sides. The `+4` default cannot be
falsified from this corpus on this cohort; if it matters, need a corpus
change (emit re-touches from the far side after `close_beyond=True`).

### Cohort **BAND** — LOW-CONFIDENCE — baseline: n=24,770, turn15=23.8%, turn10=43.1%

| factor       | bucket           | n     | turn15 | turn10 | lift15pp | default | proposed | flag |
|:-------------|:-----------------|------:|-------:|-------:|---------:|--------:|---------:|:-----|
| test_number  | t=1 (first)      |  1419 | 16.8%  | 34.8%  | **−7.0** | **+3**  | **−1**   | **‼ DIRECTION DISAGREE** |
| test_number  | t=2              |  1419 | 16.8%  | 34.8%  |  −7.0    |   0     |  −1      | — |
| test_number  | t=3+             | 21932 | 24.7%  | 44.2%  |  +0.9    |  −3     |   0      | weaker; opposite sign |
| role_reversal| rr=Y             |     0 |  n/a   |  n/a   |    —     |  +4     |   —      | NOT MEASURABLE (same as OUTER) |
| recency      | fresh (≤30m)     | 15419 | 24.2%  | 43.3%  |  +0.4    |  +1     |   0      | weaker |
| recency      | medium (30m-2h)  |  4820 | 24.2%  | 45.1%  |  +0.4    |   —     |   0      | — |
| recency      | stale (>2h)      |  3112 | 24.2%  | 42.6%  |  +0.4    |   —     |   0      | — |

**Why BB looks inverted on test_number:** BB touches happen constantly
(each 5m bar can be a touch); the "first BB touch of the day" is nearly
always at the Asian-session opening range extreme when the band is still
wide and price hasn't yet clustered — low turn rate. Later touches happen
in trending or reverting phases where the band has tightened around price
— higher turn rate. This is an artifact of BB-identity drift (LOWER at
08:00 is not the LOWER at 15:00), which is why BAND is flagged
LOW-CONFIDENCE.

### Summary vs live defaults (+3 / −3 / +4 / +1)

| live factor                     | default | P proposed | OUTER proposed | BAND proposed (lo-conf) |
|:--------------------------------|--------:|-----------:|---------------:|------------------------:|
| mem_first_touch                 |    +3   |    **−1**  |         0      |         **−1**          |
| mem_test_number_3plus           |    −3   |    **+1**  |        −1      |          0              |
| mem_role_reversal_retest        |    +4   |    +1      |     n/a        |       n/a               |
| mem_recency_fresh (≤30m)        |    +1   |    +1      |         0      |          0              |

**Operator's call points** (data on the table — no env change made):

1. **`mem_first_touch=+3` is falsified on P and BAND cohorts** in this
   corpus. First-touch turn rate is *lower*, not higher. Only OUTER_PIVOT
   shows the +2pp lift, which our rule scales to 0. The defaults were set
   from an August n=18 live sample; the corpus n=996 on P alone contradicts.
2. **`mem_test_number_3plus=−3`** is only mildly supported by
   OUTER_PIVOT (−1) and contradicted by P (+1). The "exhausted level"
   intuition doesn't survive the 33k-event scale.
3. **`mem_role_reversal_retest=+4`** is directionally correct on P (+1
   corpus) but 4× weaker; on OUTER/BAND cohorts it cannot be tested on this
   corpus (side-asymmetric emission).
4. **`mem_recency_fresh=+1`** is confirmed on P (+1); flat on OUTER and BAND.

`SESSION_STRUCT` (PDH/PDL/session-H-L) and `ROUND` cohorts sit outside this
corpus's schema — the DYNAMIC-exemption ruling extended to them means the
weight defaults there are untested by anything in `/tmp/coincidence_ext_v2`.

---

## STEP 2 — Two-bounce rescope: 27-cell grid

**Inputs:** `/tmp/two_bounce_per_day.json` (818 days, 683 weekday days,
audited detector from `/tmp/two_bounce_days.py`, published in
`reports-public/two_bounce_days_20260831.md`). Denominator for
days-per-month: **32 months** in corpus (2024-01 → 2026-08).

**Anchor sets:**
- **A_full** — any tracked level
- **B_structural** — outer pivots (R1-3/S1-3) + PDH/PDL + session H/L
- **C_struct+BB** — B AND at least one BB anchor in the same episode
  **CAVEAT:** this is *co-occurrence* within the same 25p bounce chain,
  not the strict **≤5p co-location** the operator asked for. Recovering
  strict co-location requires re-running the detector with per-anchor
  prices attached (bounce records store only `outer_anchor`). Flagged.

**Session filters** (`extreme_ts` hour on the shifted UTC clock):
- **S_any** — any hour
- **S_both_LONorNY** — both bounces have `extreme_ts` in 07:00-20:59
- **S_LONandNY** — ≥1 bounce with `extreme_ts` in 07:00-11:59 (LON)
  AND ≥1 in 12:00-20:59 (NY)

**DST caveat (from STEP 0):** EDT-months (Apr-Oct) have shifted-clock =
UTC+1h, which can move a bounce whose true-UTC extreme is at 06:00 (Asia
tail) into the LON bucket, or a true-UTC 11:00 (LON tail) into NY. Broad
9-hour NY window and 5-hour LON window tolerate this, but session filters
counting exactly "one in LON and one in NY" will pick up a small number of
false-positive/false-negative days in EDT months. The exact number is
below the precision of the 8-12/month target.

### The 27-cell surface (days/month over 32 months)

| threshold | anchor         | S_any            | S_both LON∪NY    | S_LON AND NY     |
|:---------:|:---------------|:-----------------|:-----------------|:-----------------|
|    25p    | A_full         | 595d (18.59/mo)  | 247d ( 7.72/mo)  | 409d (12.78/mo)  |
|    25p    | B_structural   | 549d (17.16/mo)  | 252d ( 7.88/mo)  | **323d (10.09/mo)** |
|    25p    | C_struct+BB    | 545d (17.03/mo)  | 256d ( 8.00/mo)  | **317d ( 9.91/mo)** |
|    35p    | A_full         | 386d (12.06/mo)  | 209d ( 6.53/mo)  | 211d ( 6.59/mo)  |
|    35p    | B_structural   | **315d ( 9.84/mo)** | 184d ( 5.75/mo)  | 160d ( 5.00/mo)  |
|    35p    | C_struct+BB    | **304d ( 9.50/mo)** | 178d ( 5.56/mo)  | 153d ( 4.78/mo)  |
|    45p    | A_full         | 200d ( 6.25/mo)  | 123d ( 3.84/mo)  |  96d ( 3.00/mo)  |
|    45p    | B_structural   | 142d ( 4.44/mo)  |  91d ( 2.84/mo)  |  62d ( 1.94/mo)  |
|    45p    | C_struct+BB    | 137d ( 4.28/mo)  |  87d ( 2.72/mo)  |  61d ( 1.91/mo)  |

Cells landing in the 8-12/month band are bold.

### Year stability for 8-12/month cells

| cell | overall | 2024 (12 mo) | 2025 (12 mo) | 2026 (8 mo) |
|:-----|--------:|-------------:|-------------:|------------:|
| T=25 B_structural S_LONandNY   | 10.09/mo | 10.08/mo (n=121) | 12.08/mo (n=145) |  7.12/mo (n=57) |
| T=25 C_struct+BB S_LONandNY    |  9.91/mo | 10.08/mo (n=121) | 11.83/mo (n=142) |  6.75/mo (n=54) |
| T=25 C_struct+BB S_both_LONorNY|  8.00/mo |  9.83/mo (n=118) |  8.33/mo (n=100) |  4.75/mo (n=38) |
| T=35 B_structural S_any        |  9.84/mo |  8.17/mo (n=98)  | 12.08/mo (n=145) |  9.00/mo (n=72) |
| T=35 C_struct+BB S_any         |  9.50/mo |  8.08/mo (n=97)  | 11.42/mo (n=137) |  8.75/mo (n=70) |

**Year-stability read:** **None** of the 8-12/mo cells is truly stable
year-over-year. The T=25 S_LONandNY cells sit at 10-12/mo in 2024-25 but
collapse to 6-7/mo in 2026 (partial year, Jan-Aug). The T=35 S_any cells
range 8-12/mo across the three years, best 3-year spread of the group.
**Honest note per the operator's spec:** no cell is *stable* near 10/month
— every candidate has a 2× spread across years, or a monotone drop as the
detector picks up bar-source changes (IG live from 2026-03-23 has tighter
tick density than the HistData rebuild; more granular = fewer 25p bounces
qualifying because the 5m aggregation is different).

### TWO cells nearest 10/month (full date lists)

Both cells tie at |Δ|=0.09 from 10/mo.

#### Cell A — T=25p, B_structural, S_LONandNY — 323 days, 10.09/mo

Full list (weekday tag in parens):

2024-01-02(Tue), 2024-01-03(Wed), 2024-01-04(Thu), 2024-01-05(Fri), 2024-01-08(Mon), 2024-01-09(Tue),
2024-01-11(Thu), 2024-01-12(Fri), 2024-01-17(Wed), 2024-01-18(Thu), 2024-01-19(Fri), 2024-01-22(Mon),
2024-01-23(Tue), 2024-01-26(Fri), 2024-01-31(Wed), 2024-02-01(Thu), 2024-02-05(Mon), 2024-02-12(Mon),
2024-02-14(Wed), 2024-02-16(Fri), 2024-02-22(Thu), 2024-02-23(Fri), 2024-02-27(Tue), 2024-02-29(Thu),
2024-03-01(Fri), 2024-03-06(Wed), 2024-03-08(Fri), 2024-03-14(Thu), 2024-03-20(Wed), 2024-03-22(Fri),
2024-03-27(Wed), 2024-03-28(Thu), 2024-04-02(Tue), 2024-04-03(Wed), 2024-04-09(Tue), 2024-04-11(Thu),
2024-04-15(Mon), 2024-04-17(Wed), 2024-04-26(Fri), 2024-04-29(Mon), 2024-05-01(Wed), 2024-05-02(Thu),
2024-05-08(Wed), 2024-05-14(Tue), 2024-05-15(Wed), 2024-05-22(Wed), 2024-05-23(Thu), 2024-05-28(Tue),
2024-05-30(Thu), 2024-05-31(Fri), 2024-06-04(Tue), 2024-06-10(Mon), 2024-06-11(Tue), 2024-06-13(Thu),
2024-06-21(Fri), 2024-06-24(Mon), 2024-06-27(Thu), 2024-07-05(Fri), 2024-07-12(Fri), 2024-07-16(Tue),
2024-07-29(Mon), 2024-07-31(Wed), 2024-08-02(Fri), 2024-08-05(Mon), 2024-08-07(Wed), 2024-08-08(Thu),
2024-08-14(Wed), 2024-08-16(Fri), 2024-08-21(Wed), 2024-08-22(Thu), 2024-08-28(Wed), 2024-08-29(Thu),
2024-08-30(Fri), 2024-09-03(Tue), 2024-09-04(Wed), 2024-09-05(Thu), 2024-09-06(Fri), 2024-09-09(Mon),
2024-09-12(Thu), 2024-09-13(Fri), 2024-09-20(Fri), 2024-09-26(Thu), 2024-09-27(Fri), 2024-09-30(Mon),
2024-10-02(Wed), 2024-10-07(Mon), 2024-10-08(Tue), 2024-10-09(Wed), 2024-10-11(Fri), 2024-10-15(Tue),
2024-10-18(Fri), 2024-10-22(Tue), 2024-10-23(Wed), 2024-10-25(Fri), 2024-10-30(Wed), 2024-10-31(Thu),
2024-11-04(Mon), 2024-11-06(Wed), 2024-11-07(Thu), 2024-11-08(Fri), 2024-11-12(Tue), 2024-11-13(Wed),
2024-11-14(Thu), 2024-11-15(Fri), 2024-11-20(Wed), 2024-11-22(Fri), 2024-11-25(Mon), 2024-11-26(Tue),
2024-11-29(Fri), 2024-12-02(Mon), 2024-12-03(Tue), 2024-12-04(Wed), 2024-12-11(Wed), 2024-12-12(Thu),
2024-12-16(Mon), 2024-12-18(Wed), 2024-12-19(Thu), 2024-12-24(Tue), 2024-12-27(Fri), 2024-12-30(Mon),
2024-12-31(Tue), 2025-01-07(Tue), 2025-01-08(Wed), 2025-01-09(Thu), 2025-01-13(Mon), 2025-01-14(Tue),
2025-01-15(Wed), 2025-01-17(Fri), 2025-01-20(Mon), 2025-01-21(Tue), 2025-01-23(Thu), 2025-01-27(Mon),
2025-01-28(Tue), 2025-01-29(Wed), 2025-01-30(Thu), 2025-01-31(Fri), 2025-02-04(Tue), 2025-02-11(Tue),
2025-02-12(Wed), 2025-02-13(Thu), 2025-02-18(Tue), 2025-02-19(Wed), 2025-02-21(Fri), 2025-02-25(Tue),
2025-02-27(Thu), 2025-03-03(Mon), 2025-03-06(Thu), 2025-03-07(Fri), 2025-03-12(Wed), 2025-03-19(Wed),
2025-03-20(Thu), 2025-03-24(Mon), 2025-03-25(Tue), 2025-03-27(Thu), 2025-03-31(Mon), 2025-04-01(Tue),
2025-04-02(Wed), 2025-04-03(Thu), 2025-04-07(Mon), 2025-04-08(Tue), 2025-04-09(Wed), 2025-04-10(Thu),
2025-04-11(Fri), 2025-04-15(Tue), 2025-04-16(Wed), 2025-04-17(Thu), 2025-04-23(Wed), 2025-04-24(Thu),
2025-04-28(Mon), 2025-04-29(Tue), 2025-04-30(Wed), 2025-05-01(Thu), 2025-05-05(Mon), 2025-05-06(Tue),
2025-05-07(Wed), 2025-05-12(Mon), 2025-05-13(Tue), 2025-05-16(Fri), 2025-05-19(Mon), 2025-05-20(Tue),
2025-05-21(Wed), 2025-05-27(Tue), 2025-05-28(Wed), 2025-06-03(Tue), 2025-06-09(Mon), 2025-06-10(Tue),
2025-06-11(Wed), 2025-06-12(Thu), 2025-06-13(Fri), 2025-06-16(Mon), 2025-06-17(Tue), 2025-06-18(Wed),
2025-06-19(Thu), 2025-06-20(Fri), 2025-06-24(Tue), 2025-06-25(Wed), 2025-06-27(Fri), 2025-07-01(Tue),
2025-07-03(Thu), 2025-07-07(Mon), 2025-07-08(Tue), 2025-07-10(Thu), 2025-07-16(Wed), 2025-07-17(Thu),
2025-07-18(Fri), 2025-07-21(Mon), 2025-07-22(Tue), 2025-07-23(Wed), 2025-07-28(Mon), 2025-07-29(Tue),
2025-07-30(Wed), 2025-07-31(Thu), 2025-08-04(Mon), 2025-08-05(Tue), 2025-08-06(Wed), 2025-08-07(Thu),
2025-08-08(Fri), 2025-08-11(Mon), 2025-08-12(Tue), 2025-08-27(Wed), 2025-08-28(Thu), 2025-09-02(Tue),
2025-09-03(Wed), 2025-09-10(Wed), 2025-09-11(Thu), 2025-09-12(Fri), 2025-09-15(Mon), 2025-09-17(Wed),
2025-09-18(Thu), 2025-09-23(Tue), 2025-09-26(Fri), 2025-09-30(Tue), 2025-10-01(Wed), 2025-10-02(Thu),
2025-10-06(Mon), 2025-10-08(Wed), 2025-10-09(Thu), 2025-10-10(Fri), 2025-10-13(Mon), 2025-10-15(Wed),
2025-10-16(Thu), 2025-10-17(Fri), 2025-10-24(Fri), 2025-10-31(Fri), 2025-11-05(Wed), 2025-11-11(Tue),
2025-11-12(Wed), 2025-11-13(Thu), 2025-11-14(Fri), 2025-11-17(Mon), 2025-11-18(Tue), 2025-11-20(Thu),
2025-11-21(Fri), 2025-11-28(Fri), 2025-12-01(Mon), 2025-12-02(Tue), 2025-12-03(Wed), 2025-12-04(Thu),
2025-12-05(Fri), 2025-12-09(Tue), 2025-12-10(Wed), 2025-12-11(Thu), 2025-12-17(Wed), 2025-12-18(Thu),
2025-12-30(Tue), 2025-12-31(Wed), 2026-01-13(Tue), 2026-01-20(Tue), 2026-01-21(Wed), 2026-01-26(Mon),
2026-01-27(Tue), 2026-01-28(Wed), 2026-01-30(Fri), 2026-02-09(Mon), 2026-02-10(Tue), 2026-02-20(Fri),
2026-02-24(Tue), 2026-02-26(Thu), 2026-03-02(Mon), 2026-03-04(Wed), 2026-03-05(Thu), 2026-03-06(Fri),
2026-03-10(Tue), 2026-03-11(Wed), 2026-03-12(Thu), 2026-03-13(Fri), 2026-03-16(Mon), 2026-03-17(Tue),
2026-03-19(Thu), 2026-03-20(Fri), 2026-03-23(Mon), 2026-04-02(Thu), 2026-04-06(Mon), 2026-04-08(Wed),
2026-04-10(Fri), 2026-04-21(Tue), 2026-04-22(Wed), 2026-05-05(Tue), 2026-05-12(Tue), 2026-05-18(Mon),
2026-05-20(Wed), 2026-05-21(Thu), 2026-05-22(Fri), 2026-05-26(Tue), 2026-06-04(Thu), 2026-06-05(Fri),
2026-06-11(Thu), 2026-06-16(Tue), 2026-06-18(Thu), 2026-06-19(Fri), 2026-06-22(Mon), 2026-06-23(Tue),
2026-06-24(Wed), 2026-06-29(Mon), 2026-06-30(Tue), 2026-07-15(Wed), 2026-07-16(Thu), 2026-07-20(Mon),
2026-07-21(Tue), 2026-07-23(Thu), 2026-07-24(Fri), 2026-07-28(Tue), 2026-08-07(Fri).

#### Cell B — T=25p, C_struct+BB, S_LONandNY — 317 days, 9.91/mo

**Cell B is a strict subset of Cell A.** The full 317-date list = Cell A
minus exactly these six days (the STRUCTURAL bounces on these days did
not co-occur with a BB anchor in the same 25p episode):

- 2025-02-25(Tue)
- 2025-06-16(Mon)
- 2025-07-21(Mon)
- 2026-01-30(Fri)
- 2026-02-24(Tue)
- 2026-06-24(Wed)

Full raw list dumped to `/tmp/step2_grid_out.json` → `near10[1].dates`.

### News/holiday joins for the two near-10 cells (base rate now informative)

Denominator: 595 tagged days (the audited ≥2 cohort from the prior
report). Base rates: `none 53.6%`, `ON 19.7%`, `DAY_BEFORE 16.0%`,
`DAY_AFTER 10.8%`; holiday 3.4%; top cats NFP 5.2%, CPI_US 5.2%,
CPI_UK 4.4%, FOMC 3.5%, BoE 3.2%.

**Cell A (T=25 B_structural S_LONandNY, n=323):**
- rel: none 52.9% · ON 19.5% · DAY_BEFORE 16.7% · DAY_AFTER 10.8%
- cats: CPI_US 5.6% · CPI_UK 5.6% · FOMC 4.3% · NFP 3.4% · BoE 3.1%
- holidays: 6 (1.9%)

**Cell B (T=25 C_struct+BB S_LONandNY, n=317):**
- rel: none 52.1% · ON 19.9% · DAY_BEFORE 17.0% · DAY_AFTER 11.0%
- cats: CPI_US 5.7% · CPI_UK 5.7% · FOMC 4.4% · NFP 3.5% · BoE 3.2%
- holidays: 6 (1.9%)

**Read:** the near-10 cells are indistinguishable from base rate on all
news/holiday dimensions. **News is not overrepresented in these cells** —
the LON-AND-NY filter is picking up ordinary two-session days, not
event-driven days. The operator's original ~10/month intuition, if it was
a "special news-driven days" mental model, is falsified by this join.

### Honest note on the ~10/month target

- The T=25 S_LONandNY cells hit 10/mo overall but are **not stable**: they
  drop from 10-12/mo (2024-25) to 6-7/mo (2026 partial), likely
  bar-source-mediated.
- The T=35 S_any cells span 8-12/mo across years with a smaller relative
  spread but no cell is *stable* near 10.
- **The 27-cell grid does not contain a cell that is both ~10/mo and
  year-stable.** If the operator's ~10/month is meant to be a stable
  reference cohort, the definition needs an additional dimension the grid
  does not vary (e.g. minimum day-range, session-h/l vs pivot-only anchor
  narrowing, or an explicit news exclusion).

---

## Appendix — provenance and file paths

- Corpus events: `/tmp/coincidence_ext_v2_events.json` (33,252 events, 674 full-session days)
- Per-day bounce records: `/tmp/two_bounce_per_day.json` (818 days)
- Bounce news/holiday tags: `/tmp/two_bounce_tags.json` (595 ≥2 cohort days)
- Grid output json: `/tmp/step2_grid_out.json` (surface + near-10 date lists)
- Prior audit: `reports-public/two_bounce_days_20260831.md`

**Scripts (all under `/tmp/`, no live-path changes):**
`dst_verify.py`, `dst_verify2.py`, `dst_verify3.py`, `step1_weights.py`,
`step2_grid.py`.
