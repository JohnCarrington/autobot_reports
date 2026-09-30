# PIA_FIRST deployment checklist — AutoBot-PIA droplet

**Date:** 2026-05-13
**Target host:** AutoBot-PIA droplet (144.126.207.200)
**Spec source:** `/opt/tradingbot/docs/pia_style_new_bot_scope_2026-05-13.md`
**Implementation commit:** see `git log -1` after merging the PIA_FIRST feature branch.

This document is the operator-facing runbook for bringing up the PIA_FIRST briefing system on a fresh droplet. The system is **disabled by default on the existing AutoBot droplet** (`PIA_FIRST_ENABLED=0`); the procedure below flips it on for the new droplet only.

---

## 0. Pre-clone droplet provisioning checks

Before cloning the repo:

| Check | Command | Expected |
|---|---|---|
| OS | `cat /etc/os-release` | Ubuntu 22.04 LTS |
| autobot user exists | `id autobot` | `uid=1001(autobot) gid=1001(autobot)` |
| Python version | `python3 --version` | `>= 3.10` |
| Time sync | `timedatectl` | NTP active, UTC display |
| Disk free | `df -h /` | `> 5 GB` free |
| Firewall | `ufw status` | Allow SSH, deny everything else |

---

## 1. Clone + dependencies

```bash
sudo -u autobot bash <<'EOF'
cd /opt
git clone https://github.com/<your-org>/tradingbot.git
cd tradingbot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
EOF
```

Verify the producer + executor modules import cleanly:

```bash
sudo -u autobot bash -c 'cd /opt/tradingbot && \
  ./venv/bin/python -c "import pia_first_briefing, pia_first_executor; print(\"OK\")"'
```

---

## 2. `.env` modifications

Copy `.env.example` to `.env` then apply the PIA_FIRST overlay below.

### 2.1 Strategy flags (set these to 0)

Everything except PIA_FIRST should be off. Per `pia_style_new_bot_scope §11`:

```bash
# Disable v5_pia entirely
BRIEFING_V5_PARALLEL_MODE=0
BRIEFING_V5_ENABLED=0

# Disable v4 PIA executor
BRIEFING_EXECUTION_ENABLED=0

# Disable all other entry strategies
GBPUSD_TREND_ENABLED=0
GBPUSD_BB_BOUNCE_ENABLED=0
GBPUSD_BB_REVERSAL_PATTERNS_ENABLED=0
RSI_EXTREME_FADE_ENABLED=0
MACD_EXTREME_FADE_ENABLED=0
BB_PATTERN2_FADE_ENABLED=0
FIFTY_PIP_BREAKOUT_ENABLED=0
# Remaining strategies' ENABLED flags should already be 0 in .env.example.
```

### 2.2 PIA_FIRST flags (the new system)

```bash
PIA_FIRST_ENABLED=1
MIN_CONFIDENCE_PIA_FIRST=60
PIA_FIRST_SCHEDULE_UTC=05:30
PIA_FIRST_MODEL=claude-sonnet-4-6
PIA_FIRST_TEMPERATURE=0.3
PIA_FIRST_MAX_TOKENS=400
```

### 2.3 EOD close (already on; explicit for clarity)

```bash
BRIEFING_EXEC_EOD_CLOSE_ENABLED=1
BRIEFING_EXEC_EOD_CLOSE_UTC=21:00
```

### 2.4 REST allowance split

Per memory `project_unpushed_local_state_audit.md` — the old + new droplet share an IG REST allowance window. Halve the budget on the new droplet:

```bash
REST_WEEKLY_BUDGET=4000
```

### 2.5 IG + Anthropic + Telegram keep-list

These must be set; verify before launching:

```bash
IG_ACC_TYPE=DEMO
IG_USERNAME=...
IG_PASSWORD=...
IG_API_KEY=...
IG_ACCOUNT_ID=...
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...        # per-droplet chat id is preferred — tags
                            # which droplet a fire came from.
ANTHROPIC_API_KEY=...
EPICS_JSON='{"GBPUSD":"CS.D.GBPUSD.TODAY.IP", ...}'
CFD_EPICS_JSON='{"GBPUSD":"CS.D.GBPUSD.CFD.IP", ...}'
BRIEFING_SCHEDULER_ENABLED=1
TRADE_SIZE=1.0
```

### 2.6 Permissions

