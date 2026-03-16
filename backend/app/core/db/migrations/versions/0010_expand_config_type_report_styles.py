"""Expand config_type CHECK to include 'report_styles'.

Adds 'report_styles' to the config_type CHECK constraint on both
vertical_config_defaults and vertical_config_overrides tables.

depends_on: 0009 (admin_infrastructure).
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_CONFIG_TYPES_V4 = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
    "'evaluation', 'macro_intelligence', 'governance_policy', "
    "'branding', 'report_styles'"
)

_CONFIG_TYPES_V3 = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
    "'evaluation', 'macro_intelligence', 'governance_policy', 'branding'"
)


def upgrade() -> None:
    for table in ("vertical_config_defaults", "vertical_config_overrides"):
        constraint = f"ck_{'defaults' if 'defaults' in table else 'overrides'}_config_type"
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"CHECK (config_type IN ({_CONFIG_TYPES_V4}))"
        )


def downgrade() -> None:
    for table in ("vertical_config_defaults", "vertical_config_overrides"):
        constraint = f"ck_{'defaults' if 'defaults' in table else 'overrides'}_config_type"
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"CHECK (config_type IN ({_CONFIG_TYPES_V3}))"
        )
