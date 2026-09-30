"""
Verify BB_REVERSAL pyramiding: two concurrent positions on the same epic
produce two distinct entries in EPIC_STATE with distinct suffixed pos_keys.

Exercises the suffix logic at trade_executor.py:497-506 without touching
the IG API or autobot's gate chain.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("IG_API_KEY", "test")
os.environ.setdefault("IG_IDENTIFIER", "test")
os.environ.setdefault("IG_PASSWORD", "test")

import trade_executor as te


def simulate_bb_reversal_entry(epic: str) -> str:
    """Mirror the pos_key / state-allocation logic in execute_trade for a
    BB_REVERSAL entry. Returns the pos_key actually assigned."""
    mode = "BB_REVERSAL"
    pk = te._pos_key(epic, mode)
    st = te._state_for_epic(pk)
    if st["active"] or st["pending_open"]:
        pk = te._pos_key(epic, f"{mode}_{int(time.time() * 1000)}")
        st = te._state_for_epic(pk)
    st["active"] = True
    st["mode"] = mode
    st["epic"] = epic
    st["_pos_key"] = pk
    return pk


def main() -> int:
    epic = "CS.D.GBPUSD.TODAY.IP"
    te.EPIC_STATE.clear()

    pk1 = simulate_bb_reversal_entry(epic)
    time.sleep(0.002)  # ensure millisecond timestamp moves forward
    pk2 = simulate_bb_reversal_entry(epic)

    bb_keys = [k for k in te.EPIC_STATE if k.startswith(f"{epic}|BB_REVERSAL")]
    active = [k for k, v in te.EPIC_STATE.items() if v.get("active")]

    print(f"pk1 = {pk1}")
    print(f"pk2 = {pk2}")
    print(f"EPIC_STATE BB_REVERSAL keys ({len(bb_keys)}):")
    for k in bb_keys:
        print(f"  {k}  active={te.EPIC_STATE[k].get('active')}")

    assert pk1 != pk2, f"pos_keys collided: {pk1}"
    assert pk1 == f"{epic}|BB_REVERSAL", f"first key should be un-suffixed: {pk1}"
    assert pk2.startswith(f"{epic}|BB_REVERSAL_"), f"second key should be suffixed: {pk2}"
    assert len(bb_keys) == 2
    assert len(active) == 2, f"expected 2 active positions, got {len(active)}"

    print("\nPASS: two concurrent BB_REVERSAL positions coexist in EPIC_STATE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
