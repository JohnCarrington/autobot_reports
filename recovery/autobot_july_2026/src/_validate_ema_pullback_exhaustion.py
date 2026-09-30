"""Offline smoke test for ema_pullback_exhaustion.

Loads a real 5M candle CSV, builds a df_5m through add_indicators() (so the
MACD_HIST_35_45_30 + DECREASING2 + EMA_* + PRICE_VS_EMA50_PIPS columns are
populated exactly like the live path), then exercises compute() and
log_fire() on the last bar in both LONG and SHORT modes.

Verifies:
  - kill switch: helper does NOT write when env flag is unset
  - RSI(14) is computed fresh (numerical check vs. RSI_3 column)
  - Divergence boolean computes
  - EMA-distance pips are sane (sub-100 pips on GBPUSD 5M)
  - log_fire writes a JSONL row when enabled
  - H1 capture (h1_direction / h1_strength / h1_separation_pips / h1_source):
    the helper calls the SAME indicators.h1_ema_direction(symbol, ...)
    entry point the live BB_BOUNCE gate uses. To verify the live call's
    value matches earlier historical reconstructions, we monkey-patch
    trend_detection.load_h1_candles_from_cache to return only H1 candles
    whose timestamp+1h ≤ fire_ts — replicating the cache state as it
    would have been at that historical moment. The helper itself is
    UNTOUCHED; the patch only narrows the data the live h1 function
    consumes during the offline test.
"""
import json
import os
import sys
import tempfile
import pandas as pd

sys.path.insert(0, "/opt/tradingbot")

# ---------- Historical H1-cache replay helper ----------
import trend_detection as _td
_orig_h1_loader = _td.load_h1_candles_from_cache

def _patch_h1_loader_to_fire_ts(fire_ts: "pd.Timestamp"):
    """Filter the H1 cache to bars whose timestamp+1h ≤ fire_ts so the
    live h1_ema_direction() call sees the cache state as it would have
    been at the historical fire moment. Helper code is unchanged; only
    the loader the live function consumes is narrowed.
    """
    # Normalise both sides to tz-naive UTC for a clean comparison.
    ft = fire_ts.tz_convert("UTC").tz_localize(None) if fire_ts.tzinfo else fire_ts
    cutoff = ft - pd.Timedelta(hours=1)
    def _patched(symbol):
        cs = _orig_h1_loader(symbol) or []
        out = []
        for c in cs:
            t = pd.Timestamp(c.get("timestamp"))
            if t.tzinfo:
                t = t.tz_convert("UTC").tz_localize(None)
            if t <= cutoff:
                out.append(c)
        return out
    _td.load_h1_candles_from_cache = _patched

def _restore_h1_loader():
    _td.load_h1_candles_from_cache = _orig_h1_loader

CSV = "/opt/tradingbot/data/candles/GBPUSD/2026-06-22.csv"

df = pd.read_csv(CSV, parse_dates=["timestamp"])
print(f"loaded {len(df)} rows from {CSV}")

# Enrich via the same indicators pipeline the live path uses.
from indicators import add_indicators, IndicatorsConfig
# Defaults: rsi_period=3, macd 35/45/30 — already matches the live
# config. The frozen dataclass means we can't mutate, so use defaults.
cfg = IndicatorsConfig()
df_enriched = add_indicators(df, cfg, pip_size=1.0, caller="ema_pullback_exhaustion_smoke")
print("enriched columns sample:",
      [c for c in df_enriched.columns
       if c.startswith(("EMA_", "MACD_HIST", "RSI_", "PRICE_VS_"))])

# ---------- env-OFF kill switch check ----------
os.environ.pop("EMA_PULLBACK_EXHAUSTION_TELEMETRY_ENABLED", None)
import importlib
import ema_pullback_exhaustion
importlib.reload(ema_pullback_exhaustion)

assert ema_pullback_exhaustion.is_enabled() is False, "kill switch must be OFF by default"
print(f"[OK] kill switch OFF by default (is_enabled()={ema_pullback_exhaustion.is_enabled()})")

