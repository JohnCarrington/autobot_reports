# EMA Pullback BUY at Upper Bollinger Band — 2026-11-04 10:17:22Z

**Pair:** GBP/USD · **Service:** `ema-pullback.service` (standalone, `/opt/ema_pullback/`)
**Deal:** `EMAPB-B-1793784609-5D79C8` → position `DIAAAAYSTNU9UB4`
**Verdict:** entered per the strategy's documented rules; strategy has **no awareness** of resistance clustering (upper BB, R3, 1.3500). Entry was +1.7p above the M5 upper BB, +11.6p above daily R3, 1.1p below 1.3500, 24.5p above the London session low. Stopped out 12 min later at the static 12-pip SL.

---

## A. Confirmed trade identity

| Field | Value | Evidence |
|---|---|---|
| Strategy | **EMA_PULLBACK** (standalone, not main AutoBot) | `trades-api /trades` → `strategy=EMA_PULLBACK`, `provenance=EXTERNAL`, `host_prefix=EMAPB` |
| Deal reference | `EMAPB-B-1793784609-5D79C8` | journald `ema-pullback` 2026-11-04 10:17:22 |
| Position id | `DIAAAAYSTNU9UB4` | same |
| Direction | BUY | setup_history.jsonl setup_id `5D79C8` |
| Size | 2.0 (DEMO SPREADBET) | `.env` `TRADE_SIZE=2.0` |
| Entry (fill) | **13498.9** (1.34989) | IG confirm `fill=13498.9` |
| Stop level | 13486.9 (1.34869) — **12p fixed** | audit `broker_sl_pips: 12.0` (`.env` `BROKER_SL_PIPS=12`) |
| Take-profit (runner) | 13598.9 (1.35989) — **100p fixed** | audit `broker_tp_pips: 100.0` |
| Partial (method_b TP1) | +15p at 1.35139 | `.env` `TAKE_PROFIT_PIPS=15` `PARTIAL_CLOSE_FRACTION=0.5` |
| Setup armed | 2026-11-04 **09:30:08.428Z** @ `entry_level=13497.65` | setup_history.jsonl `event=ARMED` |
| Submission | 2026-11-04 10:17:22.071Z (market-on-trigger) | setup_history.jsonl `event=SUBMITTING` |
| Fill | 2026-11-04 10:17:22.317Z | setup_history.jsonl `event=MARKET_ENTRY_FILLED` |
| **Arm → fill lag** | **~47 minutes** | derived |
| Close | 2026-11-04 10:30:08Z @ 13486.9 — `exit_reason=broker_closed` | setup_history.jsonl `event=CLOSED` |
| P&L | **−12.0p / −£24.00** | trades-api `pips_pnl=-12.0, pnl_gbp=-24.0` |
| Re-entry? | **Initial** entry; a second setup `83B3C5` armed intrabar at 10:25 but was **cancelled** (`m5_close_below_ema21`) | ema-pullback step log 10:30:12 |

The trade was placed by the **standalone** `ema-pullback.service` (unit: `/etc/systemd/system/ema-pullback.service`; working dir `/opt/ema_pullback/`; PID 3668542). AutoBot's main process sees it as `provenance=EXTERNAL / SIBLING_BOT` through the `EMAPB-` dealReference prefix (see `trade_executor.py:6295-6329`, `ownership_identity.py:498-508`). It did **not** pass through AutoBot's central execution gate.

---

## B. Exact reason the BUY opened

The standalone's full admission chain (`ema_pullback/pullback.py:72`, `ema_pullback/entry.py:35`, `ema_pullback/trend.py`, `ema_pullback/nms_gate.py:123`):

