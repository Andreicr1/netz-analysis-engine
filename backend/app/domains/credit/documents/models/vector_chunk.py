"""SQLAlchemy model for pgvector chunks table.

Replaces Azure AI Search as the vector retrieval backend.
RLS enforced via organization_id filter on all queries.
"""
from __future__ import annotations

import datetime as dt

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class VectorChunk(OrganizationScopedMixin, Base):
    __tablename__ = "vector_chunks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    deal_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    fund_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    breadcrumb: Mapped[str | None] = mapped_column(Text, nullable=True)
    governance_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(3072), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
