# GBP/USD Blocked‑Trade Outcome Audit — 2026‑11‑05

**Scope:** Read‑only retrospective audit of every GBP/USD trading opportunity that AutoBot
or the Bounce Family generated on Thursday 2026‑11‑05 and that was prevented from reaching
live execution. For each opportunity we identify the blocking mechanism, reconstruct the
realistic hypothetical outcome from the 5‑minute candle feed, and compare mechanism
contributions.

- **Investigation window:** 2026‑11‑05 00:00 UTC → 2026‑11‑05 18:30 UTC (live data).
- **Data sources:** `logs/v3_events.jsonl`, `logs/nms_watch_state.jsonl`,
  `logs/nms_exhaustion.jsonl-20261105`, `logs/nms_second_gate.jsonl`,
  `logs/bb_pierce_trades.jsonl`, `logs/bb_bounce_lifecycle.jsonl`, `logs/signal_log.jsonl`,
  `/opt/bb_bounce/reports/2026-11-05.csv`, systemd journal for `BB_BOUNCE_FILTER_BLOCK`
  lines, `data/candles/GBPUSD/2026-11-05.csv` (true‑UTC 5‑minute OHLC).
- **Units:** IG points / FX pips are 1:1. Stake = £2.00 / pip, matching production.
- **No tick cache exists for today.** Tick archive stops at 2026‑04‑10. All hypothetical
  P&L therefore uses 5‑minute MID OHLC walk‑forward; where a single candle both reaches
  the stop and the target the row is marked INDETERMINATE (none occurred today — all
  resolutions were clean).

---

## 1. Executive answer to the central question

> *Did AutoBot reject profitable trading opportunities today because of unnecessary or
> incorrectly applied restrictions, and if so, precisely which restrictions and how much
> did they cost?*

**Yes.** One filter is responsible for almost all of the demonstrable damage:

| Filter | Blocks | TP20 wins | TP20 losses | Verdict | Cost (£2/pip) |
|---|---|---|---|---|---|
| **`bb_bounce_filters.v1_pressure_against`** | 12 | 10 | **0** | **HARMFUL** | **−£400 of foregone winners / £0 of losses prevented** |

Every other blocking mechanism today either paid for itself or was near neutral. The 11
GBP/USD trades that actually passed the gate stack today netted **−42.7 pips / −£85.30**
(nine closed standalone BB Bounce trades + one V3_BB_S SELL that hit its stop in 10 min).
Had `v1_pressure_against` not fired, those 10 additional SELL fills on the 04:00–07:20 UTC
London down‑move would have added **+£400** at the conservative 20‑pip take‑profit level
(and up to **+£560** at a 40‑pip target — seven of the ten hit 40p on candle MFE before any
retracement).

Supporting findings:

- **`WATCH_AND_WAIT`** (NMS v3) was activated 10:00:03 → 12:10:08 UTC on confirmed
  SELLING_EXHAUSTION after a 25‑pip down‑leg into `2w_high`. During that 2h10m window the
  NMS directional authority correctly refused 3 V3_EMA_S shorts (all 3 would have hit the
  12p SL). The **separate** matrix gate on the standalone BB service additionally refused
  one BUY at 11:45 UTC (`BLOCK:MATRIX:WATCH_AND_WAIT:WATCHED_TREND=DOWN`) — that BUY would
  have hit 20p TP (+32.7p MFE). Scorecard: 3 losers avoided, 1 winner blocked. **Small
  net gain (≈ +£24), but the LONG rejection shows the W&W block does not distinguish
  "watching DOWN trend for exhaustion" from "price is already reversing UP".**
- **`NMS second gate: v3_bb_range_only`** rejected 7 V3_BB candidates because
  state=TRADABLE_NON_RANGE/FLAT_OR_COMPRESSED. 6 of those 7 would have hit the SL;
  1 (V3_BB_L at 11:59) would have hit TP20 (+29.25p MFE). **Clear net positive (+£104
  avoided).** The WS2 scope-narrowing commit (`84f0882`) earns its keep today.
- **`SEI arbiter`** (Bounce Family, mode=authoritative deployed 2026‑11‑05 pm) refused 3
  V3_BB_S triggers because STANDALONE_BB or AUTOBOT_BB_PIERCE_RUN had already settled the
  event. All 3 SL‑hit. **This is deduplication, not a filter; its "avoided loss" number
  (−£72) is the cost of the duplicate orders it prevented, not filter edge.**
- **`NMS directional authority: BLOCK_TREND_NO_ESTABLISHED_DIRECTION`** ("no_trend") is
  responsible for 12 rejections. Its scorecard is genuinely mixed: 5W/6L/1 open at TP20
  → **+£56 net missed if allowed**. During the 07:00–09:14 London down‑move it blocked
  V3_EMA_S shorts that were correctly-timed and would have won; from 13:00 onwards it
  blocked a choppy range where SL‑hit outcomes dominated. **The filter is behaviourally
  indifferent — neither a reliable protector nor a reliable permitter.**

