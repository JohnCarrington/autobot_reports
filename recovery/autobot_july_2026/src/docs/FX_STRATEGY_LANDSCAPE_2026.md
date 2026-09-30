# An Honest, Evidence-Based Map of the FX Retail Strategy Landscape

**Date:** 2026-04-21
**Scope:** Decision-support for the next 3 months of research on the `/opt/tradingbot` system.

> **Methodological note.** This report prioritises peer-reviewed work, BIS/NBER/SSRN papers, and regulator disclosures (ESMA, FCA) over trader blogs and broker marketing. Where a blog aggregator is cited it is because it is faithfully summarising an underlying regulatory or academic source. Where the literature disagrees, that is flagged. Nothing in here is a recommendation to trade or not trade — it is an evidence map.

---

## Part 1 — Category Survey

### 1. Carry trade (interest rate differentials)

- **Core thesis.** Long high-yielding currencies, short low-yielding ones; pocket the differential plus any spot appreciation. This is the most-studied "edge" in FX because the forward premium puzzle (UIP failure) is one of the most robust anomalies in the academic literature.
- **Timeframes / instruments.** Multi-week to multi-month. Deliverable FX, futures, or CFD spot positions held through rollover.
- **Evidence quality.** High. Lustig–Verdelhan and successors document positive long-run excess returns, but also show the returns compensate for FX volatility / crash risk (Menkhoff et al., "Carry Trades and Global Foreign Exchange Volatility"). Brunnermeier–Nagel–Pedersen show carry returns load on crash risk (negative skew).
- **Retail viability.** Low for an intraday bot. (i) Carry works on holding horizons measured in weeks; (ii) post-2015 differentials compressed globally under QE/ZIRP; (iii) August 2024 yen unwind is the modern illustration that carry can blow up all the hedge-fund positioning in days (BIS Sep 2024 Qtrly Review).
- **Failure modes.** "Go up the stairs, down the elevator" — negative skew. Periods like 2008, 2015 SNB, Aug 2024 wipe years of accrual.

### 2. Momentum / trend following

- **Core thesis.** Past winners keep winning on horizons of 1–12 months (cross-sectional or time-series).
- **Evidence quality.** Strong in FX specifically. Menkhoff, Sarno, Schmeling & Schrimpf (JFE 2012) find a cross-sectional winner-minus-loser spread of up to 10% p.a. in currencies, not explained by carry or standard risk factors, but with *"very effective limits to arbitrage"* — the edge exists but is costly to harvest. Managed futures / CTA indices (SG CTA, BarclayHedge) confirm real-money persistence: SG CTA Index +20.1% in 2022, ~flat 2023.
- **Retail viability.** Moderate. The research-grade edge is on daily+ timeframes across a basket of 15–30 currencies. On 4 majors at 5M intraday, you are not running "currency momentum" — you are running "intraday continuation", a different and much weaker phenomenon.
- **Failure modes.** Choppy markets, mean-reverting regimes (2015–2019 was particularly rough for trend), whipsaw drag from transaction costs.

### 3. Mean reversion (BB, RSI, stat-arb)

- **Core thesis.** Price overshoots its statistical "fair" range and reverts. The FX spot market does show mean reversion at very short horizons (microstructure noise) and at very long horizons (PPP). The middle — intraday hours to days — is dominated by noise or trend, not reversion.
- **Evidence quality.** Published backtests of Bollinger / RSI on EURUSD typically show profit factors 0.85–1.14 depending on timeframe, with the 1-hour edge basically evaporating after realistic spread. Academic synthesis (Neely, Weller; Park & Irwin) finds declining technical-rule profitability post-1995.
- **Retail viability.** Real but fragile. It works at BB pierces coincident with a session anchor (VWAP, PDH/PDL, overnight range) because you are piggy-backing on a liquidity-replenishment mechanism, not on the indicator itself. Naked BB/RSI on majors almost certainly does not work net of spread in 2026.
- **Failure modes.** News releases, breakouts (Jan 2015 CHF, March 2020, Aug 2024 — reversion strategies stacked into a directional break are career-ending).

### 4. News trading

