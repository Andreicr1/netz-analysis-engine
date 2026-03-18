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
    rationale: str | None = None
    actor_capacity: str | None = None

    revision_count: int
    current_round: int

    routing_basis: str | None = None
    classification_confidence: float | None = None
    classification_layer: int | None = None
    classification_model: str | None = None

    metadata_json: dict[str, Any] | None = None

    created_at: datetime
    updated_at: datetime


class DocumentReviewListOut(BaseModel):
    total: int
    reviews: list[DocumentReviewOut]


# ---------------------------------------------------------------------------
# Typed response schemas for review routes
# ---------------------------------------------------------------------------


class ReviewDetailOut(DocumentReviewOut):
    """GET /document-reviews/{id} — review + assignments + checklist + events."""

    assignments: list[Any] = []
    checklist: Any = None
    events: list[Any] = []


class ReviewSubmitOut(DocumentReviewOut):
    """POST /document-reviews — submit result + suggested reviewer roles."""

    suggested_reviewer_roles: list[str] = []


class ReviewDecisionResultOut(BaseModel):
    """POST /document-reviews/{id}/decide — reviewer decision result."""

    review_id: str
    your_decision: str
    review_status: str
    final_decision: str | None = None


class ReviewFinalizeResultOut(BaseModel):
    """POST /document-reviews/{id}/finalize — force-decide result."""

    review_id: str
    status: str
    final_decision: str


class ReviewAssignResultOut(BaseModel):
    """POST /document-reviews/{id}/assign — assignment result."""

    review_id: str
    status: str
    assignments_added: int


class ReviewResubmitResultOut(BaseModel):
    """POST /document-reviews/{id}/resubmit — resubmit result."""

    review_id: str
    status: str
    current_round: int


class ReviewPendingOut(BaseModel):
    """GET /document-reviews/pending — pending reviews for current actor."""

    count: int
    reviews: list[DocumentReviewOut]


class ReviewSummaryOut(BaseModel):
    """GET /document-reviews/summary — dashboard counts by status."""

    total: int
    submitted: int
    under_review: int
    approved: int
    rejected: int
    revision_requested: int
    cancelled: int


class ReviewAiAnalyzeOut(BaseModel):
    """POST /document-reviews/{id}/ai-analyze — AI analysis trigger result."""

    review_id: str
    status: str
    dispatch: str
    message: str


class ReviewChecklistOut(BaseModel):
    """GET /document-reviews/{id}/checklist — checklist summary + items."""

    review_id: str
    total: int
    checked: int
    required: int
    required_checked: int
    all_required_complete: bool
    completion_pct: float
    items: list[Any]


class ReviewChecklistItemOut(BaseModel):
    """POST check/uncheck — single checklist item response."""

    id: str
    sort_order: int
    category: str
    label: str
    description: str | None = None
    is_required: bool
    is_checked: bool
    checked_by: str | None = None
    checked_at: str | None = None
    notes: str | None = None
    ai_finding: Any = None


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
