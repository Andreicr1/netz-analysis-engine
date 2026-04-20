"""primary_benchmark_backfill_log audit table.

PR-Q5.1 Phase A2: audit trail for the tiingo-description regex backfill.
Every row processed by ``backfill_primary_benchmark_from_tiingo`` lands
here — inserted, skipped, unresolvable, or no-match — so operators can
answer "why is fund X still missing primary_benchmark?" with a single
query instead of re-running the regex.

Global table (no RLS, no organization_id). Low volume — one row per
registered-fund CIK per backfill invocation. A unique index on
(cik, source) plus ON CONFLICT DO UPDATE keeps re-runs idempotent.

depends_on: 0166.
"""

from __future__ import annotations

from alembic import op

revision = "0167_primary_benchmark_backfill_log"
down_revision = "0166_expand_benchmark_etf_canonical_aliases"
branch_labels = None
depends_on = None


_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS primary_benchmark_backfill_log (
    id                   BIGSERIAL PRIMARY KEY,
    cik                  TEXT NOT NULL,
    ticker               TEXT,
    description_snippet  TEXT,
    extracted_raw        TEXT,
    resolved_canonical   TEXT,
    pattern_id           TEXT,
    source               TEXT NOT NULL DEFAULT 'tiingo_description_regex_v1',
    action               TEXT NOT NULL
        CHECK (action IN ('inserted', 'skipped_existing', 'unresolvable', 'no_match')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_backfill_log_cik_source UNIQUE (cik, source)
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_backfill_log_action "
    "ON primary_benchmark_backfill_log (action)",
    "CREATE INDEX IF NOT EXISTS ix_backfill_log_pattern "
    "ON primary_benchmark_backfill_log (pattern_id) "
    "WHERE pattern_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_backfill_log_created_at "
    "ON primary_benchmark_backfill_log (created_at DESC)",
]


def upgrade() -> None:
    op.execute(_TABLE_DDL)
    for ddl in _INDEXES:
        op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_backfill_log_created_at")
    op.execute("DROP INDEX IF EXISTS ix_backfill_log_pattern")
    op.execute("DROP INDEX IF EXISTS ix_backfill_log_action")
    op.execute("DROP TABLE IF EXISTS primary_benchmark_backfill_log")
