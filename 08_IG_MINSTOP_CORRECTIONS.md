# IG Minimum-Stop Corrections — Implementation Report

**Date:** 2026-10-29 pm
**Scope:** Corrections A, B, C, D, E from the cross-strategy audit + mandatory rapid-stop investigation.
**Deployment status:** **NOT deployed.** All corrections prepared in isolated worktree branches for operator review.
**Services untouched:** Not restarted. Live production state preserved.

## 1. Corrections overview

| # | Correction | Status | Branch / artefact | Tests |
|---|---|---|---|---|
| A | EMA Pullback IG-min integration (BLOCK, 12p preserved) | ✅ Committed | `fix/ig-min-stop-integration-20261029` @ `480a638` in `JohnCarrington/ema_pullback` | 11 new (full suite 359/359 pass) |
| B | AutoBot — retain existing BLOCK semantics; no changes | ✅ No change needed | n/a | n/a |
| C | London Liquidity Sweep IG-min integration | ✅ Committed | `fix/ig-min-stop-integration-20261029` in `JohnCarrington/london-liquidity-sweep` (worktree only; not pushed) | 6 new |
| C | MA Cross H1 IG-min integration | ✅ Committed | `fix/ig-min-stop-integration-20261029` in MA Cross H1 repo (worktree only; not pushed) | 6 new |
| D | Dead-code cleanup `MIN_STOP_DISTANCE_PIPS` / `_IG_MIN_STOP_PTS` | ✅ No-op — dependency analysis proved them NOT dead | Documented below | n/a |
| E | EMA Pullback 12p stop | ✅ Retained unchanged | n/a | n/a |

## 2. Correction D — dependency analysis (DO NOT REMOVE)

Operator required: "Remove obsolete 12-pip broker minimum constants only after dependency analysis proves they are unused."

Analysis via `grep -rn --include=*.py` across the live tree:

| Constant | Live-tree readers | Verdict |
|---|---|---|
| `MIN_STOP_DISTANCE_PIPS` | `gbpusd_bb_bounce.py:3426` imports it as `_RRT_MIN_STOP_FLOOR` for the RANGE_ROTATION opposite-band TP calculation (gated by `BB_BOUNCE_RANGE_OPPOSITE_BAND_TP_ENABLED`). `trade_executor.py:4435` reference is in a comment only. | **ACTIVELY CONSUMED** — do not remove |
| `_IG_MIN_STOP_PTS` | `gbpusd_bb_bounce.py:3425` imports it as `_RRT_IG_MIN_PTS` for the same TP calc; `tiered_ratchet.py:300` imports it as `_MIN` in `_ig_min_stop_pips_for_pair()` helper used by the tiered-ratchet stop management. | **ACTIVELY CONSUMED** — do not remove |

The 2026-10-28 WS4 patch removed Steps 2/3/4 auto-widening in `trade_executor.execute_trade`. The constants themselves remained because they are the authoritative GBPUSD IG-min reference for OTHER code paths (RANGE_ROTATION TP + tiered-ratchet broker-min helper). The audit agent's "vestigial" classification was incorrect; this follow-up analysis supersedes it.

**No commit for Correction D.** The constants stay as-is.

## 3. Rapid stop-out investigation — summary

Full forensic report in agent findings (reproduced below in §5). All three EMA Pullback BUYs on 2026-10-29 (deals `DIAAAAYR2YZ6RB3`, `DIAAAAYR3ETVCAY`, `DIAAAAYR3TPT4BU`) were **classification A — legitimate SL hits**, no execution/data defects. Common root-cause pattern identified but **not actioned per operator instruction** ("do not change EMA Pullback entry logic, stop distance or exit strategy based on speculation").

### Headline

