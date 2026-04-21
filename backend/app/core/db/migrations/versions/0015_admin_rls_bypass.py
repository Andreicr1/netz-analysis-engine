"""Admin RLS bypass + audit log + config change notification trigger.

Adds admin_mode bypass to RLS policies on admin tables.
Creates admin_audit_log for admin write audit trail.
Creates pg_notify trigger on vertical_config_overrides for cache invalidation.
"""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Update RLS policies to include admin bypass ──
    # tenant_assets
    op.execute("DROP POLICY IF EXISTS org_isolation ON tenant_assets")
    op.execute("""
        CREATE POLICY org_isolation ON tenant_assets
            USING (
                organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                OR (SELECT current_setting('app.admin_mode', true)) = 'true'
            )
            WITH CHECK (
                organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                OR (SELECT current_setting('app.admin_mode', true)) = 'true'
            )
    """)

    # prompt_overrides
    op.execute("DROP POLICY IF EXISTS org_isolation ON prompt_overrides")
    op.execute("""
        CREATE POLICY org_isolation ON prompt_overrides
            USING (
                organization_id IS NULL
                OR organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                OR (SELECT current_setting('app.admin_mode', true)) = 'true'
            )
            WITH CHECK (
                organization_id IS NULL
                OR organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                OR (SELECT current_setting('app.admin_mode', true)) = 'true'
            )
    """)

    # prompt_override_versions
    op.execute("DROP POLICY IF EXISTS parent_isolation ON prompt_override_versions")
    op.execute("""
        CREATE POLICY parent_isolation ON prompt_override_versions
            USING (
                prompt_override_id IN (
                    SELECT id FROM prompt_overrides
                    WHERE organization_id IS NULL
                    OR organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                    OR (SELECT current_setting('app.admin_mode', true)) = 'true'
                )
            )
    """)

    # vertical_config_overrides — CRITICAL: missing from original, blocks all config admin ops
    op.execute("DROP POLICY IF EXISTS org_isolation ON vertical_config_overrides")
    op.execute("""
        CREATE POLICY org_isolation ON vertical_config_overrides
            USING (
                organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                OR (SELECT current_setting('app.admin_mode', true)) = 'true'
            )
            WITH CHECK (
                organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                OR (SELECT current_setting('app.admin_mode', true)) = 'true'
            )
    """)

    # ── admin_audit_log table (no RLS — admin-only, cross-tenant) ──
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("target_org_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("before_hash", sa.Text(), nullable=True),
        sa.Column("after_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── pg_notify trigger on vertical_config_overrides ──
    op.execute("""
        CREATE OR REPLACE FUNCTION notify_config_change() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                PERFORM pg_notify('config_changed', json_build_object(
                    'vertical', OLD.vertical,
                    'config_type', OLD.config_type,
                    'organization_id', OLD.organization_id::text
                )::text);
                RETURN OLD;
            ELSE
                PERFORM pg_notify('config_changed', json_build_object(
                    'vertical', NEW.vertical,
                    'config_type', NEW.config_type,
                    'organization_id', NEW.organization_id::text
                )::text);
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER config_override_notify
            AFTER INSERT OR UPDATE OR DELETE ON vertical_config_overrides
            FOR EACH ROW EXECUTE FUNCTION notify_config_change();
    """)


def downgrade() -> None:
    # Remove trigger
    op.execute("DROP TRIGGER IF EXISTS config_override_notify ON vertical_config_overrides")
    op.execute("DROP FUNCTION IF EXISTS notify_config_change()")

    # Drop audit log
    op.drop_table("admin_audit_log")

    # Restore original RLS policies (without admin bypass)
    op.execute("DROP POLICY IF EXISTS org_isolation ON tenant_assets")
    op.execute("""
        CREATE POLICY org_isolation ON tenant_assets
            USING (organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid)
            WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid)
    """)

    op.execute("DROP POLICY IF EXISTS org_isolation ON prompt_overrides")
    op.execute("""
        CREATE POLICY org_isolation ON prompt_overrides
            USING (
                organization_id IS NULL
                OR organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
            )
            WITH CHECK (
                organization_id IS NULL
                OR organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
            )
    """)

    op.execute("DROP POLICY IF EXISTS parent_isolation ON prompt_override_versions")
    op.execute("""
        CREATE POLICY parent_isolation ON prompt_override_versions
            USING (
                prompt_override_id IN (
                    SELECT id FROM prompt_overrides
                    WHERE organization_id IS NULL
                    OR organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                )
            )
    """)

    # Restore vertical_config_overrides to original policy (without admin bypass)
    op.execute("DROP POLICY IF EXISTS org_isolation ON vertical_config_overrides")
    op.execute("""
        CREATE POLICY org_isolation ON vertical_config_overrides
            USING (organization_id = (SELECT current_setting('app.current_organization_id'))::uuid)
    """)
