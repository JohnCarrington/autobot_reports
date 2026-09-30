"""Tests for news_momentum_observer (2026-07-26). Observation-only
strategy — validates: qualifying release produces a full row; no-
resolution release produces verdict=no_resolution; stale calendar
suppresses the row + logs the reason; observer exceptions cannot
propagate; join to the NEWS_STRATEGY release-anchored eval row is
present when available AND null-safe when absent.

Every test seeds an isolated cache dir, log path, and rolling candle
cache so nothing from the real bot leaks into the assertions."""
from __future__ import annotations

import importlib
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO = Path("/opt/tradingbot")
RELEASE_DT = datetime(2026, 7, 20, 12, 30, tzinfo=timezone.utc)


# ── Fixtures ─────────────────────────────────────────────────────────────
@pytest.fixture()
def obs_env(tmp_path, monkeypatch):
    """Reload news_momentum_observer + friends against isolated temp
    paths. Yields (module, tmp_path)."""
    cache_dir = tmp_path / "cache"
    news_cache_dir = tmp_path / "news_cache"
    logs_dir = tmp_path / "logs"
    cache_dir.mkdir()
    news_cache_dir.mkdir()
    logs_dir.mkdir()

    monkeypatch.setenv("NEWS_MOMENTUM_MODE", "observe")
    monkeypatch.setenv("CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("NEWS_STATE_CACHE_DIR", str(news_cache_dir))
    monkeypatch.setenv(
        "NEWS_MOMENTUM_OBS_LOG_PATH",
        str(logs_dir / "news_momentum_obs.jsonl"),
    )
    monkeypatch.setenv(
        "NEWS_STRATEGY_EVALS_LOG_PATH",
        str(logs_dir / "news_strategy_evals.jsonl"),
    )
    monkeypatch.setenv("NEWS_MIN_IMPACT", "HIGH")
    monkeypatch.setenv("NEWS_MOM_RANGE_START_MIN", "5")
    monkeypatch.setenv("NEWS_MOM_RANGE_END_MIN", "30")
    monkeypatch.setenv("NEWS_MOM_OBS_START_MIN", "30")
    monkeypatch.setenv("NEWS_MOM_OBS_END_MIN", "60")
    monkeypatch.setenv("NEWS_MOM_OUTCOME_END_MIN", "180")
    # Disable staleness by default — tests that need it override.
    monkeypatch.setenv("NEWS_CALENDAR_MAX_AGE_HOURS", "999999")

    for m in ("news_calendar_health", "news_momentum_observer"):
        sys.modules.pop(m, None)
    import news_calendar_health  # noqa: F401
    import news_momentum_observer as mom
    mom._reset_state_for_tests()
    return mom, tmp_path


def _seed_calendar(news_cache_dir: Path, release_dt: datetime,
                   currency: str = "USD", event: str = "Nonfarm Payrolls",
                   impact: str = "HIGH") -> None:
    for day in (release_dt - timedelta(days=1), release_dt,
                release_dt + timedelta(days=1)):
        day_str = day.strftime("%Y-%m-%d")
        (news_cache_dir / f"news_state_finnhub_{day_str}.json").write_text(
            json.dumps({
                "date": day_str,
                "events": [{
                    "ts": release_dt.isoformat(),
                    "currency": currency,
                    "impact": impact,
                    "event": event,
                }],
                "written_at": release_dt.isoformat(),
            })
        )


def _seed_rolling_cache(cache_dir: Path, pair: str,
                        bars: list) -> None:
    """bars: list of (ts_utc, o, h, l, c)."""
    path = cache_dir / f"{pair.upper()}_candles_rolling.csv"
    lines = ["timestamp,open,high,low,close"]
    for ts, o, h, lo, c in bars:
        lines.append(f"{ts.isoformat()},{o},{h},{lo},{c}")
    path.write_text("\n".join(lines) + "\n")


def _build_release() -> dict:
    return {
        "release_key": f"Nonfarm Payrolls|{int(RELEASE_DT.timestamp())}",
        "release_ts": RELEASE_DT.timestamp(),
        "release_ts_iso": RELEASE_DT.isoformat(),
        "event_name": "Nonfarm Payrolls",
        "currency": "USD",
        "impact": "HIGH",
    }


def _make_bar(release: datetime, minute_offset: int,
              o, h, lo, c):
    return (release + timedelta(minutes=minute_offset), o, h, lo, c)


# ── Test 1: qualifying release → full row with all phases ────────────────
def test_qualifying_release_produces_full_row(obs_env, monkeypatch):
    mom, tmp_path = obs_env
    news_cache_dir = tmp_path / "news_cache"
    cache_dir = tmp_path / "cache"
    logs_dir = tmp_path / "logs"

    _seed_calendar(news_cache_dir, RELEASE_DT)

    # Build a synthetic rolling cache for GBPUSD (bot-scaled × 10000).
    # PHASE A (5-30 min): high 13350, low 13300 (50p width).
    # PHASE B (30-60 min): +35m bar CLOSES at 13380 (above range) → break UP.
    # PHASE C (>break, <180m): max high 13420 (+40p MFE from 13380),
    #                          min low 13360 (-20p MAE from 13380).
    bars = []
    # Phase-A bars every 5 minutes from +5 to +25 inclusive (5 bars).
    for i, off in enumerate((5, 10, 15, 20, 25)):
        # Ramp within [13300, 13350] range.
        bars.append(_make_bar(RELEASE_DT, off,
                              13310 + i, 13320 + i * 5, 13300 + i, 13315 + i))
    # Ensure Phase A high/low are exactly at extremes.
    bars.append(_make_bar(RELEASE_DT, 15, 13320.0, 13350.0, 13300.0, 13330.0))
    # Phase-B bars from +30 to +55.
    # +30 no break, +35 breaks UP (close 13380).
    bars.append(_make_bar(RELEASE_DT, 30, 13330.0, 13345.0, 13320.0, 13340.0))
    bars.append(_make_bar(RELEASE_DT, 35, 13340.0, 13385.0, 13335.0, 13380.0))
    bars.append(_make_bar(RELEASE_DT, 40, 13380.0, 13400.0, 13370.0, 13395.0))
    # Phase-C bars (after 35m) up to +175.
    bars.append(_make_bar(RELEASE_DT, 60, 13395.0, 13410.0, 13370.0, 13400.0))
    bars.append(_make_bar(RELEASE_DT, 90, 13400.0, 13420.0, 13360.0, 13390.0))
    bars.append(_make_bar(RELEASE_DT, 120, 13390.0, 13415.0, 13375.0, 13400.0))
    bars.append(_make_bar(RELEASE_DT, 175, 13400.0, 13405.0, 13385.0, 13390.0))
    _seed_rolling_cache(cache_dir, "GBPUSD", bars)

    now = RELEASE_DT + timedelta(minutes=181)
    row = mom.observe_release(_build_release(), "GBPUSD", now=now)

    assert row is not None, "observation row should be emitted"
    assert row["kind"] == "NEWS_MOMENTUM_OBS"
    assert row["symbol"] == "GBPUSD"
    assert row["release_key"] == f"Nonfarm Payrolls|{int(RELEASE_DT.timestamp())}"
    assert row["release_currency"] == "USD"
    assert row["release_impact"] == "HIGH"
    assert row["mode"] == "observe"
    # Phase-A range: 13300-13350 → width 50p (pip = 1 unit for scaled GBPUSD).
    assert row["range_high"] == 13350.0
    assert row["range_low"] == 13300.0
    assert row["range_width_pips"] == 50.0
    # Phase-B: break UP at +35 with close 13380.
    assert row["resolution_side"] == "UP"
    assert row["resolution_break_close"] == 13380.0
    assert row["resolution_minutes_from_release"] == 35
    # Body / range in pips for the break bar (13340 open, 13380 close,
    # 13335 low, 13385 high) → body 40p, range 50p.
    assert row["resolution_bar_body_pips"] == 40.0
    assert row["resolution_bar_range_pips"] == 50.0
    # Phase-C: MFE from 13380 = max(13410,13420,13415,13405) - 13380 = 40p.
    #          MAE from 13380 = 13380 - min(13370,13360,13375,13385) = 20p.
    assert row["mfe_pips"] == 40.0
    assert row["mae_pips"] == 20.0
    assert row["verdict"] == "observed"
    # No RA eval row seeded → spike fields null, agreement=no_spike.
    assert row["spike_direction"] is None
    assert row["spike_magnitude_pips"] is None
    assert row["agreement_with_spike"] == "no_spike"

    # Row was persisted to the observation log.
    log_path = logs_dir / "news_momentum_obs.jsonl"
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    persisted = json.loads(lines[0])
    assert persisted["release_key"] == row["release_key"]


# ── Test 2: no-resolution release → verdict=no_resolution ────────────────
def test_no_resolution_verdict(obs_env):
    mom, tmp_path = obs_env
    news_cache_dir = tmp_path / "news_cache"
    cache_dir = tmp_path / "cache"

    _seed_calendar(news_cache_dir, RELEASE_DT, currency="GBP")

    bars = []
    # Phase A: range [13300, 13350].
    bars.append(_make_bar(RELEASE_DT, 5, 13310.0, 13350.0, 13300.0, 13320.0))
    bars.append(_make_bar(RELEASE_DT, 15, 13320.0, 13340.0, 13305.0, 13325.0))
    bars.append(_make_bar(RELEASE_DT, 25, 13325.0, 13345.0, 13310.0, 13330.0))
    # Phase B: NO bar closes outside the range (all closes stay inside).
    for off in (30, 35, 40, 45, 50, 55):
        bars.append(_make_bar(RELEASE_DT, off,
                              13325.0, 13348.0, 13305.0, 13325.0))
    _seed_rolling_cache(cache_dir, "GBPUSD", bars)

    now = RELEASE_DT + timedelta(minutes=181)
    row = mom.observe_release(_build_release() | {"currency": "GBP"},
                              "GBPUSD", now=now)
    assert row is not None
    assert row["verdict"] == "no_resolution"
    assert row["resolution_side"] is None
    assert row["resolution_ts_utc"] is None
    # Range width still recorded — a no-break IS data.
    assert row["range_width_pips"] == 50.0
    # No resolution → no outcome excursion measurable.
    assert row["mfe_pips"] is None
    assert row["mae_pips"] is None


# ── Test 3: stale calendar → no row + reason logged ──────────────────────
def test_stale_calendar_no_row_logs_reason(obs_env, monkeypatch, caplog):
    mom, tmp_path = obs_env
    news_cache_dir = tmp_path / "news_cache"
    cache_dir = tmp_path / "cache"
    logs_dir = tmp_path / "logs"

    _seed_calendar(news_cache_dir, RELEASE_DT)
    # Force staleness — set max-age to 0h so any file is stale.
    monkeypatch.setenv("NEWS_CALENDAR_MAX_AGE_HOURS", "0")
    # Reload health so the new threshold takes effect.
    sys.modules.pop("news_calendar_health", None)
    sys.modules.pop("news_momentum_observer", None)
    import news_calendar_health  # noqa: F401
    import news_momentum_observer as mom_reloaded
    mom_reloaded._reset_state_for_tests()

    # A minimal rolling cache (contents unused when stale).
    _seed_rolling_cache(cache_dir, "GBPUSD", [
        _make_bar(RELEASE_DT, 10, 13300.0, 13310.0, 13290.0, 13305.0),
    ])

    now = RELEASE_DT + timedelta(minutes=181)
    with caplog.at_level(logging.DEBUG, logger="news_momentum_observer"):
        row = mom_reloaded.observe_release(_build_release(), "GBPUSD", now=now)
    assert row is None
    # No observation file written.
    assert not (logs_dir / "news_momentum_obs.jsonl").exists()
    # Reason logged with "stale" in it.
    assert any("stale_calendar" in rec.getMessage()
               for rec in caplog.records), caplog.text


# ── Test 4: observer exception cannot propagate ──────────────────────────
def test_observer_exception_never_propagates(obs_env, monkeypatch):
    mom, _ = obs_env
    # Force _compute_observation to blow up. observe_release must catch
    # it and return None — no exception should reach the caller (which
    # would be autobot's 5m close loop in production).
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated observer failure")
    monkeypatch.setattr(mom, "_compute_observation", _boom)

    # Also disable staleness so we get past the health gate.
    now = RELEASE_DT + timedelta(minutes=181)
    result = mom.observe_release(_build_release(), "GBPUSD", now=now)
    assert result is None
    # sweep() must also swallow — no cache dir populated so the internal
    # path may hit various failure modes; the contract is silence.
    assert mom.sweep(now=now, throttle_override=True) == 0


# ── Test 5: join to NEWS_STRATEGY eval row when present, null when absent
def test_join_to_release_anchored_eval(obs_env):
    mom, tmp_path = obs_env
    news_cache_dir = tmp_path / "news_cache"
    cache_dir = tmp_path / "cache"
    logs_dir = tmp_path / "logs"

    _seed_calendar(news_cache_dir, RELEASE_DT)

    # Seed a RA DECISION eval row for the same release_key + pair.
    release_key = f"Nonfarm Payrolls|{int(RELEASE_DT.timestamp())}"
    eval_row = {
        "kind": "RELEASE_ANCHORED_DECISION",
        "ts_utc": (RELEASE_DT + timedelta(minutes=20)).isoformat(),
        "symbol": "GBPUSD",
        "release_key": release_key,
        "spike_direction": "UP",
        "spike_magnitude_pips": 42.5,
        "verdict": "WOULD_FIRE",
    }
    (logs_dir / "news_strategy_evals.jsonl").write_text(
        json.dumps(eval_row) + "\n"
    )

    # Build cache with a break UP so agreement=continuation.
    bars = []
    bars.append(_make_bar(RELEASE_DT, 10, 13300.0, 13350.0, 13300.0, 13330.0))
    bars.append(_make_bar(RELEASE_DT, 25, 13330.0, 13345.0, 13310.0, 13340.0))
    bars.append(_make_bar(RELEASE_DT, 35, 13340.0, 13385.0, 13335.0, 13380.0))
    bars.append(_make_bar(RELEASE_DT, 90, 13380.0, 13400.0, 13370.0, 13390.0))
    _seed_rolling_cache(cache_dir, "GBPUSD", bars)

    now = RELEASE_DT + timedelta(minutes=181)
    row = mom.observe_release(_build_release(), "GBPUSD", now=now)
    assert row is not None
    assert row["spike_direction"] == "UP"
    assert row["spike_magnitude_pips"] == 42.5
    assert row["spike_source"] == "news_strategy_release_anchored_eval"
    assert row["agreement_with_spike"] == "continuation"


def test_join_null_safe_when_eval_log_absent(obs_env):
    mom, tmp_path = obs_env
    news_cache_dir = tmp_path / "news_cache"
    cache_dir = tmp_path / "cache"

    _seed_calendar(news_cache_dir, RELEASE_DT)
    # Deliberately do NOT create logs/news_strategy_evals.jsonl.
    bars = [
        _make_bar(RELEASE_DT, 10, 13300.0, 13350.0, 13300.0, 13330.0),
        _make_bar(RELEASE_DT, 25, 13330.0, 13340.0, 13310.0, 13320.0),
        _make_bar(RELEASE_DT, 35, 13320.0, 13330.0, 13305.0, 13315.0),
        _make_bar(RELEASE_DT, 90, 13315.0, 13320.0, 13300.0, 13310.0),
    ]
    _seed_rolling_cache(cache_dir, "GBPUSD", bars)

    now = RELEASE_DT + timedelta(minutes=181)
    row = mom.observe_release(_build_release(), "GBPUSD", now=now)
    assert row is not None
    # No eval-log join available → all spike fields null.
    assert row["spike_direction"] is None
    assert row["spike_magnitude_pips"] is None
    assert row["spike_source"] is None


# ── Test 6: outcome window not elapsed → no row ──────────────────────────
def test_outcome_window_not_elapsed_returns_none(obs_env):
    mom, tmp_path = obs_env
    _seed_calendar(tmp_path / "news_cache", RELEASE_DT)
    _seed_rolling_cache(tmp_path / "cache", "GBPUSD", [
        _make_bar(RELEASE_DT, 10, 13300.0, 13310.0, 13290.0, 13305.0),
    ])
    # now is only +90 minutes — outcome window ends at +180.
    now = RELEASE_DT + timedelta(minutes=90)
    row = mom.observe_release(_build_release(), "GBPUSD", now=now)
    assert row is None


# ── Test 7: dedup — second call for same (release, pair) returns None ────
def test_dedup_on_repeat_call(obs_env):
    mom, tmp_path = obs_env
    _seed_calendar(tmp_path / "news_cache", RELEASE_DT)
    _seed_rolling_cache(tmp_path / "cache", "GBPUSD", [
        _make_bar(RELEASE_DT, 10, 13300.0, 13350.0, 13300.0, 13330.0),
        _make_bar(RELEASE_DT, 35, 13330.0, 13385.0, 13320.0, 13380.0),
    ])
    now = RELEASE_DT + timedelta(minutes=181)
    first = mom.observe_release(_build_release(), "GBPUSD", now=now)
    second = mom.observe_release(_build_release(), "GBPUSD", now=now)
    assert first is not None
    assert second is None


# ── Test 8: mode=off → sweep is a total no-op ────────────────────────────
def test_mode_off_sweep_noop(obs_env, monkeypatch):
    mom, tmp_path = obs_env
    monkeypatch.setenv("NEWS_MOMENTUM_MODE", "off")
    _seed_calendar(tmp_path / "news_cache", RELEASE_DT)
    _seed_rolling_cache(tmp_path / "cache", "GBPUSD", [
        _make_bar(RELEASE_DT, 10, 13300.0, 13350.0, 13300.0, 13330.0),
        _make_bar(RELEASE_DT, 35, 13330.0, 13385.0, 13320.0, 13380.0),
    ])
    now = RELEASE_DT + timedelta(minutes=181)
    assert mom.sweep(now=now, throttle_override=True) == 0
    # No log file created.
    assert not (tmp_path / "logs" / "news_momentum_obs.jsonl").exists()


# ── Test 9: sweep picks up qualifying release and emits per-pair rows ────
def test_sweep_emits_one_row_per_affected_pair(obs_env):
    mom, tmp_path = obs_env
    # USD release affects GBPUSD, EURUSD, USDJPY, USDCAD (4 pairs).
    _seed_calendar(tmp_path / "news_cache", RELEASE_DT, currency="USD")
    for pair in ("GBPUSD", "EURUSD", "USDJPY", "USDCAD"):
        _seed_rolling_cache(tmp_path / "cache", pair, [
            _make_bar(RELEASE_DT, 10, 13300.0, 13350.0, 13300.0, 13330.0),
            _make_bar(RELEASE_DT, 35, 13330.0, 13385.0, 13320.0, 13380.0),
        ])
    now = RELEASE_DT + timedelta(minutes=181)
    emitted = mom.sweep(now=now, throttle_override=True)
    assert emitted == 4


# ── Test 10: env-layer declares the mode + all five thresholds ───────────
def test_env_layered_declares_momentum_config():
    gates = (REPO / "env" / "40-gates.env").read_text()
    infra = (REPO / "env" / "10-infrastructure.env").read_text()
    assert "NEWS_MOMENTUM_MODE=observe" in gates
    for k in ("NEWS_MOM_RANGE_START_MIN=5",
              "NEWS_MOM_RANGE_END_MIN=30",
              "NEWS_MOM_OBS_START_MIN=30",
              "NEWS_MOM_OBS_END_MIN=60",
              "NEWS_MOM_OUTCOME_END_MIN=180"):
        assert k in infra, f"{k} missing from env/10-infrastructure.env"


# ── Test 11: autobot dispatch hook is wired ──────────────────────────────
def test_autobot_wires_sweep_hook_source_shape():
    src = (REPO / "autobot.py").read_text()
    # The hook is in _on_5m_close_log, imports the module, and calls sweep().
    assert "import news_momentum_observer as _ns_mom" in src
    assert "_ns_mom.sweep()" in src
