# Session 3-Prep & Ops Guard — 2026-08-26

**Host:** 161 (autobot.service)
**HEAD:** `9235c2b` (feat/trend-stretch-brake-adx-floor)
**Reports written:** all local, unpushed to autobot repo. Restart NOT required for any item.

---

## Contradictions in the brief

The brief cites **"the position closed 17:33Z at −29.2p (and its 17:30 scale-out sibling)"**. The system clock is UTC; today's log is UTC-stamped end-to-end; and at the moment of investigation the wall-clock read `2026-08-26 17:19 UTC`. There is no 17:30 or 17:33 UTC event in any of today's logs — the last close intent this host filed today was `16:30:01.619Z` (deal `DIAAAAYCPU44WA5`, TREND_V3_S, `TREND_V3_REGIME_LEFT`), and the position that matches the loss magnitude and hold-into-late-London profile closed at `16:33:39Z` for **−29.05p**.

Best-fit interpretation: the operator quoted **local London (BST = UTC+1)**. `17:33 BST = 16:33 UTC` and `17:30 BST = 16:30 UTC`. Investigation proceeds on that basis; if that is wrong, the trade tables below still enumerate every close today and none match "17:33Z" natively.

The referenced loser is **`06713896 / DIAAAAYCPBPYCA8` (GBPUSD_LEVEL_BOUNCE_L, BUY)** — closed 16:33:39Z at 13592.85 for −29.05p, opened 10:40:01Z at 13621.90.

The referenced "scale-out sibling" is likely **`b25fcc3d / DIAAAAYCPU44WA5` (GBPUSD_TREND_V3_S, SELL)** — scale-out at 14:20:56Z, full close 16:30:02Z at 13594.4 (+7.0p residual, +15.0p total). Different strategy, opposite direction, different management; the two positions are not linked by design and the "sibling" framing does not survive scrutiny — they simply overlap in time and closed within three minutes of each other.

---

## ITEM 2 — Position management history for the −29.05p LEVEL_BOUNCE_L loser

**Restart NOT required** — investigate-only.

### Restart timeline (from journalctl -u autobot, today)

| # | Stop UTC | Start UTC | Prev PID → New PID | Notes |
|---|---|---|---|---|
| 1 | 09:27:31 | 09:27:31 | 2649107 → 2708367 | 01h54m CPU consumed; clean systemd stop |
| 2 | 09:55:16 | 09:55:16 | 2708367 → 2709045 | 05m10s CPU; clean stop |
| 3 | 10:03:41 | 10:03:41 | 2709045 → 2709501 | 02m07s CPU |
| 4 | 10:04:26 | 10:04:26 | 2709501 → 2709560 | 24s CPU (transient); rapid re-bounce |
| 5 | 10:34:16 | 10:34:16 | 2709560 → **2715379** | 30-min run; PID 2715379 still running (6h+ uptime) |

All five restarts happened **BEFORE** the loser was opened. No restart occurred between 10:34:16Z and now.

### Position 06713896 / DIAAAAYCPBPYCA8 lifecycle (single PID)

| ts UTC | PID | event | source | pnl | notes |
|---|---|---|---|---|---|
| 10:40:01.707 | 2715379 | **open** BUY @ 13621.9 | trade_executor.confirmed → signal_log | 0 | SL 13521.9 (100p), TP 14620.9 (100p). LEVEL_BOUNCE_L is `unmanaged (100p SL is sole exit)` per per-tick log |
| 12:10:00 | 2715379 | level_touch S1 @ 13633.12 | level_bounce_ladder | +10.97p | MFE so far 11.4p |
| 12:35:00 | 2715379 | level_touch S2 @ 13615.43 | level_bounce_ladder | −6.72p | MFE 13.6p (peak) |
| 13:05:00 | 2715379 | level_touch S3 @ 13604.82 | level_bounce_ladder | −17.33p | Rolling over into New York — MACD 5m/H1 both expanding bear |
| 10:40–16:33 | 2715379 | ~4200 per-tick `STRUCTURE_EXIT skipped … unmanaged (100p SL is sole exit)` | autobot journal | — | Confirms mode config prevented all state-management (no ratchet, no scale-out, no BB exit) throughout the hold |
| 16:33:38.959 | 2715379 | IG position vanished: `dealId=DIAAAAYCPBPYCA8 not in IG positions (1/3 misses)` | autobot journal | — | First evidence the position had already been closed at IG |
| 16:33:39.043 | 2715379 | `close_by_deal_id: no open positions found` | autobot journal | — | Bot's own close attempt found nothing to close |
| 16:33:39.087 | 2715379 | LADDER close row written: realised=−29.1 mfe=+13.6 mae=38.7 given_back=42.6 hold=5h53 reason=`External close (not initiated by this host)` | level_bounce_ladder | −29.05 | |

