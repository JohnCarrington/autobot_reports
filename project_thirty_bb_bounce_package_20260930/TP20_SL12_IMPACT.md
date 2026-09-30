# Fixed TP20 / SL12 — exit-behaviour impact on GBPUSD_BB_BOUNCE_S

**Requested by:** Project Thirty (via 2026-09-30 code-retrieval task)
**Baseline:** current HEAD (`3df0a50`) exit stack per
`INTEGRATION_NOTE.md` §3 and the 2026-09-29 implementation spec §3.
**Population:** 174 SELL fills on `host_161_bb_bounce_s_deal_reference_20260929.csv`.

## Framing

The requested rule is: on entry, place broker orders with
`limit_distance = 20` and `stop_distance = 12`. No BE amend, no
scale-out, no runner trail, no post-scale floor, no BRIEFING_TP tier
machinery, no STRUCTURE_EXIT, no REGIME_MAX_HOLD, no QM_BAND_CLOSE_
INSIDE, no EXIT_PROFILE_SQUEEZE, no BB_FLIP, no BB_RANGE_TARGET, no
AUTO_K_PREMISE. Pure broker-side TP-or-SL.

## Per-close-reason counterfactual

Canonicalised close-reason distribution over the 174-row deal
reference (spec §6.1). Column meanings:

- **N**    — count of realised fills that hit this close reason.
- **Realised** — sum of `effective_pnl_pips` for that bucket (spec §0).
- **Under fixed TP20/SL12** — what would replace this exit path.

| Close reason                       | N   | Realised (p) | Under fixed TP20 / SL12                                               |
|-----------------------------------|----:|--------------:|-----------------------------------------------------------------------|
| `EXTERNAL_MANUAL`                 | 16  | (varies)      | Still applies — DEMO account manual closes are exogenous              |
| `TRAIL_STOP`                      | 16  | (mostly +)    | GONE — no trail. Runner rides to +20 or -12                           |
| `BRIEFING_TP_SL_OPEN`             | 14  | (mostly −12→−20) | Replaced by broker SL at −12 (tighter than the observed −20 default) |
| `BRIEFING_TP1_CLOSE`              | 13  | (+, varied)    | Replaced by broker TP at +20 IF TP1 was ≥ +20; else GONE (many were −) |
| `SL_HIT`                          | 13  | −20 each      | Replaced by −12 (tighter stop)                                        |
| `BE_STOP_POST_SCALEOUT`           | 12  | ≈0 net        | GONE — no scale-out to install BE                                     |
| `FLOOR_STOP_POST_SCALEOUT`        | 12  | +5 lock       | GONE — no floor                                                       |
| `QM_BAND_CLOSE_INSIDE`            | 12  | (mixed)       | GONE — QM_ENABLED path inert                                          |
| `STRUCTURE_EXIT`                  | 10  | (mixed)       | GONE — runner rides to +20 or -12                                     |
| `BE_HIT_IG`                       | 9   | ≈0 net        | GONE — no BE amend                                                    |
| `AUTO_K_PREMISE`                  | 8   | (−, small)    | GONE — no autoK                                                       |
| `IG_RECONCILE`                    | 7   | (varied)      | Still applies — post-hoc reconciliation                               |
| `BB_FLIP`                         | 5   | (varied)      | GONE — no flip                                                        |
| `MANAGER_PROFIT_PROTECT`          | 4   | (+)           | GONE                                                                  |
| `BB_RANGE_TARGET`                 | 4   | (+)           | GONE — no range target                                                |
| `PRE_NEWS_CLOSE`                  | 3   | (varied)      | Still applies (autobot.py:4905 — separate seam)                       |
| `GBPUSD_BB_BOUNCE_S_TIER_SL_OPEN` | 3   | (−)           | Replaced by broker SL at −12                                          |
| `LABEL_K_OPERATOR`                | 3   | (varied)      | Still applies — manual Telegram K                                     |
| `NY_CLOSE`                        | 3   | (varied)      | Still applies (autobot.py:4786)                                       |
| `REGIME_MAX_HOLD`                 | 2   | (varied)      | GONE — 240m stop inert                                                |
| `EXIT_PROFILE_SQUEEZE`            | 2   | (−, cuts)     | GONE — runner rides to +20 or -12                                     |
| unreconciled + TP hit             | 3   | —             | 2 unreconciled remain; TP hit → replaced by fixed +20 TP              |

## Deltas that follow from removing the exit stack

### A. Broker TP truncates every winner above +20

