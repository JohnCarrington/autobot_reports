# Root-Disk Consumption Root-Cause Investigation — 29 October 2026

**Phase 1 (read-only). No destructive changes made. No production services restarted.**

**Investigation window:** 2026-10-29T12:30-12:35Z. Current state captured below.

---

## 1. Attached volume identification and mount health

```
Filesystem     Type   Size  Used Avail Use% Mounted on
/dev/vda1      ext4    25G   23G  1.4G  95% /                                  ← ROOT, nearly full
/dev/sda       ext4   100G   23G   72G  25% /mnt/volume_lon1_1778405456698     ← attached, healthy
```

```
NAME    FSTYPE   LABEL             UUID                                 MOUNTPOINTS
sda     ext4                       6acb2952-8797-4caa-a09e-d84af5f9f769  /mnt/volume_lon1_1778405456698
vda1    ext4     cloudimg-rootfs   4640e7ac-ce2d-448f-999c-1735c8212d93  /
```

Mount options (`findmnt`):
```
/mnt/volume_lon1_1778405456698  /dev/sda  ext4  rw,noatime,discard
```

**Verdict — mount health: GOOD.** The attached volume is correctly mounted at `/mnt/volume_lon1_1778405456698`, has 72 GB free, is writable, uses `noatime` + `discard` for TRIM. Inode usage: 7,203 of 3,276,800 (0.2% — abundant).

Root filesystem inode usage: 558,087 of 3,225,600 (18%). **Space, not inode exhaustion, is the problem.**

---

## 2. Root filesystem usage breakdown

### 2.1 Top-level consumers (`du -xhd1 /`)

| Dir | Size | Classification |
|---|---|---|
| `/home` | **9.0 GB** | 70% operator worktrees, 7% Claude Code session artefacts |
| `/usr` | 5.4 GB | OS + Python + Nvidia libs + torch — permanent dependencies |
| `/opt` | 4.2 GB | AutoBot V3 + strategy sidecars (ema_pb, bb_bounce, ma_cross, lls) |
| `/var` | 3.0 GB | OS logs + snapd + apt caches |
| `/tmp` | 829 MB | Test fixtures, Claude task outputs, abandoned worktrees cleanup residue |
| `/boot` | 111 MB | kernels |
| others | <10 MB combined | — |

### 2.2 Top-30 files on root fs

| Size (MB) | Path |
|---|---|
| **670** | `/var/log/syslog` ← **primary offender** |
| 542 | `/usr/local/lib/python3.10/dist-packages/nvidia/cu13/lib/libcublasLt.so.13` |
| 469 | `/usr/local/lib/python3.10/dist-packages/triton/_C/libtriton.so` |
| 444 | `/opt/tradingbot/venv/lib/python3.10/site-packages/torch/lib/libtorch_cpu.so` |
| **414** | `/opt/tradingbot/trades/strategy_log.csv` ← **stale audit record, Jan-Feb 2026 only** |
| 287 | nvidia cufft.so.12 |
| 239 | `/usr/lib/node_modules/@anthropic-ai/claude-code/node_modules/.../claude` + `.exe` |
| 237 | nvidia nccl.so.2 |
| 234 | nvidia cusparseLt.so.0 |
| 162 | nvidia cusparse.so.12 |
| 133 | nvidia curand.so.10 |
| **128** | `/home/autobot/research/gbpusd_fib_reversal_20261027/data_out/approaches.csv` ← **research data, preserve** |
| 123 | `/usr/bin/node` |
| 121 | `/var/lib/snapd/snaps/lxd_40575.snap` |
| 121 | `/var/lib/snapd/snaps/lxd_40911.snap` |
| 110 | nvidia nvrtc.alt.so.13 |
| 109 | nvidia nvrtc.so.13 |
| 99 | nvidia nvJitLink.so.13 |
| 91 | `/var/lib/snapd/seed/snaps/lxd_28373.snap` |
| 89 | `/opt/tradingbot/.git/objects/pack/pack-...pack` |
| 86 | `/home/autobot/june-replay/tree/.git/objects/pack/...` |
| 77 | `/var/lib/snapd/snaps/core22_2437.snap` |
| 77 | `/var/lib/snapd/snaps/core22_2955.snap` |
| 71 | `/var/cache/apt/pkgcache.bin` |
| 71 | `/var/cache/apt/srcpkgcache.bin` |
| 67 | `/var/lib/snapd/seed/snaps/core20_2318.snap` |
| 67 | `/var/lib/snapd/snaps/core20_2922.snap` |
| 67 | `/var/lib/snapd/snaps/core20_2866.snap` |
| 64 | `/var/lib/apt/lists/mirrors.digitalocean.com_...` |
| 59 | journald journals (several files near 59M each) |

