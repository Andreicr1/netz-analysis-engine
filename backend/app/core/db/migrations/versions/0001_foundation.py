"""Foundation: extensions, RLS functions, audit infrastructure."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    # RLS fail-closed guard function
    op.execute("""
        CREATE OR REPLACE FUNCTION require_org_context()
        RETURNS uuid AS $$
        BEGIN
            IF current_setting('app.current_organization_id', true) IS NULL THEN
                RAISE EXCEPTION 'app.current_organization_id not set — fail closed';
            END IF;
            RETURN current_setting('app.current_organization_id')::uuid;
        END;
        $$ LANGUAGE plpgsql STABLE;
    """)

    # Audit events table
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            organization_id UUID NOT NULL,
            fund_id UUID,
            actor_id VARCHAR(128),
            request_id VARCHAR(128),
            action VARCHAR(128) NOT NULL,
            entity_type VARCHAR(64),
            entity_id VARCHAR(128),
            before_state JSONB,
            after_state JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_audit_events_org ON audit_events (organization_id)")
    op.execute("CREATE INDEX ix_audit_events_entity ON audit_events (entity_type, entity_id)")
    op.execute("CREATE INDEX ix_audit_events_action ON audit_events (action, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_events")
    op.execute("DROP FUNCTION IF EXISTS require_org_context()")
