# `open_sb_now.py` — IG Spread Bet open primitive (reproducible from this doc)

Host: AutoBot 161 (161.35.168.61). Read-only audit, no services or IG
calls were issued. Line numbers refer to the files as they exist on
disk today (2026-11-08).

## 1. Files touched when `open_sb_now()` places an order

1. **`/opt/tradingbot/open_sb_now.py`** — the primitive itself (114
   lines). Only public entry point: `open_sb_now(direction, epic,
   size, limit_distance, stop_distance, mode=None)`.
2. **`/opt/tradingbot/ig_auth.py`** — supplies the authenticated
   `IGService` (and therefore the `requests.Session` that carries the
   IG tokens). Primary call: `get_ig_session()`
   (`ig_auth.py:701-905`). Returns `(ig_service, headers, account_id)`
   — only `ig_service` is used by `open_sb_now.py`.
3. **`/opt/tradingbot/ownership_identity.py`** — mints the
   `dealReference` that tags the open with this host's ownership
   prefix. Primary call: `build_deal_reference(mode)`
   (`ownership_identity.py:468-487`).
4. **`/opt/tradingbot/venv/lib/python3.10/site-packages/trading_ig/rest.py`**
   — the `trading_ig` library. `open_sb_now()` bypasses
   `IGService.create_open_position` (which does not accept a
   `dealReference` kwarg) and calls `IGService._req(...)`
   (`trading_ig/rest.py:202-211`) directly on the same
   `/positions/otc` route the library uses internally. The confirm is
   then resolved through `IGService.fetch_deal_by_deal_reference(...)`
   (`trading_ig/rest.py:703-718`). The session, CST/XST tokens, and
   `VERSION` header are added to the `requests.Session` by the
   library.
5. **`/opt/tradingbot/.env`** — not imported; its values are read via
   `os.getenv` in `ig_auth.py`. The only variables consulted on this
   path are `IG_USERNAME`, `IG_PASSWORD`, `IG_API_KEY`, `IG_ACC_TYPE`
   (`LIVE`/`DEMO`), `IG_ACCOUNT_ID`, `IG_PRODUCT_TYPE`,
   `OWNERSHIP_HOST_PREFIX`. All redacted here.

### 1a. Source of `open_sb_now.py` end-to-end

```
 30:def open_sb_now(direction, epic, size, limit_distance, stop_distance,
 31:                mode: Optional[str] = None):
 32:    """Open a market Spread Bet position on IG with an ownership-tagged
 33:    dealReference.
 ...
 41:    try:
 42:        ig_service, headers, account_id = get_ig_session()
 43:        rest = ig_service
 44:
 45:        if not ig_service:
 46:            raise RuntimeError("IG authentication failed inside open_sb_now()")
 ...
 56:        deal_reference = build_deal_reference(mode or "DEFAULT")
 57:
 58:        print(
 59:            f"🟢 Opening {direction} {epic} size={size} "
 60:            f"stopDist={stop_distance} limDist={limit_distance} "
 61:            f"dealReference={deal_reference}"
 62:        )
 63:
 64:        params = {
 65:            "currencyCode": "GBP",
 66:            "direction": direction,
 67:            "epic": epic,
 68:            "expiry": "DFB",
 69:            "forceOpen": True,
 70:            "guaranteedStop": False,
 71:            "level": None,
 72:            "limitDistance": limit_distance,
 73:            "limitLevel": None,
 74:            "orderType": "MARKET",
 75:            "quoteId": None,
 76:            "size": size,
 77:            "stopDistance": stop_distance,
 78:            "stopLevel": None,
 79:            "trailingStop": False,
 80:            "trailingStopIncrement": None,
 81:            # Ownership marker. IG echoes this back on the confirm.
 82:            "dealReference": deal_reference,
 83:        }
 84:
 85:        response = rest._req("create", "/positions/otc", params, None, version="2")
 86:
 87:        if response.status_code != 200:
 88:            print(f"❌ open_sb_now() IG rejected OTC create: "
 89:                  f"HTTP {response.status_code} body={response.text[:300]}")
 90:            return None
 91:
 92:        try:
 93:            server_ref = json.loads(response.text).get("dealReference") or deal_reference
 94:        except Exception:
 95:            server_ref = deal_reference
 96:
 97:        # Resolve the deal confirmation (same route trading_ig uses).
 98:        confirm = rest.fetch_deal_by_deal_reference(server_ref)
 99:        print(f"✅ IG response: {confirm}")
 100:        return confirm
 101:
 102:    except Exception as e:
 103:        print(f"❌ open_sb_now() FAILED: {e}")
 104:        traceback.print_exc()
 105:        return None
```

