# IG authentication audit — ig_auth.py on AutoBot (REDACTED)

Host: AutoBot (REDACTED) — read-only audit.
Date: 2026-11-06.
Purpose: explain every rule in `ig_auth.py` plainly so a new bot (built on another server, no code ported) can reproduce the behaviour correctly. This copy has all server addresses replaced by REDACTED; no IDs, passwords, keys, tokens or deal references appear in either copy.

Everywhere below, line numbers refer to `/opt/tradingbot/ig_auth.py` unless a different file is named. Quotes are verbatim; indentation is preserved.

---

## 1. Where it lives

Primary source file:

- `/opt/tradingbot/ig_auth.py` — 1,026 lines.

Files `ig_auth.py` depends on at import time:

- Python package `python-dotenv` — reads `/opt/tradingbot/.env` via `load_dotenv(override=True)`.
- Python package `trading_ig` — installed at `/opt/tradingbot/venv/lib/python3.10/site-packages/trading_ig/`. The modules it touches are:
  - `trading_ig.__init__` / `trading_ig.trading_ig` — provides `IGService` (the REST client class).
  - `trading_ig.exceptions` or `trading_ig.rest` — provides `IGException`.
  - `trading_ig.rest` — provides `ApiExceededException`, and is the module `ig_auth.py` monkey-patches for (a) the `conv_resol` “Invalid frequency: MINUTE” bug and (b) the activity-paging `+` offset bug.
  - `trading_ig.utils` — also patched for `conv_resol` / `to_offset`.
- Python package `pandas` — optional, used only to normalise a DataFrame return from `fetch_accounts()`.
- Local module `telegram_alerts` — imported lazily inside `_send_fatal_auth_telegram()` to post a one-shot alert on fatal auth exit. Import failure is swallowed.

Files referred to for behaviour (not imported, but load-bearing):

- `/opt/tradingbot/deploy/systemd/autobot.service.d-auth-suspension-guard.conf` — pins `RestartPreventExitStatus=78 79` and `RestartSec=30s`. Line 42 of that file: `RestartPreventExitStatus=78 79`.
- `/opt/tradingbot/tests/unit/test_ig_auth.py` — 910 lines of tests, including `test_fatal_exit_code_matches_unit` which asserts the Python code and the systemd override agree on exit code 78.
- `/opt/tradingbot/tests/unit/test_ig_auth_apiexceeded_20261105.py` — 194 lines of tests added when `ApiExceededException` handling was fixed on 2026-11-05.

Nothing else is loaded by `ig_auth.py` itself. Everything the IG REST call touches comes from `trading_ig`.

### Environment variable names (values NOT shown)

Read at module load (lines 79–95):

```
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")
IG_API_KEY = os.getenv("IG_API_KEY")
IG_ACC_TYPE = (os.getenv("IG_ACC_TYPE", "DEMO") or "DEMO").upper()
IG_ACCOUNT_ID = (os.getenv("IG_ACCOUNT_ID") or "").strip()
IG_PRODUCT_TYPE = (os.getenv("IG_PRODUCT_TYPE") or "").strip().upper()
LEGACY_IG_ACCOUNT_TYPE = (os.getenv("IG_ACCOUNT_TYPE") or "").strip().upper()
```

Also read:

- `AUTH_REFRESH_MIN_INTERVAL_S` (line 264) — minimum seconds between `refresh_session()` network attempts. Default `60.0`.
- `IG_MAX_ACTIVITY_PAGES` (line 253) — unrelated to login; used by the monkey-patched activity pagination.

Missing / wrong values abort the process BEFORE any IG call:

- Lines 97–98:
  ```
  if not IG_USERNAME or not IG_PASSWORD or not IG_API_KEY:
      raise EnvironmentError("Missing IG_USERNAME / IG_PASSWORD / IG_API_KEY in .env")
  ```
- Lines 100–101:
  ```
  if IG_ACC_TYPE not in ("LIVE", "DEMO"):
      raise EnvironmentError("Invalid IG_ACC_TYPE — must be LIVE or DEMO")
  ```

`IG_ACCOUNT_TYPE` (without the second `_`) is a legacy name — if someone sets it to `CFD` or `SPREADBET` by mistake the module logs a warning and ignores it (lines 103–107).

---

## 2. Logging in (which addresses, which version, what is sent, what is kept)

### Which addresses

`ig_auth.py` never writes a URL itself. It passes `acc_type` to `IGService(...)` and lets `trading_ig` choose the base URL. In `trading_ig/rest.py` lines 139–142:

