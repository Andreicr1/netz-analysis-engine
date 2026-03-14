"""Validation schemas for the deep review benchmark and IC memo eval framework.

This module now serves two parallel use cases:
1. The legacy V3-vs-V4 benchmark harness.
2. The new hybrid IC memo evaluation framework.

Every output from the validation pipeline is structured JSON.
No subjective prose without evidence.
"""
from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════
#  Hybrid IC Memo Eval Framework
# ═══════════════════════════════════════════════════════════════════


class TriggerType(StrEnum):
    MANUAL = "manual"
    CI = "ci"
    PROMPT_CHANGE = "prompt_change"
    MODEL_CHANGE = "model_change"


class EvalRunMode(StrEnum):
    EVALUATE_EXISTING_ARTIFACTS = "evaluate_existing_artifacts"
    RUN_AND_EVALUATE = "run_and_evaluate"


class BaselineKind(StrEnum):
    GOLDEN_FIXED = "golden_fixed"
    LAST_PASS = "last_pass"
    NONE = "none"


class RegressionState(StrEnum):
    PASS = "PASS"
    REGRESSION = "REGRESSION"
    IMPROVEMENT = "IMPROVEMENT"
    DATA_ISSUE = "DATA_ISSUE"


class MetricStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    NOT_APPLICABLE = "not_applicable"
    DATA_ISSUE = "data_issue"


class GoldenApprovalStatus(StrEnum):
    SEEDED = "SEEDED"
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"


class MetricResult(BaseModel):
    metric: str
    status: MetricStatus
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    actual: object | None = None
    expected: object | None = None
    reason: str = ""
    details: dict = Field(default_factory=dict)


class LayerScore(BaseModel):
    layer: str
    applicable: bool = True
    status: MetricStatus = MetricStatus.PASS
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    metrics: list[MetricResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blocking: bool = False


class LayerAggregateScore(BaseModel):
    layer1: float | None = Field(default=None, ge=0.0, le=1.0)
    layer2: float | None = Field(default=None, ge=0.0, le=1.0)
    layer3: float | None = Field(default=None, ge=0.0, le=1.0)
    layer4: float | None = Field(default=None, ge=0.0, le=1.0)
    overall: float = Field(default=0.0, ge=0.0, le=1.0)


class BaselineReference(BaseModel):
    kind: BaselineKind = BaselineKind.NONE
    baseline_run_id: uuid.UUID | None = None
    golden_version: str | None = None
    comparable: bool = False
    comparison_warning: str | None = None


class GoldenChapterRecord(BaseModel):
    chapter_number: int = Field(ge=1, le=14)
    chapter_tag: str
    chapter_title: str
    version_tag: str = ""
    model_version: str = ""
    prompt_manifest_hash: str = ""
    text: str = ""
    citations: list[dict] = Field(default_factory=list)
    decision_anchor_snapshot: dict | None = None
    notes: str = ""


class GoldenDealManifest(BaseModel):
    deal_slug: str
    deal_name: str
    approval_status: GoldenApprovalStatus = GoldenApprovalStatus.SEEDED
    golden_version: str
    prompt_manifest_hash: str = ""
    created_at: dt.datetime
    chapters: list[GoldenChapterRecord] = Field(default_factory=list)


class EvalChapterScore(BaseModel):
    run_id: uuid.UUID
    deal_id: str
    deal_name: str | None = None
    chapter_number: int = Field(ge=1, le=14)
    chapter_tag: str
    chapter_title: str
    memo_version_tag: str = ""
    model_version: str = ""
    golden_version: str | None = None
    baseline: BaselineReference = Field(default_factory=BaselineReference)
    is_applicable_layer1: bool = True
    is_applicable_layer2: bool = True
    layer1: LayerScore = Field(default_factory=lambda: LayerScore(layer="layer1"))
    layer2: LayerScore = Field(default_factory=lambda: LayerScore(layer="layer2"))
    layer3: LayerScore = Field(default_factory=lambda: LayerScore(layer="layer3"))
    layer4: LayerScore = Field(default_factory=lambda: LayerScore(layer="layer4"))
    aggregate: LayerAggregateScore = Field(default_factory=LayerAggregateScore)
    classification: RegressionState = RegressionState.DATA_ISSUE
    classification_reason: str = ""
    comparison_summary: dict = Field(default_factory=dict)
    provider_info: dict = Field(default_factory=dict)


class EvalDealSummary(BaseModel):
    deal_id: str
    deal_name: str | None = None
    memo_version_tag: str = ""
    model_version: str = ""
    chapter_count_found: int = 0
    chapter_count_expected: int = 14
    chapter_scores: list[EvalChapterScore] = Field(default_factory=list)
    aggregate_score: float = Field(default=0.0, ge=0.0, le=1.0)
    classification: RegressionState = RegressionState.DATA_ISSUE
    classification_reason: str = ""
    blocking_layer: str | None = None
    is_comparable: bool = False
    baseline_kind: BaselineKind = BaselineKind.NONE


class EvalRunSummary(BaseModel):
    deals_evaluated: int = 0
    chapters_evaluated: int = 0
    layer_score_averages: dict = Field(default_factory=dict)
    aggregate_score: float = Field(default=0.0, ge=0.0, le=1.0)
    regressions: int = 0
    improvements: int = 0
    data_issues: int = 0
    passes: int = 0


class EvalRunReport(BaseModel):
    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    trigger_type: TriggerType = TriggerType.MANUAL
    run_mode: EvalRunMode = EvalRunMode.EVALUATE_EXISTING_ARTIFACTS
    golden_set_name: str = "ic_memo_default"
    baseline_kind: BaselineKind = BaselineKind.NONE
    baseline_run_id: uuid.UUID | None = None
    prompt_manifest_hash: str = ""
    model_manifest_hash: str = ""
    provider_manifest: dict = Field(default_factory=dict)
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    status: str = "completed"
    classification: RegressionState = RegressionState.DATA_ISSUE
    classification_reason: str = ""
    blocking_layer: str | None = None
    is_comparable: bool = False
    deal_summaries: list[EvalDealSummary] = Field(default_factory=list)
    summary: EvalRunSummary = Field(default_factory=EvalRunSummary)


class EvalRunRequest(BaseModel):
    deal_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Deals to evaluate. If omitted, the runner auto-selects.",
    )
    sample_size: int = Field(default=3, ge=1, le=10)
    actor_id: str = Field(default="validation-harness")
    trigger_type: TriggerType = TriggerType.MANUAL
    run_mode: EvalRunMode = EvalRunMode.EVALUATE_EXISTING_ARTIFACTS
    golden_set_name: str = "ic_memo_default"
    force_rerun: bool = False


