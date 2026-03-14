"""Adobe Sign REST API v6 client.

Handles OAuth 2.0 authentication via integration key and provides
methods for the transient-document → agreement workflow.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.core.config.settings import settings
from app.domains.credit.modules.adobe_sign.schemas import (
    AgreementCreationRequest,
    AgreementCreationResponse,
    AgreementStatusResponse,
    TransientDocumentResponse,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.adobesign.com/api/rest/v6"
_TIMEOUT = 60.0


class AdobeSignClientError(Exception):
    """Raised when the Adobe Sign API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Adobe Sign API error {status_code}: {detail}")


def _get_base_url() -> str:
    """Resolve base URL from environment or use default."""
    return getattr(settings, "ADOBE_SIGN_BASE_URL", None) or _DEFAULT_BASE_URL


def _get_integration_key() -> str:
    """Read integration key from environment.  Raises if not configured."""
    key = getattr(settings, "ADOBE_SIGN_INTEGRATION_KEY", None)
    if not key:
        raise RuntimeError(
            "ADOBE_SIGN_INTEGRATION_KEY is not set.  "
            "Configure it in your .env or environment variables."
        )
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_integration_key()}",
        "Content-Type": "application/json",
    }


# ── Transient Document ────────────────────────────────────────────────


def upload_transient_document(
    *,
    file_name: str,
    file_bytes: bytes,
    mime_type: str = "application/pdf",
) -> TransientDocumentResponse:
    """Upload a PDF to Adobe Sign as a transient document.

    Returns the transient document ID used when creating an agreement.
    """
    url = f"{_get_base_url()}/transientDocuments"
    headers = {
        "Authorization": f"Bearer {_get_integration_key()}",
    }
    # Adobe Sign v6 REST API expects:
    #   - "File" (multipart file field)
    #   - "File-Name" (form field with the desired filename)
    #   - "Mime-Type" (optional form field)
    files = {
        "File": (file_name, file_bytes, mime_type),
    }
    data = {"File-Name": file_name, "Mime-Type": mime_type}

    logger.info(
        "Uploading transient document: %s (%d bytes)", file_name, len(file_bytes)
    )

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(url, headers=headers, files=files, data=data)

    if resp.status_code >= 400:
        raise AdobeSignClientError(resp.status_code, resp.text)

    return TransientDocumentResponse(**resp.json())


# ── Agreement ─────────────────────────────────────────────────────────


def create_agreement(payload: AgreementCreationRequest) -> AgreementCreationResponse:
    """Create an Adobe Sign agreement and send for signature.

    The agreement is created in IN_PROCESS state so recipients
    immediately receive the signing request.
    """
    url = f"{_get_base_url()}/agreements"

    logger.info("Creating agreement: %s", payload.name)

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            url, headers=_headers(), json=payload.model_dump(exclude_none=True)
        )

    if resp.status_code >= 400:
        raise AdobeSignClientError(resp.status_code, resp.text)

    return AgreementCreationResponse(**resp.json())


def get_agreement_status(agreement_id: str) -> AgreementStatusResponse:
    """Retrieve the current status of an agreement."""
    url = f"{_get_base_url()}/agreements/{agreement_id}"

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(url, headers=_headers())

    if resp.status_code >= 400:
        raise AdobeSignClientError(resp.status_code, resp.text)

    return AgreementStatusResponse(**resp.json())


def download_signed_document(agreement_id: str) -> bytes:
    """Download the combined signed PDF for an agreement.

    Uses the /combinedDocument endpoint which merges all documents
    and audit trail into a single PDF.
    """
    url = f"{_get_base_url()}/agreements/{agreement_id}/combinedDocument"

    logger.info("Downloading signed document for agreement %s", agreement_id)

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(
            url,
            headers={
                "Authorization": f"Bearer {_get_integration_key()}",
                "Accept": "application/pdf",
            },
        )

    if resp.status_code >= 400:
        raise AdobeSignClientError(resp.status_code, resp.text)

    return resp.content


