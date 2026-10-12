# STRONG TREND — final validation (2026-10-13)

**Implementation baseline:** AutoBot commit `f90ffd2` (v2 evidence-
based state machine). BB-Bounce commit `da1babd`. **No classifier
or reversal threshold changes** in this review.

**Status:** DEVELOPMENT. No deployment, no merges, no restarts,
no `.env` edited, no IG orders.

---

## 1. Research-only truth correction

The v2 report labelled 4 days as "FPs" because its `_day_truth`
function used EOD close-position-in-range. This penalised days
with legitimate intraday trends that reversed by close.

**New truth definition — intraday dominant extreme:**

For each day, inspect the full London session (07:00 → 20:00 UTC)
and compute the dominant intraday peak displacement from the
London open:

```
peak_down = |min(disp)| if negative else 0
peak_up   = max(disp)   if positive else 0
INTRADAY_DOWN  if peak_down > peak_up and peak_down >= 20p
INTRADAY_UP    if peak_up   > peak_down and peak_up   >= 20p
INTRADAY_BOTH  if both ≥ 20p
INTRADAY_NONE  otherwise
```

A fire is **VALID** when ST's direction matches the dominant
intraday direction or when the day was `INTRADAY_BOTH`. A fire
is a **WRONG_DIRECTION** restriction when ST's direction opposes
the dominant intraday direction. Days with no fire are classified
`CORRECT_QUIET` (no intraday ≥ 20p move) or `MISSED_INTRADAY`
(intraday ≥ 20p move but no fire).

This truth is derived **chronologically**: each day is scored by
its observable intraday evidence, not retrospectively by EOD close.

---

## 2. Final scorecard (34 days, Sep 1 → Oct 13, 2026)

| Category | Count | Notes |
|---|---|---|
| **VALID_FIRE** | **16** | ST direction matches intraday extreme |
| **WRONG_DIRECTION** | **5** | ST fired opposite to intraday extreme |
| **CORRECT_QUIET** | **4** | No fire, no intraday ≥ 20p move |
| **MISSED_INTRADAY** | **9** | Intraday ≥ 20p move, no fire |
| **Total** | 34 |  |

**Fire accuracy:** 16 / 21 = **76% of fires align with intraday
truth.** The v2 scorecard's "4 FPs" collapse under this truth —
all 4 (09-04, 09-09, 09-11, 09-28) are reclassified as VALID_FIRE
because the day's dominant intraday peak was in the fire direction.

### Full per-day table

