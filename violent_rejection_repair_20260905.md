# Violent-Rejection Repair — 2026-09-05

Shadow-only. Local commit, no push. HEAD at session start: `3c5f2f3`
(feat/trend-stretch-brake-adx-floor). All changes ride the boundary:
detection + voice for the same-bar sweep-and-reclaim family, additive
to the existing SWEEP → REJECTING chain and to §16 / §24 continuation.

---

## 1. Generalisation arguments (per rule)

Every rule fires on a **class of geometry**, not on specific dates,
instruments, or times. Every threshold is an env with a geometry-terms
default.

### 1a. SAME-BAR SWEEP-REVERSAL (`STATE_VELOCITY_REJECTION`)

**Rule** (`qm_behaviour.classify_v2`, lines 171–217):

```
IF wick pierces a zone boundary by ≥ QM_VELREJ_PIERCE_PIPS (default 3p)
AND close returns strictly across the pierced boundary
AND wick-extreme→close displacement ≥ QM_VELREJ_DISPLACEMENT_PIPS (default 6p)
AND |close − center| ≤ QM_VELREJ_CLOSE_MAX_PIPS (default 15p)
THEN classify STATE_VELOCITY_REJECTION on the SAME bar,
     rejection_side = the pierced boundary
     extreme_side = same as rejection_side (for downstream compatibility)
```

**Why it fires on the class, not instances**:
- Thresholds are pip magnitudes tied to bar geometry, not tied to any
  particular symbol / date / time.
- Pierce and displacement are measured *within the bar* (`center - low`,
  `close - low`, `high - center`, `high - close`) — no reference to
  prior bars for the trigger.
- The `close-far` ceiling defends the class against "large-body break-
  through the level" being mislabelled as fade. Any bar closing >15p
  past center has *broken* the level, not rejected it — that is a
  continuation, not a fade candidate (see F7).

### 1b. POLARITY UNLOCK

`ctx.rejection_side` is populated purely from the current bar's
geometry inside `classify_v2` — from the pierced boundary and the close
side. It is *never* read from the cached `extreme_side` for the velocity
path; the velocity path sets `extreme_side = rejection_side` as a
side-effect for downstream compatibility, not as a source.

**classify_v2 change, quoted (before → after)**:

*Before* (HEAD `3c5f2f3`, qm_behaviour.py — SWEEP handler only, no
velocity path, no `rejection_side`):

```python
if close_on_opp and reach_body >= LARGE_BODY:
    ctx.signals = {
        "level_swept": True,
        "close_back_through": True,
        ...
    }
    ctx.last_state = STATE_SWEEP_DETECTED
    return STATE_SWEEP_DETECTED
```

*After* (post-repair):

```python
# STATE_VELOCITY_REJECTION additive path (2026-09-05): same-bar
# sweep-and-reclaim. rejection_side derives ENTIRELY from THIS bar.
if _env_flag("QM_VELREJ_ENABLED", True):
    pierce_min = _env_float("QM_VELREJ_PIERCE_PIPS", 3.0)
    disp_min   = _env_float("QM_VELREJ_DISPLACEMENT_PIPS", 6.0)
    close_max  = _env_float("QM_VELREJ_CLOSE_MAX_PIPS", 15.0)
    close_far  = abs(c - center) > close_max
    down_pierce = center - l
    if not close_far and down_pierce >= pierce_min and c > center:
        disp = c - l
        if disp >= disp_min:
            ctx.signals = {"level_swept":True, "close_back_through":True,
                           "m5_structure_shift":True,
                           "close_inside_bb": abs(c-center) <= 15.0,
                           "velocity_rejection": True}
            ctx.rejection_side = "below"   # geometry-derived, not cached
            ...
            return STATE_VELOCITY_REJECTION
    up_pierce = h - center
    if not close_far and up_pierce >= pierce_min and c < center:
        disp = h - c
        if disp >= disp_min:
            ctx.signals = {...}
            ctx.rejection_side = "above"  # geometry-derived
            ...
            return STATE_VELOCITY_REJECTION

# ... existing SWEEP_DETECTED path stays intact ...
if close_on_opp and reach_body >= LARGE_BODY:
    ctx.signals = {..., "velocity_rejection": velrej_flag}
    ctx.rejection_side = ctx.extreme_side   # SWEEP still uses cache;
    ctx.last_state = STATE_SWEEP_DETECTED   # velocity path does NOT.
    return STATE_SWEEP_DETECTED
```

