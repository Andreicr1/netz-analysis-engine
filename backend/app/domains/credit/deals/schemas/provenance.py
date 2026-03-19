"""Pydantic schemas for AI provenance, memo timeline, and decision audit."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

_LAYER_LABELS: dict[int, str] = {
    1: "Rule-based",
    2: "Embedding similarity",
    3: "LLM fallback",
}


def layer_label(layer: int | None) -> str | None:
    if layer is None:
        return None
    return _LAYER_LABELS.get(layer)


# ── AI Provenance ─────────────────────────────────────────────────


class AIProvenanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    classification_result: str
    classification_confidence: float | None = None
    classification_layer: int | None = None
    classification_layer_label: str | None = None
    classification_model: str | None = None
    routing_basis: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    processed_at: datetime | None = None
    review_count: int = 0
    current_review_status: str | None = None


# ── Memo Timeline ─────────────────────────────────────────────────


class MemoTimelineEventOut(BaseModel):
    event_type: str
    version: int | None = None
    actor_id: str | None = None
    actor_email: str | None = None
    actor_capacity: str | None = None
    rationale: str | None = None
    timestamp: datetime
    metadata: dict[str, Any] | None = None


class MemoTimelineOut(BaseModel):
    deal_id: uuid.UUID
    memo_count: int
    events: list[MemoTimelineEventOut]
    computed_at: datetime


# ── Decision Audit ────────────────────────────────────────────────


class DecisionAuditEventOut(BaseModel):
    event_type: str
    from_stage: str | None = None
    to_stage: str | None = None
    action: str
    actor_id: str | None = None
    actor_email: str | None = None
    actor_capacity: str | None = None
    rationale: str | None = None
    timestamp: datetime
    metadata: dict[str, Any] | None = None


class DecisionAuditOut(BaseModel):
    deal_id: uuid.UUID
    events: list[DecisionAuditEventOut]
    total_events: int
    computed_at: datetime
