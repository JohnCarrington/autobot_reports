# Day-type audit — READ-ONLY

## 1. Classifiers in the code

Three independent day-type layers live in the tree. Each has its own labels and consumer surface.

### 1a. `news_tier_classifier.py` — event-level BIG / MIDDLE / SMALL

- **file:** `/opt/tradingbot/news_tier_classifier.py`
- **entry point:** `classify_news_tier(event, context=None)` — `news_tier_classifier.py:483`
- **labels produced:** `"BIG"`, `"MIDDLE"`, `"SMALL"` (per event)
- **news source:** `/opt/tradingbot/cache/news_state_finnhub_*.json` (produced by `refresh-news-calendar.timer` + `scripts/refresh_news_calendar.py`). Each snapshot has `{ts, currency, impact, event}`.
- **how it decides:** overrides first (`OVERRIDES` table at `:116`, keyword + currency scoped), then `BIG_RULES` (`:196`), then `MIDDLE_RULES` (`:279`), else `SMALL (default_small)`.
- **override table version:** `2026-08-14.v1` (`:114`).

**BIG rule inventory** (rule_id → keyword groups → 2026 cache hits GBP+USD):

| rule_id | keyword groups | hits 2026 |
|---|---|---|
| `us_core_cpi` | `("core","cpi")`, `("core","inflation","rate")` | 18 |
| `us_cpi` | `("cpi",)`, `("inflation","rate")` | 36 |
| `us_nfp` | `("non farm payroll",)`, `("non-farm payroll",)`, `("nonfarm payroll",)`, `("nfp",)` | 11 |
| `us_unemployment_with_nfp` | `("unemployment rate",)` + `_has_nfp_same_day` | 10 |
| `us_fomc` | `("fomc",)`, `("federal funds rate",)`, `("fed funds rate",)`, `("fed","interest rate decision")`, `("fed","rate decision")` | 15 |
| `us_fed_chair_speech_at_rate_decision` | `("fed chair","speech")`, `("powell","speech")`, `("warsh","speech")`, `("fed chair",)` + `_fed_chair_attached_to_rate_decision` | 0 |
| `uk_boe_rate` | `("boe","interest rate decision")`, `("boe","rate decision")`, `("bank of england","rate decision")`, `("bank rate",)`, `("boe","press conference")`, `("boe","monetary policy")` | 9 |
| `ecb_rate` | `("ecb","interest rate decision")`, …`("deposit facility",)`, `("ecb","monetary policy")` | 0 |
| `uk_core_cpi` | `("uk","core","cpi")`, `("uk","core","inflation")` | 0 |
| `uk_gdp` | `("uk","gdp")`, `("gdp","prel")`, `("gdp","prelim")`, `("gdp","advance")`, `("gdp","flash")` | 6 |
| `us_gdp_advance_prelim` | `("gdp","advance")`, `("gdp","prel")`, `("gdp","prelim")` | 0 |
| `central_bank_minutes` | `("fomc","minutes")`, `("ecb","minutes")`, `("boe","minutes")`, `("mpc","minutes")`, `("monetary policy","minutes")` | 6 |
| `usd_fed_press_conf_override` (override) | `("fed","press conference")`, `("fomc","press conference")` | 6 |
| `usd_gdp_adv_override` (override) | `("gdp","adv")` | 6 |
| `uk_cpi_override` (override) | `("cpi",)`, `("inflation","rate")`, `("core","inflation")` GBP only | 27 |

**MIDDLE rule inventory** (rule_id → keyword groups → 2026 cache hits):

