#!/usr/bin/env python3
"""Forensic audit: TREND_V3 T0 candidates vs NMS demonstrated_direction."""
import json, gzip, glob, csv, statistics, bisect
from datetime import datetime, timezone, timedelta

CORPUS_GLOB = '/opt/tradingbot/logs/candidate_corpus.jsonl*'
ROLLING_CSV = '/opt/tradingbot/cache/GBPUSD_candles_rolling.csv'
FALLBACK_CSV = '/opt/tradingbot/cache/GBPUSD_candles.csv'
NSJ_GLOB = '/opt/tradingbot/logs/normal_state_journal.jsonl*'
OUT = '/tmp/trend_v3_vs_nms_cohort.md'

def _dt(s):
    if s is None: return None
    s = s.replace('Z','+00:00').replace(' ','T')
    return datetime.fromisoformat(s)

# ---- Load corpus rows (TREND_V3 GBPUSD) ----
def load_corpus():
    files = sorted(glob.glob(CORPUS_GLOB))
    rows = []
    per_file = {}
    for f in files:
        if 'PURGE' in f or 'NOTE' in f: continue
        opener = gzip.open if f.endswith('.gz') else open
        c = 0
        with opener(f, 'rt') as fh:
            for ln in fh:
                try: o = json.loads(ln)
                except: continue
                if o.get('strategy_family') != 'TREND_V3': continue
                if o.get('pair') != 'GBPUSD': continue
                c += 1
                rows.append((f, o))
        per_file[f] = c
    rows.sort(key=lambda t: _dt(t[1].get('first_detected_ts')))
    return rows, per_file

# ---- Load candles ----
def load_candles():
    def rd(path):
        out = []
        with open(path) as fh:
            r = csv.reader(fh)
            header = next(r)
            for row in r:
                try:
                    out.append((_dt(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4])))
                except: continue
        return out
    a = rd(ROLLING_CSV)
    b = rd(FALLBACK_CSV)
    # merge; dedupe by timestamp; rolling is authoritative
    seen = {}
    for row in a: seen[row[0]] = row
    for row in b:
        if row[0] not in seen: seen[row[0]] = row
    merged = sorted(seen.values(), key=lambda x: x[0])
    return merged

# ---- Bar lookup ----
def find_bar_idx(candles, ts):
    """Return index of the first bar with bar_ts >= ts. -1 if none."""
    tss = [c[0] for c in candles]
    i = bisect.bisect_left(tss, ts)
    if i >= len(tss): return -1
    return i

def price_move(candles, i0, minutes, side, p0):
    """Compute MFE and MAE within `minutes` from bar i0 (inclusive). Returns (mfe, mae) or None if not enough coverage."""
    t0 = candles[i0][0]
    target_end = t0 + timedelta(minutes=minutes)
    hi = candles[i0][2]; lo = candles[i0][3]
    j = i0
    while j < len(candles) and candles[j][0] <= target_end:
        hi = max(hi, candles[j][2]); lo = min(lo, candles[j][3])
        j += 1
    # Need at least one bar covering, and we need the last-included bar_ts >= t0+minutes-1bar; treat as OK if we advanced at least ceil(minutes/5) bars OR reached end but time spans enough.
    # Simpler: require last bar's timestamp >= target_end - 5m (i.e., we got the full window).
    if j == i0 + 1:
        # Only one bar; if minutes >= 5 we didn't get enough
        return None
    last_ts = candles[j-1][0]
    if (last_ts - t0).total_seconds() + 300 < minutes*60:
        # coverage short
        return None
    if side == 'LONG' or side == 'BUY':
        mfe = hi - p0
        mae = p0 - lo
    else:
        mfe = p0 - lo
        mae = hi - p0
    return (mfe, mae)

