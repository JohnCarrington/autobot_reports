# news_impact_table_161 — tier classification table from AutoBot 161

**Source module:** `/opt/tradingbot/news_tier_classifier.py` (last modified 2026-08-14 20:45 UTC — `OVERRIDE_TABLE_VERSION = "2026-08-14.v1"`, overrides-commit `84f7089`; original classifier commit `c4c6be0`, 2026-07-03).
**Host:** AutoBot 161 (161.35.168.61).
**Snapshot taken:** 2026-11-07 UTC.

## What this table is

The operator set BIG / MIDDLE / SMALL tiers from their own research into how
far GBPUSD actually moved around each release. The tiers are **owner-set**,
not keyword-derived — the keyword rules are only the matching apparatus the
code uses to recognise a release by name at run-time. The report
`reports-public/unmatched_news_events.md` (2026-10-06) states this
explicitly: *"Not classified here — the operator decides tiers."*

Each row in the CSV is one keyword pattern inside one rule or override. A
release is classified by matching its event name against these patterns, in
this priority order:

1. **OVERRIDES** (currency-scoped) — checked first.
2. **BIG_RULES** (currency-agnostic).
3. **MIDDLE_RULES** (currency-agnostic).
4. **DEFAULT** → tier `SMALL`, `matched_rule = "default_small"` (no rule
   matched).

Tiers map to downstream behaviour via `under_new_rules`:
- `BIG`   → `would_blackout = True`, `would_be_extended_eligible = True`
- `MIDDLE` → `would_blackout = True`
- `SMALL`  → `would_allow_impulse = True`

## Counts

- 78 rows total
- 7 OVERRIDES rows (4 distinct override_ids, 2 currencies — USD, GBP)
- 45 BIG_RULES rows (13 distinct rule_ids)
- 25 MIDDLE_RULES rows (13 distinct rule_ids)
- 1 DEFAULT pseudo-row for `default_small`

## Scope note (coverage)

The classifier is scoped to the two currencies that drive GBPUSD: **GBP and
USD**. The one exception is the ECB rate decision / minutes block, which
carries no currency scope in the rule table but in practice fires on EUR
(the classifier is called for GBP+USD events by `news_strategy`, so ECB
rules are present for completeness rather than active use on 161). The
OVERRIDES table is currency-scoped (USD or GBP); BIG_RULES and MIDDLE_RULES
are currency-agnostic and are applied to any HIGH-impact event the strategy
evaluates.

## Columns

| Column | Meaning |
|---|---|
| `source_table` | `OVERRIDES` \| `BIG_RULES` \| `MIDDLE_RULES` \| `DEFAULT`. OVERRIDES are checked first and always win when matched. |
| `rule_id` | Short slug recorded as `matched_rule` in the classification log (`/opt/tradingbot/logs/news_tier_classification.jsonl`). Downstream telemetry partitions on this value. |
| `tier` | `BIG`, `MIDDLE` or `SMALL`. The operator set these tiers from their own research into how far GBPUSD actually moved around each release. |
| `currency` | ISO-3 currency code (`USD` / `GBP`) for OVERRIDES entries, `ANY` for BIG_RULES / MIDDLE_RULES (those are currency-agnostic — they match on event-name text alone). |
| `keyword_group_all_required` | The substrings, joined with ` + `, that **must all appear** in `event_name.lower()` for this row to match. Order does not matter. Rules may have several of these groups; a rule matches if **any one group** matches. |
| `requires_context` | Name of an optional predicate (defined in `news_tier_classifier.py`) that must also return True. `_has_nfp_same_day` elevates US Unemployment Rate to BIG only on NFP release days; `_fed_chair_attached_to_rate_decision` elevates Fed-chair speeches to BIG only when a rate decision is scheduled the same day. |
| `override_version` | For OVERRIDES rows only — the version slug recorded in the classification log so operators can grep for the active override table version. Currently `2026-08-14.v1`. |

Movement columns are intentionally omitted — the classifier stores keyword
patterns and tiers only. The underlying GBPUSD movement numbers that
informed each tier assignment are not part of this module; see **Derivation
report search** below.

## Every release classed BIG

The 15 BIG rule_ids (from OVERRIDES + BIG_RULES rows in the CSV) group as
follows. "Currency" is the scope the rule effectively applies to on this
host; "example event names" are the Finnhub provider strings that match.