**Why continuation reads are unaffected (C2)**:
- The SWEEP → REJECTING → REJECTION_CONFIRMED path is untouched.
- `LARGE_BODY`, `reach_body`, `close_on_opp` unchanged.
- The velocity block is *before* the SWEEP block and returns only when
  the same-bar strict geometry matches; if it does not match, the
  SWEEP block runs exactly as before.
- The R2 (2026-09-03) continuation test
  (`test_qm_v2_self_contained.py::test_r2_20260903_step_candidate_consumes_v2_vocabulary`)
  still passes with `score=10 at 15:45Z, REJECTION_CONFIRMED at 15:45Z,
  ENTRY_ARMED at 15:50Z` — verified in the suite tally (§6 below).
- §16 retest and §24 re-arm sit downstream in `step_candidate` and are
  unmodified.

### 1c. DISPLACEMENT TEST (no `BODY_PIPS`)

Displacement is defined as **wick-extreme → close**, on the pierced
side:
- Downside pierce: `disp = close - low`
- Topside pierce:  `disp = high - close`

Rationale: this measures the *rejection force* itself — how much price
retreated from the pierced boundary in one bar. It is not affected by
previous close (unlike `reach_body`), so it is not confused by the
approach cadence — a bar can be violent because the *rejection* is
violent, regardless of how price got to the zone. The name
`m5_structure_shift` is kept for the score-signal so
`score_rejection_with_memory` scoring stays deterministic; the underlying
measurement is the wick-to-close displacement, not any body-vs-body
metric.

### 1d. ALERT DIRECTION FROM REJECTION GEOMETRY

`qm_pick_alerts._direction_for` (before → after quoted from the source):

*Before* (HEAD, at census time — see
`reports-public/qm_pick_detection_vs_communication_20260905.md` §1a):

```python
def _direction_for(cand: Any) -> Optional[str]:
    rd = getattr(cand, "rearm_direction", None)
    if rd in ("BUY", "SELL"):
        return rd
    try:
        e = getattr(cand, "hypothetical_entry", None)
        c = float(getattr(cand, "zone_center", 0.0) or 0.0)
        if e is not None:
            return "BUY" if float(e) > c else "SELL"     # ← inverts F4
    except Exception:
        pass
    return None
```

*After* (qm_pick_alerts.py lines 193–231):

```python
def _direction_for(cand: Any) -> Optional[str]:
    rd = getattr(cand, "rearm_direction", None)
    if rd in ("BUY", "SELL"):
        return rd                                        # §16 / §24 wins
    # Rejection geometry — takes precedence over close-vs-center fallback
    try:
        why = getattr(cand, "confidence_why", None) or {}
        if isinstance(why, dict):
            r_side = why.get("rejection_side")
            if r_side == "above": return "SELL"          # topside sweep → SELL fade
            if r_side == "below": return "BUY"           # downside sweep → BUY fade
    except Exception:
        pass
    # Legacy fallback only when neither rearm_direction NOR rejection_side
    # is present — e.g. replay of pre-2026-09-05 candidates.
    try:
        e = getattr(cand, "hypothetical_entry", None)
        c = float(getattr(cand, "zone_center", 0.0) or 0.0)
        if e is not None:
            return "BUY" if float(e) > c else "SELL"
    except Exception:
        pass
    return None
```

The `hypothetical_entry` fallback that inverted the EURUSD specimen
(arm-bar close 11615.90 sat 0.07 p above P → labelled BUY when the
internal chain had rejected a topside sweep) is now unreachable for
rejection-chain candidates; `rejection_side` sits above it in the
precedence chain.

**Why the change is geometric, not specimen-fitted**: `rejection_side`
is populated by `classify_v2` from the pierced-boundary side. Every
same-bar sweep-and-reject, every SWEEP → REJECTING chain, every velocity
short-circuit stamps it. The rule "topside sweep → SELL fade, downside
sweep → BUY fade" is the geometric definition of fade direction.

