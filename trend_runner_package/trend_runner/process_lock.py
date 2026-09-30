"""Singleton process lock using an flock'd file.

Only one Trend Runner process per configured data directory can hold
the lock. Attempts to acquire while another instance holds it raise
LockHeldError. The lock is released on process exit.
"""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
from typing import Optional


class LockHeldError(RuntimeError):
    pass


class ProcessLock:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise LockHeldError(f"lock held by another process: {self.path}") from e
            raise
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode() + b"\n")
        os.fsync(fd)
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
