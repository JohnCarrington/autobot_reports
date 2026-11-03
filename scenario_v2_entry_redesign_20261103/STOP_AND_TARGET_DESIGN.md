# Scenario V2 — stop and target design

## 1. Stops: derived from the setup, not inherited from the breakout

The deployed executor fires on a close beyond V2's `entry_price`
(breakout trigger) and uses V2's `stop_price` (structural swing
level). The previous "early-entry" study showed that reusing the
breakout stop with an earlier entry breaks the risk geometry.

The redesign derives the stop **per setup**:

| Setup | Stop location | Buffer | Rationale |
|---|---|---|---|
| M1 breakout (preserved) | V2's `stop_price` (swing-level) | 0 | V2's own invalidation |
| **A momentum impulse** | Impulse bar's low (BUY) / high (SELL) | 1 p | Impulse-bar extreme defines the rejection the entry is confirming |
| **B pullback + rejection** | Pullback trough low (BUY) / high (SELL) | 2 p | Higher-low is the actual invalidation |
| **C early structural** | Local trough low (BUY) / high (SELL) | 2 p | Trough that formed the higher-high is the invalidation |

**Buffers are small (1-2 p)** because the extremes being guarded
are themselves already near the setup's confirmation point. A
wider buffer would mean the setup fires on a bar whose own
geometry already overlaps the stop level — rejection of own
premise.

### 1.1 Pre-entry safety ceiling

Across A/B/C, if ANY pre-entry bar touches V2's own `stop_price`
(the structural swing), the setup is abandoned
(`SETUP_INVALIDATED_PRE_ENTRY`). This is a hard rule — the
mechanical stop is TIGHTER than V2's structural stop, so if the
structural stop is touched, the trade's premise is already dead.

### 1.2 IG minimum stop distance

The implementation (`impl/v2_demo_executor.py`) consults
`ig_dealing_rules.is_known_too_tight(epic, stop_pips)` before
submitting. Mechanism A's buffered impulse-bar stop can be as
tight as 3-5 p for narrow-range bars; IG's current GBP/USD
minimum has historically been 4-6 p and is cached dynamically on
rejection. When the gated stop is too tight the executor skips
the trade; the AI's own structural stop would also likely fail
on the same bar.

## 2. Targets: V2's structural target preserved

V2's `trade_proposal.target_price` is **preserved as-is** for all
setups. The AI's directional reasoning placed the target at a
structural level; moving it would be modifying V2's reasoning,
which the brief forbids.

For every setup A/B/C the mechanical reward-at-entry is:

```
reward_pips = (target − sim_entry) × sign(direction)
```

Because A/B/C fire closer to current market than M1's breakout
entry, the reward is **larger per trade** than M1 (median win
+35 p for A vs +20 p for M1).

### 2.1 Why not change the target rule?

The scope limit is clear: the operator rejected changes to
directional reasoning, which includes target selection. The
exhaustion-check from the previous (rejected) quality gate is
dropped as a formal rule here — the setup definitions in
`EARLY_ENTRY_METHODOLOGY.md` already require that fire be at or
near the setup's natural trigger, not far into the move.

The previous study found V2's targets are often the NEAREST
structural level (SWING_H / BB_U / R00). This remains a strategy-
methodology question (`entry quality follow-up` referenced in
earlier research memory) and is out of scope for this correction.

## 3. Risk-reward at entry — what the backtest actually shows

On the n = 13 sample:

| Mechanism | R:R at entry (median) | AvgLoss | AvgWin | Avg trade |
|---|---|---|---|---|
| M1 baseline | 0.62 | −21.0 | +20.3 | −4.45 |
| **A momentum** | **3.53** | **−9.1** | +35.0 | **−1.3** |
| B pullback | 1.88 | −13.7 | — | −5.9 |
| C structural | 2.4 | −11.6 | — | −6.2 |

**A's R:R at entry is 5-6× M1's.** This is the geometric case for
the redesign: when the setup fires, the trader faces 1 p of risk
for 3.5 p of reward, instead of M1's 1 p of risk for 0.6 p of
reward.

This does NOT mean A is profitable — win rates matter too, and A's
win rate on the sample is 17 % vs M1's 40 %. The lower hit rate
reflects the tight stop catching more pullbacks before the move.
But the loss-per-stop (9.1 p) is less than half M1's (21.0 p), so
A's expected trade is far less negative than M1's.

## 4. Why wider stops do not help

Experimentally confirmed by the previous investigation
(`research/scenario-v2-early-entry-20261103`): if the earlier
entry uses V2's wider breakout stop, the trade carries roughly
the same risk-in-pips as M1 but with less reward left to the
target — strictly worse.

The redesign refuses to widen stops.

## 5. Why tighter stops do not help

A buffer of 0 p (fill right at the impulse-bar's low) would
produce a 0-pip stop in extreme cases, which IG rejects outright.
The 1-2 p buffer is **minimum viable** without routinely failing
pre-submit guards.

Buffers above 3 p degenerate into "near-structural" stops and
converge toward M1's behaviour; the test on this sample has not
been run, but by design that converges toward M1's known
behaviour.

## 6. Expiry

All non-breakout setups expire 24 M5 bars (2 h) after entry if
neither target nor stop is hit. Exit at the expiry bar's close.

**Rationale:** if the predicted move has not materialised within
2 hours, the setup's thesis is stale. Carrying a shadow or DEMO
position overnight for a 2-hour-horizon setup is operational
risk without edge support.

M1 has no explicit expiry — the deployed executor monitors
indefinitely. A/B/C add expiry because their time horizon is
operationally shorter.

## 7. Open operator decisions

1. **Target-selection methodology.** Out of scope here. Flagged
   for a separate investigation. Preliminary research (`entry
   quality follow-up`) suggested V2 pins to the nearest level
   too often; this correction does not change that.
2. **Buffer size.** 1 p (A) and 2 p (B/C) chosen as minimum
   viable. Operator may override via a per-call parameter in
   `v2_early_setup.derive`; defaults are documented module-level
   constants.
3. **Expiry duration.** 2 h = 24 M5 bars default. Operator may
   adjust via `V2_SETUP_EXPIRY_BARS` env var at activation time.
4. **DEMO sizing.** Covered in `IG_DEMO_INTEGRATION.md`.