**Headline verdict:**
- *Remove `v1_pressure_against`* (set `BB_BOUNCE_V1_PRESSURE_ENABLED=0`): single-day
  expected improvement **+£400** (10 winners, 0 losses prevented).
- *Keep* `NMS second gate`, `NMS WATCH_AND_WAIT` (nms_directional_authority), `SEI
  arbiter`, `NMS wrong_direction`, `NMS exhaustion_only`. All were net-positive today.
- *Re-examine* `BLOCK_TREND_NO_ESTABLISHED_DIRECTION`. Today it had near-zero edge on
  12 attempts and cost £56 in missed net profit during a textbook London trend day. Its
  threshold or the "RANGE/NORMAL" classifier under which it fires needs recalibration.

---

## 2. Current flag state (confirmed by direct `.env` inspection)

| Flag | Value | Interpretation |
|---|---|---|
| `BB_BOUNCE_V1_PRESSURE_ENABLED` | **1** | **ACTIVE — produced today's harmful blocks** |
| `BB_BOUNCE_V1_PRESSURE_VETO_ENABLED` | 0 (default) | New opt-in veto (not the same flag; off by design) |
| `NMS_WATCH_AND_WAIT_ENABLED` | 1 | Active |
| `BB_BOUNCE_CASCADE_GATE_ENABLED` | 0 | Legacy cascade gate deliberately OFF |
| `GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED` | 0 | Legacy H1 counter gate OFF |
| `DIRECTION_FROM_NMS_SESSION_TREND` | 1 | NMS session-trend is directional authority |
| `BOUNCE_FAMILY_SEI_MODE` | `authoritative` | SEI arbiter LIVE (settled_by=* reject path active) |

`v1_pressure_against` is independent of the new `V1_PRESSURE_VETO` flag introduced earlier
today (see [[project_v1_pressure_veto_downgrade_20261105]]). The downgraded flag is
disabled by default, but the underlying **`v1_pressure_against` rule inside
`bb_bounce_filters.py` is still gated by `BB_BOUNCE_V1_PRESSURE_ENABLED=1` and is firing.**

---

## 3. Master ledger

**Event count:** 42 blocked events on 37 unique (5-min bar × side) opportunity buckets.
5 buckets had overlapping blocks from two mechanisms (shown in the "Also-blocked"
column). The one trade that passed every gate (14:41 V3_BB_S SELL, `deal_id
DIAAAAYS2L9E8AJ`, `BE-df28a54cefb3`) is included as the executed baseline.

Legend: `NMS-DIR:no_trend` = `BLOCK_TREND_NO_ESTABLISHED_DIRECTION`; `NMS-DIR:w&w` =
`BLOCK_WATCH_AND_WAIT`; `NMS-DIR:wrong` = `BLOCK_TREND_WRONG_DIRECTION`;
`NMS-DIR:exh_only` = `BLOCK_BOUNCE_STRONG_TREND_EXHAUSTION_DEVELOPING_ONLY`;
`NMS-SG:bb_range_only` = `stand_aside:v3_bb_range_only:…`;
`BB-FILTER:v1_pressure` = `bb_bounce_filters.py` rule `v1_pressure_against`;
`SEI:settled_elsewhere` = `BOUNCE_FAMILY_SEI_MODE=authoritative` arbiter reject.

</br>

