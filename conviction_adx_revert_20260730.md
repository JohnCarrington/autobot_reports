# CONVICTION_ADX_MIN revert 25 → 0 (pre-crisis baseline)

**Host:** 161 (as `autobot`, not root)
**Date:** 2026-07-30
**Change kind:** `.env` edit only. **No restart.** Effect applies at next `systemctl restart autobot`.
**Scope:** one line (`.env:536` value) + the stale rationale comment block above it. Cascade gate and all other gates untouched — one change so we can attribute any observed lift.

---

## 1. Before / after diff

**Before** (verbatim, `.env:530-536`):
```
# --- 2026-07-24: BB_BOUNCE restore, option A ---
# ADX floor neutralised pending evidence. Gate's H1-ADX check blocked all
# three armed setups today (15.4/16.5/19.4 vs 20.0). Wednesday's fires
# partly passed via the ADX=None fail-open, so 20.0 was never
# consistently enforced. Threshold to be re-set from fill data once
# bb_h1 telemetry accumulates.
CONVICTION_ADX_MIN=25
```

**After** (verbatim, `.env:530-537`):
```
# --- 2026-07-30: revert to pre-crisis baseline (was 0 up to 07-27T23:17,
# flipped 0→25 on 07-27/28 boundary, blocked estate-wide since). Live-blocked
# BB_BOUNCE_S 08:40 UTC (ADX=21.03) and EMA_PULLBACK_L 09:05 UTC (ADX=24.63)
# on 07-30; GBPUSD ADX runs under 25 for 40–70% of sessions, so an ADX floor
# on fade paths (BB_BOUNCE, BB_REV_PAT, EMA_PULLBACK) is inverted — high ADX
# is when NOT to fade. Value 0 makes _gate_adx (conviction_gate.py:233)
# pass trivially since real ADX ≥ 0 always satisfies adx_f >= 0.
CONVICTION_ADX_MIN=0
```

Single-key check:
```
$ command -p grep -cE '^CONVICTION_ADX_MIN=' /opt/tradingbot/.env
1
$ command -p grep -nE '^CONVICTION_ADX_MIN' /opt/tradingbot/.env
537:CONVICTION_ADX_MIN=0
```
One line. No duplicate.

---

## 2. env-history proof of the 07-27/28 flip

The `.env` snapshots in `/opt/tradingbot/env-history/` show the exact boundary. Each systemd restart snapshots the pre-boot `.env`; the pair straddling the flip:

```
$ command -p grep -aE 'CONVICTION_ADX_MIN' /opt/tradingbot/env-history/env.20260727T231719Z
CONVICTION_ADX_MIN=0

$ command -p grep -aE 'CONVICTION_ADX_MIN' /opt/tradingbot/env-history/env.20260728T101922Z
CONVICTION_ADX_MIN=25

$ command -p diff /opt/tradingbot/env-history/env.20260727T231719Z /opt/tradingbot/env-history/env.20260728T101922Z | command -p grep -B1 -A1 CONVICTION_ADX_MIN
534c534
< CONVICTION_ADX_MIN=0
---
> CONVICTION_ADX_MIN=25
```

`env.20260727T231719Z` (2026-07-27 23:17:19 UTC) is the **last** snapshot with `=0`.
`env.20260728T101922Z` (2026-07-28 10:19:22 UTC) is the **first** with `=25`.
And all snapshots since (`20260728T211300Z`, `20260728T233933Z`, `20260729T075417Z`, `20260729T155000Z`, `20260730T074817Z`, `20260730T083407Z`) carry `=25`. The flip crossed the 07-27/28 boundary as stated.

Revert lands the value back at its **pre-crisis** baseline of `0`.

---

## 3. What `CONVICTION_ADX_MIN=0` does in code

