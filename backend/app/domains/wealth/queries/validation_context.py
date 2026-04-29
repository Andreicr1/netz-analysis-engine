"""Pre-fetch DB state for the construction validation gate.

PR-Q116 — Wave 6 S10 C-04.  The ``ValidationDbContext`` was previously
instantiated empty, which disabled 5 of the 16 hard checks (banned
instruments, approved universe, block min/max, TAA/IPS bands).

This module provides ``build_validation_db_context()`` which loads all
five fields from the org's DB state so the gate can actually enforce them.

PR-Q116 hotfix #2 — Codex P1: realize-mode bounds parity.  The ``mode``
parameter selects the same bounds hierarchy the optimizer used, so
validation and optimizer always agree on block limits.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vertical_engines.wealth.model_portfolio.block_bounds import (
    ModeType,
    resolve_block_bounds,
)
from vertical_engines.wealth.model_portfolio.validation_gate import (
    ValidationDbContext,
)


async def build_validation_db_context(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | str,
    profile: str,
    instrument_ids: list[str],
    mode: ModeType = "propose",
    as_of_date: date | None = None,
    effective_date: date | None = None,
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
        Construction run as-of date; used for the NAV staleness check.
    effective_date
        Allocation-window pin shared with the optimizer (the same value
        ``_run_construction_async`` used for ``effective_from <= today``).
        Defaults to ``date.today()`` when omitted, but callers in the
        executor MUST forward the optimizer's pinned date so a run that
        crosses midnight does not see two different allocation versions.
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

    # 3. Block constraints: strategic_allocation — resolve bounds via the
    #    shared helper that _build_propose_block_constraints also uses.
    #    PR-Q116 hotfix: previous COALESCE chain fell back to
    #    target_weight * 0.5/1.5 which was tighter than propose-mode's
    #    default [0, 1], causing false block failures.
    #    PR-Q116 hotfix #3 — Codex P1: filter to the active allocation
    #    version exactly like ``_run_construction_async`` does (see
    #    ``routes/model_portfolios.py``):
    #      ``effective_from <= today`` AND
    #      ``effective_to IS NULL OR effective_to > today``,
    #    then collapse duplicates to the latest ``effective_from`` per block.
    #    Without this filter, historical/future rows can overwrite the
    #    active one in undefined DB order, making validation enforce
    #    different bounds than the optimizer used.
    #    PR-Q116 hotfix #6 — Codex P2: prefer the caller-supplied
    #    ``effective_date`` so optimizer and validation share a single
    #    allocation snapshot even when the run straddles midnight.
    today = effective_date or date.today()
    block_rows = await db.execute(
        text(
            """
            SELECT DISTINCT ON (sa.block_id)
                   sa.block_id,
                   sa.override_min,
                   sa.override_max,
                   sa.drift_min,
                   sa.drift_max,
                   COALESCE(sa.excluded_from_portfolio, false) AS excluded,
                   COALESCE(sa.target_weight, 0.0) AS target_w
              FROM strategic_allocation sa
             WHERE sa.organization_id = :org
               AND sa.profile = :profile
               AND sa.effective_from <= :today
               AND (sa.effective_to IS NULL OR sa.effective_to > :today)
             ORDER BY sa.block_id, sa.effective_from DESC
            """
        ),
        {"org": org_str, "profile": profile, "today": today},
    )
    block_constraints: dict[str, tuple[float, float]] = {}
    strategic_targets: dict[str, float] = {}
    for (
        block_id, override_min, override_max,
        drift_min_val, drift_max_val, excluded, target_w,
    ) in block_rows.all():
        block_constraints[str(block_id)] = resolve_block_bounds(
            override_min=float(override_min) if override_min is not None else None,
            override_max=float(override_max) if override_max is not None else None,
            drift_min=float(drift_min_val) if drift_min_val is not None else None,
            drift_max=float(drift_max_val) if drift_max_val is not None else None,
            excluded_from_portfolio=bool(excluded),
            mode=mode,
        )
        strategic_targets[str(block_id)] = float(target_w or 0.0)

    # 4. NAV latest dates for staleness check (only for instruments in the run).
    #    PR-Q116 hotfix #5 — Codex P2: bound to ``as_of_date`` when supplied,
    #    so backdated runs are evaluated against the run date and not against
    #    forward-looking NAVs ingested afterwards (which would let
    #    ``no_stale_nav`` pass on data the optimizer never saw).
    nav_latest_date: dict[str, str] = {}
    if instrument_ids:
        nav_params: dict[str, object] = {
            "ids": [uuid.UUID(iid) for iid in instrument_ids],
        }
        as_of_clause = ""
        if as_of_date is not None:
            as_of_clause = " AND nav_date <= :as_of"
            nav_params["as_of"] = as_of_date
        nav_rows = await db.execute(
            text(
                f"""
                SELECT CAST(instrument_id AS TEXT),
                       CAST(MAX(nav_date) AS TEXT) AS latest_date
                  FROM nav_timeseries
                 WHERE instrument_id = ANY(:ids){as_of_clause}
                 GROUP BY instrument_id
                """
            ),
            nav_params,
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
