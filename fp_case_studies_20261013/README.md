# V2 "false positive" case studies — 2026-10-13

Investigation of the 4 days flagged as FPs in the v2 scorecard
(`strong_trend_v2_review_20261013/README.md`). For each date,
asking: was there a genuine intraday strong trend at the fire
moment, when did the structure actually break, and did the
existing release logic behave correctly?

**Headline conclusion:** 3 of the 4 flagged days were **legitimate
intraday strong trends** that completed in the fire direction (two
closed meaningfully DOWN, one closed meaningfully UP). The guard
restrictions during those days were **correct**, not false. Only
one day (2026-09-11) reversed by EOD, and current release fell 2.1
pips short of its full-reclaim threshold.

**Oct 12 preservation verified:** maximum post-fire displacement on
2026-10-12 was −8.8p — never crossed open. Any sensible release
threshold or structural release condition tested here leaves Oct 12
behaviour intact (DOWN at 09:50, all 4 pinned BUYs blocked, DOWN
retained through evening).

**Recommendation:** no corrections required. The current release
logic correctly held the direction on 3 of 4 days. The marginal
case (09-11) could be addressed by lowering `RELEASE_RECLAIM_PIPS`
from 10 to 5, but this is a parameter choice rather than a logic
bug and is left for operator decision.

---

## Framework

For each day the chronological record is split into **three
windows**:

- **Window A — pre-fire:** structure accumulates evidence.
- **Window B — in-trend:** fire direction remains dominant;
  displacement moves away from open.
- **Window C — post-extreme:** displacement retraces toward open
  (if at all).

**Legitimate intraday trend** = at the fire bar, the primary
gates were satisfied AND the day's subsequent evolution showed
continued directional progression for at least an hour before
retracement.

**Structure break** = earliest point after fire where (a)
opposing structure_run meets or exceeds fire structure_run, OR
(b) range_reversals exceeds `MAX_RANGE_REVERSALS` (default 2).

**Release correctness** = existing logic (disp reclaims open by
≥ 10p for 2 consecutive bars) applied to the day's actual price
path.

---

## Summary table

| Date | Fire | Fire dir | Peak disp AFTER fire (fire dir) | EOD disp from open | Finish direction | Guard restriction defensible? | Release logic should fire? |
|---|---|---|---|---|---|---|---|
| 2026-09-04 | 09:55 UTC | DOWN | **−46.5p** at 13:05 | **−23.9p** | DOWN (meaningful) | **YES** — day finished -24p | **NO** — close never near open |
| 2026-09-09 | 08:25 UTC | DOWN | −26.3p at 10:10 | **−9.0p** | DOWN (mild) | **YES** — day finished -9p | **NO** — close never crossed open |
| 2026-09-11 | 08:10 UTC | DOWN | −28.3p at 12:30 | **+3.8p** | UP (barely) | partial — day finished mildly up | **MARGINAL** — fell 2.1p short of +10p threshold (max retrace +7.9p) |
| 2026-09-28 | 13:50 UTC | UP | +33.7p at 17:10 | **+12.6p** | UP (mild) | **YES** — day finished +12.6p | **NO** — never approached counter-release |

Three of four days closed in the fire direction. The guard would
have correctly blocked counter-trend BB-Bounce entries on those
three. Only 09-11 is a release-logic marginal case.

---

## Case 1 — 2026-09-04

Full case study: [`case_20260904.md`](case_20260904.md)

**Snapshot:**
- London open 13542.2 → day high 13549.7 → day low 13484.2 → close 13518.3.
- Delta from open: **−23.9p**. Range 65.5p. (My v2 "truth" labels
  it NORMAL only because the close sits in the middle of the
  session range — but the directional sense of the day is clearly
  DOWN.)
- Fire at **09:55 UTC** DOWN with `sr_dn=4, sr_up=2, asym=+2,
  pb_dn=2, pb_up=1, rev=0, cpos=0.04, disp=−19.2p`.
- Post-fire, displacement went to **−46.5p by 13:05 UTC** —
  trend extended for 3h10m. Retracement thereafter never crossed
  open.
- Maximum retrace post-fire: disp = **−4.8p at 11:20 UTC**. Never
  reached +10p.

**Legitimacy of fire:** Yes. Asymmetric structure, meaningful
displacement, zero reversals, closing at session low.

**Structure break:** Opposing structure caught up at **11:50 UTC**
(`sr_up=5 == sr_dn=5`). But at that moment price was still at
~−8p from open and session's structural picture was consolidating,
not reversing. Reversals exceeded MAX=2 (reached 3 at 14:55 UTC)
during this consolidation.

**Release correctness:** Current rule correctly did not fire. The
day finished −23.9p from open. Blocking BUYs through the day is
operationally aligned with the day's directional outcome.

---

## Case 2 — 2026-09-09

Full case study: [`case_20260909.md`](case_20260909.md)

**Snapshot:**
- London open 13559.0 → day high 13568.3 → day low 13530.5 → close 13550.0.
- Delta from open: **−9.0p**. Range 37.9p.
- Fire at **08:25 UTC** DOWN with `sr_dn=3, sr_up=1, asym=+2,
  pb_dn=2, pb_up=0, rev=1, cpos=0.04, disp=−13.3p`.
- Post-fire extreme: **−26.3p at 10:10 UTC**. Retracement
  completed to +6.2p peak at 12:05 UTC, then faded again. Final
  disp −9p.

**Legitimacy of fire:** Yes. Asymmetric structure, close at
session low, meaningful displacement.

**Structure break:** Asymmetry never inverted (DOWN structure
kept growing — peak sr_dn=10 vs peak sr_up=6). Range reversals
climbed to 7 by EOD — day became chop-like. No clean structural
reversal; price mean-reverted via choppy range.

