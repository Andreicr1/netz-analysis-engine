"""Microsoft Graph API client for SharePoint content retrieval.

Uses raw httpx + DefaultAzureCredential — lightweight alternative to msgraph-sdk.

DEPRECATED 2026-03-18: All azure imports are lazy to avoid breaking CI when azure SDK
is not installed. Retained for rollback capability only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


@dataclass(frozen=True)
class GraphHealth:
    ok: bool
    detail: str | None = None


def _get_graph_token() -> str:
    """Acquire a Graph API access token via Managed Identity / DefaultAzureCredential."""
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    token = credential.get_token(_GRAPH_SCOPE)
    return token.token


def download_file(path: str, if_none_match: str | None = None) -> tuple[bytes | None, str | None, str | None]:
    """Download a file from the configured SharePoint drive.

    Args:
        path: File path relative to drive root (e.g. "netz-private-credit/visao-geral/sobre-o-fundo.md").
        if_none_match: Optional cTag/eTag for conditional GET (returns None content if not modified).

    Returns:
        Tuple of (content_bytes, ctag, last_modified).
        content_bytes is None if the server returned 304 Not Modified.

    """
    if not settings.GRAPH_SITE_ID or not settings.GRAPH_DRIVE_ID:
        raise ValueError("GRAPH_SITE_ID and GRAPH_DRIVE_ID must be configured")

    token = _get_graph_token()
    headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
    if if_none_match:
        headers["If-None-Match"] = if_none_match

    url = f"{_GRAPH_BASE}/sites/{settings.GRAPH_SITE_ID}/drives/{settings.GRAPH_DRIVE_ID}/root:/{path}:/content"

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers, follow_redirects=True)

    if resp.status_code == 304:
        return None, if_none_match, None

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "60")
        logger.warning("Graph API throttled, Retry-After: %s", retry_after)
        raise GraphThrottledError(retry_after=int(retry_after))

    resp.raise_for_status()

    ctag = resp.headers.get("ETag")
    last_modified = resp.headers.get("Last-Modified")
    return resp.content, ctag, last_modified


def get_file_metadata(path: str) -> dict:
    """Get metadata (cTag, lastModifiedDateTime) for a file without downloading content."""
    if not settings.GRAPH_SITE_ID or not settings.GRAPH_DRIVE_ID:
        raise ValueError("GRAPH_SITE_ID and GRAPH_DRIVE_ID must be configured")

    token = _get_graph_token()
    url = f"{_GRAPH_BASE}/sites/{settings.GRAPH_SITE_ID}/drives/{settings.GRAPH_DRIVE_ID}/root:/{path}"

    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    return resp.json()


def health_check_graph() -> GraphHealth:
    """Verify Graph API connectivity and drive access."""
    try:
        if not settings.GRAPH_SITE_ID or not settings.GRAPH_DRIVE_ID:
            return GraphHealth(ok=False, detail="GRAPH_SITE_ID/GRAPH_DRIVE_ID not configured")

        token = _get_graph_token()
        url = f"{_GRAPH_BASE}/sites/{settings.GRAPH_SITE_ID}/drives/{settings.GRAPH_DRIVE_ID}"

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        return GraphHealth(ok=True)
    except Exception as e:
        return GraphHealth(ok=False, detail=str(e))


class GraphThrottledError(Exception):
    """Raised when Graph API returns 429 Too Many Requests."""

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Graph API throttled, retry after {retry_after}s")
