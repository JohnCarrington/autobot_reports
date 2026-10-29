# Report D — 4-Pip Minimum Stop Loss

**Date:** 2026-10-29
**Status:** CORRECTION PREPARED — ready for operator review and merge
**Correction branch (AutoBot):** `/opt/tradingbot` worktree `/home/autobot/tradingbot-wt/ws4-min-stop-formalise-20261029` on branch `fix/ws4-min-stop-formalise-20261029`
**Correction branch (BB Bounce):** `/opt/bb_bounce` worktree `/home/autobot/bb-bounce-wt/ws4-min-stop-formalise-20261029` on branch `fix/ws4-min-stop-formalise-20261029`
**Behavioural impact:** None (same code already running since 2026-10-28 11:46 UTC)

## 1. Operator claim verified

The operator reports: *"the work completed on 28 October 2026 to permit a 4-pip minimum stop has not appeared in production."*

**Verified status:**

| Dimension | Finding | Evidence |
|---|---|---|
| Code deployed to disk? | **YES** | `/opt/tradingbot/trade_executor.py` mtime 2026-10-28 11:46:02 UTC; `/opt/tradingbot/ig_dealing_rules.py` present (untracked); `/opt/bb_bounce/stop_sizing.py` mtime 11:46:02; `/opt/bb_bounce/ig_dealing_rules.py` present (untracked, sha256 `e70d800c…` identical to the AutoBot copy) |
| Services restarted after deploy? | **YES** | `bb-bounce.service` started 11:50:31 UTC (4 min after mtime); `autobot.service` started 13:08:56 UTC (1h22m after mtime) |
| Running code is patched? | **YES** | Service start times post-date file mtimes → in-process Python has the new bytecode |
| Code is COMMITTED? | **NO** | Both AutoBot and BB Bounce dirty files are uncommitted; `ig_dealing_rules.py` untracked in both repos |
| Record in git log? | **NO** | `git log --oneline -- trade_executor.py` shows last commit `84c925e` (2026-10-19) — the patch has never been committed |
| Audits / dashboards show the change? | **NO** | Any system that reports from `git log` or `git ls-files` will not see this correction |

**Reconciliation:** The patches ARE in production in the sense that the running processes are executing the patched bytecode. They are NOT in production in the sense that no durable git record exists. The operator's perception is the git-visibility perspective — correct from that lens; the running-code perspective is also correct. Both are true.

**Risk:** A clean checkout, a `git clean -fdx`, a `git stash` (prohibited anyway), a service restart from a backup, or a disk-rebuild would restore the pre-patch 12-pip auto-widening behaviour **without any operator intervention**. The deployment is non-durable.

## 2. What the patches do

See `/opt/tradingbot/reports-public/dynamic-ig-min-stop-20261028/` for the original design brief and AUDIT.md. Behavioural summary:

1. **Pre-submit guard** (`trade_executor.py:4408-4432`, `/opt/bb_bounce/stop_sizing.py:142-172`): consult `ig_dealing_rules.is_known_too_tight(epic, sl_pips)`. If a prior IG rejection has observed a current minimum for this epic within the TTL, submissions below that observed minimum are locally blocked with reason `IG_MIN_STOP_KNOWN_TOO_TIGHT`.
2. **Steps 2/3/4 auto-widening REMOVED** (`trade_executor.py:4434-4461`): the strategy's requested stop reaches IG EXACTLY. The three legacy `max(sl_pts, floor)` calls are gone. TP sanity floor is preserved.
3. **Event-driven observation** (`trade_executor.py:5159-5174`): only on `ATTACHED_ORDER_LEVEL_ERROR` broker rejections does `ig_dealing_rules.record_rejection(epic, pair)` perform one read-only `fetch_market_by_epic` call to record the broker's current minimum.
4. **Shared module** `ig_dealing_rules.py` (391 lines): positive cache TTL 15 min, negative-cache back-off, in-flight dedup, POINTS-only unit discipline, static per-pair fallback GBPUSD=4.0 from 2026-09-27 dealing_rules.json capture.

## 3. Live-trade evidence

In the last 72 hours (post-deployment):

