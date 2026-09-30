# RUNBOOK

Operational procedures for the AutoBot estate.

Hosts:
- **161** — `161.35.168.61`, primary trading host. Runs `autobot.service`
  (engine) + `trades-api.service` (dashboard backend on 8080) + nginx
  proxy on 3000, plus the timer-driven oneshots enumerated in
  `systemctl list-timers`. All units run as `autobot`.
- **144** — secondary host (see commit `9a3d8ae` for the auth-flood
  incident that named it). Runs its own `autobot.service`. Not directly
  accessible from a 161 session; every 144 command in this document
  is prefixed `ssh autobot@144` and MUST be re-verified from the
  operator's terminal, not assumed.

Each section below is distilled from a specific incident. Cite lines
point at commits and `reports/*.md` — read the source before deviating
from the procedure.

## Header rule (READ BEFORE EDITING THIS FILE)

**This file is updated IN THE SAME COMMIT as any change that alters an
operational procedure.** A code change that renames a systemd unit,
adds a credential-holding process, moves an env var, changes a restart
gate, or adjusts a verify signal is not complete until the affected
section here is updated and both changes land together. A single
commit is the enforcement mechanism — reviewers reject procedure-
touching PRs that leave the RUNBOOK stale.

Two consequences follow:

1. If you cannot describe the operator-visible effect of a change in
   RUNBOOK terms, the change is not ready to merge.
2. If the RUNBOOK cites `file:line` or `commit-sha` that no longer
   exists in tree, that is a bug in a PRIOR commit — fix it in the
   same PR that surfaces it. Don't leave rot for the next reader.

---

## 1. IG API KEY ROTATION

**Lesson:** `trades-api.service` ran for six days holding a rotated-away
IG API key while `autobot.service` had already picked up the new key.
The dashboard's spine (IG `/history/transactions`) returned HTTP 403
`error.security.api-key-disabled` on every fire, falling back silently
to the local `signal_log.jsonl`. Visible in the journal from at least
2026-07-27 21:41:43 UTC and diagnosed at 2026-07-28 (see
`reports/cc_journal_email_dashboard_20260727.md` FAULT 2, and the
first-hit line quoted in `reports/cc_ungated_closers_20260728.md`).
Root cause: `EnvironmentFile=/opt/tradingbot/.env` is read ONCE at
`systemctl start`; a running Python process holds the values it saw at
boot in `os.environ` and never re-reads the file. Restarting autobot
alone does not restart trades-api.

**Procedure — rotate an IG API key:**

1. **Rotate in the IG Console.**
   `https://labs.ig.com/webapicompanion` → app management → generate
   new key. Old key is invalidated the moment the new key is saved.
2. **Update `.env` on 161 AND 144.**
   On 161: edit `/opt/tradingbot/.env` line for `IG_API_KEY=` in place.
   Do NOT `sed` blindly — see section 3 for the .env-change protocol
   (snapshot first, verify flag name against code, restart, verify via
   `/proc/<pid>/environ`).
   On 144: `ssh autobot@144` and repeat.
3. **Restart every long-lived Python process that holds the key.**
   On 161 (both units must be bounced — the second is the trap):
   ```
   sudo systemctl restart autobot.service
   sudo systemctl restart trades-api.service
   ```
   On 144:
   ```
   ssh autobot@144 sudo systemctl restart autobot.service
   ```
   The oneshot timers on 161 (`daily-journal`, `eod-review-*`,
   `health-check`, `health-digest`, `rest-allowance-snapshot`,
   `v5-comparison-capture`, `forensic-backfill`, `news-*`,
   `briefing-validation`, `fires-watchdog`) re-read `.env` at each
   fire and do NOT need explicit restarts. See section 6 for the full
   consumer inventory.
4. **Verify — spine 200 in trades-api journal, no api-key-disabled.**
   ```
   journalctl -u trades-api.service --since '2 min ago' \
     | grep -E 'spine|api-key-disabled'
   ```
   Expected: `INFO GET '/history/transactions', resp 200` on next fire
   (within ~60s given the trades-api cache). Any occurrence of
   `error.security.api-key-disabled` after the restart timestamp means
   the restart did not take — check `systemctl show trades-api.service
   --property=ExecMainStartTimestamp` against the log entry's clock.
   Also verify autobot log-in on 161 + 144:
   ```
   journalctl -u autobot.service --since '2 min ago' \
     | grep -E 'IG_AUTH|created session|error.security'
   ```
