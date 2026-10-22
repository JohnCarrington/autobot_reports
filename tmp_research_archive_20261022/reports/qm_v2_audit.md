# QM pick + V2_PICK_BOUNCE audit — READ-ONLY

Sources:
- `reports-public/host_161_deal_ledger_v2_20260927.csv` (host-161 deal ledger, cutoff 2026-09-27)
- `logs/signal_log.jsonl*` + `backups/eod-review/*/signal_log.jsonl` (per-trade close P&L enrichment)
- `logs/qm_candidates.jsonl*` (lifecycle rows; ENTRY_ARMED = pick fired)
- `logs/arbiter_shadow.jsonl*` (M3 arbiter view of V2_PICK proposals, engine attribution)
- `logs/candidate_corpus.jsonl*` (upstream input snapshots)
- `logs/tm_outcomes.jsonl*` (counterfactual TM grader)
- `data/candles/{PAIR}/{DATE}.csv` + `data/candles_ext_v2/{PAIR}` (5m candles)

Host 161 runs `IG_ACC_TYPE=DEMO`; `signal_log_integrity.py:114` + `.env.example`
confirm `demo-api.ig.com`. **There are no live-account fills in the audit.**

---

## 1. REAL FILLS (QM_V2 velocity + V2_PICK_BOUNCE)

**Flag: fewer than 30 fills (12 total; 7 QM_V2 + 5 V2_PICK_BOUNCE). ALL DEMO.**

| route | strategy mode | count |
|---|---|---|
| QM_V2 (velocity) | QM_V2_VELOCITY_L / _S | 7 (4 BUY + 3 SELL) |
| V2_PICK_BOUNCE | V2_PICK_BOUNCE_SLOW_REJECTION_L / _S | 5 (3 BUY + 2 SELL) |
| V2_PICK_BOUNCE_CONTINUATION_* | — | 0 fills (never traded live) |

**Headline (DEMO, host 161):**

| route | n | pnl_rows* | wins | win% | sum pips | mean | £ @ £2/pip (est.) |
|---|---|---|---|---|---|---|---|
| QM_V2 (velocity) | 7 | 6 | 4 | 67% | **+36.55** | +6.09 | **+£73.1** |
| V2_PICK_BOUNCE (slow-rej) | 5 | 3 | 0 | **0%** | **−31.50** | −10.50 | **−£63.0** |
| **TOTAL** | **12** | **9** | **4** | **44%** | **+5.05** | +0.56 | **+£10.1** |

\* 3 trades have `close_reason=scale_out_50pct_no_final` — the partial scaled out but the final close P&L isn't in the ledger. These are omitted from pips sums.

**£ P&L recorded in signal_log: £0 for all 12** (none of these fills were captured by `signal_logger.log_open` — V2 routes bypass the briefing/BB-pierce signal_log path and record only to the deal ledger). The £ figures above are estimated at the £2/pip stake observed on the three LEVEL_BOUNCE trades that did have `pnl_gbp` recorded.

**By month (open UTC):** All 12 fires in September 2026 (one on 2026-09-17, eleven on 2026-09-23 → 2026-09-25). No fills before or after.

**By pair:** GBPUSD 8 (+25.45p), EURUSD 4 (−20.40p).

**By session (UTC hour at open):** LONDON 2 fires; NY 7 fires; OTHER 3 fires. All session_name fields in the ledger were blank for these 12 so this is derived from the UTC hour of `timestamp_open`.

**By direction:** BUY 7 (+7.20p); SELL 5 (−2.15p).

**Full trade list** (sorted by open UTC):

