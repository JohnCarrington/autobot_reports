# BB(20,2) 5m reversal-scalp — executable-price replay, two trading weeks through Fri 2026-09-25

_Read-only research on IG DEMO SPREADBET account Z3G4CJ. No orders, service
changes, or live trading-configuration changes were made. Credentials and
session tokens are never printed or committed._

Author: autobot · Generated: 2026-09-27 UTC

## 0. TL;DR

- Retrieved **actual IG bid/ask candles** from `/prices/{epic}` v3 for both
  epics: 1-minute for **Friday 2026-09-25 (00:00–20:58 UTC)** and 5-minute
  for **Mon 2026-09-14 → Wed 2026-09-23**. **Thu 2026-09-24 is missing**
  from the executable-price table — the weekly allowance (10,000 points)
  ran out at 171 remaining after the Friday-1m pull and the 8-day 5m pull,
  and the user's instructions explicitly forbid filling missing dates with
  mid-price estimates. Fri 2026-09-25 in the two-week grid is the 1-minute
  data aggregated to 5-minute bid/ask (identical mid to the local
  archive on shared bars; see §1.3).

- **The +34 pips headline from the Friday-only mid-price study does not
  reproduce on IG's own historical data**, either at mid or at
  bid/ask. Under my authoritative IG bid/ask (same 00:00–20:55 UTC window,
  identical rule, fresh BB warmup, two-slot rule, TP=8/SL=15):
  - **mid rule → net −12 pips** (10 admitted, 6 TP, 4 SL).
  - **executable rule → net −46 pips** (10 admitted, 4 TP, 5 SL, 1 UNR).
  The prior study used a locally-captured 5m mid archive that disagrees
  with IG's authoritative 5m aggregation on some bars by ~0.5–1 pip
  (see §1.3), enough to reroute the resolutions.

- **Two-week executable-price sweep (TP ∈ {5,8,10} × SL ∈ [broker_min..16])**
  — every combo is net-negative under both admission modes. The
  least-bad two-slot combo is **TP=10 SL=4 at −166.5 pips over 10
  entry-dates (1 positive day)**. The unlimited-concurrency version tops
  out at **TP=10 SL=3 at −113.5 pips** on 128 EURUSD-only candidates
  (GBPUSD blocked by 4-pip current broker minimum). No parameter grid
  survives spread on the two-week sample.

- **Direction split matters**: GBPUSD BUYs are the primary drain
  (TP=5 SL=16 → −411 pips across 69 candidates; TP=8 SL=15 →
  −467 pips across 69). **EURUSD SELL at wide stops is the one
  positive island**: 10 of 12 broker-valid EURUSD-SELL cells with
  SL ≥ 13 are net-positive, best at **TP=10 SL=16 → +115.5 pips over
  56 candidates, 70% win rate**. All other pair × direction × (TP,SL)
  cells are negative. The combined-pairs aggregate stays negative
  because GBPUSD BUY overwhelms the EURUSD-SELL edge. 56 EURUSD-SELL
  candidates over ten days is not enough to reject the null that this
  is a sample-fluke of a downtrending EURUSD window (spot moved from
  ~1.1370 to ~1.1385 to lower — see the raw data).

- **Current IG DEMO SPREADBET dealing rules** (captured live 2026-09-27
  22:14 UTC, see `dealing_rules.json`):
  - GBPUSD `minNormalStopOrLimitDistance` = 4 points
  - EURUSD `minNormalStopOrLimitDistance` = 2 points
  These are the CURRENT limits — historical per-timestamp minima are
  not recorded on this host, so 8-pip GBPUSD stops that were "broker
  rejected" in the prior study on the 12-pip bot floor are here
  broker-valid at the currently configured IG floor. See §3.

- On Friday alone, **every** (TP,SL) combo in the executable-price sweep
  finishes net-negative. See §5.4.

- **Do not treat any (TP,SL) combo from these ten days as an optimum.**
  266 candidates on a 5-min FX reversal rule tested across ten days is
  far too small a sample to distinguish signal from spread noise, and the
  effect of spread on this rule is large enough (~1–3 pip per trade)
  that anything less than several months of clean bid/ask data is
  premature.

## 1. Data provenance

### 1.1 Retrieval

