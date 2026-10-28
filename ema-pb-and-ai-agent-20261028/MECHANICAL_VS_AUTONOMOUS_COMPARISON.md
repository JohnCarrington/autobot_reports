# Mechanical EMA Pullback vs Autonomous Claude Agent — Comparison + Executive Summary

**Window:** overlapping period where both systems were observable, 2026-10-26 → 2026-10-28 (3 UK trading days; EMA PB fills are all on 2026-10-27 and 2026-10-28).
**Companion reports:**
- [EMA_PULLBACK_EXECUTION_CORRECTION.md](./EMA_PULLBACK_EXECUTION_CORRECTION.md) — strategy correction (dev branch).
- [EMA_PULLBACK_BROKER_PERFORMANCE_AUDIT.md](./EMA_PULLBACK_BROKER_PERFORMANCE_AUDIT.md) — broker-confirmed performance.
- [CLAUDE_AUTONOMOUS_AGENT_AUDIT.md](./CLAUDE_AUTONOMOUS_AGENT_AUDIT.md) — AI agent audit.

---

## Executive summary — the user's seven questions

**1. Is the mechanical EMA Pullback executing the intended strategy?**

**No, not on the execution side.** Admission and cancellation rules match the spec. Entry delivery does not: the service submits a `GOOD_TILL_CANCELLED` STOP working order at arming moment, so the broker holds the order until price revisits the frozen entry level — median wait 1 h 20 min, max 3 h 11 min observed. The user asked for immediate MARKET on trigger. A corrected dev branch (`feat/market-exec-mechanical-20261028`) with 260 tests passing is published for operator review; it adds a new `ARMED` state, a `MECHANICAL_ENTRY_MODE=market_on_trigger` flag, and a `LiveIGClient.open_market_entry()` method. The legacy path remains the default — zero behaviour change until the operator opts in.

**2. What did the mechanical system actually earn or lose?**

Broker-confirmed over 2026-10-27 to 2026-10-28: **+272.25 pips / +£544.50** across 33 closed trades. Caveats:
- **The local ledger does NOT show these fills.** All 33 are recorded as `CANCELLED/broker_vanished` in `/opt/ema_pullback/state/setup_history.jsonl` — a 100 % reconciliation defect. The strategy's own reports show zero completed trades. The +£544.50 is only visible by querying IG directly.
- **Only 10 of the 33 closes were strategy exits** (broker stop; all small losses). **23 of 33 were operator manual-close events**, in two bursts: 2026-10-28 07:29:50 UTC closed 21 EMAPB positions in one action, and 2026-10-27 17:15:21 UTC closed 2 more. Zero trades reached a broker take-profit.
- Rejections: 37 broker-rejected (mostly `INSUFFICIENT_FUNDS` on the DEMO account), 4 locally rejected (schema `type` vs `orderType` validation bug fixed in commit `ed16ee0`).
- Daily split: 2026-10-27 = −86.4 p (9 closes), 2026-10-28 = +358.65 p (24 closes).

Treat +272.25 p as "broker outcome including operator intervention", NOT as "strategy performance". Strategy-only performance in the window is 0W / 10L / **−124 p** (the broker-stop closes).

**3. Is the Claude agent genuinely autonomous?**

**Yes, mostly.** Direction, setup type, entry price, invalidation level, hold duration, position management, and the WAIT choice are all free. The AI's rationale is captured in a `primary_thesis` string per decision and the full output in `raw_json`. Two hard limits apply: the broker minimum stop is 12 pips (clamp — not a veto), and the take-profit is fixed at 100 pips (non-overridable). The post-decision envelope can veto on 12 operational grounds (market closed, spread wide, daily loss limit, etc.) and NMS v3 can veto a direction. **None of these vetoes fired in the audit window.**

**4. What trades has Claude independently identified?**

Three completed trades over the audit window; all losses, totaling **−29.1 pips / −£29.10**:

- 2026-10-26 17:20 UTC: BUY, broker_stop, −12.0 p — "breakout above 13350 round, pullback 0.1 p, target S1 cluster".
- 2026-10-27 09:35 UTC: SELL, **ai_close**, −7.8 p (−52% toward stop) — closed early with explicit "thesis reclaimed, pending Durable Goods release" rationale.
- 2026-10-27 12:55 UTC: BUY, **ai_close**, −9.3 p (−72% toward stop) — closed early with explicit "H1 EMA fan firmly bearish, broke prev-day-low support, thesis materially weakened" rationale.

The two `ai_close` exits display **loss-cutting on thesis invalidation**, not stop-only exits. That is the kind of discretionary skill Claude *could* add — but n = 2 does not establish anything about expectancy. Trade sample size is too small to make quantitative claims.

**5. Has NMS prevented Claude from trading?**

**No. Zero NMS vetoes in the audit window.** The NMS v3 state was included informationally in every snapshot Claude saw, and the gate was armed to reject a conflicting trade post-decision — but Claude did not propose a direction NMS would block in this window.

**6. Which approach has performed better so far?**

**Neither is a win.** Looking at the overlap window (2026-10-27 and 2026-10-28) where both operated:

| metric | mechanical EMA PB (broker-confirmed) | Claude autonomous |
|---|---|---|
| trades taken (window-overlap) | 33 | 2 |
| gross pnl pips (window-overlap) | +272.25 | −17.1 |
| gross pnl £ | +£544.50 | −£17.10 |
| strategy-exit-only pnl (window-overlap) | −124 p (10 broker-stop closes) | −12 p (1 broker-stop close) + −17.1 p (2 ai-close) = −29.1 p (3 trades) |
| win rate (strategy exits only) | 0 % | 0 % |
| trades/day | ~16/day over 2 days | ~1/day over 4 days |
| mean hold | ~10–30 min (bulk-close-skewed) | 75 min |
| sample size | 33 closes but 23 operator-induced | 3 total |

