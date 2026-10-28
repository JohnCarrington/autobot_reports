# Correction 2 — Final Regression Results

**Date:** 2026-10-28
**Branch tip:** `eebbaa6`
**Status:** All tests pass against the deployed modules.

---

## 1. Full worktree sweep

```
pytest scripts/research/live_obs/tests/
...
============================= 295 passed in 1.14s ==============================
```

Zero failures.  The pre-existing macro-host test failure
(`test_classifier_row_after_asof_invisible`) is **resolved** — see §3.

## 2. Correction 2 regression suite

```
pytest scripts/research/live_obs/tests/test_correction2_structured_proposals_20261028.py -v
...
32 passed in 0.19s
```

### 2.1 Twenty brief-mandated cases (unchanged from first delivery)

| # | Case | Result |
|---|---|---|
| 1 | Structured BUY proposal, all three fields | ✓ VALID / READY / BUY |
| 2 | Structured SELL proposal | ✓ VALID / READY / SELL |
| 3 | Missing `target_price` | ✓ WARN → CAUTION |
| 4 | Missing `stop_price` | ✓ WARN → CAUTION |
| 5 | Missing `entry_price` | ✓ WARN |
| 6 | Non-numeric `entry_price` | ✓ HIGH → INVALID |
| 7 | Contradictory target (BUY) | ✓ HIGH → INVALID |
| 8 | Wrong-sided stop (BUY) | ✓ HIGH → INVALID |
| 9 | Broker-scale price | ✓ HIGH → INVALID |
| 10 | Narrative-regex would duplicate entry/target; structured overrides | ✓ VALID; target from `trade_proposal` |
| 11 | Multiple levels; structured disambiguates | ✓ no flag, correct entry/target |
| 12 | Hard contradiction (65 p) → HIGH / INVALID | ✓ |
| 13 | CAUTION + complete | ✓ BUY/CONDITIONAL |
| 14 | CAUTION + incomplete | ✓ WAIT/INCOMPLETE |
| 15 | INVALID + HIGH | ✓ WAIT/SUPPRESSED |
| 16 | EXPIRED (past-UTC anchors) | ✓ WAIT/EXPIRED_ENTRY |
| 17 | STALE market data | ✓ WAIT/STALE |
| 18 | Repeated revisions deterministic | ✓ |
| 19 | Trigger-spec level mismatch | ✓ HIGH → INVALID |
| 20 | P3-compatible structured + aligned trigger_spec | ✓ VALID |

### 2.2 New C2-F cases (contradiction-validator safety repair)

| Class | Test | Result | Validates |
|---|---|---|---|
| Case A hard contradiction | `test_hard_contradiction_buy_65p` | ✓ HIGH → INVALID | BUY 65 p gap, no stop/target match |
| Case A hard contradiction | `test_hard_contradiction_sell_80p` | ✓ HIGH → INVALID | SELL 80 p gap |
| Case B ambiguous drift | `test_soft_drift_15p_emits_warn_not_high` | ✓ WARN only; CAUTION publication | 15 p gap, no stop/target match |
| Case B ambiguous drift | `test_soft_drift_structured_still_authoritative` | ✓ BUY/CONDITIONAL + structured prices intact | Downstream behaviour under WARN |
| Case C consistent | `test_narrative_matches_entry_within_5p` | ✓ no flag | 2 p agreement band |
| Case C consistent | `test_narrative_price_matches_structured_target_not_entry` | ✓ no flag | Parser grabs target; recognised as ambiguity |
| Case C consistent | `test_narrative_price_matches_structured_stop_not_entry` | ✓ no flag | Parser grabs stop; recognised as ambiguity |
| Case C consistent | `test_no_parseable_narrative_price` | ✓ no flag | Nothing matches; no flag |

### 2.3 Preservation checks

| Case | Expected | Result |
|---|---|---|
| CAUTION → CONDITIONAL (Correction 1) | still holds | ✓ |
| Wrong-sided stop → HIGH / INVALID | invariant preserved | ✓ |
| Category C exemption | still exempt | ✓ |
| `allow_discretion: true` exemption | still exempt | ✓ |

## 3. Macro-host test fixture correction

```
pytest scripts/research/live_obs/tests/test_market_observer_macro_host.py -v
...
13 passed in 0.12s
```

`test_classifier_row_after_asof_invisible` now asserts `status = EXPIRED` instead of the former `RELEASED`.  Rationale: documented contract in `market_observer_macro.py:83` says *EXPIRED iff release≤asof AND no actual available at asof*.  The fixture scenario (frozen asof 09:00 Z, release 08:00 Z, classifier row 09:05 Z = invisible at asof) deterministically yields EXPIRED under that contract.  The previous RELEASED assertion documented an older semantic that pre-dated `_classify_event_status` (introduced in snapshot commit `98a8c42` this session).

**Production classifier logic was not modified.**  The assertion was not skipped or silently weakened — it now matches the production contract explicitly, with a code comment citing the documented semantic.  The test clock is frozen (`T = dt.datetime(2026, 10, 22, 9, 0, UTC)`); no time-mocking was required.

Verified against:
* deployed C1 production file — produces EXPIRED
* Correction 2 branch (`1a6dad3`) — produces EXPIRED
* Final branch (`eebbaa6`) — produces EXPIRED

All three agreed on EXPIRED; the test assertion was the outlier.

## 4. Live smoke tests against deployed modules

Executed immediately after the 22:39:46 Z atomic swap, importing from `/mnt/volume_lon1_1778405456698/research/live_obs/agent/`:

| Smoke test | Expected | Observed |
|---|---|---|
| Valid structured BUY, all three fields | VALID, no flags | ✓ |
| Hard contradiction 65 p | INVALID + `STRUCTURED_VS_NARRATIVE_CONTRADICTION` | ✓ |
| Soft drift 15 p | CAUTION + `STRUCTURED_NARRATIVE_PRICE_DRIFT` | ✓ |
| CAUTION + full structured proposal (Correction 1 preservation) | BUY/CONDITIONAL | ✓ |

All four smoke tests passed; the deployed modules behave identically to the branch tip under test fixtures.
