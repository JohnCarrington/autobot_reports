# Scenario V2 — early-entry mechanism design

**Status:** DESIGN ONLY. Implementation in `impl/early_entry.py`; shadow
comparison harness in `scripts/shadow_compare.py`. **No production
files modified.** No deployment authorised.

**Preserved invariants** (from the operator brief):

- V2 reasoner, scenario quality assessment, publication gate and NMS
  integration unchanged.
- No reversal of V2's directional prediction.
- Closed/INVALIDATED/COMPLETED scenarios cannot be re-entered.
- No duplicate positions across revisions of the same scenario.
- Shadow-only — zero broker submission paths.
- The deployed `shadow_execution.py` (sha `8648532d…`) is UNTOUCHED;
  the new path is a parallel module.

---

## 1. Contract — what the new executor reads from V2

Taken AUTHORITATIVELY from each `scenarios_shadow.jsonl` revision whose
latest state is actionable:

| Field | Role in new executor |
|---|---|
| `scenario_id` | Dedup key (per-scenario open/closed slot) |
| `revision_idx` | Dedup key component; sweep identity |
| `generated_at_utc` | Decision-time anchor (lookahead cutoff) |
| `state` | Must be ACTIVE / ACCEPTED (not INVALIDATED / COMPLETED) |
| `opportunities[0].direction` | Trade direction (BUY/SELL) — preserved as-is |
| `publication_decision.decision` | Must be `VALID` (not CAUTION, not INVALID) |
| `trade_proposal.stop_price` | Protective stop — preserved as-is |
| `trade_proposal.target_price` | Structural target — preserved as-is |
| `trade_proposal.entry_price` | **REFERENCE ONLY** (the AI's breakout trigger) |

Taken from the primary observer snapshot stream:

| Field | Role |
|---|---|
| `snapshots.jsonl` bars | M5 OHLC used for fill simulation + MFE/MAE |
| Last-completed bar close at `generated_at_utc` | "Decision price" for A and the quality gate |

Session-aware model spread (no contemporaneous bid/ask available for
Oct 23 → Nov 3 2026 — see Appendix A for the data audit):

| Session (UK local) | Half-spread (pips) | Round-trip |
|---|---|---|
| London mid (07:00–11:00) | 0.45 | 0.9 |
| Mid-session (11:00–14:00) | 0.70 | 1.4 |
| NY active (14:00–17:00) | 1.00 | 2.0 |

---

## 2. Three mechanisms — explicit algorithms

Inputs for all three: `scenario_row`, `latest_snapshot_at_gen`, `candles`
(M5 bars with ts_open, ts_close, o, h, l, c), `now_utc`,
`max_fill_lookback_seconds` (inherited default 7200).

### A. Early directional entry

Fire the first permitted bar close after `generated_at_utc`, in the
V2-predicted direction, at the bar's close price. No breakout wait.

```python
def mechanism_A(scenario, snapshot, candles, now, lookback_s):
    scen_gen = parse(scenario["generated_at_utc"])
    enb      = max(scen_gen, now - lookback_s)      # same retrospective-fill cap
    direction= scenario["opportunities"][0]["direction"]
    stop     = scenario["trade_proposal"]["stop_price"]
    target   = scenario["trade_proposal"]["target_price"]

    post = [c for c in candles if enb < c["ts_close"] <= now]
    if not post:
        return WAITING

    entry_bar      = post[0]               # the first eligible completed bar
    simulated_entry= entry_bar["c"]        # mid-close fill at that bar

    # Opportunity-quality gate — see §3
    if not opp_quality_ok(simulated_entry, stop, target, direction,
                            spread_pips_for(entry_bar["ts_close"]),
                            scenario_gen_price=latest_snapshot_close(snapshot)):
        return REJECTED_QUALITY

    return simulate_lifecycle(entry_bar, simulated_entry, direction,
                                stop, target, candles)
```

### B. Pullback entry

Wait for exactly one "controlled pullback" bar after decision — a bar
whose close is COUNTER to the predicted direction relative to the
decision price — then enter at the close of the next bar whose close
is back in-direction.

```python
def mechanism_B(scenario, snapshot, candles, now, lookback_s):
    scen_gen = parse(scenario["generated_at_utc"])
    enb      = max(scen_gen, now - lookback_s)
    direction= scenario["opportunities"][0]["direction"]
    stop     = scenario["trade_proposal"]["stop_price"]
    target   = scenario["trade_proposal"]["target_price"]
    decision_price = latest_snapshot_close(snapshot)

    post = [c for c in candles if enb < c["ts_close"] <= now]
    seen_pullback = False
    entry_bar = None
    for bar in post:
        counter = (direction == "BUY" and bar["c"] < decision_price) \
               or (direction == "SELL" and bar["c"] > decision_price)
        indir   = (direction == "BUY" and bar["c"] > decision_price) \
               or (direction == "SELL" and bar["c"] < decision_price)
        # Hard-fail: if a stop-level price is touched BEFORE entry,
        # abandon the setup (preserves V2's own risk ceiling).
        if (direction == "BUY" and bar["l"] <= stop) \
         or (direction == "SELL" and bar["h"] >= stop):
            return SETUP_INVALIDATED_PRE_ENTRY
        if counter:
            seen_pullback = True
            continue
        if seen_pullback and indir:
            entry_bar = bar
            break
    if entry_bar is None:
        return WAITING

    simulated_entry = entry_bar["c"]
    if not opp_quality_ok(simulated_entry, stop, target, direction,
                            spread_pips_for(entry_bar["ts_close"]),
                            scenario_gen_price=decision_price):
        return REJECTED_QUALITY
    return simulate_lifecycle(entry_bar, simulated_entry, direction,
                                stop, target, candles)
```

Pullback entry is more conservative than A: it enters at a worse
entry (price has already moved against) but implicitly validates the
move's robustness, reducing false-fill rate.

### C. Earlier breakout entry

Retains the AI's breakout trigger (`trade_proposal.entry_price`) but
tightens the confirmation to intra-bar touch instead of close-beyond.
In the current executor's rule (`c["c"] > entry` for BUY), the first
bar whose CLOSE is above entry fires. In C we fire when the first
bar's HIGH touches entry (BUY) or LOW touches entry (SELL).

```python
def mechanism_C(scenario, snapshot, candles, now, lookback_s):
    scen_gen = parse(scenario["generated_at_utc"])
    enb      = max(scen_gen, now - lookback_s)
    direction= scenario["opportunities"][0]["direction"]
    entry    = scenario["trade_proposal"]["entry_price"]
    stop     = scenario["trade_proposal"]["stop_price"]
    target   = scenario["trade_proposal"]["target_price"]

    post = [c for c in candles if enb < c["ts_close"] <= now]
    entry_bar = None
    for bar in post:
        if (direction == "BUY" and bar["h"] >= entry) \
         or (direction == "SELL" and bar["l"] <= entry):
            entry_bar = bar
            break
    if entry_bar is None:
        return WAITING

    # Mechanism C fills AT the entry level (not at bar close) because
    # the trigger was intra-bar — this models a stop-market order sitting
    # at the entry level.
    simulated_entry = entry

    if not opp_quality_ok(simulated_entry, stop, target, direction,
                            spread_pips_for(entry_bar["ts_close"]),
                            scenario_gen_price=latest_snapshot_close(snapshot)):
        return REJECTED_QUALITY
    return simulate_lifecycle(entry_bar, simulated_entry, direction,
                                stop, target, candles)
```

Expected: gains ~1 bar (the "close above" vs "touch" delta) in
some scenarios, but increases false-fill rate on wick-only moves.
Not expected to dominate on today's data.

---

## 3. Opportunity-quality gate

Executed at **decision time** (before simulating any lifecycle).
Rejects entries whose economics are structurally broken.

```python
def opp_quality_ok(exec_price, stop, target, direction, half_spread_p,
                     scenario_gen_price):
    pip = 0.0001                                       # GBP/USD pip
    remaining_pips = (target - exec_price) * (1 if direction == "BUY" else -1)
    risk_pips      = (exec_price - stop) * (1 if direction == "BUY" else -1)

    if remaining_pips <= 0 or risk_pips <= 0:
        return False     # geometry already violated for this exec price

    # 1. Minimum reward in pips, after spread (round-trip half*2).
    net_reward = remaining_pips - 2 * half_spread_p
    if net_reward < MIN_NET_REWARD_PIPS:            # default 3.0 pips
        return False

    # 2. Minimum net reward-to-risk after spread.
    net_rr = net_reward / (risk_pips + 2 * half_spread_p)
    if net_rr < MIN_NET_RR:                         # default 0.75 — see §3.1
        return False

    # 3. Exhaustion check — "has the predicted move been substantially
    #    consumed?" Fire-at-market loses this check if price has
    #    already travelled > MAX_EXHAUSTION of the full predicted range.
    full_range = (target - scenario_gen_price) * (1 if direction == "BUY" else -1)
    if full_range <= 0:
        return False   # scenario-gen price already beyond target — stale
    consumed  = (exec_price - scenario_gen_price) * (1 if direction == "BUY" else -1)
    exhaustion_ratio = consumed / full_range
    if exhaustion_ratio > MAX_EXHAUSTION:           # default 0.70
        return False

    return True
```

The brief's example: a BUY with 0.8 pips to target and 20 pips to stop
would fail at the first check (`remaining_pips - 2 * spread < 3`).

### 3.1 Default thresholds and their justification

Chosen conservatively from the n=14 research sample. These are
**default values** — the feature flag exposes them for per-mode
tuning. They are not optimised on the holdout:

| Constant | Default | Rationale |
|---|---|---|
| `MIN_NET_REWARD_PIPS` | 3.0 | ≥ 1.5× worst-case half-spread (NY close); any smaller trade cannot clear bid-ask. |
| `MIN_NET_RR` | 0.75 | Research sample M5 showed +7.6 net pips at R:R ≥ 1.0 but on n=4 only. 0.75 is one step down from 1.0 to retain more trades while still filtering the R:R=0.1 class (which is 10 of 14 proposals). |
| `MAX_EXHAUSTION` | 0.70 | If the market has already travelled 70 % of the predicted range before entry, remaining reward is < 30 % of the "full move" and spread eats it. Chosen symmetric with M5's effective filter behaviour. |
| `MIN_RR_FOR_PULLBACK` | 1.0 | Mechanism B's pullback entry is already a worse fill than A; demand at least 1:1 reward:risk to compensate. |
| `MIN_RR_FOR_EARLIER_BREAKOUT` | 1.0 | Mechanism C is slightly more aggressive than deployed M1; demand at least 1:1 to counter false-breakout cost. |

### 3.2 Threshold hygiene

- Thresholds are stored in **module-level constants** of
  `impl/early_entry.py`.
- Every rejection records the **specific reason** on the audit row
  (`QUALITY_REJECTION_<NET_REWARD|NET_RR|EXHAUSTION|GEOMETRY>`), so the
  deployment-readiness analysis can audit the reject distribution.
- Tuning the thresholds requires an explicit code change + regression
  test update + operator approval; no runtime override is exposed to
  avoid silent drift.

---

## 4. Lifecycle after fill — unchanged

Once `simulate_lifecycle` fires, exit monitoring follows the exact
rules of `shadow_execution.py`:

- Bars strictly after `entry_bar.ts_open`.
- Stop hit: BUY `l <= stop`, SELL `h >= stop`. Exit at stop.
- Target hit: BUY `h >= target`, SELL `l <= target`. Exit at target.
- Both-in-same-bar: `AMBIGUOUS` (exit at bar close, flagged).
- MFE/MAE computed over the full post-entry window.

**No change to V2's stop or target.** The new executor preserves the
protective geometry V2 chose. If V2 proposes R:R = 0.2, the quality
gate rejects it; if V2 proposes R:R = 1.5, we take it at a better
entry than the deployed executor would.

---

## 5. Preserved invariants — point by point

- **Direction preserved.** `direction` comes from `opportunities[0]`; never flipped.
- **Scenario state respected.** `state in (INVALIDATED, COMPLETED)` → `SUPPRESSED`, no fill.
- **Publication gate honoured.** Only `publication_decision=VALID` is actioned. `CAUTION / INVALID / HISTORICAL / STALE` are not promoted. CAUTION remains CONDITIONAL (dashboard-visible, not actioned by this executor).
- **NMS compatibility.** The new executor reads `primary_decision` the same way `scenario_recommendation.build_trade_recommendation` does, so if NMS has flipped against V2's direction the decision rows will show it; we DO NOT override NMS. The implementation includes a defensive check that `primary_decision.direction ∈ (direction, NEUTRAL)` or that the scenario state did not transition to INVALIDATED between gen and now.
- **Per-scenario dedup.** Shared with the deployed executor via a new dedup file (`shadow_dedup_early.json`); one open position per `scenario_id` across both executors is enforced by the shadow-comparison harness (section 7).
- **Revision churn.** Latest-revision selection (same as the coverage patch); older revisions do not re-fire.
- **Retrospective-fill guard.** Same `MAX_FILL_LOOKBACK_SECONDS=7200` default from `shadow_execution.py`. Cannot backfill pre-cap history.
- **SHADOW_ONLY.** All position/close rows tagged. No imports from
  `/opt/tradingbot`, `trades_api`, IG client, broker modules.

---

## 6. What this design explicitly does NOT change

- **Reasoner prompt.** Still produces breakout-level entries. Fine —
  we ignore the breakout level in Mechanisms A/B.
- **Narrative parser.** No change. Mechanism A/B/C all route through
  the structured `trade_proposal` fields, not the regex parser.
- **Scenario quality / publication gate.** No change. CAUTION remains
  non-actionable.
- **NMS directional authority.** No change. Any new "early entry"
  path still has to pass NMS at live-deploy time; this backtest uses
  recorded `decisions.jsonl` snapshots.
- **EMA Pullback / BB Bounce / briefings / other strategies.** No
  change. New module is in `research/live_obs/agent/` tree only.
- **Live broker.** Impossible. No broker import, no live/demo code
  path, no HTTP client.

---

## Appendix A — Data availability

Contemporaneous bid/ask is **not available** for Oct 23 → Nov 3 2026.
- `/mnt/.../snapshots.jsonl`: OHLC mid only.
- `/mnt/.../ticks/GBPUSD_ticks_2026.csv`: ends 2026-04-10.
- `/mnt/.../research/tick_cache_v2_utc_corrected/GBPUSD/2026.parquet`: ends 2026-03-31.

Backtest therefore uses a session-aware **model spread**:
London mid 0.9 p, mid-session 1.4 p, NY active 2.0 p round-trip.
The CSV reports GROSS and NET separately so the operator can
substitute any other spread model.

**Known limitation:** real IG retail spreads around high-impact news
can reach 5–10 pips. The model does not cover these spikes; trades
whose entry bar falls within ±2 min of a Tier-1 release should be
treated with extra caution. The current n=14 sample does not include
enough such cases to characterise this error, but the operational
mitigation is to require `publication_decision=VALID` (which already
blocks CATEGORY_C scenarios tied to unverified releases).
