# Phase 13 C10 — final acceptance ruling

Generated: 2026-09-24T13:35Z

Predecessor: `reports-public/phase13/phase13_c9_deploy_verify_20260924.md` (commit `a3d1234`).

Boundaries observed: no manual grader invocation (all evidence from natural timer fires captured in `journalctl`) · no AutoBot restart · no `.env` change · no broker calls · no trading state writes · no manufactured trades / candidates / observations / tier advancements / outcomes · no `git stash` / no `checkout` / no `reset` / no destructive git.

---

## §0 — What was already closed by prior C10 sub-passes (this session preserves them)

Every finding below was recorded before the natural 13:15/13:30 grader fires and is left untouched.

| Sub-pass | Status entering C10-J | Evidence artefact |
|---|---|---|
| C10-A/B/C/H corpus investigation | PASS | prior turn |
| C10-D tier-evidence contract | PASS | prior turn |
| C10-E economic-close provenance | PASS | prior turn (grader.py:278 uses `_s.authoritative_close_ts`) |
| C10-F/I veto ingredients + authority invariants | PASS | prior turn |
| EOD production invocation | PASS | prior turn |
| C7/C8 TM_OBSERVATION prospective evidence | PASS | `reports-public/phase13/phase13_c9_deploy_verify_20260924.md` §7 (7 rows, DIAAAAYJBC7C9AW, C8 context fields complete on last 4) |

C10-J is the closing sub-pass: **prove that the two scheduled graders, running on their real timer cadence with today's live corpus, produce the artefacts the pipeline commits to**. That proof is where C10 fails today — see §1–§4.

---

## §1 — 13:15 UTC scheduled fire (main grader) — first natural fire this session

Captured directly from `journalctl -u phase13-grader.service --since "13:14"`:

```
Sep 24 13:15:03 systemd[1]: Starting Phase 13 outcome grader …
Sep 24 13:15:04 python3[1219981]: {
Sep 24 13:15:04 python3[1219981]:   "n_rows_scanned": 32,
Sep 24 13:15:04 python3[1219981]:   "n_outcomes_written": 0,
Sep 24 13:15:04 python3[1219981]:   "n_outcomes_skipped_already_graded": 0,
Sep 24 13:15:04 python3[1219981]:   "policy_version": "policy:a3d1234:9c8abce0e3d4:05259211e774",
Sep 24 13:15:04 python3[1219981]:   "grader_candle_archive_last_ts": "2026-09-24T13:10:00+00:00"
Sep 24 13:15:04 python3[1219981]: }
Sep 24 13:15:04 systemd[1]: Finished Phase 13 outcome grader …
```

Tier-advancement peer (same wall time):

```
Sep 24 13:15:03 systemd[1]: Starting Phase 13 tier-advancement grader …
Sep 24 13:15:04 python3[1219982]: rows_read=0 rows_graded=0 rows_appended=0
Sep 24 13:15:04 systemd[1]: Finished Phase 13 tier-advancement grader …
```

| Signal | Value |
|---|---|
| GRADER_TIMER_FIRED_1315 | **YES** — `LastTriggerUSec = 2026-09-24 13:15:03 UTC` on the timer, matching journal |
| GRADER_EXIT_STATUS_1315 | success (Result=success, ExecMainStatus=0) |
| GRADER_ROWS_WRITTEN_1315 | **0** |
| GRADER_ARCHIVE_LAST_1315 | 2026-09-24T13:10:00Z (advanced from 12:40Z at 12:45 fire) |
| TIER_GRADER_TIMER_FIRED_1315 | **YES** — same trigger microsecond |
| TIER_GRADER_ROWS_APPENDED_1315 | **0** (`rows_read=0`) |

Prior turn had predicted (`phase13_c9_deploy_verify_20260924.md` §8) that 13:00 or 13:15 would produce the first TM_OUTCOME row once the archive advanced past `12:40Z`. The archive advanced to `13:10:00Z`, well past the earliest observation's 30-min horizon end (`12:45:07Z`), yet **zero** outcomes were written. Something else is blocking.

---

## §2 — 13:30 UTC scheduled fire — corroboration on the next tick

The scheduled 13:30 fire happened while diagnosis was in progress. It is captured passively and used only to check the pattern.

