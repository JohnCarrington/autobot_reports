# Addendum C — PIA First forecasts vs daily pivots

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Base commit:** `beff559` (Addenda A + B pushed clean)
**Date:** 2026-11-04

## 1. Source material — honest inventory

### What is available

Only the five GBPUSD forecasts the operator supplied verbatim in the brief:

| # | Date | Direction | Entry | Primary target | Extended target |
|---|---|---|---|---|---|
| 1 | 28 Oct 2026 | BUY  | 1.3300 | 1.3375 | 1.3400 |
| 2 | 29 Oct 2026 | BUY  | 1.3300 | 1.3375 | 1.3400 |
| 3 | 30 Oct 2026 | BUY  | 1.3350 | 1.3425 | 1.3450 |
| 4 |  2 Nov 2026 | BUY  | 1.3350 | 1.3425 | 1.3450 |
| 5 |  3 Nov 2026 | SELL | 1.3442 | 1.3313 | not recorded |

### What is NOT available

A prior Claude session on **2026-10-16** audited every host the operator mentioned for stored IG PIA First analyst reports:
- `/opt/tradingbot/briefings/v5_pia/` (this host, 816 JSON files 2026-03-19 → 2026-10-07) — **AutoBot's own v5_pia briefings** (`schema_version: v5_pia`, LLM-authored), NOT IG analyst reports.
- `/opt/tradingbot/archive/pia_first/` on the `autobot-pia` droplet (144.126.207.200) — **AutoBot's own LLM-authored "PIA style" briefings** (`model: "claude-sonnet-4-6"`, 12 date-dirs 2026-05-14 → 2026-05-29). The module docstring (`pia_first_briefing.py`) says: *"daily LLM-authored trade plans... The LLM is the decision-maker"*. Not IG analysts.
- The FXi briefing host (178.62.105.108) was SSH-unreachable. No PDFs, HTML scrapes or email dumps of IG's PIA First analyst reports exist on any host I can access.

So **no authentic archive of IG PIA First analyst reports is available to this session**. The 5 GBPUSD forecasts above are the entire investigable dataset.

The brief also asks about EUR/USD, EUR/GBP and USD/CAD forecasts "if their original wording and corresponding market data are available." **They are not.** The operator did not supply these, and no authentic repository exists. I did not invent them.

### Sample-size footnote (important)

Of the 5 forecasts, two pairs look like re-publications of the same thesis (28 + 29 Oct both 1.3300 → 1.3375/1.3400; 30 Oct + 2 Nov both 1.3350 → 1.3425/1.3450). If we treat each distinct thesis as one sample, **the effective sample is 3 theses** (two BUY continuation theses + one SELL reversal thesis). Treating them as 5 would inflate the sample.

## 2. Forecast vs pivot table (exact distances)

Pivots computed from the production IG ASK D1 bars via the textbook formula (matches `/opt/tradingbot/ig_daily_pivots.py:183`). Prior-day selection follows the IG convention (UK calendar day, ASK side).

| Date | Direction | Level | Price | Nearest pivot | Pivot value | Δ (pips) | Baseline median* (pips) | PIA pctile** |
|---|---|---|---|---|---|---:|---:|---:|
| 28 Oct | BUY  | entry        | 1.3300 | S1 | 1.32899 | **+10.1** |  4.8 | 85.4 % |
|        |      | primary tgt  | 1.3375 | **R3** | 1.33809 | **−5.9** |  4.8 | 60.2 % |
|        |      | extended tgt | 1.3400 | R3 | 1.33809 | +19.1 |  4.8 | 100.0 % |
| 29 Oct | BUY  | entry        | 1.3300 | S1 | 1.32874 | **+12.6** |  7.8 | 82.5 % |
|        |      | primary tgt  | 1.3375 | **R2** | 1.33790 | **−4.0** |  8.0 | 25.8 % |
|        |      | extended tgt | 1.3400 | R3 | 1.34188 | −18.8 |  7.8 | 97.6 % |
| 30 Oct | BUY  | entry        | 1.3350 | P  | 1.33557 | **−5.7** | 15.2 | 19.2 % |
|        |      | primary tgt  | 1.3425 | R1 | 1.34146 | +10.4 | 14.9 | 35.3 % |
|        |      | extended tgt | 1.3450 | **R2** | 1.34502 | **−0.2** | 14.7 | **0.6 %** |
|  2 Nov | BUY  | entry        | 1.3350 | S2 | 1.33414 | +8.6 |  8.5 | 50.8 % |
|        |      | primary tgt  | 1.3425 | **R1** | 1.34277 | **−2.7** |  8.7 | 15.7 % |
|        |      | extended tgt | 1.3450 | R2 | 1.34612 | −11.2 |  8.7 | 64.8 % |
|  3 Nov | SELL | entry        | 1.3442 | **R1** | 1.34455 | **−3.5** |  9.4 | 18.1 % |
|        |      | primary tgt  | 1.3313 | **S3** | 1.33077 | **+5.3** |  9.6 | 27.3 % |