| open | route | strategy | pair | dir | entry | pips | reason |
|---|---|---|---|---|---|---|---|
| 2026-09-17 13:10 | QM_V2 | QM_V2_VELOCITY_S | GBPUSD | SELL | — | — | scale_out_50pct_no_final |
| 2026-09-23 10:05 | QM_V2 | QM_V2_VELOCITY_L | GBPUSD | BUY | — | +0.85 | — |
| 2026-09-23 13:25 | V2_PICK | V2_PICK_BOUNCE_SLOW_REJECTION_S | EURUSD | SELL | — | −10.3 | STRUCTURE_EXIT:structure_flip_up |
| 2026-09-23 13:35 | QM_V2 | QM_V2_VELOCITY_S | GBPUSD | SELL | — | +28.55 | — |
| 2026-09-24 13:30 | QM_V2 | QM_V2_VELOCITY_S | GBPUSD | SELL | 13217.05 | −9.5 | STRUCTURE_EXIT:structure_flip_up |
| 2026-09-24 14:20 | V2_PICK | V2_PICK_BOUNCE_SLOW_REJECTION_L | EURUSD | BUY | 11375.3 | −10.3 | STRUCTURE_EXIT:structure_flip_down |
| 2026-09-25 06:15 | QM_V2 | QM_V2_VELOCITY_L | GBPUSD | BUY | 13225.4 | +30.05 | scale_out+final |
| 2026-09-25 06:30 | V2_PICK | V2_PICK_BOUNCE_SLOW_REJECTION_L | EURUSD | BUY | 11384.5 | — | scale_out_50pct_no_final |
| 2026-09-25 10:25 | V2_PICK | V2_PICK_BOUNCE_SLOW_REJECTION_L | GBPUSD | BUY | 13245.3 | — | scale_out_50pct_no_final |
| 2026-09-25 16:00 | QM_V2 | QM_V2_VELOCITY_L | EURUSD | BUY | 11399.90 | +0.2 | — |
| 2026-09-25 16:05 | QM_V2 | QM_V2_VELOCITY_L | GBPUSD | BUY | 13258.80 | −13.6 | STRUCTURE_EXIT:structure_flip_down |
| 2026-09-25 17:05 | V2_PICK | V2_PICK_BOUNCE_SLOW_REJECTION_S | GBPUSD | SELL | 13242.80 | −10.9 | STRUCTURE_EXIT:structure_flip_up |

Full JSON: `/tmp/qm_v2pick_fills.json`.

---

## 2. EVERY LOGGED CANDIDATE AS A TRADE

**Dedupe:** `qm_candidates.jsonl*` rows with `state=ENTRY_ARMED`, deduped on
`(symbol, zone_center, opened_at, armed_at_ts)` → **186 unique picks.**
Side inferred from `hypothetical_stop > hypothetical_entry` (SELL) else BUY.

**Coverage:** `armed_at_ts` range **2026-09-04 → 2026-10-05 (32 days)**. The
state field itself has rows back to 2024-06-03 but no ENTRY_ARMED pick-time
anchors before 2026-09-04 — ENTRY_ARMED armed_at_ts logging began then.

**Route attribution** (via `live_fire_disposition.route`): QM_V2 = 78 picks;
V2_PICK_BOUNCE = 41; no disposition (never dispatched) = 67.

**Script:** `/tmp/qm_v2_pick_sim.py`. Enters at `armed_at_ts` on the first bar
strictly after the arm; fill at `hypothetical_entry`; half-spread 0.4p each
side; 12-bar time stop; stop-first same bar; crosses the day boundary into the
next day's candles when needed.

**Fill-assumption caveats:**
- `hypothetical_entry` is a notional limit — in live the actual IG MARKET fill
  could be adverse by the IG spread or by any gap through the limit price.
- No ATR / regime filter applied beyond what the candidate's own state recorded.
- Candles for 2026-10-01 are from `data/candles/` (live IG mid, 5m).
- All 186 picks had bars available; 0 NO_BARS, 0 NO_FORWARD.

### Top-line

| variant | n | win% | mean | median | sum |
|---|---|---|---|---|---|
| LOGGED (hypothetical SL/TP) | 186 | 40.3% | −1.69 | −2.60 | **−314.85** |
| HARD12_T10 (SL ±12, TP 10) | 186 | 46.8% | −1.18 | −0.50 | **−219.40** |
| HARD12_T15 (SL ±12, TP 15) | 186 | 40.9% | −1.49 | −2.25 | **−276.80** |

All three variants are negative-net on this candidate universe.

### Outcome breakdown

| variant | TARGET | STOP | TIME_STOP | n |
|---|---|---|---|---|
| LOGGED | 29 | 55 | 102 | 186 |
| HARD12_T10 | 60 | 53 | 73 | 186 |
| HARD12_T15 | 29 | 56 | 101 | 186 |

The logged SL/TP configuration almost never TARGETs (29/186 = 16%) — the
logged target is often very far (TP distances up to 1000+ pips when
`hypothetical_target=14xxx` for a BUY entering at 132xx on a 100p stop
template inherited from LEVEL_BOUNCE). Most LOGGED trades die on time-stop.

### HARD12_T10 by (month, session, side, route, symbol)