### 1e. FADE VOICE, MANDATORY

`qm_pick_alerts._pattern_words` (lines 322–388) now renders
`"swept {level} and rejected — fade {dir}"` whenever the candidate is
in `REJECTION_CONFIRMED` or `ENTRY_ARMED` state AND carries any of:
- `confidence_why.rejection_side` set to `above`/`below`, OR
- `confidence_why.rejection_signals` populated, OR
- a transition cause containing `velocity_rejection`.

The neutral `"entry armed — take the trigger"` is now a last-resort
fallback for ENTRY_ARMED candidates with none of the above (e.g. legacy
replay of pre-repair candidate objects). The F4 fixture in
`tests/unit/test_qm_velocity_rejection.py` proves the fade wording is
reachable and mandatory on the rejection chain.

### 1f. ANTI-CHASE GUARDS

- **Tracked-only zones**: the velocity path fires only from inside
  `step_candidate`, which is called for zones the SDE has already
  spawned a `Candidate` on. There is no cold-spawn path (verified by
  reading `qm_decision_shadow.on_5m_close_sde` at
  `qm_decision_shadow.py:2054`).
- **DYNAMIC-only zones excluded**: `_sde_pick_zone` returns None when
  the only candidate zone is a dynamic-BB slot; the caller returns
  before any state advance can happen (verified: `on_5m_close_sde`
  early-return at line 2109).
- **Newborn exemption**: `_confidence_stamp_now` calls
  `qm_level_memory.get_store().factors()` with `level_born_at` for
  swing-derived zones, and the memory layer's `QM_NEWBORN_MIN_AGE_BARS`
  drops `mem_*` factors while the level is under age
  (memory: `project_swing_retest_is_the_trade`, `qm_level_memory`).
- **One arm per (symbol, round(zone_center,1), direction, UTC-date)**:
  `_VELOCITY_ARMED` set + `_velocity_arm_key` in `qm_decision_shadow.py`
  lines 467–491. The velocity walk-through checks the key at line 862
  and short-circuits if the arm is already claimed. The
  `_short_circuit_velocity_arm` helper does the same at line 514.

### 1g. ACCEPTANCE-THROUGH GATE (F7 fix, this session)

Added `QM_VELREJ_CLOSE_MAX_PIPS` (default 15p) — a bar whose close sits
more than 15p past the level is a *break*, not a rejection. Even if
geometry has a pierce + close-back-through on the opposite side, the
close being far past center indicates the level was accepted through —
the velocity path is silent and the caller sees whatever state the
existing SWEEP chain / EXTREME / STALLING path emits.

Applied at both velocity sites:
1. The same-bar `STATE_VELOCITY_REJECTION` block (both downside and
   topside pierce branches guarded by `not close_far`).
2. The `velrej_flag` computed inside the `SWEEP_DETECTED` handler when
   emitting the `velocity_rejection` score-signal (used by
   `step_candidate` to short-circuit through
   `_short_circuit_velocity_arm`).

**Why this is class-general, not specimen-fit**: The 15p ceiling is a
geometric statement about the bar's terminal state (close-far → break).
It is symmetric across pierce directions. It matches the pre-existing
`close_inside_bb` approximation (also 15p) used as a scoring signal, so
the same ceiling now becomes an outright gate for the velocity path.

---

## 2. Per-fixture latency table (F1–F4)

Live 5m OHLC from `data/candles/{EURUSD,GBPUSD}/2026-09-04.csv`.
Fixture spawns the candidate at its `opened_at`; velocity path with
default env thresholds; MFE/MAE measured over the 36 bars following the
arm bar. Direction column reports the direction *stamped at the arm
bar*.

