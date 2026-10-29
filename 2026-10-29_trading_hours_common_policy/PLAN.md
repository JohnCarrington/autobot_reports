# Common Trading-Session Admission Policy — Consolidated Plan

**Status:** PROPOSAL — awaiting operator review
**Author:** autobot (2026-10-29)
**Trigger:** confirmed GBPUSD 14.3-pip evening spread at 21:40 UTC on 2026-10-29
**Branch (plan only):** `plan/trading-hours-common-20261029`
**No production changes.** No service restarts. No implementation branches merged.

---

## 1. Executive summary

- The operator proposes a shared admission window: **Mon–Fri 06:45–20:30 Europe/London**, applied uniformly across every execution-capable strategy and standalone service.
- The audit (§2) shows **four pre-existing time gates** today, all UTC-based and partially inconsistent. **None currently enforce the proposed window.** Two gates are stricter than the proposal (TREND_V3, BB_BOUNCE); one is looser on the evening boundary (central `QM_ENTRY_HOURS` 06:00–21:00 UTC); one is only an unused config declaration (`SESSION_WINDOWS_JSON`).
- The two standalone services (`/opt/ema_pullback`, `/opt/bb_bounce`) have **no time gate at all** today. They would gain one under this policy.
- Two existing modules (`briefing_hunt.py`, `london_open_pullback.py`) rely on a **broken BST heuristic** that already produces wrong offsets since 2026-10-25. The common policy's correct `ZoneInfo` implementation can retire those heuristics.
- **No historical spread evidence exists** in the repo for an evening expansion pattern beyond today's single 14.3-pip reading. A minimal pre-submit spread safety check is justified as a complement to the time cutoff — the two guard different failure modes.

**Proposed shape:**
1. One shared module `trading_hours.py` with a tz-aware admit function (common infra).
2. One **intersecting** gate per execution site — never widens, never overrides a strategy's stricter rule.
3. Cancellation of unfilled pending entries at cutoff **routes through each strategy's existing cancellation lifecycle** — the common gate never calls a broker close/cancel directly.
4. Zero exit-side, reconciliation, trailing, scale-out, SL/TP management touched.

**Open operator decisions** (§10) must be resolved before implementation branches are cut.

---

## 2. Audit findings

### 2.1 Execution entry points

| Strategy / service | Entry function | File:line | Current time gate |
|---|---|---|---|
| TREND_V3 | `evaluate()` | `gbpusd_trend_v3.py:1153` + `_in_session()` 1199 | UTC 07:00–20:00 (env `TREND_V3_SESSION_END_UTC=20:00`), Mon–Fri check at 1148 |
| BB Bounce (in-tree) | `evaluate()` | `gbpusd_bb_bounce.py` → `_in_window()` 1186, line 1633 | UTC 06:00–17:00 (`WIN_START=6`, `WIN_END=17`), hour-precision; plus env `BB_BOUNCE_VALID_HOURS_UTC=4,…,19` |
| V3 EMA / EMA_PULLBACK (in-tree) | Via `briefing_liquidity` and central dispatch | `briefing_liquidity.py:144` | None of its own; inherits `QM_ENTRY_HOURS` only |
| V3 BB (in-tree) | Via central dispatch | — | None of its own; inherits `QM_ENTRY_HOURS` only |
| MA Cross H1 | *(audit did not surface a live enforced site — verify)* | — | None found |
| London Liquidity Sweep | `BRIEFING_SWEEP_ENABLED` currently 0 | `.env` | `BRIEFING_SWEEP_MIN_HOUR_UTC=5` (lower bound only) |
| Central dispatch | `execute_trade` | `trade_executor.py:3801–3820` | `QM_ENTRY_HOURS` — UTC 06:00–21:00, **hour precision only**, NO weekday check |
| EMA Pullback standalone | `_run_intrabar` + `_open_setup` | `/opt/ema_pullback/ema_pullback/service.py:1005, 1599` | **None** |
| BB Bounce standalone | `open_on_confirm` | `/opt/bb_bounce/trade_runner.py:410` | **None** |

