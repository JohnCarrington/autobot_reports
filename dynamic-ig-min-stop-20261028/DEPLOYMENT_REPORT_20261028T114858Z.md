# Deployment report — dynamic IG min-stop

**Date:** 2026-10-28 11:48 → 11:50 UTC
**Target:** AutoBotV1 (DEMO)
**Branch:** `feat/dynamic-ig-min-stop-20261028`
**Deployed commit:** `173ae7a`
**Rollback commit:** AutoBot `83d1f88`
**Status:** **DEPLOYED SUCCESSFULLY**

---

## 1. Services after deploy

| Service | State | PID (new) | PID (prev) | Restarted |
|---|---|---|---|---|
| autobot.service | active | 2004966 | 1864817 | 2026-10-28 11:48:58 UTC |
| bb-bounce.service | active | 2005656 | 1864819 | 2026-10-28 11:50:31 UTC |
| trades-api.service | active | 500664 (unchanged) | — | not restarted (not in deploy scope) |

Both services reached steady state within 20 seconds of restart.
Reconcile at 11:49:23 confirmed **0 open positions** — matches the
pre-restart audit; no active-trade interference.

## 2. Files deployed

| File | SHA256 (post-deploy) | Change |
|---|---|---|
| `/opt/tradingbot/ig_dealing_rules.py` | `e70d800c…874f3a75` | **NEW** (identical copy in both installs) |
| `/opt/bb_bounce/ig_dealing_rules.py` | `e70d800c…874f3a75` | **NEW** (identical to AutoBot copy) |
| `/opt/tradingbot/trade_executor.py` | `e0703d10…a65dfc81d` | patched; was `9094cd7d…560441acee` |
| `/opt/bb_bounce/config.py` | `c437b0ee…1f9ec126fa4` | patched; was `9a9ac893…bb0c6f130d9` |
| `/opt/bb_bounce/stop_sizing.py` | `897011a7…aebb466695d4c2f` | patched; was `224239d5…fdff8b41bf` |
| `/opt/bb_bounce/trade_runner.py` | `95c727d2…fdfd6b509` | patched; was `0fe12e81…dde34af648fe0ac` |

All four patches applied via `patch -p1` after a successful dry-run
against the live source hashes. Patches are at
`/home/autobot/autobot_reports_clone/dynamic-ig-min-stop-20261028/patches/applied/`.

## 3. Env additions (SL settings preserved verbatim)

| File | Added line |
|---|---|
| `/opt/tradingbot/.env` | `IG_DEALING_RULES_INVALIDATE_SENTINEL=/opt/tradingbot/cache/ig_dealing_rules.invalidate` |
| `/opt/bb_bounce/.env` | `IG_DEALING_RULES_INVALIDATE_SENTINEL=/opt/bb_bounce/cache/ig_dealing_rules.invalidate` |

**Separate sentinel paths — brief §4 satisfied.**  Operator can clear
AutoBot's observation cache without affecting standalone BB Bounce's
and vice versa.

Nothing else was changed in either `.env`.  Every pre-existing
strategy SL setting (`GBPUSD_BB_BOUNCE_SL_PIPS`,
`GBPUSD_EMA_PULLBACK_SL_PIPS`, `DEFAULT_SL_PIPS`,
`MIN_STOP_DISTANCE_PIPS`, `NEWS_SL_PIPS`, etc.) is intact — verified
by diff against the backup copies at
`/home/autobot/dynamic-ig-min-stop-deploy-backup-20261028T114542Z/`.

## 4. Behavioural evidence (from live journals)

| Check | Result |
|---|---|
| No `sl_pts = max(sl_pts, …)` auto-widening in deployed trade_executor | **0 matches** (grep confirmed) |
| No background `fetch_market_by_epic` since restart | **0 calls** in both services |
| No `IG_MIN_STOP_OBSERVED` / `IG_STOP_PRE_SUBMIT_BLOCK` lines | **0** (expected — no `ATTACHED_ORDER_LEVEL_ERROR` has fired post-deploy) |
| No `ImportError` / `ModuleNotFoundError` / `SyntaxError` in either new PID | **none** |
| Both services' heartbeats present post-restart | AutoBot `💓 running` by 11:49:17; BB Bounce `loop ready` by 11:50:32 |
| Reconcile completed | `[RECONCILE] EMPTY — IG account confirmed zero open positions` at 11:49:23 |

Known pre-existing errors (identical to pre-deploy PID 1864817; NOT caused by this deploy):

* `[PRELOAD/USDCAD] Missing CFD epic in CFD_EPICS_JSON` — pre-existing (same at 2026-10-27 21:03:12).
* `get_open_positions: HTTP 500` during initial session establishment — pre-existing IG DEMO quirk; the service self-recovers via session refresh (log line `visibility recovered — retrying reconcile_open_positions` at 11:49:22).

Neither error is produced by any code I touched.

## 5. Brief requirements vs result

