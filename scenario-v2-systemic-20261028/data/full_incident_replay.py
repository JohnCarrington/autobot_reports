"""v2 — correct join using scenarios_shadow.generated_at_utc proximity."""
import csv
import json
import pathlib
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

CANDLE_DIRS = [
    pathlib.Path('/opt/tradingbot/data/candles_ext/GBPUSD'),
    pathlib.Path('/opt/tradingbot/data/candles/GBPUSD'),
]

PROPOSALS = '/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/shadow_proposals.jsonl'
QUALITY_FLAGS = '/mnt/volume_lon1_1778405456698/research/live_obs/journal_shadow/scenario_quality_flags.jsonl'


def _read_day(d):
    stem = d.strftime('%Y-%m-%d.csv')
    for base in CANDLE_DIRS:
        p = base / stem
        if p.exists():
            bars = []
            with p.open() as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    try:
                        bars.append((row['timestamp'],
                                      float(row['open']), float(row['high']),
                                      float(row['low']), float(row['close'])))
                    except Exception:
                        continue
            return bars
    return []


BARS = {}
d = datetime(2026, 10, 23, tzinfo=timezone.utc)
while d <= datetime(2026, 10, 28, tzinfo=timezone.utc):
    for ts_str, O, H, L, C in _read_day(d):
        BARS[ts_str[:16]] = (O, H, L, C)
    d += timedelta(days=1)


