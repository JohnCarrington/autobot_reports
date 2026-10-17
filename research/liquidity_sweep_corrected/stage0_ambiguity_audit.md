# Liquidity Sweep — Corrected Research — Stage 0

**Date:** 2026-10-17
**Branch:** `research/liquidity-sweep-corrected-20261017`
**Status:** AWAITING OPERATOR DECISIONS on 3 material definitional ambiguities.
**Mode:** RESEARCH ONLY. Production untouched.

---

## 0. Why this report exists before any code runs

The corrected research brief contains four explicit **STOP** clauses:

> §3  "If the exact historical Daily/H4/H1 classification cannot be reconstructed from existing frozen rules, report the missing definition and STOP that component rather than inventing one."
>
> §7  "If the structural rejection definition is not sufficiently precise to implement, STOP and identify the exact ambiguity. Do not silently choose a definition."
>
> §10 "If the structural objective or stop-buffer rule is not already precisely defined, report the missing definition and do not invent one."
>
> §6A "If no previously agreed threshold [for repeated-test departure] exists, report the ambiguity before implementing the test counter."

A full codebase reconnaissance (five parallel audits, 25 modules read) finds **two** of these components fully specified by frozen production code, **three** that require operator decisions, and **one** (structural exit — spec §10 Model 2) that the brief itself already labels unresolvable without clarification.

This Stage 0 report delivers Deliverable A (Stage 1 test-design discrepancy audit) and the pre-flight ambiguity list required by the brief. It does **not** execute any computation beyond manifest verification. Nothing silently invented.

---

## 1. Deliverable A — Stage 1 test-design discrepancy audit

### 1.1 What Stage 1 actually did

Stage 1 published to the sibling research branch `research/level-arrival-turn-20261017` in this same repo. Head: `56aa146` ("stage1 verdict: no mechanism survives chronological OOS").

The Stage 1 pipeline:

1. **Phase 0 (Stage 0b):** generated **9,349 wick/rejection candidates** from a *pre-selected* candidate heuristic — wick beyond a *ranked* level OR intra-bar high/low crossing + rejection candle closing back inside the Bollinger Band.  (Script: `batch_wick_rejection_stop_full.py`.)
2. **Phases 1–7:** feature audits, taxonomy, session/structural breakdowns — **all computed on the 9,349-row candidate pool**, not on an independent event population.
3. **Phase 8:** forward +30/−12 test on 7,497 executable rows (loader was repaired mid-run — see `authorized_data_io.py`, commit `d4b8167`).
4. **Phase 9:** chronological OOS on 2026-Q1 (57 days, 563 trades).

**Stage 1 headline:** Mechanism D (sustained-then-fail) was the only in-sample positive class (+0.66 to +0.84 pips/trade DEV & HOLDOUT); flipped to **−0.74 pips/trade** on OOS. Day-clustered bootstrap, Bonferroni-adjusted α=0.0017 — **no mechanism survives**.

### 1.2 Discrepancies against the corrected spec

