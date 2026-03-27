"""EDGAR data package — SEC filing data powered by edgartools.

Public API:
    fetch_edgar_data()       — single-entity lookup (never raises)
    fetch_edgar_multi_entity()  — batch with CIK dedup + parallel processing
    build_edgar_multi_entity_context()  — LLM context serializer with attribution
    extract_searchable_entities()  — entity extraction from deal fields + analysis
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vertical_engines.credit.edgar.entity_extraction import (
    extract_searchable_entities,
)

if TYPE_CHECKING:
    from vertical_engines.credit.edgar.context_serializer import (
        build_edgar_multi_entity_context as build_edgar_multi_entity_context,
    )
    from vertical_engines.credit.edgar.service import (
        fetch_edgar_data as fetch_edgar_data,
    )
    from vertical_engines.credit.edgar.service import (
        fetch_edgar_multi_entity as fetch_edgar_multi_entity,
    )

__all__ = [
    "build_edgar_multi_entity_context",
    "extract_searchable_entities",
    "fetch_edgar_data",
    "fetch_edgar_multi_entity",
]


def __getattr__(name: str) -> Any:
    if name == "fetch_edgar_data":
        from vertical_engines.credit.edgar.service import fetch_edgar_data

        return fetch_edgar_data
    if name == "fetch_edgar_multi_entity":
        from vertical_engines.credit.edgar.service import fetch_edgar_multi_entity

        return fetch_edgar_multi_entity
    if name == "build_edgar_multi_entity_context":
        from vertical_engines.credit.edgar.context_serializer import (
            build_edgar_multi_entity_context,
        )

        return build_edgar_multi_entity_context
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
