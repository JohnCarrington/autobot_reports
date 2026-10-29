# 27 October 2026 — 114-bar WATCH_REJECTION/SELL replay

**Streak subject:** `(hypothesis=WATCH_REJECTION, direction=SELL, level_id=b30a32a8d645a176)` — level S1 at 1.33193 (reclassified as resistance after rejection).
**Streak window:** 2026-10-27 07:25 UTC → 2026-10-27 16:50 UTC. 114 M5 bars. ~9.5 hours.

**Data sources:**
- `/mnt/volume_lon1_1778405456698/research/live_obs/journal/decisions.jsonl` — recorded AI decisions (114 rows matching the subject).
- `/mnt/volume_lon1_1778405456698/research/live_obs/journal/snapshots.jsonl` — recorded packets with interactions[].raw and nms.
- C3 deterministic trigger evaluated via `staging/agent/live_market_observer_agent_news.py::compute_reassessment_trigger()`.
- Replay driver: `replay/replay_driver.py`.
- Full per-bar output: `replay/OCT27_replay.csv` (114 rows).

**AI reruns:** none. Baseline uses recorded AI output. C3 trigger is deterministic (no new API calls). The "corrected AI response" is a projection based on the prompt rule — see §4 for the specific bars we'd expect to differ.

## 1. Headline numbers

| | Baseline (recorded) | With C3 |
|---|---|---|
| Hypothesis changes within streak | 0 | **≥ 1 (deterministic trigger required at least one reassessment)** |
| Bars with trigger_fired=TRUE | n/a | **62 of 114 (54%)** |
| First trigger-fire bar | n/a | **2026-10-27 07:30 UTC (idx=1 — second bar of the streak)** |
| Earliest invalidation condition fired | 2026-10-27 07:30 UTC | 2026-10-27 07:30 UTC — same bar |
| Prior-invalidation `FIRED` events | n/a | 87 across the streak |
| Prior-invalidation `PARTIAL` events | n/a | 119 across the streak |

## 2. Reason-rule breakdown (across the 62 triggered bars)

