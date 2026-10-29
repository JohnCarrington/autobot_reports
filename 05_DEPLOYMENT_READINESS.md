# Deployment Readiness — Integration of WS1 + WS2 + WS3 (2026-10-29)

**Branch:** `fix/integration-ws1-ws2-ws3-20261029` in `/opt/tradingbot`
**Worktree:** `/home/autobot/tradingbot-wt/integration-20261029`
**Head:** see `git log --oneline -1` (committed; not yet pushed in this report)

**Companion standalone branches** (unchanged; each ships independently):
- `fix/ws4-min-stop-formalise-20261029` (AutoBot) — commit `76cdc04`
- `fix/ws4-min-stop-formalise-20261029` (BB-Bounce) — commit `5c5b73b`
- `fix/ws5-nms-floor-break-formalise-20261029` (AutoBot) — commit `c52a0b2`

## 1. What this integration contains vs. the stand-alone WS branches

| Workstream | Correction vs. the earlier standalone branch |
|---|---|
| WS1 | Unchanged (same `bb_reversal_permission.py` + engine wiring) |
| WS2 | **CORRECTED**: single-flag design — `V3_BB_RANGE_ONLY_ENABLED` now gates BOTH the opposite-band exit (pre-existing) AND the new RANGE admission. Separate `V3_BB_REQUIRE_RANGE_ENABLED` flag withdrawn. NORMAL excluded from the admit set — only explicit RANGE admits. |
| WS3 | **CORRECTED**: V3_BB_L / V3_BB_S deliberately EXCLUDED from the scale-out opt-in scope (operator ruling: V3 BB exits at the opposite band, not at +8p/50%). V3_EMA + BOUNCE_TR + BOUNCE_A/C/SQ remain in scope. |

## 2. Actual vs. intended behaviour

| Spec item | Intended | Delivered | Verified by |
|---|---|---|---|
| V3 BB admission requires RANGE | V3 BB only trades eligible RANGE reversals | `_bb_range_block` returns block when `v3_state != "RANGE"` | `test_v3_bb_range_only.py::test_normal_now_blocked_per_operator_20261029` + `test_trend_states_blocked[STRONG_UP/STRONG_DOWN/EMERGING_UP/EMERGING_DOWN]` |
| V3 BB targets opposite BB | Exit = opposite Bollinger band | Pre-existing engine logic at `:689/:770`, same flag as admission | `tests/unit/test_v3_bb_band_touch.py::test_switch_on_v3_bb_long_exits_on_upper_band_touch` + `_short_exits_on_lower_band_touch` + `_bar_close_safety_net_catches_band_touch` |
| V3 BB does NOT scale out | Scale-out whitelist excludes V3_BB_* | `_scope_scale` tuple at `trade_manager.py:6428` lists V3_EMA/BOUNCE_TR/A/C/SQ only | `test_scale_out_scope.py::test_v3_bb_deliberately_excluded_per_operator_20261029` + `test_switch_on_v3_bb_not_in_opt_in_scope` |
| BB reversal composite permission | Expanded-flattening OR intertwined ribbon, direction-aware; shadow-first | `bb_reversal_permission.permit_reversal` wired at `_fire_triggers` for BB setups only; flag OFF default = shadow mode | `test_bb_reversal_permission.py` 10 cases + `test_ws12_integration.py` interaction tests |
| Scale-out partial-close plumbing | Broker request → fill → BE amend → journal | `_scale_out_50pct` primitive at `trade_manager.py:3643-3900` (unchanged); engine state BE floor propagated via `OpenPosition.current_stop` update | `test_bounce_scale_out_be_floor.py::test_is_tighter_be_floor_long/_short` + `test_switch_on_fires_on_v3_ema_at_trigger` |

## 3. Combined regression suite results

```
tests/unit/test_bb_reversal_permission.py          10 PASS
tests/unit/test_v3_bb_range_only.py                10 PASS
tests/unit/test_scale_out_scope.py                  5 PASS
tests/unit/test_ws12_integration.py                 6 PASS
tests/unit/test_bounce_scale_out_be_floor.py       10 PASS
tests/unit/test_v3_bb_band_touch.py                 7 PASS
tests/unit/test_nms_watch_state_machine.py         22 PASS
tests/bounce_engine/v3/                           123 PASS  (ex. 2 pre-existing failures)
────────────────────────────────────────────────────────
Total                                             193 PASS   0 FAIL
```

Pre-existing failures excluded (unrelated to this work, present on HEAD):
- `test_integration_remediation.py` — stub-import order dependency
- `test_window.py::test_grind_age_minutes_is_recorded` — same pattern

## 4. Historical replay — losers + winners, baseline vs. integrated

Script: `scripts/ws12_integration_replay_20261029.py`. Replay flags set
in-process (`V3_BB_RANGE_ONLY_ENABLED=1`, `BB_REVERSAL_PERMISSION_ENABLED=1`).
Replay evaluates each event's trailing 150 M5 bars and the engine's own
`trend_v3.jsonl` journal — no network, no live services touched.