def get_agreement_form_data(agreement_id: str) -> list[dict[str, Any]]:
    """Retrieve form field data from a completed agreement.

    Used to extract committee votes (Approve/Refuse checkbox values).

    Per the Adobe Sign v6 docs, ``GET /agreements/{id}/formData`` returns
    a **CSV file stream** (not JSON).  The first row is the header
    (field names) and subsequent rows are data entries.
    """
    import csv
    import io

    url = f"{_get_base_url()}/agreements/{agreement_id}/formData"

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(
            url,
            headers={
                "Authorization": f"Bearer {_get_integration_key()}",
            },
        )

    if resp.status_code >= 400:
        raise AdobeSignClientError(resp.status_code, resp.text)

    # The response is CSV text; parse into list of dicts
    content_type = resp.headers.get("content-type", "")
    text = resp.text

    if "json" in content_type:
        # Defensive: some environments may return JSON
        data = resp.json()
        return data if isinstance(data, list) else [data]

    # Default: parse as CSV (official v6 format)
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def create_agreement_draft(
    payload: AgreementCreationRequest,
) -> AgreementCreationResponse:
    """Create an Adobe Sign agreement in DRAFT state (does NOT send).

    The agreement remains editable — use ``transition_agreement_state``
    to move it to IN_PROCESS when ready to send.
    """
    url = f"{_get_base_url()}/agreements"

    # Force DRAFT state regardless of what the caller set
    data = payload.model_dump(exclude_none=True)
    data["state"] = "DRAFT"

    logger.info("Creating DRAFT agreement: %s", payload.name)

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(url, headers=_headers(), json=data)

    if resp.status_code >= 400:
        raise AdobeSignClientError(resp.status_code, resp.text)

    return AgreementCreationResponse(**resp.json())


def get_agreement_form_fields(agreement_id: str) -> list[dict]:
    """Retrieve form fields from an agreement (works on DRAFT or signed).

    Returns a list of field dicts with fieldName, fieldType, page, etc.
    """
    url = f"{_get_base_url()}/agreements/{agreement_id}/formFields"

    logger.info("Fetching form fields for agreement %s", agreement_id)

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(url, headers=_headers())

    if resp.status_code >= 400:
        # Some agreements may not have form fields — return empty
        if resp.status_code == 404:
            logger.warning("No form fields found for agreement %s", agreement_id)
            return []
        raise AdobeSignClientError(resp.status_code, resp.text)

    body = resp.json()
    # The response has a top-level "fields" array
    return body.get("fields", [])


def get_agreement_signing_urls(agreement_id: str) -> dict:
    """Get embedded signing/viewing URLs for an agreement.

    Uses POST /agreements/{id}/views with name=DOCUMENT.
    Returns dict with possible 'url' or embedded view data.
    """
    url = f"{_get_base_url()}/agreements/{agreement_id}/views"

    logger.info("Fetching signing URLs for agreement %s", agreement_id)

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(url, headers=_headers(), json={"name": "DOCUMENT"})

    if resp.status_code >= 400:
        logger.warning(
            "Could not get signing URLs for agreement %s: %s",
            agreement_id,
            resp.text,
        )
        return {}

    return resp.json()


def transition_agreement_state(agreement_id: str, target_state: str) -> None:
    """Transition an agreement to a new state (e.g. DRAFT → IN_PROCESS).

    Valid transitions: DRAFT → AUTHORING → IN_PROCESS → CANCELLED
    """
    url = f"{_get_base_url()}/agreements/{agreement_id}/state"

    logger.info("Transitioning agreement %s to %s", agreement_id, target_state)

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.put(url, headers=_headers(), json={"state": target_state})

    if resp.status_code >= 400:
        raise AdobeSignClientError(resp.status_code, resp.text)

    logger.info("Agreement %s transitioned to %s", agreement_id, target_state)


def cancel_agreement(agreement_id: str) -> None:
    """Cancel (void) an in-process agreement."""
    url = f"{_get_base_url()}/agreements/{agreement_id}/state"

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.put(url, headers=_headers(), json={"state": "CANCELLED"})

    if resp.status_code >= 400:
        raise AdobeSignClientError(resp.status_code, resp.text)

    logger.info("Agreement %s cancelled", agreement_id)


# ── Webhook Signature Verification ────────────────────────────────────


def verify_webhook_signature(
    payload_body: bytes,
    signature_header: str | None,
) -> bool:
    """Verify the X-ADOBESIGN-SIGNATURE header value.

    Adobe Sign signs webhook payloads with HMAC-SHA256 using the
    client secret / webhook secret configured in the portal.
    """
    secret = getattr(settings, "ADOBE_SIGN_WEBHOOK_SECRET", None)
    if not secret:
        logger.warning(
            "ADOBE_SIGN_WEBHOOK_SECRET not set — skipping signature verification"
        )
        return True  # permissive in dev; enforce in prod

    if not signature_header:
        logger.warning("Missing X-ADOBESIGN-SIGNATURE header")
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected.lower(), signature_header.lower())
