# Pivot Integrity Phase 4 Verification — Read-Only Audit

**No code changes. No production modifications. No service restarts. No live orders.**

- Generated: 2026-10-17 (Saturday — FX market CLOSED)
- Research branch: `research/level-arrival-turn-20261017` @ `a7e97cf`
- Production baseline: `nms/v3-prod-upgrade-20261013` @ `41a3c9c`
- Scope: three verification questions from the operator — IG bar-timestamp mapping, older-bar rejection capability, patch applicability.

---

## Headline

1. **Q1 — IG bar timestamp mapping: ESTABLISHED FROM EXISTING REPOSITORY EVIDENCE.** The IG REST payload at 03:00 UTC on day D returns the current-day's **in-progress** bar labelled `snapshotTime=D 00:00`. The last **completed** trading session at that moment is `D-1` (walking back over weekends).

2. **Q2 — Code's current ability to reject an older/in-progress weekday bar: NO.** The research-branch `previous_daily_bar` returns the first weekday bar it finds walking tail-first; it does NOT distinguish an in-progress today-dated weekday bar from the previous completed weekday bar.

3. **Q3 — Patch applicability: PATCH APPLIES CLEANLY as file-replacement**, but is **MATERIALLY INCOMPLETE** — a pre-existing root-cause fix (commits `0f796a2` + `f663e8c` from 2026-10-09) that introduces the `completed_daily_bars(bars_raw, today)` primitive **is NOT in either branch**. Phase 1–4 catches the SYMPTOM (anomalous ratio) but does not filter the in-progress bar at the source.

**GO/NO-GO on the single-file Phase 1–4 patch is downgraded from CONDITIONAL GO to NO-GO pending resolution of the missing-fix finding.**

---

## 1. Q1 — IG bar timestamp mapping

### 1.1 Direct evidence from the saved IG REST payload

File: `/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json`
- `fetched_at_utc = 2026-10-14T03:00:04.613665+00:00`
- `n_bars = 20`
- `latest bar snapshotTime = 2026/10/14 00:00:00` (snapshotTimeUTC = `2026-10-14T00:00:00`)

Observed per-bar ranges by weekday (ASK side):

```
snapshot               weekday     range_p  classification
2026-09-22 Tuesday     66.6
2026-09-23 Wednesday  122.1
2026-09-24 Thursday    52.2
2026-09-25 Friday      54.1
2026-09-27 Sunday      32.0   stub
2026-09-28 Monday      56.5
2026-09-29 Tuesday     53.2
2026-09-30 Wednesday   88.4
2026-10-01 Thursday    92.3
2026-10-02 Friday      74.6
2026-10-04 Sunday      10.5   stub
2026-10-05 Monday      58.0
2026-10-06 Tuesday     84.1
2026-10-07 Wednesday   78.6
2026-10-08 Thursday    64.5
2026-10-09 Friday      44.4
2026-10-11 Sunday      16.4   stub
2026-10-12 Monday      60.1
2026-10-13 Tuesday     60.6   ← LAST COMPLETED SESSION at 10-14 03:00 UTC
2026-10-14 Wednesday   19.0   ← IN-PROGRESS stub at 10-14 03:00 UTC
```

### 1.2 Authoritative confirmation from existing production records (commit log)

Commit `0f796a2` ("fix(pivots): build daily pivots from the last COMPLETED day bar", 2026-10-09T19:36:12+00:00) in the repository documents the mapping **explicitly**:

> *IG's DAY response ends with the current day's in-progress bar. At the 03:00 UTC run previous_daily_bar() returned prices[-1] = 2026-10-09 00:00 (three hours of data, ask H/L/C 13248.7/13226.9/13244.4), so today's GBPUSD pivots were P 13240.0 instead of ~13221.5 from the 10-08 day (13249.2/13184.7/13230.5).*

This is identical to the 2026-10-14 symptom: 03:00 UTC fetch, `prices[-1]` labelled with today's date, OHLC range of 19 p (three-hour stub).

Commit `f663e8c` (2026-10-09T19:44:41+00:00) adds Sunday-dated-bar exclusion to the same primitive.

### 1.3 Established mapping

**At 03:00 UTC on day D, the last COMPLETED trading session is the bar labelled with the previous trading date `D-1_business` (skipping Sat/Sun).**

