"""
Unit tests for autobot.py

Production API:
- main() is the only public function
- _rest_preload_symbol() is private
- No initialize(), no preload_symbol()
- Uses module-level functions from telegram_alerts (send_status_update, etc.)
- Uses ig_auth.get_ig_session for IG connection
"""


def test_main_is_callable():
    """autobot.main exists and is callable."""
    import autobot
    assert callable(autobot.main)


def test_no_initialize_function():
    """autobot does NOT export an initialize() function."""
    import autobot
    assert not hasattr(autobot, "initialize") or not callable(getattr(autobot, "initialize", None))


def test_no_public_preload_symbol():
    """autobot does NOT export a public preload_symbol() function."""
    import autobot
    assert not hasattr(autobot, "preload_symbol")


def test_has_private_rest_preload_symbol():
    """autobot has a private _rest_preload_symbol() function."""
    import autobot
    assert hasattr(autobot, "_rest_preload_symbol")
    assert callable(autobot._rest_preload_symbol)


def test_imports_send_status_update():
    """autobot imports send_status_update from telegram_alerts (module-level function)."""
    import autobot
    # It should use the module-level function, not a TelegramBot class
    assert hasattr(autobot, "send_status_update")
    assert callable(autobot.send_status_update)


def test_imports_get_ig_session():
    """autobot imports get_ig_session from ig_auth."""
    import autobot
    assert hasattr(autobot, "get_ig_session")
    assert callable(autobot.get_ig_session)
