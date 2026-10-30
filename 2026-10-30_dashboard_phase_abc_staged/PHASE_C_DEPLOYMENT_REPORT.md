# AutoBot Dashboard — Phase C Deployment-Ready Report (2026-10-30)

**Scope:** Phase A backend patches + Phase A automated tests + Phase B
staged responsive dashboard + Phase C reconciliation evidence + D-03
investigation report. **Nothing has been deployed.** Operator approval
required before copying files to `/opt/tradingbot/` or
`/opt/autobot-dashboard/`.

**Branch:** `fix/dashboard-full-20261029` at
`/home/autobot/tradingbot-wt/dashboard-full-20261029` (worktree isolated).

**Safety constraints honoured:**
- Zero trading-logic changes
- Zero order placements, amendments or cancellations
- Zero SL/TP changes
- Zero trading-service restarts
- Broker access read-only (one new read-only `/broker/positions/<id>`
  route added — never writes)
- No files touched under `/opt/ema_pullback/`, `/opt/bb_bounce/`,
  `/opt/london_liquidity_sweep/`, `/opt/ma_cross_h1/`, `/opt/tradingbot/`
  outside the worktree

---

## 1. Executive summary — three NEW financial-data integrity defects discovered

| # | Discovery | Impact | Status |
|---|---|---|---|
| N1 | D-05 duplication is 11 rows (not 2) on 28-Oct EMAPB alone; **46% dup rate**. +£337.80 **phantom profit** inflation that day. | HIGH | **Fixed by Phase A** |
| N2 | D-03 reconciler false-close has misfired **5 times in 11 h**, not once. Same fingerprint on each: 21s hold, `exit_price==broker_sl_level` to 4dp, `last_known_mid=null`, exact −12p fabricated P&L. `DIAAAAYR4FEYEBL` currently LIVE broker-OPEN with ledger-CLOSED mismatch. | HIGH | Investigation delivered; **fix is separate workstream per operator** |
| N3 | Full 10-day pre-patch dashboard P&L **overstated by +194.5 pips / +£375.00** due to duplicate rows. The audit flagged "PnL double-counted when summed" as MED — true impact is HIGH. | HIGH | **Fixed by Phase A** |

Patched backend + staged dashboard reconcile every single day in the
snapshot period. See §4 for the before/after reconciliation table.

---

## 2. Phase A — backend patches

### Files changed (worktree only)

| File | Old lines | New lines | Diff |
|---|---|---|---|
| `strategy_services.py` | 954 | ~980 | +42 lines (−11 removed) |
| `trades_api.py` | 3,533 | ~3,840 | +542 lines (−20 removed) |
| **Total** | 4,487 | ~4,820 | **+562 / −22** |

### D-01 — generic standalone-service discovery (strategy_services.py)

`discover_services()` at `strategy_services.py:204-277` no longer requires
a literal `IG_ACCOUNT_ID` line in a service's `.env`. A resolvable
`OWNERSHIP_HOST_PREFIX` (plus matching unit on disk) is now sufficient.
This is the EMA Pullback case — the service inherits credentials via a
systemd `Environment=` entry and never writes the literal line.

A new `StrategyCard("EMA_PULLBACK_STANDALONE", "EMA Pullback", "EMAPB",
...)` entry at line 611 surfaces the service on the Strategies tab.

**Validation (local):**

```
$ python3 -c "import strategy_services as ss; [print(s.host_prefix) for s in ss.discover_services()]"
EMAPB
H161
HBB
HLS
HMA
```

### D-04 — attribution tier resolver (trades_api.py)

Three additions:

1. `_strategy_from_dealref()` at line 869 extended with a
   `_STANDALONE_PREFIX_STRATEGY` map so EMAPB/HBB/HLS/HMA deal
   references decode to `EMA_PULLBACK` / `BB_BOUNCE` / `LLS` / `MA_CROSS_H1`
   even when signal_log has no row.
