# The Structural Trade Planner tab

Built 17–18 November 2026 (owner's brief "Structural Trade Planner V1 — complete dashboard redesign"). **OBSERVE
ONLY — DOES NOT CONTROL TRADING.** A dedicated tab in the existing dashboard: same page, same login, same session
cookie, same data service. It reads the planner's own files, the candle store and the trading engine's status file;
it writes nothing, never contacts IG and never works out a forecast, level or recommendation of its own.

## Where it is

| Part | File |
|---|---|
| Tabs, compact summary card, lazy loader | `dashboard/static/index.html` (`#operations`, `#stp`) |
| The tab's page code and style | `dashboard/static/stp/stp.js`, `dashboard/static/stp/stp.css` |
| Chart library | `dashboard/static/vendor/lightweight-charts.standalone.production.js` (TradingView Lightweight Charts 4.2.3, Apache-2.0, `LICENSE-lightweight-charts.txt`; sha256 pinned in the tests) |
| Read-only data | `dashboard/stp.py` |
| Routes | `dashboard/server.py` (`GET /api/stp/...`) |
| Reporting addition in the planner | `planner/keeper.py` `_issued` → `planner.folder/<PAIR>/issued.jsonl` |

The tab's script, style and the chart library are served by the data service under `/api/stp/lib/` (a fixed list of
three names), so they sit behind the same `auth_request` gate as the rest of `/api/` and **nginx needs no change**
(its `location / { return 404; }` stays). They are loaded only when the tab is first opened, so a problem in the tab
can never break the operations page. The page's CSP (`script-src 'self'`) is met: everything comes from this server.

## Routes (all GET, all need the session; 401 without; 404 while `PLANNER_OBSERVE` is off, as the panel)

| Route | Parameters (validated) | Returns |
|---|---|---|
| `/api/stp/overview` | – | forecast, freshness, current price, live recommendation card, no-recommendation explanation, chart overlays, technical evidence, recent recommendations |
| `/api/stp/candles` | `tf` = `4h`/`1h`/`5m`; `limit` 1–1000 (defaults 180/240/288); `end` UTC time (optional, ≤ now) | finished candles only (end ≤ now), oldest first, chart (sell) price in GBP/USD notation; `partial` on a built candle missing parts |
| `/api/stp/history` | `page` ≥ 1; `size` 1–50; `sort` created/status/direction/trade; `order` asc/desc; `q` (≤ 60 chars) | one row per recommendation id, paginated |
| `/api/stp/recommendation` | `id` = `STP-PAIR-YYYYMMDD-HHMM-N` | snapshot at creation, every event in order, lifecycle stage times, retrospective observation |
| `/api/stp/evaluation` | – | forecast evaluation counts and distributions (no fills, no P&L) |
| `/api/stp/lib/<name>` | `stp.js`, `stp.css`, `lightweight-charts.js` only | the files |

A failure in any of these answers that request only (500 with a message); `/api/status`, `/api/history` and the
pause switch are untouched. `/api/status` keeps its planner panel and adds `planner.card` (the compact card) inside
its own guard.

## Data sources

- `current.json` — state, last plan, live recommendation, recent; `recommendations.jsonl` — every lifecycle event and
  hourly analysis; `issued.jsonl` — each recommendation in full as issued (new; see below).
- Candle store (`candles.folder`, the same store the planner reads): 5m, 1h, 4h.
- `data/trading/<PAIR>/status.json` — current price for the price line (bid = chart price).

## What is shown

