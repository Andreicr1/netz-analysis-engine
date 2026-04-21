"""Convert wealth_vector_chunks to hypertable with compression.

Audit 2026-04-11 §A.3 confirmed ``wealth_vector_chunks`` was a
regular table with no compression. With 16 embedding sources
(ADV brochures, ESMA funds, SEC filings, DD chapters, macro
reviews, etc.) the corpus grows monotonically and storage bloats
without TimescaleDB columnar compression.

Target shape:
  time column       : updated_at
  chunk interval    : 3 months
  compress_segmentby: source_type (matches pgvector_search_service
                     WHERE-clause filters; verified 16 distinct
                     values in local dev — healthy low cardinality)
  compress_orderby  : updated_at DESC
  compression policy: compress chunks older than 3 months

PRIMARY KEY restructure — REQUIRED by the hypertable conversion:

  The existing PRIMARY KEY (id) is incompatible with TimescaleDB
  partitioning: any unique/primary-key constraint on a hypertable
  MUST include the partitioning column (here: updated_at). Options:

    (a) Extend PK to (id, updated_at) — preserves uniqueness but
        the existing worker upsert (``_batch_upsert`` in
        wealth_embedding_worker) relies on
        ``ON CONFLICT (id) DO UPDATE`` which requires a unique
        index on (id) alone. A composite PK would force-silently
        turn every re-embed into a new row, leaving stale rows
        behind — a correctness regression.

    (b) Drop the PK entirely. Rely on worker-level batch dedupe
        (already present at
        wealth_embedding_worker._batch_upsert L173-179) and
        switch the worker from ON CONFLICT-DO-UPDATE to
        DELETE-BY-ID + INSERT. Preserves "one logical row per
        id" without needing a DB-level unique constraint.

  Option (b) is shipped — it is atomic with the worker change
  in the same commit. See ``_batch_upsert`` in
  ``backend/app/domains/wealth/workers/wealth_embedding_worker.py``
  (refactored in this same commit).

  A non-unique btree index on ``(id)`` is created instead so
  the DELETE-BY-ID lookup stays O(log n) and LEFT JOIN scans
  used by the worker's per-source discovery queries remain fast.

updated_at NOT NULL:
  TimescaleDB requires the partitioning column to be NOT NULL.
  Local dev verified 0/153,664 rows have NULL updated_at (the
  column has ``DEFAULT now()`` since migration 0059). The
  migration promotes it to NOT NULL before calling
  create_hypertable.

migrate_data=true:
  ``create_hypertable`` with migrate_data copies existing rows
  into the newly-created chunks during conversion. Cannot run
  inside a transaction block — the migration uses the same
  psycopg autocommit pattern as 0049 and c3d4e5f6a7b8.

HNSW index rebuild:
  Local dev verified ``create_hypertable`` with migrate_data drops
  the pre-existing pgvector HNSW index
  (``wealth_vector_chunks_embedding_hnsw``) as part of the table
  rewrite. The migration rebuilds it after compression policy
  attachment. The build runs with
  ``max_parallel_maintenance_workers = 0`` and a bounded
  ``maintenance_work_mem`` so it fits within typical Docker
  ``/dev/shm`` budgets (local dev default is 64 MB). Production
  deployments with larger shared memory will build faster.

Forward-only:
  TimescaleDB does not support reverting a hypertable back to
  a regular table. This migration's downgrade raises
  NotImplementedError. To revert, restore from backup.

Revision ID: 0114_wealth_vector_chunks_hypertable
Revises: 0113_nav_monthly_returns_agg_unique_index
Create Date: 2026-04-11
"""

import os
from collections.abc import Sequence

import psycopg

from alembic import op

revision: str = "0114_wealth_vector_chunks_hypertable"
down_revision: str | None = "0113_nav_monthly_returns_agg_unique_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _autocommit_conninfo() -> str:
    """Resolve a psycopg-compatible connection string for autocommit DDL."""
    sync_url = os.getenv("DATABASE_URL_SYNC", "")
    if sync_url:
        return sync_url.replace("+psycopg", "")
    return op.get_bind().connection.dbapi_connection.info.dsn


def upgrade() -> None:
    # 1. Prepare schema inside the normal transaction: promote
    #    updated_at to NOT NULL, drop the legacy PK on (id), add
    #    a plain btree index on (id) for fast DELETE-BY-ID.
    op.execute(
        """
        UPDATE wealth_vector_chunks
           SET updated_at = COALESCE(updated_at, created_at, NOW())
         WHERE updated_at IS NULL
        """,
    )
    op.execute("ALTER TABLE wealth_vector_chunks ALTER COLUMN updated_at SET NOT NULL")

    op.execute("ALTER TABLE wealth_vector_chunks DROP CONSTRAINT wealth_vector_chunks_pkey")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_wealth_vector_chunks_id
        ON wealth_vector_chunks (id)
        """,
    )

    # 2. Commit the prep and switch to an autocommit connection for
    #    create_hypertable(migrate_data => true) + compression DDL.
    conninfo = _autocommit_conninfo()
    op.get_bind().connection.dbapi_connection.commit()

    with psycopg.connect(conninfo, autocommit=True) as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT create_hypertable(
                'wealth_vector_chunks',
                'updated_at',
                chunk_time_interval => INTERVAL '3 months',
                migrate_data        => true,
                if_not_exists       => true
            )
            """,
        )

        cursor.execute(
            """
            ALTER TABLE wealth_vector_chunks SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'source_type',
                timescaledb.compress_orderby   = 'updated_at DESC'
            )
            """,
        )

        cursor.execute(
            """
            SELECT add_compression_policy(
                'wealth_vector_chunks',
                INTERVAL '3 months',
                if_not_exists => true
            )
            """,
        )

        # 3. Rebuild the pgvector HNSW index that was dropped by the
        #    migrate_data conversion. Uses serial build + bounded
        #    maintenance_work_mem so it fits within typical Docker
        #    /dev/shm budgets (local dev default is 64 MB).
        #    Production deployments with larger shared memory will
        #    build faster via increased maintenance_work_mem.
        cursor.execute("SET max_parallel_maintenance_workers = 0")
        cursor.execute("SET maintenance_work_mem = '512MB'")
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS wealth_vector_chunks_embedding_hnsw
            ON wealth_vector_chunks
            USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 64)
            """,
        )

        cursor.close()


def downgrade() -> None:
    # TimescaleDB does not support reverting a hypertable back to a
    # regular table. This migration is intentionally forward-only —
    # dropping compression would leave data trapped in chunk tables
    # that a regular DROP CONSTRAINT / REINDEX cannot cleanly unwind
    # without data loss risk.
    raise NotImplementedError(
        "0114_wealth_vector_chunks_hypertable is forward-only. "
        "TimescaleDB cannot revert a hypertable to a regular table "
        "while data is present. To revert, restore from backup.",
    )
