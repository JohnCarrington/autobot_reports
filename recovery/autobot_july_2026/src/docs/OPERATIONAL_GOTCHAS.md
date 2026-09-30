# Operational Gotchas

A running log of operational pitfalls encountered during development on
`/opt/tradingbot`. Each entry is a specific problem we already tripped on
once — future sessions should read this before starting work to avoid
repeating the same debug cycle.

Entry format:

- **Date encountered** — when it happened
- **Symptom** — how it manifested (logs, Telegram, chart, test output)
- **Root cause** — what was actually wrong
- **Fix** — what we did
- **Prevention** — what to do differently next time

Newest entries go at the top.

---

## ENTRY 1 — Root-owned files under `/opt/tradingbot/`

- **Date encountered**: 2026-04-21
- **Symptom**: `autobot.service` failed the DAILY_DOUBLE callback
  registration on first restart (PID 289113). Journal showed
  `[AUTOBOT] Could not register DAILY_DOUBLE hooks: [Errno 13]
  Permission denied: '/opt/tradingbot/logs/daily_double.log'`. BB_REVERSAL
  registrations succeeded, so the service stayed up — but DAILY_DOUBLE was
  silently disabled.
- **Root cause**: The log file was created during investigation as the
  `root` user (or via `sudo` / tool invocations that don't drop to
  `autobot`). `autobot.service` runs as `autobot:autobot` and cannot
  write to root-owned files.
- **Fix**:
  ```
  chown autobot:autobot /opt/tradingbot/logs/daily_double.log \
                        /opt/tradingbot/daily_double.py
  systemctl restart autobot.service
  ```
- **Prevention**: When creating files under `/opt/tradingbot/` during
  investigation, always run as the `autobot` user or `chown` immediately.
  Watch for:
  - `.log` files in `logs/`
  - `.json` state files in `cache/`
  - Any new `.py` module
  - Files produced by ad-hoc Python scripts run as root
  A safe-by-default idiom: prefix investigation commands with
  `sudo -u autobot` when they create persistent state. Alternatively,
  after any investigation touching these directories, run
  `find /opt/tradingbot -user root -not -path '*/.git/*' -not -path
  '*/.claude/*' -not -path '*/.pytest_cache/*'` to catch stragglers.

---

## ENTRY 2 — Briefing training corpus permissions

- **Date encountered**: pre-April 2026 (referenced in prior context)
- **Symptom**: Briefing training corpus silently failed to write for an
  extended period. Zero records accumulating when records should have
  been building every briefing cycle.
