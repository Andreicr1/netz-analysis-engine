"""PR-A26.2 Section F - per-instrument 15% cap feasibility check.

The gate fires in realize mode only, AFTER the approval gate. It
walks every canonical strategic_allocation row with target_weight >
15% and counts the block's approved instruments in instruments_org
via a single SQL aggregate. If ``n_b < ceil(target / 0.15)`` it
raises ``InstrumentConcentrationBreachError`` and the optimizer is
never invoked.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.wealth.workers.construction_run_executor import (
    InstrumentConcentrationBreachError,
    _check_instrument_concentration_feasibility,
)


def _db_returning(rows: list[tuple[str, float, int]]) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_block_weight_under_cap_always_passes() -> None:
    # 10% block with ONE approved instrument - feasible (one at 10% fits).
    db = _db_returning([("na_equity_large", 0.10, 1)])
    await _check_instrument_concentration_feasibility(
        db,
        organization_id=uuid.uuid4(),
        profile="moderate",
    )


@pytest.mark.asyncio
async def test_block_weight_30pct_with_two_instruments_feasible() -> None:
    # 30% target -> ceil(0.30 / 0.15) = 2 instruments required; 2 available.
    db = _db_returning([("na_equity_large", 0.30, 2)])
    await _check_instrument_concentration_feasibility(
        db,
        organization_id=uuid.uuid4(),
        profile="moderate",
    )


@pytest.mark.asyncio
async def test_block_weight_30pct_with_one_instrument_raises() -> None:
    db = _db_returning([("na_equity_large", 0.30, 1)])
    with pytest.raises(InstrumentConcentrationBreachError) as excinfo:
        await _check_instrument_concentration_feasibility(
            db,
            organization_id=uuid.uuid4(),
            profile="moderate",
        )
    assert excinfo.value.block_id == "na_equity_large"
    assert excinfo.value.required == 2
    assert excinfo.value.available == 1


@pytest.mark.asyncio
async def test_block_weight_15pct_edge_with_one_instrument_passes() -> None:
    # 15% exactly -> target_weight <= cap, no check fires.
    db = _db_returning([("cash", 0.15, 1)])
    await _check_instrument_concentration_feasibility(
        db,
        organization_id=uuid.uuid4(),
        profile="moderate",
    )


@pytest.mark.asyncio
async def test_block_weight_just_above_cap_with_one_instrument_raises() -> None:
    # 16% -> ceil(0.16/0.15) = 2 instruments required.
    db = _db_returning([("na_equity_large", 0.16, 1)])
    with pytest.raises(InstrumentConcentrationBreachError) as excinfo:
        await _check_instrument_concentration_feasibility(
            db,
            organization_id=uuid.uuid4(),
            profile="moderate",
        )
    assert excinfo.value.required == 2


@pytest.mark.asyncio
async def test_null_target_weight_passes() -> None:
    # Unapproved blocks (target_weight IS NULL) get coerced to 0.0 and pass.
    db = _db_returning([("em_equity", None, 0)])
    await _check_instrument_concentration_feasibility(
        db,
        organization_id=uuid.uuid4(),
        profile="moderate",
    )


@pytest.mark.asyncio
async def test_only_first_breach_reported() -> None:
    # Both blocks breach; the first one in the query result surfaces.
    db = _db_returning(
        [
            ("na_equity_large", 0.30, 1),
            ("fi_us_high_yield", 0.40, 1),
        ]
    )
    with pytest.raises(InstrumentConcentrationBreachError) as excinfo:
        await _check_instrument_concentration_feasibility(
            db,
            organization_id=uuid.uuid4(),
            profile="moderate",
        )
    assert excinfo.value.block_id == "na_equity_large"
