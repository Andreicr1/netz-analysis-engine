"""PR-A19.1 Section B.1 — μ-argmax fund identifier.

Replay the universe expansion for a given org + profile up to the
point where ``compute_fund_level_inputs`` returns its ordered
``available_ids`` list, then dump metadata for a target index.

Usage::

    python -m backend.scripts.pr_a19_1_argmax_resolver \\
        --org 403d8392-ebfa-5890-b740-45da49c556eb --idx 86

Read-only; reports ticker + name + key risk metrics + NAV coverage.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

DETAIL_SQL = text(
    """
    SELECT
        i.ticker, i.name, i.asset_class,
        i.attributes->>'strategy_label' AS strategy,
        i.attributes->>'is_leveraged' AS levered,
        frm.volatility_1y, frm.return_1y, frm.cvar_95, frm.max_drawdown_1y,
        (SELECT COUNT(*) FROM nav_timeseries nt
         WHERE nt.instrument_id = i.instrument_id
           AND nt.date >= NOW() - INTERVAL '1 year') AS nav_days_1y,
        (SELECT MAX(date) FROM nav_timeseries
         WHERE instrument_id = i.instrument_id) AS last_nav_date
    FROM instruments_universe i
    LEFT JOIN fund_risk_metrics frm ON frm.instrument_id = i.instrument_id
    WHERE i.instrument_id = :target_id
    """
)

# Approved instrument IDs in this org, ordered the same way
# compute_fund_level_inputs's caller does (instruments_org.selected_at).
ORG_UNIVERSE_SQL = text(
    """
    SELECT io.instrument_id, iu.ticker
    FROM instruments_org io
    JOIN instruments_universe iu ON iu.instrument_id = io.instrument_id
    WHERE io.organization_id = :org_id
      AND io.approval_status = 'approved'
    ORDER BY io.selected_at, io.instrument_id
    """
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", required=True, help="Organization UUID")
    parser.add_argument("--idx", type=int, required=True,
                        help="Universe index to resolve (from mu_trace log)")
    parser.add_argument("--list", action="store_true",
                        help="Print the full ordered universe instead of a single idx")
    args = parser.parse_args()

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(ORG_UNIVERSE_SQL, {"org_id": UUID(args.org)})
        ).fetchall()

        if args.list:
            for i, (iid, ticker) in enumerate(rows):
                print(f"{i:4d}  {ticker:8s}  {iid}")
            await engine.dispose()
            return

        if args.idx < 0 or args.idx >= len(rows):
            print(json.dumps({
                "event": "argmax_resolver_out_of_range",
                "idx": args.idx, "universe_size": len(rows),
            }))
            await engine.dispose()
            return

        target_id, target_ticker = rows[args.idx]
        detail = (
            await conn.execute(DETAIL_SQL, {"target_id": target_id})
        ).fetchone()

    print(json.dumps({
        "event": "argmax_resolver_result",
        "idx": args.idx,
        "instrument_id": str(target_id),
        "ticker": target_ticker,
        "detail": {
            "ticker": detail[0] if detail else None,
            "name": detail[1] if detail else None,
            "asset_class": detail[2] if detail else None,
            "strategy_label": detail[3] if detail else None,
            "is_leveraged": detail[4] if detail else None,
            "volatility_1y": float(detail[5]) if detail and detail[5] is not None else None,
            "return_1y": float(detail[6]) if detail and detail[6] is not None else None,
            "cvar_95": float(detail[7]) if detail and detail[7] is not None else None,
            "max_drawdown_1y": float(detail[8]) if detail and detail[8] is not None else None,
            "nav_days_1y": int(detail[9]) if detail and detail[9] is not None else None,
            "last_nav_date": str(detail[10]) if detail and detail[10] is not None else None,
        },
    }, default=str, indent=2))

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
