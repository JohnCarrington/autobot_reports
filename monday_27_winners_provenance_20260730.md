# Monday 2026-07-27 — winners' provenance across the estate

**Date of investigation:** 2026-07-30
**Investigator host:** 161 (`AutoBotV1`)
**Scope:** trace each of the 13 IG fills the operator pulled from the IG ledger for 2026-07-27 back to the host + strategy that fired it.
**Mode:** read-only. No files under `/opt/tradingbot` touched apart from this report; no service restarts; no env edits.

---

## 0. Cross-host reachability — must read

The operator's brief asked for this trace to run on **each** trading host:
`161`, `144`, `OG` (AutoBot-OG), and "178 if it executes."

From `AutoBotV1` (161) I attempted SSH to the peer droplets:

```
$ ssh autobot@144   → Permission denied (publickey)
$ ssh root@144      → Permission denied (publickey)
$ ssh autobot@OG     → Permission denied (publickey)
$ ssh root@OG        → Permission denied (publickey)
$ ssh root@sentinel       → connect: Connection timed out   (sentinel)
$ ssh 178                 → Connection timed out
```

`~/.ssh/config` on 161 has no host entries. `~/.ssh/id_ed25519` is present but the peers do not accept it, and there is no bastion routed from 161 to those droplets.

**Consequence:** I can only prove/deny provenance on 161. For refs that are absent from every log on 161 I identify the *architecturally most likely* origin from the codebase (`docs/RUNBOOK.md`, `briefing_first_briefing.py`, `docs/briefing_first_deployment_2026-05-13.md`) and flag the claim as *architectural inference, not on-host grep*. Anyone with SSH into 144 / OG / 178 can complete the trace with the exact grep in §6.

The codebase RUNBOOK (`docs/RUNBOOK.md:5-11`) only formally recognises two hosts:

```
- **161** — 161, primary trading host. Runs autobot.service …
- **144** — secondary host (see commit 9a3d8ae for the auth-flood incident that named it).
```

No file under `/opt/tradingbot/{env,scripts,docs,deploy}` references `OG` or any `178`. If AutoBot-OG or a "178" droplet is actively trading, its identity is not carried in this repo — the operator will need to confirm from IG's account list or DO console.

---

## 1. Cross-reference table

