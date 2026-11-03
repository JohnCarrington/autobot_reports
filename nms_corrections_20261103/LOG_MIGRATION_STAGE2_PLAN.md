# Stage 2 Log Migration — Preflight + Implementation Plan

**Date:** 2026-11-03
**Trigger:** Operator-authorised Stage 2 preflight. Stage 1 (worktree migration) reclaimed 6.4 GB; new baseline is root at 71% used (17 GB used, 7.1 GB free), /mnt at 33% (31 GB used, 64 GB free).
**Scope:** READ-ONLY investigation + design for a **permanent** log-management regime. **No changes performed in this stage.**

---

## 1. Live log-writer inventory

### 1.1 Writable file descriptors held by production processes

Scanned `/proc/<pid>/fd/` for every running trading service:

| Service | PID | Started | Writable log fds |
|---|---:|---|---|
| **autobot.service** | 3337630 | 2026-11-03 09:41:14 UTC | `/opt/tradingbot/logs/diagnostics.log`, `/opt/tradingbot/logs/bb_reversal.log` |
| **ema-pullback.service** | 2514532 | 2026-10-30 12:03:35 UTC | `/opt/ema_pullback/logs/ema_pullback.log` |
| **bb-bounce.service** | 2400402 | 2026-10-29 23:18:10 UTC | **none** — logs via journald/stdout |
| **trades-api.service** | 2793845 | 2026-10-31 22:10:11 UTC | **none** — logs via journald/stdout |

**Key observation.** Only three persistent-fd `*.log` files exist. All other autobot writes (`*.jsonl`, cache, state) use open-write-close patterns via per-event file handles. This means a `/opt/tradingbot/logs/` bind-mount is safe for every log file EXCEPT the three persistent-fd files, which require a controlled service restart.

### 1.2 journald + rsyslog pipeline

| Component | Config | Effect |
|---|---|---|
| journald persistent store | `/var/log/journal/4a3054419cce80b10f60fcea694f0de8/` (exists) | journal stores to disk |
| journald volatile store | `/run/log/journal/4a3054419cce80b10f60fcea694f0de8/` (also exists) | staged in tmpfs |
| journald caps (via `/etc/systemd/journald.conf.d/50-autobot-rotation.conf`) | SystemMaxUse=500M, SystemKeepFree=5G, MaxRetentionSec=14d, SystemMaxFileSize=50M | Hard ceiling 500M on disk |
| journald → rsyslog forward | Default `ForwardToSyslog=yes` (not overridden) | Every journal event duplicated to `/var/log/syslog` |
| rsyslog pipeline | `*.*;auth,authpriv.none → -/var/log/syslog` | **Catches every journal line as text** |
| current journald footprint | 421.6 MB (close to 500 MB cap) | Will auto-vacuum when hit |

**Journald is NOT a root-disk problem** — it is capped at 500 MB and the files live partially on tmpfs. The actual root-disk cost is the **rsyslog mirror** of every journal event into `/var/log/syslog`.

### 1.3 Existing logrotate configs (per Phase 3 remediation 2026-10-29)

