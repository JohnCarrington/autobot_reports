# Enabling a 4-pip stop for a specific strategy

**Audience:** operator.  **Pre-condition:** Patch 0001b + Patch 0002b
applied; `module/ig_dealing_rules.py` deployed at
`/opt/tradingbot/ig_dealing_rules.py` and `/opt/bb_bounce/ig_dealing_rules.py`;
tests passing in deployment worktree.

Each section below shows the minimal `.env` changes required.  No code
changes are needed by the operator.

---

## 1. Standalone BB Bounce — enable 4-pip stop

### 1.1 Changes required

```bash
# /opt/bb_bounce/.env — append (or edit):
SL_PIPS=4
# BB_IG_MIN_STOP_PIPS=4.0 is already the default; no change needed.
# BB_STOP_MODE=FIXED_12 (default) OR BB_STOP_MODE=STRUCTURAL_3:
#   FIXED_12   → literally use the SL_PIPS value above (= 4 pips)
#   STRUCTURAL_3 → use structural stop (ignores SL_PIPS); 4 pips does
#                  nothing here.
```

### 1.2 Restart

```bash
sudo systemctl restart bb-bounce.service
```

### 1.3 Observability

Watch for the first fire:

```bash
journalctl -u bb-bounce.service -n 100 --no-pager | grep -E \
  "IG_STOP_VALIDATION_PASS|IG_STOP_VALIDATION_BLOCK|STOP_TOO_TIGHT"
```

Expected lines on a successful 4-pip fire:

```
[IG_STOP_VALIDATION_PASS] GBPUSD requested=4.00p min=4.00p source=live
```

### 1.4 Rollback

```bash
# /opt/bb_bounce/.env — revert
SL_PIPS=12
```

Restart.

---

## 2. AutoBot BB Bounce — enable 4-pip stop

### 2.1 Changes required

```bash
# /opt/tradingbot/.env — append or edit the following lines:
AUTOBOT_IG_MIN_STOP_STRICT=1              # strict reject (post Patch 0001b default)
GBPUSD_BB_BOUNCE_SL_PIPS=4                # strategy's requested SL
```

That is **all** you need post Patch 0001b, because:

* Step 2 (per-pair IG min) now consults IG's live dealing-rules → 4.0p.
* Step 3 (global SL floor) is REMOVED.
* Step 4 (`pair_config.MIN_SL_PIPS[GBPUSD]=12`) is SKIPPED in strict mode.

### 2.2 Restart (operator decides when)

```bash
sudo systemctl restart autobot.service   # or whatever service unit AutoBot uses
```

### 2.3 Observability

```bash
journalctl -u autobot.service -n 100 --no-pager | grep -E \
  "IG_STOP_VALIDATION_PASS|IG_STOP_VALIDATION_BLOCK|IG_MIN_STOP_CHANGE|IG_MIN_STOP_FETCH"
```

Expected on a 4-pip fire:
```
[IG_STOP_VALIDATION_PASS] GBPUSD requested=4.00p min=4.00p source=live rule_ts=1763...
[executor] GBPUSD SL=4.00p accepted below user default MIN_SL_PIPS=12.00p (strict mode)
```

### 2.4 Rollback

```bash
# /opt/tradingbot/.env — revert:
AUTOBOT_IG_MIN_STOP_STRICT=0
```

Restart.  Strategy's 4-pip request is now re-widened by Step 4 to 12p
(legacy behaviour), but all logging remains intact for diagnostics.

To fully revert to pre-patch behaviour, remove `GBPUSD_BB_BOUNCE_SL_PIPS=4`
or set it back to 20.

---

## 3. AutoBot EMA Pullback — enable 4-pip stop

EMA Pullback computes its stop from `(entry − EMA_21) + 3p buffer`
and floors at `_PAIR_MIN_SL_PIPS[GBPUSD]=12` INSIDE the strategy
(ema_pullback.py:632).  So you also need to lower the strategy's own
per-pair floor via env:

### 3.1 Changes required

```bash
# /opt/tradingbot/.env — append or edit:
AUTOBOT_IG_MIN_STOP_STRICT=1
GBPUSD_MIN_SL_PIPS=4                 # overrides pair_config.MIN_SL_PIPS[GBPUSD]
GBPUSD_EMA_PULLBACK_SL_PIPS=4        # strategy's env-level ceiling / default
```

### 3.2 Behavioural note

The strategy's output will still be the structural distance from EMA_21
if that is ≥ 4p.  Only when the structural distance is below 4p (very
close to EMA_21) does the strategy's own `max(4, structural)` become
the floor.

### 3.3 Rollback

```bash
AUTOBOT_IG_MIN_STOP_STRICT=0
```

Restart.

---

## 4. ALL AutoBot strategies — enable 4-pip for every GBPUSD strategy

```bash
# /opt/tradingbot/.env — append or edit:
AUTOBOT_IG_MIN_STOP_STRICT=1
GBPUSD_MIN_SL_PIPS=4
GBPUSD_BB_BOUNCE_SL_PIPS=4
GBPUSD_EMA_PULLBACK_SL_PIPS=4
QM_V2_LIVE_SL_PIPS=4
ONE_STRATEGY_SL_PIPS=4
TREND_V3_SL_FALLBACK_PIPS=4
NEWS_SL_PIPS=4
NEWS_TICK_SL_PIPS=4
NEWS_FADE_MAX_SL_PIPS=4   # ceiling, keeps NEWS_FADE's SL cap at 4
```

Note: `gbpusd_trend_v3.UM_SL_PIPS=12.0` is **hardcoded** (no env
override).  If the UM mode of Trend V3 is active and a 4-pip stop is
required there, a code change is needed — propose Patch 0004 to add
`TREND_V3_UM_SL_PIPS` env override.  This is deferred until the
operator confirms the need.

---

## 5. Verification checklist (post-deploy)

- [ ] `journalctl` shows at least one `IG_STOP_VALIDATION_PASS` or
      `IG_STOP_VALIDATION_BLOCK` line within the first minute.
- [ ] First GBPUSD trade after deploy shows the requested SL at the
      live broker (visible in IG platform).
- [ ] No `IG_MIN_STOP_FETCH_FAILED` lines (indicates live fetch works).
- [ ] `logs/signal_log.jsonl` continues to receive rows (no silent
      block storm).
- [ ] After 24 h, zero `IG_STOP_VALIDATION_BLOCK` lines that are not
      traced back to a deliberate sub-min request.
- [ ] After 24 h, 0 broker `ATTACHED_ORDER_LEVEL_ERROR` rejections
      (the pre-submit validation should have caught them).

If any of these fail, set `AUTOBOT_IG_MIN_STOP_STRICT=0` and restart.
Behaviour returns to pre-patch baseline.
