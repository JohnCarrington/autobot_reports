# V2 QM-PICK: detection vs communication — 2026-09-05

Investigation only. No fixes. Read-only pass over `qm_pick_alerts.py`,
`qm_decision_shadow.py`, `qm_behaviour.py`, `qm_thesis.py`,
`logs/qm_candidates.jsonl` (311 rows / 17 distinct actionable zones),
`logs/qm_pick_alerts_seen.jsonl` (12 rows), and 5m candles for 2026-09-04.

## 1. The specimen — Friday 2026-09-04 EURUSD @ P 11615.83

### 1a. Alert-template selection for this candidate

`qm_pick_alerts._pattern_words()` (lines 298–331) is the branch selector. It
looks at transition causes first, then falls back to state:

```python
def _pattern_words(cand: Any, direction: str) -> str:
    causes = " ".join(
        str(t.get("cause") or "")
        for t in (getattr(cand, "transitions", None) or [])
    ).lower()
    if "s24_rearm" in causes or "s24_reclaim" in causes:
        if direction == "BUY":
            return "failed breakdown, reclaimed — buy the reversal"
        return "failed breakout, rejected — sell the reversal"
    if "s16_retest" in causes or (isinstance(why, dict) and why.get("s16_retest")):
        if direction == "BUY":
            return "topside retest of broken level — continuation buy"
        return "underside retest of broken level — continuation sell"
    state = str(getattr(cand, "state", "") or "").upper()
    if state == "REJECTION_CONFIRMED":
        return "swept and rejected — fade"
    if state == "ENTRY_ARMED":
        return "entry armed — take the trigger"
    return state.lower().replace("_", " ") or "setup"
```

For the EURUSD specimen the transition causes were, verbatim:

```
2026-09-04T13:20Z  APPROACHING_ZONE    behaviour=APPROACHING
2026-09-04T13:35Z  EXTREME_REACHED     behaviour=EXTREME_REACHED
2026-09-04T13:45Z  SWEEP_DETECTED      behaviour=SWEEP_DETECTED
2026-09-04T14:00Z  REJECTION_CANDIDATE behaviour=REJECTING
2026-09-04T14:10Z  REJECTION_CONFIRMED rejection_score=10(very_strong)
2026-09-04T14:15Z  ENTRY_ARMED         direction=BUY
```

No cause contains `s24_rearm` / `s24_reclaim` / `s16_retest`, so those two
branches did not fire. State at alert time was `ENTRY_ARMED`, so the branch
that ran was **line 327–328**:

```python
if state == "ENTRY_ARMED":
    return "entry armed — take the trigger"
```

The direction label "BUY" comes from `_direction_for()` (lines 193–207):

```python
def _direction_for(cand: Any) -> Optional[str]:
    rd = getattr(cand, "rearm_direction", None)
    if rd in ("BUY", "SELL"):
        return rd
    try:
        e = getattr(cand, "hypothetical_entry", None)
        c = float(getattr(cand, "zone_center", 0.0) or 0.0)
        if e is not None:
            return "BUY" if float(e) > c else "SELL"
    except Exception:
        pass
    return None
```

`hypothetical_entry = 11615.9`, `zone_center = 11615.83` → 0.07 p above the
zone → **BUY**.

The stamped hypothetical_entry is set in `qm_decision_shadow.py` at line 779
inside the `REJECTION_CONFIRMED → ENTRY_ARMED` transition:

```python
direction = "BUY" if cur_bar["close"] > cand.zone_center else "SELL"
```

i.e. the direction is a **function of the arm-bar close**, not of the
rejection geometry the state machine actually observed.

### 1b. Answers to the specific questions

**Which branch selected the continuation wording?**
None. No `s16_retest` cause was in the transition list, so the
"continuation buy/sell" branch (line 320–323) was *not* taken. The
alert body did not literally say the word "continuation." What the user
saw on the phone alert reads:

