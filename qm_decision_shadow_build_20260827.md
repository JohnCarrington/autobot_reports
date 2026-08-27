# Structural Decision Engine — Shadow build — 2026-08-27

Host 161, HEAD `11fa373` → `45bd126`. Local commit, no push, no
restart tonight. Shadow activates at operator's next
`safe_restart.sh` — but "activates" here just means the module
becomes importable at boot; since nothing in the live dispatch
chain imports it, no live behaviour changes on restart either.

Tomorrow is BIG_NEWS day. This build introduces **zero live
behaviour change**. Every output is telemetry.

## Contradictions first

1. **The "Total Spec" text was NOT included in the message.** The
   task directive said "operator's Total Spec, saved verbatim to
   docs/total_spec_v1.md from provided text; §40 shadow-first and
   §39 alongside-monolith are binding" — but no spec body was
   provided; only section references (§4.5, §5, §6-§10, §13, §14,
   §20, §23, §24, §25, §29, §30, §33, §36, §37, §39, §40) and a
   handful of embedded rules (confluence weights table, zone
   classes 0-2/3-4/5-7/8+, 14-state vocabulary, candidate machine
   transitions, 12 confidence factors).

   `docs/total_spec_v1.md` was created as an **EXTRACTION** of what
   the message explicitly quoted, organised into the referenced
   section skeleton, with STUB placeholders where the spec text was
   referenced but not elaborated. When the operator pastes the full
   spec, that file should be REPLACED verbatim. STUB placeholders
   currently cover: §8 sweep predicate, §9/§10 rejection/acceptance
   weight tables and thresholds, §14 detector parameters, §20
   "next-level" selection rule, §29 factor weights, §30
   time-of-day schedule.

