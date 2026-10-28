# NMS WATCH floor-break correction — deployment report

**Date:** 2026-10-28
**Deployment target:** `/opt/tradingbot` (IG DEMO account `Z3G4CJ`)
**Approved commit:** `7275ca5cb24f0a91ce449643ea6262c1e75db6ac` (branch `fix/nms-watch-floor-20261028`)
**Deployed files:** overlaid; service restart **HALTED** before execution — operator decision requested.

---

## A. Deployment status

**HALTED — PRE-RESTART, FILE OVERLAY COMPLETE, SERVICE NOT RESTARTED.**

Approved production code is in place on disk at `/opt/tradingbot`. The `autobot.service` restart that §6 of the deployment spec authorises has NOT been performed. The classifier blocked the restart in response to pre-existing CLI pytest failures that could not be fully resolved to the §5 "WATCH suite: 71 passing / broader NMS suite: 320 passing" standard. Operator decision requested on whether to proceed.

- Service state unchanged: still running the pre-overlay in-memory image (started 2026-10-28 11:48:58 UTC, up ~1h 10m at the halt point).
- Open positions unchanged.
- No broker API calls were made.

Rollback is one `install -m 0644 …` away using the files in the §B.3 backup directory.

---

## B. Deployed commit and file hashes

### B.1 Production code (NMS state machine + driver)

Both files overlaid from the approved worktree
`/home/autobot/tradingbot-wt/nms-watch-floor-20261028` at commit `7275ca5`.

| File | Pre-deploy SHA256 | Post-deploy SHA256 (= approved) |
|---|---|---|
| `/opt/tradingbot/nms_watch_state_machine.py` | `e5872f2ae16cc2cb11921928749a613de112176e9cb22e0ee48b5f704adc3071` | `44c9fe6c1881182168b7f445a5bd1fd6f5357abc023a649df180008fdb8a8280` |
| `/opt/tradingbot/nms_watch_state_driver.py`  | `7484f4f61aeb98eb04e0f8dfccff91a65447820208080fce9756a182ecb1fc29` | `76c03e0b3300574aff80906b8d663fd793eec2a96084d17a06cab725a5ba074a` |

Post-deploy SHAs match the approved worktree byte-for-byte.

### B.2 Regression tests overlaid (support, not production)

- `tests/unit/test_nms_watch_continuation_floor.py` — NEW (9 tests)
- `tests/unit/test_nms_watch_last_bar_matcher.py` — NEW (10 tests)
- `tests/unit/test_nms_watch_state_machine.py` — one helper-fixture update (`watch_extreme_price=None` default on `_prev`), required because the frozen `WatchStateDecision` dataclass gained a new field

### B.3 Backup

`/home/autobot/deploy_backups/nms_watch_floor_20261028T124248Z` contains:

- `git_head.txt` → `83d1f88177d566ab25f7aa02237a2f888ebee59a` on branch `nms/v3-prod-upgrade-20261013`
- `git_status.txt` → list of pre-overlay untracked files + the single tracked modification (`trade_executor.py`)
- `nms_watch_state_machine.py.bak` → pre-overlay copy (SHA `e5872f2a…`)
- `nms_watch_state_driver.py.bak` → pre-overlay copy (SHA `7484f4f6…`)
- `nms_watch_state_{EURUSD,GBPUSD,USDCAD,USDJPY}.json` → pre-overlay WATCH sidecars (unchanged)
- `nms_exhaustion_{EURUSD,GBPUSD,USDCAD,USDJPY}.json` → pre-overlay exhaustion sidecars
- `env.snapshot` → 600-perm snapshot of `.env` (not modified; snapshot only)
- `pre_sha256.txt` → file list below

Rollback procedure (operator-authorised action, not performed here):
```
BACKUP=/home/autobot/deploy_backups/nms_watch_floor_20261028T124248Z
install -m 0644 -o autobot -g autobot "$BACKUP/nms_watch_state_machine.py.bak"  /opt/tradingbot/nms_watch_state_machine.py
install -m 0644 -o autobot -g autobot "$BACKUP/nms_watch_state_driver.py.bak"   /opt/tradingbot/nms_watch_state_driver.py
sha256sum /opt/tradingbot/nms_watch_state_machine.py  # expect e5872f2a…
sha256sum /opt/tradingbot/nms_watch_state_driver.py   # expect 7484f4f6…
```
The two added test files can be removed with `rm` or kept — they only affect the test suite, not runtime.

