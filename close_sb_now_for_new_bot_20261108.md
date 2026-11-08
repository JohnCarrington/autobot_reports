# `close_sb_now.py` — IG Spread Bet close primitive (reproducible from this doc)

Host: AutoBot 161 (161.35.168.61). Read-only audit, no services or IG
calls were issued. Line numbers refer to the files as they exist on
disk today (2026-11-08).

## 1. Files touched when a close is issued

1. **`/opt/tradingbot/close_sb_now.py`** (589 lines). Three public
   entry points plus one shared implementation:

   - `get_open_positions()` (`close_sb_now.py:229-372`) — raw
     `GET /positions` call that also feeds visibility state used by
     `trade_executor`'s execution-safety gate.
   - `close_by_deal_id(deal_id, ...)`
     (`close_sb_now.py:463-497`) — "I know the dealId; close this
     exact position".
   - `close_sb_now(epic, ...)` (`close_sb_now.py:500-589`) — "I only
     know the epic; close iff there is exactly one match". Refuses
     multi-match.
   - `_close_position_by_deal(deal_id, direction, size, ...)`
     (`close_sb_now.py:379-460`) — the actual OTC DELETE call. Both
     public entry points funnel through here.

2. **`/opt/tradingbot/ig_auth.py`** — supplies the authenticated
   `IGService` and the `refresh_session()` recovery call
   (`close_sb_now.py:50`). `get_ig_session()` and `refresh_session()`
   are documented in the open-side audit; `close_sb_now.py` uses them
   verbatim.

3. **`/opt/tradingbot/close_intent_journal.py`** — append-only JSONL
   journal stamped BEFORE every OTC DELETE so the reconciler never
   mislabels a bot close as external/manual. Imported at
   `close_sb_now.py:52-59` with a graceful no-op fallback if the
   module is missing (journal failures never break trading). Writes
   `logs/close_intent.jsonl`.

4. **`/opt/tradingbot/telegram_alerts.py`** — imported lazily
   (`close_sb_now.py:565`) only when `close_sb_now()` refuses a
   multi-match close, to alert the operator. Never called on a
   successful close.

5. **`/opt/tradingbot/trade_executor.py`** — lazy-imported inside
   `get_open_positions` (`close_sb_now.py:364`) only to call
   `maybe_recover_reconcile_after_refresh()` once a `/positions`
   fetch succeeds. Not part of the close path itself.

6. **`/opt/tradingbot/venv/lib/python3.10/site-packages/trading_ig/rest.py`**
   — only `IGService.fetch_deal_by_deal_reference(...)` is called
   (`close_sb_now.py:434`). The close POST itself is NOT routed
   through `IGService.close_open_position` because the bot sends a
   narrower, dealId-only body (see §2 and §4).

## 2. The exact request that closes the position

### 2.1 Address and method

`close_sb_now.py:419-430`:

```
 419:    def _call(svc: Any) -> Any:
 420:        url = f"{svc.BASE_URL}/positions/otc"
 421:        headers = dict(svc.session.headers)
 422:        headers["VERSION"] = "1"
 423:        headers["_method"] = "DELETE"
 424:        body = {
 425:            "dealId": deal_id,
 426:            "direction": close_direction,
 427:            "orderType": "MARKET",
 428:            "size": size,
 429:        }
 430:        resp = svc.session.post(url, data=_json.dumps(body), headers=headers)
```

`svc.BASE_URL` is set by `IGService.__init__` from `IG_ACC_TYPE`
(`trading_ig/rest.py:139-174`):

```
 139:    D_BASE_URL = {
 140:        "live": "https://api.ig.com/gateway/deal",
 141:        "demo": "https://demo-api.ig.com/gateway/deal",
 142:    }
 ...
 171:            self.BASE_URL = self.D_BASE_URL[acc_type.lower()]
```

This box is on `IG_ACC_TYPE=DEMO`, so effective address is:

- **Method:** `POST` (NOT `DELETE`). IG's REST API models DELETE on
  `/positions/otc` as a POST + `_method: DELETE` header override
  because the DELETE has a JSON body.
- **URL:** `https://demo-api.ig.com/gateway/deal/positions/otc`
  (LIVE: `https://api.ig.com/gateway/deal/positions/otc`).

The library confirms this is the canonical scheme
(`trading_ig/rest.py:114-124`):

