"""Workers router — HTTP trigger endpoints for background workers.

Allows CI pipelines, scheduled jobs, and admin UIs to trigger
ingestion, risk calculation, and portfolio evaluation via the API.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.domains.wealth.workers.ingestion import run_ingestion
from app.domains.wealth.workers.portfolio_eval import run_portfolio_eval
from app.domains.wealth.workers.risk_calc import run_risk_calc

router = APIRouter(prefix="/workers")


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
) -> WorkerScheduledResponse:
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
) -> WorkerScheduledResponse:
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
) -> WorkerScheduledResponse:
    background_tasks.add_task(run_portfolio_eval)
    return WorkerScheduledResponse(status="scheduled", worker="run-portfolio-eval")
