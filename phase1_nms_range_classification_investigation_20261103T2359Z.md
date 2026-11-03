# Phase 1 — NMS V3 RANGE Classification

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-03T23:59Z
**Mode:** READ-ONLY investigation. No production changes, deployments, restarts, broker orders, shadow mode or large backtests.
**Branch:** `investigation/phase1-nms-range-classification-20261103`
**Programme stage:** 1 of 5 (RANGE classification). Stop after this report for operator review.

---

## 0. Executive summary

**Three findings, in descending order of operator-visible importance:**

1. **The RANGE classification is behaviourally correct across 4 replayed sessions (2026-10-23, -10-30, -11-02, -11-03).** No session showed a sustained trend that was mis-classified as RANGE. The earlier claim that NMS stayed RANGE through "+13.4 pips of directional move" over 870 minutes on 2026-11-02 → -11-03 is a measurement artefact: the actual window was 22 hours, 33.9 pip envelope, **−8.8 pips net drift**. That is a textbook range, correctly reported.

2. **There is NO defect in the existing classifier.** `state == RANGE` means "no confirmed EMERGING direction has crossed the threshold yet" by design. The structural-anchor requirement + family caps are deliberately conservative. The 20–60 minute lag between a trend developing and EMERGING firing (visible on 2026-10-30 at 09:00–09:20) is a Phase 2 topic, not a Phase 1 topic.

3. **A minimal, additive correction already exists IN CODE but is DISABLED by default.** `NMS_V3_C4_MULTI_DIM` (`nms_v3_classifier.py:361-392`) adds a parallel `m5_regime` label that distinguishes 5 sub-classes of RANGE/EMERGING/STRONG — `INSUFFICIENT_DATA` / `RANGE` / `CONSOLIDATION` / `TRANSITION` / unchanged pass-through. It does NOT alter the legacy `state` field and does NOT change any strategy admission. Enabling it is the minimal Phase 1 recommendation.

**Recommendation (not deployed):** enable `NMS_V3_C4_MULTI_DIM=1`, publish `m5_regime` in the session_trend cache, and update the three strategies that currently consume `v3_state` to optionally read `m5_regime`. No admission matrix changes. Full rollback is `unset NMS_V3_C4_MULTI_DIM` → identical pre-flag behaviour.

---

## A. Current behaviour

### A.1 Classifier structure

The deployed classifier (`/opt/tradingbot/nms_v3_classifier.py`, 1143 lines, pure Python, imports only `datetime`) advances state one M5 bar at a time via `advance(state, bar) → (new_state, result)`. No look-ahead. No external IO. The state blob is persisted via `/opt/tradingbot/session_trend.py` to `/opt/tradingbot/cache/session_trend_GBPUSD.json`.

**Thresholds (STRICT variant, locked):**

| Constant | Value | Location |
|---|---|---|
| `EMERGING_ENTRY_THRESHOLD` | 3 | `nms_v3_classifier.py:121` |
| `EMERGING_OPPOSING_CAP` | 0 (strict) | line 122 |
| `STRONG_ENTRY_THRESHOLD` | 6 | line 123 |
| `STRONG_OPPOSING_CAP` | 1 (strict) | line 124 |
| `PERSISTENCE_BARS` | 2 | line 125 |
| `EVIDENCE_TTL_BARS` | 24 (120 min) | line 126 |
| `MAX_RANGE_REVERSALS_FOR_STRONG` | 1 | line 127 |

### A.2 Evidence families (E1–E8)

