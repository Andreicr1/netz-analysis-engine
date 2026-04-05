"""Workers router — HTTP trigger endpoints for background workers.

Allows CI pipelines, scheduled jobs, and admin UIs to trigger
ingestion, risk calculation, and portfolio evaluation via the API.

SR-1 mitigation: all worker dispatches are wrapped with asyncio.wait_for()
timeout and structured start/finish/error/timeout logging to prevent stuck
workers from blocking the event loop and to provide observability.

M-6 mitigation: idempotency guard via Redis — prevents duplicate runs,
tracks completion/failure status, returns 409 on concurrent triggers.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.jobs.worker_idempotency import (
    check_worker_status,
    idempotent_worker_wrapper,
    mark_worker_running,
)
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.domains.wealth.workers.ingestion import run_ingestion
from app.domains.wealth.workers.macro_ingestion import run_macro_ingestion
from app.domains.wealth.workers.portfolio_eval import run_portfolio_eval
from app.domains.wealth.workers.risk_calc import run_global_risk_metrics, run_risk_calc
from app.shared.enums import Role

logger = structlog.get_logger()

router = APIRouter(prefix="/workers")

# Timeout tiers (seconds)
_HEAVY_WORKER_TIMEOUT = 600  # 10 min — ingestion, risk calc, macro, fact-sheet, benchmark
_LIGHT_WORKER_TIMEOUT = 300  # 5 min — screening, watchlist, portfolio eval


def _require_admin_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM) and not actor.has_role(Role.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or IC role required")


async def _run_worker_with_timeout(
    worker_name: str,
    coro_fn: Callable[..., Awaitable[Any]],
    *args: Any,
    timeout_seconds: int = _HEAVY_WORKER_TIMEOUT,
    org_id: uuid.UUID | None = None,
) -> None:
    """Execute a worker coroutine with timeout and structured logging.

    Wraps the worker call with ``asyncio.wait_for`` to prevent stuck workers
    from blocking the ASGI event loop indefinitely.  Logs start, success,
    timeout, and error events with timing information for observability.
    """
    log = logger.bind(
        worker_name=worker_name,
        org_id=str(org_id) if org_id else None,
        timeout_seconds=timeout_seconds,
    )
    log.info("worker.started")
    t0 = time.monotonic()

    try:
        await asyncio.wait_for(coro_fn(*args), timeout=timeout_seconds)
        duration = round(time.monotonic() - t0, 2)
        log.info("worker.completed", duration_seconds=duration)
    except TimeoutError:
        duration = round(time.monotonic() - t0, 2)
        log.error(
            "worker.timeout",
            duration_seconds=duration,
            detail=f"Worker {worker_name} exceeded {timeout_seconds}s timeout",
        )
    except Exception:
        duration = round(time.monotonic() - t0, 2)
        log.exception("worker.failed", duration_seconds=duration)


class WorkerScheduledResponse(BaseModel):
    status: str
    worker: str


async def _dispatch_worker(
    background_tasks: BackgroundTasks,
    worker_name: str,
    scope: str,
    coro_func: Callable[..., Awaitable[Any]],
    *args: Any,
    timeout_seconds: int = _HEAVY_WORKER_TIMEOUT,
    org_id: uuid.UUID | None = None,
) -> WorkerScheduledResponse:
    """Check idempotency, then dispatch a worker with timeout wrapping.

    Raises HTTPException 409 if the worker is already running or recently
    completed for the given scope.  Otherwise marks it as running in Redis
    and schedules the background task with both idempotency tracking and
    the SR-1 timeout wrapper.
    """
    existing = await check_worker_status(worker_name, scope)
    if existing is not None:
        if existing.get("status") == "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Worker '{worker_name}' is already running for scope '{scope}'",
            )
        if existing.get("status") == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Worker '{worker_name}' completed recently for scope '{scope}'. "
                    "Wait for the cooldown period or check the result."
                ),
            )

    # Mark as running BEFORE dispatching to close the race window
    await mark_worker_running(worker_name, scope)

    # Compose: idempotent wrapper calls the timeout wrapper which calls the worker
    background_tasks.add_task(
        idempotent_worker_wrapper,
        worker_name,
        scope,
        _run_worker_with_timeout,
        worker_name,
        coro_func,
        *args,
        timeout_seconds=timeout_seconds,
        org_id=org_id,
    )
    return WorkerScheduledResponse(status="scheduled", worker=worker_name)


@router.post(
    "/run-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger NAV ingestion",
    description=(
        "Schedules the NAV ingestion worker as a background task. "
        "Fetches latest prices from Yahoo Finance for all active funds "
        "and upserts results into nav_timeseries. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)
    return await _dispatch_worker(
        background_tasks, "run-ingestion", str(user.organization_id),
        run_ingestion, user.organization_id,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT, org_id=user.organization_id,
    )


@router.post(
    "/run-risk-calc",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger risk calculation",
    description=(
        "Schedules the risk calculation worker as a background task. "
        "Computes rolling CVaR, VaR, returns, volatility, drawdown, and Sharpe "
        "for all active funds and stores results in fund_risk_metrics. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_risk_calc(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)
    return await _dispatch_worker(
        background_tasks, "run-risk-calc", str(user.organization_id),
        run_risk_calc, user.organization_id,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT, org_id=user.organization_id,
    )


@router.post(
    "/run-global-risk-metrics",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger global risk metrics calculation",
    description=(
        "Computes base risk metrics (CVaR, Sharpe, volatility, momentum, GARCH) "
        "for ALL active instruments with NAV. Global scope — no org_id, no DTW drift. "
        "Pre-populates fund_risk_metrics so any tenant's screener has data immediately."
    ),
    tags=["workers"],
)
async def trigger_run_global_risk_metrics(
    background_tasks: BackgroundTasks,
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)
    return await _dispatch_worker(
        background_tasks, "run-global-risk-metrics", "global",
        run_global_risk_metrics,
        timeout_seconds=14400,  # 4h for 6k+ instruments
    )


@router.post(
    "/run-portfolio-eval",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger portfolio evaluation",
    description=(
        "Schedules the portfolio evaluation worker as a background task. "
        "Evaluates CVaR status, breach days, and regime for all 3 profiles "
        "and creates daily portfolio_snapshots. Publishes Redis alerts on breach. "
        "Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_portfolio_eval(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)
    return await _dispatch_worker(
        background_tasks, "run-portfolio-eval", str(user.organization_id),
        run_portfolio_eval, user.organization_id,
        timeout_seconds=_LIGHT_WORKER_TIMEOUT, org_id=user.organization_id,
    )


@router.post(
    "/run-macro-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger macro intelligence ingestion",
    description=(
        "Schedules the macro ingestion worker as a background task. "
        "Fetches ~45 FRED series across 4 regions, computes regional macro "
        "scores via percentile-rank normalization, and stores snapshot in "
        "macro_regional_snapshots. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_macro_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)
    return await _dispatch_worker(
        background_tasks, "run-macro-ingestion", "global",
        run_macro_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-fact-sheet-gen",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger monthly fact-sheet generation",
    description=(
        "Schedules the fact-sheet generation worker as a background task. "
        "Generates executive and institutional PDFs for all active model "
        "portfolios in Portuguese (default language). Uses advisory lock "
        "to prevent concurrent runs. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_fact_sheet_gen(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.fact_sheet_gen import run_monthly_fact_sheets

    return await _dispatch_worker(
        background_tasks, "run-fact-sheet-gen", "global",
        run_monthly_fact_sheets,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-watchlist-check",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger watchlist monitoring check",
    description=(
        "Schedules the watchlist monitoring worker as a background task. "
        "Re-screens all watchlisted instruments through 3-layer screening, "
        "detects transitions (improvement/deterioration), and publishes "
        "alerts via Redis pub/sub. Uses advisory lock 900_003 to prevent "
        "concurrent runs. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_watchlist_check(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.watchlist_batch import run_watchlist_check

    org_id = user.organization_id
    return await _dispatch_worker(
        background_tasks, "run-watchlist-check", str(org_id),
        run_watchlist_check, org_id,
        timeout_seconds=_LIGHT_WORKER_TIMEOUT, org_id=org_id,
    )


@router.post(
    "/run-screening-batch",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger batch instrument screening",
    description=(
        "Schedules the screening batch worker as a background task. "
        "Re-screens all active instruments through 3-layer deterministic "
        "screening. Uses advisory lock 900_002 to prevent concurrent runs. "
        "Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_screening_batch(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.screening_batch import run_screening_batch

    org_id = user.organization_id
    return await _dispatch_worker(
        background_tasks, "run-screening-batch", str(org_id),
        run_screening_batch, org_id,
        timeout_seconds=_LIGHT_WORKER_TIMEOUT, org_id=org_id,
    )


@router.post(
    "/run-instrument-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger instrument universe NAV ingestion",
    description=(
        "Schedules the instrument NAV ingestion worker as a background task. "
        "Fetches NAV history from the configured provider for all active "
        "instruments in instruments_universe and upserts into nav_timeseries. "
        "Uses advisory lock 900_010 to prevent concurrent runs. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_instrument_ingestion(
    background_tasks: BackgroundTasks,
    lookback_days: int = Query(default=3650, ge=1, le=3650),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.instrument_ingestion import run_instrument_ingestion

    return await _dispatch_worker(
        background_tasks, "run-instrument-ingestion", "global",
        run_instrument_ingestion, lookback_days,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-benchmark-ingest",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger benchmark NAV ingestion",
    description=(
        "Schedules the benchmark NAV ingestion worker as a background task. "
        "Downloads benchmark index data from Yahoo Finance for all allocation "
        "blocks with a benchmark_ticker, and upserts into benchmark_nav (global). "
        "Uses advisory lock 900_004 to prevent concurrent runs. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_benchmark_ingest(
    background_tasks: BackgroundTasks,
    lookback_days: int = Query(default=3650, ge=1, le=3650),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.benchmark_ingest import run_benchmark_ingest

    return await _dispatch_worker(
        background_tasks, "run-benchmark-ingest", "global",
        run_benchmark_ingest, lookback_days,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-treasury-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Treasury data ingestion",
    description=(
        "Schedules the Treasury data ingestion worker as a background task. "
        "Fetches rates, debt snapshots, auction results, exchange rates, and "
        "interest expense from the US Treasury Fiscal Data API and upserts into "
        "treasury_data hypertable. Uses advisory lock 900_011. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_treasury_ingestion(
    background_tasks: BackgroundTasks,
    lookback_days: int = Query(default=365, ge=30, le=3650),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.treasury_ingestion import run_treasury_ingestion

    return await _dispatch_worker(
        background_tasks, "run-treasury-ingestion", "global",
        run_treasury_ingestion, lookback_days,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-ofr-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger OFR hedge fund data ingestion",
    description=(
        "Schedules the OFR hedge fund data ingestion worker as a background task. "
        "Fetches leverage ratios, industry AUM, strategy breakdowns, repo volumes, "
        "counterparty metrics, and stress scenarios from the OFR API and upserts "
        "into ofr_hedge_fund_data hypertable. Uses advisory lock 900_012. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_ofr_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.ofr_ingestion import run_ofr_ingestion

    return await _dispatch_worker(
        background_tasks, "run-ofr-ingestion", "global",
        run_ofr_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-sec-refresh",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger SEC aggregate refresh + cache",
    description=(
        "Schedules the SEC refresh worker as a background task. "
        "Refreshes TimescaleDB continuous aggregates (sec_13f_holdings_agg, "
        "sec_13f_drift_agg) and writes per-manager summary stats to Redis "
        "for the manager screener. Uses advisory lock 900_016. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_sec_refresh(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.sec_refresh import run_sec_refresh

    return await _dispatch_worker(
        background_tasks, "run-sec-refresh", "global",
        run_sec_refresh,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-nport-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger N-PORT holdings ingestion",
    description=(
        "Schedules the N-PORT ingestion worker as a background task. "
        "Fetches monthly portfolio holdings from SEC N-PORT filings for "
        "all active managers with CIKs. Parses XML filings and upserts "
        "into sec_nport_holdings hypertable. Uses advisory lock 900_018. "
        "Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_nport_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.nport_ingestion import run_nport_ingestion

    return await _dispatch_worker(
        background_tasks, "run-nport-ingestion", "global",
        run_nport_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-bis-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger BIS statistics ingestion",
    description=(
        "Schedules the BIS ingestion worker as a background task. "
        "Fetches credit-to-GDP gap, debt service ratio, and property "
        "prices from the BIS SDMX API for 44 countries and upserts into "
        "bis_statistics hypertable. Uses advisory lock 900_014. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_bis_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.bis_ingestion import run_bis_ingestion

    return await _dispatch_worker(
        background_tasks, "run-bis-ingestion", "global",
        run_bis_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-imf-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger IMF WEO forecast ingestion",
    description=(
        "Schedules the IMF WEO ingestion worker as a background task. "
        "Fetches 5-year forward GDP, inflation, fiscal balance, and govt "
        "debt forecasts from the IMF DataMapper API for 44 countries and "
        "upserts into imf_weo_forecasts hypertable. Uses advisory lock "
        "900_015. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_imf_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.imf_ingestion import run_imf_ingestion

    return await _dispatch_worker(
        background_tasks, "run-imf-ingestion", "global",
        run_imf_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-brochure-download",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger ADV brochure PDF download",
    description=(
        "Phase A: Download ADV Part 2A brochure PDFs from IAPD into "
        "StorageClient (R2 prod / local dev). Rate-limited at 1 req/s. "
        "Skips already-stored PDFs. Uses advisory lock 900_019. "
        "Run phase B (extract) after download completes."
    ),
    tags=["workers"],
)
async def trigger_run_brochure_download(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.brochure_ingestion import run_brochure_download

    return await _dispatch_worker(
        background_tasks, "run-brochure-download", "global",
        run_brochure_download,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-brochure-extract",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger ADV brochure text extraction",
    description=(
        "Phase B: Read brochure PDFs from StorageClient and extract text "
        "via PyMuPDF. Classifies into 18 ADV sections and extracts team "
        "members. No IAPD network calls — runs at full CPU speed. "
        "Uses advisory lock 900_020. Requires phase A (download) first."
    ),
    tags=["workers"],
)
async def trigger_run_brochure_extract(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.brochure_ingestion import run_brochure_extract

    return await _dispatch_worker(
        background_tasks, "run-brochure-extract", "global",
        run_brochure_extract,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-esma-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger ESMA UCITS universe ingestion",
    description=(
        "Schedules the ESMA ingestion worker as a background task. "
        "Fetches ~134K UCITS funds from the ESMA Solr register, "
        "deduplicates managers, resolves ISIN→ticker via OpenFIGI, "
        "and upserts into esma_managers, esma_funds, esma_isin_ticker_map. "
        "Uses advisory lock 900_019. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_esma_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.esma_ingestion import run_esma_ingestion

    return await _dispatch_worker(
        background_tasks, "run-esma-ingestion", "global",
        run_esma_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-sec-13f-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger SEC 13F holdings ingestion",
    description=(
        "Schedules the SEC 13F ingestion worker as a background task. "
        "Fetches quarterly 13F-HR filings from EDGAR for all managers with "
        "CIKs, computes quarter-over-quarter diffs, and enriches sectors. "
        "Upserts into sec_13f_holdings and sec_13f_diffs hypertables. "
        "Uses advisory lock 900_021. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_sec_13f_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.sec_13f_ingestion import run_sec_13f_ingestion

    return await _dispatch_worker(
        background_tasks, "run-sec-13f-ingestion", "global",
        run_sec_13f_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-sec-adv-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger SEC ADV bulk CSV ingestion",
    description=(
        "Schedules the SEC ADV ingestion worker as a background task. "
        "Downloads the latest monthly Form ADV CSV from SEC FOIA and "
        "upserts manager data into sec_managers and sec_manager_funds. "
        "Uses advisory lock 900_022. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_sec_adv_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.sec_adv_ingestion import run_sec_adv_ingestion

    return await _dispatch_worker(
        background_tasks, "run-sec-adv-ingestion", "global",
        run_sec_adv_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-portfolio-nav-synthesizer",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger portfolio NAV synthesis",
    description=(
        "Schedules the portfolio NAV synthesizer worker as a background task. "
        "Computes weighted synthetic NAV for all model portfolios with "
        "fund_selection_schema. Uses advisory lock 900_030 to prevent "
        "concurrent runs. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_portfolio_nav_synthesizer(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.portfolio_nav_synthesizer import run_portfolio_nav_synthesizer

    org_id = user.organization_id
    return await _dispatch_worker(
        background_tasks, "run-portfolio-nav-synthesizer", str(org_id),
        run_portfolio_nav_synthesizer, org_id,
        timeout_seconds=_LIGHT_WORKER_TIMEOUT, org_id=org_id,
    )


@router.post(
    "/run-wealth-embedding",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger wealth vector embedding worker",
    description=(
        "Schedules the wealth embedding worker as a background task. "
        "Processes ADV brochures, ESMA funds/managers, DD chapters, and "
        "macro reviews into wealth_vector_chunks with OpenAI embeddings. "
        "Incremental — only processes pending rows. Uses advisory lock 900_041. "
        "Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_wealth_embedding(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.wealth_embedding_worker import run_wealth_embedding

    return await _dispatch_worker(
        background_tasks, "run-wealth-embedding", "global",
        run_wealth_embedding,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-regime-fit",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger HMM regime fit worker",
    description=(
        "Schedules the regime fit worker as a background task. "
        "Fits a 2-state HMM on VIX history and persists the classified "
        "regime series into macro_regime_history. Consumed by risk_calc "
        "for regime-conditional CVaR. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_regime_fit(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.regime_fit import run_regime_fit

    return await _dispatch_worker(
        background_tasks, "run-regime-fit", "global",
        run_regime_fit,
        timeout_seconds=_LIGHT_WORKER_TIMEOUT,
    )


@router.post(
    "/run-nport-fund-discovery",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger N-PORT registered fund discovery",
    description=(
        "Schedules the N-PORT fund discovery worker as a background task. "
        "Discovers registered funds (mutual funds, ETFs) that file N-PORT via "
        "EDGAR EFTS, filters by AUM >= $50M, resolves adviser CIK to CRD, and "
        "upserts into sec_registered_funds. Uses advisory lock 900_024. "
        "Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_nport_fund_discovery(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.nport_fund_discovery import run_nport_fund_discovery

    return await _dispatch_worker(
        background_tasks, "run-nport-fund-discovery", "global",
        run_nport_fund_discovery,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-sec-bulk-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger quarterly SEC bulk data ingestion",
    description=(
        "Orchestrates quarterly refresh of all SEC EDGAR bulk datasets: "
        "N-CEN (registered funds + ETFs), N-MFP (money market), N-PORT, "
        "BDC list, and strategy_label backfill. Downloads ZIPs from SEC DERA, "
        "extracts, and runs all seed pipelines. "
        "Uses advisory lock 900_050. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_sec_bulk_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.sec_bulk_ingestion import run_sec_bulk_ingestion

    return await _dispatch_worker(
        background_tasks, "run-sec-bulk-ingestion", "global",
        run_sec_bulk_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-form345-ingestion",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Form 345 insider transaction ingestion",
    description=(
        "Downloads quarterly Form 3/4/5 insider transaction data from SEC EDGAR, "
        "parses SUBMISSION/REPORTINGOWNER/NONDERIV_TRANS TSV files, and upserts "
        "into sec_insider_transactions. Refreshes sec_insider_sentiment materialized view. "
        "Uses advisory lock 900_051. Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_form345_ingestion(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.form345_ingestion import run_form345_ingestion

    return await _dispatch_worker(
        background_tasks, "run-form345-ingestion", "global",
        run_form345_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-cusip-resolution",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger CUSIP → ticker resolution",
    description=(
        "Schedules the CUSIP resolution worker as a background task. "
        "Drains _cusip_resolve_queue and discovers new unresolved CUSIPs from "
        "sec_13f_holdings and sec_nport_holdings, resolves via OpenFIGI batch API, "
        "and upserts to sec_cusip_ticker_map. Uses advisory lock 900_025. "
        "Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_cusip_resolution(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.cusip_resolution import run_cusip_resolution

    return await _dispatch_worker(
        background_tasks, "run-cusip-resolution", "global",
        run_cusip_resolution,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
    )


@router.post(
    "/run-geography-enrichment",
    response_model=WorkerScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger investment geography enrichment",
    description=(
        "Schedules the geography enrichment worker as a background task. "
        "Classifies investment geography for all instruments using a 3-layer "
        "cascade: N-PORT country allocations, strategy_label/name keywords, "
        "default by fund_type/domicile. Uses advisory lock 900_060. "
        "Returns immediately."
    ),
    tags=["workers"],
)
async def trigger_run_geography_enrichment(
    background_tasks: BackgroundTasks,
    recalculate: bool = Query(default=False, description="Re-classify all instruments, not just NULLs"),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    _require_admin_role(actor)

    from app.domains.wealth.workers.geography_enrichment import run_geography_enrichment

    return await _dispatch_worker(
        background_tasks, "run-geography-enrichment", "global",
        run_geography_enrichment, recalculate,
        timeout_seconds=_LIGHT_WORKER_TIMEOUT,
    )