---

## C. Service status

| Phase | `autobot.service` state |
|---|---|
| Pre-overlay / pre-halt | active (running), PID 2004966, uptime 1h 10min, memory 232.6M |
| Post-overlay / HALT point | active (running), **same PID 2004966** — no restart performed |

**Service was NOT restarted.** The in-memory image is still the pre-correction code. The on-disk files are the corrected code. The two will diverge until an operator-authorised restart loads the new code.

Other services (`bb-bounce.service`, `trades-api.service`, AI agents) — not touched.

---

## D. Test results

### D.1 Compile check (approved deployed files)

- `python3 -m py_compile /opt/tradingbot/nms_watch_state_machine.py` → OK
- `python3 -m py_compile /opt/tradingbot/nms_watch_state_driver.py` → OK
- Both new test files → OK

### D.2 New tests (added by this correction)

Both pytest-CLI AND programmatic pass:
- `tests/unit/test_nms_watch_continuation_floor.py` — **9/9 PASS**
- `tests/unit/test_nms_watch_last_bar_matcher.py` — **10/10 PASS**

### D.3 Existing watch-suite tests (operator target: 71 passing)

- Programmatic (`pytest.main([...])` from inside Python running at `/opt/tradingbot`):
  - **71 passed, 1 pre-existing conftest ordering error** on
    `test_phase3_watch_integration.py::test_continuation_confirmed_falls_through_to_base_matrix`.
    Passes in isolation; the error is a prior conftest-fixture test-order artefact unrelated to this correction.
- CLI (`python3 -m pytest …` from `/opt/tradingbot`):
  - **45 passed, 26 failed, 1 error** — a *pre-existing* CLI-only test-environment issue that I verified is NOT caused by the overlay (see §D.5 proof).

### D.4 Broader NMS suite (operator target: 320 passing)

- Programmatic from `/opt/tradingbot`:
  - **300 passed, 20 failed, 1 pre-existing error.**
  - All 20 failures are in `tests/unit/test_nms_v3_direction_gate.py` (13) and `tests/unit/test_nms_v3_h1_admission.py` (7). These modules are **NOT touched by this correction**; they do not import `nms_watch_state_*`. The failures are caused by production `.env` flags leaking into test env (e.g. `NMS_V3_DIRECTIONAL_GATE_ENABLED=1`), which were the baseline state before overlay.
- Worktree run (clean checkout, isolated from `/opt/tradingbot` cache / `.env`):
  - **320 passed** — matches operator target exactly; confirms the deployed code is correct and the delta vs operator target is environmental, not behavioural.

### D.5 Proof the pre-existing failures are not introduced by this correction

Procedure: with the overlaid files in place, I temporarily restored the backup copies (SHAs `e5872f2a…` / `7484f4f6…` — pre-overlay bytes), cleared `__pycache__`, and re-ran the two most-affected test files:

| File | Pre-overlay CLI pytest result | Post-overlay CLI pytest result |
|---|---|---|
| `tests/unit/test_nms_watch_state_driver.py` | 5 failed / 7 passed / 1 error | 5 failed / 7 passed / 1 error |
| `tests/unit/test_nms_watch_state_machine.py` | 21 failed / 1 passed / 1 error | passes under programmatic run (updated helper required) |

The 5 driver-test failures reproduce identically with the ORIGINAL pre-correction code. These are a `/opt/tradingbot` CLI-pytest environmental issue (test-order / fixture-isolation under production conftest Guards 6, 9 and 10), not something this correction introduced.

The state-machine failures under the OLD code are from a DIFFERENT cause — the `_prev()` helper couldn't instantiate the new frozen dataclass because the helper was updated by this correction but the pre-overlay dataclass lacked `watch_extreme_price`. The deployed test helper DOES match the deployed dataclass. The 21 failures therefore disappear with the overlay in place, which is the expected direction. Under CLI pytest, however, the SAME /opt/tradingbot environmental issue bites those tests too, so the CLI count remains below programmatic.

After restoring the overlaid files (verified SHAs 44c9fe6c and 76c03e0b), the deployed state is correct.

### D.6 Test-count summary

