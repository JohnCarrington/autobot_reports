# EMA Pullback intrabar + market-execution integration — 2026-10-28

Integrates the 2026-10-28 execution repair with the operator-enabled intrabar execution posture. Preserves the live-feed wiring. Preserves the Method B exit policy. Preserves strategy primitives. Adds four correction axes against the 2026-10-28 20:10–20:12 UTC incident.

## Documents

| File | Purpose |
|---|---|
| `INTRABAR_REPAIR_COMPATIBILITY_AUDIT.md` | Three-way comparison (production /opt vs repair branch vs intrabar implementation) + compatibility matrix + merge resolution. |
| `EMA_PULLBACK_INTEGRATED_FIX.md` | Full post-integration lifecycle + §A–§E axes mapped + headline guarantees + preserved primitives. |
| `BROKER_STATE_VERIFICATION.md` | Service-written broker inventory evidence; fate of DIAAAAYRNEAPCBW + DIAAAAYRNFEB8BJ; operator pathway to classify the removal; audit trail cross-check. |
| `INTRABAR_MARKET_EXECUTION_TEST_RESULTS.md` | 369 passed / 0 failed; test → §7 mapping; headline-guarantee test citations; no-live-IG audit. |
| `SAFE_DEPLOYMENT_PLAN.md` | Backup / stop / deploy / regression / observation / live-enable procedure + fail-closed rollback. |

## Status at report time

- **Service:** `active (running)` since 2026-10-28 20:57:50 UTC on production code (operator interim).
- **Config:** `MECHANICAL_ENTRY_MODE=market_on_trigger`, `INTRABAR_ENABLED=true`, `LIVE_PRICE_FEED_ENABLED=true`.
- **Live feed:** polling bid/ask every ~2 s, periodic http_403 recovers.
- **Active setup:** `0DA7CB` BUY ARMED at 1.33359, forming_m5_ts=2026-10-28T20:55:00Z.
- **IG EMAPB working orders:** zero (service-written inventory at 20:57:53 UTC).
- **IG EMAPB positions:** none authored by this task.
- **Previous two deal IDs (DIAAAAYRNEAPCBW, DIAAAAYRNFEB8BJ):** NO LONGER OUTSTANDING. Exact fate requires operator-authorised `/history/activity` lookup.

## Branches

- Code: `fix/intrabar-market-execution-integration-20261028` on `JohnCarrington/ema_pullback` (NOT merged).
- Reports: `incident/ema-pb-intrabar-market-integration-20261028` on `JohnCarrington/autobot_reports` (NOT merged).

## Final summary

- Production intrabar execution IS functioning as intended (polling, armed setup, no stray submissions).
- The two previous GTC orders are NOT outstanding; the service-written inventory at service boot (20:57:53 UTC) found zero EMAPB-prefix working orders.
- The repair branch IS compatible with the intrabar implementation — three-way comparison shows one merge point (main.py), resolved cleanly in the integration branch.
- No execution defects remain in the integrated version against the 369-test suite.
- The integrated version IS safe for controlled IG DEMO deployment per `SAFE_DEPLOYMENT_PLAN.md`.
- **Deployment HALTED pending operator approval.**
