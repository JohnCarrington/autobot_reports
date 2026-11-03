# Addendum A — Event-definition audit + QM/AM/V2 Pick evaluation

**Branch:** `research/gbpusd-pivot-pivot-20261103`
**Base commit:** `fb99c98` (all 8 original phases)
**Scope:** audit the original event definitions and evaluate the deployed structural-reversal mechanisms (QM reversal detector, AM pick alerts, V2 Pick) against the operator's follow-up brief.

**Headline.** The original Phase 2 analysis counted **touches**, not **approaches**. Under a proper pre/at/post-overshoot classification, **85-95% of approaches to S2/R2/S3/R3 reverse before actually touching the pivot**. The original reach-matrix was conditional on a 5-15% subset. QM reversal signals (the only deployed mechanism with concrete entries) produce 48.5% raw win rate at 1R / −1.7p mean after 1.5p spread, but a session filter (LondonOpen + LondonMorning + LN/NY overlap only) lifts win rate to 79% and mean to +3.3p/trade over 19 resolved trades. V2 Pick is DISABLED in production (`V2_PICK_BOUNCE_ENABLED=0`).

## A1 — Event-definition audit

### Critique of the original (Phase 2) definitions

- An event required `bar.low <= pivot <= bar.high` (a touch). Approaches that reversed without the bar straddling the pivot were **invisible** to the analysis.
- `breakout_flag = 1` fired on `max_high_next_15bars >= pivot + 10p`. A single 1-bar wick 10p+ above the pivot followed by a hard reversal set `breakout_flag=1` — exactly the stop-sweep pattern the operator flagged.
- Reject threshold (10p / 15 bars) and breakout threshold (10p / 15 bars) were fixed. No sensitivity testing.

### Rebuilt classification

Four pre-registered outcome classes over a 30-bar hold horizon:

| Class | Rule |
|---|---|
| `PRE_PIVOT_REVERSAL` | Price enters within 15p of pivot but bar never straddles pivot; then moves ≥15p away in the opposite direction. |
| `AT_PIVOT_REVERSAL` | Bar straddles pivot, max overshoot < 3p, then max reverse excursion ≥5p. |
| `STOP_SWEEP_REVERSAL` | Bar straddles pivot, max overshoot ≥ 3p, no 2 M5 closes ≥3p past pivot, then max reverse excursion ≥5p. |
| `CONFIRMED_BREAKOUT` | Bar straddles pivot AND at least 2 closes in the hold window ≥3p past pivot AND reaches ≥10p past pivot. |
| `WICK_UNCONFIRMED` | 1 close past pivot but not 2. |
| `STALL` | Everything else. |

Sensitivity-tested against LOOSE (10p / 2p / 1 bar) and STRICT (20p / 5p / 3 bars) grids — dominant class share stable to within ±10 points.

### Headline numbers (S2/R2/S3/R3, BASE thresholds, 2024-2025 BID + 2026 Jan-Feb MID, n = 2,085 approach events across the 7 pivots)

| Pivot | n approaches | PRE_PIVOT_REVERSAL | STALL | CONFIRMED_BREAKOUT | STOP_SWEEP | AT_PIVOT_REVERSAL |
|---|---:|---:|---:|---:|---:|---:|
| S2 | 208 | **85.6 %** | 7.2 % | 5.3 % | 1.9 % | — |
| R2 | 215 | **84.7 %** | 11.6 % | 2.8 % | 0.5 % | 0.5 % |
| S3 | 116 | **94.0 %** | 2.6 % | 1.7 % | 1.7 % | — |
| R3 | 133 | **95.5 %** | 2.3 % | 1.5 % | — | 0.8 % |

Sensitivity grid (CONFIRMED_BREAKOUT share only):

| Pivot | LOOSE | BASE | STRICT |
|---|---:|---:|---:|
| S2 | 10 % | 6 % | 3 % |
| R2 | 6 % | 3 % | 2 % |
| S3 | 4 % | 2 % | 2 % |
| R3 | 3 % | 2 % | 1 % |

### Interpretation vs the original Phase 2

The Phase 2 reach-matrix (eg. "`S3 DOWN → S2` at 62 %") was conditional on **having touched** S3. That touch is the rare event: only 5-15 % of approaches get there. If the operator question is *"does price reach S2/R2/S3/R3 on a given day?"*, the honest answer is **~5-15 %, driven by the approach-reversal rate**.

The Phase 2 finding — *"once price has committed to a pivot, it rarely stops there"* — still holds within its conditional domain. It remains a useful statistic for admission policy at the moment a touch has already occurred. What it does NOT support is treating the touch as a frequent event.

### Stop sweeps specifically

Stop-sweep reversals (wick past pivot, no confirmed close, reversal) are **≤2 %** of approach events at every tested pivot/threshold. This is NOT a frequent pattern in the dataset. If the operator believes stop sweeps happen more often than this, the discrepancy likely sits at **sub-M5 timeframes** (M1 or ticks) or **at liquidity levels other than daily pivots** (session H/L, prior-swing lows, round numbers). Both are out of scope here.

## A2 — QM reversal signals (deployed mechanism)

