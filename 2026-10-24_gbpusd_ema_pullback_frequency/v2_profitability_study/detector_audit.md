# Detector audit — v1 (2026-10-24, Stage-1) vs frozen v2 rules

**Prepared:** 2026-10-24 (same day as Stage-1 completed)
**Audited artefact:** `../code/detector.py` + its outputs under `../outputs/full_scan/`
**Audit scope:** Does the Stage-1 detector correctly implement the user's authoritative rules as frozen in Stage-2 §1? Which Stage-1 opportunities survive under the frozen rules, and which depend on unresolved definitions?

The Stage-1 study (same researcher, earlier today) is kept in place. This v2 study runs alongside; this audit documents the inherited deltas.

## 1. Confirmed OK in v1 (no change needed)

| Item | Evidence |
|---|---|
| H1 bar derivation from the same M5 series (consistent timeframes) | `detector.py:_finalise_h1` folds 12 M5 bars per hour |
| H1 EMA(8,13,20) and M5 EMA(8,13,21) streaming | `detector.py:EmaState.update` — byte-level cross-check in `../validation_report.md` §3 |
| H1 bar only visible to M5 decisions after it closes (no look-ahead) | `_finalise_h1(now_ts)` fires on hour-rollover BEFORE the current M5 bar is folded in — see loop ordering in `run()` |
| EMA-21 cancellation on **close**, not wick | `pb.direction == +1 and c < e21` / `pb.direction == -1 and c > e21` — wick never cancels |
| H1 EMA 20 warm-up guard (20 bars) | `h1_warm = len(h1_closes_history) >= 20` — prevents cold-start artefacts |
| BUY/SELL symmetry (same code path, mirrored comparison) | observed in output: 6,101 BUY vs 5,606 SELL on 11,707 total — direction-balanced given a slightly BUY-biased 2.75-year sample |
| Target-before-stop AMBIGUOUS flag when both touched in same M5 bar | `_attach_mfe_mae` — AMBIGUOUS rate is 0.26-0.37% depending on pair, which is a sanity-check pass |

## 2. Issues requiring correction in v2

### 2.1 H1 trend qualification is too permissive at the baseline
**v1 behaviour:** The baseline qualification is **ordering + strict-sign-of-1h-slope**. ANY positive 1-h slope magnitude passes (even 0.01 pips/h). The published 11,707-opportunity headline uses this loose qualification.

**Why it matters per frozen rules (§1.1):** The user requires the EMAs to be "clearly sloping" and "clearly separated". A near-zero slope and sub-pip separation do not qualify, even though the ordering is correct.

**v2 fix:** Qualification magnitude thresholds must be sensitivity-tested in bands labelled WEAK / MODERATE / STRONG. The headline "opportunities per day" will be reported per band, and the "clearly sloping/separated" rule is quantified by the user if they choose a band, not by the researcher.

### 2.2 Rejection candle default is a single researcher operationalisation
**v1 behaviour:** Rejection = first M5 bar after an EMA-8 touch where (BUY) `close >= open AND close >= EMA 8`, (SELL) `close <= open AND close <= EMA 8`.

**Why it matters per frozen rules (§1.4):** The user says the rejection candle is "the bullish rejection candle" for BUY — i.e. the FIRST candle moving back in the trend direction. The requirement that `close ≥ EMA 8` was the researcher's addition; without it, a bullish close back inside the EMA band could still arm. v1 may UNDERCOUNT rejections.

**v2 fix:** Report two interpretations side-by-side.
  - **DEFAULT (v1)**: `close ≥ open AND close ≥ EMA 8` (BUY) / `close ≤ open AND close ≤ EMA 8` (SELL). Strict.
  - **LOOSE (v2 new)**: `close ≥ open` (BUY) / `close ≤ open` (SELL). Just the direction of the body; EMA-8 position of close is irrelevant. Loose.
  - Both are run through the full historical scan and both populate the trade-scenarios CSV with a `rejection_mode` tag.

### 2.3 Rearming is "immediate on next touch" — may double-count
**v1 behaviour:** After a confirmed entry OR an EMA-21 close cancellation, the detector returns to disarmed and rearms on the very next bar whose price touches EMA 8. In a tight pullback, this can produce two "pullbacks" in consecutive M5 bars.

**Why it matters per frozen rules (§1.6):** "Do not count repeated touches of EMA 8 during the same unresolved pullback as independent entries." If after an entry the price barely retreats and immediately pushes back, is that a fresh pullback or a continuation of the same one?

**v2 fix:** Report two interpretations.
  - **IMMEDIATE (v1)**: next EMA-8 touch rearms.
  - **STRICT (v2 new)**: after entry/cancel, require price to have CLOSED beyond EMA 13 in the trend direction (BUY: a bar closes `close ≥ EMA 13`; SELL: `close ≤ EMA 13`) before the next EMA-8 touch counts. This models "price resumed the trend and then pulled back again".

### 2.4 Trading-day binning used UTC date, not UK local
**v1 behaviour:** `date_utc = entry_dt.date().isoformat()` — binning on the UTC day. A pullback firing at 2024-01-02 23:30 UTC is tagged `2024-01-02`; at UK local time that is 2024-01-02 23:30 GMT → still `2024-01-02`, so no shift in winter. But during BST (summer), a 23:30 UK bar is 22:30 UTC → still `2024-01-02` UTC, same day. The subtle case: a 00:30 UK (BST) bar is 23:30 UTC previous day. v1 counts it as the previous UTC day. Over 2.75 years with ~1 bar/hour this is a modest reshuffle of counts between adjacent days.