### 2.3 Open-deleted files (`lsof +L1`)

```
systemd 1969356 autobot txt REG 252,1 1849992 0 23632 /usr/lib/systemd/systemd (deleted)
```

Only one: a `/usr/lib/systemd/systemd` binary held open by a user-session systemd after a package upgrade (1.8 MB). Not material. **No trading-service processes are holding deleted large files.**

### 2.4 `/var/log` detail

| Path | Size | Notes |
|---|---|---|
| `/var/log/syslog` | **670 MB** | ACTIVE. rsyslog weekly rotation (see §6). |
| `/var/log/journal/4a3054...` | 857 MB | journald persistent store (SystemMaxUse=1G honored) |
| `/var/log/syslog.2.gz` | 45 MB | rotated |
| `/var/log/syslog.3.gz` | 38 MB | rotated |
| `/var/log/syslog.4.gz` | 34 MB | rotated |
| `/var/log/btmp.1` | 33 MB | SSH login-failure log, rotated |
| `/var/log/btmp` | 15 MB | SSH login-failure log, active |
| `/var/log/journal/0821a4...` | 8 MB | second machine-ID journal |
| `/var/log/nginx/*` | 816 KB | nginx access/error (manageable) |

### 2.5 journald disk usage

```
journalctl --disk-usage
Archived and active journals take up 941.8M in the file system.
```

Current `SystemMaxUse=1G` — journald is honoring it. 941 MB is near the ceiling. The ceiling itself is the issue, not a rotation failure.

### 2.6 `/opt/tradingbot/` breakdown

| Subpath | Size | Classification |
|---|---|---|
| `venv` | 1.4 GB | Python dependencies — permanent |
| `trades/strategy_log.csv` | **395 MB** | **Stale audit from 2026-01/02 — single file, no active writer** |
| `.claude/worktrees/` | 334 MB | 14 registered worktrees inside the tracked tree |
| `.git` | 293 MB | Git objects + pack files |
| `logs/` | **293 MB** | Active trading jsonl + .log streams (rotated per §6) |
| `reports-public/` | 213 MB | Published research — preserve |
| `backups/` | 132 MB | .env.bak history + eod-review — preserve |
| `data/` | 265 MB | Candles, tick_cache_daily, feature caches |
| `research/` | 32 MB | — |
| `cache/` | 19 MB | — |

### 2.7 `/home/autobot/` breakdown

| Subpath | Size | Classification |
|---|---|---|
| `tradingbot-wt/` | **6.3 GB** | **114 registered git worktrees of /opt/tradingbot** — operator-owned, **DO NOT TOUCH** per task restrictions |
| `.claude/` | 649 MB | **Claude Code session artefacts** (projects + file-history) across all sessions on this box |
| `.claude/projects/-opt-tradingbot/` | 412 MB | this project's chat history |
| `.claude/file-history/` | 132 MB | all projects' file snapshots |
| `ema_pullback/` | 327 MB | source copy; `venv` 285 MB |
| `ai_trading_agent/` | 276 MB | source copy; `.venv` 249 MB |
| `.local/` | 223 MB | pip user installs |
| `ma_cross_h1/` | 202 MB | source copy; `venv` 201 MB |
| `.cache/` | 186 MB | pip wheel cache etc. |
| `reports-wt/` | 156 MB | git worktrees of `autobot_reports` |
| `autobot_reports_wt/` | 128 MB | git worktrees of `autobot_reports` |
| `research/` | 240 MB | investigation data; `gbpusd_fib_reversal_20261027/data_out/approaches.csv` is 128 MB of it |
| `june-replay/` | 94 MB | historical replay data |

### 2.8 `/tmp/` current contents