# ---- Classification ----
def classify(o):
    """Return cohort label per task spec."""
    rc = o.get('gate_reason_codes') or []
    side = o.get('side')
    cand_dir = 'BUY' if side == 'LONG' else 'SELL'
    opp = 'SELL' if cand_dir == 'BUY' else 'BUY'
    has_agree = False
    has_mismatch_opp = False
    has_ne = False
    other_tok = None
    for r in rc:
        if r == 'normal_routing:NORMAL_TRADABLE_V2_ONLY:TREND_V3':
            has_agree = True
        elif r == f'normal_routing:DIRECTION_MISMATCH:TREND_V3:{opp}':
            has_mismatch_opp = True
        elif r == 'normal_routing:DIRECTION_NOT_ESTABLISHED:TREND_V3':
            has_ne = True
        elif r.startswith('normal_routing:'):
            other_tok = r
    # Priority: DISAGREE_OPPOSITE > NOT_ESTABLISHED > AGREE > OTHER
    if has_mismatch_opp:
        return 'DISAGREE_OPPOSITE'
    if has_ne:
        return 'NOT_ESTABLISHED'
    if has_agree or o.get('gate_allowed'):
        return 'AGREE'
    return 'OTHER'

# ---- Session ----
def session_of(ts):
    h = ts.astimezone(timezone.utc).hour
    if 0 <= h < 6: return 'Asia'
    if 6 <= h < 13: return 'London'
    if 13 <= h < 20: return 'NY'
    return 'AfterHours'

# ---- Load normal_state_journal for trace correlation ----
def load_nsj():
    files = sorted(glob.glob(NSJ_GLOB))
    rows = []
    for f in files:
        if 'PURGE' in f: continue
        opener = gzip.open if f.endswith('.gz') else open
        try:
            with opener(f, 'rt') as fh:
                for ln in fh:
                    try: o = json.loads(ln)
                    except: continue
                    rows.append(o)
        except Exception:
            continue
    return rows

# ---- MAIN ----
def pct(a, b):
    if b == 0: return 'n/a'
    return f'{100.0*a/b:.1f}%'

def qstats(xs):
    if not xs:
        return dict(n=0, med=None, p25=None, p75=None)
    xs2 = sorted(xs)
    def q(p):
        i = int(round(p*(len(xs2)-1)))
        return xs2[i]
    return dict(n=len(xs2), med=q(0.5), p25=q(0.25), p75=q(0.75))

def fmt(v):
    if v is None: return 'n/a'
    return f'{v:.2f}'

