# Stage 7A execution handoff — observe scheduled-hour reversal lifecycles

**Read-only study. This is not a live agent or a profitable strategy.**

Source research branch: `research/reversal-shadow-agent-20261022`
Code: `scripts/research/reversal_shadow_stage7a.py`
Hypothesis: nominated UK hours 06,07,08,10,11,12,13,14,16 may disproportionately intersect the **start or development** of meaningful reversals. Completed H1 candle range may correlate with subsequent directional moves.

## Host instructions
1. Verify source branch SHA, Stage 5/6 frozen research outputs, timestamp authority and CLEAN datasets. Do not change /opt/tradingbot or live services.
2. Use the SAME DEV/VAL/OOS partitions, copies and allowlists already validated for Stage 5. Reject any unverified new feed or silently merged BID/MID. Source-side labels and IG-scale pip-size MUST be verified per partition.
3. Create a new detached research worktree, never checkout the running production tree. Run the test suite before data processing.
4. Invoke the Stage 7A module separately for DEV, VAL and OOS. Example (paths placeholders; replace with verified research-copy paths):
```sh
python -m unittest discover -s tests/unit -p 'test_reversal_shadow_*.py' -v
python -m scripts.research.reversal_shadow_stage7a \
  --archive-root /VERIFIED/RESEARCH/CANDLES \
  --approved-clean-days /VERIFIED/RESEARCH/dev.txt \
  --source-side BID --pip-size 1 --symbol GBPUSD \
  --output-dir /VERIFIED/RESEARCH/stage7a/dev
```
5. Outputs: `anchor_snapshots.csv` is an AS-OF hourly snapshot only. `event_outcomes.jsonl` is separate **future outcome information**. Never use it as a live feature or as a retrospectively known snapshot state. `summary.json` gives initial descriptive counts and hourly completed-H1 range.
6. Record and validate at least 20 snapshots by hand, covering UK BST/GMT transition, side, consecutive anchors, candidates without confirmation, active confirmations and missing data. Verify that the same event retains its ID across hours.
7. Produce an **independent** opportunity-denominator comparison: total valid hourly checkpoints (even when zero events visible), count of new candidates known before/at/after anchor, confirmed-and-already-active at anchor, and active continuation across anchors. The initial module does NOT itself produce all these statistics; extend it in the research branch only after writing tests. Do not mistake snapshot count for hourly opportunities.
8. In this stage the onset signal remains the frozen Stage 5 H1 reversal event, which is knowable only at its H1 close. It will *not* find early intrahour turning points. Do not claim otherwise. Stage 7B must define an independent, point-in-time M5 onset/structure detector before evaluating those.
9. Report both nominated and other hour comparisons, broken out by hour, sample sizes and uncertainty. Explicitly distinguish event incidence from conditional continuation or direction. No performance/edge claim from snapshot counts.
10. Stop if source authority fails; return exact blocker. No production deploy, no automatic orders, no NMS changes, no optimisation against OOS.

Return summary, input/output SHA-256, tests, validation examples, excluded counts, specific findings, and whether evidence supports advancing to a separately preregistered Stage 7B.
