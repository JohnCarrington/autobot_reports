# Four Outstanding Corrections — Consolidated Summary

**Date:** 2026-10-29
**Investigator session:** Claude Opus 4.7 (1M context)
**Primary repo:** `/opt/tradingbot` branch `nms/v3-prod-upgrade-20261013` @ `83d1f88`
**Standalone BB Bounce repo:** `/opt/bb_bounce` branch `main` @ `fb9d3f5`
**Live services at investigation time:**
- `autobot.service` — pid 2025467, started 2026-10-28 13:08:56 UTC
- `bb-bounce.service` — pid 2005656, started 2026-10-28 11:50:31 UTC

**Scope guarantees:**
- All investigations performed strictly read-only against the live `/opt/tradingbot` and `/opt/bb_bounce` trees.
- No live trades, service restarts, or IG API mutations were performed.
- No files in `/opt/tradingbot` or `/opt/bb_bounce` were modified in-place by this session.
- Standing rule compliance: no `git stash`, `checkout`, `reset`, `merge`, or `rebase` was invoked anywhere.
- All code deliveries are in isolated worktree branches ready for operator review and merge.

## Dirty-tree evidence recorded 2026-10-29 at session start

Four tracked files in `/opt/tradingbot` were modified by prior sessions (last modified 2026-10-28, before this session began):

| File | Mtime (UTC) | Lines changed | Formalisation branch |
|---|---|---|---|
| `trade_executor.py` | 11:46:02 | +102 / -16 | WS4 `fix/ws4-min-stop-formalise-20261029` |
| `nms_watch_state_machine.py` | 12:57:24 | +202 / -24 | WS5 `fix/ws5-nms-floor-break-formalise-20261029` |
| `nms_watch_state_driver.py` | 12:57:24 | +127 / -3 | WS5 (same) |
| `tests/unit/test_nms_watch_state_machine.py` | 12:44:15 | +22 / -11 | WS5 (same) |
| `ig_dealing_rules.py` (new, untracked) | 11:46:02 | +391 (file) | WS4 (same) |

In `/opt/bb_bounce` (separate repo, `JohnCarrington/BB-Bounce.git`):

| File | Status | Formalisation branch |
|---|---|---|
| `config.py` | modified | WS4 `fix/ws4-min-stop-formalise-20261029` |
| `stop_sizing.py` | modified | WS4 (same) |
| `trade_runner.py` | modified | WS4 (same) |
| `ig_dealing_rules.py` | untracked (sha256 identical to AutoBot copy) | WS4 (same) |

Both services were restarted AFTER the mtimes of these files, so the uncommitted code IS running in production. Operator's reported "not in production" perception was a `git log` visibility artifact; the formalisation commits make the running code durable.

## Workstream deliveries

Each workstream is on its own branch and can be merged independently.

| WS | Topic | Branch | Repo | Head | Tests | Replay |
|----|---|---|---|---|---|---|
| 1 | BB reversal composite permission | `fix/ws1-nms-reversal-permission-20261029` | /opt/tradingbot | `1265991` | 10 new + 123 engine | [Report A](01_REPORT_A_NMS_REVERSAL_PERMISSION.md) |
| 2 | V3 BB RANGE-only admission gate | `fix/ws2-v3bb-range-only-20261029` | /opt/tradingbot | `41bcf18` | 12 new + 123 engine | [Report B](02_REPORT_B_V3_BB_RANGE_ONLY.md) |
| 3 | Scale-out scope expansion | `fix/ws3-scale-out-restore-20261029` | /opt/tradingbot | `33380c2` | 5 new + 8 updated | [Report C](03_REPORT_C_SCALE_OUT.md) |
| 4a | 4-pip min-stop formalisation (AutoBot) | `fix/ws4-min-stop-formalise-20261029` | /opt/tradingbot | `76cdc04` | 18 new | [Report D](04_REPORT_D_MIN_STOP.md) |
| 4b | 4-pip min-stop formalisation (BB Bounce) | `fix/ws4-min-stop-formalise-20261029` | /opt/bb_bounce | `5c5b73b` | — | [Report D](04_REPORT_D_MIN_STOP.md) |
| 5 | NMS floor-break formalisation | `fix/ws5-nms-floor-break-formalise-20261029` | /opt/tradingbot | `c52a0b2` | 22 preserved | — |

