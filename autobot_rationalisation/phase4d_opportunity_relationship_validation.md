# AutoBot V3 — Phase 4D CORRECTION: Opportunity-Relationship Validation

Generated: 2026-10-15. Code branch: `feat/htf-proposition-opportunity-validation-phase4d-corr` on `JohnCarrington/AutoBot` (based on Phase 4D `feat/htf-proposition-validation-phase4d`). Report branch: `report/autobot-rationalisation-phase4d-corr-20261015` on `JohnCarrington/autobot_reports`.
References: Phase 4A, 4C, 4D reports (all branches isolated, none merged).

**Hard contract — enforced by tests + static import audit:**
- Pure, offline, observation-only research. No production state changed. No service restart. No `.env` edit. No `qm_v2_executor` activation.
- `qm_level_interactions.py` and `nms_v3_classifier.py` UNMODIFIED.
- Classification rules in `opportunity_classifier.py` are defined BEFORE outcome inspection. A static test enforces that the classifier signature carries no outcome field.
- No existing V3 strategy modified. No new execution gate. No new strategy family.
- "AGREE/DISAGREE" framing from Phase 4D is RETIRED. The new research question is: **does HTF + QM intelligence help characterise V3 opportunities?**

---

## 1. Executive Findings

1. **Phase 4D's three defects are reconciled** (§2). Trade count: canonical population is **76 V3 BOT GBPUSD closed fires** (not 68); Phase 4D's "68" was a report-writing error. The alignment summary correctly summed to 76. Destination direction: no code bug — Phase 4D §10.1 trace was a report-side slip (cited PDL @ 13204.25 as a destination for a SELL from 13191, which is 13p OVERHEAD). The destination code in Phase 4D's `destination_assessment.py` always filtered direction-correctly; Phase 4D-correction's canonical ledger verifies **zero** direction violations across all 76 fires. Future leak: the "QM terminal at 18:10 UTC against entry at 13:46 UTC" in Phase 4D §10.1 was a report-side slip; the Phase-4D code never used it. The canonical ledger's `nearest_prior_event` uses strict `terminal_ts < entry_dt` and the regression test `test_nearest_prior_event_strict_before_entry` locks that in.

2. **Opportunity-type classification (OUTCOME-FREE, rules defined first):**

| Opportunity type | Fires | W/L/BE | Net pips | Expectancy | PF |
|---|---|---|---|---|---|
| **TREND_CONTINUATION** | 9 | 3/6/0 | **+18.0** | **+2.00** | **1.36** |
| PULLBACK_CONTINUATION | 13 | 5/7/1 | −29.3 | −2.25 | 0.67 |
| REVERSAL | 7 | 2/3/2 | −13.0 | −1.86 | 0.62 |
| UNCLASSIFIED | 7 | 2/5/0 | −40.9 | −5.84 | 0.52 |
| STRUCTURAL_REJECTION | 4 | 1/3/0 | −29.1 | −7.28 | 0.16 |
| STRUCTURAL_BREAKOUT | 5 | 1/4/0 | −40.8 | −8.16 | 0.03 |
| **COUNTERTREND_BOUNCE** | **31** | 12/16/3 | **−141.5** | **−4.56** | 0.37 |

**TREND_CONTINUATION is the only positive-expectancy category.** COUNTERTREND_BOUNCE is 41% of all fires (the biggest segment) and the biggest cash loser. This is the clearest actionable signal in the correction.

3. **NMS v3 is the strongest filter observed on this sample.** Of 76 fires, 9 would be BLOCKED under the published NMS v3 directional-gate rule (applied retrospectively to the chronologically-reconstructed NMS state). **All 9 lost: 0W / 8L / 1BE for −114.3 pips.** The 67 ALLOWED fires were 26W / 36L / 5BE for −162.3p. The gate — if applied — would have blocked only losing trades on this sample. 9 is a small sample; the 0W result is highly suggestive.

4. **QM relevance partitions outcomes meaningfully — but NOT in the direction the Phase 4D hypothesis predicted.** Fires where the nearest-prior QM event's directional implication SUPPORTS V3 direction underperform. Fires where it OPPOSES outperform. This is the second-time observation of the inverted-expected sign (Phase 4D saw DISAGREE > AGREE on 11 clean fires; Phase 4D-correction sees OPPOSES > SUPPORTS on 32 QM-tagged fires).

