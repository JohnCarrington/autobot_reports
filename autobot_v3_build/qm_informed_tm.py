"""qm_informed_tm.py — flag-gated QM-informed exit veto.

Smallest possible integration per spec. Does NOT touch
`trade_manager.py` or `tiered_ratchet.py`. Imports the existing
`qm_continuation_veto.should_veto_exhaustion` facade and exposes
a replay-friendly wrapper that returns:

    (should_hold, reason, telemetry)

Default disabled. Enable in replay only when `enabled=True`.

Policy semantics (verbatim, no change):
  * fresh ACCEPT/BREAK_AWAY + continuation_demonstrated and NO fresh
    REJECT at an active level → VETO exhaustion (hold the trade).
  * any fresh REJECT at an active level → no veto.
  * OSCILLATING / empty / stale → no veto.

For HISTORICAL REPLAY we cannot read the live observer cache because
observer_v6 writes only started 2026-09. For 2024-25 we provide an
offline evaluator that re-runs `qm_level_interactions` against the
candle archive using production formulas (no new detector).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROD = "/opt/tradingbot"
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)


def is_enabled() -> bool:
    """Default OFF. Override via `QM_INFORMED_TM_ENABLED=1`."""
    return os.getenv("QM_INFORMED_TM_ENABLED", "0") in ("1", "true", "yes", "on")


@dataclass
class VetoDecision:
    should_veto: bool
    reason: str
    telemetry: Dict[str, Any] = field(default_factory=dict)


# ── Live wrapper (production path reuse) ────────────────────────────────

def live_should_veto_exhaustion(pair: str, direction: str, bar_ts: Any) -> VetoDecision:
    """Delegate to the production façade. Returns (False, reason=disabled)
    when the integration flag is off. NEVER raises."""
    if not is_enabled():
        return VetoDecision(False, "disabled_by_flag", {})
    try:
        import qm_continuation_veto as _qcv
        veto, telemetry = _qcv.should_veto_exhaustion(pair, direction, bar_ts)
        reason = telemetry.get("reason", "")
        return VetoDecision(bool(veto), reason, dict(telemetry))
    except Exception as exc:
        return VetoDecision(False, f"exception:{type(exc).__name__}", {})


# ── Offline historical replay evaluator ─────────────────────────────────

@dataclass
class _ActiveInteraction:
    """One live interaction with a level for the OFFLINE replay path.
    Composes `qm_level_interactions` state via its public functions."""
    level_type: str
    level_price: float
    interaction: Any
    opened_at: datetime


class OfflineObserver:
    """Reconstructs `qm_level_interactions` output across the candle
    archive for a given pair and date range. Uses ONLY the production
    `qm_level_interactions.open_interaction / update / maybe_finalize /
    record_final` functions — no new state machine is created here.
    """

    def __init__(self, pair: str, zone_pips: float = 3.0):
        import qm_level_interactions as _qli
        self._qli = _qli
        self.pair = pair
        self.zone = float(zone_pips)
        # map of (level_type, round(level_price,1)) → _ActiveInteraction
        self._active: Dict[Tuple[str, float], _ActiveInteraction] = {}
        # terminal history (per-level), used for freshness in should_hold
        self._latest_terminal: Dict[Tuple[str, float], Dict[str, Any]] = {}

    def on_bar(self, bar_ts: datetime, high: float, low: float, close: float,
                level_catalog: List[Tuple[str, float]]) -> None:
        """Apply one 5m bar to each active interaction. Opens new ones
        when price enters the zone of a catalog level that is not
        already being tracked."""
        qli = self._qli
        bar = qli.BarUpdate(ts=bar_ts.isoformat(), high=high, low=low, close=close)
        # Advance existing
        done: List[Tuple[str, float]] = []
        for key, ai in list(self._active.items()):
            ai.interaction = qli.update(ai.interaction, bar)
            closed = qli.maybe_finalize(ai.interaction, bar)
            if closed is not None:
                self._latest_terminal[key] = {
                    "level_type": closed.level_type,
                    "level_price": closed.level_price,
                    "final_state": closed.final_state,
                    "approach_side": closed.approach_side,
                    "final_ts": closed.final_ts,
                    "bar_ts": bar_ts,
                    # Mirror the observer_v6 "continuation_demonstrated" bit:
                    "continuation_demonstrated": closed.final_state in ("ACCEPT", "BREAK_AWAY"),
                }
                done.append(key)
        for k in done:
            self._active.pop(k, None)
        # Open new interactions when price enters a level zone
        for lt, lv in level_catalog:
            key = (lt, round(lv, 1))
            if key in self._active:
                continue
            # Price is within zone?
            if (high >= lv - self.zone) and (low <= lv + self.zone):
                inter = qli.open_interaction(
                    symbol=self.pair, level_type=lt, level_price=float(lv),
                    ts=bar_ts.isoformat(), bar_close=close,
                )
                self._active[key] = _ActiveInteraction(
                    level_type=lt, level_price=float(lv),
                    interaction=inter, opened_at=bar_ts,
                )

    def freshness_window(self, bar_ts: datetime, minutes: int = 6
                          ) -> List[Dict[str, Any]]:
        """Return terminals whose bar_ts falls within [bar_ts - minutes, bar_ts]."""
        lo = bar_ts - timedelta(minutes=minutes)
        return [t for t in self._latest_terminal.values() if lo <= t["bar_ts"] <= bar_ts]

    def should_veto_exhaustion(self, bar_ts: datetime, direction: str = "") -> VetoDecision:
        """Offline port of qm_continuation_veto.should_veto_exhaustion.
        Same semantic policy, applied to the offline terminal log."""
        fresh = self.freshness_window(bar_ts)
        if not fresh:
            return VetoDecision(False, "no_fresh_observations", {"n_fresh": 0})
        rejects = [t for t in fresh if t["final_state"] == "REJECT"]
        if rejects:
            return VetoDecision(False, "reject_at_active_level",
                                 {"n_fresh": len(fresh), "n_rejects": len(rejects)})
        affirms = [t for t in fresh
                     if t["final_state"] in ("ACCEPT", "BREAK_AWAY")
                     and t.get("continuation_demonstrated")]
        if affirms:
            return VetoDecision(True, "accept_or_break_away_with_continuation",
                                 {"n_fresh": len(fresh), "n_affirms": len(affirms)})
        return VetoDecision(False, "no_affirmative_continuation",
                             {"n_fresh": len(fresh)})