Caveats stacked on caveats:
- **Mechanical "profit"** is 90%+ attributable to operator bulk-closes, not strategy execution.
- **Mechanical "trades"** are 23 fills that would otherwise have run to a broker SL/TP that the window did not provide — we do not know the counterfactual.
- **Claude's sample is 3 trades.** Any statement about win rate / expectancy requires at least 30+ trades to carry evidential weight.
- Both operate on the same account and the same instrument; spread + slippage assumptions are comparable (£0.5–1 per side). The mechanical service's broker SL distance is 12 p; Claude's broker-min floor is also 12 p; so stops are comparable. Mechanical TP is 100 p (never reached); Claude's TP is fixed at 100 p (never reached, including on the 2 ai_close trades which were closed early).

**Neither system can be shown to outperform in this window.** The mechanical system's broker tape is distorted by operator intervention; Claude's is sample-starved. **The audit does NOT support a performance verdict either way.**

**7. What additional evidence is required before considering an AI-assisted mechanical strategy?**

The user explicitly asked for research-only treatment of this question — no code, no merging. On the evidence here:

- **The mechanical system would benefit from strategy-aware exits.** 0 of 33 broker take-profits in two days suggests the fixed 100-p TP is far from where the market pays out this instrument. The AI did explicitly invalidate the thesis twice before the broker stop — a signal the mechanical path currently lacks.
- **The mechanical system would NOT benefit from Claude as a pre-trade filter** on current evidence. Claude's 3-trade sample is too small to show it filters losers better than the mechanical rules do; and Claude also lost on all 3 of its own trades, so even an "both-must-agree" overlay (which the user does not want) would be filtering losers via other losers.
- **Minimum useful comparison:** both systems operating in parallel on independent paper accounts for 30+ trading days under the same conditions. Only after that can anyone separate signal from noise.
- **Scope restrictions already in CLAUDE.md:** the user has said emphatically "do not convert the mechanical strategy into an AI strategy" and "preserve the independent Claude experiment" — this report respects both. The one direction that is NOT excluded is an **AI-assisted exit module** operating only on open positions (Claude observes the position + market context, suggests exit; mechanical rules decide entries). That is a separate future experiment with its own design doc — out of scope here.

## Alignment of windows / what makes this comparable

- Instrument: **GBPUSD-TODAY** (CS.D.GBPUSD.TODAY.IP), same for both.
- Account: both use IG DEMO `Z3G4CJ` (mechanical direct, Claude paper broker simulating same IG spread-bet).
- Spread assumption: Claude paper broker uses 0.3 p slippage on each side (`broker.slippage_pips: 0.3` in `config/default.yaml`). Mechanical does not model slippage explicitly — fills come from IG's real market. Over an N-of-3-trades sample this difference is immaterial.
- Position size: both default to 2.0 £/pt (mechanical `trade_size=2.0`, Claude cap `max_size_gbp_per_pip=2.0`). In the window Claude used size 1.0 on all three trades.
- Session hours: mechanical runs 24/7; Claude is bounded by 06:45 start and 18:00 UK entry cutoff. Comparing MECHANICAL ARMS to CLAUDE ARMS only during the 06:45–18:00 UK window would be slightly fairer but makes little difference here (all 3 Claude trades + most mechanical fills are inside that window anyway).

## Observations for operator attention

Independent of the comparison, these facts fell out of the audit and are worth noting:

- **The mechanical local ledger is misleading.** The `broker_vanished` reconciliation defect means the service's own daily reports show zero fills while IG shows 33. The dev branch includes a reconciliation fix (`fetch_recent_activity_for_deal` + lifecycle probe) that resolves this going forward, and `data/reconstructed_trades.csv` lets the operator backfill the historical ledger.
- **Operator-driven bulk-close is doing real work.** The 23 operator closes captured substantial unrealised P&L on 2026-10-28 07:29:50 UTC. The audit cannot say whether this is a repeatable pattern or a one-off reaction to specific context. If it IS a routine, it suggests the mechanical exit module (fixed 100-p TP, software trailing) is not matching the operator's intent.
- **A second EMA PB instance is one restart away from going live under the same prefix.** The dev-branch execution-owner guard hard-closes this failure mode. Operator should either activate the guard or disarm the second instance (prefix rename, flag flip, or deletion of the tree).
- **Claude is spending $13 per week and taking ~1 trade per day.** $4 per trade in input cost. If the operator wants more coverage, raising cost caps or lowering the WAIT bias are the knobs. The audit does not recommend either direction — the sample is too small to say WAIT-heavy is costing performance.
- **Claude's 90 schema-NULL decisions are a prompt/validator bug, not a decisioning defect.** Easy fix for operator — out of scope for this audit.

## Appendix — data pointers

- `data/reconstructed_trades.csv` — 101 rows, mechanical broker-side truth for the window.
- `data/emapb_summary.json` — mechanical aggregates.
- `data/all_decisions.csv` — 506 rows, every Claude decision with snapshot context.
- `data/all_trades.csv` — 3 rows, full Claude trade history.
- `data/rejection_breakdown.csv` — 1 row.
- `data/ai_agent_summary.json` — AI aggregates.
