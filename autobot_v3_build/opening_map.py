"""opening_map.py — 07:00 Europe/London opening structural map.

READ-ONLY composition of EXISTING AutoBot V3 components. No new
level primitive is defined here; this module composes:

  * level_snapshot_v6.build_level_snapshot  — Stage 6C 11-type universe
  * qm_liquidity_level_mapper.build_map     — BB / swings / session H-L
  * htf_cache.load_cached_candles           — D1 / H4 / H1 reads
  * session_trend                           — NMS V3 state (if any)
  * qm_level_interactions                   — level final-state (if any)

Zero-lookahead invariants:
  * `snapshot_ts` is the FIRST M5 close at or after 07:00 Europe/London.
  * Only bars whose close_ts <= snapshot_ts enter the computation.
  * A bounce "extreme" that occurs AT snapshot_ts is NOT yet classified
    as a prior swing — see `swings_from_last_closed_bar`.
  * No future D1 anchor is used. The pivot anchor is the strictly-prior
    completed D1 bar (as the existing production formulas enforce).

The module is PURE: no filesystem writes outside logs the called modules
already write, no network, no .env mutation.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9 fallback — not expected on host 161
    ZoneInfo = None  # type: ignore

# Shim /opt/tradingbot imports when running from this worktree.
_PROD = "/opt/tradingbot"
if _PROD not in sys.path:
    sys.path.insert(0, _PROD)


__all__ = [
    "OpeningMap",
    "LevelEntry",
    "ClusterEntry",
    "build_opening_map",
    "snapshot_ts_for_date",
]


# ── Data classes ────────────────────────────────────────────────────────

@dataclass
class LevelEntry:
    type: str
    price: float
    source: str            # "stage6c" or "qm_mapper"
    distance_pips: Optional[float] = None  # from reference_price, if given

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClusterEntry:
    center_price: float
    width_pips: float
    member_types: List[str]
    label: str


@dataclass
class OpeningMap:
    pair: str
    snapshot_ts: str                       # ISO8601 UTC
    local_time: str                        # "07:00 Europe/London"
    reference_price: Optional[float]       # 5m close at snapshot_ts if known
    levels: List[LevelEntry] = field(default_factory=list)
    clusters: List[ClusterEntry] = field(default_factory=list)
    htf: Dict[str, Any] = field(default_factory=dict)
    nms: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    source_versions: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair": self.pair,
            "snapshot_ts": self.snapshot_ts,
            "local_time": self.local_time,
            "reference_price": self.reference_price,
            "levels": [l.to_dict() for l in self.levels],
            "clusters": [asdict(c) for c in self.clusters],
            "htf": self.htf,
            "nms": self.nms,
            "notes": self.notes,
            "source_versions": self.source_versions,
        }


# ── Snapshot-ts helper ───────────────────────────────────────────────────

def snapshot_ts_for_date(ref_date: datetime.date, local_time: dtime = dtime(7, 0),
                          tz: str = "Europe/London") -> datetime:
    """UTC moment of 07:00 Europe/London on `ref_date`."""
    if ZoneInfo is None:
        # Approximate: UK is UTC in winter, UTC+1 in summer
        is_bst = (3, 25) <= (ref_date.month, ref_date.day) < (10, 25)
        offset_h = -1 if is_bst else 0
        return datetime.combine(ref_date, local_time, tzinfo=timezone.utc) + timedelta(hours=offset_h)
    zi = ZoneInfo(tz)
    local = datetime.combine(ref_date, local_time, tzinfo=zi)
    return local.astimezone(timezone.utc)


# ── Reference-price helper ───────────────────────────────────────────────

def _reference_price_at(pair: str, snapshot_ts: datetime) -> Optional[float]:
    """Last completed 5m close at or before snapshot_ts, from the archive.
    Returns None if archive data is unavailable."""
    import csv
    for root in ("data/candles", "data/candles_ext", "data/fill"):
        day = snapshot_ts.date().isoformat()
        fp = Path(_PROD) / root / pair / f"{day}.csv"
        if not fp.exists():
            continue
        last = None
        with fp.open() as fh:
            r = csv.DictReader(fh)
            for row in r:
                try:
                    ts = row["timestamp"]
                    if ts.endswith("Z"):
                        ts = ts[:-1] + "+00:00"
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt > snapshot_ts:
                        break
                    last = float(row["close"])
                except Exception:
                    continue
        if last is not None:
            return last
    return None


# ── Level composition ───────────────────────────────────────────────────

def _stage6c_levels(pair: str, snapshot_ts: datetime, reference_price: float) -> List[LevelEntry]:
    out: List[LevelEntry] = []
    try:
        import level_snapshot_v6 as _ls
        snap = _ls.build_level_snapshot(
            pair=pair,
            snapshot_ts=snapshot_ts.isoformat(),
            reference_price=reference_price,
            reference_price_basis="BAR_CLOSE",
            reference_price_source="ARCHIVE_OHLC",
        )
        for lv in snap.levels:
            if lv.price is None:
                continue
            d = round(abs(reference_price - lv.price), 2) if reference_price is not None else None
            out.append(LevelEntry(type=lv.level_type, price=float(lv.price),
                                  source="stage6c", distance_pips=d))
    except Exception as exc:
        # Fail-open with a note; the briefing can still proceed with the mapper-side output
        out.append(LevelEntry(type="STAGE6C_ERROR", price=0.0, source="stage6c",
                              distance_pips=None))
    return out


def _archive_prior_d1(pair: str, for_date: datetime.date) -> Optional[Dict[str, float]]:
    """Prior-D1 OHLC assembled from the fuller 5m archive (candles + candles_ext).
    Used only when the live D1 cache lacks the required date — common for
    pre-2026-03 historical replay. Does NOT replace the mapper; it supplies
    the SAME formulas with the SAME data lineage the mapper would use if
    the cache were populated."""
    import csv
    from datetime import timedelta as _td
    for offset in range(1, 6):  # walk back up to 5 days to skip weekends
        d = (for_date - _td(days=offset)).isoformat()
        bars = []
        for root in ("data/candles", "data/candles_ext"):
            fp = Path(_PROD) / root / pair / f"{d}.csv"
            if not fp.exists():
                continue
            with fp.open() as fh:
                r = csv.DictReader(fh)
                for row in r:
                    try:
                        bars.append((
                            float(row["open"]),
                            float(row["high"]),
                            float(row["low"]),
                            float(row["close"]),
                        ))
                    except Exception:
                        continue
            if bars:
                break
        if bars:
            return {
                "open": bars[0][0],
                "high": max(b[1] for b in bars),
                "low":  min(b[2] for b in bars),
                "close": bars[-1][3],
                "date": d,
            }
    return None


def _pivots_from_prior(prior: Dict[str, float]) -> Dict[str, float]:
    """Standard floor-pivot formulas — identical to
    qm_liquidity_level_mapper._pivots_from_prior:173-187."""
    h, l, c = prior["high"], prior["low"], prior["close"]
    pp = (h + l + c) / 3.0
    return {
        "P": pp,
        "R1": 2 * pp - l,
        "R2": pp + (h - l),
        "R3": h + 2 * (pp - l),
        "S1": 2 * pp - h,
        "S2": pp - (h - l),
        "S3": l - 2 * (h - pp),
    }


def _mapper_levels(pair: str, snapshot_ts: datetime,
                    reference_price: Optional[float]) -> Tuple[List[LevelEntry], List[ClusterEntry]]:
    out: List[LevelEntry] = []
    clusters: List[ClusterEntry] = []
    had_pivots = False
    try:
        import qm_liquidity_level_mapper as _mp
        lm = _mp.build_map(symbol=pair, at_ts=snapshot_ts)
        if lm.p_level is not None and lm.p_level.price is not None:
            had_pivots = True
            d = round(abs(reference_price - lm.p_level.price), 2) if reference_price else None
            out.append(LevelEntry("P", float(lm.p_level.price), "qm_mapper", d))
        for lv in list(lm.outer_pivots) + list(lm.other_levels):
            d = round(abs(reference_price - lv.price), 2) if reference_price else None
            out.append(LevelEntry(lv.type, float(lv.price), "qm_mapper", d))
        for c in lm.clusters:
            if len(c.members) >= 2:
                clusters.append(ClusterEntry(
                    center_price=float(c.center_price),
                    width_pips=float(c.width_pips),
                    member_types=[m.type for m in c.members],
                    label=c.label,
                ))
    except Exception:
        pass

    # Fallback: pivots/PDH/PDL from the extended 5m archive when the mapper
    # didn't yield them (D1 cache sparse for pre-2026 dates).
    if not had_pivots:
        prior = _archive_prior_d1(pair, snapshot_ts.date())
        if prior is not None:
            pivs = _pivots_from_prior(prior)
            for name, price in pivs.items():
                d = round(abs(reference_price - price), 2) if reference_price else None
                out.append(LevelEntry(name, float(price), "archive_prior_d1", d))
            for name, price in (("PDH", prior["high"]), ("PDL", prior["low"])):
                d = round(abs(reference_price - price), 2) if reference_price else None
                out.append(LevelEntry(name, float(price), "archive_prior_d1", d))

    return out, clusters


def _dedup_same_source(levels: List[LevelEntry], tol_pips: float = 0.5) -> Tuple[List[LevelEntry], List[str]]:
    """Deduplicate levels whose prices are within `tol_pips` AND share the same
    semantic source. For example `qm_mapper.PDH` ≈ `stage6c.PDH` — keep one."""
    kept: List[LevelEntry] = []
    notes: List[str] = []
    for lv in levels:
        dup = None
        for k in kept:
            if abs(lv.price - k.price) <= tol_pips:
                # Treat as duplicate if types correspond (PDH==PDH, PIVOT==PIVOT, etc.)
                same_sem = (lv.type == k.type) or (
                    lv.type in ("PIVOT",) and k.type in ("PIVOT",)
                )
                if same_sem:
                    dup = k
                    break
        if dup is None:
            kept.append(lv)
        else:
            notes.append(f"dedup:{lv.source}:{lv.type}@{lv.price} ~= {dup.source}:{dup.type}@{dup.price}")
    return kept, notes


# ── HTF context ─────────────────────────────────────────────────────────

def _htf_context(pair: str, snapshot_ts: datetime) -> Dict[str, Any]:
    out: Dict[str, Any] = {"d1": None, "h4": None, "h1": None, "notes": []}
    try:
        import htf_cache as _hc
        for tf, key in (("D1", "d1"), ("H4", "h4"), ("H1", "h1")):
            cached = _hc.load_cached_candles(pair, tf) or {}
            candles = cached.get("candles") or []
            # Keep only bars that CLOSED at or before snapshot_ts
            closed = []
            for c in candles:
                ts = c.get("timestamp")
                if not ts:
                    continue
                try:
                    s = ts if not ts.endswith("Z") else ts[:-1] + "+00:00"
                    dt = datetime.fromisoformat(s)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if dt <= snapshot_ts:
                    closed.append({**c, "_dt": dt})
            if not closed:
                out["notes"].append(f"{tf}: no closed bars at/before snapshot")
                continue
            closed.sort(key=lambda b: b["_dt"])
            last = closed[-1]
            prev = closed[-2] if len(closed) >= 2 else None
            delta = (last["close"] - prev["close"]) if prev else 0.0
            out[key] = {
                "last_close": last["close"],
                "last_ts": last["_dt"].isoformat(),
                "n_closed_bars": len(closed),
                "delta_vs_prev_pips": round(delta, 2),
                "direction": "UP" if delta > 0 else ("DOWN" if delta < 0 else "FLAT"),
            }
    except Exception as exc:
        out["notes"].append(f"htf_import_error:{type(exc).__name__}")
    return out


# ── NMS context ─────────────────────────────────────────────────────────

def _nms_context(pair: str, snapshot_ts: datetime) -> Dict[str, Any]:
    """Read the NMS V3 session_trend snapshot WITHOUT advancing state."""
    out: Dict[str, Any] = {"v3_state": None, "snapshot_age_s": None, "notes": []}
    try:
        import session_trend as _st
        snap = _st.load_session_authority_snapshot(pair)
        if snap is None:
            out["notes"].append("no_session_trend_snapshot")
            return out
        out["v3_state"] = snap.get("v3_state")
        snap_ts = snap.get("as_of") or snap.get("snapshot_ts")
        if isinstance(snap_ts, str):
            try:
                s = snap_ts if not snap_ts.endswith("Z") else snap_ts[:-1] + "+00:00"
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                out["snapshot_age_s"] = round((snapshot_ts - dt).total_seconds(), 1)
            except Exception:
                pass
        # Expose a few additional telemetry fields when present (read-only)
        for k in ("primary_direction", "trend_state", "last_choch_direction"):
            if k in snap:
                out[k] = snap[k]
    except Exception as exc:
        out["notes"].append(f"session_trend_error:{type(exc).__name__}")
    return out


# ── Entry point ─────────────────────────────────────────────────────────

def build_opening_map(pair: str = "GBPUSD",
                       now_utc: Optional[datetime] = None,
                       reference_price: Optional[float] = None) -> OpeningMap:
    """Build the Opening Map for the trading date in `now_utc`.

    If `now_utc` is None, uses the current UTC time's date at 07:00 UK local.
    If `reference_price` is None, derives it from the 5m archive at snapshot_ts.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    # Snapshot time is 07:00 UK on the SAME UTC date
    snap_ts = snapshot_ts_for_date(now_utc.date())
    if reference_price is None:
        reference_price = _reference_price_at(pair, snap_ts)

    stage6c_levels = _stage6c_levels(pair, snap_ts, reference_price or 0.0)
    mapper_levels, clusters = _mapper_levels(pair, snap_ts, reference_price)
    merged, dedup_notes = _dedup_same_source(stage6c_levels + mapper_levels)
    htf = _htf_context(pair, snap_ts)
    nms = _nms_context(pair, snap_ts)

    om = OpeningMap(
        pair=pair,
        snapshot_ts=snap_ts.isoformat(),
        local_time="07:00 Europe/London",
        reference_price=reference_price,
        levels=merged,
        clusters=clusters,
        htf=htf,
        nms=nms,
        notes=list(dedup_notes),
        source_versions={
            "level_snapshot_v6": _get_version("level_snapshot_v6", "CALCULATION_VERSION", "unknown"),
            "qm_liquidity_level_mapper": "v1",
            "build": "autobot_v3_build.opening_map:v1",
        },
    )
    return om


def _get_version(mod: str, attr: str, default: str) -> str:
    try:
        import importlib
        m = importlib.import_module(mod)
        return str(getattr(m, attr, default))
    except Exception:
        return default
