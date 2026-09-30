#!/usr/bin/env python3
"""
cascade_outcome_join.py — Phase 4B cascade-vs-trade-outcome join.

Motivating audit (2026-05-12): the 2026-05-19 regime-gate review (see
`docs/regime_classifier_status_2026-05-12.md`) needs a re-runnable predicted-vs-
actual reconciliation between the Phase 4B `CandleRegimeClassifier` cascade
labels (TREND_UP / TREND_DOWN / RANGE / NEUTRAL) and live trade outcomes from
`signal_log.jsonl`. No continuous reconciliation exists; this script is the
join.

Data sources
------------
1. `/opt/tradingbot/logs/signal_log.jsonl`
   - One closed (or PHANTOM/IG_RECONCILE/MANUAL) trade per line. Field
     `cascade_stable_at_fire` was added 2026-05-11 (commit 39bb4bb) and is
     present only on trades opened from that date onward. Earlier trades need
     the fallback below.
2. `/opt/tradingbot/logs/regime_shadow.jsonl` (Phase 4B cascade per-bar shadow)
   - Every 5m close for all 4 pairs since 2026-04-28. Provides the cascade
     label fallback for any signal_log row that lacks `cascade_stable_at_fire`.
   - NOTE: the regime status doc references `logs/gbpusd_regime.jsonl` for the
     cascade. That is the *gbpusd_regime_detector* (a different, simpler
     classifier, GBPUSD only). Phase 4B's cascade lives in
     `regime_shadow.jsonl` and covers all four pairs.
3. `/opt/tradingbot/logs/forensic_fires.jsonl` (388-field per-fire snapshot)
   - Cross-checked for completeness. As of 2026-05-12, the snapshot does NOT
     contain `cascade_stable_at_fire` directly — that field lives only on
     `signal_log.jsonl` since 2026-05-11. The forensic file is therefore not
     strictly required for the join, but the script still reads it so that
     joined rows can be flagged when a forensic snapshot does exist (i.e. fires
     on or after 2026-05-05).

Output
------
- CSV table of joined rows (`--out csv|both`)
- stdout summary (`--out summary|both`) with by-strategy + by-cascade-bucket
  aggregates and an optional `--gate-by-cascade` counterfactual.

Assumptions
-----------
- £ PnL = pnl_pips × `--lot-size` (default 1.0, per .env TRADE_SIZE=1.0; see
  `docs/trades_review_2026-05-11_to_2026-05-12.md` Part 1).
- "Closed trade" filter excludes outcomes ∈ {None, PHANTOM_NEVER_EXECUTED} —
  these never actually executed in the market.
- Cascade-agree mapping is empirical: TREND_UP/TREND_DOWN are directional;
  RANGE and NEUTRAL are "neutral". See `cascade_agrees()` below.

Usage
-----
  # Defaults: last 30 days, all strategies, all pairs, stdout summary
  python3 scripts/cascade_outcome_join.py

  # Write CSV and summary
  python3 scripts/cascade_outcome_join.py --out both --csv-path /tmp/cascade_join_30d.csv

  # BB_BOUNCE_L deep-dive with counterfactual
  python3 scripts/cascade_outcome_join.py \\
      --strategy GBPUSD_BB_BOUNCE_L --strategy GBPUSD_BB_BOUNCE_S \\
      --gate-by-cascade --out summary

No external network calls. Re-running with the same args is idempotent.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/opt/tradingbot")
SIGNAL_LOG = ROOT / "logs" / "signal_log.jsonl"
REGIME_SHADOW = ROOT / "logs" / "regime_shadow.jsonl"
FORENSIC = ROOT / "logs" / "forensic_fires.jsonl"

# Outcomes that did NOT actually execute in the market — exclude from analysis.
NON_EXECUTED_OUTCOMES = {None, "", "PHANTOM_NEVER_EXECUTED"}

# Empirical cascade-label vocabulary inspected in regime_shadow.jsonl:
#   {'NEUTRAL', 'RANGE', 'TREND_UP', 'TREND_DOWN'}
DIRECTIONAL_BULL = {"TREND_UP"}
DIRECTIONAL_BEAR = {"TREND_DOWN"}
NEUTRAL_LABELS = {"NEUTRAL", "RANGE"}


# -------------------------------------------------------------------- parsing


def _parse_iso(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


# ------------------------------------------------------------------ loaders


def load_signal_log(since: datetime, until: datetime):
    rows = []
    for d in _read_jsonl(SIGNAL_LOG):
        dt = _parse_iso(d.get("timestamp_open"))
        if dt is None:
            continue
        if dt < since or dt > until:
            continue
        if d.get("outcome") in NON_EXECUTED_OUTCOMES:
            continue
        rows.append(d)
    return rows


def load_regime_shadow(since: datetime, until: datetime):
    """Return dict: pair -> sorted list of (dt, stable_label, shadow_label, conf)."""
    by_pair: dict[str, list] = defaultdict(list)
    pad = timedelta(hours=1)
    lo, hi = since - pad, until + pad
    for d in _read_jsonl(REGIME_SHADOW):
        dt = _parse_iso(d.get("ts"))
        if dt is None:
            continue
        if dt < lo or dt > hi:
            continue
        pair = (d.get("symbol") or "").upper()
        by_pair[pair].append(
            (
                dt,
                d.get("stable"),
                d.get("shadow_label"),
                d.get("shadow_confidence"),
            )
        )
    for k in by_pair:
        by_pair[k].sort(key=lambda r: r[0])
    return by_pair


def load_forensic(since: datetime, until: datetime):
    """Return list of (dt_open, strategy, direction, entry, dict)."""
    rows = []
    pad = timedelta(minutes=5)
    lo, hi = since - pad, until + pad
    for d in _read_jsonl(FORENSIC):
        dt = _parse_iso(d.get("timestamp"))
        if dt is None:
            continue
        if dt < lo or dt > hi:
            continue
        rows.append(d)
    return rows


# ------------------------------------------------------------------- helpers


def find_shadow_for(pair: str, dt_open: datetime, shadow_by_pair, max_lag=timedelta(minutes=5)):
    """Last shadow emission <= dt_open within max_lag."""
    rows = shadow_by_pair.get(pair, [])
    if not rows:
        return None
    # Binary-ish linear walk back from end (small n; fine).
    pick = None
    for entry in rows:
        if entry[0] > dt_open:
            break
        pick = entry
    if pick is None:
        return None
    if dt_open - pick[0] > max_lag:
        return None
    return pick


def find_forensic_for(pair: str, strategy: str, direction: str, dt_open: datetime, forensic_rows, tol=timedelta(seconds=60)):
    """Find a forensic snapshot matching this fire (timestamp within tol)."""
    best = None
    best_dt = None
    for d in forensic_rows:
        if d.get("strategy") != strategy:
            continue
        # forensic doesn't carry direction in a stable case, but it has it as "LONG"/"SHORT" — direction strings vary.
        # Be permissive: match BUY↔LONG, SELL↔SHORT, or exact equality.
        fdir = (d.get("direction") or "").upper()
        if direction == "BUY" and fdir not in ("BUY", "LONG"):
            continue
        if direction == "SELL" and fdir not in ("SELL", "SHORT"):
            continue
        dt = _parse_iso(d.get("timestamp"))
        if dt is None:
            continue
        diff = abs(dt - dt_open)
        if diff > tol:
            continue
        if best is None or diff < best_dt:
            best = d
            best_dt = diff
    return best


def cascade_agrees(direction: str, cascade_label):
    if cascade_label is None:
        return None
    if direction == "BUY":
        if cascade_label in DIRECTIONAL_BULL:
            return "TRUE"
        if cascade_label in DIRECTIONAL_BEAR:
            return "FALSE"
        if cascade_label in NEUTRAL_LABELS:
            return "NEUTRAL"
    elif direction == "SELL":
        if cascade_label in DIRECTIONAL_BEAR:
            return "TRUE"
        if cascade_label in DIRECTIONAL_BULL:
            return "FALSE"
        if cascade_label in NEUTRAL_LABELS:
            return "NEUTRAL"
    return None


# ---------------------------------------------------------------------- main


def build_join(args):
    since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    until = datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)

    trades = load_signal_log(since, until)
    shadow_by_pair = load_regime_shadow(since, until)
    forensic_rows = load_forensic(since, until)

    out_rows = []
    for t in trades:
        strat = t.get("strategy")
        pair = (t.get("pair") or "").upper()
        if args.strategy and strat not in args.strategy:
            continue
        if args.pair and pair not in [p.upper() for p in args.pair]:
            continue

        direction = (t.get("direction") or "").upper()
        dt_open = _parse_iso(t.get("timestamp_open"))
        cascade_label = t.get("cascade_stable_at_fire")
        cascade_conf = t.get("axis_confidence_direction") or t.get("axis_confidence_structure")
        cascade_source = "signal_log" if cascade_label is not None else None

        forensic_match = find_forensic_for(pair, strat, direction, dt_open, forensic_rows) if dt_open else None
        if forensic_match is not None and cascade_label is None:
            # Forensic file doesn't carry cascade_stable directly today, but flag presence.
            pass
        forensic_flag = "yes" if forensic_match is not None else "no"

        if cascade_label is None and dt_open is not None:
            pick = find_shadow_for(pair, dt_open, shadow_by_pair)
            if pick is not None:
                _, cascade_label, shadow_label, conf = pick
                cascade_conf = conf
                cascade_source = "shadow"

        if cascade_label is None:
            cascade_source = "none"

        pnl_pips = t.get("pnl_pips")
        pnl_gbp = None if pnl_pips is None else round(pnl_pips * args.lot_size, 4)
        agree = cascade_agrees(direction, cascade_label)

        out_rows.append(
            {
                "trade_id": t.get("deal_id") or t.get("id"),
                "timestamp_open": t.get("timestamp_open"),
                "pair": pair,
                "strategy": strat,
                "direction": direction,
                "entry": t.get("entry"),
                "cascade_label": cascade_label,
                "cascade_confidence": cascade_conf,
                "cascade_source": cascade_source,
                "cascade_agrees": agree,
                "forensic_snapshot": forensic_flag,
                "pnl_pips": pnl_pips,
                "pnl_gbp": pnl_gbp,
                "close_reason": t.get("close_reason"),
                "outcome": t.get("outcome"),
                "mfe_pips": t.get("mfe_pips"),
                "mae_pips": t.get("mae_pips"),
                "daily_bias": t.get("daily_bias"),
            }
        )
    return out_rows


# -------------------------------------------------------------- aggregation


def _bucket_stats(rows):
    n = len(rows)
    wins = sum(1 for r in rows if (r.get("pnl_pips") or 0) > 0)
    total_pips = sum((r.get("pnl_pips") or 0) for r in rows)
    avg_pips = (total_pips / n) if n else 0.0
    wr = (100.0 * wins / n) if n else 0.0
    return {"n": n, "wins": wins, "wr": wr, "total_pips": total_pips, "avg_pips": avg_pips}


def aggregate(rows):
    by_strat = defaultdict(list)
    for r in rows:
        by_strat[r["strategy"]].append(r)

    table = []
    for strat, group in sorted(by_strat.items()):
        agree = [r for r in group if r["cascade_agrees"] == "TRUE"]
        disagree = [r for r in group if r["cascade_agrees"] == "FALSE"]
        neutral = [r for r in group if r["cascade_agrees"] == "NEUTRAL"]
        none = [r for r in group if r["cascade_agrees"] is None]
        overall = _bucket_stats(group)
        table.append(
            {
                "strategy": strat,
                "n": overall["n"],
                "wr": overall["wr"],
                "total_pips": overall["total_pips"],
                "agree": _bucket_stats(agree),
                "disagree": _bucket_stats(disagree),
                "neutral": _bucket_stats(neutral),
                "none": _bucket_stats(none),
            }
        )
    return table


def print_summary(rows, gate=False, gate_neutral=False):
    if not rows:
        print("(no rows after filters)")
        return

    print("=" * 90)
    print(f"Cascade-outcome join — {len(rows)} fires")
    print("=" * 90)

    # Overall
    overall = _bucket_stats(rows)
    by_agree = defaultdict(list)
    for r in rows:
        by_agree[r["cascade_agrees"]].append(r)

    print("\nOverall buckets (cascade vs trade direction):")
    print(f"  {'bucket':<14} {'n':>4} {'wr%':>7} {'tot_pips':>10} {'avg':>8}")
    for label in ("TRUE", "FALSE", "NEUTRAL", None):
        st = _bucket_stats(by_agree.get(label, []))
        name = {None: "NO_CASCADE"}.get(label, label)
        flag = " <n<5>" if 0 < st["n"] < 5 else ""
        print(f"  {name:<14} {st['n']:>4} {st['wr']:>6.1f}% {st['total_pips']:>10.2f} {st['avg_pips']:>8.2f}{flag}")

    # By strategy
    table = aggregate(rows)
    print(f"\nBy strategy:")
    hdr = f"  {'strategy':<28} {'n':>3} {'wr%':>6} {'tot_p':>8}  "
    hdr += f"{'agree-n':>7} {'agree-wr':>9}  {'disag-n':>7} {'disag-wr':>9}  "
    hdr += f"{'neut-n':>6} {'neut-wr':>8}  {'none-n':>6}"
    print(hdr)
    for row in table:
        a, d, nu, no = row["agree"], row["disagree"], row["neutral"], row["none"]
        line = f"  {row['strategy']:<28} {row['n']:>3} {row['wr']:>5.1f}% {row['total_pips']:>8.2f}  "
        line += f"{a['n']:>7} {a['wr']:>8.1f}%  {d['n']:>7} {d['wr']:>8.1f}%  "
        line += f"{nu['n']:>6} {nu['wr']:>7.1f}%  {no['n']:>6}"
        print(line)
        # n<5 flag line for sample-size warnings
        warns = [k for k, v in (("agree", a), ("disagree", d), ("neutral", nu)) if 0 < v["n"] < 5]
        if warns:
            print(f"     n<5 bucket(s): {', '.join(warns)}")

    # Counterfactual
    if gate:
        print("\n" + "-" * 90)
        print("Counterfactual: blocked trades where cascade_agrees == FALSE")
        print("-" * 90)
        blocked = [r for r in rows if r["cascade_agrees"] == "FALSE"]
        kept = [r for r in rows if r["cascade_agrees"] != "FALSE"]
        if gate_neutral:
            blocked += [r for r in rows if r["cascade_agrees"] == "NEUTRAL"]
            kept = [r for r in rows if r["cascade_agrees"] not in ("FALSE", "NEUTRAL")]
            print("(also blocking NEUTRAL via --gate-neutral)")
        baseline = _bucket_stats(rows)
        after = _bucket_stats(kept)
        b_winners = sum(1 for r in blocked if (r.get("pnl_pips") or 0) > 0)
        b_losers = sum(1 for r in blocked if (r.get("pnl_pips") or 0) < 0)
        b_pips = sum((r.get("pnl_pips") or 0) for r in blocked)
        delta = after["total_pips"] - baseline["total_pips"]
        print(f"  baseline:           n={baseline['n']:>3}  wr={baseline['wr']:5.1f}%  tot_pips={baseline['total_pips']:8.2f}")
        print(f"  after gate (kept):  n={after['n']:>3}  wr={after['wr']:5.1f}%  tot_pips={after['total_pips']:8.2f}")
        print(f"  blocked:            n={len(blocked):>3}  winners-killed={b_winners}  losers-saved={b_losers}  tot_pips_blocked={b_pips:.2f}")
        print(f"  delta vs baseline:  {delta:+.2f} pips ({delta * 1.0:+.2f} £)")
        fpr = (b_winners / len(blocked) * 100.0) if blocked else 0.0
        print(f"  false-positive rate (winners-killed / blocked): {fpr:.1f}%")


def write_csv(rows, path: str | None):
    fields = [
        "trade_id", "timestamp_open", "pair", "strategy", "direction", "entry",
        "cascade_label", "cascade_confidence", "cascade_source", "cascade_agrees",
        "forensic_snapshot", "pnl_pips", "pnl_gbp", "close_reason", "outcome",
        "mfe_pips", "mae_pips", "daily_bias",
    ]
    if path:
        fh = open(path, "w", encoding="utf-8", newline="")
        close = True
    else:
        fh = sys.stdout
        close = False
    try:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    finally:
        if close:
            fh.close()
            print(f"[csv] wrote {len(rows)} rows -> {path}", file=sys.stderr)


# ---------------------------------------------------------------------- CLI


def parse_args(argv=None):
    today = datetime.now(tz=timezone.utc).date()
    default_until = today.isoformat()
    default_since = (today - timedelta(days=30)).isoformat()
    # Pin "today" to 2026-05-12 per the audit context if wall clock disagrees.
    # Keep the dynamic default; user can override via --since/--until.

    p = argparse.ArgumentParser(
        description="Join Phase 4B cascade labels with signal_log trade outcomes.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cascade_outcome_join.py\n"
            "  cascade_outcome_join.py --since 2026-04-12 --until 2026-05-12 --out both --csv-path /tmp/cascade.csv\n"
            "  cascade_outcome_join.py --strategy GBPUSD_BB_BOUNCE_L --strategy GBPUSD_BB_BOUNCE_S --gate-by-cascade\n"
        ),
    )
    p.add_argument("--since", default=default_since, help="ISO date YYYY-MM-DD (default: 30d ago)")
    p.add_argument("--until", default=default_until, help="ISO date YYYY-MM-DD (default: today)")
    p.add_argument("--strategy", action="append", default=[], help="Filter to strategy (repeatable)")
    p.add_argument("--pair", action="append", default=[], help="Filter to pair (repeatable)")
    p.add_argument("--out", choices=["summary", "csv", "both"], default="summary")
    p.add_argument("--csv-path", default=None, help="Path for --out csv|both (default stdout)")
    p.add_argument("--lot-size", type=float, default=1.0, help="GBP/pip — default 1.0 per .env TRADE_SIZE")
    p.add_argument("--gate-by-cascade", action="store_true", help="Counterfactual: block cascade_agrees==FALSE")
    p.add_argument("--gate-neutral", action="store_true", help="Also block cascade_agrees==NEUTRAL")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    rows = build_join(args)
    if args.out in ("csv", "both"):
        write_csv(rows, args.csv_path)
    if args.out in ("summary", "both"):
        print_summary(rows, gate=args.gate_by_cascade, gate_neutral=args.gate_neutral)


if __name__ == "__main__":
    main()
