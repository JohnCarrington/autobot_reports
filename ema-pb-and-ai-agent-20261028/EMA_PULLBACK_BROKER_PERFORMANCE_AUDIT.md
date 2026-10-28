# EMA Pullback Broker Performance Audit — 2026-10-28

**Window:** 2026-10-20 00:00 UTC → 2026-10-28 17:49 UTC
**Account:** IG DEMO SPREADBET `Z3G4CJ` (same account used by every AutoBot-family service)
**Data provenance:** IG REST `GET /workingorders`, `/positions`, `/history/activity?detailed=true`, `/history/transactions`. All reads only — zero broker mutations by this audit.

**Raw evidence:** `data/reconstructed_trades.csv` (101 rows, one per submission) + `data/emapb_summary.json` (aggregates).
**Companion:** [EMA_PULLBACK_EXECUTION_CORRECTION.md](./EMA_PULLBACK_EXECUTION_CORRECTION.md) explains why these numbers look the way they do.

---

## Headline

- **94 broker submissions** in the window. **33 filled → position opened → closed**; 20 operator-deleted via IG web UI; 37 broker-rejected before acceptance; 4 locally rejected (schema validation) before reaching IG. 0 orphans.
- **Total broker-confirmed P&L: +272.25 pips / +£544.50** on the 33 closed trades.
- **Profit factor 3.195, win rate 66.7% (22W / 11L).**
- **But the headline is misleading** — see §4. 23 of 33 trades closed via a "manual bulk close" operator action, not via the strategy's own SL/TP:
  - 2026-10-28 **07:29:50 UTC**: 21 EMAPB-prefixed positions bulk-closed in one burst.
  - 2026-10-27 **17:15:21 UTC**: 2 EMAPB-prefixed positions bulk-closed.

  **Only 10 trades reached a broker stop; 0 reached a broker take-profit. 23 of 33 "wins/losses" are operator-close events, not strategy exits.**
- **The local EMA Pullback ledger disagrees with IG on 33 of 33 completed trades.** Every fill is recorded as `CANCELLED/broker_vanished` in `/opt/ema_pullback/state/setup_history.jsonl`. The strategy's own reports therefore show NO fills and NO P&L for this window; the +£544.50 total above is only visible by querying IG directly.

## 1. Submission population

| category | n | notes |
|---|---|---|
| Pre-submission `NMS_V3_BLOCKED` | 7 | Service refused to arm (NMS directional veto); no deal_reference reached IG. |
| Local rejected (schema validation) | 4 | `http_400: validation.null-not-allowed.request.type` — the "`type` vs `orderType`" field-name bug fixed in commit `ed16ee0`. These never reached IG. |
| Broker rejected | 37 | Of which **32 were `INSUFFICIENT_FUNDS`** on the DEMO account, 5 were `ATTACHED_ORDER_LEVEL_ERROR`. |
| Cancelled working order | 20 | All 20 cancellations originated from the IG WEB UI channel — i.e. the operator manually deleted them. **ZERO cancels originated from the EMA Pullback service's own `cancel_working_order` call path.** |
| Filled then closed | 33 | The source of the +£544.50 broker P&L. |
| Filled still open | 0 | — |
| Submission total | 101 | 94 broker submissions + 7 pre-submission blocks. |

## 2. Pending-order lifetime

For the 33 submissions that filled on broker:

| statistic | seconds | human |
|---|---|---|
| min pending | 14 | 14 s (dealId `DIAAAAYQ5RKLRBT`, `EMAPB-S-1793117416-6DD802`, opened 2026-10-27T16:10:16, filled 2026-10-27T16:10:30) |
| median pending | 4,791 | ~1 h 20 min |
| mean pending | 4,827 | ~1 h 20 min |
| max pending | 11,504 | ~3 h 11 min (dealId `DIAAAAYQ6DAMRAS`, `EMAPB-S-1793137821-3B35D0`, opened 2026-10-27T21:50:21 UTC, filled 2026-10-28T01:02:05 UTC) |

An 8-order cluster submitted between 2026-10-27 22:00–22:45 UTC **all filled in a 2-minute window at 2026-10-28 01:00–01:02 UTC** — i.e. a single price touch at ~01:00 swept through eight working orders that had been sitting on IG for roughly 3 hours. This is the "orders executing after their triggering context has changed" shape the user raised at the start of the investigation.

20 cancellations happened via IG web UI with lifetimes ranging **320 s to 18,949 s** (5+ hours); the operator's cleanup bursts cluster at **15:26 / 16:55 / 20:07 / 21:17 / 11:40 UTC**. During these bursts the operator deleted 2–8 orders in a few seconds.

## 3. Daily P&L (broker-confirmed, 2026-10-27 and 2026-10-28)

The window has no fills before 2026-10-27 (the service was off / rejected earlier submissions).

| date | n | pnl_pips | pnl_gbp |
|---|---|---|---|
| 2026-10-27 | 9 | **−86.4** | −£172.80 |
| 2026-10-28 | 24 | **+358.65** | +£717.30 |
| **total** | **33** | **+272.25** | **+£544.50** |

## 4. Caveat: 23 of 33 closes are operator interventions

Classification of the 33 closed trades by `close_reason` (derived from `/history/activity` action chains + `/history/transactions`):

| close reason | n | contribution |
|---|---|---|
| `broker_stop` (reached the attached stop) | 10 | all 10 are small (10–12 p) losses |
| `broker_tp` (reached the attached take-profit) | **0** | no trade reached its 100-p TP within the window |
| `other` (manual / bulk / forced close) | **23** | includes the 21-trade bulk close at 2026-10-28 07:29:50 UTC and the 2-trade close at 2026-10-27 17:15:21 UTC |

