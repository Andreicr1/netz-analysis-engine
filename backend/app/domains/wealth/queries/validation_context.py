"""Pre-fetch DB state for the construction validation gate.

PR-Q116 — Wave 6 S10 C-04.  The ``ValidationDbContext`` was previously
instantiated empty, which disabled 5 of the 16 hard checks (banned
instruments, approved universe, block min/max, TAA/IPS bands).

This module provides ``build_validation_db_context()`` which loads all
five fields from the org's DB state so the gate can actually enforce them.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vertical_engines.wealth.model_portfolio.validation_gate import (
    ValidationDbContext,
)


async def build_validation_db_context(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | str,
    profile: str,
    instrument_ids: list[str],
    as_of_date: date | None = None,
    nav_staleness_threshold_days: int = 10,
) -> ValidationDbContext:
    """Build a fully-populated ``ValidationDbContext`` from the DB.

    Parameters
    ----------
    db
        RLS-aware async session (organization context already set).
    organization_id
        Current org UUID.
    profile
        Portfolio profile (e.g. ``"conservative"``).
    instrument_ids
        List of instrument UUID strings from the optimizer output
        (the keys of ``weights_proposed``).
    as_of_date
        Construction run as-of date; used for staleness check.
    nav_staleness_threshold_days
        Days before a NAV observation is considered stale.

    Returns
    -------
    ValidationDbContext
        Frozen dataclass ready for ``validate_construction()``.
    """
    org_str = str(organization_id)

    # Run all independent queries in parallel via gather-like pattern.
    # Since we're on a single session, we run them sequentially but
    # each is a lightweight indexed lookup.

    # 1. Banned instruments: instruments_org with approval_status = 'rejected'
    banned_rows = await db.execute(
        text(
            """
            SELECT CAST(instrument_id AS TEXT)
              FROM instruments_org
             WHERE organization_id = :org
               AND approval_status = 'rejected'
            """
        ),
        {"org": org_str},
    )
    banned_instrument_ids = frozenset(row[0] for row in banned_rows.all())

    # 2. Approved instruments: instruments_org with approval_status = 'approved'
    approved_rows = await db.execute(
        text(
            """
            SELECT CAST(instrument_id AS TEXT)
              FROM instruments_org
             WHERE organization_id = :org
               AND approval_status = 'approved'
            """
        ),
        {"org": org_str},
    )
    approved_instrument_ids = frozenset(row[0] for row in approved_rows.all())

    # 3. Block constraints: strategic_allocation (min/max from drift bands,
    #    falling back to override bounds, then to ±5pp default around target).
    #    The optimizer-facing bounds were dropped in PR-A26.2 so we derive
    #    from the approved drift bands which the realize-mode loader uses.
    block_rows = await db.execute(
        text(
            """
            SELECT sa.block_id,
                   COALESCE(sa.drift_min, sa.override_min, sa.target_weight * 0.5) AS min_w,
                   COALESCE(sa.drift_max, sa.override_max,
                            LEAST(sa.target_weight * 1.5, 1.0)) AS max_w,
                   COALESCE(sa.target_weight, 0.0) AS target_w
              FROM strategic_allocation sa
             WHERE sa.organization_id = :org
               AND sa.profile = :profile
               AND COALESCE(sa.excluded_from_portfolio, false) = false
            """
        ),
        {"org": org_str, "profile": profile},
    )
    block_constraints: dict[str, tuple[float, float]] = {}
    strategic_targets: dict[str, float] = {}
    for block_id, min_w, max_w, target_w in block_rows.all():
        block_constraints[str(block_id)] = (
            float(min_w or 0.0),
            float(max_w or 1.0),
        )
        strategic_targets[str(block_id)] = float(target_w or 0.0)

    # 4. NAV latest dates for staleness check (only for instruments in the run)
    nav_latest_date: dict[str, str] = {}
    if instrument_ids:
        nav_rows = await db.execute(
            text(
                """
                SELECT CAST(instrument_id AS TEXT),
                       CAST(MAX(nav_date) AS TEXT) AS latest_date
                  FROM nav_timeseries
                 WHERE instrument_id = ANY(:ids)
                 GROUP BY instrument_id
                """
            ),
            {"ids": [uuid.UUID(iid) for iid in instrument_ids]},
        )
        for iid, latest in nav_rows.all():
            if latest is not None:
                nav_latest_date[str(iid)] = str(latest)

    return ValidationDbContext(
        banned_instrument_ids=banned_instrument_ids,
        approved_instrument_ids=approved_instrument_ids,
        strategic_targets=strategic_targets,
        block_constraints=block_constraints,
        nav_latest_date=nav_latest_date,
        nav_staleness_threshold_days=nav_staleness_threshold_days,
    )
