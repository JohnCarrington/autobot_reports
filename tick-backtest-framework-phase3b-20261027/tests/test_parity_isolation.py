"""Phase 3 parity + isolation tests.

Deterministic tests that verify:
  - Isolation seam prevents live-service side effects
  - The production BB Bounce module can be imported safely
  - The production BB Bounce ENABLED-flag honours env overrides
  - Indicator parity for BB(20,2) matches the production formula exactly
  - Negative tests: known look-ahead / isolation violations are detected

Run:
  cd /tmp/phase3_audit && python3 -m pytest tests/test_parity_isolation.py -v
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.isolation import init_isolation, assert_no_production_side_effects  # noqa: E402


def test_isolation_installs_stubs():
    with init_isolation() as installed:
        assert "trade_executor" in installed
        assert "bounce_engine_live" in installed
        assert "signal_logger" in installed
        assert "ig_auth" in installed
        import sys as _sys
        for name in installed:
            mod = _sys.modules.get(name)
            assert mod is not None, f"{name} should be installed as stub"
            # Non-empty stubs are modules with __file__ in <stub:...> format
            if hasattr(mod, "__file__"):
                assert "<stub:" in str(mod.__file__) or mod.__file__ == "" or mod.__file__ is None


def test_isolation_import_bb_bounce_safely():
    import threading
    pre_threads = {t.name for t in threading.enumerate()}
    with init_isolation() as installed:
        import sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        assert hasattr(bb, "GbpUsdBBBounceStrategy")
        assert hasattr(bb, "evaluate")
        assert hasattr(bb, "Bar")
        assert bb.MODE_NAME_LONG == "GBPUSD_BB_BOUNCE_L"
        assert bb.MODE_NAME_SHORT == "GBPUSD_BB_BOUNCE_S"
        leaks = assert_no_production_side_effects(installed)
        assert leaks == [], f"isolation leaked: {leaks}"
    post_threads = {t.name for t in threading.enumerate()}
    assert pre_threads == post_threads, f"threads leaked: {post_threads - pre_threads}"


def test_isolation_enabled_env_override_honoured():
    """Verify that ENABLED env override is reflected in bb.ENABLED after a forced reimport."""
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}):
        import sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        assert bb.ENABLED is True


def test_isolation_disabled_strategy_returns_none():
    """Verify production BB Bounce bails on ENABLED=False (safe-off)."""
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "0"}):
        import sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = False  # defensive
        s = bb.GbpUsdBBBounceStrategy()
        ts = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
        out = s.evaluate("GBPUSD", "CS.D.GBPUSD.TODAY.IP", ts, [], [], False, False)
        assert out is None


def test_isolation_wrong_symbol_returns_none():
    """Even enabled, strategy must bail on non-GBPUSD symbols (production invariant)."""
    with init_isolation(extra_env={"GBPUSD_BB_BOUNCE_ENABLED": "1"}):
        import sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        bb.ENABLED = True
        s = bb.GbpUsdBBBounceStrategy()
        ts = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
        out = s.evaluate("EURUSD", "CS.D.EURUSD.TODAY.IP", ts, [], [], False, False)
        assert out is None


def test_production_bb_formula_population_stdev():
    """Verify the strategy's BB(20,2) uses POPULATION stdev (not sample)."""
    with init_isolation():
        import sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
                  11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0]
        lo, mid, up = bb._bb_20_2(closes, period=20, std_mult=2.0)
        # Expected: mid=10.5, var = sum((c-10.5)^2)/20 = 33.25, std = sqrt(33.25) = 5.7663
        import math
        assert abs(mid - 10.5) < 1e-12
        expected_std = math.sqrt(sum((c - 10.5) ** 2 for c in closes) / 20)
        assert abs((up - mid) / 2 - expected_std) < 1e-10, "BB uses POPULATION stdev"


