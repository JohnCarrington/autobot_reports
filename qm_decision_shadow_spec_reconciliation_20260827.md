# Spec reconciliation — Shadow build vs verbatim Total Spec — 2026-08-27

Host 161, HEAD `45bd126` → `d3c698c`. Local commit, no push, no
restart. `docs/total_spec_v1.md` now holds the operator's verbatim
spec text (replacing the extraction placeholder shipped in the
prior turn). Numeric behaviour the spec supplies has been filled in
the shadow module; §39/§40 invariants preserved.

## Contradiction resolved

Prior report's opening contradiction ("the Total Spec text was NOT
included in the message") is discharged: the operator supplied the
full spec text this turn, and `docs/total_spec_v1.md` has been
replaced verbatim with it (§1 through §45, 970 lines).

## Cross-check: what was RIGHT vs what needed FILLING

| Spec clause | Prior shadow build | Post-verbatim |
|---|---|---|
| §5 confluence weight table | Matched (PDL +3, S/R +2, session +2, swing +2, BB +2, round +1, 50 +1, EMA +1) | Unchanged — verified |
| §5 zone class bands 0-2/3-4/5-7/8+ | Matched | Unchanged — verified |
| §5 P scored separately | Matched | Unchanged — verified |
| §6 14-state vocabulary | Matched | Unchanged — verified |
| §13 candidate machine transitions | Matched (IDLE → APPROACHING → EXTREME → SWEEP → REJECTION_CANDIDATE → REJECTION_CONFIRMED → ENTRY_ARMED + failure branch) | Unchanged — verified |
| §29 12-factor list | Matched | Unchanged — verified |
| §9 rejection scoring | **STUB** — placeholder "2nd consecutive REJECTING" | **FILLED** — verbatim weight table + threshold bands (see below) |
| §14 M5 signals | Partial — had structure break / higher-low / engulfing | **EXTENDED** — added short EMA recapture + failed retest (both in spec's list) |
| §30 time-of-day | STUB (no bands supplied) | **FILLED** — 08/10/11/12/14/15/16 BST clusters, 15-min falloff window |
| §29 threshold values | STUB (>=70 eligible / >=80 countertrend) | Documented in spec, kept env-configurable per §38 |
| §8 sweep predicate | Placeholder ("wick beyond, body back within 0.3×w") | Spec §8 supplies the CONCEPT (trades beyond then returns) but no specific bar-shape ratio — placeholder retained; spec does not supersede |
| §10 acceptance weights | STUB | Spec lists signals but does NOT supply numeric weights — placeholder retained |
| §20 mean-reversion hierarchy | STUB (nearest-hard-level up/down) | Spec supplies verbatim 6-level ladder (round → BB mid → EMA cluster → pivot → opposite BB → next structural) — **DEFERRED to Phase 6 per §44** |
| §17 fast trend promotion | Not built | **DEFERRED to Phase 5 per §44** |
| §18 band-walking detector | Not built (only vocabulary state) | **DEFERRED to Phase 5 per §44** |
| §22 adaptive opposite-BB exit | Not built | **DEFERRED to Phase 6 per §44** |
| §23/§24 failed reversal/breakout | Not built as dedicated recognizer | **DEFERRED to Phase 3 per §44** |
| §25 BUILD-4 per-position hook | Not wired | **DEFERRED to Phase 6 per §44** |
| §28 chop score aggregate | Reads existing `qm_chop_features` | **DEFERRED to Phase 3 per §44** |
| §35 state priority hierarchy | Not encoded | **DEFERRED to Phase 8 per §44** |
| §41 A-F acceptance scenarios | Not built as tests | **DEFERRED to Phase 9 per §44** |

## §9 rejection scoring — verbatim implementation

The spec's exact table (§9):
```
level swept                  +2
close back through level     +3
close inside BB              +2
large reversal candle        +2
M5 structure shift           +3
momentum reversal            +1

0-3  = weak
4-6  = possible
7-9  = strong
10+  = very strong
```

Shipped in `qm_decision_shadow.score_rejection(signals) → (int, str)`
where `signals: Dict[str, bool]` with keys matching the table snake-
cased. Env override per weight: `QM_REJECTION_W_<KEY>`.

Candidate machine now consumes this: `REJECTION_CANDIDATE →
REJECTION_CONFIRMED` requires `rejection_score >= 7` (strong band)
when the caller supplies `rejection_signals` in
`candidate.confidence_why`. Weak scores stay in `CANDIDATE` (do NOT
revert — a weak signal doesn't invalidate the candidacy, only fails
to confirm it). Falls back to the prior "2nd consecutive REJECTING"
rule when signals aren't supplied so tests and cold-start callers
remain honest.

Verified in `test_rejection_scoring_matches_spec_weight_table` +
`test_candidate_transition_requires_strong_rejection_score`.

## §14 M5 confirmation — extensions

Spec §14 lists:
1. break of previous M5 swing high (BUY) / low (SELL) — HAD
2. bullish/bearish engulfing — HAD
3. rejection candle followed by confirmation — implicit in state chain
4. micro structure break — HAD
5. **short EMA recapture** — ADDED
6. **failed retest of the extreme** — ADDED

Signature extension:
```python
def m5_confirmations(prior_bars, cur_bar, direction,
                     ema_short_at_bar=None,   # NEW
                     extreme_price=None):      # NEW
```

Both optional so existing test callers keep working. Verified in
`test_m5_short_ema_recapture_signal` + `test_m5_failed_retest_signal`.

## §30 time-of-day — verbatim BST cluster hours

Spec §30 verbatim list: 08:00, 10:00, 11:00, 12:00, 14:00, 15:00,
16:00 BST.

Shipped:
```python
def time_context_score(now_utc: datetime, is_bst: bool = True) -> float
```
Returns 0.0-1.0. Peak 1.0 at any listed BST hour, linear falloff
across `QM_TOD_WINDOW_MIN` (default 15). Off-window → 0.0.

The `is_bst` param is caller-supplied — no automatic DST detection
inside the shadow (keeps the function pure and testable). Callers
that need DST awareness read the existing bot's is_bst plumbing.

Verified in `test_time_context_score_peaks_at_bst_cluster_hours` —
07:00 UTC = 08:00 BST → 1.0 (peak), 07:07 UTC = 08:07 BST → 0.53
(mid-window), 07:15 UTC = 08:15 BST → 0.0 (window edge), 04:00 UTC =
05:00 BST → 0.0 (no cluster).

## §39/§40 invariants — still binding, still verified

- `test_shadow_module_not_imported_by_production` — passes (0 hits).
- `test_strategy_module_imports_unchanged_by_shadow` for
  `gbpusd_bb_bounce` + `gbpusd_trend_v3` — passes.
- `test_shadow_registers_no_5m_close_callback` — passes.

Suite delta: **52 pass** on the touched slate (was 47 last turn),
zero new failures. 5 new tests added this turn:
- `test_rejection_scoring_matches_spec_weight_table`
- `test_candidate_transition_requires_strong_rejection_score`
- `test_time_context_score_peaks_at_bst_cluster_hours`
- `test_m5_short_ema_recapture_signal`
- `test_m5_failed_retest_signal`

## Diff

```
docs/total_spec_v1.md                    | +1937 −183 (rewrite 97%)
qm_decision_shadow.py                    |  +108 −6
tests/unit/test_qm_decision_shadow.py    |  +120 −0
```

Local commit `d3c698c` on `feat/trend-stretch-brake-adx-floor`.
No push.

## Restart note

No behaviour change. Shadow still imported by nothing in the live
dispatch chain. The restart at operator's boundary picks up the
enriched `qm_decision_shadow` module, but since no live code path
imports it, nothing new fires. Purely additive telemetry
scaffolding land, same as prior turn.

## Deferred phases — spec now available to drive them

Per §44 build order and now that the verbatim spec exists:

- **Phase 3 continuation**: dedicated failed-reversal (§23) /
  failed-breakout (§24) recognizers with their own state
  transitions; chop score aggregate (§28).
- **Phase 5**: fast trend promotion (§17) + band-walking
  detector (§18).
- **Phase 6**: adaptive exit manager — mean-reversion exit
  hierarchy (§20), adaptive opposite-BB exit (§22), BUILD-4
  per-position hook (§25).
- **Phase 7**: shadow-mode telemetry pipeline (§40) — jsonl
  writers already shipped; still need the per-bar orchestrator
  that walks all active zones and emits candidate rows on
  transition.
- **Phase 8**: strategy integration — the 6 named strategies
  (BB Bounce, Trend V3, EMA Pullback, Confirmation Break,
  Structure Break, Grind Trend) receive the shadow's WHY dict as
  additional stamp on their own decision records (still zero
  gating).
- **Phase 9**: live promotion — operator ruling only, after
  shadow telemetry demonstrates reliable classification against
  the §41 A-F acceptance scenarios.

None of these are required for the current shadow to be inert-
correct against the verbatim spec on the clauses that ARE numeric.

END