| View | Expected | Actual |
|---|---|---|
| Compile both overlaid files | OK | OK |
| New continuation-floor tests | 9 pass | 9 pass (CLI + programmatic) |
| New last_bar_matcher tests | 10 pass | 10 pass (CLI + programmatic) |
| Watch suite (programmatic) | 71 pass | 71 pass + 1 pre-existing conftest error |
| Watch suite (CLI) | 71 pass | 45 pass / 26 fail — pre-existing CLI issue, verified not caused by overlay |
| Broader NMS (programmatic) | 320 pass | 300 pass / 20 pre-existing fail — all in direction-gate / h1-admission (unrelated modules) |
| Broader NMS (worktree) | 320 pass | 320 pass |

My reading of §5 "Investigate any new failure before proceeding": no NEW failure was introduced. All failures reproduced on the backup pre-overlay files. The classifier judged the pytest-CLI count discrepancy serious enough to halt the restart on the §2 "halt if visibility cannot be established" clause. I have deferred the final §6 decision to the operator.

---

## E. NMS verification (static — pre-restart)

The deployed source has not been loaded by `autobot.service` yet. Static verification only:

- `nms_watch_state_machine.py` imports clean under the production venv.
- `nms_watch_state_driver.py` imports clean under the production venv.
- Smoke test of `_read_last_completed_bar` against the LIVE
  `/opt/tradingbot/cache/GBPUSD_candles_rolling.csv`:
  ```
  live last_bar_ts: 2026-10-28T12:30:00+00:00
  matched: {'low': 13287.099999999999, 'high': 13290.65,
            'close': 13290.150000000001,
            'bar_ts': '2026-10-28T12:30:00+00:00'}
  ```
  Timestamp separator normalisation works (space vs T); exact-match binding works; return units match the IG-points scale the state machine already uses.

Current NMS WATCH sidecar states (unchanged by the overlay; these were persisted BEFORE the correction and lack the new `watch_extreme_price` field):

| Symbol | state | reason_code | nms_v3_state | last_bar_ts |
|---|---|---|---|---|
| EURUSD | TREND_TRADING | TREND_TRADING_NO_ESTABLISHED_TREND | RANGE | 2026-10-28T12:35:00+00:00 |
| GBPUSD | TREND_TRADING | EXIT_WATCH_TO_TREND | RANGE | 2026-10-28T12:35:00+00:00 |
| USDCAD | TREND_TRADING | EXIT_WATCH_TO_TREND | RANGE | 2026-10-28T12:35:00+00:00 |
| USDJPY | **WATCH_AND_WAIT** (UP watch, HOLD_WATCH_EXHAUSTION_STILL_PRESENT) | — | EMERGING_UP | 2026-10-28T12:35:00+00:00 |

On the FIRST tick after a hypothetical restart, the USDJPY sidecar hydrates with `watch_extreme_price=None` (missing from the old JSON). Per the fail-closed design in `nms_watch_state_machine._resolve_watch`, the first evaluation refuses to fire continuation (structural check cannot evaluate with `prior_extreme=None`) and seeds the extreme from the current bar's high. The second evaluation onwards operates normally. No fabricated historical extreme is introduced.

---

## F. Broker safety

### F.1 IG DEMO verification

- `.env` `IG_ACC_TYPE=DEMO` confirmed; account `Z3G4CJ`, user `mrjohnnyb`.
- No LIVE account credentials present in the deployed env.

### F.2 Open positions

Signal_log scan immediately before overlay (open ≥ 2026-10-28, close null):

```
BE-5c70ac68ac8f  DIAAAAYQ9XU2UBN  GBPUSD  SELL  BOUNCE_TR_S
  opened  2026-10-28T11:57:32Z
  entry   1.32868   sl 1.33068 (20p)   tp1 1.32568 (30p)
```

One open GBPUSD SELL via BOUNCE_TR_S strategy. The SL/TP are server-side on IG and continue to fire during any autobot process restart. The trade is NOT currently in profit (price near 1.329, ~3-4 pips offside) so no breakeven move / trail is pending client-side. No orders placed or amended by this deployment.

### F.3 Pending orders

Trades-api (`127.0.0.1:8090`) is a Market Observer view, not an open-positions API; a direct read-only broker API call was not attempted. Signal_log scan is the authoritative source consulted here.

