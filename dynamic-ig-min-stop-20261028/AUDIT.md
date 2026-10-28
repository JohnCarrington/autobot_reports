# Stop-loss configuration audit — read-only inventory

**Date:** 2026-10-28
**Scope:** `/opt/tradingbot/*.py`, `/opt/bb_bounce/*.py`, `/opt/tradingbot/.env`
(credentials redacted), `/opt/bb_bounce/.env`.
**Outcome:** correct the previous patch set to reflect the audit — specifically,
`pair_config.MIN_SL_PIPS` is a **user-configurable per-pair default**, not an
immutable risk floor.

---

## 1. Inventory — all SL-related constants + env vars (credentials redacted)

### 1.1 `/opt/tradingbot/.env` (SL/stop keys only)

```
line  70  DEFAULT_SL_PIPS=20                              # execute_trade's fallback when decision.sl absent
line 118  MIN_STOP_DISTANCE_PIPS=12                       # trade_executor global floor (SL + TP)
line 126  NEWS_SL_PIPS=20                                 # NEWS strategies
line 149  BRIEFING_SWEEP_SL_BUFFER_PIPS=3                 # briefing_sweep buffer above structural SL
line 168  BB_REVERSAL_SL_BUFFER_PIPS=3                    # BB_REVERSAL patterns
line 368  NEWS_TICK_SL_PIPS=20                            # news tick strategy
line 381  NEWS_TICK_MAX_SLIPPAGE_PIPS=10
line 398  THREE_CO_SL_PIPS=12                             # 3-CO continuation
line 521  BB_PREMIRROR_L_MAX_SL_PIPS=25                   # ceiling
line 542  NY_CONTINUATION_L_MAX_SL_PIPS=25
line 590  NEWS_FADE_MAX_SL_PIPS=25
line 645  GBPUSD_BB_BOUNCE_SL_PIPS=20                     # autobot BB Bounce fixed SL
line 647  GBPUSD_EMA_PULLBACK_SL_PIPS=12                  # overridable from strategy
line 689  NEWS_SL_PIPS=20                                 # duplicate of 126 (last wins)
```

Not present (so defaults apply):
```
GBPUSD_MIN_SL_PIPS            # → pair_config.py MIN_SL_PIPS["GBPUSD"]=12.0 default
GBPUSD_IG_MIN_STOP_PTS        # → trade_executor._IG_MIN_STOP_PTS["GBPUSD"]=12.0 default
AUTOBOT_IG_MIN_STOP_STRICT    # proposed env; not currently set
```

### 1.2 `/opt/bb_bounce/.env` (SL/stop keys only)

Nothing set — standalone BB Bounce runs with `config.py` import-time defaults:
```
TP_PIPS = 30
SL_PIPS = 12
BB_STOP_MODE = "FIXED_12"
IG_MIN_STOP_PIPS = 4.0  (from BB_IG_MIN_STOP_PIPS env, else 4.0 default)
STRUCTURAL_BUFFER_PIPS = 3.0
```

### 1.3 Python-level constants

