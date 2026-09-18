# QM SDE Liveness and Measurement Checkpoint — 2026-09-18

**Diagnosis only.** No code, configuration, .env, restart, merge, broker action or fix.

---

## Executive verdict

- **§4 QM verdict: `QM_ALIVE_NO_QUALIFYING_CANDIDATES`** for the specific self-check window; **`QM_ALIVE_AND_EMITTING`** across the wider post-restart window.
- **NOT `QM_SILENCE_DEFECT_PROVEN`.** Genealogy audit is therefore in scope; a scoped summary is delivered below (§7) with the 18 September measurement/receipt trace added to the three-event analysis.
- **§1 Telegram alarm is a false-positive**, cleanly explained by an asymmetry in the QM self-check registry design (§1.5). No production silence, no code defect in QM itself.

---

## §1 — Captured Telegram receipt (exact)

**Journal entry, verbatim:**

```
2026-09-17 20:50:00,570 [ERROR] [QM-SELFCHECK] ERROR — 1/5 QM modules
silent despite trigger conditions in first 9 bars: qm_sde.candidates
| IDLE:awaiting_trigger: qm_hooks.exit_shadow
```

| Field | Value |
|---|---|
| **Timestamp** | `2026-09-17T20:50:00.570Z` (~22 min after 20:28:32 restart) |
| **Pair** | not scoped — the self-check is process-wide, not per-pair |
| **Self-check name** | `[QM-SELFCHECK]` sweep implemented in `qm_module_registry.py:187` (`on_bar_close`) |
| **Failing module** | `qm_sde.candidates` (JSONL sink `/opt/tradingbot/logs/qm_candidates.jsonl`; registered at `qm_hooks.py:74`) |
| **Expected condition** | `qm_candidates.jsonl` size at sweep time > baseline size at boot |
| **Observed condition** | File size **unchanged** since boot (see §3 for the causal reason) |
| **Lookback window** | `_BAR_COUNTER >= grace_bars (6) + sweep_bars (3) = 9` bar-close callback invocations from boot. Since qm_hooks._on_5m_close fires ONCE per pair per bar, and two pairs (GBPUSD, EURUSD) are subscribed, 9 counter ticks ≈ 4.5 wall-clock bars ≈ 22 min — matches the alarm time. |

### 1.5 Why the check expected qm_sde.candidates specifically

Reference: `qm_module_registry.py:107-115` — the `register(name, jsonl_path, ..., trigger_seen)` API allows a module to register a `trigger_seen` predicate. When no predicate is supplied, the module is treated as **"trigger always seen"** (see docstring), so any absence of output for ≥ `sweep_bars` counter ticks fires `[QM-SELFCHECK] ERROR`.

Per `qm_hooks.py:74`:

```python
_qm_reg.register("qm_sde.candidates", jsonl_path=str(_LOG_DIR / "qm_candidates.jsonl"))
```

**No `trigger_seen` predicate is supplied.** Contrast with the sibling registration at `qm_hooks.py:69-73`:

```python
_qm_reg.register(
    "qm_hooks.exit_shadow", jsonl_path=str(_LOG_DIR / "qm_exit_decisions.jsonl"),
    trigger_seen=_any_open_position,
)
```

`qm_hooks.exit_shadow` correctly classifies as **IDLE:awaiting_trigger** at 20:50 because no positions were open. `qm_sde.candidates` cannot make the same distinction and is misclassified as **ERROR**.

### 1.6 Did qualifying triggers actually occur during the window?

Between `2026-09-17T20:28:32Z` (restart) and `2026-09-17T20:50:00Z` (alarm), the actual production log evidence:

- `qm_candidates.jsonl` — **0 writes**.
- `qm_decision_shadow.persist_candidate()` (the sole writer at `qm_decision_shadow.py:2307`) is called **only on `ENTRY_ARMED` transitions or terminal-state transitions**. Docstring at `qm_decision_shadow.py:2308`.
- First post-restart write to `qm_candidates.jsonl` landed at **2026-09-17T23:55:00Z** (GBPUSD, `APPROACHING_ZONE`) — 3h 27m after restart, deep into the quiet Asian pre-session.

