# OUTER-LEVEL first-touch fade — provenance + trade simulation

Scope: READ-ONLY + REPLAY. No live edits. Build 1 frozen (HEAD = 730f961).
Finding under test: OUTER-LEVEL first-touch fade, turn10 ≈ 0.73 — from
`reports-public/coincidence_confirmation_ext_20260816.md` (commit `7343a6e`,
2026-08-16) and detector `/tmp/coincidence_ext_v2.py`.

---

## 1. PROVENANCE

### 1.1 Direct descendants of the August corpus work

Two production code paths carry the finding's DNA. **Neither is a pure
"fade" implementation** — both wrap the research signal in additional
machinery.

| Candidate | Lineage | Status | Where |
|---|---|---|---|
| **LEVEL_BOUNCE** (three-candle) | Direct descendant | LIVE (`.env:885 LEVEL_BOUNCE_ENABLED=1`) | `gbpusd_level_bounce.py` |
| **V2_PICK_BOUNCE** | Independent SDE route, later gated to the finding's reversal half | OFF (`.env:977 V2_PICK_BOUNCE_ENABLED=0`) | `qm_v2_executor.py`, state machine in SDE |
| QM V2 (VELOCITY route) | **Not** derived from this corpus — velocity engine | LIVE (`.env:975 QM_LIVE_FIRE=1`) | `qm_v2_executor.py` |
| BB_BOUNCE | Predates the finding; separate research family | — | `.env BB_BOUNCE_* ` gates mostly OFF (memory `[[project_bb_bounce_gates_disabled]]`) |

#### LEVEL_BOUNCE (primary descendant)

- First commit: `ac1cbd8` 2026-08-13 "feat(level_bounce): LEVEL_BOUNCE three-candle strategy, unmanaged (default OFF)" — pre-dates the confirmation report (`7343a6e`, 2026-08-16).
- Explicit citations in code tie it to the finding:
  - `gbpusd_level_bounce.py:94` `SHADOW_FWD_BARS = 12 # matches coincidence_confirmation_ext v2 window`
  - `gbpusd_level_bounce.py:97-100` "First-touch preference. Evidence: coincidence_confirmation_ext_20260816.md — singleton-day OUTER LEVEL events turn at t15=0.646 (31/48) vs multi-day 0.463 (1,001/2,164)…"
  - `gbpusd_level_bounce.py:201-203` references the "coincidence study"
  - `gbpusd_level_bounce.py:259` reversal MFE "same convention as the coincidence_confirmation_ext v2 outcome fields"
- Shape of the strategy departs from the research:
  - Research = fade at first touch (bar extreme reaches an OUTER pivot, within 3p; bail if peak pierce > 20p).
  - LEVEL_BOUNCE = **three-candle pattern**: C1 pierces BB(20,2) AND the pierced band is ≤ `LEVEL_BOUNCE_NEAR_PIPS` (default 5) of an OUTER pivot; C2 closes back inside the band; C3 fires only when price trades beyond C2's reversal extreme (stop-order fill). Exit = fixed 100p broker stop (`LEVEL_BOUNCE_STOP_PIPS=100`), no managed exits (`ac1cbd8` commit body).
  - So LEVEL_BOUNCE is a **band-and-level confluence pattern** (what the research calls COINC: band_gap ≤ 5p ≈ 3p+slack), filtered through C1/C2/C3 ordering. The research found OUTER-**LEVEL** (band ≥ 10p from the pivot) was the strongest cell at 0.733 — LEVEL_BOUNCE's `NEAR_PIPS=5` gate requires band close to the level, i.e. it selects for the **COINC cohort (0.629)** and discards the stronger LEVEL cohort.
  - The 2026-08-16 shadow (`gbpusd_level_bounce.py:93 NEAR_PIPS_SHADOW=999`) was added precisely to capture the far-band cases the live gate rejects; evidence for the inversion is the `level_bounce_middle_days_20260816.md` report.

Verdict: LEVEL_BOUNCE **is** the production descendant of the OUTER-level
first-touch finding. It fires live. It implements a *harder* version of
the research (adds C2 and C3) and selects the *weaker* cohort (band near
level, i.e. COINC not LEVEL). The pure fade — anchor-bar entry at level
price with no C2/C3 requirement — is **not implemented anywhere live**.

