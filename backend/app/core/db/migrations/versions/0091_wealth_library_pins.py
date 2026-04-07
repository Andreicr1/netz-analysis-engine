"""Wealth Library — per-user pins (pinned / starred / recent).

Phase 1.1 of the Wealth Library sprint
(docs/superpowers/specs/2026-04-08-wealth-library.md §4.4).

Single table covering three pin types with a CHECK constraint
discriminator. Unified shape avoids duplicating RLS policies, FK
constraints and route handlers across three lookalike tables. The
TTL worker (lock 900_081, registered in CLAUDE.md) prunes ``recent``
pins older than the most recent 20 per user via a row_number()
window — bounded growth is enforced post-hoc rather than at write
time so the user-facing endpoint stays simple.

RLS is composite ``(organization_id, user_id)`` — pins are strictly
per-user, never shared across users of the same org. This requires
the ``app.current_user_id`` GUC populated by the tenancy middleware
(commit 36eee30 — phase 0.1).

Foreign key
-----------

``library_index_id`` is a hard FK into ``wealth_library_index(id)``
with ``ON DELETE CASCADE``. When the trigger from a source table
(future migration 0092) deletes a row from the index — because the
underlying document was deleted — pins pointing at it disappear
automatically. Zero orphan risk.

Revision ID: 0091_wealth_library_pins
Revises: 0090_instruments_universe_slug
Create Date: 2026-04-08 16:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0091_wealth_library_pins"
down_revision: str | None = "0090_instruments_universe_slug"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Table ─────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE wealth_library_pins (
            id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id  uuid        NOT NULL,
            user_id          text        NOT NULL,
            library_index_id uuid        NOT NULL
                REFERENCES wealth_library_index(id) ON DELETE CASCADE,
            pin_type         text        NOT NULL
                CHECK (pin_type IN ('pinned', 'starred', 'recent')),
            created_at       timestamptz NOT NULL DEFAULT now(),
            last_accessed_at timestamptz NOT NULL DEFAULT now(),
            position         integer,

            CONSTRAINT wealth_library_pins_unique
                UNIQUE (organization_id, user_id, library_index_id, pin_type)
        )
        """,
    )

    # ── Indexes ───────────────────────────────────────────────────
    # 1. Main per-user query: "give me my pinned + starred + recent
    #    sorted by access recency". Composite covers the WHERE +
    #    ORDER BY in a single index scan.
    op.execute(
        """
        CREATE INDEX wlp_user_type_accessed
        ON wealth_library_pins (organization_id, user_id, pin_type, last_accessed_at DESC)
        """,
    )

    # 2. Partial index for the TTL worker (lock 900_081). Scans only
    #    the recent partition — much smaller than the full table.
    op.execute(
        """
        CREATE INDEX wlp_recent_accessed
        ON wealth_library_pins (last_accessed_at)
        WHERE pin_type = 'recent'
        """,
    )

    # 3. Index on library_index_id for the cascade delete path —
    #    PostgreSQL needs this to avoid full-table scans when an
    #    index row is removed.
    op.execute(
        """
        CREATE INDEX wlp_library_index_id
        ON wealth_library_pins (library_index_id)
        """,
    )

    # ── RLS — composite (organization_id, user_id) ────────────────
    # Pins are per-user, never shared. The composite policy enforces
    # both axes. Both subselects MUST be wrapped — without them,
    # current_setting() evaluates per-row and the index plan loses
    # ~1000x in latency. The user_id GUC was added to the tenancy
    # middleware in commit 36eee30 (phase 0.1).
    op.execute("ALTER TABLE wealth_library_pins ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE wealth_library_pins FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY org_user_isolation ON wealth_library_pins
        USING (
            organization_id = (SELECT current_setting('app.current_organization_id')::uuid)
            AND user_id = (SELECT current_setting('app.current_user_id'))
        )
        """,
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS org_user_isolation ON wealth_library_pins")
    op.execute("DROP TABLE IF EXISTS wealth_library_pins")
