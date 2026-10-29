# Disk Remediation Final Report — 29 October 2026

**Scope:** Phase 2 (immediate recovery) + Phase 3 (permanent logging corrections). All within the operator-approved logging and archive scope.

**Window:** 2026-10-29T12:30Z through 2026-10-29T13:18Z UTC.

## 1. Executive summary

| | Before | After | Δ |
|---|---|---|---|
| **Root fs free** | **1.4 GB (95%)** | **2.3 GB (91%)** | **+0.9 GB** |
| journald disk usage | 998 MB | 606 MB (→500 MB soft ceiling) | -392 MB |
| `/var/log/syslog` active | 681 MB (6+ days, weekly cadence) | 3 MB (minutes old, daily cadence) | -678 MB |
| rsyslog archives | 117 MB (3× .gz) | 155 MB (4× .gz incl. .1.gz) | +38 MB (desired — more retention) |
| strategy_log.csv on root | 414 MB (not written since Feb 2026) | 414 MB (retained per operator) | 0 (archived copy also exists) |

- Root fs usage: 95% → **91%**. Target 80% not reached; see §7.
- No trading or observer services were restarted (service start timestamps unchanged across the entire remediation window).
- No trading journals, broker records, research data, Git worktrees, Claude session history, or active logs were deleted.
- All production corrections are in place and verified live.

## 2. Phase 2 outcomes

### R1 — Force rsyslog rotation (Block A → A')

Operator-run sequence:
1. **12:55Z — First attempt (Block A):** `sudo logrotate -f /etc/logrotate.d/rsyslog` failed with "insecure parent-directory permissions". Root cause: logrotate 3.19.0 security check (introduced in commit 54e6f8c) refuses to rotate files whose parent directory is group-writable unless the config declares the privileged user via `su`. `/var/log` is `0775 root:syslog`, triggering the check. The Ubuntu-shipped `/etc/logrotate.d/rsyslog` (mtime 2021-12-23) predates this requirement.
2. **13:04Z — Corrected config installed:** staged `/etc/logrotate.d/rsyslog` with `su root syslog` + `maxsize 100M` (replacing invalid `size 100M` which disables daily cadence).
3. **13:06Z — Rotation successful:** `sudo logrotate -vf /etc/logrotate.d/rsyslog` rotated 681 MB → `/var/log/syslog.1`; new `/var/log/syslog` created; rsyslog SIGHUP'd and reopened the new file.
4. **13:07Z — Writer handoff verified:** 10-second monitor sampling showed `/var/log/syslog` growing (14,976 → 20,445 bytes) and `/var/log/syslog.1` size-frozen at 681,280,834 bytes. Writer separation confirmed.
5. **13:08Z — Compression authorised:** `sudo gzip /var/log/syslog.1` + `gzip -t /var/log/syslog.1.gz` passed. 681 MB → 38 MB on-disk (~94% compression).

### R2 — Journald vacuum (part of Block A)

- `sudo journalctl --vacuum-size=500M` at 12:55Z recovered 296 MB (998 MB → 702 MB).
- Block D restart at 13:15:50Z applied the new 500M ceiling as a hard limit; journald startup log: `System Journal is 520.1M, max 500.0M, 0B free.` journald will enforce 500M on continued writes.
- Second vacuum C.3 at 13:17Z was no-op (archives already at ceiling; current ~106 MB is active and cannot be vacuumed until rotation).

### R3 — strategy_log.csv archive (completed at 12:43Z, retained per operator §6)