class EvalRunResponse(BaseModel):
    run_id: uuid.UUID
    classification: RegressionState
    classification_reason: str
    status: str
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    summary: EvalRunSummary
    deal_summaries: list[EvalDealSummary] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  A)  Recommendation Divergence
# ═══════════════════════════════════════════════════════════════════

class RecommendationDivergence(BaseModel):
    v3_recommendation: str = ""
    v4_recommendation: str = ""
    material_divergence: bool = False
    divergence_direction: str | None = Field(
        default=None,
        description="e.g. 'APPROVE→CONDITIONAL', 'CONDITIONAL→REJECT'",
    )


# ═══════════════════════════════════════════════════════════════════
#  B)  Risk Flag Coverage Delta
# ═══════════════════════════════════════════════════════════════════

class RiskFlagCoverageDelta(BaseModel):
    risk_flags_v3: int = 0
    risk_flags_v4: int = 0
    new_flags_detected: list[str] = Field(default_factory=list)
    lost_flags: list[str] = Field(default_factory=list)
    severity_delta: float = 0.0


# ═══════════════════════════════════════════════════════════════════
#  C)  Sponsor & Key Person Impact
# ═══════════════════════════════════════════════════════════════════

class SponsorImpact(BaseModel):
    sponsor_present: bool = False
    sponsor_red_flags: int = 0
    impact_on_final: str = Field(
        default="none",
        description="'none' | 'minor' | 'material' | 'disqualifying'",
    )


# ═══════════════════════════════════════════════════════════════════
#  D)  Evidence Density & Citation Quality
# ═══════════════════════════════════════════════════════════════════

class EvidenceDensity(BaseModel):
    evidence_surface_tokens: int = 0
    citations_used: int = 0
    unsupported_claims_detected: bool = False


# ═══════════════════════════════════════════════════════════════════
#  E)  Internal Consistency Score
# ═══════════════════════════════════════════════════════════════════

class InternalConsistency(BaseModel):
    consistency_score: float = Field(default=1.0, ge=0.0, le=1.0)
    contradictions: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  Combined Delta Report (per deal)
# ═══════════════════════════════════════════════════════════════════

class DeepReviewDeltaReport(BaseModel):
    deal_id: str
    deal_name: str | None = None
    recommendation: RecommendationDivergence = Field(default_factory=RecommendationDivergence)
    risk_flags: RiskFlagCoverageDelta = Field(default_factory=RiskFlagCoverageDelta)
    sponsor: SponsorImpact = Field(default_factory=SponsorImpact)
    evidence: EvidenceDensity = Field(default_factory=EvidenceDensity)
    consistency: InternalConsistency = Field(default_factory=InternalConsistency)


# ═══════════════════════════════════════════════════════════════════
#  Engine Score (deterministic quality verdict)
# ═══════════════════════════════════════════════════════════════════

class EngineScore(BaseModel):
    engine_winner: str = Field(description="'V3' | 'V4' | 'TIE'")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


# ═══════════════════════════════════════════════════════════════════
#  Per-Deal Validation Result
# ═══════════════════════════════════════════════════════════════════

class DealValidationResult(BaseModel):
    deal_id: str
    deal_name: str | None = None
    v3_version_tag: str | None = None
    v4_version_tag: str | None = None
    v3_error: str | None = None
    v4_error: str | None = None
    delta: DeepReviewDeltaReport | None = None
    engine_score: EngineScore | None = None


# ═══════════════════════════════════════════════════════════════════
#  Top-Level Validation Report
# ═══════════════════════════════════════════════════════════════════

class DeepReviewValidationReport(BaseModel):
    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    deals_tested: int = 0
    deal_results: list[DealValidationResult] = Field(default_factory=list)
    aggregate_score: EngineScore | None = None
    winner: str = ""
    institutional_decision: str = ""


# ═══════════════════════════════════════════════════════════════════
#  API Request / Response schemas
# ═══════════════════════════════════════════════════════════════════

class ValidationSampleRequest(BaseModel):
    deal_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Specific deals to benchmark. If omitted, auto-selects first 3.",
    )
    sample_size: int = Field(default=3, ge=1, le=3)
    actor_id: str = Field(default="validation-harness")


class ValidationSampleResponse(BaseModel):
    run_id: uuid.UUID
    deals_tested: int
    winner: str
    institutional_decision: str
    aggregate_score: EngineScore | None = None
    deal_results: list[DealValidationResult] = []
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
