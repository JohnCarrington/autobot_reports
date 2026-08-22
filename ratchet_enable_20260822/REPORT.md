# RATCHET ENABLE — Option A + close-out (2026-08-22)

**Host:** AutoBotV1 (`/opt/tradingbot`)
**Branch:** `feat/trend-stretch-brake-adx-floor` — pushed HEAD `54fc359`
**Restart:** `2026-08-22 20:13:31 UTC` (`autobot.service`, operator-run)
**Main PID (post-restart):** `2131165`

---

## Push

```
$ git push origin feat/trend-stretch-brake-adx-floor
To github.com:JohnCarrington/AutoBot.git
   ff02fb5..54fc359  feat/trend-stretch-brake-adx-floor -> feat/trend-stretch-brake-adx-floor

$ git log --oneline origin/feat/trend-stretch-brake-adx-floor..HEAD
(empty)
```

Fast-forward push; no upstream rewrite.

## Contradictions surfaced during this run (up front)

**C6. `.env` block already present.** All four `EXIT_STACK_...=TIERED_RATCHET`
lines already existed at `.env:916-919` from a prior turn (backup
`.env.pre-ratchet-enable.20260822T152809Z` predates this session). Nothing
appended; operator confirmed the block was authorised.

**C7. `git log origin..HEAD` returned 1 commit, not 4.** Prior 3 commits
(`d62094d`, `88f075d`, `ff02fb5`) were already on origin. The earlier
post-restart report's "all three commits are LOCAL only" claim was
true at 15:00 UTC but stale by the time of this run. Operator
confirmed the earlier pushes were authorised.

**C8. Classify DOES run at boot.** Item 0(a) of the earlier report
claimed "classify_regime is NOT called at startup at all." Journal shows
otherwise — see boot proof (b) below. Both symbols hit
`_compute_trend_subtype` at 20:13:42-43 UTC with
`reason=insufficient_history` (not `baseline_stale` — correct branch).
This is a real re-scoping of item 0(a); not investigated further this
turn since the outcome is benign for Sunday's open.

---

## Boot proofs

### (a) — environ shows all four EXIT_STACK_ vars — PROVEN

```
$ tr '\0' '\n' < /proc/2131165/environ | grep -E '^EXIT_STACK_' | sort
EXIT_STACK_GBPUSD_EMA_PULLBACK_L=TIERED_RATCHET
EXIT_STACK_GBPUSD_EMA_PULLBACK_S=TIERED_RATCHET
EXIT_STACK_GBPUSD_TREND_V3_L=TIERED_RATCHET
EXIT_STACK_GBPUSD_TREND_V3_S=TIERED_RATCHET
```

### (b) — exit_dress resolution + baseline INFO + first-classify reason

**baseline loaded INFO — PROVEN.** Raw journalctl line:

```
2026-08-22T20:13:42+0000 AutoBotV1 python[2131165]: 2026-08-22 20:13:42,710 [INFO] [trend_subtype] baseline loaded path=/opt/tradingbot/data/grind_baseline.json session=07:00-16:00 medians=EURUSD=3.0p GBPUSD=3.9p age_secs=23630.6 window_days=20
```

**reason != baseline_stale on both symbols — PROVEN.** Raw journalctl lines:

```
2026-08-22T20:13:42+0000 AutoBotV1 python[2131165]: 2026-08-22 20:13:42,710 [INFO] [trend_subtype] transition symbol=EURUSD regime=STRONG_TREND_DOWN <unset> -> null efficiency=null bar_size_ratio=null reason=insufficient_history ts=None
2026-08-22T20:13:43+0000 AutoBotV1 python[2131165]: 2026-08-22 20:13:43,010 [INFO] [trend_subtype] transition symbol=GBPUSD regime=STRONG_TREND_DOWN <unset> -> null efficiency=null bar_size_ratio=null reason=insufficient_history ts=None
```

Reason on both = `insufficient_history` (bars-count branch), not
`baseline_stale` (48h-threshold branch) — the router is alive, the
baseline is fresh, and the null-subtype path terminates on the correct
branch.

**exit_dress resolution — all four trend modes → TIERED_RATCHET, BB
family MANAGED — PENDING.** `exit_dress.resolve()` is called per fire.
Market currently closed; no fire since restart, so no `[EXIT_DRESS]`
lines exist in the journal. Grep to run at Sunday 21:10 UTC:

```
journalctl -u autobot.service --since '2026-08-23 21:00:00' --no-pager --output=short-iso \
  | grep -iE "EXIT_DRESS|dress_resolved|TIERED_RATCHET|BRACKET_MANAGED"
```

Expected: `[EXIT_DRESS]`-tagged lines showing `bracket=TIERED_RATCHET`
for the four trend modes and `bracket=MANAGED` (or ambient default) for
BB_BOUNCE modes as fires occur.