Current `BROKER_TP_PIPS = 100.0` at
`gbpusd_bb_bounce.py:600` is a **sentinel**, not the working take-
profit. Big winners in the ledger come from tier machinery
(BRIEFING_TP2/TP3) or from the trail after scale-out. The
`total_pnl_pips` column populates only when scale-out fired, which
requires size ≥ 2.0 — see spec §3.2. Under fixed +20, every runner
above +20 loses its tail: the winner distribution is truncated at
+20 exactly.

Ballpark: of the 172 reconciled fills, 141 have `total_pnl_pips`
populated (scale-out fired). Runner tail contribution across those
141 is a large fraction of the +780 pips headline. Fixed +20 caps
each of those fills at ≤ +20 net (before considering scale-out is
also gone).

### B. Stop-outs get worse

Current `GBPUSD_BB_BOUNCE_SL_PIPS = 20` in .env (spec §5 says .env
went 12→20 at the era A→B boundary via commit `c85481c`). Fixed −12
tightens the stop by 8p per stop-out. Two competing effects:

- Fewer −20 SL hits become −12 SL hits — mechanical noise-stopouts
  from 12p were the exact reason for the 12→20 widening in commit
  `c85481c` (spec §5, Era B: "SL noise-stopouts largely
  eliminated"). Fixed −12 re-introduces them.
- No BE amend / no floor. Under the current stack, most `BE_HIT_IG`
  fills (9) and `BE_STOP_POST_SCALEOUT` fills (12) exit at ≈0 net
  after banking the +8..10p scale-out. Under fixed −12, each of
  those exits at somewhere between −12 and +20 with no partial
  bank.

### C. BRIEFING_TP tier machinery is inert

`BRIEFING_TP1_CLOSE` (13 rows) fires when TP1 (a briefing-level pip
distance from `select_tp_levels`) is reached with momentum fade
detected. TP1 is often below +20 on days with a near-price level
(e.g. PDH/PDL/round). Fixed +20 misses these earlier exits.

- If TP1 ≥ +20, the broker +20 TP fills first. The tier machinery
  would have progressed to TP2/TP3, capturing more.
- If TP1 < +20 AND momentum faded, the tier machinery banks at TP1
  (an earlier profitable exit); fixed +20 waits and either grabs
  the +20 or reverses to −12.

### D. QM_BAND_CLOSE_INSIDE / EXIT_PROFILE_SQUEEZE become inert

Both are early bar-close cuts. They're currently gated behind their
own env flags but 12 QM_BAND_CLOSE_INSIDE fills and 2
EXIT_PROFILE_SQUEEZE fills exist in the sample. Fixed +20/−12
removes them; those trades ride to broker TP/SL.

### E. STRUCTURE_EXIT becomes inert

The 10 STRUCTURE_EXIT fills exit on a 5m structure flip (HH vs prior
N bars). Without this cut, structure-flip losers ride to −12 (the
new SL) — worse than the observed structure-cut points which
frequently caught mid-move reversals before −20.

### F. REGIME_MAX_HOLD becomes inert

At fixed TP20/SL12 the broker exits so quickly the 240m time-stop
never fires. 2 rows in the sample were closed by it; those are
minor.

## Directional summary

**The current +780.85 pips over 172 SELL fills is NOT recoverable
under fixed TP20/SL12.** The dominant contributor to net P&L in the
current stack is the runner tail (via BRIEFING_TP2/TP3, TRAIL_STOP,
and BE_STOP paths) after a +8..10 scale-out. Removing the exit
stack:

- caps winners at +20 (many currently >+20 via the runner);
- tightens the stop to −12 (re-introduces noise stopouts that
  motivated the 2026-05-23 widening);
- disables the BE / floor / trail geometry that turned most
  scale-out fills into "worst case ≈0 net" outcomes.

Estimating a specific pip delta requires replaying every fill with
MFE/MAE telemetry (available in the deal-reference CSV columns
`mfe_pips`, `mae_pips`, `duration_minutes`); this note doesn't
compute the counterfactual number because the deal reference does
not record per-bar path and the accurate answer needs 5m candle
replay — see spec §7 for the reproduction protocol.

## What if only S (not L)?

Same story, since the exit machinery is symmetrical for the two
legs, with the sole L-vs-S asymmetry being the runner trail default
(`trade_manager.py:1725-1726`). Under fixed +20/−12, runner trails
are irrelevant, so L and S counterfactuals are identical modulo
direction. L's +222.9 net over 178 fills is likewise not recoverable
under fixed +20/−12.

*End of impact note.*
