# STRONG TREND state-machine calibration — 2026-10-13

**Branch:** `feat/nms-data-continuity-stages1-3-20261012` (worktree
`/home/autobot/tradingbot-wt/nms-continuity-20261012`), commits
`86f15d5` (Phase 8-complete baseline) and `403922e` (this change).

**Status:** DEVELOPMENT. Not deployed. BB-Bounce dev-side guard
patched on worktree `/home/autobot/bb-bounce-wt/session-trend-20261013`
branch `feat/nms-session-trend-guard-20261013` — ONLY the dev tree,
no production reconfigured, no services restarted.

---

## 1. Spec

The operator-approved STRONG TREND definition:

> A STRONG TREND requires:
>
> 1. Sustained directional price structure (HH/HL or LH/LL).
> 2. Meaningful progression away from the session open.
> 3. Persistence — pullbacks followed by continuation.
> 4. No repeated full-range reversals.
> 5. Recognition DURING the session, not retrospectively.
>
> A large daily range or 20-pip displacement alone does NOT
> establish a strong trend.

**Day types + permissions:**

| Day type | BUY permitted | SELL permitted |
|---|---|---|
| STRONG_TREND_DOWN | **blocked** | yes |
| STRONG_TREND_UP | yes | **blocked** |
| RANGE | yes | yes |
| NORMAL | yes | yes |

**Hard rules (preserved):**

* Direction preserved through consolidation / M5 noise.
* Release only on structural reversal (full-range reclaim across
  the London open), not on short pullbacks.
* BB-Bounce entry logic, stops, and targets unchanged.
* No deployment, no service restart, no IG orders.

---

## 2. Mapping — spec criteria → measurable features

| # | Criterion | Feature | Threshold constant |
|---|---|---|---|
| 1 | Sustained structure | `structure_run_down` / `_up` from confirmed fractal swings (N=2 point-in-time safe) | `MIN_STRUCTURE_RUN` = 2 |
| 2 | Meaningful progression | `displacement_pips` from London open | `STRONG_DISPLACEMENT_PIPS` = 20 |
| 3 | Persistence | `pullback_continues_*` counter (retrace ≥ 5p above/below reference extreme, then new extreme) | `MIN_PULLBACK_CONTINUES` = 1 |
| 4 | No full-range reversals | `range_reversals` = count of ≥ 15p H↔L alternations in confirmed-swing sequence | `MAX_RANGE_REVERSALS` = 1 |
| 5 | Recognition during session | `candidate_*_bars` persistence counter; all four criteria 1-4 must hold for N consecutive 5m bars | `STRONG_PERSISTENCE_BARS` = 2 (10 min) |

Plus a close-position gate: `CLOSE_POS_DOWN_CEILING` = 0.35 /
`CLOSE_POS_UP_FLOOR` = 0.65 (close in the trending third of the
session range).

**Release path:** DOWN → UNKNOWN when `displacement ≥
RELEASE_RECLAIM_PIPS` (= 10) for `RELEASE_PERSISTENCE_BARS` (= 2)
consecutive bars. UP mirror. Release does **not** auto-establish
the opposite direction; a fresh 5-criterion match is required for
that.

Pre-London bars (bar_ts < London open ts) **do not advance** the
state machine. Fixes the 02:20 UTC overnight-move false positive.

---

## 3. Historical data analysis (34 days, Sep-Oct 2026)

Thresholds derived from empirical feature distributions over
2026-09-01 … 2026-10-13. For each day a "day truth" is computed
*independently* from the archive:

* `UP` — close ≥ open + 20p AND (close − low) ≥ 0.6 × range
* `DOWN` — mirror
* `RANGE` — |close − open| < 20p AND range ≤ 60p
* `NORMAL` — anything else

End-of-day feature extracts (minima for trend days, maxima for
range/normal):

| Metric | DOWN min | UP min | RANGE max | NORMAL max |
|---|---|---|---|---|
| \|displacement\| at EOD | 24.8p | 32.1p | 18.9p | 19.8p |
| `structure_run_<dir>` | 4 | 6 | n/a | n/a |
| `pullback_continues_<dir>` | 2 | 2 | n/a | n/a |
| `range_reversals` | 2 (median 1) | 2 | 3 (median 1) | 3 |
| `close_pos` | 0.33 (max) | 0.69 (min) | n/a | n/a |

The 20p displacement + 0.35/0.65 close_pos thresholds sit just
below the DOWN/UP distribution minimums. `MAX_RANGE_REVERSALS=1`
is below the DOWN maximum (2) — a documented over-strictness. See
§6.

---

## 4. 34-day replay — current calibration (STRONG_DISPLACEMENT_PIPS=20)

