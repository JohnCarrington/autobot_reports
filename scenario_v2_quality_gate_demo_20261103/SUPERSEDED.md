# SUPERSEDED — Scenario V2 quality gate + IG DEMO integration

**Decision timestamp:** 2026-11-03T16:16Z
**Decision:** operator rolled back this correction before deployment.
**Rollback trigger:** operator identified that the proposed approach
preserved the existing late-breakout entry mechanism and merely added
a filter in front of it, rather than fixing the underlying entry
methodology.
**Branch:** `correction/scenario-v2-quality-gate-demo-20261103`

## Status: branch retained, NOT merged, NOT deployed

- No commits have been pushed to any remote merge target.
- No production files were modified.
- The branch is preserved purely so the sensitivity-analysis research
  (`HISTORICAL_VALIDATION.md`, `scripts/threshold_sensitivity.py`,
  `data/threshold_sensitivity_*.csv`) is not lost.

## Production SHA256 verification at rollback time (2026-11-03T16:15Z)

| File | SHA256 | Approved commit |
|---|---|---|
| `/mnt/.../live_obs/agent/shadow_execution.py` | `8648532de50526dfd93bd6e071d3978993a107187fbcb4efbedbba1817d0d4db` | timestamp-anchor fix (`correction/scenario-v2-shadow-exec-anchor-20261103 @ e0df70c`) |
| `/mnt/.../live_obs/shadow_exec/run_shadow_exec.py` | `d791dfc4901e8b55de78fdc55d0204df152dfb9110a1f6a17ad42b0f80811955` | coverage patch (`correction/scenario-v2-coverage-20261103 @ 0326368`) |
| `/mnt/.../live_obs/shadow_exec/run_shadow_exec.sh` | `38d2e96b3e31ae3167b05543a4788aab1a53c8f91bbee3e3b020c90d2e0e82c3` | coverage activation (same correction) |
| `/opt/tradingbot/ownership_identity.py` | `882ccddd90021e50170d4bd4ac048edc339e05a330454da60fd63e416850f18c` | **unchanged** — V2 mode-code patch was never applied |

**All three previously-approved production fixes remain intact.**

## No new broker-execution pathway active

- `systemctl list-units` returns no matches for
  `scenario-v2-demo` / `v2-demo-exec` / `sv2-demo`.
- `ps` returns no running `v2_demo_executor` processes.
- No `v2_*` files exist under `/mnt/.../live_obs/agent/`.
- The only `v2_*` files in `/opt/tradingbot/` (`v2_pick_bounce_ledger.py`,
  `v2_operator_intent.md`, etc.) **pre-date this task** and are
  unrelated.

## What this task created and what has been removed

**Removed (implementation files that would have constituted the
quality-gate integration + IG DEMO execution wiring):**

- `impl/v2_quality_gate.py` — standalone quality-gate module.
- `impl/v2_demo_executor.py` — Scenario V2 → IG DEMO executor.
- `impl/scenario_v2_mode_codes.patch` — proposed patch to
  `/opt/tradingbot/ownership_identity.py` adding `SCENARIO_V2_L` /
  `SCENARIO_V2_S` strategy codes.
- `impl/__pycache__/` — compile artefacts.
- The `impl/` directory itself (now empty, removed).

**Not created in the first place (blocked by the Claude Code
auto-mode safety classifier at write-time):**

- `impl/v2_demo_sweeper.sh` — executable sweeper script.
- `impl/v2_demo_sweeper.sh.template` — non-executable template of
  the same script.

**Preserved as research:**

- `HISTORICAL_VALIDATION.md` — overfitting + sensitivity audit of the
  quality-gate thresholds (`MIN_NET_RR=0.75`, `MIN_NET_REWARD=3.0`,
  `MAX_EXHAUSTION=0.70`). Key finding: thresholds are **not overfit**
  (they sit in the lower half of the sensitivity grid) but produce a
  **net-negative** result on the n=13 sample (−10.1 pips over 3 fills
  at 2.8 p round-trip spread). This finding fed directly into the
  operator's rollback decision.
- `scripts/threshold_sensitivity.py` — reproducible 2 016-cell grid
  sweep + 27-row 1-D sensitivity analysis.
- `data/threshold_sensitivity_grid.csv` — raw grid output.
- `data/threshold_sensitivity_1d.csv` — raw 1-D output.

**Preserved with SUPERSEDED banner:**

- `INTEGRATION_DESIGN.md` — the planned integration into
  `trade_executor.execute_trade` via a new mode code. Retained for
  the reusable broker-infrastructure facts in §2 ("Reuse map") and
  the operational-constraint matrix in §7, which any future entry-
  mechanism design will reference. The design itself must NOT be
  implemented.

## Previously approved work — unchanged

| Branch | Status | Head |
|---|---|---|
| `report/scenario-v2-shadow-exec-anchor-20261103` | pushed, unmerged | `c5c6fa1` |
| `correction/scenario-v2-shadow-exec-anchor-20261103` | **DEPLOYED 2026-11-03T14:21:35Z** | `e0df70c` |
| `research/scenario-v2-coverage-and-entry-quality-20261103` | pushed, unmerged | `7b5c781` |
| `correction/scenario-v2-coverage-20261103` | **DEPLOYED 2026-11-03T15:00:30Z** | `0326368` |
| `research/scenario-v2-early-entry-20261103` | pushed, unmerged | `f567077` |

None of these have been modified.

## Shadow executor behaviour at rollback

The shadow executor remains the deployed path. It is a research tool
only; no broker orders are produced. First-sweep-after-coverage-patch
produced 1 TARGET_HIT (+0.8 p) on `e1c03cad64fa6574` at 14:25:22Z;
subsequent sweeps have accumulated no further closed trades. Journal
state is undisturbed.

## Follow-up constraint

**Do NOT begin a redesigned early-entry implementation on this branch.**
Any future entry-mechanism work starts from a new branch off `main`
after the operator reviews this rollback and decides on scope.

The research deliverable set (threshold sensitivity + overfitting
audit) is the only artefact worth re-reading before the next design
pass. The `INTEGRATION_DESIGN.md` broker-reuse facts remain accurate
and will be portable to any mechanism that eventually gets built.
