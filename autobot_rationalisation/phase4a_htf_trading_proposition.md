# AutoBot V3 — Phase 4A: Higher-Timeframe Trading Proposition Engine

Generated: 2026-10-15. Branch for code: `feat/htf-trading-proposition-phase4a` on `JohnCarrington/AutoBot` (based on `nms/v3-prod-upgrade-20261013`). Branch for this report: `report/autobot-rationalisation-phase4a-20261015` on `JohnCarrington/autobot_reports`.
References: Phase 1 (operational inventory), Phase 2 (strategy performance), Phase 3 (July + V2 intelligence review).

**Hard contract — enforced by code + tests:**
- Pure, offline, observation-only engine.
- No new trading logic beyond what existing modules already encode.
- No new mandatory trade gate on V3 execution.
- No NMS override, no central_execution_gate modification, no .env edit.
- No new candle data requested from IG; no new price-history REST calls.
- Static-ast test verifies the engine imports **zero** execution surfaces.

**What was built:** a module (`htf_trading_proposition.py`), a replay harness (`scripts/htf_proposition_replay.py`), and a unit test suite (`tests/unit/test_htf_trading_proposition.py` — 30 tests, all pass).

**What was NOT built:** anything requiring a new trading rule. Every undecided rule is enumerated below under *Design Decisions Deferred for Operator Approval*. The engine honestly returns `UNKNOWN` / `NO_PROPOSITION` where a decision is pending.

---

## 1. Implementation Map (reusable V3 components)

Every module below is **imported as read-only** by the engine. No module is modified. API signatures are reproduced from the live code at HEAD `41a3c9c`.

### 1.1 HTF regime (`htf_regime.py`)
- `classify(symbol: str) -> dict` at `htf_regime.py:650` — H1 / D1 / W1 state + 4-value alignment verdict (ALIGNED_BULL / ALIGNED_BEAR / CONFLICTED / NEUTRAL). Pure; reads htf_cache.
- Returns keys include `h1_state`, `h1_strength`, `d1_state`, `w1_state`, `alignment`, `debug.{h1_reason, d1_reason, w1_reason}`.
- **No H4 output** — see Gap 1 below.

### 1.2 Hierarchical structure (`htf_structure.py`)
- `build_snapshot(pair, *, h1_candles=None, d1_candles=None, w1_candles=None, m1_candles=None, now_utc=None) -> dict` at `htf_structure.py:471`.
- Per-timeframe snapshot: `direction`, `current_leg`, `structure`, `last_swing_high`, `last_swing_low`, `last_bos`, `last_choch`, `sufficient_data`.
- Cross-timeframe `relationships`: REL_ALIGNED / REL_CORRECTIVE / REL_MIXED / REL_UNRESOLVED / REL_INSUFFICIENT.
- Closed-bar discipline enforced internally.

### 1.3 M5 structural detector (`market_structure.py`)
- `detect_confirmed_swings`, `classify_structure`, `detect_bos`, `detect_choch`, `wilder_atr`, `analyze` at `market_structure.py:58, 102, 141, 168, 244, 285`.
- Walk-forward safe (never reads bars past `asof` index).
- **Reused by htf_structure for per-TF structural computation.**

### 1.4 Levels & zones
- `levels_engine.compute_levels_snapshot(df_5m_closed, mid_price, ...)` at `levels_engine.py:144` — demand/supply zones, targets.support, targets.resistance.
- `qm_liquidity_level_mapper.build_map(symbol, at_ts=..., lookback_days=3) -> LevelMap` at `qm_liquidity_level_mapper.py:259` — 10 level types (R1-R3, S1-S3, P, PDH/L, LN_H/L, NY_H/L, BB_U/L, R00/R50) + confluence clustering.
- `qm_swing_levels.on_5m_close(sym, ts, o, h, l, c)` at `qm_swing_levels.py:85` — 3-bar close-cluster reject detector (stateful).

### 1.5 Level interactions (FSM)
- `qm_level_interactions.open_interaction(...)`, `update(inter, bar)`, `maybe_finalize(inter, bar)` at `qm_level_interactions.py:107, 123, 197`.
- Final states: `FINAL_REJECT`, `FINAL_ACCEPT`, `OSCILLATING`, `BREAK_AWAY`.
- Stateless event handlers — perfect for offline replay.

