# Root Disk Capacity — Root-Cause Analysis & Permanent Remediation Plan

**Date:** 2026-11-03
**Trigger:** Phase B deployment hit disk-free blocker twice this morning; prior memory `project_disk_remediation_20261029` documented Oct 29 Phase 3 remediation that stabilised briefly then re-filled.
**Scope:** READ-ONLY investigation + design. **No changes performed.** No service restart, no file move, no deletion, no mount reconfiguration, no systemd edit.
**Deliverable gate:** operator approval required before any implementation step in §6.

---

## 1. Observed state

### 1.1 Current filesystems

```
Filesystem     Type   Size  Used Avail Use% Mounted on
/dev/vda1      ext4    25G   24G  797M  97% /                              ← root (SATURATED)
/dev/sda       ext4   100G   25G   70G  26% /mnt/volume_lon1_1778405456698  ← attached volume (healthy)
```

### 1.2 `lsblk` + mount map

```
sda     ext4   label=  uuid=6acb2952-8797-4caa-a09e-d84af5f9f769   mounted  /mnt/volume_lon1_1778405456698  70G free
vda1    ext4   label=cloudimg-rootfs                                mounted  /                              797M free
vda15   vfat   label=UEFI                                           mounted  /boot/efi                       98M free
```

### 1.3 Mount persistence (`/etc/fstab`)

```
LABEL=cloudimg-rootfs /                 ext4 discard,errors=remount-ro            0 1
LABEL=UEFI           /boot/efi          vfat umask=0077                           0 1
/dev/disk/by-id/scsi-0DO_Volume_volume-lon1-1778405456698  /mnt/volume_lon1_1778405456698  ext4  defaults,nofail,discard  0 0
/mnt/volume_lon1_1778405456698/swapfile  none              swap  sw               0 0
```

**Key observations.**
- Volume is mounted via a stable `by-id` path (survives DO reattach) with `nofail` — the system boots if the volume is missing but swap would silently become unavailable and any symlinks pointing into it would break.
- Swap (4 GB) **lives on the volume**, not root. 2.4 GB currently in use. If the volume disappears, the box runs without swap.
- One existing symlink already crosses the boundary: `/opt/tradingbot/data/tick_cache_daily → /mnt/.../tick_cache_daily` (2.4 GB migrated 2026-10-05).

### 1.4 Inode usage

```
Filesystem      Inodes  IUsed   IFree IUse%
/dev/vda1      3225600 588507 2637093   19%
```

Root is not inode-constrained — only 19% used. The problem is pure **bytes**, not file count.

### 1.5 Journal footprint

```
Archived and active journals take up 285.5M in the file system.
```

Caps declared in `/etc/systemd/journald.conf.d/50-autobot-rotation.conf` (per `project_disk_remediation_20261029`): `SystemMaxUse=500M`, `SystemKeepFree=5G`, `MaxRetentionSec=14day`, `SystemMaxFileSize=50M`. Operator vacuumed manually this morning to 200 MB; current 285 MB is normal post-vacuum regrowth.

### 1.6 Deleted-but-held files

Scanned `/proc/<pid>/fd/` for `(deleted)` entries on autobot (3337630), bb-bounce (2400402), trades-api (2793845), ema-pullback (2514532). **None found.** No "phantom" disk use from unlinked-but-open files.

### 1.7 Top-level `du -shx` on root (no cross-fs)

```
11G   /home
5.4G  /usr
4.0G  /opt
2.0G  /var
1.2G  /tmp
111M  /boot
87M   /run
6.2M  /etc
372K  /mnt     ← empty mount-point (volume not counted — correct)
28K   /snap
```

### 1.8 Actively held writable file descriptors (production processes only)

| Service | PID | Open writable file |
|---|---|---|
| autobot | 3337630 | `/opt/tradingbot/logs/diagnostics.log` (1.1 MB) |
| autobot | 3337630 | `/opt/tradingbot/logs/bb_reversal.log` (280 KB) |
| ema-pullback | 2514532 | `/opt/ema_pullback/logs/ema_pullback.log` (280 KB) |
| bb-bounce | 2400402 | (no persistent log fd — logs via journald) |
| trades-api | 2793845 | (no persistent log fd — logs via journald) |

The other autobot log files under `/opt/tradingbot/logs/*.jsonl` are opened-written-closed per 5m-close callback, so a bind-mount of that directory is safe.

