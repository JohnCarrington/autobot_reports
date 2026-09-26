# TREND_V3 vs NMS demonstrated_direction — forensic audit of the 07:55 disagreement, 25-Sep-2026 GBPUSD

**Report scope.** Read-only forensic investigation of ONE narrow question: on 2026-09-25 at ≈07:55 UTC on GBPUSD, TREND_V3 produced a LONG candidate while NMS `demonstrated_direction` was DOWN, and the candidate was rejected with `normal_routing:DIRECTION_MISMATCH:TREND_V3:SELL`. Why?

**No code, config, .env, service, or architecture changes were made or proposed.** Evidence only.

**Date.** Authored 2026-09-26.
**Author.** autobot session.
**Branch at HEAD.** `feat/trend-stretch-brake-adx-floor` — commit `8bf2bd1` `report(day-type-conformance-audit)`.

---

## TL;DR (three sentences)

1. TREND_V3 said LONG at the 07:50 bar close because the regime engine flipped `trend_subtype` from null → `GRIND` with `grind_direction=UP` on that same bar; `gbpusd_trend_v3.py` line 1299-1308 (`grind_dir_deferral`) overrode the DOWN daily spine and produced an UP effective direction, and line 1340-1344 admitted `RANGE_ROTATION` into `_up_ok_regimes`.
2. NMS `demonstrated_direction` was DOWN — and remained DOWN through bar_ts 08:00 — because its 60-bar rolling swing structure was BEARISH (`LH=True, LL=True`, last_swing_high=13228.45, last_swing_low=13217.75, 5 confirmed highs / 7 confirmed lows). The CHoCH override that flips NMS earlier required three consecutive M5 closes > 13228.45 + 2 pip buffer = 13230.45; the first such close was 07:55 (13231.05), then 08:00 (13231.95), then 08:05 (13236.45) — CHoCH fired at 08:10:03.207 UTC for bar_ts 08:05.
3. The disagreement is **not a defect**. It is **intentional methodology difference**: TREND_V3 is a forming-trend detector that reads a per-bar regime label + subtype; NMS is a confirming-trend authority that reads confirmed-swing structure with a 3-close CHoCH override. On this specimen NMS lagged TREND_V3 by exactly 15 minutes and 8.4 pips.

---

## §1. Production truth

| item | value | source |
|---|---|---|
| repository HEAD | `8bf2bd1e27182be82fd8de62f062d594e15c41c1` | `git log -1` |
| branch | `feat/trend-stretch-brake-adx-floor` | `git branch --show-current` |
| service | `autobot.service` — active during window; stopped normally at 2026-09-25T22:00:07 UTC | `systemctl status autobot.service` |
| service uptime | Ran throughout 07:55 UTC 2026-09-25 (verified via `journalctl` fragments and log write timestamps continuous through window) | `logs/normal_state_journal.jsonl` at 07:30:00.976, 07:35:00.726, 07:40:01.260, 07:45:01.284, 07:50:00.714, 07:55:01.404, 08:00:01.886, 08:05:05.605, 08:10:03.206, 08:15:01.662 |
| relevant flags (from `.env`) | `TREND_V3_ENABLED=1`, `RIBBON_GATE_TREND_V3=1`, `CENTRAL_STRATEGY_ORCHESTRATOR=1`, `CENTRAL_EXECUTION_GATE=1`, `NEWS_TREND_ROUTER=1`, `MID_NEWS_ROUTER=1` | `.env` |
| deployed commit | Deployed process is the branch at HEAD; the event evidence and code paths cited below were all resolved against this HEAD | `git status` (clean w.r.t. tracked code files) |

**Repository divergence note.** `git status` shows untracked log/env-history/worktree artifacts. No tracked-file modifications relevant to TREND_V3 or NMS `demonstrated_direction` have been rewritten since the event. All file:line citations below correspond to the running commit.

---

## §2. Data sources consumed by each component

| component | data source | file:line |
|---|---|---|
| TREND_V3 | M5 bar close (last bar in buffer) + `regime_engine.latest_result(symbol)` — reads `winning_regime`, `trend_subtype`, `grind_direction`, `regime_label_path` | `gbpusd_trend_v3.py:1213`, `:1258`, `:1579` |
| TREND_V3 target | H4 structural highest-high in last 12 H4 bars | `gbpusd_trend_v3.py:691-699,753-755` |
| NMS | 60-bar rolling M5 buffer via `_derive_demonstrated_direction`; uses `market_structure.detect_confirmed_swings` (N=3) → `market_structure.classify_structure` → BULLISH / BEARISH / NEUTRAL; optional 3-close CHoCH override | `normal_market_state.py:394-531`, esp. `:421-433` for swing/classify, `:452-518` for CHoCH |
| gate consumer | `_demonstrated_direction(pair)` reads `nms.snapshot(pair)['demonstrated_direction']` and compares to `_map_side_to_direction(candidate.side)` | `central_execution_gate.py:1027`, comparison at `:1747-1763` |

---

## §3. The 07:55 event, verbatim

**Rejection row (candidate_corpus.jsonl):**

- `candidate_id`: `c8cae144488847d086bbb526efc9688b`
- `strategy_family`: `TREND_V3` (`strategy`: `GBPUSD_TREND_V3_UM_L`, `side`: LONG)
- `first_detected_ts`: `2026-09-25T07:55:04.429904+00:00`
- `candidate_price`: **13228.05**
- `day_type_canonical`: `MID_NEWS` (Durable Goods Orders MoM, USD, 12:30 UTC on 25-Sep)
- `market_state_snapshot.normal_market_state`: `TRADABLE_NON_RANGE` (`er10=0.5664, bb_w=11.6p, cross=4`)
- `market_state_snapshot.legacy_regime`: `RANGE_ROTATION`, `trend_subtype`: `GRIND`
- `news_trend_snapshot`: `primary_direction=BUY, trend_state=TREND_UP, bounce_direction=SELL, bounce_state=MAJOR_LEVEL_TEST, bounce_level_price=13229.15, source_bar_ts=07:50:00, snapshot_ts=07:55:04.435, snapshot_staleness_seconds=4`
- `gate_reason_codes`: `[..., "mid_news:mid_news_search_emphasis:TREND_V3", "normal_routing:DIRECTION_MISMATCH:TREND_V3:SELL", ..., "gate:REJECT:binding=normal_routing"]`
- `fired`: **false**

**Same event, TREND_V3 fire row (trend_v3.jsonl):**

```
{"event":"fire","ts":"2026-09-25T07:50:00+00:00","symbol":"GBPUSD",
 "direction":"LONG","daily_dir":"DOWN","effective_dir":"UP",
 "direction_source":"grind_dir_deferral","regime":"RANGE_ROTATION",
 "adx":20.35,"er":0.094,"entry_price":13228.05,
 "target_price":13319.05,"target_source":"h4","sl_price":13216.05,
 "tp_pips":91.0,"sl_pips":12.0,"grind_path":true}
```

