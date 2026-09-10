# QM pick direction audit — 2026-09-08 and 2026-09-09

**Scope.** Every pick alerted on 2026-09-08 and 2026-09-09 (post-amendment
machine, commit `089a547` shipping the family-labelled dedup + rejection-family
base parity). READ-ONLY, no code changes.

**Method.**
- Picks pulled from `logs/qm_pick_alerts_seen.jsonl` filtered by `date`.
- Entry price = close of the **arming bar** (the last 5m bar with
  `timestamp <= opened_at`). This matches the pick alert model: the alert
  fires on bar close, so the earliest tradable price is the close price of
  the arming bar.
- MFE/MAE measured over the **next 36 bars** (3 h) in the direction called.
- Pips = `price_units × 10 000` (5m CSV values are `mid × 100 000`).
- Verdict: **RIGHT** if 10 p MFE hit first, **WRONG** if 20 p MAE hit first
  *or* MFE < MAE at the 36-bar window end, otherwise **FLAT**.
- `score` (confidence 0–12) is emitted on the Telegram wire and app log but
  is NOT persisted to `qm_pick_alerts_seen.jsonl`, and `journalctl` history
  only reaches back to 2026-09-09 17:39 UTC on this host — so per-pick score
  is **unavailable** for 15 of 17 picks and I do not report it. See note at
  the bottom.

## Table

| # | opened_at (UTC) | pair | sess | zone | family | dir | entry | MFE p | MAE p | verdict | hit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-08 05:55 | GBPUSD | Asia   | 1.35446 | (unlabeled) | SELL | 1.35433 | 10.0 |  9.4 | RIGHT | MFE10 @ bar 17 |
| 2 | 2026-09-08 07:20 | GBPUSD | London | 1.35281 | (unlabeled) | BUY  | 1.35333 |  5.9 | 10.5 | WRONG | end MFE<MAE |
| 3 | 2026-09-08 11:40 | EURUSD | London | 1.16219 | (unlabeled) | SELL | 1.16131 |  5.1 | 18.0 | WRONG | end MFE<MAE |
| 4 | 2026-09-08 11:55 | GBPUSD | London | 1.35446 | (unlabeled) | BUY  | 1.35451 | 10.7 |  3.1 | RIGHT | MFE10 @ bar 11 |
| 5 | 2026-09-08 13:25 | GBPUSD | NY     | 1.35516 | (unlabeled) | BUY  | 1.35540 |  3.0 | 20.5 | WRONG | MAE20 @ bar 33 |
| 6 | 2026-09-08 15:30 | GBPUSD | NY     | 1.35516 | (unlabeled) | SELL | 1.35419 | 10.3 |  1.4 | RIGHT | MFE10 @ bar 14 |
| 7 | 2026-09-08 18:45 | EURUSD | NY     | 1.16219 | (unlabeled) | BUY  | 1.16229 |  7.2 |  0.8 | FLAT  | — |
| 8 | 2026-09-09 04:16 | GBPUSD | Asia   | 1.35000 | rejection    | BUY  | 1.35467 | 10.2 |  1.4 | RIGHT | MFE10 @ bar 23 |
| 9 | 2026-09-09 06:15 | GBPUSD | London | 1.35620 | rejection    | BUY  | 1.35620 |  6.3 | 21.2 | WRONG | MAE20 @ bar 33 |
| 10| 2026-09-09 07:20 | EURUSD | London | 1.16355 | continuation | BUY  | 1.16391 | 10.2 |  1.5 | RIGHT | MFE10 @ bar 5 |
| 11| 2026-09-09 08:00 | GBPUSD | London | 1.35620 | continuation | SELL | 1.35527 | 10.2 |  0.0 | RIGHT | MFE10 @ bar 11 |
| 12| 2026-09-09 11:15 | EURUSD | London | 1.16383 | continuation | SELL | 1.16375 |  0.2 | 16.7 | WRONG | end MFE<MAE |
| 13| 2026-09-09 11:20 | GBPUSD | London | 1.35613 | continuation | SELL | 1.35531 |  5.3 | 13.4 | WRONG | end MFE<MAE |
| 14| 2026-09-09 11:50 | GBPUSD | London | 1.35613 | rejection    | SELL | 1.35580 | 10.2 |  8.5 | RIGHT | MFE10 @ bar 13 |
| 15| 2026-09-09 14:20 | EURUSD | NY     | 1.16383 | continuation | BUY  | 1.16448 |  6.7 | 22.0 | WRONG | MAE20 @ bar 10 |
| 16| 2026-09-09 15:00 | GBPUSD | NY     | 1.35413 | continuation | BUY  | 1.35487 | 11.5 | 14.4 | RIGHT | MFE10 @ bar 28 |
| 17| 2026-09-09 15:00 | GBPUSD | NY     | 1.35413 | rejection    | SELL | 1.35487 | 10.0 |  1.2 | RIGHT | MFE10 @ bar 2 |

(The 23:55 opened_at row from `qm_pick_alerts_seen.jsonl` belongs to
`date=2026-09-10` and is out of scope.)

## Family × verdict tallies

