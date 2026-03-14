"""Pydantic schemas for Adobe Sign API payloads and responses."""

from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────────


class AgreementState(str, Enum):
    """Adobe Sign agreement lifecycle states."""

    DRAFT = "DRAFT"
    AUTHORING = "AUTHORING"
    IN_PROCESS = "IN_PROCESS"
    SIGNED = "SIGNED"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    OUT_FOR_SIGNATURE = "OUT_FOR_SIGNATURE"


class SignatureType(str, Enum):
    ESIGN = "ESIGN"


class RecipientRole(str, Enum):
    SIGNER = "SIGNER"
    APPROVER = "APPROVER"


class WebhookScope(str, Enum):
    ACCOUNT = "ACCOUNT"
    USER = "USER"
    RESOURCE = "RESOURCE"


class ESignatureStatus(str, Enum):
    """Application-level e-signature tracking status."""

    NOT_SENT = "NOT_SENT"
    SENT = "SENT"
    IN_PROCESS = "IN_PROCESS"
    SIGNED = "SIGNED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


# ── Transient Document (upload) ────────────────────────────────────────


class TransientDocumentResponse(BaseModel):
    """Response from POST /transientDocuments."""

    transientDocumentId: str


# ── Agreement Creation ─────────────────────────────────────────────────


class FileInfo(BaseModel):
    transientDocumentId: str


class RecipientInfo(BaseModel):
    email: str
    order: int = 1


class ParticipantSetInfo(BaseModel):
    memberInfos: list[RecipientInfo]
    role: str = RecipientRole.SIGNER.value
    order: int = 1


class MergeFieldInfo(BaseModel):
    """Pre-fill a form field in the agreement."""

    fieldName: str
    defaultValue: str


class AgreementCreationRequest(BaseModel):
    """Payload for POST /agreements."""

    fileInfos: list[FileInfo]
    name: str
    participantSetsInfo: list[ParticipantSetInfo]
    signatureType: str = SignatureType.ESIGN.value
    state: str = AgreementState.IN_PROCESS.value
    message: str | None = None
    mergeFieldInfo: list[MergeFieldInfo] | None = None
    externalId: dict[str, str] | None = None


class AgreementCreationResponse(BaseModel):
    """Response from POST /agreements."""

    id: str


# ── Agreement Status ──────────────────────────────────────────────────


class AgreementStatusResponse(BaseModel):
    """Subset of GET /agreements/{id} response."""

    id: str
    name: str
    status: str
    participantSetsInfo: list[dict] | None = None


# ── Form Fields ───────────────────────────────────────────────────────


class FormFieldLocation(BaseModel):
    """Position of a form field on a page."""

    pageNumber: int | None = None
    left: float | None = None
    top: float | None = None
    width: float | None = None
    height: float | None = None


class FormFieldOut(BaseModel):
    """A single form field returned by GET /agreements/{id}/formFields."""

    name: str = ""
    inputType: str | None = None  # TEXT_FIELD, SIGNATURE, CHECK_BOX, etc.
    contentType: str | None = None
    required: bool = False
    assignee: str | None = None
    locations: list[FormFieldLocation] = []


class AgreementViewResponse(BaseModel):
    """Response from POST /agreements/{id}/views (embedded URL)."""

    url: str | None = None
    embeddedCode: str | None = None


# ── Webhook Events ────────────────────────────────────────────────────


class WebhookEventPayload(BaseModel):
    """Adobe Sign webhook event payload (envelope).

    Per the official Adobe Sign API docs, the agreement ID may appear:
      - Nested under ``agreement.id`` (when includeDetailedInfo=true)
      - At the top level as ``agreementId`` (minimal payload)
    Both locations are checked by the ``agreement_id`` property.
    """

    webhookId: str | None = None
    webhookName: str | None = None
    webhookNotificationId: str | None = None
    webhookUrlInfo: dict | None = None
    webhookScope: str | None = None
    event: str  # e.g. AGREEMENT_ACTION_COMPLETED
    subEvent: str | None = None
    eventDate: str | None = None
    eventResourceType: str | None = None
    eventResourceParentType: str | None = None
    eventResourceParentId: str | None = None
    participantUserId: str | None = None
    participantUserEmail: str | None = None
    actingUserId: str | None = None
    actingUserEmail: str | None = None
    actingUserIpAddress: str | None = None
    # AGREEMENT_ACTION_COMPLETED includes actionType:
    # ESIGNED, DIGSIGNED, WRITTEN_SIGNED, PRESIGNED, ACCEPTED, SIGNED,
    # APPROVED, DELIVERED, FORM_FILLED, ACKNOWLEDGED
    actionType: str | None = None
    # Top-level agreement ID (minimal payload, no includeDetailedInfo)
    agreementId: str | None = None
    agreement: dict | None = None  # nested agreement data (detailed payload)

    @property
    def agreement_id(self) -> str | None:
        """Resolve agreement ID from nested or top-level field."""
        if self.agreement and self.agreement.get("id"):
            return self.agreement["id"]
        return self.agreementId

    @property
    def agreement_name(self) -> str | None:
        if self.agreement:
            return self.agreement.get("name")
        return None

    @property
    def agreement_status(self) -> str | None:
        if self.agreement:
            return self.agreement.get("status")
        return None


# ── Webhook Registration ──────────────────────────────────────────────


class WebhookRegistrationRequest(BaseModel):
    """Payload for POST /webhooks."""

    name: str
    scope: str = WebhookScope.ACCOUNT.value
    state: str = "ACTIVE"
    webhookSubscriptionEvents: list[str]
    webhookUrlInfo: dict[str, str]  # {"url": "https://..."}


class WebhookRegistrationResponse(BaseModel):
    id: str


# ── Application-level DTOs ────────────────────────────────────────────


class SendForESignatureRequest(BaseModel):
    """Optional body for the send-for-esignature endpoint."""

    message: str | None = Field(
        default=None,
        max_length=4000,
        description="Custom message to include in the Adobe Sign email",
    )


class SendForESignatureResponse(BaseModel):
    agreement_id: str
    esignature_status: str = ESignatureStatus.SENT.value
    recipients: list[str]
    sent_at: dt.datetime


class SendToCommitteeRequest(BaseModel):
    """Body for the send-to-committee endpoint."""

    committee_member_emails: list[str] = Field(
        ...,
        min_length=3,
        max_length=10,
        description="Email addresses of IC committee members (minimum 3)",
    )
    message: str | None = Field(
        default=None,
        max_length=4000,
        description="Custom message for committee members",
    )


class SendToCommitteeResponse(BaseModel):
    agreement_id: str
    esignature_status: str = ESignatureStatus.SENT.value
    committee_members: list[dict]
    sent_at: dt.datetime


class CommitteeVote(BaseModel):
    """Individual committee member vote record."""

    email: str
    vote: str | None = None  # "APPROVE" | "REFUSE" | None (pending)
    signed_at: str | None = None
    signer_status: str = "PENDING"  # PENDING | COMPLETED | REFUSED
