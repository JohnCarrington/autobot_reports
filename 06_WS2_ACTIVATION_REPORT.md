# WS2 Production Activation Report

**Date:** 2026-10-29
**Activation window:** 19:26:48 UTC (`.env` edit) → 19:28:04 UTC (restart) → 19:30:02 UTC (final verification)
**Repository:** `/opt/tradingbot` branch `nms/v3-prod-upgrade-20261013`
**Prod HEAD:** `06721a0` (unchanged from pre-activation — only `.env` was modified)
**Service:** `autobot.service` PID **2355338**, started **2026-10-29 19:28:04 UTC**

## 1. Pre-activation broker safety check

| # | Check | Evidence | Result |
|---|---|---|---|
| 1 | No open V3 BB positions | Fresh read-only `GET /positions` at 19:26:09 → HTTP 200; REST-SWEEP 30 clean cycles since 19:21:43 reconcile EMPTY | **PASS** — zero V3 BB positions |
| 2 | No new V3 BB opened since 19:21:43 UTC reconciliation | Journal grep post-19:21:43 → **0** `📤 Submit` / `OPEN success` / `dealStatus ACCEPTED` / `TRIGGER` events across 122 log lines | **PASS** |
| 3 | Prod code at `06721a0` includes WS2 single-flag implementation | SHA256 live tree matches candidate: engine.py `6accc9d1`, bb_reversal_permission.py `7ba0d3ea`. Live source check: `_V3_STATE_ADMITTED = frozenset({'RANGE'})`, `_bb_range_block` method present, `_bb_reversal_permission` method present | **PASS** |

## 2. Configuration change

**File:** `/opt/tradingbot/.env`
**Backup:** `/home/autobot/four-corrections-deploy-20261029/pre-state/.env.pre-ws2-20261029T192648Z`

**Added at line 776 (after line 764 `BOUNCE_SCALE_OUT_ENABLED=1`):**

```
# WS2 (2026-10-29) — V3 BB RANGE-only admission + opposite-band exit.
# Single-flag design (operator ruling): this flag gates BOTH
#   * NEW: WS2 admission check in bounce_engine/v3/engine.py:
#     _bb_range_block — only v3_state=="RANGE" admits a V3 BB
#     trigger; NORMAL, EMERGING_* and STRONG_* block. Fail-closed
#     on missing/stale/parse-failed cache/session_trend_<SYM>.json.
#   * PRE-EXISTING: EXIT_BAND_TOUCH opposite-band exit at :689/:770 —
#     V3 BB BUY targets the upper BB, V3 BB SELL targets the lower BB.
# Enabled 2026-10-29 after broker-side safety check confirmed zero
# open V3 BB positions. Rollback: set to 0 and restart.
V3_BB_RANGE_ONLY_ENABLED=1
```

**No code commits.** The code was already deployed at `84f0882` (Stage 3) / `06721a0` (post-WS1). This activation step changes `.env` only.

## 3. Restart

| Field | Value |
|---|---|
| Previous PID | 2353936 (started 19:21:00 UTC) |
| New PID | **2355338** |
| Restart timestamp | **2026-10-29 19:28:04 UTC** |
| ActiveState | **active** |
| Initial reconcile | HTTP 500 (transient IG rate-limit) → `RECONCILE_RETRY` recovered at 19:28:39 UTC → **EMPTY** (0 open positions) |
| Service recovery | Automatic within 35s; no manual intervention required |

## 4. Post-restart effective flag state

In-process `/proc/2355338/environ` (observed; sorted; unset flags default to 0):

```
BOUNCE_SCALE_OUT_ENABLED=1
SCALE_OUT_TRIGGER_PIPS=8
V3_BB_RANGE_ONLY_ENABLED=1
```

- `BOUNCE_SCALE_OUT_ENABLED=1` — **WS3 preserved** (scale-out active for V3_EMA/BOUNCE_TR/A/C/SQ)
- `V3_BB_RANGE_ONLY_ENABLED=1` — **WS2 activated** (admission + opposite-band exit both live)
- `BB_REVERSAL_PERMISSION_ENABLED` — **unset → defaults 0** → **WS1 shadow preserved**

## 5. Broker inventory (fresh read-only call)

Direct `GET /positions` at **2026-10-29 19:30:02 UTC** → HTTP 200:

```
IG DEMO positions: 0
```

No positions open. The autobot's internal reconcile matches (EMPTY at 19:28:39 UTC, 1min 23s before this read).

## 6. Runtime verification — all operator checklist items

