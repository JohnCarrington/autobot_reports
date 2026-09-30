# V2 simulation — regime split + carve-out feasibility

Sub-analysis of `docs/mpp_floor_fix_v2_simulation_2026-05-12.md`. Tests
whether a NEWS-only carve-out (keep OLD for NEWS, ship V2 for
SWEEP/TREND) is empirically viable on the 14-trade sample.

**Verdict: the carve-out hypothesis fails on two counts:**
1. SWEEP delta is **negative** under V2 (3/3 trades worse), not positive.
2. SWEEP+TREND combined sub-sample is **3 trades** (TREND has zero
   observations), well under the ≥8 threshold for empirical decision.
3. NEWS delta is **path-dependent** (+11.5p optimistic / −33.5p
   pessimistic), driven almost entirely by one CPI-day trade where the
   5M candle contained both TP1 and SL.

The data cannot support a regime-based carve-out decision either
direction.

---

## Per-trade data, re-cut by regime

Source: V2 sim doc, optimistic ordering for window=300, news_pct=0.75.
"Pessimistic" differs only on 2026-05-01T06:55:00 USDJPY (TP1 → SL
in same candle).

| date | pair | dir | regime | OLD | V2_opt | V2_pess | Δopt | Δpess |
|---|---|---|---|---:|---:|---:|---:|---:|
| 2026-04-27T06:50:02 | USDJPY | SELL | DEFAULT | +9.6 | +15.3 | +15.3 | +5.7 | +5.7 |
| 2026-04-27T07:05:02 | EURUSD | BUY  | DEFAULT | +9.7 | +10.2 | +10.2 | +0.5 | +0.5 |
| 2026-05-01T06:40:01 | USDJPY | SELL | NEWS    | +8.1 | +15.7 | +15.7 | +7.6 | +7.6 |
| 2026-05-01T06:50:01 | USDJPY | SELL | DEFAULT | +2.6 | +20.0 | +20.0 | +17.4 | +17.4 |
| 2026-05-01T06:55:00 | USDJPY | SELL | NEWS    | +8.0 | +20.0 | −25.0 | +12.0 | **−33.0** ← path-dependent |
| 2026-05-01T12:05:11 | USDCAD | SELL | NEWS    | +8.0 | +5.8  | +5.8  | −2.2 | −2.2 |
| 2026-05-04T15:20:50 | GBPUSD | SELL | SWEEP   | +12.2 | +5.8 | +5.8  | −6.4 | −6.4 |
| 2026-05-06T08:25:19 | GBPUSD | BUY  | SWEEP   | +12.1 | +15.9 | +15.9 | +3.8 | +3.8 |
| 2026-05-07T12:20:35 | USDCAD | BUY  | SWEEP   | +11.9 | +5.8 | +5.8  | −6.1 | −6.1 |
| 2026-05-08T13:20:01 | GBPUSD | BUY  | NEWS    | +8.6 | +9.5 | +9.5  | +0.9 | +0.9 |
| 2026-05-08T15:30:54 | GBPUSD | BUY  | NEWS    | +8.1 | −1.5 | −1.5  | −9.6 | −9.6 |
| 2026-05-11T13:10:03 | GBPUSD | BUY  | NEWS    | +8.1 | +5.8 | +5.8  | −2.3 | −2.3 |
| 2026-05-12T06:25:03 | GBPUSD | SELL | NEWS    | +8.2 | +15.9 | +15.9 | +7.7 | +7.7 |
| 2026-05-12T11:00:04 | GBPUSD | SELL | NEWS    | +8.4 | +5.8 | +5.8  | −2.6 | −2.6 |

---

## Aggregation by regime

| regime  | n | OLD   | V2 opt | Δ opt   | V2 pess | Δ pess  |
|---------|--:|------:|-------:|--------:|--------:|--------:|
| NEWS    | 8 | +65.5 | +77.0  | **+11.5** | +32.0   | **−33.5** |
| SWEEP   | 3 | +36.2 | +27.5  | **−8.7**  | +27.5   | **−8.7**  |
| TREND   | 0 | —     | —      | —       | —       | —       |
| DEFAULT | 3 | +21.9 | +45.5  | +23.6   | +45.5   | +23.6   |
| **Total** | **14** | **+123.6** | **+150.0** | **+26.4** | **+105.0** | **−18.6** |