### (c) — EXIT_STACK_ vs BIG_NEWS LADDER_PATIENT dress-resolution check

**Resolution-order docstring, verbatim, `exit_dress.py:158-181`:**

```
Resolution order (highest → lowest priority):

  1. Per-mode direct override — `EXIT_STACK_<MODE>=<BRACKET>`.
     Wins over everything else. Provided so an operator can activate
     TIERED_RATCHET (or any bracket) for one mode without needing to
     set up a DRESS_MAP_* map. Case-insensitive on both mode and
     bracket. Ignored if the value is not a VALID_BRACKET.

  2. `DRESS_MAP_<LABEL>=MODE1:BRACKET,MODE2:BRACKET,...` env for the
     current day_context label. Falls through to the built-in
     `_DEFAULT_TREND_MAP` for that label when the env is empty.

  3. `DRESS_DEFAULT_<LABEL>=<BRACKET>` per-label fallback.

  4. Ambient default — LADDER_STANDARD for ladder-managed modes
     (level_ladder.is_ladder_managed_mode); MANAGED otherwise.
```

**Built-in BIG_NEWS map, `exit_dress.py:82-90`:**

```python
"BIG_NEWS": {
    "GBPUSD_TREND_V3_L": BRACKET_LADDER_PATIENT,
    "GBPUSD_TREND_V3_S": BRACKET_LADDER_PATIENT,
    "GBPUSD_EMA_PULLBACK_L": BRACKET_LADDER_PATIENT,
    "GBPUSD_EMA_PULLBACK_S": BRACKET_LADDER_PATIENT,
    ...
```

**Resolved value on a simulated BIG_NEWS day for the four trend modes
= `TIERED_RATCHET`.** Step 1 fires (env var set); returns before step 2
is consulted. BIG_NEWS's `_DEFAULT_TREND_MAP[LADDER_PATIENT]` value is
never seen.

**Flag — unruled interaction:** on the first BIG_NEWS day, the operator's
`EXIT_STACK_...=TIERED_RATCHET` override WINS over `_DEFAULT_TREND_MAP`'s
`LADDER_PATIENT` for all four trend modes. Prior to today's change, a
BIG_NEWS-tagged day would have dressed the trend book with LADDER_PATIENT
(assess-bars+1, stop-buffer+1p, session-end exhaustion overlays). It now
routes to TIERED_RATCHET instead — the 12p init SL + 15/40/75 lock ladder
+ strict-beyond-BE exhaustion + 20:40 flat replace the patient overlay.
That is `Option A` semantics as stated ("routes ALL trend-book fires to
TIERED_RATCHET regardless of day_ctx"), but the LADDER_PATIENT default was
put there deliberately for news days. If the intent is to keep
LADDER_PATIENT on BIG_NEWS days and TIERED_RATCHET everywhere else, the
override needs conditional wiring (currently a single-precedence step-1
match wins always). No code change made — flagging for a ruling.

### (d) — reconcile hooks + book state — PROVEN

Raw journalctl:

```
2026-08-22T20:13:40+0000 AutoBotV1 python[2131165]: 2026-08-22 20:13:40,469 [INFO] [RECONCILE] No open IG positions found.
2026-08-22T20:13:40+0000 AutoBotV1 python[2131165]: 2026-08-22 20:13:40,471 [INFO] [RECONCILE] No orphaned positions — starting clean.
```

Book state: **empty**. Ratchet has no positions to arm on top of.

### (e) — journal clean, market-closed idle — PROVEN

Error-level messages since boot:

```
$ journalctl -u autobot.service --since '2026-08-22 20:13:00' --no-pager -p err | wc -l
1

$ journalctl -u autobot.service --since '2026-08-22 20:13:00' --no-pager -p err
-- No entries --
```

(`wc -l` includes the header line — 0 actual error entries.)

Heartbeat present, market-closed idle expected:

```
2026-08-22T20:13:40+0000 AutoBotV1 python[2131165]: 2026-08-22 20:13:40,482 [INFO] 💓 AutoBot running — tick age: EURUSD:0s | GBPUSD:0s | Cooldown: GBPUSD:READY | EURUSD:READY
2026-08-22T20:14:10+0000 AutoBotV1 python[2131165]: 2026-08-22 20:14:10,511 [INFO] 💓 AutoBot running — tick age: EURUSD:29s | GBPUSD:29s | Cooldown: GBPUSD:READY | EURUSD:READY
```

### (f) — live seeded buffer vs synthetic; first live classify — PENDING

The 0(d) harness quoted in the `54fc359` commit-message report used
a **synthetic** DataFrame — `np.linspace(1.2500, 1.2560, 60)*10000`,
a pure monotone drift. `efficiency = |net| / sum(|diffs|) = 0.06 / 0.06
= 1.0` is a mathematical artefact of a straight-line series, NOT a
real-tape value. Acknowledged; that presentation was misleading.

The boot-time transition lines in (b) also do not qualify — they fire
with `ts=None` and `reason=insufficient_history` (an incomplete buffer
at boot, not a real 5m close). No live-tape classify has run since
restart.

**First live classify — PENDING first 5m close after Sunday's open.**
Grep to run at Sunday 21:10 UTC:

```
journalctl -u autobot.service --since '2026-08-23 21:00:00' --no-pager --output=short-iso \
  | grep -E '\[trend_subtype\] transition' \
  | head -20
```

Expected on the first bar with a fully-populated 36-bar window: a
transition line with `efficiency=` a real value **strictly < 1.0** for
both symbols (any real tape has two-way movement in a 36-bar Kaufman
window). If the first live line shows `efficiency=1.000` on either
symbol, that's a red flag (buffer not filled with real ticks, or the
compute is degenerate) and requires investigation.

