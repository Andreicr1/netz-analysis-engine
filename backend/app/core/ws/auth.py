"""WebSocket JWT Authentication.

WebSocket connections cannot send Authorization headers during the handshake.
The token is passed as a query parameter: ``?token=<jwt>``.

Validation reuses the same ``_verify_clerk_jwt`` logic as REST endpoints.
Invalid/missing tokens → close with code 1008 (Policy Violation).
"""

from __future__ import annotations

import logging

import jwt
from fastapi import WebSocket

from app.core.config.settings import settings
from app.core.security.clerk_auth import (
    CLERK_TO_ROLE,
    Actor,
    _parse_dev_actor,
    _verify_clerk_jwt,
    clerk_org_to_uuid,
)
from app.shared.enums import Role

logger = logging.getLogger(__name__)

# WebSocket close codes
WS_CLOSE_POLICY_VIOLATION = 1008


async def authenticate_ws(ws: WebSocket) -> Actor | None:
    """Authenticate a WebSocket connection via JWT query parameter.

    Returns the Actor on success, or None after closing the socket on failure.

    Dev bypass: accepts ``dev-token-change-me`` (or configured dev_token) in
    development mode, same as REST ``get_actor()``.
    """
    token = ws.query_params.get("token")

    # Dev bypass
    if settings.is_development:
        dev_header = ws.headers.get(settings.dev_actor_header)
        if dev_header:
            return _parse_dev_actor(dev_header)

        if token == settings.dev_token:
            import uuid

            org_id = uuid.UUID(settings.dev_org_id) if settings.dev_org_id else None
            return Actor(
                actor_id="dev-user",
                name="Dev User",
                email="dev@netz.capital",
                roles=[Role.ADMIN, Role.SUPER_ADMIN],
                organization_id=org_id,
                fund_ids=[],
            )

    if not token:
        logger.warning("ws_auth_missing_token remote=%s", ws.client)
        await ws.close(code=WS_CLOSE_POLICY_VIOLATION, reason="Missing token")
        return None

    try:
        decoded = _verify_clerk_jwt(token)
    except jwt.ExpiredSignatureError:
        logger.warning("ws_auth_expired remote=%s", ws.client)
        await ws.close(code=WS_CLOSE_POLICY_VIOLATION, reason="Token expired")
        return None
    except jwt.InvalidTokenError:
        logger.warning("ws_auth_invalid remote=%s", ws.client)
        await ws.close(code=WS_CLOSE_POLICY_VIOLATION, reason="Invalid token")
        return None
    except Exception:
        logger.exception("ws_auth_unexpected_error remote=%s", ws.client)
        await ws.close(code=WS_CLOSE_POLICY_VIOLATION, reason="Auth failed")
        return None

    org_claims = decoded.get("o", {})
    org_id_str = org_claims.get("id")
    clerk_role = org_claims.get("rol", "org:member")
    internal_role = CLERK_TO_ROLE.get(clerk_role, Role.INVESTOR)

    return Actor(
        actor_id=decoded["sub"],
        name=decoded.get("name", ""),
        email=decoded.get("email", ""),
        roles=[internal_role],
        organization_id=clerk_org_to_uuid(org_id_str) if org_id_str else None,
        organization_slug=org_claims.get("slg"),
        fund_ids=None,
    )
