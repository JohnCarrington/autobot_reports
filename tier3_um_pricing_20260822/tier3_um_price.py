"""Price the UM bracket (12p SL, 100p TP, flat 20:40 UTC) for TREND_V3 fires.
Walk 5m bars forward from entry timestamp (assume entry at the bar containing timestamp_open).
Compare to signal_log managed pnl_pips per fire.
"""
import json, csv, os, datetime as dt
from collections import Counter, defaultdict
from tier3_classify import load_day  # reuse loader

SL_P = 12.0
TP_P = 100.0
FLAT_HHMM = "20:40"     # UTC hard-flat
CANDLES = "/opt/tradingbot/data/candles/GBPUSD"

# load TREND_V3 fires
tv3 = []
with open('/opt/tradingbot/logs/signal_log.jsonl') as f:
    for l in f:
        try: r = json.loads(l)
        except: continue
        if r.get('pair') != 'GBPUSD': continue
        if r.get('strategy') not in ('GBPUSD_TREND_V3_L','GBPUSD_TREND_V3_S'): continue
        tv3.append(r)
tv3.sort(key=lambda r: r['timestamp_open'])
print(f"TREND_V3 fires: {len(tv3)}")

def parse_ts(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s)

def bar_floor(ts):
    # 5-min bucket floor (UTC)
    m = ts.minute - (ts.minute % 5)
    return ts.replace(minute=m, second=0, microsecond=0)

def walk_um(fire, rows):
    """Given a signal_log fire and the date's 5-min rows, return UM bracket outcome.
    Rules:
      - direction ∈ {BUY, SELL}
      - entry price = fire['entry']
      - SL = entry -12 (BUY) or entry +12 (SELL)
      - TP = entry +100 (BUY) or entry -100 (SELL)
      - flat at 20:40 UTC
      - walk starts from the bar AFTER the entry timestamp bar (entry at signal bar close;
        subsequent bars' H/L can hit SL/TP; same-bar entry not used to avoid look-ahead)
    """
    d = fire['timestamp_open'][:10]
    ts_open = parse_ts(fire['timestamp_open'])
    entry = fire['entry']
    is_buy = (fire['direction'] == 'BUY')
    sl = entry - SL_P if is_buy else entry + SL_P
    tp = entry + TP_P if is_buy else entry - TP_P
    # start walking from FIRST bar with ts strictly AFTER the fire's bar close.
    # entry bar close approximated: bar_floor(ts_open)+5min close.
    entry_bar_close = bar_floor(ts_open) + dt.timedelta(minutes=5)
    flat_dt = dt.datetime.combine(dt.date.fromisoformat(d),
                                  dt.time(int(FLAT_HHMM.split(":")[0]),
                                          int(FLAT_HHMM.split(":")[1])),
                                  tzinfo=dt.timezone.utc)
    for ts_s, o, h, l, c in rows:
        try:
            ts = dt.datetime.fromisoformat(ts_s.replace(" ", "T"))
        except Exception:
            continue
        # only walk bars whose OPEN time >= entry_bar_close AND < flat_dt
        if ts < entry_bar_close:
            continue
        if ts >= flat_dt:
            # exit at THIS bar's open at flat, since it's the first bar not before flat
            pnl = (o - entry) if is_buy else (entry - o)
            return dict(outcome="FLAT_2040", exit_ts=ts_s, exit_price=o,
                        um_pnl=pnl, sl=sl, tp=tp)
        # in-bar check for SL/TP hit: prefer conservative (loss first) if H and L both cross
        hit_sl = (l <= sl) if is_buy else (h >= sl)
        hit_tp = (h >= tp) if is_buy else (l <= tp)
        if hit_sl and hit_tp:
            # conservative: SL first (worse-case adverse selection)
            return dict(outcome="SL_TIE", exit_ts=ts_s, exit_price=sl,
                        um_pnl=(-SL_P), sl=sl, tp=tp)
        if hit_sl:
            return dict(outcome="SL", exit_ts=ts_s, exit_price=sl,
                        um_pnl=(-SL_P), sl=sl, tp=tp)
        if hit_tp:
            return dict(outcome="TP", exit_ts=ts_s, exit_price=tp,
                        um_pnl=(+TP_P), sl=sl, tp=tp)
    # no bars left before flat — mark end-of-file flat at last close
    last = rows[-1] if rows else None
    if last:
        pnl = (last[4] - entry) if is_buy else (entry - last[4])
        return dict(outcome="EOD_TAIL", exit_ts=last[0], exit_price=last[4],
                    um_pnl=pnl, sl=sl, tp=tp)
    return dict(outcome="NO_BARS", exit_ts=None, exit_price=None, um_pnl=None, sl=sl, tp=tp)

# load candle rows once per date
row_cache = {}
def get_rows(d):
    if d in row_cache: return row_cache[d]
    p = f"{CANDLES}/{d}.csv"
    if not os.path.exists(p):
        row_cache[d] = []
    else:
        row_cache[d] = load_day(p)
    return row_cache[d]

# my day classifications
days_class = json.load(open("/tmp/tier3_days_class.json"))
tier1 = json.load(open("/tmp/tier3_tier1_dates.json"))
tier1_dates = sorted(d for d in tier1["per_date_labels"] if d <= "2026-08-21")
tv3_dates = sorted({r['timestamp_open'][:10] for r in tv3})