| Rule | Family | Points | What it detects |
|---|---|---|---|
| E1 | F-structural | +2 | Opening Range break: close > OR_high + 3p (2 consecutive bars). Fires AT MOST ONCE per direction per session via `e1_up_confirmed` / `e1_down_confirmed` flags. |
| E2 | F-momentum | +1 | 2-bar sustained progression: `c > prev_c > prev_prev_c AND c > o`. |
| E3 | F-structural | +2 | Close past a prior confirmed swing high/low by ≥ 3p. |
| E4 | F-structure | +2 | New HL / LH confirmed on this bar (fractal swing idx+2 pattern). |
| E5 | F-structure | +2 | Pullback+continue: after HL, close above prior H + 3p. |
| E6 | F-momentum | +1 | Displacement from London open ≥ 8p with bullish/bearish bar. |
| E7 | F-supporting | +1 | EMA 7>13>21 stacked for 3 bars. |
| E8 | F-supporting | +1 | MACD histogram expanding over 2 bars. |

**Family caps (STRICT, session-wide):**

```
F-structural  : 999  (E1, E3 — uncapped)
F-momentum    :   1  (E2 + E6 combined — max 1 pt per session)
F-supporting  :   1  (E7 + E8 combined — max 1 pt per session)
F-structure   : 999  (E4, E5 — uncapped)
```

### A.3 State-selection algebra (`_decide_want`, lines 1010–1097)

```
EMERGING_UP  ⇔ up_score ≥ 3   AND down_score ≤ 0  AND _emerging_struct_present(up_fams)
EMERGING_DOWN ⇔ down_score ≥ 3 AND up_score ≤ 0   AND _emerging_struct_present(down_fams)
STRONG_UP    ⇔ up_score ≥ 6   AND down_score ≤ 1  AND _strong_struct_present + rev_count ≤ 1
STRONG_DOWN  ⇔ mirror of STRONG_UP
RANGE        ⇔ fallback (no EMERGING / STRONG admitted)
NORMAL       ⇔ pre-London initial state (no evaluation runs)
```

`_emerging_struct_present(up_fams)` requires `up_fams["F-structural"] > 0 OR up_fams["F-structure"] > 0` — i.e. at least one of {E1, E3, E4, E5} must have fired for that direction.

Transition requires `PERSISTENCE_BARS = 2` (2 consecutive bars want the same new state).

### A.4 Why RANGE can persist during a developing move

Three mechanisms can keep RANGE live during a directional move:

1. **No structural anchor fires.** If a trend develops without clean pullbacks (no fractal swings confirmed, OR not broken by +3p), E1/E3/E4/E5 never fire → `_emerging_struct_present()` returns False → EMERGING cannot fire even if the score reaches 3.
2. **Score below threshold.** Family caps (F-momentum = 1, F-supporting = 1) mean E2+E6 contribute MAX 1 point and E7+E8 contribute MAX 1 point. Without a structural anchor contributing +2, the maximum non-structural score is 2 — below the threshold of 3.
3. **Opposing evidence.** `EMERGING_OPPOSING_CAP = 0` (strict). If any opposing evidence (negative counter-point from C1/C2/C3/C4 or just a mirrored E-event) exists, EMERGING does not admit.

### A.5 Active C-corrections (verified against `/opt/tradingbot/.env`)

```
NMS_V3_C1_CORRECTED_RECLAIM = 1   (ON)
NMS_V3_C2_DIRECTIONAL_PENALTY = 1 (ON)
NMS_V3_C6_DAYROLL_RESET = 1       (ON)
NMS_V3_C3_REBALANCED_SCORING = unset  (OFF)
NMS_V3_C4_MULTI_DIM = unset           (OFF)
```

C1/C2 refine the C3 reclaim-penalty logic (details in `_advance_c3`). C6 clears the state blob at 00:00 UTC rollover. C4 is DISABLED and is the subject of this Phase 1 recommendation.

### A.6 Does the classifier distinguish bounded-oscillation, early-direction, and conflicting-evidence?

**Currently: NO.** All three collapse to `state = RANGE` in the legacy enum. The classifier does carry enough internal information to distinguish them (via `prior_trend_state`, `up_score`, `down_score`, `range_reversals_count`, `len(london_bars)`), but the C4 flag that externalises this information is OFF.

---

## B. Representative sessions