5. **Also verify env delivered to the running processes** (belt-and-
   braces — section 3 style):
   ```
   for pid in $(pgrep -f autobot.py) $(pgrep -f trades_api.py); do
     printf 'pid=%s: ' "$pid"
     tr '\0' '\n' </proc/$pid/environ | grep -E '^IG_API_KEY=' \
       | cut -c1-20  # first 20 chars only — do not log the full key
   done
   ```

**Why it took six days to notice:** the trades-api fallback is silent
by design. The dashboard still renders trades (from `signal_log.jsonl`)
even when IG's spine is dead, and the WARN log line is per-fire, not
alerting. If you rotate a key, assume the operator-visible signal
alone is not enough — verify every consumer.

Sources: `reports/cc_journal_email_dashboard_20260727.md` §2b;
`reports/cc_ungated_closers_20260728.md`; commit `4ad798e` (trades-api
LIVE/DEMO env toggle) for the earlier lineage.

---

## 2. IG AUTH FAILURE — STOP FIRST, DO NOT RESTART-LOOP

**Lesson:** on 2026-07-10 09:26–14:30 UTC, a graceful `autobot`
restart returned HTTP 401 `error.security.client-suspended`. The
service unit's `Restart=always` `RestartSec=5` then queued ~2,500
further login attempts over five hours, which entrenched the
suspension into IG's anti-fraud lockout. On 2026-07-22 a related
defect in `refresh_session` cleared the in-process cache before the
re-auth attempt, so every subsequent caller
(`get_open_positions`x6, SL-amend, LS recovery) fired a fresh
`create_session()` cascade — measured at ~68 failed logins per 30 min
on host 144.

Two systemd + code protections landed. Do NOT undo either without
routing through the incident review:

- `RestartPreventExitStatus=78` in
  `/etc/systemd/system/autobot.service.d/auth-suspension-guard.conf`
  pairs with `ig_auth.FATAL_AUTH_EXIT_CODE=78`. When `ig_auth`
  classifies a 401 as `error.security.client-suspended`, the process
  exits 78 and systemd MUST NOT relaunch it. `RestartSec=30s` raises
  the outer floor for non-auth crashes. Contract is pinned by
  `tests/unit/test_ig_auth.py::test_fatal_exit_code_matches_unit` —
  the test fails if the drop-in and the code drift apart.
- `refresh_session` rate-limit + in-flight guard
  (commits `9a3d8ae`, `9f899e6`). Prior cache is restored on any
  failure; only one refresh attempt per `AUTH_REFRESH_MIN_INTERVAL_S`
  (default 60s); a concurrent second caller short-circuits to the
  prior cache instead of stacking a second backoff ladder.

**Procedure — 401 / auth failure appears in the journal:**

1. **STOP FIRST. Never restart-loop.**
   ```
   sudo systemctl stop autobot.service
   ```
   The systemd guard exits the process on `client-suspended` with 78
   and blocks re-launch, but stop the unit anyway so you can diagnose
   without racing the ordinary `Restart=` cycle for non-fatal 401s.
2. **Diagnose with READS ONLY. Do not re-login, do not curl IG, do
   not run the health-check timer manually.** Every extra login
   attempt lengthens an IG lockout.
   ```
   journalctl -u autobot.service --since '30 min ago' \
     | grep -E 'IG_AUTH|error.security|create_session|refresh_session'
   ```
   Classify the error string:
   - `error.security.client-suspended` — **terminal**. Go to
     the IG web UI, log in as `REDACTED_IG_USERNAME`, satisfy whatever anti-
     fraud step IG surfaces (2FA, security questions). Do NOT
     restart the service until you have logged in successfully on
     the web and confirmed the account is not locked.
   - `error.security.oauth-token-invalid` /
     `error.security.invalid-details` — non-fatal but rate-limited
     by the 60s throttle. Confirm `.env` credentials match the
     Console (`IG_USERNAME`, `IG_PASSWORD`, `IG_API_KEY`,
     `IG_ACC_TYPE`). If credentials look correct, wait for the
     backoff ladder (30/60/120/240/300s) to settle before touching
     anything.
   - `error.security.api-key-disabled` — key was rotated on IG
     side. Go to section 1.