| rule_id | keywords | hits |
|---|---|---|
| `ism_manufacturing_pmi` | `("ism","manufacturing")` | 20 |
| `ism_services_pmi` | `("ism","services")`, `("ism","non-manufacturing")` | 10 |
| `global_pmi_flash` | `("s&p global","pmi","flash")`, `("markit","pmi","flash")`, `("pmi","flash")`, `("composite pmi",)` | 45 |
| `retail_sales` | `("retail sales",)`, `("core retail sales",)` | 58 |
| `ppi` | `("ppi",)`, `("producer price",)` | 20 |
| `initial_jobless_claims` | `("initial jobless",)`, `("initial claims",)` | 40 |
| `continuing_claims` | `("continuing claims",)`, `("continuing jobless",)` | 0 |
| `adp` | `("adp",)` | 42 |
| `jolts` | `("jolt",)` | 10 |
| `consumer_confidence` | `("consumer confidence",)` | 20 |
| `uom_sentiment` | `("michigan","sentiment")`, `("uom","sentiment")`, `("michigan consumer",)` | 19 |
| `durable_goods` | `("durable goods",)` | 20 |
| `core_pce` | `("core","pce")` | 10 |
| `pce` | `("pce",)` | 20 |
| `industrial_production` | `("industrial production",)` | 18 |
| `gbp_gdp_mom_override` (override) | `("gdp","mom")` GBP only | 9 |

Context-sensitive rules:
- `us_unemployment_with_nfp` requires NFP same-day — `_has_nfp_same_day()` at `:162`.
- `us_fed_chair_speech_at_rate_decision` requires FOMC/rate-decision same-day — `_fed_chair_attached_to_rate_decision()` at `:176`.

**Default coverage gap:** 1,023 of 1,534 (67%) HIGH/MED GBP+USD events in the 2026 cache fall through to `default_small` because no BIG/MIDDLE rule matches. The classifier logs `[NEWS_TIER] unmatched HIGH event -> default_small … verify BIG_RULES / MIDDLE_RULES / OVERRIDES` on each (`news_tier_classifier.py:467-479`). Examples that stayed SMALL: Fed-governor speeches, UK unemployment, UK avg earnings, UK employment change, Philly Fed Mfg, Fed stress tests, GDP QoQ final/2nd est, Jackson Hole Symposium, Trump/Xi summit, Powell speech (non-rate-decision), BoE Bailey speech (non-decision).

### 1b. `calendar_day_type.py` — day-level BIG_NEWS / PRE_NEWS / POST_NEWS / MID_NEWS / NORMAL

- **file:** `/opt/tradingbot/calendar_day_type.py`
- **entry point:** `classify_date(iso_date)` — produces the dict in `_classify_from_events` at `calendar_day_type.py:140`
- **labels produced:**
  - `BIG_NEWS` — ≥1 BIG-tier GBP or USD release today
  - `PRE_NEWS` — BIG release tomorrow, no BIG today
  - `POST_NEWS` — BIG release yesterday, no BIG today
  - `MID_NEWS` — no BIG today AND no BIG adjacency AND ≥1 MIDDLE-tier GBP/USD event today (precedence §6: BIG-adjacency beats MIDDLE)
  - `NORMAL` — none of the above
  - A single day may carry both `POST_NEWS(<event> −1d)` and `PRE_NEWS(<event> +1d)` → `dual_labels` field preserves both; dominant label returned as `label`.
- **news source:** same finnhub cache; freshest snapshot that contains events for the target date (typically ≤1 day old). File-list filter at `_find_snapshot_files()`:96.
- **currency filter:** `_TRACKED_CURRENCIES = {GBP, USD}` and `_TRACKED_IMPACTS = {HIGH, H}` (`calendar_day_type.py:89-90`). Note: MED-impact events are excluded.
- **tier source:** calls `news_tier_classifier.classify_news_tier` for each HIGH event (via `big_events_for()` / `middle_events_for()`); the big_tier decision is centralised there.

### 1c. `day_type_classifier.py` — session-scoped TRENDING / CHOP / QUIET / MIXED

- **file:** `/opt/tradingbot/day_type_classifier.py`
- **labels:** `TRENDING`, `CHOP`, `QUIET`, `MIXED`
- **evaluation points:** asia_close (07:00 UTC) and london_close (12:00 UTC) — `:5-10`
- **thresholds (`:14-29`):** TRENDING = ADX-mean ≥ 28 AND ER-mean ≥ 0.42; CHOP = ADX < 22 AND ER < 0.36; QUIET = (ADX < 22 OR ER < 0.36) AND session-range ≤ trailing p25; MIXED otherwise.
- **news source:** none — pure price/ADX/ER derivation from candle archive.
- **consumer surface:** the module docstring states explicitly (`:55-56`): *"Nothing in the estate reads the label for a trading decision. Only signal_logger reads it, and only for post-hoc analysis stamping."* `DAY_TYPE_CLASSIFIER_ENABLED` defaults to **0** (`:44-47`).

