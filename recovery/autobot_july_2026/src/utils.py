"""
trading_ig.utils — Patched for pandas ≥2.2
------------------------------------------
Fixes deprecated uppercase offsets (e.g. 'MINUTE', 'H', 'M').
All offsets now lowercase ('min', 'h', 'm') to prevent ValueError.

Note: The trading_ig library uses its own utils from site-packages.
This local file is kept as a no-op placeholder. Dead functions
(conv_resol, resol_to_period, get_resolution_string, safe_to_datetime)
were removed 2026-04-07 — nothing imported them.
"""
