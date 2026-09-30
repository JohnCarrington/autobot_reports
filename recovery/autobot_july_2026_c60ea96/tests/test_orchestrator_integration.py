"""Phase-2 orchestrator integration tests.

End-to-end with mocked LLM + Telegram. Uses orchestrator-built market_data
(via assemble_v5_data_package_offline) against the deep-cache CSV so the
exercised path matches what tomorrow's live fire will exercise (minus the
real LLM call).

Verifies:
  - Two-write atomicity: the .tmp+rename pattern is used (write spy).
    Specifically: when the LLM crashes between writes, the file already
    on disk contains the deterministic plan with rationale=null.
  - Rationale appears in the final JSON when the LLM succeeds.
  - rationale=null persists when the LLM fails.
  - Telegram fires once and only once on ARMED, never on STAND_ASIDE.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from briefing.v5_pia import orchestrator                      # noqa: E402
from briefing.v5_pia.config import BRIEFINGS_DIR              # noqa: E402
from briefing.v5_pia.data_package import (                    # noqa: E402
    assemble_v5_data_package_offline,
)
from briefing.v5_pia.orchestrator import generate_briefing_v5 # noqa: E402

CACHE = ROOT / "cache"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resample(df_5m: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df_5m.empty:
        return df_5m
    df = df_5m.set_index("timestamp")
    return df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna(subset=["open"]).reset_index()


def _md_for(symbol: str, at_utc: datetime) -> dict:
    p = CACHE / f"{symbol}_candles_deep.csv"
    df = pd.read_csv(p)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df[df["timestamp"] <= pd.Timestamp(at_utc)].reset_index(drop=True)
    return assemble_v5_data_package_offline(
        symbol, "London", at_utc,
        df_5m=df, df_h1=_resample(df, "1h"),
        df_h4=_resample(df, "4h"), df_d1=_resample(df, "1D"),
    )


_AT = datetime(2026, 3, 19, 15, 5, tzinfo=timezone.utc)


@pytest.fixture
def isolated_briefings_dir(tmp_path, monkeypatch):
    """Redirect orchestrator writes into tmp_path so each test starts
    from a clean slate and we don't trample fixture/live files.
    """
    monkeypatch.setattr(orchestrator, "BRIEFINGS_DIR", tmp_path)
    return tmp_path


def _expected_path(tmp: Path, pair: str) -> Path:
    return tmp / f"briefing_{pair}_2026-03-19_London.json"


# ─────────────────────────────────────────────────────────────────────────────
# Two-write atomicity
# ─────────────────────────────────────────────────────────────────────────────

class TestTwoWriteAtomicity:
    def test_two_writes_observed_on_armed(self, isolated_briefings_dir):
        """Spy on _write_briefing — must be called exactly twice for an
        ARMED path (v1 = rationale=null, v2 = rationale=text).
        """
        md = _md_for("GBPUSD", _AT)
        good = (
            "We look to Buy at 1.33146\n"
            "Bias remains positive on daily and four hour\n"
            "Stop sits below the recent swing low\n"
            "Risk reward is acceptable on this entry"
        )
        with patch("briefing.v5_pia.rationale_writer.call_messages",
                   return_value=good), \
             patch.object(orchestrator, "_send_telegram_armed"), \
             patch.object(orchestrator, "_write_briefing",
                          wraps=orchestrator._write_briefing) as spy:
            briefing = generate_briefing_v5(
                "GBPUSD", "London", _AT,
                market_data=md, news_calendar=[], write_to_disk=True,
            )
        assert briefing.state == "ARMED"
        assert spy.call_count == 2, (
            f"expected 2 _write_briefing calls (v1+v2), got {spy.call_count}"
        )
        # Final on-disk file has rationale populated
        on_disk = json.loads(_expected_path(isolated_briefings_dir, "GBPUSD").read_text())
        assert on_disk["rationale"] == good

    def test_llm_crash_leaves_v1_on_disk(self, isolated_briefings_dir):
        """If the LLM crashes, the deterministic plan is already on disk
        from the v1 write. The v2 write is then called with
        rationale=None — so the on-disk file ends up with rationale=null
        and the trade plan intact.
        """
        md = _md_for("GBPUSD", _AT)
        def boom(**_kwargs):
            raise RuntimeError("simulated LLM crash")
        with patch("briefing.v5_pia.rationale_writer.call_messages",
                   side_effect=boom), \
             patch.object(orchestrator, "_send_telegram_armed"):
            briefing = generate_briefing_v5(
                "GBPUSD", "London", _AT,
                market_data=md, news_calendar=[], write_to_disk=True,
            )
        on_disk = json.loads(_expected_path(isolated_briefings_dir, "GBPUSD").read_text())
        # Plan intact
        assert on_disk["state"] == "ARMED"
        assert on_disk["entry"] == briefing.entry
        assert on_disk["stop"] == briefing.stop
        assert on_disk["target"] == briefing.target
        # Rationale is null
        assert on_disk["rationale"] is None

    def test_atomic_rename_no_tmp_left_behind(self, isolated_briefings_dir):
        """After a successful run there must be no .tmp file lurking
        in the briefings dir — the rename is the publish step.
        """
        md = _md_for("GBPUSD", _AT)
        with patch("briefing.v5_pia.rationale_writer.call_messages",
                   return_value="We look to Buy at 1.33146\nBias is positive\n"
                                "Stop sits below swing low\nRisk reward acceptable"), \
             patch.object(orchestrator, "_send_telegram_armed"):
            generate_briefing_v5(
                "GBPUSD", "London", _AT,
                market_data=md, news_calendar=[], write_to_disk=True,
            )
        leftovers = list(isolated_briefings_dir.glob("*.tmp"))
        assert leftovers == [], f"leftover .tmp files: {leftovers}"


# ─────────────────────────────────────────────────────────────────────────────
# Telegram gating
# ─────────────────────────────────────────────────────────────────────────────

class TestTelegramGating:
    def test_armed_sends_telegram(self, isolated_briefings_dir):
        md = _md_for("GBPUSD", _AT)
        good = (
            "We look to Buy at 1.33146\nOur bias remains positive\n"
            "Stop sits below the recent swing low\nRisk reward acceptable"
        )
        with patch("briefing.v5_pia.rationale_writer.call_messages",
                   return_value=good), \
             patch("telegram_alerts.send_telegram_message") as tg_mock:
            briefing = generate_briefing_v5(
                "GBPUSD", "London", _AT,
                market_data=md, news_calendar=[], write_to_disk=True,
            )
        assert briefing.state == "ARMED"
        assert tg_mock.call_count == 1, (
            f"telegram should fire once on ARMED, got {tg_mock.call_count}"
        )
        msg = tg_mock.call_args.args[0]
        assert "Briefing v5 GBPUSD London" in msg
        assert "Direction: BUY" in msg
        assert "Confidence: 75%" in msg
        # Rationale appears
        assert "We look to Buy" in msg

    def test_stand_aside_does_not_send_telegram(self, isolated_briefings_dir):
        md = _md_for("EURUSD", _AT)
        with patch("briefing.v5_pia.rationale_writer.call_messages",
                   return_value=(
                       "Confluence has failed this session\n"
                       "Daily and four hour bias are not aligned\n"
                       "We stand aside until structure clears"
                   )), \
             patch("telegram_alerts.send_telegram_message") as tg_mock:
            briefing = generate_briefing_v5(
                "EURUSD", "London", _AT,
                market_data=md, news_calendar=[], write_to_disk=True,
            )
        assert briefing.state == "STAND_ASIDE"
        assert tg_mock.call_count == 0, (
            f"telegram must NOT fire on STAND_ASIDE, got {tg_mock.call_count}"
        )

    def test_armed_with_failed_llm_still_sends_telegram(self, isolated_briefings_dir):
        """Phase-2 spec: 'If rationale is null (LLM failed), send the
        message anyway with [rationale unavailable] in the rationale slot.'
        """
        md = _md_for("GBPUSD", _AT)
        with patch("briefing.v5_pia.rationale_writer.call_messages",
                   return_value=None), \
             patch("telegram_alerts.send_telegram_message") as tg_mock:
            generate_briefing_v5(
                "GBPUSD", "London", _AT,
                market_data=md, news_calendar=[], write_to_disk=True,
            )
        assert tg_mock.call_count == 1
        msg = tg_mock.call_args.args[0]
        assert "[rationale unavailable]" in msg


# ─────────────────────────────────────────────────────────────────────────────
# Rationale persistence on disk
# ─────────────────────────────────────────────────────────────────────────────

class TestRationaleOnDisk:
    def test_rationale_present_in_final_json(self, isolated_briefings_dir):
        md = _md_for("GBPUSD", _AT)
        good = (
            "We look to Buy at 1.33146\nBias remains positive\n"
            "Stop sits below the recent swing low\nRisk reward acceptable"
        )
        with patch("briefing.v5_pia.rationale_writer.call_messages",
                   return_value=good), \
             patch.object(orchestrator, "_send_telegram_armed"):
            generate_briefing_v5(
                "GBPUSD", "London", _AT,
                market_data=md, news_calendar=[], write_to_disk=True,
            )
        on_disk = json.loads(_expected_path(isolated_briefings_dir, "GBPUSD").read_text())
        assert on_disk["rationale"] == good

    def test_rationale_null_when_llm_returns_none(self, isolated_briefings_dir):
        md = _md_for("GBPUSD", _AT)
        with patch("briefing.v5_pia.rationale_writer.call_messages",
                   return_value=None), \
             patch.object(orchestrator, "_send_telegram_armed"):
            generate_briefing_v5(
                "GBPUSD", "London", _AT,
                market_data=md, news_calendar=[], write_to_disk=True,
            )
        on_disk = json.loads(_expected_path(isolated_briefings_dir, "GBPUSD").read_text())
        assert on_disk["rationale"] is None
        assert on_disk["state"] == "ARMED"

    def test_rationale_null_when_validation_fails(self, isolated_briefings_dir):
        """LLM returns text that fails validation (markdown char) →
        write_rationale returns None → on-disk JSON has rationale=null."""
        md = _md_for("GBPUSD", _AT)
        bad = "We look to **Buy** at 1.33146 with bias remaining positive"  # markdown asterisks → fail
        with patch("briefing.v5_pia.rationale_writer.call_messages",
                   return_value=bad), \
             patch.object(orchestrator, "_send_telegram_armed"):
            generate_briefing_v5(
                "GBPUSD", "London", _AT,
                market_data=md, news_calendar=[], write_to_disk=True,
            )
        on_disk = json.loads(_expected_path(isolated_briefings_dir, "GBPUSD").read_text())
        assert on_disk["rationale"] is None
