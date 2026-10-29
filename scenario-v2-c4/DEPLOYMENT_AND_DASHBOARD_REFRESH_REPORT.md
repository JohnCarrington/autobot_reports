# Correction 4 — Deployment and Dashboard-Refresh Report

## 1. Timeline

| UTC | Event |
|---|---|
| 2026-10-29T10:21Z | C4 staging worktree created at `/home/autobot/reports-wt/scenario-v2-c4-20261029/` |
| 2026-10-29T10:27Z | C4 patches applied to staging; AST syntax check PASS on both files |
| 2026-10-29T10:33Z | 20 new C4 regression tests PASS (20/20) |
| 2026-10-29T10:38Z | Full test suite (262 pre-existing tests) under staging: 262 passed / 5 failed — matches pre-C4 baseline exactly |
| 2026-10-29T10:50Z | Historical replay (28 revisions, 4 configs) produced |
| 2026-10-29T12:10Z | Operator approval obtained for exact write sequence |
| 2026-10-29T12:15:26Z | Backup directory created: `agent/_backups/pre-c4-20261029T121526Z/` |
| 2026-10-29T12:15:26Z | Pre-C4 files backed up (3 files); SHA256 recorded |
| 2026-10-29T12:15:41Z | Production write — `scenario_quality.py` and `scenario_reasoner.py` installed atomically (install -m 0644) |
| 2026-10-29T12:15:41Z | Production SHA256 verified against staging: MATCH |
| 2026-10-29T12:15:41Z | `scenario_recommendation.py` SHA256 verified UNCHANGED (C2 preserved) |
| 2026-10-29T12:20:06Z | First post-C4 sweep ran (`live-market-observer-scenario-shadow.service`), Result=success |
| 2026-10-29T12:21:04Z | First post-C4 scenario row written to journal — flags: `CATEGORY_C_WITHOUT_VERIFIED_RELEASE`×2 (legitimate), NO CATEGORY_A, NO CONFIDENCE_PERCENT |
| 2026-10-29T12:22:46Z | Dashboard-only restart (`live-market-observer-dashboard.service`) — operator-run `sudo systemctl restart` |
| 2026-10-29T12:22:46Z | Dashboard ActiveState=active, Result=success, no errors in startup logs |
| 2026-10-29T12:22:46Z | Step 11 verified: `target.provenance = "trade_proposal.target_price=13300.0"` (C2 contract now visible — previously stale `sequence_token_match=…`) |

## 2. Pre-deploy sanity

| Check | Status | Evidence |
|---|---|---|
| Root filesystem has sufficient free space | **PASS** | `/dev/vda1 23G used / 1.5G free`; sufficient for `install` + backup. (Pre-C4 the volume was 100% full; 1.5 GB was freed via `git worktree remove --force` on 27 abandoned clean worktrees in `/tmp/`, each individually verified for status + process-use before removal.) |
| Next scenario sweep > 60 s away | **PASS** | At 12:15Z, next sweep was 12:20:03Z (4m 50s). Both installs completed by 12:15:41Z — ~4m 22s before next sweep. |
| Timer not stopped (operator restriction preserved) | **PASS** | `live-market-observer-scenario-shadow.timer` left running. |
| scenario_recommendation.py untouched | **PASS** | SHA256 `7edce8c9…` before + after. |

## 3. Write sequence (actual)

```bash
TS=20261029T121526Z
BACKUP_DIR=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c4-${TS}

# Step 1
mkdir -p "$BACKUP_DIR"

# Steps 2-3: backup pre-C4 production files (preserving mtime)
cp -p agent/scenario_quality.py   "$BACKUP_DIR/scenario_quality.py.pre-c4-${TS}"
cp -p agent/scenario_reasoner.py  "$BACKUP_DIR/scenario_reasoner.py.pre-c4-${TS}"
cp -p agent/scenario_recommendation.py "$BACKUP_DIR/scenario_recommendation.py.unchanged-c4-${TS}"

# Step 4: compute + record SHA256 of backups
sha256sum "$BACKUP_DIR"/*.pre-c4-* "$BACKUP_DIR"/*.unchanged-c4-* > "$BACKUP_DIR/pre-c4-${TS}.sha256"

# Steps 5-6: atomic install of C4 files
install -m 0644 staging/agent/scenario_quality.py  agent/scenario_quality.py && \
install -m 0644 staging/agent/scenario_reasoner.py agent/scenario_reasoner.py

# Step 7: verify SHA256
PROD_QS=$(sha256sum agent/scenario_quality.py   | awk '{print $1}')
PROD_RS=$(sha256sum agent/scenario_reasoner.py  | awk '{print $1}')
STAGE_QS=$(sha256sum staging/agent/scenario_quality.py  | awk '{print $1}')
STAGE_RS=$(sha256sum staging/agent/scenario_reasoner.py | awk '{print $1}')
[ "$PROD_QS" = "$STAGE_QS" ] && echo "scenario_quality MATCH"
[ "$PROD_RS" = "$STAGE_RS" ] && echo "scenario_reasoner MATCH"
```

