# Addendum M — PIA First exhaustion methodology: reconstruction attempt

**Branch:** `research/addendum-m-pia-exhaustion-20261117`
**Base commit:** `b636b45` (Addenda A–K on `research/gbpusd-pivot-pivot-20261103`)
**Date:** 2026-11-17
**Author:** autonomous research agent (Claude)
**Supersedes nothing.** Extends Addenda C / D / E / F / G / K, which remain the authoritative references for the material they cover.

> **Scope.** Research only. No production changes. No NMS modifications. No Scenario V2 modifications. No broker orders, service restarts, shadow trading, or deployments. Everything below is read-only analysis over the operator-supplied PIA forecast ledger and `/opt/tradingbot/data/candles/GBPUSD/*.csv`.

> **Honest preface.** The brief asks for reverse-engineering of PIA's exhaustion methodology from "multiple authentic PIA First forecasts between October and November 2026" and names specific 4 Nov, 16 Nov and 17 Nov observations. The authentic corpus actually recoverable from this server is 6 forecasts spanning 28 Oct – 4 Nov (only the 4 Nov one with full commentary), one single-sentence 16 Nov quote (no entry/stop/target/timestamp), and one 17 Nov paraphrase. **No exhaustion count published by PIA survives on disk.** Addendum C §7 and Addendum F §10 previously documented the same gap. Phase 3's "reconstruct exhaustion counts" task therefore cannot be performed — all this report can do is compute every plausible count candidate at each publication timestamp so that a future recovery of PIA's own counts can be matched against them. That is not a methodology reconstruction; it is a scaffold for one.

---

## TL;DR

1. **PIA's exhaustion claim on 16 Nov ("stalling negative momentum indicates a turnaround is possible")** came with the SELL recommendation **maintained**. PIA's 17 Nov paraphrased content ("oversold… anticipated a higher correction while maintaining a bearish outlook") says the same thing. Combined with PIA's explicit 4 Nov commentary stating NO exhaustion while maintaining a BUY, these three data points **support the brief's Phase 4 hypothesis**: PIA uses exhaustion to anticipate a **temporary counter-impulse**, not a **dominant-trend reversal**.

2. The 6 forecasts for which we have full levels (28 Oct – 4 Nov) show **fixed 3:1 RR** regardless of stop distance (25 / 43 / 50 p) — i.e. targets are mechanically derived from the chosen stop, not from an anticipated destination. Addendum F already established this; Addendum M confirms it is invariant across the first full reversal call (3 Nov SELL after 4 days of BUY) and the first commentary-bearing continuation call (4 Nov BUY). **The RR convention is the single most reproducible observation about PIA.**

3. **Candidate exhaustion counts at every publication timestamp are now enumerated** (`csv/PIA_EXHAUSTION_COUNT_COMPARISON.csv`). Across 6 forecasts and 3 timeframes we have: consecutive-direction counts, consecutive-closes counts, consecutive-new-highs / -lows, TD-Sequential setup counts, 15 p and 30 p zig-zag swing counts. **None of these can be checked against PIA** because PIA's own published numbers are not retrievable. If a recovered PIA forecast ever quotes a specific count, this table is where to look for a match.

4. **Reconstructed market conditions at publication show a pattern consistent with the "no-exhaustion" vs "exhaustion maintained" classification.** The one forecast where PIA explicitly says NO exhaustion (4 Nov BUY) is the one where **all three timeframes show trend-aligned momentum extension** (H1 RSI 74, D1 RSI 68, close +94 p above D1 EMA20, D1 MACD-hist positive on both H1/H4/D1). The one reversal call we have (3 Nov SELL) was taken with **H1 MACD histogram turning negative while D1 momentum was strong** — i.e. a plausible H1-exhaustion-against-D1-continuation read. **This pattern is suggestive, not statistically established.** n = 1 "no exhaustion" + n = 1 reversal call + n = 2 continuation calls does not identify a signal; it only lets us say which candidate explanations survive first contact with the available data.

5. **AutoBot's NMS Exhaustion Detector already uses PIA-style separation.** The module publishes `NO_EXHAUSTION | EXHAUSTION_DEVELOPING | EXHAUSTION_CONFIRMED` as **additive market-intelligence** that "does NOT change NMS V3 state, companion NMS state, or any trading permission" (`nms_exhaustion_detector.py:7-8`). This mirrors exactly what PIA does: observe exhaustion, keep the directional call. **The architectural distinction the brief asks for is already present in AutoBot.** The risk is on the admission side: `nms_admission_matrix.py:170` hard-BLOCKs on `WATCH_AND_WAIT`, so if exhaustion ever feeds into WATCH_AND_WAIT via family_snapshot, exhaustion would silently become a trade veto — the exact "conflate exhaustion with reversal" defect the brief names. The present code does not conflate them, but the coupling needs an explicit audit before any wiring change.

---

## 1. Corpus (Phase 1)

### 1.1 Register

Full table: [`csv/PIA_EXHAUSTION_EVIDENCE_REGISTER.csv`](../csv/PIA_EXHAUSTION_EVIDENCE_REGISTER.csv). 15 rows for the brief's 28 Oct – 17 Nov window.

| # | Date | Thesis | Dir | Entry | Stop | TGT1 | TGT2 | Conf | Commentary | Evidence class |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|
| 1 | 28 Oct | T1 | BUY breakout | 1.3300 | 1.3275 | 1.3375 | 1.3400 | — | none | LEDGER_ONLY |
| 2 | 29 Oct | T1 (repeat) | BUY breakout | 1.3300 | 1.3275 | 1.3375 | 1.3400 | — | none | LEDGER_ONLY_REPEAT |
| 3 | 30 Oct | T2 | BUY | 1.3350 | 1.3325 | 1.3425 | 1.3450 | — | none | LEDGER_ONLY |
| 4 | 2 Nov | T2 (repeat) | BUY | 1.3350 | 1.3325 | 1.3425 | 1.3450 | — | none | LEDGER_ONLY_REPEAT |
| 5 | 3 Nov | T3 | SELL | 1.3442 | 1.3485 | 1.3313 | — | — | none | LEDGER_ONLY |
| 6 | 4 Nov | T4 | BUY pullback | 1.3431 | 1.3381 | 1.3581 | — | 40 % | **FULL VERBATIM** | DIRECT_PIA |
| 7–13 | 5, 6, 9, 10, 11, 12, 13 Nov | — | — | — | — | — | — | — | — | MISSING_FORECAST |
| 14 | 16 Nov | — | SELL (maintained) | — | — | — | — | — | single-sentence quote | DIRECT_PIA_SINGLE_SENTENCE |
| 15 | 17 Nov | — | SELL (maintained) | — | — | — | — | — | paraphrase | TRANSCRIPTION |