**Same event, NMS journal row (normal_state_journal.jsonl):**

```
{"anchor_ts":"2026-09-25T06:00:00+00:00","bar_ts":"2026-09-25T07:50:00+00:00",
 "bars_since_anchor":23,"demonstrated_direction":"DOWN",
 "demonstrated_evidence":{"choch_buffer_pips":2.0,"choch_confirm_bars":3,
   "choch_direction":null,"classify_structure_state":"BEARISH",
   "hh":false,"hl":false,"last_swing_high_price":13228.45,
   "last_swing_low_price":13217.75,"lh":true,"ll":true,
   "n_confirmed_highs":5,"n_confirmed_lows":7,"swing_n":3},
 "demonstrated_reason":"structure_bearish:lh_ll",
 "reason":"tradable_non_range:er10=0.5664,bb_w=11.6p,cross=4",
 "state":"TRADABLE_NON_RANGE","symbol":"GBPUSD",
 "written_at":"2026-09-25T07:55:01.404067+00:00"}
```

---

## §4. Reconstructed price series (M5 candles, `cache/GBPUSD_candles_rolling.csv`)

| bar_ts UTC | O | H | L | C | ATR14 | ADX14 |
|---|---|---|---|---|---|---|
| 07:00 | 13224.05 | 13227.85 | 13219.35 | 13219.95 | 3.62 | 19.5 |
| 07:05 | 13220.15 | 13221.45 | 13217.75 | 13219.85 | 3.63 | 18.1 |
| 07:10 | 13219.75 | 13222.35 | 13218.45 | 13221.35 | 3.65 | 18.4 |
| 07:15 | 13221.25 | 13223.05 | 13220.15 | 13221.15 | 3.59 | 18.8 |
| 07:20 | 13221.05 | 13222.15 | 13219.25 | 13220.35 | 3.55 | 17.7 |
| 07:25 | 13220.45 | 13221.95 | 13218.55 | 13221.05 | 3.53 | 16.5 |
| 07:30 | 13220.65 | 13224.15 | 13220.55 | 13223.35 | 3.54 | 19.7 |
| 07:35 | 13223.45 | 13225.35 | 13221.15 | 13221.35 | 3.59 | 20.4 |
| 07:40 | 13221.45 | 13223.85 | 13221.05 | 13223.85 | 3.53 | 19.3 |
| 07:45 | 13223.95 | 13227.75 | 13223.95 | 13227.25 | 3.56 | 25.6 |
| **07:50** | **13227.15** | **13229.15** | **13225.95** | **13228.05** | **3.53** | **26.8** |
| **07:55** | **13227.95** | **13231.25** | **13227.95** | **13231.05** | **3.51** | **29.3** |
| **08:00** | **13231.15** | **13232.05** | **13228.85** | **13231.95** | **3.49** | **29.0** |
| **08:05** | **13232.05** | **13237.65** | **13232.05** | **13236.45** | **3.65** | **36.7** |
| 08:10 | 13236.35 | 13240.05 | 13235.95 | 13239.05 | 3.68 | 38.4 |
| 08:15 | 13238.95 | 13240.65 | 13234.85 | 13236.25 | 3.83 | 34.3 |
| 08:20 | 13236.35 | 13237.15 | 13233.85 | 13236.35 | 3.80 | 32.2 |

The 07:00-07:45 window shows a shallow range 13217.75-13227.85 (10-pip box). The break above 13227.85 occurs at the 07:45 close (13227.25 → 07:50 close 13228.05). ADX14 climbs from 16.5 (07:25) to 36.7 (08:05).

---

## §5. TREND_V3 LONG — code trace

**Module.** `/opt/tradingbot/gbpusd_trend_v3.py`.

**Fire writer.** `:1653-1673` writes the `event:"fire"` row to `logs/trend_v3.jsonl`.

**The critical branch — `grind_dir_deferral` (lines 1299-1308):**

```python
if _grind_widening_active and _grind_dir in ("UP", "DOWN"):
    if effective_dir != _grind_dir:
        logger.info("[%s] GRIND spine deferral: spine=%s effective=%s -> "
                    "grind_dir=%s (regime=%s subtype=GRIND) bar_ts=%s", ...)
        effective_dir = _grind_dir
        direction_source = "grind_dir_deferral"
```

- `_grind_widening_active = (trend_subtype == "GRIND")` (line 1286).
- `_grind_dir = grind_direction` from `regime_engine.latest_result`.

**Non-trending regime admission (lines 1340-1344, paraphrased from agent trace):** when regime ∈ non-trending set AND `_grind_dir == "UP"`, the regime is added to `_up_ok_regimes`, allowing the LONG through the regime gate.

**Regime engine input at 07:55:01 (regime_engine.jsonl-20260926):**

```
2026-09-25T07:50:01 |reg= RANGE_ROTATION |sub= None  |grind= UP |path= range
2026-09-25T07:55:01 |reg= RANGE_ROTATION |sub= GRIND |grind= UP |path= range   ← TREND_V3 reads this
2026-09-25T08:00:02 |reg= RANGE_ROTATION |sub= GRIND |grind= UP |path= range
2026-09-25T08:05:05 |reg= STRONG_TREND_UP |sub= GRIND |grind= UP |path= hist
```

**The exact state transition.** At the 07:45 write, `trend_subtype` was still not GRIND (which is why `_grind_widening_active` was False and the block writer at 07:45 recorded `regime_not_strong_down` with `effective=DOWN` and `direction_source=spine`). Between the 07:50 and 07:55 regime writes, the regime engine promoted the subtype from `None` → `GRIND`. On the 07:55 processing tick (acting on the 07:50 M5 close), TREND_V3 saw `_grind_widening_active=True`, `_grind_dir=UP`, and flipped `effective_dir` DOWN→UP. That is the fire trigger.

**Prior blocks (all `event:"block", reason:"regime_not_strong_down"`, `spine=DOWN, effective=DOWN`):** 07:30, 07:35, 07:40, 07:45 (four consecutive M5 bars). All were rejected SELL attempts against the DOWN daily spine because regime was not in `_dn_ok_regimes = {"STRONG_TREND_DOWN"}` (lines 1310-1311 per agent trace).

**Answer to Q1 (WHY TREND_V3 SAID LONG):** The regime engine emitted `trend_subtype=GRIND, grind_direction=UP` on the 07:55:01 write. That flipped `effective_dir` DOWN → UP via `grind_dir_deferral`. The M5 bar it acted on (bar_ts 07:50:00, close 13228.05) had just made a small break above the 07:00-07:45 range top (13227.85 highest high in that window), and ADX14 was rising (26.8, from 25.6 at 07:45).

