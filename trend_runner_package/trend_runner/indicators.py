"""Streaming indicators used by the trend detector.

Everything here is causal: values are emitted at bar *completion* using
only closed-bar history. There is no forward smoothing.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import isfinite
from typing import Deque, Iterable, Optional


def _wilder_alpha(period: int) -> float:
    return 1.0 / period


def _ema_alpha(period: int) -> float:
    return 2.0 / (period + 1)


@dataclass
class RollingWindow:
    """Fixed-length rolling deque; discards nothing until full."""

    size: int
    values: Deque[float] = field(default_factory=deque)

    def push(self, v: float) -> None:
        self.values.append(v)
        if len(self.values) > self.size:
            self.values.popleft()

    @property
    def full(self) -> bool:
        return len(self.values) == self.size


class EMA:
    """Standard exponential moving average, seeded by SMA of the first `period` closes."""

    __slots__ = ("period", "alpha", "_seed", "_seed_sum", "value")

    def __init__(self, period: int):
        assert period >= 1
        self.period = period
        self.alpha = _ema_alpha(period)
        self._seed: list[float] = []
        self._seed_sum = 0.0
        self.value: Optional[float] = None

    def update(self, x: float) -> Optional[float]:
        if self.value is None:
            self._seed.append(x)
            self._seed_sum += x
            if len(self._seed) == self.period:
                self.value = self._seed_sum / self.period
            return self.value
        self.value = self.alpha * x + (1 - self.alpha) * self.value
        return self.value


class WilderATR:
    """Wilder-smoothed True Range over `period` bars."""

    __slots__ = ("period", "alpha", "_prev_close", "_seed", "value")

    def __init__(self, period: int = 14):
        self.period = period
        self.alpha = _wilder_alpha(period)
        self._prev_close: Optional[float] = None
        self._seed: list[float] = []
        self.value: Optional[float] = None

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
            return self.value
        self.value = self.alpha * tr + (1 - self.alpha) * self.value
        return self.value


class MACD:
    """Classic MACD (fast, slow, signal). Emits only when all seeds are ready."""

    __slots__ = ("fast", "slow", "signal_ema", "macd", "signal", "hist")

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        assert fast < slow
        self.fast = EMA(fast)
        self.slow = EMA(slow)
        self.signal_ema = EMA(signal)
        self.macd: Optional[float] = None
        self.signal: Optional[float] = None
        self.hist: Optional[float] = None

    def update(self, close: float) -> None:
        f = self.fast.update(close)
        s = self.slow.update(close)
        if f is None or s is None:
            return
        self.macd = f - s
        sig = self.signal_ema.update(self.macd)
        if sig is None:
            return
        self.signal = sig
        self.hist = self.macd - self.signal


class BollingerBands:
    """SMA(period) +/- k * stdev(population) of the last `period` closes."""

    __slots__ = ("period", "k", "_window", "mean", "upper", "lower", "width")

    def __init__(self, period: int = 20, k: float = 2.0):
        self.period = period
        self.k = k
        self._window: Deque[float] = deque(maxlen=period)
        self.mean: Optional[float] = None
        self.upper: Optional[float] = None
        self.lower: Optional[float] = None
        self.width: Optional[float] = None

    def update(self, close: float) -> None:
        self._window.append(close)
        if len(self._window) < self.period:
            return
        m = sum(self._window) / self.period
        var = sum((x - m) ** 2 for x in self._window) / self.period
        sd = var ** 0.5
        self.mean = m
        self.upper = m + self.k * sd
        self.lower = m - self.k * sd
        self.width = self.upper - self.lower


@dataclass
class M5IndicatorSnapshot:
    """State captured at the completion of a single M5 bar."""

    ema8: Optional[float]
    ema13: Optional[float]
    ema21: Optional[float]
    ema50: Optional[float]
    atr14: Optional[float]
    macd_line: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]
    bb_upper: Optional[float]
    bb_lower: Optional[float]
    bb_width: Optional[float]


class M5IndicatorStack:
    """Aggregate M5 indicator stack keyed by bar completion time."""

    def __init__(self, macd_periods: tuple[int, int, int] = (35, 45, 30)) -> None:
        self.ema8 = EMA(8)
        self.ema13 = EMA(13)
        self.ema21 = EMA(21)
        self.ema50 = EMA(50)
        self.atr14 = WilderATR(14)
        f, s, sig = macd_periods
        self.macd = MACD(f, s, sig)
        self.bb = BollingerBands(20, 2.0)

    def update(self, o: float, h: float, l: float, c: float) -> M5IndicatorSnapshot:
        e8 = self.ema8.update(c)
        e13 = self.ema13.update(c)
        e21 = self.ema21.update(c)
        e50 = self.ema50.update(c)
        atr = self.atr14.update(h, l, c)
        self.macd.update(c)
        self.bb.update(c)
        return M5IndicatorSnapshot(
            ema8=e8, ema13=e13, ema21=e21, ema50=e50,
            atr14=atr,
            macd_line=self.macd.macd, macd_signal=self.macd.signal, macd_hist=self.macd.hist,
            bb_upper=self.bb.upper, bb_lower=self.bb.lower, bb_width=self.bb.width,
        )


@dataclass
class H1IndicatorSnapshot:
    ema21: Optional[float]
    ema50: Optional[float]
    atr14: Optional[float]


class H1IndicatorStack:
    """Coarse H1 stack for structural context."""

    def __init__(self) -> None:
        self.ema21 = EMA(21)
        self.ema50 = EMA(50)
        self.atr14 = WilderATR(14)

    def update(self, o: float, h: float, l: float, c: float) -> H1IndicatorSnapshot:
        e21 = self.ema21.update(c)
        e50 = self.ema50.update(c)
        atr = self.atr14.update(h, l, c)
        return H1IndicatorSnapshot(ema21=e21, ema50=e50, atr14=atr)


def slope_pips_per_bar(values: Iterable[Optional[float]], pip_units: float) -> Optional[float]:
    """Simple last-minus-first slope over the passed sequence, expressed in pips per bar."""
    xs = [v for v in values if v is not None]
    if len(xs) < 2:
        return None
    delta = (xs[-1] - xs[0]) / (len(xs) - 1)
    delta_pips = delta / pip_units
    return delta_pips if isfinite(delta_pips) else None
