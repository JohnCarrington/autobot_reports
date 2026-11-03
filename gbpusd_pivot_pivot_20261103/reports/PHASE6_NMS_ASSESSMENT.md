# Phase 6 — NMS diagnostic assessment (code-inspection + representative sessions)

**Scope.** Operator asked: do NOT replay all 676 days. First assess structurally. Only expand to a full replay if a meaningful diagnostic opportunity is found and the replay can be made deterministic.

Code-inspection + applying the rules to representative price-action patterns from Phase 2 is sufficient to identify the diagnostic opportunities — a full state replay is not currently warranted.

## 1. What NMS already does

Three modules, read-only:

- **`nms_v3_classifier.py`** — the state machine `NORMAL → RANGE → EMERGING_UP/DOWN → STRONG_UP/DOWN`. Key constants:
  - `EVIDENCE_TTL_BARS = 24` (120 min — evidence older than this is dropped)
  - `EMERGING_ENTRY_THRESHOLD = 3`, `STRONG_ENTRY_THRESHOLD = 6`
  - `STRONG_MIN_HL_COUNT = 2` (strict structural anchor)
  - `PERSISTENCE_BARS = 2` (every transition takes 2 bar-closes)
  - `MAX_RANGE_REVERSALS_FOR_STRONG = 1` (strict)
  - Opening-Range Breakout `OR_WINDOW_BARS = 3`, `OR_BREAK_PIPS = 3` with 2-step confirmation
- **`nms_directional_authority.py`** — unified directional authority. Combines (a) NMS v3 state, (b) companion NMS from `normal_market_state.snapshot`, (c) Central Exhaustion Detector (`cache/nms_exhaustion_<SYM>.json`). Returns `DirectionalDecision` per candidate.
- **`session_trend.py`** — session trend state tracker; also owns `range_reversals` counter.

Critical already-implemented feature (code-inspected, `nms_directional_authority.py` doc lines 29-52):

> "An established directional trend (EMERGING or STRONG) must prevent an opposing bounce unless the prevailing movement has CONFIRMED exhaustion."

So NMS already consumes an **exhaustion** signal to permit counter-trend bounces during a strong-up/down trend. The signal source is `cache/nms_exhaustion_<SYM>.json` — not pivot-distance.

## 2. What NMS does NOT do

- **No notion of pivot distance.** `nms_v3_classifier` reads only the OR window + fractal swings + candle close relative to EMAs; no daily pivot level is consulted.
- **No "destination reached" trigger.** Once in `STRONG_UP`, the classifier stays there until score decays (TTL) or structural invalidation (C1 confirmed lower-high, 2 bars below `emerging_entry_price - 3p`, etc.). Price reaching R3 — a plausible "destination" per Phase 2's 59.8% reach-rate statistics — produces no state change.
- **No prior-pivot history.** Counting "how many pivots have we already touched this session" is not an input.
- **Exhaustion is a cache-file consumer**, not a pivot-aware computation. If the exhaustion detector doesn't fire at the pivot-touch moment, the admission authority doesn't know "we're at R2".

## 3. Mapping the 5 brief defects to code

| Brief defect | Likely NMS behaviour | Code reference |
|---|---|---|
| (a) Reports RANGE when a directional move is established | Possible. With `EVIDENCE_TTL_BARS = 24` and strict family caps (F-momentum ≤ 1, F-supporting ≤ 1), a slow but persistent trend that doesn't produce rapid structural evidence can let up_score decay below 3 and fall back to RANGE even while direction is intact. | `EVIDENCE_TTL_BARS`, `FAMILY_CAPS`, `_tt_live_score` |
| (b) Treats a pullback as a full reversal | Possible on EMERGING. Invalidation rule (c) is "any confirmed lower-high during EMERGING window → RANGE." On a healthy trend with any mid-session pullback that prints a confirmed lower-high, state falls back to RANGE even if the underlying trend is intact. | Classifier design property §3, invalidation rule (c) |
| (c) Continues admitting trend-followers near an exhausted destination | Yes — at the pivot sense of "destination." Nothing in `nms_directional_authority` says "block BUY if price is at R3." Trades admitted at R3 look identical to trades admitted at R1 or above the open. | `nms_directional_authority.py` matrix (no pivot term) |
| (d) Fails to recognise a confirmed breakout through S1/R1 | Partial. ORB breakout (E1) fires on OR-high ± 3p — not on S/R pivots. So a breakout through R1 that is NOT the OR high is not recognised as E1 evidence (though it may fire E3/E5 via other criteria). | `_advance_e1`, `OR_WINDOW_BARS`, `OR_BREAK_PIPS` |
| (e) Remains in WATCH after direction reconfirmed | WATCH_AND_WAIT is not an NMS v3 state — it's a session_trend overlay. The v3 classifier pass-throughs don't contain WATCH. If the overlay stays sticky after a v3 re-emergence, that's an overlay bug, not a classifier bug. | `session_trend.py` (further investigation required to confirm) |

Three of the five are real code-level opportunities; (d) is partial; (e) is in a different module.

## 4. Representative sessions (from Phase 2 CSV)

We selected 5 session categories and 2-3 example dates per category from the BID 2024-2025 window. For each, we describe the pivot interaction pattern without running the NMS replay — the goal is to identify which specific NMS behaviour would be exercised, not to produce a numerical NMS score sheet.