```
D_BASE_URL = {
    "live": "https://REDACTED/gateway/deal",
    "demo": "https://REDACTED/gateway/deal",
}
```

So:

- `IG_ACC_TYPE=LIVE` → `https://REDACTED/gateway/deal`
- `IG_ACC_TYPE=DEMO` → `https://REDACTED/gateway/deal`

The critical warning the comment on line 83 makes is:

```
# IMPORTANT: IGService acc_type is only LIVE/DEMO (endpoint), NOT CFD/SPREADBET.
```

Sub-account choice is made AFTER login — see §4.

### Which IG endpoints are called

All paths are relative to the base URL.

1. `POST /session` — login (via `IGService.create_session()`).
   - Called in `get_ig_session()` at line 737: `_session_body = ig.create_session()`.
2. `GET /accounts` — list sub-accounts (via `IGService.fetch_accounts()`).
   - Called at line 870: `raw_accounts = ig.fetch_accounts()`.
3. `PUT /session` — switch active sub-account (via `IGService.switch_account(account_id, default_account=True)`).
   - Called at line 927 (inside `switch_account()`): `ig.switch_account(account_id, default_account=True)`.

### Which version of IG login

`ig_auth.py` calls `ig.create_session()` with no `version=` argument, so it takes the library default. In `trading_ig/rest.py` line 1615:

```
def create_session(self, session=None, encryption=False, version='2'):
```

That means **IG REST API v2 login**. The response carries the session tokens `CST` and `X-SECURITY-TOKEN` in HTTP headers, not an OAuth body. No `refresh_token`/`access_token` is created or tracked (v3 would do that; `ig_auth.py` never uses v3).

`encryption=False` is also the default, so the password is sent in clear inside TLS (the broker accepts this for v2 against both demo and live endpoints).

### What is sent in the login request

`trading_ig/rest.py` line 1636 builds the body:

```
params = {"identifier": self.IG_USERNAME, "password": password}
```

Plus HTTP headers added by `IGSessionCRUD.__init__` (`trading_ig/rest.py` lines 54–58):

```
self.session.headers.update({
    "X-IG-API-KEY": self.API_KEY,
    'Content-Type': 'application/json',
    'Accept': 'application/json; charset=UTF-8'
})
```

And a `VERSION` header set per request (`trading_ig/rest.py` line 83: `session.headers.update({'VERSION': version})`). For the login call that is `VERSION: 2`.

### What is kept from the reply

Two things:

1. **CST and X-SECURITY-TOKEN** — stored on the `requests.Session` by `trading_ig.rest.handle_session_tokens()` (line 1787 of `trading_ig/rest.py`):
   ```
   if "CST" in response.headers:
       session.headers.update({'CST': response.headers['CST']})
   if "X-SECURITY-TOKEN" in response.headers:
       session.headers.update({'X-SECURITY-TOKEN': response.headers['X-SECURITY-TOKEN']})
   ```
   After this, every subsequent REST call made through the same `IGService` carries the tokens automatically.

2. **lightstreamerEndpoint** — the URL of IG's streaming data centre for this session. Pulled out of the `/session` JSON body by `ig_auth.get_ig_session()` lines 855–867:
   ```
   global _SESSION_LS_ENDPOINT
   _SESSION_LS_ENDPOINT = None
   try:
       if _session_body is not None and hasattr(_session_body, "get"):
           _endpoint_raw = _session_body.get("lightstreamerEndpoint")
           if isinstance(_endpoint_raw, str) and _endpoint_raw.strip():
               _SESSION_LS_ENDPOINT = _endpoint_raw.strip()
   except Exception as _endpoint_exc:  # pragma: no cover — defensive
       logger.warning(
           "Could not read lightstreamerEndpoint from /session body: %s",
           _endpoint_exc,
       )
       _SESSION_LS_ENDPOINT = None
   ```
   It is exposed to the streamer module by `get_lightstreamer_endpoint()` at line 908.

The REST headers `ig_auth.py` hands back to callers are built by `_build_headers()` at line 632 and the helper `_create_headers()` at line 514:

```
return {
    "CST": cst,
    "X-SECURITY-TOKEN": token,
    "Accept": "application/json; charset=UTF-8",
    "Content-Type": "application/json; charset=UTF-8",
    "X-IG-API-KEY": api_key,
}
```

