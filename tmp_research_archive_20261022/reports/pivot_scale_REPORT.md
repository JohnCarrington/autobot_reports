# What determines whether a bounce off a pivot is a 5m event or an H1 event?

**Corpus:** GBPUSD 5m OHLC (`/opt/tradingbot/data/candles/GBPUSD/*.csv`), 65 trading days (2026-05-27 → 2026-08-13). Daily pivots per `bb_pd_gate.compute_pivots_only` from prior-completed D1 in `cache/htf/GBPUSD_D1.json`. Price stored in IG points, 1 pip = 1.0. Indicators recomputed pure-function from raw 5m: BB(20,2), MACD(35,45,30), ATR(14). H1 synthesized from 5m via 1H resample; H1 MACD(35,45,30) recomputed on that series. News = Finnhub cache in `/opt/tradingbot/cache/news_state_finnhub_*.json`, filtered to `HIGH`/`MED` × GBP or USD.

**Definitions:**
- **Approach cluster** — contiguous bars whose 5m range intersects [level−5, level+5]. Prior close relative to level defines approach direction.
- **TURN** — after the cluster, price moves ≥ 15 pips in the *away* direction (opposite to approach) before re-entering the 5-pip band.
- **CONTINUATION** — after the cluster, price moves ≥ 15 pips in the *toward* direction (through the level) before re-entering the band.
- **CHOP** — neither threshold reached before re-entry or corpus end.

Scripts (kept in /tmp for explicit cleanup): `pivot_scale_step1.py`, `pivot_scale_step2.py`, `pivot_scale_step3.py`, `pivot_scale_analyze.py`. Data: `/tmp/pivot_events.csv` (all clusters), `/tmp/pivot_scale.csv` (+shape), `/tmp/pivot_scale_features.csv` (+pre-arrival).

## Step 1 — every approach classified

| Outcome | Count | % of approaches |
|:--|--:|--:|
| TURN         |   275 | 25.4% |
| CONTINUATION |    44 |  4.1% |
| CHOP         |   765 | 70.6% |
| **Total**    | **1,084** |  |

Turns per level (rejection direction combined): P=85, R1=61, S1=54, R2=25, R3=23, S2=19, S3=8. Continuations by level: P=13, R1=10, S1=8, R2=5, R3=1, S2=6, S3=1. About 3 of every 4 approaches produce nothing.

