"""``python -m cli.replay`` – thin wrapper around :func:`trend_runner.replay.main`."""
from __future__ import annotations

from trend_runner.replay import main


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
