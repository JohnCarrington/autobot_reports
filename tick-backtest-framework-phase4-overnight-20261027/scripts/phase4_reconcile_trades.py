"""Phase 4 — reconcile IG DEMO authoritative records against internal logs.

Inputs:
  * `data/ig_transactions_gbpusd_<stamp>.json` — authoritative P&L / fills.
  * `data/ig_activity_gbpusd_<stamp>.json` — authoritative lifecycle events.
  * `/opt/tradingbot/logs/unified_trades.jsonl` — autobot internal OPEN/CLOSE.
  * `/opt/bb_bounce/reports/*.csv` — standalone BB Bounce daily closures.

Produces:
  * `data/trade_ledger.json` — reconciled trade objects keyed by open dealId.
  * `data/trade_match_summary.json` — totals + attribution + gap list.

READ-ONLY. No modifications to production artefacts.
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DATA_DIR = Path("/home/autobot/autobot_reports_clone/tick-backtest-framework-phase4-overnight-20261027/data")
UNIFIED_PATH = Path("/opt/tradingbot/logs/unified_trades.jsonl")
BBB_REPORTS_DIR = Path("/opt/bb_bounce/reports")
EMAPB_SETUP_HISTORY = Path("/opt/ema_pullback/state/setup_history.jsonl")


def _latest(pattern: str) -> Path:
    paths = sorted(glob.glob(str(DATA_DIR / pattern)))
    if not paths:
        raise SystemExit(f"no match for {pattern}")
    return Path(paths[-1])


def _parse_pnl(s: str) -> float | None:
    if not s:
        return None
    s = s.replace("£", "").replace(",", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except Exception:
        return None


def _size_direction(size_str: str) -> tuple[float, str]:
    """IG DEMO size format: '-2', '+2', '2.5' — negative is a SELL."""
    try:
        v = float(size_str)
    except Exception:
        return 0.0, "UNKNOWN"
    direction = "SELL" if v < 0 else "BUY"
    return abs(v), direction


def _is_within_window(dt_str: str, from_d: str, to_d: str) -> bool:
    return bool(dt_str) and dt_str[:10] >= from_d and dt_str[:10] <= to_d


def load_ig() -> tuple[list[dict], list[dict], dict]:
    tx = json.load(open(_latest("ig_transactions_gbpusd_*.json")))["rows"]
    act = json.load(open(_latest("ig_activity_gbpusd_*.json")))["rows"]
    pos = json.load(open(_latest("ig_positions_snapshot_*.json")))["payload"]
    return tx, act, pos


def classify_strategy(deal_ref: str, strategy_tag: str) -> tuple[str, str]:
    """Return (source_system, strategy_family). Known host prefixes:
    - H161 = autobot.service on AutoBotV1
    - HBB  = bb-bounce.service on AutoBotV1 (OWNERSHIP_HOST_PREFIX=HBB)
    - EMAPB = ema-pullback.service on AutoBotV1 (OWNERSHIP_HOST_PREFIX=EMAPB)
    - H144 = sibling host (not inspected here)
    - other = unknown
    """
    r = (deal_ref or "").upper()
    s = (strategy_tag or "").upper()
    if r.startswith("HBB-BBB") or r.startswith("HBB-"):
        return ("bb_bounce_standalone", "BB_BOUNCE")
    if r.startswith("EMAPB"):
        return ("ema_pullback_standalone", "EMA_PULLBACK")
    if r.startswith("H161"):
        if "BOUNCETR" in r or "BOUNCE_TR" in r:
            return ("autobot", "BOUNCE_TR")
        if "BOUNCE_A" in r or "BOUNCEA" in r:
            return ("autobot", "BOUNCE_A")
        if "BOUNCE_C" in r or "BOUNCEC" in r:
            return ("autobot", "BOUNCE_C")
        if "BBB" in r or "BB_BOUNCE" in r or "BB_B" in r:
            return ("autobot", "GBPUSD_BB_BOUNCE")
        if "TRENDV3" in r or "TREND_V3" in r or "V3" in r:
            return ("autobot", "GBPUSD_TREND_V3")
        if "EMA" in r:
            return ("autobot", "EMA_PULLBACK")
        return ("autobot", f"UNKNOWN:{s or 'none'}")
    if r.startswith("H144"):
        return ("sibling_host_h144", r.split("-")[1] if "-" in r else "H144")
    # Fall back to strategy tag from unified_trades when we have one.
    if s:
        if s.startswith("GBPUSD_BB_BOUNCE") or s.startswith("BOUNCE_"):
            return ("autobot", "GBPUSD_BB_BOUNCE_OR_BOUNCE")
        if s.startswith("V3_"):
            return ("autobot", "GBPUSD_TREND_V3")
        if s.startswith("GBPUSD_TREND_V3"):
            return ("autobot", "GBPUSD_TREND_V3")
        if s.startswith("V3_EMA_") or "EMA" in s:
            return ("autobot", "EMA_PULLBACK")
        return ("autobot", f"TAG:{s}")
    # Deal reference prefix we don't recognise (manual UI? other host?)
    if r:
        return ("unknown_or_manual", f"REF:{r.split('-')[0]}")
    return ("unknown_or_manual", "NO_REF")


def load_unified_trades(from_d: str, to_d: str) -> dict[str, dict]:
    """Return opens keyed by deal_id, plus closes list."""
    by_deal: dict[str, dict] = {}
    closes: dict[str, dict] = {}
    with open(UNIFIED_PATH) as f:
        for line in f:
            r = json.loads(line)
            ts = r.get("ts_utc", "")[:10]
            if not (from_d <= ts <= to_d):
                continue
            did = r.get("deal_id", "")
            if r.get("event") == "OPEN":
                by_deal[did] = r
            elif r.get("event") == "CLOSE":
                closes[did] = r
    return {"opens": by_deal, "closes": closes}


def load_emapb_setups(from_d: str, to_d: str) -> dict[str, dict]:
    """Return the final event (last state) per EMAPB deal_id."""
    if not EMAPB_SETUP_HISTORY.exists():
        return {}
    by_deal: dict[str, dict] = {}
    for line in open(EMAPB_SETUP_HISTORY):
        try:
            r = json.loads(line)
        except Exception:
            continue
        ts = r.get("ts", "")[:10]
        if not (from_d <= ts <= to_d):
            continue
        did = (r.get("setup") or {}).get("deal_id")
        if did:
            by_deal[did] = r
    return by_deal


def load_bbb_csv(from_d: str, to_d: str) -> list[dict]:
    """Standalone BB Bounce daily report rows (closed trades + non-fills)."""
    rows: list[dict] = []
    if not BBB_REPORTS_DIR.exists():
        return rows
    for p in sorted(BBB_REPORTS_DIR.glob("*.csv")):
        day = p.stem  # YYYY-MM-DD
        if day < from_d or day > to_d:
            continue
        with open(p) as f:
            dr = csv.DictReader(f)
            for row in dr:
                row["_file_day"] = day
                rows.append(row)
    return rows


_DEAL_REF_SPLIT = re.compile(r"[-:]")


def reconcile(from_d: str, to_d: str) -> dict[str, Any]:
    tx, act, pos = load_ig()

    # Filter to inspection window (IG dateUtc)
    tx = [t for t in tx if _is_within_window(t.get("dateUtc", ""), from_d, to_d)
          and str(t.get("transactionType", "")).upper() == "DEAL"]
    act = [a for a in act if _is_within_window(a.get("date", ""), from_d, to_d)]

    # Transactions pair open+close in a single row — openDateUtc / openLevel for the
    # open side, dateUtc / closeLevel for the close. `reference` is the CLOSE dealId,
    # NOT the open dealId. We key transactions by openDateUtc; a position with
    # multiple partial-close rows will have the same openDateUtc on each.
    txs_by_open_dt: dict[str, list[dict]] = defaultdict(list)
    for t in tx:
        od = t.get("openDateUtc", "")
        if od:
            txs_by_open_dt[od].append(t)

    # Activity → group by open dealId
    activity_by_deal: dict[str, list[dict]] = defaultdict(list)
    opens_by_deal: dict[str, dict] = {}
    for a in act:
        did = a.get("dealId", "")
        aff = a.get("affectedDealId", "")
        # Lifecycle events use affectedDealId when they change state of an existing position.
        # POSITION_OPENED: dealId == affectedDealId (new position).
        # POSITION_CLOSED: affectedDealId == the open; dealId == the close deal id.
        # STOP_LIMIT_AMENDED: affectedDealId == open; dealId == amendment id.
        # POSITION_PARTIALLY_CLOSED: affectedDealId == open.
        if a.get("actionType") == "POSITION_OPENED":
            key = did or aff
            opens_by_deal[key] = a
            activity_by_deal[key].append(a)
        else:
            key = aff or did
            activity_by_deal[key].append(a)

    # Load internal
    uni = load_unified_trades(from_d, to_d)
    bbb_rows = load_bbb_csv(from_d, to_d)
    # BB Bounce CSV only contains closed trades with deal_id populated for FILLs
    bbb_opens_by_deal: dict[str, dict] = {}
    bbb_rows_by_dealref: dict[str, dict] = {}
    for row in bbb_rows:
        did = (row.get("deal_id") or "").strip()
        if did:
            bbb_opens_by_deal[did] = row
        dref = (row.get("deal_reference") or "").strip()
        if dref:
            bbb_rows_by_dealref[dref] = row
    emapb_by_deal = load_emapb_setups(from_d, to_d)

    # Build the reconciled trade ledger — one entry per IG open dealId
    ledger: dict[str, dict[str, Any]] = {}
    for did, open_act in opens_by_deal.items():
        closes_act = [a for a in activity_by_deal.get(did, [])
                      if a.get("actionType") in ("POSITION_CLOSED", "POSITION_PARTIALLY_CLOSED")]
        amends_act = [a for a in activity_by_deal.get(did, [])
                      if a.get("actionType") == "STOP_LIMIT_AMENDED"]
        # Match transactions by openDateUtc (second resolution). Within a bucket,
        # tighten with direction+size when there are multiple opens in the same second.
        open_dt = open_act.get("date", "")
        candidate_tx = list(txs_by_open_dt.get(open_dt, []))
        if len(candidate_tx) > 1:
            want_dir = (open_act.get("direction") or "").upper()
            want_size = _parse_pnl(str(open_act.get("size") or "")) or None
            tx_rows = []
            for t in candidate_tx:
                sz, dr = _size_direction(t.get("size", ""))
                if want_dir in ("BUY", "SELL") and dr != want_dir:
                    continue
                tx_rows.append(t)
            if not tx_rows:
                tx_rows = candidate_tx
        else:
            tx_rows = candidate_tx
        uni_open = uni["opens"].get(did)
        uni_close = uni["closes"].get(did)
        bbb_row = bbb_opens_by_deal.get(did)

        emapb_row = emapb_by_deal.get(did)
        deal_ref = (
            (uni_open or {}).get("deal_reference")
            or (bbb_row or {}).get("deal_reference")
            or ((emapb_row or {}).get("setup") or {}).get("deal_reference")
            or ""
        )
        strategy = (uni_open or {}).get("strategy") or (
            "EMA_PULLBACK" if emapb_row else ""
        )
        src, fam = classify_strategy(deal_ref, strategy)

        size, direction = _size_direction((tx_rows[0] if tx_rows else {}).get("size", ""))
        open_level = _parse_pnl((tx_rows[0] if tx_rows else {}).get("openLevel", "")) \
            if tx_rows else open_act.get("level")
        close_level = _parse_pnl((tx_rows[0] if tx_rows else {}).get("closeLevel", "")) \
            if tx_rows else None
        pnl_gbp = sum((_parse_pnl(t.get("profitAndLoss", "")) or 0.0) for t in tx_rows) or None

        # Internal fill-level stop/limit from BBB CSV if present
        internal_stop = None
        internal_target = None
        if bbb_row:
            try:
                internal_stop = float(bbb_row.get("stop_level") or "nan")
            except Exception:
                pass
            try:
                internal_target = float(bbb_row.get("take_profit_level") or "nan")
            except Exception:
                pass

        ledger[did] = {
            "ig_open_deal_id": did,
            "ig_open_date_utc": open_act.get("date"),
            "ig_direction": open_act.get("direction") or direction,
            "ig_open_level": _parse_pnl(str(open_act.get("level") or "")) or open_level,
            "ig_initial_stop_level": _parse_pnl(str(open_act.get("stopLevel") or "")),
            "ig_initial_limit_level": _parse_pnl(str(open_act.get("limitLevel") or "")),
            "ig_channel": open_act.get("channel"),
            "ig_tx_rows": tx_rows,
            "ig_close_level": close_level,
            "ig_pnl_gbp_sum": pnl_gbp,
            "ig_closes": [{"actionType": a.get("actionType"), "date": a.get("date"),
                            "level": a.get("level"), "channel": a.get("channel"),
                            "description": a.get("description"),
                            "deal_id": a.get("dealId")} for a in closes_act],
            "ig_amendments": [{"date": a.get("date"), "stop": a.get("stopLevel"),
                               "limit": a.get("limitLevel"),
                               "channel": a.get("channel")} for a in amends_act],
            "source_system": src,
            "strategy_family": fam,
            "deal_reference": deal_ref,
            "unified_open_present": uni_open is not None,
            "unified_close_present": uni_close is not None,
            "unified_strategy_tag": strategy,
            "unified_entry_price": (uni_open or {}).get("entry_price"),
            "unified_exit_price": (uni_close or {}).get("exit_price"),
            "unified_pnl_gbp": (uni_close or {}).get("pnl_gbp"),
            "bbb_report_row": bbb_row is not None,
            "bbb_outcome": (bbb_row or {}).get("outcome"),
            "bbb_stop_level": internal_stop,
            "bbb_tp_level": internal_target,
            "emapb_setup_row": emapb_row is not None,
            "emapb_event": (emapb_row or {}).get("event"),
            "emapb_fill_price": ((emapb_row or {}).get("setup") or {}).get("fill_price"),
        }

    # Also catch unified_trades OPENs that have NO matching IG open — ought to be zero
    unmatched_internal: list[dict] = []
    for did, row in uni["opens"].items():
        if did not in ledger:
            unmatched_internal.append({
                "deal_id": did, "deal_reference": row.get("deal_reference"),
                "strategy": row.get("strategy"), "entry_price": row.get("entry_price"),
                "ts_utc": row.get("ts_utc")
            })

    # Catch BB Bounce CSV FILL rows that have no IG open (should be rare)
    unmatched_bbb: list[dict] = []
    for did, row in bbb_opens_by_deal.items():
        if did not in ledger:
            unmatched_bbb.append({
                "deal_id": did, "deal_reference": row.get("deal_reference"),
                "setup_time_utc": row.get("setup_time_utc"), "outcome": row.get("outcome"),
            })

    # Summarise by strategy family / source system
    by_src = Counter(t["source_system"] for t in ledger.values())
    by_fam = Counter(t["strategy_family"] for t in ledger.values())
    unified_coverage = Counter(
        "both" if (t["unified_open_present"] and t["unified_close_present"]) else
        ("open_only" if t["unified_open_present"] else
         ("close_only" if t["unified_close_present"] else "neither"))
        for t in ledger.values()
    )

    # Match quality grading per trade
    def grade(t: dict) -> str:
        src = t["source_system"]
        has_ig_pnl = t["ig_pnl_gbp_sum"] is not None
        has_ig_close = bool(t.get("ig_closes"))
        if src == "bb_bounce_standalone":
            if t["bbb_report_row"] and has_ig_pnl:
                return "FULLY_RECONCILED"
            if t["bbb_report_row"] and not has_ig_close:
                return "OPEN_POSITION_IG_PENDING"
            if t["bbb_report_row"]:
                return "MATCHED_NO_IG_PNL"
            return "IG_ONLY"
        if src == "ema_pullback_standalone":
            if t["emapb_setup_row"] and has_ig_pnl:
                return "FULLY_RECONCILED"
            if t["emapb_setup_row"] and not has_ig_close:
                return "OPEN_POSITION_IG_PENDING"
            if t["emapb_setup_row"]:
                return "MATCHED_NO_IG_PNL"
            return "IG_ONLY"
        if src == "autobot":
            if t["unified_open_present"] and t["unified_close_present"] and has_ig_pnl:
                return "FULLY_RECONCILED"
            if t["unified_open_present"] and has_ig_pnl:
                return "MATCHED_NO_INTERNAL_CLOSE"
            if t["unified_open_present"] and not has_ig_close:
                return "OPEN_POSITION_IG_PENDING"
            if t["unified_open_present"]:
                return "MATCHED_NO_IG_PNL"
            return "IG_ONLY"
        if src == "sibling_host_h144":
            return "SIBLING_HOST"
        # Unattributed → split by date-window relative to internal-log coverage
        od = t.get("ig_open_date_utc", "")
        ch = t.get("ig_channel")
        if ch == "WEB":
            return "MANUAL_UI_INTERVENTION"
        if od and od < "2026-10-07":
            return "PRE_LOG_COVERAGE"  # before unified_trades started
        return "UNATTRIBUTED_SIBLING_LIKELY"

    grades = Counter()
    for t in ledger.values():
        g = grade(t)
        t["match_grade"] = g
        grades[g] += 1

    summary = {
        "window": [from_d, to_d],
        "ig_total_gbpusd_deal_rows": len(tx),
        "ig_total_opens": len(opens_by_deal),
        "ig_total_activity_rows": len(act),
        "autobot_unified_opens_in_window": len(uni["opens"]),
        "autobot_unified_closes_in_window": len(uni["closes"]),
        "bbb_csv_rows_in_window": len(bbb_rows),
        "bbb_fill_rows_with_dealId": len(bbb_opens_by_deal),
        "ledger_size": len(ledger),
        "by_source_system": dict(by_src),
        "by_strategy_family": dict(by_fam),
        "unified_coverage": dict(unified_coverage),
        "match_grades": dict(grades),
        "unmatched_internal_count": len(unmatched_internal),
        "unmatched_bbb_count": len(unmatched_bbb),
    }

    return {"ledger": ledger, "summary": summary,
            "unmatched_internal": unmatched_internal,
            "unmatched_bbb": unmatched_bbb,
            "open_positions_now": pos}


def main() -> int:
    out = reconcile("2026-09-17", "2026-10-27")
    (DATA_DIR / "trade_ledger.json").write_text(json.dumps(out["ledger"], indent=2, default=str))
    (DATA_DIR / "trade_match_summary.json").write_text(json.dumps({
        "summary": out["summary"],
        "unmatched_internal": out["unmatched_internal"],
        "unmatched_bbb": out["unmatched_bbb"],
    }, indent=2, default=str))
    print(json.dumps(out["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