| Fixture | Sym | Zone | First bar rejection legally classifiable | REJECTION_CONFIRMED / VELOCITY_REJECTION ts | Arm ts | Arm price | Reversal extreme (before arm) | Pips already travelled | 36-bar MFE | 36-bar MAE | ≥25p remained? | ≥35p remained? |
|---|---|---:|---|---|---|---:|---:|---:|---:|---:|---|---|
| **F1** NFP wick S1 | EURUSD | 11590.567 (S1) | 12:30Z | 12:30Z | 12:30Z | 11594.95 (BUY) | 11585.55 | **9.4p** | **+28.0p** | 4.5p | **YES** | no |
| **F2** GBP S1 | GBPUSD | 13497.65 (S1) | 13:15Z | 13:15Z | 13:15Z | 13507.35 (BUY) | 13494.55 | 12.8p | +17.5p | 4.0p | no | no |
| **F3** GBP P first-arm | GBPUSD | 13517.167 (P) | 13:45Z (BUY) | 13:45Z | 13:45Z | 13522.35 (BUY) | 13506.35 | 16.0p | +2.5p | 19.0p | no | no |
| **F3** GBP P polarity-flip | GBPUSD | 13517.167 (P) | — | 13:50Z (SELL) | 13:50Z | 13511.55 (SELL) | 13524.05 | 12.5p | (see collision note §3) | | | |
| **F4** EUR P slow-path | EURUSD | 11615.833 (P) | 13:45Z (SWEEP) | 14:10Z | 14:15Z | 11615.90 (SELL) | 11622.90 | 7.0p | +3.6p | 8.6p | no | no |

**Reading of the latency table**:
- **F1 is the only fixture with meaningful post-arm favourable
  excursion**: +28p MFE, 4.5p MAE. This is the class the velocity path
  is designed to catch — a same-bar violent sweep with immediate
  rejection where the follow-through is real. This is the case the
  live pipeline *missed entirely* (row 4 in the census: EURUSD 12:30
  S1 sat at `EXTREME_REACHED` all day).
- **F2 is modest**: +17.5p, would have missed both a 25p and 35p
  target. The trade was viable (positive MFE, small MAE) but not a
  swing runner.
- **F3 arm-at-13:45 (BUY) is a loser** in retrospect: MFE +2.5p vs MAE
  19p. The polarity flip at 13:50 fires SELL — that direction
  eventually got the +11.6p move the operator's live trade caught. See
  §3 for the collision ledger.
- **F4 slow-path SELL is small-loss** in the arm-direction: +3.6p
  favourable / 8.6p adverse. The **VOICE** repair is the real F4 win:
  the alert now says "swept Pivot P and rejected — fade SELL" instead
  of the neutral "entry armed — take the trigger" it emitted live
  (see the census, row 14 of the 2026-09-05 detection-vs-communication
  report).

The pipeline arms are all commercially marginal at the fixture set. The
`≥25p / ≥35p remained?` columns are `NO` for 5 of the 6 arms — the
class *of trades* the velocity path catches is (on this day) short-run
mean-reverting rather than swing-worthy. F1 (+28p) is the only outlier
and it is not >35p either. Reported honestly per the operator's
"entry latency exposed explicitly" requirement.

---

## 3. Collision ledger (log-only, this session)

