# Scenario V2 Logging RCA + Stage 2 Deployment Procedure

**Date:** 2026-11-03
**Scope:** READ-ONLY investigation + staging. **No changes performed.**
**Trigger:** Operator-authorised. Before implementing Stage 2 log bind-mounts, investigate the 97.8% journal share from `live-market-observer-shadow-exec.service` and determine whether the root cause is a logging defect or an operational problem.

---

## Task A — Scenario V2 shadow-exec logging RCA

### A.1 Service identification

**Unit:** `/etc/systemd/system/live-market-observer-shadow-exec.service` + `.timer`
**Nature:** `Type=oneshot`, timer-driven **every 5 minutes**, 07:00–17:00 Europe/London on weekdays (≈120 fires/day during the active window).
**Function:** Research-only shadow trader for Scenario V2. Advances the shadow lifecycle on recent proposals.
**Broker contact:** None. ReadOnlyPaths=/opt/tradingbot, ReadWritePaths=/mnt/.../shadow_exec. No IG client, no AutoBot execution hook. Verified in prior audits.
**Latest fire:** 2026-11-03 10:25:19 UTC (5-second wall clock).

### A.2 Volume measurements

Captured during the active window (2026-11-03 ~10:25 UTC, operating at steady-state):

| Metric | Value |
|---|---:|
| Journal lines / hour (shadow-exec only) | **274,622** |
| Journal bytes / hour (short format) | **26.6 MB** |
| Lines per fire | **23,075** |
| Bytes per fire | **~2.2 MB** |
| Fires per hour | 12 |
| Fires per day (10h window) | 120 |
| Projected bytes / day in window | **~266 MB** |
| Share of all-journal volume (last 1h) | **97.80%** |

Rsyslog mirrors every journal line to `/var/log/syslog` by default (`ForwardToSyslog=yes` implicit), **doubling** the on-disk cost — once in journald (`/var/log/journal` + `/run/log/journal`, capped 500 MB) and once in `/var/log/syslog` (daily-rotated, bounded ~200 MB).

### A.3 Top message types and frequency

Per fire, the output breaks down as:

```
~2  lines   systemd Started/Deactivated banners (per activation)
~2  lines   wrapper banner: [shadow-exec] now_uk=... state=IN_WINDOW
                            [shadow-exec] sweep begin max_revisions=40
~23,071 lines  the single pretty-printed JSON report ← 99.98% of the volume
```

The JSON report has the schema `shadow_exec_sweep.v1`:

```json
{
  "schema": "shadow_exec_sweep.v1",
  "ran_at_utc": "...",
  "rows_processed": 40,
  "actions": [
    {
      "scenario_id": "...",
      "revision_idx": 18,
      "generated_at_utc": "...",
      "recommendation": "SELL",
      "readiness": "CONDITIONAL",
      "result": {
        "action": "PROPOSAL_ALREADY_EXISTS",
        "position": null,
        "readiness": "CONDITIONAL",
        "reason": "..."
      }
    },
    ... (×40)
  ],
  "summary": { ... }
}
```

A single JSON object spans ~23,071 lines because of `indent=2` pretty-printing: every key, bracket, comma, and value lives on its own line. systemd captures each newline as a separate journal entry (one timestamp + hostname + service prefix per line).

### A.4 Source of excessive output

**Exactly one line of code is responsible:**

```python
# /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.py:112
print(json.dumps(report, default=str, indent=2))
```

**Evidence that this is the ONLY source:**

```
$ grep -nE "^[^#]*print\(" /mnt/.../shadow_exec/*.py
run_shadow_exec.py:112:    print(json.dumps(report, default=str, indent=2))
```

That is the single `print()` statement in the shadow-exec entry point. No other Python logging infrastructure (no `logging.getLogger`, no `sys.stderr.write`, no explicit journal API). Everything else emitted to the journal is from the shell wrapper (3 lines) and systemd (2 lines).

### A.5 Categorical classification

