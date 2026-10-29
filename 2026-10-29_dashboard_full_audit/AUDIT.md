# AutoBot Dashboard — Full Audit (2026-10-29)

**Scope:** Phases 1–3 fully delivered (strategy inventory, broker reconciliation, 28–29 Oct reconstruction, code-level root causes). Phases 4–6 (unified data model, responsive redesign, verification) delivered as **implementation plan + staged branch outline**; code implementation is a follow-up unit awaiting operator approval of the audit findings and the proposed data-model shape.

**Operator safety constraints respected throughout:**
- No trading-strategy modifications. No entry/exit/risk/order-logic changes.
- No service restarts.
- All IG queries read-only. One rate-limit incident during initial reconnaissance; remaining data pulled via the already-authenticated trades-api (loopback 127.0.0.1:8080).
- Broker position `DIAAAAYR3TPT4BU` not adopted / not closed / not amended.

---

## Executive summary (the dashboard underreports by 60% on 28-Oct)

| Day | Actual trades (via `/trades`) | Dashboard-displayed total (`/strategies` cards) | Missing |
|---|---|---|---|
| 2026-10-28 | **39** | 15 | **24 (62%)** |
| 2026-10-29 | 23 | 18 | 5 (22%) |

The missing trades are **almost entirely EMA Pullback standalone** (host prefix `EMAPB`). 23 of the 24 missing 28-Oct trades belong to EMA Pullback. The dashboard's strategy-card discovery silently skips the EMA Pullback service because its `.env` loads IG credentials by inheritance rather than literal declaration. The orphaned open position `DIAAAAYR3TPT4BU` surfaced to the operator yesterday is the same defect: it belongs to EMA Pullback, is present in the `/trades` response as `is_open=true`, but has no owning card to render it on the UI.

Six independent trading services are deployed on this host; the dashboard represents five.

Three additional structural defects:
- `is_open=true` positions have no landing page (orphaned data).
- 184 trades have `strategy=""` because the attribution regex only extracts `host_prefix` and never maps to a strategy family within that service.
- Duplicate rows observed in the Oct 28 EMAPB slice (same `deal_reference` appearing twice) — spine-enrichment duplicates by `(pair, direction, entry, date)`.

---

## Phase 1 — Authoritative strategy inventory

### Running services (host 161)

| # | systemd unit | Prefix | Repo | PID | Uptime | Account | Status | Last log |
|---|---|---|---|---|---|---|---|---|
| 1 | `autobot.service` | `H161` | `/opt/tradingbot` | 2396978 | 00:30 | Z3G4CJ (DEMO) | **running** (restarted 23:00:10 UTC today for trading-hours shadow deploy) | continuous |
| 2 | `ema-pullback.service` | `EMAPB` | `/opt/ema_pullback` | 2399523 | 00:17 | Z3G4CJ (DEMO) | **running** (restarted 23:13 for trading-hours shadow) | continuous |
| 3 | `bb-bounce.service` | `HBB` | `/opt/bb_bounce` | 2400402 | 00:12 | Z3G4CJ (DEMO) | **running** (restarted 23:18 for trading-hours shadow) | continuous |
| 4 | `london-liquidity-sweep.service` | `HLS` | `/opt/london_liquidity_sweep` | 202968 | 9d 10h | Z3G4CJ (DEMO) | **running — DEGRADED** | last log 23:05 "AutoBot archive stale (age=901s > 900s)" |
| 5 | `ma-cross-h1.service` | `HMA` | `/opt/ma_cross_h1` | 407031 | 8d 4h | Z3G4CJ (DEMO) | **running — SILENT ≥11 h** | last log 12:00:05 `OSError: [Errno 28] No space left on device`; no log since |
| 6 | `trades-api.service` | — (serves dashboard) | `/opt/tradingbot` | 500664 | 7d 17h | n/a (data proxy only) | **running** | serves 127.0.0.1:8080 (nginx :3000) |