---

## 2. High-volume writers

### 2.1 Writer inventory

| Rank | Path | Current size (root) | Daily growth evidence | Open fd? | Criticality | Relocatable? |
|---|---|---|---|---|---|---|
| 1 | **`/home/autobot/tradingbot-wt/*`** | **6.9 GB** | one-time accretion (60+ research/replay worktrees, 80-240 MB each) | no (dormant worktrees) | **LOW** — research archive; branches already pushed | **YES — move to /mnt** |
| 2 | **`/usr/local/lib/python3.10/dist-packages/nvidia/`** + **`/opt/tradingbot/venv/lib/.../torch`** | **~1.8 GB** (nvidia ~1.5G across GPU libs, torch 692 MB in venv) | zero growth (installed, not maintained) | immutable | **LOW** — grep for `import torch` / `import nvidia` in `/opt/tradingbot/*.py` → **zero hits**. Transitively installed; not consumed by production code. | **YES — remove via pip uninstall after requirements audit** |
| 3 | **`/opt/tradingbot/trades/strategy_log.csv`** | **395 MB** | **ZERO growth since 2026-02-11** (9 months dead); `trade_log.csv` dead since 2026-03-06 | no | **LOW** — already archived to `/mnt/.../trades_archive/` per memory `project_disk_remediation_20261029` (sha256 2acf4794a…). Deliberately retained as safety copy. | **YES — delete after operator confirms archive** |
| 4 | **`/opt/tradingbot/.git`** | **298 MB** | small (git objects grow with commits) | no (not opened by any trading service) | **MEDIUM** — code history. Live services do not read it. | **MARGINAL** — git repack could shrink by 30-50%; moving the whole repo is risky because dev tools expect it in-place |
| 5 | **`/var/log/syslog*`** | **361 MB** (74 MB live + 230 MB yesterday + 57 MB older rotations) | **44.8 MB/day mean over last 6 rotations; 230 MB/day peak on 2026-11-02** (reconciliation chaos day) | **active** (rsyslog pid; writes to live `syslog`) | **MEDIUM** — core-OS troubleshooting resource. Logrotate rotate=7 daily; expected ceiling ~200 MB under normal flow. The 230 MB Nov-2 spike shows the ceiling is porous when autobot generates reconcile-error spam. | **MARGINAL** — can bind-mount to /mnt but complicates recovery when /mnt is down |
| 6 | **`/home/autobot/.cache/puppeteer`** + **`/home/autobot/.cache/pip`** | **860 MB** (676 + 184) | zero after initial download | immutable | **LOW** — puppeteer chrome used by scenario reasoner (research tier, not live). pip cache can be rebuilt from PyPI. | **YES — move puppeteer to /mnt; delete pip cache** |
| 7 | **`/opt/tradingbot/logs/`** | **140 MB** (live 54 MB `v3_events.jsonl` + rotated+gzipped daily files) | **~50-60 MB/day uncompressed `v3_events.jsonl` growth; compresses 92% to ~4 MB/day** | 2 fds open (per §1.8) — rest open-write-close | **HIGH** — strategy-decision event log + per-5m snapshots; operator consults for root-cause investigations | **YES — bind-mount is safe** |
| 8 | **`/home/autobot/{ai_trading_agent, ema_pullback, research, reports-wt, ma_cross_h1, autobot_reports_wt, autobot_reports_clone, june-replay, autobot-reports-wt, replay-eurusd-check, ema_pullback-wt, reports-publish-*}`** | **~1.6 GB combined** | one-time | no (dormant) | **LOW** — build staging / research clones / archival worktrees | **YES — move to /mnt** |
| 9 | **`/opt/tradingbot/.claude/worktrees/`** | **334 MB** | Claude Code internal — grows with new sessions | no | **LOW** — tool state, not operator-visible | **YES — move to /mnt** |
| 10 | **`/opt/tradingbot/reports-public/`** | **213 MB** | growing (new report dirs per project) | no (not held by trading services) | **MEDIUM** — public report archive; also pushed to GitHub `autobot_reports` repo | **YES — bind-mount is safe** |
| 11 | **`/opt/tradingbot/backups/`** | **132 MB** | dormant (last .env.bak written 2026-06-16) | no | **LOW** — stale `.env.bak` files from pre-June ops | **YES — move or delete** |
| 12 | **`/tmp/`** | **1.2 GB** | growth paused (oldest file 2026-04-23) | mixed owners | **LOW** — scratch artefacts; systemd-tmpfiles isn't aggressively cleaning | **YES — tmpfs or scheduled cleanup** |
| 13 | **`/opt/tradingbot/data/`** | **266 MB (minus 2.4 GB already-symlinked tick cache)** | ~130 MB actual on root; mostly research datasets | some read-only | **MIXED** — `candles/`, `candles_ext/`, `ohlc/` are live-read by autobot (must stay fast local); `eod_review/` 137 MB is overnight-batch output (can move) | **PARTIAL — eod_review relocatable; live data stays** |