### Inheritance verdict

**Clean — no inheritance happened.** Every restart today completed by 10:34:16Z. The position opened at 10:40:01Z under PID 2715379 and was managed continuously by the same PID for its full 5h53m life. `close_intent.jsonl` contains zero rows for `DIAAAAYCPBPYCA8`, confirming this host never issued any close for it — the position vanished from the IG position book at 16:33:38Z and the bot detected the disappearance via its /positions poll ~1s later. State inherited across PIDs: not applicable. State recomputed on inheritance: not applicable. Scale-out flag: not applicable — LEVEL_BOUNCE_L is configured `unmanaged (100p SL is sole exit)`, so no scale-out, ratchet, or trail state exists to inherit even in principle.

### Close authority + close-in-spec assessment

The close was **not initiated by this host**. `_classify_close_reason` in `trade_manager.py:3496` returns "External close (not initiated by this host)" as its catch-all when the exit price doesn't match SL (13521.9), TP (14620.9), the trail-aware amended SL/limit, or the pre-scale-out BE band. Exit 13592.85 is 29p below entry and matches none of these — hence the catch-all label. Options for who did close it: (a) manual close by operator at IG, (b) another autobot host on the same account, (c) an IG-side action (margin, session enforcement) — 16:33 UTC is not a rollover window (20:55–21:05Z), so option (c) is unlikely without a triggering condition. This host cannot disambiguate (a) vs (b) from local logs alone; the IG activity feed for the account would.

**In-spec for its mode?** Yes, the ride to −29p was in-spec: LEVEL_BOUNCE_L accepts a 100p stop as sole exit and has no give-back or floor rule. It was designed to be either a full winner (100p reach for target) or up-to-100p loser. Given back 42.65p from peak of +13.6p is within the mode's contract — the mode has no give-back rule. The external agent that closed at −29p is what actually saved this trade from a possibly-larger loss.

### One-paragraph honest verdict

Inheritance was clean. This loser was born, managed, and observed-closed by a single PID (2715379). Every restart today happened before the trade opened, so the "five restarts" and "the position closed today" are separate stories that the churn narrative merges. The mode's `unmanaged (100p SL is sole exit)` config is what allowed the +13.6p peak to bleed to −17p at S3 without intervention, and something external — most likely manual or a sibling host — booked the −29p exit at 16:33:39Z. If there is a lesson here it is about the LEVEL_BOUNCE_L management contract, not about restart-driven state loss.

---

## ITEM 1 — Restart guard (`scripts/safe_restart.sh`)

**Restart NOT required.** New scripts; nothing running loads them.

Files (all new, unit-test covered):
- `scripts/safe_restart_lib.py` — pure logic (rollover check, IG position normalization, verdict dataclass). No I/O; import-safe.
- `scripts/safe_restart_check.py` — fetches open positions via `close_sb_now.get_open_positions()` (the same path autobot uses), evaluates via the lib, writes an audit row to `logs/safe_restart.jsonl`, exits 0 (clear) / 1 (blocked) / 2 (guard failure).
- `scripts/safe_restart.sh` — thin bash wrapper; on pass, prints:

  ```
  sudo systemctl restart autobot.service
  ```

  The script itself does not invoke `systemctl` — the operator copy-pastes, keeping the restart visible in shell history.
- `scripts/tests/test_safe_restart_lib.py` — 7 tests (rollover boundaries, blocked/clear/unknown, rollover-beats-positions, normalization). All pass.

### Operator usage

```
scripts/safe_restart.sh                # normal — refuses if open positions or 20:55-21:05 UTC
scripts/safe_restart.sh --force        # override with WARN + audit log line
scripts/safe_restart.sh --actor NAME   # stamp actor into audit log
scripts/safe_restart.sh --json         # (via env) machine-readable verdict on stdout
```

