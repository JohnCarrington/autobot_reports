# Scenario V2 — early-entry correction, deployment readiness

**Status:** DESIGN + IMPLEMENTATION + BACKTEST + REGRESSION TESTS
READY FOR OPERATOR REVIEW. **NOT DEPLOYED.** No production files
modified. No service restarts. No live/demo broker paths activated.

**Companion deliverables (same worktree):**

- `ENTRY_DELAY_ROOT_CAUSE.md`
- `EARLY_ENTRY_DESIGN.md`
- `ENTRY_METHOD_COMPARISON.md`
- `data/BACKTEST_RESULTS.csv` (65 rows, 13 scenarios × 5 mechanisms)
- `impl/early_entry.py` (candidate module, SHADOW_ONLY)
- `scripts/backtest_early_entry.py`
- `scripts/shadow_compare.py` (parallel-execution comparison harness)
- `tests/test_early_entry.py` (17 regression cases, all PASS)

---

## 1. What is NOT changing in production

- `/mnt/.../live_obs/agent/shadow_execution.py` — **UNTOUCHED** (sha
  `8648532d…`, the deployed timestamp-anchor fix).
- `/mnt/.../live_obs/shadow_exec/run_shadow_exec.py` — **UNTOUCHED**
  (sha `d791dfc4…`, the deployed per-scenario coverage patch).
- `/mnt/.../live_obs/shadow_exec/run_shadow_exec.sh` — **UNTOUCHED**
  (sha `38d2e96b…`).
- `scenario_reasoner.py`, `scenario_quality.py`,
  `scenario_recommendation.py` — **UNTOUCHED**.
- NMS, EMA_PB, BB_BOUNCE, briefings, trades-api — **UNTOUCHED**.
- All journal history, dedup state, closed-scenario records —
  **UNTOUCHED**.

## 2. What this correction proposes to change (NOT yet deployed)

**One new file** under the research tree:
`/mnt/.../live_obs/agent/early_entry.py`
(candidate copy lives in this branch at `impl/early_entry.py`).

The deployed sweeper does NOT import it. Activation would be a
separate operator decision to either:

- **Option X — parallel shadow comparison only** (no risk):
  add a small driver that invokes `early_entry.process_proposal`
  alongside the deployed executor on each sweep, writing to a
  separate `shadow_exec_early/` directory. Both executors run on
  the same scenarios; neither can submit broker orders.
- **Option Y — replace deployed quality logic** (medium risk):
  wrap the deployed executor's fill in the quality gate (effectively
  the "M1 + quality gate" variant). Requires a minimal
  shadow_execution.py edit to call the gate before OPEN. NOT
  recommended until Option X has accumulated 30-60 live fills.
- **Option Z — do nothing yet**: let the current coverage patch
  accumulate shadow data; revisit this correction once sample size
  warrants.

**This document authorises review, not deployment.** The operator
chooses X / Y / Z.

---

## 3. Backtest findings — the specific recommendation

From `ENTRY_METHOD_COMPARISON.md`, five entry mechanisms over 13
first-READY scenarios Oct 23 → Nov 3 2026:

| Mechanism | Fills | Win % | Net pips | PF | MaxDD |
|---|---|---|---|---|---|
| M1 — current deployed | 10 | 40.0 | **−55.0** | 0.65 | −96.6 |
| A — early directional | 7 | 0.0 | −41.4 | 0.00 | −35.0 |
| B — pullback | 3 | 0.0 | −33.0 | 0.00 | −30.2 |
| C — earlier breakout | 2 | 50.0 | +16.0 | 2.65 | −11.1 |
| **M1 + quality gate** | **4** | **50.0** | **+14.7** | **1.66** | **−28.5** |

**Primary recommendation:** adopt the opportunity-quality gate from
`EARLY_ENTRY_DESIGN.md` §3. Secondary: C + gate (same gate, intra-bar
touch); both are hypotheses pending larger sample.

**Explicit disrecommendation:** do NOT deploy A or B. V2's structural
stops are not compatible with early entries; both mechanisms lose
every trade on this sample.

## 4. Risk analysis for the three activation options

### Option X — Parallel shadow comparison (RECOMMENDED)

- Isolation: new executor module writes to `shadow_exec_early/` only.
  Deployed executor and its journals untouched.
- Risk: **effectively zero**. If the new module crashes, the deployed
  sweeper is unaffected. If the deployed sweeper is unaffected, the
  dashboard continues to report the production shadow state.
- Observability: both journals grow in parallel; the operator can
  diff them via `scripts/shadow_compare.py`.
- Rollback: `rm -rf shadow_exec_early/` and remove the one line that
  invokes `early_entry.process_proposal`. No side effects.

### Option Y — M1 + quality gate inline (lower confidence)

- Scope: minimal edit to `shadow_execution.py` adding a quality-gate
  check between "candles crossed entry" and "write OPEN row". Reject
  path writes a QUALITY_REJECTION proposal row and no position.
- Risk: directly changes the live shadow fill rate. Based on the
  backtest, ~60 % of M1 fills would be rejected; however the sample
  is n=10 fills and the operator should not trust that rejection rate
  on a different market regime.
- Mitigation: feature-flag with `SHADOW_QUALITY_GATE=0` default-off.
- Rollback: unset the env var; next sweep uses original behaviour.

### Option Z — No change yet (status quo)

- Zero risk; zero signal. The current deployed configuration
  continues to accumulate ~1 shadow fill per few trading days per
  scenario. Reaching 60–100 fills (which the earlier
  `RECOMMENDATIONS.md` requested) takes months at the current cadence.