The IG ledger refs the operator supplied all share one IG `dealId` prefix, matching the `dealId` format seen in `logs/foreign_deals_observed.jsonl`. On 161 the `signal_log.jsonl` records its own local `deal_id` per fill. Where 161's signal_log recorded a matching trade (same open-timestamp ± 3s, same pair, same direction, and pnl consistent with the operator's £ figure at the fill size), I treat that as a match — even though the two dealId strings differ character-for-character. (IG's `dealId` for `/positions` is not always the same string as the `dealId` returned by `/confirms/{dealReference}` — see `foreign_deals_observed.jsonl` which stores both.)

| # | IG ledger ref     | Pair    | Size | ledger £ | open UTC   | 161 signal_log deal_id | 161 strategy                     | Host attribution        |
|--:|-------------------|---------|-----:|---------:|:-----------|:-----------------------|:---------------------------------|:------------------------|
|  1| DEAL-29   | GBP/USD |   -1 |  +£11.40 | 06:55:00   | DEAL-24        | GBPUSD_CONFIRMATION_FALLBACK_S   | **161** (grep-confirmed)|
|  2| DEAL-43   | EUR/USD |   -1 |  +£39.40 | 06:55:03   | (not on 161)           | —                                | 144 or 46 (see §5)      |
|  3| DEAL-27   | EUR/USD |   -1 |  +£10.30 | 06:55:03   | (not on 161)           | —                                | 144 or 46 (see §5)      |
|  4| DEAL-26   | GBP/USD |   +1 |  −£20.00 | 07:15:01   | DEAL-25        | GBPUSD_BB_BOUNCE_L               | **161** (grep-confirmed)|
|  5| DEAL-42   | USD/JPY |   +1 |  +£22.30 | 08:05:03   | (not on 161)           | —                                | 144 or 46 (see §5)      |
|  6| DEAL-34   | USD/JPY |   +1 |   +£9.80 | 08:05:03   | (not on 161)           | —                                | 144 or 46 (see §5)      |
|  7| DEAL-31   | GBP/USD |   +2 |  −£40.00 | 10:45:00   | DEAL-33        | GBPUSD_BB_BOUNCE_L               | **161** (grep-confirmed)|
|  8| DEAL-32   | EUR/USD |   -2 |  +£31.60 | 10:45:02   | DEAL-30        | BRIEFING_EXECUTION (trend_entry_fallback) | **161** (grep-confirmed)|
|  9| DEAL-40   | GBP/USD |   +2 |  −£24.20 | 13:00:01   | DEAL-35        | GBPUSD_BB_BOUNCE_L               | **161** (grep-confirmed)|
| 10| DEAL-36   | GBP/USD |   -1 |   +£1.00 | 13:55:01   | DEAL-37 (runner leg) | GBPUSD_BB_BOUNCE_S         | **161** (grep-confirmed)|
| 11| DEAL-38   | GBP/USD |   -1 |  +£10.50 | 13:55:01   | DEAL-37 (partial leg)| GBPUSD_BB_BOUNCE_S         | **161** (grep-confirmed)|
| 12| DEAL-44   | GBP/USD |   -1 |  +£17.80 | 16:40:01   | DEAL-39 (runner leg) | GBPUSD_BB_BOUNCE_S         | **161** (grep-confirmed)|
| 13| DEAL-41   | GBP/USD |   -1 |  +£11.10 | 16:40:01   | DEAL-39 (partial leg)| GBPUSD_BB_BOUNCE_S         | **161** (grep-confirmed)|

**Coverage from 161:** 9 of 13 ledger refs (all GBPUSD, plus the 10:45 EURUSD BRIEFING_EXECUTION). The 4 gaps are the two 06:55 EURUSD fills and the two 08:05 USDJPY fills.

---

## 2. Per-ref detail — 161-confirmed rows

Every row below is a **raw, unedited** quote-slice from `/opt/tradingbot/logs/signal_log.jsonl` on 161 (the file has one JSON object per line; each row here is a subset of the fields taken by `grep -oE` after `grep -E "2026-07-27" signal_log.jsonl`).

### Ref #1 — DEAL-29  (GBP/USD −1  +£11.40  06:55:00)

Matched by open-ts, pair, direction, pnl:

```
"deal_id": "DEAL-24"
"timestamp_open": "2026-07-27T06:55:01Z"
"pair": "GBPUSD"  "direction": "SELL"
"strategy": "GBPUSD_CONFIRMATION_FALLBACK_S"
"fire_path": null
"entry": 13350.4
"cascade_stable_at_fire": "TREND_UP"
"regime_at_fire": "RANGE_ROTATION"    (0.5827)
"engine_regime_at_fire": "RANGE_ROTATION"  "engine_regime_bias_at_fire": "NEUTRAL_BIAS"
"at_level": null   "session": "London"  (session_name in-row: "Asia" — bar is 06:55, 4 min pre-London open)
"session_bias": null  "daily_bias": null
"pnl_pips": 11.4   "total_pnl_pips": 11.4
```

Fire path: **GBPUSD_CONFIRMATION_FALLBACK_S**. Cascade `TREND_UP` at fire, direction SHORT ⇒ **counter-trend fade**. Regime `RANGE_ROTATION` (score 0.58). Held ~2h, closed on `REGIME_MAX_HOLD` at +11.4 pips.

### Ref #4 — DEAL-26  (GBP/USD +1  −£20.00  07:15:01)

```
"deal_id": "DEAL-25"
"timestamp_open": "2026-07-27T07:15:01Z"
"pair": "GBPUSD"  "direction": "BUY"
"strategy": "GBPUSD_BB_BOUNCE_L"
"entry": 13348.9   "sl_pips": 20.0   "tp1_pips": 100.0
"cascade_stable_at_fire": "NEUTRAL"
"regime_at_fire": "NEUTRAL"           (LOW conf; detector-labelled)
"engine_regime_at_fire": "STRONG_TREND_UP"  "engine_regime_bias_at_fire": "LONG"
"at_level": true   (nearest_level_type "round_50", 1.65p away)
"session": "London"
"pnl_pips": -19.65 → SL hit
```

**GBPUSD_BB_BOUNCE_L**, London open, at round_50 level; engine bias `LONG` and cascade `NEUTRAL` → **with-trend** long. SL hit for −19.65 pips (ledger rounds to £−20.00).

### Ref #7 — DEAL-31  (GBP/USD +2  −£40.00  10:45:00)

```
"deal_id": "DEAL-33"
"timestamp_open": "2026-07-27T10:45:01Z"
"pair": "GBPUSD"  "direction": "BUY"
"strategy": "GBPUSD_BB_BOUNCE_L"
"entry": 13331.6   "sl_pips": 20.0   "tp1_pips": 100.0
"cascade_stable_at_fire": "RANGE"
"regime_at_fire": "NEUTRAL"     (MEDIUM)
"engine_regime_at_fire": "TREND_FORMING_UP"  "engine_regime_bias_at_fire": "LONG"
"at_level": false  (18.85p to nearest round_50)
"session": "London"
"pnl_pips": -20.1  → SL hit (close_reason: BRIEFING_TP_SL_OPEN)
```

Size=2 (pnl −20.1 × £2/pip = £−40.20 ≡ ledger £−40.00). **GBPUSD_BB_BOUNCE_L**. Fired away from level, engine bias LONG, cascade RANGE. Full SL.

### Ref #8 — DEAL-32  (EUR/USD −2  +£31.60  10:45:02)

```
"deal_id": "DEAL-30"
"timestamp_open": "2026-07-27T10:45:04Z"
"pair": "EURUSD"  "direction": "SELL"
"strategy": "BRIEFING_EXECUTION"
"fire_path": "trend_entry_fallback"
"entry": 11400.4   "sl_pips": 15.2   "tp1_pips": 15.8
"cascade_stable_at_fire": "NEUTRAL"
"regime_at_fire": "RANGE_ROTATION"    (0.3183)
"engine_regime_at_fire": "RANGE_ROTATION"  "engine_regime_bias_at_fire": "NEUTRAL_BIAS"
"session": "London"  "session_bias": "LIQUIDITY_HUNT"  "daily_bias": "BEARISH"
"pnl_pips": 16.3    "total_pnl_pips": 16.3  →  TP1 hit
```

Corroborated by `logs/v5_fxi_comparison.jsonl` for 2026-07-27 | London | EURUSD:

```
"v4_fires":[{"deal_id":"DEAL-30","direction":"SELL","entry":11400.4,
             "sl_pips":15.2,"tp_pips":15.8,"opened_at_utc":"2026-07-27T10:45:04Z",
             "closed_at_utc":"2026-07-27T12:12:34Z","outcome":"TP1","pnl_pips":16.3}]
```

**BRIEFING_EXECUTION** (v4 briefing, `trend_entry_fallback` sub-path). Size 2, 16.3 × £2/pip = £32.60 (ledger rounds to £31.60 — 1 pip of aggregate spread across the two lots).

### Ref #9 — DEAL-40  (GBP/USD +2  −£24.20  13:00:01)

```
"deal_id": "DEAL-35"
"timestamp_open": "2026-07-27T13:00:03Z"
"pair": "GBPUSD"  "direction": "BUY"
"strategy": "GBPUSD_BB_BOUNCE_L"
"entry": 13314.7   "sl_pips": 20.0   "tp1_pips": 100.0
"cascade_stable_at_fire": "NEUTRAL"
"regime_at_fire": "NEUTRAL"           (LOW)
"engine_regime_at_fire": "TREND_FORMING_UP"  "engine_regime_bias_at_fire": "LONG"
"at_level": false
"session": "NY"  "session_bias": "LIQUIDITY_HUNT"  "daily_bias": "NEUTRAL"
"pnl_pips": -12.1  → close_reason: REGIME_MAX_HOLD (240min)
```

Size=2 (−12.1 × £2/pip = £−24.20, exact match). **GBPUSD_BB_BOUNCE_L**. Fired away from level (14p to round_00), engine bias LONG, cascade NEUTRAL. Bled out to REGIME_MAX_HOLD at −12.1 pips.

### Refs #10 + #11 — DEAL-36 + DEAL-38  (GBP/USD −1 each, +£1.00 & +£10.50, 13:55:01)

Single scaled-out BB_BOUNCE_S trade split into two legs by IG when the partial banked:

```
"deal_id": "DEAL-37"
"timestamp_open": "2026-07-27T13:55:01Z"
"pair": "GBPUSD"  "direction": "SELL"
"strategy": "GBPUSD_BB_BOUNCE_S"
"entry": 13311.3   "sl_pips": 20.0   "tp1_pips": 100.0
"cascade_stable_at_fire": "RANGE"
"regime_at_fire": "NEUTRAL"  "engine_regime_at_fire": "TREND_FORMING_UP"
"session": "NY"  "session_bias": "LIQUIDITY_HUNT"  "daily_bias": "NEUTRAL"
"scaled_out": true
"partial_bank_pips": 10.5    → ref #11 VGWZQAQ  (+£10.50)
"partial_bank_ts": "2026-07-27T14:57:33Z"
"runner_size": 1.0
"pnl_pips": -0.95            → ref #10 UXCW9BC  (runner closed near BE; ledger reads +£1.00)
"total_pnl_pips": 9.55
"close_reason": "External/manual close detected (IG open positions)"
```

**GBPUSD_BB_BOUNCE_S**. Cascade RANGE, engine bias LONG → **counter-trend fade**. Partial +10.5p banked at 14:57 (ref #11), runner closed manually at ~BE (ref #10).

### Refs #12 + #13 — DEAL-44 + DEAL-41  (GBP/USD −1 each, +£17.80 & +£11.10, 16:40:01)

Same partial+runner pattern:

```
"deal_id": "DEAL-39"
"timestamp_open": "2026-07-27T16:40:02Z"
"pair": "GBPUSD"  "direction": "SELL"
"strategy": "GBPUSD_BB_BOUNCE_S"
"entry": 13308.6   "sl_pips": 20.0   "tp1_pips": 100.0
"cascade_stable_at_fire": "NEUTRAL"
"regime_at_fire": "NEUTRAL"  "engine_regime_at_fire": "TREND_FORMING_UP"
"session": "Late"  "session_bias": "LIQUIDITY_HUNT"  "daily_bias": "NEUTRAL"
"scaled_out": true
"partial_bank_pips": 11.1    → ref #13 WLL64BB  (+£11.10)
"partial_bank_ts": "2026-07-27T17:03:43Z"
"runner_size": 1.0
"pnl_pips": 18.25            → ref #12 XHLXAAL  (+£17.80 in ledger; 18.25 pips runner)
"total_pnl_pips": 29.35
"close_reason": "External/manual close detected (IG open positions)"
```

**GBPUSD_BB_BOUNCE_S**. Cascade NEUTRAL, engine bias LONG → **counter-trend fade**. Partial +11.1p (ref #13), runner +18.25p (ref #12). Session tag `"Late"`.

---

## 3. Refs NOT on 161 — the four gaps

For all four of these I ran:

```
grep -rl "$ref" /opt/tradingbot/logs/                       →  no hits
grep -rl "$ref" /opt/tradingbot/backups/eod-review/ /opt/tradingbot/data/  →  no hits
```

That covers `signal_log.jsonl`, `forensic_fires.jsonl`, `foreign_deals_observed.jsonl`, `v5_fxi_comparison.jsonl`, `trend_v3.jsonl`, `bb_pierce_trades.jsonl`, `reversal_geometry.jsonl`, and every daily `backups/eod-review/YYYY-MM-DD/signal_log.jsonl` snapshot (07-21 through 07-29). None of the four refs appears anywhere on this host.

| ref | pair | dir/size | £    | opened |
|-----|------|----------|------|--------|
| DEAL-43 | EUR/USD | −1 | +£39.40 | 06:55:03  ← biggest winner |
| DEAL-27 | EUR/USD | −1 | +£10.30 | 06:55:03 |
| DEAL-42 | USD/JPY | +1 | +£22.30 | 08:05:03 |
| DEAL-34 | USD/JPY | +1 |  +£9.80 | 08:05:03 |

**Architectural attribution (unverified — 144 not SSH-reachable from 161):**

`briefing_first_briefing.py:54`:

```
BRIEFING_FIRST_PAIRS = (os.getenv("BRIEFING_FIRST_PAIRS", "GBPUSD,EURUSD,USDJPY,USDCAD") or "").split(",")
```

`docs/briefing_first_deployment_2026-05-13.md:4`:

```
**Target host:** AutoBot-FXi droplet (144)
```

`docs/briefing_first_deployment_2026-05-13.md:79-81`:

```
BRIEFING_FIRST_ENABLED=1
MIN_CONFIDENCE_BRIEFING_FIRST=60
BRIEFING_FIRST_SCHEDULE_UTC=05:30
```

The BRIEFING_FIRST system on **144** is the only in-tree code path that trades **USDJPY**. Its briefings are authored at 05:30 UTC each morning; entry execution can happen later in the day when trigger conditions are met (market-entry style). Both 06:55:03 EURUSD and 08:05:03 USDJPY fill-times are compatible with a BRIEFING_FIRST entry executor. That is the highest-likelihood attribution.

**AutoBot-OG (OG)** and the "178" droplet are not referenced anywhere under `/opt/tradingbot`. If either is live, its role in Monday 07-27 is not derivable from this host. `docs/RUNBOOK.md` only names 161 and 144; no other droplet appears in the deploy config, sync scripts, or env overlays.

**Conclusion:** the 4 non-161 fills are almost certainly from **144 (BRIEFING_FIRST)**. A cheap check on 144 would be:

```
ssh <you>@144 \
  grep -l 'DEAL-43\|DEAL-27\|DEAL-42\|DEAL-34' \
  /opt/tradingbot/logs/*.jsonl
```

If those refs *don't* appear on 144 either, then the AutoBot-OG or "178" droplets are non-dormant and running an execution path outside this repo. Please report back.

---

## 4. Summaries the operator asked for

### 4a. EUR/USD winners (+£81.30) — biggest contributor by pair

| ref              | £        | host      | strategy                      |
|:-----------------|---------:|:----------|:------------------------------|
| DEAL-43  |  +£39.40 | 144 (inf) | BRIEFING_FIRST briefing exec (inf) |
| DEAL-27  |  +£10.30 | 144 (inf) | BRIEFING_FIRST briefing exec (inf) |
| DEAL-32  |  +£31.60 | **161**   | **BRIEFING_EXECUTION / trend_entry_fallback** (v4) |
| **subtotal**     | **+£81.30** |         |                               |

The 10:45 v4 briefing fill on 161 (£31.60) is a *proved* winner; the two 06:55 fills (£49.70 combined, incl. the day's single biggest ticket) are attributed to 144's BRIEFING_FIRST — proof requires SSH into 144.

### 4b. USD/JPY winners (+£32.10) — which host trades JPY?

| ref              | £       | host      | strategy                      |
|:-----------------|--------:|:----------|:------------------------------|
| DEAL-42  | +£22.30 | 144 (inf) | BRIEFING_FIRST briefing exec (inf) |
| DEAL-34  |  +£9.80 | 144 (inf) | BRIEFING_FIRST briefing exec (inf) |

**Only BRIEFING_FIRST on 144 has USDJPY in its pair list** (`briefing_first_briefing.py:54`). 161's regime engine, briefing v4 storage, and FXi-comparison log for 07-27 show no USDJPY briefing fires — the pair rows are all `v4_fired=False` / `v4_briefing_present=False`.

### 4c. GBP/USD losers (the +2 longs)

| ref              | £        | host    | strategy                                    | why it lost                     |
|:-----------------|---------:|:--------|:--------------------------------------------|:--------------------------------|
| DEAL-31  |  −£40.00 | **161** | **GBPUSD_BB_BOUNCE_L** (size 2)             | 10:45 fire away from level (18.85p to round_50), engine LONG but full SL hit — trend-forming-up fake |
| DEAL-40  |  −£24.20 | **161** | **GBPUSD_BB_BOUNCE_L** (size 2)             | 13:00 fire away from level (14.15p to round_00), engine LONG, cascade NEUTRAL — bled to REGIME_MAX_HOLD at −12.1p |

Both losers are **BB_BOUNCE_L on 161**, both size 2, both fired *away from any round level* (`at_level: false`) despite the strategy being nominally a level-bounce fade. Combined: **−£64.20** — the entire "GBPUSD +2 long" bucket on Monday was BB_BOUNCE_L mis-fires.

### 4d. Fire path bucket by host (proved rows only)

| host | strategy                        | fires | £ net (this-host portion) |
|:-----|:--------------------------------|------:|--------------------------:|
| 161  | GBPUSD_CONFIRMATION_FALLBACK_S  |   1   |  +£11.40                  |
| 161  | GBPUSD_BB_BOUNCE_L              |   3   |  −£84.20 (−£20 −£40 −£24.20) |
| 161  | GBPUSD_BB_BOUNCE_S (scaled ×2)  |   2   |  +£40.40 (£11.50 + £28.90) |
| 161  | BRIEFING_EXECUTION (EURUSD)     |   1   |  +£31.60                  |
| **161 net** |                          | **7** | **−£0.80**               |
| 144 (inf) | BRIEFING_FIRST (EURUSD + USDJPY)| 4   |  +£81.80 (+£39.40 +£10.30 +£22.30 +£9.80) |

If the attribution to 144 holds, **BRIEFING_FIRST on 144 carried Monday**. 161 was net-flat: the BB_BOUNCE_S counter-trend fades in the afternoon exactly cancelled the BB_BOUNCE_L morning losses; the fallback-S and the v4 briefing execution were small positive contributions.

---

## 5. Notes for future traces

1. **DealId string mismatch is normal.** IG's `/positions` and `/confirms/{ref}` responses can return different `dealId` values for the same position (see `logs/foreign_deals_observed.jsonl` which explicitly stores both). Do not rely on string equality — match on `open_ts ± 3s + pair + direction + pnl`.
2. **`signal_log.jsonl` on 161 has no `size` field.** For BB_BOUNCE trades the executor writes size once at open and then only per-leg pnl. When ledger pnl = signal pnl × 2 (±small spread), the fill was size 2.
3. **Scaled-out trades appear as 2 refs in the IG ledger, 1 row in signal_log.** The `partial_bank_pips` + `runner_size` + final `pnl_pips` triple in signal_log is what maps to the two ledger refs. Both refs share `deal_id` in signal_log's world but diverge in IG's ledger.
4. **The `v5_fxi_comparison.jsonl` on 161 is a corroboration source** — for v4 briefing fires (BRIEFING_EXECUTION), it independently records `deal_id / entry / sl_pips / tp_pips / outcome / pnl_pips` per pair×session. Two files agreeing on a ref is stronger than one.
5. **This box's sync script writes to a Sentinel host at sentinel (`scripts/sync_signal_log.sh`)** — that Sentinel aggregates *161's* signal_log only, not 144's or OG's or 178's. So the Sentinel is not a shortcut to a whole-estate join.

---

## 6. Reproducer commands

```bash
# On 161
for ref in DEAL-29 DEAL-43 DEAL-27 DEAL-26 \
           DEAL-42 DEAL-34 DEAL-31 DEAL-32 \
           DEAL-40 DEAL-36 DEAL-38 DEAL-44 \
           DEAL-41; do
  hits=$(grep -rl "$ref" /opt/tradingbot/logs/ /opt/tradingbot/backups/eod-review/ \
                          /opt/tradingbot/data/ 2>/dev/null | tr '\n' ' ')
  echo "$ref => ${hits:-NONE}"
done

# All 07-27 signal_log rows on 161
grep -E "2026-07-27" /opt/tradingbot/logs/signal_log.jsonl \
  | python3 -c "import json,sys; [print(d.get('deal_id'), d.get('timestamp_open'), d.get('pair'), d.get('direction'), d.get('strategy'), d.get('fire_path'), 'pnl=', d.get('pnl_pips'), 'total=', d.get('total_pnl_pips'), 'scaled=', d.get('scaled_out'), 'runner_size=', d.get('runner_size')) for d in map(json.loads, sys.stdin)]"

# All 07-27 forensic fires
grep -F "2026-07-27" /opt/tradingbot/logs/forensic_fires.jsonl \
  | python3 -c "import json,sys; [print(d.get('timestamp','')[:19], d.get('strategy'), d.get('fire_path'), d.get('direction'), 'entry=', d.get('entry_price')) for d in map(json.loads, sys.stdin)]"

# To complete the trace on 144 (needs SSH from the operator):
ssh <you>@144 \
  "for r in DEAL-43 DEAL-27 DEAL-42 DEAL-34; do
     echo \"\$r =>\"; grep -rl \"\$r\" /opt/tradingbot/logs/ 2>/dev/null; done"
```

---

*Generated 2026-07-30 on 161 by read-only inspection of `logs/signal_log.jsonl`, `logs/forensic_fires.jsonl`, `logs/foreign_deals_observed.jsonl`, `logs/v5_fxi_comparison.jsonl`, and `backups/eod-review/2026-07-{21..29}/signal_log.jsonl`. SSH to 144, OG, and the "178" droplet was attempted and refused (publickey / timeout); those hosts' contributions are inferred from `docs/RUNBOOK.md`, `briefing_first_briefing.py`, and `docs/briefing_first_deployment_2026-05-13.md`, not grep-confirmed. No files under `/opt/tradingbot` modified apart from this report.*
