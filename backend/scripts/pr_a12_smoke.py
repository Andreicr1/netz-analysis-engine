"""PR-A12 F.1 live-DB smoke.

Executes construction runs for the 3 canonical model portfolios against
the local Timescale container. Emits the verification table required by
Section F of the prompt.

Usage::

    cd backend && PYTHONPATH=. python scripts/pr_a12_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://netz:password@127.0.0.1:5434/netz_engine",
)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

ORG_ID = uuid.UUID("403d8392-ebfa-5890-b740-45da49c556eb")
PORTFOLIOS = [
    ("Conservative Preservation", uuid.UUID("3945cee6-f85d-4903-a2dd-cf6a51e1c6a5")),
    ("Balanced Income",           uuid.UUID("e5892474-7438-4ac5-85da-217abcf99932")),
    ("Dynamic Growth",            uuid.UUID("3163d72b-3f8c-427e-9cd2-bead6377b59c")),
]


async def _with_rls(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Set RLS context for the session."""
    await session.execute(
        text("SELECT set_config('app.current_organization_id', :oid, true)"),
        {"oid": str(org_id)},
    )


async def main() -> None:
    from app.domains.wealth.workers.construction_run_executor import (
        execute_construction_run,
    )

    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    results: list[dict] = []
    for name, pid in PORTFOLIOS:
        print(f"\n=== Running {name} ({pid}) ===", flush=True)
        async with Session() as db:
            await _with_rls(db, ORG_ID)
            try:
                run = await execute_construction_run(
                    db,
                    portfolio_id=pid,
                    organization_id=ORG_ID,
                    requested_by="pr_a12_smoke",
                    job_id=None,
                    as_of_date=date.today(),
                )
                await db.commit()
                print(
                    f"  status={run.status} winning_phase={(run.cascade_telemetry or {}).get('cascade_summary')}",
                    flush=True,
                )
                results.append({
                    "name": name, "portfolio_id": pid, "run_id": run.id,
                    "status": run.status,
                })
            except Exception as e:
                print(f"  FAILED: {type(e).__name__}: {e}", flush=True)
                await db.rollback()
                results.append({
                    "name": name, "portfolio_id": pid, "run_id": None,
                    "status": f"error:{type(e).__name__}",
                    "error": str(e),
                })

    # F.1 verification query — pull the runs we just created
    print("\n=== F.1 verification ===", flush=True)
    async with Session() as db:
        await _with_rls(db, ORG_ID)
        rows = await db.execute(
            text(
                """
                SELECT mp.display_name AS name,
                       pcr.status,
                       pcr.cascade_telemetry->>'cascade_summary' AS summary,
                       (pcr.cascade_telemetry->>'min_achievable_cvar')::float AS min_cvar,
                       (pcr.cascade_telemetry->'achievable_return_band'->>'lower')::float AS band_lower,
                       (pcr.cascade_telemetry->'achievable_return_band'->>'upper')::float AS band_upper,
                       pcr.cascade_telemetry->'operator_signal'->>'kind' AS sig_kind,
                       (SELECT COUNT(*) FROM jsonb_object_keys(pcr.weights_proposed)) AS n_w,
                       pcr.wall_clock_ms
                FROM portfolio_construction_runs pcr
                JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
                WHERE pcr.portfolio_id IN (
                    '3945cee6-f85d-4903-a2dd-cf6a51e1c6a5',
                    'e5892474-7438-4ac5-85da-217abcf99932',
                    '3163d72b-3f8c-427e-9cd2-bead6377b59c'
                )
                  AND pcr.requested_at > NOW() - INTERVAL '30 minutes'
                ORDER BY mp.display_name, pcr.requested_at DESC
                LIMIT 3
                """,
            ),
        )
        print(f"{'name':28} {'status':10} {'summary':38} {'min_cvar':>10} "
              f"{'band_lo':>8} {'band_hi':>8} {'sig_kind':28} {'n_w':>4} {'ms':>5}", flush=True)
        for r in rows.mappings():
            min_cvar = f"{r['min_cvar']:.5f}" if r["min_cvar"] is not None else "None"
            band_lo = f"{r['band_lower']:.4f}" if r["band_lower"] is not None else "None"
            band_hi = f"{r['band_upper']:.4f}" if r["band_upper"] is not None else "None"
            sig = r["sig_kind"] or "null"
            print(
                f"{(r['name'] or '')[:28]:28} {r['status']:10} "
                f"{(r['summary'] or '')[:38]:38} {min_cvar:>10} "
                f"{band_lo:>8} {band_hi:>8} {sig[:28]:28} "
                f"{r['n_w']:>4} {r['wall_clock_ms'] or 0:>5}",
                flush=True,
            )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
