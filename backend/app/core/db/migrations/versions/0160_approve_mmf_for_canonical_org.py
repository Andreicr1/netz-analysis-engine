"""approve promoted MMFs into instruments_org for canonical dev org

Follow-up to 0159. Ensures the 316 promoted MMFs are approved for the
canonical dev org (`403d8392-ebfa-5890-b740-45da49c556eb`) so they become
candidates for the optimizer's cash block.

Production orgs will approve via the standard universe-auto-import flow;
this migration is dev-only seed behavior. Idempotent.

Revision ID: 0160_approve_mmf_for_canonical_org
Revises: 0159_promote_mmf_to_universe
"""
from __future__ import annotations

from alembic import op

revision = "0160_approve_mmf_for_canonical_org"
down_revision = "0159_promote_mmf_to_universe"
branch_labels = None
depends_on = None

CANONICAL_DEV_ORG = "403d8392-ebfa-5890-b740-45da49c556eb"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO instruments_org (
            organization_id, instrument_id, block_id,
            approval_status, source
        )
        SELECT
            '{CANONICAL_DEV_ORG}'::uuid,
            iu.instrument_id,
            'cash',
            'approved',
            'mmf_seed_canonical_org'
        FROM instruments_universe iu
        WHERE iu.attributes->>'strategy_label_source' = 'sec_mmf_promotion'
          AND iu.is_active
          AND NOT EXISTS (
              SELECT 1 FROM instruments_org io
              WHERE io.organization_id = '{CANONICAL_DEV_ORG}'::uuid
                AND io.instrument_id = iu.instrument_id
          );
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM instruments_org
         WHERE organization_id = '{CANONICAL_DEV_ORG}'::uuid
           AND source = 'mmf_seed_canonical_org';
        """
    )