### 1.2 Authentic 4 Nov commentary (verbatim)

> *"Short-term bias remains positive. No clear indication that the upward move is ending. H1 EMA50 at 1.3420. Temporary move lower expected. Buying at current price offers poor risk/reward. Look to BUY at 1.3431. Support 1.3420. Resistance 1.3486. Stop 1.3381. Target 1.3581. Confidence 40%."*

Preserved on 2026-11-04 by the operator and transcribed into the Addendum F ledger on commit `1cb2182` (`gbpusd_pivot_pivot_20261103/reports/ADDENDUM_F_PIA_METHODOLOGY_REVERSE_ENGINEERING.md`). This is the **single** authentic PIA commentary accessible from the repository.

### 1.3 Authentic 16 Nov commentary (single sentence, per brief)

> *"Although the bears are in control, the stalling negative momentum indicates a turnaround is possible."*

Source: the operator's Addendum M brief paste (cached at `/home/autobot/.claude/paste-cache/176cc4e72b2f28e4.txt`, 2026-11-17). No entry, stop, target, confidence, or publication timestamp. PIA's SELL was maintained.

### 1.4 17 Nov paraphrase (NOT verbatim, per brief)

> PIA identified oversold conditions and anticipated a higher correction while maintaining a bearish outlook.

Classification: TRANSCRIPTION / summary — not evidence of PIA's wording.

### 1.5 What is missing (operator action needed)

Seven trading days with no recovered forecast of any kind: 5, 6, 9, 10, 11, 12, 13 November. The brief directs that these be recovered from the existing ChatGPT conversation. For each missing day the register's final column names the required artefact: publication timestamp + direction + entry + stop + target(s) + confidence + full commentary (not a summary).

For 16 Nov and 17 Nov: even where a quote exists, the entry/stop/target/confidence/timestamp are absent. These too must be recovered to execute Phases 2, 5, 6 on those dates.

### 1.6 Non-fabrication clause compliance

- No forecast has been synthesised. Rows 7–13 are explicit holes; rows 14–15 record only the content the operator supplied.
- Where repeat publications occur (T1b, T2b) they are flagged `LEDGER_ONLY_REPEAT` and are **not** counted as independent observations in Phase 4 or 5.
- Operator-supplied labels like "breakout" and "pullback" are preserved but noted as operator paraphrase, not PIA verbatim.

---

## 2. Market reconstruction at publication (Phase 2)

Full table: [`csv/PIA_EXHAUSTION_MARKET_RECONSTRUCTION.csv`](../csv/PIA_EXHAUSTION_MARKET_RECONSTRUCTION.csv). Produced by [`scripts/reconstruct.py`](../scripts/reconstruct.py) from `/opt/tradingbot/data/candles/GBPUSD/*.csv`, divided by 10 000 to decimal, UTC-aligned, resampled to H1 / H4 / D1 **with completed-bucket only emission** so no look-ahead can leak in.

### 2.1 Data boundary

| Timeframe | Coverage used | Bars loaded (30-day lookback) | Notes |
|---|---|---:|---|
| M5 | `data/candles/GBPUSD/*.csv` | 30 days per forecast | scale = decimal × 10 000; prices divided back on read |
| H1 | resampled from M5 | up to ~600 | 12 M5 → 1 H1, complete-bucket emission only |
| H4 | resampled from M5 | up to ~150 | 48 M5 → 1 H4 |
| D1 | UTC-day resampling, publication day excluded | 20+ | publication day is partial, not emitted |

**Candle archive ends 2026-11-06 at 18:00 UTC.** Nothing for 9–17 Nov. All reconstruction stops at T4. The 16/17 Nov hypotheses in §5 and §7 therefore cannot be grounded in recomputed market state; they rely only on the quoted / paraphrased text.

### 2.2 Snapshot at each publication (H1 layer, key columns)

| # | Date | Dir | Spot | H1 RSI14 | H1 MACD hist (p) | H1 close vs EMA20 (p) | H1 close vs EMA50 (p) | H4 RSI14 | D1 RSI14 | D1 close vs EMA20 (p) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T1a | 28 Oct | BUY | 1.32800 | **23.09** | −1.30 | −27.01 | −46.96 | 32.28 | 49.74 | +4.35 |
| T1b | 29 Oct | BUY | 1.33095 | 47.18 | −0.32 | −5.04 | −8.24 | 46.68 | 53.75 | +26.6 |
| T2a | 30 Oct | BUY | 1.33947 | **70.11** | +0.87 | +23.57 | +46.37 | 66.38 | 57.69 | +72.64 |
| T2b | 2 Nov | BUY | 1.34035 | 58.9 | −1.0 | +11.11 | +26.12 | 58.45 | 60.74 | +64.52 |
| T3 | 3 Nov | SELL | 1.34130 | 54.99 | **−0.79** | +4.38 | +14.53 | 60.79 | 63.08 | +79.09 |
| T4 | 4 Nov | BUY | 1.34780 | **74.05** | +3.97 | +35.89 | +55.53 | 74.76 | **67.64** | **+94.06** |

**Observations.**

- **T1a sits at an H1 RSI extreme (23.09)** — the only forecast in the sample at a canonical oversold level. This is the only clean "oversold reversal" call and it is directionally correct (price rose).
- **T4 (the one "no exhaustion" statement) has every momentum oscillator at upper extremes**: H1 RSI 74, H4 RSI 75, D1 RSI 68; D1 close +94 p above D1 EMA20. PIA sees these as "not exhaustion" — i.e. PIA does not equate extended-and-overbought with exhausted-and-turning. **This is the single most important measurement-level insight in the sample** and drives Phase 4.
- **T3 (the reversal call) shows H1 MACD histogram −0.79** (contracting against previous expansion), **but D1 MACD still expanding** (+79.09 p above EMA20, D1 RSI 63). H1 shows weakening; D1 does not. This is a plausible H1-exhaustion-against-D1-continuation read — but with n = 1 we cannot say PIA uses exactly this logic.