def main():
    rows, per_file = load_corpus()
    candles = load_candles()
    nsj = load_nsj()

    total = len(rows)
    # coverage
    ts_all = [_dt(o.get('first_detected_ts')) for _,o in rows]
    dmin = min(ts_all); dmax = max(ts_all)

    # cohort tally
    cohorts = {'AGREE': [], 'DISAGREE_OPPOSITE': [], 'NOT_ESTABLISHED': [], 'OTHER': []}
    by_dtc = {}   # dtc -> cohort -> count
    by_variant = {}
    tok_counts = {}
    for f, o in rows:
        coh = classify(o)
        cohorts[coh].append((f, o))
        dtc = o.get('day_type_canonical') or 'UNKNOWN'
        by_dtc.setdefault(dtc, {}).setdefault(coh, 0)
        by_dtc[dtc][coh] = by_dtc[dtc].get(coh, 0) + 1
        var = o.get('strategy') or o.get('strategy_family')
        by_variant.setdefault(var, {}).setdefault(coh, 0)
        by_variant[var][coh] = by_variant[var].get(coh, 0) + 1
        for r in (o.get('gate_reason_codes') or []):
            if r.startswith('normal_routing:'):
                tok_counts[r] = tok_counts.get(r, 0) + 1

    # ---- Grade each row ----
    graded = {}  # coh -> list of dicts
    skipped = {c: 0 for c in cohorts}
    csv_cover_start = candles[0][0] if candles else None
    for coh, lst in cohorts.items():
        graded[coh] = []
        for f, o in lst:
            ts = _dt(o.get('first_detected_ts'))
            side = o.get('side')
            i = find_bar_idx(candles, ts)
            if i < 0 or (csv_cover_start and ts < csv_cover_start):
                skipped[coh] += 1
                continue
            p0 = candles[i][4]  # close of bar at/after ts
            m15 = price_move(candles, i, 15, side, p0)
            m30 = price_move(candles, i, 30, side, p0)
            m60 = price_move(candles, i, 60, side, p0)
            m120 = price_move(candles, i, 120, side, p0)
            if m15 is None or m30 is None or m60 is None:
                skipped[coh] += 1
                continue
            graded[coh].append(dict(o=o, f=f, ts=ts, side=side, p0=p0,
                                     mfe15=m15[0], mae15=m15[1],
                                     mfe30=m30[0], mae30=m30[1],
                                     mfe60=m60[0], mae60=m60[1],
                                     mfe120=(m120 or (None,None))[0],
                                     mae120=(m120 or (None,None))[1],
                                     bar_ts=candles[i][0]))

    # Speed test for DISAGREE_OPPOSITE
    approvals = [(_dt(o.get('first_detected_ts')), o) for f,o in cohorts['AGREE']]
    approvals.sort(key=lambda x: x[0])
    speed_minutes = []
    speed_pips = []
    for f, o in cohorts['DISAGREE_OPPOSITE']:
        ts = _dt(o.get('first_detected_ts'))
        cp = o.get('candidate_price')
        # Find next AGREE within 2h (regardless of side; the question is when NMS agreed)
        for ats, ao in approvals:
            if ats <= ts: continue
            delta = (ats - ts).total_seconds()/60.0
            if delta > 120: break
            speed_minutes.append(delta)
            if cp is not None and ao.get('candidate_price') is not None:
                speed_pips.append(abs(ao['candidate_price'] - cp))
            break

    # Session breakdowns
    def sess_stats(coh):
        by = {}
        for d in graded[coh]:
            s = session_of(d['ts'])
            by.setdefault(s, []).append(d['mfe60'])
        out = {}
        for s, xs in by.items():
            out[s] = qstats(xs)
        return out

    # Directionally-correct % and opposite-move % per cohort
    def grade_stats(coh):
        gg = graded[coh]
        n = len(gg)
        stats = dict(n_graded=n, n_skipped=skipped[coh])
        if not gg: return stats
        stats['MFE30_med'] = statistics.median([d['mfe30'] for d in gg])
        stats['MAE30_med'] = statistics.median([d['mae30'] for d in gg])
        stats['MFE30_p25'] = sorted([d['mfe30'] for d in gg])[int(0.25*(n-1))]
        stats['MFE30_p75'] = sorted([d['mfe30'] for d in gg])[int(0.75*(n-1))]
        stats['MAE30_p25'] = sorted([d['mae30'] for d in gg])[int(0.25*(n-1))]
        stats['MAE30_p75'] = sorted([d['mae30'] for d in gg])[int(0.75*(n-1))]
        stats['MFE60_med'] = statistics.median([d['mfe60'] for d in gg])
        stats['MAE60_med'] = statistics.median([d['mae60'] for d in gg])
        stats['MFE60_p25'] = sorted([d['mfe60'] for d in gg])[int(0.25*(n-1))]
        stats['MFE60_p75'] = sorted([d['mfe60'] for d in gg])[int(0.75*(n-1))]
        stats['MAE60_p25'] = sorted([d['mae60'] for d in gg])[int(0.25*(n-1))]
        stats['MAE60_p75'] = sorted([d['mae60'] for d in gg])[int(0.75*(n-1))]
        for thr in (10,20,30):
            correct = sum(1 for d in gg if d['mfe60'] >= thr and d['mfe60'] > d['mae60'])
            opp = sum(1 for d in gg if d['mae60'] >= thr)
            stats[f'correct_{thr}'] = correct
            stats[f'correct_{thr}_pct'] = 100.0*correct/n
            stats[f'opp_{thr}'] = opp
            stats[f'opp_{thr}_pct'] = 100.0*opp/n
        return stats

    coh_stats = {c: grade_stats(c) for c in cohorts}

    # ---- Session per-cohort MFE60 stats for AGREE and DISAGREE_OPPOSITE ----
    sess_agree = sess_stats('AGREE')
    sess_disagree = sess_stats('DISAGREE_OPPOSITE')

    # ---- Representative traces ----
    # 5 DISAGREE_OPPOSITE where TREND_V3 was subsequently right (mfe60 >= 10 and > mae60)
    # 5 where NMS saved (mae60 >= 10 and mfe60 < mae60)
    disagree_g = graded['DISAGREE_OPPOSITE']
    right = [d for d in disagree_g if d['mfe60'] >= 10 and d['mfe60'] > d['mae60']]
    saved = [d for d in disagree_g if d['mae60'] >= 10 and d['mfe60'] < d['mae60']]

    # Correlate normal_state_journal by pair + bar_ts window (+/-5min) for these
    def nsj_near(bar_ts):
        # find rows where 'ts' or 'bar_ts' near bar_ts and pair GBPUSD, containing demonstrated_direction transitions
        out = []
        low = bar_ts - timedelta(minutes=5)
        high = bar_ts + timedelta(minutes=60)
        for r in nsj:
            pair = r.get('pair') or r.get('symbol')
            if pair and pair != 'GBPUSD': continue
            t = r.get('bar_ts') or r.get('ts') or r.get('timestamp')
            if not t: continue
            try: dt = _dt(t)
            except: continue
            if dt is None: continue
            if low <= dt <= high:
                dd = r.get('demonstrated_direction') or r.get('primary_direction')
                if dd:
                    out.append((dt, dd, r.get('normal_market_state') or r.get('state')))
        return out[:5]

    # ---- Write report ----
    lines = []
    P = lines.append
    P('# TREND_V3 T0 vs NMS demonstrated_direction — forensic cohort audit')
    P('')
    P(f'Generated: {datetime.now(timezone.utc).isoformat()}')
    P('')
    P('> **SMALL-SAMPLE ADVISORY.** The rolling+fallback candle CSVs cover only 2026-09-23 18:55 UTC onwards, while 40 of the 50 TREND_V3 T0 rows are dated 2026-09-14 → 2026-09-23. Only 7 rows across all cohorts (3 AGREE, 3 DISAGREE_OPPOSITE, 1 NOT_ESTABLISHED) receive a full MFE/MAE grade. All percentages in section 4 are therefore descriptive of a 7-row sample, not statistically significant. Cohort tallies (section 2), token counts (section 3), and speed test (section 6, uses corpus `candidate_price` fields — no candle dependency) are on the full 50-row population.')
    P('')
    P('## 1. Corpus coverage summary')
    P('')
    P(f'- **TREND_V3 GBPUSD T0 candidates found:** {total}')
    P(f'- **Date range (first_detected_ts):** {dmin.isoformat()} → {dmax.isoformat()}')
    P(f'- **Pairs seen:** GBPUSD (filter applied) — corpus files scanned had only GBPUSD TREND_V3 rows on inspection')
    P(f'- **Per-file counts:**')
    for f, c in per_file.items():
        P(f'  - `{f}` → {c} TREND_V3 GBPUSD rows')
    P('')
    P(f'- **Rolling CSV coverage:** {candles[0][0].isoformat()} → {candles[-1][0].isoformat()} (n={len(candles)} 5-min bars)')
    P('')
    P('## 2. Cohort tally')
    P('')
    P('| Cohort | Count |')
    P('|---|---|')
    for c in ('AGREE','DISAGREE_OPPOSITE','NOT_ESTABLISHED','OTHER'):
        P(f'| {c} | {len(cohorts[c])} |')
    P(f'| **TOTAL** | **{sum(len(v) for v in cohorts.values())}** |')
    P('')
    P('**Classification priority applied:** DISAGREE_OPPOSITE > NOT_ESTABLISHED > AGREE (NORMAL_TRADABLE_V2_ONLY or gate_allowed=true) > OTHER.')
    P('')
    P('### 2a. By day_type_canonical')
    P('')
    P('| day_type | AGREE | DISAGREE_OPPOSITE | NOT_ESTABLISHED | OTHER | Total |')
    P('|---|---|---|---|---|---|')
    for dtc, sub in sorted(by_dtc.items()):
        tot = sum(sub.values())
        P(f'| {dtc} | {sub.get("AGREE",0)} | {sub.get("DISAGREE_OPPOSITE",0)} | {sub.get("NOT_ESTABLISHED",0)} | {sub.get("OTHER",0)} | {tot} |')
    P('')
    P('### 2b. By strategy variant')
    P('')
    P('| variant | AGREE | DISAGREE_OPPOSITE | NOT_ESTABLISHED | OTHER | Total |')
    P('|---|---|---|---|---|---|')
    for var, sub in sorted(by_variant.items()):
        tot = sum(sub.values())
        P(f'| {var} | {sub.get("AGREE",0)} | {sub.get("DISAGREE_OPPOSITE",0)} | {sub.get("NOT_ESTABLISHED",0)} | {sub.get("OTHER",0)} | {tot} |')
    P('')
    P('## 3. Top distinct `normal_routing:*` tokens')
    P('')
    P('| Count | Token |')
    P('|---|---|')
    for k, v in sorted(tok_counts.items(), key=lambda x: -x[1])[:10]:
        P(f'| {v} | `{k}` |')
    P('')
    P('**Note on OTHER cohort:** `normal_routing_deferred_active_trend:TREND_DOWN/TREND_UP` fires when NMS already sees an established trend in that direction; some of these carry gate_allowed=True and become AGREE, others False and become OTHER. `NORMAL_STATE_NOT_PERMITTED` / `NORMAL_STATE_UNKNOWN` are non-directional rejections.')
    P('')

    P('## 4. Grading — three cohort tables')
    P('')
    P(f'Ground truth: `{ROLLING_CSV}` merged with `{FALLBACK_CSV}`. `p0` = close of first M5 bar at/after `first_detected_ts`. Coverage starts {candles[0][0].isoformat()}, so all rows before that timestamp are counted under `n_skipped`.')
    P('')
    for coh in ('AGREE','DISAGREE_OPPOSITE','NOT_ESTABLISHED'):
        s = coh_stats[coh]
        P(f'### 4.{"abc"["AGREE DISAGREE_OPPOSITE NOT_ESTABLISHED".split().index(coh)]} {coh}')
        P('')
        P(f'- **n_graded:** {s.get("n_graded",0)}  **n_skipped (no price):** {s.get("n_skipped",0)}')
        if s.get('n_graded',0) == 0:
            P('- No graded rows.')
            P('')
            continue
        P(f'- **MFE_30 (pips)** median={fmt(s["MFE30_med"])}  p25={fmt(s["MFE30_p25"])}  p75={fmt(s["MFE30_p75"])}')
        P(f'- **MAE_30 (pips)** median={fmt(s["MAE30_med"])}  p25={fmt(s["MAE30_p25"])}  p75={fmt(s["MAE30_p75"])}')
        P(f'- **MFE_60 (pips)** median={fmt(s["MFE60_med"])}  p25={fmt(s["MFE60_p25"])}  p75={fmt(s["MFE60_p75"])}')
        P(f'- **MAE_60 (pips)** median={fmt(s["MAE60_med"])}  p25={fmt(s["MAE60_p25"])}  p75={fmt(s["MAE60_p75"])}')
        P('')
        P('| Threshold | Directionally correct within 60m | Opposite move within 60m (NMS-saved) |')
        P('|---|---|---|')
        for thr in (10,20,30):
            P(f'| ≥{thr}p | {s[f"correct_{thr}"]}/{s["n_graded"]} = {s[f"correct_{thr}_pct"]:.1f}% | {s[f"opp_{thr}"]}/{s["n_graded"]} = {s[f"opp_{thr}_pct"]:.1f}% |')
        P('')

    # Also print OTHER stats for completeness (task asked "three tables one per cohort" but we have 4; keep OTHER short)
    s = coh_stats['OTHER']
    P('### 4.d OTHER (bonus, non-primary cohort)')
    P('')
    P(f'- n_graded: {s.get("n_graded",0)}  n_skipped: {s.get("n_skipped",0)}')
    if s.get('n_graded',0) > 0:
        P(f'- MFE_60 median {fmt(s["MFE60_med"])}, MAE_60 median {fmt(s["MAE60_med"])}')
        P(f'- Correct ≥10p: {s["correct_10"]}/{s["n_graded"]} = {s["correct_10_pct"]:.1f}%')
    P('')

    P('## 5. Session breakdown (GBPUSD)')
    P('')
    P('Sessions in UTC: Asia 00–06, London 06–13, NY 13–20. Values are MFE_60 in pips.')
    P('')
    for label, ss in (('AGREE', sess_agree), ('DISAGREE_OPPOSITE', sess_disagree)):
        P(f'### {label}')
        P('')
        if not ss:
            P('- No graded rows in any session.')
            P('')
            continue
        P('| Session | n | MFE_60 median | p25 | p75 |')
        P('|---|---|---|---|---|')
        for s_name in ('Asia','London','NY','AfterHours'):
            if s_name in ss:
                q = ss[s_name]
                P(f'| {s_name} | {q["n"]} | {fmt(q["med"])} | {fmt(q["p25"])} | {fmt(q["p75"])} |')
        P('')

    P('## 6. Speed test — DISAGREE_OPPOSITE → next AGREE within 2h')
    P('')
    n_dis = len(cohorts['DISAGREE_OPPOSITE'])
    n_matched = len(speed_minutes)
    P(f'- DISAGREE_OPPOSITE population: {n_dis}. Matched to next AGREE within 2h: {n_matched}.')
    if speed_minutes:
        sm = sorted(speed_minutes)
        def qp(p, xs=sm):
            i = int(round(p*(len(xs)-1)))
            return xs[i]
        P(f'- **Minutes to NMS agreement:** median={qp(0.5):.1f}  p75={qp(0.75):.1f}  p90={qp(0.9):.1f}')
    if speed_pips:
        sp = sorted(speed_pips)
        def qp2(p, xs=sp):
            i = int(round(p*(len(xs)-1)))
            return xs[i]
        P(f'- **Pips moved between T0 and NMS agreement:** median={qp2(0.5):.2f}  p75={qp2(0.75):.2f}  p90={qp2(0.9):.2f}')
    if not speed_minutes:
        P('- No DISAGREE_OPPOSITE rows matched a subsequent AGREE within 2h.')
    P('')

    P('## 7. Representative traces (DISAGREE_OPPOSITE cohort)')
    P('')
    P('### 7a. Rows where TREND_V3 was subsequently right (MFE_60 ≥ 10p and > MAE_60)')
    P('')
    for d in right[:5]:
        o = d['o']
        nms = o.get('news_trend_snapshot') or {}
        P(f'- **T0 {d["ts"].isoformat()}** side={d["side"]} p0={d["p0"]:.2f} MFE60={d["mfe60"]:.2f}p MAE60={d["mae60"]:.2f}p  '
          f'nms.primary={nms.get("primary_direction")} nms.bounce={nms.get("bounce_direction")} state={nms.get("trend_state") or nms.get("bounce_state")}')
        traces = nsj_near(d['bar_ts'])
        for (ntt, dd, ms) in traces[:3]:
            P(f'    - nsj@{ntt.isoformat()} direction={dd} state={ms}')
    if not right:
        P('- None. (Every DISAGREE_OPPOSITE row that could be graded either failed the 10p directional threshold or MAE ≥ MFE.)')
    P('')
    P('### 7b. Rows where NMS was subsequently right (opposite move ≥ 10p and MAE > MFE)')
    P('')
    for d in saved[:5]:
        o = d['o']
        nms = o.get('news_trend_snapshot') or {}
        P(f'- **T0 {d["ts"].isoformat()}** side={d["side"]} p0={d["p0"]:.2f} MFE60={d["mfe60"]:.2f}p MAE60={d["mae60"]:.2f}p  '
          f'nms.primary={nms.get("primary_direction")} nms.bounce={nms.get("bounce_direction")} state={nms.get("trend_state") or nms.get("bounce_state")}')
        traces = nsj_near(d['bar_ts'])
        for (ntt, dd, ms) in traces[:3]:
            P(f'    - nsj@{ntt.isoformat()} direction={dd} state={ms}')
    if not saved:
        P('- None.')
    P('')
    # Fallback: since both buckets came up empty on the small sample, dump ALL DISAGREE_OPPOSITE graded rows raw
    if not right and not saved and disagree_g:
        P('### 7c. All DISAGREE_OPPOSITE rows graded (fallback since neither bucket populated)')
        P('')
        for d in disagree_g:
            o = d['o']
            nms = o.get('news_trend_snapshot') or {}
            verdict = 'MAE>MFE (NMS-leaning)' if d['mae60'] > d['mfe60'] else 'MFE>MAE (TV3-leaning)'
            P(f'- **T0 {d["ts"].isoformat()}** side={d["side"]} p0={d["p0"]:.2f}  '
              f'MFE30={d["mfe30"]:.2f}p MAE30={d["mae30"]:.2f}p MFE60={d["mfe60"]:.2f}p MAE60={d["mae60"]:.2f}p → {verdict}  '
              f'nms.primary={nms.get("primary_direction")} nms.bounce={nms.get("bounce_direction")}')
        P('')

    P('## 8. Coverage caveats')
    P('')
    P(f'- **Grading window:** rolling+fallback CSVs cover {candles[0][0].isoformat()} → {candles[-1][0].isoformat()}. TREND_V3 rows before {candles[0][0].isoformat()} could not be graded.')
    P(f'- **Skipped rows per cohort:** ' + ', '.join(f'{c}={skipped[c]}' for c in ('AGREE','DISAGREE_OPPOSITE','NOT_ESTABLISHED','OTHER')))
    P(f'- **Pip unit:** 1.0 CSV-price-unit = 1 pip (per task spec).')
    P('')

    with open(OUT, 'w') as fh:
        fh.write('\n'.join(lines))
    print('wrote', OUT)

    # quick console summary
    print('\n---SUMMARY---')
    print('total TREND_V3 GBPUSD rows:', total)
    for c in ('AGREE','DISAGREE_OPPOSITE','NOT_ESTABLISHED','OTHER'):
        s = coh_stats[c]
        print(f'{c}: n={len(cohorts[c])} graded={s.get("n_graded",0)} skipped={s.get("n_skipped",0)}')
    s = coh_stats['DISAGREE_OPPOSITE']
    if s.get('n_graded',0)>0:
        print('DISAGREE_OPPOSITE correct pct: 10p={:.1f}% 20p={:.1f}% 30p={:.1f}%'.format(s['correct_10_pct'], s['correct_20_pct'], s['correct_30_pct']))
        print('DISAGREE_OPPOSITE opposite pct: 10p={:.1f}% 20p={:.1f}% 30p={:.1f}%'.format(s['opp_10_pct'], s['opp_20_pct'], s['opp_30_pct']))

if __name__ == '__main__':
    main()