Both installs completed in <1 second total between the two `install` calls. No sweep ran during the write window.

## 4. Hashes recorded

### Backups (`_backups/pre-c4-20261029T121526Z/pre-c4-20261029T121526Z.sha256`)

```
718855ed6848b7ab816169d3d00232c15043a4f2720a3523b9b690102f821522  scenario_quality.py.pre-c4-20261029T121526Z
a9af10b95e8e9e4bc06406ba494667a065f8c9b993c3106cefdb80e473fbffab  scenario_reasoner.py.pre-c4-20261029T121526Z
7edce8c9cc40e2aad1cdb9f8b8a82d6ace7f542a93240a940e95d5f3816f88af  scenario_recommendation.py.unchanged-c4-20261029T121526Z
```

### Post-deploy production

| File | sha256 |
|---|---|
| `scenario_quality.py` | `4931aee2291407a78c2538ddc3fb65f99df67159c7bab97d6f09fc7993c33ede` |
| `scenario_reasoner.py` | `e10977e9e5f608c4840f49c7637fe39fc3966f5c1a35db0f59003e6f22c75845` |
| `scenario_recommendation.py` | `7edce8c9cc40e2aad1cdb9f8b8a82d6ace7f542a93240a940e95d5f3816f88af` **(unchanged)** |

## 5. First live post-C4 sweep (verification)

Scenario row (`scenarios_shadow.jsonl`, bar 12:10 UTC, generated 12:21:04Z):

```
scenario_id: bd7fbcce36c2c777 (reversal setup; different from the morning's 9fb58109c4dc34c2)
state: DEVELOPING
primary_direction: SELL
trade_proposal: entry=13311.0 stop=13334.0 target=13300.0
```

Quality decision (`scenario_quality_flags.jsonl`, same bar, generated 12:21:04Z):

```
decision: INVALID
flag_codes: ['CATEGORY_C_WITHOUT_VERIFIED_RELEASE', 'CATEGORY_C_WITHOUT_VERIFIED_RELEASE']
```

Material observation: **the two false-positive HIGH codes removed by C4 are absent from this live post-deploy output:**
- `CATEGORY_A_TRIGGER_WITH_EVENT_NAME` — not present (eliminated).
- `UNSUPPORTED_CONFIDENCE_PERCENT` — not present (eliminated).

The INVALID remains, correctly, due to `CATEGORY_C_WITHOUT_VERIFIED_RELEASE` × 2 — the reversal opportunities (both BUY and SELL variants on this scenario) are tagged category=C and reference a 12:30Z USD release that has not yet been released at 12:21Z. This is the preserved legitimate HIGH behaviour required by task §6.

## 6. Dashboard restart (step 10) and provenance verification (step 11)

```
# BEFORE restart
MainPID=770269
ExecMainStartTimestamp=Fri 2026-10-23 14:51:21 UTC   (5 days 21 hours uptime; pre-C2 sys.modules cache)
```

Restart performed by operator:

```
sudo systemctl restart live-market-observer-dashboard.service
```

```
# AFTER restart
MainPID=2276997
ExecMainStartTimestamp=Thu 2026-10-29 12:22:46 UTC
Result=success
ActiveState=active

# startup logs
Oct 29 12:22:45 ... Stopping Live Market Observer Dashboard
Oct 29 12:22:46 ... Started Live Market Observer Dashboard
Oct 29 12:22:46 ... observer_webserver bound to 127.0.0.1:8090
```

### Target-provenance verification

