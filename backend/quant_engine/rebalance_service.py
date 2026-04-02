"""Rebalance workflow service.

Implements the rebalance cascade state machine:
    ok → warning → breach → hard_stop

Each state transition creates a RebalanceEvent with actor_source tracking.

Config is injected as parameter by callers via ConfigService.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import structlog

from quant_engine.cvar_service import resolve_cvar_config

logger = structlog.get_logger()

# Valid status transitions
VALID_TRANSITIONS = {
    "pending": {"approved", "rejected", "cancelled", "applied"},
    "approved": {"executed"},
    "rejected": set(),
    "cancelled": set(),
    "executed": set(),
}


@dataclass
class CascadeResult:
    previous_status: str
    new_status: str
    event_created: bool
    event_id: uuid.UUID | None = None
    reason: str | None = None


def determine_cascade_action(
    trigger_status: str,
    previous_trigger_status: str | None,
    cvar_utilized_pct: float,
    consecutive_breach_days: int,
    profile: str,
    config: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Determine if a cascade action is needed based on status transition.

    Args:
        config: portfolio_profiles config dict from ConfigService.

    Returns (event_type, trigger_reason) or (None, None) if no action needed.

    """
    profiles = resolve_cvar_config(config)
    profile_config = profiles[profile]

    if trigger_status == "ok":
        return None, None

    if trigger_status == "warning" and previous_trigger_status in (None, "ok"):
        return "cvar_breach", (
            f"CVaR utilization at {cvar_utilized_pct:.1f}% "
            f"(warning threshold: {profile_config['warning_pct'] * 100:.0f}%)"
        )

    if trigger_status == "breach" and previous_trigger_status != "breach":
        return "cvar_breach", (
            f"CVaR breach: {consecutive_breach_days} consecutive days "
            f"above limit (threshold: {profile_config['breach_days']})"
        )

    return None, None


def validate_status_transition(current_status: str, new_status: str) -> bool:
    """Check if a status transition is valid."""
    valid_next = VALID_TRANSITIONS.get(current_status, set())
    return new_status in valid_next
