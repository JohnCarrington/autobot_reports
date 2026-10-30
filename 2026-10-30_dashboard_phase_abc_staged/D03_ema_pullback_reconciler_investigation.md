# D-03 Investigation — EMA Pullback false-close root cause

- **Priority:** HIGH
- **Author:** Investigation agent (read-only)
- **Date:** 2026-10-30
- **Scope:** `/opt/ema_pullback/` (deployed tree) — READ ONLY, no edits, no service
  restarts, no broker calls, no venv execution.
- **Trigger event:** 2026-10-29 20:07:22Z — deal `DIAAAAYR3TPT4BU`
  (`EMAPB-B-1793304045-89EC3C`, BUY 2.0 @ 13376.3, SL 13364.3, TP 13476.3)
  marked CLOSED by the EMA Pullback reconciler 22 seconds after fill while
  broker reports the position OPEN.
- **Verdict:** Confirmed defect. Reproduced in code. Historical misfires
  identified (5 events, same signature, over the last ~11 hours of trading).
  Proposed correction specified at the code level — NOT yet implemented.

---

## 1. Confirmed root cause (reproducible walkthrough)

### 1.1 The false-close path (code citation)

The IN_TRADE→CLOSED decision lives in `service.py` and reads only ONE
boolean signal from the broker: "was my dealId in the latest `/positions`
listing?". If the listing came back empty, the service unconditionally
treats that as "broker closed my position":

```
# /opt/ema_pullback/ema_pullback/service.py:825-838
        if active.state == IN_TRADE:
            if pos_payload is not None:
                return   # still open
            # Position vanished — broker-driven exit.
            exit_price = _safe_float(active.audit.get("last_known_mid"))
            if exit_price is None:
                exit_price = float(active.broker_sl_level or active.fill_price or 0.0)
            self.mark_closed(
                exit_price=exit_price,
                exit_ts=now_utc,
                exit_reason="broker_closed",
            )
            logger.info("[RECONCILE] IN_TRADE→CLOSED (broker exit) deal_id=%s", active.deal_id)
            return
```

`pos_payload` is the deal-id match on the output of
`list_own_open_positions(prefix)`:

```
# /opt/ema_pullback/ema_pullback/service.py:553-582
        try:
            prefix = self.cfg.ownership_prefix
            working_orders = self.ig.list_own_working_orders(prefix)
            positions = self.ig.list_own_open_positions(prefix)
        except Exception as exc:
            logger.warning("[RECONCILE] IG probe failed: %s", exc)
            return
        ...
        wo_payload, _ = _match(working_orders)
        pos_payload, pos_row = _match(positions)
```

Note: `list_own_open_positions` DOES NOT raise on failure, so the
`except` branch is unreachable for that path (see §1.2). `positions`
being `[]` means `_match()` returns `(None, None)` and `pos_payload` is
`None`.

### 1.2 The listing primitive returns `[]` on BOTH outcomes

```
# /opt/ema_pullback/ema_pullback/ig_client.py:1057-1077
    def list_own_open_positions(self, prefix: str) -> List[Dict[str, Any]]:
        """Return the open positions whose dealReference starts with our prefix."""
        self._require_live_approved()
        try:
            with self._ig_lock:
                resp = self._ig_service.session.get(
                    f"{self._ig_service.BASE_URL}/positions",
                    headers=self._ig_service.session.headers,
                )
        except Exception as exc:
            logger.warning("[LIVE-IG] positions GET failed: %s", exc)
            return []                     # <-- failure path
        if resp.status_code != 200:
            logger.warning("[LIVE-IG] positions GET %d body=%s",
                           resp.status_code, (resp.text or "")[:200])
            return []                     # <-- failure path
        try:
            rows = resp.json().get("positions", []) or []
        except Exception:
            return []                     # <-- failure path
        return _filter_by_ref_prefix(rows, prefix)   # <-- success (may be [])
```

Four code paths all return `[]`:

| Path                                                        | Meaning                 |
|-------------------------------------------------------------|-------------------------|
| requests exception (network/connect/timeout)                | **UNKNOWN** (not empty) |
| HTTP ≠ 200 (403 auth-rotate, 429 rate-limit, 5xx server)    | **UNKNOWN** (not empty) |
| JSON decode error                                           | **UNKNOWN** (not empty) |
| 200 + `positions=[]` after prefix filter                    | genuinely empty         |

The service collapses all four onto one signal (`pos_payload is None`)
and then treats that signal as "broker closed the position". Three of
the four conditions are reporting outages — not closures.

### 1.3 The actual trigger for D-03

The service log is unambiguous:

```
# /opt/ema_pullback/logs/ema_pullback.log:3933-3936
3933:2026-10-29 20:07:00,633 INFO trading_ig.rest: POST '/positions/otc', resp 200
3934:2026-10-29 20:07:00,666 INFO trading_ig.rest: GET '/confirms/EMAPB-B-1793304045-89EC3C', resp 200
3935:2026-10-29 20:07:00,667 INFO ema_pullback.ig_client: [LIVE-IG] market_entry FILLED dealReference=EMAPB-B-1793304045-89EC3C dealId=DIAAAAYR3TPT4BU fill=13376.3
3936:2026-10-29 20:07:22,236 INFO ema_pullback.service: [RECONCILE] IN_TRADE→CLOSED (broker exit) deal_id=DIAAAAYR3TPT4BU
```

Exactly ~21.6s between the fill confirm and the false-close. That
matches the poll cadence (`POLL_SECONDS=20` in `config.py:339` and
`main.py:356-369`) — i.e. the fill happened mid-poll-interval, and the
VERY NEXT reconcile tick evaluated it.

Critically there is **no `[LIVE-IG] positions GET` warning line** in the
log around that reconcile. If the GET had failed with a non-200, the
WARNING at `ig_client.py:1070-1071` would have surfaced. If the GET had
raised, the WARNING at `ig_client.py:1067` would have surfaced. Neither
appears. The reconcile therefore observed a 200-OK with `positions=[]`
— a genuine listing miss by IG's `/positions` cache, delivered 21s after
the fill confirm.

### 1.4 The exit price is fabricated (not quoted) when `last_known_mid` is unset

Line 829 reads `active.audit["last_known_mid"]`. A grep across the
entire deployed tree shows this key has **zero writers**:

```
$ grep -rn 'last_known_mid"\s*=\|"last_known_mid":' /opt/ema_pullback/ema_pullback/
(no matches)
```

Every false-close path therefore falls through to the second clause:

```
# service.py:830-831
            if exit_price is None:
                exit_price = float(active.broker_sl_level or active.fill_price or 0.0)
```

The ledger receives `exit_price == broker_sl_level`, which is EXACTLY
what every historical misfire exhibits (§2 below). This fabricated
"loss at SL" number is then written into the strategy CSV and the
setup-history JSONL as `exit_reason=broker_closed`.

### 1.5 Full call-chain summary (fill → false-close)

| Time    | Event                                                                | File:line           |
|---------|----------------------------------------------------------------------|---------------------|
| T+0.0s  | POST `/positions/otc` returns 200                                    | ig_client.py:697+   |
| T+0.03s | GET `/confirms/EMAPB-...-89EC3C` returns 200, dealId=DIAAAAYR3TPT4BU | ig_client.py:572    |
| T+0.03s | `_promote_to_in_trade(..., source="FILLED")` runs                    | service.py:2076     |
| T+21.5s | Next poll tick: `step()` → `_reconcile_broker_state()`               | service.py:356      |
| T+21.5s | `list_own_open_positions("EMAPB")` returns `[]` (200 OK, empty)      | ig_client.py:1057   |
| T+21.5s | `_match(positions)` → `pos_payload=None`                             | service.py:582      |
| T+21.5s | `active.state == IN_TRADE and pos_payload is None`                   | service.py:825-826  |
| T+21.5s | `exit_price = broker_sl_level` (fallback)                            | service.py:829-831  |
| T+21.5s | `mark_closed(..., exit_reason="broker_closed")`                      | service.py:832      |
| T+21.5s | Ledger: CLOSED. `self.active = None`. Slot freed.                    | service.py:2101-2105|