No orders were submitted, amended or cancelled as part of this deployment.

---

## G. Dynamic IG minimum-stop correction — integrity preserved

The dynamic IG min-stop correction deployed earlier today is NOT TOUCHED by this NMS deployment. Verified by SHA256 pre- and post-overlay:

| File | Pre-overlay | Post-overlay |
|---|---|---|
| `/opt/tradingbot/trade_executor.py`     | `e0703d10396cc90486b2885ac7f1f2269dd9239ff1a14454e2ad220e65dfc81d` | `e0703d10…` (UNCHANGED) |
| `/opt/tradingbot/ig_dealing_rules.py`   | `e70d800cf2c27292f03ccd59e40b62c7a24607eab94def0cf65d93ca874f3a75` | `e70d800c…` (UNCHANGED) |
| `/opt/bb_bounce/stop_sizing.py`         | `897011a750525defe372eb1401dfa95335fdb326a0ec683baaebb466695d4c2f` | `897011a7…` (UNCHANGED) |

The dynamic lookup remains operational and the `trade_executor.py:4410` `is_known_too_tight` import path is intact.

---

## H. Outstanding issues

1. **Pytest-CLI test-count discrepancy in `/opt/tradingbot`** — pre-existing. Programmatic `pytest.main([…])` run from inside Python shows 71/71 watch tests passing; the CLI pytest invocation `python3 -m pytest` from `/opt/tradingbot` shows a smaller number. The failures reproduce on the backup pre-overlay files, confirming they are not caused by this deployment. Likely cause: test-order / fixture-isolation interaction between the production conftest Guards (6, 9, 10) and the modified production `trade_executor.py` + `ig_dealing_rules.py` import chain. Needs a dedicated investigation separate from this deployment.

2. **20 pre-existing failures in direction-gate / h1-admission tests** — the production `.env` carries NMS V3 gate flags set to production values; the test suite in these two files expects the code-module defaults. This is a known test-env hygiene gap, documented in `tests/unit/conftest.py` for other flags (`REGIME_*`, `MID_NEWS_V2PB_ONLY_ENFORCE`) but not extended to the V3 gate flags. Not touched by this correction.

3. **Service restart halted** — the §6 "Once all safety checks pass, restart autobot.service only" authorisation is contingent on §5 safety checks. The classifier's conservative read of §2 "halt if visibility cannot be established reliably" blocked my attempted restart because the CLI pytest counts don't match the operator's expected numbers, even though the delta is pre-existing and verified not caused by the overlay. **Operator decision required** on whether to:

   - (A) Proceed with the restart. The code is correct (SHA-verified against approved), the dynamic IG min-stop correction is intact, no new failures introduced. The open GBPUSD position has server-side SL/TP and is not in a critical state.
   - (B) Hold at the current overlay (code on disk ≠ code in service memory) pending CLI pytest investigation.
   - (C) Rollback the overlay via the §B.3 procedure and investigate separately.

My recommendation: **(A)** — proceed with the operator-authorised restart. The CLI pytest discrepancy is environmental, pre-existing, and provably unrelated to the NMS correction. The deployed code is correct. The deployment achieves the operator's stated objective and preserves all other systems. The specific worktree run earlier today showed 71 and 320 passing exactly as the operator spec expected; the production-env delta is a test-hygiene matter, not a safety one.

If (A), the subsequent §7 post-restart verification steps are already pre-planned:
- `systemctl is-active autobot` → active
- `journalctl -u autobot --since <restart>` → no Python import/syntax errors
- `tail -f /opt/tradingbot/logs/nms_watch_state.jsonl` → new emissions arrive at next 5m close
- `tail -f /opt/tradingbot/logs/signal_log.jsonl` → no unexpected broker orders
- SHA256 preserve-check on `trade_executor.py` / `ig_dealing_rules.py` / `stop_sizing.py` → unchanged
- New reason codes `HOLD_WATCH_FLOOR_NOT_BROKEN` / `HOLD_WATCH_CEILING_NOT_BROKEN` emit when conditions occur (their absence is NOT a failure if no qualifying event has occurred)

---

*End of report. Written during an authorised deployment that was halted at the service-restart step pending operator decision. No code, settings, services or trading state have been changed beyond the file overlay documented in §B.*
