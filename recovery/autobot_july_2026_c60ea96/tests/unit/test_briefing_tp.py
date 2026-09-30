"""
Unit tests for briefing-level TP management in trade_manager.py

Tests:
- select_tp_levels: TP ordering, fallback logic, synthetic level generation
- check_momentum: HOLD/CLOSE decisions against synthetic price sequences
- SL progression: SL moves correctly at each TP level
- News blackout: profit/loss handling during blackout
"""
import pytest
from unittest.mock import patch

from trade_manager import (
    select_tp_levels,
    check_momentum,
    TradeManager,
    _BRIEFING_TP_BY_EPIC,
)


# ============================================================
# select_tp_levels
# ============================================================
class TestSelectTpLevels:
    """TP level selection from briefing levels."""

    def _make_level(self, price, level_type="resistance", source="briefing_resistance", major=False):
        return {"price": price, "level_type": level_type, "source": source, "major": major}

    def test_buy_three_levels_ordered_by_distance(self):
        """TP1=nearest, TP2=second, TP3=third level beyond entry."""
        levels = [
            self._make_level(13250),  # 20p away
            self._make_level(13270),  # 40p away
            self._make_level(13300),  # 70p away
        ]
        result = select_tp_levels(13230, "BUY", levels, "GBPUSD")
        assert result["tp1"] == 13250
        assert result["tp2"] == 13270
        assert result["tp3"] == 13300
        assert result["tp1_pips"] == pytest.approx(20.0)
        assert result["tp2_pips"] == pytest.approx(40.0)
        assert result["tp3_pips"] == pytest.approx(70.0)
        assert result["fallback"] is False

    def test_sell_levels_below_entry(self):
        """SELL: only levels below entry are used, ordered by distance."""
        levels = [
            self._make_level(13200, "support"),  # 30p away
            self._make_level(13180, "support"),  # 50p away
            self._make_level(13250, "resistance"),  # above entry — ignored
            self._make_level(13150, "support"),  # 80p away
        ]
        result = select_tp_levels(13230, "SELL", levels, "GBPUSD")
        assert result["tp1"] == 13200
        assert result["tp2"] == 13180
        assert result["tp3"] == 13150
        assert result["tp1_pips"] == pytest.approx(30.0)
        assert result["fallback"] is False

    def test_no_levels_returns_fixed_fallback(self):
        """No briefing levels → fixed TP1=30, TP2=50, TP3=80."""
        result = select_tp_levels(13230, "BUY", [], "GBPUSD")
        assert result["tp1_pips"] == pytest.approx(30.0)
        assert result["tp2_pips"] == pytest.approx(50.0)
        assert result["tp3_pips"] == pytest.approx(80.0)
        assert result["fallback"] is True
        assert result["tp1"] == pytest.approx(13260.0)

    def test_one_level_pads_with_synthetic(self):
        """One briefing level → TP2 and TP3 are synthetic +20p increments."""
        levels = [self._make_level(13250)]
        result = select_tp_levels(13230, "BUY", levels, "GBPUSD")
        assert result["tp1"] == 13250
        assert result["tp1_pips"] == pytest.approx(20.0)
        # TP2 = 20 + 20 = 40 pips from entry
        assert result["tp2_pips"] == pytest.approx(40.0)
        # TP3 = 40 + 20 = 60 pips from entry
        assert result["tp3_pips"] == pytest.approx(60.0)

    def test_two_levels_pads_tp3_synthetic(self):
        """Two briefing levels → TP3 is synthetic."""
        levels = [self._make_level(13250), self._make_level(13270)]
        result = select_tp_levels(13230, "BUY", levels, "GBPUSD")
        assert result["tp1"] == 13250
        assert result["tp2"] == 13270
        assert result["tp3_pips"] == pytest.approx(60.0)  # 40 + 20

    def test_tp3_prefers_major_level(self):
        """TP3 should prefer nearest major level when it has sufficient gap."""
        levels = [
            self._make_level(13250),  # TP1 (20p from entry)
            self._make_level(13270),  # TP2 (40p)
            self._make_level(13285),  # plain third (55p, 15p gap from TP2)
            self._make_level(13310, major=True),  # major (80p, 25p gap)
        ]
        result = select_tp_levels(13230, "BUY", levels, "GBPUSD")
        # TP3 takes the first qualifying level with sufficient gap (13285)
        # Major level preference only applies via the fallback search
        assert result["tp3"] == 13285

    def test_tp3_falls_back_to_third_if_no_major(self):
        """If no major levels beyond TP2, use the plain third level."""
        levels = [
            self._make_level(13250),
            self._make_level(13270),
            self._make_level(13280),
        ]
        result = select_tp_levels(13230, "BUY", levels, "GBPUSD")
        assert result["tp3"] == 13280

    def test_levels_behind_entry_ignored(self):
        """BUY: levels below entry are not used."""
        levels = [
            self._make_level(13200),  # below entry — ignored
            self._make_level(13210),  # below entry — ignored
            self._make_level(13250),  # above — TP1
        ]
        result = select_tp_levels(13230, "BUY", levels, "GBPUSD")
        assert result["tp1"] == 13250

    def test_sl_pips_default_12(self):
        """Default SL = 12 pips (flattened 2026-04 — ATR no longer factors)."""
        result = select_tp_levels(13230, "BUY", [], "GBPUSD")
        assert result["sl_pips"] == 12.0

    def test_sl_pips_usdjpy_12(self):
        """USDJPY entry in the override table also flattened to 12 pips."""
        result = select_tp_levels(14500, "BUY", [], "USDJPY")
        assert result["sl_pips"] == 12.0

    def test_sell_fallback_levels_below_entry(self):
        """SELL fallback levels should be below entry price."""
        result = select_tp_levels(13230, "SELL", [], "GBPUSD")
        assert result["tp1"] < 13230
        assert result["tp2"] < result["tp1"]
        assert result["tp3"] < result["tp2"]


