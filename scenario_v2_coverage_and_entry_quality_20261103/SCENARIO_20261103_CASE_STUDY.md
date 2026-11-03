# 2026-11-03 case study — scenario `e1c03cad64fa6574`

A detailed reconstruction of the one scenario that actually produced a
live post-fix OPEN+CLOSE: `e1c03cad64fa6574` rev=7 BUY. The purpose is
to illustrate the entry-quality mechanism concretely, not to re-litigate
the correctness of the executor (which worked exactly as designed).

Prices in **IG index-scale** (divide by 10 000 for FX decimal).
Timeline UTC.

---

## 1. Live outcome

| Field | Value |
|---|---|
| Scenario | `e1c03cad64fa6574` rev 7 |
| First directional opp | 08:21:14Z — SELL |
| First BUY revision | 09:31:13Z (rev 5, INVALID) |
| **First READY BUY** | 09:51:07Z (rev 7, VALID) |
| Entry level | 13425.18 (1.34252) |
| Stop level | 13404.65 (1.34047) |
| Target level | 13427.15 (1.34272) |
| **Entry bar** | 2026-11-03T13:25:00Z close 13426.35 (1.34264) |
| **Exit bar** | 2026-11-03T13:30:00Z, high 13430.85 ≥ target |
| Simulated exit | 13427.15 (= target) |
| **Gross pips** | +0.8 |
| MFE | +4.5 |
| MAE | 12.8 |
| Lag first-READY → entry | **3 h 34 min** |

Dashboard summary (post 14:30 sweep): proposals 424, open 0, closed 1,
pending 390, gross_pips +0.8, outcomes `{target_hit: 1}`.

---

## 2. Full revision timeline

36 revisions emitted over 6 h 20 min. "p2e" = pips the market must
travel in the proposed direction before the entry trigger fires.
"R:R" = reward / risk. Market close column is the M5 bar whose
`ts_close` ≤ revision gen time.

| rev | gen UTC          | dir | pub       | entry | stop  | target | reward | risk | R:R  | mkt@rev | p2e  |
|-----|------------------|-----|-----------|-------|-------|--------|--------|------|------|---------|------|
| 0   | 08:21:14         | SELL| **VALID** | 13402.00 | 13430.00 | 13380.00 | 22.0 | 28.0 | 0.79 | 13421.05 | 19.0 |
| 1   | 08:31:02         | SELL| INVALID   | 13402.50 | 13428.00 | 13378.00 | 24.5 | 25.5 | 0.96 | 13417.65 | 15.2 |
| 2–4 | 08:41–09:01     | SELL| INVALID   | 13402.65 | 13427.06 | 13377.63 | 25.0 | 24.4 | 1.02 | 13415–13419 | 13–17 |
| **5** | 09:31:13     | BUY | INVALID   | 13427.00 | 13404.65 | 13427.15 | **0.1** | 22.4 | **0.00** | 13417.45 | 9.5 |
| 6   | 09:41:12         | BUY | CAUTION   | 13425.35 | 13404.65 | 13427.15 | 1.8 | 20.7 | 0.09 | 13420.65 | 4.7 |
| **7** | 09:51:07     | BUY | **VALID** | 13425.18 | 13404.65 | 13427.15 | **2.0** | 20.5 | **0.10** | 13419.75 | 5.4 |
| 8   | 10:01:56         | BUY | VALID     | 13425.05 | 13404.65 | 13427.15 | 2.1 | 20.4 | 0.10 | 13418.65 | 6.4 |
| 9   | 10:11:04         | BUY | VALID     | 13422.35 | 13404.65 | 13427.15 | 4.8 | 17.7 | 0.27 | 13410.95 | 11.4 |
| 10  | 10:21:06         | BUY | VALID     | 13422.35 | 13404.65 | 13427.15 | 4.8 | 17.7 | 0.27 | 13407.45 | 14.9 |
| 11–16 | 10:31–11:22    | BUY | mix       | 13419–13423 | 13404–13406 | 13427.15 | 3.9–5.3 | 15.6–18.6 | 0.21–0.34 | 13407–13412 | 10–14 |
| 17  | 11:30:56         | BUY | INVALID   | 13419.30 | 13406.25 | 13427.15 | 7.9 | 13.0 | 0.61 | 13405.65 | 13.6 |
| 18  | 11:41:10         | BUY | INVALID   | 13416.30 | 13406.25 | 13427.15 | 10.9 | 10.0 | **1.09** | 13407.95 | 8.3 |
| **19** | 11:51:05    | BUY | **VALID** | 13414.50 | 13402.40 | 13427.15 | 12.6 | 12.1 | **1.04** | 13408.55 | 6.0 |
| 20–22 | 12:01–12:21    | BUY | mix       | 13414.4–13415.0 | 13402.4 | 13427.15 | 12.1–12.8 | 12.0–12.6 | 0.96–1.07 | 13410–13414 | 0.5–3.5 |
| 23–26 | 12:31–13:10    | BUY | VALID     | 13414.9–13415.0 | 13402.40 | 13427.15 | 12.1–12.2 | 12.5–12.6 | 0.96–0.98 | 13409–13413 | 2.3–5.7 |
| 27  | 13:21:11         | BUY | VALID     | 13416.95 | 13402.40 | 13427.15 | 10.2 | 14.6 | 0.70 | 13416.55 | 0.4 |
| 28  | 13:32:01         | BUY | VALID     | 13417.65 | 13402.40 | 13427.15 | 9.5 | 15.2 | 0.62 | 13426.35 | **−8.7** |
| 29  | 13:44:01         | BUY | VALID     | 13421.39 | 13402.40 | 13427.15 | 5.8 | 19.0 | 0.31 | 13422.55 | −1.2 |
| 30–35 | 13:51–14:41    | BUY | mix       | 13426.4–13428.5 | 13402.4 | **13430.85** | 2.4–4.4 | 24.0–26.1 | 0.09–0.18 | 13418–13424 | 3.5–9.4 |