| key | n | win% | mean | sum |
|---|---|---|---|---|
| **month 2026-09** | 114 | 46.5% | −1.01 | −115.00 |
| **month 2026-10** | 72 | 47.2% | −1.45 | −104.40 |
| **session LONDON** | 95 | 45.3% | −1.68 | −159.90 |
| **session NY** | 56 | 55.4% | **+0.14** | **+7.80** |
| **session OTHER** | 35 | 37.1% | −1.92 | −67.30 |
| **side BUY** | 89 | 40.4% | −2.99 | −266.15 |
| **side SELL** | 97 | 52.6% | **+0.48** | **+46.75** |
| **route QM_V2** | 78 | 43.6% | −2.08 | −162.20 |
| **route V2_PICK_BOUNCE** | 41 | 36.6% | −3.09 | **−126.65** |
| **route none (no gate dispo)** | 67 | 56.7% | +1.04 | **+69.45** |
| **symbol EURUSD** | 55 | 49.1% | +0.10 | +5.70 |
| **symbol GBPUSD** | 131 | 45.8% | −1.72 | −225.10 |

Reading: the only subset with a positive simulated expectancy is **SELL side**
(+0.48/pick) or **NY session** (+0.14/pick) or **no-disposition picks** (the
ones blocked upstream of the gate). V2_PICK_BOUNCE route is the single worst
cell: 36.6% WR, −3.09/pick, −126.65p total — this is a stronger negative
signal than the LEVEL_BOUNCE −6.11/trade cell from the earlier audit, scaled
by sample size.

### HARD12_T15 by same keys

Same sign everywhere, slightly worse win rates and ~5% more total P&L damage.
Full table in `/tmp/qm_v2_pick_sim_results.json`.

### By engine (where known from arbiter_shadow)

Arbiter V2_PICK proposals: 33 unique (deduped by `pair/bar_close_ts/level_id/side`).
By engine: CONTINUATION 20, SLOW_REJECTION 12, unknown 1. The matching of
engine to picks via timestamp is sparse (12 of 41 V2_PICK picks had an exact
arbiter engine match), so a direct engine-level table on simulated P&L is
noisy. The real fills' engine distribution (section 1): **5/5 V2_PICK fills
were SLOW_REJECTION** (0 CONTINUATION fills ever reached the broker).

---

## 3. GATING IMPACT

**(i) Stage-9 alignment rule (2026-10-03) — scored by `live_fire_disposition.gate_reasons`.**

Scope: V2_PICK_BOUNCE route only (per `qm_v2_executor.py:339-340` the
Stage-9 check is NOT run on QM_V2). HARD12_T10 cell for comparability.

| Stage-9 outcome | n picks | win% | mean | sum |
|---|---|---|---|---|
| passed Stage-9 (fired on to dispatch) | 40 | 35.0% | **−3.65** | **−145.80** |
| rejected: `v2_pick_stage9_none` | 6 | 66.7% | +2.07 | +12.45 |
| rejected: `v2_pick_stage9_disagree` | 0 | — | — | — |
| QM_V2 route (Stage-9 N/A) | 72 | 41.7% | −2.41 | −173.40 |
| no disposition | 68 | 57.4% | +1.28 | +87.35 |

Reading: **the picks that passed the 2026-10-03 Stage-9 rule are the single
worst subset** (35% WR, −3.65/pick, −£291 at £2/pip over 40 picks). The 6
picks the rule rejected under `stage9_none` would have netted +12.45p — the
rule in-sample removed winners, not losers. QM_V2 (never gated by Stage-9) is
also loss-making. The non-routed picks (never reached the gate — mostly
blocked by `one_strategy_cutover_guard`) are the only positive cell.

**(ii) Build 1 Stage 9 (structure direction) — reconstruction gap.**

I attempted to reconstruct Build 1's D2b stabilised direction at each pick
timestamp from `candidate_corpus.jsonl` `news_trend_snapshot.structure_evidence.structure`
(BULLISH / BEARISH / NONE). Corpus coverage is sparse: only **24/179 picks
(13%)** have a timestamp-matched corpus snapshot. The remaining 86% have no
reconstructable Build 1 structure state in the current logs.

