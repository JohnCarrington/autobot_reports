# Entry-quality follow-up study — scoping document

**Trigger:** 2026-11-03 anchor-correction counterfactual exposed a strategy-
side signal that cannot be seen while the executor is broken. It must be
investigated AFTER the executor is corrected and running cleanly, not
during the same change.

**Scope:** READ-ONLY research. No code changes. No deployment. No
operator action required beyond scheduling the investigation.

---

## 1. What the data already shows

Simulating all 24 pending shadow scenarios (Oct 23 → Nov 3) with the
corrected anchor and the existing dedup / lifecycle rules:

| Metric | Value |
|---|---|
| Scenarios that would have opened | 12 of 24 |
| Target hits | 6 |
| Stop hits | 6 |
| Win rate | 50 % |
| Gross pips (mid-close fills, no cost deduction) | **−40.3** |
| Mean reward on winners | +13.95 pips |
| Mean loss on stops | −20.67 pips |
| Average R:R realised | ~0.67 |

Per-trade breakdown (reproduced from the investigation report, Section
D):

| Scenario | Dir | Entry bar | Exit bar | Exit | Pips |
|---|---|---|---|---|---|
| `68d2156778092682` | SELL | 2026-10-27 15:45 | 2026-10-28 06:50 | TARGET | +17.4 |
| `87f92fcab23db555` | SELL | 2026-10-27 09:10 | 2026-10-27 12:05 | STOP | −12.0 |
| `ab10a93503c23daf` | SELL | 2026-10-26 07:05 | 2026-10-26 07:20 | TARGET | +5.1 |
| `1fe0a9594c0a28b5` | SELL | 2026-10-28 08:00 | 2026-10-28 13:40 | STOP | −14.7 |
| `9fb58109c4dc34c2` | SELL | 2026-10-29 09:20 | 2026-10-29 10:10 | STOP | −19.2 |
| `a6dedea761fa78a0` | SELL | 2026-10-29 13:15 | 2026-10-29 14:05 | STOP | −25.8 |
| `bd7fbcce36c2c777` | SELL | 2026-10-29 13:15 | 2026-10-29 14:05 | STOP | −25.8 |
| `cd35a44360265147` | SELL | 2026-10-30 12:40 | 2026-10-30 13:45 | TARGET | +18.5 |
| `31982bff857d57e3` | BUY  | 2026-10-30 09:35 | 2026-10-30 12:50 | STOP | −26.5 |
| `a12b3c0199d9e753` | BUY  | 2026-10-30 08:00 | 2026-11-02 08:55 | TARGET | +29.2 |
| `7498ece3f17ffbfa` | BUY  | 2026-11-02 07:40 | 2026-11-02 08:30 | TARGET | +12.7 |
| `e1c03cad64fa6574` | BUY  | 2026-11-03 13:25 | 2026-11-03 13:30 | TARGET | +0.8 |

---

## 2. Hypotheses to investigate (prioritised)

### H1 (highest) — Scenario-level targets are chosen too close to entry

Multiple scenarios chose targets that sit **within 5 pips of entry** when
the stop is 15–20 pips. Example: `e1c03cad64fa6574` rev=22 proposes
BUY entry 13415.02 / stop 13402.4 / target 13427.15 — reward 12.1 pips
vs risk 12.6 pips (R:R≈0.96). Rev=7 of the same scenario proposes
entry 13425.18 / target 13427.15 — reward **1.97 pips** with the same
20-pip stop (R:R≈0.1). After a 1-pip half-spread per side, that trade
cannot be positive-expectancy no matter how well-timed it is.

Deliverable: histogram of (reward / risk) and (reward / spread) across
the full scenarios_shadow.jsonl journal; identify whether the thin-TP
pattern is systemic or driven by a few bars where the AI picks the
nearest structural level.

### H2 — Breakout entries at the top of the move, retest entries missing

The brief for 2026-11-03 flagged late-entry behaviour as "chasing
price". The timeline for `e1c03cad64fa6574` shows this clearly: the
first BUY revisions (rev=5-7 at 09:31-09:51) placed entry at
13425–13427 (above resistance). As price retraced, revisions 19-28
dropped entry to 13414-13417. The scenario kept chasing without
committing to one level. First-fire executed at the HIGH of the move
(13:25 bar close 13426.35), not at the retest low (12:40 bar close
13407.95).

