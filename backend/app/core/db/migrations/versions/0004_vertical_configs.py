"""Vertical configuration tables + seed data.

Creates vertical_config_defaults (global, no RLS) and vertical_config_overrides
(tenant-scoped, with RLS). Seeds from existing YAML files.

Audit table + triggers deferred to Sprint 5-6 (migration 0005).
"""

import json
from pathlib import Path

import sqlalchemy as sa
import yaml
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# ── YAML seed file paths (relative to project root) ─────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[6]  # backend/app/core/db/migrations/versions → project root

_SEEDS: list[dict] = [
    {
        "vertical": "liquid_funds",
        "config_type": "calibration",
        "yaml_path": "calibration/config/limits.yaml",
        "description": "CVaR limits, regime thresholds, drift bands (OFR-calibrated)",
    },
    {
        "vertical": "liquid_funds",
        "config_type": "portfolio_profiles",
        "yaml_path": "calibration/config/profiles.yaml",
        "description": "Model portfolio profiles (Conservative/Moderate/Growth)",
    },
    {
        "vertical": "liquid_funds",
        "config_type": "scoring",
        "yaml_path": "calibration/config/scoring.yaml",
        "description": "Fund scoring weights (return, risk, drawdown, IR, flows, Lipper)",
    },
    {
        "vertical": "liquid_funds",
        "config_type": "blocks",
        "yaml_path": "calibration/config/blocks.yaml",
        "description": "Allocation block catalog (geography x asset class → ETF proxy)",
    },
    {
        "vertical": "private_credit",
        "config_type": "chapters",
        "yaml_path": "profiles/private_credit/profile.yaml",
        "description": "IC memo chapter structure (14 chapters)",
    },
    {
        "vertical": "private_credit",
        "config_type": "calibration",
        "yaml_path": "calibration/seeds/private_credit/calibration.yaml",
        "description": "Credit calibration defaults (Moody's, S&P, Basel III sources)",
    },
    {
        "vertical": "private_credit",
        "config_type": "scoring",
        "yaml_path": "calibration/seeds/private_credit/scoring.yaml",
        "description": "Credit deal scoring weights",
    },
]


def _load_yaml(relative_path: str) -> dict:
    """Load a YAML file and return its content as dict."""
    full_path = _PROJECT_ROOT / relative_path
    with open(full_path) as f:
        return yaml.safe_load(f)


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  TABLE 1: vertical_config_defaults (no RLS — global)
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "vertical_config_defaults",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("vertical", sa.String(50), nullable=False),
        sa.Column("config_type", sa.String(50), nullable=False),
        sa.Column("config", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("guardrails", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.UniqueConstraint("vertical", "config_type", name="uq_defaults_vertical_type"),
    )

    # CHECK constraints on text columns — prevent typos
    op.execute("""
        ALTER TABLE vertical_config_defaults
        ADD CONSTRAINT ck_defaults_vertical
        CHECK (vertical IN ('private_credit', 'liquid_funds'))
    """)
    op.execute("""
        ALTER TABLE vertical_config_defaults
        ADD CONSTRAINT ck_defaults_config_type
        CHECK (config_type IN (
            'calibration', 'scoring', 'blocks', 'chapters',
            'portfolio_profiles', 'prompts', 'model_routing', 'tone', 'evaluation'
        ))
    """)
    # Ensure config is a JSON object, not array/scalar
    op.execute("""
        ALTER TABLE vertical_config_defaults
        ADD CONSTRAINT ck_defaults_config_object
        CHECK (jsonb_typeof(config) = 'object')
    """)

    # ═══════════════════════════════════════════════════════════════
    #  TABLE 2: vertical_config_overrides (with RLS)
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "vertical_config_overrides",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("vertical", sa.String(50), nullable=False),
        sa.Column("config_type", sa.String(50), nullable=False),
        sa.Column("config", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.UniqueConstraint(
            "organization_id", "vertical", "config_type",
            name="uq_overrides_org_vertical_type",
        ),
    )

    # CHECK constraints — same as defaults
    op.execute("""
        ALTER TABLE vertical_config_overrides
        ADD CONSTRAINT ck_overrides_vertical
        CHECK (vertical IN ('private_credit', 'liquid_funds'))
    """)
    op.execute("""
        ALTER TABLE vertical_config_overrides
        ADD CONSTRAINT ck_overrides_config_type
        CHECK (config_type IN (
            'calibration', 'scoring', 'blocks', 'chapters',
            'portfolio_profiles', 'prompts', 'model_routing', 'tone', 'evaluation'
        ))
    """)

    # Composite index for lookup performance
    op.create_index(
        "idx_config_overrides_lookup",
        "vertical_config_overrides",
        ["vertical", "config_type", "organization_id"],
    )

    # ── RLS on overrides ─────────────────────────────────────────
    op.execute("ALTER TABLE vertical_config_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE vertical_config_overrides FORCE ROW LEVEL SECURITY")
    # MUST use subselect pattern — see CLAUDE.md "RLS subselect" rule
    op.execute("""
        CREATE POLICY org_isolation ON vertical_config_overrides
            USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
    """)

    # ═══════════════════════════════════════════════════════════════
    #  SEED DATA — INSERT ... ON CONFLICT DO NOTHING (idempotent)
    # ═══════════════════════════════════════════════════════════════
    bind = op.get_bind()
    for seed in _SEEDS:
        config_data = _load_yaml(seed["yaml_path"])
        bind.execute(
            sa.text("""
                INSERT INTO vertical_config_defaults
                    (id, vertical, config_type, config, description, created_by)
                VALUES
                    (gen_random_uuid(), :vertical, :config_type, :config, :description, 'migration:0004')
                ON CONFLICT (vertical, config_type) DO NOTHING
            """),
            {
                "vertical": seed["vertical"],
                "config_type": seed["config_type"],
                "config": json.dumps(config_data),
                "description": seed["description"],
            },
        )


def downgrade() -> None:
    # WARNING: destroys all config data (defaults + overrides)
    op.execute("DROP POLICY IF EXISTS org_isolation ON vertical_config_overrides")
    op.drop_index("idx_config_overrides_lookup", table_name="vertical_config_overrides")
    op.drop_table("vertical_config_overrides")
    op.drop_table("vertical_config_defaults")
