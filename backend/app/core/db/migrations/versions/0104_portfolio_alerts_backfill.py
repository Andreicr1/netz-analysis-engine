"""portfolio_alerts backfill from strategy_drift_alerts (fanout)

Phase 2 Task 2.5 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

**OD-24 locked: fanout strategy.** ``strategy_drift_alerts`` is
keyed by ``(organization_id, instrument_id)`` — one row per drifting
instrument. The new ``portfolio_alerts`` table is keyed by
``portfolio_id`` so the workbench's partial ``ix_portfolio_alerts_open``
index can use portfolio equality for the hot path.

Fanout semantics: for each ``strategy_drift_alerts`` row, emit one
``portfolio_alerts`` row per portfolio currently holding the
drifting instrument. "Currently holding" is derived from
``model_portfolios.fund_selection_schema->'funds'[].instrument_id``
since ``portfolio_weight_snapshots`` (0102) is still empty on
first backfill.

Idempotency
-----------
Each emitted row carries ``dedupe_key = md5(drift_id || portfolio_id)``
so rerunning the backfill is a no-op — the partial UNIQUE index
``ix_portfolio_alerts_dedupe`` catches repeats via
``ON CONFLICT ... DO NOTHING``.

Severity mapping
----------------
strategy_drift_alerts.severity → portfolio_alerts.severity

    'critical' → 'critical'
    'warning'  → 'warning'
    'info'     → 'info'
    (anything else, including NULL or legacy uppercase) → 'info'

Downgrade
---------
Targeted DELETE on ``source_worker = 'drift_check_backfill'`` —
removes only the rows this migration inserted. Does NOT use
``IF EXISTS`` on the table itself; if the table is gone the
migration chain is broken and should fail loudly.

Empty-DB safety
---------------
On a fresh branch the source table ``strategy_drift_alerts`` is
empty. The INSERT inserts zero rows. The migration still completes
cleanly — the whole point of running it on migrate is to shake out
syntax errors, not to move data.

Revision ID: 0104_portfolio_alerts_backfill
Revises: 0103_portfolio_alerts
Create Date: 2026-04-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0104_portfolio_alerts_backfill"
down_revision: str | None = "0103_portfolio_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fanout: for each drift row, emit one portfolio_alerts row per
    # portfolio in the same org that holds the drifting instrument.
    #
    # The LATERAL JOIN expands fund_selection_schema->'funds' into
    # per-instrument rows, then matches on instrument_id. Guarded
    # against portfolios with NULL/missing schemas via the outer
    # filter ``mp.fund_selection_schema ? 'funds'``.
    op.execute(
        """
        INSERT INTO portfolio_alerts (
            organization_id,
            portfolio_id,
            alert_type,
            severity,
            title,
            payload,
            source_worker,
            source_lock_id,
            dedupe_key,
            created_at
        )
        SELECT
            sda.organization_id,
            mp.id AS portfolio_id,
            'drift' AS alert_type,
            CASE
                WHEN lower(sda.severity) = 'critical' THEN 'critical'
                WHEN lower(sda.severity) = 'warning'  THEN 'warning'
                WHEN lower(sda.severity) = 'info'     THEN 'info'
                ELSE 'info'
            END AS severity,
            'Strategy drift detected on holding' AS title,
            jsonb_build_object(
                'drift_id', sda.id,
                'instrument_id', sda.instrument_id,
                'drift_status', sda.status,
                'drift_severity', sda.severity,
                'drift_magnitude', sda.drift_magnitude,
                'detected_at', sda.detected_at,
                'backfilled', true
            ) AS payload,
            'drift_check_backfill' AS source_worker,
            42 AS source_lock_id,
            md5(sda.id::text || '|' || mp.id::text) AS dedupe_key,
            sda.detected_at AS created_at
        FROM strategy_drift_alerts sda
        JOIN model_portfolios mp
            ON mp.organization_id = sda.organization_id
           AND mp.fund_selection_schema ? 'funds'
        CROSS JOIN LATERAL jsonb_array_elements(
            mp.fund_selection_schema->'funds'
        ) AS f(fund)
        WHERE sda.is_current = true
          AND f.fund ? 'instrument_id'
          AND (f.fund->>'instrument_id')::uuid = sda.instrument_id
        ON CONFLICT (portfolio_id, alert_type, dedupe_key)
            WHERE dismissed_at IS NULL
            DO NOTHING
        """,
    )


def downgrade() -> None:
    # Targeted DELETE — remove only rows we inserted. Does not
    # touch non-backfill alerts emitted by live workers.
    op.execute(
        """
        DELETE FROM portfolio_alerts
        WHERE source_worker = 'drift_check_backfill'
        """,
    )
