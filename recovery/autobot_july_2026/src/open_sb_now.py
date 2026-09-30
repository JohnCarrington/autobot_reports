#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
open_sb_now.py — FINAL WORKING VERSION
Compatible with your IGService signature:
currency_code, direction, epic, expiry, force_open, guaranteed_stop,
level, limit_distance, limit_level, order_type, quote_id, size,
stop_distance, stop_level, trailing_stop, trailing_stop_increment, session
"""

import time
import traceback
import inspect
from ig_auth import get_ig_session


def open_sb_now(direction, epic, size, limit_distance, stop_distance):
    """
    Opens a Spread Bet position using the IG signature discovered via inspection.
    """

    try:
        ig_service, headers, account_id = get_ig_session()
        rest = ig_service

        if not ig_service:
            raise RuntimeError("IG authentication failed inside open_sb_now()")

        # (OPTIONAL) print signature once for verification
        try:
            sig = inspect.getfullargspec(rest.create_open_position)
            print("🔍 IGService.create_open_position() SIGNATURE:", sig)
        except Exception as sig_err:
            print("❌ Signature introspection failed:", sig_err)

        deal_reference = f"autobot_{int(time.time())}"

        print(
            f"🟢 Opening {direction} {epic} size={size} "
            f"stopDist={stop_distance} limDist={limit_distance}"
        )

        # -----------------------------------------------------------
        # THE EXACT SIGNATURE ORDER YOUR IG LIBRARY REQUIRES
        # -----------------------------------------------------------
        response = rest.create_open_position(
            "GBP",             # currency_code — FX SB accounts always use "GBP"
            direction,         # direction
            epic,              # epic
            "DFB",             # expiry
            True,              # force_open
            False,             # guaranteed_stop
            None,              # level
            limit_distance,    # limit_distance
            None,              # limit_level
            "MARKET",          # order_type
            None,              # quote_id
            size,              # size
            stop_distance,     # stop_distance
            None,              # stop_level
            False,             # trailing_stop
            None,              # trailing_stop_increment
            None               # session (optional, IG has default)
        )

        print(f"✅ IG response: {response}")
        return response

    except Exception as e:
        print(f"❌ open_sb_now() FAILED: {e}")
        traceback.print_exc()
        return None


# -------------------------------------------------------------
# Manual debug runner
# -------------------------------------------------------------
if __name__ == "__main__":
    print("Testing open_sb_now()…")
    result = open_sb_now("BUY", "CS.D.EURUSD.TODAY.IP", 1.0, 10, 10)
    print("Result:", result)
