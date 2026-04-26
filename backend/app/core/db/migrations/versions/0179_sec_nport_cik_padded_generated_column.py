"""sec_nport_holdings cik_padded via trigger (TimescaleDB compression-safe)

PR-Q11 Phase 5. ``sec_nport_holdings.cik`` is stored mixed in DB local:
~1,069 unpadded (4-7 chars) and ~146 padded (10 chars). Joins against
``instruments_universe.attributes->>'sec_cik'`` (also mixed) require
``LTRIM`` or ``IN (padded, unpadded)`` patterns that disable the btree
index on cik.

Original plan was a STORED generated column ``cik_padded``, but
TimescaleDB hypertables with columnstore (compression policy) enabled
reject ``ADD COLUMN ... GENERATED ALWAYS AS ... STORED`` even when no
chunks are actually compressed yet. Validated empirically on DB local:

    ERROR: cannot add column with constraints to a hypertable that has
           columnstore enabled

Falling back to plan B from plan v2 §3.5: a regular column populated
by a BEFORE INSERT OR UPDATE trigger plus a one-shot backfill UPDATE
for existing rows. Functionally equivalent for read-side joins,
preserves write-path correctness, and survives compression policy.

Validation gate (run before applying):
  SELECT COUNT(*) FILTER (WHERE is_compressed)
  FROM timescaledb_information.chunks
  WHERE hypertable_name = 'sec_nport_holdings';

Confirmed 0/30 chunks compressed in DB local on 2026-04-26. Backfill
UPDATE on uncompressed chunks is safe; if a future deployment finds
already-compressed chunks they must be decompressed before this
migration runs (or backfill executed per-chunk after decompression).

Revision ID: 0179_sec_nport_cik_padded_generated_column
Revises: 0178_create_instrument_identity_history
Create Date: 2026-04-26
"""
from alembic import op

revision = "0179_sec_nport_cik_padded_generated_column"
down_revision = "0178_create_instrument_identity_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sec_nport_holdings
        ADD COLUMN cik_padded VARCHAR(10)
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_sec_nport_holdings_cik_padded()
        RETURNS trigger AS $$
        BEGIN
            NEW.cik_padded := LPAD(NEW.cik, 10, '0');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        """
        CREATE TRIGGER sec_nport_holdings_cik_padded_biu
        BEFORE INSERT OR UPDATE OF cik ON sec_nport_holdings
        FOR EACH ROW EXECUTE FUNCTION trg_sec_nport_holdings_cik_padded()
        """
    )

    op.execute(
        """
        UPDATE sec_nport_holdings
        SET cik_padded = LPAD(cik, 10, '0')
        WHERE cik_padded IS NULL
        """
    )

    op.execute(
        """
        CREATE INDEX ix_sec_nport_holdings_cik_padded
        ON sec_nport_holdings(cik_padded)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sec_nport_holdings_cik_padded")
    op.execute(
        "DROP TRIGGER IF EXISTS sec_nport_holdings_cik_padded_biu ON sec_nport_holdings"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS trg_sec_nport_holdings_cik_padded()"
    )
    op.execute("ALTER TABLE sec_nport_holdings DROP COLUMN IF EXISTS cik_padded")
