from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# EvidenceDocument schemas
# ---------------------------------------------------------------------------


class EvidenceDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID

    deal_id: uuid.UUID | None = None
    action_id: uuid.UUID | None = None
    report_pack_id: uuid.UUID | None = None

    filename: str
    blob_uri: str | None = None
    uploaded_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# DocumentReview schemas
# ---------------------------------------------------------------------------


class DocumentReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID

    document_id: uuid.UUID
    document_version_id: uuid.UUID | None = None

    deal_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None

    title: str
    document_type: str
    status: str
    priority: str

    submitted_by: str
    submitted_at: datetime
    due_date: date | None = None

    review_notes: str | None = None
    final_decision: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None

    revision_count: int
    current_round: int

    routing_basis: str | None = None
    classification_confidence: float | None = None

    metadata_json: dict[str, Any] | None = None

    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# ReviewAssignment schemas
# ---------------------------------------------------------------------------


class ReviewAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    review_id: uuid.UUID
    reviewer_actor_id: str
    reviewer_role: str | None = None

    round_number: int
    is_required: bool

    decision: str | None = None
    decision_at: datetime | None = None
    comments: str | None = None

    created_at: datetime
    updated_at: datetime