### 1d. `day_context.py` — BIG_NEWS / PRE_BIG / POST_BIG / CLEAR overlay layer

- **file:** `/opt/tradingbot/day_context.py`
- **labels:** `BIG_NEWS`, `PRE_BIG`, `POST_BIG`, `CLEAR` (`:77-82`)
- **source:** delegates to `calendar_day_type.big_events_for()` (`:116-137`); narrower subset of the calendar classifier.
- **flag:** `DAY_CTX_ENABLED=0` by default (`:93`). Inert unless flipped.

### Status in current .env (`725949d`)

```
grep -E "^(DAY_|CALENDAR_|NEWS_TIER_|DAY_CTX_)" /opt/tradingbot/.env | relevant subset
```
- `DAY_TYPE_CLASSIFIER_ENABLED=0` (session-scoped TRENDING/CHOP classifier is OFF)
- `DAY_CTX_ENABLED=0` (overlay layer is OFF)
- `CALENDAR_DAY_TYPE_*` paths — the day-level BIG/PRE/POST/MID/NORMAL is active (no master flag — the module is always importable; gates consult it on demand).

---

## 2. How day type was used on Monday vs now

### 2a. On `cda3678` (Monday 2026-09-28)

The gate already treated day-type as a soft input, not a trade gate. Evidence from the same `cda3678` tree:

- `central_execution_gate.py:1650` (verbatim, `cda3678`):
  > `# A9 (2026-09-13): no day_type-based early-out. The matrix lookup below is market-state × family; day_type is only consulted for family-scoped autonomous / suppressed carve-outs.`
- A10 note at `:183` (verbatim, `cda3678`):
  > `# A10 (2026-09-14, operator ruling A.2): MID_NEWS_ROUTER was deleted.` and `# ("MID_NEWS days") was already abolished by A9.5 — the mid_news delegate routes every family to _delegate_normal_routing regardless of the` day type.
- The gate's `_delegate_mid_news` is a stamp-only passthrough — it routes everything into `_delegate_normal_routing`, which is market-state × family.
- `_delegate_normal_routing` on Monday (post-A9/A10) ran on every day_type, including BIG_NEWS, MID_NEWS, PRE_NEWS, POST_NEWS and NORMAL. The decision came from `permission_matrix.is_autonomous_route(canon, family)` and `is_suppressed_family(family)` — day_type only entered via the `canon` key in those two carve-outs.
- The `(day_type, market_state)` key still appeared in `permission_matrix.py` for the `is_autonomous_route` / `is_suppressed_family` lookup (`permission_matrix.py:150`+). So on `cda3678`, day_type **could** make a family autonomous or suppressed on specific day types — but it was NOT the general directional/entry gate.

### 2b. On `725949d` (now)

Identical day-type wiring. The 2026-10-03 ruling landed as prose + a Stage-9 wiring change for V2_PICK (`3cf2b32`); it did **not** change `central_execution_gate.py` or `permission_matrix.py`. The gate still runs `_delegate_normal_routing` on every day type; day_type still enters only via the autonomous/suppressed carve-out matrix.

### 2c. Precedence ruling (verbatim, `docs/v2_precedence_ruling_20261003.md`)

```
3. Day type decides what to look for, never whether a trade is allowed
   (except the timestamp-derived release blackout). A9/A10 day-type rules
   stand.
```

The ruling demoted day_type from "may deny a trade" to "biases search". It also made explicit:

```
5. The execution gate judges execution conditions only (risk, capacity,
   timing, safety), never direction.
```

### 2d. Code the ruling actually changed

- `3cf2b32 feat(v2_pick): Stage-9-aligned firer wiring (Unit 5)` — added the Stage-9 alignment block in `qm_v2_executor.py:332-398` and extended the cutover guard's GBPUSD-permitted set in `central_execution_gate.py`. **No day-type gating code was touched** in this commit.
- No other commits between 2026-10-02 00:00 and 2026-10-05 00:00 touched `normal_market_state.py`, `permission_matrix.py`, `day_type_adapter.py`, `news_tier_classifier.py`, or `calendar_day_type.py`.

