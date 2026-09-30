#!/usr/bin/env python3
"""
daily_reconcile.py — post-EOD signal_log integrity check against IG.

For each signal_log row whose timestamp_open falls within the target UTC
date, verify it has an exact match on IG's /history/activity (via
deal_id → actions[].affectedDealId) and that close_price / pnl_pips
agree with IG's /history/transactions to within 0.1p / £0.10.

For each IG GBP/USD (and other tracked pairs) transaction whose closeDate
falls within the target UTC date, verify a signal_log row exists for it.

Exits non-zero on any of:
  * signal_log row with populated deal_id not found in IG activity,
  * signal_log row whose close_price diverges from IG closeLevel by >0.1p,
  * signal_log row whose pnl_pips diverges from IG profitAndLoss by >£0.10,
  * IG transaction with no signal_log row (deal_id not in log at all).

Legacy signal_log rows with no deal_id are logged at WARNING but do not
cause a non-zero exit — they will age out as the bot is restarted and
new rows carry the field.

Read-only. No orders, no state mutation. Safe to wire into cron/systemd.

Usage:
  python scripts/daily_reconcile.py [--date YYYY-MM-DD] [--pair GBPUSD,...]
                                    [--json-out /path/to/report.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Defer heavy imports until after argparse so --help is instant.
def _ig_session_and_headers():
    import ig_auth  # noqa: E402
    _, headers, account_id = ig_auth.get_ig_session()
    return headers, account_id


SIGNAL_LOG = REPO_ROOT / "logs" / "signal_log.jsonl"

# Same mapping as signal_log_integrity._INSTR_TO_EPIC
_INSTR_TO_EPIC = {
    "GBP/USD": "CS.D.GBPUSD.TODAY.IP",
    "EUR/USD": "CS.D.EURUSD.TODAY.IP",
    "USD/JPY": "CS.D.USDJPY.TODAY.IP",
    "USD/CAD": "CS.D.USDCAD.TODAY.IP",
    "GBP/JPY": "CS.D.GBPJPY.TODAY.IP",
}

CLOSE_PRICE_TOL_POINTS = 0.1
PNL_TOL_GBP = 0.10

logger = logging.getLogger("daily_reconcile")


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

def _fetch_transactions(date_str: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    import requests
    h = dict(headers); h["Version"] = "2"; h["Accept"] = "application/json; charset=UTF-8"
    url = (
        "https://demo-api.ig.com/gateway/deal/history/transactions"
        f"?type=ALL&from={date_str}T00:00:00&to={date_str}T23:59:59&pageSize=500"
    )
    r = requests.get(url, headers=h, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("transactions", []) or []


def _fetch_activities(date_str: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    import requests
    h = dict(headers); h["Version"] = "3"; h["Accept"] = "application/json; charset=UTF-8"
    url = (
        "https://demo-api.ig.com/gateway/deal/history/activity"
        f"?from={date_str}T00:00:00&to={date_str}T23:59:59&detailed=true&pageSize=500"
    )
    r = requests.get(url, headers=h, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("activities", []) or []


def _load_signal_log_day(date_str: str, pairs: Optional[List[str]]) -> List[Dict[str, Any]]:
    if not SIGNAL_LOG.exists():
        return []
    wanted = {p.upper() for p in pairs} if pairs else None
    out: List[Dict[str, Any]] = []
    with open(SIGNAL_LOG) as fh:
        for ln in fh:
            s = ln.strip()
            if not s:
                continue
            try:
                r = json.loads(s)
            except Exception:
                continue
            if not str(r.get("timestamp_open") or "").startswith(date_str):
                continue
            if wanted is not None and (r.get("pair") or "").upper() not in wanted:
                continue
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Join + compare
# ---------------------------------------------------------------------------

def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pnl_gbp_from_tx(tx: Dict[str, Any]) -> Optional[float]:
    """IG returns profitAndLoss as '£-12.00' or 'E-12.00' string."""
    raw = tx.get("profitAndLoss")
    if raw is None:
        return None
    s = str(raw).replace("£", "").replace("E", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _build_close_index(activities: List[Dict[str, Any]], txs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """open_deal_id → {close_level, open_level, pnl_gbp, tx, activity}."""
    tx_by_close_ref: Dict[str, Dict[str, Any]] = {}
    for t in txs:
        ref = str(t.get("reference") or "").strip()
        if ref:
            tx_by_close_ref[ref] = t

    out: Dict[str, Dict[str, Any]] = {}
    for a in activities:
        if str(a.get("type") or "") != "POSITION":
            continue
        if str(a.get("status") or "") != "ACCEPTED":
            continue
        # `actions` lives inside `details`, not at the activity top level.
        # (Verified against the v3 /history/activity?detailed=true payload:
        # the close-side affectedDealId is at details.actions[].affectedDealId.)
        details = a.get("details") or {}
        for act in (details.get("actions") or []):
            if str(act.get("actionType") or "") != "POSITION_CLOSED":
                continue
            open_deal_id = str(act.get("affectedDealId") or "").strip()
            if not open_deal_id:
                continue
            # The close-side dealId is the top-level activity.dealId; the
            # matching /transactions row has `reference == close_deal_id`.
            close_deal_id = str(a.get("dealId") or "").strip()
            tx = tx_by_close_ref.get(close_deal_id)
            out[open_deal_id] = {
                "activity": a,
                "transaction": tx,
                "close_level": _safe_float(details.get("level")),
                "open_level": _safe_float((tx or {}).get("openLevel")),
                "pnl_gbp": _pnl_gbp_from_tx(tx) if tx else None,
                "close_deal_id": close_deal_id,
            }
    return out


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

def compare(
    sl_rows: List[Dict[str, Any]],
    close_index: Dict[str, Dict[str, Any]],
    txs: List[Dict[str, Any]],
    pair_filter: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Reconcile signal_log rows against the open-side deal_id close index.

    `pair_filter` (e.g. ["GBPUSD"]) scopes BOTH the signal_log rows to scan
    AND the IG-side cross-check ("ig_close_with_no_signal_log") so that
    running with --pair GBPUSD doesn't flag EURUSD closes that signal_log
    correctly logged under a pair we chose not to load.
    """
    pair_set = {p.upper() for p in pair_filter} if pair_filter else None
    pair_instrs = None
    if pair_set:
        # Reverse-map pair → instrumentName used by IG tx payloads
        inv = {epic.split(".")[2] if "." in epic else "": instr
               for instr, epic in _INSTR_TO_EPIC.items()}
        pair_instrs = {inv.get(p) for p in pair_set if inv.get(p)}
    findings: List[Dict[str, Any]] = []
    legacy_no_dealid = 0
    ok = 0

    used_open_deal_ids: set = set()

    for r in sl_rows:
        rid = r.get("id")
        deal_id = str(r.get("deal_id") or "").strip()
        pair = r.get("pair")
        dir_ = r.get("direction")
        sl_close = _safe_float(r.get("close_price"))
        sl_pnl = _safe_float(r.get("pnl_pips"))

        if not deal_id:
            findings.append({
                "severity": "WARNING",
                "kind": "no_deal_id_legacy",
                "signal_log_id": rid,
                "pair": pair,
                "entry": r.get("entry"),
                "outcome": r.get("outcome"),
                "note": "legacy row without deal_id; skipping exact comparison",
            })
            legacy_no_dealid += 1
            continue

        close_rec = close_index.get(deal_id)
        if close_rec is None:
            findings.append({
                "severity": "FAIL",
                "kind": "signal_log_row_not_in_ig",
                "signal_log_id": rid,
                "deal_id": deal_id,
                "pair": pair,
                "direction": dir_,
                "entry": r.get("entry"),
                "close_price": sl_close,
                "pnl_pips": sl_pnl,
                "outcome": r.get("outcome"),
                "note": "signal_log row has deal_id that is not present in IG's "
                        "POSITION_CLOSED activities for this date.",
            })
            continue

        used_open_deal_ids.add(deal_id)

        ig_close = close_rec.get("close_level")
        ig_pnl = close_rec.get("pnl_gbp")

        # close_price check
        close_ok = (
            sl_close is not None
            and ig_close is not None
            and abs(float(sl_close) - float(ig_close)) <= CLOSE_PRICE_TOL_POINTS
        )
        # pnl check (signal_log stores pips, which is £ at £1/pt for tracked pairs)
        pnl_ok = (
            sl_pnl is None
            or ig_pnl is None
            or abs(float(sl_pnl) - float(ig_pnl)) <= PNL_TOL_GBP
        )

        if not close_ok:
            findings.append({
                "severity": "FAIL",
                "kind": "close_price_mismatch",
                "signal_log_id": rid,
                "deal_id": deal_id,
                "pair": pair,
                "sl_close_price": sl_close,
                "ig_close_level": ig_close,
                "delta": (float(sl_close or 0) - float(ig_close or 0)),
                "close_deal_id": close_rec.get("close_deal_id"),
            })
        if not pnl_ok:
            findings.append({
                "severity": "FAIL",
                "kind": "pnl_mismatch",
                "signal_log_id": rid,
                "deal_id": deal_id,
                "pair": pair,
                "sl_pnl_pips": sl_pnl,
                "ig_pnl_gbp": ig_pnl,
                "delta": (float(sl_pnl or 0) - float(ig_pnl or 0)),
                "close_deal_id": close_rec.get("close_deal_id"),
            })
        if close_ok and pnl_ok:
            ok += 1

    # Reverse direction: any close in IG with no signal_log row at all?
    for open_deal_id, rec in close_index.items():
        if open_deal_id in used_open_deal_ids:
            continue
        tx = rec.get("transaction") or {}
        instr = str(tx.get("instrumentName") or "")
        # Filter to tracked pairs only, to avoid spam from other instruments
        if instr and instr not in _INSTR_TO_EPIC:
            continue
        # Scope to the --pair filter when set
        if pair_instrs is not None and instr not in pair_instrs:
            continue
        findings.append({
            "severity": "FAIL",
            "kind": "ig_close_with_no_signal_log",
            "open_deal_id": open_deal_id,
            "close_deal_id": rec.get("close_deal_id"),
            "instrument": instr or "?",
            "open_level": rec.get("open_level"),
            "close_level": rec.get("close_level"),
            "pnl_gbp": rec.get("pnl_gbp"),
            "note": "IG has a closed position whose open-side dealId never made "
                    "it into signal_log.jsonl (missing log_open call?).",
        })

    summary = {
        "signal_log_rows": len(sl_rows),
        "signal_log_ok": ok,
        "signal_log_legacy_no_deal_id": legacy_no_dealid,
        "ig_closes_total": len(close_index),
        "findings_fail": sum(1 for f in findings if f["severity"] == "FAIL"),
        "findings_warning": sum(1 for f in findings if f["severity"] == "WARNING"),
    }
    return {"summary": summary, "findings": findings}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", default=None,
                    help="UTC date YYYY-MM-DD. Default: yesterday UTC.")
    ap.add_argument("--pair", default=None,
                    help="Comma-separated pairs to filter signal_log rows (e.g. GBPUSD,EURUSD). "
                         "Default: all tracked pairs.")
    ap.add_argument("--json-out", default=None,
                    help="Path to write the full report JSON. Default: "
                         "data/investigations/reconcile_YYYY-MM-DD.json")
    ap.add_argument("--no-fail", action="store_true",
                    help="Report findings but exit 0 regardless. Use for first-run bootstrap.")
    args = ap.parse_args()

    if args.date:
        date_str = args.date
    else:
        date_str = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    pairs = None
    if args.pair:
        pairs = [p.strip() for p in args.pair.split(",") if p.strip()]

    out_path = Path(args.json_out) if args.json_out else (
        REPO_ROOT / "data" / "investigations" / f"reconcile_{date_str}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("daily_reconcile: date=%s pairs=%s", date_str, pairs or "ALL")

    sl_rows = _load_signal_log_day(date_str, pairs)
    logger.info("signal_log rows for %s: %d", date_str, len(sl_rows))

    try:
        headers, account_id = _ig_session_and_headers()
    except Exception as e:
        logger.error("IG auth failed: %s", e)
        return 2
    logger.info("active IG account: %s", account_id)

    try:
        txs = _fetch_transactions(date_str, headers)
    except Exception as e:
        logger.error("IG /history/transactions fetch failed: %s", e)
        return 2
    try:
        activities = _fetch_activities(date_str, headers)
    except Exception as e:
        logger.error("IG /history/activity fetch failed: %s", e)
        return 2
    logger.info("IG fetched: %d transactions, %d activities", len(txs), len(activities))

    close_index = _build_close_index(activities, txs)
    logger.info("close-index entries (by open-side deal_id): %d", len(close_index))

    report = compare(sl_rows, close_index, txs, pair_filter=pairs)
    summary = report["summary"]
    findings = report["findings"]

    logger.info(
        "summary: sl_rows=%d ok=%d legacy_no_deal_id=%d ig_closes=%d "
        "findings_fail=%d findings_warning=%d",
        summary["signal_log_rows"], summary["signal_log_ok"],
        summary["signal_log_legacy_no_deal_id"], summary["ig_closes_total"],
        summary["findings_fail"], summary["findings_warning"],
    )

    # Log each FAIL finding inline so journalctl captures the detail
    for f in findings:
        if f["severity"] != "FAIL":
            continue
        logger.error("FAIL %s: %s", f["kind"], json.dumps(f, default=str))

    full = {
        "date": date_str,
        "pairs": pairs or sorted(_INSTR_TO_EPIC.keys()),
        "account_id": account_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **report,
    }
    out_path.write_text(json.dumps(full, indent=2, default=str))
    logger.info("report written: %s", out_path)

    if args.no_fail:
        return 0
    return 1 if summary["findings_fail"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
