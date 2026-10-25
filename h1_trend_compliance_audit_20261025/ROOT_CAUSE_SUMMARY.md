# Root-cause summary — EMA Pullback H1 compliance (2026-10-23)

**Mode.** Read-only. No strategy, service, or order change.
**Scope.** Answer the five questions in the brief §10.G directly.
**Date.** 2026-10-25
**Primary evidence.** `H1_TREND_COMPLIANCE_AUDIT.md`, `LOSING_TRADE_H1_REVIEW.md`,
`TIMESTAMP_AUTHORITY_AUDIT.md`, `H1_TREND_TIMELINE.csv`,
`M5_SETUP_H1_COMPLIANCE.csv`, `H1_TREND_CHARTS/`.

---

### 1. Is the H1 trend qualification implemented faithfully?

**Yes — to the build-spec, but the build-spec itself is markedly weaker
than the owner's stated qualitative description.**

`ema_pullback/trend.py:51-104` implements exactly what its docstring
promises: strict EMA ordering (BUY: `EMA8 > EMA13 > EMA20`) AND
three-same-signed single-hour EMA deltas (`now > prev` for all three).
Timing is correct (TIMESTAMP_AUTHORITY_AUDIT.md). The code faithfully
executes its specification.

The owner's description, however, demands additionally:

* "Clearly sloping" (magnitude, not just sign).
* "Visibly separated" (magnitude, not just ordering).
* "Established trend" (persistence, not just a single-hour snapshot).

None of these three qualifiers exist in the code or in the build-spec
text. The implementation is therefore faithful to the DOCUMENT it was
built against, but divergent from the OWNER'S INTENT as described in
this brief.

### 2. Is the implementation accepting weak or flat H1 trends?

**Yes — on 2026-10-23, 83% of setups fired during H1 hours an operator
would NOT call a clear established trend.**

| H1 visual class (research-only) | setups | % | fills |
| ------------------------------- | -----: | -: | ----: |
| A — clear established           | 4      | 17% | 1     |
| B — weak but aligned            | 17     | 74% | 4     |
| C — flattening / exhausting     | 2      | 9%  | 1     |
| D — sideways                    | 0      | 0%  | 0     |

Concrete examples of weak admissions:
- **H1@06 SELL** (C): first SELL hour after 5 NONE hours, sep -1.13p
  (less than 2 points). Fired a setup; fortunately the trend held.
- **H1@13 SELL** (B flash): a single-hour SELL between two NONE hours.
  Fired 3 setups (all cancelled).
- **H1@19 SELL** (B converging): EMAs CONVERGING (sep narrowed by
  +0.20 vs prior hour) and the slowest slope magnitudes of the day.
  Fired 2 setups; one filled and lost -12 pips.

### 3. Are multiple M5 touches inflating the setup count?

**Yes — materially. 23 raw triggers collapse to 11 distinct pullback
movements (30-min grouping) or 4 contiguous H1 trend episodes.**

The build-spec defines a trigger as a single M5 bar whose low (BUY) or
high (SELL) touches EMA 8 and whose close has not already breached EMA
21 against direction. Once a pending order cancels on an EMA-21-close,
the next qualifying M5 bar re-arms immediately. On continuously
oscillating price in a trending hour, this fires 2-3 times per hour.

Four separate H1 hours on 2026-10-23 fired 3 setups each (H1@07, H1@13,
H1@15) or 2 setups each (H1@00, H1@06, H1@09, H1@19). Compare the
research spec `research/ema_pullback_frequency_20261024/strategy_specification.md`
§4, which explicitly says "multiple candles touching EMA 8 inside the
SAME unresolved pullback do NOT count as separate opportunities" — but
the build spec and the current detector do count them, provided the
previous order has resolved.

Collapsing by episode:

| grouping                                 | count on 2026-10-23 | matches owner's 3-5? |
| ---------------------------------------- | ------------------: | -------------------- |
| Raw M5 triggers (current implementation) | 23                  | ~6× too many         |
| Distinct pullback movements (30-min gap) | 11                  | ~2-3× too many       |
| Contiguous H1 trend episodes             | 4                   | within range         |

### 4. Are the losing trades associated with weak H1 trends?

**Partially.** Of the 4 losses (11:20, 15:55, 16:45, 20:05):

| trade | H1 class | why it lost |
| ----- | -------- | ----------- |
| 11:20 | **A**    | Peak-strength H1 — but fill came 30 min late at the exhaustion low. Not a weak-H1 problem. |
| 15:55 | B        | Transitional: H1 flipped SELL at 15:00 after NONE at 14:00. Weak start of afternoon run. |
| 16:45 | B        | Same H1@15 hour as 15:55 — multi-touch inflation on a weak hour. |
| 20:05 | B (converging) | Clean "weak-H1 admission" case — flattening/exhausting SELL. |

**Three of the four losses fired during B-class H1 hours** that an
operator would describe as weak, transitional, or converging. The
fourth loss (11:20) is unrelated to H1 strength — it is a
late-fill-at-trend-exhaustion artefact.

**Both winners (06:55 trail +6.00, 10:30 trail +4.75) fired during
B/C-class H1 hours too**, so H1 class alone does not perfectly
discriminate. The common factor among winners is faster trigger→fill
delay (15 vs 26 min average), which caught the start of a push rather
than its end.

### 5. Are there any H1 timestamp or lookahead defects?

**No.** TIMESTAMP_AUTHORITY_AUDIT.md confirms:

- H1 bars built from exactly 12 completed M5 bars; forming hour never
  emitted (`h1_builder.py:85-91`).
- EMA computation causal (`pandas.ewm(span, adjust=False, min_periods=1)`).
- Each M5 decision uses the latest fully-completed H1 as-of the M5
  bar's close (`replay_historical.py:143-162`, `service.py:93-100`).
- Replay point-in-time slice byte-identical to live service by
  construction (causal ewm).
- No cache stale across steps; trend recomputed every bar.
- Weekend / gap handling walks back to the most recent prior H1 —
  cannot admit extra triggers.
- No forward H1 index access anywhere in the codebase.

**The 23-vs-expected-few discrepancy is NOT a timing bug.** It is a
specification / design question about how selectively the H1 and the
multi-touch counting rules should operate.

---

## Executive summary (one page)

- **Code is faithful to the build-spec** (which calls for strict
  ordering + three same-signed single-hour EMA deltas).
- **Build-spec is weaker than the owner's qualitative description**
  (no magnitude, no established-trend check).
- **On 2026-10-23, 83% of setups fired during H1 hours an operator
  would not call clearly trending.**
- **23 raw triggers compress to 4 genuine H1 trend episodes**
  (6× inflation) and 11 distinct pullback movements (2-3× inflation);
  this matches the owner's "3-5 per day" at the episode level.
- **3 of 4 losses occurred on weak-H1 (B-class) hours**; the fourth
  loss was a late-fill-at-exhaustion on a strong-H1 (A-class) hour.
- **No lookahead, no stale H1, no timing defects.**
- **No code change recommended by this audit.** The brief forbids
  inventing thresholds. The audit documents the gap between the owner's
  intent and the build-spec's current operationalisation and places
  the specification-amendment decision in front of the owner.

---

## Scope reaffirmed

- No modification to `trend.py`, `pullback.py`, `state_machine.py`,
  `service.py`, `exit_management.py`, `exit_simulator.py`,
  `exit_state_machine.py`, or any other strategy module.
- No parameter tuning.
- No new indicator or filter proposed as the owner's rule.
- `EXECUTION_ENABLED=false`.
- No deploy, no restart, no IG order.
