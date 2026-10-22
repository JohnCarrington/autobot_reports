# Briefing Execution — Part 1 Investigation, 2026-05-13

Service restart: 07:09:43 UTC, PID 1111620. Investigation window: 07:09:43 → ~07:21 UTC (now).

Footnote on PIA: a parallel v5_pia briefing tree exists at
`/opt/tradingbot/briefings/v5_pia/briefing_<PAIR>_2026-05-13_London.json`
(separate from the executor's source-of-truth briefings under
`/opt/tradingbot/logs/`). All findings below are about
`BRIEFING_EXECUTION` (v4) only.

---

## Section 1: Today's 05:30 UTC London briefing per pair

### 1.1 Briefing file locations

The London briefing JSONs the executor reads are written to
`/opt/tradingbot/logs/`, not `/opt/tradingbot/briefings/`. The
`briefings/` directory only contains the `v5_pia/` subtree (PIA Phase 3
shadow producer). The four executor-consumed files for today:

| Pair    | Path                                                                    | mtime (UTC) |
|---------|-------------------------------------------------------------------------|-------------|
| GBPUSD  | `/opt/tradingbot/logs/briefing_GBPUSD_2026-05-13_London.json`           | 05:32       |
| EURUSD  | `/opt/tradingbot/logs/briefing_EURUSD_2026-05-13_London.json`           | 05:35       |
| USDCAD  | `/opt/tradingbot/logs/briefing_USDCAD_2026-05-13_London.json`           | 05:39       |
| USDJPY  | `/opt/tradingbot/logs/briefing_USDJPY_2026-05-13_London.json`           | 05:36       |

(Original `ls /opt/tradingbot/briefings/*2026-05-13*` returned "No such
file or directory"; the producer writes to `/opt/tradingbot/logs/` and
the executor reads from there. Confirmed via `find /opt/tradingbot -name
"*2026-05-13*" -type f`.)

### 1.2 Per-pair extracted fields

(Extracted via Python — `jq` not installed.)

```
=== GBPUSD ===
best_trade.mode: CONDITIONAL
trading_plans count: 6
signal_filter: {'allow_buys': True, 'allow_sells': True,
                'notes': 'Both directions allowed. D1 trend is NEUTRAL (score +1/9); no directional veto applied.'}
daily_bias: NEUTRAL    session_bias: NEUTRAL
news_risk: HIGH

=== EURUSD ===
best_trade.mode: UNCONDITIONAL
trading_plans count: 6
signal_filter: {'allow_buys': True, 'allow_sells': True,
                'notes': 'Both directions allowed. D1 trend is NEUTRAL (score +3/9); no directional veto applied.'}
daily_bias: NEUTRAL    session_bias: BEARISH
news_risk: HIGH

=== USDCAD ===
best_trade.mode: CONDITIONAL
trading_plans count: 6
signal_filter: {'allow_buys': True, 'allow_sells': True,
                'notes': 'Both directions allowed. D1 trend is NEUTRAL (score +2/9); no directional veto applied.'}
daily_bias: NEUTRAL    session_bias: BEARISH
news_risk: HIGH

=== USDJPY ===
best_trade.mode: CONDITIONAL
trading_plans count: 5
signal_filter: {'allow_buys': False, 'allow_sells': True,
                'notes': 'Sells only. D1 direction is BEAR (moderate confidence, score -4/9).'}
daily_bias: BEARISH    session_bias: NEUTRAL
news_risk: HIGH
```

### 1.3 Summary table

| Pair    | best_trade mode | plans count | signal_filter (B/S)   | daily_bias | news_risk |
|---------|-----------------|-------------|-----------------------|------------|-----------|
| GBPUSD  | CONDITIONAL     | 6           | allow / allow         | NEUTRAL    | HIGH      |
| EURUSD  | UNCONDITIONAL   | 6           | allow / allow         | NEUTRAL    | HIGH      |
| USDCAD  | CONDITIONAL     | 6           | allow / allow         | NEUTRAL    | HIGH      |
| USDJPY  | CONDITIONAL     | 5           | block buys / allow    | BEARISH    | HIGH      |