- **Core thesis.** Scheduled releases produce mispricing windows of seconds to minutes where either (a) the spike itself is tradable or (b) the subsequent fade/continuation is tradable.
- **Evidence quality.** Academic consensus: macro news is the single largest driver of intraday FX variance (Andersen–Bollerslev–Diebold–Vega 2003 and successors). Whether a retail trader can *capture* that move is a separate question. BIS/ECB research on NFP shows spreads widen 3–5× in the first 60 seconds, and retail executions routinely slip 2–8 pips.
- **Retail viability.** Two regimes: (a) **pre-positioned direction** (actual vs forecast) — possible but requires a fast feed and discipline; (b) **first-candle breakout** — dominated by spread widening, not recommended. On IG spread-betting the spread-widening and slippage effectively tax the easy part of the move.
- **Failure modes.** Headline risk, revised prints, reversal after initial spike, spread blowouts.

### 5. Session-based (London open, NY open, Asian range)

- **Core thesis.** Liquidity step-functions at 08:00 London, 13:00 NY, 00:00 Tokyo produce reliable volatility clustering. The "Asian range → London breakout" is the most-published pattern.
- **Evidence quality.** BIS NBER working paper "Intra-day Seasonality in Activities of the Foreign Exchange Markets" (w12413) documents the intraday volatility U-curve extensively. ORB literature (Holmberg et al.) finds the intraday breakout edge is real in some markets/periods but *not robust across sub-periods* — the finding hinges on high-volatility windows.
- **Retail viability.** High for framing; moderate as a standalone edge. The session volatility *pattern* is one of the most persistent features in FX. Converting it into a positive-expectancy strategy after spread is harder — the naive London breakout has been known and traded for 20 years.
- **Failure modes.** Monday holiday Asia (range is noise), Fed/ECB day London opens (pre-news chop), summer August liquidity.

### 6. Order flow / volume-based

- **Core thesis.** Order flow (signed trades) is the proximate price-discovery variable in FX (Evans & Lyons 2002, JPE). If you can see flow you can predict short-horizon returns.
- **Evidence quality.** Seminal academic support, but — critically — only for those with access to actual flow data (bank customer flow, Reuters/EBS CLOB). Retail sentiment (IG/OANDA long-short ratios, FXSSI) is a noisy proxy and retail extremes do correlate with short-term reversals on a weekly horizon, but the signal is weak and widely monitored.
- **Retail viability.** (i) Retail sentiment: publicly available, modest contrarian edge at extremes, not reliable for intraday. (ii) CFTC COT: weekly, lagged 3 days, extreme-only — useful as regime context, not for a 5M trigger. (iii) Real institutional flow: not retail-accessible.
- **Failure modes.** Extreme sentiment can stay extreme during strong trends; COT has known structural breaks post-GFC (Bank for Intl. Settlements literature).

### 7. Correlation-based

- **Core thesis.** Pairs that normally track (EURUSD vs GBPUSD; AUDUSD vs NZDUSD; crosses vs dollar index) deviate and then reconvert.
- **Evidence quality.** Thin academic support at intraday horizon. Most published pairs-trading literature is on equities, where there is a cointegration mechanism; in FX the "correlation" is usually just common USD exposure, which is a regime variable, not a mean-reverting one.
- **Retail viability.** Low as a primary edge. Useful as a *filter* (e.g. "don't be short GBPUSD if EURUSD just broke its high") but the cointegration arbitrage story does not hold on 5M.
- **Failure modes.** Correlation breaks are usually the *signal of a regime change*, not a reversion setup.

### 8. Seasonality (day-of-week, time-of-day)

- **Core thesis.** Systematic return/vol differences by calendar position.
- **Evidence quality.** Mixed. Time-of-day (intraday volatility U) is robust. Day-of-week on returns is weaker and unstable post-2000 (multiple studies find the classic "Monday effect" has decayed). Month-of-year (e.g. "sell USD in May") is weaker still and survives mostly in bucket-picked datasets.
- **Retail viability.** Time-of-day filters: useful. Day-of-week entry filters: suspicious, very high overfitting risk with only ~250 observations per weekday per year.
- **Failure modes.** Regime breaks (COVID rewrote every "seasonal" effect in 2020–2021).

### 9. Macro fundamental

