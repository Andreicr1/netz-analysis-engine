"""Worker: strategy_reclassification — run the cascade classifier across all
fund sources and stage the proposed ``strategy_label`` values for operator
review.

Advisory lock : 900_062 (deterministic literal)
Frequency     : on-demand (no cron — an operator triggers it after the
                weekly ``tiingo_enrichment`` run)
Idempotent    : yes — every invocation opens a fresh ``run_id``; rows from
                prior runs are left alone so the apply script can choose
                which run to act on.

Writes go EXCLUSIVELY to ``strategy_reclassification_stage``.  Production
``strategy_label`` columns are NEVER touched here — that is the job of the
separate ``apply_strategy_reclassification.py`` script (Session B).

Source coverage
---------------
``instruments_universe``
    Primary target for Layer 1: the upstream ``tiingo_enrichment`` worker
    populates ``attributes.tiingo_description`` here. ``fund_type`` and
    current ``strategy_label`` live inside the same JSONB blob.
    Fund CIK (when present in ``attributes.sec_cik``) unlocks Layer 0.
``sec_registered_funds``, ``sec_etfs``
    Native ``cik`` column — Layer 0 (N-PORT holdings composition) runs
    first, then degrades cleanly to Layer 2 (name regex) for funds
    without N-PORT coverage.
``sec_manager_funds``
    Private funds; no fund-level CIK exists (only manager CRD), so
    Layer 0 is skipped. Cascade jumps straight to Layer 2.
``esma_funds``
    European UCITS; no N-PORT filings. Layer 0 skipped, cascade jumps
    to Layer 2.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.services.holdings_analyzer import (
    HoldingsAnalysis,
    analyze_holdings,
)
from app.domains.wealth.services.strategy_classifier import (
    ClassificationResult,
    classify_fund,
)

RECLASSIFICATION_LOCK_ID = 900_062
logger: Any = structlog.get_logger()

# Commit + log every N rows.  Large enough to amortise the per-row
# INSERT cost; small enough that a crash loses at most a few seconds of work.
_STAGE_BATCH_SIZE = 500

_DEFAULT_SOURCES: tuple[str, ...] = (
    "instruments_universe",
    "sec_manager_funds",
    "sec_registered_funds",
    "sec_etfs",
    "esma_funds",
)


# ───────────────────────────────────────────────────────────────────
# Row envelope — uniform shape regardless of source table
# ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FundRow:
    """Canonical fund row for the classifier regardless of source table."""

    source_table: str
    source_pk: str  # serialized primary key (uuid string, CIK, CRD, ISIN, series_id)
    fund_name: str
    fund_type: str | None
    current_strategy_label: str | None
    tiingo_description: str | None  # None for sources without Tiingo enrichment
    cik: str | None = None  # Fund CIK for N-PORT lookup; None when not applicable
                            # (sec_manager_funds has no fund CIK; esma_funds has no N-PORT).


# ───────────────────────────────────────────────────────────────────
# Public entry point
# ───────────────────────────────────────────────────────────────────


async def run_strategy_reclassification(
    *,
    sources: list[str] | None = None,
    limit_per_source: int | None = None,
) -> dict[str, Any]:
    """Run the cascade classifier and stage proposed labels per fund.

    Parameters
    ----------
    sources:
        Whitelist of source table names. Defaults to all five sources.
    limit_per_source:
        Cap rows per source (useful for dry-runs and CI). ``None`` processes
        the full catalog.

    Returns
    -------
    Summary dict keyed by source table plus aggregate counters and the
    generated ``run_id`` (so the operator can pipe it straight into
    ``strategy_diff_report.py --run-id ...``).
    """
    started = time.monotonic()
    selected = tuple(sources) if sources else _DEFAULT_SOURCES
    run_id = uuid.uuid4()

    logger.info(
        "strategy_reclassification.start",
        run_id=str(run_id),
        sources=list(selected),
        limit_per_source=limit_per_source,
    )

    stats: dict[str, Any] = {
        "run_id": str(run_id),
        "sources": {s: {"candidates": 0, "staged": 0} for s in selected},
        "totals": {"candidates": 0, "staged": 0, "fallback": 0},
    }

    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({RECLASSIFICATION_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("strategy_reclassification.lock_held")
            return {"status": "skipped", "reason": "lock_held", "run_id": str(run_id)}

        try:
            for source in selected:
                src_stats = await _reclassify_source(
                    db,
                    run_id=run_id,
                    source=source,
                    limit=limit_per_source,
                )
                stats["sources"][source] = src_stats
                stats["totals"]["candidates"] += src_stats["candidates"]
                stats["totals"]["staged"] += src_stats["staged"]
                stats["totals"]["fallback"] += src_stats["fallback"]
                await db.commit()
                logger.info(
                    "strategy_reclassification.source_done",
                    run_id=str(run_id),
                    source=source,
                    **src_stats,
                )
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({RECLASSIFICATION_LOCK_ID})"),
            )

    stats["duration_seconds"] = round(time.monotonic() - started, 2)
    logger.info("strategy_reclassification.complete", **stats["totals"], run_id=str(run_id))
    return stats


# ───────────────────────────────────────────────────────────────────
# Per-source dispatch
# ───────────────────────────────────────────────────────────────────


async def _reclassify_source(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    source: str,
    limit: int | None,
) -> dict[str, int]:
    """Stream rows from one source, classify each, insert into the stage table."""
    reader = _reader_for_source(source)
    if reader is None:
        logger.warning("strategy_reclassification.unknown_source", source=source)
        return {"candidates": 0, "staged": 0, "fallback": 0}

    stats = {
        "candidates": 0, "staged": 0, "fallback": 0,
        "holdings_lookups": 0, "holdings_hits": 0,
    }
    buffer: list[tuple[_FundRow, ClassificationResult]] = []

    async for row in reader(db, limit):
        stats["candidates"] += 1

        # Layer 0 prep: fetch latest N-PORT holdings if this source carries a
        # fund CIK. Per-row indexed lookup against idx_sec_nport_holdings_cik_date.
        holdings_analysis: HoldingsAnalysis | None = None
        if row.cik:
            stats["holdings_lookups"] += 1
            holdings_analysis = await _compute_holdings_analysis(db, row.cik)
            if holdings_analysis is not None and holdings_analysis.n_holdings > 0:
                stats["holdings_hits"] += 1

        result = classify_fund(
            fund_name=row.fund_name,
            fund_type=row.fund_type,
            tiingo_description=row.tiingo_description,
            holdings_analysis=holdings_analysis,
        )
        # Even ``fallback`` rows are staged — they give the operator
        # visibility into how much of the catalog the cascade could NOT
        # handle, which in turn drives Layer 3 (brochure) coverage.
        if result.strategy_label is None:
            stats["fallback"] += 1
        buffer.append((row, result))

        if len(buffer) >= _STAGE_BATCH_SIZE:
            stats["staged"] += await _persist_stage(db, run_id, buffer)
            buffer.clear()

    if buffer:
        stats["staged"] += await _persist_stage(db, run_id, buffer)

    return stats


_SourceReader = Callable[[AsyncSession, int | None], AsyncIterator[_FundRow]]


def _reader_for_source(source: str) -> _SourceReader | None:
    """Dispatch table from source name to an async row-reader."""
    return {
        "instruments_universe": _read_instruments_universe,
        "sec_manager_funds": _read_sec_manager_funds,
        "sec_registered_funds": _read_sec_registered_funds,
        "sec_etfs": _read_sec_etfs,
        "esma_funds": _read_esma_funds,
    }.get(source)


# ───────────────────────────────────────────────────────────────────
# Layer 0 helper — N-PORT holdings fetch + analysis
# ───────────────────────────────────────────────────────────────────

_NPORT_LATEST_SQL = text(
    """
    WITH latest AS (
        SELECT MAX(report_date) AS rd
        FROM sec_nport_holdings
        WHERE cik = :cik
    )
    SELECT
        report_date, cusip, isin, issuer_name,
        asset_class, sector, market_value, pct_of_nav, currency
    FROM sec_nport_holdings
    WHERE cik = :cik
      AND report_date = (SELECT rd FROM latest)
    """,
)


async def _compute_holdings_analysis(
    db: AsyncSession, cik: str,
) -> HoldingsAnalysis | None:
    """Fetch the latest N-PORT report for ``cik`` and summarise it.

    Returns ``None`` when no holdings exist for the CIK (the classifier
    handles ``None`` by skipping Layer 0 cleanly).
    """
    rows = await db.execute(_NPORT_LATEST_SQL, {"cik": cik})
    raw = [dict(r._mapping) for r in rows]
    if not raw:
        return None
    return analyze_holdings(raw)


# ───────────────────────────────────────────────────────────────────
# Source readers — one per table
#
# Each reader yields ``_FundRow`` regardless of the underlying schema so
# the dispatcher stays trivial.  Tiingo description is only available on
# ``instruments_universe``; other readers pass ``tiingo_description=None``
# and the cascade degrades to Layer 2.
# ───────────────────────────────────────────────────────────────────


async def _read_instruments_universe(
    db: AsyncSession, limit: int | None,
) -> AsyncIterator[_FundRow]:
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    # Ambiguous-CIK guard: ~88% of instruments_universe rows with a CIK
    # share that CIK with sibling rows because universe_sync currently
    # writes the *trust* CIK rather than the fund/series CIK. N-PORT for
    # a trust CIK aggregates holdings across all sub-funds, producing a
    # composition that does not represent any individual fund. We only
    # surface ``cik`` to Layer 0 when the CIK maps 1:1 within
    # instruments_universe; everything else falls through to Layer 1/2.
    # Tracked by: universe_sync trust-CIK fix (Phase 4.5 follow-up).
    rows = await db.execute(
        text(
            f"""
            WITH cik_counts AS (
                SELECT attributes->>'sec_cik' AS sec_cik, COUNT(*) AS n
                FROM instruments_universe
                WHERE attributes->>'sec_cik' IS NOT NULL
                GROUP BY attributes->>'sec_cik'
            )
            SELECT
                iu.instrument_id::text        AS pk,
                iu.name                       AS fund_name,
                iu.attributes->>'fund_type'   AS fund_type,
                iu.attributes->>'strategy_label'      AS current_label,
                iu.attributes->>'tiingo_description'  AS tiingo_desc,
                CASE WHEN cc.n = 1 THEN iu.attributes->>'sec_cik' END  AS cik
            FROM instruments_universe iu
            LEFT JOIN cik_counts cc
              ON cc.sec_cik = iu.attributes->>'sec_cik'
            WHERE iu.is_active = true
              AND iu.name IS NOT NULL
            ORDER BY iu.instrument_id
            {limit_clause}
            """,
        ),
    )
    for r in rows.mappings().all():
        yield _FundRow(
            source_table="instruments_universe",
            source_pk=r["pk"],
            fund_name=r["fund_name"],
            fund_type=r["fund_type"],
            current_strategy_label=r["current_label"],
            tiingo_description=r["tiingo_desc"],
            cik=r["cik"],
        )


async def _read_sec_manager_funds(
    db: AsyncSession, limit: int | None,
) -> AsyncIterator[_FundRow]:
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    rows = await db.execute(
        text(
            f"""
            SELECT
                id::text             AS pk,
                fund_name,
                fund_type,
                strategy_label       AS current_label
            FROM sec_manager_funds
            WHERE is_institutional = true
            ORDER BY id
            {limit_clause}
            """,
        ),
    )
    for r in rows.mappings().all():
        yield _FundRow(
            source_table="sec_manager_funds",
            source_pk=r["pk"],
            fund_name=r["fund_name"],
            fund_type=r["fund_type"],
            current_strategy_label=r["current_label"],
            tiingo_description=None,
        )


async def _read_sec_registered_funds(
    db: AsyncSession, limit: int | None,
) -> AsyncIterator[_FundRow]:
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    rows = await db.execute(
        text(
            f"""
            SELECT
                cik                  AS pk,
                cik                  AS cik,
                fund_name,
                fund_type,
                strategy_label       AS current_label
            FROM sec_registered_funds
            WHERE is_institutional = true
            ORDER BY cik
            {limit_clause}
            """,
        ),
    )
    for r in rows.mappings().all():
        yield _FundRow(
            source_table="sec_registered_funds",
            source_pk=r["pk"],
            fund_name=r["fund_name"],
            fund_type=r["fund_type"],
            current_strategy_label=r["current_label"],
            tiingo_description=None,
            cik=r["cik"],
        )


async def _read_sec_etfs(
    db: AsyncSession, limit: int | None,
) -> AsyncIterator[_FundRow]:
    # ETFs have no ``fund_type`` column; use a stable sentinel so the
    # classifier's hedge-fund gate does not misfire.
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    rows = await db.execute(
        text(
            f"""
            WITH cik_counts AS (
                SELECT cik, COUNT(*) AS n
                FROM sec_etfs
                WHERE is_institutional = true
                GROUP BY cik
            )
            SELECT
                e.series_id          AS pk,
                CASE WHEN cc.n = 1 THEN e.cik END  AS cik,
                e.fund_name,
                e.strategy_label     AS current_label
            FROM sec_etfs e
            LEFT JOIN cik_counts cc ON cc.cik = e.cik
            WHERE e.is_institutional = true
            ORDER BY e.series_id
            {limit_clause}
            """,
        ),
    )
    for r in rows.mappings().all():
        yield _FundRow(
            source_table="sec_etfs",
            source_pk=r["pk"],
            fund_name=r["fund_name"],
            fund_type="ETF",
            current_strategy_label=r["current_label"],
            tiingo_description=None,
            cik=r["cik"],
        )


async def _read_esma_funds(
    db: AsyncSession, limit: int | None,
) -> AsyncIterator[_FundRow]:
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    rows = await db.execute(
        text(
            f"""
            SELECT
                isin                 AS pk,
                fund_name,
                fund_type,
                strategy_label       AS current_label
            FROM esma_funds
            WHERE is_institutional = true
            ORDER BY isin
            {limit_clause}
            """,
        ),
    )
    for r in rows.mappings().all():
        yield _FundRow(
            source_table="esma_funds",
            source_pk=r["pk"],
            fund_name=r["fund_name"],
            fund_type=r["fund_type"],
            current_strategy_label=r["current_label"],
            tiingo_description=None,
        )


# ───────────────────────────────────────────────────────────────────
# Stage-table write
# ───────────────────────────────────────────────────────────────────


async def _persist_stage(
    db: AsyncSession,
    run_id: uuid.UUID,
    buffer: list[tuple[_FundRow, ClassificationResult]],
) -> int:
    """Batch-insert classifier results into ``strategy_reclassification_stage``.

    We use an executemany-style parameter list rather than a COPY because
    the run sizes (~75k rows total across all sources) are small enough
    that the simpler INSERT path is preferable.
    """
    if not buffer:
        return 0

    rows_payload = [
        {
            "run_id": str(run_id),
            "source_table": row.source_table,
            "source_pk": row.source_pk,
            "fund_name": row.fund_name,
            "fund_type": row.fund_type,
            "current_label": row.current_strategy_label,
            "proposed_label": result.strategy_label,
            "classification_source": result.source,
            "matched_pattern": result.matched_pattern,
            "confidence": result.confidence,
        }
        for row, result in buffer
    ]

    await db.execute(
        text(
            """
            INSERT INTO strategy_reclassification_stage (
                run_id, source_table, source_pk,
                fund_name, fund_type,
                current_strategy_label, proposed_strategy_label,
                classification_source, matched_pattern, confidence
            )
            VALUES (
                CAST(:run_id AS uuid), :source_table, :source_pk,
                :fund_name, :fund_type,
                :current_label, :proposed_label,
                :classification_source, :matched_pattern, :confidence
            )
            """,
        ),
        rows_payload,
    )
    return len(rows_payload)


if __name__ == "__main__":  # pragma: no cover - manual trigger
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_strategy_reclassification())
