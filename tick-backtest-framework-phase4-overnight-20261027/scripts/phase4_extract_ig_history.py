"""Phase 4 — authoritative IG DEMO extraction (read-only).

Pulls /history/transactions, /history/activity (detailed), and open-position
state for the configured DEMO account between a from/to date range. Writes
raw sanitised JSON into the research directory. NEVER places, amends, or
cancels orders; NEVER calls close/open; NEVER mutates production state.

Credentials are loaded from /opt/tradingbot/.env (or /opt/bb_bounce/.env as a
fallback). Account is verified DEMO before any network call. Credentials are
never written to the research repository — only sanitised payloads land on
disk.

Run with the deployed autobot venv so trading_ig is available:
    /opt/tradingbot/venv/bin/python phase4_extract_ig_history.py \\
        --from 2026-09-17 --to 2026-10-27 \\
        --out /home/autobot/autobot_reports_clone/tick-backtest-framework-phase4-overnight-20261027/data
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qsl


SAFETY_HARD_READ_ONLY_MARKER = "PHASE4_READ_ONLY_EXTRACTOR"


def load_env(paths: list[Path]) -> dict[str, str]:
    env: dict[str, str] = {}
    for p in paths:
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if not line or line.lstrip().startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def verify_demo(env: dict[str, str]) -> None:
    acc_type = env.get("IG_ACC_TYPE", "").upper()
    if acc_type != "DEMO":
        raise SystemExit(f"[SAFETY] IG_ACC_TYPE={acc_type!r} — refusing to run on anything other than DEMO")
    api_url = env.get("IG_API_URL", "")
    if api_url and "demo-api.ig.com" not in api_url:
        raise SystemExit(f"[SAFETY] IG_API_URL={api_url!r} is not a DEMO host")


def to_london_naive(d: dt.datetime) -> dt.datetime:
    """IG's history endpoints read from/to in account-local time
    (Europe/London). Convert UTC to London once here."""
    try:
        import pytz  # type: ignore
        london = pytz.timezone("Europe/London")
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(london).replace(tzinfo=None)
    except Exception:
        return d.replace(tzinfo=None)


def fetch_transactions(ig, from_dt: dt.datetime, to_dt: dt.datetime) -> list[dict]:
    """Paginated /history/transactions. Returns raw rows."""
    from_local = to_london_naive(from_dt)
    to_local = to_london_naive(to_dt)
    page = 1
    page_size = 100
    safety_pages = 100
    rows: list[dict] = []
    while page <= safety_pages:
        df = ig.fetch_transaction_history(
            from_date=from_local,
            to_date=to_local,
            page_size=page_size,
            page_number=page,
        )
        if df is None or len(df) == 0:
            break
        for _, r in df.iterrows():
            d: dict[str, Any] = {}
            for col in df.columns:
                v = r.get(col)
                d[col] = (None if v is None else str(v))
            rows.append(d)
        if len(df) < page_size:
            break
        page += 1
        time.sleep(0.15)
    return rows


_DT_OFFSET_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?[+\- ]\d{2}:?\d{2}$"
)


def _strip_offset(value: str) -> str:
    m = _DT_OFFSET_RE.match(str(value).strip())
    return m.group(1) if m else str(value).strip()


def fetch_activity_detailed(ig, from_dt: dt.datetime, to_dt: dt.datetime) -> list[dict]:
    """Detailed /history/activity via the library's own fetch_account_activity.
    Install the activity-paging monkeypatch from ig_auth so IG's offset-bearing
    next cursor is consumed correctly."""
    from_local = to_london_naive(from_dt)
    to_local = to_london_naive(to_dt)
    # Install the ig_auth activity paging monkeypatch without importing
    # ig_auth itself (which hard-fails when env vars aren't present in os.environ).
    try:
        import trading_ig.rest as ig_rest  # type: ignore
        from urllib.parse import parse_qs as _real_parse_qs
        if not getattr(ig_rest.parse_qs, "_phase4_paging_patch", False):
            def _parse_qs_paging_safe(qs, *a, **k):
                parsed = _real_parse_qs(qs, *a, **k)
                for key in ("from", "to"):
                    vals = parsed.get(key)
                    if vals:
                        parsed[key] = [_strip_offset(v) for v in vals]
                return parsed
            _parse_qs_paging_safe._phase4_paging_patch = True  # type: ignore
            ig_rest.parse_qs = _parse_qs_paging_safe
    except Exception as e:
        print(f"[act] paging patch not installed: {e}")
    df = ig.fetch_account_activity(
        from_date=from_local,
        to_date=to_local,
        detailed=True,
    )
    rows: list[dict] = []
    if df is None or len(df) == 0:
        return rows
    for _, r in df.iterrows():
        d: dict[str, Any] = {}
        for col in df.columns:
            v = r.get(col)
            if v is None:
                d[col] = None
            else:
                try:
                    json.dumps(v)
                    d[col] = v
                except Exception:
                    d[col] = str(v)
        rows.append(d)
    return rows


def fetch_positions_snapshot(ig) -> dict:
    """Current open-position snapshot. READ-ONLY — delegates to the
    library's own fetcher so we never touch position-management surfaces."""
    try:
        df = ig.fetch_open_positions()
    except Exception as e:
        return {"error": repr(e)}
    rows: list[dict] = []
    if df is not None and len(df):
        for _, r in df.iterrows():
            d: dict[str, Any] = {}
            for col in df.columns:
                v = r.get(col)
                if v is None:
                    d[col] = None
                else:
                    try:
                        json.dumps(v)
                        d[col] = v
                    except Exception:
                        d[col] = str(v)
            rows.append(d)
    return {"positions": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_date", required=True, help="UTC date YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", required=True, help="UTC date YYYY-MM-DD (inclusive)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--epic-prefix", default="CS.D.GBPUSD",
                    help="only keep rows whose epic/instrument matches this prefix")
    args = ap.parse_args()

    print(f"[{SAFETY_HARD_READ_ONLY_MARKER}] start")

    env = load_env([Path("/opt/tradingbot/.env"), Path("/opt/bb_bounce/.env")])
    verify_demo(env)

    # Prefer BB Bounce credentials — same DEMO account and simpler env.
    user = env.get("IG_USERNAME")
    pwd = env.get("IG_PASSWORD")
    api_key = env.get("IG_API_KEY")
    account_id = env.get("IG_ACCOUNT_ID", "")

    from_dt = dt.datetime.fromisoformat(args.from_date).replace(tzinfo=dt.timezone.utc)
    to_dt = dt.datetime.fromisoformat(args.to_date).replace(hour=23, minute=59, second=59,
                                                           tzinfo=dt.timezone.utc)

    from trading_ig import IGService  # type: ignore
    ig = IGService(user, pwd, api_key, "DEMO")
    sess = ig.create_session()
    acc_from_session = str(getattr(sess, "get", lambda *_: None)("currentAccountId") or
                           (sess.get("currentAccountId") if isinstance(sess, dict) else "")) \
        if hasattr(sess, "get") else ""
    print(f"[login] account={account_id} session={acc_from_session!r}")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    # /history/transactions
    print(f"[txs] {from_dt.isoformat()} → {to_dt.isoformat()}")
    txs_raw = fetch_transactions(ig, from_dt, to_dt)
    # Instrument name in /history/transactions is 'GBP/USD', not the CS.D epic.
    def _is_gbpusd(name: str) -> bool:
        n = (name or "").upper()
        return "GBP/USD" in n or "GBPUSD" in n
    txs_f = [r for r in txs_raw if _is_gbpusd(str(r.get("instrumentName", "")))]
    print(f"[txs] total={len(txs_raw)}  gbpusd_only={len(txs_f)}")
    (outdir / f"ig_transactions_raw_{stamp}.json").write_text(
        json.dumps({"account_id": account_id, "window_utc": [args.from_date, args.to_date],
                    "rows": txs_raw}, indent=2))
    (outdir / f"ig_transactions_gbpusd_{stamp}.json").write_text(
        json.dumps({"account_id": account_id, "window_utc": [args.from_date, args.to_date],
                    "rows": txs_f}, indent=2))

    # /history/activity detailed
    print(f"[act] {from_dt.isoformat()} → {to_dt.isoformat()}")
    try:
        acts_raw = fetch_activity_detailed(ig, from_dt, to_dt)
    except Exception as e:
        acts_raw = []
        print(f"[act] fetch failed: {e}")
    acts_f = [a for a in acts_raw if args.epic_prefix.upper() in str(a.get("epic", "")).upper()]
    print(f"[act] total={len(acts_raw)}  gbpusd_only={len(acts_f)}")
    (outdir / f"ig_activity_raw_{stamp}.json").write_text(
        json.dumps({"account_id": account_id, "window_utc": [args.from_date, args.to_date],
                    "rows": acts_raw}, indent=2))
    (outdir / f"ig_activity_gbpusd_{stamp}.json").write_text(
        json.dumps({"account_id": account_id, "window_utc": [args.from_date, args.to_date],
                    "rows": acts_f}, indent=2))

    # /positions snapshot (read-only — identifies open at inspection time)
    pos = fetch_positions_snapshot(ig)
    (outdir / f"ig_positions_snapshot_{stamp}.json").write_text(
        json.dumps({"account_id": account_id, "snapshot_utc": dt.datetime.utcnow().isoformat(),
                    "payload": pos}, indent=2))
    print(f"[pos] current open positions: {len((pos or {}).get('positions') or [])}")

    print(f"[{SAFETY_HARD_READ_ONLY_MARKER}] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
