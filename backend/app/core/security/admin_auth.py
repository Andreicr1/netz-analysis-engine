"""Super-admin authentication dependency for admin routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.core.security.clerk_auth import Actor, get_actor
from app.shared.enums import Role


async def require_super_admin(
    actor: Actor = Depends(get_actor),
) -> Actor:
    """Reject non-SUPER_ADMIN users with 403."""
    if Role.SUPER_ADMIN not in actor.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )
    return actor
