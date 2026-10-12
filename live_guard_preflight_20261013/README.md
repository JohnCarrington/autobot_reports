# Live guard deployment preflight — 2026-10-13

**AutoBot baseline target:** `6bc768e` (branch
`feat/nms-data-continuity-stages1-3-20261012`)
**BB-Bounce baseline target:** `da1babd` (branch
`feat/nms-session-trend-guard-20261013`)
**Deployment mode:** **ACTIVE ENFORCEMENT** (not shadow).

**Status: NOT DEPLOYED.** All checks pass. Awaiting operator approval.

---

## Permission matrix (as deployed)

| session_trend prevailing | BUY | SELL |
|---|---|---|
| STRONG_TREND_DOWN | **blocked** | allow |
| STRONG_TREND_UP | allow | **blocked** |
| RANGE | allow | allow |
| UNKNOWN (incl. NORMAL) | allow | allow |

Fail-safe shortcuts (every one of these ALLOWS the trade):

| Condition | Outcome | Reason label |
|---|---|---|
| `BB_BOUNCE_SESSION_TREND_GUARD_ENABLED` unset / 0 | allow | — (flag off) |
| `session_trend_guard` module import failed | allow | `allow:guard_module_missing` |
| Guard raised unexpectedly | allow | `allow:guard_exception:<Type>` |
| Snapshot file missing | allow | `allow:no_snapshot` |
| Snapshot `data_fresh=False` or older than `SESSION_TREND_GUARD_MAX_AGE_SECS` (default 900s) | allow | `allow:snapshot_stale:<prev>` |
| Direction string not BUY/SELL | allow | `allow:unsupported_direction` |

---

## Verification checklist (all PASS)

### 1. Branches ready for deployment

| Repo | Dev branch | HEAD | Live HEAD | Divergence | Fast-forward? |
|---|---|---|---|---|---|
| AutoBot (`/opt/tradingbot`) | `feat/nms-data-continuity-stages1-3-20261012` | `6bc768e` | `5c4e852` (detached) | 21 commits ahead | **yes** (merge-base = live HEAD) |
| BB-Bounce (`/opt/bb_bounce`) | `feat/nms-session-trend-guard-20261013` | `da1babd` | `542746a` (main) | 1 commit ahead | **yes** |

Working trees clean (only `__pycache__` untracked; nothing to commit).

### 2. Snapshot publication path

Both sides use the same default `SESSION_TREND_SNAPSHOT_DIR =
"/opt/tradingbot/cache"`, same filename convention
`session_trend_<SYM>.json`.

- Writer: `session_trend.py:757` →
  `/opt/tradingbot/cache/session_trend_GBPUSD.json`
- Reader: `session_trend_guard.py:101` → same path.
- Both processes run as `autobot` user (verified via `ps aux`).
- Directory `drwxr-xr-x autobot autobot` — writable + readable.
- Write cadence: on every M5 bar close
  (`normal_market_state.py:790-795` → `session_trend.on_bar_close`
  → `_write_snapshot`).
- Reader staleness window: 900s default (overridable via
  `SESSION_TREND_GUARD_MAX_AGE_SECS`). 5-minute bar cadence sits
  well inside this.

### 3. IG daily-% + pivot connections

- **Boot bridge** at `autobot.py:10534-10552` — after
  `ig_daily_pivots.startup_catch_up`, call both bridges with the
  live, already-authenticated `IGService`. No new POST /session.
- **Heartbeat bridge** at `autobot.py:9740-9761` — after
  `ig_daily_pivots.maybe_run_scheduled`, refresh pivots every tick
  (idempotent) and refresh daily-% in the first 5 minutes of each
  hour.
- Live payload confirmed:
  `/opt/tradingbot/cache/htf/daily_pivots.json` dated
  `trading_date=2026-10-12`, GBPUSD pivots present.
- **These inputs are SUPPORTING EVIDENCE** labelled in the reason
  string; they are not establishment / reversal gates.
  Classification is unchanged whether or not they are populated.

### 4. Every BB-Bounce opening order passes the guard

Call chain:

```
TradeRunner.open_on_confirm()        (trade_runner.py:404)
  └─ self.gw.open_market()           (trade_runner.py:453,460)
       └─ LiveGateway.open_market()  (main.py:51-57)
            └─ open_sb_now()         (open_sb_now.py:62)
                 └─ GUARD CHECK      (open_sb_now.py:95-140)
                      ├─ blocked  → return BLOCKED_BY_SESSION_TREND_GUARD
                      └─ allowed → fall through to IG REST
```

**Single choke point.** No other opening path exists. Shadow /
replay harness paths do not call `open_sb_now` (verified via
grep on BB-Bounce dev branch).

### 5. BB-Bounce entry / stops / targets unchanged

Dev branch diff vs. live baseline (`542746a..da1babd`):

```
 open_sb_now.py                                |  66 ++++++++  additions only
 session_trend_guard.py                        | 207 +++++++++++  new file
 tests/test_session_trend_guard_integration.py | 209 ++++++++++  new file
 3 files changed, 482 insertions(+), 0 deletions
```

