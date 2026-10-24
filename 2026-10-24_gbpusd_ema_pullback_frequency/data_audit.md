# Historical data audit — GBPUSD EMA pullback research

Prepared: 2026-10-24
Working tree: `/home/autobot/tradingbot-wt/ema-pullback-freq-20261024/`
Branch: `research/gbpusd-ema-pullback-frequency-20261024` (parent: `nms/v3-prod-upgrade-20261013`)

## 1. Frozen manifest check (requested)

- **Expected path:** `outputs/freeze/tick_correction_manifest.csv`
- **Expected SHA-256:** `16701ce7a150a51e743b88b2ee4737dd1ff930cbfb374bcbbfe0127c0626acdc`
- **Status in this repo:** **FILE NOT PRESENT.** `/opt/tradingbot/outputs/freeze/` does not exist in the current working tree, and no file named `tick_correction_manifest.csv` is anywhere under `/opt/tradingbot/`.
- **Related artefacts that DO exist in prior reports branches:**
  - `reports-public/2026-09-28_bb_pierce_rsi/tz.py`
  - `reports-public/2026-09-28_bb_pierce_rsi/tz_verify.py`
  (These codify the 2026-09-28 tick-timezone finding: 2024/2025 ticks need +5h; 2026-01→03-07 are UTC; 2026-03-08→03-31 need +5h; 2026-04-01+ mid-price ticks are 2-dp rounded.)

**Implication for this research:** the frozen tick manifest is unavailable, so tick-level analysis cannot be anchored to it. **This study operates exclusively on completed CANDLE data**, not on raw ticks, so the tick timestamp manifest does not gate the H1/M5 EMA calculations. The TZ findings from the ticks remain a reason to be cautious about any downstream validation that reaches back into ticks — none of that is required for opportunity counting.

If the user requires the tick manifest to be regenerated and verified before accepting candle-derived results, they must direct that explicitly; this report does not synthesise a replacement.

## 2. Candle datasets inspected

| Dataset | Path | Date range | Day files | Bar interval |
|---|---|---|---|---|
| `candles_ext_v2` | `data/candles_ext_v2/GBPUSD/` | 2024-01-01 → 2025-12-31 | 627 | 5-min |
| `candles` | `data/candles/GBPUSD/` | 2026-01-01 → 2026-10-23 | 229 | 5-min |
| `ohlc` | `data/ohlc/GBPUSD/{5M,15M,1H,4H,D1}/` | 2026-01-01 → 2026-04-10 (short) | — | multiple |

### Schema (both `candles_ext_v2` and `candles`)
```
timestamp,open,high,low,close
2024-06-03T00:00:00+00:00,12759.60,12760.80,12759.00,12760.60
```
Timestamps are **UTC** (`+00:00`). Prices are encoded as **pipettes** (raw price × 10000). 1 pip = 1.0 price unit. One day = 288 bars × 5 min when fully covered. Weekends roll between Friday 22:00 UTC and Sunday 22:00 UTC per standard FX convention; this is reflected by the trading-day file layout.

### `ohlc/` excluded
Per the standing research record, `ohlc/` was previously excluded for a material price offset. It is also truncated at 2026-04-10 and does not cover the full study window. **Not used.**

## 3. Combined coverage

- **Total trading day files:** 627 (candles_ext_v2) + 229 (candles) = **856** calendar day files
- **Date span:** 2024-01-01 → 2026-10-23 (just under 3 years)
- **Candle source split:**
  - 2024-01-01 → 2025-12-31: `candles_ext_v2/GBPUSD/<date>.csv` (consistent single source)
  - 2026-01-01 → 2026-10-23: `candles/GBPUSD/<date>.csv` (consistent single source)
  - The source changes at the 2025/2026 boundary. Both directories carry a 5-min OHLC schema and both are UTC. See §6 for the provenance check.

## 4. H1 derivation strategy

Rather than depending on the (fragmented, truncated) `ohlc/1H/` tree, **H1 bars are rolled from the same M5 series** used for the M5 side of the strategy. This guarantees internal consistency of H1 and M5 — the two timeframes are, by construction, from one data source.

