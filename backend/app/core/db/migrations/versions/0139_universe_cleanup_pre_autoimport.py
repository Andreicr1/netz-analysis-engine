"""Surgical cleanup of stale seed data before universe auto-import.

Truncates model_portfolios and all FK-cascaded dependents (construction
runs, stress results, calibration, alerts, state transitions, weight
snapshots, synthetic NAV). Preserves allocation_blocks, IC views with
active human authors, and all global tables.

Backup: restore from backups/backup_pre_universe_cleanup_*.sql.gz
Command:
    pg_dump -Fc -t model_portfolios -t portfolio_calibration \
        -t portfolio_construction_runs -t portfolio_stress_results \
        -t portfolio_alerts -t portfolio_snapshots -t portfolio_views \
        -t model_portfolio_nav -t instruments_org \
        -t portfolio_state_transitions -t portfolio_weight_snapshots \
        "$DIRECT_DATABASE_URL" \
        > backups/backup_pre_universe_cleanup_$(date +%Y%m%d_%H%M%S).sql.gz

Revision ID: 0139_universe_cleanup_pre_autoimport
Revises: 0138_holdings_drift_alerts
Create Date: 2026-04-16
"""

import sqlalchemy as sa

from alembic import op

revision = "0139_universe_cleanup_pre_autoimport"
down_revision = "0138_holdings_drift_alerts"
branch_labels = None
depends_on = None


_SYSTEM_ORG_UUID = "00000000-0000-0000-0000-000000000000"


def _audit(conn: sa.engine.Connection, table: str, action: str, rows: int) -> None:
    """Write audit event for each cleanup operation.

    Uses nil-UUID sentinel for organization_id because audit_events is a
    hypertable with NOT NULL on organization_id. System-level migration
    events are scoped to the nil org and never match any tenant RLS policy.
    """
    conn.execute(
        sa.text("""
            INSERT INTO audit_events (
                organization_id, actor_id, actor_roles, action,
                entity_type, entity_id, before_state, after_state,
                request_id, access_level, created_by, updated_by
            ) VALUES (
                CAST(:system_org AS uuid), 'system:migration', '{system}', :action,
                'universe_cleanup', :table,
                jsonb_build_object('rows_affected', :rows, 'reason', 'pr_a6_pre_autoimport'),
                NULL,
                'migration:0139', 'internal', 'system:migration', 'system:migration'
            )
        """),
        {"action": action, "table": table, "rows": rows, "system_org": _SYSTEM_ORG_UUID},
    )


def upgrade() -> None:
    conn = op.get_bind()

    # --- Step 7: Selective delete on portfolio_views (BEFORE model_portfolios truncate) ---
    # Preserve IC views with human authors that are still active.
    # effective_to IS NULL means open-ended (still valid).
    result = conn.execute(sa.text("""
        DELETE FROM portfolio_views
        WHERE effective_to < NOW()::date
           OR created_by IS NULL
    """))
    _audit(conn, "portfolio_views", "selective_delete", result.rowcount)

    # --- Step 1-6, 8: Truncate model_portfolios CASCADE ---
    # All child tables have ON DELETE CASCADE from model_portfolios:
    #   portfolio_construction_runs, portfolio_stress_results,
    #   portfolio_calibration, portfolio_alerts, portfolio_state_transitions,
    #   model_portfolio_nav, portfolio_views (remaining rows).
    # portfolio_weight_snapshots references model_portfolios(id) ON DELETE CASCADE too.
    #
    # portfolio_snapshots has NO FK to model_portfolios -- truncate separately.

    # Count before truncate for audit
    mp_count = conn.execute(sa.text("SELECT COUNT(*) FROM model_portfolios")).scalar()
    ps_count = conn.execute(sa.text("SELECT COUNT(*) FROM portfolio_snapshots")).scalar()

    conn.execute(sa.text("TRUNCATE model_portfolios CASCADE"))
    _audit(conn, "model_portfolios", "truncate_cascade", mp_count or 0)

    conn.execute(sa.text("TRUNCATE portfolio_snapshots"))
    _audit(conn, "portfolio_snapshots", "truncate", ps_count or 0)

    # --- Step 9: Delete stale instruments_org ---
    result = conn.execute(sa.text("""
        DELETE FROM instruments_org
        WHERE selected_at < '2026-04-15 00:00:00+00'
    """))
    _audit(conn, "instruments_org", "delete_stale_seeds", result.rowcount)


def downgrade() -> None:
    raise RuntimeError(
        "0139 cleanup is irreversible -- restore from "
        "backups/backup_pre_universe_cleanup_*.sql.gz"
    )
