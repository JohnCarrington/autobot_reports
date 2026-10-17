# Pivot Calculation Audit — READ-ONLY

**No code change, no configuration change, no deployment.**

- Generated: 2026-10-17
- Branch: `research/level-arrival-turn-20261017`
- Trigger: discrepancy between SRR V1 R3 for 2026-10-16 (1.335160) and the operator's chart R3 (≈ 1.3380)

Investigation finds **THREE DISTINCT pivot sets in play** for the 2026-10-16 trading session, plus a chart value from an **UNKNOWN** methodology. Only one of the four is both authoritative-in-production AND fresh — and that one wasn't fresh either (last update 2026-10-14 at 03:00:05 UTC).

---

## 1. Formula — common to live and replay (FACT)

File: `/opt/tradingbot/ig_daily_pivots.py:141-150`

```python
def compute_classic_floor(H, L, C) -> ClassicFloorPivots:
    P = (H + L + C) / 3.0
    R1 = 2 * P - L
    S1 = 2 * P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
    R3 = H + 2 * (P - L)
    S3 = L - 2 * (H - P)
```

**Classic Floor Pivots.** Pure function, used identically by both the live writer (`build_pivots_payload`) and the SRR V1 replay (`srr_v1_replay._pivot_dict_for → compute_classic_floor`). **No divergence at the formula level.**

---

## 2. Live AutoBot pivot values on 2026-10-16 at admission time (FACT)

### 2.1 Authoritative file

`/opt/tradingbot/cache/htf/daily_pivots.json` — written by `ig_daily_pivots.write_pivots()` (file writer defined at `ig_daily_pivots.py:605-619`). Also mirrored into `/opt/tradingbot/cache/session_trend_GBPUSD.json:daily_pivots` by `session_trend.set_daily_pivots()`.

### 2.2 File contents (read 2026-10-17)

```
trading_date        : "2026-10-14"
written_at_utc      : "2026-10-14T03:00:05.066729+00:00"   ← 2 days stale on 10-16
schema_version      : "ig_daily_pivots.v1"
pairs.GBPUSD.previous_bar.snapshotTimeUTC : "2026-10-14T00:00:00"
pairs.GBPUSD.previous_bar.ask : {open: 13255.0, high: 13272.1, low: 13253.1, close: 13272.0}
pairs.GBPUSD.previous_bar.bid : {open: 13253.5, high: 13271.2, low: 13251.6, close: 13271.1}
pairs.GBPUSD.pivots_ask : P=13265.73 R1=13278.37 R2=13284.73 R3=13297.37
                           S1=13259.37 S2=13246.73 S3=13240.37
pairs.GBPUSD.pivots_bid : P=13264.63 R1=13277.67 R2=13284.23 R3=13297.27
                           S1=13258.07 S2=13245.03 S3=13238.47
```

The `cache/session_trend_GBPUSD.json:daily_pivots` dict matches `pivots_ask` **byte-identically** (reads P=13265.73, R3=13297.37) — because `session_trend_integration.py` copies the ASK pivots into the session_trend state.

### 2.3 Why the live cache was 2 days stale (INFERENCE)

`ig_daily_pivots.scheduled_run_once()` (around `ig_daily_pivots.py:810-860`) fires once per UTC date at the scheduled hour (`DAILY_PIVOTS_SCHED_HOUR=3`, i.e. 03:00 UTC). Precondition: `now_utc >= 03:00 UTC` on a new UTC date AND the AutoBot process is running continuously.

The last write was 2026-10-14 at 03:00:05 UTC. No new write happened at 03:00 UTC on 2026-10-15 or 2026-10-16. Possible causes:
- AutoBot process did not run through the 03:00 UTC daily scheduler on 10-15 or 10-16 (restart / crash / sleep).
- IG REST fetch failed on 10-15 or 10-16 (auth / rate / connectivity). The scheduler **marks the date as fired even on exception paths**; if `run_daily_fetch` returned a diagnostic without a successful `write_pivots`, the file would not update.

