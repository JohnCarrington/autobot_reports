# Part A — Phase 1 C4 Deployment Report

**Author:** Claude Code (autobot)
**Date (UTC):** 2026-11-03T20:20Z
**Branch:** `deploy/phase1-c4-m5-regime-20261103`
**Mode:** Code deployed to disk. Activation requires operator `.env` edit + restart.

## 1. Pre-deployment checks (verified)

| Check | Result |
|---|---|
| autobot.service state | `active (running) since 2026-11-03 16:44:33 UTC` (today's V3 symbol-kwarg fix). PID 3504088. |
| bb-bounce.service state | `active` — adaptive-stop code deployed today. Untouched. |
| ema_pullback.service | inactive — unchanged. |
| C1 enabled? | **Yes.** `.env`: `NMS_V3_C1_CORRECTED_RECLAIM=1` |
| C2 enabled? | **Yes.** `.env`: `NMS_V3_C2_DIRECTIONAL_PENALTY=1` |
| C6 enabled? | **Yes.** `.env`: `NMS_V3_C6_DAYROLL_RESET=1` |
| C4 currently disabled? | **Yes.** `NMS_V3_C4_MULTI_DIM` not present in `.env` — defaults off. |
| Current v3_state in cache | `RANGE` (since 2026-11-03T19:35:00Z) |
| Pre-deploy session_trend.py SHA | `f4aceeee8c9c3665f666fac5c3e59c99c15b7e5f2594472788f0ff7c49d2cf83` |
| Pre-deploy nms_v3_classifier.py SHA | `f690fb9c3f3bf16f3423bb7b1f9f8767dcb6a2f3bf1e40dec55c11f9105d4a8b` (unchanged — only session_trend.py was edited) |

### 1.1 November 2–3 replay-duration correction

My 2026-11-03 23:00Z investigation (prior report) claimed: *"RANGE from 2026-11-02 08:00Z through 2026-11-03 13:40Z, 870 min, +13.4p directional move."*

**Corrected measurement** (from today's deterministic replay at `/mnt/volume_lon1_1778405456698/phase1_nms_range_investigation_20261103/replay_nms_v3.py`):

```
Continuous RANGE window:   2026-11-02T11:25Z → 2026-11-03T10:20Z
Elapsed:                   22h 55m (1335 min)
First-bar close:           13416.25
Last-bar close:            13407.45
Net drift:                 -8.80 pips
Window high:               13430.75
Window low:                13396.85
Envelope:                  33.90 pips
```

That is a textbook bounded range — 33.9p envelope with **−8.8p net drift**. The classifier correctly reported RANGE for the entire window. The original "+13.4p" was a cherry-picked endpoint comparison across the window.

## 2. Code change

Single file edited: `/opt/tradingbot/session_trend.py`. 6 hunks, 28 lines added, 0 lines removed. All additions are additive-only (new dataclass fields + persistence + cache publish).

Pre-deploy SHA: `f4aceeee8c9c3665f666fac5c3e59c99c15b7e5f2594472788f0ff7c49d2cf83`
Post-deploy SHA: `c2c7936cb2fb5aabec261d9c669f233d2b14d922f2e22045c8b285045beaab5e`

Backup: `/mnt/volume_lon1_1778405456698/phase1_c4_deploy_20261103/backup/session_trend.py.pre-c4`

### 2.1 Edit summary

| Location | Hunk | Add |
|---|---|---|
| `_SessionState` dataclass (~line 373) | 1 | `v3_m5_regime: Optional[str] = None` |
| `_SessionState.to_dict()` (~line 449) | 2 | `"v3_m5_regime": self.v3_m5_regime` |
| `_SessionState.from_dict()` (~line 525) | 3 | `v3_m5_regime=d.get("v3_m5_regime")` (back-compat: None if missing) |
| `SessionTrendAuthority` dataclass (~line 556) | 4 | `m5_regime: Optional[str] = None` |
| `SessionTrendAuthority.to_dict()` (~line 591) | 5 | `"m5_regime": self.m5_regime` |
| `_advance_v3_state()` (~line 1846) | 6 | `s.v3_m5_regime = v3_result.get("m5_regime")` after advance() |
| `_get_authority()` return (~line 2151) | 6 | `m5_regime=s.v3_m5_regime` |

### 2.2 What this does NOT change

- NMS thresholds (`EMERGING_ENTRY_THRESHOLD = 3`, `STRONG_ENTRY_THRESHOLD = 6`)
- Evidence family caps (`F-momentum = 1`, `F-supporting = 1`)
- Structural anchor requirements (`_emerging_struct_present` unchanged)
- Any strategy's admission permissions
- V3 BB entry / exit / execution rules
- Standalone BB Bounce
- EMA Pullback
- Scenario V2
- Stake / stop / TP for any strategy
- `nms_v3_classifier.py` SHA

## 3. Deterministic test results (6/6 PASS)

Test harness: `/mnt/volume_lon1_1778405456698/phase1_c4_deploy_20261103/test_c4_deploy.py`

```
T1 PASS: session_trend imports + SessionTrendAuthority has m5_regime field
T2 PASS 2026-10-23: C4 OFF → m5_regime == v3_state on all 168 post-London bars
T2 PASS 2026-10-30: C4 OFF → m5_regime == v3_state on all 156 post-London bars
T2 PASS 2026-11-02: C4 OFF → m5_regime == v3_state on all 192 post-London bars
T2 PASS 2026-11-03: C4 OFF → m5_regime == v3_state on all 145 post-London bars
T3 PASS 2026-10-23: C4 ON → sub-labels observed: ['CONSOLIDATION', 'INSUFFICIENT_DATA', 'TRANSITION']
T3 PASS 2026-10-30: C4 ON → sub-labels observed: ['CONSOLIDATION', 'INSUFFICIENT_DATA']
T3 PASS 2026-11-02: C4 ON → sub-labels observed: ['CONSOLIDATION', 'INSUFFICIENT_DATA']
T3 PASS 2026-11-03: C4 ON → sub-labels observed: ['CONSOLIDATION', 'INSUFFICIENT_DATA', 'TRANSITION']
T4 PASS 2026-10-23: v3_state sequence byte-identical C4 OFF vs ON (252 bars)
T4 PASS 2026-10-30: v3_state sequence byte-identical C4 OFF vs ON (252 bars)
T4 PASS 2026-11-02: v3_state sequence byte-identical C4 OFF vs ON (288 bars)
T4 PASS 2026-11-03: v3_state sequence byte-identical C4 OFF vs ON (241 bars)
T5 PASS: cache dict has m5_regime=CONSOLIDATION and v3_state=RANGE
T6 PASS: _SessionState persistence roundtrip + back-compat from_dict
```

**Key invariants proven:**
- T2 (661 bars): C4 OFF → `m5_regime == v3_state` byte-identical.
- T4 (1033 bars): v3_state sequence BYTE-IDENTICAL whether C4 is OFF or ON. **No strategy admission changes.**
- T6: Old on-disk state blobs (no `v3_m5_regime` key) deserialize cleanly with `None`.

## 4. Post-deploy verification

```
$ python3 -m py_compile /opt/tradingbot/session_trend.py
<no errors>

$ python3 -c "import ast; ast.parse(open('/opt/tradingbot/session_trend.py').read())"
AST parse OK

$ python3 -c "...dataclass field introspection..."
m5_regime in SessionTrendAuthority: True
v3_m5_regime in _SessionState   : True
```

autobot.service PID 3504088 (uptime 3h 33min at deploy time) is still running pre-deploy bytecode. Python does not hot-reload module code. **The new code is on disk but not in memory.**

## 5. Activation — operator-controlled

**Two operator-only actions are required to activate C4:**

### 5.1 Edit `/opt/tradingbot/.env`

Per the standing rule in `CLAUDE.md` ("Never edit .env") I did NOT modify `.env`. The operator must add exactly one line to `/opt/tradingbot/.env`:

```
NMS_V3_C4_MULTI_DIM=1
```

Best placed alongside the existing `NMS_V3_C6_DAYROLL_RESET=1` line to group the C-corrections.

### 5.2 Restart autobot.service

Per the standing rule in operator memory (`feedback_no_pkill_no_service_control`) I did NOT restart any service. The operator restart:

```
sudo systemctl restart autobot.service
```

### 5.3 Verification after restart

The operator can verify:

```
# 1. Service healthy
systemctl is-active autobot.service  # expect: active

# 2. All C-corrections live
grep -E 'NMS_V3_C[1-6]|NMS_V3_C4' /opt/tradingbot/.env
# expect: C1=1, C2=1, C4=1, C6=1

# 3. m5_regime appears in cache (on next post-London bar)
python3 -c "import json; print(json.load(open('/opt/tradingbot/cache/session_trend_GBPUSD.json'))['m5_regime'])"
# expect: one of INSUFFICIENT_DATA, RANGE, CONSOLIDATION, TRANSITION,
# EMERGING_UP, EMERGING_DOWN, STRONG_UP, STRONG_DOWN

# 4. v3_state still unchanged (no admission impact)
python3 -c "import json; print(json.load(open('/opt/tradingbot/cache/session_trend_GBPUSD.json'))['v3_state'])"
# expect: same as pre-restart (same RANGE value)

# 5. No new exceptions in the journal
journalctl -u autobot.service --since "5 minutes ago" | grep -iE "error|exception|traceback"
# expect: no NMS-related errors
```

## 6. Rollback

**Simplest (flag only):** operator removes `NMS_V3_C4_MULTI_DIM=1` from `.env` and restarts. The classifier returns `m5_regime == state` (byte-identical to pre-flag). Cache continues to publish `m5_regime` but it is identical to `v3_state`.

**Full code rollback:** restore the pre-deploy file:

```
sudo cp /mnt/volume_lon1_1778405456698/phase1_c4_deploy_20261103/backup/session_trend.py.pre-c4 /opt/tradingbot/session_trend.py
sudo systemctl restart autobot.service
```

**Rollback safety:** zero risk. The edit is additive only; no field was removed or renamed.

## 7. Preservation certification

- `nms_v3_classifier.py` SHA unchanged (`f690fb9c…` → `f690fb9c…`).
- `/opt/bb_bounce/` untouched (adaptive stop PID 3524400 preserved).
- `/opt/ema_pullback/`, `/home/autobot/ema_pullback/` untouched.
- `.env` untouched (operator action required).
- No service restart performed by me.
- No broker calls. No shadow mode. No IG DEMO execution change. No position / stake / TP / SL change.
- V3 regression fix (`live.py` SHA `38fb8d92…`) preserved.
- NMS C1 + C2 + C6 preserved (operator must also preserve them when adding the C4 line).

## 8. Open items (operator-controlled)

1. Operator edits `/opt/tradingbot/.env` to add `NMS_V3_C4_MULTI_DIM=1`.
2. Operator restarts `autobot.service`.
3. Operator verifies via §5.3.
4. Separately: Phase 2 investigation report follows as a distinct branch (`investigation/phase2-earlier-trend-recognition-20261103`).

**Stop. Awaiting operator activation. Phase 2 investigation published separately.**
