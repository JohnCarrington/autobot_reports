# Scenario V2 — entry quality & directional-accuracy analysis

**Status:** READ-ONLY research. No strategy changes authorised.
Simulations reproducible via `scripts/entry_quality_analysis.py` and
`scripts/entry_alternatives.py`.

**Companion deliverables:** `EXECUTION_COVERAGE_AUDIT.md`,
`SCENARIO_20261103_CASE_STUDY.md`, `data/ENTRY_ALTERNATIVES_COMPARISON.csv`.

---

## 1. Executive conclusion

Scenario V2's **directional calls have modest but real predictive
signal** over 15–60 minute horizons, yet its **entry mechanism and
target geometry convert that signal into net-negative trade
economics**. Across 14 actionable scenarios (publication VALID + full
structured proposal + direction-correct geometry) over 2026-10-23 →
2026-11-03:

| Metric | Value |
|---|---|
| Directional accuracy at 60 min (MFE > MAE) | **9/14 = 64 %** |
| Initial R:R median | **0.68** (mean 0.95) |
| Scenarios with initial R:R < 1.0 | **10 of 14 (71 %)** |
| Pips of favourable movement BEFORE entry (p2e) median | **12.9** |
| Current breakout entry net pips (ex spread) | **−44.5** across 10 trades |
| Current breakout net pips (with 2.8 p round-trip spread) | **−72.5** |
| Breakout + "R:R ≥ 1.0" filter net pips (same spread) | **+7.6** across 4 trades |

**Headline:** V2 systematically waits for a ~13-pip in-direction
breakout before firing — i.e. it enters AT the median of the move it
was supposed to predict — with a target typically closer than the stop.
Both choices together make 60 % of its actionable proposals negative-
expectancy before any execution noise.

Separate from this analysis, the 40-row execution window is also
silently losing 4 of 5 valid OPENs today (see `EXECUTION_COVERAGE_AUDIT.md`).
**Fixing coverage without fixing geometry/entry would increase trade
count at today's unfavourable economics.** Priority ordering is
discussed in `RECOMMENDATIONS.md`.

---

## 2. Methodology & sample

### 2.1 Universe

- `scenarios_shadow.jsonl`, 439 revisions across 24 unique scenario
  IDs, 2026-10-23 → 2026-11-03.
- Candle stream: `research/live_obs/journal/snapshots.jsonl` M5 bars
  (same stream the AI consumed).
- "Actionable" filter: scenario has a `trade_proposal` with resolvable
  `entry_price` + `stop_price` + `target_price`, `publication_decision
  = VALID`, direction-correct geometry (BUY: stop<entry<target).
- 14 of 24 scenarios survived the filter.

### 2.2 Metrics

- **First directional prediction:** first revision with a BUY/SELL
  primary opportunity.
- **First-READY:** first revision satisfying the actionable filter.
- **p2e (pips to entry at first-READY):** signed distance from the
  market close at first-READY to the proposed entry, in the trade's
  direction. Positive = entry is beyond current price (breakout).
- **R:R:** `|target − entry| / |entry − stop|`.
- **Directional MFE/MAE at horizon H:** MFE and MAE in pips from the
  market close at first-READY to the end of a window H minutes later.
  "MFE > MAE" is interpreted as the direction holding (not a trading
  claim).

### 2.3 Non-goals

- Not optimising parameters.
- Not proposing a strategy change.
- Not simulating live costs with contemporaneous bid/ask — spread is a
  flat 2.8 p round-trip assumption (operator should treat net figures
  as directionally correct, not absolutely accurate).
- Not re-sampling multiple revisions as independent trades (one row
  per scenario_id throughout).

---

## 3. Directional accuracy (reasoning independent of entry)

Measured on 14 actionable scenarios from market close at first-READY:

| Horizon | n | MFE median | MAE median | MFE > MAE count |
|---|---|---|---|---|
| 15 min | 14 | +3.8 p | +3.7 p | 7 of 14 (50 %) |
| 30 min | 14 | +6.0 p | +4.8 p | 8 of 14 (57 %) |
| 60 min | 14 | +9.3 p | +6.0 p | 9 of 14 (64 %) |

