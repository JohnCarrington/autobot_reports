# Structured `trade_proposal` as the Primary Contract — Design Note

**Date:** 2026-10-28
**Status:** Development only — no production deployment
**Branch:** `fix/scenario-v2-correction2-structured-proposals-20261028`

---

## 1. Context

Before Correction 2 the Scenario V2 reasoner output supported an optional structured `trade_proposal` object alongside the natural-language `required_price_behaviour` (RPB) and the per-opportunity `note`.  The structured object was never promoted to a primary contract: `scenario_recommendation.build_trade_recommendation` only used `trade_proposal.entry_price` + `trade_proposal.stop_price`; the target was always drawn from `resolve_target()` on the anticipated sequence (which in turn depends on narrative-regex fallbacks).

Classification of the 140 INCOMPLETE revisions over 2026-10-23 → 2026-10-28 showed that 78 % of them are target-missing (`C` class, 71) or SELL-geometry-violated (`F` class, 38) — both symptoms of narrative extraction grabbing the wrong number in the free text.  Historical journal data confirmed that in 30 of those revisions the correct target was already present in `trade_proposal.target_price` and was simply being ignored by the pipeline.

## 2. Design goals

1. Make the structured `trade_proposal` the **authoritative numeric contract** for category A (independent technical) and B (event-informed technical) BUY/SELL opportunities.
2. Keep narrative RPB and `note` as **human-readable context**; downgrade their numeric parsing to a fallback that only runs when the structured proposal is absent.
3. Catch the known failure modes (missing fields, malformed numbers, wrong price scale, wrong direction/geometry, structured-vs-narrative contradiction) **at validation time**, before the recommendation builder's final geometry assertion.
4. Preserve the HIGH → INVALID invariant and Correction 1's CAUTION→CONDITIONAL pass-through.
5. Preserve the operator's category-C and `allow_discretion:true` opt-outs so the AI retains full control over genuinely event-dependent or discretionary setups.

## 3. Schema

### 3.1 Full structured proposal (now required for category A/B BUY/SELL)

```jsonc
"trade_proposal": {
  "direction":      "BUY" | "SELL",         // required
  "entry_price":    13296.0,                // required, index-scale (10000 < p < 20000)
  "stop_price":     13289.87,               // required, index-scale
  "target_price":   13302.0,                // required, index-scale
  "entry_trigger":  "close above 13296",    // optional human-readable
  "stop_rationale": "below BB_L support",   // optional
  "target_rationale": "R00 cluster"         // optional
}
```

### 3.2 Opt-outs preserved

* `category: "C"` (event-dependent): structured proposal is **optional**; the AI legitimately may be awaiting a release.
* `allow_discretion: true`: operator-authorised escape hatch; validator does not enforce structured fields for this opportunity.

### 3.3 Scale rule

| Form | Range | Decision |
|---|---|---|
| Index-scale | `10 000 < p < 20 000` | OK (expected) |
| Broker-scale | `0 < p < 10` | **`PRICE_SCALE_MISMATCH` HIGH** |
| Any other | — | `PRICE_SCALE_MISMATCH` HIGH |

Rationale: GBPUSD prices in the LOI packet are index-scale (`12 727.0`).  A silent broker-scale value (`1.2727`) would otherwise collapse into a comparison with ~0 pips of stop distance.

### 3.4 Geometry rule

| Direction | Required ordering |
|---|---|
| BUY | `stop_price < entry_price < target_price` |
| SELL | `stop_price > entry_price > target_price` |

Any violation emits `STRUCTURED_PROPOSAL_GEOMETRY_INVALID` HIGH → INVALID.

### 3.5 Narrative-contradiction rule

If both `trade_proposal.entry_price` and the natural-language RPB contain a parseable numeric price, the two **must agree within 5 p**.  Divergence emits `STRUCTURED_VS_NARRATIVE_CONTRADICTION` HIGH → INVALID.  This catches the "AI typed 13296 in the structured block and 13360 in the RPB" class of bug.

## 4. New validator flags

Added by `_validate_structured_trade_proposal` in `scenario_quality.py`.

| Code | Severity | Pub decision | When |
|---|---|---|---|
| `MISSING_STRUCTURED_PROPOSAL` | WARN | CAUTION | category A/B BUY/SELL with any of entry/stop/target missing |
| `MALFORMED_STRUCTURED_PRICE` | HIGH | INVALID | non-numeric or non-finite price |
| `PRICE_SCALE_MISMATCH` | HIGH | INVALID | price outside 10 000–20 000 index-scale range |
| `STRUCTURED_PROPOSAL_GEOMETRY_INVALID` | HIGH | INVALID | geometry rule violated |
| `STRUCTURED_VS_NARRATIVE_CONTRADICTION` | HIGH | INVALID | structured entry disagrees with RPB-parsed entry by > 5 p |

The HIGH → INVALID invariant is preserved: every HIGH flag maps to publication_decision = INVALID; nothing is weakened to CAUTION.

## 5. Recommendation builder changes

`scenario_recommendation.build_trade_recommendation`:

* `use_structured` now requires **all three** of `entry_price`, `stop_price`, `target_price` to be present.  Both-but-not-target no longer qualifies.
* When `use_structured` is true, `target.price` is overridden from `trade_proposal.target_price` and tagged with provenance `trade_proposal.target_price=<value>`.  The narrative-extraction fallback (`resolve_target()` on the sequence) is bypassed.
* When `use_structured` is false, the pre-existing narrative-regex fallback still runs — unchanged.  The validator's `MISSING_STRUCTURED_PROPOSAL` WARN keeps the opportunity visible on the dashboard (CAUTION / INCOMPLETE), it does not suppress it.

## 6. Prompt changes

New rule **5e** in `scenario_reasoner.py`'s system prompt:

> For every category A or B opportunity with `direction` ∈ {`BUY`, `SELL`} that is not explicitly `allow_discretion:true`, emit a complete numeric `trade_proposal`:
>
> * `direction` matching the opportunity.
> * `entry_price`, `stop_price`, `target_price` as index-scale numbers (GBPUSD prices sit in the 10 000–20 000 range; a value like 1.3296 is **wrong**).
> * BUY ordering: `stop < entry < target`; SELL ordering: `stop > entry > target`.
> * `entry_trigger`, `stop_rationale`, `target_rationale` as short human-readable context.
>
> If any numeric is genuinely unknown (e.g. the target depends on a yet-to-release event), set `category: "C"` or `allow_discretion:true`.  Do NOT fabricate numbers to satisfy the schema.
>
> If the structured block disagrees with the natural-language `required_price_behaviour`, the structured block wins and the opportunity will be flagged.  Keep them in sync.

The prompt change is **forward-looking**; it cannot retroactively repair the 95 historical revisions that never emitted structured fields.

## 7. What the design explicitly does not change

* No change to the Primary Market Observer's 5-state machine.
* No change to the publication_decision enum (VALID / CAUTION / INVALID / UNVALIDATED).
* No change to the readiness enum (READY / INCOMPLETE / CONDITIONAL / HISTORICAL / SUPPRESSED / STALE / EXPIRED_ENTRY).
* No change to P3 (`trigger_spec` evaluator).  The new structured fields are checked for consistency with `trigger_spec.level_price` by the pre-existing `TRIGGER_SPEC_LEVEL_MISMATCH` validator; alignment is required within 2 p tolerance (unchanged).
* No downstream consumers (dashboard, CSV exports, broker-execution path) require migration.  All three structured fields are already present on the data model; this change only makes them authoritative when read.

---

*End of design note.*
