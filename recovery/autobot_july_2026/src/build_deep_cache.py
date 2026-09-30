#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_deep_cache.py — Manual deep cache builder for HTF preloading.

Run once manually (Sunday evening recommended) to fetch deep historical
5M candle data for H1/H4/D1 bias calculation.

Usage:
    python3 build_deep_cache.py [--symbols GBPUSD,EURUSD] [--bars 2000] [--dry-run]
    python3 build_deep_cache.py --force          # re-fetch even if recent cache exists
    python3 build_deep_cache.py --dry-run        # show plan without API calls

WARNING: Uses IG historical data allowance. Check remaining allowance
before running. Do not run automatically or on bot restart.
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("DeepCache")

# ============================================================
# CONFIG
# ============================================================

CACHE_DIR = os.getenv("CACHE_DIR", "/opt/tradingbot/cache").strip() or "/opt/tradingbot/cache"
DEEP_CACHE_BARS = int(float(os.getenv("DEEP_CACHE_BARS", "2000") or 2000))
DEEP_CACHE_MAX_AGE_DAYS = float(os.getenv("DEEP_CACHE_MAX_AGE_DAYS", "6") or 6)
DEEP_CACHE_D1_BARS = int(float(os.getenv("DEEP_CACHE_D1_BARS", "100") or 100))
INTER_SYMBOL_SLEEP_S = float(os.getenv("DEEP_CACHE_SLEEP_S", "2") or 2)

# Parse CFD epic mapping from env
CFD_EPICS_JSON = (os.getenv("CFD_EPICS_JSON") or "").strip()
CFD_EPIC_MAP: Dict[str, str] = {}
if CFD_EPICS_JSON:
    try:
        tmp = json.loads(CFD_EPICS_JSON)
        CFD_EPIC_MAP = {str(k).upper(): str(v) for k, v in tmp.items()}
    except Exception as e:
        logger.error(f"Failed to parse CFD_EPICS_JSON: {e}")


def _deep_cache_path(symbol: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol.upper()}_candles_deep.csv")


def _d1_cache_path(symbol: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol.upper()}_candles_d1.csv")


def _cache_age_days(path: str) -> Optional[float]:
    """Return age of file in days, or None if doesn't exist."""
    try:
        mtime = os.path.getmtime(path)
        return (time.time() - mtime) / 86400.0
    except OSError:
        return None


def _extract_allowance(response: Any) -> Dict[str, Any]:
    """Extract allowance info from IG API response."""
    allowance = {"remainingAllowance": "unknown", "totalAllowance": "unknown", "allowanceExpiry": "unknown"}
    try:
        if isinstance(response, dict):
            raw = response.get("allowance") or {}
            if isinstance(raw, dict):
                allowance["remainingAllowance"] = raw.get("remainingAllowance", "unknown")
                allowance["totalAllowance"] = raw.get("totalAllowance", "unknown")
                allowance["allowanceExpiry"] = raw.get("allowanceExpiry", "unknown")
    except Exception:
        pass
    return allowance


