from __future__ import annotations

import datetime as dt
import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int


class SignatureEvidenceOut(BaseModel):
    document_id: uuid.UUID
    title: str
    source_blob: str | None = None


class DirectorSignatureOut(BaseModel):
    director_id: str
    director_name: str
    status: str = Field(default="SIGNED")
    signed_at_utc: dt.datetime | None = None
    comment: str | None = None


class SignatureRequestOut(BaseModel):
    id: uuid.UUID

    # Normalized signature workflow status (frontend contract)
    status: str

    # Normalized types for UI filters
    type: str

    amount_usd: str
    beneficiary_name: str | None = None
    beneficiary_bank: str | None = None
    beneficiary_account: str | None = None

    purpose: str | None = None
    linked_entity_ref: str | None = None

    created_at_utc: dt.datetime | None = None
    deadline_utc: dt.datetime | None = None

    required_signatures_count: int = Field(default=2)
    current_signatures_count: int = Field(default=0)

    investment_memo_status: str | None = None
    committee_votes_summary: str | None = None


class SignatureRequestDetailOut(BaseModel):
    request: SignatureRequestOut
    evidence: list[SignatureEvidenceOut]
    signatures: list[DirectorSignatureOut]
    esignature_status: str | None = None
    adobe_sign_agreement_id: str | None = None


class SignRequestIn(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class RejectRequestIn(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


# ── Signature Queue schemas ──────────────────────────────────────────


class QueueItemCreateIn(BaseModel):
    """Payload to mark a document for signature from any page."""

    document_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    message: str | None = Field(default=None, max_length=2000)
    source_page: str | None = Field(
        default=None,
        max_length=64,
        description="Page that originated the request: portfolio, pipeline, reporting",
    )
    source_entity_id: uuid.UUID | None = None
    source_entity_type: str | None = Field(
        default=None,
        max_length=64,
        description="Entity type: active_investment, pipeline_deal, report_pack",
    )
    blob_uri: str | None = Field(default=None, max_length=800)


class SignatureQueueItemOut(BaseModel):
    """Queue item as returned to the frontend."""

    id: uuid.UUID
    fund_id: uuid.UUID
    document_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    title: str
    message: str | None = None
    status: str
    source_page: str | None = None
    source_entity_id: uuid.UUID | None = None
    source_entity_type: str | None = None
    blob_uri: str | None = None
    adobe_sign_agreement_id: str | None = None
    signed_blob_uri: str | None = None
    batch_id: uuid.UUID | None = None
    requested_by: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class BatchSendIn(BaseModel):
    """Payload to send one or more queued items for e-signature."""

    queue_item_ids: list[uuid.UUID] = Field(min_length=1)
    message: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional message to include in Adobe Sign agreement emails",
    )


class BatchSendItemResult(BaseModel):
    queue_item_id: uuid.UUID
    success: bool
    adobe_sign_agreement_id: str | None = None
    error: str | None = None


class BatchSendResponse(BaseModel):
    batch_id: uuid.UUID
    total: int
    sent: int
    failed: int
    results: list[BatchSendItemResult]


# ── Prepare / Confirm (2-step DRAFT flow) ────────────────────────────


class PrepareSignatureIn(BaseModel):
    """Payload for the prepare step — creates DRAFT agreements."""

    queue_item_ids: list[uuid.UUID] = Field(min_length=1)


class SignerInfoOut(BaseModel):
    """Signer details shown in the pre-send modal."""

    name: str
    email: str
    role: str = "SIGNER"
    order: int = 1


class FormFieldInfoOut(BaseModel):
    """Form field metadata shown in the pre-send modal."""

    name: str = ""
    input_type: str | None = None
    required: bool = False
    assignee: str | None = None
    page: int | None = None


class PreparedDocumentOut(BaseModel):
    """One prepared document — DRAFT agreement ready for review."""

    queue_item_id: uuid.UUID
    title: str
    agreement_id: str
    signers: list[SignerInfoOut] = []
    form_fields: list[FormFieldInfoOut] = []
    preview_url: str | None = None


class PrepareSignatureResponse(BaseModel):
    """Response from the prepare step."""

    documents: list[PreparedDocumentOut] = []
    errors: list[dict] = []


class ConfirmSendIn(BaseModel):
    """Payload to transition DRAFT agreements to IN_PROCESS."""

    agreement_ids: list[str] = Field(min_length=1)
    message: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional message (logged only — already embedded in DRAFT)",
    )


class ConfirmSendItemResult(BaseModel):
    agreement_id: str
    success: bool
    error: str | None = None


class ConfirmSendResponse(BaseModel):
    total: int
    sent: int
    failed: int
    results: list[ConfirmSendItemResult]