*(Note: TURN count here (275) is higher than the earlier report's "91 real moves" because that pass measured excursion from the turn extreme forward from inside the cluster, which broke on the next in-band bar. This pass measures excursion from cluster-end forward, which is the natural read of "after price leaves the band it went ≥15 pips away before returning." The definition here is more forgiving to slow reversals and is why the H1_SCALE bucket exists at all.)*

## Step 2 — scale classification

**Measure used:** `bars_to_10p` — 5m bars from the turn extreme until price is 10 pips away from the level in the rejection direction. (Chosen over "H1 close-back": it's model-free, doesn't depend on where H1 bar boundaries happen to fall, and directly captures the timescale of the reversal.)

**Rule proposed:**
- **5M_SCALE** — `bars_to_10p ≤ 3` (≤ 15 min to a decisive 10-pip separation) — n=157
- **AMBIGUOUS** — `bars_to_10p 4–6` (20–30 min) — n=51
- **H1_SCALE** — `bars_to_10p ≥ 7` (≥ 35 min) — n=62
- **NEVER_REACHED** (never 10p away within 4h of turn) — n=5

**Sanity check that the two groups differ in the intuitive way** (each row is the median of that group):

| Group | cluster_bars in band | 5m turn body ratio | 5m wick beyond level | **H1 containing wick beyond** | H1 close on entry side |
|:--|--:|--:|--:|--:|--:|
| 5M_SCALE (n=157) |  2 | 0.50 | 0.0 p | **0.0 p** | 95% |
| H1_SCALE (n=62)  | 18 | 0.48 | 6.4 p | **4.9 p** | 63% |

The two groups are qualitatively different, as intended. **5M turns barely touch the level and the H1 bar shows no rejection wick — the reversal is invisible on H1.** H1 turns dwell ~1.5 hours in the band, pierce ~6 pips beyond the level, and 37% of H1 containing bars actually close through the level (i.e., they only reverse on the *next* H1 bar).

**Cleanly separable? No — it is a continuum.** The `bars_to_10p` histogram has no gap: 157, 51, 32, 23, 7 (≤3, 4-6, 7-12, 13-24, 25+). The rule is a clean threshold on a smooth distribution.

## Step 3 — what separates the outcomes

### Q1. TURN vs CHOP vs CONTINUATION (pre-arrival)

Pre-arrival features measured at the bar immediately before the approach cluster starts. Effect sizes as Cliff's δ; small ≥ 0.15, medium ≥ 0.33, large ≥ 0.47.

**TURN vs CHOP — nothing has more than a small effect:**

| Feature | TURN median | CHOP median | Cliff's δ |
|:--|--:|--:|--:|
| atr_at_arrival (pips) | 4.11 | 3.77 | +0.13 |
| bb_width_at_arrival (pips) | 14.49 | 12.84 | +0.12 |
| speed_6bars_pips (\|Δ\|) | 3.80 | 3.30 | +0.12 |
| dist_from_prev_level (pips) | 23.50 | 22.33 | +0.12 |
| macd_hist_5m_at_arrival (\|·\|) | 0.20 | 0.19 | +0.01 |
| macd_hist_h1_at_arrival (\|·\|) | 1.40 | 1.34 | +0.08 |
| n_prior_touches_today (median) |    3 |    3 | −0.06 |
| macd_hist_h1_sign aligned to rejection | 53.5% | 52.4% | — |
| macd_hist_5m expanding | 43.6% | 43.3% | — |

**Only two things move the TURN rate meaningfully — session and news:**

| Session (UTC) | Approaches | TURN % | CONT % |
|:--|--:|--:|--:|
| Asia   (00–06) | 221 | **16.7%** | 1.8% |
| London (06–12) | 306 | **29.4%** | 6.5% |
| NY_AM  (12–17) | 275 | **38.5%** | 5.5% |
| NY_PM  (17–22) | 223 | 17.5%   | 2.2% |
| Off    (22–24) |  59 |  5.1%   | 0.0% |

| Near-news? | Approaches | TURN % | CONT % |
|:--|--:|--:|--:|
| Yes (±60 min, HIGH/MED, GBP or USD) | 290 | **35.9%** | 5.2% |
| No | 794 | 21.5% | 3.7% |

Session is a 2.3× lift from off-hours to NY_AM; news is a 1.7× lift.

**TURN vs CONTINUATION — the only pre-arrival separator is prior touches:**

| Feature | TURN | CONTINUATION | Cliff's δ / note |
|:--|--:|--:|--:|
| first touch today (n_prior_touches = 0) | 17% | **30%** | 1.8× lift for CONT |
| speed_6bars_pips | 3.80 | 5.05 | δ = −0.12 (mild) |
| dist_from_prev_level_pips | 23.5 | 28.3 | δ = −0.15 (mild) |
| MACD H1 aligned with approach direction | 47% | 55% | mild lift for CONT |
| news near | 37.8% | 34.1% | ≈ same |
| **dist_extreme_to_level (during-approach)** | 3.75 p | **9.80 p** | δ = **−0.86** (near-tautology) |

The one big number — 9.8 vs 3.75 pips of pierce — is a "during" feature, not pre-arrival: continuations by construction go through the level, so the extreme is deeper. Removing that, **CONTINUATIONS are best foreshadowed by (i) being the first touch of the level that day, (ii) arriving faster from further away, (iii) H1 MACD hist that already leans in the direction of the approach.** But no combination of these gets close to separating the two populations cleanly on 44 continuations — thin cell.

### Q2. 5M_SCALE vs H1_SCALE turns (pre-arrival)

Univariate pre-arrival:

| Feature | 5M_SCALE median | H1_SCALE median | Cliff's δ |
|:--|--:|--:|--:|
| atr_at_arrival (pips) | 4.39 | 4.04 | +0.19 |
| bb_width_at_arrival (pips) | 14.90 | 14.32 | +0.13 |
| speed_6bars_pips (\|Δ\|) | 4.25 | 3.35 | +0.12 |
| macd_hist_5m_at_arrival (\|·\|) | 0.22 | 0.17 | +0.15 |
| macd_hist_h1_at_arrival (\|·\|) | 1.35 | 1.29 | +0.11 |
| dist_to_next_level_pips | 27.4 | 22.3 | +0.15 |
| dist_extreme_to_level (during) | 3.53 | 4.86 | −0.30 |
| cluster_bars (during, definitional) |    2 |   18 | −0.93 |

Two categorical breakdowns are where the difference actually shows up:

**Session — the strongest pre-arrival separator:**

| Session | Turns | 5M_SCALE | AMB | H1_SCALE |
|:--|--:|--:|--:|--:|
| Asia   | 35  | 40% | 14% | **46%** |
| London | 90  | 51% | 26% | 23% |
| NY_AM  | 104 | **67%** | 15% | 17% |
| NY_PM  | 38  | **68%** | 16% | 16% |

Asia is essentially the *only* session where an H1-scale turn is roughly as likely as a 5M-scale one. NY hours are 2/3 5M-scale.

**Near-news within ±60 min of the turn:**

| News? | Turns | 5M_SCALE | AMB | H1_SCALE |
|:--|--:|--:|--:|--:|
| Yes   | 104 | **67%** | 17% | 15% |
| No    | 166 | 52% | 20% | **28%** |

News nearly doubles the H1 share when absent (28% vs 15%). A quiet-hours turn is much more likely to be an H1 event.

**5m ATR at arrival buckets:**

| ATR (pips) | Turns | 5M_SCALE | H1_SCALE |
|:--|--:|--:|--:|
| Low (< 3.5)   | 78  | 49% | 28% |
| Med (3.5–5.0) | 108 | 60% | 19% |
| High (≥ 5.0)  | 75  | **69%** | 19% |

**BB width at arrival:**

| BB width (pips) | Turns | 5M_SCALE | H1_SCALE |
|:--|--:|--:|--:|
| Narrow (< 10) | 44  | 52% | 27% |
| Med (10–20)   | 127 | 55% | 22% |
| Wide (≥ 20)   | 77  | **70%** | 18% |

All three volatility measures point the same way: high ATR / wide BB / high news activity → 5M-scale. Low volatility, quiet session → H1-scale.

**What does NOT separate the scales:**
- Which pivot (P vs R1/S1 vs outer) — proportions of 5M vs H1 are within a few points across levels.
- Approach direction (from_above vs from_below) — essentially identical.
- `arrival_from` (mid-corridor vs previous pivot) — nearly identical.
- MACD 5m expanding / not expanding at arrival — 46% vs 40% (mild).
- Prior touches of this level today — median 3 in both.
- BB position at arrival — 0.55 vs 0.46 (mild).
- Weekday — some spread but noisy (5M leans Thu/Fri, H1 more spread).

**Thin cells flagged:**
- 44 CONTINUATIONs total, split further by session/news/level yields groups of 5–15 — any cross-tab beyond one axis is not statistically supportable.
- 62 H1_SCALE turns; the by-session Asia cell is n=16.
- The "off" session bucket is n=59 total approaches, 3 turns — anything from that row is noise.

## Step 4 — plain answer

**Before price arrives at the level, three things are readable that matter, and each matters in a specific way:**

1. **Session tells you whether the approach will turn at all.** NY_AM 38.5%, London 29%, NY_PM/Asia 17%, off-hours 5%. This is the single strongest predictor of TURN vs CHOP.

2. **Volatility state — ATR, BB width, presence of news within an hour — tells you the *scale* of the turn if one comes.** High ATR (≥ 5 pips), wide BB (≥ 20 pips), news window: 65–70% of the resulting turns are 5M-scale. Low-volatility Asia session with no news: nearly half are H1-scale. **The scale is the reversal's timescale, and the reversal's timescale mirrors the market's timescale at arrival.**

3. **Prior touches and speed of arrival tilt turn-vs-continuation.** First touches with fast arrival from further away are ~1.8× more likely to break through (30% vs 17% first-touch base rate). Same-level revisits after multiple prior touches skew toward turning.

**What does not tell you anything.** MACD hist direction at arrival — 5m or H1 — has no signal for turn vs chop (~53% aligned in both, versus 50% by chance). MACD expanding at arrival does not predict scale (46% vs 40%). Which pivot is being tested is not a scale predictor. BB position at arrival is not a scale predictor.

**Bottom line.**

- **Whether the approach turns:** session + news. Volatility state matters mildly (BB, ATR).
- **Whether the turn is 5M-scale or H1-scale:** the same volatility state, more strongly. **High volatility / news / NY sessions → 5M event. Quiet Asia / no news / low ATR → H1 event.** In the extremes the split shifts from ~1:1 (Asia, no news) to ~4:1 in favour of 5M (NY_AM, news, high ATR).
- **Whether the turn will instead be a break-through:** first touch of the day from further away, with H1 MACD hist already tilting in the approach direction. Sample thin (44 continuations).
- **Nothing separates the outcomes with more than a small (Cliff's δ ~0.15–0.20) univariate effect.** No single pre-arrival measure would call the outcome for you; the best you have is a couple of small tilts in the same direction that compound.

## Reconstruction caveats

- All indicators recomputed from OHLC — no reliance on live cached values that may have drifted. Same pure functions as `indicators.py`.
- H1 synthesized by 1H resample of 5m — closes align exactly with the last 5m bar of the hour. No drift from the live htf_cache (which only covers 2026-06-29 forward anyway).
- News-window flag is best-effort: `HIGH`/`MED` impact, GBP or USD, within ±60 minutes of the turn timestamp. The Finnhub cache format has `ts`/`currency`/`impact`/`event`. Files are indexed by publication date, so ±1 day of files loaded per turn to catch events. Non-scheduled headlines (BOE speaker off-script, tariff tweet) are not in Finnhub.
- `arrival_from` requires a prior 12 bars of context; 21 turns near day-open have this null.
- The "extreme closest to the level" is interpreted here as the reversal extreme (highest high for from_below, lowest low for from_above). For deep-pierce H1-scale turns this extreme is many pips past the level; that is a real property of those turns, not a bug.
- Scale rule uses `bars_to_10p` as the definition. Alternate definitions ("H1 close-back through level" or "H1 wick_beyond_pips ≥ 3") shift the boundary by ±10 turns without materially changing the session/news/ATR conclusions.
- Session TURN% and news TURN% are joint marginals over the same 1,084 approaches — the two are correlated (news clusters in London/NY_AM). They do not add together linearly.
- 44 CONTINUATIONs is a small sample — the "first-touch bias" (30% vs 17%) is n=13 vs n=47, a 13-percentage-point gap with binomial-CI half-width around ±13 pp. It is a signal but well within stat-thin territory.