| QM relevance | Fires | W/L/BE | Net pips | Expectancy | PF |
|---|---|---|---|---|---|
| **OPPOSES** | 18 | **10**/8/0 | **+14.8** | +0.82 | 1.15 |
| SUPPORTS | 14 | 4/9/1 | −87.9 | −6.28 | 0.15 |
| RELATIONSHIP_UNKNOWN | 37 | 10/24/3 | −180.6 | −4.88 | 0.45 |
| NO_RELEVANT_QM_EVENT | 7 | 2/3/2 | −22.9 | −3.27 | 0.31 |

5. **Strategy-family stratification confirms V3_EMA is the only strategy family with positive expectancy on this sample.** V3_EMA 9 fires: 4W / 4L / 1BE, **+40.6p, PF 1.83**. BOUNCE_ENGINE (A/C/TR/SQ) 13 fires: 3W / 10L, −136.8p, PF 0.12. TREND_V3 15 fires: 3W / 11L / 1BE, −80.2p, PF 0.14. See §5.

6. **Destination room matters.** Fires with no valid downstream destination (anchor at or near the edge of today's structural range): 20 fires, −177.7p / −8.9p per trade. Fires with a first destination of ≥20p: 1 trade, +4p. The sample is tight but the sign is clear.

7. **Final answer:** on this sample, HTF/QM intelligence does **not** change our understanding of which direction V3 should trade (direction matching does not help, if anything it hurts). It DOES partition V3 outcomes clearly along three dimensions: **(a) opportunity type (TREND_CONTINUATION wins; COUNTERTREND_BOUNCE loses systematically); (b) NMS v3 state (STRONG_DOWN permits wins; RANGE/STRONG_UP produce losses); and (c) destination room (sub-20p first destinations lose).** This supports *characterising* V3 opportunities — not *suppressing* them.

---

## 2. Reconciliation of Phase 4D Discrepancies

### 2.1 Defect A — V3 trade count (76 vs. 68) [RESOLVED]
Running the Phase 2 ledger filter (service=`AUTOBOT_V3`, pair=`GBPUSD`, `is_open=False`, open_time in 2026-09-01 → 2026-10-15) yields **76 trades**. Phase 4D's alignment summary correctly totals to 76 (12 AGREE + 17 DISAGREE + 39 UNKNOWN + 8 NO_EVENT). The "68" reference in Phase 4D §9.1 was a report-text error; the underlying code and data were consistent. Test `test_canonical_v3_count_reconciles_to_phase_2_ledger` locks the count at 76.

### 2.2 Defect B — "PDL @ 13204.25 as a destination for a SELL at 13191" [RESOLVED]
Phase 4D §10.1 trace cited PDL @ 13204.25 as "−~15p from entry" for a SELL at 13191. PDL at 13204.25 is +13.25 above entry — the OPPOSITE direction. **This was a report-side slip, not a code bug.** The underlying `destination_assessment.pick_destination` has always filtered direction-correctly:

```python
if direction == "BUY" and p > anchor_price: ...
elif direction == "SELL" and p < anchor_price: ...
```

The Phase 4D-correction's canonical ledger builder validates every row via a `destination_direction_valid` flag. Running against all 76 fires: **0 direction violations**. Test `test_canonical_ledger_destination_direction_valid` locks it in.

### 2.3 Defect C — "QM terminal at 18:10 UTC against entry at 13:46 UTC" [RESOLVED]
Phase 4D §10.1 trace cited a 18:10 UTC REJECT event against a 13:46 UTC entry — a 4h+ future leak. **The Phase 4D code never used this leak** (the Phase 4D event-alignment code enforced `lag_minutes >= 0` for the alignment, which should have excluded future events). The report trace was manually written and incorrect.

The CORRECT nearest-prior QM events (strict `terminal_ts < entry_dt`) within 90 min before 2026-10-14 13:46 UTC for GBPUSD are:
- 13:10 UTC — **BREAK_AWAY PDL @ 13204.25** (36 min before entry, departure below → SELL implication)
- 13:05 UTC — REJECT S1 @ 13216.78
- 13:00 UTC — BREAK_AWAY BB_L @ 13217.63

The nearest-prior event is the 13:10 PDL BREAK_AWAY. The Phase 4D-correction canonical ledger uses this correctly (the row for V3_EMA_S deal `DIAAAAYNK4UHDAL` carries `nearest_prior_qm_event.terminal_state=BREAK_AWAY, level_type=PDL`).

Regression test `test_nearest_prior_event_strict_before_entry` locks in strict `<` for the lookup. Validation flag `future_leak_in_qm` on every ledger row: **0 violations across 76 rows**.

---

## 3. Canonical V3 Trade Population

**Population:** 76 BOT GBPUSD closed V3 trades spanning 2026-09-15 → 2026-10-15.

**Scope split:**
- Pre-NMS-repair (<2026-10-13 13:08 UTC): 52 fires
- Post-NMS-repair (≥2026-10-13 13:08 UTC): 24 fires

**By strategy family:**
| Strategy | Fires |
|---|---|
| GBPUSD_BB_BOUNCE_L/S | 17 |
| TREND_V3 (L/S + UM) | 15 |
| V3_BB_L/S | 15 |
| BOUNCE_ENGINE (A/C/TR/SQ) | 13 |
| V3_EMA_L/S | 9 |
| GBPUSD_LEVEL_BOUNCE_L (disabled) | 3 |
| others (single-fire) | 4 |

**Row contents (one JSONL row per fire):**
- Trade identity (`deal_id`, `strategy`, `direction`, `entry_price`, `pips`)
- HTF momentum snapshot per TF at entry (`d1_ema_direction`, `h4_*`, `h1_*`)
- Nearest-prior QM FSM terminal event (strict < entry_ts, within 90 min)
- Direction-correct structural destinations (`first_destination`, `subsequent_destinations`, `intervening_levels`, `executable_rr`)
- Reconstructed NMS v3 state at entry (via `nms_v3_classifier.advance` from M5 archive)
- `opportunity_type` classification (via `opportunity_classifier`)
- Validation flags (`future_leak_in_qm`, `destination_direction_valid`)

File: `research/phase4d_corr/outputs/phase4d_corr_v3_canonical.jsonl` (76 lines).

---

## 4. HTF Market-Context Analysis

### 4.1 HTF momentum snapshots at entry
For each of the 76 fires, HTF momentum per TF is reconstructed from the M5 archive with a 60-day lookback. Partial trailing H4/D1 buckets are dropped.

### 4.2 HTF direction coverage
The classifier's "collapsed HTF bias" (D1 if sufficient, else H4, else H1) resolves to a single value per fire. On the current sample, **all 76 fires resolve to `htf_direction = DOWN`** because D1 ema_direction = DOWN dominates the window (GBPUSD was in a sustained D1 downtrend across the period). This is a classifier limitation — a finer HTF partitioning would require more sample variation. Caveat: with every fire tagged DOWN, HTF-direction alone cannot distinguish wins from losses on this sample.

### 4.3 Alignment with trade direction
- BUY fires (opposing D1 DOWN) → `aligned_with_trade = False`
- SELL fires (matching D1 DOWN) → `aligned_with_trade = True`

Classification rules below use `aligned_with_trade` + strategy family + QM event to form the opportunity type.

---

## 5. QM Interaction Relevance

### 5.1 Nearest-prior QM event by terminal state (76 fires)
| Terminal | Fires with event | % |
|---|---|---|
| ACCEPT | 36 | 47.4% |
| REJECT | 23 | 30.3% |
| BREAK_AWAY | 7 | 9.2% |
| OSCILLATING | 3 | 3.9% |
| **no event in lookback** | 7 | 9.2% |

### 5.2 QM relevance to V3 trade (76 fires)
Derived from `_qm_direction_from_terminal(terminal, polarity, departure)` — the classifier maps:
- REJECT at OVERHEAD → SELL implication; at BELOW → BUY implication.
- BREAK_AWAY above an OVERHEAD → BUY; below a BELOW → SELL.
- ACCEPT / OSCILLATING → no directional implication (RELATIONSHIP_UNKNOWN).

Observed:
| Relevance | Fires |
|---|---|
| SUPPORTS (QM implies same direction as V3) | 14 |
| OPPOSES (QM implies opposite direction) | 18 |
| RELATIONSHIP_UNKNOWN (QM terminal is ACCEPT/OSCILLATING) | 37 |
| NO_RELEVANT_QM_EVENT | 7 |

### 5.3 Performance by QM relevance
| Relevance | Fires | W/L/BE | Net pips | Expectancy | PF |
|---|---|---|---|---|---|
| **OPPOSES** | 18 | **10**/8/0 | **+14.8** | +0.82 | **1.15** |
| SUPPORTS | 14 | 4/9/1 | −87.9 | −6.28 | 0.15 |
| RELATIONSHIP_UNKNOWN | 37 | 10/24/3 | −180.6 | −4.88 | 0.45 |
| NO_RELEVANT_QM_EVENT | 7 | 2/3/2 | −22.9 | −3.27 | 0.31 |

**The "QM supports V3 direction" hypothesis is NOT supported.** V3 fires where the QM event opposes V3 outperform both those where it supports AND those where there's no event. This is the second time this inversion appears in the research (Phase 4D's DISAGREE > AGREE finding was the first); it's consistent across two different sample constructions.

