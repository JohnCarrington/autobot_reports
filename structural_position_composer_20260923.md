# Structural Position-Management Composer — Path B build + causal replay + historical overlap (2026-09-23)

**Branch:** `feat/trend-stretch-brake-adx-floor` (commit `45e6727`).
**Author:** autobot · **Class:** implementation + tests + causal replay + population validation. **No .env change. No restart. No activation.**
**Trigger:** operator ruling — Path B. Build the missing composition layer between the observer's QM level-interaction states, structural levels, the existing stop-amendment primitive, and existing exit-management authorities. Do NOT revert to raw level-ladder. Do NOT activate the previously-implemented QM exhaustion veto.

---

## 0. Rulings honoured

- No new classifier. `structural_position_composer.py` reads the observer's already-emitted `structural_interpretation.{final_state, continuation_demonstrated, acceptance_side, interaction_open}` unchanged.
- No QM threshold change. No level-definition change. `level_ladder`, D1, D2, entry logic, `CentralExecutionGate`, strategy routing, Phase 16, HTF authority, raw ladder, tiered-ratchet calculations, FLIP authority, broker stop primitive — all untouched.
- Composer never violates broker-stop monotonicity. When its structurally-motivated stop would loosen an existing tightened stop, it emits `HOLD` with `monotonicity_conflict=True` and `intended_wider_stop` populated for telemetry — never a silent loosening.
- Retracement guard: composer never emits a broker-SL amendment that would trigger an immediate stop-out (proposed stop on the adverse side of current price).
- EXIT authority (target-ahead `FINAL_REJECT`) qualified on at least one cleared-behind level of earned structural protection — this prevents the canonical false-rejection exit (2026-04-14 LONG `NEAREST_50` REJECT at MFE ~6p).
- Flag `STRUCTURAL_POSITION_COMPOSER_ENABLED=0` default. Not set in production `.env`. Module ships inert; no production consumer imports it.

---

## 1. What was built (file:line)

| File | Change |
|---|---|
| `structural_position_composer.py` (**NEW**, 425 lines) | Public `compose(pair, direction, entry_price, current_price, current_stop_price, bar_ts, observer_states, ...) -> Composition`. Deterministic composition of `HOLD` / `TIGHTEN` / `EXIT` from observer states + level relationships. Never raises. |
| `tests/unit/test_structural_position_composer.py` (**NEW**, 17 tests) | Semantic matrix — ACCEPT, BREAK_AWAY, OSCILLATING, target REJECT (qualified + unqualified), cleared-behind REJECT, LONG/SHORT monotonicity conflict, retracement guard, staleness, bad direction, empty cache, no-cleared-yet, EXIT priority, flag-off default. |
| `scripts/composer_replay/composer_causal_replay.py` (**NEW**) | Per-event causal replay driving the production `tiered_ratchet` alongside `structural_position_composer` on real candles. Uses live observer JSONL when available (2026-09-23) and `qm_level_interactions.Interaction` reconstruction for dates outside live coverage (2026-04-14). |
| `scripts/composer_replay/composer_historical_overlap.py` (**NEW**) | Population replay across all 93 GBPUSD MID_NEWS ≥30p recognition-lens legs + 2026-09-23 counterfactual. Compares production vs composer per event, aggregates the operator-requested metrics. |
| `.gitignore` | Allowlist entries for the new test + replay files. |

**No modification** to `level_interaction_observer_v6.py`, `tiered_ratchet.py`, `level_ladder.py`, `qm_level_interactions.py`, `bounce_evidence.py`, `stage9s_structural_shadow.py`, `trade_manager.py`, `trade_manager_v2.py`, `qm_level_memory.py`, `central_execution_gate.py`, `strategy_dispatch_adapter.py`, or any other production module.

---

## 2. Semantic policy (code and prose match)

For each bar close, given the position's direction, entry price, current price, current broker stop, and the observer's per-level snapshot:

1. **Freshness filter.** Keep only observations whose `raw.bar_ts` is within `STRUCTURAL_COMPOSER_FRESHNESS_BARS × STRUCTURAL_COMPOSER_BAR_SECONDS` seconds of `bar_ts` (default 1 M5 bar). Stale drops; empty result → `HOLD` with `REASON_INSUFFICIENT_EVIDENCE`.

2. **Classify each fresh level relative to the position.**
   - For a `SELL`: `in_direction_side = "below"`; a level is *past-entry* if `level_price < entry_price`; *target-ahead* if `level_price < current_price`.
   - For a `BUY`: `in_direction_side = "above"`; past-entry if `level_price > entry_price`; target-ahead if `level_price > current_price`.
   - A level is `cleared-behind` iff `final_state ∈ {ACCEPT, BREAK_AWAY}` AND `continuation_demonstrated is True` AND `acceptance_side == in_direction_side` AND past-entry. Round-number and pivot levels on the wrong side of entry (broken through before the trade opened) are excluded — they are not this position's earned protection.
   - The *next-level* selected for reporting is the closest target-ahead level to `current_price`.

