# HEAD stability windows in July 2026 (from git reflog)

Each row is a period during which working-tree HEAD did not move. **Bot restart-uncertainty is bounded by these intervals** — the running SHA changed at most when HEAD did (if the bot was restarted after the fetch).

Sorted longest-first, showing all intervals ≥ 12h:

| tip SHA | idle from | idle to | hours | commit subject | fires during | pips during |
|---|---|---|---:|---|---:|---:|
| `fcda554` | 2026-07-30 07:43 | 2026-08-03 08:32 | 96.8 | (reset — no code change) | 16 | +115.7 |
| `81cab0c` | 2026-07-11 16:27 | 2026-07-14 17:05 | 72.6 | REVERSAL_WATCH min-delay floor | 1 | +5.5 |
| `99c7717` | 2026-07-03 12:04 | 2026-07-05 22:35 | 58.5 | journal Step-1 news-tier | 3 | +29.1 |
| `02d6ef6` | 2026-07-18 14:41 | 2026-07-20 07:46 | 41.1 | post-fire reversal-geometry telemetry | 0 | 0 |
| `e704089` | 2026-07-25 12:36 | 2026-07-26 19:23 | 30.8 | env-layer BAR_QUALITY docs | 0 | 0 |
| `2b4b03d` | 2026-07-16 07:27 | 2026-07-17 09:03 | 25.6 | STRONG runner TP release | 0 | 0 |
| `383c599` | 2026-07-06 12:19 | 2026-07-07 12:29 | 24.2 | regime_engine RANGE detector | 9 | +30.7 |
| `f3191a8` | 2026-07-21 18:16 | 2026-07-22 17:52 | 23.6 | bb_pierce recorder wiring | 10 | +59.8 |
| `9ea9470` | 2026-07-01 20:35 | 2026-07-02 19:51 | 23.3 | BB_BOUNCE STRONG_TREND standdown sink | 8 | +96.8 |
| `329a006` | 2026-07-17 18:37 | 2026-07-18 13:23 | 18.8 | daily journal ERROR family | 0 | 0 |
| `062133d` | 2026-07-10 16:59 | 2026-07-11 10:35 | 17.6 | bb_bounce near-touch fade path | 0 | 0 |
| `4203e89` | 2026-07-26 19:23 | 2026-07-27 12:47 | 17.4 | news-momentum observer (env/40-gates.env fresh) | 4 | −12.1 |
| `30371ad` | 2026-07-14 17:05 | 2026-07-15 10:27 | 17.4 | FXi plan telemetry | 5 | +37.7 |
| `147570f` | 2026-07-23 20:29 | 2026-07-24 12:13 | 15.7 | REST allowance capture | 4 | +8.05 |
| `eeb14f4` | 2026-07-09 20:17 | 2026-07-10 09:20 | 13.1 | logging token redact | 0 | 0 |
| `bfe1ac7` | 2026-07-05 22:35 | 2026-07-06 11:50 | 13.2 | v5_pia gate | 5 | +43.0 |
| `9f899e6` | 2026-07-23 06:47 | 2026-07-23 19:11 | 12.4 | ig_auth in-flight guard | 8 | −14.15 |
| `660899e` | 2026-07-24 19:08 | 2026-07-25 07:18 | 12.2 | bb_bounce setup-lifecycle JSONL | 0 | 0 |
| `c60ea96` | 2026-07-29 06:54 | 2026-07-29 15:15 | 8.4 | align 40-gates BB_BOUNCE_LEVEL_GATE_MODE | 0 | 0 |

**Selection notes:**
- `c60ea96` is at the bottom of this table by idle-hours, yet is chosen because its commit body uniquely records a runtime observation of PID 2654603's environ.
- `fcda554` tops idle-hours AND fires-during-window; excluded from selection per operator brief ("not simply the last July commit").
- `9ea9470` and `f3191a8` are the best "middle-of-month" fire-window candidates but lack the env/40-gates.env freshness AND lack any runtime-observation stamp.
