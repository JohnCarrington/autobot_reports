"""
Country filter for te_calendar._lookup_finnhub.

Regression: on 2026-04-23 at 08:30 UTC, a GBPUSD PREFLIGHT poll silently
returned DE's 07:30 Manufacturing PMI (actual=51.2 estimate=51.3) instead
of GB's 08:30 Manufacturing PMI (actual=53.6 estimate=49.9) because the
matcher scored by event-name only, and DE's actual was already published
while GB's was still null.

These tests assert that _lookup_finnhub rejects country mismatches at
match time, so the strategy keeps polling until the correct-country
event publishes.
"""
from __future__ import annotations

import pytest

import te_calendar


@pytest.fixture(autouse=True)
def clear_finnhub_cache():
    """Reset the module-level Finnhub cache around each test."""
    with te_calendar._lock:
        te_calendar._cache["events_fh"] = []
    yield
    with te_calendar._lock:
        te_calendar._cache["events_fh"] = []


def _inject_events(events):
    with te_calendar._lock:
        te_calendar._cache["events_fh"] = list(events)


# ---------------------------------------------------------------------------
# Regression — the actual bug from 2026-04-23 08:30
# ---------------------------------------------------------------------------

def test_regression_gb_preflight_does_not_match_de_release():
    """DE PMI published at 07:30 with actual=51.2 est=51.3. GB PMI
    scheduled for 08:30 but actual still null. A GBP preflight poll must
    return None — not DE."""
    _inject_events([
        {
            "country": "DE", "event": "S&P Global Manufacturing PMI Flash",
            "actual": 51.2, "estimate": 51.3, "prev": 52.2,
            "time": "2026-04-23 07:30:00", "impact": "high",
        },
        {
            "country": "GB", "event": "S&P Global Manufacturing PMI Flash",
            "actual": None, "estimate": 49.9, "prev": 51.0,
            "time": "2026-04-23 08:30:00", "impact": "high",
        },
    ])
    result = te_calendar.get_actual_for_event(
        "S&P Global Manufacturing PMI Flash",
        currency="GBP",
    )
    assert result is None, (
        f"expected None (GB actual not yet published), got {result!r}. "
        "This is the 08:30 GBP PMI bug — matcher silently returned DE."
    )


# ---------------------------------------------------------------------------
# Positive path — country filter does not block the right match
# ---------------------------------------------------------------------------

def test_positive_gb_returns_gb_when_both_published():
    """Once GB's actual lands, a GBP preflight must return GB's values,
    not DE's — even though DE's entry is still in the payload."""
    _inject_events([
        {
            "country": "DE", "event": "S&P Global Manufacturing PMI Flash",
            "actual": 51.2, "estimate": 51.3, "prev": 52.2,
            "time": "2026-04-23 07:30:00", "impact": "high",
        },
        {
            "country": "GB", "event": "S&P Global Manufacturing PMI Flash",
            "actual": 53.6, "estimate": 49.9, "prev": 51.0,
            "time": "2026-04-23 08:30:00", "impact": "high",
        },
    ])
    result = te_calendar.get_actual_for_event(
        "S&P Global Manufacturing PMI Flash",
        currency="GBP",
    )
    assert result is not None
    assert result["actual"] == 53.6
    assert result["forecast"] == 49.9


def test_positive_usd_only_returns_us_country():
    """USD preflight must skip any non-US entries even when they score
    higher on the title."""
    _inject_events([
        {
            "country": "GB", "event": "Retail Sales MoM",
            "actual": 1.5, "estimate": 0.5, "prev": -0.2,
            "impact": "high",
        },
        {
            "country": "US", "event": "Retail Sales MoM",
            "actual": 0.3, "estimate": 0.4, "prev": 0.2,
            "impact": "high",
        },
    ])
    result = te_calendar.get_actual_for_event("Retail Sales MoM", currency="USD")
    assert result is not None
    assert result["actual"] == 0.3


