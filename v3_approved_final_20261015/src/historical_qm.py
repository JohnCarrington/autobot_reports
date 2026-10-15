"""Historical QM-shadow driver for the approved-build replay.

Core.Engine exposes a `qm_fn(level, side) -> Optional[str]` seam. In
production this is bound to `qm_decision_shadow`, a 2300-line stateful
machine. Replaying the full machine faithfully against historical bars
is a materially larger engineering task than the current build; we take
the conservative compromise:

  * Reuse the PRODUCTION `qm_decision_shadow.classify_state` function
    verbatim — it is a pure, deterministic classifier over §6-§10
    state vocabulary.
  * At each engine qm_fn callback, classify the state of the current
    bar against the requested level using the prior-tail of 5m bars.
  * Map {ACCEPTING, BAND_WALKING, BREAKING} on the FAR side of the
    level (against the fade direction) → CONTINUATION. Everything
    else → None (no verdict).

This is NOT a new entry rule or detector: it is the production
QM-shadow classifier wired into the engine's existing seam, with the
same inputs it receives live. It understates the live QM in two ways:

  1. Live QM carries multi-candidate state (CONFIRMED, RE_ARMED, etc.);
     the shadow is bar-local and does not persist candidate state. In
     the live system a candidate that was recently ACCEPTED may still
     return CONTINUATION on a later approach; our shadow only sees the
     local price pattern.
  2. Live QM applies memory factors (`apply_memory_to_rejection_signals`)
     from the signal log. Those are site-local and not reconstructable
     from candles alone.

Both of these shortcomings MAKE THE SHADOW MORE PERMISSIVE than live
(fewer CONTINUATION verdicts → more entries armed). The replay with
this shadow attached is therefore an UPPER BOUND on the engine's
trade count relative to live-QM behaviour.
"""
from __future__ import annotations

import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

_PROD = "/opt/tradingbot"
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)

from qm_decision_shadow import (
    STATE_ACCEPTING, STATE_APPROACHING, STATE_BAND_WALKING,
    STATE_PIERCING, STATE_REJECTING, STATE_STALLING, STATE_SWEEPING,
    STATE_TOUCHING, classify_state,
)


# ── State carrier ───────────────────────────────────────────────────────

@dataclass
class HistoricalQM:
    """Keeps a rolling tail of 5m bars so that classify_state has prior
    context for each qm_fn call.

    Attributes:
      tail_size: number of prior bars retained (classify_state uses up
        to the last 2-3; we keep ~20 to be safe).
      zone_width_pips: width used for the state classification. The
        core.Engine uses `level_window_pips=5.0`, so we mirror it.
      verdicts: optional accounting of how many of each verdict type
        were issued (for the report).
    """
    tail_size: int = 20
    zone_width_pips: float = 5.0
    _tail: Deque[Dict[str, float]] = field(default_factory=lambda: deque(maxlen=20))
    verdicts: Dict[str, int] = field(default_factory=lambda: {
        "CONTINUATION": 0, "NONE": 0, "ERROR": 0,
    })

    def push_bar(self, bar: Any) -> None:
        """Call once per 5m bar after on_bar_close so the TAIL always
        includes the most-recently-closed bar."""
        try:
            d = {
                "ts": bar.ts.isoformat() if hasattr(bar.ts, "isoformat") else str(bar.ts),
                "open": float(bar.open), "high": float(bar.high),
                "low":  float(bar.low),  "close": float(bar.close),
            }
            self._tail.append(d)
        except Exception:
            pass

    def qm_fn(self, level: Any, side: Any) -> Optional[str]:
        """Mirror of the production qm_fn callback signature.

        Returns:
          "CONTINUATION" when the current state against `level` shows
          price being ACCEPTED/BAND_WALKED/PIERCED on the far side of
          the fade (i.e. the move is continuing against the proposed
          fade entry — skip the entry).
          None in all other cases (no verdict — engine proceeds as if
          QM is silent).
        """
        try:
            if not self._tail:
                self.verdicts["NONE"] += 1
                return None
            prior = list(self._tail)[:-1]
            cur = self._tail[-1]
            level_price = float(getattr(level, "price", 0.0))
            if level_price == 0.0:
                self.verdicts["NONE"] += 1
                return None
            state = classify_state(
                zone_center=level_price,
                zone_width_pips=self.zone_width_pips,
                prior_bars=prior, cur_bar=cur,
            )
            # Setup A is a FADE at a level. For side=LONG (buy at
            # support), CONTINUATION means price is CONTINUING DOWN
            # through the level — i.e. the fade is wrong.  Mirror for
            # SHORT.
            is_long = str(side).upper() == "LONG"
            cur_close = float(cur["close"])
            against_fade = (cur_close < level_price) if is_long else (cur_close > level_price)
            continuation_state = state in (STATE_ACCEPTING, STATE_BAND_WALKING,
                                            STATE_PIERCING)
            if continuation_state and against_fade:
                self.verdicts["CONTINUATION"] += 1
                return "CONTINUATION"
            self.verdicts["NONE"] += 1
            return None
        except Exception:
            self.verdicts["ERROR"] += 1
            return None


# ── Light smoke ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    class _B:
        def __init__(self, ts, o, h, l, c):
            self.ts, self.open, self.high, self.low, self.close = ts, o, h, l, c

    class _L:
        def __init__(self, price):
            self.price = price

    q = HistoricalQM()
    # Three bars progressively closing BELOW a level at 13300 — ACCEPTING
    for i, (o, h, l, c) in enumerate([
        (13300.5, 13305.0, 13299.0, 13299.5),
        (13299.5, 13300.0, 13293.0, 13294.0),
        (13294.0, 13294.5, 13289.0, 13290.0),
    ]):
        q.push_bar(_B(f"2026-10-14T0{i}:00:00Z", o, h, l, c))
    v = q.qm_fn(_L(13300.0), "LONG")
    print(f"[test] 3 bars closing-below 13300, LONG fade: verdict={v!r} "
          f"(expected: CONTINUATION since fade is wrong)")
    print(f"[test] verdicts counter: {q.verdicts}")
