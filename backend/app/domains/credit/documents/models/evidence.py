from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import (
    AuditMetaMixin,
    Base,
    FundScopedMixin,
    IdMixin,
    OrganizationScopedMixin,
)


class EvidenceDocument(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Evidence attached to Actions or Deals (IC support).

    Evidence must support both Deals and Actions.
    """

    __tablename__ = "evidence_documents"

    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    action_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    report_pack_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    blob_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Marked only after client completes the blob upload.
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