### 2.2 Journald → syslog pipeline (critical to understand)

Autobot/bb-bounce/trades-api/ema-pullback all log to stdout → captured by systemd-journald. systemd-journald forwards to rsyslog (via imjournal in `/etc/rsyslog.d/50-default.conf`), which writes to `/var/log/syslog` plus `/var/log/kern.log` and others. So journald usage (285 MB capped) + `/var/log/syslog*` usage (361 MB) are **largely duplicated information** — the same events live in both the binary journal and the text syslog file.

Logrotate for syslog is already configured (per Phase 3 remediation 2026-10-29) at rotate=7 daily with 100 MB size threshold + `delaycompress`. Expected ceiling ~200 MB; actually hit 361 MB because of the Nov-2 230 MB single-day blow-up.

### 2.3 Baseline daily growth (steady-state estimate)

| Source | Normal daily | Spiky days |
|---|---|---|
| /var/log/syslog | 45 MB (mean of last 6 days) | 230 MB (Nov 2 reconcile chaos) |
| /opt/tradingbot/logs/v3_events.jsonl (uncompressed) | 50-60 MB | — |
| /opt/tradingbot/logs/*.jsonl (other autobot) | ~10 MB total | — |
| journald (if forward-to-syslog disabled) | ~30 MB (binary) | — |
| **Combined post-rotation steady state** | **~110-120 MB/day effective** | can double on busy days |

With daily rotation + rotate=7 + delaycompress, the steady-state ceiling under current config is approximately:
- syslog family: ~200 MB (live 100 MB + 6 compressed generations averaging 20 MB each)
- autobot logs/: ~140 MB (live 50 MB current day + 7-10 compressed days ~5 MB each)
- journald: ~500 MB cap

Total steady-state log footprint on root ≈ **850 MB**. Plus `venv` 1.4 GB, OS 5.4 GB, home research sprawl 11 GB, misc 2 GB = ~20 GB floor. With 25 GB disk that leaves only ~5 GB headroom for OS updates, snap refresh, pip install, and operator work. **The root fs is dimensioned for a bare operational system but is being used as an archive.**

---

## 3. Attached volume audit

### 3.1 Health

```
Filesystem /dev/sda  ext4  100 GB  used 25 GB  free 70 GB  26%
Mount options: rw,noatime,discard  (correct for SSD)
UUID: 6acb2952-8797-4caa-a09e-d84af5f9f769
Mount persistence: fstab via /dev/disk/by-id/scsi-0DO_Volume_... with nofail
Write test: PASS (autobot can create+delete files under /mnt)
dmesg for sda errors: none
```

### 3.2 Current contents (NOT dedicated to autobot)

```
12G  /mnt/volume_lon1_1778405456698/ticks                        ← raw IG tick archive (shared research)
4.1G /mnt/volume_lon1_1778405456698/swapfile                     ← SYSTEM SWAP (critical)
2.4G /mnt/volume_lon1_1778405456698/tick_cache_daily              ← autobot's existing symlinked data
2.3G /mnt/volume_lon1_1778405456698/analysis                     ← research pipeline outputs
2.2G /mnt/volume_lon1_1778405456698/research                     ← research scratch
798M /mnt/volume_lon1_1778405456698/derived                      ← processed datasets
681M /mnt/volume_lon1_1778405456698/playwright_browsers           ← chrome binaries (research tool)
395M /mnt/volume_lon1_1778405456698/trades_archive               ← operator's strategy_log.csv archive
108M /mnt/volume_lon1_1778405456698/bb_bounce                    ← shared bb-bounce staging
86M  /mnt/volume_lon1_1778405456698/tradingbot-wt                 ← my NMS corrections worktrees + report
31M  /mnt/volume_lon1_1778405456698/logs_rotated                  ← shared log archive
...
```

**The volume is already shared between autobot's own data, the swap file, research pipelines, and other project working sets.** It is NOT dedicated infrastructure. Any migration must respect existing consumers, especially the swap file whose integrity depends on the volume being present at boot.

### 3.3 Startup behaviour if volume is unavailable

Current state (fstab `nofail` + no explicit systemd dependency from autobot.service):

| Component | Behaviour when /mnt fails to mount |
|---|---|
| systemd boot | Continues (nofail) |
| Swap | Silently absent — OOM risk under memory pressure |
| autobot.service | Starts normally; writes to /opt/tradingbot/logs on root. Breaks when it reads the tick_cache symlink (replay only — not a live-trading dependency). |
| bb-bounce.service, ema-pullback.service, trades-api.service | Unaffected (no /mnt consumers) |
| Operator work | Backups unavailable, worktrees under /mnt invisible, Phase A/B rollback blocked |

**After migration (proposed below)**:
- autobot.service MUST have an explicit `RequiresMountsFor=/mnt/volume_lon1_1778405456698` so it doesn't start on a bare root (which would lose its log output destination).
- Operator noted in prior memory: "mount-dep drop-ins STAGED not installed per safeguard §9" — this is the pending work.

### 3.4 Suitability for operational logs

- `/dev/sda` is a DigitalOcean block storage volume (SSD-backed per DO spec).
- Mount options `noatime,discard` match what autobot's log writes expect.
- Write latency: comparable to root `/dev/vda1` for sequential append (DO blocks and local SSD both ~0.5-2ms).
- 70 GB free provides 7-10× the current log footprint; sustainable at observed growth rates for years.

**Verdict: suitable for operational logs, with the systemd mount-dependency fix in place.**

---

## 4. Migration architecture (proposed; NOT implemented)

### 4.1 Design principles (operator-stated)

1. Keep executable code, credentials, cache (live state), and venv on the root disk.
2. Move only logs, historical data, research artefacts, and worktree sprawl to /mnt.
3. Prefer `bind-mount` over `symlink` (safer, OS-native, survives find/backup tools; symlinks silently break).
4. Preserve historical records (no deletion in Phase 1; archive first).
5. Protect startup via `RequiresMountsFor=` so autobot waits for the volume.

### 4.2 Path mapping

#### Phase 1 (SAFE, zero service restart required because we're moving directories not held open by production processes)

| Source (on /) | Destination | Mechanism | Reclaim |
|---|---|---|---|
| `/opt/tradingbot/reports-public/` | `/mnt/.../autobot-reports-public/` | **bind-mount** | 213 MB |
| `/opt/tradingbot/trades/` | `/mnt/.../autobot-trades/` | **bind-mount** (keep strategy_log.csv accessible under same path) | 395 MB |
| `/opt/tradingbot/backups/` | `/mnt/.../autobot-dotenv-backups/` | **bind-mount** | 132 MB |
| `/opt/tradingbot/_agent_restore/` | `/mnt/.../autobot-agent-restore/` | **bind-mount** | 9 MB |
| `/opt/tradingbot/_dashboard_stage/` | `/mnt/.../autobot-dashboard-stage/` | **bind-mount** | 1.9 MB |
| `/opt/tradingbot/.claude/worktrees/` | `/mnt/.../claude-worktrees-opt/` | **bind-mount** | 334 MB |
| `/opt/tradingbot/data/eod_review/` | `/mnt/.../autobot-eod-review/` | **bind-mount** | 137 MB |
| **Phase 1 subtotal** | | | **~1.2 GB** |

#### Phase 2 (REQUIRES one autobot restart because logs/ has 2 open file descriptors — bind-mount a directory that is being written to is unsafe)

| Source (on /) | Destination | Mechanism | Reclaim | Why restart |
|---|---|---|---|---|
| `/opt/tradingbot/logs/` | `/mnt/.../autobot-logs/` | **bind-mount** | 140 MB | autobot has 2 open fds in this dir; a bind-mount over the live dir would cause file-descriptor confusion. The clean path is: stop autobot → rsync logs/ to /mnt → bind-mount → start autobot. |
| `/opt/ema_pullback/logs/` | `/mnt/.../ema-pullback-logs/` | **bind-mount** | ~1 MB | same reason (ema-pullback has 1 open fd); requires ema-pullback restart |

#### Phase 3 (POST-APPROVAL, cleanup — no restart)

| Source (on /) | Action | Reclaim |
|---|---|---|
| `/home/autobot/tradingbot-wt/` | move → `/mnt/.../home-tradingbot-wt/` (symlink back if any tool expects old path) | 6.9 GB |
| `/home/autobot/{ai_trading_agent, ema_pullback, research, reports-wt, ma_cross_h1, autobot_reports_wt, autobot_reports_clone, june-replay, autobot-reports-wt, replay-eurusd-check, ema_pullback-wt, reports-publish-20261017, reports-public-wt, bb-bounce-wt}` | move → `/mnt/.../home-worktrees/` | ~1.6 GB |
| `/home/autobot/.cache/puppeteer/` | move → `/mnt/.../puppeteer-cache/` + symlink | 676 MB |
| `/home/autobot/.cache/pip/` | delete (rebuilt from PyPI) | 184 MB |
| `/opt/tradingbot/trades/strategy_log.csv` | delete after confirming `/mnt/.../trades_archive/` sha256 matches | 395 MB |
| `/tmp/*` older than 7 days | systemd-tmpfiles rule | ~1 GB |
| `/opt/tradingbot/.git` | `git gc --aggressive --prune=now` | expected 100-150 MB savings |

#### Phase 4 (OPTIONAL — risky, needs separate authorisation)

| Action | Reclaim | Risk |
|---|---|---|
| pip uninstall torch + nvidia GPU libs if confirmed unused | 1.5-2 GB | breaks any code path we didn't grep (transitive imports) |
| Move `/var/log/syslog*` to /mnt via `copytruncate` logrotate strategy | 200-400 MB cap | brief duplicate-write window per rotation; operational troubleshooting path crosses /mnt |
| Move `/opt/tradingbot/.git` to /mnt + symlink | 100-200 MB | git operations become volume-dependent |

### 4.3 Bind-mount vs symlink: why bind-mount wins

| Aspect | Symlink | Bind-mount |
|---|---|---|
| Transparent to all tools | Mostly; `find -xdev`, backups, some `realpath` logic can trip | **YES** — every system call sees the target as the local path |
| Preserves permissions / xattrs | Target's own | **Source dir unchanged** — bind inherits permissions of underlying mount |
| Survives tool unaware of symlinks | Breaks | **Survives** |
| Resilience to `/mnt` outage | Dangling link, silent read errors | **mount fails cleanly, systemd dependency reports** |
| Setup complexity | 1 `ln -s` | 1 fstab/`.mount` unit + initial rsync |
| Reversibility | Easy | `umount` + swap entries |

Use **symlinks** only for one-off research path shims (as already done for `tick_cache_daily`). Use **bind-mounts** for anything a service actively writes to.

### 4.4 Required systemd changes

Create `/etc/systemd/system/autobot.service.d/mount-dep.conf` (operator previously staged this per memory):

```ini
[Unit]
# Fail-closed on /mnt unavailability. Autobot's logs/ and reports-public/
# live on /mnt via bind-mount after Phase 2; the service must not start
# if the mount is absent (would write to the underlying ext4 of /, defeating
# the whole point of the migration AND filling / in a tight spot).
RequiresMountsFor=/mnt/volume_lon1_1778405456698
```

Same drop-in for `bb-bounce.service`, `ema-pullback.service`, `trades-api.service` once their log paths are migrated.

### 4.5 fstab additions (illustrative; one line per bind)

```
# ── Phase 1 bind-mounts (added after rsync of source dirs) ──
/mnt/volume_lon1_1778405456698/autobot-reports-public  /opt/tradingbot/reports-public  none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
/mnt/volume_lon1_1778405456698/autobot-trades          /opt/tradingbot/trades          none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
/mnt/volume_lon1_1778405456698/autobot-dotenv-backups  /opt/tradingbot/backups         none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
/mnt/volume_lon1_1778405456698/autobot-agent-restore   /opt/tradingbot/_agent_restore  none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
/mnt/volume_lon1_1778405456698/claude-worktrees-opt    /opt/tradingbot/.claude/worktrees none bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
/mnt/volume_lon1_1778405456698/autobot-eod-review      /opt/tradingbot/data/eod_review none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0

# ── Phase 2 (after service restart) ──
/mnt/volume_lon1_1778405456698/autobot-logs            /opt/tradingbot/logs            none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
/mnt/volume_lon1_1778405456698/ema-pullback-logs       /opt/ema_pullback/logs          none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
```

`nofail` on bind mount = system boots even if /mnt is unavailable (bind just skips). `x-systemd.requires-mounts-for=` ensures the bind unit depends on the /mnt filesystem mount being up first.

### 4.6 Rotation, compression, retention

Preserve the Oct 29 Phase 3 settings (logrotate daily + rotate 7 + compress + delaycompress). The source directory moving to /mnt doesn't change rotation — logrotate operates on paths, not devices.

Add systemd-tmpfiles cleanup for /tmp (new `/etc/tmpfiles.d/clean-tmp.conf`):

```
# Age out /tmp content older than 7 days daily.
d /tmp 1777 root root 7d
```

### 4.7 Historical records preservation

- No deletion in Phase 1/2 — bind-mounts preserve everything.
- Phase 3 deletions have explicit precondition: content must already exist in `/mnt/.../trades_archive/` with matching sha256.
- Deletion-candidate list (Phase 3) requires explicit per-file operator sign-off before any `rm`.

### 4.8 Disk-space alerts

Current: none (operator noticed only when deployment hit 97%).

Proposal (post-migration): systemd-service for a cron check that emails/pings on `/` fs usage > 85%. Minimal; one shell line + an operator-configured mail hook. Document separately after migration is stable.

### 4.9 Verification tests (before approving each phase)

For every bind-mount pair (source → destination):

```bash
# 1. rsync destination
rsync -aHAX --delete-after /opt/tradingbot/SRC/ /mnt/volume_lon1_1778405456698/DEST/

# 2. verify content identity
diff -r /opt/tradingbot/SRC/ /mnt/volume_lon1_1778405456698/DEST/  # (expect empty)
du -shx /opt/tradingbot/SRC/ /mnt/volume_lon1_1778405456698/DEST/  # (expect equal)
# OR for files-only count:
find /opt/tradingbot/SRC/ -type f | wc -l
find /mnt/volume_lon1_1778405456698/DEST/ -type f | wc -l   # expect equal

# 3. preserve ownership check
stat -c '%U %G %a' /opt/tradingbot/SRC/ /mnt/volume_lon1_1778405456698/DEST/

# 4. Install bind entry in /etc/fstab (operator)
sudo mount -a           # exercise the new fstab entry without full daemon-reload
mountpoint /opt/tradingbot/SRC   # expect "is a mountpoint"

# 5. verify write still works via the bind
touch /opt/tradingbot/SRC/.probe && rm /opt/tradingbot/SRC/.probe

# 6. For Phase 2 (logs/): verify next 5m-close event lands in bound location
ls -la --time-style=full-iso /opt/tradingbot/logs/v3_events.jsonl
# wait 5 min
ls -la --time-style=full-iso /opt/tradingbot/logs/v3_events.jsonl
# mtime should advance; verify same inode when stat'd via /mnt path
```

### 4.10 Rollback plan

Each bind-mount is independently reversible:

```bash
# Rollback a single bind-mount
sudo umount /opt/tradingbot/SRC                       # removes bind
# Edit /etc/fstab to remove the bind line
# Original underlying directory /opt/tradingbot/SRC retains its pre-rsync content on root
# If the source was emptied before bind-mount, restore from /mnt copy
```

For Phase 2 (log bind-mount under running service):
```bash
sudo systemctl stop autobot.service
sudo umount /opt/tradingbot/logs
# edit fstab
sudo systemctl start autobot.service
# verify writes go to /opt/tradingbot/logs on root fs
```

### 4.11 Startup-failure protection

With `RequiresMountsFor=/mnt/volume_lon1_1778405456698` added to each service drop-in, if the volume is unavailable at boot (e.g. DO detach), autobot.service will NOT start. Operator will see:

```
systemctl status autobot.service
   Loaded: ... autobot.service; enabled
   Active: inactive (dead)
   Condition: start condition failed
     ├─ ConditionPathExists=/mnt/volume_lon1_1778405456698  (not met)
```

Fix: `sudo mount /mnt/volume_lon1_1778405456698` → systemd auto-triggers autobot after mount succeeds.

---

## 5. Estimated reclaimed space

### 5.1 By phase (conservative)

| Phase | Operation | Expected reclaim |
|---|---|---|
| 1 (bind-mounts, no restart) | 213 + 395 + 132 + 9 + 2 + 334 + 137 = 1 221 MB | **~1.2 GB** |
| 2 (bind-mounts, one restart) | 140 + 1 MB = 141 MB | **~140 MB** |
| 3 (cleanup, no restart) | 6.9 + 1.6 + 0.68 + 0.18 + 0.40 + 1.0 + ~0.1 GB | **~10.8 GB** |
| 4 (optional, high-risk) | 1.5-2 GB (torch/nvidia prune) + 0.2 GB (syslog bind) + 0.1 GB (git bind) | 1.8-2.3 GB |

### 5.2 Post-remediation root-disk footprint target

```
Before: 24 GB used, 797 MB free (97%)
After Phase 1-3: 24G - 12.2G = ~12 GB used, ~13 GB free (48%)
```

If Phase 4 is also executed: **~10 GB used, ~15 GB free (40%)**.

### 5.3 Growth trajectory after remediation

With logs bind-mounted to /mnt:
- Daily log growth on root: ~45 MB (syslog only, if NOT bound) OR ~0 MB (if syslog also bound via Phase 4)
- Projected root fs free-space burn: 20 MB/day (OS updates + journal regrowth + misc) → ~1 GB/year
- /mnt volume burn: ~150 MB/day for log family + occasional research spikes → ~55 GB/year
- /mnt remaining capacity at 70 GB free: **>1 year steady-state headroom**

---

## 6. Safe deployment sequence

### 6.1 Phase 1 — safe bind-mounts (no service restart)

For each pair (reports-public, trades, backups, _agent_restore, _dashboard_stage, .claude/worktrees, data/eod_review):

```bash
# Operator-privileged steps:
SRC=/opt/tradingbot/reports-public
DEST=/mnt/volume_lon1_1778405456698/autobot-reports-public

sudo rsync -aHAX --info=progress2 "$SRC/" "$DEST/"
sudo diff -r "$SRC/" "$DEST/"             # expect no output
sudo stat -c '%U %G %a' "$SRC" "$DEST"    # expect identical ownership

# Snapshot pre-mount state
sudo cp -ar "$SRC" "${SRC}.pre-bind-$(date -u +%Y%m%dT%H%M%SZ)"

# Edit /etc/fstab (append line from §4.5)
sudo mount -a
mountpoint "$SRC"                         # expect "is a mountpoint"

# Verify bind
sudo touch "$SRC/.probe" && sudo rm "$SRC/.probe"
ls -la "$SRC/" | head                     # see expected contents

# After 24 hours of soak with no issues:
sudo rm -rf "${SRC}.pre-bind-"*           # discard pre-mount shadow
```

### 6.2 Phase 2 — logs bind (requires one autobot restart)

```bash
# 1. preflight: verify disk space + service health
df -h /

# 2. snapshot
sudo rsync -aHAX /opt/tradingbot/logs/ /mnt/volume_lon1_1778405456698/autobot-logs/
diff -r /opt/tradingbot/logs/ /mnt/volume_lon1_1778405456698/autobot-logs/

# 3. edit /etc/fstab (append logs bind line)
# 4. graceful service stop
sudo systemctl stop autobot.service

# 5. rename old dir (safety net)
sudo mv /opt/tradingbot/logs /opt/tradingbot/logs.pre-bind-$(date -u +%Y%m%dT%H%M%SZ)
sudo mkdir -p /opt/tradingbot/logs

# 6. mount
sudo mount /opt/tradingbot/logs
mountpoint /opt/tradingbot/logs

# 7. start autobot
sudo systemctl start autobot.service

# 8. verify
sleep 300  # wait for one 5m close
tail -n 1 /opt/tradingbot/logs/trend_v3.jsonl
# verify file is served from /mnt via:
stat --format '%d %i %n' /opt/tradingbot/logs/trend_v3.jsonl  # device id should match /mnt
```

### 6.3 Phase 3 — cleanup (no restart)

Per-item operator approval required. Example for `tradingbot-wt`:

```bash
# Verify no process has files open
sudo lsof +D /home/autobot/tradingbot-wt | head

# Move
sudo rsync -aHAX --info=progress2 /home/autobot/tradingbot-wt/ /mnt/.../home-tradingbot-wt/
diff -r /home/autobot/tradingbot-wt/ /mnt/.../home-tradingbot-wt/

# Optional symlink back for tool compatibility
sudo mv /home/autobot/tradingbot-wt /home/autobot/tradingbot-wt.pre-move
sudo ln -s /mnt/volume_lon1_1778405456698/home-tradingbot-wt /home/autobot/tradingbot-wt

# After 24 hours soak, delete the backup
sudo rm -rf /home/autobot/tradingbot-wt.pre-move
```

### 6.4 Dependencies

- Phase 1 → requires sudo (fstab edit, mount, chown).
- Phase 2 → requires sudo + one controlled autobot.service restart (with Phase A/B health protocol).
- Phase 3 → requires sudo (file moves).
- Phase 4 → separate authorisation; requires requirements.txt audit for torch/nvidia removal.

---

## 7. Rollback procedure

### 7.1 Per-bind rollback

```bash
# Remove the bind
sudo umount /opt/tradingbot/SRC

# Edit /etc/fstab to remove the bind line (or comment it out)
sudo vi /etc/fstab

# If content under /opt/tradingbot/SRC was emptied before mount:
#   Restore from /mnt copy:
sudo rsync -aHAX /mnt/volume_lon1_1778405456698/DEST/ /opt/tradingbot/SRC/
#   OR restore from the .pre-bind-TIMESTAMP backup if still present:
sudo rsync -aHAX /opt/tradingbot/SRC.pre-bind-20261103T120000Z/ /opt/tradingbot/SRC/
```

### 7.2 Full-remediation rollback

Each phase is independent. Rolling back phase N doesn't affect phases 1..N-1. In the worst case:
1. `sudo umount` every bind one by one
2. Restore files from each `.pre-bind-TIMESTAMP` snapshot
3. Remove the fstab lines
4. Restore any symlinks that pointed to /mnt

The DI (DigitalOcean) attached volume itself is unchanged by any phase — this is a filesystem-layout question, not a hardware migration.

---

## 8. Is a droplet upgrade actually necessary?

**No.** The 25 GB root disk is adequate for the operational workload (OS + venv + live cache + current-day logs). The problem is **operational hygiene**:

| Occupied by | Size | Nature |
|---|---|---|
| Historical research worktrees on /home | 6.9 GB | one-time accretion; belongs on /mnt |
| Unused Python/GPU libraries in venv | ~2 GB | installed-not-imported; needs cleanup, not more disk |
| Dead strategy_log.csv (Feb 2026) | 395 MB | archive-and-forget work left incomplete |
| Dead backup/.env files (June 2026) | 132 MB | similar |
| Journald + syslog on root | 650 MB cap + 361 MB current | log hygiene — rotatable |
| Chrome puppeteer cache | 676 MB | research tool, not live-trading |

Upgrading from 25 GB → 50 GB root would restore headroom but **not solve the root cause** — the box is being used as an undifferentiated archive. Within a year the 50 GB would face the same pressure. The correct fix is **data-tier placement**: live state on root, archives+logs on /mnt. A droplet upgrade is a workaround; this migration is a cure.

**Only consider a droplet resize if** Phase 4 (torch removal) is rejected AND the operator needs >15 GB free on root for other reasons (e.g. adding a new large OS package set). Current analysis: no such need.

---

## 9. What was NOT done in this investigation

- No files moved, deleted, truncated, compressed, or renamed.
- No `systemctl`, `mount`, `umount`, or fstab change.
- No `rm`, `rmdir`, `rsync`, `cp`, `mv` targeting live paths.
- No service restart.
- No broker action.
- No .env, systemd, or logrotate configuration change.

Everything above is a **proposal**. Operator approval required before any step.

---

## 10. Appendix: deliverable inventory

- This document: `/mnt/.../tradingbot-wt/reports-nms-corrections-20261103/nms_corrections_20261103/ROOT_DISK_CAPACITY_RCA_AND_REMEDIATION.md`
- Will be committed and pushed to branch `report/nms-corrections-20261103` so it survives sessions
- References:
  - `project_disk_remediation_20261029` (prior Phase 3 remediation memory)
  - `/etc/systemd/journald.conf.d/50-autobot-rotation.conf` (journal cap config)
  - `/etc/logrotate.d/rsyslog` (daily rotation config)
  - `/etc/fstab` (current mount config)
  - `/opt/tradingbot/data/tick_cache_daily → /mnt/.../tick_cache_daily` (existing symlink precedent)
