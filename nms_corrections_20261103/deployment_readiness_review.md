# NMS Corrections C1–C6 — Deployment Readiness Review

**Date:** 2026-11-03
**Status:** **DEPLOYMENT NOT APPROVED.** This review documents the audit the operator requested on 2026-11-03 before any production flag flip. Blocking issues identified in §12. Per-correction recommendations in §11.

**Nothing changed.** Production branches at the hashes documented in the earlier report. No services restarted. No broker action. No live env variable modified.

---

## 1. Executive summary — verdict per correction

| Correction | Verdict | Blocking issues |
|---|---|---|
| **C1** reclaim-requires-prior-excursion | **Deploy-after-C6** | 1 — needs restart to take effect |
| **C2** directional penalty on failed side | **Deploy-with-C1** | 1 — needs restart; no C1 without C2 and vice-versa in practice |
| **C3** rebalanced scoring | **Deploy-with-C1+C2** | 1 — needs restart; module-level C3_* constants also require restart to re-tune |
| **C4** multi-dimensional classification | **RECLASSIFY as DIAGNOSTIC-ONLY** | Not operationally wired — `m5_regime` has **zero production consumers**. Must not be claimed as admission authority. |
| **C5** BB_BOUNCE H1-direction gate | **DO NOT DEPLOY as-is — needs rework** | (a) fail-OPEN on missing/stale H1 snapshot — silent degradation; (b) would block **≥1 known Fri winner** (10-30T03:10 SELL +9.4p); (c) real-signal reconstruction shows only 2 of 9 Mon+Tue BB SELLs blocked |
| **C6** day-roll reset | **Deploy FIRST** | None material — reporting-only, no admission impact |
| **C7** trading-hours enforce | **Operator decision** (not a code fix) | Would eliminate 5 of 8 overnight Mon+Tue BB SELLs by prior investigation |

### Deployment-blocking issues (must address first)
1. **Disk at 99% full on `/`** — 343M free. Service restart during deployment risks log-flush failures (prior incident: 2026-10-29 disk-full event caused the systemd journal to lose the autobot restart window — see memory `project_disk_remediation_20261029`). Addressed in §10.
2. **C4 "unified multi-dimensional directional authority" claim is wrong** — `m5_regime` is populated by the classifier but written to no snapshot and read by no consumer. Report must be corrected before deploy.
3. **C5 fail-open posture is unsafe** — silent degradation to baseline free-pass when the H1 snapshot writer stops. Needs explicit fail-closed-on-unfresh behaviour before deploy.
4. **No hot-reload** — all flag flips require systemd service restart. Operator rollback plan must reflect this.
5. **Metric claim inconsistency** — "45–50% BB admit reduction" (ablation) vs "10% drop" (deployment plan) describe different populations. Reconciled in §5.

---

## 2. Q1 — Real BB_BOUNCE signal reconstruction (no candle proxy)

Source: `/opt/bb_bounce/reports/2026-{10-30,11-02,11-03}.csv`, `/opt/tradingbot/logs/nms_watch_state.jsonl*`, h1_macd_tiring MACD **reconstructed from 5m archive** using the Writer's exact formula (closed H1 series + forming H1 projection), `journalctl -u bb-bounce.service`.

### 2.1 Mon+Tue — 9 BB SELLs with C5 verdict applied

| setup_ts (UTC) | dir | v3_state | h1 last/forming hist | h1_dir | tiring | companion | exhaust | **C5** |
|---|---|---|---|---|---|---|---|---|
| 11-02T01:10 | SELL | NORMAL | +0.619 / +0.433 | UP | **True** | DOWN | DEV / SELLING | **ADMIT** (tiring) |
| 11-02T07:35 | SELL | NORMAL | −0.181 / −0.038 | DOWN | True | UP | NO_EXH | **ADMIT** (with-H1) |
| 11-02T12:35 | SELL | RANGE | +0.263 / +0.355 | UP | False | None | NO_EXH | **BLOCK** |
| 11-02T13:35 | SELL | RANGE | +0.260 / +0.332 | UP | False | UP | DEV / BUYING | **BLOCK** |
| 11-03T00:20 | SELL | RANGE | −0.600 / −0.623 | DOWN | False | DOWN | NO_EXH | ADMIT (with-H1) |
| 11-03T03:35 | SELL | RANGE | −0.962 / −1.042 | DOWN | False | DOWN | CONF / SELLING | ADMIT (with-H1) |
| 11-03T04:05 | SELL | RANGE | −1.029 / −1.044 | DOWN | False | None | DEV / BUYING | ADMIT (with-H1) |
| 11-03T05:35 | SELL | RANGE | −1.085 / −1.035 | DOWN | True | UP | NO_EXH | ADMIT (with-H1) |
| 11-03T08:05 | SELL | RANGE | −1.006 / −0.857 | DOWN | True | UP | DEV / BUYING | ADMIT (with-H1) |