| Subpath | Size |
|---|---|
| `claude-1000/` | 64 MB (my session's task outputs) |
| `r4-directional-authority/` | 55 MB (last remaining /tmp worktree; untracked `scripts/r4c5a/`) |
| `autobot_reports_push/` | 39 MB (another autobot_reports clone) |
| `replay_batch/` | 22 MB |
| `sweep_audit_20261018/` | 18 MB |
| `p3-6day-*` | 5-11 MB each (6 dirs) |
| `tmp*whatever*` + Python-pytest tmp dirs | tiny each |

**Total `/tmp` consumption today: 829 MB** (down from ~2.1 GB after the earlier worktree cleanup).

---

## 3. Logs currently stored on root fs

| File | Size | Rotator | Policy | Status |
|---|---|---|---|---|
| `/var/log/syslog` | 670 MB | rsyslog | **weekly / rotate 4 / compress** | **ROTATION TOO SLOW for this volume** |
| `/var/log/journal/4a30...` | 857 MB | journald | SystemMaxUse=1G | Honored, but ceiling is high |
| `/var/log/btmp` + `.1` | 48 MB | btmp rule | monthly | OK |
| `/var/log/syslog.*.gz` | ~117 MB | rsyslog | retained | OK (4 generations) |
| `/opt/tradingbot/logs/*.log` | ~1 MB each, 6 files | `autobot-logs` | daily / 50M / olddir **→ /mnt/.../logs_rotated/** | **CORRECT — moving to attached vol** |
| `/opt/tradingbot/logs/*.jsonl` | up to 50M each | `autobot-jsonl` | daily / 50M / in-place | **CORRECT — deliberate operator design** |
| `/opt/ema_pullback/logs/ema_pullback.log` | 1 MB | **none** | n/a | **GAP — no rotation; low volume** |
| `/home/autobot/ema_pullback/logs/*.log` | 2.5 MB | **none** | n/a | **GAP — no rotation; low volume** |
| `/opt/london_liquidity_sweep/logs/service.log` | 7.5 KB | **none** | n/a | gap, immaterial |
| `/opt/ma_cross_h1/logs/` | 0 (empty) | n/a | — | — |
| `/opt/bb_bounce/logs/` | directory does not exist | journald | journald | — |

**Not a log, but relevant to this investigation:**

| File | Size | Last writer | Notes |
|---|---|---|---|
| `/opt/tradingbot/trades/strategy_log.csv` | **395 MB** | last line 2026-02-11 | **STALE — no active writer. Historical audit from Jan-Feb 2026 only.** Candidate for move to attached volume. |
| `/opt/tradingbot/trades/trade_log.csv` | 141 KB | last line 2026-03-06 | stale |

---

## 4. Logs already stored on the attached volume

| Path | Size | Notes |
|---|---|---|
| `/mnt/volume_lon1_1778405456698/logs_rotated/` | 28 MB | AutoBot .log rotations landing here per `autobot-logs` rule. Working correctly since 2026-10-05. |
| `/mnt/volume_lon1_1778405456698/research/live_obs/journal/` | ~16 MB | Live Market Observer primary journal (decisions.jsonl, snapshots.jsonl, memory.jsonl, errors.jsonl) |
| `/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/` | ~16 MB | Scenario V2 shadow journal (scenarios_shadow.jsonl, scenario_quality_flags.jsonl, telemetry.jsonl, analogues.jsonl) |
| `/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/` | — | Scenario V2 shadow-trading sweeper outputs |

**Verdict:** The research directory on the attached volume is the correct destination; Scenario V2 and the Live Market Observer are properly routed. The AutoBot `.log` olddir rotation is also working correctly.

---

## 5. Services using incorrect logging destinations

Zero AutoBot-family services are silently writing high-volume logs to the root filesystem when they should be on the attached volume. Specifically:

| Service | Primary journal/log destination | Correct? |
|---|---|---|
| AutoBot V3 (`autobot.service`) | `/opt/tradingbot/logs/*.jsonl` (in-place) + `/opt/tradingbot/logs/*.log` (rotates to attached) + journald | **Yes** (operator design) |
| NMS v3 (shares autobot.service process) | same as AutoBot | Yes |
| EMA Pullback (`ema_pullback.service`) | `/opt/ema_pullback/logs/ema_pullback.log` (1 MB) + journald | **Partial** — no rotation configured, but low volume |
| BB Bounce (`bb_bounce.service`) | journald only (no file logging) | Yes |
| MA Cross H1 (`ma_cross_h1.service`) | journald only | Yes |
| London Liquidity Sweep | `/opt/london_liquidity_sweep/logs/service.log` (7 KB) + journald | Yes (immaterial size) |
| Live Market Observer (`live-market-observer.service`) | **`/mnt/.../research/live_obs/journal/`** + journald | **Yes (on attached)** |
| Scenario V2 sweeper (`live-market-observer-scenario-shadow.service`) | **`/mnt/.../research/live_obs/journal_shadow/`** + journald | **Yes (on attached)** |
| Scenario V2 shadow-exec sweeper | **`/mnt/.../research/live_obs/shadow_exec/`** + journald | **Yes (on attached)** |
| Scenario V2 notifier | `/mnt/.../research/live_obs/notifier_state/` + journald | **Yes (on attached)** |
| Dashboard (`live-market-observer-dashboard.service`) | journald only (HTTP serves from read-only paths) | Yes |
| Autonomous Claude Trading Agent (`ai_trading_agent/`) | journald + `/home/autobot/ai_trading_agent/data_cache/` | Yes |

**No service is misrouting logs.** The 670 MB `/var/log/syslog` includes all these services' journald output (via rsyslog `*.* -/var/log/syslog`), which is a system-level duplication, not a service-level misconfiguration.

Mount dependency gaps: no systemd unit has `RequiresMountsFor=/mnt/volume_lon1_1778405456698` wired in. If the attached volume ever failed to mount, services like `live-market-observer.service` would silently recreate their journal paths on root fs. See §8 recommendation.

---

## 6. Existing log-rotation configuration

### 6.1 System rsyslog (`/etc/logrotate.d/rsyslog`)

```
/var/log/syslog
/var/log/mail.info ... (standard list) ...
{
    rotate 4        ← keep 4 generations
    weekly          ← rotate ONCE A WEEK
    missingok
    notifempty
    compress
    delaycompress
    sharedscripts
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate
    endscript
}
```

**Status: Primary defect.** Weekly rotation on a server generating 670 MB/week of syslog = always-near-full root fs by day 7.

### 6.2 journald (`/etc/systemd/journald.conf`)

```
[Journal]
SystemMaxUse=1G
```

Status: Working, but 1 GB ceiling is high relative to 25 GB root. Should drop to 500 MB (see §8) OR move the journal to the attached volume.

### 6.3 `/etc/logrotate.d/autobot-logs` (operator-authored)

```
/opt/tradingbot/logs/*.log {
    daily
    rotate 8
    maxsize 50M
    minsize 1M
    copytruncate
    compress
    delaycompress
    notifempty
    missingok
    dateext
    dateformat -%Y%m%d
    olddir /mnt/volume_lon1_1778405456698/logs_rotated
    createolddir 0755 autobot autobot
    su autobot autobot
}
```

**Status: Working perfectly.** This is the model to replicate for other services. Rotations land on the attached volume.

### 6.4 `/etc/logrotate.d/autobot-jsonl` (operator-authored)

```
/opt/tradingbot/logs/*.jsonl {
    daily
    rotate 8
    maxsize 50M
    minsize 1M
    copytruncate
    compress
    delaycompress
    notifempty
    missingok
    dateext
    dateformat -%Y%m%d
    su autobot autobot
}
```

**Status: Working.** Deliberately rotates in-place on root per operator design (`qm audit scripts that read the previous day's tail keep working without a zcat shim`).

### 6.5 Other logrotate configs

Standard Ubuntu packages — all appropriately configured:
- `/etc/logrotate.d/apt` — apt history, weekly / rotate 12
- `/etc/logrotate.d/btmp` — login failures, monthly / rotate 1 ← **too generous given SSH brute-force volume**
- `/etc/logrotate.d/wtmp` — login successes, monthly / rotate 1
- `/etc/logrotate.d/nginx` — nginx logs, daily / rotate 14
- `/etc/logrotate.d/ufw` — firewall logs
- `/etc/logrotate.d/dpkg`, `apport`, `cloud-init`, `ubuntu-pro-client`, `unattended-upgrades`, `alternatives`, `bootlog` — all low-volume

### 6.6 Rotation gaps identified

| Service / File | Gap | Severity |
|---|---|---|
| rsyslog | weekly cadence too slow | **HIGH** (primary cause) |
| journald | 1 GB cap too high | MEDIUM |
| `/var/log/btmp*` | monthly rotation on brute-force target | MEDIUM |
| `/opt/ema_pullback/logs/*` | no rotation | LOW (currently 1 MB) |
| `/home/autobot/ema_pullback/logs/*` | no rotation | LOW (currently 2.5 MB; is this a duplicate ema_pullback install?) |
| `/opt/london_liquidity_sweep/logs/*` | no rotation | immaterial (7 KB) |
| `/opt/tradingbot/trades/*.csv` | **not logs** — stale audit records on root | **HIGH** (395 MB stale) |

---

## 7. Safest immediate recovery procedure (requires operator approval — Phase 2)

Objective: free ≥ 2 GB on root without touching trading services, broker records, research evidence, or operator worktrees. Prefer **move** over **delete**.

Ranked by safety × impact:

### R1 — Force rsyslog rotation now (recovers ~500 MB)

```bash
sudo logrotate -f /etc/logrotate.d/rsyslog
```

Effect: `/var/log/syslog` (670 MB) gets rotated → `.1` + compressed as `.2.gz` on next cycle; current syslog file becomes empty via `copytruncate`-free rotation (rsyslog uses signal-based rotation per its postrotate script). Oldest `syslog.4.gz` (34 MB) drops off.

Risk: **minimal**. rsyslog is designed for this exact flow. All running services keep writing without interruption. All historical lines are preserved compressed (and in journald independently). Net recovery: ~500 MB (670 MB active → ~150 MB rotated .1 after compression + removal of oldest .4.gz).

### R2 — Vacuum journald to 500 MB ceiling (recovers ~440 MB)

```bash
sudo journalctl --vacuum-size=500M
```

Effect: drops the oldest archived journal files until the on-disk store is ≤ 500 MB. Current ceiling is 1 GB; actual use is 941 MB.

Risk: **low**. Operator notes `journal retention requirements` must be identified first (per task §Phase 2). The journal is the ONLY place where some service-level audit lines (e.g. systemd state transitions, service start/stop records) exist long-term outside journald. If the operator has an SLA for 30+ days of journald history, this cannot be done. **Checked:** no `MaxRetentionSec` is set, so there is no formal retention policy; the implicit retention is governed by `SystemMaxUse` only. Reducing the cap is a config change, not a data-loss. The oldest discarded lines are from ~2026-10-15 (14 days back) based on the current store footprint.

### R3 — Move stale historical trade audit to attached volume (recovers 395 MB)

```bash
# Preserve audit record on attached volume; remove from root
mkdir -p /mnt/volume_lon1_1778405456698/trades_archive/
cp -p /opt/tradingbot/trades/strategy_log.csv /mnt/volume_lon1_1778405456698/trades_archive/strategy_log.csv.2026-01-01_to_2026-02-11
sha256sum /mnt/volume_lon1_1778405456698/trades_archive/strategy_log.csv.2026-01-01_to_2026-02-11
# After operator confirms the archive is readable:
rm /opt/tradingbot/trades/strategy_log.csv
```

Effect: **File has not been written to since 2026-02-11 (9 months ago)**. No active process holds it open (verified via `lsof` and the fact that the last line is 8 months+ before today). Current trading record flows go to `/opt/tradingbot/logs/*.jsonl`. This file is a stale ledger from an obsolete logging path.

Risk: **low but needs operator confirmation**. The file is a trade audit record — valuable but historical. Moving to attached volume preserves it fully.

### R4 — Vacuum /tmp session artefacts (recovers ~100 MB)

```bash
# My own Claude task-output files from this session + prior session
# (verify ownership: autobot:autobot)
ls -la /tmp/claude-1000/
# After operator approval, selectively remove task output files older than 1h
```

Risk: minimal; task outputs are ephemeral by design.

### R5 — Prune Claude session file-history on this box (recovers ~130 MB)

```bash
# Claude Code's cross-session file snapshots in /home/autobot/.claude/file-history
# Each dir represents one session; retention is cumulative with no cap
du -sh /home/autobot/.claude/file-history/*/  | sort -h
# Delete directories older than N days after operator approval
```

Risk: minimal; this is Claude's own transcript/file snapshot store. The current session is preserved by its own session-ID directory.

### Not performed (operator restriction)

- No deletion of `/home/autobot/tradingbot-wt/*` worktrees.
- No deletion of trading journals / broker records / historical candles / research evidence.
- No restart of production services.
- No truncation of actively-written logs (would miss writes).
- No change to the `autobot-jsonl` in-place rotation (operator design).

**Expected total immediate recovery (R1+R2+R3): ~1.4 GB** — just below the 2 GB target. If R4+R5 are also approved, the total is ~1.6 GB. Reaching 2 GB cleanly requires either (a) prune one older `/home/autobot/.claude/file-history/` session directory per operator discretion (~5 MB each × dozens = recoverable), or (b) accept R1+R2+R3 and defer the remaining 600 MB to the Phase 3 permanent fixes which will structurally hold rsyslog at a lower ceiling.

**If strictly 2 GB is required without approving R3**, the only remaining lever is deeper pruning of `/home/autobot/.claude/` or `/home/autobot/tradingbot-wt/` — both carry operator restrictions. Report and halt per §Phase 2 fallback.

---

## 8. Permanent storage and rotation corrections (Phase 3 — recommendations only)

### 8.1 Replace Ubuntu's default rsyslog policy

File: `/etc/logrotate.d/rsyslog`

```diff
 /var/log/syslog
 /var/log/mail.info
 ...
 {
-    rotate 4
-    weekly
+    rotate 7
+    daily
+    size 100M
     missingok
     notifempty
     compress
     delaycompress
     sharedscripts
     postrotate
         /usr/lib/rsyslog/rsyslog-rotate
     endscript
+    olddir /mnt/volume_lon1_1778405456698/syslog_rotated
+    createolddir 0755 syslog adm
 }
```

Effect:
- Rotate when the file reaches 100 MB OR daily, whichever first.
- Keep 7 generations (≈ 1 week of compressed logs on attached volume = ≈ 200 MB).
- Current log stays on root; everything older moves to attached volume.
- Dry-run check: `sudo logrotate -d /etc/logrotate.d/rsyslog`.

### 8.2 Lower journald ceiling + add free-space floor

File: `/etc/systemd/journald.conf`

```diff
 [Journal]
-SystemMaxUse=1G
+SystemMaxUse=500M
+SystemKeepFree=5G
+MaxRetentionSec=14d
```

Effect:
- Journal uses ≤ 500 MB.
- Journald will refuse to grow the journal if free disk would drop below 5 GB (safety against runaway).
- Keep 14 days of events only.

Apply via `sudo systemctl restart systemd-journald`.

**Alternative (recommended):** move the journal to the attached volume via `Storage=persistent` and bind-mount `/var/log/journal/` → `/mnt/volume_lon1_1778405456698/journal/`. More invasive; defer unless operator wants it.

### 8.3 Tighten btmp rotation

File: `/etc/logrotate.d/btmp`

```diff
 /var/log/btmp {
-    missingok
-    monthly
-    create 0660 root utmp
-    rotate 1
+    missingok
+    weekly
+    create 0660 root utmp
+    rotate 4
+    compress
+    delaycompress
 }
```

Effect: weekly rotation, 4 compressed generations. Fire-and-forget.

**Better fix (orthogonal):** add fail2ban or SSH key-only + port change. The 15 MB in two days of btmp is a brute-force attack signature.

### 8.4 Add rotation for sidecar strategy logs

File: `/etc/logrotate.d/strategy-sidecars` (new)

```
/opt/ema_pullback/logs/*.log
/opt/london_liquidity_sweep/logs/*.log
/home/autobot/ema_pullback/logs/*.log
{
    daily
    rotate 8
    maxsize 50M
    minsize 1M
    copytruncate
    compress
    delaycompress
    notifempty
    missingok
    dateext
    dateformat -%Y%m%d
    olddir /mnt/volume_lon1_1778405456698/logs_rotated
    createolddir 0755 autobot autobot
    su autobot autobot
}
```

Effect: covers the three gap paths with the same contract as `autobot-logs`.

### 8.5 Mount-dependency protection

For each unit that writes to the attached volume, add:

```
[Unit]
RequiresMountsFor=/mnt/volume_lon1_1778405456698
```

This prevents the service from starting if the volume is not mounted — stopping silent fallback to root fs. Already partially in place (several of the service units have `ReadOnlyPaths=/opt/tradingbot` + `ReadWritePaths=/mnt/volume_lon1_1778405456698/...`, which fails hard if the mount isn't there). The missing addition is explicit `RequiresMountsFor=`.

Services to protect:
- `live-market-observer.service`
- `live-market-observer-scenario-shadow.service`
- `live-market-observer-shadow-exec.service`
- `live-market-observer-dashboard.service`
- `live-scenario-notifier.service`
- `live-market-observer-news-refresh.service`

### 8.6 Archive and prune `/opt/tradingbot/trades/strategy_log.csv`

Already covered in R3. Permanent fix:
1. Move stale (not written in >30d) `strategy_log.csv` to `/mnt/.../trades_archive/`.
2. Add a quarterly archive sweep via systemd timer: files in `/opt/tradingbot/trades/` and `/opt/tradingbot/logs/` with no writes for 90 days move to `/mnt/.../trades_archive/` and `/mnt/.../logs_archive/`.

### 8.7 Prune Claude Code session artefacts

`/home/autobot/.claude/projects/*/` and `/home/autobot/.claude/file-history/*/` grow unbounded as new sessions run. Suggested caps:
- Keep file-history for last 14 days per session; move older to `/mnt/.../claude_archive/`.
- Keep `projects/*/history.jsonl` as-is (small) but prune session .json task-outputs older than 7 days.

This is Claude Code's own storage; the fix is a scheduled script, not a systemd service. Low priority.

---

## 9. Confirmed root cause

**Primary root cause:** `/var/log/syslog` grew to 670 MB because `/etc/logrotate.d/rsyslog` rotates WEEKLY. The weekly cadence is Ubuntu's default and has not been tuned for the write volume this box generates (every systemd-managed trading service writes to journald, which rsyslog mirrors to syslog). Over the last 6 days the file accumulated to ~670 MB.

**Secondary contributors (not misrouting, just accumulation):**
1. `/var/log/journal/` at 857 MB — journald honouring its 1 GB ceiling; the ceiling itself is high for a 25 GB root fs.
2. `/opt/tradingbot/trades/strategy_log.csv` at 395 MB — a stale audit record from 2026-01/02; no active writer; should have been archived to the attached volume long ago.
3. `/home/autobot/.claude/projects/-opt-tradingbot/` at 412 MB — Claude Code's cumulative session history across all my prior sessions.
4. `/home/autobot/tradingbot-wt/` at 6.3 GB — 114 operator-registered worktrees; off-limits per task restrictions.

**No AutoBot-family service is misrouting production logs to root.** The two services whose logs COULD have grown unbounded (AutoBot `.log` files, AutoBot `.jsonl` streams) are correctly managed by `/etc/logrotate.d/autobot-logs` and `/etc/logrotate.d/autobot-jsonl`. The `.log` rotation lands on the attached volume (operator-authored policy). The Live Market Observer and Scenario V2 write directly to the attached volume.

---

## 10. Correction 4 — status (resuming context)

C4 was fully deployed earlier in this session and remains operational:

| | |
|---|---|
| Scenario V2 modules | `scenario_quality.py` sha256 `4931aee2…` + `scenario_reasoner.py` sha256 `e10977e9…` (C4) |
| `scenario_recommendation.py` | sha256 `7edce8c9…` **unchanged** (C2 preserved) |
| Backup | `/mnt/.../agent/_backups/pre-c4-20261029T121526Z/` |
| Dashboard | PID 2276997, restarted 2026-10-29T12:22:46Z, Active, no errors |
| First post-C4 live sweep | 2026-10-29T12:21:04Z |
| Post-C4 scenario quality rows observed | 3 (all show C4 behaviour — zero `CATEGORY_A_TRIGGER_WITH_EVENT_NAME`, zero `UNSUPPORTED_CONFIDENCE_PERCENT`) |
| 20 new C4 regression tests | 20/20 PASS |
| Full existing suite under staging | 262/5 (identical to pre-C4 baseline) |
| Historical replay | 23 of 27 originally-INVALID 2026-10-29 revisions recovered to publishable |

**No further C4 work is needed from this investigation.** Phase 4 of the task brief is complete at the point this investigation started.

---

## 11. Deliverable checklist

- [x] Attached volume identification and mount health — §1
- [x] Root filesystem usage breakdown — §2
- [x] Logs currently stored on root — §3
- [x] Logs already stored on the attached volume — §4
- [x] Services using incorrect logging destinations — §5 (none)
- [x] Existing log-rotation configuration — §6
- [x] Safest immediate recovery procedure (ranked, operator-approval gates) — §7
- [x] Permanent storage and rotation corrections — §8
- [x] Confirmed root cause — §9
- [x] Correction 4 status — §10

**Nothing destructive has been performed. All recommendations in §7 and §8 require operator approval before execution.**
