# Ratchet Tier Advancement vs Structural Progression — Sequencing Investigation (2026-09-23)

**Branch:** `feat/trend-stretch-brake-adx-floor` (commit `fc2b009`).
**Author:** autobot · **Class:** INVESTIGATION ONLY. **No .env change. No restart. No authority changes. No code modification to production modules.**
**Trigger:** Path B structural composer accepted as not for activation. Operator ruling: investigate the more fundamental sequencing problem — the tiered ratchet may tighten the stop before structural/QM evidence has completed the directional leg, after which monotonicity correctly prevents restoration of sufficient room.

Structural position composer, QM exhaustion veto, and stop monotonicity all remain OFF / unchanged.

---

## 0. Rulings honoured

- No implementation. No `.env`. No restart. No authority changes.
- No production module modified in this investigation.
- Counterfactuals in §3 use **retention of the previously-lawful stop from the moment of a given tier advancement** — no later stop is loosened. When the ratchet advanced tier 0→1 at 12:35 setting stop 13281.85, the counterfactual retains the 13296.85 BE stop that was in force **at 12:34** and walks forward from 12:35 asking whether BE would have breached. This is not stop-loosening; it is a check on whether the specific tier advancement was necessary.
- Retrospective classification (§4) uses future outcomes ONLY for the retrospective diagnosis; §5 clearly separates causal features that were available at decision time from the retrospective outcome.

---

## 1. What was built for this investigation

| File | Role |
|---|---|
| `scripts/composer_replay/tier_advancement_sequencing.py` | Population sweep across all 93 recognition-lens ≥30p MID_NEWS legs + 2026-09-23 counterfactual. Records every tier advancement with QM state, level relationships, retained-previous-stop counterfactual, and retrospective classification. |
| `scripts/composer_replay/tier_advancement_one_shot.py` | Same runner, single-event mode for the 08:20 SHORT admit-lens replay and the 2026-04-14 LONG replay (neither is in the recognition-lens population). |
| `/tmp/tier_advancement_sequencing.json` | Full population run output. |
| `/tmp/tier_0820_short.json` | 08:20 SHORT admit-lens run output. |

No production module was modified. `tiered_ratchet.py`, `level_interaction_observer_v6.py`, `qm_level_interactions.py`, `trade_manager.py`, `structural_position_composer.py` (from the prior increment), and all other production files are unchanged.

QM states per bar are reconstructed via the real `qm_level_interactions.Interaction` state machine over the archive candles — identical technique and code path used in `scripts/phase16_veto_eval/qm_exhaustion_veto_regression.py` and `scripts/composer_replay/composer_historical_overlap.py`. No re-implementation.

---

## 2. 2026-09-23 08:20 GBPUSD TREND_V3 SHORT — bar-by-bar

Entry: `2026-09-23T08:20:00+00:00` @ 13296.85. Level universe (from pivots + round numbers, this-day fallback): P=13351.05, R1=13380.55, R2=13417.35, R3=13446.85, S1=13314.25, **S2=13284.75**, **S3=13247.95**, PDH=13387.85, PDL=13321.55, NEAREST_00=13300, NEAREST_50=13250.

### 2.1 Landmark bar table

