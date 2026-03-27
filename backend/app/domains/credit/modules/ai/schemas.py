from __future__ import annotations

import datetime as dt
import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int


class AIQueryCreate(BaseModel):
    query_text: str = Field(min_length=3)


class AIQueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    actor_id: str
    query_text: str
    request_id: str
    created_at_utc: dt.datetime


class AIResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    query_id: uuid.UUID
    model_version: str
    prompt: dict
    retrieval_sources: list[dict] | None
    citations: list[dict] | None
    response_text: str | None
    created_at_utc: dt.datetime


class AIRetrieveRequest(BaseModel):
    query: str = Field(min_length=3)
    root_folder: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class AIRetrieveResult(BaseModel):
    chunk_id: str
    document_title: str
    root_folder: str | None
    folder_path: str | None
    version_id: str
    version_number: int
    chunk_index: int | None
    excerpt: str
    source_blob: str | None


class AIRetrieveResponse(BaseModel):
    results: list[AIRetrieveResult]
    retrieval_confidence: str | None = None


class AIAnswerRequest(BaseModel):
    question: str = Field(min_length=3)
    root_folder: str | None = None
    top_k: int = Field(default=6, ge=1, le=20)
    current_view: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    entity_name: str | None = None
    context_doc_title: str | None = None


class AIAnswerCitationOut(BaseModel):
    chunk_id: str
    document_id: str
    version_id: str
    page_start: int | None
    page_end: int | None
    excerpt: str
    source_blob: str | None


class AIAnswerResponse(BaseModel):
    answer: str
    citations: list[AIAnswerCitationOut]
    retrieval_confidence: str | None = None


class AIActivityItemOut(BaseModel):
    question_id: str
    answer_id: str
    question: str | None
    asked_by: str | None
    timestamp_utc: dt.datetime | None
    insufficient_evidence: bool
    citations_count: int


class DataEnvelope(BaseModel):
    asOf: dt.datetime
    dataLatency: int | None = None
    dataQuality: str | None = None


class DocumentClassificationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    documentId: uuid.UUID = Field(validation_alias="document_id")
    versionId: uuid.UUID = Field(validation_alias="version_id")
    title: str
    rootFolder: str | None = Field(default=None, validation_alias="root_folder")
    folderPath: str | None = Field(default=None, validation_alias="folder_path")
    institutionalType: str = Field(validation_alias="institutional_type")


class DocumentClassificationResponse(DataEnvelope):
    items: list[DocumentClassificationItem]


class ManagerProfileItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    strategy: str
    region: str
    vehicleType: str = Field(validation_alias="vehicle_type")
    declaredTargetReturn: str | None = Field(default=None, validation_alias="declared_target_return")
    reportingCadence: str = Field(validation_alias="reporting_cadence")
    keyRisksDeclared: list[str] = Field(default_factory=list, validation_alias="key_risks_declared")
    lastDocumentUpdate: dt.datetime | None = Field(default=None, validation_alias="last_document_update")
    sourceDocuments: list[dict] = Field(default_factory=list, validation_alias="source_documents")


class ManagerProfileResponse(DataEnvelope):
    item: ManagerProfileItem


class ObligationRegisterItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    obligationId: str = Field(validation_alias="obligation_id")
    source: str
    obligationText: str = Field(validation_alias="obligation_text")
    frequency: str
    dueRule: str = Field(validation_alias="due_rule")
    responsibleParty: str = Field(validation_alias="responsible_party")
    evidenceExpected: str = Field(validation_alias="evidence_expected")
    status: str


class ObligationRegisterResponse(DataEnvelope):
    items: list[ObligationRegisterItem]


class GovernanceAlertItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alertId: str = Field(validation_alias="alert_id")
    domain: str
    severity: str
    entityRef: str = Field(validation_alias="entity_ref")
    title: str
    actionableNextStep: str = Field(validation_alias="actionable_next_step")


class GovernanceAlertsResponse(DataEnvelope):
    items: list[GovernanceAlertItem]


class DailyCycleRunResponse(BaseModel):
    asOf: dt.datetime
    classifiedDocuments: int
    managerProfiles: int
    obligations: int
    alerts: int


class DocumentsIngestResponse(BaseModel):
    asOf: dt.datetime
    documentsScanned: int
    documentsClassified: int
    governanceProfiles: int
    knowledgeAnchors: int


