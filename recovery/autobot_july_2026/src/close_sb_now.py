#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
close_sb_now.py
---------------
Responsibilities:
- get_open_positions(): return IG open positions in a normalized structure
- close_sb_now(epic): close an open SB position for a given epic

IMPORTANT:
- We DO NOT use ig_service.fetch_open_positions()
  because some trading_ig versions throw:
      ValueError: columns cannot be a set
- Instead we call the raw REST endpoint safely.
"""

import logging
from typing import Any, Dict, List, Optional

from ig_auth import get_ig_session, refresh_session

logger = logging.getLogger("AutoBot")


def _normalize_payload(response: Any) -> Any:
    """Unwrap (status_code, payload) style responses."""
    while isinstance(response, tuple) and len(response) == 2:
        response = response[1]
    return response


def _exc_text(exc: Exception) -> str:
    try:
        return (str(exc) or "").strip()
    except Exception:
        return ""


def _looks_like_client_token_invalid(exc: Exception) -> bool:
    msg = _exc_text(exc).lower()

    if "client-token-invalid" in msg:
        return True
    if " 401 " in f" {msg} " or "unauthorized" in msg:
        return True
    if "security" in msg and "token" in msg and "invalid" in msg:
        return True

    try:
        code = getattr(exc, "errorCode", None) or getattr(exc, "error_code", None)
        if isinstance(code, str) and "client-token-invalid" in code.lower():
            return True
    except Exception:
        pass

    return False


# ============================================================
# FIXED get_open_positions (no DataFrame path, no bug)
# ============================================================

def get_open_positions() -> Optional[List[Dict[str, Any]]]:
    """
    Returns a normalized list of open positions, or None on API error.

    IMPORTANT: callers must distinguish between:
      - None  → API/network failure; position state is unknown
      - []    → Confirmed successful response with zero open positions
      - [...]  → Positions list

    Uses raw REST call instead of fetch_open_positions()
    to avoid trading_ig DataFrame bug:
        ValueError: columns cannot be a set
    """

    try:
        ig_service, _, _ = get_ig_session()
        if ig_service is None:
            logger.error("get_open_positions: no IG session available")
            return None

        # Raw REST call
        resp = ig_service.session.get(
            f"{ig_service.BASE_URL}/positions",
            headers=ig_service.session.headers,
        )

        if resp.status_code == 401:
            logger.warning("get_open_positions: 401 Unauthorized, refreshing session and retrying once...")
            try:
                refresh_session()
                ig_service, _, _ = get_ig_session()
                resp = ig_service.session.get(
                    f"{ig_service.BASE_URL}/positions",
                    headers=ig_service.session.headers,
                )
            except Exception as refresh_exc:
                logger.error(f"get_open_positions: refresh failed: {refresh_exc}")
                return None

        if resp.status_code != 200:
            logger.error(f"get_open_positions: HTTP {resp.status_code}")
            return None

        payload = resp.json()

    except Exception as exc:
        logger.error(f"get_open_positions: raw REST call failed: {exc}")
        return None

    positions = payload.get("positions")
    if not isinstance(positions, list):
        logger.error(f"get_open_positions: unexpected payload shape (no positions list)")
        return None

    return positions


# ============================================================
# Close helpers
# ============================================================

def _close_position_by_deal(
    deal_id: str,
    close_direction: str,
    size: float,
) -> Optional[Any]:
    """
    Close a position by deal ID.

    Sends ONLY dealId + direction + orderType + size.
    Must NOT include epic or expiry — IG rejects requests where both dealId
    and epic are present with: validation.mutual-exclusive-value.request
    """
    import json as _json

    ig_service, _, _ = get_ig_session()
    if ig_service is None:
        return None

    def _call(svc: Any) -> Any:
        url = f"{svc.BASE_URL}/positions/otc"
        headers = dict(svc.session.headers)
        headers["VERSION"] = "1"
        headers["_method"] = "DELETE"
        body = {
            "dealId": deal_id,
            "direction": close_direction,
            "orderType": "MARKET",
            "size": size,
        }
        resp = svc.session.post(url, data=_json.dumps(body), headers=headers)
        if resp.status_code == 200:
            deal_ref = resp.json().get("dealReference")
            if deal_ref:
                return _normalize_payload(svc.fetch_deal_by_deal_reference(deal_ref))
            return resp.json()
        raise Exception(resp.text)

    try:
        return _call(ig_service)
    except Exception as exc:
        if not _looks_like_client_token_invalid(exc):
            logger.error(f"_close_position_by_deal failed for {deal_id}: {exc}")
            return None

        logger.warning(
            f"_close_position_by_deal: token invalid for {deal_id}; refreshing session and retrying once..."
        )
        try:
            refresh_session()
            ig_service, _, _ = get_ig_session()
            if ig_service is None:
                return None
            return _call(ig_service)
        except Exception as exc2:
            logger.error(f"_close_position_by_deal failed for {deal_id} after refresh: {exc2}")
            return None


def close_by_deal_id(deal_id: str) -> Optional[Any]:
    """Close a single position identified by its IG deal ID.

    Looks up the position in IG's open positions list to determine direction
    and size, then delegates to _close_position_by_deal.
    Returns the close response, or None if no matching position was found.
    """
    if not deal_id:
        return None

    positions = get_open_positions()
    if not positions:
        logger.info(f"close_by_deal_id: no open positions found (looking for dealId={deal_id})")
        return None

    for p in positions:
        pos = p.get("position") or {}
        if str(pos.get("dealId") or "") == str(deal_id):
            open_direction = str(pos.get("direction") or "").upper()
            close_direction = "SELL" if open_direction == "BUY" else "BUY"
            size = float(pos.get("dealSize") or pos.get("size") or 1.0)
            return _close_position_by_deal(deal_id, close_direction, size)

    logger.info(f"close_by_deal_id: no position found with dealId={deal_id}")
    return None


def close_sb_now(epic: str) -> Optional[Any]:
    """
    Close ALL open positions matching this epic.
    Returns the last close response, or None if nothing was closed.
    """

    positions = get_open_positions()
    if not positions:
        logger.info(f"close_sb_now: no open positions found for epic={epic}")
        return None

    closed_refs = []

    for p in positions:
        market = p.get("market") or {}
        pos = p.get("position") or {}

        if market.get("epic") != epic:
            continue

        deal_id = pos.get("dealId")
        if not deal_id:
            continue

        open_direction = str(pos.get("direction") or "").upper()
        close_direction = "SELL" if open_direction == "BUY" else "BUY"
        size = float(pos.get("dealSize") or pos.get("size") or 1.0)

        resp = _close_position_by_deal(deal_id, close_direction, size)
        if resp is not None:
            closed_refs.append(resp)

    if not closed_refs:
        logger.info(f"close_sb_now: no matching positions to close for epic={epic}")
        return None

    return closed_refs[-1]
