"""Adobe Sign webhook endpoint processors.

Two webhook routes are exposed:
  - /api/webhooks/adobe-sign/transfer-orders
  - /api/webhooks/adobe-sign/ic-memos

Both verify the X-ADOBESIGN-SIGNATURE header before processing.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.db.engine import get_db
from app.domains.credit.modules.adobe_sign import client as adobe_client
from app.domains.credit.modules.adobe_sign import service as adobe_service
from app.domains.credit.modules.adobe_sign.schemas import WebhookEventPayload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/adobe-sign", tags=["Adobe Sign Webhooks"])


async def _verify_signature(request: Request) -> bytes:
    """Read request body and verify Adobe Sign webhook signature.

    Returns the raw body bytes for further parsing.
    Raises HTTP 401 if signature is invalid.
    """
    body = await request.body()
    signature = request.headers.get("X-ADOBESIGN-SIGNATURE")

    if not adobe_client.verify_webhook_signature(body, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )
    return body


# ── Transfer-Order webhooks ───────────────────────────────────────────


@router.post("/transfer-orders")
async def webhook_transfer_orders(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Receive Adobe Sign webhook events for transfer-order agreements.

    Handles AGREEMENT_ACTION_COMPLETED to finalise signed transfer orders.
    Adobe Sign also sends a GET request for URL validation — we handle that
    by returning 200 for GET (handled by FastAPI's route matching).
    """
    body = await _verify_signature(request)

    import json

    try:
        payload_dict = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON"
        )

    payload = WebhookEventPayload(**payload_dict)

    if not payload.agreement_id:
        logger.warning("Webhook event missing agreement ID")
        return {"status": "ignored", "reason": "no agreement ID"}

    result = adobe_service.process_transfer_order_webhook(
        db,
        agreement_id=payload.agreement_id,
        event=payload.event,
        participant_email=payload.participantUserEmail,
    )
    return result


@router.get("/transfer-orders")
async def webhook_transfer_orders_verify(request: Request) -> dict:
    """Adobe Sign URL verification endpoint (responds to GET).

    Per docs, Adobe sends a GET with X-AdobeSign-ClientId header.
    We must validate it matches our Client ID and echo it back in the
    response body as ``{"xAdobeSignClientId": "<CLIENT_ID>"}``.
    """
    incoming_client_id = request.headers.get("X-AdobeSign-ClientId", "")
    configured_client_id = settings.ADOBE_SIGN_CLIENT_ID or ""

    if configured_client_id and incoming_client_id != configured_client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client ID mismatch",
        )
    return {"xAdobeSignClientId": incoming_client_id or configured_client_id}


# ── IC Memo webhooks ─────────────────────────────────────────────────


@router.post("/ic-memos")
async def webhook_ic_memos(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Receive Adobe Sign webhook events for IC-memo committee voting.

    Handles signer-level events to track individual votes and
    AGREEMENT_ACTION_COMPLETED for majority-based resolution.
    """
    body = await _verify_signature(request)

    import json

    try:
        payload_dict = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON"
        )

    payload = WebhookEventPayload(**payload_dict)

    if not payload.agreement_id:
        logger.warning("IC Memo webhook event missing agreement ID")
        return {"status": "ignored", "reason": "no agreement ID"}

    # Try to retrieve form data for vote extraction
    form_data = None
    if payload.event in ("AGREEMENT_ACTION_COMPLETED", "AGREEMENT_WORKFLOW_COMPLETED"):
        try:
            form_data_list = adobe_client.get_agreement_form_data(payload.agreement_id)
            form_data = form_data_list[0] if form_data_list else None
        except Exception:
            logger.warning(
                "Could not retrieve form data for agreement %s", payload.agreement_id
            )

    result = adobe_service.process_ic_memo_webhook(
        db,
        agreement_id=payload.agreement_id,
        event=payload.event,
        participant_email=payload.participantUserEmail,
        form_data=form_data,
    )
    return result


@router.get("/ic-memos")
async def webhook_ic_memos_verify(request: Request) -> dict:
    """Adobe Sign URL verification endpoint (responds to GET)."""
    incoming_client_id = request.headers.get("X-AdobeSign-ClientId", "")
    configured_client_id = settings.ADOBE_SIGN_CLIENT_ID or ""

    if configured_client_id and incoming_client_id != configured_client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client ID mismatch",
        )
    return {"xAdobeSignClientId": incoming_client_id or configured_client_id}


# ── Signature Queue webhooks ─────────────────────────────────────────


@router.post("/signature-queue")
async def webhook_signature_queue(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Receive Adobe Sign webhook events for signature-queue agreements.

    Handles AGREEMENT_ACTION_COMPLETED to download signed PDF, archive to
    Blob Storage, and update the SignatureQueueItem status to SIGNED.
    """
    body = await _verify_signature(request)

    import json

    try:
        payload_dict = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON"
        )

    payload = WebhookEventPayload(**payload_dict)

    if not payload.agreement_id:
        logger.warning("Signature queue webhook event missing agreement ID")
        return {"status": "ignored", "reason": "no agreement ID"}

    from app.domains.credit.modules.signatures.queue_service import process_signature_queue_webhook

    result = process_signature_queue_webhook(
        db,
        agreement_id=payload.agreement_id,
        event=payload.event,
        participant_email=payload.participantUserEmail,
    )
    return result


@router.get("/signature-queue")
async def webhook_signature_queue_verify(request: Request) -> dict:
    """Adobe Sign URL verification endpoint (responds to GET)."""
    incoming_client_id = request.headers.get("X-AdobeSign-ClientId", "")
    configured_client_id = settings.ADOBE_SIGN_CLIENT_ID or ""

    if configured_client_id and incoming_client_id != configured_client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client ID mismatch",
        )
    return {"xAdobeSignClientId": incoming_client_id or configured_client_id}
