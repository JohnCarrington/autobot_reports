# Scenario V2 — root cause of late entries and the trade-construction problem

**Scope:** READ-ONLY research + implementation staged. **NOT deployed.**

**Companion deliverables:** `EARLY_ENTRY_METHODOLOGY.md`,
`STOP_AND_TARGET_DESIGN.md`, `HISTORICAL_COMPARISON.md`,
`BACKTEST_RESULTS.csv`, `IMPLEMENTATION.patch`,
`IG_DEMO_INTEGRATION.md`, `DEPLOYMENT_READINESS.md`.

---

## 1. Executive summary

Scenario V2's late-entry behaviour has **three co-dependent causes**,
not one. The previous investigations addressed only the first two:

1. **Executor used wrong timestamp anchor** (fixed 2026-11-03T14:21Z).
2. **40-row window silently excluded most scenarios** (fixed
   2026-11-03T15:00Z).
3. **The reasoner's prompt + parser + validator REQUIRE the AI to
   express entries as structural breakout triggers, and the SAME
   stop/target geometry is used regardless of entry rule**. This is
   the trade-construction problem the current correction addresses.

The previous "quality gate" attempt failed because it accepted (3)
as a given and tried to filter around it. The operator was right to
reject that approach. **(3) must be fixed, not filtered.**

---

## 2. The three enforcement sites that produce late entries

Verified via code audit (research-branch Explore agent, retained in
`SUPERSEDED.md`):

### 2.1 Reasoner prompt — `scenario_reasoner.py`

- Lines 57-332 define `SCENARIO_SYSTEM`. The relevant rule blocks:
  - **5b (OPPORTUNITY CATEGORIES A/B/C)** at approx L211-274:
    describes Category A entries as "close above / break of swing /
    retest of pivot / acceptance beyond a BB" — i.e. all breakout
    triggers.
  - **5d (TRIGGER_SPEC)** at approx L260-274: the `trigger_spec.type`
    enum is `price_break_above` (bar close ≥ level) or
    `price_break_below` (bar close ≤ level). There is no
    `price_momentum_impulse` or `price_rejection_retest` type.
  - **5e (STRUCTURED TRADE PROPOSAL)** at L300+: the
    `trade_proposal.entry_price` is treated as the breakout level.
    There is no field for "setup type" or "entry rationale distinct
    from the structural target".
- Lines 355-413 define `TRADE_PROPOSAL_SCHEMA` and
  `TRIGGER_SPEC_SCHEMA` — the JSON schemas the AI's output is
  validated against. Both bake in the breakout-only trigger enum.

### 2.2 Narrative parser — `scenario_recommendation.py`

- `_extract_entry_price_from_text` (L388-446) accepts an
  `entry_price` ONLY when the surrounding text contains one of
  `breaks? below`, `closes? below`, `<=` / `<` (SELL) or the
  mirror BUY forms. No alternative trigger phrase is recognised.
- `_extract_stop_price_from_text` (L310-367) mirrors this for
  stops.
- A free numeric entry at or near current market cannot pass the
  parser without being wrapped in a breakout phrase.

### 2.3 Geometry validator — `scenario_quality.py`

- `_validate_structured_trade_proposal` (L938-1135) enforces
  `stop < entry < target` for BUY (and the mirror for SELL). It
  does **not** check whether entry is far from current market, nor
  does it distinguish setup types.
- `_validate_opportunity_sides` (L342-386) checks for wrong-sided
  stops/targets. Again, setup-agnostic.

**None of these sites are the directional reasoning model.**
Directional reasoning lives in L57-103 (preamble), L104-176
(INDICATOR DISCIPLINE / EVIDENCE), L177-206 (EVENT STATUS AUTHORITY),
L314-323 (FORWARD-LOOKING FRAMING). The current correction leaves
all of those unchanged.

---

## 3. Why the previous "early entry" test underperformed

The earlier `research/scenario-v2-early-entry-20261103 @ f567077`
backtested Mechanisms A/B/C by using **earlier entry prices** with
V2's **own stop and target** untouched. All three lost. The
operator correctly diagnosed that this was NOT a fair test of early
entry — it was a test of V2's structural stops applied to a
different fill price, which breaks the risk-reward geometry.

