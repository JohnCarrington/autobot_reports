# STRONG TREND v2 — review package (2026-10-13)

**Branch (AutoBot):** `feat/nms-data-continuity-stages1-3-20261012`
**Commit:** `f90ffd2` (v2, this change). Earlier `403922e` superseded.
**Branch (BB-Bounce dev):** `feat/nms-session-trend-guard-20261013`
(commit `da1babd`, unchanged — guard reads the v2 snapshot without
modification).

**Status:** DEVELOPMENT. Not deployed. No .env edited. No services
restarted. No IG orders placed.

---

## Why v2

The v1 state machine (`403922e`) delayed Oct 12 DOWN recognition
from 09:55 UTC to 14:20 UTC because it required `|displacement| ≥
20p` as a hard gate. Oct 12 at 09:55 had only `−15.3p` displacement
despite overwhelming structural evidence (`sr_dn=4` vs `sr_up=1`,
`close_pos=0.15`, `pullback_continues=1`, `reversals=0`). The
displacement gate rejected a day that satisfied every other
operator criterion.

The operator's redirection:

> Displacement is supporting evidence, not a mandatory
> standalone threshold.

v2 replaces the displacement hard-gate with a **structure
asymmetry** gate: a strong trend must show demonstrably more
same-direction confirmed swings than opposing swings. Displacement
magnitude surfaces as supporting evidence in the reason string.

---

## v2 recognition rules (per direction)

For STRONG DOWN:

| # | Gate | Default |
|---|---|---|
| 1 | `structure_run_down ≥ MIN_STRUCTURE_RUN` | 3 |
| 2 | `structure_run_down ≥ structure_run_up + MIN_STRUCTURE_ASYMMETRY` | +2 |
| 3 | `pullback_continues_down ≥ MIN_PULLBACK_CONTINUES AND ≥ pullback_continues_up` | 1 |
| 4 | `range_reversals ≤ MAX_RANGE_REVERSALS` | 2 |
| 5 | `close_pos ≤ CLOSE_POS_DOWN_CEILING` | 0.35 |
| 6 | `displacement ≤ −DISP_DIRECTION_SANITY_PIPS` (direction consistency, not progression) | −10p |
| 7 | all of 1–6 for `≥ STRONG_PERSISTENCE_BARS` consecutive bars | 2 bars (10 min) |

STRONG UP mirrors the above. Pre-London bars (bar_ts <
london_open_ts) do not advance the state machine.

**Supporting evidence surfaces in the reason string:**

```
strong_down:
  struct=[dn=4,up=1,asym=+3]|       ← primary: asymmetric structure
  pullback=[dn=1,up=0]|              ← primary: asymmetric persistence
  reversals=0|                       ← primary: not a range
  close_pos=0.16|                    ← primary: close near low
  disp=-11.2p(small)|                ← supporting: magnitude label
  piv_support=0|                     ← supporting: R2/R3 rejection count
  persistence_bars=2                 ← primary: criterion 5
```

**Release path (unchanged):** DOWN → UNKNOWN when displacement
reclaims the open by ≥ `RELEASE_RECLAIM_PIPS` (= 10p) for ≥
`RELEASE_PERSISTENCE_BARS` (= 2) consecutive bars. UP mirror.

---

## Why structure asymmetry is the primary gate

The six FPs under v1 and the single direction flip all shared one
feature: **symmetric or wrong-direction structure counts at fire
moment.** Bar-by-bar traces at the exact fire time:

| Day | Fire moment | sr_dn | sr_up | Asymmetry | Verdict under v2 |
|---|---|---|---|---|---|
| **Oct 12 09:55** (TRUE DOWN) | 09:55 UTC | 4 | 1 | **+3** | **PASS** → DOWN ✓ |
| 09-04 (FP DOWN) | 12:35 UTC | 5 | 5 | 0 | REJECT ✓ |
| 09-28 (FP UP) | 09:20 UTC | 3 | 2 | **−1** | REJECT ✓ |
| 09-30 (FP UP) | 09:50 UTC | 4 | 4 | 0 | REJECT ✓ |
| 10-09 (FP DOWN) | 12:35 UTC | 3 | 4 | **−1** | REJECT ✓ |
| 09-15 (DOWN truth → UP flip) | 13:50 UTC | 5 | 3 | **−2** (for UP) | REJECT ✓ |

Four of six FPs had sr_dn ≈ sr_up (symmetric); two had opposite-
direction structure. Oct 12 at 09:55 is unambiguously asymmetric
(ratio 4:1).

See [`evidence_traces.md`](evidence_traces.md) for the full
bar-by-bar traces that produced this analysis.

---

## 34-day replay results

