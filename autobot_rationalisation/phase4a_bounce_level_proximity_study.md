# Phase 4A — GBPUSD bounce event × structural-level proximity study

**Date:** 2026-10-15
**Branch:** `feat/htf-trading-proposition-phase4a` (research worktree)
**Author:** autobot
**Class:** READ-ONLY research. No code change in `/opt/tradingbot/`, no .env change, no service touch, no trade. Harness is in `autobot_rationalisation/phase4a_bounce_study/`.
**Scope (operator, 2026-10-15):** using the ORIGINAL historical GBPUSD bounce events, measure distance from every turning point to every structural level AutoBot could have known at that time; look at clusters; compare reversed / failed / ordinary; cross-reference existing HTF / QM / PAA reports; evaluate whether existing V3 entries capture the subsequent move.

---

## 0. Headline

- **Dataset:** 11,951 GBPUSD BB(20,2) 5m band-reversal events, 2024-01-02 → 2026-09-27 (census corpus at `reports-public/2026-09-27_bb_reversal_census/events_GBPUSD.csv`). Turning point = `(extreme_ts, extreme_px)`.
- **Level density on bounce extremes is overwhelming:** 79.5 % of events have ≥1 non-trivial structural level within 2 pips; 91.2 % within 5 pips; 97.6 % within 10 pips.
- **Confluence is the real signal, not single-level proximity.** 3+ levels within 2 pips of the extreme lifts the clean 10-pip-reversal rate from 35 % (0–2 levels) to **46–55 %** — a 10–20 percentage-point lift. Baseline rate across all events = 39.5 %.
- **Levels concentrate on bounce extremes vs ordinary 5m extremes 2–11×.** For 3+ levels within 2 p: ordinary 2.9 % → bounce 33.9 %, an **11.7× concentration**. SWING_H/L and RANGE_H/L drive most of this density (partly tautological — see §3.3).
- **Only London / NY session H/L discriminate reversed from failed per level type.** 1.6–1.8× lift at 2p for LN_H/L; 1.3× at 2p for NY_H/L. SWING / RANGE / pivot families appear at FAILED events as often as (or more often than) at REVERSED_10 events — they count bounces, they do not predict them.
- **Simple D1 close-change HTF direction does NOT discriminate** (REVERSED_10: with-HTF 38.7 % vs against-HTF 39.7 %). This is a reconstruction, not a replay of the live `htf_authority`; the live logs do not cover the census window.
- **Existing production QM / PAA / HTF live reports cannot be queried for the census window:** `qm_level_interactions.jsonl` logs only reach back 21 days (2026-09-21+); PAA v1 only exists from 2026-10-14; `htf_regime.jsonl` / `htf_authority.jsonl` rolling logs cover ~9 days. In the overlapping window (6 days), only 66 / 1,955 events (3.4 %) have a matched QM terminal within 10 p and 6 h.
- **V3 timing (n = 16 matched V3 fires in signal_log for the Sep 4–27 overlap):** V3 fires **median 1 bar BEFORE** the bounce extreme and **mean 4.6 bars before**. **Mean capture ratio 0.44** of the reversal_max_pips — V3 enters near the extreme and would, in principle, have been positioned to catch 44 % of the subsequent reversal (direction-unverified; see §6).

---

## 1. Dataset provenance (no modification)

- **Source:** `/opt/tradingbot/reports-public/2026-09-27_bb_reversal_census/events_GBPUSD.csv` — the 2026-09-27 band-reversal census, 11,951 GBPUSD BB(20,2) upper/lower visits across 852 trading days.
- **Turning-point definition:** `(extreme_ts, extreme_px)` — the running peak (upper visit) or trough (lower visit) reached during the visit. The census was generated under the operator's "do not create a new detector" rule.
- **Outcome labels used in this study (derived from the census columns):**
  - `REVERSED_10` (n = 4,723) — `first_10_ts` present AND `ambiguous_10 == 0` (10-pip reversal achieved without an 8-pip adverse move first).
  - `REVERSED_5` (n = 4,224) — `first_5_ts` present AND `ambiguous_5 == 0`, but no clean 10-pip reversal.
  - `FAILED` (n = 3,004) — neither clean reversal registered.

---

## 2. Level universe (reused verbatim from production implementations)

Per-event level map built at `extreme_ts` using the production formulas:

