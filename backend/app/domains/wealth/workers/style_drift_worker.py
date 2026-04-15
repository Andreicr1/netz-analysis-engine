"""Worker: style_drift_worker — compute composition drift per CIK.

Advisory lock : 900_064 (deterministic literal)
Frequency     : weekly (after sec_13f / N-PORT ingestion settles)
Idempotent    : yes — every CIK gets exactly one is_current=true row.
                Re-runs UPDATE the row if drift signal changed; older
                runs are demoted to is_current=false for history.

What this does
--------------
For every CIK in ``sec_nport_holdings`` with at least 5 quarterly
filings (current + 4 historical):

  1. Fetch the latest report_date and 4-8 prior quarters
  2. Run ``analyze_holdings`` per quarter
  3. Skip if current quarter is not coverage_quality high/medium
     (mirrors the Layer 0 classifier gates — trust-CIK aggregation
     produces meaningless composition for single-fund interpretation)
  4. Skip if current composition fails the coherence check (>=3
     dominant asset-class buckets)
  5. Compute drift via ``compute_style_drift``
  6. Persist into ``holdings_drift_alerts`` (global, no RLS)

What this does NOT do
---------------------
  • Doesn't write to ``strategy_drift_alerts`` (org-scoped table for
    performance-metric drift). The two signals are complementary —
    composition vs performance.
  • Doesn't enrich with instrument_id (drift is per-CIK; the
    frontend joins via ``sec_registered_funds.cik`` /
    ``instruments_universe.attributes->>'sec_cik'`` to map back).
  • Doesn't act on drift severity. Alerting / rebalancing triggers
    are downstream consumers of the table (separate sprint).
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.services.holdings_analyzer import (
    analyze_holdings,
)
from app.domains.wealth.services.strategy_classifier import (
    _is_coherent_composition,
)
from app.domains.wealth.services.style_drift_analyzer import (
    StyleDriftResult,
    compute_style_drift,
)

STYLE_DRIFT_LOCK_ID = 900_064
logger: Any = structlog.get_logger()

# Need at least 5 quarters total: 1 current + 4 historical baseline.
# Fewer historical points make the drift signal noisy (per analyzer).
_MIN_QUARTERS_REQUIRED = 5

# Fetch up to N prior quarters for the historical baseline. 8 quarters
# (2 years) is the institutional convention for fund style baselines.
_MAX_HISTORICAL_QUARTERS = 8

# Per-row N-PORT pull. Indexed by idx_sec_nport_holdings_cik_date.
_NPORT_BY_CIK_SQL = text(
    """
    SELECT report_date, cusip, isin, issuer_name,
           asset_class, sector, market_value, pct_of_nav, currency
    FROM sec_nport_holdings
    WHERE cik = :cik
    ORDER BY report_date DESC, cusip
    """,
)

# Discover candidates — every CIK with at least the minimum quarter
# count. Cheap query (uses idx_sec_nport_holdings_cik_date).
_CANDIDATE_CIKS_SQL = text(
    """
    SELECT cik, COUNT(DISTINCT report_date) AS n_quarters
    FROM sec_nport_holdings
    GROUP BY cik
    HAVING COUNT(DISTINCT report_date) >= :min_quarters
    ORDER BY cik
    """,
)

# Best-effort fund_name lookup — checks sec_registered_funds first, then
# sec_etfs. Returns NULL when the CIK doesn't appear in either catalog
# (alert still persisted; the JOIN happens on the read side).
_FUND_NAME_LOOKUP_SQL = text(
    """
    SELECT COALESCE(rf.fund_name, e.fund_name) AS fund_name
    FROM (SELECT :cik::text AS cik) c
    LEFT JOIN sec_registered_funds rf ON rf.cik = c.cik
    LEFT JOIN sec_etfs            e  ON e.cik  = c.cik
    LIMIT 1
    """,
)


async def run_style_drift(*, limit: int | None = None) -> dict[str, Any]:
    """Compute composition drift for every eligible CIK.

    Args:
        limit: Cap candidates processed (useful for dry-runs).

    Returns:
        Summary dict with counts per status and runtime.
    """
    started = time.monotonic()
    stats = {
        "candidates": 0,
        "insufficient_data": 0,
        "skipped_low_coverage": 0,
        "skipped_incoherent": 0,
        "stable": 0,
        "moderate": 0,
        "severe": 0,
        "errors": 0,
    }

    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({STYLE_DRIFT_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("style_drift.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            candidates = await db.execute(
                _CANDIDATE_CIKS_SQL,
                {"min_quarters": _MIN_QUARTERS_REQUIRED},
            )
            cik_rows = candidates.mappings().all()
            if limit:
                cik_rows = cik_rows[:limit]

            for r in cik_rows:
                stats["candidates"] += 1
                cik = r["cik"]
                try:
                    outcome = await _process_cik(db, cik)
                    stats[outcome] = stats.get(outcome, 0) + 1
                except Exception as exc:  # noqa: BLE001
                    stats["errors"] += 1
                    logger.exception(
                        "style_drift.cik_failed", cik=cik, error=str(exc),
                    )

                # Commit every 100 CIKs to bound transaction size and
                # let the partial unique index reflect progress.
                if stats["candidates"] % 100 == 0:
                    await db.commit()

            await db.commit()
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({STYLE_DRIFT_LOCK_ID})"),
            )

    stats["duration_seconds"] = round(time.monotonic() - started, 2)
    logger.info("style_drift.complete", **stats)
    return stats


async def _process_cik(db: AsyncSession, cik: str) -> str:
    """Compute drift for one CIK and persist. Returns outcome label."""
    rows = await db.execute(_NPORT_BY_CIK_SQL, {"cik": cik})
    raw = rows.mappings().all()

    # Group rows by report_date → list of holding dicts per quarter.
    by_date: dict[Any, list[dict]] = {}
    for row in raw:
        by_date.setdefault(row["report_date"], []).append(dict(row))
    sorted_dates = sorted(by_date.keys(), reverse=True)
    if len(sorted_dates) < _MIN_QUARTERS_REQUIRED:
        return "insufficient_data"

    current_date = sorted_dates[0]
    historical_dates = sorted_dates[1:1 + _MAX_HISTORICAL_QUARTERS]

    current = analyze_holdings(by_date[current_date])
    if current.coverage_quality not in ("high", "medium"):
        return "skipped_low_coverage"
    if not _is_coherent_composition(current):
        return "skipped_incoherent"

    historical = [analyze_holdings(by_date[d]) for d in historical_dates]
    # Prune historical entries that don't pass the same quality gates;
    # drifting against polluted baselines is noise.
    historical = [
        h for h in historical
        if h.coverage_quality in ("high", "medium")
        and _is_coherent_composition(h)
    ]
    if len(historical) < 4:
        return "insufficient_data"

    result = compute_style_drift(current, historical, instrument_id=cik)
    fund_name = await _fund_name_for_cik(db, cik)
    await _persist(db, result, cik=cik, fund_name=fund_name)
    return result.severity if result.severity != "none" else "stable"


async def _fund_name_for_cik(db: AsyncSession, cik: str) -> str | None:
    row = await db.execute(_FUND_NAME_LOOKUP_SQL, {"cik": cik})
    r = row.mappings().first()
    return r["fund_name"] if r else None


async def _persist(
    db: AsyncSession,
    result: StyleDriftResult,
    *,
    cik: str,
    fund_name: str | None,
) -> None:
    """Demote prior is_current row, then INSERT the new one.

    The partial unique index ``uq_holdings_drift_current`` prevents
    two concurrent inserts from coexisting as is_current=true.
    """
    await db.execute(
        text(
            """
            UPDATE holdings_drift_alerts
               SET is_current = false,
                   updated_at = now()
             WHERE cik = :cik AND is_current = true
            """,
        ),
        {"cik": cik},
    )
    await db.execute(
        text(
            """
            INSERT INTO holdings_drift_alerts (
                cik, fund_name, current_report_date,
                historical_window_quarters,
                composite_drift, asset_mix_drift, fi_subtype_drift,
                geography_drift, issuer_category_drift,
                status, severity, drivers,
                is_current, detected_at
            ) VALUES (
                :cik, :fund_name, :current_date,
                :hist_n,
                :composite, :asset_mix, :fi_subtype,
                :geography, :issuer_cat,
                :status, :severity, CAST(:drivers AS jsonb),
                true, :detected_at
            )
            """,
        ),
        {
            "cik": cik,
            "fund_name": fund_name,
            "current_date": result.current_date,
            "hist_n": result.historical_window_quarters,
            "composite": result.composite_drift,
            "asset_mix": result.asset_mix_drift,
            "fi_subtype": result.fi_subtype_drift,
            "geography": result.geography_drift,
            "issuer_cat": result.issuer_category_drift,
            "status": result.status,
            "severity": result.severity,
            "drivers": _json_dumps(result.drivers),
            "detected_at": datetime.now(UTC),
        },
    )


def _json_dumps(value: Any) -> str:
    import json
    return json.dumps(value)


def _process_holdings_quarters(
    quarters: dict[Any, list[dict[str, Any]]],
    cik: str,
) -> StyleDriftResult | str:
    """Pure-compute helper exposed for tests.

    Returns a ``StyleDriftResult`` on success or a string outcome
    label (``"insufficient_data"``, ``"skipped_low_coverage"``,
    ``"skipped_incoherent"``) when one of the gates rejects the CIK.
    """
    sorted_dates = sorted(quarters.keys(), reverse=True)
    if len(sorted_dates) < _MIN_QUARTERS_REQUIRED:
        return "insufficient_data"

    current_date = sorted_dates[0]
    historical_dates = sorted_dates[1:1 + _MAX_HISTORICAL_QUARTERS]

    current = analyze_holdings(quarters[current_date])
    if current.coverage_quality not in ("high", "medium"):
        return "skipped_low_coverage"
    if not _is_coherent_composition(current):
        return "skipped_incoherent"

    historical = [analyze_holdings(quarters[d]) for d in historical_dates]
    historical = [
        h for h in historical
        if h.coverage_quality in ("high", "medium")
        and _is_coherent_composition(h)
    ]
    if len(historical) < 4:
        return "insufficient_data"

    return compute_style_drift(current, historical, instrument_id=cik)


if __name__ == "__main__":  # pragma: no cover - manual trigger
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_style_drift())
