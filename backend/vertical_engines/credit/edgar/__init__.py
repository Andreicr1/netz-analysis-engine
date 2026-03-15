"""EDGAR data package — SEC filing data powered by edgartools.

Public API:
    fetch_edgar_data()       — single-entity lookup (never raises)
    fetch_edgar_multi_entity()  — batch with CIK dedup + parallel processing
    build_edgar_multi_entity_context()  — LLM context serializer with attribution
    extract_searchable_entities()  — entity extraction from deal fields + analysis
"""
from vertical_engines.credit.edgar.entity_extraction import (
    extract_searchable_entities,
)

__all__ = [
    "extract_searchable_entities",
    "fetch_edgar_data",
    "fetch_edgar_multi_entity",
    "build_edgar_multi_entity_context",
]


def fetch_edgar_data(*args, **kwargs):  # type: ignore[no-untyped-def]
    """Lazy import to avoid loading edgartools at module level."""
    from vertical_engines.credit.edgar.service import fetch_edgar_data as _impl
    return _impl(*args, **kwargs)


def fetch_edgar_multi_entity(*args, **kwargs):  # type: ignore[no-untyped-def]
    """Lazy import to avoid loading edgartools at module level."""
    from vertical_engines.credit.edgar.service import fetch_edgar_multi_entity as _impl
    return _impl(*args, **kwargs)


def build_edgar_multi_entity_context(*args, **kwargs):  # type: ignore[no-untyped-def]
    """Lazy import to avoid loading edgartools at module level."""
    from vertical_engines.credit.edgar.context_serializer import (
        build_edgar_multi_entity_context as _impl,
    )
    return _impl(*args, **kwargs)
