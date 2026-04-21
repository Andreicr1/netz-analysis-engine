"""Create fund_memberships table for per-user fund access (AUTH-02).

Maps (actor_id, organization_id) → fund_id. Queried during actor resolution
to populate Actor.fund_ids for non-admin users. Admin/super-admin bypass
this table entirely.

No RLS on this table — it is read during actor resolution before tenant
context is established. Access is restricted to the authenticated actor's
own rows via WHERE actor_id = :actor_id AND organization_id = :org_id.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    op.create_table(
        "fund_memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_id", sa.String(128), nullable=False, index=True),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("fund_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("granted_by", sa.String(128), nullable=True),
        sa.UniqueConstraint("actor_id", "organization_id", "fund_id", name="uq_fund_membership"),
    )


def downgrade() -> None:
    op.drop_table("fund_memberships")