Target was pinned to **SWING_H 13427.15** across revs 5–29 (6 h). After
rev 30, target moved up to **13430.85** when price broke above
13427.15 — but entries moved up proportionally, keeping R:R at ~0.1.

---

## 3. Answers to the brief's seven questions

### 3.1 Why 3 h 34 min between first-READY (09:51) and entry (13:25)?

The entry rule is "M5 bar close > entry level 13425.18". Between 09:51
and 13:20, price oscillated between 13405 and 13424; **not a single
M5 close breached 13425.18**. The 13:25 bar (close 13426.35) was the
first in-window close above the trigger.

The delay is a direct consequence of two choices:

1. **Entry placed ABOVE market** (p2e > 0 for every BUY revision
   except 20–22 which briefly saw entry just-above-market as price
   dipped).
2. **Entry level pinned to 13425.18 by rev 7's choice**, which the
   dedup logic honours even as later revisions (19, 22) suggest
   much lower entries — those later revisions were ignored because
   rev 7 was the first READY and owns the dedup slot.

### 3.2 Was BUY supported by market movement during that interval?

Partially. From 09:51 (price 13419.75) to 13:25 (price 13426.35) the
BUY call gained +6.6 p over 3 h 34 min — a weak drift. During the
interval, MAE reached 14.1 pips (price 13405.65 at 11:25) — more than
the proposal's R:R would tolerate had the entry fired earlier.

**The direction eventually proved right, but the path was adverse-
first-then-correct**, which is exactly the pattern breakout entries
try to avoid — and the one against which they most often fail.

### 3.3 Pips of favourable movement BEFORE execution?

From the market close at first-READY (13419.75) to the entry bar
close (13426.35): **+6.6 pips captured by the market before V2 was
willing to enter**. The remaining room to the structural target
(13427.15) was **0.8 pips** — exactly the eventual gross profit.

### 3.4 Why was the target so close to the eventual entry?