| rule_id | Currency | Example event names |
|---|---|---|
| `us_core_cpi` | USD | Core CPI, Core Inflation Rate MoM / YoY |
| `us_cpi` | USD | CPI, Inflation Rate YoY (US) |
| `us_nfp` | USD | Non Farm Payrolls, NFP, Non-Farm Payrolls, Nonfarm Payrolls |
| `us_unemployment_with_nfp` | USD | Unemployment Rate — **only** when NFP is scheduled the same day (`_has_nfp_same_day`) |
| `us_fomc` | USD | FOMC Statement, Federal Funds Rate, Fed Funds Rate, Fed Interest Rate Decision |
| `us_fed_chair_speech_at_rate_decision` | USD | Fed Chair Speech, Powell Speech, Warsh Speech, Fed Chair — **only** on rate-decision days (`_fed_chair_attached_to_rate_decision`) |
| `uk_boe_rate` | GBP | BoE Interest Rate Decision, BoE Rate Decision, Bank of England Rate Decision, Bank Rate, BoE Press Conference, BoE Monetary Policy |
| `ecb_rate` | EUR (ECB) | ECB Interest Rate Decision, ECB Rate Decision, ECB Press Conference, Main Refinancing Rate, Deposit Facility Rate, ECB Monetary Policy |
| `uk_core_cpi` | GBP | UK Core CPI, UK Core Inflation |
| `uk_gdp` | GBP | UK GDP, GDP Prel, GDP Prelim, GDP Advance, GDP Flash |
| `us_gdp_advance_prelim` | USD | GDP Advance, GDP Prel, GDP Prelim |
| `central_bank_minutes` | USD / GBP / EUR | FOMC Minutes, ECB Minutes, BoE Minutes, MPC Minutes, Monetary Policy Minutes |
| `usd_fed_press_conf_override` | USD | Fed Press Conference, FOMC Press Conference (override — standalone presser row without the FOMC token) |
| `usd_gdp_adv_override` | USD | GDP Adv (override — captures the abbreviation the feed sometimes uses) |
| `uk_cpi_override` | GBP | CPI, Inflation Rate (YoY/MoM), Core Inflation (override — fixes attribution so UK CPI prints log as `uk_cpi_override`, not `us_cpi`) |

## Every release classed MIDDLE

The 16 MIDDLE rule_ids (from OVERRIDES + MIDDLE_RULES rows):

| rule_id | Currency | Example event names |
|---|---|---|
| `ism_manufacturing_pmi` | USD | ISM Manufacturing PMI |
| `ism_services_pmi` | USD | ISM Services PMI, ISM Non-Manufacturing |
| `global_pmi_flash` | USD / GBP / EUR | S&P Global PMI Flash, Markit PMI Flash, PMI Flash (any), Composite PMI |
| `retail_sales` | USD / GBP | Retail Sales, Core Retail Sales |
| `ppi` | USD / GBP | PPI, Core PPI, Producer Price Index |
| `initial_jobless_claims` | USD | Initial Jobless Claims, Initial Claims |
| `continuing_claims` | USD | Continuing Claims, Continuing Jobless |
| `adp` | USD | ADP Employment Change |
| `jolts` | USD | JOLTs Job Openings |
| `consumer_confidence` | USD / GBP | Consumer Confidence |
| `uom_sentiment` | USD | Michigan Sentiment, UoM Sentiment, Michigan Consumer |
| `durable_goods` | USD | Durable Goods, Durable Goods Orders |
| `core_pce` | USD | Core PCE |
| `pce` | USD | PCE Price Index |
| `industrial_production` | USD / GBP | Industrial Production |
| `gbp_gdp_mom_override` | GBP | GDP MoM (monthly ONS print — override, MIDDLE not BIG) |

## SMALL

There is no SMALL rule. Any HIGH-impact event that matches no OVERRIDE, no
BIG_RULE and no MIDDLE_RULE falls through to tier `SMALL` with
`matched_rule = "default_small"`. The DEFAULT pseudo-row in the CSV records
this.

## Derivation report search (reports from August–September 2026)

Per the operator's instruction, I searched the repository for a report
published in August or September 2026 that derived the tier assignments
from GBPUSD price moves. I found **no such report**. The nearest artefacts
are:

- `reports-public/unmatched_news_events.md` (2026-10-06, fix-session item
  6b) — explicitly states *"Not classified here — the operator decides
  tiers"* and presents 60-minute GBPUSD moves as decision evidence for a
  separate, later override edit; it is not itself the tier-derivation
  report.