- **Source:** `/opt/tradingbot/trades/strategy_log.csv` (413,984,030 bytes, 419,670 lines, Jan 8 – Feb 11 2026)
- **Target:** `/mnt/volume_lon1_1778405456698/trades_archive/strategy_log.csv.archive-2026-01-08_to_2026-02-11`
- **SHA256:** `2acf4794af88e51290f2d4cd32e60584a1d44300f408d52e16b9da8bcf08123c` (source and target identical, verified)
- **Manifest:** `strategy_log.csv.archive-2026-01-08_to_2026-02-11.manifest` written alongside the archive
- **Dependency check:** `grep -rn "strategy_log\.csv" /opt/tradingbot/` returned 0 matches. `lsof` on the file returned no open handles. No cron/systemd references.
- **Source NOT removed per operator safeguard §6.** The original remains at `/opt/tradingbot/trades/strategy_log.csv`; the archive is a parallel preserved copy on the attached volume.

## 3. Phase 3 outcomes — configurations now in place

### 3.1 `/etc/logrotate.d/rsyslog` (REPLACED)

```
rotate 7           # Keep 1 week of history
daily              # Daily cadence
maxsize 100M       # Also rotate earlier if the file exceeds 100 MB
su root syslog     # Satisfy logrotate 3.19.0 parent-dir security check
missingok
notifempty
compress
delaycompress      # .1 stays uncompressed one cycle for grep/tail
sharedscripts
postrotate
    /usr/lib/rsyslog/rsyslog-rotate     # SIGHUP rsyslog to reopen
endscript
```