```
 114:    def delete(self, endpoint, params, session, version):
 115:        """Delete = POST"""
 116:        url = self._url(endpoint)
 117:        session = self._get_session(session)
 118:        session.headers.update({'VERSION': version})
 119:        session.headers.update({'_method': 'DELETE'})
 120:        response = session.post(url, data=json.dumps(params))
 121:        logging.info(f"DELETE (POST) '{endpoint}', resp {response.status_code}")
 122:        if '_method' in session.headers:
 123:            del session.headers['_method']
 124:        return response
```

`close_sb_now._close_position_by_deal` constructs a **local copy** of
the session headers at line 421 instead of mutating the session —
that way `_method` is scoped to this one POST and cannot leak into a
following unrelated call.

### 2.2 Headers on the wire

Local headers dict built at `close_sb_now.py:421-423`:

```
 421:        headers = dict(svc.session.headers)
 422:        headers["VERSION"] = "1"
 423:        headers["_method"] = "DELETE"
```

So the POST carries everything the authenticated `requests.Session`
already has, with `VERSION` overwritten to `1` (IG's `/positions/otc`
DELETE is only on v1) and `_method: DELETE` added. The base headers
on the session come from three places documented in the open-side
audit; the summary for the close POST:

| Header              | Value                                     | Source                            |
|---------------------|-------------------------------------------|-----------------------------------|
| `X-IG-API-KEY`      | REDACTED (`IG_API_KEY` env)               | `trading_ig/rest.py:56`           |
| `Content-Type`      | `application/json`                        | `trading_ig/rest.py:57`           |
| `Accept`            | `application/json; charset=UTF-8`         | `trading_ig/rest.py:58`           |
| `VERSION`           | `1`                                       | `close_sb_now.py:422` (overrides session default) |
| `_method`           | `DELETE`                                  | `close_sb_now.py:423` (DELETE-via-POST override) |
| `CST`               | REDACTED (session cookie)                 | `trading_ig/rest.py:1795-1796`    |
| `X-SECURITY-TOKEN`  | REDACTED (session cookie)                 | `trading_ig/rest.py:1797-1798`    |

### 2.3 Body — every field with the exact value sent

From `close_sb_now.py:424-429`, JSON-encoded at line 430:

```json
{
  "dealId":    "<IG deal id from /positions>",
  "direction": "BUY" | "SELL",
  "orderType": "MARKET",
  "size":      <float>
}
```

Fields:

- **`dealId`** (`close_sb_now.py:425`) — IG's internal deal id for
  the position being closed, e.g. `DIAAAAN...`. Resolved from a
  previous `GET /positions` call: `close_by_deal_id` uses the
  argument directly (`close_sb_now.py:485`); `close_sb_now(epic)`
  reads it off the matched position row at
  `close_sb_now.py:542-545,579`.
- **`direction`** (`close_sb_now.py:426`) — the **closing**
  direction, i.e. the **opposite** of the open's direction. Computed
  at `close_sb_now.py:487` and `close_sb_now.py:581`:
  ```
  487:            close_direction = "SELL" if open_direction == "BUY" else "BUY"
  ```
- **`orderType: "MARKET"`** (`close_sb_now.py:427`) — hard-coded.
  Close at market.
- **`size`** (`close_sb_now.py:428`) — defaults to the full open
  size, read from the position row at `close_sb_now.py:488` and
  `close_sb_now.py:582`:
  ```
  488:            size = float(pos.get("dealSize") or pos.get("size") or 1.0)
  ```
  (IG's v1 `/positions` uses `dealSize`; v2 uses `size`; the fallback
  to `1.0` is a last-resort safety for an unparseable row.)

### 2.4 Fields that are DELIBERATELY ABSENT

The public-signature library call `IGService.close_open_position`
(`trading_ig/rest.py:787-819`) sends a wider body:

```
 800:        version = "1"
 801:        params = {
 802:            "dealId": deal_id,
 803:            "direction": direction,
 804:            "epic": epic,
 805:            "expiry": expiry,
 806:            "level": level,
 807:            "orderType": order_type,
 808:            "quoteId": quote_id,
 809:            "size": size,
 810:        }
```

`close_sb_now._close_position_by_deal` deliberately does NOT use that
path, because IG rejects the dealId+epic combination. See the comment
at `close_sb_now.py:391-398`:

```
 391:    """
 392:    Close a position by deal ID.
 393:
 394:    Sends ONLY dealId + direction + orderType + size.
 395:    Must NOT include epic or expiry — IG rejects requests where both dealId
 396:    and epic are present with: validation.mutual-exclusive-value.request
 397:
 398:    Stamps `deal_id` into the close-intent journal BEFORE the OTC POST so the
```

Fields the bot does NOT send on the close POST:

- `epic` — mutually exclusive with `dealId` (IG rejects).
- `expiry` — mutually exclusive with `dealId` (IG rejects).
- `level` — only used for LIMIT closes; this bot only closes at
  MARKET.
- `quoteId` — only used for quote-driven closes.
- `timeInForce` — IG v1 `/positions/otc` DELETE for a MARKET close
  does not require it; omitted.

If a future caller needs an epic-keyed close (no dealId at hand), it
must either (a) resolve the dealId first via `GET /positions` — which
is what `close_sb_now(epic)` does internally — or (b) switch to the
library's `close_open_position()` path and NOT pass dealId. The two
cannot coexist in one body.

### 2.5 Partial close

Partial close is supported by the same code path: pass a `size` less
than the position's `dealSize` to `_close_position_by_deal`. The
helper will POST that smaller size and IG will close only that
portion, leaving the remainder as a still-open position with a new
`dealId` (the residual position).

Neither public wrapper here exposes a partial-close parameter:

- `close_by_deal_id` always sends full `dealSize` (`close_sb_now.py:488`).
- `close_sb_now(epic)` always sends full `dealSize`
  (`close_sb_now.py:582`).

The repo's scale-out / partial-close code lives in
`trade_executor.py` (referenced by `close_intent_journal.py` as
`_scale_out_50pct`); it uses the same `_close_position_by_deal`
helper and sets `intent_partial=True` on the journal stamp
(`close_sb_now.py:386,417,585`). A new bot that needs partial closes
should either call `_close_position_by_deal(deal_id, close_direction,
partial_size, intent_partial=True)` directly, or write its own
wrapper that does so.

### 2.6 Close-intent journal stamp (BEFORE the POST)

`close_sb_now.py:412-417`:

```
 412:    record_intent(
 413:        deal_id=deal_id,
 414:        path=intent_path,
 415:        expected_reason=intent_reason,
 416:        partial=intent_partial,
 417:    )
```

The journal is append-only (`close_intent_journal.py:7-39`). Order
matters: the stamp lands BEFORE the OTC POST so the reconciler, which
consults the journal when a position vanishes from IG, cannot
mislabel this close as external/manual.

If the OTC POST fails after the stamp, a retraction row is appended
(`close_sb_now.py:443,453,459`):

```
 443:            record_retraction(deal_id=deal_id, path=intent_path, error=f"{type(exc).__name__}: {exc}")
```

Trade-off is called out at `close_sb_now.py:407-411`: a crash
between stamp and POST yields a false-positive stamp for a close
that never happened. This degrades the reconciler in the safe
direction (miss an external label), not an unsafe one.

## 3. How the close is confirmed

### 3.1 Response from the DELETE POST

The initial response at `close_sb_now.py:431-436`:

```
 431:        if resp.status_code == 200:
 432:            deal_ref = resp.json().get("dealReference")
 433:            if deal_ref:
 434:                return _normalize_payload(svc.fetch_deal_by_deal_reference(deal_ref))
 435:            return resp.json()
 436:        raise Exception(resp.text)
```

- HTTP 200 → extract `dealReference` from the JSON body, then call
  `fetch_deal_by_deal_reference(deal_ref)` on the same
  `IGService` — this is the same confirm route the open path uses.
- HTTP 200 but no `dealReference` in the body → unusual; return the
  raw JSON body unchanged (defensive).
- Any non-200 → raise an exception carrying `resp.text`; the
  exception is caught at `close_sb_now.py:440` for retry/journal
  retraction.

### 3.2 The confirm GET

`fetch_deal_by_deal_reference` (`trading_ig/rest.py:703-718`):

```
 703:    def fetch_deal_by_deal_reference(self, deal_reference, session=None):
 704:        """Returns a deal confirmation for the given deal reference"""
 705:        version = "1"
 706:        params = {}
 707:        url_params = {"deal_reference": deal_reference}
 708:        endpoint = "/confirms/{deal_reference}".format(**url_params)
 709:        action = "read"
 710:        for i in range(5):
 711:            response = self._req(action, endpoint, params, session, version)
 712:            if response.status_code == 404:
 713:                logger.info("Deal reference %s not found, retrying." % deal_reference)
 714:                time.sleep(1)
 715:            else:
 716:                break
 717:        data = self.parse_response(response.text)
 718:        return data
```

