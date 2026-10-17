# Stage 0 — Amendment A1 — HTF is a tag, not a gate

**Date:** 2026-10-17
**Supersedes:** any reading of the original brief §3 that implied HTF direction could gate countertrend liquidity-sweep events.
**Issued by:** operator, following publication of `stage0_ambiguity_audit.md` at commit `c2dd613`.
**Status:** FROZEN before Stage 2 begins.

---

## 1. Verbatim operator clarification

> Do not use Daily, H4 or H1 direction to admit, reject or filter liquidity-sweep events. Identify all qualifying BUY and SELL events independently of higher-timeframe direction. Record Daily/H4/H1 alignment at the event timestamp solely for subsequent analysis. Preserve the distinction between trend-aligned and countertrend trades in the results, but do not allow higher-timeframe direction to change the event population or M5 entry rules. The purpose is to discover whether liquidity sweeps and repeated structural tests produce tradeable reversals, including reversals against the prevailing higher-timeframe trend.

## 2. Impact on the preregistered design

The Stage 0 design in `stage0_ambiguity_audit.md` §5 and the chosen rejection detector (AMB-1 primary) already identify events on pure M5 geometry without HTF inputs. **No implementation change needed.** This amendment makes the policy explicit so that no future reader can reintroduce an HTF filter by assuming the original brief §3 permitted one.

### 2.1 What stays

- `d1_direction.compute_d1_direction_from_candles` — still computed per event, attached as `d1_bias` column.
- `TimeframeContext.on_5m_close` — still fed chronologically to produce `h4_bias`, `h1_bias` columns.
- D1/H4 agreement (`confidence_scorer._check_hard_gates` rule) — still computed, attached as `d1_h4_aligned` boolean column.
- Deliverable H ("HTF context comparison") — remains valid as a **descriptive** split in the final verdict.
- Deliverable I breakdowns — `trend_aligned` and `countertrend` cohorts both reported.

### 2.2 What is forbidden

- No admission filter: all qualifying BUY and SELL events are counted irrespective of D1/H4/H1 direction.
- No entry filter: the AMB-1 rejection detector + the §7 confirmation rule must not condition on HTF.
- No weighting: an event where D1 is BULL and the trade is a SELL has equal weight in the ledger to a trend-aligned event.
- No per-direction cap: Section 10 exit models apply symmetrically to BUY and SELL regardless of HTF.
- No separate OOS splits by HTF agreement — chronological OOS is partitioned by time, not by HTF.

### 2.3 Compatibility with prior memory

Consistent with the operator's prior `project_r3_htf_veto_evidence` finding (2026-09-22) that naive HTF vetoes wrongly blocked 4.3% of counter-HTF majors on NORMAL days. This research is the empirical replacement for a mechanical HTF veto.

## 3. Confirmed implementation checklist for Stage 2

When Stage 2 (Deliverable B — event population scan) runs:

- [ ] Scanner receives only (symbol, M5 bars, structural levels) — no HTF arguments.
- [ ] Event-record schema includes `d1_bias`, `h4_bias`, `h1_bias`, `d1_h4_aligned`, `trade_vs_d1` (`aligned` / `countertrend` / `d1_neutral`).
- [ ] No event is excluded on an HTF criterion.
- [ ] AMB-1 primary (`level_ladder._is_rejection_at_rung`) implementation is grep-checked for any import of `d1_direction`, `timeframe_context`, or `confidence_scorer` — must be zero.
- [ ] Deliverable K final verdict reports the four cohorts (aligned-BUY, aligned-SELL, countertrend-BUY, countertrend-SELL) separately AND combined.

## 4. Still waiting

AMB-1, AMB-2, AMB-3 decisions remain open from `stage0_ambiguity_audit.md` §2. HTF clarification does not resolve them.

End of amendment A1.