```
🎯 V2 PICK — EURUSD BUY
Pivot P 11615.83 — entry armed — take the trigger
Confidence 10 (very_strong)
Thesis: …
Would enter ~11615.90 · SL 20p · first target +10
— SHADOW: V2 would take this. No order placed. —
```

The "continuation-BUY" reading is a *semantic effect*, not the literal
copy — direction=BUY at Pivot P with a neutral pattern phrase ("take
the trigger") reads as buying-the-level, i.e. continuation. The fade
wording never appears.

**What field/state was that branch keying on?**
`state == "ENTRY_ARMED"`. That is the only field the winning branch
looks at. It does not consult `rejection_score`, `rejection_signals`,
`rejection_band`, `s24_reclaim`, or the earlier `REJECTION_CONFIRMED`
transition — even though all four are present on this candidate.

**Was V2's actual internal interpretation "fade/rejection at P" while
the external message described "continuation"?**
Yes internally: `rejection_score=10`, `band=very_strong`,
`rejection_signals = {level_swept, close_back_through, m5_structure_shift,
close_inside_bb} = all True`. The state chain reached
`REJECTION_CONFIRMED` via the §9 rejection path.
Externally: the message was neutral — "entry armed — take the trigger"
with header direction BUY. It never uses the word "fade" or "rejection."
So the internal label and the external phrasing are inconsistent — not
a literal mislabel but a communication gap that reads as continuation.

**REJECTION_CONFIRMED timestamp/price:**
`2026-09-04T14:10:00+00:00`, on the 14:10 5m bar. Bar OHLC
= 11614.40 / 11614.40 / 11610.30 / **11613.20** (close 2.63 p BELOW P).
Rejection score stamped 10 (`very_strong`).

**ENTRY_ARMED timestamp/price:**
`2026-09-04T14:15:00+00:00`, on the 14:15 5m bar. Bar OHLC
= 11613.30 / 11616.00 / 11611.60 / **11615.90** (close 0.07 p ABOVE P).
`hypothetical_entry = 11615.90`, `hypothetical_stop = 11606.60`,
`hypothetical_target = 11630.90`.

**Pips of the reversal already banked at ENTRY_ARMED:**
Two readings for the same specimen because the direction label flipped
between rejection observation and arm bar.

- If we honour the arm direction (BUY): trough after sweep = 13:55 low
  11608.80, arm close 11615.90 → **7.1 p already spent** on the bounce
  before the trader is told to buy.
- If we honour the internal rejection direction (topside sweep → SELL
  fade): 13:45 sweep high 11622.90, REJECTION_CONFIRMED close 11613.20
  → **9.7 p of the down-move already spent**. Then arm bar 14:15 close
  11615.90 gave back 2.7 p of that.

**MFE remaining after ENTRY_ARMED (14:15Z, close 11615.90):**
- Max post-entry high: 11624.50 at 16:20Z → **+8.6 p** favorable for BUY.
- Max post-entry low: 11608.90 at 18:45Z → **-7.0 p** adverse (MAE).
- Stated first-target +10 (11625.9): never reached.
- Hypothetical target 11630.9 (+15): never reached.
- **+35 p was NOT available after ENTRY_ARMED in either direction.**

### 1c. A latent architectural finding surfaced by this specimen

`_direction_for()` returns `None` at `REJECTION_CONFIRMED` for a
pure-rejection candidate (no `rearm_direction`, and
`hypothetical_entry` is only set at the `ENTRY_ARMED` transition —
`qm_decision_shadow.py:787`). That means `maybe_send_pick_alert()`
skips the alert on the `REJECTION_CONFIRMED` transition and only fires
on the *next* transition (`ENTRY_ARMED`). By that point the pattern
selector has already fallen through to the neutral "entry armed" line.

Consequence: **the "swept and rejected — fade" pattern (line 326) is
architecturally unreachable for the rejection chain in the live
pipeline.** No alert on this branch has ever, and can ever, use the
word "fade" as the code currently stands.

## 2. The census — all-time actionable candidates

Deduped by `(symbol, opened_at, zone_center)`, keeping the longest
transition trail per zone. All-time (log start 2026-08-26 → today).

| # | ts (opened) | sym | zone | chain | highest state | ENTRY_ARMED | conf | alert wording | price at ENTRY_ARMED | pips banked before arm | remaining MFE (BUY dir) | ≥35 p left? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-01T20:55Z | GBP | 13515.87 | s24_reclaim | REVERSAL_CANDIDATE | no | 0 | never (below floor) | — | — | — | — |
| 2 | 2026-09-02T06:25Z | EUR | 11573.87 | s24_reclaim | REVERSAL_CANDIDATE | no | 0 | never (below floor) | — | — | — | — |
| 3 | 2026-09-02T09:09Z | GBP | 13495.00 | swing_formed | REVERSAL_CANDIDATE | no | 10 | never (dir=None) | — | — | — | — |
| 4 | 2026-09-02T13:30Z | EUR | 11583.40 | s16_retest | REVERSAL_CANDIDATE | no | 12 | "…continuation buy" | — | — | — | — |
| 5 | 2026-09-02T13:40Z | GBP | 13492.57 | s16_retest | REVERSAL_CANDIDATE | no | 10 | "…continuation buy" | — | — | — | — |
| 6 | 2026-09-02T14:00Z | GBP | 13502.60 | s16_retest | REVERSAL_CANDIDATE | no | 11 | "…continuation buy" | — | — | — | — |
| 7 | 2026-09-03T08:50Z | GBP | 13492.40 | s16_retest | REVERSAL_CANDIDATE | no | 12 | "…continuation buy" | — | — | — | — |
| 8 | 2026-09-03T11:15Z | EUR | 11607.47 | s16_retest | REVERSAL_CANDIDATE | no | 10 | "…continuation buy" | — | — | — | — |
| 9 | 2026-09-03T12:30Z | EUR | 11609.20 | s16_retest | REVERSAL_CANDIDATE | no | 10 | "…continuation buy" | — | — | — | — |
|10 | 2026-09-03T13:55Z | GBP | 13510.50 | s16_retest | REVERSAL_CANDIDATE | no | 12 | "…continuation buy" | — | — | — | — |
|11 | 2026-09-03T14:45Z | GBP | 13510.50 | s16_retest | REVERSAL_CANDIDATE | no | 12 | "…continuation sell" | — | — | — | — |
|12 | 2026-09-03T15:00Z | GBP | 13516.70 | s16_retest | REVERSAL_CANDIDATE | no | 10 | "…continuation buy" | — | — | — | — |
|13 | 2026-09-03T19:20Z | GBP | 13534.80 | s16_retest | REVERSAL_CANDIDATE | no | 10 | "…continuation sell" | — | — | — | — |
|14 | 2026-09-04T13:15Z | **EUR** | **11615.83** | **rejection** | **ENTRY_ARMED** | **yes** | **10** | "entry armed — take the trigger" | 11615.90 | 7.1 p bounce (BUY) / 9.7 p fall (SELL) | +8.6 p (max high 11624.50) / MAE -7.0 p | **no** |
|15 | 2026-09-04T14:00Z | **GBP** | **13517.17** | **rejection** | **ENTRY_ARMED** | **yes** | **10** | "entry armed — take the trigger" | 13519.85 | 9.9 p bounce (BUY) / 3.4 p fall (SELL) | +5.0 p (max high 13524.85) / SL hit at 13514.35 by 18:45Z | **no** |
|16 | 2026-09-04T15:50Z | EUR | 11615.83 | s16_retest | REVERSAL_CANDIDATE | no | 12 | never (zone-day dedup) | — | — | — | — |
|17 | 2026-09-04T15:50Z | GBP | 13517.17 | s16_retest | REVERSAL_CANDIDATE | no | 12 | never (zone-day dedup) | — | — | — | — |

Notes:
- Rows 16/17: same zones as rows 14/15 same day; `maybe_send_pick_alert`
  blocked them via the `(round(zc,1), direction, date)` dedup set. Had
  they fired they would have used the `s16_retest` "continuation buy"
  wording — a *different* label from the earlier rejection alert on the
  same zone.
- Row 3 (`swing_formed_SWING_L`) has `confidence_score=10` (≥ floor 7)
  but no direction: `rearm_direction=None` and `hypothetical_entry=None`
  → `_direction_for()` returned `None` → alert silently skipped.
- Alerts row 14/15 fired at 14:20Z and 15:35Z respectively (one bar
  after the `ENTRY_ARMED` transition — the wall-clock arrival of the
  next bar).

### Chain totals

| Chain | Ever reached actionable | Reached ENTRY_ARMED | Alerted | Alert wording (if fired) |
|---|---:|---:|---:|---|
| §9 rejection | 2 | 2 | 2 | "entry armed — take the trigger" |
| §16 retest | 12 | 0 | 10 (2 dedup-blocked) | "…continuation buy/sell" |
| §24 reclaim | 2 | 0 | 0 (below floor) | (would have been "failed break… — reversal") |
| swing formation | 1 | 0 | 0 (no direction) | (would have been "reversal candidate") |
| **TOTAL** | **17** | **2** | **12** | |

### What the alert bodies actually said, all-time

- **10 alerts** literally contained the word "continuation." All 10 were
  `s16_retest` chain, which is a *legitimate* continuation setup (retest
  of broken level → continue in the break direction). Those are
  correctly voiced by intent, though whether the underlying s16 detector
  is over-firing on things that are actually rejections is a separate
  question this report did not audit.
- **2 alerts** were the §9 rejection chain (rows 14/15). Both used the
  neutral "entry armed — take the trigger" and never contained "fade"
  or "rejection."
- **0 alerts** ever contained the literal words "fade" or "rejection"
  since the log began. The `state == "REJECTION_CONFIRMED"` branch that
  would produce "swept and rejected — fade" is architecturally
  unreachable (see §1c).

## 3. The violent class

### 3a. 2026-09-04 13:45Z GBPUSD — P-underside sweep, conf 10, never confirmed

Actual candidate (opened 13:20Z, zone P 13517.17):

```
2026-09-04T13:25Z  APPROACHING_ZONE  behaviour=APPROACHING
2026-09-04T13:40Z  EXTREME_REACHED   behaviour=EXTREME_REACHED
2026-09-04T13:45Z  SWEEP_DETECTED    behaviour=SWEEP_DETECTED
(no further transitions — stuck)
```

Bars around the sweep:

```
13:40Z  O=13508.35 H=13513.25 L=13508.25 C=13511.85   below zone
13:45Z  O=13512.15 H=13524.05 L=13511.95 C=13522.35   +5.2 above zone  ← SWEEP fires
13:50Z  O=13522.45 H=13523.15 L=13510.45 C=13511.55   -5.6 below zone  ← 11-pip down bar
13:55Z  O=13511.75 H=13511.85 L=13503.35 C=13505.55   -11.6 below zone
14:00Z  O=13505.45 H=13509.85 L=13505.15 C=13508.95   -8.2 below zone
```

**Which exact transition failed?** `SWEEP_DETECTED → REJECTION_CANDIDATE`.

**Why?** `qm_behaviour.classify_v2()` (line 181–195) requires the
subsequent bar to close on the "opp_side" of the classifier's stored
`extreme_side`. On this candidate, `extreme_side` had been latched to
`"below"` by the earlier down-wick (13:35–13:40Z), so the SWEEP was
interpreted as "swept the below extreme, expect UP rejection continuation"
and `opp_side = "above"`. Then the 13:50Z bar closed 5.6 p **BELOW**
center (11-pip down body) — the opposite polarity of what the
classifier is set up to see as REJECTING. So `rejecting_streak` never
advanced. Bars 13:55, 14:00, 14:05 all closed below center and were
therefore invisible to the REJECTING rule too.

`_maybe_expire_candidate` only counts bars while state is
`REVERSAL_CANDIDATE` or `REJECTION_CONFIRMED`; `SWEEP_DETECTED` is not
in that set, so the candidate did not expire either — it just sat.

**Could any existing rule have armed the trade as currently written?**
No. Every state-transition path from `SWEEP_DETECTED` requires
`behaviour ∈ {REJECTING, V2_REJECTION_CONFIRMED}` (rejection chain) or
`behaviour ∈ {ACCEPTING, V2_LEVEL_ACCEPTED}` (level-accepted chain).
The classifier emitted neither because both are polarity-locked and
the actual price rejection was in the direction opposite to the
classifier's cached expectation.

**Root cause:** *polarity lock-in.* The SWEEP path in
`classify_v2` (lines 137–178) short-returns before the extreme-side
update (lines 198–221), so `extreme_side` cannot flip within the same
candidate life. The REJECTING check then references the stale
`extreme_side` and rejects real rejection bars as non-matching.

Not a velocity problem — 5 min was plenty of time. It is a **detection
model** problem: the classifier cannot model a "topside sweep after an
earlier downside probe" as a topside sweep.

**Pips available after the earliest realistic detection:** the 13:50Z
close at 13511.55 is the first bar an unbiased reader could call
"rejection of the 13:45 sweep." From 13511.55 down to the day-session
low (18:45Z low 13510.35) = ~1 p; but the actual usable move was
13:50Z close → 13:55Z low 13503.35 = **8 p**. Modest, not violent.

### 3b. 2026-09-04 13:30Z NFP snap — EURUSD S1 zone 11590.57

The NFP release printed into the 12:30Z bar:
```
12:30Z  O=11625.85 H=11625.85 L=11585.55 C=11594.95   40-p wick down through S1
12:35Z  O=11595.15 H=11602.00 L=11591.90 C=11596.40   +6 above S1
```

Candidate opened 12:30Z, zone 11590.57. Reached `EXTREME_REACHED` at
12:50Z and never advanced.

**Which exact transition failed?** `EXTREME_REACHED → SWEEP_DETECTED`.

**Why?** The SWEEP check in `classify_v2` (line 142) requires
`ctx.extreme_side is not None`. On the *first* bar the classifier sees
after candidate open, `extreme_side` is unset. So bar 12:30 (the wick
itself) can only fire `EXTREME_REACHED`, not `SWEEP_DETECTED`. For
`SWEEP_DETECTED` to fire on 12:35, `reach_body = max(|c-o|, |c-prev_c|)`
must be ≥ `LARGE_BODY = 4 p`; `|11596.40 - 11594.95| = 1.45 p`,
`|11596.40 - 11595.15| = 1.25 p`. Too small. Subsequent bars had bodies
< 4 p too. `bars_since_extreme` exceeded 2 → SWEEP window expired.

**Could any rule have armed the trade?** No. The 30 p bounce from
11585 → 11615 was distributed across bars 12:30–13:25 with per-bar
bodies of 1–7 p and no single 4-p body from *previous close*
qualifying for SWEEP.

**Root cause:** *single-bar sweep invisibility + tight body threshold.*
The classifier cannot fire SWEEP on the same bar that establishes the
extreme (no prior extreme_side) and cannot fire it later either
because subsequent 5m bars didn't have decisive per-bar bodies. This
is not a velocity/timing lag — the model geometry excludes the case
entirely.

**Pips available after earliest realistic detection:** if a rule
existed that let a 12:30 bar with an inside-wick reversal fire SWEEP
immediately (i.e. `close > center` after the wick pierced the far side
of the zone), the earliest tradable entry would be 12:35Z open 11595.
The subsequent high (13:45Z 11622.90) gives **+27.9 p** available on
that scenario — genuinely material.

### 3c. GBPUSD S1 sweep at 13:15Z (zone 13497.65) — bonus violent case

Same day, same shape. Candidate opened 12:55Z, reached SWEEP_DETECTED
at 13:15Z with conf=10, never confirmed. High post-sweep 13:45Z
= 13524.05 (26.4 p above zone). Zero further transitions. Same
detection model failure as 3a — polarity locked to `extreme_side`
established during NFP low, subsequent bars ran the other way.

## 4. Verdict

**A + B — both exist, and B is the larger share.**

### A — communication is broken for the cases detection catches

- **2 of 2** §9 rejection candidates that ever reached
  `REJECTION_CONFIRMED` (100 %) alerted with "entry armed — take the
  trigger," never with "fade" or "rejection." The `state ==
  REJECTION_CONFIRMED` branch that produces "swept and rejected — fade"
  is architecturally unreachable (§1c).
- The `_direction_for` fallback on `hypothetical_entry` (which is only
  set at ENTRY_ARMED using the arm-bar close relative to zone_center)
  can flip the header label away from the direction the rejection
  chain actually implied. The EURUSD specimen sat 0.07 p above the
  pivot on the arm bar and got labelled BUY, though the internal
  chain was recording a rejection of a topside sweep.

### B — detection materially under-produces on violent geometry

- Only **17 zones ever reached any actionable state**; **2** ever
  reached `ENTRY_ARMED`; **0** rejection-chain trades ever spawned on a
  same-bar or 1-bar reversal (the violent class).
- Two visible violent fades on 2026-09-04 (EURUSD 12:30Z NFP S1, GBPUSD
  13:45Z P and GBPUSD 13:15Z S1) failed to progress past
  `EXTREME_REACHED` or `SWEEP_DETECTED`.
- The failure modes are **model-shape** problems in `classify_v2`, not
  latency:
  1. SWEEP cannot fire on the same bar that sets the extreme (line 142
     requires a prior extreme_side).
  2. `LARGE_BODY = 4 p` from `prev_close` blocks quiet-then-violent
     patterns where the reversal is on a single bar that hasn't yet
     produced a follow-up large body.
  3. `extreme_side` never flips inside a live candidate because the
     SWEEP path short-returns before the extreme update, so REJECTING
     is polarity-locked to whichever direction was probed first.

### Quantitative split

- **% of detected fades mis-voiced:** 2/2 = **100 %** of §9 rejection
  chain alerts used a neutral phrase ("entry armed — take the trigger")
  and no explicit fade language. If we widen "mis-voiced" to include
  header direction disagreeing with rejection direction, the EURUSD
  specimen (BUY header vs topside-sweep rejection) is 1 of 2.
- **% of objectively relevant violent fades that never reached
  REJECTION_CONFIRMED:** on 2026-09-04 there were at least 3 candidate
  slots on visible violent moves (EURUSD 12:30 S1, GBPUSD 13:15 S1,
  GBPUSD 13:45 P). **3 of 3 = 100 %** never reached
  `REJECTION_CONFIRMED`. The 2 candidates that *did* reach ENTRY_ARMED
  (EURUSD 13:15 opened, GBPUSD 14:00 opened) were slow multi-bar
  rejections, not the violent class.
- **% of ENTRY_ARMED fades where ≥35 p remained available after
  arming:** 0 of 2 = **0 %**. Best MFE remaining was +8.6 p (EURUSD)
  and +5.0 p (GBPUSD). Both would have hit their 20-p stop before
  target on the arm direction; the SELL-fade counterfactual on the
  EURUSD specimen would have made +7 p before the level reasserted.

### Where the remaining gap sits

Roughly: **A costs at most a copywriting fix**, but even after that fix
the underlying trade quality on the two arms is poor (target unreached,
MFE < +10 p). The bulk of the missing profit lives in **B** — the
violent-class geometry the classifier does not model. Fixing wording
without fixing detection would still leave the +27 p NFP fade and the
+8 p GBPUSD-P fade unpicked.

---

*Investigation only. No V2 prediction logic, thresholds, state
transitions, Telegram mappings, filters, or velocity handling were
altered. Diagnosis complete; STOP.*