Caveat and recommended next step: Build 1's D2b direction lives in
`direction_state.py` (commit `1cbf8f2`, 2026-10-04), which is deterministic
over the 5m candle series. A replay harness that walks the ENTRY_ARMED
timestamps through `direction_state` on the candle archive would give full
coverage. That is out of scope for a READ-ONLY log scan; the hook already
exists (see `project_day_type_primed_resolver_20260919`'s branch for a similar
replay pattern).

**(iii) Live gate refusal reason (binding) — HARD12_T10**

| binding | n | win% | mean | sum |
|---|---|---|---|---|
| **approved** (fired) | 37 | 51.4% | −1.50 | −55.40 |
| `one_strategy_cutover_guard` (blocks all QM_V2) | 30 | 33.3% | −4.33 | **−129.80** |
| `normal_routing` | 14 | 42.9% | +0.20 | +2.80 |
| `news_direction` | 9 | 33.3% | −2.76 | −24.85 |
| `entry_hours` | 4 | 50.0% | +3.32 | +13.30 |
| `v2_direction_conflict` | 4 | 25.0% | −4.50 | −18.00 |
| `kill_switch` | 2 | 50.0% | +2.15 | +4.30 |
| `concurrent_cap` | 2 | 100.0% | +9.20 | +18.40 |
| `one_book` | 2 | 100.0% | +9.20 | +18.40 |
| `news_post_lockout` | 2 | 50.0% | −1.80 | −3.60 |
| `opposing_level` | 2 | 0.0% | −12.80 | −25.60 |
| `sl_block` | 2 | 0.0% | −11.95 | −23.90 |
| no_disposition | 54 | 63.0% | +1.92 | +103.70 |
| unknown/other | 22 | 27.3% | −4.51 | −99.15 |

Reading: `one_strategy_cutover_guard` (the Build 1 kill on QM_V2 as a
legacy family) blocked the single worst group (30 picks, −129.80p). But the
*approved* picks that actually fired netted −55.40 across 37 trades — the
gate as a whole did not pre-select winners.

---

## 4. FLITTING

**Setup = `(symbol, zone_center)`.** 95 distinct setups across 179 picks
(sym/zone/armed/side-deduped). Coverage 2026-09-04 → 2026-10-05.

### Reps-per-setup histogram

| picks per setup | setups |
|---|---|
| 1 | 49 |
| 2 | 24 |
| 3 | 11 |
| 4 | 8 |
| 5 | 2 |
| 7 | 1 |

49 setups fire once (no re-arm). 46 setups re-arm at least once (48%).

### Flip counts

- **Total arm→arm flips** (adjacent picks with opposite side at the same setup): **52**
- **Setups with ≥ 1 flip:** 36 of 95 (37.9%)
- **Flips per setup histogram:** 0 flips 59, 1 flip 25, 2 flips 8, 3 flips 1, 4 flips 2

### Time between flipped picks (5m bars)

| statistic | value |
|---|---|
| n | 52 |
| mean | 48.2 bars (≈ 4h) |
| median | 25 bars (≈ 2h) |
| min / max | 2 / 298 bars |

Bin distribution: `1-3 bars: 2`, `3-6 bars: 2`, `6-12 bars: 14`, `>12 bars: 34`.
Most flips are slow (>1 hour between opposing picks); 4 flips happened within
≤ 6 bars (half an hour of 5m data).

### Daily picks + flips

| date | picks | flips | flip ratio |
|---|---|---|---|
| 2026-09-04 … 09-17 | 46 | 8 | 17% |
| 2026-09-22 | 9 | 2 | 22% |
| 2026-09-25 | 8 | 2 | 25% |
| 2026-09-29 | 13 | 3 | 23% |
| 2026-09-30 | 21 | 7 | 33% |
| **2026-10-01** | **41** | **14** | **34%** |
| **2026-10-02** | **19** | **10** | **53%** |
| 2026-10-05 | 8 | 3 | 38% |

Flip density climbed through late September and peaked at 53% of picks on
2026-10-02. Pick volume also exploded — 2026-10-01 saw 41 picks (≈ 3×
previous daily volume).

### Flip-vs-input-change coincidence

For each of the 52 flips I compared the three directional snapshots on the
prior pick vs the current pick (`news_trend_snapshot.state`, `.primary_direction`,
`structure_evidence.structure`):

| coincidence | count |
|---|---|
| NO input change at flip time | **35 (67%)** |
| ANY input changed | 17 (33%) |
| of which `nts_state` changed | 16 |
| of which `nts_primary_dir` changed | 10 |
| of which `structure` changed | 1 |

