"""Agent runtime context for the Netz Global Intelligence Agent.

Provides structured context that gets injected into the agent's prompt
so the LLM understands the current environment, available endpoints,
and pipeline capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentUIContext:
    """UI-side context passed from the frontend to scope agent responses."""

    current_view: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    entity_name: str | None = None
    context_doc_title: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def build_agent_runtime_context(**kwargs: Any) -> dict[str, Any]:
    """Build runtime context dict injected into the agent's user prompt.

    Returns a static dict describing available API endpoints and pipeline
    capabilities.  No DB queries or complex logic -- just useful context
    for the LLM to understand what the system can do.

    Parameters accepted via **kwargs (all optional):
        actor, db, fund_id, deal_folder, domains, ui_context
    """
    ui_context: AgentUIContext | None = kwargs.get("ui_context")
    deal_folder: str | None = kwargs.get("deal_folder")
    domains: list[str] | None = kwargs.get("domains")

    context: dict[str, Any] = {
        "available_endpoints": [
            {"method": "GET", "path": "/api/v1/credit/deals", "description": "List deals in pipeline"},
            {"method": "GET", "path": "/api/v1/credit/deals/{deal_id}", "description": "Deal detail with metadata"},
            {"method": "GET", "path": "/api/v1/credit/portfolio", "description": "Portfolio overview"},
            {"method": "GET", "path": "/api/v1/credit/portfolio/alerts", "description": "Portfolio alerts and actions"},
            {"method": "GET", "path": "/api/v1/credit/dashboard", "description": "Dashboard aggregation"},
            {"method": "POST", "path": "/api/v1/credit/documents/upload-url", "description": "Upload document"},
            {"method": "GET", "path": "/api/v1/credit/documents", "description": "List documents"},
            {"method": "POST", "path": "/api/v1/credit/documents/{id}/process", "description": "Process pending document"},
            {"method": "GET", "path": "/api/v1/credit/dataroom/search", "description": "Search dataroom"},
            {"method": "GET", "path": "/api/v1/credit/dataroom/folders", "description": "Dataroom folder governance"},
            {"method": "POST", "path": "/api/v1/credit/deals/{deal_id}/memo", "description": "Generate IC memo"},
            {"method": "GET", "path": "/api/v1/credit/reporting", "description": "Report packs"},
            {"method": "POST", "path": "/api/v1/credit/agent/query", "description": "Global agent query"},
        ],
        "pipeline_status": (
            "Unified deterministic pipeline: OCR -> classification -> chunking "
            "-> extraction -> embedding -> indexing. Real-time SSE progress events "
            "are emitted for each stage. Configuration managed via ConfigService."
        ),
    }

    # Add scoping context when available
    if deal_folder:
        context["current_deal_folder"] = deal_folder
    if domains:
        context["active_domains"] = domains

    # Add UI context when the agent is invoked from a specific view
    if ui_context and isinstance(ui_context, AgentUIContext):
        ui_dict = {
            k: v for k, v in {
                "current_view": ui_context.current_view,
                "entity_type": ui_context.entity_type,
                "entity_id": ui_context.entity_id,
                "entity_name": ui_context.entity_name,
                "context_doc_title": ui_context.context_doc_title,
            }.items() if v is not None
        }
        if ui_dict:
            context["ui_context"] = ui_dict

    return context