| Time (UTC) | Source | Strategy | Dir | Entry | Block mechanism | Also-blocked? | MFE | MAE | TP20 | TP40 | Net pips @ TP20/SL12 (V3) or /SL20 (BB) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 04:10 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | SELL | 13493.85 | BB-FILTER:v1_pressure | — | 46.3 | 7.15 | TP_HIT | TP_HIT | **+20** |
| 04:20 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | SELL | 13493.75 | BB-FILTER:v1_pressure | — | 46.2 | 7.25 | TP_HIT | TP_HIT | **+20** |
| 04:25 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | SELL | 13493.15 | BB-FILTER:v1_pressure | — | 45.6 | 7.85 | TP_HIT | TP_HIT | **+20** |
| 06:40 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | SELL | 13490.65 | BB-FILTER:v1_pressure | — | 43.1 | 10.35 | TP_HIT | TP_HIT | **+20** |
| 06:45 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | SELL | 13489.55 | BB-FILTER:v1_pressure | — | 42.0 | 11.45 | TP_HIT | TP_HIT | **+20** |
| 07:03 | V3 | V3_BB_L | BUY | 13497.5 | NMS-SG:bb_range_only | NMS-DIR:no_trend | 3.5 | 12.25 | SL_HIT | SL_HIT | −12 |
| 07:03 | V3 | V3_EMA_L | BUY | 13497.5 | NMS-DIR:no_trend | NMS-SG:bb_range_only | 3.5 | 12.25 | SL_HIT | SL_HIT | −12 |
| 07:09 | V3 | V3_EMA_S | SELL | 13494.9 | NMS-DIR:no_trend | — | 47.35 | 0.75 | TP_HIT | TP_HIT | **+20** |
| 07:10 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | SELL | 13494.65 | BB-FILTER:v1_pressure | NMS-DIR:no_trend | 47.1 | 0.0 | TP_HIT | TP_HIT | **+20** |
| 07:14 | V3 | V3_EMA_S | SELL | 13488.9 | NMS-DIR:no_trend | BB-FILTER:v1_pressure | 41.35 | 3.25 | TP_HIT | TP_HIT | **+20** |
| 07:15 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | SELL | 13489.65 | BB-FILTER:v1_pressure | — | 42.1 | 0.0 | TP_HIT | TP_HIT | **+20** |
| 07:20 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | SELL | 13485.05 | BB-FILTER:v1_pressure | — | 37.5 | 1.7 | TP_HIT | OPEN | **+20** |
| 08:30 | V3 | V3_EMA_S | SELL | 13474.9 | NMS-DIR:no_trend | — | 27.35 | 11.85 | TP_HIT | OPEN | **+20** |
| 09:10 | V3 | V3_EMA_S | SELL | 13477.8 | NMS-DIR:no_trend | NMS-DIR:no_trend | 30.25 | 8.95 | TP_HIT | OPEN | **+20** |
| 09:14 | V3 | V3_EMA_S | SELL | 13470.9 | NMS-DIR:no_trend | NMS-DIR:no_trend | 23.35 | 12.9 | TP_HIT | SL_HIT | **+20** |
| 09:45 | V3 | V3_EMA_S | SELL | 13465.7 | NMS-DIR:no_trend | — | 18.15 | 18.1 | SL_HIT | SL_HIT | −12 |
| 10:45 | V3 | V3_EMA_S | SELL | 13457.7 | NMS-DIR:w&w | — | 10.15 | 26.1 | SL_HIT | SL_HIT | −12 |
| 11:10 | V3 | V3_EMA_S | SELL | 13458.8 | NMS-DIR:w&w | — | 11.25 | 25.0 | SL_HIT | SL_HIT | −12 |
| 11:20 | V3 | V3_BB_L | BUY | 13461.4 | NMS-SG:bb_range_only | BB-FILTER:v1_pressure | 0.05 | 13.85 | SL_HIT | SL_HIT | −12 |
| 11:20 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | BUY | 13461.35 | BB-FILTER:v1_pressure | NMS-SG:bb_range_only | 25.4 | 13.8 | TP_HIT | OPEN | **+20** |
| 11:25 | V3 | V3_EMA_S | SELL | 13457.4 | NMS-DIR:w&w | — | 9.85 | 26.4 | SL_HIT | SL_HIT | −12 |
| 11:45 | STANDALONE_BB | BB_BOUNCE | BUY | 13454.02 | MATRIX:w&w | — | 32.72 | 6.48 | TP_HIT | OPEN | **+20** |
| 11:59 | V3 | V3_BB_L | BUY | 13457.5 | NMS-SG:bb_range_only | — | 29.25 | 6.05 | TP_HIT | OPEN | **+20** |
| 12:11 | V3 | V3_BB_S | SELL | 13469.0 | NMS-SG:bb_range_only | — | 0.0 | 14.25 | SL_HIT | SL_HIT | −12 |
| 12:19 | V3 | V3_BB_L | BUY | 13479.5 | NMS-SG:bb_range_only | — | 3.75 | 19.25 | SL_HIT | SL_HIT | −12 |
| 12:30 | V3 | V3_BB_S | SELL | 13469.8 | NMS-SG:bb_range_only | — | 15.15 | 14.55 | SL_HIT | SL_HIT | −12 |
| 12:35 | V3 | V3_BB_S | SELL | 13460.2 | SEI:settled_elsewhere | — | 5.55 | 16.55 | SL_HIT | SL_HIT | −12 |
| 12:39 | V3 | V3_BB_L | BUY | 13471.2 | NMS-DIR:exh_only | NMS-DIR:wrong | 0.55 | 12.45 | SL_HIT | SL_HIT | −12 |
| 12:39 | V3 | V3_EMA_L | BUY | 13471.2 | NMS-DIR:wrong | NMS-DIR:exh_only | 0.55 | 12.45 | SL_HIT | SL_HIT | −12 |
| 13:19 | V3 | V3_EMA_S | SELL | 13455.8 | NMS-DIR:no_trend | — | 1.15 | 13.95 | SL_HIT | SL_HIT | −12 |
| 13:46 | V3 | V3_EMA_S | SELL | 13458.3 | NMS-DIR:no_trend | — | 2.25 | 12.85 | SL_HIT | SL_HIT | −12 |
| 14:15 | V3 | V3_BB_S | SELL | 13463.3 | NMS-SG:bb_range_only | — | 0.0 | 13.45 | SL_HIT | SL_HIT | −12 |
| 14:19 | V3 | V3_EMA_L | BUY | 13469.6 | NMS-DIR:wrong | — | 7.55 | 14.6 | SL_HIT | SL_HIT | −12 |
| **14:41** | **V3 (executed)** | **V3_BB_S** | **SELL** | **13457.6** | **EXECUTED (deal `DIAAAAYS2L9E8AJ`)** | — | 0.0 | 19.55 | SL_HIT | SL_HIT | **−9.95 (actual fill)** |
| 15:00 | V3 | V3_BB_S | SELL | 13458.8 | SEI:settled_elsewhere | — | 1.1 | 17.4 | SL_HIT | SL_HIT | −12 |
| 15:15 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | BUY | 13463.25 | BB-FILTER:v1_pressure | — | 23.5 | 5.8 | TP_HIT | OPEN | **+20** |
| 15:20 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | BUY | 13468.85 | BB-FILTER:v1_pressure | — | 17.9 | 11.4 | OPEN | OPEN | — |
| 15:35 | V3 | V3_BB_S | SELL | 13472.6 | SEI:settled_elsewhere | — | 15.15 | 13.45 | SL_HIT | SL_HIT | −12 |
| 16:49 | V3 | V3_EMA_L | BUY | 13477.2 | NMS-DIR:no_trend | — | 9.55 | 8.25 | OPEN | OPEN | — |
| 17:10 | V3 | V3_EMA_L | BUY | 13482.4 | NMS-DIR:no_trend | — | 4.35 | 13.45 | SL_HIT | SL_HIT | −12 |
| 17:25 | BB_BOUNCE_AUTOBOT | BB_BOUNCE | SELL | 13480.35 | BB-FILTER:v1_pressure | — | 11.4 | 6.4 | OPEN | OPEN | — |
| 17:44 | V3 | V3_EMA_L | BUY | 13484.2 | NMS-DIR:no_trend | — | 2.55 | 12.95 | SL_HIT | SL_HIT | −12 |