`_build_headers()` then adds `X-IG-ACCOUNT-ID` at line 643 once the sub-account is chosen.

---

## 3. Staying logged in

### Keepalive / refresh

There is **none at the automatic level**. Because v2 is used:

- `trading_ig/rest.py::_check_session` (line 1692) is a no-op unless `self._valid_until` is set. `_valid_until` is only set inside `_handle_oauth()` — which only runs when the `/session` body contains an `oauthToken` field, i.e. a v3 login. So for the v2 path used here, the library never expires or refreshes the session on our behalf.
- `ig_auth.py` itself has no timer, no thread, no polling. The `(ig, headers, account_id)` tuple is cached forever in the module global `_CACHED` (line 229: `_CACHED = None`; line 904: `_CACHED = (ig, headers, account_id)`).

**Behavioural consequence:** the CST / X-SECURITY-TOKEN pair stays valid as long as IG accepts it (in practice ~6 h of inactivity or ~12 h total). When IG rejects a later call with a 401, it is the CALLER's job to trigger `refresh_session()`. `ig_auth.py` does not detect expiry proactively.

### When a refresh happens

`refresh_session()` is defined at line 959. It:

- Takes an in-process lock (`_REFRESH_LOCK`, line 265).
- Throttles to at most one network attempt every `AUTH_REFRESH_MIN_INTERVAL_S` seconds (default 60 — line 264).
- Has a second guard: `_REFRESH_INFLIGHT` (line 268). While a refresh is on the wire, concurrent callers get the prior cached session back instead of launching a parallel login.
- If both throttles pass, clears `_CACHED` to `None`, calls `get_ig_session()` to do a brand-new `create_session()`, and on failure restores the prior cache so callers keep the last good session.

The time throttle is set at attempt time (line 998: `_LAST_REFRESH_ATTEMPT = now`), NOT on success, so a burst of failing refreshes cannot bypass it.

The reasoning for this is quoted exactly in §7.

### How it notices the session has expired

**Only reactively, through callers.** `ig_auth.py` watches for `401`/`errorCode` only during the login burst inside `get_ig_session()`. After login succeeds and the tuple is cached, `ig_auth.py` doesn't inspect any further response.

Callers that use the returned `ig` object (`trade_executor`, `trade_manager`, `trades_api`, `streamer_ls`, …) see a `401` from IG on their own call, catch it, and then call `refresh_session()`. There are many such sites — e.g. `trades_api.py:2481` imports `refresh_session`, and `close_sb_now.py:50` imports it. `ig_auth.py` is agnostic about the trigger.

---

## 4. Choosing the account

After login, `get_ig_session()` calls `ig.fetch_accounts()` (line 870). The result is run through `_normalize_accounts()` (line 602), which handles the fact that the trading_ig library may return a tuple `(status, data)`, a `pandas.DataFrame`, a dict with an `"accounts"` key, a dict that IS an account, a list, or nothing — a legitimate source of brittleness the module hardens against.

`_select_account_id()` at line 658 then applies this priority (quoted exactly):

```
    """
    Priority:
    1) IG_ACCOUNT_ID (exact match)
    2) IG_PRODUCT_TYPE (SPREADBET/CFD)
    3) preferred=True
    4) first account
    """
```

1. **IG_ACCOUNT_ID forced** — if the env var is set and the exact ID exists in the list, that ID is chosen (`forced_by_env_IG_ACCOUNT_ID`). If set but not found, a WARN is logged with the available accounts and selection falls through to 2.
2. **IG_PRODUCT_TYPE** — picks the first account whose `accountType` matches (`SPREADBET` or `CFD`, case-insensitive). WARN if set but no match; falls through.
3. **`preferred=True`** flag on the account object.
4. **First account** in the list.

Once a sub-account is chosen, `get_ig_session()` calls `switch_account(ig, None, account_id)` at line 897. The switch uses `trading_ig.rest.IGService.switch_account(account_id, default_account=True)` — i.e. a `PUT /session` with `{"accountId": ..., "defaultAccount": true}`, VERSION 1 (from `trading_ig/rest.py` line 1715).

### The 412 reply

IG returns `412 Precondition Failed` when you try to switch to an account that is already active. `ig_auth.switch_account()` treats that as benign — twice over (both IGException and generic Exception branches), at lines 934–936 and 948–950:

```
if "412" in msg or "precondition" in msg_l:
    logger.info("ℹ️ switch_account returned 412 (already active) — ignoring.")
    return
```

And again for the sibling error message IG sometimes returns:

```
if "accountid-must-be-different" in msg_l:
    logger.info("ℹ️ switch_account says account must be different (already active) — ignoring.")
    return
```

Any other error from `switch_account` is logged as a warning and then **silently swallowed** — see line 898 of the caller:

```
try:
    switch_account(ig, None, account_id)
except Exception:
    pass
```

So in practice the “switch to chosen sub-account” step is best-effort: if IG refuses for any non-benign reason, the login proceeds using whichever account IG happens to think is active. The tokens / `X-IG-ACCOUNT-ID` header are still built correctly because the code trusts the ID it CHOSE, not the one IG switched to. This is a real edge case — see §8.

---

## 5. Errors recognised, and what happens for each

All error handling is concentrated in `get_ig_session()`'s `while True` login loop (lines 733–847). The three classes are:

### 5.1 `ApiExceededException` — being slowed down by IG

Caught at line 740. `trading_ig/rest.py` lines 85–88 raise this specifically when the response body contains `exceeded-api-key-allowance`:

```
if response.status_code in [401, 403]:
    if 'exceeded-api-key-allowance' in response.text:
        raise ApiExceededException()
    else:
        raise IGException(f"HTTP error: {response.status_code} {response.text}")
```

Important: `ApiExceededException` is a SIBLING of `IGException`, NOT a subclass (see §7, the 2026-11-05 comment on line 52). Before the fix this exception used to escape untyped and crash the process; systemd then restarted it immediately, entrenching the allowance block.

Behaviour now (lines 740–770):

- Uses the same ladder as the IGException allowance path: `BACKOFF_SCHEDULE = [60, 90, 120, 180]` (line 110).
- Sleeps `BACKOFF_SCHEDULE[min(attempt-1, 3)]` and retries.
- On attempt 6 or higher (`if attempt > len(BACKOFF_SCHEDULE) + 1`) it logs CRITICAL, fires a Telegram alert and raises `FatalAuthError("ApiExceededException", ...)` → process exits 78 → systemd does NOT restart.

### 5.2 `IGException` — everything else IG sends

Caught at line 771. The handler inspects the stringified exception message in this order:

1. **API-key fatal codes** (lines 779–792). Checked against `_FATAL_API_KEY_CODES` (lines 141–145):
   ```
   _FATAL_API_KEY_CODES = frozenset({
       "error.security.api-key-invalid",
       "error.security.api-key-disabled",
       "error.security.api-key-revoked",
   })
   ```
   Any match → logs CRITICAL, Telegram alert, raises `FatalAuthError` → exit 78, no restart.

2. **Allowance exceeded via IGException** (lines 795–803). Matches `error.public-api.exceeded-api-key-allowance`:
   ```
   if "error.public-api.exceeded-api-key-allowance" in msg:
       if attempt > len(BACKOFF_SCHEDULE) + 1:
           logger.error("❌ Repeated API allowance issues — giving up.")
           raise
       idx = min(attempt - 1, len(BACKOFF_SCHEDULE) - 1)
       delay = BACKOFF_SCHEDULE[idx]
       logger.warning(f"⚠️ Allowance exceeded — retrying in {delay}s.")
       time.sleep(delay)
       continue
   ```
   Five retries, then re-raises the original `IGException` (NOT `FatalAuthError`). See §8 — the exit behaviour here is inconsistent with the ApiExceededException branch that does the same thing.

3. **401 / errorCode body** (lines 807–841). If the message contains `"401"` or `"errorCode"`:
   - `_extract_ig_error_code(msg)` (line 162) pulls the `errorCode` field out of the JSON body with a regex then a JSON fallback.
   - If the code is in `_SUSPENDED_ERROR_CODES` (lines 131–135):
     ```
     _SUSPENDED_ERROR_CODES = frozenset({
         "error.security.client-suspended",
         "error.security.account-suspended",
         "error.security.account-locked",
     })
     ```
     Logs CRITICAL, Telegram alert, raises `FatalAuthError` → exit 78 → no restart.
   - Otherwise (any other 401, e.g. `error.security.invalid-details`, `error.security.oauth-token-invalid`, or an unclassified 401 with no `errorCode`): capped backoff. Uses `AUTH_BACKOFF_SCHEDULE = [30, 60, 120, 240, 300]` (line 119) and `AUTH_MAX_ATTEMPTS = 5` (line 120).
     - On attempt 5 (`if attempt >= AUTH_MAX_ATTEMPTS`): CRITICAL, Telegram, `FatalAuthError` → exit 78.
     - Before that: sleeps `_auth_backoff_seconds(attempt + 1)` and continues.

