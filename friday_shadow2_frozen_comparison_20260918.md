# Shadow2 Frozen Comparison — Recovery, Validation, and Portfolio Classification

**Date:** 2026-09-18
**Batch:** Shadow2 frozen evidence, single-shot run
**Runner PID:** 538502 (survived client disconnect)
**Runner command:** `python3 -u /mnt/volume_lon1_1778405456698/derived/autobot_strategy_study/run_survival_study.py`
**Runner cwd:** `/opt/tradingbot/.claude/worktrees/phase2b-apparatus`
**Live-trading change:** NONE. This is a Lane A research batch. No `.env`, systemctl, broker, or restart action taken or proposed.

---

## 0. Recovery narrative

At 14:07:51Z the client disconnected while the frozen comparison was running. The runner (PID 538502) was untouched — it continued executing single-threaded (`STAT=Rl`, 99.9% CPU, 1.17 GB RSS) with its stdout/stderr file descriptors still bound to `/tmp/claude-1000/-opt-tradingbot/.../tasks/bwqo1y1y5.output`. Only the harness-side task registration was reaped by the disconnect. No duplicate runner was launched. No signal was sent to PID 538502 at any point.

A single passive monitor was re-armed (task `b9rgvw6sl`, persistent, read-only) after operator authorisation. It observed pair completion, combined-output write, and normal exit without touching the process.

**Recovery timeline (UTC 2026-09-18):**

| Time | Event |
|---|---|
| 13:47:10 | Runner started (via bash 538481 → PID 538502) |
| 14:07:51 | Client disconnect; runner still alive on GBPUSD |
| 14:11:54 | Passive monitor armed (`b9rgvw6sl`) |
| 14:18:51 | GBPUSD complete: 196,022 bars loaded, 82,155 candidates, 7 not_replayable, 1900.1s duration |
| 14:19:02 | EURUSD complete: 181,903 bars, 0 candidates (10 families NOT_APPLICABLE_TO_PAIR), 3.1s |
| 14:19:04 | USDCAD complete: 157,655 bars, 0 candidates, 2.2s |
| 14:19:06 | USDJPY complete: 157,852 bars, 0 candidates, 2.2s |
| 14:19:34 | Combined `strategy_survival_results.json` (145.2 MB) + `.csv` (12.4 MB) written; PID 538502 exited normally |

---

## 1. Output validation

All four per-pair files present. Combined outputs written. Runner exited with combined artefacts on disk (not abnormal).

**Byte-level:**

```
strategy_survival_results.GBPUSD.json   128,759,632
strategy_survival_results.EURUSD.json         2,763
strategy_survival_results.USDCAD.json         2,737
strategy_survival_results.USDJPY.json         2,737
strategy_survival_results.json          145,194,027
strategy_survival_results.csv            12,386,597
```

**Structural consistency:**

- Per-pair JSON files vs combined `per_pair[<pair>]` entries: **zero differing keys across all four pairs** (verified by python dict-diff).
- CSV row count: 82,156 lines = 1 header + 82,155 rows = exactly GBPUSD `candidate_rows` count. Non-GBPUSD pairs contribute zero rows (correct — their `candidate_rows` are empty).
- Every pair carries `run_started_utc`, `run_completed_utc`, `run_duration_sec`, `bars_loaded`, `families`, `not_replayable`, `manifest_path`, `manifest_sha256`, `configuration_manifest_hash`, `identity_manifest_git_sha`.
- `manifest_sha256 = 0ea3608f9ebda7475670522106af5f69b2276da09a56fb56c8e6343fea77cd82` on every pair (single certified corpus).
- `identity_manifest_git_sha = 1044213d58ed88d7fa37dfa955cdae72b4aede59` on every pair (single certified worktree HEAD).

**Small non-GBPUSD file explanation.** EURUSD/USDCAD/USDJPY files are 2.7 KB each because every one of the 10 registered families is declared `NOT_APPLICABLE_TO_PAIR` for those pairs (current production wiring is GBPUSD-specific). This is a legitimate outcome and matches `run_manifest.json`'s `exclusions_and_blockers` block. The files carry structured `NOT_APPLICABLE_TO_PAIR` records with `production_pairs: ["GBPUSD"]` and per-family reasons.

**Runner determinism.** The runner is single-shot by design; the manifest declares `deterministic_rerun_fingerprint_recipe = sha256(json.dumps(candidate_rows, sort_keys=True))`. No rerun performed (per protocol: exactly one frozen run).

---

## 2. Family classification (Lane A)

### 2.1 GBPUSD — replayable (3 families, 82,034 admissible of 82,155 total)

Setup-treated-as-entry per §8; SL 20 pips / TP 100 pips; horizons 10, 20, 40 bars; cost provenance UNAPPLIED with sensitivity bands [0.0, 1.0, 2.0] pips.

