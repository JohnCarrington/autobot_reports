# V1↔V2 Fire-Time Join — Birth-Fixture Report

**Date:** 2026-09-05 (birth fixture for 2026-09-04)
**Scope:** shadow-only fire-time join at the `execute_trade` seam. V1 detects, V2 scores.
**Frozen for Mon–Thu exam:** `QM_JOIN_FLOOR=7`

**HEAD verified before work:** `ca81e43ba80ab229ae48a5df67d29cad9aa965d1`
`ca81e43 fix(alerts): purge stale DAY_TIER_MASK / removed-gate claims from user-facing messages`

**Local commit hash (not pushed to bot repo):** `3c5f2f32599087f0078ac1e699db01ebaf017cf9`
on branch `feat/trend-stretch-brake-adx-floor`.

---

## What was built

* **`qm_join.py`** — fire-time snapshot of V2 candidate state at the same seam as `entry_hours` / `coherence`. Persists `v2_join_score`, `v2_join_floor`, `v2_join_verdict` (`WOULD_KEEP` / `WOULD_REFUSE` / `NO_STATE`), `v2_join_factors`, `v2_join_staleness_secs`, `zone_context`, `score_mode` (`full` / `degraded`). Every path fail-silent; failures counted to `logs/qm_join_fails.jsonl`.
* **`trade_executor.execute_trade`** — one `compute_snapshot` per fire attempt; `stamp_block` on `ENTRY_HOURS` and `COHERENCE` blocks; `stamp_fire` + `emit_v2_keep_pick` when the fire passes both. Snapshot also stashed on `decision.debug["v2_join"]` so `signal_logger.log_open` merges the columns onto the fire's `signal_log` row.
* **`qm_decision_shadow.persist_candidate`** — extended to call `qm_join.census_after_transition(cand)` after every transition; classifies floor-passing actionable candidates as `v1_fire` / `v1_block` / `v1_silent` from a ±2-bar window and writes `event=v2_only` rows for genuine silence.
* **`scripts/qm_join_grade.py`** — per-day quadrant/classifier table + commercial scoreboard (ALL-V1 vs V2-KEPT-ONLY); reconstructs snapshots from `qm_candidates.jsonl` when live stamps absent; peak concurrency from real open/close intervals.

All wiring is additive; no threshold or gating behaviour changed on the V1 path.

---

## 1. Friday quadrant / classifier table (2026-09-04)

```
--- V1 FIRES (real P&L, GOOD = total_pnl_pips >= +10) n=6 ---
                      GOOD       BAD     TOTAL
V2 KEEP                  0         0         0
V2 REFUSE                3         3         6
V2 NO_STATE              0         0         0
keep precision: -   refuse precision (bad-avoided): 50.0%
full-context   KEEP 0G/0B  REFUSE 0G/0B
degraded-ctx   KEEP 0G/0B  REFUSE 3G/3B

--- V1 BLOCKS (hypothetical MFE/MAE 36-bar) n=4 ---
                      GOOD       BAD     TOTAL
V2 KEEP                  1         0         1
V2 REFUSE                0         3         3
keep precision: 100.0%   refuse precision (bad-avoided): 100.0%
full-context   KEEP 1G/0B  REFUSE 0G/0B
degraded-ctx   KEEP 0G/0B  REFUSE 0G/3B

--- V1 SILENT / V2 LOUD (hypothetical MFE/MAE 36-bar) n=2 ---
                      GOOD       BAD     TOTAL
V2 KEEP                  1         1         2
keep precision: 50.0%
```

Every Friday fire reconstructs as `WOULD_REFUSE` because live stamping wasn't running on Friday: the grader looks up the last SDE transition strictly before each fire's `ts` on the same symbol, and for each of the six fires the same-symbol candidate in memory at that instant was a low-score `APPROACHING_ZONE` / `EXTREME_REACHED` reset (score 0). The strong actionable transitions on both symbols happened later that afternoon (13:15+ GBPUSD zone 13497.65 / 13517.17; 14:10+ EURUSD zone 11615.83). The BLOCK and V2-only rows draw from those transitions and carry real scores.

## 2. Friday commercial scoreboard

```
metric                           ALL-V1        V2-KEPT
------------------------------------------------------
trades/day                            6              0
net pips                          +75.4           +0.0
win rate                          66.7%              -
expectancy/trade                 +12.56          +0.00
MFE median                         15.1              -
MAE median                          7.5              -
>=25p winners                         2              0
>=35p winners                         2              0
peak simultaneous                     3              0
peak capital £                      120              0
pips / £ peak-cap                 0.628              -
```

V2-KEPT column empty for the reason above. Peak concurrency (3) reconstructed from actual `timestamp_open`/`timestamp_close` intervals in `signal_log.jsonl`; peak-capital reference is `peak × 20p × £2/pt = £120`.

## 3. Fire table (2026-09-04)

```
time              pair    strategy                       dir      pnl   v2       verdict      mode        src
2026-09-04 08:05  GBPUSD  GBPUSD_BB_BOUNCE_L             BUY     -8.3    0  WOULD_REFUSE  degraded reconstruct
2026-09-04 11:00  GBPUSD  GBPUSD_BB_BOUNCE_S             SELL   +41.4    0  WOULD_REFUSE  degraded reconstruct
2026-09-04 12:30  GBPUSD  NEWS_STRATEGY_CONT             BUY    +39.2    0  WOULD_REFUSE  degraded reconstruct
2026-09-04 12:31  EURUSD  NEWS_STRATEGY_CONT             SELL   -10.5    0  WOULD_REFUSE  degraded reconstruct
2026-09-04 13:20  EURUSD  NEWS_STRATEGY_REVERSAL         BUY     +3.2    0  WOULD_REFUSE  degraded reconstruct
2026-09-04 13:40  GBPUSD  GBPUSD_STRUCTURE_BREAK_L       BUY    +10.4    0  WOULD_REFUSE  degraded reconstruct
```