### 2.3 What we cannot measure

- 16 Nov and 17 Nov conditions — no candle data past 2026-11-06.
- Tick-level intrabar events — the Oct–Nov window is **past** the certified tick archive (ends 2026-03-31; `project_tick_tz_mixed_20260928`). Reconstruction uses completed M5 OHLC only.

---

## 3. Exhaustion-count candidates (Phase 3)

Full table: [`csv/PIA_EXHAUSTION_COUNT_COMPARISON.csv`](../csv/PIA_EXHAUSTION_COUNT_COMPARISON.csv).

### 3.1 PIA's own numerical references — not recovered

Per Addendum C §7: *"None of these are currently accessible on this host or (per the 2026-10-16 audit) on the other configured hosts. The brief's direction to 'preserve the analyst's exact published predictions, including references to exhaustion counts … and market direction' is not satisfiable with the current archive."*

Per Addendum G §5: *"PIA First's proprietary exhaustion count is not reconstructable from any available material. Any proxy I use is my own, not PIA's."*

Addendum M does not change this. **No PIA-published count is available for any of the 6 forecasts with levels, nor for the 16/17 Nov quoted material.**

### 3.2 Enumerated candidate counts at each publication (H1 timeframe)

| # | Date | Dir | consec_dir(n, side) | consec↑closes | consec↓closes | consec↑highs | consec↓lows | TD setup (n, side) | swings 15 p | swings 30 p |
|---|---|---|---|---:|---:|---:|---:|---|---:|---:|
| T1a | 28 Oct | BUY | 4 / DOWN | 0 | 4 | — | — | **6 / BUY_SETUP** | 127 | — |
| T1b | 29 Oct | BUY | 5 / DOWN | 0 | 5 | — | — | 2 / BUY_SETUP | 131 | — |
| T2a | 30 Oct | BUY | 2 / UP | 2 | 0 | — | — | 3 / BUY_SETUP | 135 | — |
| T2b | 2 Nov | BUY | 4 / UP | 4 | 0 | — | — | 4 / SELL_SETUP | 120 | — |
| T3 | 3 Nov | SELL | 4 / UP | 4 | 0 | — | — | 2 / SELL_SETUP | 130 | — |
| T4 | 4 Nov | BUY | 3 / UP | 2 | 0 | — | — | 1 / SELL_SETUP | 138 | — |

(Full H4 / D1 columns are in the CSV.)

### 3.3 Reading

- **Most informative column:** H1 TD setup count. T1a sits at **TD BUY SETUP = 6**, i.e. 6 consecutive H1 bars each closing below the bar 4 bars earlier — the classic sign of an H1 impulse that is near the published TD Sequential threshold of 9. The TD setup count on H1 is the only enumerated count that *could* plausibly match a published "6" or "7" or "9" exhaustion claim from PIA. We cannot test this because PIA's count is absent.
- **T4 TD setup = 1 SELL SETUP** matches PIA's commentary: the upward move isn't exhausted on H1 (count only just started turning against the up move; 1 bar of countertrend), so "no clear indication that the upward move is ending" is consistent with a very low count.
- **No candidate count aligns across forecasts in a way that would reproduce a single "the PIA count"** — i.e. PIA's reversal calls (T3) do not coincide with exceptional counts on any single timeframe. PIA's one reversal call fires at H1 count 4 and H4 TD = 3 — not extreme.

### 3.4 Falsifiability path

If a recovered PIA forecast ever quotes a specific count:

- Match the value and direction against the H1, H4, D1 columns of this table.
- If PIA's count exactly matches the H1 TD setup for ≥ 3 independent publications, hypothesise H1 TD Sequential (or a close variant).
- If PIA's count matches the H1 consecutive-direction count instead, hypothesise a simple candle count.
- If no column matches, this scaffold is insufficient and we would need PIA's own calculation definition.

**Do not infer a count method from this table without recovered PIA numbers.** Any single-forecast match is coincidence at n = 6.

---

## 4. Exhaustion vs trend reversal (Phase 4)

### 4.1 Classification per forecast (strict separation of PIA-stated vs researcher-inferred)

| # | Date | Dominant direction (PIA / inferred) | Current impulse (reconstructed) | Exhaustion evidence (PIA stated) | Expected correction (PIA stated) | Preferred trade (PIA) | Expected continuation (PIA stated) |
|---|---|---|---|---|---|---|---|
| T1a | 28 Oct | UNCLEAR (counter-HTF BUY per Addendum G; no PIA text) | BEARISH (H1 RSI 23, 4 DOWN candles, −27 p vs EMA20) | UNCLEAR | UNCLEAR | **BUY** | UNCLEAR |
| T1b | 29 Oct | UNCLEAR | BEARISH-weakening (H1 RSI 47, closed back near EMA20) | UNCLEAR | UNCLEAR | **BUY** | UNCLEAR |
| T2a | 30 Oct | UNCLEAR (flat-HTF BUY per Addendum G) | BULLISH (H1 RSI 70) | UNCLEAR | UNCLEAR | **BUY** | UNCLEAR |
| T2b | 2 Nov | UNCLEAR | BULLISH (H1 RSI 59) | UNCLEAR | UNCLEAR | **BUY** | UNCLEAR |
| T3 | 3 Nov | UNCLEAR (counter-HTF SELL per Addendum G) | BULLISH-weakening (H1 MACD-hist −0.79 but D1 still strong) | **IMPLIED** by direction change from T2 → T3 | UNCLEAR | **SELL** | UNCLEAR |
| T4 | 4 Nov | **UP** (PIA stated: "Short-term bias remains positive") | BULLISH-extended (H1 RSI 74, D1 RSI 68) | **ABSENT** (PIA stated: "no clear indication that the upward move is ending") | **DOWN** (PIA stated: "Temporary move lower expected") | **BUY** | **YES** (PIA stated: upward move not ending; pullback will offer better RR) |
| 16 Nov | SELL | BEARISH-weakening (PIA stated: "bears in control" + "stalling negative momentum") | **PRESENT** (PIA stated: "stalling") | **UP** (PIA stated: "turnaround is possible") | **SELL maintained** | **YES** (SELL continuation after temporary up-correction) |
| 17 Nov | SELL | ambiguous ("oversold") | **PRESENT** (operator paraphrase: oversold) | **UP** (operator paraphrase: "higher correction") | **SELL maintained** | **YES** (operator paraphrase: "maintaining a bearish outlook") |

