"""Wealth Content ORM model — investment outlooks, flash reports, manager spotlights.

Supports status workflow: draft → review → approved → published.
Self-approval blocked: approved_by != created_by enforced at route level.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class WealthContent(OrganizationScopedMixin, Base):
    __tablename__ = "wealth_content"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    content_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
    )  # investment_outlook, flash_report, manager_spotlight
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default="pt",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft",
    )  # draft, review, approved, published
    content_md: Mapped[str | None] = mapped_column(Text)
    content_data: Mapped[dict | None] = mapped_column(JSONB)
    storage_path: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