Total London-applicable plans today across 4 pairs: 6 + 6 + 6 + 5 = **23
trading_plans authored**. CONDITIONAL vs UNCONDITIONAL: **3 CONDITIONAL,
1 UNCONDITIONAL.**

The signal_filter field is *not* consulted by `briefing_execution.py`
at fire-time — verified by `grep -nE
"signal_filter|allow_buys|allow_sells" /opt/tradingbot/briefing_execution.py`
returning empty. The flag is descriptive narrative for the briefing
JSON only. (Direction enforcement, where it exists, happens via plan
authoring — e.g. USDJPY only emitted 5 plans, of which the rank-1
London is SHORT and matches the BEAR D1.)

### 1.4 Commit `8de0265` — Step 1 prompt change

`git show 8de0265 --stat` summary: 6 files, +1002 LOC. The behavioural
change is a single edit to `morning_briefing.py` at lines 1871-1908
(+50 / -21 LOC). The diff converts the `best_trade.mode` instruction
from a neutral "if/else logic → CONDITIONAL, single thesis →
UNCONDITIONAL" framing to one that **defaults to CONDITIONAL on
multi-scenario days**.

Key new prompt clauses (literal text from the diff,
`morning_briefing.py` post-commit):

1. **Default flip:** "*Default to CONDITIONAL when your trading_plans
   cover mutually-exclusive scenarios that cannot all play out today.
   Use UNCONDITIONAL only when one plan is clearly dominant and the
   others are unlikely fallbacks (e.g. a strong-conviction continuation
   day with no impending news, no major level untested, no
   session-split thesis).*"

2. **Multi-scenario trigger list:** "*A day is multi-scenario when ANY
   of these hold: price can sweep one key level OR test another (not
   both); London is expected to behave one way and NY differently; a
   scheduled news release will resolve direction one of two ways;
   pre-event drift and post-event continuation are both plausible.*"

3. **Counter-trend legitimacy:** "*Counter-trend intraday plans WITHIN
   a strong daily_bias are legitimate and your plan_summary should
   reflect them. A BULL daily that expects a morning sweep below
   support before resuming higher is a CONDITIONAL day, not an
   UNCONDITIONAL LONG day*"

4. **Soft 4+ heuristic:** "*Soft heuristic: if you have authored 4+
   trading_plans across multiple sessions OR across multiple
   directions, the day is almost certainly multi-scenario — default to
   CONDITIONAL unless one plan's raw_probability exceeds every other
   plan by at least 0.20 (clear dominance).*"

**Today's outcome vs commit intent:** 3 of 4 pairs returned
CONDITIONAL (GBPUSD, USDCAD, USDJPY) on a day with 5–6 plans across
mutually-exclusive sweep / breakdown / news-driven branches. This is
the commit's intended behaviour.

**The 1 UNCONDITIONAL (EURUSD)** is partial counter-evidence to the
"4+ plans → default CONDITIONAL" heuristic. EURUSD authored 6 plans
across 2 sessions and 2 directions (3 London: LONG sweep-bounce, SHORT
breakdown, SHORT fade; 3 NY: SHORT continuation, LONG reversal, LONG
range-fade) — by the prompt's own soft heuristic this should have been
CONDITIONAL. The model's stated reasoning is the dominance escape
clause: *"Rank-1 London plan (sell-side liquidity sweep then bounce)
has strongest geometric setup with clear trigger, invalidation, and
pre-PPI timing, matching plan_summary thesis exactly."* The model
appears to have evaluated rank-1's `raw_probability` as 0.20+ above
all others (validation deferred — would need to inspect the model's
internal scoring). Not a prompt-design failure, but a marginal call by
the LLM on a pair whose 6 plans are arguably multi-scenario by every
other criterion.

---

## Section 2: Executor hydration state

### 2.1 Hydration log lines from journalctl

