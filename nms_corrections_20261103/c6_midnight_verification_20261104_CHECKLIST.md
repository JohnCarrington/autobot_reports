# C6 Midnight Rollover Verification Checklist

**Trigger window:** 2026-11-04 00:00:00 UTC → 00:10:00 UTC
**Owner:** operator (must be run or observed by a human session)
**Reason:** Phase A deployed `NMS_V3_C6_DAYROLL_RESET=1` on 2026-11-03 09:09:58 UTC. The isolated end-to-end rollover test PASSED against production code, but **actual production rollover has not been observed yet**. The first opportunity is Tue→Wed UTC midnight at 2026-11-04 00:00:00 UTC. This checklist must not be lost.

**Status (as of 2026-11-03 09:45 UTC):** OUTSTANDING — not yet verified.

---

## Pre-flight (should already hold)

- [ ] autobot.service is active and the running process has `NMS_V3_C6_DAYROLL_RESET=1` in `/proc/<pid>/environ`
- [ ] `/opt/tradingbot/.env` contains `NMS_V3_C6_DAYROLL_RESET=1`
- [ ] `/opt/tradingbot/session_trend.py` sha256 is `f4aceeee8c9c3665f666fac5c3e59c99c15b7e5f2594472788f0ff7c49d2cf83`
- [ ] `/opt/tradingbot/nms_v3_classifier.py` sha256 is `f690fb9c3f3bf16f3423bb7b1f9f8767dcb6a2f3bf1e40dec55c11f9105d4a8b` (post-Phase-B)
- [ ] No restarts of autobot.service between now and 00:00 UTC on 2026-11-04 (restart would resynthesize state via `restore_from_disk` and C6 should still work the same, but keep it clean)

## 00:05 UTC verification (one bar after rollover)

Run at or after `2026-11-04 00:05:30 UTC`:

```bash
# 1. Confirm the running autobot is still the pre-rollover process
systemctl show autobot.service -p MainPID -p ActiveEnterTimestamp

# 2. Live state file
python3 -c "
import json
d = json.load(open('/opt/tradingbot/cache/session_trend_state.json'))
s = d.get('states') or d
if isinstance(s, dict) and 'states' in s: s = s['states']
for sym in ('GBPUSD','EURUSD','USDJPY','USDCAD'):
    r = s.get(sym, {})
    v3 = r.get('v3_state')
    outer = r.get('session_date')
    inner = v3.get('session_date') if isinstance(v3, dict) else None
    state = v3.get('state') if isinstance(v3, dict) else None
    print(f'{sym}: outer={outer}  v3_inner={inner}  v3_state={state}  outer==inner? {outer==inner}')
    print(f'  last_session_v3: {r.get(\"last_session_v3\")}')
"

# 3. Live symbol snapshots
for S in GBPUSD EURUSD USDJPY USDCAD; do
  python3 -c "
import json
d = json.load(open('/opt/tradingbot/cache/session_trend_${S}.json'))
print('${S}: v3_state=', d.get('v3_state'), 'v3_state_since_ts=', d.get('v3_state_since_ts'), 'session_date=', d.get('session_date'), 'evaluation_ts=', d.get('evaluation_ts'))
"
done
```

### Expected results

For every symbol after the first bar on 2026-11-04:

- [ ] **outer `session_date == "2026-11-04"`** (bar date rollover already handled pre-C6)
- [ ] **inner `v3_state.session_date == "2026-11-04"`** (THIS IS THE C6 FIX — must agree with outer)
- [ ] **`outer == inner` returns `True`** for all 4 symbols
- [ ] `last_session_v3` is populated and contains Tue 2026-11-03's final summary: `{session_date: "2026-11-03", state: "RANGE" or whatever Tue ended as, state_since: ..., london_bars_count: N, range_reversals_count: N}`
- [ ] `v3_state_since_ts` for each symbol shows a Wed 2026-11-04 timestamp (NOT a stale Mon/Tue one)
- [ ] `v3_state` for each symbol is one of `NORMAL` / `RANGE` (lazy-init via `fresh_state` on first Wed bar → classifier produces its normal first-bar label)

### Red flags (any of these = FAIL — must rollback or escalate)

- outer_session_date is 2026-11-04 but any inner v3_state.session_date is still 2026-11-03 or earlier → C6 did not fire
- `last_session_v3` is `<unset>` or `null` for all four symbols after 00:05 UTC → C6 code path not reached
- autobot.service became inactive/failed/activating-auto-restart during the rollover window
- Any ERROR/Traceback/CRITICAL in `journalctl -u autobot.service --since "2026-11-03 23:55"`
- Snapshot evaluation_ts has NOT advanced past 2026-11-04 00:00 — classifier is stuck
- Live cache files not written for ≥ 10 minutes after rollover

## Service health at verification time

```bash
systemctl is-active autobot.service bb-bounce.service trades-api.service ema-pullback.service
df -h /
journalctl -u autobot.service --since "2026-11-03 23:55:00" --until "2026-11-04 00:15:00" | grep -cE '\[ERROR\]|Traceback|CRITICAL'
stat -c '%y %n' /opt/tradingbot/logs/signal_log.jsonl  # should NOT have grown unexpectedly
```

### Expected

