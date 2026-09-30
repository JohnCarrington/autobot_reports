"""log_redaction.py — redact secret patterns from log records before emit.

The primary threat is `urllib3.connectionpool` DEBUG output logging the full
outbound URL. For Telegram, the URL path *contains the bot token*
(`/bot<token>/sendMessage`), which was leaking into journalctl for anyone
with journal read on the host.

A logging.Filter attached to the root logger's handlers sees every record
that reaches those handlers — including records propagated from noisy child
loggers like `urllib3.connectionpool`. This is where we redact.

Design notes:
- Pattern-first: a rotated token is redacted without touching this file.
- Literal fallback (IG_API_KEY) for secrets whose format has no reliable
  signature — supplied at install time from the environment.
- Filters attached to specific HTTP child loggers as belt-and-braces so the
  redaction still runs if some entrypoint bypasses `install_default()` but
  has its own root-handler config.
- Idempotent — a marker attribute on the root logger prevents double
  install when multiple modules call `install_default()`.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Iterable, Optional, Tuple


_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"/bot(\d+):[A-Za-z0-9_-]{10,}"), r"/bot\1:***"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "sk-ant-***"),
    (re.compile(r"SG\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{20,}"), "SG.***"),
)


class SecretRedactingFilter(logging.Filter):
    """Redact secret patterns from LogRecord messages before emit."""

    def __init__(self, extra_literals: Optional[Iterable[str]] = None) -> None:
        super().__init__()
        self._literals: Tuple[str, ...] = tuple(
            s for s in (extra_literals or ()) if s and len(s) >= 8
        )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = msg
        for pattern, replacement in _PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        for lit in self._literals:
            if lit in redacted:
                redacted = redacted.replace(lit, "***")
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


_INSTALLED_ATTR = "_autobot_secret_redaction_installed"
_HTTP_LOGGERS = (
    "urllib3",
    "urllib3.connectionpool",
    "httpx",
    "httpcore",
    "requests",
)


def install_default(root: Optional[logging.Logger] = None) -> SecretRedactingFilter:
    """Install the redaction filter on root handlers + HTTP child loggers.

    Idempotent. Reads IG_API_KEY from the environment at install time and
    adds it as a literal-redact string, since that value has no pattern
    signature safe to match without false positives.
    """
    root = root or logging.getLogger()
    existing = getattr(root, _INSTALLED_ATTR, None)
    if isinstance(existing, SecretRedactingFilter):
        return existing

    literals = [os.getenv("IG_API_KEY", "")]
    flt = SecretRedactingFilter(extra_literals=literals)
    for handler in root.handlers:
        handler.addFilter(flt)
    for name in _HTTP_LOGGERS:
        logging.getLogger(name).addFilter(flt)
    setattr(root, _INSTALLED_ATTR, flt)
    return flt
