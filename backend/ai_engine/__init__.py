"""Public AI engine entry points.

Keep imports lazy so lightweight modules (tests, validation helpers, schemas)
can import ``ai_engine.*`` without pulling optional Azure dependencies at
module-import time.
"""


def run_daily_cycle(*args, **kwargs):
    from .ingestion.monitoring import run_daily_cycle as _impl

    return _impl(*args, **kwargs)


def run_documents_ingest_pipeline(*args, **kwargs):
    from .ingestion.document_scanner import run_documents_ingest_pipeline as _impl

    return _impl(*args, **kwargs)


def run_pipeline_ingest(*args, **kwargs):
    from .intelligence.pipeline_intelligence import run_pipeline_ingest as _impl

    return _impl(*args, **kwargs)


def run_portfolio_ingest(*args, **kwargs):
    from .intelligence.portfolio_intelligence import run_portfolio_ingest as _impl

    return _impl(*args, **kwargs)


__all__ = [
    "run_daily_cycle",
    "run_documents_ingest_pipeline",
    "run_pipeline_ingest",
    "run_portfolio_ingest",
]