```
Sep 24 13:30:00 systemd[1]: Starting Phase 13 outcome grader …
Sep 24 13:30:00 python3[1221410]:   "n_rows_scanned": 34,
Sep 24 13:30:00 python3[1221410]:   "n_outcomes_written": 0,
Sep 24 13:30:00 python3[1221410]:   "policy_version": "policy:a3d1234:9c8abce0e3d4:05259211e774",
Sep 24 13:30:00 python3[1221410]:   "grader_candle_archive_last_ts": "2026-09-24T13:25:00+00:00"
Sep 24 13:30:00 systemd[1]: Finished Phase 13 outcome grader …
```

Row scan count grows monotonically (23 → 28 → 32 → 34) — new corpus rows are being read; the cursor watermark is not stale — but `n_outcomes_written` stays at 0 across four consecutive scheduled fires (12:45, 13:00, 13:15, 13:30).

**Idempotency evidence (bonus, not the acceptance signal):** the cursor at `cache/tm_corpus_cursor.json` contains `{"graded_tuples": [], "last_run_ts": "2026-09-24T13:15:04.615055+00:00", "policy_version": "policy:a3d1234:9c8abce0e3d4:05259211e774"}`. The grader is idempotent — each tick re-scans the same rows without ever admitting one to `graded_tuples` — which is itself a symptom of the underlying defect.

---

## §3 — Diagnosis: `TM_CORPUS_WRITER_PRODUCTION` is not present in the grader service env

### Eligibility side of the argument

At 13:30's archive_last (`13:25:00Z`), the corpus contains **18 complete TM_OBSERVATION rows** (rows with the full `bar_close`/`deal_id`/`pair`/`direction`/`observation_ts_utc` set that `grade_one` needs). Of these, **8 rows have ≥1 horizon whose end_ts ≤ archive_last**, producing **10 eligible (row, horizon) tuples**. Concretely:

```
record_id=207cad7a  obs_ts=12:15:07.477  horizon=30m  end=12:45:07  <= 13:25:00  ✓
record_id=1f634f84  obs_ts=12:20:01.079  horizon=30m  end=12:50:01  <= 13:25:00  ✓
record_id=3c75126a  obs_ts=12:25:00.957  horizon=30m  end=12:55:00  <= 13:25:00  ✓
record_id=56c2ea03  obs_ts=12:30:01.082  horizon=30m  end=13:00:01  <= 13:25:00  ✓
record_id=e13567b3  obs_ts=12:35:00.923  horizon=30m  end=13:05:00  <= 13:25:00  ✓
record_id=2383660c  obs_ts=12:40:01.052  horizon=30m  end=13:10:01  <= 13:25:00  ✓
record_id=87552867  obs_ts=12:45:00.922  horizon=30m  end=13:15:00  <= 13:25:00  ✓
record_id=acb18983  obs_ts=12:50:00.816  horizon=30m  end=13:20:00  <= 13:25:00  ✓
record_id=207cad7a  obs_ts=12:15:07.477  horizon=60m  end=13:15:07  <= 13:25:00  ✓
record_id=1f634f84  obs_ts=12:20:01.079  horizon=60m  end=13:20:01  <= 13:25:00  ✓
```

The horizon-eligibility guard at `grader.py:302` (`if archive_last is None or end_ts > archive_last: continue`) does not exclude any of these — for row `207cad7a`, `end_ts=12:45:07 ≤ archive_last=13:25:00`. Yet zero outcomes were appended. Something inside the write path is dropping them silently.

### Silent-drop root cause

The grader systemd unit as installed (byte-identical to `deploy/systemd/phase13-grader.service`):

```
Environment=PYTHONUNBUFFERED=1
```

is the **only** `Environment=` directive. Verified:

```
$ systemctl show phase13-grader.service -p Environment
Environment=PYTHONUNBUFFERED=1
$ systemctl show phase13-grader.service -p EnvironmentFiles
EnvironmentFiles=
```

There is no `EnvironmentFile=/opt/tradingbot/.env`, and systemd services do not inherit interactive shell env. The grader oneshot therefore runs with **no `TM_CORPUS_WRITER_PRODUCTION`** set.

`tm_corpus_writer.py:77–79`:

