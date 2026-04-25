"""Holdings drift alerts table — global (no RLS), keyed on CIK.

Persists style-drift detection results from the
``style_drift_worker`` (lock 900_064). Drift is a property of the fund
itself (composition shifted vs its 8-quarter mean), not the org's
view of the fund — so the table is global like ``fund_risk_metrics``.

Distinct from ``strategy_drift_alerts`` (org-scoped, populated by the
``/analytics/strategy-drift/scan`` route), which detects drift in
performance metrics (volatility / Sharpe / drawdown z-scores). The
two tables are complementary: composition vs. performance.

Revision ID: 0138_holdings_drift_alerts
Revises: 0137_stage_applied_batch_id
Create Date: 2026-04-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0138_holdings_drift_alerts"
down_revision = "0137_stage_applied_batch_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "holdings_drift_alerts",
        sa.Column(
            "id", sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("cik", sa.Text(), nullable=False),
        sa.Column("fund_name", sa.Text(), nullable=True),
        sa.Column("current_report_date", sa.Date(), nullable=False),
        sa.Column("historical_window_quarters", sa.Integer(), nullable=False),

        # Per-dimension drifts (0-100 scale)
        sa.Column("composite_drift", sa.Numeric(8, 4), nullable=False),
        sa.Column("asset_mix_drift", sa.Numeric(8, 4), nullable=False),
        sa.Column("fi_subtype_drift", sa.Numeric(8, 4), nullable=False),
        sa.Column("geography_drift", sa.Numeric(8, 4), nullable=False),
        sa.Column("issuer_category_drift", sa.Numeric(8, 4), nullable=False),

        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column(
            "drivers",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),

        sa.Column(
            "is_current", sa.Boolean(),
            nullable=False, server_default="true",
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )

    op.execute("""
        ALTER TABLE holdings_drift_alerts
        ADD CONSTRAINT chk_holdings_drift_status
        CHECK (status IN ('stable', 'drift_detected', 'insufficient_data'))
    """)
    op.execute("""
        ALTER TABLE holdings_drift_alerts
        ADD CONSTRAINT chk_holdings_drift_severity
        CHECK (severity IN ('none', 'moderate', 'severe'))
    """)

    # Partial unique index — only one current alert per CIK. Concurrent
    # worker runs that try to insert two is_current=true rows for the
    # same CIK will violate the constraint, forcing the second to
    # update-then-insert atomically.
    op.create_index(
        "uq_holdings_drift_current",
        "holdings_drift_alerts",
        ["cik"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )
    # Severity dashboard query
    op.create_index(
        "ix_holdings_drift_severity",
        "holdings_drift_alerts",
        ["severity"],
        postgresql_where=sa.text("is_current = true"),
    )
    # Historical lookup
    op.create_index(
        "ix_holdings_drift_cik_date",
        "holdings_drift_alerts",
        ["cik", "current_report_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_holdings_drift_cik_date", table_name="holdings_drift_alerts")
    op.drop_index("ix_holdings_drift_severity", table_name="holdings_drift_alerts")
    op.drop_index("uq_holdings_drift_current", table_name="holdings_drift_alerts")
    op.drop_table("holdings_drift_alerts")