On the wire (confirm):

- **Method:** `GET`
- **URL:**
  `https://{demo-api|api}.ig.com/gateway/deal/confirms/<dealReference>`
- **Headers:** same `requests.Session` as the close POST but
  `VERSION` is overwritten to `1`
  (`trading_ig/rest.py:98`). `_method` is already stripped from the
  session (it was only on the local headers dict at
  `close_sb_now.py:421`).
- **Body:** none (GET; `params={}`).
- **Retry:** up to 5 attempts, 1 s apart on HTTP 404, because IG
  sometimes lags briefly between accepting the OTC close and exposing
  its confirmation.

### 3.3 What fields the caller inspects on the confirm

`close_sb_now._close_position_by_deal` returns the parsed confirm
dict unchanged after normalisation
(`close_sb_now.py:64-68,434`):

```
 64:def _normalize_payload(response: Any) -> Any:
 65:    """Unwrap (status_code, payload) style responses."""
 66:    while isinstance(response, tuple) and len(response) == 2:
 67:        response = response[1]
 68:    return response
```

Neither `close_sb_now()` nor `close_by_deal_id()` inspects any
field of the confirm — they delegate that to the upstream caller
(`trade_executor.close_position(...)` in this repo). Fields the
upstream caller checks and that a new bot's wrapper should
branch on:

- `dealStatus` — `"ACCEPTED"` or `"REJECTED"`. The authoritative
  success/failure signal.
- `reason` — `"SUCCESS"` on accept; on reject carries codes like
  `"POSITION_NOT_AVAILABLE_TO_CLOSE"`, `"MARKET_OFFLINE"`,
  `"INSUFFICIENT_FUNDS"`, `"CLOSING_ONLY_TRADES_ACCEPTED_ON_THIS_ACCOUNT"`.
- `dealId` — IG's id for this close ticket. Different from the open's
  `dealId` (which was closed).
- `affectedDeals` — list of `{dealId, status: "DELETED"|"AMENDED"}`.
  On a full close this is a single `DELETED`; on a partial close the
  original position appears as `AMENDED` with a residual `dealId`.
- `level` — the level the close filled at.
- `size` — size actually closed (may differ from requested if IG
  partially filled).
- `profit`, `profitCurrency` — realised P&L on the closed portion.

Example rejection shape: `{"dealStatus":"REJECTED", "reason":
"MARKET_OFFLINE", "dealReference":"H161-...", "dealId": "...", ...}`.

## 4. Rejections, allowance errors, and auth errors

### 4.1 Non-200 on the close POST — handled in `close_sb_now.py`

`_close_position_by_deal` raises on any non-200
(`close_sb_now.py:436`), caught at line 440:

```
 438:    try:
 439:        return _call(ig_service)
 440:    except Exception as exc:
 441:        if not _looks_like_client_token_invalid(exc):
 442:            logger.error(f"_close_position_by_deal failed for {deal_id}: {exc}")
 443:            record_retraction(deal_id=deal_id, path=intent_path, error=f"{type(exc).__name__}: {exc}")
 444:            return None
```

Two paths from there:

- **Not a token-invalid error** → log, append a retraction row,
  return `None`. The journal retraction ensures the reconciler will
  not treat the un-closed position as bot-closed if a later
  `/positions` sweep still shows it.
- **Token-invalid error** → attempt one session refresh and retry
  (`close_sb_now.py:446-460`):

  ```
   446:        logger.warning(
   447:            f"_close_position_by_deal: token invalid for {deal_id}; refreshing session and retrying once..."
   448:        )
   449:        try:
   450:            refresh_session()
   451:            ig_service, _, _ = get_ig_session()
   452:            if ig_service is None:
   453:                record_retraction(deal_id=deal_id, path=intent_path, error="no_ig_session_after_refresh")
   454:                return None
   455:            # Retry keeps the original intent stamp valid — no re-stamp.
   456:            return _call(ig_service)
   457:        except Exception as exc2:
   458:            logger.error(f"_close_position_by_deal failed for {deal_id} after refresh: {exc2}")
   459:            record_retraction(deal_id=deal_id, path=intent_path, error=f"post_refresh:{type(exc2).__name__}: {exc2}")
   460:            return None
  ```