Fetched via IG REST `/prices/{epic}` (version 3) using trading_ig's
`fetch_historical_prices_by_epic()` with `format=ig.flat_prices` so the
DataFrame index carries `snapshotTimeUTC` (true UTC), not
`snapshotTime` (Europe/London). See `fetch_ig_bidask.py`.

| what | file | resolution | first (UTC) | last (UTC) | rows |
|---|---|---|---|---|---:|
| GBPUSD Fri 25 Sep | data/GBPUSD/2026-09-25_minute_bidask.csv | MINUTE | 2026-09-24T23:00 | 2026-09-25T20:58 | 1317 |
| EURUSD Fri 25 Sep | data/EURUSD/2026-09-25_minute_bidask.csv | MINUTE | 2026-09-24T23:00 | 2026-09-25T20:58 | 1317 |
| GBPUSD Mon 14 → Tue 23 | data/GBPUSD/2026-09-{14..23}_minute_5_bidask.csv (8 files, no Sat/Sun) | MINUTE_5 | 2026-09-13T23:00 | 2026-09-23T20:55 | 8 × 264–288 |
| EURUSD Mon 14 → Tue 23 | data/EURUSD/2026-09-{14..23}_minute_5_bidask.csv | MINUTE_5 | 2026-09-13T23:00 | 2026-09-23T20:55 | 8 × 264–288 |

Each row carries bid_open, bid_high, bid_low, bid_close, ask_open,
ask_high, ask_low, ask_close, volume. Prices are IG "points" — divide
by 10 000 for the real quote.

The Fri 1-min data is aggregated inside `run.py` (function
`_aggregate_1m_to_5m`) into 5-minute bars anchored on UTC minute
boundaries: open = first minute's open, high/low = max/min across the
five minutes, close = last minute's close, on both bid and ask streams
independently.

IG's date-range parameters are interpreted in Europe/London (BST in
September), so a naive `from=2026-09-25T00:00` request returns bars
whose `snapshotTimeUTC` starts at 2026-09-24T23:00 UTC. Bars are correctly
UTC-timestamped in the stored CSVs; only the request window slides.

### 1.2 Coverage

**10 UTC entry-dates present** across the two weeks:

| entry_date | notes |
|---|---|
| 2026-09-14 (Mon) | full |
| 2026-09-15 (Tue) | full |
| 2026-09-16 (Wed) | full |
| 2026-09-17 (Thu) | full |
| 2026-09-18 (Fri) | closes ~21 UTC |
| 2026-09-20 (Sun) | tail 23:00–23:55 UTC of Sun-evening Monday-open; 5 admitted trades in this hour on some (TP,SL) combos |
| 2026-09-21 (Mon) | full |
| 2026-09-22 (Tue) | full |
| 2026-09-23 (Wed) | full |
| **2026-09-24 (Thu)** | **EXCLUDED — allowance exhausted after 8 × 5m + 2 × 1m fetches** |
| 2026-09-25 (Fri) | 1-min → 5m agg |

### 1.3 IG historical prices vs the local 5m mid archive

Cross-checked 5-min mid on Fri 2026-09-25 against
`/opt/tradingbot/data/candles/{pair}/2026-09-25.csv`. Most bars agree
exactly (verified at 2026-09-25T00:00 UTC: (13209.85, 13213.55,
13209.65, 13213.15) both files). **A minority of bars disagree by
~0.5–1 pip.** Example:

| bar (UTC) | source | O | H | L | C |
|---|---|---|---|---|---|
| 2026-09-25T02:55 | local | 11372.5 | 11372.6 | 11371.6 | 11371.9 |
| 2026-09-25T02:55 | IG bid/ask → mid | 11372.5 | 11372.6 | 11371.6 | 11371.9 |
| **2026-09-25T03:00** | **local** | **11371.8** | **11371.9** | **11369.8** | **11370.8** |
| **2026-09-25T03:00** | **IG bid/ask → mid** | **11372.4** | **11372.4** | **11370.2** | **11371.3** |
| 2026-09-25T03:05 | local | 11370.9 | 11372.4 | 11370.8 | 11371.5 |
| 2026-09-25T03:05 | IG bid/ask → mid | 11371.4 | 11372.6 | 11371.3 | 11371.6 |
| 2026-09-25T03:10 | local | 11371.4 | 11371.4 | 11369.6 | 11369.6 |
| 2026-09-25T03:10 | IG bid/ask → mid | 11371.4 | 11371.4 | 11369.6 | 11369.6 |

