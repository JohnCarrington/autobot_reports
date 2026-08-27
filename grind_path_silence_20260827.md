# Grind-path silence investigation — 2026-08-27

Host 161. Investigation started 05:15Z after operator chart-read of a live
overnight grind (GBPUSD 02:00–06:30Z on 2026-08-27) that fired nothing and
logged nothing.

## Contradictions first

- **Operator claim: "trend_subtype=GRIND direction=DOWN at 05:15Z stamped on
  the BB_BOUNCE_L fire row."** — NOT SUPPORTED. The only 2026-08-27 fire
  before the report was `deal_id=DIAAAAYCRQXTMA4` at `timestamp_open
  2026-08-27T04:05:02Z` (`GBPUSD_BB_BOUNCE_L`). Its signal_log row stamps
  `trend_subtype: null`, `grind_direction: null`, `trend_subtype_bar_ratio:
  0.3803`, `trend_subtype_efficiency: 0.0949`. There is no 05:15Z fire.

- **Operator claim: journalctl 02:00Z+ grep for
  `grind|UM_S x block|warmup|consol|cooldown|reason` returns EMPTY.**
  CONFIRMED. That's the real defect. It is not that the grind path was
  wrongly gated — it is that its verdict never reached the operator's field
  of view.

## Centrepiece: 05:15Z stamp vs day-scale warmup

`regime_engine.jsonl` last row for GBPUSD at 05:15Z, verbatim:

```
timestamp                = 2026-08-27T05:15:01.102308+00:00
symbol                   = GBPUSD
winning_regime           = TREND_FORMING_DOWN
regime_label_path        = hist
trend_subtype            = None
trend_subtype_bar_ratio  = 0.3964
trend_subtype_reason     = day_context_warmup
grind_direction          = None
session_bars_elapsed     = 0
day_median_bar_ratio     = None
```

The engine classifier IS running every 5m; it correctly returns
`trend_subtype=None reason=day_context_warmup` because
`session_bars_elapsed < GRIND_DAY_MIN_BARS (24)`. The 07:00Z anchor makes
`session_bars_elapsed=0` at every UTC hour before 07:00. This ONLY lives
inside `logs/regime_engine.jsonl` — no journal emit.

The operator observed `trend_subtype=null` on the 04:05Z fire row (see §1
below), which the schema surfaces as `trend_subtype: null` with
`trend_subtype_bar_ratio: 0.3803` populated. The `bar_ratio` is populated
BEFORE the warmup early-return at regime_engine.py:1268, which is why the
row carries a number in that slot despite subtype being null. The operator's
"GRIND/DOWN at 05:15Z" reading does not match any row in signal_log,
regime_engine.jsonl, trend_v3.jsonl, or systemd journal — most likely a
misread of the `engine_regime_at_fire=TREND_FORMING_DOWN
engine_regime_bias_at_fire=SHORT` fields as GRIND/DOWN.

Resolution — no classifier/router wiring bug. Warmup gate is working
as ruled.

## Per-bar evidence table (regime_engine.jsonl, GBPUSD)

| Bar UTC | winning_regime | subtype | reason | session_bars | day_med | grind_dir |
|---|---|---|---|---|---|---|
| 03:00:00 | RANGE_ROTATION      | null | day_context_warmup | 0 | null | null |
| 04:30:00 | TREND_FORMING_DOWN  | null | day_context_warmup | 0 | null | null |
| 05:15:00 | TREND_FORMING_DOWN  | null | day_context_warmup | 0 | null | null |
| 05:25:00 | TREND_FORMING_DOWN  | null | day_context_warmup | 0 | null | null |

Fixed pattern across the window: `session_bars_elapsed=0`,
`day_median_bar_ratio=null`, `subtype_reason=day_context_warmup`. The
day-scale check at `regime_engine.py:1261` returns before the one-sided EMA
computation, so `grind_direction` never gets stamped. All consistent with
the 07:00Z-anchored warmup rule.

## §1 — Was the grind path evaluated overnight?

**No, not the classifier's grind decision branch, and not the TV3 grind
evaluator either. Two silent gates operate in sequence:**

1. **TV3 session gate** (`gbpusd_trend_v3.py:1198`, `TREND_V3_SESSION_GATE_ENABLED=1`,
   `TREND_V3_SESSION_START_UTC=07:00`, `TREND_V3_SESSION_END_UTC=16:00`).
   Every 5m bar between ~00:00Z and 07:00Z hits `[TV3_SESSION] suppressed
   entry at <ts>` and returns. **43 hits** in `journalctl 02:00–06:30Z`,
   e.g.:
   ```
   Aug 27 02:00:01 [INFO] [TV3_SESSION] suppressed entry at 2026-08-27T02:00:00Z
   Aug 27 02:05:01 [INFO] [TV3_SESSION] suppressed entry at 2026-08-27T02:05:00Z
   ...
   ```
   These lines exist in the journal but do not carry the strings
   `grind`, `warmup`, `consol`, or `cooldown` — hence the operator's grep
   pattern missed them.

