# Operator-run Phase 2 + Phase 3 commands

**Context:** autobot has no passwordless sudo. The commands below require operator execution. Each block is independent and verifiable.

**Measurement anchor (pre-change state):**
```
/dev/vda1  25G  23G  1.4G  95%  /                     (root fs)
/dev/sda  100G  23G   72G  25%  /mnt/volume_lon1_...  (attached vol)
```

Run each block via the `! ...` prefix in your next prompt. After each, the output lands in this conversation and I will verify + proceed.

---

## Block A — Immediate recovery (Phase 2 R1 + R2)

**Scope:** force rsyslog rotation + vacuum journald. Recovers ~940 MB.

```
sudo logrotate -f /etc/logrotate.d/rsyslog && \
sudo journalctl --vacuum-size=500M && \
df -h / && \
ls -la /var/log/syslog /var/log/syslog.1* 2>/dev/null && \
journalctl --disk-usage
```

Expected result:
- `/var/log/syslog` becomes small (new file, rsyslog reopened via SIGHUP).
- `/var/log/syslog.1` or `.1.gz` appears as the just-rotated 670 MB.
- Previous `.1.gz` → `.2.gz`, etc. Oldest `.4.gz` dropped.
- `journalctl --disk-usage` reports ≤ 500 MB.
- Expected `/` after: ~2.3 GB free (gain of ~900 MB).

---

## Block B — Phase 2 R3 cleanup (removal of already-archived strategy_log.csv)

**Scope:** remove `/opt/tradingbot/trades/strategy_log.csv` AFTER the archive at `/mnt/.../trades_archive/` has been operator-verified. Recovers ~395 MB.

**Pre-check (safe — no changes):**
```
sha256sum /opt/tradingbot/trades/strategy_log.csv /mnt/volume_lon1_1778405456698/trades_archive/strategy_log.csv.archive-2026-01-08_to_2026-02-11 && \
cat /mnt/volume_lon1_1778405456698/trades_archive/strategy_log.csv.archive-2026-01-08_to_2026-02-11.manifest
```

Expected: both hashes identical `2acf4794af88e51290f2d4cd32e60584a1d44300f408d52e16b9da8bcf08123c`.

**Removal (destructive):**
```
rm /opt/tradingbot/trades/strategy_log.csv && \
df -h / && \
ls -la /opt/tradingbot/trades/
```

Note: `rm` runs as autobot (no sudo needed — autobot owns `/opt/tradingbot/trades/`). I did not perform this step automatically because operator Phase 2 §3 requires explicit per-step approval ("Do not remove the original until all checks pass").

Expected: `/` after ≈ 2.7 GB free (gain of ~400 MB).

---

## Block C — Install Phase 3 config files

**Scope:** copy staged configs into system paths; `daemon-reload`; validate.

Prerequisites (staging worktree already contains the files):

```
# Verify staging files exist and are syntactically valid
ls /home/autobot/reports-wt/disk-root-cause-20261029/disk-root-cause-20261029/staging/logrotate.d/ && \
ls /home/autobot/reports-wt/disk-root-cause-20261029/disk-root-cause-20261029/staging/journald.conf.d/ && \
find /home/autobot/reports-wt/disk-root-cause-20261029/disk-root-cause-20261029/staging/systemd.system/ -type f
```

Install (file copies + daemon-reload — NO service restarts):

```
sudo install -m 0644 -o root -g root \
    /home/autobot/reports-wt/disk-root-cause-20261029/disk-root-cause-20261029/staging/logrotate.d/rsyslog \
    /etc/logrotate.d/rsyslog && \
sudo install -m 0644 -o root -g root \
    /home/autobot/reports-wt/disk-root-cause-20261029/disk-root-cause-20261029/staging/logrotate.d/strategy-sidecars \
    /etc/logrotate.d/strategy-sidecars && \
sudo mkdir -p /etc/systemd/journald.conf.d && \
sudo install -m 0644 -o root -g root \
    /home/autobot/reports-wt/disk-root-cause-20261029/disk-root-cause-20261029/staging/journald.conf.d/50-autobot-rotation.conf \
    /etc/systemd/journald.conf.d/50-autobot-rotation.conf && \
for svc in live-market-observer live-market-observer-scenario-shadow live-market-observer-shadow-exec live-market-observer-shadow live-market-observer-dashboard live-market-observer-news-refresh live-scenario-notifier; do
    sudo mkdir -p /etc/systemd/system/${svc}.service.d && \
    sudo install -m 0644 -o root -g root \
        /home/autobot/reports-wt/disk-root-cause-20261029/disk-root-cause-20261029/staging/systemd.system/${svc}.service.d/50-mount-requires.conf \
        /etc/systemd/system/${svc}.service.d/50-mount-requires.conf
done && \
sudo systemctl daemon-reload && \
echo "DONE — files installed; daemon reloaded. No services restarted."
```

