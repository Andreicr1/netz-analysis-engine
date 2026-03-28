"""Wealth embedding worker — vectorises Wealth sources into wealth_vector_chunks.

Sources:
  A. sec_manager_brochure_text → entity_type="firm", source_type="brochure"
  F. sec_managers + team/funds  → entity_type="firm", source_type="sec_manager_profile"
  G. sec_registered_funds + N-PORT → entity_type="fund", source_type="sec_fund_profile"
  H. sec_13f_holdings summary  → entity_type="firm", source_type="sec_13f_summary"
  I. sec_manager_funds grouped → entity_type="firm", source_type="sec_private_funds"
  J. esma_funds enriched       → entity_type="fund", source_type="esma_fund_profile"
  K. esma_managers enriched    → entity_type="firm", source_type="esma_manager_profile"
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

# Legacy source_types replaced by enriched profiles
_LEGACY_SOURCE_TYPES = ("esma_fund", "esma_manager")


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
            # One-time cleanup: remove legacy ESMA name-only chunks
            await _cleanup_legacy_source_types(db)

            stats: dict = {}
            for source_name, coro_fn in [
                ("brochure", _embed_brochure_sections),
                ("sec_manager_profile", _embed_sec_manager_profiles),
                ("sec_fund_profile", _embed_sec_fund_profiles),
                ("sec_13f_summary", _embed_sec_13f_summaries),
                ("sec_private_funds", _embed_sec_private_funds),
                ("esma_fund_profile", _embed_esma_fund_profiles),
                ("esma_manager_profile", _embed_esma_manager_profiles),
                ("dd_chapters", _embed_dd_chapters),
                ("macro_reviews", _embed_macro_reviews),
            ]:
                try:
                    stats[source_name] = await coro_fn(db)
                except Exception:
                    logger.exception("wealth_embedding.source_failed", source=source_name)
                    stats[source_name] = {"error": True}
                    await db.rollback()
            logger.info("wealth_embedding.complete", **stats)
            return {"status": "completed", **stats}
        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({WEALTH_EMBEDDING_LOCK_ID})"),
                )
            except Exception:
                pass


# ── Legacy cleanup ─────────────────────────────────────────────────


async def _cleanup_legacy_source_types(db: AsyncSession) -> None:
    """Remove old esma_fund / esma_manager chunks (replaced by enriched profiles).

    Also prunes sec_manager_profile chunks for managers without active funds
    (registered or private) — filters out pure RIAs, planners, etc.
    """
    result = await db.execute(
        text("""
            DELETE FROM wealth_vector_chunks
            WHERE source_type = ANY(:types)
        """),
        {"types": list(_LEGACY_SOURCE_TYPES)},
    )
    deleted = result.rowcount

    # Prune manager profiles for irrelevant managers (no funds)
    prune = await db.execute(text("""
        DELETE FROM wealth_vector_chunks w
        WHERE w.source_type = 'sec_manager_profile'
          AND NOT EXISTS (
              SELECT 1 FROM sec_managers m
              WHERE m.crd_number = w.entity_id
                AND (m.private_fund_count > 0
                     OR EXISTS (SELECT 1 FROM sec_registered_funds rf
                                WHERE rf.crd_number = m.crd_number))
          )
    """))
    pruned = prune.rowcount
    deleted += pruned

    if deleted:
        await db.commit()
        logger.info("wealth_embedding.legacy_cleanup", deleted_legacy=result.rowcount, pruned_profiles=pruned)


# ── Batch upsert helper ─────────────────────────────────────────────


async def _batch_upsert(db: AsyncSession, rows: list[dict]) -> None:
    """Upsert into wealth_vector_chunks with ON CONFLICT DO UPDATE."""
    # Deduplicate by id within the batch (last wins) to prevent
    # CardinalityViolationError from JOINs that multiply rows.
    seen: dict[str, int] = {}
    for idx, row in enumerate(rows):
        seen[row["id"]] = idx
    if len(seen) < len(rows):
        rows = [rows[i] for i in sorted(seen.values())]

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
            SELECT DISTINCT ON (b.crd_number, b.section)
                   b.crd_number, b.section, b.content, b.filing_date
            FROM sec_manager_brochure_text b
            LEFT JOIN wealth_vector_chunks w
              ON w.id = 'brochure_' || b.crd_number || '_' || b.section
            WHERE b.section = ANY(:sections)
              AND (w.id IS NULL
                   OR (b.filing_date IS NOT NULL
                       AND b.filing_date > w.embedded_at::date))
            ORDER BY b.crd_number, b.section, b.filing_date DESC NULLS LAST
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


# ── Source F: SEC Manager Profiles ───────────────────────────────────


def _format_aum(value: int | None) -> str:
    if not value:
        return "N/A"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    return f"${value:,.0f}"


def _format_json_summary(data: dict | list | None, max_items: int = 5) -> str:
    if not data:
        return "N/A"
    if isinstance(data, dict):
        items = [f"{k}: {v}" for k, v in list(data.items())[:max_items]]
    elif isinstance(data, list):
        items = [str(x) for x in data[:max_items]]
    else:
        return str(data)
    return ", ".join(items) if items else "N/A"


async def _embed_sec_manager_profiles(db: AsyncSession) -> dict:
    """Embed SEC manager profiles → entity_type='firm', source_type='sec_manager_profile'."""
    result = await db.execute(text("""
        SELECT m.crd_number, m.firm_name, m.registration_status,
               m.state, m.country, m.aum_total, m.aum_discretionary,
               m.total_accounts, m.fee_types, m.client_types,
               m.compliance_disclosures, m.last_adv_filed_at,
               m.private_fund_count, m.hedge_fund_count,
               m.pe_fund_count, m.vc_fund_count,
               m.real_estate_fund_count, m.other_fund_count,
               m.total_private_fund_assets,
               (SELECT COUNT(*) FROM sec_manager_team t WHERE t.crd_number = m.crd_number) AS team_count,
               (SELECT string_agg(
                   t2.person_name || COALESCE(' (' || t2.title || ')', ''),
                   ', ' ORDER BY t2.person_name
               )
               FROM (SELECT person_name, title FROM sec_manager_team
                     WHERE crd_number = m.crd_number LIMIT 3) t2
               ) AS top_team
        FROM sec_managers m
        LEFT JOIN wealth_vector_chunks w
          ON w.id = 'sec_manager_profile_' || m.crd_number
        WHERE m.firm_name IS NOT NULL
          AND (m.private_fund_count > 0
               OR EXISTS (SELECT 1 FROM sec_registered_funds rf
                          WHERE rf.crd_number = m.crd_number))
          AND (w.id IS NULL
               OR (m.last_adv_filed_at IS NOT NULL
                   AND m.last_adv_filed_at > w.embedded_at::date))
        ORDER BY m.crd_number
        LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        fund_parts = []
        if r.private_fund_count:
            fund_parts.append(f"{r.private_fund_count} private funds")
        if r.hedge_fund_count:
            fund_parts.append(f"{r.hedge_fund_count} hedge funds")
        if r.pe_fund_count:
            fund_parts.append(f"{r.pe_fund_count} PE funds")
        if r.vc_fund_count:
            fund_parts.append(f"{r.vc_fund_count} VC funds")
        if r.real_estate_fund_count:
            fund_parts.append(f"{r.real_estate_fund_count} real estate funds")
        if r.other_fund_count:
            fund_parts.append(f"{r.other_fund_count} other funds")
        fund_breakdown = ", ".join(fund_parts) if fund_parts else "None reported"

        location = ", ".join(filter(None, [r.state, r.country]))

        text_content = (
            f"{r.firm_name} (CRD {r.crd_number}) is a {r.registration_status or 'registered'} "
            f"investment adviser based in {location or 'unknown location'}. "
            f"Total AUM: {_format_aum(r.aum_total)} ({_format_aum(r.aum_discretionary)} discretionary). "
            f"Manages {r.total_accounts or 0} accounts.\n\n"
            f"Fund breakdown: {fund_breakdown}. "
            f"Total private fund assets: {_format_aum(r.total_private_fund_assets)}.\n\n"
            f"Investment team ({r.team_count} professionals)"
            f"{': ' + r.top_team if r.top_team else ''}.\n\n"
            f"Fee structures: {_format_json_summary(r.fee_types)}. "
            f"Client types: {_format_json_summary(r.client_types)}. "
            f"Last ADV filed: {r.last_adv_filed_at or 'N/A'}. "
            f"Compliance disclosures: {r.compliance_disclosures or 0}."
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"sec_manager_profile_{r.crd_number}",
            "organization_id": None,
            "entity_id": r.crd_number,
            "entity_type": "firm",
            "source_type": "sec_manager_profile",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.crd_number,
            "firm_crd": r.crd_number,
            "filing_date": r.last_adv_filed_at,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.sec_manager_profiles_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source G: SEC Registered Fund Profiles ───────────────────────────


async def _embed_sec_fund_profiles(db: AsyncSession) -> dict:
    """Embed SEC registered fund profiles → entity_type='fund', source_type='sec_fund_profile'."""
    result = await db.execute(text("""
        WITH latest_holdings AS (
            SELECT h.cik,
                   string_agg(
                       h.issuer_name || COALESCE(' (' || h.sector || ')', '') ||
                       ': ' || ROUND(h.pct_of_nav, 2) || '%%',
                       '; ' ORDER BY h.pct_of_nav DESC NULLS LAST
                   ) AS top_holdings,
                   string_agg(DISTINCT h.sector, ', ' ORDER BY h.sector) FILTER (WHERE h.sector IS NOT NULL) AS sectors,
                   MAX(h.report_date) AS report_date
            FROM (
                SELECT cik, issuer_name, sector, pct_of_nav, report_date,
                       ROW_NUMBER() OVER (PARTITION BY cik ORDER BY pct_of_nav DESC NULLS LAST) AS rn
                FROM sec_nport_holdings
                WHERE report_date = (SELECT MAX(report_date) FROM sec_nport_holdings sub WHERE sub.cik = sec_nport_holdings.cik)
            ) h
            WHERE h.rn <= 10
            GROUP BY h.cik
        ),
        fund_classes AS (
            SELECT cik,
                   string_agg(
                       COALESCE(class_name, series_name, 'Class') ||
                       COALESCE(' (' || ticker || ')', ''),
                       ', ' ORDER BY series_id, class_id
                   ) AS class_list
            FROM sec_fund_classes
            GROUP BY cik
        )
        SELECT f.cik, f.fund_name, f.fund_type, f.total_assets,
               f.inception_date, f.last_nport_date, f.crd_number,
               m.firm_name AS adviser_name,
               fc.class_list,
               lh.top_holdings, lh.sectors, lh.report_date AS holdings_date
        FROM sec_registered_funds f
        LEFT JOIN sec_managers m ON m.crd_number = f.crd_number
        LEFT JOIN fund_classes fc ON fc.cik = f.cik
        LEFT JOIN latest_holdings lh ON lh.cik = f.cik
        LEFT JOIN wealth_vector_chunks w ON w.id = 'sec_fund_profile_' || f.cik
        WHERE f.fund_name IS NOT NULL
          AND (w.id IS NULL
               OR (f.last_nport_date IS NOT NULL
                   AND f.last_nport_date > w.embedded_at::date))
        ORDER BY f.cik
        LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        adviser_part = f" managed by {r.adviser_name} (CRD {r.crd_number})" if r.adviser_name else ""
        classes_part = f"\nShare classes: {r.class_list}." if r.class_list else ""
        holdings_part = ""
        if r.top_holdings:
            holdings_part = (
                f"\n\nTop 10 holdings (as of {r.holdings_date}):\n{r.top_holdings}."
                f"\n\nSector allocation: {r.sectors or 'N/A'}."
            )

        text_content = (
            f"{r.fund_name} (CIK {r.cik}) is a {r.fund_type or 'registered fund'}"
            f"{adviser_part}. "
            f"Total assets: {_format_aum(r.total_assets)}. "
            f"Inception: {r.inception_date or 'N/A'}."
            f"{classes_part}"
            f"{holdings_part}"
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"sec_fund_profile_{r.cik}",
            "organization_id": None,
            "entity_id": r.cik,
            "entity_type": "fund",
            "source_type": "sec_fund_profile",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.cik,
            "firm_crd": r.crd_number,
            "filing_date": r.last_nport_date,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.sec_fund_profiles_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source H: SEC 13F Holdings Summaries ─────────────────────────────


async def _embed_sec_13f_summaries(db: AsyncSession) -> dict:
    """Embed 13F portfolio summaries → entity_type='firm', source_type='sec_13f_summary'."""
    result = await db.execute(text("""
        WITH latest_dates AS (
            SELECT cik, MAX(report_date) AS report_date
            FROM sec_13f_holdings
            GROUP BY cik
        ),
        holdings_agg AS (
            SELECT h.cik, h.report_date,
                   COUNT(*) AS position_count,
                   SUM(h.market_value) AS total_value,
                   string_agg(
                       h.issuer_name || ': $' || TRIM(TO_CHAR(h.market_value, '999,999,999,999')) ||
                       ' (' || ROUND(h.market_value * 100.0 / NULLIF(t.total_val, 0), 1) || '%%)',
                       '; ' ORDER BY h.market_value DESC NULLS LAST
                   ) FILTER (WHERE h.rn <= 20) AS top_holdings,
                   ROUND(SUM(h.market_value) FILTER (WHERE h.rn <= 5) * 100.0 / NULLIF(SUM(h.market_value), 0), 1) AS top5_pct,
                   ROUND(SUM(h.market_value) FILTER (WHERE h.rn <= 10) * 100.0 / NULLIF(SUM(h.market_value), 0), 1) AS top10_pct,
                   string_agg(DISTINCT
                       h.sector || ': ' ||
                       ROUND(s.sector_pct, 1) || '%%',
                       '; ' ORDER BY h.sector || ': ' || ROUND(s.sector_pct, 1) || '%%'
                   ) FILTER (WHERE h.sector IS NOT NULL) AS sector_breakdown
            FROM (
                SELECT cik, report_date, issuer_name, sector, market_value,
                       ROW_NUMBER() OVER (PARTITION BY cik ORDER BY market_value DESC NULLS LAST) AS rn
                FROM sec_13f_holdings
                JOIN latest_dates ld USING (cik, report_date)
            ) h
            JOIN (SELECT cik, SUM(market_value) AS total_val FROM sec_13f_holdings JOIN latest_dates USING (cik, report_date) GROUP BY cik) t USING (cik)
            LEFT JOIN LATERAL (
                SELECT h2.sector, SUM(h2.market_value) * 100.0 / NULLIF(t.total_val, 0) AS sector_pct
                FROM sec_13f_holdings h2
                JOIN latest_dates ld2 ON h2.cik = ld2.cik AND h2.report_date = ld2.report_date
                WHERE h2.cik = h.cik AND h2.sector = h.sector
                GROUP BY h2.sector
            ) s ON true
            GROUP BY h.cik, h.report_date
        )
        SELECT ha.cik, ha.report_date, ha.position_count, ha.total_value,
               ha.top_holdings, ha.top5_pct, ha.top10_pct, ha.sector_breakdown,
               m.firm_name, m.crd_number
        FROM holdings_agg ha
        LEFT JOIN sec_managers m ON m.cik = ha.cik
        LEFT JOIN wealth_vector_chunks w
          ON w.id = 'sec_13f_summary_' || ha.cik || '_' || ha.report_date::text
        WHERE w.id IS NULL
        ORDER BY ha.cik
        LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        firm_part = f" ({r.firm_name})" if r.firm_name else ""
        crd_part = f", CRD {r.crd_number}" if r.crd_number else ""

        text_content = (
            f"13F Portfolio of{firm_part} (CIK {r.cik}{crd_part}) as of {r.report_date}. "
            f"Total market value: {_format_aum(r.total_value)}. "
            f"Position count: {r.position_count}.\n\n"
            f"Top 20 holdings:\n{r.top_holdings or 'N/A'}.\n\n"
            f"Concentration: Top 5 = {r.top5_pct or 0}%, Top 10 = {r.top10_pct or 0}%.\n\n"
            f"Sector breakdown:\n{r.sector_breakdown or 'N/A'}."
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"sec_13f_summary_{r.cik}_{r.report_date}",
            "organization_id": None,
            "entity_id": r.cik,
            "entity_type": "firm",
            "source_type": "sec_13f_summary",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.cik,
            "firm_crd": r.crd_number,
            "filing_date": r.report_date,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.sec_13f_summaries_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source I: SEC Private Funds ──────────────────────────────────────


async def _embed_sec_private_funds(db: AsyncSession) -> dict:
    """Embed private fund portfolios → entity_type='firm', source_type='sec_private_funds'."""
    result = await db.execute(text("""
        WITH fund_agg AS (
            SELECT f.crd_number,
                   COUNT(*) AS fund_count,
                   SUM(f.gross_asset_value) AS total_gav,
                   COUNT(*) FILTER (WHERE f.is_fund_of_funds) AS fof_count,
                   string_agg(DISTINCT f.fund_type, ', ' ORDER BY f.fund_type) FILTER (WHERE f.fund_type IS NOT NULL) AS type_breakdown,
                   string_agg(
                       f.fund_name ||
                       COALESCE(' (' || f.fund_type || ')', '') ||
                       ': GAV ' || COALESCE('$' || TRIM(TO_CHAR(f.gross_asset_value, '999,999,999,999')), 'N/A') ||
                       ', ' || COALESCE(f.investor_count::text, '?') || ' investors',
                       '; ' ORDER BY f.gross_asset_value DESC NULLS LAST
                   ) AS fund_list
            FROM sec_manager_funds f
            GROUP BY f.crd_number
        )
        SELECT fa.crd_number, fa.fund_count, fa.total_gav, fa.fof_count,
               fa.type_breakdown, fa.fund_list,
               m.firm_name
        FROM fund_agg fa
        JOIN sec_managers m ON m.crd_number = fa.crd_number
        LEFT JOIN wealth_vector_chunks w
          ON w.id = 'sec_private_funds_' || fa.crd_number
        WHERE w.id IS NULL
        ORDER BY fa.crd_number
        LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        text_content = (
            f"Private fund portfolio of {r.firm_name} (CRD {r.crd_number}): "
            f"{r.fund_count} private funds, total GAV: {_format_aum(r.total_gav)}.\n\n"
            f"Funds:\n{r.fund_list or 'N/A'}.\n\n"
            f"Fund-of-funds: {r.fof_count}. Fund types: {r.type_breakdown or 'N/A'}."
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"sec_private_funds_{r.crd_number}",
            "organization_id": None,
            "entity_id": r.crd_number,
            "entity_type": "firm",
            "source_type": "sec_private_funds",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.crd_number,
            "firm_crd": r.crd_number,
            "filing_date": None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.sec_private_funds_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source J: ESMA Fund Profiles (replaces Source B) ─────────────────


async def _embed_esma_fund_profiles(db: AsyncSession) -> dict:
    """Embed enriched ESMA fund profiles → entity_type='fund', source_type='esma_fund_profile'."""
    result = await db.execute(text("""
        SELECT e.isin, e.fund_name, e.fund_type, e.domicile,
               e.host_member_states, e.yahoo_ticker,
               m.company_name AS manager_name, m.country AS manager_country
        FROM esma_funds e
        LEFT JOIN esma_managers m ON m.esma_id = e.esma_manager_id
        LEFT JOIN wealth_vector_chunks w ON w.id = 'esma_fund_profile_' || e.isin
        WHERE e.fund_name IS NOT NULL
          AND w.id IS NULL
        ORDER BY e.isin
        LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        manager_part = f" Managed by {r.manager_name}" if r.manager_name else ""
        if r.manager_country:
            manager_part += f" ({r.manager_country})"
        manager_part += "." if manager_part else ""

        host_states = ", ".join(r.host_member_states) if r.host_member_states else "N/A"
        ticker_part = r.yahoo_ticker or "not available"

        text_content = (
            f"{r.fund_name} (ISIN {r.isin}) is a {r.fund_type or 'UCITS'} fund "
            f"domiciled in {r.domicile or 'unknown'}."
            f"{manager_part} "
            f"Distributed in: {host_states}. "
            f"Yahoo ticker: {ticker_part}."
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"esma_fund_profile_{r.isin}",
            "organization_id": None,
            "entity_id": r.isin,
            "entity_type": "fund",
            "source_type": "esma_fund_profile",
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
    logger.info("wealth_embedding.esma_fund_profiles_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source K: ESMA Manager Profiles (replaces Source C) ──────────────


async def _embed_esma_manager_profiles(db: AsyncSession) -> dict:
    """Embed enriched ESMA manager profiles → entity_type='firm', source_type='esma_manager_profile'."""
    result = await db.execute(text("""
        SELECT e.esma_id, e.company_name, e.country,
               e.authorization_status, e.lei, e.sec_crd_number,
               (SELECT COUNT(*) FROM esma_funds f WHERE f.esma_manager_id = e.esma_id) AS actual_fund_count,
               (SELECT COUNT(DISTINCT f.domicile) FROM esma_funds f WHERE f.esma_manager_id = e.esma_id) AS domicile_count
        FROM esma_managers e
        LEFT JOIN wealth_vector_chunks w ON w.id = 'esma_manager_profile_' || e.esma_id
        WHERE e.company_name IS NOT NULL
          AND w.id IS NULL
        ORDER BY e.esma_id
        LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        lei_part = r.lei or "not available"
        crd_part = f" Cross-registered with US SEC as CRD {r.sec_crd_number}." if r.sec_crd_number else ""

        text_content = (
            f"{r.company_name} (ESMA ID {r.esma_id}) is a "
            f"{r.authorization_status or 'registered'} UCITS management company "
            f"based in {r.country or 'unknown'}. LEI: {lei_part}. "
            f"Manages {r.actual_fund_count} UCITS funds across {r.domicile_count} domiciles."
            f"{crd_part}"
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"esma_manager_profile_{r.esma_id}",
            "organization_id": None,
            "entity_id": r.esma_id,
            "entity_type": "firm",
            "source_type": "esma_manager_profile",
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
    logger.info("wealth_embedding.esma_manager_profiles_done", embedded=len(rows))
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
