# Stage 7B — H1 Bollinger pierce to M5 observation (research handoff)

## Frozen initial watch definition (do not mistake for an executable entry)
- H1 Bollinger Band **20-period, 2 population standard deviations** on **last 20 fully completed, consecutive H1 closes**, excluding the developing H1. This is a *research convention* to avoid intrahour lookahead, not a claim that it matches a chart's dynamically updating current H1 band.
- During the next H1 hour, the first **closed M5 candle** whose high strictly exceeds the frozen upper H1 band queues `SELL_WATCH`; low strictly below the frozen lower queues `BUY_WATCH`. The intrahour high/low is only known after that M5 candle closes.
- At most one watch per direction per hourly bucket; never imply an order.
- Preserve UK's nominated nine hours 06,07,08,10,11,12,13,14,16 as *labels*, not hard gates. Record time to earliest watch, most recent completed H1 range, and watches at 09/15 as prespecified comparison controls.
- Do not impose the separate M5 three-candle Bollinger Bounce strategy (20/2, fixed 30/12) on these research events without a distinct prespecified comparison. That strategy is NOT changed.

## Stage 7B.1: historical watch-frequency census
On a detached research worktree fetched from `research/reversal-shadow-agent-20261022`:

1. Independently verify Stage 5/6/7A audit hashes and 703 approved CLEAN days. Treat historical BID DEV/VAL and MID OOS separately.
2. Run `python -m unittest discover -s tests/unit -p 'test_reversal_shadow_*.py' -v`.
3. Run each partition separately using existing *verified* archive copy and allowed-day file:
```bash
python -m scripts.research.reversal_shadow_stage7b_bb \
  --archive-root /VERIFIED/CLEAN/DEV_M5_ROOT \
  --approved-clean-days /VERIFIED/ALLOWLIST/dev.txt \
  --symbol GBPUSD --source-side BID --pip-size 1 \
  --output-dir /VERIFIED/OUTPUT/stage7b/dev
```
Repeat for VAL BID and OOS MID, with their own roots and allowlists.
4. Audit 20 raw M5/H1 examples by hand including touches that must not count, same-hour double-direction watches, clock changes, and source gaps. Report denominator: eligible M5 candles/H1 hours as well as watch counts. Keep zero-watch hours in the denominator.
5. For each watch, tag the Stage 5 detector's known-at-time states, whether the watch preceded completed-H1 detection, and the UK clock time. **Do not join on eventual confirmation as a feature**.
6. First deliver counts and actual event lead times. **Do not claim bounce success before point-in-time M5 rejection/structure and first-hit outcome definitions exist.**

## Stage 7B.2: continuation-vs-failure preregistration (NOT YET IMPLEMENTED)
Before viewing outcomes, freeze:
- M5 price-action evidence for bounce vs continued band excursion, including how long a watch remains valid.
- M5 event identity across multiple hourly watches and duplicate/overlapping observations.
- A point-in-time entry-proxy rule.
- Independently evaluated +20 and +30 pip thresholds, adverse invalidation/stop, time horizon and tie policy when target and stop both occur in a single M5 bar.
- Zero/missing-candle censoring, spread/slippage and realistic cost estimate, and time/range matched controls.
- Source-consistent OOS design; the current 2026 OOS MID archive has already been *descriptively explored* in Stage 7A. Do not portray follow-on threshold tuning against it as pristine untouched OOS.

## Constraints
Never change live AutoBot, BB-Bounce, NMS V3, systemd or IG credentials. Report a blocker if authority cannot be verified. New code is an *offline watch generator*, not a continuously running production agent.
