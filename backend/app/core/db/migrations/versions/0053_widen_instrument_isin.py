"""Widen instruments_universe.isin from VARCHAR(12) to VARCHAR(30).

ESMA fund identifiers use LEI-based codes (20 chars) that exceed the
standard 12-char ISIN length, causing StringDataRightTruncationError
on import.
"""

revision = "0053_widen_instrument_isin"
down_revision = "0052_sec_entity_links"

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.alter_column(
        "instruments_universe",
        "isin",
        type_=sa.String(30),
        existing_type=sa.String(12),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "instruments_universe",
        "isin",
        type_=sa.String(12),
        existing_type=sa.String(30),
        existing_nullable=True,
    )
