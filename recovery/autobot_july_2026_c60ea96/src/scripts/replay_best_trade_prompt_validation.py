#!/usr/bin/env python3
"""
One-shot replay validator for the best_trade prompt change.

For each (date, session) pair in CASES, builds a data_package from historical
candles, injects d1_direction_detail and news fields from the saved OLD
briefing JSON for fidelity, calls the live Anthropic API with the CURRENT
(new) production prompt via _build_user_message, and compares the NEW
best_trade.mode against the OLD one.

Output:
  - per-case JSON saved to data/briefings_replay_new_prompt/
  - tabular comparison report printed to stdout + saved to
    docs/best_trade_prompt_validation_2026-05-12.md

Read-only with respect to git (does not commit). Costs ~$0.18 per call.
"""
import json, os, sys, time, logging, requests
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/opt/tradingbot")
os.chdir("/opt/tradingbot")
from dotenv import load_dotenv
load_dotenv("/opt/tradingbot/.env")

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("replay_prompt_val")

from morning_briefing import (
    SYSTEM_PROMPT, ANTHROPIC_URL, ANTHROPIC_MODEL, BRIEFING_MAX_TOKENS,
    _h1_momentum_summary, _ema_alignment_summary,
    _emas_from_closes, _macd_hist_from_closes, _POINTS_PER_PIP,
    _derive_session_bias_from_h1, _build_user_message,
)
from indicators import add_indicators, IndicatorsConfig

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LOGS = Path("/opt/tradingbot/logs")
OUT = Path("/opt/tradingbot/data/briefings_replay_new_prompt")
OUT.mkdir(parents=True, exist_ok=True)
REPORT = Path("/opt/tradingbot/docs/best_trade_prompt_validation_2026-05-12.md")

# Validation set: 7 calls
# 1 today (target case), 5 historical (mix of UNCOND/COND), 1 smoke
# Each tuple: (date, session, old_briefing_filename_stem)
CASES = [
    ("2026-05-12", "London", "briefing_GBPUSD_2026-05-12_London"),
    ("2026-05-11", "London", "briefing_GBPUSD_2026-05-11_London"),
    ("2026-05-11", "NY",     "briefing_GBPUSD_2026-05-11_NY"),
    ("2026-05-08", "London", "briefing_GBPUSD_2026-05-08_London"),
    ("2026-05-07", "London", "briefing_GBPUSD_2026-05-07_London"),
    ("2026-05-05", "London", "briefing_GBPUSD_2026-05-05_London"),
    ("2026-05-04", "London", "briefing_GBPUSD_2026-05-04_London"),
]
PAIR = "GBPUSD"
SESSIONS_UTC = {
    "London":      {"gmt": (6, 30), "bst": (5, 30)},
    "Mid-session": {"gmt": (10, 45), "bst": (9, 45)},
    "NY":          {"gmt": (13, 0),  "bst": (12, 0)},
}
IND_CFG = IndicatorsConfig(
    ema_period=50, bb_period=20, bb_std=2.0,
    macd_fast=35, macd_slow=45, macd_signal=30, aroon_period=14,
)


def _is_bst(date_str: str) -> bool:
    m, d = int(date_str.split("-")[1]), int(date_str.split("-")[2])
    return m >= 4 or (m == 3 and d >= 29)


def load_candles(pair: str, date: str) -> pd.DataFrame:
    csv_p = Path(f"data/candles/{pair}/{date}.csv")
    if csv_p.exists():
        df = pd.read_csv(csv_p, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        return df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return pd.DataFrame()


def aggregate_h1(df_5m, before_ts):
    df = df_5m[df_5m["timestamp"] < before_ts].copy()
    if len(df) < 12:
        return []
    df["hour"] = df["timestamp"].dt.floor("h")
    g = df.groupby("hour").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        count=("close", "count"),
    ).reset_index()
    g = g[g["count"] >= 10]
    out = []
    for _, r in g.iterrows():
        out.append({
            "time": str(r["hour"]),
            "open": round(float(r["open"]), 5),
            "high": round(float(r["high"]), 5),
            "low": round(float(r["low"]), 5),
            "close": round(float(r["close"]), 5),
        })
    return out[-20:]