Only the 2026-09-09 picks carry family labels — the amendment commit
(`089a547`) landed 2026-09-09 04:19 UTC and began writing `family` to the
seen-jsonl. The 7 picks from 2026-09-08 are pre-family-labelled and shown
below in an unlabeled bucket.

**Family-labelled only (2026-09-09):**

| family        | RIGHT | WRONG | FLAT | hit-rate |
|---------------|-------|-------|------|----------|
| rejection     |   3   |   1   |  0   |  75 % (3/4) |
| continuation  |   3   |   3   |  0   |  50 % (3/6) |
| **all-labelled** | **6** | **4** | **0** | **60 % (6/10)** |

**Unlabeled (pre-amendment, 2026-09-08, all 7):** 3 RIGHT / 3 WRONG / 1 FLAT.
Grand total including these: 9 RIGHT / 7 WRONG / 1 FLAT ≈ 53 % hit-rate
(9 / 17), 59 % including FLAT as neutral (9 / 16).

**Concentration.** On the labelled cohort, continuation (50 %) and rejection
(75 %) both sit within noise on this sample. The rejection family is
actually the *better*-performing bucket — the four WRONG picks split
1 rejection / 3 continuation. The inaccuracy is **not concentrated** in the
fade/rejection family on these two days; if anything, on this sample size
continuation is the marginally weaker side.

## WRONG fades — arming-bar geometry

Only one family-labelled **fade / rejection** pick came out WRONG on these
two days.

### Pick #9 — 2026-09-09 06:15 UTC — GBPUSD BUY, zone 1.35620

Arming bar (`2026-09-09T06:15:00+00:00`) OHLC:

```
open  1.35561
high  1.35622   (zone = 1.35620, +0.2 p above)
low   1.35560   (−6.0 p below zone)
close 1.35620   (at zone, +0.05 p above)
```

- **Boundary pierced.** The LOW pierced the zone by 6.0 p downward
  (`rejection_side = "below"` by construction).
- **Close side.** The close is essentially AT the zone (+0.05 p — a rounding
  artefact of the ×10 000 storage). It did *not* reclaim clearly back above
  the zone; there is no bullish body above the level, just a bottom-wick.
- **Direction rule.** Per `qm_pick_alerts._direction_for` (post-2026-09-05 F4
  fix), a downside pierce → BUY fade. This pick's direction assignment is
  **on-rule** — it derives from the rejection-geometry branch
  (`confidence_why["rejection_side"] == "below"` → BUY), NOT from the
  `hypothetical_entry vs zone_center` fallback. `rearm_direction` was not
  set (this is not a §16/§24 path).
- **What went wrong.** Not a mislabelled direction; it's a marginal geometry
  case. Close at zone with no body-above reclaim is a thin rejection
  signature, and price then re-tested and broke through: MAE hit 20 p at
  bar 33 (~2 h 45 m after arming). The rejection-geometry rule fired
  correctly on the bar's shape; the shape itself is a borderline positive.

## Score availability

`qm_pick_alerts_seen.jsonl` stores only `{opened_at, dir, session, zone_key,
date, family, alerted_at}` — no `confidence_score` field. The
`[QM-PICK] … conf=<N>` log line is written by `qm_pick_alerts.py:579` /
`:770` at INFO but only survives in `journalctl -u autobot`, whose retention
on this host does not reach back to 2026-09-08 (earliest available message
is 2026-09-09 17:39 UTC, after all but the last two 09-09 picks).
Two picks fall inside the retention window (the pair alerted at
2026-09-09 15:00 UTC and Pick #17 alerted at 15:25 UTC); a grep of that
window did not surface `[QM-PICK]` lines either, so I have not reported
score for any pick rather than reporting it inconsistently.

## Anomalies noticed in-flight

- **Pick #2** was `opened_at=2026-09-08T07:20` but `alerted_at=11:20` — a
  4-hour delivery gap. The 15-min freshness ceiling should have suppressed
  this per the stale-leak guard; worth a follow-up read of
  `_maybe_send_pick_alert` behaviour that day.
- **Pick #17** was `opened_at=15:00`, `alerted_at=15:25` — 25 min gap on the
  SELL side of the same 15:00 zone/day where Pick #16 (BUY, continuation)
  had already alerted at 15:05. Family=rejection here, so this is the
  post-amendment "one-per-family per zone/side/day" cell doing its intended
  double-alert. Both hit RIGHT.
- Picks #16 and #17 arm on the *same* GBPUSD bar (15:00 UTC OHLC
  1.35628 / 1.35648 / 1.35478 / 1.35487 — a wide down-body). Continuation-BUY
  and rejection-SELL fire from the same bar in opposite directions. Both
  reach 10 p MFE first (BUY at bar 28, SELL at bar 2), which is the
  window-order-dependent artefact of MFE-first-wins; the SELL side hit
  first in real time.

---

**Data sources.** `logs/qm_pick_alerts_seen.jsonl`,
`data/candles/{EURUSD,GBPUSD}/2026-09-{08,09,10}.csv`. Audit script:
in-tree throwaway (not committed).
