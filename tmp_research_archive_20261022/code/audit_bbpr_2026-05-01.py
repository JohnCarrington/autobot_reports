"""Audit BB_PIERCE_RUN for 2026-05-01 against 6 user-validated setups.

For each candidate bar, calls the deployed gbpusd_bb_bounce.evaluate()
with full DEBUG logging captured, and inspects intermediate gate
decisions via the debug dict.

Read-only — no code changes. No state mutation."""
from __future__ import annotations
import os, sys, json, logging
sys.path.insert(0, "/opt/tradingbot")

# Source .env
for line in open("/opt/tradingbot/.env"):
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        continue
    k, _, v = s.partition("=")
    os.environ[k.strip()] = v.strip()

# Capture all DEBUG logs from the strategy
logging.basicConfig(level=logging.DEBUG, format="%(message)s")
for h in logging.root.handlers:
    h.setLevel(logging.DEBUG)

import pandas as pd
import gbpusd_bb_bounce as bbb
import morning_briefing as mb
import news_calendar

# Historical news for 2026-05-01 — only ISM Manufacturing PMI 14:00 USD
HIST = [
    {"time": "14:00", "currency": "USD", "event_name": "ISM Manufacturing PMI", "impact": "High"},
]
news_calendar.get_todays_events = lambda currencies=None: HIST

# Load 05-01 briefing in effect at each setup time
BRIEFINGS_BY_TIME = []
for fp in sorted([
    "/opt/tradingbot/logs/briefing_GBPUSD_2026-05-01_London.json",
    "/opt/tradingbot/logs/briefing_GBPUSD_2026-05-01_London_Open.json",
    "/opt/tradingbot/logs/briefing_GBPUSD_2026-05-01_Mid-session.json",
    "/opt/tradingbot/logs/briefing_GBPUSD_2026-05-01_NY_Mid.json",
]):
    b = json.load(open(fp))
    BRIEFINGS_BY_TIME.append((pd.to_datetime(b["briefing_time"], utc=True), b))

def briefing_at(t):
    chosen = None
    for bt, b in BRIEFINGS_BY_TIME:
        if bt <= t:
            chosen = b
        else:
            break
    return chosen

# Load bars
df = pd.read_csv("/opt/tradingbot/cache/GBPUSD_candles.csv")
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
df = df.sort_values("timestamp").reset_index(drop=True)

USER_SETUPS = [
    ("06:30", "LONG",  "single pierce, +30p run"),
    ("06:45", "SHORT", "3-cluster, +20p run"),
    ("09:25", "LONG",  "4-cluster, +50p run"),
    ("12:10", "SHORT", "4-cluster, +20p run"),
    ("13:45", "LONG",  "2-cluster, +30p run"),
    ("14:00", "SHORT", "5-cluster, +100p+ run"),
]

BACKTEST_FIRES = ["06:25 BUY", "11:20 SELL", "14:05 SELL", "14:25 SELL"]


def eval_at_bar(bar_idx: int):
    """Call gbpusd_bb_bounce.evaluate at bar bar_idx with the prior bar
    as setup. Return (decision, captured_log_lines)."""
    # Build a list capture handler
    captured = []
    class L(logging.Handler):
        def emit(self, record):
            if "BB_PIERCE_RUN" in record.getMessage():
                captured.append(record.getMessage())
    bbb_logger = logging.getLogger("gbpusd_bb_bounce")
    h = L()
    bbb_logger.addHandler(h)

    bar = df.iloc[bar_idx]
    prev = df.iloc[bar_idx-1]
    ts = bar["timestamp"]

    # Briefing in effect at this bar
    b = briefing_at(ts)
    if b is not None:
        mb._BRIEFINGS["GBPUSD"] = b

    prev_b = bbb.Bar(timestamp=prev["timestamp"].to_pydatetime(),
                     open=float(prev["open"]), high=float(prev["high"]),
                     low=float(prev["low"]), close=float(prev["close"]))
    cur_b  = bbb.Bar(timestamp=bar["timestamp"].to_pydatetime(),
                     open=float(bar["open"]), high=float(bar["high"]),
                     low=float(bar["low"]), close=float(bar["close"]))
    closes = df.iloc[max(0, bar_idx-29):bar_idx+1]["close"].astype(float).tolist()

    try:
        dec = bbb.evaluate(
            symbol="GBPUSD", epic="CS.D.GBPUSD.TODAY.IP",
            ts=ts.to_pydatetime(), bars=[prev_b, cur_b],
            closes_ind=closes,
            has_open_long=False, has_open_short=False,
        )
    finally:
        bbb_logger.removeHandler(h)
    return dec, captured


def fmt_bar(r):
    return (f"O={r['open']:.2f} H={r['high']:.2f} L={r['low']:.2f} "
            f"C={r['close']:.2f}")


