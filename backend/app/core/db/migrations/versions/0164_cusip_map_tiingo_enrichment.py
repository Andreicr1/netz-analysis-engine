"""sec_cusip_ticker_map — Tiingo fundamentals enrichment columns.

Extends sec_cusip_ticker_map to store the Tiingo /fundamentals/meta
payload used by PR-Q4.1 holdings-rail enrichment worker. All columns
nullable — existing rows remain valid, the worker backfills over time.

New columns:
    sic_code              INTEGER          — Tiingo sicCode (SEC-native)
    tiingo_industry       TEXT             — Tiingo industry (GICS-approx granular)
    tiingo_meta_fetched_at TIMESTAMPTZ     — last Tiingo meta call timestamp

`gics_sector` (already on the table) becomes the write target for Tiingo's
`sector` field. Layered storage — SIC for compliance/research, GICS-approx
for display in DD ch.4 + matview.

depends_on: 0163 (mv_nport_sector_attribution).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0164_cusip_map_tiingo_enrichment"
down_revision = "0163_mv_nport_sector_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sec_cusip_ticker_map",
        sa.Column("sic_code", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sec_cusip_ticker_map",
        sa.Column("tiingo_industry", sa.Text(), nullable=True),
    )
    op.add_column(
        "sec_cusip_ticker_map",
        sa.Column(
            "tiingo_meta_fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Partial index for the worker's "needs-enrichment" scan: equity rows with
    # a ticker resolved but no GICS sector yet. Tight — only covers the working
    # set, not the full 33k-row catalog.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cusip_map_needs_tiingo_enrichment "
        "ON sec_cusip_ticker_map (ticker) "
        "WHERE ticker IS NOT NULL AND gics_sector IS NULL",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cusip_map_needs_tiingo_enrichment")
    op.drop_column("sec_cusip_ticker_map", "tiingo_meta_fetched_at")
    op.drop_column("sec_cusip_ticker_map", "tiingo_industry")
    op.drop_column("sec_cusip_ticker_map", "sic_code")
