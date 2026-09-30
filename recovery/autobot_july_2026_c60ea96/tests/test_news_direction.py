"""
Tests for NEWS strategy currency-aware direction mapping.

Verifies that PREFLIGHT fires in the correct direction for every
currency/beat/miss combination, and that unaffected pairs are skipped.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from news_tick_strategy import (
    get_preflight_signal,
    is_pair_affected,
    _PREFLIGHT_DIRECTION,
    _AFFECTED_PAIRS,
)


# ── USD events affect all pairs ──────────────────────────────────

class TestUSDEvents:
    def test_usd_beat_gbpusd_sell(self):
        assert get_preflight_signal("USD", "BEAT", "GBPUSD") == "SELL"

    def test_usd_beat_eurusd_sell(self):
        assert get_preflight_signal("USD", "BEAT", "EURUSD") == "SELL"

    def test_usd_beat_usdjpy_buy(self):
        assert get_preflight_signal("USD", "BEAT", "USDJPY") == "BUY"

    def test_usd_beat_usdcad_buy(self):
        """USDCAD: USD is base. USD BEAT = USD strengthens = BUY USDCAD."""
        assert get_preflight_signal("USD", "BEAT", "USDCAD") == "BUY"

    def test_usd_miss_gbpusd_buy(self):
        assert get_preflight_signal("USD", "MISS", "GBPUSD") == "BUY"

    def test_usd_miss_eurusd_buy(self):
        assert get_preflight_signal("USD", "MISS", "EURUSD") == "BUY"

    def test_usd_miss_usdjpy_sell(self):
        assert get_preflight_signal("USD", "MISS", "USDJPY") == "SELL"

    def test_usd_miss_usdcad_sell(self):
        """USDCAD: USD MISS = USD weakens = SELL USDCAD."""
        assert get_preflight_signal("USD", "MISS", "USDCAD") == "SELL"


# ── GBP events affect GBPUSD only ───────────────────────────────

class TestGBPEvents:
    def test_gbp_beat_gbpusd_buy(self):
        assert get_preflight_signal("GBP", "BEAT", "GBPUSD") == "BUY"

    def test_gbp_miss_gbpusd_sell(self):
        assert get_preflight_signal("GBP", "MISS", "GBPUSD") == "SELL"

    def test_gbp_beat_eurusd_none(self):
        assert get_preflight_signal("GBP", "BEAT", "EURUSD") is None

    def test_gbp_beat_usdjpy_none(self):
        assert get_preflight_signal("GBP", "BEAT", "USDJPY") is None

    def test_gbp_beat_usdcad_none(self):
        assert get_preflight_signal("GBP", "BEAT", "USDCAD") is None

    def test_gbp_miss_eurusd_none(self):
        assert get_preflight_signal("GBP", "MISS", "EURUSD") is None


# ── EUR events affect EURUSD only ───────────────────────────────

class TestEUREvents:
    def test_eur_beat_eurusd_buy(self):
        assert get_preflight_signal("EUR", "BEAT", "EURUSD") == "BUY"

    def test_eur_miss_eurusd_sell(self):
        assert get_preflight_signal("EUR", "MISS", "EURUSD") == "SELL"

    def test_eur_beat_gbpusd_none(self):
        assert get_preflight_signal("EUR", "BEAT", "GBPUSD") is None

    def test_eur_beat_usdjpy_none(self):
        assert get_preflight_signal("EUR", "BEAT", "USDJPY") is None


# ── JPY events affect USDJPY only ───────────────────────────────

class TestJPYEvents:
    def test_jpy_beat_usdjpy_sell(self):
        """JPY BEAT = JPY strengthens = SELL USDJPY (JPY is quote currency)."""
        assert get_preflight_signal("JPY", "BEAT", "USDJPY") == "SELL"

    def test_jpy_miss_usdjpy_buy(self):
        assert get_preflight_signal("JPY", "MISS", "USDJPY") == "BUY"

    def test_jpy_beat_gbpusd_none(self):
        assert get_preflight_signal("JPY", "BEAT", "GBPUSD") is None

    def test_jpy_beat_eurusd_none(self):
        assert get_preflight_signal("JPY", "BEAT", "EURUSD") is None


# ── CAD events affect USDCAD only ───────────────────────────────

class TestCADEvents:
    def test_cad_beat_usdcad_sell(self):
        """CAD BEAT = CAD strengthens = SELL USDCAD (CAD is quote, stronger = price falls)."""
        assert get_preflight_signal("CAD", "BEAT", "USDCAD") == "SELL"

    def test_cad_miss_usdcad_buy(self):
        assert get_preflight_signal("CAD", "MISS", "USDCAD") == "BUY"

    def test_cad_beat_gbpusd_none(self):
        assert get_preflight_signal("CAD", "BEAT", "GBPUSD") is None


# ── Affected pair filtering ──────────────────────────────────────

class TestAffectedPairs:
    def test_usd_affects_all(self):
        for pair in ["GBPUSD", "EURUSD", "USDJPY", "USDCAD"]:
            assert is_pair_affected("USD", pair) is True

    def test_gbp_affects_gbpusd_only(self):
        assert is_pair_affected("GBP", "GBPUSD") is True
        assert is_pair_affected("GBP", "EURUSD") is False
        assert is_pair_affected("GBP", "USDJPY") is False
        assert is_pair_affected("GBP", "USDCAD") is False

    def test_eur_affects_eurusd_only(self):
        assert is_pair_affected("EUR", "EURUSD") is True
        assert is_pair_affected("EUR", "GBPUSD") is False

    def test_jpy_affects_usdjpy_only(self):
        assert is_pair_affected("JPY", "USDJPY") is True
        assert is_pair_affected("JPY", "GBPUSD") is False

    def test_cad_affects_usdcad_only(self):
        assert is_pair_affected("CAD", "USDCAD") is True
        assert is_pair_affected("CAD", "GBPUSD") is False

    def test_unknown_currency_affects_nothing(self):
        assert is_pair_affected("CHF", "GBPUSD") is False
        assert is_pair_affected("AUD", "EURUSD") is False


# ── Case insensitivity ──────────────────────────────────────────

class TestCaseInsensitivity:
    def test_lowercase_currency(self):
        assert get_preflight_signal("usd", "BEAT", "GBPUSD") == "SELL"

    def test_lowercase_beat_miss(self):
        assert get_preflight_signal("USD", "beat", "GBPUSD") == "SELL"

    def test_lowercase_symbol(self):
        assert get_preflight_signal("USD", "BEAT", "gbpusd") == "SELL"

    def test_all_lowercase(self):
        assert get_preflight_signal("gbp", "miss", "gbpusd") == "SELL"

    def test_affected_lowercase(self):
        assert is_pair_affected("gbp", "gbpusd") is True


# ── Mapping table completeness ───────────────────────────────────

class TestMappingCompleteness:
    def test_all_currencies_have_beat_and_miss(self):
        currencies = {"USD", "GBP", "EUR", "JPY", "CAD"}
        for ccy in currencies:
            assert (ccy, "BEAT") in _PREFLIGHT_DIRECTION, f"Missing ({ccy}, BEAT)"
            assert (ccy, "MISS") in _PREFLIGHT_DIRECTION, f"Missing ({ccy}, MISS)"

    def test_all_currencies_in_affected_pairs(self):
        for ccy in ["USD", "GBP", "EUR", "JPY", "CAD"]:
            assert ccy in _AFFECTED_PAIRS, f"Missing {ccy} in _AFFECTED_PAIRS"

    def test_direction_values_are_buy_or_sell(self):
        for key, mapping in _PREFLIGHT_DIRECTION.items():
            for pair, signal in mapping.items():
                assert signal in ("BUY", "SELL"), f"Invalid signal {signal} for {key}/{pair}"