| Category | Evidence | Verdict |
|---|---|---|
| Application-level logging | `logging` module not used anywhere in shadow-exec | — |
| **stdout emission** | **`print()` statement, 1 instance, line 112** | **YES — root cause** |
| stderr emission | None (wrapper uses stderr only on fatal path) | — |
| systemd service churn / restart loop | `NRestarts=0`; `ExecMainStatus=0`; `ActiveState=inactive` (clean oneshot) | — |
| Repeated exception handling (log-and-retry) | No `try/except` writing to log in the sweep code; `shadow_execution.process_proposal` is idempotent | — |
| journald/syslog duplication | **YES** — `ForwardToSyslog=yes` is systemd default; every line in journal is mirrored to `/var/log/syslog` | duplication confirmed |
| Operational problem (shadow-exec failing silently?) | Exit status 0 on every observed fire; `shadow_proposals.jsonl` growing normally; shadow trades being generated | **no operational problem** |

**This is NOT an error loop, NOT a reconcile loop, NOT a trading-logic issue.** It is purely verbose diagnostic output from one `indent=2` call.

### A.6 Smallest safe correction

**Change** `run_shadow_exec.py:112` from:

```python
print(json.dumps(report, default=str, indent=2))
```

to:

```python
print(json.dumps(report, default=str))
```

**Delete the `indent=2` kwarg.** Nothing else.

### A.7 What the correction preserves

| Audit property | Preserved? | How |
|---|---|---|
| Errors (exceptions from `process_proposal`) | **YES** | Python exceptions still raise → stderr → journal → syslog. systemd `ExecMainStatus != 0` on failure. |
| Warnings | **YES** | The JSON report's `result.reason` strings include `"CAUTION SELL …"`, `"WAIT suppressed by …"`, etc. — all preserved verbatim as JSON values. |
| Trade decisions | **YES** | `recommendation` field (BUY/SELL/WAIT), `readiness` field (VALID/CONDITIONAL/SUPPRESSED/INCOMPLETE/INVALID) — all preserved. |
| Rejected signals | **YES** | `result.action` values (`PROPOSAL_ALREADY_EXISTS`, `PROPOSAL_INVALID`, etc.) — preserved. |
| Audit telemetry | **YES** | `schema`, `ran_at_utc`, `rows_processed`, full `actions[]` array, `summary` sub-object — all preserved. |
| Operator grep access | **YES** | `journalctl -u live-market-observer-shadow-exec.service --output=cat` emits the single-line JSON; `jq` can filter. Example: `journalctl -u live-market-observer-shadow-exec.service --output=cat | jq '.actions[] | select(.recommendation == "SELL")'` |
| Content completeness | **YES** | JSON serialisation is identical — only whitespace / newlines removed. |

### A.8 What the correction does NOT change

