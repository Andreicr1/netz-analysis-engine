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


class DealCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    deal_name: str | None = Field(default=None, max_length=300)
    borrower_name: str | None = Field(default=None, max_length=300)
    requested_amount: float | None = None
    currency: str = Field(default="USD", max_length=3)
    meta: dict | None = Field(default=None, validation_alias="metadata", serialization_alias="metadata")

    # Deal context enrichment fields (NOT stored in DB — flow to deal_context.json on blob)
    target_vehicle: str | None = Field(default=None, max_length=300)
    vehicle_aliases: str | None = Field(default=None, max_length=600)
    domain: str | None = Field(default=None, max_length=120)
    ic_context: str | None = Field(default=None, max_length=4000)


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    title: str
    borrower_name: str | None
    requested_amount: float | None
    currency: str
    stage: str
    is_archived: bool
    rejection_reason_code: str | None
    rejection_rationale: str | None
    meta: dict | None = Field(default=None, serialization_alias="metadata")
    ai_summary: str | None = None
    ai_risk_flags: dict | None = None
    ai_key_terms: dict | None = None
    approved_deal_id: uuid.UUID | None = None
    approved_at: dt.datetime | None = None
    approved_by: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class DealStagePatch(BaseModel):
    to_stage: str = Field(min_length=2, max_length=64)
    rationale: str | None = None


class DealContextPatch(BaseModel):
    """Investment parameters that live only in deal_context.json on blob — no DB columns."""
    geography: str | None = Field(default=None, max_length=300)
    currency: str | None = Field(default=None, max_length=3)
    commitment_usd: str | None = Field(default=None, max_length=64)
    portfolio_weight_max: str | None = Field(default=None, max_length=64)
    return_target_net: str | None = Field(default=None, max_length=300)
    redemption_terms: str | None = Field(default=None, max_length=600)
    liquidity_gate: str | None = Field(default=None, max_length=300)
    borrower: str | None = Field(default=None, max_length=300)


class DealDecisionCreate(BaseModel):
    outcome: str = Field(min_length=2, max_length=32)  # approved/rejected/conditional
    reason_code: str | None = Field(default=None, max_length=64)
    rationale: str = Field(min_length=3)


class DealDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    deal_id: uuid.UUID
    outcome: str
    reason_code: str | None
    rationale: str
    decided_at: dt.datetime


class QualificationRunRequest(BaseModel):
    deal_id: uuid.UUID
    rule_ids: list[uuid.UUID] | None = None


class QualificationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    deal_id: uuid.UUID
    rule_id: uuid.UUID
    result: str  # pass/fail/flag
    reasons: list[dict] | None
    run_at: dt.datetime


class QualificationRunResponse(BaseModel):
    deal: DealOut
    results: list[QualificationResultOut]
    auto_archived: bool = False


class DealDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    deal_id: uuid.UUID
    document_type: str
    filename: str
    status: str
    blob_container: str | None = None
    blob_path: str | None = None
    authority: str | None = None
    last_indexed_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class DealDocumentRegister(BaseModel):
    blob_container: str = Field(min_length=1, max_length=300)
    blob_path: str = Field(min_length=1, max_length=800)
    doc_type: str = Field(min_length=1, max_length=64)
    authority: str = Field(min_length=1, max_length=64)
    filename: str | None = Field(default=None, max_length=300)


# ── IC Approval ───────────────────────────────────────────────────────


class DealApproveRequest(BaseModel):
    deal_type: str | None = Field(default=None, max_length=64, description="DealType enum value — auto-derived from research_output if omitted")
    rationale: str | None = Field(default=None, max_length=4000)
    sponsor_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000, description="IC approval notes")


class DealApproveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pipeline_deal: DealOut
    portfolio_deal_id: uuid.UUID
    active_investment_id: uuid.UUID | None = None
    approved_at: dt.datetime
    approved_by: str
    status: str = "converted"


# ── Deal Cashflows ────────────────────────────────────────────────────


class DealCashflowCreate(BaseModel):
    flow_type: str = Field(min_length=2, max_length=64, description="disbursement|repayment_principal|repayment_interest|fee|distribution|capital_call")
    amount: float
    currency: str = Field(default="USD", max_length=3)
    flow_date: dt.date
    description: str | None = Field(default=None, max_length=2000)
    reference: str | None = Field(default=None, max_length=120)


class DealCashflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deal_id: uuid.UUID
    fund_id: uuid.UUID
    flow_type: str
    amount: float
    currency: str
    flow_date: dt.date
    description: str | None
    reference: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


# ── Deal Performance ─────────────────────────────────────────────────


class DealPerformanceOut(BaseModel):
    deal_id: uuid.UUID
    total_invested: float
    total_received: float
    net_cashflow: float
    moic: float | None = None
    cash_to_cash_days: int | None = None
    cashflow_count: int


# ── Portfolio Monitoring ─────────────────────────────────────────────


class CashflowEventOut(BaseModel):
    id: str
    event_date: str
    event_type: str
    amount: float
    currency: str
    notes: str = ""


class MonitoringMetricsOut(BaseModel):
    deal_id: uuid.UUID
    total_contributions: float
    total_distributions: float
    interest_received: float
    principal_returned: float
    net_cash_position: float
    cash_to_cash_multiple: float | None = None
    irr_estimate: float | None = None
    cashflow_events: list[CashflowEventOut] = []
    computed_at: dt.datetime


# ── Deal Events ──────────────────────────────────────────────────────


class DealEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deal_id: uuid.UUID | None
    pipeline_deal_id: uuid.UUID | None
    fund_id: uuid.UUID
    event_type: str
    actor_id: str
    payload: dict | None
    created_at: dt.datetime


class DealAIOutputUpdate(BaseModel):
    ai_summary: str | None = None
    ai_risk_flags: dict | list[dict] | None = None
    ai_key_terms: dict | list[dict] | None = None