1. **H1 EMA-8/13/20 trend qualification** (trend.py). At H1 09:00 bar close the gate recorded `h1_direction=BUY`, EMA8/13/20 all up-sloped, separations positive, admission_allowed=True.
2. **M5 EMA-8 touch** (pullback.py:72). The **09:30 forming M5 bar** dipped to `low=13485.55` on the live EMA-8 at 13486.11 — the intrabar touch fires at `touch_tick_ts=09:30:08.428Z`.
3. **Entry level = 5-bar high + 3p buffer** (entry.py:35). Preceding bars 09:05-09:25 — max high 13494.65 (bar 09:15) — entry level **13497.65**.
4. **NMS V3 directional gate** (nms_gate.py:234-247). Snapshot `session_trend_GBPUSD.json` returned `v3_state=EMERGING_UP`; the gate's only rule is "block BUY when state ∈ {STRONG_DOWN, EMERGING_DOWN}" — all other states PASS. Explicitly documented refusal to apply trend-strength, exhaustion, structure, or price-action gates (nms_gate.py:19-28).
5. **ARMED @ 09:30:08Z**, working order `market_on_trigger` at 13497.65, stop 12p, TP 100p.
6. **47 minutes of waiting.** For the next ~47 M5 polls the state stays `ARMED`, events `[]`. Price slowly climbs from 13485 to 13498.
7. **Trigger fill @ 10:17:22Z.** Ask crosses 13497.65 → market submit → fill 13498.9.
8. **Stop hit @ 10:30:08Z** at 13486.9.

> **Decisive production log**, journald `ema-pullback.service`:
> ```
> Nov 04 09:30:09 ... step {... 'events': [{'kind': 'nms_v3_pass', 'v3_state': 'EMERGING_UP', 'reason': 'nms_v3_direction_pass:state=EMERGING_UP:side=BUY'}, {'kind': 'intrabar_armed', 'setup_id': '5D79C8', 'direction': 'BUY', 'entry_level': 13497.65}]}
> Nov 04 10:17:22 ... POST '/positions/otc', resp 200
> Nov 04 10:17:22 ... [LIVE-IG] market_entry FILLED dealReference=EMAPB-B-1793784609-5D79C8 dealId=DIAAAAYSTNU9UB4 fill=13498.9
> ```

### Filters actually evaluated

| Filter | Present? | Value at arm | Effect |
|---|---|---|---|
| H1 EMA8/13/20 alignment | Yes | all up, aligned | PASS |
| H1 slope gates (pips/hr per leg) | Yes | 5.4 / 4.7 / 3.9 | PASS |
| H1 separation gates (8→13, 13→20) | Yes | 9.7 / 9.75p | PASS |
| H4 context sanity | Yes (advisory) | aligned BUY, ordering/slope ok | PASS |
| M5 EMA-8 touch (pullback) | Yes | low 13485.55 ≤ EMA8 13486.11 | PASS |
| M5 close-below-EMA21 cancel | Yes | not triggered until 10:25 bar | PASS |
| NMS V3 directional gate | Yes | state=EMERGING_UP, age 310s | PASS (aligned) |
| NMS V3 snapshot staleness (900s cap) | Yes | 310s | PASS |

### Filters **absent** from the strategy (grep of `ema_pullback/*.py`)

| Filter | Status |
|---|---|
| Bollinger Band position | **not implemented** — zero references to `bollinger`/`bb_upper`/`bb_lower`/`boll_` |
| Daily pivots (R1/R2/R3/S1/S2/S3) | **not implemented** — zero references |
| Round numbers (1.3500 / 13500) | **not implemented** — zero references |
| Remaining-upside / target-distance minimum | **not implemented** — zero references |
| NMS exhaustion / watch-and-wait | **not read** — gate reads `v3_state` only, not `exhaustion`/`watch` fields |
| Session-progress / displacement cap | **not implemented** |

The breakout-entry design means the strategy mechanically chases price up by 5-bar-high+3p — **the further price has already run, the higher it chases**.

---

## C. NMS assessment

Snapshot at the arming time: `cache/session_trend_GBPUSD.json` with `evaluation_ts=2026-11-04T09:25:00Z`, age 310s at arm. Used by the gate:

| Field | Value |
|---|---|
| `v3_state` | **EMERGING_UP** |
| `displacement_pips` (hour of 09:00) | 2.2p |
| `london_open_price` | 13478.85 |
| `data_fresh` | True |
| `schema_version` | session_trend.v2 (supported) |

The gate logic (`ema_pullback/nms_gate.py:234-247`) **explicitly refuses** to consider:

* trend strength beyond the two directional-block states,
* H1 regime admission,
* countertrend confirmation,
* exhaustion,
* market-structure confirmation,
* additional price-action confirmation.

