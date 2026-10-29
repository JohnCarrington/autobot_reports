# Scenario V2 — 29 October 2026 Investigation

Investigation into why Scenario Intelligence V2 displayed `WAIT` for the entire morning of 29 October 2026 despite material GBP/USD price movement, including a 21.7-pip upside rally and a 33.8-pip downside reversal.

**Investigation only. No code changes, service restarts, or deployments were performed.**

## Deliverables

| File | Purpose |
|------|---------|
| [`GBPUSD_20261029_MARKET_RECONSTRUCTION.md`](GBPUSD_20261029_MARKET_RECONSTRUCTION.md) | Verified M5 candle walk 02:30-10:00 UK time, swing H/L, breakout taxonomy, news context |
| [`SCENARIO_V2_20261029_DECISION_TIMELINE.csv`](SCENARIO_V2_20261029_DECISION_TIMELINE.csv) | Full timeline — every revision 06:50-09:50 with primary observer state, V2 direction, trade proposal, publication decision, trigger status |
| [`INVALID_FLAGS_ROOT_CAUSE.md`](INVALID_FLAGS_ROOT_CAUSE.md) | 09:46 screenshot three HIGH flags — exact AI output, validator rules, false-positive mechanism |
| [`WATCH_REJECTION_20261029_AUDIT.md`](WATCH_REJECTION_20261029_AUDIT.md) | Primary observer 37-bar WATCH_REJECTION streak; stated-vs-satisfied invalidation audit; comparison to 27 October 114-bar incident |
| [`C1_C2_LIVE_DEPLOYMENT_VERIFICATION.md`](C1_C2_LIVE_DEPLOYMENT_VERIFICATION.md) | Module hashes, sweeper import freshness, structured proposal check, dashboard stale-cache evidence |
| [`MISSED_OPPORTUNITIES_20261029.csv`](MISSED_OPPORTUNITIES_20261029.csv) | Three identified moves classified A-L with primary + contributing causes |
| [`TARGETED_FIX_RECOMMENDATIONS.md`](TARGETED_FIX_RECOMMENDATIONS.md) | Ranked recommendations, counterfactual rescue count, deployment order |

## Final answers (as the task brief requires)

**A. At what time did Scenario V2 first identify today's bearish opportunity?**
2026-10-29T06:50:00Z (UTC = UK on this date, post-BST). Scenario `9fb58109c4dc34c2` revision 0, created with primary_direction=SELL, trade_proposal entry 1.33000, stop 1.33180, target 1.32858 (S1).

**B. Did it identify the opportunity before GBP/USD fell, or afterwards?**
Before. At scenario creation (06:50Z) GBP/USD was 1.33095. The decisive fall from 1.33303 to 1.32965 did not occur until 08:00-09:25Z. However, between creation and the fall, price rallied to 1.33303 — exceeding the scenario's own stop (1.33180) by 12.3 pips BEFORE the entry condition was ever triggered. The scenario should have been invalidated at 08:00; it was not.

**C. Why exactly was the 09:46 recommendation INVALID?**
Three HIGH quality flags on the 09:30 scenario revision (shown on the dashboard at 09:46:30Z): two `UNSUPPORTED_CONFIDENCE_PERCENT` (matching "<10% probability" and "<5% probability" dismissive hedges) and one `CATEGORY_A_TRIGGER_WITH_EVENT_NAME` (false positive: validator matched the generic word "Price" in the trigger text against the token "price" from the economic-calendar event "PCE Price Index MoM"). Any HIGH flag drives `publication_decision=INVALID`; the recommendation engine then hard-gates to `recommendation=WAIT, readiness=SUPPRESSED`. See `INVALID_FLAGS_ROOT_CAUSE.md` for full line-cited analysis.

**D. Were the three HIGH flags justified or false positives?**
- Flag 1 & 2 (UNSUPPORTED_CONFIDENCE_PERCENT): mechanically correct but **semantic false positive**. The AI used "<N% probability" to DISMISS unlikely alternative pathways, not to CLAIM confidence for a trade. The validator does not distinguish the two sentiments.
- Flag 3 (CATEGORY_A_TRIGGER_WITH_EVENT_NAME): **FALSE POSITIVE**. Stopword-list defect — `price` is not in `_EVENT_NAME_STOPWORDS` so the generic noun "Price" in natural-language trigger text matches the `price` token from event names like "PCE Price Index MoM".

**E. Did the primary observer become stuck in WATCH_REJECTION again?**
Yes — 37 consecutive bars (06:50Z-09:50Z, growing). Three of the observer's six self-published invalidation conditions were simultaneously satisfied at 08:00 (5 consecutive closes above the pivot, +17.08p high penetration, HH+HL NMS). The agent's own narrative conceded "Bullish NMS structure (HH+HL, 5 confirmed highs) **contradicts** structural reject state" and "price holding above level suggests **weak rejection**". Hypothesis never flipped. Identical pattern to the 27 October 114-bar incident.

