# M4 FINAL ACCEPTANCE CLOSURE — combined weekend boot + allowance proof

**Report date:** 2026-09-21
**Chain under closure:**
- `4b354f4` M0-M3
- `fa18a90` authoritative prior-D1 selector
- `783eb0e` multi-day 5D/20D weekend-fragment guard
- `4bf3e55` M4 persisted daily structural context (dark-wired, default OFF)

**Closure commit:** delivers TESTS + REPORT only per §13. **No production code modified.**

**Verdict:** `M4_FINAL_ACCEPTANCE = PASS` · `PRODUCTION_CODE_DEFECT_FOUND = NO` · `READY_FOR_M5 = YES` · `SAFE_TO_DEPLOY = NO`.

---

## §2 · Causal full-weekend fixture

Built in `tests/unit/test_m4_closure_weekend_boot.py::_build_causal_weekend_fixture`:

- **15 weekdays** Mon 2026-03-02 → Fri 2026-03-20 of 5m data
- **Last-weekday truncation** at 22:00 UTC (Fri stops at 21:55 5m, closing at 22:00 UTC) so no synthetic bars land inside the FX weekend closure window
- **Weekend closure** Fri 2026-03-20 22:00 UTC → Sun 2026-03-22 22:00 UTC — **zero** 5m emitted in this window
- **Sun 2026-03-22 22:00 UTC FX reopen** — 24 bars through Sun 23:55 UTC
- **Mon 2026-03-23 open** — 96 bars covering 00:00 → 08:00 UTC
- **Depth**: 4200+ 5m rows (>3000 required), 90+ H4 buckets (>60 required), 15 D1 bars

D1 authority seeded via `_seed_d1_cache_with_friday`: Thursday and Friday D1 candles in `cache/htf/GBPUSD_D1.json` at the midnight-UTC-of-trading-day convention `htf_cache.select_prior_completed_d1` expects.

---

## §3-§4 · Path A (uninterrupted) vs Path B (restarted) — H1/H4/consumer/readiness parity

Two paths execute the identical 5m stream:

- **Path A** — one `TimeframeContext`; feed pre + post rows continuously.
- **Path B** — `TimeframeContext` #1 feeds pre-shutdown rows; state saved via `htf_cache.save_candles_to_cache(SYM, "H1"/"H4", ...)`; fresh `TimeframeContext` #2 loaded via the actual production Phase-1 boot chain (`startup_load_or_flag` → `validate_persisted_htf` → `inject_htf_candles`); then feed post-reopen rows.

Comparison follows the **intersection convention** established by M0-M3's `test_R_full_depth_restart_parity_60_h4` (test_historical_v2_m0_m3_closure.py:191-258): trailing partials that are inherently ephemeral across restart are compared only on the common bucket_epochs — no bar-count divergence is asserted, but every bar present in both paths must be byte-identical on OHLC.

### Results

`test_closure_H1_H4_parity_A_vs_B` — **PASS**

- `POST_WEEKEND_H1_DIFF = EMPTY` on the common H1 intersection (all closed H1 buckets match on open/high/low/close bytewise).
- `POST_WEEKEND_H4_DIFF = EMPTY` on the common H4 intersection.
- `len(common_h4) ≥ 60` — production consumer depth met on the intersection.
- No H1 bucket starts inside the [Fri 22:00, Sun 22:00) UTC closure window (would require a 5m at that hour; none emitted).
- H4 bucket [Sun 20-24) (the reopen-leg partial) has OHLC values ≥ 1.35, i.e., sourced only from the Sun 22:00+ walk-forward leg — no stale Fri contamination.

`test_closure_H4_consumer_parity_A_vs_B` — **PASS**

Consumer input slices modelled on the M0-M3 template (structural_state closes[-30:], ff_h4 tail-50 OHLC, swing_h4 tail-30 OHLC tuple, TREND_V3 tail-12 closes):