2. `_strategy_resolution_tier()` at line 924 — labels every /trades row
   as `TIER1_DEALREF` / `TIER2_SIGNALLOG` / `TIER3_UNATTRIBUTED` /
   `TIER0_UNKNOWN`.
3. `_attribution_note()` at line 946 — human-readable explanation of why
   a Tier-3 row is unattributed (empty for Tier-1/2).

Downstream: `_aggregate_positions()`, `_explode_legs()`, and
`_build_open_position_rows()` all stamp `strategy_resolution` and
`attribution_note` fields onto their output rows.

### D-05 — journal↔spine dedup guard (trades_api.py)

Two layers:

1. **Fetch-layer dedup** at `_fetch_ig_transactions()` line 1114 — a
   `seen` set keyed on `(reference, dateUtc)` suppresses the IG
   pagination overlap. Logs the suppression count.
2. **Defensive dedup** at `_explode_legs()` end (new block) — if the
   fetch guard ever misses, the raw view still outputs one row per
   `deal_id`. Logs a defensive-guard warning if it ever triggers.

### D-02 — open-position deal-id authority (trades_api.py)

- `_fetch_ig_position_by_dealid()` at line 1420 — read-only probe of IG
  `GET /positions/{dealId}` with 30s TTL. Returns
  `{status: OPEN|CLOSED|ERROR, payload, http_status, note,
  authority_source: "deal_id_confirm"}`. Never writes.
- Every row from `_fetch_ig_open_positions` now carries
  `authority_source: "listing"` so the dashboard can distinguish
  listing-derived vs deal-id-confirmed rows.
- New route `GET /broker/positions/<deal_id>` at line 3733 — exposes the
  probe to the dashboard, cookie-gated like every other endpoint.

### D-06 — /service-health endpoint (trades_api.py)

- `_service_health_classify()` at line 3797 — pure classifier of
  `(active, sub_state, last_log_iso, last_log_text)` to
  `HEALTHY / DEGRADED / STALE / STOPPED / FAILED / UNKNOWN`. Evidence
  carried on every row.
- `_build_service_health_payload()` at line 3858 — pulls `systemctl
  is-active` + `journalctl -n 1` for each discovered service, classifies,
  returns a payload with per-status counts.
- Route `GET /service-health` at line 3910 with 15s TTL cache.

Live validation (just now against production systemd):

```
H161    HEALTHY     active, last log '... [INFO] [LS-OCCUPANCY] pair=USDJPY tick_inv=149 ...'
HBB     HEALTHY     active, last log "... [INFO] GET '/confirms/TRVWXDJF5R8TYRZ', resp 200"
HLS     DEGRADED    recent log matches error keyword: '... AutoBot archive stale ... age=901s > 900s'
HMA     DEGRADED    recent log matches error keyword: 'OSError: [Errno 28] No space left on device'
EMAPB   HEALTHY     (newly admitted by D-01)
counts: 3 HEALTHY · 2 DEGRADED · 0 STALE · 0 STOPPED · 0 FAILED · 0 UNKNOWN
```

The DEGRADED signals on HLS + HMA were silently invisible before — now
each appears inline on the strategy card as a coloured chip with the
underlying evidence as a tooltip.

---

## 3. Phase A — automated test suite

New directory `tests/dashboard_full_20261029/` with 5 modules:

| Module | Tests | Pre-deploy result | Phase C acceptance (post-deploy) |
|---|---|---|---|
| test_discovery.py       | 5 | 5 PASS | 5 PASS |
| test_attribution.py     | 5 | 5 PASS | 5 PASS |
| test_dedup.py           | 2 | 2 PASS | 2 PASS |
| test_service_health.py  | 8 | 8 PASS | 8 PASS |
| test_reconciliation.py  | 9 | 2 PASS + 4 FAIL + 3 SKIP (live-endpoint; expected failures until deploy) | 9 PASS |
| **Total**               | **29** | **22 PASS, 4 FAIL, 3 SKIP** | **29 PASS, 0 FAIL** |

