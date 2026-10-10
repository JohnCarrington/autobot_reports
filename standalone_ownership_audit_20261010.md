# Standalone BB-bounce program — AutoBot ownership-touch audit

Host 161 (161.35.168.61). Code path /opt/tradingbot at commit visible via `git log -1`.
Investigation only — no changes. All line numbers are from the live files at audit time.

## Scope

Three questions:

1. How does `ownership_identity.build_deal_reference` build a dealReference, and what does the `mode` argument change?
2. Every place AutoBot decides whether an open IG position belongs to it. For each: what is checked (host tag, mode, epic, else)?
3. If a separate program on this host opens a GBPUSD trade via `open_sb_now(..., mode="BBSTANDALONE")`, would any AutoBot code manage, modify or close it? Yes/no per site, with code quoted.

---

## 1. `build_deal_reference(mode)`

`ownership_identity.py:464-483`:

```python
def build_deal_reference(mode: Optional[str], now_ms: Optional[int] = None) -> str:
    """Build this host's dealReference for a new broker open.

    Shape ``<host>-<mode_code>-<epoch_ms_last10>``. Host and epoch are
    never truncated; the mode code is already bounded (≤ ``_MODE_MAX``
    chars) by the ``_MODE_CODES`` table and the fallback. The full
    reference is guaranteed ≤ ``_IG_MAX`` (30) and matches
    ``^[A-Za-z0-9_-]{1,30}$``.
    """
    host = host_prefix()
    code = _mode_code(mode)[:_MODE_MAX] or "X"
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    epoch = str(int(now_ms))[-_EPOCH_MAX:]
    ref = f"{host}{_SEP}{code}{_SEP}{epoch}"
    assert len(ref) <= _IG_MAX, (
        f"dealReference overflow: {ref!r} ({len(ref)} chars) — "
        "shrink the entry in _MODE_CODES or lower _HOST_MAX"
    )
    return ref
```

Three fields are glued with `-` (constants `_IG_MAX = 30`, `_HOST_MAX = 6`, `_EPOCH_MAX = 10`, `_MODE_MAX = 12`, `_SEP = "-"` — `ownership_identity.py:30-39`):

### `host`
Resolved by `host_prefix()` at `ownership_identity.py:403-426`:

```python
def host_prefix() -> str:
    """This host's ownership prefix on IG dealReferences.

    Resolution order:
      1. ``OWNERSHIP_HOST_PREFIX`` env (sanitised, truncated to
         ``_HOST_MAX``) — explicit operator override.
      2. ``"H"`` + first octet of this box's primary public IPv4.
         Two boxes on different public /8s cannot collide; two boxes
         on the same /8 can — in that case the operator must set
         ``OWNERSHIP_HOST_PREFIX`` to disambiguate.
      3. ``"H0"`` on total failure (no IPv4 reachable).
    ...
    """
    override = os.getenv("OWNERSHIP_HOST_PREFIX") or ""
    cleaned = _sanitize(override, keep="A-Za-z0-9")[:_HOST_MAX]
    if cleaned:
        return cleaned
    ip = _primary_ipv4()
    first_octet = ip.split(".", 1)[0] if "." in ip else ""
    if first_octet.isdigit() and 1 <= len(first_octet) <= 3:
        return f"H{first_octet}"
    return "H0"
```

On host 161 (161.35.168.61) the primary IPv4's first octet is `161`, so `host_prefix()` returns `"H161"` unless `OWNERSHIP_HOST_PREFIX` is set.

### `code` — this is what `mode` changes

`_mode_code(mode)` at `ownership_identity.py:454-461`:

```python
def _mode_code(mode: Optional[str]) -> str:
    key = str(mode or "").strip()
    if key in _MODE_CODES:
        return _MODE_CODES[key]
    key_upper = key.upper()
    if key_upper in _MODE_CODES:
        return _MODE_CODES[key_upper]
    return _fallback_mode_code(key)
```