### 1.6 D1 directional bias (`d1_direction.py`)
- `compute_d1_direction_from_candles(pair, d1_candles, config=None)` at `d1_direction.py:439`.
- `compute_d1_direction_from_cache(pair, now_utc=None, cache_dir=None)` at `d1_direction.py:452`.
- 9-check deterministic score ±1..±9; direction BULL/BEAR/NEUTRAL; confidence strong/moderate/neutral.

### 1.7 NMS v3 directional authority (reference-only; never modified)
- `nms_v3_classifier.advance(state, bar) -> (new_state, result)` — NORMAL → RANGE → EMERGING_UP/DOWN → STRONG_UP/DOWN.
- `session_trend.session_authority(symbol)` + `load_session_authority_snapshot(symbol)` — read-only snapshot access at `session_trend.py:767, 783`.
- `nms_v3_direction_gate.check(strategy, direction, symbol) -> bool` — the direction veto that V3 strategies rely on. **The engine does NOT import this module** (see §9 integrity test). It re-applies the stated rule locally on a read-only snapshot so the proposition can carry an observational `nms_permits_direction` flag.

### 1.8 Candle access (`htf_cache.py`)
- `htf_cache.load_cached_candles(symbol, tf)` at `htf_cache.py:324` — reads D1/H1/H4/W1 from the live rolling cache.
- `htf_cache.load_persisted_5m(symbol, ...)` at `htf_cache.py:112` — merges archive + rolling + legacy, used as the archive source by the replay harness.

### 1.9 Gaps identified
1. **No H4 output from htf_regime.** The engine emits `h4_context = {"state": "UNKNOWN", "reason": "htf_regime does not produce H4 directly"}` rather than fabricating one. H4 is listed as a Deferred Decision (DD-04B equivalent) if the operator wants it added. Options: (a) extend htf_regime with an H4 classifier; (b) aggregate H1 → H4 in a thin helper; (c) rely on htf_structure which already derives per-TF direction for `h1` but not `h4`.
2. **D1 history is thin in the live cache** (observed 11 D1 bars at test time). The engine returns `d1_context.state = "SIDEWAYS"` with `reason.why = "insufficient_d1_history"` when the 9-check cannot proceed. This is a *data* gap, not a code gap. The replay harness in `from-archive` mode aggregates D1 from the M5 archive and bypasses this limitation.
3. **qm_level_interactions is stateful (per-process).** For live use the state is maintained by the main autobot process; the engine accepts a pre-computed `interaction_state` string via the `preloaded` kwarg so a replay harness or a shadow consumer can inject state deterministically.

---

## 1A. Phase 4A Scope Clarification — Continuation Observational Interface

A parallel **Phase 4B** workstream is investigating recovery of the original QM continuation detector. Phase 4A does NOT implement any continuation / reversal prediction algorithm. It only **exposes an observational interface** through which the future detector can supply a verdict:

```
CONTINUATION           — the detector asserts the current move is a continuation
NOT_CONTINUATION       — the detector asserts the current move is NOT a continuation
INSUFFICIENT_EVIDENCE  — the detector cannot say; this is the shipped default
```