**Observation.** At 60 min the predicted direction wins on
favourable-vs-adverse excursion in 64 % of cases, with median MFE
~1.5× median MAE. That is NOT a trading edge on its own (MFE is a
hypothetical best fill, not an achievable one), but it is above
coin-flip and significant enough that **a competent entry mechanism
could extract it**. The current entry mechanism does not.

---

## 4. Entry geometry — the central defect

### 4.1 Reward distribution

Initial reward (target−entry) across 14 actionable scenarios:
`min 5.3, median 19.4, mean 19.8, max 31.9` pips.

Initial risk (entry−stop): typically 15–30 pips.

**R:R summary:**

| R:R band | Count | Share |
|---|---|---|
| < 0.5 (reward much smaller than risk) | 6 | 43 % |
| 0.5–0.99 | 4 | 29 % |
| 1.0–1.49 | 2 | 14 % |
| ≥ 1.5 | 2 | 14 % |

The strategy's structural targets are often the nearest named level
(SWING_H, R00, BB_U). Entries are placed above/below current price for
breakout confirmation. The combination forces reward to be whatever is
left between the breakout trigger and the next level — often < 10 pips
— while stops are structural and much larger.

### 4.2 Distance travelled before entry

p2e (pips the market needs to travel before the entry trigger fires)
at first-READY: `min −7.7, median 12.9, mean 13.5, max 53.5` pips.

Of 14 actionable scenarios, 10 have p2e > 0 at first-READY — i.e. the
AI is already waiting for a 13-pip breakout before it is willing to
act. Combined with the stop placed ~20 pips below entry, the entry
fires AT or near the median favourable excursion the strategy itself
predicted (median MFE at 60 min = 9.3 p). The remaining room to the
target is then typically < 10 pips.

**This is "buy the top / sell the bottom" by construction.** The
directional reasoning may be right; the execution rule converts it
into a late entry near the exhaustion of the move.

### 4.3 Revision drift

Across all 439 revisions, entries migrate progressively **towards
current market** as price retraces: see
`data/revision_drift.csv`. Example: `e1c03cad64fa6574` BUY entries
drift from 13427 (rev 5) → 13414.5 (rev 19, lowest) → 13428.5 (rev 33,
after breakout) over 4 h. Target stays largely fixed at the structural
level (SWING_H 13427.15). The result:

- When price retraces, the AI drops entry closer to market, improving
  R:R momentarily (rev 19: R:R 1.04).
- When price then breaks out, the AI chases the breakout and R:R
  collapses again (rev 33: R:R 0.09).

Mechanistically this is "the AI keeps revising the entry to maintain
breakout confirmation" — which guarantees the entry fires near a local
high (BUY) or low (SELL), not before the move.

---

## 5. Alternative entry mechanisms

`scripts/entry_alternatives.py` simulates five fill rules over the
same 13 actionable scenarios (one scenario rejected on geometry
pre-check during the alternative run — `e1c03cad64fa6574` is included
in the main table but a slightly stricter geometry gate in the
alternative script dropped one earlier dataset row). All use identical
stop and target from the proposal. Spread: 1.4 p half, 2.8 p
round-trip. Full CSV in `data/ENTRY_ALTERNATIVES_COMPARISON.csv`.

| Mechanism | Trades | Fills | Closed | Targets | Stops | Win % | Gross | **Net** | Mean |
|---|---|---|---|---|---|---|---|---|---|
| M1 Current (close-above-entry breakout) | 13 | 10 | 10 | 4 | 6 | 40.0 | −44.5 | **−72.5** | −4.5 |
| M2 Immediate at first-READY | 13 | 13 | 12 | 2 | 10 | 16.7 | +8.8 | **−24.8** | +0.7 |
| M3 First M5 close in direction | 13 | 13 | 12 | 2 | 10 | 16.7 | −38.6 | **−72.2** | −3.2 |
| M4 Pullback then direction | 13 | 13 | 11 | 2 | 9 | 18.2 | −24.5 | **−55.3** | −2.2 |
| M5 Current + require R:R ≥ 1.0 | 13 | 4 | 4 | 2 | 2 | 50.0 | +18.8 | **+7.6** | +4.7 |