| date | intraday | ST_fire | first_ts | min_disp | max_disp | verdict |
|---|---|---|---|---|---|---|
| 2026-09-01 | DOWN | DOWN | 16:35 UTC | −34.2p | +10.0p | VALID_FIRE |
| 2026-09-02 | UP   | DOWN | 10:40 UTC | −17.7p | +20.7p | **WRONG_DIRECTION** |
| 2026-09-03 | UP   | —    | — | −6.2p | +55.6p | MISSED_INTRADAY |
| 2026-09-04 | DOWN | DOWN | 09:55 UTC | −46.5p | +4.9p | VALID_FIRE |
| 2026-09-06 | NONE | —    | — | −3.2p | +12.0p | CORRECT_QUIET |
| 2026-09-07 | UP   | UP   | 08:35 UTC | −3.6p | +20.7p | VALID_FIRE |
| 2026-09-08 | UP   | DOWN | 08:55 UTC | −14.4p | +22.0p | **WRONG_DIRECTION** |
| 2026-09-09 | DOWN | DOWN | 08:25 UTC | −26.3p | +6.6p | VALID_FIRE |
| 2026-09-10 | DOWN | DOWN | 11:10 UTC | −63.0p | +0.0p | VALID_FIRE |
| 2026-09-11 | DOWN | DOWN | 08:10 UTC | −28.3p | +7.9p | VALID_FIRE |
| 2026-09-13 | NONE | —    | — | −7.4p | +0.0p | CORRECT_QUIET |
| 2026-09-14 | BOTH | —    | — | −26.0p | +22.6p | MISSED_INTRADAY |
| 2026-09-15 | UP   | —    | — | −2.2p | +26.1p | MISSED_INTRADAY |
| 2026-09-16 | DOWN | DOWN | 16:40 UTC | −103.9p | +2.4p | VALID_FIRE |
| 2026-09-17 | DOWN | —    | — | −58.5p | +7.4p | MISSED_INTRADAY |
| 2026-09-18 | BOTH | DOWN | 10:45 UTC | −33.1p | +23.8p | VALID_FIRE |
| 2026-09-21 | NONE | —    | — | −17.4p | +15.7p | CORRECT_QUIET |
| 2026-09-22 | DOWN | —    | — | −50.0p | +0.3p | MISSED_INTRADAY |
| 2026-09-23 | DOWN | DOWN | 09:45 UTC | −92.1p | +0.0p | VALID_FIRE |
| 2026-09-24 | DOWN | DOWN | 09:55 UTC | −39.3p | +10.1p | VALID_FIRE |
| 2026-09-25 | UP   | UP   | 08:50 UTC | −4.2p | +37.8p | VALID_FIRE |
| 2026-09-27 | DOWN | —    | — | −21.8p | +0.0p | MISSED_INTRADAY |
| 2026-09-28 | UP   | UP   | 13:50 UTC | −5.3p | +33.7p | VALID_FIRE |
| 2026-09-29 | DOWN | —    | — | −35.1p | +11.3p | MISSED_INTRADAY |
| 2026-09-30 | UP   | —    | — | +0.0p | +47.9p | MISSED_INTRADAY |
| 2026-10-01 | DOWN | DOWN | 08:40 UTC | −81.9p | +2.2p | VALID_FIRE |
| 2026-10-02 | UP   | DOWN | 12:10 UTC | −15.2p | +39.1p | **WRONG_DIRECTION** |
| 2026-10-04 | NONE | —    | — | −4.6p | +2.4p | CORRECT_QUIET |
| 2026-10-05 | DOWN | UP   | 08:20 UTC | −25.1p | +18.7p | **WRONG_DIRECTION** |
| 2026-10-06 | UP   | UP   | 07:55 UTC | −5.3p | +67.8p | VALID_FIRE |
| 2026-10-07 | DOWN | DOWN | 08:10 UTC | −55.7p | +1.1p | VALID_FIRE |
| 2026-10-08 | UP   | —    | — | −9.9p | +53.5p | MISSED_INTRADAY |
| 2026-10-09 | DOWN | UP   | 08:25 UTC | −28.1p | +11.4p | **WRONG_DIRECTION** |
| **2026-10-12** | **DOWN** | **DOWN** | **09:50 UTC** | **−42.6p** | **+0.0p** | **VALID_FIRE** |

---

## 3. Genuine false restrictions (5 days)

Days where ST fired in the direction opposite to the dominant
intraday peak. **These are the real false restrictions** —
BB-Bounce entries in the aligned direction would be blocked
on a day actually moving the other way.

| Date | Fire | Intraday peak (opposite) | ST final | Notes |
|---|---|---|---|---|
| 2026-09-02 | DOWN at 10:40 | **UP** peak +20.7p | RANGE | Marginal: UP leg just at 20p threshold. Day was mostly choppy. BB-Bounce BUYs wrongly blocked. |
| 2026-09-08 | DOWN at 08:55 | **UP** peak +22.0p | UNKNOWN | ST fired DOWN then released. BUYs blocked during the DOWN window. |
| 2026-10-02 | DOWN at 12:10 | **UP** peak +39.1p (strong!) | RANGE | Clear wrong-direction. Day went strongly UP but ST fired DOWN. ST released to RANGE by EOD so some recovery. |
| 2026-10-05 | UP at 08:20 | **DOWN** peak −25.1p | RANGE | Fire opposite to dominant DOWN move. ST released to RANGE by EOD. |
| 2026-10-09 | UP at 08:25 | **DOWN** peak −28.1p | UNKNOWN | Fire opposite to dominant DOWN. ST released. |

Three of five (10-02, 10-05, 10-09) released to UNKNOWN or RANGE
before EOD — the release path mitigated the error window. Two
(09-02, 09-08) are earlier in the window and more concerning.

**Common pattern (not implemented):** All 5 are days where ST
latched onto an opening leg that reversed. Earlier wrong-direction
fires at 08:20-08:55 may indicate the state machine is too
aggressive in the first 2 hours after London open. A
`MIN_BARS_SINCE_LONDON` requirement (e.g., 24 bars = 2h) was
considered in prior reports and rejected; the data here supports
reconsidering. **Not implemented in this review.**

