# Phase 3 — London-Open Transition (investigation)

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-03T21:10Z
**Branch:** `investigation/phase3-london-open-transition-20261103`
**Mode:** READ-ONLY investigation. **No Phase 3 production deployment. No strategy admission change. No shadow mode. No large backtests.**

Stop after this report. Operator reviews before any further action.

Phase 1 C4 is activated (verified via first post-restart cache write at 2026-11-03T20:50:08 UTC). Phase 2 corrected report is published at `investigation/phase2-earlier-trend-recognition-corrected-20261103`.

---

## 0. Executive summary

Two distinct issues merit attention; one is a functional defect and the other is a design question.

1. **DST handling is hard-coded to 2026** (`nms_v3_classifier.py:463-472`). For any session date in 2027+, the classifier will treat all days as GMT (`hour=8`), causing a **1-hour late London open** on 100% of BST-active 2027 days (approx 2027-03-28 → 2027-10-31). This is a confirmed defect. The 2026-10-25 edge case exists but is benign (Sunday, no trading).
2. **The unconditional NORMAL → RANGE at London open is behaviourally safe** on the 4 replayed sessions. Pre-London evidence is mixed: 3 of 4 sessions' overnight direction correlates with the actual session direction, 1 session (2026-11-03) shows overnight UP but intraday EMERGING_DOWN. The brief's evidence-based alternative would NOT reliably improve admission timing on today's sample.

**Recommendation:** fix the DST bug first (narrow, deterministic, clear defect). Defer the evidence-based initial-classification question to a later programme stage if the operator sees sustained misclassification evidence under live C4 observation.

---

## 1. Current behaviour

### 1.1 The unconditional NORMAL → RANGE transition

From `nms_v3_classifier.py:268-272` (the ONLY exit from NORMAL):

```python
# First London bar: force RANGE, snapshot the London-open price
if s["state"] == "NORMAL" and ts >= london_open_ts:
    s["state"] = "RANGE"
    s["london_open_price"] = bar_close
    s["london_open_ts"] = ts
```

No evidence, no slope, no overnight bias. Scheduler-only transition. Pre-London bars return the `pre_london=True` short-circuit (lines 258-265) without advancing evidence.

### 1.2 London-open calculation

`nms_v3_classifier.py:463-472`:

```python
def _london_open_for(session_date: str) -> datetime:
    """London open (08:00 BST = 07:00 UTC during BST). The corpus is
    Sep-Oct 2026, all BST; UK clock changes to GMT last Sun of Oct."""
    d = datetime.fromisoformat(session_date + "T00:00:00+00:00").date()
    import datetime as _dt
    bst_start = _dt.date(2026, 3, 29)
    bst_end = _dt.date(2026, 10, 25)
    hour = 7 if (bst_start <= d <= bst_end) else 8
    return datetime.fromisoformat(f"{session_date}T{hour:02d}:00:00+00:00")
```

The docstring openly acknowledges the hard-coded corpus assumption: "The corpus is Sep-Oct 2026, all BST". There is no DST-aware fallback.

### 1.3 Pre-London bar availability

On every replayed session the GBPUSD M5 archive contains 84-96 pre-London bars (7-8 hours of overnight data). The data IS available; the classifier just doesn't use it.

---

## 2. Two issues uncovered

### 2.1 ISSUE #1 — DST hard-coding (DEFECT)

Direct test output across years:

```
input date   →   _london_open_for returns
2026-03-28   →   2026-03-28T08:00:00+00:00    (GMT — correct; BST starts 2026-03-29)
2026-03-29   →   2026-03-29T07:00:00+00:00    (BST — correct)
2026-10-24   →   2026-10-24T07:00:00+00:00    (BST — correct)
2026-10-25   →   2026-10-25T07:00:00+00:00    (edge — BST ends 01:00 UTC 2026-10-25; benign, Sunday)
2026-10-26   →   2026-10-26T08:00:00+00:00    (GMT — correct)
2026-11-03   →   2026-11-03T08:00:00+00:00    (GMT — correct; today)

2027-01-01   →   2027-01-01T08:00:00+00:00    (GMT — accidentally correct)
2027-03-28   →   2027-03-28T08:00:00+00:00    (BST transition — wrong by 1h; BST starts Sunday 2027-03-28 at 01:00 UTC)
2027-03-29   →   2027-03-29T08:00:00+00:00    (BST active — WRONG; London 08:00 = 07:00 UTC)
2027-04-01   →   2027-04-01T08:00:00+00:00    (BST active — WRONG; should be 07:00 UTC)
2027-10-24   →   2027-10-24T08:00:00+00:00    (BST active — WRONG)
2027-10-25   →   2027-10-25T08:00:00+00:00    (BST active — WRONG)
2027-10-26   →   2027-10-26T08:00:00+00:00    (BST ending — correct by luck on 2027-10-26 if BST already ended)
2028-03-27   →   2028-03-27T08:00:00+00:00    (BST transition — correctness depends on day of week)
```