3. **Only after IG-side lockout is cleared, restart:**
   ```
   sudo systemctl start autobot.service
   journalctl -u autobot.service --since '1 min ago' \
     | grep -E 'IG_AUTH|created session|error.security'
   ```
   First expected log line: `[IG_AUTH] created session (attempt=1)`.
   If a fresh `client-suspended` appears, STOP the service again and
   go back to step 2 — IG will not have re-cleared the lockout.

Sources: `/etc/systemd/system/autobot.service.d/auth-suspension-guard.conf`
(header comment, in-tree at
`deploy/systemd/autobot.service.d-auth-suspension-guard.conf`); commit
`db08493` (401 classification); commits `9a3d8ae`, `9f899e6`
(refresh_session hardening); `tests/unit/test_ig_auth.py`.

---

## 3. .ENV CHANGE

**Lesson:** the `.env` file at `/opt/tradingbot/.env` is the sole
`EnvironmentFile=` for `autobot.service` and `trades-api.service`, and
is edited by hand or by ad-hoc `sed`. Two failure modes have hit us:

1. **Sed-scripted overwrite dropped a flag** — the TRADE_SIZE rewrite
   on 2026-07-27 09:50 UTC blasted through the file with a template
   the operator was maintaining separately, silently removing
   `DAILY_JOURNAL_EMAIL_ENABLED` and any other flag not in the
   template (see `reports/cc_journal_email_dashboard_20260727.md`
   fault-1 fix-status note). The bot kept running; a downstream
   feature just stopped firing.
2. **Caret-prefixed value ("^") from a bad paste or editor artifact**
   made the loader emit values that Python code then failed to parse.
   `env-history` snapshots taken pre- and post-boot let us diff the
   two files and see the malformation without a strict schema check.

Two guards landed and MUST remain wired:

- `env-history.conf` drop-in — `ExecStartPre` snapshots `.env` into
  `/opt/tradingbot/env-history/env.<UTC-timestamp>` on every start,
  retaining the newest 60. Snapshots are the authoritative record
  of what was actually delivered to the process at boot.
- `env-drift.conf` drop-in — `ExecStartPre` runs
  `scripts/env_drift_check.py`, which diffs the two most-recent
  snapshots and emits ONE Telegram containing variable NAMES only
  (never values), capped at 15 per category. Body wrapped so any
  failure logs and exits 0 — must not block boot. Commit `f03dc6a`
  is the reference.

**Procedure — any `.env` change:**

1. **Snapshot before touching.** The `env-history` drop-in does this
   at boot, but do it explicitly before edit-then-restart so you have
   the delta unambiguously:
   ```
   cp /opt/tradingbot/.env \
      "/opt/tradingbot/env-history/env.pre.$(date -u +%Y%m%dT%H%M%SZ)"
   ```
2. **Verify the flag NAME against code before you sed.** The env-drift
   check catches only presence/absence — a typo that renames
   `TRADE_SIZE` to `TRADE_SIZES` produces a silent default fall-back,
   not an alert. Grep the code readers first:
   ```
   grep -rnE "os\.getenv\(['\"]FLAG_NAME['\"]" /opt/tradingbot/*.py \
     /opt/tradingbot/scripts/*.py
   ```
   If no reader matches, either the flag is dead or you have the name
   wrong. Fix the name; do not add a dead flag.
3. **Edit `.env`.** Preserve `600 autobot:autobot` mode (the .env
   change process runs as the `autobot` user, so the mode is
   preserved automatically — but check after any `sudo` edit).
4. **Restart the consumers.** For flags read by autobot:
   ```
   sudo systemctl restart autobot.service
   ```
   For flags also read by trades-api (any `IG_*`, `TRADES_API_*`,
   `DASHBOARD_*`, or auth-related var — most `.env` changes fall
   into this bucket):
   ```
   sudo systemctl restart trades-api.service
   ```
   Timer oneshots re-read `.env` at each fire — no action needed
   unless the change is urgent.
5. **VERIFY via `/proc/<pid>/environ`. NEVER TRUST THE FILE ALONE.**
   The file has the new value; the process may not.
   ```
   pid=$(pgrep -f autobot.py | head -1)
   tr '\0' '\n' </proc/$pid/environ | grep '^FLAG_NAME='
   ```
   Repeat for `trades_api.py` PID if that consumer was restarted.
   An empty result means the process did not pick up the change —
   the restart did not happen, or the flag name is misspelled in
   `.env`, or the file wasn't saved.
