"""Knowledge-base chunk schema for pgvector retrieval.

Cross-cutting retrieval data types used by the pipeline KB adapter
and global agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Document type taxonomy used across all retrieval indexes
DocType = Literal[
    "TERM_SHEET",
    "CREDIT_AGREEMENT",
    "FACILITY_AGREEMENT",
    "LOAN_AGREEMENT",
    "SECURITY_AGREEMENT",
    "INTERCREDITOR",
    "GUARANTEE",
    "PLEDGE",
    "LEGAL",
    "FINANCIAL",
    "FINANCIAL_STATEMENTS",
    "FUND_CONSTITUTION",
    "FUND_POLICY",
    "SUBSCRIPTION_AGREEMENT",
    "SIDE_LETTER",
    "COMPLIANCE",
    "REGULATORY",
    "RISK_ASSESSMENT",
    "RISK",
    "COVENANT",
    "COVENANT_COMPLIANCE",
    "MONITORING",
    "INSURANCE",
    "WATCHLIST",
    "OTHER",
]


@dataclass
class ComplianceChunk:
    """A single evidence chunk from pgvector retrieval.

    Despite the name, this is used across all domains (pipeline,
    regulatory, constitution, service providers).
    """

    chunk_id: str
    doc_id: str
    domain: str
    doc_type: str
    source_blob: str
    chunk_text: str
    obligation_candidate: bool = False
    extraction_confidence: float = 0.5
    search_score: float | None = None
    last_modified: str | None = None
    root_folder: str | None = None
    metadata: dict = field(default_factory=dict)