def _normalize_prices_df(response: Any):
    """Extract and normalize prices DataFrame from IG response."""
    import pandas as pd

    if not isinstance(response, dict):
        return None

    prices = response.get("prices")
    if prices is None:
        return None

    # If return_dataframe=True, prices is already a DataFrame
    if hasattr(prices, "columns"):
        df = prices.copy()
    elif isinstance(prices, list):
        rows = []
        for p in prices:
            if not isinstance(p, dict):
                continue
            ts = p.get("snapshotTimeUTC") or p.get("snapshotTime") or p.get("timestamp")

            def _mid(x, fallback_key):
                if isinstance(x, dict):
                    return x.get("mid")
                return p.get(fallback_key)

            o = _mid(p.get("openPrice"), "open")
            h = _mid(p.get("highPrice"), "high")
            l_ = _mid(p.get("lowPrice"), "low")
            c = _mid(p.get("closePrice"), "close")
            if c is None:
                continue
            rows.append({"timestamp": ts, "open": o, "high": h, "low": l_, "close": c})
        if not rows:
            return None
        df = pd.DataFrame(rows)
    else:
        return None

    # Standardize column names
    if "timestamp" not in df.columns:
        # trading_ig DataFrames use a MultiIndex or specific column naming
        # Try common alternatives
        for col_name in ("DateTime", "datetime", "time", "snapshotTimeUTC", "snapshotTime"):
            if col_name in df.columns:
                df = df.rename(columns={col_name: "timestamp"})
                break

    # Handle trading_ig multi-level columns: ('bid', 'Open'), ('ask', 'Open'), etc.
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        # Flatten — prefer 'mid' prices if available, else 'bid'
        flat_cols = {}
        for col_tuple in df.columns:
            if not isinstance(col_tuple, tuple):
                continue
            price_type, ohlc = col_tuple[0], col_tuple[1]
            ohlc_lower = str(ohlc).lower()
            if ohlc_lower in ("open", "high", "low", "close") and price_type in ("mid", "bid"):
                if ohlc_lower not in flat_cols or price_type == "mid":
                    flat_cols[ohlc_lower] = col_tuple
        if flat_cols:
            rename_map = {v: k for k, v in flat_cols.items()}
            df = df[list(flat_cols.values())].copy()
            df.columns = [rename_map[c] for c in df.columns]

    # If timestamp is the index, reset it
    if "timestamp" not in df.columns and df.index.name in ("DateTime", "datetime", "timestamp", "time"):
        df = df.reset_index()
        if df.columns[0] in ("DateTime", "datetime", "time"):
            df = df.rename(columns={df.columns[0]: "timestamp"})

    # Ensure required columns exist
    for c in ("timestamp", "open", "high", "low", "close"):
        if c not in df.columns:
            logger.warning(f"Missing column '{c}' in response. Available: {list(df.columns)}")
            return None

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df[["timestamp", "open", "high", "low", "close"]]


