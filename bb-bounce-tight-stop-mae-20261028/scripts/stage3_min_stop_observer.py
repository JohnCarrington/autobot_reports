"""Phase 6 Stage 3 — read-only IG DEMO minimum-stop observer.

Research utility — operator-approved invocation only.  Does NOT install
a systemd service or cron entry.

Captures one sample of GBP/USD (and optionally other) dealing-rules +
snapshot fields from IG DEMO using the existing authenticated
read-only session.  Writes an append-only JSONL file outside
`/opt/tradingbot`.

Usage
-----
    python3 scripts/stage3_min_stop_observer.py \\
        --out /home/autobot/research/min_stop/observations.jsonl \\
        --epic CS.D.GBPUSD.TODAY.IP

Recommended cadence (if a continuous collection is authorised by the
operator): one sample every 60 seconds during London/NY hours and every
5 minutes outside them.  Do NOT install this as a persistent process
without a separate operator sign-off.

Safety
------
* Read-only — only `fetch_market_by_epic` is called.
* Never submits an order, nor amends or cancels one.
* Never writes to `/opt/tradingbot`.
* Fails loudly on any API error — never fabricates missing fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_OUT = Path("/home/autobot/research/min_stop/observations.jsonl")
DEFAULT_EPIC = "CS.D.GBPUSD.TODAY.IP"


def _london_now() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(tz=ZoneInfo("Europe/London")).isoformat()
    except Exception:
        return ""


def sample(epic: str) -> dict:
    """Return one observation; raises on any failure."""
    sys.path.insert(0, "/opt/tradingbot")
    from ig_auth import get_ig_session  # type: ignore

    s = get_ig_session()
    ig = s[0] if isinstance(s, (tuple, list)) else s
    md = ig.fetch_market_by_epic(epic)
    rules = (md.get("dealingRules") if isinstance(md, dict)
             else getattr(md, "dealingRules", None)) or {}
    snap = (md.get("snapshot") if isinstance(md, dict)
            else getattr(md, "snapshot", None)) or {}
    now_utc = datetime.now(tz=timezone.utc).isoformat()
    bid = snap.get("bid") if isinstance(snap, dict) else None
    offer = snap.get("offer") if isinstance(snap, dict) else None
    spread = None
    try:
        if bid is not None and offer is not None:
            spread = round(float(offer) - float(bid), 4)
    except Exception:
        spread = None
    return {
        "ts_utc": now_utc,
        "ts_london": _london_now(),
        "epic": epic,
        "min_normal_stop": (
            rules.get("minNormalStopOrLimitDistance", {}).get("value")
            if isinstance(rules.get("minNormalStopOrLimitDistance"), dict) else None
        ),
        "min_normal_stop_unit": (
            rules.get("minNormalStopOrLimitDistance", {}).get("unit")
            if isinstance(rules.get("minNormalStopOrLimitDistance"), dict) else None
        ),
        "min_controlled_stop": (
            rules.get("minControlledRiskStopDistance", {}).get("value")
            if isinstance(rules.get("minControlledRiskStopDistance"), dict) else None
        ),
        "min_step_distance": (
            rules.get("minStepDistance", {}).get("value")
            if isinstance(rules.get("minStepDistance"), dict) else None
        ),
        "min_deal_size": (
            rules.get("minDealSize", {}).get("value")
            if isinstance(rules.get("minDealSize"), dict) else None
        ),
        "min_deal_size_unit": (
            rules.get("minDealSize", {}).get("unit")
            if isinstance(rules.get("minDealSize"), dict) else None
        ),
        "bid": bid,
        "offer": offer,
        "spread": spread,
        "market_status": snap.get("marketStatus") if isinstance(snap, dict) else None,
        "update_time": snap.get("updateTime") if isinstance(snap, dict) else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--epic", default=DEFAULT_EPIC)
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    row = sample(args.epic)
    with args.out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(row, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