```bash
chmod 600 /opt/tradingbot/.env
chown autobot:autobot /opt/tradingbot/.env
```

---

## 3. Cache pre-population (cherry-pick from current droplet)

Per `pia_style_new_bot_scope §12`, cherry-pick the warm caches. Without these, the producer can fire on day 1 only if there are enough D1/H1 bars accumulated — cherry-picking saves a full day of warmup.

From the old droplet (AutoBot, current), run:

```bash
rsync -avz --rsync-path="sudo -u autobot rsync" \
  /opt/tradingbot/cache/htf/ \
  autobot@144.126.207.200:/opt/tradingbot/cache/htf/

rsync -avz --rsync-path="sudo -u autobot rsync" \
  /opt/tradingbot/cache/*_candles*.csv \
  autobot@144.126.207.200:/opt/tradingbot/cache/
```

Then on the new droplet, verify mtimes:

```bash
ls -la /opt/tradingbot/cache/htf/ | grep -E '_(D1|H1)\.json'
stat /opt/tradingbot/cache/GBPUSD_candles.csv
```

Per memory `project_d1_cache_staleness_silent_neutral.md`, a D1 cache > 48h old silently leads to a NEUTRAL bias. The producer surfaces `current_price_at_gen` in every briefing JSON — anomalies show up there.

---

## 4. Memory cherry-pick

Per `pia_style_new_bot_scope §12.4`. KEEP these on AutoBot-PIA:

- `user_timezone.md`
- `reference_deployment.md`
- `project_briefing_max_tokens_eurusd.md`
- `project_briefing_schedule_consolidation.md`
- `project_histdata_cert_expired.md`
- `project_d1_cache_extension_deferred.md`
- `project_d1_cache_staleness_silent_neutral.md`
- `feedback_run_as_autobot_not_root.md`
- `feedback_no_co_authored_by.md`
- `feedback_phase4_estimate_padding.md`

DROP (irrelevant on the PIA-only droplet):

- `feedback_bias_flipflop.md`        (v4 bias logic; v4 disabled)
- `project_sentinel_memory_fix.md`   (different droplet)
- `project_bb_reversal_d3y.md`       (strategy disabled)
- `project_news_tick_tight_tp_guard.md`
- `project_regime_classifier_*` files (Phase 4 not running)
- `project_signal_log_dispatcher_gap.md`
- `project_bb_pierce_run_*` files
- `project_ema_pullback_deferred_redesign.md`
- `project_forensic_infra_live.md`   (still applies but secondary)
- `project_bb_pierce_run_macd_gate_live.md`
- `project_3co_h1_ema_stack_gate_live.md`
- `project_v5_pia_*` files            (v5 disabled)
- `project_phase4_strategy_threading_for_may23.md`

ADD (new memory for the PIA-only droplet):

- `project_pia_first_deployed.md` — record deploy date, env flag values, first useful output day.

---

## 5. systemd setup

The autobot.service unit file already lives in the repo. Install it:

```bash
sudo cp /opt/tradingbot/autobot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autobot.service
```

Verify the unit runs as `User=autobot` (per memory `feedback_run_as_autobot_not_root.md`):

```bash
grep User= /etc/systemd/system/autobot.service
# Expected: User=autobot
```

Start the service:

```bash
sudo systemctl start autobot.service
sudo systemctl status autobot.service
```

---

## 6. First-run verification (11 steps)

After boot, run through each check. **Do NOT trade live until all 11 pass.**

### 6.1 Service status

```bash
sudo systemctl is-active autobot.service
# Expected: active
```

### 6.2 Log shows PIA_FIRST scheduler hook fired (or "disabled by env flag")

```bash
journalctl -u autobot.service -n 200 | grep -i "pia_first"
# Expected: [pia_first] session start date=... pairs=... model=...
# OR: [pia_first] disabled by env flag (means PIA_FIRST_ENABLED=0 — fix .env)
```

### 6.3 Anthropic API key reachable

```bash
journalctl -u autobot.service | grep -E "anthropic.*(error|HTTP)"
# Expected: empty (no errors)
```

### 6.4 Today's briefing files exist for all 4 pairs

```bash
DATE=$(date -u +%F)
ls -la /opt/tradingbot/briefings/pia_first/$DATE/
# Expected: GBPUSD.json EURUSD.json USDJPY.json USDCAD.json
# Any *_INVALID.json files = LLM produced unparseable / off-spec output;
# inspect, then send a Telegram poke if it recurs across days.
```

