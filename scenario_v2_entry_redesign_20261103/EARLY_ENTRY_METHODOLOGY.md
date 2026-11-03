# Scenario V2 — early-entry methodology

**Status:** DESIGN + IMPLEMENTATION STAGED. **Not deployed.**

> ## ⚠ Updated 2026-11-03 — 2-hour expiry REMOVED
>
> Earlier sections of this document mentioned a 24-M5-bar (2 h)
> expiry for A/B/C setups. Per operator directive 2026-11-03, there
> is **no post-entry time-based close**. Once an order opens the
> broker's attached stop/target governs the exit entirely. The
> `DEFAULT_EXPIRY_BARS` constant and `expiry_bars` field have been
> removed from the derivation module.
>
> The `DEFAULT_LOOKBACK_SECONDS = 7200` (2 h) **PRE-ENTRY** cap
> remains — it bounds how far back the derivation looks for a
> trigger bar BEFORE any order is placed, and never closes a live
> position.
>
> Backtest numbers in this doc are superseded by the no-expiry
> re-run in `FINAL_REVIEW_V2.md` §3.

## 1. Scope reminder

- V2's directional reasoning: UNCHANGED.
- Entry trigger, stop placement, target eligibility: CO-DESIGNED
  from the setup's own invalidation structure.
- Setup expires after 2 h / 24 M5 bars if neither target nor stop
  is hit.

## 2. Setup definitions

Each setup is a **mechanical rule** operating on M5 bar data +
V2's `direction` and `target_price`. V2's `stop_price` is read
only as a HARD safety ceiling: if any pre-entry bar touches it,
the setup is abandoned (`SETUP_INVALIDATED_PRE_ENTRY`).

### 2.1 Mechanism A — momentum impulse continuation

**Pre-context (at scenario-gen):**
- `med_range_10` = median (high − low) of the last 10 completed
  M5 bars.

**Entry (BUY):**
Enter at the close of the first post-gen M5 bar for which ALL
hold:
- `close > open` (bullish body)
- `(high − low) ≥ 1.5 × med_range_10` (expanded range)
- `(close − low) / (high − low) ≥ 0.60` (close is in upper 40 %
  of the range — not a doji, not a shooting star)
- V2's stop has not been touched by this bar or any earlier
  post-gen bar.

**Entry (SELL):** mirror — bearish body, close in lower 40 %.

**Stop:** `impulse_bar.low − 1 p` (BUY) / `impulse_bar.high + 1 p`
(SELL). The 1 p buffer accounts for pip-granularity noise and
spread at entry.

**Target:** V2's `trade_proposal.target_price` (preserved).

**Expiry:** 24 M5 bars (2 h) after entry if neither target nor
stop hit. Exit at the expiry bar's close.

**Rationale:** classic momentum entry. The impulse bar's low (BUY)
has already been rejected by the move — if price returns to it the
momentum thesis is wrong, and we're out quickly for a small loss.

### 2.2 Mechanism B — pullback and rejection

**Pre-context (at scenario-gen):**
- `decision_price` = close of the last completed bar at scenario-gen.

**Setup identification (BUY):**
1. Collect post-gen bars whose close < `decision_price` as
   `pullback_bars`.
2. On the first bar whose close > `decision_price` AND
   `low > min(pb.low for pb in pullback_bars)` (higher-low
   formation), fire.
3. If `len(pullback_bars) > 6`, abort (pullback too long —
   setup void).
4. If V2's stop is touched during pullback, abort
   `SETUP_INVALIDATED_PRE_ENTRY`.

**Entry (BUY):** close of the rejection bar.

**Stop:** `min(pullback_bars.low) − 2 p` (BUY) /
`max(pullback_bars.high) + 2 p` (SELL). The 2 p buffer is wider
than A's 1 p because pullback lows are more exposed to noise.

**Target + expiry:** same as A.

**Rationale:** entering after a confirmed higher-low gives a
better entry than the breakout, with a stop placed just below
the pullback trough.

### 2.3 Mechanism C — early structural continuation

**Setup identification (BUY):**
Walk post-gen bars in 3-bar windows `(a, b, c)`:
1. `a.high ≥ b.high` (local peak at `a`).
2. `b.low < a.low AND b.low < c.low` (local trough at `b`).
3. `c.close > a.high` (continuation break).
Fire at `c.close`. Stop: `b.low − 2 p`. Target + expiry: as above.