(From nms_gate.py:19-28.) So the gate **permitted** the BUY rather than endorsed it — it is a "not-against-the-trend" veto, not an authorisation.

The deployed `session_trend_GBPUSD.json` later in the morning contains a telling field — **`pivot_rejections`** — showing six logged rejections at R3 (13487.3) between 08:00 and 08:35:

```
08:00  R3 rejection_direction=DOWN  dist=-4.25p
08:05  R3 rejection_direction=DOWN  dist=-4.45p
08:15  R3 rejection_direction=DOWN  dist=-4.55p
08:20  R3 rejection_direction=DOWN  dist=-3.55p
08:30  R3 rejection_direction=DOWN  dist=-2.05p
08:35  R3 rejection_direction=DOWN  dist=-3.55p
```

The data classifier **saw** the morning's R3 wall. The EMA Pullback NMS gate **does not read `pivot_rejections`** — it reads only `v3_state`. So R3 rejection history was present in the file but ignored.

---

## D. Bollinger / resistance assessment at fill (10:17:22Z)

Values computed from the archived M5 candles through the last COMPLETED bar before fill (10:15:00Z close, `data/candles/GBPUSD/2026-11-04.csv`):

| Indicator | Value | vs entry 13498.9 (1.34989) |
|---|---|---|
| **M5 BB upper (20, 2σ)** | **13497.23** | entry **+1.67p ABOVE upper band** |
| M5 BB middle | 13489.38 | entry +9.52p above mid |
| M5 BB lower | 13481.53 | — |
| M5 BB width | 15.70p (compressed) | — |
| EMA 7 (M5) | 13493.08 | entry +5.82p above |
| EMA 13 (M5) | 13491.20 | entry +7.70p above |
| EMA 21 (M5) | 13488.58 | entry +10.32p above |
| EMA 100 (M5) | 13469.42 | entry +29.48p above |
| EMA 200 (M5) | 13454.48 | entry +44.42p above |
| RSI(14) M5 | 62.4 | elevated, not extreme |
| MACD(12,26,9) hist | -0.094 | turning negative (early divergence) |
| **Daily R3** | **13487.3** | entry **+11.6p ABOVE R3** |
| Daily R2 | 13461.8 | — |
| Daily P | 13423.1 | — |
| **1.35000 round number** | **13500.0** | entry **−1.1p below** |
| London session (08:00) open | 13478.85 | entry +20.05p from open |
| London session low (08:00-10:15) | 13474.35 (08:10 bar) | entry **+24.55p from day's low** |
| London session high up to 10:15 | 13498.95 | entry 0.05p below session high |

**All values above are from candles that CLOSED before the 10:17:22Z fill — no look-ahead.**

The fill landed at essentially the peak of the morning swing, above the compressed 15.7p upper band, above the R3 level that had rejected the 08:00-08:35 opening drive, within a pip of 1.3500.

---

## E. Root cause

**The entry was legitimate per the strategy's own rulebook and ran through an enabled, fail-closed NMS directional gate. The defect is the strategy's design, not an execution error:**

1. **Missing resistance-cluster awareness** — the EMA-PB module has no BB, pivot, or round-number input at any stage (grep of `/opt/ema_pullback/ema_pullback/*.py` returns zero hits). The entry level is mechanically chosen as "5-bar high + 3p" regardless of what's directly overhead.
2. **NMS gate is directional-only by design** — `nms_gate.py:19-28` explicitly enumerates everything it refuses to check (trend strength, exhaustion, structure, price-action). The authoritative pivot-rejection history at R3 was present in the same snapshot file (`pivot_rejections`) but is unread.
3. **Static 12-pip stop** — `.env` `BROKER_SL_PIPS=12`, static for every entry. At a resistance cluster (R3 pierced, 1.3500 ahead, upper BB above) this stop is less than one typical pullback; the trade was effectively a 12-pip coin flip on continuation above 1.3500.
4. **47-minute arm→fill chase** — the pullback happened at 09:30 with EMA-8 ≈ 13486; the trade didn't fill until 10:17 at 13498.9. Price moved 12 pips between the pullback setup and the execution. The strategy does not re-validate context during the wait (the step log shows `events=[]` for every bucket between 09:30 and 10:15), so neither the renewed proximity to R3/1.3500 nor the upper-band encroachment aborts the setup.
5. **Not a one-off.** Looking back through `setup_history.jsonl`, the standalone's last **18 closed entries** are **15 losses / 3 wins** (14 of the 15 losses hit the fixed −12p broker SL). Many of the losers share the pattern "H1-trend BUY → ~45-60min arm → fill just under or at a higher-timeframe resistance → stop out at −12p". This specific trade sits on that line.

