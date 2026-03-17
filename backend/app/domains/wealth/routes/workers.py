"""Workers router — HTTP trigger endpoints for background workers.

Allows CI pipelines, scheduled jobs, and admin UIs to trigger
ingestion, risk calculation, and portfolio evaluation via the API.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.domains.wealth.workers.ingestion import run_ingestion
from app.domains.wealth.workers.macro_ingestion import run_macro_ingestion
from app.domains.wealth.workers.portfolio_eval import run_portfolio_eval
from app.domains.wealth.workers.risk_calc import run_risk_calc
from app.shared.enums import Role

router = APIRouter(prefix="/workers")


def _require_admin_role(actor: Actor) -> None:
    if not actor.has_role(Role.INVESTMENT_TEAM) and not actor.has_role(Role.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or IC role required")


class WorkerScheduledResponse(BaseModel):
    status: str
    worker: str


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
    background_tasks.add_task(run_ingestion)
    return WorkerScheduledResponse(status="scheduled", worker="run-ingestion")


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
    background_tasks.add_task(run_risk_calc)
    return WorkerScheduledResponse(status="scheduled", worker="run-risk-calc")


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
    background_tasks.add_task(run_portfolio_eval)
    return WorkerScheduledResponse(status="scheduled", worker="run-portfolio-eval")


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
    background_tasks.add_task(run_macro_ingestion)
    return WorkerScheduledResponse(status="scheduled", worker="run-macro-ingestion")


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

    background_tasks.add_task(run_monthly_fact_sheets)
    return WorkerScheduledResponse(status="scheduled", worker="run-fact-sheet-gen")


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
    background_tasks.add_task(run_watchlist_check, org_id)
    return WorkerScheduledResponse(status="scheduled", worker="run-watchlist-check")


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

    # org_id needs to be passed to the worker
    org_id = user.organization_id
    background_tasks.add_task(run_screening_batch, org_id)
    return WorkerScheduledResponse(status="scheduled", worker="run-screening-batch")
