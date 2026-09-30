"""level_telemetry — pure level-distance telemetry.

Extracted from gbpusd_bb_bounce.py:2172-2225 on 2026-07-24 so
gbpusd_structure_break.py can produce the same six level-distance fields
onto its signal_log rows. Observable-only; NEVER feeds entry logic, sizing,
SL/TP, or any gate.

Byte-identical contract: for the same inputs, compute_level_distance_fields
returns the same values (types, ordering, rounding) that the previous inline
block in gbpusd_bb_bounce.py wrote onto debug_dict. See
tests/unit/test_level_telemetry.py for the parity harness.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def compute_level_distance_fields(
    entry_price: Optional[float],
    distance_from_pdh_pips: Optional[float],
    distance_from_pdl_pips: Optional[float],
    threshold_pips: float,
) -> Dict[str, Any]:
    """Return the six level-distance fields.

    Inputs mirror what _ff_snap["swing_5m"] exposes:
      distance_from_pdh_pips: raw signed (close - pdh) / pip_size.
      distance_from_pdl_pips: raw signed (close - pdl) / pip_size.
    Either may be None when fewer than 287 5m bars are available.

    Round-number distances are derived from entry_price using the same
    mod-100 / mod-50 arithmetic as the original inline block; they feed the
    "nearest_level_type" pick but are NOT returned as separate output keys
    (signal_logger already stamps dist_to_00_pips / dist_to_0050_pips
    directly from entry_price via a strategy-agnostic path).
    """
    d00: Optional[float] = None
    d50: Optional[float] = None
    try:
        ep = float(entry_price)
        d00 = round(min(ep % 100.0, 100.0 - ep % 100.0), 2)
        d50 = round(min(ep % 50.0, 50.0 - ep % 50.0), 2)
    except (TypeError, ValueError):
        pass

    cands = []
    if distance_from_pdh_pips is not None:
        cands.append(("pdh", abs(float(distance_from_pdh_pips))))
    if distance_from_pdl_pips is not None:
        cands.append(("pdl", abs(float(distance_from_pdl_pips))))
    if d00 is not None:
        cands.append(("round_00", float(d00)))
    if d50 is not None:
        cands.append(("round_50", float(d50)))

    out: Dict[str, Any] = {
        "at_level_threshold_pips": float(threshold_pips),
        "dist_to_pdh_pips": (
            round(float(distance_from_pdh_pips), 2)
            if distance_from_pdh_pips is not None else None
        ),
        "dist_to_pdl_pips": (
            round(float(distance_from_pdl_pips), 2)
            if distance_from_pdl_pips is not None else None
        ),
    }
    if cands:
        cands.sort(key=lambda x: x[1])
        lvl_type, lvl_min = cands[0]
        out["dist_to_nearest_level_pips"] = round(lvl_min, 2)
        out["nearest_level_type"] = lvl_type
        out["at_level"] = bool(lvl_min <= float(threshold_pips))
    else:
        out["dist_to_nearest_level_pips"] = None
        out["nearest_level_type"] = None
        out["at_level"] = None
    return out