2. **Regime engine day-scale warmup** (`regime_engine.py:1261-1268`,
   `GRIND_DAY_MIN_BARS=24`, `GRIND_DAY_SESSION_ANCHOR_UTC=07:00`).
   Even if the session gate were off, every classify pre-07:00Z sees
   `session_bars_elapsed=0` and returns `trend_subtype=None
   subtype_reason=day_context_warmup`. This ONLY lives in
   `logs/regime_engine.jsonl` — zero journal hits.

Furthest point reached on any 5m bar in 02:00–06:30Z: `_in_session=False`
short-circuit at `gbpusd_trend_v3.py:1203`. The classifier itself does run
(evidence: `regime_engine.jsonl` rows above), but TV3's `evaluate()` never
gets past its session gate to consult `trend_subtype`.

## §2 — Warmup hypothesis: contradiction resolved

Hypothesis: "05:15Z fire row stamps GRIND/DOWN, therefore either
(a) warmup gates the router but not the classifier, (b) session-anchor
arithmetic is wrong overnight, or (c) day-scale is unwired on some label
class."

Resolution: no fire row stamps GRIND. The one 08-27 fire (04:05:02Z)
stamps `trend_subtype: null grind_direction: null`. The
regime_engine.jsonl bar row at 05:15Z also stamps `null` +
`reason=day_context_warmup`. There is no contradiction; the operator
misread a field.

Arithmetic check on the anchor:
- `_GRIND_DAY_SESSION_ANCHOR = 07:00` (parsed from `GRIND_DAY_SESSION_ANCHOR_UTC` env).
- Mask at `regime_engine.py:1246-1249`:
  `(_dates == _last_date) & (_times >= _GRIND_DAY_SESSION_ANCHOR)`.
- At `_last_ts = 2026-08-27T05:15Z`, `_last_date = 2026-08-27`, all
  buffer bars on 08-27 have time `< 07:00`, so `_session_mask` is all-False
  → `_sess_bars = 0`. Consistent with the row stamp.

No arithmetic bug; the semantics are: "only bars on `_last_date` after
`07:00` count." That excludes both prior-day tail AND same-day pre-anchor
bars. Overnight grinds are structurally invisible to the classifier until
`07:00 + 24×5m = 09:00Z`.

Wiring check: The same `_sess_bars < GRIND_DAY_MIN_BARS` gate runs BEFORE
the trending-vs-non-trending split at `regime_engine.py:1304-1322`, so
both label classes are equally warmup-gated (no (c) inconsistency).

## §3 — Trigger hypothesis: did consolidation-break ever arm?

**Trigger was never reached — the session gate short-circuited TV3
before evaluate()'s consolidation-break site.**

Confirmed by two independent sinks:
- `logs/trend_v3.jsonl` last row `2026-08-26T19:50:00+00:00` (block
  `grind_consol_not_broken_dn`). File last modified `2026-08-26
  19:55:01Z`. Zero rows for 08-27.
- Journal: last `[TREND_V3] GRIND spine deferral` line at `Aug 26
  19:55:01Z`. Silence until `Aug 27 04:05:02` when only `[EXIT_DRESS]
  boot maps` mentions `_TREND_V3_*` mode names (that's the boot map
  emitter, not TV3 evaluate).

The consolidation-break trigger at `gbpusd_trend_v3.py:1503-1541`
requires (a) `_grind_widening_active = (trend_subtype == "GRIND")` at
line 1285 AND (b) `bars[-1].close` breaks max-of-last-N-highs (LONG) or
min-of-last-N-lows (SHORT). During a monotone drift with no pause,
condition (a) requires GRIND classification (which needs
`session_bars_elapsed >= 24`), and condition (b) requires the current
bar's close to poke past the prior N=4 highs/lows. A monotone drift by
definition satisfies (b) at every step — so a fully-monotone grind
would arm the trigger every 5m from the first eligible bar, gated then
by the 6-bar `GRIND_REENTRY_COOLDOWN_BARS` (5m each) between fires.
The 2026-08-11 replay's 16 consolidation blocks were the OPPOSITE tape
— compressed range, not monotone drift; the ledger sensor at line 1516
`current_close <= _consol_high` rejects any close inside the range and
requires the CURRENT close to poke past prior extremes.

## §4 — Silence defect: every early-return that exits without a journal reason

`_compute_trend_subtype` — 11 early returns, of which only 4 emit a
throttled WARN (baseline_missing / baseline_stale / baseline_no_symbol /
baseline_null_scalar). The other 7 (`insufficient_history` ×3,
`zero_volatility`, `eff_compute_failed`, `ratio_compute_failed`,
`day_context_warmup`, `day_ratio_too_high`, `non_trending_no_grind`)
are visible ONLY on the `regime_engine.jsonl` row. `_log_subtype_transition_if_any`
at line 1345 dedups on unchanged state, so a stable `None` state emits
zero journal lines.

TV3 `_log_block` — 15 call sites (lines 1252–1586), each writes ONLY
to `logs/trend_v3.jsonl` via `_write_jsonl`. `logger` is not called.
Included grind-tagged reasons: `grind_reentry_cooldown`,
`grind_consol_not_broken_up/dn`, `grind_consol_insufficient_history`,
plus `regime_not_strong_up/down` when the grind widening path is active.

