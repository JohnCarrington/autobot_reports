# EMA_PULLBACK & BRIEFING_EXECUTION — segmented re-score

**Premise from the request.** Lifetime figures
(`GBPUSD_EMA_PULLBACK_L` −131 p, `BRIEFING_EXECUTION` −338 p) span
versions of both strategies that no longer exist. Find the change
points, cut by them, re-score per segment.

## Reading this before the numbers — the NTZ premise doesn't match the record

The request assumes an "NTZ gate promotion (~2026-08-06) and its
revert". Both git and env history contradict that framing:

- `BRIEFING_NO_TRADE_ZONE_ENABLED=1` continuously in every `.env`
  snapshot from **2026-05-14** (earliest surviving `.env.bak_*`)
  through the current `/opt/tradingbot/.env` (2026-08-11 15:48).
  27 snapshots checked, all `=1`. No promotion event, no revert.
- No commit between 2026-08-04 and 2026-08-08 touches
  `BRIEFING_NO_TRADE_ZONE_ENABLED` or the `no_trade_zone` code path
  in `strategy_logic.py`. The code path itself has been present and
  active since well before the pnl window opens.
- `logs/diagnostics.log` (35 MB, current) contains zero
  `no_trade_zone` / `NTZ` records — there is no per-veto telemetry
  to count.

**What actually changed on `BRIEFING_EXECUTION` in early August** is
different, and is the change point I use below:

| commit | UTC time | change |
| :--- | :--- | :--- |
| **`d787cbe`** | **2026-08-03 08:32** | `fix(briefing_exec): fail-closed post-arm slice in _tv2_eval_sweep` — before this fix, the sweep evaluator was silently reading the full ~17 h in-memory 5m history (RangeIndex vs Timestamp comparison threw, caught by a bare `except`), so any prior excursion vacuously satisfied the sweep test. After the fix, only post-arm bars count. |
| **`ce8b647`** | **2026-08-10 23:48** | `feat(structure_exit): env-drivable per-mode exemption` — adds `BRIEFING_EXECUTION` to `STRUCTURE_EXIT_EXEMPT_MODES_EXTRA`. Post-close, not an entry gate. Motivating study (per commit body): 8 fires' STRUCTURE_EXIT closes had counterfactual +126.8 p, 3/8 counterfactual TP hits. |

**Live env confirmed** (`/opt/tradingbot/.env`, 2026-08-11 15:48 UTC):
`BRIEFING_NO_TRADE_ZONE_ENABLED=1`. NTZ is enforcing and has been for
the entire pnl window. There is no "while NTZ was enforcing" segment
to isolate because there is no "while it wasn't" comparator.

## EMA_PULLBACK — change points

From `git log gbpusd_ema_pullback.py`:

| commit | UTC time | change |
| :--- | :--- | :--- |
| `ea509bd` | 2026-07-20 15:19 | `feat(ema_pullback): hard-gate armed machine on side-signed fan_pips` — the fanning gate the request refers to. |
| `8a0f192` | 2026-07-28 23:37 | `feat(ema_pullback): retire armed machine, run detect-and-fire under WIDE regime gate` — the armed machine is retired here; this is the shape change. |
| `ed6931b` | 2026-08-05 17:08 | `feat(ribbon_gate): ribbon-state classifier + BB_BOUNCE/EMA_PB/TREND_V3 consumption matrix` — new ribbon gate consumed by EMA_PB. |
| `e22eb4e` | 2026-08-07 16:29 | `feat(velocity_gate): fourth entry-gate term` — velocity gate added. |

## Segmented re-score — EMA_PULLBACK

Corpus: 108 GBPUSD EMA_PULLBACK fires (`GBPUSD_EMA_PULLBACK_L`+`_S`+
armed `EMA_PULLBACK`). pnl populated 78/108; the 30 armed-machine
`EMA_PULLBACK` rows (all 2026-04-11) carry no pnl at all.

| segment | window | n | n_pnl | WR | med pnl | **sum pnl** | med mfe (n) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | pre-fan-gate (→ 07-20 15:19) | 97 | 67 | 41.8% | −10.50 | **−177.8 p** | 7.45 (31) |
| B | fan-gate era (07-20 → 07-28 23:37) | 3 | 3 | 33.3% | −11.45 | −10.0 p | 14.35 (3) |
| C | detect-and-fire era (07-28 → 08-05 17:08) | 4 | 4 | 25.0% | −10.45 | −16.1 p | 3.65 (4) |
| D | ribbon-gate era (08-05 → 08-07 16:29) | 1 | 1 | 0.0% | −11.85 | −11.8 p | 5.25 (1) |
| E | velocity-gate era (08-07 → now) | 3 | 3 | 33.3% | −8.70 | −19.2 p | 5.95 (3) |

Per-strategy inside each segment (kept because pnl coverage varies):

- **A (n=97, pnl 67):**
  `GBPUSD_EMA_PULLBACK_L` n=30 sum −88.0 p WR 36.7%;
  `GBPUSD_EMA_PULLBACK_S` n=37 sum −89.9 p WR 45.9%;
  armed `EMA_PULLBACK` n=30 (no pnl).
- **B (n=3):** all `EMA_PULLBACK_S`.
- **C (n=4):** `EMA_PULLBACK_L` n=2 sum −20.9 p (0/2); `EMA_PULLBACK_S` n=2 sum +4.8 p (1/2).
- **D (n=1):** single `EMA_PULLBACK_L` loss.
- **E (n=3):** `EMA_PULLBACK_L` n=2 sum −10.6 p; `EMA_PULLBACK_S` n=1 sum −8.7 p.

