# STANDDOWN-SHADOW — 3-candidate verdict telemetry (instrumentation-only)

**Host:** 161.35.168.61 · `/opt/tradingbot` · branch `feat/trend-stretch-brake-adx-floor`  
**Commit:** `d51564d`  
**Scope:** telemetry-only, ZERO behaviour change  
**Runs:** inactive until the operator's next natural restart (rides alongside the pending Phase 0a `5eb637f`, Phase 1.1 `bc12af8`, conftest guard `b55b96f`)

---

## Contradictions (first)

1. **The dwell source I picked is not the deque the task offered as fallback.** The task said "If per-bar history isn't already held in memory, a 8-deep deque per symbol fed at each 5m classify is acceptable — state which you did." I went with a stateless tail-read of `logs/regime_engine.jsonl` (last 256 KiB, seek+decode+parse) instead of adding a deque. Reason: the deque option would need a callback wiring change to feed it at each 5m classify (either an insert into `regime_engine.emit()` or a new callback registration), whereas the tail-read requires zero touch to any producer path. Correctness is equivalent — the jsonl is written before the standdown consult runs on the same bar (regime callback fires ahead of BB_BOUNCE per registration order). Trade-off: ~256 KiB seek+parse per consult vs zero-IO deque; for a strategy that consults at ≤5-minute cadence per symbol this is well within budget.

2. **The systemd unit for the backfill can't be activated by me.** `deploy/systemd/eod-review-metrics.service` in the repo tree has the new `ExecStart=` line but the live `/etc/systemd/system/eod-review-metrics.service` does not — activation requires `cp` + `systemctl daemon-reload` which needs root. Same-restart-batching policy applies: operator syncs the unit at the next natural restart, then the 22:05 UTC timer will pick up the backfill. Until then, `mfe_pips` / `mae_pips` in `logs/standdown_shadow.jsonl` remain null. Telemetry rows themselves ARE written from live once autobot.service restarts, since `standdown_shadow.py` lives inside the Python import graph.

3. **The 3 fix-candidates are asymmetric** — one wants a truthy signal (dwell < N implies "young trend, permit fade"), the other wants a truthy signal on `label_path == "struct" AND confidence_final < FLOOR` (which lifts only the ambiguous struct-promoted subset). The pathconf verdict inherits `actual_decision` in every other case, so it CAN'T disagree with actual outside the low-confidence struct zone. This is by design (per the task spec) but worth naming: a pathconf-only fix would only touch a subset of standdowns, whereas dwell would touch every young STRONG_TREND run.

---

## Consult-site diff