class DocumentIndexItem(BaseModel):
    docId: uuid.UUID
    blobPath: str
    containerName: str
    domainTag: str
    lifecycleStage: str
    detectedDocType: str | None
    resolvedAuthority: str | None
    shareability: str
    auditReady: bool
    lastIngestedAt: dt.datetime


class DocumentIndexResponse(DataEnvelope):
    items: list[DocumentIndexItem]


class KnowledgeAnchorOut(BaseModel):
    anchorType: str
    anchorValue: str
    sourceSnippet: str | None
    pageReference: str | None


class DocumentDetailResponse(DataEnvelope):
    docId: uuid.UUID
    blobPath: str
    containerName: str
    domainTag: str
    lifecycleStage: str
    classification: dict
    governanceProfile: dict | None
    anchors: list[KnowledgeAnchorOut]


class PipelineIngestResponse(BaseModel):
    asOf: dt.datetime
    deals: int
    dealDocuments: int
    profiles: int
    briefs: int
    alerts: int


class PipelineDealItem(BaseModel):
    dealId: uuid.UUID
    dealName: str
    sponsorName: str | None
    lifecycleStage: str
    riskBand: str | None
    strategyType: str | None = None
    recommendationSignal: str | None = None
    asOf: dt.datetime
    documentCount: int = 0
    intelligenceStatus: str | None = None
    dealFolderPath: str | None = None
    chaptersCompleted: int = 0
    lastGenerated: dt.datetime | None = None


class PipelineDealsResponse(DataEnvelope):
    items: list[PipelineDealItem]


class PipelineRiskFlagOut(BaseModel):
    riskType: str
    severity: str
    reasoning: str
    sourceDocument: str | None


class PipelineICBriefOut(BaseModel):
    executiveSummary: str | None = None
    opportunityOverview: str | None = None
    returnProfile: str | None = None
    downsideCase: str | None = None
    riskSummary: str | None = None
    comparisonPeerFunds: str | None = None
    recommendationSignal: str | None = None


class UnderwritingArtifactOut(BaseModel):
    """Unified underwriting truth object from Deep Review V4."""

    recommendation: str
    confidenceLevel: str
    riskBand: str
    missingDocuments: list[dict] | None = None
    criticFindings: dict | None = None
    policyBreaches: dict | None = None
    chaptersCompleted: int = 0
    modelVersion: str | None = None
    generatedAt: dt.datetime | None = None
    versionNumber: int = 1
    evidencePackHash: str | None = None


class PipelineDealDetailResponse(DataEnvelope):
    dealId: uuid.UUID
    dealName: str
    sponsorName: str | None
    lifecycleStage: str
    intelligenceStatus: str | None = None
    approvedDealId: uuid.UUID | None = None
    dealFolderPath: str | None = None
    profile: dict | None
    riskFlags: list[PipelineRiskFlagOut]
    icBrief: PipelineICBriefOut | None
    researchOutput: dict | None = None
    documents: list[dict] | None = None
    icReady: bool = False
    underwritingArtifact: UnderwritingArtifactOut | None = None


class PipelineAlertOut(BaseModel):
    alertId: uuid.UUID
    dealId: uuid.UUID
    alertType: str
    severity: str
    description: str
    createdAt: dt.datetime
    resolvedFlag: bool


class PipelineAlertsResponse(DataEnvelope):
    items: list[PipelineAlertOut]


class PortfolioIngestResponse(BaseModel):
    asOf: dt.datetime
    investments: int
    metrics: int
    drifts: int
    covenants: int
    cashFlags: int
    riskRegistry: int
    briefs: int


class PortfolioInvestmentItem(BaseModel):
    investmentId: uuid.UUID
    investmentName: str
    managerName: str | None
    lifecycleStatus: str
    strategyType: str | None
    targetReturn: str | None
    committedCapitalUsd: float | None
    deployedCapitalUsd: float | None
    currentNavUsd: float | None
    overallRiskLevel: str | None
    asOf: dt.datetime


class PortfolioInvestmentsResponse(DataEnvelope):
    items: list[PortfolioInvestmentItem]


class PortfolioDriftOut(BaseModel):
    metricName: str
    baselineValue: float | None
    currentValue: float | None
    driftPct: float | None
    severity: str
    reasoning: str


class PortfolioCovenantOut(BaseModel):
    covenantName: str
    status: str
    severity: str
    details: str | None
    lastTestedAt: dt.datetime | None
    nextTestDueAt: dt.datetime | None