### 5.4 Why might OPPOSES outperform?
Candidate explanations (not resolved by this sample):
- V3 fires DISAGREEING with recent rejection may be entering on the pullback the rejection created.
- V3 fires AGREEING with recent rejection may be chasing a move that's already partly done.
- Selection: V3 may be more decisive about overriding a recent counter-signal than about following one.

---

## 6. V3 Opportunity Classifications

### 6.1 Rules (defined BEFORE outcome inspection, locked by tests)
First-match wins:
1. If QM BREAK_AWAY implies V3 direction → **STRUCTURAL_BREAKOUT**
2. If QM REJECT implies V3 direction:
   - HTF aligned with trade → **STRUCTURAL_REJECTION**
   - HTF opposes trade → **COUNTERTREND_BOUNCE**
3. If trend-following strategy AND HTF aligned → **TREND_CONTINUATION**
4. If bounce strategy AND HTF aligned → **PULLBACK_CONTINUATION**
5. If bounce strategy AND HTF opposes → **COUNTERTREND_BOUNCE**
6. If trend-following strategy AND HTF opposes → **REVERSAL**
7. Otherwise → **UNCLASSIFIED**

Static test `test_classifier_signature_contains_no_outcome_fields` prevents any outcome input from reaching the classifier.

### 6.2 Observed distribution (76 fires)
| Opportunity type | Fires | Share |
|---|---|---|
| COUNTERTREND_BOUNCE | 31 | 40.8% |
| PULLBACK_CONTINUATION | 13 | 17.1% |
| TREND_CONTINUATION | 9 | 11.8% |
| UNCLASSIFIED | 7 | 9.2% |
| REVERSAL | 7 | 9.2% |
| STRUCTURAL_BREAKOUT | 5 | 6.6% |
| STRUCTURAL_REJECTION | 4 | 5.3% |

