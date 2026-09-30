"""
Unit tests for strategy_logic.py

Production API:
- StrategyDecision dataclass
- evaluate_signals() function
- No StrategyConfig class
- No standalone compute_indicators() function
- No standalone bollinger_bands(), detect_market_regime(), determine_entry_signal(),
  strategy_decision(), _compute_sl_tp()
"""


def test_strategy_decision_exists():
    """StrategyDecision dataclass can be imported."""
    from strategy_logic import StrategyDecision
    assert StrategyDecision is not None


def test_strategy_decision_fields():
    """StrategyDecision has the expected fields."""
    from strategy_logic import StrategyDecision
    dec = StrategyDecision(
        symbol="EURUSD",
        regime="RANGE",
        signal="NONE",
        mode="DISPATCH",
        entry=None,
        sl=None,
        tp=None,
        use_trailing_stop=False,
        reason="test",
    )
    assert dec.symbol == "EURUSD"
    assert dec.regime == "RANGE"
    assert dec.signal == "NONE"
    assert dec.mode == "DISPATCH"
    assert dec.entry is None
    assert dec.sl is None
    assert dec.tp is None
    assert dec.use_trailing_stop is False
    assert dec.reason == "test"
    assert dec.debug == {}


def test_strategy_decision_optional_fields():
    """StrategyDecision has optional size and pip_size fields."""
    from strategy_logic import StrategyDecision
    dec = StrategyDecision(
        symbol="EURUSD",
        regime="RANGE",
        signal="BUY",
        mode="RANGE_REVERSION",
        entry=1.1,
        sl=12.0,
        tp=30.0,
        use_trailing_stop=True,
        reason="test",
        size=1.5,
        pip_size=1.0,
    )
    assert dec.size == 1.5
    assert dec.pip_size == 1.0


def test_evaluate_signals_exists():
    """evaluate_signals function exists and is callable."""
    from strategy_logic import evaluate_signals
    assert callable(evaluate_signals)


def test_no_strategy_config():
    """strategy_logic does NOT have a StrategyConfig class."""
    import strategy_logic
    assert not hasattr(strategy_logic, "StrategyConfig")


def test_no_standalone_compute_indicators():
    """strategy_logic does NOT have a standalone compute_indicators function."""
    import strategy_logic
    assert not hasattr(strategy_logic, "compute_indicators")


def test_no_standalone_bollinger_bands():
    """strategy_logic does NOT have a standalone bollinger_bands function."""
    import strategy_logic
    assert not hasattr(strategy_logic, "bollinger_bands")


def test_no_standalone_strategy_decision_function():
    """strategy_logic does NOT have a strategy_decision function (it's a dataclass)."""
    import strategy_logic
    # StrategyDecision is a dataclass, not a function named strategy_decision
    assert not hasattr(strategy_logic, "strategy_decision")


def test_detect_regime_exists():
    """detect_regime function exists (lightweight regime helper)."""
    import strategy_logic
    assert hasattr(strategy_logic, "detect_regime")
    assert callable(strategy_logic.detect_regime)