**C5 blocks 2 of 9 Mon+Tue BB SELLs.** The two counter-H1 Mon afternoon fires (12:35 + 13:35) where H1 MACD was positive and growing. **No Tue overnight fires blocked by C5** — all Tue SELLs were WITH-H1 because H1 MACD had already flipped negative by Mon close.

### 2.2 Fri 10-30 reference — C5 adverse impact

Twelve BB TAKEN entries that Friday. C5 verdict:

| setup | dir | H1 hist | tiring | C5 verdict |
|---|---|---|---|---|
| 10-29T22:15 | SELL | +4.027 / +4.246 | False | **BLOCK** |
| 10-29T23:40 | BUY | +4.244 / +4.285 | False | ADMIT |
| 10-30T01:15 | SELL | +4.481 / +4.734 | False | **BLOCK** |
| **10-30T03:10 SELL** | **+4.650 / +4.752** | **False** | **BLOCK (CSV +9.4p winner forfeited)** |
| 10-30T05:20 | BUY | +4.526 / +4.334 | True | ADMIT |
| 10-30T06:25 | SELL | +4.438 / +4.428 | True | ADMIT |
| 10-30T07:25 | SELL | +4.358 / +4.436 | False | **BLOCK** |
| 10-30T11:20 | BUY | +4.750 / +4.757 | False | ADMIT |
| 10-30T16:10 | SELL | +3.289 / +3.078 | True | ADMIT |
| 10-30T17:55 | BUY | +3.009 / +2.583 | True | ADMIT |
| 10-30T20:10 | SELL | +2.018 / +1.784 | True | ADMIT |
| 10-30T20:40 | BUY | +2.018 / +1.718 | True | ADMIT |

**C5 blocks 4 of 12 Fri BB TAKEN entries.** The 10-30T03:10 SELL is a **known +9.4p winner** that C5 would forfeit. The three other blocks (10-29T22:15, 10-30T01:15, 10-30T07:25) have UNKNOWN close P&L in the CSV (the P1 EMAPB-close defect also affects some bb-bounce rows). On raw-signal evidence **C5 is net-negative on the 3-day sample**: 2 losses prevented vs ≥1 known winner forfeited plus 3 unknowns.

---

## 3. Q2 — Real H161 candidate reconstruction + C1-C4 recovery

Source: `/opt/tradingbot/logs/trend_v3.jsonl` and `logs/bounce_engine.jsonl` for the window.

### 3.1 Event counts

| day | trend_v3 `nms_direction_blocked` | trend_v3 fires | bounce_engine ARMED | ARMED→OPENED | ARMED→ORDER_REFUSED | ARMED→INVALIDATED |
|---|---:|---:|---:|---:|---:|---:|
| 10-30 Fri | 142 | 3 SHORT (13:40-13:50) | 14 | 2 | 9 | 3 |
| 11-02 Mon | 156 | 0 | 7 (all LONG, all 14:25-19:00) | 0 | 6 | 1 |
| 11-03 Tue (→08:30Z) | 20 | 0 | 0 | 0 | 0 | 0 |

### 3.2 Classifier re-run on 156 Mon blocks under C1+C2+C3+C4

Mon C1-C4 EMERGING bars (verbatim from `scripts/replay_nms_v3.py`):
- **EMERGING_UP** 08:40, 08:45, 08:50, 08:55, 09:00, 09:05, 09:10, 09:15, 09:20 (9 bars; up=4, dn=0..1)
- **EMERGING_DOWN** 10:40, 10:45, 10:50, 10:55, 11:00, 11:15, 11:20 (7 bars; up=−2..−3, dn=4)

