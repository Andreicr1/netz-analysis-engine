from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory
from app.core.jobs.tracker import (
    get_redis_pool,
    publish_event,
    publish_terminal_event,
    register_job_owner,
)
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.allocation import MacroRegimeSnapshot
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.schemas.research import (
    CorrelationMatrixAccepted,
    CorrelationMatrixPayload,
    CorrelationMatrixRequest,
)

router = APIRouter(prefix="/research/correlation", tags=["research"])

_CACHE_TTL_SECONDS = 3600
_ASYNC_THRESHOLD = 50
_MAX_UNIVERSE = 200


def _cache_key(body: CorrelationMatrixRequest, org_id: str) -> str:
    raw = json.dumps(
        {
            "org_id": org_id,
            "instrument_ids": sorted(str(item) for item in body.instrument_ids),
            "window_days": body.window_days,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _redis_client() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=get_redis_pool())


async def _cache_get(cache_key: str) -> dict[str, Any] | None:
    redis = await _redis_client()
    try:
        raw = await redis.get(f"research:correlation:{cache_key}")
        return None if raw is None else dict(json.loads(raw))
    finally:
        await redis.aclose()


async def _cache_set(cache_key: str, payload: dict[str, Any]) -> None:
    redis = await _redis_client()
    try:
        await redis.set(
            f"research:correlation:{cache_key}",
            json.dumps(payload, default=str),
            ex=_CACHE_TTL_SECONDS,
        )
    finally:
        await redis.aclose()


async def _load_labels(
    db: AsyncSession,
    instrument_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    result = await db.execute(
        select(Instrument.instrument_id, Instrument.name).where(
            Instrument.instrument_id.in_(instrument_ids),
        ),
    )
    labels = {row.instrument_id: row.name for row in result.all()}
    missing = [item for item in instrument_ids if item not in labels]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown instrument ids: {', '.join(str(item) for item in missing[:3])}",
        )
    return labels


async def _load_regime_state(db: AsyncSession) -> tuple[str | None, date | None]:
    result = await db.execute(
        select(MacroRegimeSnapshot.as_of_date, MacroRegimeSnapshot.raw_regime)
        .order_by(MacroRegimeSnapshot.as_of_date.desc())
        .limit(1),
    )
    row = result.first()
    if row is None:
        return None, None
    return row.raw_regime, row.as_of_date


async def _load_returns_matrix(
    db: AsyncSession,
    instrument_ids: list[uuid.UUID],
    window_days: int,
) -> tuple[np.ndarray, list[date]]:
    date_floor = date.today() - timedelta(days=window_days + 90)
    stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id.in_(instrument_ids),
            NavTimeseries.nav_date >= date_floor,
            NavTimeseries.return_1d.isnot(None),
        )
        .order_by(NavTimeseries.nav_date)
    )
    result = await db.execute(stmt)
    rows = result.all()
    returns_by_inst: dict[uuid.UUID, dict[date, float]] = {}
    for row in rows:
        returns_by_inst.setdefault(row.instrument_id, {})[row.nav_date] = float(row.return_1d)

    if len(returns_by_inst) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient return history for correlation analysis",
        )

    common_dates = sorted(set.intersection(*(set(item.keys()) for item in returns_by_inst.values())))
    if len(common_dates) < 45:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient overlapping NAV data: {len(common_dates)} days",
        )
    if len(common_dates) > window_days:
        common_dates = common_dates[-window_days:]

    matrix = np.zeros((len(common_dates), len(instrument_ids)), dtype=np.float64)
    for col_idx, instrument_id in enumerate(instrument_ids):
        series = returns_by_inst.get(instrument_id)
        if series is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Universe contains instruments without aligned return history",
            )
        for row_idx, nav_date in enumerate(common_dates):
            matrix[row_idx, col_idx] = series[nav_date]
    return matrix, common_dates


def _nearest_psd_correlation(matrix: np.ndarray) -> np.ndarray:
    repaired = np.array(matrix, dtype=np.float64, copy=True)
    repaired = (repaired + repaired.T) / 2.0
    for _ in range(4):
        eigenvalues, eigenvectors = np.linalg.eigh(repaired)
        clipped = np.clip(eigenvalues, 1e-8, None)
        repaired = eigenvectors @ np.diag(clipped) @ eigenvectors.T
        repaired = (repaired + repaired.T) / 2.0
        scale = np.sqrt(np.maximum(np.diag(repaired), 1e-12))
        repaired = repaired / np.outer(scale, scale)
        np.fill_diagonal(repaired, 1.0)
    return repaired