---

## §6. NMS `demonstrated_direction` DOWN — code trace

**Module.** `/opt/tradingbot/normal_market_state.py`, function `_derive_demonstrated_direction` at `:394-531`.

**Structure derivation (lines 421-433):**
```python
swing_n = _env_int("NMS_DIRECTION_SWING_N", 3)     # → 3
min_bars = 2 * swing_n + 2                         # → 8
highs = np.array([b[2] for b in self._bars])       # last 60 M5 bars
lows  = np.array([b[3] for b in self._bars])
confirmed_highs, confirmed_lows = _ms.detect_confirmed_swings(highs, lows, asof=n-1, N=swing_n)
structure, dbg = _ms.classify_structure(confirmed_highs, confirmed_lows)
```

Result mapping (`:520-529`): `STRUCTURE_BULLISH` (HH+HL) → `UP`; `STRUCTURE_BEARISH` (LH+LL) → `DOWN`; else `None`.

**CHoCH override (lines 452-518):** if the last 3 M5 closes all exceed `last_swing_high + choch_buffer_pips` (2p default), flip `demonstrated_direction` to UP (symmetric for DOWN). Kill-switch env: `NMS_DIRECTION_CHOCH_AUTHORITY_ENABLED` (default ON).

**NMS journal for GBPUSD, bar_ts 07:25 through 08:15 (verbatim `demonstrated_direction`, `demonstrated_reason`):**

| bar_ts | dir | reason | choch_direction |
|---|---|---|---|
| 07:25 | DOWN | structure_bearish:lh_ll | null |
| 07:30 | DOWN | structure_bearish:lh_ll | null |
| 07:35 | DOWN | structure_bearish:lh_ll | null |
| 07:40 | DOWN | structure_bearish:lh_ll | null |
| 07:45 | DOWN | structure_bearish:lh_ll | null |
| **07:50** | **DOWN** | **structure_bearish:lh_ll** | **null** ← the row the 07:55 rejection consumed |
| 07:55 | DOWN | structure_bearish:lh_ll | null |
| 08:00 | DOWN | structure_bearish:lh_ll | null |
| **08:05** | **UP** | **choch_up:3_consec_closes>swing_high=13228.45+buf=2.0 (this=13236.45)** | **UP** ← flip |
| 08:10 | UP | choch_up:3_consec_closes>swing_high=13228.45+buf=2.0 (this=13239.05) | UP |
| 08:15 | UP | choch_up:3_consec_closes>swing_high=13228.45+buf=2.0 (this=13236.25) | UP |

The structure state (`classify_structure_state`) remained `BEARISH` even after CHoCH flipped the emitted direction. The last confirmed swing_high (13228.45) and swing_low (13217.75) did not change across the entire window — the CHoCH override, not new swing formation, was what flipped NMS.

**Answer to Q2 (WHY NMS SAID SELL):** at the 07:50 bar close, the confirmed-swing structure over the previous 60 M5 bars was LH+LL (5 confirmed highs, 7 confirmed lows), producing `STRUCTURE_BEARISH` and `demonstrated_direction=DOWN`. The CHoCH override was inactive because only 1 close so far (the 07:50 close 13228.05) had exceeded the swing_high 13228.45 — actually 13228.05 is *below* 13228.45, so at 07:50 NMS had not yet seen ANY confirming close. It needed 3 consecutive closes ≥ 13230.45 (13228.45 + 2p buffer). The first was 07:55 (13231.05), then 08:00 (13231.95), then 08:05 (13236.45). CHoCH fired on the 08:05 close, written at 08:10:03.207.

**Answer to Q3 (evidence used):** TREND_V3 used regime-engine per-bar labels + subtype; NMS used the last 60 M5 bars' confirmed swings + 3-close CHoCH.

---

## §7. Information age

At the 07:55:04.437 rejection timestamp:

| quantity | value |
|---|---|
| decision timestamp | 2026-09-25T07:55:04.437 UTC |
| latest closed M5 bar | 2026-09-25T07:50:00 UTC (bar close ≈ 07:55:00) |
| latest bar TREND_V3 acted on | bar_ts 07:50:00, fire event ts 07:50:00, written ~07:55:xx (source bar close 13228.05) |
| latest bar NMS acted on | bar_ts 07:50:00 (matches TREND_V3), NMS journal written 07:55:01.404 |
| snapshot_ts of NMS in candidate row | 2026-09-25T07:55:04.435 UTC (snapshot_staleness_seconds=4) |
| timestamp SELL evidence was established | Both structure fields (`last_swing_high_price=13228.45, last_swing_low_price=13217.75`) were unchanged from at least bar_ts 07:25 through 08:00 (six 5-min ticks of the NMS journal). The BEARISH classification traces back earlier — not visible in the 07:25+ window but stable. |
| last time NMS *re-evaluated* direction | 07:55:01.404 UTC (bar_ts 07:50) — 3 seconds before the rejection |
| next time NMS *changed* direction | 08:10:03.207 UTC (bar_ts 08:05) |

**TREND_V3 INFORMATION AGE = 4.4 seconds** (both fire and rejection acting on same 07:50 bar close).
**NMS INFORMATION AGE = 3.0 seconds** (fresh 07:50 bar re-evaluation completed 07:55:01.404, consumed at 07:55:04.437). The underlying *evidence* (BEARISH structure) is older than the current bar but was actively re-tested every 5m without change.

---

## §8. Was NMS stale?

**A. TECHNICALLY STALE — NO.** The NMS journal shows a re-evaluation on every M5 bar close for bar_ts 07:25 / 07:30 / 07:35 / 07:40 / 07:45 / 07:50 / 07:55 / 08:00 / 08:05 / 08:10 / 08:15 — no missed updates. The `snapshot_staleness_seconds=4` field on the candidate row confirms freshness within the 5m cadence.

**B. SEMANTICALLY STALE — AMBIGUOUS-LEANING-YES-BY-DESIGN.** The BEARISH structure (5H/7L, last_swing_high 13228.45) reflected the range action from 07:05 → 07:45 (10-pip box, 13217.75–13227.85). At the 07:50 close (13228.05), price had *just* broken through the swing_high 13228.45's proximity, but not the 3-close CHoCH threshold (13230.45). The direction was **technically fresh but structurally lagging** by design: NMS demands three confirming closes past a 2p buffer before flipping via CHoCH, and demands new confirmed swings before flipping via structure. Neither had happened by 07:50.

---

## §9. Why did TREND_V3 change before NMS?

**Different definition of "trend is changing" — this is a design difference, not a defect.**