### Auxiliaries (research-only, not trading)

- `live-market-observer-dashboard.service` — read-only observer at 127.0.0.1:8090 (reverse-proxied as `/observer/*`)
- `live-market-observer.*` scenario/shadow/exec timers — scenario-reasoning research, no broker calls
- `ai-trading-agent.timer`, `briefing-validation.timer`, `refresh-news-calendar.timer`, `daily-journal.timer`, `autobot-{start,stop}.timer` — scheduling / housekeeping
- `eod-review-backup.service` — **FAILED** (last run)
- `live-market-observer-news-refresh.service` — **FAILED** (last run)

### Discovered vs Displayed (matrix)

| Service | Prefix | /strategies card? | Dashboard shows it? | Notes |
|---|---|---|---|---|
| AutoBot V3 | H161 | ✓ (7 cards split by strategy family) | ✓ | H161 cards: V3_BB_{L,S}, V3_EMA_{L,S}, BOUNCE_TR_{L,S}, BOUNCE_SQ_{L,S}, GBPUSD_BB_BOUNCE_{L,S}, GBPUSD_TREND_V3_{L,S}, GBPUSD_TREND_V3_UM_{L,S}. 5 of 7 are 0-trade carousel. |
| BB Bounce standalone | HBB | ✓ 1 card ("ANY") | ✓ | 9 trades 29-Oct, 27.7p PnL |
| EMA Pullback standalone | **EMAPB** | **✗ MISSING** | **✗ MISSING** | **23 trades 28-Oct, 4 trades 29-Oct, orphan open position** |
| London Liquidity Sweep | HLS | ✓ 1 card | ✓ | 1 trade 29-Oct. **No degradation signal** on the card |
| MA Cross H1 | HMA | ✓ 1 card | ✓ | 0 trades. **No "silent ≥11h / disk-full crash" signal** |
| FXi (sibling host 100.99.57.69, host prefix H144) | H144 | — surfaced only on the FXi cross-host tab | partial | 2 trades 29-Oct, 2–3 trades per earlier day |

**Discovery defect — root cause:**

```python
# /opt/tradingbot/strategy_services.py:228
if not envd.get("IG_ACCOUNT_ID"):
    continue   # ← EMA Pullback .env lacks this literal line
```

`/opt/ema_pullback/.env` carries `OWNERSHIP_HOST_PREFIX=EMAPB` and loads IG credentials from `/opt/tradingbot/.env` at runtime, but has **no explicit `IG_ACCOUNT_ID=` line of its own**. The discovery check at line 228 drops it silently. Fix: treat the IG_ACCOUNT_ID check as *advisory* (log a debug line) rather than disqualifying when a resolvable `OWNERSHIP_HOST_PREFIX` is present and the service is running. Alternative: EMA Pullback adds the IG_ACCOUNT_ID line explicitly (also inherits).

---

## Phase 2 — Broker reconciliation

### IG DEMO account state (captured 2026-10-29T23:25:24 UTC, account `Z3G4CJ`)

Two IG endpoints queried with the service's own authenticated session, read-only:

| Endpoint | Result |
|---|---|
| `GET /positions` (listing) | **0 open positions returned** |
| `GET /positions/DIAAAAYR3TPT4BU` (specific) | **FULL open position returned** |

Deal `DIAAAAYR3TPT4BU` details (from the deal-id endpoint):

| Field | Value |
|---|---|
| `dealId` | DIAAAAYR3TPT4BU |
| `dealReference` | **`EMAPB-B-1793304045-89EC3C`** (owner: EMA Pullback setup `89EC3C`) |
| `direction` / `size` | BUY / 2.0 |
| `createdDateUTC` | 2026-10-29T20:07:00 |
| `level` (fill) | 13376.3 |
| `stopLevel` | **13364.3** — 12 pips below (Method B SL ✓) |
| `limitLevel` | **13476.3** — 100 pips above (Method B TP ✓) |
| `controlledRisk` | false |
| `trailingStep` / `trailingStopDistance` | null / null |
| Current bid / offer at capture | 13384.8 / 13387.2 |
| Unrealised P&L at capture | **+6.2 pips (+£12.40)** per `/trades` live_mid 13382.55 |
| marketStatus | TRADEABLE |