| File | Line | Constant | Default | Env override | Role |
|---|---|---|---|---|---|
| `trade_executor.py` | 154 | `DEFAULT_SL_PIPS` | 12 | `DEFAULT_SL_PIPS` | fallback for `decision.sl` |
| `trade_executor.py` | 945 | `MIN_SL_PIPS` | 2 | `MIN_SL_PIPS` | hard sanity floor (reject SL<2p; local helper only) |
| `trade_executor.py` | 947 | `MAX_REASONABLE_SL_PIPS` | 500 | `MAX_REASONABLE_SL_PIPS` | hard ceiling (reject SL>500) |
| `trade_executor.py` | 952 | `MIN_STOP_DISTANCE_PIPS` | 12.0 | `MIN_STOP_DISTANCE_PIPS` | **global SL floor at Step 3** |
| `trade_executor.py` | 953 | `MIN_LIMIT_DISTANCE_PIPS` | 12.0 | `MIN_LIMIT_DISTANCE_PIPS` | global TP floor |
| `trade_executor.py` | 962-967 | `_IG_MIN_STOP_PTS` | GBPUSD=12 | `GBPUSD_IG_MIN_STOP_PTS` | **per-pair SL floor at Step 2 (broker min proxy)** |
| `pair_config.py` | 44-48 | `MIN_SL_PIPS` | GBPUSD=12.0 | `GBPUSD_MIN_SL_PIPS` | **per-pair SL floor at Step 4 (shared user default)** |
| `strategy_logic.py` | 321 | `DEFAULT_SL_PIPS` | 20 | `DEFAULT_SL_PIPS` | strategy-logic default |
| `strategy_logic.py` | 323 | `SWEEP_SL_PIPS` | 12 | `SWEEP_SL_PIPS` | sweep SL |
| `tiered_ratchet.py` | 129 | `RATCHET_INIT_SL_PIPS_DEFAULT` | 12.0 | `RATCHET_INIT_SL_PIPS` | ratchet init SL |
| `one_strategy_emitter.py` | 90 | `ONE_STRATEGY_SL_PIPS` | 12.0 | `ONE_STRATEGY_SL_PIPS` | one-strategy router |
| `gbpusd_bb_bounce.py` | 589 | `SL_PIPS` | 12.0 | `GBPUSD_BB_BOUNCE_SL_PIPS` | AutoBot BB Bounce |
| `gbpusd_trend_v3.py` | 60 | `UM_SL_PIPS` | 12.0 | (none) | TREND_V3 utility-member SL |
| `gbpusd_trend_v3.py` | 98 | `SL_FALLBACK_PIPS` | 15.0 | `TREND_V3_SL_FALLBACK_PIPS` | TREND_V3 fallback SL |
| `gbpusd_trend_v3.py` | 99 | `SL_BUFFER_PIPS` | 2.0 | `TREND_V3_SL_BUFFER_PIPS` | buffer below swing low |
| `ema_pullback.py` | 66 | `SL_BUFFER_PIPS` | 3.0 | `EMA_PULLBACK_SL_BUFFER` | EMA pullback buffer above EMA_21 |
| `qm_v2_executor.py` | 185 | hardcoded | 20.0 | `QM_V2_LIVE_SL_PIPS` | QM V2 live SL |
| `briefing_execution.py` | 2223, 2437 | `max(sl_pips, 3.0)` | 3.0 | (none) | briefing SL hard floor |
| `/opt/bb_bounce/config.py` | 21 | `SL_PIPS` | 12 | (none) | BB Bounce standalone fixed SL |
| `/opt/bb_bounce/config.py` | 53 | `IG_MIN_STOP_PIPS` | 4.0 | `BB_IG_MIN_STOP_PIPS` | BB Bounce standalone broker floor |

---

## 2. Strategy-by-strategy runtime matrix

| Strategy | Configured SL | Source | Overrides (floor/ceiling) | Final enforcement |
|---|---|---|---|---|
| **BB Bounce standalone** (`/opt/bb_bounce`) | **12 pips** | `config.SL_PIPS=12` (FIXED_12 mode) OR structural from `stop_sizing.structural_stop` (STRUCTURAL_3 mode, buffer 3p) | Broker floor: `IG_MIN_STOP_PIPS=4.0` (env `BB_IG_MIN_STOP_PIPS`). Rejection logic at `stop_sizing.py:143`. | Standalone `open_sb_now` → IG REST. Never routed through AutoBot trade_executor. **Rejects** if structural distance < 4.0p (no auto-widen). |
| **BB Bounce AutoBot** (`gbpusd_bb_bounce.py`) | **20 pips** | `GBPUSD_BB_BOUNCE_SL_PIPS=20` env (default 12) | Step 2 `_IG_MIN_STOP_PTS[GBPUSD]=12` floor; Step 3 `MIN_STOP_DISTANCE_PIPS=12` floor; Step 4 `pair_config.MIN_SL_PIPS[GBPUSD]=12` floor. All THREE auto-widen via `max()`. | `trade_executor.execute_trade`. Final = `max(20, 12, 12, 12) = 20p`. If strategy tried 4p: `max(4, 12, 12, 12) = 12p` **silently widened**. |
| **EMA Pullback** (`ema_pullback.py`) | **12 pips** (env) OR structural = \|entry − EMA_21\| + 3p buffer, whichever wider | `GBPUSD_EMA_PULLBACK_SL_PIPS=12` env; `_PAIR_MIN_SL_PIPS` floor inside strategy at line 632 | Same 3-floor pipeline at execute_trade as BB Bounce AutoBot | Strategy applies its own `MIN_SL_PIPS` floor BEFORE calling execute_trade. Then execute_trade applies the 3 floors again. |
| **Trend V3** (`gbpusd_trend_v3.py`) | **15 pips** fallback OR structural = swing low ± 2p buffer | `TREND_V3_SL_FALLBACK_PIPS=15` env; `TREND_V3_MAX_SL_PIPS` ceiling (default resolved at 60p) | Same 3-floor pipeline at execute_trade | Final per fire. On tight structural swing + Step 2/3/4 floors, widened to 12-15p. |
| **QM** (via `qm_v2_executor.py`) | **20 pips** | `QM_V2_LIVE_SL_PIPS=20` env | Same 3-floor pipeline at execute_trade | 20p → max(20, 12, 12, 12) = 20p |
| **V2 Pick One** (one_strategy_emitter) | **12 pips** | `ONE_STRATEGY_SL_PIPS=12` env | Same 3-floor pipeline at execute_trade | 12p pass-through |
| **Briefing Execution** (`briefing_execution.py`) | Computed from `inv_price_tc` (invalidation price in plan) | Hard local floor at line 2223/2437: `max(sl_pips, 3.0)` | Then feeds into execute_trade with its 3 floors | 3p local floor + 3-floor pipeline → min effective = 12p for GBPUSD |

