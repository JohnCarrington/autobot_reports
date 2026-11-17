# Structural Trade Planner — recommendation lifecycle investigation (17 November 2026)

**Scope:** the inconsistencies seen on the dashboard's planner panel on 17 November 2026 (two SELL recommendations
on the same zone 1.32135–1.32199 with different outcomes, "NO RECOMMENDATION" while the forecast was bearish, and
"Tue 22:00 — NOT current").

**Evidence used:** the planner's own persisted files, read only, copied at 22:20 UTC to the development workspace
(`/home/autobot/worktrees/stp-dashboard-work/evidence/`):

- `data/planner/GBPUSD/recommendations.jsonl` (append-only lifecycle events and hourly analyses);
- `data/planner/GBPUSD/current.json` (state, last plan, recent recommendations);
- the stored 5-minute candles 20:10–22:25 UTC (`m5_2010_2225.txt`, chart = sell price).

Prices: the planner stores IG points (13213.5 = 1.32135). All times UTC (UK = GMT on 17 November).
No planner behaviour was changed in the course of this investigation.

## 1. What the records say

| Time (UTC) | Event | Id | Recorded reason |
|---|---|---|---|
| 20:24:13 | analysis | – | BEARISH, CORRECTION_ACTIVE, corrective reversal, SELL zone 13213.5–13219.9 (Major), primary 13200 |
| 20:24:13 | created → waiting | **STP-GBPUSD-20261117-2024-1** | Major zone (3 families) 4.1 pips away, PLAUSIBLE |
| 20:25:00 | active | …-2024-1 | the 20:20 5-minute candle reached the zone |
| 21:00:03 | analysis + supported | …-2024-1 | re-checked: the structural basis still holds |
| 22:00:00 | **completed** | …-2024-1 | price reached the primary destination 13200 (21:55 candle) after the zone |
| 22:00:02 | analysis | – | same plan: SELL zone 13213.5–13219.9, primary 13200 |
| 22:00:02 | created → waiting | **STP-GBPUSD-20261117-2200-2** | Major zone (3 families) **10.0 pips away**, PLAUSIBLE |
| 22:05:00 | **invalidated** | …-2200-2 | destination reached before entry: price reached 13200 (22:00 candle) without reaching the zone |

The 5-minute candles that decided each step (sell price):

| Candle | High | Low | Close | Rule applied (3-pip allowance, `rejection.near_level_within_pips`) |
|---|---|---|---|---|
| 20:20 | 1.32121 | 1.32086 | 1.32111 | high ≥ zone low 1.32135 − 3 pips (1.32105) → **zone interaction** (rec 1 ACTIVE) |
| 20:45 | 1.32153 | 1.32111 | 1.32129 | highest point: 1.8 pips inside the zone |
| 21:55 | 1.32073 | 1.32013 | 1.32035 | low ≤ primary 1.32000 + 3 pips (1.32030) → **destination interaction** (rec 1 COMPLETED) |
| 22:00 | 1.32018 | 1.31988 | 1.31990 | low ≤ 1.32030 → destination interaction (rec 2 INVALIDATED, never near its zone) |

## 2. Answers to the thirteen questions

1. **Different ids?** Yes: `STP-GBPUSD-20261117-2024-1` and `STP-GBPUSD-20261117-2200-2` (counter 1 and 2).
2. **Created:** 20:24:13 and 22:00:02 UTC.
3. **Structural evidence:** identical for both (the 22:00 analysis reproduced the 20:24 plan exactly): daily R1
   1.32135 (reference), daily swing low 1.32155 (former support, now resistance), hourly swing lows 1.32174,
   1.32198, 1.32199 and hourly swing high 1.32185; families higher-timeframe structure, pivot, structure; class Major.
   Primary destination 1.32000 (Major zone 1.31897–1.32000: 4-hour swing lows, daily pivot 1.31944, previous week low
   1.31999, round number 1.32000).
