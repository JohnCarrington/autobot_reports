# Historical Data Architecture V2 — Design Audit

**Removing restart dependency on IG historical REST**

- **Date:** 2026-09-21
- **HEAD:** `ed511ce9a78e3dcef8e8486c114c0b0b4a7fb5c4`
- **Scope:** Audit + design only. **No code changes, no service touches, no IG contact.**
- **Trading state:** `TRADE_ENABLED=0`, Stage10P paused, service running.

---

## 0. Executive summary

The restart-warmup pain is not caused by a lack of local data. It is caused by an in-memory-only H4 stack that must be reconstituted from scratch on every process start. Everything else that today burns IG historical allowance at restart is already either (a) skippable when the on-disk cache is fresh, or (b) skippable in principle but not wired that way yet.

**Root cause in one line:** `TimeframeContext._h4_closed[sym]` is process-local; it has no persisted counterpart on disk (unlike H1 and D1 in `cache/htf/`), so the H4 cold-start path always finds it empty and reaches for REST.

**The fix is not a rewrite.** It is:
1. Add persisted H4 to `cache/htf/{SYMBOL}_H4.json` (mirror the H1/D1 shape).
2. Reorder the H4 cold-start to prefer persisted H4 → 5M-derived H4 → REST-as-repair, matching the H1/D1 pattern.
3. Widen the rolling 5M retention just enough that derived H1/H4 always exceed indicator warm-up (~2400 bars ≈ 8.3 days).
4. Persist previous-completed-day D1 OHLC once per day and treat it as the authoritative pivot source for today (D1 REST becomes gap-repair only).
5. Keep the 8000-point weekly budget as a **last-resort** safety net, not the primary control on availability.

The eight thousand-point counter (currently 7996/8000) is doing its job — it stopped historical allowance from disappearing again — but it is being asked to do too much. Restart readiness should not depend on that counter having room.

---

## 1. HISTORICAL_REST_CALL_GRAPH

All IG historical-price REST calls funnel through **one wrapper**: `autobot.py::_rest_fetch_df` (`autobot.py:1348-1468`). That wrapper opens a `rest_allowance.begin_reservation()`, submits, and disposes of the reservation as CONFIRMED / RELEASED / UNCERTAIN depending on the exception class. Every call site below is a caller of that wrapper. There are **no unguarded historical REST call sites in the live process** (`build_deep_cache.py` bypasses the guard but is an offline utility; it is not part of the running service).

| # | CALL_SITE | EPIC | TIMEFRAME | REQUESTED_POINTS | WHEN_CALLED | STARTUP_OR_RUNTIME | WHY_REQUIRED | CONSUMER | REPEATED_AFTER_RESTART | CACHE_CHECK_BEFORE_REQUEST | PERSISTED_DATA_CHECK_BEFORE_REQUEST |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `autobot.py:1569` `_v5_pia_h4_cold_start` | `_pick_preload_epic(sym)` (TODAY CFD) | `HOUR_4` | 40 | Once per symbol per startup | STARTUP | Produce ≥20 H4 closed bars for `TimeframeContext.sufficient_h4_bars`; PIA / TREND_V3 / EMA_PB rely on H4 alignment | `tf_ctx._h4_closed[sym]` (in-memory) | **YES — every restart** because `_h4_closed[sym]` is in-memory only | Yes: `_h4_closed[sym] ≥ 20` skip; `rest_allowance.remaining() < 200` skip | **NO persisted H4 store exists** — 5M-agg fallback exists (line 1610), but REST is primary when allowance permits |
| 2 | `autobot.py:1754` `_rest_preload_symbol` (tail-gap) | TODAY CFD | `MINUTE_5` | 5–600, computed from rolling age | Startup, if `rolling_age_sec > REST_5M_GAPFILL_GRACE_SECS` (360s) | STARTUP | Patch missing 5M tail into rolling cache | rolling `_candles_rolling.csv` | Only if rolling cache is >6 min stale at restart — otherwise skipped | Yes: `REST_5M_GAPFILL_ENABLED`, grace-secs age check | Yes: `_read_rolling_cache_df` |
| 3 | `autobot.py:1862` `_rest_preload_symbol` (internal-gap) | TODAY CFD | `MINUTE_5` | 5 to `STRUCTURE_BUFFER_GAPFILL_MAX_POINTS` per gap | Startup, only if internal gaps detected | STARTUP | Repair mid-buffer gaps | rolling `_candles_rolling.csv` | Only if internal gaps exist | Yes: `STRUCTURE_BUFFER_GAPFILL_ENABLED=0` (default OFF) | Yes: `_scan_internal_gaps` on persisted buffer |
| 4 | `autobot.py:1980` `_rest_preload_symbol` (primary 5M) | TODAY CFD | `MINUTE_5` | `max(50, 60)` = 60 | Startup, if rolling+persisted 5M caches both insufficient | STARTUP | Cold-start 5M buffer | `_candles.csv` + candle-builder feed | Only if rolling+persisted both missing | Yes: both caches checked first | Yes: rolling+snapshot both |
| 5 | `autobot.py:1994` `_rest_preload_symbol` (1M→5M) | TODAY CFD | `MINUTE` | `PRELOAD_REST_1M_POINTS` (50) | Startup, only if #4 returned empty | STARTUP | Last-resort 5M synthesis via aggregation | `_candles.csv` | Only if #4 fails | Yes | Yes |
| 6 | `autobot.py:10352` (HTF gap-fill inline) | TODAY CFD | `HOUR` or `DAY` | `max(5, age/bucket + 5)` | Startup, per TF, only if `htf_cache.startup_load_or_flag` returns `action="gap_fill"` | STARTUP | Patch H1/D1 into persisted HTF JSON | `cache/htf/{SYM}_{H1,D1}.json` + `_TF_CTX.inject_htf_candles` | Skipped if HTF cache is fresh — H1 fresh <1h, D1 fresh <24h | Yes: `startup_load_or_flag` first | Yes: `cache/htf/*.json` |