def build_pkg(pair, date, session, df_all, briefing_ts, old_briefing):
    sym = pair.upper()
    ppp = _POINTS_PER_PIP.get(sym, 1.0)
    pre = df_all[df_all["timestamp"] <= briefing_ts]
    if len(pre) < 20:
        return None
    current_price = round(float(pre.iloc[-1]["close"]), 5)
    try:
        pre_ind = add_indicators(pre[["timestamp", "open", "high", "low", "close"]].copy(), IND_CFG)
    except Exception:
        pre_ind = pre
    ema_5m = {}
    for p in (8, 13, 21, 50, 200):
        col = f"EMA_{p}"
        if col in pre_ind.columns and pd.notna(pre_ind[col].iloc[-1]):
            ema_5m[str(p)] = round(float(pre_ind[col].iloc[-1]), 5)
    h1_candles = aggregate_h1(df_all, briefing_ts)
    h1_closes = [float(c["close"]) for c in h1_candles]
    ema_h1 = _emas_from_closes(h1_closes)
    macd_h1_hist = _macd_hist_from_closes(h1_closes)
    bb_upper = bb_lower = None
    if len(h1_closes) >= 20:
        w = h1_closes[-20:]; sma = sum(w) / 20
        std = (sum((x - sma) ** 2 for x in w) / 20) ** 0.5
        bb_upper = round(sma + 2 * std, 5); bb_lower = round(sma - 2 * std, 5)
    ema200 = ema_h1.get("200"); ema50 = ema_h1.get("50")
    pv200 = round((current_price - float(ema200)) / ppp, 1) if ema200 else None
    pv50 = round((current_price - float(ema50)) / ppp, 1) if ema50 else None
    et = "NEUTRAL"
    if ema50 and ema200:
        diff = (float(ema50) - float(ema200)) / ppp
        if diff > 5: et = "BULLISH"
        elif diff < -5: et = "BEARISH"

    # Pull from saved OLD briefing for fidelity
    d1_detail = (old_briefing or {}).get("d1_direction_detail")
    news_events = (old_briefing or {}).get("news_events") or []
    news_context = (old_briefing or {}).get("news_context") or {}

    return {
        "symbol": sym,
        "current_price": current_price,
        "session": session,
        "briefing_date": date,
        "briefing_time_utc": briefing_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "h1_candles": h1_candles,
        "ema_5m": ema_5m,
        "ema_h1": ema_h1,
        "h1_ema_values": {k: v for k, v in ema_h1.items() if k in ("8", "13", "21", "50")},
        "macd_h1_hist": macd_h1_hist,
        "h1_momentum_summary": _h1_momentum_summary(h1_candles),
        "ema_alignment": _ema_alignment_summary(current_price, ema_h1),
        "bb_upper": bb_upper, "bb_lower": bb_lower,
        "price_vs_h1_ema200_pips": pv200,
        "price_vs_h1_ema50_pips": pv50,
        "h1_ema_trend": et,
        "prev_session_bias": None,
        "prev_session_actual_direction": None,
        "prev_session_pip_move": None,
        "usd_proxy_bias": None, "usd_proxy_pips": None,
        "news_events": news_events,
        "news_context": news_context,
        "d1_direction_detail": d1_detail,
        "recent_signals": [],
        "recent_accuracy": [],
        "accuracy_last_5": None,
    }


