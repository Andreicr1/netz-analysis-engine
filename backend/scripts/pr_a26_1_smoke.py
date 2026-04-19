"""PR-A26.1 live-DB smoke. Dispatches propose_mode runs for the 3 canonical
model portfolios against the local Timescale container and prints the
resulting proposal payloads.
"""
from __future__ import annotations

import asyncio
import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://netz:password@127.0.0.1:5434/netz_engine",
)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ORG_ID = uuid.UUID("403d8392-ebfa-5890-b740-45da49c556eb")
PORTFOLIOS = [
    ("Conservative Preservation", uuid.UUID("3945cee6-f85d-4903-a2dd-cf6a51e1c6a5")),
    ("Balanced Income",           uuid.UUID("e5892474-7438-4ac5-85da-217abcf99932")),
    ("Dynamic Growth",            uuid.UUID("3163d72b-3f8c-427e-9cd2-bead6377b59c")),
]


async def _with_rls(session: AsyncSession, org_id: uuid.UUID) -> None:
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

    for name, pid in PORTFOLIOS:
        print(f"\n=== PROPOSE: {name} ({pid}) ===", flush=True)
        async with Session() as db:
            await _with_rls(db, ORG_ID)
            try:
                run = await execute_construction_run(
                    db,
                    portfolio_id=pid,
                    organization_id=ORG_ID,
                    requested_by="pr_a26_1_smoke",
                    propose_mode=True,
                )
            except Exception as exc:
                print(f"  EXCEPTION: {type(exc).__name__}: {exc}", flush=True)
                continue

            print(f"  status={run.status}", flush=True)
            ct = run.cascade_telemetry or {}
            print(f"  winner_signal={ct.get('winner_signal')}", flush=True)
            print(f"  run_mode={ct.get('run_mode')}", flush=True)
            pm = ct.get("proposal_metrics") or {}
            print(
                f"  metrics: E[r]={pm.get('expected_return')} "
                f"CVaR={pm.get('expected_cvar')} "
                f"target={pm.get('target_cvar')} "
                f"feasible={pm.get('cvar_feasible')} "
                f"sharpe={pm.get('expected_sharpe')}",
                flush=True,
            )
            bands = ct.get("proposed_bands") or []
            print(f"  proposed_bands ({len(bands)} blocks):", flush=True)
            for b in bands:
                print(
                    f"    {b.get('block_id'):20} t={b.get('target_weight'):.4f} "
                    f"[min={b.get('drift_min'):.4f} max={b.get('drift_max'):.4f}]",
                    flush=True,
                )


if __name__ == "__main__":
    asyncio.run(main())