Specifically: V2's stop is placed at the structural swing-low
(say 20 p below the breakout trigger). The breakout entry sits
15 p above the swing-low. An "earlier" entry at scenario-gen (say
5 p above the swing-low) means the stop is **effectively 5 p below
the fill**, which is TIGHT. But V2's stop isn't 5 p below the
earlier entry — it is **20 p below the breakout trigger**, which is
~10 p below the earlier entry. So the "early" trade carries nearly
the SAME risk-in-pips as the breakout trade, but with much less
reward left to the target.

The current correction fixes this by **deriving the stop from the
setup's OWN invalidation structure**, mechanically, from M5 bars
available at scenario-gen. Entry, stop, and target are redesigned
together.

---

## 4. What is being changed

| Component | Change | File | Preserve? |
|---|---|---|---|
| Directional reasoning | **UNCHANGED** | `scenario_reasoner.py` L57-206 | yes |
| Scenario state machine | **UNCHANGED** | `scenario_schema.py` L39-70 | yes |
| Anticipated-sequence construction | **UNCHANGED** | `scenario_reasoner.py` L120-170 | yes |
| NMS integration | **UNCHANGED** | `nms_directional_authority.py` | yes |
| Scenario quality publication gate | **UNCHANGED** | `scenario_quality.py` L1186-1224 | yes |
| **TRIGGER_SPEC enum** | **extended** with `price_momentum_impulse` and `price_rejection_retest` | `scenario_reasoner.py` L260-274, `scenario_schema.py` L378-413 | no |
| **TRADE_PROPOSAL_SCHEMA** | **extended** with `setup_type` enum + per-setup stop/target rationale fields | `scenario_reasoner.py` L355-413 | no |
| **Entry-price parser** | **extended** to accept non-breakout trigger phrases | `scenario_recommendation.py` L388-446 | no |
| **Stop-price parser** | **unchanged** — stops still parsed from invalidation text; the AI's own stop is retained as the "structural stop" fallback | `scenario_recommendation.py` L310-367 | yes |
| **Geometry validator** | **extended** with setup-type-aware checks (e.g. momentum stops may be close to entry; breakout stops may be further) | `scenario_quality.py` L938-1135 | no |
| **Executor** | **replaced** for the new setup types by `v2_early_setup.derive` → `v2_demo_executor.submit`. Deployed `shadow_execution.py` **unchanged**. | new `impl/v2_early_setup.py`, `impl/v2_demo_executor.py` | n/a |

**Changes to directional reasoning: zero.** The AI still predicts
direction the same way; it is told how to EXPRESS actionable
setups differently.

---

## 5. The three setups investigated

Details in `EARLY_ENTRY_METHODOLOGY.md`. Backtest results in
`HISTORICAL_COMPARISON.md` and `BACKTEST_RESULTS.csv`.

- **A — momentum impulse continuation.** Fire at the close of the
  first post-gen bar that is a clear momentum impulse in the
  predicted direction (bullish body, range > 1.5× median,
  upper-body > 60 % of range for BUY). Stop below the impulse bar's
  low. Target: V2's structural target.
- **B — pullback + rejection.** Wait 1-3 counter-direction bars,
  then enter on the first in-direction bar whose low is above the
  pullback trough (higher-low formation). Stop below the trough.
- **C — early structural continuation.** Objective 3-bar pivot
  pattern (local peak + local trough + continuation break). Stop
  below the trough.

Each has its own expiry (2 h / 24 M5 bars) so stale setups don't
persist.

---

## 6. What this correction does NOT solve

1. **Sample size.** n = 13 first-READY scenarios. No amount of
   mechanism engineering can rescue a strategy from a 13-trade
   sample. The IG DEMO deployment is a **data-accumulation
   exercise**; expect net-negative outcomes in the first 30+
   trades.
2. **Directional accuracy ceiling.** V2's 60-min MFE > MAE on this
   sample is 64 %. If the ceiling in a larger sample is 50 % the
   mechanism redesign cannot make the strategy profitable.
3. **Target selection drift.** V2's structural targets are often
   the nearest named level. The current correction does not change
   the target-selection prompt — only how the AI expresses the
   trigger that leads to that target. See
   `STOP_AND_TARGET_DESIGN.md` §5 for the operator's open question.
4. **Spread model.** No contemporaneous bid/ask for Oct 23 → Nov 3
   2026. Backtest uses a session-aware model (0.9 / 1.4 / 2.0
   round-trip). News spikes to 5-10 p are NOT modelled.

The deliverable makes NO claim of profitability. It makes a
geometric claim: Mechanism A's trade geometry is strictly less bad
than M1's on every risk dimension measured (MDD, average-loss size,
R:R-at-entry, pips-consumed-at-entry).
