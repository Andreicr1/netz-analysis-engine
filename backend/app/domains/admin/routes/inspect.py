"""Admin data lake inspection routes — DuckDB Parquet queries."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security.admin_auth import require_super_admin
from app.core.security.clerk_auth import Actor
from app.domains.admin.schemas.inspect import (
    ChunkStatsOut,
    DimensionMismatchOut,
    DocumentCoverageOut,
    ExtractionQualityOut,
    InspectResultOut,
    StaleEmbeddingOut,
)
from app.services.duckdb_client import get_duckdb_client

router = APIRouter(
    prefix="/admin/inspect",
    tags=["admin-inspect"],
    dependencies=[Depends(require_super_admin)],
)

_VALID_VERTICALS = frozenset({"credit", "wealth"})
_TIMEOUT_SECONDS = 30


def _validate_vertical(vertical: str) -> None:
    if vertical not in _VALID_VERTICALS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid vertical '{vertical}'. Must be one of: {', '.join(sorted(_VALID_VERTICALS))}",
        )


@router.get(
    "/{org_id}/{vertical}/stale-embeddings",
    response_model=InspectResultOut[StaleEmbeddingOut],
)
async def get_stale_embeddings(
    org_id: uuid.UUID,
    vertical: str,
    current_model: str = Query(default="text-embedding-3-large"),
    expected_dim: int = Query(default=3072),
    actor: Actor = Depends(require_super_admin),
) -> InspectResultOut[StaleEmbeddingOut]:
    _validate_vertical(vertical)
    client = get_duckdb_client()
    try:
        results = await asyncio.wait_for(
            client.async_stale_embeddings(org_id, vertical, current_model, expected_dim),
            timeout=_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="DuckDB query timed out")
    items = [StaleEmbeddingOut.model_validate(r, from_attributes=True) for r in results]
    return InspectResultOut(
        results=items,
        count=len(items),
        org_id=org_id,
        vertical=vertical,
        queried_at=datetime.now(UTC),
    )


@router.get(
    "/{org_id}/{vertical}/coverage",
    response_model=InspectResultOut[DocumentCoverageOut],
)
async def get_document_coverage(
    org_id: uuid.UUID,
    vertical: str,
    actor: Actor = Depends(require_super_admin),
) -> InspectResultOut[DocumentCoverageOut]:
    _validate_vertical(vertical)
    client = get_duckdb_client()
    try:
        results = await asyncio.wait_for(
            client.async_document_coverage(org_id, vertical),
            timeout=_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="DuckDB query timed out")
    items = [DocumentCoverageOut.model_validate(r, from_attributes=True) for r in results]
    return InspectResultOut(
        results=items,
        count=len(items),
        org_id=org_id,
        vertical=vertical,
        queried_at=datetime.now(UTC),
    )


@router.get(
    "/{org_id}/{vertical}/extraction-quality",
    response_model=InspectResultOut[ExtractionQualityOut],
)
async def get_extraction_quality(
    org_id: uuid.UUID,
    vertical: str,
    min_chars: int = Query(default=50),
    actor: Actor = Depends(require_super_admin),
) -> InspectResultOut[ExtractionQualityOut]:
    _validate_vertical(vertical)
    client = get_duckdb_client()
    try:
        results = await asyncio.wait_for(
            client.async_extraction_quality(org_id, vertical, min_chars),
            timeout=_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="DuckDB query timed out")
    items = [ExtractionQualityOut.model_validate(r, from_attributes=True) for r in results]
    return InspectResultOut(
        results=items,
        count=len(items),
        org_id=org_id,
        vertical=vertical,
        queried_at=datetime.now(UTC),
    )


@router.get(
    "/{org_id}/{vertical}/chunk-stats",
    response_model=ChunkStatsOut,
)
async def get_chunk_stats(
    org_id: uuid.UUID,
    vertical: str,
    actor: Actor = Depends(require_super_admin),
) -> ChunkStatsOut:
    _validate_vertical(vertical)
    client = get_duckdb_client()
    try:
        result = await asyncio.wait_for(
            client.async_chunk_stats(org_id, vertical),
            timeout=_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="DuckDB query timed out")
    return ChunkStatsOut(
        total_chunks=result.total_chunks,
        total_documents=result.total_documents,
        total_chars=result.total_chars,
        avg_chunk_chars=result.avg_chunk_chars,
        median_chunk_chars=result.median_chunk_chars,
        p95_chunk_chars=result.p95_chunk_chars,
        doc_type_distribution=result.doc_type_distribution,
        org_id=org_id,
        vertical=vertical,
        queried_at=datetime.now(UTC),
    )


@router.get(
    "/{org_id}/{vertical}/embedding-audit",
    response_model=InspectResultOut[DimensionMismatchOut],
)
async def get_embedding_audit(
    org_id: uuid.UUID,
    vertical: str,
    expected_dim: int = Query(default=3072),
    actor: Actor = Depends(require_super_admin),
) -> InspectResultOut[DimensionMismatchOut]:
    _validate_vertical(vertical)
    client = get_duckdb_client()
    try:
        results = await asyncio.wait_for(
            client.async_embedding_dimension_audit(org_id, vertical, expected_dim),
            timeout=_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="DuckDB query timed out")
    items = [DimensionMismatchOut.model_validate(r, from_attributes=True) for r in results]
    return InspectResultOut(
        results=items,
        count=len(items),
        org_id=org_id,
        vertical=vertical,
        queried_at=datetime.now(UTC),
    )