| # | Required behaviour | Verification | Result |
|---|---|---|---|
| 7a | Only explicit NMS `RANGE` admits V3 BB | Simulated gate against 6 regimes using live source + flag `V3_BB_RANGE_ONLY_ENABLED=1` | ✅ `RANGE → ADMIT`; others → BLOCK |
| 7b | `NORMAL` blocked | Simulated | ✅ `NORMAL → BLOCK (v3_bb_not_in_range)` |
| 7b | `EMERGING_UP`/`EMERGING_DOWN` blocked | Simulated | ✅ both → BLOCK |
| 7b | `STRONG_UP`/`STRONG_DOWN` blocked | Simulated | ✅ both → BLOCK |
| 7c | V3 BB BUY targets opposite upper Bollinger Band | Code audit `bounce_engine/v3/engine.py:909-915` (bar-close) + `:966-973` (tick) — LONG side, `bar.high >= upper` or `ask >= upper` → `EXIT_BAND_TOUCH` on `upper` band | ✅ confirmed |
| 7d | V3 BB SELL targets opposite lower Bollinger Band | `:919-928` (bar-close) + `:975-982` (tick) — SHORT side, `bar.low <= lower` or `bid <= lower` → `EXIT_BAND_TOUCH` on `lower` band | ✅ confirmed |
| 7e | V3 BB excluded from scale-out | Live-source parse of `trade_manager.py` WS3 scope: `{'BOUNCE_A_L/S', 'BOUNCE_C_L/S', 'BOUNCE_SQ_L/S', 'BOUNCE_TR_L/S', 'V3_EMA_L/S'}` — **V3_BB_L/S not in whitelist** | ✅ confirmed |
| 7f | WS3 scale-out enabled for V3_EMA / BOUNCE_TR / BOUNCE_A/C/SQ | In-process `BOUNCE_SCALE_OUT_ENABLED=1`; scope above | ✅ confirmed |
| 7g | WS1 shadow still calculating + logging without blocking | `bb_reversal_permission.ENABLED = False`; module method `_bb_reversal_permission` present on V3Engine; wiring in `_fire_triggers` calls it before TRIGGER emission; shadow contract (pre-deploy): permitted forced True + metrics populated + decision_reason + shadow_would_block flagged | ✅ confirmed |
| 7h | Broker reconciliation normal | 19:28:39 UTC RECONCILE EMPTY after visibility recovery; REST-SWEEP daemon running (next sync cycle ≤ 90s) | ✅ confirmed |
| 7h | Service health normal | Active; heartbeats emitting (`💓 AutoBot running — tick age: 0s`); all 4 pairs streaming ticks; no error events after initial reconcile recovery | ✅ confirmed |
| — | No duplicate close attempts | Journal grep post-19:28:04 | ✅ zero duplicates |
| — | No rejected broker SUBMIT requests | Journal grep post-19:28:04 | ✅ zero rejections |
| — | Standalone BB Bounce unchanged | `bb-bounce.service` PID 2005656, started 2026-10-28 11:50:31 UTC (untouched) | ✅ unaltered |
| — | WS1 enforcement NOT activated | `BB_REVERSAL_PERMISSION_ENABLED` unset in `.env` and in process environment | ✅ shadow only |

## 7. First-trigger runtime observation

No V3 BB TRIGGER has fired since restart (no armed BB setup produced a trigger in the first ~2 minutes). Runtime observation of:
- WS2 `TRIGGER_BLOCKED` with `reason="ws2:v3_bb_not_in_range"` (if non-RANGE regime)
- WS1 shadow metrics on TRIGGER event payload (`bb_reversal_permission={bb_width_now, bb_width_peak, is_flattened, bands_expanding, ribbon_state, is_braided, decision_reason, shadow_would_block}`)
- WS2 `EXIT_BAND_TOUCH` on opposite-band price touch for an open V3 BB position

...will be captured when the first V3 BB signal fires. This is a passive wait, not a failure.

The gate is **loaded and active** per import tests + process environment + source audits. First real event will log to `/var/log/journal` for autobot.service and will carry the WS2/WS1 reason/metrics payload directly.

## 8. Rollback

- **Instant rollback of WS2 activation** (keep code, disable):
  ```
  sed -i 's/^V3_BB_RANGE_ONLY_ENABLED=1$/V3_BB_RANGE_ONLY_ENABLED=0/' /opt/tradingbot/.env
  sudo systemctl restart autobot.service
  ```
  After next reconcile the gate becomes inert and the opposite-band exit disables. Byte-identical to pre-WS2 behaviour. No code revert needed.

- **Code revert** (if required): `git revert 84f0882` (reverts WS2 code commit on `nms/v3-prod-upgrade-20261013`).

- **Backup**: `/home/autobot/four-corrections-deploy-20261029/pre-state/.env.pre-ws2-20261029T192648Z` can be restored verbatim.

## 9. Full deployment-complete manifest (post-WS2 activation)

| WS | Prod commit | Flag | Behavioural state |
|----|---|---|---|
| WS4 (AutoBot min-stop) | `6975091` | — | Formalised (no behavioural change from pre-deployment) |
| WS5 (NMS floor-break) | `edd1d37` | — | Formalised (no behavioural change) |
| WS3 (scale-out) | `e1a46f2` | `BOUNCE_SCALE_OUT_ENABLED=1` | **ACTIVE** — V3_EMA / BOUNCE_TR / A/C/SQ scale out at +8p; V3_BB excluded |
| WS2 (V3 BB range-only + opposite-band) | `84f0882` | `V3_BB_RANGE_ONLY_ENABLED=1` | **ACTIVE** — V3 BB admits only in RANGE regime; opposite-band EXIT_BAND_TOUCH active |
| WS1 (reversal permission) | `06721a0` | `BB_REVERSAL_PERMISSION_ENABLED` unset (=0) | **SHADOW** — metrics logged on every V3 BB TRIGGER; admission unaffected |
