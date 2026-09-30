# Missing capabilities and known limitations

## Not delivered in this package (intentionally)

* **Live broker wiring on the destination droplet.** Only the offline
  replay, unit tests and observation-mode recorder tail are proven
  here. `TREND_EXECUTION_ENABLED=0` by default and the operator must
  supply IG_USERNAME / IG_API_KEY / IG_PASSWORD out-of-band, then wire
  `IGExecutor` into `observation_runner.py`'s `run()` loop after the
  first strategy signals fire.
* **IG login (password-based Session token flow).** `IGExecutor`
  accepts a caller-supplied `requests.Session`. Wiring the full IG
  session lifecycle (login, refresh, logout, session coexistence with
  the AutoBot recorder) is a follow-up task tracked in
  `docs/missing_capabilities.md#follow-up`.
* **Historical IG price fetch.** Not wired and not needed —
  offline replay uses the local candle archive, and observation mode
  uses the recorder tail.
* **Chart-visual verification of the 22:00 UTC pivot boundary.** The
  boundary is asserted based on the AutoBot convention. A follow-up
  audit should compare Trend Runner's daily OHLC against IG chart
  reference for a random sample.
* **Sub-M5 exit granularity from ticks.** The exit engine works on
  completed 5-minute bars. Stop/target ambiguity within one bar is
  resolved conservatively (stop wins over target). The tick archive is
  available and a follow-up may refine within-bar exit prices.
* **P30 legacy reconciliation.** Any outstanding Project Thirty
  positions must be resolved by their owning process; Trend Runner
  refuses to import them.
* **Deployment on the destination droplet.** This host (161n) builds
  and validates the package; it does not deploy. The published branch
  gives the destination everything it needs to install.

## Known limitations

* Full-corpus replay currently reports mid-only fills and does not
  deduct broker execution costs. Realistic PnL will be lower than the
  headline `net_pips`.
* The `M5Aggregator` boundary-aligns bars to their nominal 5-minute
  starts. If the recorder skips a boundary tick, the aggregator will
  still emit a valid bar at the next arriving tick — the bar start
  remains anchored to the 5-minute floor.
* `pause_hint` is exposed by the regime engine as a diagnostic; the
  strategy currently uses it only for entry sizing decisions in future
  revisions, not as a live gate.
* `SwingBuffer.direction()` is O(1); `infer_direction(list)` remains
  O(len(list)) for compatibility with tests. Callers on the hot path
  use the buffer variant.

## Follow-up

1. Wire the IG login flow behind an operator-flipped
   `TREND_EXECUTION_ENABLED=1` env with password-based Session token
   refresh; verify session coexistence with the recorder on staging
   before enabling in production.
2. Extend the exit engine with within-bar tick refinement for
   `PROTECTIVE_STOP` and `R3_TARGET`/`S3_TARGET` decisions.
3. Add a spread-aware fill model to the offline replay to close the
   gap between mid-only pips and net PnL.
4. Verify the 22:00 UTC pivot boundary against IG's chart reference on
   Fridays and Sundays.
