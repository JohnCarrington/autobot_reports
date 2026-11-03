# Scenario V2 — IG DEMO integration design

**Status:** DESIGN + IMPLEMENTATION STAGED. **NOT activated.** No
production file modified. No broker call made.

## 1. Scope

Install the new mechanical-setup derivation module
(`impl/v2_early_setup.py`) and the DEMO executor template
(`impl/v2_demo_executor.py.template`) alongside the deployed shadow
executor. On activation, the DEMO executor:

- Reads scenarios from `scenarios_shadow.jsonl` (same source as the
  deployed shadow sweeper).
- Calls `v2_early_setup.derive(..., mode="A")` to produce a coherent
  (entry, stop, target, expiry) setup.
- If a fill is produced AND flags allow AND NMS permits AND IG
  min-stop is acceptable, submits a market order via
  `autobot.execute_trade` with strategy tag `SCENARIO_V2_L` /
  `SCENARIO_V2_S`.
- Journals every decision (`DISPATCHED`, `DRY_RUN`, `DISABLED`,
  `SKIPPED`, …) to `v2_demo_decisions.jsonl` for audit.

The deployed shadow executor keeps running untouched. V2 DEMO is
**additive**; the operator may disable the shadow executor at
activation time or run both in parallel.

## 2. Reuse map (same facts as previous investigations; verified)

| Need | Reused component |
|---|---|
| Order submission | `autobot.execute_trade(decision, epic, …)` → `trade_executor.execute_trade` → `open_sb_now` |
| Stop + target attached on OPEN | `open_sb_now` passes `stopDistance` / `limitDistance` on POST `/positions/otc` |
| Account identity | `IG_ACC_TYPE=DEMO` validated at `ig_auth.py` import |
| Strategy tag | `ownership_identity._MODE_CODES` + `_SYSTEM_GROUP`: `SCENARIO_V2_L` → `SV2_L`, `SCENARIO_V2_S` → `SV2_S` |
| NMS gate | `nms_directional_authority.evaluate(symbol, strategy_family="BOUNCE_MEAN_REVERSION", side, …)` |
| IG min-stop | `ig_dealing_rules.is_known_too_tight(epic, stop_pips)` |
| Dedup | `EPIC_STATE` keyed by `epic + side + mode` — automatic via `execute_trade` |
| Exit management | `close_sb_now.reconcile_open_positions()` + `trade_manager.py` — central; no V2-side exit loop |
| Error handling | `trade_executor._extract_rejection_detail`, `ig_dealing_rules.record_rejection` on `ATTACHED_ORDER_LEVEL_ERROR` |

**V2 adds:** one derivation module, one DEMO executor template, a
2-line patch to `ownership_identity.py` for the new mode codes, and
one wrapper script template.

## 3. Feature-flag mechanism

Three env vars (default off / safe):

| Env var | Default | Effect |
|---|---|---|
| `V2_SV2_DEMO_ENABLED` | `0` | Master switch. `0` → log a `DISABLED` row, no broker call. |
| `V2_SV2_DEMO_DRY_RUN` | `1` | `1` → evaluate everything, log `DRY_RUN`, no broker call. |
| `V2_SV2_DEMO_MODE` | `A` | Which mechanism to use (A/B/C). A is recommended. |
| `V2_SV2_DEMO_POSITION_SIZE` | `0.5` | Pip stake. Capped at `V2_SV2_DEMO_MAX_SIZE` (default 2.0). |
| `IG_ACC_TYPE` | — | Must equal `DEMO` or module raises `EnvironmentError` at import. |

Activation sequence (brief §8 — operator-controlled):

1. Install `v2_early_setup.py` to
   `/mnt/.../live_obs/agent/v2_early_setup.py`.
2. Rename + install
   `v2_demo_executor.py.template` → `v2_demo_executor.py` to
   `/mnt/.../live_obs/agent/v2_demo_executor.py`.
3. Apply `patches/0001-reasoner-prompt-setup-types.patch` to
   `scenario_reasoner.py` (allows AI to emit new setup types).
4. Apply `patches/0002-parser-validator-setup-types.patch` to
   `scenario_recommendation.py` + `scenario_quality.py`.
5. Patch `ownership_identity.py` to add `SCENARIO_V2_L` / `SCENARIO_V2_S`
   mode codes (see `patches/0003-ownership-mode-codes.patch`).