```
bar    close     MFE  tier  stop      Δ_stop   reason              QM state @ this bar          cont  rej
────────────────────────────────────────────────────────────────────────────────────────────────────────
08:20  13302.75   0.1  -1   13308.85    -      init SL (12p above)  no interactions               —     —
09:35  13286.75  10.9   0   13296.85  −12p    tier 0 → BE lock     S1 ACCEPT, PDL BREAK_AWAY,   Y     N
                                                                    NEAREST_00 ACCEPT (all
                                                                    above entry — inherited
                                                                    market context, not this
                                                                    trade's earned protection)
11:05  13291.75  19.2   0   13296.85    -      no tier change       S2 ACCEPT+cont (below entry, Y     N
                                                                    THIS position's first
                                                                    cleared-behind level)
12:35  13264.45  33.4   1   13281.85  −15p    tier 1 → +15p lock   S1/S2/NEAREST_00 ACCEPT,     Y     N
                                                                    PDL BREAK_AWAY
                                                                    cleared_behind_count=1 (S2)
                                                                    continuation_positive=4
                                                                    zero REJECT, zero OSCILLATING
13:15  13268.75  33.6   1   13281.85    -      RATCHET_EXHAUSTION   (no change)                  Y     N
                                                fires (6 flat bars
                                                beyond BE)  → CLOSE
                                                @ +28.1p
13:25  13287.85  33.6   —   —           -      (post-close; had     (no change; observer would   Y     N
                                                position held, this   still emit S2 ACCEPT
                                                bar would breach     because state is FROZEN
                                                tier-1 stop 13281.85 once stamped)
                                                → RATCHET_STOP)
14:00  13262.05  46.0   —   —           -      (session continued   S2 ACCEPT+cont              Y     N
                                                downward — position
                                                would have run further)
14:25  13250.85  48.4   —   —           -      S3 interaction opens S3 interaction_open          Y     N
14:35  13255.45  48.4   —   —           -      S3 FINAL_REJECT       S3 REJECT (first REJECT     Y     Y
                                                                     of the session)
16:55  13233.85  63.0   —   —           -      session close (MID_  S2 BREAK_AWAY, S3 REJECT    Y     Y
                                                NEWS convention)     sustained
```

### 2.2 First tier advancement that becomes incompatible with subsequent structurally valid movement

**Tier 0 → Tier 1 at 12:35** — stop moves from 13296.85 (BE) to **13281.85** (entry − 15p).

This is the transition the operator specifically flagged. Two mechanisms make it incompatible with the run that structurally continued to session low 13233.85:

1. **It enables ratchet exhaustion.** The ratchet's exhaustion predicate requires `sw_stop < entry_price` strictly (SELL case, `tiered_ratchet.py:643-646`). Tier 0 (BE) has `sw_stop == entry`, exhaustion cannot fire. Tier 1 has `sw_stop < entry`, exhaustion becomes ARMED. Six consecutive no-new-extreme bars after 12:35 → exhaustion fires at 13:15.
2. **It positions the software stop 0.93p below the 13:25 pullback close.** Under retained BE stop 13296.85, the 13:25 close 13287.85 is 8.99p below the stop → NO breach. Under tier-1 stop 13281.85, the 13:25 close 13287.85 is 6.00p above the stop → BREACH.

**Either mechanism alone (exhaustion at 13:15 OR stop-breach at 13:25) would have closed the position under tier 1. Under retained tier-0 BE stop, neither activates.**

The prior tier −1 → 0 advancement at 09:35 (init SL → BE) is also retrospectively classified `PREMATURE_TIGHTEN` because retaining the 12p LOSS init SL would ALSO have run to NY_CLOSE. But that classification is a technicality: the init SL is at −12p and BE stop is at 0p, both above the eventual session low; retaining the LOSS stop just leaves a wider MAE window that never got tested here (session did not adverse-retrace past entry after the initial capture). The **operative** first-incompatible transition is tier 0 → 1 at 12:35, because that is the one which converts a passive protective posture into an active exit trigger.

### 2.3 Counterfactual — retain tier-0 BE stop from 12:35 forward

Walk the candles from 12:35 with stop held at 13296.85 (BE). For a SHORT this stop only fires if `bar_close > 13296.85`:

| Bar | close | close > 13296.85? |
|---|---|---|
| 12:35 through 13:20 | 13260-13275 range | NO |
| 13:25 | 13287.85 | NO (still below BE) |
| 13:30-14:00 | 13260-13285 | NO |
| 14:00 | 13262.05 | NO |
| 14:35 | 13255.45 | NO |
| 15:00 | 13258.35 | NO |
| 16:05 | 13249.65 | NO |
| 16:55 | 13233.85 | NO |