- **sha256:** `b2f977437b49cc5c26f3f022e19eef2f95b87359ae9833e3fcb099b3dac2deab`
- Validated via `logrotate -d` dry-run; validated live via `logrotate -vf` at 13:06Z.
- Decision: rotation stays IN-PLACE on root fs. `olddir` to attached volume would require `copytruncate` (not clean with rsyslog's SIGHUP-based reopen pattern). With rotate 7 × compressed ~45 MB per gen, worst-case root footprint ≈ (100 MB active) + (6 × ~45 MB compressed) ≈ 370 MB — well under previous 795 MB weekly peak.

### 3.2 `/etc/logrotate.d/strategy-sidecars` (NEW)

Covers these previously-unrotated application logs:
- `/opt/ema_pullback/logs/*.log` (currently 1 MB — writer: ema_pullback.service)
- `/opt/london_liquidity_sweep/logs/*.log` (currently 7 KB — writer: london_liquidity_sweep.service)
- `/home/autobot/ema_pullback/logs/*.log` (currently 2.5 MB — second ema_pullback instance's stdout/stderr/supervisor + ema_pullback.log)

Policy mirrors `/etc/logrotate.d/autobot-logs` exactly:
```
daily / rotate 8 / maxsize 50M / minsize 1M / copytruncate / compress / delaycompress
notifempty / missingok / dateext / dateformat -%Y%m%d / su autobot autobot
olddir /mnt/volume_lon1_1778405456698/logs_rotated
createolddir 0755 autobot autobot
```

- **sha256:** `1393e9a03d2484187c29f196228d39a186fb35b9a37c12cd6272e1e768138b34`
- Validated via `logrotate -d` dry-run.
- Cross-filesystem behaviour: `copytruncate` + `olddir` lands rotated .gz on the attached volume while the active file stays on root (same pattern as the existing autobot-logs rotation, which has worked since 2026-10-05).

### 3.3 `/etc/systemd/journald.conf.d/50-autobot-rotation.conf` (NEW drop-in)

```
[Journal]
SystemMaxUse=500M       # Was 1G; new hard ceiling
SystemKeepFree=5G       # NEW: refuse journal growth if root fs would drop below 5G free
MaxRetentionSec=14day   # NEW: drop events older than 14 days regardless of size budget
SystemMaxFileSize=50M   # Explicit; matches journald default of ~62M (1/8 of SystemMaxUse)
```

- **sha256:** `e3acb6e119194e520d844defc33a0a1ee7824e2ca6835feb35c497e744c130fb`
- Applied via `sudo systemctl restart systemd-journald` at 13:15:50Z. Pre-restart timestamp 2026-10-05 21:02:52 → post-restart 2026-10-29 13:15:50.
- Startup log confirmed enforcement: `System Journal (/var/log/journal/4a3054419cce80b10f60fcea694f0de8) is 520.1M, max 500.0M, 0B free.`
- journald began immediate archive-file eviction. 998 MB → 606 MB immediately. Will converge to ≤500 MB as fresh writes arrive and old entries expire.
- **Retention impact:** `MaxRetentionSec=14day` is the formal policy. Given current log rate (~70 MB/day), the 500M ceiling will enforce effective ~7-day retention — tighter than the 14-day retention cap in practice. Both constraints apply (whichever is more restrictive).

### 3.4 Mount-dependency drop-ins (STAGED, NOT INSTALLED)

Per operator safeguard §9 ("Do not activate mount-dependency changes if doing so requires restarting live services. Stage those changes for a maintenance window instead."), the staged `[Unit] RequiresMountsFor=/mnt/volume_lon1_1778405456698` drop-ins for the seven live-market-observer* / live-scenario-notifier services remain in the staging worktree at:

```
staging/systemd.system/live-market-observer.service.d/50-mount-requires.conf
staging/systemd.system/live-market-observer-scenario-shadow.service.d/50-mount-requires.conf
staging/systemd.system/live-market-observer-shadow-exec.service.d/50-mount-requires.conf
staging/systemd.system/live-market-observer-shadow.service.d/50-mount-requires.conf
staging/systemd.system/live-market-observer-dashboard.service.d/50-mount-requires.conf
staging/systemd.system/live-market-observer-news-refresh.service.d/50-mount-requires.conf
staging/systemd.system/live-scenario-notifier.service.d/50-mount-requires.conf
```

**Status: FUTURE MAINTENANCE WINDOW.** The drop-ins would take effect only on next service start (not during installation), so technically a maintenance window is not strictly required unless the operator wants the active services to also pick up the dependency immediately. Flag the deployment as a maintenance-window action to be safe.

Current anti-root-fs-fallback protections already in place (not introduced by this task, but worth noting):
- Service units declare `ReadOnlyPaths=/opt/tradingbot` + `ReadWritePaths=/mnt/volume_lon1_1778405456698/research/live_obs/*` — kernel-level mount binding. If the mount is absent at service start, these paths cannot be opened RW, and the service fails fast with a clear error rather than silently writing to root.
- `fstab` has `nofail,discard` on the attached volume — the volume will not block boot but will remount cleanly on recovery.

The RequiresMountsFor= drop-ins add a systemd-level pre-flight check so the service doesn't even START without the volume. Belt + braces with the sandbox rules.

### 3.5 Worktree-on-attached-volume

- Created base directory: `/mnt/volume_lon1_1778405456698/worktrees/` (empty, 4 KB)
- Staged helper script: `staging/scripts/wt-attached-helper.sh` (not installed to a system path; manually invokable from the staging worktree or copied to `/usr/local/bin/` by the operator)
- Future workflow:
  ```
  /path/to/wt-attached-helper.sh origin/main my-work
  cd /mnt/volume_lon1_1778405456698/worktrees/my-work
  ```
- Existing `/home/autobot/tradingbot-wt/*` worktrees (6.3 GB, 114 worktrees) **unchanged**.

**Open question regarding Claude Code harness:** the `EnterWorktree` tool creates worktrees under `.claude/worktrees/` within the current repository. There is no documented `worktree.basePath` setting that redirects this. Operators who want ALL future Claude-Code-created worktrees on the attached volume would need to:
- Either run Claude Code from a working directory already on the attached volume (CWD determines `.claude/worktrees/` location), or
- Use the helper script manually when creating a new line of work.

The helper + base directory are the minimal non-invasive change; a more aggressive change (e.g., a `.claude/worktrees` → `/mnt/...` symlink inside the primary tree) would affect existing worktrees and is not recommended.

## 4. Verification matrix

| Check | Result |
|---|---|
| Root fs usage after remediation | **91% (2.3 GB free)** — down from 95% (1.4 GB free). |
| Space recovered total | **~900 MB** (-640 MB syslog, -300 MB journal, +40 MB more archives on attached vol). |
| `/var/log/syslog` rotation | Active file 3 MB; `.1.gz` 38 MB (compressed from 681 MB); rsyslog continues writing cleanly. |
| rsyslog writer handoff | Verified over 10-second sample window: `/var/log/syslog` grew 14,976 → 20,445 B; `.1` size-frozen at 681,280,834 B. |
| Compressed archive integrity | `gzip -t /var/log/syslog.1.gz` passed. |
| journald retention | SystemMaxUse=500M (hard ceiling), SystemKeepFree=5G (safety), MaxRetentionSec=14d (soft policy), SystemMaxFileSize=50M. All enforced live. |
| Archived strategy_log.csv checksum | SHA256 `2acf4794a…` matches between source (`/opt/tradingbot/trades/`) and target (`/mnt/.../trades_archive/`). |
| Mount-dependency status | NOT installed (deferred to maintenance window per safeguard §9). Current sandbox-level protection via `ReadOnlyPaths`/`ReadWritePaths` remains in place. |
| Service start timestamps unchanged | `autobot.service` 2026-10-28T13:08:56Z, `live-market-observer.service` 2026-10-29T07:00:02Z, `live-market-observer-dashboard.service` 2026-10-29T12:22:46Z (from C4 earlier — not restarted by this task), `rsyslog.service` 2026-09-22T06:23:46Z. Only `systemd-journald` was restarted (13:15:50Z), which is a system log capture service, not a trading service. |
| **Root fs < 80%** | **NO** (91%). See §7 for options to reach ≤80%. |

## 5. Permanent-fix dry-run summary

| Config | Dry-run result |
|---|---|
| `/etc/logrotate.d/rsyslog` (new) | `after 1 days (7 rotations); log files >= 104857600 are rotated earlier`; `empty log files are not rotated, old logs are removed`. |
| `/etc/logrotate.d/strategy-sidecars` (new) | All 6 target paths parsed; each log's state file freshly initialised; rotation deferred until `maxsize` or next day. |
| `journald.conf.d/50-autobot-rotation.conf` | `systemd-journald` startup log: `System Journal is 520.1M, max 500.0M, 0B free.` — confirms SystemMaxUse applied. |
| `rsyslog` live rotation | Produced `/var/log/syslog.1` (uncompressed 681 MB, then compressed to 38 MB) and empty new `/var/log/syslog`. Writer handoff verified via file-size monitoring. |

## 6. Service inventory — unchanged

| Service | ExecMainStart | Status |
|---|---|---|
| `autobot.service` | Wed 2026-10-28 13:08:56 UTC | active |
| `live-market-observer.service` | Thu 2026-10-29 07:00:02 UTC | active |
| `live-market-observer-dashboard.service` | Thu 2026-10-29 12:22:46 UTC | active (restarted during C4, not this task) |
| `rsyslog.service` | Tue 2026-09-22 06:23:46 UTC | active (SIGHUP via logrotate — not a restart) |
| `ema_pullback.service` | n/a (inactive — operator-controlled) | inactive |
| `bb_bounce.service` | n/a (inactive — operator-controlled) | inactive |
| `systemd-journald` | **Thu 2026-10-29 13:15:50 UTC** | **active (RESTARTED to apply new config — not a trading service)** |

No trading service was restarted. The only service restart was `systemd-journald`, which is explicitly outside the trading-service scope and is the standard mechanism to apply journald.conf changes.

## 7. Work requiring a future maintenance window

### 7.1 To reach ≤80% root fs usage (≤5 GB free)

Current: 91% (2.3 GB free). To reach 80% (≥5 GB free) would require **recovering an additional ~2.7 GB**. Options the operator can authorise:

| Action | Recovery | Risk |
|---|---|---|
| Remove `/opt/tradingbot/trades/strategy_log.csv` (archive already on attached volume) | ~395 MB | Low — original is a dead file (last written 2026-02-11); verified archive matches by SHA256. Operator explicitly declined in this task. |
| Prune `/home/autobot/.claude/file-history/*` dirs older than 14 days | ~100 MB | Minimal — Claude Code's cross-session file snapshots. |
| Prune `/home/autobot/.claude/projects/-opt-tradingbot/` old session logs | ~200 MB (keep latest N days) | Minimal. |
| Move operator worktrees `/home/autobot/tradingbot-wt/<oldest>/` to attached volume | 100 MB-500 MB each | Low-medium. Explicitly disallowed by current task restrictions. |

Reaching ≤80% within current task restrictions is not achievable: ~900 MB has been recovered; the remaining consumers are preserved operator-owned artefacts.

### 7.2 Mount-dependency drop-ins (safeguard §9 deferred)

Install the seven staged `50-mount-requires.conf` drop-ins at a maintenance window. Installation steps:
```
# Operator-run during maintenance window
for svc in live-market-observer live-market-observer-scenario-shadow \
           live-market-observer-shadow-exec live-market-observer-shadow \
           live-market-observer-dashboard live-market-observer-news-refresh \
           live-scenario-notifier; do
    sudo mkdir -p /etc/systemd/system/${svc}.service.d
    sudo install -m 0644 -o root -g root \
        /home/autobot/reports-wt/disk-root-cause-20261029/disk-root-cause-20261029/staging/systemd.system/${svc}.service.d/50-mount-requires.conf \
        /etc/systemd/system/${svc}.service.d/50-mount-requires.conf
done
sudo systemctl daemon-reload
# No service restart needed — the dependency applies on NEXT service start
# To activate immediately on currently-running services, you'd restart each
# (that's the maintenance-window action).
```

### 7.3 Weekly archive-to-attached-volume sweep for rsyslog

Optional improvement: a weekly systemd timer that moves `/var/log/syslog.*.gz` to `/mnt/.../syslog_archive/` once each file is ≥ 7 days old. Keeps root fs rsyslog footprint under ~100 MB active + ~100 MB compressed = 200 MB cap. Deferrable; not needed given current ceiling.

### 7.4 Worktree-helper installation

Copy `staging/scripts/wt-attached-helper.sh` to `/usr/local/bin/wt-attached-helper.sh` for operator convenience. Document the alternate workflow for Claude Code (CWD-driven worktree location).

## 8. Deliverable checklist

- [x] Attached volume identification + mount health — unchanged from Phase 1 audit.
- [x] Root filesystem usage before and after — §1.
- [x] Actual space recovered — §1 (0.9 GB).
- [x] Log rotation settings applied — §3.1, §3.2.
- [x] journald retention and storage limits — §3.3.
- [x] Archive checksum verification — §2 R3; SHA256 `2acf4794a…` matches.
- [x] Mount-dependency status — §3.4 (STAGED, not installed; safeguard §9).
- [x] Any work requiring a future maintenance window — §7.
- [x] Whether root filesystem usage is now below 80% — §4 (NO; 91%).

## 9. Restrictions honoured

- No trading service restarted. autobot.service / live-market-observer.service / ema_pullback.service / bb_bounce.service / rsyslog.service all retain their pre-remediation start timestamps.
- Only `systemd-journald` restarted — a system log capture service outside the trading-service scope, restart required to apply the drop-in.
- No Git worktrees deleted.
- No Claude session history deleted.
- No trading journals / historical candles / broker records / research data deleted.
- strategy_log.csv original retained on root per operator safeguard §6; archived copy on attached volume preserved.
- Mount-dependency drop-ins staged, not installed, per safeguard §9.
- Correction 4 state unchanged throughout: `scenario_quality.py` / `scenario_reasoner.py` / `scenario_recommendation.py` sha256 hashes identical to post-C4 deployment (not touched by this task).