6. **Watch for the drift Telegram.** If the two most-recent
   `env-history/env.*` snapshots differ, one alert lands per boot
   with the NAMES of added/removed/changed variables. Zero-alert on
   an intended change means the drift check failed silently — read
   `logs/env_drift.log` (`f03dc6a` sends failures there, exit 0).

Sources: `reports/cc_journal_email_dashboard_20260727.md` (TRADE_SIZE
sed-overwrite note); commit `f03dc6a` (env-drift check); the
`autobot.service.d/env-history.conf` + `env-drift.conf` drop-ins.

---

## 4. ADDING A PAIR

**Lesson:** ticks from IG are subscription-shared across all
subscribed epics. Adding a pair dilutes the per-bar tick count for
every other pair on the same subscription tier, and if the aggregate
starves any pair below the bar-quality floor, downstream 5m-close
consumers (`bb_bounce`, `ema_pullback`, `structure_break`,
`bar_quality_check`) get quiet-hours-shaped junk without the sizing
math being aware. The 2026-07-23 dilution event is what forced the
bar-quality floor to ship on 2026-07-25 (commit `1aa5da7`).

The floor is watch-and-shout only: it emits a `WARNING` per starved
bar and ONE Telegram after `BAR_QUALITY_ALERT_CONSEC` (default 6)
consecutive starved bars per pair, with cooldown
`BAR_QUALITY_ALERT_COOLDOWN_MIN` (default 60 min). Quiet hours
22–06 UTC and weekends are exempt. It does NOT gate entries or scale
back subscriptions.

**Procedure — add a pair:**

1. **One at a time.** Edit `EPICS_JSON` in `.env` to add the single
   new epic (line 27 today: `EPICS_JSON={"GBPUSD":"CS.D.GBPUSD.TODAY.IP",...}`).
   Follow section 3 for the .env-change protocol (snapshot,
   verify, restart, `/proc/<pid>/environ`). Restart autobot only —
   `trades-api` reads instruments from IG on demand.
2. **Watch `[BAR-QUALITY]` a full session before the next pair.**
   ```
   journalctl -u autobot.service --since 'today' \
     | grep '\[BAR-QUALITY\]'
   ```
   Expected first-week state: near-zero starved-bar warnings during
   London + NY (06–20 UTC weekdays); some starved bars are fine in
   Asia, they are exempt from Telegram alerts.
   Cross-check every previously-live pair: dilution manifests as an
   uptick on the *existing* pair, not the new one.
3. **If any pair emits the BAR_QUALITY Telegram in the first
   session**, back the add out (revert `.env`, restart), and
   re-plan. Dilution is not something we tolerate through — the
   floor is a signal, not a mitigation. See commit `1aa5da7`
   commit message: "watch-and-shout only. Reuses IG's native
   CONS_TICK_COUNT... none of these knobs gate."
4. **Only if a full session is quiet** (no `[BAR-QUALITY]` WARNs on
   any pair during 06–20 UTC) proceed to the next pair. There is no
   fixed "wait N days" — it is per-pair, based on the alert history
   for THIS pair, on THIS host.

