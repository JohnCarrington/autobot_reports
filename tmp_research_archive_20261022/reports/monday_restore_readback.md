# Monday 2026-09-28 — restore readback (READ-ONLY, awaiting operator go)

## 1. What was running Monday

**Commit:** `cda3678` — "docs: IG DEMO acceptance report — pre-activation template"
(committed 2026-09-26 20:34:39 UTC).

**Evidence of "running on Monday":**
- `env.20260926T203743Z` is the only env-history snapshot between Sat 2026-09-26
  20:37:43 UTC and Tue 2026-09-29 14:46:46 UTC. The snapshot is produced
  `ExecStartPre` on every autobot.service restart (see `systemctl status
  autobot.service` drop-ins → `env-history.conf`). So the service ran
  continuously 2026-09-26 20:37:43 → 2026-09-29 14:46:46 on whatever code was on
  disk at the start.
- `git reflog` at that start: HEAD was `cda3678` (`2026-09-26 20:34:39 +0000`;
  next HEAD change was Sun 2026-09-27 21:01 for `8d64aef` and five more
  docs-only commits on 2026-09-28 — none of which were loaded because no
  restart happened).
- journalctl is unavailable: `journalctl --list-boots` shows only the current
  boot (started today 2026-10-05 09:15); the box was rebooted today so pre-reboot
  systemd journal is gone.
- `autobot-stop.timer` is **enabled** (fires Fri 22:00 UTC); `autobot-start.timer`
  is **disabled** — the Sat 2026-09-26 20:37 start was manual (operator or
  deploy script), and the service survived through Monday until the manual
  restart Tue 14:46.

**.env in force Monday:** `/opt/tradingbot/env-history/env.20260926T203743Z`
(48,340 bytes). This is the snapshot captured at the Sat 2026-09-26 20:37:43 UTC
start; no further snapshots exist until Tue 2026-09-29 14:46:46, confirming no
restart during Monday.

**Diff vs current `/opt/tradingbot/.env` — exactly one line:**

```
977c977
< V2_PICK_BOUNCE_ENABLED=1        (Monday)
---
> V2_PICK_BOUNCE_ENABLED=0        (current)
```

That one flag flip was captured in the first env snapshot of Sat 2026-10-03
09:25:06 UTC — the restart onto `restore/monday-firewall` → `restore/monday-plus`.
Nothing else in `.env` has changed since Monday.

Flags that were enabled on Monday (grep of env.20260926T203743Z):
- `ONE_STRATEGY_ENABLED=1`
- `BRIEFING_EXECUTION_ENABLED=1`
- `LEVEL_BOUNCE_ENABLED=1`
- `QM_LIVE_FIRE=1`
- `V2_PICK_BOUNCE_ENABLED=1` (differs from today)
- `BRIEFING_SWEEP_ENABLED=0`, `BRIEFING_HUNT_ENABLED=0`, `BRIEFING_LIQUIDITY_ENABLED=0`
- `BRIEFING_TP_ENABLED=1`

---

## 2. Monday + early-Tuesday fills (before any Tuesday restart)

The deal ledger stops 2026-09-27, so these come from
`logs/candidate_corpus.jsonl*` (executed=true) + `logs/close_intent.jsonl`
(close reasons) + `logs/tm_outcomes.jsonl` (counterfactual grader; the "if held"
figures are **not** the actual close P&L).

**Monday 2026-09-28** (all on cda3678; signal_log carries no entry for these):

| open UTC | deal_id | strategy | pair | side | entry | observed close reason | cf-if-held final (grader) |
|---|---|---|---|---|---|---|---|
| 06:00:07 | DIAAAAYJVP7PBA6 | ONE_STRATEGY | GBPUSD | LONG | 13240.75 | partial scale_out_50pct @ 07:29:55 (final close reason not recorded) | +1.0p (30m horizon) |
| 15:55:07 | DIAAAAYJYQAYGA4 | ONE_STRATEGY | GBPUSD | SHORT | 13252.35 | (no close_intent found) | −10.8p (30m horizon; max adverse 24.7p) |
| 18:50:04 | DIAAAAYJY53JNBY | ONE_STRATEGY | GBPUSD | SHORT | 13258.15 | NY_CLOSE @ 20:55:03 | +0.9p (30m horizon) |

