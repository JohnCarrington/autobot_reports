# Era B GBPUSD_BB_BOUNCE_S benchmark — unresolved differences

**Status: NOT REPRODUCED.** The benchmark does not yet reproduce the
Era B strategy that produced 36 fills / +395.40 pips. Below is what is
established and what remains open.

## What the source and .env history establish

Retrieved at commit `c85481c` (2026-05-23 12:33 UTC, AutoBot repo) and
`e8fc9dd` (same day, 17:54 UTC — the counter-H1 rebuild). Env snapshots
pinned in `spec_pins/env_history/` cover 2026-05-23 → 2026-06-16 with
15 discrete `.env` states. Provenance in
`outputs_multi/provenance_manifest.json`.

**All admission gates other than pierce + rejection were disabled by
.env in Era B**, contradicting the earlier spec assertion in
`gbpusd_bb_bounce_s_implementation_spec_20260929.md` §5 that
"cascade-disagree and regime gates active":

- `BB_BOUNCE_CASCADE_GATE_ENABLED=0` throughout every Era B snapshot
- `GBPUSD_BB_BOUNCE_REGIME_FILTER_ENABLED=0` throughout
- `GBPUSD_BB_BOUNCE_NEWS_BLACKOUT_ENABLED=0` throughout
- `GBPUSD_BB_BOUNCE_MACD_EXTENDED_MOMENTUM_GATE_ENABLED=0` throughout
- `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED=false` from 2026-05-25 onward
  (env override — code default was `true` per e8fc9dd)

The pierce threshold moved during Era B:

| Effective (UTC) | `GBPUSD_BB_BOUNCE_PIERCE_THRESH_PIPS` | Evidence |
|---|---:|---|
| 2026-05-23 → 2026-05-24 15:25 | 0.5 | `backups/bb_bounce_counter_h1_20260523/.env` |
| 2026-05-24 15:25 → 2026-06-05 03:52 | 2.0 | `env-batch2-stranglers-20260524T152536Z` + `.env.bak-2026-05-27` |
| 2026-06-05 03:52 → 2026-06-05 04:17 | 0.5 (regression?) | `.env.bak.bb_trail-pre.20260605_035226` — a "pre" snapshot |
| 2026-06-05 04:17 → 2026-06-15 07:00 | 1.0 (inferred) | `.env.bak.pierce_thresh-pre.20260605_041746` shows 0.5, then a change |
| 2026-06-15 07:00 → 2026-06-24 (end) | 1.0 | `structure_break_enable-pre.20260615_120821`, `2026-06-16T120455Z.bak` |

`SCALE_OUT_TRIGGER_PIPS` tightened 10 → 8 before 2026-06-15. Runner
trail flipped ON at 2026-06-05 03:52 (`BB_BOUNCE_RUNNER_TRAIL_ENABLED=1`,
`ACTIVATE=12`, `OFFSET=6`).

## Signal parity — every variant leaves gaps

