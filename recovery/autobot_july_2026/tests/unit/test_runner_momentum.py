"""Parity tests for runner_momentum.

Locks the byte-identical guarantee against the pre-2026-07-27 inline
logic in gbpusd_trend_v3.py (_m1_aligned and
_macd_hist_last_and_contracting). The oracle functions in this file
are verbatim copies of those blocks; the shared helpers must produce
the same result on a fixed input matrix.

Also covers evaluate_runner_verdict — the shadow/enforce entry point.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple

import pytest

from runner_momentum import (
    evaluate_runner_verdict,
    m1_aligned,
    macd_hist_last_and_contracting,
)


# ─── Oracle: verbatim copy of gbpusd_trend_v3._m1_aligned (pre-2026-07-27).
def _oracle_m1_aligned(direction: str, macd_hist):
    if macd_hist is None:
        return None
    try:
        h = float(macd_hist)
    except (TypeError, ValueError):
        return None
    if direction == "LONG":
        return h > 0.0
    if direction == "SHORT":
        return h < 0.0
    return None


# ─── Oracle: verbatim copy of _macd_hist_last_and_contracting.
def _oracle_macd_hist_last_and_contracting(df_5m: Any) -> Tuple[Optional[float], Optional[bool]]:
    try:
        col = "MACD_HIST_35_45_30"
        if df_5m is None or col not in df_5m.columns or len(df_5m) < 2:
            return None, None
        last = float(df_5m[col].iloc[-1])
        prev = float(df_5m[col].iloc[-2])
        if math.isnan(last) or math.isnan(prev):
            return None, None
        return last, (abs(last) < abs(prev))
    except Exception:
        return None, None


# ─── m1_aligned: fixed-input matrix ────────────────────────────────────────
_M1_CASES = [
    # (direction, macd_hist, expected)
    ("LONG",   0.0025, True),
    ("LONG",  -0.0025, False),
    ("LONG",   0.0,   False),   # zero = not aligned
    ("SHORT",  0.0025, False),
    ("SHORT", -0.0025, True),
    ("SHORT",  0.0,   False),
    ("LONG",   None,  None),    # undecidable
    ("SHORT",  None,  None),
    ("LONG",   "bad", None),    # non-numeric -> None
    ("NEUTRAL", 0.5,  None),    # unknown direction -> None
    ("long",   0.5,   None),    # case-sensitive for LONG/SHORT semantics
    ("short",  -0.5,  None),
]


@pytest.mark.parametrize("direction,hist,expected", _M1_CASES)
def test_m1_aligned_byte_identical_to_oracle(direction, hist, expected):
    got = m1_aligned(direction, hist)
    want = _oracle_m1_aligned(direction, hist)
    assert got == want, f"dir={direction!r} hist={hist!r} got={got!r} oracle={want!r}"
    # Only the LONG/SHORT/None/malformed cases are locked to the oracle.
    # The extra BUY/SELL synonyms are new — separate test below.
    if direction in ("LONG", "SHORT") or hist is None or direction not in ("LONG", "SHORT", "BUY", "SELL"):
        assert got == expected


def test_m1_aligned_buy_sell_synonyms_new_behaviour():
    # New in 2026-07-27: universal shadow/enforce path uses BUY/SELL tokens.
    assert m1_aligned("BUY",  0.001) is True
    assert m1_aligned("BUY", -0.001) is False
    assert m1_aligned("SELL", 0.001) is False
    assert m1_aligned("SELL", -0.001) is True
    # Zero counts as not aligned (same rule as LONG/SHORT).
    assert m1_aligned("BUY",  0.0) is False
    assert m1_aligned("SELL", 0.0) is False


# ─── macd_hist_last_and_contracting: pandas-fake fixtures ──────────────────
class _FakeSeries:
    def __init__(self, values):
        self._v = list(values)

    class _iloc:
        def __init__(self, outer):
            self._outer = outer

        def __getitem__(self, idx):
            return self._outer._v[idx]

    @property
    def iloc(self):
        return _FakeSeries._iloc(self)


class _FakeDF:
    def __init__(self, cols):
        self._cols = dict(cols)  # {col_name: [values...]}

    @property
    def columns(self):
        return list(self._cols.keys())

    def __len__(self):
        if not self._cols:
            return 0
        return len(next(iter(self._cols.values())))

    def __getitem__(self, col):
        return _FakeSeries(self._cols[col])


_MH_CASES = [
    # (col_values, expected_last, expected_contracting, tag)
    ([0.001, 0.002, 0.003], 0.003, False, "expanding_up"),
    ([0.003, 0.002, 0.001], 0.001, True,  "contracting_shrinking"),
    ([-0.003, -0.002, -0.001], -0.001, True, "neg_shrinking"),
    ([0.001, -0.001], -0.001, False, "flipped_same_mag"),
    ([0.0, 0.0], 0.0, False, "flat_zero"),
    ([float("nan"), 0.001], None, None, "prev_nan"),
    ([0.001, float("nan")], None, None, "last_nan"),
]


@pytest.mark.parametrize("vals,exp_last,exp_ctr,tag", _MH_CASES)
def test_macd_hist_last_and_contracting_byte_identical_to_oracle(vals, exp_last, exp_ctr, tag):
    df = _FakeDF({"MACD_HIST_35_45_30": vals, "close": [1.0] * len(vals)})
    got = macd_hist_last_and_contracting(df)
    oracle = _oracle_macd_hist_last_and_contracting(df)
    assert got == oracle, f"[{tag}] got={got} oracle={oracle}"
    assert got == (exp_last, exp_ctr), f"[{tag}] got={got} expected=({exp_last},{exp_ctr})"


def test_macd_hist_missing_col_returns_nones():
    df = _FakeDF({"close": [1.0, 1.0, 1.0]})
    assert macd_hist_last_and_contracting(df) == (None, None)
    assert _oracle_macd_hist_last_and_contracting(df) == (None, None)


def test_macd_hist_none_frame_returns_nones():
    assert macd_hist_last_and_contracting(None) == (None, None)
    assert _oracle_macd_hist_last_and_contracting(None) == (None, None)


def test_macd_hist_short_frame_returns_nones():
    df = _FakeDF({"MACD_HIST_35_45_30": [0.001]})  # len 1 < 2
    assert macd_hist_last_and_contracting(df) == (None, None)


# ─── evaluate_runner_verdict — universal shadow/enforce entry point ────────
def test_evaluate_verdict_hold_when_aligned_long():
    v = evaluate_runner_verdict("BUY", 0.002)
    assert v["verdict"] == "HOLD"
    assert v["aligned"] is True
    assert v["macd_hist"] == 0.002
    assert v["direction"] == "BUY"
    assert "m1_aligned" in v["reason"]


def test_evaluate_verdict_would_exit_when_flipped_long():
    v = evaluate_runner_verdict("BUY", -0.002)
    assert v["verdict"] == "WOULD_EXIT"
    assert v["aligned"] is False
    assert "m1_flipped" in v["reason"]


def test_evaluate_verdict_hold_when_undecidable_defaults_safe():
    # macd_hist=None -> HOLD (fail-safe, never trigger a WOULD_EXIT on
    # missing data).
    v = evaluate_runner_verdict("BUY", None)
    assert v["verdict"] == "HOLD"
    assert v["aligned"] is None
    assert "m1_undecidable" in v["reason"]


def test_evaluate_verdict_short_side():
    assert evaluate_runner_verdict("SELL", -0.001)["verdict"] == "HOLD"
    assert evaluate_runner_verdict("SELL",  0.001)["verdict"] == "WOULD_EXIT"


def test_evaluate_verdict_trend_v3_tokens_unchanged():
    # LONG/SHORT tokens must yield the same verdicts as BUY/SELL — this
    # is what proves TREND_V3's monitor_exits stays byte-identical after
    # the extraction.
    assert evaluate_runner_verdict("LONG",  0.002)["verdict"] == "HOLD"
    assert evaluate_runner_verdict("LONG", -0.002)["verdict"] == "WOULD_EXIT"
    assert evaluate_runner_verdict("SHORT", 0.002)["verdict"] == "WOULD_EXIT"
    assert evaluate_runner_verdict("SHORT",-0.002)["verdict"] == "HOLD"
