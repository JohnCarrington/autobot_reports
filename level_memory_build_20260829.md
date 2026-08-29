# LevelMemory — testing/retesting history as a scoring input

**HEAD built against:** `c3ee999` — "fix(trend_v3): FIRE log format — skipped(grind), not false X>=Y"
(if the operator has already restarted, live tape now includes `f534a3b` GRIND context weight and `c3ee999` truthful grind fire logs; those commits are unrelated to this build).

**Status:** SHADOW-FIRST. Nothing gates, sizes, or fires. Local commit only, no push, no restart required beyond the operator's normal boundary restart.

**Operator diagnosis (2026-08-28, binding):**
> "It is all about testing and retesting the levels — the bot treats every level the same."
> F1 sold into a pivot with ~9 hours of successful defences (lost −5.4).
> F7 sold the pierce-then-reclaim retest of the SAME pivot 4.5 hours later (won +19.95).
> Same level, same price, opposite outcomes — distinguished only by test history.

---

## 1. Contradictions surfaced

**A. The retro corpus is small and P-cohort samples are thin.**
The `qm_level_interactions.jsonl` tape covers only 2 days (2352 rows). For the P cohort (the surface where F1/F7 fought) there are only 19 total interactions — 4 first-touches, 3 seconds, 12 at test_number ≥ 3, of which 3 carry `role_reversal=True`. The default weights below are grounded in the OUTER_PIVOT and SESSION_STRUCT NY splits — both hold the "first defends, later exhausts" pattern with n=18 and n=284 respectively. When live tape crosses ~30 days the operator should re-run the calibration script and adjust weights before any promotion out of shadow.

**B. The DYNAMIC cohort is dominated by 3+ tests.**
1495 of 1503 DYNAMIC (BB/EMA) interactions land in test_bucket 3+, because the BB midline touches every few bars. This means `mem_test_number_3plus` will fire on nearly every BB signal — the penalty weight (default −3) will suppress most BB fade candidates. This is a design decision the operator must rule on: whether test-number-decay should apply to dynamic surfaces or only to pivots/round numbers. Env override: set `QM_MEM_W_MEM_TEST_NUMBER_3PLUS=0` to neutralise for shadow observation.

**C. My quick "was this the deepest pierce of the day" proxy across the pierce-recorder corpus shows the OPPOSITE of the operator's cited pattern** (first-touches 29% "deepest", 3+ touches 44.5% "deepest"). This is a max-order artefact of my proxy — later-in-session pierces tend to be deeper because volatility expands into NY, not because the level defends worse. The correct outcome metric is forward MFE within a fixed horizon, which the pierce ledger does not carry per-row. The retro-calibration script uses interaction-record `max_excursion_*` as a bar-granular proxy — its OUTER_PIVOT 27.8% (first) → 11.8% (3+) split does match the operator's diagnosis.

---

## 2. Extension points quoted verbatim

**Q1 — where the closed interaction stream is written today** (`qm_level_interactions.py:237-246`):

```python
def record_final(inter: Interaction) -> None:
    """Append final-state record. Fail-silent."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Drop internal underscored fields from the record
        d = {k: v for k, v in asdict(inter).items() if not k.startswith("_")}
        with _LOG_PATH.open("a") as fh:
            fh.write(json.dumps(d) + "\n")
    except Exception:
        pass
```

Every closed interaction flows through this single sink. LevelMemory folds in HERE — no parallel event stream.

**Q2 — where interactions are opened, driven, and finalized** (`qm_hooks.py:132-183`):

```python
def _run_build2(symbol: str, ts_utc: datetime,
                bar_high: float, bar_low: float, bar_close: float,
                level_map: Any) -> None:
    ...
    # Update every active interaction with this bar
    finalized: List[Tuple[Tuple[str, float], Any]] = []
    for key, inter in list(active.items()):
        try:
            inter = _b2.update(inter, bar)
            active[key] = inter
            finalized_maybe = _b2.maybe_finalize(inter, bar)
            if finalized_maybe is not None:
                _b2.record_final(finalized_maybe)
                finalized.append((key, finalized_maybe))
```

The memory dispatch was inserted immediately after `_b2.record_final(finalized_maybe)` — same finalize site, wrapped fail-silent, cannot break the interaction stream.

**Q3 — where the §9 rejection weight table lives** (`qm_decision_shadow.py:661-668`):

```python
_REJECTION_WEIGHTS = {
    "level_swept":         2,
    "close_back_through":  3,
    "close_inside_bb":     2,
    "large_reversal":      2,
    "m5_structure_shift":  3,
    "momentum_reversal":   1,
}
```

