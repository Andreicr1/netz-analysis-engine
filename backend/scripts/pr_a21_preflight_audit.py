"""PR-A21 — org universe sanitization pre-flight audit.

Read-only diagnostic that surfaces the four defects addressed by
migration ``0149_sanitize_org_universe``:

* **D1** — duplicate rows per ``(organization_id, instrument_id)`` in
  ``instruments_org``.
* **D2** — rows with ``block_id IS NULL`` produced by a backfill source
  (``pr_a19_1_backfill``, ``pr_a20_backfill`` …).
* **D3** — rows still pointing at the retired ``fi_govt`` block.
* **D3 global** — presence of ``fi_govt`` / ``fi_us_treasury`` in
  ``allocation_blocks`` and ``strategic_allocation``.

Emits a JSON report on stdout and a human-readable summary on stderr.
Always exits 0 so it can be chained into CI without gating.

Usage::

    python -m backend.scripts.pr_a21_preflight_audit

Idempotent, read-only — safe to run against production.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


D1_SQL = text(
    """
    WITH dupes AS (
        SELECT organization_id, instrument_id, COUNT(*) AS n_rows
        FROM instruments_org
        GROUP BY organization_id, instrument_id
        HAVING COUNT(*) > 1
    )
    SELECT d.organization_id,
           d.instrument_id,
           d.n_rows,
           iu.ticker
    FROM dupes d
    JOIN instruments_universe iu USING (instrument_id)
    ORDER BY d.organization_id, iu.ticker
    """
)

D2_SQL = text(
    """
    SELECT organization_id, source, COUNT(*) AS n_rows
    FROM instruments_org
    WHERE block_id IS NULL
    GROUP BY organization_id, source
    ORDER BY organization_id, source
    """
)

D3_SQL = text(
    """
    SELECT io.organization_id,
           COUNT(*) AS n_rows,
           ARRAY_AGG(DISTINCT iu.ticker ORDER BY iu.ticker) AS tickers
    FROM instruments_org io
    JOIN instruments_universe iu USING (instrument_id)
    WHERE io.block_id = 'fi_govt'
    GROUP BY io.organization_id
    ORDER BY io.organization_id
    """
)

GLOBAL_SQL = text(
    """
    SELECT
        EXISTS (
            SELECT 1 FROM allocation_blocks WHERE block_id = 'fi_govt'
        ) AS has_fi_govt,
        EXISTS (
            SELECT 1 FROM allocation_blocks WHERE block_id = 'fi_us_treasury'
        ) AS has_fi_us_treasury,
        (
            SELECT COUNT(*) FROM strategic_allocation
            WHERE block_id = 'fi_govt'
        ) AS sa_uses_fi_govt,
        (
            SELECT COUNT(*) FROM strategic_allocation
            WHERE block_id = 'fi_us_treasury'
        ) AS sa_uses_fi_us_treasury
    """
)


async def _collect(conn) -> dict[str, Any]:
    # D1
    d1_rows = (await conn.execute(D1_SQL)).fetchall()
    d1_by_org: dict[str, dict[str, Any]] = {}
    for org_id, instrument_id, n_rows, ticker in d1_rows:
        bucket = d1_by_org.setdefault(
            str(org_id), {"count": 0, "examples": []},
        )
        bucket["count"] += 1
        if len(bucket["examples"]) < 10:
            bucket["examples"].append(
                {
                    "instrument_id": str(instrument_id),
                    "n_rows": int(n_rows),
                    "ticker": ticker,
                }
            )

    # D2
    d2_rows = (await conn.execute(D2_SQL)).fetchall()
    d2_by_org: dict[str, dict[str, Any]] = {}
    for org_id, source, n_rows in d2_rows:
        bucket = d2_by_org.setdefault(
            str(org_id), {"count": 0, "by_source": {}},
        )
        bucket["count"] += int(n_rows)
        bucket["by_source"][source or "<null>"] = int(n_rows)

    # D3
    d3_rows = (await conn.execute(D3_SQL)).fetchall()
    d3_by_org: dict[str, dict[str, Any]] = {}
    for org_id, n_rows, tickers in d3_rows:
        d3_by_org[str(org_id)] = {
            "count": int(n_rows),
            "tickers": list(tickers) if tickers else [],
        }

    # Global
    global_row = (await conn.execute(GLOBAL_SQL)).one()
    has_fi_govt, has_fi_us_treasury, sa_fi_govt, sa_fi_us_treasury = global_row

    # Union of all orgs touched by any defect.
    org_ids = set(d1_by_org) | set(d2_by_org) | set(d3_by_org)
    organizations = []
    for org_id in sorted(org_ids):
        organizations.append(
            {
                "organization_id": org_id,
                "d1_duplicate_pairs": d1_by_org.get(
                    org_id, {"count": 0, "examples": []},
                ),
                "d2_null_block_id_rows": d2_by_org.get(
                    org_id, {"count": 0, "by_source": {}},
                ),
                "d3_fi_govt_rows": d3_by_org.get(
                    org_id, {"count": 0, "tickers": []},
                ),
                "d3_fi_govt_targeted_by_strategic_allocation": (
                    int(sa_fi_govt) > 0
                ),
            }
        )

    return {
        "organizations": organizations,
        "global": {
            "allocation_blocks_has_fi_govt": bool(has_fi_govt),
            "allocation_blocks_has_fi_us_treasury": bool(has_fi_us_treasury),
            "strategic_allocation_uses_fi_govt": int(sa_fi_govt),
            "strategic_allocation_uses_fi_us_treasury": int(sa_fi_us_treasury),
        },
    }


def _summarize(report: dict[str, Any]) -> str:
    lines = ["PR-A21 preflight audit summary"]
    g = report["global"]
    lines.append(
        f"  global: fi_govt={g['allocation_blocks_has_fi_govt']} "
        f"fi_us_treasury={g['allocation_blocks_has_fi_us_treasury']} "
        f"strategic_allocation(fi_govt)={g['strategic_allocation_uses_fi_govt']} "
        f"strategic_allocation(fi_us_treasury)="
        f"{g['strategic_allocation_uses_fi_us_treasury']}"
    )
    orgs = report["organizations"]
    if not orgs:
        lines.append("  no organizations have any D1/D2/D3 defect — clean state")
        return "\n".join(lines)
    for org in orgs:
        lines.append(
            f"  org={org['organization_id']} "
            f"D1={org['d1_duplicate_pairs']['count']} "
            f"D2={org['d2_null_block_id_rows']['count']} "
            f"D3={org['d3_fi_govt_rows']['count']}"
        )
    return "\n".join(lines)


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    try:
        async with engine.connect() as conn:
            report = await _collect(conn)
    finally:
        await engine.dispose()

    print(json.dumps(report, indent=2, sort_keys=True))
    print(_summarize(report), file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