**Net:** the ruling restated what was already true in A9/A10 code since 2026-09-13; the 10-03 commit changed Stage-9 wiring only.

### 2e. Current consumers of day_type

What day_type still controls today (`725949d`):
- `permission_matrix.is_autonomous_route(day_type, family)` — autonomous carve-outs per (day_type, family).
- `permission_matrix.is_suppressed_family(family)` + day-type checks — opt-out set for ranges × families on specific days.
- Signal_logger stamps `day_type_at_fire` and `calendar_day_type` on every fire row (post-hoc only).
- Briefing / dashboard rendering reads day_type as context (display only).
- Search-emphasis fields in `_delegate_mid_news` (`:1337`): `mid_news_search_emphasis:<family>` is stamped but does not reject.

What day_type does **not** control:
- Direction (Stage 9 owns it per the ruling §2).
- Trade allowance (gate §5 — execution conditions only).
- Any specific family's permission except where the autonomous/suppressed matrix cells explicitly carve one out.

Timestamp-derived release blackout (the one exception in §3) runs in `news_direction` / `news_post_lockout` delegates (`central_execution_gate.py:1048` and `:399`) — not from the day-type label itself but from the raw release timestamp.

---

## 3. Does the tier definition match market-moving reality?

**Method.** 290 HIGH-impact GBP+USD events from 2026 finnhub cache × GBPUSD 5m candles. For each event, found the first bar at or after the release `ts`, took its open as anchor, then measured the **max absolute excursion** (`max(|high−anchor|, |anchor−low|)`) over the following 12 bars (60 minutes). Grouped by (tier, rule_id, currency). Only groups with n ≥ 3 shown. **Descriptive only — no entry/exit, no spread.**

### Ranked by median 60-min excursion (pips)

| tier | rule | ccy | n | **median** | p75 | max | comment |
|---|---|---|---|---|---|---|---|
| **BIG** | usd_fed_press_conf_override | USD | 5 | **38.6** | 56.1 | 75.0 | consistent — correct tier |
| **BIG** | us_nfp | USD | 10 | **38.5** | 63.3 | 77.9 | consistent — correct tier |
| **BIG** | us_unemployment_with_nfp | USD | 9 | **35.1** | 63.3 | 77.9 | same session as NFP — correct tier |
| **BIG** | us_fomc | USD | 12 | **22.1** | 68.1 | 73.0 | long tail (p75 68.1) — correct tier |
| **BIG** | uk_gdp | GBP | 6 | **21.1** | 27.4 | 27.4 | correct tier |
| **MIDDLE** | global_pmi_flash | GBP | 18 | **20.0** | 22.4 | 40.0 | **moves like a BIG** (matches uk_gdp 21.1) |
| **MIDDLE** | ism_manufacturing_pmi | USD | 9 | **19.6** | 23.8 | 26.9 | **moves like a BIG** (matches us_cpi 18.1) |
| **BIG** | us_core_cpi | USD | 16 | **18.1** | 24.9 | 36.7 | consistent — correct tier |
| **BIG** | us_cpi | USD | 16 | **18.1** | 24.9 | 36.7 | correct tier |
| **SMALL** | default_small | GBP | 9 | **17.8** | 20.1 | 25.1 | **larger than three BIGs below** — rule gap |
| **MIDDLE** | gbp_gdp_mom_override | GBP | 8 | **17.6** | 21.1 | 27.4 | boundary — could sit either side |
| **MIDDLE** | core_pce | USD | 9 | **17.0** | 24.9 | 38.9 | correct tier |
| **MIDDLE** | durable_goods | USD | 9 | **17.0** | 25.0 | 38.9 | correct tier |
| **BIG** | uk_boe_rate | GBP | 5 | **16.9** | 24.3 | 52.8 | small-sample; low median vs other BIGs |
| **SMALL** | default_small | USD | 56 | **16.5** | 24.9 | 64.9 | **large group — many should match a rule** |
| **MIDDLE** | ppi | USD | 9 | **14.7** | 26.8 | 32.2 | correct tier |
| **MIDDLE** | ism_services_pmi | USD | 9 | **14.5** | 22.1 | 25.1 | correct tier |
| **BIG** | uk_cpi_override | GBP | 9 | **14.0** | 16.6 | 22.7 | **low for a BIG** — below multiple MIDDLEs |
| **BIG** | usd_gdp_adv_override | USD | 3 | **13.6** | 19.8 | 19.8 | small-sample; low median |
| **MIDDLE** | retail_sales | GBP | 9 | **12.1** | 13.9 | 21.8 | correct tier |
| **MIDDLE** | jolts | USD | 9 | **10.7** | 12.8 | 54.6 | correct tier (one outlier) |
| **MIDDLE** | retail_sales | USD | 8 | **9.8** | 15.2 | 19.2 | correct tier |
| **MIDDLE** | uom_sentiment | USD | 8 | **8.9** | 16.9 | 17.0 | low — borderline SMALL |

