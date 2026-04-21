"""Add org_slug to tenant_assets for public asset serving.
Fix prompt_override_versions RLS: add missing WITH CHECK clause.

depends_on: 0009 (admin_infrastructure).
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Add org_slug to tenant_assets ────────────────────────────────
    op.add_column(
        "tenant_assets",
        sa.Column("org_slug", sa.Text(), nullable=True),
    )
    op.create_index("ix_tenant_assets_org_slug", "tenant_assets", ["org_slug"])

    # ── Fix prompt_override_versions RLS: add WITH CHECK clause ──────
    # The original policy only had USING (read path). INSERT requires
    # WITH CHECK when FORCE ROW LEVEL SECURITY is enabled.
    op.execute("DROP POLICY IF EXISTS parent_isolation ON prompt_override_versions")
    # MUST use subselect pattern — see CLAUDE.md "RLS subselect" rule
    op.execute("""
        CREATE POLICY parent_isolation ON prompt_override_versions
            USING (
                prompt_override_id IN (
                    SELECT id FROM prompt_overrides
                    WHERE organization_id IS NULL
                    OR organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                )
            )
            WITH CHECK (
                prompt_override_id IN (
                    SELECT id FROM prompt_overrides
                    WHERE organization_id IS NULL
                    OR organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
                )
            )
    """)


def downgrade() -> None:
    # ── Restore original RLS policy (USING only) ─────────────────────
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

    # ── Remove org_slug from tenant_assets ───────────────────────────
    op.drop_index("ix_tenant_assets_org_slug", table_name="tenant_assets")
    op.drop_column("tenant_assets", "org_slug")
