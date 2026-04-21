"""Create audit_events table with RLS policy.

Stores immutable entity-level audit trail (CREATE, UPDATE, DELETE) with
optional before/after JSONB snapshots. RLS-scoped by organization_id
using the standard subselect pattern.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Drop legacy audit_events from 0001 (no RLS, fewer columns) ──
    op.execute("DROP TABLE IF EXISTS audit_events CASCADE")

    # ── audit_events table ─────────────────────────────────────────
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "fund_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "access_level",
            sa.String(32),
            nullable=False,
            server_default="internal",
        ),
        sa.Column("actor_id", sa.String(128), nullable=False, index=True),
        sa.Column(
            "actor_roles",
            sa.ARRAY(sa.Text),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("action", sa.String(32), nullable=False, index=True),
        sa.Column("entity_type", sa.String(64), nullable=False, index=True),
        sa.Column("entity_id", sa.String(128), nullable=False, index=True),
        sa.Column("before_state", JSONB, nullable=True),
        sa.Column("after_state", JSONB, nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
    )

    # ── Composite index for common query patterns ──────────────────
    op.create_index(
        "ix_audit_events_org_entity",
        "audit_events",
        ["organization_id", "entity_type", "created_at"],
    )

    # ── RLS: standard org isolation with subselect pattern ─────────
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY org_isolation ON audit_events
            USING (organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid)
            WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS org_isolation ON audit_events")
    op.execute("ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_audit_events_org_entity", table_name="audit_events")
    op.drop_table("audit_events")