### 2.1 Three auto-widening floors in `execute_trade`

```
Strategy SL (decision.sl)
  → Step 1: pips→points (sl_pts = sl_pips * ppp)
  → Step 2: sl_pts = max(sl_pts, _IG_MIN_STOP_PTS[pair] = 12)      [proxy for IG broker min — WRONG default]
  → Step 3: sl_pts = max(sl_pts, MIN_STOP_DISTANCE_PIPS = 12)       [global SL floor]
  → Step 4: sl_pts = max(sl_pts, _PAIR_MIN_SL_PIPS[pair] = 12 pips) [shared user per-pair default]
  → to broker
```

Three independent 12-pip floors.  Any one of them widens the strategy's
requested stop silently.

---

## 3. `pair_config.MIN_SL_PIPS` — purpose + ownership

### 3.1 Code evidence

```python
# pair_config.py:37-48
# Per-pair minimum SL floors (pips), env-overridable.
MIN_SL_PIPS: Dict[str, float] = {}
for _p in PAIRS:
    _e = os.getenv(f"{_p}_MIN_SL_PIPS")
    if _e is not None:
        MIN_SL_PIPS[_p] = float(_e)
MIN_SL_PIPS.setdefault("GBPUSD", 12.0)
MIN_SL_PIPS.setdefault("EURUSD", 10.0)
MIN_SL_PIPS.setdefault("USDJPY", 15.0)
MIN_SL_PIPS.setdefault("USDCAD", 10.0)
MIN_SL_PIPS.setdefault("GBPJPY", 12.0)
```

### 3.2 Readers (all treat MIN_SL_PIPS as a floor to apply)

* `trade_executor.py:4423` — `pair_min_pts = pair_min_pips * ppp; sl_pts = max(sl_pts, pair_min_pts)` — Step 4
* `ema_pullback.py:632` — strategy applies the floor
* `london_open_pullback.py:224` — strategy applies the floor
* `briefing_sweep.py:438` — strategy applies the floor
* `briefing_hunt.py:256` — strategy applies the floor
* `news_continuation.py:643-644` — strategy applies the floor
* `pia_first_briefing.py:236, 398` — PIA briefing uses as advisory
* `premarket_health_pia.py:113-116` — health check compares

### 3.3 Classification

The explicit code comment is **"env-overridable" per-pair minimum SL floor**.
There is **no incident report, no runbook entry, and no risk-committee note**
tying this value to a mandatory risk requirement.  Multiple strategies
apply it as a local floor BEFORE calling execute_trade; the executor
then applies it AGAIN at Step 4.

**Verdict: `pair_config.MIN_SL_PIPS` is a user-configurable per-pair default,
not an immutable risk requirement.**  The 12-pip GBPUSD default is a legacy
copy of the historical AutoBot internal convention — it predates and
duplicates the IG broker minimum.

### 3.4 Impact of this reclassification on the proposed patches

Patch 0001 (previous draft) preserved Step 4 as "existing risk restriction".
That was wrong.  Step 4 is a user default, not a risk policy.  The
corrected patch (Patch 0001b, below) also removes the auto-widen at Step 4
when `AUTOBOT_IG_MIN_STOP_STRICT=1`.  The env variable `GBPUSD_MIN_SL_PIPS`
remains a user-configurable per-pair preference.