## 2. The exact request that opens the position

### 2.1 Address and method

The library routes `_req("create", ...)` to `IGSessionCRUD.create()`
(`trading_ig/rest.py:79-92`):

```
 79:    def create(self, endpoint, params, session, version):
 80:        """Create = POST"""
 81:        url = self._url(endpoint)
 82:        session = self._get_session(session)
 83:        session.headers.update({'VERSION': version})
 84:        response = session.post(url, data=json.dumps(params))
 85:        logging.info(f"POST '{endpoint}', resp {response.status_code}")
 86:        if response.status_code in [401, 403]:
 87:            if 'exceeded-api-key-allowance' in response.text:
 88:                raise ApiExceededException()
 89:            else:
 90:                raise IGException(f"HTTP error: {response.status_code} {response.text}")
 91:
 92:        return response
```

`_url()` prefixes the endpoint with `BASE_URL`:

```
 75:    def _url(self, endpoint):
 76:        """Returns url from endpoint and base url"""
 77:        return self.BASE_URL + endpoint
```

`BASE_URL` is chosen by `IG_ACC_TYPE` at IGService construction
(`trading_ig/rest.py:139-174`):

```
 139:    D_BASE_URL = {
 140:        "live": "https://api.ig.com/gateway/deal",
 141:        "demo": "https://demo-api.ig.com/gateway/deal",
 142:    }
 ...
 171:            self.BASE_URL = self.D_BASE_URL[acc_type.lower()]
```

Current `/opt/tradingbot/.env` has `IG_ACC_TYPE=DEMO`, so effective
address on this box right now is:

- **Method:** `POST`
- **URL:** `https://demo-api.ig.com/gateway/deal/positions/otc`
  (switch to `https://api.ig.com/gateway/deal/positions/otc` if the
  new bot runs on a LIVE key).

### 2.2 Headers on the wire

The `requests.Session` that performs the POST is
`IGService.session`. It accumulates headers from three places.

**(a)** Set once at IGService construction
(`trading_ig/rest.py:55-59`, applied to `self.session` inside
`IGSessionCRUD.__init__`):

```
 55:        self.session.headers.update({
 56:            "X-IG-API-KEY": self.API_KEY,
 57:            'Content-Type': 'application/json',
 58:            'Accept': 'application/json; charset=UTF-8'
 59:        })
```

**(b)** Set per request by `IGSessionCRUD.create()`
(`trading_ig/rest.py:83`): `VERSION` is overwritten on every call;
`open_sb_now.py` passes `version="2"` at line 85, so the POST carries
`VERSION: 2`.

**(c)** Captured from the `/session` login response and left on the
Session for the life of the process
(`trading_ig/rest.py:1787-1798`):

```
 1787:def handle_session_tokens(response, session):
 ...
 1795:    if "CST" in response.headers:
 1796:        session.headers.update({'CST': response.headers['CST']})
 1797:    if "X-SECURITY-TOKEN" in response.headers:
 1798:        session.headers.update({'X-SECURITY-TOKEN': response.headers['X-SECURITY-TOKEN']})
```

`ig_auth.get_ig_session()` additionally switches the active account
(`ig_auth.py:896-899`, forwarded to `IGService.switch_account`
`trading_ig/rest.py:1711-1720`):

```
 1711:    def switch_account(self, account_id, default_account, session=None):
 1712:        """Switches active accounts, optionally setting the default account"""
 1713:        version = "1"
 1714:        params = {"accountId": account_id, "defaultAccount": default_account}
 1715:        endpoint = "/session"
 1716:        action = "update"
 1717:        response = self._req(action, endpoint, params, session, version)
 1718:        self._manage_headers(response)
```

Full outbound header set on `POST /positions/otc`:

| Header              | Value                                     | Source                            |
|---------------------|-------------------------------------------|-----------------------------------|
| `X-IG-API-KEY`      | REDACTED (`IG_API_KEY` env)               | `rest.py:56`                      |
| `Content-Type`      | `application/json`                        | `rest.py:57`                      |
| `Accept`            | `application/json; charset=UTF-8`         | `rest.py:58`                      |
| `VERSION`           | `2`                                       | `rest.py:83` (per-request, from `version="2"` at `open_sb_now.py:85`) |
| `CST`               | REDACTED (session cookie)                 | `rest.py:1795-1796` after `create_session()` |
| `X-SECURITY-TOKEN`  | REDACTED (session cookie)                 | `rest.py:1797-1798` after `create_session()` |