**Hard invariants on this interface (test-enforced):**
- These three strings are the only legal verdicts.
- `NOT_CONTINUATION` **does NOT imply REVERSAL.** The engine never inverts a NOT_CONTINUATION verdict into a rejection proposition. A reversal proposition (STRUCTURAL_REJECTION in this engine's taxonomy) must be supported by separately-established rejection evidence — specifically `qm_level_interactions` final state. See tests `test_not_continuation_does_not_change_proposition_type_or_direction` and `test_continuation_default_is_insufficient_evidence`.
- The shipped default provider (`_default_continuation_provider`) returns `INSUFFICIENT_EVIDENCE` unconditionally. **No shipped code path produces CONTINUATION or NOT_CONTINUATION.**
- Until Phase 4B results are reviewed and approved, no provider is wired. The interface is read-only observation only.
- A provider returning a value outside `CONTINUATION_STATES` is coerced to `INSUFFICIENT_EVIDENCE`. A provider that raises is caught; `INSUFFICIENT_EVIDENCE` is still emitted. Tests `test_continuation_provider_invalid_value_coerces_to_insufficient` and `test_continuation_provider_exception_is_caught` cover both.

### 1A.1 Interface signature
```python
# Caller API
build_proposition(symbol, ..., continuation_provider=None) -> Proposition

# Provider contract
provider(symbol: str,
          now_utc: datetime,
          d1_ctx: dict,         # d1 context block
          h1_ctx: dict,         # h1 context block
          struct_ctx: dict,     # htf_structure-derived context
          level: dict | None,   # the significant level or None
         ) -> str               # one of CONTINUATION_STATES
```

### 1A.2 Verdict precedence
1. `preloaded["continuation_state"]` (replay/test override) — always wins.
2. `continuation_provider` callable (future Phase 4B wiring).
3. `_default_continuation_provider` → `INSUFFICIENT_EVIDENCE`.

### 1A.3 Proposition fields added for this interface
```
continuation_state   : one of CONTINUATION_STATES
continuation_source  : "default_provider" | "preloaded" | provider.__name__
continuation_note    : "observational only; does not modify
                        proposition_type or expected_direction"
```

The `continuation_state` field is **never** read by `classify_proposition_type`, `pick_destination`, `evaluate_status`, or `_nms_context_for`. It is a sidecar observational tag only. Any future integration (e.g. "shadow-replay propositions where continuation_state=CONTINUATION preceded V3 trend fires") happens *outside* the engine, downstream of the emitted Proposition.

### 1A.4 QM integration deferred
Per operator restriction: **no QM integration until Phase 4B findings have been reviewed and approved.** The interface exists so Phase 4B can wire a detector without further changes to this engine; it does not pre-commit the engine to any particular detector.

---

## 2. Proposition Contract

Full dataclass in `htf_trading_proposition.py`. Fields (all serialisable via `asdict()`):

```python
Proposition:
    version                       = "phase4a.v1.0"
    execution_authority           = "NONE"  # hard-coded marker
    symbol                        : str
    timestamp                     : ISO UTC

    # section 3 context (completed candles only)
    d1_context                    : {state, reason}
    h4_context                    : {state, reason}  # currently UNKNOWN (Gap 1)
    h1_context                    : {state, strength, reason}

    market_structure              : {monthly, weekly, daily, h1,
                                      relationships, closed_bar_counts}

    # section 4 level anchor
    significant_level             : {level_type, price, distance_pips,
                                      signed_pips, cluster_size,
                                      interaction_state}

    # classification (section 5)
    proposition_type              : TREND_CONTINUATION | STRUCTURAL_REJECTION
                                    | STRUCTURAL_BREAKOUT | NO_PROPOSITION
    expected_direction            : BUY | SELL | UNKNOWN
    expected_destination          : {level_type, price, distance_pips,
                                      below_minimum?}
    confirmation_condition        : str  # cites existing module semantics
    invalidation_condition        : str

    # lifecycle (section 2 statuses)
    status                        : WATCHING | AWAITING_CONFIRMATION
                                    | CONFIRMED | INVALIDATED | NO_PROPOSITION

    supporting_evidence           : [str, ...]
    nms_context                   : {prevailing, nms_state, snapshot_ts,
                                      session_date, note}
    suggested_strategy_families   : [str, ...]       # existing V3 only
    nms_permits_direction         : bool | None      # observation only

    # Phase 4A continuation observational interface (§1A)
    continuation_state            : "CONTINUATION" | "NOT_CONTINUATION"
                                    | "INSUFFICIENT_EVIDENCE"   # default
    continuation_source           : "default_provider" | "preloaded" | provider.__name__
    continuation_note             : str   # "observational only; does not modify
                                           # proposition_type or expected_direction"

    data_quality                  : {mid_price_source, closed_bar_counts,
                                      regime_has_data, structure_has_data,
                                      level_map_has_data, n_levels,
                                      d1_direction_cache_stale,
                                      destination_below_minimum}
    deferred_decisions            : [DD-01, ..., DD-08]  # by id
```

Where data is unavailable, the engine emits `UNKNOWN` on strings and `None`/`{}` on values. The engine never invents a market assessment.

---

## 3. Reusable Component Inventory

| Component | Used for | Reuse mode |
|---|---|---|
| `htf_regime.classify` | d1/h1/w1 state + alignment verdict | direct call (or preloaded) |
| `htf_structure.build_snapshot` | hierarchical structure M/W/D/H1 + relationships | pass pre-loaded D1/H1 candles |
| `d1_direction.compute_d1_direction_from_cache` / `_from_candles` | 9-check D1 bias score + direction | direct call (or preloaded) |
| `qm_liquidity_level_mapper.build_map` | 10-type level map + clustering | direct call; `at_ts` respected for historical replay |
| `qm_level_interactions` (module) | APPROACHING / INTERACTING / FINAL_{REJECT,ACCEPT,OSCILLATING} / BREAK_AWAY | state consumed via `preloaded["interaction_state"]` |
| `session_trend.load_session_authority_snapshot` | NMS v3 state (STRONG_UP, …) for observation | read-only; snapshot loaded once per build |
| `htf_cache.load_cached_candles` | D1/H1 candle fetch | direct call (or caller preloads) |

**Deliberately NOT reused** (would introduce surface area the engine must not have):
- `trade_executor`, `trade_manager`, `open_sb_now`, `close_sb_now`
- `strategy_dispatch_adapter`, `central_execution_gate`, `one_strategy_emitter`
- `nms_v3_direction_gate` (the gate module itself — rule is re-applied on a snapshot, not through the gate function)
- `qm_v2_executor`, `orchestrator_v2`, `ig_execution`

Enforced statically by `test_engine_imports_zero_execution_surfaces` which AST-parses `htf_trading_proposition.py` and asserts the import set is disjoint from `_FORBIDDEN_IMPORTS`.

---

## 4. Design Decisions Deferred for Operator Approval

Eight explicit decisions. Each needs operator ratification before the engine's output can inform any live decision. In the interim the engine uses the labelled **PROVISIONAL** defaults and flags every emitted proposition with the ID list in `deferred_decisions`.

| ID | Question | Provisional default | Options |
|---|---|---|---|
| **DD-01** | What counts as "nearby" for the significant level? | top-K=1 nearest with distance recorded | A absolute pips (≤20p), B fraction of H1 ATR (≤0.5×), C top-K regardless |
| **DD-02** | At a resistance in ALIGNED_BULL, REJECTION or CONTINUATION? | CONTINUATION on alignment, REJECTION only on explicit `qm_level_interactions` pierce/final evidence | A continuation default, B emit both candidates, C rejection default |
| **DD-03** | How is `expected_destination` picked? | next structural level in proposition direction | A next level, B PDH/PDL, C levels_engine targets |
| **DD-04** | Minimum pip distance to a defensible destination? | ≥ 15p absolute; `data_quality.destination_below_minimum` otherwise | A absolute (15p), B ATR-scaled, C no minimum |
| **DD-05** | What flips a proposition to CONFIRMED? | `qm_level_interactions.FINAL_REJECT` for rejection or BREAK_AWAY for breakout only — no new candle rules invented | A FSM-only, B FSM + M5 BoS/CHoCH, C FSM + candle pattern |
| **DD-06** | When does HTF disagreement imply NO_PROPOSITION? | never (disagreement is informational; type tree handles direction) | A never, B when D1+H4 both oppose H1, C only on REL_INSUFFICIENT |
| **DD-07** | Which existing V3 strategy to suggest per proposition type? | multi-match list of compatible families (per section 1) | A 1:1 hard-coded, B multi-match, C no suggestion |
| **DD-08** | Should the engine know a-priori that R-family / BB_U / PDH are overhead and S-family / BB_L / PDL are below (polarity table)? | geometric only — if `signed_pips == 0`, direction is UNKNOWN | A polarity table, B geometric only, C both |

Also open (data gaps, not decisions):
- **G-01: no H4 output from htf_regime** — `h4_context.state = UNKNOWN` until an H4 producer lands.
- **G-02: thin D1 cache** — live cache may have insufficient D1 history; replay harness `from-archive` mode is the workaround.
- **G-03: qm_level_interactions FSM state** must be supplied by the caller for a given bar (either live process state, replay reconstruction, or `UNKNOWN`).

---

## 5. Offline Engine (unambiguous rules only)

Shipped as `htf_trading_proposition.py` (~500 lines). Core API:

```python
build_proposition(symbol, *, now_utc=None, mid_price=None,
                   preloaded=None) -> Proposition
```

Called:
- Live: with no args beyond symbol → engine reads live cache for regime/structure/d1_direction/level_map/NMS snapshot.
- Historical replay: caller passes `preloaded` with pre-computed state so the engine does not re-fetch live cache.

Internal decision pipeline (every step is pure):
1. `_context_from_htf_regime(regime)` — shapes HTF output into D1/H1/W1 blocks + alignment.
2. `_context_from_htf_structure(struct)` — per-TF direction + current_leg + last BoS/CHoCH + relationships.
3. `_flatten_level_map(level_map)` — unifies p_level / outer_pivots / other_levels into a flat list carrying cluster size.
4. `pick_significant_level(mid, levels)` — picks top-K=1 nearest (DD-01 provisional).
5. `classify_proposition_type(d1, h1, alignment, relationships, level, interaction_state)` — DD-02 + DD-08 provisional rules.
6. `pick_destination(direction, anchor, levels, min_distance_pips)` — DD-03 + DD-04 provisional.
7. `confirmation_and_invalidation(ptype, direction, level)` — strings grounded in existing module semantics.
8. `evaluate_status(ptype, interaction_state, destination)` — DD-05 provisional (FSM-only).
9. `_nms_context_for(symbol, direction)` — read snapshot, re-apply nms_v3_direction_gate rule locally.
10. `suggest_strategy_families(ptype)` — DD-07 provisional (multi-match list).

**Status machine — provisional (DD-05):**
| Proposition type | Observed state | Status |
|---|---|---|
| STRUCTURAL_REJECTION | FINAL_REJECT | **CONFIRMED** |
| STRUCTURAL_REJECTION | FINAL_ACCEPT | INVALIDATED |
| STRUCTURAL_REJECTION | INTERACTING / APPROACHING | AWAITING_CONFIRMATION |
| STRUCTURAL_REJECTION | anything else | WATCHING |
| STRUCTURAL_BREAKOUT | BREAK_AWAY | **CONFIRMED** |
| STRUCTURAL_BREAKOUT | INTERACTING | AWAITING_CONFIRMATION |
| STRUCTURAL_BREAKOUT | anything else | WATCHING |
| TREND_CONTINUATION | any | WATCHING (no FSM match; confirmation is M5 BoS, not computed here) |
| any | destination below minimum (DD-04) | NO_PROPOSITION |

The TREND_CONTINUATION status never auto-advances past WATCHING by design — its confirmation (`M5 BoS in direction=... after pullback`) requires live M5 structure analysis which the engine can observe but does not act on.

---

## 6. Unit Tests

37 tests, all passing (`pytest tests/unit/test_htf_trading_proposition.py` → `37 passed in 0.41s`).

Covers (per Step-8 spec):
| # | Case | Test |
|---|---|---|
| 1 | D1/H4/H1 aligned trend | `test_aligned_bull_trend_emits_trend_continuation` |
| 2 | D1/H4 disagreement | `test_conflicted_htf_no_level_interaction_returns_no_proposition` |
| 3 | H1 rejection at resistance | `test_rejection_at_resistance_emits_structural_rejection_sell` |
| 4 | H1 rejection at support | `test_rejection_at_support_emits_structural_rejection_buy` |
| 5 | Breakout and acceptance | `test_breakout_acceptance_emits_structural_breakout`, `test_breakaway_is_confirmed` |
| 6 | Failed breakout / invalidation | `test_proposition_invalidation_on_rejection_fail`, `test_rejection_awaiting_then_final_reject_confirms` |
| 7 | No nearby structural level | `test_no_level_map_returns_no_proposition` |
| 8 | No defensible destination | `test_destination_below_minimum_marks_insufficient_room` |
| 9 | Incomplete HTF candles | `test_empty_regime_structure_graceful` |
| 10 | Stale market data | `test_stale_d1_direction_cache_is_surfaced` |
| 11 | NMS opposition | `test_nms_opposition_is_recorded_not_blocked` (also `test_nms_context_blocks_sell_on_strong_up`, `test_nms_context_passes_on_range`) |
| 12 | Proposition invalidation | `test_rejection_final_accept_becomes_invalidated`, `test_signed_pips_zero_returns_no_proposition` |
| 13 | Historical replay without look-ahead | `test_replay_slice_strict_look_ahead_barrier` |
| 14 | **No execution side effects — static import guard** | `test_engine_imports_zero_execution_surfaces`, `test_execution_authority_marker_is_none` |

Plus component-level sanity tests on `pick_significant_level`, `pick_destination`, `evaluate_status`, `suggest_strategy_families`, `confirmation_and_invalidation`, `_flatten_level_map`, and `_nms_context_for`.

**Continuation interface tests (§1A):**
- `test_continuation_default_is_insufficient_evidence` — default provider.
- `test_continuation_provider_is_called_and_stored` — wiring works.
- `test_continuation_provider_invalid_value_coerces_to_insufficient` — safety net.
- `test_continuation_provider_exception_is_caught` — safety net.
- `test_preloaded_continuation_state_overrides_provider` — replay/test override.
- `test_not_continuation_does_not_change_proposition_type_or_direction` — **the hard invariant**: NOT_CONTINUATION ≠ REVERSAL.
- `test_continuation_states_enumeration_is_exact` — three legal values only.

---

## 7. Historical Replay Harness

Delivered as `scripts/htf_proposition_replay.py`. Two modes:

### 7.1 `--mode live-cache`
Walks forward through requested timestamps and calls `build_proposition(symbol, now_utc=ts)` relying on the current rolling cache (`/opt/tradingbot/cache/htf/{SYM}_{H1,D1}.json` and `/opt/tradingbot/cache/session_trend_{SYM}.json`). Suitable for the trailing window the cache covers (today + ~30 days of H1 + ~11 days of D1 at measurement time).

### 7.2 `--mode from-archive`
Reconstructs the HTF context from the on-disk M5 archive:
- Loads M5 CSVs for the requested range + 14-day lookback.
- Aggregates completed H1 (12-bar window) and D1 (20+ H1 bars per FX day, 22:00 UTC boundary).
- Feeds pre-aggregated candles into `htf_structure.build_snapshot(h1_candles=..., d1_candles=...)` and `d1_direction.compute_d1_direction_from_candles(d1)`.
- Does NOT call `htf_regime.classify()` in this mode (that function reads from cache directly) — the engine notes `data_quality.regime_has_data = False` and emits `d1_context.state = UNKNOWN` as a result.

### 7.3 Look-ahead prevention (verified by test case 13)
- `_slice_until(seq, now_utc)` drops any row with `timestamp > now_utc`.
- `_aggregate_h1` drops partial-hour windows (< 12 M5 bars).
- `_aggregate_d1` drops partial-day windows (< 20 H1 bars).
- `htf_structure.build_snapshot` filters current partial month/week/day/hour via its internal `_filter_closed_*` helpers.
- `qm_liquidity_level_mapper.build_map(sym, at_ts=historical_ts)` filters its internal 5-min bar set to `<= at_ts`.

### 7.4 Example invocation
```
scripts/htf_proposition_replay.py \
    --symbol GBPUSD \
    --mode from-archive \
    --start 2026-10-14T07:00:00Z --end 2026-10-14T20:00:00Z \
    --step 60 \
    --output /tmp/replay_gbpusd_2026-10-14.jsonl
```
Output: one `Proposition` JSON object per step on stdout + the output file. The harness writes ONLY to the output path given on the command line; it does not touch live cache, logs, broker state, or any persisted file.

### 7.5 Observed replay results (2026-10-14 GBPUSD)
Running the harness `from-archive` for 2026-10-14 07:00–20:00 UTC at 60-min step produces **14 steps, all NO_PROPOSITION**. Reason: `data_quality.regime_has_data = False` (from-archive mode skips `htf_regime.classify`), so alignment is `UNKNOWN` and the type classifier falls through to NO_PROPOSITION. The engine correctly refuses to invent an alignment it does not have access to.

Running the harness `live-cache` for 2026-10-15 07:00–11:00 UTC produces **5 steps, all NO_PROPOSITION**. Reason: live `htf_regime.classify()` reports `d1_state = SIDEWAYS` with `reason.why = insufficient_d1_history` (only 11 D1 bars in cache) → alignment `NEUTRAL` → no coherent setup. The engine honestly reports the data gap rather than fabricate a proposition.

**Interpretation:** on 2026-10-14/15 the engine's conservative rules + the current data gaps combine to emit no actionable propositions. This is correct behaviour, not a defect. Resolving G-02 (D1 cache depth) or an operator ratifying DD-02 to permit alignment-only setups would change the volume of propositions emitted, not the engine's shape.

---

## 8. Example Proposition Records

Seven synthetic examples (full records in `phase4a_examples.jsonl`), each with coherent HTF state, levels, and interaction. These exercise every proposition type and lifecycle status.

### A — TREND_CONTINUATION (BUY, WATCHING)
```
HTF aligned bull, price between S1 and PDH; room to run up to BB_U
type=TREND_CONTINUATION  direction=BUY  status=WATCHING  nms_perm=True
level=PDH@13265.0  dist=10.0p  destination=BB_U@13285.0 (+20p)
confirm:    M5 BoS in direction=BUY after pullback
invalidate: M5 CHoCH against direction=BUY
families:   GBPUSD_TREND_V3_L/S, _UM_L/S, V3_EMA_L/S, GBPUSD_TREND_CONT
```

### B — STRUCTURAL_REJECTION (SELL, AWAITING_CONFIRMATION)
```
HTF conflicted (D1 DOWN, H1 UP). Price at BB_U, INTERACTING.
type=STRUCTURAL_REJECTION  direction=SELL  status=AWAITING_CONFIRMATION  nms_perm=True
level=BB_U@13285.0  dist=1.0p  destination=PDH@13265.0 (-20p)
confirm:    qm_level_interactions reaches FINAL_REJECT at level BB_U
invalidate: qm_level_interactions reaches FINAL_ACCEPT at level BB_U
families:   GBPUSD_BB_BOUNCE_L/S, V3_BB_L/S
```

### C — STRUCTURAL_REJECTION (BUY, CONFIRMED)
```
HTF conflicted (D1 UP, H1 DOWN). Price 1p above BB_L, FINAL_REJECT.
type=STRUCTURAL_REJECTION  direction=BUY  status=CONFIRMED  nms_perm=True
level=BB_L@13225.0  dist=1.0p  destination=S1@13240.0 (+15p)
confirm/invalidate: as above (qm_level_interactions)
```

### D — STRUCTURAL_BREAKOUT (BUY, CONFIRMED)
```
Aligned bull, price 10p above R1, BREAK_AWAY.
type=STRUCTURAL_BREAKOUT  direction=BUY  status=CONFIRMED  nms_perm=True
level=R1@13300.0  dist=10.0p  destination=R2@13330.0 (+30p)
confirm:    qm_level_interactions reaches BREAK_AWAY beyond level R1
invalidate: price re-enters the level zone, transitions back to INTERACTING
families:   GBPUSD_TREND_V3_L/S, GBPUSD_TREND_CONT
```

### E — NO_PROPOSITION (destination below minimum)
```
Aligned bull but BB_U and R2 only 5p apart (< DD-04 minimum 15p).
type=TREND_CONTINUATION classified, but
destination=R2@13266.0 dist=5.0p  below_minimum=True
status=NO_PROPOSITION
```

### F — Rejection + NMS directional block (observational only)
```
Rejection SELL setup. NMS state=STRONG_UP would block SELL direction.
type=STRUCTURAL_REJECTION  direction=SELL  status=AWAITING_CONFIRMATION
nms_permits_direction=False  nms_state=STRONG_UP
```
The proposition is still emitted — opportunity assessment is independent of execution permission. The `nms_permits_direction=False` flag is observational; the engine does NOT suppress the proposition because NMS says no.

### G — Signed pips exactly zero (DD-08 ambiguity)
```
Price exactly at R1, interaction FINAL_ACCEPT.
type=NO_PROPOSITION  direction=UNKNOWN  status=NO_PROPOSITION
evidence: "breakout state observed but price exactly at level
          (signed_pips=0); direction ambiguous (DD-08)"
```

All seven records are in `phase4a_examples.jsonl` with full field population.

---

## 9. Evidence of Zero Execution Side Effects

Enforced at three layers:

### 9.1 Static import audit (unit test)
`test_engine_imports_zero_execution_surfaces` parses the engine source with `ast` and asserts the top-level import set is disjoint from `_FORBIDDEN_IMPORTS`:

```python
_FORBIDDEN_IMPORTS = frozenset({
    "trade_executor", "trade_manager",
    "open_sb_now", "close_sb_now",
    "strategy_dispatch_adapter",
    "central_execution_gate", "one_strategy_emitter",
    "nms_v3_direction_gate",      # rule reapplied locally, module not imported
    "qm_v2_executor",
    "orchestrator_v2", "ig_execution",
})
```
Test passes.

### 9.2 Marker constant
`EXECUTION_AUTHORITY = "NONE"` is a hard-coded module-level constant and is also stamped on every emitted Proposition. The dataclass default is literal `"NONE"`; there is no code path that mutates it. Test `test_execution_authority_marker_is_none` verifies.

### 9.3 Replay harness output discipline
The harness writes **only** to the `--output` path given on the command line. It does not open any file in `/opt/tradingbot/cache/`, `/opt/tradingbot/logs/`, `/opt/tradingbot/state/`, or `/opt/tradingbot/.env` for write. The harness performs **no** `logger` writes beyond stdlib `logging.debug` on its own module.

### 9.4 Side-channel audit (manual review)
- No `telegram_alerts` import.
- No `requests` / HTTP calls.
- No file writes outside `--output`.
- No child process spawns.
- No modification of module-global state in any imported module (all calls read-only).

### 9.5 Live NMS not touched
The engine READS `/opt/tradingbot/cache/session_trend_{SYM}.json` via `session_trend.load_session_authority_snapshot`. It never calls the gate function, never writes to the snapshot, never changes NMS state. The `nms_permits_direction` field on every Proposition is an *observational* mirror of the gate rule, applied to the snapshot in the engine's own local function (`_nms_context_for`). It is **not** an admission decision for any strategy.

---

## 10. What the Operator Needs to Decide Next

The engine is ready to observe. Before it can inform any live decision, the operator should ratify (or override) each of the eight Deferred Design Decisions. The provisional defaults are defensible but are not "the rule" until confirmed.

In priority order (highest leverage first):
1. **DD-02 (type decision tree at a level in alignment)** — the biggest shape-of-output lever.
2. **DD-04 (minimum destination distance)** — controls how many propositions get emitted vs. filtered as insufficient room.
3. **DD-05 (confirmation threshold)** — whether CONFIRMED means FSM-only or FSM + M5 BoS.
4. **DD-08 (level-type polarity)** — resolves the signed-pips-zero ambiguity.
5. **DD-01 (nearby radius)** and **DD-03 (destination rule)** — tunables that materially affect which levels anchor propositions.
6. **DD-06 (HTF conflict handling)** — mostly a filtering choice.
7. **DD-07 (strategy family mapping)** — cosmetic until the engine is wired to a consumer; multi-match is a safe default.

Three additional items are **data gaps, not decisions**:
- **G-01**: H4 regime output (either add an H4 classifier, aggregate internally, or leave h4_context UNKNOWN).
- **G-02**: live D1 cache depth (needs more D1 bars retained to make live-mode useful; from-archive mode already works around this).
- **G-03**: qm_level_interactions FSM state transport (either run the FSM in the autobot process and surface its state to the engine, or compute it in the replay harness per bar).

---

## 11. Delivery Boundary (what Phase 4A does NOT do)

Per the operator's absolute restrictions, Phase 4A delivered **ONLY**:
- One module (`htf_trading_proposition.py`).
- One replay harness (`scripts/htf_proposition_replay.py`).
- One test suite (`tests/unit/test_htf_trading_proposition.py`).
- One `.gitignore` allowlist entry.

Phase 4A did **not**:
- Restart or stop any service.
- Modify `.env`, cache, logs, state files, or NMS persistence.
- Change NMS V3, central_execution_gate, or trade_manager code.
- Register any new autobot.py hook.
- Send a broker order.
- Modify an open position.
- Deploy to production.
- Alter V3 strategy admission.

The code branch `feat/htf-trading-proposition-phase4a` on `JohnCarrington/AutoBot` sits isolated and is NOT merged.

---

## 12. Files

| File | Role | Lines |
|---|---|---|
| `htf_trading_proposition.py` | engine | ~500 |
| `scripts/htf_proposition_replay.py` | offline replay harness | ~270 |
| `tests/unit/test_htf_trading_proposition.py` | 30 unit tests | ~400 |
| `.gitignore` | allowlist test file | 1-line add |
| `autobot_rationalisation/phase4a_examples.jsonl` | 7 example proposition records | 7 |

---

## 13. Next Steps (require operator approval before implementation)

- Decide DD-01 through DD-08.
- Decide G-01 (H4 producer) + G-02 (D1 cache depth) + G-03 (FSM state transport).
- Optionally: wire a thin shadow consumer in autobot.py that calls `build_proposition()` on each 5m close and writes the result to `/opt/tradingbot/logs/htf_proposition.jsonl` for post-hoc analysis. **Shadow write only; no execution path.**
- Optionally: a Phase-4B replay harness that joins proposition records against actual V3 fire outcomes to measure whether `TREND_CONTINUATION` propositions in `WATCHING` state preceded V3 trend fires, and whether their directional agreement correlated with trade outcome.

Each of these is a candidate for a Phase 4B scope definition. Nothing is implemented beyond the current observer.

---

*End of Phase 4A HTF Trading Proposition Engine report. Code and tests committed to isolated branch `feat/htf-trading-proposition-phase4a`; no production state changed.*
