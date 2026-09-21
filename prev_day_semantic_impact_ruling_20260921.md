# PRE-M4 SEMANTIC IMPACT RULING — fa18a90

**Commit under review:** `fa18a90 fix(prior-d1): authoritative previous-completed-D1 selector (pre-M4 correction)`
**Date:** 2026-09-21
**Scope:** read-only audit. No production code, live cache, IG contact, or timer state touched. TRADE_ENABLED=0, STAGE10P paused.
**Baseline for diff:** `4b354f4` (checked out at `/tmp/pre-fa18a90-audit` via `git worktree add`; no stash).
**Conclusion up front:** `FA18A90_SEMANTIC_CHANGE = CORRECTIVE_BUT_PREVIOUS_INTENT_AMBIGUOUS`. `ADDITIONAL_PREREQUISITE_FIX_REQUIRED = YES` (latent Sunday-fragment defect on `5D_HIGH`/`5D_LOW`/`20D_HIGH`/`20D_LOW` propagates into `gbpusd_confirmation_fallback` via the `SWING_HIGH`/`SWING_LOW` vocab tags — proven with fixture). `READY_TO_RESUME_M4 = NO`.

---

## §1 · Issue A — original semantic intent of `PREV_DAY_HIGH` / `_LOW` / `_CLOSE`

**Ruling:** `PREV_DAY_ORIGINAL_SEMANTICS = AMBIGUOUS`.

### Evidence

| # | Locus | Evidence | Points to |
|---|-------|----------|-----------|
| 1 | `level_computation.py:444-448` (pre-fix, `/tmp/pre-fa18a90-audit`) | `if d1: cats["PREV_DAY_HIGH"] = d1[-1]["high"]` — no docstring, no comment. `d1` is `ss._aggregate_to_d1(files)` where `files` is `_load_5m_csvs()` grouping by calendar-UTC filename `YYYY-MM-DD.csv`. | UTC_CALENDAR_DAY (implementation) |
| 2 | `structural_state.py:307-329` — `_load_5m_csvs` | Glob `sym_dir.glob('*.csv')` and select by `p.stem` (filename date). Weekend files are **not** filtered. Only *today's* partial is excluded. | UTC_CALENDAR_DAY, includes Sundays |
| 3 | `level_computation.py:78-83`, `354` (pre- and post-fix) | Neighbouring Asian-session code in the same module uses `ASIAN_START_HOUR_PREV = 22` — FX-session boundary is already the local convention for session windows. | FX_TRADING_DAY (by analogy) |
| 4 | `bb_pd_gate.py:245-260` (pre-fix @ 4b354f4) — `_select_prior_d1` docstring | "Uses the identical D1 source and prior-day rule as `compute_pd_pct` so `pd_pct` and pivot outputs can never disagree about which bar is 'yesterday'." The asserted invariant is `pd_pct == pivots`; **it does not name `PREV_DAY_HIGH`**. `bb_pd_gate` walks `cache/htf/{SYM}_D1.json` which is FX-session labelled. | FX_TRADING_DAY for PDH; silent on level_computation |
| 5 | `git log -p -- level_computation.py` around the introduction of `PREV_DAY_*` | Original 2026-earlier commit introduced these three names without a comment defining the day boundary. No downstream design doc names PREV_DAY_HIGH. | UNDOCUMENTED |
| 6 | `tests/unit/test_previous_trading_day_selector.py` (added *by* fa18a90) | `test_G_pdh_and_prev_day_high_source_identity` asserts `PREV_DAY_HIGH == PDH`. This is a **new** assertion — it cannot be evidence of prior intent. | (Post-hoc — excluded) |

### Reading

Two labels for "yesterday's high" existed in production with two different day boundaries. The `bb_pd_gate` path has been FX-session for at least the 2026-09-07 exam-freeze tightening. The `level_computation` path was calendar-UTC with no defence. Under any reasonable naming, "PDH" and "PREV_DAY_HIGH" should be the same bar — but the codebase never explicitly said so before fa18a90. Hence **AMBIGUOUS** on the strict question, with the pre-existing structural bias (Asian-session code, PDH docstring) leaning FX_TRADING_DAY.

**`FA18A90_PREV_DAY_CHANGE_INTENDED = NOT_PROVEN`** — the change is defensible; the pre-existing intent is not documented.

---

## §2 · Quantifying the PREV_DAY_* behavioural change on ordinary weekdays

