"""Pydantic v2 schemas for investor portal endpoints.

These are investor-facing — intentionally EXCLUDE internal storage paths
(blob_path, blob_uri) that would reveal ADLS topology to external users.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InvestorReportPackItem(BaseModel):
    """Published report pack visible to investors."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    status: str
    period_month: str | None = None
    published_at: datetime | None = None
    created_at: datetime | None = None


class InvestorStatementItem(BaseModel):
    """Investor statement — excludes blob_path (internal storage)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period_month: str
    created_at: datetime | None = None


class InvestorDocumentItem(BaseModel):
    """Document approved for investor distribution — excludes blob_uri."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    document_type: str
    status: str
    content_type: str | None = None
    original_filename: str | None = None
    created_at: datetime | None = None


class InvestorListResponse(BaseModel):
    """Paginated list envelope for investor endpoints."""

    items: list[InvestorDocumentItem] | list[InvestorStatementItem]
