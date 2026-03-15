"""Deals module service — stub for Sprint 2b.

Full pipeline deal CRUD implemented in Sprint 3 when the pipeline
intelligence engine is wired.
"""

from __future__ import annotations

from typing import Any


def list_deals(*args: Any, **kwargs: Any) -> list[Any]:
    raise NotImplementedError("Pipeline deals service — Sprint 3")


def build_deal_context_dict(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError("Pipeline deals service — Sprint 3")


def create_deal(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("Pipeline deals service — Sprint 3")


def patch_stage(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("Pipeline deals service — Sprint 3")


def decide(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("Pipeline deals service — Sprint 3")


def run_qualification(*args: Any, **kwargs: Any) -> tuple[Any, ...]:
    raise NotImplementedError("Pipeline deals service — Sprint 3")


def approve_pipeline_deal(*args: Any, **kwargs: Any) -> tuple[Any, ...]:
    raise NotImplementedError("Pipeline deals service — Sprint 3")


def list_deal_events(*args: Any, **kwargs: Any) -> list[Any]:
    raise NotImplementedError("Pipeline deals service — Sprint 3")
