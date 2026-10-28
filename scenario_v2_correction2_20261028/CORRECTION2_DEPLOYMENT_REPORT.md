# Correction 2 — Deployment Report

**Date:** 2026-10-28
**Deployment timestamp (UTC):** `2026-10-28T22:39:46Z`
**Operator-authorised:** yes (explicit go-ahead captured as `AskUserQuestion` answer in this session)

---

## 1. What was deployed

Three files from branch `fix/scenario-v2-correction2-structured-proposals-20261028` at commit `eebbaa6`:

* `scenario_recommendation.py`
* `scenario_quality.py`
* `scenario_reasoner.py`

Target directory: `/mnt/volume_lon1_1778405456698/research/live_obs/agent/`

## 2. Hashes

### 2.1 Pre-deploy (Correction 1 production baseline)

```
fd00780ee602945bc22fccdd49d3551882a2101f0f943add1566d99abe10b1ee  scenario_recommendation.py
617f469113cadb8c998c3dcc047596b5ac457694d89589828f71f92d2836bbb0  scenario_quality.py
584c5ff02eacbd94ad3a39c0f4e0d873dc4e36afcc51bf54fb4ff3107aa123b8  scenario_reasoner.py
```

### 2.2 Backup

```
Location: /mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups/
Timestamp: 20261028T223911Z

617f469113cadb8c998c3dcc047596b5ac457694d89589828f71f92d2836bbb0  scenario_quality.py.pre-c2.20261028T223911Z
584c5ff02eacbd94ad3a39c0f4e0d873dc4e36afcc51bf54fb4ff3107aa123b8  scenario_reasoner.py.pre-c2.20261028T223911Z
fd00780ee602945bc22fccdd49d3551882a2101f0f943add1566d99abe10b1ee  scenario_recommendation.py.pre-c2.20261028T223911Z

Side-car: pre-c2.20261028T223911Z.sha256 (verifies against C1 baseline)
```

### 2.3 Post-deploy (branch tip `eebbaa6`)

```
7edce8c9cc40e2aad1cdb9f8b8a82d6ace7f542a93240a940e95d5f3816f88af  scenario_recommendation.py
718855ed6848b7ab816169d3d00232c15043a4f2720a3523b9b690102f821522  scenario_quality.py
a9af10b95e8e9e4bc06406ba494667a065f8c9b993c3106cefdb80e473fbffab  scenario_reasoner.py
```

All three deployed hashes match the branch tip exactly.

## 3. Deployment steps performed

1. **Backup** — three files copied to `_backups/` with `.pre-c2.<TS>` suffix and a sha256 sidecar.  Verified sha256sum matches C1 baseline.
2. **Stage** — three worktree files copied next to targets as `*.c2.new`.  `diff -q` confirmed byte-identical to branch source.
3. **Concurrency check**:
   * no running Python process imports `scenario_quality`/`scenario_recommendation`/`scenario_reasoner` (only the long-running `observer_webserver.py` which caches modules in-process; see §4);
   * last sweep write to `scenarios_shadow.jsonl` was `2026-10-28 16:51:05 UTC` (~5h50m before deploy);
   * next scenario sweep timer fires `2026-10-29T07:00:00Z` (~8h after deploy, UK session open).
4. **Atomic swap** — three `mv` renames chained in a single shell line.  Same-filesystem rename ⇒ each rename is atomic; the chain prevents partial-set observation by any import that begins after the first rename completes.
5. **Post-swap hash verification** — all three deployed sha256sums match the branch tip.
6. **Smoke test** — fresh Python interpreter imports the deployed modules directly from `/mnt/.../live_obs/agent/`; four canonical fixtures all pass (VALID structured BUY, hard contradiction → INVALID, soft drift → CAUTION, CAUTION pass-through → BUY/CONDITIONAL).  Documented in `CORRECTION2_FINAL_REGRESSION_RESULTS.md` §4.

## 4. What was not restarted and why

The long-running `observer_webserver.py` dashboard process (PID 770269, started 2026-10-23) imports `scenario_recommendation` dynamically but caches the module in its interpreter `sys.modules`.  **It was not restarted.**  Reasons:

* The brief explicitly instructs *"Do not introduce an unnecessary service restart"* and *"Do not modify unrelated services"*.
* The dashboard is **read-only**; it computes recommendations for display only.  No shadow-journal row, no broker order, no notification is derived from the dashboard's cached module copy.
* The sweep service and the one-shot CLI both run fresh Python processes per invocation; they load the new modules on next tick (07:00 UTC tomorrow).
* The dashboard will pick up the new modules on next operator-initiated restart.