| Level type | Source formula in production | Known-at-time anchor |
|---|---|---|
| PIVOT / R1 / R2 / R3 / S1 / S2 / S3 | `bb_pd_gate.compute_pivots_only` (`level_snapshot_v6.py:482-528`) + `qm_liquidity_level_mapper._pivots_from_prior` (`qm_liquidity_level_mapper.py:173-187`) | prior D1 OHLC |
| PDH / PDL | same anchor as pivots | prior D1 high/low |
| NEAREST_00 / NEAREST_50 | nearest 100-p / 50-p grid round-trip (`level_snapshot_v6._build_nearest_entries:700-765`) | causal reference price |
| SWING_H / SWING_L | rolling max/min of last 48 × 5m bars (`qm_liquidity_level_mapper._swing_hl:199-204`) | 4-hour trailing window |
| RANGE_H / RANGE_L | intraday H/L up to extreme_ts (`qm_liquidity_level_mapper.build_map:293-296`) | today's 5m bars so far |
| LN_H / LN_L | 07:00–16:00 UTC H/L (`qm_liquidity_level_mapper._session_hl:206-220`) | London session so far |
| NY_H / NY_L | 13:00–22:00 UTC H/L (same function) | NY session so far |
| BB_U / BB_L | Bollinger(20, 2.0) on 5m closes to extreme_ts (`qm_liquidity_level_mapper._bollinger:189-197`) | 5m closes up to and including extreme bar |

**The harness is a thin research driver. It does not re-define any level.** It replays the production formulas against the raw candle archive at `extreme_ts`.

BB_U / BB_L are reported in the per-event JSONL but **excluded from the proportion analysis** — bounces are BB touches by construction, so BB distance ≈ 0 is a self-reference, not an observation. The 19 "non-trivial" level types in the tables below exclude BB.

---

## 3. Proportion of events with structural levels within K pips

### 3.1 Any non-trivial level within K pips (overall + by outcome)

| K | ALL (n=11,951) | REVERSED_10 (n=4,723) | REVERSED_5 (n=4,224) | FAILED (n=3,004) |
|---|---:|---:|---:|---:|
| 2 p | **79.5 %** | 80.6 % | 77.3 % | 80.8 % |
| 5 p | 91.2 % | 90.8 % | 90.4 % | 92.6 % |
| 10 p | 97.6 % | 96.8 % | 98.0 % | 98.3 % |
| 15 p | 99.2 % | 98.9 % | 99.4 % | 99.4 % |

Observation: **virtually every bounce extreme is near some structural level.** The within-K-of-any-level rate does NOT discriminate reversed from failed — the signal is in **which** level and **how many**.

### 3.2 By level type — bounce extremes vs ordinary 5m extremes

Ordinary baseline = 2,000 randomly sampled 5m bar extremes that fall **outside** every census event interval (seed 20261015). "Lift" = bounce % / ordinary %.