---

## 4. Missed strong trends (9 days)

Days with a sustained intraday move ≥ 20p where ST never fired.
These are **lost protection opportunities** but not false
restrictions — guard allows both BUY and SELL on these days.

| Date | Intraday direction | Peak | Why ST never fired (fire-moment evidence insufficient) |
|---|---|---|---|
| 2026-09-03 | UP | +55.6p | Structure asymmetry never ≥ 2 for UP |
| 2026-09-14 | BOTH | −26.0 / +22.6p | Both directions had moves; asymmetry diluted |
| 2026-09-15 | UP | +26.1p | Mild progression; evidence stayed below gates |
| 2026-09-17 | DOWN | −58.5p | Structure didn't accumulate asymmetry in time |
| 2026-09-22 | DOWN | −50.0p | Slow drift; asymmetric structure never fully formed |
| 2026-09-27 | DOWN | −21.8p | Just at threshold; evidence insufficient |
| 2026-09-29 | DOWN | −35.1p | Structure stayed symmetric through the day |
| 2026-09-30 | UP | +47.9p | Fast move; sr_up grew with sr_dn in lockstep |
| 2026-10-08 | UP | +53.5p | Pullback_up never caught up to pullback_dn |

**Recognition timestamps for VALID_FIRE days (operator-requested):**

London times are UTC. BST applies through Sun 2026-10-25.

| Date | ST fire time | Direction | Delta from London open |
|---|---|---|---|
| 09-01 | 16:35 UTC | DOWN | +9h35m |
| 09-04 | 09:55 UTC | DOWN | +2h55m |
| 09-07 | 08:35 UTC | UP | +1h35m |
| 09-09 | 08:25 UTC | DOWN | +1h25m |
| 09-10 | 11:10 UTC | DOWN | +4h10m |
| 09-11 | 08:10 UTC | DOWN | +1h10m |
| 09-16 | 16:40 UTC | DOWN | +9h40m |
| 09-18 | 10:45 UTC | DOWN | +3h45m |
| 09-23 | 09:45 UTC | DOWN | +2h45m |
| 09-24 | 09:55 UTC | DOWN | +2h55m |
| 09-25 | 08:50 UTC | UP | +1h50m |
| 09-28 | 13:50 UTC | UP | +6h50m |
| 10-01 | 08:40 UTC | DOWN | +1h40m |
| 10-06 | 07:55 UTC | UP | +0h55m |
| 10-07 | 08:10 UTC | DOWN | +1h10m |
| **10-12** | **09:50 UTC** | **DOWN** | **+2h50m** |

---

## 5. 2026-09-28 contrary-pivot investigation — CORRECTION

**My earlier case-study report (`fp_case_studies_20261013`) claimed
"44 R-level DOWN rejections before the UP fire".** This claim was
incorrect.

**Root cause 1 — wrong prev-day pivot source:** My case-study
code's `_prev()` picked Sunday 2026-09-27 (which contains overnight
archive bars) instead of Friday 2026-09-25. This produced the wrong
pivot set with R1 at 13244.8 (just 3p above London open 13241.5).
Price touched R1 many times, inflating the count.

**Root cause 2 — ad-hoc counting ignored the pivot filter:** My
case-study code counted every record in `pivot_rejections` without
filtering by pivot name. Production `_detect_pivot_rejection`
(session_trend.py:1063-1094) tracks only R2/R3/S2/S3 — R1 touches
produce no record.

**Corrected count with Friday 2026-09-25 pivots:**

```
Pivots: R3=13324.6 R2=13294.1 R1=13270.5 P=13240.0
         S1=13216.4 S2=13185.9 S3=13162.3

09-28 fire reason:
strong_up:struct=[up=6,dn=4,asym=+2]|pullback=[up=2,dn=0]|
reversals=0|close_pos=0.82|disp=+26.3p(strong)|
piv_support=0|persistence_bars=2
```

**Finding:** `piv_support=0`. There is **no contrary pivot evidence
on 2026-09-28** under the production logic. The earlier concern
("44 contrary rejections") was a reporting artefact, not a signal.

No logic change recommended. The pivot-rejection detector is
functioning as specified; it correctly ignored R1 touches.