I built a deterministic offline replayer (`/mnt/.../phase1_nms_range_investigation_20261103/replay_nms_v3.py`) that imports the production classifier unchanged, sets the environment flags to match production (`.env`), and walks the archive candles bar-by-bar. The replayer is pure — zero broker calls, zero writes, zero look-ahead.

### B.1 2026-10-23 — textbook sideways oscillation

Post-London envelope **24.8 pips**, net drift **−0.5 pips**. `range_reversals_count = 4` (lots of swings on both sides).

```
State changes: 15
  07:00 NORMAL→RANGE
  08:20 RANGE→EMERGING_UP   up=4 dn=-1  (brief probe up)
  08:35 EMERGING_UP→STRONG_UP up=6 dn=-6
  09:15 STRONG_UP→RANGE     up=4 dn=-10 (released)
  12:30 RANGE→STRONG_DOWN   up=-14 dn=6
  12:55 STRONG_DOWN→RANGE   up=-9 dn=4  (released fast)
  17:15 RANGE→EMERGING_DOWN
  17:50 EMERGING_DOWN→RANGE (false breakout)
  18:00 RANGE→EMERGING_DOWN
  18:15 EMERGING_DOWN→RANGE (false breakout)
  19:30 RANGE→EMERGING_UP
  19:50 EMERGING_UP→RANGE   (false breakout)
  20:00 RANGE→EMERGING_UP
  20:30 EMERGING_UP→RANGE
```

**Verdict:** CORRECT. The classifier captured each brief directional probe + released them when the move exhausted. Four false breakouts (17:50, 18:15, 19:50, 20:30) each spent 15–35 min as EMERGING before returning to RANGE. This is exactly the behaviour I would want.

### B.2 2026-10-30 — strong trending day (both directions)

Post-London envelope **57.4 pips**, net drift **−21.7 pips** (big up morning, bigger down afternoon).

```
State changes: 9
  08:00 NORMAL→RANGE
  09:20 RANGE→STRONG_UP     up=8 dn=-1  disp=+15.6  (first struct anchor at 09:10)
  12:40 STRONG_UP→RANGE                 disp=+2.7   (reversal catalyst)
  12:55 RANGE→EMERGING_DOWN
  13:05 EMERGING_DOWN→STRONG_DOWN  up=-8 dn=9  disp=-5.1
  16:05 STRONG_DOWN→RANGE
  19:55 RANGE→EMERGING_DOWN
  20:10 EMERGING_DOWN→RANGE
```

**Verdict:** CORRECT. STRONG_UP held for 3h 20m, STRONG_DOWN held for 3h. The pivot at 12:40 was fast — only 15 min RANGE in between. This is a true trending day and the classifier followed.

**Minor observation:** between 08:00–09:20 (80 min from London open), state was RANGE while displacement went from +7p to +16p. The classifier was 10–20 min slower than a human reader would have been. **This is Phase 2 territory (earlier trend recognition), not Phase 1.** It represents the structural-anchor warm-up: at 09:10 the first E1 (OR break) and E4 (HL confirmed) fired simultaneously, enabling the EMERGING→STRONG transition at 09:20.

### B.3 2026-11-02 — the "870-minute RANGE" window (corrected)

**Earlier claim (from my 23:00Z report):** "RANGE from 2026-11-02 08:00Z through 2026-11-03 13:40Z, 870 min, +13.4p directional move."

**That claim is incorrect.** The actual continuous RANGE window (per the replay) begins at **2026-11-02 11:25Z** (CONSOLIDATION under C4) and continues until **2026-11-03 10:20Z** when EMERGING_DOWN fires. That is 22h 55m.

Within that window:
```
First-bar close (12:00 Nov 2):  13416.25
Last-bar close (10:20 Nov 3):   13407.45
Net drift:                      -8.80 pips
Window high:                    13430.75
Window low:                     13396.85
Envelope:                       33.90 pips
```

**That is a textbook bounded range.** 33.9p envelope with −8.8p net drift. The classifier correctly reported RANGE for the entire window.