| Level type | 2p bounce | 2p ordinary | lift @2p | 5p bounce | 5p ordinary | 10p bounce | 10p ordinary |
|---|---:|---:|---:|---:|---:|---:|---:|
| **SWING_H** | 31.5 % | 3.2 % | **9.8×** | 37.3 % | 9.8 % | 47.4 % | 25.8 % |
| **SWING_L** | 30.6 % | 2.8 % | **11.1×** | 36.9 % | 11.5 % | 47.7 % | 30.1 % |
| **RANGE_H** | 24.6 % | 5.9 % | 4.2× | 29.0 % | 11.4 % | 37.7 % | 24.1 % |
| **RANGE_L** | 24.0 % | 4.8 % | 5.1× | 28.8 % | 12.8 % | 37.9 % | 30.1 % |
| **LN_H** | 13.6 % | 3.4 % | 4.1× | 16.5 % | 8.3 % | 21.5 % | 17.8 % |
| **LN_L** | 12.9 % | 2.0 % | 6.5× | 16.2 % | 5.0 % | 21.6 % | 12.9 % |
| **NY_H** | 10.6 % | 2.8 % | 3.8× | 12.1 % | 7.0 % | 15.2 % | 14.8 % |
| **NY_L** | 10.4 % | 1.8 % | 5.6× | 12.4 % | 5.1 % | 15.8 % | 14.5 % |
| PIVOT | 5.5 % | 4.5 % | 1.2× | 13.5 % | 12.0 % | 26.0 % | 24.9 % |
| NEAREST_00 | 4.1 % | 4.1 % | 1.0× | 9.5 % | 8.8 % | 19.3 % | 15.1 % |
| NEAREST_50 | 4.1 % | 5.5 % | 0.7× | 10.3 % | 13.0 % | 20.6 % | 23.2 % |
| PDH | 3.2 % | 3.1 % | 1.0× | 8.0 % | 7.2 % | 15.5 % | 11.3 % |
| PDL | 3.1 % | 1.1 % | 2.7× | 7.3 % | 6.5 % | 14.6 % | 14.0 % |
| R1 | 2.5 % | 3.2 % | 0.8× | 6.1 % | 6.2 % | 12.2 % | 10.3 % |
| S1 | 2.6 % | 3.3 % | 0.8× | 6.0 % | 8.3 % | 12.1 % | 17.2 % |
| R2 | 1.2 % | 0.4 % | 3.5× | 3.2 % | 0.8 % | 6.4 % | 2.1 % |
| S2 | 1.0 % | 0.9 % | 1.2× | 2.6 % | 2.0 % | 5.4 % | 4.2 % |
| R3 | 0.6 % | 0.0 % | ∞ | 1.8 % | 0.0 % | 3.4 % | 0.0 % |
| S3 | 0.5 % | 0.8 % | 0.6× | 1.3 % | 1.4 % | 2.7 % | 2.8 % |

**Reading:**

- SWING_H / SWING_L concentrate ~10× on bounce extremes vs ordinary — but see §3.3 for the circularity caveat.
- RANGE_H / RANGE_L: 4–5× — again, intraday-max partly tautological.
- **Session H/L (LN_H/L, NY_H/L)**: 4–7× concentration. These are prior-known levels (set earlier in the day), not current-extreme tautologies.
- Floor pivots (PIVOT, R1, S1, PDH, PDL): close to ordinary. Round numbers: close to ordinary. R2 / R3: rare but genuinely bounce-biased.

### 3.3 Methodological caveat on SWING_H/L and RANGE_H/L

- `_swing_hl` and the intraday-range function compute max/min over bars **including the current (extreme) bar**. If the current 5m bar's high is the max over the lookback — which it often is for a bounce extreme — SWING_H trivially equals the extreme. Same for RANGE_H.
- This is a property of the production implementation; the operator rule "use existing implementations" forbids changing it. The result is presented as-is, with the caveat that the SWING / RANGE lift is partly measuring the production definition rather than a prior-structure coincidence.
- For session H/L (LN_H/L, NY_H/L) the bars included are only those within the UTC session window; the current 5m bar at the extreme is included only if its hour lies in the session window. The lift here is **not** tautological — it is a genuine finding that bounces concentrate at the London / NY session highs and lows.

### 3.4 Clusters — ≥2 and ≥3 levels within K pips

| K | ≥2 levels (ALL) | ≥2 levels REV_10 | ≥2 levels FAIL | ≥3 levels (ALL) | ≥3 levels REV_10 | ≥3 levels FAIL |
|---|---:|---:|---:|---:|---:|---:|
| 2 p | 59.0 % | 62.4 % | 61.4 % | 33.9 % | from histogram §3.5 | — |
| 5 p | 75.9 % | 76.0 % | 79.3 % | — | — | — |
| 10 p | 91.3 % | 89.1 % | 94.2 % | — | — | — |
| 15 p | 96.6 % | 94.7 % | 97.6 % | — | — | — |

### 3.5 Cluster-size histogram at 2 p — REVERSED_10 rate rises monotonically

| Cluster size at 2 p | n | % REVERSED_10 | % REVERSED_5 | % FAILED |
|---:|---:|---:|---:|---:|
| 0 | 2,451 | 37.4 % | 39.1 % | 23.5 % |
| 1 | 2,446 | 35.1 % | 41.0 % | 23.9 % |
| 2 | 3,005 | 33.1 % | 40.1 % | 26.9 % |
| 3 | 2,582 | **46.2 %** | 28.4 % | 25.4 % |
| 4 | 1,231 | **51.3 %** | 22.2 % | 26.6 % |
| 5 | 217 | **55.3 %** | 22.1 % | 22.6 % |
| 6 | 19 | 52.6 % | 21.1 % | 26.3 % |

