# NMS A4 fix — structure demonstrates direction, indicators cannot veto

**Staging branch: `fix/nms-a4-trend-authoritative` @ `71b4d04`, based on production HEAD `5321065` (feat/trend-stretch-brake-adx-floor tip). Worktree: `/opt/tradingbot/.claude/worktrees/nms-a4-trend-fix`. No merge, no live restart, no broker action.**

Operator numbering "Wed 09-17 / Thu 09-18 / Fri 09-19" maps to the tape data at `data/candles/GBPUSD/2026-09-16.csv` (103p 92%-body trend down), `.../2026-09-17.csv` (MPC day, mixed trend down), `.../2026-09-18.csv` (up-drift, 60p range). This report cites both notations where useful.

---

## Step 1 — Strangle point located

**Both (b) and (c) are broken.** Trace against Wed 2026-09-16 10:00–12:00 UTC bars fed through the real NMS module (`scripts/nms_a4_trend_replay_20260919.py`):

### (a) Structure detector — OK

At Wed 09:30 UTC, `market_structure.detect_confirmed_swings` + `classify_structure` correctly produce `STRUCTURE_BEARISH` (LH+LL). NMS's `_derive_demonstrated_direction` returns `("DOWN", "structure_bearish:lh_ll", …)` — the demonstrated_direction field is set on 51 bars across the Wed session. The detector is not the bug.

### (b) NMS `_decide()` — A4 VIOLATION, `normal_market_state.py:518` (pre-fix)

```python
if chop_active:
    return FLAT_OR_COMPRESSED, ...
```

Fires unconditionally on `chop_shadow_active=True`, regardless of `demonstrated_direction`. Wed 09:30–11:05 UTC (before fix, `nms_a4_replay_before_fix_20260919.txt` lines ~53–75): 9 consecutive bars with `demo_dir=DOWN` labelled `FLAT_OR_COMPRESSED` because bb_w had squeezed to 5–7p:

```
2026-09-16T09:30   FLAT_OR_COMPRESSED   DOWN  flat_or_compressed:bb_w=5. lh_ll  bb_w=5.0p  er10=0.14  cross=3
2026-09-16T09:35   FLAT_OR_COMPRESSED   DOWN  flat_or_compressed:bb_w=5. lh_ll  bb_w=5.0p  er10=0.02  cross=3
2026-09-16T09:40   FLAT_OR_COMPRESSED   DOWN  flat_or_compressed:bb_w=4. lh_ll  bb_w=4.9p  er10=0.05  cross=3
...
2026-09-16T10:40   FLAT_OR_COMPRESSED   DOWN  flat_or_compressed:bb_w=6. lh_ll  bb_w=6.7p  er10=0.22  cross=2
```

A confirmatory indicator (chop_shadow — bb_w + midline slope both below thresholds) vetoed a structurally-demonstrated trend to a compression state. Per A4, this is forbidden.

**Whole-Wed breakdown (BEFORE, session 07–22 UTC).** Of 51 bars where structure demonstrated DOWN, NMS labelled:
- 15 bars `FLAT_OR_COMPRESSED` (A4 violation)
- 18 bars `PRODUCTIVE_RANGE` (A4 violation — range partition applied over a demonstrated trend)
- 18 bars `TRADABLE_NON_RANGE` (correct terminal state, but no `TREND_DOWN` in vocab)
- **0 bars `TREND_DOWN`** — that state did not exist

### (c) `guards/range_gate.evaluate()` — A4 VIOLATION, `guards/range_gate.py:290` (pre-fix)

```python
if wide_bands and low_er:
    rec["verdict"] = "SUPPRESS"
    ...
    return True, rec["reason"], rec
```

Direction-agnostic suppression: `bb_w>=15 AND ER<=0.35` → block, without ever consulting `normal_market_state.snapshot(symbol)['demonstrated_direction']`. Fri 2026-09-18 16:00–16:20 UTC (live `logs/range_gate.jsonl`):

```
16:00  TRADABLE_NON_RANGE  dir=UP  LONG  BLOCK  ranging bb_w=31.82p>=15.00p AND ER(10)=0.16<=0.35
16:05  TRADABLE_NON_RANGE  dir=UP  LONG  BLOCK  ranging bb_w=30.03p>=15.00p AND ER(10)=0.27<=0.35
16:10  TRADABLE_NON_RANGE  dir=UP  LONG  BLOCK  ranging bb_w=27.70p>=15.00p AND ER(10)=0.24<=0.35
16:15  TRADABLE_NON_RANGE  dir=UP  LONG  BLOCK  ranging bb_w=26.25p>=15.00p AND ER(10)=0.20<=0.35
16:20  TRADABLE_NON_RANGE  dir=UP  LONG  BLOCK  ranging bb_w=25.00p>=15.00p AND ER(10)=0.24<=0.35
```