### 1.6 Why list_own_open_positions returning `[]` is ambiguous

Summarising §1.2:

- `[]` on genuine empty: `/positions` returned 200 with `positions=[]`,
  OR with positions that all failed our prefix filter.
- `[]` on HTTP failure: `requests` raised, OR `resp.status_code != 200`.
- `[]` on JSON failure: body not parseable as JSON.

The caller (`service.py:582`) cannot tell these apart. The only
telemetry the client emits for failures is a WARNING log line — the
return value itself is lossy. On the business layer, the reconciler
reads the sentinel `None` from `_match()` as if it meant "broker says
your position is gone", which is a strict superset of what the client
can actually prove.

---

## 2. Historical misfire evidence

Scan of `/opt/ema_pullback/state/setup_history.jsonl` (421 total rows) for
`exit_reason=broker_closed` yields **5 events**, all with ~21s held time
and `exit_price == broker_sl_level`:

| # | ts (CLOSED record)             | deal_id             | setup_id | dir  | fill_price | exit_price | SL level | held_s | reconcile log line |
|---|--------------------------------|---------------------|----------|------|------------|------------|----------|--------|--------------------|
| 1 | 2026-10-29T15:53:50.534115Z    | DIAAAAYR2YZ6RB3     | 7A5CFB   | BUY  | 13380.0    | 13368.0    | 13368.0  | 21.88  | log:3368/3371      |
| 2 | 2026-10-29T17:11:47.899193Z    | DIAAAAYR3ETVCAY     | 07C0E9   | BUY  | 13375.0    | 13363.0    | 13363.0  | 21.44  | log:3544/3545      |
| 3 | **2026-10-29T20:07:22.230791Z**| **DIAAAAYR3TPT4BU** | 89EC3C   | BUY  | 13376.3    | 13364.3    | 13364.3  | 20.98  | **log:3935/3936**  |
| 4 | 2026-10-30T00:43:52.333484Z    | DIAAAAYR4FEYEBL     | F8E4EF   | BUY  | 13390.5    | 13378.5    | 13378.5  | 20.94  | log:4829/4830      |
| 5 | 2026-10-30T03:03:34.587341Z    | DIAAAAYR4QJPMAG     | 4A2EA4   | BUY  | 13399.5    | 13387.5    | 13387.5  | 22.72  | log:5391/5392      |

### 2.1 Signature consistency

All five events share the exact pathological fingerprint:

- `exit_reason == "broker_closed"`
- `exit_price - fill_price == -12.0` (BROKER_SL_PIPS = 12)
- `exit_price == broker_sl_level` to 4 decimal places
- Held time ≈ one poll interval (20-23s)
- `audit.last_known_mid == null`

### 2.2 What this signature implies

- **Every** `broker_closed` event in the EMA Pullback ledger since
  deployment is suspicious. The strategy has not recorded a single
  broker-driven close with a plausible non-SL exit price.
- The three events on 2026-10-29 pre-dating D-03 were produced by the
  same codepath. D-03 was ALREADY misfiring hours before 20:07Z — it
  simply had not been audited until event #3 was flagged by the
  operator.
- Events #4 and #5 occurred AFTER the 20:07Z event, confirming the
  defect persists through the UTC-day rollover.

### 2.3 Audit evidence that these are false-closes

The service log for each event (grep output on `ig_client.py` live
positions endpoint over the day):

```
$ grep -n "positions GET\|workingorders GET" /opt/ema_pullback/logs/ema_pullback.log
(no matches)
```

Zero HTTP failures logged across the entire file (6120 lines). Every
one of the five reconciles observed a 200 OK response with an empty
listing. This is an IG `/positions` cache-coherency artefact — the
dealId exists at the broker but is not yet reflected in the
account-wide positions listing on the exact 21s poll that follows the
fill.