That ~0.4-pip lower `low` at 03:00 in the local archive is enough to
drop mid_low below the BB(20,2) lower band on the 03:05 bar and produce
an EURUSD BUY candidate that the IG-authoritative feed **does not**
produce (see §5.1). One rerouted candidate propagates through the
re-key state and the two-slot admission cascade, changing the ranking.

**Conclusion**: on IG's own historical prices, the prior study's
+34-pip mid-price Friday two-slot result at TP=8/SL=15 does not
reproduce — even before spread is charged. IG's `/prices/{epic}` v3 is
the authoritative source of what the DEMO account would have replayed;
the local archive is a locally-captured stream with small but
material drift.

### 1.4 Allowance metadata

Every REST call and its IG-reported `remainingAllowance` is logged to
`allowance_log.jsonl`. Summary:

| stage | rows | remaining after |
|---|---:|---:|
| 1-bar probe (start) | 1 | 9999 |
| 2 × Friday MINUTE (both pairs, `format=format_prices` — wrong index) | 2 × 1317 = 2634 | 7365 |
| 2 × Friday MINUTE (both pairs, refetch with `format=flat_prices`) | 2 × 1317 = 2634 | 4731 |
| 16 × 5-min range fetch (Sep 14–23, both pairs) | 8 × (2 × 264–288) ≈ 4560 | 171 |
| STOP triggered (remainingAllowance < 300 safety threshold) | — | — |

The first Friday MINUTE pull consumed allowance twice because the
initial run used `format=format_prices` which indexes on
`snapshotTime` (Europe/London), giving BST-shifted timestamps.
Re-fetched with `format=flat_prices` (indexes on `snapshotTimeUTC`) for
the CSVs on disk.

## 2. Rule (unchanged causal entry definition)

BB(20, 2) on the 5-minute **mid close** (mid = (bid+ask)/2 per corner),
computed on the last 20 closed bars including bar i (rolling, population
stdev — ddof=0, matching TA-Lib default).

- Upper touch on bar i: `mid_high_i >= upper_i`.
- Lower touch on bar i: `mid_low_i <= lower_i`.
- Upper rejection: touch AND `mid_close_i < upper_i` → **SELL** at OPEN of bar i+1.
- Lower rejection: touch AND `mid_close_i > lower_i` → **BUY** at OPEN of bar i+1.
- New-opportunity re-key: after a rejection on side S, further
  rejections on S are blocked until mid close crosses back through the
  middle from the opposite direction (upper block clears once
  `mid_close < middle`; lower block clears once `mid_close > middle`).
- If both upper and lower rejections would fire on the same bar, the
  side with the larger pierce (max distance from the band) wins.
- The rule is unchanged from `../2026-09-25_bb_scalp/report.md` §2.

Execution (this study, executable-price mode):
- **BUY**: entry = ask_open of bar i+1; exit-close = bid.
  - TP hit when `bid_high >= entry_ask + tp`.
  - SL hit when `bid_low  <= entry_ask − sl`.
  - MFE = max(bid_high) − entry_ask; MAE = entry_ask − min(bid_low).
- **SELL**: entry = bid_open of bar i+1; exit-close = ask.
  - TP hit when `ask_low  <= entry_bid − tp`.
  - SL hit when `ask_high >= entry_bid + sl`.
  - MFE = entry_bid − min(ask_low); MAE = max(ask_high) − entry_bid.
- Same-bar TP and SL simultaneously → **AMBIGUOUS** (grouped with
  UNRESOLVED). No such cases occurred in this sweep.

## 3. Broker minimum stop distance (current + historical)

Captured live 2026-09-27T22:14 UTC via
`GET /markets/CS.D.<pair>.TODAY.IP` — see `dealing_rules.json`:

| pair | epic | `minNormalStopOrLimitDistance` | `minControlledRiskStopDistance` | `minStepDistance` |
|---|---|---:|---:|---:|
| GBPUSD | CS.D.GBPUSD.TODAY.IP | **4.0 pts** | 8.0 pts | 1.0 pt |
| EURUSD | CS.D.EURUSD.TODAY.IP | **2.0 pts** | 5.0 pts | 5.0 pts |

