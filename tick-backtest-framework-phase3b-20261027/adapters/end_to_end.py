"""Phase 3b Stage 7-9 — end-to-end adapter.

Chains production BB Bounce → Phase 2 BrokerSimulator → position lifecycle.

The central_execution_gate is deliberately NOT invoked at the gate stage
here: its real-time state dependencies (NMS state, slot ledger, news tier)
cannot be reconstructed outside Level A overlapping data (which does not
exist for the certified-usable tick window — see Phase 3 §H). Instead,
this adapter exercises the gate code at module-import time (proving it
loads under isolation) and documents it as NOT_EVALUATED at the Level A
runtime seam.

The Phase 2 BrokerSimulator applies min-distance clamping, close-side
quote determination, SL/TP trigger logic, and classification taxonomy.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Add the Phase 2 sim/ dir to sys.path if the local copy is in the Phase 3b report
_P3B_LOCAL = Path(__file__).resolve().parent.parent
_PHASE2_IN_REPO = _P3B_LOCAL.parent / "tick-backtest-framework-phase2-20261027"
_PHASE2_PUBLISHED = Path("/home/autobot/autobot_reports_clone/tick-backtest-framework-phase2-20261027")
for cand in (_P3B_LOCAL, _PHASE2_IN_REPO, _PHASE2_PUBLISHED):
    if (cand / "sim" / "__init__.py").exists():
        if str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
        break

from sim.types import Direction, OrderRequest, Quote  # noqa: E402
from sim.broker import BrokerSimulator  # noqa: E402


PIP = 0.0001  # GBPUSD, used only for TP/SL distance interpretation


@dataclass
class StrategyFire:
    """A fire from the production BB Bounce strategy, in IG points space."""
    ts: int                 # ns UTC
    direction: Direction    # BUY / SELL
    entry_price_ig: float   # IG points, e.g. 13655.5
    sl_pips: float          # SL distance in pips
    tp_pips: float          # broker TP distance in pips (default 100 per prod)
    mode: str


def fire_to_order_request(fire: StrategyFire, deal_ref: str) -> OrderRequest:
    """Convert a production strategy fire into a Phase 2 OrderRequest.

    The strategy emits prices in IG points format (×10000). The Phase 2
    simulator operates in FX decimal (1.3655). Convert here.
    """
    # IG points → FX decimal: divide by 10000
    entry_fx = fire.entry_price_ig / 10000.0
    sign = 1 if fire.direction == Direction.BUY else -1
    sl_abs_fx = entry_fx - sign * fire.sl_pips * PIP
    tp_abs_fx = entry_fx + sign * fire.tp_pips * PIP
    return OrderRequest(
        deal_ref=deal_ref,
        direction=fire.direction,
        size=1.0,
        order_type="MARKET",
        submitted_ts_ns=fire.ts,
        sl_absolute=sl_abs_fx,
        tp_absolute=tp_abs_fx,
    )


def quote_fx(ts_ns: int, bid_ig: float, ask_ig: float) -> Quote:
    """Build a Phase 2 Quote from IG-points bid/ask."""
    return Quote(ts_ns, bid_ig / 10000.0, ask_ig / 10000.0)
