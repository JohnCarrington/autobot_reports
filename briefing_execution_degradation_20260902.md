# Briefing-execution degradation forensics — AutoBot-FXi (144)

**Date:** 2026-09-02 · **Mode:** read-only forensics (no code, config, service or broker changes)
**Question put by the operator:** briefing execution was highly accurate historically and has degraded to
trading badly — find what changed, with dates and numbers.

**Headline:** the execution chain did not break. It is measurably *tighter* now than in the
"good era". The claimed degradation is not statistically separable from noise, and the premise
that this box was ever "highly accurate" is not supported by its own fill record.

Evidence sources, in full:

| Source | Path / command |
|---|---|
| Trade outcomes (the fill ledger) | `/opt/tradingbot/logs/signal_log.jsonl` (91 rows, 90 briefing-driven) |
| Independent outcome ledger | `/opt/tradingbot/logs/briefing_outcomes_2026-{05..09}.csv` (81 rows) |
| Briefing artifacts the executor consumes | `/opt/tradingbot/logs/briefing_<PAIR>_<DATE>_<Session>.json` (500 files) |
| Briefing artifacts (v5 FXi engine) | `/opt/tradingbot/briefings/v5_fxi/` (604 files) |
| Briefing plan-vs-market scoring | `/opt/tradingbot/data/briefing_outcomes.jsonl` (452 rows) |
| NTZ gate shadow ledger | `/opt/tradingbot/logs/ntz_shadow.jsonl` (296 rows) |
| Forward veto counterfactual | `/opt/tradingbot/logs/veto_counterfactual.jsonl` (16 rows) |
| Unrecovered scale-out legs | `/opt/tradingbot/logs/scaleout_unrecovered.jsonl` (2 rows) |
| Config history | `/opt/tradingbot/.env` + 11 dated `.env.bak.*` snapshots |
| Code history | `git log` on `briefing_execution.py`, `briefing_executor_v2.py`, `autobot.py`, `briefing_engine.py` |
| Service state | `systemctl show autobot.service`, `journalctl -u autobot.service` |

All commands run as `autobot`. Nothing was restarted, written or committed except this document.
No IG session was opened — a probe would have spawned a competing session against the live bot.

---

## 0. Two measurement traps that had to be cleared first

Both of these would have manufactured a false "break week" had they gone unnoticed.

### 0.1 The P&L column changes meaning on 2026-07-22

`total_pnl_pips` (size-weighted across all legs) exists only from **2026-07-22**. Before that only
`pnl_pips` is present, and for a scaled-out trade `pnl_pips` is the **runner leg alone**.

Scale-out has been live far longer than the logging:

```
BRIEFING_EXEC_SCALEOUT_10P_ENABLED  absent in .env.bak.before_be_enable (2026-05-31 11:43)
                                    =1     in .env.bak.before_htf_authority_on (2026-06-01 23:02)
```

So every scaled-out fill between **2026-06-01 and 2026-07-27** has a single-leg number in the log and
a different true value. Comparing raw `pnl_pips` across that boundary compares two different
quantities and puts an artificial step exactly where the operator's "degradation" is alleged to begin.

`logs/scaleout_unrecovered.jsonl` confirms the gap is real and not recoverable from this host:

> `"reason": "Primary evidence rotated away before it was captured to any durable store. The logrotate at 2026-08-30 00:00 dropped the syslog covering 2026-07-26..08-02, and journald's oldest autobot.service entry is 2026-07-28T01:16:41Z..."`

**Correction applied.** The scale-out rule is deterministic (bank 50% at +10p, runner stop→BE), so the
all-leg total is reconstructable as `0.5×10 + 0.5×pnl_pips` for any fill whose recorded `mfe_pips ≥ 10`.
Validated against the 14 fills where both columns exist:

| | |
|---|---|
| Rows reproduced to within ±0.05 pips | **13 / 14** |
| Sole outlier | 2026-07-31 USDJPY (`runner_size` 0.5, not 1.0; a manual-close anomaly) — excluded |

Every P&L figure in this report is the reconstructed **all-leg** number. The per-fill CSV carries a
`pnl_source` column marking each value `logged`, `reconstructed`, or `single-leg`.