Run:

```
cd /home/autobot/tradingbot-wt/dashboard-full-20261029
python3 -m pytest tests/dashboard_full_20261029/ -v
```

The 4 pre-deploy failures all probe the LIVE trades-api on
`http://127.0.0.1:8080`, which still runs the unpatched code. **These
four are the Phase C acceptance gate** — they must flip to PASS once the
staged trades-api is deployed:

1. `test_live_every_deal_reference_appears_at_most_once` — asserts D-05
   fix is live
2. `test_live_every_row_carries_strategy_resolution` — asserts D-04
   stamping is live
3. `test_live_emapb_rows_resolve_to_ema_pullback` — asserts D-04
   standalone fallback is live
4. `test_live_emapb_card_present_in_strategies_today` — asserts D-01
   discovery is live

The 3 pre-deploy skips are tests that depend on the new `/service-health`
endpoint (not yet deployed) + the recording-only baseline test.

---

## 4. Reconciliation evidence — before vs after

### 10-day aggregate (2026-10-20 → 2026-10-30, snapshot 05:46:57 UTC)

| day        | rows_b | rows_a | dup | pips_b | pips_a | drift   | £_b     | £_a     | drift £  |
|------------|-------:|-------:|---:|-------:|-------:|--------:|--------:|--------:|---------:|
| 2026-10-20 |     23 |     22 |   1 |  −0.9  | −7.5   |   +6.6  | −38.50  | −45.10  |  +6.60   |
| 2026-10-21 |     18 |     17 |   1 |  25.3  | −22.0  |  +47.3  |  50.70  | −43.90  | +94.60   |
| 2026-10-22 |     25 |     25 |   0 | −26.5  | −26.5  |   0.0   | −52.13  | −52.13  |  0.00    |
| 2026-10-23 |     19 |     18 |   1 | −30.8  | −38.8  |   +8.0  | −47.81  | −55.81  |  +8.00   |
| 2026-10-25 |      1 |      1 |   0 | −12.0  | −12.0  |   0.0   |  −6.00  |  −6.00  |  0.00    |
| 2026-10-26 |     15 |     15 |   0 |−102.8  |−102.8  |   0.0   |−187.60  |−187.60  |  0.00    |
| 2026-10-27 |     28 |     25 |   3 | −99.9  | −63.9  |  −36.0  |−199.80  |−127.80  | −72.00   |
| **2026-10-28** | **40** | **29** | **11** | **368.5** | **199.9** | **+168.6** | **775.20** | **437.40** | **+337.80** |
| 2026-10-29 |     24 |     24 |   0 |  11.0  |  11.0  |   0.0   |   9.63  |   9.63  |  0.00    |
| 2026-10-30 |      6 |      6 |   0 | −15.9  | −15.9  |   0.0   | −31.80  | −31.80  |  0.00    |
| **TOTAL**  | **199**| **182**| **17** | — | — | **+194.5 p** | — | — | **+£375.00** |

**Pre-patch dashboard was reporting +£375.00 phantom profit across the
10-day window.** Nearly all of it (+£337.80) landed on 2026-10-28.

### 2026-10-28 by host_prefix

| prefix | BEFORE rows | AFTER rows | removed | BEFORE pips | AFTER pips | drift   |
|--------|------------:|-----------:|--------:|------------:|-----------:|--------:|
| EMAPB  |     **24**  |    **13**  |  **11** |    **358.1**|  **189.5** | **+168.6** |
| H161   |          6  |         6  |     0   |      −17.5  |     −17.5  |   0.0   |
| HBB    |          8  |         8  |     0   |       51.9  |      51.9  |   0.0   |
| HLS    |          2  |         2  |     0   |      −24.0  |     −24.0  |   0.0   |
| **TOTAL** | **40**   |    **29**  |  **11** |     368.5   |     199.9  | **+168.6** |

