"""Pydantic v2 schemas for DuckDB data lake inspection endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class StaleEmbeddingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    chunk_count: int
    embedding_model: str


class DocumentCoverageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    doc_type: str
    chunk_count: int
    total_chars: int
    has_embeddings: bool


class ExtractionQualityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    doc_type: str
    total_chunks: int
    empty_chunks: int
    governance_flagged: int
    avg_char_count: float


class ChunkStatsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_chunks: int
    total_documents: int
    total_chars: int
    avg_chunk_chars: float
    median_chunk_chars: float
    p95_chunk_chars: float
    doc_type_distribution: dict[str, int]
    org_id: uuid.UUID
    vertical: str
    queried_at: datetime


class DimensionMismatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    chunk_count: int
    embedding_dim: int


class InspectResultOut(BaseModel, Generic[T]):
    results: list[T]
    count: int
    org_id: uuid.UUID
    vertical: str
    queried_at: datetime
