# Enabling a 4-pip stop for a specific strategy (event-driven design)

**Design:** 2026-10-28 operator ruling — event-driven, no pre-trade API.
**Pre-condition:** Patches applied + module deployed per
`DEPLOYMENT_MANIFEST.md`.

## How this works (short version)

* The operator sets the strategy's requested stop in `.env`.  No other
  change is needed.
* AutoBot submits every trade with that stop attached to the initial IG
  order.
* If IG accepts, you trade with the exact stop you asked for.
* If IG rejects for an insufficient stop distance, the module records
  what IG currently requires and the NEXT submission with a too-tight
  stop is blocked locally.  The rejected trade is NOT auto-widened and
  NOT retried.
* After the TTL (default 15 min) or an operator `invalidate`, the
  local block is cleared and the strategy is free to try again.

---

## 1. Standalone BB Bounce — enable 4-pip stop

### 1.1 Pre-condition

Patch 0004 to `/opt/bb_bounce/config.py` applied (TP_PIPS and SL_PIPS
now read from env).  Without this patch, `SL_PIPS=12` is hardcoded.

### 1.2 Changes required

```bash
# /opt/bb_bounce/.env — append (or edit):
BB_SL_PIPS=4
# No other env needed. The strategy will submit with sl_distance=4.
```

### 1.3 Restart

```bash
sudo systemctl restart bb-bounce.service
```

### 1.4 Observability

```bash
# Successful 4-pip trades carry sl_distance=4 to IG; no module log needed.
journalctl -u bb-bounce.service -n 100 --no-pager | grep -E "stop_distance|STOP_TOO_TIGHT"

# If IG currently requires more than 4p for this epic, you will see:
# 1. ATTACHED_ORDER_LEVEL_ERROR from IG (first rejected submission)
# 2. [IG_MIN_STOP_OBSERVED] value=Xp (one log line) — the module records
#    what IG requires.
# 3. Subsequent 4-pip submissions → STOP_TOO_TIGHT from stop_sizing.py
#    (local block, no IG call).
```

### 1.5 Rollback

```bash
# /opt/bb_bounce/.env — revert:
BB_SL_PIPS=12
```

Restart.

---

## 2. AutoBot BB Bounce — enable 4-pip stop

### 2.1 Changes required

```bash
# /opt/tradingbot/.env — append or edit:
GBPUSD_BB_BOUNCE_SL_PIPS=4
```

### 2.2 Behavioural note

AutoBot still has three legacy widening floors in `execute_trade`:
Step 2 (`_IG_MIN_STOP_PTS`), Step 3 (global `MIN_STOP_DISTANCE_PIPS`),
and Step 4 (`pair_config.MIN_SL_PIPS`).  The event-driven redesign
leaves these in place as **safety nets for unknown pairs or module
failure**.  To let a 4-pip request actually reach IG, you must also
lower them:

```bash
# /opt/tradingbot/.env — append or edit:
GBPUSD_IG_MIN_STOP_PTS=4        # Step 2 — per-pair IG proxy
MIN_STOP_DISTANCE_PIPS=4        # Step 3 — global fallback
GBPUSD_MIN_SL_PIPS=4            # Step 4 — pair_config user default
GBPUSD_BB_BOUNCE_SL_PIPS=4      # strategy's requested SL
```

Alternative — leave the floors at their defaults and raise the
strategy's requested stop:
```bash
GBPUSD_BB_BOUNCE_SL_PIPS=12     # safe within all floors
```

### 2.3 Restart

```bash
sudo systemctl restart autobot.service
```

### 2.4 Observability

```bash
# After an ATTACHED_ORDER_LEVEL_ERROR rejection (first attempt), expect:
journalctl -u autobot.service -n 100 --no-pager | grep -E \
  "ATTACHED_ORDER_LEVEL_ERROR|IG_MIN_STOP_OBSERVED|IG_STOP_PRE_SUBMIT_BLOCK"

# Successful submissions (requested stop accepted by IG) carry sl_distance
# and no block from the dealing_rules module.
```

### 2.5 Rollback

```bash
# /opt/tradingbot/.env — revert the overrides:
# GBPUSD_IG_MIN_STOP_PTS=12
# MIN_STOP_DISTANCE_PIPS=12
# GBPUSD_MIN_SL_PIPS=12
# GBPUSD_BB_BOUNCE_SL_PIPS=20  (original)
```

Restart.

---

## 3. Clearing a stale local block (operator sentinel)

If a legitimate submission is being blocked locally because of a stale
observation (e.g. IG tightened momentarily and has since relaxed), the
operator clears it by writing a sentinel file.  The running service
consumes the file on its next lookup — no service restart required.

```bash
# Clear ONE epic
echo "CS.D.GBPUSD.TODAY.IP" | sudo tee /opt/tradingbot/cache/ig_dealing_rules.invalidate

# Clear ALL observations in the process
echo "ALL" | sudo tee /opt/tradingbot/cache/ig_dealing_rules.invalidate
```

The next trade submission (within a few seconds) consumes the file,
clears the observation, and logs
`IG_MIN_STOP_SENTINEL_INVALIDATE cleared=<epic>`.

**Important:** running `python3 -c "import ig_dealing_rules; ig_dealing_rules.invalidate(...)"`
in a FRESH shell creates a new interpreter whose module state is empty.
It does NOT clear the running autobot/bb-bounce service's cache.
Use the sentinel-file protocol above instead.

The observation also expires automatically after
`IG_DEALING_RULES_TTL_SECS` seconds (default 900 = 15 min).  Set
`IG_DEALING_RULES_TTL_SECS=60` in `.env` for a faster auto-clear if the
operator wants more aggressive retry.

The sentinel path is env-overridable via
`IG_DEALING_RULES_INVALIDATE_SENTINEL` for operators who want to park
the sentinel outside `/opt/tradingbot/cache/`.

---

## 4. Verification checklist (post-deploy)

- [ ] `journalctl` shows strategy-submitted stops reaching IG with the
      requested distance.
- [ ] First trade after deploy carries the SL on the initial order
      (no post-submission amend to set it).
- [ ] No `IG_MIN_STOP_OBSERVED` logs during normal operation (only
      after a confirmed ATTACHED_ORDER_LEVEL_ERROR).
- [ ] After an operator triggers a sub-min test, exactly one
      `fetch_market_by_epic` call fires per rejection; subsequent
      sub-min submissions block locally.
- [ ] 24 h after deploy: zero regressions in strategy fire counts,
      zero regressions in NMS admission counts, zero changes to
      `pair_config.MIN_SL_PIPS` behaviour.

If any check fails, follow the soft or hard rollback in
`DEPLOYMENT_MANIFEST.md` §4.
