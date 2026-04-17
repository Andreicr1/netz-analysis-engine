"""PR-A12.2 — profile-differentiated CVaR defaults."""
from __future__ import annotations

from decimal import Decimal

from app.domains.wealth.models.model_portfolio import default_cvar_limit_for_profile


def test_conservative_default() -> None:
    assert default_cvar_limit_for_profile("conservative") == Decimal("0.0250")


def test_moderate_default() -> None:
    assert default_cvar_limit_for_profile("moderate") == Decimal("0.0500")


def test_growth_default() -> None:
    assert default_cvar_limit_for_profile("growth") == Decimal("0.0800")


def test_aggressive_default() -> None:
    assert default_cvar_limit_for_profile("aggressive") == Decimal("0.1000")


def test_unknown_profile_falls_back_to_moderate() -> None:
    assert default_cvar_limit_for_profile("custom_profile") == Decimal("0.0500")


def test_none_profile_falls_back_to_moderate() -> None:
    assert default_cvar_limit_for_profile(None) == Decimal("0.0500")


def test_case_insensitive() -> None:
    assert default_cvar_limit_for_profile("CONSERVATIVE") == Decimal("0.0250")
    assert default_cvar_limit_for_profile("Growth") == Decimal("0.0800")