Under `permit_trend` matrix (`nms_session_trend_direction.py:290-294`): EMERGING_UP admits BUY; EMERGING_DOWN admits SELL. **16 of 156 Mon blocks (10.3%) convert to directional admissions.**

### 3.3 Downstream feasibility of the 16 Mon admissions

**(a) ADX_MIN=25, ER_MIN=0.5, ER_BARS=20** (`gbpusd_trend_v3.py:88-90`) check — recomputed from 5m archive:
- EMERGING_UP 08:40–09:20: ADX14 48.8–61.7 (all pass); ER20 0.482–0.641 (**6 of 9 bars have ER ≥ 0.5**).
- EMERGING_DOWN 10:40–11:20: ADX14 38–40 (all pass); ER20 0.162–0.863 (**5 of 7 bars have ER ≥ 0.5**).

**(b) bounce_engine ARMED overlap** — Mon 08:00–11:30 had only `EXHAUSTION_CANDIDATE × 3` + `EXHAUSTION_DEMONSTRATED × 1`. **Zero ARMED, zero PULLBACK_HOLD** before 14:25:14. All 7 Mon ARMs were LONG — EMERGING_DOWN SELLs would never be served by the pullback path.

**Conclusion:** C1-C4 opens narrow EMERGING windows that the direct trend_v3 strategies can enter via `permit_trend` (ADX+ER feasible on ≥11 of 16 bars), but the **bounce_engine pullback path recovers nothing on Mon** because no ARMED candidate overlaps the EMERGING windows. Realistic recovery on Mon: **≤2 fires** (1 BUY 08:40-09:20 + 1 SELL 10:40-11:00). Tue recovers 0.

### 3.4 Fri reference — would C1-C4 have changed Fri's result?

Fri baseline already produced STRONG_UP 40 / EMERGING_DOWN 5 / STRONG_DOWN 35. Corrected: STRONG_UP 40 / EMERGING_DOWN 3 / STRONG_DOWN 37. **C1-C4 recovers nothing additional on Fri** — the 5 autobot H161 fires that happened would still happen; no new fires added or removed.

---

## 4. Q3 — C5 H1 MACD source audit

### 4.1 Writer path (operational now)

- **Writer:** `/opt/tradingbot/h1_macd_tiring_writer.py:153`
- **Caller:** `/opt/tradingbot/autobot.py:3874-3882` — hardcoded `if sym == "GBPUSD"` + gated by `DIRECTION_FROM_NMS_SESSION_TREND`.
- **Cadence:** every 5m close for GBPUSD only.
- **Hardcoded `_SYMBOL = "GBPUSD"`** at `h1_macd_tiring_writer.py:52`. The writer cannot write for any other pair.
- **Freshness guard:** `_max_age_s()` = `DIRECTION_SNAPSHOT_MAX_AGE_S` = **900s (15 min default)**. Not overridden in either `.env`.
- **Live state at report time (2026-11-03 08:35 UTC):** file at `/opt/tradingbot/cache/h1_macd_tiring_GBPUSD.json` is 254 bytes, last_hist=−1.003, forming_hist=−0.981, **tiring=True**. Writer is operational.

### 4.2 Fail-open matrix (verbatim from C5 code at `open_sb_now.py:384-397`)

| Condition | `_read_h1_direction` | Admission under C5=1 |
|---|---|---|
| File missing | `("UNKNOWN", False, "no_snapshot")` | **ADMIT** |
| Invalid `ts_utc` | `("UNKNOWN", False, "no_ts_utc")` | **ADMIT** |
| Age > 900s | `("UNKNOWN", False, "stale:…")` | **ADMIT** |
| `last_completed_hist` null | `("UNKNOWN", True, "no_last_hist")` | **ADMIT** |
| `last_completed_hist = 0.0` | `("UNKNOWN", True, "last_hist=0")` | **ADMIT** |
| last_hist > 0, side SELL, tiring=False | `("UP", True, ...)` | **BLOCK** |
| last_hist < 0, side BUY, tiring=False | `("DOWN", True, ...)` | **BLOCK** |
| With-direction (BUY+UP or SELL+DOWN) | — | ADMIT |
| tiring=True (any) | — | ADMIT |