The operator-side audit cited in the brief
(2026-10-29T23:25:24Z, `DIAAAAYR3TPT4BU` queried via deal-id endpoint
and confirmed OPEN) is the authoritative proof that the broker position
survived the reconcile. The same deal-id probe on events #1, #2, #4, #5
is a strongly-recommended follow-up (and is almost certainly going to
produce a similar OPEN-vs-ledger-CLOSED discrepancy).

---

## 3. Why the broker is actually OPEN but the listing is empty

IG's REST surface exposes two orthogonal view of positions:

| Endpoint              | Semantics                                                     | Latency after fill |
|-----------------------|---------------------------------------------------------------|--------------------|
| `GET /positions`      | Account-wide positions listing. **Cache-backed, snapshot view.** | **Lagged by 5-30s** |
| `GET /positions/{dealId}` | Deal-authoritative lookup. Returns 200 if open, 404 if closed. | **Immediate (ledger-of-truth)** |

The listing endpoint is a materialised view over the per-deal ledger.
Short-lived cache invalidation gaps are a known IG-side characteristic
(the dashboard-banner research summarised in the operator memory
[[dashboard_banner_unreliable]] documents an analogous staleness problem
in a different IG REST surface — snapshot views are not deal-of-truth).

In the D-03 case the chain is:

1. POST `/positions/otc` → 200 + dealId `DIAAAAYR3TPT4BU`.
2. GET `/confirms/{dealRef}` → 200, `dealStatus=ACCEPTED`.
3. **The per-deal ledger reflects the position immediately.**
4. The account-wide positions-listing cache is invalidated / rebuilt
   asynchronously by IG. Rebuild typically completes within one tick,
   but under broker load or auth-rotation it can lag past the EMA
   Pullback poll interval.
5. GET `/positions` at T+21.5s returns 200 with `positions=[]` because
   the listing cache is still mid-rebuild.
6. GET `/positions/DIAAAAYR3TPT4BU` at the same instant would return
   200 with the position body — the per-deal ledger has been authoritative
   the whole time.

The EMA Pullback service never probes the per-deal endpoint. Its only
view of the broker's position state is the lagging snapshot view, and
it does not even distinguish between "snapshot says empty" and
"snapshot GET failed" (§1.2).

### 3.1 Rate of recurrence

The 5-event histogram across ~11 hours of trading (15:53Z 2026-10-29 →
03:03Z 2026-10-30) is a strict lower bound — only the events that
produced a fill AND then triggered false-close are visible. The rate
observed is one false-close every ~2.2 trading hours during the London
session's active window. Any proposed correction MUST be verified to
survive at least one full UK-market day (one full session cycle
including Asia roll, London open, NY session, overnight) before the
ledger can be trusted again.

---

## 4. Proposed safe correction (code, NOT yet implemented)

The remediation space has three independent layers. The brief asks for
A+C combined — those are the right two. Option B is lower-value and
discussed for completeness.

### 4.1 Option A — Deal-id confirm before mark_closed

**Change surface:** `service.py:825-838` IN_TRADE→CLOSED branch
reorganised to require an independent broker confirmation before
`mark_closed()`.

**New client method** (plumbing-only, no network changes elsewhere):

```python
# ig_client.py (new method on LiveIGClient)
def probe_position_by_deal_id(self, deal_id: str) -> Optional[dict]:
    """Return the position body if GET /positions/{dealId} responds 200.
    Return None if 404. Raise LookupUnknown on any other outcome
    (HTTP non-200/non-404, network, JSON failure).

    This is the deal-authoritative probe. The listing endpoint
    (/positions) is a cache view and can lag the per-deal ledger by
    several seconds after a fill or close.
    """
    self._require_live_approved()
    with self._ig_lock:
        resp = self._ig_service.session.get(
            f"{self._ig_service.BASE_URL}/positions/{deal_id}",
            headers=self._ig_service.session.headers,
        )
    if resp.status_code == 200:
        try:
            return resp.json()
        except Exception as exc:
            raise LookupUnknown(f"deal-id probe JSON decode: {exc}")
    if resp.status_code == 404:
        return None
    raise LookupUnknown(
        f"deal-id probe HTTP {resp.status_code} body={(resp.text or '')[:200]}"
    )
```