**Source.** `/opt/tradingbot/logs/qm_reversal_signals.jsonl` — 183 signals total (4 pairs) emitted by `qm_reversal_detector.py` since 2026-10-19. GBPUSD subset: **43 signals** across 14 trading days ending 2026-11-03. All emit entry_price + stop_price + stop_distance_pips at trigger time.

### Overall outcomes (1.5p round-trip spread, 1R rule TP=stop_distance / SL=stop_distance)

| Metric | Value |
|---|---|
| GBPUSD signals | 43 |
| Entry feasible (price revisited entry) | 37 / 43 (86 %) |
| Blocked by NMS v3 | 7 (16 %) |
| 1R resolved intraday | 33 |
| Wins | 16 (**48.5 %**) |
| Total net pips | **−54.5** |
| Mean net pips / trade | **−1.7** |
| 2R resolved | 32 |
| Wins | 9 (28.1 %) |
| Mean net pips / trade (2R) | **−2.9** |

Raw QM outcomes are around break-even on win rate (48.5%), negative after spread (−1.7p / trade). On a 2R target they are clearly losing (28.1% win).

### Nearest-pivot concentration

QM signals cluster near the inner pivots P / S1 / R1 (34 of 43 = 79 %). Rarely near S2 / R2 (5) or S3 / R3 (4). This matches the Phase 2 observation that extreme pivots are rarely touched.

### Win rate by nearest pivot (1R, feasible+resolved)

| Nearest | n | win % | mean net |
|---|---:|---:|---:|
| P  | 10 | 60 % | +0.5 p |
| S1 |  8 | 50 % | −1.9 p |
| S2 |  4 | 50 % | −2.0 p |
| R1 |  7 | 29 % | **−4.5 p** |
| R2 |  1 | 0 %  | −8.6 p |
| R3 |  3 | 67 % | +1.4 p |

**R1-nearest QM signals (n=7) are the worst-performing pivot subset**, consistent with Phase 2's finding that R1 UP is a coin-flip event at best.

## A3 — Time of day and remaining capacity

### Win rate by London session (1R, feasible+resolved; Oct-Nov 2026 UK winter, UTC = UK local)

| Session | n | wins | win % | total net | mean net |
|---|---:|---:|---:|---:|---:|
| LondonOpen (07-09 UTC) | 5 | 4 | **80 %** | +14.4 p | +2.9 p |
| LondonMorning (09-12 UTC) | 4 | 4 | **100 %** | +23.1 p | +5.8 p |
| LN/NY overlap (12-16 UTC) | 10 | 7 | **70 %** | +24.3 p | +2.4 p |
| LateNY (16-22 UTC) | 8 | 0 | **0 %** | **−76.8 p** | **−9.6 p** |
| Asia / off-session | 6 | 1 | 17 % | −39.5 p | −6.6 p |

**The entire sample's losses live in LateNY + off-session.** Filter to the LN-NY active window (LondonOpen + LondonMorning + LN/NY overlap) and the signal looks like this:

| Subset | n | wins | win % | total | mean |
|---|---:|---:|---:|---:|---:|
| Active-session only | 19 | 15 | **78.9 %** | **+61.8 p** | **+3.3 p** |

That's a materially positive edge after spread on 19 trades — but 19 trades is a small sample. Binomial 95% CI on 78.9%: roughly [60%, 90%].

### Signal side

| Side | n | wins | win % | mean net |
|---|---:|---:|---:|---:|
| BUY  | 17 | 10 | 58.8 % | −0.1 p |
| SELL | 16 |  6 | 37.5 % | **−3.3 p** |

SELL signals do worse in this window. The window was a GBP-strong period (pair ~1.325 → ~1.345) — SELL reversal signals were counter-trend.

### NMS gate passed vs blocked

| Subset | n | win % | mean net |
|---|---:|---:|---:|
| NMS allowed | 26 | 50 % | −1.3 p |
| NMS blocked | 7 | 43 % | −3.1 p |

Blocked signals have been slightly worse in this sample but not strongly discriminating — NMS blocking is not clearly adding value on QM signals in this window (sample too small to conclude).

## A4 — Practical trade outcomes

Trades measured strictly: *entry level actually crossed* AND *stop was not hit before target*. Targets are NOT credited simply because price "eventually reached" the predicted direction.

- Raw QM outcomes at 1R: **48.5 % win, −1.7p/trade mean** (n=33).
- Session-filtered (active window only): **78.9 % win, +3.3p/trade mean** (n=19).
- 2R rule: raw 28 %, session-filtered would need n=19 recomputed — small-sample.
- Entry feasibility was high (86 %) — price does revisit the trigger level in most cases. The constraint is time-of-day + stop hitting first.

**Translation.** The QM reversal detector appears to have a usable edge if (and only if) its emissions are restricted to the LN-NY active trading window. The sample is small (19 active-window resolved trades) and the window is a specific 14-day regime (2026-10-19 → 2026-11-03). Needs replication on a longer window before any production action.

## A2b — AM pick alerts and V2 Pick

### AM (`qm_pick_alerts.py`)

