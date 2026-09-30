# MPP fix v2 — parameter sweep + adversarial validation

Per user instruction: validate the v2 design (time gate + per-regime
floor_pct) against historical data BEFORE committing. The +30p-over-OLD
ship gate is the decision criterion.

**Recommendation: DO NOT COMMIT. Revert working copy. Surface findings.**

Best v2 combination is +26.2p over OLD under best-case ordering (3.8p
short of ship gate), or −18.8p under worst-case ordering. The 30-day
sample is too small and too volatility-conditioned to clear the bar
with confidence.

---

## Sweep results — 12 combinations

Per-cell columns: `net_pnl` (total over 14 trades), `winners` (TP1
hits), `retrace` (MPP_NEW closes at retrace), `reversals` (SL or
MAX_HOLD where new < old).

### Pessimistic ordering (SL fires first when both SL+TP touch same candle)

| window_s | news_pct | net_pnl | winners | retrace | reversals | delta_vs_OLD |
|---:|---:|---:|---:|---:|---:|---:|
| 300 | 0.75 | 104.8 | 5 | 5 | 2 | **−18.8** |
| 600 | 0.75 | 104.8 | 5 | 5 | 2 | −18.8 |
| 900 | 0.75 | 104.8 | 5 | 5 | 2 | −18.8 |
| 300 | 0.6  | 101.2 | 5 | 5 | 2 | −22.4 |
| 600 | 0.6  | 101.2 | 5 | 5 | 2 | −22.4 |
| 900 | 0.6  | 101.2 | 5 | 5 | 2 | −22.4 |
| 300 | 0.5  |  98.8 | 5 | 5 | 2 | −24.8 |
| 600 | 0.5  |  98.8 | 5 | 5 | 2 | −24.8 |
| 900 | 0.5  |  98.8 | 5 | 5 | 2 | −24.8 |
| 300 | 0.85 |  97.8 | 4 | 6 | 2 | −25.8 |
| 600 | 0.85 |  97.8 | 4 | 6 | 2 | −25.8 |
| 900 | 0.85 |  97.8 | 4 | 6 | 2 | −25.8 |

### Optimistic ordering (TP fires first when both SL+TP touch same candle)

| window_s | news_pct | net_pnl | winners | retrace | reversals | delta_vs_OLD |
|---:|---:|---:|---:|---:|---:|---:|
| 300 | 0.75 | **149.8** | 6 | 5 | 1 | **+26.2** |
| 600 | 0.75 | 149.8 | 6 | 5 | 1 | +26.2 |
| 900 | 0.75 | 149.8 | 6 | 5 | 1 | +26.2 |
| 300 | 0.6  | 146.2 | 6 | 5 | 1 | +22.6 |
| 600 | 0.6  | 146.2 | 6 | 5 | 1 | +22.6 |
| 900 | 0.6  | 146.2 | 6 | 5 | 1 | +22.6 |
| 300 | 0.5  | 143.8 | 6 | 5 | 1 | +20.2 |
| 600 | 0.5  | 143.8 | 6 | 5 | 1 | +20.2 |
| 900 | 0.5  | 143.8 | 6 | 5 | 1 | +20.2 |
| 300 | 0.85 | 142.8 | 5 | 6 | 1 | +19.2 |
| 600 | 0.85 | 142.8 | 5 | 6 | 1 | +19.2 |
| 900 | 0.85 | 142.8 | 5 | 6 | 1 | +19.2 |

OLD baseline: +123.6p over the 14 trades.

### Key observations from the sweep

1. **The time gate adds zero value.** All three window sizes (300/600/900s)
   produce IDENTICAL results in every row. The historical OLD MPP
   closes happened at median age ≈ 26 minutes — well past any candidate
   gate. The hypothesis "time gate filters fast-reverser trades" is
   empirically wrong on this sample. The two reversal trades that
   inspired the hypothesis closed at 13s and 35min — the 13s trade WAS
   fast but my simulation's pessimistic-ordering result for it was an
   artefact (see below).