Verbatim `conviction_gate.py:221-236`:
```python
def _gate_adx(regime: dict) -> Tuple[bool, str, dict]:
    enabled = _env_bool("CONVICTION_ADX_GATE_ENABLED", "1")
    threshold = _env_float("CONVICTION_ADX_MIN", 20.0)
    if not enabled:
        return True, "ADX_gate_disabled", {"enabled": False}
    adx = regime.get("ADX")
    if adx is None:
        return True, "ADX_unavailable_fail_open", {"adx": None, "threshold": threshold}
    try:
        adx_f = float(adx)
    except (TypeError, ValueError):
        return True, "ADX_unparseable_fail_open", {"adx": adx, "threshold": threshold}
    passed = adx_f >= threshold
    return passed, ("ADX_pass" if passed else f"ADX_below_threshold:{adx_f:.1f}<{threshold:.1f}"), {
        "adx": adx_f, "threshold": threshold,
    }
```

The decisive line is 233: `passed = adx_f >= threshold`.

**With `threshold=0.0`:** every real ADX value is ≥ 0 by definition (ADX is a magnitude), so `passed = True` on every evaluation. The verdict emitted is `ADX_pass`, keeping the telemetry line intact for post-hoc analysis. Edge cases:

| Regime.ADX input | Verdict with threshold=0 | Note |
|------------------|--------------------------|------|
| Any positive float | `passed=True, ADX_pass` | Whole intended domain |
| Exactly 0.0        | `passed=True, ADX_pass` | `0.0 >= 0.0` |
| `None`             | `passed=True, ADX_unavailable_fail_open` | Pre-existing fail-open (line 227-228) — unchanged |
| Unparseable        | `passed=True, ADX_unparseable_fail_open` | Pre-existing fail-open (line 231-232) — unchanged |

**`0` fully neutralises the gate.** No need to also flip `CONVICTION_ADX_GATE_ENABLED=0` — that path (line 224) exits with `ADX_gate_disabled` and would drop the ADX telemetry entirely. Keeping the gate enabled + threshold 0 preserves the `ADX_pass` log line so we can still see ADX at each fire and re-tune later if telemetry warrants.

Alternative equivalents (not used): `CONVICTION_ADX_GATE_ENABLED=0` (disables gate outright but loses telemetry); leaving 25 in place would obviously not fix the block.

---

## 4. Which strategies pass through this shared conviction path

`conviction_gate.evaluate()` is invoked exactly once, in `trade_executor.py:1331-1345`:

```python
if not _REGIME_MATRIX_ENABLED_TE:
    try:
        import conviction_gate as _cg
        …
        _ok, _reason, _details = _cg.evaluate(_sym_cg, _dir_cg, mode)
        if not _ok:
            logger.info("[CONVICTION] BLOCKED %s %s %s — %s", …)
            _set_block_info("CONVICTION_GATE", str(_reason))
            return None
```

The regime-matrix flag (`_REGIME_MATRIX_ENABLED_TE`) is not set in this deployment, so the gate runs for every call to `execute_trade`. `execute_trade(decision, epic)` is defined at `trade_executor.py:1192` and is the **single execution entry point** for the estate. Every strategy dispatcher in `autobot.py` funnels into it — 23 `execute_trade(` call sites across autobot.py, one per strategy dispatch. Mapping the strategy-tagged locals to their strategies:

| autobot.py line | Local        | Strategy                                    |
|-----------------|--------------|---------------------------------------------|
| 3192            | `_nt_dec`    | NEWS-TICK                                   |
| 3422            | `_ns_dec`    | NEWS strategy                               |
| 3558            | `_fpb_dec`   | FIFTY_PIP_BREAKOUT                          |
| 3820            | `_rev_l_dec` | GBPUSD_BB_REV_L                             |
| 3845            | `_big_dec`   | GBPUSD_BIG_REV                              |
| 3945            | `_gt_dec`    | GBPUSD_TREND                                |
| 4071            | `_ov_dec`    | GBPUSD_OVERNIGHT_LEVEL_SWEEP                |
| 4129            | `_pm_dec`    | GBPUSD_BB_PREMIRROR                         |
| 4180            | `_ny_dec`    | GBPUSD_NY_CONTINUATION                      |
| 4323            | `_bbb_dec`   | **GBPUSD_BB_BOUNCE** (blocked 08:40 today)  |
| 4545            | `_brp_dec`   | GBPUSD_BB_REV_PAT                           |
| 4693            | `_ep_dec`    | **GBPUSD_EMA_PULLBACK** (blocked 09:05 today) |
| 4849            | `_sb_dec`    | STRUCTURE_BREAK                             |
| 4975            | `_r_dec`     | GBPUSD_RAW_REVERSAL                         |
| 5054            | `_rr_dec`    | RSI_FADE                                    |
| 5134            | `_cf_dec`    | CONFIRMATION_FALLBACK                       |
| 5177            | `decision`   | briefing execution (v5)                     |
| 5437 / 5619 / 5896 / 6096 / 6283 / 6478 | (secondary dispatch paths) | SB / BB_BOUNCE / EMA_PULLBACK / BB_REV_PAT / CONFIRMATION / regime router |

