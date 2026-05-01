"""PR-BE-7 — backward-compat URL alias normaliser for profile path params.

Maps the legacy ``aggressive`` profile slug to the canonical ``growth``
slug with a structured deprecation log so the sunset dashboard can
track residual usage. ``aggressive`` was a development artefact and is
not a canonical product profile; ``growth`` is the institutional
"Dynamic Growth" profile (display label resolved by
``profile_display_label`` / ``profileDisplayLabel``).

Sunset target: 2026-10-30 (180 days post-merge).

Usage in route handlers
-----------------------
    from app.domains.wealth.routes._profile_normalizer import (
        normalize_profile_param,
    )

    @router.get("/{profile}/strategic")
    async def get_strategic(profile: str, ...):
        profile = normalize_profile_param(profile)
        ...

Unknown profiles raise ``HTTPException(400)`` with the list of valid
slugs in ``detail`` so a misconfigured client gets actionable feedback
instead of a downstream "no rows found" 404. Tenant-scoped custom
profiles are out of scope here (Q6 / v2 / post-GA) and will land via a
ConfigService-backed registry rather than by widening this hardcoded
allowlist.
"""

from __future__ import annotations

import structlog
from fastapi import HTTPException

logger = structlog.get_logger()

_LEGACY_PROFILE_ALIASES: dict[str, str] = {"aggressive": "growth"}
_VALID_PROFILES: frozenset[str] = frozenset({"conservative", "moderate", "growth"})
_SUNSET_DATE = "2026-10-30"


def normalize_profile_param(profile: str) -> str:
    """Resolve a path-param profile slug, accepting one legacy alias.

    Returns the canonical lowercase slug. Emits ``legacy_profile_url_alias``
    when the legacy ``aggressive`` slug is received. Raises 400 for any
    other unknown slug — never silently passes through to downstream
    queries that would 404 with a confusing "no allocation found"
    message.
    """
    lc = profile.strip().lower()
    if lc in _LEGACY_PROFILE_ALIASES:
        canonical = _LEGACY_PROFILE_ALIASES[lc]
        logger.info(
            "legacy_profile_url_alias",
            received=profile,
            canonical=canonical,
            sunset_at=_SUNSET_DATE,
        )
        return canonical
    if lc not in _VALID_PROFILES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_profile",
                "message": f"Profile '{profile}' is not recognized.",
                "valid_profiles": sorted(_VALID_PROFILES),
            },
        )
    return lc


__all__ = ["normalize_profile_param"]