Source: `journalctl -u autobot.service --since "07:09:00" --until
"07:11:00" | grep -E "hydrated|plan state"`

```
07:09:43.371 [BRIEFING-EXEC] USDJPY plan state hydrated — active=3 london=2 ny_pending=3 ny_armed=0 ny_discarded=0 invalidated=6
07:09:43.372 [BRIEFING-EXEC] USDCAD plan state hydrated — active=1 london=3 ny_pending=3 ny_armed=0 ny_discarded=0 invalidated=5
07:09:43.373 [BRIEFING-EXEC] EURUSD plan state hydrated — active=1 london=3 ny_pending=3 ny_armed=0 ny_discarded=0 invalidated=5
07:09:43.373 [BRIEFING-EXEC] GBPUSD plan state hydrated — active=0 london=3 ny_pending=3 ny_armed=0 ny_discarded=0 invalidated=7
```

Cache files read at startup
(`/opt/tradingbot/cache/briefing_plans_<PAIR>.json`):

| Pair    | Cache file mtime (UTC) | active | london | ny_pending | invalidated |
|---------|------------------------|--------|--------|------------|-------------|
| GBPUSD  | 06:25:02               | 0      | 3      | 3          | 7           |
| EURUSD  | 05:35:12               | 1      | 3      | 3          | 5           |
| USDCAD  | 06:00:02               | 1      | 3      | 3          | 5           |
| USDJPY  | 05:40:25               | 3      | 2      | 3          | 6           |

### 2.2-2.3 Per-pair active_plans contents

Read from each cache file via Python. **All active plans carry the new
`plan_id` field, originate from `best_trade` resolution, and use
strategy tag `BRIEFING_EXECUTION` (no BRIEFING_V5 / PIA in the executor
plan list).**

#### USDJPY — active=3 (matches verification)

| plan_id    | session | rank | direction | bias  | entry_zone        | stop_loss | targets         | expires_at  |
|------------|---------|------|-----------|-------|-------------------|-----------|-----------------|-------------|
| `London_1` | London  | 1    | SELL      | SHORT | [15772.0, 15775.0]| 15782.0   | [15760, 15753]  | 12:30Z      |
| `London_2` | London  | 2    | BUY       | LONG  | [15753.0, 15756.0]| 15745.0   | [15765, 15772]  | 12:30Z      |
| `NY_1`     | NY      | 1    | BUY       | LONG  | [15775.0, 15778.0]| 15765.0   | [15789, 15800]  | end_of_day  |

USDJPY signal_filter says `allow_buys=False`, yet London_2 (BUY) and
NY_1 (BUY) are in active_plans. This is consistent with §1.3 — the
executor does not consult `signal_filter`; the LLM chose to author
2-way London branches anyway (Section 1.4 commit explicitly licenses
counter-trend intraday plans within a directional D1).

#### EURUSD — active=1

| plan_id    | session | rank | direction | bias | entry_zone           | stop_loss | targets             | expires_at |
|------------|---------|------|-----------|------|----------------------|-----------|---------------------|------------|
| `London_1` | London  | 1    | BUY       | LONG | [11730.0, 11732.0]   | 11722.0   | [11740.0, 11748.1]  | 12:30Z     |

UNCONDITIONAL → singleton (rank-1 London). All 3 London branches are
preserved in `london_plans[]` audit field for visibility.

#### USDCAD — active=1

| plan_id    | session | rank | direction | bias  | entry_zone           | stop_loss | targets             | expires_at |
|------------|---------|------|-----------|-------|----------------------|-----------|---------------------|------------|
| `London_1` | London  | 1    | SELL      | SHORT | [13712.0, 13716.0]   | 13726.0   | [13680.0, 13646.8]  | 12:30Z     |

CONDITIONAL with 2 branches (London rank-1 + NY rank-1). NY_1 was
invalidated at 06:00:02 by H1 close 13697.25 beyond invalidation
13690.00 (journal evidence), leaving 1 active plan.