**5 of 7 UNKNOWN/stale cells silently admit.** The reason string on admit is `allow:unified_bounce_range:RANGE` — **identical to the gate-off path**. There is no `allow:bb_c5_fail_open:...` sentinel. An operator who flips `BB_BOUNCE_C5_H1_GATE=1` without verifying the writer is live would believe the gate is enforced; the gate instead admits 100% of what would have been blocked, with no telemetry trail.

### 4.3 Should UNKNOWN permit counter-trend?

Current posture (fail-open): preserves mean-reversion on true consolidation H1 (last_hist≈0). Loses safety under writer failure.

**Recommendation:** split the policy:
- `h1_fresh=True, h1_dir=UNKNOWN` (fresh snapshot, histogram at zero — true consolidation): **ADMIT** with explicit `allow:bb_c5_consolidation:h1_zero` telemetry.
- `h1_fresh=False` (missing/stale snapshot): **BLOCK counter-direction** with `block:bb_c5_h1_snapshot_unfresh:...` reason.

This separates "I know H1 is noise" from "I don't know what H1 is." Operator rollback by disabling the writer would then block ALL counter-direction fires instead of silently reverting — operator-visible on day one.

### 4.4 C5 is **not deployment-ready as-is**

Verdict: the C5 code requires the fail-closed-on-unfresh rework before deployment. Marked DO NOT DEPLOY.

---

## 5. Q4 — C4 consumer propagation audit

### 5.1 Producer-only field — zero consumers

- `m5_regime` is populated by `nms_v3_classifier.advance()` return dict (C4 worktree, lines 362-399).
- **Grep across production trees:**
  - `/opt/tradingbot/*.py`: **0 hits** for `m5_regime`
  - `/opt/bb_bounce/*.py`: **0 hits**
  - `/opt/ema_pullback/*.py`: **0 hits**
  - `central_execution_gate.py`, `nms_directional_authority.py`: **0 hits**

### 5.2 Snapshot write path drops the field

- `session_trend.py:1820-1850` reads only `v3_result["state"]` from `advance()`.
- `_write_snapshot` (`session_trend.py:2075-2125`) writes only `v3_state` string.
- **Live proof:** `/opt/tradingbot/cache/session_trend_GBPUSD.json` keys include `v3_state` but NOT `m5_regime` (verified by `jq keys_unsorted` output at report time).

### 5.3 Reclassification

**C4 as currently implemented is DIAGNOSTIC-ONLY.** It has an initializer (classifier populates the field) but no driver (snapshot write path drops it) and zero consumers (gates read only `v3_state`). By the wiring rule in `CLAUDE.md`, C4 is **unwired**.

**Do not claim C4 provides "unified multi-dimensional directional authority" in deployment comms.** As wired, C4 is a research/replay refinement that reaches the ablation runner and unit tests only.

**To make C4 operational would require:** (1) a copier into `_write_snapshot`, (2) a consumer in at least one admission gate. Neither exists.

---

## 6. Q5 — Metric reconciliation (45–50% vs 10%)

Both numbers were in the previous report. They describe **different populations and different reductions.** Reconciling honestly:

### 6.1 The 45% number — candle-proxy ablation
From `scripts/ablation_runner.py` across 25 historical sessions × candle-level BB-pierce signals:

| config | BB signals (proxy) | base admits | C5 admits | reduction |
|---|---:|---:|---:|---:|
| baseline NMS | 157 | 126 | 61 | **52%** |
| c1c2c3c4 NMS | 157 | 114 | 59 | 48% |

The 45–50% reduction is **C5 vs baseline Phase 2B on the candle-level proxy**, aggregated across 25 sessions.

**Why the proxy overstates:** the candle-level pierce+rejection proxy produces 157 signals; the real tick-level BB_BOUNCE strategy produces fewer (9 in Mon+Tue window from real logs vs 3 from proxy). The proxy fires on more bars than real BB_BOUNCE, and C5 blocks counter-H1 at every one of those extra bars — inflating the reduction fraction.

### 6.2 The 10% number — admit-pathway shift
The deployment plan said "~10% drop in BB_BOUNCE free-pass admits concentrated on counter-H1-tiring cases." This referred to the baseline Phase 2B admit column going 126 → 114 across configurations (ablation table). That is **NOT a C5-attributable reduction** — it is a side-effect of C1-C4 pushing more bars from RANGE to EMERGING (which routes to with-trend / exhaustion paths, not free-pass). C5 itself blocks ~45–50% of what reaches the free-pass path.