| # | Discrepancy | Impact |
|---|---|---|
| **D1** | **Pre-selected candidate pool** (9,349) rather than scanning every eligible M5 approach to every structural level chronologically | Entire population bias: Stage 1 can only validate the *wick/rejection* heuristic, not the strategy the operator intends to test. Approaches that penetrate and close back without a wick-shape rejection on the *same bar* are invisible to Stage 1. Agent 1 full audit: "Stage 1 can only tell us whether the wick/rejection *shape* paid; it cannot tell us whether sweeps as a trading sequence pay." |
| **D2** | **BID basis for DEV/HOLDOUT, MID basis for OOS** (forced by data availability: `candles_ext_v2` = BID 2024-01-01 → 2025-12-31; `candles` = MID 2026-01-01 →) | Stage 1 OOS validation is not a true chronological held-out test — the measurement basis changed. OOS prevalence of Mechanism B jumped 23.2% vs DEV 3.8%; Mechanism C 5.8% vs 0.5%. Likely bar-high/low crossing artefact, not a market change. **Corrected spec §11 explicitly requires investigating this** and §12 forbids claiming clean OOS validation when the measurement basis changes. |
| **D3** | **Pool reuse for feature engineering AND out-of-sample test** — Phases 1–7 discovered features in the 9,349-row pool; Phase 8/9 tested the resulting mechanism labels on the same pool | Classical multiple-testing / adaptive-overfit risk. Day-clustered Bonferroni α=0.0017 is a partial mitigation, but structural leakage remains. |
| **D4** | **Lagged ZigZag(30) as TRUE label** — a reversal is TRUE only after price has already moved 30 pips, so sub-30p real reversals contaminate FALSE class | Bimodal label; feature AUC estimates are optimistic. |
| **D5** | **Mechanism D direction asymmetry** flagged but not pre-registered: D SELL +1.71 p/trade; D BUY −3.40 p/trade. Stage 1 refused to validate | Correct refusal; not a Stage 1 fault but a design limit. |
| **D6** | **No clock verdict on candle sources.** FREEZE.md §6 (`/opt/tradingbot/reports/v3/FREEZE.md:176`): "The historical evaluation is therefore labelled **UNVERIFIED CLOCKS**." The Stage 0b manifest (SHA 16701ce7…) exists but on a different filesystem (`/mnt/volume_lon1_1778405456698/…`) and verifies **ticks**, not candles | Candle-timestamp integrity is assumed, not verified. Pre-corrected research must honour this limitation. |
| **D7** | **No repeated-test (Section 6A) measurement** — Stage 1 taxonomy's Mechanism B ("repeated interaction") is a loose per-level touch count, not Section 6A's first/second/third test sequence with departure/return definition | Section 6A is a corrected-spec addition and has no Stage 1 analogue. |
| **D8** | **No independent "touch without penetration" / "rejection without follow-through" / "breakout continuation" counts** — Stage 1 only logged candidates that passed the wick+rejection filter | Section 8 of the corrected spec requires the full funnel including incomplete events. |

### 1.3 Verdict for Deliverable A

Stage 1 was internally rigorous but **tested a different hypothesis** than the one the operator intended. The 9,349-row pool is a *within-wick-rejection-pool* study, not a *liquidity-sweep-as-trading-sequence* study. The corrected spec's independent-population scan (§5) is the right fix.

---

## 2. Material definitional ambiguities — operator decision required

The spec forbids silent invention. Each item below:
- cites what the codebase provides,
- states precisely what is unspecified,
- proposes a resolution with rationale,
- names what I will do while waiting.

### 2.1 **AMB-1: Which rejection detector?**  (spec §7)

The spec says *"Use the user's existing rejection-candle definitions where explicitly available"* AND *"Do not import Bollinger Bounce rules."*

The codebase contains **four** rejection detectors. Three are impermissible or state-dependent; the fourth is a candidate but is not currently labelled a "rejection" primitive in production.

| # | Detector | File:line | Pure M5 geometry? | Spec-permissible? |
|---|---|---|---|---|
| (a) | `BB_BOUNCE` rejection: body ≥ 1.5p + close-side vs open + close inside BB ± tolerance | `gbpusd_bb_bounce.py:2138-2155` | NO — requires BB | **Forbidden by spec** ("Do not import Bollinger Bounce rules") |
| (b) | `LEVEL_LADDER._is_rejection_at_rung`: `high > rung AND close < rung AND (close − low) ≤ range/3` (bearish at resistance); mirror for bullish at support | `level_ladder.py:484-510` | YES | **Candidate** |
| (c) | §16 retest-band: wick within 8p of level AND body ≥ 4p AND close back + `memory.role_reversal_armed` state | `qm_decision_shadow.py:1943-2127` | NO — requires `LevelMemory` state replay | Permissible but state-heavy |
| (d) | §24 sweep-reclaim: inside `CAND_LEVEL_ACCEPTED` state, bars ≤4, close through `zone_center` opposite to `accepted_side`, body ≥ 4p | `qm_decision_shadow.py:1150-1225` | NO — requires state machine replay | Permissible but state-heavy |

**The ambiguity:**
- Detector (a) is excluded by the spec.
- Detector (b) is **pure geometry** and matches the sweep sequence directly: a bar that pierced the level and closed back through with close in the far third of its range. However it is **not labelled "rejection"** anywhere in the briefing-sweep documentation that the spec's §7 refers to; it lives under the `level_ladder` module.
- Detectors (c) and (d) are the production-level primitives but require full `qm_decision_shadow` state replay (every M5 bar fed through the state machine from session open), which is tractable but materially expands the Stage 2 computational footprint.

