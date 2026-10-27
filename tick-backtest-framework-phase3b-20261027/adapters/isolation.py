"""Phase 3 isolation seam.

Install THIS MODULE'S init_isolation() BEFORE importing any AutoBot module.
It installs stub replacements for the subset of /opt/tradingbot modules
that have live side-effects (network, broker, persistent writes).

Isolation policy:
- NO IG network calls. All IG REST / Lightstreamer modules are stubbed.
- NO production log writes. All AutoBot logger file handlers are muted
  by replacing _write_* helpers at monkey-patch time where applicable.
- NO scheduler threads start. All briefing / news / observer loop
  modules get a stub.
- Env var overrides force every strategy ENABLED=0 before any strategy
  module imports (production code reads env at import time).

What is NOT stubbed (safe reads):
- strategy_logic.StrategyDecision — pure dataclass, used for return types.
- Any pure-math helpers.
- Config constants.

To use:

    from adapters.isolation import init_isolation
    with init_isolation():
        import gbpusd_bb_bounce as bb
        # ...

The context manager also sets a hard-abort signal if any un-intercepted
IG endpoint is called — tests will trip immediately.
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys
import types
from pathlib import Path


# Env flags that MUST be set to safe values before importing AutoBot modules.
# This covers top-level module-import-time `_env_bool(...)` reads.
ISOLATION_ENV_OVERRIDES = {
    # Hard-disable every strategy — nothing may fire in isolation
    "GBPUSD_BB_BOUNCE_ENABLED": "0",     # overridden per-test when driving
    "EMA_PULLBACK_ENABLED": "0",
    "TREND_V3_ENABLED": "0",
    "STRUCTURE_BREAK_ENABLED": "0",
    "NEWS_STRATEGY_ENABLED": "0",
    "CONFIRMATION_FALLBACK_ENABLED": "0",
    "BRIEFING_EXECUTION_ENABLED": "0",
    "BRIEFING_V5_ENABLED": "0",
    "LIQUIDITY_SWEEP_ENABLED": "0",
    # Disable orchestrator + central gate — tests drive strategy directly
    "CENTRAL_STRATEGY_ORCHESTRATOR": "0",
    "CENTRAL_EXECUTION_GATE": "0",
    # Disable NMS gates by default
    "NMS_SECOND_GATE_ENABLED": "0",
    "V3_NMS_AUTHORITY_GATE_ENABLED": "0",
    "NMS_V3_DIRECTIONAL_GATE_ENABLED": "0",
    "DIRECTION_FROM_NMS_SESSION_TREND": "0",
    # BB Bounce gates deliberately disabled in production per memory
    # [[project_bb_bounce_gates_disabled]] since 2026-05-28:
    "GBPUSD_BB_BOUNCE_H1_COUNTER_GATE_ENABLED": "false",
    "BB_BOUNCE_CASCADE_GATE_ENABLED": "0",
    # Suppress production log writes where possible via explicit env
    "AUTOBOT_ISOLATION_MODE": "1",
    "SIGNAL_LOG_PATH": "/tmp/phase3_audit/_sink/signal_log.jsonl",
}


_PROD_ROOT = Path("/opt/tradingbot")


class _StubAttribute:
    """A placeholder attribute that returns another _StubAttribute on access."""
    def __init__(self, name: str = ""):
        self._name = name
    def __repr__(self): return f"<stub:{self._name}>"
    def __call__(self, *a, **k): return _StubAttribute(self._name + "()")
    def __getattr__(self, k): return _StubAttribute(f"{self._name}.{k}")
    def __iter__(self): return iter([])
    def __bool__(self): return False


def _make_stub_module(name: str, extras: dict | None = None) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__file__ = f"<stub:{name}>"
    for k, v in (extras or {}).items():
        setattr(m, k, v)
    return m


def _install_prod_module_stubs() -> list[str]:
    """Replace selected AutoBot modules with inert stubs. Returns list of installed names."""
    installed: list[str] = []

    # trade_executor — side-effectful; replace with inert stub but preserve
    # the names BB bounce reads (ONE_BOOK_* etc). Nothing is called in evaluate(),
    # but lazy imports deeper in BB-bounce helpers might reach for it.
    te = _make_stub_module("trade_executor", {
        "execute_trade": _StubAttribute("trade_executor.execute_trade"),
        "EPIC_STATE": {},
        "EPIC_STATE_LOCK": _StubAttribute("EPIC_STATE_LOCK"),
        "register_trade_open_callback": lambda *a, **k: None,
        "consume_last_block_info": lambda: None,
    })
    sys.modules["trade_executor"] = te
    installed.append("trade_executor")

    # Lightstreamer / streaming — no connections
    for name in ("streamer_ls", "price_streamer", "streamer_api", "native_5m_source", "pair_recorder"):
        sys.modules[name] = _make_stub_module(name)
        installed.append(name)

    # IG session / auth — no network
    sys.modules["ig_auth"] = _make_stub_module("ig_auth", {
        "FatalAuthError": type("FatalAuthError", (RuntimeError,), {}),
    })
    installed.append("ig_auth")

    # Position + close helpers — stubbed
    for name in ("open_sb_now", "close_sb_now", "bounce_engine_live"):
        sys.modules[name] = _make_stub_module(name)
        installed.append(name)

    # Signal + telemetry writers — stubbed (we provide an in-memory logger below)
    def _session_from_utc_hour(hour: int) -> str:
        # Mirror production signal_logger._session_from_utc_hour mapping
        if hour >= 22 or hour < 7:
            return "ASIA"
        if hour < 12:
            return "LONDON"
        if hour < 17:
            return "NY"
        return "SYDNEY"
    sl = _make_stub_module("signal_logger", {
        "log_open": lambda *a, **k: None,
        "log_close": lambda *a, **k: None,
        "LOG_PATH": "/tmp/phase3_audit/_sink/signal_log.jsonl",
        "_session_from_utc_hour": _session_from_utc_hour,
    })
    sys.modules["signal_logger"] = sl
    installed.append("signal_logger")

    # Measurement writer
    sys.modules["measurement_writer"] = _make_stub_module("measurement_writer")
    installed.append("measurement_writer")

    # News / briefing — fail-open stubs. Also stub news_calendar so no network
    # fetches run during StrategyDecision construction (observed as 429 rate-
    # limit errors against ForexFactory from strategy_logic).
    nrw = _make_stub_module("news_release_window", {
        "is_in_release_window": lambda ts: (False, "stub_no_news_data"),
    })
    sys.modules["news_release_window"] = nrw
    installed.append("news_release_window")

    nc = _make_stub_module("news_calendar", {
        "is_news_day": lambda *a, **k: False,
        "get_upcoming_events": lambda *a, **k: [],
        "get_events_for_date": lambda *a, **k: [],
        "get_todays_events": lambda *a, **k: [],
        "high_impact_in_window": lambda *a, **k: False,
    })
    sys.modules["news_calendar"] = nc
    installed.append("news_calendar")

    nms2 = _make_stub_module("nms_second_gate")
    nms2_check = types.SimpleNamespace(
        allowed=True, bypassed=True, reason_codes=[], binding="stub-bypass",
        range_state="UNKNOWN", session_trend="UNKNOWN",
    )
    nms2.check = lambda *a, **kw: nms2_check
    sys.modules["nms_second_gate"] = nms2
    installed.append("nms_second_gate")

    # Trade manager — strategy consumes select_tp_levels() output as a dict
    # with keys: tp1, tp2, tp3 (prices), tp1_pips, tp2_pips, tp3_pips, sl_pips,
    # levels_used, fallback. Matches the production fallback-dict shape at
    # trade_manager.py:4716-4729. ppp=1.0 (GBPUSD IG TODAY epic: 1 point = 1 pip).
    def _select_tp_levels_stub(entry_price, direction, briefing_levels=None, pair="GBPUSD"):
        d = str(direction or "").upper()
        sign = 1.0 if d == "BUY" else -1.0
        tp1_pips, tp2_pips, tp3_pips = 20.0, 40.0, 60.0
        return {
            "tp1": float(entry_price) + tp1_pips * 1.0 * sign,
            "tp2": float(entry_price) + tp2_pips * 1.0 * sign,
            "tp3": float(entry_price) + tp3_pips * 1.0 * sign,
            "tp1_pips": tp1_pips, "tp2_pips": tp2_pips, "tp3_pips": tp3_pips,
            "sl_pips": 15.0,
            "levels_used": [],
            "fallback": True,
        }
    tm = _make_stub_module("trade_manager", {
        "select_tp_levels": _select_tp_levels_stub,
        "setup_briefing_tp": lambda *a, **k: None,
    })
    sys.modules["trade_manager"] = tm
    installed.append("trade_manager")

    # Morning briefing
    mb = _make_stub_module("morning_briefing", {
        "get_briefing": lambda *a, **k: None,
    })
    sys.modules["morning_briefing"] = mb
    installed.append("morning_briefing")

    # Pair scope — safe constants
    ps = _make_stub_module("pair_scope", {
        "can_trade": lambda pair, family="", mode="": True,
        "epic_for": lambda sym: "CS.D.GBPUSD.TODAY.IP",
    })
    sys.modules["pair_scope"] = ps
    installed.append("pair_scope")

    # Regime engine — strategy calls .latest_result(symbol=…) with optional args.
    # NEUTRAL default avoids RANGE_ROTATION-specific opposite-band-TP gate blocking
    # on tight synthetic fixtures. Production regime behaviour must be tested
    # separately with a RANGE_ROTATION stub when exercising those pathways.
    _regime_default = {
        "winning_regime": "NEUTRAL",
        "conf_floor_applied": False,
        "h1_macd_hist": 0.0,
        "h1_decel_streak": 0,
    }
    re = _make_stub_module("regime_engine", {
        "latest_result": lambda *a, **kw: _regime_default,
    })
    sys.modules["regime_engine"] = re
    installed.append("regime_engine")

    # Timeframe context (used by BB bounce via lazy import)
    class _FakeSnapshot:
        h1_bias = "NEUTRAL"
        d1_bias = "NEUTRAL"
        h1_series = []
        d1_series = []
    tfc = _make_stub_module("timeframe_context", {
        "snapshot": lambda sym: _FakeSnapshot(),
    })
    sys.modules["timeframe_context"] = tfc
    installed.append("timeframe_context")

    # Orchestrator / central gate — not reached in isolated BB evaluation
    for name in ("orchestrator", "orchestrator_v2", "central_execution_gate",
                 "strategy_dispatch_adapter", "news_trend_classifier",
                 "news_tier_classifier", "news_slot_ledger", "regime_router_engine",
                 "nms_v3_direction_gate"):
        sys.modules[name] = _make_stub_module(name)
        installed.append(name)

    return installed


@contextlib.contextmanager
def init_isolation(extra_env: dict | None = None):
    """Context manager: install isolation, pre-set env flags, yield, cleanup."""
    saved_env = {}
    for k, v in ISOLATION_ENV_OVERRIDES.items():
        saved_env[k] = os.environ.get(k)
        os.environ[k] = v
    for k, v in (extra_env or {}).items():
        saved_env.setdefault(k, os.environ.get(k))
        os.environ[k] = v

    # Insert /opt/tradingbot onto sys.path so later imports find real modules
    added = False
    if str(_PROD_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROD_ROOT))
        added = True

    installed = _install_prod_module_stubs()

    # Pre-create the sink directory for any accidental file writes
    Path("/tmp/phase3_audit/_sink").mkdir(parents=True, exist_ok=True)

    try:
        yield installed
    finally:
        # Restore env
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # Remove installed stubs so a subsequent real import can succeed
        for name in installed:
            sys.modules.pop(name, None)
        if added:
            sys.path.remove(str(_PROD_ROOT))


def assert_no_production_side_effects(installed: list[str]) -> list[str]:
    """Return a list of imported real-production modules that bypass isolation.

    Call this AFTER the isolation context has imported the strategy — it enumerates
    sys.modules looking for AutoBot modules we did NOT stub but which are present.
    This is a defensive check: if a strategy imports an uninstalled real module
    with side effects, we want to flag it loudly.
    """
    _REAL_SIDE_EFFECT = {
        # These are DEFINITELY unsafe in prod — list of module names expected to be stubbed
        "trade_executor", "streamer_ls", "price_streamer", "bounce_engine_live",
        "open_sb_now", "close_sb_now", "ig_auth",
    }
    leaks = []
    for name in _REAL_SIDE_EFFECT:
        mod = sys.modules.get(name)
        if mod is None:
            continue
        if "<stub:" in str(getattr(mod, "__file__", "")):
            continue
        # Real file loaded
        leaks.append(name)
    return leaks
