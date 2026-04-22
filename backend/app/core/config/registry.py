"""Canonical Config Type Registry — CFG-04.

Single source of truth for all supported config domains.
ConfigService and admin routes validate against this registry.

Ownership models:
  - config_service: managed via ConfigService (vertical_config_defaults/overrides)
  - prompt_service: managed via PromptService (prompt_overrides table, filesystem .j2)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigDomain:
    """A registered config domain with its metadata."""

    vertical: str
    config_type: str
    ownership: str  # "config_service" | "prompt_service"
    client_visible: bool
    description: str
    required: bool = True  # CFG-01: required configs raise on miss, optional emit warning


# ── Registry ────────────────────────────────────────────────────────────────

_REGISTRY: tuple[ConfigDomain, ...] = (
    # ── liquid_funds: ConfigService-managed ──────────────────────────────
    ConfigDomain(
        vertical="liquid_funds",
        config_type="calibration",
        ownership="config_service",
        client_visible=True,
        description="Quant engine limits, regime thresholds, drift bands",
    ),
    ConfigDomain(
        vertical="liquid_funds",
        config_type="portfolio_profiles",
        ownership="config_service",
        client_visible=True,
        description="CVaR profiles, portfolio allocation parameters",
    ),
    ConfigDomain(
        vertical="liquid_funds",
        config_type="scoring",
        ownership="config_service",
        client_visible=True,
        description="Scoring weights for fund evaluation",
    ),
    # blocks: REMOVED — allocation_blocks table is the source of truth, not ConfigService.
    # chapters: REMOVED — CHAPTER_REGISTRY in dd_report/models.py is the source of truth.
    ConfigDomain(
        vertical="liquid_funds",
        config_type="macro_intelligence",
        ownership="config_service",
        client_visible=False,
        description="Macro committee config — regions, indicators, thresholds",
    ),
    ConfigDomain(
        vertical="liquid_funds",
        config_type="screening_layer1",
        ownership="config_service",
        client_visible=False,
        description="Screener quantitative filter criteria",
        required=False,
    ),
    ConfigDomain(
        vertical="liquid_funds",
        config_type="screening_layer2",
        ownership="config_service",
        client_visible=False,
        description="Screener qualitative filter criteria",
        required=False,
    ),
    ConfigDomain(
        vertical="liquid_funds",
        config_type="screening_layer3",
        ownership="config_service",
        client_visible=False,
        description="Screener AI-assisted deep filter criteria",
        required=False,
    ),
    # ── private_credit: ConfigService-managed ────────────────────────────
    ConfigDomain(
        vertical="private_credit",
        config_type="chapters",
        ownership="config_service",
        client_visible=False,
        description="IC memo analysis profile chapters (IP-protected)",
    ),
    ConfigDomain(
        vertical="private_credit",
        config_type="calibration",
        ownership="config_service",
        client_visible=True,
        description="Leverage limits, coverage ratios, underwriting thresholds",
    ),
    ConfigDomain(
        vertical="private_credit",
        config_type="scoring",
        ownership="config_service",
        client_visible=True,
        description="Credit scoring weights",
    ),
    ConfigDomain(
        vertical="private_credit",
        config_type="governance_policy",
        ownership="config_service",
        client_visible=False,
        description="Governance policy thresholds for document compliance",
    ),
    # ── cross-vertical: ConfigService-managed ────────────────────────────
    ConfigDomain(
        vertical="_admin",
        config_type="branding",
        ownership="config_service",
        client_visible=False,
        description="Tenant branding: logos, colors, display name",
        required=False,
    ),
    # ── wealth: ConfigService-managed ────────────────────────────────────
    ConfigDomain(
        vertical="wealth",
        config_type="optimizer",
        ownership="config_service",
        client_visible=False,
        description="Wealth construction-engine optimizer tunables (reserved for future per-tenant overrides)",
        required=False,
    ),
    ConfigDomain(
        vertical="wealth",
        config_type="command_palette",
        ownership="config_service",
        client_visible=False,
        description="Terminal command palette search/cache tunables",
        required=False,
    ),
)


class ConfigRegistry:
    """Canonical registry for all supported config domains."""

    _domains: ClassVar[dict[tuple[str, str], ConfigDomain]] = {
        (d.vertical, d.config_type): d for d in _REGISTRY
    }
    _version_hash: ClassVar[str] = ""

    @classmethod
    def get(cls, vertical: str, config_type: str) -> ConfigDomain | None:
        """Look up a registered config domain. Returns None if unregistered."""
        return cls._domains.get((vertical, config_type))

    @classmethod
    def is_registered(cls, vertical: str, config_type: str) -> bool:
        """Check if a (vertical, config_type) pair is in the registry."""
        return (vertical, config_type) in cls._domains

    @classmethod
    def all_domains(cls) -> list[ConfigDomain]:
        """Return all registered config domains."""
        return list(cls._domains.values())

    @classmethod
    def config_service_domains(cls) -> list[ConfigDomain]:
        """Return only ConfigService-managed domains."""
        return [d for d in cls._domains.values() if d.ownership == "config_service"]

    @classmethod
    def client_visible_types(cls) -> frozenset[str]:
        """Derive CLIENT_VISIBLE_TYPES from registry (must match ConfigService)."""
        return frozenset(d.config_type for d in cls._domains.values() if d.client_visible)

    @classmethod
    def verticals(cls) -> set[str]:
        """Return all registered verticals."""
        return {d.vertical for d in cls._domains.values()}

    @classmethod
    def types_for_vertical(cls, vertical: str) -> list[str]:
        """Return all config_types registered for a vertical."""
        return [d.config_type for d in cls._domains.values() if d.vertical == vertical]

    @classmethod
    def validate_lookup(cls, vertical: str, config_type: str) -> None:
        """Log warning if a config lookup targets an unregistered domain.

        Does NOT raise — enforcement is opt-in via CFG-01.
        Emits structured telemetry for observability.
        """
        if not cls.is_registered(vertical, config_type):
            logger.warning(
                "Config lookup for unregistered domain: vertical=%s config_type=%s",
                vertical,
                config_type,
                extra={
                    "event": "config_registry_miss",
                    "vertical": vertical,
                    "config_type": config_type,
                },
            )