Reproduced pre- and post-fix numerics from real historical data (`/opt/tradingbot/data/candles/GBPUSD/*.csv` for pre; `/opt/tradingbot/cache/htf/GBPUSD_D1.json` for post). Deltas are in **pips** (1 pip = 10 IG scaled units at 5-decimal quote).

```
fire_date   dow | pre-fix source                              | post-fix source                             | ΔH   ΔL   ΔC  (pips)
------------------------------------------------------------------------------------------------------------------------------
2026-09-15  Tue | 2026-09-14  H=13528.55 L=13463.95 C=13500.95 | 2026-09-14  H=13525.30 L=13463.50 C=13504.50 | +0.3 +0.0 -0.4
2026-09-16  Wed | 2026-09-15  H=13501.65 L=13463.85 C=13471.05 | 2026-09-15  H=13504.50 L=13463.40 C=13474.60 | -0.3 +0.0 -0.4
2026-09-17  Thu | 2026-09-16  H=13497.00 L=13372.05 C=13382.25 | 2026-09-16  H=13494.20 L=13367.30 C=13379.60 | +0.3 +0.5 +0.3
2026-09-18  Fri | 2026-09-17  H=13407.60 L=13336.05 C=13356.15 | 2026-09-17  H=13406.40 L=13335.60 C=13357.50 | +0.1 +0.0 -0.1
2026-09-09  Wed | 2026-09-08  H=13562.45 L=13521.65 C=13544.25 | 2026-09-08  H=13562.00 L=13521.20 C=13540.60 | +0.0 +0.0 +0.4
2026-09-10  Thu | 2026-09-09  H=13568.35 L=13530.45 C=13550.05 | 2026-09-09  H=13567.90 L=13530.00 C=13551.80 | +0.0 +0.0 -0.2
2026-09-11  Fri | 2026-09-10  H=13560.45 L=13491.15 C=13510.35 | 2026-09-10  H=13559.80 L=13490.70 C=13511.80 | +0.1 +0.0 -0.1
2026-08-26  Wed | 2026-08-25  H=13654.35 L=13621.45 C=13645.45 | 2026-08-25  H=13653.90 L=13621.00 C=13648.70 | +0.0 +0.0 -0.3
2026-08-20  Thu | 2026-08-19  H=13630.55 L=13523.25 C=13599.55 | 2026-08-19  H=13630.55 L=13523.25 C=13606.30 | +0.0 +0.0 -0.7
```

Both paths select the **same calendar date**; the values differ because the FX-session bar spans D-1 22:00 → D 22:00 UTC while the calendar-UTC bar spans D 00:00 → D 24:00 UTC (the two 2-hour tails at each end).

- **`NORMAL_WEEKDAY_MAX_HIGH_DELTA_PIPS = 0.5`** (across sample; typical magnitude ≤ 0.3 pip)
- **`NORMAL_WEEKDAY_MAX_LOW_DELTA_PIPS  = 0.5`**
- **`NORMAL_WEEKDAY_MAX_CLOSE_DELTA_PIPS = 0.7`**

### Downstream effect on the candidate/selection surface

`gbpusd_confirmation_fallback._select_liquidity_levels` (`gbpusd_confirmation_fallback.py:225-249`) calls `level_computation.get_ranked_levels` and consumes tags `PREV_DAY_HIGH` / `PREV_DAY_LOW`. Its selection rule filters by `LEVEL_MAX_DIST_PIPS` band and orders by closeness to `current_close`. A ≤0.7-pip shift in PREV_DAY_H/L on ordinary weekdays can:

- **Reorder** two candidate levels that were within ≤0.7 pips of each other → **DOWNSTREAM_SELECTION_CHANGED = YES (possible, not empirically forced in this sample)**.
- **Never add / remove** a candidate from the max-distance band (~40-60 pips typical). → **DOWNSTREAM_CANDIDATE_SET_CHANGED = NO** for ordinary weekdays.

**`NORMAL_WEEKDAY_PREV_DAY_BEHAVIOUR_CHANGED = YES`** — small magnitude (≤ ~1 pip) but non-empty on every ordinary weekday.

---

## §3 · Weekend case for PREV_DAY_* — Sunday-partial CSV

### Source, side by side

