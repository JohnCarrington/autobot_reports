"""Block continuation-style trades that fire within N pips of a level the
trade direction would be passing through. Mirrors RAW_REVERSAL's level set
(briefing legacy buckets only) for consistency.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from guards.base import Guard, GuardContext, GuardResult


def _collect_levels(briefing_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract levels from the briefing's legacy buckets only.

    Mirrors gbpusd_raw_reversal._extract_briefing_levels: pulls from
    key_levels, major_levels, and liquidity_pools (buy_side → resistance,
    sell_side → support). Does NOT use the new levels[] array, yesterday's
    H/L, or today's morning extreme — keeps the level set exactly aligned
    with what RAW_REVERSAL gates on.

    Future expansion path: the new levels[] array surfaces additional types
    (PIVOT, SWEEP_TARGET, NO_TRADE_ZONE, LIQUIDITY_POOL with directional
    metadata) that observable data may show this guard is missing. When
    expanding, treat them per the approved mapping:
      - PIVOT → blocks both directions (treat as swing)
      - SWEEP_TARGET → orient by trade_direction field
      - LIQUIDITY_POOL → orient by buy_side/sell_side label
      - NO_TRADE_ZONE → blocks both directions: the briefing has
        explicitly flagged the price as do-not-trade, so a continuation
        firing through it would act against explicit briefing guidance.
    """
    if not briefing_data or not isinstance(briefing_data, dict):
        return []

    out: List[Dict[str, Any]] = []

    for src in ("key_levels", "major_levels"):
        d = briefing_data.get(src) or {}
        for v in d.get("support") or []:
            try:
                out.append({"price": float(v), "type": "support", "source": src})
            except (TypeError, ValueError):
                continue
        for v in d.get("resistance") or []:
            try:
                out.append({"price": float(v), "type": "resistance", "source": src})
            except (TypeError, ValueError):
                continue

    lp = briefing_data.get("liquidity_pools") or {}
    for v in lp.get("sell_side") or []:
        try:
            out.append({"price": float(v), "type": "support", "source": "liquidity_pools.sell_side"})
        except (TypeError, ValueError):
            continue
    for v in lp.get("buy_side") or []:
        try:
            out.append({"price": float(v), "type": "resistance", "source": "liquidity_pools.buy_side"})
        except (TypeError, ValueError):
            continue

    return out


class LevelsProximityGuard(Guard):
    name = "levels_proximity"
    enabled_env_var = "GUARD_LEVELS_PROXIMITY_ENABLED"

    @property
    def threshold_pips(self) -> float:
        return float(os.getenv("GUARD_LEVELS_PROXIMITY_PIPS", "3") or 3.0)

    def evaluate(self, context: GuardContext) -> GuardResult:
        threshold = self.threshold_pips
        levels = _collect_levels(context.briefing_data)
        entry = context.intended_entry
        pip_size = context.pip_size or 0.0001
        direction = str(context.direction).upper()
        is_buy = direction in ("BUY", "LONG")
        is_sell = direction in ("SELL", "SHORT")

        nearest_in_path: Optional[Dict[str, Any]] = None
        nearest_distance: Optional[float] = None
        for lv in levels:
            price = lv["price"]
            lv_type = lv.get("type", "")
            in_path = (
                (is_buy and price > entry and lv_type in ("resistance", "swing"))
                or (is_sell and price < entry and lv_type in ("support", "swing"))
            )
            if not in_path:
                continue
            d = abs(price - entry) / pip_size
            if nearest_distance is None or d < nearest_distance:
                nearest_distance = d
                nearest_in_path = lv

        nearest_payload: Optional[Dict[str, Any]] = None
        if nearest_in_path is not None and nearest_distance is not None:
            nearest_payload = {
                "price": round(nearest_in_path["price"], 5),
                "source": nearest_in_path.get("source"),
                "type": nearest_in_path.get("type"),
                "distance_pips": round(nearest_distance, 2),
            }

        common = {
            "direction": direction,
            "entry": round(entry, 5),
            "nearest_level_in_path": nearest_payload,
            "all_levels_checked": len(levels),
            "threshold_pips": threshold,
        }

        if not levels:
            return GuardResult(self.name, False, "no_levels_found", data=common)

        if nearest_in_path is None or nearest_distance is None or nearest_distance > threshold:
            return GuardResult(self.name, False, "no_blocking_level_in_path", data=common)

        lv_type = nearest_in_path.get("type", "")
        block_data = {
            **common,
            "level_price": round(nearest_in_path["price"], 5),
            "level_source": nearest_in_path.get("source"),
            "level_type": lv_type,
            "distance_pips": round(nearest_distance, 2),
        }
        return GuardResult(
            self.name, True,
            reason=f"{'long' if is_buy else 'short'}_through_{lv_type}",
            data=block_data,
        )
