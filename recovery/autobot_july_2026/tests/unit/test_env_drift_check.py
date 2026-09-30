"""Tests for scripts/env_drift_check.py — ITEM 1."""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path("/opt/tradingbot")
SCRIPT_PATH = REPO_ROOT / "scripts" / "env_drift_check.py"


def _load_module(monkeypatch, tmp_path, *, env_history_dir=None, env_file=None,
                 log_file=None):
    """Load env_drift_check.py fresh with paths pointing at tmp fixtures."""
    spec = importlib.util.spec_from_file_location(
        "env_drift_check_under_test", str(SCRIPT_PATH)
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if env_history_dir is not None:
        monkeypatch.setattr(mod, "ENV_HISTORY_DIR", Path(env_history_dir))
    if env_file is not None:
        monkeypatch.setattr(mod, "ENV_FILE", Path(env_file))
    if log_file is not None:
        monkeypatch.setattr(mod, "LOG_FILE", Path(log_file))
    for h in list(logging.getLogger("env_drift_check").handlers):
        logging.getLogger("env_drift_check").removeHandler(h)
    return mod


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_diff_correct_name_lists(monkeypatch, tmp_path):
    hist = tmp_path / "env-history"
    envf = tmp_path / ".env"
    logf = tmp_path / "logs" / "env_drift.log"
    _write(hist / "env.20260101T000000Z", "FOO=1\nBAR=2\nGONE=3\n")
    _write(hist / "env.20260101T010000Z", "FOO=1\nBAR=99\nNEW=4\n")
    _write(envf, "TELEGRAM_TOKEN=t\nTELEGRAM_CHAT_ID=c\nALERT_HOST_LABEL=HOST\n")

    mod = _load_module(monkeypatch, tmp_path, env_history_dir=hist,
                       env_file=envf, log_file=logf)

    sent = {}

    def _fake_send(env, text, log):
        sent["env"] = env
        sent["text"] = text

    monkeypatch.setattr(mod, "_send_telegram", _fake_send)

    assert mod.main() == 0
    assert "text" in sent, "expected a Telegram send"
    msg = sent["text"]
    assert msg.startswith("[HOST] CONFIG DRIFT at boot: "), msg
    assert "1 changed (BAR)" in msg
    assert "1 removed (GONE)" in msg
    assert "1 added (NEW)" in msg
    # value must never appear in message
    assert "99" not in msg
    assert "2" not in msg or " 2 " not in msg  # count-of-changed uses digit; per-value 2 absent


def test_no_prior_snapshot_silent(monkeypatch, tmp_path):
    hist = tmp_path / "env-history"
    hist.mkdir()
    _write(hist / "env.20260101T000000Z", "FOO=1\n")
    envf = tmp_path / ".env"
    _write(envf, "TELEGRAM_TOKEN=t\nTELEGRAM_CHAT_ID=c\n")
    logf = tmp_path / "logs" / "env_drift.log"

    mod = _load_module(monkeypatch, tmp_path, env_history_dir=hist,
                       env_file=envf, log_file=logf)
    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda env, text, log: sent.append(text))
    assert mod.main() == 0
    assert sent == []


def test_no_drift_silent(monkeypatch, tmp_path):
    hist = tmp_path / "env-history"
    _write(hist / "env.20260101T000000Z", "FOO=1\nBAR=2\n")
    _write(hist / "env.20260101T010000Z", "FOO=1\nBAR=2\n")
    envf = tmp_path / ".env"
    _write(envf, "TELEGRAM_TOKEN=t\nTELEGRAM_CHAT_ID=c\n")
    logf = tmp_path / "logs" / "env_drift.log"

    mod = _load_module(monkeypatch, tmp_path, env_history_dir=hist,
                       env_file=envf, log_file=logf)
    sent = []
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda env, text, log: sent.append(text))
    assert mod.main() == 0
    assert sent == []


def test_script_exits_zero_on_forced_exception(monkeypatch, tmp_path):
    hist = tmp_path / "env-history"
    _write(hist / "env.a", "FOO=1\n")
    _write(hist / "env.b", "FOO=2\n")
    envf = tmp_path / ".env"
    _write(envf, "TELEGRAM_TOKEN=t\nTELEGRAM_CHAT_ID=c\n")
    logf = tmp_path / "logs" / "env_drift.log"

    mod = _load_module(monkeypatch, tmp_path, env_history_dir=hist,
                       env_file=envf, log_file=logf)

    def _boom(*a, **kw):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(mod, "_diff", _boom)
    assert mod.main() == 0
    # log file created and contains the traceback
    assert logf.exists()
    content = logf.read_text(encoding="utf-8")
    assert "simulated failure" in content


def test_name_list_capped_at_15(monkeypatch, tmp_path):
    hist = tmp_path / "env-history"
    prev_lines = "\n".join(f"K{i}=v{i}" for i in range(30)) + "\n"
    curr_lines = "\n".join(f"K{i}=vX" for i in range(30)) + "\n"
    _write(hist / "env.a", prev_lines)
    _write(hist / "env.b", curr_lines)
    envf = tmp_path / ".env"
    _write(envf, "TELEGRAM_TOKEN=t\nTELEGRAM_CHAT_ID=c\n")
    logf = tmp_path / "logs" / "env_drift.log"

    mod = _load_module(monkeypatch, tmp_path, env_history_dir=hist,
                       env_file=envf, log_file=logf)
    sent = {}
    monkeypatch.setattr(mod, "_send_telegram",
                        lambda env, text, log: sent.setdefault("text", text))
    assert mod.main() == 0
    msg = sent["text"]
    assert "30 changed" in msg
    assert "+15 more" in msg


def test_script_subprocess_returns_zero_when_history_absent(tmp_path):
    """End-to-end: invoke the script binary, no history dir, should exit 0."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
        },
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