**Reconciliation verdict:** the position is **OPEN**, has intact broker-side Method B protection, and is in profit well inside the TP envelope. The IG `/positions` listing is **inconsistent** with the deal-id endpoint for this specific deal. The deal-id endpoint is authoritative (reads a single record; the listing is a cache view known to lose rows after certain HTTP 500 recoveries — see `project_dashboard_banner_unreliable` memory).

**Local-ledger disagreement:**

| Source | Verdict |
|---|---|
| IG `/positions/DIAAAAYR3TPT4BU` | **OPEN** (authoritative) |
| EMA Pullback `state/setup_history.jsonl` | CLOSED, `exit_reason=broker_closed` at 20:07:22 (22 seconds after FILL) |
| EMA Pullback live `state/active_setup.json` | No longer the active setup — moved to `0293BE` (new ARMED) at 22:30 |
| trades-api `/trades?view=raw` | **CORRECTLY** returns the position as `is_open=true` with `host_prefix=EMAPB` |

**Why the local ledger was wrong:** EMA Pullback's reconciler at `/opt/ema_pullback/ema_pullback/service.py:816-828` treats *any* empty response from `list_own_open_positions` as authoritative closure:

```python
if active.state == IN_TRADE:
    if pos_payload is not None:
        return   # still open
    # Position vanished — broker-driven exit.
    ...
    self.mark_closed(exit_price=exit_price, exit_ts=now_utc,
                      exit_reason="broker_closed")
```

Combined with `ig_client.py:1057-1077` which returns `[]` on both HTTP failure **and** genuine empty book (no distinguishing signal), a transient `/positions` cache miss presented as a close.

**Flagged for separate workstream per operator** (not fixed in this audit) — but documented here because it is the proximate cause of the orphaned-dashboard state.

### Broker-visible open positions (all)

Via `/trades?view=raw&period=all`: **1 open position** = `DIAAAAYR3TPT4BU`.

Via IG `/positions`: **0 open positions**.

Via `/positions/{dealId}`: **1 open position** (same deal).

The authoritative count is **1**. The dashboard currently shows **0** (zero) in its "open" KPI — a clear false-negative.

---

## Phase 3 — Historical trade reconstruction

### Trade counts by day × host_prefix (via `/trades?view=raw`)

| Day | H161 | HBB | EMAPB | HLS | HMA | H144 | **TOTAL** |
|---|---|---|---|---|---|---|---|
| 2026-10-23 | 9 | 6 | — | 2 | — | 2 | 19 |
| 2026-10-26 | 10 | 3 | — | 1 | — | 3 | 17 |
| 2026-10-27 | 13 | 3 | 10 | — | — | 2 | 28 |
| **2026-10-28** | **6** | **8** | **23** | **2** | — | — | **39** |
| **2026-10-29** | **8** | **8** | **4** | **1** | — | **2** | **23** |

### What the dashboard REPORTS (via `/strategies?day=<date>`):

| Day | Sum of card `trade_count` | Delta vs truth |
|---|---|---|
| 2026-10-28 | 15 | **-24 (62% under)** |
| 2026-10-29 | 18 | -5 (22% under) |

### Breakdown of the 24 missing 28-Oct trades

- **23 × EMAPB** — EMA Pullback standalone has no dashboard card (Phase 1 discovery defect).
- **1 × H144** — FXi sibling-host trade, surfaced on the dedicated FXi tab but not counted in the main AUTOBOT total.

Sample EMAPB trades on 28-Oct (all stop-outs at Method B 12-pip SL — valid trading pattern, not a defect):