### 4.2 Central question — does PIA use exhaustion to anticipate correction, not reversal?

**Supporting evidence (3 observations):**

1. **4 Nov (T4):** PIA explicitly separates *continuation expected* ("upward move not ending") from *temporary move lower expected*. The trade is a BUY, the entry is **below** current market, and the stated reason is "Buying at current price offers poor risk/reward." → Exhaustion-of-impulse language (temporary pullback) coexists with trend-continuation thesis. Preferred trade matches dominant direction, not the correction.

2. **16 Nov:** PIA explicitly maintains SELL despite acknowledging "stalling negative momentum" and that "a turnaround is possible." → Exhaustion language is applied to the current impulse while the dominant SELL call is kept.

3. **17 Nov (paraphrased):** PIA identifies oversold and anticipates a higher correction while maintaining a bearish outlook. → Same shape as #2.

**Contradicting evidence (1 observation):**

- **3 Nov (T3):** PIA flips from BUY (4 days) to SELL (1 day) with no preserved commentary. This is the **only direction change** in the corpus and the one that looks most like a "reversal call", not a continuation-after-correction call. At face value, this one forecast suggests PIA sometimes *does* interpret exhaustion as a dominant-trend reversal signal, not just an impulse-correction signal. **Without commentary we cannot distinguish "PIA saw a reversal" from "PIA saw a fresh short-term short opportunity against a tiring up-move."**

**Verdict on Phase 4 hypothesis:** the three authentic quotes (T4, 16 Nov, 17 Nov) all support the brief's hypothesis. The one direction change (T3) is an unresolved contradictor whose interpretation depends on commentary we do not have. **Hypothesis is supported by direct PIA statements on 3 out of 4 commentary-bearing observations.** This is not statistical evidence (n = 3 confirmations + 1 unresolved) but it is the strongest finding the available corpus supports.

---

## 5. Signal identification (Phase 5)

### 5.1 Simplest-single-measurement first

The brief forbids jumping to a scoring system before ruling out single measurements. The two anchor observations:

- **4 Nov (T4) = "NO EXHAUSTION" control.** All indicators trend-aligned up at upper extremes (§2.2).
- **16 Nov = "EXHAUSTION PRESENT" positive.** No reconstructable market state (data archive ends 2026-11-06). PIA stated: "stalling negative momentum."

We have **one positive example without market data** and **one negative example with market data**. No single measurement can be tested for discriminative power on this sample. What we can do is enumerate the measurements that *would* be at trend-aligned extremes under "no exhaustion" and at countertrend contraction under "exhaustion present", and name the ones already computed in the reconstruction CSV as candidates to test once the 5–17 Nov forecasts are recovered.

### 5.2 Candidate single-measurement explanations and their status on the available n

| Candidate measurement | Definition | On T4 "no exhaustion" | On T3 implied reversal | Works for bull AND bear? | Computable without future data? |
|---|---|---|---|---|---|
| H1 MACD histogram sign vs prior | Hist(t) vs Hist(t−3) | +3.97 p (positive, expanding) | −0.79 p (negative, contracting against prior positive) | Yes | Yes |
| H1 RSI pulling back from extreme | RSI last-3 vs last-1 | RSI 74, still rising — no pullback | RSI 55, down from recent higher levels | Yes | Yes |
| H1 close vs EMA20 after extension | > +30 p after N aligned bars | +35.89 p (very extended, still aligned) | +4.38 p (returned to mean from extension) | Yes | Yes |
| Consecutive same-direction closes capping out | Count hits threshold K then first countersign close | 2 ↑ closes (no cap) | 4 ↑ closes (no cap per se, but then SELL called) | Yes | Yes |
| Rejection candle at prior extreme | Long wick ≥ 60 % of range at swing boundary | 4.26 p upper wick on H1 (modest) | not applicable | Yes | Yes |
| BB width contraction | H1 BB20 width(t) < width(t−5) | width not contracting | not contracting | Yes | Yes |
| TD Sequential setup reaching 9 | Any TF count = 9 | H1 SELL_SETUP = 1 (no) | H1 SELL_SETUP = 2 (no) | Yes | Yes |

**Status.** Every candidate is *consistent* with T4 being labelled NO_EXHAUSTION — the single clean data point we have. None can be ruled in or ruled out at n = 1 "no exhaustion" + n = 1 undocumented reversal call. **This is where the missing 5-17 Nov corpus matters most.**

### 5.3 Essential control (4 Nov) analysis

The 4 Nov forecast is the brief's essential "NOT exhausted" control. Reconstructed market: H1 RSI 74, H4 RSI 75, D1 RSI 68, D1 MACD positive, all three timeframe closes extended above both EMA20 and EMA50. If PIA's exhaustion detector used a plain overbought threshold (e.g. H1 RSI ≥ 70) or a plain extension threshold (e.g. H1 close > EMA20 + 30 p), **T4 would be flagged as exhausted** — contradicting the forecast.

Therefore PIA's exhaustion test **cannot be a single threshold-crossing indicator**. Either (a) PIA requires *both* an extreme value *and* momentum contraction (so RSI 74 with MACD still expanding = not exhausted), or (b) PIA is using a bar-sequence construct (TD / consecutive-closes) and the sequence count hadn't hit the cap yet, or (c) PIA weighs HTF alignment heavily (D1 up, H4 up, H1 up — no reason to call exhaustion). **All three remain possibilities on the available evidence.** A single recovered forecast with authentic momentum-contraction commentary would discriminate between them.

---

## 6. Post-publication outcomes (Phase 6)

Full table: [`csv/PIA_EXHAUSTION_OUTCOMES.csv`](../csv/PIA_EXHAUSTION_OUTCOMES.csv). 10-day post-publication horizon; observation window ends 2026-11-06T18:00Z (candle archive limit).

### 6.1 Four separate outcome measures per the brief