```python
def is_enabled() -> bool:
    """D4: production activation is explicit. Default OFF."""
    return _env_bool("TM_CORPUS_WRITER_PRODUCTION", "0")
```

`tm_corpus_writer.py:182–183` (inside `record_outcome`):

```python
if not is_enabled():
    return None
```

`grader.py:427–430` interprets the `None` return as "not written":

```python
rid = _cw.record_outcome(out)
if rid is not None:
    n_outcomes_written += 1
    already_graded.add(tuple_key)
```

Consequence: **every horizon-eligible row is composed into a valid TM_OUTCOME dict inside `grade_one`, passed to `record_outcome`, dropped fail-silently by `is_enabled()`, never counted toward `n_outcomes_written`, and never added to `already_graded`**. `n_outcomes_written = 0` is not diagnosing "nothing to grade" — it is masking a silent-drop wiring defect.

### Isolated confirmation (no grader invocation)

Executed with the exact env of the systemd oneshot to prove the flag path in isolation (writer module only; grader never called):

```
$ /opt/tradingbot/venv/bin/python3 -c "
import os
os.environ.clear()
os.environ['PYTHONUNBUFFERED'] = '1'
os.environ['PATH'] = '/usr/bin:/bin'
import sys; sys.path.insert(0, '/opt/tradingbot')
import tm_corpus_writer as _cw
print('TM_CORPUS_WRITER_PRODUCTION in env:', 'TM_CORPUS_WRITER_PRODUCTION' in os.environ)
print('is_enabled():', _cw.is_enabled())
"
TM_CORPUS_WRITER_PRODUCTION in env: False
is_enabled(): False
```

`is_enabled()=False` under the systemd oneshot env → `record_outcome` returns None → 0 TM_OUTCOME writes possible under the current unit file.

The tier-advancement grader has the same defect: its service file also has only `Environment=PYTHONUNBUFFERED=1`, and `record_tier_advancement_outcome` (`tm_corpus_writer.py:978–986`) is gated by the same `is_enabled()`.

### Why the C9 report's zero-outcomes explanation was wrong (in retrospect, but only in retrospect)

C9 (`phase13_c9_deploy_verify_20260924.md` §4) attributed the zero at 12:45:01 to the `end_ts > archive_last` strict-greater guard. That IS the reason at 12:45:01 (earliest obs_ts=12:36:23Z has 30m end=13:06:23Z, and archive_last was 12:40:00Z). It is **not** the reason at 13:00, 13:15, or 13:30: the archive has walked far past the earliest 30m end_ts, so the guard admits rows now; the writer's `is_enabled()` gate is what still drops them. C9's local fact was right; its "next tick will pick these up" projection was wrong because the underlying wiring blocks the write regardless of eligibility.

### Boundary of the defect

- **Only writes are affected.** All READS (`tm_corpus.jsonl`, `signal_log.jsonl`, candle archive, cursor) succeed — that is why `n_rows_scanned` and `grader_candle_archive_last_ts` populate correctly.
- **AutoBot is unaffected.** AutoBot (`autobot.service`) loads `.env` explicitly and has `TM_CORPUS_WRITER_PRODUCTION=1` in-process. `tm_corpus.jsonl` observation growth this session (14 TM_OBSERVATION rows for two live GBPUSD trades) proves the writer is enabled inside AutoBot.
- **No trading behaviour or authority change.** Grader outputs are Authority=NONE by schema; the defect withholds analytical rows only — it does not touch execution, gates, or `.env`.

---

## §4 — Tier-advancement input side (still valid input-availability wait, plus the same defect if input lands)

- `logs/tier_advancement_corpus.jsonl` is absent (only the quarantined `.testleak.20260923T201000Z` variant exists from an older test).
- Today's ratchet events (`grep 2026-09-24 logs/tiered_ratchet.jsonl`) are exclusively `pos_key="PARITY|1"` replay events — no live position ratcheted a tier on 2026-09-24.
- The Seam-C tier-advancement observation emitter (`tiered_ratchet.py:690`, `_tacw.record_tier_advancement_observation(_obs_row)`) is wired but has had no natural trigger this session.
- **If** the seam fires under AutoBot's env, the observation lands. The subsequent tier-grader tick would then be subject to the same `TM_CORPUS_WRITER_PRODUCTION` gate on the outcome writer and would drop the outcome silently — the fix in §5 covers both graders.

