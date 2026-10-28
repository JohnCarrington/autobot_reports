# P3 deployment readiness

**NOT AUTHORISED for deployment.**  This document records the
state in which P3 is left after Workstream B completion.

## 1. Build state

| Artefact | Path | Commit |
|----------|------|--------|
| CLI entry | `scripts/research/live_obs/trigger_evaluator/cli_sweep.py` | `fix` worktree HEAD |
| Core evaluator | `scripts/research/live_obs/trigger_evaluator/trigger_evaluator.py` | same |
| systemd service | `scripts/research/live_obs/trigger_evaluator/deploy/live-market-observer-trigger-eval.service` | same |
| systemd timer | `scripts/research/live_obs/trigger_evaluator/deploy/live-market-observer-trigger-eval.timer` | same |

Fix worktree: `/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/`
Branch: `feat/scenario-v2-systemic-p1p2p3-20261028`

## 2. Deployment procedure (NOT TO BE EXECUTED without operator approval)

### Step 1 — install evaluator module to production path

```
WT=/home/autobot/tradingbot-wt/scenario-v2-reasoner-fix-20261028/scripts/research/live_obs/trigger_evaluator
LO=/mnt/volume_lon1_1778405456698/research/live_obs/trigger_evaluator

sudo install -d -o autobot -g autobot -m 0755 ${LO}
sudo install -o autobot -g autobot -m 0644 ${WT}/__init__.py    ${LO}/__init__.py
sudo install -o autobot -g autobot -m 0644 ${WT}/trigger_evaluator.py ${LO}/trigger_evaluator.py
sudo install -o autobot -g autobot -m 0644 ${WT}/cli_sweep.py   ${LO}/cli_sweep.py
```

### Step 2 — install systemd units

```
sudo install -o root -g root -m 0644 \
    ${WT}/deploy/live-market-observer-trigger-eval.service \
    /etc/systemd/system/live-market-observer-trigger-eval.service
sudo install -o root -g root -m 0644 \
    ${WT}/deploy/live-market-observer-trigger-eval.timer \
    /etc/systemd/system/live-market-observer-trigger-eval.timer
sudo systemctl daemon-reload
```

### Step 3 — enable + start timer

```
sudo systemctl enable --now live-market-observer-trigger-eval.timer
sudo systemctl list-timers live-market-observer-trigger-eval.timer --no-pager
# Next fire should align with the next XX:00:15, XX:05:15, … UK local
```

### Step 4 — monitoring

Watch the first fire in logs:
```
journalctl -u live-market-observer-trigger-eval.service -f
```

Watch shadow proposals for the new readiness state:
```
tail -F /mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/shadow_proposals.jsonl \
  | grep -E "READY_FOR_EVALUATION|readiness_evaluator"
```

Watch dedup state growth:
```
watch -n 60 'wc -l /mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/trigger_eval_state.json'
```

## 3. Monitoring + failure alerts (template)

### Operational metrics to track

| Metric | Source | Alert threshold |
|--------|--------|-----------------|
| CLI exit code 1 | `systemctl status live-market-observer-trigger-eval.service` | > 2 consecutive failures |
| Sweeps per hour | `journalctl -u … --since '1 hour ago'  | grep -c 'sweep done'` | < 10 per hour during UK trading window |
| FIRE count per day | grep `FIRE` in sweep logs | more than 20/day = unusual (investigate) |
| Lock timeout | grep `could not acquire` in sweep logs | > 1/day = investigate concurrent writer collision |
| Average sweep time | self-report from journal | > 30 s |

### Suggested alertmanager rule (template)

```
groups:
  - name: scenario_v2_trigger_evaluator
    rules:
      - alert: TriggerEvaluatorFailing
        expr: rate(systemd_unit_failed_total{name="live-market-observer-trigger-eval.service"}[15m]) > 2
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: Trigger evaluator failing repeatedly
          description: The P3 trigger evaluator has failed > 2 times in the past 15 minutes.

      - alert: TriggerEvaluatorSilent
        expr: time() - trigger_evaluator_last_sweep_timestamp > 1800
        for: 30m
        labels: { severity: warning }
        annotations:
          summary: Trigger evaluator has not swept in 30+ minutes during UK trading window
```