def main():
    parser = argparse.ArgumentParser(description="Build deep 5M cache for HTF preloading")
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated symbols (default: all from CFD_EPICS_JSON)",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=DEEP_CACHE_BARS,
        help=f"Number of 5M bars per symbol (default: {DEEP_CACHE_BARS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan without making API calls",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even if recent deep cache exists",
    )
    args = parser.parse_args()

    if not CFD_EPIC_MAP:
        logger.error("CFD_EPICS_JSON not set or empty in .env. Cannot proceed.")
        sys.exit(1)

    # Determine symbols to fetch
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        # Validate against CFD_EPIC_MAP
        for s in symbols:
            if s not in CFD_EPIC_MAP:
                logger.error(f"Symbol {s} not found in CFD_EPICS_JSON. Available: {list(CFD_EPIC_MAP.keys())}")
                sys.exit(1)
    else:
        symbols = list(CFD_EPIC_MAP.keys())

    bars = max(50, min(5000, args.bars))

    # ------------------------------------------------------------------
    # Pre-flight: check existing deep caches
    # ------------------------------------------------------------------
    fetch_plan: List[Tuple[str, str, int]] = []  # (symbol, epic, bars)
    for sym in symbols:
        epic = CFD_EPIC_MAP[sym]
        path = _deep_cache_path(sym)
        age = _cache_age_days(path)

        if age is not None and age < DEEP_CACHE_MAX_AGE_DAYS and not args.force:
            logger.info(f"  SKIP {sym}: deep cache exists ({age:.1f} days old, < {DEEP_CACHE_MAX_AGE_DAYS}d). Use --force to re-fetch.")
            continue

        status = "NEW" if age is None else f"STALE ({age:.1f}d)"
        fetch_plan.append((sym, epic, bars))
        logger.info(f"  FETCH {sym}: {bars} bars × MINUTE_5 from {epic} [{status}]")

    if not fetch_plan:
        logger.info("Nothing to fetch — all deep caches are recent.")
        return

    # Show plan summary
    total_bars = sum(b for _, _, b in fetch_plan)
    cost_per_symbol = bars + 500  # bars + safety buffer
    print()
    print("=" * 60)
    print("  DEEP CACHE BUILD PLAN")
    print("=" * 60)
    for sym, epic, b in fetch_plan:
        print(f"  {sym}: {b} bars × MINUTE_5 from {epic}")
    print(f"\n  Estimated allowance cost: ~{total_bars} data points")
    print(f"  Output directory: {CACHE_DIR}")

    if args.dry_run:
        print("\n  --dry-run specified. No API calls will be made.")
        print("=" * 60)
        return

    # ------------------------------------------------------------------
    # Pre-flight: check allowance with a cheap 1-bar call
    # ------------------------------------------------------------------
    logger.info("Connecting to IG for allowance check...")
    try:
        from ig_auth import get_ig_session
        ig, headers, account_id = get_ig_session()
        logger.info(f"IG session OK (account: {account_id})")
    except Exception as e:
        logger.error(f"IG login failed: {e}")
        sys.exit(1)

    first_epic = fetch_plan[0][1]
    try:
        _test = ig.fetch_historical_prices_by_epic_and_num_points(first_epic, "MINUTE_5", 1)
        preflight_allowance = _extract_allowance(_test)
        remaining = preflight_allowance.get("remainingAllowance", 0)
        total_allowance = preflight_allowance.get("totalAllowance", "unknown")
        # Account for the 1-bar test call we just made
        if isinstance(remaining, (int, float)):
            remaining = remaining - 1
    except Exception as e:
        logger.warning(f"Pre-flight allowance check failed: {e}")
        logger.warning("Proceeding without allowance info — will check per-symbol.")
        remaining = "unknown"
        total_allowance = "unknown"

    # Show allowance status
    print()
    if isinstance(remaining, (int, float)):
        can_fetch = max(0, int(remaining // cost_per_symbol))
        print(f"  Current allowance: {remaining} remaining (of {total_allowance})")
        print(f"  Estimated cost: {total_bars} ({len(fetch_plan)} symbols × {bars} bars)")
        if remaining < total_bars:
            print()
            print(f"  WARNING: Insufficient allowance for full refresh.")
            print(f"  Available: {remaining} | Required per symbol: {cost_per_symbol}")
            print(f"  Can fetch: {can_fetch} symbol(s)")
            if not args.symbols:
                avail_syms = ",".join(s for s, _, _ in fetch_plan[:can_fetch])
                if avail_syms:
                    print(f"  Tip: Use --symbols {avail_syms} to fetch only what you need")
        else:
            print(f"  Allowance OK — sufficient for all {len(fetch_plan)} symbols.")
    else:
        print(f"  Current allowance: unknown (pre-flight check failed)")
        print(f"  Estimated cost: {total_bars} ({len(fetch_plan)} symbols × {bars} bars)")

    print("=" * 60)

    if isinstance(remaining, (int, float)) and remaining < cost_per_symbol:
        logger.warning("Not enough allowance to fetch even 1 symbol. Aborting.")
        return

    try:
        confirm = input("\n  Continue? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        logger.info("Aborted.")
        return

    if confirm != "y":
        logger.info("Aborted by user.")
        return

    # ------------------------------------------------------------------
    # Fetch loop
    # ------------------------------------------------------------------
    os.makedirs(CACHE_DIR, exist_ok=True)

    results: List[Dict[str, Any]] = []
    first_allowance: Optional[Dict[str, Any]] = None
    last_allowance: Optional[Dict[str, Any]] = None
    allowance_threshold = bars + 500  # need enough for next fetch + safety buffer

    for i, (sym, epic, num_bars) in enumerate(fetch_plan):
        # Pre-fetch allowance check: skip symbol if insufficient
        if isinstance(remaining, (int, float)) and remaining < allowance_threshold:
            logger.warning(
                f"[{i + 1}/{len(fetch_plan)}] SKIP {sym}: insufficient allowance "
                f"({remaining} remaining, need {allowance_threshold}). "
                f"Use --symbols to fetch fewer symbols."
            )
            results.append({"symbol": sym, "bars": 0, "error": "allowance_insufficient", "remaining": remaining})
            continue

        logger.info(f"[{i + 1}/{len(fetch_plan)}] Fetching {sym}: {num_bars} × MINUTE_5 from {epic} ...")

        try:
            response = ig.fetch_historical_prices_by_epic_and_num_points(
                epic, "MINUTE_5", int(num_bars)
            )

            # Extract allowance and update running tracker
            allowance = _extract_allowance(response)
            last_allowance = allowance
            if first_allowance is None:
                first_allowance = allowance
            remaining = allowance.get("remainingAllowance", "unknown")

            # Post-fetch: check if allowance is critically low
            if isinstance(remaining, (int, float)) and remaining < allowance_threshold:
                logger.warning(
                    f"[{sym}] Allowance low after fetch ({remaining} remaining, "
                    f"need {allowance_threshold} for next). Remaining symbols will be skipped."
                )

            # Normalize to DataFrame
            df = _normalize_prices_df(response)
            if df is None or len(df) == 0:
                logger.warning(f"[{sym}] No data returned from IG API")
                results.append({"symbol": sym, "bars": 0, "error": "empty_response", "remaining": remaining})
                continue

            # Write to deep cache
            path = _deep_cache_path(sym)
            df.to_csv(path, index=False)
            bar_count = len(df)

            # Compute date range
            first_ts = str(df.iloc[0]["timestamp"])[:10]
            last_ts = str(df.iloc[-1]["timestamp"])[:10]

            logger.info(
                f"[DEEP-CACHE] {sym}: {bar_count} bars written → {path} "
                f"({first_ts} → {last_ts}) [allowance remaining: {remaining}]"
            )
            results.append({
                "symbol": sym,
                "bars": bar_count,
                "first_ts": first_ts,
                "last_ts": last_ts,
                "remaining": remaining,
                "path": path,
            })

        except Exception as e:
            err_str = str(e).lower()
            if "exceeded-account-historical-data-allowance" in err_str or "historical-data-allowance" in err_str:
                logger.error(
                    f"[{sym}] IG historical data allowance EXCEEDED. "
                    f"Stopping immediately. Already written symbols are safe."
                )
                results.append({"symbol": sym, "bars": 0, "error": "allowance_exceeded"})
                break
            else:
                logger.warning(f"[{sym}] Fetch failed: {type(e).__name__}: {e} — continuing with next symbol")
                results.append({"symbol": sym, "bars": 0, "error": str(e)})
                continue

        # Rate limiting between symbols
        if i < len(fetch_plan) - 1:
            logger.info(f"  Sleeping {INTER_SYMBOL_SLEEP_S}s before next symbol...")
            time.sleep(INTER_SYMBOL_SLEEP_S)

    # ------------------------------------------------------------------
    # Post-flight summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    success_count = sum(1 for r in results if r.get("bars", 0) > 0)
    fail_count = sum(1 for r in results if r.get("bars", 0) == 0)
    if success_count > 0 and fail_count > 0:
        print("  DEEP CACHE BUILD — PARTIAL SUCCESS")
    elif success_count > 0:
        print("  DEEP CACHE BUILD COMPLETE")
    else:
        print("  DEEP CACHE BUILD — NO DATA FETCHED")
    print("=" * 60)

    total_fetched = 0
    for r in results:
        sym = r["symbol"]
        bar_count = r.get("bars", 0)
        total_fetched += bar_count
        if bar_count > 0:
            print(f"  ✓ {sym}: {bar_count} bars ({r.get('first_ts', '?')} → {r.get('last_ts', '?')})")
        else:
            print(f"  ✗ {sym}: FAILED — {r.get('error', 'unknown')}")

    if last_allowance:
        final_remaining = last_allowance.get("remainingAllowance", "?")
        final_total = last_allowance.get("totalAllowance", "?")
        print(f"\n  Total bars fetched: {total_fetched}")
        print(f"  Allowance remaining: {final_remaining} / {final_total}")

    if fail_count > 0 and success_count > 0:
        print(f"\n  Note: {success_count} symbol(s) cached successfully.")
        print(f"  The bot will use deep cache for those and fall back to")
        print(f"  standard cache for the remaining {fail_count} symbol(s).")
    print("=" * 60)

    # ------------------------------------------------------------------
    # D1 (DAY) candle fetch — separate file per symbol
    # ------------------------------------------------------------------
    d1_bars = DEEP_CACHE_D1_BARS
    d1_cost_per_symbol = d1_bars + 100  # bars + safety buffer

    # Build D1 fetch plan — skip symbols with recent D1 cache unless --force
    d1_fetch_plan: List[Tuple[str, str, int]] = []
    for sym in symbols:
        epic = CFD_EPIC_MAP[sym]
        d1_path = _d1_cache_path(sym)
        age = _cache_age_days(d1_path)
        if age is not None and age < DEEP_CACHE_MAX_AGE_DAYS and not args.force:
            logger.info(f"  SKIP D1 {sym}: d1 cache exists ({age:.1f}d old). Use --force to re-fetch.")
            continue
        d1_fetch_plan.append((sym, epic, d1_bars))

    if d1_fetch_plan:
        print()
        print("=" * 60)
        print("  D1 (DAY) CANDLE FETCH")
        print("=" * 60)
        for sym, epic, b in d1_fetch_plan:
            print(f"  {sym}: {b} bars × DAY from {epic}")

        d1_total_bars = sum(b for _, _, b in d1_fetch_plan)
        print(f"\n  Estimated allowance cost: ~{d1_total_bars} data points")

        if isinstance(remaining, (int, float)) and remaining < d1_cost_per_symbol:
            print(f"  WARNING: Insufficient allowance ({remaining} remaining). Skipping D1 fetch.")
            print("=" * 60)
        else:
            try:
                d1_confirm = input("\n  Fetch D1 candles? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                d1_confirm = "n"

            if d1_confirm == "y":
                d1_results: List[Dict[str, Any]] = []
                for i, (sym, epic, num_bars) in enumerate(d1_fetch_plan):
                    # Allowance gate
                    if isinstance(remaining, (int, float)) and remaining < d1_cost_per_symbol:
                        logger.warning(
                            f"[D1 {i + 1}/{len(d1_fetch_plan)}] SKIP {sym}: insufficient allowance "
                            f"({remaining} remaining, need {d1_cost_per_symbol})"
                        )
                        d1_results.append({"symbol": sym, "bars": 0, "error": "allowance_insufficient"})
                        continue

                    logger.info(f"[D1 {i + 1}/{len(d1_fetch_plan)}] Fetching {sym}: {num_bars} × DAY from {epic} ...")

                    try:
                        response = ig.fetch_historical_prices_by_epic_and_num_points(
                            epic, "DAY", int(num_bars)
                        )
                        allowance = _extract_allowance(response)
                        last_allowance = allowance
                        remaining = allowance.get("remainingAllowance", "unknown")

                        df = _normalize_prices_df(response)
                        if df is None or len(df) == 0:
                            logger.warning(f"[D1 {sym}] No data returned from IG API")
                            d1_results.append({"symbol": sym, "bars": 0, "error": "empty_response"})
                            continue

                        path = _d1_cache_path(sym)
                        df.to_csv(path, index=False)
                        bar_count = len(df)

                        first_ts = str(df.iloc[0]["timestamp"])[:10]
                        last_ts = str(df.iloc[-1]["timestamp"])[:10]

                        logger.info(
                            f"[D1-CACHE] {sym}: {bar_count} bars written → {path} "
                            f"({first_ts} → {last_ts}) [allowance remaining: {remaining}]"
                        )
                        d1_results.append({
                            "symbol": sym, "bars": bar_count,
                            "first_ts": first_ts, "last_ts": last_ts,
                            "remaining": remaining, "path": path,
                        })

                    except Exception as e:
                        err_str = str(e).lower()
                        if "historical-data-allowance" in err_str:
                            logger.error(f"[D1 {sym}] Allowance EXCEEDED. Stopping D1 fetch.")
                            d1_results.append({"symbol": sym, "bars": 0, "error": "allowance_exceeded"})
                            break
                        else:
                            logger.warning(f"[D1 {sym}] Fetch failed: {type(e).__name__}: {e}")
                            d1_results.append({"symbol": sym, "bars": 0, "error": str(e)})
                            continue

                    if i < len(d1_fetch_plan) - 1:
                        time.sleep(INTER_SYMBOL_SLEEP_S)

                # D1 summary
                print()
                print("=" * 60)
                print("  D1 CACHE SUMMARY")
                print("=" * 60)
                for r in d1_results:
                    sym = r["symbol"]
                    if r.get("bars", 0) > 0:
                        print(f"  ✓ {sym}: {r['bars']} D1 bars ({r.get('first_ts','?')} → {r.get('last_ts','?')})")
                    else:
                        print(f"  ✗ {sym}: FAILED — {r.get('error', 'unknown')}")
                if last_allowance:
                    print(f"\n  Allowance remaining: {last_allowance.get('remainingAllowance', '?')} / {last_allowance.get('totalAllowance', '?')}")
                print("=" * 60)
            else:
                logger.info("D1 fetch skipped by user.")


if __name__ == "__main__":
    main()
