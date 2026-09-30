"""Unit coverage for htf_authority.

Targets the ADX-floor RANGE→TREND override added in f4216cf and the
telemetry-serializer fix in 172b63a. Ported from /tmp/_validate_adx_override.py
(the ad-hoc validation harness) into pytest so the cases land in CI.

Cases A–G mirror the validator's 7 scenarios on _classify_market.
Case H exercises evaluate()'s row serializer to confirm the four
new fields (adx_override_fired, _value, _floor, _direction_source)
are emitted into the logged record — the gap 172b63a closes.

Stubbing strategy mirrors the validator:
  - htf_regime.classify       — in-process module stub via sys.modules
  - regime_engine.latest_result — same
  - htf_authority._structure_dir — monkeypatched on the freshly-loaded module
  - htf_authority._load_recent_h1_closes — returns [] to suppress the
    sibling drift-override path
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Make /opt/tradingbot importable when pytest is invoked from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _install_stubs(
    monkeypatch,
    *,
    h1_state: str = "RANGE",
    structure_dir: str = "FLAT",
    adx: float | None = 35.0,
    directional_bias: str = "SHORT",
    raise_in_regime_engine: bool = False,
):
    """Replace htf_regime + regime_engine with in-process stubs, force a
    fresh htf_authority load so its imports rebind to the stubs, then
    patch the two primitives the override consults out-of-band."""
    htf_stub = types.ModuleType("htf_regime")

    def _classify(_sym):
        return {
            "h1_state": h1_state,
            "d1_state": "DOWN",
            "w1_state": "DOWN",
            "alignment": "NEUTRAL",
            "debug": {
                "h1_features": {
                    "ema8_minus_ema21_pips": -3.0,
                    "ema_slope": -0.4,
                },
                "d1_features": {"ema_slope": -0.5},
                "w1_features": {"ema_slope": -0.3},
                "pip_size": 1.0,
            },
        }

    htf_stub.classify = _classify
    monkeypatch.setitem(sys.modules, "htf_regime", htf_stub)

    re_stub = types.ModuleType("regime_engine")

    def _latest_result(_sym):
        if raise_in_regime_engine:
            raise RuntimeError("simulated regime_engine failure")
        return {
            "ADX": adx,
            "directional_bias": directional_bias,
            "winning_regime": "STRONG_TREND_DOWN",
            "full_features": {"close": 13400.0},
        }

    re_stub.latest_result = _latest_result
    monkeypatch.setitem(sys.modules, "regime_engine", re_stub)

    monkeypatch.delitem(sys.modules, "htf_authority", raising=False)
    import htf_authority as HA  # noqa: E402

    monkeypatch.setattr(
        HA,
        "_structure_dir",
        lambda _sym: (
            structure_dir,
            {"lookback": 5, "min_break_pips": 0.0, "flip_bar_ts": None},
        ),
    )
    monkeypatch.setattr(HA, "_load_recent_h1_closes", lambda _sym, _w: [])
    return HA


@pytest.fixture
def env_baseline(monkeypatch, tmp_path):
    """Standard env for every case — disable noisy sibling features and
    point telemetry at a temp dir so live logs aren't polluted."""
    monkeypatch.setenv("HTF_AUTHORITY_LOG_PATH", str(tmp_path / "htf.jsonl"))
    monkeypatch.setenv("BB_BLOCK_SHADOW_LOG_PATH", str(tmp_path / "bbs.jsonl"))
    monkeypatch.setenv("NEWS_STATE_LOGGING_ENABLED", "0")
    monkeypatch.setenv("HTF_AUTHORITY_ENABLED", "1")
    monkeypatch.setenv("HTF_AUTH_STRUCTURE_LEADS_ENABLED", "0")
    monkeypatch.setenv("HTF_AUTH_STRUCTURE_RANGE_STANDDOWN_ENABLED", "0")


@pytest.fixture
def override_on(monkeypatch, env_baseline):
    monkeypatch.setenv("HTF_AUTH_ADX_OVERRIDE_ENABLED", "1")
    monkeypatch.setenv("HTF_AUTH_ADX_TREND_FLOOR", "25.0")


@pytest.fixture
def override_off(monkeypatch, env_baseline):
    monkeypatch.setenv("HTF_AUTH_ADX_OVERRIDE_ENABLED", "0")
    monkeypatch.setenv("HTF_AUTH_ADX_TREND_FLOOR", "25.0")


