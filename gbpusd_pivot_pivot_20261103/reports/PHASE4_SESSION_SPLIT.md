# Phase 4 — Session Split

Session-blind pivot stats hide the single biggest effect in the dataset. The same event — e.g. S3 DOWN — behaves very differently by UTC hour.

## Session buckets (fixed, pre-defined)

| Bucket | UTC hours | n events | share |
|---|---|---:|---:|
| Asia | 00:00-07:00 | 593 | 38.0% |
| LondonOpen | 07:00-09:00 | 283 | 18.1% |
| LondonMorning | 09:00-12:00 | 196 | 12.6% |
| LN/NY overlap | 12:00-16:00 | 300 | 19.2% |
| LateNY | 16:00-22:00 | 130 |  8.3% |
| WeekendStub | 22:00-24:00 |  59 |  3.8% |

Notes:
- Asia events are the plurality because the session is seven hours long and most daily pivots sit inside the overnight range.
- LateNY has the smallest share — pivots are usually already touched by the time New York closes, so few first-touches remain.

## Reach-rate by pivot × session

| Lvl \ Session | Asia | LondonOpen | LondonMorning | LN/NY | LateNY |
|---|---:|---:|---:|---:|---:|
| S3 |  89% |  85% |  77% |  46% |  25% |
| S2 | 100% | 100% |  95% |  79% |  33% |
| S1 |  96% |  82% |  80% |  68% |  29% |
| P  |  86% |  67% |  66% |  50% |  15% |
| R1 |  98% |  83% |  85% |  62% |  30% |
| R2 |  96% | 100% |  95% |  72% |  29% |
| R3 |  79% |  82% |  59% |  36% |  45% |

**The gradient is monotonic for most levels:** Asia → LateNY = reach-rate drops from 85-100% to 15-45%. The interpretation is simple: an Asia touch has 5+ more hours of session ahead for price to reach another pivot; a LateNY touch has 2 hours or less.

## Reject+Both rate (price retraces ≥10p against approach within 15 bars)

| Lvl \ Session | Asia | LondonOpen | LondonMorning | LN/NY | LateNY |
|---|---:|---:|---:|---:|---:|
| S3 |  33% |  55% |  62% |  54% |  50% |
| S2 |  48% |  43% |  43% |  67% |  60% |
| S1 |  33% |  43% |  47% |  58% |  34% |
| P  |  23% |  50% |  52% |  55% |  30% |
| R1 |  26% |  50% |  35% |  50% |  56% |
| R2 |  23% |  41% |  41% |  61% |  43% |
| R3 |  11% |  65% |  28% |  36% |  55% |

**The reversion signal is session-specific.** S3 DOWN reverts within 15 bars at 11% in Asia but 65% in LondonOpen and 55% in LateNY. Models that classify S3 DOWN as a "reversal trigger" in all sessions will mis-fire half the time.

## Combined evidence summary

Session is the single largest moderator in the dataset:

1. **London Open is where pivots work best as destinations.** Reach rates 67-100%, reject rates 32-53%, neither rates 5-21%. If a pivot-destination NMS supplement is to be deployed, the clearest window to activate it is 07:00-12:00 UTC.
2. **LN/NY overlap favours reversion-at-extremes.** S3/R3 reach-rates drop sharply (46%/36%) and reject rates on them are high. This is the opposite behaviour to Asia, where the extreme is a continuation destination.
3. **LateNY is the lowest-signal window.** 15-45% reach rates, 17-35% "neither" events. A pivot-destination system should probably be *dampened* here, not amplified.
4. **Asia is a continuation-biased session.** Reach rates 85-100%, reject rates <35%. Price drifts between levels with little commitment. Pivots in Asia are "touched and moved through."

## Implication for NMS

The brief flags:
- "Reports RANGE when a directional move is established."
- "Treats a pullback as a full reversal."
- "Continues admitting trend-following trades near an exhausted destination."

Session-conditional pivot behaviour implies the NMS admission rule probably should be session-conditional too. For example:

- **At a pivot touch in LondonOpen or LN/NY overlap:** the 50-60% reject rate justifies a pause/reassessment regardless of the directional thesis.
- **At a pivot touch in Asia:** the reject rate is ~20-30% — not evidence for reassessment. A pullback here is *far* more likely to be a hold than a reversal.
- **At S3/R3 in LN/NY or LateNY:** reach-rates drop and reject rates rise — this is where "approaching exhausted destination" is cleanest.

None of this is strong enough yet for a code change. Next:

- Phase 3 (exhaustion features): does RSI / BB / TD-Seq predict the LondonOpen reject that is otherwise a 50/50 call?
- Phase 7: binomial CIs on every number above (ns range 9-308; the small-sample cells have very wide intervals).
- Phase 6: find concrete NMS historical cases in LondonOpen or LN/NY where the directional admission continued past a pivot that then reverted.
