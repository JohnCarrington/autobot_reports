"""Guard base interface — see guards/__init__.py for the public surface."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class GuardContext:
    symbol: str
    direction: str
    strategy_mode: str
    intended_entry: float
    intended_sl: float
    intended_tp: float
    current_mid: float
    current_time_utc: datetime
    df_5m: Any
    briefing_data: Optional[Dict[str, Any]] = None
    news_blackout_active: bool = False
    news_event_in_window: Optional[Dict[str, Any]] = None
    pip_size: float = 0.0001


@dataclass
class GuardResult:
    guard_name: str
    block: bool
    reason: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


class Guard:
    name: str = ""
    enabled_env_var: str = ""

    def is_enabled(self) -> bool:
        if not self.enabled_env_var:
            return True
        return str(os.getenv(self.enabled_env_var, "1")).strip() in ("1", "true", "yes")

    def evaluate(self, context: GuardContext) -> GuardResult:
        raise NotImplementedError