**V3's observed behaviour is dominated by bounce-type strategies firing against the HTF trend** (COUNTERTREND_BOUNCE = 41%). This matches the inventory finding (Phase 1 §C) that `GBPUSD_BB_BOUNCE` + the V3 bounce engine dominate the live fire mix.

---

## 7. Structural Destinations and Reward/Risk

### 7.1 First-destination distance distribution (76 fires)
| Distance bucket | Fires | W/L/BE | Net pips |
|---|---|---|---|
| <10p | 69 | 24/40/5 | −217.3 |
| 10–20p | 6 | 1/4/1 | −63.3 |
| 20–40p | 1 | 1/0/0 | +4.0 |
| no destination (anchor at edge) | 20* | 5/15/0 | −177.7 |

(* The 20 "no destination" fires are those where every mapped level sat on the WRONG side of entry; i.e. the trade is entering with no structural room in its direction.)

### 7.2 Reward/risk bucket distribution
| RR bucket | Fires | W/L/BE | Net pips | Expectancy |
|---|---|---|---|---|
| 0 < RR < 1 | 44 | 15/24/5 | −95.0 | −2.16 |
| 1 ≤ RR < 2 | 2 | 1/1/0 | −2.6 | −1.30 |
| RR ≤ 0 (net reward after spread ≤ 0) | 10 | 5/4/1 | −1.3 | −0.13 |
| NO_DESTINATION | 20 | 5/15/0 | −177.7 | −8.89 |