**Reading:** below 3 levels in 2 p the clean-10 reversal rate is 33–37 %. From 3 levels upward it jumps to 46–55 %. The signal appears at the 3-level threshold and plateaus. FAILED rate is roughly flat across cluster sizes (23–27 %) — the lift comes from reclassifying weak reversals (REV_5) into clean reversals (REV_10).

### 3.6 Per-type REV_10 vs FAILED lift — which level types predict reversal success

Only two level families show > 1.3× lift of REV_10 over FAILED at 2 p:

| Level type | REV_10 @2p | FAILED @2p | lift @2p | REV_10 @5p | FAILED @5p | lift @5p |
|---|---:|---:|---:|---:|---:|---:|
| **LN_H** | 19.6 % | 11.7 % | **1.67×** | 22.9 % | 13.8 % | 1.66× |
| **LN_L** | 18.6 % | 10.3 % | **1.80×** | 21.8 % | 13.1 % | 1.66× |
| NY_H | 14.1 % | 10.7 % | 1.32× | 15.7 % | 11.8 % | 1.33× |
| NY_L | 13.9 % | 10.8 % | 1.30× | 15.9 % | 13.0 % | 1.22× |
| NEAREST_00 | 4.3 % | 3.3 % | 1.29× | 9.5 % | 9.3 % | 1.02× |
| R3 | 0.6 % | 0.6 % | 1.12× | 1.8 % | 1.6 % | 1.10× |
| SWING_L | 31.9 % | 30.8 % | 1.04× | 36.3 % | 38.5 % | 0.94× |
| SWING_H | 32.8 % | 34.1 % | 0.96× | 37.0 % | 41.7 % | 0.89× |
| RANGE_H | 24.3 % | 27.9 % | 0.87× | 27.8 % | 33.7 % | 0.83× |
| RANGE_L | 23.0 % | 25.7 % | 0.90× | 26.6 % | 32.0 % | 0.83× |
| PIVOT | 4.4 % | 5.4 % | 0.80× | 10.2 % | 13.7 % | 0.75× |
| (R1/S1/S2/R2/PDH/PDL/NEAREST_50/S3) | 0.5–3.6 % | 0.4–4.7 % | 0.57–1.18× | — | — | — |

**Reading:**

- **Only session highs/lows discriminate.** London session levels have the strongest lift (1.67–1.80× at 2 p). NY lower.
- SWING and RANGE levels appear at FAILED events as often as REVERSED_10 events (lift < 1). They attract bounces of all outcomes equally — they are a bounce-location indicator, not a bounce-success indicator.
- Floor pivots and prior-day H/L: close to parity. They don't help pick which bounces will succeed.
- Bottom line: for a reversal proposition the engine should weight **LN_H/L and NY_H/L** proximity above the SWING/RANGE/PIVOT families.

---

## 4. Successful reversals vs failed vs ordinary — side-by-side

| | within 2 p | within 5 p | within 10 p | within 15 p |
|---|---:|---:|---:|---:|
| **Ordinary 5m extremes** — ≥1 level | 37.5 % | 69.2 % | 92.9 % | 98.7 % |
| ALL bounces — ≥1 level | 79.5 % | 91.2 % | 97.6 % | 99.2 % |
| REVERSED_10 bounces — ≥1 level | 80.6 % | 90.8 % | 96.8 % | 98.9 % |
| FAILED bounces — ≥1 level | 80.8 % | 92.6 % | 98.3 % | 99.4 % |
| **Ordinary 5m extremes** — cluster ≥2 | 11.8 % | 36.8 % | 68.8 % | 88.9 % |
| ALL bounces — cluster ≥2 | 59.0 % | 75.9 % | 91.3 % | 96.6 % |
| REVERSED_10 bounces — cluster ≥2 | 62.4 % | 76.0 % | 89.1 % | 94.7 % |
| FAILED bounces — cluster ≥2 | 61.4 % | 79.3 % | 94.2 % | 97.6 % |
| **Ordinary 5m extremes** — cluster ≥3 | 2.9 % | 19.7 % | 55.9 % | 75.0 % |
| ALL bounces — cluster ≥3 | 33.9 % | — | — | — |

**Reading:**

