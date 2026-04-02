"""Update screening L1 config: US-only domiciles + SEC fund structures.

Restricts eliminatory layer to US instruments only (Mutual Fund, ETF, BDC,
Money Market). Removes UCITS/Cayman/Delaware/SICAV until broker execution
capability is confirmed.

Revision ID: 0082_screening_l1_us_only
Revises: 0081_model_portfolio_results
Create Date: 2026-04-02
"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0082_screening_l1_us_only"
down_revision: str | None = "0081_model_portfolio_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# New L1 config — US fund structures only, track record removed (data gap)
_NEW_FUND_L1 = {
    "min_aum_usd": 100_000_000,
    "allowed_domiciles": ["US"],
    "allowed_structures": ["Mutual Fund", "ETF", "BDC", "Money Market"],
}

# Previous L1 config — for rollback
_OLD_FUND_L1 = {
    "min_aum_usd": 100_000_000,
    "min_track_record_years": 3,
    "allowed_domiciles": ["IE", "LU", "KY", "US", "GB"],
    "allowed_structures": ["UCITS", "Cayman_LP", "Delaware_LP", "SICAV"],
}


def _update_fund_l1(fund_criteria: dict) -> None:
    bind = op.get_bind()
    # Read current full config
    row = bind.execute(
        sa.text("""
            SELECT config FROM vertical_config_defaults
            WHERE vertical = 'liquid_funds' AND config_type = 'screening_layer1'
        """),
    ).fetchone()
    if not row:
        return

    config = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    config["fund"] = fund_criteria

    bind.execute(
        sa.text("""
            UPDATE vertical_config_defaults
            SET config = CAST(:config_value AS jsonb)
            WHERE vertical = 'liquid_funds' AND config_type = 'screening_layer1'
        """),
        {"config_value": json.dumps(config)},
    )


def upgrade() -> None:
    _update_fund_l1(_NEW_FUND_L1)


def downgrade() -> None:
    _update_fund_l1(_OLD_FUND_L1)