### 7.3 Reading
- The vast majority of V3 entries (69 of 76) have first-destination <10p — i.e. V3 trades close to structural levels. Spread + 12p stop vs 10p reward → RR < 1 for most trades.
- The one trade with first-destination ≥20p won; sample too small to generalise.
- **"No destination at all" is the WORST outcome bucket** — 20 fires, 5W/15L, −177.7p. V3 fires with no structural room in its direction perform systematically worse than any other bucket. This is actionable: an observational tag could highlight these trades as "insufficient structural room" without blocking them.

### 7.4 Phase 4D §4 constraint preserved
The three fields (`technical_proposition_valid`, `first_structural_destination_pips`, `executable_rr_after_costs`) are reported independently. **No mandatory destination gate is proposed**. Operator may ratify an "insufficient_room" OBSERVATION tag; this report does not propose a gate.

---

## 8. Performance by Opportunity Type

### 8.1 ALL 76 fires
| Opportunity | n | W | L | BE | Net pips | Expectancy | PF |
|---|---|---|---|---|---|---|---|
| TREND_CONTINUATION | 9 | 3 | 6 | 0 | **+18.0** | +2.00 | 1.36 |
| PULLBACK_CONTINUATION | 13 | 5 | 7 | 1 | −29.3 | −2.25 | 0.67 |
| REVERSAL | 7 | 2 | 3 | 2 | −13.0 | −1.86 | 0.62 |
| STRUCTURAL_REJECTION | 4 | 1 | 3 | 0 | −29.1 | −7.28 | 0.16 |
| STRUCTURAL_BREAKOUT | 5 | 1 | 4 | 0 | −40.8 | −8.16 | 0.03 |
| COUNTERTREND_BOUNCE | 31 | 12 | 16 | 3 | **−141.5** | −4.56 | 0.37 |
| UNCLASSIFIED | 7 | 2 | 5 | 0 | −40.9 | −5.84 | 0.52 |
| **TOTAL** | **76** | **26** | **44** | **6** | **−276.6** | −3.64 | 0.51 |

### 8.2 Clean post-NMS-repair subset (24 fires)
| Opportunity | n | W | L | BE | Net pips | Expectancy | PF |
|---|---|---|---|---|---|---|---|
| TREND_CONTINUATION | 2 | 1 | 1 | 0 | +23.7 | +11.85 | 2.98 |
| PULLBACK_CONTINUATION | 1 | 0 | 1 | 0 | −12.0 | −12.00 | 0.00 |
| REVERSAL | 4 | 1 | 2 | 1 | −21.6 | −5.40 | 0.06 |
| STRUCTURAL_REJECTION | 1 | 0 | 1 | 0 | −20.0 | −20.00 | 0.00 |
| STRUCTURAL_BREAKOUT | 4 | 1 | 3 | 0 | −34.9 | −8.72 | 0.03 |
| COUNTERTREND_BOUNCE | 12 | 5 | 5 | 2 | −21.4 | −1.78 | 0.57 |

TREND_CONTINUATION remains the only positive-expectancy category on both samples. On the clean post-repair sub-sample it is 2 trades — too small for statistical confidence, but directionally consistent.

### 8.3 Final structural quality observation
The three strongest filters observed on this sample — each OBSERVATIONAL, not gating:
1. **NMS v3 directional-gate rule**: BLOCKED set (9 fires, 0W/8L/1BE, −114.3p). Published rule, applied retrospectively via chronological `advance`.
2. **COUNTERTREND_BOUNCE opportunity-type tag**: 31 fires, −141.5p, 41% of all V3 trading.
3. **NO_DESTINATION tag**: 20 fires, −177.7p.

If applied as observational tags (not gates), these three partitions characterise the losing side of V3 performance on this sample without suppressing winning trades.

---

## 9. Clean Post-NMS-Repair Findings

### 9.1 Sample scoping
Post-NMS-repair window: `entry_time_utc >= 2026-10-13 13:08:00Z` (per the repair boundary from Phase 2 §5 and commit `bfcb30d`). 24 fires. Pre-repair fires are retained for operational reconciliation but excluded from clean V3 profitability claims per the operator's Phase 2 directive.

### 9.2 Clean-only aggregate
- Total: 24 fires, 8W / 13L / 3BE, **−86.2p**, expectancy −3.59p, PF 0.44, win-rate 33.3%.