- Commit messages `c4c6be0` (2026-07-03, classifier birth) and `84f7089`
  (2026-08-14, OVERRIDE table) carry rationale per entry but do not cite
  an upstream GBPUSD-move derivation report.

The derivation lives in the operator's own notes, not in this repository.
This note is included so the absence is explicit; I have not invented a
citation.

## Unmatched HIGH-impact GBP/USD releases in the stored calendar (last 6 months)

Scan window: **2026-05-08 → 2026-11-07** (183 days). Source:
`/opt/tradingbot/cache/news_state_finnhub_*.json` — 260 snapshot files,
14,036 raw event rows, 198 HIGH-impact GBP/USD events after dedup by
`(event_name, currency, release_ts_utc)`. Each event was classified via
the live `news_tier_classifier.classify_news_tier` with same-day same-
currency event names supplied as context (so the context-aware rules fire
correctly). Rows below are the events that classified as `SMALL` (no rule
matched).

| Event name | Currency | Count | First seen | Last seen (example) |
|---|---:|---:|---|---|
| Unemployment Rate | USD | 7 | 2026-06-05 | 2026-08-07 |
| Unemployment Rate | GBP | 6 | 2026-06-18 | 2026-08-18 |
| Building Permits Prel | USD | 6 | 2026-06-16 | 2026-08-18 |
| Existing Home Sales | USD | 6 | 2026-06-09 | 2026-08-11 |
| Housing Starts | USD | 6 | 2026-06-16 | 2026-08-18 |
| Personal Income MoM | USD | 6 | 2026-06-25 | 2026-08-26 |
| Personal Spending MoM | USD | 6 | 2026-06-25 | 2026-08-26 |
| Fed Chair Warsh Speech | USD | 4 | 2026-07-01 | 2026-08-28 |
| Fed Chair Warsh Testimony | USD | 2 | 2026-07-14 | 2026-07-15 |
| GDP Growth Rate QoQ 2nd Est | USD | 2 | 2026-05-28 | 2026-08-26 |
| GDP Growth Rate QoQ Final | USD | 2 | 2026-06-25 | 2026-09-30 |
| Autumn Budget | GBP | 1 | 2026-10-28 | 2026-10-28 |
| Autumn Budget 2026 | GBP | 1 | 2026-10-28 | 2026-10-28 |
| Autumn Forecast Statement | GBP | 1 | 2026-10-28 | 2026-10-28 |
| Interest Rate | GBP | 1 | 2026-11-05 | 2026-11-05 |
| Midterm Elections | USD | 1 | 2026-11-03 | 2026-11-03 |
| President Trump and President Xi Summit | USD | 1 | 2026-09-24 | 2026-09-24 |

17 distinct event names, 57 release instances out of the 198 HIGH-impact
dedup set (≈ 28.8%). Notes:

- `us_unemployment_with_nfp` elevates **USD Unemployment Rate** to BIG
  only on NFP days; the six prints above are the other months (solo
  release). Standalone promotion is a rule-table edit, not an OVERRIDE.
- `Fed Chair Warsh Speech / Testimony` count 4 + 2 above are the ones
  where no FOMC / rate decision was scheduled the same day, so
  `_fed_chair_attached_to_rate_decision` did not elevate.
- `Housing Starts` and `Building Permits Prel` share the US 12:30 UTC
  release slot — the same-day same-release-time duplicates are counted
  separately per the event-name key.
- `Interest Rate` (GBP, 2026-11-05) fell through because the UK BoE rule
  requires `("boe", "interest rate decision")`, `("boe", "rate
  decision")`, `("bank of england", "rate decision")` or the standalone
  `("bank rate",)` substring — plain `"Interest Rate"` matches none of
  them. Flag for the operator: this is a Finnhub-name variant for the
  BoE bank-rate print.

## Reproducibility

- Rule / override dump: Python on 161 reading the live
  `news_tier_classifier` module in-process (no network, no IG, no
  Finnhub).
- Unmatched scan: same approach as
  `scripts/unmatched_news_events_scan.py` but frequency-only (movement
  columns not computed).
- Snapshot taken **2026-11-07 UTC**.

## Secrets review

Both files (CSV + this README) contain no credentials — the classifier
module itself contains no API keys or account numbers; the unmatched-events
script sets IG environment variables to literal `"stub"` only to allow
`news_tier_classifier` imports (several transitive imports probe for
those at module load). Those stub values are **not** in this README.
