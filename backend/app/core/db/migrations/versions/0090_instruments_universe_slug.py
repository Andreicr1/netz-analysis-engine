"""Add immutable slug column to instruments_universe.

Phase 1.1 of the Wealth Library sprint
(docs/superpowers/specs/2026-04-08-wealth-library.md §4.6).

The Wealth Library /library/due-diligence/by-fund/<slug>/v<version>
URLs require a stable, URL-safe identifier per instrument. Renaming
a fund must NOT change its slug — every IC e-mail, Slack share,
exported PDF and audit log carries URLs that would otherwise break
silently. Trade-off explicitly accepted in the spec: a fund renamed
in 2027 still resolves under the slug derived from its 2026 name.

This migration:

  1. Adds the ``slug text`` column on ``instruments_universe``.
  2. Creates a ``slugify`` helper (PL/pgSQL pure, no extensions
     required) that lowercases, accent-folds and replaces non-
     alphanumerics with hyphens.
  3. Creates a BEFORE INSERT trigger that generates the slug,
     handling collisions with numeric suffixes (-2, -3, ...).
  4. The trigger ALSO fires on UPDATE OF name but **does not** mutate
     slug — it emits a NOTICE if name changed (audit-friendly) and
     enforces immutability via NEW.slug := OLD.slug.
  5. Backfills existing rows in a single DO block (idempotent).
  6. After backfill, sets slug NOT NULL and UNIQUE.

Note on global vs tenant scope: ``instruments_universe`` is the
global catalogue (no RLS, no organization_id). The slug therefore
needs to be globally unique. The trigger collision-handling appends
``-2``, ``-3`` etc. until a free slug is found.

Revision ID: 0090_instruments_universe_slug
Revises: 0089_wealth_library_index
Create Date: 2026-04-08 15:30:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0090_instruments_universe_slug"
down_revision: str | None = "0089_wealth_library_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. Add the column (nullable for now — backfill before NOT NULL) ──
    op.execute("ALTER TABLE instruments_universe ADD COLUMN IF NOT EXISTS slug text")

    # ── 2. Helper: slugify(input text) -> text ──
    # IMMUTABLE so we can reuse it inside the BEFORE INSERT trigger
    # without locking concerns. Pure PL/pgSQL — no unaccent extension
    # dependency. Handles: lowercase, accent stripping (PT/EN coverage),
    # non-alphanumeric to single hyphen, leading/trailing hyphen trim.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION slugify(input text)
        RETURNS text
        LANGUAGE plpgsql
        IMMUTABLE
        AS $$
        DECLARE
            s text;
        BEGIN
            IF input IS NULL OR length(input) = 0 THEN
                RETURN 'untitled';
            END IF;

            -- Lower-case
            s := lower(input);

            -- Accent folding (PT + EN coverage). translate() is the
            -- fastest available approach without an extension; the
            -- character set covers acute, grave, circumflex, tilde,
            -- diaeresis on a/e/i/o/u and the cedilla.
            s := translate(
                s,
                'aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN',
                'aaaaaeeeeiiiiooooouuuucnaaaaaeeeeiiiiooooouuuucn'
            );
            s := translate(
                s,
                E'\u00e1\u00e0\u00e2\u00e3\u00e4\u00e9\u00e8\u00ea\u00eb\u00ed\u00ec\u00ee\u00ef\u00f3\u00f2\u00f4\u00f5\u00f6\u00fa\u00f9\u00fb\u00fc\u00e7\u00f1\u00c1\u00c0\u00c2\u00c3\u00c4\u00c9\u00c8\u00ca\u00cb\u00cd\u00cc\u00ce\u00cf\u00d3\u00d2\u00d4\u00d5\u00d6\u00da\u00d9\u00db\u00dc\u00c7\u00d1',
                'aaaaaeeeeiiiiooooouuuucnaaaaaeeeeiiiiooooouuuucn'
            );

            -- Replace any run of non-[a-z0-9] with a single hyphen
            s := regexp_replace(s, '[^a-z0-9]+', '-', 'g');

            -- Trim leading and trailing hyphens
            s := trim(both '-' from s);

            -- Empty after stripping (e.g. all-symbol input) -> fallback
            IF length(s) = 0 THEN
                RETURN 'untitled';
            END IF;

            RETURN s;
        END;
        $$;
        """,
    )

    # ── 3. Trigger function for instruments_universe ──
    # Handles INSERT (generate slug, handle collisions) and
    # UPDATE OF name (emit NOTICE, enforce immutability).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION instruments_universe_set_slug()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            base_slug text;
            candidate text;
            suffix    int := 1;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                -- Generate a fresh slug from the name. If the caller
                -- provided one explicitly, slugify it anyway so the
                -- format is normalised.
                IF NEW.slug IS NOT NULL AND length(NEW.slug) > 0 THEN
                    base_slug := slugify(NEW.slug);
                ELSE
                    base_slug := slugify(NEW.name);
                END IF;

                candidate := base_slug;

                -- Collision check — append numeric suffix if needed
                WHILE EXISTS (
                    SELECT 1 FROM instruments_universe WHERE slug = candidate
                ) LOOP
                    suffix := suffix + 1;
                    candidate := base_slug || '-' || suffix;
                END LOOP;

                NEW.slug := candidate;
                RETURN NEW;
            END IF;

            IF TG_OP = 'UPDATE' THEN
                -- Slug is IMMUTABLE — preserve the old value even
                -- when the name changes. Emit a NOTICE so devs see
                -- the rename in logs without breaking URL stability.
                IF NEW.name IS DISTINCT FROM OLD.name THEN
                    RAISE NOTICE
                        'instruments_universe.name changed from % to % but slug remains immutable: %',
                        OLD.name, NEW.name, OLD.slug;
                END IF;
                NEW.slug := OLD.slug;
                RETURN NEW;
            END IF;

            RETURN NEW;
        END;
        $$;
        """,
    )

    # ── 4. Attach the trigger ──
    # BEFORE INSERT generates the slug.
    # BEFORE UPDATE OF name preserves slug + emits NOTICE on rename.
    op.execute("DROP TRIGGER IF EXISTS instruments_universe_slug_insert ON instruments_universe")
    op.execute(
        """
        CREATE TRIGGER instruments_universe_slug_insert
        BEFORE INSERT ON instruments_universe
        FOR EACH ROW
        EXECUTE FUNCTION instruments_universe_set_slug();
        """,
    )

    op.execute("DROP TRIGGER IF EXISTS instruments_universe_slug_update ON instruments_universe")
    op.execute(
        """
        CREATE TRIGGER instruments_universe_slug_update
        BEFORE UPDATE OF name ON instruments_universe
        FOR EACH ROW
        WHEN (NEW.name IS DISTINCT FROM OLD.name)
        EXECUTE FUNCTION instruments_universe_set_slug();
        """,
    )

    # ── 5. Backfill existing rows ──
    # Idempotent: processes only rows where slug is currently NULL.
    # Safe to re-run if the migration is partially rolled back.
    op.execute(
        """
        DO $$
        DECLARE
            rec       record;
            base_slug text;
            candidate text;
            suffix    int;
        BEGIN
            FOR rec IN
                SELECT instrument_id, name
                FROM instruments_universe
                WHERE slug IS NULL
                ORDER BY instrument_id
            LOOP
                base_slug := slugify(rec.name);
                candidate := base_slug;
                suffix := 1;
                WHILE EXISTS (
                    SELECT 1 FROM instruments_universe WHERE slug = candidate
                ) LOOP
                    suffix := suffix + 1;
                    candidate := base_slug || '-' || suffix;
                END LOOP;
                UPDATE instruments_universe
                SET slug = candidate
                WHERE instrument_id = rec.instrument_id;
            END LOOP;
        END
        $$;
        """,
    )

    # ── 6. Lock in the constraints after backfill ──
    op.execute("ALTER TABLE instruments_universe ALTER COLUMN slug SET NOT NULL")
    op.execute(
        "ALTER TABLE instruments_universe "
        "ADD CONSTRAINT instruments_universe_slug_unique UNIQUE (slug)",
    )


def downgrade() -> None:
    # Drop in reverse order of dependencies
    op.execute("DROP TRIGGER IF EXISTS instruments_universe_slug_update ON instruments_universe")
    op.execute("DROP TRIGGER IF EXISTS instruments_universe_slug_insert ON instruments_universe")
    op.execute("DROP FUNCTION IF EXISTS instruments_universe_set_slug()")
    op.execute(
        "ALTER TABLE instruments_universe "
        "DROP CONSTRAINT IF EXISTS instruments_universe_slug_unique",
    )
    op.execute("ALTER TABLE instruments_universe DROP COLUMN IF EXISTS slug")

    # NOTE: slugify() function is intentionally NOT dropped on
    # downgrade because future migrations or other tables may rely
    # on it. It is a pure helper with no side effects.
