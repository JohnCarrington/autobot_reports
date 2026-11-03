# Scenario V2 entry redesign — deployment readiness

**Status:** DESIGN + IMPLEMENTATION STAGED + REGRESSION TESTS GREEN.
**NOT DEPLOYED.** No production file modified. No broker call made.

> ## ⚠ Updated 2026-11-03 after final review
>
> * No DRY_RUN / shadow / simulation phase. The ENABLED flag is
>   the only master switch. See `FINAL_REVIEW.md` §4.
> * Earlier A P&L stats were MISREPORTED (−17.4 net); the
>   corrected number is **+59.9 net** on n=13. The claim that
>   this establishes profitability is NOT supported — sample is
>   still too small.
> * Preflight connectivity script added
>   (`scripts/preflight_demo_connectivity.py`): operator runs
>   once post-install, pre-activation.

**Branch:** `correction/scenario-v2-entry-redesign-20261103` on
`JohnCarrington/autobot_reports` (push on commit).

## 1. What this correction installs on operator approval

| Artefact | Path | Status |
|---|---|---|
| Mechanical setup derivation | `/mnt/.../live_obs/agent/v2_early_setup.py` | NEW FILE — pure logic, no I/O, no broker import |
| DEMO executor | `/mnt/.../live_obs/agent/v2_demo_executor.py` (from `.template`) | NEW FILE — DEMO guard at import, feature flagged, default-off |
| Reasoner prompt | `/mnt/.../live_obs/agent/scenario_reasoner.py` | PATCHED — extends TRIGGER_SPEC enum + TRADE_PROPOSAL schema; preserves directional reasoning |
| Narrative parser | `/mnt/.../live_obs/agent/scenario_recommendation.py` | PATCHED — accepts non-breakout setup types; BREAKOUT path unchanged |
| Publication validator | `/mnt/.../live_obs/agent/scenario_quality.py` | PATCHED — adds UNKNOWN_SETUP_TYPE + MISSING_INVALIDATION_REFERENCE flags |
| Strategy mode codes | `/opt/tradingbot/ownership_identity.py` | PATCHED — adds SCENARIO_V2_L / SCENARIO_V2_S (2 lines each in `_MODE_CODES` + `_SYSTEM_GROUP`) |
| Sweeper wrapper | `/mnt/.../live_obs/shadow_exec/v2_demo_sweeper.sh` | OPERATOR-WRITTEN — must mirror `run_shadow_exec.sh` but export V2_SV2_DEMO_* env vars; this correction supplies only the design (see `IG_DEMO_INTEGRATION.md` §3) because the auto-mode classifier refused to write an executable sweeper file. |
| Systemd unit + timer | `/etc/systemd/system/live-scenario-v2-demo-exec.{service,timer}` | OPERATOR-WRITTEN — same reason |

## 2. Pre-deploy verification

| Check | Expected |
|---|---|
| Production shadow_execution.py sha256 | `8648532de50526dfd93bd6e071d3978993a107187fbcb4efbedbba1817d0d4db` (unchanged) |
| Production run_shadow_exec.py sha256 | `d791dfc4901e8b55de78fdc55d0204df152dfb9110a1f6a17ad42b0f80811955` (unchanged) |
| Production run_shadow_exec.sh sha256 | `38d2e96b3e31ae3167b05543a4788aab1a53c8f91bbee3e3b020c90d2e0e82c3` (unchanged) |
| /opt/tradingbot/.env `IG_ACC_TYPE` | `DEMO` |
| No `v2_early_setup.py` already present | TRUE (ls /mnt/.../live_obs/agent/) |
| No `v2_demo_executor.py` already present | TRUE |
| Regression tests pass | 16/16 PASS |
| Mode codes unregistered pre-patch | TRUE (`grep SCENARIO_V2 /opt/tradingbot/ownership_identity.py` → empty) |

## 3. Operator activation sequence (NOT to be executed by Claude)