For the 2026-10-14 03:00 UTC fetch:
- Last completed session = **2026-10-13 (Tuesday)** → `prices[-2]` in the saved payload (range 60.6 p — full weekday session).
- `prices[-1]` labelled `2026-10-14` is the **in-progress Wednesday bar** with ~3 hours of data (range 19 p).

For the (future) Monday 2026-10-19 03:00 UTC fetch (**PENDING MARKET OPEN**):
- Expected `prices[-1]` labelled `2026-10-19` with Monday overnight-stub range.
- Expected `prices[-2]` labelled `2026-10-18` with Sunday stub (10–30 p).
- Expected last completed = `prices[-3]` labelled `2026-10-16` Friday (full session).

**No uncertainty remains on this question.**

---

## 2. Q2 — Can the code reject an older / in-progress weekday bar?

### 2.1 Current research-branch behaviour (`a7e97cf`)

`previous_daily_bar(prices, now_utc=None)` walks the payload tail-first and REJECTS:
- Unparseable date (Phase 4 T1)
- Date > now_utc.date() (Phase 4 T3 — future)
- Saturday-labelled (Phase 4 T3 — defensive)
- Sunday-labelled (Phase 3)

The first weekday bar it finds is RETURNED. **It does NOT distinguish an in-progress today-dated weekday bar from a completed previous-day weekday bar.**

Verified: on the saved 2026-10-14 payload with `now_utc=2026-10-14T03:00`, `previous_daily_bar` returns `prices[-1]` labelled `2026-10-14` (the Wednesday in-progress stub). The regression test `TestSavedPayloadRegressionT2::test_saved_payload_previous_daily_bar_picks_10_14` confirms this behaviour explicitly.

### 2.2 How Phase 4 catches the symptom

Phase 4 T2's `check_sanity_floor` fail-closed path REJECTS the in-progress bar because its range (19 p) is below the min_ratio floor (0.30) against the available-sample average (69 p):

```
TestSavedPayloadRegressionT2::test_saved_payload_sanity_floor_rejects_10_14_bar PASS
→ ok=False, status="below_floor_reduced_sample", ratio=0.274
```

So the END-TO-END pivot write fails on the anomalous bar even though `previous_daily_bar` accepts it. The scheduler's Phase 1 retry fires every 30 min; downstream readers fall back to legacy mid-based pivots.

**This is a workaround, not a root fix.** If the in-progress bar had a range above the ratio threshold (e.g., a wild overnight gap), the current patch would ACCEPT it and compute pivots from an incomplete session.

### 2.3 Pre-existing root fix in the repository (NOT in either branch)

Commits `0f796a2` + `f663e8c` introduce `completed_daily_bars(bars_raw, today)`:

```python
def completed_daily_bars(bars_raw, today):
    """Bars whose snapshot date is BEFORE today (UTC) — i.e. completed
    days. ... Sat/Sun-dated bars are dropped too..."""
    out = []
    for b in bars_raw or []:
        d = _parse_bar_date(b)
        if d is not None and d < today and d.weekday() < 5:
            out.append(b)
    return out
```

Plus the function signatures update: `previous_daily_bar(prices, today=...)`, `check_sanity_floor(bars_raw, ..., today=...)`, `compute_dollar_direction(..., today=...)`. All callers in `run_daily_fetch` / `build_pivots_payload` pass `trading_date` so the "today" filter is active in production.

**Verification that this primitive is reachable from the research-branch tip (`a7e97cf`):**

```
$ git merge-base --is-ancestor 0f796a2 a7e97cf
→ 0f796a2 is NOT reachable from research tip
$ git merge-base --is-ancestor f663e8c a7e97cf
→ f663e8c is NOT reachable from research tip
```

**Both commits are in the repository (`git log --all` shows them) but not in the research-branch's ancestry.** They were authored on a different branch that was never merged into either `nms/v3-prod-upgrade-20261013` or `research/level-arrival-turn-20261017`.

### 2.4 Verification that the production baseline also lacks the fix