- `POST_WEEKEND_H4_CONSUMER_DIFF = EMPTY` — every slice byte-identical.
- `POST_WEEKEND_H4_READINESS_PARITY = PASS` — every readiness flag identical, all True at test depth (structural_state 30, ff_h4 50, swing 30, trend_v3 12, sixty_bar 60).

---

## §5 · Daily-structural-level parity into the same fixture

`test_closure_daily_snapshot_parity_A_vs_B` — **PASS**

Both paths call `daily_snapshot.ensure_snapshot_for_today(SYM, monday, epic=EPIC, now_utc=...)` against the same D1 cache; the snapshot is a pure function of the D1 cache + trading date. Identity holds by construction and is verified directly against production code.

- `POST_WEEKEND_DAILY_LEVEL_DIFF = EMPTY` (stripping `calculated_at`, which differs by definition since the two calls use different `now_utc`).
- Monday snapshot's `trading_date = 2026-03-23`, `previous_trading_date = 2026-03-20`, `source_d1_timestamp = 2026-03-20T00:00:00+00:00`.
- `PDH = 1.36`, `PDL = 1.33` — bytewise identical to seeded Friday D1 OHLC. Pivot family (P/R1-R3/S1-S3) computed from these three inputs via `daily_snapshot._compute_pivots_from_ohlc`; matches `bb_pd_gate.compute_pivots_only` (proven separately by `test_daily_snapshot.py::test_build_snapshot_pivot_math_matches_bb_pd_gate`).

---

## §6 · Sunday-reopen trading-date semantics table

Emitted verbatim by `test_closure_sunday_reopen_trading_date_semantics`. Column key:

- **WC**: `datetime.date()` of the UTC timestamp — what the M4 boot hook (`autobot.py:10518`, `datetime.now(timezone.utc).date()`) passes to `ensure_snapshot_for_today`.
- **FX**: the FX-session trading date, computed as `(ts_utc + 2h).date()` — the day the [D-1 22:00, D 22:00) UTC session belongs to.
- **EH**: whether the trade_executor entry-hours gate is open (`QM_ENTRY_HOUR_START=7`, `QM_ENTRY_HOUR_END=17` per `trade_executor.py:2567-2568`, gate at `trade_executor.py:2570-2572`).
- **M4_ARG**: the argument the M4 boot hook actually passes today (= WC).
- **STATUS**: `unavailable` / `rebuilt` / `loaded` from `ensure_snapshot_for_today`.
- **SNAP_TD**: snapshot's `trading_date` field (`-` if `unavailable`).
- **READY**: whether daily-context is READY for the strategy layer (snapshot present).

```
UTC                          WC          FX          EH   M4_ARG      STATUS       SNAP_TD     READY
2026-03-22T21:59:00+00:00    2026-03-22  2026-03-22  NO   2026-03-22  unavailable  -           NO
2026-03-22T22:00:00+00:00    2026-03-22  2026-03-23  NO   2026-03-22  unavailable  -           NO
2026-03-22T22:05:00+00:00    2026-03-22  2026-03-23  NO   2026-03-22  unavailable  -           NO
2026-03-22T23:59:00+00:00    2026-03-22  2026-03-23  NO   2026-03-22  unavailable  -           NO
2026-03-23T00:00:00+00:00    2026-03-23  2026-03-23  NO   2026-03-23  rebuilt      2026-03-23  YES
2026-03-23T06:59:00+00:00    2026-03-23  2026-03-23  NO   2026-03-23  loaded       2026-03-23  YES
2026-03-23T07:00:00+00:00    2026-03-23  2026-03-23  YES  2026-03-23  loaded       2026-03-23  YES
```

Reading:

- **Sun 22:00 → 23:59 UTC**: `WC=Sunday`, `FX=Monday` — the wall-clock date and the FX-session trading date diverge. M4 boot hook (uses WC) passes Sunday → `unavailable`. Snapshot not built/loaded.
- **Mon 00:00 UTC**: WC advances to Monday → snapshot rebuilt from Friday D1.
- **Mon 07:00 UTC** (entry-hours open): snapshot is `loaded` (present since Mon 00:00 boot). Daily context is READY BEFORE the entry window opens.

