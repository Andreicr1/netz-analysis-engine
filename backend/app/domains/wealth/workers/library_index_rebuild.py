"""Wealth Library — nightly index self-heal worker.

Phase 1.2 of the Wealth Library sprint
(docs/superpowers/specs/2026-04-08-wealth-library.md §4.1 / §10).

The transactional triggers installed in migration 0092 keep
``wealth_library_index`` in sync with the three source tables
(``wealth_content``, ``dd_reports``, ``macro_reviews``) on every
INSERT/UPDATE/DELETE. This worker exists as a *defence in depth*
mechanism: if a trigger fails silently — typically because of a
PL/pgSQL exception swallowed by an outer transaction abort, or
because triggers were disabled during a migration — the index would
drift from the sources without any user-visible signal.

The self-heal procedure
=======================

Per source table:

1. Detect *missing* rows: source rows whose ``(source_table, id,
   organization_id)`` tuple has no counterpart in the index. Computed
   via SQL ``EXCEPT`` so PostgreSQL can hash-anti-join cleanly.
2. Detect *orphan* rows: index rows whose source_id no longer exists
   in the underlying source table.
3. If either delta > 0, emit a structured ``warning`` log line — this
   is the only signal we have that a trigger failed silently. Ops
   should investigate before the next run.
4. Re-sync the missing rows by re-executing the backfill INSERT from
   migration 0092 with ``ON CONFLICT (...) DO UPDATE`` semantics —
   safe to re-apply over already-correct rows because the upsert is
   idempotent. Scoped to the missing IDs to keep the cost bounded.
5. Delete the orphan rows from the index.

Lock 900_080 prevents concurrent runs across processes. The worker
operates without an RLS GUC because it must read every tenant.

Usage
-----

    python -m app.domains.wealth.workers.library_index_rebuild
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()

LIBRARY_INDEX_REBUILD_LOCK_ID = 900_080


# Source-table -> SQL to re-insert missing rows. Mirrors migration
# 0092 backfill exactly, restricted by `WHERE id = ANY(:missing_ids)`
# and using `ON CONFLICT DO UPDATE` so divergent fields are repaired.
_RESYNC_WEALTH_CONTENT = """
INSERT INTO wealth_library_index (
    organization_id, source_table, source_id,
    kind, title, subtitle,
    status, language, version, is_current,
    entity_kind, entity_id, entity_slug, entity_label,
    folder_path, author_id, approver_id,
    approved_at, created_at, updated_at,
    confidence_score, decision_anchor, storage_path, metadata
)
SELECT
    wc.organization_id,
    'wealth_content',
    wc.id,
    wc.content_type,
    wc.title,
    NULL,
    wc.status,
    wc.language,
    NULL,
    true,
    NULL, NULL, NULL, NULL,
    CASE
        WHEN lower(coalesce(wc.status, '')) IN
             ('draft','review','pending_approval','rejected','failed','generating') THEN
            ARRAY['Drafts & Pending'] ||
            CASE wc.content_type
                WHEN 'investment_outlook' THEN
                    ARRAY['Macro & Outlook', 'Investment Outlook',
                          to_char(wc.created_at, 'YYYY-"Q"Q')]
                WHEN 'flash_report' THEN
                    ARRAY['Macro & Outlook', 'Flash Reports',
                          to_char(wc.created_at, 'YYYY-MM')]
                WHEN 'manager_spotlight' THEN
                    ARRAY['Due Diligence', 'Manager Spotlights']
                ELSE
                    ARRAY['Other', wc.content_type]
            END
        ELSE
            CASE wc.content_type
                WHEN 'investment_outlook' THEN
                    ARRAY['Macro & Outlook', 'Investment Outlook',
                          to_char(wc.created_at, 'YYYY-"Q"Q')]
                WHEN 'flash_report' THEN
                    ARRAY['Macro & Outlook', 'Flash Reports',
                          to_char(wc.created_at, 'YYYY-MM')]
                WHEN 'manager_spotlight' THEN
                    ARRAY['Due Diligence', 'Manager Spotlights']
                ELSE
                    ARRAY['Other', wc.content_type]
            END
    END AS folder_path,
    wc.created_by,
    wc.approved_by,
    wc.approved_at,
    wc.created_at,
    wc.updated_at,
    NULL, NULL, wc.storage_path,
    jsonb_build_object('content_type', wc.content_type)
FROM wealth_content wc
WHERE wc.id = ANY(:missing_ids)
ON CONFLICT (source_table, source_id, organization_id) DO UPDATE SET
    kind         = EXCLUDED.kind,
    title        = EXCLUDED.title,
    status       = EXCLUDED.status,
    language     = EXCLUDED.language,
    folder_path  = EXCLUDED.folder_path,
    author_id    = EXCLUDED.author_id,
    approver_id  = EXCLUDED.approver_id,
    approved_at  = EXCLUDED.approved_at,
    updated_at   = EXCLUDED.updated_at,
    storage_path = EXCLUDED.storage_path,
    metadata     = EXCLUDED.metadata;