3. **No cleared-behind → `HOLD`.** The composer never fabricates a structural stop from geometry alone. If OSCILLATING is present the reason is `REASON_HOLD_OSCILLATING`; otherwise `REASON_HOLD_NO_CLEARED`. OSCILLATING does NOT grant additional holding authority — the reason string is telemetry-only.

4. **`FINAL_REJECT` at target-ahead (qualified on cleared-behind ≥ 1) → `EXIT`.** Reason `REASON_EXIT_TARGET_REJECT`. This is the composer's terminating authority for "continuation through the next rung has failed".

5. **Structural stop = last-cleared-level ± buffer.** For a `SELL`, `stop = min(cleared_behind).price + buffer_pips × pip_size` (buffer above the lowest captured level). For a `BUY`, `stop = max(cleared_behind).price − buffer_pips × pip_size`. This mirrors the rung-following geometry at `level_ladder.py:938-948` but consumes the observer's frozen finality instead of raw per-bar close-beyond.

6. **Retracement guard.** If the derived stop would sit on the adverse side of `current_price` (would cause an immediate broker stop-out), emit `HOLD` with `REASON_HOLD_RETRACED_PAST_LEVEL` and log `intended_wider_stop`. The observer's frozen-state design cannot detect a level reclaim; this guard prevents the composer from acting on a stale-favourable capture.

7. **Monotonicity check.** If the derived stop would loosen `current_stop_price` (SELL: `proposed > current`; BUY: `proposed < current`), emit `HOLD` with `monotonicity_conflict=True` and `REASON_HOLD_MONOTONICITY`. If equal to current: `HOLD` with `REASON_HOLD_ACCEPT_CONTINUATION`.

8. **Otherwise → `TIGHTEN`** with `proposed_stop` and `REASON_TIGHTEN_STRUCTURAL`.

---

## 3. Tests

```
$ python3 -m pytest tests/unit/test_tiered_ratchet.py tests/unit/test_ratchet_exhaustion_veto.py tests/unit/test_structural_position_composer.py -q
....................................................                     [100%]
52 passed in 0.86s
```

- 23 pre-existing `test_tiered_ratchet.py` cases pass unchanged.
- 12 `test_ratchet_exhaustion_veto.py` cases pass unchanged (composer does not touch veto path).
- 17 new `test_structural_position_composer.py` cases cover the operator's full semantic matrix.

Composer test roster:

| # | Test | Semantic clause exercised |
|---|---|---|
| 1 | `test_short_accept_with_continuation_tightens_from_be_when_price_below_stop` | ACCEPT + continuation → TIGHTEN (SHORT, price on correct side) |
| 2 | `test_short_accept_but_current_stop_already_tighter_holds` | Monotonicity — proposed > current for SHORT → HOLD |
| 3 | `test_short_break_away_treated_as_cleared_behind` | BREAK_AWAY is a continuation-positive final state |
| 4 | `test_short_final_reject_at_target_ahead_triggers_exit` | Target REJECT + earned protection → EXIT |
| 5 | `test_oscillating_alone_does_not_produce_tighten` | OSCILLATING alone → HOLD, no additional authority |
| 6 | `test_reject_at_cleared_behind_level_does_not_exit` | REJECT on opposition side → HOLD (not target-ahead) |
| 7 | `test_long_accept_with_continuation_tightens_from_be` | LONG symmetric ACCEPT → TIGHTEN |
| 8 | `test_long_monotonicity_conflict_when_ratchet_already_higher` | LONG monotonicity — proposed < current → HOLD |
| 9 | `test_stale_observation_dropped_and_returns_insufficient_evidence` | Freshness filter drops stale observations |
| 10 | `test_bad_direction_returns_hold_insufficient_evidence` | Non-BUY/SELL direction → HOLD |
| 11 | `test_empty_cache_returns_hold_insufficient_evidence` | No observer data → HOLD |
| 12 | `test_no_cleared_behind_yet_returns_hold_no_stop` | Interaction open but not stamped → HOLD |
| 13 | `test_exit_takes_priority_over_tighten_and_conflict` | Target REJECT beats monotonicity/tighten path |
| 14 | `test_short_retraced_above_structural_stop_holds` | SHORT retracement guard (S2 case) |
| 15 | `test_target_reject_without_cleared_behind_does_not_exit` | Unqualified target REJECT → HOLD (04-14 canonical case) |
| 16 | `test_long_retraced_below_structural_stop_holds` | LONG retracement guard |
| 17 | `test_flag_off_is_default_and_module_is_pure_composition` | STRUCTURAL_POSITION_COMPOSER_ENABLED False by default |

---

## 4. 2026-09-23 08:20 GBPUSD SHORT — causal replay

Entry: `2026-09-23T08:20:00+00:00` @ 13296.85 SHORT. Observer states: live JSONL (`logs/level_interaction_observer_v6.jsonl`). Bars: `data/candles/GBPUSD/2026-09-23.csv`. Ratchet: production `tiered_ratchet.on_bar_close`.

