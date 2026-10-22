# Stage 7B.2 — Frozen M5 rejection and continuation/failure experiment
Date: 2026-10-22. Research-only; candidate rules below are **assistant proposals**, NOT user-established trading strategy rules. No change to standalone M5 BB Bounce or production AutoBot.

## Why this experiment
Stage 7B.1 established the H1 BB(20,2)-pierce watch, often a persistent trend rather than a reversal. Structural enrichment adds causal PDH/PDL, P, R1–R3, S1–S3 but lacks historical swing highs/lows. The question is whether *observable M5 rejection* after a watch precedes +20/+30 before an adverse move, and whether time/H1 range/structure add predictive information.

## Frozen observational event/entry definitions
- Universe: all Stage 7B.1 watch events, from the already-frozen band definition: fixed bands from 20 prior **completed** consecutive H1 close values; M5 pierce known only at M5 close.
- Proposed M5 rejection: from the first watch-triggering M5 bar (called W), look at only the **next two contiguous closed M5 bars**. For SELL_WATCH, the first such bar to CLOSE strictly below the fixed H1 upper band with high **not greater than W.high** constitutes an observed rejection; BUY_WATCH symmetric (close strictly above fixed H1 lower band, low not below W.low). If the next two bars are missing, mark GAP; if no such bar appears, NO_REJECTION.
- To distinguish rejection from already-successful trend, record separately whether W.close itself lay beyond the band and whether a rejection forms; do not restrict the universe to W.close outside.
- A rejection is known at its M5 close. Research entry proxy = immediately following M5 OPEN (if absent, CENSORED). Do not substitute an earlier price or future close.
- No additional structural break/retest rule is silently imposed in this first experiment: measure any later break/retest as **features/events**, with a separate freeze before using them to decide entries. This prevents trading-logic drift.
- Same-side consecutive hourly pierces receive distinct **watch IDs** but group into a **run ID**; all are reported; also report first-watch-only results as a predeclared sensitivity analysis. Opposite-side watches remain separately recorded. Overlapping outcomes are dependent, not independent trials.

## First-hit research labels (NOT broker-executable P&L)
- From entry proxy, compare future M5 OHLC extremes for separately reported favourable +20 and +30 pip thresholds against **adverse -12 pips**, corresponding to the broker-minimum SL the user has previously used, as an *explicit research assumption*, not a new trading rule. Both thresholds use entry-price-relative fixed pip units as measured in source archive.
- Observe for **24 contiguous M5 candles (2 hours)** after entry. Any missing candle => CENSORED_GAP (do not count as loss).
- If TP or adverse threshold first reached: TARGET_FIRST or ADVERSE_FIRST. Same M5 candle hits both => AMBIGUOUS_BOTH, report separately; pessimistic bound treats it as adverse-first, optimistic bound as target-first. No assumption that OHLC determines intrabar ordering.
- Neither hit by horizon => UNRESOLVED. No forced exit is assumed. Record MFE, MAE and end-close separately.
- BID DEV/VAL and MID OOS are not executable spread/ask simulations; do not imply net pips. Report hypothetical gross first-hit frequencies separately from plausible measured spread/slippage estimates if independently available. No fabrication of costs.

## Prespecified context comparisons (not filters)
- Time: user's UK 06,07,08,10,11,12,13,14,16 vs controls 09,15 vs other hours. Apply Europe/London and BST/GMT.
- Completed prior H1 range continuous + within-partition quintiles; no using developing H1 future.
- Nearest structural level distances ≤5, (5,15], (15,30], >30 pips. Confluence ≥2 levels within 10p, room to next opposing level in pips. Structural data is PARTIAL: historical swing highs/lows missing; do not claim they were evaluated.
- Distinguish WATCH-to-rejection conversion rate from rejection-to-first-hit continuation probability and total WATCH-to-first-hit yield. Condition on H1 range and time before claiming level-specific effects.
- Negative control: same-hour watch without rejection. Do not invent proxy entries for non-rejections; report their subsequent raw directional excursions from the *next M5 open following W* only as a separately labelled comparison.

## Integrity / evaluation
Use previously verified CLEAN source files, approved dates and event hashes. DEV, VAL, OOS partitions untouched. Note OOS already descriptively explored in Stage 7A/7B, and BID→MID basis shift; this is not a pristine independently held-out test. Do not tune definitions on OOS. Audit at least 20 raw event windows including gaps, tie candles, cross-hour DST, mixed BUY/SELL and repeated pierces. Return event counts, each funnel denominator, counts of CENSORED, AMBIGUOUS and UNRESOLVED, and difference vs no-rejection controls. Never use future outcomes as features.

## Safety
Read-only detached research worktree. No trading, no broker access, no AutoBot production changes, no NMS V3 edits, no standalone M5 BB Bounce edits, no service restarts. Declare blocked if verified historical inputs unavailable.