```
# curl http://127.0.0.1:8090/observer/trade-recommendation (post-restart)
scenario_id: bd7fbcce36c2c777
entry.price: 13311.0,  provenance: "trade_proposal.entry_price=13311.0"
stop.price:  13334.0,  provenance: "trade_proposal.stop_price=13334.0"
target.price: 13300.0, provenance: "trade_proposal.target_price=13300.0"       ← C2 CONTRACT NOW VISIBLE
recommendation: WAIT
readiness: SUPPRESSED
```

Before the restart the same endpoint returned `target.provenance = "sequence_token_match='Downside Continuation to S1 (If R00 Break Holds)'"` — the pre-C2 pattern. The restart replaced the stale `sys.modules['scenario_recommendation']` with the on-disk C2 version. The dashboard now computes recommendations from the current C2 + C4 code.

## 7. Service isolation (operator §9)

Only `live-market-observer-dashboard.service` was restarted. The following services were NOT touched (confirmed by `ExecMainStartTimestamp` comparison across the window):

| Service | Status |
|---|---|
| `live-market-observer.service` | **not touched** (still PID 2213675, started 2026-10-29T07:00:02Z) |
| `live-market-observer-scenario-shadow.service` | timer-driven; last fires 12:20:06Z, 12:25:xxZ (natural, not caused by restart) |
| `live-market-observer-shadow-exec.service` | timer-driven; untouched |
| `live-scenario-notifier.service` | timer-driven; untouched |
| `live-market-observer-news-refresh.service` | timer-driven; untouched |
| AutoBot / NMS / EMA Pullback / BB Bounce / Trading Agent | not touched (not in Scenario V2 scope) |

## 8. Rollback procedure (if needed)

```bash
TS=20261029T121526Z
BACKUP=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/pre-c4-${TS}
TARGET=/mnt/volume_lon1_1778405456698/research/live_obs/agent

# Step 1: restore files to their EXACT original filenames
install -m 0644 "$BACKUP/scenario_quality.py.pre-c4-${TS}"  "$TARGET/scenario_quality.py"
install -m 0644 "$BACKUP/scenario_reasoner.py.pre-c4-${TS}" "$TARGET/scenario_reasoner.py"

# Step 2: SHA256 verify against the recorded pre-C4 hashes
cd "$BACKUP" && sha256sum -c pre-c4-${TS}.sha256 --ignore-missing  # should PASS for the two restored

# Step 3: verify production hashes match the pre-C4 hashes
EXPECTED_Q=718855ed6848b7ab816169d3d00232c15043a4f2720a3523b9b690102f821522
EXPECTED_R=a9af10b95e8e9e4bc06406ba494667a065f8c9b993c3106cefdb80e473fbffab
[ "$(sha256sum $TARGET/scenario_quality.py  | awk '{print $1}')" = "$EXPECTED_Q" ] && echo "Q OK" || echo "Q FAIL"
[ "$(sha256sum $TARGET/scenario_reasoner.py | awk '{print $1}')" = "$EXPECTED_R" ] && echo "R OK" || echo "R FAIL"

# Step 4: restart dashboard only
sudo systemctl restart live-market-observer-dashboard.service

# Step 5: next scenario sweep will import pre-C4 code (sweeper is oneshot — fresh import each tick)
```

Rollback is file-replace only — no DB migration, no state cleanup, no journal mutation. Rollback restores EXACT original filenames (`scenario_quality.py` and `scenario_reasoner.py` — not the backup-timestamped names).

## 9. Residual observations

- `scenarios_shadow.jsonl` and `scenario_quality_flags.jsonl` retain ALL pre- and post-C4 rows — no mutation of historical evidence (operator §12).
- `_backups/pre-c4-20261029T121526Z/` is a 134 KB directory containing three backup files plus the sha256 manifest. It should NOT be deleted; it is the rollback target.
- The C4 behaviour will become fully observable as 12:30Z passes and the USD releases either VERIFY (clearing `CATEGORY_C_WITHOUT_VERIFIED_RELEASE`) or EXPIRE. Expected post-release pattern: category C can resolve to publishable; category A reversal-opp can resolve to publishable; INVALID count drops further.
- The authority to publish lies entirely with the scenario sweeper — Scenario V2 remains shadow-only, no broker interaction.
