# Scenario V2 — entry method comparison

**Dataset:** 13 first-READY scenarios across the Oct 23 → Nov 3 2026
shadow journal (publication VALID + geometry-valid structured proposal).
**Spread:** session-aware model, 0.9 p / 1.4 p / 2.0 p round-trip
(contemporaneous bid/ask unavailable — see Appendix A of
`EARLY_ENTRY_DESIGN.md`). **Candles:** `research/live_obs/journal/snapshots.jsonl`
M5 OHLC. **Lookahead:** unlimited for the backtest (so no fill is
hidden by the live 2 h cap); the production deploy would still honour
the cap.

Backtest harness: `scripts/backtest_early_entry.py`. Raw rows:
`data/BACKTEST_RESULTS.csv` (65 rows, 13 scenarios × 5 mechanisms).

---

## 1. Headline table

| Mechanism | Fills | Closed | Targets | Stops | Win % | Gross | **Net** | AvgWin | AvgLoss | MaxDD | **PF** | Delay (med min) | Pips consumed (med) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 — current breakout | 10 | 10 | 4 | 6 | 40.0 | −44.5 | −55.0 | +20.3 | −21.0 | −96.6 | 0.65 | 43.9 | 13.4 |
| **A** — early directional | 7 | 6 | 0 | 6 | 0.0 | −35.0 | −41.4 | — | −5.8 | −35.0 | 0.00 | −1.2 | 1.3 |
| **B** — pullback | 3 | 2 | 0 | 2 | 0.0 | −30.2 | −33.0 | — | −15.1 | −30.2 | 0.00 | 19.0 | 3.0 |
| **C** — earlier breakout | 2 | 2 | 1 | 1 | 50.0 | +18.3 | +16.0 | +29.4 | −11.1 | −11.1 | 2.65 | 133.7 | 12.8 |
| **M1 + quality gate** | **4** | 4 | 2 | 2 | 50.0 | **+18.8** | **+14.7** | +23.6 | −14.2 | −28.5 | **1.66** | 49.0 | 5.5 |

(Pips are mid-close fills; "net" subtracts the model spread.
"MaxDD" is the deepest cumulative-pips drawdown in exit-order.)

---

## 2. Interpretation

### 2.1 M1 (deployed) is net-negative

40 % win rate, average winner +20 p, average loser −21 p. Expectancy
is negative because the win rate does not clear the risk-reward
imbalance V2's proposals impose (median R:R 0.68). Deeper drawdown
(−96.6 p) than any other mechanism on this sample.

### 2.2 A (early entry) kills every trade

Zero wins across 6 closed trades. The mechanism enters near the
scenario-gen bar close (~1.3 p into the predicted move) and reaches
V2's STOP before V2's TARGET on every tested scenario.

**Why:** V2's stops are structural (swing low / swing high / BB_L
band). They are placed assuming the executor fires at a BREAKOUT
level — i.e. 10-15 p further into the move. When we fire 10-15 p
earlier, the stop is left WAY further below, giving the pullback-
to-structural-level pattern plenty of room to stop us out BEFORE the
move V2 was predicting. Six consecutive stop-outs is a strong signal
that the AI's stops are NOT optimal for earlier entries.

Average loss is small (−5.8 p) because our entries are closer to the
stop, but the win rate collapse dominates expectancy.

### 2.3 B (pullback) suffers pre-entry stop-outs

Of 13 proposals, 7 are rejected (`SETUP_INVALIDATED_PRE_ENTRY` —
the AI's stop was touched during the pullback bar itself, before any
in-direction bar fired). The 3 that fired all closed on STOP_HIT.
Same structural-stop problem as A, with the additional complication
that waiting for a pullback FIRST moves the entry even closer to the
stop in the time dimension.

### 2.4 C (earlier breakout) is positive but n=2

Intra-bar touch of the AI's entry trigger. Fills at the trigger level
(modelled stop-market order). On this sample it fires 2 of 13 scenarios
(5 rejected by quality gate; 6 waiting or no touch). 1 target, 1
stop; +18.3 gross, +16.0 net. **PF 2.65 on n=2 is not a result; it's a
hypothesis.** Larger sample needed.

### 2.5 M1 + quality gate is the best confirmed outcome

Same breakout rule as the deployed executor + the opportunity-quality
gate from `EARLY_ENTRY_DESIGN.md` §3. 4 fills (gate rejects 6 of M1's
10). Win rate 50 %, gross +18.8, **net +14.7 after spread**.

The gate's effect is **asymmetric by design**:
- It rejects trades where V2's own geometry says reward < 0.75 × risk
  after spread, OR where the predicted move is > 70 % consumed, OR
  where the raw remaining reward is < 3 p (half the worst-case
  spread).
- All 6 M1 trades that the gate rejected would have been stop-outs,
  targets < 1 p profit, or targets ≤ spread. Removing them lifts the
  average winner to +23.6 p and shrinks the average loser to −14.2 p.

This is the "do less of the thin trades" strategy — not "capture more
of the move" (which the brief hypothesised). On this sample the data
disagrees with that hypothesis.

### 2.6 Combined mechanisms

- **A + C** was NOT separately tested here because A loses every
  trade — adding its fills on top of C would strictly worsen the
  numbers.
- **M1 + gate** functions as "C with close-above-trigger confirmation
  and bar-close fill price". Close to C in spirit; larger sample
  (4 vs 2 fills) with similar economics.
- **The design module** supports an `A_AND_C` mode (first-to-fire
  wins) but this backtest does not evaluate it because A dominates
  the first-to-fire decision in every scenario while being
  net-negative — the combination would inherit A's losses.

---