### 0.2 "External/manual close" is a residual bucket, not operator intervention

It is 31–35% of all closes and it is tempting to read it as a human hand on the book. It is not.
`trade_manager.py:623-653` classifies a position that vanished from IG by comparing implied P&L
against stored TP/SL distances with a 3-pip tolerance, and **falls through to this string whenever
nothing matches**:

```python
def _detect_ig_close_reason(state_obj: dict, exit_hint: Any) -> str:
    ...
    if tp_pips > 0 and abs(pnl_pips - tp_pips) <= tolerance: return "TP hit"
    if sl_pips > 0 and abs(pnl_pips + sl_pips) <= tolerance: return "SL hit"
    if 0 <= pnl_pips <= be_offset + tolerance:                return "Breakeven stop hit (IG server-side)"
    ...
    return "External/manual close detected (IG open positions)"
```

So it means **"unclassified exit"**. Roughly a third of this box's briefing exits carry no reliable
close attribution. That is a genuine forensic limitation and it is stated wherever it bears on a
conclusion below.

---

## 1. Fill ledger

**91 briefing-driven fills**, 2026-05-22 → 2026-09-02. 90 are in `signal_log.jsonl`; one
(2026-07-26 EURUSD SELL) appears only in the outcomes CSV — it falls inside the rotated-away window.
The two ledgers otherwise agree on 80 of 81 shared rows.

Live `BRIEFING_EXECUTION` began **2026-06-01** (`BRIEFING_EXECUTION_ENABLED` is `0` in the 2026-05-21
and 2026-05-31 snapshots, `1` from 2026-06-01). The five May fills are the retired
`BRIEFING_FXI_FIRST_*` predecessor (identifier rendered per the repo's name-substitution rule; the
literal string in the log carries the retired project name). **There is no live briefing-execution history on this box before
2026-06-01** — a point that matters in §5.

Full per-fill ledger — date, side, entry, the briefed level it executed against, entry deviation,
executor SL/TP vs briefed SL/TP, fire path, all-leg P&L and close reason — is committed alongside
this report as **`briefing_execution_fill_ledger_20260902.csv`** (90 rows, 25 columns).

### Weekly net (all legs, Monday-anchored)

| Week | Trades | Net pips | Mean | Win % | Cumulative |
|---|---:|---:|---:|---:|---:|
| 2026-05-18 | 2 | −7.00 | −3.50 | 0.0 | −7.00 |
| 2026-05-25 | 3 | −16.20 | −5.40 | 0.0 | −23.20 |
| 2026-06-01 | 12 | −22.35 | −1.86 | 41.7 | −45.55 |
| 2026-06-08 | 10 | +5.15 | +0.52 | 50.0 | −40.40 |
| 2026-06-15 | 11 | **+61.25** | +5.57 | 81.8 | +20.85 |
| 2026-06-22 | 9 | **−64.38** | −7.15 | 33.3 | −43.52 |
| 2026-06-29 | 1 | +5.05 | +5.05 | 100.0 | −38.47 |
| 2026-07-06 | 2 | +10.03 | +5.01 | 100.0 | −28.45 |
| 2026-07-13 | 1 | −15.55 | −15.55 | 0.0 | −44.00 |
| 2026-07-20 | 11 | +27.60 | +2.51 | 63.6 | −16.40 |
| 2026-07-27 | 7 | +51.68 | +7.38 | 71.4 | +35.28 |
| 2026-08-03 | 1 | +35.38 | +35.38 | 100.0 | **+70.65** ← peak |
| 2026-08-10 | 2 | −37.15 | −18.57 | 0.0 | +33.50 |
| 2026-08-17 | 8 | −32.15 | −4.02 | 50.0 | +1.35 |
| 2026-08-24 | 5 | −34.17 | −6.83 | 40.0 | −32.82 |
| 2026-08-31 | 5 | +24.98 | +5.00 | 80.0 | −7.85 |

Monthly, live `BRIEFING_EXECUTION` only:

| Month | Trades | Net pips | Mean | Win % | TP-hit % | SL-hit % |
|---|---:|---:|---:|---:|---:|---:|
| 2026-06 | 42 | −20.32 | −0.48 | 52 | 10 | 24 |
| 2026-07 | 22 | **+78.80** | +3.58 | 68 | 0 | 27 |
| 2026-08 | 19 | −42.25 | −2.22 | 53 | 16 | 26 |
| 2026-09 | 2 | −0.88 | −0.44 | 50 | 0 | 50 |
| **Lifetime** | **85** | **+15.35** | **+0.18** | **56.5** | | |

### The exact week accuracy broke — it doesn't

The equity peak is the week of **2026-08-03** (+70.65 cumulative) and the trough is
**2026-08-28** (max drawdown **103.48 pips**). The naive answer is therefore "week commencing
2026-08-10". That answer does not survive testing.

- Per-trade standard deviation is **14.50 pips**. A 20-trade window therefore has a standard
  deviation of **±64.9 pips** around its mean. The post-08-10 result is −78.50 pips over 20 trades —
  about **1.2 sigma**. Entirely ordinary.
- Split at 2026-08-10, pre vs post: mean +1.44 vs −3.92 pips/trade, gap +5.37.
  Permutation test, 200,000 shuffles: **p = 0.074**.
- That split was *chosen because it looked worst*. Scanning all 66 candidate split points and
  permuting the maximum gap — the correct test once you have searched — gives
  **p = 0.445**.

> **There is no statistically defensible break week.** The August drawdown is what this strategy's
> own trade-to-trade variance produces routinely.

---

## 2. Chain integrity — good era vs bad era

All 90 fills were matched back to a plan in that day's briefing file for that pair
(`entry_zone`, `stop_loss`, `targets[0]`). Chain integrity did not degrade; it **improved**.

| Month | Fills | Direction match | Median entry deviation | 90th pct | In-zone | Median SL dev | Median TP dev |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 5 | 100% | 5.30p | 5.90p | 0% | 1.60p | 23.50p |
| 2026-06 | 42 | 100% | 0.00p | 4.60p | 60% | 0.85p | 0.74p |
| 2026-07 | 22 | 100% | 0.00p | 1.80p | 68% | 0.55p | 6.20p |
| 2026-08 | 19 | 100% | 0.00p | 6.10p | 68% | 1.60p | 1.00p |
| 2026-09 | 2 | 100% | 0.00p | 0.00p | 100% | 0.90p | 0.88p |

Direction matches the briefed plan bias on **90/90 fills**. Entries land inside the briefed zone in
68% of bad-era fills versus 60% in June. Executor stops and targets track briefed levels to well
under a pip.

### Three good-era fills, verbatim against their day's briefing

```
2026-07-23T11:50  USDJPY BUY    [briefing_USDJPY_2026-07-23_London.json]
  briefed plan   : 'NY continuation after London breakout'  (prob 0.38, conf MEDIUM)
  briefed zone [16348.0, 16355.0]  stop 16335.0  target 16360.0
  ACTUAL fill    : entry 16348.5 -> IN ZONE
  exec sl 16334.6 (dev 0.4p) | tp1 16359.6 (dev 0.4p)
  trend_entry_fallback | +93min | +22.55 pips (EOD_CLOSE)

2026-07-27T06:55  EURUSD SELL   [briefing_EURUSD_2026-07-27_London.json]
  briefed plan   : 'Fade buy-side liquidity sweep pre-Ifo'  (prob 0.42, conf MEDIUM)
  briefed zone [11410.0, 11413.0]  stop 11420.0  target 11390.7
  ACTUAL fill    : entry 11408.2 -> OUTSIDE by 1.8p
  exec sl 11419.6 (dev 0.4p) | tp1 11390.3 (dev 0.4p)
  phase2_sweep_reclaim | +83min | +25.05 pips (unclassified exit)

2026-07-27T08:05  USDJPY BUY    [briefing_USDJPY_2026-07-27_London.json]
  briefed plan   : 'Sell-side liquidity sweep reversal long'  (prob 0.42, conf MEDIUM)
  briefed zone [16352.0, 16356.0]  stop 16338.0  target 16394.15
  ACTUAL fill    : entry 16352.4 -> IN ZONE
  exec sl 16338.4 (dev 0.4p) | tp1 16394.6 (dev 0.45p)
  phase2_sweep_reclaim | +151min | +15.90 pips (unclassified exit)
```

