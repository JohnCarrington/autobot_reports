# Phase 8 — Ranked NMS improvement recommendations

## Guardrails

- **No shadow trading. No shadow deployment. No broker writes. No production change under this phase.** Everything below is a design proposal.
- All claims below are backed by Phase 2 (n=1,561 pivot events across 676 trading days) and Phase 6 (NMS code inspection). None are backed by Phase 3's feature model — Phase 3 **falsified** the idea that momentum/trend/volatility/structure features can predict reject vs breakout at R1/S1 out-of-sample.
- The operator's central requirement is reiterated here: **recognising a reversal after the event is not the same as predicting one beforehand.** The ranked recommendations below strictly concern *reassessment triggers* and *destination awareness*, not predictive signals.

## Recommendation summary

| # | Change | OOS evidence | Implementation risk | Expected benefit shape |
|---|---|---|---|---|
| **1** | Pivot-destination assessor (additive) | STRONG | LOW | Downgrade trend-continuation admission quality at S3/R3 |
| **2** | Session-conditional NMS sensitivity | STRONG | MEDIUM | Reduce LateNY / overlap false admissions; more aggressive LondonOpen |
| **3** | Explicit "destination reached → reassess" signal written to the existing exhaustion cache | STRONG (via #1) | VERY LOW | Reuses existing wiring; no classifier change |
| **4** | Treat P (pivot) touches as low-information events | MODERATE | VERY LOW | Flag (not block) trades admitted within 5p of P |
| **5** | Build historical-replay harness for NMS | N/A (infra) | MEDIUM | Enables ex-ante sizing of #1/#2 before any deploy |
| **6** | Add TD Sequential / ADX as research-only features | NEGATIVE so far | — | Only proceed with clear hypothesis; not evidence-backed |
| **7** | Change NMS classifier state-machine | NEGATIVE | HIGH | Not recommended; classifier design is sound |

Ranked below in detail.

---

### 1. Pivot-destination assessor — **ADDITIVE supplement, do NOT replace the classifier**

**Why.** Phase 2 reach-matrix evidence (1,561 events):
- `R3 UP` 60% reach-next, 40% stay-at-extreme — materially worse than R1/R2 for trend continuation.
- `S3 DOWN` 62% reach-next (mostly S2 retrace, not S-to-S continuation).
- At `R2 UP`, next-pivot distribution is 46% R3 continuation / 42% R1 reversal / 18% none — essentially a flip-a-coin on continuation vs mean-reversion at this level.
- NMS's current admission matrix admits trend-followers equally at R1, R2, R3 (Phase 6 §3 defect (c)).

**What to build.**
- A read-only `pivot_destination.py` module that, for each GBPUSD M5 bar close, emits a signal: `destination_class ∈ {NONE, APPROACHING, AT_R3, AT_S3, PAST_R3, PAST_S3}` + `distance_pips_to_next_pivot` + `prior_pivots_touched_today`.
- Signal persisted to a cache file analogous to `cache/nms_exhaustion_<SYM>.json`.
- The existing `nms_directional_authority.py` ALREADY consumes exhaustion signals. Add a second consumer line: downgrade `BUY ALLOW` (STRONG_UP + trend family) to `BUY FLAG_FOR_REASSESS` when `destination_class in {AT_R3, PAST_R3}`.

**What NOT to build.**
- Do NOT automatically block or auto-reverse. Phase 3 proved features cannot predict reversal at a pivot out-of-sample. `FLAG_FOR_REASSESS` means "require a second confirming signal," not "flip the trade."
- Do NOT change the classifier.

**OOS evidence.** Phase 2 OOS reach-rates remain within ±10pp on TEST at R1/R2/S1/S2 (basis-clean) — the **pattern is stable enough** to use as a gate, even if we cannot predict a single event. It's a filter, not a predictor.

**Implementation risk.** LOW. New module. Pure consumer of existing bar close callbacks and the existing pivots cache (`cache/htf/daily_pivots.json` already in production). No NMS code change.

---

### 2. Session-conditional NMS sensitivity

**Why.** Phase 4 is the single strongest effect in the dataset:
- R3 UP `reject rate`: Asia 11%, LondonOpen 65%, LondonMorning 28%, LN/NY 36%, LateNY 55%.
- Reach rates spread from 85-100% in Asia to 15-45% in LateNY.
- **Same event, different sessions, 3-5x different post-touch behaviour.**

**What to build.**
- Session-conditional versions of `EMERGING_ENTRY_THRESHOLD` and `STRONG_ENTRY_THRESHOLD`.
- LondonOpen / LondonMorning: current thresholds (3 / 6) — this is where pivot interactions produce the cleanest signal.
- LN/NY overlap: raise entry thresholds by +1 (4 / 7) — more evidence required before promoting. Reject rates are elevated here.
- LateNY: raise to +2 (5 / 8) — reach rates drop sharply; weak signal.
- Asia: current thresholds — most events here are drift, not momentum, so stricter thresholds are consistent with the "low-information" character.

**What NOT to build.**
- Do not vary `EVIDENCE_TTL_BARS` by session — it's load-bearing for the C3/C6 corrections (per `nms_v3_classifier.py` C3_TTL_QUARTER_BARS docs).
- Do not add a session-specific confirmation count without the full replay verification.

**OOS evidence.** Phase 4 session gradient is monotonic and stable. The simplest version — require more evidence to promote during low-signal windows — rests on 300+ events per session bucket.

**Implementation risk.** MEDIUM. Threshold changes are intrusive. Needs the Phase 5 replay harness (#5) to verify no silent behavioural regression on historical seasons.

---

### 3. Write destination signal to existing exhaustion cache (zero-touch NMS)

**Why.** `nms_directional_authority.py` already consumes `cache/nms_exhaustion_<SYM>.json`. If `pivot_destination.py` writes to the same file format (merge-only, under a distinct key), the authority code path to block BUY on STRONG_UP + SELL_EXHAUSTION already exists. This is **near-zero NMS risk**.

**What to build.**
- `pivot_destination.py` writes `{"pivot_destination_signal": "AT_R3", "written_at_utc": "..."}` to `cache/nms_exhaustion_GBPUSD.json`.
- Small change in `nms_directional_authority` to read this extra key and OR it into the exhaustion evidence check.

**Implementation risk.** VERY LOW. Shares the proven wiring.

---

### 4. P touches are low-information — flag only

**Why.** Phase 2: 40.6% of P touches trigger **neither** a 10p reject nor a 10p breakout within 15 bars. Highest "no-signal" rate across all pivots. The classifier should not treat a P touch as a decision point.

**What to build.**
- When a trade is admitted and the entry price is within 5 pips of P (daily pivot), the `DirectionalDecision` carries an `entry_quality_flag=NEAR_P`.
- Downstream logging only. **No admission change.**

**OOS evidence.** TRAIN 40.6% "neither" at P vs 14-27% at every other level; TEST 34.2% — stable.

**Implementation risk.** VERY LOW. Pure logging.

---

### 5. Build the NMS replay harness

**Why.** Recommendations #1-#3 should be sized before deploy. Right now Phase 6 is a structural claim — we have not measured "how many trades would be flagged." The replay harness is the measurement tool.

**Scope.** Isolated harness module. Starts `fresh_state("GBPUSD", d)` at each session start; walks the M5 archive to end-of-session; emits a one-row-per-bar JSONL. Join with `pivot_events.csv` to count the specific admission patterns.

**Implementation risk.** MEDIUM. The classifier is pure, but the companion NMS (`normal_market_state.snapshot`) and exhaustion cache are stateful side-channels. Replaying those deterministically is work. Could be scoped as "classifier-only replay" first (ignore side-channels; produce bounds, not exact admissions).

---

### 6. TD Sequential, ADX, order-flow features — do NOT add without a hypothesis

**Why.** Phase 3 tested 14 features and showed they do not generalise. Adding more features without a strong hypothesis compounds the overfit risk (as seen in logistic-regression TRAIN-TEST gaps of 0.27-0.37 AUC). If any feature is added, it should be preceded by:
(a) a clearly stated hypothesis for why it would separate reject from breakout at a specific pivot/session combination,
(b) a pre-registered test window (chronological OOS), and
(c) a stop-rule.

---

### 7. Changing the NMS classifier state machine — NOT RECOMMENDED

**Why.** The classifier design (TTL evidence, family caps, 2-step persistence, strict structural anchor) looks fundamentally sound per the 2026-10-13 validation report referenced in the module docstring. The defects identified in Phase 6 (RANGE-when-directional, pullback-as-reversal) are downstream of **admission policy**, not classification. Changing the classifier risks destabilising everything built on top of it.

---

## Honest limitations

1. **Costs not modelled.** GBP/USD spread ~1p on DEMO; actual execution of a R3-flagged reassessment would cost ~1p round-trip. Any benefit at R3 from the 40% stall rate is marginal unless the stall is deep enough to justify not entering.
2. **Sample sizes:** R3 UP has only 92 events (24.1% in Asia). Any session × pivot bucket is single-digit to low-dozens on TEST. CIs are correspondingly wide.
3. **Basis mix:** Phase 2 includes 106 MID 2026 events. Phase 3 restricted to BID only; Phase 7 uses BID only. Phase 2 headline table mixes bases — individual numbers can shift ±2pp.
4. **No forecasting:** every recommendation above is a FILTER (gate admissions, flag positions, request reassessment). None are PREDICTIONS of continuation vs reversal — Phase 3 showed that cannot be done from this feature set.

## Deploy criteria (for any of these, later)

Standard deployment path per [[feedback_wiring_rule]]:
- Separate authorisation, not inferred.
- Preflight tests + regression tests on a clean worktree.
- Default-OFF flag.
- DEMO first.
- Observability measurement window before enabling broadly.
- No production change under this phase.
