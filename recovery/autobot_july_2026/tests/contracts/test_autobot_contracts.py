import inspect
import logging
import autobot


def test_autobot_imports_successful_and_logger():
    """Module should import and expose the shared AutoBot logger."""
    assert hasattr(autobot, "logger")
    assert isinstance(autobot.logger, logging.Logger)
    assert autobot.logger.name == "AutoBot"


def test_autobot_function_presence():
    """Core public entrypoints must exist and be callable."""
    assert hasattr(autobot, "main"), "autobot is missing main"
    assert callable(autobot.main), "main should be callable"


def test_autobot_main_signature():
    """main() should be a zero-arg entrypoint (no required parameters)."""
    sig = inspect.signature(autobot.main)
    for param in sig.parameters.values():
        assert (
            param.default is not param.empty
            or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD)
        ), "main() must not require any arguments"


def test_autobot_no_public_initialize():
    """autobot no longer exposes a public initialize() function."""
    assert not hasattr(autobot, "initialize")


def test_autobot_has_private_rest_preload():
    """_rest_preload_symbol is a private helper that must exist."""
    assert hasattr(autobot, "_rest_preload_symbol")
    assert callable(autobot._rest_preload_symbol)