Target was pinned to SWING_H = 13427.15, the first swing-high above
rev 5's price (13417.45) at 09:31Z. Breakout entries by construction
fire NEAR that swing-high. So the target was always going to be
within a few pips of entry under any revision whose entry was
placed above price.

A simple geometric fix (reward ≥ risk floor at generation time, or
"target must be at least K pips beyond the entry trigger") would
have forced a different target selection — likely 13441.3 (the next
swing-high up), which is what the sister scenarios
`31982bff857d57e3` and `a12b3c0199d9e753` BUYs used.

### 3.5 Did revisions materially change entry/target/stop?

- **Entry**: migrated 13427.00 → 13414.5 → 13428.5 (over 4 h). YES.
- **Stop**: 13404.65 → 13402.4 (−2.25 p over 2 h); minimal.
- **Target**: 13427.15 for 6 h, then 13430.85. The target was the
  single most stable field.

Had rev 19 (11:51, entry 13414.5, R:R 1.04) owned the dedup slot
instead of rev 7, the entry would have fired at the 12:10 bar (close
13414.65 > 13414.5) and had 12.5 pips to target. The actual
dedup-wins rule (first READY) gives rev 7, costing 10 pips of
reward.

### 3.6 Could any alternative entry have captured more of the move?

Yes, with caveats. Using the entry-alternatives script (M1–M5)
restricted to this scenario:

| Mechanism | Fill? | Entry | Exit | Gross | Comment |
|---|---|---|---|---|---|
| M1 current (close-above 13425.18) | 13:25 bar | 13426.35 | 13427.15 TARGET | +0.8 | what happened |
| M2 fill at first-READY | 09:55 bar | 13418.65 | 13427.15 TARGET | +8.5 | path volatile |
| M3 first in-direction bar | 10:30 bar | 13414.35 | 13427.15 TARGET | +12.8 | directionally LUCKY |
| M4 pullback then direction | 10:35 bar | 13412.35 | 13427.15 TARGET | +14.8 | path still volatile |
| M5 current + R:R ≥ 1.0 filter | **not taken** | — | — | — | rev 7 R:R was 0.10 |

M2–M4 look attractive IF the stop had been placed closer. With the
actual stop at 13404.65 (20 p below entry), M2–M4 would have survived
the morning dip to 13405.65 only barely (MAE 7 p from M4's entry).
Across the whole 14-scenario sample, M2–M4 produce **more wins by pip
count but more losses by trade count** — net slightly worse than M1.

The one filter that unambiguously helps the sample as a whole, M5,
would have **not taken this trade** (R:R 0.10). Which is a feature,
not a bug: this trade produced +0.8 p gross, below any reasonable
spread floor.

### 3.7 Was +0.8 p profitable after spread?

**No.** Even at the tightest reasonable GBP/USD half-spread (0.9 p
London mid-session), a round-trip costs ~1.8 p. The nominal +0.8 p
gross becomes net **−1.0 p** at best, **−2.0 p** at the session
average (1.4 p half) and worse near NY close or news.

The trade "won" on target per the shadow executor's definition
(target_hit), but it is economically a scratch at best and a small
loss realistically. This matches the broader M1 finding: 4 of M1's
10 trades had gross < 5 p and three of those cannot clear retail
spread. (See `ENTRY_QUALITY_ANALYSIS.md` §5.2.)

---

## 4. What this case illustrates (summary)

1. The AI's direction call was eventually right (BUY, +6 p over 4 h).
2. The entry mechanism waited for a breakout, so it entered within
   1 p of target.
3. The target was fixed to the nearest structural level, so there was
   nowhere to go after entry.
4. The lifecycle executed exactly to specification; the specification
   is what produces the −$1 outcome.
5. The scenario happens to be the ONLY one in the 40-row window today,
   which is why it fired at all — see `EXECUTION_COVERAGE_AUDIT.md`.
   Three other scenarios would have fired within the lookback window
   with better R:R if the window were per-scenario.

**Fix sequence:** (a) coverage patch to make all scenarios eligible,
(b) methodology work on target/entry/stop geometry before trusting the
expanded fill count.
