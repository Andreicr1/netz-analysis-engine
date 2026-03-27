"""Wealth embedding worker — vectorises Wealth sources into wealth_vector_chunks.

Sources:
  A. sec_manager_brochure_text → entity_type="firm", source_type="brochure"
  B. esma_funds                → entity_type="fund", source_type="esma_fund"
  C. esma_managers             → entity_type="firm", source_type="esma_manager"
  D. dd_chapters               → entity_type="fund", source_type="dd_chapter"
  E. macro_reviews             → entity_type="macro", source_type="macro_review"

Advisory lock: 900_041 (global)
Frequency: daily (cron 3h UTC)
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai_engine.extraction.embedding_service import async_generate_embeddings
from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.models.wealth_vector_chunk import WealthVectorChunk

logger = structlog.get_logger()

WEALTH_EMBEDDING_LOCK_ID = 900_041
EMBED_BATCH_SIZE = 100
UPSERT_BATCH_SIZE = 200

BROCHURE_EMBED_SECTIONS = frozenset({
    "investment_philosophy",
    "methods_of_analysis",
    "advisory_business",
    "risk_management",
    "performance_fees",
    "full_brochure",
})

BROCHURE_SECTION_LABELS = {
    "investment_philosophy": "Investment Philosophy",
    "methods_of_analysis": "Methods of Analysis",
    "advisory_business": "Advisory Business",
    "risk_management": "Risk Management",
    "performance_fees": "Performance Fees",
    "full_brochure": "ADV Part 2A Brochure",
}


# ── Entry point ──────────────────────────────────────────────────────


async def run_wealth_embedding() -> dict:
    """Main entry point — vectorise all Wealth sources."""
    async with async_session() as db:
        lock = await db.execute(
            text(f"SELECT pg_try_advisory_lock({WEALTH_EMBEDDING_LOCK_ID})"),
        )
        if not lock.scalar():
            logger.warning("wealth_embedding.lock_held")
            return {"status": "skipped", "reason": "lock_held"}
        try:
            stats: dict = {}
            stats["brochure"] = await _embed_brochure_sections(db)
            stats["esma_funds"] = await _embed_esma_funds(db)
            stats["esma_managers"] = await _embed_esma_managers(db)
            stats["dd_chapters"] = await _embed_dd_chapters(db)
            stats["macro_reviews"] = await _embed_macro_reviews(db)
            logger.info("wealth_embedding.complete", **stats)
            return {"status": "completed", **stats}
        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({WEALTH_EMBEDDING_LOCK_ID})"),
                )
            except Exception:
                pass


# ── Batch upsert helper ─────────────────────────────────────────────


async def _batch_upsert(db: AsyncSession, rows: list[dict]) -> None:
    """Upsert into wealth_vector_chunks with ON CONFLICT DO UPDATE."""
    for i in range(0, len(rows), UPSERT_BATCH_SIZE):
        chunk = rows[i : i + UPSERT_BATCH_SIZE]
        stmt = pg_insert(WealthVectorChunk.__table__).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "content": stmt.excluded.content,
                "embedding": stmt.excluded.embedding,
                "embedding_model": stmt.excluded.embedding_model,
                "embedded_at": stmt.excluded.embedded_at,
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
    await db.commit()


# ── Source A: ADV Brochures ──────────────────────────────────────────


async def _embed_brochure_sections(db: AsyncSession) -> dict:
    """Embed semantic sections of sec_manager_brochure_text → entity_type='firm'."""
    result = await db.execute(
        text("""
            SELECT b.crd_number, b.section, b.content, b.filing_date
            FROM sec_manager_brochure_text b
            LEFT JOIN wealth_vector_chunks w
              ON w.id = 'brochure_' || b.crd_number || '_' || b.section
            WHERE b.section = ANY(:sections)
              AND (w.id IS NULL
                   OR (b.filing_date IS NOT NULL
                       AND b.filing_date > w.embedded_at::date))
            ORDER BY b.crd_number
            LIMIT 10000
        """),
        {"sections": list(BROCHURE_EMBED_SECTIONS)},
    )

    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [
        f"[{BROCHURE_SECTION_LABELS.get(r.section, r.section)}] {r.content[:4000]}"
        for r in rows
    ]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"brochure_{r.crd_number}_{r.section}",
            "organization_id": None,
            "entity_id": r.crd_number,
            "entity_type": "firm",
            "source_type": "brochure",
            "section": r.section,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.crd_number,
            "firm_crd": r.crd_number,
            "filing_date": r.filing_date,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.brochure_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source B: ESMA Funds ─────────────────────────────────────────────


async def _embed_esma_funds(db: AsyncSession) -> dict:
    """Embed esma_funds → entity_type='fund' (direct analysis object)."""
    result = await db.execute(text("""
        SELECT e.isin, e.fund_name, e.fund_type, e.domicile, e.esma_manager_id
        FROM esma_funds e
        LEFT JOIN wealth_vector_chunks w ON w.id = 'esma_fund_' || e.isin
        WHERE e.fund_name IS NOT NULL
          AND w.id IS NULL
        ORDER BY e.isin
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [
        f"{r.fund_name} | {r.fund_type or 'UCITS'} | {r.domicile or ''}"
        for r in rows
    ]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"esma_fund_{r.isin}",
            "organization_id": None,
            "entity_id": r.isin,
            "entity_type": "fund",
            "source_type": "esma_fund",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.isin,
            "firm_crd": None,
            "filing_date": None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.esma_funds_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source C: ESMA Managers ──────────────────────────────────────────


