"""Governance policy config_type + seed data.

Expands the config_type CHECK constraint on vertical_config_defaults and
vertical_config_overrides to include 'governance_policy'.

Seeds the governance_policy config from _GOVERNANCE_POLICY_SEED into
vertical_config_defaults for the private_credit vertical.

depends_on: 0006 (macro_reviews).
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# ── CHECK constraint value lists ────────────────────────────────────
_CONFIG_TYPES_V1 = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
    "'evaluation', 'macro_intelligence'"
)

_CONFIG_TYPES_V2 = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', 'tone', "
    "'evaluation', 'macro_intelligence', 'governance_policy'"
)

# ── Seed data — flat scalar values matching _DEFAULTS in policy_loader.py ──
_GOVERNANCE_POLICY_SEED: dict = {
    "single_manager_pct": 35.0,
    "single_investment_pct": 35.0,
    "single_sector_pct": 35.0,
    "single_geography_pct": 40.0,
    "top3_names_pct": 75.0,
    "non_usd_unhedged_pct": 20.0,
    "min_commingled_pct": 35.0,
    "max_hard_lockup_pct": 10.0,
    "max_lockup_years": 2.0,
    "min_quarterly_liquidity_pct": 20.0,
    "max_leverage_underlying_pct": 300.0,
    "min_manager_track_record_years": 2.0,
    "min_manager_aum_usd": 100_000_000.0,
    "max_manager_default_rate_pct": 10.0,
    "board_override_triggers": [
        "single_manager",
        "single_investment",
        "hard_lockup",
        "non_usd_unhedged",
    ],
    "watchlist_triggers": [
        "covenant_breach",
        "payment_delay",
        "cashflow_deterioration",
        "valuation_markdown",
        "legal_regulatory_event",
        "structural_change_underlying",
    ],
    "ic_approval_required_above_pct": 35.0,
    "review_frequency_days": 90,
}

_TABLES = ["vertical_config_defaults", "vertical_config_overrides"]
_CONSTRAINT_NAMES = {
    "vertical_config_defaults": "ck_defaults_config_type",
    "vertical_config_overrides": "ck_overrides_config_type",
}


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  ALTER CHECK: add 'governance_policy' to config_type constraints
    # ═══════════════════════════════════════════════════════════════
    for table in _TABLES:
        constraint = _CONSTRAINT_NAMES[table]
        op.execute(f"""
            ALTER TABLE {table}
            DROP CONSTRAINT {constraint}
        """)
        op.execute(f"""
            ALTER TABLE {table}
            ADD CONSTRAINT {constraint}
            CHECK (config_type IN ({_CONFIG_TYPES_V2}))
        """)

    # ═══════════════════════════════════════════════════════════════
    #  SEED: governance_policy config for private_credit
    # ═══════════════════════════════════════════════════════════════
    bind = op.get_bind()
    bind.execute(
        sa.text("""
            INSERT INTO vertical_config_defaults
                (id, vertical, config_type, config, description, created_by)
            VALUES (
                gen_random_uuid(),
                :vertical,
                :config_type,
                :config,
                :description,
                'migration:0007'
            )
            ON CONFLICT (vertical, config_type) DO NOTHING
        """),
        {
            "vertical": "private_credit",
            "config_type": "governance_policy",
            "config": json.dumps(_GOVERNANCE_POLICY_SEED),
            "description": "Concentration limits, governance triggers, IC thresholds (Investment Policy s.4-5)",
        },
    )


def downgrade() -> None:
    # 1. Remove governance_policy rows — overrides FIRST, then defaults
    op.execute("""
        DELETE FROM vertical_config_overrides
        WHERE config_type = 'governance_policy'
    """)
    op.execute("""
        DELETE FROM vertical_config_defaults
        WHERE vertical = 'private_credit' AND config_type = 'governance_policy'
    """)

    # 2. Restore V1 CHECK constraints (without 'governance_policy')
    for table in _TABLES:
        constraint = _CONSTRAINT_NAMES[table]
        op.execute(f"""
            ALTER TABLE {table}
            DROP CONSTRAINT {constraint}
        """)
        op.execute(f"""
            ALTER TABLE {table}
            ADD CONSTRAINT {constraint}
            CHECK (config_type IN ({_CONFIG_TYPES_V1}))
        """)