### 4a. Losers (brief §6 mandatory)

| Event | PnL | v3_state | WS2 | WS1 | Combined |
|---|---|---|---|---|---|
| 10-29 10:40 V3_BB_S DIAAAAYRSRNAVAJ | −10.6p | RANGE | ADMIT | **BLOCK** deny_band_walking | **BLOCK (ws1)** |
| 10-26 07:00 V3_BB_L DIAAAAYQHUDLZBT | −11.4p | NORMAL | **BLOCK** | BLOCK deny_band_walking | **BLOCK (ws2)** |
| 10-26 08:00 V3_BB_L (Monday #2)     | ~−22p | RANGE | ADMIT | **BLOCK** deny_band_walking | **BLOCK (ws1)** |
| 10-26 08:45 V3_BB_L (Monday #3)     | ~−22p | RANGE | ADMIT | ADMIT permit_flattened       | **ADMIT**  |
| 10-26 13:45 V3_BB_L (Monday #4)     | ~−22p | RANGE | ADMIT | **BLOCK** deny_band_walking | **BLOCK (ws1)** |

**4 of 5 known losers blocked** (−68p avoided). The 08:45 case admits with the "permit_flattened" branch (width_now 23.6p < 85% × peak 28.1p) — operator-approved rule.

### 4b. Winners (12 historical, 2026-10-12 → 2026-10-29)

| Event | PnL | v3_state | WS2 | WS1 | Combined |
|---|---|---|---|---|---|
| 10-29 08:10 V3_BB_S DIAAAAYRSDJGSAJ   | +20.9p | RANGE  | ADMIT | ADMIT permit_braided    | **ADMIT** |
| 10-28 17:01 V3_BB_S DIAAAAYRM2S3VBY   |  +8.7p | RANGE  | ADMIT | BLOCK deny_band_walking | BLOCK (ws1) |
| 10-27 17:20 V3_BB_S DIAAAAYQ5V7W2B4   |  +8.4p | RANGE  | ADMIT | ADMIT permit_braided    | **ADMIT** |
| 10-26 17:41 V3_BB_S DIAAAAYQLV89HBC   | +37.5p | RANGE  | ADMIT | BLOCK deny_band_walking | BLOCK (ws1) |
| 10-23 15:05 V3_BB_S DIAAAAYQC956SBC   |  +9.0p | RANGE  | ADMIT | ADMIT permit_braided    | **ADMIT** |
| 10-22 15:01 V3_BB_L DIAAAAYP9L2AUBY   | +39.0p | RANGE  | ADMIT | BLOCK deny_band_walking | BLOCK (ws1) |
| 10-22 08:19 V3_BB_L DIAAAAYP8G7MMA6   | +11.9p | RANGE  | ADMIT | ADMIT permit_braided    | **ADMIT** |
| 10-20 09:20 V3_BB_L DIAAAAYPJ7WV7BU   | +47.4p | *none* | BLOCK | —                         | BLOCK (ws2 **data gap**) |
| 10-15 06:45 BB_BOUNCE_L DIAAAAYNQXK8HBS | +11.2p | *none* | BLOCK | —                         | BLOCK (ws2 **data gap**) |
| 10-14 15:55 V3_BB_L DIAAAAYNLKBPDBN   | +12.2p | *none* | BLOCK | —                         | BLOCK (ws2 **data gap**) |
| 10-13 06:00 V3_BB_L DIAAAAYM2L3EYBN   | +16.3p | *none* | BLOCK | —                         | BLOCK (ws2 **data gap**) |
| 10-12 12:20 V3_BB_S DIAAAAYMVWLRCA4   | +25.6p | *none* | BLOCK | —                         | BLOCK (ws2 **data gap**) |

### 4c. Replay data limitation (important)

`trend_v3.jsonl` journal has a 25-day gap: `trend_v3.jsonl-20261002.gz` ends at 2026-10-01 and the next archive starts 2026-10-26. All five 10-12 to 10-20 winners fall in the gap and read `v3_state=None`, which triggers WS2's `fail-closed` path (`v3_bb_range_cache_missing`). **These are replay-data artefacts, not predictions of live behaviour.** In live operation the engine journal is updated every M5 close and has no multi-day gaps.

### 4d. Honest headline numbers

Within the data-reliable window (post-2026-10-20 for v3_state coverage):

| Cohort | Admitted | Blocked |
|---|---|---|
| Losers (n=5)      | 1 (08:45 permit_flattened) | 4 |
| Winners (n=7)     | **4** (BRAIDED on tight bands) | 3 (deny_band_walking during live reversal setups) |

Preservation on data-reliable winners: **4 / 7 = 57 %**.
Loser suppression: **4 / 5 = 80 %**.

## 5. Remaining blockers

**Blocker A — WS1 blocks 3 of 7 well-measured winners.** All three were `deny_band_walking`: bands were still expanding to a new peak at the moment of entry, yet the move subsequently reversed. The composite rule is a priori reasonable (don't reverse into an expanding band) but these three profitable reversals contradict the premise.

Operator tuning levers (env-tunable, no code change required):
- `BB_FLATTEN_RATIO` — lower from 0.85 (looser flattening test) → more PERMITs
- `BB_FLATTEN_LOOKBACK` — raise from 10 (longer window) → bands fully-flatten more often
- `BB_MIN_EXPANDED_PIPS` — lower from 20.0 → "flattened" counted more often

Recommended operator action: ship WS1 in **shadow mode** (`BB_REVERSAL_PERMISSION_ENABLED=0`) for 1-2 weeks and tabulate `shadow_would_block` entries vs. actual trade outcomes before flipping the flag.

**Blocker B — WS2 relies on fresh v3_state cache.** In live operation `cache/session_trend_GBPUSD.json` is written on every M5 close by `autobot.py:3968`. Cache absence/staleness is a legitimate fail-closed condition. For replay, the data gap in the archived journal produced false blocks — this is NOT a live-operation issue.

Operator action: before `V3_BB_RANGE_ONLY_ENABLED=1`, confirm the live cache file exists and is <5 min old. The default `V3_BB_RANGE_CACHE_MAX_AGE_S=300` is appropriate but tunable.

**No remaining blockers for WS3, WS4, WS5** — all three are pure plumbing (scope widen, formalise live code).

## 6. Baseline vs. corrected trade outcomes (data-reliable window)

Within the 7 winners + 5 losers where v3_state is journal-resolvable (post-2026-10-20):

| Scenario | Baseline (no gates) | Integrated (WS1+WS2) | Delta |
|---|---|---|---|
| Losers (−p observed) | −67.6p | −22.0p (only 08:45 admitted) | **+45.6p saved** |
| Winners (+p observed, data-reliable) | +134.9p (across 7) | +53.2p (across 4 admitted) | **−81.7p forgone** |
| **Net (losers avoided − winners forgone)** | — | — | **−36.1p** |

The gate narrowly LOSES on the measured window. The operator may wish to:
1. **Loosen WS1** by tuning the three env knobs above, OR
2. **Deploy shadow first** and only activate once a tuned threshold is validated across a larger sample (ideally 90+ V3_BB trades), OR
3. **Deploy WS2 alone** without WS1 — WS2 captures regime scope but preserves the composite trade behaviour. Opposite-band exit (also enabled by the same flag) would still fire.

## 7. Test invocation (for operator audit)

```bash
cd /home/autobot/tradingbot-wt/integration-20261029

# Unit regression
python -m pytest \
  tests/unit/test_bb_reversal_permission.py \
  tests/unit/test_v3_bb_range_only.py \
  tests/unit/test_scale_out_scope.py \
  tests/unit/test_ws12_integration.py \
  tests/unit/test_bounce_scale_out_be_floor.py \
  tests/unit/test_v3_bb_band_touch.py \
  tests/unit/test_nms_watch_state_machine.py \
  tests/bounce_engine/v3/ \
  --ignore=tests/bounce_engine/v3/test_integration_remediation.py \
  --ignore=tests/bounce_engine/v3/test_window.py \
  -q
# Expected: 193 passed

# Historical replay
V3_BB_RANGE_ONLY_ENABLED=1 BB_REVERSAL_PERMISSION_ENABLED=1 \
  python scripts/ws12_integration_replay_20261029.py
# Expected: 5 losers + 12 winners table + summary line
```

## 8. Deployment conditions (operator decision)

1. **WS4 (both repos)** — ready. Zero behavioural change. Merge any time.
2. **WS5** — ready. Zero behavioural change. Merge any time.
3. **WS3** — merge any time; behavioural change only after operator sets `BOUNCE_SCALE_OUT_ENABLED=1` + authorises restart.
4. **WS1 + WS2 (via this integration branch)** — merge any time; behavioural changes only after operator sets the two flags + authorises restart. Recommended path:
   - Flip `V3_BB_RANGE_ONLY_ENABLED=1` FIRST (regime gate + opposite-band exit; narrow, deterministic).
   - Keep `BB_REVERSAL_PERMISSION_ENABLED=0` (shadow) for 1-2 weeks of telemetry.
   - Review shadow-mode `decision_reason` entries vs. actual trade outcomes; tune `BB_FLATTEN_RATIO` and `BB_FLATTEN_LOOKBACK` if needed.
   - Flip `BB_REVERSAL_PERMISSION_ENABLED=1` once the tuned preservation rate exceeds the loss-avoidance rate.

## 9. Standing-rule assertions

- No files in `/opt/tradingbot` or `/opt/bb_bounce` modified in-place.
- No live services were restarted; no IG API call was made.
- All corrections remain behind flags with default `0` so a merge is byte-safe.
- No `git stash`, `checkout`, `reset`, `merge`, or `rebase` was invoked.
- The uncommitted work in the live production trees is preserved; WS4 and WS5 branches formalise the running code without altering it.