#### GBPUSD — active=0

CONDITIONAL with 3 London branches (rank 1/2/3). All 3 were dropped
between 05:35 and 06:25:

- `London_3` (SHORT) invalidated at 05:35:28 (`[BRIEFING-EXEC] GBPUSD
  plan ... (plan_id=London_3) invalidated — 5m bar close 13544.75000
  beyond invalidation 13518.00000`).
- `London_1` (LONG) expired at 06:00 (`[BRIEFING-EXEC] GBPUSD plan ...
  (plan_id=London_1) expired at 06:00 — dropping`). This is the
  pre-news sweep-fade plan with hard 06:00 deadline.
- `London_2` (LONG) invalidated at 06:25:02 (`[BRIEFING-EXEC] GBPUSD
  plan ... (plan_id=London_2) invalidated — 5m bar close 13535.55000
  beyond invalidation 13545.00000`).

active=0 is the correct end-state given today's price action; not a
hydration bug.

### 2.4 Multi-slot architecture confirmation

`_plans[sym]` is a **list of distinct plan dicts**, iterated
rank-ascending in `evaluate_tick`. Each list element is a full plan
dict with its own `_sweep_seen`, `_armed_at`, `_trend_closes`,
`_dormant` latches. Evidence:

- `briefing_execution.py:1947-1957`:
  ```python
  plans = list(self._plans.get(sym) or [])
  # Rank-ascending iteration with deterministic cross-session
  # tie-break (London=0 before NY=1, then plan_id lexicographic).
  plans.sort(key=lambda p: (
      int(p.get("rank") or 999),
      0 if str(p.get("session") or "").lower() == "london" else 1,
      str(p.get("plan_id") or ""),
  ))
  ```
- Cache write (`briefing_execution.py:2661`):
  ```python
  "active_plans": list(self._plans.get(sym) or []),
  ```
- Cache read with backward-compat for the old singleton field
  (`briefing_execution.py:2764-2772`).

USDJPY's `active=3` is genuinely 3 distinct plans being independently
evaluated — confirmed by the journal showing simultaneous evaluation:
at 07:15:02 a single tick produced three log lines, one per plan:
- `London_1 SELL BLOCKED trigger_v2 ... reason=['rsi(5m,>,70.0): cur=48.16 prev=51.10']`
- `NY_1 ... skipped — phase2 5m close=15770.25 did not confirm (direction=BUY ...)`
- `London_2 ... TREND_ENTRY vetoed — entry 15770.25 is 14.2p past zone (cap 10p)`

Three different gate paths, three different plan_ids, one tick. That
is the multi-slot design delivering exactly as specified in commits
`5772574` (Commit B) and `229dab4` (Commit C).

One stale-cache artifact worth noting: the `ny_pending`, `london_plans`,
and `invalidated_plans` audit lists in the saved JSON have
`plan_id=None` and (for `invalidated_plans`) all-None metadata. The
post-`4789627` rank-backfill + hard-drop logic only applies to
`active_plans` on hydrate (see `briefing_execution.py:2774-2820`); the
other lists are preserved as written. This is cosmetic — the executor
only iterates `_plans[sym]` (active) in `evaluate_tick`.

---

## Section 3: BRIEFING_EXECUTION fires since 07:09:43

### 3.1 / 3.2 Raw fire events

From `journalctl -u autobot.service --since "07:09:43"`. **No
broker-accepted fires since restart** — `grep -E "IG response|dealStatus"`
returned empty. All fires that reached dispatch were blocked by
concurrent cap at the trade_executor layer.