4. **Any other IGException** (lines 843–844) — logged as `❌ IG login error: ...` and re-raised untouched (ordinary exception → exit 1 → systemd DOES restart). This is the catch-all for anything the module doesn't recognise.

### 5.3 Any other Exception

Lines 845–847:

```
except Exception as e:
    logger.error(f"❌ Unexpected login error: {e}")
    raise
```

Re-raised untouched (exit 1 → systemd restart). No backoff.

### 403 handling

`ig_auth.py` never matches `"403"` in a string. 403s from IG arrive wrapped:

- If body contains `exceeded-api-key-allowance` → `trading_ig` raises `ApiExceededException` → handled under 5.1.
- Otherwise → `trading_ig` raises `IGException("HTTP error: 403 <body>")` → falls through the IG handler. If the body happens to contain an API-key fatal code, path 5.2.1 catches it. If it contains `errorCode`, the generic 401/errorCode path (5.2.3) kicks in even though it's a 403 — `"errorCode" in msg` is true. Otherwise it hits the generic catch-all and re-raises.

### “Throttled vs real login failure” — the key distinction

- **Throttled by IG** = `ApiExceededException` OR an `IGException` whose message contains `error.public-api.exceeded-api-key-allowance`. Treated as transient. Retry with the 60/90/120/180 ladder. Never fatal on first hits.
- **Real login failure** = anything else classified above (suspension/lockout, revoked key, bad password/invalid-details). The ones IG will NEVER resolve by retry are routed to `FatalAuthError` → exit 78 → systemd stays down. The ones that MIGHT resolve (ordinary 401 with no suspended-code) get up to 5 attempts, then still fatal to protect against repeated-login lockout.

The explicit rationale for the “retry on one process, exit fatally when cap hit” pattern is quoted in §7.

---

## 6. Retries — every site and how long it waits

### Ladder #1 — API allowance retries

- Defined line 110: `BACKOFF_SCHEDULE = [60, 90, 120, 180]`.
- Applies to `ApiExceededException` (line 740) and to the `IGException` allowance path (line 795).
- Retries executed on attempts 1, 2, 3, 4, 5 (all sleep then continue). On attempt 6 the loop gives up.
- Sleep selection (lines 762–763, 799–800):
  ```
  idx = min(attempt - 1, len(BACKOFF_SCHEDULE) - 1)
  delay = BACKOFF_SCHEDULE[idx]
  ```
  So: attempt 1 → 60 s wait (`BACKOFF_SCHEDULE[0]`), attempt 2 → 90 s (`[1]`), attempt 3 → 120 s (`[2]`), attempt 4 → 180 s (`[3]`), attempt 5 → 180 s (`[3]` again, clamped). Total time slept across the 5 attempts ≈ **630 s** before `FatalAuthError`.
- End-of-ladder condition `attempt > len(BACKOFF_SCHEDULE) + 1` (lines 748, 796) → triggers on the 6th iteration.

### Ladder #2 — non-suspended 401 retries

- Defined line 119: `AUTH_BACKOFF_SCHEDULE = [30, 60, 120, 240, 300]`.
- Cap defined line 120: `AUTH_MAX_ATTEMPTS = 5`.
- Applies to any 401/errorCode whose code is NOT in `_SUSPENDED_ERROR_CODES` and NOT in `_FATAL_API_KEY_CODES`.
- Delay helper at line 190:
  ```
  def _auth_backoff_seconds(attempt: int) -> int:
      if attempt <= 1:
          return 0
      idx = min(attempt - 2, len(AUTH_BACKOFF_SCHEDULE) - 1)
      return AUTH_BACKOFF_SCHEDULE[idx]
  ```
  It is called with `attempt + 1`, so for attempts 1..4 the sleeps are 30, 60, 120, 240 seconds. On attempt 5 we hit the `attempt >= AUTH_MAX_ATTEMPTS` branch and raise `FatalAuthError` BEFORE sleeping — the `300` value is never applied. Total time slept ≈ **450 s**.

### Ladder #3 — refresh_session throttle

