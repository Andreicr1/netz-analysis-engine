"""AI module routes with explicit startup diagnostics and strict assembly."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass

from fastapi import APIRouter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SubRouterSpec:
    name: str
    module_path: str
    required: bool = True


@dataclass(frozen=True)
class AIRouterAssemblyDiagnostics:
    status: str
    loaded_modules: tuple[str, ...]
    degraded_modules: tuple[str, ...]
    required_modules: tuple[str, ...]
    optional_modules: tuple[str, ...]
    failure_details: tuple[tuple[str, str], ...]
    route_count: int


_SUBROUTER_SPECS: tuple[_SubRouterSpec, ...] = (
    _SubRouterSpec("copilot", "app.domains.credit.modules.ai.copilot"),
    _SubRouterSpec("documents", "app.domains.credit.modules.ai.documents"),
    _SubRouterSpec("compliance", "app.domains.credit.modules.ai.compliance"),
    _SubRouterSpec("pipeline_deals", "app.domains.credit.modules.ai.pipeline_deals"),
    _SubRouterSpec("extraction", "app.domains.credit.modules.ai.extraction", required=False),
    _SubRouterSpec("portfolio", "app.domains.credit.modules.ai.portfolio", required=False),
    _SubRouterSpec("deep_review", "app.domains.credit.modules.ai.deep_review"),
    _SubRouterSpec("memo_chapters", "app.domains.credit.modules.ai.memo_chapters"),
    _SubRouterSpec("artifacts", "app.domains.credit.modules.ai.artifacts"),
)

router = APIRouter(prefix="/ai", tags=["ai"])
_assembled = False
_ASSEMBLY_DIAGNOSTICS = AIRouterAssemblyDiagnostics(
    status="uninitialized",
    loaded_modules=(),
    degraded_modules=(),
    required_modules=tuple(spec.name for spec in _SUBROUTER_SPECS if spec.required),
    optional_modules=tuple(spec.name for spec in _SUBROUTER_SPECS if not spec.required),
    failure_details=(),
    route_count=0,
)


def _route_count() -> int:
    return len(router.routes)


def _import_subrouter(spec: _SubRouterSpec):
    module = importlib.import_module(spec.module_path)
    child_router = getattr(module, "router", None)
    if child_router is None:
        raise ImportError(f"{spec.module_path} does not expose a router")
    return child_router


def _update_diagnostics(
    *,
    status: str,
    loaded_modules: list[str],
    degraded_modules: list[str],
    failure_details: list[tuple[str, str]],
) -> None:
    global _ASSEMBLY_DIAGNOSTICS
    _ASSEMBLY_DIAGNOSTICS = AIRouterAssemblyDiagnostics(
        status=status,
        loaded_modules=tuple(loaded_modules),
        degraded_modules=tuple(degraded_modules),
        required_modules=tuple(spec.name for spec in _SUBROUTER_SPECS if spec.required),
        optional_modules=tuple(spec.name for spec in _SUBROUTER_SPECS if not spec.required),
        failure_details=tuple(failure_details),
        route_count=_route_count(),
    )


def get_ai_router_diagnostics() -> AIRouterAssemblyDiagnostics:
    return _ASSEMBLY_DIAGNOSTICS


def _assemble() -> None:
    global _assembled
    if _assembled:
        return

    loaded_modules: list[str] = []
    degraded_modules: list[str] = []
    failure_details: list[tuple[str, str]] = []

    for spec in _SUBROUTER_SPECS:
        try:
            router.include_router(_import_subrouter(spec))
            loaded_modules.append(spec.name)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if spec.required:
                failure_details.append((spec.name, detail))
            else:
                degraded_modules.append(spec.name)
                logger.warning(
                    "AI sub-router degraded: %s (%s)",
                    spec.name,
                    detail,
                )

    status = "healthy"
    if failure_details:
        status = "failed"
    elif degraded_modules:
        status = "degraded"

    _update_diagnostics(
        status=status,
        loaded_modules=loaded_modules,
        degraded_modules=degraded_modules,
        failure_details=failure_details,
    )

    logger.info(
        "AI router assembly status=%s loaded=%s degraded=%s route_count=%d",
        _ASSEMBLY_DIAGNOSTICS.status,
        ",".join(_ASSEMBLY_DIAGNOSTICS.loaded_modules) or "none",
        ",".join(_ASSEMBLY_DIAGNOSTICS.degraded_modules) or "none",
        _ASSEMBLY_DIAGNOSTICS.route_count,
    )

    if failure_details:
        failure_text = ", ".join(f"{name} ({detail})" for name, detail in failure_details)
        logger.error("AI router assembly failed required_modules=%s", failure_text)
        raise RuntimeError(f"Required AI sub-router import failed: {failure_text}")

    _assembled = True


_assemble()