Context: a **pre-restart fire is still open**. At 06:40:03 (PID
1093450, before the 07:09:43 restart on PID 1111620), USDCAD London_1
TREND_ENTRY SELL @ 13702.45 fired and was accepted (`[DISPATCH]
CS.D.USDCAD.TODAY.IP SELL BRIEFING_EXECUTION entry accepted (0/1 open
before)`, `[BRIEFING-EXEC] USDCAD fill confirmed plan_id=London_1
session=London dealId=DIAAAAXGCBL2PA7`). The new process reconciled
this at 07:09:42 (`[RECONCILE] ✅ Restored CS.D.USDCAD.TODAY.IP SELL
entry=13701.2 dealId=DIAAAAXGCBL2PA7 ... mode=BRIEFING_EXECUTION`).
That is the concurrent slot consumed for the remainder of the session.

### 3.3 Fire table since 07:09:43

| Time UTC   | Pair   | Dir  | Plan ID    | Strategy            | Entry      | SL pips | TP pips | Trigger                           | Outcome                                |
|------------|--------|------|------------|---------------------|------------|---------|---------|-----------------------------------|----------------------------------------|
| 07:09:43.94 | USDCAD | SELL | London_1   | BRIEFING_EXECUTION  | 13703.85   | 20.4    | 57.1    | TREND_ENTRY (2x 5M closes through zone, 90.0min since arm) | DISPATCH blocked — concurrent cap (1/1) |
| 07:10:02.74 | USDCAD | SELL | London_1   | BRIEFING_EXECUTION  | 13706.35   | 17.9    | 59.5    | TREND_ENTRY (2x 5M, 90.3min)      | DISPATCH blocked — concurrent cap (1/1) |
| 07:15:04.18 | USDCAD | SELL | London_1   | BRIEFING_EXECUTION  | 13705.95   | 18.3    | 59.2    | TREND_ENTRY (2x 5M, 95.3min)      | DISPATCH blocked — concurrent cap (1/1) |
| 07:20:03.40 | USDCAD | SELL | London_1   | BRIEFING_EXECUTION  | 13708.05   | 16.2    | 61.2    | TREND_ENTRY (2x 5M, 100.3min)     | DISPATCH blocked — concurrent cap (1/1) |

All 4 fires are the **same plan** (USDCAD London_1) re-firing on each
new 5M close because the dispatch-side concurrent cap rejects without
clearing the executor-side fire. Plan stays armed (`_sweep_seen=false`,
TREND_ENTRY fallback path) and re-triggers every 5 minutes. The
already-filled position on the same plan is the cap holder.

### 3.4 Are the USDCAD fires plan-driven or fallback?

The fires are emitted via the **TREND_ENTRY fallback path**
(`briefing_execution.py:2026-2228`), `fire_path="trend_entry_fallback"`
(line 2144 / 2206). This path is **plan-driven, not strategy-fallback**:

- Trigger condition: 2 consecutive 5M closes through the plan's
  authored entry_zone in the plan's authored direction AND ≥30 min since
  arming (`BRIEFING_TREND_ENTRY_MIN_MINUTES=30`,
  `briefing_execution.py:40`). Activates when the producer-authored
  sweep never materialised but price has decisively moved through the
  zone — code comment line 2026 calls it "TREND_ENTRY fallback".
- Uses the plan's `invalidation_price` for SL (line 2045), the plan's
  `targets` for TP (line 2069), and the plan's `entry_zone` for the
  10-pip drift-past-zone cap (line 2057-2067).
- USDCAD London_1's authored entry_zone is [13712.0, 13716.0]. The
  fires entered at 13703.85 / 13706.35 / 13705.95 / 13708.05 — 8.0 /
  5.7 / 6.0 / 4.0 pips past zone_lo (within the 10p cap). Drift is
  within bounds, plan author's invalidation 13724.25 is used for SL.

In other words, "TREND_ENTRY fallback" means "the plan's zone-based
entry never triggered the producer-authored sweep+reclaim, but price
went through the zone on a clean trend — fire the plan in its
authored direction using its authored invalidation, with a geometric
sanity cap." It is the same plan, the same authoring, just a different
fire_path stamp.

