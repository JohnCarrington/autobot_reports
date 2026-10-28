# EMA Pullback market-execution repair — 2026-10-28

Standalone EMA Pullback service correction after the 2026-10-28 20:10–20:12 UTC incident. Two live GOOD_TILL_CANCELLED BUY STOP orders at IG DEMO (deal IDs `DIAAAAYRNEAPCBW` and `DIAAAAYRNFEB8BJ` at 1.33410) that the local ledger falsely marked `broker_vanished`.

## Documents

| File | Purpose |
|---|---|
| `ROOT_CAUSE_ANALYSIS.md` | Evidence from the production ledger + IG probe; primary cause (reconciler false-cancel) + secondary causes (legacy mode default, no fingerprint dedup, no boot refuse); 100p TP origin (Method B authorised exit policy, commit `0d94096`). |
| `CORRECTED_ARCHITECTURE.md` | Full lifecycle under corrected `market_on_trigger` mode; opportunity fingerprint; reconciler decision tree; boot-time cross-process safety; file layout. |
| `BROKER_RECONCILIATION.md` | ORDER_WAITING + UNRESOLVED branch semantics; state-preservation invariants; the `/confirms 404` question; historical scope of `broker_vanished` entries. |
| `REGRESSION_RESULTS.md` | 257 passed / 0 failed; mapping tests → correction axes; headline guarantee check (no `place_working_order` under corrected default); raw pytest output. |
| `DEPLOYMENT_PLAN.md` | Four-step operator-authorised procedure (A: cancel legacy orders; B: deploy code; C: observation smoke; D: enable live) + rollback. **This task does NOT execute any step.** |

## Status

- Service: `inactive (dead)` throughout the task.
- Two live orders at IG: NOT touched.
- Dev branch: `fix/market-execution-20261028` on the EMA Pullback repo (JohnCarrington/ema_pullback). HEAD commits: baseline sync, corrections, tests, replay.
- 257 passed / 0 failed on the full test suite.
- Reports: this package.
- Deployment: deferred to operator review.

## Replay evidence

See `/home/autobot/ema_pullback-wt/market-execution-20261028/reports/replay/replay_20261028_20_05_20_15.md` on the EMA Pullback branch for the pre-vs-post reconstruction of the two false cancels.
