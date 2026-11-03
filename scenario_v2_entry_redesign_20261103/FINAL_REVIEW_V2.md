# Scenario V2 — final review v2 (two-hour expiry removed, DEMO-only destination)

**Operator directive 2026-11-03 (final):**
1. **No shadow trading of any form.** DEMO is the only destination.
2. **No two-hour automatic trade close.** Once an order opens the
   broker's attached stop/target owns the exit. Pre-entry setup
   expiry is OK (no order placed); POST-entry time-based close is
   forbidden.

This document is additive to `FINAL_REVIEW.md` and supersedes any
expiry claim in the earlier docs.

---

## 1. Time-based-exit audit (brief §A1)

| File | Finding | Status |
|---|---|---|
| `impl/v2_early_setup.py` | DEFAULT_EXPIRY_BARS constant REMOVED; `expiry_bars` field REMOVED from `SetupOutcome`; `derive()` signature no longer accepts it. Only `lookback_seconds` remains (PRE-entry cap). | **CLEAN** |
| `impl/v2_demo_executor.py.template` | No `expiry_bars` reference. No `close_position` / `cancel` / `exit` call. V2 does NOT own any exit path. | **CLEAN** |
| `patches/0001-reasoner-prompt-setup-types.patch` | Reasoner prompt extension only. No exit logic. | **CLEAN** |
| `patches/0002-parser-validator-setup-types.patch` | Parser/validator updates only. No exit logic. | **CLEAN** |
| `patches/0003-ownership-mode-codes.patch` | Mode-code registration only. No exit logic. | **CLEAN** |
| `scripts/backtest_coherent_setups.py` | **BACKTEST ONLY.** No production path. Previously forced close at bar 24; now modified to monitor indefinitely until stop or target OR classify as UNRESOLVED. | **UPDATED** |

**Zero production paths close a V2 position based on elapsed time.**
Once the DEMO executor dispatches an order via `autobot.execute_trade`,
the broker's attached stop + target distance govern the exit, and
the central `close_sb_now.reconcile_open_positions` loop handles
stop/target execution without V2 involvement.

### 1.1 Pre-entry setup expiry (allowed by operator)

The derivation module caps how far back it looks for a trigger via
`DEFAULT_LOOKBACK_SECONDS = 7200` (2 h). This is a PRE-ENTRY cap:
if the sweeper fires a scenario whose gen time is > 2 h ago and no
trigger bar has materialised in the intervening bars, no order is
placed. This is distinct from and inconsistent with closing an
already-open position — no order has been placed.

---

## 2. Dedup + non-interference audit (brief §A2)

Scenario V2 DEMO orders cannot:

- **Duplicate themselves.** `trade_executor.execute_trade`'s central
  `EPIC_STATE` dedup is keyed by `epic|mode`. V2 uses
  `SCENARIO_V2_L`/`SCENARIO_V2_S`. Once V2 opens a BUY on GBP/USD,
  `EPIC_STATE[CS.D.GBPUSD.TODAY.IP|SCENARIO_V2_L].pending_open = True`
  and subsequent V2 fires are blocked until the state clears. The
  5-min sweep cadence vs synchronous execute_trade return means
  state is updated before any next-sweep attempt.
- **Interfere with EMA_PB.** EMA_PB mode codes are
  `GBPUSD_EMA_PULLBACK_L/S` — distinct `EPIC_STATE` keys.
- **Interfere with BB_BOUNCE.** Mode codes `GBPUSD_BB_BOUNCE_L/S` —
  distinct keys.
- **Interfere with Briefings or any other strategy.** All strategies
  carry distinct mode codes in `ownership_identity._MODE_CODES`.
- **Submit after a timeout retry.** V2's `_submit_demo_order` has
  zero retry logic; it calls the dispatcher once and reports the
  outcome. Any retry policy is owned by `trade_executor` centrally.

**Positions already owned by other strategies are invisible to V2.**
V2's dispatcher call only knows about its own mode code; it cannot
read or close another strategy's position.

Grep audit confirms zero `close_sb_now`, `close_position`,
`cancel_order` references in V2's modules.

---

## 3. Re-run backtest without post-entry expiry (brief §B)

Backtest now monitors bars indefinitely until stop OR target is
hit, matching the real IG broker lifecycle. UNRESOLVED is the new
status for trades that haven't yet closed within the available
candle sample.

Full run: `scripts/backtest_coherent_setups.py` →
`data/BACKTEST_RESULTS.csv` (104 rows unchanged).

### 3.1 Headline results — ALL n = 13

| Mech | Fills | Targets | Stops | Unresolved | Win % | Gross | **Net** | AvgW | AvgL | MDD | **PF** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 baseline | 10 | 4 | 6 | 0 | 40.0 | −44.5 | **−55.0** | +20.3 | −21.0 | −105.3 | 0.65 |
| **A momentum** | **13** | 4 | 9 | **0** | 30.8 | +112.7 | **+95.7** | **+47.5** | **−8.6** | **−54.6** | **2.46** |
| B pullback | 7 | 0 | 7 | 0 | 0.0 | −84.4 | −92.2 | — | −12.1 | −84.4 | 0.00 |
| C structural | 4 | 0 | 4 | 0 | 0.0 | −42.2 | −45.8 | — | −10.6 | −42.2 | 0.00 |

