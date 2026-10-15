"""telegram_briefings.py — 07:00 UK + pre-NY structural briefings.

Formats an OpeningMap into a Telegram-friendly text and (optionally)
sends it via the EXISTING telegram_alerts sender. Delivery failure is
NEVER allowed to block anything else — all public functions catch
exceptions internally.

Public API:
  * format_opening_briefing(om, header="07:00 UK Opening Map") -> str
  * format_pre_ny_briefing(om, london_hl=(h, l)) -> str
  * send_briefing(text, dry_run=True) -> bool
  * build_and_send_opening(now_utc=None, dry_run=True) -> dict  (full orchestration)

Determinism contract:
  * format_* are pure functions of their inputs. No clock reads, no
    env reads, no file reads. They are directly unit-testable with
    frozen OpeningMap payloads.
  * send_briefing is the ONLY side-effectful function; it short-circuits
    on `dry_run=True` (the default) so test runs never trigger live
    Telegram traffic.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_PROD = "/opt/tradingbot"
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)

from autobot_v3_build.opening_map import OpeningMap, ClusterEntry, LevelEntry, build_opening_map


# ── Formatters ──────────────────────────────────────────────────────────

def _fmt_price(p: Optional[float]) -> str:
    if p is None:
        return "n/a"
    return f"{p/10000.0:.5f}"


def _fmt_level(lv: LevelEntry) -> str:
    d = f" ({lv.distance_pips:+.1f}p)" if lv.distance_pips is not None else ""
    return f"{lv.type}: {_fmt_price(lv.price)}{d}"


def _dir_glyph(direction: Optional[str]) -> str:
    return {"UP": "↑", "DOWN": "↓", "FLAT": "→"}.get(direction or "", "?")


def _cluster_line(c: ClusterEntry) -> str:
    types = ", ".join(c.member_types[:6])
    extra = f" +{len(c.member_types)-6}" if len(c.member_types) > 6 else ""
    return (f"• <b>Cluster</b> @ {_fmt_price(c.center_price)} "
            f"(width {c.width_pips:.1f}p; {len(c.member_types)} levels: {types}{extra})")


def format_opening_briefing(om: OpeningMap,
                            header: str = "07:00 UK Opening Map") -> str:
    """Pure formatter — no I/O."""
    lines: List[str] = [f"<b>{header}</b> — {om.pair}"]
    lines.append(f"snapshot_ts: <code>{om.snapshot_ts}</code>  "
                 f"ref: {_fmt_price(om.reference_price)}")
    # HTF
    d1 = om.htf.get("d1") or {}
    h4 = om.htf.get("h4") or {}
    h1 = om.htf.get("h1") or {}
    lines.append("<b>HTF</b>  " +
                 f"D1 {_dir_glyph(d1.get('direction'))} ({_fmt_price(d1.get('last_close'))})  " +
                 f"H4 {_dir_glyph(h4.get('direction'))} ({_fmt_price(h4.get('last_close'))})  " +
                 f"H1 {_dir_glyph(h1.get('direction'))} ({_fmt_price(h1.get('last_close'))})")
    # NMS
    nms_state = (om.nms or {}).get("v3_state") or "unknown"
    nms_extras: List[str] = []
    for k in ("primary_direction", "trend_state"):
        v = (om.nms or {}).get(k)
        if v:
            nms_extras.append(f"{k}={v}")
    nms_line = f"<b>NMS V3</b>  state={nms_state}"
    if nms_extras:
        nms_line += "  " + " ".join(nms_extras)
    lines.append(nms_line)
    # Clusters (prioritised over single levels for readability)
    if om.clusters:
        lines.append("<b>Confluence clusters:</b>")
        for c in sorted(om.clusters, key=lambda cc: len(cc.member_types), reverse=True):
            lines.append(_cluster_line(c))
    # Nearest-to-reference levels (top 8 by |distance_pips|)
    nearest = [lv for lv in om.levels
               if lv.type != "STAGE6C_ERROR" and lv.distance_pips is not None]
    nearest.sort(key=lambda lv: lv.distance_pips or 0.0)
    if nearest:
        lines.append("<b>Nearest levels:</b>")
        for lv in nearest[:8]:
            lines.append(f"• {_fmt_level(lv)}")
    # Notes
    if om.notes:
        lines.append("<b>Notes:</b>")
        for n in om.notes[:4]:
            lines.append(f"• <i>{n}</i>")
    return "\n".join(lines)


def format_pre_ny_briefing(om: OpeningMap,
                            london_hl: Tuple[Optional[float], Optional[float]] = (None, None),
                            header: str = "Pre-NY Update") -> str:
    """Pre-NY briefing: adds London session H/L that have ESTABLISHED
    since the morning open. Trading is NOT gated on this; the briefing
    is informational."""
    lh, ll = london_hl
    base = format_opening_briefing(om, header=header)
    extra: List[str] = ["<b>London session so far:</b>"]
    if lh is not None:
        extra.append(f"• LN_H: {_fmt_price(lh)}")
    if ll is not None:
        extra.append(f"• LN_L: {_fmt_price(ll)}")
    if lh is None and ll is None:
        extra.append("• (London session H/L not yet established — proceeding without)")
    return base + "\n" + "\n".join(extra)


# ── Sender (fail-closed on exceptions; dry_run default True) ────────────

def send_briefing(text: str, dry_run: bool = True) -> bool:
    """Send a Telegram briefing. Returns True on success; False on
    failure or when dry_run is True. NEVER raises."""
    if dry_run:
        return False
    try:
        import telegram_alerts as _ta
        _ta.send_telegram_message(text, parse_mode="HTML")
        return True
    except Exception:
        return False


# ── Orchestration ───────────────────────────────────────────────────────

def build_and_send_opening(now_utc: Optional[datetime] = None,
                            pair: str = "GBPUSD",
                            dry_run: bool = True) -> Dict[str, Any]:
    """Build the Opening Map at the 07:00 UK snapshot for `now_utc`'s date,
    format it, and (optionally) send to Telegram. Returns a dict with:

      * opening_map: the OpeningMap payload (dict)
      * briefing_text: the formatted text
      * send_ok: bool
      * dry_run: bool

    Fail-silent: any internal error returns a dict with "error".
    """
    try:
        om = build_opening_map(pair=pair, now_utc=now_utc)
        text = format_opening_briefing(om)
        ok = send_briefing(text, dry_run=dry_run)
        return {
            "opening_map": om.to_dict(),
            "briefing_text": text,
            "send_ok": ok,
            "dry_run": dry_run,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}:{exc}", "dry_run": dry_run}


def build_and_send_pre_ny(now_utc: Optional[datetime] = None,
                           pair: str = "GBPUSD",
                           london_hl: Tuple[Optional[float], Optional[float]] = (None, None),
                           dry_run: bool = True) -> Dict[str, Any]:
    try:
        om = build_opening_map(pair=pair, now_utc=now_utc)
        text = format_pre_ny_briefing(om, london_hl=london_hl)
        ok = send_briefing(text, dry_run=dry_run)
        return {
            "opening_map": om.to_dict(),
            "briefing_text": text,
            "send_ok": ok,
            "dry_run": dry_run,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}:{exc}", "dry_run": dry_run}