### 2.2 Existing gates ranked against the proposal (UTC equivalent of 06:45–20:30 London)

| Gate | GMT (now, until 2027-03-28) | BST (summer) | Relation to proposal |
|---|---|---|---|
| Proposed common | 06:45–20:30 UTC | 05:45–19:30 UTC | — |
| TREND_V3 | 07:00–20:00 UTC | 07:00–20:00 UTC | **Strictly tighter in winter** (loses first 15 min, last 30 min). In summer the start is tighter but the end is looser than common. |
| BB_BOUNCE window | 06:00–17:00 UTC | 06:00–17:00 UTC | Tighter end, **looser 06:00–06:45 start in winter**. |
| BB_BOUNCE valid hours | includes 4, 5, 18, 19 | includes 4, 5, 18, 19 | **Includes hours OUTSIDE proposal** (04, 05, 18–19 range tests). |
| QM central | 06:00–21:00 UTC | 06:00–21:00 UTC | **Looser on both ends** in both DST modes. |

**Interpretation.** The common policy is an UPPER BOUND. For strategies with a stricter rule (TREND_V3), the strategy rule still binds. For strategies with a looser rule (BB_BOUNCE's 04-05 UTC in `VALID_HOURS`, QM central's 06:00/21:00), the common gate TIGHTENS admission.

### 2.3 Pending-order cancellation lifecycle

- **AutoBot:** no time-of-day pending cancellation exists today (`trade_manager.py` close/amend primitives are signal-driven, not clock-driven). The reconciler at `trade_executor.py:6193` runs at startup only.
- **EMA Pullback standalone:** cancellation only via `_check_cancellations` on M5 close vs EMA21 (`service.py:1514`); no time rule. ARMED setups are local; CANCEL at cutoff is a one-line state change with no broker call.
- **BB Bounce standalone:** cancellation only via strategy state machine (C2_MISSING at `strategy.py:161`, EXPIRED at line 196). ARMED is local; no broker working order to cancel.

**Policy implication.** No existing time-driven cancellation path exists. The common gate must introduce a new seam that **drops local ARMED/pending state at cutoff** without issuing broker calls for strategies whose pending state is local-only, and routes through each strategy's existing cancellation path for strategies with broker-side working orders. Protective SL/TP orders are managed by exit paths and are **not** touched.

### 2.4 Exit, reconciliation, management (24/5)

Confirmed independent of entry-admission code in all three trees:
- AutoBot: `trade_manager.py` close/amend/trail primitives; `trade_executor.py` reconciler.
- EMA Pullback: `service.py:2005` `_advance_exit_lifecycle` + `ig_client.py:92` `close_open_position`.
- BB Bounce: `trade_runner.py:651` `check_broker_closes` (2 s poll).

**No cross-contamination risk** — the proposed gate sits strictly on the admission path. Verified at the function level.

### 2.5 DST / timezone handling

**Correctly implemented today:**
- `/opt/tradingbot/ig_time.py:21` — `ZoneInfo("Europe/London")`.
- `/opt/tradingbot/strategy_services.py:56` — same.
- `/opt/tradingbot/news_calendar.py:84–107` — correct last-Sunday BST arithmetic.
- `/opt/bb_bounce/london_clock.py` — correct `ZoneInfo` for daily report boundary.

**Broken BST heuristics (unused for the proposed gate, but worth cleaning up):**
- `/opt/tradingbot/briefing_hunt.py:69–72` — `month >= 4 or (month == 3 and day >= 29)`. Returns True on 2026-10-25 to 2026-10-31 but BST ended at 02:00 UTC on 2026-10-25.
- `/opt/tradingbot/london_open_pullback.py:69–73` — identical defect.