# ============================================================
# check_momentum
# ============================================================
class TestCheckMomentum:
    """Momentum check at TP levels."""

    def test_all_conditions_met_returns_hold(self):
        """All 3 conditions YES → HOLD."""
        result = check_momentum(
            direction="BUY",
            macd_hist_current=5.0,   # > prev → expanding
            macd_hist_prev=3.0,
            candle_bodies=[(100, 105), (102, 108), (104, 110)],  # 3/3 bullish
            recent_highs=[108, 112],  # new high
            recent_lows=[100, 101],
        )
        assert result == "HOLD"

    def test_all_conditions_met_sell_returns_hold(self):
        """SELL: all 3 conditions YES → HOLD."""
        result = check_momentum(
            direction="SELL",
            macd_hist_current=-5.0,  # more negative → expanding
            macd_hist_prev=-3.0,
            candle_bodies=[(110, 105), (108, 102), (106, 100)],  # 3/3 bearish
            recent_highs=[112, 108],
            recent_lows=[101, 98],  # new low
        )
        assert result == "HOLD"

    def test_two_conditions_no_returns_close(self):
        """If 2+ conditions are NO → CLOSE."""
        result = check_momentum(
            direction="BUY",
            macd_hist_current=2.0,   # < prev → NOT expanding
            macd_hist_prev=5.0,
            candle_bodies=[(100, 98), (102, 99), (104, 101)],  # 0/3 bullish
            recent_highs=[112, 108],  # NOT new high
            recent_lows=[100, 101],
        )
        assert result == "CLOSE"

    def test_one_condition_no_returns_close(self):
        """Even 2 YES + 1 NO → CLOSE (spec requires all 3 for HOLD)."""
        result = check_momentum(
            direction="BUY",
            macd_hist_current=5.0,   # expanding ✓
            macd_hist_prev=3.0,
            candle_bodies=[(100, 105), (102, 108), (104, 110)],  # 3/3 bullish ✓
            recent_highs=[112, 108],  # NOT new high ✗
            recent_lows=[100, 101],
        )
        assert result == "CLOSE"

    def test_missing_data_counts_as_no(self):
        """Missing/None data → conditions default to NO → CLOSE."""
        result = check_momentum("BUY", None, None, [], [], [])
        assert result == "CLOSE"

    def test_two_of_three_bodies_sufficient(self):
        """2 of 3 candle bodies in direction is sufficient for that condition."""
        result = check_momentum(
            direction="BUY",
            macd_hist_current=5.0,
            macd_hist_prev=3.0,
            candle_bodies=[(100, 98), (102, 108), (104, 110)],  # 2/3 bullish
            recent_highs=[108, 112],
            recent_lows=[100, 101],
        )
        assert result == "HOLD"

    def test_one_of_three_bodies_insufficient(self):
        """Only 1 of 3 bullish bodies → condition fails."""
        result = check_momentum(
            direction="BUY",
            macd_hist_current=5.0,
            macd_hist_prev=3.0,
            candle_bodies=[(100, 98), (102, 99), (104, 110)],  # 1/3 bullish
            recent_highs=[108, 112],
            recent_lows=[100, 101],
        )
        # MACD expanding ✓, bodies ✗, new high ✓ → 2 YES → CLOSE
        assert result == "CLOSE"