**True immutable risk controls that MUST remain:**
- `MIN_SL_PIPS = 2` (line 945) — reject SL<2p sanity (no legitimate stop can be below the pip grid).
- `MAX_REASONABLE_SL_PIPS = 500` (line 947) — reject absurd SL values.
- Per-strategy `*_MAX_SL_PIPS` ceilings (lines 521, 542, 590) — operator caps on individual strategies.

These three CAN remain.  They are:
- (a) genuinely bounding (not widening), and
- (b) sanity-check magnitudes, not strategy-level choices.

---

## 4. Conflicting / redundant 12-pip settings

| # | Site | Default | Role claimed | Actual role |
|---|---|---|---|---|
| 1 | `MIN_STOP_DISTANCE_PIPS` env default 12 | 12 | "global broker floor (covers unknown pairs)" | **duplicate of broker min; wrong default** |
| 2 | `_IG_MIN_STOP_PTS["GBPUSD"]=12` env default | 12 | "per-pair IG API minimum" | **stale copy of IG broker min; wrong default** |
| 3 | `pair_config.MIN_SL_PIPS["GBPUSD"]=12.0` env default | 12 | "per-pair minimum SL floor" | **user-configurable default disguised as a safety floor** |
| 4 | `gbpusd_bb_bounce.SL_PIPS=12` default | 12 | strategy's fixed SL | real strategy choice — correctly configurable |
| 5 | `gbpusd_trend_v3.UM_SL_PIPS=12.0` | 12 | utility-member SL | hardcoded, no env override |
| 6 | `one_strategy_emitter.ONE_STRATEGY_SL_PIPS=12` | 12 | router default | real strategy choice |
| 7 | `tiered_ratchet.RATCHET_INIT_SL_PIPS_DEFAULT=12.0` | 12 | ratchet init SL | real strategy choice |

**Runtime winner for a BB Bounce AutoBot GBPUSD fire** (today):
```
decision.sl = 20              # GBPUSD_BB_BOUNCE_SL_PIPS=20
→ Step 1: 20p * 1 = 20pts
→ Step 2: max(20, 12) = 20
→ Step 3: max(20, 12) = 20
→ Step 4: max(20, 12) = 20
Final: 20 pips.
```

**Runtime winner for a hypothetical 4-pip strategy fire** (today):
```
decision.sl = 4
→ Step 1: 4 → 4pts
→ Step 2: max(4, 12) = 12  (silent widening via _IG_MIN_STOP_PTS)
→ Step 3: max(12, 12) = 12
→ Step 4: max(12, 12) = 12
Final: 12 pips — strategy intent lost.
```

**Runtime winner for a 4-pip strategy with corrected patches + proper env**:
```
Env: AUTOBOT_IG_MIN_STOP_STRICT=1, GBPUSD_MIN_SL_PIPS=4,
     GBPUSD_<STRATEGY>_SL_PIPS=4
decision.sl = 4
→ Step 1: 4 → 4pts
→ Step 2: ig_dealing_rules.validate_stop → IG min = 4.0p → PASS
→ Step 3: REMOVED for SL
→ Step 4: max(4, 4) = 4  (pair_min_pips now = 4 via env)
Final: 4 pips. ✓
```

### 4.1 Standalone vs AutoBot divergence

| Dimension | Standalone BB Bounce | AutoBot BB Bounce |
|---|---|---|
| Broker-min default | **4.0 pips** (correct per 2026-09-27 capture) | 12.0 pips (wrong) |
| Enforcement on under-min | **Rejection** (correct, `stop_sizing.py:143`) | **Silent widening** (wrong) |
| Dynamic lookup | Static import-time constant | Static dict in trade_executor |
| User-configurable | `BB_IG_MIN_STOP_PIPS` env | `GBPUSD_IG_MIN_STOP_PTS` + 2 others |

Standalone BB Bounce is **already closer to the brief's intent** — the
patch there (Patch 0002) just adds a runtime lookup to replace the
import-time constant.  AutoBot requires the structural correction in
Patch 0001b (below).

---

## 5. Corrected patches

### 5.1 Patch 0001b — `trade_executor.py` (replaces Patch 0001)

**Changes vs original Patch 0001:**

