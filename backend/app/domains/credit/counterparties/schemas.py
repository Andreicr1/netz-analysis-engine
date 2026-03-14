from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.domains.credit.counterparties.enums import (
    BankAccountChangeStatus,
    BankAccountChangeType,
    CounterpartyEntityType,
    CounterpartyStatus,
    DocumentRole,
    ServiceType,
)

# ── Counterparty ─────────────────────────────────────────────────────

class _CounterpartyIsoMixin(BaseModel):
    @field_validator("country_of_incorporation", "tax_jurisdiction", check_fields=False)
    @classmethod
    def uppercase_iso(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class CounterpartyCreate(_CounterpartyIsoMixin):
    entity_type: CounterpartyEntityType
    legal_name: str = Field(min_length=1, max_length=500)
    trading_name: str | None = Field(default=None, max_length=500)
    country_of_incorporation: str | None = Field(default=None, min_length=3, max_length=3)
    registration_number: str | None = Field(default=None, max_length=100)
    deal_id: uuid.UUID | None = None
    pipeline_deal_id: uuid.UUID | None = None
    lei: str | None = Field(default=None, max_length=20)
    tax_jurisdiction: str | None = Field(default=None, min_length=3, max_length=3)
    service_type: ServiceType | None = None
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    contract_value: Decimal | None = None
    notes: str | None = Field(default=None, max_length=5000)


class CounterpartyUpdate(_CounterpartyIsoMixin):
    legal_name: str | None = Field(default=None, min_length=1, max_length=500)
    trading_name: str | None = None
    country_of_incorporation: str | None = Field(default=None, min_length=3, max_length=3)
    registration_number: str | None = None
    lei: str | None = Field(default=None, max_length=20)
    tax_jurisdiction: str | None = Field(default=None, min_length=3, max_length=3)
    service_type: ServiceType | None = None
    contract_start_date: date | None = None
    contract_end_date: date | None = None
    contract_value: Decimal | None = None
    notes: str | None = Field(default=None, max_length=5000)


class CounterpartyRead(BaseModel):
    id: uuid.UUID
    fund_id: uuid.UUID
    entity_type: CounterpartyEntityType
    legal_name: str
    trading_name: str | None
    country_of_incorporation: str | None
    registration_number: str | None
    status: CounterpartyStatus
    deal_id: uuid.UUID | None
    pipeline_deal_id: uuid.UUID | None
    lei: str | None
    tax_jurisdiction: str | None
    service_type: ServiceType | None
    contract_start_date: date | None
    contract_end_date: date | None
    contract_value: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None

    model_config = {"from_attributes": True}


class CounterpartyListResponse(BaseModel):
    items: list[CounterpartyRead]
    total: int


# ── Bank Account ─────────────────────────────────────────────────────

class BankAccountRead(BaseModel):
    id: uuid.UUID
    counterparty_id: uuid.UUID
    label: str
    currency: str
    bank_name: str
    account_number: str
    swift_code: str
    iban: str | None
    intermediary_bank: str | None
    intermediary_swift: str | None
    is_primary: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Bank Account Change (four-eyes) ─────────────────────────────────

ALLOWED_BANK_FIELDS: frozenset[str] = frozenset({
    "label", "currency", "bank_name", "account_number", "swift_code",
    "iban", "intermediary_bank", "intermediary_swift", "is_primary",
})


class BankAccountChangeRequest(BaseModel):
    """Payload for requesting a bank account create/update/deactivate."""
    change_type: BankAccountChangeType
    bank_account_id: uuid.UUID | None = None
    payload: dict = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def validate_payload_keys(cls, v: dict) -> dict:
        bad_keys = set(v.keys()) - ALLOWED_BANK_FIELDS
        if bad_keys:
            raise ValueError(f"Disallowed payload fields: {bad_keys}")
        return v


class BankAccountChangeRead(BaseModel):
    id: uuid.UUID
    bank_account_id: uuid.UUID | None
    counterparty_id: uuid.UUID
    change_type: BankAccountChangeType
    payload: dict | None
    status: BankAccountChangeStatus
    requested_by: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BankAccountChangeReview(BaseModel):
    """Approve or reject a pending bank account change."""
    approved: bool
    review_notes: str | None = Field(default=None, max_length=500)


# ── Counterparty Document Link ───────────────────────────────────────

class CounterpartyDocumentLink(BaseModel):
    document_id: uuid.UUID
    document_role: DocumentRole
    notes: str | None = Field(default=None, max_length=500)


class CounterpartyDocumentRead(BaseModel):
    id: uuid.UUID
    counterparty_id: uuid.UUID
    document_id: uuid.UUID
    document_role: DocumentRole
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