The pivot-writer logs would resolve this exactly. **Not available in the research tree** — would need the autobot stdout/stderr log stream from 10-14 03:00 UTC through 10-16 03:00 UTC. [UNKNOWN at log level.]

### 2.4 The "previous_bar" OHLC is anomalous (FACT)

Live file reports `previous_bar.ask: {O=13255.0, H=13272.1, L=13253.1, C=13272.0}` — a **19-pip range** labelled `snapshotTimeUTC=2026-10-14T00:00:00`.

No 5m-MID aggregated window in `/opt/tradingbot/data/candles/GBPUSD/` reproduces an OHLC with a 19-pip range for any plausible 2026-10-13 → 2026-10-14 window. Representative aggregations (MID basis):

| window | n bars | H | L | C | range |
|---|---:|---:|---:|---:|---:|
| [10-13 22:00 → 10-14 00:00) UTC (2 h) | 24 | 13257.55 | 13248.10 | 13256.95 | 9.5 p |
| [10-13 20:00 → 10-14 00:00) UTC (4 h) | 48 | 13260.45 | 13248.10 | 13256.95 | 12.4 p |
| [10-13 00:00 → 10-14 00:00) UTC day | 288 | 13260.45 | 13204.25 | 13256.95 | 56.2 p |
| [10-13 22:00 → 10-14 22:00) UTC IG D1 | 288 | 13275.15 | 13136.35 | 13188.95 | 138.8 p |

**None matches live's 19-pip range.** The IG-REST daily-bars API returned an OHLC that AutoBot's own 5m aggregator does not reproduce from the same data range. The IG daily API's "snapshotTimeUTC=2026-10-14T00:00:00" bar is some IG-specific derivation (possibly a reduced-session Columbus-Day fragment, since 2026-10-13 is Columbus Day in the US and IG's FX hours can collapse). [INFERENCE — would need IG-side bar-definition docs to resolve.]

---

## 3. SRR V1 replay values and a bug in the Friday regression script (FACT)

### 3.1 As-run (`scripts/srr_v1_friday_regression.py`)

The script loads bars with:
```python
bars = _load_bars("2026-10-15") + _load_bars("2026-10-16")
```

For `trading_day = 2026-10-16`, `srr_v1_replay._prior_trading_day()` returns `2026-10-15`, and `_ig_d1_window(2026-10-15)` returns `[2026-10-14T22:00, 2026-10-15T22:00)` UTC. **But bars from `[2026-10-14T22:00, 2026-10-15T00:00)` are in the file `2026-10-14.csv`, which was NOT loaded by the regression script.** The replay therefore operated on a **truncated 22-hour window** `[2026-10-15T00:00, 2026-10-15T22:00)`.

### 3.2 As-run OHLC and pivots (from `reports/srr_v1/friday_regression_20261017.json`)

Truncated window (missing first 2 hours of the full D1 window):
```
O=13229.15  H=13279.50  L=13221.05  C=13270.75   range 58.75 p
→ P=13257.10  R1=13293.15  R2=13315.55  R3=13351.60
  S1=13234.70  S2=13198.65  S3=13176.25
```

### 3.3 CORRECTED replay (full IG D1 window with 10-14 bars loaded)

```
Window [2026-10-14T22:00, 2026-10-15T22:00) MID candles — 264 bars
O=13229.15  H=13279.50  L=13186.75  C=13270.75   range 92.75 p
→ P=13245.67  R1=13304.58  R2=13338.42  R3=13397.33
  S1=13211.83  S2=13152.92  S3=13119.08
```

The missing 2-hour chunk `[2026-10-14T22:00, 2026-10-15T00:00)` pushed the LOW from 13186.75 down to the real 10-15 D1 low. **L drops by 34.3 pips; R3 rises by 45.7 pips.**

### 3.4 Bug status