**BE stop never breaches.** Ratchet exhaustion never fires (tier 0 → `beyond_be=False` → exhaust check short-circuits). Position runs to NY_CLOSE at 16:55 @ **13233.85 → +63.0p realized** (production actual: +28.1p, delta **+34.9p**).

Additionally: at 14:35 S3 FINAL_REJECT fires (first bear-side REJECT of the session). If S3 REJECT is used as a discretionary exit trigger, close at 13255.45 → **+41.4p** (matches the `qm_successor_investigation_20260923.md` §5.5 composed decision outcome). Both counterfactuals materially outperform production.

**0820_PREVIOUS_STOP_WOULD_SURVIVE = YES.**

---

## 3. Historical population — 93 events, 105 ratchet tier advancements

Population: same 93 recognition-lens ≥30p GBPUSD MID_NEWS legs (Jan 5 – Aug 5 2026) + 3 counterfactual legs on 2026-09-23 as used in `composer_historical_overlap_20260923.md`.

### 3.1 Aggregate

```
RATCHET_ADVANCEMENTS_ANALYSED           = 105
GOOD_TIGHTENS                           = 33   (31.4%)
PREMATURE_TIGHTENS                      = 45   (42.9%)
IRRELEVANT_TIGHTENS                     = 27   (25.7%)
```

Classification rule (retrospective only):
- **PREMATURE_TIGHTEN**: retained-previous-stop counterfactual delivers > 2p more realized pips than production.
- **GOOD_TIGHTEN**: retained-previous-stop counterfactual delivers > 2p LESS than production (production tighten protected profit before genuine deterioration).
- **IRRELEVANT_TIGHTEN**: |Δ| ≤ 2p, outcome unchanged.

### 3.2 By tier transition

| Transition | N | GOOD | PREMATURE | IRRELEVANT | % PREMATURE |
|---|---|---|---|---|---|
| tier −1 → tier 0 (init SL → BE, trigger MFE ≥ 10p) | 70 | 22 | 27 | 21 | **38.6%** |
| tier 0 → tier 1 (BE → +15p, trigger MFE ≥ 30p) | 33 | 10 | **17** | 6 | **51.5%** |
| tier 1 → tier 2 (+15p → +40p, trigger MFE ≥ 60p) | 1 | 0 | 1 | 0 | 100% (n=1) |
| tier −1 → tier 1 (fast skip, single-bar MFE ≥ 30p) | 1 | 1 | 0 | 0 | (n=1) |

**MOST_PROBLEMATIC_TIER_TRANSITION = tier 0 → tier 1 (BE → +15p at MFE ≥ 30p).** 51.5% of tier 0 → 1 transitions are retrospectively PREMATURE. This is exactly the 08:20 SHORT case's failure mode: the ratchet locks +15p profit but simultaneously arms exhaustion, and 6 flat-MFE bars later exhaustion closes the position while the leg still has more room per the observer.

The tier −1 → 0 (BE lock) is less problematic because:
- (a) It is a passive protection move (stop cannot breach on any close ≤ entry for a SHORT); breach requires an adverse move all the way back to entry.
- (b) It does NOT arm exhaustion (`beyond_be=False`).

### 3.3 Per-transition retrospective ratio (worst-first)

The 45 PREMATURE tightens are the source of the composer replay's negative population delta reported in `structural_position_composer_20260923.md` §6.1 (−114.95p). The composer's monotonicity gate correctly refused to loosen these already-tightened stops, so composer-authority did NOT recover them — the trade was structurally lost at the tighten moment.

---

## 4. Causal-discriminator analysis (existing machinery only)

For each advancement, snapshot the CAUSAL evidence available at that bar (available at decision time — no future information):