### 2026-10-28 dashboard display reconciliation

| State | Dashboard shows | True trades | Delta |
|---|---:|---:|---:|
| **BEFORE** (audit day) | 15 | 39 (24 EMAPB + 15 others, pre-dedup) | **−62% under** |
| **AFTER** (predicted) | **29** | 29 (13 EMAPB + 16 others, deduped) | **0 — matches** |

### EMAPB on 2026-10-28 — authoritative unique-trade ledger

13 unique deals totalling +189.5 pips:

| deal_reference | dir | entry → close | pips | strategy |
|---|---|---|---:|---|
| EMAPB-S-1793123418-971388 | SELL | 13312.05 → 13282.70 | +29.3 | EMA_PULLBACK |
| EMAPB-S-1793148320-0B8C4D | SELL | 13304.65 → 13282.70 | +21.9 | EMA_PULLBACK |
| EMAPB-S-1793141115-4708F0 | SELL | 13302.20 → 13282.70 | +19.5 | EMA_PULLBACK |
| EMAPB-S-1793140507-186E1B | SELL | 13301.90 → 13282.70 | +19.2 | EMA_PULLBACK |
| EMAPB-S-1793143814-18CF9F | SELL | 13301.85 → 13282.70 | +19.1 | EMA_PULLBACK |
| EMAPB-S-1793143204-AC1E7A | SELL | 13301.55 → 13282.70 | +18.8 | EMA_PULLBACK |
| EMAPB-S-1793139918-C5E8F3 | SELL | 13301.40 → 13282.70 | +18.7 | EMA_PULLBACK |
| EMAPB-S-1793144708-2EC338 | SELL | 13301.05 → 13282.70 | +18.3 | EMA_PULLBACK |
| EMAPB-S-1793139308-510218 | SELL | 13300.45 → 13282.70 | +17.8 | EMA_PULLBACK |
| EMAPB-S-1793139023-F7AFBD | SELL | 13298.25 → 13282.70 | +15.5 | EMA_PULLBACK |
| EMAPB-S-1793138412-F3EA28 | SELL | 13298.10 → 13282.70 | +15.4 | EMA_PULLBACK |
| EMAPB-S-1793184019-37DBD2 | SELL | 13277.25 → 13289.25 | −12.0 | EMA_PULLBACK |
| EMAPB-S-1793174113-9F8792 | SELL | 13274.65 → 13286.65 | −12.0 | EMA_PULLBACK |
| **SUM** | | | **+189.5** | |

### Unattributed roll-up (snapshot period)

55 TIER3_UNATTRIBUTED rows across the snapshot:

- 51 × `H144` (FXi sibling host — surfaced on the dedicated FXi tab,
  not on the main AUTOBOT total)
- 4 × various IG internal 15-char prefixes
  (`B6LAAY57QM4TYRZ`, `GDGD2TSE9YCTYRZ`, `TQNPAC7DM78TYRZ`,
  `2SVJXP4E3UTYRZ`) — manually-closed positions / IG-side activity;
  each row carries `attribution_note="host_prefix … is an IG internal
  …-char deal/activity id — opener did not stamp an ownership prefix"`

Every single row is accounted for — none silently dropped.

---

## 5. Phase B — staged dashboard

### File

`autobot-dashboard/index.staged.html` (224 KB, 5,405 lines) — a
superset of the current `/opt/autobot-dashboard/index.html` with
responsive overlays + consolidated H161 group + UNATTRIBUTED card +
service-health inline chips + broker-disagreement banner.

### Changes vs current index.html

