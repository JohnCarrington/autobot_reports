"""Historical NMS / HTF regime reconstruction driver.

core.Engine reads HTF direction via its OWN internal D1/H4 EMA20 of
`self.bars` — that path is already causally correct in the replay
(bars are chronological, no lookahead) and verified in the current
build's validation report.

This driver exists for the **combined Trend V3 / EMA Pullback replay**
seam: those production strategies consult `htf_regime.classify` and
`session_trend.v3_state` at every bar close. To replay them
historically we must give those modules access to only-up-to-now
candle state. We do that by monkey-patching their candle loaders.

Scope status (2026-10-15): this driver is wired and smoke-tested as
a standalone module. It is NOT consumed by the current core.Engine
replay (which does not call `htf_regime.classify`). It is kept here
as the ready-to-use seam for the Trend V3 / EMA PB combined replay —
see §Limitations in the final validation report for why that combined
replay was deferred this iteration.

Usage:
    from autobot_v3_build.approved.historical_regime import (
        HistoricalRegime,
    )
    hr = HistoricalRegime(symbol="GBPUSD")
    hr.push_m5_bar(bar)                 # feed on every m5 close
    classification = hr.classify_now()  # pure, uses the production
                                        # htf_regime.classify function
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_PROD = "/opt/tradingbot"
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)


# ── 5m → H1 → D1 aggregators (same convention as core_engine_replay) ──

def _m5_bar_dict(bar: Any) -> Dict[str, Any]:
    try:
        return {
            "timestamp": bar.ts.isoformat() if hasattr(bar.ts, "isoformat") else str(bar.ts),
            "open": float(bar.open), "high": float(bar.high),
            "low":  float(bar.low),  "close": float(bar.close),
            "ts":  bar.ts if isinstance(bar.ts, datetime) else None,
        }
    except Exception:
        return {}


def _aggregate_h1(m5_bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: Dict[datetime, Dict[str, Any]] = {}
    for b in m5_bars:
        ts = b.get("ts")
        if ts is None:
            continue
        hour = ts.replace(minute=0, second=0, microsecond=0)
        d = out.get(hour)
        if d is None:
            out[hour] = {
                "timestamp": (hour + timedelta(hours=1)).isoformat(),
                "open": b["open"], "high": b["high"],
                "low":  b["low"],  "close": b["close"],
            }
        else:
            d["high"] = max(d["high"], b["high"])
            d["low"]  = min(d["low"], b["low"])
            d["close"] = b["close"]
    return sorted(out.values(), key=lambda c: c["timestamp"])


def _aggregate_d1(h1_bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for b in h1_bars:
        day = str(b["timestamp"])[:10]
        d = out.get(day)
        if d is None:
            out[day] = {
                "timestamp": day + "T00:00:00+00:00",
                "open": b["open"], "high": b["high"],
                "low":  b["low"],  "close": b["close"],
            }
        else:
            d["high"] = max(d["high"], b["high"])
            d["low"]  = min(d["low"], b["low"])
            d["close"] = b["close"]
    return sorted(out.values(), key=lambda c: c["timestamp"])


@dataclass
class HistoricalRegime:
    """Buffers 5m bars and provides on-demand htf_regime.classify.

    Thread-model: single-threaded; the replay drives it sequentially.
    Monkey-patch model: `classify_now` installs lambdas on
    `htf_regime._load_h1_candles` and `_load_d1_candles` to point at
    our buffered aggregates, calls `htf_regime.classify(symbol)`, and
    restores the originals.
    """
    symbol: str = "GBPUSD"
    _buffer: List[Dict[str, Any]] = field(default_factory=list)
    _max_bars: int = 60 * 24 * 60   # ~60 days of 5m bars

    def push_m5_bar(self, bar: Any) -> None:
        d = _m5_bar_dict(bar)
        if not d:
            return
        self._buffer.append(d)
        if len(self._buffer) > self._max_bars:
            self._buffer = self._buffer[-self._max_bars:]

    def classify_now(self) -> Dict[str, Any]:
        import htf_regime as _htf
        h1 = _aggregate_h1(self._buffer)
        d1 = _aggregate_d1(h1)
        orig_h1 = _htf._load_h1_candles
        orig_d1 = _htf._load_d1_candles
        try:
            _htf._load_h1_candles = lambda s: h1
            _htf._load_d1_candles = lambda s: d1
            return _htf.classify(self.symbol)
        finally:
            _htf._load_h1_candles = orig_h1
            _htf._load_d1_candles = orig_d1


# ── Smoke ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import timezone as _tz
    # Build 300 synthetic hourly rising bars (so d1 UP, h1 UP, w1 UP)
    class _B:
        def __init__(self, ts, o, h, l, c):
            self.ts, self.open, self.high, self.low, self.close = ts, o, h, l, c

    hr = HistoricalRegime()
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(2000):
        ts = base + timedelta(minutes=5 * i)
        px = 13000.0 + i * 0.1
        hr.push_m5_bar(_B(ts, px, px + 0.5, px - 0.1, px + 0.3))
    out = hr.classify_now()
    print(f"[test] alignment={out.get('alignment')!r} h1={out.get('h1_state')!r} "
          f"d1={out.get('d1_state')!r} w1={out.get('w1_state')!r}")
