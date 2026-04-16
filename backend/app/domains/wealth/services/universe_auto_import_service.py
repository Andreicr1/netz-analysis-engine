"""Universe auto-import service — bulk populate instruments_org from the
sanitized global catalog (``instruments_universe`` with ``is_institutional
= true``).

The service is the reusable core consumed by both:

* the nightly worker ``universe_auto_import`` (lock 900_103), and
* the admin endpoint ``POST /admin/universe/auto-import/run`` used for
  provisioning a brand-new org on demand.

Qualification cascade (all SQL, run once globally per invocation of the
worker, then applied to every org inside its own transaction):

1. ``instruments_universe`` base filter — ``is_active = true``,
   ``is_institutional = true``, ``instrument_type`` in the liquid set,
   ``attributes->>'fund_type'`` NOT private, and either no
   ``attributes->>'sec_universe'`` or one of the liquid universes.
2. AUM floor USD 200M — read from ``attributes->>'aum_usd'``.
3. Five-year NAV coverage — ``COUNT(nav_date) >= 1_260`` in
   ``nav_timeseries`` (the errata overrides the spec's
   ``fund_inception_date`` approach because that column is NULL on
   ``mv_unified_funds`` for every registered_us row).

Classification runs in Python against the canonical
``STRATEGY_LABEL_TO_BLOCKS`` map via :func:`classify_block` — the same
function covered by ``test_universe_auto_import_classifier.py``. The
SQL-table alternative proposed in the db-architect annex is intentionally
not built; the classifier is the single source of truth.

Idempotency contract (ON CONFLICT DO UPDATE):

* ``approval_status``: ``pending`` → ``approved``; any other value (e.g.
  ``rejected``) is preserved verbatim so IC decisions stick across runs.
* ``block_id``: overwritten unless ``block_overridden = true``.
* ``source``: ``manual`` → ``manual,auto`` so audit keeps both origins;
  ``manual,auto`` stays; anything else becomes ``universe_auto_import``
  on first write.
* ``selected_at``: monotonic (``GREATEST``) so the column tracks the
  most recent touch without losing the earlier manual selection.
"""

from __future__ import annotations

import time
from typing import Any, TypedDict
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.domains.wealth.services.universe_auto_import_classifier import (
    classify_block,
)

logger: Any = structlog.get_logger()

AUM_FLOOR_USD = 200_000_000
NAV_COVERAGE_MIN = 1_260  # ~5y trading days
STATEMENT_TIMEOUT_SECONDS = 120


class AutoImportMetrics(TypedDict):
    """Per-org result of an auto-import run."""

    org_id: str
    evaluated: int
    added: int
    updated: int
    skipped: int
    skipped_by_reason: dict[str, int]
    duration_ms: int


_QUALIFIED_QUERY = text(
    """
    WITH candidates AS (
        SELECT
            iu.instrument_id,
            iu.instrument_type,
            iu.asset_class,
            iu.name,
            iu.attributes
        FROM instruments_universe iu
        WHERE iu.is_active = TRUE
          AND iu.is_institutional = TRUE
          AND iu.asset_class IS NOT NULL
          AND iu.instrument_type IN (
              'fund', 'etf', 'mutual_fund',
              'closed_end_fund', 'interval_fund',
              'money_market', 'ucits'
          )
          AND (
              iu.attributes->>'fund_type' IS NULL
              OR iu.attributes->>'fund_type' NOT IN (
                  'Hedge Fund',
                  'Private Equity Fund',
                  'Venture Capital Fund',
                  'Securitized Asset Fund'
              )
          )
          AND (
              iu.attributes->>'sec_universe' IS NULL
              OR iu.attributes->>'sec_universe' IN (
                  'registered_us', 'etf', 'ucits_eu', 'money_market'
              )
          )
          AND COALESCE((iu.attributes->>'aum_usd')::numeric, 0)
              >= :aum_floor
    ),
    covered AS (
        SELECT c.instrument_id
        FROM candidates c
        JOIN nav_timeseries nt ON nt.instrument_id = c.instrument_id
        GROUP BY c.instrument_id
        HAVING COUNT(nt.nav_date) >= :coverage_min
    )
    SELECT
        c.instrument_id,
        c.instrument_type,
        c.asset_class,
        c.name,
        c.attributes
    FROM candidates c
    JOIN covered cov USING (instrument_id)
    """,
)


_UPSERT_QUERY = text(
    """
    INSERT INTO instruments_org (
        id, organization_id, instrument_id,
        block_id, approval_status, selected_at, source, block_overridden
    )
    VALUES (
        gen_random_uuid(), :org_id, :instrument_id,
        :block_id, 'approved', NOW(),
        'universe_auto_import', FALSE
    )
    ON CONFLICT (organization_id, instrument_id) DO UPDATE
    SET
        block_id = CASE
            WHEN instruments_org.block_overridden IS TRUE
                THEN instruments_org.block_id
            ELSE EXCLUDED.block_id
        END,
        approval_status = CASE
            WHEN instruments_org.approval_status = 'pending'
                THEN 'approved'
            ELSE instruments_org.approval_status
        END,
        selected_at = GREATEST(
            instruments_org.selected_at,
            EXCLUDED.selected_at
        ),
        source = CASE
            WHEN instruments_org.source = 'manual'      THEN 'manual,auto'
            WHEN instruments_org.source = 'manual,auto' THEN 'manual,auto'
            ELSE 'universe_auto_import'
        END
    WHERE instruments_org.approval_status IS DISTINCT FROM 'rejected'
    RETURNING (xmax = 0) AS inserted
    """,
)