(Note: `trigger_evaluator_last_sweep_timestamp` metric is NOT
exposed by the current implementation — would need a Prometheus
exporter wrapper.)

## 4. Rollback instructions

### Disable timer (immediate)

```
sudo systemctl disable --now live-market-observer-trigger-eval.timer
```

The timer stops firing immediately.  No in-flight sweep can start
after this.  An already-running sweep completes normally (writes
its proposals + state) and exits.

### Remove systemd units

```
sudo rm /etc/systemd/system/live-market-observer-trigger-eval.service
sudo rm /etc/systemd/system/live-market-observer-trigger-eval.timer
sudo systemctl daemon-reload
```

### Remove evaluator module (optional — safe to leave in place)

```
sudo rm -rf /mnt/volume_lon1_1778405456698/research/live_obs/trigger_evaluator/
```

Leaving the module in place is safe because without the timer,
nothing invokes `cli_sweep`.  P1 and P2 remain unaffected.

### Journal cleanup (optional)

Proposals written by P3 can be identified in
`shadow_proposals.jsonl` by:
* `proposal_id.startswith("triggered-")`
* `readiness == "READY_FOR_EVALUATION"`
* `entry.provenance == "trigger_evaluator deterministic match"`

They can be grep-filtered out if the operator wants to purge them
from downstream analysis.  Alternatively, leave them in — journals
are append-only by design.

### State file cleanup

```
sudo rm /mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/trigger_eval_state.json
```

Only needed if the module is uninstalled.  Harmless to leave.

## 5. Pre-deploy checklist for the operator

Before `systemctl enable --now`:

- [ ] P1 and P2 deployed (verified via `/mnt/.../agent/*.py` SHA256).
- [ ] At least one scenario revision with `category` field present
      has been observed in `scenarios_shadow.jsonl` (confirms AI is
      emitting the new schema).
- [ ] At least one scenario revision with `trigger_spec` field
      present has been observed (confirms AI is emitting
      machine-readable triggers for A/B categories).
- [ ] Dashboard CSS updated for `readiness=READY_FOR_EVALUATION`
      state (optional cosmetic).
- [ ] 24 h of post-P1-P2 production has elapsed with no new regressions.
- [ ] Operator reviews:
      - `P1_P2_DEPLOYMENT_REPORT.md`
      - `P3_INTEGRATION_COMPLETION_REPORT.md`
      - `P3_REGRESSION_RESULTS.md`
      - this document

## 6. Known limitations at deploy time

* P3 relies on scenarios carrying `trigger_spec`.  Scenarios
  emitted BEFORE P2 was deployed will not fire via P3 (they lack
  `trigger_spec`).  This is CORRECT and SAFE — the evaluator only
  fires on scenarios that explicitly carry a machine-readable
  trigger.
* First few hours after P3 is enabled, FIRE count will be low until
  the AI accumulates scenarios with the new schema.
* The dashboard reads `shadow_proposals.jsonl` as-is; it may need
  a CSS entry for the new `readiness=READY_FOR_EVALUATION` value
  (cosmetic — not blocking).
* No live-trade capability introduced.  Even a FIRED proposal is
  shadow-only; the operator (or the autonomous trading agent) must
  make the trading decision.

## 7. Current state summary

| Component | State |
|-----------|-------|
| CLI entry (`cli_sweep.py`) | Written, tested with `--dry-run`, NOT installed to production |
| Trigger-spec consistency validator | In agent code, PART OF the P1+P2 deployment (via scenario_quality.py) |
| Cross-process dedup | In evaluator code; NOT YET invoked in production |
| systemd service + timer | Templates written, NOT installed |
| Timer schedule DST handling | Verified via `systemd-analyze calendar` |
| Monitoring hooks | Documented, NOT wired to Prometheus/alertmanager |
| Rollback | Documented; takes ~30 s to execute |