def _denoise_correlation(returns_matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    standardized = returns_matrix - returns_matrix.mean(axis=0, keepdims=True)
    std = standardized.std(axis=0, ddof=1, keepdims=True)
    std[std == 0] = 1.0
    standardized = standardized / std

    raw_corr = np.corrcoef(standardized, rowvar=False)
    raw_corr = np.nan_to_num(raw_corr, nan=0.0)
    raw_corr = (raw_corr + raw_corr.T) / 2.0
    np.fill_diagonal(raw_corr, 1.0)

    eigenvalues, eigenvectors = np.linalg.eigh(raw_corr)
    n_obs, n_assets = standardized.shape
    q_ratio = max(float(n_obs) / float(max(n_assets, 1)), 1.0)
    lambda_plus = (1.0 + np.sqrt(1.0 / q_ratio)) ** 2
    signal_mask = eigenvalues > lambda_plus

    denoised_eigenvalues = eigenvalues.copy()
    if np.any(~signal_mask):
        noise_mean = float(np.mean(eigenvalues[~signal_mask]))
        denoised_eigenvalues[~signal_mask] = max(noise_mean, 1e-8)

    denoised = eigenvectors @ np.diag(denoised_eigenvalues) @ eigenvectors.T
    denoised = _nearest_psd_correlation(denoised)
    return raw_corr, denoised


def _build_payload(
    *,
    instrument_ids: list[uuid.UUID],
    labels: list[str],
    returns_matrix: np.ndarray,
    common_dates: list[date],
    regime_state_at_calc: str | None,
    as_of_date: date | None,
    cache_key: str,
) -> dict[str, Any]:
    historical_matrix, structural_matrix = _denoise_correlation(returns_matrix)
    return CorrelationMatrixPayload(
        instrument_ids=instrument_ids,
        labels=labels,
        historical_matrix=np.round(historical_matrix, 4).tolist(),
        structural_matrix=np.round(structural_matrix, 4).tolist(),
        regime_state_at_calc=regime_state_at_calc,
        effective_window_days=len(common_dates),
        as_of_date=as_of_date or (common_dates[-1] if common_dates else None),
        cache_key=cache_key,
        psd_enforced=True,
        diagonal_normalized=True,
    ).model_dump(mode="json")


async def _compute_payload(
    db: AsyncSession,
    body: CorrelationMatrixRequest,
    cache_key: str,
) -> dict[str, Any]:
    labels_map = await _load_labels(db, body.instrument_ids)
    returns_matrix, common_dates = await _load_returns_matrix(db, body.instrument_ids, body.window_days)
    regime_state, regime_as_of = await _load_regime_state(db)
    labels = [labels_map[item] for item in body.instrument_ids]
    return await asyncio.to_thread(
        _build_payload,
        instrument_ids=body.instrument_ids,
        labels=labels,
        returns_matrix=returns_matrix,
        common_dates=common_dates,
        regime_state_at_calc=regime_state,
        as_of_date=regime_as_of,
        cache_key=cache_key,
    )


async def _run_correlation_job(
    *,
    app: Any,
    job_id: str,
    body: CorrelationMatrixRequest,
    cache_key: str,
) -> None:
    try:
        cached = await _cache_get(cache_key)
        if cached is not None:
            await publish_terminal_event(job_id, "done", {"result": cached, "cache_hit": True})
            return

        await publish_event(job_id, "progress", {"stage": "loading", "message": "Loading aligned return history"})
        async with async_session_factory() as db:
            payload = await _compute_payload(db, body, cache_key)
        await _cache_set(cache_key, payload)
        await publish_terminal_event(job_id, "done", {"result": payload, "cache_hit": False})
    except HTTPException as exc:
        await publish_terminal_event(
            job_id,
            "error",
            {"detail": exc.detail, "status_code": exc.status_code},
        )
    except Exception as exc:
        await publish_terminal_event(job_id, "error", {"detail": str(exc)})
    finally:
        active = getattr(app.state, "active_research_jobs", None)
        if isinstance(active, dict):
            active.pop(job_id, None)


@router.post(
    "/matrix",
    response_model=CorrelationMatrixPayload | CorrelationMatrixAccepted,
    summary="Structural and historical correlation matrices",
)
async def post_correlation_matrix(
    body: CorrelationMatrixRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    user: CurrentUser = Depends(get_current_user),
):
    if len(body.instrument_ids) > _MAX_UNIVERSE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximum supported universe is {_MAX_UNIVERSE} funds",
        )

    cache_key = _cache_key(body, str(actor.organization_id))
    if len(body.instrument_ids) > _ASYNC_THRESHOLD:
        job_id = str(uuid.uuid4())
        await register_job_owner(job_id, str(actor.organization_id))
        task = asyncio.create_task(
            _run_correlation_job(
                app=request.app,
                job_id=job_id,
                body=body,
                cache_key=cache_key,
            )
        )
        active = getattr(request.app.state, "active_research_jobs", None)
        if active is None:
            active = {}
            request.app.state.active_research_jobs = active
        active[job_id] = task
        accepted = CorrelationMatrixAccepted(
            job_id=job_id,
            stream_url=f"/api/v1/jobs/{job_id}/stream",
            cache_key=cache_key,
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump())

    cached = await _cache_get(cache_key)
    if cached is not None:
        return CorrelationMatrixPayload.model_validate(cached)

    payload = await _compute_payload(db, body, cache_key)
    await _cache_set(cache_key, payload)
    return CorrelationMatrixPayload.model_validate(payload)