async def _embed_esma_managers(db: AsyncSession) -> dict:
    """Embed esma_managers → entity_type='firm' (Management Company)."""
    result = await db.execute(text("""
        SELECT e.esma_id, e.company_name, e.country,
               e.authorization_status, e.sec_crd_number
        FROM esma_managers e
        LEFT JOIN wealth_vector_chunks w ON w.id = 'esma_manager_' || e.esma_id
        WHERE e.company_name IS NOT NULL
          AND w.id IS NULL
        ORDER BY e.esma_id
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [
        f"{r.company_name} | {r.country or ''} | {r.authorization_status or ''}"
        for r in rows
    ]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"esma_manager_{r.esma_id}",
            "organization_id": None,
            "entity_id": r.esma_id,
            "entity_type": "firm",
            "source_type": "esma_manager",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.esma_id,
            "firm_crd": r.sec_crd_number,
            "filing_date": None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.esma_managers_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source D: DD Chapters ────────────────────────────────────────────


async def _embed_dd_chapters(db: AsyncSession) -> dict:
    """Embed dd_chapters org-scoped → entity_type='fund'.

    entity_id = instrument_id from the parent dd_reports row (via dd_report_id FK).
    """
    result = await db.execute(text("""
        SELECT c.id AS chapter_id,
               r.instrument_id,
               r.organization_id,
               c.chapter_tag,
               c.content_md
        FROM dd_chapters c
        JOIN dd_reports r ON r.id = c.dd_report_id
                         AND r.organization_id = c.organization_id
        LEFT JOIN wealth_vector_chunks w ON w.id = 'dd_chapter_' || c.id::text
        WHERE c.content_md IS NOT NULL
          AND length(c.content_md) > 100
          AND w.id IS NULL
        ORDER BY c.id
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [r.content_md[:6000] for r in rows]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"dd_chapter_{r.chapter_id}",
            "organization_id": str(r.organization_id),
            "entity_id": str(r.instrument_id),
            "entity_type": "fund",
            "source_type": "dd_chapter",
            "section": r.chapter_tag,
            "content": texts[i],
            "language": "en",
            "source_row_id": str(r.chapter_id),
            "firm_crd": None,
            "filing_date": None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.dd_chapters_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source E: Macro Reviews ──────────────────────────────────────────


async def _embed_macro_reviews(db: AsyncSession) -> dict:
    """Embed macro_reviews org-scoped → entity_type='macro'.

    Embeds decision_rationale as the primary semantic chunk.
    """
    result = await db.execute(text("""
        SELECT id, organization_id, decision_rationale, created_at
        FROM macro_reviews
        WHERE decision_rationale IS NOT NULL
          AND length(decision_rationale) > 50
          AND NOT EXISTS (
              SELECT 1 FROM wealth_vector_chunks
              WHERE id = 'macro_review_' || macro_reviews.id::text || '_rationale'
          )
        ORDER BY id
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = [r.decision_rationale[:6000] for r in rows]
    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"macro_review_{r.id}_rationale",
            "organization_id": str(r.organization_id),
            "entity_id": str(r.id),
            "entity_type": "macro",
            "source_type": "macro_review",
            "section": "rationale",
            "content": texts[i],
            "language": "en",
            "source_row_id": str(r.id),
            "firm_crd": None,
            "filing_date": r.created_at.date() if r.created_at else None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.macro_reviews_done", embedded=len(rows))
    return {"embedded": len(rows)}
