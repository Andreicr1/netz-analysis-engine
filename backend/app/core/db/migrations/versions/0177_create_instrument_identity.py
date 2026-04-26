"""Create instrument_identity table with resolution ENUM and CHECK constraints.

PR-Q11 Phase 1.1 — Instrument Identity Layer foundation.

Canonical identity table for all instrument identifiers (CIK, CUSIP, ISIN,
FIGI, ticker, series_id, class_id, CRD, private fund ID, LEI).

Key design decisions:
- FK ON DELETE RESTRICT (not CASCADE) — catalog re-sync must not destroy
  identity provenance.
- CIK is not UNIQUE at listing/share-class grain.
- ISIN CHECK enforces ISO6166 format only.
- chk_at_least_one_identifier has 3 branches per resolution_status.
- No partial index using NOW() (invalid/unstable in PostgreSQL).

Revision ID: 0177_create_instrument_identity
Revises: 0176_add_asset_class_to_factor_model_fits
Create Date: 2026-04-26
"""
from alembic import op

revision = "0177_create_instrument_identity"
down_revision = "0176_add_asset_class_to_factor_model_fits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- ENUM ---
    op.execute("""
        CREATE TYPE instrument_identity_resolution_status AS ENUM (
            'canonical',
            'candidate',
            'unresolved'
        )
    """)

    # --- TABLE ---
    op.execute("""
        CREATE TABLE instrument_identity (
            instrument_id           UUID PRIMARY KEY
                                    REFERENCES instruments_universe(instrument_id)
                                    ON DELETE RESTRICT,

            -- SEC identifiers
            cik_padded              VARCHAR(10),
            cik_unpadded            VARCHAR(10),
            sec_series_id           VARCHAR(15),
            sec_class_id            VARCHAR(15),
            sec_crd                 VARCHAR(10),
            sec_private_fund_id     VARCHAR(50),

            -- Security identifiers
            cusip_8                 VARCHAR(8),
            cusip_9                 VARCHAR(9),
            isin                    VARCHAR(12),
            sedol                   VARCHAR(7),
            figi                    VARCHAR(12),

            -- Market identifiers
            ticker                  VARCHAR(20),
            ticker_exchange         VARCHAR(20),
            mic                     VARCHAR(4),

            -- Entity identifiers
            lei                     VARCHAR(20),
            esma_manager_id         VARCHAR(20),

            -- Resolution state
            resolution_status       instrument_identity_resolution_status
                                    NOT NULL DEFAULT 'unresolved',
            conflict_state          JSONB NOT NULL DEFAULT '{}'::jsonb,

            -- Provenance
            last_resolved_at        TIMESTAMPTZ,
            identity_sources        JSONB NOT NULL DEFAULT '{}'::jsonb,

            -- Audit
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- CHECK: CIK padded format (10 digits)
            CONSTRAINT chk_cik_padded_format
                CHECK (cik_padded ~ '^[0-9]{10}$' OR cik_padded IS NULL),

            -- CHECK: CIK unpadded format (no leading zeros)
            CONSTRAINT chk_cik_unpadded_format
                CHECK (cik_unpadded ~ '^[1-9][0-9]*$' OR cik_unpadded IS NULL),

            -- CHECK: CIK consistency (R-6)
            CONSTRAINT chk_cik_consistency
                CHECK (
                    cik_unpadded IS NULL
                    OR cik_padded IS NULL
                    OR cik_padded = LPAD(cik_unpadded, 10, '0')
                ),

            -- CHECK: SEC series_id format
            CONSTRAINT chk_sec_series_id_format
                CHECK (sec_series_id ~ '^S[0-9]{9}$' OR sec_series_id IS NULL),

            -- CHECK: SEC class_id format
            CONSTRAINT chk_sec_class_id_format
                CHECK (sec_class_id ~ '^C[0-9]{9}$' OR sec_class_id IS NULL),

            -- CHECK: CUSIP-9 format
            CONSTRAINT chk_cusip_9_format
                CHECK (cusip_9 ~ '^[0-9A-Z]{9}$' OR cusip_9 IS NULL),

            -- CHECK: CUSIP-8 format
            CONSTRAINT chk_cusip_8_format
                CHECK (cusip_8 ~ '^[0-9A-Z]{8}$' OR cusip_8 IS NULL),

            -- CHECK: ISIN ISO6166 format only
            CONSTRAINT chk_isin_iso6166
                CHECK (isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$' OR isin IS NULL),

            -- CHECK: FIGI format
            CONSTRAINT chk_figi_format
                CHECK (figi ~ '^BBG[0-9A-Z]{9}$' OR figi IS NULL),

            -- CHECK: LEI format
            CONSTRAINT chk_lei_format
                CHECK (lei ~ '^[A-Z0-9]{18}[0-9]{2}$' OR lei IS NULL),

            -- CHECK: at least one identifier per resolution status
            CONSTRAINT chk_at_least_one_identifier
                CHECK (
                    (
                        resolution_status = 'canonical'
                        AND (
                            cik_padded IS NOT NULL OR
                            sec_series_id IS NOT NULL OR
                            isin IS NOT NULL OR
                            cusip_9 IS NOT NULL OR
                            ticker IS NOT NULL OR
                            sec_private_fund_id IS NOT NULL OR
                            esma_manager_id IS NOT NULL
                        )
                    )
                    OR (
                        resolution_status = 'candidate'
                        AND (
                            sec_crd IS NOT NULL OR
                            ticker IS NOT NULL OR
                            cik_padded IS NOT NULL OR
                            sec_series_id IS NOT NULL OR
                            sec_private_fund_id IS NOT NULL OR
                            esma_manager_id IS NOT NULL
                        )
                    )
                    OR resolution_status = 'unresolved'
                )
        )
    """)

    # --- NON-UNIQUE REVERSE LOOKUP INDEXES ---
    op.execute("""
        CREATE INDEX ix_identity_cik_padded
            ON instrument_identity(cik_padded)
            WHERE cik_padded IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_cik_unpadded
            ON instrument_identity(cik_unpadded)
            WHERE cik_unpadded IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_isin
            ON instrument_identity(isin)
            WHERE isin IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_ticker
            ON instrument_identity(ticker)
            WHERE ticker IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_ticker_mic
            ON instrument_identity(ticker, mic)
            WHERE ticker IS NOT NULL OR mic IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_cusip_9
            ON instrument_identity(cusip_9)
            WHERE cusip_9 IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_cusip_8
            ON instrument_identity(cusip_8)
            WHERE cusip_8 IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_series_class
            ON instrument_identity(sec_series_id, sec_class_id)
            WHERE sec_series_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_crd
            ON instrument_identity(sec_crd)
            WHERE sec_crd IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_private_fund_id
            ON instrument_identity(sec_private_fund_id)
            WHERE sec_private_fund_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_figi
            ON instrument_identity(figi)
            WHERE figi IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_lei
            ON instrument_identity(lei)
            WHERE lei IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_esma_manager_id
            ON instrument_identity(esma_manager_id)
            WHERE esma_manager_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_identity_last_resolved_at
            ON instrument_identity(last_resolved_at)
    """)
    op.execute("""
        CREATE INDEX ix_identity_conflict_state_gin
            ON instrument_identity USING GIN(conflict_state)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS instrument_identity")
    op.execute("DROP TYPE IF EXISTS instrument_identity_resolution_status")
