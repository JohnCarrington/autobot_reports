"""Single-day replay with full engine-journal capture.

Reuses the production harness (`core_engine_replay.py`) but:

  1. Scopes to a single calendar date.
  2. Captures EVERY engine journal line + port call so misses can be
     cited at bar granularity.
  3. Still warms up with 60+ prior clean days so bollinger/EMA/HTF
     are not cold.

CLI:
    PYTHONPATH=.:/opt/tradingbot \
        python3 autobot_v3_build/approved/single_day_runner.py \
        --date 2026-01-28 --mode sl12_tp30
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROD = "/opt/tradingbot"
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)

OUT_DIR = Path(__file__).resolve().parent / "replay_out"
OUT_DIR.mkdir(exist_ok=True)


def _apply_env(mode: str) -> None:
    """Mirror of core_engine_replay._apply_env — identical settings."""
    base = {
        "BOUNCE_SQUEEZE_ENABLED": "1",
        "BOUNCE_TREND_ENABLED": "1",
        "BOUNCE_EXHAUSTION_ENABLED": "1",
        "BOUNCE_NEWS_VIEW_ENABLED": "1",
        "BOUNCE_HTF_DIRECTION_ENABLED": "1",
        "BOUNCE_TREND_HTF_PROOF_ENABLED": "1",
        "BOUNCE_C_MACD_FADING_ENABLED": "1",
        "BOUNCE_JUNE_EXHAUSTION_CLOSE_ENABLED": "1",
        "BOUNCE_ENTRY_HOURS_UTC": "06-21",
        "BOUNCE_BROKER_TP_PIPS": "100",
        "BOUNCE_EXIT_MODE": "june",
    }
    for k, v in base.items():
        os.environ[k] = v


class CapturingJournal:
    def __init__(self) -> None:
        self.lines: List[Dict[str, Any]] = []

    def __call__(self, text: str, **facts: Any) -> None:
        self.lines.append({"text": text, **facts})

    def write(self, line: str) -> None:
        self.lines.append({"text": line})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD UTC date to replay")
    ap.add_argument("--mode", choices=["june_prod", "sl12_tp30"], default="sl12_tp30")
    ap.add_argument("--warmup-days", type=int, default=60,
                    help="How many prior clean days to feed as warmup")
    ap.add_argument("--no-ticks", action="store_true")
    ap.add_argument("--no-qm", action="store_true")
    args = ap.parse_args()

    target_date = date.fromisoformat(args.date)
    target_iso = target_date.isoformat()
    _apply_env(args.mode)

    # Deferred imports (env must be set first for Config factory defaults).
    from bounce_engine.core import Bar, Config, Engine
    from autobot_v3_build.approved.core_engine_replay import (
        HistoryPool, ReplayOrderPort, _close_matching_trade,
        _simulate_broker_stops_pre_bar, _view_levels_fn_factory,
        _events_fn_no_op, _qm_fn_no_op, finalise_pnl,
    )
    from autobot_v3_build.approved.stage0b_loader import (
        iter_clean_days, load_day_bars,
    )
    from autobot_v3_build.approved.tick_fills import TickResolver
    from autobot_v3_build.approved.historical_qm import HistoricalQM

    # Which partition does the target date belong to? For warmup we want
    # the prior clean days across all partitions, chronologically.
    all_clean = list(iter_clean_days(None))
    all_clean.sort(key=lambda cd: cd.date_iso)
    # Isolate target
    target_cd = next((cd for cd in all_clean if cd.date_iso == target_iso), None)
    if target_cd is None:
        print(f"ERROR: {target_iso} is not in the Stage 0b CLEAN manifest")
        sys.exit(1)
    priors = [cd for cd in all_clean if cd.date_iso < target_iso][-args.warmup_days:]
    print(f"[single_day] target={target_iso} ({target_cd.candle_src}, {target_cd.regime}) "
          f"warmup_days={len(priors)}")

    pool = HistoryPool()
    for cd in priors:
        pool.all_m5.extend(load_day_bars(cd))
    pool.all_m5.extend(load_day_bars(target_cd))
    pool.all_m5.sort(key=lambda b: b["ts"])
    print(f"[single_day] pool bars: {len(pool.all_m5)}  "
          f"(span {pool.all_m5[0]['ts'].isoformat()} → {pool.all_m5[-1]['ts'].isoformat()})")

    # Build engine
    cfg = Config()
    if args.mode == "sl12_tp30":
        import dataclasses as _dc
        cfg = _dc.replace(cfg, june_sl_pips=12.0)
    port = ReplayOrderPort(partition="SINGLE_DAY")
    journal = CapturingJournal()
    view_cache: Dict[str, Any] = {}
    cur_ref: Dict[str, float] = {"today": "", "ref": 0.0}
    hqm: Optional[HistoricalQM] = None if args.no_qm else HistoricalQM()
    eng = Engine(
        cfg=cfg,
        levels_fn=_view_levels_fn_factory(view_cache, pool, cur_ref),
        qm_fn=(hqm.qm_fn if hqm is not None else _qm_fn_no_op),
        orders=port,
        journal=journal,
        events_fn=_events_fn_no_op,
    )

    # Verify engine identity + config
    print(f"[single_day] engine={Engine.__module__}.{Engine.__name__}")
    print(f"[single_day] cfg: exit_mode={cfg.exit_mode!r} sl={cfg.june_sl_pips} tp={cfg.june_tp_pips} "
          f"partial={cfg.june_partial_pips} squeeze={cfg.squeeze_enabled} trend={cfg.trend_enabled} "
          f"htf={cfg.htf_direction_enabled}")

    # Tick resolver for the target day only (warmup bars don't need
    # tick-fill resolution since no positions carry across).
    ticks: Optional[TickResolver] = None
    if not args.no_ticks:
        ticks = TickResolver(pair="GBPUSD", target_dates={target_iso}, verbose=True)
        ticks.prepare()
        print(f"[single_day] tick coverage: {ticks.has_coverage(target_iso)}")

    # Mark where journal capture should START (we only report target-day events)
    target_date_only_idx = None
    bar_count = 0
    for b in pool.all_m5:
        day_iso = b["ts"].date().isoformat()
        cur_ref["today"] = day_iso
        cur_ref["ref"] = float(b["close"])
        bar = Bar(ts=b["ts"], open=b["open"], high=b["high"],
                   low=b["low"], close=b["close"])
        if day_iso == target_iso and target_date_only_idx is None:
            target_date_only_idx = len(journal.lines)
            print(f"[single_day] target day reached at bar {bar_count} "
                  f"(engine warmup bars: {bar_count}); journal from here on is target-day")
        # Pre-bar broker stop simulation only on target day (warmup
        # positions should have been cleared by the engine's own
        # friday-flatten / weekend logic).
        if day_iso == target_iso:
            _simulate_broker_stops_pre_bar(eng, port, bar, ticks=ticks)
        try:
            eng.on_bar_close(bar)
        except Exception as exc:
            print(f"[single_day] exc at {b['ts']}: {type(exc).__name__}: {exc}")
        if hqm is not None:
            hqm.push_bar(bar)
        bar_count += 1
    for t in port.trades:
        finalise_pnl(t)

    # Report
    print("\n=== TARGET-DAY JOURNAL (chronological) ===\n")
    seen = set()
    for j in journal.lines[target_date_only_idx or 0:]:
        txt = j.get("text", "")
        ev = j.get("event", "")
        ts = j.get("ts") or j.get("bar_ts") or j.get("close_ts") or ""
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        key = (txt, ev, ts)
        if key in seen:
            continue
        seen.add(key)
        print(f"  [{ev or '-':<30}] {txt}")

    print("\n=== TARGET-DAY TRADES (port call-log) ===\n")
    tgt_trades = [t for t in port.trades
                   if t.open_ts and t.open_ts.date().isoformat() == target_iso]
    if not tgt_trades:
        print("  (NO TRADES opened on target day)")
    for t in tgt_trades:
        print(f"  open  {t.open_ts.isoformat()}  side={t.side}  setup={t.setup}  "
              f"entry={t.entry_price}  stop={t.stop}")
        for p in t.partials:
            print(f"    partial  {p.get('ts')}  @ {p.get('price')}  "
                  f"ratio={p.get('size_ratio')}  reason={p.get('reason')}  pips={p.get('pips')}")
        if t.close_ts:
            print(f"  close {t.close_ts.isoformat()}  @ {t.close_price}  "
                  f"reason={t.close_reason}  fill_source={t.fill_source}  "
                  f"realised_pips={t.realised_pips}  net_pips={t.net_pips}")
        else:
            print(f"  still-open at end-of-day")

    print("\n=== QM VERDICTS ===")
    if hqm is not None:
        print(f"  {hqm.verdicts}")
    else:
        print("  QM shadow disabled (--no-qm)")

    # Save complete journal + trades for the record
    out = {
        "target_date": target_iso,
        "mode": args.mode,
        "warmup_days": len(priors),
        "cfg": {
            "exit_mode": cfg.exit_mode,
            "june_sl_pips": cfg.june_sl_pips,
            "june_tp_pips": cfg.june_tp_pips,
            "june_partial_pips": cfg.june_partial_pips,
            "squeeze_enabled": cfg.squeeze_enabled,
            "trend_enabled": cfg.trend_enabled,
            "htf_direction_enabled": cfg.htf_direction_enabled,
        },
        "use_ticks": not args.no_ticks,
        "use_qm": not args.no_qm,
        "journal_target_day": [{k: str(v) if isinstance(v, datetime) else v
                                 for k, v in j.items()}
                                for j in journal.lines[target_date_only_idx or 0:]],
        "trades_target_day": [{
            "open_ts": t.open_ts.isoformat() if t.open_ts else None,
            "side": t.side,
            "setup": t.setup,
            "entry_price": t.entry_price,
            "stop": t.stop,
            "close_ts": t.close_ts.isoformat() if t.close_ts else None,
            "close_price": t.close_price,
            "close_reason": t.close_reason,
            "fill_source": t.fill_source,
            "realised_pips": t.realised_pips,
            "net_pips": t.net_pips,
            "partials": t.partials,
            "stop_history": t.stop_history,
        } for t in tgt_trades],
        "qm_verdicts": dict(hqm.verdicts) if hqm is not None else None,
    }
    path = OUT_DIR / f"single_day_{target_iso}_{args.mode}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[single_day] wrote {path}")


if __name__ == "__main__":
    main()