Deliverable: for every scenario that opened in the counterfactual, map
the entry bar's position within the scenario's own min/max price
excursion (0 % = low, 100 % = high). Hypothesis: BUY entries cluster
near 80-100 %, SELL entries near 0-20 %, i.e. systematic "sell the low
/ buy the high".

### H3 — Target distance from entry does not reflect scenario volatility

Several scenarios share the identical target `13427.15` (e.g. all BUY
revs 5-29 of `e1c03cad64fa6574`) even though entry moved 13 pips over
3 h. The target appears to be anchored to a structural level
(SWING_H), but the risk–reward is not re-evaluated as entry drifts.

Deliverable: for each scenario where target is fixed across
revisions, check whether R:R recomputed over revisions falls below
1.0 at any point; count how many of those revisions were still
published VALID.

### H4 — Direction-flip latency

`e1c03cad64fa6574` opened as SELL (rev=0-4) at 08:21-09:01, then
flipped to BUY (rev=5+) at 09:31. The flip followed ~1 h of price
holding above the SELL stop. Was the flip triggered by structure, by
price action, or by a surrender rule? If a surrender rule, is it
reactive (chase) or principled (NMS flip)?

Deliverable: for every scenario that flipped direction, identify what
upstream signal preceded the flip (NMS state, publication-decision
flag, bar-close level breach, time-based rule).

### H5 — Session-of-day effect

Six of the 12 counterfactual trades opened in the London-open window
(07:00-10:00 UTC), six in or after the NY-open window (12:30-14:30).
Pip P&L split by session may reveal time-of-day effects currently
hidden by the aggregate.

### H6 — Scenario cohort decay

Does the first revision of a scenario produce a better R:R trade than
late revisions, OR vice versa? Four of the 12 trades opened on the
first revision; three on rev=6 or rev=7; two on rev=1. Mean pips
by opening revision may inform a future "latest-revision wins" vs
"first-revision wins" dedup policy.

---

## 3. Non-goals

Explicitly **out of scope** for this follow-up:

- Any change to `scenario_reasoner.py`, `scenario_quality.py`,
  `scenario_recommendation.py` or `shadow_execution.py`.
- Any modification to NMS directional authority or EMA_PB / BB_BOUNCE
  gates.
- Any live-execution deployment.
- Rebuilding counterfactual pips with cost-model deduction (requires a
  separate IG spread + slippage calibration study).
- Judging the strategy as a whole from n=12. The post-correction
  shadow stream must accumulate at least 60-100 observations before
  methodology changes are considered.

---

## 4. Preconditions

- Executor correction (branch
  `correction/scenario-v2-shadow-exec-anchor-20261103`) deployed and
  running cleanly for **≥ 5 trading days**.
- Shadow positions journal (`shadow_positions.jsonl`) actively being
  populated by live sweeps — the follow-up uses that data, not the
  counterfactual replay.
- No concurrent methodology experiments running on
  `scenario_reasoner.py` (so the sample is one coherent cohort).

---

## 5. Suggested cadence

- **Week 1 after deploy** — accumulate live shadow fills; do not
  investigate.
- **Week 2** — run H1 (R:R histogram) on accumulated live data; cross-
  check against this document's n=12 counterfactual to see whether
  the pattern persists under live sampling.
- **Week 3+** — run H2–H6 only if H1 confirms a target-geometry
  problem.

---

## 6. Risk of not investigating

**Low in the short term.** The system is shadow-only; no capital is at
risk. The data is in the journal already and will keep accumulating.
**Material in the longer term:** if the methodology issue is real, any
future "shadow → live" promotion decision based on raw hit-rate or
raw gross-pip tally will be miscalibrated, because the R:R geometry
means a 50 % win rate is net-negative at current spread.

---

## 7. Memory handoff

When this follow-up is started, open with:
`project_gbpusd_scenario_v2_entry_quality_followup.md`.

Load-bearing references:

- `project_scenario_v2_waitfailure_20261029` — prior
  anchoring/breakout-chase pattern
- `project_gbpusd_news_trend_opportunity_20261024` — breakout-chase
  behaviour in a different cohort
- `project_scenario_v2_c3_staged_20261029` — scenario-lifecycle
  invariants; shadow dedup rules
- This document

**Not yet relevant** (keep the follow-up focused):
`project_dynamic_ig_min_stop_patches_20261028`,
`project_bb_bounce_tight_stop_falsified_20261028`,
`project_bb_bounce_retest_hypothesis_falsified_20261028`.