def call_api(sym, session, pkg):
    user_msg = _build_user_message(sym, session, pkg)
    for attempt in range(2):
        try:
            resp = requests.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": BRIEFING_MAX_TOKENS,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_msg}],
                },
                timeout=180,
            )
            resp.raise_for_status()
            body = resp.json()
            text = body["content"][0]["text"].strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()
            return json.loads(text)
        except Exception as e:
            logger.warning("  attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(5)
    return None


def schema_validate_best_trade(bt):
    """Return (ok, errors) for a best_trade object using the same rules
    as morning_briefing._validate_best_trade. Replays the executor's
    structural expectations."""
    errs = []
    if bt is None:
        return True, []
    if not isinstance(bt, dict):
        return False, ["not a dict"]
    mode = bt.get("mode")
    if mode not in ("UNCONDITIONAL", "CONDITIONAL"):
        errs.append(f"mode={mode!r} not in (UNCONDITIONAL, CONDITIONAL)")
    if not isinstance(bt.get("reasoning"), str) or not bt["reasoning"].strip():
        errs.append("reasoning missing/empty")
    if mode == "UNCONDITIONAL":
        if not isinstance(bt.get("plan_rank"), int):
            errs.append("UNCONDITIONAL plan_rank must be int")
        if bt.get("plan_session") not in ("London", "NY"):
            errs.append(f"UNCONDITIONAL plan_session invalid: {bt.get('plan_session')!r}")
        cb = bt.get("conditional_branches")
        if cb not in (None, [], ()):
            errs.append("UNCONDITIONAL must not carry conditional_branches")
    elif mode == "CONDITIONAL":
        if bt.get("plan_rank") is not None or bt.get("plan_session") is not None:
            errs.append("CONDITIONAL plan_rank/plan_session must be null at top level")
        cb = bt.get("conditional_branches")
        if not isinstance(cb, list) or len(cb) < 2:
            errs.append(f"CONDITIONAL needs ≥2 branches (got {type(cb).__name__})")
        else:
            for i, br in enumerate(cb):
                if not isinstance(br, dict):
                    errs.append(f"branch[{i}] not a dict")
                    continue
                if not isinstance(br.get("condition_text"), str) or not br["condition_text"].strip():
                    errs.append(f"branch[{i}] condition_text missing/empty")
                if not isinstance(br.get("plan_rank"), int):
                    errs.append(f"branch[{i}] plan_rank not int")
                if br.get("plan_session") not in ("London", "NY"):
                    errs.append(f"branch[{i}] plan_session invalid")
    return len(errs) == 0, errs


def main():
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    print("=" * 78)
    print("  best_trade prompt validation — replay vs new prompt")
    print(f"  {len(CASES)} cases, model={ANTHROPIC_MODEL}, max_tokens={BRIEFING_MAX_TOKENS}")
    print("=" * 78)

    all_dates = sorted({c[0] for c in CASES})
    all_candles = pd.DataFrame()
    for date in all_dates:
        df = load_candles(PAIR, date)
        if not df.empty:
            all_candles = pd.concat([all_candles, df], ignore_index=True)
    all_candles = all_candles.sort_values("timestamp").reset_index(drop=True)
    logger.info("Loaded %d total 5M candles across %d dates", len(all_candles), len(all_dates))

    results = []
    for date, sess, stem in CASES:
        bst = _is_bst(date)
        t = SESSIONS_UTC[sess]["bst" if bst else "gmt"]
        y, m, d = map(int, date.split("-"))
        ts = datetime(y, m, d, t[0], t[1], tzinfo=timezone.utc)

        old_path = LOGS / f"{stem}.json"
        old_b = json.load(open(old_path)) if old_path.exists() else None
        old_bt = (old_b or {}).get("best_trade") or {}
        old_mode = old_bt.get("mode", "(none)")
        old_summary = (old_b or {}).get("plan_summary", "")

        pkg = build_pkg(PAIR, date, sess, all_candles, ts, old_b)
        if pkg is None:
            logger.warning("SKIP %s %s — insufficient candles", date, sess)
            results.append({"date": date, "session": sess, "old_mode": old_mode,
                            "new_mode": "SKIP", "skipped": "insufficient candles"})
            continue

        logger.info("CALL %s %s (price=%.1f, old_mode=%s)", date, sess, pkg["current_price"], old_mode)
        new_b = call_api(PAIR, sess, pkg)
        if new_b is None:
            results.append({"date": date, "session": sess, "old_mode": old_mode,
                            "new_mode": "FAIL", "skipped": "API failed"})
            continue

        new_bt = new_b.get("best_trade") or {}
        new_mode = new_bt.get("mode", "(none)")
        new_summary = new_b.get("plan_summary", "")
        schema_ok, schema_errs = schema_validate_best_trade(new_bt)
        new_plans = new_b.get("trading_plans") or []

        # Persist the full new briefing
        with open(OUT / f"{stem}_new_prompt.json", "w") as f:
            json.dump(new_b, f, indent=2)

        flip = old_mode != new_mode
        results.append({
            "date": date, "session": sess,
            "old_mode": old_mode, "new_mode": new_mode, "flip": flip,
            "old_summary": old_summary,
            "new_summary": new_summary,
            "new_branches": new_bt.get("conditional_branches"),
            "new_reasoning": new_bt.get("reasoning"),
            "new_plan_count": len(new_plans),
            "new_plan_bias_set": sorted({str(p.get("bias","?")).upper() for p in new_plans}),
            "schema_ok": schema_ok,
            "schema_errs": schema_errs,
            "old_d1_dir": ((old_b or {}).get("d1_direction_detail") or {}).get("direction"),
            "old_d1_score": ((old_b or {}).get("d1_direction_detail") or {}).get("score"),
        })
        time.sleep(2)

    # Print summary
    print()
    print("=" * 78)
    print("  RESULTS")
    print("=" * 78)
    print(f"  {'date':<10} {'sess':<10} {'old':<14} {'new':<14} {'flip?':<6} schema  branches  biases")
    print("  " + "-" * 76)
    for r in results:
        bcount = len(r.get("new_branches") or []) if isinstance(r.get("new_branches"), list) else "-"
        biases = ",".join(r.get("new_plan_bias_set", []))
        sch = "ok" if r.get("schema_ok") else "FAIL"
        flip = ("YES" if r.get("flip") else "no") if r.get("new_mode") not in ("SKIP","FAIL") else "-"
        print(f"  {r['date']:<10} {r['session']:<10} {r['old_mode']:<14} {r['new_mode']:<14} "
              f"{flip:<6} {sch:<6}  {str(bcount):<7}  {biases}")

    # Compute over-correction rate
    actual = [r for r in results if r["new_mode"] not in ("SKIP", "FAIL")]
    uncond_old = [r for r in actual if r["old_mode"] == "UNCONDITIONAL"]
    flips = [r for r in uncond_old if r["new_mode"] == "CONDITIONAL"]
    flip_rate = (len(flips) / len(uncond_old)) if uncond_old else 0.0
    cond_old = [r for r in actual if r["old_mode"] == "CONDITIONAL"]
    cond_stayed = [r for r in cond_old if r["new_mode"] == "CONDITIONAL"]
    schema_fails = [r for r in actual if not r["schema_ok"]]

    print()
    print(f"  UNCONDITIONAL old → CONDITIONAL new : {len(flips)}/{len(uncond_old)} = {flip_rate:.0%}")
    print(f"  CONDITIONAL old → stayed CONDITIONAL: {len(cond_stayed)}/{len(cond_old)}")
    print(f"  schema validation failures          : {len(schema_fails)}/{len(actual)}")

    # Write report
    md = []
    md.append("# best_trade prompt validation (replay, 2026-05-12)")
    md.append("")
    md.append(f"Model: `{ANTHROPIC_MODEL}` · max_tokens: {BRIEFING_MAX_TOKENS} · "
              f"system prompt: unchanged · user prompt: post-edit.")
    md.append("")
    md.append("## Headline metrics")
    md.append("")
    md.append(f"- **UNCONDITIONAL → CONDITIONAL flip rate**: {len(flips)}/{len(uncond_old)} "
              f"= **{flip_rate:.0%}** (target band 30-50%; <20% = under-doing it, "
              f">60% = over-correction)")
    md.append(f"- **CONDITIONAL stability**: {len(cond_stayed)}/{len(cond_old)} stayed CONDITIONAL")
    md.append(f"- **Schema validation**: {len(actual) - len(schema_fails)}/{len(actual)} pass")
    md.append("")
    md.append("## Per-case breakdown")
    md.append("")
    md.append("| Date | Sess | Old mode | New mode | Flip? | Schema | Branches | Plan biases | D1 |")
    md.append("|------|------|----------|----------|-------|--------|----------|-------------|------|")
    for r in results:
        bcount = len(r.get("new_branches") or []) if isinstance(r.get("new_branches"), list) else "-"
        biases = ",".join(r.get("new_plan_bias_set", []))
        sch = "ok" if r.get("schema_ok") else "FAIL"
        flip = ("YES" if r.get("flip") else "no") if r.get("new_mode") not in ("SKIP","FAIL") else "-"
        d1 = f"{r.get('old_d1_dir','?')}/{r.get('old_d1_score','?'):+d}" if r.get("old_d1_score") is not None else "-"
        md.append(f"| {r['date']} | {r['session']} | {r['old_mode']} | {r['new_mode']} "
                  f"| {flip} | {sch} | {bcount} | {biases} | {d1} |")
    md.append("")
    md.append("## Per-case detail")
    md.append("")
    for r in results:
        if r["new_mode"] in ("SKIP", "FAIL"):
            md.append(f"### {r['date']} {r['session']}: {r['new_mode']}")
            md.append(f"({r.get('skipped', '?')})"); md.append(""); continue
        md.append(f"### {r['date']} {r['session']}: {r['old_mode']} → {r['new_mode']}"
                  f"{' (FLIPPED)' if r['flip'] else ''}")
        md.append("")
        md.append(f"**Old plan_summary:**  {r['old_summary']}"); md.append("")
        md.append(f"**New plan_summary:**  {r['new_summary']}"); md.append("")
        md.append(f"**New best_trade.reasoning:**  {r['new_reasoning']}"); md.append("")
        if r["new_mode"] == "CONDITIONAL" and r.get("new_branches"):
            md.append("**New branches:**")
            for i, br in enumerate(r["new_branches"]):
                md.append(f"  {i+1}. `({br.get('plan_session')}, {br.get('plan_rank')})` "
                          f"— {br.get('condition_text')}")
            md.append("")
        if not r["schema_ok"]:
            md.append(f"**SCHEMA ERRORS:** {r['schema_errs']}"); md.append("")
        md.append("---"); md.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(md))
    print(f"\n  Full report: {REPORT}")
    print(f"  Briefings: {OUT}/")


if __name__ == "__main__":
    main()
