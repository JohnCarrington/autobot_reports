"""Unit tests for compute_usd_strength — the basket-based USD strength
proxy that replaces the USDJPY-only computation at morning_briefing.py:767.
Bug 2 of docs/briefing_producer_audit_2026-05-11.md.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, "/opt/tradingbot")

from usd_strength import (
    compute_usd_strength,
    USD_BASE_PAIRS, USD_QUOTE_PAIRS,
    STRONG_THRESHOLD,
)


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _h1_buffer(closes, base_price=100.0, range_per_bar=0.5,
               now_utc: datetime | None = None, n_bars: int | None = None):
    """Build an H1 buffer of dicts. `closes` is the close series; high/low
    track close ± range_per_bar/2. Timestamps end at `now_utc` (default
    fresh = utcnow), one bar per hour."""
    now_utc = now_utc or datetime.now(timezone.utc)
    n = n_bars or len(closes)
    if len(closes) < n:
        closes = [base_price] * (n - len(closes)) + list(closes)
    out = []
    for i, c in enumerate(closes):
        ts = now_utc - timedelta(hours=(n - 1 - i))
        out.append({
            "timestamp": ts.isoformat(),
            "open": c - 0.1, "high": c + range_per_bar / 2,
            "low": c - range_per_bar / 2, "close": c,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────
# Group 1 — basket aggregation
# ─────────────────────────────────────────────────────────────────────────

def test_basket_all_usd_positive_says_strong():
    """USDJPY up, USDCAD up, EURUSD down, GBPUSD down — all consistent
    with USD strengthening."""
    n = 25
    buffers = {
        "USDJPY": _h1_buffer([150.0 + 0.1 * i for i in range(n)], range_per_bar=0.5),
        "USDCAD": _h1_buffer([1.35 + 0.001 * i for i in range(n)], range_per_bar=0.005),
        "EURUSD": _h1_buffer([1.10 - 0.001 * i for i in range(n)], range_per_bar=0.005),
        "GBPUSD": _h1_buffer([1.27 - 0.0008 * i for i in range(n)], range_per_bar=0.005),
    }
    out = compute_usd_strength("AUDUSD", buffers, lookback_bars=6, atr_lookback_bars=20)
    assert out["method"] == "basket"
    assert out["usd_proxy_bias"] == "USD_STRONG"
    assert out["usd_proxy_pips"] > STRONG_THRESHOLD
    assert len(out["contributing_pairs"]) == 4


def test_basket_mixed_signals_near_zero():
    """Half pairs say USD-up, half say USD-down: result clamps to NEUTRAL band."""
    n = 25
    # USDJPY rising 0.1/bar AND EURUSD rising 0.001/bar = JPY says USD-up,
    # EURUSD says USD-down. With matched normalised magnitudes they cancel.
    buffers = {
        "USDJPY": _h1_buffer([150.0 + 0.1 * i for i in range(n)], range_per_bar=1.0),
        "USDCAD": _h1_buffer([1.35] * n, range_per_bar=0.005),  # flat
        "EURUSD": _h1_buffer([1.10 + 0.001 * i for i in range(n)], range_per_bar=0.01),
        "GBPUSD": _h1_buffer([1.27] * n, range_per_bar=0.005),  # flat
    }
    out = compute_usd_strength("AUDUSD", buffers, lookback_bars=6, atr_lookback_bars=20)
    assert out["method"] == "basket"
    assert out["usd_proxy_bias"] == "USD_NEUTRAL"
    assert abs(out["usd_proxy_pips"]) <= STRONG_THRESHOLD


def test_basket_all_usd_negative_says_weak():
    n = 25
    buffers = {
        "USDJPY": _h1_buffer([150.0 - 0.1 * i for i in range(n)], range_per_bar=0.5),
        "USDCAD": _h1_buffer([1.35 - 0.001 * i for i in range(n)], range_per_bar=0.005),
        "EURUSD": _h1_buffer([1.10 + 0.001 * i for i in range(n)], range_per_bar=0.005),
        "GBPUSD": _h1_buffer([1.27 + 0.0008 * i for i in range(n)], range_per_bar=0.005),
    }
    out = compute_usd_strength("AUDUSD", buffers, lookback_bars=6, atr_lookback_bars=20)
    assert out["method"] == "basket"
    assert out["usd_proxy_bias"] == "USD_WEAK"
    assert out["usd_proxy_pips"] < -STRONG_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────
# Group 2 — per-pair exclusion and tier degradation
# ─────────────────────────────────────────────────────────────────────────

def test_briefing_for_usdjpy_excludes_itself():
    n = 25
    buffers = {
        "USDJPY": _h1_buffer([150.0 + i * 10 for i in range(n)], range_per_bar=0.5),  # huge move
        "EURUSD": _h1_buffer([1.10 - 0.001 * i for i in range(n)], range_per_bar=0.005),
        "USDCAD": _h1_buffer([1.35 + 0.001 * i for i in range(n)], range_per_bar=0.005),
    }
    out = compute_usd_strength("USDJPY", buffers, lookback_bars=6, atr_lookback_bars=20)
    assert "USDJPY" not in out["contributing_pairs"]
    # Result still well-formed because EURUSD + USDCAD are available
    assert out["method"] in ("basket", "degraded_single")


def test_degraded_single_with_two_pairs():
    n = 25
    buffers = {
        "USDJPY": _h1_buffer([150.0 + 0.1 * i for i in range(n)], range_per_bar=0.5),
        "EURUSD": _h1_buffer([1.10 - 0.001 * i for i in range(n)], range_per_bar=0.005),
    }
    out = compute_usd_strength("USDCAD", buffers, lookback_bars=6, atr_lookback_bars=20)
    assert out["method"] == "degraded_single"
    assert len(out["contributing_pairs"]) == 2


def test_unavailable_when_no_pairs():
    out = compute_usd_strength("EURUSD", {}, lookback_bars=6, atr_lookback_bars=20)
    assert out["method"] == "unavailable"
    assert out["usd_proxy_pips"] is None
    assert out["usd_proxy_bias"] is None
    assert out["contributing_pairs"] == []


def test_unavailable_when_only_self_pair():
    n = 25
    buffers = {"EURUSD": _h1_buffer([1.10] * n)}
    out = compute_usd_strength("EURUSD", buffers, lookback_bars=6, atr_lookback_bars=20)
    assert out["method"] == "unavailable"
    assert out["usd_proxy_pips"] is None


# ─────────────────────────────────────────────────────────────────────────
# Group 3 — Today's bug: per-pair values must differ
# ─────────────────────────────────────────────────────────────────────────

def test_gbpusd_and_eurusd_results_differ_today():
    """The visible bug today: GBPUSD and EURUSD both saw +26.2 because both
    pulled from the same USDJPY computation. After the fix, each pair's
    basket excludes itself, so the contributing sets differ."""
    cache_root = Path("/opt/tradingbot/cache/htf")
    if not cache_root.exists():
        pytest.skip("no HTF cache in this environment")
    buffers = {}
    for p in ("GBPUSD", "EURUSD", "USDJPY", "USDCAD"):
        path = cache_root / f"{p}_H1.json"
        if not path.exists():
            continue
        candles = json.loads(path.read_text()).get("candles", []) or []
        candles = sorted(candles, key=lambda c: c.get("timestamp", ""))
        buffers[p] = candles
    if "GBPUSD" not in buffers or "EURUSD" not in buffers:
        pytest.skip("required pairs not in cache")
    # Use the most recent H1 timestamp as now_utc to avoid staleness skips.
    from datetime import datetime
    latest_ts = max(
        datetime.fromisoformat(buffers[p][-1]["timestamp"])
        for p in buffers
    )
    g = compute_usd_strength("GBPUSD", buffers, now_utc=latest_ts)
    e = compute_usd_strength("EURUSD", buffers, now_utc=latest_ts)
    assert g["contributing_pairs"] != e["contributing_pairs"], (
        f"contributing pairs should differ: g={g['contributing_pairs']} e={e['contributing_pairs']}"
    )
    # The numeric results should also differ — the visible symptom of the bug.
    assert g["usd_proxy_pips"] != e["usd_proxy_pips"], (
        f"GBPUSD and EURUSD must compute different USD-proxy values; got "
        f"g={g['usd_proxy_pips']} e={e['usd_proxy_pips']}"
    )


# ─────────────────────────────────────────────────────────────────────────
# Group 4 — Adversarial / edge cases
# ─────────────────────────────────────────────────────────────────────────

def test_boj_intervention_does_not_dominate():
    """USDJPY rockets 200 pips while the rest of the basket is flat. The
    pre-fix proxy would scream USD_STRONG; the basket-weighted version sees
    one outlier in a flat basket."""
    n = 25
    flat_eur = _h1_buffer([1.10] * n, range_per_bar=0.005)
    flat_cad = _h1_buffer([1.35] * n, range_per_bar=0.005)
    flat_gbp = _h1_buffer([1.27] * n, range_per_bar=0.005)
    jpy_spike = _h1_buffer(
        [150.0 + i * 0.005 for i in range(n - 6)] + [150.0 + 2.0 + i * 0.1 for i in range(6)],
        range_per_bar=0.3,
    )
    buffers = {
        "USDJPY": jpy_spike, "EURUSD": flat_eur,
        "USDCAD": flat_cad, "GBPUSD": flat_gbp,
    }
    out = compute_usd_strength("AUDUSD", buffers, lookback_bars=6, atr_lookback_bars=20)
    # Even though USDJPY moved a LOT, the basket is mostly flat. JPY's
    # contribution gets diluted by /4 — the aggregate should NOT exceed
    # the dominant-single-pair signal we'd get from JPY alone.
    pre_fix_jpy_only_normalized = (
        (jpy_spike[-1]["close"] - jpy_spike[-7]["close"]) /
        sum(c["high"] - c["low"] for c in jpy_spike[-20:]) * 20
    )
    pre_fix_pips = round(pre_fix_jpy_only_normalized * 10.0, 1)
    # The basket dilutes by ~4×.
    assert abs(out["usd_proxy_pips"]) < abs(pre_fix_pips), (
        f"basket should dilute lone-JPY spike: basket={out['usd_proxy_pips']}, "
        f"jpy-only-style={pre_fix_pips}"
    )


def test_stale_pair_excluded():
    n = 25
    fresh = _h1_buffer([150.0 + 0.1 * i for i in range(n)])
    stale_now = datetime.now(timezone.utc) - timedelta(hours=48)
    stale_buf = _h1_buffer([150.0] * n, now_utc=stale_now)
    buffers = {"USDJPY": stale_buf, "EURUSD": fresh, "USDCAD": fresh}
    out = compute_usd_strength("GBPUSD", buffers, lookback_bars=6, atr_lookback_bars=20)
    assert "USDJPY" not in out["contributing_pairs"]
    assert out["skipped"].get("USDJPY", "").startswith("stale")


def test_genuine_usd_strong_signal_preserved():
    """When all basket pairs genuinely agree on USD-up, the proxy correctly
    reads USD_STRONG without dilution (adversarial check: don't normalize
    away genuine signal)."""
    n = 25
    buffers = {
        "USDJPY": _h1_buffer([150.0 + 0.5 * i for i in range(n)], range_per_bar=0.5),
        "USDCAD": _h1_buffer([1.35 + 0.005 * i for i in range(n)], range_per_bar=0.005),
        "EURUSD": _h1_buffer([1.10 - 0.005 * i for i in range(n)], range_per_bar=0.005),
        "GBPUSD": _h1_buffer([1.27 - 0.004 * i for i in range(n)], range_per_bar=0.005),
    }
    out = compute_usd_strength("AUDUSD", buffers, lookback_bars=6, atr_lookback_bars=20)
    assert out["usd_proxy_bias"] == "USD_STRONG"
    # All four contributions should agree in sign
    signs = {c["usd_contribution"] > 0 for c in out["per_pair"]}
    assert signs == {True}


def test_insufficient_history_excluded():
    short_buf = _h1_buffer([150.0, 151.0, 152.0], n_bars=3)  # 3 bars only
    long_buf = _h1_buffer([1.10 + 0.001 * i for i in range(25)])
    buffers = {"USDJPY": short_buf, "EURUSD": long_buf, "USDCAD": long_buf}
    out = compute_usd_strength("GBPUSD", buffers, lookback_bars=6, atr_lookback_bars=20)
    assert "USDJPY" not in out["contributing_pairs"]
    assert "insufficient" in out["skipped"].get("USDJPY", "")


# ─────────────────────────────────────────────────────────────────────────
# Group 5 — pre-fix regression markers
# ─────────────────────────────────────────────────────────────────────────

def test_module_imported_by_morning_briefing():
    """Bug 2 wire-in: morning_briefing must import usd_strength."""
    src = Path("/opt/tradingbot/morning_briefing.py").read_text()
    assert "from usd_strength import" in src or "import usd_strength" in src, (
        "morning_briefing must import usd_strength (Bug 2 fix)"
    )


def test_prompt_language_softened():
    """The 'often overrides isolated H1 momentum' phrase must be replaced."""
    src = Path("/opt/tradingbot/morning_briefing.py").read_text()
    assert "often overrides isolated H1 momentum" not in src, (
        "old prompt language must be replaced (Bug 2 narrative softening)"
    )
    assert "daily_bias" in src and "deterministic" in src.lower(), (
        "softened prompt should defer to deterministic daily_bias"
    )


def test_sign_convention():
    """USD-base pairs (USDJPY/USDCAD/USDCHF) get +1, USD-quote get -1."""
    from usd_strength import _sign
    assert _sign("USDJPY") == +1
    assert _sign("USDCAD") == +1
    assert _sign("USDCHF") == +1
    assert _sign("EURUSD") == -1
    assert _sign("GBPUSD") == -1
    assert _sign("AUDUSD") == -1
    assert _sign("NZDUSD") == -1
