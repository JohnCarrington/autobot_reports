"""
Regression tests locking in the removal of MACD crossover exits.

The v4 BB_REVERSAL rebuild deleted evaluate_macd_exit and
check_bb_reversal_macd_exit. Phase 3 cleanup then removed the stale
autobot registration block and the stale comments in trade_manager.py
and trade_executor.py.

These tests exist so a future edit that re-introduces MACD crossover as
a close trigger fails fast in CI.

Scope (matches the scope the spec explicitly confirmed):
  - IN: MACD as an EXIT trigger (crossover / zero-cross that closes a
    position)
  - OUT: MACD as an entry filter (ema_pullback, briefing_liquidity, etc.)
  - OUT: MACD histogram HOLD/CLOSE decision in check_momentum at TP1/TP2
    — always closes at a TP price, not a crossover exit
  - OUT: MACD as the v4 tighter_filter stub (returns True unconditionally)
  - OUT: MACD display/logging/regime classification
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path("/opt/tradingbot")
EXIT_DECISION_FILES = [
    REPO_ROOT / "trade_manager.py",
    REPO_ROOT / "trade_executor.py",
    REPO_ROOT / "bb_reversal.py",
    REPO_ROOT / "autobot.py",
]


def test_no_evaluate_macd_exit_symbol():
    """The evaluate_macd_exit function must not be defined or imported
    anywhere in the runtime exit-decision files."""
    offenders = []
    for p in EXIT_DECISION_FILES:
        text = p.read_text()
        if "evaluate_macd_exit" in text:
            offenders.append(str(p))
    assert not offenders, (
        f"evaluate_macd_exit must not appear in: {offenders}. "
        f"MACD crossover exits were removed in the v4 rebuild — do not "
        f"re-introduce them."
    )


def test_no_check_bb_reversal_macd_exit_symbol():
    """The check_bb_reversal_macd_exit callback must not be defined,
    imported, or registered anywhere."""
    offenders = []
    for p in EXIT_DECISION_FILES:
        text = p.read_text()
        if "check_bb_reversal_macd_exit" in text:
            offenders.append(str(p))
    assert not offenders, (
        f"check_bb_reversal_macd_exit must not appear in: {offenders}. "
        f"The MACD zero-cross exit callback is gone — do not re-register."
    )


def test_no_macd_crossover_or_zero_cross_phrase_in_exit_path():
    """Strict phrase guard: 'MACD' within 20 chars of ('crossover' or
    'zero-cross' or 'zero cross') within 40 chars of ('exit' or 'close')
    must not appear in the exit-decision files.

    Tuned to flag only the exit semantics — leaves entry-filter MACD
    refs, histogram momentum at TP levels, and display logging alone.
    """
    pattern = re.compile(
        r"macd.{0,20}(crossover|zero[-\s]?cross).{0,40}(exit|close)",
        re.IGNORECASE | re.DOTALL,
    )
    offenders = []
    for p in EXIT_DECISION_FILES:
        text = p.read_text()
        matches = pattern.findall(text)
        if matches:
            offenders.append((str(p), matches))
    assert not offenders, (
        f"MACD crossover/zero-cross exit phrasing re-appeared in "
        f"exit-decision paths: {offenders}. This phrase guard caught the "
        f"pattern — if the match is a false positive (e.g. a comment "
        f"describing what was removed), rephrase to keep the grep clean."
    )


def test_bb_reversal_has_no_macd_exit_public_api():
    """The BBReversalStrategy class must not expose a check_bb_reversal_
    macd_exit method, and the bb_reversal module must not expose
    evaluate_macd_exit / check_bb_reversal_macd_exit at the module level."""
    import bb_reversal

    assert not hasattr(bb_reversal, "evaluate_macd_exit"), (
        "bb_reversal.evaluate_macd_exit must not exist"
    )
    assert not hasattr(bb_reversal, "check_bb_reversal_macd_exit"), (
        "bb_reversal.check_bb_reversal_macd_exit must not exist"
    )
    assert not hasattr(bb_reversal.BBReversalStrategy, "check_bb_reversal_macd_exit"), (
        "BBReversalStrategy.check_bb_reversal_macd_exit method must not exist"
    )
    assert not hasattr(bb_reversal.BBReversalStrategy, "evaluate_macd_exit"), (
        "BBReversalStrategy.evaluate_macd_exit method must not exist"
    )


def test_autobot_startup_has_no_macd_exit_registration():
    """autobot.py must not contain the registration block that imported
    check_bb_reversal_macd_exit (which previously hit a swallowed
    ImportError at startup after v4 rebuild)."""
    text = (REPO_ROOT / "autobot.py").read_text()
    # Whole-block phrase
    assert "register BB_REVERSAL MACD exit" not in text, (
        "autobot.py still contains the MACD-exit registration log phrase"
    )
    assert "check_bb_reversal_macd_exit" not in text, (
        "autobot.py still imports or registers check_bb_reversal_macd_exit"
    )