The intent stamp is NOT rewritten on retry — the deal_id is the same
and the journal is append-only (`close_sb_now.py:455`).

### 4.2 Token-invalid classifier

`_looks_like_client_token_invalid` (`close_sb_now.py:78-95`)
pattern-matches the error string and any `errorCode` attribute:

```
 78:def _looks_like_client_token_invalid(exc: Exception) -> bool:
 79:    msg = _exc_text(exc).lower()
 80:
 81:    if "client-token-invalid" in msg:
 82:        return True
 83:    if " 401 " in f" {msg} " or "unauthorized" in msg:
 84:        return True
 85:    if "security" in msg and "token" in msg and "invalid" in msg:
 86:        return True
 87:
 88:    try:
 89:        code = getattr(exc, "errorCode", None) or getattr(exc, "error_code", None)
 90:        if isinstance(code, str) and "client-token-invalid" in code.lower():
 91:            return True
 92:    except Exception:
 93:        pass
 94:
 95:    return False
```

Catches:
- `error.security.client-token-invalid` (the common 401 on an expired
  session).
- Any error string containing " 401 " or "unauthorized".
- The combined substring pattern "security … token … invalid".
- Structured `errorCode` / `error_code` attributes on the exception
  object.

### 4.3 Position-visibility failure modes (close via epic)

`close_sb_now(epic)` calls `get_open_positions()` first
(`close_sb_now.py:526-534`):

```
 526:    positions = get_open_positions()
 527:    if positions is None:
 528:        # API failure — surface the ambiguity to the caller rather than
 529:        # falling through to a "no matches" branch that reads like success.
 530:        logger.warning(f"close_sb_now: IG position fetch failed for epic={epic} — refusing to act")
 531:        return None
 532:    if not positions:
 533:        logger.info(f"close_sb_now: no open positions found for epic={epic}")
 534:        return None
```

Three-state visibility model explicitly documented at
`close_sb_now.py:16-33`:

- `None` → UNKNOWN (API failure). Caller MUST NOT act. `close_sb_now`
  returns `None`.
- `[]` → EMPTY. Nothing to close; return `None`.
- `[...]` → POSITIONS. Proceed to match.

### 4.4 Multi-match refusal

`close_sb_now(epic)` explicitly refuses when the epic has more than
one open position and no dealId was supplied
(`close_sb_now.py:551-576`):

```
 551:    if len(matches) > 1:
 552:        # MULTI-MATCH REFUSAL. Do not pick one; do not close any.
 ...
 558:        logger.warning(
 559:            "[close_sb_now] REFUSED multi-match on epic=%s: %d positions [%s]. "
 560:            "Caller supplied no dealId — cannot safely disambiguate. "
 ...
 564:        try:
 565:            from telegram_alerts import send_telegram_message
 566:            send_telegram_message(
 567:                f"⚠️ <b>close_sb_now REFUSED</b>\n"
 ...
 573:            )
```

Historical context at `close_sb_now.py:513-514`: this behaviour fixes
the 2026-08-26 wrong-deal close; the prior version silently closed
every match.

### 4.5 `GET /positions` (visibility fetch) error handling

`get_open_positions` has its own three-way error path
(`close_sb_now.py:264-342`):

- **401 Unauthorized** (`close_sb_now.py:277-289`) — refresh the IG
  session once and retry the GET. On refresh failure: record UNKNOWN,
  return `None`.
- **Persistent HTTP 500** (`close_sb_now.py:292-331`) — after
  `GET_OPEN_POSITIONS_REFRESH_AFTER` consecutive failures (env;
  default 3, `close_sb_now.py:115`) refresh the session and retry
  once. `ig_auth.refresh_session`'s own 60 s throttle guarantees this
  cannot cascade. If the refresh+retry still returns non-200, record
  UNKNOWN, return `None`.
- **Other non-200** (`close_sb_now.py:332-334`) — record UNKNOWN,
  return `None`. The response body is logged truncated to 512 bytes
  at `close_sb_now.py:253-262`:

  ```
   253:    def _log_body_if_available(resp: Any, label: str) -> None:
   254:        try:
   255:            body = (resp.text or "")[:512] if resp is not None else ""
   256:            if body:
   257:                logger.warning(
   258:                    "get_open_positions: %s response body (truncated): %s",
   259:                    label, body,
   260:                )
   261:        except Exception:
   262:            pass
  ```