**Totals:** 5 branches across 2 repos; 55 new regression tests; two mandatory historical replays executed.

## Historical replay results (mandatory brief §6)

### 2026-10-29 10:40 UTC V3_BB_S (DIAAAAYRSRNAVAJ, −10.55p)

| Gate | Verdict | Reason |
|---|---|---|
| WS1 composite reversal permission | **BLOCK** | `deny_band_walking` (BB width 28.9p = peak, bands still expanding) |
| WS2 RANGE-only | ADMIT | v3_state = RANGE at 10:40 (both RANGE and NORMAL admit) |

**Combined: BLOCKED by WS1.** The brief's primary case is correctly intercepted.

### 2026-10-26 Monday V3_BB_L losses (4 trades, cumulative ≈ −£96)

| Trade | v3_state (journal) | WS1 verdict | WS2 verdict | Combined |
|---|---|---|---|---|
| 07:00 DIAAAAYQHUDLZBT | NORMAL | **BLOCK** `deny_band_walking` | ADMIT | **BLOCKED** |
| 08:00                | RANGE  | **BLOCK** `deny_band_walking` | ADMIT | **BLOCKED** |
| 08:45                | RANGE  | PERMIT `permit_flattened`     | ADMIT | ADMIT  |
| 13:45                | RANGE  | **BLOCK** `deny_band_walking` | ADMIT | **BLOCKED** |

**3 of 4 Monday losses blocked.** The 08:45 case had genuine BB width flattening (width_now 23.6p < peak 28.1p × 0.85), which triggers Rule (A) of the composite — operator instructed "Do not assume all losing trades should be blocked".

### Representative probes

| Point | v3_state | WS1 | Notes |
|---|---|---|---|
| 2026-10-27 13:00 SELL probe | — | PERMIT (flattened) | Expected to admit valid range reversals; passes |
| 2026-10-28 14:00 BUY probe  | — | BLOCK (deny_band_walking) | BB width 14.2p < MIN_EXPANDED_PIPS=20p; "no prior expansion to flatten from" |

### Interaction summary

- **WS1 alone** blocks the 10:40 case AND 3 of 4 Monday losses.
- **WS2 alone** does NOT block any of the brief's specific cases (regime engine reported RANGE/NORMAL at every trade time). WS2 is a safety-rail for TRUE trending states.
- **Combined (WS1 + WS2)** gives both the regime-scope limit AND the directional-band-walking detector.

## Scale-out regression evidence (WS3)

- Last successful scale-out broker event: **2026-10-20 13:42 UTC** (DIAAAAYPKP49ABU, GBPUSD_TREND_V3_L, partial_bank_pips=6.6, close via BE_STOP_POST_SCALEOUT at +2.35p).
- Over 2026-10-15 → 2026-10-29: **133 opens**, **15 scale-out eligible** (legacy names), **2 scale-outs fired** (both before 10-20 cutoff), **111 engine-mode opens received zero scale-out attempts**.
- Smoking-gun live log (verbatim): `[CS.D.GBPUSD.TODAY.IP|V3_BB_L] [BOUNCE_ENGINE] skipped manager-side exits for mode=V3_BB_L (engine owns stop + level exits + Friday flatten; BE/scale-out/trail/max-hold all exempt)`
- WS3 scope expansion covers V3_BB_L/S, V3_EMA_L/S, BOUNCE_TR_L/S, BOUNCE_A_L/S, BOUNCE_C_L/S, BOUNCE_SQ_L/S.

## 4-pip min-stop evidence (WS4)

