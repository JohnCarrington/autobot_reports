"""Block briefing-driven trades when price has displaced past threshold against bias."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from guards.base import Guard, GuardContext, GuardResult


def _session_open_price_from_df(df_5m: Any, current_time_utc: datetime) -> Optional[float]:
    """Return the open of today's 06:00 UTC 5m bar, or None if not present.

    Pulls from df_5m as data-derivation only — no new state. Returns None
    on weekend boots or when the session-open bar isn't in the buffer yet,
    which the caller treats as 'don't guard, don't fake'.
    """
    if df_5m is None:
        return None

    today = current_time_utc.astimezone(timezone.utc).date()
    target_ts = datetime(today.year, today.month, today.day, 6, 0, tzinfo=timezone.utc)

    try:
        import pandas as pd
        if isinstance(df_5m, pd.DataFrame):
            if "timestamp" not in df_5m.columns or len(df_5m) == 0:
                return None
            ts_col = pd.to_datetime(df_5m["timestamp"], utc=True, errors="coerce")
            mask = ts_col == target_ts
            if not mask.any():
                return None
            return float(df_5m.loc[mask, "open"].iloc[0])
    except Exception:
        pass

    try:
        for raw in df_5m:
            bar = raw.get("candle") if isinstance(raw, dict) and isinstance(raw.get("candle"), dict) else raw
            ts = getattr(bar, "ts", None) or getattr(bar, "timestamp", None)
            if isinstance(bar, dict):
                ts = bar.get("timestamp") or bar.get("ts") or bar.get("t")
            if ts is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if isinstance(ts, (int, float)):
                ts = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts.astimezone(timezone.utc) == target_ts:
                if isinstance(bar, dict):
                    val = bar.get("open") if "open" in bar else bar.get("o")
                    return float(val) if val is not None else None
                return float(getattr(bar, "open"))
    except Exception:
        pass

    return None


class StaleBriefingGuard(Guard):
    name = "stale_briefing"
    enabled_env_var = "GUARD_STALE_BRIEFING_ENABLED"

    @property
    def threshold_pips(self) -> float:
        return float(os.getenv("GUARD_STALE_BRIEFING_PIPS", "50") or 50.0)

    def evaluate(self, context: GuardContext) -> GuardResult:
        briefing = context.briefing_data or {}
        bias = str(briefing.get("session_bias", "")).upper()

        if bias not in ("BULLISH", "BEARISH"):
            return GuardResult(self.name, False, "neutral_bias_or_missing",
                               data={"bias": bias or "MISSING"})

        sf = briefing.get("signal_filter") or {}
        allow_buys = sf.get("allow_buys", True)
        allow_sells = sf.get("allow_sells", True)

        direction_u = str(context.direction).upper()
        is_buy = direction_u in ("BUY", "LONG")
        is_sell = direction_u in ("SELL", "SHORT")

        if is_buy and allow_buys is False:
            return GuardResult(self.name, False, "briefing_signal_filter_already_blocks",
                               data={"reason": "allow_buys=false"})
        if is_sell and allow_sells is False:
            return GuardResult(self.name, False, "briefing_signal_filter_already_blocks",
                               data={"reason": "allow_sells=false"})

        session_open = _session_open_price_from_df(context.df_5m, context.current_time_utc)
        if session_open is None:
            return GuardResult(self.name, False, "session_open_unavailable",
                               data={"note": "no 06:00 UTC row in df_5m — skip-no-block fallback"})

        pip_size = context.pip_size or 0.0001
        displacement_pips = (context.current_mid - session_open) / pip_size
        threshold = self.threshold_pips

        block = False
        blocked_dir = ""
        if bias == "BEARISH" and is_sell and displacement_pips > threshold:
            block = True
            blocked_dir = "SELL"
        elif bias == "BULLISH" and is_buy and displacement_pips < -threshold:
            block = True
            blocked_dir = "BUY"

        return GuardResult(
            self.name,
            block,
            reason=f"bias={bias} disp={displacement_pips:+.1f}p threshold={threshold:.0f}p" if block else "within_threshold",
            data={
                "bias": bias,
                "session_open": round(session_open, 5),
                "current": round(context.current_mid, 5),
                "displacement_pips": round(displacement_pips, 2),
                "threshold_pips": threshold,
                "blocked_direction": blocked_dir,
            },
        )