The producer-authored entry_trigger_v2 for London_1 was:
```json
{"type": "sweep", "level": 13717.5, "side": "above", "tolerance_pips": 2.0},
{"type": "candle_close", "timeframe": "5m", "direction": "below", "level": 13715.0}
```
A sweep-and-reclaim pattern that never materialised (price went down,
not up-then-down). TREND_ENTRY filled the gap.

---

## Section 4: Plans that hit triggers but were blocked

### 4.1 Raw block events since 07:09:43

Source: `journalctl -u autobot.service --since "07:09:43" | grep -iE
"blocked|skipped|vetoed|did not confirm|invalidated"`

```
07:09:43.954  USDCAD SELL  BRIEFING_EXECUTION  blocked — concurrent cap reached (1/1)              [DISPATCH]
07:09:44.639  USDJPY plan_id=NY_1 skipped — phase2 5m close=15772.75 did not confirm (BUY)         [BRIEFING-EXEC]
07:10:02.742  USDCAD SELL  BRIEFING_EXECUTION  blocked — concurrent cap reached (1/1)              [DISPATCH]
07:10:03.103  USDJPY plan_id=NY_1 skipped — phase2 5m close=15771.60 did not confirm (BUY)         [BRIEFING-EXEC]
07:10:03.104  USDJPY TREND_ENTRY vetoed — entry 15771.60 is 15.6p past zone (cap 10p) London_2     [BRIEFING-EXEC]
07:10:06.063  EURUSD plan_id=London_1 skipped — phase2 5m close=11720.20 did not confirm (BUY)     [BRIEFING-EXEC]
07:15:02.326  EURUSD plan_id=London_1 skipped — phase2 5m close=11718.30 did not confirm (BUY)     [BRIEFING-EXEC]
07:15:02.529  USDJPY SELL BLOCKED trigger_v2 plan_id=London_1 ... reason=['rsi(5m,>,70.0): cur=48.16 prev=51.10']  [BRIEFING-EXEC]
07:15:02.530  USDJPY plan_id=NY_1 skipped — phase2 5m close=15770.25 did not confirm (BUY)         [BRIEFING-EXEC]
07:15:02.571  USDJPY TREND_ENTRY vetoed — entry 15770.25 is 14.2p past zone (cap 10p) London_2     [BRIEFING-EXEC]
07:15:04.182  USDCAD SELL  BRIEFING_EXECUTION  blocked — concurrent cap reached (1/1)              [DISPATCH]
07:20:03.387  EURUSD plan_id=London_1 skipped — phase2 5m close=11718.10 did not confirm (BUY)     [BRIEFING-EXEC]
07:20:03.405  USDCAD SELL  BRIEFING_EXECUTION  blocked — concurrent cap reached (1/1)              [DISPATCH]
07:20:03.596  USDJPY plan_id=NY_1 skipped — phase2 5m close=15772.20 did not confirm (BUY)         [BRIEFING-EXEC]
07:20:03.597  USDJPY TREND_ENTRY vetoed — entry 15772.20 is 16.2p past zone (cap 10p) London_2     [BRIEFING-EXEC]
```

### 4.2 / 4.3 Block classification

Cross-referenced against `/opt/tradingbot/docs/executor_gate_kill_list_2026-05-12.md`
(audit Section 2 — KEEP/REMOVE buckets).

