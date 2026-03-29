"""Create instruments_org table and migrate org-scoped columns.

Revision ID: 0068
Revises: 0067_insider_transactions
"""

revision = "0068_instruments_org"
down_revision = "0067_insider_transactions"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    # 1. Create instruments_org — tenant-scoped selection from global catalog
    op.execute("""
        CREATE TABLE instruments_org (
            id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            organization_id  UUID NOT NULL,
            instrument_id    UUID NOT NULL
                REFERENCES instruments_universe(instrument_id) ON DELETE CASCADE,
            block_id         VARCHAR(80)
                REFERENCES allocation_blocks(block_id),
            approval_status  VARCHAR(20) NOT NULL DEFAULT 'pending',
            selected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, instrument_id)
        )
    """)
    op.execute("""
        CREATE INDEX ix_instruments_org_organization_id
        ON instruments_org (organization_id)
    """)
    op.execute("""
        CREATE INDEX ix_instruments_org_instrument_id
        ON instruments_org (instrument_id)
    """)
    op.execute("""
        CREATE INDEX ix_instruments_org_block_id
        ON instruments_org (block_id)
    """)

    # 2. RLS policy
    op.execute("ALTER TABLE instruments_org ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY instruments_org_rls ON instruments_org
        USING (organization_id = (SELECT current_setting('app.current_organization_id'))::uuid)
    """)

    # 3. Migrate existing data from instruments_universe → instruments_org
    op.execute("""
        INSERT INTO instruments_org (organization_id, instrument_id, block_id, approval_status, selected_at)
        SELECT organization_id, instrument_id, block_id, COALESCE(approval_status, 'pending'), created_at
        FROM instruments_universe
        WHERE organization_id IS NOT NULL
        ON CONFLICT (organization_id, instrument_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS instruments_org CASCADE")