- **12-pip SL did its job** at the exact stop level in all three trades. No slippage past the stop visible.
- **Spread was normal 0.9p** at every polled sample before and after every fill.
- **H1 qualification was clean every time** (ema8_slope, 8-13 sep, 13-20 sep all passed).
- **Entry fills landed at the top of short-lived M5 wicks.** The frozen entry level `max(highs of last 5 M5 bars) + 3 pip buffer` systematically fires when a new local extreme is set, which on 2026-10-29 coincided with intraday reversal tops.
- **Tick-level MAE cannot be verified** — the autobot tick cache ends 2026-04-10 and no sub-M5 tick ladder exists for 2026-10-29. The three stops filled at the exact stop level per the setups ledger; whether broker executed with any slippage past the stop is not visible in retained artefacts.
- **No action proposed.** Operator approved keeping the 12-pip Method B §3 backstop.

## 4. Correction A — EMA Pullback details

**Branch:** `fix/ig-min-stop-integration-20261029` in `/home/autobot/ema_pullback-wt/ig-min-stop-20261029` (worktree of `JohnCarrington/ema_pullback`)
**Commit:** `480a638`
**Base:** `fix/intrabar-wiring-20261028` @ `1f8b508` — the branch whose `ig_client.py` and `config.py` are byte-identical to the live `/opt/ema_pullback` tree

### Files

| File | Change |
|---|---|
| `ema_pullback/ig_dealing_rules.py` | NEW. Shared observer module. Byte-identical to `/opt/bb_bounce/ig_dealing_rules.py` except (a) default sentinel path → `/opt/ema_pullback/cache/ig_dealing_rules.invalidate`; (b) added `set_session_provider(fn)` so standalone EMA Pullback can register its existing `IGService` without needing an `ig_auth` module. |
| `ema_pullback/ig_client.py` | `open_market_entry()` gains PRE-SUBMIT guard + POST-REJECTION record. BLOCK semantics on `ig_dealing_rules.is_known_too_tight`. On `ATTACHED_ORDER_LEVEL_ERROR` reason, calls `record_rejection(epic, pair)`. Pip/point conversion is explicit: `stop_distance_pips = stop_distance / cfg.pip_size` (defensive against bad `pip_size`). |
| `tests/test_ig_min_stop_integration.py` | NEW. 11 regression cases covering permissible-no-observation, observation=12 (equal → proceeds), observation=15/20/25 (BLOCK), BLOCK-never-widens canary, dealing-rules exception → fail-safe, `ATTACHED_ORDER_LEVEL_ERROR` → record + subsequent block, non-matching rejection → observation unchanged, pip/point conversion with `pip_size=1.0`, `pip_size=0.0001`, defensive `pip_size=0`. |

Full test suite: **359 passed** (11 new + 348 pre-existing).

### Preservation guarantees

- `BROKER_SL_PIPS=12` unchanged (per operator E ruling).
- `BROKER_TP_PIPS=100` unchanged.
- Method B software exit path, entry mechanic, trigger logic, H1 qualification, intrabar touch detection — **all untouched**.
- `/opt/ema_pullback/.env` — no change.
- Fail-safe pass-through if the module import/call raises (same contract as AutoBot `trade_executor.py:4412-4418`).

### Deployment requirements

1. **The live `/opt/ema_pullback` is NOT a git worktree** — operator must manually sync files from this branch:
   ```
   cp /home/autobot/ema_pullback-wt/ig-min-stop-20261029/ema_pullback/ig_dealing_rules.py \
      /opt/ema_pullback/ema_pullback/ig_dealing_rules.py
   cp /home/autobot/ema_pullback-wt/ig-min-stop-20261029/ema_pullback/ig_client.py \
      /opt/ema_pullback/ema_pullback/ig_client.py
   ```
2. Create cache dir if missing: `mkdir -p /opt/ema_pullback/cache` (owner `autobot:autobot`).
3. Optionally wire `ig_dealing_rules.set_session_provider(...)` call in the service's startup. **Not strictly needed** — the module's fallback path imports `ig_auth`; if `ig_auth` is absent (which it is in /opt/ema_pullback), `_fetch_once` returns a `IG_AUTH_IMPORT:ModuleNotFoundError` and `record_rejection` logs it as a fetch-failure. This means **ATTACHED_ORDER_LEVEL_ERROR observations will not be recorded until the session provider is registered** — the PRE-SUBMIT guard still works (it just has no observations to consult). To fully enable: in `/opt/ema_pullback/ema_pullback/service.py` after the first IG session is established, add:
   ```python
   from ema_pullback import ig_dealing_rules as _dr
   _dr.set_session_provider(lambda: self._ig.ig_service)  # or equivalent
   ```