**v2 fix:** Compute the trading date as the UK-local date of entry. This also matters for "attribute realised profit to the date the position closes" (brief §7) — exit UK date is what matters for daily PnL. Both are stored in v2 output.

### 2.5 No executable-fill modelling, no spread accounting
**v1 behaviour:** `entry_px` = `rejection.high` (BUY) or `rejection.low` (SELL), both read from MID candles. MFE/MAE are MID-based. No concept of bid/ask fill, no spread cost.

**Why it matters per frozen rules (§1.5, §6.4):** Realised net pips must subtract the spread, model BUY fills at ASK and SELL exits at BID (and symmetrically), and distinguish the signal reference from the fill price.

**v2 fix:** For each opportunity, store the MID at entry. The scenario engine evaluates:
- `net_realised = gross_mid_move - spread` for both directions
- TP condition on MID: favourable MID move ≥ `TP + spread` (so that realised ≥ TP)
- SL condition on MID: adverse MID move ≥ `SL − spread` (stop fires when BID or ASK — whichever the exit uses — crosses the stop level)
- Explicit scenarios for spread ∈ {0.5, 1.0, 1.5}, labelled.

### 2.6 Horizon handling is informational only — no concept of TP / SL / time exit
**v1 behaviour:** v1 records MFE/MAE at 15/30/60/120-min horizons and target-before-stop touch pairs. It does NOT model what a trader with a 10p-TP + 10p-SL would actually have taken.

**v2 fix:** Full trade-outcome engine (`code/trade_engine.py`): per-opportunity walk forward up to 120 min, exit on first-touch TP, SL, or horizon. Classify AMBIGUOUS (same M5 bar touches both), WIN, LOSS, TIME_EXIT. Each classification carries a realised pip number.

### 2.7 No concurrency model
**v1 behaviour:** Every detected opportunity is counted independently. If two BUY entries fire within 10 minutes of each other, they are both in `opportunities.csv`.

**Why it matters per frozen rules (§6.6):** The user explicitly asks for two concurrency scenarios: A (one position at a time) and B (independent signals).

**v2 fix:** Scenario-level filtering. Scenario A: process opportunities in time order; a new entry is deferred/dropped if a prior position is still open. Scenario B: all independent (= v1 behaviour).

## 3. Issues that are NOT bugs but need user acknowledgement

### 3.1 Candle source provenance (BID vs MID) is undocumented
v1 assumed MID. The code generators in the repo (`candle_builder.py`) do process live MID ticks, but the archived files in `data/candles_ext_v2/` were built pre-TZ-fix (pre 2026-09-28) and the archive has no in-file provenance header. The frozen tick-correction manifest at `outputs/freeze/tick_correction_manifest.csv` is NOT present in this working tree (observed in Stage 1, remains the case in Stage 2).

**Posture:** v2 treats candles as MID and reports every outcome with the explicit "MID + spread/2 execution model" caveat. If the user later confirms the archives are BID, every BUY MFE statistic should be adjusted by +spread/2 (BID candles under-report BUY favourable movement) and every SELL by −spread/2. The direction of the effect, not the magnitude of absolute profitability, is sensitive to this.

### 3.2 "Clearly sloping / clearly separated" numerical thresholds remain unresolved
v2 does NOT pick these on the user's behalf. The slope × separation bins are reported with chronological OOS split and sample-size caveats so the user can see where the signal lives.

### 3.3 Rejection candle intrabar sequencing is unobservable at M5 granularity
When a single M5 bar touches EMA 8, hits a rejection body shape, AND the next M5 bar breaks the high, we have no sub-5-min visibility. v1 and v2 both read the sequence from completed-M5 ordering. This is a hard limit of the available data; tick-level validation is out of scope.

## 4. Reconciliation — which v1 opportunities survive the frozen rules

v1 produced 11,707 confirmed entries under (DEFAULT rejection, IMMEDIATE rearm, no slope/separation magnitude cut). Under v2 the same scan is re-run with the four combinations:

- (DEFAULT rejection × IMMEDIATE rearm) = v1 behaviour (reproduced exactly byte-for-byte to confirm the engine didn't regress)
- (LOOSE rejection × IMMEDIATE rearm) = **more** opportunities (loose rejection admits more bars as rejections)
- (DEFAULT rejection × STRICT rearm) = **fewer** opportunities (strict rearm filters out same-pullback repeats)
- (LOOSE rejection × STRICT rearm) = cross effect

The frozen rules (§1 of Stage 2) do not formally pick between any of these — they are all reasonable interpretations of a user-level description. v2 publishes a per-cell comparison table in `research_report.md` §3.3 so the user can see the sensitivity. **No v1 opportunity is discarded or renamed; v2 is additional, not a replacement.**

### Numerical reconciliation (filled in by `code/reconciliation.py` once v2 engine runs)

See `outputs/scenarios/opportunity_count_matrix.csv` and `research_report.md` §3.3.

## 5. Scope of this audit (and what it is not)

This audit covers only the Stage-1 detector in this working tree. It does not opine on the various production EMA-pullback strategies elsewhere in `/opt/tradingbot/` (`ema_pullback.py`, `gbpusd_ema_pullback.py`), which were explicitly excluded by both Stage-1 and Stage-2 briefs (§1.4 / §11.2).

No v1 opportunity is marked as "invalid" by this audit — v1 is a valid LOOSE-threshold / DEFAULT-rejection / IMMEDIATE-rearm reading of the brief, and all v1 outputs stay in place. v2 adds four well-labelled interpretations and the trade-outcome engine the frozen rules now require.
