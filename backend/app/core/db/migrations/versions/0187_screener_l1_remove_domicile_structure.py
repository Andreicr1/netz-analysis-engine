"""Remove allowed_domicile + allowed_structure gates from Layer 1 screening config.

Institutional decision (2026-04-28): domicile and structure are descriptive
tags for UI/reports/DD only — not material risk gates. Layer 1 retains only
min_aum_usd + min_track_record_years. If tenant-specific domicile/structure
gating is needed in the future, use Layer 2 mandate_fit (per-tenant).

Also removes any leftover plural variants (allowed_domiciles, allowed_structures)
as defensive cleanup. JSONB `-` operator is no-op on missing keys → idempotent.

Revision ID: 0187_screener_l1_remove_domicile_structure
Revises: 0186_screener_criterion_key_singular
Create Date: 2026-04-28
"""

from alembic import op

revision = "0187_screener_l1_remove_domicile_structure"
down_revision = "0186_screener_criterion_key_singular"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove keys from vertical_config_defaults
    op.execute("""
        UPDATE vertical_config_defaults
        SET config = jsonb_set(
            config,
            '{fund}',
            (config->'fund')
                - 'allowed_domicile'
                - 'allowed_domiciles'
                - 'allowed_structure'
                - 'allowed_structures'
        )
        WHERE config_type = 'screening_layer1'
          AND config ? 'fund'
    """)

    # Remove keys from vertical_config_overrides (any tenant)
    op.execute("""
        UPDATE vertical_config_overrides
        SET config = jsonb_set(
            config,
            '{fund}',
            (config->'fund')
                - 'allowed_domicile'
                - 'allowed_domiciles'
                - 'allowed_structure'
                - 'allowed_structures'
        )
        WHERE config_type = 'screening_layer1'
          AND config ? 'fund'
    """)


def downgrade() -> None:
    # Re-add canonical defaults to vertical_config_defaults only.
    # Override re-introduction is operational data, not schema.
    op.execute("""
        UPDATE vertical_config_defaults
        SET config = jsonb_set(
            config,
            '{fund}',
            (config->'fund')
                || jsonb_build_object(
                       'allowed_domicile', jsonb_build_array('US'),
                       'allowed_structure', jsonb_build_array('Mutual Fund', 'ETF', 'BDC', 'Money Market')
                   )
        )
        WHERE config_type = 'screening_layer1'
          AND config ? 'fund'
    """)
