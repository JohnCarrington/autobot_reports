"""Block entries where price has already moved through the trade direction."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from guards.base import Guard, GuardContext, GuardResult


def _price_n_mins_ago(df_5m: Any, current_time_utc: datetime, lookback_mins: int) -> Optional[float]:
    """Return the close of the bar approximately lookback_mins minutes ago."""
    if df_5m is None:
        return None

    target_ts = current_time_utc.astimezone(timezone.utc) - timedelta(minutes=lookback_mins)

    try:
        import pandas as pd
        if isinstance(df_5m, pd.DataFrame):
            if len(df_5m) == 0 or "timestamp" not in df_5m.columns:
                return None
            ts_col = pd.to_datetime(df_5m["timestamp"], utc=True, errors="coerce")
            diffs = (ts_col - target_ts).abs()
            idx = diffs.idxmin()
            if pd.isna(idx):
                return None
            tol = timedelta(minutes=4, seconds=59)
            if diffs.loc[idx] > tol:
                return None
            return float(df_5m.loc[idx, "close"])
    except Exception:
        pass

    try:
        best = None
        best_diff = None
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
            diff = abs((ts - target_ts).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best = bar
        if best is None or best_diff is None or best_diff > 4 * 60 + 59:
            return None
        if isinstance(best, dict):
            val = best.get("close") if "close" in best else best.get("c")
            return float(val) if val is not None else None
        return float(getattr(best, "close"))
    except Exception:
        return None


class PricedInGuard(Guard):
    name = "priced_in"
    enabled_env_var = "GUARD_PRICED_IN_ENABLED"

    @property
    def threshold_pips(self) -> float:
        return float(os.getenv("GUARD_PRICED_IN_PIPS", "25") or 25.0)

    @property
    def lookback_mins(self) -> int:
        return int(float(os.getenv("GUARD_PRICED_IN_LOOKBACK_MINS", "30") or 30))

    def evaluate(self, context: GuardContext) -> GuardResult:
        lookback = self.lookback_mins
        threshold = self.threshold_pips
        pip_size = context.pip_size or 0.0001

        price_then = _price_n_mins_ago(context.df_5m, context.current_time_utc, lookback)
        if price_then is None:
            return GuardResult(self.name, False, "insufficient_lookback_data",
                               data={"lookback_mins": lookback})

        price_now = context.current_mid
        move_pips = (price_now - price_then) / pip_size

        direction_u = str(context.direction).upper()
        is_buy = direction_u in ("BUY", "LONG")
        is_sell = direction_u in ("SELL", "SHORT")

        block = False
        if is_buy and move_pips > threshold:
            block = True
        elif is_sell and move_pips < -threshold:
            block = True

        return GuardResult(
            self.name,
            block,
            reason=f"move_in_dir={move_pips:+.1f}p threshold={threshold:.0f}p lookback={lookback}m" if block else "within_threshold",
            data={
                "direction": direction_u,
                "price_then": round(price_then, 5),
                "price_now": round(price_now, 5),
                "move_pips": round(move_pips, 2),
                "threshold_pips": threshold,
                "lookback_mins": lookback,
            },
        )