| Family | n | admissible | wins h40 | losses h40 | open h40 | gross h40 (c=0) | h40 @ c=1 | h40 @ c=2 | per-cand @ c=1 |
|---|---|---|---|---|---|---|---|---|---|
| BB_BOUNCE | 11,296 | 11,278 | 32 | 3,683 | 7,563 | +5,306 p | **-5,972 p** | -17,250 p | **-0.53 p** |
| BB_NEAR_TOUCH | 70,543 | 70,441 | 176 | 14,072 | 56,193 | +24,779 p | **-45,662 p** | -116,103 p | **-0.65 p** |
| LEVEL_BOUNCE | 316 | 315 | 2 | 83 | 230 | +889.65 p | **+574.65 p** | +259.65 p | **+1.82 p** |

### 2.2 GBPUSD — not_replayable (7 families)

Reason per `families_registry.py`; each family requires live production runtime state that the frozen replay cannot reconstruct from candles alone.

| Family | Reason |
|---|---|
| QM_SDE | Shadow2 does not claim behavioural equivalence to production QM outputs (`qm_sde_replay_scaffold.py:20`) |
| TREND_V3 | Live H1/D1 htf_cache + regime engine + ribbon-gate singletons + MACD/cooldown ledgers |
| EMA_PULLBACK | Live indicator buffers + armed-machine state; also OFF end-to-end in production |
| STRUCTURE_BREAK | Live swing state + ribbon gate + structural target computer reading H1/D1 caches |
| CONFIRMATION_FALLBACK | Confirmation-engine live rolling state + prior candidate ledger |
| NEWS_TREND | `news_release_window` buffer + NEWS_TREND_ROUTER live state; historical snapshots not stored |
| BB_REVERSAL_PATTERNS | Per-strategy pattern state (ARC/V/near-touch tiers) + live BB history + regime cache |

### 2.3 EURUSD / USDCAD / USDJPY — NOT_APPLICABLE_TO_PAIR

All 10 registered families are GBPUSD-only in current production wiring. Extending to other pairs is a wiring change, not a study change. Zero candidates emitted from these pairs is the correct study result.

---

## 3. Portfolio proposal (unchanged from the pre-run draft — now confirmed by the frozen numbers)

The pre-run `strategy_portfolio_proposal.json` (2026-09-18 13:41) drafted the classification anticipating the frozen numbers. The completed run has confirmed those numbers to the pip. No modification to the proposal is required. Recap:

- `families_retained_live`: **empty**
- `families_constrained_to_segment`: **empty**
- `families_placed_in_shadow`: **empty**
- `families_insufficient_evidence`: BB_BOUNCE, BB_NEAR_TOUCH, LEVEL_BOUNCE
- `families_not_replayable_in_this_batch`: 7 (as above)
- `flag_changes_that_would_be_made`: **NONE**
- `rollback_flags.flags`: **empty** (no changes → no rollbacks)

### 3.1 Bucket-level evidence supporting "insufficient" for each replayable family

**BB_BOUNCE.** Every horizon is net-negative at 1-pip cost. The only bucket that survives 1-pip cost is BIG_NEWS day-type (n=655, +1.01 p/cand at c=1, +0.008 p/cand at c=2 — marginal at 2p). Not enough evidence to promote a BIG_NEWS-only carve-out under §8's complexity ceiling.

**BB_NEAR_TOUCH.** All 70,441 admissible candidates are massively net-negative at 1-pip cost (-45,662 p total h40). No session, day-type, or direction subset survives.

**LEVEL_BOUNCE.** Only positive family at cost. Bucket structure (h20, per-cand @ c=1 pip):

| Session | n | per-cand @ 1p | verdict |
|---|---|---|---|
| LONDON | 109 | **+3.16 p** | strongest |
| NY | 119 | **+3.08 p** | strong |
| UNKNOWN | 41 | +0.01 p | flat |
| ASIA | 46 | -2.51 p | negative |

| Direction | n | per-cand @ 1p |
|---|---|---|
| SHORT | 178 | **+3.09 p** |
| LONG | 137 | +0.34 p |

| Day-type | n | per-cand @ 1p |
|---|---|---|
| POST_NEWS | 54 | +3.46 p |
| NORMAL | 69 | +2.02 p |
| BIG_NEWS | 60 | +1.62 p |
| PRE_NEWS | 52 | +1.63 p |
| MID_NEWS | 80 | +1.10 p |

The LONDON+NY, SHORT-dominant, non-ASIA picture is consistent with a level-retest bounce that needs session liquidity to close. **But the sample is 315 candidates total — 228 in LONDON+NY, 178 SHORT — and the LEVEL_BOUNCE pivot cache is absent before 2026-01-02 (`pivots_unavailable`) which truncates the archive window. Bootstrap CI is not yet computed and Lane B is not yet populated.** §15 requires Lane A + Lane B agreement for any global promotion; this batch delivers only Lane A. Portfolio verdict: **INSUFFICIENT_EVIDENCE**, keep current live configuration unchanged, expand pivot cache coverage before a live decision.

---

## 4. Constraints and caveats explicit in this batch

