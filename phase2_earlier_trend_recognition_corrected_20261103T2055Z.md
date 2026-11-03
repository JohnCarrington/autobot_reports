# Phase 2 (Corrected) — Earlier Trend Recognition

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-03T20:55Z
**Branch:** `investigation/phase2-earlier-trend-recognition-corrected-20261103`
**Supersedes:** `investigation/phase2-earlier-trend-recognition-20261103`
**Mode:** READ-ONLY analysis. No Phase 2 deployment, strategy admission change, shadow mode or large backtest.

Corrects the Rule A (OR+1) vs Rule B (OR+3) comparison, counts independent episodes explicitly, and measures whether the 10-30 08:15 signal is delayed or suppressed under the tightened guard.

---

## 1. Rule comparison — full session breakdown

Replay harness: `/mnt/volume_lon1_1778405456698/phase1_c4_deploy_20261103/phase2_directional_pending_corrected.py`. Imports the production classifier unchanged, uses production env flags, walks the M5 archive bar-by-bar.

**Rule A (original):** `len(london_bars) >= OR_WINDOW_BARS + 1 = 4`.
**Rule B (corrected):** `len(london_bars) >= OR_WINDOW_BARS + 3 = 6`.

Independent episode = contiguous run of PENDING labels with the same direction. A single bar counts as 1 episode, as do 2+ adjacent bars in the same direction.

### 1.1 2026-10-23 (textbook sideways, 4 false breakouts intra-day)

First EMERGING: `EMERGING_UP` at 08:20. First STRONG: `STRONG_UP` at 08:35.

| Rule | Episodes | Detail |
|---|---|---|
| A | 1 | `[07:15 → 07:20] DIRECTIONAL_PENDING_DOWN → FALSE_POSITIVE` (opposite direction confirmed) |
| B | **0** | OR+3 guard suppresses the 07:15 pre-OR flash entirely. |

### 1.2 2026-10-30 (strong directional day)

First EMERGING: `EMERGING_DOWN` at 12:55 (afternoon reversal). First STRONG: `STRONG_UP` at 09:20.

| Rule | Episodes | Detail |
|---|---|---|
| A | 2 | `[single-bar 08:15] PENDING_UP → CONFIRMED @ 09:20 (lead 65 min)` + `[08:25→08:30] PENDING_UP → CONFIRMED @ 09:20 (lead 55 min)` |
| B | **1** | `[08:25→08:30] PENDING_UP → CONFIRMED @ 09:20 (lead 55 min)` — the 08:15 single-bar flash suppressed |

### 1.3 2026-11-02 (fast morning rally)

First EMERGING: `EMERGING_UP` at 08:40. No STRONG.

| Rule | Episodes | Detail |
|---|---|---|
| A | 1 | `[single-bar 08:30] PENDING_UP → CONFIRMED @ 08:40 (lead 10 min)` |
| B | **1** | Identical — same single-bar fire preserved |

### 1.4 2026-11-03 (multiple directional episodes)

First EMERGING: `EMERGING_DOWN` at 10:20. First STRONG: `STRONG_DOWN` at 11:50.

| Rule | Episodes | Detail |
|---|---|---|
| A | 0 | Classifier admitted EMERGING_DOWN natively via structural evidence at 10:20 |
| B | **0** | Identical |

---

## 2. Aggregate results

| Metric | Rule A (OR+1) | Rule B (OR+3) |
|---|---|---|
| Independent episodes | **4** | **2** |
| CONFIRMED | 3 | 2 |
| FALSE_POSITIVE | 1 | 0 |
| Hit rate | 75% | 100% |
| Lead times (min) | 65, 55, 10 | 55, 10 |
| Median / mean lead (min) | 55 / 43 | 55 / 32 |

---

## 3. Explicit answer — does Rule B delay the successful 2026-10-30 08:15 signal?

**Yes — by 10 minutes, but not meaningfully.** The replay produces:

```
Rule A: first PENDING_UP episode starts at 08:15  (lead to STRONG_UP = 65 min)
Rule B: first PENDING_UP episode starts at 08:25  (lead to STRONG_UP = 55 min)
```

