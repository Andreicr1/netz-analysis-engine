"""Fund membership model — authoritative source for per-user fund access.

Maps (actor_id, organization_id) → set of fund_ids the actor can access.
Admin and super-admin roles bypass this table entirely via Actor.can_access_fund().
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class FundMembership(Base):
    """Per-user fund access grants within an organization.

    Global tables like macro_data have no organization_id. This table is
    organization-scoped but does NOT use OrganizationScopedMixin because
    it is queried during actor resolution (before RLS context is set).
    """

    __tablename__ = "fund_memberships"
    __table_args__ = (
        UniqueConstraint("actor_id", "organization_id", "fund_id", name="uq_fund_membership"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    actor_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    fund_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    granted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    granted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
