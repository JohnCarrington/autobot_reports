#!/usr/bin/env python3
"""
verify_dispatcher_decoupling.py — sanity check for feat/dispatcher-decoupling.

Coverage (matches spec step 17):
  1. _strategy_family canonicalisation
  2. _resolve_concurrent_cap default + override
  3. _count_open_positions: empty / single / pyramid legs / direction-suffix /
     closed positions excluded / NEWS_TICK exempt
  4. SL cooldown: default 1800, set/read/expire under simulated time,
     direction independence
  5. News blackout fresh-entry gates stripped (grep-based);
     pre-news close + CLOSE_ON_BLACKOUT paths still present
  6. R:R minimum gates stripped; strategy-internal BRIEFING_LIQUIDITY_MIN_RR
     preserved
  7. BYPASS_CONCURRENT_CAP env + decision.debug bypass paths present

Exits 0 if all assertions pass, non-zero on any failure. Run with:
  /opt/tradingbot/venv/bin/python3 /opt/tradingbot/scripts/verify_dispatcher_decoupling.py
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager

sys.path.insert(0, "/opt/tradingbot")

import strategy_logic as sl  # noqa: E402
import trade_executor as te  # noqa: E402
import autobot as ab          # noqa: E402

PASSES: int = 0
FAILS: list = []


def assert_(cond: bool, msg: str) -> None:
    global PASSES, FAILS
    if cond:
        PASSES += 1
        print(f"  PASS  {msg}")
    else:
        FAILS.append(msg)
        print(f"  FAIL  {msg}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


@contextmanager
def epic_state(positions):
    """Temporarily replace trade_executor.EPIC_STATE with `positions`
    (list of (pos_key, state_dict))."""
    saved = dict(te.EPIC_STATE)
    te.EPIC_STATE.clear()
    for pk, st in positions:
        te.EPIC_STATE[pk] = st
    try:
        yield
    finally:
        te.EPIC_STATE.clear()
        te.EPIC_STATE.update(saved)


def _pos(epic: str, mode: str, *, active: bool = True,
         pending_open: bool = False, direction: str = "BUY"):
    pk = f"{epic}|{mode}"
    st = {"epic": epic, "mode": mode, "active": active,
          "pending_open": pending_open, "direction": direction}
    return pk, st


# ───────────────────────────────────────────────────────────────────────────
section("1. _strategy_family canonicalisation")
assert_(sl._strategy_family("BB_REVERSAL") == "BB_REVERSAL", "BB_REVERSAL bare")
assert_(sl._strategy_family("BB_REVERSAL_1714405832000") == "BB_REVERSAL",
        "BB_REVERSAL pyramid leg suffix → BB_REVERSAL")
assert_(sl._strategy_family("GBPUSD_BB_BOUNCE_L") == "BB_BOUNCE",
        "GBPUSD_BB_BOUNCE_L → BB_BOUNCE")
assert_(sl._strategy_family("GBPUSD_BB_BOUNCE_S") == "BB_BOUNCE",
        "GBPUSD_BB_BOUNCE_S → BB_BOUNCE")
assert_(sl._strategy_family("GBPUSD_TREND_CONT_L") == "GBPUSD_TREND_CONTINUATION",
        "GBPUSD_TREND_CONT_L → GBPUSD_TREND_CONTINUATION")
assert_(sl._strategy_family("GBPUSD_RAW_REVERSAL_S") == "GBPUSD_RAW_REVERSAL",
        "GBPUSD_RAW_REVERSAL_S → GBPUSD_RAW_REVERSAL")
assert_(sl._strategy_family("3CO") == "3CO", "3CO bare")
assert_(sl._strategy_family("BRIEFING_EXECUTION") == "BRIEFING_EXECUTION", "BE bare")
assert_(sl._strategy_family("NEWS_TICK") == "NEWS_TICK", "NEWS_TICK bare")
assert_(sl._strategy_family("") == "", "empty input → empty")

# ───────────────────────────────────────────────────────────────────────────
section("2. _resolve_concurrent_cap defaults + override")
assert_(sl._resolve_concurrent_cap("NEWS_TICK") is None, "NEWS_TICK exempt → None")
assert_(sl._resolve_concurrent_cap("NEWS_STRATEGY") is None, "NEWS_STRATEGY exempt → None")
assert_(sl._resolve_concurrent_cap("BB_REVERSAL") == 2, "BB_REVERSAL reversal cap=2")
assert_(sl._resolve_concurrent_cap("BB_BOUNCE") == 2, "BB_BOUNCE reversal cap=2")
assert_(sl._resolve_concurrent_cap("BRIEFING_EXECUTION") == 1, "BRIEFING_EXECUTION default=1")
assert_(sl._resolve_concurrent_cap("3CO") == 1, "3CO default=1")
assert_(sl._resolve_concurrent_cap("GBPUSD_TREND_CONTINUATION") == 1, "TREND_CONT default=1")

# Per-strategy override
os.environ["CONCURRENT_CAP_3CO"] = "3"
assert_(sl._resolve_concurrent_cap("3CO") == 3, "3CO override env=3")
del os.environ["CONCURRENT_CAP_3CO"]
assert_(sl._resolve_concurrent_cap("3CO") == 1, "3CO override removed → back to 1")

# Reversal-default override
os.environ["CONCURRENT_CAP_REVERSAL_DEFAULT"] = "5"
assert_(sl._resolve_concurrent_cap("BB_REVERSAL") == 5, "REVERSAL default override=5")
del os.environ["CONCURRENT_CAP_REVERSAL_DEFAULT"]

# ───────────────────────────────────────────────────────────────────────────
section("3a. _count_open_positions — 3CO at cap 1")
EPIC = "CS.D.GBPUSD.TODAY.IP"

with epic_state([]):
    assert_(sl._count_open_positions(EPIC, "3CO") == 0, "empty state → count=0")

with epic_state([_pos(EPIC, "3CO")]):
    cur = sl._count_open_positions(EPIC, "3CO")
    cap = sl._resolve_concurrent_cap("3CO")
    assert_(cur == 1, f"one 3CO open → count=1 (got {cur})")
    assert_(cur >= cap, f"3CO at cap (cur={cur} >= cap={cap}) — second attempt would block")

# Closed position not counted
with epic_state([_pos(EPIC, "3CO", active=False, pending_open=False)]):
    assert_(sl._count_open_positions(EPIC, "3CO") == 0,
            "inactive 3CO → count=0 (slot freed)")

# pending_open counts (broker-confirmation gap)
with epic_state([_pos(EPIC, "3CO", active=False, pending_open=True)]):
    assert_(sl._count_open_positions(EPIC, "3CO") == 1,
            "pending_open 3CO → count=1 (race-safe)")

# ───────────────────────────────────────────────────────────────────────────
section("3b. BB_REVERSAL pyramid legs counted as one family")
positions = [_pos(EPIC, "BB_REVERSAL")]
with epic_state(positions):
    assert_(sl._count_open_positions(EPIC, "BB_REVERSAL") == 1,
            "1 leg (bare) → count=1")

# Add timestamp-suffixed leg (simulates trade_executor.py:688 path)
leg2 = (f"{EPIC}|BB_REVERSAL_1714405832000",
        {"epic": EPIC, "mode": "BB_REVERSAL_1714405832000",
         "active": True, "pending_open": False, "direction": "BUY"})
with epic_state([positions[0], leg2]):
    cur = sl._count_open_positions(EPIC, "BB_REVERSAL")
    cap = sl._resolve_concurrent_cap("BB_REVERSAL")
    assert_(cur == 2, f"2 legs (1 bare + 1 suffixed) → count=2 (got {cur})")
    assert_(cur >= cap, f"BB_REVERSAL at reversal cap (cur={cur} >= cap={cap})")

# Third leg → over cap (would be blocked at dispatcher)
leg3 = (f"{EPIC}|BB_REVERSAL_1714405899999",
        {"epic": EPIC, "mode": "BB_REVERSAL_1714405899999",
         "active": True, "pending_open": False, "direction": "BUY"})
with epic_state([positions[0], leg2, leg3]):
    cur = sl._count_open_positions(EPIC, "BB_REVERSAL")
    cap = sl._resolve_concurrent_cap("BB_REVERSAL")
    assert_(cur > cap, f"3 legs over cap (cur={cur} > cap={cap}) — 4th attempt blocks")

# Close the first leg → count drops, slot frees
with epic_state([
    _pos(EPIC, "BB_REVERSAL", active=False, pending_open=False),
    leg2,
]):
    cur = sl._count_open_positions(EPIC, "BB_REVERSAL")
    assert_(cur == 1, f"1 closed + 1 active → count=1 (got {cur})")

# ───────────────────────────────────────────────────────────────────────────
section("3c. BB_BOUNCE: LONG + SHORT both count toward BB_BOUNCE cap")
with epic_state([_pos(EPIC, "GBPUSD_BB_BOUNCE_L")]):
    cur = sl._count_open_positions(EPIC, "BB_BOUNCE")
    assert_(cur == 1, f"BB_BOUNCE_L only → BB_BOUNCE count=1 (got {cur})")

with epic_state([
    _pos(EPIC, "GBPUSD_BB_BOUNCE_L"),
    _pos(EPIC, "GBPUSD_BB_BOUNCE_S", direction="SELL"),
]):
    cur = sl._count_open_positions(EPIC, "BB_BOUNCE")
    cap = sl._resolve_concurrent_cap("BB_BOUNCE")
    assert_(cur == 2, f"BB_BOUNCE_L + _S → BB_BOUNCE count=2 (got {cur})")
    assert_(cur >= cap,
            f"BB_BOUNCE at cap (cur={cur} >= cap={cap}) — third attempt blocks")

# ───────────────────────────────────────────────────────────────────────────
section("3d. NEWS_TICK exempt from cap regardless of count")
with epic_state([_pos(EPIC, "NEWS_TICK")]):
    cap = sl._resolve_concurrent_cap("NEWS_TICK")
    assert_(cap is None, "NEWS_TICK cap=None (exempt) with 1 open")
    cur = sl._count_open_positions(EPIC, "NEWS_TICK")
    # cap is None so cur >= cap is irrelevant — exemption short-circuits in
    # the dispatcher integration. Just confirm cap stays None.
    assert_(cap is None and cur == 1, f"NEWS_TICK count={cur} but cap=None (still exempt)")

# ───────────────────────────────────────────────────────────────────────────
section("4. SL cooldown — default + same-direction + expiry")
assert_(ab.COOLDOWN_SECONDS_AFTER_SL == 1800,
        f"COOLDOWN_SECONDS_AFTER_SL=1800 (got {ab.COOLDOWN_SECONDS_AFTER_SL})")

# Snapshot real _SL_BLOCKS to restore after testing
saved_blocks = dict(ab._SL_BLOCKS)
try:
    ab._SL_BLOCKS.clear()

    # T=0: SL hit on 3CO BUY GBPUSD → set 1800s block
    ab._set_sl_block("GBPUSD", EPIC, "BUY", 1800)
    rem_t0 = ab._sl_block_remaining("GBPUSD", EPIC, "BUY")
    assert_(1700 < rem_t0 <= 1800,
            f"T=0: BUY block ~1800s (got {rem_t0:.0f})")

    # Different direction (SELL): no block
    rem_sell = ab._sl_block_remaining("GBPUSD", EPIC, "SELL")
    assert_(rem_sell == 0.0,
            f"T=0: SELL no block (got {rem_sell}) — different-dir re-entry allowed")

    # T+15min: simulate by rewriting the deadline 900s in the future
    key = ab._sl_block_key("GBPUSD", EPIC, "BUY")
    ab._SL_BLOCKS[key] = time.time() + 900
    rem_15 = ab._sl_block_remaining("GBPUSD", EPIC, "BUY")
    assert_(800 < rem_15 <= 900,
            f"T+15min: ~900s remain (got {rem_15:.0f}) — BUY still blocked")

    # T+31min: cooldown expired (deadline in the past)
    ab._SL_BLOCKS[key] = time.time() - 60
    rem_31 = ab._sl_block_remaining("GBPUSD", EPIC, "BUY")
    assert_(rem_31 == 0.0,
            f"T+31min: cooldown expired (got {rem_31}) — BUY re-entry allowed")
finally:
    ab._SL_BLOCKS.clear()
    ab._SL_BLOCKS.update(saved_blocks)

# ───────────────────────────────────────────────────────────────────────────
section("5. News blackout fresh-entry gates stripped; close paths preserved")
autobot_src = open("/opt/tradingbot/autobot.py").read()
assert_("new entries blocked" not in autobot_src,
        "autobot.py: '📰 News blackout: ... new entries blocked' log line removed")
assert_("News exit window active" not in autobot_src,
        "autobot.py: '📰 News exit window active' log line (briefing avoid_before) removed")

# Pre-news close path still present
assert_("_get_imminent_high_news_event" in autobot_src,
        "autobot.py: pre-news close helper still present")
assert_("PRE_NEWS_CLOSE" in autobot_src,
        "autobot.py: PRE_NEWS_CLOSE close-reason still emitted")

# CLOSE_ON_BLACKOUT close path still present
assert_("NEWS_BLACKOUT_CLOSE" in autobot_src,
        "autobot.py: NEWS_BLACKOUT_CLOSE path still present")

# trade_manager close paths still present
tm_src = open("/opt/tradingbot/trade_manager.py").read()
assert_("NEWS_BLACKOUT_PROFIT" in tm_src,
        "trade_manager.py: BRIEFING_TP NEWS_BLACKOUT_PROFIT path present")
assert_("WINDOW_SWEEP_PRE_NEWS" in tm_src,
        "trade_manager.py: WINDOW_SWEEP pre-news close path present")

# ───────────────────────────────────────────────────────────────────────────
section("6. R:R minimum gates stripped; strategy-internal R:R logic preserved")
te_src = open("/opt/tradingbot/trade_executor.py").read()
# Allow the name to appear in deprecation comments only — assert no
# executable references remain (assignment or comparison patterns).
te_code_lines = [
    ln for ln in te_src.splitlines()
    if ln.strip() and not ln.lstrip().startswith("#")
]
te_code_text = "\n".join(te_code_lines)
assert_("MIN_RR_THRESHOLD" not in te_code_text,
        "trade_executor.py: no executable MIN_RR_THRESHOLD references "
        "(deprecation comment OK)")
assert_("R:R gate BLOCKED" not in te_src,
        "trade_executor.py: 'R:R gate BLOCKED' log line removed")
assert_("blocked_min_rr" not in te_src,
        "trade_executor.py: 'blocked_min_rr' close_reason removed")
assert_(not hasattr(te, "MIN_RR_THRESHOLD"),
        "trade_executor module: no MIN_RR_THRESHOLD attribute")

be_src = open("/opt/tradingbot/briefing_execution.py").read()
assert_("Guard 3: R:R gate" not in be_src,
        "briefing_execution.py: 'Guard 3: R:R gate' comment removed")
assert_("TREND_ENTRY vetoed — R:R" not in be_src,
        "briefing_execution.py: TREND_ENTRY R:R floor log line removed")

# Strategy-internal kept
bl_src = open("/opt/tradingbot/briefing_liquidity.py").read()
assert_("BRIEFING_LIQUIDITY_MIN_RR" in bl_src,
        "briefing_liquidity.py: BRIEFING_LIQUIDITY_MIN_RR (TP picker) preserved")

# ───────────────────────────────────────────────────────────────────────────
section("7. BYPASS_CONCURRENT_CAP env + decision.debug bypass paths")
sl_src = open("/opt/tradingbot/strategy_logic.py").read()
assert_("BYPASS_CONCURRENT_CAP" in sl_src,
        "strategy_logic.py: BYPASS_CONCURRENT_CAP env var read")
assert_("would-block at" in sl_src and "bypassed via" in sl_src,
        "strategy_logic.py: 'would-block bypassed' log line present")
assert_("bypass_concurrent_cap" in sl_src,
        "strategy_logic.py: per-call decision.debug.bypass_concurrent_cap supported")

# ───────────────────────────────────────────────────────────────────────────
section("Summary")
print(f"\n  {PASSES} pass, {len(FAILS)} fail")
for f in FAILS:
    print(f"    FAIL: {f}")

sys.exit(0 if not FAILS else 1)