| Fire date | Pre-fix source (`d1[-1]` from `_aggregate_to_d1`) | Post-fix source (`select_prior_completed_d1`) |
|-----------|---------------------------------------------------|-----------------------------------------------|
| 2026-09-14 Mon | **`2026-09-13` (Sunday partial)** — 48 5m bars, 20:00-23:55 UTC only | `2026-09-11` (Friday, full FX-session bar) |
| 2026-09-07 Mon | **`2026-09-06` (Sunday partial)** | `2026-09-04` (Friday) |
| 2026-08-31 Mon | **`2026-08-30` (Sunday partial)** | `2026-08-28` (Friday) |
| 2026-09-21 Mon | `2026-09-18` (Friday — no Sunday CSV present that week) | `2026-09-18` (Friday) |

**Numeric deltas on post-weekend Mondays where a Sunday CSV exists** (pips):

```
2026-09-14 Mon | pre 2026-09-13  H=13532.40 L=13516.25 C=13526.95 | post 2026-09-11  H=13534.70 L=13476.70 C=13522.20 | ΔH=-0.2  ΔL=+4.0  ΔC=+0.5
2026-09-07 Mon | pre 2026-09-06  H=13523.25 L=13505.30 C=13516.35 | post 2026-09-04  H=13549.20 L=13481.50 C=13510.00 | ΔH=-2.6  ΔL=+2.4  ΔC=+0.6
2026-08-31 Mon | pre 2026-08-30  H=13542.05 L=13526.25 C=13539.75 | post 2026-08-28  H=13597.40 L=13525.60 C=13526.30 | ΔH=-5.5  ΔL=+0.1  ΔC=+1.3
```

The 2026-08-31 case: on Monday the pre-fix code returned Sunday's thin 4-hour extremes as PDH/PDL, understating the true Friday high by **5.5 pips**. On the same Monday PDH from `bb_pd_gate` returned Friday's 13597.40 → **PDH and PREV_DAY_HIGH silently disagreed by 5.5 pips**, which is well inside the `gbpusd_confirmation_fallback` band and inside typical stop-distance tolerances.

**Sunday CSVs actually present in `/opt/tradingbot/data/candles/GBPUSD/`** (grep for weekday=7 files, 2026 only, most recent 12):

```
2026-04-05, 2026-04-12, 2026-04-19, 2026-04-26, 2026-05-03, 2026-05-10, 2026-05-31,
2026-06-14, 2026-06-21, 2026-06-28, 2026-07-05, 2026-07-19, 2026-07-26, 2026-08-02,
2026-08-09, 2026-08-16, 2026-08-23, 2026-08-30, 2026-09-06, 2026-09-13
```

Most weekends produce one. The 2026-04-04/11/18 files are Saturday partials from the Easter-adjacent trading week. This is a real, recurring input surface — not a theoretical one.

**Pre-fix behaviour could and did select the Sunday fragment on Monday.** The fix is corrective.

---

## §4 · Issue B — audit of remaining calendar-UTC aggregates

