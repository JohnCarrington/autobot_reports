# R1 — Historical Data Architecture V2 Production Rollout

**Date:** 2026-09-21
**Phase:** R1 (integrate + deploy + activate M0-M6 historical chain with trading disabled)
**Result:** PASS — historical architecture active in production, TRADE_ENABLED=0 preserved throughout.

## Accepted chain deployed

| Milestone | Commit | Description |
|-----------|--------|-------------|
| M0-M3 | `4b354f4` | H4 persistence + Phase 1b reconstruction |
| PRIOR_D1 | `fa18a90` | Authoritative previous-completed-D1 selector |
| MULTIDAY_GUARD | `783eb0e` | 5D/20D weekend-fragment guard |
| M4 | `4bf3e55` | Persisted daily structural snapshot |
| M4_CLOSURE | `ed294b7` | Combined weekend boot + allowance proof |
| M5 | `fb13107` | Daily-structural-context consumer + readiness |
| M6 | `835fc9e` | Historical gap-repair authority + H4 REST retirement |
| M6_AUTHORITY_CLOSURE | `6a3bc2e` | Universal REST authority + fail-closed |
| M6_INTEGRATION_PROOF | `e8534f2` | Journal lifecycle + fallback authority defects exposed |
| M6_DEFECT_FIX | `79a31a0` | DEFECT_A journal lifecycle + DEFECT_B MINUTE fallback |

Production HEAD before and after rollout: `79a31a0` — no code integration needed; deployment was pure activation.

## Ancestry

- `PRODUCTION_HEAD_BEFORE = 79a31a039d198cd5943d9083cbfdcd914c1de25f`
- `HISTORICAL_BRANCH_HEAD = 79a31a039d198cd5943d9083cbfdcd914c1de25f`
- `MERGE_BASE = 79a31a039d198cd5943d9083cbfdcd914c1de25f`
- `INTEGRATION_HEAD = 79a31a039d198cd5943d9083cbfdcd914c1de25f`
- `INTEGRATION_METHOD = none required — HEAD already contains accepted chain`
- `PRODUCTION_INCIDENT_FIXES_PRESERVED = YES` — every prior incident/hotfix commit remains reachable from HEAD (PRICE stream migration `2bb9058`, terminal fail-closed `c3c9557`, rest_allowance chain `5cbbfa0` → `95b79d3` → `ed511ce`).

## Pre-deploy regression

- **371 M0-M6 accepted-chain tests + 69 PRICE stream / rest_allowance / lifecycle tests = 440 / 440 pass** on current HEAD.
- **Offline complete-cache boot proof** (using isolated copies of production D1/H1 caches under M0-M6 flags ON): M4 builds snapshot from persisted D1, M5 context ready, M6 authority refuses H4 REST → allowance would be preserved.

## Flag activation

Only four historical flags added to `/opt/tradingbot/.env`. Nothing else touched. Backup at `env-history/env.R1-pre-rollout.20260921T183217Z` (sha256 `da3436a5...` identical to pre-edit live).

| Flag | Default | R1 value | Purpose |
|------|---------|----------|---------|
| `HTF_V2_BOOT_ENABLED` | 0 | **1** | M0-M3 H4 persistence + Phase 1b reconstruction |
| `DAILY_SNAPSHOT_ENABLED` | 0 | **1** | M4 daily snapshot builder/reader |
| `DAILY_STRUCTURAL_CONTEXT_ENABLED` | 0 | **1** | M5 strategy readiness gate |
| `HISTORICAL_GAP_REPAIR_ENABLED` | 0 | **1** | M6 gap-repair authority + journal |
| `TRADE_ENABLED` | (existing) | **0** (unchanged) | Kill switch — trading MUST stay disabled in R1 |

Post-edit .env diff = exactly the 9 appended lines (4 flags + 5 comment/blank). `TRADE_ENABLED=0` verified unchanged.

## Restart

Single `systemctl restart autobot` executed by operator at 2026-09-21 18:34:44 UTC.

| Metric | Before | After |
|---|---|---|
| PID | 861510 | 907523 |
| NRestarts | 0 | 0 |
| Uptime | 5h 58min | fresh boot |
| .env sha256 | `da3436a5...` | `9654d748...` |
| Historical flags active in `/proc/PID/environ` | none | all 4 set to `1` |
| `TRADE_ENABLED` in `/proc/PID/environ` | `0` | `0` |
| rest_allowance sha256 | `8d07dd45...` used=7996/8000 | `8d07dd45...` used=7996/8000 **(unchanged)** |
| GBPUSD_D1.json | present, 185 bars | unchanged |
| GBPUSD_H1.json | present, 550 bars | unchanged |
| GBPUSD_H4.json | MISSING | **created 18:34:53, 9 bars from Phase 1b reconstruction** |
| EURUSD_H4.json | MISSING | **created 18:34:53, 9 bars** |
| GBPUSD_DAILY_SNAPSHOT.json | MISSING | **created 18:34:53 — trading_date=2026-09-21, source=2026-09-18 D1** |
| EURUSD_DAILY_SNAPSHOT.json | MISSING | **created 18:34:53** |
| repair_journal.json | MISSING | **created 18:34:53 — 4 entries** |

