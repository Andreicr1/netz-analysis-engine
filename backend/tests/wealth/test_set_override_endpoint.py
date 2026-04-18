"""PR-A26.2 Section D - set-override endpoint + optimizer wiring.

Covers the override endpoint itself (request validation, canonical-
block membership, row update + RETURNING) and the schema-level guard
on ``override_min <= override_max``. The propose-mode optimizer
integration (``BlockConstraint`` carrying the override bounds) lives
in ``test_propose_mode_override.py``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.security.clerk_auth import Actor
from app.domains.wealth.routes.model_portfolios import set_override
from app.domains.wealth.schemas.model_portfolio import SetOverrideRequest


def _make_actor() -> Actor:
    from app.shared.enums import Role

    return Actor(
        actor_id="tester",
        name="Tester",
        email="tester@example.com",
        roles=[Role.INVESTMENT_TEAM],
        organization_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        fund_ids=[],
    )


def _make_user() -> Any:
    user = MagicMock()
    user.name = "tester"
    return user


def _make_db_for_override(
    *, block_canonical: bool | None, sa_row: dict | None,
) -> AsyncMock:
    """Stub AsyncSession for the set-override handler.

    Call sequence:
      1. ``execute(canonical_check).scalar_one_or_none()`` -> bool | None
      2. ``execute(update ... RETURNING).mappings().one_or_none()`` -> row
      3. ``flush()``
    """
    db = AsyncMock()

    canonical_result = MagicMock()
    canonical_result.scalar_one_or_none.return_value = block_canonical

    sa_result = MagicMock()
    mappings = MagicMock()
    mappings.one_or_none.return_value = sa_row
    sa_result.mappings.return_value = mappings

    calls = {"i": 0}

    async def _execute(stmt, params: dict | None = None):
        calls["i"] += 1
        if calls["i"] == 1:
            return canonical_result
        return sa_result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def test_schema_rejects_min_above_max() -> None:
    with pytest.raises(ValidationError):
        SetOverrideRequest(
            block_id="na_equity_large", override_min=0.30, override_max=0.10,
        )


def test_schema_accepts_single_sided_override() -> None:
    req = SetOverrideRequest(block_id="na_equity_large", override_max=0.15)
    assert req.override_min is None
    assert req.override_max == 0.15


@pytest.mark.asyncio
async def test_set_override_happy_path() -> None:
    now_ts = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
    sa_row = {
        "block_id": "na_equity_large",
        "target_weight": 0.05,
        "drift_min": 0.02,
        "drift_max": 0.08,
        "override_min": None,
        "override_max": 0.10,
        "approved_at": now_ts,
        "approved_by": "tester",
        "excluded_from_portfolio": False,
    }
    db = _make_db_for_override(block_canonical=True, sa_row=sa_row)

    resp = await set_override(
        profile="moderate",
        body=SetOverrideRequest(
            block_id="na_equity_large",
            override_max=0.10,
            rationale="cap equity concentration",
        ),
        db=db,
        user=_make_user(),
        actor=_make_actor(),
        org_id="00000000-0000-0000-0000-000000000001",
    )

    assert resp.block_id == "na_equity_large"
    assert resp.override_max == 0.10
    assert resp.override_min is None


@pytest.mark.asyncio
async def test_set_override_rejects_non_canonical_block() -> None:
    db = _make_db_for_override(block_canonical=False, sa_row=None)

    with pytest.raises(HTTPException) as excinfo:
        await set_override(
            profile="moderate",
            body=SetOverrideRequest(
                block_id="not_a_block", override_max=0.10,
            ),
            db=db,
            user=_make_user(),
            actor=_make_actor(),
            org_id="00000000-0000-0000-0000-000000000001",
        )
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_set_override_404_when_row_missing() -> None:
    db = _make_db_for_override(block_canonical=True, sa_row=None)

    with pytest.raises(HTTPException) as excinfo:
        await set_override(
            profile="moderate",
            body=SetOverrideRequest(
                block_id="na_equity_large", override_max=0.10,
            ),
            db=db,
            user=_make_user(),
            actor=_make_actor(),
            org_id="00000000-0000-0000-0000-000000000001",
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_set_override_clears_both_bounds() -> None:
    now_ts = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
    sa_row = {
        "block_id": "na_equity_large",
        "target_weight": 0.05,
        "drift_min": 0.02,
        "drift_max": 0.08,
        "override_min": None,
        "override_max": None,
        "approved_at": now_ts,
        "approved_by": "tester",
        "excluded_from_portfolio": False,
    }
    db = _make_db_for_override(block_canonical=True, sa_row=sa_row)

    resp = await set_override(
        profile="moderate",
        body=SetOverrideRequest(
            block_id="na_equity_large",
            override_min=None,
            override_max=None,
        ),
        db=db,
        user=_make_user(),
        actor=_make_actor(),
        org_id="00000000-0000-0000-0000-000000000001",
    )
    assert resp.override_min is None
    assert resp.override_max is None