Script: `scripts/composer_replay/composer_causal_replay.py --date 2026-09-23 --direction SELL --entry-ts 2026-09-23T08:20:00+00:00 --entry-price 13296.85`. Trace: `/tmp/composer_causal_replay_2026-09-23_SELL.json`.

### 4.1 Landmark table (from the live replay run)

```
landmark            bar_ts                     close broker_stop  ratchet composer     proposed  reason
────────────────────────────────────────────────────────────────────────────────────────────────────────
entry               2026-09-23T08:20:00+00:00  13302.75    13308.85       -  HOLD         0.00  HOLD_NO_CLEARED_LEVEL
S2 first close      2026-09-23T09:45:00+00:00  13282.35    13296.85       -  HOLD         0.00  HOLD_NO_CLEARED_LEVEL
S2 acceptance       2026-09-23T11:05:00+00:00  13291.75    13296.85       -  HOLD         0.00  HOLD_RETRACED_PAST_LEVEL
13:15 (exh moment)  2026-09-23T13:15:00+00:00  13268.75    13281.85   CLOSE  HOLD         0.00  HOLD_MONOTONICITY_CONFLICT
13:25 pullback      2026-09-23T13:25:00+00:00  13287.85    13281.85       -  HOLD         0.00  HOLD_RETRACED_PAST_LEVEL
14:00               2026-09-23T14:00:00+00:00  13262.05    13281.85       -  HOLD         0.00  HOLD_MONOTONICITY_CONFLICT
14:25 S3 open       2026-09-23T14:25:00+00:00  13250.85    13281.85       -  EXIT         0.00  EXIT_TARGET_LEVEL_REJECT
14:35 S3 REJECT     2026-09-23T14:35:00+00:00  13255.45    13281.85       -  EXIT         0.00  EXIT_TARGET_LEVEL_REJECT
15:00               2026-09-23T15:00:00+00:00  13258.35    13281.85       -  EXIT         0.00  EXIT_TARGET_LEVEL_REJECT
16:05               2026-09-23T16:05:00+00:00  13249.65    13281.85       -  EXIT         0.00  EXIT_TARGET_LEVEL_REJECT
```

### 4.2 Reading the trace

- **08:20 entry → 09:45 first close below S2.** No level cleared yet (interaction open but `final_state` not stamped). Composer HOLDs.
- **11:05 S2 `FINAL_ACCEPT` + `continuation_demonstrated=True`.** Composer's derived structural stop = `S2 + 3p = 13286.92`. But **bar close 13291.75 has retraced above 13286.92** — the level was accepted in a prior bar (10:30 close 13279.25) and price has since bounced back above. Composer emits `HOLD` with `REASON_HOLD_RETRACED_PAST_LEVEL` and telemetry `intended_wider_stop=13286.92`. This is deliberate — the observer's frozen ACCEPT stamp cannot detect the reclaim, and issuing 13286.92 as a broker-SL amendment would trigger an immediate stop-out. The retracement guard prevents this pathology.
- **13:15 exhaustion moment.** Ratchet's `no_new_extreme_bars` reached 6 (production exhaustion fires). Composer sees `S2 ACCEPT+cont`, `S1 ACCEPT+cont`, `NEAREST_00 ACCEPT+cont`, `PDL BREAK_AWAY+cont` — all continuation-positive. But composer's derived stop 13286.92 is **looser** than the tier-1 lock 13281.85 → `HOLD` with `monotonicity_conflict=True`. Production ratchet closes at **13268.75, RATCHET_EXHAUSTION, +28.1p**.
- **13:25 pullback.** Position already closed by production ratchet at 13:15. If it had held, bar close 13287.85 > tier-1 stop 13281.85 → `RATCHET_STOP` would fire at 13:25 for +9p (this is the outcome the prior veto experiment produced). The composer's structural stop 13286.92 is 0.93p tighter than the retracement close 13287.85 → composer would also have breached at 13:25 (or 12:35 tier-1 would have consumed it first anyway).
- **14:35 S3 `FINAL_REJECT`.** Composer emits `EXIT` (target-ahead REJECT after earned protection at S2). Production position long since closed — composer's EXIT is theoretical. Realized had it been reachable: entry 13296.85 − 13255.45 = **+41.4p** (matches the `qm_successor_investigation_20260923.md` §5.5 composed decision outcome).
- **Composer's earliest target-REJECT EXIT was 14:05 on `NEAREST_50` (13250.0) REJECT at close 13264.45 → +32.4p**. Also unreachable under production exit at 13:15.

### 4.3 08:20 SHORT metrics under composer authority (no veto, monotonic)

| Field | Value | Notes |
|---|---|---|
| `0820_S2_ACTION` | `HOLD` (retraced past level) | S2+3=13286.92, close 13291.75 above (retraced) |
| `0820_1315_ACTION` | `HOLD` (monotonicity conflict) | Composer's 13286.92 > tier-1 lock 13281.85 |
| `0820_1325_SURVIVES` | `NO` | Production closed at 13:15 by RATCHET_EXHAUSTION |
| `0820_S3_REJECTION_ACTION` | `EXIT` (target-ahead REJECT at 14:35) | Theoretical only — position closed at 13:15 |
| `0820_FINAL_EXIT` | `RATCHET_EXHAUSTION` at `2026-09-23T13:15:00+00:00` @ 13268.75 | Production behaviour preserved (composer inert here) |
| `0820_CAPTURED_PIPS` | `+28.10p` | Same as production (composer had no realised effect) |
| Session MFE | 72.9p | Peak favourable displacement from entry |

