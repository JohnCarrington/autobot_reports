# Rejection-Family Census — 2026-09-07 / 2026-09-08

Read-only census. No code changes. Source of truth:
`logs/qm_candidates.jsonl` (state chain, peak stamped confidence, factor
breakdown) cross-referenced with `logs/qm_pick_alerts_seen.jsonl` (what
actually alerted) and `logs/qm_join.jsonl` (V1↔V2 verdict snapshots).

Scope: every candidate whose state chain entered
`{VELOCITY_REJECTION, REJECTION_CANDIDATE, REJECTION_CONFIRMED,
ENTRY_ARMED}` via the rejection path on 2026-09-07 or 2026-09-08.
Candidate snapshots deduped by `(symbol, zone_center, opened_at)`;
"peak" = max `confidence_score` across snapshots.

Alerting rules read (`qm_pick_alerts.maybe_send_pick_alert`):
- actionable states = `{REVERSAL_CANDIDATE, REJECTION_CONFIRMED, ENTRY_ARMED}`
- floor: `QM_ALERT_FLOOR` (default 7)
- freshness: bar_ts within `QM_ALERT_MAX_AGE_MIN` (default 15 min)
- dedup: `(opened_at, dir, session)` **AND** `(round(zone,1), dir, UTC-date)`

---

## 1. Rejection-family candidates — per candidate

Total unique rejection-family candidates in window: **6**.
Peak stamped score for **all 6 = ≥ floor (7)**. Alerted: 3 of 6.
The 3 not-alerted are all zone-day dedup blocks; none were killed by
the floor, freshness, hours, or "never reached actionable state".

