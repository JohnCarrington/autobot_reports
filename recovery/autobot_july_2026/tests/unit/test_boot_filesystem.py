"""Tests for filesystem_paths.ensure_output_directories and
filesystem_paths.verify_output_directories_writable.

Covers the failure modes the 2026-05-06 NY miss exposed:
  - missing dirs: created
  - existing dir, wrong owner: WARNING only, no auto-fix
  - mkdir failure: logged WARNING, doesn't crash (probe is the gate)
  - probe failure: ERROR + telegram + sys.exit(1)
  - probe success: INFO log, returns count
  - non-root chown failure: logged, doesn't crash
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import filesystem_paths as fsp


# ────────────────────────────────────────────────────────────────────────
# ensure_output_directories
# ────────────────────────────────────────────────────────────────────────

def test_ensure_creates_missing_dirs(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "nested" / "b"
    assert not a.exists() and not b.exists()
    fsp.ensure_output_directories([a, b])
    assert a.is_dir() and b.is_dir()


def test_ensure_existing_correct_owner_silent(tmp_path, caplog):
    d = tmp_path / "d"
    d.mkdir()
    # Whatever owner we have right now is, by definition, the "correct"
    # one for the running user. Patch the resolver to match.
    st = d.stat()
    with patch.object(fsp, "_resolve_target_uid_gid", return_value=(st.st_uid, st.st_gid)):
        with caplog.at_level(logging.WARNING, logger="AutoBot"):
            fsp.ensure_output_directories([d])
    assert "exists with owner" not in caplog.text


def test_ensure_existing_wrong_owner_warns_no_fix(tmp_path, caplog):
    d = tmp_path / "d"
    d.mkdir()
    st = d.stat()
    bogus_uid = st.st_uid + 999
    bogus_gid = st.st_gid + 999
    with patch.object(fsp, "_resolve_target_uid_gid", return_value=(bogus_uid, bogus_gid)):
        with caplog.at_level(logging.WARNING, logger="AutoBot"):
            fsp.ensure_output_directories([d])
    assert "exists with owner" in caplog.text
    assert "init_filesystem.sh" in caplog.text
    # No auto-fix: original ownership preserved.
    assert d.stat().st_uid == st.st_uid


def test_ensure_mkdir_failure_warns_does_not_crash(tmp_path, caplog):
    d = tmp_path / "would_be_created"
    with patch.object(Path, "mkdir", side_effect=PermissionError("nope")):
        with caplog.at_level(logging.WARNING, logger="AutoBot"):
            fsp.ensure_output_directories([d])
    assert "mkdir" in caplog.text and "failed" in caplog.text


def test_ensure_chown_failure_on_root_warns_does_not_crash(tmp_path, caplog):
    d = tmp_path / "d"
    # Pretend we're root so the chown branch is reached.
    with patch.object(os, "geteuid", return_value=0), \
         patch.object(fsp, "_resolve_target_uid_gid", return_value=(99999, 99999)), \
         patch.object(os, "chown", side_effect=PermissionError("denied")):
        with caplog.at_level(logging.WARNING, logger="AutoBot"):
            fsp.ensure_output_directories([d])
    assert d.is_dir()
    assert "chown" in caplog.text and "failed" in caplog.text


# ────────────────────────────────────────────────────────────────────────
# verify_output_directories_writable
# ────────────────────────────────────────────────────────────────────────

def test_verify_success_returns_count(tmp_path, caplog):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    telegram = MagicMock()
    exit_fn = MagicMock()
    with caplog.at_level(logging.INFO, logger="AutoBot"):
        n = fsp.verify_output_directories_writable(
            [a, b], telegram_send=telegram, exit_fn=exit_fn,
        )
    assert n == 2
    telegram.assert_not_called()
    exit_fn.assert_not_called()
    assert "all output directories writable: 2 dirs verified" in caplog.text
    # No probe files left behind.
    assert list(a.iterdir()) == [] and list(b.iterdir()) == []


def test_verify_failure_logs_error_alerts_and_exits(tmp_path, caplog):
    # Simulating "directory not writable" via Path.write_text raise.
    # POSIX chmod can't fake this when the test runner is root.
    bad = tmp_path / "d"
    bad.mkdir()
    telegram = MagicMock()
    exit_fn = MagicMock()
    real_write_text = Path.write_text

    def fail_write(self, *a, **kw):
        if str(self).startswith(str(bad)):
            raise PermissionError("simulated denial")
        return real_write_text(self, *a, **kw)

    with patch.object(Path, "write_text", new=fail_write):
        with caplog.at_level(logging.ERROR, logger="AutoBot"):
            fsp.verify_output_directories_writable(
                [bad], telegram_send=telegram, exit_fn=exit_fn,
            )

    exit_fn.assert_called_once_with(1)
    telegram.assert_called_once()
    msg = telegram.call_args.args[0]
    assert "AutoBot boot failure" in msg
    assert str(bad) in msg
    assert "not writable" in caplog.text
    assert "PermissionError" in caplog.text


def test_verify_telegram_failure_does_not_block_exit(tmp_path, caplog):
    bad = tmp_path / "d"
    bad.mkdir()
    telegram = MagicMock(side_effect=RuntimeError("telegram down"))
    exit_fn = MagicMock()

    def fail_write(self, *a, **kw):
        raise PermissionError("simulated denial")

    with patch.object(Path, "write_text", new=fail_write):
        with caplog.at_level(logging.ERROR, logger="AutoBot"):
            fsp.verify_output_directories_writable(
                [bad], telegram_send=telegram, exit_fn=exit_fn,
            )

    exit_fn.assert_called_once_with(1)
    assert "telegram alert failed" in caplog.text


def test_verify_short_circuits_after_first_fail(tmp_path):
    """First failing dir should short-circuit so we don't spam telegram
    with the same systemic error N times."""
    bad1 = tmp_path / "d1"
    bad2 = tmp_path / "d2"
    bad1.mkdir(); bad2.mkdir()
    telegram = MagicMock()
    exit_fn = MagicMock()  # doesn't actually exit

    def fail_write(self, *a, **kw):
        raise PermissionError("simulated denial")

    with patch.object(Path, "write_text", new=fail_write):
        fsp.verify_output_directories_writable(
            [bad1, bad2], telegram_send=telegram, exit_fn=exit_fn,
        )

    assert telegram.call_count == 1
    assert exit_fn.call_count == 1