The bot's own configured floor (`trade_executor.py:437-443`) is **12
GBPUSD / 6 EURUSD**, above the current IG minimum. Historical per-time
minima are not on disk; use these current values as a lower bound, not
as an attestation for the exact 2026-09-14..25 fire times. Stops below
`minNormalStopOrLimitDistance` are omitted from the pair's admitted set
in the two-slot table; the unlimited-concurrency table lets you inspect
what a 3-pip sub-minimum stop path would have looked like.

## 4. Candidate counts

`candidates.csv` — full 2-week detection walking a single BB context
across every 5-minute bar.

| pair | direction | count |
|---|---|---:|
| GBPUSD | BUY | 69 |
| GBPUSD | SELL | 69 |
| EURUSD | BUY | 72 |
| EURUSD | SELL | 56 |
| **total** | | **266** |

Candidate counts by day (bar_ts date):

| date | count |
|---|---:|
| 2026-09-14 | 25 |
| 2026-09-15 | 36 |
| 2026-09-16 | 37 |
| 2026-09-17 | 28 |
| 2026-09-18 | 29 |
| 2026-09-21 | 33 |
| 2026-09-22 | 26 |
| 2026-09-23 | 26 |
| 2026-09-25 | 26 |

_Note the drop-off on 2026-09-14 relative to Tue/Wed — that day's
early hours have a partially-warmed BB from the extra Sun-evening
bars but a smoother price path._

## 5. Sweep results

Six CSVs alongside this report — every table is derivable from these.

| file | scope |
|---|---|
| `sweep_per_pair_dir.csv` | (TP, SL) × pair × direction (BUY/SELL) — 4 rows per (TP, SL) |
| `sweep_per_pair.csv` | (TP, SL) × pair — 2 rows per (TP, SL) |
| `sweep_combined_unlimited.csv` | (TP, SL) × combined-pairs, unlimited concurrency |
| `sweep_combined_two_slot.csv` | (TP, SL) × combined-pairs, ≤2 concurrent AND no-overlap-same-pair |
| `sweep_friday_only.csv` | Friday isolated slice (both admission modes) |
| `sweep_daily_two_slot.csv` | per (TP, SL) × date under two-slot |

### 5.1 Friday apples-to-apples reproduction (`friday_reproduce.py`)

Same rule, same 00:00–20:55 UTC window (matching the prior study), fresh
BB warmup + fresh re-key on the day's bars alone:

| mode | admitted | TP | SL | UNR | net pips |
|---|---:|---:|---:|---:|---:|
| mid (my IG bid/ask → mid) | 10 | 6 | 4 | 0 | **−12.00** |
| executable (bid/ask) | 10 | 4 | 5 | 1 | **−46.00** |

The prior study reported 10 admitted / 8 TP / 2 SL / 0 UNR / **+34 pips**
using the local 5m mid archive. That result reversed once the same rule
was applied to IG's authoritative historical prices — 2 candidate
trades resolve differently because the local archive's 03:00 UTC and
03:05 UTC EURUSD bars disagree with IG's server-side data by ~0.5 pip
in low/close (see §1.3).

### 5.2 Two-week executable-price two-slot ranking (top of table)

From `sweep_combined_two_slot.csv`. All net_pips are executable and
already spread-adjusted (spread is intrinsic to bid/ask entry/exit).

| rank | TP | SL | taken | TP | SL | UNR | wr | net pips | net/tr | max_dd | skipped-same-pair |
|---:|---:|---:|---:|---:|---:|---:|:-:|---:|---:|---:|---:|
| 1 | 5 | 3 | 109 | 30 | 79 | 0 | 0.28 | **−87.00** | −0.80 | −101.00 | 19 |
| 2 | 10 | 3 | 87 | 12 | 74 | 1 | 0.15 | **−94.50** | −1.09 | −117.00 | 41 |
| 3 | 8 | 3 | 99 | 18 | 81 | 0 | 0.18 | **−99.00** | −1.00 | −109.00 | 29 |
| 4 | 5 | 2 | 121 | 20 | 101 | 0 | 0.17 | **−102.00** | −0.84 | −108.00 | 7 |
| 5 | 8 | 2 | 117 | 11 | 106 | 0 | 0.09 | **−124.00** | −1.06 | −128.00 | 11 |
| 6 | 10 | 2 | 109 | 7 | 102 | 0 | 0.06 | **−134.00** | −1.23 | −150.00 | 19 |
| 7 | 10 | 4 | 191 | 41 | 146 | 4 | 0.22 | **−166.50** | −0.87 | −184.00 | 75 |
| 8 | 10 | 5 | 175 | 42 | 129 | 4 | 0.25 | **−217.50** | −1.24 | −225.00 | 91 |
| 9 | 8 | 5 | 186 | 53 | 131 | 2 | 0.28 | **−231.00** | −1.24 | −237.00 | 80 |
| 10 | 8 | 4 | 206 | 47 | 157 | 2 | 0.23 | **−252.00** | −1.22 | −260.00 | 60 |