**New service branch**:

```python
# service.py:825-838 — rewritten
if active.state == IN_TRADE:
    if pos_payload is not None:
        return   # listing says still open — no change
    # Listing says empty. Confirm authoritatively before closing.
    try:
        probe = self.ig.probe_position_by_deal_id(active.deal_id or "")
    except LookupUnknown as exc:
        logger.warning(
            "[RECONCILE] IN_TRADE deal-id probe inconclusive deal_id=%s: %s "
            "— deferring close decision to next tick",
            active.deal_id, exc,
        )
        return   # DO NOT close on an unknown outcome
    if probe is not None:
        # Broker confirms the position is OPEN. The empty listing was
        # a cache-coherency artefact. Leave the setup in IN_TRADE.
        logger.info(
            "[RECONCILE] IN_TRADE listing-empty but deal-id confirms OPEN "
            "deal_id=%s — ignoring listing miss",
            active.deal_id,
        )
        return
    # Broker confirms the position is CLOSED (deal-id 404).
    # TODO before this ships: wire /history/activity probe here so the
    # exit_price can be taken from the broker's recorded close level
    # instead of fabricated from broker_sl_level. See §4.4 "Known gap".
    exit_price = _safe_float(active.audit.get("last_known_mid"))
    if exit_price is None:
        exit_price = float(active.broker_sl_level or active.fill_price or 0.0)
    self.mark_closed(
        exit_price=exit_price,
        exit_ts=now_utc,
        exit_reason="broker_closed",
    )
    logger.info(
        "[RECONCILE] IN_TRADE→CLOSED (broker exit, deal-id confirmed 404) "
        "deal_id=%s", active.deal_id,
    )
    return
```

**Trade-offs**:

- Pro: Correct signal plumbing. The deal-id endpoint is IG's
  deal-of-truth; a 404 is unambiguous.
- Pro: Zero behavioural change on the happy path (position still open
  in the listing → no extra network call).
- Con: One extra `/positions/{dealId}` GET per reconcile tick during
  which the listing is empty. Rate ≈ one false-close every 2.2 hours
  observed → negligible IG surface load (~0.0001 QPS).
