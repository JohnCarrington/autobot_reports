"""Per-strategy guard registration."""

from __future__ import annotations

from typing import Dict, List

# Strategy mode → ordered list of guard names to run.
# NEWS_TICK / NEWS_STRATEGY / RAW_REVERSAL stay empty: actuals-driven or
# strategy-internal filters already cover their fire conditions; layering
# guards on top would double-block.
GUARD_REGISTRY: Dict[str, List[str]] = {
    "TREND_CONTINUATION": ["news_blackout", "priced_in", "levels_proximity"],
    "BRIEFING_EXECUTION": ["stale_briefing", "news_blackout", "priced_in"],
    "BRIEFING_SWEEP":     ["stale_briefing", "news_blackout", "priced_in"],
    "3CO":                ["levels_proximity"],
    "EMA_PULLBACK":       ["news_blackout", "priced_in", "levels_proximity"],
    "GBPUSD_BB_BOUNCE":   ["news_blackout", "priced_in", "levels_proximity"],

    "NEWS_TICK":      [],
    "NEWS_STRATEGY":  [],
    "RAW_REVERSAL":   [],
}


def get_guards_for(strategy_mode: str) -> List[str]:
    return list(GUARD_REGISTRY.get(strategy_mode, []))