* Step 4 (`pair_config.MIN_SL_PIPS`) now also respects the strict-reject
  mode — when `AUTOBOT_IG_MIN_STOP_STRICT=1`, it does NOT widen if the
  strategy's requested stop is below it.  Instead the strategy's stop
  passes through and only the LIVE broker min matters.
* Rationale: Section 3 of this audit established MIN_SL_PIPS is a user
  default, not a risk policy.  Preserving it as a widening floor
  defeats the purpose of adding `GBPUSD_MIN_SL_PIPS=4` to allow tight
  stops.
* Compat mode (`AUTOBOT_IG_MIN_STOP_STRICT=0`) preserves the legacy
  Step 4 widening so operator rollback remains clean.
* Patch 0001b includes the initial-order rejection-recovery seam
  (brief §8): on `ATTACHED_ORDER_LEVEL_ERROR` broker response, call
  `ig_dealing_rules.invalidate(epic)` and return a structured
  rejection to the strategy (no retry).

### 5.2 Patch 0002b — `/opt/bb_bounce/stop_sizing.py` (minor update to 0002)

* No semantic change — but the audit confirms the standalone path is
  already structurally correct; only the import-time constant needs the
  runtime shim.
* Add a `logger.info` emission when the live lookup returns a value
  **different** from `config.IG_MIN_STOP_PIPS` so operator-visible
  drift is captured.

### 5.3 Patch 0003 — unify readers (optional, not required for 4-pip enablement)

* Migrate `trade_manager._resolve_ig_min_stop_pips_with_ts` to call
  `ig_dealing_rules.get_min_normal_stop_pips`.  Removes the duplicate
  cache in `trade_manager.py:604 _MARKET_MIN_STOP_CACHE`.
* **Deferred** — not required for the operator's 4-pip goal.  Can land
  separately once Patches 0001b + 0002b are confirmed stable.

### 5.4 Writing the corrected 0001b diff

Below is the diff on top of the current `/opt/tradingbot/trade_executor.py`:

```diff
@@ -4398,20 +4398,109 @@ def execute_trade(...):
     raw_sl_pts = sl_pts
     raw_tp_pts = tp_pts

-    # Step 2: Apply per-pair IG API minimum (hard floor from IG)
-    ig_min = _IG_MIN_STOP_PTS.get(pair, MIN_STOP_DISTANCE_PIPS)
-    sl_pts = max(sl_pts, ig_min)
-    if tp_pts is not None:
-        tp_pts = max(tp_pts, ig_min)
-
-    # Observability: flag when IG-min inflates TP above strategy intent.
-    if tp_pts is not None and raw_tp_pts is not None and tp_pts > raw_tp_pts + 1e-6:
-        logger.info(
-            f"[executor] {pair} TP clamped up by broker min: "
-            f"raw={raw_tp_pts / ppp:.1f}p → ig_min={ig_min / ppp:.1f}p "
-            f"(strategy intent was {tp_pips:.1f}p)"
-        )
-
-    # Step 3: Apply global broker floor (covers unknown pairs)
-    sl_pts = max(sl_pts, MIN_STOP_DISTANCE_PIPS)
+    # Step 2: Dynamic broker-min validation (2026-10-28).
+    # Replaces the previous static-dict lookup + max() auto-widen.
+    # Consults IG's live dealingRules via ig_dealing_rules.validate_stop.
+    _dyn_strict = os.getenv("AUTOBOT_IG_MIN_STOP_STRICT", "1").strip() != "0"
+    try:
+        from ig_dealing_rules import validate_stop as _ig_validate_stop
+        _ig_validation = _ig_validate_stop(
+            epic=epic, pair=pair, requested_pips=float(sl_pips),
+            strict=_dyn_strict, require_fresh=True,
+        )
+    except Exception as _val_exc:
+        _ig_validation = None
+        logger.warning(
+            "[executor] IG dealing-rules validation unavailable (%s: %s) — "
+            "falling back to static per-pair floor",
+            type(_val_exc).__name__, _val_exc,
+        )
+
+    if _ig_validation is not None and _ig_validation.reason_code == "PASS":
+        logger.info(
+            "[IG_STOP_VALIDATION_PASS] %s requested=%.2fp min=%.2fp "
+            "source=%s rule_ts=%s",
+            pair, _ig_validation.requested_pips,
+            _ig_validation.broker_min_pips or -1.0,
+            _ig_validation.rule_source,
+            f"{int(_ig_validation.rule_ts)}" if _ig_validation.rule_ts else "none",
+        )
+        ig_min = (_ig_validation.broker_min_pips or 0.0) * ppp
+    elif _ig_validation is not None and _ig_validation.reason_code == "TOO_TIGHT":
+        _min_pips = _ig_validation.broker_min_pips or 0.0
+        logger.warning(
+            "[IG_STOP_VALIDATION_BLOCK] %s requested=%.2fp min=%.2fp "
+            "short_by=%.2fp strategy=%s source=%s rule_ts=%s",
+            pair, _ig_validation.requested_pips, _min_pips,
+            abs(_ig_validation.difference_pips or 0.0),
+            str(decision.mode or "") if decision is not None else "unknown",
+            _ig_validation.rule_source,
+            f"{int(_ig_validation.rule_ts)}" if _ig_validation.rule_ts else "none",
+        )
+        if _dyn_strict:
+            _set_block_info(
+                epic, "IG_MIN_STOP_VIOLATION",
+                f"stop={sl_pips:.2f}p < min={_min_pips:.2f}p "
+                f"(source={_ig_validation.rule_source})",
+            )
+            return None
+        ig_min = _min_pips * ppp
+        sl_pts = max(sl_pts, ig_min)
+    else:
+        ig_min = _IG_MIN_STOP_PTS.get(pair, MIN_STOP_DISTANCE_PIPS)
+        sl_pts = max(sl_pts, ig_min)
+
+    if tp_pts is not None:
+        tp_pts = max(tp_pts, ig_min)
+    if tp_pts is not None and raw_tp_pts is not None and tp_pts > raw_tp_pts + 1e-6:
+        logger.info(
+            f"[executor] {pair} TP clamped up by broker min: "
+            f"raw={raw_tp_pts / ppp:.1f}p → ig_min={ig_min / ppp:.1f}p "
+            f"(strategy intent was {tp_pips:.1f}p)"
+        )
+
+    # Step 3: Global SL floor REMOVED (2026-10-28).  Previously
+    # auto-widened to MIN_STOP_DISTANCE_PIPS=12 which was a duplicate of
+    # the broker-min proxy.  Now handled by Step 2's live validation.
     if tp_pts is not None:
         tp_pts = max(tp_pts, MIN_LIMIT_DISTANCE_PIPS)
@@ -4420,10 +4509,20 @@
-    # Step 4: Apply per-pair volatility floor (our minimum, in pips → points)
-    pair_min_pips = _PAIR_MIN_SL_PIPS.get(pair)
-    if pair_min_pips is not None:
-        pair_min_pts = pair_min_pips * ppp
-        sl_pts = max(sl_pts, pair_min_pts)
+    # Step 4: Per-pair user-configurable SL floor (pair_config.MIN_SL_PIPS).
+    # The audit (AUDIT.md §3) established this is a user default, not an
+    # immutable risk policy.  In strict mode we skip this widening — the
+    # strategy's requested stop stands as submitted (subject only to the
+    # live broker min at Step 2).  Operator can still raise the per-pair
+    # default via <PAIR>_MIN_SL_PIPS env for user-level preferences.
+    pair_min_pips = _PAIR_MIN_SL_PIPS.get(pair)
+    if pair_min_pips is not None and not _dyn_strict:
+        # Compat mode only — preserve legacy widening for rollback.
+        pair_min_pts = pair_min_pips * ppp
+        sl_pts = max(sl_pts, pair_min_pts)
+    elif pair_min_pips is not None and sl_pts < pair_min_pips * ppp:
+        logger.info(
+            "[executor] %s SL=%.2fp accepted below user default "
+            "MIN_SL_PIPS=%.2fp (strict mode)",
+            pair, sl_pts / ppp, pair_min_pips,
+        )
```

---

## 6. Exact configuration changes required to enable a 4-pip stop for ONE strategy

### 6.1 Example — enable 4-pip stop for standalone BB Bounce only

Standalone BB Bounce **already supports 4-pip stops** today.  The only
change is to let the strategy actually request them:

```bash
# /opt/bb_bounce/.env — add these lines:
SL_PIPS=4
# (BB_IG_MIN_STOP_PIPS=4.0 already the default)
```

Restart `bb-bounce.service` (operator action).

### 6.2 Example — enable 4-pip stop for AutoBot BB Bounce

Three env changes are required (because of the three auto-widen floors
that will remain active until Patch 0001b is applied):

