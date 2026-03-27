"""SQLAlchemy model for wealth_vector_chunks — fund-centric vector index.

Separated from vector_chunks (Credit/deal-centric).
organization_id nullable: NULL = global data (SEC/ESMA, no tenant).

entity_type values:
  "firm"  — RIA / Management Company (brochure ADV, ESMA manager)
  "fund"  — instrument fund (ESMA fund, DD chapter)
  "macro" — macro review
NEVER use "manager" — manager = PM individual in this system.

firm_crd: CRD of the managing firm, populated for entity_type="firm".
Enables: instrument.attributes["sec_crd"] → firm_crd → chunks.
"""

from __future__ import annotations

import datetime as dt

from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class WealthVectorChunk(Base):
    __tablename__ = "wealth_vector_chunks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), nullable=True, index=True,
    )
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(Text, nullable=True, default="en")
    source_row_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    firm_crd: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    filing_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(3072), nullable=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedded_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