- `trade_runner.py` — **unchanged** (C1/C2/C3 setup detection,
  arming, confirmation, entry trigger).
- `bands.py` — **unchanged** (Bollinger Band computation).
- `stop_sizing.py` — **unchanged** (stop + target distance logic).
- `close_sb_now.py` — **unchanged** (position close path).
- `open_sb_now.py` — guard is **additive** at the top of the
  function; everything after the guard (deal reference, IG REST,
  response handling) is identical to live.

### 6. Fail-safe behaviour

All 10 integration tests pass:

```
tests/test_session_trend_guard_integration.py — 10 passed in 0.17s

  flag_off_never_blocks                         → fail-safe allow
  missing_snapshot_proceeds                     → fail-safe allow
  stale_snapshot_proceeds                       → fail-safe allow
  corrupt_snapshot_proceeds                     → fail-safe allow
  unknown_and_range_do_not_block[UNKNOWN]       → policy allow
  unknown_and_range_do_not_block[RANGE]         → policy allow
  buy_under_down_blocks_before_ig               → enforce
  sell_under_up_blocks_before_ig                → enforce
  sell_under_down_proceeds_to_ig                → aligned allow
  buy_under_up_proceeds_to_ig                   → aligned allow
```

Guard is self-contained: zero AutoBot runtime imports; snapshot
JSON only. If AutoBot stops writing snapshots, BB-Bounce reads
stale → allows. If AutoBot never deploys, BB-Bounce (with flag
on) still allows (`allow:no_snapshot`).

### 7. Rollback immediately available

Three rollback paths of increasing scope — see §Rollback below.
The fastest (flag flip + bb-bounce restart) reverts enforcement
in **under 30 seconds** without touching code.

### 8. Test runs

```
AutoBot:
  cd /home/autobot/tradingbot-wt/nms-continuity-20261012
  python -m pytest tests/data_continuity/  →  102 passed in 7.93s

BB-Bounce:
  cd /home/autobot/bb-bounce-wt/session-trend-20261013
  python -m pytest tests/test_session_trend_guard_integration.py
                                             →  10 passed in 0.17s
```

Combined 112 tests pass. No regressions.

---

## Deployment commands (exact)

**Operator must run these on the live host (161).**

### Step 1 — Merge AutoBot dev branch into production branch

The live `/opt/tradingbot` tree is a detached-HEAD worktree at
`5c4e852`. To update:

```bash
# From the main AutoBot clone (NOT a worktree):
cd /opt/tradingbot
# Verify we are on the production ref before merge:
git log --oneline -1
# → 5c4e852 fix(v3): five audit defects — callback signature, ...

# Fast-forward merge the dev branch:
git merge --ff-only feat/nms-data-continuity-stages1-3-20261012

# Expected result: HEAD advances to 6bc768e
git log --oneline -1
# → 6bc768e feat(nms): wire IG daily-%% + daily-pivot bridges...
```

If `--ff-only` fails, the merge-base has moved; **stop and
contact operator** — this preflight assumes a fast-forward.

### Step 2 — Merge BB-Bounce dev branch into main

```bash
cd /opt/bb_bounce
# Verify current:
git log --oneline -1
# → 542746a merge: deploy BB Bounce enhancements...
git branch --show-current
# → main

git merge --ff-only feat/nms-session-trend-guard-20261013

# Expected result: HEAD at da1babd
git log --oneline -1
# → da1babd feat(bb-bounce): session-trend counter-trend guard at open_sb_now
```

### Step 3 — Add BB-Bounce env flag

**Operator edits `/opt/bb_bounce/.env` and appends:**

```
BB_BOUNCE_SESSION_TREND_GUARD_ENABLED=1
```

Optional (both have reasonable defaults):

```
# Already defaults to /opt/tradingbot/cache — only set if custom:
# SESSION_TREND_SNAPSHOT_DIR=/opt/tradingbot/cache
# Already defaults to 900s (15 min) — only tighten if snapshot
# writer is known to run on a stricter cadence:
# SESSION_TREND_GUARD_MAX_AGE_SECS=900
```

**Verify .env parse before restart:**

```bash
grep BB_BOUNCE_SESSION_TREND_GUARD_ENABLED /opt/bb_bounce/.env
# → BB_BOUNCE_SESSION_TREND_GUARD_ENABLED=1
```

### Step 4 — Restart AutoBot first

AutoBot must restart first so it begins:
- publishing the new fuller snapshot JSON (with
  `pivot_source_date`, `ig_daily_pct_*` fields),
- running the bridge calls at boot + heartbeat.

```bash
sudo systemctl restart autobot.service
sudo systemctl status autobot.service --no-pager | head -20
```

Wait for the first bar close + snapshot write (≤ 5 minutes).
Verify snapshot:

```bash
# Check snapshot exists and is current:
ls -la /opt/tradingbot/cache/session_trend_GBPUSD.json
cat /opt/tradingbot/cache/session_trend_GBPUSD.json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); \
      print('prevailing:', d['prevailing']); \
      print('evaluation_ts:', d['evaluation_ts']); \
      print('data_fresh:', d['data_fresh']); \
      print('daily_pivots.R3:', (d.get('daily_pivots') or {}).get('R3')); \
      print('ig_daily_pct_change:', d.get('ig_daily_pct_change'))"
```