Rolling rule (closed-candle, no leakage):
- H1 bar `t` (anchored at the top of UTC hour `t`) is built from the twelve M5 bars with timestamps `[t, t+55 min]`.
- The H1 bar is **considered CLOSED and available for decisions** only at the moment the M5 bar for `t+55 min` closes (i.e. at wall time `t+1h`). The M5 bar inside the current hour is NEVER permitted to influence H1 trend decisions for the hour it belongs to.
- Any H1 EMA value for hour `t` is computed from EMA state updated with H1 bars whose closed time ≤ `t`. The EMA value is "available" for M5 decisions in hour `t+1` and later.
- Days spanning weekend rollovers are joined into a continuous H1 series by preserving the EMA state across weekends (no re-seeding).

## 5. Day exclusions

The following day categories exist in the raw files:

| Category | Example | Treatment |
|---|---|---|
| Full trading day (288 M5 bars) | 2024-06-03 | **INCLUDED** |
| Short Friday / holiday close | 2024-12-27 (265 bars, ends 21:55) | **INCLUDED** (partial but internally continuous — short end treated as early session close) |
| Sunday open (session begins ~22:00 UTC) | 2026-02-15 (85 bars from 17:00) | **INCLUDED** — contributes to the following Monday as an evening-prior session |
| Monday with no previous-weekend prefix | 2024-01-01 | **INCLUDED** |
| True market closures (Saturday) | 2024-01-06, 2024-01-13 … | **ABSENT by filename** (correct) |

Within the day CSVs for which a 288-bar full-day was spot-checked, M5 bar continuity was perfect (gaps=0). The strategy requires only closed-candle sequencing, so a short close-of-session does not corrupt detection — any pullback not yet confirmed by the final M5 bar remains uncounted.

## 6. BID vs MID provenance (unresolved, best effort)

Neither CSV header nor filename declares BID vs MID. Candle-generation code in the repo:
- `candle_builder.py` lives in the main tree and ingests the live tick stream (which is MID per `tz.py` corrections after 2026-04-01 where ticks are 2-dp rounded).
- `candles_ext_v2/` filenames do not advertise a side, and the archived build predates the tick-TZ work.

**Assumption applied here:** both datasets are mid-price candles (the engine never persists a dedicated bid series into these paths — the only BID/ASK material in the repo is the live tick side).

**Mitigation:** every outcome statistic (MFE/MAE / target-reached) is reported with an **explicit mid-only caveat** and compared to a per-pip spread allowance. No `realised_pnl` is claimed. See `research_report.md` for the spread discussion.

If the user confirms the candle series are BID, the direction labels do not change (BUY and SELL are symmetric by construction) but target-reached statistics must be re-interpreted (BID candles underestimate BUY MFE and overestimate SELL MFE by roughly one spread).

## 7. Daily-time semantics

All CSV timestamps are UTC. The research question references "UK trading hour" so a mapping to Europe/London is applied for aggregation only. The strategy itself is UTC-indexed:
- 2024-03-31 00:00 UTC → 01:00 BST (clocks forward)
- 2024-10-27 02:00 BST → 01:00 UTC (clocks back)

The DST shift is applied at the UK-local aggregation layer (session binning). The underlying candle sequencing never shifts.

## 8. Summary

| Field | Value |
|---|---|
| Source datasets | `data/candles_ext_v2/GBPUSD` + `data/candles/GBPUSD` |
| Date range | 2024-01-01 → 2026-10-23 |
| Number of day files | 856 |
| Days excluded | 0 at this stage (short-close days retained; see §5) |
| Missing candle periods | None observed within-day for sampled full days (gaps=0 at 5-min granularity) |
| Timestamp corrections applied | None — candles are UTC and consistent |
| BID/MID provenance | Assumed MID — not documented at source. Mid-only caveat propagates to outcome stats |
| H1 and M5 same source | **Yes** — H1 derived from same M5 CSV |
| Frozen tick manifest | **NOT PRESENT at expected path.** Study operates on candles, not ticks. See §1. |