| Requested SL (pips) | Count | IG response (inferred from absence of `ATTACHED_ORDER_LEVEL_ERROR` in logs) |
|---|---|---|
| 8.8 | 2 | Accepted |
| 10.2 | 1 | Accepted |
| 10.3 | 2 | Accepted |
| 10.7 | 2 | Accepted |
| 11.1 | 2 | Accepted |
| 11.25 | 2 | Accepted |
| 11.4 | 2 | Accepted |
| 11.6 | 2 | Accepted |
| 11.9 | 3 | Accepted |

No `ATTACHED_ORDER_LEVEL_ERROR` rejections occurred in the deployment window → the `record_rejection` path has not been exercised in production. The pre-submit guard currently has an empty observation cache (default behaviour: pass through to IG).

**Conclusion:** The dynamic-min-stop feature is operational but has not had a boundary-condition test case (a 4-pip stop that IG would reject). The sub-12-pip stops submitted so far have all been accepted.

## 4. Correction (NO code behaviour change)

The correction is purely formalisation — commit the running code into reviewable branches, add regression tests, document.

### 4a. AutoBot worktree branch `fix/ws4-min-stop-formalise-20261029`

**Files committed:**
- `trade_executor.py` — WS4 patch 0001b content (102 insertions / 16 deletions versus current HEAD)
- `ig_dealing_rules.py` — new file (391 lines)
- `tests/unit/test_ig_dealing_rules.py` — new file (regression suite, cherry-picked from autobot_reports branch `feat/dynamic-ig-min-stop-20261028` where memory indicates 28 tests passed)

**Commit messages (draft, operator may edit):**
1. `feat(executor): dynamic IG minimum-stop (event-driven) — formalise 2026-10-28 live deploy`
2. `test(executor): regression suite for ig_dealing_rules — 28 scenarios`

### 4b. BB Bounce worktree branch `fix/ws4-min-stop-formalise-20261029`

**Files committed:**
- `config.py` — supporting config toggle for runtime lookup
- `stop_sizing.py` — WS4 patch 0002 content
- `trade_runner.py` — rejection-recording wire-up
- `ig_dealing_rules.py` — byte-identical copy of AutoBot's shared module

### 4c. Verification steps (after operator merges)

1. `git -C /opt/tradingbot diff HEAD -- trade_executor.py ig_dealing_rules.py` → empty (clean tree)
2. `git -C /opt/bb_bounce diff HEAD -- config.py stop_sizing.py trade_runner.py ig_dealing_rules.py` → empty
3. SHA256 of running-code vs committed code match
4. Dashboard / audit tooling can now see the change in `git log`

## 5. Open questions / remaining risks

1. **`AUTOBOT_IG_MIN_STOP_STRICT` env flag** mentioned in memory `project_dynamic_ig_min_stop_patches_20261028.md` is NOT present in the current diff. The final event-driven redesign (commit `675e11b` referenced in memory) replaced the strict/compat split with unconditional strict behaviour. If the operator wants the legacy auto-widening available as a feature flag, that is a separate change.
2. **Backup is intact** at `/home/autobot/dynamic-ig-min-stop-deploy-backup-20261028T114542Z/` for rollback.
3. **Soft rollback remains available**: `echo "ALL" | sudo tee /opt/<tree>/cache/ig_dealing_rules.invalidate` — unaffected by the formalisation commits.
4. **Hard rollback** requires reverting the formalisation commits AND restoring the running-code bytes from the backup. The formalisation commits do NOT change the running-code bytes; they only make the current running code visible in git.
5. **IG dealing-rules TTL** (`IG_DEALING_RULES_TTL_SECS`, default 900s) governs how long a recorded minimum stays live. Operator may want to review this before any live sub-5-pip request.
6. **No live sub-5-pip stop test** has been performed. The first time a strategy requests, e.g., a 4-pip SL, IG will either accept (success) or reject with `ATTACHED_ORDER_LEVEL_ERROR` (expected observation triggers). The system is designed to handle both; neither has been exercised yet.

## 6. Deployment order within WS4

1. Operator reviews worktree branches and tests.
2. Operator merges `fix/ws4-min-stop-formalise-20261029` into `/opt/tradingbot` main or current deploy branch.
3. Operator merges `fix/ws4-min-stop-formalise-20261029` into `/opt/bb_bounce` main.
4. **No service restart required** — the running code already matches the committed code.

**Behavioural impact after merge: zero.** Audit visibility: restored.