6. Install the wrapper script (`v2_demo_sweeper.sh.template` — not
   present in this correction; operator writes one based on the
   deployed `run_shadow_exec.sh` with `V2_SV2_DEMO_*` env vars
   exported).
7. Install the systemd unit + timer (templates in
   `/mnt/.../live_obs/deploy/`).
8. Observe decision journal for a few sweeps with
   `V2_SV2_DEMO_ENABLED=1 V2_SV2_DEMO_DRY_RUN=1` — all rows should
   show `DRY_RUN` with full setup detail.
9. **Operator approval checkpoint.** Confirm `IG_ACC_TYPE=DEMO` is
   set, confirm no LIVE account anywhere, confirm EMA_PB / BB_BOUNCE
   positions are not affected.
10. Set `V2_SV2_DEMO_DRY_RUN=0`. The next sweep that passes all
    gates submits a real DEMO order.

## 4. Mutex / cross-strategy interaction

- `EPIC_STATE` dedup keyed by `epic + side + mode`. V2's mode is
  `SCENARIO_V2_L` / `SCENARIO_V2_S`, distinct from EMA_PB / BB_BOUNCE
  modes. V2 can legally hold a concurrent position with those
  strategies.
- `AUTOBOT_AGGREGATE_POSITION_CAP` (default 2) enforced by
  `trade_executor.execute_trade`. V2 contributes at most 1 concurrent
  position.
- One V2 position per pair per direction via EPIC_STATE.
- NMS directional authority gate consulted pre-submit; if NMS says
  no, V2 skips.

## 5. Failure modes

| Failure | Containment |
|---|---|
| `IG_ACC_TYPE=LIVE` | Module raises `EnvironmentError` at import; wrapper exits 3 before importing. |
| `V2_SV2_DEMO_ENABLED=0` | Executor logs SKIP; no broker call. |
| `V2_SV2_DEMO_DRY_RUN=1` | Executor evaluates everything but does not call broker. |
| Setup derivation returns `reject`/`wait`/`error` | Executor logs reason, no broker call. |
| NMS blocks | Logged with NMS reason_code. |
| IG min-stop too tight | Skipped; next sweep inherits learned min from `ig_dealing_rules`. |
| Broker rejects | Centralised handler in `trade_executor`; V2 adds no retry. |
| Mode-code registry missing | `open_sb_now` fallback deterministic abbreviation (`_fallback_mode_code`); audit may show `UNKNOWN` tag — not a hard failure. |

## 6. What is NOT in scope for this correction

- LIVE / funded account support. The import-time `IG_ACC_TYPE=DEMO`
  guard refuses to run anywhere else. Removing it requires a
  separate operator-approved change.
- Removal of the deployed shadow executor. The operator may do that
  independently at activation time.
- Dynamic position sizing. Fixed stake (default £0.5/pip) with a
  hard cap.
- Mechanism B or C activation. The default `V2_SV2_DEMO_MODE=A` is
  recommended; B and C are supported by the derivation module but
  showed worse geometric and P&L results in the backtest.
- Reasoner prompt activation. The prompt patch (patches/0001) is
  STAGED but requires operator approval to apply. Until applied,
  the AI continues to emit `setup_type=BREAKOUT` (implicit), and the
  DEMO executor will NOT fire — because A/B/C derivation requires
  the AI to allow non-breakout setups via the extended prompt.
  Operator may choose to activate ONLY the derivation module
  (deriving A from historical data regardless of what the AI
  emits), or activate both derivation + prompt.

## 7. Expected post-activation behaviour on today's data

If the derivation module were activated TODAY (with the deployed
scenario journal and `V2_SV2_DEMO_MODE=A`):

- 13 scenarios in the journal would be processed per sweep.
- 13 would produce a Mechanism A setup fill (every scenario fires).
- Of those: ~2 would hit target, ~5 would hit stop, ~7 would expire
  flat (per backtest).
- NMS gate behaviour cannot be forecast without live NMS state.
- IG min-stop may block some of the tighter buffered stops;
  dynamic learning kicks in on first rejection.

**Expected outcome: more fills than the deployed shadow executor,
smaller losses per stop (median -9.1 vs deployed shadow's -21.0),
and still net-negative on this sample.** This is a data-
accumulation deployment, not a profit prediction.