| NAME | SOURCE (file:line) | WINDOW_SEMANTICS | USES_D1_OHLC | CAN_22:00_vs_00:00_CHANGE | CAN_SUNDAY_PARTIAL_ENTER | CAN_POST_WEEKEND_RESTART_CHANGE | DOWNSTREAM_CONSUMERS |
|------|--------------------|------------------|:---:|:---:|:---:|:---:|----------------------|
| `5D_HIGH` / `5D_LOW` | `level_computation.py:470-472`; d1 = `ss._aggregate_to_d1(_load_5m_csvs(sym, today, 35))` (structural_state.py:357, :307) | max/min over last 5 D1 bars from calendar-UTC filenames | YES (built from 5m via `_aggregate_to_d1`) | NO (max/min insensitive to intraday boundary once the same calendar date is included) | **YES** — `_load_5m_csvs` does not filter weekend filenames; only *today* is excluded | **YES** — a Sunday CSV enters the last-5-bar window on Monday and shifts max/min | Mapped to vocab tags `SWING_HIGH`/`SWING_LOW` (`level_computation.py:138-141`). Consumed by `gbpusd_confirmation_fallback._BUY_SIDE_TAGS/_SELL_SIDE_TAGS` (`gbpusd_confirmation_fallback.py:138-140`) as sweep-side liquidity levels |
| `20D_HIGH` / `20D_LOW` | `level_computation.py:474-476` | same as 5D but last 20 D1 bars | YES | NO | **YES** | **YES** — 3-4 past Sundays in a 20-bar window | Same `SWING_HIGH`/`SWING_LOW` route → `gbpusd_confirmation_fallback` |
| `WEEK_HIGH` / `WEEK_LOW` / `WEEKLY_MID` / `PREV_WEEK_HIGH` / `PREV_WEEK_LOW` | `level_computation.py:478-484`; weekly = `ss._aggregate_to_weekly(d1)` (structural_state.py:397) | ISO-week (Mon-Sun) bucketing of calendar-UTC D1 bars | YES | NO (ISO-week membership stable under 22:00-vs-00:00 shift) | **YES** — Sunday CSV belongs to the ISO-week ending that Sunday and enters the current-week bucket | **YES** — Sunday partial can lift `WEEK_HIGH`, drop `WEEK_LOW`, or become the `WEEK_CLOSE` | Vocab tags `WEEK_HIGH`/`WEEK_LOW`/`PREV_WEEK_HIGH`/`PREV_WEEK_LOW`/`DAILY_PIVOT` (`level_computation.py:134-136, :151`). **Not** in `gbpusd_confirmation_fallback` allowlist; used by ranked-level output only. No enumerated trade-capable consumer that gates on numeric weekly values (as of this HEAD) |
| `D1_EMA_20` | `level_computation.py:503-505`; series = `[b["close"] for b in d1]`, `_ema(closes, 20)` | 20-period EMA over calendar-UTC D1 close sequence | YES (closes only) | NO (boundary shift changes each close by ≤ ~0.7 pip; EMA of 20 dampens further) | **YES** — Sunday CSV close enters the series | **YES** | Vocab tag `EMA_50` (`level_computation.py:152`). Consumed by `level_computation.get_ranked_levels` only — no trade-capable strategy gates on the numeric `D1_EMA_20` category value. The v5_pia briefing `d1_ema_20` field (`briefing/v5_pia/data_package.py:187`) is a **separate** value sourced from `_TF_CTX._d1_closed` (`timeframe_context.py:279-282` with `D1_SESSION_OFFSET_SEC` — FX-session aligned), **not** this calendar-UTC path |

### v5_pia disambiguation

The Explore pass flagged v5_pia briefing `d1_ema_20` as a downstream consumer of `D1_EMA_20`. Verified: it is a **name collision, not a data collision**. `briefing/v5_pia/data_package.py:183-187` reads `base["d1_candles"]` from `morning_briefing._assemble_data_package`, which pulls from `_TF_CTX._d1_closed` — the FX-session-aligned aggregation in `timeframe_context.py:279-282`. That path is unaffected by `level_computation`'s calendar-UTC `d1`. Confidence scoring and trade-plan stops in v5_pia therefore do not consume the `D1_EMA_20` category we are auditing.

---

## §5 · Controlled counterexample — Sunday fragment against 5D / 20D / weekly / EMA_20

Fixture: 25 completed weekdays ending Fri 2026-08-14 with `high = 1000+i`, `low = 990+i`, `close = 1000+i`, `i∈[0,24]`. Sunday 2026-08-16 partial injected with distinctive `high=9999, low=8888, close=9500`. Existing algorithms run unchanged.

```
Last weekday bar: date=2026-08-14 open=1019 high=1024 low=1014 close=1024
Sunday fragment:  date=2026-08-16 open=9000 high=9999 low=8888 close=9500

5D_HIGH  wo= 1024.0  w= 9999.0  CHANGED=True
5D_LOW   wo= 1010.0  w= 1011.0  CHANGED=True
20D_HIGH wo= 1024.0  w= 9999.0  CHANGED=True
20D_LOW  wo=  995.0  w=  996.0  CHANGED=True
WEEK_HIGH  (current ISO-33) wo= 1024.0  w= 9999.0  CHANGED=True
WEEK_LOW   (current ISO-33) wo= 1010.0  w= 1010.0  CHANGED=False  # only because 8888 > 1010; a Sunday low < 1010 would flip this
WEEK_CLOSE (current ISO-33) wo= 1024.0  w= 9500.0  CHANGED=True
D1_EMA_20  wo= 1014.5000  w= 1822.6429  CHANGED=True  delta=+808.14
```

