"""Strategy drift alerts table — org-scoped with RLS.

Persists strategy drift detection results per instrument.
is_current flag pattern (same as screening_results) with partial unique index
to prevent race condition on concurrent scans.

RLS uses subselect pattern: (SELECT current_setting(..., true)) — avoids
per-row evaluation that causes 1000x slowdown (see CLAUDE.md).

depends_on: 0013 (benchmark_nav).
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_drift_alerts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "instrument_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("instruments_universe.instrument_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("anomalous_count", sa.Integer(), nullable=False),
        sa.Column("total_metrics", sa.Integer(), nullable=False),
        sa.Column("metric_details", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Status CHECK
    op.execute("""
        ALTER TABLE strategy_drift_alerts
        ADD CONSTRAINT chk_drift_alert_status
        CHECK (status IN ('stable', 'drift_detected', 'insufficient_data'))
    """)

    # Severity CHECK
    op.execute("""
        ALTER TABLE strategy_drift_alerts
        ADD CONSTRAINT chk_drift_alert_severity
        CHECK (severity IN ('none', 'moderate', 'severe'))
    """)

    # Partial unique index: only one current alert per instrument per org
    # Prevents race condition when two concurrent scans insert is_current=True
    op.create_index(
        "uq_drift_alerts_current",
        "strategy_drift_alerts",
        ["organization_id", "instrument_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    # Composite index for dashboard queries (GET /alerts?severity=severe&is_current=true)
    op.create_index(
        "ix_drift_alerts_severity",
        "strategy_drift_alerts",
        ["organization_id", "severity"],
        postgresql_where=sa.text("is_current = true"),
    )

    # ── RLS: subselect with current_setting(..., true) + WITH CHECK ──
    op.execute("ALTER TABLE strategy_drift_alerts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE strategy_drift_alerts FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY strategy_drift_alerts_org_isolation ON strategy_drift_alerts
            USING (organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid)
            WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid)
    """)


def downgrade() -> None:
    # Must drop RLS before dropping table
    op.execute("DROP POLICY IF EXISTS strategy_drift_alerts_org_isolation ON strategy_drift_alerts")
    op.execute("ALTER TABLE strategy_drift_alerts DISABLE ROW LEVEL SECURITY")
    op.drop_table("strategy_drift_alerts")