Raw CSV: [`master_ledger.csv`](./gbpusd_blocked_trades_audit_20261105_master_ledger.csv).

---

## 4. Mechanism scorecard (ranked by |NET_IF_ALLOWED| at TP20)

| Rank | Mechanism | Blocks | TP20 W / L | Missed profit | Avoided loss | **Net if removed** | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | `BB-FILTER:v1_pressure_against` | **12** | 10 / 0 | **+200 p / +£400** | 0 p / £0 | **+200 p (+£400)** | **HARMFUL — disable** |
| 2 | `NMS-SG:v3_bb_range_only` (WS2) | 7 | 1 / 6 | +20 p | −72 p | **−52 p (−£104)** | HELPFUL — keep |
| 3 | `NMS-DIR:w&w` (authority refuse SHORT) | 3 | 0 / 3 | 0 p | −36 p | **−36 p (−£72)** | HELPFUL — keep |
| 4 | `SEI:settled_elsewhere` (dedup) | 3 | 0 / 3 | 0 p | −36 p | **−36 p (−£72)** | Dedup, not an edge filter — keep |
| 5 | `NMS-DIR:no_trend` (`BLOCK_TREND_NO_ESTABLISHED_DIRECTION`) | 12 | 5 / 6 | +100 p | −72 p | **+28 p (+£56)** | **Behaviourally indifferent — recalibrate** |
| 6 | `NMS-DIR:wrong` | 2 | 0 / 2 | 0 p | −24 p | **−24 p (−£48)** | HELPFUL — keep |
| 7 | `NMS-DIR:exh_only` | 1 | 0 / 1 | 0 p | −12 p | **−12 p (−£24)** | HELPFUL — keep |
| 8 | `MATRIX:WATCH_AND_WAIT` (standalone BB) | 1 | 1 / 0 | +20 p | 0 p | **+20 p (+£40)** | Mild harm — not a full filter failure |

**Totals across all blocks** (TP20 baseline, V3 at 12-p SL, BB at 20-p SL):
- Gross missed profit: **+340 pips / +£680**
- Gross avoided loss: **−252 pips / −£504**
- **Net if all blocks were removed:** **+88 pips / +£176**

Removing *only* `v1_pressure_against` (keeping every other filter):
**+200 pips / +£400**.