The tier grader's zero rows this session is a legitimate no-input state, unlike the main grader's zero writes (which is a silent-drop defect on real input).

---

## §5 — Fix staged (repo-only; INSTALLATION requires operator sudo)

Two service files updated in `deploy/systemd/`. The installed copies at `/etc/systemd/system/` are **untouched** — those require operator sudo and a `daemon-reload`.

### Diff (repo-side)

`deploy/systemd/phase13-grader.service`:

```
+Environment=TM_CORPUS_WRITER_PRODUCTION=1
```

`deploy/systemd/phase13-tier-advancement-grader.service`:

```
+Environment=TM_CORPUS_WRITER_PRODUCTION=1
```

Comment blocks rewritten in both to state the true wiring dependency (grader-side `record_*` calls are gated by this flag; `.env` is NOT inherited by intent, but the one flag output actually depends on IS wired in-band).

### What is deliberately NOT changed

- `tm_corpus_writer.py` — the `is_enabled()` gate is intentional at the writer level and applies uniformly to AutoBot's writes and grader's writes; loosening it would be a wider policy change.
- The timer cadence — 15-min OnCalendar retained.
- The `Nice=15 / IOSchedulingClass=idle / Restart=no` isolation posture — kept.
- Any `.env` load — full-file inheritance is still refused; only the one relevant flag is set in-band.

### Operator remediation steps (must run as root)

```
sudo install -m 0644 /opt/tradingbot/deploy/systemd/phase13-grader.service /etc/systemd/system/phase13-grader.service
sudo install -m 0644 /opt/tradingbot/deploy/systemd/phase13-tier-advancement-grader.service /etc/systemd/system/phase13-tier-advancement-grader.service
sudo systemctl daemon-reload
# Optional: force a fresh fire now instead of waiting for the next :00/:15/:30/:45 tick.
# Not required — the next natural tick will pick them up.
```

After the next fire, `logs/tm_outcomes.jsonl` must appear with rows for every eligible `(join_record_id, horizon)` pair from `tm_corpus.jsonl`, and `cache/tm_corpus_cursor.json`'s `graded_tuples` must grow accordingly.

---

## §6 — Trading isolation still intact throughout

| Field | Value |
|---|---|
| autobot.service state | active (running) |
| autobot MainPID | **1217431 UNCHANGED** — same PID as C9 verification (`ActiveEnterTimestamp=2026-09-24T12:36:21 UTC`) |
| AUTOBOT_PID_UNCHANGED_BY_GRADERS | YES |
| AUTOBOT_PID_UNCHANGED_BY_DIAGNOSIS | YES — no restart, no signal, no `pkill`, no `systemctl start/stop/restart` (per feedback memory `no_pkill_no_service_control`) |
| BROKER_API_CALLS_FROM_DIAGNOSIS | 0 |
| TRADING_STATE_WRITES_FROM_DIAGNOSIS | 0 |
| .env TOUCHED | NO |
| TM_AUTHORITY_CHANGED | NO |
| TRADING_BEHAVIOUR_CHANGED | NO |
| GRADER_MANUALLY_INVOKED | NO — all four grader fires captured here (12:45, 13:00, 13:15, 13:30) are natural timer fires under systemd |

---

## §7 — Original final block (pre-remediation, preserved verbatim for the audit trail)

