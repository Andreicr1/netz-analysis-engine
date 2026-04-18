"""PR-A19.1 Section A.1 — canonical liquid-beta coverage audit.

For each organization, report which of the 10 canonical tickers
(SPY, IVV, VTI, AGG, BND, IEF, TLT, SHY, GLD, VTEB) are present,
approved, and block-assigned in ``instruments_org``. Emits a
structured ``universe_canonical_coverage`` log line per org.

Usage::

    python -m backend.scripts.pr_a19_1_universe_audit

Idempotent, read-only. Safe to run against production.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

CANONICAL_TICKERS = (
    "SPY", "IVV", "VTI", "AGG", "BND", "IEF", "TLT", "SHY", "GLD", "VTEB",
)

AUDIT_SQL = text(
    """
    WITH canonical(ticker) AS (
        SELECT unnest(CAST(:tickers AS text[]))
    ),
    universe_canonical AS (
        SELECT iu.instrument_id, iu.ticker
        FROM instruments_universe iu
        JOIN canonical c ON c.ticker = iu.ticker
    ),
    org_coverage AS (
        SELECT
            o.id AS organization_id,
            uc.ticker,
            io.instrument_id IS NOT NULL AS in_org,
            io.approval_status,
            io.block_id
        FROM organizations o
        CROSS JOIN universe_canonical uc
        LEFT JOIN instruments_org io
            ON io.organization_id = o.id
           AND io.instrument_id = uc.instrument_id
    )
    SELECT organization_id, ticker, in_org, approval_status, block_id
    FROM org_coverage
    ORDER BY organization_id, ticker
    """
)


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(AUDIT_SQL, {"tickers": list(CANONICAL_TICKERS)})
        ).fetchall()

    by_org: dict[str, dict[str, dict[str, object]]] = {}
    for org_id, ticker, in_org, status, block_id in rows:
        by_org.setdefault(str(org_id), {})[ticker] = {
            "in_org": bool(in_org),
            "approval_status": status,
            "block_id": block_id,
        }

    for org_id, coverage in by_org.items():
        missing = [t for t, v in coverage.items() if not v["in_org"]]
        unapproved = [
            t for t, v in coverage.items()
            if v["in_org"] and v["approval_status"] != "approved"
        ]
        unblocked = [
            t for t, v in coverage.items()
            if v["in_org"] and v["block_id"] is None
        ]
        print(
            json.dumps(
                {
                    "event": "universe_canonical_coverage",
                    "org_id": org_id,
                    "n_present": 10 - len(missing),
                    "missing_tickers": missing,
                    "unapproved": unapproved,
                    "unblocked": unblocked,
                }
            )
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
