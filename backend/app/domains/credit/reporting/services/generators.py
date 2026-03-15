"""Report section generators — stub for Sprint 2b.

These will be fully implemented when reporting is connected to real data.
"""

from __future__ import annotations

from typing import Any


def generate_nav_summary(**kwargs: Any) -> dict[str, Any]:
    return {"section": "nav_summary", "data": {}}


def generate_portfolio_exposure(**kwargs: Any) -> dict[str, Any]:
    return {"section": "portfolio_exposure", "data": {}}


def generate_overdue_obligations(**kwargs: Any) -> dict[str, Any]:
    return {"section": "overdue_obligations", "data": {}}


def generate_open_actions(**kwargs: Any) -> dict[str, Any]:
    return {"section": "open_actions", "data": {}}
