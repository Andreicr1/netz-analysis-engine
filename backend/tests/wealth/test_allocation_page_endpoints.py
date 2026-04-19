"""PR-A26.3 Section A - strategic-allocation + approval-history endpoints.

Mirrors the AsyncMock pattern of ``test_approve_proposal_endpoint.py`` -
the handlers issue raw ``text()`` SQL and we stub ``AsyncSession`` so
the response shape is asserted without a live database. Live-DB smoke
will run via the Section I playwright flow.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.wealth.routes.model_portfolios import (
    get_approval_history,
    get_strategic_allocation,
)
from app.domains.wealth.utils.block_display import (
    BLOCK_DISPLAY_NAMES,
    CANONICAL_BLOCK_ORDER,
    humanize_block,
)


def _make_user() -> Any:
    user = MagicMock()
    user.name = "tester"
    return user


ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _mappings_result(rows: list[dict[str, Any]]) -> MagicMock:
    result = MagicMock()
    mappings = MagicMock()
    mappings.all.return_value = rows
    result.mappings.return_value = mappings
    return result


def _scalar_one_result(value: Any) -> MagicMock:
    result = MagicMock()
    result.scalar_one.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


# ── get_strategic_allocation ────────────────────────────────────────────


def _seed_rows(approved_n: int) -> list[dict[str, Any]]:
    """Seed ``approved_n`` approved rows + rest unapproved across the 18."""
    now = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
    rows: list[dict[str, Any]] = []
    for i, bid in enumerate(CANONICAL_BLOCK_ORDER):
        if i < approved_n:
            rows.append(
                {
                    "block_id": bid,
                    "target_weight": Decimal("0.05"),
                    "drift_min": Decimal("0.02"),
                    "drift_max": Decimal("0.08"),
                    "override_min": None,
                    "override_max": None,
                    "excluded_from_portfolio": False,
                    "approved_from_run_id": uuid.uuid4(),
                    "approved_at": now - timedelta(minutes=i),
                    "approved_by": "alice",
                }
            )
        else:
            rows.append(
                {
                    "block_id": bid,
                    "target_weight": None,
                    "drift_min": None,
                    "drift_max": None,
                    "override_min": None,
                    "override_max": None,
                    "excluded_from_portfolio": False,
                    "approved_from_run_id": None,
                    "approved_at": None,
                    "approved_by": None,
                }
            )
    return rows


def _db_for_strategic(
    rows: list[dict[str, Any]], *, cvar_from_calibration: float | None = 0.05,
) -> AsyncMock:
    db = AsyncMock()
    execute_calls = {"i": 0}

    async def _execute(stmt, params: dict | None = None):
        execute_calls["i"] += 1
        if execute_calls["i"] == 1:
            # SA rows fetch
            return _mappings_result(rows)
        # CVaR lookup via select(...) — scalar_one_or_none
        return _scalar_one_result(
            Decimal(str(cvar_from_calibration))
            if cvar_from_calibration is not None
            else None,
        )

    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.mark.asyncio
async def test_strategic_returns_18_rows_in_canonical_order() -> None:
    rows = _seed_rows(approved_n=0)
    db = _db_for_strategic(rows)

    resp = await get_strategic_allocation(
        profile="moderate", db=db, user=_make_user(), org_id=str(ORG_ID),
    )

    assert len(resp.blocks) == 18
    assert [b.block_id for b in resp.blocks] == list(CANONICAL_BLOCK_ORDER)
    assert resp.has_active_approval is False
    assert resp.last_approved_at is None
    assert resp.last_approved_by is None
    # Humanized names are populated
    assert resp.blocks[0].block_name == BLOCK_DISPLAY_NAMES["na_equity_large"]


@pytest.mark.asyncio
async def test_strategic_surfaces_last_approval_metadata() -> None:
    rows = _seed_rows(approved_n=5)
    db = _db_for_strategic(rows)

    resp = await get_strategic_allocation(
        profile="moderate", db=db, user=_make_user(), org_id=str(ORG_ID),
    )

    assert resp.has_active_approval is True
    assert resp.last_approved_by == "alice"
    assert resp.last_approved_at is not None
    approved = [b for b in resp.blocks if b.approved_at is not None]
    assert len(approved) == 5


@pytest.mark.asyncio
async def test_strategic_cvar_falls_back_to_profile_default() -> None:
    rows = _seed_rows(approved_n=0)
    db = _db_for_strategic(rows, cvar_from_calibration=None)

    resp = await get_strategic_allocation(
        profile="conservative", db=db, user=_make_user(), org_id=str(ORG_ID),
    )

    # Conservative default from default_cvar_limit_for_profile is non-zero.
    assert resp.cvar_limit > 0.0


@pytest.mark.asyncio
async def test_strategic_rejects_unknown_profile() -> None:
    db = _db_for_strategic(_seed_rows(approved_n=0))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        await get_strategic_allocation(
            profile="bogus", db=db, user=_make_user(), org_id=str(ORG_ID),
        )
    assert excinfo.value.status_code == 400


# ── get_approval_history ────────────────────────────────────────────────


def _db_for_history(entries: list[dict[str, Any]], total: int) -> AsyncMock:
    db = AsyncMock()
    execute_calls = {"i": 0}

    async def _execute(stmt, params: dict | None = None):
        execute_calls["i"] += 1
        if execute_calls["i"] == 1:
            return _scalar_one_result(total)
        return _mappings_result(entries)

    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.mark.asyncio
async def test_history_orders_newest_first_with_active_computed() -> None:
    now = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
    entries_raw = [
        {
            "id": uuid.uuid4(),
            "run_id": uuid.uuid4(),
            "approved_by": "alice",
            "approved_at": now,
            "superseded_at": None,
            "cvar_at_approval": Decimal("0.05"),
            "expected_return_at_approval": Decimal("0.08"),
            "cvar_feasible_at_approval": True,
            "operator_message": "Latest approval",
        },
        {
            "id": uuid.uuid4(),
            "run_id": uuid.uuid4(),
            "approved_by": "bob",
            "approved_at": now - timedelta(days=1),
            "superseded_at": now,
            "cvar_at_approval": Decimal("0.06"),
            "expected_return_at_approval": Decimal("0.075"),
            "cvar_feasible_at_approval": True,
            "operator_message": None,
        },
        {
            "id": uuid.uuid4(),
            "run_id": uuid.uuid4(),
            "approved_by": "carol",
            "approved_at": now - timedelta(days=7),
            "superseded_at": now - timedelta(days=1),
            "cvar_at_approval": None,
            "expected_return_at_approval": None,
            "cvar_feasible_at_approval": False,
            "operator_message": "older",
        },
    ]
    db = _db_for_history(entries_raw, total=3)

    resp = await get_approval_history(
        profile="moderate", db=db, user=_make_user(), org_id=str(ORG_ID),
    )

    assert resp.total == 3
    assert len(resp.entries) == 3
    assert resp.entries[0].is_active is True
    assert resp.entries[1].is_active is False
    assert resp.entries[2].is_active is False
    assert resp.entries[0].approved_by == "alice"
    assert resp.entries[2].cvar_at_approval is None
    assert resp.entries[2].cvar_feasible_at_approval is False


@pytest.mark.asyncio
async def test_history_pagination_limit_offset_passes_through() -> None:
    db = _db_for_history(entries=[], total=15)

    resp = await get_approval_history(
        profile="moderate",
        db=db,
        user=_make_user(),
        org_id=str(ORG_ID),
        limit=5,
        offset=10,
    )

    assert resp.total == 15
    assert resp.entries == []


# ── humanize helper ─────────────────────────────────────────────────────


def test_humanize_block_falls_back_for_unknown_id() -> None:
    assert humanize_block("na_equity_large") == "US Large-Cap Equity"
    assert humanize_block("unknown_block_x") == "Unknown Block X"
