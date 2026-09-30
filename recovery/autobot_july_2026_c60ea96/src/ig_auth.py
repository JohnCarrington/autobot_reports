#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ig_auth.py — resilient, version-agnostic IGService authentication with session caching

Returns: (ig_service, headers, account_id)

This version:
- Uses IGService (required for preload + Lightstreamer)
- Supports multiple trading_ig versions
- Extracts CST/XST tokens safely from multiple locations
- Normalizes fetch_accounts() outputs (tuple/dict/list/df)
- Handles API allowance throttling with correct backoff indexing
- Switches account when necessary (ignores benign errors)
- ✅ Respects IG_ACCOUNT_ID (force specific sub-account, e.g. SPREADBET)
- ✅ Supports IG_PRODUCT_TYPE fallback (SPREADBET or CFD)
- Provides canonical public APIs: get_ig_session(), switch_account(), refresh_session()
- Provides canonical private helper: _create_headers(api_key, cst, token)

PRE-CHECK (Continual Errors Ledger):
- #83 .env must be loaded before env-dependent modules: satisfied (load_dotenv first).
- #88 Token extraction is version-agnostic: satisfied (_extract_tokens()).
- #19 fetch_accounts() may return tuple/dict/list/df: satisfied (_normalize_accounts()).
- #22/#86 ValueError: Invalid frequency: MINUTE: FIXED via trading_ig conv_resol/to_offset monkeypatch.
"""

import os
import time
import logging
import threading
from dotenv import load_dotenv

# Ensure environment is loaded BEFORE any imports that rely on env vars.
# override=True (2026-05-27): python-dotenv strips inline `# comment`
# text on KEY=value lines (systemd does not), so the clean dotenv parse
# overwrites any systemd-polluted environ values. See autobot.py:49
# for the full rationale.
load_dotenv(override=True)

# Optional pandas import (fetch_accounts normalization)
try:
    import pandas as pd
except Exception:
    pd = None  # gracefully fallback

# --- trading_ig imports (version agnostic) ---
try:
    from trading_ig.exceptions import IGException  # newer
except Exception:
    from trading_ig.rest import IGException  # older

try:
    from trading_ig import IGService
except Exception:
    from trading_ig.trading_ig import IGService  # fallback for older installs

logger = logging.getLogger("AutoBot")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# --- Environment Variables (canonical names) ---
IG_USERNAME = os.getenv("IG_USERNAME")
IG_PASSWORD = os.getenv("IG_PASSWORD")
IG_API_KEY = os.getenv("IG_API_KEY")

# IMPORTANT: IGService acc_type is only LIVE/DEMO (endpoint), NOT CFD/SPREADBET.
IG_ACC_TYPE = (os.getenv("IG_ACC_TYPE", "DEMO") or "DEMO").upper()

# Optional: force specific sub-account (SpreadBet/CFD account id)
IG_ACCOUNT_ID = (os.getenv("IG_ACCOUNT_ID") or "").strip()

# Optional: choose by product type if account id not given
# Expected values: SPREADBET or CFD (case-insensitive)
IG_PRODUCT_TYPE = (os.getenv("IG_PRODUCT_TYPE") or "").strip().upper()

# Backwards/legacy env var sometimes causes confusion — do NOT use it as IGService acc_type.
# If you accidentally set IG_ACCOUNT_TYPE=CFD, it should not break login.
LEGACY_IG_ACCOUNT_TYPE = (os.getenv("IG_ACCOUNT_TYPE") or "").strip().upper()

if not IG_USERNAME or not IG_PASSWORD or not IG_API_KEY:
    raise EnvironmentError("Missing IG_USERNAME / IG_PASSWORD / IG_API_KEY in .env")

if IG_ACC_TYPE not in ("LIVE", "DEMO"):
    raise EnvironmentError("Invalid IG_ACC_TYPE — must be LIVE or DEMO")

if LEGACY_IG_ACCOUNT_TYPE and LEGACY_IG_ACCOUNT_TYPE not in ("LIVE", "DEMO"):
    logger.warning(
        f"⚠️ IG_ACCOUNT_TYPE='{LEGACY_IG_ACCOUNT_TYPE}' is NOT used for IGService acc_type. "
        "Use IG_ACC_TYPE=LIVE/DEMO. Use IG_ACCOUNT_ID (or IG_PRODUCT_TYPE=SPREADBET/CFD) to choose sub-account."
    )

# --- Retry delays for API allowance errors ---
BACKOFF_SCHEDULE = [60, 90, 120, 180]  # seconds

# --- Auth-failure classification (2026-07-10) ---
# In-process backoff for transient 401s that are NOT client-suspended.
# Rationale: the 09:26:53 UTC restart-loop incident showed that letting
# systemd restart at 5s intervals against IG entrenches an anti-fraud
# suspension. A capped in-process backoff keeps repeated auth failures
# on ONE process, so IG sees a well-behaved caller instead of ~2,500
# fresh logins/hour.
AUTH_BACKOFF_SCHEDULE = [30, 60, 120, 240, 300]  # seconds; last value is cap
AUTH_MAX_ATTEMPTS = 5

# Distinct exit code for auth failures we do NOT want systemd to retry.
# The unit file's RestartPreventExitStatus is pinned to this exact value
# (see deploy/systemd/autobot.service.d/auth-suspension-guard.conf and
# tests/unit/test_ig_auth.py::test_fatal_exit_code_matches_unit).
FATAL_AUTH_EXIT_CODE = 78

# Marker codes we treat as "manual intervention required — do NOT retry".
# Anything IG has *told us* is a lockout / suspension / decommission belongs
# here; those states never resolve by trying again.
_SUSPENDED_ERROR_CODES = frozenset({
    "error.security.client-suspended",
    "error.security.account-suspended",
    "error.security.account-locked",
})


class FatalAuthError(RuntimeError):
    """Raised when auth cannot succeed via retry (suspension or attempt cap).

    Callers (autobot.main) must translate this to sys.exit(FATAL_AUTH_EXIT_CODE)
    so the systemd RestartPreventExitStatus wiring keeps the service down
    until an operator intervenes.
    """

    def __init__(self, error_code: str, message: str, attempts: int):
        super().__init__(message)
        self.error_code = error_code
        self.attempts = attempts


def _extract_ig_error_code(msg: str) -> str:
    """Pull the `errorCode` field out of an IG JSON error payload.

    IG's 401 body is `{"errorCode":"error.security.client-suspended"}`.
    The trading_ig library wraps that into `HTTP error: 401 <body>`, so we
    parse the JSON substring rather than the surrounding prefix. Returns
    "" when no code is found — callers treat that as an unclassified 401.
    """
    if not msg:
        return ""
    import json
    import re

    # Fast path: substring match on the canonical prefix.
    m = re.search(r'"errorCode"\s*:\s*"([^"]+)"', msg)
    if m:
        return m.group(1)
    # Fallback: try to locate any {...} JSON body and parse it.
    try:
        start = msg.index("{")
        end = msg.rindex("}") + 1
        payload = json.loads(msg[start:end])
        code = payload.get("errorCode") or ""
        return str(code)
    except (ValueError, json.JSONDecodeError):
        return ""


def _auth_backoff_seconds(attempt: int) -> int:
    """Return the seconds to sleep before attempt `attempt` (1-indexed).

    Attempt 1 has no prior backoff; the schedule kicks in from attempt 2.
    """
    if attempt <= 1:
        return 0
    idx = min(attempt - 2, len(AUTH_BACKOFF_SCHEDULE) - 1)
    return AUTH_BACKOFF_SCHEDULE[idx]


def _send_fatal_auth_telegram(error_code: str, attempts: int) -> None:
    """One-shot Telegram alert on fatal auth exit. Never re-raises."""
    try:
        from telegram_alerts import send_telegram_message
    except Exception:
        return
    if error_code in _SUSPENDED_ERROR_CODES:
        body = (
            "🚨 <b>IG account suspended</b> — manual intervention required, "
            f"service will NOT self-restart.\n"
            f"errorCode: <code>{error_code}</code>\n"
            f"Exit code: {FATAL_AUTH_EXIT_CODE} (systemd Restart prevented)."
        )
    else:
        body = (
            "🚨 <b>IG auth failed — retry cap reached</b>, service will NOT "
            "self-restart.\n"
            f"errorCode: <code>{error_code or 'unknown'}</code>\n"
            f"attempts: {attempts}\n"
            f"Exit code: {FATAL_AUTH_EXIT_CODE}."
        )
    try:
        send_telegram_message(body, wait=True)
    except Exception:
        pass


# --- Singleton session cache ---
_CACHED = None

# --- trading_ig resolution patch state ---
_RESOLUTION_PATCHED = False

# --- refresh_session throttle state (2026-07-23 auth-flood fix) ---
AUTH_REFRESH_MIN_INTERVAL_S = float(os.getenv("AUTH_REFRESH_MIN_INTERVAL_S", "60.0"))
_REFRESH_LOCK = threading.Lock()
_LAST_REFRESH_ATTEMPT = 0.0
_REFRESH_INFLIGHT_PRIOR = None
_REFRESH_INFLIGHT = False


# -----------------------------------------------------------
# Continual Errors Ledger #22/#86:
# Patch trading_ig conv_resol / to_offset so "MINUTE" doesn't hit pandas.to_offset
# -----------------------------------------------------------
def _apply_trading_ig_resolution_patch():
    """
    Fix for:
      ValueError: Invalid frequency: MINUTE

    Cause:
      Some trading_ig builds route IG resolution strings (e.g. "MINUTE") into pandas offset parsing.

    Strategy:
    - Override trading_ig.utils.conv_resol and trading_ig.rest.conv_resol to return IG strings
      without calling pandas offsets.
    - Optionally patch trading_ig.utils.to_offset to map "MINUTE" -> "1min" if invoked.
    """
    global _RESOLUTION_PATCHED
    if _RESOLUTION_PATCHED:
        return

    ig_utils = None
    ig_rest = None

    try:
        import trading_ig.utils as ig_utils  # type: ignore
    except Exception:
        ig_utils = None

    try:
        import trading_ig.rest as ig_rest  # type: ignore
    except Exception:
        ig_rest = None

    def _safe_conv_resol(resolution):
        if resolution is None:
            return resolution
        r = str(resolution).strip()
        if not r:
            return resolution

        ru = r.upper()

        # Keep canonical IG request strings unchanged
        if ru in ("MINUTE", "HOUR", "DAY", "WEEK", "MONTH"):
            return ru

        # For any other inputs, return uppercase without pandas validation
        return ru

    # Patch conv_resol in utils
    try:
        if ig_utils is not None and hasattr(ig_utils, "conv_resol"):
            ig_utils.conv_resol = _safe_conv_resol  # type: ignore
    except Exception:
        pass

    # Patch conv_resol in rest (some versions import/alias it there)
    try:
        if ig_rest is not None and hasattr(ig_rest, "conv_resol"):
            ig_rest.conv_resol = _safe_conv_resol  # type: ignore
    except Exception:
        pass

    # Patch to_offset defensively (only if present)
    try:
        if ig_utils is not None and hasattr(ig_utils, "to_offset"):
            _orig_to_offset = ig_utils.to_offset  # type: ignore

            def _to_offset_patched(freq):
                try:
                    if isinstance(freq, str) and freq.strip().upper() == "MINUTE":
                        return _orig_to_offset("1min")
                except Exception:
                    pass
                return _orig_to_offset(freq)

            ig_utils.to_offset = _to_offset_patched  # type: ignore
    except Exception:
        pass

    _RESOLUTION_PATCHED = True
    logger.debug("Applied trading_ig resolution patch (#22/#86).")


# Apply patch as early as possible (import-time)
_apply_trading_ig_resolution_patch()


# -----------------------------------------------------------
# Canonical header helper (required by your architecture)
# -----------------------------------------------------------
def _create_headers(api_key: str, cst: str, token: str) -> dict:
    """Canonical helper: build base headers from api_key + CST + X-SECURITY-TOKEN."""
    return {
        "CST": cst,
        "X-SECURITY-TOKEN": token,
        "Accept": "application/json; charset=UTF-8",
        "Content-Type": "application/json; charset=UTF-8",
        "X-IG-API-KEY": api_key,
    }


# -----------------------------------------------------------
# Helpers for token extraction
# -----------------------------------------------------------
def _headers_from_requests_session(ig) -> dict:
    """Extract CST/XST tokens directly from IGService underlying requests session headers."""
    try:
        sess = getattr(getattr(ig, "crud_session", None), "session", None)
        if not sess:
            return {}
        headers = getattr(sess, "headers", {}) or {}
        norm = {str(k).upper(): v for k, v in headers.items()}
        if "CST" in norm and "X-SECURITY-TOKEN" in norm:
            return {"CST": norm["CST"], "X-SECURITY-TOKEN": norm["X-SECURITY-TOKEN"]}
        return {}
    except Exception:
        return {}


def _extract_tokens(ig) -> dict:
    """
    Extract CST/XST tokens from multiple possible IGService attributes, depending on version.

    Order:
    1) requests session headers
    2) ig.session.auth_data
    3) ig.auth_data
    4) ig.session_data
    5) legacy client_token/security_token attributes
    """
    # 1) requests session
    t = _headers_from_requests_session(ig)
    if t:
        return t

    # 2) ig.session.auth_data
    try:
        sess = getattr(ig, "session", None)
        ad = getattr(sess, "auth_data", None)
        if isinstance(ad, dict):
            cst = ad.get("client_token") or ad.get("CST")
            xst = ad.get("security_token") or ad.get("X-SECURITY-TOKEN")
            if cst and xst:
                return {"CST": cst, "X-SECURITY-TOKEN": xst}
    except Exception:
        pass

    # 3) ig.auth_data
    try:
        ad = getattr(ig, "auth_data", None)
        if isinstance(ad, dict):
            cst = ad.get("client_token") or ad.get("CST")
            xst = ad.get("security_token") or ad.get("X-SECURITY-TOKEN")
            if cst and xst:
                return {"CST": cst, "X-SECURITY-TOKEN": xst}
    except Exception:
        pass

    # 4) ig.session_data (legacy)
    try:
        sd = getattr(ig, "session_data", None)
        if isinstance(sd, dict):
            cst = sd.get("client_token") or sd.get("CST")
            xst = sd.get("security_token") or sd.get("X-SECURITY-TOKEN")
            if cst and xst:
                return {"CST": cst, "X-SECURITY-TOKEN": xst}
    except Exception:
        pass

    # 5) Legacy direct attrs
    cst = getattr(ig, "client_token", None)
    xst = getattr(ig, "security_token", None)
    if cst and xst:
        return {"CST": cst, "X-SECURITY-TOKEN": xst}

    return {}


def _normalize_accounts(result):
    """Normalize fetch_accounts() output into a list of dicts."""
    data = result

    # tuple(status, data)
    if isinstance(data, tuple) and len(data) == 2:
        _, data = data

    # DataFrame
    if pd is not None and isinstance(data, pd.DataFrame):
        try:
            return data.to_dict(orient="records")
        except Exception:
            return []

    # dict
    if isinstance(data, dict):
        if "accounts" in data and isinstance(data["accounts"], list):
            return list(data["accounts"])
        if "accountId" in data:
            return [data]
        return []

    # list
    if isinstance(data, list):
        return data

    return []


def _build_headers(ig, account_id: str) -> dict:
    """Construct REST headers including CST/XST tokens + account id."""
    tokens = _extract_tokens(ig)
    cst = tokens.get("CST")
    xst = tokens.get("X-SECURITY-TOKEN")

    if not cst or not xst:
        logger.error("Token extraction failed — unable to locate CST/XST in IGService session.")
        raise RuntimeError("Login succeeded but CST/XST not found.")

    headers = _create_headers(IG_API_KEY, cst, xst)
    headers["X-IG-ACCOUNT-ID"] = account_id
    return headers


def _summarize_accounts(accounts):
    parts = []
    for a in accounts:
        if not isinstance(a, dict):
            continue
        parts.append(
            f"id={a.get('accountId')} type={a.get('accountType')} name={a.get('accountName')} preferred={a.get('preferred')}"
        )
    return " | ".join(parts)


def _select_account_id(accounts):
    """
    Priority:
    1) IG_ACCOUNT_ID (exact match)
    2) IG_PRODUCT_TYPE (SPREADBET/CFD)
    3) preferred=True
    4) first account
    """
    # 1) force by account id
    if IG_ACCOUNT_ID:
        for a in accounts:
            if isinstance(a, dict) and str(a.get("accountId")) == IG_ACCOUNT_ID:
                return IG_ACCOUNT_ID, "forced_by_env_IG_ACCOUNT_ID"
        logger.warning(
            f"⚠️ IG_ACCOUNT_ID={IG_ACCOUNT_ID} was set but not found in fetch_accounts(). "
            f"Available: {_summarize_accounts(accounts)}"
        )

    # 2) choose by product type
    if IG_PRODUCT_TYPE:
        for a in accounts:
            if isinstance(a, dict) and str(a.get("accountType", "")).upper() == IG_PRODUCT_TYPE:
                return a.get("accountId"), f"matched_IG_PRODUCT_TYPE={IG_PRODUCT_TYPE}"
        logger.warning(
            f"⚠️ IG_PRODUCT_TYPE={IG_PRODUCT_TYPE} was set but no matching accountType found. "
            f"Available: {_summarize_accounts(accounts)}"
        )

    # 3) preferred
    for a in accounts:
        if isinstance(a, dict) and a.get("preferred", False):
            return a.get("accountId"), "preferred_true"

    # 4) first
    first = accounts[0]
    if isinstance(first, dict):
        return first.get("accountId"), "fallback_first"
    return getattr(first, "accountId", None), "fallback_first_attr"


# -----------------------------------------------------------
# Public API (canonical)
# -----------------------------------------------------------
def get_ig_session():
    """
    Returns singleton (ig_service, headers, account_id).

    On first call:
    - create IGService(...)
    - login with retries on API allowance issues
    - choose account (IG_ACCOUNT_ID / IG_PRODUCT_TYPE / preferred / first)
    - switch account if required
    - extract CST/XST tokens
    - build REST headers
    """
    global _CACHED

    # Ensure patch is active before any trading_ig REST calls (#22/#86)
    _apply_trading_ig_resolution_patch()

    if _CACHED:
        return _CACHED

    ig = IGService(
        username=IG_USERNAME,
        password=IG_PASSWORD,
        api_key=IG_API_KEY,
        acc_type=IG_ACC_TYPE,
    )

    attempt = 0
    last_auth_code = ""
    while True:
        attempt += 1
        try:
            logger.info(f"🔑 IGService.create_session() attempt {attempt} ({IG_ACC_TYPE}) …")
            ig.create_session()
            logger.info("✅ IG login OK (IGService session established).")
            break
        except IGException as e:
            msg = str(e)

            # Common "bad key" case: fail fast (no point retrying a wrong key)
            if "error.security.api-key-invalid" in msg or "api-key-invalid" in msg:
                logger.error(f"❌ API key invalid: {e}")
                raise

            # Allowance exceeded backoff (server rate-limit, not an auth failure)
            if "error.public-api.exceeded-api-key-allowance" in msg:
                if attempt > len(BACKOFF_SCHEDULE) + 1:
                    logger.error("❌ Repeated API allowance issues — giving up.")
                    raise
                idx = min(attempt - 1, len(BACKOFF_SCHEDULE) - 1)
                delay = BACKOFF_SCHEDULE[idx]
                logger.warning(f"⚠️ Allowance exceeded — retrying in {delay}s.")
                time.sleep(delay)
                continue

            # Auth failure classification (2026-07-10 fix).
            # IG 401s carry an `errorCode` in the body; parse it and decide.
            if "401" in msg or "errorCode" in msg:
                code = _extract_ig_error_code(msg)
                last_auth_code = code

                # Suspension / lockout: never retry. Manual intervention only.
                if code in _SUSPENDED_ERROR_CODES:
                    logger.critical(
                        "❌ IG auth CRITICAL — errorCode=%s. Manual intervention "
                        "required; service will NOT self-restart (exit %d).",
                        code, FATAL_AUTH_EXIT_CODE,
                    )
                    _send_fatal_auth_telegram(code, attempt)
                    raise FatalAuthError(code, msg, attempt)

                # Any other auth failure: bounded in-process exponential backoff.
                if attempt >= AUTH_MAX_ATTEMPTS:
                    logger.critical(
                        "❌ IG auth CRITICAL — %d attempts exhausted "
                        "(last errorCode=%s). Service will NOT self-restart "
                        "(exit %d).",
                        attempt, code or "unknown", FATAL_AUTH_EXIT_CODE,
                    )
                    _send_fatal_auth_telegram(code, attempt)
                    raise FatalAuthError(code or "unknown", msg, attempt)

                # Try again after the schedule delay.
                # attempt+1 is the NEXT attempt, so index by that.
                delay = _auth_backoff_seconds(attempt + 1)
                logger.warning(
                    "⚠️ IG auth failed (errorCode=%s attempt %d/%d) — "
                    "retrying in %ds.",
                    code or "unknown", attempt, AUTH_MAX_ATTEMPTS, delay,
                )
                time.sleep(delay)
                continue

            logger.error(f"❌ IG login error: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected login error: {e}")
            raise

    # fetch and normalize accounts
    raw_accounts = ig.fetch_accounts()
    accounts = _normalize_accounts(raw_accounts)
    if not accounts:
        raise RuntimeError("No IG accounts returned at login.")

    account_id, why = _select_account_id(accounts)
    if not account_id:
        raise RuntimeError("Could not determine account ID from accounts payload.")

    # Helpful selection log
    chosen = None
    for a in accounts:
        if isinstance(a, dict) and a.get("accountId") == account_id:
            chosen = a
            break

    if chosen:
        logger.info(
            f"👤 Selected account: id={chosen.get('accountId')} type={chosen.get('accountType')} "
            f"name='{chosen.get('accountName')}' preferred={chosen.get('preferred')} "
            f"(why={why} IG_ACCOUNT_ID={'set' if IG_ACCOUNT_ID else 'unset'} IG_PRODUCT_TYPE={'set' if IG_PRODUCT_TYPE else 'unset'})"
        )
    else:
        logger.info(f"👤 Selected account: id={account_id} (why={why})")

    # attempt switch_account
    try:
        switch_account(ig, None, account_id)
    except Exception:
        pass

    headers = _build_headers(ig, account_id)
    logger.info(f"✅ Using account {account_id}; CST/XST ready.")

    _CACHED = (ig, headers, account_id)
    return _CACHED


def switch_account(ig, headers, account_id):
    """
    Canonical API: switch account on IGService.
    headers param is accepted for signature compatibility, but not required here.
    """
    try:
        ig.switch_account(account_id, default_account=True)
        return
    except IGException as e:
        msg = (str(e) or "")
        msg_l = msg.lower()

        # Benign cases (already active)
        if "412" in msg or "precondition" in msg_l:
            logger.info("ℹ️ switch_account returned 412 (already active) — ignoring.")
            return
        if "accountid-must-be-different" in msg_l:
            logger.info("ℹ️ switch_account says account must be different (already active) — ignoring.")
            return

        logger.warning(f"⚠️ switch_account warning: {e}")
        return
    except Exception as e:
        # Some trading_ig versions raise non-IGException here for the same benign conditions
        msg = (str(e) or "")
        msg_l = msg.lower()

        if "412" in msg or "precondition" in msg_l:
            logger.info("ℹ️ switch_account returned 412 (already active) — ignoring.")
            return
        if "accountid-must-be-different" in msg_l:
            logger.info("ℹ️ switch_account says account must be different (already active) — ignoring.")
            return

        logger.warning(f"⚠️ switch_account warning: {e}")
        return


def refresh_session():
    """
    Canonical API: force refresh cached session.
    Returns a new (ig_service, headers, account_id).

    Rate-limited to one re-auth attempt per AUTH_REFRESH_MIN_INTERVAL_S
    (default 60s). Calls inside the window return the existing cached
    session; if none is present, raise RuntimeError WITHOUT contacting IG.
    Slot is consumed at attempt time, so a failing burst cannot bypass
    the throttle.

    On any failure the prior _CACHED value is restored so subsequent
    callers keep the last-good session instead of triggering a fresh
    create_session() cascade (the 2026-07-22 auth-flood defect).
    """
    global _CACHED, _LAST_REFRESH_ATTEMPT, _REFRESH_INFLIGHT_PRIOR, _REFRESH_INFLIGHT

    now = time.monotonic()
    with _REFRESH_LOCK:
        elapsed = now - _LAST_REFRESH_ATTEMPT
        # Concurrency guard: while a refresh is in flight, callers must NOT
        # start a second re-auth regardless of elapsed time. The time throttle
        # limits entry RATE; this flag limits CONCURRENCY. Both are needed —
        # a non-fatal 401 (invalid-details / oauth-token-invalid) sends the
        # in-flight caller through the 30/60/120/240/300 ladder (~12.5min),
        # during which the time throttle would otherwise expire and let a
        # second caller stack its own ladder on top.
        if _REFRESH_INFLIGHT or elapsed < AUTH_REFRESH_MIN_INTERVAL_S:
            existing = _CACHED if _CACHED is not None else _REFRESH_INFLIGHT_PRIOR
            if existing is not None:
                return existing
            raise RuntimeError(
                f"refresh_session throttled "
                f"(inflight={_REFRESH_INFLIGHT}, elapsed={elapsed:.1f}s, "
                f"min={AUTH_REFRESH_MIN_INTERVAL_S}s) "
                "and no cached session available"
            )
        # Consume slot at attempt time (not on success) so a failing burst
        # cannot bypass the throttle.
        _LAST_REFRESH_ATTEMPT = now
        prior_cache = _CACHED
        # Side-channel copy: concurrent readers inside the throttle window
        # find the prior session here while _CACHED is temporarily None.
        # Must be released before the network call — get_ig_session() can
        # walk the 30/60/120/240/300 backoff ladder (~12.5min).
        _REFRESH_INFLIGHT_PRIOR = prior_cache
        _REFRESH_INFLIGHT = True
        _CACHED = None

    # Ensure patch survives refresh (#22/#86)
    _apply_trading_ig_resolution_patch()

    try:
        new_session = get_ig_session()
    except BaseException:
        with _REFRESH_LOCK:
            if _CACHED is None:
                _CACHED = prior_cache
            _REFRESH_INFLIGHT_PRIOR = None
            _REFRESH_INFLIGHT = False
        raise

    with _REFRESH_LOCK:
        _REFRESH_INFLIGHT_PRIOR = None
        _REFRESH_INFLIGHT = False
    return new_session