class PortfolioCashImpactOut(BaseModel):
    impactType: str
    severity: str
    estimatedImpactUsd: float | None
    liquidityDays: int | None
    message: str
    resolvedFlag: bool


class PortfolioRiskOut(BaseModel):
    riskType: str
    riskLevel: str
    trend: str | None
    rationale: str


class PortfolioBriefOut(BaseModel):
    executiveSummary: str
    performanceView: str
    covenantView: str
    liquidityView: str
    riskReclassificationView: str
    recommendedActions: list[str]
    lastGeneratedAt: dt.datetime


class PortfolioInvestmentDetailResponse(DataEnvelope):
    investmentId: uuid.UUID
    investmentName: str
    managerName: str | None
    lifecycleStatus: str
    sourceContainer: str
    sourceFolder: str
    profile: dict
    drifts: list[PortfolioDriftOut]
    covenants: list[PortfolioCovenantOut]
    cashImpacts: list[PortfolioCashImpactOut]
    risks: list[PortfolioRiskOut]
    boardBrief: PortfolioBriefOut | None


class PortfolioAlertOut(BaseModel):
    alertType: str
    severity: str
    investmentId: uuid.UUID
    investmentName: str
    message: str
    createdAt: dt.datetime


class PortfolioAlertsResponse(DataEnvelope):
    items: list[PortfolioAlertOut]


# ─────────────────────────────────────────────────────────────────
#  Deep Review & Investment Memorandum schemas
# ─────────────────────────────────────────────────────────────────

class DeepReviewRequest(BaseModel):
    actor_id: str = Field(default="ai-engine", description="Who triggered the review")


class DeepReviewResultItem(BaseModel):
    dealId: uuid.UUID
    dealName: str | None = None
    profileCreated: bool = False
    riskFlagsCount: int = 0
    icBriefCreated: bool = False
    imDraftCreated: bool = False
    error: str | None = None


class DeepReviewResponse(BaseModel):
    asOf: dt.datetime
    totalDeals: int = 0
    reviewed: int = 0
    errors: int = 0
    results: list[DeepReviewResultItem] = []


class DealDeepReviewResponse(BaseModel):
    dealId: str
    dealName: str | None = None
    profileCreated: bool = False
    riskFlagsCount: int = 0
    icBriefCreated: bool = False
    imDraftCreated: bool = False
    analysisKeys: list[str] = []
    asOf: dt.datetime
    error: str | None = None


class InvestmentMemorandumOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dealId: uuid.UUID = Field(validation_alias="deal_id")
    versionTag: str = Field(validation_alias="version_tag")
    executiveSummary: str = Field(validation_alias="executive_summary")
    opportunityOverview: str = Field(validation_alias="opportunity_overview")
    investmentTermsSection: str = Field(validation_alias="investment_terms_section")
    corporateStructureSection: str = Field(validation_alias="corporate_structure_section")
    returnProfileSection: str = Field(validation_alias="return_profile_section")
    downsideCaseSection: str = Field(validation_alias="downside_case_section")
    riskSummarySection: str = Field(validation_alias="risk_summary_section")
    peerComparisonSection: str = Field(validation_alias="peer_comparison_section")
    recommendation: str
    recommendationRationale: str = Field(validation_alias="recommendation_rationale")
    generatedAt: dt.datetime = Field(validation_alias="generated_at")
    modelVersion: str = Field(validation_alias="model_version")


class InvestmentMemorandumResponse(DataEnvelope):
    item: InvestmentMemorandumOut | None = None


class ICMemorandumPdfResponse(BaseModel):
    signedPdfUrl: str | None = None
    versionTag: str | None = None
    generatedAt: dt.datetime | None = None
    modelVersion: str | None = None
    available: bool = True
    message: str | None = None


class PeriodicReviewPdfResponse(BaseModel):
    signedPdfUrl: str
    versionTag: str
    reviewedAt: dt.datetime
    modelVersion: str


class FactSheetPdfResponse(BaseModel):
    signedPdfUrl: str
    versionTag: str
    generatedAt: dt.datetime
    modelVersion: str


class MarketingPresentationPdfResponse(BaseModel):
    signedPdfUrl: str
    versionTag: str
    generatedAt: dt.datetime
    modelVersion: str


class PeriodicReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    investmentId: uuid.UUID = Field(validation_alias="investment_id")
    reviewType: str = Field(validation_alias="review_type")
    overallRating: str = Field(validation_alias="overall_rating")
    executiveSummary: str = Field(validation_alias="executive_summary")
    performanceAssessment: str = Field(validation_alias="performance_assessment")
    covenantCompliance: str = Field(validation_alias="covenant_compliance")
    materialChanges: list[str] = Field(default_factory=list, validation_alias="material_changes")
    riskEvolution: str = Field(validation_alias="risk_evolution")
    liquidityAssessment: str = Field(validation_alias="liquidity_assessment")
    valuationView: str = Field(validation_alias="valuation_view")
    recommendedActions: list[str] = Field(default_factory=list, validation_alias="recommended_actions")
    reviewedAt: dt.datetime = Field(validation_alias="reviewed_at")
    modelVersion: str = Field(validation_alias="model_version")


class PeriodicReviewResponse(DataEnvelope):
    item: PeriodicReviewOut | None = None


class PeriodicReviewsListResponse(DataEnvelope):
    items: list[PeriodicReviewOut]


class PortfolioReviewResponse(BaseModel):
    investmentId: str
    investmentName: str | None = None
    reviewId: str | None = None
    overallRating: str | None = None
    asOf: dt.datetime
    error: str | None = None


class PortfolioBatchReviewResponse(BaseModel):
    asOf: dt.datetime
    totalInvestments: int = 0
    reviewed: int = 0
    errors: int = 0
    results: list[PortfolioReviewResponse] = []


# ─────────────────────────────────────────────────────────────────
#  Portfolio Deal Monitoring (capital-at-risk)
# ─────────────────────────────────────────────────────────────────

class CashflowEventItem(BaseModel):
    id: str
    eventDate: str
    eventType: str
    amount: float
    currency: str
    notes: str = ""


class CashflowSummary(BaseModel):
    totalContributions: float = 0.0
    totalDistributions: float = 0.0
    interestReceived: float = 0.0
    principalReturned: float = 0.0
    netCashPosition: float = 0.0
    cashToCashMultiple: float | None = None
    irrEstimate: float | None = None


class CovenantMonitoringItem(BaseModel):
    covenantName: str
    status: str
    severity: str
    details: str | None = None
    lastTestedAt: dt.datetime | None = None
    nextTestDueAt: dt.datetime | None = None


class RiskMonitoringItem(BaseModel):
    riskType: str
    riskLevel: str
    trend: str | None = None
    rationale: str


class PortfolioDealMonitoringResponse(DataEnvelope):
    """Full portfolio-deal monitoring record (capital-at-risk)."""

    investmentId: uuid.UUID
    dealId: uuid.UUID | None = None
    dealName: str
    sponsorName: str | None = None
    jurisdiction: str | None = None
    instrument: str | None = None
    status: str = "ACTIVE"
    # Capital structure
    commitment: float | None = None
    deployedCapital: float | None = None
    currentNav: float | None = None
    strategyType: str | None = None
    targetReturn: str | None = None
    # Cashflow
    cashflowSummary: CashflowSummary
    cashflowEvents: list[CashflowEventItem] = []
    # Monitoring
    covenantMonitoring: list[CovenantMonitoringItem] = []
    riskMonitoring: list[RiskMonitoringItem] = []
    monitoringOutput: dict | None = None
    aiMonitoringSummary: str | None = None
    # Board brief
    boardBrief: PortfolioBriefOut | None = None
    latestReview: PeriodicReviewOut | None = None
    lastReviewedAt: dt.datetime | None = None


# ── Pipeline Ingest Job observability ─────────────────────────────────


class IngestJobOut(BaseModel):
    """Read-only view of a PipelineIngestJob record."""

    id: uuid.UUID
    fundId: uuid.UUID | str
    status: str
    startedAt: dt.datetime
    finishedAt: dt.datetime | None = None
    documentsDiscovered: int = 0
    documentsBridged: int = 0
    documentsIngested: int = 0
    documentsFailed: int = 0
    chunksCreated: int = 0
    errorSummary: dict | None = None

    @classmethod
    def from_orm_row(cls, row) -> IngestJobOut:
        """Create from a PipelineIngestJob ORM instance."""
        return cls(
            id=row.id,
            fundId=row.fund_id,
            status=row.status if isinstance(row.status, str) else row.status.value,
            startedAt=row.started_at,
            finishedAt=row.finished_at,
            documentsDiscovered=row.documents_discovered or 0,
            documentsBridged=row.documents_bridged or 0,
            documentsIngested=row.documents_ingested or 0,
            documentsFailed=row.documents_failed or 0,
            chunksCreated=row.chunks_created or 0,
            errorSummary=row.error_summary,
        )


