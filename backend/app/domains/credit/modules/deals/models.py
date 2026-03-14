from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin


class PipelineDeal(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Pipeline deal — origination / due-diligence phase.

    Table: pipeline_deals.  Intelligence lifecycle fields
    (intelligence_status, intelligence_generated_at) live HERE,
    never on the portfolio Deal (deals table).
    """

    __tablename__ = "pipeline_deals"

    deal_name: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    sponsor_name: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    lifecycle_stage: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    first_detected_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deal_folder_path: Mapped[str | None] = mapped_column(String(800), nullable=True, index=True)
    transition_target_container: Mapped[str | None] = mapped_column(String(120), nullable=True)
    intelligence_history: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    title: Mapped[str] = mapped_column(String(300), index=True)
    borrower_name: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    requested_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    stage: Mapped[str] = mapped_column(String(64), index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    rejection_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    rejection_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # --- AI output columns (populated by Deal Intelligence pipeline) ---
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_risk_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_key_terms: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    research_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    marketing_thesis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Intelligence lifecycle ---
    intelligence_status: Mapped[str] = mapped_column(
        Enum("PENDING", "PROCESSING", "READY", "FAILED", name="intelligence_status_enum", create_type=False),
        server_default="PENDING", nullable=False, index=True,
    )
    intelligence_generated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- IC Approval tracking ---
    approved_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- relationships ---
    documents: Mapped[list[DealDocument]] = relationship(
        "DealDocument",
        back_populates="deal",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    __table_args__ = (Index("ix_pipeline_deals_fund_stage", "fund_id", "stage"),)


# Backward-compatible alias — existing imports that use ``Deal`` will
# continue to work.  New code should use ``PipelineDeal`` explicitly.
Deal = PipelineDeal


class DealDocument(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "pipeline_deal_documents"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), index=True)
    document_type: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), default="registered", index=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # --- Blob tracking (Deal Intelligence pipeline) ---
    blob_container: Mapped[str | None] = mapped_column(Text, nullable=True)
    blob_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    authority: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_indexed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- relationship ---
    deal: Mapped[PipelineDeal] = relationship("PipelineDeal", back_populates="documents")

    __table_args__ = (
        Index("uq_deal_doc_blob_path", "deal_id", "blob_path", unique=True),
    )


class DealStageHistory(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "pipeline_deal_stage_history"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), index=True)
    from_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(64), index=True)
    changed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)


class DealDecision(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "pipeline_deal_decisions"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)  # approved/rejected/conditional
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    rationale: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class QualificationRule(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "pipeline_qualification_rules"

    name: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[str] = mapped_column(String(32), default="v1", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    rule_config: Mapped[dict] = mapped_column(JSON)


class QualificationResult(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "pipeline_qualification_results"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_qualification_rules.id", ondelete="RESTRICT"),
        index=True,
    )
    result: Mapped[str] = mapped_column(String(16), index=True)  # pass/fail/flag
    reasons: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    run_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class DealCashflow(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Portfolio-deal cashflow ledger entry (FK → deals.id)."""

    __tablename__ = "deal_cashflows"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deals.id", ondelete="RESTRICT"), index=True)
    flow_type: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    flow_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        Index("ix_deal_cashflows_deal_fund", "deal_id", "fund_id"),
        Index("ix_deal_cashflows_flow_date_type", "flow_date", "flow_type"),
    )


class DealConversionEvent(Base):
    """Immutable audit record of each Pipeline → Portfolio conversion."""

    __tablename__ = "deal_conversion_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True,
    )
    fund_id: Mapped[uuid.UUID] = mapped_column(index=True)
    pipeline_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    portfolio_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    active_investment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("active_investments.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversion_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_deal_conversion_events_fund_created", "fund_id", "created_at"),
    )


class DealEvent(Base):
    """Immutable lifecycle audit log for deal events across pipeline + portfolio."""

    __tablename__ = "deal_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True,
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    pipeline_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_deals.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    fund_id: Mapped[uuid.UUID] = mapped_column(index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_deal_events_fund_type", "fund_id", "event_type"),
        Index("ix_deal_events_created", "created_at"),
    )