### 6.3 The real-signal number — 22-33%
From §2 (real logs):
- Mon+Tue BB SELLs: 2 of 9 blocked (22%)
- Fri BB TAKEN: 4 of 12 blocked (33%)
- Combined 3-day window: 6 of 21 (29%)

### 6.4 Corrected characterization

**C5's blocking effect: ~22-33% of real BB_BOUNCE fires** on this 3-day window (not 45-50%). The deployment plan's "10%" number was describing a different metric and should not have been in the same sentence as C5's effect. The 45-50% from the ablation was accurate for the proxy but does not transfer to real-signal rates.

The previous report conflated three distinct reductions. For the record:
- **C1-C4 effect on baseline-gate admits:** 126 → 114 (−9.5%, from more EMERGING classifications)
- **C5 effect on free-pass admits (proxy):** 126 → 61 (−52%)
- **C5 effect on free-pass admits (real signals, Mon+Tue+Fri):** 21 → 15 (−29%)

---

## 7. Q6 — State persistence + restart behaviour

Full test battery in `/tmp/part1_part2_output.txt` + `/tmp/part3_output.txt`. **27 PASS / 0 FAIL.** Summary:

| Area | Tests | Result |
|---|---|---|
| Flag-toggle mid-session (back-compat setdefault) | 6 | PASS |
| State blob JSON round-trip (byte-identical final row) | 3 | PASS |
| Flags-off byte-parity with production | 3 | PASS |
| `has_excursion` / `max_disp_*` persist across serialize | 5 | PASS |
| C6 day-rollover: C6=1 nulls `v3_state` | 4 | PASS |
| C6=0 reproduces the production bug (v3_state carries over) | 1 | PASS |
| Prior-session summary in `last_session_v3` | 1 | PASS |
| Rollover detection on first Tue bar | 1 | PASS |
| Lazy-init via `fresh_state` is clean | 1 | PASS |
| Weekend handling (Fri → Mon trigger) | 1 | PASS by inspection |
| Snapshot round-trip + cross-version matrix | 1 | PASS |

**Key finding:** flags live in the state blob and are consulted per-bar via `_env_flags()` → `fresh_state()`. State blobs persisted before C1-C6 landed deserialize cleanly thanks to the setdefault shims at `nms_v3_classifier.py:248-252`.

Weekend handling via `session_trend.py:1382` (`if s.session_date != bar_date_iso:`) fires on any UTC-date change — covers midnight Mon-Tue AND Fri-close → Mon-open. **Not run end-to-end** through the real `on_bar_close` (would require live NMS director + snapshot writer); replaced by replica-code execution of the C6 block.

---

## 8. Q7 — Config reload mechanism

### 8.1 Reload-behaviour matrix

| Flag | .env file | Code read-timing | Needs service restart? |
|---|---|---|---|
| `NMS_V3_C1_CORRECTED_RECLAIM` | `/opt/tradingbot/.env` | `_env_flags()` during `fresh_state` (once per session) | **YES — systemd + state frozen** |
| `NMS_V3_C2_DIRECTIONAL_PENALTY` | `/opt/tradingbot/.env` | same | **YES** |
| `NMS_V3_C3_REBALANCED_SCORING` | `/opt/tradingbot/.env` | same (plus module-level `C3_EXCURSION_PIPS` etc constants frozen at import) | **YES** — even re-tuning the threshold constants requires restart |
| `NMS_V3_C4_MULTI_DIM` | `/opt/tradingbot/.env` | same | **YES** |
| `NMS_V3_C6_DAYROLL_RESET` | `/opt/tradingbot/.env` | per-call `os.environ.get` at rollover | **YES** — code is live-read capable but systemd prevents env delivery |
| `BB_BOUNCE_C5_H1_GATE` | `/opt/bb_bounce/.env` | per-call `_env_bool` inside admit | **YES — bb-bounce service** |
| `DIRECTION_FROM_NMS_SESSION_TREND` (writer master) | `/opt/tradingbot/.env` | per-call `_env_bool` inside writer | **YES — autobot** |