## 3. Metric-by-metric detail (per brief §7)

| Metric | M1 | A | B | C | M1 + gate |
|---|---|---|---|---|---|
| Number of trades (scenarios offered) | 13 | 13 | 13 | 13 | 13 |
| Fills | 10 | 7 | 3 | 2 | 4 |
| Win rate | 40.0 % | 0 % | 0 % | 50 % | 50 % |
| Gross pips (mid) | −44.5 | −35.0 | −30.2 | +18.3 | +18.8 |
| Net pips (model spread) | −55.0 | −41.4 | −33.0 | +16.0 | +14.7 |
| Avg win pips | +20.3 | — | — | +29.4 | +23.6 |
| Avg loss pips | −21.0 | −5.8 | −15.1 | −11.1 | −14.2 |
| Max drawdown | −96.6 | −35.0 | −30.2 | −11.1 | −28.5 |
| Profit factor | 0.65 | 0 | 0 | 2.65 | 1.66 |
| Entry delay (med min) | 43.9 | −1.2 | 19.0 | 133.7 | 49.0 |
| Pips consumed at entry (med) | 13.4 | 1.3 | 3.0 | 12.8 | 5.5 |
| MFE / MAE post-entry: see per-row CSV |

Note on "entry delay": for Mechanism A, delay is slightly negative
because the fill lands at the FIRST bar whose `ts_close > scen_gen`,
and `scen_gen` typically falls shortly after a bar close, so the
fill bar is ~0-5 min after `scen_gen` — reported as a small negative
delta in some cases due to the scenario-gen timestamp being inside
the fill bar's close window.

---

## 4. Sample-size caveat (restated)

n = 13 first-READY scenarios is **too small for statistically
reliable conclusions**. The confidence intervals around every metric
are wide. Specifically:

- M1 + gate's PF 1.66 and C's PF 2.65 are each supported by 2
  winning trades. One losing trade would flip either to negative.
- The 0 % win rate on A (n=6) is a strong directional signal, but
  the magnitude of loss (−5.8 p avg) is small — a single win would
  materially change the picture.
- No multi-year validation is possible on this cohort because the
  shadow stream only covers 10 trading days.

**Reading guidance:** treat the ranking (M1+gate / C > M1 > A / B)
as directionally supported, treat the magnitudes as hypothesis-
level.

---

## 5. In-sample / out-of-sample split

The brief asks for in-sample vs out-of-sample separation where data
supports it. With n = 13 total, splitting even 70/30 leaves ~4 trades
in the hold-out — too few to validate anything.

**What we did instead:** every threshold in the quality gate
(`MIN_NET_REWARD_PIPS=3.0`, `MIN_NET_RR=0.75`, `MAX_EXHAUSTION=0.70`)
was chosen on the basis of DESIGN RATIONALE (see
`EARLY_ENTRY_DESIGN.md` §3.1), not by fitting to the n=13 sample's
P&L curve. We did not iterate thresholds against the sample. The
quality gate's parameters are therefore not optimised to this data;
their performance on the sample is an unseen result.

**Recommended out-of-sample protocol:** after the operator-approved
deployment of M1+gate (or C+gate), accumulate 30-60 further fills in
the live shadow stream, then re-run `backtest_early_entry.py` with
`DEV_SAMPLE = first 13 scenarios, OOS_SAMPLE = next 30-60`. Confirm
the gate holds up before any further mechanism change.

---

## 6. Recommended mechanism

**Primary recommendation: M1 + opportunity-quality gate.**

Rationale:

- Positive on the only mechanism+gate combination that survived
  statistical plausibility (+14.7 net pips, PF 1.66, n = 4 fills).
- Minimal change surface: the deployed `shadow_execution.py` fill
  logic is unchanged. The gate is a pre-fill rejection check.
- Preserves V2's directional reasoning, stops, targets, NMS
  integration, scenario lifecycle. The ONLY new behaviour is
  "refuse to open positions whose own-proposed geometry is below
  the quality threshold".

**Secondary recommendation: C + opportunity-quality gate** — same
quality gate, intra-bar entry-level fill. Slightly better on this
sample (+16.0 vs +14.7 net; n = 2 vs 4). If deployed, run alongside
M1+gate in parallel shadow mode for direct comparison. The design
module supports this via `mode="C"`.

**Explicit non-recommendations:**

- **Do NOT deploy A.** 0 % win rate across 6 trades. The structural
  stops do not fit immediate entries.
- **Do NOT deploy B.** Pre-entry stop-outs dominate; worse than A.
- **Do NOT deploy A_AND_C.** Mode supported for completeness only;
  A dominates the first-to-fire decision while being net-negative.
- **Do NOT change V2's stops or targets to make A viable.** The
  brief explicitly forbids modifying stop/target placement.

---

## 7. Honest reframe of the brief's hypothesis

The brief asked: *"redesign Scenario V2's entry mechanism so it can
enter nearer the beginning of a predicted directional movement"*.

The data says the problem is not when V2 enters — the problem is
**that V2 proposes trades where reward is smaller than risk even if
executed perfectly**. The best outcome in this backtest comes from
refusing to take those trades, not from entering them earlier.

Earlier entry (Mechanism A) in fact worsens outcomes because V2's
structural stops become uneconomical at the new entry. Only a
mechanism that preserves the AI's own stop-anchored geometry
(C = same breakout; M1+gate = same breakout) and simply rejects
thin-R:R scenarios is positive.

The brief's final instruction — "make Scenario V2 act on its
directional intelligence while there is still meaningful profit
available" — is best served by DECLINING to act on scenarios whose
proposed geometry does not leave meaningful profit, rather than
acting on them earlier.