### Three bad-era fills, verbatim against their day's briefing

```
2026-08-17T05:45  EURUSD BUY    [briefing_EURUSD_2026-08-17_London.json]
  briefed plan   : 'Bullish continuation on sweep reclaim'  (prob 0.52, conf MEDIUM)
  briefed zone [11585.0, 11587.5]  stop 11578.0  target 11600.0
  ACTUAL fill    : entry 11587.4 -> IN ZONE
  exec sl 11578.4 (dev 0.4p) | tp1 11600.4 (dev 0.4p)
  phase2_sweep_reclaim | +13min | +12.05 pips (TP hit)

2026-08-17T07:30  GBPUSD BUY    [briefing_GBPUSD_2026-08-17_London.json]
  briefed plan   : 'Bullish breakout above prev day high'  (prob 0.58, conf MEDIUM)
  briefed zone [13562.0, 13567.0]  stop 13550.0  target 13600.0
  ACTUAL fill    : entry 13565.9 -> IN ZONE
  exec sl 13550.4 (dev 0.4p) | tp1 13600.4 (dev 0.4p)
  phase2_sweep_reclaim | +119min | -3.75 pips (unclassified exit)

2026-08-17T08:30  USDCAD SELL   [briefing_USDCAD_2026-08-17_NY.json]
  briefed plan   : 'NY bearish continuation after London weakness'  (prob 0.55, conf MEDIUM)
  briefed zone [13858.0, 13862.0]  stop 13870.0  target 13840.0
  ACTUAL fill    : entry 13851.5 -> OUTSIDE by 6.5p
  exec sl 13875.0 (dev 5.0p) | tp1 13846.5 (dev 6.5p)
  trend_entry_fallback | +174min | -23.15 pips (SL hit)
```

The bad-era fills sit **closer** to their briefed levels than the good-era ones (0.4p executor
deviations throughout; contrast a 22.3p stop deviation on 2026-06-15 USDJPY). The chain is intact.

### The one place drift does cost money

Entry deviation is not free, and the effect is concentrated in the `trend_entry_fallback` path,
which by design enters away from the briefed zone (only 28% in-zone, vs 92% for `phase2_sweep_reclaim`):

| Entry deviation from briefed zone | Fills | Net pips | Mean |
|---|---:|---:|---:|
| in zone (0p) | 55 | +17.58 | +0.32 |
| 0–3p outside | 15 | +33.65 | +2.24 |
| **3–8p outside** | **11** | **−31.05** | **−2.82** |
| >8p outside | 4 | −4.82 | −1.21 |

`trend_entry_fallback` swung from +1.79/trade (n=29) in the good era to **−8.73/trade (n=7)** in the
bad era, contributing **−61.10** of the −78.50 post-08-10 total. All four of its bad-era losers were
"continuation" plans that hit their stop. This is the strongest single lead in the data — but n=7,
and plan age at fire does not explain it (correlation of plan age with pips = **−0.046**, n=85).

---

## 3. What changed when

### Config — conviction floors, tolerances, TP/SL sources and session windows are all unchanged

| Key | 05-21 | 05-31 | 06-01 | 06-07 | 06-12 | 07-05 | 08-06 | 08-10 | 08-29 |
|---|---|---|---|---|---|---|---|---|---|
| `BRIEFING_EXECUTION_ENABLED` | 0 | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `BRIEFING_EXEC_MIN_PROB` | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 | 0.40 |
| `BRIEFING_LEVEL_TOLERANCE_PIPS` | 12 | 12 | 12 | 12 | 12 | 12 | 12 | 12 | 12 |
| `BRIEFING_INVALIDATION_TOLERANCE_PIPS` | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 |
| `BRIEFING_EXEC_TRIGGER_V2_MODE` | live | live | live | live | live | live | live | live | live |
| `BRIEFING_EXEC_USE_DEEPEST_TARGET` | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `BRIEFING_EXEC_TRADE_SIZE` | – | – | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| `BRIEFING_EXEC_SIGNAL_FILTER_ENABLED` | – | – | – | – | – | – | 1 | 1 | **shadow** |
| `BRIEFING_EXEC_NTZ_GATE_ENABLED` | – | – | – | – | – | – | 1 | **shadow** | **shadow** |