```sh
# 0. Baseline SHAs
sha256sum /mnt/volume_lon1_1778405456698/research/live_obs/agent/{shadow_execution.py,scenario_reasoner.py,scenario_recommendation.py,scenario_quality.py} \
          /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/{run_shadow_exec.py,run_shadow_exec.sh} \
          /opt/tradingbot/ownership_identity.py

# 1. Backup
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-v2-early-setup-$TS
mkdir -p "$BACKUP"
cp /mnt/volume_lon1_1778405456698/research/live_obs/agent/{scenario_reasoner.py,scenario_recommendation.py,scenario_quality.py} "$BACKUP/"
cp /opt/tradingbot/ownership_identity.py "$BACKUP/"
sha256sum "$BACKUP"/*.py > "$BACKUP/sha256.txt"

# 2. Install new modules
install -m 0644 /home/autobot/reports-wt/scenario-v2-entry-redesign-20261103/scenario_v2_entry_redesign_20261103/impl/v2_early_setup.py \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/v2_early_setup.py
install -m 0644 /home/autobot/reports-wt/scenario-v2-entry-redesign-20261103/scenario_v2_entry_redesign_20261103/impl/v2_demo_executor.py.template \
    /mnt/volume_lon1_1778405456698/research/live_obs/agent/v2_demo_executor.py
# (Remove the template header lines from v2_demo_executor.py manually — the
# .template file's first 15 lines are an operator notice.)

# 3. Apply patches
cd /mnt/volume_lon1_1778405456698/research/live_obs/agent/
patch -p1 < /home/autobot/.../patches/0001-reasoner-prompt-setup-types.patch
patch -p1 < /home/autobot/.../patches/0002-parser-validator-setup-types.patch
cd /opt/tradingbot/
patch -p1 < /home/autobot/.../patches/0003-ownership-mode-codes.patch

# 4. Verify
python3 -c "import ownership_identity as o; assert 'SCENARIO_V2_L' in o._MODE_CODES"
python3 -c "import sys; sys.path.insert(0,'/mnt/.../live_obs/agent'); import v2_early_setup; print(v2_early_setup.VALID_MODES)"

# 5. Pre-flight connectivity (READ-ONLY — no order placed)
cd /home/autobot/reports-wt/.../scenario_v2_entry_redesign_20261103/scripts
python3 preflight_demo_connectivity.py
# Must print "PREFLIGHT ALL GREEN".

# 6. Write wrapper + unit with ENABLED=0 FIRST (safe boot)
# Operator writes:
#   /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/v2_demo_sweeper.sh
#   /etc/systemd/system/live-scenario-v2-demo-exec.service
#   /etc/systemd/system/live-scenario-v2-demo-exec.timer
# with Environment=V2_SV2_DEMO_ENABLED=0 (safe default)
# sudo systemctl daemon-reload && sudo systemctl enable --now live-scenario-v2-demo-exec.timer

# 7. Observe one sweep in /mnt/.../live_obs/v2_demo_decisions.jsonl
#    Every row should show status=DISABLED with full setup detail.
#    This confirms the full pipeline runs correctly without any
#    broker call.

# 8. Operator approval checkpoint — confirm IG_ACC_TYPE=DEMO,
#    no LIVE account present, EMA_PB / BB_BOUNCE unaffected.

# 9. Flip V2_SV2_DEMO_ENABLED=1 in the unit file; sudo systemctl daemon-reload.
#    Next sweep that passes all gates submits a REAL IG DEMO order.
```

## 4. Rollback

Env-var disable (safest, no file edits):

```sh
sudo systemctl stop live-scenario-v2-demo-exec.timer
sudo systemctl disable live-scenario-v2-demo-exec.timer
sudo systemctl edit live-scenario-v2-demo-exec.service
# Set: Environment=V2_SV2_DEMO_ENABLED=0
sudo systemctl daemon-reload
```

File-level rollback (restore pre-correction baseline):

```sh
BACKUP=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-v2-early-setup-<TS>
install -m 0644 "$BACKUP/scenario_reasoner.py" /mnt/.../live_obs/agent/
install -m 0644 "$BACKUP/scenario_recommendation.py" /mnt/.../live_obs/agent/
install -m 0644 "$BACKUP/scenario_quality.py" /mnt/.../live_obs/agent/
install -m 0644 "$BACKUP/ownership_identity.py" /opt/tradingbot/
rm /mnt/.../live_obs/agent/v2_early_setup.py
rm /mnt/.../live_obs/agent/v2_demo_executor.py
```