| Config file | Scope | Rotation policy | Destination |
|---|---|---|---|
| `/etc/logrotate.d/autobot-jsonl` | `/opt/tradingbot/logs/*.jsonl` | daily, rotate 8, maxsize 50M, minsize 1M, **copytruncate**, delaycompress | **in-place on root** (deliberate — scripts scan prev-day) |
| `/etc/logrotate.d/autobot-logs` | `/opt/tradingbot/logs/*.log` | daily, rotate 8, maxsize 50M, **copytruncate**, delaycompress | **olddir → /mnt/.../logs_rotated/** (already working — files back to Oct 6) |
| `/etc/logrotate.d/strategy-sidecars` | `/opt/ema_pullback/logs/*.log` + 2 more | daily, rotate 8, maxsize 50M, **copytruncate**, delaycompress | **olddir → /mnt/.../logs_rotated/** |
| `/etc/logrotate.d/rsyslog` | `/var/log/syslog`, `/var/log/kern.log`, etc. | daily, size 100M, rotate 7, compress, delaycompress, `su root syslog` | **in-place on root** (deliberate — rsyslog SIGHUP needs rename) |
| `/etc/logrotate.d/ufw` | `/var/log/ufw.log` | weekly, rotate 4 | in-place (OS default, small) |

**The `.log` family already relocates rotated generations to /mnt.** The gap is on `.jsonl` and `syslog` families, which keep everything on root.

### 1.4 Current `/opt/tradingbot/logs/` composition (snapshot)

```
140 MB total
├─ 119 live uncompressed *.jsonl files        88 MB  (dominated by v3_events.jsonl 54 MB)
├─ 194 rotated *.jsonl*.gz files              29 MB  (last 8 generations × ~15 files)
├─ 2 live *.log files                        1.4 MB  (diagnostics + bb_reversal — open fds)
├─ 15+ inactive one-off *.log files           ~2 MB  (notifempty guards them)
└─ Rotated .log.gz archive                 on /mnt   ← already migrated via autobot-logs olddir
```

### 1.5 Current `/var/log/syslog*` composition (snapshot)

```
/var/log/syslog    (live)   85 MB  mtime now
/var/log/syslog.1  (yday)  230 MB  mtime 2026-11-03 00:00  ← Nov-2 spike day
/var/log/syslog.2.gz        0.7 MB mtime 2026-11-02 00:00
/var/log/syslog.3.gz        0.6 MB mtime 2026-11-01 00:00
/var/log/syslog.4.gz        9 MB   mtime 2026-10-31 00:00
/var/log/syslog.5.gz        3 MB   mtime 2026-10-30 00:00
/var/log/syslog.6.gz       38 MB   mtime 2026-10-29 13:06  ← Phase 3 Oct 29 chaos day
```

7-day average: **45 MB/day**. Peak: 230 MB/day. Steady-state root ceiling under current rotation ~200 MB.

---

## 2. 110 MB/day growth attribution

### 2.1 Last-1-hour journal composition (where every byte originates)

```
Service                                       Lines/hour     % of volume
live-market-observer-shadow-exec.service      252,886        97.80%
autobot.service                                 2,579         1.00%
init.scope                                      1,893         0.73%
parallel-candle-compare.service                   338         0.13%
kernel                                            174         0.07%
ssh.service                                       145         0.06%
ema-pullback.service                              128         0.05%
ai-trading-agent.service                           66         0.03%
forensic-backfill.service                          64         0.02%
live-market-observer-shadow.service                55         0.02%
live-market-observer.service                       54         0.02%
live-market-observer-scenario-shadow.service       46         0.02%
live-scenario-notifier.service                     42         0.02%
phase13-grader.service                             28         0.01%
```

**97.8% of journald volume is `live-market-observer-shadow-exec.service`.** This is a timer-driven oneshot (`/mnt/.../research/live_obs/shadow_exec/run_shadow_exec.sh`) in the Scenario V2 research pipeline (per memory `project_scenario_v2_c4_deployed_20261029`). `StandardOutput=journal`. It is NOT a live-trading service.

Because the shadow-exec goes to journald and `ForwardToSyslog=yes` is the default, **every one of those 252,886 lines ALSO lands in `/var/log/syslog`**.

### 2.2 Autobot's own 1-hour share: 2,579 lines (1.0%)

Breakdown by log-tag frequency:

```
[INFO]          1,623  (62.6%)
[WARNING]         924  (35.6%)
[LS-CB]           579   LightStreamer callback-latency warnings (slow onItemUpdate)
[LS-WORKER]       341   tick-queue overflow warnings per pair
[PIVOT-ANCHOR]    295   pivot-anchor computation
[LS-OCCUPANCY]    194
[PIVOT_BRIDGE]    115
[STRATEGY]         49
[REST-SWEEP]       39
[QM-MEM]           24
[LS-RECOVERY]      21
[ERROR]            18   <-- actual errors (0.7% of autobot lines)
```

Top autobot WARNING+ patterns:

```
 231  LS-CB native-5m onItemUpdate took N.Nms (>50ms threshold)
 130  LS-WORKER USDJPY tick queue overflow
  97  LS-CB USDJPY PRICE onItemUpdate took N.Nms (>50ms threshold)
  88  LS-CB GBPUSD PRICE onItemUpdate ...
  86  LS-CB EURUSD PRICE onItemUpdate ...
  77  LS-CB USDCAD PRICE onItemUpdate ...
 ...  (similar — all performance telemetry)
  13  PIVOTS ig_daily_pivots unavailable for EURUSD — falling back
   4  get_open_positions: HTTP N (consecutive_failures=N)   ← ERRORS
   3  PRELOAD/USDJPY ❌ Missing CFD epic in CFD_EPICS_JSON
   3  LS-WATCHDOG tick age >N stale — triggering recovery
```

**Verdict on autobot growth:**
- ~65% is pure INFO (normal operational telemetry)
- ~35% is WARNING (LightStreamer performance telemetry — slow callbacks, tick-queue pressure)
- <1% is actual ERROR
- **Only 4 broker-reconcile errors per hour.** This is NOT a reconcile loop.

The Nov-2 230 MB spike was almost certainly dominated by shadow-exec and/or an LS-perf episode, NOT by broker reconcile errors.

### 2.3 Composition of the daily 110 MB

Based on 1-hour sample scaled to 24h + direct file-size measurements:

| Source | Daily growth | Where it lands | Rotation status |
|---|---:|---|---|
| journald (binary) | ~30 MB | /var/log/journal + /run (tmpfs) | 500M cap — self-healing |
| rsyslog mirror | ~45 MB | /var/log/syslog | daily, rotate 7 in-place on root |
| v3_events.jsonl | ~50 MB | /opt/tradingbot/logs/ | daily copytruncate in-place on root |
| other autobot *.jsonl | ~5-10 MB | /opt/tradingbot/logs/ | same |
| autobot *.log family | ~2 MB | /opt/tradingbot/logs/ | **daily copytruncate → /mnt** (already migrated) |
| ema-pullback .log | ~0.5 MB | /opt/ema_pullback/logs/ | **daily copytruncate → /mnt** (already migrated) |

Reconcile ERRORS contribute negligibly to this. **The 110 MB/day is normal trading telemetry + Scenario V2 research-pipeline volume, not an error loop.**

Note that the shadow-exec service produces enormous journald volume but journald is bounded at 500 MB — its contribution to ROOT disk is bounded. The rsyslog mirror of those events is unbounded (grows into syslog) but trimmed by the daily rotate 7 × 100 MB rule.

---

## 3. Attached-volume preflight

### 3.1 Capacity + health

```
/dev/sda  ext4  100 GB  used 31 GB  free 64 GB  33%
Mount options: rw,noatime,discard   (SSD-friendly, matches /dev/vda1)
UUID: 6acb2952-8797-4caa-a09e-d84af5f9f769
Mount persistence: fstab via /dev/disk/by-id/scsi-0DO_Volume_...  with nofail,discard
Write test (by autobot user): PASS
dmesg for sda errors: none
```

### 3.2 Existing /mnt content inventory (updated post-Stage-1)

```
Already-shared tenants:
  12 GB  /mnt/.../ticks                              raw IG tick archive
  4.1 GB /mnt/.../swapfile                            SYSTEM SWAP
  6.3 GB /mnt/.../home-tradingbot-wt (NEW: Stage 1 migration — 118 worktrees)
  2.4 GB /mnt/.../tick_cache_daily                   (symlinked from /opt/tradingbot/data/)
  2.3 GB /mnt/.../analysis
  2.2 GB /mnt/.../research
  798 MB /mnt/.../derived
  681 MB /mnt/.../playwright_browsers
  395 MB /mnt/.../trades_archive                     (strategy_log.csv archive)
  108 MB /mnt/.../bb_bounce                          (shared bb-bounce staging)
  31 MB  /mnt/.../logs_rotated                       ← autobot-logs olddir destination
  86 MB  /mnt/.../tradingbot-wt                      NMS corrections + bb-bounce C5 + reports
```

**/mnt is shared infrastructure** (not autobot-dedicated). The swap file in particular is operationally load-bearing.