```
$ git merge-base --is-ancestor 0f796a2 41a3c9c
→ 0f796a2 is NOT reachable from 41a3c9c
$ git merge-base --is-ancestor f663e8c 41a3c9c
→ f663e8c is NOT reachable from 41a3c9c

$ grep -n 'def completed_daily_bars' /opt/tradingbot/ig_daily_pivots.py
→ (no match)

$ git log --oneline nms/v3-prod-upgrade-20261013 -- ig_daily_pivots.py
2832285 fix(build2): ig_daily_pivots DataFrame-shape handling + view price fallback
915d701 feat(build2): ig_daily_pivots.startup_catch_up
7394e28 feat(build2): ig_daily_pivots — in-process scheduler + sanity floor + BB_BOUNCE DXY
9affa2a feat(build2): ig_daily_pivots — add dollar-direction surface
1920cd0 feat(build2): ig_daily_pivots — IG REST daily bid/ask pivot source
```

Production tip at 2832285 (2026-10-06). The 2026-10-09 `completed_daily_bars` fix was never merged into the production branch.

### 2.5 Answer

**NO — in its current form the research-branch patch does NOT reject an in-progress today-dated weekday bar from `previous_daily_bar`.**
Phase 4's sanity-floor fail-closed catches a NARROW stub by RANGE check — a symptomatic workaround.
**YES — the code CAN be extended to reject such bars**: the pre-existing `completed_daily_bars` primitive on commits `0f796a2` + `f663e8c` is the authoritative pattern. Those commits are in the repository but not merged into either branch under audit.

---

## 3. Q3 — Phase 1–4 patch applies cleanly to production?

### 3.1 Mechanical cleanness (file-replacement)

The research branch's `ig_daily_pivots.py` is a strict descendant of the production baseline's `ig_daily_pivots.py` (merge-base = `41a3c9c`). The diff is entirely contained in that one file; no other production file is touched by Phases 1–4.

```
$ git merge-base 41a3c9c a7e97cf
41a3c9c5302346e4159ae06ef2f4f7ad99a1f935
$ git log --oneline a7e97cf..41a3c9c -- ig_daily_pivots.py
(empty — nothing in production that's not in research)
$ wc -l /tmp/prod_baseline_ig_daily_pivots.py \
         /home/autobot/tradingbot-wt/level-arrival-turn-20261017/ig_daily_pivots.py
926  prod baseline (41a3c9c)
1243 research tip (a7e97cf)
```

**Mechanical conclusion**: file-replacement (copy research-branch `ig_daily_pivots.py` → production path) applies CLEANLY. No merge conflict, no need to touch any other production file. All public-API call sites (callers in `autobot.py`, `session_trend_integration.py`, `bb_pd_gate.py`, `level_ladder.py`, `view_builder.py`) continue to work: new kwargs are optional, existing positional signatures unchanged.

### 3.2 Semantic completeness — **MATERIALLY INCOMPLETE**

The patch applies, but it is MISSING the `completed_daily_bars` primitive from the 2026-10-09 fix. Consequence:

- On any day where IG REST returns an in-progress today-dated bar with a range ABOVE the Phase 4 sanity-floor threshold (0.30 of weekday mean), the pivots would still be computed from the incomplete session. The 10-14 anomaly was caught only because the stub happened to be below the ratio threshold.
- On days with a wider overnight gap, the stub bar could pass the ratio check and silently seed the pivot payload with incomplete session data.

**This is a known defect with a known pre-existing fix.** The research branch's Phase 4 compensates for it indirectly (via the ratio floor) but does not resolve the root cause.

### 3.3 Three options for the operator

| option | action | risk |
|---|---|---|
| **A — Deploy Phase 1–4 as-is** | Single-file replacement. 102 tests pass. Weekend-amplified alert risk mitigated. The 10-14 anomaly is caught by the ratio floor. | **MATERIAL** — an in-progress bar with a non-narrow range (e.g., wild overnight gap) would still slip through. |
| **B — Carry 0f796a2 + f663e8c into the research branch, re-test, then deploy** | Cherry-pick the two commits into a new Phase 5 commit on `research/level-arrival-turn-20261017`. Verify no regressions. Then deploy a (still-single-file) replacement. | **LOW** — resolves the root cause; preserves Phase 1–4 safety nets as defence in depth. |
| **C — Deploy the 0f796a2 + f663e8c fix alone** | Cherry-pick just those two commits onto the production baseline. Skip Phase 1–4. | **MEDIUM** — root cause fixed but no retry, no weekend suppression, no alert dedup, no DataFrame guard. |