2. **`news_pct = 0.75` is the best pure-MPP setting** under either
   ordering. Trades closer to the lock_armed trigger get tighter
   give-back room while still beating the instant-close bug.
3. **Pessimistic and optimistic orderings disagree by ~45p net.** That
   spread is the irreducible uncertainty from candle-level simulation:
   when SL and TP touch the same candle, OHLC doesn't reveal the path.
   The honest answer is somewhere in the middle.

---

## Winning combination

`window=300, news_pct=0.75` (chosen for tightest floor, no time gate).

Per-trade results — OPTIMISTIC ordering (best-case for new logic):

```
  open_ts              pair     dir   reg     flr  oldPnL  newPnL  reason
  ---------------------------------------------------------------------------
  2026-04-27T06:50:02  USDJPY   SELL  DEFAULT 20.0   +9.6   +15.3  MAX_HOLD
  2026-04-27T07:05:02  EURUSD   BUY   DEFAULT 20.0   +9.7   +10.2  MAX_HOLD
  2026-05-01T06:40:01  USDJPY   SELL  NEWS     6.0   +8.1   +15.7  TP1
  2026-05-01T06:50:01  USDJPY   SELL  DEFAULT 20.0   +2.6   +20.0  TP1
  2026-05-01T06:55:00  USDJPY   SELL  NEWS     6.0   +8.0   +20.0  TP1  ← path-dependent
  2026-05-01T12:05:11  USDCAD   SELL  NEWS     6.0   +8.0    +5.8  MPP_NEW
  2026-05-04T15:20:50  GBPUSD   SELL  SWEEP    6.0  +12.2    +5.8  MPP_NEW
  2026-05-06T08:25:19  GBPUSD   BUY   SWEEP    6.0  +12.1   +15.9  TP1
  2026-05-07T12:20:35  USDCAD   BUY   SWEEP    6.0  +11.9    +5.8  MPP_NEW
  2026-05-08T13:20:01  GBPUSD   BUY   NEWS     6.0   +8.6    +9.5  TP1
  2026-05-08T15:30:54  GBPUSD   BUY   NEWS     6.0   +8.1    −1.5  MAX_HOLD ← reversal
  2026-05-11T13:10:03  GBPUSD   BUY   NEWS     6.0   +8.1    +5.8  MPP_NEW
  2026-05-12T06:25:03  GBPUSD   SELL  NEWS     6.0   +8.2   +15.9  TP1     ← today's 3CO
  2026-05-12T11:00:04  GBPUSD   SELL  NEWS     6.0   +8.4    +5.8  MPP_NEW
  ---------------------------------------------------------------------------
  Total:                                            +123.6  +149.8
  Delta:                                                    +26.2p (FAIL +30p gate)
```

Pessimistic ordering same combination:
- 2026-05-01T06:55:00 USDJPY collapses from +20.0 (TP1) to −25.0 (SL) → net swings to +104.8p, delta −18.8p.

---

## Adversarial checks on the winning combination (optimistic best)

### Check 1 — drop today's 3CO

Today's 3CO is the trade whose audit triggered this whole investigation.
If the fix's gains depend disproportionately on it, the win is fragile.

| Sample | OLD | NEW | Delta |
|---|---:|---:|---:|
| Full 14 trades | +123.6 | +149.8 | +26.2 |
| Without today's 3CO | +115.4 | +133.9 | +18.5 |

**Today's 3CO contributes +7.7p to the +26.2 delta.** Without it the
fix is +18.5p over OLD — still positive under optimistic, but further
from the +30p ship gate. Not a fatal dependency, but the fix's case
weakens.

### Check 2 — split by date

The 30-day sample spans 2026-04-27 to 2026-05-12. Does the fix work on
both halves?

