from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin, OrganizationScopedMixin


class AIQuery(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "ai_queries"

    actor_id: Mapped[str] = mapped_column(String(200), index=True)
    query_text: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at_utc: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class AIResponse(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "ai_responses"

    query_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_queries.id", ondelete="CASCADE"), index=True)
    model_version: Mapped[str] = mapped_column(String(80), index=True)
    prompt: Mapped[dict] = mapped_column(JSON)
    retrieval_sources: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    citations: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at_utc: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (Index("ix_ai_responses_fund_query", "fund_id", "query_id"),)


# EPIC 3C: institutional Q&A (append-only) with explicit citation table.
class AIQuestion(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "ai_questions"

    actor_id: Mapped[str] = mapped_column(String(200), index=True)
    question_text: Mapped[str] = mapped_column(Text)
    root_folder: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    retrieved_chunk_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at_utc: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class AIAnswer(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "ai_answers"

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_questions.id", ondelete="CASCADE"), index=True)
    model_version: Mapped[str] = mapped_column(String(80), index=True)
    answer_text: Mapped[str] = mapped_column(Text)
    prompt: Mapped[dict] = mapped_column(JSON)
    created_at_utc: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (Index("ix_ai_answers_fund_question", "fund_id", "question_id"),)


class AIAnswerCitation(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "ai_answer_citations"

    answer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_answers.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excerpt: Mapped[str] = mapped_column(Text)
    source_blob: Mapped[str | None] = mapped_column(String(800), nullable=True)

    __table_args__ = (Index("ix_ai_answer_citations_fund_answer", "fund_id", "answer_id"),)


class DocumentRegistry(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "document_registry"

    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_versions.id", ondelete="CASCADE"), index=True, nullable=True)
    blob_path: Mapped[str] = mapped_column(String(800), nullable=False)
    container_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    domain_tag: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    authority: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    shareability: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    detected_doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lifecycle_stage: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    last_ingested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_modified_utc: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    root_folder: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    folder_path: Mapped[str | None] = mapped_column(String(800), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    institutional_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    classifier_version: Mapped[str] = mapped_column(String(80), nullable=False, default="wave-ai1-v1")
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    data_latency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_quality: Mapped[str | None] = mapped_column(String(16), nullable=True, default="OK")

    __table_args__ = (
        Index("ix_document_registry_fund_type", "fund_id", "institutional_type"),
        Index("ix_document_registry_fund_version", "fund_id", "version_id", unique=True),
        Index("ix_document_registry_fund_container_blob", "fund_id", "container_name", "blob_path", unique=True),
    )


class ManagerProfile(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "manager_profiles"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str] = mapped_column(String(120), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(120), nullable=False)
    declared_target_return: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reporting_cadence: Mapped[str] = mapped_column(String(80), nullable=False)
    key_risks_declared: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    last_document_update: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_documents: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    data_latency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_quality: Mapped[str | None] = mapped_column(String(16), nullable=True, default="OK")

    __table_args__ = (Index("ix_manager_profiles_fund_name", "fund_id", "name", unique=True),)


class ObligationRegister(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "obligation_register"

    obligation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    obligation_text: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    due_rule: Mapped[str] = mapped_column(String(300), nullable=False)
    responsible_party: Mapped[str] = mapped_column(String(120), nullable=False)
    evidence_expected: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_documents: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    data_latency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_quality: Mapped[str | None] = mapped_column(String(16), nullable=True, default="OK")

    __table_args__ = (Index("ix_obligation_register_fund_obligation_id", "fund_id", "obligation_id", unique=True),)


class GovernanceAlert(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "governance_alerts"

    alert_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    entity_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    actionable_next_step: Mapped[str] = mapped_column(Text, nullable=False)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    data_latency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_quality: Mapped[str | None] = mapped_column(String(16), nullable=True, default="OK")

    __table_args__ = (Index("ix_governance_alerts_fund_alert_id", "fund_id", "alert_id", unique=True),)


class DocumentClassification(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "document_classifications"

    doc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)
    classification_basis: Mapped[str] = mapped_column(String(120), nullable=False)

    __table_args__ = (Index("ix_document_classifications_fund_doc", "fund_id", "doc_id", unique=True),)


class DocumentGovernanceProfile(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "document_governance_profile"

    doc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True)
    resolved_authority: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    binding_scope: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    shareability_final: Mapped[str] = mapped_column(String(40), nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (Index("ix_document_governance_profile_fund_doc", "fund_id", "doc_id", unique=True),)


class KnowledgeAnchor(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "knowledge_anchors"

    doc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True)
    anchor_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    anchor_value: Mapped[str] = mapped_column(String(500), nullable=False)
    source_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)

    __table_args__ = (Index("ix_knowledge_anchors_fund_doc", "fund_id", "doc_id"),)


class KnowledgeEntity(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "knowledge_entities"

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    __table_args__ = (Index("ix_knowledge_entities_fund_type_name", "fund_id", "entity_type", "canonical_name", unique=True),)


class KnowledgeLink(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "knowledge_links"

    source_document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True)
    target_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    authority_tier: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_knowledge_links_fund_source_target_type", "fund_id", "source_document_id", "target_entity_id", "link_type", unique=True),
    )


class ObligationEvidenceMap(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "obligation_evidence_map"

    obligation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_registry.id", ondelete="SET NULL"), nullable=True, index=True)
    satisfaction_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    last_checked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (Index("ix_obligation_evidence_map_fund_obligation", "fund_id", "obligation_id", unique=True),)


class DealDocumentIntelligence(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "deal_documents"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_registry.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (Index("ix_deal_documents_fund_deal_doc", "fund_id", "deal_id", "doc_id", unique=True),)


class DealIntelligenceProfile(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "deal_intelligence_profiles"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True)
    strategy_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    geography: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sector_focus: Mapped[str | None] = mapped_column(String(160), nullable=True)
    target_return: Mapped[str | None] = mapped_column(String(60), nullable=True)
    risk_band: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    liquidity_profile: Mapped[str | None] = mapped_column(String(80), nullable=True)
    capital_structure_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    key_risks: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    differentiators: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    summary_ic_ready: Mapped[str] = mapped_column(Text, nullable=False)
    last_ai_refresh: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (Index("ix_deal_intelligence_profiles_fund_deal", "fund_id", "deal_id", unique=True),)


class DealRiskFlag(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "deal_risk_flags"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True)
    risk_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    source_document: Mapped[str | None] = mapped_column(String(800), nullable=True)

    __table_args__ = (Index("ix_deal_risk_flags_fund_deal", "fund_id", "deal_id"),)


class DealICBrief(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "deal_ic_briefs"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    opportunity_overview: Mapped[str] = mapped_column(Text, nullable=False)
    return_profile: Mapped[str] = mapped_column(Text, nullable=False)
    downside_case: Mapped[str] = mapped_column(Text, nullable=False)
    risk_summary: Mapped[str] = mapped_column(Text, nullable=False)
    comparison_peer_funds: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_signal: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    __table_args__ = (Index("ix_deal_ic_briefs_fund_deal", "fund_id", "deal_id", unique=True),)


class PipelineAlert(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "pipeline_alerts"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_pipeline_alerts_fund_deal", "fund_id", "deal_id"),)


class ActiveInvestment(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "active_investments"

    # FK targets portfolio deals (deals.id), NOT pipeline_deals.
    # See migration 0029_active_investment_anchor_fix.
    deal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=True, index=True)
    primary_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_registry.id", ondelete="SET NULL"), nullable=True, index=True)
    investment_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    manager_name: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_container: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_folder: Mapped[str] = mapped_column(String(400), nullable=False, index=True)
    strategy_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_return: Mapped[str | None] = mapped_column(String(60), nullable=True)
    committed_capital_usd: Mapped[float | None] = mapped_column(nullable=True)
    deployed_capital_usd: Mapped[float | None] = mapped_column(nullable=True)
    current_nav_usd: Mapped[float | None] = mapped_column(nullable=True)
    last_monitoring_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    transition_log: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    data_latency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_quality: Mapped[str | None] = mapped_column(String(16), nullable=True, default="OK")

    __table_args__ = (
        Index("ix_active_investments_fund_name", "fund_id", "investment_name"),
        Index("ix_active_investments_fund_source_folder", "fund_id", "source_folder", unique=True),
    )


class PerformanceDriftFlag(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "performance_drift_flags"

    investment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    baseline_value: Mapped[float | None] = mapped_column(nullable=True)
    current_value: Mapped[float | None] = mapped_column(nullable=True)
    drift_pct: Mapped[float | None] = mapped_column(nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", index=True)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (Index("ix_performance_drift_flags_fund_investment", "fund_id", "investment_id"),)


class CovenantStatusRegister(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "covenant_status_register"

    investment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True)
    covenant_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    covenant_test_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    breach_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    covenant_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_tested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_test_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (Index("ix_covenant_status_register_fund_investment", "fund_id", "investment_id"),)


class CashImpactFlag(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "cash_impact_flags"

    investment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    impact_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    estimated_impact_usd: Mapped[float | None] = mapped_column(nullable=True)
    liquidity_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (Index("ix_cash_impact_flags_fund_investment", "fund_id", "investment_id"),)


class InvestmentRiskRegistry(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "investment_risk_registry"

    investment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True)
    risk_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trend: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    source_evidence: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (Index("ix_investment_risk_registry_fund_investment", "fund_id", "investment_id"),)


class BoardMonitoringBrief(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "board_monitoring_briefs"

    investment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    performance_view: Mapped[str] = mapped_column(Text, nullable=False)
    covenant_view: Mapped[str] = mapped_column(Text, nullable=False)
    liquidity_view: Mapped[str] = mapped_column(Text, nullable=False)
    risk_reclassification_view: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_actions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    last_generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (Index("ix_board_monitoring_briefs_fund_investment", "fund_id", "investment_id", unique=True),)


# MacroSnapshot — backward-compatible re-export.
# Canonical location: app.shared.models.MacroSnapshot
# This re-export will be removed after migration is verified.
from app.shared.models import MacroSnapshot  # noqa: F401


class InvestmentMemorandumDraft(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """AI-generated Investment Memorandum draft for IC review."""

    __tablename__ = "investment_memorandum_drafts"

    deal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True)
    version_tag: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    opportunity_overview: Mapped[str] = mapped_column(Text, nullable=False)
    investment_terms_section: Mapped[str] = mapped_column(Text, nullable=False)
    corporate_structure_section: Mapped[str] = mapped_column(Text, nullable=False)
    return_profile_section: Mapped[str] = mapped_column(Text, nullable=False)
    downside_case_section: Mapped[str] = mapped_column(Text, nullable=False)
    risk_summary_section: Mapped[str] = mapped_column(Text, nullable=False)
    peer_comparison_section: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    recommendation_rationale: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    __table_args__ = (Index("ix_im_drafts_fund_deal", "fund_id", "deal_id"),)


# ─────────────────────────────────────────────────────────────────
#  Deep Review V4 — Evidence Pack + Chapter Book
# ─────────────────────────────────────────────────────────────────


class MemoEvidencePack(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Frozen institutional truth source for V4 chapter-book memo generation.

    Generated once per deal version.  Every memo chapter reads from this
    artifact — no chapter may mutate it.  ≤ 5 000 tokens.
    """

    __tablename__ = "memo_evidence_packs"

    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    version_tag: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    __table_args__ = (
        Index("ix_memo_evidence_packs_fund_deal", "fund_id", "deal_id"),
    )


class MemoChapter(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Individual memo chapter in the V4 chapter-book architecture.

    Each chapter is generated independently from a frozen EvidencePack
    plus a small set of relevant evidence chunks.  Persisted immediately
    after generation for resume safety.
    """

    __tablename__ = "memo_chapters"

    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    evidence_pack_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memo_evidence_packs.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_tag: Mapped[str] = mapped_column(String(60), nullable=False)
    chapter_title: Mapped[str] = mapped_column(String(200), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    version_tag: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    generated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    token_count_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
    )

    __table_args__ = (
        Index("ix_memo_chapters_fund_deal_num", "fund_id", "deal_id", "chapter_number"),
        UniqueConstraint("deal_id", "version_tag", "chapter_number", name="uq_chapter_deal_version_num"),
    )


# ─────────────────────────────────────────────────────────────────
#  Unified Underwriting Artifact — single IC truth source
# ─────────────────────────────────────────────────────────────────


class DealUnderwritingArtifact(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Unified underwriting truth object produced by Deep Review V4.

    Only one row per deal may have ``is_active=True`` at any time.
    The Pipeline Engine MUST NOT write to this table.  Frontend and
    API consumers resolve IC recommendation, risk band, confidence,
    and missing-document checklist exclusively from the active artifact.
    Previous artifacts are retained for audit (``is_active=False``).
    """

    __tablename__ = "deal_underwriting_artifacts"

    deal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    evidence_pack_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recommendation: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    risk_band: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    missing_documents: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    critic_findings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    policy_breaches: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chapters_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )

    __table_args__ = (
        Index("ix_underwriting_artifacts_fund_deal", "fund_id", "deal_id"),
        Index("ix_underwriting_artifacts_active", "deal_id", "is_active"),
    )


class PeriodicReviewReport(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """AI-generated periodic review of an active investment."""

    __tablename__ = "periodic_review_reports"

    investment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("active_investments.id", ondelete="CASCADE"), nullable=False, index=True)
    review_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    overall_rating: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    performance_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    covenant_compliance: Mapped[str] = mapped_column(Text, nullable=False)
    material_changes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    risk_evolution: Mapped[str] = mapped_column(Text, nullable=False)
    liquidity_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    valuation_view: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_actions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    reviewed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (Index("ix_periodic_reviews_fund_investment", "fund_id", "investment_id"),)


# ─────────────────────────────────────────────────────────────────
#  Deep Review Validation Harness — audit persistence
# ─────────────────────────────────────────────────────────────────


class DeepReviewValidationRun(Base, IdMixin, AuditMetaMixin):
    """Per-deal result row from a V3-vs-V4 validation benchmark run.

    One row per (run_id, deal_id).  Stores the full delta JSON and
    deterministic winner for institutional audit.
    """

    __tablename__ = "deep_review_validation_runs"

    fund_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False, index=True,
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    v3_version_tag: Mapped[str | None] = mapped_column(String(80), nullable=True)
    v4_version_tag: Mapped[str | None] = mapped_column(String(80), nullable=True)
    delta_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    winner: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    engine_score_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    aggregate_winner: Mapped[str | None] = mapped_column(String(10), nullable=True)
    institutional_decision: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_validation_runs_run_deal", "run_id", "deal_id"),
    )


# ─────────────────────────────────────────────────────────────────
#  IC Memo Eval Framework — hybrid regression tracking
# ─────────────────────────────────────────────────────────────────


class EvalRun(Base, IdMixin, AuditMetaMixin):
    """Top-level execution record for the hybrid IC memo eval framework."""

    __tablename__ = "eval_runs"

    fund_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    run_mode: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    golden_set_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    baseline_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    prompt_manifest_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    model_manifest_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_manifest_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="completed")
    classification: Mapped[str] = mapped_column(String(20), nullable=False, index=True, default="DATA_ISSUE")
    classification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        Index("ix_eval_runs_run_id", "run_id", unique=True),
        Index("ix_eval_runs_fund_started", "fund_id", "started_at"),
    )


class EvalChapterScore(Base, IdMixin, AuditMetaMixin):
    """Per-chapter score row for a hybrid IC memo eval run."""

    __tablename__ = "eval_chapter_scores"

    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    fund_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True, index=True,
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_deals.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    deal_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_tag: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    chapter_title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_applicable_layer1: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_applicable_layer2: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    layer1_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    layer2_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    layer3_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    layer4_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    aggregate_score_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    classification: Mapped[str] = mapped_column(String(20), nullable=False, index=True, default="DATA_ISSUE")
    classification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    golden_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    memo_version_tag: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    provider_info_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_eval_chapter_scores_run_deal", "run_id", "deal_id"),
        Index("ix_eval_chapter_scores_run_chapter", "run_id", "chapter_tag"),
        UniqueConstraint("run_id", "deal_id", "chapter_tag", name="uq_eval_run_deal_chapter"),
    )