Note: `ig_auth._create_headers()` (`ig_auth.py:514-522`) and
`_build_headers()` (`ig_auth.py:632-644`) build a parallel header
dict including `X-IG-ACCOUNT-ID` and return it to the caller, but
`open_sb_now.py` uses `ig_service` (the `IGService` object), not that
dict — so the wire headers for `POST /positions/otc` are the ones on
`IGService.session` listed above. The active account is already bound
by `switch_account` (`ig_auth.py:896-899`).

### 2.3 Body — every field with the exact value sent

From `open_sb_now.py:64-83`, JSON-encoded by
`json.dumps(params)` at `trading_ig/rest.py:84`:

```json
{
  "currencyCode":          "GBP",
  "direction":             <"BUY" | "SELL">,        // caller argument
  "epic":                  <epic string>,            // caller argument
  "expiry":                "DFB",
  "forceOpen":             true,
  "guaranteedStop":        false,
  "level":                 null,
  "limitDistance":         <limit_distance>,         // caller argument
  "limitLevel":            null,
  "orderType":             "MARKET",
  "quoteId":               null,
  "size":                  <size>,                   // caller argument
  "stopDistance":          <stop_distance>,          // caller argument
  "stopLevel":             null,
  "trailingStop":          false,
  "trailingStopIncrement": null,
  "dealReference":         "<host>-<mode_code>-<epoch_ms_last10>"
}
```

Field-by-field intent:

- `currencyCode: "GBP"` — hard-coded (`open_sb_now.py:65`). GB Spread
  Bet account.
- `direction` — caller argument, must be `"BUY"` or `"SELL"` (IG REST
  contract; not validated here).
- `epic` — caller argument, IG market epic (e.g.
  `"CS.D.GBPUSD.TODAY.IP"`). The manual `__main__` runner at
  `open_sb_now.py:113` uses `"CS.D.EURUSD.TODAY.IP"`.
- `expiry: "DFB"` — hard-coded. Daily Funded Bet, the Spread Bet
  default-rolling contract (`open_sb_now.py:68`).
- `forceOpen: true` — new separate position rather than netting
  against any existing opposite-direction holding
  (`open_sb_now.py:69`).
- `guaranteedStop: false` — no premium guaranteed stop requested
  (`open_sb_now.py:70`).
- `level: null` — only used for non-MARKET orders; MARKET ignores it
  (`open_sb_now.py:71`).
- `limitDistance` — take-profit distance in IG points (same units as
  the instrument's pip; GBPUSD quotes to 10ths of a pip, so IG points
  == pips for this epic). Caller argument (`open_sb_now.py:72`).
- `limitLevel: null` — alternative absolute TP level; unused because
  distance is given (`open_sb_now.py:73`).
- `orderType: "MARKET"` — market order (`open_sb_now.py:74`).
- `quoteId: null` — not a quote-driven order (`open_sb_now.py:75`).
- `size` — Spread Bet size (currency per point); caller argument
  (`open_sb_now.py:76`).
- `stopDistance` — stop distance in IG points. Caller argument
  (`open_sb_now.py:77`).
- `stopLevel: null` — alternative absolute SL level; unused
  (`open_sb_now.py:78`).
- `trailingStop: false`, `trailingStopIncrement: null` — no trailing
  stop at open; trailing is attached post-open elsewhere
  (`open_sb_now.py:79-80`).
- `dealReference` — identity-tagged string built here, sent with the
  order; IG echoes it back on the confirm. See §2.4.

The library's public `create_open_position()`
(`trading_ig/rest.py:821-871`) does not expose `dealReference` as a
kwarg, which is why `open_sb_now.py` uses `_req()` directly. The
field is a documented part of IG's `POST /positions/otc` v2 schema
and IG accepts it when passed in the body (confirmed in production
daily by the main AutoBot).

### 2.4 How `dealReference` is built

`open_sb_now.py:56`:

```
 56:        deal_reference = build_deal_reference(mode or "DEFAULT")
```

`ownership_identity.py:468-487`:

```
 468:def build_deal_reference(mode: Optional[str], now_ms: Optional[int] = None) -> str:
 469:    """Build this host's dealReference for a new broker open.
 ...
 477:    host = host_prefix()
 478:    code = _mode_code(mode)[:_MODE_MAX] or "X"
 479:    if now_ms is None:
 480:        now_ms = int(time.time() * 1000)
 481:    epoch = str(int(now_ms))[-_EPOCH_MAX:]
 482:    ref = f"{host}{_SEP}{code}{_SEP}{epoch}"
 483:    assert len(ref) <= _IG_MAX, (
 484:        f"dealReference overflow: {ref!r} ({len(ref)} chars) — "
 485:        "shrink the entry in _MODE_CODES or lower _HOST_MAX"
 486:    )
 487:    return ref
```

Shape: `<host>-<mode_code>-<epoch_ms_last10>`, capped at IG's 30-char
limit, matching the regex `^[A-Za-z0-9_-]{1,30}$`
(`ownership_identity.py:30-47`).

- **Host prefix** (`ownership_identity.py:407-430`): the env
  `OWNERSHIP_HOST_PREFIX` if set, else `"H"` + the first octet of the
  box's primary outbound IPv4 (via a UDP probe to `8.8.8.8`;
  `ownership_identity.py:388-404`). On 161.35.168.61 this resolves to
  `H161`. A new bot on a different `/8` gets a different prefix for
  free; two bots on the same `/8` must set `OWNERSHIP_HOST_PREFIX`.
- **Mode code**: looked up in `_MODE_CODES`
  (`ownership_identity.py:53-163`); unknown modes fall back to a
  deterministic abbreviation preserving the `_L`/`_S` suffix
  (`ownership_identity.py:433-455`). For a new strategy, add a row to
  `_MODE_CODES` AND `_SYSTEM_GROUP`.
- **Epoch**: last 10 digits of `int(time.time() * 1000)`
  (`ownership_identity.py:480-481`).

For a new bot: port `ownership_identity.py` and either keep the same
scheme or replace `host_prefix()` so the new host gets a unique
prefix. Cross-bot reconcile depends on this: `is_our_reference()`
(`ownership_identity.py:490-499`) and `is_sibling_reference()`
(`ownership_identity.py:502-512`) use the prefix to decide "mine" vs
"sibling's" on a shared IG account.

## 3. How the deal is confirmed

The POST response from `POST /positions/otc` carries only
`{"dealReference": "..."}` — no fills, no deal id, no level. The
authoritative confirmation is a second REST call, pulled from
`fetch_deal_by_deal_reference()` (`trading_ig/rest.py:703-718`):

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

On the wire (confirm call):

- **Method:** `GET`
- **URL:** `https://{demo-api|api}.ig.com/gateway/deal/confirms/<dealReference>`
- **Headers:** same `requests.Session` as the POST, but
  `VERSION` overwritten to `1`
  (`trading_ig/rest.py:98`). Plus `CST`, `X-SECURITY-TOKEN`,
  `X-IG-API-KEY`, `Accept`, `Content-Type` as before.
- **Body:** none (GET; `params={}`).
- **Retry:** up to 5 attempts, 1 s apart, on HTTP 404 (IG can lag a
  moment between accepting the OTC order and exposing its
  confirmation — this is normal, not an error).

`open_sb_now.py` prefers the `dealReference` echoed back by IG in the
POST body over the one it built, because the library and IG both
treat the echo as canonical; the fallback is the ref it minted
locally (`open_sb_now.py:92-95`):

```
 92:        try:
 93:            server_ref = json.loads(response.text).get("dealReference") or deal_reference
 94:        except Exception:
 95:            server_ref = deal_reference
 96:
 97:        # Resolve the deal confirmation (same route trading_ig uses).
 98:        confirm = rest.fetch_deal_by_deal_reference(server_ref)
```

### 3.1 What the caller checks on the confirm

`open_sb_now()` returns the parsed confirm dict unchanged
(`open_sb_now.py:98-100`) — it does not itself inspect any field.
Decision logic (ACCEPTED vs REJECTED) belongs to the upstream caller.
The IG v1 `/confirms/{ref}` payload shape is:

```
{
  "date":          "2026-11-08T07:51:12.123",
  "status":        "OPEN" | "AMENDED" | "CLOSED" | ...,
  "reason":        "SUCCESS" | "MARKET_CLOSED" | "RISK_CHECK" | ...,
  "dealStatus":    "ACCEPTED" | "REJECTED",
  "epic":          "CS.D.GBPUSD.TODAY.IP",
  "expiry":        "DFB",
  "dealReference": "H161-...-....",
  "dealId":        "DIAAAAN...",
  "affectedDeals": [{"dealId": "...", "status": "OPENED"}],
  "level":         1.32345,
  "size":          1.0,
  "direction":     "BUY" | "SELL",
  "stopLevel":     1.32245,
  "limitLevel":    1.32545,
  "stopDistance":  10,
  "limitDistance": 20,
  "guaranteedStop": false,
  "trailingStop":  false,
  "profit":        null,
  "profitCurrency": null
}
```

A new bot's wrapper should branch on `dealStatus == "ACCEPTED"` (and
read `reason` on rejection for diagnostics). Example callers in this
repo:

- `/opt/tradingbot/trade_executor.py` (main AutoBot) parses the same
  shape for post-open bookkeeping.
- `/opt/bb_bounce/open_sb_now.py` on this host is a larger sibling
  (944 lines) that wraps the same primitive with quote polling,
  retry, and audit logging; the 114-line
  `/opt/tradingbot/open_sb_now.py` is the minimal reference.

## 4. Rejections, allowance errors, and auth errors

### 4.1 Non-200 on the POST — handled in `open_sb_now.py`

`open_sb_now.py:87-90`:

```
 87:        if response.status_code != 200:
 88:            print(f"❌ open_sb_now() IG rejected OTC create: "
 89:                  f"HTTP {response.status_code} body={response.text[:300]}")
 90:            return None
```

Only truncated body is logged; the function returns `None` on any
non-200. Any other exception during the flow is caught at
`open_sb_now.py:102-105` and converted to `None` with a traceback
printed to stdout:

```
 102:    except Exception as e:
 103:        print(f"❌ open_sb_now() FAILED: {e}")
 104:        traceback.print_exc()
 105:        return None
```

### 4.2 Library-level error handling — `trading_ig/rest.py`

`IGSessionCRUD.create()` raises before `open_sb_now.py` even sees the
response on two specific conditions
(`trading_ig/rest.py:86-90`):

```
 86:        if response.status_code in [401, 403]:
 87:            if 'exceeded-api-key-allowance' in response.text:
 88:                raise ApiExceededException()
 89:            else:
 90:                raise IGException(f"HTTP error: {response.status_code} {response.text}")
```

Library also raises on server problems
(`trading_ig/rest.py:220-221`):

```
 220:        if response.status_code >= 500:
 221:            raise (IGException(f"Server problem: status code: {response.status_code}, reason: {response.reason}"))
```

And on any 200 body carrying an allowance-exceeded marker
(`trading_ig/rest.py:224-225`):

```
 224:        if self._api_limit_hit(response.text):
 225:            raise ApiExceededException()
```

So `open_sb_now()`'s `except Exception` at line 102 catches:
`ApiExceededException`, `IGException` (401/403 non-allowance,
5xx server), and anything else. In all cases the function returns
`None`; upstream must retry/escalate.

### 4.3 Auth-side classification — `ig_auth.py`

`get_ig_session()` (`ig_auth.py:701-905`) classifies IG error codes
at login. The relevant sets are:

```
 131:_SUSPENDED_ERROR_CODES = frozenset({
 132:    "error.security.client-suspended",
 133:    "error.security.account-suspended",
 134:    "error.security.account-locked",
 135:})
 136:
 141:_FATAL_API_KEY_CODES = frozenset({
 142:    "error.security.api-key-invalid",
 143:    "error.security.api-key-disabled",
 144:    "error.security.api-key-revoked",
 145:})
```

Behaviour on each class (all paths live inside the login loop at
`ig_auth.py:733-847`):

- **`ApiExceededException` on `/session`** (`ig_auth.py:740-770`) —
  retried with backoff `[60, 90, 120, 180]` seconds
  (`ig_auth.py:110`). After exhausting the ladder, raises
  `FatalAuthError` → exit `78`. Historical context: before 2026-11-05
  this exception propagated as exit 1 and systemd restarted the
  process, entrenching the allowance block.
- **`error.security.api-key-{invalid,disabled,revoked}`**
  (`ig_auth.py:779-792`) — fatal immediately: `FatalAuthError`, exit
  `78`, no retry. systemd `RestartPreventExitStatus=78` keeps the
  service DOWN.
- **`error.public-api.exceeded-api-key-allowance`** in an
  `IGException` message (`ig_auth.py:795-803`) — retried with the
  same `[60, 90, 120, 180]` ladder.