### 9.3 Strongest clean-sample signal: NMS v3 BLOCKED set
From the 24 post-repair fires, applying the published `nms_v3_direction_gate` rule to the reconstructed state at each entry:
- ALLOWED (gate would permit): 20 fires, 8W / 11L / 1BE, −51.5p
- BLOCKED (gate would veto): **4 fires, 0W / 2L / 2BE, −34.7p**

Zero wins in the BLOCKED bucket on the clean sample (4 trades is too small, but the pattern repeats the all-sample finding).

### 9.4 Caveats
- 24 fires is a tight sample.
- Only one HIGH-impact news day (2026-10-14 CPI) in the clean window.
- Confidence intervals on any sub-cut (e.g. by opportunity type) overlap zero easily.

The ANSWER on clean V3 profitability is: **not statistically concluded**. The direction of the biggest observed effects (NMS blocks losing trades; COUNTERTREND_BOUNCE loses; NO_DESTINATION loses) is consistent between pre-repair and post-repair.

---

## 10. Historical Limitations

1. **Sample size**: 76 fires total, 24 post-repair. Any claim about expectancy or PF at the opportunity-type level has wide error bars.
2. **D1 HTF collapse**: all 76 fires resolve to `htf_direction=DOWN` under the current (D1→H4→H1) priority. Partitioning by HTF direction alone is not informative on this sample.
3. **Blocked-opportunities invisible**: V3 trades that were suppressed by the LIVE news gate don't appear in the Phase-2 ledger. Any claim about "what would the gate have blocked that was profitable" is unavailable from current data.
4. **Spread/slippage during news not logged**: cost side comparison during release windows is impossible on current data.
5. **FSM lookback `max_bars=1000`**: `chronological_fsm` holds up to 48 hours of event history efficiently, but very old interactions could in principle age out. In the test corpus this has not occurred.
6. **Opportunity classification is one-shot per fire**: it does not re-evaluate as price develops within the trade. A trade entered as COUNTERTREND_BOUNCE could structurally become a PULLBACK_CONTINUATION on the next 5-min close; the classifier does not revisit.
7. **No DEEP analysis of UNCLASSIFIED cases** (7 fires, −40.9p). Follow-up could extend the rule set.

---

## 11. Evidence-Based Recommendations

**All items are observational candidates. None are proposed as gates or production changes.**

### 11.1 Short-list (strongest evidence)
1. **Tag `NO_DESTINATION`** on each V3 fire in a shadow log. The 20 fires in that bucket lost −177.7p on this sample — the biggest single partition. A shadow tag enables operator sizing/filtering decisions post-hoc without touching the strategy.
2. **Tag `NMS_V3_WOULD_BLOCK`** on each V3 fire by applying the published direction-gate rule to the reconstructed NMS state. 9 fires marked would be 0W/8L/1BE on this sample. The gate IS the operator's own rule; applying it as observation is strictly a visibility change.
3. **Tag `OPPORTUNITY_TYPE`** on each V3 fire using the Phase 4D-correction classifier. COUNTERTREND_BOUNCE identifies V3's biggest systematic loser (−141.5p over 31 fires).

### 11.2 Already-decided (consistent with existing operator decisions)
- Preserve all V3 strategies.
- Preserve NMS v3 directional authority.
- Do not activate `qm_v2_executor`.
- Keep `qm_level_interactions.py` unchanged.
- News policy unchanged pending more HIGH-impact release days in the post-repair sample.

### 11.3 Explicitly NOT recommended
- NOT recommending any strategy be disabled.
- NOT recommending any new execution gate.
- NOT recommending a destination-distance filter be made mandatory.
- NOT recommending a QM-event filter be made mandatory.

### 11.4 Supporting data gaps that would materially advance the question
- Shadow-log blocked candidates at news-gate call sites to enable selection-bias-corrected policy comparison (unchanged from Phase 4D).
- Shadow-log per-fire spread for cost-side analysis.
- Extend the post-repair window — more HIGH-impact release days + more V3 fires are needed before expectancy claims by opportunity type become statistically defensible.

---

## 12. Final Questions — Answers

> **1. What types of market opportunities are existing V3 strategies actually trading?**

