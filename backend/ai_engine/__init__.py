"""Public AI engine entry points.

Keep imports lazy so lightweight modules (tests, validation helpers, schemas)
can import ``ai_engine.*`` without pulling vertical-specific runtime
dependencies at module-import time.

The legacy re-exports below resolve through the shared vertical selector rather
than importing any one vertical package directly at import time.
"""

from .vertical_registry import resolve_vertical_export


def _run_profile_export(profile_name: str, export_name: str, *args, **kwargs):
    impl = resolve_vertical_export(profile_name, export_name)
    return impl(*args, **kwargs)


def run_daily_cycle(*args, **kwargs):
    from .ingestion.monitoring import run_daily_cycle as _impl

    return _impl(*args, **kwargs)


def run_documents_ingest_pipeline(*args, **kwargs):
    from .ingestion.document_scanner import run_documents_ingest_pipeline as _impl

    return _impl(*args, **kwargs)


def run_pipeline_ingest(*args, **kwargs):
    return _run_profile_export("private_credit", "run_pipeline_ingest", *args, **kwargs)


def run_portfolio_ingest(*args, **kwargs):
    return _run_profile_export("private_credit", "run_portfolio_ingest", *args, **kwargs)


__all__ = [
    "run_daily_cycle",
    "run_documents_ingest_pipeline",
    "run_pipeline_ingest",
    "run_portfolio_ingest",
]