Both rollback paths preserve the deployed `shadow_execution.py`
timestamp-anchor fix (sha `8648532d…`) and the deployed
`run_shadow_exec.py` coverage patch (sha `d791dfc4…`) — these are
UNTOUCHED by this correction.

## 5. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Prompt change breaks AI output | Low | Low | Prompt change is additive — BREAKOUT remains valid. Pre-existing scenarios unaffected. |
| Parser rejects new setup types until patch applied | Low | Low | Setup types `MOMENTUM_IMPULSE`/etc. are gated behind patch 0002; if the AI emits them before patch is applied, the parser falls back to narrative extraction and treats as INCOMPLETE. |
| DEMO executor misroutes an order to LIVE | Very low | Very high | Hard import guard: `IG_ACC_TYPE != DEMO` raises `EnvironmentError` at module scope. Wrapper exits 3 before importing on any wrong env. |
| V2 submits more trades than EMA_PB / BB_BOUNCE expect | Low | Low | `AUTOBOT_AGGREGATE_POSITION_CAP` enforces aggregate limit. V2 contributes at most 1 concurrent position by default sizing. |
| Backtest result does not generalise | High | Low | Explicitly disclosed. DEMO deployment is a data-accumulation exercise, not a profit prediction. Expect net-negative outcomes in first 30+ trades. |
| Operator forgets to flip DRY_RUN=0 after validation | Low | Low (no broker activity) | Dashboard shows DRY_RUN rows explicitly; no orders submitted. |

## 6. Explicit non-changes (restated)

- **Directional reasoning** (prompt L57-206, L314-323, L575-641) UNCHANGED.
- **Scenario state machine** UNCHANGED.
- **Publication-gate flag severities** for reasoning-quality rules UNCHANGED.
- **NMS directional authority** UNCHANGED.
- **EMA Pullback, BB Bounce, briefings** UNCHANGED.
- **The deployed shadow executor** continues to run (operator may disable at activation time; this correction does not touch it).

## 7. Honest expectations

- Mechanism A IS NOT PROVEN PROFITABLE on the available n=13 sample.
- A has BETTER TRADE GEOMETRY than M1 (R:R at entry 5-6× better,
  avg loss half, MDD 2.5× better).
- A is INFORMATION-ACCUMULATION BAIT: fires on more scenarios than
  M1 (13 vs 10) → faster accumulation of out-of-sample data.
- Target the 30-fill review before concluding anything on live DEMO
  performance.

## 8. Deliverables index

- `ROOT_CAUSE_AND_TRADE_CONSTRUCTION.md` — the three co-dependent
  causes of late entries; what is editable vs untouchable.
- `EARLY_ENTRY_METHODOLOGY.md` — formal spec of mechanisms A/B/C.
- `STOP_AND_TARGET_DESIGN.md` — stop-derivation rules + target
  preservation.
- `HISTORICAL_COMPARISON.md` — n=13 backtest with DEV/VAL split +
  honest sample-size caveats.
- `BACKTEST_RESULTS.csv` — 104 rows, reproducible via
  `scripts/backtest_coherent_setups.py`.
- `impl/v2_early_setup.py` — mechanical derivation module (pure
  logic, 16/16 tests pass).
- `impl/v2_demo_executor.py.template` — DEMO executor (DEMO guard
  at import, feature flagged, default off).
- `patches/0001-reasoner-prompt-setup-types.patch` — reasoner
  prompt extension.
- `patches/0002-parser-validator-setup-types.patch` — parser +
  validator updates.
- `patches/0003-ownership-mode-codes.patch` — strategy tag
  registration.
- `tests/test_v2_early_setup.py` — 16 regression tests.
- `IG_DEMO_INTEGRATION.md` — reuse map + activation sequence.
- `DEPLOYMENT_READINESS.md` — this file.