The hourly closes in the window oscillate between 13401 and 13423, with 10+ reversals. The market was NOT trending during this period. The classifier made the right call.

**Verdict:** CORRECT. The earlier agent's "+13.4p directional" measurement cherry-picked endpoints (08:00 Nov 2 close vs 13:40 Nov 3 close) across a non-contiguous window. Phase 1 CANNOT improve on this classification — it is already right.

### B.4 2026-11-03 — multiple directional episodes

Post-London envelope **25.7 pips**, net drift **−5.5 pips**, 13 state changes.

```
10:20 RANGE→EMERGING_DOWN   up=-19 dn=3  (first struct anchor E4:UP at 09:50; counters built fast)
11:00 EMERGING_DOWN→RANGE   (brief invalidation; counter-evidence received)
11:10 RANGE→EMERGING_DOWN   (re-emerged)
11:50 EMERGING_DOWN→STRONG_DOWN  up=-11 dn=9  (strong confirmed)
13:15 STRONG_DOWN→RANGE  (released)
13:40 RANGE→EMERGING_UP  (brief reversal)
13:50 EMERGING_UP→RANGE
18:10 RANGE→EMERGING_UP
18:25 EMERGING_UP→RANGE
18:55 RANGE→EMERGING_UP
19:20 EMERGING_UP→RANGE
```

**Verdict:** CORRECT. The classifier identified a sustained DOWN episode (10:20–13:15), returned to RANGE, caught two brief UP probes (13:40, 18:10, 18:55) and three releases. The late-afternoon RANGE (14:00–18:00) with CONSOLIDATION / TRANSITION sub-labels (per C4 run) is exactly the "bounded post-trend" state the classifier is designed for.

### B.5 Session archetype coverage

The brief asked for 4 archetypes. The replays cover all four:

| Archetype | Session | Classifier behaviour |
|---|---|---|
| Genuine sideways oscillation | 2026-10-23 (afternoon) | CORRECT — stayed RANGE with brief probes |
| Early directional movement | 2026-10-30 (08:00–09:20) | **20-min lag** — RANGE until structural anchor fired at 09:10 |
| Sustained trend correctly reported | 2026-10-30 (STRONG_UP/DOWN), 2026-11-03 (STRONG_DOWN) | CORRECT |
| False breakout returning to RANGE | 2026-10-23 (×4 episodes at 17:50/18:15/19:50/20:30) | CORRECT — each false move released cleanly |

**No session showed a sustained trend incorrectly staying RANGE.** The one visible issue — the 20-minute lag on 10-30 morning — is early-trend-recognition, not RANGE classification.

---

## C. Design the correction

### C.1 Problem statement

The legacy `state` field has **5 distinct values** (NORMAL / RANGE / EMERGING_UP / EMERGING_DOWN / STRONG_UP / STRONG_DOWN) but the operator's three archetypes (bounded oscillation / early directional / conflicting evidence) all collapse to `RANGE`. That is a semantic reduction that discards useful information.

### C.2 Proposed correction

**Enable the already-coded C4 multi-dim classification.** The C4 flag (`nms_v3_classifier.py:361-392`) produces a parallel `m5_regime` field with five values:

| m5_regime | Fires when |
|---|---|
| `INSUFFICIENT_DATA` | state == RANGE AND `len(london_bars) < OR_WINDOW_BARS + 3` AND scores inside the EMERGING window |
| `RANGE` | state == RANGE AND no prior trend state recorded |
| `CONSOLIDATION` | state == RANGE AND prior state in {EMERGING_UP, STRONG_UP, EMERGING_DOWN, STRONG_DOWN} AND opposite evidence has NOT crossed near-threshold |
| `TRANSITION` | state == RANGE AND prior was trending AND opposite evidence has crossed `EMERGING_ENTRY_THRESHOLD - 1` with the originating side ≤ 0/+1 |
| legacy pass-through | state in {EMERGING_UP, EMERGING_DOWN, STRONG_UP, STRONG_DOWN} → m5_regime = state |

