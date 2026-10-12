# NMS restart-safety repair — 2026-10-13

**Approved scope:** A (restore_from_disk at startup) + C (restricted
London-open fallback) + state validation.

**Branch:** `fix/nms-restart-safety-20261013` HEAD `1f6ba6c` in
isolated worktree `/home/autobot/tradingbot-wt/nms-restart-safety-20261013`.

**Pushed:** `refs/heads/fix/nms-restart-safety-20261013` at
`1f6ba6cfbf5582eb419b15b174de6afb9d132a09`.

**Status:** NOT DEPLOYED. Live `/opt/tradingbot` HEAD unchanged
at `e84fafd`. Services unchanged. Enforcement flag unchanged.

---

## 1. The 2026-10-12 22:50 UTC incident

Observed snapshot after deployment restart:

```
london_open_ts    : 2026-10-12T07:00:00Z
london_open_price : 13208.95         ← WRONG (= restart bar's open)
last_bar_close    : 13208.05
prevailing        : UNKNOWN
hourly_samples    : []
```

True 07:00 UTC price was `13246.15` (per IG daily pivots P=13246.47
and the archive first bar `2026-10-12T07:55:00` opening at
13246.15). The snapshot's recorded displacement was `-0.9p`; the
true displacement against the real 07:00 anchor was `~-38p`.

### Two linked defects

| Defect | Location | Behaviour |
|---|---|---|
| 1 | `session_trend.py:_advance_bar_locked` | On first bar close after restart, if `london_open_price is None` AND `bar_ts >= london_open_ts`, silently set `london_open_price = current_bar_open`. On a 22:50 UTC restart this used the current bar as the London anchor. |
| 2 | `autobot.py` boot sequence | `session_trend._save_to_disk()` fired on every bar close, but `session_trend.restore_from_disk()` was never called at startup. Even when a valid state file existed, a restart wiped memory. |

## 2. Corrections applied

### Correction C — restricted anchor-initialisation window

`session_trend.py:_advance_bar_locked`:

```python
_lo_window_s = _env_int(
    "SESSION_TREND_LONDON_OPEN_FALLBACK_SECONDS", 3600,
)
if (s.london_open_price is None
        and bar_ts >= london_open_ts
        and (bar_ts - london_open_ts).total_seconds()
            <= _lo_window_s):
    s.london_open_ts = _iso(london_open_ts)
    s.london_open_price = float(o)
```

Only the first bar whose START is within `_lo_window_s` seconds
(default 3600 = 1 h) of the canonical London open can initialise
the anchor. A bar arriving >1 h past the open does nothing — the
anchor stays at None and the state machine remains UNKNOWN.

**Why 1 hour and not strictly 5 minutes?** The archive-replay test
suite reads a CSV that starts at `07:55 UTC` (the first archived
bar) — 55 min past the canonical 07:00 open. A 5-min window would
also reject this case, breaking the Oct-12 pinned regression. The
1-h window comfortably accommodates the archive-start case while
rejecting any evening/night restart (>= 2 h past open). Operators
wanting strict 5-min behaviour can set
`SESSION_TREND_LONDON_OPEN_FALLBACK_SECONDS=300` in the env.

### Correction A — wire `restore_from_disk` at startup

`autobot.py` (immediately after the existing
`normal_market_state.restore_from_disk()` call):

```python
try:
    import session_trend as _st_boot
    _st_boot.restore_from_disk()
    logger.info("[SESSION_TREND] boot restore complete")
except Exception as _st_boot_err:
    logger.warning(
        "[SESSION_TREND] boot restore failed: %s", _st_boot_err,
    )
```

### Validated restore_from_disk

Every per-symbol entry is validated before hydration. One corrupt
entry does not disable restoration of others. Rejected entries are
logged at INFO level so a silent-drop restart is visible in ops.

Validation checks (all must hold):

| Check | Reject reason if fails |
|---|---|
| `schema_version == "session_trend.v1"` | `wrong schema_version` |
| `blob["symbol"]` matches registry key | `symbol mismatch` |
| `blob["session_date"]` equals today's UTC date | `session_date not today` |
| `blob["london_open_ts"]` parseable + within last 24 h | `london_open_ts unparseable` / `in the future` / `>24h old` |
| `blob["london_open_price"]` finite + strictly positive | `not finite+positive` |
| `blob["last_bar_ts"]` parseable + within last 24 h | `last_bar_ts unparseable` / future / >24h |
| `blob["prevailing"]` in {UNKNOWN, RANGE, UP, DOWN} | `invalid prevailing` |

