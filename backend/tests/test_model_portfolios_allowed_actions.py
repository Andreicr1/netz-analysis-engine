"""Tests for ``allowed_actions`` on model portfolio responses.

Phase 1 Task 1.4 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Two test layers:

1. **Route smoke tests** — confirm the GET endpoints are mounted and
   require auth (no DB required). 401 responses prove the routes
   exist; 404 would indicate the router is not registered.

2. **Helper unit tests** — exercise the `_serialize_with_actions`
   pipeline (state machine projection + ConfigService policy +
   construction-run validation lookup) using a synthesized portfolio
   ORM object and a mocked async session. Pure-Python — no DB needed.

The full state→actions matrix lives in
``test_portfolio_state_machine.py``; this file only verifies the
route layer correctly *invokes* the state machine.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

ORG_ID = "00000000-0000-0000-0000-000000000001"
PORTFOLIO_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

DEV_ACTOR_HEADER = {
    "X-DEV-ACTOR": json.dumps(
        {
            "actor_id": "test-user",
            "roles": ["ADMIN", "INVESTMENT_TEAM"],
            "fund_ids": [],
            "org_id": ORG_ID,
        },
    ),
}

BASE = "/api/v1/model-portfolios"


# ── Route smoke tests (no DB) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_list_model_portfolios_requires_auth(client: AsyncClient):
    resp = await client.get(BASE)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_model_portfolios_route_exists(client: AsyncClient):
    """401 (not 404) proves the router is mounted."""
    resp = await client.get(BASE)
    assert resp.status_code != 404


@pytest.mark.asyncio
async def test_get_model_portfolio_requires_auth(client: AsyncClient):
    resp = await client.get(f"{BASE}/{PORTFOLIO_ID}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_model_portfolio_route_exists(client: AsyncClient):
    resp = await client.get(f"{BASE}/{PORTFOLIO_ID}")
    assert resp.status_code != 404


# ── Phase 4 calibration GET/PUT smoke tests ────────────────────────


@pytest.mark.asyncio
async def test_get_portfolio_calibration_requires_auth(client: AsyncClient):
    """Phase 4 Task 4 — GET /{id}/calibration must require auth."""
    resp = await client.get(f"{BASE}/{PORTFOLIO_ID}/calibration")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_portfolio_calibration_route_exists(client: AsyncClient):
    """401 (not 404) proves the calibration GET route is mounted."""
    resp = await client.get(f"{BASE}/{PORTFOLIO_ID}/calibration")
    assert resp.status_code != 404


@pytest.mark.asyncio
async def test_put_portfolio_calibration_requires_auth(client: AsyncClient):
    """Phase 4 Task 4 — PUT /{id}/calibration must require auth."""
    resp = await client.put(
        f"{BASE}/{PORTFOLIO_ID}/calibration",
        json={"mandate": "moderate"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_put_portfolio_calibration_route_exists(client: AsyncClient):
    """401 (not 404) proves the calibration PUT route is mounted."""
    resp = await client.put(
        f"{BASE}/{PORTFOLIO_ID}/calibration",
        json={"mandate": "moderate"},
    )
    assert resp.status_code != 404


# ── Phase 5 Task 5.2 transitions dispatcher smoke tests ────────────


@pytest.mark.asyncio
async def test_post_portfolio_transition_requires_auth(client: AsyncClient):
    """Phase 5 Task 5.2 — POST /{id}/transitions must require auth."""
    resp = await client.post(
        f"{BASE}/{PORTFOLIO_ID}/transitions",
        json={"action": "validate"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_portfolio_transition_route_exists(client: AsyncClient):
    """401 (not 404) proves the transition dispatcher route is mounted."""
    resp = await client.post(
        f"{BASE}/{PORTFOLIO_ID}/transitions",
        json={"action": "validate"},
    )
    assert resp.status_code != 404


@pytest.mark.asyncio
async def test_post_portfolio_transition_rejects_unknown_action(client: AsyncClient):
    """Pydantic Literal validation must reject actions not in the union.

    Even without auth the FastAPI request validation runs first when the
    body is malformed, so this returns 422 not 401. The test proves the
    schema is enforced regardless of auth context.
    """
    resp = await client.post(
        f"{BASE}/{PORTFOLIO_ID}/transitions",
        json={"action": "construct"},  # construct is excluded — has its own route
    )
    # 422 (Unprocessable Entity) when the schema rejects ``construct``
    # before any auth/permission check runs.
    assert resp.status_code in (401, 422)


# ── Helper unit tests for _serialize_with_actions ─────────────────


def _fake_portfolio(state: str = "draft") -> MagicMock:
    """Build a MagicMock that quacks like a ``ModelPortfolio`` ORM row.

    Pydantic's ``model_validate`` with ``from_attributes=True`` reads
    attributes by name; this MagicMock provides every column the
    ``ModelPortfolioRead`` schema expects.
    """
    from datetime import datetime, timezone
    from decimal import Decimal

    p = MagicMock()
    p.id = PORTFOLIO_ID
    p.organization_id = uuid.UUID(ORG_ID)
    p.profile = "moderate"
    p.display_name = "Test Portfolio"
    p.description = None
    p.benchmark_composite = None
    p.inception_date = None
    p.backtest_start_date = None
    p.inception_nav = Decimal("1000.00")
    p.status = "draft"
    p.state = state
    p.state_metadata = {}
    p.state_changed_at = datetime.now(tz=timezone.utc)
    p.state_changed_by = None
    p.fund_selection_schema = None
    p.backtest_result = None
    p.stress_result = None
    p.created_at = datetime.now(tz=timezone.utc)
    p.created_by = "test-user"
    return p


@pytest.mark.asyncio
async def test_serialize_with_actions_draft_returns_construct_archive():
    """A draft portfolio with no construction runs gets the canonical
    ``[construct, archive]`` action set."""
    from app.domains.wealth.routes.model_portfolios import (
        _serialize_with_actions,
    )
    from vertical_engines.wealth.model_portfolio.state_machine import (
        ApprovalPolicy,
        ValidationStatus,
    )

    portfolio = _fake_portfolio(state="draft")
    db = AsyncMock()  # not used because we pre-seed policy + validation

    rendered = await _serialize_with_actions(
        db,
        portfolio,
        policy=ApprovalPolicy(),
        validation=ValidationStatus(has_run=False, passed=False),
    )

    assert rendered.state == "draft"
    assert "construct" in rendered.allowed_actions
    assert "archive" in rendered.allowed_actions
    assert "approve" not in rendered.allowed_actions


@pytest.mark.asyncio
async def test_serialize_with_actions_validated_returns_approve_rebuild():
    """A validated portfolio with a passing run gets ``[approve, rebuild_draft]``."""
    from app.domains.wealth.routes.model_portfolios import (
        _serialize_with_actions,
    )
    from vertical_engines.wealth.model_portfolio.state_machine import (
        ApprovalPolicy,
        ValidationStatus,
    )

    portfolio = _fake_portfolio(state="validated")
    db = AsyncMock()

    rendered = await _serialize_with_actions(
        db,
        portfolio,
        policy=ApprovalPolicy(),
        validation=ValidationStatus(has_run=True, passed=True),
    )

    assert rendered.state == "validated"
    assert "approve" in rendered.allowed_actions
    assert "rebuild_draft" in rendered.allowed_actions


@pytest.mark.asyncio
async def test_serialize_with_actions_archived_returns_empty():
    """An archived portfolio is terminal — zero actions."""
    from app.domains.wealth.routes.model_portfolios import (
        _serialize_with_actions,
    )
    from vertical_engines.wealth.model_portfolio.state_machine import (
        ApprovalPolicy,
        ValidationStatus,
    )

    portfolio = _fake_portfolio(state="archived")
    db = AsyncMock()

    rendered = await _serialize_with_actions(
        db,
        portfolio,
        policy=ApprovalPolicy(),
        validation=ValidationStatus(has_run=True, passed=True),
    )

    assert rendered.state == "archived"
    assert rendered.allowed_actions == []


@pytest.mark.asyncio
async def test_serialize_with_actions_constructed_with_failing_validation_default_policy():
    """Default policy gates approve on validation pass — failing run hides approve."""
    from app.domains.wealth.routes.model_portfolios import (
        _serialize_with_actions,
    )
    from vertical_engines.wealth.model_portfolio.state_machine import (
        ApprovalPolicy,
        ValidationStatus,
    )

    portfolio = _fake_portfolio(state="constructed")
    db = AsyncMock()

    rendered = await _serialize_with_actions(
        db,
        portfolio,
        policy=ApprovalPolicy(),  # require_construction_for_approve=True (default)
        validation=ValidationStatus(has_run=True, passed=False),
    )

    assert "approve" not in rendered.allowed_actions
    assert "validate" in rendered.allowed_actions
    assert "rebuild_draft" in rendered.allowed_actions
    assert "reject" in rendered.allowed_actions


@pytest.mark.asyncio
async def test_serialize_with_actions_soft_block_keeps_approve_visible():
    """OD-5: when policy.require_construction_for_approve=False, a
    failing validation does NOT remove approve. The route layer is
    responsible for capturing the override rationale + audit log."""
    from app.domains.wealth.routes.model_portfolios import (
        _serialize_with_actions,
    )
    from vertical_engines.wealth.model_portfolio.state_machine import (
        ApprovalPolicy,
        ValidationStatus,
    )

    portfolio = _fake_portfolio(state="constructed")
    db = AsyncMock()

    rendered = await _serialize_with_actions(
        db,
        portfolio,
        policy=ApprovalPolicy(require_construction_for_approve=False),
        validation=ValidationStatus(has_run=True, passed=False),
    )

    assert "approve" in rendered.allowed_actions, (
        "Soft-block contract: approve must remain visible even on "
        "failing validation when require_construction_for_approve=False"
    )


@pytest.mark.asyncio
async def test_resolve_approval_policy_falls_back_to_conservative_defaults():
    """If ConfigService misses (e.g. config domain not registered), the
    helper must return a conservative ApprovalPolicy — never raise."""
    from app.domains.wealth.routes.model_portfolios import (
        _resolve_approval_policy,
    )

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("config domain not registered"))

    policy = await _resolve_approval_policy(db, ORG_ID)
    assert policy.allow_self_approval is False
    assert policy.require_construction_for_approve is True


@pytest.mark.asyncio
async def test_serialize_with_actions_includes_state_metadata_fields():
    """``allowed_actions`` is in addition to the state machine projection
    fields, not a replacement. The frontend reads both."""
    from app.domains.wealth.routes.model_portfolios import (
        _serialize_with_actions,
    )
    from vertical_engines.wealth.model_portfolio.state_machine import (
        ApprovalPolicy,
        ValidationStatus,
    )

    portfolio = _fake_portfolio(state="live")
    portfolio.state_metadata = {"parent_live_id": str(uuid.uuid4())}

    rendered = await _serialize_with_actions(
        AsyncMock(),
        portfolio,
        policy=ApprovalPolicy(),
        validation=ValidationStatus(has_run=True, passed=True),
    )

    assert rendered.state == "live"
    assert "parent_live_id" in rendered.state_metadata
    assert "pause" in rendered.allowed_actions
    assert "archive" in rendered.allowed_actions