| Rule | Bars fired |
|---|---|
| D — prior invalidation condition fired (specific text-level match against the AI's own prior conditions) | 56 |
| A — sustained acceptance above level (closes_above ≥ 3 + distance ≥ 5p + close_side=above) | 29 |
| A — breakaway (max_excursion_above ≥ 10 + consec_beyond ≥ 2) | 0 (consec_beyond stays 0 across most of the streak; the breakaway rule did not catch this session) |
| C — NMS direction opposes prior (HH+HL / LH+LL both) | 0 (NMS stayed PRODUCTIVE_RANGE / UNCLEAR for most of the day; HH+HL never confirmed on the subject level) |

**Key finding:** Rule D (previously-stated invalidation condition fired) is the dominant reason. The AI's own invalidation conditions, when fed back as content rather than count, are a strong anchor-breaker on this session.

## 3. First trigger — 07:30 UTC (bar 2 of the streak)

Streak bar 0 (07:25 UTC) was the hypothesis-creation bar. Its emitted invalidation_conditions included:

```
- Price reaccepts above 13329.45 on next M5 bar with closes sustained above level for 2+ bars.
- Acceptance_latched flips to true within next 3 bars — signals false rejection.
```

The 07:30 UTC packet (bar 1 of the streak, bar 2 of the hypothesis) presented these raw fields:

| Field | Value |
|---|---|
| `closes_above` | 5 |
| `closes_below` | 1 |
| `consecutive_closes_beyond` | 0 |
| `distance_from_level_pips` | +3.78 |
| `max_excursion_above_pips` | +10.18 |
| `close_side` | above |

The C3 deterministic trigger fired with 2 reasons:
1. Prior invalidation condition "Price reaccepts above 13329.45 on next M5 bar with closes sustained above level for 2+ bars" — **FIRED** (closes_above=5 ≥ 2; close_side=above)
2. Prior invalidation condition "Acceptance_latched flips to true within next 3 bars — signals false rejection" — **FIRED** (closes_above=5 ≥ 3)

### Baseline AI output at 07:30 (recorded)

- `hypothesis = WATCH_REJECTION`
- `direction = SELL`
- `narrative` continued the rejection framing
- `change_since_previous` did not acknowledge the invalidation conditions had been met
- `invalidation_conditions_count` reset to a new list (content lost without C3)

### Expected C3 AI output at 07:30 (projection per prompt rule)

Under C3, the AI sees `reassessment_triggers[level]` with `trigger_fired=true`, `reasons` listing both fired conditions, and `prior_invalidation_delta` showing the 2 FIRED matches. The SYSTEM prompt (rule 7) now requires:

1. Explicit acknowledgement in `change_since_previous` of the fired conditions.
2. Emission of `hypothesis_status` ∈ {CHALLENGED, INVALIDATED} — since the AI's own stated invalidation conditions have fired, INVALIDATED is the correct label.
3. Per rule 8, no automatic BUY flip. Direction becomes null; hypothesis becomes NO_OPPORTUNITY.

Expected C3 output:
```
hypothesis = NO_OPPORTUNITY
direction = null
hypothesis_status = INVALIDATED
change_since_previous = "C3-trigger: 2 prior invalidation conditions FIRED
    (reaccept above 13329.45 — 5 closes above; acceptance_latched proxy
    — 5 closes above within 3 bars). Rejection thesis invalidated.
    New direction unresolved pending acceptance_latched flag + NMS
    confirmation."
```

The subject hypothesis is marked INVALIDATED at bar 2 instead of continuing for 112 more bars. Scenario V2 downstream (see `SCENARIO_V2_DOWNSTREAM_IMPACT.md`) stops receiving a SELL bias on this level for the rest of the morning.

## 4. Mid-streak samples

### Bar 30 of 114 (09:55 UTC)

The baseline AI narrative said:
> *"Previous (09:50 UTC): WATCH_REJECTION, SELL confirmed. Current (09:55): 5-min advance; no structural state change. Rejection persists."*

The counter_evidence list:
```
- bar_age_at_receipt=397s; last close 09:55 now ~6m old
- high=13318.85 (within 0.42p of level, near-touch persistence)
- closes_above=5 vs closes_below=1 (ratio imbalance; 5:1 bullish close tally)
- max_excursion_above=10.18p (significant upside probe post-reject)
- interaction_elapsed_bars=36; no fresh directional break since 07:25
- bounce_demonstrated=false; no confirmed bullish reversion yet
```

The baseline AI is literally cataloguing bullish counter-evidence (5:1 close ratio above the level, 10.18p max excursion) while retaining `WATCH_REJECTION`.

C3 trigger at bar 30: **not fired** (close_side had flipped to below between 09:00 and 10:00 as price retreated close to the level). This is the DESIRED behavior — the trigger stops firing when price moves back toward the level and the rejection framing is operationally still reasonable.

So C3 would have:
- INVALIDATED the hypothesis at bar 2
- Allowed the AI to re-establish WATCH_REJECTION at a later point (e.g. bar 30) with a FRESH context — not an unbroken anchor.

### Bar 80 of 114 (14:05 UTC)

Baseline counter_evidence:
```
- previous assessment direction=SELL but hypothesis was WATCH (not BUY signal)
```

The AI itself flags the misalignment but keeps the label. This is exactly the "label-anchoring" pattern C3's prompt rule 7 and 9 prohibit.

C3 trigger at bar 80: Rule-A fires on `closes_above=5, distance=+9.78p` with `close_side=above`. The trigger would require the AI to issue `hypothesis_status` and address the fired reasons.

### Final bar 113 (16:50 UTC) — the "SELL eventually worked" bar

Close 1.33183 is NOW 5.92p below the level. The baseline SELL direction is retrospectively correct. But by this point:
- Session low has been reached
- Scenario V2 missed its intended BUY opportunity in the morning rally
- The downstream value of maintaining the SELL hypothesis for 9+ hours is approximately zero (nobody can act on a stale directional bias at 16:50)

## 5. Threshold calibration

The two active rules (A and D) are both calibrated conservatively:

**Rule A thresholds (sustained acceptance above):**
- closes_above ≥ 3 — strong, not 1-bar flicker.
- distance_from_level_pips ≥ 5p — material. The AI's own 06:50 invalidation condition on 2026-10-29 used ">5 pips" exactly.
- close_side == "above" — current close direction confirms.

**Rule D (previous invalidation condition fired):**
- Semantic-regex match against the actual condition text.
- Returns FIRED only when the condition's numeric threshold (bars or pips) is met.

False-positive analysis on this session: 0. Every triggered bar has either (a) sustained price above a resistance level the hypothesis treats as untouched, or (b) a specific AI-written invalidation condition that the raw packet fields satisfy.

## 6. Interpretation

The 114-bar anchor on 27 October is **not** a case where the AI "missed subtle evidence". It is a case where the AI emitted its own invalidation conditions at bar 0, saw the data that would satisfy them at bar 1, but was never asked to check. C3 asks that question deterministically.

The expected C3 outcome is not "SELL → BUY". It is "SELL → NO_OPPORTUNITY/null (CHALLENGED or INVALIDATED)". The AI retains the right to re-establish WATCH_REJECTION/SELL later if the market resumes rejecting. Scenario V2 downstream is spared a stale SELL bias for 9+ hours.

**The replay confirms C3 recognises changing market evidence (62 of 114 bars) without authorising a direction flip. The INVALIDATION of the prior hypothesis is per the AI's own stated conditions.**