**The composer's structural authority is architecturally identical to what would save this trade — but under strict stop monotonicity + non-veto over ratchet exits, its authority never engages in time to help this specific case.** The monotonicity conflict at 13:15 is real (`STOP_MONOTONICITY_CONFLICT = YES`) and is the honest exposed constraint per the operator's ruling.

---

## 5. 2026-04-14 LONG — adverse-case replay (mandatory)

Entry: `2026-04-14T08:00:00+00:00` @ 13533.85 LONG. Observer states: reconstructed via `qm_level_interactions.Interaction` state machine (this date is outside live observer coverage). Bars: `data/candles/GBPUSD/2026-04-14.csv`.

Script: `scripts/composer_replay/composer_causal_replay.py --date 2026-04-14 --direction BUY --entry-ts 2026-04-14T08:00:00+00:00 --entry-price 13533.85 --reconstruct`. Trace: `/tmp/composer_causal_replay_2026-04-14_BUY.json`.

### 5.1 Landmark table

```
landmark      bar_ts                     close broker_stop  ratchet composer     proposed  reason
────────────────────────────────────────────────────────────────────────────────────────────────────────
entry         2026-04-14T08:00:00+00:00  13533.85    13521.85       -  HOLD         0.00  HOLD_NO_CLEARED_LEVEL
11:00         2026-04-14T11:00:00+00:00  13544.65    13533.85       -  HOLD         0.00  HOLD_NO_CLEARED_LEVEL
12:30         2026-04-14T12:30:00+00:00  13566.15    13551.88       -  HOLD         0.00  HOLD_ACCEPT_CONTINUATION
13:15         2026-04-14T13:15:00+00:00  13578.95    13551.88       -  HOLD         0.00  HOLD_ACCEPT_CONTINUATION
13:25 (exh)   2026-04-14T13:25:00+00:00  13582.70    13551.88       -  HOLD         0.00  HOLD_ACCEPT_CONTINUATION
14:00         2026-04-14T14:00:00+00:00  13584.35    13551.88   CLOSE  HOLD         0.00  HOLD_ACCEPT_CONTINUATION
15:30         2026-04-14T15:30:00+00:00  13582.55    13551.88       -  HOLD         0.00  HOLD_ACCEPT_CONTINUATION
16:55         2026-04-14T16:55:00+00:00  13561.85    13551.88       -  HOLD         0.00  HOLD_ACCEPT_CONTINUATION
```

### 5.2 Reading the trace