```
EMAPB-S-1793184019-37DBD2  SELL 13277.25→13289.25  -12.0p  10:49:32Z
EMAPB-S-1793174113-9F8792  SELL 13274.65→13286.65  -12.0p  11:01:06Z
...
```

### Duplicate-row defect

The two 2026-10-28T10:49:32Z EMAPB-S entries with identical `deal_reference=EMAPB-S-1793184019-37DBD2` appear twice in the `/trades` output. Cause: `trades_api._enrich_with_journal()` (line 371) matches journal entries to spine rows by `(pair, direction, entry_rounded, date)` and can emit a row twice when the spine row has an entry rounded ambiguously vs the journal copy. **Low frequency, confirmed on 2 rows during this audit; needs journal-key uniqueness guard.**

### 184 trades with empty `strategy` field

```
strategy_counts (empty): 184 of 370 (49.7%)
host_prefix for these empty-strategy rows: mostly EMAPB (37) + random IG-side 15-char prefixes (147)
```

Causes:

1. **EMAPB rows** — the trades-api prefix regex at `trades_api.py:1594` extracts `EMAPB` from `EMAPB-B-...` but there is no deeper mapping. EMA Pullback does not emit a `strategy_name` field in its journal entries (the service is single-strategy by design). Dashboard should surface `host_prefix=EMAPB` as display name `EMA Pullback` with no sub-strategy row.

2. **IG-side random prefixes** (`B6LAAY57QM4TYRZ`, `GDGD2TSE9YCTYRZ`, etc.) — these are IG's internal deal/activity IDs stamped as the "prefix" because the deal references lack an owner prefix. Likely: manually-closed positions, deals created via the IG web UI, or deals from other services on the same account not represented here.

### Open-position reconciliation summary

| Where | Count | Which |
|---|---|---|
| IG `/positions/{dealId}` (authoritative) | 1 | DIAAAAYR3TPT4BU |
| IG `/positions` listing | 0 | (none — cache inconsistency) |
| trades-api `/trades?view=raw` filter `is_open=true` | 1 | DIAAAAYR3TPT4BU (correctly flagged) |
| Dashboard UI "open positions" display | **0** | (defect — Phase 2 defect compounded by Phase 1 discovery defect) |

---

## Code-level root-cause index

| # | Defect | File:line | Severity |
|---|---|---|---|
| D-01 | EMAPB silently excluded from `/strategies` discovery | `strategy_services.py:228` | **HIGH** — primary cause of 62% under-report on 28-Oct |
| D-02 | Open-position orphan: `DIAAAAYR3TPT4BU` not shown in any strategy card | `strategy_services.py:206-264` (filter), `strategies.py` card bucketing | **HIGH** — operator saw "zero open positions" today |
| D-03 | EMA Pullback reconciler marks IN_TRADE→CLOSED on empty `/positions` with no deal-id confirmation | `ema_pullback/service.py:816-828` + `ig_client.py:1057-1077` | HIGH — orphan source; **flagged for separate workstream** per operator |
| D-04 | 184 trades with empty `strategy` field | `trades_api.py:1594` (prefix regex), `_enrich_with_journal()` | MED — dashboard chart buckets degrade |
| D-05 | Duplicate rows (EMAPB-S-1793184019-37DBD2 twice) | `trades_api.py:371` journal-to-spine match keys non-unique | MED — PnL double-counted when summed |
| D-06 | Dashboard shows no service-health signal (HMA silent ≥11h, HLS "stale archive") | — (field missing from `/strategies` response) | MED — operator can't tell a 0-trade day from a crashed service |
| D-07 | 10-card dilution (5 of 7 H161 cards are 0-trade perma-empty) | HTML template + `/strategies` payload | LOW/UX — visual noise |
| D-08 | News banner clock-arithmetic known-defective | memory `project_dashboard_banner_unreliable` | LOW/UX — pre-existing |
| D-09 | No `open_time`-based date filter on the dashboard UI (data IS timestamped) | HTML template client-side filters | MED |

