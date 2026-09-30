"""Runtime configuration loader.

Reads environment variables (or a .env file loaded by the caller) into
a strongly-typed dataclass with safe defaults. LIVE broker accounts are
rejected: the loader raises immediately if IG_ACCOUNT_TYPE != "DEMO".
Execution is disabled by default; the operator must set
TREND_EXECUTION_ENABLED=1 explicitly to allow order submission.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _get_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return float(v)


def _get_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return int(v)


def _get_str(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v.strip() if v is not None else default


@dataclass
class TrendRunnerConfig:
    # Storage
    data_dir: str
    ledger_path: str
    outbox_path: str
    state_path: str
    lock_path: str
    log_dir: str

    # Symbol / instrument
    epic: str
    pip_size: float
    min_broker_distance_pips: float
    min_size: float

    # Strategy
    stake_gbp_per_pip: float
    max_risk_pips: float
    max_late_entry_pips: float

    # Execution / broker
    execution_enabled: bool
    ig_account_type: str  # must be "DEMO"
    ig_username: Optional[str]
    ig_api_key: Optional[str]
    ig_base_url: str

    # Streaming / recorder
    use_recorder_tail: bool
    recorder_path: str

    # Telegram
    telegram_bot_token: Optional[str]
    telegram_chat_id: Optional[str]


def load_config(env: dict[str, str] | None = None) -> TrendRunnerConfig:
    if env is not None:
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
    try:
        data_dir = _get_str("TREND_DATA_DIR", "/home/autobot/trend-runner/data")
        cfg = TrendRunnerConfig(
            data_dir=data_dir,
            ledger_path=_get_str("TREND_LEDGER_PATH", f"{data_dir}/ledger.jsonl"),
            outbox_path=_get_str("TREND_OUTBOX_PATH", f"{data_dir}/telegram_outbox.jsonl"),
            state_path=_get_str("TREND_STATE_PATH", f"{data_dir}/state.json"),
            lock_path=_get_str("TREND_LOCK_PATH", f"{data_dir}/trend-runner.lock"),
            log_dir=_get_str("TREND_LOG_DIR", "/home/autobot/trend-runner/logs"),
            epic=_get_str("TREND_EPIC", "CS.D.GBPUSD.MINI.IP"),
            pip_size=_get_float("TREND_PIP_SIZE", 1.0),
            min_broker_distance_pips=_get_float("TREND_MIN_BROKER_DISTANCE_PIPS", 4.0),
            min_size=_get_float("TREND_MIN_SIZE", 0.5),
            stake_gbp_per_pip=_get_float("TREND_STAKE_GBP_PER_PIP", 2.0),
            max_risk_pips=_get_float("TREND_MAX_RISK_PIPS", 30.0),
            max_late_entry_pips=_get_float("TREND_MAX_LATE_ENTRY_PIPS", 25.0),
            execution_enabled=_get_bool("TREND_EXECUTION_ENABLED", False),
            ig_account_type=_get_str("IG_ACCOUNT_TYPE", "DEMO"),
            ig_username=os.environ.get("IG_USERNAME"),
            ig_api_key=os.environ.get("IG_API_KEY"),
            ig_base_url=_get_str("IG_BASE_URL", "https://demo-api.ig.com/gateway/deal"),
            use_recorder_tail=_get_bool("TREND_USE_RECORDER_TAIL", True),
            recorder_path=_get_str("TREND_RECORDER_PATH", "/opt/tradingbot/logs/price_streamer.jsonl"),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
        )
    finally:
        if env is not None:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    if cfg.ig_account_type.upper() != "DEMO":
        raise RuntimeError(
            f"Trend Runner refuses to run against IG_ACCOUNT_TYPE={cfg.ig_account_type!r};"
            " only DEMO is permitted."
        )
    return cfg
