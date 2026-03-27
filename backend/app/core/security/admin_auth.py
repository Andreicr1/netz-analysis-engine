"""Super-admin authentication dependency for admin routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.core.security.clerk_auth import Actor, get_actor
from app.shared.enums import Role


async def require_super_admin(
    actor: Actor = Depends(get_actor),
) -> Actor:
    """Reject non-admin users with 403.

    Accepts both SUPER_ADMIN and ADMIN — Clerk free/pro plans only
    support org:admin, so for single-tenant deployments ADMIN is
    sufficient for platform operations.
    """
    if Role.SUPER_ADMIN not in actor.roles and Role.ADMIN not in actor.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )
    return actor