**Every strategy the bot runs** goes through this gate. Setting `CONVICTION_ADX_MIN=0` removes the ADX-floor block from **all** of them simultaneously — that is exactly the intent: the same knob that blocked BB_BOUNCE_S at 08:40 and EMA_PULLBACK_L at 09:05 today would also block STRUCTURE_BREAK, RSI_FADE, NEWS, BB_REV_PAT, etc. whenever ADX < 25 at their fire moment. All unblocked in one turn.

Note: STRUCTURE_BREAK also carries a **second, independent** ADX≥25 floor inside its own code (`gbpusd_structure_break.py:192`, `STRUCTURE_BREAK_ADX_MIN=25.0` default) that is *not* touched by this change. That was noted in the prior report; it is out of scope here per "do NOT touch anything else."

---

## 5. In-process import verification

Loaded the new `.env` into a clean subprocess (matching how systemd will load it at next restart) and exercised `_gate_adx` on today's live-blocked ADX values:

```
$ env -i PATH=/usr/bin:/bin HOME=$HOME /opt/tradingbot/venv/bin/python -c "
import os
from pathlib import Path
for raw in Path('/opt/tradingbot/.env').open():
    s = raw.strip()
    if not s or s.startswith('#'): continue
    if s.startswith('export '): s = s[len('export '):]
    if '=' not in s: continue
    k, _, v = s.partition('=')
    if v and v[0] in ('\"',\"'\") and v[-1]==v[0]: v = v[1:-1]
    os.environ[k.strip()] = v
print('env-loaded CONVICTION_ADX_MIN =', repr(os.environ.get('CONVICTION_ADX_MIN')))

import conviction_gate as cg
threshold = cg._env_float('CONVICTION_ADX_MIN', 20.0)
enabled  = cg._env_bool('CONVICTION_ADX_GATE_ENABLED', '1')
print(f'gate reads: threshold={threshold!r}  enabled={enabled!r}')

for adx in (21.03, 24.63, 0.0):
    ok, reason, det = cg._gate_adx({'ADX': adx})
    print(f'  ADX={adx:>5}  -> passed={ok}  reason={reason}  detail={det}')

ok, reason, det = cg._gate_adx({'ADX': None})
print(f'  ADX=None  -> passed={ok}  reason={reason}')
"
```

Output:
```
env-loaded CONVICTION_ADX_MIN = '0'
gate reads: threshold=0.0  enabled=True
  ADX=21.03  -> passed=True  reason=ADX_pass  detail={'adx': 21.03, 'threshold': 0.0}
  ADX=24.63  -> passed=True  reason=ADX_pass  detail={'adx': 24.63, 'threshold': 0.0}
  ADX=  0.0  -> passed=True  reason=ADX_pass  detail={'adx': 0.0, 'threshold': 0.0}
  ADX=None  -> passed=True  reason=ADX_unavailable_fail_open
```

All confirmations:
- The new `.env` parses to `CONVICTION_ADX_MIN='0'`.
- `_env_float` reads it as `0.0`.
- `_env_bool` for `CONVICTION_ADX_GATE_ENABLED` reads default `True` — the gate remains enabled; `threshold=0.0` is what neutralises it. Telemetry line still emitted as `ADX_pass`.
- Today's two live-blocked ADX values (21.03 for BB_BOUNCE_S 08:40; 24.63 for EMA_PULLBACK_L 09:05) now both return `passed=True, ADX_pass`. Same fires under the new value would go through, not be gated.
- Edge cases (`ADX=0.0` and `ADX=None`) also pass, matching pre-crisis baseline behaviour.