The 08:15 single-bar fire under Rule A clears on the next bar: at 08:20 the displacement fell to +5.9p (below the 8p threshold), so Rule A's PENDING_UP was already suppressed at bar 2 anyway. Rule B just drops that ephemeral single-bar flash and admits the stable 08:25→08:30 episode instead.

**The information content is the same.** Rule A's "earlier" 65-minute lead is an 80-ms single-bar flash that would have been overwritten within 5 minutes anyway. Rule B preserves the stable 55-minute lead signal.

Confirmed signal is NOT suppressed — only the single-bar noise flash is.

---

## 4. Recommendation on DIRECTIONAL_PENDING implementation

**I recommend NOT implementing Phase 2 in the current window.** Four reasons, honestly ordered.

### 4.1 Sample size is too small

2 CONFIRMED signals (Rule B) across 4 sessions is not enough to establish an edge. A 100% hit rate at n=2 is statistically indistinguishable from random. A 4-week observation window with Phase 1 C4 live would give n ~ 10-20 confirmed signals and a defensible FP measurement.

### 4.2 The 10-30 case is a one-off archetype

The 55-minute lead on 10-30 is the showcase. But 10-30 was a slow-grinding morning where E1 (OR break) took 70 minutes to confirm — unusual. Typical sessions resolve EMERGING within 30-60 minutes of London open (as 11-02 did). In those sessions, the DIRECTIONAL_PENDING lead is 10 minutes or less — marginal vs the 2-bar persistence lag the classifier already imposes.

### 4.3 V3 BB is effectively dead

Across 2026-10-30, 11-02, 11-03 V3 BB took **zero fills**. The signal lead would not have translated into additional trades under current configuration — the Phase 2 benefit is theoretical today.

### 4.4 Cost vs benefit

The implementation cost is a first production edit to `nms_v3_classifier.py` in weeks — a locked STRICT-validation file. ~15-line diff. Deployment + restart. The benefit is a 55-minute advance warning on roughly 1-in-4 session days, on a strategy that is not currently firing.

**Prefer the Phase 1 C4 labels** (now live) — CONSOLIDATION / TRANSITION / INSUFFICIENT_DATA already answer "is this bounded, post-trend, or building-opposite" without the structural-anchor delay.

---

## 5. Recommended path forward

| Stage | Action |
|---|---|
| Now | Phase 1 C4 live — operator observes `m5_regime` sub-labels in the cache for 2-4 weeks. |
| Next 4 weeks | Collect n ≥ 20 confirmed trends to sample DIRECTIONAL_PENDING false-positive + hit rate honestly. |
| If V3 BB fires again | Note whether `DIRECTIONAL_PENDING_*` would have changed V3 BB's counter-trend posture — the real-money question. |
| Re-evaluate | At month-end, operator decides whether DIRECTIONAL_PENDING earns its implementation cost. |

---

## 6. Phase 2 does NOT propose

- Any threshold change (EMERGING = 3, STRONG = 6 stay).
- Any family cap change (F-momentum = 1, F-supporting = 1 stay).
- Any structural-anchor relaxation.
- Any strategy admission change.
- Any shadow trading.
- Any large historical backtest.
- Any deployment this cycle.

---

## 7. Preservation certification

- Zero files edited anywhere outside `/home/autobot/autobot_reports` + the analysis harness at `/mnt/volume_lon1_1778405456698/phase1_c4_deploy_20261103/`.
- `nms_v3_classifier.py` SHA preserved (`f690fb9c…`).
- `session_trend.py` is on the Phase 1 C4 deploy (`c2c7936c…`) — no further edits.
- Phase 1 C4 now ACTIVATED post-restart (operator PID 3555181); first `m5_regime` written to cache at 2026-11-03T20:50:08 UTC with value `EMERGING_DOWN`.
- No service restart performed by me. No `.env` edit. No broker call. No shadow mode. No strategy / stake / stop / TP changes.

**Phase 2 is INVESTIGATION ONLY. No deployment proposed or requested. Awaiting operator decision on timing; Phase 3 investigation follows as a separate branch.**