- **Composer NEVER emits EXIT** on this LONG. The EXIT trigger is qualified on ≥ 1 cleared-behind level of earned protection. At 10:20 `NEAREST_50` (13550.0) enters `FINAL_REJECT` (target-ahead REJECT) — but no level is cleared-behind yet (R1 hasn't accepted). Under the qualification rule, composer HOLDs. **This is the canonical case the qualifier prevents — the earlier (unqualified) design produced a false-rejection EXIT at MFE ~6p; the qualifier correctly suppresses it.**
- **Composer TIGHTEN fires** between 11:00 and 12:30: broker stop moves from BE 13533.85 → R1−3 = 13551.88. This is composer's contribution — a mid-run structural stop lock at +18p profit floor. Ratchet's tier-1 (entry+15p = 13548.85) would have fired later; when it does, its proposed 13548.85 is looser than composer's 13551.88 and the monotonic gate keeps the tighter 13551.88.
- **13:25 ratchet exhaustion candidate**: no_new_extreme reaches 6 for the ratchet. But `beyond_be` requires software_stop > entry (strictly), and ratchet's internal `software_stop_price` is still updating from its own tier schedule — the composer's tighter broker stop doesn't influence ratchet's exhaustion arithmetic. Ratchet fires exhaustion at 14:00, close 13584.35 = **+50.5p** (production).
- **Composer EXIT** timeline: none. Composer HOLD_ACCEPT_CONTINUATION from 12:30 through 16:55 — no target-ahead level in adverse REJECT while continuation stays positive at R1.
- **Composer P&L on 04-14: +50.5p (identical to production).** The known adverse case (veto held past a genuine momentum peak → +28p give-back) is NOT reproduced by the composer, because the composer does not veto ratchet exhaustion.

### 5.3 Distinguishing 04-14 from 09-23 with existing causal evidence

The operator asked: "Explain what existing causal evidence distinguishes it from the 23-September continuation case. If existing evidence cannot distinguish them, report that limitation rather than adding an invented rule."

**Existing observer/QM evidence at ratchet-exhaustion moment:**

| Field | 2026-04-14 13:25 | 2026-09-23 13:15 |
|---|---|---|
| Cleared-behind (in-direction, ACCEPT+cont, past entry) | R1 @ 13554.91 (below current for LONG) — 1 level | S2 @ 13283.92 (above current for SHORT) — 1 level |
| Additional continuation signals | NEAREST_50 previously rejected then re-cleared as price rose above | S1, NEAREST_00 all ACCEPT+cont (but ABOVE entry for SHORT → NOT counted as this position's earned protection) |
| Target-ahead level | None inside session-reachable range | S3 @ 13246.28 (targeted, not yet interacted) |
| Any REJECT / OSCILLATING at fresh active level | None | None (until 14:20+ NEAREST_50 / S3 REJECT) |
| Bar-level pattern in the exhaustion window | Flat 13579-13587 (drift) | 20p intraday shakeout followed by continuation to 14:35 S3 REJECT |

**Both cases present identical composer inputs at their respective ratchet-exhaustion moments: 1 cleared-behind level, no active REJECT, target-ahead not yet interacted.** The bar-level pattern that would distinguish "genuine plateau" (04-14) from "shakeout with continuation" (09-23) is NOT surfaced by any existing classifier — the observer's frozen-state design does not encode "adverse retracement past captured level" nor "impulse still in progress vs exhausted". A distinguishing primitive would be new machinery (either a reclaim detector or a bar-volatility-based freshness signal); the operator's ruling excludes adding it.

**Honest limitation:** the composer, under existing causal evidence alone, cannot pre-emptively distinguish 04-14 from 09-23 at ratchet-exhaustion time. In this Path B design that limitation does not produce harm — because the composer does not veto ratchet exhaustion. Production ratchet's MFE-freshness heuristic correctly calls the top of the impulse in both cases (04-14: +50.5p exhaustion catches the peak; 09-23: +28.1p exhaustion also catches the peak but the composer identifies a further +13.3p realizable at 14:35 S3 REJECT — both correct under composer semantics, only 09-23 requires overriding ratchet exhaustion to capture, which is out of scope for this increment).

---

## 6. Historical overlap validation (production vs composer)

Population: 93 recognition-lens legs across 32 GBPUSD MID_NEWS sessions (Jan 5 → Aug 5 2026) + 3 counterfactual legs on 2026-09-23 = **93 events**. QM states reconstructed via `qm_level_interactions.Interaction` state machine (identical to `scripts/phase16_veto_eval/qm_exhaustion_veto_regression.py` — the same real state machine, no re-implementation).

Script: `scripts/composer_replay/composer_historical_overlap.py`. Output: `/tmp/composer_historical_overlap.json`.

### 6.1 Aggregate summary

```
OVERLAP_POPULATION                       = 93
CURRENT_TOTAL_PIPS   (production)        = +895.60p
COMPOSER_TOTAL_PIPS  (composer)          = +780.65p
DELTA                                     = −114.95p  (composer NET NEGATIVE)

CURRENT_MEDIAN                            = +1.20p
COMPOSER_MEDIAN                           = +3.60p
CURRENT_MEAN                              = +9.63p
COMPOSER_MEAN                             = +8.39p

CURRENT_MEDIAN_CAPTURE_RATIO (real/MFE)   = 0.044
COMPOSER_MEDIAN_CAPTURE_RATIO             = −0.435   (dominated by early exits on low-MFE trades)

CURRENT_GIVEBACK_MEDIAN (MFE − realised)  = 18.95p
COMPOSER_GIVEBACK_MEDIAN                  = 20.20p

WINNERS_TO_LOSERS                         = 4   (production >0, composer ≤ 0)
TWENTY_PIP_WINNERS_REDUCED_BELOW_10P      = 1

COMPOSER_REJECTION_EXITS                  = 11 (STRUCTURAL_COMPOSER_EXIT_TARGET_LEVEL_REJECT)
COMPOSER_BROKER_STOP_EXITS                = 11 (composer TIGHTEN caused breach before ratchet)
COMPOSER_TIGHTENS_TOTAL                   = 39 (successful monotonic-tighter amendments)
MONOTONICITY_HOLD_EVENTS                  = 168 (bars where composer wanted to loosen — correctly held)
INSUFFICIENT_EVIDENCE_BAR_EVENTS          = 2118 (bars with no cleared-behind level)

EXIT_REASON_DIST                          = {
  RATCHET_STOP: 36,
  RATCHET_EXHAUSTION: 18,
  END_OF_DATA (NY_CLOSE): 17,
  STRUCTURAL_COMPOSER_EXIT_TARGET_LEVEL_REJECT: 11,
  COMPOSER_BROKER_STOP: 11
}
```

### 6.2 Winners→losers cases (composer harm)

| Date | Dir | Entry | MFE | Production | Composer | Composer reason |
|---|---|---|---|---|---|---|
| 2026-01-15 | SELL | 13388.25 | 13.8p | +6.8p (NY_CLOSE) | −0.8p (END_OF_DATA) | held past production exit; MAE stopped |
| 2026-01-26 | SELL | 13689.45 | 14.8p | +8.8p (NY_CLOSE) | −6.1p (target REJECT) | composer EXIT below entry |
| 2026-05-22 | BUY | 13431.75 | 15.3p | +12.9p (NY_CLOSE) | −0.1p (END_OF_DATA) | composer TIGHTEN then reversed |
| 2026-08-05 | SELL | 13461.65 | 2.0p | +1.2p (NY_CLOSE) | −7.9p (END_OF_DATA) | composer TIGHTEN below entry |

### 6.3 ≥20p winner reduced below +10p

| Date | Dir | Production | Composer | Delta |
|---|---|---|---|---|
| 2026-05-28 | BUY | +27.9p (RATCHET_EXHAUSTION) | +3.9p (COMPOSER_BROKER_STOP) | −24.0p |

### 6.4 Composer target-REJECT EXIT cases

| Date | Dir | Production | Composer | Delta |
|---|---|---|---|---|
| 2026-01-15 | SELL | +33.3p | +24.2p | −9.0p |
| 2026-01-26 | SELL | +8.8p | −6.1p | −14.9p |
| 2026-01-30 | SELL | +32.8p | +10.6p | −22.2p |
| 2026-02-02 | SELL | +23.3p | +14.8p | −8.6p |
| 2026-03-27 | SELL | +45.8p | +47.5p | **+1.7p** |
| 2026-03-27 | SELL | +33.2p | +31.2p | −2.0p |
| 2026-03-31 | SELL | +15.6p | +15.6p |  0.0p |
| 2026-06-01 | SELL | +39.8p | +44.3p | **+4.5p** |
| 2026-06-01 | BUY | +15.8p | +1.5p | −14.3p |
| 2026-07-24 | BUY | +7.8p | +17.5p | **+9.7p** |
| 2026-09-23 | SELL | +32.7p | +23.4p | −9.3p |

**Sum across 11 rejection-EXIT events: −64.4p.** Composer's target-REJECT EXIT captures value in 3 cases (03-27 SELL, 06-01 SELL, 07-24 BUY = +15.9p combined) and gives up value in 6 cases. The value-add cases are indistinguishable *ex ante* from the value-loss cases using existing causal evidence — same rule (target-ahead REJECT after earned protection), different intraday outcomes.

### 6.5 Reading the population result

- **Machinery is correct.** All 168 monotonicity-conflict holds are the composer honouring the operator's "never loosen" contract. All 2118 no-cleared-yet holds are the composer refusing to fabricate a stop from geometry alone. The composer never proposed an immediate-breach amendment (retracement guard held on every attempt where price had retraced past the derived stop).
- **Composer NET NEGATIVE at population scale (−114.95p).** The composer's target-REJECT EXIT authority is empirically too eager on the ≥30p MID_NEWS population — for every 1 case where an early EXIT captures value (~+3-10p), 2 cases sacrifice a further +9-22p of runnable momentum. Same shape observed in the veto experiment (`qm_continuation_veto_ratchet_exhaustion_20260923.md` §5.4: false-exhaustions-prevented 1, adverse-holds 3, net −30.1p on the narrower overlap subpopulation).
- **Composer TIGHTEN authority is essentially neutral.** 39 successful TIGHTENs occurred across 93 events; most were subsumed by subsequent ratchet tier advances (composer's rung-following stop is architecturally similar to but tactically wider than ratchet's tier-1 lock in MID_NEWS conditions). The 11 `COMPOSER_BROKER_STOP` exits are cases where the TIGHTEN was retained (ratchet didn't tighten further) and breached before ratchet exhaustion — mostly small negative deltas.
- **Stop-monotonicity conflict is real and correctly handled.** 168 events across the population where the composer's structurally-motivated stop was looser than the operative ratchet stop. The composer did NOT emit those amendments (matching the operator's contract). The intended_wider_stop is captured in telemetry for future architectural analysis.
- **Insufficient-evidence events are the norm early in a leg.** 2118 bar events (mean 22.8/event) had no cleared-behind level yet — the leg had not established structural protection when the composer was consulted. This is expected: the observer needs 2 consecutive closes beyond the level plus N bars out-of-zone to stamp `FINAL_ACCEPT`, and most legs open below their first target level.

### 6.6 What this replay does NOT license

- **Do not extrapolate.** Rates from this ≥30p MID_NEWS overlap subpopulation MUST NOT be projected onto the ~200 daily TREND_V3 candidates that do not reach this size class.
- **Do not activate the composer.** The measured net effect at population scale is negative; the mechanism is correct but the target-REJECT EXIT authority is empirically too eager in intraday flows without additional qualifiers.
- **Do not attribute the −114.95p to the mechanism as designed.** The single-largest contributor is the 11 target-REJECT EXITs summing to −64.4p (57% of the deficit). A subsequent proposal could either (a) further qualify the EXIT trigger with MFE / bar-volatility / bounce-evidence (well-defined telemetry available), or (b) confine composer authority to TIGHTEN-only (net-neutral) and pass structural EXIT decisions to a future consumer.

---

## 7. Flag-OFF parity

```
$ grep -rn "structural_position_composer\|structural_composer" /opt/tradingbot --include='*.py' \
       | grep -v tests | grep -v scripts/composer_replay | grep -v structural_position_composer.py
(empty — zero production imports)
```

- `structural_position_composer.py` is imported by exactly three places: the module itself (`__all__` export), `tests/unit/test_structural_position_composer.py`, and `scripts/composer_replay/*.py` (replay only, off production path).
- `STRUCTURAL_POSITION_COMPOSER_ENABLED` is not set in production `.env` — module default (`False`) governs. `test_flag_off_is_default_and_module_is_pure_composition` asserts this.
- The 23 pre-existing `test_tiered_ratchet.py` cases + 12 `test_ratchet_exhaustion_veto.py` cases pass unchanged.
- `tiered_ratchet.py`, `level_interaction_observer_v6.py`, `level_ladder.py`, `qm_level_interactions.py`, `trade_manager.py`, `central_execution_gate.py` all unchanged in this commit.

**Flag OFF is byte-for-behaviour equivalent to production without the composer.**

---

## 8. Required metric block

```
COMPOSER_IMPLEMENTED                    = structural_position_composer.py (425 lines) + tests/unit/test_structural_position_composer.py (17 tests, 415 lines) + scripts/composer_replay/composer_causal_replay.py + scripts/composer_replay/composer_historical_overlap.py

NEW_CLASSIFIER_ADDED                    = NO (composer reads observer's already-emitted structural_interpretation.{final_state, continuation_demonstrated, acceptance_side, interaction_open} unchanged)
QM_CHANGED                              = NO (no changes to qm_level_interactions, level_interaction_observer_v6, level_snapshot_v6, bounce_evidence, stage9s_structural_shadow, qm_level_memory)
RATCHET_CHANGED                         = NO (tiered_ratchet.py not touched in this commit; the veto seam previously landed on this branch stays flag-OFF and is not activated)
STOP_MONOTONICITY_CONFLICT              = YES. Confirmed at 2026-09-23T13:15 (composer's structural stop S2 + 3p = 13286.92 for a SHORT vs tier-1 lock 13281.85 — proposed would loosen → composer emits HOLD with monotonicity_conflict=True; NEVER a silent violation). Recurs across 168 bar-events in the historical overlap population. Composer exposes the conflict via Composition.intended_wider_stop for future architectural analysis; ratchet's monotonic-tighter enforcement at tiered_ratchet.py:589-598 remains authoritative.

0820_S2_ACTION                          = HOLD (REASON_HOLD_RETRACED_PAST_LEVEL). At 2026-09-23T11:05 S2 FINAL_ACCEPT stamped (close 13291.75), composer's derived structural stop S2+3=13286.92 sits BELOW current price → issuing as broker SL would trigger immediate stop-out. Composer records intended_wider_stop=13286.92 in telemetry and HOLDs. This is the retracement guard operating as designed — the observer's frozen-state semantics do not detect level reclaim, and the composer must not silently produce an immediate-breach amendment.
0820_1315_ACTION                        = HOLD (REASON_HOLD_MONOTONICITY_CONFLICT). At 2026-09-23T13:15 (ratchet exhaustion moment), composer's structural stop 13286.92 is LOOSER than the operative tier-1 stop 13281.85 for a SHORT (proposed 13286.92 > current 13281.85). Composer records the conflict and holds. Production ratchet independently fires RATCHET_EXHAUSTION on this bar.
0820_1325_SURVIVES                      = NO. Under composer authority (no veto over ratchet exits) + strict stop monotonicity, position was closed at 13:15 by RATCHET_EXHAUSTION @ 13268.75 (+28.1p). 13:25 bar is not reached under the production timeline. If exhaustion had been suppressed, the tier-1 stop 13281.85 would breach at 13:25 close 13287.85 → +9p RATCHET_STOP; composer's structural stop 13286.92 (0.93p tighter) would ALSO have breached at 13:25. No composer-derivable stop wider than 13286.92 exists under the "rung-following + buffer_pips=3" contract; a wider stop would either violate monotonicity (already established) or exceed entry (BE) which contradicts profit protection.
0820_S3_REJECTION_ACTION                = EXIT (REASON_EXIT_TARGET_REJECT). At 2026-09-23T14:35 the observer stamps S3 @ 13246.28 as FINAL_REJECT; at that point S2 remains cleared-behind → EXIT qualification met. Composer emits EXIT. In the replay this proposal is theoretical because production ratchet closed the position at 13:15; the composer's first target-REJECT EXIT proposal is actually at 14:05 on NEAREST_50 (13250.0) REJECT (close 13264.45) which would give +32.4p if reachable, and the 14:35 S3 REJECT is at close 13255.45 → +41.4p if reachable.
0820_FINAL_EXIT                         = RATCHET_EXHAUSTION at 2026-09-23T13:15:00+00:00 @ 13268.75 (production; unchanged by composer authority in this design)
0820_CAPTURED_PIPS                      = +28.10p (production; composer had zero realised effect on this position — TIGHTEN blocked by retracement guard at 11:05, TIGHTEN blocked by monotonicity at 13:15+, EXIT unreachable because production closed at 13:15)

APR14_RESULT                            = +50.50p (production RATCHET_EXHAUSTION at 2026-04-14T14:00 @ 13584.35). Composer does NOT reproduce the previously-observed adverse hold (+50.5p → +28p give-back under veto). The composer emitted TIGHTEN once (BE 13533.85 → R1−3 = 13551.88, mid-run structural stop lock; net-neutral because it never breached) and never emitted EXIT (target-ahead REJECT at 10:20 NEAREST_50 was correctly suppressed by the earned-protection qualifier — the canonical false-rejection exit that motivated the qualifier). The remaining architectural limitation: existing causal evidence (observer states, level relationships) does not pre-emptively distinguish 04-14's "genuine plateau" from 09-23's "shakeout with continuation" at ratchet-exhaustion time; both present identical composer inputs. A distinguishing primitive would be NEW machinery (reclaim detector or bar-volatility freshness signal), explicitly out of scope per the ruling.

OVERLAP_POPULATION                      = 93 (recognition-lens legs across 32 MID_NEWS sessions Jan 5–Aug 5 2026 + 3 counterfactual legs on 2026-09-23)
CURRENT_TOTAL_PIPS                      = +895.60p (production tiered_ratchet)
COMPOSER_TOTAL_PIPS                     = +780.65p (composer authority: TIGHTEN via monotonic gate + target-REJECT EXIT qualified on cleared-behind ≥ 1, applied per bar)
CURRENT_MEDIAN_CAPTURE                  = 0.044 (median realised/MFE across events with MFE > 0)
COMPOSER_MEDIAN_CAPTURE                 = −0.435 (dominated by low-MFE trades where an early exit produces a negative pip result that divides a small positive MFE)

FALSE_HOLDS                             = 168 (monotonicity-hold bar-events across the population where composer wanted to widen the stop; contract prohibits, so composer held). These are NOT harm — they are the operator's monotonicity contract operating as designed. Under Path B's "no ratchet modification" ruling, these cannot be resolved without changing ratchet authority (out of scope for this increment).
WINNERS_TO_LOSERS                       = 4 (events where production >0p, composer ≤ 0p — mostly composer TIGHTEN followed by adverse retracement to composer stop; smaller giveback protection meets larger MAE exposure)
20P_WINNERS_REDUCED_BELOW_10P           = 1 (2026-05-28 BUY: production +27.9p RATCHET_EXHAUSTION, composer +3.9p COMPOSER_BROKER_STOP)
CONTINUATION_CORRECTLY_PRESERVED        = ~60 events where composer HOLD_ACCEPT_CONTINUATION covered the run without emitting EXIT (measured indirectly — production and composer close on identical ratchet event with delta 0)
REJECTION_EXITS                         = 11 (composer target-ahead FINAL_REJECT after earned protection). Sum delta vs production across all 11: −64.4p (3 positive: +1.7 +4.5 +9.7 = +15.9; 6 negative summing −71.0; 2 zero). The EXIT trigger is empirically too eager on this population.
STOP_AMENDMENTS                         = 39 composer TIGHTEN amendments successfully applied via monotonic gate. Most were subsequently subsumed by ratchet tier advances (composer's rung-following stop is architecturally similar to but tactically wider than ratchet tier-1 in MID_NEWS conditions).
INSUFFICIENT_EVIDENCE_CASES             = 2118 bar events with no cleared-behind level (observer had not yet stamped FINAL_ACCEPT on any in-direction level past entry). Composer emitted HOLD_NO_CLEARED / HOLD_OSCILLATING correctly — no fabricated stops. Mean ~22.8 such bars per event, consistent with the observer's 2-consecutive-closes-beyond + N-bars-out-of-zone stamping cadence.

FLAG_OFF_PARITY                         = PASS. Zero production imports of structural_position_composer confirmed via grep. STRUCTURAL_POSITION_COMPOSER_ENABLED not set in production .env → module default False → module is inert on flag OFF. All 23 pre-existing test_tiered_ratchet.py cases + all 12 test_ratchet_exhaustion_veto.py cases + all 17 new test_structural_position_composer.py cases pass. tiered_ratchet.py, level_interaction_observer_v6.py, level_ladder.py, trade_manager.py, and all other production modules unchanged in this commit.

READY_FOR_ACTIVATION                    = NO. On the overlapping ≥30p MID_NEWS recognition-lens population the composer is net −114.95p across 93 events (WINNERS_TO_LOSERS=4, ≥20p→<10p reductions=1, target-REJECT EXITs net −64.4p across 11 firings). The mechanism is correct and byte-for-behaviour safe (FLAG_OFF_PARITY=PASS), but activating it under the current ratchet tier schedule + observer semantics would surrender P&L. The measured negative-delta cases share the same causal inputs as the measured positive-delta cases; a further discriminator (bar-volatility-based freshness, MFE floor on EXIT authority, bounce_evidence integration, or a level-reclaim primitive) is required before broader activation would be justified. Any such discriminator constitutes a new increment and would need its own regression and its own operator ruling.
```

*Stop.*
