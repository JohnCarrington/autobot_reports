"""Verify STEP 1 telemetry classifier — zero behaviour change + 14-day
classification sanity check. Run:  python3 _verify_news_tier_step1.py"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import news_calendar
import news_strategy
import news_tier_classifier as ntc


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ------------------------------------------------------------------
# 1. Zero behaviour-change spot check
# ------------------------------------------------------------------
section("1. Zero behaviour-change spot check")

# Stub the calendar with a fixed list — an NFP + Unemployment Rate + non-USD
# event — call _arming_event_for and confirm returned dict is unchanged from
# the pre-Step1 shape (event_name/currency/release_epoch, no tier field).

fake_events = [
    {"time": "13:30", "currency": "USD", "event_name": "Non Farm Payrolls",
     "impact": "High", "forecast": "180K", "previous": "175K",
     "date_utc": datetime.utcnow().strftime("%Y-%m-%d")},
    {"time": "13:30", "currency": "USD", "event_name": "Unemployment Rate",
     "impact": "High", "forecast": "4.1", "previous": "4.1",
     "date_utc": datetime.utcnow().strftime("%Y-%m-%d")},
    {"time": "13:30", "currency": "JPY", "event_name": "Fed Chair Warsh Speech",
     "impact": "High", "date_utc": datetime.utcnow().strftime("%Y-%m-%d")},
]


_orig = news_calendar.get_todays_events
news_calendar.get_todays_events = lambda: fake_events
try:
    # Force ts so 13:30 UTC is now (±5 min window)
    ts = datetime.utcnow().replace(hour=13, minute=30, second=0, microsecond=0).timestamp()
    got = news_strategy._arming_event_for(ts, "GBPUSD")
    assert got is not None
    assert set(got.keys()) == {"event_name", "currency", "release_epoch"}, (
        f"return shape changed! got keys: {sorted(got.keys())}"
    )
    assert got["event_name"] == "Non Farm Payrolls"  # first-match preserved
    print("PASS: _arming_event_for returns unchanged shape and first-match value:")
    print(f"    {got}")
finally:
    news_calendar.get_todays_events = _orig


# ------------------------------------------------------------------
# 2. Kill-switch honoured
# ------------------------------------------------------------------
section("2. Kill-switch (NEWS_TIER_CLASSIFIER_LOG_ENABLED=0)")

# Flip the module-level flag and confirm classify_and_log short-circuits.
_prev = ntc.NEWS_TIER_CLASSIFIER_LOG_ENABLED
ntc.NEWS_TIER_CLASSIFIER_LOG_ENABLED = False
try:
    log_path = Path(ntc.NEWS_TIER_CLASSIFICATION_LOG_PATH)
    before = log_path.stat().st_size if log_path.exists() else 0
    ntc.classify_and_log(
        event={"event_name": "Kill-Switch Test Event", "currency": "USD",
               "time": "12:00", "date_utc": "2099-01-01"},
        symbol="GBPUSD",
        current_behaviour="test",
        context=None,
    )
    after = log_path.stat().st_size if log_path.exists() else 0
    if before == after:
        print("PASS: kill-switch prevents log write (no size change)")
    else:
        print(f"FAIL: log grew {after - before} bytes with kill-switch off")
finally:
    ntc.NEWS_TIER_CLASSIFIER_LOG_ENABLED = _prev


# ------------------------------------------------------------------
# 3. Sanity classifications on canonical event names
# ------------------------------------------------------------------
section("3. Sanity classifications on canonical event names")

canonical = [
    # (event_name, currency, expected_tier)
    ("Non Farm Payrolls", "USD", "BIG"),
    ("NFP", "USD", "BIG"),
    ("Nonfarm Payrolls", "USD", "BIG"),
    ("Non-Farm Payrolls", "USD", "BIG"),
    ("US CPI", "USD", "BIG"),
    ("Inflation Rate YoY", "USD", "BIG"),
    ("Core CPI", "USD", "BIG"),
    ("Core Inflation Rate MoM", "GBP", "BIG"),
    ("Fed Interest Rate Decision", "USD", "BIG"),
    ("Federal Funds Rate", "USD", "BIG"),
    ("BoE Interest Rate Decision", "GBP", "BIG"),
    ("Bank Rate", "GBP", "BIG"),
    ("ECB Press Conference", "EUR", "BIG"),
    ("Deposit Facility Rate", "EUR", "BIG"),
    ("Main Refinancing Rate", "EUR", "BIG"),
    ("GDP Advance", "USD", "BIG"),
    ("GDP Prel", "GBP", "BIG"),
    ("FOMC Minutes", "USD", "BIG"),

    ("ISM Manufacturing PMI", "USD", "MIDDLE"),
    ("ISM Services PMI", "USD", "MIDDLE"),
    ("S&P Global Manufacturing PMI Flash", "USD", "MIDDLE"),
    ("Retail Sales MoM", "USD", "MIDDLE"),
    ("Core Retail Sales", "USD", "MIDDLE"),
    ("PPI MoM", "USD", "MIDDLE"),
    ("Core PPI", "USD", "MIDDLE"),
    ("Initial Jobless Claims", "USD", "MIDDLE"),
    ("Continuing Claims", "USD", "MIDDLE"),
    ("ADP Employment Change", "USD", "MIDDLE"),
    ("JOLTs Job Openings", "USD", "MIDDLE"),
    ("Consumer Confidence", "USD", "MIDDLE"),
    ("Michigan Consumer Sentiment Prel", "USD", "MIDDLE"),
    ("Durable Goods Orders", "USD", "MIDDLE"),
    ("Core PCE Price Index MoM", "USD", "MIDDLE"),
    ("Industrial Production", "USD", "MIDDLE"),

    ("Unemployment Rate", "USD", "SMALL"),           # standalone → SMALL
    ("Fed Chair Warsh Speech", "USD", "SMALL"),       # unattached → SMALL
    ("Trade Balance", "USD", "SMALL"),
    ("Ifo Business Climate", "EUR", "SMALL"),
    ("GfK Consumer Confidence", "GBP", "SMALL"),
    ("Existing Home Sales", "USD", "SMALL"),
    ("Building Permits Prel", "USD", "SMALL"),
    ("ZEW Economic Sentiment Index", "EUR", "SMALL"),
    ("Balance of Trade", "GBP", "SMALL"),
]

fails = []
print(f"{'event_name':45s} {'expected':7s} {'got':7s} {'matched_rule':40s}")
print("-" * 100)
for name, ccy, exp in canonical:
    r = ntc.classify_news_tier({"event_name": name, "currency": ccy})
    ok = r["tier"] == exp
    marker = "OK " if ok else "!! "
    print(f"{marker}{name:42s} {exp:7s} {r['tier']:7s} {r['matched_rule']}")
    if not ok:
        fails.append((name, exp, r["tier"], r["matched_rule"]))

if fails:
    print(f"\nFAIL: {len(fails)} mis-classifications")
else:
    print("\nPASS: all canonical events classified as expected")


# ------------------------------------------------------------------
# 4. Context-aware rules (unemployment-with-NFP, fed-chair-with-rate-decision)
# ------------------------------------------------------------------
section("4. Context-aware rules")

r_alone = ntc.classify_news_tier({"event_name": "Unemployment Rate", "currency": "USD"})
r_with_nfp = ntc.classify_news_tier(
    {"event_name": "Unemployment Rate", "currency": "USD"},
    context={"same_day_events": ["Non Farm Payrolls", "Unemployment Rate"]},
)
print(f"Unemployment Rate alone         : tier={r_alone['tier']}  rule={r_alone['matched_rule']}")
print(f"Unemployment Rate + NFP context : tier={r_with_nfp['tier']}  rule={r_with_nfp['matched_rule']}")

r_chair_alone = ntc.classify_news_tier(
    {"event_name": "Fed Chair Powell Speech", "currency": "USD"}
)
r_chair_at_rate = ntc.classify_news_tier(
    {"event_name": "Fed Chair Powell Speech", "currency": "USD"},
    context={"same_day_events": ["FOMC Statement", "Fed Chair Powell Speech"]},
)
print(f"Fed Chair Speech alone          : tier={r_chair_alone['tier']}  rule={r_chair_alone['matched_rule']}")
print(f"Fed Chair Speech + FOMC context : tier={r_chair_at_rate['tier']}  rule={r_chair_at_rate['matched_rule']}")


# ------------------------------------------------------------------
# 5. Deviation telemetry + would_deviation_change_tier
# ------------------------------------------------------------------
section("5. Deviation labels")

cases = [
    ("BIG in-line", "Non Farm Payrolls", "USD", 175000, 175200),   # tiny miss
    ("BIG big miss", "Non Farm Payrolls", "USD", 100000, 175000),  # -43%
    ("MIDDLE big surprise", "Retail Sales MoM", "USD", 1.2, 0.3),  # +300%
    ("MIDDLE in-line", "Retail Sales MoM", "USD", 0.31, 0.30),
    ("SMALL big surprise", "Trade Balance", "USD", -100, -50),     # +100%
    ("no forecast", "PPI MoM", "USD", 0.3, None),
]
print(f"{'label':30s} {'tier':7s} {'dev':10s} {'label_flag'}")
print("-" * 78)
for label, name, ccy, actual, forecast in cases:
    r = ntc.classify_news_tier({
        "event_name": name, "currency": ccy, "actual": actual, "forecast": forecast
    })
    dev = f"{r['deviation']:.4f}" if r["deviation"] is not None else "n/a"
    print(f"{label:30s} {r['tier']:7s} {dev:10s} {r['would_deviation_change_tier']}")


# ------------------------------------------------------------------
# 6. Live 14-day pass: classify every HIGH event the news feed knows
#    about across the last 14 days that we have observed evidence for.
# ------------------------------------------------------------------
section("6. Classifications on last ~14 days of observed HIGH events")

# We can't replay the calendar feed for past dates (ForexFactory feed is
# this-week-only), but news_strategy_observed.jsonl has real event
# occurrences the bot processed. Extract unique (date, event_name,
# currency) from that log for the last 14 days, then classify.

observed_log = Path("/opt/tradingbot/logs/news_strategy_observed.jsonl")
cutoff = datetime.now(timezone.utc) - timedelta(days=14)

seen: set = set()
rows = []
with observed_log.open("r", encoding="utf-8") as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        name = d.get("event_name")
        if not name:
            continue
        ts_iso = d.get("ts") or d.get("ts_utc")
        try:
            ts_dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")) if ts_iso else None
        except Exception:
            ts_dt = None
        if ts_dt is None or ts_dt < cutoff:
            continue
        # currency is not always in the observed row — infer from symbol if possible.
        key = (ts_dt.strftime("%Y-%m-%d"), name)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"date": key[0], "event_name": name})

# Also merge in today's live calendar so a fresh NFP that hasn't fired
# yet is still visible.
try:
    for ev in news_calendar.get_todays_events() or []:
        if str(ev.get("impact") or "").lower() != "high":
            continue
        today_key = (datetime.utcnow().strftime("%Y-%m-%d"), ev["event_name"])
        if today_key in seen:
            continue
        seen.add(today_key)
        rows.append({"date": today_key[0], "event_name": ev["event_name"], "currency": ev.get("currency")})
except Exception as exc:
    print(f"(live calendar unavailable: {exc})")

# Build a per-day context map so unemployment-with-NFP / fed-chair-at-rate
# rules can fire.
by_day: dict = {}
for r in rows:
    by_day.setdefault(r["date"], []).append(r["event_name"])

rows.sort(key=lambda r: (r["date"], r["event_name"]))
print(f"{'date':11s} {'event_name':46s} {'tier':7s} {'matched_rule':35s} {'would_blackout':14s} {'ext_elig'}")
print("-" * 130)
count_by_tier = {"BIG": 0, "MIDDLE": 0, "SMALL": 0}
for r in rows:
    ctx = {"same_day_events": by_day.get(r["date"], [])}
    cls = ntc.classify_news_tier(r, ctx)
    count_by_tier[cls["tier"]] += 1
    unr = cls["under_new_rules"]
    print(
        f"{r['date']:11s} {r['event_name'][:44]:46s} "
        f"{cls['tier']:7s} {cls['matched_rule']:35s} "
        f"{str(unr['would_blackout']):14s} {unr['would_be_extended_eligible']}"
    )

print(f"\nTotal HIGH events classified: {sum(count_by_tier.values())}")
print(f"  BIG   : {count_by_tier['BIG']}")
print(f"  MIDDLE: {count_by_tier['MIDDLE']}")
print(f"  SMALL : {count_by_tier['SMALL']}")