**F. Did Corrections 1 and 2 operate correctly in this morning's live session?**
Sweeper + reasoner: **yes**. 19/19 scenario rows carry a complete structured trade_proposal (entry+stop+target); HIGH → INVALID preserved on 31/31 quality rows; `MISSING_STRUCTURED_PROPOSAL` WARN emitted 3 times when a proposal was partial. The CAUTION → CONDITIONAL path is intact in code but received zero rows today because every row triggered at least one HIGH flag — mostly the two false-positive rules above. **The CAUTION path is not broken; it is starved.** Dashboard web-server process: **has a stale `sys.modules` cache** from pre-C2 import on 2026-10-23. Observable in target.provenance showing `sequence_token_match=…` (pre-C2) rather than `trade_proposal.target_price=…` (C2). **No observable impact on today's displayed recommendation** because both resolve to 1.32858 for this scenario. Fix: controlled dashboard-only restart (operator action).

**G. Were any technically valid trading opportunities missed?**
Three movements identified:
1. **BUY 07:00-08:00 upside (+21.7p)** — Neither primary observer nor V2 flagged. Primary cause A (not identified) + G (anchored).
2. **SELL 08:00-09:25 reversal (-33.8p)** — V2 had the right direction from 06:50Z but publication was suppressed every revision (false-positive HIGH flags). The scenario's entry trigger ("2 consecutive closes ≤ 1.33000") was never cleanly met: 09:20 close was 1.32989 (1 of 2), 09:25 close was 1.33008 (back above). Session low was 1.32965 — target 1.32858 was not reached. Classification: F (false-positive HIGH suppression) + G (stop pre-blown at 08:00) + H (trigger 1-of-2, 2nd close invalidated the rule).
3. **BUY 09:25-09:45 recovery (+11.7p)** — too small to be a clean standalone trade (below 14p reward floor) and unsignalled.

**H. Which precise changes would prevent those missed opportunities from recurring?**
See `TARGETED_FIX_RECOMMENDATIONS.md`. Ranked:
1. Add `price` + generic market-structure nouns to `_EVENT_NAME_STOPWORDS` AND constrain AI prompt to use "Close"/"Bar" as trigger subject.
2. Split UNSUPPORTED_CONFIDENCE_PERCENT into HIGH-endorsement vs WARN-dismissive paths OR ban numeric percentages at the prompt level.
3. Primary observer mechanical hypothesis-flip rule when `consecutive_closes_beyond ≥ 2` AND `distance_from_level_pips ≥ 5` AND `nms.demonstrated_direction` conflicts.
4. Pre-entry stop-blown scenario invalidation: `WATCHING/DEVELOPING` → `INVALIDATED` when price touches scenario stop before entry fires.
5. Dashboard-only restart to pick up C2 target-provenance (hygiene, no behavioural impact today).

Counterfactual: deploying only Rank 1 + Rank 2 fixes would have let **24 of 31 (77%)** of today's scenario revisions reach CAUTION → CONDITIONAL SELL instead of INVALID → WAIT. Including the specific scenario the operator saw at 09:46.

**I. Is the dashboard displaying the latest authoritative recommendations?**
Dashboard reads the **latest** scenario revision correctly (observed: 09:40 bar revision at generated_at_utc 09:51:06Z is served now at 09:55Z). The publication_decision banner is accurate (reads directly from the sweeper-written journal). However, the `/observer/trade-recommendation` endpoint computes its payload using `scenario_recommendation.build_trade_recommendation` — this module is **stale** in the long-running dashboard process (`sys.modules` cache from pre-C2 import on 2026-10-23). Material impact today: nil. Fix: dashboard-only restart.

**J. Would P3 have materially improved today's trade timing?**
No. P3 is deterministic trigger evaluation. The scenario's entry rule "2 consecutive closes ≤ 1.33000" was never operationally met (09:20 close below, 09:25 close back above). P3 would have correctly waited and never fired, same as the current system. P3's **secondary benefit** would be real-time pre-entry stop-blown detection — if deployed with Rank 4 recommendation, P3 would have auto-invalidated the SELL scenario at 08:00 when price touched 1.33303 (above stop 1.33180). That specific benefit is independent of entry-timing improvement.

---

## Context on restrictions honoured

- No production code modified.
- No services restarted.
- No dashboard restart performed (recommended for operator action — see Rank 6).
- NMS, EMA Pullback, autonomous Claude Trading Agent untouched.
- P3 not deployed.
- No broker orders submitted; no broker-exec paths touched.
- HIGH → INVALID validator contract preserved — recommendations do not weaken it.
- Existing production journals preserved; this investigation only reads them.
