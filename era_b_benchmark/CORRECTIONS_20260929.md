# Era B benchmark — corrections (2026-09-29 late)

Two focused corrections to the earlier reports in this directory
(`UNRESOLVED_DIFFERENCES.md`, the prior chat summaries).

## 1. Raw-vs-gated identity bug — FIXED

`run_multi_variant.py:383-385` used `id(sig)` to skip matched signals
when classifying false positives. The gated and raw runs create
separate `Signal` instances so `id()` never matched — every matched
signal appeared a second time in the FP list under `UNRESOLVED`.

Fix (2026-09-29): compare `(rejection_bar.ts, direction)` tuples, the
same key `match_ledger()` uses.

### Corrected entry-parity counts (36 Era B ledger fills)

| Variant | Raw fires | After gates | Matched | FP total | FN | UNRESOLVED-FP (was) |
|---|---:|---:|---:|---:|---:|---:|
| Fixed 0.5 p | 101 | 61 | 27 | 34 | 9 | 22 (was 38) |
| Fixed 1.0 p | 80 | 55 | 27 | 28 | 9 | 22 (was 44) |
| Fixed 2.0 p | 42 | 33 | 14 | 19 | 22 | 19 (was 33) |
| Env-history | 63 | 45 | 22 | 23 | 14 | **23 (was 45)** |

The env variant is the one most affected — its "45 UNRESOLVED FP"
number in `UNRESOLVED_DIFFERENCES.md` overstated the gap by 22 fires
that were actually matched. Corrected count is **23 UNRESOLVED FP**.

### Timestamped examples (from `outputs_multi/`)

**Matched** (env variant, 3 of 22 — all `matched=True` in
`exit_parity_blind.csv`):
- `DIAAAAXMXBJG3A7` 2026-06-01 ledger close = BE_HIT_IG, pnl +10.15 p
- `DIAAAAXMZ9XBEAZ` 2026-06-01 ledger close = STRUCTURE_EXIT, pnl -14.80 p
- `DIAAAAXNM9YTXA9` 2026-06-03 ledger close = BRIEFING_TP1_CLOSE, pnl +35.20 p

**Genuine extra signals** (UNRESOLVED FP, 3 of 23 in env variant,
same in every fixed variant — pierce depth well above every tested
threshold):
- 2026-05-27T12:40Z rejection bar, entry 13449.25, pierce depth 8.36 p
- 2026-05-28T16:35Z rejection bar, entry 13441.25, pierce depth 5.16 p
- 2026-06-02T12:00Z rejection bar, entry 13471.75, pierce depth 2.21 p

**Missed fills** (env FN, 3 of 14 — all present in
`logs/confirmation_engine.jsonl-20260917` as live-trader fires):
- `DIAAAAXMRHKJ8AY` 2026-05-29 07:05:04Z entry 13436.65, pierce depth
  1.46 p — filtered by env-variant because history says pierce_thresh
  was 2.0 p at that ts (evidence inconsistent with the fire)
- `DIAAAAXMR2E6ZA2` 2026-05-29 11:15:03Z entry 13416.45, pierce depth
  1.18 p — same reason
- `DIAAAAXMSRVJBAM` 2026-05-29 15:20:01Z entry 13478.25, pierce depth
  13.04 p — passed pierce; unclear why FN, further investigation
  outside this correction's scope

### Remaining mismatch (unchanged by the bug fix)

- **Match rate: 22/36 (env) / 27/36 (fixed 0.5 or 1.0) / 14/36 (fixed 2.0)**.
  No single pierce threshold reproduces all 36. Consistent with the
  earlier finding that the running trader's config differs from
  every pinned .env snapshot.
- **23 genuine extra signals** in the env variant — pierce+rejection
  bars that produced clean setups but were not fired by the live
  trader for reasons the pinned source + .env do not explain.
- **9 missed fills** in the fixed-0.5 or fixed-1.0 variants — same
  bars the live trader fired; my benchmark's slot gate (based on
  benchmark's own predicted exit times) blocks them.

## 2. P&L labels — corrected classification

The earlier reports classified the 8 `EXTERNAL_MANUAL` closes as
"human discretionary operator closes". **This was overreach.** The
ledger column records only that the close was not initiated by host
161's process — it does not identify the actor.

Corrected classification:

| close_reason | Actor | Note |
|---|---|---|
| EXTERNAL_MANUAL (8) | **Unknown** | Detected as a mismatch between host 161's EPIC_STATE and the IG broker's open positions. Could be an operator, another host on the shared IG DEMO account, an IG server-side action, or another process. |
| IG_RECONCILE (2) | Broker / post-hoc audit | Reconstructed via `/history/transactions` daily reconciliation |
| SL_HIT / TP_HIT / BE_HIT_IG / BE_STOP_POST_SCALEOUT | AutoBot exit engine + broker | Reproducible from OHLC |
| TRAIL_STOP / BRIEFING_TP*_CLOSE / STRUCTURE_EXIT | AutoBot exit engine | Not reproducible from OHLC alone (tick-driven or live-input-driven) |

The earlier "40.7 % was human discretionary" framing is withdrawn.
Correctly stated: **8 of 36 closes (+161.10 p) came from an actor
outside host 161's process. The identity of that actor is not
established by the pinned artifacts.**

### Do not present +395.4 p as a reproducible strategy result

Given (a) 40.7 % of the P&L is closed by an unknown actor, (b) the
BRIEFING_TP tier machinery produced 32.7 % of the P&L despite the
pinned .env flagging its enable-var as DEAD, and (c) the running
trader's config diverges from every pinned .env — **the +395.40 p
figure is not a reproducible strategy result**. It is the observed
outcome of an interaction between the AutoBot code, its unknown
runtime configuration, and one or more external closing actors, on
one specific 33-day window.

For any downstream comparison (Project Thirty, DEMO forward,
sensitivity study), the reproducible claim is limited to:

- The entry mechanism (2-bar pierce ≥ ~0.5 p + rejection close), which
  matches 27/36 of the ledger's rejection-bar timestamps at fixed
  0.5 p threshold.

All other claims should await better evidence about the running
config and the closing actors.

## 3. Observation-only detector for Project Thirty

The pierce → rejection-close entry mechanism is well-characterized
enough to ship as an **observation-only** candidate. See
[`observer/`](observer/README.md). No broker submission, no state
change on host 161, no host 161 deployment. Ready for Project Thirty
to pull and run.