### 8.2 Why

- **systemd `EnvironmentFile=` is only re-read at unit start.** Verified from `systemctl show autobot.service -p EnvironmentFiles -p FragmentPath`. Editing `.env` does not reach the running process.
- **State persistence:** C1-C4 flags are read via `_env_flags()` once per `fresh_state()`, then frozen on the state blob for the duration of that session. Flag flip takes effect only at next `fresh_state` seed (daily rollover) or a process restart.
- **Module-level constants:** C3's threshold constants (`C3_EXCURSION_PIPS` etc) read `os.environ.get` **at module import time** (nms_v3_classifier.py:99-110). Even if hot-reload were wired, re-tuning these needs a process restart.
- **No sentinel-file mechanism exists for any NMS flag.** The only sentinel is `IG_DEALING_RULES_INVALIDATE_SENTINEL` (unrelated).

### 8.3 Deployment implication

The previous report said "Rollback = set flag to 0 + reload (no restart required if hot-reload is wired)." **This is wrong.** Every rollback = edit `.env` → `systemctl restart <service>`.

---

## 9. Q8 — Integration tests across services

Full battery in `/tmp/part3_output.txt`. Summary:

| Test | Result | Note |
|---|---|---|
| 3A — Snapshot schema unchanged (no `m5_regime` key written) | PASS | Confirms C4 is diagnostic-only |
| 3B — bb_bounce doesn't read `m5_regime` | PASS | Preserves cross-version compat |
| 3C — ema_pullback doesn't read `m5_regime` | PASS | — |
| 3D — No `schema_version` bump needed | PASS | `session_trend.v2` unchanged |
| 3E — Old-style snapshot loads under new consumer; new-style loads under old consumer | PASS | Cross-version matrix verified |
| 3F.1 — `permit_trend` reads only `v3_state` string | PASS | — |
| 3F.4 — C5 uses separate `h1_macd_tiring` cache (schema-independent) | PASS | — |

### 9.1 Stale-data handling

- `nms_v3_direction_gate._h1_bias` snapshot staleness check: `NMS_V3_H1_MAX_AGE_S=3900s` (data-time) — unchanged, continues to protect.
- `nms_directional_authority._session_authority` snapshot staleness: `NMS_UNIFIED_AUTHORITY_MAX_AGE_SECONDS=360s` — unchanged.
- `_read_tiring` / `_read_h1_direction` (C5): `_max_age_s()=900s`.
- **C5 freshness check is weakest at 15 min** — if the writer stalls for 15 min + 1 bar, the gate silently admits. Addressed in §4.

### 9.2 Strategy-specific permissions

- `autobot gbpusd_trend_v3.permit_trend`: reads only `v3_state` enum. No change required.
- `bb_bounce open_sb_now._read_v3_state`: reads only `v3_state` enum. No change required.
- `ema_pullback nms_gate.check`: reads only `v3_state` enum. No change required.

**All three consumers are backward-compatible with the corrected classifier** because the legacy `state` field is preserved verbatim.

---

## 10. Q9 — Root filesystem at 99% capacity

### 10.1 Current state

```
/dev/vda1       25G   24G   343M  99% /
/dev/sda       100G   25G    70G  26% /mnt/volume_lon1_1778405456698
```

### 10.2 Space inventory under `/opt/tradingbot`

| Path | Size |
|---|---|
| `/opt/tradingbot/data` | 266M |
| `/opt/tradingbot/logs` | 311M (top: `v3_events.jsonl` 53M + `v3_events.jsonl-20261103` 49M) |
| `/opt/tradingbot/reports-public` | 213M |
| `/opt/tradingbot/_agent_restore` | 9.0M |
| `/opt/tradingbot/env-history` | 3.4M (63 files) |
| scratch `does-not-exist-*.tmp` | 184K (46 files) |
| systemd journal | 597.7M |

Hot-path services (`autobot`, `bb-bounce`, `trades-api`, `ema-pullback`) all have cwd/log paths under `/opt/tradingbot/*` and `/var/log/journal/*`. Moving the data/logs tree requires updating multiple systemd unit `WorkingDirectory=` / `Environment=` paths (verified via `grep -rln /opt/tradingbot/{logs,data} /etc/systemd/system/` which found 5+ unit files).