# ── Case A — RANGE + ADX>=floor + structure_dir=DOWN → TREND/DOWN ───────
def test_case_a_range_adx_above_floor_with_structure_dir_flips(monkeypatch, override_on):
    HA = _install_stubs(
        monkeypatch, h1_state="RANGE", structure_dir="DOWN",
        adx=35.0, directional_bias="SHORT",
    )
    out = HA._classify_market("GBPUSD")
    assert out["call"] == "TREND"
    assert out["direction"] == "DOWN"
    assert out["adx_override_fired"] is True
    assert out["adx_override_value"] == 35.0
    assert out["adx_override_floor"] == 25.0
    assert out["adx_override_direction_source"] == "structure_dir"


# ── Case B — RANGE + ADX>=floor + structure_dir=FLAT + bias=LONG → TREND/UP ──
def test_case_b_range_adx_above_floor_uses_regime_engine_bias(monkeypatch, override_on):
    HA = _install_stubs(
        monkeypatch, h1_state="RANGE", structure_dir="FLAT",
        adx=28.0, directional_bias="LONG",
    )
    out = HA._classify_market("GBPUSD")
    assert out["call"] == "TREND"
    assert out["direction"] == "UP"
    assert out["adx_override_fired"] is True
    assert out["adx_override_value"] == 28.0
    assert out["adx_override_direction_source"] == "regime_engine_bias"


# ── Case C — RANGE + ADX<floor → stays RANGE ───────────────────────────
def test_case_c_range_adx_below_floor_stays_range(monkeypatch, override_on):
    HA = _install_stubs(
        monkeypatch, h1_state="RANGE", structure_dir="DOWN",
        adx=20.0, directional_bias="SHORT",
    )
    out = HA._classify_market("GBPUSD")
    assert out["call"] == "RANGE"
    assert out["adx_override_fired"] is False


# ── Case D — RANGE + ADX>=floor + no direction available → stays RANGE ─
def test_case_d_range_adx_above_floor_no_direction_stays_range(monkeypatch, override_on):
    HA = _install_stubs(
        monkeypatch, h1_state="RANGE", structure_dir="FLAT",
        adx=35.0, directional_bias="",
    )
    out = HA._classify_market("GBPUSD")
    assert out["call"] == "RANGE"
    assert out["adx_override_fired"] is False


# ── Case E — TREND call + ADX>=floor → override never fires ────────────
def test_case_e_trend_call_override_never_fires(monkeypatch, override_on):
    HA = _install_stubs(
        monkeypatch, h1_state="EXPANSION", structure_dir="DOWN",
        adx=35.0, directional_bias="SHORT",
    )
    out = HA._classify_market("GBPUSD")
    # h1=EXPANSION + DOWN slopes → TREND already; override gate is
    # out["call"]=="RANGE" so it never touches a TREND call.
    assert out["call"] == "TREND"
    assert out["adx_override_fired"] is False


# ── Case F — RANGE + regime_engine raises → stays RANGE, clean abort ──
def test_case_f_range_regime_engine_raises_stays_range(monkeypatch, override_on):
    HA = _install_stubs(
        monkeypatch, h1_state="RANGE", structure_dir="DOWN",
        adx=35.0, directional_bias="SHORT",
        raise_in_regime_engine=True,
    )
    out = HA._classify_market("GBPUSD")
    assert out["call"] == "RANGE"
    assert out["adx_override_fired"] is False


# ── Case G — flag OFF + RANGE + ADX>=floor → stays RANGE (kill switch) ─
def test_case_g_flag_off_stays_range(monkeypatch, override_off):
    HA = _install_stubs(
        monkeypatch, h1_state="RANGE", structure_dir="DOWN",
        adx=35.0, directional_bias="SHORT",
    )
    out = HA._classify_market("GBPUSD")
    assert out["call"] == "RANGE"
    assert out["adx_override_fired"] is False


# ── Case H — serializer emits the four new fields when override fires ──
# Covers 172b63a: pre-fix, adx_override_fired was set on the classification
# dict but never bridged into evaluate()'s hand-curated details dict, so
# every logged row was missing the field.
def test_case_h_serializer_emits_adx_override_fields(monkeypatch, override_on):
    HA = _install_stubs(
        monkeypatch, h1_state="RANGE", structure_dir="DOWN",
        adx=35.0, directional_bias="SHORT",
    )
    captured: list[dict] = []
    monkeypatch.setattr(HA, "_write_log", lambda rec: captured.append(rec))

    HA.evaluate("GBPUSD", "SELL", "GBPUSD_TREND_S")

    assert len(captured) == 1, "evaluate() should write exactly one telemetry row"
    rec = captured[0]
    assert rec.get("adx_override_fired") is True
    assert rec.get("adx_override_value") == 35.0
    assert rec.get("adx_override_floor") == 25.0
    assert rec.get("adx_override_direction_source") == "structure_dir"
    # And the override's effect on call/direction is also serialized.
    assert rec.get("call") == "TREND"
    assert rec.get("authority_direction") == "DOWN"