| Period | n | OLD | NEW | Delta |
|---|---:|---:|---:|---:|
| 2026-04 | 2 | +19.3 | +25.5 | +6.2 |
| 2026-05 | 12 | +104.3 | +124.3 | +20.0 |

Under optimistic ordering, both periods are positive. Under pessimistic
ordering: April +6.2p, May −25.0p (reverses sign). Under realistic
mid-case ordering, the May contribution shrinks substantially.

### Check 3 — the path-dependence problem

The +45p spread between pessimistic and optimistic comes almost
entirely from one trade: **2026-05-01T06:55:00 USDJPY SELL**. That
trade opened during the BoJ CPI release; the 06:55 5M candle had a
50p high-low range that touched BOTH the +20p TP1 AND the −25p SL in
the same 5M window. Path determines outcome.

- OLD: closed at +8 via MPP after 13 seconds (the OLD bug fired before
  either extreme was reached).
- NEW pessimistic (SL-first): trade hits SL at −25.
- NEW optimistic (TP-first): trade hits TP1 at +20.
- Reality (per the candle's close = 15597.15, near the high): price
  almost certainly went DOWN first (favorable side) to the low
  15549.25, then UP through the high. So **TP1-first is probably
  correct for this trade**.

But "probably correct" is not the same as "verified." Without
tick-level data, I can't confirm. If this is a CPI/BoJ news day pattern
(price spikes through both levels intra-candle), the assumption could
fail on a different news event. **The single trade carries 33p of
delta uncertainty in a sample of 14.**

### Check 4 — reversal cases under the winning combination

Under optimistic ordering, 1 reversal remains:
- 2026-05-08T15:30:54 GBPUSD BUY: OLD +8.1 (MPP-clipped) → NEW −1.5 (MAX_HOLD).
  Best pnl in simulation = +5.5 — never reached trigger 8 under my
  candle simulation, so MPP never armed. Trade aged out at max_hold
  expiry. The OLD record claims pnl=+8.1 with mfe=3.9 (lower than pnl
  — this signal_log record is internally inconsistent; likely a
  pre-2A instrumentation gap).

Net adversarial verdict: the optimistic +26.2p delta is **not robust**.
Drop the highest-volatility news-day trade and we're at +6.2p in April.
Add pessimistic ordering for that one trade and we go from +26.2 to
−18.8.

---

## Decision

User's ship gate from the spec:
> If the winning combination passes adversarial checks AND beats OLD by
> 30+ pips: commit. If it doesn't: revert, surface findings, we discuss
> other options.

| Criterion | Result |
|---|---|
| Best v2 (optimistic) ≥ OLD + 30 | **+26.2p — FAIL** (3.8p short) |
| Best v2 (pessimistic) ≥ OLD + 30 | **−18.8p — FAIL** (wrong sign) |
| Adversarial: works without today's 3CO | +18.5p — partial (less than +30) |
| Adversarial: split by date | +6.2 (Apr) / +20.0 (May) under optimistic — OK |
| Path-dependence | One trade swings the result by 45p across orderings |

**Recommendation: REVERT working copy. Do not ship.**

The fix is mathematically positive under optimistic conditions but
fails the +30p gate, and the result is dominated by intra-candle path
assumptions on a single high-volatility news trade. The 30-day sample
is too small and too event-conditioned (3 of 14 trades were on
2026-05-01, the CPI day, and 2 more on 2026-05-12, today's CPI day) to
clear the bar.

---

## Other options simulated (for reference)

### Option 2: scrap MPP for non-tight strategies entirely

Adds 3CO and GBPUSD_TREND_CONT_L/S to the existing exemption list (which
already exempts NEWS_TICK, NEWS_STRATEGY, RAW_REVERSAL, BB_BOUNCE,
BB_REV_PAT). MPP simply doesn't close these strategies.

- Optimistic ordering: NEW +128.5p vs OLD +123.6p = +4.9p delta — FAIL.
- Pessimistic ordering: NEW +83.5p vs OLD +123.6p = −40.1p delta — FAIL.

Outcomes under optimistic: 7 MAX_HOLD / 6 TP1 / 1 SL. The MAX_HOLD
category is the killer — many trades that OLD-MPP clipped at +8/+12 would,
without MPP, age out 60-240 min later at small positive or small
negative pnl. Worse than the OLD clip.

### Summary across all options simulated

| Option | Pessimistic | Optimistic |
|---|---:|---:|
| OLD (the bug) | +123.6 | +123.6 |
| V1 (floor scaling, no time gate) | −40.9 | (not run, similar) |
| V2 (best: 300/0.75) | −18.8 | +26.2 |
| Option 2 (scrap MPP for non-tight) | −40.1 | +4.9 |
| Ship gate (+30 over OLD = +153.6) | none pass | none pass |

---

## What we've learned

1. **The OLD bug was accidentally protective on news-day reversals.**
   The "MPP clipped at peak" framing is true on calm-day trends but
   incomplete on news-day spike-and-reverse patterns. The same instant
   close-on-arm that we're calling a bug saved a −25p loss on
   2026-05-01 USDJPY.

2. **A 30-day, 14-trade sample is too small to validate exit logic.**
   Path-dependence on news days creates ±45p of irreducible uncertainty
   in 5M candle simulation. To actually validate this fix would need
   tick-level data + a longer sample (90+ days).

3. **The structural bug is real but the cure is worse than the
   disease.** The bug clips peak winners. But the bug also exits weak
   trades before they reverse to SL. Net is positive on the historical
   sample because the saved-SL trades are larger magnitude than the
   clipped winners.

4. **Per-strategy exemption (the audit's option 4) is a bandaid that
   removes the safety net for those strategies — same simulated
   outcome as option 2.** Doesn't help.

---

## What to discuss next

Options that the simulation didn't test but might be worth designing:

1. **Tighter trigger, not looser floor.** Lower the regime trigger
   (e.g. NEWS=6 instead of 8) so MPP arms earlier and the give-back
   tolerance is naturally smaller. Counter-intuitive but might match
   the actual price action better.

2. **Momentum-based exit.** Replace "retrace through floor" with
   "N consecutive bars without new extreme + close at current pnl."
   Doesn't help news-day reversals (they happen on a single bar).

3. **Post-TP1 trailing only.** Disable MPP until TP1 is hit. After
   TP1 is hit, switch to a trail to lock in the TP1 minimum. Doesn't
   help here because all 14 trades closed BEFORE TP1 — they're the
   ones that never reached the first target.

4. **Accept the bug for high-news regimes.** Keep OLD behaviour for
   NEWS regime (where it's accidentally protective) but fix it for
   SWEEP/TREND (where the bug is more clearly pathological). The
   30-day sample shows mostly NEWS-regime trades, which is exactly
   the cohort where OLD wins.

5. **No fix.** The bug costs us some peak captures but protects from
   reversals. Net over 30d: +123.6p. The cost of the bug is the gap
   to a theoretical "perfect exit" — which we'd need a much larger
   sample to estimate.

I lean toward option 4 (keep OLD for NEWS, fix for SWEEP/TREND) or
option 5 (no fix; close the audit with "the bug is load-bearing").
But this is a strategic decision, not a refactor decision. Surface
for the next session.

---

## Files to revert (NOT committed)

```
M trade_manager.py                       # the proposed fix
M .gitignore                              # allowlist entry
A tests/unit/test_mpp_floor_invariant.py  # 13 tests
A docs/mpp_floor_fix_simulation_2026-05-12.md       # prior v1 report
A docs/mpp_floor_fix_v2_simulation_2026-05-12.md    # this file
```

Working copy will be reverted to last committed state (`5772574`) after
your direction. The audit doc (`manager_profit_protect_audit_2026-05-12.md`)
remains — it correctly identified the structural bug; the fix-design
challenge is the unresolved follow-up.
