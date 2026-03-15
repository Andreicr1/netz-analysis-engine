"""Agent context — stub for Sprint 2b. Full implementation in Sprint 3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentUIContext:
    fund_id: str = ""
    actor_id: str = ""
    root_folder: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def build_agent_runtime_context(**kwargs: Any) -> dict[str, Any]:
    return {}