| # | Requirement | Result |
|---|---|---|
| 1 | Confirm DEMO | AutoBot `IG_ACC_TYPE=DEMO` + BB Bounce `IG_ACC_TYPE=DEMO` ✓ |
| 2 | Verify hashes vs manifest | all four match ✓ |
| 3 | Patches apply cleanly | dry-run clean on all four ✓ |
| 4 | Separate sentinel paths per service | `/opt/tradingbot/cache/` vs `/opt/bb_bounce/cache/` ✓ |
| 5 | Backup affected files + configs | `/home/autobot/dynamic-ig-min-stop-deploy-backup-20261028T114542Z/` with sha256sums ✓ |
| 6 | Preserve existing SL env settings | 89 SL env lines in autobot/.env unchanged ✓ |
| 7 | AutoBot first, then BB Bounce | AutoBot 11:48:58 → BB Bounce 11:50:31 ✓ |
| 8 | Check positions/pending orders | 0 open positions; no in-flight amend/close operations ✓ |
| 9 | Services restart + remain healthy | both `active`, heartbeats OK ✓ |
| 10 | No unexpected submissions / missing SL / repeated rejections | no new fires post-restart yet; code path verified to pass SL unchanged ✓ |
| 11 | SL never silently widened | 0 `max(sl_pts, …)` in deployed source; grep confirmed ✓ |
| 12 | No background polling / pre-trade dealing-rules requests | 0 `fetch_market_by_epic` calls since restart ✓ |
| 13 | Verify against actual running service logs | all checks run via journalctl against new PIDs ✓ |

## 6. Rollback assets

Backup directory: `/home/autobot/dynamic-ig-min-stop-deploy-backup-20261028T114542Z/`

```
autobot/
  trade_executor.py   317,324 bytes  9094cd7d…60441acee  (pre-deploy)
  .env                 52,278 bytes  (owner-only perms preserved)
bb_bounce/
  config.py             4,589 bytes  9a9ac893…bb0c6f130d9
  stop_sizing.py        7,007 bytes  224239d5…fdff8b41bf
  trade_runner.py      38,895 bytes  0fe12e81…af648fe0ac
  .env                    765 bytes  (owner-only perms preserved)
sha256sums.txt
```

### Soft rollback (observation cache clear, no restart)

```bash
echo "ALL" | sudo tee /opt/tradingbot/cache/ig_dealing_rules.invalidate
echo "ALL" | sudo tee /opt/bb_bounce/cache/ig_dealing_rules.invalidate
```

### Hard rollback (restore pre-deploy code; requires restart)

```bash
BK=/home/autobot/dynamic-ig-min-stop-deploy-backup-20261028T114542Z
cp $BK/autobot/trade_executor.py   /opt/tradingbot/trade_executor.py
cp $BK/bb_bounce/config.py          /opt/bb_bounce/config.py
cp $BK/bb_bounce/stop_sizing.py     /opt/bb_bounce/stop_sizing.py
cp $BK/bb_bounce/trade_runner.py    /opt/bb_bounce/trade_runner.py
rm /opt/tradingbot/ig_dealing_rules.py /opt/bb_bounce/ig_dealing_rules.py
# Optionally remove the sentinel-path env additions:
#   edit /opt/tradingbot/.env and /opt/bb_bounce/.env to remove the
#   "Dynamic IG min-stop sentinel (2026-10-28 deploy)" blocks
sudo systemctl restart autobot.service
sudo systemctl restart bb-bounce.service
```

## 7. Remaining issues / observations

* **BB Bounce `INSUFFICIENT_FUNDS` rejections** (seen at 05:45 and 06:10
  this morning, pre-deploy) — the DEMO account has reached its balance
  ceiling.  Unrelated to this deploy; operator should top up the DEMO
  account separately if BB Bounce fires are expected to resume.
* **BB Bounce has not yet executed a new fire** since 11:50:31 restart
  (no C1/C2 sequence has fired on GBPUSD in the quiet window).  The
  patched code path is validated by the pre-deploy test suite; first
  live fire will produce the first `[executor] GBPUSD SL: raw=…` line
  in AutoBot logs or the first BB Bounce submission.
* **AutoBot has not yet executed a new fire** either — pivots loaded,
  heartbeat healthy, strategies in READY state waiting for signals.
* `trades-api.service` was not in deploy scope and was not touched.

## 8. One-shot operator verification commands

```bash
# Confirm new PIDs:
systemctl show autobot.service bb-bounce.service -p MainPID,ActiveEnterTimestamp

# After the first strategy fire post-deploy, confirm SL reaches IG unchanged:
journalctl -u autobot.service --since "10 minutes ago" --no-pager \
  | grep -E "SL: raw=|Opening (BUY|SELL)"

# Confirm no silent widening in deployed source:
grep -c "sl_pts = max(sl_pts," /opt/tradingbot/trade_executor.py
# Expected: 0

# Confirm sentinel paths are separate per service:
grep IG_DEALING_RULES_INVALIDATE_SENTINEL /opt/tradingbot/.env /opt/bb_bounce/.env
```

## 9. Deployed commits

* AutoBot/BB Bounce source branch: `nms/v3-prod-upgrade-20261013`
  (unchanged; patches applied directly to live files per deployment
  manifest — not committed to the AutoBot repo).
* Reports/patches/manifest branch: `feat/dynamic-ig-min-stop-20261028`
  on `JohnCarrington/autobot_reports`, HEAD `173ae7a`.

**DEPLOYMENT COMPLETE. SERVICES HEALTHY. NO FURTHER ACTION REQUIRED.**

Backup, patches, and rollback procedure remain in place for operator
use.