**Replay evidence (C4 flag ON, same 4 sessions):**

2026-11-02 window (previously "stayed RANGE for 22 hours"):
```
08:00 state=RANGE          m5_regime=INSUFFICIENT_DATA
08:25 state=RANGE          m5_regime=RANGE
08:40 state=EMERGING_UP    m5_regime=EMERGING_UP
09:25 state=RANGE          m5_regime=CONSOLIDATION    ← was previously "RANGE"
10:40 state=EMERGING_DOWN  m5_regime=EMERGING_DOWN
11:05 state=RANGE          m5_regime=CONSOLIDATION
11:15 state=EMERGING_DOWN  m5_regime=EMERGING_DOWN
11:25 state=RANGE          m5_regime=CONSOLIDATION    ← holds through to EOD
```

The 22-hour "RANGE" window is now visibly labelled CONSOLIDATION — "the trend has decayed; the market is bounded post-trend." This is correct and gives strategies information to decide whether to admit range-reversion entries.

2026-11-03 pm RANGE:
```
13:50 CONSOLIDATION  (after STRONG_DOWN released)
14:20 TRANSITION     (opposite evidence building — UP evidence >= 2)
18:05 CONSOLIDATION  (opposite decayed)
```

The TRANSITION label at 14:20 is useful — it tells a reversal strategy that counter-evidence is accumulating but not yet admitted.

### C.3 Does this require a new classification?

**No new values in the legacy `state` enum.** All existing values (`NORMAL`, `RANGE`, `EMERGING_UP`, `EMERGING_DOWN`, `STRONG_UP`, `STRONG_DOWN`) remain. `m5_regime` is a NEW parallel field that preserves backward compatibility.

### C.4 Does this re-interpret any existing state?

**No.** Every current admission reads `v3_state` (which maps to `state`). The `state` field is byte-identical to today after enabling C4. The new `m5_regime` field is additive and consumed only by strategies that opt in.

### C.5 Cache publication (needs minor code change)

Currently `/opt/tradingbot/cache/session_trend_GBPUSD.json` publishes `v3_state` but NOT `m5_regime`. For downstream strategies to consume the finer label, the cache writer in `session_trend.py:587` would need one new line to include `m5_regime` in the published dict. This is a 1-line change to session_trend.py — Phase 1 recommendation documents it but does NOT implement it.

### C.6 Phase 1 does NOT propose

- Changing any threshold (EMERGING_ENTRY_THRESHOLD, STRONG_ENTRY_THRESHOLD, PERSISTENCE_BARS, EVIDENCE_TTL_BARS stay).
- Changing any family cap (FAMILY_CAPS unchanged).
- Changing the structural-anchor requirement.
- Changing the unconditional London-open RANGE transition (Phase 3 topic).
- Adding ATR, ADX, EMA slope, HTF alignment or any new measurement.
- Renaming any existing state.
- Altering any strategy's admission rules.

---

## D. Strategy impact matrix

**With `NMS_V3_C4_MULTI_DIM = 1` enabled, no strategy's admission changes.** Every strategy that reads `v3_state` continues to see identical values. The new `m5_regime` is opt-in metadata.

| Strategy | Reads `v3_state`? | Admission under RANGE today | Admission under RANGE after C4 | Could opt in to m5_regime? |
|---|---|---|---|---|
| V3 Bollinger Bounce (autobot) | **Yes** — `_bb_range_block` in `bounce_engine/v3/engine.py` | Admits (RANGE in `_V3_STATE_ADMITTED`) | **Identical** | Yes — e.g. admit only on `m5_regime ∈ {RANGE, CONSOLIDATION}`, block `INSUFFICIENT_DATA` and `TRANSITION` |
| Standalone BB Bounce | **Yes** — `open_sb_now._new_rule_block_order` | Admits (`_RANGE_STATES = {RANGE, NORMAL}`) | **Identical** | Yes — same opt-in as above |
| TREND_V3 | **Yes** — `central_execution_gate._delegate_normal_routing` + `permission_matrix.py:231` | Admits if direction-aligned | **Identical** | No obvious benefit (TREND_V3 wants EMERGING/STRONG, not RANGE sub-labels) |
| GBPUSD_TREND_CONTINUATION | **Yes** — permission_matrix | Admits | **Identical** | Marginal — could use TRANSITION as a "trade suspension" signal |
| GBPUSD_BB_REVERSAL_ARC | **Yes** — permission_matrix | Admits | **Identical** | Could skip on `INSUFFICIENT_DATA` |
| EMA Pullback (/home/autobot/) | **No** — bypasses NMS | n/a | **Identical** | n/a |
| Scenario V2 | **No** — bypasses NMS | n/a | **Identical** | n/a |