- **Unparseable JSON / missing `positions` list**
  (`close_sb_now.py:343-347`) — UNKNOWN, `None`.

The UNKNOWN state is sticky until the next successful 200; readers
consult `positions_state_visible(max_age_s=60)`
(`close_sb_now.py:140-153`) and `trade_executor`'s execution gate
refuses to open NEW positions while the state is UNKNOWN.

### 4.6 Comments in the code about what IG rejects

- `close_sb_now.py:391-398` — dealId + epic in the same body →
  `validation.mutual-exclusive-value.request`. The bot never sends
  both.
- `close_sb_now.py:16-42` — three-state visibility model and the two
  2026-10-19 session-recovery paths (401 immediate refresh; 500
  refresh after 3 consecutive failures).
- `close_sb_now.py:407-411` — intent stamp before OTC is the safe
  failure direction (worst case: false-positive stamp).
- `close_sb_now.py:11-14` — explicitly avoids
  `ig_service.fetch_open_positions()` because some trading_ig
  versions raise `ValueError: columns cannot be a set` on its
  DataFrame path.
- `close_sb_now.py:510-520` — rationale for refusing multi-match
  epic-closes; links to `reports/close_sb_now_dealid_collision_fix_20260826.md`.
- `close_sb_now.py:34-39` — recovery context: `refresh_session` is
  throttled by `ig_auth` to one re-auth per 60 s, so the 500 refresh
  path cannot stampede.

## 5. Minimal reproduction for a new bot

To copy this primitive onto a new box:

1. Port **`ig_auth.py`** (or install `trading_ig` and roll a thinner
   wrapper): the mandatory outputs are an authenticated `IGService`
   whose `requests.Session` carries valid `CST`, `X-SECURITY-TOKEN`,
   `X-IG-API-KEY`, and a working `refresh_session()` with its own
   rate-limit.
2. Port **`close_intent_journal.py`** (or write a minimal equivalent
   with `record_intent` / `record_retraction` / `has_recent_intent`).
   If the reconciler does not need it, swap the imports at
   `close_sb_now.py:52-59` for the no-op fallbacks already defined
   there — the trading path still works.
3. Copy **`close_sb_now.py`** verbatim. The authoritative constants
   are:
   - URL: `{BASE_URL}/positions/otc`
   - Method: POST with `_method: DELETE` header
   - `VERSION: 1` header (override, library default is 2)
   - Body: exactly `{dealId, direction, orderType="MARKET", size}` —
     NO `epic`, NO `expiry`, NO `level`, NO `quoteId`,
     NO `timeInForce`
   - Confirm: `GET /confirms/<dealReference>` with up to 5 404
     retries, VERSION=1
4. Partial close: call `_close_position_by_deal(deal_id,
   close_direction, partial_size, intent_partial=True)` with a
   `size` strictly less than the open's `dealSize`. IG will leave the
   residual as an open position with a new `dealId`.
5. Decide `IG_ACC_TYPE` per box (`LIVE` or `DEMO`); this picks the
   base URL at `trading_ig/rest.py:139-142`. No code change needed.
6. On every close: upstream code owns retry policy beyond
   token-invalid (one in-primitive retry), `dealStatus` parsing from
   the returned confirm dict, and reconcile; the primitive itself
   returns `None` on any failure and leaves a retraction row in the
   journal.

## 6. Production usage context

- Main AutoBot on 161 drives this primitive via
  `trade_executor.close_position(pos_key=...)` for normal exits and
  via `close_by_deal_id` for dealId-keyed exits. Scale-out /
  partial-close callers set `intent_partial=True` in the journal
  stamp.
- A sibling primitive, `/opt/bb_bounce/close_sb_now.py` (432 lines),
  exists on the same host but belongs to the standalone BB Bounce
  service. The 589-line `/opt/tradingbot/close_sb_now.py` is the
  canonical primitive the operator asked to copy for a new bot.
- Secrets (`IG_USERNAME`, `IG_PASSWORD`, `IG_API_KEY`,
  `IG_ACCOUNT_ID`, `CST`, `X-SECURITY-TOKEN`) are **REDACTED**
  throughout this document.