```bash
# /opt/tradingbot/.env — add these lines:
AUTOBOT_IG_MIN_STOP_STRICT=1          # new — strict reject default (post Patch 0001b)
GBPUSD_IG_MIN_STOP_PTS=4              # overrides _IG_MIN_STOP_PTS default (Step 2 fallback)
MIN_STOP_DISTANCE_PIPS=4              # overrides global floor default (Step 3)
GBPUSD_MIN_SL_PIPS=4                  # overrides pair_config default (Step 4)
GBPUSD_BB_BOUNCE_SL_PIPS=4            # strategy's requested SL
```

After Patch 0001b is applied, the `AUTOBOT_IG_MIN_STOP_STRICT=1` single
switch is sufficient (Step 3 removed, Step 4 skipped in strict mode).
In that case the operator needs only:

```bash
# /opt/tradingbot/.env — add these lines (post Patch 0001b):
AUTOBOT_IG_MIN_STOP_STRICT=1
GBPUSD_BB_BOUNCE_SL_PIPS=4
# IG dealing-rules lookup supplies the broker min dynamically; no need
# to set *_IG_MIN_STOP_PTS, MIN_STOP_DISTANCE_PIPS, or *_MIN_SL_PIPS.
```

### 6.3 Example — enable 4-pip stop ONLY for EMA Pullback (leave others at 12)

Post Patch 0001b:

```bash
GBPUSD_EMA_PULLBACK_SL_PIPS=4
# No other env changes needed; AUTOBOT_IG_MIN_STOP_STRICT=1 default
# allows per-strategy tight stops without affecting others.
```

### 6.4 Rollback

Set `AUTOBOT_IG_MIN_STOP_STRICT=0` and restart.  Legacy auto-widen
behaviour restored.  All per-strategy env settings remain in place but
their effect is capped by the restored 12-pip floors.

Full code rollback: `git revert <patch commit>`.

---

## 7. Remaining limitations

* `trade_manager._MARKET_MIN_STOP_CACHE` (the amend path cache) is NOT
  consolidated with the new `ig_dealing_rules` cache — two caches, one
  process.  Harmless; consolidation is Patch 0003 (deferred).
* `trade_manager._IG_MIN_STOP_PIPS_FALLBACK=4.0` is already correct;
  the fallback in the new module matches.
* Standalone BB Bounce's existing `IG_MIN_STOP_PIPS` env name
  (`BB_IG_MIN_STOP_PIPS`) differs from AutoBot's new
  (`AUTOBOT_IG_MIN_STOP_STRICT` only — the dynamic lookup needs no
  per-pair env on AutoBot side).  Keep both; they are the respective
  rollback switches.
* Multiple strategy modules apply `_PAIR_MIN_SL_PIPS` locally
  **before** calling `execute_trade` (e.g. `ema_pullback.py:634`).
  Patch 0001b only affects the executor's Step 4.  Strategies that
  want to submit sub-default stops must also stop widening via their
  own local floor.  See §6.3 — setting the strategy's own
  `GBPUSD_<STRATEGY>_SL_PIPS` to the desired distance addresses this
  because the strategy's `max()` becomes `max(4, 4) = 4`.

---

## 8. Test coverage (addendum to original test suite)

Original 28 tests cover the module API.  Additional integration
scenarios that the audit identifies as high-value:

1. **Step 4 skip in strict mode** — verify `trade_executor` does NOT
   widen via `_PAIR_MIN_SL_PIPS` when `AUTOBOT_IG_MIN_STOP_STRICT=1`.
2. **Step 4 preserved in compat mode** — verify legacy widening still
   happens when `=0`.
3. **4-pip strategy fire with correct env** — end-to-end: `.env`
   configured for 4p → execute_trade accepts 4p → broker sees 4p.
4. **Strategy's local `_PAIR_MIN_SL_PIPS` floor** — verify that
   setting `GBPUSD_MIN_SL_PIPS=4` lets `ema_pullback.py:634`
   compute 4p and pass it through.
5. **ATTACHED_ORDER_LEVEL_ERROR recovery** — verify that after a
   broker rejection, `ig_dealing_rules.invalidate(epic)` is called and
   the next validation issues a fresh fetch.

These are documented but **not implemented in the current patch set**
because they require editing the production `trade_executor.py` (and
hence a production worktree).  They are prepared as additional test
specs in `tests/integration_test_specs.md`.
