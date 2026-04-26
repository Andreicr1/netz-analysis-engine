"""esma_funds — PK rotate from isin to lei + shadow rename.

PR-Q11B Phase 2.4. After all callsites are updated to use ``lei``,
rotate the primary key from ``isin`` (which stored LEIs) to the proper
``lei`` column. Rename old ``isin`` → ``legacy_isin_misnamed`` to prevent
accidental reads.

Pre-flight verified: no incoming FK references to esma_funds(isin).
esma_securities FK already targets esma_funds(lei) from 0181.

Revision ID: 0182_switch_esma_funds_pk_to_lei
Revises: 0181_create_esma_securities
Create Date: 2026-04-26
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0182_switch_esma_funds_pk_to_lei"
down_revision: str | None = "0181_create_esma_securities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE esma_funds DROP CONSTRAINT esma_funds_pkey")
    op.execute("ALTER TABLE esma_funds ADD CONSTRAINT esma_funds_pkey PRIMARY KEY (lei)")
    op.execute("ALTER TABLE esma_funds RENAME COLUMN isin TO legacy_isin_misnamed")


def downgrade() -> None:
    op.execute("ALTER TABLE esma_funds RENAME COLUMN legacy_isin_misnamed TO isin")
    op.execute("ALTER TABLE esma_funds DROP CONSTRAINT esma_funds_pkey")
    op.execute("ALTER TABLE esma_funds ADD CONSTRAINT esma_funds_pkey PRIMARY KEY (isin)")
