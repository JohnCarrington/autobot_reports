# Scenario V2 entry-delay — root cause analysis

**Scope:** READ-ONLY investigation. No production files modified.

**Companion deliverables:** `EARLY_ENTRY_DESIGN.md`,
`ENTRY_METHOD_COMPARISON.md`, `BACKTEST_RESULTS.csv`,
`EARLY_ENTRY_IMPLEMENTATION.patch`, `DEPLOYMENT_READINESS.md`.

---

## 1. Executive conclusion

Scenario V2's entry delay is **not an executor bug**. It is encoded in
the reasoner's **prompt** and reinforced by the recommendation
**narrative parser**:

- The AI is explicitly instructed to express every actionable entry as
  a **breakout trigger** (`"break above / below <level>"` or
  equivalent).
- The narrative parser accepts an `entry_price` ONLY when the
  surrounding text contains the mandatory breakout phrase.
- There is **no alternative "fire at scenario-gen market" path**.

The executor then opens on the first M5 close beyond that breakout
trigger — faithfully, as designed. The 12.9-pip median
price-to-entry distance at first-READY is the AI's own choice,
mechanically transmitted through to the fill.

**Operator directive constraints:** we must preserve V2's reasoning,
directional prediction, scenario quality and NMS integration. We
cannot touch the prompt or parser. Therefore the only legitimate
intervention point is a **new, parallel executor path** that
re-interprets the proposal: use `direction`, `stop`, `target`,
`publication_decision`, `scenario.state`, and `scenario.generated_at_utc`
exactly as V2 emits them, but **replace the entry trigger** with an
alternative fill rule that captures more of the predicted movement.

Everything that follows in the companion documents is a direct
consequence of this constraint.

---

## 2. The three sites that enforce breakout entries

### 2.1 Reasoner prompt (`scenario_reasoner.py`)

- Lines 211-214 — Category A definition:
  ```
  "A. TECHNICAL — the entry trigger is a pure price-structure
  condition (close above / below a named level, break of a swing,
  retest of a pivot, acceptance beyond a BB, holding of a session
  high) and depends on NO economic event."
  ```
- Lines 260-274 — TRIGGER_SPEC rule 5d:
  ```
  "`price_break_above` (bar close >= `level_price`),
   `price_break_below` (bar close <= `level_price`)"
  ```

Every example and allowed `trigger_spec` enum requires a
breakout-level entry. There is no "enter at current close" trigger
type.

### 2.2 Narrative parser (`scenario_recommendation.py`)

Function `_extract_entry_price_from_text` at L388-445 accepts an
entry price ONLY if the surrounding text contains one of:

- `breaks? below` / `closes? below` / `<=` / `<` (SELL)
- `breaks? above` / `closes? above` / `>=` / `>` (BUY)

A free numeric price without one of those trigger phrases is
rejected. Scenarios whose `trade_proposal.entry_price` is at or near
current market will not survive this parser unless the AI explicitly
re-expresses them as a breakout — which the prompt steers it away
from.

### 2.3 Geometry validator (`scenario_quality.py`)

`_validate_structured_trade_proposal` (around L1041-1059) checks
`stop < entry < target` (BUY) / `stop > entry > target` (SELL). It
does **NOT** compare `entry_price` to current market close. So the
validator alone does not force breakout semantics — the enforcement
happens in parser and prompt.

### 2.4 (Non-active) trigger evaluator stale-entry suppressor

Prior research surfaced `trigger_evaluator.py` with
`entry_tolerance_pts = 8` — a stale-entry suppressor if price has
moved more than 8 pips past a breakout level. Not currently wired
into the deployed executor (`shadow_execution.py` opens on first
close beyond entry regardless of how far price has already moved).

---

## 3. Why the executor's close-above-entry rule is NOT the main
delay source

The deployed executor's rule is already the "earliest reliable
breakout trigger": first M5 bar whose close is strictly beyond the
entry level in the proposed direction, no further confirmation. The
delay is dominated by:

1. The AI placing `entry_price` ~13 pips beyond market (median,
   p2e > 0 for 10/14 actionable scenarios).
2. Market needing to actually traverse those ~13 pips while remaining
   above the stop for the entire time.

Replacing "close above entry" with "high touches entry" would gain
~1 bar in some cases but increase false-fill rate. Not a cheap win.

---

## 4. The only legitimate intervention surface

Given the operator constraints:

- Cannot modify prompt (preserves V2 reasoning).
- Cannot modify parser (same).
- Cannot modify scenario_quality (same).
- Cannot touch NMS or other strategies.

**The valid surface is: a new, parallel executor path** that
subscribes to the same scenarios + direction + stop + target
emitted by V2 but applies its OWN entry rule. Specifically:

- Take `scenario.generated_at_utc` as the decision time (same as the
  deployed executor's lookahead anchor).
- Take `direction`, `stop_price`, `target_price` as authoritative
  (V2's directional and risk-management choices preserved).
- Take `entry_price` ONLY as a reference (the breakout level the AI
  would have waited for) — but do NOT use it as the fill trigger.
- Apply one of:
  - A. **Early directional entry** — fill at scenario-gen bar close
    (closest-to-decision price available on M5 stream).
  - B. **Pullback entry** — wait for one controlled pullback, then
    enter on the next in-direction close.
  - C. **Earlier breakout** — refine the breakout entry (effectively
    a no-op; see §3).
- Apply an **opportunity-quality gate** at decision time that rejects
  the fill if the net reward-to-risk after model spread falls below
  a threshold, or the predicted move is already substantially
  consumed.

Preserving `direction / stop / target / publication / state` means we
inherit V2's protection: no reversal, no NMS override, no CAUTION-to-
READY promotion, no scenario-lifecycle violation.

The entry-level drift problem is **not solved** by this — it's bypassed.
The AI will continue proposing breakout entries; the parallel executor
simply doesn't wait for them.

---

## 5. Separate concern — pips_consumed grows with p2e

A trade geometry fact worth stating up front: the AI's target is
usually `SWING_H`/`SWING_L` or similar — the next structural level in
the predicted direction. If the entry is placed near the midpoint
between current price and target, then by the time price "triggers"
the breakout the AI itself proposed, roughly HALF the reward is
already gone. This is independent of the executor; it is the direct
consequence of structural targets + structural breakout entries.

A good early-entry mechanism will capture most of the move only if
the directional reasoning is right. **If V2's direction is wrong,
early entry just takes the loss sooner.** The backtest in
`BACKTEST_RESULTS.csv` reports both outcomes separately.

---

## 6. What this does and does not promise

**Delivers:**
- A design that opens positions earlier when V2's reasoner issues
  READY recommendations.
- A quality gate that rejects proposals with no profitable room
  remaining after spread.
- A parallel-shadow comparison harness so earlier-entry fills can
  be audited against the existing executor.

**Does not deliver:**
- A fix to V2's underlying tendency to propose breakout entries.
- A guarantee of profitability — only four scenarios in the research
  sample had R:R ≥ 1.0 and the sample as a whole has been
  net-negative.
- Any live-execution path.

The entry-level drift question is best addressed by a separate
investigation into the reasoner prompt (not authorised here).