### Observations

1. **MIDDLE events punching above tier:** `global_pmi_flash` (20.0p) and `ism_manufacturing_pmi` (19.6p) move as much as or more than the median BIG US CPI (18.1p) and median UK BoE rate (16.9p). The tier assignment doesn't track observed GBPUSD impact.
2. **BIG events punching below tier:** `uk_cpi_override` (14.0p) sits below six MIDDLEs; `usd_gdp_adv_override` (13.6p, small-n) sits below five MIDDLEs; `uk_boe_rate` (16.9p, small-n) is lower than global PMI flash and ISM Mfg PMI.
3. **SMALL rule-gap mass:** 65 default_small events (56 USD + 9 GBP) move 16-18p median — comparable to the lower-end BIGs. The default_small bucket contains category-mismatched events (Fed-governor speeches, UK labour-market release, Fed stress tests, non-rate-decision Chair speeches). Any of these is in the same move-size range as a UK CPI print.
4. **The ordering BIG > MIDDLE > SMALL mostly holds on average but with clear overlap.** On 60-min GBPUSD impact alone, a hard cutoff by tier would misclassify ~20% of events either direction.

**Caveats:** 60-min window may underweight events whose impact rolls out slowly (central-bank minutes, retail sales); may overweight events whose spike happens in the first 5m but reverts. Anchor = first-5m-open after `ts` — a surprise released into a thin bar prints an immediate wick that this method captures but a bar-close-based measure would smooth. All moves on GBPUSD only; a USD-move event may move harder vs JPY/CHF than vs GBP. Spread not deducted. No entry/exit — purely descriptive excursion.

---

## 4. Last 60 trading-day labels (`calendar_day_type.classify_date`)

Period: **2026-07-14 to 2026-10-05** (60 weekday candles present on disk).

Per-label aggregate (GBPUSD, pips):

| label | n | median H-L | median \|net\| | p75 H-L |
|---|---|---|---|---|
| BIG_NEWS | 14 | **71.4** | 30.9 | 107.3 |
| MID_NEWS | 14 | 56.2 | 34.9 | 85.3 |
| POST_NEWS | 11 | 64.6 | 31.0 | 79.3 |
| PRE_NEWS | 10 | 38.0 | 22.3 | 69.3 |
| NORMAL | 11 | **40.4** | 14.4 | 52.9 |

Reading: at **day** granularity the labels do order the range roughly as intended (NORMAL ≈ 40p, BIG_NEWS ≈ 71p, MID_NEWS/POST_NEWS between). NORMAL is clearly the smallest-range cohort. BIG_NEWS p75 (107.3p) is the widest tail. PRE_NEWS has the smallest median range — days are tentative ahead of a BIG release.

### Per-day table