---

## 6. Live PID unchanged — matches "no restart" spec

The running process was started before the edit and captured the old value at boot:
```
$ pgrep -f 'venv/bin/python /opt/tradingbot/autobot.py' | head -1
2887975

$ cat /proc/2887975/environ | tr '\0' '\n' | command -p grep -E '^CONVICTION_ADX_MIN='
CONVICTION_ADX_MIN=25
```

The live PID **still sees 25** and will continue to block on ADX < 25 until the next systemd restart. The `.env` change is staged, not applied — matches the "LIVE, no restart (effect next restart)" instruction. Any restart from here forward (planned or otherwise) will pick up `0`.

---

## 7. What was *not* touched

Per the instruction "do NOT touch the cascade gate or anything else — one change":

- `bb_pierce_run.py` cascade gate — unchanged. Still blocks LONG on `cascade=TREND_DOWN` and SHORT on `cascade=TREND_UP`. (2 of 3 BB_BOUNCE fire candidates today died here; that remains the case after this revert.)
- `gbpusd_structure_break.py:192` STRUCTURE_BREAK_ADX_MIN=25.0 default — unchanged (env not set).
- `CONVICTION_ADX_GATE_ENABLED` — unchanged (default `1`, i.e., gate stays enabled → still emits `ADX_pass` telemetry per fire).
- `CONVICTION_DI_GATE_ENABLED`, `CONVICTION_CONF_GATE_ENABLED`, `REVERSAL_TREND_GUARD_*` — untouched. All remain at their prior defaults / env states.
- HTF_AUTHORITY, CROSS_BIAS_GATE, FXI_LEVEL_VETO, GBPUSD_BB_NEARTOUCH, LEVELS_PROXIMITY, NEWS_BLACKOUT, PRICED_IN, RACE_CAUGHT, DUPLICATE_ACTIVE — unchanged.

One dial moved. If, after restart, BB_BOUNCE / EMA_PULLBACK / etc. start opening again on ADX-below-25 sessions, the attribution is unambiguous.

---

## 8. Expected effect after next restart

At next `systemctl restart autobot`:
- Systemd re-parses `.env`; the new PID inherits `CONVICTION_ADX_MIN=0`.
- Every strategy that reaches `trade_executor.execute_trade` continues to be evaluated by `conviction_gate.evaluate` — but the ADX sub-gate now returns `ADX_pass` for every non-`None` ADX value.
- BB_BOUNCE fires that survive CASCADE_GATE will no longer be killed by CONVICTION-ADX. Same for EMA_PULLBACK, BB_REV_PAT, STRUCTURE_BREAK (only its own local ADX≥25 floor remains, which is a separate concern), RSI_FADE, NEWS, etc.
- The other sub-gates in `conviction_gate` (`reversal_trend_guard`, `_gate_di_alignment`, `_gate_confidence`) still run and can still block on their own criteria — but per today's telemetry all of those were passing anyway (`flag_enabled=False`, `DI_gate_disabled`, `conf_gate_disabled`).

If fires still fail to convert to opens after restart, the culprit is *not* this gate — CASCADE_GATE, STRUCTURE_BREAK_ADX_MIN, or something further downstream would be next to look at.

---

## 9. References

- `/opt/tradingbot/.env:530-537` — the change.
- `/opt/tradingbot/env-history/env.20260727T231719Z` (last `=0`), `env.20260728T101922Z` (first `=25`) — the flip proof.
- `/opt/tradingbot/conviction_gate.py:221-236` — `_gate_adx`.
- `/opt/tradingbot/trade_executor.py:1192, 1329-1345` — `execute_trade` + conviction invocation (single choke point for all strategies).
- `/opt/tradingbot/autobot.py:3192, 3422, 3558, 3820, 3845, 3945, 4071, 4129, 4180, 4323, 4545, 4693, 4849, 4975, 5054, 5134, 5177, …` — the 23 `execute_trade(` call sites.
- `/proc/2887975/environ` — live PID still on `25` (no-restart confirmation).
