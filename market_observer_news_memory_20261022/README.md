# Market Observer — news enrichment + historical episode memory (2026-10-22)

Research-only package. Nothing in here touches `/opt/tradingbot` runtime
code, modifies production systemd units, or enables broker calls.

All files below live on the research volume at
`/mnt/volume_lon1_1778405456698/research/live_obs/`. This directory
mirrors them for GitHub-tracked history. The volume paths are the
authoritative install locations.

## What's in this package

### `agent/`
* `historical_episode_memory.py` — point-in-time retriever over the
  17,804-episode `phase7b.v1.0` interaction corpus
  (`/mnt/.../derived/interaction_corpus/GBPUSD_phase7b_v1.jsonl`).
  Hard contract: an episode `E` is eligible at `asof` only when
  `E.episode_end_ts <= asof`. Pure Python, no AutoBot imports.
* `history_informed_shadow_observer.py` — deterministic sweeper that
  reads the primary observer's `snapshots.jsonl` and writes a separate
  `journal_shadow/analogues.jsonl`. No LLM/broker calls. Idempotent via
  byte-offset cursor plus dedup set.

### `deploy/`
* `live-market-observer.service.news-candidate` — news-enriched variant
  of the primary observer unit. ExecStart points at
  `run_observer_news.sh`; byte-identical otherwise.
* `live-market-observer-news-refresh.service` /
  `.timer` — research-only Finnhub calendar refresh (weekdays, every 30
  min between 05:00 and 21:30 UTC → 34 calls/day, well under free-tier).
  Writes to `research/live_obs/news/verified_events.jsonl` only.
* `live-market-observer-shadow.service` / `.timer` — history-informed
  shadow observer, fires every 5 min; resumable sweeper.

### `bin/`
* `run_shadow_observer.sh` — wrapper used by the shadow service unit.

### `tests/`
* `test_historical_episode_memory.py` — 14 cases covering corpus load,
  bucket edges, approach mapping, leak-freedom at four asofs, UTC-only
  guard, and genuine retrieval against the live journal.
* `test_history_informed_shadow_observer.py` — 6 cases covering journal
  disjointness, primary-journal preservation during sweep, idempotency,
  and whole-sweep leak-freedom.

Full observer suite: **73/73 passing** (53 pre-existing + 20 new).

## Hard contracts (invariants)

1. No trading services modified or restarted. `trades-api.service` and
   `autobot.service` remain `active`.
2. One primary observer only. `live-market-observer.service` is
   `inactive` and `static`; no stray `live_market_observer_agent*.py`
   processes exist.
3. The read-only dashboard
   `live-market-observer-dashboard.service` stays up throughout.
4. Historical memory cannot access future outcomes during live
   assessment. Both the module and its tests enforce
   `episode_end_ts <= asof`.
5. News updates preserve point-in-time timestamps (`known_at_utc`) and
   provenance (`source=finnhub`, `event_id`). Later revisions append
   new rows; they never overwrite earlier `known_at_utc`.
6. Trading execution remains disabled. `NEWS_STRATEGY_ENABLED=0` was
   not changed; the research Finnhub refresher is the observer's
   independent path to the same raw calendar data.
7. The shadow journal cannot share state with the primary journal —
   `_ensure_disjoint` rejects any path at or beneath the primary
   journal directory.

## Operator commands (sudo required)

```bash
# 1 — install news-enriched primary observer (do NOT start today)
sudo cp /etc/systemd/system/live-market-observer.service \
        /etc/systemd/system/live-market-observer.service.pre-news-ROLLBACK
sudo install -o root -g root -m 0644 \
    /mnt/volume_lon1_1778405456698/research/live_obs/deploy/live-market-observer.service.news-candidate \
    /etc/systemd/system/live-market-observer.service
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/live-market-observer.service

# 2 — install research-only Finnhub refresh timer (enable + start)
sudo install -o root -g root -m 0644 \
    /mnt/volume_lon1_1778405456698/research/live_obs/deploy/live-market-observer-news-refresh.service \
    /etc/systemd/system/live-market-observer-news-refresh.service
sudo install -o root -g root -m 0644 \
    /mnt/volume_lon1_1778405456698/research/live_obs/deploy/live-market-observer-news-refresh.timer \
    /etc/systemd/system/live-market-observer-news-refresh.timer
sudo systemctl daemon-reload
sudo systemctl enable --now live-market-observer-news-refresh.timer

# 3 — install history-informed shadow observer timer (enable + start)
sudo install -o root -g root -m 0644 \
    /mnt/volume_lon1_1778405456698/research/live_obs/deploy/live-market-observer-shadow.service \
    /etc/systemd/system/live-market-observer-shadow.service
sudo install -o root -g root -m 0644 \
    /mnt/volume_lon1_1778405456698/research/live_obs/deploy/live-market-observer-shadow.timer \
    /etc/systemd/system/live-market-observer-shadow.timer
sudo systemctl daemon-reload
sudo systemctl enable --now live-market-observer-shadow.timer

# 4 — tomorrow's London session (operator)
#    starts the primary (news-enriched) observer at ~07:00 UK
sudo systemctl start live-market-observer.service
```

Rollback (if the news-enriched unit misbehaves tomorrow): restore
`/etc/systemd/system/live-market-observer.service.pre-news-ROLLBACK` and
`sudo systemctl daemon-reload`.