**No UNRESOLVED trades** — every A/B/C/M1 fill eventually hit a
stop or target within the available sample. The sample is complete
for the lifecycle test.

### 3.2 DEV / VAL split

**DEV (n = 7):**

| Mech | Targets | Stops | Win % | Net | PF |
|---|---|---|---|---|---|
| M1 | 2 | 5 | 28.6 | −56.9 | 0.50 |
| **A** | **1** | **6** | 14.3 | **−11.4** | 0.95 |
| B | 0 | 5 | 0.0 | −71.6 | 0.00 |
| C | 0 | 3 | 0.0 | −31.7 | 0.00 |

**VAL (n = 6):**

| Mech | Targets | Stops | Win % | Net | PF |
|---|---|---|---|---|---|
| M1 | 2 | 1 | 66.7 | +1.9 | 1.19 |
| **A** | **3** | **3** | 50.0 | **+107.1** | **6.14** |
| B | 0 | 2 | 0.0 | −20.6 | 0.00 |
| C | 0 | 1 | 0.0 | −14.1 | 0.00 |

### 3.3 Interpretation vs the earlier (expiry) summary

- **A improves without expiry** (+95.7 net vs +59.9 under 2 h cap).
  The reason: 3 previously-expired-at-small-gain trades eventually
  ran to the full structural target under the real broker
  lifecycle, converting +12 p expiry closes into +42–60 p
  target hits.
- **A still takes more stops** without expiry (9 vs 5 before). The
  3 trades that previously expired-small-negative at bar 24 ran to
  stop later — they weren't being "saved" by the expiry; the
  expiry was prematurely closing them.
- **Classical win rate dropped** from 53.8 % (profitable-at-exit,
  including expired-positive) to 30.8 % (targets / (targets +
  stops)). The 30.8 % is the honest broker-lifecycle rate.
- **PF 2.46 on 13 fills is still too small for a profitability
  claim.** n = 13 is not statistically sufficient.
- **DEV is net-negative, VAL is net-positive.** The strong VAL
  (+107 net on 6 fills, 3/3 wins vs stops) is pleasing but
  dominated by a few directional calls that happened to work; one
  stop-out away from flipping neutral. Treat as hypothesis-grade.
- **B and C are strictly worse without expiry.** Both relied on the
  expiry mechanic to lock small gains. Without it they go to stop.
  No deployment path for B or C.

### 3.4 Max drawdown considerations

Mechanism A's MDD rose from −39.7 (with expiry) to −54.6 (without
expiry). The reason: without expiry, consecutive stop-outs are
not interrupted by "scratch close" expiry exits. The drawdown is
realistic for the broker lifecycle; the operator should expect
~55 p peak-to-trough drawdowns during data-accumulation DEMO.

---

## 4. Verified: no duplicate orders after timeout; no cross-strategy interference

See §2 above. Explicitly:

- V2's DEMO executor is a thin wrapper over `autobot.execute_trade`.
- `execute_trade` dedup via `EPIC_STATE[epic|mode]` is the single
  source of truth. V2 adds no state.
- Mode codes `SCENARIO_V2_L` / `SCENARIO_V2_S` are distinct from
  every other mode in `ownership_identity._MODE_CODES`.
- No `close_sb_now` / `cancel` / position-close call in V2's
  modules.
- No retry logic in V2's dispatcher.

---

## 5. Preserved: new early momentum entry + its matched structural stop

The entry mechanism (Mechanism A) and the stop placement (impulse
bar's own extreme − 1 p buffer) are UNCHANGED. Both are retained
exactly as designed.

---

## 6. Deployment readiness summary

- **Deliverables ready.** No files installed. No orders placed.
- **Production SHAs unchanged.** `shadow_execution.py` sha
  `8648532d…`; `run_shadow_exec.py` sha `d791dfc4…`;
  `run_shadow_exec.sh` sha `38d2e96b…`; `ownership_identity.py`
  sha `882ccddd…`.
- **20 regression tests pass** (ran after module cleanup).
- **No shadow trading.** No DRY_RUN flag. No parallel comparison
  harness. The only switch is `V2_SV2_DEMO_ENABLED` (0/1).
- **No post-entry time-based close.** Audited across all modules
  and patches.
- **Mechanism A** (momentum impulse + mechanical stop + V2's
  structural target). Backtest n = 13: 4 targets + 9 stops, 30.8 %
  win, net +95.7 pips, PF 2.46 — **not sufficient to establish
  profitability**, hypothesis-grade only.

Deployment steps unchanged from `DEPLOYMENT_READINESS.md` §3:
backup → install → patch → write wrapper (ENABLED=0) → preflight
connectivity script → observe DISABLED journal rows → operator
approval → flip ENABLED=1 → submit REAL DEMO orders.