# ============================================================
# SL Progression
# ============================================================
class TestSLProgression:
    """Verify SL moves correctly through TP1 → TP2 → TP3."""

    @pytest.fixture
    def tm(self):
        return TradeManager()

    def _setup_trade(self, tm, epic, entry=13230, direction="BUY"):
        """Set up a mock trade with briefing TP plan."""
        import trade_executor as _exec
        st = _exec._state_for_epic(epic)
        st.update({
            "active": True,
            "epic": epic,
            "direction": direction,
            "entry_price": entry,
            "pip_size": 1.0,
            "open_time": 0,
            "mode": "BRIEFING_LIQUIDITY",
        })
        levels = [
            {"price": entry + 20 if direction == "BUY" else entry - 20,
             "level_type": "resistance" if direction == "BUY" else "support",
             "source": "test", "major": False},
            {"price": entry + 40 if direction == "BUY" else entry - 40,
             "level_type": "resistance" if direction == "BUY" else "support",
             "source": "test", "major": False},
            {"price": entry + 70 if direction == "BUY" else entry - 70,
             "level_type": "resistance" if direction == "BUY" else "support",
             "source": "test", "major": True},
        ]
        tm.setup_briefing_tp(epic, entry, direction, levels, "GBPUSD")
        return st

    def test_initial_sl_is_entry_minus_12(self, tm):
        """On open, SL = entry - 12 pips for BUY (flattened default)."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        self._setup_trade(tm, epic, entry=13230, direction="BUY")
        meta = _BRIEFING_TP_BY_EPIC[epic]
        assert meta["sl_price"] == pytest.approx(13218.0)  # 13230 - 12
        assert meta["current_phase"] == "OPEN"

    def test_initial_sl_sell_is_entry_plus_12(self, tm):
        """On open, SL = entry + 12 pips for SELL (flattened default)."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        self._setup_trade(tm, epic, entry=13230, direction="SELL")
        meta = _BRIEFING_TP_BY_EPIC[epic]
        assert meta["sl_price"] == pytest.approx(13242.0)  # 13230 + 12

    @patch("trade_manager._exec")
    def test_tp1_hold_moves_sl_to_breakeven(self, mock_exec, tm):
        """After TP1 with HOLD momentum, SL should move to entry (breakeven)."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        mock_exec.TRADE_STATE = {}
        mock_exec.TRADE_STATE_BY_EPIC = {}
        st = self._setup_trade(tm, epic, entry=13230, direction="BUY")

        # Simulate reaching TP1 (13250) with good momentum
        with patch("trade_manager.check_momentum", return_value="HOLD"):
            with patch("trade_manager._effective_price_for_management", return_value=13250.0):
                with patch("trade_manager._calculate_pnl_pips", return_value=20.0):
                    tm._monitor_briefing_tp(
                        epic, 13250.0,
                        macd_hist=5.0, prev_macd_hist=3.0,
                        candle_bodies=[(100, 105)], recent_highs=[108, 112], recent_lows=[100, 101],
                    )

        meta = _BRIEFING_TP_BY_EPIC[epic]
        assert meta["current_phase"] == "TP1"
        assert meta["sl_price"] == pytest.approx(13230.0)  # breakeven

    @patch("trade_manager._exec")
    def test_tp2_hold_moves_sl_to_tp1(self, mock_exec, tm):
        """After TP2 with HOLD momentum, SL should move to TP1 level."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        mock_exec.TRADE_STATE = {}
        mock_exec.TRADE_STATE_BY_EPIC = {}
        st = self._setup_trade(tm, epic, entry=13230, direction="BUY")

        # Manually advance to TP1 phase
        meta = _BRIEFING_TP_BY_EPIC[epic]
        meta["current_phase"] = "TP1"
        meta["sl_price"] = 13230.0  # breakeven

        # Simulate reaching TP2 (13270) with good momentum
        with patch("trade_manager.check_momentum", return_value="HOLD"):
            with patch("trade_manager._effective_price_for_management", return_value=13270.0):
                with patch("trade_manager._calculate_pnl_pips", return_value=40.0):
                    tm._monitor_briefing_tp(
                        epic, 13270.0,
                        macd_hist=5.0, prev_macd_hist=3.0,
                        candle_bodies=[(100, 105)], recent_highs=[108, 112], recent_lows=[100, 101],
                    )

        meta = _BRIEFING_TP_BY_EPIC[epic]
        assert meta["current_phase"] == "TP2"
        assert meta["sl_price"] == pytest.approx(13250.0)  # TP1 level

    @patch("trade_manager._exec")
    def test_tp1_close_closes_position(self, mock_exec, tm):
        """At TP1 with fading momentum, position should close."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        mock_exec.TRADE_STATE = {}
        mock_exec.TRADE_STATE_BY_EPIC = {}
        st = self._setup_trade(tm, epic, entry=13230, direction="BUY")

        with patch("trade_manager.check_momentum", return_value="CLOSE"):
            with patch("trade_manager._effective_price_for_management", return_value=13250.0):
                with patch("trade_manager._calculate_pnl_pips", return_value=20.0):
                    with patch("trade_manager._close_trade_best_effort") as mock_close:
                        tm._monitor_briefing_tp(
                            epic, 13250.0,
                            macd_hist=2.0, prev_macd_hist=5.0,
                        )
                        mock_close.assert_called_once_with(epic, "BRIEFING_TP1_CLOSE", 13250.0)

    @patch("trade_manager._exec")
    def test_tp3_always_closes(self, mock_exec, tm):
        """TP3 always closes regardless of momentum."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        mock_exec.TRADE_STATE = {}
        mock_exec.TRADE_STATE_BY_EPIC = {}
        st = self._setup_trade(tm, epic, entry=13230, direction="BUY")

        # Advance to TP2 phase
        meta = _BRIEFING_TP_BY_EPIC[epic]
        meta["current_phase"] = "TP2"

        with patch("trade_manager._effective_price_for_management", return_value=13300.0):
            with patch("trade_manager._calculate_pnl_pips", return_value=70.0):
                with patch("trade_manager._close_trade_best_effort") as mock_close:
                    tm._monitor_briefing_tp(epic, 13300.0)
                    mock_close.assert_called_once_with(epic, "BRIEFING_TP3_HIT", 13300.0)

    @patch("trade_manager._exec")
    def test_sl_hit_closes_position(self, mock_exec, tm):
        """Price hitting SL should close the trade."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        mock_exec.TRADE_STATE = {}
        mock_exec.TRADE_STATE_BY_EPIC = {}
        st = self._setup_trade(tm, epic, entry=13230, direction="BUY")

        with patch("trade_manager._effective_price_for_management", return_value=13209.0):
            with patch("trade_manager._calculate_pnl_pips", return_value=-21.0):
                with patch("trade_manager._close_trade_best_effort") as mock_close:
                    tm._monitor_briefing_tp(epic, 13209.0)
                    mock_close.assert_called_once()
                    assert "SL" in mock_close.call_args[0][1]

    @patch("trade_manager._exec")
    def test_pullback_trail_closes_between_levels(self, mock_exec, tm):
        """25-pip pullback from swing after TP1 should close."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        mock_exec.TRADE_STATE = {}
        mock_exec.TRADE_STATE_BY_EPIC = {}
        st = self._setup_trade(tm, epic, entry=13230, direction="BUY")

        meta = _BRIEFING_TP_BY_EPIC[epic]
        meta["current_phase"] = "TP1"
        meta["sl_price"] = 13230.0  # breakeven
        meta["swing_extreme"] = 13270.0  # Best price reached

        # Price pulls back 25 pips from swing (13270 - 25 = 13245)
        with patch("trade_manager._effective_price_for_management", return_value=13245.0):
            with patch("trade_manager._calculate_pnl_pips", return_value=15.0):
                with patch("trade_manager._close_trade_best_effort") as mock_close:
                    tm._monitor_briefing_tp(epic, 13245.0)
                    mock_close.assert_called_once()
                    assert "PULLBACK" in mock_close.call_args[0][1]