**Rationale:** this is the earliest objective higher-high
structural confirmation of a BUY move. Stop at the trough is a
textbook invalidation.

## 3. Explicit non-rules

- **No arbitrary fixed-pip stops.** Every stop above is derived
  from a specific bar feature.
- **No stop-tightening to manufacture R:R.** The buffers (1 p / 2 p)
  are small and documented.
- **No stop-widening to avoid historical losses.** Stops sit at the
  mechanical invalidation; if the move invalidates, the trade loses
  a measurable, small pip count.
- **No target drift.** V2's target is used as-is. If the market
  structure makes the target impossible, the opp-quality gate (now
  part of the AI's own publication logic) refuses to publish.
- **No chase-the-price.** Pullback bars are bounded (≤ 6) and
  expiry caps setup life at 2 h.

## 4. Setup/direction compatibility

| Setup | BUY | SELL | Why |
|---|---|---|---|
| A momentum | ✓ | ✓ | Symmetrical — bullish/bearish impulse |
| B pullback | ✓ | ✓ | Symmetrical — higher-low / lower-high |
| C structural | ✓ | ✓ | Symmetrical — local peak+trough patterns |

## 5. Why Mechanism A is the recommended primary

Backtest headline on n = 13 (details in
`HISTORICAL_COMPARISON.md`):

| Mechanism | Fills | Win % | Net pips | Avg Win | Avg Loss | MDD | PF | R:R at entry |
|---|---|---|---|---|---|---|---|---|
| M1 baseline | 10 | 40.0 | **−55.0** | +20.3 | −21.0 | **−105.3** | 0.65 | 0.62 |
| **A momentum** | **13** | 16.7 | **−17.4** | **+35.0** | **−9.1** | **−40** | 0.77 | **3.53** |
| B pullback | 7 | 0.0 | −44.8 | — | −13.7 | −41 | 0.00 | 1.88 |
| C structural | 4 | 0.0 | −25.0 | — | −11.6 | −23 | 0.00 | 2.4 |

**A is the only mechanism that improves every risk-adjusted metric
over M1**:

- Fires every scenario (no "wait" states).
- Average loss is less than half M1's.
- Max drawdown is roughly a third of M1's.
- Realised R:R at entry is 5-6× M1's.
- Average winner is 1.7× M1's.

A is still net-negative on this sample. B and C both have 0 %
win rates — pullback and structural-continuation setups require
a specific market pattern that the n = 13 sample does not
provide enough of.

**Operator decision point:** deploy A to IG DEMO as a
data-accumulation exercise with better geometry than M1.
`HISTORICAL_COMPARISON.md` has the DEV / VAL split.

## 6. Interaction with V2's publication gate

The AI reasoner's prompt is extended (see
`IMPLEMENTATION.patch`) to allow emitting `setup_type` ∈
`{"BREAKOUT", "MOMENTUM_IMPULSE", "PULLBACK_REJECTION",
"EARLY_STRUCTURAL"}`. For non-BREAKOUT setup types the AI must
also supply:

- `invalidation_reference`: the specific M5 bar whose low/high
  the stop sits below/above (e.g. "last impulse bar at HH:MM").
- `expiry_bars`: default 24 (2 h).

The publication validator (`scenario_quality.py`) is extended to:

- Allow non-breakout `trigger_spec` types without flagging them as
  "CATEGORY_A_WITHOUT_BREAK_TRIGGER".
- Still require direction-correct geometry.
- Reject if `setup_type` is not one of the known enum values.

If the AI emits `setup_type=BREAKOUT`, behaviour is **exactly
unchanged from today**. The redesign is **additive**: new setup
types are available; the old one still works.

## 7. Executor path

The deployed shadow executor (`shadow_execution.py`) is NOT
modified. The new executor (`v2_demo_executor.py`) reads scenarios,
calls the mechanical setup-derivation module
(`v2_early_setup.derive`) for setup types A/B/C, and submits a
single DEMO order via `trade_executor.execute_trade` with
`strategy="SCENARIO_V2_L"` / `SCENARIO_V2_S"`. The stop + target
are the derived values, not V2's own.

For `setup_type=BREAKOUT` (today's default) the new executor still
honours the AI's own `entry_price` / `stop_price` / `target_price`
unchanged.