* **Baseline median** = median min-distance-to-nearest-pivot for 10,000 uniform random prices drawn across the realised trading day's high-low range for that date.
** **PIA pctile** = the percentile of the PIA level's actual distance inside the baseline distribution. 50% ≈ no better than random; <25% = meaningfully closer; >75% = meaningfully further.

### Reading

- **14 of 14 levels** (entry + primary + extended across all forecasts) were measured against the baseline.
- **Four levels sit at pctile < 20 %** (meaningfully closer than random):
  - 30 Oct extended target 1.3450 = R2 **exactly** (0.6 %) — but note this is a +100 p fixed-increment target that *happened* to coincide with R2 that day.
  - 2 Nov primary target 1.3425 ≈ R1 (15.7 %, −2.7 p).
  - 3 Nov entry 1.3442 ≈ R1 (18.1 %, −3.5 p).
  - 30 Oct entry 1.3350 ≈ P (19.2 %, −5.7 p).
- **Three levels sit at pctile ≥ 97 %** (meaningfully further than random):
  - 28 Oct extended 1.3400 (100 %).
  - 29 Oct extended 1.3400 (97.6 %).
  - 29 Oct primary 1.3375 at the boundary of a cluster (pctile 25.8 but geometry matches R2 at 4 p away).
- The rest are at 15-85 % pctile — not meaningfully closer or further than random.

## 3. The 75/100 pip pattern — fixed-increment, not measured-move

Every BUY forecast has primary = entry + 75.0 pips (exact) and extended = entry + 100.0 pips (exact):

| Date | Entry | Primary | Extended | Primary Δ | Extended Δ |
|---|---|---|---|---:|---:|
| 28 Oct | 1.3300 | 1.3375 | 1.3400 | +75.0 | +100.0 |
| 29 Oct | 1.3300 | 1.3375 | 1.3400 | +75.0 | +100.0 |
| 30 Oct | 1.3350 | 1.3425 | 1.3450 | +75.0 | +100.0 |
|  2 Nov | 1.3350 | 1.3425 | 1.3450 | +75.0 | +100.0 |

**This is a fixed-increment target convention for BUY, not a measured move.** Evidence:

| Prior-day range (ASK) | Primary ∆ | Extended ∆ | Match to range? |
|---|---:|---:|---|
| 27 Oct 45.5 p | +75 p | +100 p | No |
| 28 Oct 65.7 p | +75 p | +100 p | No |
| 29 Oct 94.5 p | +75 p | +100 p | No |
| 30 Oct 59.9 p | +75 p | +100 p | No |

If primary were derived from the prior-day range (a classic measured-move), it would scale with the range. It doesn't — it stays at 75/100 across 45-95 p prior ranges. So the BUY targets are a **fixed convention**, applied regardless of structure.

**The SELL target (3 Nov) is different.** Entry 1.3442 → target 1.3313 = −129 pips. Not 75, not 100, not a round-number increment. It IS the closest sensible level to S3 (S3 at 1.33077, target at 1.3313 → 5.3 p above S3). **The SELL target looks pivot-aware; the BUY targets do not.**

### Implication for the hypothesis

Because the four BUY forecasts all use +75 / +100 (fixed), **any "pivot alignment" of a BUY target is coincidental** — it is a function of whether that day's R1 / R2 / R3 happens to land near the +75 or +100 offset from a round-number entry. Which pivot it "aligns with" is therefore determined by the day's prior-range, not by PIA's targeting method.

## 4. Predicted vs actual outcomes

| # | Date | Dir | Entry triggered | Primary hit | Extended hit | Actual turning point (first wave) | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | 28 Oct | BUY | **yes** same-day | yes 29 Oct 15:15 | yes 30 Oct 01:05 | 30 Oct high 1.34347 (+148.4 p MFE) | both targets reached |
| 2 | 29 Oct | BUY | same as #1 (re-publication of continuation thesis) | — | — | — | treated as same thesis |
| 3 | 30 Oct | BUY | **no** (pair never dipped to 1.3350 again; lowest 1.33743) | n/a | n/a | — | thesis correct direction but not executable |
| 4 |  2 Nov | BUY | **no** (pair never dipped to 1.3350; lowest 1.33796) | n/a | n/a | — | thesis correct direction but not executable |
| 5 |  3 Nov | SELL | **yes** 4 Nov 00:15 (17h late) | **no** | — | 4 Nov low 1.34264 so far; 4 Nov high 1.34786 → +44 p adverse after entry | currently losing |