"""

_RESYNC_DD_REPORTS = """
INSERT INTO wealth_library_index (
    organization_id, source_table, source_id,
    kind, title, subtitle,
    status, language, version, is_current,
    entity_kind, entity_id, entity_slug, entity_label,
    folder_path, author_id, approver_id,
    approved_at, created_at, updated_at,
    confidence_score, decision_anchor, storage_path, metadata
)
SELECT
    dr.organization_id,
    'dd_reports',
    dr.id,
    coalesce(dr.report_type, 'dd_report'),
    CASE coalesce(dr.report_type, 'dd_report')
        WHEN 'bond_brief' THEN
            coalesce(iu.name, 'Unknown Instrument') || ' — Bond Brief'
        ELSE
            coalesce(iu.name, 'Unknown Instrument')
            || ' — DD Report v' || dr.version::text
    END,
    NULL,
    dr.status,
    dr.pdf_language,
    dr.version,
    dr.is_current,
    'instrument',
    dr.instrument_id,
    iu.slug,
    coalesce(iu.name, 'Unknown Instrument'),
    CASE
        WHEN lower(coalesce(dr.status, '')) IN
             ('draft','review','pending_approval','rejected','failed','generating') THEN
            ARRAY['Drafts & Pending'] ||
            CASE coalesce(dr.report_type, 'dd_report')
                WHEN 'bond_brief' THEN
                    ARRAY['Due Diligence', 'Bond Briefs',
                          coalesce(iu.name, 'Unknown Instrument')]
                ELSE
                    ARRAY['Due Diligence', 'By Fund',
                          coalesce(iu.name, 'Unknown Instrument'),
                          'v' || dr.version::text]
            END
        ELSE
            CASE coalesce(dr.report_type, 'dd_report')
                WHEN 'bond_brief' THEN
                    ARRAY['Due Diligence', 'Bond Briefs',
                          coalesce(iu.name, 'Unknown Instrument')]
                ELSE
                    ARRAY['Due Diligence', 'By Fund',
                          coalesce(iu.name, 'Unknown Instrument'),
                          'v' || dr.version::text]
            END
    END AS folder_path,
    dr.created_by,
    dr.approved_by,
    dr.approved_at,
    dr.created_at,
    coalesce(dr.approved_at, dr.created_at) AS updated_at,
    dr.confidence_score,
    dr.decision_anchor,
    dr.storage_path,
    jsonb_build_object(
        'report_type', dr.report_type,
        'schema_version', dr.schema_version,
        'rejection_reason', dr.rejection_reason
    )
FROM dd_reports dr
LEFT JOIN instruments_universe iu
       ON iu.instrument_id = dr.instrument_id
WHERE dr.id = ANY(:missing_ids)
ON CONFLICT (source_table, source_id, organization_id) DO UPDATE SET
    kind             = EXCLUDED.kind,
    title            = EXCLUDED.title,
    status           = EXCLUDED.status,
    language         = EXCLUDED.language,
    version          = EXCLUDED.version,
    is_current       = EXCLUDED.is_current,
    entity_slug      = EXCLUDED.entity_slug,
    entity_label     = EXCLUDED.entity_label,
    folder_path      = EXCLUDED.folder_path,
    approver_id      = EXCLUDED.approver_id,
    approved_at      = EXCLUDED.approved_at,
    updated_at       = EXCLUDED.updated_at,
    confidence_score = EXCLUDED.confidence_score,
    decision_anchor  = EXCLUDED.decision_anchor,
    storage_path     = EXCLUDED.storage_path,
    metadata         = EXCLUDED.metadata;
"""

_RESYNC_MACRO_REVIEWS = """
INSERT INTO wealth_library_index (
    organization_id, source_table, source_id,
    kind, title, subtitle,
    status, language, version, is_current,
    entity_kind, entity_id, entity_slug, entity_label,
    folder_path, author_id, approver_id,
    approved_at, created_at, updated_at,
    confidence_score, decision_anchor, storage_path, metadata
)
SELECT
    mr.organization_id,
    'macro_reviews',
    mr.id,
    'macro_review',
    to_char(mr.as_of_date, 'IYYY-"W"IW') || ' — Macro Committee Review',
    to_char(mr.as_of_date, 'IYYY-"W"IW'),
    mr.status,
    NULL,
    NULL,
    true,
    NULL, NULL, NULL, NULL,
    CASE
        WHEN lower(coalesce(mr.status, '')) IN
             ('draft','pending','review','pending_approval','rejected') THEN
            ARRAY['Drafts & Pending', 'Macro & Outlook',
                  'Weekly Macro Reviews',
                  to_char(mr.as_of_date, 'IYYY-"W"IW')]
        ELSE
            ARRAY['Macro & Outlook', 'Weekly Macro Reviews',
                  to_char(mr.as_of_date, 'IYYY-"W"IW')]
    END AS folder_path,
    mr.created_by,
    mr.approved_by,
    mr.approved_at,
    mr.created_at,
    mr.updated_at,
    NULL, NULL, NULL,
    jsonb_build_object(
        'as_of_date', mr.as_of_date,
        'is_emergency', mr.is_emergency,
        'snapshot_id', mr.snapshot_id,
        'decision_rationale', mr.decision_rationale
    )
