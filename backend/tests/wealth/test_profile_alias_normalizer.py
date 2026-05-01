"""PR-BE-7 — backward-compat alias normalisation for legacy ``aggressive``.

Covers four surfaces:
  * ``default_cvar_limit_for_profile`` (model layer)
  * ``_PROPOSE_VALID_PROFILES`` (propose-mode endpoint allowlist)
  * ``normalize_profile_param`` (URL path-param normaliser module)
  * ``validate_profile`` (shared route helper, post-PR-BE-7)

Sunset target for the alias: 2026-10-30 (180 days post-merge).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.domains.wealth.models.model_portfolio import default_cvar_limit_for_profile
from app.domains.wealth.routes._profile_normalizer import normalize_profile_param
from app.domains.wealth.routes.common import validate_profile
from app.domains.wealth.routes.model_portfolios import _PROPOSE_VALID_PROFILES

# ── Model-layer alias ────────────────────────────────────────────────


def test_growth_default_cvar_unchanged() -> None:
    """Status-quo regression — growth keeps the 0.1000 CVaR default."""
    assert default_cvar_limit_for_profile("growth") == Decimal("0.1000")


def test_aggressive_alias_returns_growth_default() -> None:
    """Legacy ``aggressive`` resolves to the growth default (0.1000)."""
    assert default_cvar_limit_for_profile("aggressive") == Decimal("0.1000")


def test_aggressive_uppercase_alias_resolves_to_growth() -> None:
    """Case-insensitive normalisation also rewrites the alias."""
    assert default_cvar_limit_for_profile("AGGRESSIVE") == Decimal("0.1000")


# ── Propose-mode allowlist ───────────────────────────────────────────


def test_propose_valid_profiles_excludes_aggressive() -> None:
    """``_PROPOSE_VALID_PROFILES`` no longer carries the legacy slug."""
    assert "growth" in _PROPOSE_VALID_PROFILES
    assert "conservative" in _PROPOSE_VALID_PROFILES
    assert "moderate" in _PROPOSE_VALID_PROFILES
    assert "aggressive" not in _PROPOSE_VALID_PROFILES


# ── URL alias normaliser ─────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [
    ("conservative", "conservative"),
    ("moderate", "moderate"),
    ("growth", "growth"),
    ("Conservative", "conservative"),
    ("GROWTH", "growth"),
])
def test_normalize_profile_param_canonical_passthrough(raw: str, expected: str) -> None:
    assert normalize_profile_param(raw) == expected


def test_normalize_profile_param_aggressive_alias_resolves_to_growth() -> None:
    """Legacy URL ``/allocation/aggressive/strategic`` resolves to growth."""
    assert normalize_profile_param("aggressive") == "growth"
    assert normalize_profile_param("Aggressive") == "growth"
    assert normalize_profile_param(" AGGRESSIVE ") == "growth"


def test_normalize_profile_param_invalid_profile_rejected() -> None:
    """Unknown slugs raise 400 with the list of valid profiles."""
    with pytest.raises(HTTPException) as exc:
        normalize_profile_param("dynamic")
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["error"] == "invalid_profile"
    assert sorted(detail["valid_profiles"]) == ["conservative", "growth", "moderate"]


# ── Shared validate_profile (existing helper) ────────────────────────


def test_validate_profile_aggressive_alias_resolves_to_growth() -> None:
    """The shared validator rewrites legacy ``aggressive`` to ``growth``."""
    assert validate_profile("aggressive") == "growth"


@pytest.mark.parametrize("slug", ["conservative", "moderate", "growth"])
def test_validate_profile_canonical_passthrough(slug: str) -> None:
    assert validate_profile(slug) == slug


def test_validate_profile_unknown_slug_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_profile("speculative")
    assert exc.value.status_code == 400
