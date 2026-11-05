# v1_pressure_against filter — investigation 2026-11-05

Operator directive: *"Investigate the 11:10 BUY rejected by
v1_pressure_against to determine whether that filter is unnecessarily
rejecting valid reversal opportunities. Do not weaken it based on one
retrospective winner."*

**Verdict: evidence is insufficient to recommend any change. The
3-week block sample is small (n=29 blocks; only 5 with recoverable
outcome records). Keep the filter as deployed.**

## Filter definition

`bb_bounce_filters.v1_pressure_signal()` computes the USD-vs-GBP
pressure signal from today's FX-day open bar (17:00 NY) vs the last
closed 5m bar:

- `usd_pct` ≈ change in EURUSD since FX-day open (inverted to give
  USD strength proxy).
- `gbp_pct` ≈ change in GBPUSD since FX-day open.
- Combined into an *expected GBPUSD direction*: BUY if GBP outpacing
  USD, SELL if USD outpacing GBP, FLAT otherwise.
- Signal states: `WITH` / `AGAINST` / `UNKNOWN`.

If the candidate's side disagrees with the expected direction the
filter returns `OUTCOME_REFUSED` with `refusing_rule=v1_pressure_against`.

Deployed flag: `BB_BOUNCE_V1_PRESSURE_ENABLED=1` (autobot .env:1052).
Closeback flag also on; dollar-direction filter is OFF.

## Live block record 2026-10-15 → 2026-11-05 16:00 UTC (3 weeks)

```
Total BB_BOUNCE_FILTER_BLOCK events — 29 (all rule=v1_pressure_against)
By side:                 SELL 23   BUY 6
By closeback context:    AFTER_CLOSEBACK 24   BEFORE_CLOSEBACK 5
By dollar-filter shadow: AGAINST 23   WITH 6   (perfect with v1)
```

Of the 5 BEFORE_CLOSEBACK rows, the closeback filter would have
blocked the entry independently — they add no information to the v1
signal's impact. The 24 AFTER_CLOSEBACK rows are the cases where v1
is the *sole* blocker.

## Outcome match (rejection resolutions where entry_price was computed)

Cross-reference against `bb_pierce_trades.jsonl`
RESOLUTION records sharing the inferred pierce bar
(`pierce_ts = floor_5m(block_ts) − 10 min`):

| block ts (UTC)     | side | v1 | dollar | closeback        | pierce_ts (UTC)       | entry   | MFE  | MAE  | pnl@TP20/SL20 |
|--------------------|------|----|--------|------------------|----------------------|---------|------|------|---------------|
| 2026-11-03 11:35:09| BUY  | AGAINST | WITH    | BEFORE_CLOSEBACK | 2026-11-03T11:25:00Z | 13407.15| 26.1 |  2.9 | **+20.0**     |
| 2026-11-04 04:40:10| SELL | AGAINST | AGAINST | AFTER_CLOSEBACK  | 2026-11-04T04:30:00Z | 13472.55| 24.6 | 12.9 | **+20.0**     |
| 2026-11-04 04:45:08| SELL | AGAINST | AGAINST | AFTER_CLOSEBACK  | 2026-11-04T04:35:00Z | 13466.25| 18.3 | 21.2 | **−20.0**     |
| 2026-11-04 12:35:21| SELL | AGAINST | AGAINST | AFTER_CLOSEBACK  | 2026-11-04T12:25:00Z | 13489.35| 29.25| 14.6 | **+20.0**     |
| 2026-11-05 11:20:07| BUY  | AGAINST | WITH    | BEFORE_CLOSEBACK | 2026-11-05T11:10:00Z | 13460.85| 22.95| 13.3 | **+20.0**     |

**5 matches: 4 wins, 1 loss, net +60 p (avg +12 p/trade).**

The remaining 24 blocks have no matched RESOLUTION record (archive
schema gap: the v1-blocker ran in `gbpusd_bb_bounce.py` but the
pierce resolver in `bb_pierce_recorder.py` uses a different detection
window, so some blocked pierces aren't recorded as resolved rejections
in the pierce log). This is a tooling limitation, not a claim about
those trades' outcomes.

## Baseline comparison

Same 3-week window, same TP20/SL20 definition:

| Universe | n | wins | losses | flat | net | avg/trade |
|---|---|---|---|---|---|---|
| v1-blocked (matched) | 5 | 4 | 1 | 0 | **+60.0 p** | **+12.0 p** |
| Live-fired BB_PIERCE_RUN | 15 | 5 | 6 | 4 | **−11.3 p** | **−0.8 p** |
| All resolved pierce-rejections | 398 | 223 | 175 | 0 | +780.8 p | +2.0 p |

Interpretation:
- The raw pierce universe (398 rejections) is modestly positive
  (+2 p/trade, 56 % win rate), consistent with the historical bounce
  edge.
- Live-fired is **negative** (−0.8 p/trade over 15 trades) — the
  currently deployed filter stack is *not* producing a better sample
  than random. (Note: the N=15 live sample is itself small; also
  heavily depressed by the `BLOCK_BAD_SIDE` defect that has been
  silently blocking fires since the `NMS_UNIFIED_DIRECTIONAL_AUTHORITY`
  flag was turned on sometime between 2026-10-27 19:20 and 22:00 UTC.)
- The matched v1-blocked sample looks positive (+12 p/trade) but
  **N=5 is far too small to overturn the filter design**. A single
  additional loser would change the sign.

## Why is the matched sample so sparse?

- `bb_bounce_filters.py` fires the block at the autobot's `evaluate()`
  seam in `gbpusd_bb_bounce.py:2333`. The arming logic there uses
  `pierce ≥ 0.5 p` with a 3-bar rejection window (per .env).
- `bb_pierce_recorder.py` writes RESOLUTION records with its own
  pierce/rejection definitions. The two pipelines don't share state.
- Any mismatch in either pierce threshold, body-ratio rule, or the
  rejection-window scan means a pierce that the autobot sees as
  armed-and-ready is simply absent from the pierce recorder log.

Enriching the cross-reference would require either (a) back-filling
the pierce recorder with the autobot's bb_bounce arming view, or
(b) adding a resolution tracker to the v1-block site. Both are
engineering tasks, out of scope for this investigation.

## Nov 5 block (the "11:10 BUY winner")

The live-evidence case the operator flagged:

- Pierce bar 2026-11-05T11:10:00Z: LOWER band, pierce_depth 1.94 p,
  BB width 12.55 p (squeeze), engine regime STRONG_TREND_DOWN but
  prior-floor hold was intact.
- Rejection bar 11:15: close 13460.85 back above BB_lower.
- Autobot armed BUY → `evaluate()` ran filter chain at 11:20:07 →
  `BB_BOUNCE_FILTER_BLOCK rule=v1_pressure_against closeback=
  BEFORE_CLOSEBACK v1=AGAINST dollar=WITH`.
- Pierce-recorder resolution: entry 13460.85, MFE +22.95 p, MAE 13.3 p,
  pnl@TP20/SL20 = +20 p.

Crucially, v1=AGAINST and dollar=WITH on this one — the two filters
**disagreed** (the shadow dollar-direction filter was *not* against
the BUY). On 23/29 blocks the two agreed (dollar=AGAINST). This is the
only specific lever I can see that *might* refine v1 — require both
signals to agree before refusing — but that lever would need its own
cross-validated audit against a much larger sample.

## Recommendation

**Do nothing. The defect fix deployed today (BLOCK_BAD_SIDE
normalisation) is the single intervention with clear evidence of
harm. The v1_pressure filter's selectivity is unproven but the sample
is too small to overturn.**

Follow-up telemetry to accumulate (no code change needed):
1. The `bb_bounce_decisions.jsonl` log is defined in `bb_bounce_filters.
   py` but writes only when `BB_BOUNCE_DECISION_LOG_ENABLED=1`
   (currently off). Turning it on would record every v1 verdict with
   context — the data needed for a proper audit. Operator decision.
2. Over the next 4–6 weeks of post-`BLOCK_BAD_SIDE`-fix operation,
   collect ≥ 50 v1-blocked matched outcomes before reconsidering.
3. If the "require v1 AND dollar to agree" refinement is considered,
   it should enter `BB_BOUNCE_DOLLAR_DIRECTION_ENABLED` shadow mode
   first (already-defined flag, currently 0) so its agreement rate
   can be measured against v1.

**No filter code change proposed. No .env change proposed.**