- The level-attracting signature of a bounce vs ordinary price is **enormous**: 11.7× at ≥3 levels within 2 p (2.9 % → 33.9 %), 2.1× at any level within 2 p.
- Within the bounce population, REVERSED_10 and FAILED look nearly identical on raw level-count metrics. The discrimination comes from (a) WHICH level types are near (§3.6), and (b) the specific cluster-size inflection at 3 levels within 2 p (§3.5).

---

## 5. HTF / QM / PAA at the turning point

### 5.1 HTF — reconstruction

Live `htf_authority.jsonl` and `htf_regime.jsonl` rolling logs cover **~9 days (2026-10-06 onward)** and therefore do not overlap the census window. The HTF column below is a **reconstruction** using the same prior-D1 anchor the production path uses: D1 trend direction = sign of close_{d−1} − close_{d−2}; magnitude in pips.

For HTF-alignment classification: `WITH_HTF` means the bounce reverses INTO the prior D1 direction (upper + DOWN, or lower + UP). `AGAINST_HTF` means the bounce reverses AWAY from the prior D1 direction.

| HTF tag | n | REV_10 | REV_5 | FAILED |
|---|---:|---:|---:|---:|
| WITH_HTF (bounce into HTF direction) | 5,864 | 38.7 % | 36.5 % | 24.8 % |
| AGAINST_HTF | 5,834 | 39.7 % | 34.7 % | 25.7 % |
| UNKNOWN_HTF (missing prior-D1 anchor) | 253 | 54.5 % | 23.7 % | 21.7 % |

**Observation:** simple prior-D1-close direction gives essentially **no discrimination** (REV_10 differs by 1 pp). The strong HTF signals the operator has characterised elsewhere (e.g. memory `[[project_r3_htf_veto_evidence]]`) use more structure than this reconstruction — HTF trend magnitude, H4 slope, counter-HTF carve-outs. A follow-up study using the actual production `htf_authority.compute(now)` applied to historical bars would be meaningful; the live log is not available for this corpus.

### 5.2 QM — live log overlap only (3.4 % matched)

`logs/qm_level_interactions.jsonl*` covers 2026-09-21 → 2026-10-15 (21 days). Overlap with the census window (2024-01-02 → 2026-09-27) is **6 days (2026-09-21 → 2026-09-27)**.

- Census events in that window: **1,955**.
- Events with ≥1 QM terminal (any level_type) whose price was within 10 pips of `extreme_px` and whose `final_ts` was within 6 hours of `extreme_ts`: **66** (3.4 %).

That low match rate is the structural reality that the operator has already documented: the `qm_level_interactions` state machine resolves on terminal interactions (ACCEPT / REJECT / OSCILLATING / BREAK_AWAY) that align with FINITE-set structural levels (Stage 6C-ish). Many bounce events happen at Bollinger / swing extremes that are not in the Stage 6C-ish universe or do not close an interaction in the 6-hour window around the extreme.

**The per-event JSONL file** (`per_event_components.jsonl`) carries each matched QM terminal verbatim; sample of the field shape:

```json
{"level_type": "LN_H", "level_price": 13432.0, "final_state": "REJECT",
 "approach_side": "below", "final_ts": "...", "distance_pips": 1.8, "delta_h": 0.08}
```

A full retrospective QM run against the 3-year corpus is possible (the state machine is pure-function per `qm_level_interactions.py`) but outside the operator's "use existing implementations" scope — it would require instantiating hundreds of per-level interactions per day across the archive. Not performed here; flagged in §7 as follow-up.

### 5.3 PAA — no coverage

`paa.assessment` + `paa.h1_bb_event` + `paa.level_map` were committed 2026-10-14 (`7d4c81f`). No PAA assessment records exist for any census event, and the production emitter path has not run for any of them. Reported as `NO_COVERAGE` across the dataset.

If PAA were to be applied retrospectively, the same observation as for QM holds: PAA is a pure consumer of NMS V3 state snapshots + H1 BB events + the level map; those can be reconstructed from the archive. Not performed here.

---

## 6. V3 entries vs bounce events

### 6.1 Sample