---

## Sub-sample sizes — adversarial check

| Cohort | Size | User threshold | Status |
|---|--:|--:|---|
| NEWS | 8 | ≥5 for carve-out trust | **OK in isolation** |
| SWEEP | 3 | — | small |
| TREND | 0 | — | **no observations** |
| SWEEP + TREND combined | **3** | **≥8** | **TOO SMALL** |
| DEFAULT (env-trigger path) | 3 | n/a | not regime-aware; excluded from carve-out logic |

The NEWS cohort alone is at the minimum size for trust (n=8 ≥ 5). The
SWEEP+TREND comparator cohort is **at 37.5% of the threshold (3 of
required 8)**. The decision can't be made on this sample.

---

## Hypothesis check

> H: "Under V2 best (300/0.75), delta is positive for SWEEP+TREND and
>    negative for NEWS. If yes to both, NEWS-only carve-out is viable."

| Sub-claim | Result |
|---|---|
| NEWS delta negative under both orderings | **FALSE** (opt +11.5, pess −33.5 — sign flips) |
| SWEEP delta positive | **FALSE** (−8.7p; 3/3 trades worse than OLD) |
| TREND testable at all | **FALSE** (zero observations) |

**The carve-out hypothesis fails its precondition.** SWEEP is also a
loser under V2, not just NEWS. The "winners" (TP1 hits) in the SWEEP
bucket are 1 of 3 trades; the other 2 retrace through the new floor
and close at +5.8p — well below the OLD clip at +12p. With only 3
SWEEP observations and a 33% TP1 rate, we can't tell whether V2 helps
SWEEP on average or hurts it.

---

## Where the +26.4p headline delta actually comes from

Decompose the optimistic +26.4p:

| Source | Δ contribution | Reliability |
|---|---:|---|
| DEFAULT trades (3 trades) | **+23.6p** | Simulation artefact. V2 doesn't change MPP for DEFAULT trades (env trigger=35 is unchanged). Why did OLD close them at +9.6 / +9.7 / +2.6? Likely they were really in NEWS or a different code path, mis-classified by my regime inference. The +23.6p is not a real V2 benefit. |
| Path-dependent 2026-05-01 USDJPY | **+12.0p (opt) / −33.0p (pess)** | Single trade. CPI day. 5M candle contained both +20p TP1 AND −25p SL. Path unknowable from OHLC. |
| Today's 3CO (2026-05-12 GBPUSD) | **+7.7p** | The trade that motivated this whole investigation. Real benefit. |
| Other 10 trades net | **−16.9p** | The other 10 trades collectively LOSE under V2. The headline +26.4p comes from 3 specific trades (DEFAULT + path-dep + today). |

If we strip the simulation-artefact +23.6p and the path-dependent ±33p
swing, the "real" V2 delta on the verifiable trades is **−16.9p ± 25p**.
That's not a signal; that's noise.

---

## What the regime split DOES tell us

The aggregation does surface one robust finding worth noting, even
though it doesn't unlock a carve-out:

**Under V2, on the 11 trades where regime is clear (NEWS + SWEEP), V2
is net negative under any reasonable ordering.** NEWS+SWEEP combined
under optimistic: +11.5 − 8.7 = +2.8p delta over 11 trades. Under
pessimistic: −33.5 − 8.7 = −42.2p. Mid-case is barely positive to
clearly negative. The V2 fix doesn't help the regime-aware cohort in
aggregate.

The +26.4p headline win is entirely outside the regime-aware cohort
— in trades that V2 doesn't actually affect (DEFAULT bucket, where MPP
behaviour is unchanged at env-trigger=35).

---

## Adversarial extras

### Why my "DEFAULT" classifications might be wrong