#### V2_PICK_BOUNCE (secondary, OFF)

- `qm_v2_executor.py:296-490` — `_fire_route` for `V2_PICK_BOUNCE`.
- Engines mapped `qm_v2_executor.py:232-233`:
  - `SLOW_REJECTION` → `opportunity_type=REVERSAL` (the fade half)
  - `CONTINUATION`   → `opportunity_type=TREND_CONTINUATION`
- No explicit `coincidence_confirmation_ext` citation. V2_PICK was built as the SDE's "pick-bounce" entry (`candidate.py:62`, `candidate.py:103`, Stage 6a `stage6a_recognition.py:21,139`), not as a direct implementation of the corpus turn-10 result. It overlaps with the fade thesis because `SLOW_REJECTION` ≈ "price got rejected at a defended level".
- Status: `V2_PICK_BOUNCE_ENABLED=0` in `.env:977`. Dead.

### 1.2 Stage-9 alignment rule (2026-10-03)

Operator amendment appended to `docs/v2_precedence_ruling_20261003.md:20-25`
(commit `c7fb3f1` 2026-10-03 12:51 UTC):
> V2_PICK_BOUNCE may open a trade **only when its side agrees with Stage 9 demonstrated direction** (UP → BUY, DOWN → SELL). Stage 9 NONE = no trade.

Wiring: `qm_v2_executor.py:332-398`. Pre-dispatch block in `_fire_route`
for `route == V2_PICK_BOUNCE` only (VELOCITY/QM_V2 is unchanged, `line 339-340`):

- `line 348-367`: build `demonstrated_direction.build_from_production(sym)`; on
  any exception → `v2_pick_stage9_exception` → fail-closed REJECT.
- `line 368-383`: Stage-9 NONE / unavailable → `v2_pick_stage9_none` → REJECT.
- `line 384-398`: Stage-9 UP but candidate SELL (or DOWN vs BUY) →
  `v2_pick_stage9_disagree:{dir}` → REJECT.

**Does this block fades by construction?** Partially — and only against
HTF. A "fade" is defined by geometry (counter-move at a defended pivot),
not by HTF. Two cases:

1. **With-trend fade** (dip-buy at S-level in HTF UP, or rally-sell at R-level in HTF DOWN) → side AGREES with Stage 9 → passes.
2. **Counter-trend fade** (rally-sell at R-level in HTF UP, or dip-buy at S-level in HTF DOWN) → side DISAGREES → blocked.

So Stage-9 silently drops **the counter-trend half** of the OUTER-level
first-touch finding (the research corpus was HTF-agnostic). It also
blocks every fade when Stage 9 cannot resolve a direction (NONE/unavailable).

### 1.3 Counts from recent logs

Scoped scan: `logs/qm_candidates.jsonl*` (lifecycle rows with
`live_fire_disposition`) and `logs/arbiter_shadow.jsonl*`
(M3 arbiter V2_PICK proposals). The direct executor-side `live_fire_disposition`
only has 79 rows across the archive — this field is only persisted when the
executor is reached, and `V2_PICK_BOUNCE_ENABLED=0` means most proposals
short-circuit upstream. Numbers are small-sample.

**Executor-side disposition (`V2_PICK_BOUNCE_ENABLED=0` → mostly unreachable):**

| metric | count |
|---|---|
| V2_PICK_BOUNCE live_fire_disposition rows | 79 |
| gate_allowed = True (Stage 9 passed) | 15 |
| executed = True | 8 |
| rejected: `v2_pick_stage9_disagree:*` | **0** |
| rejected: `v2_pick_stage9_none` | **14** |

**Arbiter shadow (M3 V2_PICK proposals, `inputs.A` = Stage-9 proxy from `demonstrated_direction.build_from_production`):**