The conviction floor, level tolerance, invalidation tolerance, trigger mode, TP source
(deepest-target) and trade size have **not moved once** in the entire period. The only changes on the
briefing surface are two gates being relaxed from enforce to shadow:

- **2026-08-10 23:02** — `BRIEFING_EXEC_NTZ_GATE_ENABLED` `1 → shadow`, with the reason recorded inline:
  > `# 2026-08-10: enforce->shadow; 17/19 Jul11-Aug05 fills (+119.6p net) would have been vetoed. Collect ntz_shadow.jsonl evidence first.`
- **2026-08-17 08:20** — `BRIEFING_EXEC_SIGNAL_FILTER_ENABLED` `1 → shadow`.

Both were deliberate, documented, and made *because the gates were vetoing winners*.

### Did the NTZ relaxation cost the pips?

No — it is far too small. `ntz_shadow.jsonl` records **296 plan evaluations since 2026-08-11** and only
**10** hit a no-trade zone. Tracing those 10 to actual fills gives **2 distinct trades**
(2026-08-11 GBPUSD −13.65, 2026-08-17 USDCAD −23.15), and even those are a loose day-level join —
the 08-11 fill's entry of 13514.6 sits outside the shadow record's zone of [13503, 13508], so it
did not come from the vetoed plan at all. Ceiling on the NTZ relaxation: **≈ −36.8 pips**, and
realistically less, against a −103 pip drawdown.

### Code

Commits touching the execution chain in the bad-era window:

```
2026-08-29 deeb552 feat(veto-cf): forward counterfactual ledger for the two enforcing gates
2026-08-29 0cbdb8b feat(signal_log): record the scale-out leg; add size-weighted total_pnl_pips
2026-08-18 4184f38 fix(BE): honest broker limits + lockout survives restart (08-17 fills)
2026-08-17 1a9d63c fix(BE): drop the redundant dispatcher-level briefing-trigger gate
2026-08-11 e3317e4 fix(BE): drop self-defeating no_trade_zones at ingest
2026-08-11 bb81c87 fix(BE): key NY-eval latch by briefing_time, not UTC date
2026-08-09 1fa21fc feat(BE): NTZ shadow ledger — telemetry-only, zero behaviour change
2026-08-06 707f6d9 fix(BE): enforce briefing signal_filter + no_trade_zones at arm and fire
2026-08-06 158fea8 fix: stop BE amends erasing the broker take-profit
```

Note the sequence: the gates were **introduced** on 2026-08-06 (707f6d9), and relaxed within days
once their shadow evidence showed them vetoing profitable trades. They were never enforcing during
the July "good era" — July predates them entirely. **Their relaxation cannot explain a regression
relative to July, because July ran with them absent.**

### Service restarts

- `NRestarts=0`; `ExecMainStartTimestamp=Wed 2026-09-02 06:04:55 UTC` — the live process started today
  and is running current code and current `.env`.
- A restart is provable between **2026-08-10 23:02** (the NTZ edit) and **2026-08-11 05:32:33** — the
  first `ntz_shadow.jsonl` record carries `"gate_mode": "shadow"`, so the new value was in-process by then.
- A full restart timeline could not be reconstructed: journald on this box holds only
  **2026-07-28 onward** (3.8 GB, 8 GB cap) and the syslog covering 2026-07-26..08-02 was dropped by
  the 2026-08-30 logrotate. Restart history before 2026-07-28 is gone from this host.

### The 2026-07-22 .env incident — was 144's recovery complete?

**Yes, on every key that touches the briefing chain.** Reconstructing the pre-incident config from
`.env.save.1` (2026-07-05) and diffing forward:

- Keys present pre-incident and **missing today: none.** Nothing fell back to a silent code default.
- Keys added since: 21 (the 08-06 gates, cascade mode, news-window automation, host labelling).
- Value regressions on the trading surface: **one**, `BOT_ID`, a telemetry label changed by the
  2026-08-29 host-label commit. No behavioural key regressed.

The briefing-relevant diff across the incident window contains additions only:

```
> BRIEFING_EXEC_NTZ_GATE_ENABLED=1
> BRIEFING_EXEC_SIGNAL_FILTER_ENABLED=1
> CASCADE_DISAGREE_MODE=shadow
< NEWS_WINDOWS_FILE=/opt/tradingbot/news_windows.json
> NEWS_WINDOWS_FILE=/opt/tradingbot/news_windows_auto.json
> NEWS_WINDOWS_STALE_DAYS=7
```

---

## 4. Upstream check — did the briefing change character?

### Plan geometry: no

Every trading plan written to this box, by month:

| Month | Plans | Median prob | HIGH conf | Median TP dist | Median SL dist | Median RR | Median zone width |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 490 | 0.380 | 3% | 17.5p | 12.5p | 1.35 | 5.0p |
| 2026-06 | 735 | 0.380 | 1% | 18.5p | 12.0p | 1.50 | 5.0p |
| 2026-07 | 555 | 0.380 | 1% | 17.8p | 11.0p | 1.56 | 4.0p |
| 2026-08 | 769 | 0.380 | 1% | 18.5p | 11.5p | 1.61 | 4.0p |
| 2026-09 | 81 | 0.380 | 1% | 17.5p | 11.8p | 1.31 | 4.0p |

Median plan probability is **0.380 in every single month**. TP distance, stop distance, reward:risk
and entry-zone width are flat. The briefing's *shape* has not moved at all.

### Plan predictive accuracy: mild, mostly not significant

| Month | Sessions | Bias correct | Regime correct | TP1 hit | TP2 hit | Sweep acc | Median session range |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 54 | 41.5% | 88.9% | 70.4% | 29.6% | 2.0p | 23.0p |
| 2026-06 | 139 | 35.7% | 87.1% | 43.2% | 9.4% | 2.3p | 17.7p |
| 2026-07 | 102 | 40.6% | 85.3% | 51.0% | 9.8% | 2.0p | 18.8p |
| 2026-08 | 149 | 34.9% | 85.9% | 41.6% | 5.4% | 2.6p | 17.8p |

Regime accuracy and sweep-level accuracy are flat. Session range compressed once in late May
(23.0p → ~18p) and has been stable since — it did not step down again in August.

The important observation is the **shape**: August ≈ June, and **July is the outlier upward** on both
sides of the chain simultaneously.

| | July | June + August | Permutation p |
|---|---:|---:|---:|
| Briefing TP1-hit rate | 51.0% (52/102) | 42.4% (122/288) | 0.084 |
| Briefing TP2-hit rate | 9.8% | 7.3% | 0.274 |
| Briefing bias correct | 40.6% | 35.4% | 0.371 |
| **Execution pips/trade** | **+3.58 (n=22)** | **−1.03 (n=61)** | **0.104** |

Execution outperformed in exactly the month the briefing itself was most accurate, and reverted in
exactly the months it was not. That is the signature of a **faithful executor tracking its input**,
not of a broken one. Neither July advantage reaches significance on its own, which is the honest
reading: the sample cannot support strong claims in either direction.

The one metric with a genuine monotonic decline is **TP2-hit, 29.6% → 5.4%**. Plans still ask for a
second target ~18 pips out while the median session range is ~17.8 pips and the median absolute
session move is 7.6 pips. Deep second targets are structurally unreachable in this tape — but that
has been true since June, not since August.

---

## 5. Verdict

**The chain is intact and the tape did not change either. What changed is the sample.**

Ranked causes, with pips attached:

