"""PR-BE-7 — consolidate legacy ``aggressive`` profile/mandate into ``growth``.

Defensive backfill across every wealth surface that historically carried
the ``aggressive`` slug. Per the F1 audit (2026-04-30), the local docker
DB and the Timescale Cloud target both have **zero** rows referencing
the legacy slug — ``aggressive`` was a development artefact, not a
canonical product profile, and never made it into a tenant snapshot.
The migration runs anyway as a one-time hygiene sweep so any developer
fixture or stale environment is brought into line with the
post-PR-BE-7 enum (``conservative`` / ``moderate`` / ``growth``).

The application-layer alias normaliser (introduced alongside this
migration) keeps URL- and mandate-level callers backward compatible
through 2026-10-30 (180 days post-merge); the DB layer is the
authoritative truth source from this revision onward.

Revision ID: 0199_q165_consolidate_aggressive_into_growth
Revises: 0198_q159_rebuild_mv_nport_sector_attribution
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op

# Revision identifiers, used by Alembic.
revision = "0199_q165_consolidate_aggressive_into_growth"
down_revision = "0198_q159_rebuild_mv_nport_sector_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Profile namespace ──────────────────────────────────────────
    # Three tables carry a ``profile`` column whose canonical enum was
    # ``conservative`` / ``moderate`` / ``growth`` / ``aggressive``.
    # PR-BE-7 collapses ``aggressive`` into ``growth``.
    op.execute(
        "UPDATE model_portfolios SET profile = 'growth' "
        "WHERE profile = 'aggressive'",
    )
    op.execute(
        "UPDATE strategic_allocation SET profile = 'growth' "
        "WHERE profile = 'aggressive'",
    )
    op.execute(
        "UPDATE allocation_approvals SET profile = 'growth' "
        "WHERE profile = 'aggressive'",
    )

    # ── Mandate namespace ──────────────────────────────────────────
    # ``portfolio_calibration.mandate`` is a ``String(64)`` column with
    # no DB-level CHECK constraint, so the legacy ``aggressive`` value
    # is a free-form artefact. Same hygienic UPDATE pattern.
    op.execute(
        "UPDATE portfolio_calibration SET mandate = 'growth' "
        "WHERE mandate = 'aggressive'",
    )


def downgrade() -> None:
    raise NotImplementedError(
        "PR-BE-7 consolidates the legacy 'aggressive' profile/mandate "
        "into 'growth'. The original distinction was a development "
        "artefact, not a canonical product setting, so a reversible "
        "downgrade would have to invent which rows were originally "
        "'aggressive' vs which were 'growth'. Restore from a "
        "pre-migration backup if you genuinely need the legacy split.",
    )
