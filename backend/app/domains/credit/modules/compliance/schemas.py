from __future__ import annotations

import datetime as dt
import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ObligationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    regulator: str | None = Field(default=None, max_length=64)
    description: str | None = None
    is_active: bool = True
    source_type: str | None = Field(default=None, max_length=32)  # CIMA | LPA | IMA | SERVICE_CONTRACT
    frequency: str | None = Field(default=None, max_length=32)  # ANNUAL | QUARTERLY | MONTHLY | AD_HOC
    next_due_date: dt.date | None = None
    risk_level: str | None = Field(default=None, max_length=16)  # HIGH | MEDIUM | LOW
    responsible_party: str | None = Field(default=None, max_length=200)
    document_reference: str | None = Field(default=None, max_length=500)
    legal_basis: str | None = Field(default=None, max_length=500)


class ObligationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    name: str
    regulator: str | None
    description: str | None
    is_active: bool
    source_type: str | None = None
    frequency: str | None = None
    next_due_date: dt.date | None = None
    risk_level: str | None = None
    responsible_party: str | None = None
    document_reference: str | None = None
    legal_basis: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class ObligationWorkflowOut(ObligationOut):
    workflow_status: str = Field(default="OPEN", max_length=32)
    display_status: str = Field(default="PENDING", max_length=32)  # PENDING | IN_PROGRESS | COMPLETED | OVERDUE


class ObligationEvidenceLinkIn(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID | None = None


class ObligationEvidenceOut(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID | None
    title: str
    root_folder: str | None
    folder_path: str | None
    linked_at: dt.datetime
    linked_by: str


class ActorMeOut(BaseModel):
    actor_id: str
    roles: list[str]


class ComplianceSnapshotOut(BaseModel):
    generated_at_utc: dt.datetime
    total_open_obligations: int
    total_ai_gaps: int
    closed_obligations_last_30_days: int


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: dt.datetime
    actor_id: str
    actor_roles: list[str]
    action: str
    entity_type: str
    entity_id: str
    before: dict | None
    after: dict | None
    request_id: str


class ObligationStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    obligation_id: uuid.UUID
    status: str
    last_computed_at: dt.datetime
    details: dict | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ObligationRequirementCreate(BaseModel):
    doc_type: str = Field(min_length=2, max_length=100)
    periodicity: str | None = Field(default=None, max_length=32)  # monthly | quarterly | annual | once
    expiry_days: int | None = None
    is_required: bool = True
    meta: dict | None = None


class ObligationRequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    obligation_id: uuid.UUID
    doc_type: str
    periodicity: str | None
    expiry_days: int | None
    is_required: bool
    meta: dict | None
    created_at: dt.datetime
    updated_at: dt.datetime