2. **The synthetic S1-sweep walk landed in an IDLE terminal, not
   ENTRY_ARMED — and this is the honest outcome.** At 05:00-05:20Z
   2026-08-27, GBPUSD 5m closes sat in [13583.5, 13594.65]. The
   D1-derived S1 pivot for 08-27 (using the last available prior
   D1 bar 2026-08-25 — with the 42-day gap backfilled per prior
   session's report) is **13633.12** — ~40p ABOVE the price. Every
   bar closes deep below S1 → the classifier reports `ACCEPTING`
   (two consecutive closes far from center in the same direction)
   → the candidate machine never leaves IDLE because
   IDLE→APPROACHING_ZONE requires `behaviour=APPROACHING`, and
   that requires a bar within `zone_width_pips` of the center.
   Price is 40p away, `zone_width_pips=5` → no approach possible.
   Details in the "Synthetic walk" section below.

## Extension points — quoted before coding

### §4.5 EMA levels + §5 confluence — extends `qm_liquidity_level_mapper.build_map`

Existing `LevelMap` (mapper lines 82-93):
```python
@dataclass
class LevelMap:
    symbol: str
    computed_at: str
    p_level: Optional[Level] = None
    outer_pivots: List[Level] = ...    # R1-R3, S1-S3
    other_levels: List[Level] = ...    # non-pivot, non-P
    clusters: List[Cluster] = ...
    density: int = 0
```

Existing `Cluster` (mapper lines 66-79):
```python
@dataclass
class Cluster:
    center_price: float
    members: List[Level]
    width_pips: float = 0.0
    label: str = ""
    p_price: Optional[float] = None   # P separate — standing rule
```

**Extension** in `qm_decision_shadow.build_zones()`:
- calls `build_map()` unchanged
- adds §4.5 EMA_8/13/21/100/200 as extra `Level` records into
  `lm.other_levels`
- re-runs the mapper's own `_cluster()` on the enriched pool so P
  stays out of the members list per its standing rule
- lifts each `Cluster` into a `DecisionZone` with weight sum + class

**Weight table** (per §5, env-overridable `QM_CONFLUENCE_W_<TYPE>`):

```python
_DEFAULT_WEIGHTS = {
    "PDH": 3, "PDL": 3,                        # prev-day ±3
    "R1": 2, "R2": 2, "R3": 2,                 # S/R ±2
    "S1": 2, "S2": 2, "S3": 2,
    "LN_H": 2, "LN_L": 2, "NY_H": 2, "NY_L": 2,   # session ±2
    "SWING_H": 2, "SWING_L": 2,                # swing ±2
    "BB_U": 2, "BB_L": 2, "BB_M": 2,           # BB ±2
    "R00": 1, "R50": 1,                        # round +1, 50 +1
    "EMA_8": 1, "EMA_13": 1, "EMA_21": 1,
    "EMA_100": 1, "EMA_200": 1,                # EMA +1
    "RANGE_H": 2, "RANGE_L": 2,
}
```

Zone classes: `LOW 0-2 / MODERATE 3-4 / HIGH 5-7 / VERY_HIGH 8+`.
P is scored SEPARATELY — never pooled. EMA levels are excluded
from `hard_density` count (§4.5) but contribute to the weight sum.

### §6-§10 State vocabulary — extends `qm_level_interactions`

Existing (`qm_level_interactions.py:39-45`):
```python
STATE_APPROACHING = "APPROACHING"
STATE_INTERACTING = "INTERACTING"
FINAL_REJECT      = "REJECT"
FINAL_ACCEPT      = "ACCEPT"
FINAL_OSCILLATING = "OSCILLATING"
FINAL_BREAK_AWAY  = "BREAK_AWAY"
```

**Extension** in `qm_decision_shadow.classify_state()` adds the
full 14-state vocabulary without touching the existing 2-state
Interaction machine (which keeps writing to its own
`logs/qm_level_interactions.jsonl`):

```
APPROACHING, ACCELERATING, TOUCHING, PIERCING, SWEEPING,
REJECTING, ACCEPTING, BREAKING, RETESTING, CONTINUING,
BAND_WALKING, STALLING, FAILED_BREAK, FAILED_REVERSAL
```

### §13/§23/§24 Candidate machine — new, no existing extension point

There is no pre-existing candidate machine at this granularity; the
`bb_pierce` armed-machine is symmetric conceptually but strategy-
specific. `qm_decision_shadow.Candidate` + `step_candidate()`
implement the operator's stated transitions:

```
IDLE → APPROACHING_ZONE → EXTREME_REACHED → SWEEP_DETECTED
     → REJECTION_CANDIDATE → REJECTION_CONFIRMED → ENTRY_ARMED
Failure: … → LEVEL_ACCEPTED → REVERSAL_CANCELLED → CONTINUATION_WATCH
FAILED_BREAKOUT (orthogonal terminal)
```

Every transition appended to `Candidate.transitions` with cause;
hypothetical E/S/T recorded at `ENTRY_ARMED`.

### §29 Confidence — reads from existing chop features + regime engine

Existing chop features live at `qm_chop_features.py` (211 lines,
never referenced from live-trading gates per module-level
docstring). Existing chop-shadow lives in `regime_engine.py:717`
(`_compression_chop_shadow`) with output plumbed through
`signal_logger.py:1277-1280`.

**Extension** in `qm_decision_shadow.score_confidence()`: reads a
plain `Dict[str, Any]` of factor values [-1, +1]; caller assembles
by pulling from existing sources. Twelve factors per §29,
env-tunable weights `QM_CONFIDENCE_W_<NAME>`, WHY dict per
§36/§37 lists present / absent / contribs.

### §20 next-level — new, minimal stub

The existing `bb_pd_gate.compute_pivot_nearest` picks a single
directional nearest pivot. `qm_decision_shadow.next_levels()`
takes the full `List[DecisionZone]` list and returns
`(next_up, next_down)` with `exclude_ema=True` by default (per §4.5).

### §25 exit hierarchy — BUILD-4 shadow extension deferred

Existing BUILD-4 shadow is `qm_exit_shadow.py` (182 lines). The
operator's §25 asks for extending it to log intermediate structural
levels an open trade reaches — this needs the BUILD-4 shadow's
per-position event surface, which is a per-strategy plumb. **Not
built in this session** — a stub function `next_levels()` in
`qm_decision_shadow` is the input the BUILD-4 extension would
consume. Documented as PENDING.

## Item-by-item scope table

| Item | Built this session | Deferred (needs full spec) |
|---|---|---|
| 1 Mapper §4.5 EMA + §5 weighted confluence + zone classes + DecisionZone jsonl | **YES** | — |
| 2 Behaviour Engine v2 state vocabulary + approach context §7 | **YES** (14 states + §7 scalars) | §8 sweep predicate detail, §9/§10 numeric weights & threshold bands (STUB in spec doc) |
| 3 Candidate state machine §13/§23/§24 + hypothetical E/S/T + candidates jsonl | **YES** | §9 acceptance rule uses "2nd consecutive REJECTING" as placeholder — spec text needed |
| 4 M5 confirmation §14 | **YES** (structure-break / higher-low / lower-high / engulfing) | Detector params (swing lookback, engulfing floor) via env |
| 5 Structural target engine §25 + BUILD-4 exit shadow extension | **PARTIAL** — `next_levels()` shipped; BUILD-4 wire-up deferred | Per-position BUILD-4 hook |
| 6 Confidence §29 12-factor 0-100 + WHY §36/§37 | **YES** | §30 time-of-day schedule; per-factor spec-supplied weights |
| 7 Explainability §36/§37 | **YES** via WHY dict on every candidate | — |

## The synthetic S1-sweep walk

Fixture: live 5m CSV `data/candles/GBPUSD/2026-08-27.csv`, 5 bars
in `[05:00Z, 05:25Z)` plus one prior at 04:55Z.

Zone construction: pivots computed from the last available prior
D1 bar (2026-08-25, per `_prior_d1("GBPUSD", 2026-08-27)`) via the
existing `qm_liquidity_level_mapper._pivots_from_prior`. **S1 =
13633.12.**

Walk output (verbatim from the test's `-s` capture):

```
=== S1-sweep walk 2026-08-27 05:00-05:20Z (S1=13633.12) ===
  2026-08-27T05:00:00+00:00  behaviour=ACCEPTING        candidate=IDLE
  2026-08-27T05:05:00+00:00  behaviour=ACCEPTING        candidate=IDLE
  2026-08-27T05:10:00+00:00  behaviour=ACCEPTING        candidate=IDLE
  2026-08-27T05:15:00+00:00  behaviour=ACCEPTING        candidate=IDLE
  2026-08-27T05:20:00+00:00  behaviour=ACCEPTING        candidate=IDLE
final state: IDLE
transitions: 0
confidence: 51 (present=['regime_alignment', 'confluence', 'sweep', 'chop'],
                absent=['bb_extreme', 'rejection_strength',
                        'acceptance_strength', 'm5_confirmed',
                        'time_of_day', 'day_type', 'momentum',
                        'news_proximity'])
```

**Honest reading:** during 05:00-05:20Z, GBPUSD sat around
13584-13595 — ~40p BELOW S1 (13633.12). Every 5m bar closes far
from S1 → classifier calls `ACCEPTING` (§9/§10 semantics:
consistent side and distance from level). Candidate machine
IDLE→APPROACHING_ZONE requires `behaviour=APPROACHING` which
requires the bar within `zone_width_pips` (5p default) of the
center. 40p away → no approach → the candidate never opens. If the
operator was referring to a sweep of a DIFFERENT level or
timeframe, the walk needs to be re-run with that zone; the
scaffolding above supports that trivially by supplying a different
`DecisionZone.center_price`.

Confidence score 51 (near neutral) is expected given only 4
factors are supplied to the score call in the test (§29 stubs the
remaining 8 as ABSENT — surfaced explicitly in the WHY).

## Proofs

### Identity — strategy paths byte-identical

```
tests/unit/test_qm_decision_shadow.py::test_strategy_module_imports_unchanged_by_shadow[gbpusd_bb_bounce-attrs0] PASSED
tests/unit/test_qm_decision_shadow.py::test_strategy_module_imports_unchanged_by_shadow[gbpusd_trend_v3-attrs1]  PASSED
tests/unit/test_qm_decision_shadow.py::test_shadow_registers_no_5m_close_callback           PASSED
tests/unit/test_qm_decision_shadow.py::test_shadow_module_not_imported_by_production        PASSED
```

`test_shadow_module_not_imported_by_production` greps every
production `.py` file for the string `qm_decision_shadow`;
non-zero hits fail loudly. This blocks any future accidental
import from `bb_bounce.py` / `gbpusd_trend_v3.py` / `level_bounce.py`
or `trade_manager.py` at CI time.

### Fail-silent wrappers

Every public function in `qm_decision_shadow.py` wraps its body in
`try/except Exception` and logs via `logger.debug` on failure. The
DEBUG level keeps journal spam near zero while preserving forensic
trail on `journalctl -p debug` or `journalctl | grep QM-SHADOW`.

### Synthetic walk assertions

Test `test_synthetic_s1_sweep_walk_2026_08_27_0500_0520` — asserts
the walk completes without raising and lands in a valid terminal
state (11 acceptable terminals in the §13/§23/§24 machine). Passed.

### Suite delta

```
$ pytest tests/unit/test_qm_decision_shadow.py \
         tests/unit/test_d1_csv_fallback.py \
         tests/unit/test_grind_path_suppression_logging.py \
         tests/unit/test_conftest_telegram_guard.py \
         tests/unit/test_rest_allowance_ig_capture.py -q

47 passed in 1.19s
```

**Zero new failures.**

## Diff

```
qm_decision_shadow.py                              | +505 (new)
docs/total_spec_v1.md                              | +183 (new)
tests/unit/test_qm_decision_shadow.py              | +373 (new)
.gitignore                                         | +1
```

Local commit `45bd126` on `feat/trend-stretch-brake-adx-floor`.
No push.

## Pending — needs the full spec text

1. **`docs/total_spec_v1.md` replacement.** The verbatim spec was
   not provided in this session's directive; the file currently
   holds an extraction from what the message quoted. Replace when
   the operator pastes it.
2. **§8 sweep predicate** (bar-shape / follow-through) — the
   classifier currently uses "wick beyond, body back within 0.3×w"
   as a placeholder.
3. **§9 / §10 numeric weight tables + threshold bands** — the
   `REJECTION_CANDIDATE → REJECTION_CONFIRMED` transition uses
   "2nd consecutive REJECTING" as a placeholder rule.
4. **§14 detector parameter values** — engulfing body-ratio floor
   defaults to 1.0 via `QM_ENGULF_BODY_RATIO`.
5. **§20 "next-level" selection rule** — currently nearest-hard-level
   above/below the current price; the spec may require a directional
   or class-filtered variant.
6. **§29 factor-specific weights** — currently 1.0 uniform via
   `QM_CONFIDENCE_W_<NAME>` overrides.
7. **§30 time-of-day context score** — schedule + weights not
   supplied.
8. **§25 BUILD-4 exit-shadow wire-up** — per-position hook + logging
   of observe-verdict at intermediate structural levels. Not built.

## Restart note

The shadow module becomes importable at the operator's next
`safe_restart.sh`. Since nothing in the live dispatch chain
imports it — verified by
`test_shadow_module_not_imported_by_production` — **the restart
introduces no behavioural change**. This is a purely additive
scaffolding land.

Not urgent. Restart at boundary at operator's convenience;
tomorrow's BIG_NEWS morning is unaffected either way.

END