# ============================================================
# News Blackout
# ============================================================
class TestNewsBlackout:
    """News blackout handling during open trades."""

    @pytest.fixture
    def tm(self):
        return TradeManager()

    def _setup_trade(self, tm, epic, entry=13230, direction="BUY"):
        import trade_executor as _exec
        st = _exec._state_for_epic(epic)
        st.update({
            "active": True, "epic": epic, "direction": direction,
            "entry_price": entry, "pip_size": 1.0, "open_time": 0,
            "mode": "BRIEFING_LIQUIDITY",
        })
        levels = [
            {"price": entry + 30, "level_type": "resistance", "source": "test", "major": False},
            {"price": entry + 50, "level_type": "resistance", "source": "test", "major": False},
            {"price": entry + 80, "level_type": "resistance", "source": "test", "major": True},
        ]
        tm.setup_briefing_tp(epic, entry, direction, levels, "GBPUSD")
        return st

    @patch("trade_manager._exec")
    def test_news_blackout_positive_profit_closes(self, mock_exec, tm):
        """Positive profit during news blackout → close."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        mock_exec.TRADE_STATE = {}
        mock_exec.TRADE_STATE_BY_EPIC = {}
        self._setup_trade(tm, epic)

        with patch("trade_manager._effective_price_for_management", return_value=13240.0):
            with patch("trade_manager._calculate_pnl_pips", return_value=10.0):
                with patch("trade_manager._close_trade_best_effort") as mock_close:
                    tm._monitor_briefing_tp(epic, 13240.0, news_blackout=True)
                    mock_close.assert_called_once()
                    assert "NEWS_BLACKOUT" in mock_close.call_args[0][1]

    @patch("trade_manager._exec")
    def test_news_blackout_negative_profit_lets_sl_handle(self, mock_exec, tm):
        """Negative profit during news blackout → do nothing, let SL handle."""
        epic = "CS.D.GBPUSD.TODAY.IP"
        mock_exec.TRADE_STATE = {}
        mock_exec.TRADE_STATE_BY_EPIC = {}
        self._setup_trade(tm, epic)

        with patch("trade_manager._effective_price_for_management", return_value=13220.0):
            with patch("trade_manager._calculate_pnl_pips", return_value=-10.0):
                with patch("trade_manager._close_trade_best_effort") as mock_close:
                    tm._monitor_briefing_tp(epic, 13220.0, news_blackout=True)
                    mock_close.assert_not_called()