**The regression script is incorrect.** It should load `_load_bars("2026-10-14")` as well so the IG D1 window is fully covered. The replay FUNCTION `build_snapshot_for` is correct given the inputs it receives; the error is in the caller. **Per directive: NOT fixing. Reporting only.**

The Stage 2 published report (`v3_improvement_stage2_srr_v1_20261017.md`) therefore shows the truncated-window pivots. The CORRECTED pivots are what the SRR V1 replay would have produced had the script loaded the right bars.

---

## 4. Side-by-side reconciliation (FACT)

### 4.1 OHLC inputs

| source | basis | window | H | L | C | range |
|---|---|---|---:|---:|---:|---:|
| LIVE `daily_pivots.json:previous_bar.ask` | ASK | IG labelled `2026-10-14T00:00:00` (anomalous 19 p) | 13272.10 | 13253.10 | 13272.00 | **19.0 p** |
| LIVE `daily_pivots.json:previous_bar.bid` | BID | same as above | 13271.20 | 13251.60 | 13271.10 | 19.6 p |
| SRR replay AS-RUN | MID | `[2026-10-15T00:00, 2026-10-15T22:00)` (**truncated** — missing 2 h) | 13279.50 | 13221.05 | 13270.75 | 58.75 p |
| SRR replay CORRECTED | MID | `[2026-10-14T22:00, 2026-10-15T22:00)` **full D1** | 13279.50 | 13186.75 | 13270.75 | 92.75 p |

### 4.2 Pivots

| source | P | R1 | R2 | R3 | S1 | S2 | S3 | R3 as decimal |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| LIVE AutoBot (ASK) | 13265.73 | 13278.37 | 13284.73 | **13297.37** | 13259.37 | 13246.73 | 13240.37 | 1.329737 |
| LIVE AutoBot (BID) | 13264.63 | 13277.67 | 13284.23 | 13297.27 | 13258.07 | 13245.03 | 13238.47 | 1.329727 |
| SRR replay AS-RUN | 13257.10 | 13293.15 | 13315.55 | **13351.60** | 13234.70 | 13198.65 | 13176.25 | 1.335160 |
| SRR replay CORRECTED | 13245.67 | 13304.58 | 13338.42 | **13397.33** | 13211.83 | 13152.92 | 13119.08 | **1.339733** |
| CHART (operator-reported, ≈) | — | — | — | **≈ 13380** | — | — | — | **≈ 1.3380** |

### 4.3 Reasons for every discrepancy

| pair | pip difference in R3 | reason |
|---|---:|---|
| LIVE vs SRR AS-RUN | +54.23 | Live uses a bar from `snapshotTimeUTC=2026-10-14T00:00:00` labelled for the 10-14 trading session (2 days stale). AS-RUN replay uses a truncated 10-15 session window. Different source days + different windows. |
| LIVE vs SRR CORRECTED | +99.96 | Same as above — plus the AS-RUN replay also loses pips from the truncated window. CORRECTED replay uses the full 10-15 D1 window which is the correct bar for the 10-16 session. |
| SRR AS-RUN vs CORRECTED | +45.73 | The missing 2 hours `[2026-10-14T22:00, 2026-10-15T00:00)` contained the session low (13186.75 vs truncated-window low 13221.05). Lower L raises R3 via `R3 = H + 2(P - L)`. |
| LIVE (ASK) vs LIVE (BID) | −0.10 | Half-spread ≈ 0.1 pip at the IG-recorded ASK/BID differential for that bar (not the usual 0.75-1.5 p spread, because the H/L/C offsets differ in the IG-reported bar). |
| CORRECTED replay vs CHART | ≈ −17 | **UNKNOWN**. No tested standard methodology (Classic / Camarilla / Woodie / Fibonacci) with any UTC-aligned session boundary tested here produces R3 ≈ 1.3380. |

### 4.4 Alternative pivot methodologies tested on 10-14 22:00 → 10-15 22:00 MID D1 bar