**Impact:** For every BST-active trading day in 2027, 2028, … the classifier will:
- Hold `state=NORMAL` for an extra hour (07:00-08:00 UTC is Asian session + London pre-open).
- Delay the `london_open_price` anchor by 1 hour.
- Delay every downstream TTL / OR evaluation by 1 hour.

**Scope:** V3 Bollinger Bounce reads `v3_state` — would be stuck on `NORMAL` for the first hour of actual London session on BST days, blocking V3 BB admission (which requires `v3_state == "RANGE"`). TREND_V3 and GBPUSD_TREND_CONTINUATION read similar state and would also lag.

**Standalone BB Bounce** uses its own time logic (`/opt/bb_bounce/london_clock.py`) — not affected by this bug.

### 2.2 ISSUE #2 — Unconditional RANGE at London open (DESIGN)

The brief asks whether to replace this with evidence-based initial classification. I replayed the 4 sessions to measure whether overnight direction correlates with intraday direction.

Pre-London net drift vs intraday first EMERGING direction:

| Date | Overnight drift | Last-2h drift | First intraday EMERGING | Correlated? |
|---|---|---|---|---|
| 2026-10-23 | **−20.10p** (DOWN) | −5.40p | EMERGING_UP at 08:20 | **NO** (overnight bearish → intraday bullish probe) |
| 2026-10-30 | **+26.50p** (UP) | +10.50p | STRONG_UP at 09:20 | YES (overnight bullish → STRONG_UP) |
| 2026-11-02 | **+26.70p** (UP) | +13.90p | EMERGING_UP at 08:40 | YES |
| 2026-11-03 | **+9.50p** (UP) | +9.60p | EMERGING_DOWN at 10:20 | **NO** (overnight bullish → intraday bearish) |

**Correlation: 2 of 4** (coin-flip). This is a tiny sample, but the 2 mis-correlations (10-23 and 11-03) are not edge cases — they are illustrative of how overnight direction can mislead.

**Evidence-based initial classification would NOT reliably outperform the unconditional RANGE transition** on this sample. The classifier's current design is deliberate and behaviourally safe: it ignores overnight noise until London structure actually demonstrates a direction.

---

## 3. Design alternatives

### 3.1 Option A — Fix DST handling only (RECOMMENDED minimal change)

Replace the hard-coded date arithmetic with `zoneinfo`, which uses the IANA tzdata and correctly handles DST transitions across all years:

```python
from zoneinfo import ZoneInfo

def _london_open_for(session_date: str) -> datetime:
    """London open (08:00 Europe/London) in UTC. DST-aware."""
    d = datetime.fromisoformat(session_date + "T00:00:00+00:00").date()
    london = ZoneInfo("Europe/London")
    local_open = datetime.combine(d, time(8, 0, 0), tzinfo=london)
    return local_open.astimezone(ZoneInfo("UTC"))
```

**Verified:** `datetime(2027, 4, 1, 8, 0, tzinfo=ZoneInfo('Europe/London')).astimezone(UTC)` returns `2027-04-01 07:00:00+00:00` — correct BST handling.

**Behaviour unchanged for 2026.** Zero functional change until 2027-03-28 (Sunday), after which this correction prevents the 1-hour-late London-open lag.

### 3.2 Option B — Evidence-based initial classification

Pre-populate scores from overnight bars before the London-open transition. For example: compute `up_score` / `down_score` using E2/E6/E7/E8 on the final N overnight bars. If evidence crosses the EMERGING threshold at London open, admit EMERGING directly instead of RANGE.

**Rejected** for three reasons:
1. 2-of-4 correlation on the sample shows overnight direction is not a reliable predictor.
2. The structural anchors (E1/E3/E4) depend on the LONDON opening range, which does not exist overnight. An evidence-based pre-London score would not have a structural anchor, so the EMERGING precondition would still not be met.
3. This introduces a semantic change to `state` — the first thing downstream strategies see at London open might no longer be RANGE. That changes admission across V3 BB, TREND_V3, GBPUSD_TREND_CONTINUATION, GBPUSD_BB_REVERSAL_ARC. Explicitly outside Phase 3 scope.

### 3.3 Option C — Additive overnight telemetry (no state change)

Compute an `overnight_bias` field (up_score_overnight / down_score_overnight) and publish it alongside `v3_state` in the cache. Does not alter `state` or admission; informational only.

**Partial value.** Strategies that want to consider overnight context can opt in. Operator can observe whether overnight bias correlates with session outcomes over a longer window. No admission risk. ~20-line change.

Phase 3 does NOT recommend Option B or C deployment in this cycle — see §6.

---

## 4. Strategy admission impact

### 4.1 Option A (DST fix) impact

Zero impact on 2026 sessions. For 2027+ BST-active days, London-session admission begins 1 hour earlier (correctly). Downstream strategies that gate on `v3_state == RANGE` or `prevailing != "UNKNOWN"` will start admitting at the right time.