| Field | Value |
|---|---|
| **C10_TIER_A_B_C_H_CORPUS_INVESTIGATION** | **PASS** (prior turn — preserved) |
| **C10_TIER_D_EVIDENCE_CONTRACT** | **PASS** (prior turn — preserved) |
| **C10_TIER_E_ECONOMIC_CLOSE_PROVENANCE** | **PASS** (prior turn — preserved) |
| **C10_TIER_F_I_VETO_AUTHORITY_INVARIANTS** | **PASS** (prior turn — preserved) |
| **C10_EOD_PRODUCTION_INVOCATION** | **PASS** (prior turn — preserved) |
| **C10_TM_OBSERVATION_PROSPECTIVE_PROOF** | **PASS** (preserved from C9 §7) |
| **C10_TM_OUTCOME_PROSPECTIVE_PROOF_1315** | **FAIL** — 0 outcomes despite ≥5 eligible tuples |
| **C10_TM_OUTCOME_PROSPECTIVE_PROOF_1330** | **FAIL** — 0 outcomes despite 10 eligible tuples |
| **C10_TIER_OUTCOME_PROSPECTIVE_PROOF** | **NOT_APPLICABLE_THIS_SESSION** (no live tier event; writer gate would drop if it fired) |
| **C10_ROOT_CAUSE_IDENTIFIED** | **YES** — writer flag absent from grader systemd env |
| **C10_FIX_STAGED_IN_REPO** | **YES** — commit `c748006` |
| **C10_FIX_INSTALLED_TO_SYSTEMD** | **NO** (as of the 13:35Z snapshot; operator install pending) |
| **C10_ACCEPTANCE_RULING** | **REJECT (until installed fix produces first TM_OUTCOME row)** |

---

## §8 — Post-remediation natural-fire proof (added 2026-09-24T14:02Z)

**Operator action recap:** approved fix commit `c748006`, installed both updated unit files to `/etc/systemd/system/`, ran `systemctl daemon-reload`. No AutoBot restart. No manual grader invocation. No manufactured data.

Post-install parity check (repo ↔ installed, both graders):

```
$ diff /opt/tradingbot/deploy/systemd/phase13-grader.service /etc/systemd/system/phase13-grader.service
(empty — byte-identical)
$ diff /opt/tradingbot/deploy/systemd/phase13-tier-advancement-grader.service /etc/systemd/system/phase13-tier-advancement-grader.service
(empty — byte-identical)
$ systemctl show phase13-grader.service -p Environment
Environment=PYTHONUNBUFFERED=1 TM_CORPUS_WRITER_PRODUCTION=1
$ systemctl show phase13-tier-advancement-grader.service -p Environment
Environment=PYTHONUNBUFFERED=1 TM_CORPUS_WRITER_PRODUCTION=1
```

### 13:45 UTC — first natural fire under the corrected env (main grader)

Journal (verbatim):

```
Sep 24 13:45:05 systemd[1]: Starting Phase 13 outcome grader …
Sep 24 13:45:06 python3[1223144]: {
Sep 24 13:45:06 python3[1223144]:   "n_rows_scanned": 40,
Sep 24 13:45:06 python3[1223144]:   "n_outcomes_written": 25,
Sep 24 13:45:06 python3[1223144]:   "n_outcomes_skipped_already_graded": 0,
Sep 24 13:45:06 python3[1223144]:   "policy_version": "policy:c748006:9c8abce0e3d4:05259211e774",
Sep 24 13:45:06 python3[1223144]:   "grader_candle_archive_last_ts": "2026-09-24T13:40:00+00:00"
Sep 24 13:45:06 python3[1223144]: }
Sep 24 13:45:06 systemd[1]: phase13-grader.service: Deactivated successfully.
Sep 24 13:45:06 systemd[1]: Finished Phase 13 outcome grader …
```

| Signal | Value |
|---|---|
| GRADER_TIMER_FIRE_TS | **2026-09-24T13:45:05Z** (natural) |
| GRADER_EXIT_STATUS | **success** (Result=success, ExecMainStatus=0) |
| ELIGIBLE_TUPLES_BEFORE | **25** — 10 × 30m + 5 × 60m + 10 × actual_close (composed by `grade_one` from 20 complete TM_OBSERVATION rows, 10 of which qualify for at least one fixed horizon at archive_last=13:40:00Z, plus 10 actual_close outcomes derivable via the signal_log join because the source trade already closed at 13:00:03Z with reason=QM_BAND_CLOSE_INSIDE) |
| TM_OUTCOMES_WRITTEN | **25** (matches ELIGIBLE_TUPLES_BEFORE exactly) |
| TM_OUTCOMES_FILE_EXISTS | **YES** — `logs/tm_outcomes.jsonl` (26 094 bytes, 25 lines) |
| CURSOR_GRADED_TUPLES_AFTER | **25** — `cache/tm_corpus_cursor.json.graded_tuples` (all 25 listed by `<record_id>|<horizon>`) |

### First genuine outcome — full field-by-field proof