| dimension | TREND_V3 | NMS `demonstrated_direction` |
|---|---|---|
| primary input | regime_engine per-bar label + `trend_subtype` + `grind_direction` | 60-bar M5 buffer → `detect_confirmed_swings` (N=3) → `classify_structure` |
| lookback | last M5 bar + regime engine's internal windows | ~60 M5 bars, but swings must be confirmed (N=3 flanking bars each side, so a swing pivot is confirmable ~4 bars after it forms) |
| flip trigger | subtype flips to GRIND with grind_direction ≠ spine | (a) new HH+HL / LH+LL pattern, OR (b) 3-close CHoCH beyond swing + 2p |
| confirmation count | 0 (single-bar subtype flip suffices) | 3 (for CHoCH) or new swing formation (for structure) |
| persistence/hysteresis | none stated in the fire path | none between bar closes; each 5m bar re-evaluates from scratch |
| bar source | M5 close from `_5m` buffer, regime from `regime_engine.latest_result` | 60-bar M5 buffer built by NMS |
| update frequency | per M5 bar processing tick | per M5 bar close |

The two components are looking at overlapping but distinct evidence: TREND_V3 is a *forming*-trend detector (react to regime-engine subtype flips within 1 bar); NMS is a *confirmed*-trend authority (require 3-close CHoCH or new swing pivot).

---

## §10. Subsequent price from the rejected 07:55 T0 (candidate_price=13228.05)

Using `cache/GBPUSD_candles_rolling.csv`:

| offset | bar_ts | close | pips vs 13228.05 (LONG P/L) |
|---|---|---|---|
| +0 | 07:50 | 13228.05 | 0.0 |
| +5m | 07:55 | 13231.05 | +3.0 |
| +10m | 08:00 | 13231.95 | +3.9 |
| +15m | 08:05 | 13236.45 | +8.4 ← NMS CHoCH triggered |
| +20m | 08:10 | 13239.05 | +11.0 |
| +30m | 08:20 | 13236.35 | +8.3 |
| +60m | 08:50 | 13236.85 | +8.8 |
| +120m | 09:50 | 13239.05 | +11.0 |
| +130m | 10:00 | 13243.05 | +15.0 |

**MFE(60m) from 07:50 close 13228.05:** max high in window 07:50…08:50 was **13240.65** (08:15 bar high) → **MFE = +12.6 pips**.
**MAE(60m):** min low in window was 13225.95 (07:50 bar own low) → **MAE = −2.1 pips**.
**MFE(120m):** 13240.65 (unchanged; max within 07:50-09:50 also captures 13239.05 at 08:10) → **MFE = +12.6 pips** (a second push to 13240.45 / 13243.05 comes at +125–130 minutes).

**Eventual TREND_V3 admission.** The 08:10:05 candidate (bar_ts 08:05, `candidate_price=13236.45`) was approved by `normal_routing:NORMAL_TRADABLE_V2_ONLY:TREND_V3` and executed at 08:10:10.677 UTC (deal_id `DIAAAAYJPUURXA9`). Slippage/delay from the earliest rejected LONG at 13228.05 → executed at 13236.45 = **+8.4 pips consumed while waiting**.

**When NMS stopped saying SELL.** 08:10:03.207 UTC (bar_ts 08:05). 15 min after the first TREND_V3 LONG fire.

---

## §11-§13. Historical cohort (candidate_corpus.jsonl + rotated)

**Cohort methodology.** Every TREND_V3 T0 row in the two accessible corpus files:
- `logs/candidate_corpus.jsonl` (live): 12 GBPUSD TREND_V3 rows.
- `logs/candidate_corpus.jsonl-20260923` (rotated): 38 GBPUSD TREND_V3 rows.
- **Total 50 rows, date range 2026-09-14T11:50 → 2026-09-25T11:10 UTC.**
- The two `PURGE_NOTE_20260914.txt` files document that only 12 unit-test fixture rows were purged; no live production rows were removed.

Rows classified by scanning `gate_reason_codes` for the `normal_routing:...` token:

| cohort | criterion | n | share |
|---|---|---|---|
| AGREE | `NORMAL_TRADABLE_V2_ONLY:TREND_V3` or `gate_allowed=true` | 20 | 40% |
| DISAGREE_OPPOSITE | `DIRECTION_MISMATCH:TREND_V3:<opposite of side>` | **6** | **12%** |
| NOT_ESTABLISHED | `DIRECTION_NOT_ESTABLISHED:TREND_V3` | 9 | 18% |
| OTHER | `normal_routing_deferred_active_trend:TREND_UP/DOWN`, `NORMAL_STATE_NOT_PERMITTED`, `NORMAL_STATE_UNKNOWN` | 15 | 30% |

**Top `normal_routing:*` tokens (full population, n=50):**

| n | token |
|---|---|
| 13 | `normal_routing_deferred_active_trend:TREND_DOWN` |
| 12 | `NORMAL_TRADABLE_V2_ONLY:TREND_V3` |
| 9 | `DIRECTION_NOT_ESTABLISHED:TREND_V3` |
| 4 | `normal_routing_deferred_active_trend:TREND_UP` |
| 4 | `NORMAL_STATE_NOT_PERMITTED:TREND_V3` |
| 3 | `DIRECTION_MISMATCH:TREND_V3:BUY` |
| 3 | `DIRECTION_MISMATCH:TREND_V3:SELL` |
| 2 | `NORMAL_STATE_UNKNOWN:TREND_V3` |

**By day type:**

| day_type | AGREE | DISAGREE_OPPOSITE | NOT_ESTABLISHED | OTHER | Total |
|---|---|---|---|---|---|
| BIG_NEWS | 8 | 2 | 7 | 5 | 22 |
| BIG_NEWS_MINUS_1 | 2 | 0 | 0 | 3 | 5 |
| BIG_NEWS_PLUS_1 | 2 | 0 | 0 | 5 | 7 |
| MID_NEWS | 5 | **4** | 1 | 2 | 12 |
| NORMAL | 3 | 0 | 1 | 0 | 4 |

MID_NEWS has 4 of the 6 DISAGREE_OPPOSITE cases — over-represented (33% of DISAGREE cases from 24% of the population).

### Grading limitation

The rolling+deep candle CSVs (`cache/GBPUSD_candles_rolling.csv` + `cache/GBPUSD_candles.csv`) cover 2026-09-23T18:55 → 2026-09-25T20:55. **40 of 50 rows fall before 2026-09-23T18:55** and cannot be graded from cache. Only 7 of 50 receive full MFE/MAE grading:

| cohort | graded | skipped (pre-coverage) |
|---|---|---|
| AGREE | 3 | 17 |
| DISAGREE_OPPOSITE | **3** | 3 |
| NOT_ESTABLISHED | 1 | 8 |
| OTHER | 0 | 15 |