Full replay of 2026-09-01 … 2026-10-13 against the live GBPUSD
candle archive.

**Scorecard:**

| Metric | v1 (`403922e`) | **v2 (`f90ffd2`)** |
|---|---|---|
| Correct trend classifications | 7 | **11** |
| Direction flips (truth vs final opposite) | 1 | **0** |
| False positives (truth RANGE/NORMAL, final UP/DOWN) | 6 | **4** |
| Missed trends | 10 | 7 |
| Oct 12 first DOWN | 14:20 UTC | **09:50 UTC** |
| Oct 12 pinned BUYs blocked | 1 of 4 | **4 of 4** |

**Confusion matrix (v2):**

| truth \\ final | DOWN | RANGE | UNKNOWN | UP |
|---|---|---|---|---|
| DOWN (12) | **8** | 3 | 1 | 0 |
| NORMAL (7) | 1 | 5 | 0 | 1 |
| RANGE (9) | 2 | 2 | 5 | 0 |
| UP (6) | 0 | 2 | 1 | **3** |

**Full per-day table:** see [`replay_table.md`](replay_table.md).

**Pros:**
- Oct 12 recognition at 09:50 UTC — matches operator's intent
- All 4 pinned BUYs on Oct 12 now blocked (was 1 of 4 under v1)
- Zero direction flips at EOD
- 09-15 flip (DOWN truth → UP) eliminated — day now stays UNKNOWN
- 09-30 FP eliminated — day now stays RANGE
- 10-09 wrong-direction FP eliminated — day stays UNKNOWN
- 09-01 no longer fires UP mid-morning before switching to DOWN

**Remaining failure modes:**

### 4 FPs — genuinely strong-looking days that reversed

| Date | Truth | ST | Fired | Why unavoidable point-in-time |
|---|---|---|---|---|
| 2026-09-04 | NORMAL | DOWN | 09:55 | asym=+2, pb=2, cpos=0.04, disp=−19p — meets every criterion; day reversed to NORMAL by EOD. |
| 2026-09-09 | RANGE | DOWN | 08:25 | Strong early DOWN leg; sr_dn=3, pb=2, cpos=0.04, disp=−13p. Day reversed later; release never crossed +10p threshold. |
| 2026-09-11 | RANGE | DOWN | 08:10 | Fast early plunge (disp=−24p by 09:05); sr_dn=3 asymmetric. Day mean-reverted; disp recovered but not past +10p. |
| 2026-09-28 | NORMAL | UP | 13:50 | Afternoon rally with asym=+2, cpos=0.82, disp=+26p; faded mild by EOD (close NORMAL). |

These days satisfy all 6 primary gates AT THE FIRE MOMENT. The
subsequent reversal is only visible in hindsight. The release
path handles the full-reclaim case; days that fade mildly (close
+5 to +15 from open) stay ST=UP/DOWN all day. See §4 for
mitigation options.

### 2 within-day wrong-direction fires

| Date | Truth | First fire | Final |
|---|---|---|---|
| 2026-09-18 | UP | DOWN at 10:45 | UNKNOWN |
| 2026-10-02 | UP | DOWN at 12:10 | RANGE |

These days have strong DOWN morning legs that satisfy the primary
gates, then reverse and complete as UP days. The release path
clears the DOWN state before EOD (final = UNKNOWN / RANGE), so
BB-Bounce BUYs are allowed by close. During the window between
fire and release, aligned BUYs are blocked — a documented
unavoidable cost.

### 7 missed trends

| Date | Truth | Reason unresolved |
|---|---|---|
| 2026-09-02 | DOWN | Day's structure insufficiently asymmetric; released before close. |
| 2026-09-03 | UP | Mild progression; sr_up never cleared min + asym. |
| 2026-09-15 | DOWN | Both directions had equal structure through the day; stays UNKNOWN. |
| 2026-09-17 | DOWN | Insufficient structure count at any point. |
| 2026-09-18 | UP | Started DOWN (wrong), released to UNKNOWN; UP never built asymmetric structure. |
| 2026-09-22 | DOWN | Slow drift; structure never asymmetric. |
| 2026-10-02 | UP | Started DOWN, released to RANGE; UP never rebuilt. |

Missed-trend days have **no false restriction** — both BUY and SELL
are permitted. The cost is a BB-Bounce entry on a counter-trend
day that could have been protected. v2's rate (7/18 = 39% miss)
is better than v1 (10/18 = 56%).

---

## 4. Mitigation discussion (operator decisions)

### 4.1 For the 4 "faded" FPs — displacement-decay soft release

Add a soft-release path: if established ≥ 3 hours AND current
displacement has shrunk from its extreme by ≥ 60% WITHOUT reaching
the full reclaim threshold, release to UNKNOWN.