- Module is **shadow telemetry only** per the file docstring. Sends Telegram alerts when a `qm_decision_shadow` candidate reaches an actionable state. **No deployed trade entry** attaches to these alerts.
- Journal `logs/qm_pick_alerts_seen.jsonl` (473 rows total) — GBPUSD-range subset ~202 alerts across 88 London / 92 NY / 12 Asia / 10 Late sessions. Direction balanced 100 BUY / 102 SELL.
- Because the alerts carry no entry/stop, we cannot measure practical trade outcomes against them on the same methodology as QM signals. Any evaluation would require imposing a hypothetical entry rule, which crosses the line from measurement into strategy construction.

### V2 Pick (`qm_decision_shadow` → V2_PICK_BOUNCE family)

- Flag check: `grep V2_PICK_BOUNCE_ENABLED /opt/tradingbot/.env` → `V2_PICK_BOUNCE_ENABLED=0`.
- `nms_reversal_oracles.v2_pick_reversal_evidence` (`:169-180`) is a placeholder returning `None` for this reason.
- There are **no live V2 Pick signals** to evaluate. The system exists in the code path but is disabled at the master switch.

## A5 — Combined findings vs the operator's questions

**1. Did the original research understate reversal frequency because of its event definitions?**

Yes. The original Phase 2 counted touches (bar straddles pivot) — not approaches. Under a proper pre/at/post-overshoot classification, **85-95% of approaches to S2/R2/S3/R3 reverse BEFORE touching** the pivot. The original reach-matrix numbers (e.g. "R3 UP → R2 at 59%") remain valid within their conditional domain (given touch), but describe a 5-15% subset of approach events. If the operator's intent was "does price reach S3 as a destination?", the honest answer is **~5-15%**, dominated by the pre-touch reversal class, not the 60% reach-rate stated earlier.

**2. Do QM reversal signals, filtered by session timing + remaining capacity, improve continuation-vs-reversal prediction?**

In this 14-day window: **yes**, QM reversal signals restricted to LondonOpen + LondonMorning + LN/NY overlap show 78.9% win rate / +3.3p mean net / +61.8p total over 19 resolved trades at 1R after 1.5p spread. **Unfiltered**, the signal is slightly negative (48.5% / −1.7p). **LateNY alone** is catastrophic (0% win / −9.6p mean).

CIs are wide at this sample size. The direction of the finding is consistent with the Phase 4 (original) session gradient result: pivot-adjacent decisions are much more decisive in the LN-NY active window than in LateNY or Asia.

**3. Does the existing research understate stop sweeps?**

Not in the metric defined here. Only ~2% of approach events at S2/R2/S3/R3 are STOP_SWEEP_REVERSAL under BASE thresholds. If stop sweeps are observed more often in practice, they likely occur at (a) sub-M5 resolution, (b) non-pivot liquidity levels (session H/L, swing lows, round numbers), or (c) pivots we didn't audit (S1/R1 inner pivots which were out of this follow-up's scope).

**4. What should NMS do differently given this?**

Nothing in this addendum changes the Phase 8 recommendation set:
- **#1 Pivot-destination assessor remains valid** — but its effect size is smaller than Phase 2 suggested because the touch itself is rare. The stronger case is a **"pivot approach reassessment"** trigger that fires at the 15p proximity, not only at touch.
- **#2 Session-conditional NMS sensitivity remains the strongest-evidence recommendation.** A2 (QM signals) adds to the Phase 4 evidence: LateNY structural signals carry materially different outcome distributions.
- **V2 Pick should NOT be enabled** on the strength of this data — it is currently disabled (`V2_PICK_BOUNCE_ENABLED=0`) and has no signal stream to evaluate. Enabling it would be an experiment, not a deploy.

## Caveats

- 43 GBPUSD QM signals / 33 resolved is a small sample. Session-filtered n=19 is smaller still. Any production decision based on this needs replication on a longer QM signal history (the journal starts 2026-10-19).
- Bid/ask spread assumed fixed at 1.5p. Actual DEMO spread during signal moments may be wider at session opens or scheduled-news windows.
- Historical outcome is on MID candles (2026 live-captured) — the certified tick archive ends 2026-03-31 and does not cover this window.
- 2R outcomes are reported for context but are not the dominant exit rule for the deployed detector (which uses `QM_REVERSAL_TP_RULE=STRUCT` — structural targets, not fixed R multiples). The 1R/2R numbers are a simple sanity frame, not the actual deployed strategy's P&L.
- `nms_v3_allowed` field is inconsistently populated (some signals have `nms_v3_gate_disabled` in reason_codes but `nms_v3_allowed=true`) — the "blocked" subset is best interpreted as "would have been blocked under the v3 gate," not "was blocked from entering."

## Reproducibility

- `scripts/addendum_a1_event_classes.py` — rebuilt event classifier + sensitivity grid.
- `scripts/addendum_a2_qm_outcomes.py` — QM signal ↔ pivot ↔ price outcome overlay.
- `csv/addendum_a1_events.csv` — 2,085 approach events across 7 pivots.
- `csv/addendum_a2_qm_outcomes.csv` — 43 GBPUSD QM signal outcome rows.

No production files modified. No shadow mode. No broker orders.