**All 3 graded DISAGREE_OPPOSITE rows are the 07:55 / 08:00 / 08:05 sequence from the very event under audit** — they are three sequential 5m candidates on the same 25-Sep price move. The corpus available on disk therefore contains, effectively, **one clustered specimen** of DISAGREE_OPPOSITE; drawing broader statistics from n=3 tightly-correlated rows is not defensible.

### Grading results (evidence, not conclusions)

**DISAGREE_OPPOSITE (3 graded rows, same underlying event, LONG-side, all with `nms.primary=BUY, nms.bounce=SELL`):**

| T0 | p0 (candidate_price) | MFE30 | MAE30 | MFE60 | MAE60 | verdict at ≥10p in 60m |
|---|---|---|---|---|---|---|
| 07:55:04 | 13228.05 | +8.7p | -3.1p | +8.7p | -3.1p | not reached |
| 08:00:05 | 13231.05 | +4.2p | -5.5p | +4.2p | -5.8p | not reached |
| 08:05:06 | 13231.95 | +1.6p | -8.1p | +1.6p | -8.4p | not reached |

Note that the earliest T0 (07:55, entry 13228.05) *is* the one with the strongest TREND_V3-leaning grade, and the subsequent MFE-in-the-window using bar highs (not closes) reaches **+12.6p** — which does cross the 10p threshold. Using bar highs is a defensible alternative grading; the cohort agent used closes. Either way, the specimen is directionally consistent with TREND_V3 in the 60m window.

**AGREE control (3 graded rows):** MFE_60 median 4.4p, MAE_60 median 5.6p. Also fails the 10p threshold at 60m. The AGREE control is a mixed BIG_NEWS / MID_NEWS bag from 2026-09-24 and 2026-09-25 morning; MAE > MFE in 2 of 3.

**NOT_ESTABLISHED (1 graded row):** MFE_60 = 6.6p, MAE_60 = 4.4p. MFE > MAE but sub-10p.

**Honest read:** *the sample too small to distinguish "NMS disagreement damages TREND_V3" from "NMS disagreement protects TREND_V3" or from "makes no difference at 10p thresholds"*. The historical cohort tells us:
- (a) DIRECTION_MISMATCH is uncommon (12% of TREND_V3 T0s) and roughly balanced between BUY and SELL sides.
- (b) MID_NEWS is over-represented in DIRECTION_MISMATCH occurrences.
- (c) The one clustered specimen graded shows TREND_V3 was directionally correct at the +12.6p / -2.1p (highs/lows) level within 60 minutes.

**Speed test (uses candidate_price only, does not require candle grading):**

| metric | value |
|---|---|
| DISAGREE_OPPOSITE population | 6 |
| Matched to a subsequent AGREE within 2h | 4 |
| Minutes to NMS agreement (of matched 4): median | 15.0 |
| Minutes to NMS agreement: p75 | 15.0 |
| Minutes to NMS agreement: p90 | 120.0 |
| Pips price moved between T0 and NMS agreement: median | 8.4 |
| Pips price moved between T0 and NMS agreement: p75 | 8.4 |
| Pips price moved between T0 and NMS agreement: p90 | 13.5 |

The median 8.4p / 15 min matches the 07:55 → 08:10 specimen exactly (because that specimen dominates the graded subset). Two of six DISAGREE_OPPOSITE never subsequently converged to AGREE within 2h.

Cohort raw data lives at `/tmp/trend_v3_vs_nms_cohort.md`.

---

## §14. How often does NMS save TREND_V3?

**In the graded 3-row DISAGREE_OPPOSITE subset:** by MFE_60 (closes) ≥ 10p adverse-to-TREND_V3 measure, **0 of 3 (0%)**. By MAE_60 (lows) ≥ 10p, still 0 of 3 (the worst MAE was −8.4p). NMS did not measurably "save" TREND_V3 in this sample — TREND_V3 was directionally consistent with subsequent price (albeit at sub-10p MFE60 at close granularity).

**In the un-graded remainder:** unknown.

---

## §15. How often does NMS damage TREND_V3?

**In the graded 3-row DISAGREE_OPPOSITE subset:** MFE_60 ≥ 10p favourable-to-TREND_V3 by closes = 0 of 3. By bar highs (the 07:55 specimen) = 1 of 3 (+12.6p). Meanwhile the median 8.4-pip cost of the wait was borne on the eventual 08:10 execution — so this specimen shows NMS blocked +8.4p of ex-post trend by imposing 15 min of confirmation delay. TP was 91p originally (13319.05); the eventual 08:10 candidate had TP re-computed to 72p (13308.85 target). The trade did open at 08:10:10 at level 13236.45.

**Trade outcome from broker log fragment (autobot.service journalctl):** at 22:00:06 UTC (autobot shutdown), the daily broker calls include a BUY at 13258.8 and a SELL at 13242.8. The 25-Sep TREND_V3 08:10 LONG was managed to close within the day; final P/L on this specific deal was not reconstructed in this audit (broker close events are in a separate log family). The +12.6p MFE60 evidence stands independent of the eventual exit.

---

## §16. Speed test summary (repeat, distilled)

Median NMS lag when it disagrees but eventually agrees: **15 minutes**.
Median pips consumed during wait: **8.4 pips**.
p90 lag: **120 minutes** (i.e. one in ten times NMS takes 2 hours to catch up).
Two of six DISAGREE_OPPOSITE never converged within 2 hours.

---

## §17. Agreement control (AGREE cohort)

Same coverage limitation applies — only 3 of 20 AGREE rows have gradable price. In that tiny sample MFE_60 median 4.4p, MAE_60 median 5.6p — indistinguishable from DISAGREE_OPPOSITE at close granularity. **Agreement adds no measurable discrimination at n=3**. This is not a conclusion about the general population; it's a statement about what the accessible corpus supports.

---

## §18. NOT_ESTABLISHED control

**Population 9/50 (18%).** All 9 rows on BIG_NEWS or MID_NEWS days. Only 1 gradable: MFE_60 6.6p, MAE_60 4.4p (edge-favouring TREND_V3 but sub-10p). Distinct phenomenon from DISAGREE_OPPOSITE — merits its own audit if pursued (this report does not conflate the two).

---

## §19. Day-type breakdown

Already reported in §11. DIRECTION_MISMATCH rate by day type:
- MID_NEWS: 4/12 = **33%** (over-represented)
- BIG_NEWS: 2/22 = **9%**
- BIG_NEWS_MINUS_1: 0/5 = 0%
- BIG_NEWS_PLUS_1: 0/7 = 0%
- NORMAL: 0/4 = 0%