**`SUNDAY_FRAGMENT_AFFECTS_5D_HIGH   = YES`**
**`SUNDAY_FRAGMENT_AFFECTS_20D_HIGH  = YES`**
**`SUNDAY_FRAGMENT_AFFECTS_WEEKLY    = YES`** (`WEEK_HIGH`, `WEEK_CLOSE` confirmed; `WEEK_LOW` conditionally, depends on Sunday's low)
**`SUNDAY_FRAGMENT_AFFECTS_D1_EMA20  = YES`**

The commit body's claim that these are "insensitive to a 2-hour boundary shift" is **technically true for the 22:00-vs-00:00 shift itself** — but that is the wrong risk vector. The Sunday-partial vector — which is what the same commit explicitly fixed for `PREV_DAY_*` — remains open on all four aggregates.

---

## §6 · Post-weekend readiness impact

| STRATEGY / FAMILY | INPUT | SUNDAY_FRAGMENT_CAN_REACH_IT | CAN_CHANGE_SIGNAL / READINESS / LEVEL | FAIL_CLOSED_OR_SILENT |
|---|---|:---:|---|---|
| `gbpusd_confirmation_fallback` (sweep-and-reclaim) | `SWING_HIGH` / `SWING_LOW` tags via `_select_liquidity_levels` (`gbpusd_confirmation_fallback.py:225-249`) → level_computation `5D_HIGH/LOW`, `20D_HIGH/LOW` map to those tags (`level_computation.py:138-141`) | **YES** on any Monday after a weekend where the prior-Sunday CSV exists | Reordering / substitution of a sweep-target liquidity level; on 20D window a distant past-Sunday's inflated high can become the dominant sell-side candidate for the entire week | **SILENT** — no fail-closed, the level is used as-is |
| `bb_pd_gate` (pivot family, PDH/PDL) | `select_prior_completed_d1` — FX-session, weekend-filtered | NO | — | — |
| `gbpusd_ema_pullback` | H1 EMAs and swing structure from `_TF_CTX` — not `level_computation` category dict | NO | — | — |
| `TREND_V3` / `STRUCTURE_BREAK` | Structure levels via `structural_state`; consumes `structural_state.classify_structure` and swing points, not the calendar-UTC `d1[-1]` extremes | Indirect — `structural_state._aggregate_to_d1` is the same source but the consumers of `classify_structure` operate on swing runs, not the last-bar values | Not proven in this audit — call chain would need targeted reproduction | — |
| v5_pia briefing (confidence scorer, trade-plan stops) | `d1_ema_20` / `h4_ema_20` from `_TF_CTX._d1_closed` — FX-session-aligned | NO (different source than the audited `D1_EMA_20` category) | — | — |
| `WEEK_*` / `PREV_WEEK_*` consumers | Vocab tags emitted; no trade-capable consumer in the current HEAD gates numerically on these | N/A (nothing to reach) | — | — |

**`POST_WEEKEND_REMAINING_AGGREGATE_DEFECT = YES`** for `5D_HIGH`/`5D_LOW`/`20D_HIGH`/`20D_LOW` via the `SWING_HIGH`/`SWING_LOW` route into `gbpusd_confirmation_fallback`. Weekly and D1_EMA_20 remain unreached by any trade-capable consumer at this HEAD.

**`AFFECTED_STRATEGIES = gbpusd_confirmation_fallback`** (through the shared `SWING_HIGH` / `SWING_LOW` vocab tag routing 5D/20D extremes to the strategy's sweep-target liquidity list).

---

## §7 · Scope discipline

This audit does **not** authorise migrating every daily calculation to FX-session D1. The four remaining aggregates have **no explicit calendar-day intent documented anywhere**, and the Sunday-fragment risk is real. The right corrections are surgical:

- Either filter weekend files from `_load_5m_csvs` (belongs in `structural_state`), or
- Route the four aggregates through FX-session D1 (same shape as the fa18a90 fix for `PREV_DAY_*`).

`WEEK_HIGH` / `WEEK_LOW` / `WEEKLY_MID` / `PREV_WEEK_*` and `D1_EMA_20` may not be worth immediate rework — they have no trade-capable consumer today — but `5D_*` / `20D_*` do reach a live strategy via the vocab-tag alias and warrant a follow-up.

---

## §8 · Ruling

`FA18A90_SEMANTIC_CHANGE = CORRECTIVE_BUT_PREVIOUS_INTENT_AMBIGUOUS`

- **Corrective**, because:
  - Pre-existing code allowed a Sunday-evening 4-hour fragment to become PREV_DAY_HIGH/LOW/CLOSE on Monday. Reproduced on three historical Mondays (2026-08-31, 2026-09-07, 2026-09-14). Delta up to 5.5 pips on PDH.
  - Pre-existing code silently disagreed with `bb_pd_gate` PDH on those Mondays and by ≤ ~0.7 pips on every ordinary weekday. Two sources of truth for "yesterday's high" is a defect regardless of which is deemed canonical.
  - `gbpusd_confirmation_fallback` consumes `PREV_DAY_HIGH`/`PREV_DAY_LOW` directly (`gbpusd_confirmation_fallback.py:138-140`) — a real live consumer benefits from the alignment.
- **Previous intent ambiguous**, because:
  - The pre-existing implementation was calendar-UTC and carried no docstring/comment.
  - The invariant PDH ↔ PREV_DAY_HIGH was **not** documented before fa18a90 (the pre-fix `bb_pd_gate` docstring only asserts `pd_pct == pivots`).
  - The test that pins the identity (`test_G_pdh_and_prev_day_high_source_identity`) was **added by** fa18a90 and cannot serve as prior-intent evidence.

---

## §9 · FINAL RETURN

```
COMMIT_UNDER_REVIEW = fa18a90

PREV_DAY_ORIGINAL_SEMANTICS = AMBIGUOUS
FA18A90_PREV_DAY_CHANGE_INTENDED = NOT_PROVEN
NORMAL_WEEKDAY_PREV_DAY_BEHAVIOUR_CHANGED = YES

NORMAL_WEEKDAY_MAX_HIGH_DELTA_PIPS  = 0.5
NORMAL_WEEKDAY_MAX_LOW_DELTA_PIPS   = 0.5
NORMAL_WEEKDAY_MAX_CLOSE_DELTA_PIPS = 0.7

DOWNSTREAM_CANDIDATE_SET_CHANGED = NO   (ordinary weekdays; the 1-pip delta cannot cross the ~40-60 pip max-dist band)
DOWNSTREAM_SELECTION_CHANGED     = NOT_TESTED  (empirically not forced in the ordinary-weekday sample; possible under adverse ordering within the band; on post-weekend Monday with Sunday CSV present the SELECTED bar itself differs — Friday vs Sunday fragment — so selection IS changed there)

SUNDAY_PRE_FIX_SOURCE  = _aggregate_to_d1(files)[-1] where files include cache/GBPUSD/YYYY-MM-DD.csv with no weekend filter → picks Sunday partial
SUNDAY_POST_FIX_SOURCE = select_prior_completed_d1(sym, fire_date) walking cache/htf/GBPUSD_D1.json with weekday<5 filter → picks Friday

SUNDAY_FRAGMENT_AFFECTS_5D_HIGH   = YES
SUNDAY_FRAGMENT_AFFECTS_20D_HIGH  = YES
SUNDAY_FRAGMENT_AFFECTS_WEEKLY    = YES
SUNDAY_FRAGMENT_AFFECTS_D1_EMA20  = YES

POST_WEEKEND_REMAINING_AGGREGATE_DEFECT = YES  (5D_HIGH/LOW and 20D_HIGH/LOW reach gbpusd_confirmation_fallback via SWING_HIGH/SWING_LOW vocab-tag alias)

AFFECTED_STRATEGIES = gbpusd_confirmation_fallback
                       (via SWING_HIGH/SWING_LOW vocab tags fed by 5D_HIGH/LOW and 20D_HIGH/LOW —
                        latent Sunday-fragment defect not fixed by fa18a90)

FA18A90_SEMANTIC_CHANGE = CORRECTIVE_BUT_PREVIOUS_INTENT_AMBIGUOUS

ADDITIONAL_PREREQUISITE_FIX_REQUIRED = YES
    (Recommend follow-up: either filter weekend files in structural_state._load_5m_csvs,
     or route 5D_*/20D_* through the FX-session D1 store — same pattern as the fa18a90
     PREV_DAY_* fix. Weekly and D1_EMA_20 have no trade-capable consumer at HEAD but
     carry the same latent semantic mismatch and should be tickets, not silent debt.)

READY_TO_RESUME_M4 = NO

LIVE_SERVICE_TOUCHED = NO
LIVE_CACHE_CHANGED   = NO
LIVE_IG_CONTACT      = NO
TRADE_ENABLED        = 0
STAGE10P             = PAUSED

SAFE_TO_DEPLOY = NO
```

STOP.