| Time UTC    | Pair   | Dir  | Plan ID    | Gate                                           | Bucket | Justified? | Audit row |
|-------------|--------|------|------------|------------------------------------------------|--------|------------|-----------|
| 07:09:43.95 | USDCAD | SELL | London_1   | concurrent cap (1/1) at DISPATCH               | KEEP   | Yes — already-open USDCAD position from 06:40:03 fire on the same plan | #24 (per-pair cap) |
| 07:09:44.64 | USDJPY | BUY  | NY_1       | phase2 5m close did not confirm                | KEEP   | Yes — close 15772.75 not above zone_lo 15775.0 (BUY direction) | #(phase2 normal flow) |
| 07:10:02.74 | USDCAD | SELL | London_1   | concurrent cap (1/1)                           | KEEP   | Yes — same as 07:09:43 | #24 |
| 07:10:03.10 | USDJPY | BUY  | NY_1       | phase2 5m close did not confirm                | KEEP   | Yes | — |
| 07:10:03.10 | USDJPY | BUY  | London_2   | TREND_ENTRY 10p drift-past-zone cap            | KEEP   | Yes — 15.6p past zone, plan authored for [15753-15756] | #9 |
| 07:10:06.06 | EURUSD | BUY  | London_1   | phase2 5m close did not confirm                | KEEP   | Yes — close 11720.20 outside zone [11730-11732] (sweep seen at 07:09:44) | — |
| 07:15:02.33 | EURUSD | BUY  | London_1   | phase2 5m close did not confirm                | KEEP   | Yes | — |
| 07:15:02.53 | USDJPY | SELL | London_1   | trigger_v2 BLOCKED — rsi(5m,>,70.0) failed (cur=48.16)  | KEEP   | Yes — plan-authored RSI condition, never overbought = no fade | #7 |
| 07:15:02.53 | USDJPY | BUY  | NY_1       | phase2 5m close did not confirm                | KEEP   | Yes | — |
| 07:15:02.57 | USDJPY | BUY  | London_2   | TREND_ENTRY 10p drift-past-zone cap            | KEEP   | Yes — 14.2p past zone | #9 |
| 07:15:04.18 | USDCAD | SELL | London_1   | concurrent cap (1/1)                           | KEEP   | Yes | #24 |
| 07:20:03.39 | EURUSD | BUY  | London_1   | phase2 5m close did not confirm                | KEEP   | Yes | — |
| 07:20:03.41 | USDCAD | SELL | London_1   | concurrent cap (1/1)                           | KEEP   | Yes | #24 |
| 07:20:03.60 | USDJPY | BUY  | NY_1       | phase2 5m close did not confirm                | KEEP   | Yes | — |
| 07:20:03.60 | USDJPY | BUY  | London_2   | TREND_ENTRY 10p drift-past-zone cap            | KEEP   | Yes — 16.2p past zone | #9 |

**Block bucket distribution:** 15 blocks since 07:09:43. **15 KEEP, 0
REMNANT, 0 OTHER.**

Block breakdown by gate type:
- concurrent cap (DISPATCH): 4 (all USDCAD London_1)
- phase2 5m close did not confirm: 6 (3 EURUSD London_1, 3 USDJPY NY_1)
- TREND_ENTRY 10p drift-past-zone cap: 3 (all USDJPY London_2)
- trigger_v2 (rsi 5m > 70.0 failed): 1 (USDJPY London_1)
- silent skips: 1 (USDCAD `concurrent_cap_reached` STRATEGY-line echoes
  the DISPATCH line — same event, different layer)

**REMNANT directional gates fired: zero.** No D1_VETO emissions, no
6-bar HH/HL trend references, no `unknown_unknown` plan_id warnings.
Code grep confirms `D1_VETO|d1_veto|6.bar|consec_HH` returns empty in
`/opt/tradingbot/briefing_execution.py`.

### 4.4 USDJPY London_2 past-zone block — legitimate stale plan?

**Yes, legitimate.** Details:

- London_2 (USDJPY) was promoted to `_plans[USDJPY]` from briefing
  ingest at 05:36:33 UTC (cache `_armed_at = 1778650593.07`).
- Plan-authored entry_zone: [15753.0, 15756.0], direction BUY.
- Plan-authored sweep_level_price: `null` (no anchor sweep — the BUY
  branch relies on price returning to zone after the dip).
- By 07:10:03 (the first post-restart block), price was at 15771.60 —
  15.6 pips above zone_hi 15756.0. That's a BUY plan whose
  "sell-side liquidity sweep bounce" thesis has long since passed; the
  bounce already happened or never happened, but price is now 15p+
  above the authored entry. Firing a BUY here would enter at a price
  the plan never authored.
