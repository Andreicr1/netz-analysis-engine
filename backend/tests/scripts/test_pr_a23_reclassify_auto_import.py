"""Unit tests for the PR-A23 reclassify script ``_process_org``.

Exercises the per-org logic with a mock ``AsyncSession``. The DB itself
is not touched — we assert which UPDATE statements fire with which
parameters, which is enough to prove:

* VTEB-like rows (muni) surface for review → block_id updated to NULL
  on ``instruments_org`` AND ``needs_human_review`` flag set on
  ``instruments_universe``.
* Happy-path rows (correct strategy_label) are no-ops.
* Rows with ``block_overridden = TRUE`` are never updated.
* Dry-run suppresses all UPDATE calls.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _mock_row(scalar_value: Any = None, mapping: list | None = None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    result.all.return_value = mapping or []
    mappings_proxy = MagicMock()
    mappings_proxy.all.return_value = mapping or []
    result.mappings.return_value = mappings_proxy
    return result


def _build_db(
    select_rows: list[dict],
) -> tuple[AsyncMock, list[tuple[str, Any]]]:
    captured: list[tuple[str, Any]] = []

    async def _execute(stmt: Any, params: Any = None) -> MagicMock:
        sql = str(stmt)
        captured.append((sql, params))
        if "FROM instruments_org io" in sql and "WHERE io.organization_id" in sql:
            return _mock_row(mapping=select_rows)
        return _mock_row()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db, captured


def _row(
    *,
    ticker: str,
    current_block: str | None,
    strategy_label: str | None,
    asset_class: str = "fixed_income",
    name: str = "",
    block_overridden: bool = False,
) -> dict:
    return {
        "id": uuid.uuid4(),
        "instrument_id": uuid.uuid4(),
        "current_block_id": current_block,
        "block_overridden": block_overridden,
        "ticker": ticker,
        "instrument_type": "etf",
        "asset_class": asset_class,
        "investment_geography": "US",
        "name": name or ticker,
        "attributes": (
            {"strategy_label": strategy_label} if strategy_label else {}
        ),
    }


@pytest.mark.asyncio
async def test_vteb_like_row_flagged_and_set_null() -> None:
    """VTEB-style row (fixed_income, no strategy_label, no name signal)
    was living in fi_us_aggregate. After PR-A23 it reclassifies to None
    → block set NULL + universe flagged.
    """
    from scripts.pr_a23_reclassify_auto_import import _process_org

    row = _row(
        ticker="VTEB",
        current_block="fi_us_aggregate",
        strategy_label=None,
        name="Vanguard Tax-Exempt Bond",
    )
    db, captured = _build_db([row])

    summary = await _process_org(
        db,
        org_id=uuid.uuid4(),
        valid_blocks={"fi_us_aggregate", "fi_us_treasury"},
        dry_run=False,
    )

    assert summary["rows_updated"] == 1
    assert summary["rows_flagged_for_review"] == 1

    # Must have issued both updates.
    block_updates = [c for c in captured if "UPDATE instruments_org" in c[0]]
    flag_updates = [
        c for c in captured
        if "UPDATE instruments_universe" in c[0]
        and "needs_human_review" in c[0]
    ]
    assert len(block_updates) == 1
    assert block_updates[0][1]["block_id"] is None
    assert len(flag_updates) == 1


@pytest.mark.asyncio
async def test_happy_path_row_unchanged() -> None:
    """Row with correct strategy_label already in the matching block:
    no UPDATE should fire.
    """
    from scripts.pr_a23_reclassify_auto_import import _process_org

    row = _row(
        ticker="SPY",
        current_block="na_equity_large",
        strategy_label="Large Blend",
        asset_class="equity",
    )
    db, captured = _build_db([row])

    summary = await _process_org(
        db,
        org_id=uuid.uuid4(),
        valid_blocks={"na_equity_large"},
        dry_run=False,
    )

    assert summary["rows_updated"] == 0
    assert summary["rows_flagged_for_review"] == 0
    assert summary["rows_unchanged"] == 1

    block_updates = [c for c in captured if "UPDATE instruments_org" in c[0]]
    assert block_updates == []


@pytest.mark.asyncio
async def test_overridden_row_never_touched() -> None:
    """block_overridden=TRUE must short-circuit — the UPDATE on
    instruments_org must not fire even when the classifier returns a
    different block.
    """
    from scripts.pr_a23_reclassify_auto_import import _process_org

    row = _row(
        ticker="EFA",
        current_block="na_equity_large",
        strategy_label="Foreign Large Blend",
        asset_class="equity",
        block_overridden=True,
    )
    db, captured = _build_db([row])

    summary = await _process_org(
        db,
        org_id=uuid.uuid4(),
        valid_blocks={"na_equity_large", "dm_europe_equity"},
        dry_run=False,
    )

    assert summary["rows_override_skipped"] == 1
    block_updates = [c for c in captured if "UPDATE instruments_org" in c[0]]
    assert block_updates == []


@pytest.mark.asyncio
async def test_dry_run_suppresses_writes() -> None:
    from scripts.pr_a23_reclassify_auto_import import _process_org

    row = _row(
        ticker="VTEB",
        current_block="fi_us_aggregate",
        strategy_label=None,
    )
    db, captured = _build_db([row])

    summary = await _process_org(
        db,
        org_id=uuid.uuid4(),
        valid_blocks={"fi_us_aggregate"},
        dry_run=True,
    )

    # Counts reflect intended changes.
    assert summary["rows_updated"] == 1
    assert summary["rows_flagged_for_review"] == 1

    # But no UPDATE should actually fire.
    mutations = [
        c for c in captured
        if "UPDATE instruments_org" in c[0]
        or ("UPDATE instruments_universe" in c[0] and "needs_human_review" in c[0])
    ]
    assert mutations == []