### 3.4 Patch applicability answer

- **MECHANICAL**: patch applies cleanly as file-replacement. No merge conflict, no cross-file impact. 102 tests pass against the current research-branch state.
- **SEMANTIC**: patch is incomplete without `completed_daily_bars`. **Option B is strongly recommended** — merge the pre-existing fix FIRST, then layer Phase 1–4 on top.

---

## 4. Unresolved uncertainty

1. **Why commits `0f796a2` and `f663e8c` were not merged into `nms/v3-prod-upgrade-20261013` or `research/level-arrival-turn-20261017`.** Both commits are dated 2026-10-09; the production branch's latest `ig_daily_pivots.py` change is `2832285` dated 2026-10-06. Operators must confirm whether this is:
   - Intentional (the fix was superseded by a different approach we have not identified).
   - Accidental (merge was skipped by mistake).
   - An in-flight branch that was not completed.

2. **Monday 2026-10-19 03:00 UTC live-fetch behaviour** — still PENDING MARKET OPEN. The saved payload is from a Wednesday; a Monday fetch likely has a different `prices[-1]` composition (Sunday stub + Monday overnight stub + Friday full completed).

3. **IG REST session convention for daily-bar session end** — not formally established via IG documentation. The empirical evidence (saved payload) is consistent with:
   - Weekday bar `D` represents the FULL D-day trading session (midnight-to-midnight UTC or NY-close-to-NY-close).
   - At 03:00 UTC on day D, IG REST publishes an INCOMPLETE D-day bar containing only the overnight stub.
   - The last FULLY COMPLETED bar at 03:00 UTC on D is `D-1_business`.

   This interpretation is consistent with commit `0f796a2`'s message and the saved payload. Formal IG documentation would close the uncertainty.

4. **Whether Phase 4's ratio floor (0.30) is strict enough to catch all overnight-stub anomalies.** The 10-14 stub happened to have ratio 0.274 (just below 0.30). A stub with a wider overnight gap could be above 0.30 and pass. **Resolution: merge `completed_daily_bars` as Option B above.**

---

## 5. Boundary statement

- Audit mode: READ-ONLY.
- No code modified in production, research, or any other tree.
- No service restarted.
- No live orders.
- No deployment.
- Three questions from the operator answered with evidence.
- Material finding escalated: the pre-existing `completed_daily_bars` fix (commits `0f796a2` + `f663e8c`, 2026-10-09) was never merged into the production branch OR the research branch. Both branches lack the root-cause fix for IG's in-progress today-dated daily bar.

**Recommendation: STOP deployment of Phase 1–4 pending operator decision between Option A / B / C above. Option B strongly preferred.**

---

## 6. Appendix — Verification commands used

```
# Q1 — Mapping evidence from saved payload
python3 -c "import json; d = json.load(open('/opt/tradingbot/cache/htf/GBPUSD_D1_bid_ask.json')); print(d['fetched_at_utc'], len(d['prices']), d['prices'][-1]['snapshotTime'])"

# Historical commit
git show 0f796a2 --stat
git show f663e8c --stat

# Q2 — Code's current reject capability
grep -n 'def previous_daily_bar\|def completed_daily_bars' \
     /home/autobot/tradingbot-wt/level-arrival-turn-20261017/ig_daily_pivots.py \
     /opt/tradingbot/ig_daily_pivots.py

# Q3 — Patch cleanness + semantic completeness
cd /opt/tradingbot && git merge-base --is-ancestor 0f796a2 41a3c9c
cd /opt/tradingbot && git merge-base --is-ancestor 0f796a2 a7e97cf
cd /opt/tradingbot && git merge-base 41a3c9c a7e97cf
cd /opt/tradingbot && git log --oneline a7e97cf..41a3c9c -- ig_daily_pivots.py

# Diff sizes
wc -l /tmp/prod_baseline_ig_daily_pivots.py \
       /home/autobot/tradingbot-wt/level-arrival-turn-20261017/ig_daily_pivots.py
```

*— end of Phase 4 verification audit —*
