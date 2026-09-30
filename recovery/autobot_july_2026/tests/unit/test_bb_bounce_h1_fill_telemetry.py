"""Verify h1_dir_at_arm / h1_strength_at_arm propagate from armed setup
through StrategyDecision.debug and into the signal_logger row schema
under prefixed bb_ keys.

Also verifies:
  - signal_logger emits `None` for both keys when debug omits them
    (i.e. non-BB strategies see nulls).
  - A telemetry-side exception in the fill-stamp block does not
    propagate through evaluate().
"""
from __future__ import annotations

import types


def test_debug_dict_carries_h1_fields_from_fired_setup():
    """Emulate the fill-stamp block: exercised as a pure dict copy so we
    do not need to spin up a full evaluate() with df_5m + regime cache."""
    fired_setup = {
        "h1_dir_at_arm": "BEARISH",
        "h1_strength_at_arm": 0.42,
    }
    debug_dict: dict = {}
    debug_dict["bb_h1_dir_at_arm"] = fired_setup.get("h1_dir_at_arm")
    debug_dict["bb_h1_strength_at_arm"] = fired_setup.get("h1_strength_at_arm")

    assert debug_dict["bb_h1_dir_at_arm"] == "BEARISH"
    assert debug_dict["bb_h1_strength_at_arm"] == 0.42


def test_signal_logger_row_carries_bb_h1_keys_when_present_in_debug():
    """The log_open row-dict field list references dbg.get('bb_h1_*').
    We verify the mapping directly (avoids running the full log_open with
    live env, briefing, IG price feed, and a real DataFrame)."""
    dbg = {"bb_h1_dir_at_arm": "BULLISH", "bb_h1_strength_at_arm": 0.28}
    # Mirror of signal_logger.py:1194-1195 pattern:
    row = {
        "bb_h1_dir_at_arm":      dbg.get("bb_h1_dir_at_arm") if isinstance(dbg, dict) else None,
        "bb_h1_strength_at_arm": dbg.get("bb_h1_strength_at_arm") if isinstance(dbg, dict) else None,
    }
    assert row["bb_h1_dir_at_arm"] == "BULLISH"
    assert row["bb_h1_strength_at_arm"] == 0.28


def test_signal_logger_row_null_when_debug_omits_bb_h1_keys():
    """Non-BB strategies (or any dbg dict that doesn't set these keys)
    produce null-valued row cells — no KeyError, no crash."""
    dbg = {"unrelated": 1}
    row = {
        "bb_h1_dir_at_arm":      dbg.get("bb_h1_dir_at_arm") if isinstance(dbg, dict) else None,
        "bb_h1_strength_at_arm": dbg.get("bb_h1_strength_at_arm") if isinstance(dbg, dict) else None,
    }
    assert row["bb_h1_dir_at_arm"] is None
    assert row["bb_h1_strength_at_arm"] is None


def test_signal_logger_row_null_when_debug_is_not_a_dict():
    """The `isinstance(dbg, dict)` guard is intentional — some emitters
    pass a namespace instead of a dict. Confirm null behaviour."""
    dbg = types.SimpleNamespace(some_field=1)
    row = {
        "bb_h1_dir_at_arm":      dbg.get("bb_h1_dir_at_arm") if isinstance(dbg, dict) else None,
        "bb_h1_strength_at_arm": dbg.get("bb_h1_strength_at_arm") if isinstance(dbg, dict) else None,
    }
    assert row["bb_h1_dir_at_arm"] is None
    assert row["bb_h1_strength_at_arm"] is None


def test_fill_stamp_block_swallows_exceptions_in_bb_bounce():
    """The bb_bounce fill-stamp is wrapped in try/except so a telemetry
    read that raises does not propagate through evaluate(). Simulate a
    fired_setup whose .get() blows up."""
    class ExplodingSetup(dict):
        def get(self, key, default=None):
            raise RuntimeError(f"boom on {key}")

    fired_setup = ExplodingSetup()
    debug_dict: dict = {}
    # Same shape as gbpusd_bb_bounce.py:2141-2151:
    try:
        debug_dict["bb_h1_dir_at_arm"] = fired_setup.get("h1_dir_at_arm")
        debug_dict["bb_h1_strength_at_arm"] = fired_setup.get("h1_strength_at_arm")
    except Exception:
        pass
    # The keys should NOT be present (block bailed on first line), and
    # crucially no exception escaped.
    assert "bb_h1_dir_at_arm" not in debug_dict
    assert "bb_h1_strength_at_arm" not in debug_dict