**Coarser binary** (armed-machine retirement 2026-07-28 23:37):

| segment | n | n_pnl | WR | med pnl | sum pnl | med mfe (n) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| PRE-retire (armed-machine era + fan-gate era) | 100 | 70 | 41.4% | −10.50 | **−187.9 p** | 8.10 (34) |
| POST-retire (detect-and-fire → now) | 8 | 8 | 25.0% | −10.45 | **−47.2 p** | 5.20 (8) |

**Verdict — EMA_PULLBACK.**

- The **entire post-armed-retire sample is 8 fires**, spread across
  three subsequent gate iterations (detect-and-fire / ribbon / velocity).
  Every subsegment except A has n ≤ 4 pnl-scored fires.
- **Post-cutover record: 8 fires, 2 winners, sum −47.2 p.** By any
  metric this is **too thin to judge** whether the shape change was a
  net positive. All eight fires bled at close to the SL (median pnl
  −10.45 p ≈ full stop-out).
- Every gate iteration since 2026-07-28 has produced ≤ 4 fires. The
  same environment that no longer runs the −131 p lifetime EMA_PB_L
  hasn't had a fair sample of the new one.

## BRIEFING_EXECUTION — change points and segments

Corpus: 310 BRIEFING_EXECUTION fires. pnl populated 142/310 (older
rows lack `pnl_pips`; the field was added to the logger in June).

| segment | window | n | n_pnl | WR | med pnl | **sum pnl** | med mfe (n) |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| PRE sweep-fix | up to 2026-08-03 08:32 | 306 | 139 | 36.7% | −4.00 | **−306.5 p** | 7.77 (68) |
| POST sweep-fix, PRE structure-exit-exempt | 2026-08-03 08:32 → 2026-08-10 23:48 | **3** | 3 | 0.0% | −10.60 | **−31.9 p** | 9.20 (3) |
| POST structure-exit-exempt | 2026-08-10 23:48 → now | **1** | 0 | — | — | (no pnl yet) | (none) |

Only **4 fires** exist since the 2026-08-03 sweep-fix; **1 fire** since
the 2026-08-10 STRUCTURE_EXIT exemption.

### Fire cadence — equivalent 8-day windows around the sweep-fix

| window | fires | sum pnl |
| :--- | ---: | ---: |
| 2026-07-26 → 2026-08-03 (pre-fix) | 9 | −16.8 p |
| 2026-08-03 → 2026-08-11 (post-fix) | 3 | −31.9 p |

The sweep-eval fix **cut BRIEFING_EXECUTION fire cadence by ~⅔** in
matched 8-day windows (9 → 3). This is consistent with the commit
description: pre-fix, false-satisfied sweeps were letting the strategy
fire; post-fix, only actually-post-arm excursions release the entry.
The three post-fix fires all lost pnl; the sample is too thin to
conclude anything about the *quality* of what remains.

### NTZ vetoes while enforcing

The request asked how many plans were vetoed by NTZ while it was
enforcing. NTZ has been enforcing continuously (see top of report), so
"while it was enforcing" is the entire pnl window. But there is
**no telemetry that logs per-plan NTZ vetoes** — `strategy_logic.py`
returns a rejection reason `no_trade_zone [lo-hi]` but does not
JSONL-log it, and 0 rows in `logs/diagnostics.log` or the searchable
logs contain the string `no_trade_zone` outside the briefing-plan JSON
files themselves. **Veto counts cannot be reported from this host.**

**Verdict — BRIEFING_EXECUTION.**

- Post-fix sample (2026-08-03 → 2026-08-11): **3 fires, all losers,
  sum −31.9 p.** Cadence dropped ~⅔; **too thin to judge** whether
  the surviving fires are directionally better.
- Post-structure-exit-exemption sample (2026-08-10 → now): **1 fire,
  no pnl yet.** Nothing to score.
- Live env: `BRIEFING_NO_TRADE_ZONE_ENABLED=1`. NTZ enforcing.
- The −306.5 p lifetime figure is now entirely from the pre-2026-08-03
  era (306 of 310 fires); the post-fix strategy has generated too few
  fires to have a lifetime.

## Sample-honesty summary

| strategy | segment | n | verdict |
| :--- | :--- | ---: | :--- |
| EMA_PULLBACK | pre-fan-gate era (A) | 97 | negative sum, 67 pnl fires |
| EMA_PULLBACK | fan-gate era (B) | 3 | too thin |
| EMA_PULLBACK | detect-and-fire (C) | 4 | too thin |
| EMA_PULLBACK | ribbon-gate (D) | 1 | too thin |
| EMA_PULLBACK | velocity-gate (E) | 3 | too thin |
| EMA_PULLBACK | pre/post binary | 100 / 8 | **post-cutover too thin to judge** |
| BRIEFING_EXECUTION | pre-sweep-fix | 306 | negative sum, 139 pnl fires |
| BRIEFING_EXECUTION | post-sweep-fix | 3 | **too thin to judge**; cadence cut ⅔ |
| BRIEFING_EXECUTION | post-structure-exit-exempt | 1 | no pnl yet |

No recommendations.

---
*Sources: `git log`, `.env` and 27 `.env.bak*` snapshots,
`/opt/tradingbot/logs/signal_log.jsonl`, `/opt/tradingbot/logs/diagnostics.log`.
Change-point hashes: `ea509bd`, `8a0f192`, `ed6931b`, `e22eb4e`, `d787cbe`,
`ce8b647`. Analysis kept in `/tmp/segrescore/` during the run and cleaned
by explicit name at the end.*
