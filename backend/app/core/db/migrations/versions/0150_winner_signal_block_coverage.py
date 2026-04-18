"""PR-A22 — document ``block_coverage_insufficient`` winner signal.

No schema change is required. ``portfolio_construction_runs.cascade_telemetry``
is a free-form JSONB column (see migration ``0142_construction_cascade_telemetry``);
``winner_signal`` is a JSON key inside that column and has no CHECK
constraint or Postgres ENUM backing. The Python ``WinnerSignal`` enum
in ``app/domains/wealth/schemas/sanitized.py`` is the single source
of truth for allowed values — PR-A22 extends it with
``BLOCK_COVERAGE_INSUFFICIENT = 'block_coverage_insufficient'``.

This migration exists only as an audit marker so the decision is
traceable in ``alembic history``. ``upgrade`` and ``downgrade`` are
both no-ops.
"""
from __future__ import annotations

revision = "0150_winner_signal_block_coverage"
down_revision = "0149_sanitize_org_universe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No schema change — see module docstring.
    pass


def downgrade() -> None:
    # No schema change — see module docstring.
    pass
