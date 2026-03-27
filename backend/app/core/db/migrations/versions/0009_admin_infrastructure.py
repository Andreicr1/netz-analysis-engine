"""Admin infrastructure: tenant_assets, prompt_overrides, prompt_override_versions.

Creates 3 new tables for multi-tenant branding and prompt customization.
Seeds default branding config into vertical_config_defaults for both verticals.

depends_on: 0008 (wealth_analytical_models).
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# ── New tables that need RLS ──────────────────────────────────────
_RLS_TABLES = [
    "tenant_assets",
    "prompt_overrides",
    "prompt_override_versions",
]

# ── Default branding config (seeded for both verticals) ───────────
_DEFAULT_BRANDING = {
    "company_name": "Netz Capital",
    "tagline": "Institutional Investment Intelligence",
    "logo_light_url": "/api/v1/assets/tenant/{org_slug}/logo_light",
    "logo_dark_url": "/api/v1/assets/tenant/{org_slug}/logo_dark",
    "favicon_url": "/api/v1/assets/tenant/{org_slug}/favicon",
    "primary_color": "#1a1a2e",
    "accent_color": "#e94560",
    "font_family": "Inter, system-ui, sans-serif",
    "report_header": "Netz Capital",
    "report_footer": "Confidential — For Authorized Recipients Only",
    "email_from_name": "Netz Capital",
}


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  PHASE A: New tables
    # ═══════════════════════════════════════════════════════════════

    # ── tenant_assets ─────────────────────────────────────────────
    op.create_table(
        "tenant_assets",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True,
        ),
        sa.Column("asset_type", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
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
        sa.UniqueConstraint(
            "organization_id", "asset_type", name="uq_tenant_assets_org_type",
        ),
    )

    # CHECK: asset_type enum
    op.execute("""
        ALTER TABLE tenant_assets
        ADD CONSTRAINT chk_tenant_asset_type
        CHECK (asset_type IN ('logo_light', 'logo_dark', 'favicon'))
    """)

    # CHECK: content_type enum
    op.execute("""
        ALTER TABLE tenant_assets
        ADD CONSTRAINT chk_tenant_asset_content_type
        CHECK (content_type IN (
            'image/png', 'image/jpeg', 'image/x-icon', 'image/vnd.microsoft.icon'
        ))
    """)

    # ── prompt_overrides ──────────────────────────────────────────
    op.create_table(
        "prompt_overrides",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", sa.Uuid(as_uuid=True), nullable=True, index=True,
        ),
        sa.Column("vertical", sa.Text(), nullable=False),
        sa.Column("template_name", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1",
        ),
        sa.Column("updated_by", sa.Text(), nullable=False),
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
        sa.UniqueConstraint(
            "organization_id",
            "vertical",
            "template_name",
            name="uq_prompt_overrides_org_vertical_template",
        ),
    )

    # ── prompt_override_versions ──────────────────────────────────
    op.create_table(
        "prompt_override_versions",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "prompt_override_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("prompt_overrides.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ═══════════════════════════════════════════════════════════════
    #  PHASE B: RLS on all new tables
    # ═══════════════════════════════════════════════════════════════

    # ── tenant_assets: standard org isolation ─────────────────────
    op.execute("ALTER TABLE tenant_assets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_assets FORCE ROW LEVEL SECURITY")
    # MUST use subselect pattern — see CLAUDE.md "RLS subselect" rule
    op.execute("""
        CREATE POLICY org_isolation ON tenant_assets
            USING (organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid)
            WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid)
    """)

    # ── prompt_overrides: org-specific rows + global rows (org_id IS NULL) ──
    op.execute("ALTER TABLE prompt_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_overrides FORCE ROW LEVEL SECURITY")
    # Policy for org-scoped rows: standard org isolation
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

    # ── prompt_override_versions: inherit via FK to prompt_overrides ──
    op.execute("ALTER TABLE prompt_override_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_override_versions FORCE ROW LEVEL SECURITY")
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

    # ═══════════════════════════════════════════════════════════════
    #  PHASE C: Expand config_type constraint + seed default branding
    # ═══════════════════════════════════════════════════════════════
    _CONFIG_TYPES_V3 = (
        "'calibration', 'scoring', 'blocks', 'chapters', "
        "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
        "'evaluation', 'macro_intelligence', 'governance_policy', 'branding'"
    )
    for table in ("vertical_config_defaults", "vertical_config_overrides"):
        constraint = f"ck_{'defaults' if 'defaults' in table else 'overrides'}_config_type"
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK (config_type IN ({_CONFIG_TYPES_V3}))")

    import json

    branding_json = json.dumps(_DEFAULT_BRANDING)
    bind = op.get_bind()
    for vertical in ("private_credit", "liquid_funds"):
        bind.execute(
            sa.text("""
                INSERT INTO vertical_config_defaults (vertical, config_type, config, description, version)
                VALUES (:vertical, 'branding', :config, :description, 1)
                ON CONFLICT ON CONSTRAINT uq_defaults_vertical_type DO NOTHING
            """),
            {
                "vertical": vertical,
                "config": branding_json,
                "description": f"Default branding and white-label settings for {vertical}",
            },
        )


def downgrade() -> None:
    # ── Remove seeded branding config ─────────────────────────────
    op.execute("""
        DELETE FROM vertical_config_defaults
        WHERE config_type = 'branding'
        AND vertical IN ('private_credit', 'liquid_funds')
    """)

    # ── Remove RLS from new tables ────────────────────────────────
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table}")
        op.execute(f"DROP POLICY IF EXISTS parent_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # ── Drop new tables (children first) ──────────────────────────
    op.drop_table("prompt_override_versions")
    op.drop_table("prompt_overrides")
    op.drop_table("tenant_assets")