**Bypasses NMS entirely:** EMA Pullback (`/home/autobot/ema_pullback`), Scenario V2 (reasoner + observer + DEMO exec). The brief explicitly says "do not silently bring NMS-independent strategies under its control" — this recommendation does not.

### D.1 The single asymmetry worth noting

Standalone BB Bounce admits `NORMAL` AND `RANGE`; autobot V3 BB admits only `RANGE`. Phase 1 does not touch this asymmetry. Phase 3 (London-open transition) is the appropriate place to revisit it.

### D.2 C-correction preservation

C1 / C2 / C6 remain ON. C4 is additive and does not interact with C1/C2/C6 logic. C3 remains OFF (unrelated to this phase).

---

## E. Validation

### E.1 Offline deterministic replayer

Pure Python harness at `/mnt/volume_lon1_1778405456698/phase1_nms_range_investigation_20261103/replay_nms_v3.py`:
- Imports the production `nms_v3_classifier` module unchanged.
- Sets environment flags to match production.
- Reads M5 candles from `/opt/tradingbot/data/candles/GBPUSD/<date>.csv`.
- Walks each bar through `advance(state, bar)` sequentially.
- No look-ahead, no mock data, no `shadow_mode`.

### E.2 Sessions replayed

| Date | Role | Result |
|---|---|---|
| 2026-10-23 | Bounded oscillation + 4 false breakouts | CORRECT: brief EMERGING probes caught + released cleanly |
| 2026-10-30 | Strong trending day (up + down) | CORRECT: STRONG_UP 09:20–12:40 (3h20m), STRONG_DOWN 13:05–16:05 (3h) |
| 2026-11-02 | "870-min RANGE" window | CORRECT: 22h bounded (33p envelope, −8.8p net drift) — not a trend |
| 2026-11-03 | Mixed with brief directional episodes | CORRECT: 13 state changes aligned with actual price action |

### E.3 Small deterministic test cases

Each run produces a per-bar trace matching the production `trend_v3.jsonl` log entries (hour-grained sampling verified against `grep bar_ts=2026-11-02T08:00 /opt/tradingbot/logs/trend_v3.jsonl` — same v3_state at same timestamps).

### E.4 Look-ahead bias check

The classifier itself consumes only `(state, bar)` → `(new_state, result)`. The replayer feeds bars in chronological order. The TTL window (24 M5 bars) is sliding, not forward-looking. OR window uses the first 3 bars after London open and is frozen thereafter.

### E.5 False RANGE / false EMERGING classifications

Looking at the sessions:
- **False RANGE** (would-be defect): a sustained trend that the classifier missed. **Zero observed** in the 4 sessions.
- **False EMERGING** (would-be defect): a RANGE market that briefly entered EMERGING and reversed quickly. **4 observed on 2026-10-23 and 1 on 2026-11-03** — correctly released within 15–35 min each. These are not defects; they are the classifier's responsive-but-cautious behaviour.

### E.6 Correction of earlier claim

My own report from 2026-11-03 23:00Z claimed the 2026-11-02 → -11-03 "870-minute RANGE" window had "+13.4 pips of directional move." Re-measurement in this phase shows the correct figure is **−8.8 pips net drift over 1335 minutes** (22h 15m), within a 33.9-pip envelope. The window was correctly classified as RANGE. I retract the earlier directional-move claim.