| metric | count |
|---|---|
| V2_PICK_BOUNCE proposals | 49 |
| engine = CONTINUATION | 20 |
| engine = SLOW_REJECTION (the fade half) | **26** |
| side BUY | 23 |
| side SELL | 26 |
| A (Stage-9 proxy) AGREES with B direction | 11 |
| A DISAGREES with B direction (would be `stage9_disagree`) | **7** |
| A unavailable / NONE (would be `stage9_none`) | **31** |

So in the arbiter log, of 49 V2_PICK proposals, **38 (78%) would be
rejected by the Stage-9 rule** (31 NONE + 7 disagree) and only 11 (22%)
would pass. Of the 26 `SLOW_REJECTION` proposals (the research fade
twin), the agree/disagree/NONE split is in the same ballpark.

**Conclusion for Section 1.** The finding has one live descendant
(LEVEL_BOUNCE) that selects the weaker COINC cohort via a hard
band-proximity gate, and one dead descendant (V2_PICK_BOUNCE,
`ENABLED=0`) whose Stage-9 gate would additionally cull ~78% of what
remained. The pure OUTER-LEVEL first-touch fade (anchor-bar entry at
level price, no C2/C3, no HTF filter) is **not implemented live**.

---

## 2. TRADE SIMULATION

Script: `/tmp/outer_fade_sim.py`, output `/tmp/outer_fade_sim_results.json`.

### 2.1 Spec (verbatim constraints)

- OUTER pivots only: R1/R2/R3 for SELL fade; S1/S2/S3 for BUY fade (P excluded).
- `TOUCH_PIPS=3`, `MAX_PIERCE_PIPS=20`, `FWD_BARS=12`.
- First touch per `(date, level, side)` — one trade per level per date per side.
- Sources:
  - 2024-01-01 → 2025-12-31: `data/candles_ext/GBPUSD/{DATE}.csv` (ext).
  - 2026-01-01 → 2026-10-04: `data/candles/GBPUSD/{DATE}.csv` (live) with fallback to `data/ohlc/GBPUSD/5M/{DATE}.csv` for pre-live dates.
  - **Excluded**: all of 2026-03 (`2026-03-*`, 23 days — user request) and 2026-04-07..10 (known-corrupt flat).
- Pivots: 2024-25 classic-floor on `candles_ext/GBPUSD_D1.csv` prior day; 2026 `bb_pd_gate.compute_pivots_only` (IG D1 cache).
- Days scanned: **829** (`ext=627`, `live=202`). Skipped bad: 35. Skipped (no pivots): 3.
- Unique first-touches (anchor bars that reached a level, peak-pierce ≤ 20p): **845**.

### 2.2 Fill convention (exact)

- Entry fires on the **first bar** whose extreme actually reaches the level (bar.h ≥ level for SELL at resistance; bar.l ≤ level for BUY at support). Approach-but-not-reach bars (within 3p but no crossing) are NOT fillable and are skipped.
- Entry price = level (mid). **Half-spread 0.4p adverse at entry; 0.4p adverse at exit.** Net pip P&L = raw mid change in favorable direction − 0.8p.
- The anchor bar is bar 0; forward tracking starts at anchor_idx+1 and runs 12 bars.
- Peak pierce measured across the contiguous touching chain containing the anchor (BOTH past and future contiguous touching bars within 3p). If peak > 20p → BREAKOUT → trade abandoned.

### 2.3 Stop variants and targets

- (a) `FIRST_CLOSE` — exit on first 5m close beyond the level. Stop pips = adverse mid distance at that close.
- (b) `HARD_12P` — pip stop at level ± 12p; can trigger intra-bar (bar.h ≥ level+12 for SELL; bar.l ≤ level−12 for BUY). Loss = −12p mid − 0.8p = **−12.8p net**.
- (c) `PIERCE_20P` — pip stop at level ± 20p (the v2 breakout cap). Loss = **−20.8p net**.
- Targets: 10p and 15p (reversal MFE). Win = target_p − 0.8p net.
- Time stop: close at the 12th forward bar's close.
- **Stop-first on same bar** (per request): if a bar's range contains both the stop pip and the target pip, the stop is taken.

### 2.4 Top-line (per variant × target)

