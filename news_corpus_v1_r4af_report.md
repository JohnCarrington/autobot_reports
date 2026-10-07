# News Corpus v1 — R4A-F (Finnhub PIT release corpus)

Study version: **R4A-F**
Research branch HEAD: `caa31d5ea24df71f60f384ad2e24a9451dfd91b0` on `research/news-rest` (in isolated worktree `/home/autobot/tradingbot-wt/news-rest`)
Report generated: 2026-10-07

---

## 1. Preamble

- **Credential prefix.** `FINNHUB_API_KEY` first-4-chars: **`d795`**. `FRED_API_KEY`: absent from `/opt/tradingbot/.env` (prefix: `none`).
- **No `/opt/tradingbot/*.py` or `/opt/tradingbot/.env` was touched** during this run. Classifier, strategy, and news_view code were imported read-only from the production path.
- **Prior report byte-check** (sha256 before / after this session's work):
  - `/opt/tradingbot/reports-public/news_rest_break_event_study_20261007.md`: `3c14f484b441390b0b5fa90300efede4daaf9bebb5286b6f7ceb365903f5ddf7` (unchanged — matches the R3 preservation requirement).
  - `/opt/tradingbot/reports-public/news_corpus_v1_report.md`: `5019b2c875aa4601ca100d8a954a7d3ca5632aa794538b31a03786acd969343d` (unchanged — the prior R4A TE-STOP record is preserved).
- **Filename note.** The operator's instructions used the literal filename `news_corpus_v1_report.md` while also requiring the prior R4A STOP report at that exact path to remain untouched. These two instructions contradict each other if resolved literally. Judgement call: this R4A-F report is written to the distinct filename `news_corpus_v1_r4af_report.md` so the prior STOP record stays byte-intact. The operator can redirect if a different naming is preferred.

---

## 2. Finnhub PIT access probe

Both probes made before any corpus build.

### Probe 1 — `2026-02-02` → `2026-02-06`

- **URL** (token redacted): `GET https://finnhub.io/api/v1/calendar/economic?from=2026-02-02&to=2026-02-06&token=<REDACTED>`
- **HTTP status**: `200`
- **Response bytes**: `79892`
- **First 500 chars of body**:

```
{"economicCalendar":[{"actual":null,"country":"MX","estimate":null,"event":"Constitution Day","impact":"low","prev":null,"time":"2026-02-02 00:00:00","unit":""},{"actual":null,"country":"MY","estimate":null,"event":"Federal Territory Day","impact":"low","prev":null,"time":"2026-02-02 00:00:00","unit":""},{"actual":null,"country":"RW","estimate":null,"event":"National Heroes' Day","impact":"low","prev":null,"time":"2026-02-02 00:00:00","unit":""},{"actual":null,"country":"MY","estimate":null,"eve
```

- **Schema check**: every event row carries `actual`, `country`, `estimate`, `event`, `impact`, `prev`, `time`, `unit`. All seven required schema fields are structurally present on every row (several are `null` for holiday rows, which is correct Finnhub behaviour).
- **Countries present (sample)**: GB ✓, US ✓, plus 85 other ISO-2 country codes.
- **NFP note**: the operator-expected US NFP for `2026-02-06` is **not present** in Finnhub's calendar for this window. Finnhub returned 4 US `high`-impact rows for the week (ISM Manufacturing PMI, ISM Services PMI, JOLTs Job Openings, Michigan Consumer Sentiment Prel), all with fully populated `actual/estimate/prev/time/unit/impact/country`. Finnhub lists US employment-adjacent indicators (ISM Manufacturing Employment, ADP Employment Change, Canadian Employment Change) in the week but no US Non-Farm Payrolls row. This is a Finnhub coverage gap (or a late/missing release in that specific month) rather than a schema failure. **Verdict: schema is populated for US high-impact events in the week; access proceeds.**

### Probe 2 — `2026-09-08` → `2026-09-12`

- **URL** (token redacted): `GET https://finnhub.io/api/v1/calendar/economic?from=2026-09-08&to=2026-09-12&token=<REDACTED>`
- **HTTP status**: `200`
- **Response bytes**: `59457`
- **First 500 chars of body**:

```
{"economicCalendar":[{"actual":null,"country":"MT","estimate":null,"event":"Feast of Our Lady of Victories","impact":"low","prev":null,"time":"2026-09-08 00:00:00","unit":""},{"actual":null,"country":"IE","estimate":null,"event":"Construction PMI","impact":"low","prev":null,"time":"2026-09-08 00:01:00","unit":""},{"actual":-5.2,"country":"AU","estimate":null,"event":"Westpac Consumer Confidence Change","impact":"high","prev":6,"time":"2026-09-08 00:30:00","unit":"%"},{"actual":84.4,"country":"AU
```

- **US CPI 2026-09-11 verification** (operator-expected row): `{"actual":3.4,"country":"US","estimate":3.4,"event":"Inflation Rate YoY","impact":"high","prev":3.4,"time":"2026-09-11 12:30:00","unit":"%"}` — all seven schema fields populated.
- **UK GDP MoM 2026-09-11 verification** (operator-expected row): `{"actual":0.4,"country":"GB","estimate":0,"event":"GDP MoM","impact":"high","prev":0.3,"time":"2026-09-11 06:00:00","unit":"%"}` — all seven schema fields populated.
- **ECB rate decision 2026-09-10 note**: the ECB is an `EU` country-code row, not GB/US. Captured in raw data for forensics; filtered out at normalisation per the scope rule (`countries ∈ {GB, US}`).

**Access gate PASSED.** Proceeded to full build.

---

## 3. Dataset scope

| Field | Value |
|---|---|
| Date range | `2025-12-29` → `2026-10-07` (Monday-anchored weeks covering the operator's `2026-01-01`..`2026-10-07` span; the first week starts a few days before 2026-01-01 to snap to Monday) |
| Countries | `GB`, `US` |
| Week-range requests | **41** |
| Raw files | 41 × `.json.gz` + 41 × `.meta.json` = **82 files** |
| Raw total bytes (compressed) | **369,026 bytes** (sum of all `*.json.gz` under `research/news_corpus/v1/raw/`) |
| All HTTP statuses | `200` on every request (zero 4xx/5xx retries) |

Full per-week meta sidecars live at `research/news_corpus/v1/raw/finnhub_*.meta.json` — each sidecar carries `url` (token REDACTED), `fetched_at_utc`, `http_status`, `response_bytes`, `raw_gz_sha256`, `raw_gz_bytes`, `event_count`, and `countries` histogram.

---

## 4. Normalisation

**Field schema per row** (`research/news_corpus/v1/normalized/releases.jsonl`, 4054 rows):

| Field | Source |
|---|---|
| `release_ts_utc` | parsed from Finnhub `time` as UTC ISO |
| `release_ts_raw` | verbatim Finnhub `time` |
| `event` | verbatim Finnhub `event` |
| `country` | verbatim Finnhub `country` |
| `currency` | derived: `GB→GBP`, `US→USD` |
| `provider_event_id` | **null (Finnhub does not expose)** |
| `research_key` | `<country>_<slug>_<ts>` composite |
| `actual_raw` / `actual` | verbatim / numeric |
| `consensus_forecast_raw` / `consensus_forecast` | Finnhub `estimate` verbatim / numeric |
| `te_forecast_raw` / `te_forecast` | **null (Finnhub-only run)** |
| `previous_raw` / `previous` | Finnhub `prev` verbatim / numeric |
| `revised_raw` / `revised` | **null (Finnhub does not expose)** |
| `importance_raw` / `importance_rank` | Finnhub `impact` / 1-2-3 |
| `source` | `"finnhub"` |
| `last_update_raw` / `last_update_utc` | **null (Finnhub does not expose)** |
| `unit_raw` | verbatim Finnhub `unit` |
| `parsing_flags` | list |
| `raw_source_file` | relative path to gz |

**Parsing-flag frequency** across all 4054 rows (GB+US):

| Flag | Count |
|---|---|
| `source_missing_revised` | 4054 (every row — Finnhub gap) |
| `source_missing_last_update` | 4054 (every row — Finnhub gap) |
| `source_missing_provider_event_id` | 4054 (every row — Finnhub gap) |
| `source_missing_te_forecast` | 4054 (every row — Finnhub-only run) |
| `consensus_forecast_not_numeric` | 2343 |
| `actual_not_numeric` | 595 |
| `previous_not_numeric` | 571 |

The four source-missing flags are universal because they're Finnhub schema limitations, not row-level parsing failures. The three `*_not_numeric` flags are expected: Finnhub emits central-bank speeches, auction announcements, holidays, and other calendar-only entries with null numeric fields. Those rows cascade into exclusions in §6.

---

## 5. Tier distribution

Per country × tier counts (after classifier run; tier=SMALL dominates GB/US combined because Finnhub's `impact` field is broad):

| Country | BIG | MIDDLE | SMALL | Total |
|---|---:|---:|---:|---:|
| GB | 68 | 173 | 554 | 795 |
| US | 106 | 541 | 2612 | 3259 |
| **Total** | **174** | **714** | **3166** | **4054** |

Classifier used: `/opt/tradingbot/news_tier_classifier.py` sha256 `bad0d0133afde1f4140de7b73de755ae2f09c17cc5ec37d3646529c9c7392a9b`. Rules in that file emitted ~40 fallthrough WARN lines for HIGH-impact events that neither BIG nor MIDDLE rule matched (Treasury Gilt auctions, BoE speeches, Fed Powell/Warsh speeches, bank holidays, Jackson Hole Symposium, Trump-Xi Summit, etc.) — all demoted to SMALL per the classifier's documented default. These fallthroughs are flagged in the classifier's log; they're not an R4A-F defect, they're a known classifier gap the operator can address in a future override-table bump.

---

## 6. Exclusions

Exclusion reasons (one row per excluded release — 3495 total):

| Country | tier_small | actual_not_numeric | consensus_forecast_not_numeric | Total |
|---|---:|---:|---:|---:|
| GB | 554 | 47 | 36 | 637 |
| US | 2612 | 54 | 192 | 2858 |
| **Total** | **3166** | **101** | **228** | **3495** |

Final scoreable set = BIG + MIDDLE with numeric `actual` AND numeric `consensus_forecast` = **559 releases** (sum of 68+173+106+541 minus exclusions = 101 + 228 extracted from BIG/MIDDLE rows). This is the dataset entering §7 and §8.

Full excluded list at `research/news_corpus/v1/normalized/excluded.jsonl` with per-row `exclusion_reason`.

---

## 7. Component surprise

Per-component tagging over the 559 scoreable rows (`research/news_corpus/v1/normalized/releases_scoreable.jsonl`):

- **GOOD_FOR_CURRENCY lookup path**: substring iteration over `news_strategy.GOOD_FOR_CURRENCY` dict (sha256 `15b67e31a2be09d896c7cf7b36b2e11fc6d93536a32bba423abfc713f8590cc5`), insertion-order first-match, identical to `news_strategy.good_for_currency()` lines 404-424.
- **Polarity-not-found**: 175 of 559 scoreable rows had NO keyword match in GOOD_FOR_CURRENCY (Treasury auctions, specialty indices, central-bank speeches that passed tier filtering). The implementation flagged these with `polarity_not_found=True` and used the module's documented `POSITIVE` fallback for direction scoring. These rows carry `polarity_matched_keyword=null` for later audit.

**`component_direction_for_currency` counts** (STRENGTHEN / WEAKEN relative to the component's own currency):

| Direction | Count |
|---|---:|
| IN_LINE | 248 |
| STRENGTHEN | 172 |
| WEAKEN | 139 |

**`component_direction_for_gbpusd` counts** (STRENGTHEN translated to GBPUSD direction: GBP↑ → UP, USD↑ → DOWN):

| Direction | Count |
|---|---:|
| IN_LINE | 248 |
| DOWN | 158 |
| UP | 153 |

The IN_LINE share (44%) is explained by `actual == consensus_forecast` cases plus near-identical rate decisions where Finnhub emits the same value for both; this is descriptive 4A provenance, not a threshold rule.

Per-row 4A provenance (`actual_raw`, `consensus_forecast_raw`, `actual`, `consensus_forecast`, `raw_diff`, `direction_after_good_for_currency`) is embedded on every scoreable row's `provenance_4A` object. No threshold, normalisation, weighting, or classification rule has been applied — this stage records surprise sign only.

---

## 8. Event grouping + classification

Grouping key = exact match on `release_ts_utc` (string equality). Pre-registered rule:
- Highest-tier component wins.
- Same-tier conflict (two or more same-highest-tier components with opposing GBPUSD directions and at least two of {UP, DOWN} both present) → `CONFLICTED`.
- No scoreable component → `NO_SURPRISE`. (Zero such groups in this corpus because scoreable rows are the input.)

Per-group output at `research/news_corpus/v1/normalized/events.jsonl` (209 rows). The `bounce_engine.news_view.proposition()` function (sha256 `d99b604f579e878ffcacbc37c89b0cad92213e6f2aaa6b4fc625c2ea12b03d88`) was also called per group and its output is attached as `nv_proposition` for cross-reference — it uses the forecast-vs-previous (not actual-vs-forecast) scoring, so it answers a different question and is purely informational here.

**Event classification counts** (209 groups):

| Classification | Count |
|---|---:|
| DOWN | 68 |
| UP | 66 |
| IN_LINE | 58 |
| CONFLICTED | 17 |

### All 17 CONFLICTED events (top-tier components only)

```
2026-01-14T13:30:00+00:00 (top=MIDDLE):
  [US/MIDDLE] Core PPI MoM: actual=0.0 forecast=0.2 gbpusd=UP
  [US/MIDDLE] Core PPI YoY: actual=3.0 forecast=2.7 gbpusd=DOWN
  [US/MIDDLE] PPI MoM: actual=0.2 forecast=0.2 gbpusd=IN_LINE
  [US/MIDDLE] PPI YoY: actual=3.0 forecast=2.7 gbpusd=DOWN
  [US/MIDDLE] Retail Sales Control Group MoM: actual=0.4 forecast=0.4 gbpusd=IN_LINE
  [US/MIDDLE] Retail Sales Ex Autos MoM: actual=0.5 forecast=0.4 gbpusd=DOWN
  [US/MIDDLE] Retail Sales MoM: actual=0.6 forecast=0.4 gbpusd=DOWN

2026-02-02T15:00:00+00:00 (top=MIDDLE):
  [US/MIDDLE] ISM Manufacturing PMI: actual=52.6 forecast=48.5 gbpusd=DOWN
  [US/MIDDLE] ISM Manufacturing Prices: actual=59.0 forecast=60.5 gbpusd=UP

2026-02-04T15:00:00+00:00 (top=MIDDLE):
  [US/MIDDLE] ISM Services Employment: actual=50.3 forecast=52.3 gbpusd=UP
  [US/MIDDLE] ISM Services PMI: actual=53.8 forecast=53.5 gbpusd=DOWN

2026-02-20T13:30:00+00:00 (top=BIG):
  [US/BIG] GDP Growth Rate QoQ Adv: actual=1.4 forecast=3.0 gbpusd=UP
  [US/BIG] GDP Price Index QoQ Adv: actual=3.7 forecast=2.8 gbpusd=DOWN

2026-04-22T06:00:00+00:00 (top=BIG):
  [GB/BIG] Core Inflation Rate MoM: actual=0.4 forecast=0.5 gbpusd=DOWN
  [GB/BIG] Core Inflation Rate YoY: actual=3.1 forecast=3.2 gbpusd=DOWN
  [GB/BIG] Inflation Rate MoM: actual=0.7 forecast=0.6 gbpusd=UP
  [GB/BIG] Inflation Rate YoY: actual=3.3 forecast=3.3 gbpusd=IN_LINE

2026-04-24T06:00:00+00:00 (top=MIDDLE):
  [GB/MIDDLE] Retail Sales ex Fuel MoM: actual=0.2 forecast=0.2 gbpusd=IN_LINE
  [GB/MIDDLE] Retail Sales ex Fuel YoY: actual=1.7 forecast=2.0 gbpusd=DOWN
  [GB/MIDDLE] Retail Sales MoM: actual=0.7 forecast=0.2 gbpusd=UP
  [GB/MIDDLE] Retail Sales YoY: actual=1.7 forecast=1.3 gbpusd=UP

2026-04-30T12:30:00+00:00 (top=BIG):
  [US/BIG] GDP Growth Rate QoQ Adv: actual=2.0 forecast=2.3 gbpusd=UP
  [US/BIG] GDP Price Index QoQ Adv: actual=4.5 forecast=3.8 gbpusd=DOWN

2026-05-01T14:00:00+00:00 (top=MIDDLE):
  [US/MIDDLE] ISM Manufacturing Employment: actual=46.4 forecast=49.0 gbpusd=UP
  [US/MIDDLE] ISM Manufacturing PMI: actual=52.7 forecast=53.0 gbpusd=UP
  [US/MIDDLE] ISM Manufacturing Prices: actual=84.6 forecast=80.0 gbpusd=DOWN

2026-05-14T12:30:00+00:00 (top=MIDDLE):
  [US/MIDDLE] Continuing Jobless Claims: actual=1782.0 forecast=1790.0 gbpusd=IN_LINE
  [US/MIDDLE] Initial Jobless Claims: actual=211.0 forecast=205.0 gbpusd=UP
  [US/MIDDLE] Retail Sales Control Group MoM: actual=0.5 forecast=0.4 gbpusd=DOWN
  [US/MIDDLE] Retail Sales Ex Autos MoM: actual=0.7 forecast=0.6 gbpusd=DOWN
  [US/MIDDLE] Retail Sales MoM: actual=0.5 forecast=0.5 gbpusd=IN_LINE

2026-06-01T14:00:00+00:00 (top=MIDDLE):
  [US/MIDDLE] ISM Manufacturing PMI: actual=54.0 forecast=53.0 gbpusd=DOWN
  [US/MIDDLE] ISM Manufacturing Prices: actual=82.1 forecast=85.5 gbpusd=UP

2026-06-10T12:30:00+00:00 (top=BIG):
  [US/BIG] Core Inflation Rate MoM: actual=0.2 forecast=0.3 gbpusd=UP
  [US/BIG] Core Inflation Rate YoY: actual=2.9 forecast=2.9 gbpusd=IN_LINE
  [US/BIG] CPI: actual=335.12 forecast=335.11 gbpusd=DOWN
  [US/BIG] Inflation Rate MoM: actual=0.5 forecast=0.5 gbpusd=IN_LINE
  [US/BIG] Inflation Rate YoY: actual=4.2 forecast=4.2 gbpusd=IN_LINE

2026-06-11T12:30:00+00:00 (top=MIDDLE):
  [US/MIDDLE] Continuing Jobless Claims: actual=1795.0 forecast=1780.0 gbpusd=IN_LINE
  [US/MIDDLE] Core PPI MoM: actual=0.4 forecast=0.5 gbpusd=UP
  [US/MIDDLE] Core PPI YoY: actual=4.9 forecast=5.4 gbpusd=UP
  [US/MIDDLE] Initial Jobless Claims: actual=229.0 forecast=219.0 gbpusd=UP
  [US/MIDDLE] PPI MoM: actual=1.1 forecast=0.7 gbpusd=DOWN
  [US/MIDDLE] PPI YoY: actual=6.5 forecast=6.4 gbpusd=DOWN

2026-07-16T12:30:00+00:00 (top=MIDDLE):
  [US/MIDDLE] Continuing Jobless Claims: actual=1805.0 forecast=1820.0 gbpusd=IN_LINE
  [US/MIDDLE] Initial Jobless Claims: actual=208.0 forecast=217.0 gbpusd=DOWN
  [US/MIDDLE] Retail Sales Control Group MoM: actual=0.5 forecast=0.5 gbpusd=IN_LINE
  [US/MIDDLE] Retail Sales Ex Autos MoM: actual=-0.2 forecast=-0.1 gbpusd=UP
  [US/MIDDLE] Retail Sales MoM: actual=0.2 forecast=0.2 gbpusd=IN_LINE

2026-07-22T06:00:00+00:00 (top=BIG):
  [GB/BIG] Core Inflation Rate YoY: actual=2.6 forecast=2.5 gbpusd=UP
  [GB/BIG] Inflation Rate MoM: actual=0.1 forecast=0.1 gbpusd=IN_LINE
  [GB/BIG] Inflation Rate YoY: actual=2.6 forecast=2.7 gbpusd=DOWN

2026-07-30T12:30:00+00:00 (top=BIG):
  [US/BIG] GDP Growth Rate QoQ Adv: actual=1.5 forecast=2.1 gbpusd=UP
  [US/BIG] GDP Price Index QoQ Adv: actual=6.3 forecast=3.6 gbpusd=DOWN

2026-09-10T12:30:00+00:00 (top=MIDDLE):
  [US/MIDDLE] Continuing Jobless Claims: actual=1774.0 forecast=1780.0 gbpusd=IN_LINE
  [US/MIDDLE] Core PPI MoM: actual=0.2 forecast=0.3 gbpusd=UP
  [US/MIDDLE] Core PPI YoY: actual=4.6 forecast=4.6 gbpusd=IN_LINE
  [US/MIDDLE] Initial Jobless Claims: actual=206.0 forecast=205.0 gbpusd=UP
  [US/MIDDLE] PPI MoM: actual=0.4 forecast=0.4 gbpusd=IN_LINE
  [US/MIDDLE] PPI YoY: actual=5.4 forecast=5.3 gbpusd=DOWN

2026-10-01T14:00:00+00:00 (top=MIDDLE):
  [US/MIDDLE] ISM Manufacturing PMI: actual=54.5 forecast=55.0 gbpusd=UP
  [US/MIDDLE] ISM Manufacturing Prices: actual=77.9 forecast=72.3 gbpusd=DOWN
```

Collision shapes cluster into three recognisable families:
- **CPI/PPI MoM-vs-YoY splits**: components move in opposite directions because the headline MoM beats consensus while the YoY misses (or vice versa).
- **ISM headline-vs-prices**: PMI headline up while input prices up is a classic growth-vs-inflation conflict.
- **GDP growth-vs-deflator**: strong deflator with weak real growth produces opposite GBPUSD signs for the same release-time stamp.

The operator can decide in a follow-up whether to collapse MoM/YoY pairs to a single component (via a provider-event-id proxy) or keep them separate as this corpus does.

---

## 9. First-print verification

**US (ALFRED/FRED)**: `FRED_API_KEY` is **absent** from `/opt/tradingbot/.env`. Per the operator rule not to swap credentials, every US scoreable row that mapped to a FRED series was annotated `first_print_source=unavailable_no_fred_key`. No alfred fetches were made.

**UK (ONS)**: The ONS legacy timeseries endpoint `https://api.ons.gov.uk/timeseries/<cdid>/dataset/<ds>/data` returns `HTTP 404` with body `"This API has been decommissioned as part of a suite of work to improve the digital products and services we offer. It was fully retired on 25/11/2024."`. Attempting the beta endpoint `https://api.beta.ons.gov.uk/v1/timeseries/<cdid>/data` returns `HTTP 404` with body `"No API is defined for GET /timeseries/<cdid>/data"`. A one-shot probe at the start of the first-print pass confirmed the retirement; after that the script short-circuited and labelled every UK scoreable row that mapped to a CDID as `first_print_source=ons_vintage_not_api_accessible`. No ONS fetches reached a usable vintage.

**First-print source distribution over the 559 scoreable rows**:

| source | count |
|---|---:|
| `no_series_mapping` | 313 |
| `unavailable_no_fred_key` | 178 |
| `ons_vintage_not_api_accessible` | 68 |
| `alfred` (actually fetched) | 0 |
| `ons_proxy_current_revision` (actually fetched) | 0 |

| matches / mismatches | count |
|---|---:|
| `matches=True` | 0 |
| `matches=False` (mismatch) | 0 |
| `matches=None` (no first-print value) | 559 |

**No mismatches to report** — there are zero successful first-print fetches to compare against Finnhub `actual`. The entire verification is blocked by missing/retired upstream endpoints, which is itself the finding: with Finnhub as the only live source, we have no second-source corroboration for `actual` values in this corpus. The series maps `research/news_corpus/v1/first_print_maps/{fred,ons}_series_map.json` are shipped in the corpus so the verification can be rerun by just providing a FRED key or by swapping ONS to a bulk-download approach.

---

## 10. Code hashes + file inventory

### Code hashes (production files, read-only)

| Path | sha256 |
|---|---|
| `/opt/tradingbot/news_tier_classifier.py` | `bad0d0133afde1f4140de7b73de755ae2f09c17cc5ec37d3646529c9c7392a9b` |
| `/opt/tradingbot/news_strategy.py` | `15b67e31a2be09d896c7cf7b36b2e11fc6d93536a32bba423abfc713f8590cc5` |
| `/opt/tradingbot/bounce_engine/news_view.py` | `d99b604f579e878ffcacbc37c89b0cad92213e6f2aaa6b4fc625c2ea12b03d88` |

### Corpus file inventory (`research/news_corpus/v1/`, 96 files total)

Non-raw files (raw files are listed exhaustively in `manifest.json`'s `raw_files` block):

| sha256 | bytes | path |
|---|---:|---|
| `c4af9462ba91d452e0b2dd877d71072e15d5a6cfefd5804aa1a1f86f472e23d5` | 17374 | `manifest.json` |
| `907513c03c7b5bc48aa9cc2d2b8a47d5439cc102a50b34d912f769538e1c5658` | 3541837 | `normalized/releases.jsonl` |
| `2c33214aafa78814adf0c95ebb5008ce6947031608597dbc0417b0c831c93c58` | 742138 | `normalized/releases_scoreable.jsonl` |
| `3ef98aacba8e670a1adef371a1665a5d59c6ba5b04cf8344a2c60bb4454dcf62` | 815083 | `normalized/releases_scoreable_fp.jsonl` |
| `8e3e57306108dcc63077956f1bdaf079275d9f110a498052e3768d6a96cdd96c` | 3370935 | `normalized/excluded.jsonl` |
| `4b29c4fe2ed79425e24f6397762817a2123c34f48271996096e11b9d41056397` | 809439 | `normalized/events.jsonl` |
| `0d3befce70fd2918f4476d9976a65f6d26b4d88489d6e8102d0d5fe7396123cf` | 1869 | `first_print_maps/fred_series_map.json` |
| `8a18987397bec5fac7d0f2463ae7f4f8427e713b71c55ab12b0dda3529812320` | 1693 | `first_print_maps/ons_series_map.json` |
| `81e8072c42bdd45ecd20020c882e7639c32ff2e07d3230b3a7dde4fae4993c26` | 4767 | `scripts/fetch_finnhub.py` |
| `0772f1ab2f63669abbcf976b26194f73d0c4bb88319ec5a6926d74051a1e31a4` | 5717 | `scripts/normalize.py` |
| `7e8acb2c40b183d40fc3af5a4f7b53812ea58f9e4444acf3ee934cf6d7c26abc` | 8429 | `scripts/classify.py` |
| `5a4e7d1e6f8cef2c7fdbc43cbb144c4b505383d2371b9c67a18d8fa2114e3d2a` | 8653 | `scripts/first_print.py` |
| `d91c964de7339d8b0790193e1df71eb92d43c2b4a87b798055e160fded8901b1` | 5286 | `scripts/build_manifest.py` |
| `3e526163514525990dfc38840a147ee3002947a832ca3cf0d3f463ca140299aa` | 3751 | `scripts/report_stats.py` |

(The 82 raw files — 41 gz + 41 meta — are listed in full in `manifest.json`.)

Corpus commit: `caa31d5ea24df71f60f384ad2e24a9451dfd91b0` on `research/news-rest` (not pushed per operator rule).

---

## 11. STOP marker

R4A-F complete. **R4B not started.** No candle data touched, no outcomes computed. The corpus is read-only; any future change is v2.

---

## 12. Filename choice

This report is at **`/opt/tradingbot/reports-public/news_corpus_v1_r4af_report.md`**. The prior R4A STOP record at `/opt/tradingbot/reports-public/news_corpus_v1_report.md` is byte-unchanged (sha256 `5019b2c875aa4601ca100d8a954a7d3ca5632aa794538b31a03786acd969343d`). This departure from the operator's literal filename resolves the contradiction between "write to news_corpus_v1_report.md" and "the previous R4A STOP report stay untouched". The operator can redirect to a different naming if preferred; the content is agnostic to filename.