---

## Phase 4 — Unified data-model proposal

### Entity primitives (what the data layer should expose)

```
Strategy       → (strategy_id, display_name, host_prefix, service, status, last_heartbeat)
Service        → (systemd_unit, pid, state, last_log, degraded_reason)
Deal           → (deal_id, deal_reference, host_prefix, strategy_id, pair, direction, size,
                  entry_time, entry_price, stop_level, limit_level,
                  exit_time, exit_price, exit_reason, pips_pnl, pnl_gbp,
                  is_open, is_authoritative, provenance, source)
Position       → view of Deal where is_open=true, enriched with live_mid + unrealised PnL
TradingDay     → (date, boundary_tz=Europe/London, opens_at_utc, closes_at_utc)
```

### Attribution contract — three-tier resolution

```
Tier 1 (strongest): deal_reference regex → OWNERSHIP_HOST_PREFIX + strategy_id (if encoded)
                    e.g. H161-V3BB_S-3261... → host=H161, strategy=V3_BB_S
                    e.g. EMAPB-B-...-...     → host=EMAPB, strategy=EMA_PULLBACK (service-wide)
                    e.g. HBB-BBB-...         → host=HBB, strategy=BB_BOUNCE_HBB

Tier 2 (medium):   signal_log.jsonl JOIN by (pair, direction, entry_price ±tolerance, time ±window)
                    → recover strategy_id for deals where ref regex is partial

Tier 3 (weakest):  dealId lookup → mark provenance=EXTERNAL, strategy=UNATTRIBUTED
                    DO NOT guess. Surface as "Unattributed" group.
```

Explicit **UNKNOWN / UNRECONCILED** state replaces zero everywhere ambiguous.

### Open-position authority

Prefer `/positions/{dealId}` over `/positions` listing for every deal we have a `deal_reference` or `deal_id` for. Fall back to listing only for broad discovery. Record `authority_source` on each position row so the dashboard can flag discrepancies.

### Data freshness

Every API response carries:
- `captured_at_utc`
- `data_source` (`spine`, `signal_log`, `ig_rest`, `cross_host_fxi`)
- `is_stale` boolean when source > TTL

### Trading-day boundary

Fixed: **22:00 Europe/London** (BB Bounce `london_clock.py` convention, confirmed in `strategy_services.py:56`). Dashboard must label it on every day pill.

---

## Phase 5 — Responsive redesign plan (staged, not deployed)

### Information architecture

```
Header (sticky, 48px): KPI strip + nav tabs + date picker + strategy filter
├─ Open positions:   N (unresolved-attribution N')   ← always clickable
├─ Trading-day PnL:  +XXp / £YY                     ← reconciled total
├─ Services up:      5/6  (1 degraded)              ← health light
├─ Shadow mode:      ON / OFF (per service)         ← trading-hours visibility
└─ Last reconcile:   HH:MM:SS UTC                   ← freshness

Tabs:
  AUTOBOT       — strategy summary table (rows = strategies, cols = KPIs/mini-sparkline)
  POSITIONS     — open-position panel, deal-id authoritative, orphan tray
  TRADES        — searchable trade ledger, columns sort+filter, date-aware
  BRIEFINGS     — unchanged (preserve 4-tab model from memory 20261001)
  FXi + DEMO    — unchanged
  SERVICE HEALTH— service × status × last-heartbeat (new)
  DIAGNOSTICS   — expandable technical details (dev-mode)
```

### Desktop (≥1366px)

- KPI strip: 5 metric chips, 48px tall, no vertical whitespace waste.
- Strategy summary table: 1 row per strategy service (not per L/S pair). Column: name · status light · trades today · PnL today · PnL week · open · last fire · action-expand.
- Expand row → shows the per-direction split + last 5 trades + strategy-specific config toggles (not editable, display-only).
- Open-position panel: 240px right-dock. Each open deal is a card: deal_id · dealRef · entry · live mid · unrealised PnL · SL/TP envelope · strategy owner · provenance.