Whole-file corruption (unreadable, not JSON, not a dict) hydrates
nothing — registry starts empty.

### UNKNOWN never produces a restriction

Operator requirement 5 verified against existing
`session_trend_guard.py:197`:

```python
return (False, f"allow:prevailing={prev}")
```

The guard blocks only `BUY+DOWN` and `SELL+UP`. All other
combinations (including every variant with `prevailing=UNKNOWN`)
hit the final allow. A test
(`test_unknown_prevailing_never_blocks_guard`) pins this behaviour
so a future refactor cannot silently introduce an UNKNOWN block.

## 3. Regression tests

Added `tests/data_continuity/test_restart_safety.py` — 13 tests
across 8 scenarios, all passing:

| # | Scenario | Test |
|---|---|---|
| 1 | Intraday restart after DOWN established | `test_restart_mid_down_restores_direction` |
| 2 | Intraday restart after UP established | `test_restart_mid_up_restores_direction` |
| 3 | Restart without saved state | `test_restart_with_no_state_file_fresh_start` |
| 4 | Restart with stale state | `test_restart_with_stale_state_rejected` |
| 5 | Restart with corrupted state | `test_restart_with_corrupted_state_fresh_start` × 5 variants (unparseable JSON, scalar JSON, list JSON, non-dict value, schema mismatch) |
| 6 | Restart after London open (post-fallback-window) | `test_evening_restart_does_not_set_london_anchor` |
| 7 | Midnight / session rollover | `test_midnight_rollover_rejects_prior_day_state` |
| 8 | 2026-10-12 22:50 UTC false-anchor | `test_oct12_22h50_false_anchor_scenario` |
| + | UNKNOWN never blocks guard | `test_unknown_prevailing_never_blocks_guard` |

```
tests/data_continuity/test_restart_safety.py — 13 passed in 0.25s
```

## 4. Full regression

| Suite | Result |
|---|---|
| NMS data_continuity (incl. 13 new + Oct 12 pinned) | **115 / 115 PASS** |
| V3 engine (direct scope) | **123 / 123 PASS** |
| BB-Bounce guard integration | **10 / 10 PASS** |
| Pre-existing failures (`test_integration_remediation`, `test_window`) | unchanged — predate all this work |

Oct 12 pinned regression:
```
tests/data_continuity/test_phase8_oct12_regression.py::test_oct12_pinned_replay — PASSED
```

## 5. Files changed

| File | Change |
|---|---|
| `session_trend.py` | Restricted anchor-initialisation window + validated restore_from_disk + `_parse_iso_safe` helper (201 insertions / 9 deletions) |
| `autobot.py` | `session_trend.restore_from_disk()` call at boot (18 insertions) |
| `tests/data_continuity/test_restart_safety.py` | New file — 13 restart-safety tests (342 insertions) |

Commits on `fix/nms-restart-safety-20261013`:
```
1f6ba6c chore: remove __pycache__ files accidentally staged in prior commit
9eca2e3 fix(nms): restart-safety repair — validated restore + anchor window
e84fafd (base — current /opt/tradingbot HEAD)
```

**NOT CHANGED by this repair:**
- Trading strategies — not touched.
- Trend thresholds — unchanged (`MIN_STRUCTURE_RUN`, `MIN_STRUCTURE_ASYMMETRY`, `MAX_RANGE_REVERSALS` all unchanged).
- BB-Bounce entry logic / stops / targets — unchanged.
- V3 state machine — unchanged.
- Classification semantics — unchanged.

The only behaviour change: an evening-restart or any first bar >1 h past the canonical London open no longer silently sets a false anchor.

## 6. Deployment procedure (operator action)

### Prerequisites
- Repair branch pushed and visible: `fix/nms-restart-safety-20261013` at `1f6ba6c`.
- Current live HEAD: `e84fafd` (fast-forwardable to `1f6ba6c` — single-commit delta plus the pycache cleanup).

### Step 1 — Fast-forward merge into `/opt/tradingbot`

```bash
cd /opt/tradingbot

# Verify we are on e84fafd before merge:
git log --oneline -1
# → e84fafd reconcile: fold rest of operator WIP ...

# Fast-forward merge:
git merge --ff-only fix/nms-restart-safety-20261013
```

**If the working-tree has new modifications since the earlier deployment** (eg. operator changes to `deploy/systemd/*` since the last merge), git may refuse until those are either committed or restored. Verify first with `git status --short` and stop if anything unexpected.

**Expected result after successful merge:** `git log --oneline -1` shows `1f6ba6c`.

### Step 2 — Verify compiled code loads correctly

