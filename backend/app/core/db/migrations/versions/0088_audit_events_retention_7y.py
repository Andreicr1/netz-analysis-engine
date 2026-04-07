"""Add 7-year retention policy to the audit_events hypertable.

Phase 0 audit (2026-04-08) found that ``audit_events`` has been a
TimescaleDB hypertable since migration 0030 with native compression
configured for chunks older than one month, but no automatic retention
policy. Audit data therefore grows unbounded.

Institutional compliance requires a hard 7-year retention floor for
audit trail data — long enough for SEC, FINRA and ESMA inspection
windows, short enough that we don't pay for storage of irrelevant
events forever. This migration adds the policy in a non-blocking way
so the existing data is unaffected; only chunks whose entire time
range falls before now() - 7 years will be dropped on the next
TimescaleDB background worker tick.

The policy is idempotent (``if_not_exists => true``) so re-running
the migration is safe. ``add_retention_policy`` is fully transactional
unlike ``create_hypertable``, so the standard ``op.execute`` path
works without autocommit gymnastics.

Spec reference:
docs/superpowers/specs/2026-04-08-wealth-library.md §4.5

Revision ID: 0088_audit_events_retention_7y
Revises: 0087_enable_timescale_compression
Create Date: 2026-04-08 14:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0088_audit_events_retention_7y"
down_revision: str | None = "0087_enable_timescale_compression"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent — TimescaleDB returns the existing job_id if a policy
    # is already attached and ``if_not_exists`` is true. No-op on
    # re-run.
    op.execute(
        "SELECT add_retention_policy("
        "  'audit_events',"
        "  INTERVAL '7 years',"
        "  if_not_exists => true"
        ")",
    )


def downgrade() -> None:
    # Idempotent counterpart — drops the policy if present, no-op
    # otherwise. Compression policy and the hypertable itself are
    # untouched (those belong to migration 0030 and are out of scope).
    op.execute(
        "SELECT remove_retention_policy("
        "  'audit_events',"
        "  if_exists => true"
        ")",
    )