4. **Did price reach the entry zone?** Rec 1: yes — by the approved 3-pip touch rule at 20:20 (1.4 pips short of the
   zone's lower edge), and physically at 20:45 (1.8 pips inside). Rec 2: no — price was 12 to 15 pips below the zone (1.31988–1.32018 against the zone edge 1.32135)
   throughout its 3-minute life.
5. **Became active:** rec 1 at 20:25:00 (the 20:20–20:25 candle). Note: that candle **began before the recommendation
   was created** (20:24:13) and the touch may partly predate it. Rec 2 never became active.
6. **Primary destination reached?** Rec 1: yes at 21:55 (low 1.32013, within the 3-pip allowance of 1.32000 —
   price itself did not trade at 1.32000 until 22:00). Rec 2: the destination was touched by the very next candle
   (22:00), before its zone.
7. **Structural invalidation?** No zone break (no hourly close ≥ 1.32229) and no 4-hour structure break for either.
   Rec 2's INVALIDATED is the "destination reached before entry" rule, not a structural invalidation.
8. **Supersession:** not involved and correctly so. Rec 1 had already ended (COMPLETED at 22:00:00, in the 5-minute
   checks) before the 22:00:02 re-plan, so the re-plan found no live recommendation and issued a new one. Supersession
   only applies to a live recommendation.
9. **Why different outcomes with identical zones?** They are two separate forecasts issued at different moments with
   different prices relative to the plan. Rec 1 was issued 4.1 pips below the zone: price went up into the zone, then
   down to the destination — the forecast sequence played out (COMPLETED). Rec 2 was issued when price was 3.5 pips
   above the primary destination and already within its 3-pip touch range on the preceding candle; the destination
   was touched immediately, before any approach to the zone (INVALIDATED). Same zone, different situations — both
   classifications follow the approved rules.
10. **Why NO RECOMMENDATION?** Rec 2 was invalidated at 22:05. The planner only issues a recommendation at an hourly
    re-plan (D-21, adjustment 1), so until 23:00 there is no live recommendation even though the 22:00 plan still
    recommends a SELL. The old panel showed only the generic text "no recommendation" (the plan's
    `no_recommendation` field was empty because the plan *did* recommend), with no hint of why.
11. **Why "NOT current"?** `current.json` had `data_fresh: true` and `not_current_reasons: []`. The keeper sets
    `current = recommendation is not None and fresh and not reasons` (`planner/keeper.py` `run`) — it describes whether
    *a recommendation* is current (FC-08). With no recommendation it is always false. The panel printed it next to the
    analysis time as "· NOT current", which reads as "the analysis is out of date". The analysis was in fact current
    (the 22:00 analysis is the latest hourly one; the next was due at 23:00) and the data fresh.
12. **Internally consistent?** Yes. Every event is in time order; each id has exactly one terminal event; the
    `recent` list in `current.json` matches the history file; counters match; the zone and destination prices in the
    reasons match the stored plans.
13. **Incorrectly classified?** No recommendation was misclassified under the approved rules. Rec 2's quick
    invalidation comes from a mismatch between two approved rules (section 3, D-1).

## 3. Root causes, by category

| Category | Finding |
|---|---|
| **Correct behaviour, poorly presented** | (P-1) Two records with one zone are correct (separate ids, separate forecasts) but the panel listed them as two near-identical lines with no times. (P-2) "Destination reached" uses the approved 3-pip allowance; the wording "price reached 13200" can read as an exact touch (21:55 low was 1.32013). (P-3) Activation by the 3-pip allowance, not physical entry, is not stated. |
| **Dashboard interpretation defects** | (DI-1) "NOT current" displayed the recommendation's FC-08 currency flag as if it were the analysis's freshness. (DI-2) "NO RECOMMENDATION" gave no reason when the plan recommends but the last recommendation ended since the last analysis. (DI-3) Prices shown as IG points (13213.5–13219.9). |
| **Recommendation-history defects** | (H-1) When a recommendation ends, the keeper drops the full record; only the short summary in the "created" event survives — the original intermediate/extended destinations, invalidation conditions and structured evidence are lost. Fixed for the future by a reporting-only addition (`issued.jsonl`, section 5). The two 17 November records cannot be restored beyond their summary (the 22:00 full plan was saved in the evidence copy). (H-2) The planner persists only the levels inside the zones it considered, not its whole level map, so the chart can only draw those (documented limitation). |
| **Genuine planner lifecycle defect** | (D-1) **The guard against issuing at the destination and the touch rule disagree.** The planner already has a guard (`planner/assess.py`, `destination_first_applies`): the "destination reached before entry" rule applies only if the primary destination's edge is more than 3 pips beyond the **current price** (the last close). The touch rule that then fires it (`zones.interacts`) uses the candle's **extreme** with a 3-pip allowance. At 22:00:02 price was 1.32035, 3.5 pips above 1.32000, so the guard switched the rule on (by 0.5 pip) — yet the 21:55 candle's low (1.32013) was already inside the touch allowance, and the next candle (low 1.31988) fired it. A recommendation issued a few pips outside the guard is therefore likely to be invalidated by ordinary 5-minute noise, which is what happened to rec 2. (At 23:00 the same zone was issued again as `…-2300-3` with price 1.32029: inside the guard, so the rule is off and that recommendation waits for its zone — see the follow-up.) (D-2, minor) The activation candle can be one that started before creation (20:20 candle vs 20:24:13 creation). |
| **Data freshness issues** | None. Data was fresh (`data_fresh: true`, the planner ran every 5 minutes, the analysis was the latest hourly one). |

## 4. Proposed planner corrections (NOT implemented — need the owner's approval)

These change planner decisions/recording and are outside the dashboard work's authority:

- **D-1 (recommended):** make the guard and the touch rule agree: decide `destination_first_applies` with the
  same test the 5-minute check uses — the rule applies only if the latest finished 5-minute candle does **not**
  already interact with the primary destination zone (`zones.interacts`), optionally with a margin of one typical
  5-minute range. Alternatively, do not issue a recommendation at all while price is within the touch allowance of its
  primary destination (record `no_recommendation = "price is already at the primary destination"`). A test
  reproducing 17 November 22:00 (close 1.32035, 21:55 low 1.32013, destination 1.32000) must not produce an
  immediate "destination reached before entry".
- **D-2 (optional):** at issue, apply the zone check only to 5-minute candles that *start* at or after the creation
  time, or record the activation as "touch began before creation". The dashboard already flags this case.
- **H-2 (optional, reporting only):** persist the plan's structured level map in `last_plan` so the chart can draw
  every planner level, not only those inside considered zones.

## 5. What the dashboard work changed in response (reporting/presentation only)

- The STP tab shows freshness from the planner's own timestamps and rules (CURRENT / ANALYSIS OVERDUE / STALE DATA /
  PLANNER NOT RUNNING / MARKET CLOSED / PLANNER UNAVAILABLE) and keeps the recommendation's FC-08 currency separate (DI-1).
