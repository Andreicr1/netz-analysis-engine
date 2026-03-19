"""Wealth Document & DocumentVersion models.

Mirrors Credit's document models but scoped to wealth vertical.
Portfolio/instrument association instead of fund/deal.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, IdMixin, OrganizationScopedMixin
from app.shared.enums import DocumentIngestionStatus


class WealthDocument(Base, IdMixin, OrganizationScopedMixin, AuditMetaMixin):
    __tablename__ = "wealth_documents"

    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    root_folder: Mapped[str] = mapped_column(String(200), default="documents", index=True)
    subfolder_path: Mapped[str | None] = mapped_column(String(800), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "root_folder", "subfolder_path", "title",
            name="uq_wealth_docs_org_folder_title",
        ),
        Index("ix_wealth_docs_org_portfolio", "organization_id", "portfolio_id"),
        Index("ix_wealth_docs_org_instrument", "organization_id", "instrument_id"),
    )


class WealthDocumentVersion(Base, IdMixin, OrganizationScopedMixin, AuditMetaMixin):
    __tablename__ = "wealth_document_versions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wealth_documents.id", ondelete="CASCADE"),
        index=True,
    )
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    version_number: Mapped[int] = mapped_column(Integer, index=True)
    blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    blob_path: Mapped[str | None] = mapped_column(String(800), nullable=True, index=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Numeric(20, 0), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ingestion_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DocumentIngestionStatus.PENDING.value,
        index=True,
    )
    ingestion_error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        Index("ix_wealth_doc_ver_doc_ver", "document_id", "version_number", unique=True),
    )