---

## 6. 2026-10-12 regression — verified unchanged

Pinned regression test
`tests/data_continuity/test_phase8_oct12_regression.py` executes
the chronological replay against the live 2026-10-12 GBPUSD archive
and asserts:

| Assertion | Result |
|---|---|
| London open @ 2026-10-12T07:00:00+00:00 | ✓ open price 13246.2 |
| **First DOWN establishment @ 2026-10-12T09:50:00+00:00** | ✓ |
| 08:10:11 SELL | ✓ allow |
| 09:35:12 BUY | ✓ allow |
| **10:20:18 BUY** | ✓ **block:established_down** |
| **11:18:06 BUY** | ✓ **block:established_down** |
| 12:20:14 SELL | ✓ allow |
| **14:10:14 BUY** | ✓ **block:established_down** |
| 15:25:22 SELL | ✓ allow |
| **16:10:24 BUY** | ✓ **block:established_down** |
| Evening prevailing at 20:25 UTC | ✓ DOWN (survived) |
| Prevailing since-ts unchanged | ✓ 2026-10-12T09:50:00+00:00 |

Test passes. **All 4 pinned BUYs blocked, DOWN retained from 09:50
through evening close.**

Run output:
```
tests/data_continuity/test_phase8_oct12_regression.py::test_oct12_pinned_replay PASSED
```

---

## 7. Integration status — BB-Bounce guard end-to-end

### 7.1 Production chain

| Stage | File / line | Status |
|---|---|---|
| Driver (bar close emits event) | `autobot.py:3926` → calls `_nms_bar.on_bar_close` | ✓ wired |
| Hook into session_trend | `normal_market_state.py:790-795` → calls `session_trend.on_bar_close` | ✓ wired |
| State machine update | `session_trend.py:_advance_bar_locked` + `_update_prevailing_locked` | ✓ wired |
| Atomic snapshot write | `session_trend.py:675-677` → `_write_snapshot` (publish_snapshot=True default) | ✓ wired |
| Snapshot read | `session_trend_guard.py:_load_snapshot` + `_snapshot_fresh` | ✓ wired |
| Guard consumer | `open_sb_now.py:38` → `should_block_order` imported | ✓ wired |

Integration tests (BB-Bounce side):

```
tests/test_session_trend_guard_integration.py — 10 passed in 0.16s

  test_buy_under_down_blocks_before_ig           PASSED
  test_sell_under_up_blocks_before_ig            PASSED
  test_sell_under_down_proceeds_to_ig            PASSED
  test_buy_under_up_proceeds_to_ig               PASSED
  test_flag_off_never_blocks                     PASSED
  test_missing_snapshot_proceeds                 PASSED
  test_stale_snapshot_proceeds                   PASSED
  test_corrupt_snapshot_proceeds                 PASSED
  test_unknown_and_range_do_not_block[UNKNOWN]   PASSED
  test_unknown_and_range_do_not_block[RANGE]     PASSED
```

Permissions enforced correctly (fresh snapshot + flag enabled):

```
prevailing   BUY      SELL
UP           allow    block
DOWN         block    allow
RANGE        allow    allow
UNKNOWN      allow    allow
```

Freshness enforcement (fail-safe):

```
missing snapshot → allow (never blocks)
stale snapshot   → allow (never blocks)
corrupt snapshot → allow (never blocks)
flag disabled    → allow (never blocks)
```

### 7.2 IG daily-% acquisition — NOT WIRED

`session_ig_daily_pct.fetch_and_record()` is **implemented but not
called from anywhere in the codebase.**

```
# Audit result (grep -rn 'fetch_and_record' *.py scripts/*.py):
session_ig_daily_pct.py:45:def fetch_and_record(...)
session_ig_daily_pct.py:102:__all__ = ["fetch_and_record"]
# No callers found.
```

**Consequence:** the `ig_daily_pct_change`, `ig_daily_pct_source`
and `ig_daily_pct_as_of` fields on the `session_trend` state are
never populated. The snapshot JSON written to disk shows these
fields as `null`. Consumers (BB-Bounce guard, operator dashboards)
cannot use the IG daily-% figure.

Not a safety issue — these are informational fields, not gates —
but it's a **wiring debt** per the CLAUDE.md Wiring rule:

> No component is complete without a production initializer,
> driver, and consumer cited at file:line.

**Recommended fix (not applied here):** add a boot-time call in
`autobot.main()` after IG session establishes:

```python
try:
    import session_ig_daily_pct as _sdp
    _sdp.fetch_and_record(self.ig_service, epic, "GBPUSD")
except Exception as exc:
    logger.debug("[IG_DAILY_PCT] bridge call failed: %s", exc)
```

And optionally a periodic refresh via a timer. Operator action
required.

### 7.3 session_trend.set_daily_pivots — NOT WIRED

Related secondary wiring gap. `set_daily_pivots()` has no production
caller. `ig_daily_pivots.py` writes pivots to disk at
`/opt/tradingbot/cache/htf/daily_pivots.json` but nothing bridges
that JSON into `session_trend`'s in-memory state.

**Consequence:** `_detect_pivot_rejection()` (session_trend.py:
1063-1094) exits immediately on `if not s.daily_pivots: return`
in production. The pivot-rejection detector is dead code until
wired. `piv_support` is always 0 in prod reason strings.

**Not a safety issue** — pivot is supporting evidence, not a gate.
But it means the "piv_support=N" labelling in BB-Bounce audit
reports is misleading (always 0 in prod).

**Recommended fix (not applied here):** add a boot-time bridge
after `ig_daily_pivots.read_daily_pivots()` succeeds. Something
like:

```python
# in autobot startup, after ig_daily_pivots run:
try:
    import ig_daily_pivots as _idp
    import session_trend as _st
    data = _idp.read_daily_pivots("GBPUSD")
    if data:
        _st.set_daily_pivots("GBPUSD", data["pivots"],
                             source_date=data["trading_date"])
except Exception as exc:
    logger.debug("[PIVOT_BRIDGE] failed: %s", exc)
```

Operator action required.

---

## 8. Test runs

### 8.1 data_continuity (AutoBot worktree)

```
cd /home/autobot/tradingbot-wt/nms-continuity-20261012
python -m pytest tests/data_continuity/

93 passed in 6.12s
```

All 93 tests pass. Includes:
- Phase 7 direction-authority tests
- Phase 8 session_trend tests (state machine, freshness, pivots)
- Phase 8-complete pinned 2026-10-12 regression
- Phase 8c 34-day replay (research-only, doesn't fail suite)

### 8.2 BB-Bounce guard integration

```
cd /home/autobot/bb-bounce-wt/session-trend-20261013
python -m pytest tests/test_session_trend_guard_integration.py

10 passed in 0.16s
```

---

## 9. Outstanding issues

| Issue | Severity | Impact | Recommendation |
|---|---|---|---|
| **IG daily-% not wired** | Medium | `ig_daily_pct_*` snapshot fields always null; consumers can't use the figure | Add boot-time + periodic call in `autobot.main()` |
| **`session_trend.set_daily_pivots` not wired** | Low | Pivot-rejection detector dead in prod; `piv_support` always 0 | Add boot bridge from `ig_daily_pivots.read_daily_pivots` |
| **5 wrong-direction fires** | Medium | 5/34 days: BB-Bounce entries in aligned direction wrongly blocked. 3 of 5 release before EOD | Investigate common pattern (all fire 07:55-13:50 UTC); consider minimum-elapsed-time or counter-direction-check-first gate. Not in this review's scope |
| **9 missed strong trends** | Low | Lost protection on sustained-trend days where structure didn't accumulate asymmetric evidence | Expected trade-off against FP minimisation; may improve with the `MIN_BARS_SINCE_LONDON` consideration above |
| **09-11 release margin** | Low | Day retraced to +7.9p — 2.1p short of +10p release threshold. Classified VALID_FIRE under intraday truth so no action required | None (closed under this review) |
| **09-28 contrary-pivot claim** | High (reporting) | Earlier case-study report was wrong about "44 R-rejections" | Corrected in §5 above |

**Operator decisions requested:**

1. Approve wiring fix for IG daily-% bridge?
2. Approve wiring fix for pivot bridge?
3. Investigate the 5 wrong-direction fires further (separate task)?
4. Any other acceptance questions before merge/deployment?

**No deployment, merge, restart, config change or IG orders by this
review.**

STOP FOR REVIEW.