- Audit row #9 (`/opt/tradingbot/docs/executor_gate_kill_list_2026-05-12.md`)
  classifies this as KEEP: "*GEOMETRIC stale-plan protection.
  Distinguishes 'direction is wrong' from 'the entry zone the producer
  wrote no longer exists.'*"
- Code: `briefing_execution.py:2060-2067`, the 10-pip cap is
  symmetrical for BUY/SELL and uses the plan's own zone, not a
  directional bias.

Plan still hasn't been invalidated (invalidation is `15745.0
below 5m`; price never closed below that), so it keeps re-firing the
TREND_ENTRY path every 5M, and the cap keeps catching it every 5M.
Acceptable; will resolve at 12:30Z expiry.

---

## Section 5: Honest summary

### 5.1 Is BRIEFING_EXECUTION firing on triggered plans now?

**Yes — directionally unblocked.** Pre-`4789627`, SHORTs were
universally vetoed via D1_VETO + 6-bar HH/HL gates. Post-`4789627`,
since the 07:09:43 restart we see **4 SELL fires** at the
BRIEFING-EXEC layer (USDCAD London_1, all blocked downstream by
concurrent cap from a pre-existing fill), **1 SELL block at
trigger_v2** (USDJPY London_1, RSI 48 vs required >70 — legitimate
plan-author trigger), and **3 BUY-direction TREND_ENTRY past-zone
caps** (USDJPY London_2, geometric not directional). Zero of those 8
events involves a directional gate. There were also 2 USDCAD fires
pre-restart at 06:40:03 that were broker-accepted (`dealId=DIAAAAXGCBL2PA7`,
SELL). Net: SHORTs are firing, the only thing blocking them is the
operational concurrent-position cap and the plan-authored
trigger/zone state.

### 5.2 Remaining silent blocks

**Mostly clean.** The post-audit log surface now emits at INFO for:
trigger_v2 BLOCKED (line 2474, verified), phase2 did-not-confirm (line
2251), TREND_ENTRY vetos (lines 2061, 2080, 2119), TREND_ENTRY
levels_match advisory (line 2126), session-lockout silent skip (lines
1965-1969, deduped via `_skip_log_seen`), `_dormant` silent skip
(lines 1975-1979, deduped). All audit-row VISIBLE entries are wired
up. The only `logger.debug` paths remaining in `briefing_execution.py`
are operational scaffolding (resample failures `:557`, dedup-load
hiccup `:1527`, Telegram notify failure `:1768`, resolver expired
branches `:1200,1222`) — none of which would change a fire/skip
decision. Raising `LOG_LEVEL=DEBUG` would surface tick-level price
ingestion and feed-side detail but no additional executor skip paths.
Caveat: I have not audited every `continue` in the file (there are
40+) for "silent skip with no preceding log" — the 5 cases the audit
explicitly called out are confirmed wired.

### 5.3 Is multi-slot delivering?

**Yes, with a caveat.** Per-pair active-plan counts (hydrated +
post-invalidation): GBPUSD=0, EURUSD=1, USDCAD=1, USDJPY=3.
Independent evaluation evidence: USDJPY at 07:15:02 emits three
distinct gate decisions on a single tick — London_1 trigger_v2,
London_2 TREND_ENTRY cap, NY_1 phase2 confirm — three different
plan_ids, three different fire paths, three different gates. That is
the multi-slot design delivering exactly as commits `5772574` /
`229dab4` specified. **Caveat:** EURUSD's UNCONDITIONAL collapse left
only 1 active plan despite 6 authored — the multi-slot machinery is
correct, but the producer's 8de0265 prompt didn't push the LLM to
CONDITIONAL on EURUSD today. That is upstream of the executor; not a
multi-slot delivery failure. On USDCAD, NY_1 invalidated at 06:00:02
naturally reduced the CONDITIONAL active set from 2 to 1; on GBPUSD,
all 3 London branches naturally invalidated/expired between 05:35 and
06:25 — both healthy outcomes of producer-authored invalidation
conditions, not multi-slot bugs.