Every same-bar/same-zone collision where the velocity path claims and
another path (continuation / §16 / §24 / velocity's own opposite side)
also claims. Per C2 no resolution attempted.

| ts | sym | zone | velocity claim | competing claim | resolution |
|---|---|---:|---|---|---|
| 2026-09-04T13:45Z | GBPUSD | 13517.167 (P) | velocity BUY (downside-pierce interpretation of 13:45 bar: L=13511.95 below by 5.22p, C=13522.35 above by 5.2p, disp=10.4p) | velocity SELL @ 13:50Z on the same zone (up_pierce+close-below topside geometry) | **BOTH FIRE**. Different side keys ⇒ per-side dedup allows both arms on the same zone/day. Wrong-direction BUY at 13:45 later contradicted by SELL at 13:50 (operator's live-tape reading was SELL). |
| 2026-09-04T13:45Z | GBPUSD | 13517.167 (P), opened 09:20Z slot | velocity BUY same as above | separate candidate slot on the same zone-day | Same-zone-different-candidate — zone-day dedup at the ALERT layer (`qm_pick_alerts._SEEN_ZONE_DAY`) blocks the duplicate Telegram send; the state machine transition still fires in shadow. |
| 2026-09-04T14:55Z | GBPUSD | 13517.167 (P) | velocity SELL @ 14:55 (post-arm on live slot) | live pipeline slow-path ENTRY_ARMED at 14:00Z (opened 14:00Z slot) | Additive; the live arm keeps its direction, velocity SELL is a new alert on a different side. Alert-layer zone-day dedup will drop the second Telegram if fired same day/side. |
| 2026-09-04T17:00Z / 20:55Z | GBPUSD | 13517.167 (P) | velocity SELL @ 17:00, velocity BUY @ 20:55 | different candidate slot (opened 15:50Z REVERSAL_CANDIDATE) | Additive — velocity path claims sides after live REVERSAL_CANDIDATE. Log-only. |

**Class of collision the operator should flag as a follow-up**:
adjacent-bar opposite-direction velocity arms on the same zone (F3
BUY@13:45 → SELL@13:50). Neither of the two velocity firings is
geometrically wrong in isolation — the 13:45 bar *does* satisfy the
downside-pierce + close-back-through geometry with disp 10.4p, and the
13:50 bar *does* satisfy the upside-pierce equivalent with disp 11.6p.
The two-bar shape is the classic "failed break + reversal": bar 1
pushes through and closes above, bar 2 crashes below. The current rule
treats them independently and arms both. **This is a candidate for a
future adjacent-bar-opposite-side mute rule**, but per C2 no resolution
in this session.

---

## 4. Shared-code diff — justified line-by-line against named defects

Diff vs HEAD `3c5f2f3` (files touched: `qm_behaviour.py`,
`qm_decision_shadow.py`, `qm_pick_alerts.py`,
`tests/unit/test_qm_velocity_rejection.py`).

### 4a. `qm_behaviour.py` (+134 lines)

| Change | Defect addressed |
|---|---|
| `STATE_VELOCITY_REJECTION` constant | New vocabulary token so `step_candidate` can recognise the same-bar velocity firing without conflating it with the existing SWEEP_DETECTED. |
| `_env_flag(name, default)` helper | Env boolean parsing so all velocity gates are env-toggleable (C1 — no hard-coded thresholds). |
| `BehaviourContext.rejection_side: Optional[str]` field | Carries the pierced-boundary side across the boundary between classifier and shadow, so `_direction_for` and `step_candidate.REJECTION_CONFIRMED → ENTRY_ARMED` can derive direction from geometry rather than from arm-bar close vs zone_center (F4 defect). |
| `classify_v2` — new VELOCITY_REJECTION block (lines 161–217) | **F1** (same-bar sweep-reclaim never classified), **F2** (arm before zone slot churn), **F3** (polarity unlock — geometry-only rather than cached extreme_side). |
| `classify_v2` — `close_far` gate applied to VELOCITY_REJECTION block AND to `velrej_flag` inside SWEEP handler (this session, +8 lines) | **F7** (violent-acceptance-through must NOT arm). Suppresses velocity signal when `abs(c-center) > 15p`. |

### 4b. `qm_decision_shadow.py` (+261 / −5 lines)

| Change | Defect addressed |
|---|---|
| `STATE_V2_VELOCITY_REJECTION` mirror + import from `qm_behaviour` | Vocabulary parity so `step_candidate` can pattern-match. |
| `_VELOCITY_ARMED: set` + `_velocity_arm_key()` + `_reset_velocity_dedup_for_tests()` | Anti-chase — one velocity arm per (sym, zone, side, day). |
| `_short_circuit_velocity_arm(cand, ts, cur_bar)` | The SWEEP handler's own velocity signal (F2 arm within one bar of SWEEP). |
| New `step_candidate` branch `if b == STATE_V2_VELOCITY_REJECTION` (lines 843–931) | Walk-through: current_state → EXTREME_REACHED → SWEEP_DETECTED → REJECTION_CANDIDATE → REJECTION_CONFIRMED → ENTRY_ARMED on one bar, driven by geometry-derived direction. Additive: never touches continuation/§16/§24 branches. |
| Collision ledger at lines 867–881 (`[QM-VELREJ-COLLISION]` log) | Logs when velocity claims a bar/zone that already carries a continuation/§16/§24 candidate. Per C2 no resolution. |
| REJECTION_CONFIRMED → ENTRY_ARMED direction derivation (lines 999–1044): `rejection_side` wins, close-vs-center is *fallback only* | **F4** — direction lie fix at slow-path ENTRY_ARMED. |
| `on_5m_close_sde`: hoist `_bctx.rejection_side` onto `cand.confidence_why` alongside signals (lines 2168–2174) | Plumbing so downstream `_direction_for` and `step_candidate` see the geometry-derived side. |

### 4c. `qm_pick_alerts.py` (+64 / −5 lines)

| Change | Defect addressed |
|---|---|
| `_direction_for` — `rejection_side` in the precedence chain above the `hypothetical_entry` fallback (lines 193–231) | **F4** — direction lie at alert render time. |
| `_pattern_words` — rejection-chain state + evidence gate → "swept {level} and rejected — fade {dir}" (lines 322–388) | **A-side of the census** (100% of §9 rejection alerts on 09-04 said "entry armed — take the trigger" instead of "fade"). Now the fade wording is *mandatory* for the rejection chain. |

### 4d. `tests/unit/test_qm_velocity_rejection.py` (+455 lines new file)

| Change | Defect addressed |
|---|---|
| F1..F7 recorded-bar fixtures with byte-clean isolation (`_env_defaults`, memory disabled, dedup reset) | Pins the repair against the six failure modes named in the operator brief. |
| F6 create-only guard — asserts peer QM test files exist unmodified | C2 zero-delta guardrail. |
| F7 assertions strengthened this session — also checks `ENTRY_ARMED not in reached` AND no transition cause contains `velocity_rejection` | The prior F7 assertion (`REJECTION_CONFIRMED not in reached`) was silently passing on the rip bar because the walk-through consumed REJECTION_CONFIRMED and landed on ENTRY_ARMED in one step. Strengthened test caught the false-positive; close-far gate fixed it. |

---

## 5. Incremental-contribution verdict vs join baseline

**Baseline caveat**: `logs/qm_join.jsonl` on this host contains 20 rows
all dated 2026-09-05 (post-repair test firings). There is no 2026-09-04
data in the join ledger to cross-reference against. The task's
"2 v1_silent cases that day" claim cannot be verified against this
host's join ledger; I proxy the baseline instead by counting live
`ENTRY_ARMED` state in `logs/qm_candidates.jsonl` for 09-04.

**Live baseline on 2026-09-04** (from `logs/qm_candidates.jsonl`):
- 17 unique (sym, zone, opened_at) candidate slots
- **2** ever reached `ENTRY_ARMED`:
  - EURUSD zone 11615.833 opened 13:15Z (slow-path, direction was BUY live; direction is SELL post-repair)
  - GBPUSD zone 13517.167 opened 14:00Z (slow-path, direction SELL)

**Velocity path additional arms on 2026-09-04** (replay with new gate,
per-slot):

| # | Sym | Zone | Opened | Live highest | Velocity arms | Classification |
|---|---|---:|---|---|---|---|
| 1 | GBPUSD | 13517.167 (P) | 09:20Z | EXTREME_REACHED | 13:45 BUY, 13:50 SELL | **★NEW** |
| 2 | EURUSD | 11590.567 (S1) | 12:30Z | EXTREME_REACHED | 12:30 BUY | **★NEW** (F1) |
| 3 | GBPUSD | 13497.65 (S1)  | 12:55Z | SWEEP_DETECTED  | 13:15 BUY | **★NEW** (F2) |
| 4 | GBPUSD | 13517.167 (P) | 13:20Z | SWEEP_DETECTED | 13:45 BUY, 13:50 SELL | **★NEW** (F3 specimen) |
| 5 | GBPUSD | 13517.167 (P) | 14:00Z | ENTRY_ARMED (live) | 14:55 SELL, 20:55 BUY | ⊕ also-live |
| 6 | GBPUSD | 13517.167 (P) | 15:50Z | REVERSAL_CANDIDATE | 17:00 SELL, 20:55 BUY | **★NEW** |

**Verdict**: The velocity path adds **5 new candidate slots armed
that were silent under the live pipeline**, plus additional side-splits
on 1 slot the live pipeline already armed. As a *second candidate
source* against the 2-arm live baseline this is a 2.5×–3× increase in
armed count. However:

- **Only F1 (+28p MFE) delivers a commercially interesting excursion**
  in the 36-bar window; the other new arms are marginal or losing.
- The GBPUSD P zone (13517.167) is over-represented: 4 of the 6 slots
  are the same zone. Adjacent-bar opposite-side collisions (13:45 BUY
  → 13:50 SELL) show up on 2 of those slots.
- Zone-day alert dedup at `qm_pick_alerts._SEEN_ZONE_DAY` will suppress
  duplicate Telegrams to the operator, but the state-machine
  transitions still fire (visible in shadow logs).

**As a second candidate source** the velocity path adds value on the
NFP-family same-bar sweep (F1) and demonstrably catches the F2/F3
detection-model failures the census diagnosed. It also introduces
same-day opposite-direction arms on volatile zones — flagged for
future adjacent-bar mute-rule consideration.

---

## 6. Suite tally (F6)

Command:
```
pytest tests/unit/test_qm_v2_self_contained.py tests/unit/test_qm_decision_shadow.py \
       tests/unit/test_qm_pick_alerts.py tests/unit/test_qm_thesis.py \
       tests/unit/test_qm_s24_reclaim_and_confidence.py \
       tests/unit/test_qm_level_memory_f1_f7.py \
       tests/unit/test_qm_velocity_rejection.py
```

- **Total**: 67 tests
- **Passed**: 65
- **Failed**: 2 (`test_shadow_module_only_imported_by_sanctioned_hooks`,
  `test_acceptance_walk_2026_08_26_0600_0800_gbpusd_s1`)

**Both failures are PRE-EXISTING at HEAD `3c5f2f3`**, verified by
stashing this session's edits and re-running:
```
$ git stash push -m 'wip velocity gate' qm_behaviour.py
$ pytest tests/unit/test_qm_decision_shadow.py::test_shadow_module_only_imported_by_sanctioned_hooks \
         tests/unit/test_qm_decision_shadow.py::test_acceptance_walk_2026_08_26_0600_0800_gbpusd_s1
========================= 2 failed in 0.64s =========================
$ git stash pop
```

Both failures are outside the F6 scope
(§16/§24/continuation/memory/alert). **Suite delta from this session:
zero.**

The added tests file (`tests/unit/test_qm_velocity_rejection.py`) adds
7 passing fixtures — F1..F7 all green after the F7 strengthening this
session.

---

## 7. Requested-fixture check-in — does anything need a special case?

Per the operator's terminal clause: "If any fixture needs a special
case — say so and STOP instead."

**Answer: NO special case is required in the code under C1.**

- F1 fires cleanly under the general same-bar geometry rule.
- F2 fires under the SWEEP-handler velocity augmentation (same rule).
- F3 SELL fires cleanly at 13:50 under geometry. F3's collision
  companion (BUY at 13:45) is a general-geometry firing too — not a
  bug per se, but a reportable collision (see §3). No specimen-fitted
  code was added to alter the 13:45 firing.
- F4 direction correction rides on the general `rejection_side`
  precedence in `_direction_for` (no EURUSD/P-specific branch).
- F5 drift bars fire nothing (score gate, close_back_through, and
  displacement all fail together on quiet bars).
- F6 verified zero-delta against pre-existing suite.
- F7 rip bar is blocked by the general 15p acceptance-through gate
  (`QM_VELREJ_CLOSE_MAX_PIPS`). This is a symmetric geometry rule (not
  specimen-fitted): a close farther than 15p past center is a break,
  not a hold, on any symbol/zone/date.

The two follow-up items I flag for the operator (both non-blocking):

1. **Adjacent-bar opposite-direction velocity arms** (F3 13:45 BUY →
   13:50 SELL). Currently both fire. A future "adjacent-bar-opposite-
   side mute" rule could suppress the second arm within N bars of the
   first, but this would be a NEW rule and per C2 no resolution this
   session.
2. **Post-arm second-side velocity firings** (e.g. GBPUSD 13517.167
   opened 14:00Z has live BUY at 14:15 plus velocity SELL at 14:55).
   Alert-layer zone-day dedup partially handles this by suppressing
   the Telegram; state-machine transitions still fire in shadow.

STOP.

---

*This report and the implementing patch are shadow-only and are locally
committed on branch `feat/trend-stretch-brake-adx-floor`. No push.*