**Safe UTC-hour comparisons** (do not depend on DST):
- `daily_journal.py:513`, `health_digest.py:54/56`, `day_planner.py:116/118`, `historical_gap_repair.py:175/177`, `autobot.py:1895/1897`, `normal_market_state.py:1587`, `gbpusd_bb_bounce.py:2513`.

### 2.6 Spread history / evidence

- `/opt/tradingbot/reports-public/` — no spread-expansion report filed.
- `/opt/tradingbot/logs/phase2b_measurement.jsonl` — sample has `spread_pips=1.5` at normal hours; no evening sampling.
- Memory records (`project_bb_scalp_comparison_20260928`, `project_gbpusd_morning_hold_20260930`) give typical GBPUSD spread of 0.7–1.5 pips but no evening-specific data.
- Today's `bid=13367.0 ask=13381.3` at 21:40 UTC = 14.3 pips is the **only documented wide-spread datum**.

**Implication.** The proposed cutoff is justified by this single observation; it should be deployed as a conservative first measure. A **separate pre-submit spread safety check** (§9) is also justified because wide spreads can occur **inside** permitted hours (news releases, flash events). The two protect different failure modes.

---

## 3. Policy specification

**Permitted entry window.** Monday–Friday, 06:45–20:30 Europe/London (inclusive start, inclusive end — i.e. `local_time ∈ [06:45, 20:30]`; `20:30:00.000` admitted, `20:30:00.001` blocked).

**Scope.**
- Blocks: any NEW trade admission, including the moment a signal becomes a MARKET order, STOP working order, or local ARMED/pending state.
- Blocks: cancels unfilled pending/ARMED entry setups at or after the cutoff instant **via each strategy's existing cancellation lifecycle**. No new broker API calls introduced by the gate itself for local-only pending state.
- Permits: all exit/management/reconciliation/trailing/scale-out/break-even/emergency-close logic at all hours.
- Permits: SL/TP amendments. **Never** cancels protective broker orders as part of the cutoff.