1. **Lane A only.** Lane B (prospective accumulator, §15) is `CONTRACT_READY_AWAITING_PROSPECTIVE_POPULATION`. No global promotion admissible from this batch alone.
2. **Cost model is UNAPPLIED.** All headline numbers are on GROSS_PRICE_PATH; the [0, 1, 2] pip cost sensitivity bands are external not measured. Real GBPUSD spread + slippage varies by session; a 1-pip band is a reasonable London/NY yardstick, less so for Asia.
3. **Setup-treated-as-entry (§8).** BB_BOUNCE / BB_NEAR_TOUCH / LEVEL_BOUNCE are graded at setup detection; the production arm/rejection lifecycle is not reproduced (would require per-session touch counters + gate state). Actual live entries are a subset of setups; expect lower absolute candidate counts under production wiring, and the family expectancies here are upper bounds on what production would trade.
4. **Open-at-horizon fraction is high.** h40 open fractions: BB_BOUNCE 67%, BB_NEAR_TOUCH 80%, LEVEL_BOUNCE 73%. The pip yields are dominated by the resolved minority + MFE/MAE proxies at horizon end. Portfolio impact depends on how production monetises "still open at horizon."
5. **LEVEL_BOUNCE archive truncation.** No pivots pre-2026-01-02; the 315 candidates are concentrated in a narrower window than the nominal 2.5-year study span.
6. **`intrabar_ambiguous = 0` across all admissible families.** §7 ambiguity handling exists in the harness (INTRABAR_AMBIGUOUS → conservative primary + optimistic upper bound) but did not fire on this corpus — bar granularity and SL/TP separation kept every resolved candidate unambiguous.

---

## 5. Next batches (not authorised here)

1. **Bootstrap CI computation.** Daily-block bootstrap 1000+ resamples over the 82,155 frozen candidate rows in `strategy_survival_results.csv`. Required by acceptance-check §1 in the proposal before any flag change.
2. **Lane B prospective accumulator.** Begin the ≥3-month prospective evidence window per §15. Global promotion remains INADMISSIBLE until Lane B is populated.
3. **QM behavioural-equivalence certification.** If `qm_decision_shadow.on_5m_close_sde` (driven via `qm_sde_replay_scaffold.py`) can be certified to reproduce production QM outputs across the golden windows, flip QM_SDE to REPLAYABLE and re-run the frozen comparison once for QM_SDE.
4. **Pivot cache backfill for LEVEL_BOUNCE.** Extend pivot cache coverage back through the study window so LEVEL_BOUNCE evaluations pre-2026-01-02 stop emitting `pivots_unavailable`. Then re-run the frozen comparison once for LEVEL_BOUNCE (or all three replayable families) with the extended coverage.
5. **CATEGORY_COVERAGE_STUBS population.** Populate the golden set with specific bars once operator approves selection criteria.

---

## 6. Identity chain (audit)

- Frozen protocol: `docs/frozen_evidence_protocol_shadow2_20260918.md` (sha256/16 `7b648ce83df53541`)
- Worktree: `/opt/tradingbot/.claude/worktrees/phase2b-apparatus`
- Worktree HEAD: `1044213d58ed88d7fa37dfa955cdae72b4aede59` (shadow2_research_head)
- Shadow2 baseline: `b400c6ea856c701c6e3617e60ea6af0b436bd389`
- Approved production HEAD: `00d1ce670ea4d961e3bd809569ecf4cd1d0a462d` (occupancy-repair rev.3)
- Corpus manifest sha256/32: `0ea3608f9ebda7475670522106af5f69`
- Harness certification: 42 tests passed (23 foundation + 19 harness-run) — `harness_certification.json`
- Protected-file baseline: `PROOF_HOLDS` vs approved production HEAD 00d1ce6 (`central_execution_gate.py`, `trade_executor.py`, `trade_manager.py` unchanged from Shadow1 baseline; intervening changes are exactly the reviewed occupancy-repair series e38efa7 → bfd5de8 → 00d1ce6)
- Sys.path isolation active during run; write firewalls active during run; no broker / gate / trade_executor import in harness source (source-scan verified)

## 7. Read-only artefacts on disk

Location: `/mnt/volume_lon1_1778405456698/derived/autobot_strategy_study/`

- `strategy_survival_results.json` (145.2 MB) — combined per_pair dictionary
- `strategy_survival_results.csv` (12.4 MB) — 82,155 candidate rows, 17-column schema
- `strategy_survival_results.{GBPUSD,EURUSD,USDCAD,USDJPY}.json` — per-pair intermediate writes
- `strategy_portfolio_proposal.json` — flag-change proposal (unchanged from 13:41 draft; now confirmed)
- `run_manifest.json` — run identity, git shas, protocol, exclusions
- `harness_certification.json` — 42/42 tests, firewalls, isolation record
- `candle_corpus_manifest.jsonl` — 2,946 rows, sha256/32 `0ea3608f9ebda7475670522106af5f69`
- `corpus_certification.json`, `corpus_gaps.jsonl`, `corpus_conflicts.jsonl` — corpus audit

## 8. Verdict

Frozen comparison **COMPLETED** without live-trading side effects. Recovery from client disconnect **CLEAN** — one runner alive the entire time, no duplicates, no signals sent. Output integrity **VALIDATED**. Family classification and portfolio proposal **CONFIRMED**. Flag-change delta **ZERO**. Next required batches queued.
