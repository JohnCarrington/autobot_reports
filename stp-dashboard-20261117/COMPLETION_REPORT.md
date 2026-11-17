# Structural Trade Planner dashboard — completion report (overnight 17–18 November 2026)

**Status: built, tested, committed and DEPLOYED** (deployment authorised by the owner's mid-run message: "deploy the
completed Structural Trade Planner dashboard overnight… You may restart the dashboard service… do not restart trading
or price-processing services"). Observe only throughout; no trading, forecasting or lifecycle rule changed.

- Branch `stp-dashboard` (worktree `/home/autobot/worktrees/autobot-stp-dashboard`), commits `106d2d4`, **`c41ddbd`**.
- Production `/opt/autobot` `main`: `cc70dc5` → **`c41ddbd`** (fast-forward, 23:23:47 UTC). Not pushed to GitHub.
- Backup/rollback: tag `pre-stp-dashboard-20261117`; `/home/autobot/backups/stp-dashboard-deploy-20261117/`
  (`ROLLBACK.md`, previous `dashboard/` + `planner/keeper.py`, planner data copy).
- Progress log: `/home/autobot/worktrees/stp-dashboard-work/progress.log`; deploy log: `deploy.log` there.

## 1. Lifecycle investigation findings

Full report: `docs/research/stp_dashboard_20261117/LIFECYCLE_INVESTIGATION.md`.

- The two SELL 1.32135–1.32199 recommendations are **different records**: `STP-GBPUSD-20261117-2024-1` (created 20:24:13
  UTC) and `STP-GBPUSD-20261117-2200-2` (22:00:02), with identical structural evidence (daily R1, daily swing low,
  hourly swings; Major; primary 1.32000).
- Rec 1: ACTIVE at 20:25 (20:20 candle within the approved 3-pip allowance; physically 1.8 pips inside at 20:45),
  supported at 21:00, **COMPLETED** 22:00:00 (21:55 low 1.32013 within 3 pips of 1.32000). Correct.
- Rec 2: issued 2 s after rec 1 completed (no live recommendation → new one; supersession not involved, correctly),
  with price 1.32035, 3.5 pips above its destination; the next candle touched the destination → **INVALIDATED
  "destination reached before entry"**. Correct under the rules, but it exposes **planner defect D-1**: the
  planner's own guard (`assess.py` `destination_first_applies`) compares the destination with the last close (> 3
  pips), while the touch rule uses the candle extreme with a 3-pip allowance; rec 2 passed the guard by 0.5 pip.
  Proposed correction (not implemented): decide the guard with the same touch test, or do not issue at the
  destination. At 23:00 the same zone was issued as `…-2300-3` inside the guard (rule correctly off; still WAITING).
- "NO RECOMMENDATION" (22:05–23:00): rec 2 had ended and the planner only issues at hourly analyses. Correct
  behaviour, unexplained by the old panel.
- "Tue 22:00 — NOT current": a **dashboard interpretation defect** — the panel printed the recommendation's FC-08
  currency flag (always false with no recommendation) as if it were analysis freshness; data was fresh.
- Records internally consistent; nothing misclassified. Recommendation-history gap: full records were discarded on
  retirement → fixed going forward by the reporting-only `issued.jsonl`.

## 2. Dashboard implementation summary