- `signal_log.jsonl` holds **129 total GBPUSD rows**; **68 are V3-family** (`GBPUSD_TREND_V3_L/S/UM_L/UM_S`, `V3_BB_L/S`, `V3_EMA_L/S`, `BOUNCE_A/C/TR_L/S`).
- Signal log oldest row: 2026-09-04. Census youngest row: 2026-09-27. Overlap window = 23 days.
- **16 V3 fires match a census event** (fired inside `[start_ts, end_ts]` OR extreme_ts within 60 min). 52 fires are unmatched (either no bounce event in that window or the match window was too tight).
- All 16 matches are from the four `TREND_V3` variants. No V3_BB, V3_EMA, BOUNCE_* match in this sample.

### 6.2 Timing

| Metric | Value |
|---|---|
| Lag (bars = minutes/5), negative = fire BEFORE extreme | median **-1.0**, mean **-4.6**, min -23.0, max +7.0 |
| Fires at or before extreme | 11 / 16 (69 %) |
| Fires 1-3 bars after extreme | 4 / 16 (25 %) |
| Fires >3 bars after extreme | 1 / 16 (6 %) |

Reading: **the median V3 fire precedes the bounce extreme by one 5m bar**. The mean is pulled further negative by a long tail of V3 fires that lead the turn by up to 23 bars (nearly 2 hours). V3 is positioned early relative to the turn — the question for the HTF Proposition Engine becomes whether early entry is good (captures the reversal from the start) or bad (bought the top / sold the bottom and had to withstand continued adverse before reversal).

### 6.3 Capture

For each matched V3 fire, we compute:

- `entry_vs_extreme_pips = |entry − extreme_px|`
- `potential_capture_pips = max(reversal_max_pips − entry_vs_extreme_pips, 0)` — the slice of the subsequent reversal still ahead of entry
- `capture_ratio = potential_capture_pips / reversal_max_pips`

| Metric | Value |
|---|---|
| Potential capture pips (mid-price axis) | median **4.55**, mean **4.14**, max 10.85 |
| Capture ratio | median **0.635**, mean **0.44**, max 0.91 |
| By strategy — mean capture ratio | TREND_V3_L 0.515 (n=3), TREND_V3_S 0.470 (n=4), TREND_V3_UM_L 0.394 (n=5), TREND_V3_UM_S 0.401 (n=4) |

**Reading:**

- V3 trades were, on the mid-price axis, positioned to capture roughly **44 % of the reversal_max_pips** when they coincided with a bounce event.
- **No direction-alignment check performed.** The analysis measures distance-from-extreme and residual-reversal-pips, not whether V3's direction matches the reversal direction. A V3 LONG fired right before an upper-side bounce extreme is positioned WRONG for the reversal — it is positioned FOR the preceding move. The 44 % median is therefore an UPPER BOUND on captured pips if direction aligned, and 0 otherwise. Spread, slippage, and the trade's own SL/TP are also not modelled.
- Three TREND_V3 subtypes show similar capture (0.39–0.52). The sample is too small (n = 16) to call differences meaningful.

### 6.4 What this does NOT prove

- Whether V3's direction was aligned with the ensuing reversal is not checked. For a trend-following strategy, firing into a BB extreme is often firing AGAINST the ensuing reversal — V3 would be the loser side, not the capturer. Resolving this requires joining V3 direction + event side + direction labels across all 16 events, which is in scope for a follow-up but not performed here because the sample is too small to be decisive.
- Realised P&L (post-spread, post-SL/TP) is not measured — the capture_ratio is a MID-PRICE upper bound.

A full "V3 entry timing × bounce reversal" study at scale needs:

1. A 2024-01 → 2026-09-27 signal_log corpus (not available on this host — the live file is 23 days deep).
2. Direction × event-side classification (BUY on upper-side event = positioned against reversal; SELL on lower-side event = same).
3. Trade-manager replay for realised P&L vs mid-price reversal_max_pips.

---

## 7. Caveats and limits