- The brief has already rejected this option explicitly.

## 5. Regression tests

All 17 regression cases pass against the proposed
`impl/early_entry.py`:

```
Ran 17 tests in 0.011s — OK
```

Groups:

- **Opportunity-quality gate** — 5 cases (geometry / net reward /
  net R:R / exhaustion / ok-passes).
- **Mechanism A** — 1 case (fires at first bar close).
- **Mechanism B** — 2 cases (pullback-then-direction;
  pre-entry stop abandonment).
- **Mechanism C** — 1 case (intra-bar touch fills at trigger).
- **Scenario lifecycle gates** — 3 cases (INVALIDATED skipped;
  publication != VALID skipped; NMS conflict skipped).
- **Per-scenario dedup** — 1 case (second mode on same scenario is
  blocked by per-scenario open/closed slot).
- **Retrospective-fill cap** — 1 case (default 2 h cap still
  bounds).
- **Feature flag OFF** — 1 case (mode="OFF" is a no-op).
- **SHADOW_ONLY invariant** — 2 cases (no broker imports;
  separate shadow dir from deployed).

Backtest harness ran end-to-end producing a 65-row CSV. Shadow-
comparison harness ran end-to-end against sandbox dirs (zero
production writes).

## 6. Known limitations

1. **Sample size.** n = 13 first-READY scenarios is too small for
   strong conclusions. All comparative P&L figures should be
   read as hypothesis-grade. The operator should NOT ratify
   Option Y on this evidence alone — Option X first builds the
   out-of-sample.
2. **Spread model.** No contemporaneous bid/ask for Oct 23 → Nov 3
   2026. Backtest uses a session-aware model (0.9 / 1.4 / 2.0 pips
   round-trip). News spikes to 5-10 pips are not modelled.
3. **Historical shadow-compare replay.** The shadow-compare harness,
   when driven by historical data, gets `readiness != READY` for
   many scenarios because `scenario_recommendation.build_trade_recommendation`
   evaluates market-data freshness against wall-clock-now (not the
   historical scenario-gen time). This is a **replay-mode limitation
   only** — in live use both executors see the same FRESH snapshot.
   The backtest harness avoids this issue by invoking the fill
   mechanism directly without rebuilding the recommendation.
4. **No live-vs-shadow spread calibration.** Shadow fills are
   mid-close; true IG retail fills can differ by 0.5-3 p especially
   around news. Any eventual live-deploy decision requires an
   independent calibration study (not in scope).
5. **Mechanism A / B structural-stop mismatch.** The backtest
   established that A and B lose every tested trade because V2's
   stops are sized for a breakout-level entry. The design module
   SUPPORTS them (behind feature flags), but the deployment-
   readiness assessment does NOT recommend them.

## 7. Operator decision matrix

| Question | Threshold | If passed → | If failed → |
|---|---|---|---|
| Is the directional signal real? | 60-min MFE>MAE ≥ 55 % on fresh ≥30-fill sample | Pursue Option Y with gate | Pursue Option Z |
| Does the quality gate hold up out-of-sample? | 30-60 live fills after Option X deploy | Promote to Option Y | Hold at Option X |
| Does M1+gate's net PF remain ≥ 1.3 on 30+ fills? | PF 1.3+ | Operator may consider live promotion (SEPARATE investigation) | Stop; redesign gate thresholds |

## 8. If deployed — rollback procedure (not for Option Z)

### Option X rollback

```sh
# Remove the parallel executor's state and the invocation line.
rm -rf /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec_early/
# Revert the sweeper driver that added the parallel call. The
# patched run_shadow_exec.py (sha d791dfc4) is unchanged; a separate
# patch would have added the parallel call behind a flag — rolling
# that patch back requires the operator to install the pre-X baseline.
```

### Option Y rollback

```sh
# Env-var disable, no file edit:
sudo systemctl edit live-market-observer-shadow-exec.service
# Add: Environment=SHADOW_QUALITY_GATE=0
sudo systemctl daemon-reload
# Next 5-min timer firing picks up the disable.
```

## 9. Explicit non-changes (restated)

Even under Option Y, we DO NOT modify any of the following:

- V2's reasoner prompt (`scenario_reasoner.py`).
- V2's narrative parser (`scenario_recommendation.py` structured-vs-
  narrative logic).
- V2's publication gate (`scenario_quality.py`).
- V2's directional prediction, stops, targets.
- NMS directional authority.
- EMA Pullback, BB Bounce, briefings, trades-api, broker clients.

The ONLY mutable surface is "whether the shadow executor OPENs a
position with the AI's own proposed geometry". The quality gate
answers "no" when V2's own numbers say the trade is not worth taking.
It never answers "yes" to a trade V2 did not already authorise.

## 10. Deliverables index

- `ENTRY_DELAY_ROOT_CAUSE.md` — why the delay exists.
- `EARLY_ENTRY_DESIGN.md` — formal algorithm for A / B / C + gate.
- `ENTRY_METHOD_COMPARISON.md` — backtest headline + rankings +
  honest sample caveats.
- `data/BACKTEST_RESULTS.csv` — 65 rows (reproducible via
  `scripts/backtest_early_entry.py`).
- `impl/early_entry.py` — new module (candidate; not deployed).
- `scripts/backtest_early_entry.py` — backtest harness.
- `scripts/shadow_compare.py` — parallel-execution comparison
  harness (for post-Option-X verification).
- `tests/test_early_entry.py` — 17 regression tests, all PASS.
- `DEPLOYMENT_READINESS.md` — this file.