```
[GOOD_TIGHTEN]         n=33
  cleared_behind_count               median 0     mean 0.39
  continuation_positive_count        median 1     mean 1.24
  any_reject_active_rate                            0.848
  any_oscillating_active_rate                       0.030
  any_break_away_active_rate                        0.485
  target_ahead_final_state           None:29  ACCEPT:2  BREAK_AWAY:1  REJECT:1
  mfe_at_tighten                     median 11.7p mean 18.17p

[PREMATURE_TIGHTEN]    n=45
  cleared_behind_count               median 0     mean 0.36
  continuation_positive_count        median 1     mean 1.82
  any_reject_active_rate                            0.622
  any_oscillating_active_rate                       0.000
  any_break_away_active_rate                        0.533
  target_ahead_final_state           None:38  REJECT:6  BREAK_AWAY:1
  mfe_at_tighten                     median 16.1p mean 21.60p

[IRRELEVANT_TIGHTEN]   n=27
  cleared_behind_count               median 0     mean 0.44
  continuation_positive_count        median 2     mean 1.93
  any_reject_active_rate                            0.815
  any_oscillating_active_rate                       0.000
  any_break_away_active_rate                        0.593
  target_ahead_final_state           None:18  REJECT:6  BREAK_AWAY:2  ACCEPT:1
  mfe_at_tighten                     median 11.95p mean 17.04p
```

### 4.1 Feature-by-feature discrimination test

| Feature | GOOD | PREMATURE | Gap | Discriminator? |
|---|---|---|---|---|
| cleared_behind_count (mean) | 0.39 | 0.36 | 0.03 | **NO** — identical |
| continuation_positive_count (mean) | 1.24 | 1.82 | 0.58 | Weak — PREMATURE has MORE continuation signals (counter-intuitive; likely reflects inherited pre-entry level state, not this-trade progression) |
| any_reject_active_rate | 84.8% | 62.2% | **22.6 pp** | **Marginal population-level signal.** But: heavy overlap; 62% of PREMATURE tightens still had a REJECT present. |
| any_oscillating_active_rate | 3.0% | 0.0% | 3.0 pp | Effectively silent — OSCILLATING is rare at tighten bars. |
| any_break_away_active_rate | 48.5% | 53.3% | 4.8 pp | No discrimination. |
| target_ahead FINAL_REJECT | 3.0% | 2.2% | 0.8 pp | No discrimination. |
| mfe_at_tighten (median) | 11.7p | 16.1p | +4.4p | Confounded by tier composition (tier −1→0 fires at 10p, tier 0→1 fires at 30p+; PREMATURE is over-represented in tier 0→1). Not a clean signal. |

**The only feature with meaningful population-level separation is `any_reject_active_rate` (22.6 pp gap in favour of GOOD).** But the overlap is very large (~62% of PREMATURE tightens also show an active REJECT), and this feature is silent on the operator's two specific cases (both 09-23 08:20 SHORT and 04-14 LONG show `any_reject_active=False` at their tier 0 → 1 moment).

### 4.2 Specific 09-23 vs 04-14 side-by-side at tier 0 → 1

```
                                  09-23 SHORT (12:35)       04-14 LONG (12:00)
                                  ────────────────────      ────────────────────
Direction                         SELL                      BUY
Entry price                       13296.85                  13533.85
MFE at tighten                    33.4p                     30.6p
Prev stop                         13296.85 (BE)             13533.85 (BE)
New stop                          13281.85 (+15p lock)      13548.85 (+15p lock)
QM raw states at tighten          S1 ACCEPT (above entry)   PDH ACCEPT (below entry)
                                  S2 ACCEPT (below entry)   NEAREST_50 BREAK_AWAY
                                  PDL BREAK_AWAY            (above entry)
                                  NEAREST_00 ACCEPT
cleared_behind_count               1 (S2)                    1 (NEAREST_50)
continuation_positive_count        4                         2
any_reject_active                  False                     False
any_oscillating_active             False                     False
any_break_away_active              True (PDL)                True (NEAREST_50)
target_ahead identified            None (S3 not yet          None (R1 not yet interacted)
                                    interacted)

RETROSPECTIVE ────────────────
CF prev stop → exit               NY_CLOSE @ 13233.85       NY_CLOSE @ 13561.85
CF prev stop → pips                +63.0p                    +28.0p
Production exit                    RATCHET_EXHAUSTION 13:15  RATCHET_EXHAUSTION 14:00
Production pips                    +28.1p                    +50.5p
Δ (CF − Prod)                     +34.9p                    −22.5p
Classification                     PREMATURE_TIGHTEN         GOOD_TIGHTEN
```

