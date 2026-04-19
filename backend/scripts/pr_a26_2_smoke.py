"""PR-A26.2 live-DB smoke. Full propose → approve → realize loop for the 3
canonical portfolios against the local Timescale container.
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
    ("Conservative Preservation", uuid.UUID("3945cee6-f85d-4903-a2dd-cf6a51e1c6a5"), "conservative"),
    ("Balanced Income",           uuid.UUID("e5892474-7438-4ac5-85da-217abcf99932"), "moderate"),
    ("Dynamic Growth",            uuid.UUID("3163d72b-3f8c-427e-9cd2-bead6377b59c"), "growth"),
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

    propose_runs: dict[str, uuid.UUID] = {}

    # ── Phase 1: propose ──
    for name, pid, profile in PORTFOLIOS:
        print(f"\n=== PROPOSE: {name} ({profile}) ===", flush=True)
        async with Session() as db:
            await _with_rls(db, ORG_ID)
            try:
                run = await execute_construction_run(
                    db,
                    portfolio_id=pid,
                    organization_id=ORG_ID,
                    requested_by="pr_a26_2_smoke_propose",
                    propose_mode=True,
                )
                ct = run.cascade_telemetry or {}
                print(f"  status={run.status} signal={ct.get('winner_signal')}")
                pm = ct.get("proposal_metrics") or {}
                print(
                    f"  E[r]={pm.get('expected_return')} "
                    f"CVaR={pm.get('expected_cvar')} "
                    f"feasible={pm.get('cvar_feasible')}"
                )
                if run.status == "succeeded":
                    propose_runs[profile] = run.id
                await db.commit()
            except Exception as e:
                import traceback

                print(f"  EXCEPTION: {type(e).__name__}: {e}")
                traceback.print_exc()

    # ── Phase 2: approve ──
    print("\n=== APPROVE ===")
    for profile, run_id in propose_runs.items():
        async with Session() as db:
            await _with_rls(db, ORG_ID)
            # approve via direct SQL snapshot (endpoint logic inlined for test)
            result = await db.execute(
                text("""
                    SELECT cascade_telemetry->'proposed_bands' AS bands,
                           cascade_telemetry->'proposal_metrics' AS metrics
                    FROM portfolio_construction_runs
                    WHERE id = :rid
                """),
                {"rid": str(run_id)},
            )
            row = result.mappings().one_or_none()
            if not row or not row["bands"]:
                print(f"  {profile}: NO BANDS — skip")
                continue
            bands = row["bands"]
            metrics = row["metrics"] or {}

            # supersede any prior active approval
            await db.execute(
                text("""
                    UPDATE allocation_approvals
                       SET superseded_at = now()
                     WHERE organization_id = :org
                       AND profile = :prof
                       AND superseded_at IS NULL
                """),
                {"org": str(ORG_ID), "prof": profile},
            )

            # insert approval
            approval_id = uuid.uuid4()
            await db.execute(
                text("""
                    INSERT INTO allocation_approvals
                        (id, run_id, organization_id, profile, approved_by,
                         cvar_at_approval, expected_return_at_approval,
                         cvar_feasible_at_approval)
                    VALUES
                        (:id, :rid, :org, :prof, :by,
                         :cvar, :er, :feas)
                """),
                {
                    "id": str(approval_id),
                    "rid": str(run_id),
                    "org": str(ORG_ID),
                    "prof": profile,
                    "by": "pr_a26_2_smoke",
                    "cvar": metrics.get("target_cvar"),
                    "er": metrics.get("expected_return"),
                    "feas": bool(metrics.get("cvar_feasible", True)),
                },
            )

            # snapshot bands atomically
            for band in bands:
                await db.execute(
                    text("""
                        UPDATE strategic_allocation
                           SET target_weight = :t,
                               drift_min = :dmin,
                               drift_max = :dmax,
                               approved_from_run_id = :rid,
                               approved_at = now(),
                               approved_by = 'pr_a26_2_smoke'
                         WHERE organization_id = :org
                           AND profile = :prof
                           AND block_id = :b
                    """),
                    {
                        "org": str(ORG_ID),
                        "prof": profile,
                        "b": band["block_id"],
                        "t": band["target_weight"],
                        "dmin": band["drift_min"],
                        "dmax": band["drift_max"],
                        "rid": str(run_id),
                    },
                )
            await db.commit()
            print(f"  {profile}: approved run {run_id} (18 bands snapshotted)")

    # ── Phase 3: realize ──
    for name, pid, profile in PORTFOLIOS:
        print(f"\n=== REALIZE: {name} ({profile}) ===")
        async with Session() as db:
            await _with_rls(db, ORG_ID)
            try:
                run = await execute_construction_run(
                    db,
                    portfolio_id=pid,
                    organization_id=ORG_ID,
                    requested_by="pr_a26_2_smoke_realize",
                    propose_mode=False,
                )
                ct = run.cascade_telemetry or {}
                print(f"  status={run.status} signal={ct.get('winner_signal')}")
                n_weights = len(run.weights_proposed or {})
                print(f"  n_instrument_weights={n_weights}")
            except Exception as e:
                print(f"  EXCEPTION: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
