# STP dashboard — test results

All runs on branch `stp-dashboard` in `/home/autobot/worktrees/autobot-stp-dashboard`, `nice -n 15`, one full suite
at a time (checked no other pytest was running).

| Run | Result | Log |
|---|---|---|
| Baseline before changes: dashboard + planner suites | 107 passed | – |
| Full suite #1 | 2293 passed, **1 failed**: `test_ig_connection.py::test_ig_is_the_only_part_that_talks_to_ig` — `dashboard/stp.py` imported `urllib.parse`. Fixed by a small query parser of its own (the guard test was not changed) | `stp-dashboard-work/full_regression_1.log` |
| Full suite #2 | **2295 passed, 0 failed** (7 min 34 s) | `stp-dashboard-work/full_regression_2.log` |
| Pre-commit hook on commit 106d2d4 (full suite on the committed files) | all passed | – |
| Pre-commit hook on the final commit | see the commit (the hook refuses a commit with a failing test) | – |

No existing test was weakened or edited. One existing test checks an exact snippet of `index.html`
(`test_the_page_keeps_the_planner_section_hidden_unless_a_planner_block_arrives`); the new code keeps that snippet
intact (the owner's R3 rule still holds).

## New tests

`tests/technical/test_stp_dashboard.py` — 42 tests covering the brief's technical items:
1 candle retrieval · 2 ordering · 3 timeframe alignment · 4 no unfinished candle (and partial built candles marked)
· 5 structural overlays are the planner's own recorded levels · 6 entry zone (none drawn without a recommendation)
· 7 targets and invalidation · 8 history one row per id · 9 event order · 10 UTC timestamps as recorded · 11 every
route needs the session · 12 parameter validation, file whitelist, query decoding · 13 pagination, sorting, search ·
14 speed on a month of hourly analyses (< 2 s) · 15 responsive layout rules and touch handling · 16 failure isolation
(a broken STP route leaves `/api/status` working; a damaged planner file shows "unavailable") · 17 existing routes and
the PLANNER_OBSERVE-off behaviour unchanged · 18 no broker access (no web library; page code GETs only its own
routes, no HTML injection) · 19 no trading-code import (static and at run time) · 20 no planner authorisation; the
`issued.jsonl` addition is reporting only and a write failure changes nothing. Plus: the page has the tab and card;
the vendored library is the published 4.2.3 (sha256 pinned); price text conversion.

`tests/functional/test_stp_dashboard_scenarios.py` — 24 tests, lifecycles made by the real keeper:
1 bearish · 2 bullish · 3 corrective reversal · 4 healthy-trend pullback · 5 H4/daily conflict · 6 waiting ·
7 active · 8 completed · 9 invalidated (confirmed break) · 10 superseded · 11 no recommendation with a direction (A)
· 12 indeterminate direction (B) · 13 stale data (C) and "between hourly analyses is CURRENT" · 14 missing indicators
· 15 H4 EMA200 warming up · 16 identical zones stay separate · 17 historical selection (snapshot) and a record from
before snapshots (summary only, nothing reconstructed) · 18 destination reached before entry (D) and the
"issued with price at the destination" flag · 19 continuation across hourly analyses · 20 planner unavailable while
the dashboard works · evaluation never reports trading results · the compact card.

## Visual

10 screenshots (see `screenshots/README.md`), desktop and phone, from the real page; every capture had no console
errors and no horizontal overflow. Defects found and fixed from them: live recommendation drawn as "original"
(historical mode leaking), forecast label running into the price axis, the status stamp overlapping the tab, a tile
word breaking on phones, too many level labels (hourly and far levels now quiet), a 2-decimal planner number shown
as "1.32070.4", negative excursions (now floored at 0, a distance).
