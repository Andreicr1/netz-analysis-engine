"""
Compliance Global Intelligence Agent — API routes.

POST /compliance/agent/query
  Request:  { "question": str, "domain": str|null }
  Response: { "answer": str, "citations": [...], "chunks_used": int, "domain_filter": str|null }
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.domains.credit.compliance.agent.compliance_agent import ComplianceGlobalAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compliance/agent", tags=["compliance-agent"])


# ------------------------------------------------------------------ #
# Request / Response models                                           #
# ------------------------------------------------------------------ #
class AgentQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000, description="Compliance question")
    domain: str | None = Field(
        default=None,
        description="Optional domain filter: REGULATORY | CONSTITUTION | SERVICE_PROVIDER",
    )


class AgentCitation(BaseModel):
    chunk_id: str
    doc_type: str
    authority: str
    source_blob: str
    search_score: float | None = None
    last_modified: str | None = None


class CrossValidationClaim(BaseModel):
    claim_type: str
    claim_text: str
    confirming_chunks: int
    status: str  # CONFIRMED | WEAK | UNCONFIRMED


class CrossValidationResult(BaseModel):
    has_critical_claims: bool
    claims: list[CrossValidationClaim]
    overall_status: str  # CONFIRMED | REVIEW_REQUIRED | NO_CRITICAL_CLAIMS


class ConfidenceComponents(BaseModel):
    search_score_avg: float = 0.0
    domain_purity: float = 0.0
    source_diversity: float = 0.0
    chunk_count_factor: float = 0.0


class LastModifiedRange(BaseModel):
    earliest: str | None = None
    latest: str | None = None


class RecencyAnalysis(BaseModel):
    revisions_detected: list[str] = []
    most_recent: str | None = None
    mixed_revisions: bool = False
    outdated_chunks: list[str] = []
    recency_warning: str | None = None
    last_modified_range: LastModifiedRange = LastModifiedRange()


class AgentQueryResponse(BaseModel):
    answer: str
    citations: list[AgentCitation]
    chunks_used: int
    domain_filter: str | None = None
    # Hardening fields
    retrieval_confidence: float = 0.0
    confidence_components: ConfidenceComponents = ConfidenceComponents()
    cross_validation: CrossValidationResult = CrossValidationResult(
        has_critical_claims=False, claims=[], overall_status="NO_CRITICAL_CLAIMS"
    )
    recency: RecencyAnalysis = RecencyAnalysis()


# ------------------------------------------------------------------ #
# Route                                                               #
# ------------------------------------------------------------------ #
@router.post("/query", response_model=AgentQueryResponse)
def query_agent(payload: AgentQueryRequest):
    """
    Ask the Compliance Intelligence Agent a question.
    The agent retrieves evidence from Azure AI Search indexes,
    grounds its answer exclusively on those chunks, and returns
    structured citations.
    """
    logger.info(
        "AGENT_API /query question=%r domain=%s",
        payload.question[:80],
        payload.domain,
    )

    agent = ComplianceGlobalAgent()
    result = agent.answer(
        question=payload.question,
        domain=payload.domain,
    )

    return result