---

## §7 · Defect ruling for the Sunday-reopen window

`test_closure_no_production_defect_at_sunday_reopen` — **PASS**

**Ruling: `PRODUCTION_CODE_DEFECT_FOUND = NO`.**

Rationale — five independent gates prevent any trade during the ambiguous Sun-22:00-to-Mon-07:00 window:

1. **All five non-news strategies have their own weekday gate.** `ts.weekday() >= 5` blocks Sat (5) and Sun (6):
   - `gbpusd_bb_bounce.py:1188`
   - `gbpusd_ema_pullback.py:1082`
   - `gbpusd_confirmation_fallback.py:318`
   - `gbpusd_structure_break.py:775`
   - `gbpusd_pivot_break.py:453`

2. **trade_executor entry-hours gate** (`trade_executor.py:2560-2622`) reads `datetime.utcnow().hour` and blocks trades outside `[7, 17)` UTC. Sun 22:05 has `hour=22` → blocked regardless of strategy.

3. **News strategies** (briefing_execution, pia_first_briefing, morning_briefing) have their own weekend-market-closure detection (`morning_briefing.py:3795-4124`).

4. **M4 is dark-wired.** `DAILY_SNAPSHOT_ENABLED` defaults to `"0"`. No strategy at HEAD reads `daily_snapshot` (verified by grep: only `autobot.py` and the tests reference the module). Even if the snapshot were absent or wrong, no consumer would notice.