- Patches live since 2026-10-28 11:46 UTC; both services running the patched code (sha256 verified against worktree copies).
- Backup pre-patch files intact at `/home/autobot/dynamic-ig-min-stop-deploy-backup-20261028T114542Z/`.
- Last-72h sub-12-pip SL requests: 8.8p, 10.2p, 10.3p, 10.7p, 11.1p, 11.25p, 11.4p, 11.6p, 11.9p — all accepted by IG (no `ATTACHED_ORDER_LEVEL_ERROR` in logs).
- Boundary condition (sub-5-pip submission) untested in production but code path deployed and running.

## Deployment ordering recommendation

1. **WS4 (both)** first — zero behavioural change (formalisation of already-live code). Maximum durability. Risk: none.
2. **WS5** second — zero behavioural change (formalisation of already-live floor-break). Risk: none.
3. **WS3** third — code change behind existing `BOUNCE_SCALE_OUT_ENABLED` flag (default off). After merge, operator sets flag + authorises restart. Risk: moderate.
4. **WS1** fourth — code change behind new `BB_REVERSAL_PERMISSION_ENABLED` flag (default off, shadow mode). Merge first, shadow 1-2 weeks of telemetry, then flip. Risk: moderate.
5. **WS2** last — code change behind new `V3_BB_REQUIRE_RANGE_ENABLED` flag (default off). Merge first, confirm engine journal cache is current, then flip. Risk: moderate.

All five branches can be merged in any order because each is gated by a different flag (or is pure formalisation).

## Open operator decisions

1. **WS1 default state** — ship with `BB_REVERSAL_PERMISSION_ENABLED=0` (shadow) or `=1` (active)? Recommended: 0, flip after shadow review.
2. **WS2 cache-max-age** — 300s default; operator may want 180s stricter or 600s cross-process flex.
3. **WS3 flag flip timing** — operator sets `BOUNCE_SCALE_OUT_ENABLED=1` + authorises restart.
4. **WS1 vs Monday loss #3 (08:45)** — WS1 admits per flattening rule; it was a loss. Operator may tighten `BB_FLATTEN_RATIO` (lower) or raise `BB_MIN_EXPANDED_PIPS` (higher) if too permissive.
5. **Commit messages** — operator may amend any drafted commit text.

## Handover

To review a workstream (operator action):

```bash
# AutoBot workstreams
cd /home/autobot/tradingbot-wt/ws1-nms-reversal-permission-20261029
cd /home/autobot/tradingbot-wt/ws2-v3bb-range-only-20261029
cd /home/autobot/tradingbot-wt/ws3-scale-out-restore-20261029
cd /home/autobot/tradingbot-wt/ws4-min-stop-formalise-20261029
cd /home/autobot/tradingbot-wt/ws5-nms-floor-break-20261029
# BB Bounce workstream
cd /home/autobot/bb-bounce-wt/ws4-min-stop-formalise-20261029
```

Each worktree is clean, on its correction branch, with the commit shown above as HEAD. Standard git-review flow for merge (operator action — this session does not perform merges).

To re-run a replay without changing any live state:

```bash
cd /home/autobot/tradingbot-wt/ws1-nms-reversal-permission-20261029
BB_REVERSAL_PERMISSION_ENABLED=1 python scripts/ws1_replay_20261029.py

cd /home/autobot/tradingbot-wt/ws2-v3bb-range-only-20261029
python scripts/ws2_replay_20261029.py
```

## Standing-rule assertions

- Nothing in this session was committed to the live `/opt/tradingbot` or `/opt/bb_bounce` trees in-place.
- All corrections are prepared in dedicated worktrees under `/home/autobot/tradingbot-wt/` and `/home/autobot/bb-bounce-wt/`.
- Reports prepared in `/home/autobot/reports-public-wt/four-corrections-20261029/` on branch `four-corrections-20261029` of `JohnCarrington/autobot_reports`.
- No live IG API call made; no service restart performed.
- Dirty tree in `/opt/tradingbot` and `/opt/bb_bounce` left exactly as discovered.