- Defined line 264: `AUTH_REFRESH_MIN_INTERVAL_S = float(os.getenv("AUTH_REFRESH_MIN_INTERVAL_S", "60.0"))`.
- No retry — this is an ENTRY throttle. Callers invoking `refresh_session()` within 60 s of the previous attempt receive the EXISTING cached session (if any) without touching IG; else a `RuntimeError`.
- A second concurrency flag `_REFRESH_INFLIGHT` (line 268) blocks second callers for the duration of an in-flight network attempt, regardless of elapsed time. Rationale in §7.

### No implicit retries in library calls

`trading_ig.IGService` is constructed WITHOUT a `retryer=` argument (line 723), so `tenacity`-based retries at the library layer are disabled. Every REST call either succeeds, raises, or is retried by application code.

### Which exit codes bypass systemd restart

`/opt/tradingbot/deploy/systemd/autobot.service.d-auth-suspension-guard.conf:42`:

```
RestartPreventExitStatus=78 79
```

- 78 = `FATAL_AUTH_EXIT_CODE` — raised by any `FatalAuthError`, translated in `autobot.py` lines 12706–12739.
- 79 = streamer fatal (out of scope for this audit).

Any `raise` that is NOT a `FatalAuthError` exits 1 → systemd DOES restart after `RestartSec=30s`.

---

## 7. Lessons encoded in comments — quoted exactly

These are the design decisions the module records with historical context. A new bot should recreate the LOGIC, not just the text.

### 7.1 Why `load_dotenv(override=True)` (lines 34–37)

```
# override=True (2026-05-27): python-dotenv strips inline `# comment`
# text on KEY=value lines (systemd does not), so the clean dotenv parse
# overwrites any systemd-polluted environ values. See autobot.py:49
# for the full rationale.
```

### 7.2 Why `ApiExceededException` is caught separately (lines 52–61 and 741–761)

```
# 2026-11-05 — ApiExceededException is raised by trading_ig when the
# response body carries one of:
#   error.public-api.exceeded-api-key-allowance
#   error.public-api.exceeded-account-allowance
#   error.public-api.exceeded-account-trading-allowance
# It is a SIBLING of IGException, not a subclass (see
# trading_ig.rest.py). Prior get_ig_session only caught IGException,
# so an allowance-exceeded 403 on /session propagated untyped, exited
# the process with status 1, and triggered systemd Restart=always —
# producing the 2026-11-05 18:57:42 → 18:58:17 login flood.
```

```
# 2026-11-05 — ApiExceededException is NOT a subclass of
# IGException. Previously it propagated as exit=1 and
# systemd Restart=always re-issued the login seconds later,
# entrenching the allowance block. Route it through the
# same BACKOFF_SCHEDULE ladder as the IGException-wrapped
# errorCode, then raise FatalAuthError (exit 78) when the
# ladder is exhausted so systemd keeps the service DOWN.
```

### 7.3 Why the in-process retry cap exists (lines 112–120)

```
# --- Auth-failure classification (2026-07-10) ---
# In-process backoff for transient 401s that are NOT client-suspended.
# Rationale: the 09:26:53 UTC restart-loop incident showed that letting
# systemd restart at 5s intervals against IG entrenches an anti-fraud
# suspension. A capped in-process backoff keeps repeated auth failures
# on ONE process, so IG sees a well-behaved caller instead of ~2,500
# fresh logins/hour.
AUTH_BACKOFF_SCHEDULE = [30, 60, 120, 240, 300]  # seconds; last value is cap
AUTH_MAX_ATTEMPTS = 5
```

### 7.4 Why exit 78 is wired to systemd (lines 122–126)

```
# Distinct exit code for auth failures we do NOT want systemd to retry.
# The unit file's RestartPreventExitStatus is pinned to this exact value
# (see deploy/systemd/autobot.service.d/auth-suspension-guard.conf and
# tests/unit/test_ig_auth.py::test_fatal_exit_code_matches_unit).
FATAL_AUTH_EXIT_CODE = 78
```

### 7.5 Why the API-key fatal codes are terminal (lines 137–145)

```
# API-key states that never recover without an operator rotating the key.
# 2026-09-21: treat all three the same way — FatalAuthError → exit 78,
# so systemd RestartPreventExitStatus keeps the service DOWN and does
# not generate a session-create per restart.
```

### 7.6 Why FatalAuthError is used (lines 148–154)

```
class FatalAuthError(RuntimeError):
    """Raised when auth cannot succeed via retry (suspension or attempt cap).

    Callers (autobot.main) must translate this to sys.exit(FATAL_AUTH_EXIT_CODE)
    so the systemd RestartPreventExitStatus wiring keeps the service down
    until an operator intervenes.
    """
