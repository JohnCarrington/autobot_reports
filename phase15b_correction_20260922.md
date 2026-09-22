# Phase 15B — Provenance Correction (Stage10P production boundary)

**MASTER_PHASE:** 15
**PHASE:** 15B — final acceptance / Stage10P provenance correction
**PHASE15B_COMMIT:** `c220291`
**CORRECTION_COMMIT:** `7171893` on `feat/trend-stretch-brake-adx-floor`
**Prior report:** `reports-public/phase15b_acceptance_20260922.md` (commit `8204d92`)
**Date:** 2026-09-22 (UTC)

---

## §0 — Result

`PHASE15_ACCEPTED = YES`
`READY_FOR_PHASE16 = YES`
`PRODUCTION_CHANGED = NO`

The Phase 15 retrieval architecture is unchanged. Only the Stage10P
eligibility rule and its associated tests, derived structural index,
manifest, and this report have been corrected.

---

## §4 — Timestamp semantics

`OBSERVATION_TS_SEMANTICS = opening_bar_ts` (market timestamp of the
bar that OPENED the level interaction — the completed 5m bar that
triggered the observer seam). Source: `stage9s_structural_shadow.py`
`observe_interaction_open` at line 517:
```python
"observation_ts": opening_bar_ts,
```
It is emphatically **not** the wall-clock write time. A development
replay that constructs a synthetic Interaction with any historical or
future `opening_bar_ts` will produce a shadow row carrying that
market ts.

`CHECKPOINT_TS_SEMANTICS = N/A` — there is no separate `checkpoint_ts`
field in the StructuralResolutionShadowV1 schema. `checkpoint_type`
is a fixed enum (`INTERACTION_OPEN`), and the causal moment of the
prediction is `observation_ts` alone.

---

## §3 — Controlled production deployment ts

`SERVING_R2_PRODUCTION_DEPLOYMENT_TS = 2026-09-22T13:08:00.870000+00:00 UTC`