| # | UTC time (first rej entry) | Sym | Zone | Dir | Chain | Peak score | Factor breakdown (peak) | Alerted? | If not — reason |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-07 08:35 | EURUSD | 11632.9 | SELL | APPR → EXTR → SWEEP → **REJ_CAND(velrej) → REJ_CONF(velrej_score=10 very_strong) → ENTRY_ARMED(SELL_from_rejection_geometry)** | **10 (very_strong)** | level_swept=2, close_back_through=3, m5_structure_shift=3, close_inside_bb=2, velocity_rejection=0 | **YES — alerted 08:40:00.52Z** | — |
| 2 | 2026-09-08 06:20 | GBPUSD | 13544.6 | SELL | APPR → EXTR → SWEEP → **REJ_CAND(REJECTING) → REJ_CONF → ENTRY_ARMED** | **10 (very_strong)** | level_swept=2, close_back_through=3, m5_structure_shift=3, close_inside_bb=2 | **NO** | **zone-day dedup**: prior alert 06:00:00.65Z for opened_at 05:55Z, same zone 13544.6, same dir SELL, same UTC date (that earlier alert was a REVERSAL_CANDIDATE conf=10 on the same zone) |
| 3 | 2026-09-08 09:40 | GBPUSD | 13528.1 | BUY  | APPR → EXTR → SWEEP → **REJ_CAND(REJECTING)** → LEVEL_ACCEPTED → **REJ_CONF → ENTRY_ARMED** | **13 (very_strong)** | level_swept=2, close_back_through=3, m5_structure_shift=3, close_inside_bb=2, velocity_rejection=0, **mem_first_touch=3** | **YES — alerted 11:20:00.61Z** (stamped 11:15Z after memory-bumped re-arm) | — |
| 4 | 2026-09-08 11:55 | GBPUSD | 13544.6 | BUY  | EXTR → SWEEP → **REJ_CAND(VELOCITY_REJECTION) → REJ_CONF(velrej_score=10) → ENTRY_ARMED** | **10 (very_strong)** | level_swept=2, close_back_through=3, m5_structure_shift=3, close_inside_bb=2, velocity_rejection=0 | **YES — alerted 12:00:00.94Z** | — |
| 5 | 2026-09-08 14:20 | GBPUSD | 13551.6 | BUY  | EXTR → SWEEP → **REJ_CAND(VELOCITY_REJECTION) → REJ_CONF(velrej_score=10) → ENTRY_ARMED** | **10 (very_strong)** | level_swept=2, close_back_through=3, m5_structure_shift=3, close_inside_bb=2, velocity_rejection=0 | **NO** | **zone-day dedup**: prior alert 13:30:00.53Z for opened_at 13:25Z, same zone 13551.6, dir BUY, UTC date 09-08 (that earlier alert was a §16-retest REVERSAL_CANDIDATE conf=12) |
| 6 | 2026-09-08 15:30 | GBPUSD | 13544.6 | SELL | APPR → EXTR → SWEEP → **REJ_CAND(VELOCITY_REJECTION) → REJ_CONF(velrej_score=10) → ENTRY_ARMED** | **10 (very_strong)** | level_swept=2, close_back_through=3, m5_structure_shift=3, close_inside_bb=2, velocity_rejection=0 | **NO** | **zone-day dedup**: prior alert 06:00:00.65Z for opened_at 05:55Z, same zone 13544.6, dir SELL, UTC date 09-08 (same as blocker for candidate #2) |

Notes on the chain notation:
- The `velrej` cause label = `velocity_rejection_walk_through` (SWEEP → REJ_CAND
  triggered by same-bar sweep-and-reclaim), followed by `velocity_rejection_score=N(band)_side=X`
  when scored into REJ_CONF.
- The `REJECTING` cause label = the classic two-consecutive-REJECTING-bars path.
- Candidate #3 walked through LEVEL_ACCEPTED then re-armed inside the level
  (rejection path off memory), which is why its peak score is 13 (=10 base +
  3 from `mem_first_touch`).
- Candidates #4 and #5 skipped APPROACHING_ZONE because the same-bar
  VELOCITY_REJECTION walk-through logic backfills EXTREME_REACHED → SWEEP
  → REJ_CAND → REJ_CONF on one bar.

---

## 2. Score distribution — rejection vs continuation family (same window)

Continuation-family = candidates whose peak actionable transition on
2026-09-07 or 2026-09-08 was into `REVERSAL_CANDIDATE` (the §16-retest /
accepted-level continuation entry) or `CONTINUATION_WATCH`, and which
did NOT also progress through the rejection chain on the same window.
Peak = max `confidence_score` across all snapshots of that candidate.

Unique rejection candidates: **6**. Unique continuation candidates: **7**.

| Bucket | Rejection family (n=6) | Continuation family (n=7) |
|---|---|---|
| < floor (0–6) | 0 | 0 |
| 7–8 | 0 | 0 |
| 9–11 | **5** (all conf=10) | **3** (conf 10, 10, 11) |
| 12+ | **1** (conf=13, mem_first_touch bump) | **4** (conf 12, 12, 12, 15) |

Full list of peak scores:

- **Rejection family**: 10, 10, 10, 10, 10, 13 — median 10, max 13.
- **Continuation family**: 10, 10, 11, 12, 12, 12, 15 — median 12, max 15.
  - GBPUSD 13533.68 opened 09-07 08:35 → 12 (REVERSAL_CANDIDATE)
  - GBPUSD 13526.17 opened 09-07 10:15 → 15 (REVERSAL_CANDIDATE, highest in window)
  - GBPUSD 13544.60 opened 09-08 05:55 → 10 (REVERSAL_CANDIDATE — the alert that later blocked rejection candidates #2 and #6)
  - EURUSD 11621.93 opened 09-08 11:40 → 11 (REVERSAL_CANDIDATE)
  - GBPUSD 13544.60 opened 09-08 12:25 → 12 (REVERSAL_CANDIDATE)
  - GBPUSD 13551.60 opened 09-08 13:25 → 12 (REVERSAL_CANDIDATE — the alert that later blocked rejection candidate #5)
  - GBPUSD 13551.60 opened 09-08 15:30 → 10 (REVERSAL_CANDIDATE)

For context: 57 unique candidates touched a transition on the two-day
window; 42 of the 57 never crossed into a scored state (peak conf=0),
15 were scored. All 15 scored candidates cleared the floor of 7.

---

## 3. What stopped the un-alerted candidates

Every un-alerted rejection candidate was killed by the **zone-day
dedup key** `(round(zone,1), dir, UTC-date)`, not by floor / freshness /
hours / state.

- **#2 (13544.6 SELL 09-08)** and **#6 (13544.6 SELL 09-08)** both lost to
  the 06:00Z REVERSAL_CANDIDATE alert (opened_at 05:55Z, conf=10) on the
  same zone/dir/day. That earliest alert on the day is a continuation-
  family fire; the two rejection-family fires on the same zone later in
  the day are locked out.
- **#5 (13551.6 BUY 09-08)** lost to the 13:30Z §16-retest REVERSAL_CANDIDATE
  alert (opened_at 13:25Z, conf=12) on the same zone/dir/day.

None of the six candidates were suppressed by:
- freshness ceiling (stamped_at was always ≤ 5 min after the relevant bar);
- alert floor (all six ≥ 7);
- never reaching an actionable state (all six reached ENTRY_ARMED or
  REJ_CONF at least once);
- entry-hours block (all six landed in London or Asia trading hours
  that are enabled).

---

## 4. Provenance / method

- Candidate universe: `logs/qm_candidates.jsonl` filtered to snapshots
  whose transitions include a target-date entry into
  `{REJECTION_CANDIDATE, REJECTION_CONFIRMED, VELOCITY_REJECTION,
  ENTRY_ARMED}`, deduped by `(symbol, zone_center, opened_at)`.
- Alert log: `logs/qm_pick_alerts_seen.jsonl` (dedup persistence keyed
  on `(opened_at, dir, session)` + `(round(zone,1), dir, UTC-date)`).
- Alert code: `qm_pick_alerts.maybe_send_pick_alert()` — floor
  `_floor()` = env `QM_ALERT_FLOOR` (default 7), freshness
  `_max_age_min()` = env `QM_ALERT_MAX_AGE_MIN` (default 15).
- Scoring code: `qm_decision_shadow.score_rejection_with_memory()`;
  breakdown captured in `cand.confidence_why["breakdown"]` +
  `memory_factors`.
- Continuation family = peak actionable state was `REVERSAL_CANDIDATE`
  or `CONTINUATION_WATCH` on the target dates AND no target-date
  transition into the rejection family.
