# Top-5 highest-profit July days — HEAD tip + strategy split

Data sources: `git reflog /opt/tradingbot` (HEAD movements per second), `backups/eod-review/2026-07-31/signal_log.jsonl` (fires + outcomes).

| rank | date | net pips | fires | HEAD at 00:00 UTC | HEAD moves during trading | single-tip capture? |
|---:|---|---:|---:|---|---:|---|
| 1 | 2026-07-21 | +138.8 | 13 | `ae9de0f` (Jul 20 18:54) | 11 | NO — HEAD moved 11× |
| 2 | 2026-07-15 | +102.8 | 25 | `30371ad` (Jul 14 17:05) | 6 | NO — HEAD moved 6× |
| 3 | 2026-07-31 | +97.2 | 12 | `fcda554` (Jul 29 15:15) | 0 | **YES** — fcda554 all day |
| 4 | 2026-07-02 | +96.8 | 8 | `9ea9470` (Jul 1 20:35) | 0 during trading | **YES** — 9ea9470 all fires |
| 5 | 2026-07-06 | +62.1 | 11 | `bfe1ac7` (Jul 5 22:35) | 2 | NO — moves at 11:50 (faf109e) and 12:19 (383c599) |

**Per-strategy pip contribution on each top-5 day:** see PROVENANCE.md §5 in the parent package. Full breakdown per day + timestamp there.

Neither `c60ea96` (this package's tip) nor any other single July tip cleanly covers all 5 top days. `fcda554` and `9ea9470` each cleanly capture 1 top-5 day. `c60ea96` was live during none of them (its 8h20m window lay between fcda554-adjacent commits).