If the dashboard's displayed recommendation must align with the sweep's written recommendation before next restart, the operator may issue `sudo systemctl restart observer_webserver.service` (equivalent) at a quiet moment; this is **not** required for correctness of the shadow journal.

## 5. Services inventory confirmed untouched

* `live-market-observer.service` — primary observer; no changes.
* `live-market-observer-shadow.service` — deterministic shadow; no changes.
* `live-market-observer-scenario-shadow.service` — Scenario V2 shadow sweep; **imports the deployed modules on next tick**, no restart initiated.
* `live-market-observer-news-refresh.service` — news/macro feed; no changes.
* `live-market-observer-shadow-exec.service` — no changes.
* `live-scenario-notifier.service` — notifier; no changes.
* No cron entries modified.

## 6. Rollback instructions

If the next scheduled sweep (or any post-deploy inspection) shows an unexpected regression:

```bash
BAK=/mnt/volume_lon1_1778405456698/research/live_obs/agent/_backups
TS=20261028T223911Z
DST=/mnt/volume_lon1_1778405456698/research/live_obs/agent

# Verify backup hashes before restoring
sha256sum "$BAK"/*.pre-c2.$TS   # expect C1 baseline

# Restore all three (atomic chain)
cp -p "$BAK/scenario_recommendation.py.pre-c2.$TS" "$DST/scenario_recommendation.py.rollback.new" \
  && cp -p "$BAK/scenario_quality.py.pre-c2.$TS"         "$DST/scenario_quality.py.rollback.new" \
  && cp -p "$BAK/scenario_reasoner.py.pre-c2.$TS"        "$DST/scenario_reasoner.py.rollback.new" \
  && mv "$DST/scenario_recommendation.py.rollback.new"   "$DST/scenario_recommendation.py" \
  && mv "$DST/scenario_quality.py.rollback.new"          "$DST/scenario_quality.py" \
  && mv "$DST/scenario_reasoner.py.rollback.new"         "$DST/scenario_reasoner.py"

# Verify restored hashes
sha256sum "$DST"/scenario_recommendation.py "$DST"/scenario_quality.py "$DST"/scenario_reasoner.py
# expected: fd00780e... (recommendation), 617f4691... (quality), 584c5ff0... (reasoner)
```

No service restart required for rollback; the next sweep tick loads the restored files.

Do not roll back only one or two of the three files — the C2 changes to `scenario_recommendation.py` (consume `trade_proposal.target_price`) depend on the `scenario_quality.py` validator pair and the `scenario_reasoner.py` prompt rule 5e.  Rollback the full triplet or none.

## 7. Operational verification — status

**PENDING** per brief §10.  The scenario sweep timer next fires at `2026-10-29T07:00:00Z` (UK session open).  No shadow-journal row has yet been produced under the deployed Correction 2 modules.  The deployment is **structurally** verified (hash parity + smoke tests) and **behaviourally** verified against the 235-row historical cohort; **operational** verification (observing a live sweep write under the new modules) awaits the next scheduled fire.

### Watchlist (first live sweep)

| Metric | Expected direction |
|---|---|
| Service-level error in journal / stderr | 0 |
| `MISSING_STRUCTURED_PROPOSAL` WARN count | > 0, trending down over subsequent sweeps as prompt rule 5e takes effect |
| `STRUCTURED_NARRATIVE_PRICE_DRIFT` WARN count | low; any case ≫ 50 p that was previously silent is now surfaced |
| `STRUCTURED_VS_NARRATIVE_CONTRADICTION` HIGH count | 0 unless a genuine hard contradiction occurs |
| CONDITIONAL readiness count | ↑ vs C1 baseline |
| INCOMPLETE readiness count | ↓ vs C1 baseline |
| INVALID count | unchanged (no HIGH gate weakened) |

If `INVALID` or `MALFORMED_STRUCTURED_PRICE` / `PRICE_SCALE_MISMATCH` jump materially — investigate before concluding success, as these would indicate the AI learned to emit **invalid** structured prices that the narrative fallback previously masked.

## 8. Communication

Operator notification suggested after first clean sweep post-deploy:
> Correction 2 (structured trade_proposal → primary numeric contract; A/B/C narrative-vs-structured classification) deployed at 2026-10-28T22:39:46Z.  Shadow-only.  Backup `_backups/20261028T223911Z`.  Full validation report + replay CSV at autobot_reports → `scenario_v2_correction2_20261028/`.
