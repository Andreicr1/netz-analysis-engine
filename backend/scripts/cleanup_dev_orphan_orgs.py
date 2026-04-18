"""Dev-only: delete all rows for orphan organization_ids across every RLS-scoped table.

Use when dev DB accumulates stale tenant UUIDs from prior Clerk sessions. Discovers
tables dynamically via information_schema so future schemas are covered without
maintenance.

Refuses to touch the canonical org. Dry-run by default.

Usage:
    python -m backend.scripts.cleanup_dev_orphan_orgs            # dry-run
    python -m backend.scripts.cleanup_dev_orphan_orgs --apply    # execute
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

CANONICAL_ORG = "403d8392-ebfa-5890-b740-45da49c556eb"

ORPHAN_ORGS: tuple[str, ...] = (
    "e28fc30c-9d6d-4b21-8e91-cad8696b44fa",
    "07eb6ed0-2d76-4455-90d8-0abcb55628b0",
    "740b907d-fe70-4300-bf41-c3d1e08386d6",
)


def _resolve_sync_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not dsn:
        env_path = Path(__file__).resolve().parents[2] / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("DATABASE_URL_SYNC="):
                    dsn = line.split("=", 1)[1].strip()
                    break
                if line.startswith("DATABASE_URL=") and not dsn:
                    dsn = line.split("=", 1)[1].strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL or DATABASE_URL_SYNC required")
    return dsn.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def _discover_scoped_tables(cur: psycopg.Cursor) -> list[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name = 'organization_id'
          AND table_name NOT LIKE 'v_%'
          AND table_name NOT LIKE 'mv_%'
        ORDER BY table_name
        """
    )
    return [row[0] for row in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="execute deletes (default: dry-run)")
    args = parser.parse_args()

    if CANONICAL_ORG in ORPHAN_ORGS:
        print(f"ABORT: canonical org {CANONICAL_ORG} is in the orphan list.", file=sys.stderr)
        return 2

    dsn = _resolve_sync_dsn()
    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            tables = _discover_scoped_tables(cur)
            print(f"Discovered {len(tables)} RLS-scoped tables.", file=sys.stderr)

            # Disable RLS for the session (superuser / app role). Needed so the
            # script can see and delete rows belonging to arbitrary orgs.
            cur.execute("SET LOCAL row_security = off")

            summary: dict[str, dict[str, int]] = {}
            for table in tables:
                counts: dict[str, int] = {}
                for org_id in ORPHAN_ORGS:
                    stmt_count = sql.SQL("SELECT COUNT(*) FROM {} WHERE organization_id = %s").format(
                        sql.Identifier(table)
                    )
                    cur.execute(stmt_count, (org_id,))
                    n = cur.fetchone()[0]  # type: ignore[index]
                    if n == 0:
                        continue
                    counts[org_id] = n
                    if args.apply:
                        stmt_del = sql.SQL("DELETE FROM {} WHERE organization_id = %s").format(
                            sql.Identifier(table)
                        )
                        cur.execute(stmt_del, (org_id,))
                if counts:
                    summary[table] = counts

            total_rows = sum(n for c in summary.values() for n in c.values())
            report = {
                "mode": "apply" if args.apply else "dry-run",
                "canonical_org_preserved": CANONICAL_ORG,
                "orphan_orgs": list(ORPHAN_ORGS),
                "tables_affected": len(summary),
                "total_rows": total_rows,
                "detail": summary,
            }
            print(json.dumps(report, indent=2))

            if args.apply:
                conn.commit()
                print("COMMITTED", file=sys.stderr)
            else:
                conn.rollback()
                print("ROLLED BACK (dry-run)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