**Proposed resolution (not applied without approval):**

> **Primary:** use (b) `_is_rejection_at_rung` as the rejection primitive. It is import-free, point-in-time, uses only M5 OHLC + the structural level, and matches the operator's §7 sequence literally.
> **Sensitivity sidecar:** rerun the whole pipeline with (c)+(d) as the rejection primitive, replaying `qm_decision_shadow` from session open. Report both populations in Deliverable D with the operator's intended one as primary.

**Operator decision needed:**
- Approve (b) as primary?  Y / N
- Approve (c)+(d) sensitivity rerun?  Y / N
- Or specify a different frozen rejection detector by file:line?

---

### 2.2 **AMB-2: Swing-high / swing-low confirmation**  (spec §4)

Spec §4: *"Previously confirmed swing highs / lows. All levels must be known before the approach. No future-confirmed swing points."*

Three coexisting swing systems:

| # | Source | File:line | Confirmation point | Walk-forward safe? |
|---|---|---|---|---|
| (α) | `qm_swing_levels` — 3-bar close cluster (span ≤ 3p env `QM_SWING_CLUSTER_SPAN_PIPS`) + ≥15p rejection bar | `qm_swing_levels.py:85-179` | At the failure bar's close | YES, but session-scoped (volatile) |
| (β) | `market_structure.detect_confirmed_swings` — fractal: bar k is a swing high if `highs[k] > max(highs[k±N])`, default N=3 | `market_structure.py:58-96` | At bar k+N | YES |
| (γ) | `level_computation._swing_points` — H1 24-bar / 10p reversal filter; H4 30-bar / 20p — included in briefing level clusters | `level_computation.py:249-319` | Implicit (reversal filter) | YES but H1/H4-only |

**The ambiguity:** which of (α), (β), (γ) — or all three — is the canonical "previously confirmed swing" for structural-level purposes? They produce different populations:

- (α) is M5-grained and session-reset.
- (β) is bar-grained with explicit N-bar confirmation delay — the safest for "no future peek" semantics.
- (γ) is HTF-only and already baked into `level_computation.get_ranked_levels()`.

**Proposed resolution (not applied without approval):**

> **Primary:** (β) `detect_confirmed_swings(N=3)` applied on M5 for the operator's "swing high / swing low" level family. The N=3 bar delay is explicit — a swing at bar k becomes a *known* level only at bar k+3's close. This is maximally defensive against future leakage.
> **Supplementary HTF swings:** (γ) via `get_ranked_levels()` continues to feed H1_SWING_HIGH#0..4 / H4_SWING_HIGH#0..4 under their existing confirmation rules.

**Operator decision needed:**
- Approve (β) N=3 as the M5 swing definition?  Y / N  (if different N, specify)
- Approve (γ) H1/H4 swing families to be included in level enumeration?  Y / N
- Include (α) session-scoped swings as an additional family?  Y / N

---

### 2.3 **AMB-3: Repeated-test departure threshold**  (spec §6A)

Spec §6A: *"A new test requires price to depart from the level and subsequently return. Use a point-in-time departure and return definition. Do not optimise the departure threshold using future outcomes. If no previously agreed threshold exists, report the ambiguity before implementing the test counter."*

**What the codebase provides:**
- `sweep_level_validator.py:37` — `LEVEL_TOLERANCE = 8` pips. This is used as a **retest band** (approach proximity), not as a departure threshold.
- No module defines a point-in-time *departure* threshold for test-counter purposes. `qm_level_memory.LevelMemory.touch_count` increments on finalised interactions but the "finalise" event is not documented as a departure test.

**The ambiguity:** given price has approached a level (entered the 8p retest band), when does it count as having *departed* so that the next re-entry registers as test N+1 rather than extending test N?

