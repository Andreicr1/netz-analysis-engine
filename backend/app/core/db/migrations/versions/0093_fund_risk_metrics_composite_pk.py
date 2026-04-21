"""fund_risk_metrics: composite key with organization_id (P0-1 fix)

Revision ID: 0093_fund_risk_metrics_composite_pk
Revises: 0092_wealth_library_triggers
Create Date: 2026-04-07

P0-1 — fund_risk_metrics PK was (instrument_id, calc_date), causing the
two writers (run_global_risk_metrics with org_id=NULL, run_risk_calc
with org_id=<tenant>) to clobber each other's rows on UPSERT. The last
worker to run owned the row's organization_id; metrics shown to a tenant
could silently belong to a *different* tenant after another worker ran.

Fix: drop the old PK, create a UNIQUE INDEX with NULLS NOT DISTINCT
(PG 15+, available on Timescale Cloud PG 16) over
(instrument_id, calc_date, organization_id). NULLS NOT DISTINCT means
two NULL org rows are treated as duplicates, so there is exactly one
global row per (instrument_id, calc_date), coexisting with up to N
tenant-scoped rows.

fund_risk_metrics is a TimescaleDB hypertable (c3d4e5f6a7b8) with a
30-day compression policy. Compressed chunks block constraint changes,
so we decompress all chunks first (idempotent on uncompressed chunks).
The compression policy itself is unchanged and will re-compress chunks
in the background.

NOTE: run during a low-traffic window in production. Decompression
rewrites historical chunks and is I/O heavy.
"""

import logging

from sqlalchemy import text

from alembic import op

logger = logging.getLogger(__name__)

revision = "0093_fund_risk_metrics_composite_pk"
down_revision = "0092_wealth_library_triggers"
branch_labels = None
depends_on = None


def _has_timescaledb(bind) -> bool:
    return bind.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'"),
    ).scalar() is not None


def upgrade() -> None:
    bind = op.get_bind()

    if _has_timescaledb(bind):
        # Decompress every chunk so the constraint change can proceed.
        # if_compressed => true makes this a no-op for already-uncompressed chunks.
        bind.execute(
            text(
                "SELECT decompress_chunk(c, true) "
                "FROM show_chunks('fund_risk_metrics') c",
            ),
        )

    bind.execute(
        text(
            "ALTER TABLE fund_risk_metrics "
            "DROP CONSTRAINT IF EXISTS fund_risk_metrics_pkey",
        ),
    )

    bind.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_fund_risk_metrics_pk "
            "ON fund_risk_metrics (instrument_id, calc_date, organization_id) "
            "NULLS NOT DISTINCT",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_timescaledb(bind):
        bind.execute(
            text(
                "SELECT decompress_chunk(c, true) "
                "FROM show_chunks('fund_risk_metrics') c",
            ),
        )

    # Collapse duplicates: keep the org-scoped row when one exists, else NULL row.
    bind.execute(
        text(
            "DELETE FROM fund_risk_metrics frm1 "
            "WHERE frm1.organization_id IS NULL "
            "  AND EXISTS (SELECT 1 FROM fund_risk_metrics frm2 "
            "              WHERE frm2.instrument_id = frm1.instrument_id "
            "                AND frm2.calc_date = frm1.calc_date "
            "                AND frm2.organization_id IS NOT NULL)",
        ),
    )

    bind.execute(text("DROP INDEX IF EXISTS ux_fund_risk_metrics_pk"))
    bind.execute(
        text(
            "ALTER TABLE fund_risk_metrics "
            "ADD CONSTRAINT fund_risk_metrics_pkey "
            "PRIMARY KEY (instrument_id, calc_date)",
        ),
    )