OLD MPP fires when current_pnl ≤ breach_level. The breach_level is
`floor − epsilon`. Under OLD:
- DEFAULT (env trigger=35): would fire when best_pnl ≥ 35.
- NEWS (regime trigger=8): would fire when best_pnl ≥ 8 — but the
  close pnl can be a bit above 8 if price advanced between arming and
  the next manager tick.

For the 3 trades I classified DEFAULT (close pnl +9.6 / +9.7 / +2.6):
- +9.6 and +9.7 are 1.6-1.7p above the NEWS trigger of 8. Plausibly
  NEWS regime, just current_pnl had advanced beyond the trigger by
  the tick MPP fired. My ±1.5p classification threshold was too tight.
- +2.6 is anomalous. Doesn't match any regime trigger. Could be a
  BRIEFING_EXECUTION or WINDOW_SWEEP trade (12p arm, breakeven floor)
  where the floor=0 caused close at breakeven-ish. Without the raw
  signal_log details, I can't verify.

If those 3 trades were actually NEWS-regime, then the NEWS cohort
becomes 11 trades and the DEFAULT cohort is empty. Re-aggregated under
that assumption (rough estimate, treating the +23.6p as half-NEWS):
- NEWS (11 trades) opt: +35p, pess: −10p, Δopt: +14p, Δpess: −44p
- SWEEP (3): Δ −8.7p

The carve-out hypothesis ("NEWS bad, SWEEP good") would STILL fail:
SWEEP is still negative.

### What would unlock the carve-out

A 90-day sample with:
- ≥8 trades each in SWEEP and TREND
- Regime correctly captured per trade (not inferred from close pnl)
- Tick-level data for at least the news-day candles

would let us actually test whether V2 helps SWEEP/TREND. The current
30-day sample, conditioned by 5 of 14 trades being on CPI days
(2026-05-01: 3 trades, 2026-05-12: 2 trades), is too event-loaded.

---

## Recommendation

**Do not pursue the NEWS-only carve-out.** The data doesn't support it:

1. SWEEP cohort is **negative** under V2 (3/3 trades worse than OLD).
   That contradicts the carve-out premise that "V2 helps SWEEP."
2. SWEEP+TREND combined sub-sample is **3 trades**, well below the
   user-specified ≥8 threshold.
3. TREND has **zero observations**.
4. The +26.4p headline delta is dominated by simulation-artefact
   DEFAULT trades (+23.6p) that V2 doesn't actually affect.

Surface this finding; we'll discuss real options:

- **Option A (audit close): Accept the bug as load-bearing.**
  The 30-day net is +123.6p with the bug. Any fix attempt we've
  simulated nets negative or fails the +30p gate. Close the audit
  with "the bug is protective on news-day reversals; ship no fix."

- **Option B (instrument more):** Add MAE/MFE/peak tracking to every
  trade for 60-90 days. Re-evaluate then with proper data. Defer the
  fix.

- **Option C (per-strategy, not per-regime):** The audit identified
  the exemption list at trade_manager.py:2195-2205. Adding 3CO and
  GBPUSD_TREND_CONT could be tried — but the simulation shows this
  is structurally the same as option 2 (scrap MPP for non-tight)
  which also failed.

- **Option D (live experiment):** Ship V2 to one strategy (3CO only)
  as a live A/B for 30 days. Strategy-isolated risk, real data, no
  candle-level approximation. Higher fidelity than simulation but
  costs real pnl during the experiment window.

My lean: **Option A** (close the audit, no fix) with **Option B**
(instrument for future data) layered on. The simulation evidence is
too weak to ship anything, and the structural bug is empirically
protective on the news-heavy 30-day window we sampled.

---

## Files reviewed (read-only)

- `docs/manager_profit_protect_audit_2026-05-12.md`
- `docs/mpp_floor_fix_simulation_2026-05-12.md` (v1)
- `docs/mpp_floor_fix_v2_simulation_2026-05-12.md` (v2)

No code modified. No commits.
