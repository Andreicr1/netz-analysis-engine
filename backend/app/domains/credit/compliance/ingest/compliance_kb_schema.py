"""
Pydantic schemas for the Unified Compliance Knowledge Base.
Covers: Fund Constitution · Service Provider Contracts · CIMA Regulation
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ComplianceDomain = Literal[
    "REGULATORY",
    "CONSTITUTION",
    "SERVICE_PROVIDER",
    "PIPELINE",
]

DocType = Literal[
    "CIMA_HANDBOOK",
    "CIMA_REGULATION",
    "LPA",
    "IMA",
    "SUBSCRIPTION_DOC",
    "ENGAGEMENT_LETTER",
    "OTHER",
]


class ComplianceDocument(BaseModel):
    doc_id: str
    title: str
    domain: ComplianceDomain
    doc_type: DocType

    jurisdiction: str = "CAYMAN"
    provider: str | None = None

    source_blob: str
    effective_date: str | None = None

    ingested_at: str = Field(
        default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    )


class ComplianceChunk(BaseModel):
    chunk_id: str
    doc_id: str

    domain: ComplianceDomain
    doc_type: DocType

    source_blob: str
    chunk_text: str

    obligation_candidate: bool = False
    extraction_confidence: float = 0.5

    source_snippet: str | None = None

    # Search-time metadata (populated by adapter, not persisted)
    search_score: float | None = None
    last_modified: str | None = None