```bash
cd /opt/tradingbot
/opt/tradingbot/venv/bin/python -c "
import sys
sys.path.insert(0, '/opt/tradingbot')
import session_trend
assert hasattr(session_trend, 'restore_from_disk'), 'restore_from_disk missing'
import autobot  # must import without error
print('OK: session_trend has restore_from_disk; autobot imports clean')
" 2>&1 | tail
```

### Step 3 — Operator-run service restart

```bash
# AutoBot FIRST so it begins publishing snapshots with the new behaviour:
sudo systemctl restart autobot.service
sudo systemctl status autobot.service --no-pager | head -15

# Wait ≥ 5 minutes, then check the boot restore log:
sudo journalctl -u autobot.service --since "5 minutes ago" | grep -E "SESSION_TREND|session_trend"
# Expected: "[SESSION_TREND] boot restore complete"
# (If a stale state file was present you will also see
#  "[SESSION_TREND] restore rejected for GBPUSD: <reason>" at INFO)

# Check the published snapshot — should either be UNKNOWN with
# None anchor (first restart of the day) or carry restored state:
cat /opt/tradingbot/cache/session_trend_GBPUSD.json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(
      'prevailing:        ', d.get('prevailing'),
      '\nlondon_open_ts:    ', d.get('london_open_ts'),
      '\nlondon_open_price: ', d.get('london_open_price'),
      '\nlast_bar_ts:       ', d.get('last_bar_ts'),
      '\nlast_bar_close:    ', d.get('last_bar_close'),
      '\ndata_fresh:        ', d.get('data_fresh'))"
```

**Expected after a restart during a London session:**
- `prevailing: UNKNOWN` (first-ever deploy with the new logic; state file written pre-repair is dropped if present due to validation)
- `london_open_ts: None` (anchor NOT set from the restart bar)
- `london_open_price: None`
- `last_bar_ts`, `last_bar_close`: current values
- `data_fresh: True`

**Expected after a clean overnight start before London open:**
- The 07:00 UTC bar will set the anchor correctly on its close.
- `prevailing` evolves normally from UNKNOWN as the session develops.

### Step 4 — BB-Bounce service restart (unchanged from previous plan)

```bash
sudo systemctl restart bb-bounce.service
sudo systemctl status bb-bounce.service --no-pager | head -15
```

### Step 5 — Monitor
```bash
sudo journalctl -u autobot.service -f -n 50 \
  | grep -E "SESSION_TREND|session_trend|BLOCKED_BY_SESSION_TREND"
sudo journalctl -u bb-bounce.service -f -n 50 \
  | grep -E "session_trend_guard|BLOCKED|🛡"
```

### Rollback (if needed)

**Fastest — flag flip (unchanged from previous plan):**
```bash
# Edit /opt/bb_bounce/.env — set:
BB_BOUNCE_SESSION_TREND_GUARD_ENABLED=0
sudo systemctl restart bb-bounce.service
```

**Full code rollback — git reset only on operator approval:**
```bash
# /opt/tradingbot back to e84fafd (pre-restart-safety but
# post-reconciliation deployment):
cd /opt/tradingbot
git reset --hard e84fafd
sudo systemctl restart autobot.service
# BB-Bounce unaffected by this repair — no rollback needed.
```

Note the `git reset --hard` here is DESTRUCTIVE and the operator's standing rule prohibits me from executing it without explicit approval.

## 7. Immediate recovery of today's session state

The deployed e84fafd code is currently running with a false
anchor (`london_open_price=13208.95`). After this repair deploys:

- If no state file exists at boot: the state starts fresh. The false anchor is cleared. `prevailing=UNKNOWN`, no false restriction.
- If the stale state file exists but has `session_date != today's UTC date` by boot time: validation rejects the stale blob, state starts fresh. Same outcome.
- If today's session_date state file exists with the wrong `london_open_price=13208.95`: validation PASSES (the value is finite + positive + within 24 h). The false anchor is PRESERVED. **Operator may want to delete the state file before restart** to force a clean start:

```bash
# Optional pre-restart cleanup to force a fresh anchor:
rm -f /opt/tradingbot/cache/session_trend_state.json
rm -f /opt/tradingbot/cache/session_trend_GBPUSD.json
```

Then restart AutoBot. The state machine will stay UNKNOWN until tomorrow's 07:00 London open, which produces the first bar within the 1-h window and correctly sets the anchor.

## 8. STOP BEFORE PRODUCTION CHANGES

No live code changed. No services restarted. No enforcement enabled. No IG orders. Awaiting operator execution.