**Three defensible point-in-time choices:**
| Option | Departure rule | Rationale |
|---|---|---|
| D-A | Price exits the 8p band and stays outside for ≥1 M5 close | Minimal; matches "band departure" literally |
| D-B | Price exits the 8p band and reaches ≥N pips distance (e.g. 12p = 1.5× band) | Prevents chop around the band from inflating test counts |
| D-C | Price exits and establishes a confirmed intermediate swing in the opposite direction (per AMB-2 definition) | Structurally cleanest; aligns tests with meaningful retracements |

**Proposed resolution (not applied without approval):**

> **Primary:** D-B with threshold `TEST_DEPARTURE_PIPS = 12` (1.5× `LEVEL_TOLERANCE`). Secondary report also lists test counts under D-A and D-C for the same event population so sensitivity is visible without re-running from scratch.

**Operator decision needed:**
- Approve D-B at 12 pips?  Y / N (if different value, specify)
- Report D-A and D-C alongside as sensitivity?  Y / N

---

## 3. Preregistered defaults for lower-stakes decisions

These are not material-level ambiguities but they *are* choices. Documented here so the operator can override before any code runs.

| Decision | Default | Source |
|---|---|---|
| Approach band width | 8 pips | `sweep_level_validator.py:37` |
| Confirmation rule | strict close beyond rejection extreme (BUY: `close > rj.high`; SELL: `close < rj.low`) | `briefing_sweep.py:401-407` |
| Earliest executable entry | at the confirmation-candle **close** (not open, not touch) | `briefing_sweep.py:401-407` convention |
| D1 direction | `d1_direction.compute_d1_direction_from_candles` — 9-check scoring, BULL/BEAR/NEUTRAL at ≥±4/−4 | `d1_direction.py:439-449` |
| D1/H4 agreement | `d1_close > d1_ema20` compared to `h4_close > h4_ema20` | `briefing/v5_pia/confidence_scorer.py:460-506` |
| D1 window | FX session: `[D−1 22:00 UTC, D 22:00 UTC)` labelled D 00:00 UTC | `timeframe_context.py:81-83` |
| H4 / H1 bias | `sign(EMA21 − EMA50)` on H4 / H1 closes; neutral buffer 0.0 | `timeframe_context.py:285-314` |
| Daily pivots | Classical floor: `P=(H+L+C)/3`, R1=`2P−L`, S1=`2P−H`, R2=`P+(H−L)`, S2=`P−(H−L)`, R3=`H+2(P−L)`, S3=`L−2(H−P)` from prior completed D1 bar via `htf_cache.select_prior_completed_d1` | `ig_daily_pivots.py:141-150` + `level_computation.py:471-479` |
| Round-number levels | multiples of 50 pips within ±150 pips of current price | `level_computation.py:322-339`, 551-555 |
| Multi-level overlap | cluster within 5p, enforce 15p separation, cluster anchor = highest-priority member | `level_computation.py:587-621` |
| Session boundaries | London 07:00–18:00 Europe/London; NY 13:00–18:00 Europe/London | `bounce_engine/v3/eval_historical.py:40-131` |
| Candle M5 loader | `bounce_engine/v3/eval_historical.load_m5(root, from_date, to_date) → List[M5Bar]` | `eval_historical.py:54-83` |
| H1 resampler | `h1_pierce.resample_h1_from_5m(df5m, min_5m_bars=6)`; left label, left-closed | `h1_pierce.py:198-247` |
| Transaction cost | 0.9 pips spread + 0.5 pips adverse stop slippage; same-bar stop/trigger/exit resolved adversely | `eval_historical.py:46,274-312` |

**Operator decision needed:** confirm this table en bloc, or line-item overrides.

---

## 4. Data authority

### 4.1 Manifest verification

```
file : /mnt/volume_lon1_1778405456698/research/gbpusd_intraday_feasibility/
       worktree/outputs/freeze/tick_correction_manifest.csv
size : 80,863 bytes (822 lines; 1 header + 821 data rows)
mtime: 2026-10-08 16:40 UTC
sha256: 16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc
         ✓ matches spec §11
```

### 4.2 What the manifest actually certifies

The manifest is a **tick-vs-candle clock-coherence verdict** per date — it does **not** certify the candle values themselves. Columns include `n_candle_bars`, `best_lag_fine_s`, `regime_classification`, `regime_match`. A date is "clean" when `status=ok AND regime_match=True`.