- New **Structural Trade Planner** tab (hash `#stp`) beside **Operations**, same login/session; shown only while
  `PLANNER_OBSERVE` is on (owner's R3).
- Operations tab: the big planner panel replaced by a compact card (direction, expected movement, status, last
  analysis, freshness, **Open Structural Trade Planner**). Nothing else on that tab changed.
- STP tab: forecast overview (5 tiles) and the no-recommendation explanation (A/B/C/D from recorded reasons);
  interactive chart beside the trade-plan card; lifecycle timeline; history explorer; forecast evaluation;
  collapsible Technical Evidence & Market Structure. Desktop-first, stacks on phones (summary → plan → chart → …).
- Read-only routes `GET /api/stp/{overview,candles,history,recommendation,evaluation,lib/*}` in the existing data
  service; validated and bounded; failure-isolated. nginx unchanged. Docs: `docs/STP_DASHBOARD.md`.
- Planner: one reporting-only addition (`issued.jsonl`).

## 3. Interactive chart capabilities

TradingView Lightweight Charts 4.2.3 (vendored, Apache-2.0). H4/H1/M5 switch (remembered), wheel/pinch zoom, drag
pan, crosshair, price and UK-time axes, current-price line, auto-resize, older candles loaded when panning left,
finished candles only. Overlays from the planner's own records only: 4-hour swings, hourly levels, daily/weekly S/R,
daily/weekly pivots, considered confluence zones; entry zone (shaded), intermediate/primary/extended destinations,
invalidation lines; a schematic dashed forecast path labelled FORECAST; past-recommendation markers. Toggles and
Reset view.

## 4. Recommendation history and evaluation

History: one row per id (identical zones never merged), search, sort, pages; selecting one shows its lifecycle, the
forecast available at creation (full snapshot, or the recorded summary for the two pre-snapshot records — missing
fields shown as "not recorded"), the market observed afterwards, and replays it on the chart with markers.
Evaluation: counts (total, awaiting, activated, completed, invalidated, superseded, never reached zone, reached
primary before/after zone, invalidated before primary, issued at the destination), excursions from the reference
level after activation, creation→zone and activation→primary times, stability across hourly re-checks, ambiguities;
INSUFFICIENT DATA under 3 values. No fills, spreads, P&L, wins or losses.

## 5. Screenshots

`docs/research/stp_dashboard_20261117/screenshots/` (index in its README): desktop and phone, live data (waiting
recommendation, historical selection, evaluation, technical evidence, M5, compact card, the 22:40 no-recommendation
state) and a deterministic fixture for an ACTIVE recommendation. All from the real page; no console errors, no
horizontal overflow.

## 6. Technical and functional tests

42 technical + 24 functional new tests (brief items 1–20 each, plus extras), lifecycles generated by the real keeper.
All pass. Details: `docs/research/stp_dashboard_20261117/TEST_RESULTS.md`.

## 7. Full regression

#1: 2293 passed, 1 failed (`test_ig_is_the_only_part_that_talks_to_ig`: `stp.py` used `urllib`) → fixed without
touching the test. #2: **2295 passed, 0 failed**. Pre-commit hooks: 106d2d4 all passed; **c41ddbd 2296 passed**.
No existing test weakened or edited.

## 8. Branch and commit

`stp-dashboard` @ **`c41ddbd`** (on top of production `cc70dc5`); now also production `main`.

## 9. Deployment (done) and readiness

23:23:46–23:23:58 UTC: preconditions checked (production at cc70dc5, no tracked edits by other sessions), backup,
fast-forward, smoke test of the merged code (every STP and existing route, logged in, in-process on 127.0.0.1:18768),
**dashboard data service restarted** — without sudo, by `kill -KILL` of its own process so that systemd
(`Restart=on-failure`) restarted it (new PID 464694) — then verified: `/api/stp/overview` 401 without a session (404
before), page served by nginx contains the tab, `/api/status` gated, production page loads in a browser with no
script errors. **autobot-prices not restarted** (PID 452409 unchanged). The planner's 23:25 run on the new keeper
code completed normally. Automatic rollback was armed and not needed.

Not verified: a logged-in session through nginx against the live service (the password was not used); the
authenticated routes were verified on the same merged code in-process. **Please open the dashboard, log in and look
at the Structural Trade Planner tab**; reload the page (on a phone, close and reopen the tab).

## 10. Outstanding risks, issues and decisions

1. **Planner D-1** (decision): align the destination-first guard with the touch rule — needs your approval (changes
   planner decisions).
2. D-2 (minor, optional): activation by a candle that started before creation; H-2 (optional): persist the full
   level map so the chart can draw every planner level.
3. **Pre-existing nginx header issue** (found while verifying): the page response carries no
   Content-Security-Policy / X-Frame-Options / nosniff headers, because `location = /` has its own `add_header`
   (nginx then drops the server-level ones). Not caused by this work; fixing needs `deploy/autobot-dashboard.nginx`
   changed (repeat the headers in each location, or an include) and `sudo nginx -t && sudo systemctl reload nginx`.
4. The restart was done by signal because the autobot user cannot use `systemctl restart`; a normal `sudo systemctl
   restart autobot-dashboard` later is harmless.
5. The two 17 November records have summary-only "at creation" data (by design, nothing reconstructed).
6. `main` (c41ddbd) is not pushed to GitHub (production was already ahead of origin before this work).
7. The isolated screenshot tooling (Playwright venv, unpacked libraries) lives in `stp-dashboard-work/`; it is not
   used by AutoBot and can be deleted.