**Worst-case per-startup consumption (assuming worst state of every cache):**
40 (H4) + 600 (5M gap-fill) + 600 (5M internal-gap, if enabled — it isn't) + 60 (5M primary) + 50 (1M) + 250 (H1 gap-fill) + 250 (D1 gap-fill) ≈ **1,850 points**.

**Typical consumption with warm caches:** 40 (H4) — every other site short-circuits.

**Zero runtime REST.** All historical fetches happen in startup phase. Live bars arrive over Lightstreamer only. Search over the whole process lifetime yields no runtime historical call.

**Non-historical IG REST — deliberately out of scope:**
- Session/auth (`get_ig_session`, `refresh_session`)
- Positions / working orders queries (position sync, kill-switch, TP/SL updates)
- Streaming subscription negotiation
- Sentiment / market details
- Any allowance-bounded but non-historical endpoint

None of these are wrapped by `rest_allowance`, and correctly so — IG's historical-price weekly cap is distinct from the general REST envelope. Preserve that separation.

---

## 2. STRATEGY HISTORICAL REQUIREMENTS

Enabled production strategies (from `.env` + `MEMORY.md` cross-check; EMA_PB / BB_BOUNCE-cascade / raw-reversal are OFF and stay off):

| STRATEGY | TIMEFRAME | MINIMUM_HISTORY | WHY | CAN_DERIVE_FROM_5M | MUST_COME_FROM_IG | PERSISTABLE |
|---|---|---|---|---|---|---|
| GBPUSD_BB_BOUNCE | 5M | 75 bars | BB(20), MACD(12,26,9), RSI(3,14), EMA(50), pierce wicks | Yes | No | Yes (rolling 5M) |
| GBPUSD_BB_BOUNCE | H1 | 75 bars | regime MACD(35,45,30) | Yes (agg 5M) | No | Yes (H1 JSON) |
| GBPUSD_BB_BOUNCE | D1 | 1 prior | PDH/PDL/pivots | No | Yes for original; **cached D1 is authoritative once written** | Yes (D1 JSON) |
| GBPUSD_TREND_V3 | 5M | 75 | ADX(14), MACD, ATR(14), EMA(50) | Yes | No | Yes |
| GBPUSD_TREND_V3 | H1 | 75 | regime | Yes | No | Yes |
| GBPUSD_TREND_V3 | H4 | 20 (arm) / 50 (rich) | HTF alignment via `_h4_closed` | Yes (agg 5M) | No | Yes (design gap — see §3/§5) |
| GBPUSD_TREND_V3 | D1 | 2 | pivots, PDH/PDL | No | Cached authoritative | Yes |
| GBPUSD_EMA_PULLBACK (currently OFF end-to-end, but wiring stays) | 5M/H1 | as above | — | Yes | No | Yes |
| GBPUSD_STRUCTURE_BREAK | 5M | 100 | ADX transition + MACD | Yes | No | Yes |
| GBPUSD_STRUCTURE_BREAK | H1 | 75 | regime | Yes | No | Yes |
| GBPUSD_STRUCTURE_BREAK | D1 | 2 | structure | No | Cached authoritative | Yes |
| GBPUSD_PIVOT_BREAK | 5M | 60 | coil detection | Yes | No | Yes |
| GBPUSD_PIVOT_BREAK | D1 | 1 prior | pivots | No | Cached authoritative | Yes |
| GBPUSD_LEVEL_BOUNCE | 5M | 20 | BB pierce | Yes | No | Yes |
| GBPUSD_LEVEL_BOUNCE | D1 | 1 prior | outer pivots | No | Cached authoritative | Yes |
| THREE_CO | 5M/H1 | 25/50 | pattern + momentum | Yes | No | Yes |
| NEWS_STRATEGY (tick-driven) | 5M | 14 | ATR spike | Yes | No | Yes |
| NEWS_STRATEGY | H1 | 50 | bias | Yes (agg 5M) | No | Yes |
| NEWS_STRATEGY | D1 | 2 | prior-day range | No | Cached authoritative | Yes |
| CONFIRMATION_FALLBACK | 5M | 20 | patterns | Yes | No | Yes |
| BRIEFING_EXECUTION | 5M/H1/D1 | 600 / 100 / 100 | rich context | Yes for 5M/H1, D1 cached | D1 first-write from IG | Yes |
| **regime_engine (aux)** | H1 | 75 | MACD(35,45,30) | Yes (agg 5M) | No | Yes |
| **htf_authority (aux)** | H1/D1/W1 | 21+ | EMA direction / slope | H1/D1 yes; W1 needs D1 aggregation | No | Yes |

**Distinguishing genuine IG-source from convenient IG-source:**

- **Genuinely IG-only:** the *first* previous-day D1 OHLC on a new trading day. Nothing else in the enabled roster needs a bar that cannot be reconstructed either from persisted state or from local 5M aggregation.
- **Currently IG-sourced but does not need to be after restart:** every H1, H4, and D1 bar older than "last-cached" is already on disk once written. The current architecture just doesn't consult that disk state consistently for H4.
- **Never IG-sourceable meaningfully:** 5M wicks and body structure. Those come from Lightstreamer live. If the stream is up, they arrive without touching REST.

---

## 3. D1 / DAILY STRUCTURAL LEVELS

**ARE_TODAYS_LEVELS_DETERMINISTIC_ONCE_PREVIOUS_DAY_CLOSES = YES.**

Everything in `{PIVOT, PDH, PDL, R1..R3, S1..S3}` is a pure function of the previous completed D1 candle. `NEAREST_00 / NEAREST_50` are functions of current price only (no history required). Confirmed by inspection of `bb_pd_gate.py::compute_pd_pct` (lines 156–242) and `bb_pd_gate.compute_pivots_only` (called from `gbpusd_pivot_break.py:471`, `gbpusd_level_bounce.py:529`).

Today's on-disk D1 cache (`cache/htf/GBPUSD_D1.json`) already holds ~250 completed-day bars, and pivot readers already walk that cache backward to select the "prior D1" bar (with a weekend-label guard added 2026-09-07). The infrastructure to make D1 REST unnecessary at restart **already exists** — what is missing is:

1. A dedicated **structural-levels file** per epic, per trading date, computed once per day at rollover, so a restart during the same trading day never re-derives pivots from the D1 cache. Even the derivation from the D1 cache is safe (no REST), so this is a performance/clarity improvement, not a REST-cost fix.
2. **Explicit verification** at startup: if the D1 cache holds a valid `prior_d1` for today's date, no D1 REST should ever fire — including as part of "gap fill" — because there is no gap to fill.

**Proposed persisted-levels record (one JSON file per epic, replaced atomically at each daily rollover):**

Path: `cache/levels/{SYMBOL}_daily_levels.json`

```json
{
  "trading_date": "2026-09-22",
  "epic": "CS.D.GBPUSD.TODAY.IP",
  "previous_day_date": "2026-09-19",
  "previous_day_open":  1.30845,
  "previous_day_high":  1.31123,
  "previous_day_low":   1.30580,
  "previous_day_close": 1.30712,
  "pivot":  1.30805,
  "pdh":    1.31123,
  "pdl":    1.30580,
  "r1":     1.31030,
  "r2":     1.31348,
  "r3":     1.31573,
  "s1":     1.30487,
  "s2":     1.30262,
  "s3":     1.29944,
  "calculated_at":     "2026-09-21T22:05:12Z",
  "source":            "d1_cache",
  "source_timestamp":  "2026-09-19T22:00:00Z",
  "provenance": {
    "d1_cache_mtime":  "2026-09-21T21:59:47Z",
    "cache_bucket_epoch": 1758326400,
    "version": 1
  }
}
```

**Restart semantics (same trading day):**
- If `trading_date` in file matches today's trading date **and** file mtime is newer than the D1 cache-record used → **REUSE** as-is. No D1 REST, no D1 cache re-walk.
- If file is missing or `trading_date` does not match today → **REGENERATE** from the D1 cache (still no REST, because the D1 cache already holds the required bar).
- If D1 cache is missing the required prior day → **THEN** REST-repair the D1 cache (guarded by budget), regenerate levels file.

Safety: since pivots are a pure function of previous-day OHLC, and the previous day is immutable once closed, reuse is unconditionally safe within the same trading date. Weekend rules already prevent Sat/Sun-labelled bars from becoming anchors (`htf_cache.py:456–499`, `bb_pd_gate.py:245–300`).

---

## 4. REQUIRED 5M RETENTION

The purpose of increased 5M retention is to make H1 and H4 fully reconstructible from local 5M on restart without touching REST.

**Formula:** `retention_5m_bars = max(indicator_warmup_bars_per_TF) × bars_per_TF_hour × safety_margin`

- H4 indicator warm-up peak: 50 H4 bars (rich MACD/EMA for HTF alignment). 50 × 48 = **2,400 5M bars**.
- H1 indicator warm-up peak: 75 H1 bars (regime MACD(35,45,30)). 75 × 12 = **900 5M bars**.
- Safety margin: +20% for indicator settle + boundary alignment + short weekend gap tolerance.
- **Adopt:** 5M retention = **~3,000 bars** (≈10.4 days) across all configured epics.

Currently: `PRELOAD_TARGET_5M_BARS=600` (about 50 hours). That is enough for H1 warm-up (900 required, 600 present — actually short) but nowhere near enough for full H4 warm-up. This is why the H4 cold-start path exists in the first place.

Per-epic retention targets (all identical; the workload is symmetrical across configured pairs):

- `GBPUSD_REQUIRED_5M_RETENTION = 3000`
- `EURUSD_REQUIRED_5M_RETENTION = 3000`
- `USDJPY_REQUIRED_5M_RETENTION = 3000`
- `USDCAD_REQUIRED_5M_RETENTION = 3000`
- `GBPJPY_REQUIRED_5M_RETENTION = 3000` (if present in TRADING_PAIRS)
- `EURGBP_REQUIRED_5M_RETENTION = 3000` (if present)
- `AUDUSD_REQUIRED_5M_RETENTION = 3000` (if present)

Cost: 3,000 rows × ~120 bytes/row (OHLC + indicator columns) ≈ 360 KB per epic — trivial.

**Non-goal:** do not attempt "full W1 reconstruction from 5M." Weekly EMA is `htf_authority`'s optional check and is graceful when unavailable; keep W1 out of the retention envelope.

---

## 5. LOCAL DERIVATION (5M → H1 → H4)

`timeframe_context.py` already contains the aggregator: `_floor_bucket` (line 59), `_PartialCandle.update_from_5m` (line 49), `preload_h4_from_5m_cache` (called from `autobot.py:1617`). What is missing is a single deterministic **cold-boot derivation** that runs before any HTF gap-fill decision is made.

**Proposed derivation pipeline (per symbol, run once at startup after rolling-5M is loaded):**

```
load persisted 5M rolling (target 3000 bars)
   ↓
group by H1 bucket (UTC hour boundary)
   → emit each *closed* H1 bucket into an ordered list
   → drop the in-progress current H1 (bucket epoch > now-3600)
   ↓
group closed H1 into H4 buckets (H1 bucket_epoch // 4 aligned to UTC)
   → emit each closed H4 bucket
   → drop the in-progress current H4
   ↓
merge the emitted H1 list with cache/htf/{SYM}_H1.json (dedupe by bucket_epoch, cache wins on conflict where cache is older/authoritative? — see below)
merge the emitted H4 list with cache/htf/{SYM}_H4.json (new file — see §14 recommendation)
   ↓
seed TimeframeContext._h1_closed[sym] and _h4_closed[sym]
```

**Conflict-resolution rule:** on bucket overlap, the record whose `contributions` count is higher (or whose provenance is authoritative — see §7) wins. In practice: an H1 bucket assembled from 12 closed 5M bars beats an H1 bucket cache-restored with `contributions=1` from a mid-bucket restart, and vice versa.

**Boundary invariants:**
- Closed causal bars only. In-progress buckets never emitted.
- UTC-anchored: H1 buckets at `epoch // 3600`, H4 buckets at `epoch // 14400`, D1 buckets at the FX-day rule already in `timeframe_context.py`.
- No future data (drop any bar with `bucket_epoch >= now-<bucket_secs>`).
- No fabricated gap bars — if a 5M bar is missing, its H1 bucket goes down by 1 contribution; if the H1 bucket falls below `MIN_CONTRIBUTIONS_FOR_PERSIST` it is not emitted.
- Deterministic across restarts: same 5M input → same H1/H4 output, always.

**D1:** keep IG D1 as the authoritative daily source (the FX-day boundary at 22:00 UTC is subtle and IG's daily bars encode the correct settlement window). The `htf_cache` already handles this correctly. D1 REST is warranted only when the cache is genuinely missing a previous day (weekend restart on a Monday after a maintenance window that truncated the D1 cache, for example).

---

## 6. STARTUP_HISTORY_SEQUENCE (idempotent restart)

**Governing requirement:** N restarts with complete persisted history ⇒ 0 additional historical REST requests.

Proposed sequence (per symbol; sequential across the pipeline, parallel across symbols):

```
1. Load rolling 5M cache from disk       (cache/{SYM}_candles_rolling.csv)
2. Validate rolling cache                 (contiguity, ≥ MIN_CACHE_CANDLES, tail-age ≤ session-relevant threshold)
3. Derive H1 closed bars from 5M          (see §5 pipeline)
4. Derive H4 closed bars from 5M          (see §5 pipeline)
5. Load persisted H1/H4/D1 HTF caches     (cache/htf/{SYM}_{H1,H4,D1}.json)
6. Merge derived H1/H4 into TF context    (cache-authoritative wins where contributions differ)
7. Load persisted daily levels file       (cache/levels/{SYM}_daily_levels.json)
8. Validate levels file's trading_date    (matches today's FX trading day)
9. If levels file is stale for today AND D1 cache holds prior-day bar → regenerate levels file (still no REST)
10. Identify genuine gaps                 (missing 5M interior, D1 prior-day missing, HTF cache below indicator warm-up floor)
11. Only THEN consider REST repair        (§7)
12. If any REST repair failed on a required timeframe → mark that strategy set as ABSTAIN; do not degrade silently
```

Contrast with today's sequence, which lets `_v5_pia_h4_cold_start` reach REST at step 1 because H4 has no persisted counterpart to check.

---

## 7. GAP-BASED REST REPAIR

**REST_REPAIR_TRIGGER — the union of:**
- 5M rolling tail-age > `REST_5M_GAPFILL_GRACE_SECS` **and** the resulting gap is not weekend/closed-session.
- 5M interior gap detected by `_scan_internal_gaps` (already conservative — `STRUCTURE_BUFFER_GAPFILL_ENABLED=0` today; keep default OFF).
- H1 derived-plus-cache stack has < `H1_INDICATOR_WARMUP_BARS` (75) after §6 step 6 → repair the tail from IG H1.
- H4 derived-plus-cache stack has < `H4_ARM_BARS` (20) after §6 step 6 → repair from IG H4 as absolute last resort. (In steady state this trigger never fires because §4 retention keeps H4 derivable.)
- D1 cache does not hold a prior-day bar for the current FX trading date → repair a single-day D1 window.

**REST_REPAIR_REQUEST_SHAPE:**

```
identity = (symbol, resolution, bucket_start_epoch, bucket_end_epoch)
```

Bucket-aligned, not point-count-based. Requests are the smallest whole-bucket window that covers the gap. Weekend intervals are subtracted from the requested window before shaping the call.

**Overlap / dedup:**
- On successful repair, persist a **repair-attempt journal** (see §8) keyed by `identity`.
- Any subsequent restart that computes the same `identity` for an unfilled gap consults the journal first: if the range has been attempted since the last authoritative disk mutation of that timeframe, do not attempt again.
- Maximum repair size per call: bounded to the smaller of {IG per-call max for that resolution, budget-remaining / 4}. This prevents any single repair from exhausting the remaining budget.

**Weekends / market closures:** gap intervals that fall entirely within Fri 21:00 UTC – Sun 22:00 UTC (or the equivalent per-instrument closure) are subtracted before shaping. Never request a bar that IG has never generated.

**Incomplete current bars:** never request the in-progress bucket. Repair boundary is always `now - bucket_secs` (exclusive).

**Staleness policy:** if the gap identity is older than one week AND the affected timeframe is only feeding an indicator whose oldest useful data point has scrolled past → do not repair; the data would be discarded on arrival anyway.

**Atomic persistence:** each successful repair writes new bars into the timeframe cache under the same atomic pattern already used (`_atomic_write_state` semantics from `rest_allowance.py:238–320` transplanted to `htf_cache.save_candles_to_cache`).

---

## 8. RESTART-STORM PROTECTION

**Persistent request-identity ledger.** Path: `cache/rest_repair_journal.jsonl` (append-only).

Each attempt writes:

```json
{
  "identity": {"symbol": "GBPUSD", "resolution": "HOUR", "bucket_start": 1758216000, "bucket_end": 1758312000},
  "attempted_at": 1758400000,
  "outcome": "confirmed" | "released" | "uncertain",
  "points_charged": 24,
  "reservation_txn_id": "<uuid>",
  "notes": "..."
}
```

On startup, `rest_repair_journal` is loaded into an in-memory `dict[identity → last_attempt]`. Before every candidate REST repair, `_rest_fetch_df` consults the map and applies the following rule:

- `last_attempt.outcome == "confirmed"` and the identity's window is already reflected in the on-disk cache → **skip** (already have the data).
- `last_attempt.outcome == "confirmed"` but the on-disk cache does not reflect it → **something wrote and rolled back** → allow one retry; then apply exponential backoff (1h, 4h, 24h) until either success or manual intervention.
- `last_attempt.outcome == "uncertain"` → **treat conservatively**: do not retry within a cool-off window (proposed: 30 min for tail-gap 5M, 4h for HTF, 24h for D1). This preserves the `rest_allowance` UNCERTAIN semantics.
- `last_attempt.outcome == "released"` → retry allowed (pre-send failure, no IG-side charge).

Journal is bounded by pruning entries older than 2 × the local budget reset window (2 weeks). Pruning at startup, not runtime.

**Existing reservation accounting** in `rest_allowance` remains the ledger for allowance *consumption*. The repair journal is the ledger for allowance *decision* — orthogonal responsibilities; do not merge them.

---

## 9. LOCAL_BUDGET_STILL_USEFUL = YES

**Recommended long-term role:**

The 8000-point weekly budget is being asked to do two jobs today: (a) rate-limit historical calls against the shared 10k IG cap, and (b) act as the primary availability gate for restart readiness. It succeeds at (a) and should keep doing it. It fails at (b) precisely because it is a *rate-limit*, not a *cache* — the point of this design is to move availability off the budget and onto persisted history.

**After migration, the local budget should be:**
- A hard ceiling on gap-repair spend per week.
- A conservative floor on how many points can be spent by any single repair (≤ `remaining/4`, as noted in §7).
- **Never** a determinant of whether AutoBot can serve strategies on startup — that is a cache question, not a budget question.
- Retained at 8000 as a 20% headroom against IG's 10k, unchanged.
- Reservation-based accounting (`5cbbfa0`) retained without modification. All three states (CONFIRMED / RELEASED / UNCERTAIN) are load-bearing for correctness and continue to be so.
- ISO Monday reset retained without modification.

Do not touch either the value or the reset in this design phase. The current 7996/8000 state is proof the system is doing its job; the fact that this design must work while that counter is exhausted (§12) is the strongest validation of the "cache-first, budget-last" thesis.

---

## 10. IG_ALLOWANCE_TELEMETRY_ROLE

Today, `autobot.py:1438–1461` parses IG's response allowance block on every fetch and writes it to `rest_allowance.json` under separate keys (`ig_allowance_remaining`, `ig_allowance_total`, `ig_allowance_expiry_s`, `ig_allowance_observed_at`). Current file: `ig_allowance_remaining=32`, `points_used=7996`. Local counter and IG counter agree in spirit (both nearly exhausted) but not in value — this is expected because IG's counter counts the shared pool across all clients on the account.

**Long-term design:**

Keep the two concepts **strictly separate**. Their semantics differ in three ways:

1. **Period.** IG's `allowanceExpiry` is a rolling window from first spend, not an ISO week. The two counters roll over independently.
2. **Unit.** IG counts every historical-price request. The local reservation counts the same, but the local charge is `1 * num_points` while IG may be charging per-call regardless of size (verify empirically before conflating).
3. **Authority.** IG is authoritative for whether the *next* fetch will succeed. Local is authoritative for *this session's decision-making*.

**Proposed policy (not implemented in this phase):**

- **Admission decision** should be the *minimum* of: local remaining, IG remaining × safety-factor (proposed: 0.8), and a per-symbol per-startup budget cap (proposed: 200 points to ensure any one symbol cannot exhaust the whole allowance).
- **Alert threshold** when IG remaining drops below (say) 500: emit an operational alert but do not gate.
- **Divergence guard:** if local remaining is very high but IG remaining is very low, prefer IG. Some other process (or a build_deep_cache run) has consumed IG's share.
- **Refuse to admit** when either counter is at floor; the earlier §11 fail-mode analysis then takes over.

Do not implement the admission-side use of IG telemetry until the cache-first architecture is in place. Otherwise this becomes another mechanism that can gate startup on external state.

---

## 11. FAILURE MODES

For each scenario, the priorities are (highest first): **no incorrect trading context → minimise historical REST → minimise strategy downtime**.

| Scenario | Behaviour under V2 |
|---|---|
| **Clean restart, complete cache** | Load persisted 5M → derive H1/H4 → load H1/H4/D1 caches → load levels file. Zero REST. All strategies READY within seconds. |
| **Repeated restart** | Repair journal + persisted caches short-circuit every gap decision. Zero REST after the first restart that had a genuine gap. |
| **Crash restart** | `rest_allowance.recover_orphans` transitions OPEN → UNCERTAIN as today. Repair journal reflects last successful attempts. Same as clean restart otherwise. |
| **Missing 5M gap (interior)** | Detected by `_scan_internal_gaps`. Repair journal consulted. If not-recently-attempted → REST repair (weekend-filtered). If attempted-and-uncertain → cool-off. If gap falls in the indicator settle-in region for a specific strategy → that strategy abstains. |
| **Stale D1 (last cached bar is >48h old on a weekday)** | `htf_cache.is_prior_d1_stale` returns True. If prior-day D1 is present but a *newer* one is missing → REST-repair 1-2 D1 bars. If prior-day itself is missing → D1 repair mandatory before pivot-consuming strategies can arm. |
| **Missing daily-level file** | Regenerate from D1 cache (no REST). If D1 cache is missing the required prior day → escalate to D1 repair. |
| **Corrupt cache (rolling / HTF / levels)** | Fail closed on that specific cache. Do not silently zero. Emit critical alert. Fall back to REST repair only for the affected timeframe, budget permitting; strategies dependent on the failed timeframe abstain until the repair succeeds. |
| **Uncertain historical request** | Charge retained; identity marked UNCERTAIN in repair journal; cool-off applies before retry. Same as today's `rest_allowance` behaviour, extended to the repair-decision layer. |
| **Actual IG allowance rejection** | Repair fails. Strategies dependent on the missing data abstain. `rest_preload_block.json` remains as the last-resort back-off signal (retain existing 30-min block). |
| **Weekend restart (Sat/Sun)** | No gap-fills fire (weekend-subtraction in §7). Persisted history is authoritative and will remain so until Sunday 22:00 UTC. |
| **Restart shortly after daily boundary** | The FX-day rollover is 22:00 UTC. If the restart lands between 22:00 and 22:15 UTC and the previous-day D1 bar has not yet been written to the D1 cache → wait for `HTF_D1_MIN_PLAUSIBLE_RANGE` guard + CSV fallback (already present in `htf_cache.py:404-450`). If both fail, escalate to a single-bar D1 REST at 22:15 UTC. This is the one legitimate every-day-if-restarted historical REST call, and it costs 1 point. |

**Explicitly rejected behaviours:**
- Silent degradation on missing data.
- Emitting synthetic bars to fill gaps.
- Repeating a UNCERTAIN attempt without cool-off.
- Treating the local budget as a strategy-readiness signal.

---

## 12. MIGRATION FROM CURRENT SYSTEM

**Constraint reminder:** current live state is `points_used=7996`, `points_budget=8000` (4 points left this week). The migration must prove restart readiness **without any historical REST call**.

**Migration stages (each stage is independently deployable and each stage's proof is a replay against candle archive + a synthetic-restart drill against the running state files, per no-deferred-validation rule):**

**Stage M0 — Instrumentation only (no behaviour change):**
- Add a startup log line per symbol reporting: rolling-5M-count, derived-H1-count, cache-H1-count, derived-H4-count, cache-H4-count, D1-prior-present, levels-file-present.
- Add a repair-journal write on every existing REST call (does not gate anything yet).
- Purpose: measure the size of the H1/H4 gap on today's real state.

**Stage M1 — Persist H4 to `cache/htf/{SYM}_H4.json`:**
- Mirror the H1 writer path in `timeframe_context.py` for H4 closed buckets.
- Backfill: on first deploy, write the current in-memory H4 stack (once H4 cold-start naturally completes on the *last* allowance-permitted restart of the week — or, safer, backfill from persisted 5M using the derivation pipeline in §5 → no REST).
- Reader in `_v5_pia_h4_cold_start` now consults the H4 cache first.

**Stage M2 — Widen 5M retention to 3000 bars per epic:**
- Change `PRELOAD_TARGET_5M_BARS` (or split it: retention target vs. preload target) to 3000.
- Verify `candle_builder._persist_rolling_cache` writes atomically at 3000-row size (it already does; this is a config change).

**Stage M3 — Derive-H1/H4-from-5M at startup:**
- Wire the §5 derivation pipeline into `_startup_preload_symbols` between the rolling-load and HTF cache-load steps.
- Merge derived-with-cached under the contribution-count rule.

**Stage M4 — Persisted daily levels:**
- Add `cache/levels/{SYM}_daily_levels.json` writer at daily rollover (22:00 UTC).
- Add reader in the pivot-consuming strategies; fall through to D1 cache if levels file is missing/stale.

**Stage M5 — Repair-journal-gated REST:**
- Consult repair journal before every historical REST call.
- Enforce cool-off on UNCERTAIN, per-identity dedup on CONFIRMED.
- Only after M0–M4 have proved zero-REST restart on real state.

**Stage M6 — Retire H4 REST from the primary path:**
- H4 REST becomes gap-repair only (§7 last-resort trigger). Cold-start path stops calling REST unconditionally.

**Order-of-operations safety:**
- M0–M4 can land while `points_used=7996` because none of them requires a historical fetch to prove correctness. All can be validated by replay against `data/candles/*.csv`.
- M5 changes call-site behaviour; test in shadow mode first (log-what-would-happen without gating) for at least one week.
- M6 is the final flip; requires M0–M5 stable and demonstrated across ≥10 real restarts.

**Do not reset the 8000 counter as part of migration.** The design goal is precisely that we do not need to.

---

## 13. TEST PLAN

Every test runs against persisted historical corpora + synthetic filesystem states. No live IG required.

| ID | Test | Method |
|---|---|---|
| A | Clean restart with complete cache → 0 REST | Snapshot production `cache/` at a known-good moment; boot in test harness; assert `_rest_fetch_df` call count is 0. |
| B | 10 consecutive restarts → 0 duplicate REST | Boot, allow a genuine gap, verify one REST, then boot 9 more times with no cache mutation. Assert 0 additional REST. |
| C | H1 identical before/after restart | Compare `_h1_closed[sym]` bucket-by-bucket across boots on the same input. Byte-equal OHLC. |
| D | H4 identical before/after restart | Same as C for H4. |
| E | Daily levels identical before/after restart | Compare `pivot/pdh/pdl/r1..r3/s1..s3` for the same trading date across boots. Byte-equal. |
| F | Genuine 5M gap → only missing range requested | Ablate a specific bucket window from 5M cache; boot; verify REST call's `(bucket_start, bucket_end)` matches ablated window. |
| G | Already-repaired gap → no second request | Run F, then boot again with the same ablated cache + repair journal reflecting confirmed fill. Verify 0 REST. |
| H | REST repair failure → strategy abstains | Mock `_rest_fetch_df` to return `(None, None)`; verify strategies that depend on the failed timeframe abstain and log; verify no synthetic-bar fill. |
| I | Uncertain request → conservative accounting | Mock `_rest_fetch_df` to raise `ReadTimeout`; verify reservation moves to UNCERTAIN, points not refunded, repair journal marks identity `uncertain`, cool-off enforced on next boot. |
| J | Corrupt cache → fail closed | Corrupt each cache file in turn (invalid JSON / partial row / mode-mismatch); assert boot detects and fails visibly per timeframe (does not silently rebuild without evidence). |
| K | Daily-boundary restart → correct previous-day levels | Set system clock to 22:05 UTC; boot before D1 cache has been updated; verify levels file falls back to yesterday's data until D1 cache catches up; verify one legitimate D1 REST at 22:15 if D1 cache still absent. |
| L | Weekend restart → no fictitious gaps | Set clock to Saturday 12:00 UTC; ablate Fri 22:00 – Sun 22:00 from 5M cache; verify no REST fires (weekend-subtraction). |
| M | Local budget exhausted + complete cache → strategies still READY without REST | Set `rest_allowance.json` to `points_used=8000`; boot; verify all strategies reach READY, verify 0 REST attempts. **This is the migration-completeness test.** |
| N | Local budget exhausted + essential gap → affected strategy abstains, no bypass | Set budget to exhausted; ablate D1 prior-day; boot; verify pivot-consuming strategies abstain and log; verify no attempt to bypass budget. |

**Test corpus:** `data/candles/GBPUSD/*.csv` already provides several months of 5M data, sufficient for A–N without any live-IG dependency.

**Rerun cadence:** every merge to the feature branch. Publish a report to `reports-public/` showing pass counts per test ID and any regressions.

---

## 14. FINAL DESIGN RETURN

- **CURRENT_RESTART_REST_DEPENDENCY** = Six historical call sites, all at startup. In practice, H4 cold-start (call site #1) fires on nearly every restart because `_h4_closed[sym]` is in-memory only. The other five short-circuit on warm caches.

- **ROOT_CAUSE_OF_RESTART_WARMUP** = No persisted H4 cache. H1 and D1 are on disk (`cache/htf/`), but H4 is aggregated live in `TimeframeContext` memory and lost on process exit. The cold-start REST-primary path is the workaround, and it costs 40 points per symbol per restart.

- **D1_REST_GENUINELY_REQUIRED_EVERY_RESTART** = **NO.** The D1 cache holds ~250 completed-day bars. REST is required only for the one previous-day bar on a fresh trading day and only if the daily rollover writer has not yet run — a per-day event, not a per-restart event.

- **H1_REST_GENUINELY_REQUIRED_EVERY_RESTART** = **NO.** The H1 cache exists and is fresh <1h. Live 5M aggregation refills gaps.

- **H4_REST_GENUINELY_REQUIRED_EVERY_RESTART** = **NO.** With a persisted H4 cache + 3000-bar 5M retention, H4 is fully derivable on startup.

- **PERSISTED_5M_CAN_REMOVE_H1_RESTART_FETCH** = **YES** (already essentially true, and fully true after §4 retention widening).

- **PERSISTED_5M_CAN_REMOVE_H4_RESTART_FETCH** = **YES**, given §4 (3000-bar retention) or §5 with §14's H4 cache addition.

- **PERSISTED_DAILY_LEVELS_CAN_REMOVE_D1_RESTART_FETCH** = **YES** for all restart scenarios within the same trading date; D1 REST is unavoidable only once per new trading day and only if the D1 cache is empty for that day.

- **NORMAL_RESTART_HISTORICAL_REST_TARGET** = 0 requests.

- **RESTART_STORM_DUPLICATE_REQUEST_TARGET** = 0 requests.

- **LOCAL_BUDGET_LONG_TERM_ROLE** = Last-resort weekly ceiling on gap-repair. No longer the primary determinant of restart readiness.

- **IG_ALLOWANCE_TELEMETRY_ROLE** = Observation-only today. In a later phase, minimum-of-(local, IG × 0.8, per-symbol cap) admission rule. Never conflated with local budget in units or period.

- **PROPOSED_COMPONENTS:**
  - `cache/htf/{SYMBOL}_H4.json` (new; mirror of H1 shape)
  - `cache/levels/{SYMBOL}_daily_levels.json` (new; one per epic)
  - `cache/rest_repair_journal.jsonl` (new; append-only)
  - `history_derive.py` (new module; §5 pipeline)
  - `daily_levels.py` (new module; writer at daily rollover, reader for pivot-consuming strategies)
  - Extensions to `htf_cache.py`, `timeframe_context.py`, `autobot.py` startup sequence

- **FILES_LIKELY_TO_CHANGE:**
  - `autobot.py` (startup sequence ~lines 8900-9120; `_v5_pia_h4_cold_start` at 1516-1620; `_rest_fetch_df` at 1348-1468 to consult journal)
  - `timeframe_context.py` (H4 persist path; derivation callers)
  - `htf_cache.py` (H4 support; atomic-write hardening carried over from `rest_allowance.py:238-320`)
  - `candle_builder.py` (`_persist_rolling_cache` retention change)
  - `bb_pd_gate.py` (read from levels file first)
  - `.env` (new keys for retention, cool-off windows, per-symbol caps)
  - `strategy_logic.py` and pivot-consuming strategies (thin adapter to levels file)

- **MIGRATION_STAGES:** M0–M6 (see §12). None require resetting the current 7996 counter.

- **TEST_PLAN:** A–N (see §13). Test M is the definitive migration-completeness proof.

- **RISKS:**
  - **Contribution-count merge rule (§5) mis-attribution.** If a mid-bucket restart writes a low-contribution H4 bar and a subsequent full-bucket derivation misjudges which one is authoritative, the H4 bar could regress. Mitigation: cache-write guards in `htf_cache.py:388-402` already reject in-progress buckets; extend the same guard to H4.
  - **Daily-levels stale-across-rollover.** If the rollover writer fails silently, the next restart still sees yesterday's levels file marked for yesterday's date and refuses to reuse — good, but the strategy will fall back to computing from the D1 cache, which is fine but requires proof by test K.
  - **5M retention widening changes hot-path memory footprint.** 3000 × 7 epics × ~120 bytes ≈ 2.5 MB — negligible. Verify indicator computations do not become O(n²) over 3000 rows (they should not; pandas rolling is O(n)).
  - **Repair-journal file growth.** Bounded by pruning at startup (≤ 2 × budget window). Rotate journal at week rollover.
  - **H4 cache first-population.** Before Stage M1 has been running for one H4 cycle, the H4 cache is empty. Bootstrap by running the §5 derivation once against the (widened) 5M cache — no REST.

- **OPEN_QUESTIONS:**
  - Does IG's per-call allowance charge scale linearly with `numPoints`, or is it flat per call? The current local counter assumes linear; verify empirically against IG's reported `remainingAllowance` before touching the admission rule in §10.
  - `EURGBP`, `GBPJPY`, `AUDUSD` presence in `TRADING_PAIRS` — the 5M retention figures assume they are configured. If they are not, drop them from the retention budget.
  - Should the daily-levels writer run in the AutoBot process or as a separate systemd timer? Recommendation: same process — the writer needs the same D1 cache and the same weekend-guard logic that lives in `htf_cache.py`. A separate timer would duplicate those guards.
  - The `build_deep_cache.py` script bypasses `rest_allowance` (§4 note). Should it be brought under the guard? Recommendation: yes, in a separate ticket — it is not part of the live service but it shares the shared 10k IG pool.

- **IMPLEMENTATION_RECOMMENDATION:**
  1. Land M0 first to size the actual gap on real state (may reveal that H4 cache today already has ≥20 bars in memory 5% of the time, meaning REST is fired unnecessarily even more often than assumed).
  2. M1 + M2 together — persisted H4 + widened 5M retention — remove ~95% of restart REST cost.
  3. M4 (daily levels) is orthogonal; can land in parallel with M1/M2.
  4. M3 (derivation) is the intellectual heart of the design; land after M1/M2 have proven the write side is sound.
  5. M5 (journal-gated REST) and M6 (H4 REST retirement) are the definitive "no restart REST" flips; land only after M0–M4 have accumulated evidence.
  6. Total effort estimate: 3–4 focused sessions if landed in the order above. Each session ends with a `reports-public/` report showing which of tests A–N pass on real state.

- **DO NOT IMPLEMENT.** This is design only.

---

## Confirmation

- **LIVE_SERVICE_TOUCHED** = NO
- **LIVE_IG_CONTACT** = NO
- **TRADE_ENABLED** = 0
- **STAGE10P** = PAUSED

STOP.