### 10.3 Safe-remediation options (require operator approval; **nothing executed by this review**)

**Option A — Journal vacuum (recovers up to 400M, lowest risk):**
```
sudo journalctl --vacuum-size=200M
```
Drops older archived journal entries. Live-write stream continues. Zero service impact. Historical troubleshooting beyond the vacuum window becomes impossible, but this is already partial (prior memory noted the 2026-10-29 → 2026-11-02 15:40 window is gone).

**Option B — Compress rotated logs (recovers ~40M):**
```
# Already-rotated files that are NOT currently open:
gzip /opt/tradingbot/logs/v3_events.jsonl-20261103
gzip /opt/tradingbot/logs/level_interaction_observer_v6.jsonl-20261103
gzip /opt/tradingbot/logs/sweep_journal_2026-03-19.csv
gzip /opt/tradingbot/logs/sweep_journal_2026-03-20.csv
```
Idempotent; `.gz` versions already exist for older rotated days. Low risk.

**Option C — Scratch cleanup (recovers 184K, negligible):**
```
# 46 'does-not-exist-*.tmp' zero-content scratch files
rm /opt/tradingbot/does-not-exist-*.tmp
```

**Option D — Archive `data/eod_review` to /mnt (recovers 137M):**
```
# Requires understanding whether any live service reads this directory.
# Preliminary check via grep for the path returned no obvious consumer.
# Recommended: move to /mnt/volume_lon1_1778405456698/eod_review_archive/
# and symlink back if a consumer exists.
```
**Needs operator confirmation that eod_review is historical/archive and not a live write path.**

**Option E — Prune `reports-public` artefacts (potential 100M+):**
```
# reports-public has 42 subdirs. Operator should audit which are
# obsolete and remove via `git rm`. Current repo is already pushed
# to GitHub so local prune is lossless from an archival standpoint.
```

**Option F — Move the whole `logs/` tree to `/mnt` with bind-mount:**
```
# Technically possible via mount move; risky mid-flight.
# Operator decision.
```

### 10.4 Pre-deployment recommendation

Before any flag-flip-triggered service restart, apply **Options A + B + C** (minimum ~440M recovered, no service downtime, no consumer path change). This brings `/` to ~85% utilisation, with headroom for log-flush during restart. Options D-F are longer-term.

### 10.5 Hard constraints

- Memory `project_disk_remediation_20261029` notes that logrotate 3.19.0 requires `su root syslog` for /var/log 0775 root:syslog. The weekly→daily rotation + maxsize 100M + rotate 7 was already applied Oct 29.
- Memory also notes mount-dep drop-ins were STAGED not installed per safeguard §9. Still staged.
- Journal cap already 500M per `/etc/systemd/journald.conf.d/50-autobot-rotation.conf`. Hitting 597.7M is a hot-topic for the live operator per `project_disk_remediation_20261029`.

---

## 11. Per-correction PASS/FAIL + recommendation

| Correction | Baseline parity | Monday effect | Fri effect | C5 fail-open? | Consumer wired? | Deploy decision |
|---|---|---|---|---|---|---|
| **C6** | PASS | None (diagnostic) | None | n/a | n/a (session_trend internal) | **DEPLOY FIRST — Phase A.** Low-risk reporting fix. |
| **C1** | PASS (5/5 spot checks reproduce) | Admits 16 EMERGING bars (10.3% of blocks) | No change | n/a | `permit_trend` (`v3_state`) — PASS | **DEPLOY — Phase B.** After C6. Needs restart. |
| **C2** | PASS | Required for C1's EMERGING_DOWN (10:40-11:20) | No change | n/a | PASS | **DEPLOY WITH C1 — Phase B** |
| **C3** | PASS | Caps negatives at −6 per family (incremental over C1+C2) | No change | n/a | PASS | **DEPLOY WITH C1+C2 — Phase C.** NB: module-level C3 threshold constants require restart to re-tune. |
| **C4** | PASS (field inert at consumer level) | Classifier emits new regime labels | None | n/a | **NOT WIRED — zero consumers** | **RECLASSIFY as DIAGNOSTIC-ONLY — Phase E.** Enable only for diagnostic logging; do not claim admission authority. |
| **C5** | PASS at code level | Blocks 2 of 9 Mon+Tue BB SELLs (22%) | Blocks 4 of 12 Fri TAKEN including **1 known +9.4p winner** | **YES — silently** | n/a | **DO NOT DEPLOY as-is.** Rework fail-open posture (§4.3) + obtain operator sign-off on Fri impact. |
| **C7** (operator decision) | n/a | 5 of 8 Mon+Tue overnight BB blocked | n/a | n/a | n/a | Separate operator decision. |