**Every causal feature available at the moment of the tier 0 → 1 advancement is either identical between the two cases (`cleared_behind_count=1`, `any_reject_active=False`, `any_oscillating_active=False`, `any_break_away_active=True`, target_ahead `None`) or points in the WRONG direction (`continuation_positive_count`: 09-23 has 4, 04-14 has 2 — the case with MORE continuation evidence turns out to be PREMATURE).**

`continuation_positive_count` is inflated on 09-23 because three of its four continuation-positive levels (S1, PDL, NEAREST_00) were cleared before the trade opened (above entry for a SHORT) — they represent inherited market context, not this-position structural progression. `cleared_behind_count` correctly filters these to 1 in both cases, so the true structural-progression signal is IDENTICAL.

**CAUSAL_EXISTING_DISCRIMINATOR_FOUND on the 09-23 vs 04-14 side-by-side = NO. Existing machinery does not distinguish these two.**

At population scale a marginal signal exists (`any_reject_active_rate` 22.6 pp gap), but its overlap is large and it is silent on the two operator-flagged cases.

---

## 5. Structural interpretation of the sequencing failure

The sequencing problem is architectural:

- The ratchet advances by **MFE** (favourable excursion measured in pips from entry). Its tier schedule (10p → BE, 30p → +15p, 60p → +40p, 100p → +75p) is calibrated to price-based profit-lock milestones.
- The observer stamps `FINAL_ACCEPT` on a level by **bar cadence** (2 consecutive closes beyond + N bars out of zone, per `qm_level_interactions.py`). Its progression is time-in-zone driven.

These two clocks are not synchronised. In the 09-23 SHORT case:

- 08:20 entry.
- **09:35 (T+1h15m)**: MFE reaches 10p → ratchet fires tier −1 → 0. Meanwhile S2 has not yet been touched (interaction opens at 09:35 with S2's zone entry, `FINAL_ACCEPT` stamped at 11:05).
- **12:35 (T+4h15m)**: MFE reaches 30p → ratchet fires tier 0 → 1. Structurally: S2 is captured (ACCEPT stamped 90 minutes earlier), but the next-target S3 (13247.95) is another ~17p away; the leg has more room.
- **13:15 (T+4h55m)**: 6 flat-MFE bars → ratchet fires RATCHET_EXHAUSTION. Structurally: S2 remains ACCEPT+cont, no REJECT, no OSCILLATING; the observer has never issued a "leg complete" signal.

The ratchet declared victory 4 hours before the observer's earliest "leg complete" signal (14:35 S3 REJECT). This is the sequencing gap.

On 04-14 the two clocks HAPPENED to align: ratchet exhaustion at 14:00 was preceded by observer NEAREST_50 BREAK_AWAY and no subsequent structural progression; the "flat MFE" ratchet signal correctly co-occurred with a "structural plateau" observer state. But this alignment is coincidental — the observer did not emit a "plateau" signal, it simply stopped updating any level (no adverse retest of NEAREST_50, no S1/R2 approach). The 14:00 exhaustion "correctly caught the top" because the top happened to be reached before the next structural interaction; on 09-23 the next structural interaction (S3 at 14:25) was 3h50m past ratchet exhaustion.

**The observer has no "leg complete / continuation exhausted" primitive.** Its `FINAL_ACCEPT`/`FINAL_BREAK_AWAY` states are per-level resolutions; they do NOT compose into a session-level "further progression exhausted" signal. Adding one is new machinery (a bar-density or ATR-normalised progression detector), which is out of scope.

---

## 6. What NOT to do (per operator ruling)

- Do NOT activate the structural composer (accepted as not-for-activation).
- Do NOT activate the QM exhaustion veto (already established as net-negative on this population).
- Do NOT change stop monotonicity (that would break the SL amend primitive's invariant).
- Do NOT invent a new classifier to make the GOOD-vs-PREMATURE distinction.

The findings above use existing machinery only.

---

## 7. Required metric block

```
RATCHET_ADVANCEMENTS_ANALYSED           = 105 (across 93 recognition-lens ≥30p GBPUSD MID_NEWS legs + 2026-09-23 counterfactual)
GOOD_TIGHTENS                           = 33   (31.4%)
PREMATURE_TIGHTENS                      = 45   (42.9%)
IRRELEVANT_TIGHTENS                     = 27   (25.7%)
MOST_PROBLEMATIC_TIER_TRANSITION        = tier 0 → tier 1 (BE → +15p at MFE ≥ 30p). N=33 firings, 17 PREMATURE (51.5%), 10 GOOD (30.3%), 6 IRRELEVANT (18.2%). This transition simultaneously (a) locks +15p profit and (b) moves the software stop STRICTLY BEYOND BE, ARMING ratchet exhaustion (tiered_ratchet.py:643-646). Both mechanisms independently produce the incompatible-with-continuation exit on the flagged 09-23 case.

0820_FIRST_INCOMPATIBLE_TIGHTEN_TS      = 2026-09-23T12:35:00+00:00
0820_STOP_BEFORE                        = 13296.85 (tier 0, BE)
0820_STOP_AFTER                         = 13281.85 (tier 1, entry − 15p — the value the operator explicitly asked to trace)
0820_QM_STATE_AT_TIGHTEN                = S1 ACCEPT (above entry, inherited context); S2 ACCEPT+cont (below entry, THIS position's cleared-behind); PDL BREAK_AWAY (above entry, inherited); NEAREST_00 ACCEPT (above entry, inherited). Zero REJECT active. Zero OSCILLATING active. BREAK_AWAY present (PDL). continuation_positive_count=4. cleared_behind_count (past-entry, in-direction) = 1 (S2).
0820_STRUCTURAL_STATE_AT_TIGHTEN        = position 33.4p in profit past S2 (accepted below going down); next in-direction structural level S3 @ 13247.95 is 16.5p further below current close 13264.45 — NOT YET INTERACTED (interaction opens at 14:25, ~2 hours later); no adverse re-cross detected by any classifier; no REJECT at any active level; all in-direction evidence continuation-positive.
0820_PREVIOUS_STOP_WOULD_SURVIVE        = YES. Retained tier-0 BE stop 13296.85 is at entry (SHORT: sw_stop == entry) so ratchet exhaustion is disabled (`beyond_be` requires strict inequality, tiered_ratchet.py:643-646). Every subsequent bar close through session end 16:55 remains ≤ 13291.75 (max is 13:25 close 13287.85, which is 8.99p BELOW the retained BE stop) → no software-stop breach. No lawful ratchet exit fires. First alternative structural exit is 14:35 S3 FINAL_REJECT.
0820_COUNTERFACTUAL_EXIT                = NY_CLOSE at 2026-09-23T16:55:00+00:00 @ 13233.85. (Alternative structural exit at 14:35 S3 FINAL_REJECT @ 13255.45 = +41.40p.)
0820_COUNTERFACTUAL_PIPS                = +63.00p (retained BE, hold to session close). +41.40p (retained BE, exit at 14:35 S3 REJECT). Production actual: +28.10p. Delta vs production: +34.90p (NY_CLOSE) / +13.30p (S3 REJECT). MFE session peak: 72.9p.

APR14_TIGHTEN_STATE                     = tier 0 → tier 1 at 2026-04-14T12:00:00+00:00; stop 13533.85 (BE) → 13548.85 (+15p lock); MFE 30.6p. QM at tighten: PDH ACCEPT (below entry — inherited context); NEAREST_50 BREAK_AWAY (above entry — THIS position's cleared-behind). Zero REJECT active. Zero OSCILLATING active. BREAK_AWAY present. continuation_positive_count=2. cleared_behind_count=1 (NEAREST_50). Retained BE counterfactual: NY_CLOSE @ 13561.85 = +28.00p vs production RATCHET_EXHAUSTION at 14:00 @ 13584.35 = +50.50p (delta −22.5p). Classification: GOOD_TIGHTEN — the tighter stop enabled exhaustion which correctly caught the peak; retained BE would have run to a plateaued NY_CLOSE at reduced profit.

CAUSAL_EXISTING_DISCRIMINATOR_FOUND     = NO for the specific 09-23 vs 04-14 comparison. Every existing causal feature (cleared_behind_count, any_reject_active, any_oscillating_active, any_break_away_active, target_ahead_final_state, target_ahead_dist_pips) is either IDENTICAL between the two cases or points in the WRONG direction (continuation_positive_count is 4 for the SHORT [PREMATURE] and 2 for the LONG [GOOD] — inverted from the intuition that more continuation evidence should predict continuation). MARGINAL at population scale: any_reject_active_rate 84.8% (GOOD) vs 62.2% (PREMATURE) = 22.6 pp gap; but overlap is heavy (62% of PREMATURE tightens still have a REJECT present) and this signal is silent on both operator-flagged cases.

DISCRIMINATOR                           = "presence of a fresh REJECT at any level" is the only existing feature with meaningful population-level separation (22.6 pp). It does NOT discriminate the specific 09-23 vs 04-14 cases (both show any_reject_active=False at their tier 0 → 1 moment). No feature or combination of existing features cleanly separates PREMATURE from GOOD.

SMALLEST_CORRECTION_IF_ANY              = NONE within existing-machinery-only + no-authority-changes ruling. The mechanism producing the sequencing failure is architectural: the ratchet advances by MFE (price milestone), the observer resolves by bar cadence (state-machine time-in-zone), and no existing signal composes the two clocks. Any correction requires either:
  (a) a tier-advance gate on the ratchet ("tier 0 → 1 defers until an in-direction structural level past entry is FINAL_ACCEPT-stamped" — this would have deferred the 08:20 tighten until 11:05 S2 ACCEPT, which does not resolve the 09-23 case because S2 stamps 90 minutes before the tier 1 fire anyway; a stricter gate would require "…until target-ahead has been interacted" which does resolve 09-23 but adds a bar-count clock the ratchet does not currently read); OR
  (b) an exhaustion suppressor on the QM continuation signal (this is exactly the previously-rejected QM continuation veto; net −30.1p on this population per qm_continuation_veto_ratchet_exhaustion_20260923.md); OR
  (c) a bar-volatility / ATR-normalised progression detector added to the observer (this is a NEW classifier, out of scope).
None of (a), (b), (c) is "smallest".

READY_FOR_IMPLEMENTATION_RULING          = NO. The sequencing failure is real, quantified (45/105 tightens PREMATURE across the population, +34.9p average recoverable pip loss on the 08:20 SHORT alone), and its most-problematic transition (tier 0 → 1) is identified. But existing causal machinery does NOT discriminate PREMATURE from GOOD firings well enough to justify a small conditional correction. Any resolution requires new architectural surface (either a structural-progression precondition on tier advancement, or a QM-continuation-aware exhaustion suppressor, or a new observer primitive for leg-complete/continuation-exhausted); each is a new increment requiring its own operator ruling and its own regression against this same 93-event overlap population.
```

*Stop.*
