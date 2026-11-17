# STP dashboard — deployment readiness and rollback

Branch `stp-dashboard` (worktree `/home/autobot/worktrees/autobot-stp-dashboard`), based on production `cc70dc5`.

## What changes in production

| File | Effect | Takes effect |
|---|---|---|
| `dashboard/static/index.html` | tabs; compact planner card replaces the big panel; loads the STP tab on first use | at once (nginx serves the repository) — browser reload |
| `dashboard/static/stp/*`, `dashboard/static/vendor/*` | the tab's code, style, chart library | served by the data service after its restart |
| `dashboard/stp.py`, `dashboard/server.py` | read-only `GET /api/stp/...`; `planner.card` in `/api/status` | after `autobot-dashboard` restarts |
| `planner/keeper.py` | reporting only: `issued.jsonl` written when a recommendation is created | the next planner run (the price service starts a fresh `python -m planner run` after each 5-minute candle) — **no price-service restart** |
| docs, tests | – | – |

Not changed: nginx, systemd units, `.env`, settings, strategies, orders, trade manager, safety, risk, the planner's
forecasting and lifecycle rules, `recommendations.jsonl` and `current.json` formats. No new Python dependency. No new
service. The browser loads nothing from outside this server.

Between the merge and the dashboard restart, the page degrades safely: the card falls back to the panel's fields, and
the STP tab says it could not be loaded; the rest of the dashboard works.

## Dependencies

TradingView Lightweight Charts 4.2.3 standalone build, vendored (Apache-2.0; licence beside it; npm tarball sha1
verified on download, file sha256 pinned in the tests).

## Install (as done, or by hand)

1. Backup: tag `pre-stp-dashboard-20261117` on the production commit; copy `dashboard/` and `planner/keeper.py` to
   `/home/autobot/backups/stp-dashboard-deploy-20261117/`.
2. `cd /opt/autobot && git merge --ff-only stp-dashboard` (only if `main` is still the base and no tracked file is
   modified by another session; untracked files of other sessions are left alone).
3. Smoke test the merged code on 127.0.0.1 (another port) against the production files, read only.
4. Restart the data service: `sudo systemctl restart autobot-dashboard` (owner). Without sudo, the service can be
   restarted by systemd itself: it runs as `autobot` with `Restart=on-failure`, so `kill -KILL <its pid>` makes
   systemd start it again after 5 seconds. Never touch `autobot-prices`.
5. Verify: service active with a new PID; `/api/status` 200 through the service; `/api/stp/*` 401 without a session;
   page loads; a logged-in check of every STP route (in-process with the production code).

## Rollback

    cd /opt/autobot
    git reset --keep pre-stp-dashboard-20261117    # undoes the fast-forward; only the merged files change,
                                                   # other sessions' untracked files are kept
    sudo systemctl restart autobot-dashboard       # or: kill -KILL $(systemctl show -p MainPID --value autobot-dashboard)

If `main` has moved on since (other sessions' commits), revert instead: `git revert -m 1 <merge>` or
`git revert <stp commits>` by path, then restart the dashboard.

`issued.jsonl` can stay (nothing else reads it) or be moved aside. The old planner panel returns with the old
`index.html`. The price service is never involved.

## Risks

- Low: the tab is read only and isolated (lazy-loaded script, its own routes, guarded). A failure shows
  "unavailable" on the tab only.
- The planner change is a write to a new file inside a try/except; tested that a failure to write leaves the
  recommendation unchanged.
- Restarting the dashboard drops in-flight requests for ~5 seconds; logged-in sessions stay valid (same secret key).
- `PLANNER_OBSERVE` off: the tab and card disappear, exactly as the old panel.
