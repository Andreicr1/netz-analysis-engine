"""Direct validator check — bypasses construction pipeline."""
from __future__ import annotations

import asyncio
import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://netz:password@127.0.0.1:5434/netz_engine",
)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main() -> None:
    from quant_engine.block_coverage_service import validate_block_coverage

    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    org_id = uuid.UUID("403d8392-ebfa-5890-b740-45da49c556eb")
    for profile in ("conservative", "moderate", "growth"):
        async with Session() as db:
            await db.execute(
                text("SELECT set_config('app.current_organization_id', :oid, true)"),
                {"oid": str(org_id)},
            )
            rpt = await validate_block_coverage(db, org_id, profile)
            print(f"\n=== {profile} ===")
            print(f"  is_sufficient={rpt.is_sufficient}")
            print(f"  total_target_weight_at_risk={rpt.total_target_weight_at_risk}")
            print(f"  n_gaps={len(rpt.gaps)}")
            for g in rpt.gaps:
                print(
                    f"    {g.block_id:20} tw={g.target_weight:.4f} "
                    f"catalog_avail={g.catalog_candidates_available} "
                    f"labels={g.suggested_strategy_labels[:3]}"
                )


if __name__ == "__main__":
    asyncio.run(main())