4. `sudo systemctl restart ema-pullback.service`
5. Verify PID bump + process env + first entry attempt.

### Rollback

Delete the two new files from `/opt/ema_pullback/ema_pullback/` and restart. Or `git revert 480a638` in the worktree then re-sync.

## 5. Correction C — LLS + MA Cross H1 details

**LLS branch:** `fix/ig-min-stop-integration-20261029` in `/home/autobot/tradingbot-wt/lls-ig-min-stop-20261029` (worktree of `JohnCarrington/london-liquidity-sweep`); 1 commit.
**MA Cross branch:** `fix/ig-min-stop-integration-20261029` in `/home/autobot/tradingbot-wt/ma-cross-ig-min-stop-20261029` (worktree of MA Cross H1 repo); 1 commit.

Both follow the same pattern:
- `ig_dealing_rules.py` — new file, byte-identical to the shared module except per-service sentinel path
- `ig_execution.py` — pre-submit guard + post-rejection record on `ATTACHED_ORDER_LEVEL_ERROR`
- `tests/test_ig_min_stop_integration.py` — 6 regression cases each (permissible, block, no-widen canary, fail-safe, record-then-block, non-matching rejection)

LLS is a true git worktree of `/opt/london_liquidity_sweep` so an operator-sync would be a direct `git checkout` or file-copy. MA Cross H1's live tree has significant uncommitted drift (277-line diff in `ig_execution.py`, plus 5 other files + 3 new untracked files); the correction branch intentionally mirrors those live files (preserving production state per operator instruction) so my IG-min layering is on top of actual production, not master's stale code.

### Preservation guarantees

| Property | LLS | MA Cross H1 |
|---|---|---|
| Configured SL | 12p (`config.SL_PIPS=12.0`) unchanged | 30p (`MA_STOP_PIPS=30.0`) unchanged |
| EXECUTION flag | `LLS_EXECUTION_ENABLED=1` unchanged | `MA_EXECUTION_ENABLED=1` unchanged |
| Strategy rules | untouched | untouched |
| `.env` | unchanged | unchanged |

### Deployment requirements

For each service:
1. Review the branch diff.
2. Sync files to live tree (LLS: `git checkout fix/ig-min-stop-integration-20261029 -- ig_dealing_rules.py ig_execution.py tests/test_ig_min_stop_integration.py`; MA Cross: file-copy or sync).
3. Create cache dir for each: `mkdir -p /opt/london_liquidity_sweep/state /opt/ma_cross_h1/state` (owner `autobot:autobot`).
4. `sudo systemctl restart london-liquidity-sweep.service` / `ma-cross-h1.service`.
5. Verify.

Neither service is currently firing (0 fires in last 48h), so there is no live-position impact.

### Rollback

Revert the single commit or delete the new files + restart.

## 6. Operator-authored decisions required for deployment

| # | Decision | My recommendation |
|---|---|---|
| 1 | Deploy Correction A (EMA Pullback)? | YES — the 3 fast-SL trades today suggest IG stops are being hit at or near the 12p boundary; defensive IG-min guard is valuable. |
| 2 | Add `set_session_provider` wiring to EMA Pullback's `service.py` startup? | YES — otherwise the POST-REJECTION observation path only works after the first manual sync. Optional for pre-submit guard. |
| 3 | Deploy Correction C LLS? | YES but low-urgency (0 fires in 48h). |
| 4 | Deploy Correction C MA Cross H1? | YES but lowest-urgency (30p SL unlikely to trip IG min). |
| 5 | Act on rapid-stop entry-mechanic finding? | **NOT at this stage** per operator instruction. The forensic report documents the pattern for future review; no code change proposed. |

## 7. Full rapid-stop forensic (from the investigation agent)