Every one of those bars had `demonstrated_direction=UP` in NMS's `normal_state_journal.jsonl` (HH+HL from the confirmed-swing detector). Two of those blocked candidates are recorded in `logs/daily_journal.md` as `blocked_winner` — the LONG would have run +19.4p and +18.1p in 60m. A confirmatory bb_w+ER veto of a demonstrated direction. Forbidden by A4.

---

## Step 2 — Fix (smallest change honouring A4)

Commit `71b4d04` on `fix/nms-a4-trend-authoritative`. No new indicators, no new thresholds; veto removed at both points.

### `normal_market_state.py`

Added state constants:

```python
TREND_UP = "TREND_UP"
TREND_DOWN = "TREND_DOWN"

ALL_STATES = frozenset({
    UNKNOWN, PRODUCTIVE_RANGE, FLAT_OR_COMPRESSED, TRADABLE_NON_RANGE,
    TREND_UP, TREND_DOWN,
})
TREND_STATES = frozenset({TREND_UP, TREND_DOWN})
```

`_decide()` now takes `demo_dir` and short-circuits on structure BEFORE the feature partition:

```python
def _decide(self, feats, demo_dir=None):
    # A4 — structure is authoritative. HH+HL / LH+LL wins over
    # ER / BB / chop_shadow.
    if demo_dir == "UP":
        return TREND_UP, f"trend_up:structure_bullish ..."
    if demo_dir == "DOWN":
        return TREND_DOWN, f"trend_down:structure_bearish ..."
    ...  # existing 4-state partition unchanged
```

`classify()` computes hysteresis (`NMS_TREND_HYSTERESIS_ENABLED=1` by default): a resolved `TREND_UP`/`TREND_DOWN` holds for one bar of neutral structure; opposite-direction flips immediately.

```python
if (demo_dir is None
        and self._last_update is not None
        and self._last_update.state in TREND_STATES
        and int(_env_int("NMS_TREND_HYSTERESIS_ENABLED", 1)) == 1):
    if self._last_update.state == TREND_UP:
        effective_dir = "UP"
    elif self._last_update.state == TREND_DOWN:
        effective_dir = "DOWN"
    _held = effective_dir is not None
state, reason = self._decide(feats, effective_dir)
if _held:
    reason = f"hysteresis_hold:{reason}"
```

### `permission_matrix.py`

Two new rows admitting the same family set as `TRADABLE_NON_RANGE`:

```python
MatrixRow("NORMAL", "TREND_UP",
          _TRADABLE_NON_RANGE_ADMITTED, "NORMAL_TREND_UP",
          "NORMAL_STATE_NOT_PERMITTED:{family}"),
MatrixRow("NORMAL", "TREND_DOWN",
          _TRADABLE_NON_RANGE_ADMITTED, "NORMAL_TREND_DOWN",
          "NORMAL_STATE_NOT_PERMITTED:{family}"),
```

`requires_direction_alignment` extended:

```python
if ms in ("TRADABLE_NON_RANGE", "TREND_UP", "TREND_DOWN"):
    return fam in _A10_TRADABLE_NON_RANGE_FAMILIES
```

`ALL_MARKET_STATES` and `lookup()` allowed set extended similarly.

### `guards/range_gate.py`

Before returning SUPPRESS, consult NMS demonstrated direction. With-direction candidates admit (structure authoritative). Counter-direction still suppresses. `None` (no structure) preserves historic bb_w+ER behaviour so a genuinely-ranging tape still gets suppressed.

```python
_nms_dir = _read_nms_demonstrated_direction(symbol)
rec["nms_demonstrated_direction"] = _nms_dir
if _nms_dir is not None:
    _dir_up = str(direction).upper() in ("LONG", "BUY", "UP")
    _dir_dn = str(direction).upper() in ("SHORT", "SELL", "DOWN")
    if (_nms_dir == "UP" and _dir_up) or (_nms_dir == "DOWN" and _dir_dn):
        rec["verdict"] = "ALLOW"
        rec["reason"] = (
            f"structure_confirmed_with_direction "
            f"nms_dir={_nms_dir} candidate_dir={direction} "
            f"(A4: bb_w+ER may not veto structurally-demonstrated {_nms_dir})"
        )
        return False, "", rec
```

