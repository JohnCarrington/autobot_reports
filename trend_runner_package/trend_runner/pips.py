"""GBPUSD pip arithmetic and price-unit handling.

Corpus price convention: the archive stores raw float values equal to
``display_quote * 10_000``. A printed value of ``13229.65`` corresponds
to a market quote of ``1.322965``. IG quotes GBPUSD at 5 decimal
places; a *pip* is the 4th decimal (``0.0001``). In corpus units this
is exactly 1.0. Sub-pip precision (``.65``) is therefore a decipip
(0.1 pip) which the archive preserves.
"""

from __future__ import annotations

PIP_UNITS: float = 1.0
"""Number of internal price units per pip (GBPUSD)."""

DECIPIP_UNITS: float = 0.1


def price_to_pips(delta_units: float) -> float:
    """Convert a signed price delta in corpus units to pips."""
    return delta_units / PIP_UNITS


def pips_to_price(pips: float) -> float:
    """Convert pips to corpus price units."""
    return pips * PIP_UNITS


def round_price(value: float, decimals: int = 2) -> float:
    """Round a raw corpus price to the smallest sub-pip step (0.1 pip)."""
    return round(value, decimals)


def format_pips(pips: float, dp: int = 1) -> str:
    return f"{pips:+.{dp}f}p"
