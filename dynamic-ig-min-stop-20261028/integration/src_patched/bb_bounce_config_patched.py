"""
config.py — BB Bounce standalone constants.

All paths and tuning constants live here. Env vars are loaded by
ig_auth at import time from /opt/bb_bounce/.env (explicit path).
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Instrument -------------------------------------------------
EPIC = "CS.D.GBPUSD.TODAY.IP"
SYMBOL = "GBPUSD"

# IG spread-bet FX: 1 point = 1 pip (verified Stage 1 + signal_log
# evidence 2026-09-24 BB_BOUNCE_L entry/sl arithmetic). Distances sent
# to IG are PLAIN pip counts.
PIP = 0.0001  # one pip in quote-level terms (for human diagnostics only)
# 2026-10-28 — env-overridable so the operator can reconfigure the
# strategy's requested TP/SL without a code deploy.  Defaults match
# the historical production values; no behavioural change until the
# operator explicitly sets BB_SL_PIPS / BB_TP_PIPS in /opt/bb_bounce/.env.
TP_PIPS = int(float(os.getenv("BB_TP_PIPS", "30")))
SL_PIPS = int(float(os.getenv("BB_SL_PIPS", "12")))
TRADE_SIZE = 2.0  # £2 per pip

# --- Stop-loss mode (NEW; default preserves historical production) --
# "FIXED_12"      → legacy: fixed 12-pip stop from entry fill.
# "STRUCTURAL_3"  → stop at min(C1.low,C2.low) − 3p for BUY, mirror SELL.
# "SHADOW"        → compute both FIXED_12 and STRUCTURAL_3 propositions
#                   and record them to the shadow log; DO NOT submit any
#                   order (see shadow_mode.py).
# Default FIXED_12 so production behaviour is unchanged until the
# operator switches explicitly via the env var.
BB_STOP_MODE = os.getenv("BB_STOP_MODE", "FIXED_12")

# Structural-stop buffer (pips BEYOND the rejection extreme). Default
# 3.0 matches Test 12H B3 — the best structural buffer tested.
STRUCTURAL_BUFFER_PIPS = float(os.getenv("BB_STRUCTURAL_BUFFER_PIPS", "3.0"))

# IG platform constraints — AUTHORITATIVE EVIDENCE:
# * minNormalStopOrLimitDistance for GBPUSD DFB = 4.0 POINTS (= 4.0 pips).
#   Captured live 2026-09-27 via GET /markets/CS.D.GBPUSD.TODAY.IP; see
#   /opt/tradingbot/reports-public/2026-09-27_bb_scalp_2wk/dealing_rules.json
#   and the companion report §3. Cross-verified against the 2026-07-20
#   storm-day log: 08:00:29 accepted at 7.35p, 08:00:30 rejected at 1.55p.
# * minControlledRiskStopDistance = 8.0 POINTS (not used — we submit
#   guaranteedStop=False, so the hard floor is 4.0 not 8.0).
# * minDealSize = 0.03 PERCENTAGE (unit coding ambiguous for FX DFB).
#   AutoBot V3 uses an in-house policy floor of 0.5 (.env.example:131
#   MIN_SIZE=0.5), which is above any plausible interpretation of 0.03,
#   so we use 0.5 here as the practical conservative floor.
# * minStepDistance = 1.0 POINTS (relevant only to amend; we don't
#   amend on open).
# Values may be overridden by env for operator control.
IG_MIN_STOP_PIPS = float(os.getenv("BB_IG_MIN_STOP_PIPS", "4.0"))
IG_MIN_STAKE = float(os.getenv("BB_IG_MIN_STAKE", "0.5"))
IG_STAKE_INCREMENT = float(os.getenv("BB_IG_STAKE_INCREMENT", "0.1"))

# Reference cash risk: TRADE_SIZE × SL_PIPS (= £2 × 12 = £24 historically).
# Under STRUCTURAL_3, when the structural stop is WIDER than SL_PIPS, the
# stake is reduced so the initial cash risk never exceeds this reference.
# When the structural stop is TIGHTER than SL_PIPS, the stake is NOT
# increased — the default TRADE_SIZE is preserved (less cash risk is
# accepted; never silently increased).
REFERENCE_RISK_POUNDS = float(os.getenv("BB_REFERENCE_RISK_POUNDS",
                                         str(TRADE_SIZE * SL_PIPS)))

# --- Bollinger -------------------------------------------------
BB_PERIOD = 20
BB_STDDEV = 2.0
BB_WARMUP_BARS = BB_PERIOD  # min closed bars before any band evaluation
HISTORY_LOAD_BARS = 60  # bars loaded at boot from earlier daily files

# --- Setup window ----------------------------------------------
BAR_SECONDS = 300
C2_FOLLOW_SECONDS = 300  # C2 must be exactly 5 min after C1
VALIDITY_SECONDS_FROM_C2_CLOSE = 1800  # 30 min from C2 CLOSE (A7)

# --- Deal reference / ownership --------------------------------
MODE_TAG = "BBB"  # dealReference becomes HBB-BBB-<epoch10>

# --- Paths -----------------------------------------------------
AUTOBOT_CANDLES_DIR = Path(
    os.getenv("AUTOBOT_CANDLES_DIR", "/opt/tradingbot/data/candles/GBPUSD")
)
REPORTS_DIR = Path(os.getenv("BB_REPORTS_DIR", "/opt/bb_bounce/reports"))
STATE_DIR = Path(os.getenv("BB_STATE_DIR", "/opt/bb_bounce/state"))

# Shadow mode writes side-by-side FIXED_12 vs STRUCTURAL_3 propositions
# to this file (append-only JSONL). Never submits an order.
SHADOW_LOG_PATH = Path(os.getenv("BB_SHADOW_LOG",
                                   str(STATE_DIR / "shadow_log.jsonl")))

# --- Loop cadence ----------------------------------------------
POLL_SECONDS = float(os.getenv("BB_POLL_SECONDS", "2.0"))

# --- Rounding (addition #4) ------------------------------------
PRICE_DECIMALS = 2  # candle values rounded to 2 dp before any use
