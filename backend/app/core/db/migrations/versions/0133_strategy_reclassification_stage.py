"""Staging table for cascade classifier reclassification runs.

Holds the (current_label, proposed_label, source, matched_pattern)
tuple per fund until an operator reviews the diff and applies it.
Session B scripts (``strategy_diff_report.py``, ``apply_strategy_reclassification.py``)
read from and update this table; production strategy_label columns are
NEVER touched by the worker itself.

Revision ID: 0133_strategy_reclassification_stage
Revises: 0132_merge_0110_heads
Create Date: 2026-04-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0133_strategy_reclassification_stage"
down_revision = "0132_merge_0110_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_reclassification_stage",
        sa.Column(
            "stage_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Which source we read the fund from. Free-form text (not an enum)
        # so adding a new source later is a code-only change.
        sa.Column("source_table", sa.Text, nullable=False),
        # Primary key of the source row, serialized as text. UUIDs, CIKs,
        # CRDs and ISINs all fit cleanly; text keeps the table polymorphic.
        sa.Column("source_pk", sa.Text, nullable=False),
        sa.Column("fund_name", sa.Text, nullable=True),
        sa.Column("fund_type", sa.Text, nullable=True),
        sa.Column("current_strategy_label", sa.Text, nullable=True),
        sa.Column("proposed_strategy_label", sa.Text, nullable=True),
        # Lineage — which cascade layer fired. One of:
        #   tiingo_description | name_regex | adv_brochure | fallback
        sa.Column("classification_source", sa.Text, nullable=False),
        sa.Column("matched_pattern", sa.Text, nullable=True),
        sa.Column("confidence", sa.Text, nullable=False),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # NULL = staged but not yet applied. Set by the apply script.
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_reclassification_stage_run_id",
        "strategy_reclassification_stage",
        ["run_id"],
    )
    op.create_index(
        "idx_reclassification_stage_source_table",
        "strategy_reclassification_stage",
        ["source_table"],
    )
    # Partial index on unapplied rows — the diff/apply scripts always
    # filter by ``applied_at IS NULL``.
    op.create_index(
        "idx_reclassification_stage_unapplied",
        "strategy_reclassification_stage",
        ["run_id", "source_table"],
        postgresql_where=sa.text("applied_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_reclassification_stage_unapplied",
        table_name="strategy_reclassification_stage",
    )
    op.drop_index(
        "idx_reclassification_stage_source_table",
        table_name="strategy_reclassification_stage",
    )
    op.drop_index(
        "idx_reclassification_stage_run_id",
        table_name="strategy_reclassification_stage",
    )
    op.drop_table("strategy_reclassification_stage")
