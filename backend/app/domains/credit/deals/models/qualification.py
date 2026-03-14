from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, IdMixin, OrganizationScopedMixin


class DealQualification(Base, IdMixin, OrganizationScopedMixin, AuditMetaMixin):
    """Stores qualification runs for audit + learning.
    Qualification runs must persist forever.
    """

    __tablename__ = "deal_qualifications"

    deal_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)

    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False)