- **Header:** freshness badge, price, last analysis, next analysis due, the planner's last run.
- **Forecast overview:** dominant direction (with the planner's meaning), condition (exact code + meaning),
  expected movement (FORECAST tag; plain words for the planner's "UP into resistance, then DOWN" — direction sequence
  only), preferred opportunity (BUY/SELL or NO CURRENT OPPORTUNITY, with the forecast direction kept separate),
  recommendation status (planner states mapped to labels: WAITING → WAITING FOR ENTRY ZONE, ACTIVE → ACTIVE (PRICE AT
  THE ZONE), others unchanged; NO RECOMMENDATION).
- **No-recommendation explanation** from recorded reasons only: A direction but no valid entry (the plan's
  `no_recommendation`), B no dominant direction, C unavailable or stale, D the last analysis's recommendation has
  since ended (its id, status and recorded reason; next chance at the next hourly analysis).
- **Chart:** H4/H1/M5 candles, zoom (wheel/pinch), pan (drag), crosshair, price and time axes in UK time, current
  price line, responsive (autoSize), older candles loaded when panning left. Overlays (toggles): Structure (4-hour
  swings, hourly levels, daily and weekly S/R), Pivots (daily, weekly), Zones (the confluence zones considered),
  Trade plan (shaded entry zone, intermediate/primary/extended destinations, invalidation lines, schematic dashed
  forecast arrows labelled FORECAST), Past recs (markers). Reset view. The timeframe is remembered (browser storage).
  The live, unfinished candle is not drawn.
- **Trade-plan card:** every field of the brief's table, from the live recommendation; with none, the forecast and
  the explanation only — no levels are drawn.
- **Lifecycle:** CREATED → WAITING FOR ZONE → ACTIVE → COMPLETED/INVALIDATED/SUPERSEDED with recorded times
  ("not recorded" / "never reached" otherwise) and every event with its reason; "forecast information available at
  creation" beside "market movement observed afterwards".
- **History:** search, sort, pages of 15; select a row to review it on the chart (original zone, targets and
  invalidation as issued; markers for created/active/ended; candles after creation are what happened).
- **Evaluation:** see methodology below.
- **Technical Evidence & Market Structure** (collapsed): 4-hour structure, condition evidence, daily/weekly context,
  EMA 7/13/21/100/200, RSI 3, MACD 35/45/30, Bollinger, ADR and range, pivots, conflicts, warm-up, freshness, decision
  reasons, the zones considered.

## Freshness rules (presentation of the planner's own data)

UNAVAILABLE (no readable `current.json`) · MARKET CLOSED (market hours) · STALE DATA (the planner's own `data_fresh`
false, with its reasons) · PLANNER NOT RUNNING (last run > 20 minutes ago while the market is open; it runs every 5
minutes) · ANALYSIS OVERDUE (> 10 minutes past the expected hourly analysis) · otherwise CURRENT. Opening the page
between hourly analyses is CURRENT. The recommendation's own FC-08 "current" flag is shown separately on the plan card.

## Recommendation history behaviour

One record per id from `recommendations.jsonl` (never merged by zone). Status: the live record's status if live,
otherwise the last status-bearing event. "At creation": the full snapshot from `issued.jsonl` when present; otherwise
only the summary the planner kept in the "created" event, labelled as such — the original intermediate and extended
destinations and invalidation conditions of recommendations issued before `issued.jsonl` existed (the two of
17 November) are shown as "not recorded", never reconstructed.

`issued.jsonl` (planner, reporting only): when the keeper creates a recommendation it also appends the full record
(without its running history) to this separate file. It decides nothing, the lifecycle file is unchanged, and a write
failure is logged and ignored.

## Forecast evaluation methodology

Observation only: not trading results; no fills, spreads, commissions, P&L, wins or losses; nothing is optimised.
Period: the first recorded analysis plus four weeks. Counts come from the lifecycle events. "Reached primary" =
COMPLETED plus INVALIDATED "destination reached before entry". Excursions: distances in pips from the planner's
reference level, from the 5-minute candle that reached the zone to the end (or now), chart price. Times: creation →
first ACTIVE; first ACTIVE → COMPLETED. Stability: hourly re-checks of live recommendations (supported / changed),
and supersessions. Ambiguities listed: one 5-minute candle touching both zone and destination; an activation candle
that began before creation; a recommendation issued with price already within 3 pips of its primary destination.
Fewer than 3 values: INSUFFICIENT DATA.

## Known limitations

- Structural levels on the chart are those the planner persisted (inside the zones it considered and their
  destinations, plus the pivots in its observations). The planner does not persist its whole level map (proposal H-2
  in the investigation report).
- Retired recommendations from before `issued.jsonl` have summary-only "at creation" data.
- The forecast path is schematic (direction sequence), never a price path or timing.

## Tests

`tests/technical/test_stp_dashboard.py` (technical items 1–20), `tests/functional/test_stp_dashboard_scenarios.py`
(functional items 1–20 plus the 17 November shape), fixtures `tests/stp_fixtures.py` (lifecycles made by the real
keeper).
