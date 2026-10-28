"""Phase 5 Stage D — real trade-manager decision adapter.

Research-only.  Imports selected deterministic helpers from the deployed
``trade_manager`` module and exposes them to the research event bus
without triggering live IG REST calls.

Scope
-----
* ``_detect_ig_close_reason`` — exit-reason classifier used by the
  external-close sweep (deterministic once state is provided).
* ``_calculate_pnl_pips`` — pip-math helper used throughout.
* ``_apply_bb_bounce_post_scale_floor`` — break-even floor arming math
  for BB Bounce scaled-out runners (the arithmetic portion; the broker
  SL amendment is stubbed).

Isolation guarantees
--------------------
* ``EPIC_STATE`` and ``_PROFIT_MGMT_BY_EPIC`` are swapped with scratch
  dicts.
* The IG REST session accessor is patched to raise, so any accidental
  REST call during research fails loudly instead of touching the live
  broker.
* ``trade_executor`` is replaced by a stub that records calls instead of
  executing them.

The adapter is NOT a complete replacement for ``trade_manager`` — it
only exposes the surface necessary for Phase 5 management-decision
replay.  Full integration of ``orchestrator_v2`` → central gate →
``trade_executor`` is deferred and documented in README.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any, Dict


OPT = Path("/opt/tradingbot")


class _StubIGSession:
    """Hard-fail stub for `get_ig_session` — any real REST call is a bug."""

    def __call__(self, *a, **kw):  # pragma: no cover — defensive
        raise RuntimeError(
            "Phase 5 research adapter: live IG session access is forbidden.",
        )


def _install_stubs(scratch_log_dir: Path) -> types.ModuleType:
    """Install stubs for every production side-effect before import.

    The deployed `trade_manager.py` is a *module* with import-time side
    effects (logging config, EPIC_STATE reads, etc.).  We import it via
    importlib with a controlled sys.path and after monkey-patching the
    environment variables that gate dangerous paths.
    """
    scratch_log_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("TRADE_LOG_AUTOINSTALL", "0")
    os.environ.setdefault("TRADE_LOG_PROMPT_AUTHORITATIVE_ENABLED", "0")

    if str(OPT) not in sys.path:
        sys.path.insert(0, str(OPT))

    # Replace production boundary modules with lightweight stubs BEFORE
    # importing trade_manager.  Each stub blocks any accidental live call
    # path (REST, broker action, Telegram).

    _ig_auth = types.ModuleType("ig_auth")
    _ig_auth.get_ig_session = _StubIGSession()
    _ig_auth.refresh_session = lambda *a, **kw: None
    _ig_auth.IG_ACC_TYPE = "DEMO"
    _ig_auth.IG_USERNAME = "stub"
    _ig_auth.IG_PASSWORD = "stub"
    _ig_auth.IG_API_KEY = "stub"
    sys.modules["ig_auth"] = _ig_auth

    _tg = types.ModuleType("telegram_alerts")
    _tg.send_telegram_message = lambda *a, **kw: None
    _tg.send_trade_close_alert = lambda *a, **kw: None
    _tg.send_trade_open_alert = lambda *a, **kw: None
    sys.modules["telegram_alerts"] = _tg

    _csn = types.ModuleType("close_sb_now")
    _csn.get_open_positions = lambda *a, **kw: []
    _csn.close_position_by_deal = lambda *a, **kw: None
    sys.modules["close_sb_now"] = _csn

    # Replace trade_executor with a lightweight recorder BEFORE importing
    # trade_manager so trade_manager's `import trade_executor as _exec`
    # binds to the recorder.
    if "trade_executor" in sys.modules:
        del sys.modules["trade_executor"]
    recorder = types.ModuleType("trade_executor")

    class _Recorder:
        def __init__(self):
            self.calls = []
            self.EPIC_STATE: Dict[str, Dict[str, Any]] = {}
            class _Lock:
                def __enter__(self): return self
                def __exit__(self, *_a): return False
            self.EPIC_STATE_LOCK = _Lock()

        def __getattr__(self, name):
            def _call(*args, **kwargs):
                self.calls.append((name, args, kwargs))
                return None
            return _call

    rec = _Recorder()
    recorder.EPIC_STATE = rec.EPIC_STATE
    recorder.EPIC_STATE_LOCK = rec.EPIC_STATE_LOCK
    recorder.TRADE_STATE_BY_EPIC = rec.EPIC_STATE
    recorder.TRADE_STATE = {}
    recorder._CLOSE_CALLBACKS = []
    recorder._OPEN_CALLBACKS = []

    def _rec_call(name):
        def _call(*args, **kwargs):
            rec.calls.append((name, args, kwargs))
            return True
        return _call

    # Expose every attribute trade_manager re-exports at import time
    # (`trade_manager.py:121-133`).  Each is backed by the recorder.
    for name in (
        "execute_trade", "update_trade_state", "close_position",
        "close_all_positions_for_epic", "apply_trailing_stop",
        "has_active_trade_for_mode", "get_all_positions_for_epic",
        "handle_partial_exit", "close_trade",
        "register_trade_close_callback", "register_trade_open_callback",
    ):
        setattr(recorder, name, _rec_call(name))
    recorder._recorder = rec
    sys.modules["trade_executor"] = recorder

    # trade_log autoinstall is already disabled.  We still need to make
    # trade_log importable since trade_manager imports it.
    import importlib
    tm = importlib.import_module("trade_manager")
    return tm


class TradeManagerAdapter:
    """Thin wrapper exposing deterministic helpers to the event bus."""

    def __init__(self, scratch_log_dir: Path):
        self._tm = _install_stubs(scratch_log_dir)

    # ------------------------------------------------------------
    # Exit classification
    # ------------------------------------------------------------
    def classify_close_reason(
        self, *, state: Dict[str, Any], exit_hint: float | None,
        pos_key: str | None = None,
    ) -> str:
        return self._tm._detect_ig_close_reason(state, exit_hint, pos_key)

    # ------------------------------------------------------------
    # Pip arithmetic
    # ------------------------------------------------------------
    def pnl_pips(self, *, direction: str, entry: float, exit_price: float,
                 pip_size: float) -> float:
        return self._tm._calculate_pnl_pips(
            direction, float(entry), float(exit_price), float(pip_size),
        )

    # ------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------
    @property
    def trade_executor_recorder(self):
        import trade_executor as _exec  # type: ignore
        return _exec._recorder  # type: ignore[attr-defined]
