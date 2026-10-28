# Scenario V2 — Correction 2 Deployment Plan

**Date drafted:** 2026-10-28
**Author:** AutoBot engineering (Claude Opus 4.7 / 1M context)
**Status:** **Not yet executed.**  This document is a plan for the operator; no production file is modified by it.

---

## 0. Non-authorisation reminder

The task that produced this plan was explicitly **development-only**.  The operator alone decides when (and whether) to execute the steps below.  Nothing in this document should be acted on without that explicit authorisation.

---

## 1. Deployment summary

Three files from the Correction 2 branch replace their deployed counterparts.  No systemd changes, no service restart.  Scenario V2 is **shadow-only** (no broker execution); the risk model matches the Correction 1 deployment two days ago.

## 2. Pre-deployment checklist

1. **Branch pointer.**  `fix/scenario-v2-correction2-structured-proposals-20261028` at commit `1a6dad3` (one commit on top of the Correction 1 baseline `6ec1987`).  Worktree: `/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/`.
2. **Hash of deployed Correction 1 file (for backup/rollback evidence):**
   ```bash
   sha256sum /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_recommendation.py
   # expected: fd00780e... (Correction 1)
   ```
3. **Full test sweep green** (24 new + 262 pre-existing passing; 1 pre-existing time-dependent macro-host test unrelated).
4. **Nothing to migrate downstream.**  No new column, no renamed field, no changed enum.  Dashboard, CSV exports, broker-execution path all consume the same data model.

## 3. Backup

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
BAK=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups
mkdir -p "$BAK"
cp /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_recommendation.py \
   "$BAK/scenario_recommendation.pre-c2.${TS}.py"
cp /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_quality.py \
   "$BAK/scenario_quality.pre-c2.${TS}.py"
cp /mnt/volume_lon1_1778405456698/research/live_obs/agent/scenario_reasoner.py \
   "$BAK/scenario_reasoner.pre-c2.${TS}.py"
sha256sum "$BAK"/*.pre-c2.${TS}.py > "$BAK/pre-c2.${TS}.sha256"
```

## 4. Staged atomic deployment

```bash
SRC=/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/scripts/research/live_obs/agent
DST=/mnt/volume_lon1_1778405456698/research/live_obs/agent

# Stage next to targets (same filesystem → atomic rename)
for f in scenario_recommendation.py scenario_quality.py scenario_reasoner.py; do
  cp "$SRC/$f" "$DST/${f}.c2.new"
done

# Verify copied bytes match the branch
diff -q "$SRC/scenario_recommendation.py" "$DST/scenario_recommendation.py.c2.new"
diff -q "$SRC/scenario_quality.py"         "$DST/scenario_quality.py.c2.new"
diff -q "$SRC/scenario_reasoner.py"        "$DST/scenario_reasoner.py.c2.new"

# Atomic swap
for f in scenario_recommendation.py scenario_quality.py scenario_reasoner.py; do
  mv "$DST/${f}.c2.new" "$DST/$f"
done

sha256sum "$DST"/scenario_*.py
```

## 5. Post-deployment verification

1. **Hashes updated.**  New SHA256s should match the three files at commit `1a6dad3`.
2. **Smoke test** (next scheduled sweep ≤ 5 min):
   * At least one shadow revision reaches the pipeline.
   * No stack trace in the shadow service logs.
   * Dashboard still renders the publication_decision + readiness columns.
3. **Shadow-journal row inspection.**  First revision after deployment:
   * If the AI emitted a complete `trade_proposal`: expect `publication_decision = VALID` + `readiness = READY` + `entry.provenance = "trade_proposal.entry_price=..."`.
   * If the AI omitted structured fields on a category-A/B BUY/SELL: expect `publication_decision = CAUTION` + flag `MISSING_STRUCTURED_PROPOSAL` + the narrative-regex fallback still populating entry/stop/target where possible.
4. **No service restart required.**  Both the shadow service and the dashboard import the modified modules from the mounted volume on each sweep.

## 6. Rollback

If any smoke-test criterion fails:

```bash
BAK=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups
TS=<timestamp used in §3>
DST=/mnt/volume_lon1_1778405456698/research/live_obs/agent
cp "$BAK/scenario_recommendation.pre-c2.${TS}.py" "$DST/scenario_recommendation.py"
cp "$BAK/scenario_quality.pre-c2.${TS}.py"         "$DST/scenario_quality.py"
cp "$BAK/scenario_reasoner.pre-c2.${TS}.py"        "$DST/scenario_reasoner.py"
sha256sum "$DST"/scenario_*.py
# expected: Correction-1 hashes
```

No service restart required; the next sweep will pick up the restored files.

## 7. First-24-hour watchlist

| Metric | Expected direction |
|---|---|
| Shadow revisions / day | unchanged (~40–45) |
| `MISSING_STRUCTURED_PROPOSAL` WARN count | > 0, gradually trending down as the AI learns the structured-first contract |
| CONDITIONAL readiness count | +20 % to +60 % vs. Correction 1 baseline |
| INCOMPLETE readiness count | −20 % to −30 % |
| INVALID readiness count | unchanged (no HIGH→INVALID path weakened) |
| Service-level errors | 0 (modules import-compatible with the mounted volume) |

If `INVALID` jumps materially — stop and investigate; it would mean the structured path is picking up invalid prices that the narrative fallback silently dropped before.

## 8. Explicit non-actions

* **Do not** modify any systemd timer or service.  The shadow service and the sweep CLI already read from the mounted volume on each invocation.
* **Do not** enable Scenario V2 broker execution.  This remains out of scope and unauthorised.
* **Do not** deploy P3 (`trigger_spec` evaluator CLI).  P3 remains prepared-but-not-installed.
* **Do not** amend any production environment variable file.
* **Do not** replace Correction 1's `scenario_recommendation.py` with a mix of Correction 2 changes and other work-in-progress.  Deploy the branch tip in one shot or not at all.

## 9. Communication after deployment

Post a one-line note in the shadow dashboard channel:

> Correction 2 (structured trade_proposal → primary numeric contract) deployed at `<TS UTC>`.  Shadow-only.  Dashboard: expect ↑ CONDITIONAL rows and new `MISSING_STRUCTURED_PROPOSAL` CAUTION flag on partial AI output.  Rollback: `<link to this doc §6>`.

---

*End of deployment plan.*