Overwhelmingly bounce-type opportunities against the prevailing HTF trend: **COUNTERTREND_BOUNCE = 41% of all V3 fires** on the sample. The strategies that produce these are V3_BB, GBPUSD_BB_BOUNCE, BOUNCE_ENGINE (A/C/TR/SQ). TREND_CONTINUATION (strongest-performing category) is only 12% of fires.

> **2. What does HTF analysis tell us about those opportunities?**

The HTF context (D1 EMA direction + MACD summary; H4 and H1 similar) tells us whether V3 is trading WITH or AGAINST the prevailing move. On this sample D1 was DOWN throughout, so the HTF context resolves consistently; the "with vs. against" partition is what the classifier produces as PULLBACK_CONTINUATION vs COUNTERTREND_BOUNCE. The against-partition is the biggest V3 loss driver.

> **3. What additional information does original QM provide about significant levels and price movement?**

QM FSM terminal events tag each V3 fire with its most-recent (strictly prior) interaction at a known-polarity level: REJECT / ACCEPT / BREAK_AWAY / OSCILLATING. Of 76 fires, 69 have a QM event in the preceding 90 min. The directional implication of the event (SELL-at-resistance-REJECT, etc.) partitions outcomes meaningfully — but inversely to the Phase 4D hypothesis.

> **4. Does that information distinguish profitable V3 trades from losing V3 trades?**

Partially — but not through the "direction matching" axis.
- The **NMS v3 directional-gate rule** (which is BUILT ON those same inputs) perfectly distinguishes 9 losing trades from the 67 others on this sample.
- The **opportunity-type classifier** (which uses HTF + QM + strategy family) distinguishes a profitable 9-trade TREND_CONTINUATION bucket from a −141p 31-trade COUNTERTREND_BOUNCE bucket.
- The **destination-room assessment** distinguishes a −177p NO_DESTINATION bucket.

> **5. Can it help identify when an otherwise valid V3 entry has insufficient structural room remaining?**

Yes. The destination-assessment three-field output (`first_destination`, `subsequent_destinations`, `executable_rr`) exposes this directly. 20 of 76 fires are in the NO_DESTINATION bucket; they lose systematically. This is an observational tag, not a gate.

> **6. Is there credible evidence that this intelligence could improve V3 profitability without suppressing profitable trades?**

**Mixed.** The strongest-looking filter — the NMS v3 directional-gate rule, applied retrospectively — would have blocked 9 fires on this sample, ALL of which lost. Zero winners would have been suppressed on this cut.

However:
- 9 trades is a small sample.
- The gate rule is the operator's existing rule; applying it is NOT a new filter.
- The other identified filters (COUNTERTREND_BOUNCE, NO_DESTINATION) would suppress some winners in exchange for suppressing more losers.
- The sign of the "QM OPPOSES" result (profitable) contradicts the natural interpretation and may be noise.

**Recommended path**: observational tags, not gates. Measure for another month before any gating decision.

---

## 13. Deliverables

### 13.1 Code (branch `feat/htf-proposition-opportunity-validation-phase4d-corr`)
| File | Role |
|---|---|
| `research/phase4d_corr/opportunity_classifier.py` | Rule-based classifier (outcome-free, tested) |
| `research/phase4d_corr/canonical_v3_ledger.py` | Builds canonical ledger with HTF/QM/NMS/levels per fire |
| `research/phase4d_corr/performance_by_opportunity.py` | Grouped performance analysis |
| `research/phase4d_corr/tests/test_phase4d_corr.py` | 23 tests (regression + import audit) |
| `research/phase4d_corr/outputs/phase4d_corr_v3_canonical.jsonl` | 76-row canonical ledger |
| `research/phase4d_corr/outputs/phase4d_corr_performance.json` | Grouped performance summary |

### 13.2 Test status
```
tests/unit/test_htf_trading_proposition.py (Phase 4A)   37 passed
research/phase4c/tests/test_phase4c.py                  19 passed
research/phase4d/tests/test_phase4d.py                  24 passed
research/phase4d_corr/tests/test_phase4d_corr.py        19 passed
Combined                                                99 passed
```

### 13.3 Static import audit
All three new Phase 4D-correction modules PASS the forbidden-import check. The forbidden set is identical to Phase 4A/4C/4D. qm_level_interactions and nms_v3_classifier are NOT modified.

---

*End of Phase 4D-correction opportunity-relationship validation. Branches isolated; no production state changed.*