### Trade 1 — `DIAAAAYR2YZ6RB3` (setup `7A5CFB`)
- Fill: 13380.0 (ask) at 15:53:27.247 UTC; broker SL 13368.0 (12p); broker TP 13480.0 (100p)
- Close: 15:53:49.124 UTC at 13368.0 — SL hit ~21.9s after fill
- Realised slippage vs frozen entry level (13378.65): +1.35p (within 2p budget)
- Spread at fill (±10s): 0.9p
- M5 15:50 bar OHLC: O=13366.95 H=13379.85 L=13366.95 C=13374.65 — fill at top of 13-pip wick
- H1 qualification: ema8_slope 3.15 p/hr, 8-13 sep 3.85p, 13-20 sep 3.26p, admission_allowed=True

### Trade 2 — `DIAAAAYR3ETVCAY` (setup `07C0E9`)
- Fill: 13375.0 (ask) at 17:11:25.077 UTC; broker SL 13363.0 (12p); broker TP 13475.0 (100p)
- Close: 17:11:46.513 UTC at 13363.0 — SL hit ~21.4s after fill
- Realised slippage: +0.65p
- Spread at fill: 0.9p
- M5 17:10 bar OHLC: O=13372.35 H=13374.95 L=13369.75 C=13369.75 — fill at bar high; closed 5p below fill
- H1 qualification: ema8_slope 6.59 p/hr, 8-13 sep 7.00p, 13-20 sep 5.36p, admission_allowed=True

### Trade 3 — `DIAAAAYR3TPT4BU` (setup `89EC3C`)
- Fill: 13376.3 (ask) at 20:07:00.666 UTC; broker SL 13364.3 (12p); broker TP 13476.3 (100p)
- Close: 20:07:20.694 UTC at 13364.3 — SL hit ~21.0s after fill
- Realised slippage: +0.95p
- Spread at fill: 0.9p
- M5 20:05 bar OHLC: O=13370.45 H=13377.35 L=13370.45 C=13376.65 — fill at bar high; next 60s bid retraced to 13373.3
- H1 qualification: ema8_slope 3.47 p/hr, 8-13 sep 8.37p, 13-20 sep 7.98p, admission_allowed=True
- H1 close-trend 16:00→19:00: 13371.95 → 13368.45 → 13366.95 → 13362.95 (fading intraday)

### Common factors

1. **Entry mechanic systematically buys wicks**: `entry_level = max(highs of 5 preceding M5 bars) + 3p` + mid-cross trigger fires at or near the top of the first intraday push that revisits the recent swing high — by construction a hit requires a NEW local extreme.
2. **All three fills were at bar-high extremes** that failed to hold within the same or next M5 bar.
3. **H1 qualification was clean every time**; strategy obeyed its own rules. H4 was `direction=NEUTRAL` for all three; H1 close-trend was weakening on close-to-close through the afternoon.
4. **Spread normal (0.9p)**, slippage within budget (0.65–1.35p vs 2p budget), no feed/data defect visible.
5. **12p SL hit cleanly** at the exact stop level in all three.
6. **No tick-level MAE verification possible** — tick cache ends 2026-04-10; sub-M5 tick ladder for 2026-10-29 does not exist in retained artefacts.

**Primary root-cause finding (information-only, no action):** the strategy was buying new-high wicks on a session where H1 was slope-qualified but close-weakening and H4 was neutral — i.e. the "fresh high" trigger coincided with local reversal tops of counter-moves inside a chop/fade regime. The 12p SL did its job as a backstop; the fast stop-outs are the honest signal that the entries were timed to the wick. Classification A (legitimate) with a design-caused poor-entry overlay.

## 8. Standing-rule compliance

- ✅ No live services restarted
- ✅ No deployment to `/opt/*` live trees
- ✅ No existing positions altered (0 open at verification time 20:30 UTC)
- ✅ No test broker orders submitted
- ✅ All corrections prepared in isolated worktree branches
- ✅ Live production files preserved (WS4 dirty state untouched; MA Cross's 277-line drift preserved)
- ✅ No `git stash` / `reset` / `checkout --` / destructive operations
- ✅ AutoBot V3 BB untouched

Awaiting operator review before any deployment step.