# ─────────────────────────────────────────────────────────────────
#  Deep Review V4 — Tier-1 Institutional Memorandum OS
# ─────────────────────────────────────────────────────────────────

class DeepReviewV4Request(BaseModel):
    actor_id: str = Field(default="ai-engine", description="Who triggered the review")
    force: bool = Field(default=False, description="Skip cache and regenerate from scratch")


class MemoChapterOut(BaseModel):
    """Single chapter of the 13-chapter memo book."""

    chapter_number: int
    chapter_tag: str
    chapter_title: str
    content_md: str | None = None
    model_version: str | None = None
    token_count_input: int | None = None
    token_count_output: int | None = None
    generated_at: dt.datetime | None = None


class MemoChapterSummary(BaseModel):
    """Lightweight chapter summary (no content — used in list responses)."""

    chapter_number: int
    chapter_tag: str
    chapter_title: str


class DealDeepReviewV4Response(BaseModel):
    """Response for a single-deal V4 deep review run."""

    dealId: str
    dealName: str | None = None
    pipelineVersion: str = "v4"
    versionTag: str | None = None
    evidencePackId: str | None = None
    evidencePackTokens: int | None = None
    chaptersCompleted: int = 0
    chaptersTotal: int = 13
    chapters: list[MemoChapterSummary] = []
    criticConfidence: float | None = None
    criticFatalFlaws: int = 0
    criticRewriteRequired: bool = False
    finalConfidence: float | None = None
    quantStatus: str | None = None
    concentrationBreached: bool = False
    policyStatus: str | None = None
    sponsorFlags: int = 0
    macroStressFlag: bool = False
    tokenUsage: dict | None = None
    asOf: dt.datetime | None = None
    cachedResult: bool = False
    error: str | None = None


class DeepReviewV4BatchResponse(BaseModel):
    """Response for batch V4 deep review across all deals."""

    asOf: dt.datetime
    pipelineVersion: str = "v4"
    totalDeals: int = 0
    reviewed: int = 0
    errors: int = 0
    results: list[DealDeepReviewV4Response] = []


class MemoChaptersResponse(DataEnvelope):
    """All chapters for a deal's current evidence pack."""

    dealId: str
    evidencePackId: str | None = None
    versionTag: str | None = None
    chapters: list[MemoChapterOut] = []


class EvidencePackResponse(DataEnvelope):
    """Frozen evidence pack for a deal."""

    dealId: str
    evidencePackId: str | None = None
    versionTag: str | None = None
    tokenCount: int | None = None
    generatedAt: dt.datetime | None = None
    modelVersion: str | None = None
    evidenceJson: dict | None = None


# ─────────────────────────────────────────────────────────────────
#  Memo Chapter Versioning & Reassembly (B1/B2/B3 endpoints)
# ─────────────────────────────────────────────────────────────────


class MemoChapterVersionItem(BaseModel):
    chapter_number: int
    chapter_tag: str
    chapter_title: str
    version_tag: str | None = None
    model_version: str | None = None
    generated_at: dt.datetime | None = None
    content_preview: str | None = None
    evidence_pack_id: str | None = None


class MemoChapterVersionsResponse(BaseModel):
    deal_id: str
    chapters: list[MemoChapterVersionItem]
    total_chapters: int
    version_mix: bool


class MemoChapterRegenerateRequest(BaseModel):
    actor_id: str = "ai-engine"
    version_tag: str = "v4-rerun-http"


class MemoChapterRegenerateResponse(BaseModel):
    deal_id: str
    chapter_number: int
    chapter_tag: str
    chapter_title: str
    version_tag: str
    model_version: str
    generated_at: dt.datetime
    content_md: str
    chars: int


# ─────────────────────────────────────────────────────────────────
#  Critical Gaps — approval-blocking data gaps across memo chapters
# ─────────────────────────────────────────────────────────────────


class CriticalGapItem(BaseModel):
    """A single approval-blocking data gap flagged during IC Memo generation."""

    chapter_tag: str
    chapter_num: int
    chapter_title: str
    gap: str


class CriticalGapsResponse(DataEnvelope):
    """Structured critical_gaps for a pipeline deal, aggregated across all memo chapters."""

    dealId: str
    totalGaps: int = 0
    gaps: list[CriticalGapItem] = []
    artifactVersion: int | None = None
    generatedAt: dt.datetime | None = None

