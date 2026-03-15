"""Pipeline Intelligence Engine — deal screening and IC memo generation.

Public API:
    generate_pipeline_intelligence()  — two-call structured + memo flow
    run_pipeline_ingest()             — orchestrate discovery + aggregation + monitoring
    discover_pipeline_deals()         — deal registration from blob folders
    aggregate_deal_documents()        — document intelligence mapping
    run_pipeline_monitoring()         — alert generation
    compute_completeness_score()      — data-room completeness scoring

Error contract: never-raises (orchestration engine). Returns empty dict/list
on failure, sets intelligence_status to FAILED.
"""
from vertical_engines.credit.pipeline.discovery import (
    aggregate_deal_documents,
    discover_pipeline_deals,
)
from vertical_engines.credit.pipeline.intelligence import (
    generate_pipeline_intelligence,
)
from vertical_engines.credit.pipeline.monitoring import (
    run_pipeline_monitoring,
)
from vertical_engines.credit.pipeline.screening import (
    compute_completeness_score,
)
from vertical_engines.credit.pipeline.service import run_pipeline_ingest

__all__ = [
    "generate_pipeline_intelligence",
    "run_pipeline_ingest",
    "discover_pipeline_deals",
    "aggregate_deal_documents",
    "run_pipeline_monitoring",
    "compute_completeness_score",
]
