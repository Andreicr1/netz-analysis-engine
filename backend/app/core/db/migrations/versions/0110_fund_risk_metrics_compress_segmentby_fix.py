"""fund_risk_metrics compress_segmentby fix — organization_id → instrument_id.

Audit 2026-04-11 (docs/audits/Phase-2-Scope-Audit-Investigation-Report.md
§A.1) confirmed fund_risk_metrics was segmented by organization_id at
c3d4e5f6a7b8 L104. The table is global with nullable org; base risk
metrics are written globally by the ``global_risk_metrics`` worker
(lock 900_071) with ``org=NULL`` for the vast majority of rows.
Segmenting by a predominantly-NULL column defeats TimescaleDB
compression — the columnstore cannot form meaningful segment groups
from a single NULL value, so each "segment" degenerates toward per-row
storage.

The correct segmentation is ``instrument_id``, which is always
populated with high cardinality and matches the dominant access
pattern of the screener and entity analytics hot paths
(``WHERE instrument_id = X ORDER BY calc_date DESC``).

``calc_date DESC`` orderby is preserved from c3d4e5f6a7b8 — verified
via ``timescaledb_information.compression_settings``.

Strategy: decompress any already-compressed chunks, alter the
compression setting, recompress. In local dev the decompress step is
a no-op (no compressed chunks yet). In production the compression
policy (30-day age threshold from c3d4e5f6a7b8) may have compressed
older chunks under the wrong segmentby — this migration decompresses
up to the most recent 3 such chunks and recompresses them under the
new key. Older chunks past those top-3 are left compressed under the
legacy key; they age out of query-planner relevance and a later
bulk-recompress job can clean them up when convenient.

Revision ID: 0110_fund_risk_metrics_compress_segmentby_fix
Revises: 0109
Create Date: 2026-04-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0110_fund_risk_metrics_compress_segmentby_fix"
down_revision: str | None = "0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Decompress up to the 3 most recent compressed chunks so the
    #    ALTER TABLE can succeed. ``SET (timescaledb.compress_segmentby = ...)``
    #    is rejected if any chunk is currently compressed under the old
    #    segmentby. In local dev this is typically a no-op.
    op.execute(
        """
        DO $$
        DECLARE
            chunk record;
            decompressed int := 0;
        BEGIN
            FOR chunk IN
                SELECT c.chunk_schema, c.chunk_name
                FROM timescaledb_information.chunks c
                WHERE c.hypertable_name = 'fund_risk_metrics'
                  AND c.is_compressed = true
                ORDER BY c.range_start DESC
                LIMIT 3
            LOOP
                PERFORM decompress_chunk(
                    format('%I.%I', chunk.chunk_schema, chunk.chunk_name)::regclass
                );
                decompressed := decompressed + 1;
            END LOOP;
            RAISE NOTICE 'fund_risk_metrics: decompressed % chunks', decompressed;
        END $$
        """,
    )

    # 2. Alter the compression setting.
    op.execute(
        """
        ALTER TABLE fund_risk_metrics
        SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'instrument_id',
            timescaledb.compress_orderby = 'calc_date DESC'
        )
        """,
    )

    # 3. Recompress the decompressed chunks under the new segmentby.
    #    Scoped to the same "top 3 recent" window so we do not
    #    accidentally recompress chunks we did not touch.
    op.execute(
        """
        DO $$
        DECLARE
            chunk record;
            recompressed int := 0;
        BEGIN
            FOR chunk IN
                SELECT c.chunk_schema, c.chunk_name
                FROM timescaledb_information.chunks c
                WHERE c.hypertable_name = 'fund_risk_metrics'
                  AND c.is_compressed = false
                  AND c.range_end < NOW() - INTERVAL '30 days'
                ORDER BY c.range_start DESC
                LIMIT 3
            LOOP
                PERFORM compress_chunk(
                    format('%I.%I', chunk.chunk_schema, chunk.chunk_name)::regclass
                );
                recompressed := recompressed + 1;
            END LOOP;
            RAISE NOTICE 'fund_risk_metrics: recompressed % chunks', recompressed;
        END $$
        """,
    )


def downgrade() -> None:
    # Mirror of upgrade with the legacy segmentby restored.
    op.execute(
        """
        DO $$
        DECLARE
            chunk record;
        BEGIN
            FOR chunk IN
                SELECT c.chunk_schema, c.chunk_name
                FROM timescaledb_information.chunks c
                WHERE c.hypertable_name = 'fund_risk_metrics'
                  AND c.is_compressed = true
                ORDER BY c.range_start DESC
                LIMIT 3
            LOOP
                PERFORM decompress_chunk(
                    format('%I.%I', chunk.chunk_schema, chunk.chunk_name)::regclass
                );
            END LOOP;
        END $$
        """,
    )

    op.execute(
        """
        ALTER TABLE fund_risk_metrics
        SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'organization_id',
            timescaledb.compress_orderby = 'calc_date DESC'
        )
        """,
    )

    op.execute(
        """
        DO $$
        DECLARE
            chunk record;
        BEGIN
            FOR chunk IN
                SELECT c.chunk_schema, c.chunk_name
                FROM timescaledb_information.chunks c
                WHERE c.hypertable_name = 'fund_risk_metrics'
                  AND c.is_compressed = false
                  AND c.range_end < NOW() - INTERVAL '30 days'
                ORDER BY c.range_start DESC
                LIMIT 3
            LOOP
                PERFORM compress_chunk(
                    format('%I.%I', chunk.chunk_schema, chunk.chunk_name)::regclass
                );
            END LOOP;
        END $$
        """,
    )