```

### 7.7 Why the lightstreamerEndpoint is captured (lines 231–239, repeated at 849–854)

```
# --- Lightstreamer endpoint captured from the /session response ---
# 2026-09-21 MARKET→PRICE migration: IG's /session body carries the
# authoritative lightstreamerEndpoint for the session's data centre.
# streamer_ls previously derived the endpoint from IG_ACC_TYPE alone,
# violating IG's documented contract that the endpoint may change.
# get_ig_session() now captures the value from ig.create_session()'s
# return payload; streamer_ls._connect_ls() reads it via
# get_lightstreamer_endpoint(). None here means the /session body did
# not carry the field — streaming callers MUST treat that as terminal.
```

### 7.8 Why the refresh throttle has both time AND inflight guards (lines 978–996)

```
# Concurrency guard: while a refresh is in flight, callers must NOT
# start a second re-auth regardless of elapsed time. The time throttle
# limits entry RATE; this flag limits CONCURRENCY. Both are needed —
# a non-fatal 401 (invalid-details / oauth-token-invalid) sends the
# in-flight caller through the 30/60/120/240/300 ladder (~12.5min),
# during which the time throttle would otherwise expire and let a
# second caller stack its own ladder on top.
```

### 7.9 Why the slot is consumed at attempt time, not success (lines 996–998)

```
# Consume slot at attempt time (not on success) so a failing burst
# cannot bypass the throttle.
_LAST_REFRESH_ATTEMPT = now
```

### 7.10 Why `refresh_session()` restores the prior cache on failure (lines 970–973)

```
On any failure the prior _CACHED value is restored so subsequent
callers keep the last-good session instead of triggering a fresh
create_session() cascade (the 2026-07-22 auth-flood defect).
```

### 7.11 Why activity pagination state is kept on the library module (lines 256–261)

```
# Paging state lives on the trading_ig.rest module (not this module) because
# ig_auth is legitimately re-imported by test fixtures (test_ig_auth.py's
# ig_auth_env autouse reload). A counter on ig_auth's own globals would be
# invisible to a fresh module object, and re-running the patch would wrap
# the already-wrapped parse_qs a second time — double-counting every page.
# Anchoring on the library module gives exactly one instance across reloads.
```

(Not login-related, but it is a durable lesson about where to put patch state when you monkey-patch a library.)

---

## 8. Things that look wrong, unused, duplicated or contradictory

Reported as observations only — not fixed.

### 8.1 Inconsistent fatal path between the two allowance branches

- `ApiExceededException` branch (lines 740–761) raises `FatalAuthError("ApiExceededException", ...)` when the ladder is exhausted → exit 78 → systemd does NOT restart.
- `IGException` allowance-exceeded branch (lines 795–803) ends with a bare `raise` → the original `IGException` propagates → exit 1 → systemd DOES restart after 30 s.

The 2026-11-05 comment at lines 52–61 explicitly calls out that the original crash-and-restart pattern entrenches allowance locks. Fixing it in the `ApiExceededException` path left the same pattern in the IGException-wrapped allowance path. Either IG wraps the allowance error into `ApiExceededException` (the current library behaviour at `trading_ig/rest.py:85-88`) — in which case the IGException branch is dead — or a library version does wrap it as IGException, in which case this branch still has the exact defect the 2026-11-05 note warns about.

### 8.2 `AUTH_BACKOFF_SCHEDULE[4] = 300` is unreachable

Line 119 comments that the last value is a cap, but with `AUTH_MAX_ATTEMPTS = 5` the code raises `FatalAuthError` on `attempt == 5` BEFORE sleeping (line 822). `_auth_backoff_seconds()` at line 190 would only clamp to index 4 (=300 s) at attempt ≥ 7. The 300 is therefore dead code — not a bug, just misleading documentation.

### 8.3 `switch_account()` failure is doubly swallowed

- Inside `switch_account()` (lines 921–956), every non-benign exception is logged as a warning and returned silently.
- In `get_ig_session()` (lines 896–899) the entire call is also wrapped in `try: ... except Exception: pass`.

If IG refuses the account switch for a reason the module doesn't recognise, the caller gets no error. The bot continues using the chosen `account_id` in its own `X-IG-ACCOUNT-ID` header while IG may actually be keeping a DIFFERENT sub-account active. This is probably fine in practice (the first account you get is usually the preferred one already) but it is not safe by construction.

### 8.4 The “benign 412 / accountid-must-be-different” block is duplicated

Lines 934–939 (inside the `IGException` branch) and lines 948–953 (inside the generic `Exception` branch) carry identical logic and messages. That is intentional per the comment at 944–946, but a future refactor is a candidate to pull it into a helper.

### 8.5 `_select_account_id()` has an unused fallback

Lines 692–695:

```
first = accounts[0]
if isinstance(first, dict):
    return first.get("accountId"), "fallback_first"
