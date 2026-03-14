from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin
from app.domains.credit.documents.enums import DocumentDomain, DocumentIngestionStatus


class Document(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "documents"

    # Canonical registry (can cover evidence, dataroom, reporting, etc.)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # e.g. "dataroom"
    document_type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    current_version: Mapped[int] = mapped_column(default=0, nullable=False)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Dataroom-related (optional; used when source == "dataroom")
    root_folder: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    folder_path: Mapped[str | None] = mapped_column(String(800), nullable=True, index=True)
    domain: Mapped[DocumentDomain | None] = mapped_column(SAEnum(DocumentDomain, name="document_domain_enum"), nullable=True, index=True)
    blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    __table_args__ = (
        Index("ix_documents_fund_type", "fund_id", "document_type"),
        UniqueConstraint("fund_id", "root_folder", "folder_path", "title", name="uq_documents_fund_folder_title"),
    )


class DocumentVersion(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "document_versions"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(index=True)
    blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Numeric(20, 0), nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Dataroom ingest (optional)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    extracted_text_blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    ingest_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PENDING", index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingest_error: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Institutional dataroom governance
    blob_path: Mapped[str | None] = mapped_column(String(800), nullable=True, index=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # EPIC 3B: worker-driven ingestion lifecycle
    ingestion_status: Mapped[DocumentIngestionStatus] = mapped_column(
        SAEnum(DocumentIngestionStatus, name="document_ingestion_status_enum"),
        nullable=False,
        server_default=DocumentIngestionStatus.PENDING.value,
        index=True,
    )

    __table_args__ = (Index("ix_doc_versions_doc_ver", "document_id", "version_number", unique=True),)


class DocumentAccessPolicy(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "document_access_policies"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DocumentRootFolder(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Custom root folders created by ADMINs (rare).
    Canonical roots live in code constants; this table future-proofs governance.
    """

    __tablename__ = "document_root_folders"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    __table_args__ = (UniqueConstraint("fund_id", "name", name="uq_document_root_folders_fund_name"),)


class DocumentChunk(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Append-only chunk store (source of truth) for audit reproducibility.
    New document version => new set of chunks.
    """

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_vector: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

    # For traceability (denormalized)
    version_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index", name="uq_document_chunks_version_chunk_index"),
        Index("ix_document_chunks_fund_doc_ver", "fund_id", "document_id", "version_id"),
    )