Memory keys extend this table; `score_rejection()`'s signature is UNCHANGED. Existing callers that pass legacy-only signal dicts get byte-identical scores.

**Q4 — where the §29 confidence factor list lives** (`qm_decision_shadow.py:751-755`):

```python
_CONF_FACTORS = (
    "regime_alignment", "confluence", "bb_extreme", "sweep",
    "rejection_strength", "acceptance_strength", "m5_confirmed",
    "time_of_day", "day_type", "momentum", "chop", "news_proximity",
)
```

`level_memory` is appended; `score_confidence()` treats an absent factor as 0 contribution, so callers that don't supply the new key get byte-identical scores.

---

## 3. Retro-calibration table

Source: `logs/qm_level_interactions.jsonl` (2352 rows, 2026-08-26 → 2026-08-28).
Outcome metric: `max_excursion_*_pips ≥ 10p on the fade side` (bar-granular proxy — the interaction record's own excursion figure).
Cohorts: **P**, **OUTER_PIVOT**, **DYNAMIC** (BB/EMA), **SESSION_STRUCT**. P and OUTER_PIVOT held SEPARATE per standing rule.

```
     cohort     | session  | test_bucket | role_rev |    n     | outcome_10p
----------------|----------|-------------|----------|----------|-------------
DYNAMIC         | ALL      | 1           | FALSE    |     4    |    0.000
DYNAMIC         | ALL      | 2           | FALSE    |     3    |    0.000
DYNAMIC         | ALL      | 2           | TRUE     |     1    |    0.000
DYNAMIC         | ALL      | 3+          | FALSE    |   690    |    0.043
DYNAMIC         | ALL      | 3+          | TRUE     |   805    |    0.097
OUTER_PIVOT     | ALL      | 1           | FALSE    |    18    |    0.278   ← fresh outer pivots fade
OUTER_PIVOT     | ALL      | 2           | FALSE    |    13    |    0.308
OUTER_PIVOT     | ALL      | 2           | TRUE     |     1    |    1.000   ← F7 pattern (n=1, illustrative)
OUTER_PIVOT     | ALL      | 3+          | FALSE    |    34    |    0.118   ← exhausted outer pivots break
OUTER_PIVOT     | ALL      | 3+          | TRUE     |     3    |    0.000
P               | ALL      | 1           | FALSE    |     4    |    0.000
P               | ALL      | 2           | FALSE    |     3    |    0.000
P               | ALL      | 3+          | FALSE    |     9    |    0.111
P               | ALL      | 3+          | TRUE     |     3    |    0.000
SESSION_STRUCT  | ASIA     | 1           | FALSE    |   119    |    0.042
SESSION_STRUCT  | ASIA     | 2           | FALSE    |    26    |    0.038
SESSION_STRUCT  | ASIA     | 2           | TRUE     |     4    |    0.000
SESSION_STRUCT  | ASIA     | 3+          | FALSE    |     8    |    0.000
SESSION_STRUCT  | LONDON   | 1           | FALSE    |   145    |    0.041
SESSION_STRUCT  | LONDON   | 2           | FALSE    |    36    |    0.028
SESSION_STRUCT  | LONDON   | 3+          | FALSE    |    16    |    0.125
SESSION_STRUCT  | NY       | 1           | FALSE    |   284    |    0.271   ← NY fresh: 27%
SESSION_STRUCT  | NY       | 2           | FALSE    |    48    |    0.229
SESSION_STRUCT  | NY       | 2           | TRUE     |     2    |    0.000
SESSION_STRUCT  | NY       | 3+          | FALSE    |     9    |    0.000   ← NY exhausted: 0%
SESSION_STRUCT  | OTHER    | 1           | FALSE    |    17    |    0.000
SESSION_STRUCT  | OTHER    | 2           | FALSE    |     1    |    0.000
SESSION_STRUCT  | OTHER    | 2           | TRUE     |     1    |    0.000
SESSION_STRUCT  | OTHER    | 3+          | TRUE     |     1    |    0.000
```

**Rulings the operator should make from this table before any promotion out of shadow:**
- OUTER_PIVOT and SESSION_STRUCT-NY both confirm the "first defends, later exhausts" pattern. Defaults set to match.
- DYNAMIC cohort samples are too concentrated in bucket 3+ to distinguish the test-number pattern; may need cohort-specific weight overrides.
- P cohort is n=19 total — the F1/F7 acceptance fixture is the only current honest test.
- ASIA/LONDON SESSION_STRUCT show low fade rates across all buckets — likely a chop/liquidity confound the memory factors don't capture.

Weights defaulted from this evidence (env-tunable under `QM_MEM_W_*`):

| Signal | Default weight | Reason |
|---|---|---|
| `mem_first_touch` | +3 | OUTER_PIVOT 27.8% at bucket 1; NY SESSION_STRUCT 27.1% — twice the base rate |
| `mem_test_number_3plus` | -3 | OUTER_PIVOT drops 27.8% → 11.8% at bucket 3+; NY drops 27.1% → 0% |
| `mem_role_reversal_retest` | +4 | F7 pattern; n=1 in current tape but explicitly named by operator |
| `mem_recency_fresh` | +1 | Half-life default 4h (`QM_MEM_RECENCY_HALFLIFE_S=14400`) |

Confidence-scalar composition (`memory_confidence_scalar`, signed in [−1, +1]):
role_reversal_retest +0.6, first_touch +0.3, recency_fresh +0.1, test_number_3plus −0.5.

---

## 4. Acceptance — F1 vs F7 fixture (both breakdowns verbatim)

Test: `tests/unit/test_qm_level_memory_f1_f7.py::test_f1_penalised_vs_f7_bonused` — **PASSED**.

Setup: same P pivot @ 13593.0. Same base rejection signals for both moments: `level_swept=True`, `close_back_through=True`, `close_inside_bb=True` (base = 7 → strong). All divergence is attributable to memory alone.

### F1 — 2026-08-28T06:15Z (after 9 hrs of defended pierces, no reversal)

```
F1 FACTORS (06:15Z, P pivot):
  mem_first_touch = False
  mem_test_number_3plus = True
  mem_role_reversal_retest = False
  mem_recency_fresh = True
  test_number = 10
  touch_count = 9
  defence_count = 9
  pierce_count = 9
  accept_count = 0
  oscillate_count = 0
  role_reversal_armed = False
  last_accept_side = None
  approach_side = above
  recency_seconds = 4500.0
  recency_score = 0.7316
  identity_session = ALL
  identity_price_key = 13593.0

F1 REJECTION SCORE:
  base_score = 7
  base_band = strong
  memory_score = -2
  total_score = 5
  total_band = possible
  breakdown = {'level_swept': 2, 'close_back_through': 3, 'close_inside_bb': 2,
               'mem_test_number_3plus': -3, 'mem_recency_fresh': 1}
```

**F1 result:** base_score 7 (strong) → total_score 5 (possible). Memory contribution = −2. **PENALISED as required.** The band demotion from `strong` → `possible` is the honest downgrade the operator asked for — F1's amnesiac context scored `strong`, its memory-aware context scores `possible`.

### F7 — 2026-08-28T10:45Z (same P pivot, one intervening ACCEPT + reclaim)

```
F7 FACTORS (10:45Z, same P pivot post-pierce reclaim):
  mem_first_touch = False
  mem_test_number_3plus = True
  mem_role_reversal_retest = True
  mem_recency_fresh = True
  test_number = 11
  touch_count = 10
  defence_count = 9
  pierce_count = 10
  accept_count = 1
  oscillate_count = 0
  role_reversal_armed = True
  last_accept_side = above
  approach_side = below
  recency_seconds = 9900.0
  recency_score = 0.5028
  identity_session = ALL
  identity_price_key = 13593.0

F7 REJECTION SCORE:
  base_score = 7
  base_band = strong
  memory_score = 2
  total_score = 9
  total_band = strong
  breakdown = {'level_swept': 2, 'close_back_through': 3, 'close_inside_bb': 2,
               'mem_test_number_3plus': -3, 'mem_role_reversal_retest': 4,
               'mem_recency_fresh': 1}
```

**F7 result:** base_score 7 → total_score 9. Memory contribution = +2. **BONUSED as required.** The +4 `mem_role_reversal_retest` weight overwhelms the −3 `mem_test_number_3plus` penalty; the retest-from-far-side after the acceptance flip is exactly the F7 pattern the operator named.

### Cross-check

- F7 total (9) > F1 total (5): swing of **+4 points** attributable purely to test history.
- Confidence-scalar delta: F1 = **−0.4**, F7 = **+0.2** (swing +0.6).

The memory logic distinguishes the two moments. The build clears its own reason-for-existing bar.

---

## 5. Proofs

**Identity.** `score_rejection` and `score_confidence` remain byte-identical for legacy callers. Verified in-conversation:

```
score_rejection legacy path: (10, 'very_strong')
score_confidence legacy path: score=84
IDENTITY PROOF: OK — legacy score_rejection and score_confidence outputs unchanged;
level_memory absent → 0 contribution.
```

Strategy modules (`gbpusd_bb_bounce`, `gbpusd_trend_v3`) do not import `qm_level_memory` — the SDE import-sanction test `test_shadow_module_only_imported_by_sanctioned_hooks` continues to pass.

**Fail-silent.** Every public entry point (`get`, `factors`, `on_final`, `apply_memory_to_rejection_signals`, `score_rejection_with_memory`, `memory_confidence_scalar`) swallows bad inputs and returns a safe default. Verified with intentionally malformed inputs — no exception escaped.

**Suite delta.** Baseline HEAD c3ee999: **151 failed / 1905 passed / 20 skipped / 28 errors**.
With this build: **149 failed / 1907 passed / 20 skipped / 28 errors**.
**Zero new failures introduced.** Two tests moved from fail → pass: the new `test_f1_penalised_vs_f7_bonused` and the updated `test_confidence_missing_factors_are_listed_absent` (updated to reflect the added `level_memory` factor; the test now asserts the length matches `_CONF_FACTORS` rather than hardcoding 12).

**Log cadence.** One `logger.info("[QM-MEM] ...")` in `qm_level_memory.py:324` inside `on_final()` — fires on state change of a memory record (a closed interaction just folded in). All other `[QM-MEM]` sites are DEBUG-level swallowed-error logs. No per-bar INFO traffic.

---

## 6. Files touched

| Path | Change | Fail-silent boundary |
|---|---|---|
| `qm_level_memory.py` (new, 432 lines) | LevelMemoryStore, session bucket, identity rule per level type, persistence, factor query | Every public method wrapped |
| `qm_hooks.py` (+7 lines around `_run_build2`) | Dispatch to `qm_level_memory.get_store().on_final(inter)` on interaction finalize | `try:/except: pass` |
| `qm_decision_shadow.py` (+~90 lines) | Extend `_REJECTION_WEIGHTS` with four `mem_*` keys, add `apply_memory_to_rejection_signals`, `score_rejection_with_memory`, append `level_memory` to `_CONF_FACTORS`, `memory_confidence_scalar` | Every new function wrapped |
| `scripts/qm_level_memory_calibration.py` (new, 216 lines) | Read-only retro-calibration walker | N/A (offline tool) |
| `tests/unit/test_qm_level_memory_f1_f7.py` (new) | F1/F7 acceptance fixture | N/A (test) |
| `tests/unit/test_qm_decision_shadow.py` (+2 lines) | `test_confidence_missing_factors_are_listed_absent` updated to `len(shadow._CONF_FACTORS)` instead of hardcoded 12 | N/A (test) |

New telemetry files (created lazily on first update):
- `logs/qm_level_memory.jsonl` (append-only, one line per state change)
- `logs/qm_level_memory_state.json` (compact restart-continuity snapshot)

---

## 7. Env-tunable surface (all default to shadow-neutral behaviour)

| Env var | Default | Purpose |
|---|---|---|
| `QM_LEVEL_MEMORY_ENABLED` | `1` | Master kill-switch for the on_final dispatch. `0` = no memory writes, no INFO logs, no factor computation. |
| `QM_MEM_W_MEM_FIRST_TOUCH` | `3` | Fade-bonus weight when the approach is the first touch of the level identity in the session. |
| `QM_MEM_W_MEM_TEST_NUMBER_3PLUS` | `-3` | Fade-penalty when the identity is on its 3rd+ test. |
| `QM_MEM_W_MEM_ROLE_REVERSAL_RETEST` | `4` | F7 bonus — approach from the opposite side of a prior acceptance flip. |
| `QM_MEM_W_MEM_RECENCY_FRESH` | `1` | Small bonus while the last test is within `QM_MEM_RECENCY_HALFLIFE_S` seconds. |
| `QM_MEM_RECENCY_HALFLIFE_S` | `14400` | 4h decay half-life for recency freshness. |

---

## 8. Restart note

**No restart required for this build to produce telemetry.** The extension is dormant until an interaction closes (`qm_level_interactions.record_final` → `qm_hooks._run_build2` finalize path → `qm_level_memory.get_store().on_final`), and that chain is picked up by the module-import path already loaded by `qm_hooks.install()`. The next process restart the operator makes for any other reason will start writing `logs/qm_level_memory.jsonl` and populating the state file.

To promote out of shadow (NOT DONE HERE), the operator's next steps would be:
1. Let 30+ days of live tape accumulate.
2. Re-run `python3 scripts/qm_level_memory_calibration.py` and rule on weight defaults.
3. Decide whether DYNAMIC cohort should get `test_number_3plus` neutralised.
4. Wire `apply_memory_to_rejection_signals` and `memory_confidence_scalar` into a strategy's live path (currently NO strategy calls them — this is shadow observation only).