Extracted verbatim from row 1 of `logs/tm_outcomes.jsonl`:

| Field | Value |
|---|---|
| SOURCE_OBSERVATION_ID (`join_record_id`) | `207cad7a88f2469c9af357fc4a79c18d` |
| TRADE_ID (`deal_id`) | `DIAAAAYJBC7C9AW` |
| DECISION_TS (`decision_ts_utc`) | `2026-09-24T12:15:07.477271+00:00` |
| HORIZON | `30m` |
| OUTCOME_GRADED_TS (`graded_ts_utc`) | `2026-09-24T13:45:05.841189+00:00` |
| MFE_PIPS (`cf_if_held_max_pnl_pips` — horizon-window counterfactual) | **6.0** (whole-trade `actual_mfe_pips_whole_trade` = 12.35, from signal_log join) |
| MAE_PIPS (`cf_if_held_max_adverse_pips` — horizon-window counterfactual) | **5.5** (whole-trade `actual_mae_pips_whole_trade` = 5.35, from signal_log join) |
| PROVENANCE | `grader_version=phase13.grader.v1.0` · `grader_candle_archive_last_ts=2026-09-24T13:40:00+00:00` · `cf_flip_policy_version=policy:c748006:9c8abce0e3d4:05259211e774` · `decision_ref_price=13220.55` (bar_close of source TM_OBSERVATION at bar_ts=12:10) · `effective_end_ts_utc=2026-09-24T12:45:07.477271+00:00` (=decision_ts + 30m; horizon closed before trade close at 13:00:03Z, so held to horizon end) · `actual_close_ts_utc=2026-09-24T13:00:03+00:00` · `actual_close_reason=QM_BAND_CLOSE_INSIDE` · `actual_pnl_pips_whole_trade=10.8` |
| OUTCOME_TS > DECISION_TS | **YES** — 2026-09-24T13:45:05Z > 2026-09-24T12:15:07Z (Δ = 1h 29m 58s; strictly forward-causal) |

Byte-clean row (from `head -1 logs/tm_outcomes.jsonl`, pretty-printed):

```json
{
  "join_record_id": "207cad7a88f2469c9af357fc4a79c18d",
  "deal_id": "DIAAAAYJBC7C9AW",
  "pair": "GBPUSD", "direction": "BUY", "strategy_family": null,
  "horizon": "30m",
  "grader_version": "phase13.grader.v1.0",
  "grader_candle_archive_last_ts": "2026-09-24T13:40:00+00:00",
  "decision_ref_price": 13220.55,
  "decision_ts_utc": "2026-09-24T12:15:07.477271+00:00",
  "effective_end_ts_utc": "2026-09-24T12:45:07.477271+00:00",
  "actual_close_ts_utc": "2026-09-24T13:00:03+00:00",
  "actual_close_price": 13231.2,
  "actual_close_reason": "QM_BAND_CLOSE_INSIDE",
  "actual_mfe_pips_whole_trade": 12.35,
  "actual_mae_pips_whole_trade": 5.35,
  "actual_pnl_pips_whole_trade": 10.8,
  "cf_if_held_max_pnl_pips": 6.0,
  "cf_if_held_max_adverse_pips": 5.5,
  "cf_if_held_final_pnl_pips": 3.0,
  "cf_if_exited_now_pnl_pips": null,
  "cf_flip_admissible_now": null,
  "cf_flip_policy_version": "policy:c748006:9c8abce0e3d4:05259211e774",
  "record_type": "TM_OUTCOME",
  "schema_version": "phase13.tm_outcome.v1.0",
  "record_id": "6c0e00b1ce09406d9bd1bb8e1f21594a",
  "graded_ts_utc": "2026-09-24T13:45:05.841189+00:00"
}
```

### 14:00 UTC — subsequent natural fire (idempotency proof)

Journal (verbatim):