Validate (post-install):

```
# logrotate dry-runs now at the real paths
sudo logrotate -d /etc/logrotate.d/rsyslog 2>&1 | tail -5 && \
sudo logrotate -d /etc/logrotate.d/strategy-sidecars 2>&1 | tail -5 && \
# systemd drop-ins visible
systemctl show live-market-observer.service -p RequiresMountsFor && \
systemctl show live-market-observer-scenario-shadow.service -p RequiresMountsFor
```

Expected `RequiresMountsFor=` output: `/mnt/volume_lon1_1778405456698`.

---

## Block D — Apply journald config change

**Scope:** restart systemd-journald to apply the new drop-in. Brief ~100 ms interruption of journal capture. No trading-service restarts.

```
sudo systemctl restart systemd-journald && \
sudo systemctl status systemd-journald --no-pager | head -5 && \
journalctl --disk-usage
```

Expected: journalctl prints "Archived and active journals take up ~500M in the file system." (`SystemMaxUse=500M` immediately enforced).

---

## Block E — Final verification

```
echo '--- Disk ---' && \
df -h / /mnt/volume_lon1_1778405456698 && \
echo '--- Root fs top files ---' && \
sudo find / -xdev -type f -size +100M -printf '%s %p\n' 2>/dev/null | sort -nr | head -10 && \
echo '--- journald ---' && \
journalctl --disk-usage && \
sudo journalctl --header 2>&1 | grep -E 'Max Use|Max File Size|Keep Free' | head -5 && \
echo '--- rsyslog rotation state ---' && \
ls -la /var/log/syslog* && \
echo '--- Drop-in mount deps ---' && \
systemctl show live-market-observer.service -p RequiresMountsFor && \
echo '--- Services unchanged (ExecMainStartTimestamp should match earlier C4 values) ---' && \
systemctl show live-market-observer.service live-market-observer-dashboard.service -p ExecMainStartTimestamp --value
```

Expected final state:
- `/dev/vda1` ≤ 80% used (target).
- journald ≤ 500 MB.
- `/var/log/syslog` reset to small size.
- `strategy_log.csv` either present at archive location only (if Block B run) or still present on both root + archive.
- All live-market-observer* services show `RequiresMountsFor=/mnt/volume_lon1_1778405456698`.
- Service start timestamps unchanged — no trading-service restart.

---

## Rollback (if any step is unexpected)

```
# Logrotate: restore Ubuntu defaults from APT package
sudo apt-get install --reinstall rsyslog
sudo rm -f /etc/logrotate.d/strategy-sidecars

# Journald: remove drop-in + restart
sudo rm /etc/systemd/journald.conf.d/50-autobot-rotation.conf
sudo systemctl restart systemd-journald

# Mount requires: remove the drop-in dir contents (don't rmdir the service.d dirs — they may have other drop-ins)
for svc in live-market-observer live-market-observer-scenario-shadow live-market-observer-shadow-exec live-market-observer-shadow live-market-observer-dashboard live-market-observer-news-refresh live-scenario-notifier; do
    sudo rm -f /etc/systemd/system/${svc}.service.d/50-mount-requires.conf
done
sudo systemctl daemon-reload

# strategy_log.csv: restore from archive if removed and later needed
cp -p /mnt/volume_lon1_1778405456698/trades_archive/strategy_log.csv.archive-2026-01-08_to_2026-02-11 /opt/tradingbot/trades/strategy_log.csv
```