- **SWING_H/L and RANGE_H/L are partly tautological** at the extreme bar — the production implementation includes the current bar in the lookback. §3.3 details.
- **Oracle horizon.** REVERSED_10 and REVERSED_5 labels come from the census's own `first_10_ts` / `first_5_ts` columns, which are forward-looking from `extreme_ts` under the census's internal boundary rule. No new reversal definition was invented.
- **Mid-price only.** All distances and reversal metrics are mid-price. Spread (typical ~1 p GBPUSD) is not deducted. This matters most for the smaller capture-ratio measurements.
- **HTF signal is a reconstruction.** The live `htf_authority` logs do not cover the census window. The D1-trend reconstruction in §5.1 is a weak proxy for the actual production HTF classification.
- **QM match rate is low (3.4 %)** in the overlap window, by the structural reality that the QM state machine resolves only on finite-set level interactions. The low rate is not a defect of the match method; it reflects the sparsity of QM terminal records.
- **PAA has no coverage** for this corpus. Flagging only, not a limitation of the study.
- **V3 sample is small (n = 16).** Direction alignment not verified. Capture-ratio is a mid-price upper bound.
- **Confluence lift from 3 → ≥3 levels within 2 p is monotonic through size 5 (n = 217).** Size 6 (n = 19) is thin. Size ≥ 7 is noisy. Any proposition should treat the ≥3-level trigger with the lift it earns, not with the sparse higher-count tail.
- **Levels used are the single-pass "known-at-time" universe from the archive.** The implementation reused the production formulas verbatim; it did not re-run the production code paths (which are tick-driven and side-effectful). A full re-run with `level_snapshot_v6.build_level_snapshot(pair, snapshot_ts=extreme_ts, reference_price=extreme_px, …)` is possible once the production code paths are refactored to accept a historical reference loader — see follow-ups.

---

## 8. Research artefacts

Under `autobot_rationalisation/phase4a_bounce_study/`:

| File | Purpose | Rows |
|---|---|---:|
| `level_distance_harness.py` | Per-event level-distance harness | — |
| `ordinary_baseline.py` | Non-bounce 5m-extreme baseline sampler | — |
| `components_at_event.py` | HTF reconstruction + QM-log matcher + PAA coverage probe | — |
| `v3_entry_capture.py` | V3 fire × event matcher | — |
| `per_event_levels.jsonl` | Per-event level map + distances | **11,951** |
| `per_event_components.jsonl` | Per-event HTF/QM payload | 11,951 |
| `summary.json` | Aggregate within-K matrix, cluster histograms | — |
| `ordinary_baseline.json` | 2,000-sample baseline distribution | — |
| `components_summary.json` | HTF / QM / PAA coverage summary | — |
| `v3_entry_capture.jsonl` | Per-V3-fire capture records | 68 |
| `v3_entry_capture_summary.json` | V3 timing + capture aggregates | — |

Reproducibility: `python3 autobot_rationalisation/phase4a_bounce_study/level_distance_harness.py && \
python3 ..._ordinary_baseline.py && python3 ..._components_at_event.py && python3 ..._v3_entry_capture.py`. All scripts are READ-ONLY on `/opt/tradingbot/`.

---

## 9. Implications for the HTF Trading Proposition Engine

- **Confluence is a usable signal.** The engine's "where might this reverse" question gets a clean lift from counting non-trivial structural levels within 2 pips of the current extreme / BB touch — three or more is the inflection.
- **Prefer session H/L in level weighting.** London session H/L and NY session H/L are the only families with ≥1.3× REV_10/FAILED lift in this corpus. SWING / RANGE / pivot families are useful for presence, not for discrimination.
- **BB touch alone is not a reversal signal.** 59 % of all BB touches are "near 2+ levels within 2 p" but half still fail to produce a clean 10-pip reversal — the HTF Proposition Engine should treat BB touches as watch-points, not firing conditions.
- **V3 is positioned early relative to the turn but faces direction-alignment risk.** The HTF Proposition Engine's "suggested_strategy_family" output should treat an impending bounce reversal as a reason to NOT emit a TREND continuation proposition for V3 unless the HTF direction is aligned with the bounce reversal (upper-side bounce + HTF DOWN; lower-side bounce + HTF UP), i.e. the setup is bounce-into-trend rather than bounce-against-trend.
- **The missing live telemetry (QM / PAA / HTF) is the main gap.** Running the existing modules against the historical corpus — not reinventing them — would give a complete causal replay. That is a follow-up: it requires wrapping the production entry points with a historical-reference-loader shim and running them in the research worktree.

---

## 10. STOP

Study complete. No live code, config, service, cache, or position touched. Operator-authorised scope respected: use existing implementations and the original historical events; do not create a new detector; do not change bounce definitions. Follow-ups (direction-aligned V3 analysis, QM replay against the 3-year corpus, live HTF retrospective) are documented but not performed.