```
Sep 24 14:00:05 systemd[1]: Starting Phase 13 outcome grader …
Sep 24 14:00:06 python3[1223933]: {
Sep 24 14:00:06 python3[1223933]:   "n_rows_scanned": 48,
Sep 24 14:00:06 python3[1223933]:   "n_outcomes_written": 6,
Sep 24 14:00:06 python3[1223933]:   "n_outcomes_skipped_already_graded": 25,
Sep 24 14:00:06 python3[1223933]:   "policy_version": "policy:c748006:9c8abce0e3d4:05259211e774",
Sep 24 14:00:06 python3[1223933]:   "grader_candle_archive_last_ts": "2026-09-24T13:55:00+00:00"
Sep 24 14:00:06 python3[1223933]: }
Sep 24 14:00:06 systemd[1]: Finished Phase 13 outcome grader …
```

| Signal | Value |
|---|---|
| n_outcomes_skipped_already_graded | **25** — every previously-written tuple correctly refused by the cursor watermark |
| n_outcomes_written | **6** (new: 3 × 60m horizons that just crossed archive_last for older obs; 3 × 30m for newer bar_ts=13:05–13:20 observations) |
| DUPLICATE_OUTCOMES_CREATED | **0** — post-14:00 file has 31 rows and 31 distinct `(join_record_id, horizon)` tuples |
| IMMUTABLE_EXISTING_OUTCOMES_CHANGED | **0** — SHA256 of `logs/tm_outcomes.jsonl` first 25 lines after 14:00 fire matches the post-13:45 baseline `1c4fa9cbd86b96d9b37c8b107f49e32018bdfd4aa9add47602ba1a6346b53d2d` byte-for-byte (append-only confirmed) |
| CURSOR_GRADED_TUPLES_AFTER (14:00) | **31** |

Six new outcomes from the 14:00 fire (bar_ts and decision_ts fully preserved from the source TM_OBSERVATION):

| record_id (first 12) | horizon | decision_ts_utc |
|---|---|---|
| 2383660ce520 | 60m | 2026-09-24T12:40:01.051953+00:00 |
| 8755286783a7 | 60m | 2026-09-24T12:45:00.922435+00:00 |
| acb1898312ba | 60m | 2026-09-24T12:50:00.815919+00:00 |
| 869d9ff8f981 | 30m | 2026-09-24T13:10:00.790471+00:00 |
| a1249f23e1fe | 30m | 2026-09-24T13:15:02.279714+00:00 |
| 3152da86feb2 | 30m | 2026-09-24T13:20:00.685833+00:00 |

### Tier grader — corrected env installed, no natural input this session

- `systemctl show phase13-tier-advancement-grader.service -p Environment` returns `Environment=PYTHONUNBUFFERED=1 TM_CORPUS_WRITER_PRODUCTION=1` (fix in place).
- 13:45 and 14:00 tier-grader fires: `rows_read=0 rows_graded=0 rows_appended=0` — legitimate no-input state; `logs/tier_advancement_corpus.jsonl` is absent; today's only ratchet events are `pos_key=PARITY|1` replay events.
- `TIER_ADVANCEMENT_PROSPECTIVE_PROOF = PENDING_NATURAL_EVENT`. Per the preserved C10-D contract ruling, awaiting a natural ratchet advance on a live position is an input-availability wait, **not a defect and not a Phase-13 blocker**. The wired chain is intact end-to-end: `tiered_ratchet.py:690` emitter → `record_tier_advancement_observation` writer (now enabled in-grader-env too by extension) → tier grader appends to `tier_advancement_outcomes.jsonl` on maturity.

### AutoBot isolation still intact

| Field | Value |
|---|---|
| autobot MainPID | **1217431 UNCHANGED** — identical to the pre-C10 snapshot; ActiveEnterTimestamp `2026-09-24T12:36:21 UTC` |
| .env TOUCHED | NO |
| Broker calls from graders | 0 |
| Trading state writes from graders | 0 |
| Manual grader invocations | 0 (all six proof fires — 12:45, 13:00, 13:15, 13:30, 13:45, 14:00 — are natural timer fires under systemd) |

---

## §9 — Revised C10 acceptance ruling (supersedes §7)