def classify_outcome(direction, entry, stop, target, sweep_ts_iso, horizon_bars=60):
    if not sweep_ts_iso or entry is None:
        return {'result': 'INSUFFICIENT_DATA', 'reason': 'no entry'}
    try:
        sweep_dt = datetime.fromisoformat(sweep_ts_iso.replace('Z', '+00:00')).astimezone(timezone.utc)
    except Exception:
        return {'result': 'INSUFFICIENT_DATA'}
    minute = (sweep_dt.minute // 5 + 1) * 5
    if minute >= 60:
        start = sweep_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        start = sweep_dt.replace(minute=minute, second=0, microsecond=0)
    bars_to_walk = []
    cur = start
    for _ in range(horizon_bars):
        key = cur.strftime('%Y-%m-%dT%H:%M')
        if key in BARS:
            bars_to_walk.append((cur, BARS[key]))
        cur += timedelta(minutes=5)
    if not bars_to_walk:
        return {'result': 'INSUFFICIENT_DATA'}
    trigger_bar = None
    for ts, (O, H, L, C) in bars_to_walk:
        if direction == 'BUY' and H >= entry:
            trigger_bar = (ts, (O, H, L, C)); break
        if direction == 'SELL' and L <= entry:
            trigger_bar = (ts, (O, H, L, C)); break
    if trigger_bar is None:
        return {'result': 'TRIGGER_NEVER_MET'}
    i0 = bars_to_walk.index(trigger_bar)
    mfe = mae = 0.0
    for ts, (O, H, L, C) in bars_to_walk[i0:]:
        if direction == 'BUY':
            tp = (target is not None) and (H >= target)
            sl = (stop is not None) and (L <= stop)
            mfe = max(mfe, H - entry)
            mae = max(mae, entry - L)
        else:
            tp = (target is not None) and (L <= target)
            sl = (stop is not None) and (H >= stop)
            mfe = max(mfe, entry - L)
            mae = max(mae, H - entry)
        if tp and sl:
            return {'result': 'INTRABAR_AMB', 'trigger_ts': trigger_bar[0].isoformat(),
                    'mfe_pts': round(mfe, 2), 'mae_pts': round(mae, 2),
                    'resolution_ts': ts.isoformat()}
        if tp:
            return {'result': 'TP_HIT', 'trigger_ts': trigger_bar[0].isoformat(),
                    'mfe_pts': round(mfe, 2), 'mae_pts': round(mae, 2),
                    'resolution_ts': ts.isoformat()}
        if sl:
            return {'result': 'SL_HIT', 'trigger_ts': trigger_bar[0].isoformat(),
                    'mfe_pts': round(mfe, 2), 'mae_pts': round(mae, 2),
                    'resolution_ts': ts.isoformat()}
    return {'result': 'UNRESOLVED_IN_HORIZON', 'trigger_ts': trigger_bar[0].isoformat(),
            'mfe_pts': round(mfe, 2), 'mae_pts': round(mae, 2)}


# Load quality flags; index by bar_ts and generated_at (approximate 2-second window)
flags_rows = []
with open(QUALITY_FLAGS) as fh:
    for line in fh:
        flags_rows.append(json.loads(line))


def _flags_for(bar_ts, gen_at):
    """Find the flag row with matching bar_ts and generated_at within 10 s."""
    if not bar_ts or not gen_at:
        return None
    try:
        g = datetime.fromisoformat(gen_at.replace('Z', '+00:00'))
    except Exception:
        return None
    best = None
    best_delta = None
    for f in flags_rows:
        if f.get('bar_ts_utc') != bar_ts:
            continue
        f_g = f.get('generated_at_utc')
        if not f_g:
            continue
        try:
            fg = datetime.fromisoformat(f_g.replace('Z', '+00:00'))
        except Exception:
            continue
        delta = abs((fg - g).total_seconds())
        if delta <= 10 and (best_delta is None or delta < best_delta):
            best = f
            best_delta = delta
    return best


out_rows = []
with open(PROPOSALS) as fh:
    for line in fh:
        p = json.loads(line)
        pub = p.get('publication') or {}
        if pub.get('decision') != 'INVALID':
            continue
        unique_flags = sorted(set(pub.get('flag_codes') or []))
        if 'UNVERIFIED_EVENT_AS_CATALYST' not in unique_flags:
            continue
        entry = (p.get('entry') or {}).get('price')
        stop = (p.get('stop') or {}).get('price')
        tgt = (p.get('target') or {}).get('price')
        direction = p.get('direction')
        gen_ts = p.get('generated_at_utc')
        bar_ts = (p.get('scenario') or {}).get('bar_ts_utc')
        # Find event names from flag journal
        qf = _flags_for(bar_ts, (p.get('scenario') or {}).get('generated_at_utc'))
        event_names = set()
        field_names = set()
        if qf:
            for f in qf.get('flags', []):
                if f.get('code') == 'UNVERIFIED_EVENT_AS_CATALYST':
                    field_names.add(f.get('where'))
                    m = re.search(r"event '([^']+)'", f.get('detail', ''))
                    if m:
                        event_names.add(m.group(1))
        outcome = classify_outcome(direction, entry, stop, tgt, gen_ts)
        out_rows.append({
            'scenario_id': p.get('scenario_id'),
            'revision_idx': p.get('revision_idx'),
            'generated_at_utc': gen_ts,
            'bar_ts_utc': bar_ts,
            'direction': direction,
            'entry': entry,
            'stop': stop,
            'target': tgt,
            'market_data_status': p.get('market_data_status'),
            'quarantined_events': ';'.join(sorted(event_names)),
            'fired_in_fields': ';'.join(sorted(field_names)),
            'result': outcome.get('result'),
            'trigger_ts': outcome.get('trigger_ts'),
            'mfe_pts': outcome.get('mfe_pts'),
            'mae_pts': outcome.get('mae_pts'),
            'resolution_ts': outcome.get('resolution_ts'),
        })

print(f'rows={len(out_rows)}')
with_events = sum(1 for r in out_rows if r['quarantined_events'])
print(f'rows with resolved event names: {with_events}')

# Dump
with open('/tmp/incident_catalogue.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
    w.writeheader()
    for r in out_rows:
        w.writerow(r)

# Analysis
from collections import Counter
ev_counter = Counter()
for r in out_rows:
    for ev in r['quarantined_events'].split(';'):
        if ev:
            ev_counter[ev] += 1
print('\nQuarantined event frequency across the 122 suppressed rows:')
for ev, n in ev_counter.most_common():
    print(f'  {ev:48} {n:>4}')

print('\nOutcome × direction:')
dir_out = defaultdict(Counter)
for r in out_rows:
    dir_out[r['direction']][r['result']] += 1
for d, dist in dir_out.items():
    print(f'  {d:5} {dict(dist)}')