```
Classic Floor:    P=13245.67  R1=13304.58  R2=13338.42  R3=13397.33
Camarilla:        R1=13279.25  R2=13287.75  R3=13296.26  R4=13321.76
Woodie:           Pw=13251.94  R1=13317.13  R2=13344.69
Fibonacci:        Pf=13245.67  R1=13281.10  R2=13302.99  R3=13338.42
```

**None approximates 13380.**

### 4.5 Alternative session boundaries tested (Classic Floor, MID)

```
IG D1 [10-14 22:00 → 10-15 22:00)   : R3 = 13397.33
UTC calendar [10-15 00:00 → 10-16 00:00): R3 = 13351.87
NY close [10-14 21:00 → 10-15 21:00)   : R3 = 13402.27
London close [10-14 17:00 → 10-15 17:00): R3 = 13428.48
London close BST [10-14 16:00 → 10-15 16:00): R3 = 13444.08
```

**None approximates 13380.** The chart's methodology cannot be derived from any formula × boundary combination tested here.

---

## 5. Chart R3 ≈ 1.3380 — status: UNRESOLVED (FACT)

Per the directive: *"If its settings cannot be established, report that comparison as unresolved rather than assuming the chart is authoritative."*

**The chart's R3 ≈ 1.3380 cannot be reproduced from any standard pivot methodology × session boundary I tested, using the price source available on this host.** Possibilities (all speculative):

- Chart's trading platform uses a non-classical pivot variant with proprietary parameters.
- Chart's broker provides its own daily-OHLC source that differs from AutoBot's 5m MID aggregation AND from IG's daily REST API.
- The "≈ 1.3380" is a visual approximation from the chart screenshot and the true chart value is some nearby but different number.
- Chart overlay reads from an entirely different source (e.g. a weekly pivot or a mid-session pivot).

**Required to close:** the chart's pivot-indicator settings (formula + source timeframe + session boundary) or raw data from the chart platform. Not available in the AutoBot repo. **Do NOT assume the chart is authoritative.**

---

## 6. Point-in-time correctness verification (FACT)

### 6.1 Replay uses only prior-session data

`srr_v1_replay._prior_trading_day()` returns `trading_day - 1 business day`. For `trading_day = 2026-10-16` (Friday), prior = `2026-10-15` (Thursday). `_ig_d1_window(2026-10-15)` → `[2026-10-14T22:00, 2026-10-15T22:00)` UTC. **All bars in this window have `ts < 2026-10-16T14:35:28` (the critical trade admission time).** No future bar is read.

Independently verified by the test `tests/unit/test_srr_v1.py::TestNoLookAhead::test_assess_does_not_touch_future_bars` which monkey-patches `load_structural_snapshot` to raise on invocation during `assess()`.

### 6.2 Live writer uses prior IG daily bar

`previous_daily_bar(prices) = prices[-1]` returns the most recently CLOSED IG daily bar from the REST response. [FACT, `ig_daily_pivots.py:501-512`.] IG only returns closed bars via `/prices` with a `pageSize` cap; no in-flight bar is included.

---

## 7. Recalculated 14:35 UTC BUY structural room — Friday 10-16

Entry: 13367.9, BUY. Opposing levels are those with price > entry.

### 7.1 With the LIVE pivot cache (what AutoBot ACTUALLY saw at admission)

```
P=13265.73 R1=13278.37 R2=13284.73 R3=13297.37
S1=13259.37 S2=13246.73 S3=13240.37
london_open = 13310.45
```

All pivots are BELOW entry 13367.9. London_open is BELOW. **No opposing structural level.** `nearest_major_level = None`. `structural_room_pips = None`. `assessment_reason = "no_opposing_level"`.

### 7.2 With the CORRECTED replay pivots (fresh 10-14 22:00 → 10-15 22:00 MID D1)