Row distribution (my survey, matching Agent 1):

| Partition | Date range | Rows ok+match | Candle source | Basis | Regime(s) |
|---|---|---|---|---|---|
| DEV | 2024-01-01 → 2025-06-30 | ~447 | `candles_ext_v2` | **BID** | fixed_minus4h, fixed_minus5h |
| HOLDOUT | 2025-07-01 → 2025-12-31 | ~139 | `candles_ext_v2` | **BID** | fixed_minus4h, fixed_minus5h |
| OOS | 2026-01-01 → 2026-03-31 | ~57 | `candles` | **MID** | unshifted_utc (50) + fixed_minus5h (7) |
| **Total authorised** | | **643** | | | |

Excluded: 25 "ok but anomalous_*" rows (regime_match=False), 137 "no_candles" rows (missing bar data), 16 other rows.

### 4.3 Honest limitation (per spec §11 and FREEZE.md §6)

**The candles have never been clock-verified against an authoritative reference** inside `/opt/tradingbot`. FREEZE.md §6: *"The historical evaluation is therefore labelled **UNVERIFIED CLOCKS**."* The Stage 0b manifest lives on a separate research volume and verifies **tick-vs-candle alignment** — not candle correctness in absolute terms. The research in this branch inherits this limitation. **All results will carry the "UNVERIFIED CLOCKS" caveat explicitly** in their final verdict.

### 4.4 Price-basis investigation (spec §11)

The 2024-2025 vs 2026 basis change is **structural, not optional** — there is no single-basis source covering both partitions on this host. The corrected spec requires explicit investigation. **Preregistered plan:**

1. For every authorised 2026 trading day, cross-check `candles` MID OHLC against any available `candles_ext_v2` row for the same date. If both exist, measure the systematic shift (should be ≤ ½ spread ≈ 0.45 p).
2. Repeat the event-population scan twice on the 2026 window:
   - as-is MID basis;
   - MID synthesised to BID via `bid = mid − 0.45p` (approximation).
3. Report whether the sweep-event count and the direction of each event changes under the two basis assumptions.
4. If material (≥5% event-count delta or any direction flips), down-rate OOS validity accordingly.

This is **not** a definitional ambiguity — the spec sanctions it — but the operator should know the shape of the investigation before Stage 2 runs.

---

## 5. Deliverable B — Structural approach population (preregistered design)

For each authorised date `d` in the 643-day manifest set:
1. Load M5 candles from the manifest-indicated source.
2. Compute all structural levels valid at the start of each M5 bar via `level_computation.get_ranked_levels(symbol="GBPUSD", now_utc=t_bar_open)` PLUS daily pivots P/R1–R3/S1–S3 from `ig_daily_pivots.compute_classic_floor()` (currently not wired into `get_ranked_levels` — direct call needed) PLUS swing highs/lows from AMB-2's chosen rule.
3. For each (level, bar) pair, classify the bar's relationship to the level:
   - **Touch:** price enters the 8p approach band but does not cross the level.
   - **Penetration:** price crosses the level during the bar (high > level for resistance / low < level for support).
   - **Breakout:** penetration AND close beyond the level AND (next-bar close also beyond level) — note this is forward-looking by one bar, used only for taxonomy, never for entry eligibility.
   - **Approach-no-penetration:** price enters the band but does not pierce.
4. Emit one event record per (date, level, M5 bar) with these labels + the test counter from AMB-3's chosen rule.
5. Independence from Stage 1: this scan does **not** read the frozen 9,349 pool. The 9,349-row candidate list is referenced only in Deliverable K reconciliation.

Expected population size: ~643 days × ~288 bars × 4-6 levels ≈ 740k to 1.1M event records before any filter. Storage: Parquet, partitioned by (year, month), under `research/liquidity_sweep_corrected/data/approaches.parquet/`.

---

## 6. Deliverables C → K — Preregistered plan

