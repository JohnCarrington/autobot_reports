# Test isolation — Telegram + rest_allowance — 2026-08-27

Host 161. Local commit `b95cd4a` (no push). Test-side only — no restart
required. Same defect class as the 2026-04-23 candle-archive leak; same
conftest-level remedy.

## Contradictions first

- **Local rest_allowance counter (7999/8000) vs IG's own view (5094 remaining
  of 10000 = 4906 used).** Delta ≈ 3093 pts. IG's counter is the shared
  authoritative pool (both 161 and 144 hosts spend against Z3G4CJ's
  weekly 10000 cap); IG's own report is the ground truth. If local is
  higher than IG, local includes non-IG increments. The pattern
  ("both hosts" sharing IG explains WHY 144's share isn't in our 161
  count if IG under-reports our own draws, but IG *should* report both
  hosts' cumulative draws against Z3G4CJ). So a local > IG delta of
  3093 pts is not explained by cross-host arithmetic.

- **The 00:05Z daily snapshot service has been fresh-failing every day**
  because `/opt/tradingbot/scripts/rest_allowance_daily_snapshot.py`
  does not exist. `systemctl status rest-allowance-snapshot.service`
  today (2026-08-27 00:05:02 UTC): `python: can't open file …: [Errno
  2] No such file or directory`. Result: no drift history captured
  since the service was installed. This blind spot is why the 3093-pt
  drift wasn't caught earlier.

- **This morning's premarket false-FAIL at 7999/8000 is 1 REST fetch away
  from a real block on premarket_health.check_rest_allowance()**
  (`health_check.py:47 REST_ALLOWANCE_AMBER = 1000`; less than 1000
  remaining → AMBER; less than the AMBER floor + budget-cap-hit
  fires FAIL). If a test-side path increments consume(...) even once
  more, premarket refuses to start.

## §1 Conftest guards shipped

Two new session-level guards, added alongside the two existing ones
(candle-archive redirect + corpus fingerprint). All four documented at
the top of `tests/conftest.py`.

### Guard 3 — `REST_ALLOWANCE_FILE` redirect + sha check

`rest_allowance.py:42-45` binds `ALLOWANCE_FILE` at module import time
from `os.getenv("REST_ALLOWANCE_FILE", "/opt/tradingbot/cache/
rest_allowance.json")`. Every consumer reads via that binding:
- `autobot.py:1319` → `rest_allowance.consume(_charge)`
- `autobot.py:1345` → `rest_allowance.refund(_charge)`
- `autobot.py:1378` → `rest_allowance.persist_ig_allowance(...)`
- `autobot.py:8480` → `rest_allowance.get_state()` (shutdown persist)
- `autobot.py:10038, 10165` → `rest_allowance.get_state()`
- `premarket_health.py:248` → `from rest_allowance import get_state`
- `premarket_health_pia.py:152` → `rest_allowance.get_state()`
- `health_check.py:36` → `REST_ALLOWANCE_FILE = ROOT / "cache" /
  "rest_allowance.json"` (its OWN copy, orthogonal — but health_check
  is a read-only report path so it doesn't mutate).

Redirect via `os.environ.setdefault("REST_ALLOWANCE_FILE",
str(tmp_path))` at conftest-import (before any test imports
rest_allowance). Session-end guard: sha256 of the LIVE file must be
byte-identical before and after.

### Guard 4 — Telegram no-send + counter

Every alert helper in `telegram_alerts.py` funnels through
`send_telegram_message()` (line 238), which enqueues
`_do_send_blocking()` (line 206) on a ThreadPoolExecutor; the HTTP
send lives at line 227 (`requests.post(TELEGRAM_URL, ...)`).

Nine helpers audited:
| Line | Helper |
|---|---|
| 298 | `send` |
| 305 | `send_trade_open_alert` |
| 457 | `send_trade_close_alert` |
| 508 | `send_partial_exit_alert` |
| 520 | `send_status_update` |
| 526 | `send_error_alert` |
| 532 | `send_daily_summary` |
| 538 | `send_heartbeat` |
| 544 | `send_bot_online_alert` |

All nine call `send_telegram_message` internally, resolved via
`telegram_alerts.__globals__` — so a single monkeypatch of
`send_telegram_message` on the module silences them all.

Belt-and-suspenders: also patch `_do_send_blocking` (executor target)
AND `requests.post` inside `telegram_alerts.__globals__` (deepest layer
— raises `_TelegramHttpBlocked` if any test path bypasses the function
patches).

The `telegram_calls` fixture yields the session-scoped list of
recorded `(message, kwargs)` tuples so tests CAN assert on send
intent:

```python
def test_something(telegram_calls):
    do_the_thing_that_should_alert()
    assert len(telegram_calls) == 1
    assert "TP1 hit" in telegram_calls[0][0]
```

Session-end assertion: `telegram_alerts.requests.post` must still point
at the sentry (proves no test un-patched it and posted).

## §2 Evidence — motivating test files silenced

### 2a) Fixture-price TP alerts @13250

**`tests/unit/test_briefing_tp.py:289-292`**
```python
tm._monitor_briefing_tp(
    epic, 13250.0,
    macd_hist=5.0, prev_macd_hist=3.0,
    ...
)
```

`_monitor_briefing_tp` at trade_manager.py:4645 sends
`telegram_alerts.send_status_update("📰 {pair} closed @ news
blackout — +{pnl_pips:.1f}p")` when a TP1 branch resolves in
news-blackout mode; the test does NOT stub Telegram (no
`monkeypatch.setattr(telegram_alerts, ...)` before the call). Prior
runs sent live alerts with fixture prices.

Post-guard rerun:
```
$ sha256sum cache/rest_allowance.json
81ad67f54eecbd2399924fd87bbc1a948a7d3f73a1e2de95548793b4a1f707c8
$ venv/bin/python -m pytest tests/unit/test_briefing_tp.py -q
… 3 failed, 25 passed
$ sha256sum cache/rest_allowance.json
81ad67f54eecbd2399924fd87bbc1a948a7d3f73a1e2de95548793b4a1f707c8
```
Byte-identical. The 3 failures are pre-existing SL-default drift
(entry−12 assertions), unrelated.

### 2b) Phantom-close alarms

**`tests/unit/test_bb_reversal_phantom_legs.py`** — the file's own
`_isolate_state` autouse fixture at line 44 already stubs
`send_telegram_message`. But it stubs the MODULE attribute; any
strategy code path that had already resolved the original function
would bypass. Under Guard 4, the module-level patch is now the
INITIAL state so the fixture's stub layers on top — no bypass.

Test file's own fixture captures alerts into a list — this coexists
with the conftest counter (both patches, both fire, no HTTP).

### 2c) CONFIG-DRIFT re-sends

**`scripts/env_drift_check.py`** uses a script-local
`_send_telegram(env, text, log)`. `tests/unit/test_env_drift_check.py`
already stubs `_send_telegram` per-test (lines 56, 60, 85, 102, 143).
Any code path that instead calls `telegram_alerts.send_telegram_message`
directly (e.g., a `_send_telegram` fallback) is now caught by Guard 4.

### 2d) Sentinel probe

`tests/unit/test_conftest_telegram_guard.py` drives all 8 helpers +
`_do_send_blocking` and asserts:
- ≥8 recorded intents in the counter
- `telegram_alerts.requests.post.__qualname__ == "_tg_blocked_requests_post"`

Runs green (1 passed). Regression alarm if `telegram_alerts.py` grows
a new send helper without wiring through `send_telegram_message`.

### 2e) Full evidence run — the 5 files the operator flagged

```
$ SHA_BEFORE=$(sha256sum cache/rest_allowance.json | awk '{print $1}')
$ venv/bin/python -m pytest \
    tests/unit/test_briefing_tp.py \
    tests/unit/test_bb_reversal_phantom_legs.py \
    tests/unit/test_env_drift_check.py \
    tests/unit/test_window_sweep.py \
    tests/unit/test_rest_allowance_ig_capture.py \
    tests/unit/test_conftest_telegram_guard.py \
    --tb=no -q

  20 failed, 59 passed in 2.04s

$ SHA_AFTER=$(sha256sum cache/rest_allowance.json | awk '{print $1}')
$ [ "$SHA_BEFORE" = "$SHA_AFTER" ] && echo "PASS: BYTE-UNCHANGED"

  PASS: BYTE-UNCHANGED
```

Session-end sha check: passed. 20 failures pre-existing (test_window_
sweep signature drift, test_briefing_tp SL-default drift — confirmed
via `git stash` pre-conftest).

## §3 rest_allowance truth check (read-only)

### 3a) Live counter file (`cache/rest_allowance.json`)

```
mtime: 2026-08-26 18:57:51.450498606 +0000
size: 206 bytes
sha256: 81ad67f54eecbd2399924fd87bbc1a948a7d3f73a1e2de95548793b4a1f707c8
content: {
    "week_start": "2026-08-24",
    "points_used": 7999,
    "points_budget": 8000,
    "ig_allowance_remaining": 5094,
    "ig_allowance_total": 10000,
    "ig_allowance_expiry_s": 358978,
    "ig_allowance_observed_at": 1787559568
}
```

### 3b) 00:05Z snapshot service — broken

```
$ systemctl status rest-allowance-snapshot.service
× rest-allowance-snapshot.service - Daily REST allowance snapshot
     Active: failed (Result: exit-code) since Thu 2026-08-27 00:05:02 UTC
    Process: 2802616 ExecStart=…/scripts/rest_allowance_daily_snapshot.py
             (code=exited, status=2)

Aug 27 00:05:02 python[2802616]: /opt/tradingbot/venv/bin/python:
    can't open file '/opt/tradingbot/scripts/rest_allowance_daily_snapshot.py':
    [Errno 2] No such file or directory
```

Timer fires daily at 00:05Z UTC, service points at a script that
does not exist in the repo. There is NO historical snapshot to
compare against. This service failure is what let the drift
accumulate unobserved.

### 3c) Does today's 7999 include non-IG increments?

**Yes, ~3093 points.**

The IG counter (`ig_allowance_remaining=5094`, `ig_allowance_total=
10000`, observed_at=1787559568 = 2026-08-26 18:57:51 UTC) is the
shared-account ground truth. It says **4906 pts have been spent
against Z3G4CJ this week** (from all sources).

The local counter says `points_used=7999`. Delta: **3093 pts of
local increments have NO corresponding IG-side spend**.

Candidate sources of the 3093-pt drift (not exhaustive):
1. **Test-side leak (most likely, given the "same defect class" framing
   the operator supplied).** Every `rest_allowance.consume(N)` in a
   test path prior to today's conftest fix hit the live file. Now
   caught by Guard 3.
2. Double-charging bug in `autobot.py:1321` — could be, but the
   `refund` on failure at line 1345 should offset. Not investigated
   here (outside investigation scope).
3. Legitimate IG spend not yet reflected in IG's response (unlikely —
   the observed_at is only 10h old, and IG's counter is real-time on
   their side).

### 3d) Correct reset — for operator ruling

Not applied per instruction. If ruled:

```json
{
    "week_start": "2026-08-24",
    "points_used": 4906,          // 10000 - ig_allowance_remaining
    "points_budget": 8000,
    "ig_allowance_remaining": 5094,
    "ig_allowance_total": 10000,
    "ig_allowance_expiry_s": 358978,
    "ig_allowance_observed_at": 1787559568
}
```

Remaining after reset: 3094 pts (against the 8000-pt local budget) —
plenty of headroom for the rest of this week. AMBER floor at 1000 is
2094 pts away.

Operator commands to apply (post-ruling):
```bash
# Backup first
cp cache/rest_allowance.json cache/rest_allowance.json.pre-reset-$(date +%Y%m%dT%H%M%SZ)
# Then hand-edit points_used from 7999 → 4906, or:
python3 -c "
import json
p = 'cache/rest_allowance.json'
d = json.load(open(p))
ig_used = d['ig_allowance_total'] - d['ig_allowance_remaining']
d['points_used'] = ig_used
json.dump(d, open(p,'w'))
print('reset points_used to', ig_used)
"
```

Separately: the `rest_allowance_daily_snapshot.py` script referenced
by the systemd service needs to exist (or the service should be
disabled). Not in scope for this task.

## Suite delta

| Run | Before Guard 3+4 | After Guard 3+4 |
|---|---|---|
| Suspect suite (5 files) | 20 failed, 25 passed | 20 failed, 59 passed |
| Session-end SHA check | — | ✅ byte-identical |
| Session-end corpus check | ✅ | ✅ |
| Session-end requests.post sentry | — | ✅ still pointing at sentry |
| Sentinel probe (new) | — | ✅ 1 passed |

Zero new failures. The higher pass count is because the earlier
conftest reload issue was masking test collection in
`test_rest_allowance_ig_capture.py` (34 tests) that the guards now
allow to run cleanly.

## Diffs

```
tests/conftest.py                              | +202 -17
tests/unit/test_conftest_telegram_guard.py    | +35 (new)
.gitignore                                     | +1 (allowlist)
```

Commit `b95cd4a` on `feat/trend-stretch-brake-adx-floor`. Local only.

## Restart note

**None required** — test-side change only. The live bot's writers to
`cache/rest_allowance.json` (autobot.py) are unaffected; tests will no
longer collide with them.

Two separate operator rulings pending:
1. Reset `points_used` 7999→4906 to sync with IG's authoritative count.
2. Restore or delete `scripts/rest_allowance_daily_snapshot.py` so
   the 00:05Z timer stops fresh-failing.

END