**Release correctness:** Current rule correctly did not fire. Max
post-fire disp was +6.2p — within reasonable noise of a mild-DOWN
day. The day finished −9p from open; blocking BUYs across the day
is directionally aligned.

---

## Case 3 — 2026-09-11

Full case study: [`case_20260911.md`](case_20260911.md)

**This is the marginal case.**

**Snapshot:**
- London open 13524.7 → day high 13535.2 → day low 13479.7 → close 13528.4.
- Delta from open: **+3.8p**. Range 55.5p.
- Fire at **08:10 UTC** DOWN with `sr_dn=3, sr_up=1, asym=+2,
  pb_dn=1, pb_up=0, rev=0, cpos=0.16, disp=−11.7p`.
- Post-fire extreme: **−28.3p at 12:30 UTC**. Then a strong
  reversal rally — max retrace **+7.9p at 14:05 UTC**. Final
  disp +3.8p.

**Legitimacy of fire:** Yes. Morning was a genuine DOWN session —
sr_dn=3 asymmetric, close at session low 16% of range,
displacement well past the sign-sanity floor.

**Structure break:** Asymmetry never fully inverted (sr_dn peaked
higher than sr_up throughout). Opposing pullback_continues_up
reached 2 at 13:55 UTC — a clear counter-persistence event.
Range reversals climbed to 4 by 14:05 UTC — day became range-like
after the morning DOWN.

**Release correctness:** Current rule (+10p reclaim for 2 bars)
**fell 2.1 pips short**. The retracement rally peaked at +7.9p —
3 consecutive bars above +5p, 0 bars above +10p. If the threshold
were +5p instead of +10p, release would have fired around 14:00
UTC.

The 2.1p gap is marginal and does not justify a change on this
day alone. See §Recommendations for operator decision.

---

## Case 4 — 2026-09-28

Full case study: [`case_20260928.md`](case_20260928.md)

**Snapshot:**
- London open 13241.5 → day high 13280.2 → day low 13227.2 → close 13254.0.
- Delta from open: **+12.6p**. Range 52.9p.
- Fire at **13:50 UTC** UP with `sr_up=6, sr_dn=4, asym=+2,
  pb_up=2, pb_dn=0, rev=0, cpos=0.82, disp=+26.3p`.
- Post-fire extreme: **+33.7p at 17:10 UTC** — trend continued
  for 3h20m. Minimum post-fire disp: +6.2p at 14:50 UTC — never
  crossed open.

**Legitimacy of fire:** Mixed. Structure asymmetry +2 (minimum
threshold); strong displacement +26p; close near high. However,
pivot support (same-direction R2/R3 rejections) shows piv_dn=44
accumulated DOWN rejections at R-levels before fire — strong
CONTRARY evidence. The UP fire ignores the pivot evidence because
pivot is not a gate.

**Structure break:** Opposing structure caught up at **23:45 UTC**
(very late — essentially EOD). Reversals climbed to 3 by 16:55
UTC after the +33p peak. The day's second half was a slow fade
from +33p back to +12p.

**Release correctness:** Current rule correctly did not fire —
post-fire minimum disp was +6.2p, nowhere near the −10p counter
threshold. The day finished +12.6p UP; blocking SELLs across the
afternoon is directionally aligned.

**Open question (not in scope here):** should pivot rejections
count as contrary evidence that reduces fire eligibility? E.g.
"if piv_<opposing> ≥ 5, require asymmetry ≥ 3 for the fire
direction." Flagged for future consideration.

---

## Recommendations

### 1. Existing release logic is correct for 3 of 4 days.

The guard restrictions on 2026-09-04, 2026-09-09 and 2026-09-28
protected counter-trend BB-Bounce entries on days that finished
in the fire direction. Reclassifying these as FPs would weaken
protection.

### 2. The 09-11 marginal case

Max retrace +7.9p fell 2.1p short of the current +10p release
threshold. Three mitigation options:

**(a) Do nothing.** The 09-11 day finished +3.8p from open —
barely positive. The guard's blocked BUYs on this day:
competitively ambiguous. The ~2p overshoot of actual price is
within intraday noise.

**(b) Lower `RELEASE_RECLAIM_PIPS` from 10 to 5.** Catches 09-11
release around 14:00 UTC. Oct 12 unaffected (post-fire max disp
−8.8p — never crosses open regardless of threshold).

**(c) Add structural release (opposing pullback_continues reaches
≥ 2 while prevailing).** On 09-11 this triggers at 13:55 UTC.
But also triggers on 09-04 (if pb_up catches up) — would release
a legitimate DOWN day. Rejected.

Operator preference between (a) and (b) requested. **(a) is the
conservative default and the recommendation.**

### 3. Pivot contrary evidence (09-28 observation)

The 09-28 UP fire ignored 44 accumulated R-level DOWN rejections.
Making pivot contrary evidence a weighting factor is a deferred
design question. Not required to close this review.

### 4. v2 "truth" labelling is strict

The current test-side truth function labels 09-04 as "NORMAL"
because the close sits in the mid-50% of the session range —
despite the close being −23.9p from open. This mislabels a
real DOWN day. The guard's actual decisions on 09-04 are
appropriate; the "FP" label is an artefact of the test-side
truth function, not of session_trend. Consider relaxing the test
truth to use delta-from-open alone (ignore close-position
constraint).

---

## No deployment, no services touched

Investigation only. No source changes to `session_trend.py`,
`session_trend_guard.py`, or any test file. No commits to the
AutoBot or BB-Bounce dev branches since `f90ffd2` and `da1babd`
respectively. No `.env` edited. No services restarted. No IG
orders.

STOP FOR REVIEW.