| # | Cause | Pips | Confidence |
|---|---|---:|---|
| 1 | **Ordinary variance.** −78.5 pips over 20 post-08-10 trades is 1.2σ on a 14.50-pip per-trade SD. Corrected permutation test over all candidate break points: **p = 0.445**. | ≈ −78 of −78 | **High** |
| 2 | **Entry drift on `trend_entry_fallback`.** 3–8p outside the briefed zone returns −2.82/trade (n=11); the path swung to −8.73/trade in the bad era. Real, actionable, but n=7. | −61 (overlaps #1) | Medium |
| 3 | **Stop overrun.** 7 of 85 fills (8%) closed worse than stop+3p, up to 2.98× the stop distance, costing **−53.85 pips** lifetime. Rate is flat across eras (8% vs 10%) so it is not the *degradation*, but it is a live defect. | −53.85 lifetime | Medium-high |
| 4 | **Unreachable TP2.** ~18p second targets against a ~17.8p median session range; TP2-hit fell 29.6% → 5.4%. Predates August. | Opportunity cost, unquantified | Medium |
| 5 | **NTZ gate enforce→shadow (2026-08-10).** Ceiling of 2 fills; the gate did not exist during the July good era. | ≥ −36.8 (likely far less) | Low as a cause |
| 6 | **2026-07-22 .env incident.** Recovery on 144 was **complete** — no key lost, no behavioural value regressed. | 0 | High |

**On the premise.** Briefing execution on 144 has never been materially profitable. Live history runs
**2026-06-01 → 2026-09-02, 85 trades, +15.35 pips net, +0.18 pips/trade, 56.5% win rate** — a coin
flip with a small edge, swamped by ±14.5 pips of per-trade noise. The "highly accurate" era is a
single strong month, **July 2026 (+78.80 over 22 trades)**, bracketed by a negative June (−20.32)
and a negative August (−42.25). August did not fall below a high baseline; it returned to the June
baseline after a favourable July. Any earlier "accurate" period the operator recalls predates live
execution on this box and was not this system trading real orders.

**The executor is innocent, and so is the briefing engine on 178.** Level quality, TP distances and
conviction values are flat to three significant figures across every month. Chain fidelity has
improved. There is no evidence here to move the investigation to 178 — and no evidence that anything
broke at all.

**What would actually be worth doing** (not done — this was read-only):

1. Fix the stop overrun (#3) — 7 fills exiting past their stop is a real protection failure worth
   −53.85 pips, independent of the variance question.
2. Fix close attribution — a third of exits are unclassified, which is why this investigation needed
   §0.2 at all.
3. Stop drawing conclusions from 20-trade windows. At 14.5 pips SD, distinguishing a 2-pip/trade edge
   change from noise at p<0.05 needs on the order of 400 trades — roughly **four years** at this box's
   ~1.5 fills/week. Any future "it degraded" claim should be tested against that bar before config is changed.

---

## 6. Addendum — cross-check against the same-day host 161 audit

`host161_briefing_era_audit_20260902.md` (commit `71574eb`, landed on the reports remote while this
investigation was running) reaches the same conclusion about the premise, independently and on a
different host and corpus:

> **Class A (BRIEFING_EXECUTION) — verdict.** Not "accurate historically". Aggregate −340p / 313 fires.

Two independent hosts, two independent corpora, same finding: the belief that standalone briefing
execution was once highly accurate is not supported by either box's fill record.

**But 161's root cause does not transfer to 144, and this must not be mis-applied.** 161 diagnoses a
schema orphan — `briefing_execution.py` reads `briefing["trading_plans"]` while its BriefingV5 files
carry a flat single-plan schema, so the lookup returns `None` and the strategy silently no-ops from
~W22. On 144 the executor resolves its briefings from `LOG_DIR` (`briefing_execution.py:3932-3940`),
and those files are intact:

| Corpus on 144 | Files | With non-empty `trading_plans[]` |
|---|---:|---:|
| `logs/briefing_<PAIR>_<DATE>_<Session>.json` (**what the executor reads**) | 500 | **500 (100%)** |
| `logs/…` restricted to 2026-08 / 2026-09 | 165 | **165 (100%)** |
| `briefings/v5_fxi/` (flat schema — the shape that orphaned 161) | 604 | 0 |

144's Class A is alive: it fired 85 times through 2026-09-02 and every one of those fills matched
back to a real plan (§2). The dormancy cliff described on 161 did not happen here.

**Latent risk worth recording, though.** 144 holds *both* schemas on disk, and the 604 `v5_fxi` files
are exactly the flat shape that silenced 161. If 144 is ever repointed at the v5 corpus — or if the
producer stops emitting `trading_plans[]` into `LOG_DIR` — this box will go silently dormant in the
same way, with no error beyond a `"no trading_plans in briefing"` log line. That is a monitoring gap,
not a present defect.