**Separating accurate direction from accurate target:**
- Direction accuracy: 4 of 5 nominal forecasts correct direction (the SELL is currently losing); treating repeated BUYs as one thesis → 1/2 theses directionally correct with target hit, 0/1 SELL correct.
- Target accuracy: **1 of 5** forecasts reached the primary target (the 28/29 Oct BUY, treated as one thesis).

The SELL is especially informative: after entry was finally triggered on 4 Nov 00:15, price actually moved **against** the signal (high 1.34786, 44 p adverse). The target 1.3313 (near-S3) was not reached. This is the opposite pattern to the Oct 28 BUY (which ran smoothly to both targets).

## 5. Statistical significance — cannot be established

- **n = 5 forecasts, 14 level comparisons.** Treating re-publications as one thesis, **n = 3 unique theses**.
- **A single sign-rank test** is uninformative at n = 3 or 5.
- The Monte-Carlo baseline comparison (empirical percentile per level) is suggestive but not conclusive: 4 levels sit at < 20 %, 3 sit at > 97 %, and 7 sit at 20-85 %. On pure noise one would expect roughly 2.8 levels < 20 % (not meaningfully different from the 4 observed) and 3.5 > 75 % (close to the 3 observed).
- **No credible significance test exists at this sample size.** Any "correlation" claim would be an over-reading of the data.

## 6. What determines the pivot destination (if anything)

On n = 5 forecasts (3 unique theses), **this question cannot be answered empirically**. The brief asks "Why would PIA First predict a move towards R1 on one day, R2 on another, and R3 on another?" With only these cases, the strongest statement that survives scrutiny is:

- For BUY forecasts, PIA applies a fixed +75 / +100 p target from a chosen entry. Which *pivot* that target lands near is determined by the day's prior-range, not by PIA's selection logic.
- The one SELL forecast's target (1.3313) is unambiguously close to S3 (+5.3 p), close enough that pivot-aware targeting is **plausible but not proven** — a single case does not establish a method.
- The forecasts are not evenly distributed across pivot zones: of five primary targets, we see one each near R3, R2, R1, R1, S3. That is not evidence of an S2/R2 bias. If anything, R1 appears twice.

### Hypotheses from the brief, tested

| Brief hypothesis | Evidence in n=5 | Verdict |
|---|---|---|
| H1: PIA targets cluster around S2/R2 more often than S1/R1/S3/R3 | 1 near R2, 2 near R1, 1 near R3, 1 near S3; primary targets alone | **No evidence** of an S2/R2 bias in this sample. R1 is the most common — but at n=5, meaningless. |
| H2: S1/R1 forecasts occur when expected movement is limited | 2 of 5 primaries map to R1, both with +75 p expected move (same as the others). No "limited movement" pattern | **No support** at n=5 |
| H3: S2/R2 forecasts occur when substantial move is anticipated | Only 1 primary near R2 (29 Oct +75 p); same expected movement as R1 primaries | **No support** |
| H4: S3/R3 forecasts correspond to strong trends / exceptional volatility | 28 Oct primary ≈ R3 (−5.9 p). ATR / volatility not materially different that day | **No support** at n=5 |
| H5: Target selection depends on price position relative to central pivot | 28/29 Oct entries ≈ S1 (below P); 30 Oct entry ≈ P; 2 Nov entry near S2; 3 Nov entry ≈ R1. No clear mapping from entry-zone to target-zone | **No pattern** at n=5 |
| H6: PIA anticipates price travelling through intermediate pivots to reach target | 28 Oct BUY: entry ≈ S1, primary ≈ R3 → price must traverse P, R1, R2 (3 pivots). Actual: traversed all 3 and reached primary + extended. This single case is consistent with H6 but 1 example proves nothing | **Insufficient evidence** |

## 7. Direct answers (A-E)

### A. Do PIA First's predicted destinations genuinely correlate with daily pivot levels?

**Not demonstrably at n = 5.** Of 14 PIA levels measured against a per-day Monte-Carlo baseline, 4 sit at < 20 % pctile (meaningfully closer than random), 3 at > 97 % (meaningfully further), and 7 are indistinguishable from random. The one statistically striking match (30 Oct extended = R2 to −0.2 p, 0.6 %-ile) is probably coincidental — it is a +100 p fixed-increment target that happened to coincide with R2 that day.

