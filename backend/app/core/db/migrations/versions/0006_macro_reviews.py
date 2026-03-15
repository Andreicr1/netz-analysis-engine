"""Macro reviews table + tactical positions partial unique index.

Creates macro_reviews (organization-scoped, with RLS) for CIO approval workflow.
Adds partial unique index on tactical_positions to enforce one active position
per (org, profile, block).

depends_on: 0005 (macro_regional_snapshots must exist for FK).
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════
    #  TABLE: macro_reviews (organization-scoped, with RLS)
    # ═══════════════════════════════════════════════════════════════
    op.create_table(
        "macro_reviews",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("is_emergency", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column(
            "snapshot_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("macro_regional_snapshots.id"),
            nullable=True,
        ),
        sa.Column("report_json", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_rationale", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("updated_by", sa.String(128), nullable=True),
    )

    # ── CHECK constraint on status ─────────────────────────────
    op.execute("""
        ALTER TABLE macro_reviews
        ADD CONSTRAINT chk_macro_review_status
        CHECK (status IN ('pending', 'approved', 'rejected'))
    """)

    # ── Composite indexes for lookup performance ───────────────
    op.create_index(
        "idx_macro_reviews_org_status",
        "macro_reviews",
        ["organization_id", "status"],
    )
    op.create_index(
        "idx_macro_reviews_org_emergency",
        "macro_reviews",
        ["organization_id", "is_emergency", sa.text("created_at DESC")],
    )

    # ── RLS: full pattern from 0003 (ENABLE + FORCE + USING + WITH CHECK) ──
    op.execute("ALTER TABLE macro_reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE macro_reviews FORCE ROW LEVEL SECURITY")
    # MUST use subselect pattern — see CLAUDE.md "RLS subselect" rule
    op.execute("""
        CREATE POLICY org_isolation ON macro_reviews
            USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
            WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
    """)

    # ═══════════════════════════════════════════════════════════════
    #  TACTICAL POSITIONS: partial unique index (one active per block)
    # ═══════════════════════════════════════════════════════════════

    # Data cleanup: close duplicate active positions (keep most recent)
    op.execute("""
        UPDATE tactical_positions tp1 SET valid_to = CURRENT_DATE - 1
        WHERE valid_to IS NULL AND position_id != (
            SELECT position_id FROM tactical_positions tp2
            WHERE tp2.organization_id = tp1.organization_id
              AND tp2.profile = tp1.profile AND tp2.block_id = tp1.block_id
              AND tp2.valid_to IS NULL
            ORDER BY tp2.created_at DESC, tp2.position_id DESC LIMIT 1)
    """)

    op.create_index(
        "uq_tactical_one_active_per_block",
        "tactical_positions",
        ["organization_id", "profile", "block_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tactical_one_active_per_block", table_name="tactical_positions")

    # Remove RLS
    op.execute("DROP POLICY IF EXISTS org_isolation ON macro_reviews")
    op.execute("ALTER TABLE macro_reviews DISABLE ROW LEVEL SECURITY")

    op.drop_table("macro_reviews")