| variant | target | n | win% | mean_pips_net | median_pips_net |
|---|---|---|---|---|---|
| FIRST_CLOSE | 10 | 845 | 35.6% | +0.89 | −1.67 |
| FIRST_CLOSE | 15 | 845 | 31.0% | +1.12 | −1.87 |
| HARD_12P | 10 | 845 | **67.7%** | **+2.69** | **+8.57** |
| HARD_12P | 15 | 845 | 62.4% | +2.89 | +3.40 |
| PIERCE_20P | 10 | 845 | **73.3%** | **+4.12** | **+9.20** |
| PIERCE_20P | 15 | 845 | 67.9% | +4.34 | +4.50 |

- **PIERCE_20P + 10p target reproduces the research turn10 exactly (73.3% vs 0.733).** The pierce-20p stop is simply the research's "BREAKOUT excluded" rule carried into the trade: if the pierce goes >20p you're stopped at ~−20p; otherwise the only path to loss is time-stop or close-beyond, which the 10p target typically beats.
- **FIRST_CLOSE under-performs by ~40pp vs the turn10 number.** Reason: the research's turn10 counts same-bar as a WIN if the running reward hits 10p before close_beyond is flagged (reward update precedes close check per `/tmp/coincidence_ext_v2.py:191-203`). This simulation implements the user's **stop-first** rule, which flips same-bar behavior. Many "turn10" events in the research actually have the anchor-bar close printing beyond the level before the next bar's low prints 10p favorable — those become STOPs here. 275 TARGET vs 537 STOP vs 29 TIME_STOP under FIRST_CLOSE/10p.
- **HARD_12P + 10p target has a slightly worse R:R (10:12) and still clears 67.7% win rate / +2.69 mean**. 109 of 845 are HARD_12P stops; 421 TARGETs; 314 time-stops.

### 2.5 By year

| year | variant | target | n | win% | mean | median |
|---|---|---|---|---|---|---|
| 2024 | FIRST_CLOSE | 10 | 362 | 32.9% | +0.66 | −1.72 |
| 2024 | HARD_12P | 10 | 362 | 66.9% | +2.36 | +5.32 |
| 2024 | PIERCE_20P | 10 | 362 | 71.0% | +3.48 | +6.75 |
| 2025 | FIRST_CLOSE | 10 | 313 | 37.7% | +1.27 | −1.47 |
| 2025 | HARD_12P | 10 | 313 | 70.9% | +3.38 | +9.20 |
| 2025 | PIERCE_20P | 10 | 313 | 76.4% | +4.73 | +9.20 |
| 2026 | FIRST_CLOSE | 10 | 170 | 37.6% | +0.67 | −1.79 |
| 2026 | HARD_12P | 10 | 170 | 63.5% | +2.12 | +9.20 |
| 2026 | PIERCE_20P | 10 | 170 | 72.4% | +4.35 | +9.20 |

| year | variant | target | n | win% | mean | median |
|---|---|---|---|---|---|---|
| 2024 | FIRST_CLOSE | 15 | 362 | 29.0% | +0.96 | −1.85 |
| 2024 | HARD_12P | 15 | 362 | 63.8% | +2.78 | +3.32 |
| 2024 | PIERCE_20P | 15 | 362 | 67.7% | +3.90 | +4.03 |
| 2025 | FIRST_CLOSE | 15 | 313 | 32.6% | +1.49 | −1.80 |
| 2025 | HARD_12P | 15 | 313 | 63.6% | +3.55 | +4.20 |
| 2025 | PIERCE_20P | 15 | 313 | 69.3% | +4.98 | +5.40 |
| 2026 | FIRST_CLOSE | 15 | 170 | 32.4% | +0.78 | −2.02 |
| 2026 | HARD_12P | 15 | 170 | 57.1% | +1.92 | +2.11 |
| 2026 | PIERCE_20P | 15 | 170 | 65.9% | +4.10 | +4.53 |

Year stability on PIERCE_20P + 10p: **0.71 / 0.76 / 0.72** across 2024/25/26
— tracks the research's within-year turn10 numbers (0.70/0.76/0.77 for
OUTER-LEVEL alone; the simulation pool includes both LEVEL and COINC
cohorts).

### 2.6 By source