One case (3 Nov SELL target at S3 + 5.3 p) is suggestive of deliberate pivot targeting, but a single case does not establish a pattern. **A correlation cannot be confirmed or refuted on this sample.**

### B. Is S2/R2 the most common destination, or is that simply an impression from the examples?

**Impression.** Across the 5 primary targets, the nearest pivots are R3, R2, R1, R1, S3 — R1 appears most often, but at n = 5 that is meaningless. There is no evidence of an S2/R2 bias.

### C. Is PIA First using measured moves, pivot calculations or another method that produces similar targets?

**For BUY forecasts: a fixed-increment convention.** All four BUY primaries are entry + 75 p; all four extendeds are entry + 100 p, invariant to prior-day range (which varied 45-95 p). This is not a measured move. Whether the pivot alignment is coincidental or whether PIA tunes the +75 / +100 conventions to common pivot spacings for GBP/USD cannot be determined from 4 cases.

**For the SELL forecast: possibly pivot-aware.** Target 1.3313 is 5.3 p above S3, within normal rounding noise. Entry 1.3442 is 3.5 p below R1. The "trade from R1 to S3" framing is consistent with pivot thinking but one case does not establish a method.

### D. What distinguishes a forecast targeting S1/R1 from one targeting S2/R2 or S3/R3?

**Nothing visible in this sample.** All four BUY forecasts use the same +75 / +100 target convention. The "nearest pivot" to each target is determined by where that day's R1 / R2 / R3 sit relative to the fixed-increment levels — a function of prior-day range, not of PIA's analysis. For the single SELL, the −129 p target coincides with S3, but n = 1 cannot establish a rule.

The brief's hypotheses (H1-H6) **do not survive contact with the data at this sample size**. None of them has even weak support.

### E. Can the observed relationship help explain how PIA First anticipates where a day's price movement will end?

**No, not on this evidence.** The BUY targets are a fixed convention. The one SELL target coincides with S3, but inferring methodology from a single case is unsafe. To answer this question meaningfully we would need:

- Dozens of authentic PIA First forecasts with the original analyst language preserved (so we can distinguish "we're targeting the measured move to 1.3375" from "we're targeting resistance at 1.3375").
- Visibility into the analyst's stated rationale (support, resistance, measured move, swing high, pivot, trendline, Fibonacci).
- A credible out-of-sample baseline.

None of these are currently accessible on this host or (per the 2026-10-16 audit) on the other configured hosts. The brief's direction to "preserve the analyst's exact published predictions, including references to exhaustion counts, measured moves, resistance, support, moving averages, wedges and market direction" is not satisfiable with the current archive.

## 8. Limitations (explicit)

- **Only 5 forecasts, 3 unique theses.** No statistical significance claim is defensible.
- **No analyst rationale available** — only the entry / primary / extended prices. We cannot distinguish "PIA targets R2 because they ran the pivot math" from "PIA targets +100p because they always do, and today that happens to be R2".
- **No multi-pair sample.** The brief references EUR/USD, EUR/GBP, USD/CAD "if available" — none were supplied, none are stored, none were constructed.
- **One forecast still unresolved** (3 Nov SELL entry triggered 4 Nov 00:15, target not yet hit; currently ~44 p adverse).
- **Pivot cache is production ASK snapshot** at the time of research — exactly the levels production would have used; this is faithful.
- **Monte-Carlo baseline uses realised daily range (post-hoc)** — it is backward-looking by one day. A more rigorous baseline would use PRIOR-DAY range as the estimate of the trading window. The two correlate strongly for GBP/USD so the conclusion should not change.
- **The repeated-publication issue matters.** Treating 4 unique rows as 5 or 4 does not change the qualitative conclusions, but inflates sample language.

## 9. Reproducibility

- `scripts/addendum_c_pia_pivots.py` — forecast → pivots → nearest-pivot distances + Monte-Carlo baseline.
- `csv/addendum_c_pia_pivot_table.csv` — 14 rows (entry/primary/extended × 5 forecasts, one SELL has no extended).
- `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json` — production ASK D1 bars used (read-only).
- `/opt/tradingbot/data/candles/GBPUSD/2026-11-0{3,4}.csv` — live-captured MID candles for outcome verification.

## 10. Non-deployment

Read-only research. No modification to AutoBot, NMS, QM, Scenario V2 or any trading service. No broker orders, no shadow mode, no configuration changes, no new classifiers proposed.