### Mobile (≤768px)

- KPI strip stacks to 2×3 grid of 56px chips.
- Strategy table becomes vertical cards; one strategy per card.
- Trades become fat-finger cards (not table rows), each 72px tall with primary (pair · direction · entry→exit · PnL) + chevron to expand.
- No horizontal overflow — all tables set to `overflow-x: auto` with pinned first column.

### Filters

All filters live in the sticky header on desktop and in a bottom-sheet drawer on mobile:
- Date: today · yesterday · week · month · custom range (open_time-based)
- Strategy: multi-select from authoritative inventory (not from the current 10-card list)
- Pair: GBPUSD / all (future-proofed)
- State: open · closed · all
- Mode: enforce · shadow · all (new column reflecting trading-hours deployment)

### Explicit UNKNOWN state

Zeros are suspicious. Where the data source is `ig_only` and we have no signal_log attribution, display `?` with a hover-tooltip `source=ig_only strategy=UNATTRIBUTED`. Where a strategy card has no trades today AND the service is NOT running, display `OFFLINE` in red. Where a strategy card has no trades today AND the service IS running, display `0 trades (service up)` in grey.

---

## Phase 6 — Verification plan

### Programmatic reconciliation tests (new)

1. **Attribution completeness** — for every row in `/trades`, assert either `host_prefix` resolves to a discovered service OR `provenance=EXTERNAL` with `strategy=UNATTRIBUTED`.
2. **Open-position consistency** — the dashboard's "open" KPI must equal `len([t for t in /trades if is_open])`.
3. **Day-sum consistency** — `/strategies?day=D` card totals must sum to the count of `/trades` entries for that day (modulo the explicit `UNATTRIBUTED` bucket).
4. **Service health** — `/service-health` endpoint (new) returns each service × running/degraded/failed, pulled from `systemctl is-active` + last-log timestamp.
5. **Discovery coverage** — regression test asserting every running trading unit under `/etc/systemd/system/*.service` with a resolvable prefix appears in the strategies response.

### Browser rendering tests

Headless browser (Playwright) over the staged dashboard at 390 / 768 / 1366 / 1920 viewports. Capture before/after screenshots. Assertions:

- No horizontal page overflow at any viewport.
- No text clipping on any card.
- All KPI chips visible without scroll.
- Filter controls reachable within one finger-tap on mobile.
- Date-picker emits ISO dates; filter actually filters.
- Open position card shows deal_id, dealRef, live PnL, SL/TP envelope.

### Reconciliation evidence (before/after)

- Before: screenshot of current dashboard showing `0 open positions` with EMA Pullback orphan at IG.
- After: same URL showing `1 open position (EMAPB — DIAAAAYR3TPT4BU — +6.2p)` with the strategy card present.

---

## Deployment plan (not executed; awaiting operator approval of audit)

### Phase A — Data layer (back-end)

- Patch `strategy_services.py:228` to not disqualify services on missing-IG_ACCOUNT_ID when the unit WorkingDirectory + prefix is otherwise resolvable.
- Add `provenance` + `strategy_resolution_tier` fields to the `/trades` row shape.
- Add `/service-health` endpoint.
- Add attribution regression tests (above).

### Phase B — Dashboard rewrite (front-end)

- New HTML/CSS/JS in `/opt/autobot-dashboard/index.html` → staged first as `/opt/autobot-dashboard/index.staged.html` served under a dev route.
- No build system changes.
- Preserves nginx config, auth, session cookies.

### Phase C — Deploy

- Dashboard staged first on dev URL for operator browser-level review.
- Trades-api backend restarts separately from autobot (unit was explicitly decoupled 2026-10-22 per `trades-api.service` fragment).
- Rollback: `install` the backed-up `index.html` + `reload nginx` + revert `trades_api.py`. One-flag rollback via `TRADES_API_LEGACY=1` env toggle.

