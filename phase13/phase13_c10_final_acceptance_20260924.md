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

## §7 — Mandatory final block

| Field | Value |
|---|---|
| **C10_TIER_A_B_C_H_CORPUS_INVESTIGATION** | **PASS** (prior turn — preserved) |
| **C10_TIER_D_EVIDENCE_CONTRACT** | **PASS** (prior turn — preserved) |
| **C10_TIER_E_ECONOMIC_CLOSE_PROVENANCE** | **PASS** (prior turn — preserved) |
| **C10_TIER_F_I_VETO_AUTHORITY_INVARIANTS** | **PASS** (prior turn — preserved) |
| **C10_EOD_PRODUCTION_INVOCATION** | **PASS** (prior turn — preserved) |
| **C10_TM_OBSERVATION_PROSPECTIVE_PROOF** | **PASS** (preserved from C9 §7 — 7 TM_OBSERVATION rows on DIAAAAYJBC7C9AW with full C8 context on the last 4) |
| **C10_TM_OUTCOME_PROSPECTIVE_PROOF_1315** | **FAIL** — grader fired at 13:15:03Z, scanned 32 rows, wrote 0 outcomes despite archive_last=13:10:00Z admitting ≥5 horizon-eligible tuples |
| **C10_TM_OUTCOME_PROSPECTIVE_PROOF_1330** | **FAIL** — grader fired at 13:30:00Z, scanned 34 rows, wrote 0 outcomes despite archive_last=13:25:00Z admitting 10 horizon-eligible tuples |
| **C10_TIER_OUTCOME_PROSPECTIVE_PROOF** | **NOT_APPLICABLE_THIS_SESSION** — no live tier advancement fired today (`tier_advancement_corpus.jsonl` absent; only `PARITY` replay events in `tiered_ratchet.jsonl`); the same writer gate would drop this too if it fired |
| **C10_ROOT_CAUSE_IDENTIFIED** | **YES** — `TM_CORPUS_WRITER_PRODUCTION` absent from the grader oneshot's systemd env → `tm_corpus_writer.is_enabled()=False` → `record_outcome` returns None → 0 writes regardless of eligibility |
| **C10_FIX_STAGED_IN_REPO** | **YES** — `deploy/systemd/phase13-grader.service` and `deploy/systemd/phase13-tier-advancement-grader.service` gain `Environment=TM_CORPUS_WRITER_PRODUCTION=1`; comment blocks corrected |
| **C10_FIX_INSTALLED_TO_SYSTEMD** | **NO** — `/etc/systemd/system/phase13-grader.service` byte-identical to pre-fix; operator sudo required for install + daemon-reload (procedure in §5) |
| **C10_ACCEPTANCE_RULING** | **REJECT (until installed fix produces first TM_OUTCOME row)** — C10 sub-passes A-H are green and preserved; C10-J prospective outcome proof cannot be signed off while the deployed graders silently drop every write. Ruling flips to PASS on: (a) operator installs the two updated unit files + `daemon-reload`; (b) next natural timer fire logs `n_outcomes_written > 0` and appends to `logs/tm_outcomes.jsonl`; (c) `cache/tm_corpus_cursor.json.graded_tuples` grows. |
| **AUTHORITY_CHANGED** | NO |
| **TRADING_BEHAVIOUR_CHANGED** | NO |
| **AUTOBOT_TOUCHED** | NO — MainPID 1217431 unchanged; no restart; no `.env` write |

STOP after C10 final acceptance report.
