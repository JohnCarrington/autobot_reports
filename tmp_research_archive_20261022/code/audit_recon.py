"""Section 0 recon: candle coverage, news coverage, signal_log summary."""
import os, glob, json, csv
from datetime import date, timedelta, datetime

WORK = "/opt/tradingbot"
CAND_DIR = f"{WORK}/data/candles/GBPUSD"
NEWS_DIR = f"{WORK}/cache"
SL_MAIN = f"{WORK}/logs/signal_log.jsonl"
SL_BACK = f"{WORK}/data/signal_log_backfill.jsonl"

# Candle coverage
files = sorted(glob.glob(f"{CAND_DIR}/2026-*.csv"))
dates_have = sorted([os.path.basename(f).replace(".csv","") for f in files])
d0 = date(2026,1,1)
today = date(2026,8,21)
all_range = []
d = d0
while d <= today:
    all_range.append(d.isoformat())
    d += timedelta(days=1)
weekdays_range = [x for x in all_range if datetime.fromisoformat(x).weekday() < 5]
missing_weekday = sorted(set(weekdays_range) - set(dates_have))
extra = sorted(set(dates_have) - set(all_range))

# For each present candle file, get row count and time-range
row_info = {}
for f in files[:5] + files[-5:]:
    with open(f) as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)
        row_info[os.path.basename(f)] = {"rows": len(rows), "first_ts": rows[0][0] if rows else None, "last_ts": rows[-1][0] if rows else None}

# News coverage — merge backfill + live
news_files = sorted(glob.glob(f"{NEWS_DIR}/news_state_finnhub_*.json"))
news_dates = set()
for nf in news_files:
    base = os.path.basename(nf).replace("news_state_finnhub_","").replace(".json","")
    if base.startswith("backfill_"): base = base.replace("backfill_","")
    news_dates.add(base)
news_dates = sorted(news_dates)
news_missing_wd = sorted(set(weekdays_range) - set(news_dates))

# Sample one to sanity check schema
sample_ev_count = None
if news_files:
    with open(news_files[0]) as fh:
        j = json.load(fh)
        sample_ev_count = len(j.get("events", []))

# signal_log: schema + counts + date range + strategies
sl_lines = 0
sl_dates = set()
sl_strats = {}
sl_pairs = {}
sl_first = sl_last = None
with open(SL_MAIN) as fh:
    for line in fh:
        try:
            r = json.loads(line)
        except: continue
        sl_lines += 1
        t = r.get("timestamp_open") or r.get("timestamp") or ""
        if t:
            d = t[:10]
            sl_dates.add(d)
            if sl_first is None or d < sl_first: sl_first = d
            if sl_last is None or d > sl_last: sl_last = d
        s = r.get("strategy","?"); sl_strats[s] = sl_strats.get(s,0)+1
        p = r.get("pair", r.get("epic","?")); sl_pairs[p] = sl_pairs.get(p,0)+1

sl_back_lines = 0
sl_back_dates = set()
with open(SL_BACK) as fh:
    for line in fh:
        try: r = json.loads(line)
        except: continue
        sl_back_lines += 1
        t = r.get("timestamp_open") or r.get("timestamp") or ""
        if t: sl_back_dates.add(t[:10])

print("=== SECTION 0 RECON ===")
print(f"Candle dir: {CAND_DIR}")
print(f"Candle files present: {len(dates_have)} covering {dates_have[0]}..{dates_have[-1]}")
print(f"Weekdays in range 2026-01-01..2026-08-21: {len(weekdays_range)}")
print(f"Missing weekday candles: {len(missing_weekday)} -> {missing_weekday[:20]}{'...' if len(missing_weekday)>20 else ''}")
print(f"Candle sample row_info: {json.dumps(row_info, indent=1)}")
print()
print(f"News cache: {len(news_files)} files across {len(news_dates)} unique dates")
print(f"News date range: {news_dates[0]}..{news_dates[-1]}")
print(f"Weekdays missing news file: {len(news_missing_wd)} -> {news_missing_wd[:20]}{'...' if len(news_missing_wd)>20 else ''}")
print(f"Sample news event count (first file): {sample_ev_count}")
print()
print(f"signal_log main: {sl_lines} rows, dates {sl_first}..{sl_last}, {len(sl_dates)} unique dates")
print(f"signal_log backfill: {sl_back_lines} rows, {len(sl_back_dates)} dates")
print(f"Strategies (top): {sorted(sl_strats.items(), key=lambda x:-x[1])[:15]}")
print(f"Pairs: {sorted(sl_pairs.items(), key=lambda x:-x[1])[:8]}")

os.makedirs("/opt/tradingbot/reports-public/daystruct_20260821", exist_ok=True)
with open("/opt/tradingbot/reports-public/daystruct_20260821/section0_recon.json","w") as fh:
    json.dump({
        "candle_files": len(dates_have),
        "candle_first": dates_have[0], "candle_last": dates_have[-1],
        "candle_dates": dates_have,
        "candle_missing_weekdays": missing_weekday,
        "candle_row_info_sample": row_info,
        "news_files": len(news_files),
        "news_unique_dates": len(news_dates),
        "news_first": news_dates[0], "news_last": news_dates[-1],
        "news_missing_weekdays": news_missing_wd,
        "sl_main_rows": sl_lines, "sl_main_first": sl_first, "sl_main_last": sl_last,
        "sl_main_dates": sorted(sl_dates),
        "sl_backfill_rows": sl_back_lines,
        "sl_backfill_dates": sorted(sl_back_dates),
        "sl_strategies": sl_strats,
        "sl_pairs": sl_pairs,
    }, fh, indent=2)
print("\nCheckpoint -> reports-public/daystruct_20260821/section0_recon.json")
