from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.domains.credit.deals.enums import DealStage, DealType, RejectionCode


class DealCreate(BaseModel):
    deal_type: DealType
    name: str
    sponsor_name: str | None = None
    description: str | None = None


class DealDecision(BaseModel):
    stage: DealStage
    rationale: str  # min 20 chars enforced below
    actor_capacity: str  # e.g. "portfolio_manager", "ic_member", "analyst"
    actor_email: EmailStr
    rejection_code: RejectionCode | None = None
    rejection_notes: str | None = None

    @field_validator("rationale")
    @classmethod
    def rationale_min_length(cls, v: str) -> str:
        if len(v) < 20:
            msg = "rationale must be at least 20 characters"
            raise ValueError(msg)
        return v


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID

    deal_type: DealType
    stage: DealStage

    asset_id: uuid.UUID | None = None

    name: str
    sponsor_name: str | None
    description: str | None

    rejection_code: RejectionCode | None
    rejection_notes: str | None

    monitoring_output: dict[str, Any] | None = None
    marketing_thesis: dict[str, Any] | None = None

    rationale: str | None = None
    actor_capacity: str | None = None
    decided_at: datetime | None = None

    pipeline_deal_id: uuid.UUID | None = None

    created_at: datetime
    updated_at: datetime


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

    committee_members: list[dict[str, Any]] | None = None
    committee_votes: list[dict[str, Any]] | None = None
    esignature_status: str | None = None

    created_at: datetime
    updated_at: datetime


class ConditionResolvePayload(BaseModel):
    condition_id: str
    status: Literal["resolved", "waived"]
    evidence_docs: list[str] = []
    notes: str | None = None