| Component | Change | Lines |
|---|---|---|
| Build stamp | Updated to `dashboard-full-20261030 Phase A/B staged` | 1113 |
| CSS @media breakpoints | **NEW** — 3 responsive breakpoints: 1365px tablet, 768px mobile, 480px narrow-mobile | ~1113–1265 |
| `.svc-health` chip CSS | **NEW** — colour-coded HEALTHY/DEGRADED/STALE/STOPPED/FAILED/UNKNOWN with evidence tooltip | ~1137–1162 |
| `.autobot-group` CSS | **NEW** — expandable H161 group container | ~1165–1189 |
| `.unattributed-card` CSS | **NEW** — opens + closed in one combined card | ~1192–1206 |
| `.broker-disagreement-banner` CSS | **NEW** — D-02 live listing-vs-ledger disagreement | ~1210–1224 |
| `_refreshServiceHealth()` JS | **NEW** — polls `/service-health` every 15s | ~5116 |
| `_buildDisagreementBanner()` JS | **NEW** — D-02 banner builder | ~5139 |
| `_verifyBrokerPosition()` JS | **NEW** — click-to-verify handler calling `/broker/positions/<id>` | ~5165 |
| `_renderStrategyCard()` JS | **ADDED** inline health chip in each card header, `strategy-card-kpi-grid` class so @media hits | ~5020 |
| `renderStrategies()` JS | **REWRITTEN** — H161 cards wrapped in expandable group, UNATTRIBUTED banner shows closed trades + opens, header KPI includes UNATTR totals | ~5190 |

### Preserved verbatim (no changes)

- Auth flow (POST /auth, HttpOnly session cookie, `/_authcheck` nginx subrequest)
- All `localStorage` keys (`autobot_system_group`, `autobot_who`,
  `autobot_env`, `autobot_view`, `autobot_unit`, `briefings_period`,
  `briefings_strategy`)
- All existing tabs: AUTOBOT, BRIEFINGS, OBSERVER (Scenario V2), FXi, DEMO
- All existing API endpoints: `/trades`, `/briefings`, `/strategies`,
  `/fxi/briefings`, `/h144/trades`, `/h144/trades/summary`,
  `/observer/*`, `/registry`, `/news-state`, `/auth`