def setup_audit(setup_time_utc: str, expected_dir: str, note: str):
    """For a user-claimed setup at HH:MM UTC, walk through:
       - bar X-1 (setup bar) and bar X (rejection bar, eval moment)
       - what each gate would say
       - actual evaluate() outcome with all captured BB_PIERCE_RUN logs
    """
    print(f"\n{'='*90}")
    print(f"# SETUP {setup_time_utc} {expected_dir} ({note})")
    print(f"{'='*90}")

    # Find the bar where eval happens. User claim is "X:XX LONG/SHORT"
    # — that's typically the entry candle (rejection bar). So setup_bar = X-1.
    target = pd.Timestamp(f"2026-05-01 {setup_time_utc}+00:00")
    rej_idx_arr = df.index[df["timestamp"] == target]
    if len(rej_idx_arr) == 0:
        print(f"  bar at {setup_time_utc} not found")
        return
    rej_idx = int(rej_idx_arr[0])
    setup_idx = rej_idx - 1
    setup_bar = df.iloc[setup_idx]
    rej_bar = df.iloc[rej_idx]
    bbu = float(rej_bar.get("BB_UPPER_20_2", 0) or 0)
    bbl = float(rej_bar.get("BB_LOWER_20_2", 0) or 0)
    bbu_prev = float(setup_bar.get("BB_UPPER_20_2", 0) or 0)
    bbl_prev = float(setup_bar.get("BB_LOWER_20_2", 0) or 0)
    bb_width = bbu - bbl

    # Pierce magnitude
    if expected_dir == "LONG":
        pierce_pips = max(0.0, bbl_prev - float(setup_bar["low"]))
        band = f"BBL_prev={bbl_prev:.2f}"
    else:
        pierce_pips = max(0.0, float(setup_bar["high"]) - bbu_prev)
        band = f"BBU_prev={bbu_prev:.2f}"

    # 2-candle gate intermediate flags
    open_inside = (
        (expected_dir == "LONG"  and float(setup_bar["open"]) > bbl_prev) or
        (expected_dir == "SHORT" and float(setup_bar["open"]) < bbu_prev)
    )
    rej_body = float(rej_bar["close"]) - float(rej_bar["open"])
    if expected_dir == "LONG":
        rej_dir_ok = rej_body > 0  # bullish rejection for LONG
        rej_back_inside = float(rej_bar["close"]) > bbl_prev
    else:
        rej_dir_ok = rej_body < 0  # bearish rejection for SHORT
        rej_back_inside = float(rej_bar["close"]) < bbu_prev

    print(f"\n  setup bar {setup_bar['timestamp'].strftime('%H:%M')}: {fmt_bar(setup_bar)}")
    print(f"     {band}  BBU_prev={bbu_prev:.2f}  BBL_prev={bbl_prev:.2f}")
    print(f"     pierce_magnitude={pierce_pips:.2f}p  (gate floor=1.0p)")
    print(f"     open_inside_band={open_inside}  (open={setup_bar['open']:.2f})")
    print(f"  rej bar   {rej_bar['timestamp'].strftime('%H:%M')}: {fmt_bar(rej_bar)}")
    print(f"     BBU_n={bbu:.2f}  BBL_n={bbl:.2f}  BB_width={bb_width:.2f}p (floor=8.0p)")
    print(f"     body={rej_body:+.2f} ({'bull' if rej_body>0 else 'bear' if rej_body<0 else 'doji'})  "
          f"rejection_dir_ok={rej_dir_ok}  closes_back_inside={rej_back_inside}")

    dec, logs = eval_at_bar(rej_idx)
    print(f"  → strategy outcome: {'FIRE ' + dec.signal if dec else 'NO FIRE'}")
    if logs:
        for ln in logs:
            print(f"     [BBPR] {ln}")

    # Also try the bar BEFORE — in case user's "06:30 LONG" actually means
    # the rejection happened at 06:30 itself (i.e. setup at 06:30, rejection
    # at 06:35). Or if the user meant the bar BEFORE was the rejection. Try
    # both adjacent bars to disambiguate.
    print(f"\n  ── Also evaluating adjacent bars for completeness ──")
    for offset in (-1, +1):
        bidx = rej_idx + offset
        if 0 < bidx < len(df) - 1:
            b_ts = df.iloc[bidx]["timestamp"].strftime("%H:%M")
            d2, l2 = eval_at_bar(bidx)
            verdict = ("FIRE " + d2.signal) if d2 else "NO FIRE"
            print(f"  {b_ts} → {verdict}")
            for ln in l2:
                if ln.startswith("[BB_PIERCE_RUN]") or "skip" in ln or "ENTRY" in ln:
                    print(f"     [BBPR] {ln}")


# Also audit the surprise 11:20 SELL (not user-validated)
def audit_extra(time_utc: str):
    print(f"\n{'='*90}\n# EXTRA FIRE @ {time_utc} (not in user setups)\n{'='*90}")
    target = pd.Timestamp(f"2026-05-01 {time_utc}+00:00")
    rej_idx = int(df.index[df["timestamp"] == target][0])
    setup_bar = df.iloc[rej_idx-1]
    rej_bar = df.iloc[rej_idx]
    bbu_prev = float(setup_bar.get("BB_UPPER_20_2", 0))
    bbl_prev = float(setup_bar.get("BB_LOWER_20_2", 0))
    print(f"  setup {setup_bar['timestamp'].strftime('%H:%M')}: {fmt_bar(setup_bar)}  BBU={bbu_prev:.2f} BBL={bbl_prev:.2f}")
    print(f"     pierce_above_BBU = {float(setup_bar['high']) - bbu_prev:.2f}p  (high>BBU?)")
    print(f"     pierce_below_BBL = {bbl_prev - float(setup_bar['low']):.2f}p  (low<BBL?)")
    print(f"  rej   {rej_bar['timestamp'].strftime('%H:%M')}: {fmt_bar(rej_bar)}")
    body = float(rej_bar['close']) - float(rej_bar['open'])
    print(f"     body={body:+.2f}p ({'bull' if body>0 else 'bear'})")
    dec, logs = eval_at_bar(rej_idx)
    print(f"  → outcome: {'FIRE ' + dec.signal if dec else 'NO FIRE'}")
    for ln in logs:
        print(f"     [BBPR] {ln}")


for t, d, n in USER_SETUPS:
    setup_audit(t, d, n)

audit_extra("11:20")
audit_extra("14:25")