FROM macro_reviews mr
WHERE mr.id = ANY(:missing_ids)
ON CONFLICT (source_table, source_id, organization_id) DO UPDATE SET
    title       = EXCLUDED.title,
    subtitle    = EXCLUDED.subtitle,
    status      = EXCLUDED.status,
    folder_path = EXCLUDED.folder_path,
    author_id   = EXCLUDED.author_id,
    approver_id = EXCLUDED.approver_id,
    approved_at = EXCLUDED.approved_at,
    updated_at  = EXCLUDED.updated_at,
    metadata    = EXCLUDED.metadata;
"""


_SOURCE_TABLES: tuple[tuple[str, str], ...] = (
    ("wealth_content", _RESYNC_WEALTH_CONTENT),
    ("dd_reports", _RESYNC_DD_REPORTS),
    ("macro_reviews", _RESYNC_MACRO_REVIEWS),
)


async def _detect_missing(db: AsyncSession, source_table: str) -> list[str]:
    """Return source-table IDs that are missing from the index."""
    result = await db.execute(
        text(
            f"""
            SELECT s.id
            FROM {source_table} s
            EXCEPT
            SELECT i.source_id
            FROM wealth_library_index i
            WHERE i.source_table = :source_table
            """,  # noqa: S608 — source_table comes from a hardcoded allowlist
        ),
        {"source_table": source_table},
    )
    return [row[0] for row in result.fetchall()]


async def _detect_orphans(db: AsyncSession, source_table: str) -> list[str]:
    """Return index source_ids that no longer exist in the source table."""
    result = await db.execute(
        text(
            f"""
            SELECT i.source_id
            FROM wealth_library_index i
            WHERE i.source_table = :source_table
            EXCEPT
            SELECT s.id
            FROM {source_table} s
            """,  # noqa: S608 — source_table comes from a hardcoded allowlist
        ),
        {"source_table": source_table},
    )
    return [row[0] for row in result.fetchall()]


async def run_library_index_rebuild() -> dict[str, Any]:
    """Detect and repair drift between source tables and the library index.

    Returns a per-source-table summary dict for observability.
    """
    log = logger.bind(worker="library_index_rebuild", lock_id=LIBRARY_INDEX_REBUILD_LOCK_ID)
    log.info("library_index_rebuild.started")
    summary: dict[str, Any] = {"status": "completed", "sources": {}}

    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({LIBRARY_INDEX_REBUILD_LOCK_ID})"),
        )
        acquired = bool(lock_result.scalar())
        if not acquired:
            log.info("library_index_rebuild.skipped", reason="advisory_lock_held")
            return {"status": "skipped"}

        try:
            for source_table, resync_sql in _SOURCE_TABLES:
                missing_ids = await _detect_missing(db, source_table)
                orphan_ids = await _detect_orphans(db, source_table)

                source_summary: dict[str, int] = {
                    "missing": len(missing_ids),
                    "orphans": len(orphan_ids),
                    "resynced": 0,
                    "deleted": 0,
                }

                if missing_ids or orphan_ids:
                    log.warning(
                        "library_index_rebuild.drift_detected",
                        source_table=source_table,
                        missing_count=len(missing_ids),
                        orphan_count=len(orphan_ids),
                    )

                if missing_ids:
                    resync_result = await db.execute(
                        text(resync_sql),
                        {"missing_ids": missing_ids},
                    )
                    source_summary["resynced"] = resync_result.rowcount or 0

                if orphan_ids:
                    delete_result = await db.execute(
                        text(
                            """
                            DELETE FROM wealth_library_index
                            WHERE source_table = :source_table
                              AND source_id = ANY(:orphan_ids)
                            """,
                        ),
                        {"source_table": source_table, "orphan_ids": orphan_ids},
                    )
                    source_summary["deleted"] = delete_result.rowcount or 0

                summary["sources"][source_table] = source_summary
                await db.commit()

            log.info("library_index_rebuild.completed", **summary)
            return summary
        except Exception:
            await db.rollback()
            log.exception("library_index_rebuild.failed")
            raise
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({LIBRARY_INDEX_REBUILD_LOCK_ID})"),
            )


if __name__ == "__main__":
    asyncio.run(run_library_index_rebuild())