The operator-driven closes are the **source of nearly all the win pips** — closing a batch of positions at 07:29:50 on 2026-10-28 captured substantial unrealised P&L on positions that filled earlier the same day. Had those positions continued to run, several would have hit the 12-p broker stop; others would have continued to drift. Without a counterfactual, the audit cannot say which closes were "lucky" and which represent genuine strategy edge — but it CAN say that **the strategy's own exit mechanism did not produce the +£544.50**.

Interpretation guidance:

- Treat the +272.25 p figure as "**broker-confirmed outcome including operator intervention**", not as "strategy performance".
- Treat the 10 broker-stop closes (−124 p) as "**the only trades the strategy fully managed end-to-end**" — pure strategy performance in this window is 0W / 10L / −124 p.
- The 20 operator cancellations ARE a kind of intervention too, but they are easier to classify: the operator saw a working order whose context had evaporated and manually deleted it. Each cancellation prevented one potential execution; the audit cannot know how many of those would have filled, won, or stopped out.

## 5. Local-ledger misclassification (the "33 broker_vanished" bug)

**All 33 broker-side fills are recorded locally as `CANCELLED` with `cancellation_reason = "broker_vanished"`** in `/opt/ema_pullback/state/setup_history.jsonl`. The ledger therefore shows:

| local ledger says | 94 broker submissions |
|---|---|
| REJECTED | 41 (37 broker-rejected + 4 schema-rejected) |
| ORDER_WAITING → CANCELLED | 53 (= 33 real fills + 20 real cancellations) |
| NMS_V3_BLOCKED | 7 |
| Any fill event | **0** |

The strategy's own reports — EOD CSV, journal, Grafana derivatives if any — therefore show **zero completed trades for the window**. Only an audit against IG's authoritative history reveals the +£544.50.

**Root cause (service.py:496, pre-fix):**

```python
if active.state == ORDER_WAITING:
    ...
    if wo_payload is None and pos_payload is None:
        # Neither working-order nor position: broker-side cancelled
        active.state = CANCELLED
        active.cancellation_reason = "broker_vanished"
```

The reconciler polls IG once per step (~every few seconds). When `STOP_ORDER_OPENED → POSITION_OPENED → STOP_ORDER_FILLED → POSITION_CLOSED` all completes between two polls (observed minimum 14 seconds end-to-end), neither the working order NOR the position is visible on the subsequent poll, and the reconciler assumes the broker cancelled it.

**Fix (committed on dev branch `feat/market-exec-mechanical-20261028`):** before falling through to `broker_vanished`, consult `/history/activity?detailed=true` for a completed lifecycle on the active `dealId`. If a `STOP_ORDER_FILLED → POSITION_OPENED → POSITION_CLOSED` chain is found, reconstruct the fill and close events locally via `mark_filled` + `mark_closed`. See the companion report §4.6.

**Historical ledger repair:** `data/reconstructed_trades.csv` carries the broker-authoritative outcome for all 101 submissions. The operator can backfill the local ledger from that CSV without replaying signals (one row per submission, keyed by `deal_reference`, with `broker_fill_ts`, `broker_fill_price`, `position_close_ts`, `close_price`, `pnl_pips`, `pnl_gbp`, `close_reason`, and the `local_vs_broker_divergence` tag).

## 6. Methodology

`data/build_recon.py` (stdlib only — no pandas) joins the three IG payloads and the local ledger:

- Start from `/history/activity`, filter to `WORKING_ORDER` and `POSITION` rows where `dealReference` starts with `EMAPB-`.
- Group by `dealId` (ledger's `deal_id`) or by `affectedDealId` on compound action chains.
- For each dealId, order action rows by timestamp and classify the terminal action:
  - `STOP_ORDER_FILLED → POSITION_OPENED → STOP_ORDER_FILLED → POSITION_CLOSED` → FILLED+CLOSED, extract fill + close level from the matched `/history/transactions` row (by `reference`).
  - `STOP_ORDER_OPENED → WORKING_ORDER_DELETED` (WEB channel) → CANCELLED by operator.
  - `STOP_ORDER_REJECTED` → REJECTED with the IG error code.
- Compute `pnl_pips = (close - open) × direction_sign` with GBPUSD-TODAY pip = 1 IG point; `pnl_gbp = pnl_pips × size` (every position was size 2, so £/pt = 2 × pips).
- Pre-submission `NMS_V3_BLOCKED` and locally-rejected schema errors are added as rows with blank fill/close fields.

Data-quality notes:

- IG `/history/activity` timestamps are naive; the audit treats them as UTC per IG's documented convention. All 33 fills' `openDateUtc` from `/history/transactions` matched the activity timestamp to the second, so this convention holds.
- Four of the 10 broker_stop closes have `exit_ig == stop_level` to the pip; the other 6 are 0.5–1.5 p slippage below the stop level (normal for a fast-market fill).
- Zero `broker_tp` closes to use as a reference for the 100-pip target behaviour — the window just does not contain a trade that ran to +100 pips.

## 7. Links

- Reconstructed per-trade CSV: `data/reconstructed_trades.csv`
- Aggregate stats JSON: `data/emapb_summary.json`
- Reconstruction script (reproducible, stdlib-only): `data/build_recon.py`
- Service correction & reconciliation fix: [EMA_PULLBACK_EXECUTION_CORRECTION.md](./EMA_PULLBACK_EXECUTION_CORRECTION.md)
- Underlying IG snapshot (zero-write): `/tmp/ig_audit_20261028/*.json` (not published to the public repo — contains account balance info)
