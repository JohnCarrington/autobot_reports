# APPROVED SPEC — AutoBot V3 structural bounce + trend integration (2026-10-15)

Status: **Approved for isolated implementation and historical testing. NOT approved for production deployment.**

## Objective
Integrate EXISTING GBPUSD capabilities only: V3 structural bounce, Trend V3, EMA Pullback; HTF, NMS, structural level map, QM and existing trade manager. Capture recurring London/NY session reversals (particularly observed ~30–35+ pip moves), plus trend opportunities. Do not add new detectors, strategy families, arbitrary vetoes or forced two-trades-per-day logic.

## Opening structural map and Telegram
- At **07:00 Europe/London**, calculate and validate using completed, correctly timestamped candles: PDH/PDL, prior-session highs/lows, pivot P, R1–R3, S1–S3, 00/50 levels, previously established swings/ranges/support/resistance, clusters, dynamic BB and D1/H4/H1 HTF context plus current NMS.
- Prevent lookahead: levels based on the bar forming the bounce extreme must NOT be represented as pre-existing independent structure. Deduplicate same-source levels in confluence reporting.
- Telegram morning message: levels, clusters, HTF/NMS, potential structural zones and destinations. Second briefing **before NY opens**, incorporating established London H/L. Use existing Telegram integration; delivery failure NEVER blocks trading.
- Developing London/NY session H/L enrich the map as they become established; **NEVER wait for them to form** before allowing an otherwise valid trade. Trading remains within existing permitted windows.

## Execution — existing strategies only
1. **V3 Bounce** (NOT legacy standalone BB Bounce) executes valid structural reversals near pre-established significant levels. Existing V3 entry conditions, risk controls and applicable NMS permissions remain authoritative. A single significant level can suffice under existing conditions. **No mandatory three-level confluence; no mandatory QM terminal if V3 did not already require it.**
2. **Trend V3 or EMA Pullback** executes when HTF directional proposition and applicable NMS trend direction align, using existing strategy entry rules. Do not impose blanket day classification: bounce and trend opportunities can coexist.
3. Structural levels and QM supply information about upcoming obstacles and destinations, not unvalidated new entry vetoes.
4. Preserve current strategy identities, NMS directional allowlist and reversal exception, position limits, spread, stop/TP and protective risk rules. No implicit widening or loosening.

## QM-informed management
- Existing QM REJECT / ACCEPT / BREAK_AWAY / OSCILLATING observations inform the **existing trade manager** as positions approach significant levels.
- Objective: allow profitable moves to continue THROUGH levels when acceptance/breakaway is established; respond appropriately to adverse rejection rather than automatically taking 10 pips at first obstacle. **Do not equate QM terminal with immediate exit**; determine causality, timing and trade-manager wiring before choosing and testing any new exit behaviour.
- Preserve protective stops, hard risk constraints and existing trade-management behaviour until validated. **QM currently observes; any proposed management wiring must be isolated and explicitly evidenced.**

## PAA
Existing PAA Stage1 remains dormant. Inventory overlap with QM and V3; not an entry prerequisite, do not activate unless separately justified and approved.

## Historical verification and acceptance
- Reuse ORIGINAL historical GBPUSD session-bounce research and event ledger where available. The 11,951 BB reversal events in Phase 4A are NOT equivalent to the originally observed ~35-pip twice-daily bounces. Do not silently substitute one dataset for the other.
- Reconstruct every level, HTF/NMS state, QM observation and V3 signal chronologically from data available **before decision time**. Distinguish completed-bar and session boundary time, spread, SL/TP, stop-first ambiguity and actual trade-manager semantics. Correctly reconstructed NMS after Oct13 repair; do not judge V3 on compromised pre-repair trades.
- Report London and NY separately: qualifying 10/15/20/25/30/35/40/50+ pip reversal size distributions; both/one/neither opportunities per day; both/one/neither actually captured; signal and fill timing/direction; captured fraction of full move; MFE/MAE; net realised pips, win rate, PF, drawdown, missed/rejected entries with reason.
- Test trend days: HTF+NMS alignment, Trend V3 and EMA Pullback, executable costs/SL/TP; test combined portfolio interference and position limits.
- Development vs untouched validation split; reproducible artefacts, explicit sample sizes, no claims of profitability until verified. Distinguish absence of historical data from a strategy failure. Compare with existing baseline.
- Test Telegram output deterministically with frozen historical market snapshots, UK DST changes and failure modes; no actual historical Telegram sends.

## Delivery plan / restrictions
1. Inspect actual existing interfaces and record baseline, especially V3 Bounce admission, HTF/NMS, QM observer, trade manager, Telegram sender, original bounce ledger. Do not guess.
2. Freeze implementation contract and acceptance tests in isolated research/dev worktree. Reuse code; minimal integration only. No production edits.
3. Build opening/NY structural briefings and nonblocking Telegram path; unit/integration tests.
4. Wire ONLY verified existing strategy components and QM-informed trade management; test causal behaviour and existing risk invariants.
5. Run chronological historical replay; publish evidence, missed-opportunity diagnostics, and a pass/fail acceptance report.
6. **STOP for operator approval before merge/deploy, .env changes, service restarts, trading, or PAA activation.**

Source research: Phase 4A report commit `65f5b024a9e5cfde4727720bb80d0b9529a868b0`, branch `report/phase4a-bounce-level-proximity-20261015`. Key methodological hazards: SWING/RANGE/current-session H/L can include current extreme bar; QM sparse historical logs; V3 44% 'capture' direction-unverified; 10p REV_10 label is NOT full move size.

## Immediate builder handoff
Claude Code on host 161: begin with **read-only interface audit** in a NEW isolated worktree, then implement on a dedicated feature branch. Preserve all live dirty state. Report exact files, commits, tests, historical results and deployment status. Do not change /opt/tradingbot live checkout or /opt/tradingbot/reports-public live clone.