- **Core thesis.** Trade currencies where the central bank reaction function is repricing (rate expectations, terms-of-trade, balance of payments).
- **Evidence quality.** Macro hedge funds demonstrably make money at this (survivors), but it is a multi-week horizon and depends on privileged analysis capacity. Academic support for "interest rate differential drives spot" is weak at <12 month horizons (forward premium anomaly).
- **Retail viability.** Low as a mechanical 5M strategy. High as *context* layered on top of a technical trigger — e.g. "only trade GBPUSD long if rate differentials and Gilt spread are supportive." This is essentially what the morning-briefing layer is trying to capture.
- **Failure modes.** Being "right but early" (months of drawdown); central bank surprises.

### 10. Market microstructure (spread dynamics, liquidity gaps)

- **Core thesis.** The structure of the order book (spreads, kerb jumps, stop clusters, session handoffs) produces local predictability.
- **Evidence quality.** Strong at HFT timescales (Evans–Lyons; Easley, López de Prado, O'Hara). Essentially non-existent at retail-accessible latency with spread-betting execution.
- **Retail viability.** Very low as a primary edge (you are on the wrong side of the latency curve). Useful as a *risk management* layer — avoid entries during spread widening, avoid stops in obvious liquidity pools.
- **Failure modes.** Retail is typically the flow being *run over* by microstructure, not the one harvesting it.

---

## Part 2 — Honest Evidence Review

### 2.1 The "70–80% lose" statistic — what it actually means

The headline figure is real, narrow, and comes from regulator-mandated disclosure.

| Source | Figure | Population | Definition of "lose" |
|---|---|---|---|
| ESMA NCA survey, 2018 intervention | **74–89%** | EU retail CFD accounts, 4 NCAs | Net-loss account over measurement period |
| Broker KID disclosures (2024–2025) | Typically **70–82%** | Each broker's own UK retail CFD & spread-bet client base | Active-quarter net loss |
| FCA (cited in historical data) | Avg loss per trader ~£2,200 (2016), ~£4,100 (2018) | UK CFD retail | Per-account P&L |
| CFTC (US retail FX dealers, quarterly IB reports) | 65–75% losing accounts typical | Active accounts | Quarterly P&L |
| Barber, Lee, Liu, Odean — Taiwan day traders | **>80% lose** net of costs; 80% quit in ≤2 years | Full-market sample, 15 years | Net-of-cost P&L |

Important nuances most blog posts get wrong:

1. **"Per active quarter" is not "per lifetime".** A trader who has three losing quarters, then quits, counts as losing in all three; a trader who is up for 5 years and then has one bad quarter counts as a loser that quarter. The true "ever profitable over lifetime" number is lower than the quarterly figure suggests — Barber–Odean on Taiwan data put sustained profitability at **~1%** of day-traders over 15 years.
2. **Broker skew is real.** eToro reports ~46% losing (many are copy-traders); Plus500 reports ~76% (direct CFD). The instrument mix matters: CFD-index clients lose more than copied-portfolio clients.
3. **Spread-betting specifically.** UK spread-betting is tax-advantaged (no CGT) but is otherwise a CFD clone; the loss rates are in the same band. Johnny's setup falls here.
4. **Sample selection.** The ~10–15% profitable minority in most studies is a *cross-section* — not the same 10% each year. Persistence is the harder statistic, and it is harsh: roughly 3–5% are profitable over 3+ years, ~1% over 10+.

**Bottom line:** The 70–80% figure is if anything *optimistic* on lifetime basis. It's the quarterly snapshot. Sustained multi-year profitability is rarer.

### 2.2 Backtest-vs-live performance gap

Bailey, Borwein, López de Prado and Zhu ("Pseudo-mathematics and financial charlatanism", 2014; "Probability of Backtest Overfitting") formalised what practitioners have known for 30 years:

- With enough hyperparameter trials, **any** price series will yield a Sharpe >2 backtest purely by chance.
- The "deflated Sharpe ratio" — Sharpe corrected for number of trials, non-normality of returns, and finite sample — typically cuts retail-published strategies' implied Sharpes by 60–90%.
- Published finance-journal strategies have an average out-of-sample decay of roughly 50% of in-sample Sharpe (Harvey, Liu, Zhu 2016, "... and the Cross-Section of Expected Returns").

Practical implications for this system:
- Every time `backtest_bb_reversal_*.py` is re-parameterised on Apr-16/17 data, the subsequent out-of-sample expectation should be marked down heavily. The Apr-16–21 window has ~4 trading days of data — statistically, effectively zero independent observations.
- The 376-record Sentinel training set is *barely above the line* for a logistic-regression-ish classifier with ~5 features. Rule-of-thumb: ≥20 outcomes per feature (Peduzzi 1996), so 100 records for 5 features is the floor, 200+ is comfortable. Worth using, not worth trusting the coefficients to 2 significant figures.

### 2.3 Capital requirements — realistic Sharpe for retail FX

Combining the academic + CTA industry numbers:

| Approach | Plausible live Sharpe (net) | Capital needed for $1k/mo at 10% vol |
|---|---|---|
| Diversified CTA trend basket (institutional) | 0.5–0.8 | n/a — 20+ instruments required |
| Single-instrument trend following | 0.2–0.4 | $100k+ |
| FX cross-sectional momentum (full basket) | 0.5–0.7 | retail-inaccessible (needs 15+ pairs) |
| Retail intraday systematic (4 majors) | 0.2–0.6 is the *aspirational* band | $30–100k for a stable income stream |
| "Edge-free" discretionary retail | ~0 or negative | any |

**Anyone quoting Sharpe >1.5 on a retail intraday FX system should be assumed to have an overfit backtest or cherry-picked window until proven otherwise.**

---

## Part 3 — What Actually Holds Up

Synthesising the peer-reviewed and industry-disclosure evidence, the edges that have **survived out-of-sample and are accessible in principle** to a retail FX trader:

1. **Cross-sectional FX momentum** (Menkhoff et al.) — requires a basket of 15–30 pairs at daily+ frequency; limits-to-arbitrage are real but it does survive modern data. *Not what a 4-majors 5M system does.*
2. **Time-series trend following across asset classes** (CTA / managed futures literature) — confirmed in live money at large scale; Sharpes ~0.5 net. Again, basket matters.
3. **Session-open volatility clustering** — the pattern is robust, but converting to positive-expectancy requires a filter that separates the 30% of days where it works from the 70% where it's noise.
4. **Scheduled-news event pre-positioning** — real edge available for retail where actual-vs-forecast surprise combined with pre-release positioning is captured fast, *and* execution is disciplined about spread widening. The NEWS_TICK wiring here is in the right conceptual neighbourhood.
5. **Extreme retail-sentiment contrarian fades** — small, weekly horizon, widely monitored, hard to scale. Documented in IG / OANDA / DailyFX research; academic support thinner.
6. **Risk-premium carry**, at basket level, held for weeks. Retail-accessible via futures/CFD but subject to crash risk and not intraday.

What systematic macro / CTA funds actually do:
- Diversify heavily (dozens to hundreds of instruments across FX, rates, equities, commodities).
- Run many signals in parallel (trend at several horizons, carry, value, macro).
- Size on volatility targeting.
- Accept ~15–25% drawdowns as normal.

What a retail trader can plausibly replicate:
- Volatility-targeted position sizing.
- Small basket (majors + a handful of crosses) instead of single-pair concentration.
- A *few* orthogonal signal families rather than ten variants of one.
- Aggressive journalling to distinguish edge from variance.

---

## Part 4 — Fit Analysis for `/opt/tradingbot`

### Strategy × Fit matrix

| Category | Status in current stack | Classification |
|---|---|---|
| 1. Carry | Not implemented; intraday-only mandate | (d) Not a good fit — wrong timeframe |
| 2. Momentum / trend | Partially: `ema_pullback`, `session_impulse_breakout`, briefing direction gates | (a) Worth doubling down — but as a *cross-pair basket* test, not another single-pair script |
| 3. Mean reversion | Heavily: `bb_reversal`, `reversal_sweep`, `exhaustion_reversal`, `daily_double` | (a) Already core — but the evidence base is the weakest of the ones you rely on |
| 4. News | Yes: `NEWS_STRATEGY` + `NEWS_TICK` + Finnhub + TE + ForexFactory + briefing avoid-before gate | (a) Strong existing footprint; biggest edge-per-line-of-code in the stack |
| 5. Session-based | Yes: DAILY_DOUBLE, BB_REVERSAL GBPUSD-Monday D-3-Y, 3CO, `london_open_pullback` | (a) Core — and the one with the best academic underpinning you currently exploit |
| 6. Order flow / sentiment | Not wired; no retail-sentiment feed; no COT ingestion | (b) Trivial to add (IG sentiment scraped daily; COT weekly from CFTC) |
| 7. Correlation | Not wired | (b) Trivial to add as *filter* (EURUSD/GBPUSD/DXY proxy) using existing tick ingestion |
| 8. Seasonality | Implicitly via session windows, explicitly via GBPUSD-Monday config | (a) Already there; main risk is overfitting — keep few, coarse buckets |
| 9. Macro fundamental | Partially via morning briefings (LLM-generated regime + bias) | (a) Continue; the briefing layer is one of the most differentiated parts of the stack |
| 10. Microstructure | Only used defensively (`news_blackout`, spread filters if present) | (d) Not a primary edge — retail is on the wrong side |

---

## Part 5 — Specific Recommendations: 3 research directions for the next 3 months

### Recommendation A — "Does the briefing add alpha, or is it narrative theatre?"

**Why this first.** The LLM briefing layer is the most expensive part of the stack to maintain (Claude API cost + morning cognitive load) and the hardest one to evaluate by intuition. The literature (Evans & Lyons; Andersen–Bollerslev on news) says contextual information *can* predict intraday FX returns, but says nothing about whether *your* briefing is capturing it or just post-hoc narrating.

- **Data to gather.** For every briefing issued in the last 90 days: (1) the bias it declared, (2) the regime it declared, (3) the explicit plan it outlined, (4) the actual close-to-close return of each pair over the briefing's stated horizon, (5) the actual P&L of every `BRIEFING_*` trade. You likely already have most of this in `briefing_tracker.py` / `briefing_outcome_tracker.py`; audit completeness.
- **Test.** Two-pronged:
  - **Directional**: Was the declared bias correct more than 50% of the time, net of the trivial "same sign as overnight move" baseline? Chi-square / binomial test. You need ~60 independent calls for a 10pp effect at p<0.05.
  - **Value-add**: Does `BRIEFING_EXECUTION` outperform a "same-setup without briefing gate" version run in shadow? Paired-sample test on per-trade P&L.
- **Realistic edge size.** If the briefing is real signal, expect 52–56% directional accuracy on the daily bias and a 5–15bps/trade uplift on gated strategies. If it's noise, those numbers will be indistinguishable from baseline. **Worth knowing either way**: a negative result here would let you delete or sharply curtail an expensive subsystem.

### Recommendation B — "Is Sentinel picking up edge or just session bias?"

**Why.** The 376-record Sentinel training set is just barely sufficient for the feature set (strategy, direction, session, bb_width, atr). Bailey–López de Prado's deflated Sharpe literature says a logistic classifier trained on so few samples with 5+ features has a high probability of learning the training distribution's accidents (session bias especially).

- **Data to gather.** Rebuild the training set with explicit k-fold purged cross-validation (López de Prado "Advances in Financial Machine Learning" ch. 7 — the standard reference for backtest cross-validation in trading). Add "days since training" as a monitored variable in live decisions so decay is observable.
- **Test.** Three stages:
  1. **Bootstrap calibration test.** Resample 376-record set 1000 times; compute score distribution. If the feature coefficients are unstable across bootstraps, the model is overfit.
  2. **Held-out session test.** Train on London+NY sessions only; test on Asian. If performance collapses, Sentinel is a session-regime classifier, not a trade-quality classifier.
  3. **Shadow vs live.** Run Sentinel's score as *advisory* (log-only) for 4 weeks in parallel with its gate role; compare trades it would have blocked vs let through. This is probably the cleanest experiment you can run.
- **Realistic edge size.** A genuinely useful binary gate on retail FX is in the 3–8pp-of-win-rate range. If Sentinel claims more than 10pp, be suspicious. If it shows less than 2pp on out-of-sample, keep it as a diagnostic but remove it from the execution path.

### Recommendation C — "Is there a GBPUSD-specific session edge that is stable out-of-sample, or is D-3-Y a Monday ghost?"

**Why.** The memory note `project_bb_reversal_d3y.md` records a GBPUSD-only Monday configuration. This is exactly the kind of finding that Bailey et al. warn about: small-n, bucket-picked, no multiple-testing correction. Before committing more capital it needs an honest out-of-sample test.

- **Data to gather.** You already have `fetch_histdata_ticks.py` / `build_ohlc_from_ticks.py`. Pull 5+ years of GBPUSD tick data (histdata.com is free for this). Bucket by (session, day-of-week, bb_width-quintile, atr-quintile). The 2015–2019 period is particularly important because it was a range/low-vol regime that will test whether the edge survives non-Brexit conditions.
- **Test.** Walk-forward: fit D-3-Y parameters on 2019H1, test 2019H2; roll forward quarterly. Track hit rate and expectancy per bucket. Apply Benjamini–Hochberg correction for the number of buckets tested — this is the single biggest discipline step most retail backtests skip.
- **Realistic edge size.** The academic intraday literature (London breakout, opening range) suggests a ~5–15bps/trade edge is plausible for a genuine session pattern at 1–3 trades/week, **before** spread. After GBPUSD spread-bet cost (~1p), net edge of 0–5bps/trade is the honest expectation. If the walk-forward shows more than that, recheck for look-ahead.

### What NOT to do right now

- **Don't build more strategies.** You have ~14. The marginal return on strategy #15 is far below the marginal return on properly validating strategy #1–14. Bailey/López de Prado's multiple-testing math is unforgiving: 14 strategies × 5 parameters each = a selection bias that has to be corrected for.
- **Don't add a neural net on 376 samples.** `neural_meta_controller.py` and `causal_transformer.py` are conceptually interesting but are unbacked by sample size. Logistic > XGBoost > NN in that order for n<1000 labelled trades.
- **Don't hunt for new timeframes.** You are already at 5M. Moving to 1M adds cost, not edge, at retail latency. Moving to 15M or 1H might surface momentum you can't see — but that's a separate research project, not a "quick win".

---

## Part 6 — Honest Bottom Line

**Is there edge out there for a retail FX trader?** Narrowly, yes. The academic literature documents at least three robust edges (cross-sectional momentum, time-series trend, carry-crash-premium). None are ideally suited to a single-trader, 4-majors, 5M, intraday setup. The edges that *are* well-suited to that setup — session vol clustering, scheduled news pre-positioning, possibly local mean reversion at liquidity anchors — are smaller, more regime-dependent, and more crowded than the basket edges.

**Realistic expectation for a disciplined retail FX trader?** Over a 3+ year horizon, the empirical floor for "profitable with discipline and genuine edge" is roughly the top decile of accounts — an inconsistent 5–25% annualised with drawdowns of 15–30%. The "10% per month consistently" mythology is a marketing fiction not supported by any regulator, any academic paper, or any audited fund track record at scale. A Sharpe of 0.4–0.8 net of costs, with drawdowns matching the Sharpe, is the realistic high end. The *median* retail outcome is loss.

**Is continuing development rational vs. passive investing?**
- Purely as a financial expected-value calculation on the capital you'd otherwise deploy: no. An S&P/MSCI World index fund has a ~0.5 long-run Sharpe with no time input; you would need a live-money Sharpe ≥0.5 *after* valuing your time at zero to match it on risk-adjusted terms alone.
- As an educational / infrastructure / optionality project: plausibly yes. Twelve months of building has produced a non-trivial piece of infra (tick ingestion, candle builder, briefing layer, replay engine, ML scorer) that has transferable value — to you, to research, or potentially to productisation. That value is real even if the trading P&L is zero.
- As a source of compounding income at current capital: probably not at useful scale. Even at Sharpe 0.5 and 10% vol, you'd need ~£200k+ capital to earn a meaningful replacement income, which is not how IG spread-bet accounts are typically sized.

**What separates the profitable retail minority from the 70–80%?** The Barber–Odean-style and CFTC/ESMA-adjacent findings converge on a short list:
1. **They trade less.** "Profitable traders execute ~20% fewer trades" is the most replicated finding in the literature.
2. **They size risk small and vol-target.** Blow-up risk is the dominant negative-tail driver of lifetime P&L.
3. **They specialise.** One or two setups, deeply understood, journalled, and evaluated per-trade.
4. **They have an edge they can articulate causally** — they know *why* the trade has positive expectancy, not just that the backtest said so.
5. **They survive long enough to compound.** ~80% quit within 2 years (Barber–Lee–Odean). Selection bias does the rest.
6. **They separate evaluation from execution.** The trader is not the same person-role as the system-validator, even when it's one human.

Current stack is good at (3) and (6) already — the DAILY_DOUBLE / BB_REVERSAL setups are specific and narrow, the replay and Sentinel infra gives a validator role separate from the executor. The stack is *weak* at (4) — there are a lot of knobs and not a clean articulation of "we believe edge X exists for reason Y; this setup captures it". And it is at risk on (1) — pyramiding days +149p / counter-trend-stack days −43p is *exactly* the variance profile of a system that sometimes over-trades.

---

## Recommended next steps (concrete)

1. **This week:** pick one of Recommendations A, B, C and timebox 2 weeks of pure research (no new strategies, no parameter changes to live). Recommendation A is the highest-leverage one because briefings are the most expensive subsystem and the one whose value is most opaque.
2. **Next 30 days:** implement walk-forward + Benjamini–Hochberg correction in the backtest harness so future claims about any setup are not vulnerable to multiple-testing inflation. This is a one-off infra cost that protects every future strategy decision.
3. **Next 90 days:** set a written hypothesis for each active strategy — *in one sentence, why does this have positive expectancy?* — and require new strategies to pass that bar before going live. Review quarterly. A strategy you can't defend in one sentence is a strategy you are going to overtrade.
4. **Calibration:** commit to a number for expected live Sharpe of the overall system (mine: 0.3–0.5 realistic, 0.8 optimistic). Check monthly whether the live track record is consistent with that prior. If actual Sharpe is systematically below 0.2 net after 6 months of honest accounting, passive investing is the right comparison and acting on it is rational, not defeat.

---

## Sources

**Regulatory disclosures**
- [ESMA – Product Intervention (CFDs) press release](https://www.esma.europa.eu/press-news/esma-news/esma-agrees-prohibit-binary-options-and-restrict-cfds-protect-retail-investors)
- [ESMA – Additional information on agreed product intervention (NCA loss-rate data)](https://www.esma.europa.eu/sites/default/files/library/esma35-43-1000_additional_information_on_the_agreed_product_intervention_measures_relating_to_contracts_for_differences_and_binary_options.pdf)
- [Central Bank of Ireland – CFD Intervention Measure](https://www.centralbank.ie/docs/default-source/regulation/industry-market-sectors/investment-firms/mifid-firms/regulatory-requirements-and-guidance/central-bank-cfd-intervention-measure.pdf?sfvrsn=8)
- [FCA – Warnings on CFDs (2025 summary, A&O Shearman)](https://finreg.aoshearman.com/uk-fca-warns-retail-investors-of-risks-in-cfds-trading)
- [Finance Magnates – FCA reports £75m CFD losses at one firm](https://www.financemagnates.com/forex/fca-reports-75m-cfd-loss-for-90k-retail-investors-at-one-firm-promoted-by-finfluencers/)
- [Good Money Guide – CFD broker loss-rate disclosures](https://goodmoneyguide.com/trading/risk-warning-loss-percentages/)
- [Cambridge BPP — "Trading is a losing game"](https://resolve.cambridge.org/core/journals/behavioural-public-policy/article/trading-is-a-losing-game-an-audit-of-deceptive-choice-architecture-in-demomode-contract-for-difference-cfd-trading-apps/07BB4E4CC011413D8A41458F9ED32928)

**Carry trade / FX risk premia**
- [Menkhoff, Sarno, Schmeling, Schrimpf — "Carry Trades and Global Foreign Exchange Volatility" (Journal of Finance)](https://faculty.washington.edu/ss1110/IF/Sarno%20JF%20Carry%20Trade%20(1).pdf)
- [Lustig & Verdelhan — "Term Structure of Currency Carry Trade Risk Premia" (NBER w19623)](https://www.nber.org/system/files/working_papers/w19623/w19623.pdf)
- [Brunnermeier, Nagel, Pedersen — "Carry Trades and Currency Crashes" (NBER w14473)](https://www.nber.org/system/files/working_papers/w14473/w14473.pdf)
- [Burnside — "Carry Trades and Risk" (NBER w17278)](https://www.nber.org/system/files/working_papers/w17278/revisions/w17278.rev0.pdf)
- [BIS Quarterly Review Sep 2024 — "Carry off, carry on"](https://www.bis.org/publ/qtrpdf/r_qt2409a.htm)
- [BIS — "Hedge fund exposure to the carry trade"](https://www.bis.org/publ/qtrpdf/r_qt2409x.htm)

**Currency momentum**
- [Menkhoff, Sarno, Schmeling, Schrimpf — "Currency Momentum Strategies" (JFE 2012 / SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1988679)
- [BIS Working Paper 366 (same authors)](https://www.bis.org/publ/work366.pdf)

**Order flow / microstructure**
- [Evans & Lyons — "Order Flow and Exchange Rate Dynamics" (NBER w7317)](https://www.nber.org/papers/w7317)
- [Lyons & Evans — "Understanding Order Flow" (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=842482)
- [BIS — "Order flow and exchange rate dynamics"](https://www.bis.org/publ/bppdf/bispap02j.pdf)
- [ScienceDirect — "News and intraday retail investor order flow in FX"](https://www.sciencedirect.com/science/article/abs/pii/S1042443125000368)

**Technical analysis / mean reversion in FX**
- [St. Louis Fed WP 2011-001 — "Technical Analysis in the Foreign Exchange Market"](https://files.stlouisfed.org/files/htdocs/wp/2011/2011-001.pdf)
- [Cogent Econ & Finance — profitability of piercing line / dark cloud cover patterns in FX](https://www.tandfonline.com/doi/full/10.1080/23322039.2020.1768648)
- [Taylor & Francis — "Predictability of technical analysis in FX" (2024)](https://www.tandfonline.com/doi/full/10.1080/23311975.2024.2428781)

**Day-of-week / intraday seasonality**
- [ScienceDirect — "Intraday-of-the-week effects in exchange rates"](https://www.sciencedirect.com/science/article/abs/pii/S1566014119302031)
- [NBER w12413 — "Intra-day seasonality in FX activity"](https://www.nber.org/system/files/working_papers/w12413/w12413.pdf)

**Opening range / session breakout**
- [Holmberg et al. — "Assessing the profitability of intraday ORB strategies" (SSE WP)](https://swopec.hhs.se/umnees/abs/umnees0845.htm)
- [IEEE — "Profitability of timely ORB on index futures"](https://ieeexplore.ieee.org/document/8641124/)

**COT / sentiment**
- [ScienceDirect — "Predictive role of large futures trades for S&P returns"](https://www.sciencedirect.com/science/article/abs/pii/S1042443113000723)

**Retail-trader profitability (academic)**
- [Barber, Lee, Liu, Odean — "Do Day Traders Rationally Learn About Their Ability?"](https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trading%20and%20Learning%20110217.pdf)
- [Barber & Odean — "Just How Much Do Individual Investors Lose by Trading?"](https://www.researchgate.net/publication/23935366_Just_How_Much_Do_Individual_Investors_Lose_by_Trading)
- [Barber et al. — "Do Individual Day Traders Make Money? Evidence from Taiwan"](https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trade%20040330.pdf)

**Backtest overfitting**
- [Bailey, Borwein, López de Prado, Zhu — "The Probability of Backtest Overfitting" (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
- [Bailey, Borwein, López de Prado, Zhu — "Pseudo-Mathematics and Financial Charlatanism"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2308659)
- [Wiley / Significance — "How backtest overfitting leads to false discoveries"](https://rss.onlinelibrary.wiley.com/doi/10.1111/1740-9713.01588)

**CTA / trend following**
- [AQR — "Demystifying Managed Futures"](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Demystifying-Managed-Futures.pdf)
- [HedgeNordic — "Managed Futures / CTA Report 2023"](https://hedgenordic.com/wp-content/uploads/2023/03/CTA-Report-2023.pdf)
- [arXiv 2507.15876 — "Re-evaluating trend factors in CTA replication (2025)"](https://arxiv.org/html/2507.15876v1)
- [Quantica Capital — "When Trend-Following Hits Capacity" (Q1 2025)](https://quantica-capital.com/en/publication/qi-2025Q1)
