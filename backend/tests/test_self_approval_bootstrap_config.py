"""PR-OPS-2 — bootstrap-only self-approval policy seed.

Validates the migration 0200 contract:

* Bootstrap org (``403d8392-ebfa-5890-b740-45da49c556eb``) resolves to
  ``allow_self_approval=True`` because the migration seeds a per-org
  override row in ``vertical_config_overrides``.
* Any other org id resolves to the conservative default
  (``allow_self_approval=False``) because the migration intentionally
  does NOT insert a default row in ``vertical_config_defaults`` — the
  ``approval_policy`` domain is registered as ``required=False``, so a
  total miss returns a typed ``MISSING_OPTIONAL`` ``ConfigResult`` with
  ``value={}``, and ``_resolve_approval_policy`` deserialises that into
  the conservative ``ApprovalPolicy()`` defaults.

These tests are unit-level: they stub ``ConfigService.get`` to return
the ``ConfigResult`` payloads the migration is expected to produce so
they run without a live database, and they assert the mapping
``ConfigResult → ApprovalPolicy`` that the route layer relies on.

This pairs with the migration unit; together they prove the
end-to-end posture: bootstrap = self-approve allowed, every other
tenant = conservative posture (institutional default per
``docs/plans/2026-04-30-builder-workspace-redesign-final.md`` §1.1).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config.schemas import ConfigResult, ConfigResultState

BOOTSTRAP_ORG_ID = uuid.UUID("403d8392-ebfa-5890-b740-45da49c556eb")


@pytest.mark.asyncio
async def test_bootstrap_org_resolves_to_self_approval_true() -> None:
    """Bootstrap org override yields allow_self_approval=True.

    Mirrors the post-migration state where ``vertical_config_overrides``
    has a row for (BOOTSTRAP_ORG_ID, 'wealth', 'approval_policy') with
    payload ``{"allow_self_approval": true,
    "require_construction_for_approve": true}``.
    """
    from app.domains.wealth.routes.model_portfolios import (
        _resolve_approval_policy,
    )

    seeded_payload = {
        "allow_self_approval": True,
        "require_construction_for_approve": True,
    }
    fake_result = ConfigResult(
        value=seeded_payload,
        state=ConfigResultState.FOUND,
        source="db_override+db_default",
    )

    db = AsyncMock()
    with patch(
        "app.domains.wealth.routes.model_portfolios.ConfigService.get",
        new=AsyncMock(return_value=fake_result),
    ):
        policy = await _resolve_approval_policy(db, BOOTSTRAP_ORG_ID)

    assert policy.allow_self_approval is True, (
        "Bootstrap org must resolve allow_self_approval=True per "
        "migration 0200 + the institutional posture documented in "
        "docs/plans/2026-04-30-builder-workspace-redesign-final.md §9 "
        "(PR-OPS-2)."
    )
    assert policy.require_construction_for_approve is True, (
        "Bootstrap-only loosens *who* may approve, not *what* must be "
        "validated first — construction gate must remain True."
    )


@pytest.mark.asyncio
async def test_arbitrary_new_tenant_resolves_to_self_approval_false() -> None:
    """A random new-tenant UUID resolves to the conservative default.

    Mirrors the post-migration state for any org id other than the
    bootstrap one: no override row exists and the migration intentionally
    does NOT insert a default. ``ConfigService.get`` therefore returns a
    typed-miss with ``value={}`` (``MISSING_OPTIONAL`` because the
    domain is registered as ``required=False``).
    ``_resolve_approval_policy`` must coerce ``{}`` into the conservative
    ``ApprovalPolicy()`` defaults — never raise, never silently grant
    self-approval.
    """
    from app.domains.wealth.routes.model_portfolios import (
        _resolve_approval_policy,
    )

    new_tenant_id = uuid.uuid4()
    assert new_tenant_id != BOOTSTRAP_ORG_ID, (
        "uuid4() collision with the bootstrap UUID is astronomically "
        "improbable — sanity guard for the test contract."
    )

    typed_miss = ConfigResult(
        value={},
        state=ConfigResultState.MISSING_OPTIONAL,
        source="miss",
    )

    db = AsyncMock()
    with patch(
        "app.domains.wealth.routes.model_portfolios.ConfigService.get",
        new=AsyncMock(return_value=typed_miss),
    ):
        policy = await _resolve_approval_policy(db, new_tenant_id)

    assert policy.allow_self_approval is False, (
        "External tenants MUST default to allow_self_approval=False — "
        "institutional posture is non-negotiable. Migration 0200 is "
        "bootstrap-only by design."
    )
    assert policy.require_construction_for_approve is True, (
        "Construction gate must default True for external tenants."
    )