`_read_nms_demonstrated_direction` is a lazy `import normal_market_state` fail-safe wrapper: any exception (module unavailable, snapshot missing) returns None, dropping to historic bb_w+ER suppression.

---

## Step 3 — Proof on real specimens

Replay driver: `scripts/nms_a4_trend_replay_20260919.py` — reads `data/candles/GBPUSD/2026-09-{16,17,18}.csv`, feeds bars through the real NMS module and prints per-bar state + demonstrated_direction, then runs `guards/range_gate.evaluate()` on the Fri blocked-winner window with the same bars.

Full outputs saved to this repo:
- Before: [`nms_a4_replay_before_fix_20260919.txt`](nms_a4_replay_before_fix_20260919.txt)
- After: [`nms_a4_replay_after_fix_20260919.txt`](nms_a4_replay_after_fix_20260919.txt)

### Wed 2026-09-16 — 103p 92%-body trend down

**BEFORE** (session 07–22 UTC, 180 bars):

| Bars labelled | Count |
|---|---|
| FLAT_OR_COMPRESSED | 15 (all `demo_dir=DOWN` — A4 violation) |
| PRODUCTIVE_RANGE | 18 with `demo_dir=DOWN` (A4 violation) |
| TRADABLE_NON_RANGE | 18 with `demo_dir=DOWN` (terminal state, no direction encoding) |
| TREND_DOWN | 0 (state did not exist) |

Session flip count: **22**.

**AFTER** (session 07–22 UTC, 180 bars):

| Bars labelled | Count |
|---|---|
| TREND_DOWN | 108 |
| TREND_UP | 72 |
| Anything else | 0 |

Session flip count: **7**.

Wed's first LH+LL resolves to `TREND_DOWN` at 08:20 UTC and holds through the compression window 09:30–10:40 where the pre-fix code was returning FLAT_OR_COMPRESSED:

```
2026-09-16T09:30   TREND_DOWN   DOWN   trend_down:structure_bearish (er10=0.14,bb_w=5.0p,cross=3,chop_shadow=on)
2026-09-16T09:35   TREND_DOWN   DOWN   trend_down:structure_bearish (er10=0.02,bb_w=5.0p,cross=3,chop_shadow=on)
...
2026-09-16T10:40   TREND_DOWN   DOWN   trend_down:structure_bearish (er10=0.22,bb_w=6.7p,cross=2,chop_shadow=on)
```

Chop_shadow is stamped `on` in the reason — the operator can see the indicator was active but structure won, exactly as A4 mandates.

### Fri 2026-09-18 — up-drift, 60p range

**BEFORE** — 15 session flips. Range_gate on the 15:55–16:20 window: 5 of 6 bars BLOCK.

**AFTER** — 4 session flips. TREND_UP resolves at 15:20 UTC (first HH+HL after the morning trend-down leg) and holds through 18:25. Range_gate on the same window (unchanged bar data):

```
15:55  TREND_UP  UP  LONG  PASS   
16:00  TREND_UP  UP  LONG  PASS   
16:05  TREND_UP  UP  LONG  PASS   
16:10  TREND_UP  UP  LONG  PASS   
16:15  TREND_UP  UP  LONG  PASS   
16:20  TREND_UP  UP  LONG  PASS
```

All 6 pass with `verdict=ALLOW / reason=structure_confirmed_with_direction`. The two blocked_winners (16:10 → +19.4p, 16:15 → +18.1p) would have admitted.

---

## Step 4 — Hysteresis / regression / tests

### Flip-count comparison

| Day | Metric | Before | After | Δ |
|---|---|---:|---:|---:|
| Wed 09-16 | NMS session flips (07-22 UTC) | 22 | **7** | −68% |
| Fri 09-18 | NMS session flips (07-22 UTC) | 15 | **4** | −73% |

Flip reduction comes entirely from hysteresis (holding a resolved trend across one noisy bar). The state changes we retain are structurally justified — e.g. Wed's TREND_UP → TREND_DOWN flip at 08:20 UTC is the first genuine LH+LL, and Fri's TREND_DOWN → TREND_UP flip at 15:20 UTC is the point where the tape's counter-rally established fresh HH+HL after the morning down-leg.