Removing `v1_pressure_against` + recalibrating `NO_ESTABLISHED_DIRECTION`:
**+228 pips / +£456** (upper bound, still conservative at 12p SL).

---

## 5. WATCH_AND_WAIT timeline for GBP/USD

Source: `logs/nms_watch_state.jsonl` (live file; the rotated `-20261105` is yesterday's
archive — not today's). Only transitions shown; between transitions every 5‑minute
evaluation held the same state.

| Evaluation ts (UTC) | Last bar | From | **To** | v3 state | Exhaustion | Reason | Watched trend | Watch extreme |
|---|---|---|---|---|---|---|---|---|
| 00:00:06 | 2026‑11‑04T23:55 | (init) | `TREND_TRADING` | `RANGE` | `EXHAUSTION_DEVELOPING / BUYING_EXHAUSTION` | `TREND_TRADING_NO_ESTABLISHED_TREND` (v3_state=RANGE) | — | — |
| 10:00:03 | 09:55 | `TREND_TRADING` | **`WATCH_AND_WAIT`** | `EMERGING_DOWN` | `EXHAUSTION_DEVELOPING / SELLING_EXHAUSTION` | `ENTER_WATCH_EXHAUSTION_INDEPENDENT` (`v3_trend=DOWN ex_state=EXHAUSTION_DEVELOPING ex_dir=SELLING_EXHAUSTION families=['CANDLE_REJECTION'] extreme=13462.05`) | **DOWN** | 13462.05 |
| 12:10:08 | 12:05 | `WATCH_AND_WAIT` | `TREND_TRADING` | `RANGE` | `EXHAUSTION_DEVELOPING / SELLING_EXHAUSTION` | `EXIT_WATCH_TO_TREND` (v3 reverted to RANGE, watched_trend=DOWN) | — | — |

**Analysis.**
- The transition into W&W at 10:00:03 UTC *was* driven by a real exhaustion signal
  (CANDLE_REJECTION family at bar 09:55, after the price had bounced off the 2‑week
  low near 13462). This is the "post‑established-trend" semantics, not "NMS can't
  decide".
- The 2h10m W&W window successfully prevented 3 V3 EMA_S shorts that would all have
  hit the 12‑pip SL (10:45, 11:10, 11:25 UTC).
- **But** the *separate* `BLOCK:MATRIX:WATCH_AND_WAIT:WATCHED_TREND=DOWN` matrix gate
  also refused a LONG at 11:45 UTC on the standalone BB service. WATCHED_TREND=DOWN
  encodes "the trend we are watching to end is DOWN" — the LONG is exactly the trade
  the system is supposed to take once the exhaustion resolves. That LONG hit TP20
  (+32.7 pips MFE, +£40 missed). The matrix gate is over‑broad: it treats W&W as
  "no trades" rather than "no counter‑exhaustion trades (shorts) but the recovery
  long is the whole point".
- The 12:10 exit back to `TREND_TRADING` was automatic once V3 dropped back to RANGE.
- W&W did not re-arm for the rest of the day.

Scorecard for W&W: **3 losing shorts avoided (−36 p / −£72), 1 winning long blocked (+20 p
missed / £40)**. Net **helpful** on balance, but the matrix-side implementation blocks
with-the-reversal longs that the NMS-directional-authority implementation does not. These
two code paths disagree and the stricter one wins — costing money on reversal days.

---

## 6. `v1_pressure_against` deep‑dive

`v1_pressure_against` lives in `bb_bounce_filters.py` and rejects BB-bounce entries where
the EUR/USD and DXY ("dollar") pressure vectors disagree with the proposed GBP/USD
direction. On 2026‑11‑05 it was enforced by `BB_BOUNCE_V1_PRESSURE_ENABLED=1`, not by
the new opt-in `BB_BOUNCE_V1_PRESSURE_VETO_ENABLED` flag (which was introduced earlier
today and is OFF by design — see [[project_v1_pressure_veto_downgrade_20261105]]).

**All 12 of today's blocks on GBP/USD:**

| Journal ts (UTC) | Side | Logged price | closeback | v1 | dollar | Hypothetical BB bounce (20p SL / 20p TP) | MFE |
|---|---|---|---|---|---|---|---|
| 04:10:10 | SELL | 13494.35 | AFTER | AGAINST | AGAINST | **TP_HIT +20p** | 46.3 p |
| 04:20:08 | SELL | 13494.25 | AFTER | AGAINST | AGAINST | **TP_HIT +20p** | 46.2 p |
| 04:25:09 | SELL | 13493.65 | AFTER | AGAINST | AGAINST | **TP_HIT +20p** | 45.6 p |
| 06:40:08 | SELL | 13491.15 | AFTER | AGAINST | AGAINST | **TP_HIT +20p** | 43.1 p |
| 06:45:10 | SELL | 13490.05 | AFTER | AGAINST | AGAINST | **TP_HIT +20p** | 42.0 p |
| 07:10:10 | SELL | 13495.15 | AFTER | AGAINST | AGAINST | **TP_HIT +20p** | 47.1 p |
| 07:15:12 | SELL | 13490.15 | AFTER | AGAINST | AGAINST | **TP_HIT +20p** | 42.1 p |
| 07:20:17 | SELL | 13485.55 | AFTER | AGAINST | AGAINST | **TP_HIT +20p** | 37.5 p |
| 11:20:07 | BUY  | 13460.85 | BEFORE | AGAINST | WITH | **TP_HIT +20p** | 25.4 p |
| 15:15:12 | BUY  | 13462.75 | AFTER | AGAINST | WITH | **TP_HIT +20p** | 23.5 p |
| 15:20:11 | BUY  | 13468.35 | AFTER | AGAINST | WITH | Open (MFE 17.9, MAE 11.4) | 17.9 p |
| 17:25:10 | SELL | 13480.85 | AFTER | AGAINST | AGAINST | Open (MFE 11.4, MAE 6.4) | 11.4 p |

**Characteristics of today's blocks:**
- Every block had `v1=AGAINST`. For the SELL cluster the EUR/USD pressure was reading
  "against GBP/USD SELL" — but **GBP/USD then fell roughly 40 pips in the following 20–30
  minutes.** The intermarket signal was factually wrong today.
- `dollar=AGAINST` for the SELL cluster (8 rows), `dollar=WITH` for the BUY cluster
  (3 rows). Both subgroups won.
- Nine of the twelve were on the pre-London / early-London down‑move (04:10–07:20 UTC),
  three on the New York afternoon.
- Mean MFE 35.7 pips, mean MAE 6.9 pips. Reversal odds at a 20p SL / 20p TP were extremely
  favourable even before the filter looked at anything intermarket.

**Does EUR/USD cross-pair information add independent value beyond NMS?**
- *On today's sample:* **no.** Of the 12 blocks, the NMS directional-authority gate also
  independently refused only 2 of the same bars (07:10 SELL and 11:20 BUY — both still
  TP-hit by other strategies). The other 10 would have been admitted by NMS and should
  have been let through to execution; `v1_pressure_against` was the lone blocker.
- *Historical context:* the memory [[project_v1_pressure_veto_downgrade_20261105]]
  records 23/29 unique v1 blocks with 3W/1L/+40p on the 4 matched cases — a small sample
  that today's 10/0 TP20 result emphatically updates against the filter.

**Recommendation:** set `BB_BOUNCE_V1_PRESSURE_ENABLED=0` for GBP/USD. Keep the code and
the logs so the shadow data can be revisited quarterly. If the operator wants a staged
roll-off, the already-deployed `BB_BOUNCE_V1_PRESSURE_VETO_ENABLED` provides a parallel
opt-in path — but the main `ENABLED` flag is the one that is currently blocking trades
on GBP/USD.

---

## 7. Five most consequential missed opportunities

Ranked by the realistic missed pips at the production SL (12p for V3, 20p for BB bounce)
and by how clean the setup was (MFE > SL by ≥ 2×).

### #1 — 2026‑11‑05 07:09:52 UTC — V3_EMA_S SELL @ 13494.9 — blocked `NMS-DIR:no_trend`
- NMS v3 state was `NORMAL`; authority gate concluded the down-trend was not yet
  "established" even though D1 direction was down and H4 direction was down (per the
  TRIGGER's `context` block) and the price had already begun a 40‑pip leg.
- MFE 47.4 pips in the next hour; MAE 0.75 pips. Would have hit TP20 before 07:20 UTC
  and TP40 before 07:30 UTC.
- Also-blocked on the same bar: `v1_pressure_against` logged a SELL rejection 23 seconds
  later. Both filters failed on the same correctly-timed London short.

### #2 — 2026‑11‑05 04:10:10 UTC — BB_BOUNCE SELL @ 13493.85 — blocked `v1_pressure_against`
- EUR/USD was reading "AGAINST" GBP/USD SELL but price fell 46 pips over the next 30
  minutes. No other gate objected.
- MFE 46.3, MAE 7.15. Would have cleanly hit both TP20 and TP40.
- Repeated five more times in the next 2h10m without any gate re-admission.

### #3 — 2026‑11‑05 11:45:00 UTC — Standalone BB_BOUNCE BUY @ 13454.02 — blocked `MATRIX:WATCH_AND_WAIT`
- The BUY was the recovery long out of the W&W window (price bottomed at 13447.5 at
  11:50 UTC). This is the exact trade shape W&W's authority-gate is supposed to admit
  (watched_trend=DOWN → allow counter long when exhaustion resolves).
- MFE 32.7 pips; TP20 hit. Instead the matrix-gate implementation blanket‑refused.

### #4 — 2026‑11‑05 07:14:38 UTC — V3_EMA_S SELL @ 13488.9 — blocked `NMS-DIR:no_trend`
- Second-chance entry on the same London down-leg. MFE 41.4, MAE 3.25. Clean TP20 +
  TP40. Blocker: same NMS "no established direction" logic.

### #5 — 2026‑11‑05 09:10:00 UTC — V3_EMA_S SELL @ 13477.8 — blocked `NMS-DIR:no_trend`
- Third attempt on the down-leg. MFE 30.3, MAE 8.95. Clean TP20; TP30 hit on next bar
  but TP40 open at series end. Same mechanism; same mis‑classified RANGE state.

---

## 8. Reconciliation with actual GBP/USD trades on IG DEMO today

### 8.1 Trades that reached the broker

| ts_open (UTC) | Source | Strategy | Dir | Fill | Close | Pips | GBP | Close reason |
|---|---|---|---|---|---|---|---|---|
| 00:50 | Standalone BB | BB_BOUNCE | SELL | 13484.8 | 13489.6 | −4.8 | −£9.6 | TAKEN (close logged) |
| 01:15 | Standalone BB | BB_BOUNCE | SELL | 13483.8 | 13491.5 | −7.7 | −£15.4 | TAKEN |
| 02:55 | Standalone BB | BB_BOUNCE | BUY | 13491.6 | 13489.6 | −2.0 | −£4.0 | TAKEN |
| 03:15 | Standalone BB | BB_BOUNCE | SELL | 13489.9 | 13494.7 | −4.8 | −£9.6 | TAKEN |
| 04:10 | Standalone BB | BB_BOUNCE | SELL | 13492.9 | 13492.7 | +0.2 | +£0.4 | TAKEN |
| 05:55 | Standalone BB | BB_BOUNCE | BUY | 13492.6 | 13489.8 | −2.8 | −£5.6 | TAKEN |
| 07:00 | Standalone BB | BB_BOUNCE | SELL | 13489.4 | 0.0 (BE) | 0.0 | £0.0 | TAKEN (BE stop) |
| 12:20 | Standalone BB | BB_BOUNCE | SELL | 13460.2 | 13471.0 | −10.8 | −£21.6 | TAKEN |
| **14:42** | **V3 main AutoBot** | **V3_BB_S** | **SELL** | **13457.6** | **13469.55** | **−9.95** | **−£19.9** | **SL hit after 10 min** |
| 15:00 | Standalone BB | BB_BOUNCE | BUY | 13471.0 | 0.0 (BE) | 0.0 | £0.0 | TAKEN (BE stop) |
| 17:15 | Standalone BB | BB_BOUNCE | SELL | 13477.0 | — | — | — | Still open |

Closed GBPUSD performance today: **−42.65 pips / −£85.30** (10 closed; one still open).

### 8.2 Characteristic comparison

| Metric | Actually executed (10 closed) | Blocked candidates (41, TP20 hypothetical) |
|---|---|---|
| Win rate (positive close at TP20) | 1 / 10 = 10 % | 17 / 38 (excl. 3 opens) = **45 %** |
| Mean pip outcome | **−4.3 p** | **+2.3 p** |
| Mean MFE (where available) | n/a | **14.2 p** |
| Counter-trend share (BUYs on a down day) | 3 / 10 = 30 % | 16 / 41 = 39 % |

### 8.3 Interpretation

The 10 actually-admitted standalone BB Bounce trades today were, on average, *worse* than
the 41 blocked candidates evaluated at the same 20‑pip target. Nine of the 10 taken trades
hit their stop or breakeven. The one trade admitted via the "central" V3 path (14:42)
also hit its stop. Meanwhile 17 of the 38 resolvable blocked candidates would have hit
TP20 cleanly. **The system is admitting weaker setups and rejecting stronger ones** —
specifically, the strongest setups of the day (the four pre‑London / early‑London SELLs
on 2026‑11‑05 04:10–07:20 UTC) were ALL rejected by `v1_pressure_against`, while the 00:50
→ 03:15 SELLs that *did* get through were marginal and reverted.

---

## 9. Sub-process context (for the record)

- **`BB_BOUNCE_FILTER_BLOCK v1_pressure_against`** events are emitted by the main
  AutoBot python process (`/opt/tradingbot`) from `bb_bounce_filters.py`. These are a
  distinct code path from the standalone `/opt/bb_bounce` service, which is why they
  appear in the systemd journal but not in `logs/execution_rejections.jsonl`.
- The 14:42 UTC V3_BB_S execution came via the main AutoBot (`BE-df28a54cefb3`,
  `V3_BB_S` strategy) through the unified NMS direction gate (
  `LIVE_PORT_NMS_DIRECTION_ALLOW: unified:ALLOW_BOUNCE_RANGE:side=SELL state=RANGE`).
  SEI arbiter did not block it because at 14:41 the standalone BB had not yet taken a
  conflicting position.
- Two later V3_BB_S triggers (15:00, 15:35) were refused by SEI with
  `settled_by=AUTOBOT_BB_PIERCE_RUN`, which indicates AutoBot's BB_PIERCE_RUN was
  already covering the opportunity in the SEI ledger. BB_PIERCE_RUN itself did not fire
  a live trade today (0 of 23 resolution rows have `live_bot_fired=TRUE`), so the SEI
  "coverage" here is a bookkeeping note, not a real defensive block.
- Standalone BB today: 39 setups, 10 TAKEN, 14 C2_FAIL (strategy-internal), 7
  CANCEL_INVALIDATED (structural), 2 EXPIRED, 2 C4_EXPIRED, 2 CANCEL_SAME_DIR_OPEN,
  2 REJECTED (1 ALREADY_OPEN dedup; 1 MATRIX:WATCH_AND_WAIT).

---

## 10. Filter verdict matrix

| Mechanism | Useful? | Redundant? | Contradictory? | Defective? | Recommendation |
|---|---|---|---|---|---|
| `bb_bounce_filters.v1_pressure_against` | **No (today)** | Yes (duplicates NMS where NMS was right) | Yes (10 setups where NMS would have admitted) | **Yes — 10 TP wins / 0 losses prevented** | **Disable** (`BB_BOUNCE_V1_PRESSURE_ENABLED=0`). |
| `nms_directional_authority: BLOCK_WATCH_AND_WAIT` | Yes | No | No | No | **Keep.** |
| `central_execution_gate: MATRIX:WATCH_AND_WAIT` (standalone BB) | Partially | Overlaps with authority gate | **Yes — blocks WITH-reversal longs the authority gate permits** | Partially (one BUY blocked today) | **Narrow: allow BUYs when watched_trend=DOWN; allow SELLs when watched_trend=UP** (the recovery trade is precisely what W&W is expected to admit). |
| `NMS second gate: v3_bb_range_only` (WS2) | Yes | No | No | No | **Keep.** |
| `NMS direction: BLOCK_TREND_NO_ESTABLISHED_DIRECTION` | Weak (break-even to slightly harmful today) | Overlaps with second-gate logic | No | No, but un‑discriminating | **Keep but re-threshold** so a confirmed H1+H4+D1 down day (like today 07:00–09:00 UTC) can qualify as "established" earlier. Current logic required v3_state to transition to EMERGING_DOWN which happened only at 14:40 UTC. |
| `NMS direction: BLOCK_TREND_WRONG_DIRECTION` | Yes | No | No | No | **Keep.** |
| `NMS direction: BLOCK_BOUNCE_STRONG_TREND_EXHAUSTION_DEVELOPING_ONLY` | Yes | No | No | No | **Keep.** |
| `SEI arbiter authoritative` | Yes (dedup) | Overlaps with ordinary position-dedup, but with cleaner reason codes | No | No | **Keep.** |

---

## 11. Methodology and reproducibility

All analysis scripts and the raw ledger are archived under
`/tmp/blocked_audit_20261105/` on `AutoBotV1`:
- `build_ledger.py` — extracts raw events (V3 TRIGGER↔LIVE_PORT correlation, W&W
  transitions, standalone BB rows, `BB_BOUNCE_FILTER_BLOCK v1_pressure_against` journal
  scrape, NMS second gate, BB Pierce).
- `reconstruct.py` — walks `data/candles/GBPUSD/2026-11-05.csv` from each candidate's
  bar, with side‑aware MFE/MAE, SL‑first/TP‑first checks, and a hard `INDETERMINATE`
  verdict for same-bar SL/TP collisions.
- `summarise.py` — mechanism aggregates and sub-type breakdowns.
- `master_ledger.csv` — 42‑row primary output (attached as sibling file below).
- `w_and_w_timeline.csv` — the 3 transitions above.

**Assumptions kept consistent across all candidates:**
- SL distance: 12 pips (V3) or 20 pips (BB bounce). Target: 20p primary, 30p and 40p
  shadow.
- Spread: 1 pip (production DEMO). Applied where the TRIGGER didn't carry bid/ask.
- Stake: £2.00 / pip, matching production executions.
- Walk-forward resolution: 5-min OHLC mid; the first bar that triggers SL (adv ≥ SL)
  or TP (fav ≥ TP) wins; same-bar collision is INDETERMINATE (none today).

---

*Report generated 2026‑11‑05 18:30 UTC. Read‑only; no production flags, services, or
code were modified in the course of this audit.*