- **`error.security.client-suspended` / `account-suspended` /
  `account-locked`** (`ig_auth.py:812-819`) — fatal immediately,
  `FatalAuthError`, exit `78`, Telegram alert sent via
  `_send_fatal_auth_telegram`.
- **Other 401 / unclassified 401** (`ig_auth.py:821-841`) — retried
  up to `AUTH_MAX_ATTEMPTS=5` (`ig_auth.py:120`) with per-attempt
  backoff `[30, 60, 120, 240, 300]` (`ig_auth.py:119`), then fatal
  (exit 78).
- **5xx or anything else** (`ig_auth.py:843-847`) — re-raised; the
  outer caller decides.

### 4.4 Comments in the code about what IG rejects or quirks

- `open_sb_now.py:11-18` documents the reason for bypassing
  `create_open_position()`: the public signature does not accept
  `dealReference`, so we go through `_req()` directly on the same
  internal path.
- `ownership_identity.py:30-47` enforces IG's 30-char dealReference
  limit and `^[A-Za-z0-9_-]{1,30}$` regex. `build_deal_reference()`
  carries an `assert` that would raise locally if truncation ever
  fails.
- `ig_auth.py:52-67` documents that `ApiExceededException` is a
  **sibling** of `IGException`, not a subclass, and must be caught
  separately — a regression trap that produced a login flood on
  2026-11-05.
- `ig_auth.py:383-423` monkey-patches the library's activity-paging
  cursor because IG's own `paging['next']` carries a timezone offset
  that `parse_qs` corrupts and that IG's own `/history/activity`
  v3 endpoint then 400s on. Unrelated to open, but on the same
  session.
- `ig_auth.py:271-350` monkey-patches `trading_ig.utils.conv_resol`
  so the string `"MINUTE"` doesn't hit `pandas.to_offset` and raise
  `Invalid frequency`. Historical breakage; unrelated to order
  placement but applied at the same import.
- `ig_auth.py:933-939` / `943-953`: `switch_account` returning HTTP
  412 ("already active") or the
  `accountid-must-be-different` text is treated as benign — IG says
  that when the selected account is already the live one.

## 5. Minimal reproduction for a new bot

To copy this primitive onto a new box:

1. Port **`ownership_identity.py`**, or write a minimal equivalent
   that produces a 1-30 char `[A-Za-z0-9_-]` dealReference beginning
   with a unique host prefix. The prefix must differ from every
   sibling bot sharing the IG account.
2. Port **`ig_auth.py`** (or install `trading_ig` and roll a thinner
   wrapper): the mandatory outputs are an authenticated `IGService`
   whose `requests.Session` carries valid `CST`, `X-SECURITY-TOKEN`,
   `X-IG-API-KEY`. Account selection via `IG_ACCOUNT_ID` /
   `IG_PRODUCT_TYPE=SPREADBET` must be done once at startup.
3. Copy **`open_sb_now.py`** verbatim. The body at
   `open_sb_now.py:64-83` is the IG contract; only `direction`,
   `epic`, `size`, `limitDistance`, `stopDistance` are caller inputs.
   Everything else — `currencyCode: "GBP"`, `expiry: "DFB"`,
   `forceOpen: true`, `guaranteedStop: false`, `orderType: "MARKET"`,
   `trailingStop: false`, the `null` level/limit/stop level/quoteId
   fields — is fixed by this contract.
4. Decide `IG_ACC_TYPE` per box (`LIVE` or `DEMO`); this picks the
   base URL at `trading_ig/rest.py:139-142`. No code change needed.
5. On every open: upstream code owns retry policy, `dealStatus`
   parsing from the returned confirm dict, and reconcile; the
   primitive itself returns `None` on any failure.

## 6. Production usage context

- Main AutoBot on 161 drives this primitive via
  `trade_executor.py` (see the main tree) and runs under systemd
  with `Restart=always` plus `RestartPreventExitStatus=78` to
  prevent login-flood on fatal auth errors (see
  `ig_auth.py:122-126`).
- A larger sibling, `/opt/bb_bounce/open_sb_now.py` (944 lines),
  wraps the same primitive with quote-availability checks and
  retry; the 114-line `/opt/tradingbot/open_sb_now.py` is the
  canonical minimal form the operator asked to copy.
- Secrets (`IG_USERNAME`, `IG_PASSWORD`, `IG_API_KEY`,
  `IG_ACCOUNT_ID`, `CST`, `X-SECURITY-TOKEN`) are **REDACTED**
  throughout this document.