- Scenario V2 trading logic (`agent/scenario_reasoner.py`, `agent/scenario_recommendation.py`) — unmodified
- Shadow execution lifecycle (`agent/shadow_execution.py`, `process_proposal`) — unmodified
- Decision thresholds (readiness/validity rules in `scenario_quality.py`) — unmodified
- Broker permissions — shadow-exec HAS no broker contact, so this is vacuously true
- Timer schedule (`live-market-observer-shadow-exec.timer`) — unmodified
- `shadow_proposals.jsonl`, `shadow_positions.jsonl`, `shadow_closed.jsonl`, `shadow_dedup.json` file-based persistence — all unaffected (the JSON report is only a mirror of what's already written to these files)

### A.9 Expected volume reduction

| Metric | Before | After | Reduction |
|---|---:|---:|---:|
| Lines / fire | 23,075 | ~5 (systemd + wrapper + 1 JSON dump + exit) | **~4,615×** |
| Bytes / fire | ~2.22 MB | ~1-2 KB | ~1,500× |
| Lines / hour (window) | 274,622 | ~60 | ~4,500× |
| Bytes / hour (window) | ~26.6 MB | ~13 KB | ~2,000× |
| Bytes / day (10h window) | ~266 MB | ~130 KB | ~2,000× |
| **Rsyslog mirror impact (same volume)** | **~266 MB/day on `/var/log/syslog`** | **~130 KB/day** | **~2,000×** |

**Compound effect on root-disk growth:**

- Current `/var/log/syslog` daily growth: ~45 MB mean, 230 MB peak
- Shadow-exec share of that: ~90-95% (confirmed by hourly sampling)
- After correction: syslog daily growth drops to ~5-10 MB/day baseline
- **Expected `/var/log/syslog*` family footprint:** steady state ~50 MB total (vs current ~360 MB)

### A.10 Deployment: smallest safe path

The file lives on `/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.py` — on the **attached volume**, not root. Shadow-exec is `Type=oneshot` fired every 5 min — the next fire reads the file afresh. **No service restart needed.** The timer's next fire picks up the new code.

Correction procedure (**NOT EXECUTED — awaiting approval**):

```bash
# 1. Backup
cp -av /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.py \
       /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.py.pre-indent-fix-$(date -u +%Y%m%dT%H%M%SZ)

# 2. One-line edit (sed in place, after verifying the exact line)
grep -n 'indent=2' /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.py
# Expect line 112: `    print(json.dumps(report, default=str, indent=2))`
sed -i 's/print(json.dumps(report, default=str, indent=2))/print(json.dumps(report, default=str))/' \
    /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.py

# 3. Verify
grep -n 'json.dumps' /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/run_shadow_exec.py
# Expect line 112: `    print(json.dumps(report, default=str))`

# 4. Wait for next 5-min timer fire (max 5 min)
systemctl list-timers live-market-observer-shadow-exec.timer

# 5. Verify next fire produces compact output
LAST=$(systemctl show live-market-observer-shadow-exec.service -p ExecMainStartTimestamp --value)
# wait for next fire, then:
NEW=$(systemctl show live-market-observer-shadow-exec.service -p ExecMainStartTimestamp --value)
journalctl -u live-market-observer-shadow-exec.service --since "$NEW" --no-pager | wc -l
# Expect: ~5 lines (not ~23,000)
```

**Rollback:**

```bash
cp -av /mnt/.../run_shadow_exec.py.pre-indent-fix-<TS> /mnt/.../run_shadow_exec.py
# No service restart; next 5-min fire reverts
```

---

## Task B — Stage 2 migration readiness

### B.1 Path validation

| Path | State | Owner | Mode | Note |
|---|---|---|---|---|
| `/opt/tradingbot/logs/` | EXISTS | autobot:autobot | **drwxr-xr-x (755)** | source — autobot's primary log dir |
| `/opt/ema_pullback/logs/` | EXISTS | autobot:autobot | **drwxr-x--- (750)** | source — ema-pullback (more restrictive!) |
| `/mnt/volume_lon1_1778405456698/autobot-logs/` | **MISSING** | — | — | will be created in Step A |
| `/mnt/volume_lon1_1778405456698/ema-pullback-logs/` | **MISSING** | — | — | will be created in Step A |
| `/mnt/volume_lon1_1778405456698/syslog_archive/` | **MISSING** | — | — | will be created in Step A (for Step F weekly sweep) |

**Correction to prior plan:** `/opt/ema_pullback/logs/` is **mode 0750** (not 0755). Destination directory must be created with matching mode or ema-pullback's `ProtectSystem=strict` + `ReadWritePaths` sandbox will reject writes.

### B.2 Open file descriptors (will need service restart)

| Service | PID | Open writable fds in affected dirs |
|---|---:|---|
| autobot.service | 3337630 | `diagnostics.log`, `bb_reversal.log` |
| ema-pullback.service | 2514532 | `ema_pullback.log` |
| bb-bounce.service | 2400402 | **none** (journal only) |
| trades-api.service | 2793845 | **none** (journal only) |

**Scanned all other autobot-user processes for open fds in these dirs — none.** Only the 4 trading services write here; only 2 (autobot + ema-pullback) hold persistent fds.

### B.3 Current systemd mount dependencies (gap identified)

```
autobot.service      RequiresMountsFor=/opt/tradingbot                   ← does NOT include /mnt
ema-pullback.service RequiresMountsFor=/opt/ema_pullback /var/tmp         ← does NOT include /mnt
bb-bounce.service    (no explicit mount dependency)
trades-api.service   (no explicit mount dependency)
```

**None of the 4 services currently require `/mnt`.** This is the gap Step B closes.

### B.4 fstab validation

```
/dev/disk/by-id/scsi-0DO_Volume_volume-lon1-1778405456698 /mnt/volume_lon1_1778405456698 ext4 defaults,nofail,discard 0 0
/mnt/volume_lon1_1778405456698/swapfile none swap sw 0 0
```

Volume mounts via stable `by-id` path with `nofail,discard` — survives DO reattach. Swap file lives on the volume — a key dependency that already requires volume availability for memory headroom (though does not block boot).

### B.5 Script path-dependency scan

**Hard-coded references to `/opt/tradingbot/logs/`:**

| Reference | Impact under bind-mount |
|---|---|
| `/opt/tradingbot/autobot.py` (main code) | Transparent — bind-mount keeps path identical |
| `/opt/tradingbot/_verify_news_tier_step1.py` | Transparent |
| `/opt/tradingbot/backtest_briefing_tp.py` | Transparent |
| `/opt/tradingbot/_verify_stretch_brake.py` | Transparent |
| `/opt/tradingbot/backtest_replay.py` | Transparent |
| `/etc/systemd/system/autobot.service.d/ownership-heal.conf` → `chown -R autobot:autobot /opt/tradingbot/logs` | Transparent — chown works via bind to /mnt |
| `/etc/systemd/system/autobot.service.d/env-drift.conf` → `>> /opt/tradingbot/logs/env_drift.log` | Transparent |
| `/etc/systemd/system/forensic-backfill.service` → writes freshness marker under `/opt/tradingbot/logs/` | Transparent |
| `/etc/systemd/system/batch2-outcome-grader.service` → reads/writes `/opt/tradingbot/logs/qm_candidates*.jsonl` | Transparent |
| `/etc/logrotate.d/autobot-{jsonl,logs}`, `/etc/logrotate.d/strategy-sidecars` | Transparent — logrotate operates on paths, not devices |

**Hard-coded references to `/opt/ema_pullback/logs/`:**

| Reference | Impact |
|---|---|
| `/etc/systemd/system/ema-pullback.service` → `ReadWritePaths=/opt/ema_pullback/state /opt/ema_pullback/logs /opt/ema_pullback/reports` | Compatible — systemd `ReadWritePaths` honours bind-mounts (per systemd.exec(5): "If a listed path is a mount point then that mount point is made writable, regardless of filesystem options") |
| `/opt/ema_pullback/.env.example` | Documentation only, not consumed |

**Filesystem-boundary assumptions:** Zero hits for `-xdev`, "cross device", or "same filesystem" in `/opt/tradingbot/*.py` or `/opt/ema_pullback/`. No code assumes same-FS for log paths.

**Verdict:** No script needs updating. Bind-mounts are transparent at the path level.

### B.6 Space verification

```
Current /opt/tradingbot/logs:   141 MB
Current /opt/ema_pullback/logs:  296 KB
/mnt free:                        64 GB   (ample — >400× headroom)
```

### B.7 Ownership-heal interaction

The autobot `ownership-heal.conf` drop-in runs `chown -R autobot:autobot /opt/tradingbot/logs` on **every service start** (prefixed with `+` to run as root). Under a bind-mount, this `chown -R` traverses the mounted target on /mnt, re-chowning ~140 MB of files. Timing: should complete in <5 seconds on local SSD. No functional problem. Monitor startup time on first post-mount restart.

If startup becomes measurably slower, operator may consider restricting the chown scope (e.g. `--from=root:root` to only reset root-owned entries). Deferred decision; not blocking.

### B.8 journald interaction

- `/etc/systemd/journald.conf.d/50-autobot-rotation.conf` caps journald at 500 MB.
- journald lives in `/var/log/journal/` (persistent on root fs) + `/run/log/journal/` (tmpfs).
- Stage 2 bind-mounts do NOT change journald.
- **Scenario V2 fix (Task A, line 112)** reduces journald growth by ~2000× — amplifies the Stage 2 benefit.

---

## Task B.9 — Final Stage 2 deployment procedure (NOT executed)

Updated from the Stage 2 preflight plan with Task A/B refinements.

### Prerequisites (operator-attestable before Step A)

- [ ] Scenario V2 shadow-exec correction (Task A) deployed and verified for at least one timer cycle
- [ ] Root fs ≥ 2 GB free
- [ ] /mnt mounted + writable + ≥ 1 GB free
- [ ] All 4 trading services active
- [ ] NMS C1+C2+C6 flags live in autobot process
- [ ] C6 midnight verification checklist present and untouched
- [ ] Service `live-market-observer-shadow-exec.service` producing <10 lines per fire (verifies Task A took effect)

### Step 0 — Pre-flight (verification only)

```bash
# Attest preconditions
df -h /
df -h /mnt/volume_lon1_1778405456698
systemctl is-active autobot.service bb-bounce.service trades-api.service ema-pullback.service

APID=$(systemctl show autobot.service -p MainPID --value)
cat /proc/$APID/environ | tr '\0' '\n' | grep NMS_V3_C | sort
# Expect: C1=1, C2=1, C6=1

# Attest Task A result (shadow-exec quiet)
LAST=$(systemctl show live-market-observer-shadow-exec.service -p ExecMainStartTimestamp --value)
journalctl -u live-market-observer-shadow-exec.service --since "$LAST" --no-pager | wc -l
# Expect: < 20 lines (vs ~23,075 pre-fix)

# Snapshot current baseline
BACKUP=/mnt/volume_lon1_1778405456698/autobot-nms-deploy-20261103
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP/pre-stage2-logs-$TS"
sha256sum /opt/tradingbot/nms_v3_classifier.py /opt/tradingbot/session_trend.py /opt/tradingbot/.env \
          > "$BACKUP/pre-stage2-logs-$TS/hashes.txt"
```

### Step A — Prepare destinations + rsync (zero downtime)

```bash
# Create destinations with CORRECT ownership + mode
sudo install -d -o autobot -g autobot -m 0755 /mnt/volume_lon1_1778405456698/autobot-logs
sudo install -d -o autobot -g autobot -m 0750 /mnt/volume_lon1_1778405456698/ema-pullback-logs       # note: 0750!
sudo install -d -o autobot -g autobot -m 0755 /mnt/volume_lon1_1778405456698/syslog_archive

# Rsync preserve ownership + timestamps + xattrs
sudo rsync -aHAX --info=progress2 /opt/tradingbot/logs/ /mnt/volume_lon1_1778405456698/autobot-logs/
sudo rsync -aHAX --info=progress2 /opt/ema_pullback/logs/ /mnt/volume_lon1_1778405456698/ema-pullback-logs/

# Verify byte-identity
sudo diff -r --no-dereference /opt/tradingbot/logs/ /mnt/volume_lon1_1778405456698/autobot-logs/ | head -10
sudo diff -r --no-dereference /opt/ema_pullback/logs/ /mnt/volume_lon1_1778405456698/ema-pullback-logs/ | head -10
# Expect: empty

# File count parity
echo "autobot: $(find /opt/tradingbot/logs -type f | wc -l) → $(find /mnt/volume_lon1_1778405456698/autobot-logs -type f | wc -l)"
echo "ema-pb:  $(find /opt/ema_pullback/logs -type f | wc -l) → $(find /mnt/volume_lon1_1778405456698/ema-pullback-logs -type f | wc -l)"
# Expect: counts match
```

### Step B — Install systemd mount-dependency drop-ins (zero downtime)

```bash
# autobot
sudo tee /etc/systemd/system/autobot.service.d/mount-dep.conf <<'EOF'
[Unit]
RequiresMountsFor=/mnt/volume_lon1_1778405456698
EOF

# ema-pullback
sudo mkdir -p /etc/systemd/system/ema-pullback.service.d
sudo tee /etc/systemd/system/ema-pullback.service.d/mount-dep.conf <<'EOF'
[Unit]
RequiresMountsFor=/mnt/volume_lon1_1778405456698
EOF

# bb-bounce
sudo tee /etc/systemd/system/bb-bounce.service.d/mount-dep.conf <<'EOF'
[Unit]
RequiresMountsFor=/mnt/volume_lon1_1778405456698
EOF

# trades-api
sudo mkdir -p /etc/systemd/system/trades-api.service.d
sudo tee /etc/systemd/system/trades-api.service.d/mount-dep.conf <<'EOF'
[Unit]
RequiresMountsFor=/mnt/volume_lon1_1778405456698
EOF

sudo systemctl daemon-reload

# Verify (dependency visible but takes effect on next start)
systemctl show autobot.service -p RequiresMountsFor
# Expect to include: /mnt/volume_lon1_1778405456698
```

### Step C — fstab bind-mount entries (zero downtime)

```bash
sudo tee -a /etc/fstab <<'EOF'

# 2026-11-03 Stage 2 — bind-mount autobot + ema-pullback logs onto attached volume
/mnt/volume_lon1_1778405456698/autobot-logs       /opt/tradingbot/logs       none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
/mnt/volume_lon1_1778405456698/ema-pullback-logs  /opt/ema_pullback/logs     none  bind,x-systemd.requires-mounts-for=/mnt/volume_lon1_1778405456698,nofail  0 0
EOF

# Validate fstab syntax without activating
sudo mount -a --fake
# Expect: no errors
```

### Step D — autobot bind + restart (~10 sec downtime for autobot only)

```bash
# Idempotent snapshot of pre-restart state
TS=$(date -u +%Y%m%dT%H%M%SZ)
cp /opt/tradingbot/cache/session_trend_state.json "$BACKUP/pre-stage2-logs-$TS/"

# Stop autobot (releases diagnostics.log + bb_reversal.log fds)
sudo systemctl stop autobot.service

# Confirm no process holds files in /opt/tradingbot/logs/
sudo lsof +D /opt/tradingbot/logs/ 2>&1 | head
# Expect: no autobot python

# Rename old dir as safety net
sudo mv /opt/tradingbot/logs /opt/tradingbot/logs.pre-bind-$TS
sudo install -d -o autobot -g autobot -m 0755 /opt/tradingbot/logs

# Activate bind
sudo mount /opt/tradingbot/logs

# Verify bind
mountpoint /opt/tradingbot/logs    # expect: "is a mountpoint"
stat -c '%d %n' /opt/tradingbot/logs /mnt/volume_lon1_1778405456698/autobot-logs
# Expect: both device IDs match

# Start autobot
sudo systemctl start autobot.service
sleep 15
systemctl status autobot.service --no-pager | head -5

# Verify C1+C2+C6 live
cat /proc/$(systemctl show autobot.service -p MainPID --value)/environ | tr '\0' '\n' | grep NMS_V3_C
# Expect:
#   NMS_V3_C1_CORRECTED_RECLAIM=1
#   NMS_V3_C2_DIRECTIONAL_PENALTY=1
#   NMS_V3_C6_DAYROLL_RESET=1

# Verify no broker action
stat -c '%y %n' /opt/tradingbot/logs/signal_log.jsonl
# Expect: mtime 2026-10-30 (unchanged)

# After 5 min, verify new writes land under /mnt
sleep 310
ls -la --time-style=full-iso /mnt/volume_lon1_1778405456698/autobot-logs/v3_events.jsonl
# Expect: mtime advanced past the restart
```

### Step E — ema-pullback bind + restart (~10 sec downtime for ema-pullback only)

```bash
sudo systemctl stop ema-pullback.service
sudo lsof +D /opt/ema_pullback/logs/ 2>&1 | head

TS=$(date -u +%Y%m%dT%H%M%SZ)
sudo mv /opt/ema_pullback/logs /opt/ema_pullback/logs.pre-bind-$TS
sudo install -d -o autobot -g autobot -m 0750 /opt/ema_pullback/logs    # note: 0750

sudo mount /opt/ema_pullback/logs
mountpoint /opt/ema_pullback/logs

sudo systemctl start ema-pullback.service
sleep 15
systemctl status ema-pullback.service --no-pager | head -5

# Verify writes land under /mnt
sleep 60
ls -la --time-style=full-iso /mnt/volume_lon1_1778405456698/ema-pullback-logs/ema_pullback.log
# Expect: mtime recent
```

### Step F — Syslog archive timer install (zero downtime)

```bash
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
systemctl list-timers syslog-archive.timer
```

### Step G — Disk-free warn timer (zero downtime)

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

# Trigger once for sanity
sudo systemctl start disk-free-warn.service
journalctl -t disk-free-warn -n 5
# Expect: silent if free > threshold
```

---

## Expected total downtime

| Step | Service(s) affected | Downtime |
|---|---|---|
| 0 | none | 0 |
| A | none | 0 (rsync is read-only on source) |
| B | none | 0 (daemon-reload only) |
| C | none | 0 (fstab edit, no activation) |
| **D** | **autobot.service** | **~10 seconds** |
| **E** | **ema-pullback.service** | **~10 seconds** |
| F | none | 0 |
| G | none | 0 |

**Total production disruption: ~20 seconds, non-concurrent, across 2 services.** bb-bounce + trades-api are NOT restarted. No broker action.

---

## Rollback (per-step)

Each step rolls back independently via `umount` + fstab edit + rsync-back from the renamed `.pre-bind-<TS>` directory. See prior Stage 2 preflight § 8 for commands. Rollback does not require code changes.

---

## Combined effect — Scenario V2 fix + Stage 2 bind-mounts

| Component | Before | After both | Reduction |
|---|---:|---:|---:|
| journald growth / day | ~500 MB (shadow-exec dominant) | ~50 MB | ~90% |
| `/var/log/syslog*` growth / day | ~45 MB mean, 230 MB peak | ~5-10 MB mean, no spikes | ~90% |
| `/opt/tradingbot/logs/` growth / day on root | ~60 MB | **0 MB** (bind-mount redirects to /mnt) | 100% |
| `/opt/ema_pullback/logs/` growth / day on root | ~0.5 MB | **0 MB** | 100% |
| **Daily root growth total (post-Stage-2 + Task A)** | **~110 MB/day** | **~5-10 MB/day** | **~95%** |

From the current 7.0 GB free, projected root burn after both fixes:
- At ~10 MB/day → ~2 years before hitting 2 GB alert threshold
- OS updates + occasional operator work make this effectively "sustainable"

---

## C1+C2+C6 preservation guarantee

Pre-execution attestation (prerequisite):
```
sha256sum /opt/tradingbot/nms_v3_classifier.py   # expect f690fb9c…
sha256sum /opt/tradingbot/session_trend.py       # expect f4aceeee…
sha256sum /opt/tradingbot/.env                   # expect 5903ab0f…
```

Post-Step-D verification:
```
cat /proc/<new-pid>/environ | tr '\0' '\n' | grep NMS_V3_C
# Must still show C1=1, C2=1, C6=1
```

Any mismatch is a FAIL — operator should rollback Step D immediately.

**C6 midnight verification checklist** at `/opt/tradingbot/reports-public/c6_midnight_verification_20261104/CHECKLIST.md` is NOT touched by any step. Verified mtime at report write: `2026-11-03 09:48:07.855Z`.

---

## Nothing executed in this task

```
$ df -h /
/dev/vda1   25G   18G  7.0G  71% /    ← unchanged from Stage 1 completion

$ systemctl show autobot.service -p MainPID -p ActiveEnterTimestamp
MainPID=3337630
ActiveEnterTimestamp=Tue 2026-11-03 09:41:14 UTC    ← no new restart

$ sha256sum /opt/tradingbot/nms_v3_classifier.py /opt/tradingbot/session_trend.py /opt/tradingbot/.env
f690fb9c…  /opt/tradingbot/nms_v3_classifier.py
f4aceeee…  /opt/tradingbot/session_trend.py
5903ab0f…  /opt/tradingbot/.env

$ stat -c '%y %n' /opt/tradingbot/reports-public/c6_midnight_verification_20261104/CHECKLIST.md
2026-11-03 09:48:07.855546812 +0000   ← untouched
```

- No files moved, copied, deleted, truncated, compressed, bind-mounted, or symlinked.
- No service restarted.
- No `systemctl`, `mount`, `umount`, `fstab` edit, drop-in installed, logrotate config changed, python source edited.
- No broker action.
- All numbers above are proposals pending operator approval.

---

## Approval needed

**Request:**

1. **Task A — single-line Python edit on `/mnt/.../run_shadow_exec.py:112` deleting `, indent=2`.**
   - Zero downtime, no service restart, immediate effect on next 5-min timer fire.
   - Preserves all errors/warnings/trade decisions/rejected signals/audit telemetry.

2. **Stage 2 — Steps A–G as detailed above.**
   - Should be executed AFTER Task A so that `/var/log/syslog` growth has calmed and bind-mount sizing/soak reflects normal volume.
   - ~20 seconds total production disruption across autobot + ema-pullback restarts (non-concurrent).

**Stopping before implementation. Awaiting approval.**