## Fixes shipped

**A. Suppression logging — unconditional (commit `33d0162`)**

`regime_engine._log_grind_path_verdict_per_bar` emits one INFO
`[GRIND-PATH]` line per (symbol, bar_ts) at the end of every
`classify_regime` call. Carries: `verdict` (warmup / grind / impulse /
blocked), `subtype_reason`, `session_bars_elapsed`,
`day_median_bar_ratio`, `grind_direction`, `one_sided_ema72`,
`bar_size_ratio` — all scalars the operator would need to grep. Per-bar
dedup (per symbol) so a re-classify on the same bar doesn't double-log.

`gbpusd_trend_v3._log_block` additionally mirrors:
- reasons starting with `grind_` (5 sites)
- `regime_not_strong_up/down` when `grind_widening=True` kwarg present
  (2 sites)
to `logger.info` under `[GRIND-PATH] TREND_V3 block ...`. Non-grind
reasons stay JSONL-only (no firehose).

**B. Proven-cause fix — REPORTED AS WORKING-AS-RULED**

The 07:00Z-anchored 24-bar warmup and the TV3 07:00-16:00 session gate
are both by design; combined they structurally exclude overnight grinds
from the UM-grind entry path.

- **Trade-off:** Grind tapes that build overnight (Asia-EU handover on
  GBP pairs is a recurring case) are unreachable until ~09:00Z (07:00
  session + 2h warmup) even when the tape is objectively grind. By
  09:00Z the grind may have run to completion or reversed on London
  open.
- **Candidate alternatives for the operator to rule on:**
  1. **Rolling 24-bar window instead of session-anchored:** classify
     GRIND from the 24-bar median of the trailing 5m ratios regardless
     of the anchor. Retains the day-scale rejection of chop days but
     doesn't reset at 07:00Z. Cheapest change; loses the
     "session-context" framing.
  2. **Separate overnight anchor:** e.g. anchor at 21:00Z (previous
     day's NY close) with a distinct `OVERNIGHT_GRIND_DAY_MIN_BARS` so
     the classifier can label GRIND from ~23:00Z onward. Preserves the
     session semantics but adds a config surface (two anchors, two
     min-bars).
  3. **Widen TV3 session to 24×5 = full-day**: separate from the
     classifier warmup, this alone would make session_gate no-op
     overnight. Would still leave the classifier warmup in place, so no
     GRIND labels overnight — the grind entry variant would still be
     unreachable. Minimally useful unless combined with (1) or (2).

Design decision required from operator. No code change lands under B in
this commit.

**C. Tests — 6 added (`tests/unit/test_grind_path_suppression_logging.py`)**

1. `test_warmup_return_emits_grind_path_info_line` — synthetic 130-bar
   buffer entirely before 07:00Z → `subtype_reason=day_context_warmup`
   → `[GRIND-PATH]` INFO line stamped `verdict=warmup reason=day_context_warmup
   session_bars=0`.
2. `test_grind_path_verdict_deduped_per_bar` — two calls with the same
   (symbol, ts) emit exactly one line.
3. `test_grind_path_verdict_grind_stamps_verdict_grind` — real GRIND
   record stamps `verdict=grind grind_dir=DOWN session_bars=30`.
4. `test_tv3_log_block_mirrors_grind_reason_to_journal` — `_log_block(
   reason="grind_consol_not_broken_dn", ...)` emits `[GRIND-PATH] TREND_V3 block
   reason=grind_consol_not_broken_dn ...`.
5. `test_tv3_log_block_mirrors_grind_regime_block` —
   `regime_not_strong_down` with `grind_widening=True` mirrors to
   journal; without the flag, it stays JSONL-only.
6. `test_tv3_log_block_non_grind_reason_stays_jsonl_only` — negative
   test: `reentry_cooldown` does NOT emit a `[GRIND-PATH]` line (fix
   is scoped, not a firehose).

## Suite delta

Passing after change: 79 (6 new + 73 existing grind/regime tests).
Failing after change: 4 (pre-existing in `tests/unit/test_trend_subtype.py`
— confirmed unrelated by `git stash` before-vs-after; my changes did
not cause them).

## Diffs (summary)

```
gbpusd_trend_v3.py   | +37 -0
regime_engine.py     | +43 -0
tests/unit/test_grind_path_suppression_logging.py | +190 (new)
.gitignore           | +1 (allowlist)
```

Commit `33d0162` on `feat/trend-stretch-brake-adx-floor`. Local only.

## Restart note

No push. Activates on operator's next `safe_restart.sh` at their chosen
boundary. First post-restart bar close will emit
`[GRIND-PATH] symbol=GBPUSD ts=<...> regime=<...> verdict=<...>`
regardless of subtype state — verifiable with:

```
journalctl -u autobot.service --utc --since '<restart_ts>' | \
    grep '\[GRIND-PATH\]' | head
```

If verdict=warmup persists past 09:00Z UTC, the day-scale computation
is bug-out — a separate issue distinct from this visibility fix.

END