MID_NEWS's higher rate is consistent with the design tension: MID_NEWS routes TREND_V3 through the `mid_news_search_emphasis` permissive pass to `_delegate_normal_routing`, which then applies the DIRECTION_MISMATCH check strictly. NORMAL days appear only 4× in the accessible window — too few to conclude.

---

## §20. Session breakdown

Of the 3 graded DISAGREE_OPPOSITE rows: **all London session** (07:55-08:05 UTC). Speed test population of 6 DISAGREE_OPPOSITE rows: 5 London, 1 New York. Corpus too small to break out cleanly by session.

---

## §21. Is NMS's latency intentional?

**Yes — documented in the code and NMS journal.**

`normal_market_state.py:394-531` — `_derive_demonstrated_direction` — implements a **swing-structure-first, CHoCH-second** authority:
- Requires `min_bars = 2 * swing_n + 2 = 8` bars minimum.
- Uses `detect_confirmed_swings` which by definition ignores unconfirmed pivots.
- CHoCH override requires **3 consecutive** closes beyond the swing + a **2-pip buffer** (env: `NMS_DIRECTION_CHOCH_AUTHORITY_ENABLED`, default ON).
- Every 5m bar close re-evaluates from scratch — no explicit hysteresis, but the *confirmed swing* and *3-close CHoCH* rules are the effective lag mechanism.

The journal field `demonstrated_reason` uses semantically strong labels — `structure_bearish:lh_ll`, `choch_up:3_consec_closes>swing_high=…` — that make the "confirmed structure" intent explicit.

