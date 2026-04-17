"""Tests for canonical config type registry (CFG-04)."""

from __future__ import annotations

import logging

import pytest

from app.core.config.config_service import ConfigService
from app.core.config.registry import ConfigRegistry


class TestRegistryCompleteness:
    """Registry must enumerate every config domain used in the codebase."""

    def test_all_yaml_fallback_keys_registered(self):
        """Every key in _YAML_FALLBACK_MAP must be in the registry."""
        from app.core.config.config_service import _YAML_FALLBACK_MAP

        for vertical, config_type in _YAML_FALLBACK_MAP:
            assert ConfigRegistry.is_registered(vertical, config_type), (
                f"YAML fallback key ({vertical}, {config_type}) not in registry"
            )

    def test_client_visible_types_match_registry(self):
        """CLIENT_VISIBLE_TYPES must agree with registry client_visible flags."""
        registry_visible = ConfigRegistry.client_visible_types()
        assert registry_visible == ConfigService.CLIENT_VISIBLE_TYPES, (
            f"Mismatch: registry={registry_visible}, "
            f"ConfigService={ConfigService.CLIENT_VISIBLE_TYPES}"
        )

    def test_no_duplicate_domains(self):
        """Each (vertical, config_type) pair appears exactly once."""
        seen: set[tuple[str, str]] = set()
        for domain in ConfigRegistry.all_domains():
            key = (domain.vertical, domain.config_type)
            assert key not in seen, f"Duplicate registry entry: {key}"
            seen.add(key)

    def test_all_domains_have_description(self):
        for domain in ConfigRegistry.all_domains():
            assert domain.description, (
                f"Missing description: ({domain.vertical}, {domain.config_type})"
            )

    def test_all_domains_have_valid_ownership(self):
        valid = {"config_service", "prompt_service"}
        for domain in ConfigRegistry.all_domains():
            assert domain.ownership in valid, (
                f"Invalid ownership '{domain.ownership}' for "
                f"({domain.vertical}, {domain.config_type})"
            )


class TestRegistryLookup:
    def test_registered_domain_found(self):
        domain = ConfigRegistry.get("liquid_funds", "calibration")
        assert domain is not None
        assert domain.ownership == "config_service"
        assert domain.client_visible is True

    def test_unregistered_domain_returns_none(self):
        assert ConfigRegistry.get("nonexistent", "bogus") is None

    def test_is_registered_true(self):
        assert ConfigRegistry.is_registered("private_credit", "chapters")

    def test_is_registered_false(self):
        assert not ConfigRegistry.is_registered("private_credit", "nonexistent")

    def test_types_for_vertical(self):
        types = ConfigRegistry.types_for_vertical("liquid_funds")
        assert "calibration" in types
        assert "scoring" in types
        assert "macro_intelligence" in types

    def test_verticals(self):
        verticals = ConfigRegistry.verticals()
        assert "liquid_funds" in verticals
        assert "private_credit" in verticals
        assert "wealth" in verticals

    def test_wealth_optimizer_registered_as_optional(self):
        """PR-A9.1: wealth/optimizer must be registered (otherwise any future
        ``config_svc.get("wealth", "optimizer", ...)`` call would raise
        ConfigMissError). Currently there is no production reader, but the
        domain is reserved for future per-tenant overrides. required=False
        so absence of seed/override returns an empty ConfigResult instead
        of raising.
        """
        domain = ConfigRegistry.get("wealth", "optimizer")
        assert domain is not None, "wealth/optimizer must be registered"
        assert domain.required is False, "must be optional — no seed data exists"
        assert domain.client_visible is False, "optimizer internals are IP-protected"
        assert domain.ownership == "config_service"

    def test_config_service_domains_excludes_prompt_service(self):
        for d in ConfigRegistry.config_service_domains():
            assert d.ownership == "config_service"


class TestRegistryValidation:
    def test_validate_lookup_warns_on_unregistered(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.config.registry"):
            ConfigRegistry.validate_lookup("fake_vertical", "fake_type")
        assert "unregistered domain" in caplog.text.lower()

    def test_validate_lookup_silent_on_registered(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.config.registry"):
            ConfigRegistry.validate_lookup("liquid_funds", "calibration")
        assert "unregistered" not in caplog.text.lower()


class TestRegistryConsistency:
    """Screening layers and known consumer config_types must all be registered."""

    @pytest.mark.parametrize("config_type", [
        "screening_layer1",
        "screening_layer2",
        "screening_layer3",
    ])
    def test_screening_layers_registered(self, config_type: str):
        assert ConfigRegistry.is_registered("liquid_funds", config_type)

    def test_governance_policy_registered(self):
        assert ConfigRegistry.is_registered("private_credit", "governance_policy")

    def test_macro_intelligence_registered(self):
        assert ConfigRegistry.is_registered("liquid_funds", "macro_intelligence")

    def test_branding_registered(self):
        assert ConfigRegistry.is_registered("_admin", "branding")

    def test_frozen_domain_dataclass(self):
        domain = ConfigRegistry.get("liquid_funds", "calibration")
        assert domain is not None
        with pytest.raises(AttributeError):
            domain.config_type = "hacked"  # type: ignore[misc]