5. **By Mon 00:00 UTC** the wall-clock date advances to Monday, and any restart from that point rebuilds the correct Monday snapshot (source: Friday's D1). By Mon 07:00 UTC (entry-hours open), the snapshot has been present for 7 hours.

**Semantic seam that M5 must handle** (documented here, not a defect in M4): if a future M5 consumer needs the daily snapshot at Sun 22:05 UTC (weekday=6) — e.g., an FX-session-aware strategy or a news window that would be legitimate under FX conventions — the consumer must compute `trading_date` via FX-session logic (`(ts_utc + 2h).date()`) before calling `load_snapshot_if_valid`, or M4's boot hook must be extended to also boot when `wall_clock != fx_session` and the fx_session day is a weekday. M4 correctly delivers on the calendar-UTC contract it defines; M5 will define the FX-session contract if strategies need it.

- `SUNDAY_REOPEN_M4_STATUS = unavailable`
- `SUNDAY_REOPEN_CONTEXT_UNAVAILABLE = YES`
- `SUNDAY_REOPEN_CAN_TRADE = NO` (via strategy weekday gates + trade_executor entry-hours gate)
- `MONDAY_ENTRY_WINDOW_CONTEXT_READY = YES` (snapshot present since Mon 00:00 UTC boot)
- `FX_SESSION_TRADING_DATE_SEMANTICS = shift `(ts_utc + 2h).date()`; production strategy code uses wall-clock UTC date everywhere at HEAD.

---

## §8 · Real rest_allowance at 7996/8000 exercised through M4 boot hook

`test_closure_rest_allowance_7996_preserved` — **PASS**

Setup:

- `REST_ALLOWANCE_FILE` monkeypatched to a tmp path (`rest_allowance.py:110-112` reads this at module load; reloaded after monkeypatch).
- Pre-seeded state file: `{week_start: current-week-Monday, points_used: 7996, points_budget: 8000, reservations: {}}`.
- `socket.socket` blocked at the test level — any network attempt raises `RuntimeError`.
- `rest_allowance.begin_reservation` wrapped with a counting shim to detect any invocation.

Execution:

- Ran `daily_snapshot.ensure_snapshot_for_today` for three symbols (GBPUSD, EURUSD, USDJPY) — mirrors the `autobot.py:10517-10534` boot-hook loop over `EPIC_MAP`.
- GBPUSD rebuild succeeded (D1 cache seeded); EURUSD and USDJPY logged `cache_missing` warnings and returned `unavailable`. Neither error path opened a socket or reached rest_allowance.

Post-boot state via `rest_allowance.get_state()`:

```
7996_BEFORE                        = 7996
7996_AFTER                         = 7996
ALLOWANCE_BEGIN_RESERVATION_CALLS  = 0
ALLOWANCE_RESERVATIONS_CREATED     = 0
HISTORICAL_REST_CALLS              = 0
NETWORK_ATTEMPTS                   = 0
```

The `test_closure_boot_flow_zero_network` composite test additionally runs the full Path-A flow (5m ingest + H1/H4 persist + boot reload + snapshot ensure) under `socket.socket` blocked and confirms the allowance state is still 7996 at the end.

---

## §9 · Complete local readiness

Answered by the same fixture the parity tests use:

| Field | Value | Source |
|---|---|---|
| `5M_HISTORY_READY` | YES | 4200+ rows fed through `TimeframeContext.on_5m_close` |
| `H1_READY` | YES | Common H1 intersection non-empty; readiness slices identical A/B |
| `H4_READY` | YES | Common H4 intersection ≥ 60 buckets (production consumer depth) |
| `H4_CONSUMERS_READY` | YES | `structural_state_ready_30` / `ff_h4_ready_50` / `swing_ready_30` / `trend_v3_ready_12` / `sixty_bar_consumer_ready` all True in both paths |
| `AUTHORITATIVE_D1_READY` | YES | `cache/htf/GBPUSD_D1.json` seeded with Thu + Fri; `select_prior_completed_d1(SYM, Monday)` returns Friday's D1 |
| `DAILY_SNAPSHOT_READY` | YES | `ensure_snapshot_for_today(SYM, Monday)` returns `("rebuilt", <valid snap>)` |
| `DATA_CONTEXT_READY` | YES | All of the above at Mon 00:00 UTC and later |

- `STRATEGY_DAILY_CONTEXT_GATE_IMPLEMENTED = NO — expected until M5.` No production strategy at HEAD reads `daily_snapshot`; M4 is dark-wired.

---

## §10 · Stale-snapshot terminology

`test_closure_stale_snapshot_rejected_by_m4_only` — **PASS**

- `STALE_SNAPSHOT_REJECTED_BY_M4 = YES` — a Friday-dated snapshot loaded for Monday returns `(None, "trading_date_mismatch")`.
- `STRATEGY_CANNOT_TRADE_WITH_STALE_DAILY_CONTEXT = NOT_YET_PROVEN_M5` — no strategy at HEAD reads the snapshot, so the gate the ruling refers to does not yet exist. M5 wires the consumer + the readiness gate.

---

## §11 · Restart storm around the reopen

`test_closure_restart_storm_around_reopen` — **PASS**

Seven boot points executed sequentially against the same allowance state (7996/8000) and the same D1 cache:

| Point | Wall-clock | Outcome |
|---|---|---|
| Fri 22:00 UTC shutdown | 2026-03-20 | snapshot `rebuilt` for Fri (trading_date=Fri, source=Thu) |
| Sat 12:00 UTC restart | 2026-03-21 | `unavailable` (weekend); Fri snapshot preserved on disk |
| Sun 20:00 UTC pre-reopen restart | 2026-03-22 | `unavailable`; Fri snapshot preserved |
| Sun 22:05 UTC post-reopen restart | 2026-03-22 | `unavailable` (wall-clock=Sun); Fri snapshot preserved |
| Mon 06:00 UTC pre-entry restart | 2026-03-23 | snapshot `rebuilt` for Mon (source=Fri) |
| Mon 07:00 UTC at entry restart | 2026-03-23 | `loaded` (Mon snapshot present from prior boot); bytewise stable |
| Mon 07:05 UTC second restart | 2026-03-23 | `loaded`; snapshot bytes identical to previous point |

Invariants asserted:

- D1 cache mtime + size unchanged across all seven boots (M4 never mutates the D1 cache).
- `points_used` unchanged (7996) across all boots; `open_reservations == 0`, `uncertain_reservations == 0`.
- No Sat/Sun-dated snapshot ever created (would fail the `weekday < 5` assertion).
- Repeat Monday restart produces bytewise-identical snapshot file (deterministic under identical D1 input).

---

## §12 · Regression

Full run across the closure + accepted-chain suites (242 tests):

```
tests/unit/test_m4_closure_weekend_boot.py               9  PASS
tests/unit/test_daily_snapshot.py                       46  PASS  (M4)
tests/unit/test_multiday_weekend_fragment_guard.py      18  PASS  (783eb0e)
tests/unit/test_previous_trading_day_selector.py        14  PASS  (fa18a90)
tests/unit/test_historical_v2_m0_m3.py                  19  PASS  (M0-M3)
tests/unit/test_historical_v2_m0_m3_closure.py           7  PASS
tests/unit/test_htf_authority.py                         8  PASS
tests/unit/test_d1_weekend_guard.py                     10  PASS
tests/unit/test_d1_write_watchdog.py                    16  PASS
tests/unit/test_stale_anchor_gate.py                    12  PASS
tests/unit/test_gbpusd_confirmation_fallback.py          9  PASS
tests/unit/test_level_computation.py                    39  PASS
tests/unit/test_phase5_level_detector.py                12  PASS
tests/unit/test_market_state_snapshot_from_nms.py        5  PASS
tests/unit/test_phase5_acceptance.py                     7  PASS
tests/unit/test_regime_matrix_self_gates.py              9  PASS
tests/unit/test_v5_pia_rr_threshold.py                   2  PASS
                                                       ─── ────
                                                       242  PASS
```

`FA18A90_REGRESSION = PASS` · `783EB0E_REGRESSION = PASS` · `M0_M3_REGRESSION = PASS` · `M4_REGRESSION = PASS`.

---

## §14 · FINAL RETURN

```
M4_COMMIT_UNDER_TEST = 4bf3e55
CLOSURE_COMMIT       = (this commit)

PRODUCTION_CODE_CHANGED = NO
    (Two files touched:
       .gitignore                                          — allowlist entry
       tests/unit/test_m4_closure_weekend_boot.py          — new
     Zero production module modified.)

FULL_WEEKEND_CAUSAL_FIXTURE = PASS  (4200+ 5m, 90+ H4, 15 D1, real FX
                                     Fri 22:00-Sun 22:00 gap)

POST_WEEKEND_H1_PARITY        = PASS
POST_WEEKEND_H1_DIFF          = EMPTY  (common intersection)

POST_WEEKEND_H4_PARITY        = PASS
POST_WEEKEND_H4_DIFF          = EMPTY  (common intersection)

POST_WEEKEND_H4_CONSUMER_PARITY = PASS
POST_WEEKEND_H4_CONSUMER_DIFF   = EMPTY
    (structural_state closes[-30:], ff_h4 highs/lows/closes[-50:],
     swing_h4 tail-30 OHLC tuple, trend_v3 tail-12 closes)

POST_WEEKEND_H4_READINESS_PARITY = PASS

POST_WEEKEND_DAILY_LEVEL_PARITY = PASS
POST_WEEKEND_DAILY_LEVEL_DIFF   = EMPTY
    (snapshot bytewise identical modulo calculated_at; nine levels,
     source_d1, previous_trading_date, trading_date all match)

SUNDAY_REOPEN_M4_STATUS            = unavailable
SUNDAY_REOPEN_CONTEXT_UNAVAILABLE  = YES
SUNDAY_REOPEN_CAN_TRADE            = NO
    (Two independent strategy-level gates block: (1) all five
     gbpusd_*.py strategies check ts.weekday() >= 5; (2)
     trade_executor.py:2560-2622 QM_ENTRY_HOURS blocks hour ∉ [7,17).
     News strategies have their own weekend detection.)
MONDAY_ENTRY_WINDOW_CONTEXT_READY  = YES
    (Snapshot rebuilt at any Mon 00:00 UTC or later boot; entry
     window opens at Mon 07:00 UTC — 7-hour margin.)

FX_SESSION_TRADING_DATE_SEMANTICS  =
    Production STRATEGY_TRADING_DATE  = datetime.utcnow().date()
                                        (day_posture.py:186,
                                         signal_logger.py:1136,
                                         gbpusd_*.py where used)
    Production D1_STORE_LABEL         = FX-session-aligned midnight-
                                        UTC-of-trading-day
                                        (timeframe_context.py:279-282
                                         + D1_SESSION_OFFSET_SEC =
                                         22*3600 at line 83)
    M4_BOOT_HOOK_ARGUMENT             = datetime.now(timezone.utc).date()
                                        (autobot.py:10518)
    M5 WILL NEED TO DEFINE            = the fx-session trading_date
                                        the strategy consumer passes to
                                        load_snapshot_if_valid. Today
                                        no strategy consumes the
                                        snapshot; M4 is dark-wired.

7996_BEFORE = 7996
7996_AFTER  = 7996

ALLOWANCE_BEGIN_RESERVATION_CALLS = 0
ALLOWANCE_RESERVATIONS_CREATED    = 0
HISTORICAL_REST_CALLS             = 0
NETWORK_ATTEMPTS                  = 0

5M_HISTORY_READY          = YES
H1_READY                  = YES  (common intersection non-empty,
                                   readiness slices identical A/B)
H4_READY                  = YES  (common H4 ≥ 60 buckets, both paths)
H4_CONSUMERS_READY        = YES  (all four consumer readiness flags True)
AUTHORITATIVE_D1_READY    = YES  (Friday D1 in htf cache; selector
                                   returns it for Monday fire_date)
DAILY_SNAPSHOT_READY      = YES  (ensure_snapshot_for_today returns
                                   rebuilt/loaded on Monday boots)
DATA_CONTEXT_READY        = YES  (all of the above at Mon 00:00+ UTC)

STALE_SNAPSHOT_REJECTED_BY_M4                  = YES
STRATEGY_CANNOT_TRADE_WITH_STALE_DAILY_CONTEXT = NOT_YET_PROVEN_M5
    (No production strategy reads daily_snapshot at HEAD; the M5
     work item wires the consumer + the fail-closed gate.)

RESTART_STORM = PASS  (7 boot points; D1 cache unchanged; allowance
                       fixed at 7996; no Sat/Sun-dated snapshots; repeat
                       Monday restart bytewise-deterministic)

FA18A90_REGRESSION = PASS  (test_previous_trading_day_selector.py 14/14)
783EB0E_REGRESSION = PASS  (test_multiday_weekend_fragment_guard.py 18/18)
M0_M3_REGRESSION   = PASS  (M0-M3 + M0-M3 closure + HTF + watchdog +
                            weekend guard + stale anchor 62/62)
M4_REGRESSION      = PASS  (test_daily_snapshot.py 46/46)

PRODUCTION_CODE_DEFECT_FOUND = NO
    (Sunday-reopen wall-clock/FX-session divergence is a semantic
     seam for M5, not a defect in M4. The dark-wire boot hook
     correctly delivers on its calendar-UTC contract; no strategy
     consumes the snapshot; two independent strategy-level gates
     block trading during the ambiguous window.)

LIVE_SERVICE_TOUCHED = NO
LIVE_CACHE_CHANGED   = NO
LIVE_IG_CONTACT      = NO

TRADE_ENABLED        = 0
STAGE10P             = PAUSED

M4_FINAL_ACCEPTANCE  = PASS

READY_FOR_M5         = YES
SAFE_TO_DEPLOY       = NO
```

STOP.