### Tests

New: `tests/unit/test_nms_a4_trend_authoritative.py` (22 tests, all pass):

- `_decide(demo_dir=UP/DOWN)` → `TREND_UP`/`TREND_DOWN` even when `chop_shadow_active=True` + `bb_w<=5p`.
- `_decide(demo_dir=None)` regression: `FLAT_OR_COMPRESSED` / `PRODUCTIVE_RANGE` / `TRADABLE_NON_RANGE` outcomes unchanged.
- Hysteresis holds across a single neutral bar; opposite-direction flips immediately; `NMS_TREND_HYSTERESIS_ENABLED=0` disables.
- `permission_matrix.lookup(NORMAL, TREND_UP/DOWN)` admits `TREND_V3`/`EMA_PULLBACK`/`STRUCTURE_BREAK`/`CONFIRMATION_FALLBACK`; rejects `BB_BOUNCE`.
- `requires_direction_alignment` covers `TREND_UP`/`TREND_DOWN`.
- `range_gate`: with-direction passes under wide+low-ER when NMS has demonstrated direction; counter-direction still suppresses; `None` NMS preserves historic behaviour; tight bands stay `not_range`.

Existing suite regression: 202 pre-existing tests in the touched suites pass. 5 tests fail — all pre-existing on production (mid_news_search_emphasis mismatch — verified by running the same tests against the un-modified `/opt/tradingbot` tree). Unrelated to A4.

No existing test asserts the old FLAT_OR_COMPRESSED-on-trend behaviour. The tests that reference FLAT_OR_COMPRESSED stub NMS to that state and test downstream — none require it as a trend-day outcome.

---

## Wiring status

Per standing "wiring rule" — initializer + driver + consumer at file:line:

- **Initializer**: `autobot.py:8863` — `import normal_market_state as _nms_boot` + backfill at boot (unchanged; TREND_UP/DOWN emit through the same path).
- **Driver**: `autobot.py:3164` — 5m-close callback pushes bars via `_nms_bar.on_bar_close` (unchanged).
- **Consumers**:
  - `central_execution_gate.py:1435` — reads `_nms.snapshot(pair)['state']` for matrix routing; `TREND_UP`/`TREND_DOWN` flow through `permission_matrix.lookup` unchanged in shape (new rows admit the same families as `TRADABLE_NON_RANGE`).
  - `strategy_dispatch_adapter.py:220` — reads `_nms.snapshot(pair)` (unchanged).
  - `guards/range_gate.py:203` (after fix) — reads `_nms.snapshot(pair)['demonstrated_direction']` via `_read_nms_demonstrated_direction()`.
  - Journal: `logs/normal_state_journal.jsonl` (unchanged sink) — will now record `state=TREND_UP` / `state=TREND_DOWN` values.

No dead flags added. `NMS_TREND_HYSTERESIS_ENABLED` defaults to 1 (on) and is read at every classify; setting to 0 in `.env` disables hysteresis for operator diagnostics.

---

## Deployment note (operator action)

Staging is complete. To deploy, from the operator's controlled restart path:

1. Review the before/after replay outputs (linked above) and the diff on `fix/nms-a4-trend-authoritative`.
2. Merge or fast-forward `fix/nms-a4-trend-authoritative` into the deploy branch (operator-driven; standing rule prohibits me from merging).
3. `systemctl start autobot` (autobot.service is currently `inactive (dead)` since 2026-09-18 20:31:08 UTC per the previous 3-day report).

The fix is defensive at every consumer boundary — `_read_nms_demonstrated_direction` fails safe to `None`, and NMS itself keeps its "never raises" contract. If any downstream module hasn't been updated to know about `TREND_UP`/`TREND_DOWN`, `permission_matrix.lookup` will still return a valid row (with the same family set as `TRADABLE_NON_RANGE`) so admission continues to work.

---

**Files changed (commit `71b4d04`):**

```
 .gitignore                                    |   3 +
 guards/range_gate.py                          |  40 +++
 normal_market_state.py                        |  66 ++++-
 permission_matrix.py                          |  19 +-
 scripts/nms_a4_trend_replay_20260919.py       | 189 +++++++++++++
 tests/unit/test_nms_a4_trend_authoritative.py | 373 ++++++++++++++++++++++++++
 6 files changed, 680 insertions(+), 10 deletions(-)
```