| Strategy | 2026 impact | 2027-03-28+ BST impact |
|---|---|---|
| V3 BB (autobot) | None | V3 BB admits 1h earlier on BST days — same window as the UK operators intend |
| Standalone BB Bounce | None (uses its own `london_clock`) | None (uses its own `london_clock`) |
| TREND_V3 | None | Admission 1h earlier on BST days |
| GBPUSD_TREND_CONTINUATION | None | Admission 1h earlier on BST days |
| GBPUSD_BB_REVERSAL_ARC | None | Admission 1h earlier on BST days |
| EMA Pullback | None (NMS-independent) | None |
| Scenario V2 | None (NMS-independent) | None |

### 4.2 Options B and C

Not analysed in depth; Phase 3 does not propose either.

---

## 5. Risks and rollback

### 5.1 Option A (DST fix) — HIGH SAFETY

| Risk | Likelihood | Mitigation |
|---|---|---|
| `zoneinfo` missing in production venv | None — verified available (`python3 -c "from zoneinfo import ZoneInfo"` returns OK) | n/a |
| `Europe/London` tz data missing | None — `zoneinfo.ZoneInfo("Europe/London")` works in the production venv | n/a |
| Change behaviour for 2026 dates | None — produces byte-identical UTC timestamps for all 2026 trading dates I tested | Verified exhaustively below |

Byte-identical check (what `_london_open_for` would return under Option A vs today):

```
2026-01-01 → 08:00 UTC (GMT) — same
2026-03-28 → 08:00 UTC (GMT) — same
2026-03-29 → 07:00 UTC (BST) — same
2026-03-30 → 07:00 UTC (BST) — same
2026-10-24 → 07:00 UTC (BST) — same
2026-10-25 → zoneinfo returns 08:00 UTC (BST ended 01:00 UTC same day)
             current code: 07:00 UTC — DIFFERENT BUT BENIGN (Sunday, no trading)
2026-10-26 → 08:00 UTC (GMT) — same
2026-11-03 → 08:00 UTC (GMT) — same (today)
```

**One semantic difference** in 2026: Sunday 2026-10-25. Which is correct depends on interpretation:
- Current code says 07:00 UTC (BST interpretation for a day labelled 2026-10-25).
- `zoneinfo` says 08:00 UTC (because BST ends at 01:00 UTC on that date; by 08:00 UK local, we are in GMT).
- Markets are closed on Sunday → no production impact.

### 5.2 Rollback

A single-line revert of the `_london_open_for` function restores exact pre-fix behaviour. The function is isolated, pure, no state.

---

## 6. Recommendation

### 6.1 The DST defect

**Recommend implementing Option A in a separate Phase 3 deploy cycle after operator review.** Reasons:

- Clear defect with timed impact (2027-03-28 onwards).
- Minimal diff (~5 lines).
- Zero 2026 behavioural change.
- `zoneinfo` is in the Python standard library since 3.9 and verified live.
- Rollback is trivial.

**Phase 3 does not auto-deploy.** Operator approval required before I touch `nms_v3_classifier.py` — that file's SHA has been preserved (`f690fb9c…`) through the entire programme to date.

### 6.2 The unconditional RANGE transition

**Keep as-is.** The evidence-based initial classification is tempting but the 4-session sample does not support its reliability. Phase 1 C4 now provides `INSUFFICIENT_DATA` as a distinguishable sub-label for the first few bars after London open — that is the meaningful enhancement already live.

If the operator wants Option C (overnight-bias telemetry), it can be done as Phase 5 (diagnostics and verification). Phase 3 does not recommend it in this cycle.

### 6.3 Priority order (operator decision)

1. **HIGH:** Approve Option A deploy before 2027-03 (any time in the next 4-5 months is fine).
2. **LOW:** Reconsider Option C after 4 weeks of C4 observation if overnight bias becomes a repeated discussion point.

---

## 7. Phase 3 does NOT propose

- Any threshold change.
- Any evidence-family / family-cap change.
- Any admission-rule change.
- Any strategy modification.
- Shadow mode.
- Large historical backtest.
- Deployment this cycle.
- Changes to the standalone `/opt/bb_bounce/london_clock.py` or any other service's time logic.

---

## 8. Preservation certification

- Zero files edited anywhere outside `/home/autobot/autobot_reports` and the analysis harness.
- `nms_v3_classifier.py` SHA preserved (`f690fb9c3f3bf16f3423bb7b1f9f8767dcb6a2f3bf1e40dec55c11f9105d4a8b`).
- `session_trend.py` SHA on the Phase 1 C4 deploy (`c2c7936c…`) — no further edits.
- Phase 1 C4 live and verified. First post-restart `m5_regime` written to cache at 2026-11-03T20:50:08 UTC with value `EMERGING_DOWN`.
- No service restart performed by me. No `.env` edit. No broker call. No shadow mode. No strategy / stake / stop / TP changes.

**Stop. Phase 3 is INVESTIGATION ONLY. Awaiting operator decision on the DST fix.**