### 11.1 Recommended deployment order (if operator approves rework)

1. **Phase 0 — Disk remediation.** Apply §10.3 Options A + B + C before any service restart.
2. **Phase A — C6 only.** Set `NMS_V3_C6_DAYROLL_RESET=1` in `/opt/tradingbot/.env`. `systemctl restart autobot.service`. Verify at next UTC midnight: `cache/session_trend_state.json` shows `v3_state.session_date == session_date` (not stale). One trading week observation.
3. **Phase B — C1 + C2.** Set both `NMS_V3_C1_CORRECTED_RECLAIM=1` and `NMS_V3_C2_DIRECTIONAL_PENALTY=1`. `systemctl restart autobot.service`. Monitor state distribution for 5 trading days — compare EMERGING bar count vs the historical 25-session baseline.
4. **Phase C — C3.** Set `NMS_V3_C3_REBALANCED_SCORING=1`. Restart. Low incremental risk; bounds negative stacking.
5. **Phase D — C5 (ONLY AFTER REWORK).** Modify `open_sb_now.py:_phase2b_block_order` to block counter-direction when `h1_fresh=False`. Rebuild bb_bounce service. Set `BB_BOUNCE_C5_H1_GATE=1`. Monitor for Fri-adverse impact.
6. **Phase E — C4 as diagnostic.** Set `NMS_V3_C4_MULTI_DIM=1` with documentation stating "diagnostic-only; emits `m5_regime` field; no admission effect".
7. **Phase F — C7 operator decision.** Separately evaluate `TRADING_HOURS_SHADOW_MODE=0`.

Each phase independently rolls back by editing `.env` → `systemctl restart <service>`.

---

## 12. Blocking issues before any deployment

1. **Disk at 99% full.** Apply at minimum §10.3 Options A+B+C before any service restart. 343M free is marginal.
2. **C5 fail-open posture.** Rework the gate to fail-closed on `h1_fresh=False`; add telemetry sentinel. §4.3.
3. **C4 non-propagation.** Reclassify as diagnostic-only in all documentation. Do not claim unified multi-dim authority. §5.3.
4. **C5 Fri adverse impact.** Operator must sign off on forfeiting the 10-30T03:10 +9.4p SELL (plus 3 unknown-outcome blocks) in exchange for blocking 2 Mon losses.
5. **Hot-reload claim.** Correct the deployment plan to reflect `systemctl restart` requirement for every flag.
6. **Metric claim consistency.** Communicate the three-way reduction (C1-C4 effect vs C5 proxy effect vs C5 real-signal effect) distinctly. §6.

---

## 13. Nothing changed

Final verification at report write:

```
$ sha256sum /opt/tradingbot/nms_v3_classifier.py /opt/tradingbot/session_trend.py /opt/bb_bounce/open_sb_now.py
4007d21c3cdfb8912b516958bedf8cfb905457981e3dd3a5f5946f0a80f828a8  /opt/tradingbot/nms_v3_classifier.py
c943a65cbb0e92c78f2bc3d22cebfb3196cea715dbef22b72c6b27c8844aa753  /opt/tradingbot/session_trend.py
b8fb82c1f3beb4ba9d05f2dc202292e5c800bde6f8b0cc7e78a5068ce629e6ce  /opt/bb_bounce/open_sb_now.py

$ sha256sum /opt/tradingbot/.env /opt/bb_bounce/.env
414055dad41525d8830100be982edde2416f88b2b0eb822cbcf4eaa5dde893a4  /opt/tradingbot/.env
84a149fd3deadac907467111401aab492111d943e3030b13ba24a209d039109b  /opt/bb_bounce/.env
```

All production hashes match the baseline captured at start of implementation (2026-11-03). No service restarted. No live flag flipped. No broker action. Awaiting operator review of §11 recommendations + §12 blocking issues.