| Field | Value |
|---|---|
| **C10_WRITER_GATE_DEFECT_FIXED** | **YES** — commit `c748006` installed at `/etc/systemd/system/`; both graders now run with `TM_CORPUS_WRITER_PRODUCTION=1` in their oneshot env |
| **TM_OUTCOME_PROSPECTIVE_PROOF** | **PASS** — 25 outcomes written on 13:45 natural fire; first row byte-verified with all provenance and causal-forward checks |
| **TM_OUTCOME_IDEMPOTENCY_PROOF** | **PASS** — 14:00 fire skipped exactly the 25 previously-graded tuples, appended 6 new ones, and left the pre-14:00 25-row prefix byte-identical (SHA256 match) |
| **TIER_WRITER_ENV_FIXED** | **YES** — verified via `systemctl show ... -p Environment` |
| **TIER_ADVANCEMENT_PROSPECTIVE_PROOF** | **PENDING_NATURAL_EVENT** — no live ratchet advance today; preserved C10-D contract ruling classifies this as input-availability, not a Phase-13 blocker |
| **PHASE13_TM_OBSERVATION** | **PASS** — preserved from C9 §7 |
| **PHASE13_TM_ACTION** | **PASS** — preserved from prior C10 sub-passes (16 TM_ACTION rows present in `tm_corpus.jsonl`; schema-validated; forbidden-key guard exercised by unit tests) |
| **PHASE13_TM_OUTCOME** | **PASS** — 31 rows in `logs/tm_outcomes.jsonl`; all schema-valid; all `graded_ts_utc > decision_ts_utc`; all provenance fields populated |
| **PHASE13_TIER_TELEMETRY** | **PENDING** — env corrected, seam wired, awaiting first live ratchet advance to prove end-to-end (per preserved C10-D contract this is not a blocker) |
| **PHASE13_CAUSALITY** | **PASS** — `_bars_between` uses `start_ts < b.ts <= end_ts` (grader.py:117-119) so no bar at or before decision_ts contaminates the horizon; all 31 outcomes have `graded_ts_utc > decision_ts_utc` and `effective_end_ts_utc > decision_ts_utc`; observation-side forbidden-key guard blocks future fields on TM_OBSERVATION/TM_ACTION rows |
| **PHASE13_PROVENANCE** | **PASS** — every outcome carries `grader_version`, `grader_candle_archive_last_ts`, and `cf_flip_policy_version` (git-SHA-stamped `policy:c748006:...`); source TM_OBSERVATION `record_id` is the `join_record_id`, giving 1-1 traceability back into `tm_corpus.jsonl` |
| **PHASE13_RESTART_PERSISTENCE** | **PASS** — cursor `cache/tm_corpus_cursor.json` survives grader oneshot exit; 14:00 fire restored 25 tuples from cursor and correctly skipped them; TM_OBSERVATION emitter resumed across C7→C8 restart (7 rows spanning bar_ts 12:10→12:40 for `DIAAAAYJBC7C9AW`, per C9 §7) |
| **PHASE13_GRADER_SCHEDULING** | **PASS** — 15-min OnCalendar cadence hits every scheduled slot (six fires observed today at 12:45/13:00/13:15/13:30/13:45/14:00); `Result=success` on every fire; timer-driven only (no persistent grader service) |
| **PHASE13_AUTHORITY_NONE** | **PASS** — schema stamps `record_type=TM_OUTCOME` with no gate/executor readers (grep-enforced by `test_no_production_reader_of_grader_output_in_gate_or_executor`, preserved from C7); grader has no broker imports (grep-enforced by `test_no_broker_rest_calls_in_grader`); 0 trading state writes across all six fires |
| **PHASE13_DOWNSTREAM_READINESS** | **PASS** — preserved EOD production invocation ruling from prior C10 sub-pass |
| **PHASE13_COMPLETE** | **YES** |
| **BLOCKERS_IF_NO** | *(n/a — no blockers)* |
| **READY_TO_CLOSE_MASTER_PHASE13** | **YES** |
| **NEXT_MASTER_ROADMAP_POSITION** | **Phase 14 — Tabular ML** (docs/master_spec_20260911.md §3763-3767: "Train setup-quality and relevant continuation/bounce models. Shadow only.") — TM_OUTCOME corpus is now producing horizon-graded rows, which is Phase 14's training input |
| **AUTHORITY_CHANGED** | NO |
| **TRADING_BEHAVIOUR_CHANGED** | NO |
| **AUTOBOT_TOUCHED** | NO — MainPID 1217431 unchanged; no restart; no `.env` write |

STOP after revised C10 acceptance ruling.