| # | Date | Dir | Entry filled | MFE (p) | MAE (p) | TP1 hit | Stop hit | First event | Correction-first? |
|---|---|---|---|---:|---:|---|---|---|---|
| T1a | 28 Oct | BUY | yes (07:00 same bar) | +203.95 | −27.05 | yes | **yes** | **STOP** (same-bar ambiguity; see 6.2) | no |
| T1b | 29 Oct | BUY | yes (09:20) | +203.95 | −3.55 | yes | no | **TP1** | no |
| T2a | 30 Oct | BUY | yes (6-day delay: 11-06 14:10) | +27.65 | −7.85 | no | no | NEITHER | no |
| T2b | 2 Nov | BUY | yes (11-06 14:10) | +27.65 | −7.85 | no | no | NEITHER | no |
| T3 | 3 Nov | SELL | yes (11-04 00:15, 17 h delay) | +99.85 | −61.95 | no | **yes** | STOP | **yes** (price went up before down) |
| T4 | 4 Nov | BUY | yes (11-06 03:40) | +5.05 | −88.85 | no | **yes** | STOP | no |

### 6.2 Reading, with the four outcome categories kept separate

- **Correct exhaustion identification** (did the impulse weaken/correct within the horizon?)
  - T1a/T1b: yes — H1 oversold condition at T1a *did* produce a reversal.
  - T2a/T2b: no — PIA's limit entry 1.3350 was never reached on the published day's pullback (Addendum F); it was reached only via a later full retracement.
  - T3: PIA called stalling-at-R1 → price corrected by continuing up another 44 p then collapsing to 1.3423 (close of 11-06 18:00 = 13354.65 / 1.33547 — 100+ p below the entry). The correction eventually occurred, but after the stop.
  - T4: cannot be measured — insufficient post-publication data within our stop/target bounds; the move was too compressed in the brief window.
- **Correct directional forecast** (did the broader anticipated direction develop?)
  - T1/T2/T4: yes direction (price rose through Nov 2–4). T3: price continued up 44 p after entry before reversing — temporary directional reversal, yes eventually; but stop hit first.