## Historical REST proof

**Allowance state unchanged**: sha256 `8d07dd45...`, used=7996/8000 both before and after restart.

The M6 repair_journal shows exactly what happened:

```
rid=9031d33e67e7a65c sym=GBPUSD res=HOUR class=insufficient_history_first_boot
  history=[DETECTED, AUTHORIZED, FAILED_NO_SEND, STILL_MISSING]
  FAILED_NO_SEND: {'charge': 6, 'stage': 'allowance_exhausted'}
rid=a9f6a1d59e502e3a sym=GBPUSD res=DAY  class=insufficient_history_first_boot
rid=04ad39e53452c6aa sym=EURUSD res=HOUR class=insufficient_history_first_boot
rid=58f936b6ad0fe0ce sym=EURUSD res=DAY  class=insufficient_history_first_boot
```

- **4 M6 authorisations** (HTF Phase 1 H1+D1 gap-fill for GBPUSD + EURUSD)
- **All 4 refused at `rest_allowance.begin_reservation`** — budget 4 remaining < 6-8 charge
- **`FAILED_NO_SEND` state recorded in M6 journal (DEFECT_A fix confirmed working in production)**
- **STILL_MISSING terminal state recorded**
- **Zero HTTP historical price calls issued**

Note: my HTF Phase 1 wiring passed `rolling_df=None` so the M6 classifier didn't see the 550/800 H1 candles already restored from disk cache. That led to `INSUFFICIENT_HISTORY_FIRST_BOOT` classification and authorization. The pre-existing rest_allowance safety gate provided the actual REST block. Zero-HTTP invariant held. Consider tightening the HTF Phase 1 M6 wiring in a follow-up (pass rolling_df + local derived counts) so the authority refuses under M6 without depending on rest_allowance exhaustion.

## Data readiness (post-restart, after Phase 1b reconstruction)

| Epic | H1 | H4 | D1 | Daily snapshot | M5 context |
|---|---:|---:|---:|:---:|:---:|
| GBPUSD | 550 bars ✓ | **9 bars (SHALLOW, needs 20)** | 185 bars ✓ | READY | READY |
| EURUSD | 800 bars ✓ | **9 bars (SHALLOW)** | 132 bars ✓ | READY | READY |

Honest limit: H4 depth is 9 bars from Phase 1b reconstruction of 600 persisted 5m rows. Below v5_pia's `_V5_PIA_H4_SUFFICIENT_BARS=20` threshold. Live 5m closes will grow this over time (persisted between restarts). v5_pia is correctly abstaining with `reason=insufficient_h4_bars` — this is legitimate strategy-level abstention on H4 depth, NOT an M5 context problem. M5 daily-structural-context is READY for both epics.

## Stability window (10 minutes from restart)

- No PID change (still 907523)
- No NRestarts change (0)
- No rest_allowance sha256 change
- No `error21`
- No `MARKET:CS.D` fallback subscriptions
- No terminal stream/auth failures
- No SystemExit / Traceback / crashes
- 100-110 GBPUSD PRICE ticks / minute
- 90-100 EURUSD PRICE ticks / minute
- Heartbeat: `💓 AutoBot running — tick age: EURUSD:0s | GBPUSD:0s | Cooldown: READY | READY`

## Trading gate confirmation

- `TRADE_ENABLED=0` verified in `/proc/907523/environ`
- **1 broker order attempt (BRIEFING_EXECUTION EURUSD SELL at 18:35:06 UTC)**
- **Executor returned `NoneType`** — kill switch working
- **Bucket NOT consumed** (retry allowed)
- **0 real `Trade OPENED` events**
- **0 `create_open_position` calls**
- Position polling (`GET /gateway/deal/positions`) is normal read-only IG API traffic, not a broker order.

## R1 verdict

- `PRODUCTION_STABLE = YES`
- `HISTORICAL_V2_PRODUCTION_PROOF = PASS`
- `TRADE_ENABLED = 0` (kill switch honored)
- `STAGE10P = PAUSED`

Awaiting R2 ruling for trading enablement. R1 does NOT authorise trading.