**Tuesday 2026-09-29 — only fills BEFORE the first restart (14:46:46 UTC)
were still on cda3678:**

| open UTC | deal_id | strategy | pair | side | entry | observed close reason | cf-if-held final |
|---|---|---|---|---|---|---|---|
| 06:55:05 | DIAAAAYJ43XCNAZ | ONE_STRATEGY | GBPUSD | LONG | 13239.65 | (no close_intent found) | −12.7p (30m; mae 13.0p) |
| 07:35:13 | DIAAAAYJ47YT2BE | QM_V2_VELOCITY_S | EURUSD | SHORT | 11343.70 | partial scale_out_50pct @ 09:26:30 | −2.5p (30m) |
| 10:55:05 | DIAAAAYJ5N3LYA6 | ONE_STRATEGY | GBPUSD | LONG | 13234.75 | partial scale_out_50pct @ 11:49:56 | 0.0p (30m) |
| 12:05:08 | DIAAAAYKEQ6J3BC | QM_V2_VELOCITY_L | EURUSD | LONG | 11357.90 | **STRUCTURE_EXIT @ 12:35:18, pnl=−10.0p** | −11.6p (30m) |
| 12:45:07 | DIAAAAYKEU6WDA2 | ONE_STRATEGY | GBPUSD | SHORT | 13230.95 | partial scale_out_50pct @ 13:34:01 | −1.2p (30m) |

**First post-Monday restart: 2026-09-29 14:46:46 UTC → HEAD = `78840b3`
(Repair 9).** Everything after this ran on new code; the 17:15 ONE_STRATEGY
LONG fill (DIAAAAYKFR2PGBS) is **not** part of Monday's code path.

**Which strategies were enabled vs actually traded Mon/Tue (on cda3678):**

| strategy | env flag | fired? | notes |
|---|---|---|---|
| ONE_STRATEGY | `ONE_STRATEGY_ENABLED=1` | **yes — 6 of 8 fills** | all GBPUSD |
| QM_V2 velocity | `QM_LIVE_FIRE=1` | **yes — 2 of 8 fills** | both EURUSD |
| BRIEFING_EXECUTION | `BRIEFING_EXECUTION_ENABLED=1` | no fires in window | |
| V2_PICK_BOUNCE | `V2_PICK_BOUNCE_ENABLED=1` | **no fires on Mon/Tue even though enabled** | first V2_PICK slow-rejection fills landed later (2026-09-23 → 09-25 window; see section 4 of earlier audit) |
| LEVEL_BOUNCE | `LEVEL_BOUNCE_ENABLED=1` | no fires in window | last LEVEL_BOUNCE fill was 2026-09-23 06:25 |

**P&L caveat:** No source in this host carries the actual close price and
realised pips for the Mon fills except the one QM_V2 trade whose
`close_intent` recorded `pnl=−10.0p`. For the ONE_STRATEGY trades the close
reasons (`scale_out_50pct`, `NY_CLOSE`) are logged, but the fill prices are
not in signal_log (ONE_STRATEGY bypasses signal_logger, same as QM_V2 and
V2_PICK). Full-ledger pull of Mon/Tue fills would need the IG transaction
API — which requires a live session and is out of scope for a READ-ONLY
pass. The counterfactual grader numbers above are **not** actual close
P&L; they are "if-held-30m" figures from the TM phase13 grader.

---

## 3. Deploy / restart timeline since Monday

Every row below is an autobot.service start (= `env-history/env.*` creation)
mapped to the HEAD sha at that instant via `git reflog`:

| timestamp UTC | HEAD commit | one-line what changed |
|---|---|---|
| 2026-09-26 20:37:43 | cda3678 | **Monday's running build.** docs: IG DEMO acceptance template (prior same-session: f78264b feat(one_strategy) initial SL=12/TP=100 pre-DEMO) |
| 2026-09-29 14:46:46 | 78840b3 | first post-Monday restart. feat(reconcile): candidate_corpus as durable ownership fallback (Repair 9) — plus everything landed since cda3678: streamer PRICE migration (9955169), bounded LS recovery (7827630), autobot startup fail-closed (b570030), execution-authority firewall (bcd2452), ownership + freshness (477bd45), ONE_STRATEGY position-ownership + thesis invalidation (f70f8a7), NY_CLOSE weekday guard (709ea9d), Repairs 4-9. |
| 2026-09-29 16:39:41 | 52afb02 | fix(stage8): reconnect confirmed BB bounce evidence (Repair 10) |
| 2026-09-29 18:52:08 | 3df0a50 | fix(stage12): remove NMS independent EXIT authority from ONE_STRATEGY (plus 3a47694 persist active demonstrated direction; 00b5a3b require temporal reassertion; 975b3fe software-BE exemption) |
| 2026-09-30 09:17:59 | 6036d04 | fix(stage7): area-wide LOI acceptance + trust LOI ACCEPT at 2 bars |
| 2026-09-30 10:07:41 | d0bc944 | fix(stage7+stage10): close two entry dead-ends (710874b wires five SUPPORTING-only sensors; d0bc944 closes dead-ends) |
| 2026-09-30 10:22:11 | d0bc944 | restart (no new commit; env-reload or operator-triggered) |
| 2026-09-30 11:38:10 | 3435e17 | fix(stage6): resolved-interaction movement anchor survives active-area exit |
| 2026-09-30 14:51:06 | 2fb0488 | fix(execution): close /confirms-404 + open-position exact-ref gap (plus 40e2b6f durable IG pending-confirmation ledger; 124fdc0 pin Stage5 current_price) |
| 2026-09-30 16:21:42 | 3206a91 | merge fix/one-strategy-structural-opposition (fast-forward) |
| 2026-10-01 10:39:51 | 7d9fb2c | merge fix/v2-reversal-arming-cutover-20261001 (fast-forward) |
| 2026-10-01 15:32:31 | d8f6021 | fix(ads): rule 4b opposite CONTINUATION flips persisted direction |
| 2026-10-01 17:04:15 | 6a00046 | feat(arbiter): M2 — route ONE_STRATEGY emit through the arbiter (plus 5d14d51 M1 shadow; 15525fc M1 amendments) |
| 2026-10-01 17:32:16 | b4b3a17 | feat(arbiter): M3 — V2_PICK publishes proposition contract into ONE_STRATEGY |
| 2026-10-02 16:36:07 | bcd2452 | `checkout` to `restore/monday-firewall` branch (reset to execution-authority firewall only) |
| 2026-10-03 09:25:06 | 4ce9d6f | `checkout` to `restore/monday-plus` branch (NY_CLOSE weekday guard + ONE_STRATEGY exemption only; this is the env snapshot where `V2_PICK_BOUNCE_ENABLED` flipped 1 → 0) |
| 2026-10-05 11:24:17 | 725949d | current restart (today). docs(freeze) — pin BUILD 1 FROZEN block to commit 4483971 |

Total: **15 restarts since Monday's commit took effect**, spanning cda3678 →
78840b3 → 52afb02 → 3df0a50 → 6036d04 → d0bc944 → 3435e17 → 2fb0488 → 3206a91
→ 7d9fb2c → d8f6021 → 6a00046 → b4b3a17 → bcd2452 → 4ce9d6f → 725949d.

---

## 4. RESTORE PLAN — DO NOT EXECUTE

**Goal:** put `/opt/tradingbot` on commit `cda3678` with `.env` byte-identical
to `env-history/env.20260926T203743Z` (one-flag flip: `V2_PICK_BOUNCE_ENABLED=0 → 1`).

**Pre-flight invariants to confirm before go:**
1. UTC time is **outside both briefing-render windows**: `05:20-05:45` and
   `12:20-12:45` UTC. (This matches briefing-validation.timer 05:35 UTC and
   the midday briefing window; a restart inside either loses the half-hour
   briefing render.)
2. No open positions on the live book (IG DEMO account via `demo-api.ig.com`).
   `cat /opt/tradingbot/cache/pending_deal_ledger.json` should show no OPEN deals;
   if any, close them via existing operator script `scripts/safe_restart.py` or
   the equivalent `trades-api` endpoint — **operator does this**, I do not.
3. Backup takes <30s and leaves copies on-disk even if the restart fails.

**Steps** (all commands shown as the operator would run them; nothing in this
report has executed any of them):