return getattr(first, "accountId", None), "fallback_first_attr"
```

The `fallback_first_attr` branch handles a non-dict `accounts[0]`, but `_normalize_accounts()` already converts DataFrames/tuples/dicts into a list of dicts (lines 602–629). The only way to reach `fallback_first_attr` is if the normaliser returned a list containing non-dict items — which it never does. Harmless but dead.

### 8.6 Session is cached forever — no built-in expiry check

`ig_auth.py` never looks at the age of `_CACHED`. If every caller is well-behaved and triggers `refresh_session()` on a 401, this is fine. If a new caller is added and forgets to, it will quietly run with stale tokens and break on first 401 from IG. There is no proactive stale-session check in this module (see §3).

### 8.7 `logger.setLevel` is never called

Lines 74–76 only call `logging.basicConfig(level=logging.INFO, ...)` IF there are no handlers on the logger. `ig_auth.py` is imported by `autobot.py` which configures logging first, so this branch is a no-op in production. Not wrong — just worth knowing when porting.

### 8.8 `IG_PRODUCT_TYPE` value normalisation is case-insensitive on input but case-sensitive on match

At line 91 the env var is `.strip().upper()`. At line 679 the match is against `str(a.get("accountType", "")).upper()`. OK, matches. But the warning log (line 682) echoes back the upper-cased string the user may not have typed. Cosmetic only.

### 8.9 `IGException` message-based classification is fragile

The classifier at line 807 uses `if "401" in msg or "errorCode" in msg`, and the suspended / api-key matchers are substring tests on the stringified exception. If `trading_ig` ever changes its exception string format (e.g. drops the raw body), every branch becomes unreachable. This is noted here only because a new bot might choose to inspect `response.status_code` and `response.json()` directly rather than string-matching the wrapped exception.

### 8.10 `.save` / `.save.1` backup files sit next to the live file

`/opt/tradingbot/ig_auth.py.save` and `/opt/tradingbot/ig_auth.py.save.1` are present in the working tree (found via `find`). They are not imported but they live right next to the live module and could confuse grep or future diff tools. Not a code issue — a hygiene one.

### 8.11 No safety on `IG_ACCOUNT_ID` typo

If `IG_ACCOUNT_ID` is set to a value that doesn't exist, `_select_account_id()` logs a WARN (line 671) and falls through to the next priority, which may silently log the bot into a DIFFERENT account than the operator intended. There is no hard-abort option. For a trading bot this is worth reconsidering in the new build — e.g. a `IG_ACCOUNT_ID_STRICT=1` flag that raises on miss.

### 8.12 Patches applied at import time cannot be disabled

Lines 507–508:

```
_apply_trading_ig_resolution_patch()
_apply_trading_ig_activity_paging_patch()
```

Both run unconditionally at import. They mutate the shared `trading_ig.rest` and `trading_ig.utils` modules. Anything else in the same process that imports `trading_ig` sees the patched behaviour. Not a login concern, but a design note for a new bot.

---

## Appendix — call sites in the current codebase

For reference when designing the new bot's caller contract:

- Primary live entry: `autobot.py:94` — `from ig_auth import get_ig_session`.
- Fatal translation: `autobot.py:12706-12739` — translates `FatalAuthError` → `sys.exit(78)`.
- Refresh callers (reactive to 401): `trades_api.py:2481`, `close_sb_now.py:50`, and many others importing `refresh_session`.
- Streaming endpoint consumer: `streamer_ls.py:1163` — `import ig_auth as _ia` to read `_ia.get_lightstreamer_endpoint()`.
- IG REST headers consumer: `signal_log_integrity.py:108`, `trade_executor.py:87`, `trade_manager.py:526`, and many more.

Note: there is a `/opt/bb_bounce/allowance_guard.py` (and a worktree copy) referenced in prior session memory. That file is on a sibling tree, is NOT imported by `ig_auth.py` on this host, and is out of scope for this audit. If `allowance_guard` is wanted in the new bot it must be rebuilt from scratch.

---

End of audit.
