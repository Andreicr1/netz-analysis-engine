"""Adobe Sign business logic — orchestrates PDF upload, agreement
creation, signed-document archival and status tracking.
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.base import User, UserFundRole
from app.core.security.auth import Actor
from app.domains.credit.cash_management.models.cash import CashTransaction
from app.domains.credit.deals.models.ic_memos import ICMemo
from app.domains.credit.modules.adobe_sign import client as adobe_client
from app.domains.credit.modules.adobe_sign.schemas import (
    AgreementCreationRequest,
    CommitteeVote,
    ESignatureStatus,
    FileInfo,
    ParticipantSetInfo,
    RecipientInfo,
    SendForESignatureResponse,
    SendToCommitteeResponse,
)
from app.domains.credit.modules.signatures import service as signatures_service
from app.services import blob_storage

logger = logging.getLogger(__name__)


# ── Transfer-Order e-signature ────────────────────────────────────────


def get_fund_directors(db: Session, fund_id: uuid.UUID) -> list[User]:
    """Return all active users with DIRECTOR role for a fund."""
    stmt = (
        select(User)
        .join(UserFundRole, UserFundRole.user_id == User.id)
        .where(
            UserFundRole.fund_id == fund_id,
            UserFundRole.role == "DIRECTOR",
            User.is_active.is_(True),
        )
    )
    return list(db.execute(stmt).scalars().all())


def send_transfer_order_for_esignature(
    db: Session,
    *,
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    actor: Actor,
    message: str | None = None,
) -> SendForESignatureResponse:
    """Generate execution pack PDF, upload to Adobe Sign, and create an agreement.

    Recipients are all fund directors.  The agreement ID is stored on
    the CashTransaction for webhook reconciliation.
    """
    from fastapi import HTTPException, status

    # 1. Load the transaction
    tx = db.execute(
        select(CashTransaction).where(
            CashTransaction.fund_id == fund_id,
            CashTransaction.id == tx_id,
        ),
    ).scalar_one_or_none()

    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found",
        )

    if getattr(tx, "adobe_sign_agreement_id", None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transfer order already sent for e-signature",
        )

    # 2. Generate the execution-pack PDF (reuse existing service)
    pack = signatures_service.generate_execution_pack(
        db, fund_id=fund_id, actor=actor, tx_id=tx_id,
    )
    pdf_bytes: bytes | None = pack.get("pdf_bytes")
    if not pdf_bytes:
        # Fallback: download from blob if the service stored it
        blob_uri = pack.get("blob_uri") or getattr(tx, "instructions_blob_uri", None)
        if blob_uri:
            pdf_bytes = blob_storage.download_bytes(blob_uri=blob_uri)

    if not pdf_bytes:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate or retrieve execution pack PDF",
        )

    # 3. Find directors (recipients)
    directors = get_fund_directors(db, fund_id)
    if not directors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No directors found for this fund",
        )

    recipient_emails = [d.email for d in directors if d.email]
    if not recipient_emails:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Directors have no email addresses configured",
        )

    # 4. Upload transient document
    file_name = f"transfer_order_{tx_id}.pdf"
    transient = adobe_client.upload_transient_document(
        file_name=file_name,
        file_bytes=pdf_bytes,
    )

    # 5. Build participant sets (all directors sign in parallel — same order)
    participant_sets = [
        ParticipantSetInfo(
            memberInfos=[RecipientInfo(email=email, order=1)],
            role="SIGNER",
            order=idx + 1,
        )
        for idx, email in enumerate(recipient_emails)
    ]

    # 6. Create agreement
    agreement_name = f"Transfer Order – {tx.beneficiary_name or tx_id}"
    agreement_req = AgreementCreationRequest(
        fileInfos=[FileInfo(transientDocumentId=transient.transientDocumentId)],
        name=agreement_name,
        participantSetsInfo=participant_sets,
        message=message or f"Please review and sign this transfer order ({file_name}).",
        externalId={"id": str(tx_id)},
    )

    agreement_resp = adobe_client.create_agreement(agreement_req)

    # 7. Store agreement ID on the transaction
    tx.adobe_sign_agreement_id = agreement_resp.id  # type: ignore[attr-defined]
    db.flush()

    # 8. Audit trail
    now_utc = datetime.now(UTC)
    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="esignature.transfer_order.sent",
        entity_type="CashTransaction",
        entity_id=str(tx_id),
        before=None,
        after={
            "agreement_id": agreement_resp.id,
            "recipients": recipient_emails,
            "sent_at": now_utc.isoformat(),
        },
    )

    db.commit()

    return SendForESignatureResponse(
        agreement_id=agreement_resp.id,
        esignature_status=ESignatureStatus.SENT.value,
        recipients=recipient_emails,
        sent_at=now_utc,
    )


# ── IC Memo committee voting ─────────────────────────────────────────


def send_ic_memo_to_committee(
    db: Session,
    *,
    memo_id: uuid.UUID,
    committee_member_emails: list[str],
    actor: Actor,
    message: str | None = None,
) -> SendToCommitteeResponse:
    """Download existing IC Memo PDF, create Adobe Sign agreement with
    Approve/Refuse checkboxes + signature fields for each committee member.
    """
    from fastapi import HTTPException, status

    memo = db.execute(select(ICMemo).where(ICMemo.id == memo_id)).scalar_one_or_none()

    if not memo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="IC Memo not found",
        )

    if getattr(memo, "adobe_sign_agreement_id", None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IC Memo already sent to committee",
        )

    if not memo.memo_blob_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="IC Memo has no generated PDF (memo_blob_url is empty)",
        )

    # 1. Download existing PDF from Azure Blob Storage
    pdf_bytes = blob_storage.download_bytes(blob_uri=memo.memo_blob_url)

    # 2. Upload as transient document
    file_name = f"ic_memo_{memo_id}_v{memo.version}.pdf"
    transient = adobe_client.upload_transient_document(
        file_name=file_name,
        file_bytes=pdf_bytes,
    )

    # 3. Build participant sets — each committee member signs independently
    participant_sets = [
        ParticipantSetInfo(
            memberInfos=[RecipientInfo(email=email, order=1)],
            role="SIGNER",
            order=idx + 1,
        )
        for idx, email in enumerate(committee_member_emails)
    ]

    # 4. Create agreement
    agreement_name = f"IC Committee Vote – Memo v{memo.version} ({memo.deal_id})"
    agreement_req = AgreementCreationRequest(
        fileInfos=[FileInfo(transientDocumentId=transient.transientDocumentId)],
        name=agreement_name,
        participantSetsInfo=participant_sets,
        message=message
        or (
            "Please review the IC Memo and cast your vote: "
            "check Approve or Refuse, then sign."
        ),
        externalId={"id": str(memo_id)},
    )

    agreement_resp = adobe_client.create_agreement(agreement_req)

    # 5. Store agreement ID and committee info on the memo
    now_utc = datetime.now(UTC)
    committee_members = [
        CommitteeVote(email=email).model_dump() for email in committee_member_emails
    ]

    memo.adobe_sign_agreement_id = agreement_resp.id  # type: ignore[attr-defined]
    memo.committee_members = committee_member_emails  # type: ignore[attr-defined]
    memo.committee_votes = committee_members  # type: ignore[attr-defined]
    memo.esignature_status = ESignatureStatus.SENT.value  # type: ignore[attr-defined]
    db.flush()

    # 6. Audit trail
    write_audit_event(
        db,
        fund_id=memo.deal_id,  # IC memos don't have fund_id; use deal_id as correlation
        actor_id=actor.actor_id,
        action="esignature.ic_memo.sent_to_committee",
        entity_type="ICMemo",
        entity_id=str(memo_id),
        before=None,
        after={
            "agreement_id": agreement_resp.id,
            "committee_members": committee_member_emails,
            "sent_at": now_utc.isoformat(),
        },
    )

    db.commit()

    return SendToCommitteeResponse(
        agreement_id=agreement_resp.id,
        esignature_status=ESignatureStatus.SENT.value,
        committee_members=committee_members,
        sent_at=now_utc,
    )


# ── Webhook processing — Transfer Orders ─────────────────────────────


def process_transfer_order_webhook(
    db: Session,
    *,
    agreement_id: str,
    event: str,
    participant_email: str | None = None,
) -> dict[str, Any]:
    """Handle Adobe Sign webhook events for transfer-order agreements.

    On AGREEMENT_ACTION_COMPLETED (fully signed):
      1. Download signed PDF from Adobe Sign
      2. Upload to Azure Blob Storage (transfer-orders container, WORM)
      3. Update CashTransaction status to SIGNED
      4. Update document_registry with blob metadata
    """
    from app.core.config.settings import settings as app_settings

    tx = db.execute(
        select(CashTransaction).where(
            CashTransaction.adobe_sign_agreement_id == agreement_id,  # type: ignore[attr-defined]
        ),
    ).scalar_one_or_none()

    if not tx:
        logger.warning("No CashTransaction found for agreement %s", agreement_id)
        return {"status": "ignored", "reason": "agreement not found"}

    if event == "AGREEMENT_ACTION_COMPLETED":
        # Download signed PDF
        signed_pdf = adobe_client.download_signed_document(agreement_id)

        # Upload to Azure Blob Storage
        container = getattr(
            app_settings, "AZURE_BLOB_TRANSFER_ORDERS_CONTAINER", "transfer-orders",
        )
        blob_name = f"{tx.fund_id}/{tx.id}/signed_transfer_order_{agreement_id}.pdf"

        result = blob_storage.upload_bytes(
            container=container,
            blob_name=blob_name,
            data=signed_pdf,
            content_type="application/pdf",
            overwrite=False,
            metadata={
                "agreement_id": agreement_id,
                "transaction_id": str(tx.id),
                "fund_id": str(tx.fund_id),
                "signed_at": datetime.now(UTC).isoformat(),
            },
        )

        # Update transaction
        tx.evidence_bundle_blob_uri = result.blob_uri
        tx.evidence_bundle_sha256 = result.sha256

        # Mark as SIGNED via the status enum
        from app.domains.credit.cash_management.enums import CashTransactionStatus

        tx.status = CashTransactionStatus.SIGNED

        # Update document_registry
        _upsert_document_registry(
            db,
            fund_id=tx.fund_id,
            container_name=container,
            blob_path=blob_name,
            blob_uri=result.blob_uri,
            domain_tag="transfer-order-signed",
            title=f"Signed Transfer Order – {tx.beneficiary_name or tx.id}",
            checksum=result.sha256,
            etag=result.etag,
        )

        write_audit_event(
            db,
            fund_id=tx.fund_id,
            actor_id="adobe-sign-webhook",
            action="esignature.transfer_order.completed",
            entity_type="CashTransaction",
            entity_id=str(tx.id),
            before=None,
            after={
                "agreement_id": agreement_id,
                "blob_uri": result.blob_uri,
                "sha256": result.sha256,
            },
        )

        db.commit()
        logger.info("Transfer order %s signed and archived", tx.id)
        return {"status": "completed", "transaction_id": str(tx.id)}

    logger.info(
        "Ignoring event %s for transfer order agreement %s", event, agreement_id,
    )
    return {"status": "ignored", "event": event}


# ── Webhook processing — IC Memos ────────────────────────────────────


def process_ic_memo_webhook(
    db: Session,
    *,
    agreement_id: str,
    event: str,
    participant_email: str | None = None,
    form_data: dict | None = None,
) -> dict[str, Any]:
    """Handle Adobe Sign webhook events for IC-memo committee voting.

    Tracks per-member votes.  When majority is reached (2+ out of 3):
      - Update recommendation to APPROVED or REJECTED
      - Download signed PDF and archive in Azure Blob Storage
      - Update memo_blob_url to point to signed version
    """
    from app.core.config.settings import settings as app_settings

    memo = db.execute(
        select(ICMemo).where(
            ICMemo.adobe_sign_agreement_id == agreement_id,  # type: ignore[attr-defined]
        ),
    ).scalar_one_or_none()

    if not memo:
        logger.warning("No ICMemo found for agreement %s", agreement_id)
        return {"status": "ignored", "reason": "agreement not found"}

    # ── Signer-level event: record individual vote ────────────────
    if participant_email and event in (
        "AGREEMENT_ACTION_COMPLETED",
        "AGREEMENT_WORKFLOW_COMPLETED",
        "AGREEMENT_ACTION_DELEGATED",
    ):
        votes = copy.deepcopy(getattr(memo, "committee_votes", None) or [])

        # Determine vote from form data
        vote_value = _extract_vote_from_form_data(form_data, participant_email)

        for v in votes:
            if v.get("email") == participant_email:
                v["vote"] = vote_value
                v["signed_at"] = datetime.now(UTC).isoformat()
                v["signer_status"] = "COMPLETED"
                break
        else:
            # Unknown participant — append anyway
            votes.append(
                {
                    "email": participant_email,
                    "vote": vote_value,
                    "signed_at": datetime.now(UTC).isoformat(),
                    "signer_status": "COMPLETED",
                },
            )

        memo.committee_votes = votes  # type: ignore[attr-defined]
        db.flush()

        # ── Check majority ────────────────────────────────────────
        approve_count = sum(1 for v in votes if v.get("vote") == "APPROVE")
        refuse_count = sum(1 for v in votes if v.get("vote") == "REFUSE")
        total_members = len(getattr(memo, "committee_members", None) or [])
        majority = (total_members // 2) + 1

        if approve_count >= majority or refuse_count >= majority:
            new_recommendation = "APPROVED" if approve_count >= majority else "REJECTED"
            memo.recommendation = new_recommendation
            memo.esignature_status = ESignatureStatus.SIGNED.value  # type: ignore[attr-defined]

            # Download and archive signed PDF
            try:
                signed_pdf = adobe_client.download_signed_document(agreement_id)

                container = getattr(
                    app_settings,
                    "AZURE_BLOB_IC_MEMOS_SIGNED_CONTAINER",
                    "ic-memos-signed",
                )
                blob_name = (
                    f"{memo.deal_id}/{memo.id}/signed_ic_memo_{agreement_id}.pdf"
                )

                result = blob_storage.upload_bytes(
                    container=container,
                    blob_name=blob_name,
                    data=signed_pdf,
                    content_type="application/pdf",
                    overwrite=False,
                    metadata={
                        "agreement_id": agreement_id,
                        "memo_id": str(memo.id),
                        "deal_id": str(memo.deal_id),
                        "recommendation": new_recommendation,
                        "signed_at": datetime.now(UTC).isoformat(),
                    },
                )

                memo.memo_blob_url = result.blob_uri

                _upsert_document_registry(
                    db,
                    fund_id=memo.deal_id,  # correlation key
                    container_name=container,
                    blob_path=blob_name,
                    blob_uri=result.blob_uri,
                    domain_tag="ic-memo-signed",
                    title=f"Signed IC Memo v{memo.version} – {new_recommendation}",
                    checksum=result.sha256,
                    etag=result.etag,
                )

            except Exception:
                logger.exception("Failed to download/archive signed IC memo PDF")

            write_audit_event(
                db,
                fund_id=memo.deal_id,
                actor_id="adobe-sign-webhook",
                action="esignature.ic_memo.vote_majority_reached",
                entity_type="ICMemo",
                entity_id=str(memo.id),
                before=None,
                after={
                    "recommendation": new_recommendation,
                    "approve_count": approve_count,
                    "refuse_count": refuse_count,
                    "votes": votes,
                },
            )

            db.commit()
            logger.info(
                "IC Memo %s voting complete: %s (approve=%d, refuse=%d)",
                memo.id,
                new_recommendation,
                approve_count,
                refuse_count,
            )
            return {
                "status": "majority_reached",
                "recommendation": new_recommendation,
                "memo_id": str(memo.id),
            }

        # No majority yet — just commit the vote
        write_audit_event(
            db,
            fund_id=memo.deal_id,
            actor_id="adobe-sign-webhook",
            action="esignature.ic_memo.vote_recorded",
            entity_type="ICMemo",
            entity_id=str(memo.id),
            before=None,
            after={
                "participant_email": participant_email,
                "vote": vote_value,
                "approve_count": approve_count,
                "refuse_count": refuse_count,
            },
        )
        db.commit()
        return {
            "status": "vote_recorded",
            "email": participant_email,
            "vote": vote_value,
        }

    logger.info("Ignoring event %s for IC memo agreement %s", event, agreement_id)
    return {"status": "ignored", "event": event}


# ── Helpers ───────────────────────────────────────────────────────────


def _extract_vote_from_form_data(
    form_data: dict | None,
    participant_email: str,
) -> str:
    """Parse Adobe Sign form data to extract Approve/Refuse vote.

    Assumes form fields are named like ``Approve_<email>`` and
    ``Refuse_<email>`` (checkboxes).  Falls back to APPROVE if
    no explicit Refuse is found (signature alone = approval).
    """
    if not form_data:
        return "APPROVE"  # Signing without refusing = implicit approval

    # Normalise email for field lookup
    email_key = participant_email.replace("@", "_at_").replace(".", "_")

    refuse_key = f"Refuse_{email_key}"
    approve_key = f"Approve_{email_key}"

    # Also try generic field names
    for key, val in form_data.items():
        key_lower = key.lower()
        if "refuse" in key_lower and str(val).lower() in (
            "true",
            "on",
            "yes",
            "1",
            "checked",
        ):
            return "REFUSE"
        if "reject" in key_lower and str(val).lower() in (
            "true",
            "on",
            "yes",
            "1",
            "checked",
        ):
            return "REFUSE"

    return "APPROVE"


def _upsert_document_registry(
    db: Session,
    *,
    fund_id: uuid.UUID,
    container_name: str,
    blob_path: str,
    blob_uri: str,
    domain_tag: str,
    title: str,
    checksum: str | None = None,
    etag: str | None = None,
) -> None:
    """Insert or update a row in document_registry for a signed document."""
    from app.domains.credit.modules.ai.models import DocumentRegistry

    existing = db.execute(
        select(DocumentRegistry).where(
            DocumentRegistry.fund_id == fund_id,
            DocumentRegistry.container_name == container_name,
            DocumentRegistry.blob_path == blob_path,
        ),
    ).scalar_one_or_none()

    now = datetime.now(UTC)

    if existing:
        existing.checksum = checksum
        existing.etag = etag
        existing.title = title
        existing.last_ingested_at = now
        existing.lifecycle_stage = "signed"
    else:
        reg = DocumentRegistry(
            fund_id=fund_id,
            blob_path=blob_path,
            container_name=container_name,
            domain_tag=domain_tag,
            title=title,
            checksum=checksum,
            etag=etag,
            lifecycle_stage="signed",
            last_ingested_at=now,
            created_by="adobe-sign-webhook",
            updated_by="adobe-sign-webhook",
        )
        db.add(reg)

    db.flush()