- **Root cause**: Permission issue on the corpus directory — same class
  of problem as Entry 1 (autobot user couldn't write).
- **Fix**: Corrected directory permissions. Corpus at ~376 records as
  of mid-April 2026.
- **Prevention**: Add a sanity check on bot startup — attempt a write
  to the corpus directory (e.g. a `.probe` file with current ts) and
  emit a `WARNING` if it fails. A silent-fail mode is the worst kind
  of bug for data pipelines.

---

## ENTRY 3 — Bot restart loses 3CO for the rest of the day

- **Date encountered**: ongoing pattern
- **Symptom**: Restarting the bot after 06:00 UTC on any trading day
  locks 3CO out for the rest of that day. 3CO evaluates every tick but
  reports "past early-session window" every time.
- **Root cause**: 3CO's `candle_index` state is in-memory and does not
  persist across restarts. On restart, the counter is re-derived from
  the number of bars cached since session open — if that exceeds
  `THREE_CO_EARLY_WINDOW_CANDLES` (24), 3CO's window-open check fails
  for the rest of the day.
- **Fix**: No code fix yet. Workarounds:
  - Restart before 06:00 UTC if 3CO activity is wanted for that day.
  - Accept 3CO lockout if an urgent mid-session restart is required.
- **Prevention**: Avoid mid-session restarts when possible. Outstanding
  work item: make 3CO re-evaluable on restart — either persist
  `candle_index` to disk, or switch to a wall-clock-based window check
  (e.g. "within 120 minutes of session open" rather than counting bars).

---

## ENTRY 4 — IG SL sanitisation silently doubles the announced SL

- **Date encountered**: observed 2026-04-20 23:55 GBPUSD trade
- **Symptom**: Telegram message announced `SL=+6 pips`. Actual SL
  placed on IG (verified in executor logs and on IG UI) was `+12 pips`.
  Trader checking the announcement thinks the position has a tighter
  stop than it actually does.
- **Root cause**: IG broker minimum SL distance is 12 pips on GBPUSD
  (`_IG_MIN_STOP_PTS["GBPUSD"] = 12`). `trade_executor._sanitize_distance`
  silently raises any smaller SL to the broker minimum before submission.
  The Telegram announcement fires before sanitisation and uses the
  requested SL from the strategy decision, not the sanitised value.
- **Fix**: None yet. Functional behaviour is correct (broker wouldn't
  accept a smaller SL), but the UX is misleading.
- **Prevention**: When debugging SL-related issues, trust the executor
  log lines, not the Telegram message. The authoritative value is in:
  ```
  journalctl -u autobot.service | grep -E "EXECUTE_TRADE.*sl_pips|submitted SL"
  ```
  Outstanding work item: route the sanitised SL back through to the
  Telegram announcement so the message matches what's actually at IG.

---

## ENTRY 5 — TP bid-basis announcement vs ask-basis fill mismatch

- **Date encountered**: observed 2026-04-20 23:55 GBPUSD trade — chart
  showed bid touching the announced TP, but the position didn't close
- **Symptom**: Telegram announces TP at a price level. On the chart,
  the bid line reaches that level — but the trade doesn't fill. The
  ask (and the executed fill price for a SELL close) stayed 1-2 pips
  above the announced TP.
- **Root cause**: Announcements use bid-basis levels. For SELL closes,
  IG executes at ask, so ask must reach the TP level to fill. Spread
  (bid-ask gap) means ask lags the bid by the spread width. On
  tight-TP trades, the bid can touch the announced TP while the ask
  stays above it, leaving the trade unfilled.
- **Fix**: None yet — awaiting a spread-aware TP messaging rework.
- **Prevention**: Be aware that "TP touched on chart" (bid-basis) ≠
  "TP filled on IG" (ask-basis) especially on tight-TP trades (< 15p).
  When investigating apparent near-misses, pull the executor log for
  actual ask prices at the time the chart showed the bid touching:
  ```
  journalctl -u autobot.service | grep -E "<PAIR> ask=" | awk -F'ask=' '{print $2}'
  ```

---

## ENTRY 6 — Working-tree drift on `main` branch

- **Date encountered**: 2026-04-21 morning
- **Symptom**: `main` had ~56 lines of uncommitted changes including
  Group C .env edits, the `histdata-decimal-output.py` tool, and
  strategy disables. Any `git checkout` to a new branch would have
  either carried the changes forward or been prompted for stash.
- **Root cause**: Changes made during prior investigations were
  committed piecemeal, some left uncommitted on `main`. Sessions ended
  without a clean-up pass.
- **Fix**: Committed in a clean-up round during morning deploys.
- **Prevention**: At the start of every session, run:
  ```
  git -C /opt/tradingbot status --short
  ```
  Commit or stash any modified-tracked-files before starting new branches.
  Add this as a "start of session" step alongside reading any relevant
  memory / prior-session notes.

---

## ENTRY 7 — Systemd service restart clears in-memory state

- **Date encountered**: ongoing pattern
- **Symptom**: Several strategies have in-memory state that doesn't
  survive restarts. Specifically:
  - Pre-DAILY_DOUBLE: window-fired flags were lost, allowing duplicate
    entries in the same window after a restart.
  - BB_REVERSAL post-SL cooldown state.
  - Per-event NEWS_TICK dedup set (now persisted).
  - 3CO `candle_index` (see Entry 3).
- **Root cause**: State stored only in Python process memory. Restart
  reinitialises to defaults.
- **Fix**: DAILY_DOUBLE persists via
  `cache/daily_double_window_state.json` with startup reconcile. Other
  state not yet persisted.
- **Prevention**: When adding new strategy state, default to disk
  persistence via the `cache/` directory. Pattern:
  1. Write atomically — `tempfile` + `os.rename` to avoid partial
     writes if the process dies mid-flush.
  2. Rotate at UTC-midnight or whatever the natural scope is.
  3. On startup, compare disk state with broker state via
     `EPIC_STATE` / RECONCILE. If state says "position open" but no
     matching broker position exists, reset to a safe default (this
     is what `_reconcile_startup_state` does in `daily_double.py`).

---

## ENTRY 8 — Reconcile + suffixed pos_keys from pyramiding

- **Date encountered**: observed 2026-04-21
- **Symptom**: BB_REVERSAL pyramid positions have pos_keys with
  millisecond-timestamp suffixes, e.g.:
  ```
  CS.D.GBPUSD.TODAY.IP|BB_REVERSAL_1744123456789
  ```
  These don't match the canonical `CS.D.GBPUSD.TODAY.IP|BB_REVERSAL`
  format. Grep queries that use exact-match on `BB_REVERSAL` miss
  pyramid entries.
- **Root cause**: Intentional. The pyramid exemption in
  `trade_executor.py:497-506` suffixes the pos_key with
  `time.time()*1000` for each concurrent BB_REVERSAL entry so
  `EPIC_STATE` can hold multiple positions on the same epic+mode.
- **Fix**: Not a bug — by design. `RECONCILE` handles suffixed keys
  correctly via prefix matching.
- **Prevention**: When grepping for BB_REVERSAL positions in logs,
  `EPIC_STATE`, or signal logs, **use prefix match, not exact match**.
  Patterns:
  ```python
  # correct — catches BB_REVERSAL and BB_REVERSAL_<ts>
  if pos_key.startswith(f"{epic}|BB_REVERSAL"):
      ...
  # wrong — misses all pyramided entries
  if pos_key == f"{epic}|BB_REVERSAL":
      ...
  ```
  In journalctl greps, use `grep "|BB_REVERSAL"` rather than
  `grep "BB_REVERSAL$"`. If BB_REVERSAL pyramiding is ever removed,
  this distinction goes away — but until then, assume suffixed keys
  are out there.

---

## HOW TO ADD NEW ENTRIES

When a new operational gotcha is encountered, add an entry with the
6-field structure above (Date, Symptom, Root cause, Fix, Prevention).
New entries go at the top (newest first) and bump the entry number in
the existing entries up by one.

Keep entries **specific and actionable** — generic advice belongs in
`README.md` or module docstrings, not here. The value of this file is
the specific-problem-specific-fix pattern. If an entry isn't
reproducible or doesn't have a clear fix / prevention step, it's
probably noise and should be left out.

If an entry becomes stale (the underlying issue is fixed in code and
no longer reachable), leave the entry but append a `**RESOLVED <date>:
<commit sha or PR>**` line so the reader can tell it's no longer live.
Do not delete — the prevention advice may still be useful context when
a similar-shape bug appears.
