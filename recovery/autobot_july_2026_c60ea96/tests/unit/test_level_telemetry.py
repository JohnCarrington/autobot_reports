"""Parity tests for level_telemetry.compute_level_distance_fields.

Locks the byte-identical guarantee against the inline block previously in
gbpusd_bb_bounce.py:2172-2225 (removed 2026-07-24). The oracle in this file
is a verbatim copy of that block against which the new shared function is
compared on a fixed input matrix.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from level_telemetry import compute_level_distance_fields


# ─── Oracle: exact copy of the pre-2026-07-24 inline block. ────────────────
def _oracle(
    entry: Optional[float],
    dpdh_raw: Optional[float],
    dpdl_raw: Optional[float],
    thr: float,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    _lvl_d00 = None
    _lvl_d50 = None
    try:
        _lvl_ep = float(entry)
        _lvl_d00 = round(min(_lvl_ep % 100.0, 100.0 - _lvl_ep % 100.0), 2)
        _lvl_d50 = round(min(_lvl_ep % 50.0, 50.0 - _lvl_ep % 50.0), 2)
    except (TypeError, ValueError):
        pass
    _lvl_cands = []
    if dpdh_raw is not None:
        _lvl_cands.append(("pdh", abs(float(dpdh_raw))))
    if dpdl_raw is not None:
        _lvl_cands.append(("pdl", abs(float(dpdl_raw))))
    if _lvl_d00 is not None:
        _lvl_cands.append(("round_00", float(_lvl_d00)))
    if _lvl_d50 is not None:
        _lvl_cands.append(("round_50", float(_lvl_d50)))
    out["at_level_threshold_pips"] = float(thr)
    out["dist_to_pdh_pips"] = (
        round(float(dpdh_raw), 2) if dpdh_raw is not None else None
    )
    out["dist_to_pdl_pips"] = (
        round(float(dpdl_raw), 2) if dpdl_raw is not None else None
    )
    if _lvl_cands:
        _lvl_cands.sort(key=lambda x: x[1])
        _lvl_type, _lvl_min = _lvl_cands[0]
        out["dist_to_nearest_level_pips"] = round(_lvl_min, 2)
        out["nearest_level_type"] = _lvl_type
        out["at_level"] = bool(_lvl_min <= float(thr))
    else:
        out["dist_to_nearest_level_pips"] = None
        out["nearest_level_type"] = None
        out["at_level"] = None
    return out


# Fixed input matrix — spans the cases the live BB_BOUNCE has hit.
_CASES = [
    # (entry, dpdh, dpdl, thr, tag)
    (13333.85,  8.2,   -12.4, 5.0, "typical_break"),
    (13300.00,  0.0,     0.0, 5.0, "on_round_00"),
    (13350.00,  50.0,  -50.0, 5.0, "on_round_50"),
    (12950.00,  -6.0,   4.0,  5.0, "pdl_within_thr"),
    (13333.85,  None,   None, 5.0, "no_pdhpdl"),
    (13333.85,  8.2,    None, 5.0, "pdh_only"),
    (13333.85,  None,  -12.4, 5.0, "pdl_only"),
    (13333.85,  8.2,   -12.4, 1.0, "tight_thr"),
    (13333.85,  8.2,   -12.4, 10.0, "loose_thr"),
    (None,      8.2,   -12.4, 5.0, "no_entry"),
    ("bogus",   8.2,   -12.4, 5.0, "bad_entry"),
    (13300.55,  -2.34, 3.667, 5.0, "rounding_ties"),
    (13333.85,  0.0,  -12.4,  5.0, "pdh_zero"),
]


@pytest.mark.parametrize("entry,dpdh,dpdl,thr,tag", _CASES)
def test_byte_identical_to_oracle(entry, dpdh, dpdl, thr, tag):
    got = compute_level_distance_fields(
        entry_price=entry,
        distance_from_pdh_pips=dpdh,
        distance_from_pdl_pips=dpdl,
        threshold_pips=thr,
    )
    want = _oracle(entry, dpdh, dpdl, thr)
    assert set(got.keys()) == set(want.keys()), f"[{tag}] key mismatch"
    for k in want:
        assert got[k] == want[k] or (
            got[k] is None and want[k] is None
        ), f"[{tag}] key={k} got={got[k]!r} want={want[k]!r}"
        assert type(got[k]) is type(want[k]), (
            f"[{tag}] key={k} type mismatch got={type(got[k])} want={type(want[k])}"
        )


def test_missing_pdh_pdl_yields_nulls_not_exception():
    out = compute_level_distance_fields(
        entry_price=None,
        distance_from_pdh_pips=None,
        distance_from_pdl_pips=None,
        threshold_pips=5.0,
    )
    assert out["dist_to_pdh_pips"] is None
    assert out["dist_to_pdl_pips"] is None
    assert out["dist_to_nearest_level_pips"] is None
    assert out["nearest_level_type"] is None
    assert out["at_level"] is None
    assert out["at_level_threshold_pips"] == 5.0


def test_at_level_threshold_boundary():
    # exactly-at-threshold is True (<=)
    out = compute_level_distance_fields(
        entry_price=13333.85,
        distance_from_pdh_pips=5.0,
        distance_from_pdl_pips=None,
        threshold_pips=5.0,
    )
    assert out["at_level"] is True
    assert out["nearest_level_type"] == "pdh"

    # just past threshold is False
    out = compute_level_distance_fields(
        entry_price=13333.85,
        distance_from_pdh_pips=5.01,
        distance_from_pdl_pips=None,
        threshold_pips=5.0,
    )
    assert out["at_level"] is False


def test_nearest_pick_is_deterministic_on_ties():
    # pdh and pdl equidistant → sort stable → pdh wins (declared first).
    # entry chosen so round_00/round_50 sit further than the pdh/pdl tie.
    out = compute_level_distance_fields(
        entry_price=13333.85,
        distance_from_pdh_pips=3.0,
        distance_from_pdl_pips=-3.0,
        threshold_pips=5.0,
    )
    assert out["nearest_level_type"] == "pdh"


def test_returns_exactly_six_keys():
    out = compute_level_distance_fields(
        entry_price=13333.85,
        distance_from_pdh_pips=8.2,
        distance_from_pdl_pips=-12.4,
        threshold_pips=5.0,
    )
    assert set(out.keys()) == {
        "at_level_threshold_pips",
        "dist_to_pdh_pips",
        "dist_to_pdl_pips",
        "dist_to_nearest_level_pips",
        "nearest_level_type",
        "at_level",
    }