## 4. Block table (2026-09-04)

```
time              pair    strategy                       dir         reason   v2       verdict  outcome
2026-09-04 13:05  GBPUSD  GBPUSD_TREND_V3_S              SELL     COHERENCE    0  WOULD_REFUSE      BAD
2026-09-04 13:10  GBPUSD  GBPUSD_TREND_V3_S              SELL     COHERENCE    0  WOULD_REFUSE      BAD
2026-09-04 14:55  GBPUSD  GBPUSD_BB_BOUNCE_S             SELL     COHERENCE    0  WOULD_REFUSE      BAD
2026-09-04 17:10  GBPUSD  GBPUSD_BB_BOUNCE_L             BUY    ENTRY_HOURS   12    WOULD_KEEP     GOOD
```

The 17:10 `ENTRY_HOURS` block on `GBPUSD_BB_BOUNCE_L BUY` is the interesting cell: V2 score at that moment (stale from the 15:50 `REVERSAL_CANDIDATE @ 1.35172` scored 12) was `WOULD_KEEP` and the hypothetical MFE/MAE was `GOOD`.

## 5. V2-only (v1_silent) table (2026-09-04)

```
time              pair          zone chain                                      v2  dir  outcome
2026-09-04 14:10  EURUSD  1.161583  APPROACHING_ZONE,EXTREME_REACHED,SWEEP_D…   10  BUY   BAD
2026-09-04 15:25  GBPUSD  1.351717  APPROACHING_ZONE,EXTREME_REACHED,SWEEP_D…   10  BUY   GOOD
```

Both are outside ±2 bars of any V1 fire or block on the same symbol — genuine detector-gap evidence.

## 6. Staleness distribution (secs)

`min=1.0   median=3451.1   p90=10254.0   max=10293.0   (n=10)`

The high median/p90 reflects that on Friday most fires occurred while the same-symbol candidate had already sat through several bars since its last transition; when live stamping is on, this number will drop drastically because the snapshot will always land on the bar's own transition.

## 7. Full-context vs degraded-context

`full=3   degraded=9`

Full = zone present at snapshot time AND rejection signals or memory factors attached. The one KEEP+GOOD block plus the two v2_only rows are full-context; reconstructed fires and 3 of 4 blocks fell into degraded because their most-recent same-symbol candidate at the event's `ts` sat in a non-actionable reset state.

## 8. Classification counts (candidates ≥ floor, actionable)

`v1_fire=0   v1_block=0   genuine v1_silent=2`

## 9. Friday specimens vs V1 (was V2 loud where V1 was silent?)

| Zone | State reached | Nearest V1 activity | Classification |
|---|---|---|---|
| GBPUSD 1.34977 | SWEEP_DETECTED @ 13:15 (score 10) | 13:05 & 13:10 COHERENCE blocks (SELL) — but SWEEP_DETECTED is not an actionable state | — |
| GBPUSD 1.35172 | REJECTION_CONFIRMED / ENTRY_ARMED / REVERSAL_CANDIDATE @ 15:25–15:50 (score 10–12) | nearest V1 = 17:10 ENTRY_HOURS block (+105 min); GBPUSD_STRUCTURE_BREAK_L fire at 13:40 (–105 min) | **v1_silent** — genuine gap |
| EURUSD 1.16158 | REJECTION_CONFIRMED / ENTRY_ARMED / REVERSAL_CANDIDATE @ 14:10–15:50 (score 10–12) | nearest V1 = 13:20 EURUSD fire (–50 min) | **v1_silent** — genuine gap |
| GBPUSD 17:10 BB_BOUNCE_L BUY | (V1 event, not V2) | blocked by `ENTRY_HOURS`; V2 said KEEP score 12; MFE/MAE says GOOD | v1_block, V2 KEEP + GOOD |

## 10. Join failures / fail-silent events

`0 on 2026-09-04.` `logs/qm_join_fails.jsonl` empty for that date.

---

## Constraint audit

* Shadow only. Zero V1 execution gating. Zero threshold-driven behaviour change.
* Every join path wrapped in `try/except → _bump_failure`. Census + stamp are called from existing fail-silent hooks in `persist_candidate` and `execute_trade`.
* No future-bar leakage: reconstructed snapshots use last transition strictly before the event `ts`; live stamps use the current in-memory candidate state which reflects only the last completed bar.
* No retrospective score recomputation: the score stamped is what the SDE already computed for the current candidate state.
* `QM_JOIN_FLOOR=7` frozen; no per-specimen logic.
* Suite delta zero — entry_hours + coherence + trade_executor + forensic_block + qm_grind unit tests all pass (56/56 in the targeted run).
* Block stamping covers the two active pre-execution block writers at this seam (`ENTRY_HOURS`, `COHERENCE`); label-block / grind-path stamps were not wired because those paths don't currently emit their own jsonl at this choke — flagged as a follow-up if desired.

## Files (bot repo)

```
qm_join.py               new  (523 lines)
scripts/qm_join_grade.py new  (~640 lines)
trade_executor.py       +78  (snapshot + 2 block stamps + fire stamp + pick emit)
qm_decision_shadow.py    +9  (census hook in persist_candidate)
signal_logger.py        +16  (merge dbg["v2_join"] into log_open record)
```

Local commit `3c5f2f3` on `feat/trend-stretch-brake-adx-floor` — not pushed.
