"""Signature queue models.

The ``signature_queue_items`` table stores documents that have been marked
for e-signature across the platform (Portfolio, Pipeline, Reporting, etc.).
Items accumulate in this queue and can be sent individually or in batch
via Adobe Sign.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin


class SignatureQueueStatus(str, enum.Enum):
    """Lifecycle of a queued signature request."""

    QUEUED = "QUEUED"
    SENDING = "SENDING"
    SENT = "SENT"
    SIGNED = "SIGNED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class SignatureQueueItem(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """A document marked for e-signature from any page in the platform."""

    __tablename__ = "signature_queue_items"

    # ── Document reference (optional — generated PDFs may not have a record) ─
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Descriptive ───────────────────────────────────────────────
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Status ────────────────────────────────────────────────────
    status: Mapped[SignatureQueueStatus] = mapped_column(
        SAEnum(SignatureQueueStatus, name="signature_queue_status_enum"),
        nullable=False,
        default=SignatureQueueStatus.QUEUED,
        server_default=SignatureQueueStatus.QUEUED.value,
        index=True,
    )

    # ── Provenance (which page / entity added this) ───────────────
    source_page: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="UI page that added this item, e.g. portfolio, pipeline, reporting",
    )
    source_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        index=True,
        comment="ID of the deal/investment/report that owns this document",
    )
    source_entity_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Entity type, e.g. active_investment, pipeline_deal, report_pack",
    )

    # ── Blob / Adobe Sign ─────────────────────────────────────────
    blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    adobe_sign_agreement_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    signed_blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    signed_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Batch tracking ────────────────────────────────────────────
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        index=True,
        comment="Batch ID when sent as part of a batch operation",
    )

    # ── Actor ─────────────────────────────────────────────────────
    requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_sig_queue_fund_status", "fund_id", "status"),
        Index("ix_sig_queue_fund_source", "fund_id", "source_page"),
        Index("ix_sig_queue_agreement", "adobe_sign_agreement_id"),
    )