# TV3 window
tv3_start, tv3_end = tv3_dates[0], tv3_dates[-1]
print(f"TV3 window: {tv3_start} .. {tv3_end}")

# Grind-100 dates in TV3 window
grind100 = [d for d,v in days_class.items() if v.get("grind100")]
grind100_in_tv3 = [d for d in grind100 if tv3_start <= d <= tv3_end]
print(f"grind-100 dates: {grind100}")
print(f"  in TV3 window: {grind100_in_tv3}")

# TIER1 dates in TV3 window
tier1_in_tv3 = [d for d in tier1_dates if tv3_start <= d <= tv3_end]
print(f"TIER1 dates in TV3 window ({len(tier1_in_tv3)}): {tier1_in_tv3}")

# assemble subject days = grind100 + tier1 in TV3 window
subject_dates = sorted(set(grind100_in_tv3) | set(tier1_in_tv3))
print(f"subject dates union: {len(subject_dates)}")

# group TV3 fires by date
by_date = defaultdict(list)
for r in tv3:
    by_date[r['timestamp_open'][:10]].append(r)

def label_of(d):
    labs = tier1["per_date_labels"].get(d, [])
    return sorted({x[0] for x in labs}) if labs else []

print("\n[B1] Per-day walk (subject dates):")
print("     date        cls          n_fires  managed_pnl  UM_pnl   delta   labels")
totals = {"managed":0.0, "um":0.0}
per_day = []
for d in subject_dates:
    cls = days_class.get(d, {}).get("cls", "?")
    fires = by_date.get(d, [])
    rows = get_rows(d)
    if not fires:
        # not fired but subject day. record as "no fire"
        labs = label_of(d)
        print(f"     {d}  {cls:11s}  0        ---          ---      ---      {labs}")
        per_day.append(dict(date=d, cls=cls, n_fires=0, managed=0, um=0, delta=0,
                            labels=labs, walks=[]))
        continue
    walks = []
    m_pnl = 0.0
    u_pnl = 0.0
    for fire in fires:
        w = walk_um(fire, rows)
        managed = fire.get('pnl_pips') or 0.0
        um = w.get('um_pnl') if w.get('um_pnl') is not None else 0.0
        walks.append(dict(ts=fire['timestamp_open'], dir=fire['direction'],
                          entry=fire['entry'],
                          managed_pnl=managed, managed_reason=fire.get('close_reason'),
                          um_outcome=w['outcome'], um_pnl=round(um,2),
                          um_exit_ts=w.get('exit_ts')))
        m_pnl += managed
        u_pnl += um
    delta = u_pnl - m_pnl
    totals["managed"] += m_pnl
    totals["um"] += u_pnl
    labs = label_of(d)
    print(f"     {d}  {cls:11s}  {len(fires):<2d}      {m_pnl:+7.1f}      {u_pnl:+7.1f}  {delta:+7.1f}  {labs}")
    per_day.append(dict(date=d, cls=cls, n_fires=len(fires),
                        managed=round(m_pnl,1), um=round(u_pnl,1),
                        delta=round(delta,1), labels=labs, walks=walks))

print(f"\n[B1] SUBJECT totals: managed={totals['managed']:+.1f}p  UM={totals['um']:+.1f}p  "
      f"delta={totals['um']-totals['managed']:+.1f}p")

# Also do TV3 fires on NON-subject days (cost baseline) — everything TV3 dates outside subject_dates
non_subj_dates = [d for d in tv3_dates if d not in subject_dates]
print(f"\n[B2] TV3 dates NOT in subject list (n={len(non_subj_dates)}):")
totals2 = {"managed":0.0, "um":0.0}
per_day2 = []
for d in non_subj_dates:
    cls = days_class.get(d, {}).get("cls", "?")
    fires = by_date.get(d, [])
    rows = get_rows(d)
    m_pnl = 0.0; u_pnl = 0.0
    walks=[]
    for fire in fires:
        w = walk_um(fire, rows)
        m_pnl += fire.get('pnl_pips') or 0.0
        u_pnl += w.get('um_pnl') if w.get('um_pnl') is not None else 0.0
        walks.append(dict(ts=fire['timestamp_open'], dir=fire['direction'],
                          entry=fire['entry'],
                          managed_pnl=fire.get('pnl_pips'), managed_reason=fire.get('close_reason'),
                          um_outcome=w['outcome'], um_pnl=round(w['um_pnl'] or 0,2)))
    delta = u_pnl - m_pnl
    totals2["managed"] += m_pnl; totals2["um"] += u_pnl
    print(f"     {d}  {cls:11s}  {len(fires):<2d}  managed={m_pnl:+7.1f}  UM={u_pnl:+7.1f}  delta={delta:+7.1f}")
    per_day2.append(dict(date=d, cls=cls, n_fires=len(fires),
                         managed=round(m_pnl,1), um=round(u_pnl,1),
                         delta=round(delta,1), walks=walks))
print(f"\n[B2] NON-subject totals: managed={totals2['managed']:+.1f}p  UM={totals2['um']:+.1f}p  "
      f"delta={totals2['um']-totals2['managed']:+.1f}p")

# save
json.dump({"per_day_subject": per_day, "per_day_non_subject": per_day2,
           "totals_subject": totals, "totals_non_subject": totals2,
           "grind100_in_tv3": grind100_in_tv3,
           "tier1_in_tv3": tier1_in_tv3,
           "subject_dates": subject_dates},
          open("/tmp/tier3_um_prices.json","w"), indent=1)