async def fetch_qualified_instruments(db: AsyncSession) -> list[dict[str, Any]]:
    """Run the SQL qualification cascade once and return the rowset.

    The query reads only global tables (``instruments_universe`` and
    ``nav_timeseries`` — both no-RLS) so it's safe to call without an
    RLS context set. The worker prefetches once and reuses the result
    across every org; the admin endpoint calls it inline per request.

    Returned dicts mirror :func:`classify_block`'s expected shape.
    """
    result = await db.execute(
        _QUALIFIED_QUERY,
        {"aum_floor": AUM_FLOOR_USD, "coverage_min": NAV_COVERAGE_MIN},
    )
    rows: list[dict[str, Any]] = []
    for row in result.mappings().all():
        rows.append({
            "instrument_id": row["instrument_id"],
            "instrument_type": row["instrument_type"],
            "asset_class": row["asset_class"],
            "name": row["name"] or "",
            "attributes": row["attributes"] or {},
        })
    return rows


async def fetch_active_org_ids(db: AsyncSession) -> list[UUID]:
    """Return the distinct org_ids the worker should iterate.

    Sourced as a union of every tenant-scoped table that proves the org
    is real: existing selections in ``instruments_org`` (prior runs) and
    any tenant with a ``vertical_config_overrides`` entry (configured via
    seed). This avoids depending on a Clerk-managed ``organizations``
    table — there isn't one in this codebase.
    """
    result = await db.execute(
        text(
            """
            SELECT DISTINCT organization_id
            FROM (
                SELECT organization_id FROM instruments_org
                UNION
                SELECT organization_id FROM vertical_config_overrides
            ) t
            WHERE organization_id IS NOT NULL
            """,
        ),
    )
    return [row[0] for row in result.all()]


async def auto_import_for_org(
    db: AsyncSession,
    org_id: UUID,
    *,
    reason: str,
    actor_id: str = "worker:universe_auto_import",
    actor_roles: list[str] | None = None,
    request_id: str | None = None,
    qualified: list[dict[str, Any]] | None = None,
) -> AutoImportMetrics:
    """Auto-import the sanitized catalog into one org's instruments_org.

    The caller owns the session. On entry the session must already have
    ``app.current_organization_id`` set to ``org_id`` (RLS) — either via
    :func:`set_rls_context` (worker) or :func:`get_db_for_tenant`
    (endpoint). The function issues a ``SET LOCAL statement_timeout`` as
    a defensive guard against runaway UPSERTs.

    ``qualified`` lets the worker pre-fetch the global rowset once and
    reuse it across every org — it's identical per tenant because the
    catalog is global. When called ad-hoc (endpoint), pass ``None`` and
    the function fetches it inline.
    """
    started = time.monotonic()

    await db.execute(
        text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_SECONDS}s'"),
    )

    if qualified is None:
        qualified = await fetch_qualified_instruments(db)

    valid_blocks_result = await db.execute(
        text("SELECT block_id FROM allocation_blocks"),
    )
    valid_blocks = {row[0] for row in valid_blocks_result.all()}

    added = 0
    updated = 0
    skipped = 0
    skipped_by_reason: dict[str, int] = {}

    for inst in qualified:
        block_id, decision_reason = classify_block(inst, valid_blocks=valid_blocks)
        if block_id is None:
            skipped += 1
            skipped_by_reason[decision_reason] = (
                skipped_by_reason.get(decision_reason, 0) + 1
            )
            continue

        row = await db.execute(
            _UPSERT_QUERY,
            {
                "org_id": str(org_id),
                "instrument_id": str(inst["instrument_id"]),
                "block_id": block_id,
            },
        )
        ret = row.scalar_one_or_none()
        if ret is True:
            added += 1
        elif ret is False:
            updated += 1
        else:
            # Conflict hit the WHERE-clause on a rejected row: treat as
            # skipped with an explicit reason so the admin dashboard
            # surfaces how many IC rejections are being respected.
            skipped += 1
            skipped_by_reason["respected_reject"] = (
                skipped_by_reason.get("respected_reject", 0) + 1
            )

    elapsed_ms = int((time.monotonic() - started) * 1000)

    metrics: AutoImportMetrics = {
        "org_id": str(org_id),
        "evaluated": len(qualified),
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "skipped_by_reason": skipped_by_reason,
        "duration_ms": elapsed_ms,
    }

    await write_audit_event(
        db,
        actor_id=actor_id,
        actor_roles=actor_roles or ["system"],
        action="auto_import",
        entity_type="instruments_org",
        entity_id=str(org_id),
        after={**metrics, "reason": reason, "aum_floor_usd": AUM_FLOOR_USD,
               "nav_coverage_min": NAV_COVERAGE_MIN},
        request_id=request_id,
        organization_id=org_id,
    )

    logger.info(
        "universe_auto_import.org_complete",
        org_id=str(org_id),
        reason=reason,
        evaluated=metrics["evaluated"],
        added=metrics["added"],
        updated=metrics["updated"],
        skipped=metrics["skipped"],
        skipped_by_reason=metrics["skipped_by_reason"],
        duration_ms=metrics["duration_ms"],
    )

    return metrics