**Risk:** might clear a legitimate trend during consolidation.
The operator spec says "Direction retained through consolidation"
— this is in tension.

**Not implemented.** Flagged for operator decision.

### 4.2 For the "early wrong direction" cases — minimum-time-since-London gate

Add `MIN_BARS_SINCE_LONDON = 24` (120 min) requirement. Would
delay the 09-18 10:45 and 10-02 12:10 fires? Let me compute:
10:45 is 225 min past 07:00 London open — passes any reasonable
time gate. 12:10 is 310 min — passes. Time gate doesn't help.

**Not implemented** (no measurable benefit).

### 4.3 Pivot-support hard requirement

Require same-direction pivot rejection (R2/R3 for DOWN, S2/S3 for
UP) in session. Would catch days where price never challenged a
pivot level — Oct 12 09:55 has `piv_support=0`, so this hard-gate
rejects Oct 12. **Rejected** — kills the Oct 12 recognition.

Pivot support stays in the reason string as evidence; not a gate.

---

## 5. BB-Bounce impact (chronological, archive-driven)

For each day, the guard decision at every pinned trade entry
(where entry timestamps are known from the live archive):

See [`bb_bounce_impact.md`](bb_bounce_impact.md) for the trade-
by-trade breakdown. Headline for Oct 12 (the trigger case):

| Entry | Side | v1 (`403922e`) | **v2 (`f90ffd2`)** |
|---|---|---|---|
| 08:10 | SELL | allow | allow |
| 09:35 | BUY | allow | allow |
| 10:20 | BUY | allow (lost protection) | **block** ✓ |
| 11:18 | BUY | allow (lost protection) | **block** ✓ |
| 12:20 | SELL | allow | allow |
| 14:10 | BUY | allow (lost protection) | **block** ✓ |
| 15:25 | SELL | allow | allow |
| 16:10 | BUY | block | **block** ✓ |

v2 restores full protection on all 4 historical losing BUYs.

---

## 6. Wiring + files touched

**AutoBot worktree** `/home/autobot/tradingbot-wt/nms-continuity-20261012`
branch `feat/nms-data-continuity-stages1-3-20261012`:

* `session_trend.py` — v2 state machine. Primary gates per §
   "v2 recognition rules." Snapshot shape unchanged.
* `tests/data_continuity/test_phase8_oct12_regression.py` —
   pinned decisions updated: DOWN establishes 09:50 UTC, 4 of
   4 BUYs blocked.
* `tests/data_continuity/test_phase8_session_trend.py` —
   state-machine establishment tests use the direct-state helper
   from v1 (unchanged by v2).

**BB-Bounce worktree** `/home/autobot/bb-bounce-wt/session-trend-20261013`
branch `feat/nms-session-trend-guard-20261013`:

* No changes required. `session_trend_guard.py` reads the v2
   snapshot without modification. 10/10 integration tests pass.

**Live tree (never touched):** `/opt/tradingbot`, `/opt/bb_bounce`.
No services restarted. No `.env` edited. No IG orders.

---

## 7. Acceptance checklist (operator)

Against the acceptance criteria you set:

- [x] **Early recognition of genuine strong trends** — Oct 12
      DOWN at 09:50 UTC (previously 14:20); 09-01, 10-01, 10-07
      all recognised before 09:00 UTC; 09-10, 09-23, 09-24 within
      the morning session; 09-16 later (16:40) due to compressed
      structural evidence.
- [ ] **No unnecessary restrictions on RANGE days** — 2 of 9 RANGE
      days fire DOWN wrongly (09-09, 09-11); the other 7 stay
      RANGE/UNKNOWN. See §4.1 for mitigation discussion.
- [ ] **No unnecessary restrictions on NORMAL days** — 2 of 7
      NORMAL days fire wrongly (09-04 DOWN, 09-28 UP). See §4.1.
- [x] **Direction retained through consolidation** — Oct 12 held
      DOWN from 09:50 through 20:25 evening close.
- [x] **Genuine reversals correctly recognised** — 09-15 flip
      eliminated (day stays UNKNOWN); 09-18 wrong-direction fire
      releases to UNKNOWN before EOD.
- [x] **No retrospective classification** — every establishment
      cites evidence present at the fire bar.

**Operator decisions required:**

1. Accept the 4 remaining FPs as unavoidable at fire-moment
   (§4.1 displacement-decay soft release deferred)?
2. Approve merge of the dev branches?
3. Instruct deployment steps (set `BB_BOUNCE_SESSION_TREND_GUARD_
   ENABLED=1`; restart autobot-start + bb-bounce services)?

**No deployment taken.** STOP FOR REVIEW.