Independent "day truth" vs. end-of-day `session_trend.prevailing`:

| date | truth | final | first establish |
|---|---|---|---|
| 2026-09-01 | DOWN | DOWN | 16:50 |
| 2026-09-02 | DOWN | RANGE | — |
| 2026-09-03 | UP | RANGE | — |
| 2026-09-04 | NORMAL | DOWN | 12:35 |
| 2026-09-06 | RANGE | UNKNOWN | — |
| 2026-09-07 | UP | UP | 16:50 |
| 2026-09-08 | RANGE | RANGE | — |
| 2026-09-09 | RANGE | DOWN | 09:55 |
| 2026-09-10 | DOWN | DOWN | 11:10 |
| 2026-09-11 | RANGE | DOWN | 09:05 |
| 2026-09-13 | RANGE | UNKNOWN | — |
| 2026-09-14 | NORMAL | RANGE | — |
| 2026-09-15 | DOWN | **UP** | 13:50 (flip) |
| 2026-09-16 | DOWN | DOWN | 11:50 |
| 2026-09-17 | DOWN | RANGE | — |
| 2026-09-18 | UP | RANGE | 11:40 (fired DOWN then released) |
| 2026-09-21 | RANGE | RANGE | — |
| 2026-09-22 | DOWN | RANGE | — |
| 2026-09-23 | DOWN | RANGE | — |
| 2026-09-24 | DOWN | RANGE | — |
| 2026-09-25 | UP | UP | 10:10 |
| 2026-09-27 | RANGE | RANGE | — |
| 2026-09-28 | NORMAL | UP | 09:20 |
| 2026-09-29 | NORMAL | RANGE | — |
| 2026-09-30 | NORMAL | UP | 09:50 |
| 2026-10-01 | DOWN | RANGE | — |
| 2026-10-02 | UP | RANGE | — |
| 2026-10-04 | RANGE | UNKNOWN | — |
| 2026-10-05 | NORMAL | RANGE | — |
| 2026-10-06 | UP | UP | 08:40 |
| 2026-10-07 | DOWN | RANGE | — |
| 2026-10-08 | NORMAL | RANGE | — |
| 2026-10-09 | RANGE | DOWN | 12:35 |
| 2026-10-12 | DOWN | DOWN | **14:20** |

**Confusion matrix:**

| truth \\ final | DOWN | RANGE | UNKNOWN | UP |
|---|---|---|---|---|
| DOWN | 4 | 7 | 0 | 1 |
| NORMAL | 1 | 4 | 0 | 2 |
| RANGE | 3 | 3 | 3 | 0 |
| UP | 0 | 3 | 0 | 3 |

**Scorecard:**

* Correct trend classifications: **7** (4 DOWN + 3 UP)
* Direction flips (truth vs. final opposite): **1** (2026-09-15)
* False-trend classifications (truth RANGE/NORMAL, final UP/DOWN): **6**
  * 2026-09-04 NORMAL → DOWN
  * 2026-09-09 RANGE → DOWN
  * 2026-09-11 RANGE → DOWN
  * 2026-09-28 NORMAL → UP
  * 2026-09-30 NORMAL → UP
  * 2026-10-09 RANGE → DOWN
* Missed trend days: **10** (truth UP/DOWN but final not UP/DOWN)

---

## 5. 2026-10-12 pinned regression

The archive-driven regression test
(`tests/data_continuity/test_phase8_oct12_regression.py`) replays
the actual 2026-10-12 GBPUSD day in chronological order and
captures the guard's decision at each pinned trade entry.

**Current calibration (STRONG_DISPLACEMENT_PIPS=20):**

* London open: 07:00 UTC @ 13246.15.
* First DOWN establishment: **14:20 UTC** (disp −21.4p,
  struct_run=4, pullback_continues=4, reversals=0, close_pos=0.10,
  persistence_bars=2).

| Entry time | Side | Decision | Previously (09:55 pin) |
|---|---|---|---|
| 08:10:11 | SELL | allow | allow |
| 09:35:12 | BUY | allow | allow |
| 10:20:18 | BUY | **allow** | block |
| 11:18:06 | BUY | **allow** | block |
| 12:20:14 | SELL | allow | allow |
| 14:10:14 | BUY | **allow** | block |
| 15:25:22 | SELL | allow | allow |
| 16:10:24 | BUY | block | block |

**This is a documented regression in Oct-12-specific protection:**
1 of 4 historical losing BUYs blocked (was 4 of 4). The regression
is a direct consequence of adhering to the operator spec's criterion
2 ("meaningful progression") at 20 pips — the 09:55 bar had only
−15.3p displacement.

See §6 for the 15p alternative calibration which recovers 11:18
and 14:10 but introduces 3 additional false positives elsewhere.

