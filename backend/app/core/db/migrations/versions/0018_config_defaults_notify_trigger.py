"""Add pg_notify trigger on vertical_config_defaults for cache invalidation.

Migration 0015 added notify_config_change() trigger only on
vertical_config_overrides. Admin writes to vertical_config_defaults via
put_default() were silently skipping cache invalidation. This migration
adds a dedicated trigger on vertical_config_defaults that fires on
INSERT, UPDATE, and DELETE, sending organization_id as null to signal
that all tenants should invalidate their caches for the affected
vertical/config_type combination.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # vertical_config_defaults has no organization_id column, so we need
    # a separate trigger function that sends null for organization_id.
    # This tells ConfigService listeners "invalidate ALL tenants for this
    # vertical+config_type" rather than a single tenant override.
    op.execute("""
        CREATE OR REPLACE FUNCTION notify_config_default_change() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                PERFORM pg_notify('config_changed', json_build_object(
                    'vertical', OLD.vertical,
                    'config_type', OLD.config_type,
                    'organization_id', NULL
                )::text);
                RETURN OLD;
            ELSE
                PERFORM pg_notify('config_changed', json_build_object(
                    'vertical', NEW.vertical,
                    'config_type', NEW.config_type,
                    'organization_id', NULL
                )::text);
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS config_default_notify ON vertical_config_defaults;
        CREATE TRIGGER config_default_notify
            AFTER INSERT OR UPDATE OR DELETE ON vertical_config_defaults
            FOR EACH ROW EXECUTE FUNCTION notify_config_default_change();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS config_default_notify ON vertical_config_defaults")
    op.execute("DROP FUNCTION IF EXISTS notify_config_default_change()")