**Interpretation:**

- **M1 (current) is the worst.** 40 % win rate but each stop is ~20 p
  and each target is ~10 p, so net −72.5 p over 10 trades.
- **M2/M3/M4** improve the entry price (sometimes dramatically) but
  the stops were sized assuming a breakout-level entry. Entering
  earlier means price often comes back to the stop before continuing;
  win rates collapse to ~17 %, net still negative.
- **M5 — the smallest intervention — flips the strategy to
  net-positive.** Filtering out trades with R:R < 1.0 drops 9 of 13
  proposals; the surviving 4 have the acceptable geometry the system
  should have been producing all along, and both the mid and
  spread-adjusted P&Ls are positive.

### 5.1 Sample-size caveat

n = 13 actionable scenarios is **small**. The M5 result (+7.6 net
over 4 trades) is encouraging but statistically weak. The right next
step is to accumulate 60–100 fills under the correction + coverage
patch and re-run this analysis, NOT to deploy a new entry rule based
on this sample.

### 5.2 Spread sensitivity

The 2.8 p round-trip assumption is session-average retail; actual IG
GBP/USD spread varies 0.9 p (London open) to 2.0 p (NY close) and up
to 5–10 p around high-impact news. Trades with gross < 3 p are at or
below any reasonable spread band and should be treated as noise
regardless of mid-close colour. **M1 has 4 target-hit trades with
gross totals 4.8, 5.1, 12.7, 29.2 — two of those four do not clear a
realistic spread floor.** This is a methodology problem the executor
cannot fix.

---

## 6. Does V2 have predictive value? Verdict:

**Yes, modest but real at horizons ≥ 30 min.** Four independent lines
of evidence:

1. 60-min directional accuracy 64 % (Section 3) is above coin-flip at
   the n=14 sample size (not statistically conclusive but
   directionally supportive).
2. M2 (fill at first-READY, no breakout) shows that if we trust the
   AI's call and enter immediately, trades are **gross-positive**
   (+8.8 p over 12 fills) — the reasoning adds value; the stops don't
   fit the entry.
3. M5 shows that just picking the actionable proposals with
   proper geometry (reward ≥ risk) flips the strategy
   net-positive at modest R:R rules. The signal is there; the
   execution is masking it.
4. The one scenario that executed live today (`e1c03cad64fa6574` rev 7
   BUY) closed on TARGET_HIT — direction was right. Problem was the
   target was 2 p from the entry.

**The predictive value is MARGINAL and spread-fragile.** It is not
"V2 is secretly great; just fix the entry". It is "V2 has a real
signal in a difficult market; the current entry mechanism destroys
most of the signal and the current geometry destroys the rest". A
useful entry alternative that captures the signal is likely to look
like M5 (filter on R:R) OR require methodology changes to the stop
and target placement, not merely a tweak to the trigger rule.

---

## 7. Open questions for the entry-quality follow-up

1. Is the AI's `structural_target` selection biased toward the
   nearest level in the direction of the breakout, independent of
   whether that level has historical reaction?
2. Would a methodology that **requires reward ≥ risk** at scenario
   generation time (not during revision drift) produce fewer, higher-
   quality trades?
3. Does M5 remain net-positive after a run of 60–100 live post-fix
   shadow trades? (Primary follow-up — accumulate the sample before
   deciding.)
4. Session timing — do morning (London-open) proposals have different
   geometry from afternoon ones? Not addressed here; data available in
   `data/revision_drift.csv` for a follow-up.
5. Is the systematic p2e > 0 behaviour driven by scenario_quality's
   publication gate requiring a confirmed breakout, or by
   scenario_reasoner's prompt?