```
P=13245.67 R1=13304.58 R2=13338.42 R3=13397.33
S1=13211.83 S2=13152.92 S3=13119.08
london_open = 13310.45
```

- R3 = 13397.33 is **29.43 pips** above entry 13367.9.
- R2 = 13338.42 is below entry (not opposing).
- All other pivots are below entry.
- `nearest_major_level = DAILY_PIVOT_R3 @ 13397.33`
- `nearest_major_distance_pips = 29.4`
- `structural_reward_risk = 29.4 / 12 = 2.45`
- `level_relationship = UNKNOWN` (entry > 5 p from level)

### 7.3 With the CHART-reported R3 = 1.3380

If chart R3 = 13380, then:
- distance = 13380 − 13367.9 = **12.1 pips** above entry.
- `structural_reward_risk = 12.1 / 12 ≈ 1.01`
- `level_relationship = UNKNOWN` (12.1 > 5 p; or TESTING if we re-tune the threshold)

### 7.4 Verdict

The directive's "approximately 12.1 pips" **matches the chart R3 (1.3380), not any computed value**. The chart methodology remains **UNRESOLVED**.

Depending on which pivot source is treated as authoritative:
- **LIVE cache (stale)**: no opposing structural level, SRR correctly reports None.
- **CORRECTED replay (fresh MID D1)**: 29.4 pips of room, R:R 2.45.
- **CHART R3**: 12.1 pips of room, R:R 1.01.

---

## 8. Fact / Inference / Unknown classification

| finding | category |
|---|---|
| Live `daily_pivots.json` was last written 2026-10-14 at 03:00:05 UTC — 2 days stale on 10-16 | **FACT** |
| Live writer uses `compute_classic_floor` on IG REST daily-bar ASK OHLC | **FACT** |
| Live cache `previous_bar` has 19-pip range (anomalous vs 5m MID aggregates) | **FACT** |
| SRR V1 replay (CORRECTED, MID basis, full 10-14 22:00 → 10-15 22:00 D1): R3 = 13397.33 | **FACT** |
| SRR V1 replay AS-RUN in Friday regression used a truncated 22h window → R3 = 13351.60 | **FACT** |
| The regression script `scripts/srr_v1_friday_regression.py` does not load `2026-10-14.csv` bars | **FACT** |
| Chart R3 ≈ 1.3380 does not match any tested formula × boundary with available price source | **FACT** |
| Reason the live writer didn't run on 10-15 or 10-16 at 03:00 UTC | **UNKNOWN** (needs autobot stdout/stderr log for 10-14→10-16 03:00 UTC) |
| Chart's actual pivot methodology, source timeframe, and session boundary | **UNKNOWN** (not available in AutoBot repo) |
| Which pivot set the operator intended for the Stage 1 forensic "12.1 p" expectation | **INFERENCE** — matches the chart R3 at 1.3380, not the live or replay values |

---

## 9. Boundary statement — nothing changed

- `/opt/tradingbot/ig_daily_pivots.py` **not modified**.
- `/opt/tradingbot/session_trend.py` **not modified**.
- `/opt/tradingbot/cache/htf/daily_pivots.json` **not modified**.
- `/opt/tradingbot/cache/session_trend_GBPUSD.json` **not modified**.
- `scripts/srr_v1_friday_regression.py` bug **not fixed** (reported only).
- No `.env` change. No service touch. No deployment.

This audit is read-only. **STOP after reporting.**

### 9.1 Operator decisions implied by this report (NOT taken)

The following remain the operator's call, outside this audit:

1. Whether to investigate why the pivot scheduler stopped writing after 2026-10-14 at 03:00 UTC (requires autobot process logs).
2. Whether to fix the regression script's bar-loading bug and republish the Stage 2 report.
3. Whether to establish the chart's pivot methodology (settings on the chart platform).
4. Whether to add a staleness monitor to the live SRR cache so that pivots older than N hours produce an alert.

*— end of pivot audit —*
