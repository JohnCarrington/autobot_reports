import logging
import inspect
import strategy_logic


def test_strategy_logic_imports_successful():
    assert strategy_logic is not None


def test_strategy_logic_public_api_exists():
    """Only StrategyDecision and evaluate_signals are the core public API."""
    assert hasattr(strategy_logic, "StrategyDecision")
    assert hasattr(strategy_logic, "evaluate_signals")
    assert callable(strategy_logic.evaluate_signals)


def test_strategy_logic_no_removed_api():
    """These symbols were removed and must not exist."""
    assert not hasattr(strategy_logic, "StrategyConfig")
    assert not hasattr(strategy_logic, "compute_indicators")
    assert not hasattr(strategy_logic, "detect_market_regime")
    assert not hasattr(strategy_logic, "determine_entry_signal")
    assert not hasattr(strategy_logic, "bollinger_bands")
    assert not hasattr(strategy_logic, "strategy_decision")
    assert not hasattr(strategy_logic, "config")


def test_strategydecision_has_expected_fields():
    from strategy_logic import StrategyDecision
    fields = StrategyDecision.__dataclass_fields__
    expected = [
        "symbol", "regime", "signal", "mode", "entry", "sl", "tp",
        "use_trailing_stop", "reason", "debug", "size", "pip_size",
    ]
    for name in expected:
        assert name in fields, f"StrategyDecision missing field {name}"


def test_strategydecision_construction():
    from strategy_logic import StrategyDecision
    decision = StrategyDecision(
        symbol="EURUSD",
        regime="RANGE",
        signal="HOLD",
        mode="RANGE",
        entry=None,
        sl=None,
        tp=None,
        use_trailing_stop=False,
        reason="reason",
        debug={"test": 1},
    )
    assert decision.symbol == "EURUSD"
    assert decision.regime == "RANGE"
    assert decision.signal == "HOLD"
    assert decision.mode == "RANGE"
    assert decision.entry is None
    assert decision.sl is None
    assert decision.tp is None
    assert decision.use_trailing_stop is False
    assert decision.reason == "reason"
    assert isinstance(decision.debug, dict)


def test_evaluate_signals_signature():
    sig = inspect.signature(strategy_logic.evaluate_signals)
    params = list(sig.parameters.keys())
    # First required positional params
    assert "symbol" in params
    assert "epic" in params
    assert "bid" in params
    assert "ask" in params


def test_strategy_logic_logger_exists():
    assert hasattr(strategy_logic, "logger")
    assert isinstance(strategy_logic.logger, logging.Logger)
    assert strategy_logic.logger.name == "AutoBot"