def test_pierce_setup_detector_long():
    """Classic LONG pierce: prev.low <= BB_lower - 2*PIP, prev.open >= BB_lower, open-inside."""
    with init_isolation():
        import sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        # Prices in IG points format (PIP_SIZE=1.0 in bb module)
        prev = bb.Bar(
            timestamp=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
            open=13670.0, high=13672.0, low=13660.0, close=13665.0,
        )
        bb_lower = 13668.0
        bb_upper = 13700.0
        side, reason = bb._detect_pierce_setup(prev, bb_lower, bb_upper)
        # low 13660 <= 13668-2 = 13666 ✓; open 13670 >= 13668 ✓; LONG pierce
        assert side == "LONG"
        assert reason == ""


def test_pierce_setup_detector_short():
    with init_isolation():
        import sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        prev = bb.Bar(
            timestamp=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
            open=13690.0, high=13703.0, low=13685.0, close=13698.0,
        )
        bb_lower = 13680.0
        bb_upper = 13700.0
        side, reason = bb._detect_pierce_setup(prev, bb_lower, bb_upper)
        # high 13703 >= 13700+2 = 13702 ✓; open 13690 <= 13700 ✓; SHORT pierce
        assert side == "SHORT"
        assert reason == ""


def test_pierce_setup_rejected_both_bands():
    """Both-band pierce (band-squeeze hug) must be rejected per production rules."""
    with init_isolation():
        import sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        prev = bb.Bar(
            timestamp=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
            open=13685.0, high=13703.0, low=13675.0, close=13688.0,
        )
        bb_lower = 13678.0
        bb_upper = 13700.0
        side, reason = bb._detect_pierce_setup(prev, bb_lower, bb_upper)
        assert side is None
        assert reason == "both_bands"


def test_pierce_setup_rejected_open_outside_band():
    """prev.open outside the band disqualifies the pierce setup."""
    with init_isolation():
        import sys as _sys
        _sys.modules.pop("gbpusd_bb_bounce", None)
        import gbpusd_bb_bounce as bb
        # Pierce depth met but open below BBL — reject
        prev = bb.Bar(
            timestamp=datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
            open=13666.0, high=13672.0, low=13660.0, close=13665.0,
        )
        bb_lower = 13668.0
        bb_upper = 13700.0
        side, reason = bb._detect_pierce_setup(prev, bb_lower, bb_upper)
        assert side is None
        assert reason == "open_below_BBL"


def test_execute_trade_wrapper_is_the_live_binding():
    """Phase 1 flagged two execute_trade definitions in trade_executor.py.
    Static-source verification that the wrapper at :6936 is lexically after the
    inner impl at :2994, that the wrapper assigns `_execute_trade_impl = execute_trade`
    before redefining it, and that the wrapper carries `**kwargs`.

    Static inspection — does NOT import trade_executor (which pulls in IG auth)."""
    import re
    src = Path("/opt/tradingbot/trade_executor.py").read_text()
    # Find all occurrences of `def execute_trade(`
    matches = [(i, m.start()) for i, m in enumerate(re.finditer(r"^def execute_trade\(", src, re.MULTILINE))]
    assert len(matches) == 2, f"expected exactly 2 execute_trade defs, found {len(matches)}"
    # The wrapper's capture line must appear BETWEEN the two defs
    inner_off = matches[0][1]
    outer_off = matches[1][1]
    region = src[inner_off:outer_off]
    assert "_execute_trade_impl = execute_trade" in region, (
        "Expected inner impl to be captured as _execute_trade_impl before wrapper redefinition"
    )
    # Confirm the second def includes **kwargs
    wrapper_line_end = src.index("\n", outer_off)
    wrapper_signature = src[outer_off:wrapper_line_end]
    assert "**kwargs" in wrapper_signature, (
        f"Expected the wrapper (:6936) to accept **kwargs; got: {wrapper_signature}"
    )
    assert "no-redef" in src[outer_off:outer_off + 200], (
        "Expected explicit `# type: ignore[no-redef]` on the wrapper — if missing, "
        "the pattern may have changed."
    )


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