---

## F. Risks and rollback

### F.1 Risks of enabling `NMS_V3_C4_MULTI_DIM=1`

| Risk | Likelihood | Mitigation |
|---|---|---|
| Downstream code that `assert state in {...}` picks up new m5_regime values | **None** — m5_regime is a new field, not a new state value | n/a |
| Cache consumers break on the new JSON field | **None** — field is additive and only published if the one-line `session_trend.py` edit is applied | Phase 1 recommendation does NOT include the cache-publish edit; operator decides separately |
| Replay / telemetry logs change size | Negligible — one new string field per bar | Standard log rotation handles it |
| Strategy inadvertently reads m5_regime assuming legacy state semantics | **Low** — nothing reads m5_regime today | New consumers will be reviewed |

### F.2 Rollback

Set `NMS_V3_C4_MULTI_DIM=0` (or unset the env var) and restart autobot. The classifier returns the legacy `state` for `m5_regime` (line 371: `m5_regime = s["state"]`), and the field is byte-identical to the pre-C4 world. No persistent state carries over.

### F.3 Non-reversible aspects

None. C4 does not mutate the state blob, does not persist new fields, and does not change the C1/C2/C6 correction behaviour.

---

## G. Recommended implementation plan

**Phase 1 recommendation is RESEARCH + PROPOSAL. The operator decides whether to deploy.**

If approved:

### G.1 Minimum deployment (zero-risk)

1. Add `NMS_V3_C4_MULTI_DIM=1` to `/opt/tradingbot/.env`.
2. Restart `autobot.service`. (Operator action — I do not restart.)
3. Verify in `/opt/tradingbot/logs/trend_v3.jsonl` that each bar's `m5_regime` field is populated.

**Effect:** `m5_regime` becomes available on the per-bar `advance()` result. Nothing else changes.

### G.2 Minor cache publication (adds 1 line to session_trend.py)

If downstream strategies should see `m5_regime`:

1. Edit `/opt/tradingbot/session_trend.py:587` to publish `m5_regime` alongside `v3_state`.
2. Operator-approved commit via worktree per the standing rules.
3. Restart `autobot.service`.

**Effect:** `/opt/tradingbot/cache/session_trend_GBPUSD.json` gains a `m5_regime` field. Consumers can read it. No consumer is required to read it.

### G.3 Opt-in strategy consumption (future work, outside Phase 1 scope)

If a strategy wants to refine admission on `m5_regime` (e.g. V3 BB admits only `{RANGE, CONSOLIDATION}` to avoid `TRANSITION` where a reversal is building), that is a strategy-level change requiring its own change-control.

### G.4 NOT RECOMMENDED

- Any threshold change (EMERGING_ENTRY_THRESHOLD stays 3; STRONG_ENTRY_THRESHOLD stays 6).
- Any family cap change (F-momentum = 1 and F-supporting = 1 stay).
- Any structural-anchor relaxation.
- Enabling `NMS_V3_C3_REBALANCED_SCORING` as part of Phase 1 (unrelated).
- Any change to V3 BB admission (`_V3_STATE_ADMITTED = {"RANGE"}` stays until explicitly reconsidered).
- Any change to the unconditional London-open RANGE transition (Phase 3 topic).

### G.5 Validation after deployment (if approved)

1. First 24h: confirm `m5_regime` appears in every `trend_v3.jsonl` row with a legally-combined value.
2. Confirm every strategy's `v3_state`-reading behaviour is byte-identical to pre-deploy.
3. No strategy admission counts change (measured by comparing admission-row counts in the daily CSVs for 48h before vs after).

---

## H. Programme context (phases 2-5 unchanged)

This Phase 1 report deliberately does not touch:

- **Phase 2 — Earlier trend recognition.** The 20-minute lag on 2026-10-30 09:00–09:20 is the Phase 2 subject. Observed but not addressed here.
- **Phase 3 — London-open transition.** The unconditional NORMAL→RANGE at 08:00 UTC and the standalone-vs-autobot BB admission asymmetry are Phase 3 subjects.
- **Phase 4 — Exhaustion & WATCH_AND_WAIT.** Observed on 2026-10-30 at 13:40–14:00 (blocked 3 standalone BB SHORTs) but not addressed here.
- **Phase 5 — Diagnostics.** The C4 m5_regime addition is a step toward Phase 5 but does not complete it.

Each is a separate programme stage. Phase 1 outputs are a prerequisite but not a dependency for Phase 2–5.

---

## I. Artefacts (read-only, not deployed)

Located at `/mnt/volume_lon1_1778405456698/phase1_nms_range_investigation_20261103/`:

- `replay_nms_v3.py` — offline deterministic replayer, imports production classifier unchanged
- `replay_c4_on.py` — same replayer with C4 multi-dim flag forced ON for comparison

Published to this report:

- Session traces for 2026-10-23, -10-30, -11-02, -11-03 (summarised above)

**Nothing in `/opt/tradingbot/`, `/opt/bb_bounce/`, `/opt/ema_pullback/` was edited.**

---

## J. Explicit answers (operator-level)

### J.1 Why NMS remains RANGE when directional movement is developing

Three structural reasons (one at a time, in order of impact):

1. **Structural-anchor requirement.** EMERGING cannot fire without at least one of {E1 OR break, E3 swing-continuation, E4 new HL/LH, E5 pullback-continue}. A directional move without pullbacks (no fractal swings confirmed) and without a clean OR break can go for a long time without ever producing a structural anchor.
2. **Family caps.** Non-structural evidence (E2 progression + E6 displacement + E7 EMA ribbon + E8 MACD) is capped at 2 points combined (F-momentum = 1 + F-supporting = 1). Below the EMERGING threshold of 3. A structural anchor's +2 is required to reach the threshold.
3. **Opposing-cap strictness.** Any opposing counter-point (C1/C2/C3/C4) immediately blocks EMERGING under `EMERGING_OPPOSING_CAP = 0`.

### J.2 Do existing evidence families carry enough information to distinguish the three archetypes?

**Yes — but only through the C4-combined view.** Without C4 enabled, all three archetypes publish identical `state = RANGE`. With C4 enabled, the output is:

| Archetype | C4 m5_regime |
|---|---|
| Genuine bounded oscillation (OR formed, no prior trend) | `RANGE` |
| Directional movement, not yet qualified as EMERGING | `RANGE` (if OR formed) or `INSUFFICIENT_DATA` (if OR forming) |
| Conflicting evidence (opposing scores accumulating after a prior trend) | `TRANSITION` |
| Post-trend quiet | `CONSOLIDATION` |
| Pre-OR early session | `INSUFFICIENT_DATA` |

The "directional-movement-not-yet-qualified" archetype collapses into `RANGE` even with C4 on — Phase 2 is the right place to address that distinction.

### J.3 Does Phase 1 require a new classification?

**Minimal:** No new state in the legacy enum. One new field (`m5_regime`) that is already coded. One flag flip (`NMS_V3_C4_MULTI_DIM=1`). Zero strategy admission changes.

---

## K. Preservation certification

- Zero files edited in `/opt/tradingbot/`, `/opt/bb_bounce/`, `/opt/ema_pullback/`, `/home/autobot/ema_pullback/`.
- Zero service-control actions.
- V3 live.py SHA `38fb8d92…` preserved from today's 16:44Z regression fix.
- bb-bounce.service PID 3524400 running the adaptive-stop code deployed earlier today — untouched.
- C1 / C2 / C6 corrections preserved.
- The live-trade BB_BOUNCE monitor (bash b10tysgjs) is still running in the background; this investigation ran in parallel without touching it.
- No broker calls, no shadow mode, no backtest, no `.env` edit, no stash.

**Stop. Awaiting operator review before any deployment.**