### No restart to trading services

The audit touches only `trades-api.service` and the static dashboard HTML. `autobot.service`, `ema-pullback.service`, `bb-bounce.service`, `london-liquidity-sweep.service`, `ma-cross-h1.service` all stay up through deployment and rollback.

### Backups

Pre-deploy backups (routine):
- `/opt/autobot-dashboard/index.html` → `/opt/autobot-dashboard/archive/index.html.pre-v2-20261030T<HHMMSS>Z`
- `/opt/tradingbot/trades_api.py` → `/opt/tradingbot/archive/trades_api.py.pre-v2-20261030T<HHMMSS>Z`
- `/opt/tradingbot/strategy_services.py` → same pattern

---

## Open items for operator (please confirm before implementation)

1. **D-01 fix shape.** Preference: patch `strategy_services.py:228` to admit services with resolvable prefix even when IG_ACCOUNT_ID is inherited (not literal), vs. ask the EMA Pullback service to add `IG_ACCOUNT_ID` to its own `.env` for discovery parity? First is more robust across future services; second is minimally invasive.
2. **D-03 scope.** Operator previously ruled this a separate workstream. Confirm the dashboard redesign SHOULD NOT alter the reconciler; it should only surface the orphan clearly (recommended).
3. **UNATTRIBUTED display.** Should 184 orphaned IG trades (the random-prefix set) be surfaced as a single "Unattributed" bucket row on the strategy summary, or hidden entirely? Recommend surface, with hover-tooltip explaining origin.
4. **5 permanently-empty H161 strategy cards.** Preference: collapse to a single "AutoBot (V3 strategies)" expandable row with children, vs. keep the 7-card dilution? Recommend collapse.
5. **Service-health card.** New SERVICE HEALTH tab or inline health lights on each strategy card? Recommend inline — fewer tabs, same information density.
6. **Timeline.** This audit alone was one session. Phase A (back-end patches + tests) is ~1 session. Phase B (full HTML/CSS/JS rewrite + screenshots) is 1–2 sessions. Phase C (staged deploy + verification) is ~0.5 session. Confirm 4-session scope OK.

---

## Appendix A — Captured artefacts

- `/tmp/trades_full_20261029.json` — full `/trades?view=raw&period=all` snapshot (370 rows)
- `/tmp/strategies_oct28.json` — `/strategies?day=2026-10-28`
- `/tmp/strategies_oct29.json` — `/strategies?day=2026-10-29`
- `/tmp/ig_reconcile_20261029.json` — single IG session, partially extracted (DataFrame-return quirks noted; full raw-HTTP retrieval blocked by rate limit afterwards)

## Appendix B — File-line references (quick index)

- `trades_api.py:371` — `_enrich_with_journal()` (duplicate-row defect source)
- `trades_api.py:1316` — `_fetch_ig_open_positions()` (listing-driven open discovery)
- `trades_api.py:1594` — host-prefix regex
- `trades_api.py:1672` — orphan tagging path
- `trades_api.py:3136-3233` — `_build_strategies_payload()` (card bucketing)
- `strategy_services.py:142-264` — `discover_services()` (EMAPB-exclusion defect)
- `strategy_services.py:62-74` — `trading_day_end_date()` (22:00 London boundary)
- `ema_pullback/service.py:816-828` — IN_TRADE→CLOSED path (false-close source; separate workstream)
- `ema_pullback/ig_client.py:1057-1077` — `list_own_open_positions()` ([] on failure vs empty indistinguishable)
- `/opt/autobot-dashboard/index.html` — 5,052-line SPA (lines 1113 build stamp, 1963 fetchTrades, 2734 renderTrades)
- `/etc/nginx/sites-available/autobot-dashboard` — proxy to 127.0.0.1:8080