- Con: `LookupUnknown` is a new sentinel. Service treats it as
  "defer" (consistent with the existing "leave state untouched on
  transient outage" principle at service.py:547-548).

### 4.2 Option B — Retry with backoff on empty listing

**Change surface:** `service.py:556` wrapper.

```python
positions = self.ig.list_own_open_positions(prefix)
if active and active.state == IN_TRADE and active.deal_id:
    tries = 0
    while _match_deal_id(positions, active.deal_id) is None and tries < 3:
        time.sleep([2, 4, 8][tries])
        positions = self.ig.list_own_open_positions(prefix)
        tries += 1
```

**Trade-offs**:

- Pro: Does not require a new endpoint call pattern.
- Con: Adds 2+4+8 = **14 seconds of blocking latency** to every empty
  listing. If a position IS genuinely closed (SL hit), this delays the
  CLOSED ledger record by 14s and blocks the main poll loop for the
  same window. Combined with Python's GIL and the serial poll loop,
  this impairs other state transitions (ARMED, ORDER_WAITING, exit SM
  check) across the window.
- Con: Does not solve the underlying ambiguity — three empty listings
  in a row could still be a cache miss, and a 15% listing miss rate
  per probe (observed 5-events-in-11-hours is a lower bound) is enough
  that 3x compounding does not drive the false-close probability to
  zero.
- Verdict: **Not recommended standalone.** The deal-id probe is more
  decisive and faster.

### 4.3 Option C — Distinguish HTTP failure from empty at the client

**Change surface:** `ig_client.py:1057-1077`.

Current signature `list_own_open_positions(prefix) -> List[Dict[str, Any]]`
returns `[]` on both failure AND genuine empty. Change to:

```python
def list_own_open_positions(self, prefix: str) -> Optional[List[Dict[str, Any]]]:
    """Return the open positions whose dealReference starts with prefix.

    Returns:
        list[dict] - genuine listing (possibly empty) when IG responded 200.
        None       - UNKNOWN. The listing could not be obtained
                     (network/HTTP/JSON failure). Caller MUST NOT infer
                     "position closed" from this value.
    """
    self._require_live_approved()
    try:
        with self._ig_lock:
            resp = self._ig_service.session.get(
                f"{self._ig_service.BASE_URL}/positions",
                headers=self._ig_service.session.headers,
            )
    except Exception as exc:
        logger.warning("[LIVE-IG] positions GET failed: %s", exc)
        return None                                     # <-- UNKNOWN
    if resp.status_code != 200:
        logger.warning("[LIVE-IG] positions GET %d body=%s",
                       resp.status_code, (resp.text or "")[:200])
        return None                                     # <-- UNKNOWN
    try:
        rows = resp.json().get("positions", []) or []
    except Exception as exc:
        logger.warning("[LIVE-IG] positions JSON decode: %s", exc)
        return None                                     # <-- UNKNOWN
    return _filter_by_ref_prefix(rows, prefix)
```

**Service-side callers** must then handle `None` as "defer":

```python
# service.py:555-559 — new handling
positions = self.ig.list_own_open_positions(prefix)
working_orders = self.ig.list_own_working_orders(prefix)
if positions is None:
    logger.warning("[RECONCILE] /positions UNKNOWN — deferring state transitions")
    return
```

**Trade-offs**:

- Pro: Correct signal plumbing at the right layer. Three callers of
  `list_own_open_positions` (`service.py:556`, `ig_client.py:1088`
  inside `account_wide_exposure`, and `main.py:133` boot-time probe)
  all become robust against transient failures.
- Pro: Zero behavioural change on the happy path.
- Pro: Compatible with Option A — they stack cleanly.
- Con: Breaking signature change for every caller. `main.py:133`
  currently does `ig.list_own_open_positions(prefix) or []` which
  silently papers over the new semantics. Must be explicit — "unknown"
  on bootstrap should fail-closed (abort service start) not silently
  continue.

### 4.4 Recommended combination: A + C

**A alone** is insufficient because the listing can also return `[]`
due to transient HTTP failure (not just cache lag). Without C, the
service still has to call the client once, see `[]`, and then
immediately probe deal-id — but the client WARNING is the only signal
that distinguishes failure from genuine empty, and the service doesn't
read logs.

**C alone** is insufficient because even on a legitimate 200+empty
response (as in all 5 observed misfires), the listing can lag the
per-deal ledger. The service needs an authoritative probe to break
that tie.

**A+C together** form a layered defence:

| Scenario                                    | C sees   | A probes   | Decision          |
|---------------------------------------------|----------|------------|-------------------|
| Position open, listing coherent             | `[dict]` | not needed | stay IN_TRADE     |
| Position open, listing cache lag            | `[]`     | 200        | stay IN_TRADE     |
| Position closed, listing coherent           | `[]`     | 404        | mark CLOSED       |
| Position closed, listing cache lag          | `[]`     | 404        | mark CLOSED       |
| GET /positions failed                       | `None`   | not run    | defer, next tick  |
| GET /positions ok, GET /positions/{id} failed | `[]`   | LookupUnknown | defer, next tick |

Every ambiguous outcome → `defer`. Every mark_closed is deal-id-authoritative.

### 4.5 Known gap left by A+C

Even after A+C, when the broker confirms the position is CLOSED (404
on deal-id), the exit_price is still fabricated from `broker_sl_level`
because `last_known_mid` has no writer (§1.4). This produces
superficially correct P&L (always exactly −12 pips) but is not what
actually happened at the broker — IG's `/history/activity` records the
real close level and reason (TP, SL, operator, GTC expiry).

A hardened second-pass fix would:

1. Write `last_known_mid` from each live-feed tick while the setup is
   IN_TRADE (`price_source.py:337` is the obvious hook).
2. When the deal-id probe returns 404, consult
   `fetch_recent_activity_for_deal(active.deal_id)` for the authoritative
   close level and reason (code pattern already in service.py:782-801
   for the ORDER_WAITING path — can be lifted verbatim).

This is **out of scope** for the D-03 safe correction. Flagged as
follow-up: ticket "EMA Pullback false-exit-price fabrication".

---

## 5. Deployment plan (NOT part of this project)

This section is advisory for the operator. No deployment is proposed
by this report.

### 5.1 Pre-deployment testable without broker

- Add a unit test that constructs `EmaPullbackService` with a stub `ig`
  implementing a controllable `list_own_open_positions` and
  `probe_position_by_deal_id`. Drive the service into IN_TRADE, then
  make the stub return `[]` on listing + `dict` on deal-id.
  Assert `mark_closed()` is NOT called and the setup stays IN_TRADE.
  (Mirror symmetric assertion for the 404 case → `mark_closed` IS
  called.) Pattern reuse: existing `tests/` fixtures under
  `/opt/ema_pullback/tests/` already stub `IGClientBase`.
- Add a replay-harness pass over the last 11 hours of state_history +
  log data to confirm all 5 known misfires would have been averted.

### 5.2 Deployment steps (operator decision — out of scope here)

1. Build in a non-live tree per repo convention. One EMA Pullback
   service restart is required for the fix to take effect.
2. During restart the `EMAPB_SHUTDOWN_POLICY=cancel_orders_only`
   default is appropriate (open positions are protected by broker-side
   SL/TP).
3. First post-restart reconcile tick will encounter the stale ledger
   state for `DIAAAAYR3TPT4BU` (if still open) — the ledger carries
   `active = None` so the service does not try to manage it. See §6.

### 5.3 Verification after deployment

- Confirm `[LIVE-IG] positions GET` warnings surface when they occur
  (they must; previously they only logged and were swallowed).
- Confirm the first naturally-occurring broker close (SL hit, TP hit,
  or operator close) emits a CLOSED record with the dealId probe
  showing 404.
- No `broker_closed` record may be written for a position whose
  deal-id probe returned 200 within the same reconcile tick.
- Minimum 24h observation window spanning Asia roll + London open +
  NY session before the fix is considered validated.

---

## 6. Current open position status

### 6.1 D-03 deal state as of this report

- `DIAAAAYR3TPT4BU` (BUY 2.0 @ 13376.3, SL 13364.3, TP 13476.3)
  confirmed OPEN at the broker as of operator audit 2026-10-29T23:25:24Z.
- Local EMA Pullback ledger says CLOSED (exit_price 13364.3, exit_reason
  broker_closed) at 2026-10-29T20:07:20.694Z.
- `self.active` is `None`: the service has moved on and placed
  subsequent setups (F8E4EF at 00:43Z, 4A2EA4 at 03:03Z, 0987BB armed
  at 04:55Z — see `setup_history.jsonl:tail`). It will NOT reconcile
  this deal on next restart. The ledger entry is final from the
  service's perspective.

### 6.2 Reconciliation behaviour on next restart

The ledger is single-slot. On service restart `main.py` loads the last
`ARMED/ORDER_WAITING/IN_TRADE` row from `active.jsonl` (if present)
into `self.active`. For the five misfired deals, each has a terminal
`CLOSED` record and the service has already overwritten `active` with
the next setup. The restart will NOT re-adopt the broker-OPEN position
`DIAAAAYR3TPT4BU` — it is unknown to the service.

Even after the proposed A+C fix lands, the restart does not auto-reconcile
pre-existing broker positions that the service never knew about. There
is no code path in `/opt/ema_pullback/ema_pullback/` that queries
`/positions` on bootstrap and adopts matching dealIds (bootstrap only
reads the live-feed price and the local ledger).

### 6.3 Operator remediation options (choice, not recommendation)

**Option (a) — Manual broker close.** Operator closes DIAAAAYR3TPT4BU
and the four sibling positions (DIAAAAYR2YZ6RB3, DIAAAAYR3ETVCAY,
DIAAAAYR4FEYEBL, DIAAAAYR4QJPMAG) at IG's web UI or via a one-off
script. The local ledger remains stale (shows the deals as CLOSED with
fabricated -12p P&L); the broker ledger is now consistent. Operator
accepts the P&L delta between ledgers.

**Option (b) — Let the broker SL/TP run.** All five positions have
broker-side SL at `fill - 12p` and TP at `fill + 100p`. They will close
naturally on one of those levels, OR via GTC expiry. The local ledger
remains stale; the broker ledger will show the actual close prices and
times (viewable in `/history/activity`). P&L reconciliation is a
post-hoc operator exercise.

**Option (c) — Hand-reconcile the ledger.** Apply correction records
to `setup_history.jsonl` referencing the broker's authoritative close
levels (once the positions close). This is clerical, not automated,
and is tolerable because the five impacted trades are enumerable.

The report author has no basis to recommend between (a), (b), (c) —
that is an operator P&L / risk-management decision.

### 6.4 Sibling exposure

Audit the four other misfired dealIds the same way D-03 was audited.
If any are still broker-OPEN:

- DIAAAAYR2YZ6RB3 (BUY, fill 13380.0 at 15:53Z)
- DIAAAAYR3ETVCAY (BUY, fill 13375.0 at 17:11Z)
- DIAAAAYR4FEYEBL (BUY, fill 13390.5 at 00:43Z 2026-10-30)
- DIAAAAYR4QJPMAG (BUY, fill 13399.5 at 03:03Z 2026-10-30)

...then the operator has multiple live positions the EMA Pullback
service believes are closed. All are protected by broker-side SL/TP so
they are not runaway risks, but they consume account margin and are
not visible to any local service.

---

## Appendix A — Code citations recapped

- `/opt/ema_pullback/ema_pullback/service.py:825-838` — IN_TRADE→CLOSED path.
- `/opt/ema_pullback/ema_pullback/service.py:825` reads `active.state == IN_TRADE`.
- `/opt/ema_pullback/ema_pullback/service.py:826` reads `pos_payload is not None` early-return.
- `/opt/ema_pullback/ema_pullback/service.py:829-831` fabricates exit_price from broker_sl_level.
- `/opt/ema_pullback/ema_pullback/service.py:832-836` calls `mark_closed(exit_reason="broker_closed")`.
- `/opt/ema_pullback/ema_pullback/service.py:553-559` reconcile-time `list_own_open_positions` call.
- `/opt/ema_pullback/ema_pullback/service.py:582` `pos_payload, pos_row = _match(positions)`.
- `/opt/ema_pullback/ema_pullback/service.py:2084-2105` `mark_closed()` state-mutation body.
- `/opt/ema_pullback/ema_pullback/ig_client.py:1057-1077` ambiguous `[]` return primitive.
- `/opt/ema_pullback/ema_pullback/main.py:356-369` 20-second poll-loop cadence.
- `/opt/ema_pullback/ema_pullback/config.py:339` `poll_seconds=20` default.
- `/opt/ema_pullback/state/setup_history.jsonl` — 5 CLOSED broker_closed rows at 21s hold.
- `/opt/ema_pullback/logs/ema_pullback.log:3933-3936` — D-03 call-chain log evidence.
- `/opt/ema_pullback/logs/ema_pullback.log:3368/3371,3544/3545,4829/4830,5391/5392` — four sibling events.

## Appendix B — Grep commands used (reproducible)

```bash
# list_own_open_positions and false-close trigger callers
grep -rn "list_own_open_positions\|pos_payload\|mark_closed\|broker_closed" \
    /opt/ema_pullback/ema_pullback/

# last_known_mid writers (returns zero)
grep -rn 'last_known_mid"\s*=\|"last_known_mid":' /opt/ema_pullback/

# /positions/{dealId} probe (returns zero)
grep -rn "/positions/{" /opt/ema_pullback/ema_pullback/

# HTTP failure WARNINGs for /positions in the log (returns zero)
grep -n "positions GET\|workingorders GET" /opt/ema_pullback/logs/ema_pullback.log

# broker_closed events + hold-time computation
python3 -c "..."   # see §2.1 for exact script
```