**No qualifying trigger occurred in the alarm window.** The self-check was a **false-positive** due to the missing `trigger_seen` predicate.

---

## §2 — QM configuration + authority (loaded from PID 467277's env)

Extracted verbatim from `/proc/467277/environ`:

```
QM_LIVE_FIRE=1
QM_ENTRY_HOURS_ENABLED=1
QM_ENTRY_HOUR_START=7
QM_ENTRY_HOUR_END=17
QM_ACCEPT_CLOSES=2
QM_ADAPTIVE_EXIT_ENABLED=1
QM_BAND_TOUCH_TOL_PIPS=1.0
QM_BREAKAWAY_DIST_PIPS=10
QM_CHOP_CROSS_WINDOW=24
QM_CLUSTER_WIDTH_PIPS=5.0
QM_EARLY_WEIGHT_ENABLED=0
QM_LEVEL_ZONE_PIPS=3.0
QM_OSC_CROSS_MIN=3
QM_UM_CATASTROPHIC_TP_PIPS=100
CENTRAL_EXECUTION_GATE=1
CENTRAL_STRATEGY_ORCHESTRATOR=1
```

### Authority matrix

| Capability | Authorised? | Evidence |
|---|---|---|
| Emit candidates | **YES** (in-session, 07:00–17:00 UTC) | `QM_LIVE_FIRE=1`, `QM_ENTRY_HOURS_ENABLED=1` |
| Veto legacy candidates | Not applicable (QM is not a veto layer; it's an autonomous decision path) | — |
| Execute entries | **YES** in-session | `QM_LIVE_FIRE=1` |
| Manage positions | **YES** (via `qm_hooks.exit_shadow`, adaptive exit) | `QM_ADAPTIVE_EXIT_ENABLED=1` |
| Close positions | **YES** via same path as execute | same |
| Record telemetry | **YES** unconditionally | all `qm_hooks.*` registers write jsonl regardless of authority |

QM has **full live authority** in the configured hours. Any silence outside those hours is expected.

---

## §3 — Real QM caller chain + counts since 2026-09-17 20:28:32

### Chain (production evidence at each step)

```
5m bar close
  → candle_builder._emit_native_close(pair, bar)                            (production)
  → registered 5m-close callback list (in-order fan-out)                    (production)
  → qm_hooks._on_5m_close(payload)                                          (qm_hooks.py:575)
      ├── _run_build1 (LEVEL MAP)     → qm_level_map.jsonl                  (qm_hooks.py:66)
      ├── _run_build2 (INTERACTIONS)  → qm_level_interactions.jsonl         (implicit)
      ├── _run_build3 (CHOP FEATURES) → qm_chop_features.jsonl              (qm_hooks.py:68)
      ├── _run_part2_exit_rule        → qm_exit_decisions.jsonl             (qm_hooks.py:69-73, needs open pos)
      ├── _run_build4_shadow (EXIT SHADOW) → jsonl
      ├── _run_build5                                                        (varied)
      ├── qm_decision_shadow.on_5m_close_sde(...)                            (qm_hooks.py:680)
      │     └── (on ENTRY_ARMED or terminal) persist_candidate()             (qm_decision_shadow.py:2115, 2279, 2307)
      │           → append line to /opt/tradingbot/logs/qm_candidates.jsonl
      ├── qm_thesis.heartbeat(symbol)                                       (qm_hooks.py:695)
      ├── news_trend_classifier.on_bar_close_with_bounce(...)               (qm_hooks.py:729)
      ├── news_trend_entry.on_bar_close(...)                                (qm_hooks.py:753)
      └── _qm_reg.on_bar_close()  # the self-check sweeper                   (qm_hooks.py:775)
```

### Counts since 2026-09-17 20:28:32 (through 2026-09-18 ~10:00 UTC)

| Stage | Evidence source | Count |
|---|---|---|
| Qualifying bar-close callback invocations | `qm_chop_features.jsonl` post-restart | ~277 (24/hour × 2 pairs × ~11.5h) — matches expected 12 bars/hour |
| qm_hooks.level_map writes | `qm_level_map.jsonl` | 277 post-restart |
| qm_hooks.chop_features writes | `qm_chop_features.jsonl` | 277 post-restart |
| qm_hooks.exit_shadow writes | `qm_exit_decisions.jsonl` | 0 (correct — no open positions in most of the window; trigger predicate `_any_open_position`) |
| qm_sde.candidates writes | `qm_candidates.jsonl` | 15 post-restart (first at 2026-09-17T23:55 GBPUSD `APPROACHING_ZONE`; 8 GBPUSD/EURUSD `APPROACHING_ZONE`/`EXTREME_REACHED`/`REVERSAL_CANDIDATE`/`LEVEL_ACCEPTED` on Sep 18) |
| qm_thesis writes | `qm_thesis.jsonl` | 38 post-restart |
| Post-restart `ENTRY_ARMED` transitions | `qm_candidates.jsonl` state=ENTRY_ARMED | **0** in the alarm window; total post-restart same-day: none captured with `armed_at_ts>=2026-09-17T20:28` because writes carry `opened_at`/`armed_at_ts` set to the *original* transition ts, not the persist ts |
| Explicit QM live fires | Journal `[QM_V2*]` FIRED lines | 0 during 20:28 → present (no QM_V2_VELOCITY_S fires in the current PID's uptime — matches "only rejection-window bars produce fires" observation from wider audit) |
| Self-check ERRORs | Journal `[QM-SELFCHECK] ERROR` | 1 (the reported 20:50 alarm) |
| Self-check module-level failures | Same | 1 module: `qm_sde.candidates`; other modules: healthy or IDLE-with-predicate |
| Exceptions raised inside qm_sde driver | Journal `[QM-SDE].*raised` | 0 |

`qm_sde` is proven-invoked on every 5m bar (via `qm_hooks._on_5m_close`). No exceptions. Zero WRITES until 23:55 because there was no zone reaching `ENTRY_ARMED` / terminal in that window.

---

## §4 — Before-vs-after Phase 2B restart comparison

### QM candidate rows by date (raw file — `qm_candidates.jsonl`)

| Date | Total writes | ENTRY_ARMED transitions |
|---|---|---|
| 2026-09-14 | 5 | 0 |
| 2026-09-15 | 24 | 0 |
| 2026-09-16 | 80 | 5 |
| 2026-09-17 | 95 | 8 |
| 2026-09-18 (through ~10:00 UTC) | 8 | 0 (partial day; live entries would arrive later) |

Sep 17 activity is **higher** than Sep 15/16 pre-restart. The 20:28 restart falls INSIDE Sep 17 — of the 95 rows for that date, most (80+) were pre-restart. The 15 post-restart rows on Sep 17 are all `APPROACHING_ZONE`/`EXTREME_REACHED` state transitions in the quiet Asian window; no `ENTRY_ARMED`.

### Enabled flags — unchanged pre vs post restart

Env snapshot at PID 467277 shows the same QM enablement flags as the pre-restart PID would have loaded (`.env` file mtime `2026-09-17 20:26:28`, size 45572 — matches `env-history/env.20260917T202832Z`). No change to `QM_LIVE_FIRE`, `QM_ENTRY_HOURS_ENABLED`, `QM_ENTRY_HOUR_START/END`, or any other QM flag.

### Classification

| Verdict | Applies |
|---|---|
| **QM_SILENT_EXPECTED_BY_CONFIGURATION** | No — QM_LIVE_FIRE=1, in-session hours configured. |
| **QM_ALIVE_AND_EMITTING** | **YES** (over the wider post-restart window: 15 candidate writes + 38 thesis writes + 277 level_map/chop_features writes) |
| **QM_ALIVE_NO_QUALIFYING_CANDIDATES** | **YES** for the specific 20:28-20:50 alarm window (no zone reached ENTRY_ARMED / terminal; expected during a quiet late-London-close period) |
| **QM_SILENCE_DEFECT_PROVEN** | **NO** — see per-stage counts in §3 and the false-positive analysis in §1.5. |
| **PHASE2B_MERGE_REGRESSION** | **NO** — Phase 2B code changes are additive measurement writers (bb_pierce_recorder, phase2b_inc2_ownership_adapter, phase2b_inc3_level_bounce_adapter, measurement_writer, phase2b_inc2_counterfactual_predicates). None of them intercept or mutate the qm_hooks._on_5m_close callback path or the qm_decision_shadow driver. Verified by inspection: `git diff 221b378..HEAD -- gbpusd_bb_bounce.py candle_builder.py native_5m_source.py qm_hooks.py qm_decision_shadow.py` on the primary tree shows no changes to `qm_hooks.py` or `qm_decision_shadow.py`. |
| **INSUFFICIENT_PRODUCTION_EVIDENCE** | No — evidence is available and consistent. |

**Final classification: `QM_ALIVE_AND_EMITTING` (wide window); `QM_ALIVE_NO_QUALIFYING_CANDIDATES` (alarm window). NOT `QM_SILENCE_DEFECT_PROVEN`, NOT `PHASE2B_MERGE_REGRESSION`.**

---

## §5 — Measurement chain for `DIAAAAYHCG6LWBM` (live BB position)

Position: GBPUSD BUY, opened 2026-09-18T07:45:04Z at 13369.6, strategy `GBPUSD_BB_BOUNCE_L`, live.

| Chain step | Record type / source | Status |
|---|---|---|
| Detector evaluation (BB_BOUNCE family) | `phase2b_measurement.jsonl` `record_type=DETECTOR_EVAL family=BB_BOUNCE` | **MEASUREMENT_DETECTOR_STATUS = INSTRUMENTED_AND_EMITTING** — 4 rows for the 07:30-07:45 bars, states `PIERCE_LOWER` (07:30, 07:35) → `NO_PIERCE` (07:40, 07:45). |
| Candidate corpus row | `candidate_corpus.jsonl` | **PRESENT** — 2 rows at 07:45:04.319 and 07:45:04.602, strategy `GBPUSD_BB_BOUNCE_L`, gate_allowed=True, executed=True. |
| Gate disposition | `candidate_corpus.jsonl` reason_codes | **PRESENT** — full APPROVE_FINAL walk with `concurrent_cap_ok_0_1`, `one_book:coherence_ok`, etc. (see prior audit for full receipt) |
| Broker open | `journalctl` `✅ Trade OPENED` + `IG response` | **PRESENT** — 2026-09-18T07:45:04Z, entry 13369.6 |
| Ownership snapshots (Phase 2B inc2) | `phase2b_measurement.jsonl` `record_type=POSITION_OWNERSHIP_SNAPSHOT` | **MEASUREMENT_OWNERSHIP_STATUS = INSTRUMENTED_AND_EMITTING** — 30 rows and counting, one per 5m bar since 07:45:06, `source_module=phase2b_inc2_ownership_adapter` |
| Counterfactual invalidation shadow | `phase2b_measurement.jsonl` `record_type=COUNTERFACTUAL_INVALIDATION_SHADOW` | **MEASUREMENT_SHADOW_STATUS = INSTRUMENTED_AND_EMITTING** — 30 rows paired with ownership snapshots, `source_class=COUNTERFACTUAL_SHADOW`, zero rows claim `would_trigger_close=True` |
| GATE_DECISION Phase 2B record | not written | **IMPLEMENTED_NOT_WIRED** — no `GATE_DECISION` record type is emitted for this deal by any adapter; gate walks are captured in the existing `candidate_corpus.jsonl` `gate_reason_codes` (see prior audit) |
| POSITION_OPEN Phase 2B record | not written | **IMPLEMENTED_NOT_WIRED** — position-open is captured in the existing `signal_log`/`bb_pierce_trades.jsonl` chain and the broker journal, not (yet) as a distinct Phase 2B record type |

**FULL_MEASUREMENT_CHAIN_STATUS = `INSTRUMENTED_WITH_DOCUMENTED_UNWIRED_RECORD_TYPES`.** The three Phase 2B-owned record types (`DETECTOR_EVAL`, `POSITION_OWNERSHIP_SNAPSHOT`, `COUNTERFACTUAL_INVALIDATION_SHADOW`) all emit correctly and join to this deal. The two record types (`GATE_DECISION`, `POSITION_OPEN`) that some earlier design docs proposed as Phase 2B additions are `IMPLEMENTED_NOT_WIRED` per the operator's honesty rule.

---

## §6 — Decision

**Decision: NOT `QM_SILENCE_DEFECT_PROVEN` — proceed with the strategy-genealogy audit (§7).**

Causal defect summary of the Telegram alarm (for the record, no fix):

- **`qm_sde.candidates` is registered without a `trigger_seen` predicate at `qm_hooks.py:74`.** The self-check treats predicate-less modules as "trigger always seen", so any absence of ENTRY_ARMED-or-terminal transitions in the first ~9 counter ticks after boot fires a false-positive ERROR. Sibling modules (`qm_hooks.exit_shadow`) that DO supply a predicate correctly classify as `IDLE:awaiting_trigger`.

---

## §7 — Strategy-genealogy audit (scoped) + 18 September receipt trace

### 7.1 Genealogy — architectural authority vs statistical superiority

| Family | Architectural authority | Statistical basis (recent) | Interaction |
|---|---|---|---|
| `BB_BOUNCE` | Legacy detector; still authorized to emit + execute (autonomous). Fires from `gbpusd_bb_bounce.GbpUsdBBBounceStrategy.evaluate`. | Sep 16-17 executed multiple times (see prior audit). Sep 18 07:45 fire = `DIAAAAYHCG6LWBM` (live). | Central gate + one_book + concurrent_cap gate its admissions. |
| `TREND_V3` | Legacy detector; authorized. | Sep 16 & 17 executed (see audit). | Same central gate. |
| `LEVEL_BOUNCE` | Legacy detector; authorized. | Prior period had emissions; recent replay batch demonstrated PARTIAL reproduction. | Same central gate. |
| `QM_V2_VELOCITY_S/L` (SDE) | **Authorized to emit + execute** (`QM_LIVE_FIRE=1`). NOT authoritative over other families — it's another autonomous emitter next to BB_BOUNCE/TREND_V3/LEVEL_BOUNCE. Does NOT veto them. | Sep 17 13:10 fire = QM_V2_VELOCITY_S (see prior audit). Post-restart: 0 QM_V2 fires so far (see §3). | Same central gate. |
| `NEWS_STRATEGY_*` / `NEWS_CONT_LEG` | Authorized in news windows. | Post-restart: no news-family fires. | Same central gate. |
| `EMA_PULLBACK` | Authorized; multiple environmental gates. | Recent activity per corpus. | Same central gate. |
| `STRUCTURE_BREAK` / `CONFIRMATION_FALLBACK` | Authorized. | Post-restart: no fires. | Same central gate. |

**Key architectural point:** QM is one autonomous emitter among many, **not** an authority layer over legacy families. Its "SDE" role (Systematic Decision Engine) is per its own decision-shadow logic (`qm_decision_shadow.py`), not a supervisory role over `BB_BOUNCE` etc. Statistical performance of QM vs legacy is a separate empirical question — the SELFCHECK alarm and the architecture don't answer it.

### 7.2 Three-event analysis, with the 18 September addition

Per prior audit reports, the three broker positions relevant to the recent audit history:

| Event | Position | Route | Strategy | Outcome |
|---|---|---|---|---|
| 2026-09-16 14:50 GBPUSD SELL | `DIAAAAYG2RPHFBE` | Autonomous BB_BOUNCE | `GBPUSD_BB_BOUNCE_S` | closed same day |
| 2026-09-17 13:10 GBPUSD SELL | `DIAAAAYG73Z4PBK` | Autonomous QM_V2 | `QM_V2_VELOCITY_S` | profit, target-first |
| 2026-09-17 15:45 GBPUSD SELL | `DIAAAAYG8JY59BV` | Autonomous TREND_V3 | `GBPUSD_TREND_V3_S` | loss (STRUCTURE_EXIT) |
| **2026-09-18 07:45 GBPUSD BUY** | **`DIAAAAYHCG6LWBM`** | **Autonomous BB_BOUNCE** | **`GBPUSD_BB_BOUNCE_L`** | **live, pnl ~-2 to -4p at time of report** |

**Measurement/receipt trace for the 18 September addition:**

- Setup detection: `bb_pierce_buy (setup_age=1b)` at 07:45:04.319 UTC (rejection bar = 07:40) — captured in `candidate_corpus.jsonl` reason_codes[0].
- Gate walk: full APPROVE_FINAL chain: `kill_switch_pass, observation_ok, news_direction:news_no_active_trend:NO_CLEAR_TREND, mid_news_off_route, normal_routing:NORMAL_PRODUCTIVE_BB_ONLY:BB_BOUNCE, opposing_level_off, mechanical_ok, entry_hours_ok, sl_block_ok, one_book:coherence_ok, news_post_lockout_ok, concurrent_cap:concurrent_cap_ok_0_1, bucket_dedup:bucket_dedup_ok, cooldown:cooldown_ok, ml_veto:shadow_ok:no_features, gate:APPROVE_FINAL`.
- Fire: `Opening BUY size=2.0 stopDist=20.0 limDist=100.0` → IG response `ACCEPTED, dealId=DIAAAAYHCG6LWBM, dealReference=FDWH6SSDJT8TYRZ, level=13369.6`.
- Reservation: gate `_RESERVATIONS[a0f99e25...]` — occupied, deal_id linked.
- Measurement: 4 DETECTOR_EVAL rows (BB_BOUNCE family, 07:30-07:45), 30 POSITION_OWNERSHIP_SNAPSHOT rows (07:45:06 onwards), 30 COUNTERFACTUAL_INVALIDATION_SHADOW rows.

**QM's role in this event: zero.** QM is not an emitter of BB_BOUNCE candidates; `GbpUsdBBBounceStrategy` (legacy detector) is the direct emitter. QM's SDE runs alongside on every bar via `qm_decision_shadow.on_5m_close_sde` and independently tracks its own zones; nothing about `DIAAAAYHCG6LWBM` requires or was influenced by QM.

### 7.3 Genealogy verdict

- **BB_BOUNCE / TREND_V3 / LEVEL_BOUNCE**: legacy detectors, live autonomous authority.
- **QM_V2 (SDE)**: additional autonomous emitter; live authority; **not** a supervisory or veto layer over the legacy families.
- **Recent execution counts** (10-day window per prior audit): mix of legacy and QM. Statistical superiority of QM vs legacy is not evidenced by the SELFCHECK alarm — that alarm is a design asymmetry.
- **Live position `DIAAAAYHCG6LWBM`** was emitted and gated through the legacy BB_BOUNCE + central gate path with the Phase 2B measurement adapters observing (not intervening) throughout.

---

## Appendix — no production changes

- No production code was modified.
- No configuration change, .env write, systemd action, broker action.
- Occupancy-repair worktree untouched.
- phase2b-apparatus worktree untouched.
- Live position `DIAAAAYHCG6LWBM` untouched.
- Independent close-only monitor for `DIAAAAYHCG6LWBM` continues untouched.
- No background monitors, tasks, or wakeups initiated by this batch.