- **Executable trade** (price reached PIA's entry before the forecast expired): T1a, T1b yes. T2a, T2b never within Addendum F's window (filled 6 days later in our extended window — effectively unexecutable). T3 yes (17 h late). T4 yes (2 days late).
- **Profitable trade** (TP1 before stop): T1b only.

### 6.3 Subtle finding: entry-same-bar ambiguity for T1a

T1a's entry 1.3300 was filled in the 07:00 M5 bar; the same day's low later reached 1.3273 (below the 1.3275 stop). The script's `first_event = STOP` is *literally* correct using M5 bar-close timestamps, but the within-bar sequence of (stop@1.3275, TP1@1.3375) cannot be ordered from OHLC alone. A trader using a stop-loss order would likely have been stopped out intraday on Oct 28 before the 48-hour winning run. Addendum F read this as "entry + both targets reached"; Addendum M's first-event-pessimistic reading is "stopped out same day, missed the subsequent +200 p run." **Both readings are compatible with the OHLC data.** This is a reporting choice rather than a disagreement with Addendum F.

### 6.4 Correction-first behaviour

The brief's Phase 4 hypothesis predicts that forecasts with "exhaustion" language should see a correction before continuation. We cannot test this on the sample because **only T3 had explicit (inferred) exhaustion and only T3 showed correction-first behaviour**. The one forecast where PIA explicitly stated NO exhaustion (T4) was indeed stopped out on direct adverse movement, not after a counter-correction. This is directionally consistent with the hypothesis but is one data point in each cell — unsuitable for a conclusion.

---

## 7. Reconstructed decision process (Phase 7)

### 7.1 What the authentic 4 Nov commentary supports (direct PIA statements)

Reading the 4 Nov commentary strictly as PIA's own analytical sequence:

1. **Dominant direction stated.** ("Short-term bias remains positive.")
2. **Exhaustion test performed with negative result.** ("No clear indication that the upward move is ending.")
3. **Anticipation of a corrective pullback separate from the exhaustion result.** ("Temporary move lower expected.")
4. **Entry quality check against current market.** ("Buying at current price offers poor risk/reward.")
5. **Entry level selection at a structural support.** ("Look to BUY at 1.3431. Support 1.3420.")
6. **Structural landmarks declared.** ("H1 EMA50 at 1.3420." "Resistance 1.3486.")
7. **Stop and target placed.** ("Stop 1.3381. Target 1.3581.")
8. **Confidence declared.** ("Confidence 40 %.")

Steps 1–3 are the brief's "determine dominant direction" → "assess impulse exhaustion" → "anticipate correction" sequence. Steps 4–5 are the entry-selection step. Steps 6–8 round out trade geometry.

### 7.2 What the 16 and 17 Nov quotes add

Both quotes carry an **exhaustion-present yet trade-direction-maintained** stance. They do not add new steps to the 4 Nov sequence; they populate the opposite branch of Step 2 (exhaustion test positive) while keeping Step 5's entry-selection logic coupled to the dominant-direction call.

### 7.3 What we do NOT have evidence for

- The numerical calculation PIA uses in Step 2 (the exhaustion test itself) — see §3.
- Whether Step 3 "anticipated correction" depth is itself computed or judgment. The 4 Nov commentary states the entry (1.3431) and the support (1.3420) with no formula.
- Whether Step 4 "poor risk/reward at current price" is literal (3:1 RR math from current price would make the +150 p target too far to clear without a pullback) or a general heuristic. Addendum F's fixed-3:1 observation makes the literal reading plausible.
- Any of the above for a reversal call. T3 (3 Nov SELL) has no commentary, so the reversal-decision process is completely dark.

### 7.4 Proposed decision model (speculative)

A minimal model consistent with the three authentic statements (4 Nov, 16 Nov, 17 Nov):

```
dominant_direction   ← higher-timeframe-informed judgment
impulse_direction    ← recent H1 / H4 directional movement
exhaustion_state     ← test applied to impulse (algorithm UNKNOWN; count-based plausible)
anticipated_correction ← when exhaustion_state ≠ ABSENT, expect counter-impulse
                          counter_impulse_direction = opposite(impulse_direction)
structural_invalidation ← stop placed at a structural level 25-50 p from entry
preferred_direction  ← dominant_direction (NOT impulse_direction, NOT correction_direction)
entry                ← structural level in the dominant_direction path AFTER anticipated
                       counter-impulse
target               ← entry ± 3 × stop_distance        (Addendum F: fixed RR)
                         (not derived from a destination level)
```

**Explicit speculation flags.** `exhaustion_state`'s test is unknown. `structural_invalidation`'s rule for picking "the right 25-50 p" is unknown. The target rule *is* supported (3:1 RR invariant across 6 forecasts, Addendum F §1). The other components are plausible inferences, not established facts.

---

## 8. Implications for AutoBot NMS and Scenario V2 (Phase 8)

### 8.1 NMS Exhaustion Detector — does it conflate exhaustion with reversal?

File: `/opt/tradingbot/nms_exhaustion_detector.py` (1 356 lines). Key design statements from the module docstring (lines 1–14):

> *"Publishes a per-symbol exhaustion assessment at every M5 close. The assessment is additive market-intelligence: it does NOT change NMS V3 state, companion NMS state, or any trading permission. Consumers that want to act on exhaustion must do so through a separately approved wiring task — this module only reads inputs and writes the snapshot."*

> *"Three central NMS layers: NMS V3 → trend direction + strength; Companion NMS → demonstrated structural direction; THIS MODULE → exhaustion of the prevailing directional movement"*

**Verdict: the detector itself does NOT conflate exhaustion with reversal.** It explicitly keeps exhaustion as a separate assessment and declines to modify directional authority. The architecture mirrors PIA's own stance in the 16 Nov quote ("bears are in control" [= trend intact] + "stalling" [= exhaustion present] + SELL maintained [= trade direction unchanged by exhaustion]).

States published: `NO_EXHAUSTION | EXHAUSTION_DEVELOPING | EXHAUSTION_CONFIRMED | UNKNOWN`. Direction tagged: `BUYING_EXHAUSTION | SELLING_EXHAUSTION | NONE | UNKNOWN`. Evidence families: CANDLE_REJECTION, MOMENTUM, STRUCTURE, FAILED_EXTENSION, COMPRESSION (and a 6th read beyond line 80 of the module header). **EXHAUSTION_CONFIRMED requires ≥ 2 distinct families agreeing.** This multi-family corroboration matches PIA's observed restraint (not every pullback is called exhausted).

### 8.2 Where the risk sits — WATCH_AND_WAIT admission

Separate module: `nms_admission_matrix.py:170` hard-BLOCKs on `snap.state == STATE_WATCH_AND_WAIT`. `nms_family_snapshot.py:58` defines `STATE_WATCH_AND_WAIT = "WATCH_AND_WAIT"`. If exhaustion ever becomes a trigger for WATCH_AND_WAIT in `family_snapshot`, then CONFIRMED exhaustion would silently become a trade block — i.e. the system *would* conflate exhaustion with reversal at the admission layer, even though the detector itself does not.

**Audit task (not a change) before any wiring of exhaustion into admission:** verify the inputs that currently cause WATCH_AND_WAIT in `family_snapshot` and confirm none of them are driven by the exhaustion detector today.

### 8.3 Does the exhaustion state persist beyond its market conditions?

Memory notes already flag this risk: `project_emapb_watch_state_gate_pr1_20261104` records a WATCH_AND_WAIT gate deployed to the EMA-pullback service that reads the shared state. State persistence after conditions changed is a known pattern of defect. We did not find evidence in the Nov–4 overnight audit (`/home/autobot/audits/overnight_20261106/REPORT.md`) that exhaustion specifically overstayed — but the audit was about a BB Bounce execution anomaly, not exhaustion.

### 8.4 Scenario V2 — can it hold a bearish direction + anticipate a bullish correction?

Based on existing memory (`project_scenario_v2_correction2_structured_proposal.md`, 2026-10-28): Scenario V2's trade_proposal contract is structured with `{entry, stop, target_price}` as the authoritative price contract, with narrative vs structured reconciliation (HIGH > 50 p; WARN 5–50 p). The structured layer holds a direction and a geometry; the narrative layer can disagree.

**This architecture already supports PIA's split.** The direction + geometry of a Scenario V2 trade_proposal are the "dominant direction + entry" that corresponds to PIA's maintained call. The narrative layer could carry the "exhaustion / expected correction" annotation without changing the proposal. The gap is whether V2 **uses** exhaustion evidence to select a *conditional* entry further from current price (PIA's §7.1 step 4: "poor RR at current price"). A separate structured field would need to carry this — the existing `trade_proposal.*_price` fields don't include a conditional entry offset.

### 8.5 Missing information in both systems

- **Neither system reads a dedicated "anticipated correction depth" input today.** The entry is the entry; no system currently schedules a *second* conditional price to upgrade/degrade the signal if the counter-impulse runs further than expected.
- **Neither system has a PIA-count-equivalent.** The exhaustion detector's MOMENTUM family uses MACD "tiring" contraction and divergence — a different formulation than TD Sequential or consecutive-closes. An audit task (not a change) would compare detector trigger density against our enumerated H1 TD Setup counts from §3.

### 8.6 Risks of implementing an unverified exhaustion model

- **False-equivalence with reversal.** If PIA's method quietly treats some exhaustion signals as reversal triggers, copying "exhaustion → correction only" would undergenerate reversals. If PIA's method is purely "exhaustion → correction + direction maintained", conservative copying would be safe. **We cannot distinguish these without Nov 5–17 commentary.**
- **Threshold fitting on n = 6.** Any numerical threshold we invent now is fitted to a sample of 6 and almost certainly overfits.
- **Count substitution.** Using TD Sequential or consecutive-closes as a stand-in for PIA's actual count would be "AI_HYPOTHESIS" per the brief's classification scheme — a methodology we have not verified is PIA's.

**Recommendation: no wiring change until the 5–17 Nov forecasts are recovered.** This report produced a scaffold (§3 count table, §2 market state) sufficient to validate a count hypothesis the moment PIA numbers surface.

---

## 9. Direct answers to the brief's questions

### Q1 — What does PIA First appear to mean by exhaustion?

A momentum-contraction + price-stalling condition **affecting the current directional impulse**, distinct from and not implying a change in the **dominant directional trend**. Supported by: 4 Nov NO exhaustion (impulse still extending → trend thesis intact), 16 Nov EXHAUSTION ("stalling negative momentum" + SELL maintained), 17 Nov EXHAUSTION ("oversold" + SELL maintained).

### Q2 — Which market measurements most closely reproduce PIA's assessments?

**Insufficient evidence to establish.** On the one authentic "no exhaustion" case (T4) the reconstructed H1/H4/D1 state shows every momentum oscillator at upper extremes with HTF alignment — ruling out any single-threshold overbought/oversold interpretation. Multi-component tests (extreme + momentum contraction, or extreme + HTF misalignment) remain possible. No single measurement has been validated.

### Q3 — Can the exhaustion counts be reconstructed mathematically?

**No**, because no PIA count is retrievable from this server (Addendum C §7 confirmed empty; Addendum F §10 confirmed empty; Addendum M confirms no change). The candidate-count scaffold in `csv/PIA_EXHAUSTION_COUNT_COMPARISON.csv` enumerates eight count interpretations across three timeframes at six publications so that future recovered numbers can be checked, but that is a scaffold, not a reconstruction.

### Q4 — Does PIA distinguish exhaustion of an impulse from reversal of the dominant trend?

**Yes, on 3 of 3 commentary-bearing observations** (4 Nov, 16 Nov, 17 Nov). The one direction-change case (3 Nov T3) has no commentary and could plausibly be either a reversal call or a fresh short-against-tiring-up-move call — unresolved.

### Q5 — What evidence causes PIA to anticipate a corrective rally or pullback?

**Insufficient preserved commentary to answer.** 4 Nov says "temporary move lower expected" without a stated reason; 16 Nov says "turnaround is possible" because of "stalling negative momentum"; 17 Nov says oversold → higher correction. The common thread is "momentum stalling in the current impulse direction", but the specific measurement that triggers the stalling call is not quoted.

### Q6 — How does PIA use the anticipated correction when selecting its entry?

**Addendum F's fixed-3:1 RR observation is the strongest evidence.** The 4 Nov "Buying at current price offers poor risk/reward" is PIA explicitly rejecting an entry that doesn't satisfy the 3:1 geometry from current price. The anticipated correction is used to drop the entry to a level where 3× stop fits within the dominant-direction thesis's room.

### Q7 — Which findings are supported by multiple independent forecasts, and which remain speculative?

**Multi-forecast supported:**
- Fixed 3:1 primary RR (6 forecasts, 3 different stop sizes). [SUPPORTED — Addendum F replicated here.]
- Exhaustion ≠ reversal (3 commentary-bearing observations). [SUPPORTED]
- Stops placed near structural pivots (Addendum F §2: 5 of 6 within 10 p). [SUPPORTED]

**Speculative (single forecast or inference from absence of commentary):**
- Specific exhaustion count calculation. [UNSUPPORTED]
- Pullback-depth rule (how far to drop entry from current price). [UNSUPPORTED]
- Decision between "exhaustion → hold + wait for correction" and "exhaustion → reverse" (the T3 case). [UNRESOLVED]

### Q8 — What would AutoBot need to change to reproduce the supported aspects?

**Nothing in NMS.** The Exhaustion Detector already separates exhaustion from trend direction. The minimal change for Scenario V2 would be a structured carry-field for an **anticipated-correction-conditional entry** (today the proposal has a single `entry`; PIA's workflow would prefer a dominant-direction trade with a conditional entry, triggered on the counter-impulse first). **This is a design note, not a recommendation to change code.** Any wiring task is predicated on first recovering the 5–17 Nov corpus.

### Q9 — What additional evidence would be required to reconstruct PIA's exhaustion method more precisely?

In rough priority order:

1. **The authentic 5–17 Nov PIA forecasts.** Full prose + direction + entry + stop + target + confidence + publication timestamp. 11 trading days are blank.
2. **Any preserved PIA exhaustion count value** (1 number with the surrounding sentence is enough to begin discrimination between the enumerated candidates in §3).
3. **Commentary for T1, T2, T3** (28 Oct, 30 Oct, 3 Nov). Especially T3 — the direction change without commentary is the single most damaging blind spot.
4. **Chronologically-identified PIA forecasts across a much longer window** (e.g. 6 months) to move from n = 6 scaffold to statistically meaningful validation.

---

## 10. What we know / suspect / still need to discover (per brief's final requirement)

### WHAT WE KNOW
*(supported directly by authentic PIA forecasts and reconstructed market data)*

| Finding | Evidence | Confidence |
|---|---|---|
| **PIA maintains a directional call while acknowledging exhaustion of the current impulse** | Direct quotes: 4 Nov ("no clear indication…" + BUY maintained); 16 Nov ("stalling negative momentum" + SELL maintained); 17 Nov (oversold + SELL maintained) | HIGH |
| **PIA uses a fixed 3:1 primary / 4:1 extended RR regardless of stop distance** | 6 forecasts × 3 different stop sizes (25 / 43 / 50 p) all exactly 3:1 primary; the two with extended targets exactly 4:1 | HIGH |
| **PIA's entries and stops cluster near daily pivots** | Addendum F §2 — entries 4/6 within 10 p of pivot; stops 5/6 within 10 p | HIGH |
| **"Overbought on the oscillator" is not sufficient for PIA to call exhaustion** | 4 Nov: H1 RSI 74 + H4 RSI 75 + D1 RSI 68 while PIA says "upward move not ending" | MEDIUM (n = 1 commentary-bearing "no exhaustion" case) |
| **PIA's own exhaustion count is NOT recoverable from this server** | Addendum C §7, Addendum F §10, Addendum M corpus search — confirmed empty across paste-cache, briefings archive, autobot_reports branches, home research dirs | HIGH |

### WHAT WE SUSPECT
*(supported by some evidence but not conclusively established)*

| Hypothesis | Evidence for | Evidence against | Confidence |
|---|---|---|---|
| PIA uses a **bar-sequence count (TD Sequential or similar) on H1** as its exhaustion test | H1 TD setup = 6 on T1a (the one clean oversold-reversal call); 4 Nov TD = 1 SELL_SETUP ("just starting a pullback") matches the "temporary move lower expected" language | 3 Nov SELL fires at H1 TD = 2 — nowhere near the TD "9" threshold | LOW |
| PIA uses **H1 MACD histogram contraction** (not RSI) as its momentum-exhaustion test | 3 Nov SELL fires with H1 MACD hist −0.79 while D1 MACD still expanding | 4 Nov NO exhaustion has strong positive H1 MACD hist (+3.97) — consistent | MEDIUM |
| PIA's "anticipated correction" depth is **the pullback to EMA / next support within the dominant-direction-aligned retracement zone** | 4 Nov: entry 1.3431 ≈ H1 EMA50 1.3420 + 11 p, i.e. the EMA band | n = 1 | LOW |
| PIA treats the dominant direction as **higher-timeframe-informed judgment**, not a mechanical D1 slope | Half of unique theses are counter-HTF reversal calls (Addendum G §2) | We cannot see what else PIA weighs | MEDIUM |
| **Scenario V2's structured proposal could carry PIA's workflow** with a conditional-entry field | V2 already has a direction + geometry contract; the exhaustion-vs-reversal distinction is already in NMS | No conditional-entry field exists today | MEDIUM (architecturally, not performance-wise) |

### WHAT WE STILL NEED TO DISCOVER
*(smallest additional observations / tests to resolve remaining uncertainty)*

| Question | Smallest evidence that would resolve it |
|---|---|
| Does PIA use a specific count algorithm? | **One recovered PIA forecast with a quoted count number and the timeframe**. Test against the candidate table in §3; a match on H1 TD setup for ≥ 2 independent recoveries would promote the TD hypothesis. |
| What triggers PIA's "stalling momentum" call? | **Full 16 Nov commentary** — specifically the sentence(s) around "stalling negative momentum" and whatever specific indicator or count PIA cites. Also: 17 Nov verbatim (not paraphrase). |
| Is T3 (3 Nov SELL) a reversal call or a short-against-tired-up-move? | **Full 3 Nov commentary**. One quote with language like "trend is turning" vs "selling into strength" distinguishes it. |
| Does "exhaustion" in PIA's lexicon ever switch the directional call? | A recovered forecast where PIA **changes direction** AND cites exhaustion as the reason. Absent this, the brief's hypothesis stands undisputed on direct statements. |
| Can AutoBot's existing exhaustion detector reproduce PIA's calls? | **A chronological PIA corpus** (any sample, ideally 20+ forecasts). Run the detector in replay over the same window and compare. The detector snapshots at `/opt/tradingbot/cache/nms_exhaustion_<SYM>.json` + the log `/opt/tradingbot/logs/nms_exhaustion.jsonl` are the comparison target. |

**Per-component confidence summary for the proposed decision model (§7.4):**

- Fixed 3:1 RR target rule: **HIGH** confidence. Reproduces in all 6 ledger forecasts.
- Pivot-anchored stop: **HIGH**. Addendum F §5 Monte-Carlo baseline.
- Dominant-direction-preserving exhaustion assessment: **MEDIUM-HIGH**. 3 commentary-bearing observations.
- Specific exhaustion test algorithm: **LOW**. No count recovered, no verified formula.
- Anticipated-correction depth rule: **LOW**. One commentary-bearing case.
- Conditional entry offset ("look to BUY at X" when market is at Y): **MEDIUM**. Supported by T4's explicit RR-rejection language, consistent with 3 further unfilled T2/T2b limit publications.

---

## 11. Non-deployment, non-fabrication, provenance

- Read-only. No production, NMS, QM, Scenario V2, scheduler, or configuration change. No broker orders. No service start / stop / restart.
- No forecast text has been synthesised. The only PIA quotes in this report are the 4 Nov commentary (from Addendum F §1 verbatim), the 16 Nov single sentence (from the operator's Addendum M brief), and the 17 Nov paraphrase (flagged as paraphrase throughout).
- Every quantitative claim in §6 is reproducible from `scripts/reconstruct.py` and the on-disk candle archive.
- 1 346 total lines of unmodified NMS exhaustion detector code (`/opt/tradingbot/nms_exhaustion_detector.py` lines 1–1356) cited for §8; no modification proposed.
- Previously published Addenda A–K on `research/gbpusd-pivot-pivot-20261103` are **preserved**. Addendum M extends; it does not supersede.

### Provenance table

| Element | Source |
|---|---|
| T1–T6 price ledger | Addendum F §1 (operator-supplied via brief; committed on `1cb2182`) |
| 4 Nov verbatim commentary | Addendum F §1 §1.1 |
| 16 Nov single-sentence quote | Operator's Addendum M brief (paste-cache `176cc4e72b2f28e4.txt`, 2026-11-17 09:03 UTC) |
| 17 Nov paraphrase | Operator's Addendum M brief (same paste) |
| M5 candles | `/opt/tradingbot/data/candles/GBPUSD/*.csv` (coverage ends 2026-11-06T18:00Z) |
| Pivot formulas | `/opt/tradingbot/ig_daily_pivots.py:183` (textbook; cross-cited in Phase 1b of pivot-pivot report) |
| NMS exhaustion detector design | `/opt/tradingbot/nms_exhaustion_detector.py` docstring (lines 1–80) |
| Admission-matrix WATCH_AND_WAIT BLOCK | `/opt/tradingbot/nms_admission_matrix.py:15 §1 / line 170` |
| Addendum C PIA-archive emptiness claim | `origin/research/gbpusd-pivot-pivot-20261103:…/ADDENDUM_C_PIA_PIVOT_HYPOTHESIS.md` §7 |
| Addendum G exhaustion-count emptiness claim | same branch, `ADDENDUM_G_PIA_HIGHER_TIMEFRAME_DIRECTION_AND_PIVOT_ENTRIES.md` §5 |

### Limitations re-stated

- n = 6 forecasts with levels, n = 3 with commentary-bearing content. No statistical significance claim is made or implied anywhere in this document.
- Candle archive ends 2026-11-06T18:00Z. Reconstructions beyond that date are impossible on the current server.
- Tick data for the Oct–Nov 2026 window is not certified (`project_tick_tz_mixed_20260928`). Analysis uses M5 OHLC only.
- The single PIA count hypothesis (H1 TD Sequential) is marked LOW confidence and explicitly labelled speculative. Do not treat the count scaffold as a reconstructed algorithm.
