"""Document Review models — governed review workflow for legal documents.

FSM:
  SUBMITTED → UNDER_REVIEW → APPROVED | REJECTED | REVISION_REQUESTED
  REVISION_REQUESTED → SUBMITTED (resubmit with new version)

Each review can have multiple reviewers assigned. The review is complete
when all required reviewers have submitted their decision, or when an
ADMIN/GP force-approves.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, OrganizationScopedMixin, IdMixin


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CANCELLED = "CANCELLED"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class ReviewPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class DocumentReview(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """A review request for a document requiring approval before execution."""

    __tablename__ = "document_reviews"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True, index=True,
    )

    deal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="LEGAL | REGULATORY | DD_REPORT | TERM_SHEET | INVESTMENT_MEMO | MARKETING | OTHER",
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ReviewStatus.SUBMITTED.value, index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ReviewPriority.MEDIUM.value, index=True,
    )

    submitted_by: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    revision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_round: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    routing_basis: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="Why this was routed to specific reviewers (AI classification, manual, etc.)",
    )
    classification_confidence: Mapped[float | None] = mapped_column(nullable=True)

    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        Index("ix_doc_reviews_fund_status", "fund_id", "status"),
        Index("ix_doc_reviews_fund_doc", "fund_id", "document_id"),
        Index("ix_doc_reviews_submitted_by", "submitted_by", "status"),
    )


class ReviewAssignment(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Assignment of a reviewer to a document review."""

    __tablename__ = "review_assignments"

    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_reviews.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    reviewer_actor_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    reviewer_role: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
        comment="Role that triggered the assignment (COMPLIANCE, INVESTMENT_TEAM, etc.)",
    )

    round_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    decision: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True,
        comment="APPROVED | REJECTED | REVISION_REQUESTED",
    )
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_review_assign_reviewer", "reviewer_actor_id", "decision"),
        Index("ix_review_assign_review_round", "review_id", "round_number"),
    )


class ReviewChecklistItem(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """A checklist item that must be verified during document review."""

    __tablename__ = "review_checklist_items"

    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_reviews.id", ondelete="CASCADE"), nullable=False, index=True,
    )

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_checked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    checked_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_finding: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="AI pre-analysis: {status: FOUND|NOT_FOUND|UNCLEAR, confidence: 0-100, "
                "excerpt: str, source_chunk_id: str, model: str, analyzed_at: str}",
    )

    __table_args__ = (
        Index("ix_review_checklist_review", "review_id", "sort_order"),
    )


class ReviewEvent(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin):
    """Immutable log of review lifecycle events."""

    __tablename__ = "review_events"

    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_reviews.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="submitted | assigned | decision | status_change | resubmitted | comment",
    )
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_review_events_review", "review_id", "created_at"),
    )
