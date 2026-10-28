"""Build MISSED_GBPUSD_OPPORTUNITIES.csv — for every V2 proposal that
had a parseable entry/stop/target, replay the M5 candles after the
decision and report whether the trigger was met, target reached,
stop reached."""
import csv
import json
import pathlib
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PROP = pathlib.Path("/mnt/volume_lon1_1778405456698/research/live_obs/shadow_exec/shadow_proposals.jsonl")
CANDLES_EXT = pathlib.Path("/opt/tradingbot/data/candles_ext/GBPUSD")
CANDLES_MID = pathlib.Path("/opt/tradingbot/data/candles/GBPUSD")

UTC = timezone.utc
UK = ZoneInfo("Europe/London")


def _load_bars():
    bars = {}
    for day in ("2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28"):
        for base in (CANDLES_MID, CANDLES_EXT):
            p = base / f"{day}.csv"
            if p.exists():
                with p.open() as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        try:
                            bars[row["timestamp"][:16]] = (
                                float(row["open"]), float(row["high"]),
                                float(row["low"]), float(row["close"]))
                        except (KeyError, ValueError):
                            continue
                break
    return bars


BARS = _load_bars()


def _simulate(direction, entry, stop, target, from_ts, horizon=60):
    """Walk candles after `from_ts`; return (trigger_met_at, tp_hit_at, sl_hit_at)."""
    if not from_ts or entry is None:
        return (None, None, None)
    try:
        start = datetime.fromisoformat(from_ts.replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return (None, None, None)
    # Round up to next 5-min boundary
    m = (start.minute // 5 + 1) * 5
    if m >= 60:
        cur = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        cur = start.replace(minute=m, second=0, microsecond=0)
    trigger_met = tp_hit = sl_hit = None
    for _ in range(horizon):
        key = cur.strftime("%Y-%m-%dT%H:%M")
        b = BARS.get(key)
        if b:
            O, H, L, C = b
            if trigger_met is None:
                if direction == "BUY" and H >= entry:
                    trigger_met = cur
                elif direction == "SELL" and L <= entry:
                    trigger_met = cur
            if trigger_met is not None:
                if direction == "BUY":
                    if target is not None and H >= target and tp_hit is None:
                        tp_hit = cur
                    if stop is not None and L <= stop and sl_hit is None:
                        sl_hit = cur
                else:
                    if target is not None and L <= target and tp_hit is None:
                        tp_hit = cur
                    if stop is not None and H >= stop and sl_hit is None:
                        sl_hit = cur
                # Earliest of tp/sl stops the walk
                if tp_hit and (sl_hit is None or tp_hit <= sl_hit):
                    break
                if sl_hit and (tp_hit is None or sl_hit <= tp_hit):
                    break
        cur += timedelta(minutes=5)
    return (trigger_met, tp_hit, sl_hit)


out_rows = []
with PROP.open() as fh:
    for line in fh:
        r = json.loads(line)
        if "2026-10-2" not in (r.get("generated_at_utc") or ""):
            continue
        entry = (r.get("entry") or {}).get("price")
        stop = (r.get("stop") or {}).get("price")
        tgt = (r.get("target") or {}).get("price")
        direction = r.get("direction")
        if direction not in ("BUY", "SELL") or entry is None:
            continue
        gen = r.get("generated_at_utc") or ""
        trig, tp_hit, sl_hit = _simulate(direction, entry, stop, tgt, gen)
        gen_uk = ""
        try:
            gen_uk = datetime.fromisoformat(gen.replace("Z", "+00:00")) \
                .astimezone(UK).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
        out_rows.append({
            "generated_at_utc": gen[:19],
            "generated_at_uk": gen_uk,
            "scenario_id": r.get("scenario_id","")[:16],
            "revision_idx": r.get("revision_idx"),
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "target": tgt,
            "recommendation": r.get("recommendation"),
            "readiness": r.get("readiness"),
            "pub_decision": (r.get("publication") or {}).get("decision"),
            "flag_codes": ",".join(sorted(set((r.get("publication") or {}).get("flag_codes") or []))),
            "trigger_met_at": trig.isoformat() if trig else "",
            "tp_hit_at": tp_hit.isoformat() if tp_hit else "",
            "sl_hit_at": sl_hit.isoformat() if sl_hit else "",
            "trigger_met": "YES" if trig else "NO",
            "tp_hit": "YES" if tp_hit else "NO",
            "sl_hit": "YES" if sl_hit else "NO",
        })

OUT = pathlib.Path("/tmp/MISSED_GBPUSD_OPPORTUNITIES.csv")
with OUT.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
    w.writeheader()
    for r in out_rows:
        w.writerow(r)
print(f"wrote {OUT} ({len(out_rows)} rows)")

# Summary: of proposals that WOULD-HAVE-WON, which were WAIT?
from collections import Counter
wait_won = 0
wait_lost = 0
publish_won = 0
publish_lost = 0
for r in out_rows:
    if r["recommendation"] in ("BUY", "SELL") and r["pub_decision"] in ("VALID",):
        if r["tp_hit"] == "YES":
            publish_won += 1
        elif r["sl_hit"] == "YES":
            publish_lost += 1
    elif r["recommendation"] == "WAIT" and r["trigger_met"] == "YES":
        if r["tp_hit"] == "YES":
            wait_won += 1
        elif r["sl_hit"] == "YES":
            wait_lost += 1

print(f"\n== Outcome if the operator had followed the pipeline recommendation ==")
print(f"PUBLISHED (BUY/SELL): TP wins = {publish_won}, SL losses = {publish_lost}")
print(f"\n== Outcome if operator had followed WAIT-suppressed proposals ==")
print(f"WAITed but trigger met: TP wins = {wait_won}, SL losses = {wait_lost}")
print(f"\n(Not real trades; bar-OHLC resolution, no spread deducted.  Illustrative only.)")