If `mode` is in the explicit `_MODE_CODES` table (`ownership_identity.py:53-161`, 70+ entries), the stable short code is used (e.g. `"GBPUSD_BB_BOUNCE_L"` → `"GBPBB_L"`, `"BRIEFING_V5"` → `"BRIEF_V5"`, `"DEFAULT"` → `"DEF"`). If not, a deterministic fallback is used at `ownership_identity.py:429-451`:

```python
def _fallback_mode_code(mode: str) -> str:
    """Deterministic abbreviation for modes not in ``_MODE_CODES``.

    Preserves a trailing ``_L`` / ``_S`` direction so same-family
    opposite-direction fires can't collide. Truncates the family part
    from the right. Always ≤ ``_MODE_MAX`` chars; always non-empty.
    """
    s = _sanitize(mode, keep="A-Za-z0-9_").upper()
    if not s:
        return "X"
    direction = ""
    if s.endswith("_L") or s.endswith("_S"):
        direction = s[-2:]
        family = s[:-2]
    else:
        family = s
    # Family part: strip underscores and digits-only noise, then truncate.
    family_compact = re.sub(r"[^A-Z0-9]", "", family) or "X"
    family_budget = _MODE_MAX - len(direction)
    if family_budget < 1:
        return (direction or "X")[:_MODE_MAX] or "X"
    code = family_compact[:family_budget] + direction
    return code or "X"
```

`mode="BBSTANDALONE"` is not in `_MODE_CODES`, so it goes through the fallback: no `_L`/`_S` suffix, `family_compact = "BBSTANDALONE"`, `family_budget = 12`, `code = "BBSTANDALONE"[:12] = "BBSTANDALONE"` (12 chars, exactly `_MODE_MAX`).

### `epoch`
Last 10 digits of `int(time.time() * 1000)`.

### Summary
Calling `build_deal_reference("BBSTANDALONE")` on host 161 with `OWNERSHIP_HOST_PREFIX` unset produces `"H161-BBSTANDALONE-<epoch10>"` (28 chars, matches `DEAL_REFERENCE_PATTERN` at `ownership_identity.py:44-47`). Calling it with any other mode on this host produces `"H161-<code>-<epoch10>"` where `<code>` is either the explicit table entry or the fallback abbreviation.

---

## 2. Every AutoBot site that decides whether an open IG position belongs to it

Production-code callers of `ownership_identity.is_our_reference` / `is_sibling_reference` / `strategy_from_reference` were found by `grep -rn 'is_our_reference\|is_sibling_reference\|strategy_from_reference\|host_prefix(\|from ownership_identity' --include='*.py'`. Tests/scripts not counted. Three live modules carry the decisions: `trade_executor.py`, `trades_api.py`, and `ownership_identity.py` itself.

Each site is quoted below with the exact check and what it governs.

### Site A — Reconciler sibling guard (REJECTS the position)
`trade_executor.py:5967-6001`:

```python
# ── Sibling-reference guard ───────────────────────────────
# A dealReference matching our naming scheme (<host>-<mode>-
# <epoch_ms>) with a DIFFERENT host prefix proves another
# instance of this code opened the position. Reject without any
# local lookup — we must never adopt a sibling's open even if
# it happens to share an epic / direction / price with one of
# ours.
try:
    from ownership_identity import (
        is_our_reference as _is_our_ref,
        is_sibling_reference as _is_sibling_ref,
    )
except Exception:
    _is_our_ref = lambda _r: False
    _is_sibling_ref = lambda _r: False
if _own_deals_only and _is_sibling_ref(deal_reference):
    size_for_log = _to_float_or_none(
        pos.get("dealSize") or pos.get("size") or pos.get("contractSize")
    )
    logger.warning(
        "[OWNERSHIP] %s dealId=%s dealRef=%s direction=%s "
        "size=%s — SIBLING (dealReference host prefix is NOT this "
        "host's); leaving untouched.",
        epic_raw or epic, deal_id, deal_reference, direction, size_for_log,
    )
    _log_foreign_deal({
        "epic": epic_raw or epic,
        "dealId": deal_id,
        "dealReference": deal_reference,
        "direction": direction,
        "size": size_for_log,
        "foreign_reason": "sibling_deal_reference_prefix",
        "host": os.getenv("HOSTNAME") or os.uname().nodename,
    })
    continue
```