### (g) — decision.sl per mode + ratchet-tighten-at-arm

| mode | decision.sl source (file:line) | pip value | ratchet init tightens? |
|:---|:---|:---|:---|
| `GBPUSD_TREND_V3_L` | `gbpusd_trend_v3.py:1548` (`sl=float(sl_pips)`); `sl_pips` capped at `MAX_SL_PIPS=12` (`gbpusd_trend_v3.py:114`, env default `"12"`, no override) | `min(structural, 12)` — often 8-12p, never > 12 | **No.** ≤ ratchet 12p → `already_inside` guard at `trade_executor.py:2334-2343` fires SKIP |
| `GBPUSD_TREND_V3_S` | same | same | **No** — same guard |
| `GBPUSD_EMA_PULLBACK_L` | `gbpusd_ema_pullback.py:1011`, `:1547`, `:2847` (`sl=round(sl_pips, 2)`); `sl_pips = SL_PIPS = 12.0` (`gbpusd_ema_pullback.py:395` + env override `.env:644`) | **12p exactly** | **No.** Existing 12p = ratchet init 12p → `already_inside` guard SKIP |
| `GBPUSD_EMA_PULLBACK_S` | same | **12p exactly** | **No** — same guard |

At arm, the strategy-installed broker SL is either equal to (EMA_PB)
or tighter than (TREND_V3 with a close swing) the ratchet's 12p init.
The `already_inside` guard leaves it in place — the ratchet's 12p
never *widens* an existing tighter SL. The load-bearing new protection
on top is the SOFTWARE stop advancement: tier locks at 15/40/75p per
`RATCHET_TIERS=10:0,30:15,60:40,100:75`, strict-beyond-BE exhaustion
after 6 flat bars once tier 1+ hits, and 20:40 UTC session flat.

---

## Final state — what Sunday 21:00 opens with

**Book:** empty (0 open positions, reconcile clean).

**Env / router:** all four `EXIT_STACK_...=TIERED_RATCHET` vars loaded
into the service process; `[trend_subtype]` router alive (baseline
fresh, load INFO emitted at boot, first classify hit
`insufficient_history` not `baseline_stale`).

**Exit dress for the four trend modes:** `TIERED_RATCHET` on ALL day
contexts including BIG_NEWS (`EXIT_STACK_` step 1 wins over BIG_NEWS
`_DEFAULT_TREND_MAP` step 2 — flagged in (c) as an unruled interaction).

**Exit dress for BB family:** unchanged. `EXIT_STACK_` keys not set for
BB_BOUNCE modes; resolution falls to step 4 ambient default (`MANAGED`
for non-ladder modes).

**Decision.sl at arm:** 12p or tighter across all four trend modes;
ratchet 12p init never widens existing SL. Software tier ladder
(0/15/40/75), strict-beyond-BE exhaustion, and 20:40 UTC session flat
sit on top.

**GRIND path status:** the entry-side GRIND branch (drop-ER, +consolidation
break, +6-bar re-entry cooldown) is wired but its first live activation
proof is (f), which is PENDING. Included in this Sunday-open state
description only as much as (b) already proved (router alive, baseline
loaded); the "GRIND actually fires and produces a real-tape efficiency"
claim is PENDING (f).

---

## Sunday 21:10 UTC grep list (verbatim)

```
# (b) — exit_dress resolution
journalctl -u autobot.service --since '2026-08-23 21:00:00' --no-pager --output=short-iso \
  | grep -iE "EXIT_DRESS|dress_resolved|TIERED_RATCHET|BRACKET_MANAGED"

# (f) — first live classify
journalctl -u autobot.service --since '2026-08-23 21:00:00' --no-pager --output=short-iso \
  | grep -E '\[trend_subtype\] transition' \
  | head -20
```