Also update: the per-pair confidence gates, pip-size table, and
strategy allowlists that were added ad-hoc for prior pairs (see
commits `5d44f41` "EURUSD pip_size 0.1 → 1.0", `b15e496`
"Confidence gate: 0.65 for London only", `407b555` "BB_REVERSAL pair
allowlist"). None of these are auto-derived from `EPICS_JSON`; the
new pair will silently use GBPUSD numbers until a code change is
merged. That code change is IN SCOPE for the pair-add PR, not a
follow-up.

Sources: commits `1aa5da7`, `e704089`; `.env` lines 560–563
(`BAR_QUALITY_*` knobs); `candle_builder.py::_bar_quality_check`.

---

## 5. CREDENTIAL EXPOSURE

**Lesson:** on 2026-07-24, `.env.backup.20260204_200508` and
`.env.save` were found tracked in the git tree. Both contained a
full IG credential set. They had been committed months earlier and
never noticed until a routine `git ls-files` audit. Commit
`20635d5` untracked them and added `.env.backup.*` + `.env.save`
patterns to `.gitignore`. Commit `1afd64c` had previously untracked
`.env` itself. Local `.env*` backup files continue to be created by
hand and by editor autosaves — the gitignore keeps them out; nothing
else does.

**Procedure — suspected credential exposure:**

1. **Assume rotation is required.** If a credential file has been
   read by a process outside your control (git push, git clone,
   ChatGPT/Claude context, screen share, backup upload, pastebin,
   third-party CI), rotate before doing anything else. Fresh keys
   are cheap; not rotating is not.
   - IG: section 1 procedure end-to-end (rotate on Console, update
     `.env` on 161 and 144, restart autobot + trades-api).
   - Telegram bot token: revoke via `@BotFather` `/revoke`, generate
     new, update `TELEGRAM_TOKEN` in `.env` (section 3), restart
     autobot + trades-api. Existing chat_id survives.
   - SendGrid / FINNHUB / any other API key: rotate in the
     provider's console, update `.env`, restart.
2. **Untrack the offending file** and add its pattern to
   `.gitignore`. Do this even if the file was never pushed — the
   next `git add .` will re-stage it otherwise. Reference commits:
   `20635d5`, `1afd64c`.
   ```
   git rm --cached <path>
   printf '<pattern>\n' >> .gitignore
   git add .gitignore
   git commit -m 'chore: untrack <path>; rotate downstream'
   ```
3. **Verify `git ls-files` is clean before ANY push.**
   ```
   git ls-files | grep -iE '^\.env|password|secret|credential|token'
   ```
   The only expected match is `.env.example` (contents are all
   placeholder). Any other match is an unfixed exposure — do not
   push.
4. **If the file was pushed to a remote**, the credential is
   compromised even after `git rm`. Git history retains it. Rotation
   is the only fix. `git filter-repo` / BFG remove the file from
   history but do not un-expose it — treat rotation as mandatory,
   history rewriting as a hygiene follow-up.
5. **Document the exposure window** in the commit message and (if
   push happened) in an incident report under `reports/`. The
   February 2026 backup was tracked for months; the delta between
   "committed" and "detected" is the number worth capturing.

Sources: commit `20635d5` (untrack .env backups); commit `1afd64c`
(untrack .env); `.gitignore` lines 4, 115, 116.

---

## 6. KEY-ROTATION CONSUMER LIST

**Lesson:** the 2026-07-28 six-day dead-key incident (section 1)
happened because `trades-api.service` was invisible in the operator's
mental model of "autobot" — bouncing autobot didn't bounce it, and
its failure mode was silent. This section is the enumeration of
every long-lived process on this estate that reads IG or Telegram
credentials, so the next rotation does not create a new six-day
blind spot.

The rule: **a running Python process reads `.env` once at boot and
holds the values in `os.environ` for its lifetime.** Rotate ⇒
restart every process on this list. For oneshot units, `.env` is
re-read at each fire, so no explicit restart is needed — but the
`.env` file itself must be current before the next fire time
(`systemctl list-timers` to see the next fire).

### Long-lived processes (must be restarted after any credential
rotation)

| # | Host | Unit | Credentials in memory | Restart command | Verify signal |
|---|------|------|------------------------|-----------------|---------------|
| 1 | 161 | `autobot.service` | IG_USERNAME, IG_PASSWORD, IG_API_KEY, IG_ACC_TYPE, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (via `ig_auth.py`, `telegram_alerts.py`) | `sudo systemctl restart autobot.service` | `journalctl -u autobot.service --since '2 min ago' \| grep -E 'IG_AUTH.*created session\|TELEGRAM'` — expect a fresh `created session (attempt=1)` line, no `error.security.*` after the restart timestamp. |
| 2 | 161 | `trades-api.service` | IG_USERNAME, IG_PASSWORD, IG_API_KEY, IG_ACC_TYPE (via `ig_auth.py`; dashboard spine uses `/history/transactions`) | `sudo systemctl restart trades-api.service` | `journalctl -u trades-api.service --since '2 min ago' \| grep -E 'spine\|api-key-disabled'` — expect `resp 200` on the next spine fire (~60s cache); ANY `error.security.api-key-disabled` after restart timestamp means the restart did not take. |
| 3 | 144 | `autobot.service` | Same as (1). Referenced by commit `9a3d8ae` ("~68 failed logins per 30min on host 144"). | `ssh autobot@144 sudo systemctl restart autobot.service` | `ssh autobot@144 journalctl -u autobot.service --since '2 min ago' \| grep 'IG_AUTH'` — expect fresh `created session (attempt=1)`. |