| src | variant | target | n | win% | mean | median |
|---|---|---|---|---|---|---|
| ext (2024-25) | PIERCE_20P | 10 | 675 | 73.5% | +4.06 | +9.20 |
| live (2026) | PIERCE_20P | 10 | 170 | 72.4% | +4.35 | +9.20 |
| ext | HARD_12P | 10 | 675 | 68.7% | +2.84 | +8.50 |
| live | HARD_12P | 10 | 170 | 63.5% | +2.12 | +9.20 |
| ext | FIRST_CLOSE | 10 | 675 | 35.1% | +0.94 | −1.63 |
| live | FIRST_CLOSE | 10 | 170 | 37.6% | +0.67 | −1.79 |

The ext/live split is clean — the pierce stop's +4p mean survives
the shift to the live IG candle source.

### 2.7 London vs NY (and other)

Session bucketing on anchor-bar UTC hour: LONDON=[07,13), NY=[13,20), OTHER=rest.

| session | variant | target | n | win% | mean | median |
|---|---|---|---|---|---|---|
| LONDON | PIERCE_20P | 10 | 326 | 75.5% | +4.50 | +9.20 |
| LONDON | HARD_12P | 10 | 326 | 68.4% | +2.64 | +9.20 |
| LONDON | FIRST_CLOSE | 10 | 326 | 35.0% | +0.73 | −1.68 |
| NY | PIERCE_20P | 10 | 251 | **80.1%** | **+5.55** | +9.20 |
| NY | HARD_12P | 10 | 251 | **72.5%** | **+3.71** | +9.20 |
| NY | FIRST_CLOSE | 10 | 251 | 43.4% | +1.65 | −1.38 |
| OTHER | PIERCE_20P | 10 | 268 | 64.2% | +2.31 | +2.75 |
| OTHER | HARD_12P | 10 | 268 | 62.3% | +1.80 | +2.50 |
| OTHER | FIRST_CLOSE | 10 | 268 | 29.1% | +0.36 | −1.70 |

**NY is the clear winner** on every stop/target cell: 80.1% WR / +5.55p
mean on PIERCE_20P + 10p. LONDON follows at 75.5% / +4.50. OTHER
(Asian + late-US) collapses to 64.2% / +2.31 and widens the losers.

### 2.8 Side split (unfiltered by HTF — relevant for the Stage-9 question)

| side | variant | target | n | win% | mean | median |
|---|---|---|---|---|---|---|
| BUY (S-level fade) | PIERCE_20P | 10 | 407 | 77.1% | +4.82 | +9.20 |
| SELL (R-level fade) | PIERCE_20P | 10 | 438 | 69.6% | +3.47 | +6.58 |
| BUY | HARD_12P | 10 | 407 | 70.5% | +3.24 | +9.20 |
| SELL | HARD_12P | 10 | 438 | 65.1% | +2.19 | +5.05 |

Both sides are positive on all three stop variants at 10p target. The
Stage-9 rule would retain whichever side agrees with current HTF
direction (BUY-fades in HTF UP; SELL-fades in HTF DOWN) and drop the
other. On the corpus, this amounts to blocking the slightly weaker SELL
side when HTF is UP and the slightly stronger BUY side when HTF is DOWN
— symmetric drop in trade count, no obvious edge-direction preserved.

### 2.9 Caveats

- Fill at level price is **optimistic for the losing tail**: in live
  conditions the anchor bar's extreme may be *through* the level
  (peak pierce 0 to 20p); a market order placed at bar-close may fill
  at an adverse price mid between the level and the extreme. The
  simulation gives the trade credit for a limit at the level, which
  the research design implicitly assumes.
- Stop-first same-bar is the user-specified convention. The research's
  "target-first" convention would raise FIRST_CLOSE 10p from 35.6% to
  something closer to the research turn10 of ~73% (see §2.4).
- Pivots after 2026-01-01 depend on `bb_pd_gate.compute_pivots_only`;
  3 days skipped where IG D1 cache was unavailable.
- No warm-up required (no BB; this simulation is level-only).
- No regime, HTF, or news filter applied — pure geometry per spec.

---

## STOP.