### A) Clean rejects (reject only, 60-bar outcome ≤ 15p — price touched the pivot and did NOT follow through)

- **2024-01-05 R2 UP @ 15:10** — mid-LN/NY overlap. 60-bar outcome ≤ 15p means price touched R2, retraced ≥ 10p within 15 bars, and never recovered past R2 for the next 5 hours.
- **2024-01-19 S1 DOWN @ 08:30** — London Open.
- **2024-01-17 S1 DOWN @ 06:10** — pre-London.

**Expected NMS failure mode:** on 2024-01-05, by 15:10 NMS v3 was probably in `STRONG_UP` or at least `EMERGING_UP` (R1 was touched earlier in the day). The `BUY ALLOW` matrix row would pass admission at R2 touch. No code in `nms_directional_authority` would flag "R2 is a candidate destination; downgrade this admission."

### B) Clean breakouts (60-bar > 30p, reached next pivot)

- **2024-01-05 R1 UP @ 15:00 → R2** — R1 touched, continued to R2 within an hour, 60-bar outcome >30p.
- **2024-01-08 R2 UP @ 15:10 → R3** — R2 touched, breakout to R3.
- **2024-01-23 S1 DOWN @ 14:30 → S2** — S1 broken, continued to S2.

**Expected NMS behaviour:** these are the "correct" cases where NMS stays `STRONG_UP`/`STRONG_DOWN` and admits trend-followers at each successive pivot — which continues to work. No defect here.

### C) Failed breakouts / stop sweeps (BOTH flags fired AND 60-bar outcome ≤ 20p)

- **2024-01-04 R2 UP @ 09:40** — London Morning. Breakout flag AND reject flag both fired → price crossed R2+10p then came back and reverted ≥ 10p the other way, all within 15 bars. 60-bar outcome ≤20p → price stalls out there.
- **2024-02-14 S1 DOWN @ 08:35** — London Open stop sweep.
- **2024-04-17 R1 UP @ 07:35** — London Open stop sweep at R1.

**Expected NMS failure mode:** this is a "stop-sweep followed by reversal" pattern — exactly what Phase 3 asked whether features can predict. We showed they cannot. For NMS specifically: on a 2026-01-04 breakout bar at 09:40, the v3 score could jump (E1/E3/E5 all plausible) → promote to STRONG_UP. Then the retrace triggers at least one C1 (lower-high) → EMERGING invalidation → back to RANGE. This is the *correct* response structurally, but the admission that occurred during the brief STRONG_UP window is already done. No mechanical NMS defect exists; the defect is that **no downstream gate said "we're at R2 UP after a breakout — verify before acting"**.

### D) Sustained bull trends (R1 + R2 + R3 all touched upward in one day)

- **2024-01-02, 2024-01-08, 2024-01-15, 2024-01-29**

**Expected NMS behaviour:** NMS v3 promotes to STRONG_UP by the time R2 is touched. Trend-follower trades are admitted at R2 and R3 — this is the "**continues admitting trend-followers near an exhausted destination**" defect (brief point c). From Phase 2: R3 UP shows a 59.8% reach-rate (lower than R1/R2) and a 50% reject+both rate (higher than R1/R2) in the LondonOpen session. Trades admitted at R3 touches have materially worse forward prospects than trades admitted at R1 touches — NMS does not distinguish.

### E) Sustained bear trends (S1+S2+S3 all touched)

Mirror of (D). Same defect.

## 5. Diagnostic opportunity

**Found.** The clearest, evidence-supported gap in NMS is **pivot-destination awareness**:

- Phase 2 reach matrix shows S3/R3 touches have ~40% chance of "no next pivot" (price stalls at the extreme). That's materially higher than S1/R1 touches (~22%).
- Phase 4 shows this is session-conditional: LN/NY overlap and LateNY in particular show 60% / 72% reject rates at R3 UP, vs 24% at R1 UP in LondonOpen.
- NMS's current admission matrix does not consume pivot location. All STRONG_UP admissions are equivalent.
- The exhaustion detector already exists as a cache-file consumer in `nms_directional_authority.py`. A pivot-destination signal could be *written* to that cache (same consumer shape) without any change to the classifier or the authority code.

## 6. Recommendation on full replay

Not needed yet. The code-level diagnostic is sufficient to proceed to Phase 8 recommendations. A full replay could be commissioned later to *quantify* the frequency at which the pivot-destination gap fires — but the gap's existence is established by inspection and does not depend on counting historical cases.

If a replay is later commissioned, the engineering plan is:
1. Build an isolated `nms_replay_harness.py` that starts with `fresh_state("GBPUSD", date)` at each session start and advances through all M5 bars. The classifier is already pure (no I/O per the module docstring) — a replay is possible deterministically **if** the companion NMS and exhaustion cache are both re-generated identically for the historical session, which is non-trivial.
2. Snapshot `v3_state` at each pivot-event timestamp from `pivot_events.csv`.
3. Join and report state transitions vs pivot touches.

This is a 1-2 day engineering job and should only be scheduled if the Phase 8 pivot-destination assessor recommendation is accepted and needs ex-ante sizing.
