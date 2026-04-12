"""mv_construction_run_diff materialized view.

Computes weight + ex-ante metrics deltas between consecutive
construction runs per portfolio. Phase 4 Builder's "Compare to
previous run" analytics panel reads from this view instead of
recomputing on every request.

Structure per row:
  portfolio_id
  run_id
  previous_run_id
  weight_delta_jsonb  — keyed by instrument_id with
                        {from, to, delta}
  metrics_delta_jsonb — keyed by metric name with
                        {from, to, delta}
  status_delta_text   — short summary ('initial run' | 'delta computed')

Source columns (audited 2026-04-11 against live
``portfolio_construction_runs`` schema — the brief's placeholders
``final_weights`` / ``final_metrics`` do NOT exist on this table;
the real columns are ``weights_proposed`` (jsonb) and
``ex_ante_metrics`` (jsonb)).

Depends on the ``event_log`` column added in Session 2.A commit 2.
We pre-join runs with their predecessor via window LAG() over
``requested_at`` and filter to terminal states only
(``succeeded`` or ``superseded``).

Unique index on ``run_id`` enables CONCURRENT refresh. Btree index
on ``(portfolio_id, run_id)`` supports the Builder's per-portfolio
"show me the diff for the latest N runs" query pattern.

Revision ID: 0118_mv_construction_run_diff
Revises: 0117_v_screener_org_membership
Create Date: 2026-04-11
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0118_mv_construction_run_diff"
down_revision: str | None = "0117_v_screener_org_membership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW mv_construction_run_diff AS
        WITH ordered AS (
            SELECT
                id AS run_id,
                portfolio_id,
                organization_id,
                requested_at,
                status,
                weights_proposed,
                ex_ante_metrics,
                LAG(id) OVER (
                    PARTITION BY portfolio_id
                    ORDER BY requested_at
                ) AS previous_run_id,
                LAG(weights_proposed) OVER (
                    PARTITION BY portfolio_id
                    ORDER BY requested_at
                ) AS previous_weights,
                LAG(ex_ante_metrics) OVER (
                    PARTITION BY portfolio_id
                    ORDER BY requested_at
                ) AS previous_metrics
            FROM portfolio_construction_runs
            WHERE status IN ('succeeded', 'superseded')
        )
        SELECT
            o.run_id,
            o.portfolio_id,
            o.organization_id,
            o.previous_run_id,
            o.requested_at,
            COALESCE(
                (
                    SELECT jsonb_object_agg(
                        key,
                        jsonb_build_object(
                            'from',  COALESCE((o.previous_weights ->> key)::numeric, 0),
                            'to',    COALESCE((o.weights_proposed  ->> key)::numeric, 0),
                            'delta', COALESCE((o.weights_proposed  ->> key)::numeric, 0)
                                   - COALESCE((o.previous_weights ->> key)::numeric, 0)
                        )
                    )
                    FROM (
                        SELECT jsonb_object_keys(
                            COALESCE(o.weights_proposed, '{}'::jsonb)
                            || COALESCE(o.previous_weights, '{}'::jsonb)
                        ) AS key
                    ) k
                ),
                '{}'::jsonb
            ) AS weight_delta_jsonb,
            COALESCE(
                (
                    SELECT jsonb_object_agg(
                        key,
                        jsonb_build_object(
                            'from',  (o.previous_metrics ->> key),
                            'to',    (o.ex_ante_metrics  ->> key),
                            'delta',
                                CASE
                                    WHEN jsonb_typeof(o.ex_ante_metrics -> key) = 'number'
                                     AND jsonb_typeof(o.previous_metrics -> key) = 'number'
                                    THEN to_jsonb(
                                        (o.ex_ante_metrics ->> key)::numeric
                                        - (o.previous_metrics ->> key)::numeric
                                    )
                                    ELSE NULL
                                END
                        )
                    )
                    FROM (
                        SELECT jsonb_object_keys(
                            COALESCE(o.ex_ante_metrics, '{}'::jsonb)
                            || COALESCE(o.previous_metrics, '{}'::jsonb)
                        ) AS key
                    ) k
                ),
                '{}'::jsonb
            ) AS metrics_delta_jsonb,
            CASE
                WHEN o.previous_run_id IS NULL THEN 'initial run'
                ELSE 'delta computed'
            END AS status_delta_text
        FROM ordered o
        WITH NO DATA
        """,
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_mv_construction_run_diff_run
        ON mv_construction_run_diff (run_id)
        """,
    )

    op.execute(
        """
        CREATE INDEX idx_mv_construction_run_diff_portfolio
        ON mv_construction_run_diff (portfolio_id, requested_at DESC)
        """,
    )

    op.execute("REFRESH MATERIALIZED VIEW mv_construction_run_diff")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_construction_run_diff")
