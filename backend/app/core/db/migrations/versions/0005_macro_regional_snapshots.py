"""Macro regional snapshots table + config_type expansion.

Creates macro_regional_snapshots (global, no RLS) for storing
regional macro scoring data.  Expands the config_type CHECK constraint
on vertical_config_defaults and vertical_config_overrides to include
'macro_intelligence'.

Seeds the macro_intelligence config from YAML into vertical_config_defaults.
"""

import json
from pathlib import Path

import sqlalchemy as sa
import yaml
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_PROJECT_ROOT = Path(__file__).resolve().parents[5]


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  TABLE: macro_regional_snapshots (global, no RLS)
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "macro_regional_snapshots",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("as_of_date", sa.Date, nullable=False, unique=True, index=True),
        sa.Column("data_json", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
    )

    # ═══════════════════════════════════════════════════════════════
    #  ALTER CHECK: add 'macro_intelligence' to config_type constraints
    # ═══════════════════════════════════════════════════════════════
    # Drop existing CHECK constraints and recreate with expanded values.
    # This is the standard ALTER CHECK pattern for PostgreSQL.
    op.execute("""
        ALTER TABLE vertical_config_defaults
        DROP CONSTRAINT ck_defaults_config_type
    """)
    op.execute("""
        ALTER TABLE vertical_config_defaults
        ADD CONSTRAINT ck_defaults_config_type
        CHECK (config_type IN (
            'calibration', 'scoring', 'blocks', 'chapters',
            'portfolio_profiles', 'prompts', 'model_routing', 'tone',
            'evaluation', 'macro_intelligence'
        ))
    """)

    op.execute("""
        ALTER TABLE vertical_config_overrides
        DROP CONSTRAINT ck_overrides_config_type
    """)
    op.execute("""
        ALTER TABLE vertical_config_overrides
        ADD CONSTRAINT ck_overrides_config_type
        CHECK (config_type IN (
            'calibration', 'scoring', 'blocks', 'chapters',
            'portfolio_profiles', 'prompts', 'model_routing', 'tone',
            'evaluation', 'macro_intelligence'
        ))
    """)

    # ═══════════════════════════════════════════════════════════════
    #  SEED: macro_intelligence config
    # ═══════════════════════════════════════════════════════════════
    yaml_path = _PROJECT_ROOT / "calibration" / "seeds" / "liquid_funds" / "macro_intelligence.yaml"
    if yaml_path.exists():
        with open(yaml_path) as f:
            config_data = yaml.safe_load(f)

        op.execute(
            sa.text("""
                INSERT INTO vertical_config_defaults
                    (id, vertical, config_type, config, description)
                VALUES (
                    gen_random_uuid(),
                    'liquid_funds',
                    'macro_intelligence',
                    :config,
                    'Regional macro scoring, staleness thresholds, dimension weights'
                )
                ON CONFLICT (vertical, config_type) DO NOTHING
            """),
            {"config": json.dumps(config_data)},
        )


def downgrade() -> None:
    # Restore original CHECK constraints (without macro_intelligence)
    op.execute("""
        ALTER TABLE vertical_config_overrides
        DROP CONSTRAINT ck_overrides_config_type
    """)
    op.execute("""
        ALTER TABLE vertical_config_overrides
        ADD CONSTRAINT ck_overrides_config_type
        CHECK (config_type IN (
            'calibration', 'scoring', 'blocks', 'chapters',
            'portfolio_profiles', 'prompts', 'model_routing', 'tone', 'evaluation'
        ))
    """)

    op.execute("""
        ALTER TABLE vertical_config_defaults
        DROP CONSTRAINT ck_defaults_config_type
    """)
    op.execute("""
        ALTER TABLE vertical_config_defaults
        ADD CONSTRAINT ck_defaults_config_type
        CHECK (config_type IN (
            'calibration', 'scoring', 'blocks', 'chapters',
            'portfolio_profiles', 'prompts', 'model_routing', 'tone', 'evaluation'
        ))
    """)

    # Remove seed data
    op.execute("""
        DELETE FROM vertical_config_defaults
        WHERE vertical = 'liquid_funds' AND config_type = 'macro_intelligence'
    """)

    op.drop_table("macro_regional_snapshots")