Rows 1–6 use SL below GBPUSD's 4-pip current minimum, so their
admitted set is EURUSD-only; the small pool of EUR-only trades has
smaller losses in absolute terms but a worse hit-rate.

The best combo that respects the current GBPUSD 4-pip floor is
**TP=10 / SL=4 at −166.5 pips** across 191 admitted trades over 10
entry-dates. **One positive day** (Sep 15, +4 pips); nine negative
days.

Two-slot skips fell almost entirely on "same-pair open" (not "two
slots full"): with only two pairs and the same-pair-open block first,
the two-slot cap almost never bites in isolation. See
`sweep_combined_two_slot.csv` column `skipped_two_slot` — 0 for every
row.

### 5.3 Two-week executable-price unlimited-concurrency ranking (top)

From `sweep_combined_unlimited.csv`:

| rank | TP | SL | taken | wr | net pips | net/tr | max_dd |
|---:|---:|---:|---:|:-:|---:|---:|---:|
| 1 | 5 | 3 | 128 | 0.27 | **−104.00** | −0.81 | −118.00 |
| 2 | 5 | 2 | 128 | 0.16 | **−109.00** | −0.85 | −115.00 |
| 3 | 10 | 3 | 128 | 0.16 | **−113.50** | −0.89 | −134.00 |
| 4 | 8 | 3 | 128 | 0.19 | **−120.00** | −0.94 | −135.00 |
| 5 | 10 | 2 | 128 | 0.09 | **−124.00** | −0.97 | −132.00 |
| 6 | 8 | 2 | 128 | 0.10 | **−126.00** | −0.98 | −128.00 |
| 7 | 10 | 4 | 266 | 0.23 | **−214.50** | −0.81 | −230.00 |
| 8 | 8 | 4 | 266 | 0.24 | −288.00 | −1.08 | −296.00 |
| 9 | 5 | 4 | 266 | 0.32 | −291.00 | −1.09 | −295.00 |
| 10 | 10 | 5 | 266 | 0.26 | −292.50 | −1.10 | −300.00 |

The full 266-candidate cell (`sl >= 4`, both pairs eligible) is
uniformly worse under unlimited concurrency — more losers admitted
without slot filtering. The pileup of losing trades on 2026-09-22 (see
§5.5) drives the largest drawdowns.

### 5.4 Friday 2026-09-25 alone under executable prices

From `sweep_friday_only.csv` (both admission modes). Every combo is
net-negative. Two-slot best on Friday alone: TP=10 / SL=2 at **+4 pips**
(EURUSD-only, sub-4p GBPUSD minimum, 5 trades), which is inside noise
and would not be admissible on GBPUSD.

Top-10 combos on Friday alone, executable-price two-slot (from
`sweep_friday_only.csv`; the top-2 use SL below GBPUSD's 4p minimum):

| TP | SL | taken | wr | net pips | net/tr | max_dd |
|---:|---:|---:|:-:|---:|---:|---:|
| 10 | 3 | 9 | 0.33 | **+9.50** | +1.06 | −9.00 |
| 10 | 2 | 10 | 0.20 | **+4.00** | +0.40 | −6.00 |
| 10 | 4 | 21 | 0.29 | −2.50 | −0.12 | −28.00 |
| 8 | 3 | 12 | 0.25 | −3.00 | −0.25 | −12.00 |
| 8 | 2 | 13 | 0.15 | −6.00 | −0.46 | −12.00 |
| 10 | 5 | 19 | 0.32 | −7.50 | −0.39 | −30.00 |
| 10 | 7 | 16 | 0.38 | −8.50 | −0.53 | −39.00 |
| 5 | 2 | 13 | 0.15 | −12.00 | −0.92 | −12.00 |
| 8 | 4 | 21 | 0.29 | −12.00 | −0.57 | −32.00 |
| 10 | 6 | 18 | 0.33 | −14.50 | −0.81 | −34.00 |

The prior +34 headline sits at TP=8 SL=15 two-slot: **−61 pips** on my
full-context detection (26 candidates, 11 admitted), or **−46 pips**
on the apples-to-apples day-only detection (24 candidates, 10
admitted, §5.1).

### 5.5 Per-day contribution under two-slot

Best combo respecting broker minimum (TP=10 / SL=4):

| date | trades | wins | losses | UNR | TP hits | SL hits | net pips |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-14 | 21 | 5 | 16 | 0 | 5 | 16 | −14.00 |
| **2026-09-15** | **20** | **6** | **14** | **0** | **6** | **14** | **+4.00** |
| 2026-09-16 | 26 | 5 | 18 | 3 | 5 | 18 | −22.00 |
| 2026-09-17 | 23 | 5 | 18 | 0 | 5 | 18 | −22.00 |
| 2026-09-18 | 14 | 3 | 11 | 0 | 3 | 11 | −14.00 |
| 2026-09-20 | 1 | 0 | 1 | 0 | 0 | 1 | −4.00 |
| 2026-09-21 | 21 | 4 | 17 | 0 | 4 | 17 | −28.00 |
| 2026-09-22 | 22 | 3 | 19 | 0 | 3 | 19 | −46.00 |
| 2026-09-23 | 22 | 5 | 17 | 0 | 5 | 17 | −18.00 |
| 2026-09-25 | 21 | 6 | 15 | 0 | 5 | 15 | −2.50 |
| **total** | **191** | **42** | **146** | **3** | **41** | **146** | **−166.50** |

The single positive day (Sep 15) contributes +4 pips against a
two-week loss of −166.5 pips. Sep 22 alone is −46 pips, but no single
day dominates. Nine of ten entry-dates are net-negative.

Aggregating across all 45 (TP,SL) combos, per-date net pips:

| date | Σ net over 45 combos |
|---|---:|
| 2026-09-14 | −2161 |
| 2026-09-15 | **+70** |
| 2026-09-16 | −1239 |
| 2026-09-17 | −1990 |
| 2026-09-18 | −856 |
| 2026-09-20 | −45 |
| 2026-09-21 | −1698 |
| 2026-09-22 | −3154 |
| 2026-09-23 | −2143 |
| 2026-09-25 | −1385 |

Only 2026-09-15 was aggregate-positive. **Best single day for any
combo**: TP=10 / SL=13 on 2026-09-15 → +57 pips, but the same combo
across the window totals **−458.5 pips**. No positive-day pattern
concentrated on any particular direction, session, or day of week is
visible from ten days.

### 5.6 Per-pair × per-direction breakdown at a representative stop

TP=8, SL=15, executable-price, no admission cap (uses every candidate):

| pair | direction | taken | wr | net pips | net/tr | max_dd |
|---|---|---:|:-:|---:|---:|---:|
| GBPUSD | BUY  | 69 | 0.33 | **−467.10** | −6.77 | −467.10 |
| GBPUSD | SELL | 69 | 0.58 | −73.00 | −1.06 | −171.00 |
| EURUSD | BUY  | 72 | 0.58 | −75.70 | −1.05 | −164.00 |
| EURUSD | SELL | 56 | 0.71 | **+80.00** | +1.43 | −74.00 |

**GBPUSD BUY** is the clear single loss source across the whole sweep
— **every** (TP, SL ≥ 4) cell in `sweep_per_pair_dir.csv` is deeply
negative for GBPUSD BUY, with the loss growing monotonically in SL
(−128 → −411 pips as SL widens from 4 → 16 at TP=5). This pair ×
direction alone contributes more than the entire two-week loss for
the wider stops on the combined-pairs table; the other three
pair × direction cells partially offset it.

**EURUSD SELL is positive at wide stops**. Positive cells among
broker-valid (SL ≥ pair minimum) combos:

| pair | direction | TP | SL | taken | wr | net pips |
|---|---|---:|---:|---:|:-:|---:|
| EURUSD | SELL | 10 | 16 | 56 | 0.70 | **+115.50** |
| EURUSD | SELL |  8 | 16 | 56 | 0.73 | **+88.00** |
| EURUSD | SELL | 10 | 15 | 56 | 0.66 | +82.50 |
| EURUSD | SELL |  8 | 15 | 56 | 0.71 | +80.00 |
| EURUSD | SELL | 10 | 14 | 56 | 0.64 | +77.50 |
| EURUSD | SELL |  8 | 14 | 56 | 0.70 | +74.00 |
| EURUSD | SELL | 10 | 13 | 56 | 0.59 | +28.50 |
| EURUSD | SELL |  8 | 13 | 56 | 0.64 | +28.00 |
| GBPUSD | SELL | 10 |  4 | 69 | 0.29 |  +8.00 |
| EURUSD | SELL |  5 | 16 | 56 | 0.77 |  +7.00 |

This is 10 positive cells out of 39 broker-valid × 3 TPs × 2 pairs ×
2 directions = 156 cells. All positive cells except one are EURUSD
SELL; the single GBPUSD SELL cell is at the tightest 4p stop and is
inside noise. Interpreting this as a rule: **EURUSD SELL at BB upper
band with TP∈{8,10} and SL≥14 was profitable on these ten days**, but
56 candidates is not enough to reject the null that this is a
sample-fluke of a downtrending EURUSD window. The combined-pairs table
(§5.2, §5.3) shows the aggregate is still negative because GBPUSD BUY
overwhelms the EURUSD-SELL edge.

## 6. £2/pip illustration

Not the point of this study, but for scale — at £2 per pip, whole-position:

| combo | scope | net_pips_2wk | £@£2/p |
|---|---|---:|---:|
| TP=10 SL=4 | two-slot | −166.5 | **−£333.00** |
| TP=5 SL=3 | two-slot (EUR only) | −87.0 | **−£174.00** |
| TP=10 SL=13 | two-slot | −458.5 | **−£917.00** |
| TP=8 SL=15 | two-slot | −320.0 | **−£640.00** |

## 7. Reproducibility

```bash
cd /opt/tradingbot/reports-public/2026-09-27_bb_scalp_2wk
# All fetches are idempotent — existing files are skipped.
python3 fetch_ig_bidask.py probe --symbol GBPUSD
python3 fetch_ig_bidask.py day   --date 2026-09-25 --resolution MINUTE
python3 fetch_ig_bidask.py range --start 2026-09-14 --end 2026-09-23 --resolution MINUTE_5
python3 run.py
python3 verify_mid_friday.py    # sanity: TP=8 SL=15 Fri two-slot on mid rule
python3 friday_reproduce.py     # apples-to-apples window
```

Environment: `ig_auth.get_ig_session()` reuses the bot's existing
authenticated session (DEMO SPREADBET account Z3G4CJ, `IG_ACC_TYPE=DEMO`
from `.env`, never printed). No orders. No config writes.

## 8. What extra data would move the conclusion

1. **A larger date window** — the whole point of the exercise. Two
   weeks × 266 candidates is not enough to distinguish spread noise
   from rule signal. Once next week's allowance quota is available, a
   month-scale replay is straightforward from the same fetcher.

2. **Thursday 2026-09-24** — excluded here only because allowance ran
   out at 171 of 10 000 remaining after the 8 × 5m + Friday 1m fetches.
   Adding it after the weekly reset (2026-10-04) would close a small
   gap; every other combo already has 9 of the 10 target dates.

3. **Real per-second bid/ask on the 5-minute bars** would remove the
   0-ambiguous-cases guarantee we already have (no same-bar TP+SL
   occurred in this sample) but is not load-bearing for the
   conclusion. The rule is losing on 5-minute-executable prices; a
   more granular resolver will not turn losers back into winners.

4. **Historical per-timestamp `minNormalStopOrLimitDistance`** would
   let us say which historical entries actually saw the current 4/2p
   minimum vs a wider one. This changes the "broker-valid" flag but
   not the net-pip figures — trades already resolved at their price
   path regardless of admissibility.

5. A **direction-conditioned rule** that suppresses GBPUSD BUYs in an
   uptrend, or gates on a higher-timeframe bias, would test whether
   the profitable EURUSD-SELL subset in §5.6 survives outside this
   sample.