### 6.5 JSONL daily log appended

```bash
tail -n 1 /opt/tradingbot/logs/pia_first_briefing.jsonl | python3 -m json.tool
```

### 6.6 Telegram summary received

Operator visually checks the Telegram chat for the `🧠 PIA_FIRST briefing` summary at ~05:31 UTC.

### 6.7 Executor fires on first usable tick (if any conf ≥ 60)

```bash
journalctl -u autobot.service | grep -E "pia_first_exec.*FIRE"
# Expected (if any pair was conf >= 60): [pia_first_exec] GBPUSD FIRE BUY ...
# Empty if all 4 pairs were conf < 60 — fine; producer will retry tomorrow.
```

### 6.8 Forensic snapshot written

```bash
grep -c '"strategy":"BRIEFING_PIA_FIRST' /opt/tradingbot/logs/forensic_fires.jsonl
# Expected: one record per fire from 6.7
```

### 6.9 Signal log records the mode tag

```bash
grep -c "BRIEFING_PIA_FIRST_" /opt/tradingbot/logs/signal_log.csv
# Expected: matches 6.7 count
```

### 6.10 EOD close picks up PIA_FIRST positions at 21:00 UTC

Set a calendar reminder to check at 21:01 UTC:

```bash
journalctl -u autobot.service --since "21:00 UTC" \
  | grep -E "EOD-CLOSE.*BRIEFING_PIA_FIRST"
# Expected: one line per open PIA_FIRST position closed.
```

### 6.11 Open positions count matches expected

```bash
journalctl -u autobot.service --since "21:02 UTC" | grep "active=0"
# OR via the bot's internal state dump if available.
```

---

## 7. Smoke test (offline)

Run the test suite before flipping `PIA_FIRST_ENABLED` to 1:

```bash
sudo -u autobot /opt/tradingbot/venv/bin/python -m pytest \
  tests/unit/test_pia_first_briefing.py \
  tests/unit/test_pia_first_executor.py \
  tests/integration/test_pia_first_e2e.py \
  -q
# Expected: 40 passed
```

---

## 8. Rollback procedure

If anything looks wrong:

1. `sudo systemctl stop autobot.service`
2. Edit `.env`: `PIA_FIRST_ENABLED=0`
3. `sudo systemctl start autobot.service`
4. Verify in journalctl: `[pia_first] disabled by env flag`

The system is fully inert when the flag is 0 — no LLM calls, no fires, no scheduler dispatch.

---

## 9. Observability hooks

| Concern | Where to look |
|---|---|
| Did the LLM call succeed? | `journalctl ... \| grep "pia_first.*LLM"` |
| Did validation pass? | `journalctl ... \| grep "pia_first.*validation"` |
| Did the executor fire? | `journalctl ... \| grep "pia_first_exec.*FIRE"` |
| Did the broker accept? | `journalctl ... \| grep "execute_trade.*BRIEFING_PIA_FIRST"` |
| What's the day-by-day record? | `/opt/tradingbot/logs/pia_first_briefing.jsonl` |
| Per-pair plan today? | `/opt/tradingbot/briefings/pia_first/$(date -u +%F)/<PAIR>.json` |
| EOD close fired? | `journalctl ... \| grep "BRIEFING-EXEC.*EOD-CLOSE.*PIA_FIRST"` |

---

## 10. First-week review cadence

Per `pia_style_new_bot_scope §14.5`: at end of week 1, review:

- 4 pairs × 5 trading days = 20 plans expected.
- How many fired (conf ≥ 60)? How many won?
- Confidence calibration: did conf=80 setups actually win more than conf=65?
- Telegram cadence sane?
- LLM consistency: did the same pair flip direction day-to-day without underlying structure change?

Adjust the system prompt at the start of week 2 if needed — NOT during week 1.

---

## 11. Cost monitoring

Per `pia_style_new_bot_scope §3.2`:

- Per call: ~$0.022 (Sonnet 4.6)
- Per day: ~$0.087 (4 pairs × 1 session)
- Per month: ~$1.92 (22 trading days)

Anthropic console dashboard should show `~120-130 calls/month` from this droplet's key. If it shows materially more, something is retrying that shouldn't (the producer has no retry logic; a runaway scheduler loop would be the suspect — check `journalctl ... \| grep "Firing London PIA_FIRST briefing"` and confirm exactly one per day).
