from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class EvidenceDocument(Base):
    """
    Evidence attached to Actions or Deals (IC support).

    Evidence must support both Deals and Actions.
    """

    __tablename__ = "evidence_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    fund_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)

    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    action_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    report_pack_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)

    blob_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Marked only after client completes the blob upload.
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