Recovery, primary source: `/proc/982843/stat`
```
boot_epoch          = 1776009731    (from /proc/stat "btime")
starttime_jiffies   = 1407274987    (field 22 of /proc/PID/stat)
HZ                  = 100           (os.sysconf(SC_CLK_TCK))
absolute_epoch      = boot_epoch + starttime_jiffies / HZ
                    = 1776009731 + 14072749.87
                    = 1790082480.87
                    → 2026-09-22T13:08:00.870Z UTC
```
Cross-check, secondary source: `ps -p 982843 -o lstart` →
`Tue Sep 22 13:08:00 2026`, and `stat /proc/982843 -c '%y'` →
`2026-09-22 13:08:01.670252814 +0000` (procfs directory ctime is
slightly after the process's own start ts, as expected).

Third cross-check, `journalctl -u autobot.service` shows the prior
service instance (PID 966930) started `2026-09-22T10:01:15Z` under
a pre-r2 HEAD and was stopped shortly before. The current process
inherited the deployment.

---

## §1 + §5 — Old vs new rule

`OLD_STAGE10P_BOUNDARY = 2026-09-11T00:00:00+00:00`
`OLD_BOUNDARY_VALID = NO`

The old rule (`observation_ts > 2026-09-11T00:00:00Z`) used market
timestamp as the discriminator. It was arithmetically defensible on
the current corpus (which happens to have no serving-r2 OK rows
with `observation_ts` between 2026-09-11 and the actual deployment)
but semantically fragile: a dev replay carrying a serving-r2 tag
and a market ts anywhere after 2026-09-11 would silently pass.

`AUTHORITATIVE_PROVENANCE_RULE`:

```
AUTHORITATIVE_PROSPECTIVE iff all four:
  (1) model_version == "stage9s.model.v1.0.io_model_s.676073826acc9fab.serving-r2"
  (2) interaction_id NOT IN {"abc","a","a8edf012746d2d08"}
  (3) inference_status == "OK"
  (4) observation_ts + 5m (i.e. the bar that closed at
      observation_ts+5m) > SERVING_R2_PRODUCTION_DEPLOYMENT_TS

Ambiguity: if observation_ts + 5m sits inside (deployment_ts − 5m,
deployment_ts], the row is QUARANTINED (could be the prior process's
last bar or the new process's first bar; wall-clock write evidence
would be required to disambiguate — not available in the ledger).

Otherwise: TEST_ONLY or INCOMPLETE per subsidiary rules.
```

The rule is coded at
`scripts/phase15/eligibility.classify_shadow_prediction_row` and
regression-tested at
`tests/unit/phase15/test_phase15_substrate.py::test_no_ambiguous_row_becomes_authoritative`.

---

## §2 + §6 — Every shadow row classified

The shadow ledger has 59 rows. Full audit against the corrected
rule + observer-lifecycle cross-check:

`NATURAL_SERVING_R2_ROWS`:

| Line | model_version | observation_ts (opening_bar_ts) | interaction_id | inference_status | Observer lifecycle |
|---|---|---|---|---|---|
| L57 | serving-r2 | 2026-09-22T13:05:00Z | `59c1f69d10e7b821` | OK | EURUSD PDL 11462.2, 14 observer records for this interaction (opening at same ts) |
| L58 | serving-r2 | 2026-09-22T13:25:00Z | `ec007a3ee464d607` | OK | EURUSD NEAREST_50 11450.0, 10 observer records |
| L59 | serving-r2 | 2026-09-22T14:10:00Z | `0e8e9910556c1599` | OK | GBPUSD NEAREST_50 13350.0, 1 observer record (interaction still live at build time) |

All three iids exist in `logs/level_interaction_observer_v6.jsonl`
with matching pair, level_type, level_price, interaction_start_ts.
The `59c1f69d10e7b821` EURUSD PDL row is the natural post-deployment
inference the operator called out.

`NATURAL_SERVING_R2_COUNT = 3`

`TEST_DEVELOPMENT_SERVING_R2_ROWS = L4-L54 (44 rows) + L27-L41 (already counted)`

Breakdown:
  - Stale test interaction_ids (`abc`, `a`, `a8edf012746d2d08`) at
    L1-L3, L13 (4 rows) — always TEST_ONLY.
  - Base model_version (pre serving-r1) at L4-L12, L14-L26, L46,
    L55-L56 (26 rows) — TEST_ONLY because model_version ≠ serving-r2.
  - serving-r1 at L27-L41 (15 rows) — TEST_ONLY because
    model_version ≠ serving-r2.
  - serving-r2 with `observation_ts=2026-09-10T12:00:00Z` at
    L42-L45, L47-L54 (12 rows) — INCOMPLETE because
    `inference_status=REQUIRED_FEATURE_MISSING`. Under the corrected
    rule they would ALSO be TEST_ONLY on the bar-close-vs-deployment
    check (13:00 closes at 13:05 which is way before deployment),
    but the status check short-circuits first.

`TEST_DEVELOPMENT_SERVING_R2_COUNT = 56` (all non-authoritative rows)

`AMBIGUOUS_SERVING_R2_ROWS = (none in current corpus)`
`AMBIGUOUS_SERVING_R2_COUNT = 0`

No row is silently promoted to AUTHORITATIVE_PROSPECTIVE.

---

## §6 — Cross-check natural rows against observer lifecycle

Command reproduction (read-only):
```python
# opens both ledgers, joins on interaction_id
from collections import defaultdict
obs = defaultdict(list)
for line in open('/opt/tradingbot/logs/level_interaction_observer_v6.jsonl'):
    r = json.loads(line); obs[r['interaction_id']].append(r)
for line in open('/opt/tradingbot/logs/structural_resolution_shadow.jsonl'):
    r = json.loads(line)
    if r['interaction_id'] not in {"abc","a","a8edf012746d2d08"}:
        assert r['interaction_id'] in obs
```
All 55 non-stale-token shadow rows resolve in the observer ledger.
The 3 natural production rows resolve with real production
characteristics (matching pair, level_type, level_price, interaction
start ts).

Terminal-episode lookup (for `59c1f69d10e7b821`, the EURUSD PDL
inference): the interaction has 14 per-bar observer rows carrying
the same `interaction_start_ts=2026-09-22T13:05:00Z`. No terminal
episode written yet (interaction still resolving or already
terminated after the audit snapshot — the observer writes terminals
independently).

---

## §7 — Corrections applied

`STRUCTURAL_INDEX_REBUILT = YES`
  - Path: `reports/phase15/structural_interaction_index.jsonl`
  - Old sha256 (Phase15B c220291): `2dfbae647c4f55d2af45e4e939af9181c3cc01b83683110f670472186e0bd249`
  - New sha256 (this correction):  `e20f56b2907c3fb6b89dc3a63080489d1101f7bb7a9aaa6b4da8bc9ddd972b01`
  - Records: 592 → 609 (natural growth of source ledger during the audit; 3 authoritative shadow rows now, up from 2)
  - Records with MODEL_S opinion attached: 20 → 28 (observer rows joined by exact interaction_id to the 3 authoritative shadow predictions)

`ENTRY_INDEX_CHANGED = YES` (natural corpus growth — 206 → 207 records; shape unchanged)
  - Old sha256: `2b23cb8264b132aa5cee7e7be3626d000ac3a66d946b55c522402cb763cd8415`
  - New sha256: `bca2e6e7a32ba88bf649226795fe6f50c14e7532b6687e9fc5530875fde64743`

Manifest updated (`reports/phase15/manifest.json`). Retrieval API
signatures + retrieval families + retrieval method + leakage barrier
+ pip convention + measurement horizon + candidate identity bridge
+ price source + eligibility taxonomy — all unchanged.

Sources NOT mutated:
```
logs/structural_resolution_shadow.jsonl   (unchanged)
logs/level_interaction_observer_v6.jsonl  (grew naturally by production)
logs/candidate_corpus.jsonl               (unchanged in this correction)
logs/qm_candidates.jsonl                  (unchanged)
logs/signal_log.jsonl                     (unchanged)
```

MODEL_S artifact NOT touched. Stage10P joiner NOT run. Stage6G stays OFF.

---

## §8 — Regression tests

`TEST_RESULTS = 38 passed` (was 33; 5 new).
`NEW_FAILURES = 0`

New tests:
  - `test_shadow_pre_deployment_serving_r2_excluded` — L42-L54 case:
    serving-r2 tag + market ts on 2026-09-10 → TEST_ONLY, reason
    `pre_deployment_bar_close`.
  - `test_shadow_natural_serving_r2_authoritative_matches_l57_l58_l59`
    — every real natural iid is AUTHORITATIVE_PROSPECTIVE with
    reason `post_deployment`.
  - `test_shadow_replay_carries_historical_market_ts_but_serving_r2_still_test_only`
    — a hypothetical replay row (serving-r2 + OK + observation_ts
    between old boundary 2026-09-11 and deployment 2026-09-22) is
    TEST_ONLY under the corrected rule. This is the leak the old
    rule would have admitted.
  - `test_shadow_ambiguous_bar_close_within_1_bar_of_deployment_is_quarantined`
    — a serving-r2 OK row with observation_ts=2026-09-22T13:00:00Z
    (bar closes at 13:05:00Z, inside the uncertainty window around
    deployment 13:08:00.870Z) → QUARANTINED, never authoritative.
  - `test_shadow_serving_r2_inference_failed_incomplete_not_authoritative`
    — serving-r2 tag with non-OK inference remains INCOMPLETE, never
    authoritative regardless of write timing.
  - `test_serving_r2_production_deployment_ts_is_pid_982843_start`
    — provenance regression: constant must match the recovered
    PID 982843 start ts exactly.
  - `test_no_ambiguous_row_becomes_authoritative` — sweep every row
    on disk and assert every AUTHORITATIVE_PROSPECTIVE row satisfies
    the full 4-part rule and its reason mentions `post_deployment`.

Command:
```
cd /opt/tradingbot && python3 -m pytest tests/unit/phase15/ -q
```

---

## §9 — Phase 15 acceptance

`PHASE15_ACCEPTED = YES`

The existing Phase 15B architecture is accepted:
  - ENTRY_CANDIDATE retrieval (candidate_corpus + qm_candidates,
    deterministic exact-ID bridge via IG deal_ref / deal_id)
  - STRUCTURAL_INTERACTION retrieval (level_interaction_observer_v6,
    MODEL_S opinion attached only via exact interaction_id join to
    AUTHORITATIVE_PROSPECTIVE shadow rows under the CORRECTED rule)
  - Hybrid hard-filter + normalised numeric KNN
  - Decision / outcome / provenance leakage barrier proven structurally
  - Deterministic exact-ID bridges only (never heuristic)

TRADEMANAGER_DECISION family remains DEFERRED (pos_key ↔ deal_id
semantics). Phase 16 is NOT blocked on it.

`READY_FOR_PHASE16 = YES`

---

## §10 — Production safety

```
PRODUCTION_PID          = 982843
PRODUCTION_HEAD (loaded) = fe974c9
PRODUCTION_CHANGED       = NO
```

No restart. No .env change. No broker call. No historical REST.
No Stage6G. No joiner run. No MODEL_S retraining.
No production-code deployment.

Only tree changes (all under Phase 15 substrate, none imported by
the running autobot process):
  - `scripts/phase15/eligibility.py`
  - `tests/unit/phase15/test_phase15_substrate.py`
  - `reports/phase15/manifest.json`
  - `reports/phase15/entry_candidate_index.jsonl` (regenerated;
    gitignored)
  - `reports/phase15/structural_interaction_index.jsonl` (regenerated;
    gitignored)
  - This report (`reports-public/`)

---

## §11 — Return

```
PHASE15B_COMMIT                              = c220291
CORRECTION_COMMIT                            = 7171893

OBSERVATION_TS_SEMANTICS                     = opening_bar_ts (market timestamp of the bar that opened the interaction; NOT wall-clock write time; source stage9s_structural_shadow.py:517)
CHECKPOINT_TS_SEMANTICS                      = N/A (no such field; checkpoint_type is a fixed enum)

SERVING_R2_PRODUCTION_DEPLOYMENT_TS          = 2026-09-22T13:08:00.870000+00:00 UTC (recovered from /proc/982843/stat)

OLD_STAGE10P_BOUNDARY                        = 2026-09-11T00:00:00+00:00
OLD_BOUNDARY_VALID                           = NO

NATURAL_SERVING_R2_ROWS                      = L57 (EURUSD PDL 13:05), L58 (EURUSD NEAREST_50 13:25), L59 (GBPUSD NEAREST_50 14:10)
NATURAL_SERVING_R2_COUNT                     = 3

TEST_DEVELOPMENT_SERVING_R2_ROWS             = 4 stale-iid + 26 base-mv + 15 serving-r1 + 12 serving-r2 pre-deployment (INCOMPLETE via status short-circuit) — total 56
TEST_DEVELOPMENT_SERVING_R2_COUNT            = 56

AMBIGUOUS_SERVING_R2_ROWS                    = (none)
AMBIGUOUS_SERVING_R2_COUNT                   = 0

AUTHORITATIVE_PROVENANCE_RULE                = model_version==serving-r2 AND interaction_id NOT IN stale-set AND inference_status==OK AND (observation_ts + 5m) > deployment_ts; ambiguity within one 5m bar of deployment → QUARANTINED

STRUCTURAL_INDEX_REBUILT                     = YES (sha256 2dfbae64... → e20f56b2..., 592 → 609 records, 20 → 28 with MODEL_S)
ENTRY_INDEX_CHANGED                          = YES (natural corpus growth 206 → 207; sha256 2b23cb82... → bca2e6e7...)

TEST_RESULTS                                 = 38 passed
NEW_FAILURES                                 = 0

CORRECTION_COMMIT                            = 7171893

PRODUCTION_CHANGED                           = NO
PRODUCTION_PID                               = 982843
PRODUCTION_HEAD (loaded)                     = fe974c9

PHASE15_ACCEPTED                             = YES
READY_FOR_PHASE16                            = YES
```

---

## §12 — Hard stop

Phase 15 accepted. Phase 16 not begun. Stopping for operator acceptance
of this correction.