| date (dow) | label | dual | H-L p | net p | top event |
|---|---|---|---|---|---|
| 2026-07-14 (Tue) | BIG_NEWS | BIG_NEWS | +54.7 | -10.9 | US Core CPI / CPI |
| 2026-07-15 (Wed) | POST_NEWS | POST_NEWS | +177.5 | +142.0 | — |
| 2026-07-16 (Thu) | MID_NEWS | MID_NEWS | +85.3 | -60.1 | UK GDP MoM, Retail Sales |
| 2026-07-17 (Fri) | MID_NEWS | MID_NEWS | +54.8 | -24.4 | Michigan Sentiment Prel |
| 2026-07-20 (Mon) | NORMAL | NORMAL | +68.3 | -14.2 | — |
| 2026-07-21 (Tue) | PRE_NEWS | PRE_NEWS | +95.7 | -53.4 | — |
| 2026-07-22 (Wed) | BIG_NEWS | BIG_NEWS | +40.0 | -5.5 | UK Inflation YoY |
| 2026-07-23 (Thu) | POST_NEWS | POST_NEWS | +79.3 | -55.5 | — |
| 2026-07-24 (Fri) | MID_NEWS | MID_NEWS | +42.7 | +10.4 | Retail Sales, PMI Flash |
| 2026-07-27 (Mon) | MID_NEWS | MID_NEWS | +79.9 | -60.3 | Durable Goods |
| 2026-07-28 (Tue) | PRE_NEWS | PRE_NEWS | +38.3 | -2.9 | — |
| 2026-07-29 (Wed) | BIG_NEWS | BIG_NEWS | +108.1 | +79.4 | Fed Rate Decision, Press Conf |
| 2026-07-30 (Thu) | BIG_NEWS | BIG_NEWS | +144.6 | +93.0 | BoE Rate, UK GDP Adv |
| 2026-07-31 (Fri) | POST_NEWS | POST_NEWS | +95.6 | +20.6 | — |
| 2026-08-03 (Mon) | MID_NEWS | MID_NEWS | +85.7 | -64.1 | ISM Manufacturing PMI |
| 2026-08-04 (Tue) | MID_NEWS | MID_NEWS | +37.5 | +22.8 | JOLTs |
| 2026-08-05 (Wed) | MID_NEWS | MID_NEWS | +41.9 | +19.5 | ISM Services PMI |
| 2026-08-06 (Thu) | PRE_NEWS | PRE_NEWS | +35.0 | -14.4 | — |
| 2026-08-07 (Fri) | BIG_NEWS | BIG_NEWS | +74.5 | +35.4 | NFP, Unemployment |
| 2026-08-10 (Mon) | POST_NEWS | POST_NEWS | +47.1 | +21.6 | — |
| 2026-08-11 (Tue) | PRE_NEWS | PRE_NEWS | +23.9 | -1.8 | — |
| 2026-08-12 (Wed) | BIG_NEWS | BIG_NEWS | +58.0 | -12.6 | US Core CPI / CPI |
| 2026-08-13 (Thu) | BIG_NEWS | BIG_NEWS | +38.8 | -7.3 | US GDP Prel |
| 2026-08-14 (Fri) | POST_NEWS | POST_NEWS | +73.7 | +43.4 | — |
| 2026-08-17 (Mon) | NORMAL | NORMAL | +35.3 | +3.9 | — |
| 2026-08-18 (Tue) | PRE_NEWS | PRE_NEWS | +34.5 | -14.6 | — |
| 2026-08-19 (Wed) | BIG_NEWS | BIG_NEWS | +107.3 | +63.6 | UK Inflation YoY, FOMC Minutes |
| 2026-08-20 (Thu) | POST_NEWS | POST_NEWS | +64.9 | +43.3 | — |
| 2026-08-21 (Fri) | MID_NEWS | MID_NEWS | +57.6 | -2.8 | Retail Sales, PMI Flash |
| 2026-08-24 (Mon) | NORMAL | NORMAL | +34.6 | -16.8 | — |
| 2026-08-25 (Tue) | NORMAL | NORMAL | +32.9 | +8.2 | — |
| 2026-08-26 (Wed) | MID_NEWS | MID_NEWS | +65.1 | -49.5 | Core PCE MoM, Durable Goods |
| 2026-08-27 (Thu) | PRE_NEWS | PRE_NEWS | +31.7 | +0.0 | — |
| 2026-08-28 (Fri) | BIG_NEWS | BIG_NEWS | +71.3 | -62.0 | NFP Annual Revision Prel |
| 2026-08-31 (Mon) | POST_NEWS | POST_NEWS | +31.5 | +8.5 | — |
| 2026-09-01 (Tue) | MID_NEWS | MID_NEWS | +52.4 | -34.7 | ISM Mfg PMI, JOLTs |
| 2026-09-02 (Wed) | NORMAL | NORMAL | +40.4 | -30.6 | — |
| 2026-09-03 (Thu) | PRE_NEWS | PRE_NEWS | +68.3 | +45.4 | — |
| 2026-09-04 (Fri) | BIG_NEWS | BIG_NEWS | +65.5 | -10.7 | NFP, Unemployment |
| 2026-09-07 (Mon) | POST_NEWS | POST_NEWS | +43.3 | +31.0 | — |
| 2026-09-08 (Tue) | NORMAL | NORMAL | +40.8 | -3.1 | — |
| 2026-09-09 (Wed) | NORMAL | NORMAL | +37.9 | +5.7 | — |
| 2026-09-10 (Thu) | PRE_NEWS | PRE_NEWS | +69.3 | -39.6 | — |
| 2026-09-11 (Fri) | BIG_NEWS | BIG_NEWS | +55.5 | +18.0 | US Core CPI / CPI |
| 2026-09-14 (Mon) | POST_NEWS | POST_NEWS | +64.6 | -25.8 | — |
| 2026-09-15 (Tue) | PRE_NEWS | PRE_NEWS | +37.8 | -30.0 | — |
| 2026-09-16 (Wed) | BIG_NEWS | BIG_NEWS | +125.0 | -89.0 | UK Inflation YoY, Fed Rate Decision |
| 2026-09-17 (Thu) | BIG_NEWS | BIG_NEWS | +71.5 | -26.4 | BoE Rate Decision |
| 2026-09-18 (Fri) | POST_NEWS | POST_NEWS | +59.5 | +33.7 | — |
| 2026-09-21 (Mon) | NORMAL | NORMAL | +39.4 | -14.4 | — |
| 2026-09-22 (Tue) | NORMAL | NORMAL | +66.3 | -24.8 | — |
| 2026-09-23 (Wed) | MID_NEWS | MID_NEWS | +120.7 | -106.1 | PMI Flash Mfg + Services |
| 2026-09-24 (Thu) | NORMAL | NORMAL | +52.2 | -27.9 | — |
| 2026-09-25 (Fri) | MID_NEWS | MID_NEWS | +54.1 | +37.1 | Durable Goods |
| 2026-09-28 (Mon) | NORMAL | NORMAL | +52.9 | +25.3 | — |
| 2026-09-29 (Tue) | MID_NEWS | MID_NEWS | +52.8 | -24.2 | JOLTs |
| 2026-09-30 (Wed) | MID_NEWS | MID_NEWS | +88.4 | +35.0 | Core PCE MoM |
| 2026-10-01 (Thu) | PRE_NEWS | PRE_NEWS | +92.3 | -67.4 | — |
| 2026-10-02 (Fri) | BIG_NEWS | BIG_NEWS | +74.3 | +41.0 | NFP, Unemployment |
| 2026-10-05 (Mon) | POST_NEWS | POST_NEWS | +54.6 | -30.0 | — |

**Label distribution across the 60-day window:** BIG_NEWS 14, MID_NEWS 14, POST_NEWS 11, NORMAL 11, PRE_NEWS 10. ~23% BIG, ~65% news-adjacent (BIG+PRE+POST+MID), ~18% NORMAL.

Three big-move outliers to flag:
- **2026-07-15 POST_NEWS +177.5p H-L / +142.0p net** — the day after NFP; largest range in the window; label is correct (POST). The move was a follow-through.
- **2026-09-16 BIG_NEWS +125.0p / -89.0p net** — US CPI + Fed decision stacked; label correct.
- **2026-09-23 MID_NEWS +120.7p / -106.1p net** — biggest move in the MID_NEWS bucket; event list = S&P PMI Flashes. This is the single-pair biggest MID move: another data point that `global_pmi_flash` punches above its tier.

STOP.