### Classification of the root cause

- [x] **Missing exhaustion / resistance-location filter** (strategy-design gap)
- [x] **NMS authority limited to direction-only** (deliberate — but leaves R3/BB/round-number unenforced anywhere else)
- [x] **Static stop ill-matched to session-end location** (configuration gap)
- [ ] NMS stale state — snapshot age 310s, healthy
- [ ] Day-roll / timestamp mismatch — none observed
- [ ] Ownership / gate bypass — EMA-PB is a sibling service by design (`OWNERSHIP_HOST_PREFIX=EMAPB`); main AutoBot central gate was never in the path

> The trade was not "incorrectly opened" in the compliance sense — the strategy did precisely what it was built to do. The report is that the strategy as built cannot avoid buying into the top of a session rally because it lacks every one of the signals (BB, pivot, round number, session-progress) that would say "not here".

---

## F. Recommendations (for operator consideration — nothing deployed)

1. **Add a resistance-location gate to EMA Pullback's arm step.** The snapshot the gate already reads contains `daily_pivots` and `pivot_rejections` — a cheap first cut would be: *refuse BUY when `entry_level` is within X pips of any R-level that has ≥2 logged rejections since session open (and symmetric for SELL at S-levels)*. No new data source needed.
2. **Compare `entry_level` against the live M5 upper BB(20,2) at arm-time** and refuse when `entry_level > BB_upper - margin_pips` on BUY (symmetric for SELL). Strategy already has `candle_reader` and `indicators.ema`; BB is a one-helper addition.
3. **Dynamic SL.** The 2026-10-28 dynamic IG min-stop package (`feat/dynamic-ig-min-stop-20261028`) was staged for `trade_executor.py` + `/opt/bb_bounce/stop_sizing.py` but not applied to `/opt/ema_pullback/`. The 12p fixed SL is the smallest practical IG MIN_STOP today; an ATR-scaled minimum (e.g. `max(12, 0.9×ATR_pips)`) would prevent the "entry at resistance + 12p stop" coin flip.
4. **Arm-to-fill re-validation.** When `arm→fill > 20 min`, re-evaluate the location stack (BB, R, round-number) before submitting. The `events=[]` bucket runs today are silent passes.
5. **Treat the 15/3 loser ratio of the last 18 closed trades as a separate issue** — out of this trade's scope, but the pattern is visible in `setup_history.jsonl` and likely informs the design decision above.

---

## Appendix — Evidence trail

* Service unit: `/etc/systemd/system/ema-pullback.service` (standalone)
* Code: `/opt/ema_pullback/ema_pullback/{pullback,entry,trend,nms_gate,service,main}.py`
* Setup lifecycle record: `/opt/ema_pullback/state/setup_history.jsonl` (setup_id `5D79C8`)
* Journald: `journalctl -u ema-pullback.service --since "2026-11-04 09:30:00" --until "2026-11-04 10:30:30"`
* M5 candles archive: `/opt/tradingbot/data/candles/GBPUSD/2026-11-04.csv`
* NMS v3 snapshot: `/opt/tradingbot/cache/session_trend_GBPUSD.json`
* Trade view: `curl -sS http://localhost:8080/trades?view=grouped` (deal_reference `EMAPB-B-1793784609-5D79C8`)
* AutoBot sibling-ownership code: `/opt/tradingbot/trade_executor.py:6295-6329`, `/opt/tradingbot/ownership_identity.py:498-508`

All indicator values (BB, EMAs, RSI, MACD) were recomputed from the on-disk M5 candles through the last **completed** bar before the fill (10:15:00Z close). Bands and EMAs use the 20 and 200-length windows that straddle the day-boundary and therefore pull in the final bars of 2026-11-03 for warmup.
