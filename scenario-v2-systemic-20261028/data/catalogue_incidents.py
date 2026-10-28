"""One-off analysis script: catalogue each scenario where UNVERIFIED fired."""
import json
from collections import defaultdict, Counter

PROPOSALS = '/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/shadow_proposals.jsonl'

by_scen = defaultdict(list)
with open(PROPOSALS) as fh:
    for line in fh:
        p = json.loads(line)
        by_scen[p.get('scenario_id')].append(p)

for sid, rows in sorted(by_scen.items(), key=lambda kv: kv[1][0].get('generated_at_utc','')):
    sample_pub = Counter((r.get('publication') or {}).get('decision','UNVALIDATED') for r in rows)
    ue_fires = sum(1 for r in rows for c in (r.get('publication') or {}).get('flag_codes') or [] if c == 'UNVERIFIED_EVENT_AS_CATALYST')
    if sample_pub.get('INVALID', 0) == 0 or ue_fires == 0:
        continue
    rows.sort(key=lambda r: r.get('revision_idx', 0))
    print(f'=== scenario {sid} ({len(rows)} revisions) ===')
    print(f'    pubs={dict(sample_pub)}  UNVERIFIED_fires={ue_fires}')
    for r in rows:
        pub = r.get('publication') or {}
        dec = pub.get('decision', 'UNVALIDATED')
        if dec != 'INVALID':
            continue
        entry = r.get('entry') or {}
        stop = r.get('stop') or {}
        tgt = r.get('target') or {}
        flags_unique = sorted(set(pub.get('flag_codes') or []))
        md = r.get('market_data_status', '')
        print(f'  rev{r.get("revision_idx"):>2} {r.get("generated_at_utc","")[:19]} '
              f'dir={r.get("direction",""):>4} entry={entry.get("price")} '
              f'stop={stop.get("price")} tgt={tgt.get("price")} '
              f'mktdata={md} flags={flags_unique}')
    print()
