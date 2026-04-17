"""PR-A17 one-shot re-run of auto-import worker across every known org.

Reuses the production service path (same classifier, same UPSERT). Prints
per-org counters + the final instruments_org block_id distribution so the
live-smoke coverage numbers in Section F.1 can be validated.
"""
from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domains.wealth.services.universe_auto_import_service import (  # noqa: E402
    auto_import_for_org,
)


async def main() -> None:
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url, pool_pre_ping=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    async with sm() as db:
        orgs = (await db.execute(text(
            """
            SELECT DISTINCT organization_id
            FROM instruments_org
            UNION
            SELECT organization_id FROM vertical_config_overrides
            """
        ))).scalars().all()

        print(f"Re-running auto-import for {len(orgs)} orgs…")
        for org_id in orgs:
            await db.execute(
                text(f"SET LOCAL app.current_organization_id = '{org_id}'"),
            )
            res = await auto_import_for_org(
                db, UUID(str(org_id)),
                reason="pr_a17_rerun",
                actor_id="script:rerun_auto_import_pr_a17",
            )
            await db.commit()
            print(f"  {org_id}: inserted={res.get('inserted')} "
                  f"updated={res.get('updated')} skipped={res.get('skipped')} "
                  f"reasons={res.get('skipped_by_reason')}")

        rows = (await db.execute(text(
            """
            SELECT block_id, COUNT(*) AS n
            FROM instruments_org
            WHERE approval_status = 'approved'
            GROUP BY block_id
            ORDER BY n DESC
            """
        ))).all()
        print("\nPost-run block_id distribution (approved):")
        for r in rows:
            print(f"  {r.block_id:20s} {r.n:>5}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