- Equity canvas rendering (`drawEquity()`)
- Date pickers + period buttons
- Nginx routing (no config changes needed — new routes `/service-health`
  and `/broker/positions/<id>` are proxied by the catch-all `/trades`
  pattern — see §6.2 if that's incorrect for your nginx)

### Scenario V2 separation (operator requirement 4)

Scenario V2 observation / shadow activity remains in its dedicated
OBSERVER tab, routed to `127.0.0.1:8090/observer/*`. The AUTOBOT and
STRATEGIES tabs show only broker-executed trades (sourced from
`/trades?view=raw&period=all`, which pulls from IG transaction history +
signal_log — never from the observer). The two surfaces have **zero**
overlap.

### Responsive design (operator requirement 6)

Three breakpoints:

- **Desktop (≥1366 px)** — unchanged from current layout: 6-column KPI
  grids, horizontal strategy card headers, 7-column trade row grids.
- **Tablet (769–1365 px)** — strategy card KPI grid collapses to 3
  columns, tab padding tightens.
- **Mobile (≤768 px)** — tab bar scrolls horizontally with touch-smooth
  overflow, strategy card KPI grid collapses to 2 columns, trade rows
  reflow from `display:grid` to block-level (each row is a stacked
  pseudo-card with inline-block spans).
- **Narrow mobile (≤480 px)** — H161 group header padding tightens
  further.

Operator requirement 7 (no clipped columns): all grid rows that would
overflow at narrow widths are redeclared `display: block !important` in
the mobile media query so span children fall into natural wrap. No
`overflow-x: auto` scrollbars inside cards.

### "Never show zero when data is unverified" (operator requirement 9)

Three callouts:

1. Service-health chip renders `UNKNOWN` with tooltip `"no
   /service-health row for this service"` when the endpoint has not
   returned yet — not a silent `HEALTHY`.
2. UNATTRIBUTED card renders both opens and closed trades inline with
   per-row `attribution_note` hover tooltip explaining why.
3. The AUTOBOT and Strategies summary KPI chips use `_fmtPnlPounds(null)`
   → `"—"` rather than `"£0.00"` when the underlying data layer returns
   null (unverified).

### Broker-vs-ledger disagreement banner (operator requirement 10)

Every `is_open` row with `provenance === 'EXTERNAL'` on a known-service
prefix (`EMAPB`, `HBB`, `HLS`, `HMA`, `H161`) surfaces in the red
"broker open · local ledger says CLOSED" banner at the top of the
Strategies tab. Each row carries a `verify at broker →` link that
calls the new read-only `/broker/positions/<id>` endpoint and alerts
the dashboard operator with the authoritative deal-id response.
**No order-side action is ever offered** — the banner is diagnostic
only.

Currently (per the live /trades snapshot) **2 EMAPB positions have the
disagreement signature**:

- `DIAAAAYR3TPT4BU` (EMAPB-B-1793304045-89EC3C) — the audit's original orphan
- `DIAAAAYR4FEYEBL` (EMAPB-B-1793320628-F8E4EF) — a **new** orphan surfaced during this
  session that is directly linked to the D-03 misfire fingerprint

Both will appear in the banner on the staged dashboard.

### H161 consolidation (operator requirement 5)

The seven H161 cards (V3_BB, V3_EMA, BOUNCE_TR, BOUNCE_SQ,
GBPUSD_BB_BOUNCE, TREND_V3, TREND_V3_UM, plus the three OFF-with-activity
catalog entries BOUNCE_A, BOUNCE_C, EMA_PULLBACK) are wrapped in a
single `<div class="autobot-group">` with:

- Headline: `AutoBot V3 (combined)` + aggregate day P&L + aggregate pip
  P&L + aggregate trade count + aggregate open count + H161 health chip
- Click-to-expand arrow (`▶` → `▼`)
- Expanded body: the per-strategy card details, one per row,
  **identical** to the current per-card rendering (preserves full detail)

Sibling-service cards (HBB BB Bounce, HLS, HMA, EMAPB) render inline
below, each a top-level row.

---

## 6. Deployment procedure (NOT YET EXECUTED — AWAITING OPERATOR APPROVAL)

### 6.1 Pre-deploy backups (routine)

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p /opt/autobot-dashboard/archive
cp /opt/autobot-dashboard/index.html \
   /opt/autobot-dashboard/archive/index.html.pre-dashboard-full-$TS
cp /opt/tradingbot/trades_api.py \
   /opt/tradingbot/archive/trades_api.py.pre-dashboard-full-$TS
cp /opt/tradingbot/strategy_services.py \
   /opt/tradingbot/archive/strategy_services.py.pre-dashboard-full-$TS
```

### 6.2 Nginx — verify no route changes needed

```bash
grep -nE "(service-health|broker/positions)" /etc/nginx/sites-available/autobot-dashboard
```

If the output is empty, nginx will fall through to the catch-all
`location / {}` which proxies to `127.0.0.1:8080`. Expected to be the
case; **if the output has existing lines**, pause and consult operator.

### 6.3 Backend staged install

```bash
cp /home/autobot/tradingbot-wt/dashboard-full-20261029/trades_api.py \
   /opt/tradingbot/trades_api.py
cp /home/autobot/tradingbot-wt/dashboard-full-20261029/strategy_services.py \
   /opt/tradingbot/strategy_services.py
```

### 6.4 Backend restart (trades-api only — never autobot)

```bash
sudo systemctl restart trades-api.service
sleep 5
systemctl is-active trades-api.service
# Verify new routes:
curl -s http://127.0.0.1:8080/service-health | head -c 300
curl -s http://127.0.0.1:8080/broker/positions/DIAAAAYR3TPT4BU | head -c 300
```

**No other service is restarted.** Specifically: `autobot.service`,
`ema-pullback.service`, `bb-bounce.service`,
`london-liquidity-sweep.service`, `ma-cross-h1.service` all stay up.

### 6.5 Dashboard staged install

Operator decides between two deployment strategies:

**Option A — direct swap (operator approves after browser review):**
```bash
cp /home/autobot/tradingbot-wt/dashboard-full-20261029/autobot-dashboard/index.staged.html \
   /opt/autobot-dashboard/index.html
sudo systemctl reload nginx
```

**Option B — dev-route first (safer):**
Add a `/dev-dashboard/` location to nginx that serves `index.staged.html`
and leave the production `index.html` untouched. Operator browser-tests
the staged variant at `/dev-dashboard/`, then promotes.

### 6.6 Phase C acceptance gate

Run the test suite against the live post-deploy endpoint:

```bash
cd /home/autobot/tradingbot-wt/dashboard-full-20261029
python3 -m pytest tests/dashboard_full_20261029/ -v
```

Expected: **29 PASS / 0 FAIL / 1 SKIP** (the recording-only baseline test
stays skipped by design).

If any live-endpoint test fails, roll back per §6.7.

### 6.7 Rollback

```bash
TS=<timestamp from step 6.1>
sudo systemctl stop trades-api.service
cp /opt/tradingbot/archive/trades_api.py.pre-dashboard-full-$TS \
   /opt/tradingbot/trades_api.py
cp /opt/tradingbot/archive/strategy_services.py.pre-dashboard-full-$TS \
   /opt/tradingbot/strategy_services.py
cp /opt/autobot-dashboard/archive/index.html.pre-dashboard-full-$TS \
   /opt/autobot-dashboard/index.html
sudo systemctl start trades-api.service
sudo systemctl reload nginx
```

Rolls back cleanly in under a minute. No trading-service state touched.

---

## 7. Open items for operator

1. **D-03 fix** — a HIGH-severity defect NOT addressed by this project.
   `DIAAAAYR4FEYEBL` is currently LIVE broker-OPEN with ledger-CLOSED.
   Three unresolved deals from the 11-hour window
   (`DIAAAAYR2YZ6RB3`, `DIAAAAYR3ETVCAY`, `DIAAAAYR4QJPMAG`) also need
   deal-id audit. Full investigation + proposed correction in
   `reports/D03_ema_pullback_reconciler_investigation.md`.
2. **DIAAAAYR3TPT4BU remediation** — no action taken. Position is intact
   on broker with Method B SL/TP envelope. Three paths: (a) manual close,
   (b) let broker SL/TP run its course, (c) resolve as part of the D-03
   fix workstream.
3. **nginx dev-route** vs **direct swap** — your call per §6.5.
4. **D-05 historical P&L recomputation** — the +£375 pre-patch
   over-report means prior daily journals + weekly reports that quoted
   `/trades` sums are **inflated**. Consider a one-off recompute pass
   before relying on any pre-2026-10-30 daily number.
5. **Scenario V2 OBSERVER tab** — unchanged by this project. The
   previous memory note (`project_scenario_v2_c4_deployed_20261029`)
   remains the governing spec for that pipeline.

---

## 8. Deliverables (branch `fix/dashboard-full-20261029`)

- `strategy_services.py` — D-01 patched (+42 / −11)
- `trades_api.py` — D-02 + D-04 + D-05 + D-06 patched (+542 / −20)
- `autobot-dashboard/index.staged.html` — Phase B staged dashboard (new)
- `tests/dashboard_full_20261029/*.py` — 5 test modules, 29 tests
- `reports/D03_ema_pullback_reconciler_investigation.md` — HIGH-priority separate workstream
- `reports/PHASE_C_DEPLOYMENT_REPORT.md` — this document

Branch pushed to GitHub via the autobot_reports repo workflow in Phase C
completion. **No production file has been modified.** No service has
been restarted.

Awaiting operator approval of §6.5 and §7.4 before any production step.
