"""Section H verification runner.

Invokes the universe auto-import service against every active org in the
local DB and prints per-org metrics as JSON. Intended for the PR-A6
verification matrix — callers pass the ``reason`` label on the CLI so the
audit trail distinguishes the first run from the idempotency re-run.

Usage:
    python backend/scripts/run_universe_auto_import_verification.py <reason>
"""

from __future__ import annotations

import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import text

from app.core.db.engine import async_session_factory
from app.domains.wealth.services.universe_auto_import_service import (
    auto_import_for_org,
    fetch_active_org_ids,
    fetch_qualified_instruments,
)


async def _run(reason: str) -> list[dict[str, object]]:
    async with async_session_factory() as session:
        org_ids: list[UUID] = await fetch_active_org_ids(session)
        qualified = await fetch_qualified_instruments(session)

    print(
        json.dumps(
            {
                "active_orgs": [str(o) for o in org_ids],
                "qualified_universe": len(qualified),
                "reason": reason,
            },
            indent=2,
        ),
    )

    results: list[dict[str, object]] = []
    for org_id in org_ids:
        async with async_session_factory() as session:
            await session.execute(
                text(
                    "SELECT set_config('app.current_organization_id', :oid, true)",
                ),
                {"oid": str(org_id)},
            )
            metrics = await auto_import_for_org(
                session,
                org_id,
                reason=reason,
                actor_id="script:verification",
                actor_roles=["system"],
                qualified=qualified,
            )
            await session.commit()
            results.append(dict(metrics))
    return results


async def main(reason: str) -> None:
    results = await _run(reason)
    print(json.dumps({"per_org": results}, indent=2, default=str))


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "h_section_verification"
    asyncio.run(main(label))