**Two-thirds of V2 side flips happen without any observable upstream direction
input change.** The remaining third coincides mostly with
`news_trend_snapshot.state` transitions (e.g. `MAJOR_LEVEL_TEST` ↔ `TREND_UP`).
Caveat: 155/179 picks have no corpus timestamp match within ±2 min, so
coverage of the pick→input join is low — the 67%/33% split is drawn from the
24 picks that have both a flip and a snapshot.

### Simulated results by flit subset (HARD12_T10)

| subset | n | win% | mean | median | sum |
|---|---|---|---|---|---|
| (a) every pick | 179 | 47.5% | −1.10 | −0.40 | −197.70 |
| (b) first per setup only | 95 | **50.5%** | **−0.30** | +0.50 | **−28.20** |
| (c) held ≥ 3 bars (no flip in next 3 bars) | 177 | 48.0% | −1.01 | −0.40 | −178.70 |
| (d) flipped-from-prev picks only | 52 | **36.5%** | **−3.35** | −4.00 | **−174.35** |

Reading:
- **Culling to the first pick per setup recovers almost all the loss:**
  −28.20 vs −197.70 total pips. The re-arm/flip population is where the money
  is bleeding.
- The 52 flipped picks (29% of the population) carry **−174.35p of the −197.70p
  total** — i.e. flipped-pick trades are responsible for 88% of the loss on
  HARD12_T10.
- Held-3-bars filter removes only 2 picks (177 vs 179) and barely changes the
  result — most flips are slow enough that a 3-bar hold filter doesn't catch
  them.

### Simulated results by flit subset (HARD12_T15)

Same pattern, modestly worse: (a) −253.60 total; (b) **−15.80 total**;
(c) −234.60; (d) **−214.65** (52 picks carry 85% of loss).

### Build 1 D2b stabilised direction at pick time

**Not reconstructable from current logs.** The pick-time logs do not record
`direction_state.StabilisedDirection` output. The code exists at
`direction_state.py:97-453` (A15 / D2b, commit `1cbf8f2` 2026-10-04); it is
deterministic over the 5m candle series, so a replay harness that re-runs
`direction_state` from a cold start up to each pick's `armed_at_ts` would
reconstruct the stabilised direction. That reconstruction is out of scope for
this READ-ONLY audit.

What I *can* say from the available snapshot fields: of the 52 flips, only 1
(2%) coincided with a `structure_evidence.structure` change (BULLISH↔BEARISH).
The other 51 flips happened while the upstream structure field was constant
or null. **This is consistent with D2b (a structure-anchored direction) being
stable while V2's pick side flitted on faster inputs** — but the small-n
corpus coverage (24/179 picks have any corpus snapshot) means this inference
is suggestive, not definitive.

---

## DATA COVERAGE SUMMARY

| source | rows / coverage |
|---|---|
| host 161 deal ledger v2 (QM_V2 + V2_PICK) | 12 fills, 2026-09-17 → 2026-09-25 |
| qm_candidates ENTRY_ARMED (deduped) | 186 picks, armed_at_ts 2026-09-04 → 2026-10-05 |
| qm_candidates raw ENTRY_ARMED rows | 903 (many are repeats of the same pick re-logged) |
| arbiter_shadow V2_PICK proposals | 49 (33 unique by pair/bar/level/side) |
| candidate_corpus with structure snapshot | 268 rows, covers 24/179 picks within ±2 min |
| tm_outcomes (counterfactual grader) | present for 10/12 ledger fills |
| Build 1 D2b direction at historical picks | **NOT RECONSTRUCTABLE** from logs alone (requires replay) |
| signal_log V2_PICK/QM_V2 close P&L | **absent** — V2 routes bypass signal_logger |
| close_intent.jsonl (close reasons) | present for 11/12 ledger fills |

**Gaps:**
- No pre-2026-09-04 ENTRY_ARMED pick anchors (candidate state machine logged
  less direction-field detail before that).
- `pnl_gbp` populated for only 3 LEVEL_BOUNCE trades across the entire audit
  (used to anchor the £2/pip stake assumption).
- Build 1 D2b direction state is deterministic but not snapshotted at pick
  time; need a replay to join.
- Session_name is blank in the ledger for all QM/V2 fills; derived from UTC
  hour of `timestamp_open`.

## No tuning performed. All stops/targets per spec. Report ends. STOP.