Guard triggers:
1. **Open positions on this book** → refuse; print the position list; `--force` overrides.
2. **20:55–21:05 UTC (rollover)** → refuse regardless of position state; `--force` overrides. Rollover check runs before positions, so an empty book inside the window is still blocked.
3. **IG /positions fetch fails (None returned)** → refuse (we do not guess). `--force` overrides.

Audit log: `logs/safe_restart.jsonl`, one row per invocation (clear, blocked, or forced), fields: `ts_utc, actor, status, forced, reason, n_positions, positions`.

Standing rule: **this is now the only sanctioned restart path.** Direct `sudo systemctl restart autobot.service` is discouraged; the guard is what makes forced restarts observable in the audit log.

---

## ITEM 3 — Session-3 calibration harness

**Restart NOT required.** New script; read-only.

Files:
- `scripts/qm_day_features_report.py` — accepts `YYYY-MM-DD` or `YYYY-MM-DD..YYYY-MM-DD`, `--pair GBPUSD`, `--json`. Reads `qm_chop_features.jsonl` + `qm_level_interactions.jsonl` + `data/candles/<pair>/YYYY-MM-DD.csv`. Keep-first dedup on candle timestamps.
- `docs/qm_day_labels.jsonl` — append-only operator labels. First row written for today: `TREND_GRIND_DOWN`.

### First two rows of the calibration table

```
date       │ bars │ net_range  │ net_dir  │ cross_med/max  │ med_leg_exc │ bbw_ratio  │ boundary_n │ REJECT_rate
─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
2026-08-25 │ 288  │ 32.9       │ 8.2      │ 0/0            │ —           │ —          │ 0          │ —
2026-08-26 │ 209  │ 65.1       │ -51.2    │ 0/5            │ 2.89        │ 0.749      │ 117        │ 0.547
```

Per-level extreme boundary interactions for today:

```
BB_L     n=32  REJECT=22  ACCEPT=9   BREAK_AWAY=1   reject_rate=0.688
BB_U     n=21  REJECT=11  ACCEPT=7   BREAK_AWAY=3   reject_rate=0.524
NY_H     n=3   REJECT=3   ACCEPT=0   BREAK_AWAY=0   reject_rate=1.000
NY_L     n=13  REJECT=6   ACCEPT=5   BREAK_AWAY=2   reject_rate=0.462
PDL      n=4   REJECT=2   ACCEPT=1   BREAK_AWAY=1   reject_rate=0.500
RANGE_L  n=21  REJECT=9   ACCEPT=9   BREAK_AWAY=3   reject_rate=0.429
SWING_H  n=2   REJECT=2   ACCEPT=0   BREAK_AWAY=0   reject_rate=1.000
SWING_L  n=21  REJECT=9   ACCEPT=9   BREAK_AWAY=3   reject_rate=0.429
```

### Data hygiene notes

- Yesterday (2026-08-25) has only **3 rows in `qm_chop_features.jsonl`** for GBPUSD — all timestamped `23:40:42Z` with null BB-width fields and `range=15.0` (stale/instrumentation-nascent). Candles give a truthful `net_range=32.9p`. `qm_level_interactions.jsonl` has zero rows for 2026-08-25 in the file at all. **The instrumentation needed for the harness's own metrics only started emitting reliably today** — this is worth knowing before comparing today's numbers against historical days: for now, only today's row is a real sample; older days would require a backfill from candles or a live-forward wait.
- Today's row is stable — 188 chop rows across the day, 138 level interactions of which 117 hit an extreme level.

### Today's label

```json
{"date": "2026-08-26", "pair": "GBPUSD", "label": "TREND_GRIND_DOWN",
 "labelled_by": "operator", "labelled_at_utc": "2026-08-26T17:20:00Z",
 "notes": "Fade-hostile day: net_dir=-51.2p on 65.1p range; gate should have
 stood the fade book down. First operator-labelled day of the QM calibration series."}
```

Appended to `docs/qm_day_labels.jsonl`. Format is append-only JSONL for future operator entries.

---

## Restart-required summary

| Item | Change | Restart? |
|---|---|---|
| 1 — safe_restart.sh + module + tests | New files under `scripts/`, no autobot imports | **No** |
| 2 — position continuity investigation | Read-only, no code touched | **No** |
| 3 — qm_day_features_report.py + label | New script under `scripts/`, new labels file under `docs/` | **No** |

Everything above activates when it is first invoked; nothing is on autobot's import path.