- "No recommendation" is explained from recorded reasons: A (direction but no valid entry — the plan's reason),
  B (no direction), C (unavailable/stale), D (the last analysis's recommendation has ended; next chance at the next
  hourly analysis — with the ended recommendation's id, status and recorded reason) (DI-2).
- Prices in GBP/USD notation everywhere (DI-3); history one row per id with times and reasons (P-1).
- The evaluation and the recommendation view flag "issued with price already at the primary destination" (D-1) and
  "activation candle began before creation" (D-2) as observations, without re-deciding anything.
- `planner/keeper.py`: one reporting-only addition — each new recommendation is also written in full to
  `issued.jsonl` (append-only, separate file, failure-proof; the lifecycle file and every decision unchanged) (H-1).

## 6. Follow-up observation (23:00 UTC)

At 23:00:03 the planner issued `STP-GBPUSD-20261117-2300-3`: the same zone 1.32135–1.32199 and primary 1.32000,
11.9 pips below the zone, price 1.32029. Its `destination_first_applies` is **false** (price within 3 pips of the
destination), so the 23:00 candle (low 1.32008, inside the touch allowance) did **not** invalidate it; at 23:05 it was
WAITING. This confirms the guard exists and works when price is inside it, and that rec 2 was a boundary case
(D-1). Note the consequence for rec 3: with the destination rule off, it can only end by reaching its zone and then
the destination, a confirmed break, a direction change, supersession or the evidence changing. Evidence copy:
`evidence/recommendations_20261117T2306Z.jsonl`.
