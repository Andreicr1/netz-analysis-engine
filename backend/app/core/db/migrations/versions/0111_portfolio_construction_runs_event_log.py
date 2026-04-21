"""portfolio_construction_runs event_log JSONB column.

Phase 4 Builder's SSE late-subscriber replay requires every event
published during a construction run to be persisted, not just
buffered in Redis. A user opening the Builder in another tab
mid-run must be able to replay the full optimizer trace by reading
the run row — no need to race the Redis buffer TTL.

Schema: ``event_log`` is a JSONB array of event objects, each with
``{seq, type, ts, payload}``. The ``construction_run_executor``
worker (Session 2.C retrofit) appends via
``jsonb_set`` (or ``||``) as events fire.
``mv_construction_run_diff`` (Session 2.B) reads from the column
to compute weight/metrics deltas between runs N and N-1.

A GIN index on ``event_log`` supports the dominant query patterns:
``WHERE event_log @> '[{"type": "validation_failed"}]'`` and
JSONB path extraction used by the diff MV.

Revision ID: 0111_portfolio_construction_runs_event_log
Revises: 0110_fund_risk_metrics_compress_segmentby_fix
Create Date: 2026-04-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0111_portfolio_construction_runs_event_log"
down_revision: str | None = "0110_fund_risk_metrics_compress_segmentby_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "portfolio_construction_runs",
        sa.Column(
            "event_log",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.create_index(
        "ix_pcr_event_log_gin",
        "portfolio_construction_runs",
        ["event_log"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    # NO IF EXISTS — fail loudly per 0099 discipline.
    op.drop_index("ix_pcr_event_log_gin", table_name="portfolio_construction_runs")
    op.drop_column("portfolio_construction_runs", "event_log")
