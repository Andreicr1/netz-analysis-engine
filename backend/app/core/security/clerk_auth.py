"""Clerk JWT Authentication — Netz Analysis Engine
=================================================

Verifies Clerk JWT v2 tokens (API version 2025-04-10+).
Organization data is in the compact `o` claim:
  { "sub": "user_xxx", "o": { "id": "org_xxx", "rol": "org:admin", "slg": "acme" } }

Adapted from Wealth OS JWKS caching pattern (auth/dependencies.py:32-93)
with Clerk-specific claim extraction.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config.settings import settings
from app.shared.enums import Role

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

# Fixed namespace for deterministic Clerk org ID → UUID conversion.
# Clerk org IDs are strings ("org_xxx"), but the DB uses UUID for organization_id.
# uuid5(NAMESPACE, "org_xxx") always produces the same UUID for the same input.
_CLERK_ORG_NAMESPACE = uuid.UUID("6ba7b814-9dad-11d1-80b4-00c04fd430c8")  # NAMESPACE_URL


def clerk_org_to_uuid(clerk_org_id: str) -> uuid.UUID:
    """Convert a Clerk organization ID (string) to a deterministic UUID.

    Used both in auth (JWT → Actor) and in seed scripts to ensure the same
    Clerk org ID always maps to the same internal UUID.
    """
    try:
        return uuid.UUID(clerk_org_id)
    except ValueError:
        return uuid.uuid5(_CLERK_ORG_NAMESPACE, clerk_org_id)


# Clerk org role slug → internal Role enum
CLERK_TO_ROLE: dict[str, Role] = {
    "org:super_admin": Role.SUPER_ADMIN,
    "org:admin": Role.ADMIN,
    "org:investment_team": Role.INVESTMENT_TEAM,
    "org:gp": Role.GP,
    "org:director": Role.DIRECTOR,
    "org:compliance": Role.COMPLIANCE,
    "org:auditor": Role.AUDITOR,
    "org:investor": Role.INVESTOR,
    "org:advisor": Role.ADVISOR,
    # Fallback: Clerk default roles
    "org:member": Role.INVESTOR,
}


@dataclass
class Actor:
    """Authenticated user context, available in all route handlers."""

    actor_id: str
    name: str
    email: str
    roles: list[Role] = field(default_factory=list)
    organization_id: uuid.UUID | None = None
    organization_slug: str | None = None
    fund_ids: list[uuid.UUID] | None = field(default=None)

    def has_role(self, role: Role) -> bool:
        return Role.SUPER_ADMIN in self.roles or Role.ADMIN in self.roles or role in self.roles

    def can_access_fund(self, fund_id: uuid.UUID) -> bool:
        if Role.ADMIN in self.roles or Role.SUPER_ADMIN in self.roles:
            return True
        return self.fund_ids is not None and fund_id in self.fund_ids


# JWKS client — lazy init, caches keys automatically
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not settings.clerk_jwks_url:
            raise RuntimeError("CLERK_JWKS_URL not configured")
        _jwks_client = PyJWKClient(settings.clerk_jwks_url, cache_keys=True)
    return _jwks_client


def _verify_clerk_jwt(token: str) -> dict:
    """Verify a Clerk JWT and return decoded claims.

    Uses PyJWKClient with built-in key caching and rotation handling.
    Clerk does not use `aud` claim by default — skip audience verification.
    """
    client = _get_jwks_client()
    try:
        signing_key = client.get_signing_key_from_jwt(token)
    except jwt.PyJWKClientError:
        # Key not found — may be rotation. Clear cache and retry once.
        client.get_jwk_set(refresh=True)
        signing_key = client.get_signing_key_from_jwt(token)

    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        options={"verify_aud": False},
    )


def _parse_dev_actor(header_value: str) -> Actor:
    """Parse X-DEV-ACTOR JSON header for local development."""
    data = json.loads(header_value)
    roles = [Role(r) for r in data.get("roles", ["ADMIN"])]
    org_id = data.get("org_id")
    fund_ids = [uuid.UUID(f) for f in data.get("fund_ids", [])]
    return Actor(
        actor_id=data.get("actor_id", "dev-user"),
        name=data.get("name", "Dev User"),
        email=data.get("email", "dev@netz.capital"),
        roles=roles,
        organization_id=uuid.UUID(org_id) if org_id else None,
        organization_slug=data.get("org_slug"),
        fund_ids=fund_ids,
    )


async def get_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Actor:
    """FastAPI dependency: extract authenticated actor from request.

    Priority:
    1. X-DEV-ACTOR header (dev only)
    2. Clerk JWT Bearer token
    """
    # Dev bypass
    if settings.is_development:
        dev_header = request.headers.get(settings.dev_actor_header)
        if dev_header:
            return _parse_dev_actor(dev_header)

        # Accept static dev token
        if credentials and credentials.credentials == settings.dev_token:
            org_id = uuid.UUID(settings.dev_org_id) if settings.dev_org_id else None
            return Actor(
                actor_id="dev-user",
                name="Dev User",
                email="dev@netz.capital",
                roles=[Role.ADMIN, Role.SUPER_ADMIN],
                organization_id=org_id,
                fund_ids=[],
            )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    try:
        decoded = _verify_clerk_jwt(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    except Exception as exc:
        logger.exception("Unexpected error during Clerk JWT verification")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token verification failed") from exc

    # Extract Clerk v2 organization claims
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
        fund_ids=None,  # Resolved from DB on demand in fund-scoped routes
    )


def require_role(*allowed_roles: Role):
    """FastAPI dependency factory: require at least one of the allowed roles."""

    async def _check(actor: Actor = Depends(get_actor)) -> Actor:
        if Role.ADMIN in actor.roles or Role.SUPER_ADMIN in actor.roles:
            return actor
        if not any(r in actor.roles for r in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return actor

    return _check


# Backward-compatible aliases (migrated from netz-wealth-os / netz-private-credit-os)
CurrentUser = Actor
get_current_user = get_actor

# Alias used by credit modules — same semantics as require_role
require_roles = require_role


def require_readonly_allowed():
    """Dependency: allow readonly roles (INVESTOR, AUDITOR, ADVISOR) plus all write roles."""
    from app.shared.enums import READONLY_ROLES
    return require_role(*READONLY_ROLES, Role.INVESTMENT_TEAM, Role.GP, Role.DIRECTOR, Role.COMPLIANCE)


def require_ic_member():
    """Dependency: require IC member role (ADMIN or INVESTMENT_TEAM)."""
    return require_role(Role.INVESTMENT_TEAM)


def require_fund_access():
    """FastAPI dependency factory: validate fund_id access + organization context.

    For non-admin actors whose fund_ids were not provided via dev header,
    resolves fund membership from the fund_memberships table. Admin and
    super-admin roles bypass membership lookup entirely.
    """

    async def _check(
        fund_id: uuid.UUID,
        actor: Actor = Depends(get_actor),
    ) -> Actor:
        # Organization context required for all fund-scoped operations
        if not settings.is_development and actor.organization_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active organization",
            )

        # Admin/super-admin bypass — no DB lookup needed
        if Role.ADMIN in actor.roles or Role.SUPER_ADMIN in actor.roles:
            return actor

        # Resolve fund_ids from DB if not already populated (e.g. from dev header)
        # fund_ids=None means "not resolved yet"; [] means "resolved but empty"
        if actor.fund_ids is None and actor.organization_id is not None:
            actor.fund_ids = await _resolve_fund_ids(actor.actor_id, actor.organization_id)

        if not actor.can_access_fund(fund_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No access to this fund",
            )
        return actor

    return _check


async def _resolve_fund_ids(actor_id: str, organization_id: uuid.UUID) -> list[uuid.UUID]:
    """Load fund memberships from DB for the given actor + organization.

    Uses a dedicated session (no RLS) because this runs during actor
    resolution, before tenant context is established.
    """
    from sqlalchemy import select

    from app.core.db.engine import async_session_factory
    from app.core.security.models import FundMembership

    async with async_session_factory() as session:
        result = await session.execute(
            select(FundMembership.fund_id).where(
                FundMembership.actor_id == actor_id,
                FundMembership.organization_id == organization_id,
            ),
        )
        return list(result.scalars().all())