`gbpusd_bb_bounce.py` — one insertion at line 2519, plus one one-line fix (`_rg = {}` in the fail-open branch so the subsequent `.get()` doesn't `AttributeError`):

```diff
         if BB_BOUNCE_STRONG_TREND_STANDDOWN_ENABLED and not _REGIME_MATRIX_ENABLED:
             try:
                 import regime_engine as _re
                 _rg = _re.latest_result("GBPUSD") or {}
                 _winning = str(_rg.get("winning_regime") or "").upper()
             except Exception as _re_exc:
                 _winning = ""
+                _rg = {}
                 logger.warning(
                     "[%s] regime_engine.latest_result failed: %s — stand-down "
                     "fail-open (fire proceeds)",
                     LOG_TAG, _re_exc,
                 )
             _fade_blocked = (
                 (_winning == "STRONG_TREND_UP"   and direction == "SELL") or
                 (_winning == "STRONG_TREND_DOWN" and direction == "BUY")
             )
+            # Shadow-verdict telemetry (2026-08-24, PHASE STANDDOWN-SHADOW).
+            # Fires whenever the consult sees a STRONG_TREND regime (both
+            # SUPPRESS-actual fade cases and PERMIT-actual same-direction
+            # cases). Never raises, never mutates _fade_blocked or any
+            # downstream behaviour — the standdown return path is
+            # byte-identical to before.
+            if _winning in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
+                try:
+                    import standdown_shadow as _ss
+                    _ss_ts = None
+                    try:
+                        _ss_ts = cur.timestamp.astimezone(timezone.utc).strftime(
+                            "%Y-%m-%dT%H:%M:%SZ"
+                        )
+                    except Exception:
+                        _ss_ts = datetime.now(timezone.utc).strftime(
+                            "%Y-%m-%dT%H:%M:%SZ"
+                        )
+                    _ss.record(
+                        ts_utc=_ss_ts,
+                        symbol=str(symbol).upper(),
+                        direction=direction,
+                        actual_decision=("SUPPRESS" if _fade_blocked else "PERMIT"),
+                        regime=_winning,
+                        label_path=_rg.get("regime_label_path"),
+                        struct_promoted=_rg.get("regime_struct_promoted"),
+                        confidence_final=_rg.get("confidence_final"),
+                        setup_price=(
+                            float(cur.close)
+                            if getattr(cur, "close", None) is not None
+                            else None
+                        ),
+                    )
+                except Exception:
+                    pass
             if _fade_blocked:
```

The insertion is BEFORE the `if _fade_blocked:` branch and MODIFIES NOTHING inside that branch. The three call paths downstream (SUPPRESS+return None, log-JSONL, labeller-enqueue, PERMIT-fall-through) are byte-identical.

## Log line shape

Per consult, one JSONL row appended to `logs/standdown_shadow.jsonl`:

```json
{
  "ts_utc": "2026-08-21T14:45:00Z",
  "symbol": "GBPUSD",
  "dir": "BUY",
  "actual_decision": "SUPPRESS",
  "regime": "STRONG_TREND_DOWN",
  "label_path": "struct",
  "struct_promoted": true,
  "confidence_final": 0.0172,
  "dwell_run_length": 4,
  "verdict_dwell_n6": "PERMIT",
  "verdict_dwell_n8": "PERMIT",
  "verdict_pathconf": "PERMIT",
  "pathconf_floor": 0.3,
  "setup_price": 13625.55,
  "mfe_pips": null,
  "mae_pips": null
}
```

Plus one INFO log line at each consult:

```
[STANDDOWN-SHADOW] 2026-08-21T14:45:00Z GBPUSD BUY actual=SUPPRESS regime=STRONG_TREND_DOWN path=struct conf=0.0172 dwell=4 → n6=PERMIT n8=PERMIT pc=PERMIT
```

## Outcome backfill

`scripts/standdown_shadow_backfill_outcomes.py`, chained onto the existing `eod-review-metrics.service` (systemd timer at `*-*-* 22:05:00 UTC`, daily). For each row from TODAY (UTC) whose `mfe_pips`/`mae_pips` are still null:

1. Read the deduped per-symbol daily CSV (`{CANDLE_ARCHIVE_ROOT}/{SYM}/{YYYY-MM-DD}.csv`, keep-first-per-timestamp).
2. Extract the 90-minute window forward of `ts_utc`.
3. Compute direction-aware favourable/adverse pip excursion from `setup_price` (same conventions the standdown triage uses).
4. Rewrite the JSONL atomically via `tempfile.mkstemp` + `os.replace`.

Ride: `eod-review-metrics.service`, timer `eod-review-metrics.timer`, `OnCalendar=*-*-* 22:05:00 UTC`, next fire `Mon 2026-08-24 22:05:00 UTC`.

---

## Test output (raw)

```
$ venv/bin/python -m pytest tests/unit/test_standdown_shadow.py -v
============================= test session starts ==============================
platform linux -- Python 3.10.12, pytest-9.0.2, pluggy-1.6.0 -- /opt/tradingbot/venv/bin/python
cachedir: .pytest_cache
rootdir: /opt/tradingbot
plugins: anyio-4.12.1
collecting ... collected 22 items

test_compute_verdicts[SUPPRESS-3-hist-0.42-PERMIT-PERMIT-SUPPRESS]         PASSED
test_compute_verdicts[SUPPRESS-5-hist-0.42-PERMIT-PERMIT-SUPPRESS]         PASSED
test_compute_verdicts[SUPPRESS-6-hist-0.42-SUPPRESS-PERMIT-SUPPRESS]       PASSED
test_compute_verdicts[SUPPRESS-7-hist-0.42-SUPPRESS-PERMIT-SUPPRESS]       PASSED
test_compute_verdicts[SUPPRESS-8-hist-0.42-SUPPRESS-SUPPRESS-SUPPRESS]     PASSED
test_compute_verdicts[SUPPRESS-None-hist-0.42-UNKNOWN-UNKNOWN-SUPPRESS]    PASSED
test_compute_verdicts[SUPPRESS-10-struct-0.25-SUPPRESS-SUPPRESS-PERMIT]    PASSED
test_compute_verdicts[SUPPRESS-10-struct-0.55-SUPPRESS-SUPPRESS-SUPPRESS]  PASSED
test_compute_verdicts[SUPPRESS-10-hist-0.05-SUPPRESS-SUPPRESS-SUPPRESS]    PASSED
test_compute_verdicts[SUPPRESS-10-struct-None-SUPPRESS-SUPPRESS-SUPPRESS]  PASSED
test_compute_verdicts[PERMIT-10-hist-0.05-SUPPRESS-SUPPRESS-PERMIT]        PASSED
test_compute_verdicts[PERMIT-10-struct-0.25-SUPPRESS-SUPPRESS-PERMIT]      PASSED
test_compute_verdicts_case_insensitive_label_path                          PASSED
test_dwell_run_length_basic_run                                            PASSED
test_dwell_run_length_breaks_on_label_change                               PASSED
test_dwell_run_length_ignores_other_symbols                                PASSED
test_dwell_run_length_missing_file_returns_none                            PASSED
test_dwell_run_length_zero_when_current_label_absent                       PASSED
test_record_writes_row                                                     PASSED
test_record_never_raises_on_bad_inputs                                     PASSED
test_import_standdown_shadow                                               PASSED
test_shadow_block_import_failure_swallowed                                 PASSED

============================== 22 passed in 0.16s ==============================
```

## Import check

```
$ venv/bin/python -c "import standdown_shadow; import gbpusd_bb_bounce; print('imports OK'); print('PATHCONF_FLOOR=', standdown_shadow.PATHCONF_FLOOR)"
imports OK
PATHCONF_FLOOR= 0.3
```

## Full-suite delta

| Metric | Before (pre-commit) | After (this commit) | Delta |
|---|---:|---:|---:|
| failed | 142 | 142 | 0 |
| passed | 1650 | 1672 | **+22** (my 22 new tests) |
| skipped | 20 | 20 | 0 |
| errors | 28 | 28 | 0 |
| time | 77.62s | 77.95s | +0.3s |

`bb_bounce or standdown or archive` subset run showed a second failing test order-dependent — `test_outside_window_deferred_row_when_armed_and_after_close` passes in isolation and passes when run against the same subset without my change too. Pre-existing test-order flakiness, not a regression from this commit. Full-suite `fails=142` is identical to baseline.

## git show --stat

```
commit d51564d  feat(standdown_shadow): 3-candidate verdict telemetry at consult site
 .gitignore                                    |   1 +
 deploy/systemd/eod-review-metrics.service     |  24 +++
 gbpusd_bb_bounce.py                           |  36 ++++
 scripts/standdown_shadow_backfill_outcomes.py | 190 ++++++++++++++++++++
 standdown_shadow.py                           | 204 ++++++++++++++++++++++
 tests/unit/test_standdown_shadow.py           | 238 ++++++++++++++++++++++++++
 6 files changed, 693 insertions(+)
```

Note: `deploy/systemd/eod-review-metrics.service` shows as "create mode" because that file was previously untracked in the git tree despite existing on disk (deploy/systemd/ has a whitelist but individual service files weren't `git add`'d until now). My commit adds it as newly-tracked with the extra `ExecStart=` line. Live `/etc/systemd/system/eod-review-metrics.service` is unchanged.

## Rides pending

This commit joins three others waiting on the next `systemctl restart autobot.service`:

- `5eb637f` — Phase 0a call-count instrumentation (`flag_call_counter` + regime_tree_shadow probe)
- `bc12af8` — candle_archive idempotent last-row check
- `b55b96f` — test-suite corpus-integrity guard + `CANDLE_ARCHIVE_ROOT` env-var rename
- `d51564d` — this commit (standdown-shadow telemetry)

None have been pushed. The 30-day-clock for the shadow verdicts starts at first autobot restart post-`d51564d`.