---

## 6. Sensitivity — STRONG_DISPLACEMENT_PIPS 20 vs. 15

| Threshold | TP | FP | Missed | Flips | Oct 12 first DOWN | Oct 12 BUYs blocked |
|---|---|---|---|---|---|---|
| **20p (current default)** | 7 | 6 | 10 | 1 | 14:20 | 1 of 4 |
| 15p (alternative) | 7 | 9 | 10 | 1 | 11:05 | 3 of 4 |

The 15p alternative recovers substantial Oct-12 protection but:

* Adds 3 false-positive days (2026-09-08 RANGE→UP, 2026-09-04
  NORMAL→DOWN earlier, 2026-10-08 NORMAL→UP) — these days would
  have one trade direction wrongly blocked.
* Preserves the one direction flip (2026-09-15 DOWN truth → ST UP)
  as a worst-case error.

**Operator decision point:** which failure mode is more expensive?

* Letting counter-trend BUYs through on a real DOWN day → the Oct-12
  BB-Bounce loss recurs.
* Blocking the aligned direction on a RANGE/NORMAL day → missed
  trade on that day only; the aligned direction still trades.

Setting via `.env`:
```
SESSION_TREND_STRONG_DISP_PIPS=15   # or omit for default 20
```
No code change required.

---

## 7. Direction flip — 2026-09-15 analysis

The single direction flip:

* Truth: DOWN (close well below open, large body in bottom third).
* ST final: UP, established 13:50 UTC with
  `strong_up:disp=+26.1p|struct_run=3|pullback_continues=5|reversals=0|close_pos=0.86`.

The session had a strong UP leg early-afternoon that satisfied all
5 criteria. The subsequent reversal to a DOWN close did not trigger
the UP release because `displacement` never reclaimed `−10p` for
2 consecutive bars (reclaim is measured from the London open, not
from the UP establishment peak).

**Possible refinement (not applied):** add a drawdown-from-peak
release — "UP released when close drops ≥ 20p from
`max(close) since prevailing_since_ts`". Would require operator
sign-off and a full re-run; not in scope of this calibration pass.

---

## 8. Wiring + files touched

**Changed (AutoBot worktree, feat branch):**

* `session_trend.py` — 5-criterion state machine (initializer:
  module-level singletons; driver: `on_bar_close()`; consumer:
  `session_authority()` + atomic snapshot write).
* `tests/data_continuity/test_phase8_oct12_regression.py` — pinned
  decisions updated to match 14:20 UTC first-DOWN establishment.
* `tests/data_continuity/test_phase8_session_trend.py` —
  state-machine-specific tests rewritten; establishment semantics
  are now covered end-to-end by the archive-driven tests.

**Unchanged / not touched:**

* `session_trend_guard.py` — snapshot shape backward-compatible.
* `session_ig_daily_pct.py` — IG daily-% bridge unchanged.
* BB-Bounce `open_sb_now.py` on the dev worktree — guard call site
  intact; guard reads the new snapshot without modification.

**Test status (data_continuity suite):** 93 pass, 0 fail.
Bounce_engine failures in `test_integration_remediation.py` are
pre-existing (last modified at `d9f107e`, upstream of this branch)
and unrelated to session_trend.

---

## 9. Deployment notes (operator action)

**Nothing deployed by this change.** To go live after operator
review:

1. Merge the dev branch into main (operator action).
2. Set `BB_BOUNCE_SESSION_TREND_GUARD_ENABLED=1` in `.env` on the
   BB-Bounce host.
3. (Optional) Set `SESSION_TREND_STRONG_DISP_PIPS=15` if operator
   chooses the Oct-12-recoverable calibration.
4. Restart only `autobot-start.service` on the AutoBot host so the
   state machine starts publishing snapshots.
5. Restart only `bb-bounce.service` on the BB-Bounce host so the
   guard reads the fresh snapshots.

Snapshot file path (production): `data/session_trend_GBPUSD.json`.
BB-Bounce reads it via `SESSION_TREND_SNAPSHOT_DIR` env + stale-age
window `SESSION_TREND_GUARD_MAX_AGE_SECS` (default 600s).

---

## 10. Review checklist

- [ ] Approve the 5-criterion state machine as spec-compliant.
- [ ] Decide `STRONG_DISPLACEMENT_PIPS` — 20p (default) or 15p
      (Oct-12 recovery with 3 additional FPs).
- [ ] Approve or defer the §7 drawdown-from-peak release refinement.
- [ ] Approve merge of the dev branches (AutoBot + BB-Bounce).
- [ ] Instruct Claude to enable the guard flag + restart services,
      or do so manually.
