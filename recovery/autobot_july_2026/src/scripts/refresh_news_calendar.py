#!/usr/bin/env python3
"""refresh_news_calendar.py — safe, wrapped fetch of the Finnhub economic
calendar into cache/news_state_finnhub_YYYY-MM-DD.json.

Written to run under a systemd timer (see deploy/systemd/refresh-news-
calendar.{service,timer}). Design notes:

  * ATOMIC WRITE — fetch to a temp file, then os.replace() into place.
    A crashed / partial fetch NEVER truncates or corrupts the existing
    file. If fetch fails, the existing file (if any) is left untouched.
  * NON-BLOCKING — no side effects on the live bot's in-memory caches.
    news_state / news_calendar re-read from disk on their own cadence.
  * IDEMPOTENT — safe to run multiple times per day.
  * LOG PREFIX [NEWS-CAL] — greppable across bot + timer output.

Exit codes:
  0  success (file written or already-fresh no-op)
  1  fetch failed AND no prior cache exists for today → stale state
  2  environment error (missing FINNHUB_API_KEY)
  0  fetch failed but a prior cache exists for today → operator is
     already warned by the staleness alerter; timer keeps running
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(os.getenv("TRADINGBOT_HOME", "/opt/tradingbot"))
CACHE_DIR = Path(os.getenv("NEWS_STATE_CACHE_DIR", str(REPO / "cache")))
CACHE_PREFIX = "news_state_finnhub_"
FETCH_TIMEOUT_S = float(os.getenv("NEWS_CALENDAR_FETCH_TIMEOUT_S", "15"))
FROM_LOOKBACK_DAYS = int(os.getenv("NEWS_CALENDAR_LOOKBACK_DAYS", "2"))
TO_LOOKAHEAD_DAYS = int(os.getenv("NEWS_CALENDAR_LOOKAHEAD_DAYS", "7"))

# Mirror news_state.py normalisation so consumers can read the file
# uniformly. Keep in sync with news_state._COUNTRY_CCY / _IMPACT_MAP.
_COUNTRY_CCY = {
    "GB": "GBP", "US": "USD", "EU": "EUR", "CA": "CAD", "JP": "JPY",
}
_IMPACT_MAP = {"high": "HIGH", "medium": "MED", "low": "LOW"}
FINNHUB_URL = "https://finnhub.io/api/v1/calendar/economic"


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
_log = logging.getLogger("refresh_news_calendar")


def _today_str_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cache_path_for(date_str: str) -> Path:
    return CACHE_DIR / f"{CACHE_PREFIX}{date_str}.json"


def _fetch_finnhub(api_key, from_date, to_date):
    """Return list-of-normalised-events or None on failure."""
    try:
        import requests
    except Exception as exc:
        _log.warning("[NEWS-CAL] requests not installed: %s", exc)
        return None
    try:
        resp = requests.get(
            FINNHUB_URL,
            params={"from": from_date, "to": to_date, "token": api_key},
            timeout=FETCH_TIMEOUT_S,
        )
    except Exception as exc:
        _log.warning("[NEWS-CAL] WARNING fetch failed: %s", exc)
        return None

    if resp.status_code in (401, 403):
        _log.warning(
            "[NEWS-CAL] WARNING tier-locked (%s) — check FINNHUB_API_KEY tier",
            resp.status_code,
        )
        return None
    if resp.status_code != 200:
        _log.warning("[NEWS-CAL] WARNING HTTP %s", resp.status_code)
        return None

    try:
        data = resp.json()
    except Exception as exc:
        _log.warning("[NEWS-CAL] WARNING parse error: %s", exc)
        return None

    raw = (data or {}).get("economicCalendar") or []
    out = []
    for ev in raw:
        try:
            country = str(ev.get("country") or "").strip().upper()
            ccy = _COUNTRY_CCY.get(country)
            if not ccy:
                continue
            impact = _IMPACT_MAP.get(
                str(ev.get("impact") or "").strip().lower()
            )
            if impact not in ("HIGH", "MED"):
                continue
            time_s = str(ev.get("time") or "").strip()
            if not time_s:
                continue
            dt = datetime.fromisoformat(time_s.replace(" ", "T"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            out.append({
                "ts": dt.isoformat(),
                "currency": ccy,
                "impact": impact,
                "event": str(ev.get("event") or "")[:80],
            })
        except Exception:
            continue
    out.sort(key=lambda e: e["ts"])
    return out


def _atomic_write(path, payload):
    """Write payload as JSON to a temp file next to path, then rename.
    os.replace() is atomic on the same filesystem. On any exception the
    temp file is removed and path is left untouched."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.stem + ".", suffix=".json.tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def main():
    api_key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    if not api_key:
        _log.warning(
            "[NEWS-CAL] WARNING FINNHUB_API_KEY missing — cannot refresh."
        )
        return 2

    today = _today_str_utc()
    dest = _cache_path_for(today)
    prior_existed = dest.exists()

    from_date = (
        datetime.now(timezone.utc) - timedelta(days=FROM_LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d")
    to_date = (
        datetime.now(timezone.utc) + timedelta(days=TO_LOOKAHEAD_DAYS)
    ).strftime("%Y-%m-%d")

    events = _fetch_finnhub(api_key, from_date, to_date)

    if events is None:
        # Fetch failed. File is untouched by design — atomic-write means
        # no partial data hits disk. Report state so operator can see.
        if prior_existed:
            _log.warning(
                "[NEWS-CAL] WARNING fetch FAILED; prior cache preserved: %s",
                dest,
            )
            return 0
        _log.warning(
            "[NEWS-CAL] WARNING fetch FAILED and NO PRIOR CACHE for %s — "
            "consumers will see stale/missing calendar",
            today,
        )
        return 1

    payload = {
        "date": today,
        "events": events,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "source": "refresh_news_calendar",
    }
    _atomic_write(dest, payload)
    _log.info(
        "[NEWS-CAL] refreshed %s events=%d file=%s",
        today, len(events), dest,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