Checks: **dealReference host-prefix only** (via `is_sibling_reference` → regex match AND host prefix ≠ this host's). If it's a sibling → log, skip, do not touch.

### Site B — Reconciler ownership resolution for ADOPTION
Same function, `trade_executor.py:6003-6138`. Four ownership sources checked in order. Each proves the broker-side identity of the position:

```python
# ── Own-deals-only gate (per-deal check) ──────────────────
# Two durable ownership sources, tried in order:
#   (A) signal_log — the legacy dispatch path recorded here.
#   (B) candidate_corpus — orchestrator-routed families record
#       here (Repair 9, 2026-09-29). See _scan_candidate_corpus
#       for the ownership predicate (executed=True + non-null
#       execution_deal_id + non-null candidate_id + non-null
#       execution_ts). Sibling-bot deals cannot appear in this
#       corpus because it is written by AutoBot's own
#       orchestrator/adapter seam on this host.
# A deal that misses BOTH sources is FOREIGN and is skipped.
# ...
_own_by_deal = False
_own_by_ref = False
_corpus_row: Optional[Dict[str, Any]] = None
_pending_row: Optional[Dict[str, Any]] = None
ownership_source: Optional[str] = None
if _own_deals_only:
    _own_by_deal = bool(
        _signal_log_readable
        and deal_id
        and lookup_signal_log_by_deal_id(deal_id) is not None
    )
    _own_by_ref = bool(
        _signal_log_readable
        and not _own_by_deal
        and deal_reference
        and lookup_signal_log_by_deal_reference(deal_reference) is not None
    )
    if _own_by_deal or _own_by_ref:
        ownership_source = "signal_log"
    else:
        # Repair 9 fallback — consult candidate_corpus. Exact
        # dealId or dealReference match; ownership predicate
        # enforced inside the helper.
        if deal_id:
            _corpus_row = lookup_candidate_corpus_by_deal_id(deal_id)
        if _corpus_row is None and deal_reference:
            _corpus_row = lookup_candidate_corpus_by_deal_reference(deal_reference)
        if _corpus_row is not None:
            ownership_source = "candidate_corpus_recovery"
            ...
    # 2026-09-30 repair — third ownership source: the durable
    # pending-confirmation ledger. ...
    if ownership_source is None:
        try:
            import pending_deal_ledger as _pdl_rec
            if deal_id:
                _pending_row = _pdl_rec.find_by_deal_id(deal_id)
            if _pending_row is None and deal_reference:
                _pending_row = _pdl_rec.get(deal_reference)
            if isinstance(_pending_row, dict):
                _p_state = str(_pending_row.get("state") or "")
                # Only ACCEPTED records prove ownership. ...
                if _p_state == _pdl_rec.STATE_ACCEPTED:
                    ownership_source = "pending_deal_ledger"
                    ...
                else:
                    _pending_row = None
        ...
    # Fourth ownership source: dealReference prefix. On a shared
    # account where open_sb_now stamps every open with
    # <host>-<mode>-<epoch_ms>, a position whose dealReference
    # starts with THIS host's prefix is ours by broker-authored
    # identity even if the signal_log / candidate_corpus /
    # pending_deal_ledger entry was lost (e.g. disk eviction).
    if ownership_source is None and _is_our_ref(deal_reference):
        ownership_source = "deal_reference_prefix"
        logger.warning(
            "[RECONCILE] %s dealId=%s dealRef=%s direction=%s — "
            "AutoBot ownership recovered via dealReference prefix "
            "match (no signal_log / candidate_corpus / "
            "pending_deal_ledger entry).",
            epic_raw or epic, deal_id, deal_reference, direction,
        )
    if ownership_source is None:
        size_for_log = _to_float_or_none(
            pos.get("dealSize") or pos.get("size") or pos.get("contractSize")
        )
        logger.warning(
            "[RECONCILE] %s dealId=%s dealRef=%s direction=%s "
            "size=%s — FOREIGN (no signal_log origin and no "
            "candidate_corpus origin on this host); leaving "
            "untouched. ..."
        )
        _log_foreign_deal({ ... })
        continue
```

Checks (in order):
1. `dealId` or `dealReference` present as an executed row in `signal_log.jsonl` (writer-of-record for most strategies).
2. `dealId` or `dealReference` present in the `candidate_corpus` with executed=True (orchestrator-routed families: ONE_STRATEGY / QM_V2 / V2_PICK_BOUNCE / BRIEFING_EXECUTION).
3. `dealId` or `dealReference` present in `pending_deal_ledger` with state `ACCEPTED`.
4. `_is_our_ref(deal_reference)` — **dealReference host-prefix match only**. No mode, no epic, no price check. Any dealReference of the form `H161-*-\d{1,10}` passes on this host.

If none match, the position is logged as FOREIGN and `continue` — not adopted.

Reconciler is called **once per boot**, at `autobot.py:12083`:
```python
_reconciled, _seen = reconcile_open_positions(EPIC_MAP, mode_map=_mode_map)
```
(Confirmed by `grep -n 'reconcile_open_positions(' /opt/tradingbot/autobot.py` — no other call sites.)

Default-ON gate at `trade_executor.py:5914-5916`:
```python
_own_deals_only = (
    os.getenv("RECONCILE_OWN_DEALS_ONLY", "1") or "1"
).strip() == "1"
```
With `RECONCILE_OWN_DEALS_ONLY=0` the sibling guard and the four ownership predicates above are **skipped entirely** and every IG position is adopted (pre-gate behaviour).

### Site C — SYNC sweep (operates on local EPIC_STATE only)
`autobot.py:4587-4693`, inside `AutoBot.run_positions_sync`:

```python
def run_positions_sync(self) -> None:
    """SYNC sweep: reconcile broker open positions with EPIC_STATE.
    ...
    """
    try:
        SYNC_MISS_THRESHOLD = 3  # require 3 consecutive confirmed misses (~45s at 15s gap)
        positions = get_open_positions()
        ...
        # Check each locally-tracked position against IG by deal_id
        checked_pks: set = set()
        for _sym, _ep in self.epic_map.items():
            ep_s = str(_ep)
            active_pos = get_all_positions_for_epic(ep_s)
            if not active_pos:
                ...
                continue
            for pk, _pos_st in active_pos:
                checked_pks.add(pk)
                did = str(_pos_st.get("dealId") or _pos_st.get("deal_id") or "")
                if did and did in ig_deal_ids:
                    self._sync_miss_counts.pop(pk, None)
                elif did:
                    misses = self._sync_miss_counts.get(pk, 0) + 1
                    self._sync_miss_counts[pk] = misses
                    if misses < SYNC_MISS_THRESHOLD:
                        logger.warning(
                            f"⚠️ {_ep} dealId={did} not in IG positions ({misses}/{SYNC_MISS_THRESHOLD} misses); waiting."
                        )
                    else:
                        logger.warning(f"🧹 IG has no position for {_ep} dealId={did} ({misses} checks); SYNC closing.")
                        try:
                            _sync_exit = _pos_st.get("last_mid") or _pos_st.get("exit_price")
                            close_position(pos_key=pk, reason="SYNC_NO_POSITION", exit_hint_price=_sync_exit)
                        ...

        # Global sweep: catch any active pos_key whose epic was not in
        # epic_map (or was missed above). ...
        from trade_executor import (
            EPIC_STATE as _EPIC_STATE_ALL,
            EPIC_STATE_LOCK as _EPIC_STATE_LOCK_ALL,
        )
        with _EPIC_STATE_LOCK_ALL:
            _orphan_items = list(_EPIC_STATE_ALL.items())
        for pk, _pos_st in _orphan_items:
            if pk in checked_pks:
                continue
            if not (_pos_st.get("active") or _pos_st.get("pending_open")):
                continue
            did = str(_pos_st.get("dealId") or _pos_st.get("deal_id") or "")
            if not did:
                continue
            if did in ig_deal_ids:
                ...
                continue
            misses = self._sync_miss_counts.get(pk, 0) + 1
            self._sync_miss_counts[pk] = misses
            if misses < SYNC_MISS_THRESHOLD:
                logger.warning(
                    f"⚠️ orphan pk={pk} dealId={did} not in IG positions "
                    f"({misses}/{SYNC_MISS_THRESHOLD} misses); waiting."
                )
            else:
                logger.warning(
                    f"🧹 IG has no position for orphan pk={pk} dealId={did} "
                    f"({misses} checks); SYNC closing."
                )
                try:
                    _sync_exit = _pos_st.get("last_mid") or _pos_st.get("exit_price")
                    close_position(pos_key=pk, reason="SYNC_NO_POSITION_ORPHAN", exit_hint_price=_sync_exit)
```

Checks: **membership in local `EPIC_STATE`**, nothing else. The outer loop iterates `self.epic_map` keys and the inner loop iterates `EPIC_STATE` entries. IG positions not already in `EPIC_STATE` are never visited by this sweep.

### Site D — Per-epic position lookup used by close/manage calls
`trade_executor.py:1514-1526`:

```python
def get_all_positions_for_epic(epic: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Return list of (pos_key, state_dict) for all active/pending positions on this epic."""
    epic = str(epic).strip()
    prefix = epic + "|"
    # Snapshot via list() so a concurrent EPIC_STATE mutation on another
    # thread (e.g. cross-pair worker creating a new pk) cannot raise
    # RuntimeError: dictionary changed size during iteration mid-list-comp
    # and silently kill the per-tick monitor. Mirrors the existing
    # snapshot pattern at count_open_positions_by_pair_direction (~L600).
    return [
        (k, v) for k, v in list(EPIC_STATE.items())
        if k.startswith(prefix) and (v.get("active") or v.get("pending_open"))
    ]
```

Checks: **local `EPIC_STATE` key prefix** (epic) **AND active/pending flag**. No broker data, no dealReference check.

### Site E — Close-all-for-epic (routes via Site D)
`trade_executor.py:6569-6586`:

```python
def close_all_positions_for_epic(
    epic: str,
    reason: Optional[str] = None,
    exit_hint_price: Optional[float] = None,
):
    """Close ALL active positions for the given epic (all modes)."""
    epic = str(epic).strip()
    positions = get_all_positions_for_epic(epic)
    if not positions:
        return None
    results = []
    for pk, _st in positions:
        try:
            r = close_position(pos_key=pk, reason=reason, exit_hint_price=exit_hint_price)
            results.append(r)
        except Exception as e:
            logger.error(f"❌ close_all_positions_for_epic: failed for {pk}: {e}")
    return results[-1] if results else None
```

Checks: whatever `get_all_positions_for_epic` returns, i.e. `EPIC_STATE` entries only.

### Site F — Point-close by pos_key
`trade_executor.py:6523-6566`:

```python
def close_position(
    epic: str = "",
    reason: Optional[str] = None,
    exit_hint_price: Optional[float] = None,
    *,
    pos_key: Optional[str] = None,
):
    """Close a specific position.

    Accepts either pos_key (preferred) or bare epic (backward compat — closes
    the first active position found for that epic).
    """
    if pos_key:
        pk = str(pos_key).strip()
    else:
        pk = str(epic).strip()
    st = _state_for_epic(pk)
    ...
    return close_trade(resolved_pk)
```

Checks: **local `EPIC_STATE`** via `_state_for_epic(pk)`. No broker-side ownership check. The call sites in `autobot.py` and `trade_manager.py` all pass a `pos_key` from EPIC_STATE (verified by grep across both files).

### Site G — Trade-manager monitor loop (SL amend / trail / scale-out / briefing exits)
Call site at `autobot.py:4802` and `4820`:

```python
trade_manager.monitor_positions(
```

`trade_manager.monitor_positions` iterates `EPIC_STATE` for the given epic (every `_amend_broker_sl` and `_exec.close_position` call site in `trade_manager.py` operates on a `pos_key` sourced from `EPIC_STATE`). Checks: **membership in `EPIC_STATE`** plus per-mode allowlists keyed by `st["mode"]`.

### Site H — Dashboard provenance labelling (reporting only, no close)
`trades_api.py:900-946`:

```python
def _classify_open_provenance(
    enr_present: bool,
    by_affected: "dict[str, list[dict]]",
    parent_id: str,
    deal_reference: "str | None" = None,
) -> str:
    """Return BOT / MANUAL / EXTERNAL / SIBLING_BOT / UNKNOWN for the
    position's OPEN event.

    Rules (priority order):
      1. enr present in signal_log → BOT
      2. OPEN event's ``dealReference`` matches this host's prefix
         (ownership_identity.is_our_reference) → BOT
      3. OPEN event's ``dealReference`` matches our scheme but a
         DIFFERENT host prefix → SIBLING_BOT (shared-account scenario)
      4. OPEN channel in {Web, Mobile} → MANUAL
      5. OPEN channel in {API, System} or missing → EXTERNAL
      6. Fallback → UNKNOWN
    """
    if enr_present:
        return "BOT"
    # (2) + (3) dealReference-based ownership (2026-10-08).
    ref = (deal_reference or "").strip()
    if not ref:
        ref = _dealref_for_open(by_affected, parent_id)
    if ref:
        try:
            import ownership_identity  # noqa: WPS433 — lazy
            if ownership_identity.is_our_reference(ref):
                return "BOT"
            if ownership_identity.is_sibling_reference(ref):
                return "SIBLING_BOT"
        except Exception:
            pass
    open_act = _open_activity_row(by_affected, parent_id)
    ...
```

Checks: `signal_log` enrichment presence; then dealReference host prefix via `is_our_reference` / `is_sibling_reference`; then IG activity-stream channel. Pure labelling for the dashboard — this function does not place or close any trades.

Also at `trades_api.py:600-614`:

```python
    for suf, op in opens.items():
        did = op["deal_id"]
        if did and did in fire_deal_ids:
            continue
        # 2026-10-08: skip our-own-reference opens — they are bot fires
        # that bypassed signal_log (BOUNCE_A_*, ONE_STRATEGY).
        ref = op.get("dealReference", "")
        if ref:
            try:
                import ownership_identity  # noqa: WPS433
                if ownership_identity.is_our_reference(ref):
                    continue
            except Exception:
                pass
```

Same thing — a dashboard loop that excludes our-prefix opens from the "externals" list.

### No other production ownership checks
Everything else in the grep output (`tests/`, `scripts/`, `backfill_signal_log.py`, `daily_loss_stop.py`) is either tests, offline tooling, or non-position-management (`daily_loss_stop.py:171-201` groups signal_log rows for a loss-cap calculation; it does not close positions).

---

## 3. Would AutoBot touch a standalone trade opened on this host with `mode="BBSTANDALONE"`?

Precondition: the standalone calls `open_sb_now(..., mode="BBSTANDALONE")` from `/opt/tradingbot/open_sb_now.py`. That function always stamps `dealReference = build_deal_reference(mode or "DEFAULT")` at `open_sb_now.py:56`. On host 161 with `OWNERSHIP_HOST_PREFIX` unset, the dealReference will be `H161-BBSTANDALONE-<epoch10>` (28 chars, matches `DEAL_REFERENCE_PATTERN`).

The two deciding predicates behave as follows on this reference, on this host, with the default env:

- `is_our_reference("H161-BBSTANDALONE-...")` → **True** (host prefix equals `host_prefix()="H161"`).
- `is_sibling_reference("H161-BBSTANDALONE-...")` → **False** (host prefix equals this host's).

Code quoted, `ownership_identity.py:486-508`:

```python
def is_our_reference(deal_reference: Optional[str]) -> bool:
    """True iff ``deal_reference`` matches our scheme AND the host prefix
    equals :func:`host_prefix`. Non-matching strings (e.g. legacy
    IG-generated or human-set) return False."""
    if not deal_reference:
        return False
    m = DEAL_REFERENCE_PATTERN.match(str(deal_reference).strip())
    if m is None:
        return False
    return m.group("host") == host_prefix()


def is_sibling_reference(deal_reference: Optional[str]) -> bool:
    """True iff ``deal_reference`` matches our scheme but with a
    DIFFERENT host prefix — i.e. a sibling bot's open on this account.
    Non-matching strings return False (they are "unknown provenance",
    not "proven foreign")."""
    if not deal_reference:
        return False
    m = DEAL_REFERENCE_PATTERN.match(str(deal_reference).strip())
    if m is None:
        return False
    return m.group("host") != host_prefix()
```

Site-by-site answer:

| Site | What it does | Touches BBSTANDALONE on this host? | Mechanism |
|---|---|---|---|
| A — reconciler sibling guard (`trade_executor.py:5982-6001`) | Skip-and-log IG positions whose dealReference prefix is a sibling | **No** | `is_sibling_reference` returns False (same host prefix), so this branch is not taken. |
| B — reconciler ownership adoption (`trade_executor.py:6003-6138`) | At boot, adopt any IG position that matches one of the four ownership sources | **Yes — only at AutoBot boot/restart.** The fourth source `_is_our_ref(deal_reference)` at line 6107 matches `H161-BBSTANDALONE-...` and sets `ownership_source = "deal_reference_prefix"`. The position is adopted into `EPIC_STATE` with `mode` → `DEFAULT` (because `strategy_from_reference("H161-BBSTANDALONE-...")` returns None — `BBSTANDALONE` is not in `_MODE_CODES`, and `signal_log` / `candidate_corpus` / `pending_deal_ledger` have no record on this host). Once in `EPIC_STATE`, Sites C–G below operate on it. |
| C — SYNC sweep (`autobot.py:4587-4693`) | Close local positions IG no longer has | **Yes — only after Site B adoption.** The sweep iterates `EPIC_STATE`; if BBSTANDALONE closed the position itself and the dealId disappears from IG, the SYNC sweep observes 3 consecutive misses and calls `close_position(pos_key=pk, reason="SYNC_NO_POSITION", exit_hint_price=...)` or `"SYNC_NO_POSITION_ORPHAN"`. If the standalone's position is NOT in `EPIC_STATE`, this sweep cannot see it. |
| D — `get_all_positions_for_epic` (`trade_executor.py:1514-1526`) | Return `EPIC_STATE` entries for an epic | **Only via Site B.** Pure `EPIC_STATE` reader. |
| E — `close_all_positions_for_epic` (`trade_executor.py:6569-6586`) | Loop Site D results and call `close_position` on each | **Only via Site B.** The sites that call this (e.g. `autobot.py:5617`) will close any adopted BBSTANDALONE position for GBPUSD if the call fires (LEVEL_BOUNCE flip, weekend shutdown, etc.). |
| F — `close_position` (`trade_executor.py:6523-6566`) | Close one position by `pos_key` | **Only via Site B.** Direct call sites in `autobot.py` and `trade_manager.py` all pass `pos_key` from `EPIC_STATE`. |
| G — `trade_manager.monitor_positions` (`autobot.py:4802,4820`) | Per-tick SL amend / trail / scale-out / briefing-TP / time-exits | **Only via Site B.** Monitors `EPIC_STATE` entries. Once adopted with `mode=DEFAULT`, the position is subject to any trade-management rule that doesn't gate on a specific mode allowlist. Specifically, `trade_manager` has many allowlists keyed on `mode` (BRIEFING_* / TREND_V3_* / BB_* etc.), so most strategy-specific handlers will NOT fire on `mode="DEFAULT"`; however, the generic `_amend_broker_sl` primitive and the generic close paths route through `pos_key` and will fire for any adopted position. The `[RECONCILE] ... was about to be tagged DEFAULT` WARN at `trade_executor.py:6205-6208` is the comment acknowledging exactly this risk. |
| H — `trades_api._classify_open_provenance` (`trades_api.py:900-946`) and the externals-skip at `trades_api.py:600-614` | Dashboard labelling | **No management/modification/close. Reporting only.** But it will label the standalone position as `BOT` (because `is_our_reference` returns True) and exclude it from the externals list — i.e. the dashboard will book BBSTANDALONE P&L under AutoBot. |

### Net answer

- **While AutoBot is running continuously** (no restart between the standalone's open and its close): **No AutoBot code manages, modifies or closes the position.** `reconcile_open_positions` is called only once per boot (`autobot.py:12083`); all other management paths (Sites C–G) read `EPIC_STATE`, which never gets the standalone's position without going through the reconciler.

- **If AutoBot restarts while the standalone's position is open**: **Yes.** The reconciler takes the "deal_reference_prefix" ownership branch at `trade_executor.py:6107` and adopts the position into `EPIC_STATE` with `mode=DEFAULT`. From that point on it is a managed AutoBot position: SYNC sweep (Site C) can close it on vanished-dealId, `close_all_positions_for_epic` (Site E) can close it on any GBPUSD close-all event, `trade_manager` (Site G) can amend its stop via the generic `_amend_broker_sl` path. The emitted log line is `"[RECONCILE] ... — AutoBot ownership recovered via dealReference prefix match (no signal_log / candidate_corpus / pending_deal_ledger entry)."`

- **Dashboard**: Independently of restart, the standalone's trade will be classified as `BOT` by `trades_api` (Site H) and included in AutoBot P&L totals.

The two gates that control the restart-adoption behaviour, both quoted above, are the host prefix (`host_prefix()` in `ownership_identity.py:403-426` — defaults to `H<first-ipv4-octet>` but respects `OWNERSHIP_HOST_PREFIX`) and the `RECONCILE_OWN_DEALS_ONLY` env (default `1`, read at `trade_executor.py:5914-5916`).

---

## Appendix — grep commands used

```
grep -rn 'is_our_reference\|is_sibling_reference\|strategy_from_reference\|from ownership_identity\|import ownership_identity\|host_prefix(' --include='*.py'
grep -rn 'close_all\|close-all\|orphan\|reconcile\|reconciliation\|position_sweep\|sweep_positions\|TradeManager\|trade_manager\|cancel_all\|close_all_positions\|_close_all\|unknown.*position\|unmanaged' --include='*.py' /opt/tradingbot/*.py
grep -rn 'def close_all_positions_for_epic\|def reconcile_open_positions\|def recover_orphans\|def _is_ours\|def _is_mine\|def is_bot_owned\|def is_our_position' --include='*.py' /opt/tradingbot/*.py
grep -n 'close_sb_now\b\|close_position(\|close_by_deal_id(' /opt/tradingbot/trade_executor.py /opt/tradingbot/autobot.py /opt/tradingbot/trade_manager.py
grep -n 'reconcile_open_positions' /opt/tradingbot/autobot.py /opt/tradingbot/trade_executor.py /opt/tradingbot/trade_manager.py
```

No secrets, keys, or `.env` contents are included in this report.
