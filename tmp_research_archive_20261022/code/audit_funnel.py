#!/usr/bin/env python3
"""Reconstruct 2026-09-18 funnel from log files."""
import json, collections, os, sys, datetime

TODAY = '2026-09-18'
LOGS = '/opt/tradingbot/logs'

def load_today(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = str(d.get('ts') or d.get('timestamp') or d.get('event_ts_utc') or d.get('emit_ts') or d.get('bar_ts_utc') or '')
            if ts.startswith(TODAY):
                rows.append((ts, d))
    return rows

def hour_hist(rows):
    h = collections.Counter()
    for ts, _ in rows:
        # HH from ISO
        try:
            hh = ts[11:13]
        except Exception:
            hh = '??'
        h[hh] += 1
    return h

print("=== FUNNEL for %s (UTC) ===" % TODAY)

# 1) 5M bar closes from candle_events (may not exist as a file; we saw them in journal)
# Skip — journal already shows normal cadence.

# 2) measurement DETECTOR_EVAL rows — this is the primary evaluation record per-bar
meas = load_today(os.path.join(LOGS, 'phase2b_measurement.jsonl'))
print("\n--- phase2b_measurement.jsonl (today) ---")
print("total DETECTOR_EVAL rows today:", len(meas))
by_src = collections.Counter(r.get('source_module','?') for _, r in meas)
by_pair = collections.Counter(r.get('pair','?') for _, r in meas)
by_family = collections.Counter(r.get('family','?') for _, r in meas)
by_state = collections.Counter(r.get('detector_state','?') for _, r in meas)
by_emit = collections.Counter(('EMITTED' if r.get('emitted') else 'NOT_EMITTED') for _, r in meas)
by_class = collections.Counter(r.get('source_class','?') for _, r in meas)
by_reason = collections.Counter(r.get('non_emission_reason','?') for _, r in meas)
print("by source_module:", dict(by_src))
print("by pair:", dict(by_pair))
print("by family:", dict(by_family))
print("by detector_state:", dict(by_state))
print("emitted?:", dict(by_emit))
print("source_class:", dict(by_class))
print("non_emission_reasons (top):", by_reason.most_common(10))
print("hour hist:", sorted(hour_hist(meas).items()))

# 3) candidate_corpus.jsonl
cc = load_today(os.path.join(LOGS, 'candidate_corpus.jsonl'))
print("\n--- candidate_corpus.jsonl (today) ---")
print("total candidate rows today:", len(cc))
for ts, r in cc:
    print(" - ts=%s epic=%s fam=%s side=%s gate_allowed=%s executed=%s hour_block=%s" % (
        ts, r.get('epic'), r.get('strategy_family') or r.get('strategy'),
        r.get('side'), r.get('gate_allowed'), r.get('executed'),
        [c for c in (r.get('gate_reason_codes') or []) if 'entry_hours' in c]
    ))
    # binding rejection reason
    binding = [c for c in (r.get('gate_reason_codes') or []) if c.startswith('gate:')]
    print("   binding:", binding)

# 4) qm_candidates.jsonl
qc = load_today(os.path.join(LOGS, 'qm_candidates.jsonl'))
print("\n--- qm_candidates.jsonl (today) ---")
print("total rows today:", len(qc))
for ts, r in qc[:20]:
    keys = list(r.keys())[:12]
    print(f" - ts={ts} keys={keys}")
    for k in ('symbol','epic','strategy_family','strategy','decision','disposition','emitted','gate_allowed','executed'):
        if k in r:
            print(f"     {k}={r[k]}")

# 5) qm_candidates_graded (setups & progressions)
qcg = load_today(os.path.join(LOGS, 'qm_candidates_graded.jsonl'))
print("\n--- qm_candidates_graded.jsonl (today) ---")
print("total rows today:", len(qcg))
by_grade = collections.Counter(r.get('grade') or r.get('disposition') or r.get('outcome') or '?' for _, r in qcg)
print("by grade/dispo:", by_grade.most_common())

# 6) entry_instrumentation
ei = load_today(os.path.join(LOGS, 'entry_instrumentation.jsonl'))
print("\n--- entry_instrumentation.jsonl (today) ---")
print("total rows today:", len(ei))
for ts, r in ei:
    print(f" - ts={ts} keys={list(r.keys())[:10]}")

# 7) confirmation_fallback
cf = load_today(os.path.join(LOGS, 'confirmation_fallback.jsonl'))
print("\n--- confirmation_fallback.jsonl (today) ---")
print("total rows today:", len(cf))

# 8) news_trend_entry
nte = load_today(os.path.join(LOGS, 'news_trend_entry.jsonl'))
print("\n--- news_trend_entry.jsonl (today) ---")
print("total rows today:", len(nte))
by_state = collections.Counter(r.get('state') or r.get('trend_state') or '?' for _, r in nte)
print("by state:", by_state.most_common())
