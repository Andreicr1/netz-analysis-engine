"""Wealth embedding worker — vectorises Wealth sources into wealth_vector_chunks.

Sources:
  A. sec_manager_brochure_text → entity_type="firm", source_type="brochure"
  F. sec_managers + team/funds  → entity_type="firm", source_type="sec_manager_profile"
  G. sec_registered_funds + N-CEN + XBRL → entity_type="fund", source_type="sec_fund_profile"
  O. sec_fund_classes per-series XBRL   → entity_type="fund", source_type="sec_fund_series_profile"
  H. sec_13f_holdings summary  → entity_type="firm", source_type="sec_13f_summary"
  I. sec_manager_funds grouped → entity_type="firm", source_type="sec_private_funds"
  J. esma_funds enriched       → entity_type="fund", source_type="esma_fund_profile"
  K. esma_managers enriched    → entity_type="firm", source_type="esma_manager_profile"
  L. sec_etfs + N-CEN          → entity_type="fund", source_type="sec_etf_profile"
  M. sec_bdcs                  → entity_type="fund", source_type="sec_bdc_profile"
  N. sec_money_market_funds    → entity_type="fund", source_type="sec_mmf_profile"
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
    "fees_compensation",
    "client_types",
    "disciplinary",
    "brokerage_practices",
    "full_brochure",
})

BROCHURE_SECTION_LABELS = {
    "investment_philosophy": "Investment Philosophy",
    "methods_of_analysis": "Methods of Analysis",
    "advisory_business": "Advisory Business",
    "risk_management": "Risk Management",
    "performance_fees": "Performance Fees",
    "fees_compensation": "Fees & Compensation",
    "client_types": "Types of Clients",
    "disciplinary": "Disciplinary Information",
    "brokerage_practices": "Brokerage Practices",
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
                ("sec_fund_series_profile", _embed_sec_fund_series_profiles),
                ("sec_13f_summary", _embed_sec_13f_summaries),
                ("sec_private_funds", _embed_sec_private_funds),
                ("esma_fund_profile", _embed_esma_fund_profiles),
                ("esma_manager_profile", _embed_esma_manager_profiles),
                ("sec_etf_profile", _embed_sec_etf_profiles),
                ("sec_bdc_profile", _embed_sec_bdc_profiles),
                ("sec_mmf_profile", _embed_sec_mmf_profiles),
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

    # Prune manager profiles for non-RIA managers
    prune = await db.execute(text("""
        DELETE FROM wealth_vector_chunks w
        WHERE w.source_type = 'sec_manager_profile'
          AND NOT EXISTS (
              SELECT 1 FROM sec_managers m
              WHERE m.crd_number = w.entity_id
                AND m.registration_status = 'Registered'
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
          AND m.registration_status = 'Registered'
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
    """Embed SEC registered fund profiles → entity_type='fund', source_type='sec_fund_profile'.

    Enriched with N-CEN data (LEI, AUM, flags) and XBRL fee data per share class.
    """
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
                       COALESCE(' (' || ticker || ')', '') ||
                       CASE WHEN expense_ratio_pct IS NOT NULL
                            THEN ' ER:' || ROUND(expense_ratio_pct * 100, 2) || '%%'
                            ELSE '' END ||
                       CASE WHEN net_assets IS NOT NULL
                            THEN ' AUM:$' || TRIM(TO_CHAR(net_assets / 1e9, '999,999.0')) || 'B'
                            ELSE '' END,
                       '; ' ORDER BY net_assets DESC NULLS LAST
                   ) AS class_list
            FROM sec_fund_classes
            GROUP BY cik
        )
        SELECT f.cik, f.fund_name, f.fund_type, f.strategy_label,
               f.total_assets, f.monthly_avg_net_assets,
               f.inception_date, f.last_nport_date, f.crd_number,
               f.lei, f.is_index, f.is_target_date, f.is_fund_of_fund,
               f.management_fee, f.net_operating_expenses,
               f.return_after_fees, f.return_before_fees,
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
        strategy_part = f" Strategy: {r.strategy_label}." if r.strategy_label else ""

        # AUM: prefer N-CEN monthly_avg_net_assets, fallback to total_assets
        aum = r.monthly_avg_net_assets or r.total_assets
        aum_str = _format_aum(aum)

        # Flags
        flags = []
        if r.is_index:
            flags.append("index fund")
        if r.is_target_date:
            flags.append("target-date")
        if r.is_fund_of_fund:
            flags.append("fund-of-funds")
        flags_part = f" ({', '.join(flags)})" if flags else ""

        # Fees
        fee_parts = []
        if r.management_fee:
            fee_parts.append(f"mgmt fee {float(r.management_fee):.2f}%")
        if r.net_operating_expenses:
            fee_parts.append(f"expense ratio {float(r.net_operating_expenses):.2f}%")
        fee_str = f" Fees: {', '.join(fee_parts)}." if fee_parts else ""

        # Performance
        perf_str = ""
        if r.return_after_fees is not None:
            perf_str = f" Annual return (after fees): {float(r.return_after_fees):.2f}%."

        classes_part = f"\nShare classes: {r.class_list}." if r.class_list else ""
        holdings_part = ""
        if r.top_holdings:
            holdings_part = (
                f"\n\nTop 10 holdings (as of {r.holdings_date}):\n{r.top_holdings}."
                f"\n\nSector allocation: {r.sectors or 'N/A'}."
            )

        text_content = (
            f"{r.fund_name} (CIK {r.cik}) is a {r.fund_type or 'registered fund'}{flags_part}"
            f"{adviser_part}.{strategy_part} "
            f"AUM: {aum_str}. Inception: {r.inception_date or 'N/A'}."
            f"{fee_str}{perf_str}"
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


# ── Source O: SEC Fund Series Profiles (per-series XBRL) ─────────────


async def _embed_sec_fund_series_profiles(db: AsyncSession) -> dict:
    """Embed per-series fund profiles from sec_fund_classes XBRL data.

    Source G embeds 1 chunk per CIK (Trust-level), which loses granularity
    for large trusts like Goldman Sachs Trust (660 share classes, 1 chunk).
    This source creates 1 chunk per series_id — the actual fund unit — with
    aggregated share class data (expense ratios, AUM, returns, tickers).
    """
    result = await db.execute(text("""
        WITH series_agg AS (
            SELECT fc.series_id,
                   fc.cik,
                   MAX(fc.series_name) AS series_name,
                   COUNT(*) AS class_count,
                   string_agg(
                       COALESCE(fc.class_name, 'Class') ||
                       COALESCE(' (' || fc.ticker || ')', '') ||
                       CASE WHEN fc.expense_ratio_pct IS NOT NULL
                            THEN ' ER:' || ROUND(fc.expense_ratio_pct * 100, 2) || '%%'
                            ELSE '' END ||
                       CASE WHEN fc.net_assets IS NOT NULL
                            THEN ' AUM:$' || TRIM(TO_CHAR(fc.net_assets / 1e6, '999,999,999')) || 'M'
                            ELSE '' END ||
                       CASE WHEN fc.avg_annual_return_pct IS NOT NULL
                            THEN ' Ret:' || ROUND(fc.avg_annual_return_pct * 100, 2) || '%%'
                            ELSE '' END,
                       '; ' ORDER BY fc.net_assets DESC NULLS LAST
                   ) AS class_details,
                   MIN(fc.expense_ratio_pct) FILTER (WHERE fc.expense_ratio_pct IS NOT NULL) AS min_er,
                   MAX(fc.expense_ratio_pct) FILTER (WHERE fc.expense_ratio_pct IS NOT NULL) AS max_er,
                   SUM(fc.net_assets) AS total_aum,
                   MAX(fc.holdings_count) AS holdings_count,
                   MAX(fc.portfolio_turnover_pct) AS turnover_pct,
                   MAX(fc.perf_inception_date) AS inception_date,
                   MAX(fc.advisory_fees_paid) AS advisory_fees
            FROM sec_fund_classes fc
            WHERE fc.series_id IS NOT NULL
            GROUP BY fc.series_id, fc.cik
        )
        SELECT sa.series_id, sa.cik, sa.series_name, sa.class_count,
               sa.class_details, sa.min_er, sa.max_er, sa.total_aum,
               sa.holdings_count, sa.turnover_pct, sa.inception_date,
               sa.advisory_fees,
               f.fund_type, f.strategy_label, f.crd_number,
               f.is_index, f.is_target_date, f.is_fund_of_fund,
               m.firm_name AS adviser_name
        FROM series_agg sa
        JOIN sec_registered_funds f ON f.cik = sa.cik
        LEFT JOIN sec_managers m ON m.crd_number = f.crd_number
        LEFT JOIN wealth_vector_chunks w
          ON w.id = 'sec_fund_series_' || sa.series_id
        WHERE sa.series_name IS NOT NULL
          AND w.id IS NULL
        ORDER BY sa.series_id
        LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        adviser_part = f" managed by {r.adviser_name}" if r.adviser_name else ""
        strategy_part = f" Strategy: {r.strategy_label}." if r.strategy_label else ""

        flags = []
        if r.is_index:
            flags.append("index fund")
        if r.is_target_date:
            flags.append("target-date")
        if r.is_fund_of_fund:
            flags.append("fund-of-funds")
        flags_part = f" ({', '.join(flags)})" if flags else ""

        # Expense ratio range
        er_part = ""
        if r.min_er is not None:
            if r.min_er == r.max_er:
                er_part = f" Expense ratio: {float(r.min_er) * 100:.2f}%."
            else:
                er_part = f" Expense ratio range: {float(r.min_er) * 100:.2f}%-{float(r.max_er) * 100:.2f}%."

        aum_str = _format_aum(r.total_aum)
        holdings_part = f" Holdings: {r.holdings_count}." if r.holdings_count else ""
        turnover_part = f" Turnover: {float(r.turnover_pct) * 100:.1f}%." if r.turnover_pct else ""
        fees_part = f" Advisory fees paid: ${r.advisory_fees:,.0f}." if r.advisory_fees else ""

        # Truncate class details for large series
        class_details = r.class_details or "N/A"
        if len(class_details) > 4000:
            class_details = class_details[:4000] + "..."

        text_content = (
            f"{r.series_name} (Series {r.series_id}, CIK {r.cik}) is a "
            f"{r.fund_type or 'registered fund'}{flags_part}{adviser_part}."
            f"{strategy_part} AUM: {aum_str}."
            f"{er_part}{holdings_part}{turnover_part}{fees_part}"
            f"\n\nShare classes ({r.class_count}): {class_details}."
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    upsert_rows = [
        {
            "id": f"sec_fund_series_{r.series_id}",
            "organization_id": None,
            "entity_id": r.series_id,
            "entity_type": "fund",
            "source_type": "sec_fund_series_profile",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.series_id,
            "firm_crd": r.crd_number,
            "filing_date": None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.sec_fund_series_profiles_done", embedded=len(rows))
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
    """Embed private fund portfolios → entity_type='firm', source_type='sec_private_funds'.

    AUM floor: only managers with combined GAV ≥ $1B are embedded.
    One chunk per (crd_number, strategy_label) to preserve vintage-level detail
    for large managers (e.g. Apollo 669 funds, Blackstone 400+).
    """
    result = await db.execute(text("""
        WITH eligible_managers AS (
            SELECT crd_number
            FROM sec_manager_funds
            GROUP BY crd_number
            HAVING SUM(gross_asset_value) >= 1000000000
        ),
        strategy_agg AS (
            SELECT f.crd_number,
                   COALESCE(f.strategy_label, 'Unclassified') AS strategy,
                   COUNT(*) AS fund_count,
                   SUM(f.gross_asset_value) AS strategy_gav,
                   COUNT(*) FILTER (WHERE f.is_fund_of_funds) AS fof_count,
                   string_agg(DISTINCT f.fund_type, ', ' ORDER BY f.fund_type)
                       FILTER (WHERE f.fund_type IS NOT NULL) AS type_breakdown,
                   string_agg(
                       f.fund_name ||
                       ': GAV ' || COALESCE('$' || TRIM(TO_CHAR(f.gross_asset_value, '999,999,999,999')), 'N/A') ||
                       ', ' || COALESCE(f.investor_count::text, '?') || ' investors',
                       '; ' ORDER BY f.gross_asset_value DESC NULLS LAST
                   ) AS fund_list
            FROM sec_manager_funds f
            JOIN eligible_managers em ON em.crd_number = f.crd_number
            GROUP BY f.crd_number, COALESCE(f.strategy_label, 'Unclassified')
        )
        SELECT sa.crd_number, sa.strategy, sa.fund_count, sa.strategy_gav,
               sa.fof_count, sa.type_breakdown, sa.fund_list,
               m.firm_name
        FROM strategy_agg sa
        JOIN sec_managers m ON m.crd_number = sa.crd_number
        LEFT JOIN wealth_vector_chunks w
          ON w.id = 'sec_private_funds_' || sa.crd_number || '_' ||
             replace(lower(sa.strategy), ' ', '_')
        WHERE w.id IS NULL
        ORDER BY sa.crd_number, sa.strategy
        LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        # Truncate fund list to ~6000 chars to stay within embedding token limit
        fund_list = r.fund_list or "N/A"
        if len(fund_list) > 6000:
            fund_list = fund_list[:6000] + "..."
        text_content = (
            f"{r.strategy} funds of {r.firm_name} (CRD {r.crd_number}): "
            f"{r.fund_count} funds, GAV: {_format_aum(r.strategy_gav)}.\n\n"
            f"Funds:\n{fund_list}.\n\n"
            f"Fund-of-funds: {r.fof_count}. "
            f"SEC types: {r.type_breakdown or 'N/A'}."
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    strategy_slug = lambda s: s.lower().replace(" ", "_").replace("/", "_")
    upsert_rows = [
        {
            "id": f"sec_private_funds_{r.crd_number}_{strategy_slug(r.strategy)}",
            "organization_id": None,
            "entity_id": r.crd_number,
            "entity_type": "firm",
            "source_type": "sec_private_funds",
            "section": r.strategy,
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
        SELECT e.isin, e.fund_name, e.fund_type, e.strategy_label, e.domicile,
               e.host_member_states, e.yahoo_ticker,
               m.company_name AS manager_name, m.country AS manager_country
        FROM esma_funds e
        LEFT JOIN esma_managers m ON m.esma_id = e.esma_manager_id
        LEFT JOIN wealth_vector_chunks w ON w.id = 'esma_fund_profile_' || e.isin
        WHERE e.fund_name IS NOT NULL
          AND w.id IS NULL
        ORDER BY e.isin
        LIMIT 15000
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

        strategy_part = f" Strategy: {r.strategy_label}." if r.strategy_label else ""

        text_content = (
            f"{r.fund_name} (ISIN {r.isin}) is a {r.fund_type or 'UCITS'} fund "
            f"domiciled in {r.domicile or 'unknown'}."
            f"{manager_part}{strategy_part} "
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
    """Embed ESMA manager profiles per-strategy → entity_type='firm', source_type='esma_manager_profile'.

    One chunk per (esma_id, strategy_label) to capture umbrella structure.
    Large ManCos like Amundi LU (427 funds, 29 strategies) get one chunk per
    strategy sleeve with sub-fund list, instead of a single generic chunk.

    Cross-registration with SEC resolved via name matching when sec_crd_number
    is not populated (CRD enrichment pending).
    """
    result = await db.execute(text("""
        WITH strategy_agg AS (
            SELECT f.esma_manager_id,
                   COALESCE(f.strategy_label, 'Unclassified') AS strategy,
                   COUNT(*) AS fund_count,
                   COUNT(DISTINCT f.domicile) AS domicile_count,
                   string_agg(DISTINCT f.domicile, ', ' ORDER BY f.domicile)
                       FILTER (WHERE f.domicile IS NOT NULL) AS domiciles,
                   COUNT(*) FILTER (WHERE f.yahoo_ticker IS NOT NULL) AS with_ticker,
                   string_agg(
                       f.fund_name ||
                       COALESCE(' (' || f.yahoo_ticker || ')', '') ||
                       COALESCE(' [' || f.domicile || ']', ''),
                       '; ' ORDER BY f.fund_name
                   ) AS fund_list
            FROM esma_funds f
            GROUP BY f.esma_manager_id, COALESCE(f.strategy_label, 'Unclassified')
        ),
        sec_crossref AS (
            SELECT DISTINCT ON (e2.esma_id)
                   e2.esma_id, s2.crd_number, s2.firm_name AS sec_name,
                   s2.aum_total, s2.private_fund_count
            FROM (
                SELECT esma_id,
                       lower(split_part(company_name, ' ', 1)) AS w1,
                       lower(split_part(company_name, ' ', 2)) AS w2
                FROM esma_managers
                WHERE sec_crd_number IS NULL
                  AND length(split_part(company_name, ' ', 1)) >= 4
                  AND split_part(company_name, ' ', 2) != ''
            ) e2
            JOIN (
                SELECT crd_number, firm_name, aum_total, private_fund_count,
                       lower(split_part(firm_name, ' ', 1)) AS w1,
                       lower(split_part(firm_name, ' ', 2)) AS w2
                FROM sec_managers
                WHERE registration_status = 'Registered'
                  AND aum_total > 1000000000
            ) s2 ON s2.w1 = e2.w1 AND s2.w2 = e2.w2
            ORDER BY e2.esma_id, s2.aum_total DESC NULLS LAST
        )
        SELECT sa.esma_manager_id, sa.strategy, sa.fund_count,
               sa.domicile_count, sa.domiciles, sa.with_ticker, sa.fund_list,
               m.company_name, m.country, m.authorization_status, m.lei,
               COALESCE(m.sec_crd_number, sc.crd_number) AS resolved_crd,
               sc.sec_name, sc.aum_total AS sec_aum, sc.private_fund_count AS sec_pf_count
        FROM strategy_agg sa
        JOIN esma_managers m ON m.esma_id = sa.esma_manager_id
        LEFT JOIN sec_crossref sc ON sc.esma_id = sa.esma_manager_id
        LEFT JOIN wealth_vector_chunks w
          ON w.id = 'esma_manager_' || sa.esma_manager_id || '_' ||
             replace(lower(sa.strategy), ' ', '_')
        WHERE m.company_name IS NOT NULL AND w.id IS NULL
        ORDER BY sa.esma_manager_id, sa.strategy
        LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        lei_part = f" LEI: {r.lei}." if r.lei else ""

        # SEC cross-registration
        sec_part = ""
        if r.resolved_crd:
            sec_part = f" Cross-registered with US SEC (CRD {r.resolved_crd}"
            if r.sec_name:
                sec_part += f", {r.sec_name}"
            if r.sec_aum:
                sec_part += f", AUM {_format_aum(r.sec_aum)}"
            if r.sec_pf_count:
                sec_part += f", {r.sec_pf_count} private funds"
            sec_part += ")."

        # Truncate fund list
        fund_list = r.fund_list or "N/A"
        if len(fund_list) > 5000:
            fund_list = fund_list[:5000] + "..."

        text_content = (
            f"{r.strategy} funds of {r.company_name} (ESMA {r.esma_manager_id}, "
            f"{r.country or 'unknown'}): "
            f"{r.fund_count} UCITS sub-funds across {r.domicile_count} domiciles "
            f"({r.domiciles or 'N/A'}). "
            f"{r.with_ticker} with market ticker.{lei_part}{sec_part}\n\n"
            f"Sub-funds:\n{fund_list}."
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)

    strategy_slug = lambda s: s.lower().replace(" ", "_").replace("/", "_")
    upsert_rows = [
        {
            "id": f"esma_manager_{r.esma_manager_id}_{strategy_slug(r.strategy)}",
            "organization_id": None,
            "entity_id": r.esma_manager_id,
            "entity_type": "firm",
            "source_type": "esma_manager_profile",
            "section": r.strategy,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.esma_manager_id,
            "firm_crd": r.resolved_crd,
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


# ── Source L: SEC ETF Profiles ──────────────────────────────────────


async def _embed_sec_etf_profiles(db: AsyncSession) -> dict:
    """Embed SEC ETFs → entity_type='fund', source_type='sec_etf_profile'.

    Enriched with N-CEN operational flags + XBRL fees from sec_fund_classes.
    """
    result = await db.execute(text("""
        WITH etf_xbrl AS (
            SELECT fc.series_id,
                   MIN(fc.expense_ratio_pct) AS min_er,
                   MAX(fc.expense_ratio_pct) AS max_er,
                   MAX(fc.net_assets) AS xbrl_aum,
                   MAX(fc.holdings_count) AS holdings_count,
                   MAX(fc.portfolio_turnover_pct) AS turnover_pct,
                   MAX(fc.avg_annual_return_pct) AS xbrl_return,
                   string_agg(
                       COALESCE(fc.class_name, 'Share') ||
                       COALESCE(' (' || fc.ticker || ')', '') ||
                       CASE WHEN fc.expense_ratio_pct IS NOT NULL
                            THEN ' ER:' || ROUND(fc.expense_ratio_pct * 100, 2) || '%%'
                            ELSE '' END ||
                       CASE WHEN fc.net_assets IS NOT NULL
                            THEN ' AUM:$' || TRIM(TO_CHAR(fc.net_assets / 1e6, '999,999,999')) || 'M'
                            ELSE '' END,
                       '; ' ORDER BY fc.net_assets DESC NULLS LAST
                   ) AS class_details
            FROM sec_fund_classes fc
            WHERE fc.series_id IN (SELECT series_id FROM sec_etfs)
            GROUP BY fc.series_id
        )
        SELECT e.series_id, e.fund_name, e.cik, e.ticker, e.strategy_label,
               e.asset_class, e.index_tracked, e.is_index, e.is_in_kind_etf,
               e.creation_unit_size, e.pct_in_kind_creation, e.pct_in_kind_redemption,
               e.management_fee, e.net_operating_expenses,
               e.tracking_difference_gross, e.tracking_difference_net,
               e.monthly_avg_net_assets, e.daily_avg_net_assets,
               e.nav_per_share, e.market_price_per_share,
               e.return_before_fees, e.return_after_fees,
               e.is_sec_lending_authorized, e.did_lend_securities,
               e.has_expense_limit, e.domicile, e.ncen_report_date,
               x.min_er, x.max_er, x.xbrl_aum, x.holdings_count,
               x.turnover_pct, x.xbrl_return, x.class_details
        FROM sec_etfs e
        LEFT JOIN etf_xbrl x ON x.series_id = e.series_id
        LEFT JOIN wealth_vector_chunks w ON w.id = 'sec_etf_profile_' || e.series_id
        WHERE e.fund_name IS NOT NULL AND w.id IS NULL
        ORDER BY e.series_id LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        ticker_part = f" ({r.ticker})" if r.ticker else ""
        strategy = f" Strategy: {r.strategy_label}." if r.strategy_label else ""
        index_part = f" Tracks: {r.index_tracked}." if r.index_tracked else (" Index fund." if r.is_index else "")

        # AUM: prefer XBRL, fallback to N-CEN monthly avg
        aum = r.xbrl_aum or r.monthly_avg_net_assets
        aum_str = _format_aum(aum)

        # Fees: combine N-CEN + XBRL
        fee_parts = []
        if r.management_fee:
            fee_parts.append(f"mgmt fee {float(r.management_fee):.2f}%")
        if r.net_operating_expenses:
            fee_parts.append(f"net ER {float(r.net_operating_expenses):.2f}%")
        elif r.min_er is not None:
            if r.min_er == r.max_er:
                fee_parts.append(f"ER {float(r.min_er) * 100:.2f}%")
            else:
                fee_parts.append(f"ER {float(r.min_er) * 100:.2f}%-{float(r.max_er) * 100:.2f}%")
        if r.has_expense_limit:
            fee_parts.append("expense cap in place")
        fee_str = f" Fees: {', '.join(fee_parts)}." if fee_parts else ""

        # Tracking
        td_parts = []
        if r.tracking_difference_net is not None:
            td_parts.append(f"net {float(r.tracking_difference_net):.2f}%")
        if r.tracking_difference_gross is not None:
            td_parts.append(f"gross {float(r.tracking_difference_gross):.2f}%")
        td_str = f" Tracking difference: {', '.join(td_parts)}." if td_parts else ""

        # NAV & market price
        nav_parts = []
        if r.nav_per_share is not None:
            nav_parts.append(f"NAV ${float(r.nav_per_share):.2f}")
        if r.market_price_per_share is not None:
            nav_parts.append(f"market ${float(r.market_price_per_share):.2f}")
            if r.nav_per_share is not None and r.nav_per_share > 0:
                premium = (float(r.market_price_per_share) / float(r.nav_per_share) - 1) * 100
                nav_parts.append(f"{'premium' if premium > 0 else 'discount'} {abs(premium):.2f}%")
        nav_str = f" Price: {', '.join(nav_parts)}." if nav_parts else ""

        # Performance
        perf_parts = []
        ret = r.return_after_fees if r.return_after_fees is not None else r.xbrl_return
        if ret is not None:
            perf_parts.append(f"after fees {float(ret):.2f}%")
        if r.return_before_fees is not None:
            perf_parts.append(f"before fees {float(r.return_before_fees):.2f}%")
        perf_str = f" Return: {', '.join(perf_parts)}." if perf_parts else ""

        # ETF mechanics
        mech_parts = []
        if r.is_in_kind_etf:
            mech_parts.append("in-kind ETF")
        if r.creation_unit_size:
            mech_parts.append(f"creation unit {r.creation_unit_size:,} shares")
        if r.is_sec_lending_authorized:
            lend = "lent securities" if r.did_lend_securities else "authorized (not lent)"
            mech_parts.append(f"sec lending {lend}")
        mech_str = f" Mechanics: {', '.join(mech_parts)}." if mech_parts else ""

        # Holdings & turnover from XBRL
        hold_str = f" Holdings: {r.holdings_count}." if r.holdings_count else ""
        turn_str = f" Turnover: {float(r.turnover_pct) * 100:.1f}%." if r.turnover_pct else ""

        # Share classes from XBRL
        class_str = ""
        if r.class_details:
            cd = r.class_details
            if len(cd) > 2000:
                cd = cd[:2000] + "..."
            class_str = f"\nShare classes: {cd}."

        text_content = (
            f"{r.fund_name}{ticker_part} (Series {r.series_id}) is a US-listed ETF."
            f"{strategy}{index_part} AUM: {aum_str}."
            f"{fee_str}{td_str}{nav_str}{perf_str}{mech_str}{hold_str}{turn_str}"
            f"{class_str}"
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)
    upsert_rows = [
        {
            "id": f"sec_etf_profile_{r.series_id}",
            "organization_id": None,
            "entity_id": r.series_id,
            "entity_type": "fund",
            "source_type": "sec_etf_profile",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.series_id,
            "firm_crd": None,
            "filing_date": r.ncen_report_date,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.sec_etf_profiles_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source M: SEC BDC Profiles ─────────────────────────────────────


async def _embed_sec_bdc_profiles(db: AsyncSession) -> dict:
    """Embed SEC BDCs → entity_type='fund', source_type='sec_bdc_profile'.

    Enriched with full N-CEN operational data + XBRL fees from sec_fund_classes.
    """
    result = await db.execute(text("""
        WITH bdc_xbrl AS (
            SELECT fc.series_id,
                   MIN(fc.expense_ratio_pct) AS min_er,
                   MAX(fc.expense_ratio_pct) AS max_er,
                   MAX(fc.net_assets) AS xbrl_aum,
                   MAX(fc.holdings_count) AS holdings_count,
                   MAX(fc.portfolio_turnover_pct) AS turnover_pct,
                   MAX(fc.avg_annual_return_pct) AS xbrl_return
            FROM sec_fund_classes fc
            WHERE fc.series_id IN (SELECT series_id FROM sec_bdcs)
            GROUP BY fc.series_id
        )
        SELECT b.series_id, b.fund_name, b.cik, b.ticker, b.strategy_label,
               b.investment_focus, b.management_fee, b.net_operating_expenses,
               b.return_before_fees, b.return_after_fees,
               b.monthly_avg_net_assets, b.daily_avg_net_assets,
               b.nav_per_share, b.market_price_per_share,
               b.is_externally_managed, b.is_sec_lending_authorized,
               b.has_line_of_credit, b.has_interfund_borrowing,
               b.ncen_report_date, b.inception_date,
               x.min_er, x.max_er, x.xbrl_aum, x.holdings_count,
               x.turnover_pct, x.xbrl_return
        FROM sec_bdcs b
        LEFT JOIN bdc_xbrl x ON x.series_id = b.series_id
        LEFT JOIN wealth_vector_chunks w ON w.id = 'sec_bdc_profile_' || b.series_id
        WHERE b.fund_name IS NOT NULL AND w.id IS NULL
        ORDER BY b.series_id LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        strategy = r.strategy_label or "Private Credit"
        focus = f" Focus: {r.investment_focus}." if r.investment_focus else ""
        ticker_part = f" ({r.ticker})" if r.ticker else ""
        aum = r.xbrl_aum or r.monthly_avg_net_assets
        aum_str = _format_aum(aum)

        # Fees
        fee_parts = []
        if r.management_fee:
            fee_parts.append(f"mgmt fee {float(r.management_fee):.2f}%")
        if r.net_operating_expenses:
            fee_parts.append(f"net ER {float(r.net_operating_expenses):.2f}%")
        elif r.min_er is not None:
            fee_parts.append(f"XBRL ER {float(r.min_er) * 100:.2f}%")
        fee_str = f" Fees: {', '.join(fee_parts)}." if fee_parts else ""

        # NAV discount/premium
        discount = ""
        if r.nav_per_share and r.market_price_per_share:
            disc_pct = (float(r.market_price_per_share) / float(r.nav_per_share) - 1) * 100
            label = "premium" if disc_pct > 0 else "discount"
            discount = (
                f" NAV ${float(r.nav_per_share):.2f}, "
                f"market ${float(r.market_price_per_share):.2f} "
                f"({label} {abs(disc_pct):.1f}%)."
            )

        # Performance
        perf_parts = []
        ret = r.return_after_fees if r.return_after_fees is not None else r.xbrl_return
        if ret is not None:
            perf_parts.append(f"after fees {float(ret):.2f}%")
        if r.return_before_fees is not None:
            perf_parts.append(f"before fees {float(r.return_before_fees):.2f}%")
        perf_str = f" Return: {', '.join(perf_parts)}." if perf_parts else ""

        # Operational flags
        ops = []
        if r.is_externally_managed:
            ops.append("externally managed")
        if r.is_sec_lending_authorized:
            ops.append("sec lending authorized")
        if r.has_line_of_credit:
            ops.append("has line of credit")
        if r.has_interfund_borrowing:
            ops.append("interfund borrowing")
        ops_str = f" Operations: {', '.join(ops)}." if ops else ""

        # Holdings & turnover
        hold_str = f" Holdings: {r.holdings_count}." if r.holdings_count else ""
        turn_str = f" Turnover: {float(r.turnover_pct) * 100:.1f}%." if r.turnover_pct else ""
        incept = f" Inception: {r.inception_date}." if r.inception_date else ""

        text_content = (
            f"{r.fund_name}{ticker_part} (Series {r.series_id}, CIK {r.cik}) "
            f"is a Business Development Company (BDC). "
            f"Strategy: {strategy}.{focus} AUM: {aum_str}.{incept}"
            f"{fee_str}{discount}{perf_str}{ops_str}{hold_str}{turn_str}"
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)
    upsert_rows = [
        {
            "id": f"sec_bdc_profile_{r.series_id}",
            "organization_id": None,
            "entity_id": r.series_id,
            "entity_type": "fund",
            "source_type": "sec_bdc_profile",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.series_id,
            "firm_crd": None,
            "filing_date": r.ncen_report_date,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.sec_bdc_profiles_done", embedded=len(rows))
    return {"embedded": len(rows)}


# ── Source N: SEC Money Market Fund Profiles ───────────────────────


async def _embed_sec_mmf_profiles(db: AsyncSession) -> dict:
    """Embed SEC MMFs → entity_type='fund', source_type='sec_mmf_profile'."""
    result = await db.execute(text("""
        SELECT m.series_id, m.fund_name, m.cik, m.mmf_category, m.strategy_label,
               m.is_govt_fund, m.is_retail,
               m.weighted_avg_maturity, m.weighted_avg_life,
               m.seven_day_gross_yield, m.net_assets,
               m.pct_daily_liquid_latest, m.pct_weekly_liquid_latest,
               m.seeks_stable_nav, m.investment_adviser
        FROM sec_money_market_funds m
        LEFT JOIN wealth_vector_chunks w ON w.id = 'sec_mmf_profile_' || m.series_id
        WHERE m.fund_name IS NOT NULL AND w.id IS NULL
        ORDER BY m.series_id LIMIT 10000
    """))
    rows = result.fetchall()
    if not rows:
        return {"embedded": 0}

    now = datetime.now(tz=timezone.utc)
    texts = []
    for r in rows:
        aum_str = _format_aum(r.net_assets)
        yield_str = f" 7-day gross yield: {float(r.seven_day_gross_yield):.2f}%." if r.seven_day_gross_yield else ""
        wam = f" WAM: {r.weighted_avg_maturity} days." if r.weighted_avg_maturity else ""
        wal = f" WAL: {r.weighted_avg_life} days." if r.weighted_avg_life else ""
        liq = ""
        if r.pct_daily_liquid_latest:
            liq = f" Daily liquid: {float(r.pct_daily_liquid_latest) * 100:.1f}%."
        retail = " Retail." if r.is_retail else " Institutional."
        adviser = f" Adviser: {r.investment_adviser}." if r.investment_adviser else ""

        text_content = (
            f"{r.fund_name} (Series {r.series_id}) is a {r.mmf_category} money market fund.{retail} "
            f"AUM: {aum_str}.{yield_str}{wam}{wal}{liq}{adviser}"
        )
        texts.append(text_content)

    batch = await async_generate_embeddings(texts, batch_size=EMBED_BATCH_SIZE)
    upsert_rows = [
        {
            "id": f"sec_mmf_profile_{r.series_id}",
            "organization_id": None,
            "entity_id": r.series_id,
            "entity_type": "fund",
            "source_type": "sec_mmf_profile",
            "section": None,
            "content": texts[i],
            "language": "en",
            "source_row_id": r.series_id,
            "firm_crd": None,
            "filing_date": r.reporting_period if hasattr(r, "reporting_period") else None,
            "embedding": batch.vectors[i],
            "embedding_model": batch.model,
            "embedded_at": now,
        }
        for i, r in enumerate(rows)
    ]
    await _batch_upsert(db, upsert_rows)
    logger.info("wealth_embedding.sec_mmf_profiles_done", embedded=len(rows))
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