### Oneshot timer-fired scripts (re-read `.env` at each fire — no
restart needed, but the `.env` must be current before the next fire)

| Unit | Timer cadence | Credentials read on fire |
|------|---------------|--------------------------|
| `daily-journal.service` | 21:00 UTC daily | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `SENDGRID_API_KEY`, `EMAIL_FROM`, `EMAIL_TO`/`JOURNAL_EMAIL_TO` (via `daily_journal.py`; no direct IG use). |
| `eod-review-metrics.service` | 22:05 UTC daily | Reads `.env` for feature flags; no direct credential use in `scripts/eod_review_metrics.py`. |
| `eod-review-narrative.service` | 22:20 UTC daily | Reads `.env` for feature flags; no direct credential use in `scripts/eod_review_narrative.py`. |
| `eod-review-backup.service` | 22:35 UTC daily | Shell script (`scripts/eod_review_backup_local.sh`); no credentials. |
| `health-check.service` | every 5 min | Reads `.env`; posts via `telegram_alerts` (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID). |
| `health-digest.service` | HH:00 UTC | Reads `.env`; posts via `telegram_alerts`. |
| `rest-allowance-snapshot.service` | 00:05 UTC daily | Reads `.env`; no direct IG/Telegram use in `scripts/rest_allowance_daily_snapshot.py`. |
| `v5-comparison-capture.service` | 12:30 + 21:30 UTC | Reads `.env`; no direct IG use in `scripts/v5_pia_comparison_capture.py`. |
| `forensic-backfill.service` | HH:05 UTC hourly | No `EnvironmentFile=`; no direct credential use in `scripts/forensic_outcome_backfill.py`. |
| `briefing-validation.service` | Mon–Fri 05:35 UTC | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (via `scripts/validate_briefing.py`, reads `.env` directly). |
| `news-calendar.service` | timer disabled today; when enabled: 4h weekdays | `FINNHUB_API_KEY` (via `scripts/refresh_news_calendar.py`). |
| `news-momentum-obs.service` | (see `systemctl list-timers`) | Reads `.env`; observer-only. |
| `fires-watchdog.service` | (see `systemctl list-timers`) | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` (via `telegram_alerts.py` import). |
| `autobot-start.service` / `autobot-stop.service` | Sun 21:00 / Fri 22:00 UTC | Systemctl wrapper only; no credentials. |

### Ad-hoc scripts that use `ig_auth` (NOT wired to any systemd
unit — the operator must ensure `.env` is current before manual
invocation)

`scripts/backfill_daily_candles.py`, `scripts/daily_reconcile.py`,
`scripts/shadow_audit.py`. Grep: `grep -lE 'from ig_auth|import
ig_auth' /opt/tradingbot/scripts/*.py`.

### The whole-estate verify pass

After any rotation, one command block confirms both long-lived
consumers see the new key:

```
for pid in $(pgrep -f autobot.py) $(pgrep -f trades_api.py); do
  ts=$(stat -c '%Y' /proc/$pid)
  echo "pid=$pid started=$(date -u -d @$ts +%FT%TZ)"
  tr '\0' '\n' </proc/$pid/environ | grep -E '^IG_API_KEY=' | cut -c1-20
done
journalctl -u autobot.service -u trades-api.service --since '5 min ago' \
  | grep -E 'IG_AUTH|api-key-disabled|created session'
```

Add the 144 host's equivalent under `ssh autobot@144 …`.

**Refresh this section whenever a new long-lived process is added or a
timer script starts using a credential.** Per the header rule, the
commit that adds the process is not complete until this table
reflects it.

Sources: `systemctl list-units --type=service`, `systemctl
list-timers`, `/etc/systemd/system/*.service`, `grep -lE
'IG_API_KEY\|IG_USERNAME\|IG_PASSWORD' /opt/tradingbot/*.py
/opt/tradingbot/scripts/*.py`, `grep -lE
'TELEGRAM_TOKEN\|TELEGRAM_CHAT_ID' …`, `grep -lE 'from ig_auth\|import
ig_auth' …`.
| 4 | 178 | fxi-producer (timer oneshots, London 05:30 / NY 12:30 UTC) | Z3G4CI IG creds + ANTHROPIC_API_KEY + SendGrid + Telegram, re-read per fire from /opt/fxi-producer/.env — file must be current before next fire; no restart needed | — | run_session.jsonl status=ok, no auth errors |
