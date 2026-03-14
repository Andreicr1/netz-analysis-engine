from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.domains.credit.deals.enums import DealStage, DealType, RejectionCode


class DealCreate(BaseModel):
    deal_type: DealType
    name: str
    sponsor_name: str | None = None
    description: str | None = None


class DealDecision(BaseModel):
    stage: DealStage
    rejection_code: RejectionCode | None = None
    rejection_notes: str | None = None


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID

    deal_type: DealType
    stage: DealStage

    name: str
    sponsor_name: str | None
    description: str | None

    rejection_code: RejectionCode | None
    rejection_notes: str | None


# ---------------------------------------------------------------------------
# IC Memo schemas
# ---------------------------------------------------------------------------


class ICMemoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deal_id: uuid.UUID

    executive_summary: str
    risks: str | None
    mitigants: str | None

    recommendation: str | None
    conditions: list[dict[str, Any]]
    version: int
    memo_blob_url: str | None
    condition_history: list[dict[str, Any]]

    created_at: datetime


class ConditionResolvePayload(BaseModel):
    condition_id: str
    status: Literal["resolved", "waived"]
    evidence_docs: list[str] = []
    notes: str | None = None

