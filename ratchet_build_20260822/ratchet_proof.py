"""End-to-end proof walk of tiered_ratchet.

(1) Synthetic walk — BUY entry, tape reaches +30p then flatlines →
    tier advance at +10 (BE) then +30 (+15), exhaustion at 6 flat bars.
    Every bar quoted with both stop tracks (software + broker).
(2) Second walk — BUY entry, tape immediately drops below init 12p SL
    with no tier ever fired → INIT_SL close via RATCHET_STOP. Exhaustion
    counter irrelevant.
(3) Boot line + confirmation: no mode currently resolves to
    TIERED_RATCHET at the shipped env template.
(4) journal — restart command hand-off.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone


def _bar_ts(k: int) -> datetime:
    return datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc) + \
        timedelta(minutes=5 * k)


def _reset_env():
    tmp = tempfile.mkdtemp(prefix="ratchet_proof_")
    os.environ["RATCHET_STATE_PATH"] = f"{tmp}/state.json"
    os.environ["RATCHET_TELEMETRY_PATH"] = f"{tmp}/tele.jsonl"
    os.environ["RATCHET_TIERS"] = "10:0,30:15,60:40,100:75"
    os.environ["RATCHET_INIT_SL_PIPS"] = "12"
    os.environ["RATCHET_EXHAUST_BARS"] = "6"
    for k in list(os.environ):
        if k.startswith(("DRESS_MAP_", "DRESS_DEFAULT_", "EXIT_STACK_")):
            del os.environ[k]
    return tmp


logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])

print("=" * 78)
print("  TIERED_RATCHET end-to-end proof")
print("=" * 78)

# Freshly reload modules so the env is authoritative.
tmpdir = _reset_env()
import tiered_ratchet
importlib.reload(tiered_ratchet)
import exit_dress
importlib.reload(exit_dress)

# ── (0) Boot banner already emitted above by the reload of tiered_ratchet.

# ── (3) Confirm no mode currently resolves to TIERED_RATCHET ─────────
print("\n[3] Dress resolution at shipped env template (no operator overrides):")
print(f"  {'mode':<26s} {'CLEAR':>18s} {'BIG_NEWS':>18s} {'PRE_BIG':>18s} {'POST_BIG':>18s}")
for m in ("GBPUSD_TREND_V3_L", "GBPUSD_TREND_V3_S",
          "GBPUSD_EMA_PULLBACK_L", "GBPUSD_EMA_PULLBACK_S",
          "GBPUSD_BB_BOUNCE_L"):
    row = [f"{exit_dress.resolve(m, lbl):>18s}"
           for lbl in ("CLEAR", "BIG_NEWS", "PRE_BIG", "POST_BIG")]
    print(f"  {m:<26s} " + " ".join(row))
    for lbl in ("CLEAR", "BIG_NEWS", "PRE_BIG", "POST_BIG"):
        assert exit_dress.resolve(m, lbl) != "TIERED_RATCHET", \
            f"BUG: {m}/{lbl} resolves to TIERED_RATCHET"
print("  → confirmed: no mode resolves to TIERED_RATCHET at boot config")


def _fmt(v):
    return "--" if v is None else f"{v:.4f}"


def _print_bar(k, ts, o, h, l, c, tr):
    st = tr.snapshot_state("PK|MODE") or {}
    sw = st.get("software_stop_price")
    br = st.get("broker_stop_price")
    sw_pips = st.get("software_stop_pips")
    max_p = st.get("max_favorable_pips")
    tier = st.get("current_tier")
    no_new = st.get("no_new_extreme_bars")
    closed = st.get("closed", False)
    print(
        f"  bar#{k:2d} ts={ts.strftime('%H:%M')} "
        f"O={_fmt(o)} H={_fmt(h)} L={_fmt(l)} C={_fmt(c)} | "
        f"sw={_fmt(sw)} ({str(sw_pips):>4s}p) "
        f"br={_fmt(br)} tier={tier} "
        f"max_fav={str(max_p):>6s}p no_new={no_new} "
        f"closed={closed}"
    )


# ─────────────────────────────────────────────────────────────────────────
# (1) BUY entry, tape → +30p then flatlines
# ─────────────────────────────────────────────────────────────────────────
print("\n[1] Synthetic walk — BUY entry at 13000.0, tape reaches +30p then flat 6+ bars")
print("    Expect: tier 0 (BE) → tier 1 (+15) → exhaustion at 6 flat bars beyond BE.")
importlib.reload(tiered_ratchet)  # fresh state for scenario 1
tr = tiered_ratchet
tr.arm(pos_key="PK|MODE", mode="GBPUSD_TREND_V3_L",
       direction="BUY", symbol="GBPUSD",
       entry_ts=_bar_ts(0), entry_price=13000.0)
_print_bar(0, _bar_ts(0), None, None, None, None, tr)

bars = [
    # bar#1: reach +12p high → tier 0 (BE).
    dict(o=13000.0, h=13012.0, l=12999.0, c=13008.0),
    # bar#2: high to +32p → tier 1 (+15).
    dict(o=13008.0, h=13032.0, l=13005.0, c=13025.0),
    # bars 3-8: flatline. No new fav high. Exhaustion trips on bar 8
    # (6 no-new-extreme bars beyond BE, tier 1 stop = +15).
    dict(o=13025.0, h=13031.0, l=13022.0, c=13024.0),
    dict(o=13024.0, h=13030.0, l=13022.0, c=13023.0),
    dict(o=13023.0, h=13029.0, l=13021.0, c=13024.0),
    dict(o=13024.0, h=13031.0, l=13022.0, c=13023.0),
    dict(o=13023.0, h=13029.0, l=13021.0, c=13024.0),
    dict(o=13024.0, h=13030.0, l=13021.0, c=13022.0),  # 6th flat bar
]
for i, b in enumerate(bars, start=1):
    act = tr.on_bar_close("PK|MODE", _bar_ts(i),
                          bar_open=b["o"], bar_high=b["h"],
                          bar_low=b["l"], bar_close=b["c"],
                          closes_series=[])
    _print_bar(i, _bar_ts(i), b["o"], b["h"], b["l"], b["c"], tr)
    if act is not None:
        print(f"        → Action: amend_sl_price={_fmt(act.amend_sl_price)} "
              f"close={act.close} reason={act.close_reason}")
    if act is not None and act.close:
        break

final = tr.snapshot_state("PK|MODE") or {}
print(f"\n  Final state: closed={final.get('closed')} "
      f"tier={final.get('current_tier')} "
      f"sw_stop_pips={final.get('software_stop_pips')} "
      f"max_fav={final.get('max_favorable_pips')}p")

# ─────────────────────────────────────────────────────────────────────────
# (2) BUY entry, tape drops through init SL — untouched by exhaustion
# ─────────────────────────────────────────────────────────────────────────
print("\n[2] Synthetic walk — BUY entry at 13000.0, tape falls below init 12p SL")
print("    Expect: init 12p stop breach → RATCHET_STOP close on first breach bar.")
_reset_env()
importlib.reload(tiered_ratchet)
tr = tiered_ratchet
tr.arm(pos_key="SUB|BE", mode="GBPUSD_TREND_V3_L",
       direction="BUY", symbol="GBPUSD",
       entry_ts=_bar_ts(0), entry_price=13000.0)
_print_bar(0, _bar_ts(0), None, None, None, None, tr)

bars2 = [
    dict(o=13000.0, h=13001.0, l=12995.0, c=12998.0),   # small drop, still above SL
    dict(o=12998.0, h=12999.0, l=12992.0, c=12995.0),   # holding
    dict(o=12995.0, h=12996.0, l=12986.0, c=12987.0),   # closes BELOW 12988 SL → RATCHET_STOP
]
for i, b in enumerate(bars2, start=1):
    act = tr.on_bar_close("SUB|BE", _bar_ts(i),
                          bar_open=b["o"], bar_high=b["h"],
                          bar_low=b["l"], bar_close=b["c"],
                          closes_series=[])
    _print_bar(i, _bar_ts(i), b["o"], b["h"], b["l"], b["c"], tr)
    if act is not None:
        print(f"        → Action: amend_sl_price={_fmt(act.amend_sl_price)} "
              f"close={act.close} reason={act.close_reason}")
    if act is not None and act.close:
        break

# ─────────────────────────────────────────────────────────────────────────
# (4) Restart / activation instructions.
# ─────────────────────────────────────────────────────────────────────────
print("\n[4] Activation — RESTART REQUIRED to pick up new code paths")
print("    (autobot loads exit_dress + tiered_ratchet at import; the running")
print("     autobot.service has neither).")
print()
print("    To activate for one mode, on the host:")
print("      sudo systemctl edit autobot.service   # or edit /opt/tradingbot/.env")
print("      # add e.g.")
print("      EXIT_STACK_GBPUSD_TREND_V3_L=TIERED_RATCHET")
print("      EXIT_STACK_GBPUSD_TREND_V3_S=TIERED_RATCHET")
print("      sudo systemctl restart autobot.service")
print()
print("    Only autobot.service reads these envs — no other unit. The nightly")
print("    grind-baseline.timer + daily-journal.timer are unaffected.")
print()
print("    To roll back: unset EXIT_STACK_<MODE> and restart. State file")
print("    at /opt/tradingbot/cache/tiered_ratchet_state.json is orphaned")
print("    but harmless (reconcile_on_startup drops keys not in EPIC_STATE).")

print("\n=" * 78)
print("  END proof")
print("=" * 78)