### 3.3 Startup-dependency behaviour on volume failure

Current state (post-Stage-1):

| Component | Behaviour if `/mnt` fails to mount |
|---|---|
| systemd boot | Continues (fstab has `nofail`) |
| Swap | Silently absent — OOM risk under memory pressure |
| autobot.service | Starts; writes to /opt on root. **If** we bind-mount `/opt/tradingbot/logs/` without a mount-dependency, logs would be written to the underlying root dir (defeating migration AND filling root fast). |
| Stage-1 worktrees | Inaccessible — 118 research worktrees invisible |
| /opt/tradingbot/data/tick_cache_daily → broken symlink | Replay code gets ENOENT; live trading unaffected |

**The mandatory fix for Stage 2:** every service that writes to a /mnt-backed path MUST have `RequiresMountsFor=/mnt/volume_lon1_1778405456698` in a systemd drop-in. This is the "no silent fallback" guarantee the operator requested.

---

## 4. Design — permanent log management

### 4.1 Overview

Three decisions:

| Component | Current state | Proposal |
|---|---|---|
| `/opt/tradingbot/logs/` (autobot — .jsonl + 2 live .log) | On root, 140 MB + ~60 MB/day growth | **Bind-mount to /mnt/.../autobot-logs/** (requires ONE autobot restart) |
| `/opt/ema_pullback/logs/` (ema-pullback — 1 live .log) | On root, 1 MB + ~0.5 MB/day | **Bind-mount to /mnt/.../ema-pullback-logs/** (requires ONE ema-pullback restart; small) |
| `/var/log/syslog*` (rsyslog) | On root, ~45 MB/day + 7-day retention; 200 MB ceiling | **No bind-mount.** Weekly sweep moves `.N.gz` ≥ 7 days old to /mnt/.../syslog_archive/. Live + .1 remain on root (needed by rsyslog SIGHUP rename semantics). |
| journald | 500 MB cap on /var/log/journal + /run | **No change — already capped.** Optionally reduce `SystemMaxUse` to 200M if memory pressure matters. |

### 4.2 Bind-mount vs symlink — bind-mount, same reasoning as RCA §4.3

Decided in the Oct 29 Phase 3 and reconfirmed in the Nov-3 remediation plan. Bind-mounts are OS-native, transparent, and systemd can gate service startup on them via `RequiresMountsFor=`. Symlinks silently break under mount failure and can confuse tools like `find -xdev`, backup software, and `realpath`-dependent code.

### 4.3 Startup-dependency protection ("no silent fallback")

Create `/etc/systemd/system/autobot.service.d/mount-dep.conf` and parallel files for `ema-pullback.service`, `bb-bounce.service`, `trades-api.service`:

```ini
[Unit]
# 2026-11-03 Stage 2: autobot writes to /opt/tradingbot/logs/ which is
# bind-mounted from /mnt/volume_lon1_1778405456698/autobot-logs/. If the
# attached volume is unavailable, the service MUST fail to start —
# otherwise writes would land on the underlying root ext4, defeating
# the migration AND filling / rapidly.
RequiresMountsFor=/mnt/volume_lon1_1778405456698
```

Behaviour under volume unavailability:

```
$ systemctl status autobot.service
  Loaded: ... autobot.service; enabled
  Active: inactive (dead)
  Condition: start condition failed
    ConditionPathExists=/mnt/volume_lon1_1778405456698  (not met)
```

To recover: operator mounts the volume → systemd auto-triggers autobot.

### 4.4 Rotation policy — unchanged after Stage 2

The existing logrotate configs continue to function AS-IS after the bind-mount:
- `/etc/logrotate.d/autobot-jsonl`: still rotates `/opt/tradingbot/logs/*.jsonl` daily with copytruncate; the files now live on /mnt but the config refers to the directory PATH, not device
- `/etc/logrotate.d/autobot-logs`: still rotates `/opt/tradingbot/logs/*.log` with olddir to /mnt/.../logs_rotated/ (redundant now since the source is also on /mnt, but harmless)
- `/etc/logrotate.d/strategy-sidecars`: same, for ema-pullback
- `/etc/logrotate.d/rsyslog`: unchanged — syslog stays on root until weekly sweep

### 4.5 Syslog archive sweep (new)

Create `/etc/systemd/system/syslog-archive.service` + `.timer`:

```ini
# /etc/systemd/system/syslog-archive.service
[Unit]
Description=Move rotated syslog gz files older than 7 days to /mnt
RequiresMountsFor=/mnt/volume_lon1_1778405456698
ConditionPathExists=/mnt/volume_lon1_1778405456698/syslog_archive

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'find /var/log -maxdepth 1 -name "syslog.*.gz" -o -name "kern.log.*.gz" -o -name "ufw.log.*.gz" -mtime +7 2>/dev/null | xargs -r -I{} mv -v {} /mnt/volume_lon1_1778405456698/syslog_archive/'
User=root

# /etc/systemd/system/syslog-archive.timer
[Unit]
Description=Weekly syslog archive sweep

[Timer]
OnCalendar=Sun 04:00
Persistent=true

[Install]
WantedBy=timers.target
```

**Guarantee:** `ConditionPathExists=` ensures the service never runs if /mnt is down (safe no-op). The `-mtime +7` guard preserves recent 7-day retention on /; only files >7 days old move. Rsyslog itself is unaffected.

### 4.6 Disk-space warnings (new)

Create `/etc/systemd/system/disk-free-warn.service` + `.timer`:

```ini
# /etc/systemd/system/disk-free-warn.service
[Unit]
Description=Alert if root fs free space drops below threshold

[Service]
Type=oneshot
# 2 GB free threshold on /
ExecStart=/bin/sh -c '
  avail_mb=$(df -BM / | awk "NR==2 {print int(\$4)}" | tr -d M);
  if [ "$avail_mb" -lt 2048 ]; then
    msg="[DISK-WARN] / free=${avail_mb}MB < 2048MB threshold";
    logger -t disk-free-warn -p daemon.warning "$msg";
    # Optional: send to operator email/telegram via existing autobot notifier
    # (left as separate task — operator chooses alerting channel)
  fi
'

# /etc/systemd/system/disk-free-warn.timer
[Unit]
Description=Disk-free check every 15 min

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

Emits a `logger` warning line to syslog (operator-visible via `journalctl -t disk-free-warn`). Can be extended later with Telegram/Slack/email once operator picks a channel.

### 4.7 Journald SystemMaxUse — optional reduction

Journald lives in /var/log/journal (persistent on vda1) and /run/log/journal (tmpfs — RAM). Current 500M cap means up to 500M of binary journal consumes vda1 at saturation. On a 25 GB root with ~17 GB used, the 500 MB journal is tolerable.

**Optional:** reduce `SystemMaxUse=500M` → `SystemMaxUse=200M` in `/etc/systemd/journald.conf.d/50-autobot-rotation.conf`. Saves up to 300 MB on root. Trade-off: shorter investigation history for the shadow-exec-dominated journal stream. Operator decision; not required to meet Stage 2 target.

---

## 5. Implementation sequence

Each step shown as the **exact operator commands**. Nothing has been executed; this is the plan for separate approval.

### 5.0 Pre-flight (operator)

```bash
# Confirm current state
df -h / /mnt/volume_lon1_1778405456698
systemctl is-active autobot.service bb-bounce.service trades-api.service ema-pullback.service

# Confirm C1+C2+C6 flags still live (phase B must not have regressed)
cat /proc/$(systemctl show autobot.service -p MainPID --value)/environ | tr '\0' '\n' | grep NMS_V3_C

# Preserve the C6 midnight checklist location (will NOT be touched by this plan)
ls -la /opt/tradingbot/reports-public/c6_midnight_verification_20261104/CHECKLIST.md
```

### 5.1 Step A — stage destination + rsync (ZERO downtime, zero service impact)

```bash
# Create destination directories
sudo mkdir -p /mnt/volume_lon1_1778405456698/autobot-logs
sudo mkdir -p /mnt/volume_lon1_1778405456698/ema-pullback-logs
sudo mkdir -p /mnt/volume_lon1_1778405456698/syslog_archive
sudo chown autobot:autobot /mnt/volume_lon1_1778405456698/autobot-logs /mnt/volume_lon1_1778405456698/ema-pullback-logs

# Preserve exact ownership + mtimes
sudo rsync -aHAX --info=progress2 /opt/tradingbot/logs/ /mnt/volume_lon1_1778405456698/autobot-logs/
sudo rsync -aHAX --info=progress2 /opt/ema_pullback/logs/ /mnt/volume_lon1_1778405456698/ema-pullback-logs/

# Verify
sudo diff -r /opt/tradingbot/logs/ /mnt/volume_lon1_1778405456698/autobot-logs/ | head
sudo diff -r /opt/ema_pullback/logs/ /mnt/volume_lon1_1778405456698/ema-pullback-logs/ | head
find /opt/tradingbot/logs -type f | wc -l
find /mnt/volume_lon1_1778405456698/autobot-logs -type f | wc -l
# counts must match
```

Expected downtime: **zero** — rsync is read-only on source side.

### 5.2 Step B — add systemd mount-dependency drop-ins (ZERO downtime)

```bash
sudo tee /etc/systemd/system/autobot.service.d/mount-dep.conf <<'EOF'
[Unit]
# 2026-11-03 Stage 2: logs/ bind-mount depends on /mnt
RequiresMountsFor=/mnt/volume_lon1_1778405456698
EOF

sudo tee /etc/systemd/system/ema-pullback.service.d/mount-dep.conf <<'EOF'
[Unit]
# 2026-11-03 Stage 2: logs/ bind-mount depends on /mnt
RequiresMountsFor=/mnt/volume_lon1_1778405456698
EOF

sudo tee /etc/systemd/system/bb-bounce.service.d/mount-dep.conf <<'EOF'
[Unit]
# bb-bounce does not currently log to disk, but future rotation + reports
# live under /mnt. Add dependency pre-emptively.
RequiresMountsFor=/mnt/volume_lon1_1778405456698
EOF

sudo tee /etc/systemd/system/trades-api.service.d/mount-dep.conf <<'EOF'
[Unit]
# trades-api reads trade history files which may be relocated later.
# Add dependency pre-emptively.
RequiresMountsFor=/mnt/volume_lon1_1778405456698
EOF

sudo systemctl daemon-reload
# No restart — the drop-in takes effect on next service start naturally.
# Services that are running now continue running; the dependency is for
# future starts.
```

Expected downtime: **zero** — `daemon-reload` does not interrupt running units.

### 5.3 Step C — fstab bind-mount entries (ZERO downtime; mount not activated yet)

```bash
sudo tee -a /etc/fstab <<'EOF'

# 2026-11-03 Stage 2 — autobot + ema-pullback log bind-mounts
/mnt/volume_lon1_1778405456698/autobot-logs       /opt/tradingbot/logs       none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
/mnt/volume_lon1_1778405456698/ema-pullback-logs  /opt/ema_pullback/logs     none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
EOF

# Validate fstab syntax (does NOT execute mounts)
sudo mount -a --fake 2>&1 | head
```

Expected downtime: **zero** — fstab edits don't activate until explicit `mount -a` or next boot.

### 5.4 Step D — autobot restart with bind-mount activation

```bash
# Preserve pre-restart snapshot of state
BACKUP=/mnt/volume_lon1_1778405456698/autobot-nms-deploy-20261103
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP/pre-logs-bind-$TS"
cp -av /opt/tradingbot/cache/session_trend_state.json "$BACKUP/pre-logs-bind-$TS/"
sha256sum /opt/tradingbot/*.py /opt/tradingbot/.env > "$BACKUP/pre-logs-bind-$TS/hashes.pre.txt"

# Stop autobot (releases the 2 open fds in logs/)
sudo systemctl stop autobot.service

# Verify no process holds files in /opt/tradingbot/logs/
sudo lsof +D /opt/tradingbot/logs/ 2>&1 | head
# (expect no autobot python results)

# Rename old dir to preserve it under a dated name (safety net)
sudo mv /opt/tradingbot/logs /opt/tradingbot/logs.pre-bind-$(date -u +%Y%m%dT%H%M%SZ)
sudo mkdir -p /opt/tradingbot/logs

# Activate bind
sudo mount /opt/tradingbot/logs
mountpoint /opt/tradingbot/logs    # must say "is a mountpoint"

# Start autobot
sudo systemctl start autobot.service

# Verify
systemctl status autobot.service --no-pager | head
cat /proc/$(systemctl show autobot.service -p MainPID --value)/environ | tr '\0' '\n' | grep NMS_V3_C
# must show C1+C2+C6 all live
```

**Expected downtime: ~5-10 seconds** for autobot (service stop → mount → service start). bb-bounce + trades-api + ema-pullback stay running during this.

### 5.5 Step E — ema-pullback restart

```bash
sudo systemctl stop ema-pullback.service
sudo lsof +D /opt/ema_pullback/logs/ 2>&1 | head  # verify no fds
sudo mv /opt/ema_pullback/logs /opt/ema_pullback/logs.pre-bind-$(date -u +%Y%m%dT%H%M%SZ)
sudo mkdir -p /opt/ema_pullback/logs
sudo mount /opt/ema_pullback/logs
mountpoint /opt/ema_pullback/logs
sudo systemctl start ema-pullback.service
systemctl status ema-pullback.service --no-pager | head
```

**Expected downtime: ~5-10 seconds** for ema-pullback. Does not affect autobot (which is already restarted and uses its own bind-mount).

### 5.6 Step F — syslog archive sweep (install only; first run next Sunday 04:00)

```bash
# Install service + timer unit files
sudo tee /etc/systemd/system/syslog-archive.service <<'EOF'
[Unit]
Description=Move rotated syslog gz files older than 7 days to /mnt
RequiresMountsFor=/mnt/volume_lon1_1778405456698
ConditionPathExists=/mnt/volume_lon1_1778405456698/syslog_archive

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'find /var/log -maxdepth 1 \( -name "syslog.*.gz" -o -name "kern.log.*.gz" -o -name "ufw.log.*.gz" \) -mtime +7 2>/dev/null | xargs -r -I{} mv -v {} /mnt/volume_lon1_1778405456698/syslog_archive/'
User=root
EOF

sudo tee /etc/systemd/system/syslog-archive.timer <<'EOF'
[Unit]
Description=Weekly syslog archive sweep

[Timer]
OnCalendar=Sun 04:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now syslog-archive.timer
sudo systemctl list-timers syslog-archive.timer
```

Expected downtime: **zero**.

### 5.7 Step G — disk-free warning timer

```bash
sudo tee /etc/systemd/system/disk-free-warn.service <<'EOF'
[Unit]
Description=Alert if root fs free space drops below threshold

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'avail_mb=$(df -BM / | awk "NR==2 {gsub(/M/, \"\", \$4); print int(\$4)}"); if [ "$avail_mb" -lt 2048 ]; then logger -t disk-free-warn -p daemon.warning "[DISK-WARN] / free=${avail_mb}MB < 2048MB threshold"; fi'
User=root
EOF

sudo tee /etc/systemd/system/disk-free-warn.timer <<'EOF'
[Unit]
Description=Disk-free check every 15 min

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now disk-free-warn.timer
```

Expected downtime: **zero**.

---

## 6. Expected service downtime (summary)

| Step | Service(s) affected | Downtime |
|---|---|---|
| A — rsync | none | zero |
| B — systemd drop-in | none | zero (daemon-reload only) |
| C — fstab edit | none | zero |
| **D — autobot bind + restart** | **autobot.service** | **~5-10 seconds** |
| **E — ema-pullback bind + restart** | **ema-pullback.service** | **~5-10 seconds** |
| F — syslog archive timer install | none | zero |
| G — disk-warn timer install | none | zero |

**Total production downtime: ~10-20 seconds across the autobot and ema-pullback restarts.** bb-bounce and trades-api are NOT restarted. No broker action. Live trading unaffected beyond the ~10s per-service blips (within normal 5m-close tolerance; LightStreamer reconnects transparently).

---

## 7. Verification tests (per step)

### 7.1 Post-step-A (rsync)

```bash
# Byte-identical check
find /opt/tradingbot/logs -type f -printf "%p %s\n" | sort > /tmp/src.list
cd /mnt/volume_lon1_1778405456698/autobot-logs && find . -type f -printf "./%p %s\n" | sed 's|./\./|/opt/tradingbot/logs/|' | sort > /tmp/dst.list
diff /tmp/src.list /tmp/dst.list   # expect empty

# Spot-check md5sums
for f in $(ls /opt/tradingbot/logs/*.jsonl | head -5); do
  src_md=$(md5sum "$f" | awk '{print $1}')
  dst_md=$(md5sum "/mnt/volume_lon1_1778405456698/autobot-logs/$(basename $f)" | awk '{print $1}')
  echo "$f src=$src_md dst=$dst_md match=$([ "$src_md" = "$dst_md" ] && echo YES || echo NO)"
done
```

### 7.2 Post-step-D (autobot bind + restart)

```bash
# bind-mount active
mountpoint /opt/tradingbot/logs

# writes land on /mnt (device-id check)
stat -c '%d %n' /opt/tradingbot/logs/
stat -c '%d %n' /mnt/volume_lon1_1778405456698/autobot-logs/
# both device-ids must match (same filesystem)

# wait one 5m close
sleep 310
# verify a new write landed under the bind
ls -la --time-style=full-iso /opt/tradingbot/logs/v3_events.jsonl
# mtime must have advanced past the restart timestamp

# Autobot flags still live
cat /proc/$(systemctl show autobot.service -p MainPID --value)/environ | tr '\0' '\n' | grep NMS_V3_C
# Must still show: NMS_V3_C1_CORRECTED_RECLAIM=1, NMS_V3_C2_DIRECTIONAL_PENALTY=1, NMS_V3_C6_DAYROLL_RESET=1

# Services all healthy
systemctl is-active autobot.service bb-bounce.service trades-api.service ema-pullback.service

# No broker action triggered
stat -c '%y %n' /opt/tradingbot/logs/signal_log.jsonl
# mtime must still be 2026-10-30 (no new broker orders during restart)
```

### 7.3 Post-step-F (syslog sweep timer)

```bash
# Dry-run — see what WOULD move on the next Sunday run
sudo find /var/log -maxdepth 1 \( -name 'syslog.*.gz' -o -name 'kern.log.*.gz' -o -name 'ufw.log.*.gz' \) -mtime +7

# Verify timer is scheduled
systemctl list-timers syslog-archive.timer

# Trigger once manually to prove it works
sudo systemctl start syslog-archive.service
ls -la --time-style=full-iso /mnt/volume_lon1_1778405456698/syslog_archive/
```

### 7.4 Post-step-G (disk-free-warn)

```bash
# Trigger once; if free > threshold → silent (no log entry)
sudo systemctl start disk-free-warn.service
journalctl -t disk-free-warn -n 5
```

### 7.5 End-to-end post-migration

```bash
# Root free space (expect large reclaim)
df -h /

# No prunable mounts
findmnt /opt/tradingbot/logs
findmnt /opt/ema_pullback/logs

# Mount dependencies registered
systemctl show autobot.service -p RequiresMountsFor
systemctl show ema-pullback.service -p RequiresMountsFor

# After 24h soak: compare growth vs projection
sudo du -sh /opt/tradingbot/logs /opt/ema_pullback/logs
sudo du -sh /mnt/volume_lon1_1778405456698/autobot-logs /mnt/volume_lon1_1778405456698/ema-pullback-logs
```

---

## 8. Rollback procedure

### 8.1 Per-step rollback

**Step D rollback — autobot bind-mount:**

```bash
sudo systemctl stop autobot.service

sudo umount /opt/tradingbot/logs

# Restore original /opt/tradingbot/logs/ from the renamed backup
sudo mv /opt/tradingbot/logs.pre-bind-<TS> /opt/tradingbot/logs

# Remove the bind entry from /etc/fstab (edit manually)
sudo vi /etc/fstab   # delete the line '/mnt/.../autobot-logs → /opt/tradingbot/logs'

sudo systemctl daemon-reload
sudo systemctl start autobot.service

# Verify
mountpoint /opt/tradingbot/logs   # must say "is NOT a mountpoint"
stat -c '%d %n' /opt/tradingbot/logs/   # device-id must match /dev/vda1
```

**Step E rollback — ema-pullback bind-mount:** same pattern.

**Steps F+G rollback — timer units:**

```bash
sudo systemctl disable --now syslog-archive.timer disk-free-warn.timer
sudo rm /etc/systemd/system/syslog-archive.service /etc/systemd/system/syslog-archive.timer
sudo rm /etc/systemd/system/disk-free-warn.service /etc/systemd/system/disk-free-warn.timer
sudo systemctl daemon-reload
```

**Steps B+C rollback — drop-ins + fstab:**

```bash
sudo rm /etc/systemd/system/autobot.service.d/mount-dep.conf
sudo rm /etc/systemd/system/ema-pullback.service.d/mount-dep.conf
sudo rm /etc/systemd/system/bb-bounce.service.d/mount-dep.conf
sudo rm /etc/systemd/system/trades-api.service.d/mount-dep.conf
sudo systemctl daemon-reload
# Edit /etc/fstab to remove the bind lines (if not already done in steps D/E)
```

### 8.2 Full-migration rollback

If Phase B deployment regressed or the migration itself causes issues, roll back D→E→C→B→F→G independently. Each step's backup `.pre-bind-<TS>` directory on root preserves the original state. The destination `/mnt/.../autobot-logs/` + `/mnt/.../ema-pullback-logs/` can be left in place (safe archive) or removed after soak.

The migration does NOT touch:
- `/opt/tradingbot/*.py` (code)
- `/opt/tradingbot/.env` (credentials)
- `/opt/tradingbot/cache/` (live classifier state)
- `/opt/tradingbot/venv/` (Python runtime)
- `/opt/bb_bounce/*` (bb-bounce code and config)
- `/opt/ema_pullback/*.py` + `/opt/ema_pullback/.env`
- Any trading flags or broker configuration

Rollback is fully filesystem-level; no code or configuration change needed.

---

## 9. Expected space reclaim

| Reclaim mechanism | Immediate | Daily going forward |
|---|---:|---:|
| /opt/tradingbot/logs/ bind to /mnt | 140 MB | ~55-60 MB/day |
| /opt/ema_pullback/logs/ bind to /mnt | 1 MB | ~0.5 MB/day |
| Syslog archive weekly sweep | 0 MB (first run next Sunday) | ~10-15 MB/day avg (bounded by rotate 7) |
| **Total Stage 2** | **~140 MB immediate** | **~65-75 MB/day deflection off root** |

Note: Stage 1 (worktree migration) delivered a one-time 6.4 GB. Stage 2 delivers a MUCH smaller one-time reclaim but **prevents 65-75 MB/day of ongoing root growth** — a different operational benefit. Combined with the already-working `.log` olddir rotation and syslog cap, root growth after Stage 2 is reduced to:

```
Pre-Stage-2 root growth: ~110 MB/day
Post-Stage-2 root growth: ~30 MB/day (journald + /tmp accretion + OS)
```

At that rate, from the current 7.1 GB free, root hits the 2 GB alert threshold in ~165 days. Combined with Stage 3 (worktree-sprawl further cleanup, Puppeteer cache migration, strategy_log.csv removal), the box operates on a sustainable long-term footing.

---

## 10. C1/C2/C6 preservation guarantee

Stage 2 is **log infrastructure only**. It does **NOT**:
- Modify `/opt/tradingbot/nms_v3_classifier.py` (C1+C2 code)
- Modify `/opt/tradingbot/session_trend.py` (C6 code)
- Modify `/opt/tradingbot/.env` (C1+C2+C6 flags)
- Alter the C6 midnight verification checklist at `/opt/tradingbot/reports-public/c6_midnight_verification_20261104/CHECKLIST.md`

Pre-verification during step D will confirm:

```bash
# These must all still match pre-Phase-B baseline:
sha256sum /opt/tradingbot/nms_v3_classifier.py   # expect f690fb9c…
sha256sum /opt/tradingbot/session_trend.py       # expect f4aceeee…
sha256sum /opt/tradingbot/.env                   # expect 5903ab0f…

# After step D (autobot restart):
cat /proc/<NEW_PID>/environ | tr '\0' '\n' | grep NMS_V3_C
# expect:
#   NMS_V3_C1_CORRECTED_RECLAIM=1
#   NMS_V3_C2_DIRECTIONAL_PENALTY=1
#   NMS_V3_C6_DAYROLL_RESET=1

# The C6 midnight checklist file (unchanged):
ls -la --time-style=full-iso /opt/tradingbot/reports-public/c6_midnight_verification_20261104/CHECKLIST.md
# mtime should still be the original write at 2026-11-03 09:48:07.855Z
```

Any mismatch is a FAIL — operator should rollback step D immediately.

---

## 11. Open questions / operator decisions

1. **ForwardToSyslog policy.** The current pipeline duplicates every journal event into `/var/log/syslog`, giving operators text-greppable logs at the cost of ~45 MB/day on root. Options: (a) keep it (current); (b) disable to save ~45 MB/day on root but lose `tail -f /var/log/syslog`; (c) selectively filter in rsyslog to drop high-volume-low-value sources (e.g. shadow-exec). **Recommended: keep current.** The 45 MB/day is bounded by 7-day rotate 7 × 100 MB cap and the archive sweep moves older gz to /mnt.

2. **journald SystemMaxUse reduction.** Can reduce 500M → 200M for ~300MB headroom on root. Operational trade-off: shorter investigation history. **Recommended: defer.** Not required to meet Stage 2 target.

3. **Alert channel.** The disk-free-warn timer currently emits to syslog only. Operator should decide whether to extend to Telegram/email/Slack. **Recommended: defer until operator picks a channel.**

4. **Timing of Steps D+E.** Operator may prefer to run both restarts in rapid succession to limit the overall "window of change," or stagger them 24h apart to isolate attribution. **No strong preference from me.**

5. **IG rate limit on dual restart.** Prior Phase B restart hit `trading_ig.rest.ApiExceededException` on the second restart within 31 minutes. If step D happens shortly after another autobot restart, IG may rate-limit `/accounts` fetch. Mitigation: space step D at least 60 minutes from any prior autobot restart. systemd `RestartSec=30s` auto-recovery handled the Phase B blip; the same mechanism protects step D.

---

## 12. Nothing executed in this preflight

Verification at report write:

```
$ sha256sum /opt/tradingbot/nms_v3_classifier.py /opt/tradingbot/session_trend.py /opt/tradingbot/.env
f690fb9c3f3bf16f3423bb7b1f9f8767dcb6a2f3bf1e40dec55c11f9105d4a8b  /opt/tradingbot/nms_v3_classifier.py
f4aceeee8c9c3665f666fac5c3e59c99c15b7e5f2594472788f0ff7c49d2cf83  /opt/tradingbot/session_trend.py
5903ab0f531a56c34a434af340b7873696700f341afb075f6522270860cee365  /opt/tradingbot/.env

$ systemctl show autobot.service -p MainPID -p ActiveEnterTimestamp
MainPID=3337630
ActiveEnterTimestamp=Tue 2026-11-03 09:41:14 UTC   ← unchanged since Phase B restart

$ df -h /
/dev/vda1   25G   17G  7.1G  71% /   ← unchanged since Stage 1 completion
```

- No files moved, copied, deleted, truncated, compressed, bind-mounted, or symlinked.
- No service restarted.
- No `systemctl`, `mount`, `umount`, fstab edit, or systemd drop-in installed.
- No broker action.
- C6 midnight-rollover verification checklist UNTOUCHED (mtime still 2026-11-03 09:48:07.855Z).

Everything above is a **proposal**. Operator approval required before any step.

---

## 13. Deliverable location

- This document: `/mnt/.../tradingbot-wt/reports-nms-corrections-20261103/nms_corrections_20261103/LOG_MIGRATION_STAGE2_PLAN.md`
- Will be committed to branch `report/nms-corrections-20261103` and pushed to GitHub
