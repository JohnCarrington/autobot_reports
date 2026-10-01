# Briefing JSON schema (v5_pia)

Every file in `samples/` conforms to the pydantic model in `../code/briefing/v5_pia/schema.py` (`BriefingV5`).

## Top-level fields (field order matches on-disk JSON)

| Field                       | Type                                      | Notes |
|-----------------------------|-------------------------------------------|-------|
| `schema_version`            | `str` — must equal `"v5_pia"`             | Field validator enforces |
| `pair`                      | `str` — e.g. `"EURUSD"`                   | |
| `session`                   | `"London" \| "NY"`                        | |
| `generated_at_utc`          | ISO-8601 UTC string, suffix `Z`           | Producer write time |
| `valid_until_utc`           | ISO-8601 UTC string, suffix `Z`           | Executor-honored expiry |
| `direction`                 | `"BUY" \| "SELL" \| "STAND_ASIDE"`        | |
| `state`                     | `"GENERATED" \| "ARMED" \| "STAND_ASIDE" \| "FIRED" \| "CLOSED"` | At write time |
| `confidence`                | `int` in `[0, 100]`                       | |
| `confidence_bucket`         | `"STAND_ASIDE" \| "WATCH" \| "ARMED" \| "HIGH_CONVICTION"` | Must be consistent with `confidence` |
| `confidence_breakdown`      | `dict` — scorer internals                 | Shape owned by scorer, not schema |
| `bias_anchor`               | `float \| None`                           | Scaled-pip price (see pip_conventions.md) |
| `bias_anchor_label`         | `str \| None`                             | |
| `entry`                     | `float \| None`                           | Scaled-pip price |
| `stop`                      | `float \| None`                           | Scaled-pip price |
| `target`                    | `float \| None`                           | Scaled-pip price |
| `rr`                        | `float >= 0`                              | Reward:risk ratio |
| `stop_structural_level`     | `str \| None`                             | Label of the level anchoring the stop |
| `target_structural_level`   | `str \| None`                             | Label of the level anchoring the target |
| `support_levels`            | `list[float]`                             | Scaled-pip prices |
| `resistance_levels`         | `list[float]`                             | Scaled-pip prices |
| `rationale`                 | `str \| None`                             | LLM-written where Phase-2 is enabled, else null |
| `stand_aside_reason`        | `str \| None`                             | e.g. `"data_unavailable"`, `"below_min_confidence"` |
| `news_in_window`            | `bool`                                    | Any high-impact news in valid window |
| `news_event`                | `dict \| None`                            | Event metadata if `news_in_window` is True |
| `execution`                 | `dict`                                    | Default: `{"min_confidence_to_arm": 70, "executed": False, "executed_at_utc": None, "deal_id": None, "outcome": None}` |

## Confidence bucket boundaries

```
STAND_ASIDE:      0 ≤ confidence < 50
WATCH:           50 ≤ confidence < 70
ARMED:           70 ≤ confidence < 85
HIGH_CONVICTION: 85 ≤ confidence ≤ 100
```

The pydantic model enforces consistency between `confidence` and `confidence_bucket` with a `model_validator(mode="after")`. Attempting to construct a `BriefingV5(confidence=60, confidence_bucket="ARMED")` raises `ValueError`.

## Price scale

All prices are in IG scaled-pip units — same as the candle CSVs. See `../docs/pip_conventions.md` for the per-pair scale factor.

## STAND_ASIDE semantics

When `direction == "STAND_ASIDE"`:
- `state == "STAND_ASIDE"`.
- `entry`, `stop`, `target` are all `None`.
- `rr == 0`.
- `stand_aside_reason` is populated. Common values:
  - `"data_unavailable"` — producer could not assemble a full data package (candles missing, etc.)
  - `"below_min_confidence"` — scored but didn't clear the ARMED threshold.
  - `"news_blackout"` — a high-impact release prevents arming.

## Validation on host 46

Run `python3 code/validate_briefing.py --date 2026-07-01 --dry-run` from the package root to see the shipped validator in action (it reads from `/opt/tradingbot/briefings/v5_pia/` so it will not find these samples unless you symlink or override; the file is shipped as a reference, not for in-package validation).

Programmatic validation:
```python
from briefing.v5_pia.schema import BriefingV5
import json, pathlib
for p in pathlib.Path("briefings/samples").rglob("*.json"):
    BriefingV5(**json.loads(p.read_text()))  # raises on malformed
```
