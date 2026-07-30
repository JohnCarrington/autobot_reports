# [T0b] Name scrub — signed-off blocked-class changes

**Date:** 2026-07-30
**Branch:** `fix/briefing-first-unblock`
**Identity:** AutoBot-FXi <autobot@autobot-fxi.local>
**Predecessor:** `[T0]` 7efa3f6 (internal-only identifier scrub)

The changes below live outside the git tree (`/etc`, and a gitignored
`.claude/` file), so this note is the in-repo record of what was done.
Rollback copies are under `/root/*.bak.20260730_*`.

## 1. nginx dashboard — renamed + realm changed, reloaded

```
/etc/nginx/sites-available/<legacy>-dashboard  ->  /etc/nginx/sites-available/fxi-dashboard
/etc/nginx/sites-enabled/<legacy>-dashboard    ->  /etc/nginx/sites-enabled/fxi-dashboard
                                              (symlink re-pointed, not just renamed)
```

```diff
--- /root/<legacy>-dashboard.bak.20260730_201753
+++ /etc/nginx/sites-available/fxi-dashboard
@@ -2,7 +2,7 @@
     listen 144:3000;
     server_name _;

-    auth_basic "<Legacy> Dashboard";
+    auth_basic "FXi Dashboard";
     auth_basic_user_file /etc/nginx/.htpasswd_dashboard;
```

Validation and reload:

```
$ sudo nginx -t
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful

$ sudo systemctl reload nginx     # OK, nginx active
$ curl -o /dev/null -w "%{http_code}" http://144:3000/
401                               # basic-auth still enforced
$ curl -sI http://144:3000/ | grep -i www-authenticate
WWW-Authenticate: Basic realm="FXi Dashboard"
```

## 2. systemd unit Descriptions — edited, NOT reloaded

No `daemon-reload` was issued; these ride the final restart at the end of
the session. `systemctl` therefore still reports the old Description and
prints the expected "unit file changed on disk" warning until then.

```diff
--- /etc/systemd/system/autobot.service
-Description=AutoBot-<Legacy> FX trading bot (<LEGACY>_FIRST only)
+Description=AutoBot-FXi FX trading bot

--- /etc/systemd/system/premarket-health.service
-Description=<LEGACY>_FIRST premarket healthcheck
+Description=FXi briefing premarket healthcheck

--- /etc/systemd/system/premarket-health.timer
-Description=<LEGACY>_FIRST premarket healthcheck timer
+Description=FXi briefing premarket healthcheck timer
```

The `(<LEGACY>_FIRST only)` qualifier was dropped rather than translated: it was
already factually stale, since the legacy briefing-first path is disabled on this box and
BRIEFING_EXECUTION is the live path.

## 3. `.claude/settings.local.json` — 14 dead allow-entries pruned

`permissions.allow`: 648 -> 634. All 14 were one-shot historical grants
(git-log/sed invocations against files that no longer exist, plus
`cat /etc/nginx/sites-available/<legacy>-dashboard`). File is gitignored
(`.gitignore:11 *.json`) so it is not part of this commit; JSON revalidated
after the edit.

## 4. CHECK — write-side `schema_version` (PASS, no action)

The writer emits `v5_fxi`. The `v5_<legacy>` literal is read-side back-compat only.

```
briefing/v5_fxi/orchestrator.py:109:        schema_version          = "v5_fxi",
briefing/v5_fxi/orchestrator.py:255:        schema_version          = "v5_fxi",
briefing/v5_fxi/confidence_scorer.py:564:            "schema_version": "v5_fxi.scorer.v1",
briefing/v5_fxi/confidence_scorer.py:631:        "schema_version":      "v5_fxi.scorer.v1",
```

Newest artifacts on disk (2026-07-30 12:39 UTC, NY session) confirm it:

```
briefings/v5_fxi/briefing_USDCAD_2026-07-30_NY.json:  "schema_version": "v5_fxi",
                                                        "schema_version": "v5_fxi.scorer.v1",
briefings/v5_fxi/briefing_EURUSD_2026-07-30_NY.json:  "schema_version": "v5_fxi",
briefings/v5_fxi/briefing_USDJPY_2026-07-30_NY.json:  "schema_version": "v5_fxi",
```

## 5. CHECK — `v5_<legacy>_comparison.jsonl` (DORMANT, left alone)

The output file does not exist, and the scripts have no callers:

```
$ ls -l logs/v5_<legacy>_comparison.jsonl
ls: cannot access 'logs/v5_<legacy>_comparison.jsonl': No such file or directory
$ grep -rln "v5_fxi_comparison" .              # excl .git/venv
(no matches outside the two scripts themselves)
$ grep -rn "comparison" /etc/systemd/system/ /etc/cron*   -> none
$ crontab -l                                             -> no crontab for autobot
```

`scripts/v5_fxi_comparison_{capture,analyze}.py` are fully dormant, so their
`v5_<legacy>_comparison.jsonl` path literals were left untouched per the
dormant=leave rule.

## 6. NEW finding — dashboard basic-auth username still carries the old name

Not in the original T0 report: `/etc/nginx/.htpasswd_dashboard` is mode 0600
root-only, so the unprivileged grep in T0 could not read it. Re-grepping
under sudo shows the htpasswd **username** is a legacy-named literal. Both
the username and the bcrypt hash are **redacted from this public copy** — they
are live credential components.

Left unchanged — it is a live credential, and changing it changes the
username every dashboard client/bookmark must supply. Needs an explicit
decision plus a coordinated `htpasswd` rewrite.

## Still untouched (per sign-off)

Persisted `v5_<legacy>` / `<legacy>_first_v1` schema literals and the 128 + 47 JSON
artifacts that carry them; `logs/{signal_log.jsonl,diagnostics.log,
sweep_journal_*.csv}`; `archive/<legacy>_first/**`; `reports-shared/` (separate
repo, shared with 161) and `reports-public/`; `.env.bak.*`; `*.bak.*` source
backups; dated `docs/` + `reports/` post-mortems; the box hostname (still the legacy
name, unchanged).