Expected output pattern:

```
prevailing: UNKNOWN  (or DOWN/UP/RANGE depending on time of day)
evaluation_ts: 2026-10-13T...+00:00  (within the last 5 min)
data_fresh: True
daily_pivots.R3: 13293.23  (or today's value)
ig_daily_pct_change: -0.21  (or current value)
```

**If `daily_pivots.R3` is None, the pivot bridge did not fire.**
Likely cause: `ig_daily_pivots.read_pivots` returning None (file
missing or stale). Investigate before enabling the guard.

**If `ig_daily_pct_change` is None, the daily-% bridge did not
fire.** Likely cause: IG session not attached by boot time, or
IG REST error. The guard will still function (daily-% is
informational, not a gate).

### Step 5 — Restart BB-Bounce

```bash
sudo systemctl restart bb-bounce.service
sudo systemctl status bb-bounce.service --no-pager | head -20
```

### Step 6 — Verify active enforcement

Watch the BB-Bounce log for guard decisions on the next opening
attempt:

```bash
sudo journalctl -u bb-bounce.service -f -n 50 \
  | grep -E "BLOCKED_BY_SESSION_TREND_GUARD|open_sb_now BLOCKED|🛡"
```

If a counter-trend attempt arrives, the log will show:

```
🛡 open_sb_now BLOCKED by session-trend guard: direction=BUY \
  epic=CS.D.GBPUSD.TODAY.IP reason=block:established_down:disp=...
```

If no counter-trend attempt comes in the first few hours, the
guard is passive — this is expected during RANGE/UNKNOWN sessions
and does not indicate a problem.

### Step 7 — Confirm Oct-12-shaped behaviour

The pinned regression (`tests/data_continuity/test_phase8_oct12_
regression.py`) proves the behaviour against archived data. The
live system's actual behaviour on an analogous day cannot be
pre-tested; monitor via the log command above.

---

## Rollback commands (ordered by speed)

### Rollback A — Flag-off (fastest, ~30 seconds)

**No code changes.** Flip the enablement flag:

```bash
# Edit /opt/bb_bounce/.env — change the line to:
BB_BOUNCE_SESSION_TREND_GUARD_ENABLED=0
# or delete it entirely.

sudo systemctl restart bb-bounce.service
```

The guard immediately becomes a no-op (returns `allow:...` for
every call). AutoBot continues publishing snapshots harmlessly.
This is the recommended first response if enforcement causes an
unexpected issue — zero code regression.

### Rollback B — Revert BB-Bounce guard commit only

Keep AutoBot's new session_trend infrastructure (snapshots keep
flowing), roll BB-Bounce back to its live baseline:

```bash
cd /opt/bb_bounce
git log --oneline -3
# → da1babd feat(bb-bounce): session-trend counter-trend guard...
# → 542746a merge: deploy BB Bounce enhancements...

git reset --hard 542746a   # or: git revert da1babd (safer)

sudo systemctl restart bb-bounce.service
```

### Rollback C — Full revert (both services)

If the AutoBot bridges themselves cause an issue, revert both:

```bash
# BB-Bounce (as in B above):
cd /opt/bb_bounce
git reset --hard 542746a
sudo systemctl restart bb-bounce.service

# AutoBot:
cd /opt/tradingbot
git log --oneline -1
# → 6bc768e feat(nms): wire IG daily-%% + daily-pivot bridges...
git reset --hard 5c4e852   # back to live baseline
sudo systemctl restart autobot.service
```

**Important:** `git reset --hard` is DESTRUCTIVE. If any uncommitted
work exists in `/opt/tradingbot` or `/opt/bb_bounce`, `git stash`
is prohibited by the standing rules — ask operator before running.
The preflight audit shows both trees clean (only __pycache__
untracked), so these commands are safe at the time of this report
and should remain so provided no commits land in between.

### Rollback — monitoring verification

After any rollback:

```bash
# Confirm guard off:
grep BB_BOUNCE_SESSION_TREND_GUARD_ENABLED /opt/bb_bounce/.env

# Confirm no BLOCKED entries in last hour:
sudo journalctl -u bb-bounce.service --since "1 hour ago" \
  | grep -c "BLOCKED_BY_SESSION_TREND_GUARD"
# Expected: 0
```

---

## Approval request

Pre-deployment status: **all 8 checks pass.**

If approved:
1. Operator runs Step 1 (AutoBot merge).
2. Operator runs Step 2 (BB-Bounce merge).
3. Operator edits `.env` per Step 3.
4. Operator restarts AutoBot per Step 4 and verifies snapshot.
5. Operator restarts BB-Bounce per Step 5.
6. Operator monitors per Step 6 for the first 1-2 trading sessions.
7. Rollback available at any point per the three-tier plan above.

**No deployment or restarts have been performed by this review.**
STOP FOR OPERATOR APPROVAL.