def test_positive_eur_matches_any_eurozone_country():
    """EUR should legitimately match EU/DE/FR/IT/ES/NL — the today's-bug
    narrative around the 07:30 EUR PMI assumes DE's print is the answer
    for currency=EUR, so the filter must NOT over-restrict."""
    _inject_events([
        {
            "country": "DE", "event": "S&P Global Manufacturing PMI Flash",
            "actual": 51.2, "estimate": 51.3, "prev": 52.2,
            "impact": "high",
        },
    ])
    result = te_calendar.get_actual_for_event(
        "S&P Global Manufacturing PMI Flash",
        currency="EUR",
    )
    assert result is not None
    assert result["actual"] == 51.2


# ---------------------------------------------------------------------------
# Adversarial inputs
# ---------------------------------------------------------------------------

def test_currency_none_returns_none():
    _inject_events([
        {
            "country": "GB", "event": "PMI",
            "actual": 50.0, "estimate": 49.0, "impact": "high",
        },
    ])
    assert te_calendar.get_actual_for_event("PMI", currency=None) is None


def test_currency_empty_returns_none():
    _inject_events([
        {
            "country": "GB", "event": "PMI",
            "actual": 50.0, "estimate": 49.0, "impact": "high",
        },
    ])
    assert te_calendar.get_actual_for_event("PMI", currency="") is None


def test_currency_unknown_returns_none():
    """Any currency not in _COUNTRIES_FOR_CURRENCY must fail closed."""
    _inject_events([
        {
            "country": "GB", "event": "PMI",
            "actual": 50.0, "estimate": 49.0, "impact": "high",
        },
    ])
    assert te_calendar.get_actual_for_event("PMI", currency="XYZ") is None


def test_empty_event_title_returns_none():
    _inject_events([
        {
            "country": "GB", "event": "PMI",
            "actual": 50.0, "estimate": 49.0, "impact": "high",
        },
    ])
    assert te_calendar.get_actual_for_event("", currency="GBP") is None


def test_no_cached_events_returns_none():
    _inject_events([])
    assert te_calendar.get_actual_for_event(
        "S&P Global Manufacturing PMI Flash", currency="GBP",
    ) is None


def test_multiple_same_country_same_title_picks_best_score():
    """If two GB entries share a title, the current tie-break (first
    wins by > not >=) must still resolve deterministically without
    leaking into a different country."""
    _inject_events([
        {
            "country": "GB", "event": "S&P Global Manufacturing PMI Flash",
            "actual": 53.6, "estimate": 49.9, "prev": 51.0,
            "impact": "high",
        },
        {
            "country": "GB", "event": "S&P Global Manufacturing PMI Flash",
            "actual": 54.0, "estimate": 49.5, "prev": 51.0,
            "impact": "high",
        },
    ])
    result = te_calendar.get_actual_for_event(
        "S&P Global Manufacturing PMI Flash",
        currency="GBP",
    )
    assert result is not None
    # Either entry is defensible — what matters is (a) non-None and
    # (b) the country is GB.
    assert result["actual"] in (53.6, 54.0)


def test_same_title_other_country_with_actual_does_not_steal_match():
    """The payload has GB event (actual=null) and US event (actual
    published). A GBP poll must not return US's value."""
    _inject_events([
        {
            "country": "US", "event": "Retail Sales MoM",
            "actual": 1.2, "estimate": 0.5, "impact": "high",
        },
        {
            "country": "GB", "event": "Retail Sales MoM",
            "actual": None, "estimate": 0.3, "impact": "high",
        },
    ])
    assert te_calendar.get_actual_for_event(
        "Retail Sales MoM", currency="GBP",
    ) is None


def test_gbp_country_set_rejects_eu_composite():
    """EU composite PMI must not satisfy a GBP lookup even though EU
    is in the TRADED_COUNTRIES set generally."""
    _inject_events([
        {
            "country": "EU", "event": "S&P Global Manufacturing PMI Flash",
            "actual": 52.2, "estimate": 50.8, "impact": "medium",
        },
    ])
    assert te_calendar.get_actual_for_event(
        "S&P Global Manufacturing PMI Flash", currency="GBP",
    ) is None
