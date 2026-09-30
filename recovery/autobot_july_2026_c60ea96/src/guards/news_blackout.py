"""Block fresh entries during news blackout windows + a configurable pre-event buffer."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from guards.base import Guard, GuardContext, GuardResult


class NewsBlackoutGuard(Guard):
    name = "news_blackout"
    enabled_env_var = "GUARD_NEWS_BLACKOUT_ENABLED"

    @property
    def pre_buffer_mins(self) -> int:
        return int(float(os.getenv("GUARD_PRE_BLACKOUT_BUFFER_MINS", "10") or 10))

    def evaluate(self, context: GuardContext) -> GuardResult:
        if context.news_blackout_active:
            ev = context.news_event_in_window or {}
            return GuardResult(
                self.name, True,
                reason=f"blackout_active_{ev.get('event_name','event')}@{ev.get('event_time_utc','?')}UTC",
                data={
                    "event_name": ev.get("event_name"),
                    "event_time_utc": ev.get("event_time_utc"),
                    "mins_to_event": ev.get("mins_to_event"),
                    "blackout_minutes": ev.get("blackout_minutes"),
                    "in_pre_buffer": False,
                },
            )

        ev = context.news_event_in_window or {}
        mins_to_event = ev.get("mins_to_event")
        if mins_to_event is None:
            return GuardResult(self.name, False, "no_event_in_window", data={})

        try:
            mins_to = float(mins_to_event)
        except (TypeError, ValueError):
            return GuardResult(self.name, False, "bad_mins_to_event", data={"raw": mins_to_event})

        buf = self.pre_buffer_mins
        if 0 <= mins_to < buf:
            return GuardResult(
                self.name, True,
                reason=f"pre_buffer_{ev.get('event_name','event')}@{ev.get('event_time_utc','?')}UTC mins_to={mins_to:.1f}",
                data={
                    "event_name": ev.get("event_name"),
                    "event_time_utc": ev.get("event_time_utc"),
                    "mins_to_event": mins_to,
                    "blackout_minutes": ev.get("blackout_minutes"),
                    "in_pre_buffer": True,
                    "buffer_mins": buf,
                },
            )

        return GuardResult(self.name, False, "outside_buffer",
                           data={"mins_to_event": mins_to, "buffer_mins": buf})
