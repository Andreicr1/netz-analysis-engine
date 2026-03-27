"""Portfolio Engine — investment discovery, metrics, drift, covenants, risk, and board briefs.

Public API:
    run_portfolio_ingest()              — full portfolio monitoring pipeline (orchestrator)
    discover_active_investments()       — discover investments from document registry
    extract_portfolio_metrics()         — compute and persist portfolio metrics
    detect_performance_drift()          — detect metric drift across periods
    build_covenant_surveillance()       — build covenant status register
    reclassify_investment_risk()        — multi-dimensional risk reclassification
    build_board_monitoring_briefs()     — executive summaries per investment

Error contract: never-raises (orchestration engine called during portfolio ingest).
Catches exceptions, logs with exc_info=True, re-raises for caller transaction control.
"""
from vertical_engines.credit.portfolio.briefs import build_board_monitoring_briefs
from vertical_engines.credit.portfolio.covenants import build_covenant_surveillance
from vertical_engines.credit.portfolio.discovery import discover_active_investments
from vertical_engines.credit.portfolio.drift import detect_performance_drift
from vertical_engines.credit.portfolio.metrics import extract_portfolio_metrics
from vertical_engines.credit.portfolio.risk import reclassify_investment_risk
from vertical_engines.credit.portfolio.service import run_portfolio_ingest

__all__ = [
    "build_board_monitoring_briefs",
    "build_covenant_surveillance",
    "detect_performance_drift",
    "discover_active_investments",
    "extract_portfolio_metrics",
    "reclassify_investment_risk",
    "run_portfolio_ingest",
]