**Precedence.** The common gate is an UPPER BOUND. If a strategy already has a stricter window (TREND_V3's 07:00–20:00 UTC), the strategy keeps its rule. The common gate only ever tightens.

**NEWS exemption carried from `QM_ENTRY_HOURS` today.** The current central gate exempts `NEWS_TICK`, `NEWS_STRATEGY`, `NEWS_CONT_LEG` (`trade_executor.py:3804–3807`). The proposed common gate must honour that exemption OR an operator decision explicitly scopes it in (§10).

**Timezone.** `ZoneInfo("Europe/London")`. Boundary comparison performed by converting `datetime.now(timezone.utc)` → `astimezone(ZoneInfo("Europe/London"))` → compare `.time()` against 06:45 / 20:30.

**Weekday guard.** `local_dt.weekday() < 5` (0=Monday, 4=Friday). Saturday/Sunday blocked.

**Observability.** On block, log a structured line:

```
[TRADING_HOURS_BLOCK] strategy=<family> pair=<pair> now_london=<HH:MM:SS tz> next_open=<ISO UTC> reason=BLOCK_OUTSIDE_TRADING_HOURS
```

Where `next_open` is the next 06:45 Mon–Fri in Europe/London expressed as UTC.

---

## 4. Common infrastructure

### 4.1 New module (AutoBot tree)

**Location:** `/opt/tradingbot/trading_hours.py` (new).
**Rationale:** Lives next to existing `ig_time.py` and `strategy_services.py` so all three timezone utilities colocate. Imported with a dotted path from both AutoBot (direct) and standalone services (as a vendored copy — see §4.2).

**Public API (minimal — resists ossification):**

```python
# trading_hours.py
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")

# Defaults match operator-approved window; may be overridden per-process
# via env TRADING_HOURS_START / TRADING_HOURS_END (HH:MM, London local).
DEFAULT_START = dtime(6, 45)
DEFAULT_END   = dtime(20, 30)

def is_entry_window_open(now_utc: datetime,
                         start: dtime | None = None,
                         end:   dtime | None = None) -> bool:
    """True iff `now_utc` falls inside Mon–Fri start..end Europe/London."""
    local = now_utc.astimezone(LONDON)
    if local.weekday() >= 5:
        return False
    t = local.time()
    s = start or DEFAULT_START
    e = end   or DEFAULT_END
    return s <= t <= e

def next_entry_open_utc(now_utc: datetime,
                        start: dtime | None = None,
                        end:   dtime | None = None) -> datetime:
    """Next Monday–Friday `start` o'clock Europe/London expressed in UTC."""
    ...  # BST-aware roll-forward, no naive hour arithmetic

def block_reason(now_utc: datetime) -> str:
    """Structured string for [TRADING_HOURS_BLOCK] logs."""
    ...
```

- No class — three top-level functions.
- No singleton, no cache, no process state.
- Env knobs **optional** (`TRADING_HOURS_START`, `TRADING_HOURS_END`) with the operator-approved defaults baked in so a missing env never widens the gate.
- Weekday test uses the London-local date — correct across DST and across the Friday 21:00 → Monday 06:45 wrap.

### 4.2 Vendoring policy for standalone services

Standalone services (`/opt/ema_pullback`, `/opt/bb_bounce`) do **not** import from the AutoBot tree at runtime (unit files explicitly separate paths; `ema_pullback/ig_dealing_rules.py` was deliberately duplicated for this reason). The same pattern applies here:

- The canonical copy lives at `/opt/tradingbot/trading_hours.py`.
- Each standalone ships an exact copy at `ema_pullback/trading_hours.py` and `bb_bounce/trading_hours.py`.
- Byte-identical module content is enforced by a one-line SHA256 check in the standalone's CI/test suite.

This matches the already-approved pattern (see memory `project_dynamic_ig_min_stop_patches_20261028`).

### 4.3 Env surface

Added once (in each service's `.env` for parity):

```
# Trading-hours common admission gate (Mon–Fri Europe/London)
TRADING_HOURS_ENABLED=1
TRADING_HOURS_START=06:45
TRADING_HOURS_END=20:30
# TRADING_HOURS_NEWS_EXEMPT inherits the QM_ENTRY_HOURS_EXEMPT_PREFIXES set
# in AutoBot. Standalones have no NEWS exemption semantics.
```

Fail-open kill switch: `TRADING_HOURS_ENABLED=0` restores pre-integration behaviour byte-identically. Never used in production unless the gate itself is being quarantined.

---

## 5. Per-service integration points

### 5.1 AutoBot (`/opt/tradingbot/`)

**Primary seam.** Extend the existing `QM_ENTRY_HOURS` block at `trade_executor.py:3801–3820`.

- Replace the integer-hour UTC compare with `trading_hours.is_entry_window_open(now_utc)`.
- Preserve the NEWS exemption and the fail-open behaviour (`logger.info` on block; no exception propagation).
- Preserve the `[ENTRY-HOURS] blocked` log line *in addition* to the new `[TRADING_HOURS_BLOCK]` line so legacy log tooling continues to work.
- `QM_ENTRY_HOURS_ENABLED=1` continues to be the master switch; `TRADING_HOURS_ENABLED` becomes an inner switch allowing the operator to disable the new window logic independently.
- The hour-precision `QM_ENTRY_HOUR_START/_END` env variables stay valid for operators who want to tighten further for one deployment; the common gate only ever intersects.

**Strategy-specific gates stay in place.** No code change to:
- `gbpusd_trend_v3.py:1148–1199` — keeps its 07:00–20:00 UTC + Mon–Fri rule.
- `gbpusd_bb_bounce.py:1186–1191, 1633` — keeps its 06:00–17:00 UTC window + 04–19 UTC valid-hour mask.

The central gate blocks whatever a strategy-local gate would have let through outside 06:45–20:30 London.

**Pending-cancellation at cutoff.** Routing proposal:
- The common gate blocks admission at every tick after cutoff, so no new setup can arise.
- For strategies that keep ARMED state across the cutoff instant, each strategy's existing cancellation rule still fires (M5 close vs EMA21 for pullback-family; C2 window expiry for BB Bounce). The common gate does **not** issue cancel calls directly.
- Protective SL/TP amendments and exit lifecycle run through unchanged paths.

### 5.2 EMA Pullback standalone (`/opt/ema_pullback/`)

**Primary seam.** `service.py:1005` `_run_intrabar` and `service.py:1599` `_open_setup`.

- **Both ARM paths** (intrabar touch at line 1108 `_open_setup_intrabar`, completed-M5 touch at line 508 `_open_setup`) call `trading_hours.is_entry_window_open(now_utc)` at the top. On False: `diag["events"].append({"kind":"trading_hours_block", "reason":...})` and `return` — no state change, no broker call.
- **ARMED state at cutoff.** The service's existing `_check_cancellations` continues to run. ARMED setups are local-only (no broker footprint; `service.py:1551-1561`). An ARMED setup that spans 20:30 London would be cancelled at the next completed-M5 close vs EMA21, or carried locally into Monday morning — operator decision §10.4.
- **Exit lifecycle (`_advance_exit_lifecycle` at line 2005) unchanged.**

### 5.3 BB Bounce standalone (`/opt/bb_bounce/`)

**Primary seam.** `trade_runner.py:410` `open_on_confirm` (immediately before `open_sb_now`).

- Add `if not trading_hours.is_entry_window_open(now_utc): return` with structured log.
- The strategy state machine (`strategy.py:208`) may still produce `OPEN_TRADE` events; the gate blocks them at the admission moment.
- **ARMED/validity-window states are purely local** (`strategy.py:190-198`) — no broker footprint; the usual 30-minute C2 window expiry handles cleanup.
- **Broker-close detection** (`trade_runner.py:651`) and `check_broker_closes` (2 s poll) run unchanged.

### 5.4 TREND_V3 (in-tree)

Strategy-local gate at `gbpusd_trend_v3.py:1199` is kept. Central gate adds an outer layer. No code change inside V3.

### 5.5 BB Bounce in-tree variant (`gbpusd_bb_bounce.py`)

Strategy-local gate at `_in_window` kept. Central gate adds outer layer. No code change inside BB Bounce.

### 5.6 MA Cross H1

Audit returned no execution site. Before implementation, do a focused re-scan for `MA_CROSS` to confirm whether a live admission site exists in the current main branch. If one surfaces, add to §5 integration list.

### 5.7 London Liquidity Sweep

`BRIEFING_SWEEP_ENABLED=0` today (not firing). Still include the gate in the admission path so if/when it is enabled, it inherits the common policy.

---

## 6. Impact matrix for existing enabled strategies

Assuming the common gate is enabled, in **GMT (today's regime)**:

| Strategy | Change | Observable effect |
|---|---|---|
| TREND_V3 | No change (07:00–20:00 UTC ⊂ 06:45–20:30 UTC) | None |
| BB_BOUNCE in-tree | 04:00/05:00 UTC admissions eliminated | 2 hours × ~N firings/wk removed |
| BB_BOUNCE valid-hour 18, 19 | 18-19 UTC still admitted (⊂ 20:30 UTC) | None |
| Central dispatch (QM) | 06:00–06:45 UTC and 20:30–21:00 UTC blocked | ~1.25 h/day of marginal admissions removed |
| EMA Pullback standalone | 00:00–06:45 UTC and 20:30–24:00 UTC blocked | eliminates all overnight / post-NY admissions |
| BB Bounce standalone | Same as above | Same |

In **BST (summer 2027 onwards)**, the UTC envelope becomes 05:45–19:30 UTC. The qualitative picture is unchanged — common gate ⊂ TREND_V3 continues; BB_BOUNCE early-hour tightening preserved; central / standalones tightened on both ends.

**Measurement before deploy.** For each enabled strategy, replay the last 20 trading days and count signals that would be blocked by the gate. Delivered as a per-strategy count + per-hour histogram so the operator sees exactly which admissions disappear. (This is a prerequisite to Phase 2 — see §8.)

---

## 7. Open positions and outstanding pending orders

**Open positions.** No impact. Exit lifecycle, trailing, BE, scale-out, broker-side SL/TP are all 24/5.

**Outstanding pending orders.**

| Service | At-cutoff behaviour |
|---|---|
| AutoBot STOP working orders (if any) | Not touched by common gate. Current operator policy already drains these via `trade_manager` flows. |
| EMA Pullback local ARMED | Not touched by common gate. Lives on until cancelled by M5 close vs EMA21, or filled when price moves back inside the window on Monday morning. Operator decision §10.4. |
| BB Bounce local ARMED/C2 | Not touched. 30-minute validity window at `strategy.py:190–198` already expires it. |
| Protective SL/TP on IG | Never touched. The common gate has no code path that calls `cancel_working_order` or `close_open_position`. |

**At first deployment** (not now; operator approval gated): expect zero broker-visible side effects at the cutoff instant. Within 24h, the ARMED state tables on standalones may hold overnight ARMEDs — this is already the behaviour today when the market is closed on weekends, so no new risk is introduced.

---

## 8. Deployment phases

**Phase 0 — this plan.** Operator reviews, resolves open decisions (§10), approves.

**Phase 1 — common module + impact telemetry.** Isolated branch `feat/trading-hours-common-20261030-01`.
- Add `/opt/tradingbot/trading_hours.py` + regression tests (§9).
- Wire ONLY into AutoBot's `trade_executor.py` central gate in **SHADOW** mode: log `[TRADING_HOURS_BLOCK_SHADOW]` without blocking admission.
- Run for one full UK trading week to collect:
  - count of would-block decisions by strategy family
  - per-hour histogram
  - overlap with existing `QM_ENTRY_HOURS` blocks
- No production deploy; shadow via an isolated test harness or a flagged on/off deploy, operator's choice.

**Phase 2 — AutoBot in-tree enforcement.** Isolated branch `feat/trading-hours-common-20261030-02`.
- Flip SHADOW → BLOCK in the central gate. Add in-tree strategy ownership logging.
- Deploy to AutoBot DEMO alongside existing V3 and BB Bounce in-tree admissions.
- Observe 2 trading days.

**Phase 3 — EMA Pullback standalone.** Isolated branch `fix/ema-pullback-trading-hours-20261030`.
- Vendor the module.
- Wire into `_run_intrabar` and `_open_setup`.
- Full regression suite (currently 364 passing — all must stay passing; add ~15 trading-hours tests).
- Deploy with the surgical install pattern from the IG min-stop deployment.

**Phase 4 — BB Bounce standalone.** Isolated branch `fix/bb-bounce-trading-hours-20261030`.
- Vendor module, wire into `open_on_confirm`.
- Regression suite.
- Deploy.

**Phase 5 — spread safety check (recommended, §9).** Isolated branch.
- Add a pre-submit `max_spread_pips` env + gate in each submission path (AutoBot `trade_executor`, EMA Pullback `ig_client.open_market_entry`, BB Bounce `trade_runner.open_on_confirm`).
- Default `MAX_SPREAD_PIPS=8` (per-pair in AutoBot) — conservative initial value based on today's 14.3-pip evening observation.

**Rollback.** Each phase has a one-env-flag rollback: `TRADING_HOURS_ENABLED=0` restores pre-integration behaviour. No file movement required.

---

## 9. Regression test matrix

### 9.1 `trading_hours.py` unit tests (per-copy)

- Admit at 06:45:00 London on Monday.
- Admit at 20:30:00 London on Friday.
- Block at 06:44:59.999 on Monday.
- Block at 20:30:00.001 on Friday.
- Block all day Saturday.
- Block all day Sunday.
- Admit 07:00 UTC on 2027-03-27 (last BST-starting Sunday eve, London 07:00 BST not yet).
- Admit 07:45 UTC on 2027-03-28 06:45 (first full BST morning; UTC 05:45 = London 06:45).
- Block 05:44 UTC on 2027-03-28 (two-second edge pre-BST-opening).
- Admit 06:45 UTC on 2026-10-25 (BST-end Sunday, but market closed → actually blocked because Sunday). Verify Sunday block beats BST-roll check.
- Admit 06:45 UTC on 2026-10-26 (first full post-BST Monday).

### 9.2 US DST independence

- Admit 07:00 UTC on 2026-11-01 (US DST ends; UK still GMT) — no change to London window.
- Admit 07:00 UTC on 2027-03-08 (US DST starts; UK still GMT) — no change.

### 9.3 Each service's integration tests

- Replay a signal at 20:29 London — admitted. Same signal at 20:31 — blocked, logged, no state change.
- Verify exits still run outside the window: feed a tick at 21:00 London while a position is open → BE/trail logic executes as usual.
- Verify ARMED state at cutoff: service.py path must NOT emit `_open_setup` after cutoff, must NOT cancel broker orders.
- Fail-open: raise an exception inside `trading_hours` and verify the submission proceeds (per `QM_ENTRY_HOURS` existing fail-open contract).

### 9.4 Impact telemetry replay

- Last 20 trading days per enabled strategy → count admissions blocked by common gate.
- Delivered as a markdown table in the Phase 1 commit.

---

## 10. Open operator decisions

| # | Decision |
|---|---|
| 10.1 | **NEWS exemption.** Should the common gate honour `QM_ENTRY_HOURS` NEWS exemption (NEWS_TICK, NEWS_STRATEGY, NEWS_CONT_LEG)? Current proposal: yes, inherit for parity. |
| 10.2 | **BB_BOUNCE valid hours 04, 05 UTC.** The common gate blocks these. Confirm BB_BOUNCE loses 04–05 UTC admissions (currently in `BB_BOUNCE_VALID_HOURS_UTC=4,5,…`). |
| 10.3 | **BB_BOUNCE window end 17:00 UTC.** Keep the stricter 17:00 UTC in-tree limit, or widen in-tree to 20:30 London so the common gate alone governs? Current proposal: keep BB_BOUNCE's 17:00 UTC. |
| 10.4 | **Overnight ARMED state (EMA Pullback standalone, BB Bounce standalone).** Should the ARMED state live across the 20:30 London cutoff into Monday morning (current behaviour: yes, carried in local ledger), or should the service drop ARMED state at cutoff? Current proposal: carry (no change). |
| 10.5 | **Spread safety check (§9).** Deploy alongside the trading-hours policy, or deliver separately? Current proposal: deploy as a sibling of Phase 5 with its own branch. |
| 10.6 | **DST heuristic cleanup.** `briefing_hunt.py` and `london_open_pullback.py` have the broken `_is_bst()` heuristic. Replace with calls to `ZoneInfo` as part of this initiative, or carve into a separate corrective branch? Current proposal: separate corrective branch — orthogonal to the common gate. |
| 10.7 | **Phase 1 shadow mode delivery.** Agree the Phase 1 branch delivers shadow telemetry only, with a defined review window (one UK trading week), before Phase 2 enforcement? |

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| New gate silently widens an existing stricter rule | Policy §3 "intersect, never widen"; §5 preserves each strategy's local rule verbatim. |
| DST transition drops an admission mid-day | `ZoneInfo` conversion, no naive hour math (§4.1, §9.2). |
| Protective SL/TP accidentally cancelled | Gate code has no path to `cancel_working_order` or `close_open_position` (§3, §7); unit test added to assert this. |
| Standalone and AutoBot copies drift | Byte-identical check in each standalone's CI; sha256 pinned in commit messages. |
| Fail-closed on gate exception blocks all trading | Current `QM_ENTRY_HOURS` is fail-open; the common gate inherits that contract (§5.1, §9.3). |
| Operator rolls back mid-day | Single env flag `TRADING_HOURS_ENABLED=0` restores pre-integration behaviour byte-identically. |

---

## 12. Pre-submit spread safety check — recommended

**Rationale.** Today's 14.3-pip spread at 21:40 UTC was observed within the current `QM_ENTRY_HOUR_END=21` window. A time cutoff alone does not protect against wide spreads **inside** permitted hours (news releases, flash events, holiday thinness). The two gates protect different failure modes:

- **Time cutoff:** avoids known-bad hours.
- **Spread safety check:** avoids anomalous spreads at any hour.

**Minimal design.** A single pre-submit check per service, placed immediately before each MARKET order submission (`trade_executor.py` central submit; `ig_client.open_market_entry` in EMA Pullback; `trade_runner.open_on_confirm` + `open_sb_now` in BB Bounce):

```python
spread_pips = (ask - bid) / pip_size
if spread_pips > cfg.max_spread_pips:
    log(f"[SPREAD_SAFETY_BLOCK] spread={spread_pips:.1f}p > cap={cfg.max_spread_pips:.1f}p")
    return REJECTED(...)
```

**Default cap.** `MAX_SPREAD_PIPS=8` for GBPUSD. Based on today's 14.3-pip observation, a cap at 8 would have blocked the trade with margin, while 1.5-pip normal spreads sit well below the cap. Per-pair override via env or cfg.

**No further gating.** Deliberately: no `avg_spread` tracking, no rolling cap, no "widening tolerance" logic. Flat threshold, structured log, fail-open on cfg error.

Delivered as a sibling to Phase 5; approvable independently of the time cutoff.

---

## 13. Deliverables when operator approves

1. Phase 1 branch: `/opt/tradingbot` + `trading_hours.py` + central-gate shadow wire + replay histogram report.
2. Phase 2 branch: central-gate enforcement.
3. Phase 3 branch: EMA Pullback integration + regression suite update.
4. Phase 4 branch: BB Bounce standalone integration + regression suite update.
5. Phase 5 branch: pre-submit spread check across all three services.
6. (Optional / orthogonal) `briefing_hunt.py` + `london_open_pullback.py` `_is_bst()` corrective branch.

Each branch delivered on its own worktree. **No production restarts** until all branches are reviewed and the operator issues a sequenced deployment approval.

---

## Appendix A — file:line references (quick index)

- `trade_executor.py:3801–3820` — central `QM_ENTRY_HOURS` block (replace / extend here).
- `gbpusd_trend_v3.py:153–155, 1148, 1199` — TREND_V3 session gate (unchanged).
- `gbpusd_bb_bounce.py:109–110, 1186–1191, 1633` — BB Bounce in-tree window (unchanged).
- `ig_time.py:19–66` — tz infrastructure template.
- `strategy_services.py:42–90` — tz infrastructure template.
- `briefing_hunt.py:69–72`, `london_open_pullback.py:69–73` — broken BST heuristic (orthogonal cleanup).
- `/opt/ema_pullback/ema_pullback/service.py:1005, 1599` — standalone EMA Pullback entry seams.
- `/opt/bb_bounce/trade_runner.py:410, 651` — standalone BB Bounce entry seams.
- `/opt/bb_bounce/london_clock.py:17, 46–60` — tz-safe pattern already in-tree.

## Appendix B — not yet verified (needs confirmation before Phase 1)

- **MA Cross H1 execution site.** The audit did not surface a live file:line. Before Phase 1, grep for `MA_CROSS_H1_ENABLED` in current main and confirm whether an active admission site exists; if yes, add to §5. If no, note explicitly in Phase 1 branch message.
- **In-tree EMA_PULLBACK admission precedence.** The in-tree EMA Pullback admission site goes via `briefing_liquidity.py:144`; confirm the central dispatch exactly serialises it through `trade_executor.execute_trade` (and therefore through the central gate at line 3801).
