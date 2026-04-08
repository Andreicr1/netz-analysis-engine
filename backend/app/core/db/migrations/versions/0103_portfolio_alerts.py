"""portfolio_alerts — unified alerts feed with materialized dedupe_key

Phase 2 Task 2.4 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Replaces the fire-and-forget ``_publish_alert`` pattern in
``portfolio_eval.py:138-166``. Every worker that emits a portfolio
alert writes a durable row here, then publishes on Redis pubsub for
the SSE bridge. Postgres is the source of truth — Redis is the
ephemeral delivery mechanism.

OD-23 LOCKED: **materialized ``dedupe_key text`` column**
---------------------------------------------------------
Rather than app-level ``payload->>'dedupe_key'`` deduplication, we
materialize the key as a NOT NULL column and enforce a partial
UNIQUE index. This gives:
- Stronger guarantee (DB rejects duplicates, not just the app)
- Faster planner queries (direct B-tree lookup, no JSONB extraction)
- Cheaper to maintain (one extra text column is nothing next to
  the payload JSONB)

The dedupe key is any stable per-alert hash the producer computes
(e.g. ``md5(source_row_id || portfolio_id)`` for drift fanout).

Alert types (8 values, matching DB draft §7 + live price):

    cvar_breach        — from portfolio_eval (breach)
    drift              — from drift_check (portfolio holding drift)
    regime_change      — from regime_fit (regime transition)
    price_staleness    — from live_price_poll (stale quotes)
    weight_drift       — from portfolio_eval (slippage vs target)
    rebalance_suggested — from rebalance engine
    validation_block   — from validation_gate (Phase 3 blocker)
    custom             — free-form escape hatch

Severity: info | warning | critical.

Two partial indexes
-------------------
1. ``ix_portfolio_alerts_open`` on ``(portfolio_id, created_at DESC)``
   WHERE ``dismissed_at IS NULL`` — the hot path. Feeds the Live
   workbench AlertsFeedPanel's "open alerts" stream.
2. ``ix_portfolio_alerts_dedupe`` UNIQUE on ``(portfolio_id,
   alert_type, dedupe_key)`` WHERE ``dismissed_at IS NULL`` — the
   materialized OD-23 guard. Dismissed alerts can be re-emitted
   with the same dedupe_key (the partial index ignores them).

Downgrade
---------
NO ``IF EXISTS``.

Revision ID: 0103_portfolio_alerts
Revises: 0102_portfolio_weight_snapshots_hypertable
Create Date: 2026-04-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0103_portfolio_alerts"
down_revision: str | None = "0102_portfolio_weight_snapshots_hypertable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ALERT_TYPES = (
    "cvar_breach",
    "drift",
    "regime_change",
    "price_staleness",
    "weight_drift",
    "rebalance_suggested",
    "validation_block",
    "custom",
)

_SEVERITIES = ("info", "warning", "critical")


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE portfolio_alerts (
            id                uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id   uuid         NOT NULL,
            portfolio_id      uuid         NOT NULL
                REFERENCES model_portfolios(id) ON DELETE CASCADE,

            alert_type        text         NOT NULL,
            severity          text         NOT NULL,
            title             text         NOT NULL,
            payload           jsonb        NOT NULL DEFAULT '{{}}'::jsonb,

            -- Source attribution
            source_worker     text         NOT NULL,
            source_lock_id    integer,

            -- OD-23: materialized dedupe column (NOT NULL)
            dedupe_key        text         NOT NULL,

            -- Lifecycle
            created_at        timestamptz  NOT NULL DEFAULT now(),
            acknowledged_at   timestamptz,
            acknowledged_by   text,
            dismissed_at      timestamptz,
            dismissed_by      text,
            auto_dismiss_at   timestamptz,

            CONSTRAINT ck_alert_type
                CHECK (alert_type IN (
                    {", ".join(f"'{a}'" for a in _ALERT_TYPES)}
                )),
            CONSTRAINT ck_alert_severity
                CHECK (severity IN (
                    {", ".join(f"'{s}'" for s in _SEVERITIES)}
                ))
        )
        """,
    )

    # ── Hot-path partial index: open alerts for a portfolio ───────
    op.execute(
        """
        CREATE INDEX ix_portfolio_alerts_open
        ON portfolio_alerts (portfolio_id, created_at DESC)
        WHERE dismissed_at IS NULL
        """,
    )

    # ── OD-23 dedupe guard: partial UNIQUE on materialized key ────
    op.execute(
        """
        CREATE UNIQUE INDEX ix_portfolio_alerts_dedupe
        ON portfolio_alerts (portfolio_id, alert_type, dedupe_key)
        WHERE dismissed_at IS NULL
        """,
    )

    # ── Cold-path index: full history for the audit drawer ───────
    op.execute(
        """
        CREATE INDEX ix_portfolio_alerts_portfolio_created
        ON portfolio_alerts (portfolio_id, created_at DESC)
        """,
    )

    # ── Org-wide sweeper support: auto_dismiss_at scan ────────────
    op.execute(
        """
        CREATE INDEX ix_portfolio_alerts_auto_dismiss
        ON portfolio_alerts (auto_dismiss_at)
        WHERE dismissed_at IS NULL AND auto_dismiss_at IS NOT NULL
        """,
    )

    # ── RLS — subselect pattern ───────────────────────────────────
    op.execute("ALTER TABLE portfolio_alerts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE portfolio_alerts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY portfolio_alerts_rls
        ON portfolio_alerts
        USING (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        WITH CHECK (
            organization_id = (SELECT current_setting('app.current_organization_id'))::uuid
        )
        """,
    )


def downgrade() -> None:
    # NO IF EXISTS — fail loudly.
    op.execute("DROP POLICY portfolio_alerts_rls ON portfolio_alerts")
    op.execute("DROP INDEX ix_portfolio_alerts_auto_dismiss")
    op.execute("DROP INDEX ix_portfolio_alerts_portfolio_created")
    op.execute("DROP INDEX ix_portfolio_alerts_dedupe")
    op.execute("DROP INDEX ix_portfolio_alerts_open")
    op.execute("DROP TABLE portfolio_alerts")
