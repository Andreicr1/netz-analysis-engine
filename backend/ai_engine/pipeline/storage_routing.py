"""ADLS path routing for bronze / silver / gold layers.

Builds deterministic paths following the convention:
  {tier}/{org_id}/{vertical}/...

Vertical comes from ``IngestRequest.vertical`` (request context),
NOT from classification output.

``_global/`` paths are for reference data (FRED, Yahoo, benchmarks)
with no org_id and no vertical.  Client documents NEVER go to ``_global/``.
"""
from __future__ import annotations

import re
from uuid import UUID

# Matches safe path segments: alphanumeric start, then alphanumeric/dot/dash/underscore.
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-]*$")

_VALID_VERTICALS = frozenset({"credit", "wealth"})
_VALID_TIERS = frozenset({"bronze", "silver", "gold"})


def _validate_segment(value: str, label: str) -> None:
    """Validate a single path segment against traversal and injection."""
    if not value:
        raise ValueError(f"{label} must not be empty")
    if not _SAFE_PATH_SEGMENT_RE.match(value):
        raise ValueError(
            f"Invalid {label}: {value!r} — must match {_SAFE_PATH_SEGMENT_RE.pattern}"
        )


def _validate_vertical(vertical: str) -> None:
    if vertical not in _VALID_VERTICALS:
        raise ValueError(f"Invalid vertical: {vertical!r} — must be one of {_VALID_VERTICALS}")


# ── Bronze layer (raw ingested data) ───────────────────────────────


def bronze_document_path(org_id: UUID, vertical: str, doc_id: str) -> str:
    """``bronze/{org_id}/{vertical}/documents/{doc_id}.json``

    Stores raw OCR output as JSON.
    """
    _validate_vertical(vertical)
    _validate_segment(doc_id, "doc_id")
    return f"bronze/{org_id}/{vertical}/documents/{doc_id}.json"


# ── Silver layer (processed / enriched data) ───────────────────────


def silver_chunks_path(org_id: UUID, vertical: str, doc_id: str) -> str:
    """``silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet``

    Stores chunked + embedded document data as Parquet.
    """
    _validate_vertical(vertical)
    _validate_segment(doc_id, "doc_id")
    return f"silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet"


def silver_metadata_path(org_id: UUID, vertical: str, doc_id: str) -> str:
    """``silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json``

    Stores extracted metadata + summary as JSON.
    """
    _validate_vertical(vertical)
    _validate_segment(doc_id, "doc_id")
    return f"silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json"


# ── Gold layer (analytical outputs) ────────────────────────────────


def gold_memo_path(org_id: UUID, vertical: str, memo_id: str) -> str:
    """``gold/{org_id}/{vertical}/memos/{memo_id}.json``

    Stores IC memos and analytical reports.
    """
    _validate_vertical(vertical)
    _validate_segment(memo_id, "memo_id")
    return f"gold/{org_id}/{vertical}/memos/{memo_id}.json"


# ── Global paths (no org_id, no vertical) ──────────────────────────


def global_reference_path(dataset: str, filename: str) -> str:
    """``gold/_global/{dataset}/{filename}``

    For reference data shared across all tenants: FRED indicators,
    ETF benchmarks, Yahoo Finance snapshots.
    """
    _validate_segment(dataset, "dataset")
    _validate_segment(filename, "filename")
    return f"gold/_global/{dataset}/{filename}"