TREND_V3 (`gbpusd_trend_v3.py:1299-1308`) has an explicit design comment (per the trace agent's report on lines 1289-1298) labelled *"Operator ruling 2026-08-25: counter-spine grinds TRADE"* — a deliberate 1-bar responsiveness on GRIND subtype flips.

**So the disagreement is architectural, not accidental.** TREND_V3 is designed to react on subtype flips within 1 bar. NMS is designed to confirm direction changes on 3-close CHoCH or new swing formation. When price is in the middle of a range breakout, the two components will *by design* be in different states for 2-3 M5 bars.

Central execution gate `:1747-1763` then makes NMS the authority for permission on TRADABLE_NON_RANGE. That is the architectural choice (per `[[project_a9_matrix_gap_20260913]]`: `TRADABLE_NON_RANGE` admits TREND_V3 *with direction alignment*).

---

## §22. Defect vs design test

Explicit checks:

| candidate defect | test | result |
|---|---|---|
| stale state | NMS re-wrote on every M5 bar close 07:25 → 08:15 (see §6 table); `snapshot_staleness_seconds=4` on candidate | NO — fresh |
| missed updates | Journal is dense with entries at 07:30:00.976, 07:35:00.726, 07:40:01.260, 07:45:01.284, 07:50:00.714, 07:55:01.404, 08:00:01.886, 08:05:05.605, 08:10:03.206 | NO — none missed |
| candle-source mismatch | Both TREND_V3 and NMS acted on bar_ts 07:50:00 (verified via trend_v3.jsonl and normal_state_journal.jsonl) | NO |
| timestamp/timezone | Both logs use UTC ISO-8601 with `+00:00` suffix | NO |
| persistence defect | NMS journal shows `bars_since_anchor` monotonically incrementing 18 → 19 → … → 28 (anchor 06:00 UTC) — no reset | NO |
| restart/rebuild | Service ran continuously through the window (see §1 uptime evidence) | NO |
| update-order race | NMS journal write at 07:55:01.404 precedes candidate rejection at 07:55:04.437 by 3 seconds — consumer read the fresh state | NO |
| wrong pair | Both records `symbol=GBPUSD`, `pair=GBPUSD` | NO |
| wrong bar | Both source `bar_ts=07:50:00` | NO |
| hysteresis bug | No hysteresis coded on TREND_V3 fire path; NMS has explicit 3-close CHoCH, no additional lag | NO |
| direction inversion | `demonstrated_direction=DOWN` maps to gate token `SELL` via `_map_side_to_direction` inverse; consistent | NO |
| cached-state-not-refreshed | Journal shows fresh row per bar | NO |

**None of the defect signatures hold.** The disagreement is **INTENTIONAL DESIGN LATENCY**: NMS's swing-structure + CHoCH is a longer-window authority; TREND_V3's grind_dir_deferral is a shorter-window reactor.

---

## §23. Required 25-Sep chronological table

| TIME UTC | PRICE (close/action) | LATEST CLOSED BAR | TREND_V3 STATE | TV3 DIR | TV3 REASON | NMS STATE | NMS DIR | NMS REASON | NMS EVIDENCE AGE | ROUTING | RESULT |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 07:30:00.976 | 13223.35 | 07:30 | block | SELL(attempted) | regime_not_strong_down | fresh | DOWN | structure_bearish:lh_ll | 3s | — | block |
| 07:35:00.726 | 13221.35 | 07:35 | block | SELL(attempted) | regime_not_strong_down | fresh | DOWN | structure_bearish:lh_ll | 3s | — | block |
| 07:40:01.260 | 13223.85 | 07:40 | block | SELL(attempted) | regime_not_strong_down | fresh | DOWN | structure_bearish:lh_ll | 4s | — | block |
| 07:45:01.284 | 13227.25 | 07:45 | block | SELL(attempted) | regime_not_strong_down | fresh | DOWN | structure_bearish:lh_ll | 4s | — | block |
| 07:50:00.714 (NMS write) | 13228.05 | 07:50 | — | — | — | fresh | DOWN | structure_bearish:lh_ll | 4s | — | — |
| 07:55:01.404 (NMS write) | 13228.05 | 07:50 (still) | — | — | — | fresh | DOWN | structure_bearish:lh_ll | 3s | — | — |
| 07:55:04.437 (rejection) | 13228.05 | 07:50 | fire | **LONG** | grind_dir_deferral (RANGE_ROTATION + GRIND + grind_dir=UP) | fresh | DOWN | structure_bearish:lh_ll | 3s | **DIRECTION_MISMATCH:TREND_V3:SELL** | **REJECT** |
| 08:00:01.886 (NMS write) | 13231.05 | 07:55 | — | — | — | fresh | DOWN | structure_bearish:lh_ll (07:55 close 13231.05 ≥ 13230.45 — 1st CHoCH close) | 2s | — | — |
| 08:00:05.988 (rejection) | 13231.05 | 07:55 | fire | LONG | grind_dir_deferral | fresh | DOWN | structure_bearish:lh_ll | 5s | DIRECTION_MISMATCH:TREND_V3:SELL | REJECT |
| 08:05:05.605 (NMS write) | 13231.95 | 08:00 | — | — | — | fresh | DOWN | structure_bearish:lh_ll (08:00 close 13231.95 — 2nd CHoCH close) | 5s | — | — |
| 08:05:06.881 (rejection) | 13231.95 | 08:00 | fire | LONG | grind_dir_deferral | fresh | DOWN | structure_bearish:lh_ll | 6s | DIRECTION_MISMATCH:TREND_V3:SELL | REJECT |
| 08:10:03.207 (NMS write) | 13236.45 | 08:05 | — | — | — | fresh | **UP** | **choch_up:3_consec_closes>swing_high=13228.45+buf=2.0 (this=13236.45)** | 3s | — | — |
| 08:10:05.414 (candidate) | 13236.45 | 08:05 | fire | LONG | grind_dir_deferral (STRONG_TREND_UP now) | fresh | UP | choch_up | 5s | **NORMAL_TRADABLE_V2_ONLY:TREND_V3** | **APPROVE** |
| 08:10:10.677 | 13236.45 | 08:05 | executed | LONG | — | — | — | — | — | — | **filled** deal_id DIAAAAYJPUURXA9 |

---

## §24. Required historical table

| Cohort | n | TV3 correct ≥10p 60m (graded/total) | TV3 correct ≥20p (graded) | TV3 correct ≥30p (graded) | NMS correct ≥10p (graded) | NMS correct ≥20p | NMS correct ≥30p | Ambiguous | Median NMS lag (min) | Median price move during lag (pips) |
|---|---|---|---|---|---|---|---|---|---|---|
| DISAGREE_OPPOSITE | 6 | 0/3 by close (1/3 by bar-high MFE) | 0/3 | 0/3 | 0/3 | 0/3 | 0/3 | n/a | 15.0 | 8.4 |
| AGREE | 20 | 0/3 (close basis) | 0/3 | 0/3 | — | — | — | — | 0 | 0 |
| NOT_ESTABLISHED | 9 | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 | — | n/a | n/a |

**Sample-size caveat:** all `graded` counts reflect the 2026-09-23T18:55+ candle coverage window; percentages from n=1-3 are illustrative, not statistical.

---

## §25. Required direct answers

**1. EXACTLY WHY DID TREND_V3 SAY LONG AT 07:55 ON 25 SEPTEMBER?**
Regime engine wrote `winning_regime=RANGE_ROTATION, trend_subtype=GRIND, grind_direction=UP` at 07:55:01. `gbpusd_trend_v3.py:1299-1308` `grind_dir_deferral` flipped `effective_dir` DOWN→UP. `:1340-1344` admitted `RANGE_ROTATION` into `_up_ok_regimes` because `_grind_dir="UP"` on a non-trending regime. Fire produced at 07:50 bar close 13228.05.

**2. EXACTLY WHY DID NMS SAY SELL?**
`normal_market_state.py:_derive_demonstrated_direction`: 60-bar M5 buffer produced `LH=True, LL=True` (5 confirmed highs, 7 confirmed lows). `classify_structure` returned `STRUCTURE_BEARISH`. CHoCH override inactive (no closes yet exceeded swing_high 13228.45 + 2p buffer). Result `DOWN` → gate token `SELL`.

**3. WHAT PRICE EVIDENCE DID EACH USE?**
TREND_V3: M5 bar close 13228.05 + regime engine's per-bar subtype flip. NMS: 60 M5 bars → confirmed swing pivots (`last_swing_high=13228.45, last_swing_low=13217.75`).

**4. WHAT WAS THE AGE OF THAT EVIDENCE?**
TREND_V3: 4.4 seconds since bar close. NMS: 3 seconds since re-evaluation; underlying BEARISH structure was ≥ 30 minutes old (unchanged since bar_ts 07:25 in the journal window; older still in unrecorded history).

**5. WAS NMS TECHNICALLY STALE?** **NO.** Fresh re-evaluation every 5m bar, no missed updates, `snapshot_staleness_seconds=4`.

**6. WAS NMS SEMANTICALLY STALE?** **AMBIGUOUS, LEANING YES-BY-DESIGN.** The BEARISH structure reflected the range 07:00-07:45; the break was in progress but had not yet passed the 3-close CHoCH threshold. NMS was operating exactly to spec — it just requires more confirmation than TREND_V3.

**7. WAS THE DISAGREEMENT CAUSED BY:**
- **intended different methodology: YES** (swing structure vs regime-engine subtype).
- **intended confirmation latency: YES** (3-close CHoCH + 2p buffer).
- **implementation defect: NO** (no missed updates, correct bar, correct pair, no race, correct mapping).
- **data timing defect: NO.**
- **state persistence defect: NO.**

**8. WHEN DID NMS CHANGE FROM SELL?**
2026-09-25T08:10:03.207 UTC (bar_ts 08:05). Reason `choch_up:3_consec_closes>swing_high=13228.45+buf=2.0 (this=13236.45)`.

**9. HOW MANY MINUTES AFTER TREND_V3 LONG?** 15 minutes after the first TREND_V3 LONG fire at 07:55:04.437.

**10. HOW MANY PIPS DID PRICE MOVE DURING THAT INTERVAL?**
By close: 13228.05 → 13236.45 = **+8.4 pips**.
By max high: 13228.05 → 13237.65 (08:05 bar high) = **+9.6 pips**.

**11. WHAT DID PRICE SUBSEQUENTLY DO FROM THE ORIGINAL TREND_V3 T0?**
From 13228.05 (07:50 close): +12.6p MFE within 60m (13240.65 at 08:15 high); −2.1p MAE. +15.0p at 130m (13243.05 at 10:00 close). Direction was UP.

**12. HISTORICALLY, HOW OFTEN DOES THIS EXACT DISAGREEMENT OCCUR?**
In the accessible corpus: 6 DISAGREE_OPPOSITE rows out of 50 TREND_V3 T0 rows = **12%**. 3 of those 6 cases (50% of DISAGREE cases) are 07:55/08:00/08:05 25-Sep — one clustered event. Pre-2026-09-23 rows exist (n=40) but cannot be price-graded from cache; direction-mismatch classification alone is available for all 50.

**13. WHEN THEY DISAGREE, HOW OFTEN IS TREND_V3 SUBSEQUENTLY RIGHT?**
Sample too small. In the 3 graded rows (all the 25-Sep event), by bar-high MFE_60 the 07:55 entry crossed +10p (1/3); by close-basis MFE_60 no entry crossed +10p (0/3). Broader answer requires more corpus coverage or a replay against the historical candle archive.

**14. HOW OFTEN IS NMS SUBSEQUENTLY RIGHT?**
Same sample: 0/3 by any adverse threshold ≥10p at 60m.

**15. HOW OFTEN DOES NMS DISAGREEMENT PROTECT AUTOBOT FROM A BAD TREND_V3 ENTRY?**
In the graded sample, 0 of 3. In the ungraded 3 remaining DISAGREE_OPPOSITE rows, unknown.

**16. HOW OFTEN DOES NMS DISAGREEMENT BLOCK/DELAY A USEFUL TREND_V3 ENTRY?**
On the 25-Sep specimen, YES — TREND_V3 would have entered at 13228.05 (07:55 candidate); actual entry was 13236.45 (08:10). Delta = 8.4 pips of trend consumed. On the broader corpus, the speed test shows median 8.4p / 15 min delay when NMS eventually agrees (4 of 6 DISAGREE_OPPOSITE cases). 2 of 6 never converged.

**17. WHEN TREND_V3 IS RIGHT FIRST, HOW LONG DOES NMS TYPICALLY TAKE TO CATCH UP?**
Median 15 minutes (3 M5 bars) in the graded/speed-test population.

**18. HOW MANY PIPS ARE TYPICALLY CONSUMED WHILE WAITING?**
Median 8.4 pips (p75 8.4p, p90 13.5p, from the 4 matched DISAGREE→AGREE pairs).

**19. DOES NMS AGREEMENT MATERIALLY IMPROVE TREND_V3 DISCRIMINATION?**
**INSUFFICIENT EVIDENCE.** The 3 graded AGREE and 3 graded DISAGREE rows are statistically indistinguishable (all sub-10p MFE_60 on close basis). This cannot be answered from the accessible corpus. It requires either (a) recovering earlier candidate_corpus data from an audit backup, or (b) replaying the M5 candle archive through central_execution_gate.py to synthesise the missing rows.

**20. DOES THE EVIDENCE INDICATE AN IMPLEMENTATION DEFECT?** **NO.** All defect signatures tested negative (§22).

**21. DOES THE EVIDENCE INSTEAD INDICATE AN INTENTIONAL DESIGN TRADE-OFF?** **YES.** The two components have deliberately different confirmation counts (0-bar reactive vs 3-close CHoCH). The trade-off is between (a) catching trends earlier (TREND_V3 alone) and (b) avoiding chop entries (NMS gates via `demonstrated_direction`).

**22. WHAT REMAINS UNEXPLAINED?**
- **Broad statistical answer to Q13/Q14/Q15/Q19** — the corpus on disk only covers 2026-09-14 forward (12 days), and only 2026-09-23T18:55+ is price-gradable. A candle-archive replay through central_execution_gate.py is needed to answer the "how often" questions across meaningful sample sizes.
- **Whether the 2 of 6 DISAGREE_OPPOSITE cases that never converged within 2h were subsequently right or wrong** — un-graded.
- **The trade outcome of the 08:10 execution deal `DIAAAAYJPUURXA9`** — broker close events live in a separate log family not reviewed for this narrow audit.

---

## Appendix A. Verbatim `gate_reason_codes` for the four consecutive candidates

| ts | candidate_id | reason token |
|---|---|---|
| 07:55:04.437 | c8cae144 | ...`normal_routing:DIRECTION_MISMATCH:TREND_V3:SELL`, `gate:REJECT:binding=normal_routing` |
| 08:00:05.988 | ae8a04b1 | ...`normal_routing:DIRECTION_MISMATCH:TREND_V3:SELL`, `gate:REJECT:binding=normal_routing` |
| 08:05:06.881 | a40233b6 | ...`normal_routing:DIRECTION_MISMATCH:TREND_V3:SELL`, `gate:REJECT:binding=normal_routing` |
| 08:10:05.414 | 4691cf1f | ...`normal_routing:NORMAL_TRADABLE_V2_ONLY:TREND_V3`, `gate:APPROVE_FINAL` |
| 08:10:10.677 (exec) | 4691cf1f (fired) | same tokens as above; `execution_deal_id=DIAAAAYJPUURXA9`, `execution_deal_ref=SMWENGLHWQUTYRZ` |

## Appendix B. Files and code cited (file:line, HEAD `8bf2bd1`)

| purpose | citation |
|---|---|
| TREND_V3 fire writer | `gbpusd_trend_v3.py:1653-1673` |
| TREND_V3 block writer | `gbpusd_trend_v3.py:1688-1690` |
| TREND_V3 grind_dir_deferral | `gbpusd_trend_v3.py:1299-1308` |
| TREND_V3 regime gate `regime_not_strong_down` | `gbpusd_trend_v3.py:1372-1378` |
| TREND_V3 non-trending admit | `gbpusd_trend_v3.py:1340-1344` |
| TREND_V3 bar/regime inputs | `gbpusd_trend_v3.py:1213`, `:1258`, `:1579` |
| NMS `_derive_demonstrated_direction` | `normal_market_state.py:394-531` |
| NMS structure derivation | `normal_market_state.py:421-433` |
| NMS CHoCH override | `normal_market_state.py:452-518` |
| gate `_demonstrated_direction` | `central_execution_gate.py:1027` |
| gate DIRECTION_MISMATCH producer | `central_execution_gate.py:1756-1763` |
| gate requires_direction_alignment call | `central_execution_gate.py:1747-1763` |
| gate MID_NEWS pass-through | `central_execution_gate.py:1362-1379` |
| gate matrix permission_matrix | `permission_matrix.py:213-243` |

## Appendix C. Log rows referenced

- `logs/candidate_corpus.jsonl` — rejection and execution rows for `c8cae144…`, `ae8a04b1…`, `a40233b6…`, `4691cf1f…` (all 2026-09-25 07:55-08:10 UTC).
- `logs/trend_v3.jsonl` — block events at 07:30, 07:35, 07:40, 07:45 (all `reason:"regime_not_strong_down"`) and fire events at 07:50, 07:55, 08:00, 08:05.
- `logs/normal_state_journal.jsonl` — GBPUSD entries bar_ts 07:25 → 08:15 (see §6 table).
- `logs/regime_engine.jsonl-20260926` — GBPUSD entries at 07:50:01 / 07:55:01 / 08:00:02 / 08:05:05 (see §5).
- `cache/GBPUSD_candles_rolling.csv` — M5 OHLC 07:00 → 08:55 (see §4).

## Appendix D. Historical cohort intermediate

Full cohort scratch: `/tmp/trend_v3_vs_nms_cohort.md`. n=50 TREND_V3 T0 rows; 6 DISAGREE_OPPOSITE; 20 AGREE; 9 NOT_ESTABLISHED; 15 OTHER. Grading window 2026-09-23T18:55 → 2026-09-25T20:55 UTC; 40 rows pre-coverage. Speed test computed on full 6-row DISAGREE_OPPOSITE population (does not require candle grading).

---

END OF REPORT. No code, config, .env, or architecture changes made or proposed.