`outputs_multi/entry_parity_by_variant.csv`. All variants run pierce +
rejection close + counter-H1 gate (when env says on) + position-slot
gate (using the benchmark's own predicted exit times).

| Variant | Raw fires | After gates | Matched | FP | FN | Match rate |
|---|---:|---:|---:|---:|---:|---:|
| Fixed 0.5 | 101 | 61 | 27 / 36 | 34 | 9 | 75.0 % |
| Fixed 1.0 | 80 | 55 | 27 / 36 | 28 | 9 | 75.0 % |
| Fixed 2.0 | 42 | 33 | 14 / 36 | 19 | 22 | 38.9 % |
| Env-history | 63 | 45 | 22 / 36 | 23 | 14 | 61.1 % |

**No single threshold reproduces all 36 ledger fires**, consistent with
the pierce threshold moving during the period. But the env-history
variant matches *fewer* fires than the fixed 0.5/1.0 variants —
meaning the env-history table I reconstructed is not exactly the .env
state the trader was reading each day.

Sources of the FN gap in every variant:

1. Ledger fires that happened during an env-history window where my
   reconstructed pierce threshold was too high — e.g., a fire with
   pierce depth 0.8 p during a window my table says was 2.0 p. There
   are 9 such fires in the fixed-0.5 variant that get slot-blocked
   because of upstream benchmark exit-timing errors (my sim predicts
   the previous position stays open longer than it actually did in
   the ledger).
2. Broker fills where the ledger's `entry_price` differs from the bar
   close by > 2 p — accounted for by matching on rejection-bar
   timestamp + direction, so no true "unmatched" here.

## False-positive classification

`outputs_multi/false_positives_classified.csv`, 63 rows for the
env-history variant. Distribution:

| Reason | Env variant | 0.5 variant | 1.0 variant | 2.0 variant |
|---|---:|---:|---:|---:|
| REJECTED_BY_ENV_PIERCE_THRESHOLD | 0¹ | 23 | 11 | 0 |
| REJECTED_BY_POSITION_SLOT | 18 | 40 | 25 | 9 |
| REJECTED_BY_COUNTER_H1 | 0² | 0² | 0² | 0² |
| **UNRESOLVED** | **45** | **38** | **44** | **33** |

¹ The env variant already applies the env-history threshold at
detection time, so this class collapses into "would-be-arm-time
reject" and shows 0 here.

² Counter-H1 recorded zero blocks in every variant because the env
history says the gate was DISABLED across every snapshot from
2026-05-25 onward — matching the source-code check
`H1_COUNTER_GATE_ENABLED = _env_bool("GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED", "true")`
with `.env` set to `false`. If the ledger's small-sample of fires WAS
actually shaped by the counter-H1 gate, that would imply either the
env was different in reality or the gate was compiled-in from a
different branch.

**45 unresolved FP in the env variant** — pierces with matching
rejection candles that were NOT filtered by any gate we have source
+ .env evidence for. These are the primary open question.

Hypotheses for the unresolved FPs (not yet tested):

- **Bar-buffer contiguity guard** (commit `d5d67d6` 2026-05-21) —
  skips `evaluate()` on non-contiguous 5m buffer. On restart / gap /
  weekend-open the benchmark may fire where the live trader would
  have skipped. Requires modelling the live buffer state.
- **BB warmup / pre-market state** — the live trader only fires when
  the 5m CandleBuilder has ≥ 20 completed bars in a contiguous
  session. The benchmark uses the offline candle cache which is
  always complete; a live restart during Era B may have missed
  setups.
- **Concurrent-cap on other strategies** — even with a free
  BB_BOUNCE slot, other strategies (EMA_PULLBACK, TREND_V3, etc.)
  hitting the aggregate cap could have blocked BB_BOUNCE via the
  autobot-side concurrency gate. This benchmark does not model
  cross-strategy state.
- **Recorded but unreconciled ledger fires** — some ledger rows
  aren't Era B (the CSV has 174 total across all eras); overlap in
  rejection-bar timestamp with an Era B row could produce a spurious
  "match" while a real Era B fire (with different bar-close but same
  minute) shows as FP.

## Exit parity — 9 replayable of 36

`outputs_multi/exit_parity_blind.csv`. Classification of ledger
close reasons:

| Ledger close reason | Count | Benchmark can replay? | Note |
|---|---:|---|---|
| TRAIL_STOP | 7 | ✔ (with env trail from 2026-06-05) | Simulator matches sign; magnitude differs by 5–13 p |
| BE_STOP_POST_SCALEOUT | 2 | ✔ | Bench sim generates similar outcomes |
| SL_HIT | 1 | ✔ | 1 case; bench SCALE_OUT_BE'd (+5) where ledger SL_HIT (−20) — MFE-window mismatch |
| STRUCTURE_EXIT | 8 | ✘ | Requires structure_flip module not in benchmark |
| EXTERNAL_MANUAL | 8 | ✘ (non-replayable by definition) | Shared IG DEMO account |
| BRIEFING_TP1_CLOSE | 5 | ✘ | Env says `BRIEFING_TP_ENABLED=0`; ledger contradicts. Unresolved. |
| BRIEFING_TP_SL_OPEN | 1 | ✘ | Same as above |
| BE_HIT_IG | 2 | ✘ | Server-side broker BE; approximation of SCALE_OUT_BE |
| IG_RECONCILE | 2 | ✘ (non-replayable) | Post-hoc audit patch |

**Total replayable: 10 of 36. Non-replayable: 26 of 36.**

For the 9 that were matched AND replayable, the delta accounting:

- Ledger sum: **+112.65 p**
- Benchmark sum (env variant, blind): **+78.15 p**
- Delta: **−34.50 p across 9 deals** = **−3.83 p per deal average**

The magnitude gap on the TRAIL_STOP subset comes from an important
mechanical fact: the simulator uses the FULL 5-minute bar low as the
"post-scale MFE" for each bar. The live trader's trail moves in
response to ticks that may briefly touch a favourable extreme then
retrace within the same bar. The benchmark's bar-low overestimates
sustained MFE, so its trail arms and locks earlier than the live
trader's did, capturing 6–10 p vs the live 18–22 p. This is a genuine
resolution-of-data limitation, not a rule error.

For the 13 non-replayable matched deals: benchmark generated an
approximate exit (mostly TRAIL_STOP or SCALE_OUT_BE) totalling
−19.75 p vs a ledger of +105.55 p. Comparing these numbers is not
valid — the ledger closed those via briefing tier, structure_exit, or
operator/external actions the benchmark deliberately does not model.

For the 14 unmatched (FN) deals: ledger pips = +177.20 p. These are
signals the benchmark did not emit because either the env-history
detector filtered them (pierce depth < the reconstructed threshold at
that ts) or the slot gate blocked them (an upstream benchmark
prediction had the slot still occupied).

## Bench pnl vs ledger

Grand totals do **not** align:

- Ledger (36 fills): **+395.40 pips**
- Benchmark env-variant (22 matched fills, 4-exit sim + trail): **+58.40 pips**

The 337-pip gap breaks down as (approximately):

- 177 pips: 14 ledger fills the benchmark did not detect (FN)
- 125 pips: soft-exit gap on 13 matched-but-non-replayable ledger fills
- 34 pips: quantitative disagreement on the 9 matched-replayable
   fills (mostly trail exit timing)
- Remainder rounded away

## Bottom line — what remains open before DEMO forward

1. **UNRESOLVED false positives (45 in env variant).** Sources not yet
   tested: bar-contiguity guard, live restart gaps, concurrent-cap
   accounting on other strategies, and reconciling env-history to
   whatever configuration was actually loaded by the running trader
   each morning of Era B.
2. **26 of 36 close reasons are non-replayable** without importing
   the AutoBot tier machinery (BRIEFING_TP*), structure module
   (STRUCTURE_EXIT), or accepting external/operator closes as truly
   out-of-scope. The BRIEFING_TP* / TIER_SL_OPEN presence in the
   ledger while `.env` says `BRIEFING_TP_ENABLED=0` is a specific
   contradiction that neither source nor pinned .env resolves.
3. **Env-history is approximate.** 15 snapshots across 33 calendar
   days is under-sampled; the actual .env may have changed more
   often than captured. Getting Project Thirty an exact per-day
   .env would need either (a) the missing snapshots, or (b) running
   the trader in shadow mode with an audit log of every getenv() call.
4. **Trail exit magnitude off by 5–13 p on 7 replayable TRAIL_STOP
   deals.** This is a resolution artefact: 5m OHLC does not carry
   the tick-order needed to model the live tick-by-tick trail. Fix
   requires tick data; tick archive stops at 2026-04-10 (Era B
   entirely uncovered).
5. **Signal parity has no clean fixed-threshold answer.** Best fixed
   variant is 0.5 or 1.0 at 27/36. The env-history variant lags at
   22/36. Getting to 36/36 needs work on (1)–(3) above.

Given these five items, **the claim that the profitable strategy has
been reproduced is not supported by the evidence in this benchmark**.
The pierce + rejection *entry mechanism* is well-characterized and
reproduces most of the ledger's signal shape. The *admission gates
and exit engine* are not fully characterized from source + pinned
.env alone; the running trader had inputs and state we cannot
reconstruct here.

## Read-only guarantees

- `config.IG_SUBMISSION_ENABLED = False` — asserted at every run start
- No IG SDK imported anywhere in `era_b_bench/`
- `/opt/tradingbot/gbpusd_bb_bounce.py`, `trade_manager.py`,
  `trade_executor.py`, `autobot.py`, `.env` — all UNMODIFIED
- Running AutoBot process (PID confirmed at start) — UNMODIFIED
- No new services started; no orders placed
