"""
Briefing Calibrator
───────────────────
Reads briefing outcome CSVs and generates a calibration summary string
to inject into the morning briefing prompt for self-improvement.
"""

import logging
from typing import Optional

from briefing_tracker import BriefingTracker

logger = logging.getLogger(__name__)

_tracker = BriefingTracker()


def get_calibration_summary(
    symbol: Optional[str] = None,
    lookback_days: int = 14,
) -> Optional[str]:
    """
    Returns a human-readable calibration summary string, or None if
    insufficient data.

    Example output:
        'Recent performance (14 days): Direction accuracy 68%.
         Confirmed signals win rate 72% (18 trades) vs unconfirmed 45% (11 trades).
         High confidence (>0.7) accuracy 75%.
         LIQUIDITY_HUNT sessions: 8 trades, 5 wins (62%).'
    """
    try:
        stats = _tracker.get_statistics(symbol=symbol, lookback_days=lookback_days)
    except Exception as e:
        logger.warning(f"[briefing_calibrator] Failed to get statistics: {e}")
        return None

    total = stats.get("total_trades", 0)
    if total < 3:
        return None

    parts = [f"Recent performance ({lookback_days} days, {total} trades):"]

    da = stats.get("direction_accuracy")
    if da is not None:
        parts.append(f"Direction accuracy {da}%.")

    cwr = stats.get("confirmed_win_rate")
    ct = stats.get("confirmed_total", 0)
    uwr = stats.get("unconfirmed_win_rate")
    ut = stats.get("unconfirmed_total", 0)
    if cwr is not None and uwr is not None:
        parts.append(
            f"Confirmed signals win rate {cwr}% ({ct} trades) "
            f"vs unconfirmed {uwr}% ({ut} trades)."
        )
    elif cwr is not None:
        parts.append(f"Confirmed signals win rate {cwr}% ({ct} trades).")

    p1wr = stats.get("plan1_win_rate")
    p1t = stats.get("plan1_total", 0)
    if p1wr is not None:
        parts.append(f"Plan-matched trades win rate {p1wr}% ({p1t} trades).")

    cal = stats.get("confidence_calibration", {})
    if cal.get("0.7+") is not None:
        parts.append(f"High confidence (>0.7) accuracy {cal['0.7+']}%.")
    if cal.get("0.6-0.7") is not None:
        parts.append(f"Medium confidence (0.6-0.7) accuracy {cal['0.6-0.7']}%.")

    sess = stats.get("session_expectation_stats", {})
    for exp, s in sess.items():
        parts.append(
            f"{exp} sessions: {s['trades']} trades, {s['wins']} wins ({s['win_rate']}%)."
        )

    return " ".join(parts)
