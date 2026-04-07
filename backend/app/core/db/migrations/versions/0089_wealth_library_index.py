"""Wealth Library — unified index table schema.

Phase 1.1 of the Wealth Library sprint
(docs/superpowers/specs/2026-04-08-wealth-library.md §4.1).

This migration creates the canonical ``wealth_library_index`` table
that consolidates outputs from ``wealth_content``, ``dd_reports`` and
``macro_reviews`` (and future pipelines) into a single denormalised
read surface for the Library UI.

Design rationale (from spec §4.1, decision rejecting both materialized
view and route-handler aggregator):

* Triggers on each source table will keep the index in sync
  transactionally — that part lives in a separate migration so the
  schema is reviewed in isolation. This migration is **schema only**:
  table, indexes, RLS, extensions. No DML.

* The table is **NOT a TimescaleDB hypertable**. Volume projections
  (~120k rows in 3 years across all tenants) are well below the
  break-even point for chunking, and the dominant access pattern is
  equality on ``organization_id + kind + status`` rather than time
  range. Re-evaluate if we ever cross 10M rows.

* The full-text ``search_vector`` is a generated column with the
  ``simple`` text search configuration (no stemming/stopwords). The
  Wealth domain is bilingual (PT and EN) within the same tenant —
  ``english`` or ``portuguese`` would break stemming for the other
  language and produce non-deterministic ranking. ``simple`` gives
  predictable, audit-friendly behaviour. See spec §4.2.

* Markdown body is **NOT indexed** here. The ``wealth_vector_chunks``
  table (pgvector + OpenAI embeddings) already covers semantic search
  on document content for the Fund Copilot RAG. The Library indexes
  metadata only — title, subtitle, entity label, kind, status,
  language, summary preview from metadata jsonb.

* ``folder_path`` is a materialized ``text[]`` populated by the
  triggers (next migration). ``ltree`` was rejected because nicknames
  of funds carry accents/punctuation that ``ltree`` cannot encode
  without losing information. ``text[]`` + GIN with ``&&``/``@>``
  operators is the equivalent functional pattern.

* ``RLS is enabled`` with the standard subselect pattern
  ``(SELECT current_setting('app.current_organization_id')::uuid)``
  for tenant isolation.

* The ``UNIQUE`` constraint on ``(source_table, source_id,
  organization_id)`` is the logical key — no foreign key into the
  source tables because there is no single target. The triggers
  enforce upsert semantics, and a self-heal worker (lock 900_080)
  reconciles the index against sources nightly.

Revision ID: 0089_wealth_library_index
Revises: 0088_audit_events_retention_7y
Create Date: 2026-04-08 15:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0089_wealth_library_index"
down_revision: str | None = "0088_audit_events_retention_7y"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────
    # pg_trgm gives us trigram fuzzy matching for fund names
    # ("T Rowe Price" -> "T. Rowe Price Cap Appreciation"). Idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── Table ─────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE wealth_library_index (
            id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id   uuid        NOT NULL,

            -- Source discriminator + logical FK
            source_table      text        NOT NULL,
            source_id         uuid        NOT NULL,

            -- Canonical metadata (sanitised by trigger)
            kind              text        NOT NULL,
            title             text        NOT NULL,
            subtitle          text,
            status            text        NOT NULL,
            language          text,

            -- Versioning (DD reports only — null for the rest)
            version           integer     DEFAULT 1,
            is_current        boolean     NOT NULL DEFAULT true,

            -- Linked entity (instrument / manager / portfolio / region)
            entity_kind       text,
            entity_id         uuid,
            entity_slug       text,
            entity_label      text,

            -- Materialised folder path (set by trigger)
            folder_path       text[]      NOT NULL,

            -- Authorship + lifecycle timestamps
            author_id         text,
            approver_id       text,
            approved_at       timestamptz,
            created_at        timestamptz NOT NULL,
            updated_at        timestamptz NOT NULL,

            -- DD-only quant signals
            confidence_score  numeric(5, 2),
            decision_anchor   text,

            -- Storage + free-form bag for source-specific fields
            storage_path      text,
            metadata          jsonb,

            -- Generated full-text search vector
            -- Configuration: 'simple' (no stemming/stopwords) — bilingual safe.
            -- Weights:
            --   A -> title (highest)
            --   B -> subtitle, entity_label (entity context)
            --   C -> kind, status, language, metadata->>'summary' (filters)
            --   D -> author_id, approver_id (authorship)
            search_vector     tsvector
                GENERATED ALWAYS AS (
                    setweight(to_tsvector('simple', coalesce(title, '')), 'A')
                    || setweight(to_tsvector('simple', coalesce(subtitle, '')), 'B')
                    || setweight(to_tsvector('simple', coalesce(entity_label, '')), 'B')
                    || setweight(to_tsvector('simple', coalesce(kind, '')), 'C')
                    || setweight(to_tsvector('simple', coalesce(status, '')), 'C')
                    || setweight(to_tsvector('simple', coalesce(language, '')), 'C')
                    || setweight(to_tsvector('simple', coalesce(metadata->>'summary', '')), 'C')
                    || setweight(to_tsvector('simple', coalesce(author_id, '')), 'D')
                    || setweight(to_tsvector('simple', coalesce(approver_id, '')), 'D')
                ) STORED,

            CONSTRAINT wealth_library_index_source_unique
                UNIQUE (source_table, source_id, organization_id)
        )
        """,
    )

    # ── Indexes ───────────────────────────────────────────────────
    # 1. GIN over the generated tsvector — full-text search
    op.execute(
        "CREATE INDEX wli_search_vector_gin "
        "ON wealth_library_index USING gin (search_vector)",
    )

    # 2-3. Trigram GIN for fuzzy matching of titles and entity labels
    op.execute(
        "CREATE INDEX wli_title_trgm "
        "ON wealth_library_index USING gin (title gin_trgm_ops)",
    )
    op.execute(
        "CREATE INDEX wli_entity_label_trgm "
        "ON wealth_library_index USING gin (entity_label gin_trgm_ops)",
    )

    # 4. GIN over folder_path text[] — supports `&&` (overlap) and
    #    `@>` (contains) operators for "show me everything under
    #    this folder branch" queries.
    op.execute(
        "CREATE INDEX wli_folder_path_gin "
        "ON wealth_library_index USING gin (folder_path)",
    )

    # 5. Composite B-tree on the FIRST element of folder_path
    #    (the L1 group). 5x faster than GIN for the common
    #    "all children of one root group" query.
    op.execute(
        "CREATE INDEX wli_folder_root_btree "
        "ON wealth_library_index ((folder_path[1]), organization_id, created_at DESC)",
    )

    # 6. Composite B-tree for filter queries (kind + status combined
    #    with org and recency).
    op.execute(
        "CREATE INDEX wli_org_kind_status_created "
        "ON wealth_library_index (organization_id, kind, status, created_at DESC)",
    )

    # 7. Index on the source FK for fast self-heal worker scans
    op.execute(
        "CREATE INDEX wli_source_lookup "
        "ON wealth_library_index (source_table, source_id)",
    )

    # ── RLS ───────────────────────────────────────────────────────
    op.execute("ALTER TABLE wealth_library_index ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE wealth_library_index FORCE ROW LEVEL SECURITY")

    # The subselect wrapper around current_setting() is CRITICAL for
    # performance — without it, current_setting() evaluates per-row
    # and the index plan loses 1000x speed. See CLAUDE.md §Critical
    # Rules and tenancy/middleware.py module docstring.
    op.execute(
        """
        CREATE POLICY org_isolation ON wealth_library_index
        USING (
            organization_id = (SELECT current_setting('app.current_organization_id')::uuid)
        )
        """,
    )


def downgrade() -> None:
    # Order matters — drop policy before table; indexes are dropped
    # automatically with the table.
    op.execute("DROP POLICY IF EXISTS org_isolation ON wealth_library_index")
    op.execute("DROP TABLE IF EXISTS wealth_library_index")

    # NOTE: pg_trgm extension is intentionally NOT dropped on
    # downgrade. Other tables may use it in the future and dropping
    # an extension is destructive at the database level.