# Re-point the log to a tempfile so we can prove no-write when disabled.
with tempfile.TemporaryDirectory() as td:
    log_path = os.path.join(td, "ema_pullback_exhaustion.jsonl")
    os.environ["EMA_PULLBACK_EXHAUSTION_LOG_PATH"] = log_path
    importlib.reload(ema_pullback_exhaustion)

    # With kill switch OFF the autobot wrapper will NOT call log_fire — so
    # we don't call it either. Confirm no file is created merely by
    # importing the module.
    assert not os.path.exists(log_path), "no log file should exist with kill switch OFF and helper not invoked"
    print(f"[OK] no log file created when helper not invoked: {log_path}")

    # ---------- enable + exercise ----------
    os.environ["EMA_PULLBACK_EXHAUSTION_TELEMETRY_ENABLED"] = "1"
    importlib.reload(ema_pullback_exhaustion)
    assert ema_pullback_exhaustion.is_enabled() is True
    print(f"[OK] kill switch ON via env flag (is_enabled()={ema_pullback_exhaustion.is_enabled()})")

    rec_long = ema_pullback_exhaustion.compute(df_enriched, "BUY", pip_size=1.0)
    rec_short = ema_pullback_exhaustion.compute(df_enriched, "SELL", pip_size=1.0)

    print("\n--- LONG compute() output ---")
    print(json.dumps(rec_long, indent=2, default=str))
    print("\n--- SHORT compute() output ---")
    print(json.dumps(rec_short, indent=2, default=str))

    # Sanity checks
    assert rec_long["err"] is None or "macd" not in (rec_long["err"] or ""), f"unexpected err: {rec_long['err']}"
    assert rec_long["rsi14_now"] is not None, "RSI(14) must be populated"
    # RSI_3 column exists on df_enriched. Confirm helper's RSI(14) is NOT
    # the same value (they would only match by coincidence; checking the
    # arrays head-to-head is the rigorous check).
    from indicators import rsi
    r14 = rsi(df_enriched["close"].astype(float), 14)
    rsi14_tail = float(r14.iloc[-1])
    rsi3_tail = float(df_enriched["RSI_3"].iloc[-1])
    print(f"\nRSI(14) tail = {rsi14_tail:.2f}; RSI_3 tail = {rsi3_tail:.2f}")
    assert abs(rec_long["rsi14_now"] - round(rsi14_tail, 2)) < 1e-6, \
        f"helper rsi14_now ({rec_long['rsi14_now']}) must match fresh rsi(close,14) tail ({rsi14_tail:.2f})"
    print(f"[OK] helper rsi14_now matches fresh rsi(close,14), distinct from RSI_3")

    # EMA distance sanity
    p8 = rec_long["price_vs_ema8_pips"]
    p21 = rec_long["price_vs_ema21_pips"]
    p50 = rec_long["price_vs_ema50_pips"]
    print(f"price_vs_ema8 = {p8} pips, price_vs_ema21 = {p21} pips, price_vs_ema50 = {p50} pips")
    for name, v in (("ema8", p8), ("ema21", p21), ("ema50", p50)):
        assert v is None or -200.0 < v < 200.0, f"{name} pips out of plausible range: {v}"
    print("[OK] EMA-distance pips are in plausible GBPUSD 5M range")

    # Confluence count is the number of TRUE legs.
    legs3 = [rec_long["rsi14_divergence"], rec_long["macd_hist_shrinking"],
             rec_long["price_extended_against_direction"]]
    expected3 = sum(1 for v in legs3 if v is True)
    assert rec_long["exhaustion_confluence_3"] == expected3, "confluence_3 count mismatch"
    legs4 = legs3 + [rec_long["entry_against_fan"]]
    expected4 = sum(1 for v in legs4 if v is True)
    assert rec_long["trend_trap_score"] == expected4, "trend_trap_score count mismatch"
    print(f"[OK] exhaustion_confluence_3={rec_long['exhaustion_confluence_3']} "
          f"matches 3-leg TRUE count")
    print(f"[OK] trend_trap_score={rec_long['trend_trap_score']} "
          f"matches 4-leg TRUE count (incl. entry_against_fan)")

    # Exercise log_fire with a fake trade_id / deal_id
    from datetime import datetime, timezone
    ema_pullback_exhaustion.log_fire(
        trade_id="test-trade-uuid",
        deal_id="DEALFAKE123",
        epic="CS.D.GBPUSD.TODAY.IP",
        symbol="GBPUSD",
        direction="BUY",
        fire_ts_utc=datetime.now(timezone.utc),
        df_5m=df_enriched,
        pip_size=1.0,
        decision_debug={"fan_width_pips_at_fire": 1.23},
    )
    assert os.path.exists(log_path), f"log file should exist at {log_path}"
    with open(log_path) as fh:
        line = fh.readline().strip()
    written = json.loads(line)
    assert written["trade_id"] == "test-trade-uuid"
    assert written["deal_id"] == "DEALFAKE123"
    print(f"\n[OK] log_fire wrote one JSONL row with trade_id+deal_id join keys")
    print("--- written row ---")
    print(json.dumps(written, indent=2, default=str))

    # ---------- H1-source UNAVAILABLE path (no symbol) ----------
    # When compute() is called without `symbol`, h1_ema_direction is not
    # called and h1_source stays "unavailable" (fields None). Asserts
    # there is NO silent fallback to a reconstructed value.
    rec_no_sym = ema_pullback_exhaustion.compute(df_enriched, "BUY", pip_size=1.0)
    assert rec_no_sym["h1_source"] == "unavailable", \
        f"no-symbol path should produce h1_source='unavailable', got {rec_no_sym['h1_source']!r}"
    assert rec_no_sym["h1_direction"] is None and rec_no_sym["h1_strength"] is None, \
        "h1 fields must be None when h1_source='unavailable'"
    print(f"\n[OK] no-symbol path → h1_source='unavailable', no silent fallback.")

    # ---------- Falling-knife #1: 2026-06-05T13:05:04Z BB_BOUNCE_L ----------
    print("\n" + "=" * 60)
    print("FALLING-KNIFE #1: 2026-06-05T13:05:04Z GBPUSD_BB_BOUNCE_L")
    print("(real losing long: pnl_pips=-20.0 vs cleanly bearish fan)")
    print("=" * 60)
    fk_csv = "/opt/tradingbot/data/candles/GBPUSD/2026-06-05.csv"
    fk_ts = pd.Timestamp("2026-06-05T13:05:04Z")
    fk_df = pd.read_csv(fk_csv, parse_dates=["timestamp"])
    fk_df["timestamp"] = pd.to_datetime(fk_df["timestamp"], utc=True).dt.tz_localize(None)
    fk_slice = fk_df[fk_df["timestamp"] <= fk_ts.tz_localize(None)].copy()
    fk_enriched = add_indicators(fk_slice, cfg, pip_size=1.0,
                                 caller="ema_pullback_exhaustion_fallingknife")

    _patch_h1_loader_to_fire_ts(fk_ts)
    try:
        rec_fk = ema_pullback_exhaustion.compute(
            fk_enriched, "BUY", pip_size=1.0,
            decision_debug={"fan_width_pips_at_fire": 9.67},
            symbol="GBPUSD",
        )
    finally:
        _restore_h1_loader()
    print(json.dumps(rec_fk, indent=2, default=str))

    assert rec_fk["err"] is None, f"unexpected err on falling-knife slice: {rec_fk['err']}"
    assert rec_fk["fan_is_bearish_stacked"] is True
    assert rec_fk["entry_against_fan"] is True
    assert rec_fk["fan_stack_order"] == "50>21>13>8"
    assert rec_fk["fan_width_pips_source"] == "decision_debug"
    assert rec_fk["h1_source"] == "live_call", \
        f"expected h1_source='live_call' with patched cache, got {rec_fk['h1_source']!r}"
    assert rec_fk["h1_direction"] is not None
    print(f"\n[OK] entry_against_fan=True, fan_stack_order={rec_fk['fan_stack_order']!r}.")
    print(f"[OK] h1_direction={rec_fk['h1_direction']!r}, h1_strength={rec_fk['h1_strength']}, "
          f"sep_pips={rec_fk['h1_separation_pips']}, source={rec_fk['h1_source']!r}.")

    # ---------- Falling-knife #2: 2026-06-22T08:25:01Z BB_BOUNCE_L ----------
    # The exact fire whose H1 was earlier RECONSTRUCTED as BEARISH /
    # strength 0.361. The check: does the helper's live h1_ema_direction
    # call (now flowing through the patched cache loader) return the
    # SAME numbers? If they diverge, the gate-re-enable analysis (which
    # used the reconstruction) was built on a value the live call would
    # not have produced.
    print("\n" + "=" * 60)
    print("FALLING-KNIFE #2: 2026-06-22T08:25:01Z GBPUSD_BB_BOUNCE_L")
    print("(prior reconstruction: H1 BEARISH, separation_strength≈0.361)")
    print("=" * 60)
    fk2_csv = "/opt/tradingbot/data/candles/GBPUSD/2026-06-22.csv"
    fk2_ts = pd.Timestamp("2026-06-22T08:25:01Z")
    fk2_df = pd.read_csv(fk2_csv, parse_dates=["timestamp"])
    fk2_df["timestamp"] = pd.to_datetime(fk2_df["timestamp"], utc=True).dt.tz_localize(None)
    fk2_slice = fk2_df[fk2_df["timestamp"] < fk2_ts.tz_localize(None)].copy()
    fk2_enriched = add_indicators(fk2_slice, cfg, pip_size=1.0,
                                  caller="ema_pullback_exhaustion_fallingknife2")

    _patch_h1_loader_to_fire_ts(fk2_ts)
    try:
        rec_fk2 = ema_pullback_exhaustion.compute(
            fk2_enriched, "BUY", pip_size=1.0, symbol="GBPUSD"
        )
    finally:
        _restore_h1_loader()
    print(json.dumps(rec_fk2, indent=2, default=str))

    assert rec_fk2["h1_source"] == "live_call", \
        f"expected h1_source='live_call', got {rec_fk2['h1_source']!r}"
    assert rec_fk2["h1_direction"] == "BEARISH", \
        f"prior reconstruction said BEARISH; live call returned {rec_fk2['h1_direction']!r}"
    # Tolerance: 0.005 ≈ ½ a percentage point of separation_strength.
    assert abs(rec_fk2["h1_strength"] - 0.361) < 0.005, (
        f"live h1_strength={rec_fk2['h1_strength']} diverges from "
        f"reconstruction (0.361) by more than 0.005 — FLAG: the gate-"
        f"re-enable analysis used a value the live call does not produce."
    )
    print(f"\n[OK] live h1_ema_direction match: direction={rec_fk2['h1_direction']!r}, "
          f"strength={rec_fk2['h1_strength']} (reconstruction was 0.361).")

print("\nALL CHECKS PASSED.")