- [ ] All 4 services `active`
- [ ] Disk free ≥ 500 MB (not a hard requirement for verification, but note headroom)
- [ ] Zero new ERROR/Traceback/CRITICAL lines beyond the known benign PRELOAD/USDCAD-USDJPY epic warnings and transient IG REST reconcile blips
- [ ] signal_log.jsonl: if autobot started trading overnight, note any new entries and attribute them (do not blame C6 for an EMERGING-admitted H161 trade; those are from C1+C2)

## Classifier output sanity check at 00:30 UTC

Run at ~00:30 UTC when 6 Wed bars have accumulated:

```bash
grep '"bar_ts": "2026-11-04T00:' /opt/tradingbot/logs/trend_v3.jsonl | tail -5
cat /opt/tradingbot/cache/session_trend_GBPUSD.json | python3 -m json.tool | grep -E 'v3_state|v3_up_score|v3_down_score|v3_state_since'
```

### Expected

- [ ] trend_v3 blocks for `2026-11-04T00:{05,10,15,20,25}:00+00:00` bars present
- [ ] `v3_state=RANGE` or `NORMAL` (pre-London), `up_score` and `down_score` both near zero (fresh state has no accumulated evidence yet)
- [ ] `v3_state_since_ts` reflects the Wed first-bar timestamp, NOT a stale Tue/Mon ts

## If verification PASSES

- [ ] Edit this file: change the "Status" line at top to `VERIFIED` and add `**verified_by:** <operator name>  **verified_at:** <UTC ts>`
- [ ] Commit the updated checklist to `report/nms-corrections-20261103` branch:
  ```bash
  cd /mnt/volume_lon1_1778405456698/tradingbot-wt/reports-nms-corrections-20261103
  cp /opt/tradingbot/reports-public/c6_midnight_verification_20261104/CHECKLIST.md \
     nms_corrections_20261103/c6_midnight_verification_20261104/CHECKLIST.md
  git add nms_corrections_20261103/c6_midnight_verification_20261104/
  git commit -m "c6 midnight-rollover verification 2026-11-04: VERIFIED"
  git push origin report/nms-corrections-20261103
  ```
- [ ] Mark the operator task tracker (if used) as complete

## If verification FAILS

**STOP.** Do not deploy Phase C. Do not change broker orders.

1. Capture full state:
   ```bash
   DEST=/mnt/volume_lon1_1778405456698/autobot-nms-deploy-20261103/c6-rollover-failure-$(date -u +%Y%m%dT%H%M%SZ)
   mkdir -p "$DEST"
   cp /opt/tradingbot/cache/session_trend_state.json "$DEST/"
   cp /opt/tradingbot/cache/session_trend_*.json "$DEST/"
   journalctl -u autobot.service --since "2026-11-03 23:50:00" --until "2026-11-04 00:30:00" --no-pager > "$DEST/journal_autobot.log"
   sha256sum /opt/tradingbot/session_trend.py /opt/tradingbot/nms_v3_classifier.py /opt/tradingbot/.env > "$DEST/hashes.txt"
   ```

2. Document what failed:
   - which symbol(s) failed outer==inner check
   - last_session_v3 state
   - journal errors
   - whether autobot restarted during the rollover window

3. Rollback Phase A (C6 only — do NOT roll back Phase B unless the failure is independent):
   ```bash
   # Replace with pre-C6 session_trend.py (worktree pre-c6 backup):
   cp /mnt/volume_lon1_1778405456698/autobot-nms-deploy-20261103/pre-c6-20261103T085930Z/session_trend.py.prod /opt/tradingbot/session_trend.py
   # Remove the C6 env flag:
   grep -v 'NMS_V3_C6_DAYROLL_RESET' /opt/tradingbot/.env > /tmp/.env.new && mv /tmp/.env.new /opt/tradingbot/.env
   # Verify SHAs
   sha256sum /opt/tradingbot/session_trend.py  # expect c943a65c…
   # Restart (operator sudo required)
   sudo systemctl restart autobot.service
   ```

4. Preserve Phase B (C1+C2+classifier) rollback separately — do not conflate.

## References

- Deployment-readiness review: `/opt/tradingbot/reports-public/nms_corrections_20261103/deployment_readiness_review.md`
- Phase A install: `/mnt/volume_lon1_1778405456698/autobot-nms-deploy-20261103/pre-c6-20261103T085930Z/`
- Phase B install: `/mnt/volume_lon1_1778405456698/autobot-nms-deploy-20261103/pre-c1c2-20261103T093740Z/`
- Isolated e2e rollover test script: `/mnt/volume_lon1_1778405456698/autobot-nms-deploy-20261103/day_roll_e2e_test.py`
- C6 code: `/opt/tradingbot/session_trend.py:1423-1448` (block starts at the `# C6 (NMS_V3_C6_DAYROLL_RESET)` comment)

## Durability guarantees

1. **File-system durable:** this checklist lives under `/opt/tradingbot/reports-public/c6_midnight_verification_20261104/` on the live filesystem. Survives Claude sessions, operator SSH logout, service restarts.
2. **Git-durable:** committed and pushed to `autobot_reports` repo on branch `report/nms-corrections-20261103`. Visible at https://github.com/JohnCarrington/autobot_reports/tree/report/nms-corrections-20261103
3. **Operator-visible path:** `/opt/tradingbot/reports-public/` is where other project reports live; this directory is intended to be discoverable.

---

**Do not mark C6 fully verified until the live rollover has been observed.**