| Deliv. | Content | Depends on | Output format |
|---|---|---|---|
| B | Approach population (above) | §5 | Parquet |
| C | Chronological liquidity-sweep event ledger (Type A + Type B separately, Sequences A/B/C of §6A) | B + AMB-3 | Parquet + markdown summary |
| D | M5 rejection + confirmation ledger (per AMB-1 primary and sensitivity) | C + AMB-1 | Parquet |
| E | Favourable / adverse excursion analysis (§9) with +10/+15/+20/+25/+30/+40 pip milestones; adverse excursion before each favourable milestone | D | Parquet + CSV + markdown |
| F | Fixed 30/12 comparison with Stage 1 | E | Markdown |
| G | Structural exit feasibility assessment (Model 2, spec §10) — **may remain unexecuted** per spec §10: "If the structural objective or stop-buffer rule is not already precisely defined, report the missing definition and do not invent one." The brief itself permits deferring this component. | E + spec clarity | Markdown (deferral report acceptable) |
| H | HTF context comparison (D1&H4 agree vs disagree) | E | Markdown |
| I | Session + level-family breakdown | E | Markdown + CSV |
| J | Chronological validation (DEV / HOLDOUT / OOS; freeze before OOS; day-clustered bootstrap) | all above | Markdown |
| K | Final research verdict + answers to the 16 §13 questions | J | Markdown |

---

## 7. Non-negotiable guardrails confirmed

- RESEARCH ONLY, production AutoBot untouched. ✓
- NMS V3 untouched. ✓
- Standalone BB Bounce untouched. ✓
- Existing London Liquidity Sweep service (`/opt/london_liquidity_sweep/`) untouched. ✓
- No deployment, no service restart, no systemctl. ✓
- Candle cache untouched. ✓
- No new technical indicators invented. ✓
- No `git stash` in this branch's work. ✓
- No commits inside `/opt/tradingbot` — this report is being written in a worktree at `/home/autobot/reports-wt/liquidity-sweep-corrected-20261017/`. ✓
- Frozen research definitions preserved. ✓

---

## 8. What happens when operator responds

Preferred format of operator response — anywhere in the next message:

```
AMB-1: (b) primary, (c)+(d) sensitivity yes
AMB-2: (β) N=3 yes, (γ) HTF yes, (α) session no
AMB-3: D-B at 12 pips, report D-A and D-C sensitivity yes
§3 preregistered defaults: approved as listed  [or line-item overrides]
```

Once the three AMB-* decisions are set, Stage 2 (Deliverable B — independent event population scan) starts immediately. Expected first-commit landing time on this branch after decisions: ≈ 2–4 hours of batch compute for the full 643-day scan, published incrementally per spec rule *"Commit after each completed unit of work."*

---

## 9. Appendix — reconnaissance citations

Full file:line citations for every claim in §1–§3 are in the five parallel reconnaissance agent reports produced on 2026-10-17. Those reports are not committed to the repo (would be noise); their findings are preserved verbatim in this file above.

Key frozen-rule entry points (for the next-session reader):

- Data loader: `/opt/tradingbot/bounce_engine/v3/eval_historical.py:54-83`
- D1 direction: `/opt/tradingbot/d1_direction.py:439-449`
- HTF context: `/opt/tradingbot/timeframe_context.py:217-401`
- D1/H4 agreement: `/opt/tradingbot/briefing/v5_pia/confidence_scorer.py:421-529`
- Pivots: `/opt/tradingbot/ig_daily_pivots.py:141-150`
- Level enumeration: `/opt/tradingbot/level_computation.py:755-810`
- Rejection (a): `/opt/tradingbot/gbpusd_bb_bounce.py:2138-2155`
- Rejection (b): `/opt/tradingbot/level_ladder.py:484-510`
- Rejection (c): `/opt/tradingbot/qm_decision_shadow.py:1943-2127`
- Rejection (d): `/opt/tradingbot/qm_decision_shadow.py:1150-1225`
- Confirmation: `/opt/tradingbot/briefing_sweep.py:401-407`
- Swings (α): `/opt/tradingbot/qm_swing_levels.py:85-179`
- Swings (β): `/opt/tradingbot/market_structure.py:58-96`
- Swings (γ): `/opt/tradingbot/level_computation.py:249-319`
- Memory factors: `/opt/tradingbot/qm_level_memory.py:209-499`
- Freeze note: `/opt/tradingbot/reports/v3/FREEZE.md:176`

End of Stage 0.