```bash
#  === STEP 0: archive current state (reversible safety net) ===
TS=$(date -u +%Y%m%dT%H%M%SZ)
sudo mkdir -p /opt/tradingbot/archive/pre_restore_$TS
sudo cp -a /opt/tradingbot/.env                             /opt/tradingbot/archive/pre_restore_$TS/env.now
sudo cp -a /opt/tradingbot/cache/pending_deal_ledger.json   /opt/tradingbot/archive/pre_restore_$TS/
sudo cp -a /opt/tradingbot/cache/v2_pick_bounce_ledger.json /opt/tradingbot/archive/pre_restore_$TS/
sudo cp -a /opt/tradingbot/cache/one_strategy_event_ledger.json /opt/tradingbot/archive/pre_restore_$TS/
cd /opt/tradingbot
git rev-parse HEAD > /opt/tradingbot/archive/pre_restore_$TS/head.sha
git status -uno    > /opt/tradingbot/archive/pre_restore_$TS/git_status.txt

#  === STEP 1: confirm FLAT on IG (operator — not me) ===
# Review /opt/tradingbot/cache/pending_deal_ledger.json
# Close any open positions out-of-band via the operator's usual tool.
# Verify positions = 0 via trades-api or the dashboard before continuing.

#  === STEP 2: stop both services ===
sudo systemctl stop autobot.service
sudo systemctl stop trades-api.service

#  === STEP 3: move the tree to Monday's commit ===
cd /opt/tradingbot
# detached HEAD at 725949d today; move to cda3678
git checkout cda3678

#  === STEP 4: restore Monday's .env ===
# Current .env differs by exactly one flag; restore the full snapshot for
# strict parity.
sudo cp /opt/tradingbot/env-history/env.20260926T203743Z /opt/tradingbot/.env
sudo chmod 600 /opt/tradingbot/.env
sudo chown autobot:autobot /opt/tradingbot/.env

#  === STEP 5: verify the swap before starting ===
diff /opt/tradingbot/env-history/env.20260926T203743Z /opt/tradingbot/.env   # must be empty
git -C /opt/tradingbot rev-parse HEAD                                        # must print cda36782...

#  === STEP 6: start services (outside the two briefing windows!) ===
# Must be outside 05:20-05:45 and 12:20-12:45 UTC.
sudo systemctl start trades-api.service
sudo systemctl start autobot.service

#  === STEP 7: post-start sanity ===
sudo systemctl status autobot.service --no-pager | head -20
sudo systemctl status trades-api.service --no-pager | head -5
ls -lt /opt/tradingbot/env-history/env.* | head -3        # should show a brand-new snapshot
tail -40 /opt/tradingbot/logs/autobot.log 2>/dev/null || journalctl -u autobot.service -n 40 --no-pager
```

**Reversal path (if something is wrong post-start):**
```bash
sudo systemctl stop autobot.service trades-api.service
sudo cp /opt/tradingbot/archive/pre_restore_$TS/env.now /opt/tradingbot/.env
git -C /opt/tradingbot checkout $(cat /opt/tradingbot/archive/pre_restore_$TS/head.sha)
# then operator re-starts outside the briefing windows
```

**Risks the operator should name before I touch any of this:**
- The 15 restarts since Monday landed real repairs (streamer PRICE migration,
  execution-authority firewall, IG pending-confirmation durability, NY_CLOSE
  weekday guard, ONE_STRATEGY ownership). Restoring to cda3678 reverts **all**
  of them. In particular: the Mon/Tue QM_V2 live fire fills happened under the
  cda3678 streamer; if that streamer path has a known defect fixed after
  Monday, we're re-exposing it.
- The 2026-10-02 and 2026-10-03 `restore/monday-firewall` and
  `restore/monday-plus` checkpoints were themselves attempts to restore
  Monday's trading posture while keeping a subset of the post-Monday repairs
  (execution firewall + NY_CLOSE guard). The operator may want to confirm
  whether a strict cda3678 is what's wanted or one of those restore branches.
- The current HEAD is a detached `725949d` tagged "BUILD 1 FROZEN" with the
  standing rule *"Never run stash pop, stash apply, checkout, reset, merge,
  or rebase"* (CLAUDE.md §Git discipline). Step 3 above is an operator
  `git checkout` — I would not run it on my own initiative.
- `autobot-start.timer` is `disabled` — if the restart is scripted into an
  overnight window and the service dies, nothing will bring it back
  automatically. Confirm restart happens in-session.

**Nothing has been executed. Awaiting operator go-signal.**

STOP.
